"""Shared numeric/DataFrame utility functions — no Streamlit dependency."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import List

import pandas as pd

from adapters.base import MONTH_MAP
from ui.helpers import (
    EXTRACTION_NUMERIC_COLUMNS,
    add_abbreviation_meanings,
    format_brl,
    parse_brl_value,
)


def _normalize_header_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text


def _to_numeric_flexible(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().any():
        return numeric
    return series.apply(parse_brl_value)


def _coalesce_numeric_series(df: pd.DataFrame, candidate_cols: List[str]) -> pd.Series:
    if df.empty:
        return pd.Series(dtype="float64")

    def _normalize_col(col_name: str) -> str:
        text = unicodedata.normalize("NFKD", str(col_name or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return text.strip().lower()

    def _resolve_column(candidate: str):
        normalized_candidate = _normalize_col(candidate)
        exact = None
        contains = None
        for col in df.columns:
            normalized_col = _normalize_col(col)
            if normalized_col == normalized_candidate:
                exact = col
                break
            if contains is None and normalized_candidate and normalized_candidate in normalized_col:
                contains = col
        return exact if exact is not None else contains

    output = pd.Series(float("nan"), index=df.index, dtype="float64")
    for candidate in candidate_cols:
        resolved = _resolve_column(candidate)
        if resolved is None:
            continue
        parsed = _to_numeric_flexible(df[resolved])
        output = output.fillna(parsed)
    return output


def _weighted_average_positive(price: pd.Series, weight: pd.Series) -> float | None:
    if price.empty:
        return None

    p = pd.to_numeric(price, errors="coerce")
    w = pd.to_numeric(weight, errors="coerce")
    valid = p.notna() & (p > 0)

    if valid.any():
        valid_with_weight = valid & w.notna() & (w > 0)
        if valid_with_weight.any():
            denom = float(w[valid_with_weight].sum())
            if denom > 0:
                return float((p[valid_with_weight] * w[valid_with_weight]).sum() / denom)
        return float(p[valid].mean())

    return None


def _sum_or_zero(series: pd.Series) -> float:
    value = pd.to_numeric(series, errors="coerce").sum(min_count=1)
    if pd.isna(value):
        return 0.0
    return float(value)


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator is None or denominator == 0:
        return float("nan")
    return float(numerator) / float(denominator)


def _parse_reference_series(reference: pd.Series) -> pd.Series:
    refs = reference.fillna("").astype(str).str.strip()
    parsed = pd.to_datetime(refs, format="%m/%Y", errors="coerce")
    missing = parsed.isna()

    if missing.any():
        extracted = refs[missing].str.upper().str.extract(r"^(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)[/-](\d{2,4})$")
        month_num = extracted[0].map(MONTH_MAP)
        years = extracted[1]
        years = years.where(years.str.len() == 4, "20" + years)
        alt = pd.to_datetime(month_num + "/01/" + years, format="%m/%d/%Y", errors="coerce")
        parsed.loc[missing] = alt.values

    return parsed


def _add_estimated_cost_columns(df: pd.DataFrame, energy_rate_rs_kwh: float, extra_demand_rate_rs_kw: float) -> pd.DataFrame:
    out = df.copy()
    for col in EXTRACTION_NUMERIC_COLUMNS:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = _to_numeric_flexible(out[col]).fillna(0.0)

    out["extra_demand_kw"] = out["dif_demanda"].clip(lower=0.0)
    out["estimated_energy_cost_rs"] = out["kwh_total_te"] * float(energy_rate_rs_kwh)
    out["estimated_extra_demand_cost_rs"] = out["extra_demand_kw"] * float(extra_demand_rate_rs_kw)
    out["estimated_total_cost_rs"] = out["estimated_energy_cost_rs"] + out["estimated_extra_demand_cost_rs"]

    total_fatura = _to_numeric_flexible(out.get("total_fatura_rs", pd.Series(index=out.index, dtype="float64")))
    itens_total = _to_numeric_flexible(out.get("itens_fatura_total_valor_rs", pd.Series(index=out.index, dtype="float64")))
    mask_fatura = total_fatura.notna() & (total_fatura > 0)
    mask_itens = (~mask_fatura) & itens_total.notna() & (itens_total > 0)

    out["actual_total_cost_rs"] = total_fatura.where(mask_fatura, itens_total.where(mask_itens, pd.NA))
    out["total_cost_rs"] = out["actual_total_cost_rs"].where(
        out["actual_total_cost_rs"].notna() & (out["actual_total_cost_rs"] > 0),
        out["estimated_total_cost_rs"],
    )
    out["cost_source"] = "estimated"
    out.loc[mask_fatura, "cost_source"] = "actual_fatura"
    out.loc[mask_itens, "cost_source"] = "actual_itens"
    return out


def _build_monthly_financials(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["reference_date", "kwh_total_te", "extra_demand_kw", "total_cost_rs", "actual_total_cost_rs"]
    if df.empty or "reference_date" not in df.columns:
        return pd.DataFrame(columns=cols)

    temp = df.dropna(subset=["reference_date"]).copy()
    if temp.empty:
        return pd.DataFrame(columns=cols)

    monthly = (
        temp.groupby("reference_date", as_index=False)[["kwh_total_te", "extra_demand_kw", "total_cost_rs", "actual_total_cost_rs"]]
        .sum()
        .sort_values("reference_date")
    )
    return monthly


def _build_itens_fatura_detail_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "municipio", "reference_date", "referencia", "uc", "item",
        "quantidade", "preco_unitario_com_tributos_rs", "valor_rs", "uploaded_file",
    ]
    if df.empty or "itens_fatura_json" not in df.columns:
        return pd.DataFrame(columns=cols)

    rows: list[dict] = []
    for _, row in df.iterrows():
        raw = row.get("itens_fatura_json", "")
        if not raw:
            continue
        try:
            items = json.loads(raw)
        except Exception:
            continue
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "municipio": row.get("municipio", ""),
                    "reference_date": row.get("reference_date", pd.NaT),
                    "referencia": row.get("referencia", ""),
                    "uc": str(row.get("uc", "")),
                    "item": item.get("item", ""),
                    "quantidade": item.get("quantidade"),
                    "preco_unitario_com_tributos_rs": item.get("preco_unitario_com_tributos"),
                    "valor_rs": item.get("valor"),
                    "uploaded_file": row.get("uploaded_file", ""),
                }
            )

    if not rows:
        return pd.DataFrame(columns=cols)

    out = pd.DataFrame(rows)
    for col in ["quantidade", "preco_unitario_com_tributos_rs", "valor_rs"]:
        out[col] = _to_numeric_flexible(out[col])
    out["reference_date"] = pd.to_datetime(out["reference_date"], errors="coerce")
    return out[cols]


def _build_municipio_profile(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["municipio", "total_kwh", "total_cost_rs", "extra_demand_kw", "uc_count", "peak_share_pct", "avg_cost_per_kwh_rs"]
    if df.empty or "municipio" not in df.columns:
        return pd.DataFrame(columns=cols)

    temp = df.copy()
    for col in ["consumo_hp_kwh", "consumo_fhp_kwh", "kwh_total_te", "extra_demand_kw", "total_cost_rs"]:
        if col not in temp.columns:
            temp[col] = 0.0
        temp[col] = _to_numeric_flexible(temp[col]).fillna(0.0)
    if "uc" not in temp.columns:
        temp["uc"] = ""

    profile = (
        temp.groupby("municipio", as_index=False)
        .agg(
            total_kwh=("kwh_total_te", "sum"),
            total_cost_rs=("total_cost_rs", "sum"),
            extra_demand_kw=("extra_demand_kw", "sum"),
            uc_count=("uc", "nunique"),
            consumo_hp_kwh=("consumo_hp_kwh", "sum"),
            consumo_fhp_kwh=("consumo_fhp_kwh", "sum"),
        )
    )

    consumo_total = (profile["consumo_hp_kwh"] + profile["consumo_fhp_kwh"]).replace(0, float("nan"))
    profile["peak_share_pct"] = (profile["consumo_hp_kwh"] / consumo_total * 100.0).fillna(0.0)
    profile["avg_cost_per_kwh_rs"] = (profile["total_cost_rs"] / profile["total_kwh"].replace(0, float("nan"))).fillna(0.0)
    profile = profile.drop(columns=["consumo_hp_kwh", "consumo_fhp_kwh"]).sort_values("total_kwh", ascending=False)
    return profile[cols]


def _build_inefficiency_uc_table(df: pd.DataFrame, extra_demand_rate_rs_kw: float) -> pd.DataFrame:
    cols = ["municipio", "uc", "consumo_hp_kwh", "consumo_fhp_kwh", "peak_share_pct", "extra_demand_kw", "estimated_extra_demand_cost_rs"]
    if df.empty or "uc" not in df.columns or "municipio" not in df.columns:
        return pd.DataFrame(columns=cols)

    temp = df.copy()
    for col in ["consumo_hp_kwh", "consumo_fhp_kwh", "extra_demand_kw"]:
        if col not in temp.columns:
            temp[col] = 0.0
        temp[col] = _to_numeric_flexible(temp[col]).fillna(0.0)

    agg = (
        temp.groupby(["municipio", "uc"], as_index=False)
        .agg(
            consumo_hp_kwh=("consumo_hp_kwh", "sum"),
            consumo_fhp_kwh=("consumo_fhp_kwh", "sum"),
            extra_demand_kw=("extra_demand_kw", "sum"),
        )
    )
    total_a4 = (agg["consumo_hp_kwh"] + agg["consumo_fhp_kwh"]).replace(0, float("nan"))
    agg["peak_share_pct"] = (agg["consumo_hp_kwh"] / total_a4 * 100.0).fillna(0.0)
    agg["estimated_extra_demand_cost_rs"] = agg["extra_demand_kw"] * float(extra_demand_rate_rs_kw)
    agg = agg.sort_values(["estimated_extra_demand_cost_rs", "peak_share_pct"], ascending=[False, False])
    return agg[cols].head(25)


def _build_savings_opportunities(
    *,
    peak_share_pct: float,
    peak_threshold_pct: float,
    extra_demand_kw: float,
    extra_demand_cost_rs: float,
    selected_vs_avg_kwh_pct: float,
    avg_cost_per_kwh_rs: float,
    energy_rate_rs_kwh: float,
) -> list[str]:
    tips: list[str] = []
    if not pd.isna(peak_share_pct) and peak_share_pct > peak_threshold_pct:
        tips.append(
            f"Peak-hour consumption is {peak_share_pct:.1f}%. Shift discretionary loads outside peak to target <= {peak_threshold_pct:.0f}%."
        )
    if extra_demand_kw > 0:
        tips.append(
            f"Detected {extra_demand_kw:,.2f} kW of extra demand, adding about {format_brl(extra_demand_cost_rs)}. Review contracted demand and stagger equipment starts."
        )
    if not pd.isna(selected_vs_avg_kwh_pct) and selected_vs_avg_kwh_pct > 10:
        tips.append(
            add_abbreviation_meanings(
                f"Usage is {selected_vs_avg_kwh_pct:.1f}% above municipality average benchmark. Prioritize audits for top UCs by kWh."
            )
        )
    if not pd.isna(avg_cost_per_kwh_rs) and avg_cost_per_kwh_rs > (energy_rate_rs_kwh * 1.15):
        tips.append(
            add_abbreviation_meanings(
                "Average cost per kWh is materially above base tariff. Focus on demand overruns and corrections."
            )
        )
    if not tips:
        tips.append(add_abbreviation_meanings("Current profile is close to benchmark. Keep monthly monitoring and focus on top 5 UCs."))
    return tips


def _merge_warning_messages(*warning_groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in warning_groups:
        for message in group or []:
            text = str(message or "").strip()
            if not text:
                continue
            if text in seen:
                continue
            seen.add(text)
            merged.append(text)
    return merged
