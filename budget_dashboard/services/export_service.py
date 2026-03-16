"""Extraction export and analytics functions."""
from __future__ import annotations

import importlib
import re
import sys
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st
from openpyxl import load_workbook

from config import DEFAULT_DEMAND_RATE_BRL_KW, DEFAULT_ENERGY_RATE_BRL_KWH, DEFAULT_PEAK_THRESHOLD_PCT
from excel_engine import apply_dynamic_totals
from ui.helpers import build_excel_bytes_from_frames
from ui.numeric_utils import (
    _add_estimated_cost_columns,
    _build_itens_fatura_detail_table,
    _build_monthly_financials,
    _build_municipio_profile,
    _build_inefficiency_uc_table,
    _build_savings_opportunities,
    _normalize_header_name,
    _parse_reference_series,
    _safe_div,
    _sum_or_zero,
    _to_numeric_flexible,
)


def _latest_extraction_payload(setup: dict) -> tuple[pd.DataFrame, list[dict], dict]:
    def _normalize_records(records_value: Any) -> list[dict]:
        if isinstance(records_value, pd.DataFrame):
            return records_value.to_dict(orient="records")
        if isinstance(records_value, list):
            return [dict(item) for item in records_value if isinstance(item, dict)]
        return []

    raw_df = st.session_state.get("latest_extracted_raw_df")
    records = st.session_state.get("latest_extracted_records")

    if isinstance(raw_df, pd.DataFrame):
        raw_frame = raw_df.copy()
    else:
        raw_frame = pd.DataFrame()

    records_list = _normalize_records(records)

    bridge_raw = None
    bridge_stats = st.session_state.get("pdf_bridge_stats", {})
    if isinstance(bridge_stats, dict):
        bridge_raw = bridge_stats.get("master_df")
    bridge_records = _normalize_records(st.session_state.get("pdf_bridge_records"))

    if raw_frame.empty and isinstance(bridge_raw, pd.DataFrame) and not bridge_raw.empty:
        raw_frame = bridge_raw.copy()
        if bridge_records:
            records_list = bridge_records
    elif not records_list and bridge_records:
        records_list = bridge_records

    resumo = {
        "generated_at": datetime.now().isoformat(),
        "project_name": str(setup.get("project_name", "") or ""),
        "municipio": str(setup.get("city", "") or ""),
        "state": str(setup.get("state", "") or ""),
        "source_file": str(setup.get("extraction_source_file", "") or ""),
        "source_scenario": str(setup.get("extraction_scenario", "") or ""),
        "mwp_ac": float(setup.get("mwp_ac", 0.0) or 0.0),
    }
    return raw_frame, records_list, resumo


def _reorder_original_extract_columns(df: pd.DataFrame) -> pd.DataFrame:
    preferred = [
        "municipio", "referencia", "reference_date", "uc", "nome", "endereco",
        "categoria", "tipo_fornecimento", "kwh_total_te", "demanda_contratada_kw",
        "demanda_hp_kw", "demanda_fhp_kw", "consumo_hp_kwh", "consumo_fhp_kwh",
        "total_fatura_rs", "itens_fatura_total_valor_rs", "itens_fatura_energia_valor_rs",
        "itens_fatura_energia_kwh", "itens_fatura_preco_medio_rs_kwh", "dif_demanda",
        "extra_demand_kw", "estimated_energy_cost_rs", "estimated_extra_demand_cost_rs",
        "actual_total_cost_rs", "estimated_total_cost_rs", "total_cost_rs", "cost_source",
        "pdf_source", "page_first_seen", "audit_pdf_pages", "itens_fatura_json", "uploaded_file",
    ]
    front = [col for col in preferred if col in df.columns]
    remainder = [col for col in df.columns if col not in front]
    return df[front + remainder]


