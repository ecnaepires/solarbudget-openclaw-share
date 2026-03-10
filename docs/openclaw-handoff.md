# OpenClaw Handoff Notes

This document exists to answer the operational questions that are not obvious from code inspection alone.

## What is missing from the repository on purpose

The repository does not include:

- real invoice PDFs
- local credentials
- generated dashboard outputs
- extraction logs
- municipality extracted/master/dimensionamento output folders
- local backups and ad hoc debug artifacts

These were excluded to avoid publishing secrets, personal or utility billing data, and local-only noise.

## What is actually required to run core workflows

Required for the main dashboard flow:

- `budget_dashboard/template.xlsx`
- `budget_dashboard/excel_map.yaml`
- `budget_dashboard/catalog/*`
- `Project/estudo_faturas_municipios/fatura_engine/*`
- `Project/estudo_faturas_municipios/templates/final_template_all_in_one.xlsx`

Required to validate extraction reliability:

- real or redacted PDF invoices from multiple distributors

Required only for optional helper scripts:

- `Project/estudo_faturas_municipios/credentials.json`
  - only needed by `extract_uc_blocks.py`
  - this is for Google Sheets access via `gspread`
  - not required for the main Streamlit dashboard or local PDF extraction

## Environment and config notes

No `.env` file is required for the normal dashboard flow.

Optional environment variables observed in code:

- `DISCOVERY_OUTPUT_DIR`
  - used by dashboard extraction discovery mode
  - optional
- `USERNAME` / `USER`
  - only used for lightweight audit metadata in output logs

## Path coupling that still exists

The dashboard currently imports the extraction engine from a sibling path:

```text
budget_dashboard/
Project/estudo_faturas_municipios/
```

`budget_dashboard/services/extraction_bridge_service.py` still contains an absolute local fallback path for the original machine, but the bundled repo layout was preserved so runtime does not depend on that fallback if the repo is cloned intact.

## Most valuable next artifact

The most valuable thing still missing is a redacted PDF fixture pack.

Recommended fixture set:

- 2 to 3 PDFs that extract correctly
- 2 to 3 PDFs that extract badly
- 1 mixed batch with multiple distributors

Most valuable failure patterns:

- category detection wrong
- A4 HP / FHP parsing wrong
- municipality grouping messy
- incomplete field extraction
- normalization wrong after extraction

## Where to put those PDFs

Use:

```text
fixtures/pdfs/
```

Suggested naming:

- `works-celesc-1.pdf`
- `fails-enel-a4-1.pdf`
- `weird-cpfl-2.pdf`

Add companion metadata using the manifest example in `fixtures/pdfs/manifest.example.json`.

## Current operational state in blunt terms

What already works:

- the dashboard runs
- the extraction engine is integrated
- multiple distributor layouts are supported
- generic fallback extraction exists
- adapter-based normalization exists
- budget/export flow exists

What is still weak:

- no committed real PDF test corpus
- extraction reliability is not proven across real layouts
- dashboard and extractor are still coupled by directory layout instead of a cleaner package boundary
- dependency management is practical but not locked

## What a truly operational version should look like

Clone once, install once, run the dashboard without local path hacks, upload mixed utility invoices from different distributors, get reliable normalized extraction, feed that directly into sizing and budget generation, and export usable outputs with minimal manual cleanup.
