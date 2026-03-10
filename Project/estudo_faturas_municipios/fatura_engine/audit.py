import os
from typing import Iterable, Optional

import pandas as pd


def build_audit_pdf_pages(df: pd.DataFrame, group_cols: Optional[Iterable[str]] = None) -> pd.DataFrame:
    """
    Creates an audit trail:
      audit_pdf_pages = "file1: 1, 10 | file2: 3"
    Uses pdf_source + page_first_seen and groups by `group_cols` (default: ["uc"]).
    """
    if df is None or df.empty:
        keys = [c for c in (group_cols or ["uc"]) if c]
        return pd.DataFrame(columns=[*keys, "audit_pdf_pages"])

    temp = df.copy()
    keys = [c for c in (group_cols or ["uc"]) if c in temp.columns]
    if not keys:
        return pd.DataFrame(columns=["audit_pdf_pages"])

    # Ensure stable key types.
    if "uc" in keys:
        temp["uc"] = temp["uc"].astype(str)
    if "referencia" in keys:
        temp["referencia"] = temp["referencia"].astype(str)

    temp["pdf_source"] = (
        temp["pdf_source"]
        .astype(str)
        .map(lambda s: os.path.splitext(os.path.basename(str(s).strip()))[0] if str(s).strip() else "")
    )
    temp["page_first_seen"] = pd.to_numeric(temp["page_first_seen"], errors="coerce")

    # Keep only valid pages.
    temp = temp.dropna(subset=["page_first_seen"])
    temp["page_first_seen"] = temp["page_first_seen"].astype(int)
    if temp.empty:
        return pd.DataFrame(columns=[*keys, "audit_pdf_pages"])

    cols = [*keys, "pdf_source", "page_first_seen"]
    temp = temp[cols].drop_duplicates().sort_values([*keys, "pdf_source", "page_first_seen"])

    def fmt_group(g: pd.DataFrame) -> str:
        parts = []
        for pdf, gg in g.groupby("pdf_source", sort=True):
            pages = gg["page_first_seen"].tolist()
            pages_str = ", ".join(str(p) for p in pages)
            parts.append(f"{pdf}: {pages_str}")
        return " | ".join(parts)

    rows = []
    grouped = temp.groupby(keys, sort=True, dropna=False)
    for group_key, grp in grouped:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        row = {k: group_key[idx] for idx, k in enumerate(keys)}
        row["audit_pdf_pages"] = fmt_group(grp)
        rows.append(row)

    return pd.DataFrame(rows)
