"""Dashboard context shared across all step modules."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DashboardContext:
    """Typed container for all data needed by step render functions."""
    project: dict
    active_scenario: dict
    selected_scenario: str
    scenario_names: list[str]
    modules_catalog: list[dict]
    inverters_catalog: list[dict]
    bos_catalog: list[dict]
    pricing_versions: list[dict]
    excel_map: dict
    state_rows: list[dict] = field(default_factory=list)

    @property
    def setup(self) -> dict:
        return self.project["setup"]

    @property
    def wizard_step(self) -> str:
        return self.project.get("wizard_step", "A")
