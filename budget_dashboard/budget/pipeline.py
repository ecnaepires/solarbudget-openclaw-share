from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from adapters import detect_adapter, get_adapter
from budget.contract_schema import (
    CONTRACT_SCHEMA_VERSION,
    REQUIRED_CONTRACT_COLUMNS,
    ContractSchemaError,
)
from financial_model import (
    apply_dc_ac_ratio,
    calculate_inverter_quantity,
    calculate_module_count,
    mw_to_kwp,
)


@dataclass
class BudgetInputs:
    mwp_ac: float
    dc_ac_ratio: float
    module_wp: float
    inverter_kw: float
    module_price_com_bdi_per_kwp: float
    inverter_price_com_bdi: float
    module_price_sem_bdi_per_kwp: float = 0.0
    inverter_price_sem_bdi: float = 0.0
    additional_capex: float = 0.0
    opex_pct_capex: float = 0.02
    productivity_kwh_kwp_year: float = 1350.0
    energy_tariff_rs_kwh: float = 0.85
    ppp_investor_share_pct: float = 0.70


def _resolve_contract_path(contract_path: str | Path) -> Path:
    path = Path(contract_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Contract file not found: {path}")
    return path


def get_contract_cache_token(contract_path: str | Path) -> str:
    path = _resolve_contract_path(contract_path)
    mtime = path.stat().st_mtime_ns
    return f"{path}|{mtime}"


def _read_contract_file(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, encoding="utf-8-sig")
    if suffix in {".xlsx", ".xls"}:
        workbook = pd.ExcelFile(path)
        target_sheet = "displayed_data" if "displayed_data" in workbook.sheet_names else workbook.sheet_names[0]
        return pd.read_excel(workbook, sheet_name=target_sheet)
    raise ValueError(f"Unsupported contract format: {suffix}")


@st.cache_data(show_spinner=False)
def _load_contract_dataframe_cached(path_str: str, cache_token: str) -> pd.DataFrame:
    del cache_token  # only for cache invalidation on file mtime changes
    return _read_contract_file(Path(path_str))


def _validate_contract_schema(
    df: pd.DataFrame, contract_path: Path, adapter_name: str | None = None,
) -> None:
    from budget.contract_schema import get_required_columns_for_adapter

    actual_columns = [str(col) for col in df.columns]
    required = get_required_columns_for_adapter(adapter_name)
    if not required:
        return  # Skip validation for auto/config-driven adapters
    missing = [col for col in required if col not in actual_columns]
    if missing:
        raise ContractSchemaError(
            missing_columns=missing,
            actual_columns=actual_columns,
            required_columns=required,
            contract_path=str(contract_path),
            schema_version=CONTRACT_SCHEMA_VERSION,
        )


def load_contract_dataframe(
    contract_path: str | Path,
    validate_schema: bool = True,
    adapter_name: str | None = None,
) -> pd.DataFrame:
    path = _resolve_contract_path(contract_path)
    cache_token = get_contract_cache_token(path)
    df = _load_contract_dataframe_cached(str(path), cache_token)
    if validate_schema:
        _validate_contract_schema(df, path, adapter_name=adapter_name)
    return df


def read_contract_dataframe_raw(contract_path: str | Path) -> pd.DataFrame:
    return load_contract_dataframe(contract_path, validate_schema=False)


@st.cache_data(show_spinner=False)
def _standardize_with_adapter_cached(
    df: pd.DataFrame,
    adapter_name: str,
    cache_token: str,
) -> pd.DataFrame:
    del cache_token  # ensures invalidation by contract file updates
    adapter = get_adapter(adapter_name)
    return adapter.adapt(df)


def standardize_with_adapter(
    df: pd.DataFrame,
    adapter_name: str = "celesc",
    cache_token: str = "",
) -> pd.DataFrame:
    standardized = _standardize_with_adapter_cached(df, adapter_name, cache_token)
    if standardized.empty:
        return standardized
    required = {"municipio", "uc", "consumer_class", "reference_date", "consumption_kwh"}
    missing = required - set(standardized.columns)
    if missing:
        raise ValueError(f"Adapter output missing required columns: {sorted(missing)}")
    return standardized


def compute_consumption_totals_by_class(standardized_df: pd.DataFrame) -> dict[str, float]:
    if standardized_df is None or standardized_df.empty:
        return {"B3": 0.0, "IP": 0.0, "A4": 0.0, "OUTROS": 0.0, "TOTAL": 0.0}

    grouped = standardized_df.groupby("consumer_class", dropna=False)["consumption_kwh"].sum()
    b3 = float(grouped.get("B3", 0.0))
    ip = float(grouped.get("IP", 0.0))
    a4 = float(grouped.get("A4", 0.0))
    outros = float(grouped.get("OUTROS", 0.0))
    total = b3 + ip + a4 + outros
    return {"B3": b3, "IP": ip, "A4": a4, "OUTROS": outros, "TOTAL": total}


def _expected_month_labels(max_reference: pd.Timestamp, expected_months: int) -> list[str]:
    if pd.isna(max_reference):
        max_reference = pd.Timestamp.today().replace(day=1)
    labels = []
    current = max_reference.replace(day=1)
    for _ in range(int(expected_months)):
        labels.append(current.strftime("%Y-%m"))
        current = current - pd.DateOffset(months=1)
    return sorted(set(labels))


def _build_data_quality_report_core(
    standardized_df: pd.DataFrame,
    expected_months: int = 13,
    top_n: int = 200,
) -> dict[str, Any]:
    if standardized_df is None or standardized_df.empty:
        return {
            "expected_months": int(expected_months),
            "unique_ucs": 0,
            "months_available": [],
            "month_count": 0,
            "missing_reference_count": 0,
            "missing_reference_examples": [],
            "null_zero_stats_by_class": [],
            "missing_references_list": [],
            "ucs_with_missing_months": [],
            "ucs_all_zero_kwh": [],
            "critical_messages": ["Contrato vazio apos adaptacao."],
            "is_critical": True,
        }

    local = standardized_df.copy()
    local["reference_date"] = pd.to_datetime(local.get("reference_date"), errors="coerce")
    if "reference_month" not in local.columns:
        local["reference_month"] = local["reference_date"].dt.strftime("%Y-%m")
    local["reference_month"] = local["reference_month"].astype(str).replace("NaT", "").replace("nan", "")

    months_available = sorted({m for m in local["reference_month"].tolist() if str(m).strip()})
    missing_ref_mask = local["reference_date"].isna()
    missing_ref_count = int(missing_ref_mask.sum())

    missing_examples = []
    if missing_ref_count > 0:
        cols = [col for col in ["municipio", "uc", "consumer_class", "source_file"] if col in local.columns]
        if cols:
            missing_examples = (
                local.loc[missing_ref_mask, cols]
                .drop_duplicates()
                .head(top_n)
                .to_dict(orient="records")
            )

    stats_rows = []
    for klass in ["B3", "IP", "A4"]:
        subset = local[local["consumer_class"] == klass]
        total_rows = int(len(subset))
        if total_rows == 0:
            stats_rows.append(
                {
                    "consumer_class": klass,
                    "rows": 0,
                    "null_kwh_rows": 0,
                    "zero_or_negative_kwh_rows": 0,
                    "null_kwh_pct": 0.0,
                    "zero_or_negative_kwh_pct": 0.0,
                }
            )
            continue

        null_rows = int(subset["consumption_kwh"].isna().sum())
        zero_rows = int((subset["consumption_kwh"].fillna(0.0) <= 0).sum())
        stats_rows.append(
            {
                "consumer_class": klass,
                "rows": total_rows,
                "null_kwh_rows": null_rows,
                "zero_or_negative_kwh_rows": zero_rows,
                "null_kwh_pct": null_rows / total_rows,
                "zero_or_negative_kwh_pct": zero_rows / total_rows,
            }
        )

    max_ref = local["reference_date"].max()
    expected_labels = _expected_month_labels(max_ref, expected_months=expected_months)
    expected_set = set(expected_labels)

    uc_missing_rows = []
    zero_uc_rows = []
    for uc, group in local.groupby("uc", dropna=False):
        municipio = str(group["municipio"].iloc[0]) if "municipio" in group.columns else ""
        consumer_class = str(group["consumer_class"].iloc[0]) if "consumer_class" in group.columns else ""

        uc_months = {m for m in group["reference_month"].tolist() if str(m).strip()}
        missing_for_uc = sorted(expected_set - uc_months)
        if missing_for_uc:
            uc_missing_rows.append(
                {
                    "uc": str(uc),
                    "municipio": municipio,
                    "consumer_class": consumer_class,
                    "months_present_count": len(uc_months),
                    "missing_months_count": len(missing_for_uc),
                    "missing_months": ", ".join(missing_for_uc[:24]),
                }
            )

        series = pd.to_numeric(group["consumption_kwh"], errors="coerce")
        if bool((series.fillna(0.0) <= 0).all()):
            zero_uc_rows.append(
                {
                    "uc": str(uc),
                    "municipio": municipio,
                    "consumer_class": consumer_class,
                    "rows": int(len(group)),
                    "total_kwh": float(series.fillna(0.0).sum()),
                }
            )

    uc_missing_rows = sorted(uc_missing_rows, key=lambda row: row["missing_months_count"], reverse=True)[:top_n]
    zero_uc_rows = sorted(zero_uc_rows, key=lambda row: row["rows"], reverse=True)[:top_n]

    missing_refs_table = []
    if missing_ref_count > 0:
        cols = [col for col in ["municipio", "uc", "consumer_class", "source_file"] if col in local.columns]
        if cols:
            missing_refs_table = (
                local.loc[missing_ref_mask, cols]
                .drop_duplicates()
                .head(top_n)
                .to_dict(orient="records")
            )

    critical_messages: list[str] = []
    unique_ucs = int(local["uc"].nunique()) if "uc" in local.columns else 0
    if unique_ucs == 0:
        critical_messages.append("Nenhuma UC valida encontrada.")
    if len(months_available) < int(expected_months):
        critical_messages.append(
            f"Meses disponiveis ({len(months_available)}) abaixo do esperado ({expected_months})."
        )
    if missing_ref_count > 0:
        critical_messages.append(f"Existem {missing_ref_count} linhas sem referencia valida.")

    total_rows = int(len(local))
    nonpositive_rows = int((pd.to_numeric(local["consumption_kwh"], errors="coerce").fillna(0.0) <= 0).sum())
    if total_rows > 0 and (nonpositive_rows / total_rows) > 0.30:
        critical_messages.append("Mais de 30% das linhas estao com kWh nulo/zero/negativo.")
    if len(zero_uc_rows) > 0:
        critical_messages.append(f"Existem {len(zero_uc_rows)} UCs com kWh zerado em todos os registros.")

    return {
        "expected_months": int(expected_months),
        "expected_month_labels": expected_labels,
        "unique_ucs": unique_ucs,
        "months_available": months_available,
        "month_count": len(months_available),
        "missing_reference_count": missing_ref_count,
        "missing_reference_examples": missing_examples,
        "null_zero_stats_by_class": stats_rows,
        "missing_references_list": missing_refs_table,
        "ucs_with_missing_months": uc_missing_rows,
        "ucs_all_zero_kwh": zero_uc_rows,
        "critical_messages": critical_messages,
        "is_critical": bool(critical_messages),
    }


@st.cache_data(show_spinner=False)
def _build_data_quality_report_cached(
    standardized_df: pd.DataFrame,
    expected_months: int,
    cache_token: str,
    top_n: int,
) -> dict[str, Any]:
    del cache_token  # only for cache invalidation
    return _build_data_quality_report_core(standardized_df, expected_months=expected_months, top_n=top_n)


def build_data_quality_report(
    standardized_df: pd.DataFrame,
    expected_months: int = 13,
    cache_token: str = "",
    top_n: int = 200,
) -> dict[str, Any]:
    return _build_data_quality_report_cached(
        standardized_df=standardized_df,
        expected_months=int(expected_months),
        cache_token=cache_token,
        top_n=int(top_n),
    )


def compute_budget_metrics(standardized_df: pd.DataFrame, inputs: BudgetInputs) -> dict[str, Any]:
    ac_kwp = mw_to_kwp(float(inputs.mwp_ac))
    dc_kwp = apply_dc_ac_ratio(ac_kwp, float(inputs.dc_ac_ratio))
    module_count = calculate_module_count(dc_kwp, float(inputs.module_wp))
    inverter_qty = calculate_inverter_quantity(ac_kwp, float(inputs.inverter_kw))

    modules_capex_com = dc_kwp * float(inputs.module_price_com_bdi_per_kwp)
    inverters_capex_com = inverter_qty * float(inputs.inverter_price_com_bdi)
    total_capex_com = modules_capex_com + inverters_capex_com + float(inputs.additional_capex)

    modules_capex_sem = dc_kwp * float(inputs.module_price_sem_bdi_per_kwp)
    inverters_capex_sem = inverter_qty * float(inputs.inverter_price_sem_bdi)
    total_capex_sem = modules_capex_sem + inverters_capex_sem + float(inputs.additional_capex)

    annual_opex = total_capex_com * float(inputs.opex_pct_capex)
    annual_generation_kwh = dc_kwp * float(inputs.productivity_kwh_kwp_year)
    class_totals = compute_consumption_totals_by_class(standardized_df)
    annual_consumption_kwh = class_totals["TOTAL"]

    annual_offset_kwh = (
        min(annual_generation_kwh, annual_consumption_kwh)
        if annual_consumption_kwh > 0
        else annual_generation_kwh
    )
    annual_gross_savings = annual_offset_kwh * float(inputs.energy_tariff_rs_kwh)

    ppp_share = min(max(float(inputs.ppp_investor_share_pct), 0.0), 1.0)
    annual_ppp_investor_revenue = annual_gross_savings * ppp_share
    annual_ppp_customer_savings = annual_gross_savings - annual_ppp_investor_revenue
    annual_project_cashflow = annual_ppp_investor_revenue - annual_opex
    simple_payback_years = total_capex_com / annual_project_cashflow if annual_project_cashflow > 0 else None

    return {
        "inputs": asdict(inputs),
        "consumption_by_class_kwh": class_totals,
        "sizing": {
            "ac_kwp": ac_kwp,
            "dc_kwp": dc_kwp,
            "module_count": module_count,
            "inverter_qty": inverter_qty,
        },
        "capex_sem_bdi": {
            "modules": modules_capex_sem,
            "inverters": inverters_capex_sem,
            "additional": float(inputs.additional_capex),
            "total": total_capex_sem,
        },
        "capex_com_bdi": {
            "modules": modules_capex_com,
            "inverters": inverters_capex_com,
            "additional": float(inputs.additional_capex),
            "total": total_capex_com,
        },
        "opex": {
            "annual_opex": annual_opex,
            "opex_pct_capex": float(inputs.opex_pct_capex),
        },
        "ppp": {
            "annual_generation_kwh": annual_generation_kwh,
            "annual_consumption_kwh": annual_consumption_kwh,
            "annual_offset_kwh": annual_offset_kwh,
            "annual_gross_savings": annual_gross_savings,
            "investor_share_pct": ppp_share,
            "annual_ppp_investor_revenue": annual_ppp_investor_revenue,
            "annual_ppp_customer_savings": annual_ppp_customer_savings,
            "annual_project_cashflow": annual_project_cashflow,
            "simple_payback_years": simple_payback_years,
        },
    }


def build_budget_pipeline(
    contract_path: str | Path,
    adapter_name: str,
    inputs: BudgetInputs,
    expected_months: int = 13,
) -> dict[str, Any]:
    adapter_requested = str(adapter_name or "").strip().lower()
    raw_df = load_contract_dataframe(
        contract_path, validate_schema=True, adapter_name=adapter_requested,
    )
    cache_token = get_contract_cache_token(contract_path)
    adapter_detection = None
    adapter_used = adapter_requested
    if adapter_requested in {"", "auto"}:
        adapter_detection = detect_adapter(raw_df, outputs_info=None)
        if adapter_detection.get("is_confident") and adapter_detection.get("adapter"):
            adapter_used = str(adapter_detection["adapter"])
        else:
            raise ValueError(
                "AUTO adapter nao conseguiu detectar com confianca. "
                "Escolha manualmente CELESC/ENEL/CPFL."
            )

    standardized_df = standardize_with_adapter(
        raw_df,
        adapter_name=adapter_used,
        cache_token=f"{cache_token}|{adapter_used}",
    )
    quality = build_data_quality_report(
        standardized_df,
        expected_months=expected_months,
        cache_token=f"{cache_token}|{adapter_used}|quality",
        top_n=200,
    )
    metrics = compute_budget_metrics(standardized_df, inputs)
    return {
        "raw_rows": int(len(raw_df)),
        "standardized_rows": int(len(standardized_df)),
        "standardized_df": standardized_df,
        "quality": quality,
        "metrics": metrics,
        "adapter_requested": adapter_requested,
        "adapter_used": adapter_used,
        "adapter_detection": adapter_detection,
    }

