"""Scenario bundling helpers for review/export steps."""
from __future__ import annotations

from typing import List

from services.excel_map_service import build_export_updates_from_map, summarize_sheet_totals
from services.scenario_service import compute_sizing_metrics, find_by_model


def build_scenario_bundle(
    project: dict,
    scenario_name: str,
    modules_catalog: List[dict],
    inverters_catalog: List[dict],
    excel_map: dict,
) -> dict:
    setup = project["setup"]
    scenario = project["scenarios"][scenario_name]

    module = find_by_model(modules_catalog, scenario.get("module_model", ""))
    inverter = find_by_model(inverters_catalog, scenario.get("inverter_model", ""))
    if module is None:
        module = modules_catalog[0]
    if inverter is None:
        inverter = inverters_catalog[0]

    sizing = compute_sizing_metrics(setup, scenario, module, inverter)
    updates, line_items = build_export_updates_from_map(
        excel_map=excel_map,
        setup=setup,
        scenario=scenario,
        sizing=sizing,
    )
    sheet_totals = summarize_sheet_totals(line_items)

    total_sem = float(sum(item["total_sem_bdi"] for item in sheet_totals))
    total_com = float(sum(item["total_com_bdi"] for item in sheet_totals))

    return {
        "module": module,
        "inverter": inverter,
        "sizing": sizing,
        "updates": updates,
        "line_items": line_items,
        "sheet_totals": sheet_totals,
        "totals": {
            "grand_total_sem_bdi": total_sem,
            "grand_total_com_bdi": total_com,
        },
    }
