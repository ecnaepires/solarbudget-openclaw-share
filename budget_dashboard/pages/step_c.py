"""Step C renderer."""
from __future__ import annotations

import streamlit as st

from services.bos_service import bos_editor_dataframe, update_bos_overrides_from_editor
from services.scenario_bundle_service import build_scenario_bundle
from ui.context import DashboardContext
from ui.helpers import (
    SCALING_RULE_OPTIONS,
    add_abbreviation_meanings,
    format_brl,
    format_scenario_name,
    render_nav_buttons,
)
from ui.style import section_end, section_start


def render_step_c(ctx: DashboardContext) -> None:
    section_start("C. BOS / Civil / Administrativo", chip=format_scenario_name(ctx.selected_scenario), solid=True)
    st.caption(
        "Ative/desative linhas de custo e ajuste premissas de escala/preco. "
        "Esses overrides alimentam o mapa do Excel na exportacao."
    )

    bos_df = bos_editor_dataframe(ctx.bos_catalog, ctx.active_scenario)
    with st.form("bos_editor_form"):
        edited_bos_df = st.data_editor(
            bos_df,
            hide_index=True,
            width="stretch",
            column_config={
                "item_code": st.column_config.TextColumn("Item", width="small"),
                "item_name": st.column_config.TextColumn("Descricao", width="large"),
                "unit": st.column_config.TextColumn("Unidade", width="small"),
                "enabled": st.column_config.CheckboxColumn("Ativo"),
                "scaling_rule": st.column_config.SelectboxColumn(
                    "Regra de escala",
                    options=SCALING_RULE_OPTIONS,
                ),
                "base_qty_per_mwp": st.column_config.NumberColumn(
                    add_abbreviation_meanings("Qtd / MWp AC"),
                    format="%.6f",
                ),
                "base_qty_per_kwp": st.column_config.NumberColumn(
                    add_abbreviation_meanings("Qtd / kWp DC"),
                    format="%.6f",
                ),
                "base_qty_per_string": st.column_config.NumberColumn("Qtd / string", format="%.6f"),
                "base_qty_fixed": st.column_config.NumberColumn("Qtd fixa", format="%.6f"),
                "unit_price_sem": st.column_config.NumberColumn(
                    add_abbreviation_meanings("Preco unitario SEM"),
                    format="%.4f",
                ),
                "unit_price_com": st.column_config.NumberColumn(
                    add_abbreviation_meanings("Preco unitario COM"),
                    format="%.4f",
                ),
            },
            num_rows="fixed",
        )
        if st.form_submit_button(f"Salvar configuracoes de {add_abbreviation_meanings('BOS')} / Civil / Administrativo"):
            update_bos_overrides_from_editor(ctx.active_scenario, edited_bos_df)
            st.success("Overrides do cenario salvos.")

    st.divider()

    bundle_preview = build_scenario_bundle(
        ctx.project,
        ctx.selected_scenario,
        ctx.modules_catalog,
        ctx.inverters_catalog,
        ctx.excel_map,
    )
    total_com = bundle_preview["totals"]["grand_total_com_bdi"]
    st.metric(add_abbreviation_meanings("Previa do total COM BDI (todas as abas mapeadas)"), format_brl(total_com))

    section_end()
    render_nav_buttons(ctx.project)
