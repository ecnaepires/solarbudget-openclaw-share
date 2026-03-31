"""Tests for step validator functions in ui/validators.py."""
import pytest

from ui.context import DashboardContext
from ui.validators import (
    ValidationMessage,
    step_completion_status,
    validate_step_a,
    validate_step_b,
    validate_step_c,
    validate_step_d,
    validate_step_e,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(
    client="Acme",
    project_name="Projeto Solar",
    city="Sao Paulo",
    mwp_ac=2.0,
    module_model="MOD-A",
    inverter_model="INV-A",
    bos_overrides=None,
    bos_catalog=None,
    wizard_step="A",
):
    setup = {
        "client": client,
        "project_name": project_name,
        "city": city,
        "mwp_ac": mwp_ac,
        "city_ibge_code": "",
        "state": "SP",
        "project_date": "2025-01-01",
        "reference_mwp_ac": 0.0,
    }
    active_scenario = {
        "name": "Scenario A",
        "module_model": module_model,
        "inverter_model": inverter_model,
        "bos_overrides": bos_overrides or {},
    }
    project = {
        "setup": setup,
        "scenarios": {"Scenario A": active_scenario},
        "active_scenario": "Scenario A",
        "wizard_step": wizard_step,
    }
    return DashboardContext(
        project=project,
        active_scenario=active_scenario,
        selected_scenario="Scenario A",
        scenario_names=["Scenario A"],
        modules_catalog=[],
        inverters_catalog=[],
        bos_catalog=bos_catalog or [],
        pricing_versions=[],
        excel_map={},
    )


def _levels(messages):
    return [m.level for m in messages]


def _texts(messages):
    return [m.text for m in messages]


# ---------------------------------------------------------------------------
# validate_step_a
# ---------------------------------------------------------------------------

class TestValidateStepA:
    def test_complete_setup_no_messages(self):
        ctx = _make_ctx()
        assert validate_step_a(ctx) == []

    def test_missing_client_warns(self):
        ctx = _make_ctx(client="")
        msgs = validate_step_a(ctx)
        assert any("cliente" in t.lower() for t in _texts(msgs))
        assert "warning" in _levels(msgs)

    def test_missing_project_name_warns(self):
        ctx = _make_ctx(project_name="")
        msgs = validate_step_a(ctx)
        assert any("projeto" in t.lower() for t in _texts(msgs))

    def test_missing_city_warns(self):
        ctx = _make_ctx(city="")
        msgs = validate_step_a(ctx)
        assert any("cidade" in t.lower() for t in _texts(msgs))

    def test_zero_mwp_info(self):
        ctx = _make_ctx(mwp_ac=0.0)
        msgs = validate_step_a(ctx)
        assert any("mwp" in t.lower() or "mwp" in t for t in _texts(msgs))
        assert "info" in _levels(msgs)

    def test_all_missing_returns_multiple_messages(self):
        ctx = _make_ctx(client="", project_name="", city="", mwp_ac=0.0)
        assert len(validate_step_a(ctx)) >= 3


# ---------------------------------------------------------------------------
# validate_step_b
# ---------------------------------------------------------------------------

class TestValidateStepB:
    def test_both_set_no_errors(self):
        ctx = _make_ctx()
        assert validate_step_b(ctx) == []

    def test_missing_module_errors(self):
        ctx = _make_ctx(module_model="")
        msgs = validate_step_b(ctx)
        assert any("modulo" in t.lower() for t in _texts(msgs))
        assert "error" in _levels(msgs)

    def test_missing_inverter_errors(self):
        ctx = _make_ctx(inverter_model="")
        msgs = validate_step_b(ctx)
        assert any("inversor" in t.lower() for t in _texts(msgs))
        assert "error" in _levels(msgs)

    def test_both_missing_returns_two_errors(self):
        ctx = _make_ctx(module_model="", inverter_model="")
        msgs = validate_step_b(ctx)
        errors = [m for m in msgs if m.level == "error"]
        assert len(errors) == 2


# ---------------------------------------------------------------------------
# validate_step_c
# ---------------------------------------------------------------------------

class TestValidateStepC:
    def _bos_item(self, code="BOS-001", name="Cable", price_sem=2.5, price_com=3.0, rule="per_kwp_dc"):
        return {
            "item_code": code,
            "item_name": name,
            "unit_price_sem": price_sem,
            "unit_price_com": price_com,
            "scaling_rule": rule,
        }

    def test_valid_bos_no_messages(self):
        item = self._bos_item()
        overrides = {"BOS-001": {"enabled": True, "unit_price_sem": 2.5, "unit_price_com": 3.0, "scaling_rule": "per_kwp_dc"}}
        ctx = _make_ctx(bos_catalog=[item], bos_overrides=overrides)
        assert validate_step_c(ctx) == []

    def test_negative_price_error(self):
        item = self._bos_item()
        overrides = {"BOS-001": {"enabled": True, "unit_price_sem": -1.0, "unit_price_com": 3.0, "scaling_rule": "per_kwp_dc"}}
        ctx = _make_ctx(bos_catalog=[item], bos_overrides=overrides)
        msgs = validate_step_c(ctx)
        assert any("negativo" in t.lower() for t in _texts(msgs))
        assert "error" in _levels(msgs)

    def test_invalid_scaling_rule_warning(self):
        item = self._bos_item()
        overrides = {"BOS-001": {"enabled": True, "unit_price_sem": 2.5, "unit_price_com": 3.0, "scaling_rule": "bogus_rule"}}
        ctx = _make_ctx(bos_catalog=[item], bos_overrides=overrides)
        msgs = validate_step_c(ctx)
        assert any("escalonamento" in t.lower() or "scaling" in t.lower() for t in _texts(msgs))
        assert "warning" in _levels(msgs)

    def test_disabled_item_skipped(self):
        item = self._bos_item()
        overrides = {"BOS-001": {"enabled": False, "unit_price_sem": -99.0, "unit_price_com": -99.0, "scaling_rule": "bogus"}}
        ctx = _make_ctx(bos_catalog=[item], bos_overrides=overrides)
        # Disabled items should be skipped entirely
        assert validate_step_c(ctx) == []

    def test_empty_catalog_no_messages(self):
        ctx = _make_ctx(bos_catalog=[], bos_overrides={})
        assert validate_step_c(ctx) == []


# ---------------------------------------------------------------------------
# validate_step_d
# ---------------------------------------------------------------------------

class TestValidateStepD:
    def test_with_mwp_no_warnings(self):
        ctx = _make_ctx(mwp_ac=2.0)
        assert validate_step_d(ctx) == []

    def test_zero_mwp_warning(self):
        ctx = _make_ctx(mwp_ac=0.0)
        msgs = validate_step_d(ctx)
        assert len(msgs) == 1
        assert msgs[0].level == "warning"


# ---------------------------------------------------------------------------
# validate_step_e
# ---------------------------------------------------------------------------

class TestValidateStepE:
    def test_with_mwp_no_errors(self):
        ctx = _make_ctx(mwp_ac=1.5)
        assert validate_step_e(ctx) == []

    def test_zero_mwp_error(self):
        ctx = _make_ctx(mwp_ac=0.0)
        msgs = validate_step_e(ctx)
        assert len(msgs) == 1
        assert msgs[0].level == "error"


# ---------------------------------------------------------------------------
# step_completion_status
# ---------------------------------------------------------------------------

class TestStepCompletionStatus:
    def test_fully_complete(self):
        ctx = _make_ctx()
        status = step_completion_status(ctx)
        assert status["A"] is True
        assert status["B"] is True
        assert status["C"] is True
        assert status["D"] is True
        assert status["E"] is True

    def test_incomplete_a(self):
        ctx = _make_ctx(client="", mwp_ac=0.0)
        status = step_completion_status(ctx)
        assert status["A"] is False

    def test_incomplete_b(self):
        ctx = _make_ctx(module_model="")
        status = step_completion_status(ctx)
        assert status["B"] is False

    def test_incomplete_e(self):
        ctx = _make_ctx(mwp_ac=0.0)
        status = step_completion_status(ctx)
        assert status["E"] is False

    def test_c_and_d_always_true(self):
        ctx = _make_ctx(mwp_ac=0.0, module_model="", inverter_model="")
        status = step_completion_status(ctx)
        assert status["C"] is True
        assert status["D"] is True
