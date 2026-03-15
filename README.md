# SolarBudget Workspace Share

This repository is a shareable bundle of the two local projects that currently work together:

- `budget_dashboard/`: the main Streamlit dashboard for sizing, budgeting, exports, adapters, and workflow control.
- `Project/estudo_faturas_municipios/`: the invoice extraction project used by the dashboard through `fatura_engine`.

The layout is intentional. The dashboard resolves the extraction engine from a sibling path, so both folders are kept in one repository without changing runtime code.

## Repository layout

```text
solarbudget-openclaw-share/
  README.md
  requirements-share.txt
  budget_dashboard/
  Project/
    estudo_faturas_municipios/
```

## What this bundle includes

- dashboard UI, services, adapters, catalogs, templates, and export logic
- extraction engine code, regex/layout logic, tests, and municipality pipeline scripts
- YAML adapter configs for multiple distributors
- templates and sample test assets needed by the current workflow

## What is intentionally excluded

These were kept out of version control on purpose:

- virtual environments
- Python cache files
- local backups
- generated dashboard outputs and extraction logs
- extracted municipality output folders and local archives
- local secrets such as `credentials.json`

If OpenClaw needs credentials or generated outputs, they must be supplied separately.

## Quick start

1. Clone the repository.
2. Create and activate a Python virtual environment at the repository root or inside `budget_dashboard/`.
3. Install dependencies:

```powershell
pip install -r requirements-share.txt
```

4. Start the dashboard:

```powershell
cd budget_dashboard
streamlit run app.py
```

5. Keep the repository structure unchanged so the dashboard can import the extraction project from:

```text
../Project/estudo_faturas_municipios
```

## Runtime notes

- The dashboard dynamically imports `fatura_engine.extractors.extract_pdf` from the extraction project.
- `budget_dashboard/services/extraction_bridge_service.py` assumes the sibling extraction path exists.
- Streamlit config is stored in `budget_dashboard/.streamlit/config.toml`.
- Dashboard-generated outputs are recreated locally and are not committed.

## Dependency notes

The repository did not originally contain a locked dependency file. A practical shared install list is provided in `requirements-share.txt` for the combined workspace.

Optional integrations:

- `gspread` and `google-auth` are only needed for scripts that talk to Google services.
- `plotly` is used by the extraction project's Streamlit app, not the main dashboard.

## Suggested first checks after clone

From `budget_dashboard/`:

```powershell
python -m py_compile app.py ui\style.py
streamlit run app.py
```

From `Project/estudo_faturas_municipios/`:

```powershell
python -m unittest discover -s tests
```

## Notes for OpenClaw

- The dashboard and extraction engine are coupled by directory layout, not by published package install.
- The share bundle is designed for inspection, collaboration, and local execution, not as a polished package release.
- If OpenClaw wants this split into cleaner independent repos or converted into a single proper Python workspace, that should be treated as a separate refactor.
- See `docs/openclaw-handoff.md` for missing artifacts, runtime exclusions, and the recommended PDF fixture pack structure.

Practice change
