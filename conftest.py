"""Root conftest.py — makes both project roots importable from anywhere.

Running `pytest` from the repo root will discover tests in both:
  - Project/estudo_faturas_municipios/tests/
  - budget_dashboard/  (future dashboard tests)

without needing to cd into each directory first.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent
_DASHBOARD_ROOT = _REPO_ROOT / "budget_dashboard"
_EXTRACTION_ROOT = _REPO_ROOT / "Project" / "estudo_faturas_municipios"

for _path in (_DASHBOARD_ROOT, _EXTRACTION_ROOT):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)
