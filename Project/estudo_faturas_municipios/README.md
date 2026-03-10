# text_extract

Utility project for extracting electricity bill data from PDFs and generating municipality deliverables.

## Current Structure

- `fatura_engine/`: core extraction logic, regex/models, and audit helpers.
- `run_full_study.py`: main end-to-end pipeline for municipality studies.
- `streamlit_app.py`: Streamlit interface for extraction and exports.
- `run_fatura_extraction.py`: single-PDF extractor runner.
- `run_batch_municipio.py`: multi-PDF batch runner + merged master output.
- `templates/`: shared workbook templates (source templates).
- `municipios/`: municipality-specific input/output folders.
- `archive/backups/`: archived backup scripts.
- Root utility scripts:
  - `merge_outputs.py`
  - `build_template_final.py`
  - `build_12m_template.py`
  - `dimensionamento_ufv.py`
  - `extract_uc_blocks.py`
  - `extract_faturas_main_code.py`

## Suggested Conventions

- Keep reusable code in `fatura_engine/`.
- Keep source templates in `templates/`.
- Keep municipality runs under `municipios/<MUNICIPIO>/`.
- Keep temporary/legacy scripts in `archive/` if no longer part of the main flow.
- Avoid adding generated CSV/XLSX outputs to the project root.

## Main Commands

- Full pipeline:
  - `python run_full_study.py <MUNICIPIO> <PDF1> <PDF2> ...`
- Single PDF extraction:
  - `python run_fatura_extraction.py <PDF_PATH> <OUT_PREFIX>`
- Batch extraction:
  - `python run_batch_municipio.py <MUNICIPIO_PREFIX> <PDF1> <PDF2> ...`

## One-Click Dashboard (Windows)

- Double-click `open_dashboard.bat` in the project root.
- It starts `streamlit_app.py` and opens `http://localhost:8501`.

## Tests

- Run all tests:
  - `python -m unittest discover -s tests -p "test_*.py"`
