"""Tariff inference and autofill from invoice data."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from services.extraction_bridge_service import parse_streamlit_export_dataframe
from ui.helpers import format_brl, parse_brl_value
from ui.numeric_utils import (
    _coalesce_numeric_series,
    _to_numeric_flexible,
    _weighted_average_positive,
)


def infer_tariffs_from_invoice_raw(raw_df: pd.DataFrame) -> dict:
    if not isinstance(raw_df, pd.DataFrame) or raw_df.empty:
        return {}

    local = raw_df.copy()

    categoria_series = local.get("categoria", pd.Series("", index=local.index))
    subgrupo_series = local.get("subgrupo", pd.Series("", index=local.index))
    classif_series = local.get("classificacao_uc", pd.Series("", index=local.index))
    grupo_series = local.get("grupo_tensao", pd.Series("", index=local.index))
    local["_categoria_text"] = (
        categoria_series.fillna("").astype(str) + " "
        + subgrupo_series.fillna("").astype(str) + " "
        + classif_series.fillna("").astype(str) + " "
        + grupo_series.fillna("").astype(str)
    ).str.upper()

    blended_price = _coalesce_numeric_series(local, [
        "itens_fatura_preco_medio_rs_kwh", "itens_fatura_preco_all_in_blended_rs_kwh",
        "itens_fatura_preco_all_in_fhp_rs_kwh", "itens_fatura_preco_all_in_hp_rs_kwh",
    ])
    energia_valor = _coalesce_numeric_series(local, ["itens_fatura_energia_valor_rs", "total_fatura_rs"])
    energia_kwh = _coalesce_numeric_series(local, ["itens_fatura_energia_kwh", "kwh_total_te"])
    derived_blended = pd.Series(float("nan"), index=local.index, dtype="float64")
    valid_derived = energia_valor.notna() & energia_kwh.notna() & (energia_valor > 0) & (energia_kwh > 0)
    derived_blended.loc[valid_derived] = energia_valor.loc[valid_derived] / energia_kwh.loc[valid_derived]
    blended_price = blended_price.fillna(derived_blended)

    b3_ip_weight = _coalesce_numeric_series(local, ["kwh_b3_ip", "itens_fatura_energia_kwh", "kwh_total_te"])

    a4_hp_price = _coalesce_numeric_series(local, [
        "itens_fatura_preco_all_in_hp_rs_kwh", "itens_fatura_preco_all_in_blended_rs_kwh", "itens_fatura_preco_medio_rs_kwh",
    ])
    a4_hp_price = a4_hp_price.fillna(blended_price)
    a4_hp_weight = _coalesce_numeric_series(local, ["kwh_a4_p_te", "consumo_hp_kwh", "itens_fatura_energia_kwh"])

    a4_fhp_price = _coalesce_numeric_series(local, [
        "itens_fatura_preco_all_in_fhp_rs_kwh", "itens_fatura_preco_all_in_blended_rs_kwh", "itens_fatura_preco_medio_rs_kwh",
    ])
    a4_fhp_price = a4_fhp_price.fillna(blended_price)
    a4_fhp_weight = _coalesce_numeric_series(local, ["kwh_a4_fp_te", "consumo_fhp_kwh", "itens_fatura_energia_kwh"])

    b3_mask = local["_categoria_text"].str.contains(r"\bB3\b", na=False)
    ip_mask = local["_categoria_text"].str.contains(r"\bIP\b|\bB4A\b|\bB4B\b", na=False)
    a4_mask = local["_categoria_text"].str.contains(r"\bA4\b", na=False)

    tariff_b3 = _weighted_average_positive(blended_price[b3_mask], b3_ip_weight[b3_mask])
    tariff_b4a = _weighted_average_positive(blended_price[ip_mask], b3_ip_weight[ip_mask])
    tariff_a4_hp = _weighted_average_positive(a4_hp_price[a4_mask], a4_hp_weight[a4_mask])
    tariff_a4_fhp = _weighted_average_positive(a4_fhp_price[a4_mask], a4_fhp_weight[a4_mask])

    result = {}
    if tariff_b3 is not None:
        result["dim_tariff_b3"] = float(tariff_b3)
    if tariff_b4a is not None:
        result["dim_tariff_b4a"] = float(tariff_b4a)
    if tariff_a4_hp is not None:
        result["dim_tariff_a4_hp"] = float(tariff_a4_hp)
    if tariff_a4_fhp is not None:
        result["dim_tariff_a4_fhp"] = float(tariff_a4_fhp)
    return result


def apply_pending_tariff_autofill() -> None:
    pending = st.session_state.get("pending_tariff_autofill")
    if not isinstance(pending, dict) or not pending:
        return

    for key, value in pending.items():
        if value is None:
            continue
        numeric = float(value)
        st.session_state[key] = numeric
        st.session_state[f"{key}_raw"] = format_brl(numeric)

    st.session_state["last_tariff_autofill"] = pending
    st.session_state["tariff_autofill_applied"] = True
    st.session_state.pop("pending_tariff_autofill", None)


def recalculate_pdf_records_after_tariff_autofill(
    *,
    months_to_use: int,
    hsp: float,
    performance_ratio: float,
    days_per_month: float,
    a4_hp_factor: float,
    capex_brl_per_mwp: float,
    tariff_b3_rs_kwh: float | None,
    tariff_b4a_rs_kwh: float | None,
    tariff_a4_hp_rs_kwh: float | None,
    tariff_a4_fhp_rs_kwh: float | None,
) -> bool:
    current_records = st.session_state.get("pdf_bridge_records")
    if not isinstance(current_records, list) or not current_records:
        return False

    needs_recalc = any(
        isinstance(record, dict)
        and record.get("payback_months") is None
        and bool(record.get("payback_needs_tariff_input"))
        for record in current_records
    )
    if not needs_recalc:
        return False

    raw_df = None
    pdf_stats = st.session_state.get("pdf_bridge_stats", {})
    if isinstance(pdf_stats, dict):
        master_df = pdf_stats.get("master_df")
        if isinstance(master_df, pd.DataFrame) and not master_df.empty:
            raw_df = master_df
    if raw_df is None:
        latest_raw_df = st.session_state.get("latest_extracted_raw_df")
        if isinstance(latest_raw_df, pd.DataFrame) and not latest_raw_df.empty:
            raw_df = latest_raw_df
    if raw_df is None:
        return False

    source_label = ""
    first_record = current_records[0] if current_records else {}
    if isinstance(first_record, dict):
        source_label = str(first_record.get("source_file") or "").strip()
    if not source_label:
        files_processed = int(pdf_stats.get("files_processed", 0) or 0) if isinstance(pdf_stats, dict) else 0
        source_label = f"PDF upload ({files_processed} file(s))"

    recalculated_records = parse_streamlit_export_dataframe(
        raw_df,
        source_label=source_label,
        months_to_use=months_to_use,
        hsp=hsp,
        performance_ratio=performance_ratio,
        days_per_month=days_per_month,
        a4_hp_factor=a4_hp_factor,
        capex_brl_per_mwp=capex_brl_per_mwp,
        tariff_b3_rs_kwh=tariff_b3_rs_kwh,
        tariff_b4a_rs_kwh=tariff_b4a_rs_kwh,
        tariff_a4_hp_rs_kwh=tariff_a4_hp_rs_kwh,
        tariff_a4_fhp_rs_kwh=tariff_a4_fhp_rs_kwh,
    )
    if not recalculated_records:
        return False

    st.session_state["pdf_bridge_records"] = recalculated_records
    st.session_state["latest_extracted_records"] = recalculated_records
    return True
