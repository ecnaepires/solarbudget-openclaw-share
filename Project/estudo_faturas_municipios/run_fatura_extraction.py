import argparse
import os
import time

import pandas as pd

from fatura_engine.extractors import extract_pdf
from fatura_engine.audit import build_audit_pdf_pages


def build_uc_x_mes(df: pd.DataFrame, out_xlsx: str) -> None:
    """
    Builds a matrix UC x Referencia with kwh_total_te as values.
    """
    if df.empty:
        pd.DataFrame().to_excel(out_xlsx, index=False)
        return

    temp = df.copy()

    # Ensure UC remains string (preserve leading zeros)
    if "uc" in temp.columns:
        temp["uc"] = temp["uc"].astype(str)

    index_cols = ["nome", "endereco", "uc", "categoria", "tipo_fornecimento", "pdf_source"]

    pivot = temp.pivot_table(
        index=index_cols,
        columns="referencia",
        values="kwh_total_te",
        aggfunc="sum",
        fill_value=0,
        sort=False,
    ).reset_index()

    # Keep row order aligned with the invoice page order (first seen page per UC block).
    if "page_first_seen" in temp.columns:
        order_map = (
            temp[index_cols + ["page_first_seen"]]
            .assign(page_first_seen=pd.to_numeric(temp["page_first_seen"], errors="coerce"))
            .dropna(subset=["page_first_seen"])
            .groupby(index_cols, as_index=False)["page_first_seen"]
            .min()
            .sort_values("page_first_seen", kind="stable")
            .reset_index(drop=True)
        )
        if not order_map.empty:
            order_map["_row_order"] = range(len(order_map))
            pivot = (
                pivot.merge(order_map[index_cols + ["_row_order"]], on=index_cols, how="left")
                .sort_values("_row_order", kind="stable", na_position="last")
                .drop(columns=["_row_order"])
            )

    pivot.to_excel(out_xlsx, index=False)


def main(pdf_path: str, out_prefix: str, profile: bool = False, discovery_mode: bool = False) -> None:
    started_at = time.perf_counter() if profile else 0.0
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    extraction_started_at = time.perf_counter() if profile else 0.0
    df = extract_pdf(pdf_path, discovery_mode=discovery_mode)
    if profile:
        extraction_elapsed = time.perf_counter() - extraction_started_at
        print(f"[profile] extract_pdf: {extraction_elapsed:.2f}s")

    # Ensure UC is always stored as string (preserve leading zeros)
    if "uc" in df.columns:
        df["uc"] = df["uc"].astype(str)

    # Build audit trail: PDF + pages per key
    audit_keys = ["uc", "referencia"] if {"uc", "referencia"}.issubset(df.columns) else ["uc"]
    audit_df = build_audit_pdf_pages(df, group_cols=audit_keys)
    df = df.merge(audit_df, on=audit_keys, how="left")

    # Stats + warnings
    rows = len(df)
    missing_ref = int(df["referencia"].isna().sum()) if "referencia" in df.columns else 0
    blank_kwh = int(df["kwh_total_te"].isna().sum()) if "kwh_total_te" in df.columns else 0

    # Categoria counts
    cat_counts = df["categoria"].value_counts(dropna=False) if "categoria" in df.columns else pd.Series()

    if missing_ref:
        print(f"WARNING: {missing_ref} rows without 'referencia' (MM/AAAA).")
    if blank_kwh:
        print(f"WARNING: {blank_kwh} rows without kWh total (kwh_total_te).")

    out_csv = f"{out_prefix}.csv"
    out_tsv = f"{out_prefix}.tsv"
    out_xlsx = f"{out_prefix}_uc_x_mes.xlsx"

    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    df.to_csv(out_tsv, sep="\t", index=False, encoding="utf-8-sig")
    build_uc_x_mes(df, out_xlsx)

    print(f"Saved: {out_csv}, {out_tsv}, {out_xlsx}")
    print(f"rows= {rows}")
    print(f"missing_ref= {missing_ref}")
    print(f"blank_kwh= {blank_kwh}")
    if len(cat_counts):
        print("categoria counts:")
        print(cat_counts.to_string())
    if profile:
        elapsed = time.perf_counter() - started_at
        print(f"[profile] extraction_total: {elapsed:.2f}s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract one PDF and generate CSV/TSV + UC x mes workbook outputs."
    )
    parser.add_argument("pdf_path", help="Input PDF file path")
    parser.add_argument("out_prefix", help="Output prefix (without extension)")
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Print timing information",
    )
    parser.add_argument(
        "--discovery-mode",
        action="store_true",
        help="Enable discovery logging and write <pdf>_discovery.json",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(
        args.pdf_path,
        args.out_prefix,
        profile=args.profile,
        discovery_mode=args.discovery_mode,
    )
