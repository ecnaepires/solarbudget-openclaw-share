"""Step validation framework for the dashboard."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import streamlit as st

from ui.context import DashboardContext


@dataclass
class ValidationMessage:
    level: str  # "error", "warning", "info"
    text: str


def validate_step_a(ctx: DashboardContext) -> List[ValidationMessage]:
    messages = []
    setup = ctx.setup
    if not setup.get("client"):
        messages.append(ValidationMessage("warning", "Cliente nao informado."))
    if not setup.get("project_name"):
        messages.append(ValidationMessage("warning", "Nome do projeto nao informado."))
    if not setup.get("city"):
        messages.append(ValidationMessage("warning", "Cidade nao selecionada."))
    mwp = float(setup.get("mwp_ac", 0) or 0)
    if mwp <= 0:
        messages.append(ValidationMessage("info", "MWp AC nao definido. Aplique um dimensionamento."))
    return messages


def validate_step_b(ctx: DashboardContext) -> List[ValidationMessage]:
    messages = []
    scenario = ctx.active_scenario
    if not scenario.get("module_model"):
        messages.append(ValidationMessage("error", "Nenhum modulo selecionado."))
    if not scenario.get("inverter_model"):
        messages.append(ValidationMessage("error", "Nenhum inversor selecionado."))
    return messages


def validate_step_c(ctx: DashboardContext) -> List[ValidationMessage]:
    messages = []
    bos_overrides = ctx.active_scenario.get("bos_overrides", {})
    for item in ctx.bos_catalog:
        code = str(item.get("item_code", ""))
        override = bos_overrides.get(code, {})
        enabled = bool(override.get("enabled", True))
        if not enabled:
            continue
        price_sem = float(override.get("unit_price_sem", item.get("unit_price_sem", 0.0)) or 0.0)
        price_com = float(override.get("unit_price_com", item.get("unit_price_com", 0.0)) or 0.0)
        name = item.get("item_name", code)
        if price_sem < 0 or price_com < 0:
            messages.append(ValidationMessage("error", f"BOS '{name}': preco negativo nao permitido."))
        scaling_rule = override.get("scaling_rule", item.get("scaling_rule", "fixed"))
        valid_rules = {"fixed", "per_mwp_ac", "per_kwp_dc", "per_string", "percent_of_capex"}
        if scaling_rule not in valid_rules:
            messages.append(ValidationMessage("warning", f"BOS '{name}': regra de escalonamento invalida '{scaling_rule}'."))
    return messages


def validate_step_d(ctx: DashboardContext) -> List[ValidationMessage]:
    messages = []
    mwp = float(ctx.setup.get("mwp_ac", 0) or 0)
    if mwp <= 0:
        messages.append(ValidationMessage("warning", "MWp nao definido — revisao parcial."))
    return messages


def validate_step_e(ctx: DashboardContext) -> List[ValidationMessage]:
    messages = []
    mwp = float(ctx.setup.get("mwp_ac", 0) or 0)
    if mwp <= 0:
        messages.append(ValidationMessage("error", "MWp AC nao definido. Aplique um dimensionamento antes de exportar."))
    return messages


STEP_VALIDATORS = {
    "A": validate_step_a,
    "B": validate_step_b,
    "C": validate_step_c,
    "D": validate_step_d,
    "E": validate_step_e,
}


def render_validation_bar(ctx: DashboardContext) -> None:
    """Render validation messages at the top of the current step."""
    step = ctx.wizard_step
    validator = STEP_VALIDATORS.get(step)
    if validator is None:
        return

    messages = validator(ctx)
    if not messages:
        return

    for msg in messages:
        if msg.level == "error":
            st.error(msg.text)
        elif msg.level == "warning":
            st.warning(msg.text)
        elif msg.level == "info":
            st.info(msg.text)


def step_completion_status(ctx: DashboardContext) -> dict[str, bool]:
    """Check completion status for each step (for progress indicator)."""
    setup = ctx.setup
    scenario = ctx.active_scenario
    mwp = float(setup.get("mwp_ac", 0) or 0)

    return {
        "A": bool(setup.get("client") and setup.get("city") and mwp > 0),
        "B": bool(scenario.get("module_model") and scenario.get("inverter_model")),
        "C": True,  # BOS always has defaults
        "D": True,  # Review is always viewable
        "E": mwp > 0,
    }
