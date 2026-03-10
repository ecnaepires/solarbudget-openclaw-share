import argparse
import os
import time
import pandas as pd

from fatura_engine.extractors import extract_pdf
from fatura_engine.audit import build_audit_pdf_pages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run extraction for multiple PDFs and export per-file + merged master outputs."
    )
    parser.add_argument("municipio_prefix", help="Output prefix for generated files")
    parser.add_argument("pdf_paths", nargs="+", help="Input PDF file paths")
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Print timing information",
    )
    parser.add_argument(
        "--discovery-mode",
        action="store_true",
        help="Enable discovery logging and write <pdf>_discovery.json per file",
    )
    return parser.parse_args()


def main():
    cli = parse_args()
    municipio_prefix = cli.municipio_prefix
    pdf_paths = cli.pdf_paths
    profile = cli.profile
    discovery_mode = cli.discovery_mode

    all_dfs = []
    started_at = time.perf_counter() if profile else 0.0

    for pdf_path in pdf_paths:
        pdf_started_at = time.perf_counter() if profile else 0.0
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        print(f"\n--- Extracting: {pdf_path}")
        extraction_started_at = time.perf_counter() if profile else 0.0
        df = extract_pdf(pdf_path, discovery_mode=discovery_mode)
        if profile:
            extraction_elapsed = time.perf_counter() - extraction_started_at
            print(f"[profile] extract_pdf: {extraction_elapsed:.2f}s")

        # Ensure UC stays as text
        if "uc" in df.columns:
            df["uc"] = df["uc"].astype(str)

        # Add audit per-row (single PDF)
        audit_keys = ["uc", "referencia"] if {"uc", "referencia"}.issubset(df.columns) else ["uc"]
        audit_df = build_audit_pdf_pages(df, group_cols=audit_keys)
        df = df.merge(audit_df, on=audit_keys, how="left")

        out_prefix = f"{municipio_prefix}_{os.path.splitext(os.path.basename(pdf_path))[0]}"
        out_csv = f"{out_prefix}.csv"
        out_tsv = f"{out_prefix}.tsv"

        df.to_csv(out_csv, index=False, encoding="utf-8-sig")
        df.to_csv(out_tsv, sep="\t", index=False, encoding="utf-8-sig")
        print(f"Saved: {out_csv}, {out_tsv} (rows={len(df)})")
        if profile:
            pdf_elapsed = time.perf_counter() - pdf_started_at
            print(f"[profile] total_pdf: {pdf_elapsed:.2f}s")

        if not df.empty:
            all_dfs.append(df)

    if not all_dfs:
        print("\n=== MASTER SKIPPED ===")
        print("No extracted rows found across provided PDFs.")
        return

    # Merge everything into master
    master = pd.concat(all_dfs, ignore_index=True)

    # Rebuild audit across ALL PDFs (important)
    master_audit_keys = ["uc", "referencia"] if {"uc", "referencia"}.issubset(master.columns) else ["uc"]
    master_audit = build_audit_pdf_pages(master, group_cols=master_audit_keys)
    master = (
        master.drop(columns=["audit_pdf_pages"], errors="ignore")
        .merge(master_audit, on=master_audit_keys, how="left")
    )

    master_csv = f"{municipio_prefix}_master.csv"
    master_tsv = f"{municipio_prefix}_master.tsv"

    master.to_csv(master_csv, index=False, encoding="utf-8-sig")
    master.to_csv(master_tsv, sep="\t", index=False, encoding="utf-8-sig")

    print("\n=== MASTER SAVED ===")
    print(f"Saved: {master_csv}, {master_tsv}")
    print(f"rows= {len(master)}")
    if "categoria" in master.columns:
        print("categoria counts:")
        print(master["categoria"].value_counts(dropna=False).to_string())
    else:
        print("categoria counts: column not available in master output.")
    if profile:
        elapsed = time.perf_counter() - started_at
        print(f"[profile] batch_total: {elapsed:.2f}s")


if __name__ == "__main__":
    main()
