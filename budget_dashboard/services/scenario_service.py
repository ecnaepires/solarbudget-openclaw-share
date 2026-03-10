import math
from copy import deepcopy
from datetime import date
from typing import Dict, List, Optional

from config import (
    BRAZIL_MAX_AMBIENT_C,
    BRAZIL_MIN_AMBIENT_C,
    DC_AC_RATIO_MAX,
    DC_AC_RATIO_MIN,
    DEFAULT_HOT_CELL_DELTA_C,
    STC_TEMP_C,
)
from financial_model import (
    adjust_voltage_for_temperature,
    apply_dc_ac_ratio,
    calculate_combiners,
    calculate_inverter_quantity,
    calculate_module_count,
    calculate_strings,
    mw_to_kwp,
    string_voltage,
    string_voltage_vmp,
)


DEFAULT_SCENARIO_NAMES = ["Scenario A", "Scenario B", "Scenario C"]


def _first_value(rows: List[dict], key: str, default=""):
    if not rows:
        return default
    return rows[0].get(key, default)


def _bos_override_from_catalog(item: dict) -> dict:
    return {
        "enabled": True,
        "scaling_rule": item.get("scaling_rule", "fixed"),
        "unit_price_sem": float(item.get("unit_price_sem", 0.0) or 0.0),
        "unit_price_com": float(item.get("unit_price_com", 0.0) or 0.0),
        "base_qty_per_mwp": item.get("base_qty_per_mwp"),
        "base_qty_per_kwp": item.get("base_qty_per_kwp"),
        "base_qty_fixed": item.get("base_qty_fixed"),
        "base_qty_per_string": item.get("base_qty_per_string"),
    }


def _default_scenario(
    scenario_name: str,
    default_module_model: str,
    default_inverter_model: str,
    default_version: str,
    bos_catalog: List[dict],
) -> dict:
    bos_overrides = {
        item["item_code"]: _bos_override_from_catalog(item)
        for item in bos_catalog
        if item.get("item_code")
    }

    return {
        "name": scenario_name,
        "pricing_version": default_version,
        "module_brand_filter": "All",
        "module_supplier_filter": "All",
        "inverter_brand_filter": "All",
        "inverter_supplier_filter": "All",
        "module_model": default_module_model,
        "inverter_model": default_inverter_model,
        "dc_ac_ratio": 1.20,
        "modules_per_string": 28,
        "strings_per_combiner": 24,
        "spare_factor": 1.05,
        "module_price_sem_override": None,
        "module_price_com_override": None,
        "inverter_price_sem_override": None,
        "inverter_price_com_override": None,
        "bos_overrides": bos_overrides,
    }


def initialize_project_state(
    project_state: Optional[dict],
    modules_catalog: List[dict],
    inverters_catalog: List[dict],
    pricing_versions: List[dict],
    bos_catalog: List[dict],
) -> dict:
    default_version = _first_value(pricing_versions, "version_id", "PV-BASE")
    default_module = _first_value(modules_catalog, "model", "")
    default_inverter = _first_value(inverters_catalog, "model", "")

    if project_state is None:
        scenarios = {
            name: _default_scenario(
                name,
                default_module,
                default_inverter,
                default_version,
                bos_catalog,
            )
            for name in DEFAULT_SCENARIO_NAMES
        }
        return {
            "setup": {
                "client": "",
                "city": "Sao Paulo",
                "city_ibge_code": "",
                "state": "SP",
                "project_name": "Projeto Solar",
                "project_date": date.today().isoformat(),
                "mwp_ac": 0.0,
                "reference_mwp_ac": 0.0,
            },
            "scenarios": scenarios,
            "active_scenario": DEFAULT_SCENARIO_NAMES[0],
            "wizard_step": "A",
        }

    project = deepcopy(project_state)
    project.setdefault("setup", {})
    setup = project["setup"]
    setup.setdefault("client", "")
    setup.setdefault("city", "Sao Paulo")
    setup.setdefault("city_ibge_code", "")
    setup.setdefault("state", "SP")
    setup.setdefault("project_name", "Projeto Solar")
    setup.setdefault("project_date", date.today().isoformat())
    setup.setdefault("mwp_ac", 0.0)
    setup.setdefault("reference_mwp_ac", 0.0)

    # Enforce extraction as the single source of truth for project MWp.
    imported_mwp = setup.get("extraction_imported_mwp")
    if imported_mwp is None:
        setup["mwp_ac"] = 0.0
    else:
        try:
            setup["mwp_ac"] = float(imported_mwp)
        except (TypeError, ValueError):
            setup["mwp_ac"] = 0.0

    project.setdefault("scenarios", {})
    for scenario_name in DEFAULT_SCENARIO_NAMES:
        if scenario_name not in project["scenarios"]:
            project["scenarios"][scenario_name] = _default_scenario(
                scenario_name,
                default_module,
                default_inverter,
                default_version,
                bos_catalog,
            )
        else:
            scenario = project["scenarios"][scenario_name]
            template = _default_scenario(
                scenario_name,
                default_module,
                default_inverter,
                default_version,
                bos_catalog,
            )
            for key, value in template.items():
                scenario.setdefault(key, value)

            # Keep BOS override map in sync with latest catalog rows.
            bos_overrides = scenario.get("bos_overrides", {})
            for item in bos_catalog:
                item_code = item.get("item_code")
                if item_code and item_code not in bos_overrides:
                    bos_overrides[item_code] = _bos_override_from_catalog(item)
            scenario["bos_overrides"] = bos_overrides

    active = project.get("active_scenario", DEFAULT_SCENARIO_NAMES[0])
    if active not in project["scenarios"]:
        project["active_scenario"] = DEFAULT_SCENARIO_NAMES[0]
    project.setdefault("wizard_step", "A")
    return project


