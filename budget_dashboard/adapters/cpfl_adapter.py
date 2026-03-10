from __future__ import annotations

from .celesc_adapter import CelescAdapter


class CpflAdapter(CelescAdapter):
    """
    Initial CPFL adapter reuses CELESC mapping rules.
    If extractor schema differs, update only this adapter.
    """

    name = "cpfl"
    description = "Adapter inicial CPFL (herda mapeamento base CELESC)."
