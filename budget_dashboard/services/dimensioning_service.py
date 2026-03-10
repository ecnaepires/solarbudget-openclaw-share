"""Dimensioning and budget generation (orcamentar) logic."""
from __future__ import annotations

from copy import deepcopy
from typing import Optional

import pandas as pd

from ui.helpers import add_abbreviation_meanings
from ui.numeric_utils import _normalize_header_name


def dimensionar(
    records: list[dict],
    raw_df: Optional[pd.DataFrame] = None,
    *,
    preferred_municipio: str = "",
    months_to_use: int = 13,
) -> dict:
    if not records:
        raise ValueError("Nao foi possivel dimensionar: sem registros extraidos.")

    preferred = str(preferred_municipio or "").strip().lower()
    selected_record = None
    if preferred:
        for rec in records:
            municipio = str(rec.get("municipio", "") or "").strip().lower()
            if municipio and municipio == preferred:
                selected_record = rec
                break

    warnings: list[str] = []
    if selected_record is None:
        selected_record = max(records, key=lambda rec: float(rec.get("mwp", 0.0) or 0.0))
        if len(records) > 1:
            warnings.append(add_abbreviation_meanings("Multiplos cenarios detectados; usado o de maior MWp."))

    if selected_record.get("payback_needs_tariff_input"):
        warnings.append("Tarifa ausente -> payback indisponivel/estimado.")

    if isinstance(raw_df, pd.DataFrame) and not raw_df.empty:
        normalized_columns = {_normalize_header_name(col): col for col in raw_df.columns}

        if "itens_fatura_energia_kwh" not in normalized_columns:
            warnings.append(add_abbreviation_meanings("Fonte kWh fallback (nao veio de Itens da Fatura)."))

        tipo_cols = [
            col_name for norm_name, col_name in normalized_columns.items()
            if "tipo_fornecimento" in norm_name or "tipo_fornecimento_uc" in norm_name
        ]
        tipo_ok = False
        for col_name in tipo_cols:
            series = raw_df[col_name].fillna("").astype(str).str.strip()
            if series.ne("").any():
                tipo_ok = True
                break
        if not tipo_ok:
            warnings.append("Tipo fornecimento ausente.")

        categoria_col = normalized_columns.get("categoria")
        needs_review = False
        if categoria_col:
            categoria_series = raw_df[categoria_col].fillna("").astype(str).str.upper().str.strip()
            unknown_mask = categoria_series.isin({"", "OUTROS", "N/A", "NAN"})
            if bool(unknown_mask.any()):
                needs_review = True
                warnings.append("Categoria/fornecimento com deteccao incerta (needs_review).")
        else:
            needs_review = True
            warnings.append("Categoria ausente no extraido (needs_review).")

        ref_candidates = ["reference_date", "data_referencia", "referencia", "competencia", "mes_referencia"]
        ref_col = next((normalized_columns.get(_normalize_header_name(name)) for name in ref_candidates if normalized_columns.get(_normalize_header_name(name))), None)
        if ref_col:
            references = pd.to_datetime(raw_df[ref_col], errors="coerce", dayfirst=True)
            month_count = int(references.dropna().dt.to_period("M").nunique())
            if month_count < int(months_to_use):
                warnings.append(add_abbreviation_meanings("UC com meses faltantes -> zeros preenchidos."))
    else:
        needs_review = True
        warnings.append("Sem dataframe bruto para validacao detalhada (needs_review).")

    month_labels = list(selected_record.get("month_labels") or [])
    category_totals = dict(selected_record.get("consumo_medio_mensal_kwh") or {})
    selected_warnings = [str(msg) for msg in (selected_record.get("warnings") or []) if str(msg).strip()]
    warnings.extend(selected_warnings)

    return {
        "mwp_ac": float(selected_record.get("mwp", 0.0) or 0.0),
        "kwp_total": float(selected_record.get("kwp", 0.0) or 0.0),
        "category_totals": category_totals,
        "month_labels": month_labels,
        "selected_record": selected_record,
        "warnings": warnings,
        "needs_review": bool(any("needs_review" in str(msg).lower() for msg in warnings)),
    }


def orcamentar(
    project: dict,
    scenario_name: str,
    modules_catalog: list[dict],
    inverters_catalog: list[dict],
    excel_map: dict,
    *,
    mwp_ac: float,
    build_scenario_bundle_fn,
) -> dict:
    if float(mwp_ac) <= 0:
        raise ValueError("MWp invalido para orcamentacao.")

    local_project = deepcopy(project)
    local_project["setup"]["mwp_ac"] = float(mwp_ac)
    bundle = build_scenario_bundle_fn(local_project, scenario_name, modules_catalog, inverters_catalog, excel_map)
    from ui.helpers import write_budget_excel_bytes
    budget_xlsx_bytes = write_budget_excel_bytes(bundle["updates"])
    warnings = [str(msg) for msg in (bundle["sizing"].get("warnings") or []) if str(msg).strip()]
    return {
        "updates": bundle["updates"],
        "budget_xlsx_bytes": budget_xlsx_bytes,
        "totals": bundle["totals"],
        "warnings": warnings,
        "bundle": bundle,
    }