def find_by_model(rows: List[dict], model_name: str) -> Optional[dict]:
    for row in rows:
        if row.get("model") == model_name:
            return row
    return None


def effective_price(value_override, fallback_value: float) -> float:
    if value_override is None:
        return float(fallback_value)
    return float(value_override)


def compute_sizing_metrics(setup: dict, scenario: dict, module: dict, inverter: dict) -> dict:
    mwp_ac = float(setup.get("mwp_ac", 0.0))
    dc_ac_ratio = float(scenario.get("dc_ac_ratio", 1.2))
    modules_per_string = int(scenario.get("modules_per_string", 28))
    strings_per_combiner = int(scenario.get("strings_per_combiner", 24))
    spare_factor = float(scenario.get("spare_factor", 1.05))

    ac_kwp = mw_to_kwp(mwp_ac)
    dc_kwp = apply_dc_ac_ratio(ac_kwp, dc_ac_ratio)

    module_count = calculate_module_count(dc_kwp, float(module["wp"]))
    inverter_qty = calculate_inverter_quantity(ac_kwp, float(inverter["kw"]))

    strings = calculate_strings(module_count, modules_per_string)
    combiners = calculate_combiners(strings, strings_per_combiner)
    combiners_with_spare = math.ceil(combiners * spare_factor)

    vstring_vmp_stc = string_voltage_vmp(modules_per_string, float(module["vmp"]))
    module_voc_cold = adjust_voltage_for_temperature(
        float(module["voc"]),
        float(module.get("temp_coeff_voc", 0.0)),
        BRAZIL_MIN_AMBIENT_C,
        STC_TEMP_C,
    )
    vstring_voc_cold = string_voltage(modules_per_string, module_voc_cold)

    module_vmp_hot = adjust_voltage_for_temperature(
        float(module["vmp"]),
        float(module.get("temp_coeff_voc", 0.0)),
        BRAZIL_MAX_AMBIENT_C + DEFAULT_HOT_CELL_DELTA_C,
        STC_TEMP_C,
    )
    vstring_vmp_hot = string_voltage(modules_per_string, module_vmp_hot)

    module_price_sem = effective_price(
        scenario.get("module_price_sem_override"),
        float(module["price_sem_bdi_per_kwp"]),
    )
    module_price_com = effective_price(
        scenario.get("module_price_com_override"),
        float(module["price_com_bdi_per_kwp"]),
    )
    inverter_price_sem = effective_price(
        scenario.get("inverter_price_sem_override"),
        float(inverter["price_sem_bdi"]),
    )
    inverter_price_com = effective_price(
        scenario.get("inverter_price_com_override"),
        float(inverter["price_com_bdi"]),
    )

    modules_cost_sem = dc_kwp * module_price_sem
    modules_cost_com = dc_kwp * module_price_com
    inverters_cost_sem = inverter_qty * inverter_price_sem
    inverters_cost_com = inverter_qty * inverter_price_com

    warnings: List[str] = []
    if dc_ac_ratio < DC_AC_RATIO_MIN or dc_ac_ratio > DC_AC_RATIO_MAX:
        warnings.append(
            f"Razao DC/AC {dc_ac_ratio:.2f} fora da faixa recomendada "
            f"[{DC_AC_RATIO_MIN:.2f}, {DC_AC_RATIO_MAX:.2f}]."
        )

    mppt_min = float(inverter["mppt_min_v"])
    mppt_max = float(inverter["mppt_max_v"])
    if vstring_vmp_stc < mppt_min:
        warnings.append(
            f"Vmp da string em STC ({vstring_vmp_stc:.0f}V) abaixo do MPPT minimo ({mppt_min:.0f}V)."
        )
    if vstring_vmp_stc > mppt_max:
        warnings.append(
            f"Vmp da string em STC ({vstring_vmp_stc:.0f}V) acima do MPPT maximo ({mppt_max:.0f}V)."
        )
    if vstring_voc_cold > mppt_max:
        warnings.append(
            f"Voc da string no frio ({vstring_voc_cold:.0f}V em {BRAZIL_MIN_AMBIENT_C:.0f}C) acima do MPPT maximo ({mppt_max:.0f}V)."
        )
    if vstring_vmp_hot < mppt_min:
        warnings.append(
            f"Vmp da string no quente ({vstring_vmp_hot:.0f}V em {BRAZIL_MAX_AMBIENT_C + DEFAULT_HOT_CELL_DELTA_C:.0f}C de celula) abaixo do MPPT minimo ({mppt_min:.0f}V)."
        )

    return {
        "mwp_ac": mwp_ac,
        "ac_kwp": ac_kwp,
        "dc_kwp": dc_kwp,
        "dc_ac_ratio": dc_ac_ratio,
        "module_count": module_count,
        "inverter_qty": inverter_qty,
        "modules_per_string": modules_per_string,
        "strings_per_combiner": strings_per_combiner,
        "strings": strings,
        "combiners": combiners,
        "combiners_with_spare": combiners_with_spare,
        "vstring_vmp_stc": vstring_vmp_stc,
        "vstring_vmp_hot": vstring_vmp_hot,
        "vstring_voc_cold": vstring_voc_cold,
        "module_price_sem": module_price_sem,
        "module_price_com": module_price_com,
        "inverter_price_sem": inverter_price_sem,
        "inverter_price_com": inverter_price_com,
        "modules_cost_sem": modules_cost_sem,
        "modules_cost_com": modules_cost_com,
        "inverters_cost_sem": inverters_cost_sem,
        "inverters_cost_com": inverters_cost_com,
        "modules_inverters_total_sem": modules_cost_sem + inverters_cost_sem,
        "modules_inverters_total_com": modules_cost_com + inverters_cost_com,
        "warnings": warnings,
    }
