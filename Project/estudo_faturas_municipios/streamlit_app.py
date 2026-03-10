from __future__ import annotations

import io
import json
import os
import re
import tempfile
import time
import hashlib
from datetime import date

import pandas as pd
import pdfplumber
import plotly.express as px
import streamlit as st
from openpyxl import load_workbook

from fatura_engine.audit import build_audit_pdf_pages
from fatura_engine.extractors import extract_pdf


MONTH_MAP = {
    "JAN": "01",
    "FEV": "02",
    "MAR": "03",
    "ABR": "04",
    "MAI": "05",
    "JUN": "06",
    "JUL": "07",
    "AGO": "08",
    "SET": "09",
    "OUT": "10",
    "NOV": "11",
    "DEZ": "12",
}

NUMERIC_COLUMNS = [
    "kwh_total_te",
    "demanda_item",
    "dif_demanda",
    "demanda_contratada_kw",
    "demanda_hp_kw",
    "demanda_fhp_kw",
    "consumo_hp_kwh",
    "consumo_fhp_kwh",
    "total_fatura_rs",
    "itens_fatura_total_valor_rs",
    "itens_fatura_energia_valor_rs",
    "itens_fatura_energia_kwh",
    "itens_fatura_preco_medio_rs_kwh",
    "itens_fatura_preco_all_in_fhp_rs_kwh",
    "itens_fatura_preco_all_in_hp_rs_kwh",
    "itens_fatura_preco_all_in_blended_rs_kwh",
]


