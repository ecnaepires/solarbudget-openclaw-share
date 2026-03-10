"""Step D renderer."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from services.scenario_bundle_service import build_scenario_bundle
from ui.context import DashboardContext
from ui.helpers import add_abbreviation_meanings, format_brl, format_scenario_name, render_nav_buttons
from ui.style import section_end, section_start


def render_step_d(ctx: DashboardContext) -> None:
    section_start("D. Revisao", chip=format_scenario_name(ctx.selected_scenario), solid=True)

    bundles = {
        name: build_scenario_bundle(
            ctx.project,
            name,
            ctx.modules_catalog,
            ctx.inverters_catalog,
            ctx.excel_map,
        )
        for name in ctx.scenario_names
    }

    comparison_rows = []
    for name in ctx.scenario_names:
        scenario = ctx.project["scenarios"][name]
        bundle = bundles[name]
        sizing = bundle["sizing"]
        comparison_rows.append(
            {
                "scenario": name,
                "pricing_version": scenario.get("pricing_version", ""),
                "dc_kwp": sizing["dc_kwp"],
                "module_count": sizing["module_count"],
                "inverter_qty": sizing["inverter_qty"],
                "modules+inverters_com_bdi": sizing["modules_inverters_total_com"],
                "mapped_total_com_bdi": bundle["totals"]["grand_total_com_bdi"],
                "warnings": len(sizing["warnings"]),
            }
        )

    comparison_df = pd.DataFrame(comparison_rows)
    comparison_df = comparison_df.rename(
        columns={
            "scenario": "cenario",
            "pricing_version": "versao_preco",
            "dc_kwp": "dc_kwp",
            "module_count": "qtd_modulos",
            "inverter_qty": "qtd_inversores",
            "modules+inverters_com_bdi": "modulos_inversores_com_bdi",
            "mapped_total_com_bdi": "total_com_bdi_mapeado",
            "warnings": "alertas",
        }
    )
    comparison_df["cenario"] = comparison_df["cenario"].map(format_scenario_name)

    comparison_column_config = {
        col: st.column_config.NumberColumn(col, format="R$ %.2f")
        for col in ("modulos_inversores_com_bdi", "total_com_bdi_mapeado")
        if col in comparison_df.columns
    }

    st.markdown("**Comparacao de cenarios**")
    st.dataframe(
        comparison_df,
        hide_index=True,
        width="stretch",
        column_config=comparison_column_config,
    )

    st.divider()

    active_bundle = bundles[ctx.selected_scenario]
    st.markdown(f"**Detalhes do cenario ativo: {format_scenario_name(ctx.selected_scenario)}**")
    m1, m2, m3 = st.columns(3)
    m1.metric(add_abbreviation_meanings("Total geral SEM BDI"), format_brl(active_bundle["totals"]["grand_total_sem_bdi"]))
    m2.metric(add_abbreviation_meanings("Total geral COM BDI"), format_brl(active_bundle["totals"]["grand_total_com_bdi"]))
    m3.metric(
        add_abbreviation_meanings("Modulos + Inversores COM BDI"),
        format_brl(active_bundle["sizing"]["modules_inverters_total_com"]),
    )

    warnings = active_bundle["sizing"]["warnings"]
    if warnings:
        for message in warnings:
            st.warning(message)
    else:
        st.success("Sem alertas de dimensionamento/razao para o cenario ativo.")

    st.divider()

    sheet_totals_df = pd.DataFrame(active_bundle["sheet_totals"])
    sheet_currency_columns = [
        col
        for col in sheet_totals_df.columns
        if pd.api.types.is_numeric_dtype(sheet_totals_df[col])
        and ("total" in col.lower() or "bdi" in col.lower() or "valor" in col.lower())
    ]
    sheet_column_config = {
        col: st.column_config.NumberColumn(col, format="R$ %.2f")
        for col in sheet_currency_columns
    }

    st.markdown("**Totais das abas mapeadas (previa)**")
    st.dataframe(
        sheet_totals_df,
        hide_index=True,
        width="stretch",
        column_config=sheet_column_config,
    )

    st.divider()

    st.markdown("**Registro dos principais inputs**")
    st.json(
        {
            "setup": ctx.setup,
            "scenario": ctx.project["scenarios"][ctx.selected_scenario],
            "module": active_bundle["module"],
            "inverter": active_bundle["inverter"],
        },
        expanded=False,
    )

    section_end()
    render_nav_buttons(ctx.project)
