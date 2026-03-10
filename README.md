# SolarBudget Share Bundle

This repository packages the full local workspace needed to run the SolarBudget dashboard together with the connected invoice extraction engine used by the dashboard.

## Included projects

- `budget_dashboard/`: Streamlit dashboard, adapters, pricing/catalog data, export pipeline, UI, and services.
- `Project/estudo_faturas_municipios/`: invoice extraction engine (`fatura_engine`), templates, municipality pipeline scripts, and tests.

## Why the structure looks like this

The dashboard currently resolves the extraction project from a sibling path:

- `budget_dashboard`
- `Project/estudo_faturas_municipios`

This repository preserves that layout so the integration works without code changes.

## What is intentionally excluded from version control

- virtual environments
- Python cache files
- local backups
- generated dashboard outputs and logs
- local extraction archives and derived municipality output folders
- `credentials.json` and other local-only secrets

## Run locally

1. Create and activate a Python environment for `budget_dashboard`.
2. Install the required dependencies used by the dashboard and extraction project.
3. From `budget_dashboard`, run:

```powershell
streamlit run app.py
```

4. If the dashboard needs the extraction engine, keep the sibling folder structure intact.

## Notes for OpenClaw

- The dashboard imports the extraction engine dynamically from `Project/estudo_faturas_municipios`.
- Generated outputs are not committed; they should be recreated locally after clone.
- Local secret files are excluded and must be supplied separately if required.