def resolve_default_template_path() -> str:
    candidates = [
        os.path.join("templates", "final_template_all_in_one.xlsx"),
        "final_template_all_in_one.xlsx",
        "PALHOÃ‡A_PROJETO_final_model_filledCORRECTVERSION.xlsx",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


def sanitize_export_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or "Sunergies_app"


def sum_or_zero(series: pd.Series) -> float:
    value = pd.to_numeric(series, errors="coerce").sum(min_count=1)
    if pd.isna(value):
        return 0.0
    return float(value)


def safe_div(numerator: float, denominator: float) -> float:
    if denominator is None or denominator == 0:
        return float("nan")
    return float(numerator) / float(denominator)


def format_currency(value: float) -> str:
    if pd.isna(value):
        return "N/A"
    return f"R$ {value:,.2f}"


def format_number(value: float, suffix: str = "") -> str:
    if pd.isna(value):
        return "N/A"
    return f"{value:,.2f}{suffix}"


def infer_municipio(file_name: str, municipio_override: str) -> str:
    override = (municipio_override or "").strip()
    if override:
        return override

    stem = os.path.splitext(os.path.basename(file_name))[0]
    stem = re.sub(r"(?i)[_-]?faturas?.*$", "", stem)
    stem = re.sub(r"(?i)[_-]?invoice[s]?.*$", "", stem)
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return stem or "NAO INFORMADO"


def parse_reference_series(reference: pd.Series) -> pd.Series:
    refs = reference.fillna("").astype(str).str.strip()
    parsed = pd.to_datetime(refs, format="%m/%Y", errors="coerce")

    missing = parsed.isna()
    if missing.any():
        extracted = refs[missing].str.upper().str.extract(
            r"^(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)[/-](\d{2,4})$"
        )
        month_num = extracted[0].map(MONTH_MAP)
        years = extracted[1]
        years = years.where(years.str.len() == 4, "20" + years)
        alt = pd.to_datetime(month_num + "/01/" + years, format="%m/%d/%Y", errors="coerce")
        parsed.loc[missing] = alt.values

    return parsed


def dedupe_payloads_by_content(payloads: tuple[tuple[str, bytes], ...]) -> tuple[tuple[tuple[str, bytes], ...], list[str]]:
    if not payloads:
        return tuple(), []

    unique: list[tuple[str, bytes]] = []
    skipped_names: list[str] = []
    seen: dict[str, str] = {}
    for file_name, file_bytes in payloads:
        digest = hashlib.sha256(file_bytes).hexdigest()
        if digest in seen:
            skipped_names.append(file_name)
            continue
        seen[digest] = file_name
        unique.append((file_name, file_bytes))
    return tuple(unique), skipped_names


def build_extraction_cache_key(
    payloads: tuple[tuple[str, bytes], ...],
    expand_a4_historico: bool,
    municipio_override: str,
) -> str:
    h = hashlib.sha256()
    h.update(b"v1")
    h.update(str(bool(expand_a4_historico)).encode("utf-8"))
    h.update(str(municipio_override or "").strip().lower().encode("utf-8"))
    for file_name, file_bytes in payloads:
        h.update(str(file_name).encode("utf-8", errors="ignore"))
        h.update(hashlib.sha256(file_bytes).digest())
    return h.hexdigest()


@st.cache_data(show_spinner=False)
def get_pdf_page_count(file_name: str, file_bytes: bytes) -> int:
    _ = file_name  # keep signature stable for caching by file identity
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            return int(len(pdf.pages))
    except Exception:
        return 0


def build_progress_message(
    pct: int,
    completed_files: int,
    total_files: int,
    pages_done: int,
    total_pages: int,
    current_file: str = "",
    current_file_page: int | None = None,
    current_file_total_pages: int | None = None,
) -> str:
    message = (
        f"{pct}% | PDFs {completed_files}/{total_files} | "
        f"Pages {pages_done}/{total_pages}"
    )
    if current_file:
        if (
            current_file_page is not None
            and current_file_total_pages is not None
            and current_file_total_pages > 0
        ):
            message += f" | Reading {current_file_page}/{current_file_total_pages}: {current_file}"
        else:
            message += f" | Reading: {current_file}"
    return message


def set_progress_bar(progress_bar, pct: int, text: str) -> None:
    try:
        progress_bar.progress(pct, text=text)
    except TypeError:
        progress_bar.progress(pct)


def compute_progress_pct(
    completed_files: int,
    total_files: int,
    current_file_pages_done: int = 0,
    current_file_total_pages: int = 0,
) -> int:
    if total_files <= 0:
        return 0

    fraction = 0.0
    if current_file_total_pages > 0:
        fraction = min(1.0, max(0.0, float(current_file_pages_done) / float(current_file_total_pages)))

    exact = ((float(completed_files) + fraction) / float(total_files)) * 100.0
    return max(0, min(100, int(exact)))


def render_progress(
    progress_bar,
    status_box,
    pct: int,
    completed_files: int,
    total_files: int,
    pages_done: int,
    total_pages: int,
    current_file: str = "",
    current_file_page: int | None = None,
    current_file_total_pages: int | None = None,
) -> None:
    set_progress_bar(progress_bar, pct, f"{pct}%")
    status_box.write(
        build_progress_message(
            pct=pct,
            completed_files=completed_files,
            total_files=total_files,
            pages_done=pages_done,
            total_pages=total_pages,
            current_file=current_file,
            current_file_page=current_file_page,
            current_file_total_pages=current_file_total_pages,
        )
    )


def grow_progress(
    progress_bar,
    status_box,
    current_pct: int,
    target_pct: int,
    completed_files: int,
    total_files: int,
    pages_done: int,
    total_pages: int,
    current_file: str = "",
    current_file_page: int | None = None,
    current_file_total_pages: int | None = None,
) -> int:
    target = max(current_pct, min(100, int(target_pct)))
    if target == current_pct:
        render_progress(
            progress_bar=progress_bar,
            status_box=status_box,
            pct=current_pct,
            completed_files=completed_files,
            total_files=total_files,
            pages_done=pages_done,
            total_pages=total_pages,
            current_file=current_file,
            current_file_page=current_file_page,
            current_file_total_pages=current_file_total_pages,
        )
        return current_pct

    for pct in range(current_pct + 1, target + 1):
        render_progress(
            progress_bar=progress_bar,
            status_box=status_box,
            pct=pct,
            completed_files=completed_files,
            total_files=total_files,
            pages_done=pages_done,
            total_pages=total_pages,
            current_file=current_file,
            current_file_page=current_file_page,
            current_file_total_pages=current_file_total_pages,
        )
        time.sleep(0.004)

    return target


def extract_single_pdf(
    file_name: str,
    file_bytes: bytes,
    expand_a4_historico: bool,
    municipio_override: str,
    progress_callback=None,
) -> pd.DataFrame:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(file_bytes)
        tmp_path = tmp_file.name

    try:
        extracted = extract_pdf(
            tmp_path,
            expand_a4_historico=expand_a4_historico,
            progress_callback=progress_callback,
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if extracted is None or extracted.empty:
        return pd.DataFrame()

    df = extracted.copy()
    # Keep audit/source traces tied to the uploaded filename, not the temp file used during parsing.
    df["pdf_source"] = os.path.splitext(os.path.basename(file_name))[0]
    df["uploaded_file"] = file_name
    df["municipio"] = infer_municipio(file_name, municipio_override)

    if "uc" in df.columns:
        df["uc"] = df["uc"].astype(str)

    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def process_uploaded_pdfs(
    payloads: tuple[tuple[str, bytes], ...],
    expand_a4_historico: bool,
    municipio_override: str,
    progress_bar,
    status_box,
) -> tuple[pd.DataFrame, int]:
    payloads, _ = dedupe_payloads_by_content(payloads)
    if not payloads:
        set_progress_bar(progress_bar, 0, "0%")
        status_box.write("No files provided.")
        return pd.DataFrame(), 0

    total_files = len(payloads)
    page_counts = [get_pdf_page_count(file_name, file_bytes) for file_name, file_bytes in payloads]
    total_pages = int(sum(page_counts))
    total_pages_display = max(total_pages, 0)
    frames: list[pd.DataFrame] = []

    render_progress(
        progress_bar=progress_bar,
        status_box=status_box,
        pct=0,
        completed_files=0,
        total_files=total_files,
        pages_done=0,
        total_pages=total_pages_display,
    )
    current_pct = 0
    completed_files = 0
    pages_done = 0

    for index, ((file_name, file_bytes), file_pages) in enumerate(zip(payloads, page_counts), start=1):
        current_file_pages_done = 0
        current_file_total_pages = file_pages

        if current_file_total_pages > 0:
            render_progress(
                progress_bar=progress_bar,
                status_box=status_box,
                pct=current_pct,
                completed_files=completed_files,
                total_files=total_files,
                pages_done=pages_done,
                total_pages=total_pages_display,
                current_file=file_name,
                current_file_page=0,
                current_file_total_pages=current_file_total_pages,
            )

        def on_page_processed(page_number: int, total_in_pdf: int) -> None:
            nonlocal current_pct, current_file_pages_done, current_file_total_pages
            page_number = max(0, int(page_number))
            total_in_pdf = max(0, int(total_in_pdf))
            current_file_pages_done = max(current_file_pages_done, page_number)
            if total_in_pdf > 0:
                current_file_total_pages = total_in_pdf

            pages_so_far = pages_done + current_file_pages_done
            target_pct = compute_progress_pct(
                completed_files=completed_files,
                total_files=total_files,
                current_file_pages_done=current_file_pages_done,
                current_file_total_pages=max(current_file_total_pages, 1),
            )
            current_pct = grow_progress(
                progress_bar=progress_bar,
                status_box=status_box,
                current_pct=current_pct,
                target_pct=target_pct,
                completed_files=completed_files,
                total_files=total_files,
                pages_done=pages_so_far,
                total_pages=max(total_pages_display, pages_so_far),
                current_file=file_name,
                current_file_page=current_file_pages_done,
                current_file_total_pages=current_file_total_pages,
            )

        df = extract_single_pdf(
            file_name=file_name,
            file_bytes=file_bytes,
            expand_a4_historico=expand_a4_historico,
            municipio_override=municipio_override,
            progress_callback=on_page_processed,
        )
        if not df.empty:
            frames.append(df)

        file_pages_effective = max(file_pages, current_file_total_pages, current_file_pages_done)
        if file_pages_effective > file_pages:
            total_pages_display += file_pages_effective - file_pages

        pages_done += file_pages_effective
        completed_files = index

        target_pct = compute_progress_pct(completed_files=completed_files, total_files=total_files)
        current_pct = grow_progress(
            progress_bar=progress_bar,
            status_box=status_box,
            current_pct=current_pct,
            target_pct=target_pct,
            completed_files=completed_files,
            total_files=total_files,
            pages_done=pages_done,
            total_pages=total_pages_display,
            current_file=file_name,
            current_file_page=current_file_total_pages if current_file_total_pages > 0 else current_file_pages_done,
            current_file_total_pages=current_file_total_pages if current_file_total_pages > 0 else None,
        )

    if current_pct < 100:
        current_pct = grow_progress(
            progress_bar=progress_bar,
            status_box=status_box,
            current_pct=current_pct,
            target_pct=100,
            completed_files=total_files,
            total_files=total_files,
            pages_done=pages_done,
            total_pages=total_pages_display,
        )

    render_progress(
        progress_bar=progress_bar,
        status_box=status_box,
        pct=100,
        completed_files=total_files,
        total_files=total_files,
        pages_done=pages_done,
        total_pages=total_pages_display,
    )

    total_pages_processed = pages_done
    if not frames:
        return pd.DataFrame(), total_pages_processed

    master = pd.concat(frames, ignore_index=True)
    needed_for_audit = {"uc", "pdf_source", "page_first_seen"}
    if needed_for_audit.issubset(master.columns):
        audit_keys = ["uc", "referencia"] if {"uc", "referencia"}.issubset(master.columns) else ["uc"]
        audit_df = build_audit_pdf_pages(master, group_cols=audit_keys)
        if not audit_df.empty:
            master = (
                master.drop(columns=["audit_pdf_pages"], errors="ignore")
                .merge(audit_df, on=audit_keys, how="left")
            )

    if "referencia" in master.columns:
        master["reference_date"] = parse_reference_series(master["referencia"])
    else:
        master["reference_date"] = pd.NaT

    return master, total_pages_processed


def add_estimated_cost_columns(df: pd.DataFrame, energy_rate_rs_kwh: float, extra_demand_rate_rs_kw: float) -> pd.DataFrame:
    out = df.copy()

    for col in NUMERIC_COLUMNS:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    out["extra_demand_kw"] = out["dif_demanda"].clip(lower=0.0)
    out["estimated_energy_cost_rs"] = out["kwh_total_te"] * float(energy_rate_rs_kwh)
    out["estimated_extra_demand_cost_rs"] = out["extra_demand_kw"] * float(extra_demand_rate_rs_kw)
    out["estimated_total_cost_rs"] = out["estimated_energy_cost_rs"] + out["estimated_extra_demand_cost_rs"]

    total_fatura = pd.to_numeric(out.get("total_fatura_rs"), errors="coerce")
    itens_total = pd.to_numeric(out.get("itens_fatura_total_valor_rs"), errors="coerce")

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


def build_monthly_financials(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["reference_date", "kwh_total_te", "extra_demand_kw", "total_cost_rs", "actual_total_cost_rs"]
    if df.empty or "reference_date" not in df.columns:
        return pd.DataFrame(columns=cols)

    temp = df.dropna(subset=["reference_date"]).copy()
    if temp.empty:
        return pd.DataFrame(columns=cols)

    monthly = (
        temp.groupby("reference_date", as_index=False)[
            ["kwh_total_te", "extra_demand_kw", "total_cost_rs", "actual_total_cost_rs"]
        ]
        .sum()
        .sort_values("reference_date")
    )
    return monthly


def build_itens_fatura_detail_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "municipio",
        "reference_date",
        "referencia",
        "uc",
        "item",
        "quantidade",
        "preco_unitario_com_tributos_rs",
        "valor_rs",
        "uploaded_file",
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
    for c in ["quantidade", "preco_unitario_com_tributos_rs", "valor_rs"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    if "reference_date" in out.columns:
        out["reference_date"] = pd.to_datetime(out["reference_date"], errors="coerce")
    return out[cols]


def build_municipio_profile(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "municipio",
        "total_kwh",
        "total_cost_rs",
        "extra_demand_kw",
        "uc_count",
        "peak_share_pct",
        "avg_cost_per_kwh_rs",
    ]
    if df.empty or "municipio" not in df.columns:
        return pd.DataFrame(columns=cols)

    temp = df.copy()
    for col in ["consumo_hp_kwh", "consumo_fhp_kwh", "kwh_total_te", "extra_demand_kw", "total_cost_rs"]:
        if col not in temp.columns:
            temp[col] = 0.0
        temp[col] = pd.to_numeric(temp[col], errors="coerce").fillna(0.0)

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

    consumo_total = profile["consumo_hp_kwh"] + profile["consumo_fhp_kwh"]
    profile["peak_share_pct"] = (profile["consumo_hp_kwh"] / consumo_total.replace(0, pd.NA) * 100.0).fillna(0.0)
    profile["avg_cost_per_kwh_rs"] = (
        profile["total_cost_rs"] / profile["total_kwh"].replace(0, pd.NA)
    ).fillna(0.0)
    profile = profile.drop(columns=["consumo_hp_kwh", "consumo_fhp_kwh"])
    profile = profile.sort_values("total_kwh", ascending=False)

    return profile[cols]


def build_inefficiency_uc_table(df: pd.DataFrame, extra_demand_rate_rs_kw: float) -> pd.DataFrame:
    cols = [
        "municipio",
        "uc",
        "consumo_hp_kwh",
        "consumo_fhp_kwh",
        "peak_share_pct",
        "extra_demand_kw",
        "estimated_extra_demand_cost_rs",
    ]
    if df.empty or "uc" not in df.columns or "municipio" not in df.columns:
        return pd.DataFrame(columns=cols)

    temp = df.copy()
    for col in ["consumo_hp_kwh", "consumo_fhp_kwh", "extra_demand_kw"]:
        if col not in temp.columns:
            temp[col] = 0.0
        temp[col] = pd.to_numeric(temp[col], errors="coerce").fillna(0.0)

    agg = (
        temp.groupby(["municipio", "uc"], as_index=False)
        .agg(
            consumo_hp_kwh=("consumo_hp_kwh", "sum"),
            consumo_fhp_kwh=("consumo_fhp_kwh", "sum"),
            extra_demand_kw=("extra_demand_kw", "sum"),
        )
    )
    total_a4 = agg["consumo_hp_kwh"] + agg["consumo_fhp_kwh"]
    agg["peak_share_pct"] = (agg["consumo_hp_kwh"] / total_a4.replace(0, pd.NA) * 100.0).fillna(0.0)
    agg["estimated_extra_demand_cost_rs"] = agg["extra_demand_kw"] * float(extra_demand_rate_rs_kw)
    agg = agg.sort_values(["estimated_extra_demand_cost_rs", "peak_share_pct"], ascending=[False, False])

    return agg[cols].head(25)


def build_savings_opportunities(
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
            f"Detected {extra_demand_kw:,.2f} kW of extra demand, adding about {format_currency(extra_demand_cost_rs)}. "
            "Review contracted demand and stagger motor/equipment starts."
        )

    if not pd.isna(selected_vs_avg_kwh_pct) and selected_vs_avg_kwh_pct > 10:
        tips.append(
            f"Usage is {selected_vs_avg_kwh_pct:.1f}% above the municipality average benchmark. "
            "Prioritize audits for the top UCs by monthly kWh."
        )

    if not pd.isna(avg_cost_per_kwh_rs) and avg_cost_per_kwh_rs > (energy_rate_rs_kwh * 1.15):
        tips.append(
            "Average cost per kWh is materially above the base energy tariff. "
            "Focus on demand overruns and power-factor corrections where applicable."
        )

    if not tips:
        tips.append(
            "Current profile is close to benchmark. Keep monthly monitoring and target the top 5 UCs for continuous optimization."
        )

    return tips


def reorder_columns(df: pd.DataFrame) -> pd.DataFrame:
    preferred = [
        "municipio",
        "referencia",
        "reference_date",
        "uc",
        "nome",
        "endereco",
        "categoria",
        "tipo_fornecimento",
        "kwh_total_te",
        "demanda_contratada_kw",
        "demanda_hp_kw",
        "demanda_fhp_kw",
        "consumo_hp_kwh",
        "consumo_fhp_kwh",
        "total_fatura_rs",
        "itens_fatura_total_valor_rs",
        "itens_fatura_energia_valor_rs",
        "itens_fatura_energia_kwh",
        "itens_fatura_preco_medio_rs_kwh",
        "dif_demanda",
        "extra_demand_kw",
        "estimated_energy_cost_rs",
        "estimated_extra_demand_cost_rs",
        "actual_total_cost_rs",
        "estimated_total_cost_rs",
        "total_cost_rs",
        "cost_source",
        "pdf_source",
        "page_first_seen",
        "audit_pdf_pages",
        "itens_fatura_json",
        "uploaded_file",
    ]

    front = [col for col in preferred if col in df.columns]
    remainder = [col for col in df.columns if col not in front]
    return df[front + remainder]


def apply_date_filter(df: pd.DataFrame, date_range: tuple[date, date] | None) -> pd.DataFrame:
    if date_range is None or "reference_date" not in df.columns:
        return df

    start, end = date_range
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    return df[df["reference_date"].between(start_ts, end_ts, inclusive="both")]


@st.cache_data(show_spinner=False)
def build_excel_download(
    displayed_df: pd.DataFrame,
    monthly_kwh_df: pd.DataFrame,
    monthly_financial_df: pd.DataFrame,
    category_df: pd.DataFrame,
    top_uc_df: pd.DataFrame,
    inefficiency_uc_df: pd.DataFrame,
    itens_detail_df: pd.DataFrame,
    municipio_profile_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    tips_df: pd.DataFrame,
) -> bytes:
    output = io.BytesIO()

    export_displayed = displayed_df.copy()
    if "reference_date" in export_displayed.columns:
        export_displayed["reference_date"] = export_displayed["reference_date"].dt.strftime("%Y-%m-%d")

    export_monthly_kwh = monthly_kwh_df.copy()
    if "reference_date" in export_monthly_kwh.columns:
        export_monthly_kwh["reference_date"] = export_monthly_kwh["reference_date"].dt.strftime("%Y-%m-%d")

    export_monthly_financial = monthly_financial_df.copy()
    if "reference_date" in export_monthly_financial.columns:
        export_monthly_financial["reference_date"] = export_monthly_financial["reference_date"].dt.strftime("%Y-%m-%d")

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        export_displayed.to_excel(writer, sheet_name="displayed_data", index=False)
        export_monthly_kwh.to_excel(writer, sheet_name="monthly_kwh", index=False)
        export_monthly_financial.to_excel(writer, sheet_name="monthly_cost", index=False)
        category_df.to_excel(writer, sheet_name="category_kwh", index=False)
        top_uc_df.to_excel(writer, sheet_name="top_uc_kwh", index=False)
        inefficiency_uc_df.to_excel(writer, sheet_name="inefficiencies", index=False)
        itens_detail_df.to_excel(writer, sheet_name="itens_fatura", index=False)
        municipio_profile_df.to_excel(writer, sheet_name="benchmark", index=False)
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        tips_df.to_excel(writer, sheet_name="savings_tips", index=False)

    output.seek(0)
    return output.getvalue()


@st.cache_data(show_spinner=False)
def build_template_preserving_download(
    displayed_df: pd.DataFrame,
    template_xlsx: str,
    municipio_export_name: str,
) -> tuple[bytes, str]:
    from run_full_study import apply_dynamic_totals, export_to_final_workbook

    template_path = str(template_xlsx or "").strip()
    if not template_path or not os.path.exists(template_path):
        raise FileNotFoundError(f"Template workbook not found: {template_path}")

    export_name = sanitize_export_name(municipio_export_name)
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_xlsx = export_to_final_workbook(
            master=displayed_df.copy(),
            out_dir=tmp_dir,
            municipio=export_name,
            template_xlsx=template_path,
            fill_dimensionamento=True,
        )
        workbook = load_workbook(out_xlsx, data_only=False)
        apply_dynamic_totals(workbook)
        workbook.save(out_xlsx)
        with open(out_xlsx, "rb") as fp:
            content = fp.read()
        return content, os.path.basename(out_xlsx)


st.set_page_config(page_title="Sunergies_app", layout="wide")
st.title("Sunergies_app")
st.caption("Upload invoices, run extraction, explore structured data, and export filtered results.")

with st.sidebar:
    st.header("Processing")
    uploaded_files = st.file_uploader(
        "Upload PDF invoices",
        type=["pdf"],
        accept_multiple_files=True,
    )
    municipio_override = st.text_input("Municipio override (optional)", value="")
    expand_a4_historico = st.checkbox("Expand historico (A4/B3/IP)", value=True)
    run_extraction = st.button("Run extraction", type="primary", use_container_width=True)
    template_export_path = st.text_input(
        "Template workbook path",
        value=resolve_default_template_path(),
        help="Template used for formatted Excel download (styles and formulas preserved).",
    )

    st.header("Cost Model")
    energy_rate_rs_kwh = st.number_input(
        "Energy tariff (R$/kWh)",
        min_value=0.0,
        value=0.85,
        step=0.01,
    )
    extra_demand_rate_rs_kw = st.number_input(
        "Extra demand charge (R$/kW)",
        min_value=0.0,
        value=42.0,
        step=0.5,
    )
    peak_threshold_pct = st.slider(
        "Peak usage alert threshold (%)",
        min_value=5,
        max_value=80,
        value=25,
        step=1,
    )

if not uploaded_files:
    st.info("Upload one or more PDF invoices to start the extraction.")
    st.stop()

payloads = tuple((file.name, file.getvalue()) for file in uploaded_files)
payloads, skipped_duplicate_uploads = dedupe_payloads_by_content(payloads)
if skipped_duplicate_uploads:
    st.warning(
        "Skipped duplicate upload(s) with identical PDF content: "
        + ", ".join(skipped_duplicate_uploads)
    )
if not payloads:
    st.warning("No unique files to process after removing duplicates.")
    st.stop()

cache_key = build_extraction_cache_key(
    payloads=payloads,
    expand_a4_historico=expand_a4_historico,
    municipio_override=municipio_override,
)
use_cached = (
    st.session_state.get("extract_cache_key") == cache_key
    and "extract_cache_df" in st.session_state
    and "extract_cache_pages" in st.session_state
)

if use_cached and not run_extraction:
    master_df = st.session_state["extract_cache_df"].copy()
    total_pages_processed = int(st.session_state["extract_cache_pages"])
    progress_bar = st.progress(100)
    progress_status = st.empty()
    progress_status.write(
        f"100% | PDFs {len(payloads)}/{len(payloads)} | Pages {total_pages_processed}/{total_pages_processed} | Using cached extraction"
    )
elif not run_extraction:
    st.info("Files ready. Click 'Run extraction' in the sidebar when you want to start.")
    st.stop()
else:
    progress_bar = st.progress(0)
    progress_status = st.empty()
    master_df, total_pages_processed = process_uploaded_pdfs(
        payloads=payloads,
        expand_a4_historico=expand_a4_historico,
        municipio_override=municipio_override,
        progress_bar=progress_bar,
        status_box=progress_status,
    )
    st.session_state["extract_cache_key"] = cache_key
    st.session_state["extract_cache_df"] = master_df.copy()
    st.session_state["extract_cache_pages"] = int(total_pages_processed)

if master_df.empty:
    st.warning("No rows were extracted from the uploaded files.")
    st.stop()

st.success(
    f"Processed {len(payloads)} unique file(s) and {total_pages_processed} page(s). "
    "Dashboard refreshed with latest extraction."
)

with st.sidebar:
    st.header("Filters")
    municipio_options = sorted(master_df["municipio"].dropna().astype(str).unique().tolist())
    selected_municipios = st.multiselect(
        "Municipality",
        options=municipio_options,
        default=municipio_options,
    )

    date_range: tuple[date, date] | None = None
    valid_dates = master_df["reference_date"].dropna().sort_values()
    if not valid_dates.empty:
        min_date = valid_dates.min().date()
        max_date = valid_dates.max().date()
        selected_dates = st.date_input(
            "Reference date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
            date_range = (selected_dates[0], selected_dates[1])
    else:
        st.caption("No valid reference dates found in `referencia`.")

date_filtered_df = apply_date_filter(master_df.copy(), date_range)
if selected_municipios:
    filtered_df = date_filtered_df[date_filtered_df["municipio"].isin(selected_municipios)].copy()
else:
    filtered_df = date_filtered_df.iloc[0:0].copy()

filtered_enriched = add_estimated_cost_columns(filtered_df, energy_rate_rs_kwh, extra_demand_rate_rs_kw)
benchmark_pool_enriched = add_estimated_cost_columns(date_filtered_df, energy_rate_rs_kwh, extra_demand_rate_rs_kw)

monthly_financial_df = build_monthly_financials(filtered_enriched)
monthly_kwh_df = pd.DataFrame()
if {"reference_date", "municipio", "kwh_total_te"}.issubset(filtered_enriched.columns):
    monthly_kwh_df = (
        filtered_enriched.dropna(subset=["reference_date"])
        .groupby(["municipio", "reference_date"], as_index=False)["kwh_total_te"]
        .sum()
        .sort_values("reference_date")
    )

total_cost_rs = sum_or_zero(filtered_enriched["total_cost_rs"]) if "total_cost_rs" in filtered_enriched else 0.0
actual_cost_rs = sum_or_zero(filtered_enriched["actual_total_cost_rs"]) if "actual_total_cost_rs" in filtered_enriched else 0.0
total_billed_total_a_pagar_rs = (
    sum_or_zero(filtered_enriched["total_fatura_rs"])
    if "total_fatura_rs" in filtered_enriched
    else 0.0
)
total_billed_invoice_count = (
    int((pd.to_numeric(filtered_enriched["total_fatura_rs"], errors="coerce") > 0).sum())
    if "total_fatura_rs" in filtered_enriched
    else 0
)
if {"cost_source", "estimated_total_cost_rs"}.issubset(filtered_enriched.columns):
    estimated_fallback_cost_rs = sum_or_zero(
        filtered_enriched.loc[filtered_enriched["cost_source"] == "estimated", "estimated_total_cost_rs"]
    )
else:
    estimated_fallback_cost_rs = 0.0
total_kwh = sum_or_zero(filtered_enriched["kwh_total_te"]) if "kwh_total_te" in filtered_enriched else 0.0
itens_energy_valor_rs = (
    sum_or_zero(filtered_enriched["itens_fatura_energia_valor_rs"])
    if "itens_fatura_energia_valor_rs" in filtered_enriched
    else 0.0
)
itens_energy_kwh = (
    sum_or_zero(filtered_enriched["itens_fatura_energia_kwh"])
    if "itens_fatura_energia_kwh" in filtered_enriched
    else 0.0
)
avg_cost_per_kwh_rs = safe_div(itens_energy_valor_rs, itens_energy_kwh)
avg_cost_source_label = "Itens da Fatura (Valor/Quantidade)"
if pd.isna(avg_cost_per_kwh_rs):
    avg_cost_per_kwh_rs = safe_div(total_cost_rs, total_kwh)
    avg_cost_source_label = "Total Cost / Total kWh"
actual_cost_share_pct = safe_div(actual_cost_rs, total_cost_rs) * 100.0

if not monthly_financial_df.empty:
    latest_row = monthly_financial_df.iloc[-1]
    latest_ref = latest_row["reference_date"]
    latest_ref_label = latest_ref.strftime("%m/%Y")
    total_monthly_cost_rs = float(latest_row["total_cost_rs"])
    ytd_spending_rs = sum_or_zero(
        monthly_financial_df.loc[
            monthly_financial_df["reference_date"].dt.year == latest_ref.year,
            "total_cost_rs",
        ]
    )
else:
    latest_ref_label = "N/A"
    total_monthly_cost_rs = total_cost_rs
    ytd_spending_rs = total_cost_rs

consumo_hp_total = sum_or_zero(filtered_enriched["consumo_hp_kwh"]) if "consumo_hp_kwh" in filtered_enriched else 0.0
consumo_fhp_total = sum_or_zero(filtered_enriched["consumo_fhp_kwh"]) if "consumo_fhp_kwh" in filtered_enriched else 0.0
peak_share_pct = safe_div(consumo_hp_total, consumo_hp_total + consumo_fhp_total) * 100.0
extra_demand_kw = sum_or_zero(filtered_enriched["extra_demand_kw"]) if "extra_demand_kw" in filtered_enriched else 0.0
extra_demand_cost_rs = extra_demand_kw * float(extra_demand_rate_rs_kw)
extra_demand_events = int((filtered_enriched["extra_demand_kw"] > 0).sum()) if "extra_demand_kw" in filtered_enriched else 0

municipio_profile_df = build_municipio_profile(benchmark_pool_enriched)
avg_municipio_kwh = municipio_profile_df["total_kwh"].mean() if not municipio_profile_df.empty else float("nan")
avg_municipio_peak_pct = municipio_profile_df["peak_share_pct"].mean() if not municipio_profile_df.empty else float("nan")
avg_municipio_extra_kw = municipio_profile_df["extra_demand_kw"].mean() if not municipio_profile_df.empty else float("nan")
selected_vs_avg_kwh_pct = (safe_div(total_kwh, avg_municipio_kwh) - 1.0) * 100.0 if not pd.isna(avg_municipio_kwh) else float("nan")

tips = build_savings_opportunities(
    peak_share_pct=peak_share_pct,
    peak_threshold_pct=float(peak_threshold_pct),
    extra_demand_kw=extra_demand_kw,
    extra_demand_cost_rs=extra_demand_cost_rs,
    selected_vs_avg_kwh_pct=selected_vs_avg_kwh_pct,
    avg_cost_per_kwh_rs=avg_cost_per_kwh_rs,
    energy_rate_rs_kwh=float(energy_rate_rs_kwh),
)

inefficiency_uc_df = build_inefficiency_uc_table(filtered_enriched, extra_demand_rate_rs_kw)

st.subheader("Top Summary")
summary_col_1, summary_col_2, summary_col_3, summary_col_4 = st.columns(4)
summary_col_1.metric(
    "Total Billed (Total a Pagar)",
    format_currency(total_billed_total_a_pagar_rs),
    delta=f"Invoices: {total_billed_invoice_count}",
)
summary_col_2.metric("Total Monthly Cost", format_currency(total_monthly_cost_rs), delta=f"Reference: {latest_ref_label}")
summary_col_3.metric("Year-to-Date Spending", format_currency(ytd_spending_rs))
summary_col_4.metric("Average Cost per kWh", format_currency(avg_cost_per_kwh_rs))
st.caption(
    "Total Billed uses only extracted `total_fatura_rs` (Total a Pagar). "
    "Other cost metrics prioritize billed values and fall back to tariff estimates when missing."
)
st.caption(f"Average cost per kWh source: {avg_cost_source_label}.")
st.caption(
    f"Actual billed-cost coverage: {format_number(actual_cost_share_pct, '%')} "
    f"(actual={format_currency(actual_cost_rs)} | estimated fallback={format_currency(estimated_fallback_cost_rs)})."
)

st.subheader("Operational Snapshot")
ops_col_1, ops_col_2, ops_col_3, ops_col_4 = st.columns(4)
ops_col_1.metric("Rows", f"{len(filtered_enriched):,}")
ops_col_2.metric("Unique UCs", int(filtered_enriched["uc"].nunique()) if "uc" in filtered_enriched else 0)
ops_col_3.metric("Municipios", int(filtered_enriched["municipio"].nunique()) if "municipio" in filtered_enriched else 0)
ops_col_4.metric("Total kWh", format_number(total_kwh))

st.subheader("Inefficiencies")
ineff_col_1, ineff_col_2, ineff_col_3 = st.columns(3)
ineff_col_1.metric("Peak-Hour Usage Share", format_number(peak_share_pct, "%"))
ineff_col_2.metric("Extra Demand Charges", format_currency(extra_demand_cost_rs))
ineff_col_3.metric("Demand Overrun Events", f"{extra_demand_events:,}")
if not pd.isna(peak_share_pct) and peak_share_pct > peak_threshold_pct:
    st.warning(
        f"Peak-hour usage ({peak_share_pct:.1f}%) is above the alert threshold ({peak_threshold_pct}%)."
    )

if not inefficiency_uc_df.empty:
    st.dataframe(inefficiency_uc_df, use_container_width=True, height=260)

    top_extra_df = inefficiency_uc_df.head(10).copy()
    top_extra_df["uc_label"] = top_extra_df["municipio"].astype(str) + " | " + top_extra_df["uc"].astype(str)
    top_extra_fig = px.bar(
        top_extra_df.sort_values("estimated_extra_demand_cost_rs", ascending=True),
        x="estimated_extra_demand_cost_rs",
        y="uc_label",
        orientation="h",
        title="Top Extra Demand Cost by UC",
    )
    st.plotly_chart(top_extra_fig, use_container_width=True)
else:
    st.caption("No inefficiency data available for current filters.")

st.subheader("Benchmark Comparison")
bench_col_1, bench_col_2, bench_col_3 = st.columns(3)
bench_col_1.metric(
    "Selected vs Avg Municipio (kWh)",
    format_number(total_kwh),
    delta=(f"{selected_vs_avg_kwh_pct:+.1f}%" if not pd.isna(selected_vs_avg_kwh_pct) else "N/A"),
)
bench_col_2.metric(
    "Peak Share vs Avg Municipio",
    format_number(peak_share_pct, "%"),
    delta=(
        f"{(peak_share_pct - avg_municipio_peak_pct):+.1f} pp"
        if (not pd.isna(peak_share_pct) and not pd.isna(avg_municipio_peak_pct))
        else "N/A"
    ),
)
bench_col_3.metric(
    "Extra Demand vs Avg Municipio",
    format_number(extra_demand_kw, " kW"),
    delta=(
        f"{(extra_demand_kw - avg_municipio_extra_kw):+.2f} kW"
        if not pd.isna(avg_municipio_extra_kw)
        else "N/A"
    ),
)

if not municipio_profile_df.empty:
    benchmark_chart_df = municipio_profile_df.copy()
    benchmark_chart_df["selection_group"] = benchmark_chart_df["municipio"].isin(selected_municipios).map(
        {True: "Selected", False: "Other"}
    )
    benchmark_fig = px.bar(
        benchmark_chart_df.sort_values("total_kwh", ascending=False),
        x="municipio",
        y="total_kwh",
        color="selection_group",
        title="Usage Benchmark by Municipio (kWh)",
    )
    st.plotly_chart(benchmark_fig, use_container_width=True)
else:
    st.caption("Benchmark comparison requires at least one municipio with extracted usage.")

st.subheader("Savings Opportunities")
for tip in tips:
    st.markdown(f"- {tip}")

st.subheader("Structured Data")
st.dataframe(reorder_columns(filtered_enriched), use_container_width=True, height=420)

itens_detail_df = build_itens_fatura_detail_table(filtered_enriched)
st.subheader("Itens da Fatura - Preco Unitario e Valor")
if not itens_detail_df.empty:
    st.dataframe(itens_detail_df, use_container_width=True, height=280)
    itens_summary_df = (
        itens_detail_df.groupby("item", as_index=False)
        .agg(
            total_valor_rs=("valor_rs", "sum"),
            total_quantidade=("quantidade", "sum"),
            preco_unitario_medio_rs=("preco_unitario_com_tributos_rs", "mean"),
        )
        .sort_values("total_valor_rs", ascending=False)
    )
    itens_chart_df = itens_summary_df.head(15).sort_values("total_valor_rs", ascending=True)
    itens_fig = px.bar(
        itens_chart_df,
        x="total_valor_rs",
        y="item",
        orientation="h",
        title="Top Itens por Valor (R$)",
    )
    st.plotly_chart(itens_fig, use_container_width=True)
else:
    itens_summary_df = pd.DataFrame(columns=["item", "total_valor_rs", "total_quantidade", "preco_unitario_medio_rs"])
    st.caption("Nenhum item de 'Itens da Fatura' foi identificado para os filtros atuais.")

category_kwh_df = pd.DataFrame()
if {"categoria", "kwh_total_te"}.issubset(filtered_enriched.columns):
    category_kwh_df = (
        filtered_enriched.groupby("categoria", dropna=False, as_index=False)["kwh_total_te"]
        .sum()
        .sort_values("kwh_total_te", ascending=False)
    )

uc_kwh_df = pd.DataFrame()
if {"uc", "municipio", "kwh_total_te"}.issubset(filtered_enriched.columns):
    uc_kwh_df = (
        filtered_enriched.groupby(["municipio", "uc"], as_index=False)["kwh_total_te"]
        .sum()
        .sort_values("kwh_total_te", ascending=False)
        .head(15)
    )
    uc_kwh_df["uc_label"] = uc_kwh_df["municipio"].astype(str) + " | " + uc_kwh_df["uc"].astype(str)

st.subheader("Interactive Charts")
if not monthly_kwh_df.empty:
    monthly_fig = px.line(
        monthly_kwh_df,
        x="reference_date",
        y="kwh_total_te",
        color="municipio",
        markers=True,
        title="Monthly Consumption (kWh)",
    )
    st.plotly_chart(monthly_fig, use_container_width=True)
else:
    st.caption("Monthly chart unavailable because date or kWh data is missing after filters.")

if not monthly_financial_df.empty:
    monthly_cost_fig = px.line(
        monthly_financial_df,
        x="reference_date",
        y="total_cost_rs",
        markers=True,
        title="Monthly Cost (R$) - Actual First, Estimated Fallback",
    )
    st.plotly_chart(monthly_cost_fig, use_container_width=True)
else:
    st.caption("Monthly cost chart unavailable because reference dates are missing.")

chart_col_1, chart_col_2 = st.columns(2)
with chart_col_1:
    if not category_kwh_df.empty:
        category_fig = px.bar(
            category_kwh_df,
            x="categoria",
            y="kwh_total_te",
            color="categoria",
            title="Consumption by Category",
        )
        st.plotly_chart(category_fig, use_container_width=True)
    else:
        st.caption("Category chart unavailable for the current filters.")

with chart_col_2:
    if not uc_kwh_df.empty:
        top_uc_fig = px.bar(
            uc_kwh_df.sort_values("kwh_total_te", ascending=True),
            x="kwh_total_te",
            y="uc_label",
            orientation="h",
            title="Top 15 UCs by Consumption",
        )
        st.plotly_chart(top_uc_fig, use_container_width=True)
    else:
        st.caption("Top-UC chart unavailable for the current filters.")

summary_export_df = pd.DataFrame(
    [
        {"metric": "total_billed_total_a_pagar_rs", "value": total_billed_total_a_pagar_rs, "reference": "filtered period"},
        {"metric": "total_billed_invoice_count", "value": total_billed_invoice_count, "reference": "filtered period"},
        {"metric": "total_monthly_cost_rs", "value": total_monthly_cost_rs, "reference": latest_ref_label},
        {"metric": "ytd_spending_rs", "value": ytd_spending_rs, "reference": latest_ref_label},
        {"metric": "avg_cost_per_kwh_rs", "value": avg_cost_per_kwh_rs, "reference": "filtered period"},
        {"metric": "avg_cost_per_kwh_source", "value": avg_cost_source_label, "reference": "calculation method"},
        {"metric": "itens_fatura_energia_valor_rs", "value": itens_energy_valor_rs, "reference": "filtered period"},
        {"metric": "itens_fatura_energia_kwh", "value": itens_energy_kwh, "reference": "filtered period"},
        {"metric": "actual_cost_rs", "value": actual_cost_rs, "reference": "filtered period"},
        {"metric": "estimated_fallback_cost_rs", "value": estimated_fallback_cost_rs, "reference": "filtered period"},
        {"metric": "actual_cost_share_pct", "value": actual_cost_share_pct, "reference": "filtered period"},
        {"metric": "peak_share_pct", "value": peak_share_pct, "reference": "filtered period"},
        {"metric": "extra_demand_kw", "value": extra_demand_kw, "reference": "filtered period"},
    ]
)
tips_export_df = pd.DataFrame({"savings_opportunity": tips})

excel_bytes = build_excel_download(
    displayed_df=filtered_enriched,
    monthly_kwh_df=monthly_kwh_df,
    monthly_financial_df=monthly_financial_df,
    category_df=category_kwh_df,
    top_uc_df=uc_kwh_df,
    inefficiency_uc_df=inefficiency_uc_df,
    itens_detail_df=itens_detail_df,
    municipio_profile_df=municipio_profile_df,
    summary_df=summary_export_df,
    tips_df=tips_export_df,
)

if len(selected_municipios) == 1:
    municipio_export_name = selected_municipios[0]
else:
    municipio_export_name = "Sunergies_app"

if os.path.exists(template_export_path):
    with st.spinner("Preparing template-formatted workbook..."):
        formatted_excel_bytes, formatted_filename = build_template_preserving_download(
            displayed_df=filtered_enriched,
            template_xlsx=template_export_path,
            municipio_export_name=municipio_export_name,
        )
    st.download_button(
        label="Download displayed data as Excel",
        data=formatted_excel_bytes,
        file_name=formatted_filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Generated from your template workbook to preserve formatting.",
    )
else:
    st.error(
        f"Template workbook not found: `{template_export_path}`. "
        "Set a valid path in the sidebar to download with preserved formatting."
    )

st.download_button(
    label="Download analytics tables (flat Excel)",
    data=excel_bytes,
    file_name="sunergies_app_filtered_flat.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)



