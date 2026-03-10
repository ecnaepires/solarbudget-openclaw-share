# Refactor Checklist: Target Architecture vs Current State

## Goal
Turn `app.py` into an orchestration layer and move reusable logic into focused modules.

## Intended Architecture
- `ui/helpers.py`: shared formatting, BRL parsing, CSV/Excel byte builders, common UI constants.
- `ui/extraction_helpers.py`: extraction, tariff inference, dimensioning/orcamento/export helpers.
- `ui/context.py` + `ui/validators.py`: typed context and step validation logic.
- `ui/style.py`: visual theme and UI section components.
- `adapters/*`: adapter registry, auto-detection, config-driven adapters.
- `budget/*`: schema validation, data quality report, budget pipeline metrics.
- `app.py`: compose modules, handle Streamlit state/layout, call services/helpers.

## Current State (Before this pass)
- `ui/*`, `adapters/*`, and `budget/*` modules already exist and are wired in key flows.
- `app.py` still duplicates many functions now present in `ui/helpers.py` and `ui/extraction_helpers.py`.
- Net effect: logic works, but maintenance risk is high because behavior can drift between duplicate copies.

## This Pass
- [x] Add this checklist.
- [x] Remove duplicated helper constants/functions from `app.py` and import from `ui/helpers.py`.
- [x] Remove duplicated extraction functions from `app.py` and import from `ui/extraction_helpers.py`.
- [x] Keep only compatibility wrappers where signatures intentionally differ.
- [x] Run syntax/import verification after refactor.

## Remaining (After this pass)
- [ ] Add focused tests for adapter detection, contract quality checks, and extraction export flows.
- [ ] Initialize git history in this folder to track future changes cleanly.