def _build_original_extraction_frames(raw_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    if raw_df.empty:
        empty = pd.DataFrame()
        return {
            "displayed_data": empty,
            "monthly_kwh": empty,
            "monthly_cost": empty,
            "category_kwh": empty,
            "top_uc_kwh": empty,
            "inefficiencies": empty,
            "itens_fatura": empty,
            "benchmark": empty,
            "summary": empty,
            "savings_tips": pd.DataFrame({"savings_opportunity": ["Sem dados de extração para análise."]}),
        }

    displayed_df = raw_df.copy()
    for audit_col in ("page_first_seen", "audit_pdf_pages"):
        if audit_col not in displayed_df.columns:
            displayed_df[audit_col] = ""

    _pdf_name_col = next((c for c in ["uploaded_file", "pdf_source"] if c in displayed_df.columns), None)
    if _pdf_name_col is not None or "page_first_seen" in displayed_df.columns:
        def _make_pdf_ref(row):
            raw_name = str(row[_pdf_name_col] or "") if _pdf_name_col else ""
            stem = Path(raw_name).stem if raw_name and raw_name not in ("nan", "") else ""
            try:
                page = int(float(str(row.get("page_first_seen", 0) or 0)))
            except (ValueError, TypeError):
                page = 0
            if stem and page > 0:
                return f"{stem} page: {page}"
            return stem or (f"page: {page}" if page > 0 else "")
        _pdf_ref_series = displayed_df.apply(_make_pdf_ref, axis=1)
        displayed_df["pdf_source"] = _pdf_ref_series
        displayed_df["audit_pdf_pages"] = _pdf_ref_series

    if "reference_date" not in displayed_df.columns:
        if "referencia" in displayed_df.columns:
            displayed_df["reference_date"] = _parse_reference_series(displayed_df["referencia"])
        else:
            displayed_df["reference_date"] = pd.NaT
    else:
        displayed_df["reference_date"] = pd.to_datetime(displayed_df["reference_date"], errors="coerce")

    energy_rate_rs_kwh = DEFAULT_ENERGY_RATE_BRL_KWH
    extra_demand_rate_rs_kw = DEFAULT_DEMAND_RATE_BRL_KW
    peak_threshold_pct = DEFAULT_PEAK_THRESHOLD_PCT

    enriched_df = _add_estimated_cost_columns(
        displayed_df, energy_rate_rs_kwh=energy_rate_rs_kwh, extra_demand_rate_rs_kw=extra_demand_rate_rs_kw,
    )
    displayed_export = _reorder_original_extract_columns(enriched_df)

    monthly_kwh_df = pd.DataFrame()
    if {"reference_date", "municipio", "kwh_total_te"}.issubset(enriched_df.columns):
        monthly_kwh_df = (
            enriched_df.dropna(subset=["reference_date"])
            .groupby(["municipio", "reference_date"], as_index=False)["kwh_total_te"]
            .sum().sort_values("reference_date")
        )

    monthly_financial_df = _build_monthly_financials(enriched_df)

    category_kwh_df = pd.DataFrame()
    if {"categoria", "kwh_total_te"}.issubset(enriched_df.columns):
        category_kwh_df = (
            enriched_df.groupby("categoria", dropna=False, as_index=False)["kwh_total_te"]
            .sum().sort_values("kwh_total_te", ascending=False)
        )

    top_uc_df = pd.DataFrame()
    if {"uc", "municipio", "kwh_total_te"}.issubset(enriched_df.columns):
        top_uc_df = (
            enriched_df.groupby(["municipio", "uc"], as_index=False)["kwh_total_te"]
            .sum().sort_values("kwh_total_te", ascending=False).head(15)
        )
        top_uc_df["uc_label"] = top_uc_df["municipio"].astype(str) + " | " + top_uc_df["uc"].astype(str)

    itens_detail_df = _build_itens_fatura_detail_table(enriched_df)
    municipio_profile_df = _build_municipio_profile(enriched_df)
    inefficiency_uc_df = _build_inefficiency_uc_table(enriched_df, extra_demand_rate_rs_kw=extra_demand_rate_rs_kw)

    total_cost_rs = _sum_or_zero(enriched_df["total_cost_rs"]) if "total_cost_rs" in enriched_df else 0.0
    actual_cost_rs = _sum_or_zero(enriched_df["actual_total_cost_rs"]) if "actual_total_cost_rs" in enriched_df else 0.0
    total_kwh = _sum_or_zero(enriched_df["kwh_total_te"]) if "kwh_total_te" in enriched_df else 0.0
    itens_energy_valor_rs = _sum_or_zero(enriched_df["itens_fatura_energia_valor_rs"]) if "itens_fatura_energia_valor_rs" in enriched_df else 0.0
    itens_energy_kwh = _sum_or_zero(enriched_df["itens_fatura_energia_kwh"]) if "itens_fatura_energia_kwh" in enriched_df else 0.0

    avg_cost_per_kwh_rs = _safe_div(itens_energy_valor_rs, itens_energy_kwh)
    avg_cost_source_label = "Itens da Fatura (Valor/Quantidade)"
    if pd.isna(avg_cost_per_kwh_rs):
        avg_cost_per_kwh_rs = _safe_div(total_cost_rs, total_kwh)
        avg_cost_source_label = "Total Cost / Total kWh"

    actual_cost_share_pct = _safe_div(actual_cost_rs, total_cost_rs) * 100.0

    if not monthly_financial_df.empty:
        latest_row = monthly_financial_df.iloc[-1]
        latest_ref = latest_row["reference_date"]
        latest_ref_label = latest_ref.strftime("%m/%Y")
        total_monthly_cost_rs = float(latest_row["total_cost_rs"])
        ytd_spending_rs = _sum_or_zero(
            monthly_financial_df.loc[monthly_financial_df["reference_date"].dt.year == latest_ref.year, "total_cost_rs"]
        )
    else:
        latest_ref_label = "N/A"
        total_monthly_cost_rs = total_cost_rs
        ytd_spending_rs = total_cost_rs

    consumo_hp_total = _sum_or_zero(enriched_df["consumo_hp_kwh"]) if "consumo_hp_kwh" in enriched_df else 0.0
    consumo_fhp_total = _sum_or_zero(enriched_df["consumo_fhp_kwh"]) if "consumo_fhp_kwh" in enriched_df else 0.0
    peak_share_pct = _safe_div(consumo_hp_total, consumo_hp_total + consumo_fhp_total) * 100.0
    extra_demand_kw = _sum_or_zero(enriched_df["extra_demand_kw"]) if "extra_demand_kw" in enriched_df else 0.0
    extra_demand_cost_rs = extra_demand_kw * float(extra_demand_rate_rs_kw)
    avg_municipio_kwh = municipio_profile_df["total_kwh"].mean() if not municipio_profile_df.empty else float("nan")
    selected_vs_avg_kwh_pct = (
        (_safe_div(total_kwh, avg_municipio_kwh) - 1.0) * 100.0 if not pd.isna(avg_municipio_kwh) else float("nan")
    )
    tips = _build_savings_opportunities(
        peak_share_pct=peak_share_pct,
        peak_threshold_pct=peak_threshold_pct,
        extra_demand_kw=extra_demand_kw,
        extra_demand_cost_rs=extra_demand_cost_rs,
        selected_vs_avg_kwh_pct=selected_vs_avg_kwh_pct,
        avg_cost_per_kwh_rs=avg_cost_per_kwh_rs,
        energy_rate_rs_kwh=float(energy_rate_rs_kwh),
    )

    summary_df = pd.DataFrame(
        [
            {"metric": "total_monthly_cost_rs", "value": total_monthly_cost_rs, "reference": latest_ref_label},
            {"metric": "ytd_spending_rs", "value": ytd_spending_rs, "reference": latest_ref_label},
            {"metric": "avg_cost_per_kwh_rs", "value": avg_cost_per_kwh_rs, "reference": "filtered period"},
            {"metric": "avg_cost_per_kwh_source", "value": avg_cost_source_label, "reference": "calculation method"},
            {"metric": "itens_fatura_energia_valor_rs", "value": itens_energy_valor_rs, "reference": "filtered period"},
            {"metric": "itens_fatura_energia_kwh", "value": itens_energy_kwh, "reference": "filtered period"},
            {"metric": "actual_cost_rs", "value": actual_cost_rs, "reference": "filtered period"},
            {"metric": "actual_cost_share_pct", "value": actual_cost_share_pct, "reference": "filtered period"},
            {"metric": "peak_share_pct", "value": peak_share_pct, "reference": "filtered period"},
            {"metric": "extra_demand_kw", "value": extra_demand_kw, "reference": "filtered period"},
        ]
    )

    tips_df = pd.DataFrame({"savings_opportunity": tips})
    return {
        "displayed_data": displayed_export,
        "monthly_kwh": monthly_kwh_df,
        "monthly_cost": monthly_financial_df,
        "category_kwh": category_kwh_df,
        "top_uc_kwh": top_uc_df,
        "inefficiencies": inefficiency_uc_df,
        "itens_fatura": itens_detail_df,
        "benchmark": municipio_profile_df,
        "summary": summary_df,
        "savings_tips": tips_df,
    }


def _sanitize_export_name_like_streamlit(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or "Sunergies_app"


def _resolve_streamlit_template_path(extraction_root: Path) -> str:
    root = Path(extraction_root).resolve()
    candidates = [
        root / "templates" / "final_template_all_in_one.xlsx",
        root / "final_template_all_in_one.xlsx",
        root / "PALHOÇA_PROJETO_final_model_filledCORRECTVERSION.xlsx",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        "Nao foi possivel localizar o template final do streamlit_app.py "
        f"em {root} (templates/final_template_all_in_one.xlsx)."
    )


def _import_run_full_study_from_root(extraction_root: Path):
    root = Path(extraction_root).resolve()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    module_name = "run_full_study"
    existing = sys.modules.get(module_name)
    if existing is not None:
        module_file = str(getattr(existing, "__file__", "") or "")
        if module_file:
            try:
                module_path = Path(module_file).resolve()
                if hasattr(module_path, "is_relative_to"):
                    under_root = module_path.is_relative_to(root)
                else:
                    under_root = str(module_path).lower().startswith(str(root).lower())
            except Exception:
                under_root = False
            if not under_root:
                sys.modules.pop(module_name, None)

    return importlib.import_module(module_name)


def _build_streamlit_exact_template_export_bytes(raw_df: pd.DataFrame, extraction_root: Path) -> bytes:
    if raw_df.empty:
        raise ValueError("Sem dados para exportar no formato do streamlit_app.py.")

    displayed_df = raw_df.copy()
    for audit_col in ("page_first_seen", "audit_pdf_pages"):
        if audit_col not in displayed_df.columns:
            displayed_df[audit_col] = ""

    _pdf_name_col = next((c for c in ["uploaded_file", "pdf_source"] if c in displayed_df.columns), None)
    if _pdf_name_col is not None or "page_first_seen" in displayed_df.columns:
        def _make_pdf_ref(row):
            raw_name = str(row[_pdf_name_col] or "") if _pdf_name_col else ""
            stem = Path(raw_name).stem if raw_name and raw_name not in ("nan", "") else ""
            try:
                page = int(float(str(row.get("page_first_seen", 0) or 0)))
            except (ValueError, TypeError):
                page = 0
            if stem and page > 0:
                return f"{stem} page: {page}"
            return stem or (f"page: {page}" if page > 0 else "")
        _pdf_ref_series = displayed_df.apply(_make_pdf_ref, axis=1)
        displayed_df["pdf_source"] = _pdf_ref_series
        displayed_df["audit_pdf_pages"] = _pdf_ref_series

    if "reference_date" not in displayed_df.columns:
        if "referencia" in displayed_df.columns:
            displayed_df["reference_date"] = _parse_reference_series(displayed_df["referencia"])
        else:
            displayed_df["reference_date"] = pd.NaT
    else:
        displayed_df["reference_date"] = pd.to_datetime(displayed_df["reference_date"], errors="coerce")

    displayed_df = _add_estimated_cost_columns(displayed_df, energy_rate_rs_kwh=0.85, extra_demand_rate_rs_kw=42.0)

    municipio_options = sorted(
        displayed_df["municipio"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()
    ) if "municipio" in displayed_df.columns else []
    if len(municipio_options) == 1:
        municipio_export_name = municipio_options[0]
    else:
        municipio_export_name = "Sunergies_app"
    municipio_export_name = _sanitize_export_name_like_streamlit(municipio_export_name)

    template_path = _resolve_streamlit_template_path(extraction_root)
    run_full_study = _import_run_full_study_from_root(extraction_root)
    export_to_final_workbook = getattr(run_full_study, "export_to_final_workbook", None)
    if not callable(export_to_final_workbook):
        raise AttributeError("run_full_study.export_to_final_workbook nao encontrado no projeto de extracao.")

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_xlsx = export_to_final_workbook(
            master=displayed_df.copy(),
            out_dir=tmp_dir,
            municipio=municipio_export_name,
            template_xlsx=template_path,
            fill_dimensionamento=True,
        )
        output_path = Path(output_xlsx)
        if not output_path.exists():
            raise FileNotFoundError(f"Exportacao final nao gerou arquivo: {output_path}")
        workbook = load_workbook(output_path, data_only=False)
        apply_dynamic_totals(workbook)
        workbook.save(output_path)
        return output_path.read_bytes()


def exportar_extracao(
    raw_df: Optional[pd.DataFrame],
    records: list[dict],
    resumo: dict,
    extraction_root: Optional[Path] = None,
) -> bytes:
    from services.extraction_bridge_service import default_extraction_root

    template_compatible = _is_template_export_compatible_raw_df(raw_df)
    if template_compatible:
        root_candidate = extraction_root
        if root_candidate is None:
            root_candidate = Path(
                st.session_state.get("extraction_root_path", str(default_extraction_root()))
            ).expanduser()
        if not root_candidate.exists():
            root_candidate = default_extraction_root()
        try:
            return _build_streamlit_exact_template_export_bytes(raw_df.copy(), extraction_root=Path(root_candidate))
        except Exception as exc:
            st.warning(
                "Nao foi possivel gerar o Excel extraido no formato do template "
                f"(fallback aplicado): {exc}"
            )
    elif isinstance(raw_df, pd.DataFrame) and not raw_df.empty:
        st.warning(
            "Excel extraido atual nao possui colunas completas para o template "
            "(ex.: categoria/uc/referencia/kwh). Gerado fallback tabular."
        )

    frames: Dict[str, pd.DataFrame] = {}
    if isinstance(raw_df, pd.DataFrame):
        frames.update(_build_original_extraction_frames(raw_df.copy()))
        raw_out = raw_df.copy()
        for audit_col in ("page_first_seen", "audit_pdf_pages"):
            if audit_col not in raw_out.columns:
                raw_out[audit_col] = ""
        frames["extraido_raw"] = raw_out
    frames["resumo_extracao"] = pd.DataFrame([resumo])
    if records:
        frames["dimensionamento"] = pd.DataFrame(records)
    return build_excel_bytes_from_frames(frames)


def _is_template_export_compatible_raw_df(df: Optional[pd.DataFrame]) -> bool:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return False

    normalized = {_normalize_header_name(col) for col in df.columns}
    has_categoria = "categoria" in normalized
    has_uc = "uc" in normalized
    has_referencia = "referencia" in normalized or "reference_date" in normalized
    has_kwh = "kwh_total_te" in normalized or "itens_fatura_energia_kwh" in normalized
    return has_categoria and has_uc and has_referencia and has_kwh
