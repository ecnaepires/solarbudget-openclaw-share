"""Extraction helpers — PDF processing + re-exports from split service modules.

Functions have been organized into:
- ui.numeric_utils: shared numeric/DataFrame utilities
- services.tariff_service: tariff inference and autofill
- services.dimensioning_service: dimensionar / orcamentar
- services.export_service: export and analytics

This module keeps PDF processing logic and re-exports everything
so existing imports from ui.extraction_helpers continue to work.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import streamlit as st

from services.extraction_bridge_service import extract_records_from_uploaded_pdfs
from ui.helpers import parse_brl_value

# ── Re-exports from ui.numeric_utils ─────────────────────────────────────────
from ui.numeric_utils import (  # noqa: F401
    _add_estimated_cost_columns,
    _build_inefficiency_uc_table,
    _build_itens_fatura_detail_table,
    _build_monthly_financials,
    _build_municipio_profile,
    _build_savings_opportunities,
    _coalesce_numeric_series,
    _merge_warning_messages,
    _normalize_header_name,
    _parse_reference_series,
    _safe_div,
    _sum_or_zero,
    _to_numeric_flexible,
    _weighted_average_positive,
)

# ── Re-exports from services.tariff_service ──────────────────────────────────
from services.tariff_service import (  # noqa: F401
    apply_pending_tariff_autofill,
    infer_tariffs_from_invoice_raw,
    recalculate_pdf_records_after_tariff_autofill,
)

# ── Re-exports from services.dimensioning_service ────────────────────────────
from services.dimensioning_service import (  # noqa: F401
    dimensionar,
    orcamentar,
)

# ── Re-exports from services.export_service ──────────────────────────────────
from services.export_service import (  # noqa: F401
    _build_original_extraction_frames,
    _build_streamlit_exact_template_export_bytes,
    _import_run_full_study_from_root,
    _is_template_export_compatible_raw_df,
    _latest_extraction_payload,
    _reorder_original_extract_columns,
    _resolve_streamlit_template_path,
    _sanitize_export_name_like_streamlit,
    exportar_extracao,
)


# ── PDF processing (remains here — tightly coupled to Streamlit cache) ───────

class _UploadedPDFBytes:
    def __init__(self, name: str, file_bytes: bytes):
        self.name = str(name or "uploaded.pdf")
        self._bytes = file_bytes

    def getvalue(self) -> bytes:
        return self._bytes


def _read_excel_prefer_extraction_sheet(excel_source: Any) -> pd.DataFrame:
    source_for_excel = excel_source
    if hasattr(excel_source, "getvalue") and not isinstance(excel_source, (str, Path)):
        source_for_excel = BytesIO(excel_source.getvalue())

    workbook = pd.ExcelFile(source_for_excel)
    try:
        normalized_to_actual = {str(name).strip().lower(): name for name in workbook.sheet_names}
        for preferred in ("displayed_data", "extraido_raw"):
            chosen = normalized_to_actual.get(preferred)
            if chosen is not None:
                return pd.read_excel(workbook, sheet_name=chosen)
        return pd.read_excel(workbook, sheet_name=workbook.sheet_names[0])
    finally:
        workbook.close()


def _build_pdf_payload(uploaded_pdfs) -> list[dict]:
    payload: list[dict] = []
    for uploaded in uploaded_pdfs or []:
        file_name = str(getattr(uploaded, "name", "uploaded.pdf") or "uploaded.pdf")
        try:
            file_bytes = uploaded.getvalue()
        except Exception:
            continue
        payload.append({"name": file_name, "bytes": file_bytes})
    return payload


def _pdf_payload_signature(payload: list[dict]) -> str:
    hasher = hashlib.sha256()
    for item in payload:
        name_bytes = str(item.get("name", "")).encode("utf-8", errors="ignore")
        file_bytes = bytes(item.get("bytes", b""))
        hasher.update(name_bytes)
        hasher.update(len(file_bytes).to_bytes(8, byteorder="big", signed=False))
        hasher.update(hashlib.sha256(file_bytes).digest())
    return hasher.hexdigest()


def process_pdfs(
    uploaded_pdfs,
    extraction_root: Path,
    *,
    municipio_override: str = "",
    expand_a4_historico: bool = True,
    months_to_use: int = 13,
    hsp: float = 4.9,
    performance_ratio: float = 0.80,
    days_per_month: float = 30.0,
    a4_hp_factor: float = 1.0,
    capex_brl_per_mwp: float = 8_500_000.0,
    tariff_b3_rs_kwh: float | None = None,
    tariff_b4a_rs_kwh: float | None = None,
    tariff_a4_hp_rs_kwh: float | None = None,
    tariff_a4_fhp_rs_kwh: float | None = None,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict:
    payload = _build_pdf_payload(uploaded_pdfs)
    if not payload:
        raise ValueError("Nenhum PDF foi enviado para processamento.")

    extraction_root_path = Path(extraction_root).expanduser().resolve()
    payload_signature = _pdf_payload_signature(payload)
    cache_key = (
        payload_signature, str(extraction_root_path),
        str(municipio_override or "").strip(), bool(expand_a4_historico),
        int(months_to_use), float(hsp), float(performance_ratio),
        float(days_per_month), float(a4_hp_factor), float(capex_brl_per_mwp),
        None if tariff_b3_rs_kwh is None else float(tariff_b3_rs_kwh),
        None if tariff_b4a_rs_kwh is None else float(tariff_b4a_rs_kwh),
        None if tariff_a4_hp_rs_kwh is None else float(tariff_a4_hp_rs_kwh),
        None if tariff_a4_fhp_rs_kwh is None else float(tariff_a4_fhp_rs_kwh),
    )
    cache_store = st.session_state.setdefault("simple_extraction_cache", {})
    cache_entry = cache_store.get(cache_key)
    if cache_entry:
        cached_raw_df = cache_entry.get("raw_df")
        cached_stats = deepcopy(cache_entry.get("stats", {}))
        cached_records = deepcopy(cache_entry.get("records", []))
        raw_df_out = cached_raw_df.copy() if isinstance(cached_raw_df, pd.DataFrame) else pd.DataFrame()
        if progress_callback:
            total_pages = int(cached_stats.get("total_pages", 0) or 0)
            progress_callback({"phase": "init", "pages_processed": 0, "total_pages": total_pages, "progress": 0.0, "current_pdf_name": "", "pdf_page_no": 0, "pdf_pages": 0})
            progress_callback({"phase": "page_done", "pages_processed": total_pages, "total_pages": total_pages, "progress": 1.0 if total_pages > 0 else 0.0, "current_pdf_name": "", "pdf_page_no": 0, "pdf_pages": 0})
        warnings: list[str] = list(cache_entry.get("warnings", []))
        return {
            "raw_df": raw_df_out, "records": cached_records, "stats": cached_stats,
            "audit": {
                "files_processed": int(cached_stats.get("files_processed", 0) or 0),
                "rows_extracted": int(cached_stats.get("rows_extracted", 0) or 0),
                "failed_files": list(cached_stats.get("failed_files") or []),
                "total_pages": int(cached_stats.get("total_pages", 0) or 0),
                "pages_processed": int(cached_stats.get("pages_processed", 0) or 0),
            },
            "warnings": warnings, "cache_hit": True,
        }

    uploaded_wrapped = [_UploadedPDFBytes(item["name"], item["bytes"]) for item in payload]
    records, stats = extract_records_from_uploaded_pdfs(
        uploaded_pdfs=uploaded_wrapped,
        extraction_root=extraction_root_path,
        municipio_override=municipio_override,
        expand_a4_historico=expand_a4_historico,
        months_to_use=months_to_use,
        hsp=hsp, performance_ratio=performance_ratio,
        days_per_month=days_per_month, a4_hp_factor=a4_hp_factor,
        capex_brl_per_mwp=capex_brl_per_mwp,
        tariff_b3_rs_kwh=tariff_b3_rs_kwh, tariff_b4a_rs_kwh=tariff_b4a_rs_kwh,
        tariff_a4_hp_rs_kwh=tariff_a4_hp_rs_kwh, tariff_a4_fhp_rs_kwh=tariff_a4_fhp_rs_kwh,
        progress_callback=progress_callback,
    )

    raw_df = stats.get("master_df")
    raw_df_out = raw_df.copy() if isinstance(raw_df, pd.DataFrame) else pd.DataFrame()
    stats_out = {
        "files_processed": int(stats.get("files_processed", 0) or 0),
        "rows_extracted": int(stats.get("rows_extracted", 0) or 0),
        "failed_files": list(stats.get("failed_files") or []),
        "total_pages": int(stats.get("total_pages", 0) or 0),
        "pages_processed": int(stats.get("pages_processed", 0) or 0),
    }
    warnings: list[str] = []
    if stats_out["failed_files"]:
        warnings.append("Arquivos com falha na extracao: " + ", ".join(stats_out["failed_files"]))
    if stats_out["rows_extracted"] <= 0:
        warnings.append("Extracao sem itens validos; revise os PDFs.")

    cache_store[cache_key] = {
        "raw_df": raw_df_out.copy(), "records": deepcopy(records),
        "stats": deepcopy(stats_out), "warnings": list(warnings),
    }

    return {
        "raw_df": raw_df_out, "records": records, "stats": stats_out,
        "audit": stats_out, "warnings": warnings, "cache_hit": False,
    }
