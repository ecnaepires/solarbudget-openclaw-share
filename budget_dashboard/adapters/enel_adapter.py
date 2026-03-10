from __future__ import annotations

from .celesc_adapter import CelescAdapter


class EnelAdapter(CelescAdapter):
    """
    Initial ENEL adapter reuses CELESC mapping rules.
    If extractor schema differs, update only this adapter.
    """

    name = "enel"
    description = "Adapter inicial ENEL (herda mapeamento base CELESC)."
