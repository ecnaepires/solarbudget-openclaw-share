"""Tests for scenario_service: initialization, sizing metrics, warnings."""
import pytest

from services.scenario_service import (
    DEFAULT_SCENARIO_NAMES,
    _default_scenario,
    _bos_override_from_catalog,
    compute_sizing_metrics,
    find_by_model,
    initialize_project_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_module():
    return {
        "model": "MOD-TEST", "brand": "Brand", "wp": 550.0,
        "vmp": 41.0, "voc": 49.5, "temp_coeff_voc": -0.29,
        "price_sem_bdi_per_kwp": 1200.0, "price_com_bdi_per_kwp": 1450.0,
        "supplier": "SupA", "notes": "", "pricing_version": "V1",
    }


@pytest.fixture
def minimal_inverter():
    return {
        "model": "INV-TEST", "brand": "Brand", "kw": 100.0,
        "mppt_min_v": 200.0, "mppt_max_v": 800.0,
        "price_sem_bdi": 50000.0, "price_com_bdi": 60000.0,
        "supplier": "SupA", "notes": "", "pricing_version": "V1",
    }


@pytest.fixture
def empty_catalogs():
    return {
        "modules": [],
        "inverters": [],
        "bos": [],
        "pricing": [],
    }


@pytest.fixture
def full_catalogs(minimal_module, minimal_inverter):
    return {
        "modules": [minimal_module],
        "inverters": [minimal_inverter],
        "bos": [
            {
                "item_code": "BOS-001", "item_name": "Cable DC",
                "unit": "m", "scaling_rule": "per_kwp_dc",
                "base_qty_per_kwp": 10.0, "base_qty_per_mwp": None,
                "base_qty_fixed": None, "base_qty_per_string": None,
                "unit_price_sem": 2.5, "unit_price_com": 3.0,
            }
        ],
        "pricing": [{"version_id": "V1", "date": "2025-01", "description": "Base", "source": "manual"}],
    }


# ---------------------------------------------------------------------------
# _bos_override_from_catalog
# ---------------------------------------------------------------------------

def test_bos_override_from_catalog_structure():
    item = {
        "scaling_rule": "per_kwp_dc",
        "unit_price_sem": 2.5,
        "unit_price_com": 3.0,
        "base_qty_per_kwp": 10.0,
        "base_qty_per_mwp": None,
        "base_qty_fixed": None,
        "base_qty_per_string": None,
    }
    override = _bos_override_from_catalog(item)
    assert override["enabled"] is True
    assert override["scaling_rule"] == "per_kwp_dc"
    assert override["unit_price_sem"] == pytest.approx(2.5)
    assert override["unit_price_com"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# _default_scenario
# ---------------------------------------------------------------------------

def test_default_scenario_structure(full_catalogs):
    scenario = _default_scenario(
        "Scenario A", "MOD-TEST", "INV-TEST", "V1", full_catalogs["bos"]
    )
    assert scenario["name"] == "Scenario A"
    assert scenario["module_model"] == "MOD-TEST"
    assert scenario["inverter_model"] == "INV-TEST"
    assert scenario["dc_ac_ratio"] == pytest.approx(1.20)
    assert "bos_overrides" in scenario
    assert "BOS-001" in scenario["bos_overrides"]


def test_default_scenario_empty_bos():
    scenario = _default_scenario("Scenario A", "", "", "V1", [])
    assert scenario["bos_overrides"] == {}


# ---------------------------------------------------------------------------
# initialize_project_state — fresh state
# ---------------------------------------------------------------------------

def test_initialize_fresh_state(full_catalogs):
    state = initialize_project_state(
        None,
        full_catalogs["modules"],
        full_catalogs["inverters"],
        full_catalogs["pricing"],
        full_catalogs["bos"],
    )
    assert "setup" in state
    assert "scenarios" in state
    assert state["setup"]["mwp_ac"] == 0.0
    assert state["wizard_step"] == "A"
    for name in DEFAULT_SCENARIO_NAMES:
        assert name in state["scenarios"]


def test_initialize_fresh_uses_first_catalog_defaults(full_catalogs):
    state = initialize_project_state(
        None,
        full_catalogs["modules"],
        full_catalogs["inverters"],
        full_catalogs["pricing"],
        full_catalogs["bos"],
    )
    scenario = state["scenarios"][DEFAULT_SCENARIO_NAMES[0]]
    assert scenario["module_model"] == "MOD-TEST"
    assert scenario["inverter_model"] == "INV-TEST"
    assert scenario["pricing_version"] == "V1"


# ---------------------------------------------------------------------------
# initialize_project_state — existing state merging
# ---------------------------------------------------------------------------

def test_initialize_existing_preserves_client(full_catalogs):
    existing = {
        "setup": {"client": "Acme Corp", "mwp_ac": 0.0},
        "scenarios": {},
        "active_scenario": DEFAULT_SCENARIO_NAMES[0],
        "wizard_step": "B",
    }
    state = initialize_project_state(
        existing,
        full_catalogs["modules"],
        full_catalogs["inverters"],
        full_catalogs["pricing"],
        full_catalogs["bos"],
    )
    assert state["setup"]["client"] == "Acme Corp"
    assert state["wizard_step"] == "B"


def test_initialize_extraction_mwp_enforced(full_catalogs):
    existing = {
        "setup": {"mwp_ac": 0.0, "extraction_imported_mwp": 2.5},
        "scenarios": {},
    }
    state = initialize_project_state(
        existing,
        full_catalogs["modules"],
        full_catalogs["inverters"],
        full_catalogs["pricing"],
        full_catalogs["bos"],
    )
    assert state["setup"]["mwp_ac"] == pytest.approx(2.5)


def test_initialize_no_extraction_mwp_resets_to_zero(full_catalogs):
    existing = {
        "setup": {"mwp_ac": 5.0},  # no extraction_imported_mwp key
        "scenarios": {},
    }
    state = initialize_project_state(
        existing,
        full_catalogs["modules"],
        full_catalogs["inverters"],
        full_catalogs["pricing"],
        full_catalogs["bos"],
    )
    assert state["setup"]["mwp_ac"] == 0.0


def test_initialize_adds_missing_scenarios(full_catalogs):
    existing = {
        "setup": {},
        "scenarios": {DEFAULT_SCENARIO_NAMES[0]: {"name": DEFAULT_SCENARIO_NAMES[0]}},
    }
    state = initialize_project_state(
        existing,
        full_catalogs["modules"],
        full_catalogs["inverters"],
        full_catalogs["pricing"],
        full_catalogs["bos"],
    )
    for name in DEFAULT_SCENARIO_NAMES:
        assert name in state["scenarios"]


# ---------------------------------------------------------------------------
# find_by_model
# ---------------------------------------------------------------------------

def test_find_by_model_found(minimal_module):
    result = find_by_model([minimal_module], "MOD-TEST")
    assert result is minimal_module


def test_find_by_model_not_found(minimal_module):
    result = find_by_model([minimal_module], "NONEXISTENT")
    assert result is None


def test_find_by_model_empty_list():
    assert find_by_model([], "MOD-TEST") is None


# ---------------------------------------------------------------------------
# compute_sizing_metrics — correct calculations
# ---------------------------------------------------------------------------

def test_compute_sizing_basic(minimal_module, minimal_inverter):
    setup = {"mwp_ac": 1.0}
    scenario = {
        "dc_ac_ratio": 1.20,
        "modules_per_string": 28,
        "strings_per_combiner": 24,
        "spare_factor": 1.05,
        "module_price_sem_override": None,
        "module_price_com_override": None,
        "inverter_price_sem_override": None,
        "inverter_price_com_override": None,
    }
    result = compute_sizing_metrics(setup, scenario, minimal_module, minimal_inverter)

    assert result["mwp_ac"] == pytest.approx(1.0)
    assert result["ac_kwp"] == pytest.approx(1000.0)
    assert result["dc_kwp"] == pytest.approx(1200.0)
    assert result["module_count"] > 0
    assert result["inverter_qty"] > 0
    assert isinstance(result["warnings"], list)


def test_compute_sizing_dc_ac_ratio_out_of_range(minimal_module, minimal_inverter):
    setup = {"mwp_ac": 1.0}
    scenario = {
        "dc_ac_ratio": 2.0,  # above DC_AC_RATIO_MAX (1.40)
        "modules_per_string": 28,
        "strings_per_combiner": 24,
        "spare_factor": 1.05,
        "module_price_sem_override": None,
        "module_price_com_override": None,
        "inverter_price_sem_override": None,
        "inverter_price_com_override": None,
    }
    result = compute_sizing_metrics(setup, scenario, minimal_module, minimal_inverter)
    assert any("DC/AC" in w or "dc/ac" in w.lower() for w in result["warnings"])


def test_compute_sizing_mppt_violation(minimal_module, minimal_inverter):
    """Inverter with very narrow MPPT window → string voltage warnings."""
    narrow_inverter = dict(minimal_inverter)
    narrow_inverter["mppt_min_v"] = 700.0
    narrow_inverter["mppt_max_v"] = 750.0

    setup = {"mwp_ac": 1.0}
    scenario = {
        "dc_ac_ratio": 1.20,
        "modules_per_string": 28,
        "strings_per_combiner": 24,
        "spare_factor": 1.05,
        "module_price_sem_override": None,
        "module_price_com_override": None,
        "inverter_price_sem_override": None,
        "inverter_price_com_override": None,
    }
    result = compute_sizing_metrics(setup, scenario, minimal_module, narrow_inverter)
    # At least one MPPT-related warning should be present
    assert any("MPPT" in w or "mppt" in w.lower() or "Vmp" in w or "Voc" in w for w in result["warnings"])


def test_compute_sizing_price_override(minimal_module, minimal_inverter):
    setup = {"mwp_ac": 1.0}
    scenario = {
        "dc_ac_ratio": 1.20,
        "modules_per_string": 28,
        "strings_per_combiner": 24,
        "spare_factor": 1.05,
        "module_price_sem_override": 999.0,
        "module_price_com_override": None,
        "inverter_price_sem_override": None,
        "inverter_price_com_override": None,
    }
    result = compute_sizing_metrics(setup, scenario, minimal_module, minimal_inverter)
    assert result["module_price_sem"] == pytest.approx(999.0)
    # com_override is None → falls back to catalog
    assert result["module_price_com"] == pytest.approx(minimal_module["price_com_bdi_per_kwp"])
