"""Step B renderer."""
from __future__ import annotations

import streamlit as st

from services.catalog_service import (
    catalog_value_options,
    filter_catalog_rows,
    upsert_inverter_catalog_row,
    upsert_module_catalog_row,
)
from services.scenario_service import compute_sizing_metrics
from ui.context import DashboardContext
from ui.helpers import (
    add_abbreviation_meanings,
    brl_text_input,
    format_all_option,
    format_brl,
    format_scenario_name,
    render_nav_buttons,
    safe_index,
    slugify_filename,
)
from ui.style import section_end, section_start


def render_step_b(ctx: DashboardContext) -> None:
    modules_catalog = ctx.modules_catalog
    inverters_catalog = ctx.inverters_catalog

    section_start("B. Equipamentos", chip=format_scenario_name(ctx.selected_scenario), solid=True)
    st.caption("Selecione versao de preco, ajuste catalogo e configure o dimensionamento do cenario ativo.")

    version_options = [row["version_id"] for row in ctx.pricing_versions]
    if ctx.active_scenario.get("pricing_version") not in version_options:
        ctx.active_scenario["pricing_version"] = version_options[0]

    ctx.active_scenario["pricing_version"] = st.selectbox(
        "Versao da Tabela de Precos",
        version_options,
        index=safe_index(version_options, ctx.active_scenario.get("pricing_version", version_options[0])),
    )
    version_row = next(
        (row for row in ctx.pricing_versions if row["version_id"] == ctx.active_scenario["pricing_version"]),
        None,
    )
    if version_row:
        st.caption(
            f"Data da versao: {version_row['date']} | {version_row['description']} | Fonte: {version_row['source']}"
        )

    with st.expander("Catalogo: adicionar/atualizar modelos (salva em CSV)", expanded=False):
        st.caption(
            "Salva diretamente em catalog/modules.csv e catalog/inverters.csv. "
            "As linhas sao inseridas/atualizadas por modelo + fornecedor + versao de preco."
        )
        mod_col, inv_col = st.columns(2)
        with mod_col:
            with st.form("catalog_module_form"):
                st.markdown("**Adicionar Modulo**")
                cm_brand = st.text_input("Marca", value="Marca Customizada")
                cm_model = st.text_input("Modelo")
                cm_wp = st.number_input("Wp", min_value=1.0, value=600.0, step=1.0)
                cm_vmp = st.number_input("Vmp (V)", min_value=1.0, value=41.5, step=0.1)
                cm_voc = st.number_input("Voc (V)", min_value=1.0, value=49.5, step=0.1)
                cm_tcvoc = st.number_input("Coef. temp Voc (%/C)", value=-0.28, step=0.01)
                cm_sem = brl_text_input(
                    add_abbreviation_meanings("Preco SEM BDI (R$/kWp)"),
                    state_key="catalog_module_price_sem",
                    default_value=float(st.session_state.get("catalog_module_price_sem", 2800.0)),
                )
                cm_com = brl_text_input(
                    add_abbreviation_meanings("Preco COM BDI (R$/kWp)"),
                    state_key="catalog_module_price_com",
                    default_value=float(st.session_state.get("catalog_module_price_com", 3550.0)),
                )
                cm_supplier = st.text_input("Fornecedor", value="Fornecedor Customizado")
                cm_notes = st.text_input("Observacoes", value="")
                if st.form_submit_button("Salvar Modulo no Catalogo"):
                    if not cm_model.strip():
                        st.error("O modelo do modulo e obrigatorio.")
                    elif not cm_supplier.strip():
                        st.error("O fornecedor do modulo e obrigatorio.")
                    else:
                        action = upsert_module_catalog_row(
                            {
                                "model": cm_model.strip(),
                                "brand": cm_brand.strip(),
                                "wp": float(cm_wp),
                                "vmp": float(cm_vmp),
                                "voc": float(cm_voc),
                                "temp_coeff_voc": float(cm_tcvoc),
                                "price_sem_bdi_per_kwp": float(cm_sem),
                                "price_com_bdi_per_kwp": float(cm_com),
                                "supplier": cm_supplier.strip(),
                                "notes": cm_notes.strip(),
                                "pricing_version": ctx.active_scenario["pricing_version"],
                            }
                        )
                        st.success(
                            f"Modulo {action} no catalogo para a versao {ctx.active_scenario['pricing_version']}."
                        )
                        st.rerun()
        with inv_col:
            with st.form("catalog_inverter_form"):
                st.markdown("**Adicionar Inversor**")
                ci_brand = st.text_input("Marca ", value="Marca Customizada")
                ci_model = st.text_input("Modelo ")
                ci_kw = st.number_input("Potencia (kW)", min_value=1.0, value=330.0, step=1.0)
                ci_mppt_min = st.number_input(
                    add_abbreviation_meanings("MPPT min (V)"),
                    min_value=1.0,
                    value=500.0,
                    step=1.0,
                )
                ci_mppt_max = st.number_input(
                    add_abbreviation_meanings("MPPT max (V)"),
                    min_value=1.0,
                    value=1500.0,
                    step=1.0,
                )
                ci_sem = brl_text_input(
                    add_abbreviation_meanings("Preco SEM BDI (R$/unidade)"),
                    state_key="catalog_inverter_price_sem",
                    default_value=float(st.session_state.get("catalog_inverter_price_sem", 47000.0)),
                )
                ci_com = brl_text_input(
                    add_abbreviation_meanings("Preco COM BDI (R$/unidade)"),
                    state_key="catalog_inverter_price_com",
                    default_value=float(st.session_state.get("catalog_inverter_price_com", 59000.0)),
                )
                ci_supplier = st.text_input("Fornecedor ", value="Fornecedor Customizado")
                ci_notes = st.text_input("Observacoes ", value="")
                if st.form_submit_button("Salvar Inversor no Catalogo"):
                    if not ci_model.strip():
                        st.error("O modelo do inversor e obrigatorio.")
                    elif not ci_supplier.strip():
                        st.error("O fornecedor do inversor e obrigatorio.")
                    elif float(ci_mppt_max) <= float(ci_mppt_min):
                        st.error(add_abbreviation_meanings("MPPT max deve ser maior que MPPT min."))
                    else:
                        action = upsert_inverter_catalog_row(
                            {
                                "model": ci_model.strip(),
                                "brand": ci_brand.strip(),
                                "kw": float(ci_kw),
                                "mppt_min_v": float(ci_mppt_min),
                                "mppt_max_v": float(ci_mppt_max),
                                "price_sem_bdi": float(ci_sem),
                                "price_com_bdi": float(ci_com),
                                "supplier": ci_supplier.strip(),
                                "notes": ci_notes.strip(),
                                "pricing_version": ctx.active_scenario["pricing_version"],
                            }
                        )
                        st.success(
                            f"Inversor {action} no catalogo para a versao {ctx.active_scenario['pricing_version']}."
                        )
                        st.rerun()

    section_end()

    st.divider()

    section_start("B. Filtros e Dimensionamento", chip=ctx.active_scenario.get("pricing_version", ""))

    version_filter = ctx.active_scenario["pricing_version"]
    version_modules = filter_catalog_rows(modules_catalog, pricing_version=version_filter)
    version_inverters = filter_catalog_rows(inverters_catalog, pricing_version=version_filter)

    c1, c2 = st.columns(2)
    with c1:
        module_brand_options = catalog_value_options(version_modules, "brand")
        ctx.active_scenario["module_brand_filter"] = st.selectbox(
            "Filtro de Marca do Modulo",
            module_brand_options,
            index=safe_index(module_brand_options, ctx.active_scenario.get("module_brand_filter", "All")),
            format_func=format_all_option,
        )
        module_supplier_options = catalog_value_options(version_modules, "supplier")
        ctx.active_scenario["module_supplier_filter"] = st.selectbox(
            "Filtro de Fornecedor do Modulo",
            module_supplier_options,
            index=safe_index(module_supplier_options, ctx.active_scenario.get("module_supplier_filter", "All")),
            format_func=format_all_option,
        )

    with c2:
        inverter_brand_options = catalog_value_options(version_inverters, "brand")
        ctx.active_scenario["inverter_brand_filter"] = st.selectbox(
            "Filtro de Marca do Inversor",
            inverter_brand_options,
            index=safe_index(inverter_brand_options, ctx.active_scenario.get("inverter_brand_filter", "All")),
            format_func=format_all_option,
        )
        inverter_supplier_options = catalog_value_options(version_inverters, "supplier")
        ctx.active_scenario["inverter_supplier_filter"] = st.selectbox(
            "Filtro de Fornecedor do Inversor",
            inverter_supplier_options,
            index=safe_index(inverter_supplier_options, ctx.active_scenario.get("inverter_supplier_filter", "All")),
            format_func=format_all_option,
        )

    filtered_modules = filter_catalog_rows(
        modules_catalog,
        brand=ctx.active_scenario["module_brand_filter"],
        supplier=ctx.active_scenario["module_supplier_filter"],
        pricing_version=version_filter,
    )
    filtered_inverters = filter_catalog_rows(
        inverters_catalog,
        brand=ctx.active_scenario["inverter_brand_filter"],
        supplier=ctx.active_scenario["inverter_supplier_filter"],
        pricing_version=version_filter,
    )

    if not filtered_modules:
        st.error("Nenhum modulo corresponde aos filtros/versao selecionados.")
        section_end()
        render_nav_buttons(ctx.project)
        return
    if not filtered_inverters:
        st.error("Nenhum inversor corresponde aos filtros/versao selecionados.")
        section_end()
        render_nav_buttons(ctx.project)
        return

    module_display = [f"{row['brand']} | {row['model']} | {row['supplier']}" for row in filtered_modules]
    inverter_display = [f"{row['brand']} | {row['model']} | {row['supplier']}" for row in filtered_inverters]

    current_module_idx = 0
    for idx, row in enumerate(filtered_modules):
        if row["model"] == ctx.active_scenario.get("module_model"):
            current_module_idx = idx
            break
    current_inverter_idx = 0
    for idx, row in enumerate(filtered_inverters):
        if row["model"] == ctx.active_scenario.get("inverter_model"):
            current_inverter_idx = idx
            break

    selected_module_label = st.selectbox("Modelo do Modulo", module_display, index=current_module_idx)
    selected_module = filtered_modules[module_display.index(selected_module_label)]
    ctx.active_scenario["module_model"] = selected_module["model"]

    selected_inverter_label = st.selectbox("Modelo do Inversor", inverter_display, index=current_inverter_idx)
    selected_inverter = filtered_inverters[inverter_display.index(selected_inverter_label)]
    ctx.active_scenario["inverter_model"] = selected_inverter["model"]

    st.markdown("**Sobrescrever precos (opcional, por cenario)**")
    use_override = st.checkbox(
        "Sobrescrever precos de catalogo para este cenario",
        value=ctx.active_scenario.get("module_price_sem_override") is not None
        or ctx.active_scenario.get("inverter_price_sem_override") is not None,
    )

    if use_override:
        scenario_key = slugify_filename(ctx.selected_scenario)
        p1, p2 = st.columns(2)
        with p1:
            ctx.active_scenario["module_price_sem_override"] = brl_text_input(
                add_abbreviation_meanings("Modulo SEM BDI (R$/kWp)"),
                state_key=f"{scenario_key}_module_price_sem_override",
                default_value=float(
                    ctx.active_scenario.get("module_price_sem_override")
                    or selected_module["price_sem_bdi_per_kwp"]
                ),
            )
            ctx.active_scenario["module_price_com_override"] = brl_text_input(
                add_abbreviation_meanings("Modulo COM BDI (R$/kWp)"),
                state_key=f"{scenario_key}_module_price_com_override",
                default_value=float(
                    ctx.active_scenario.get("module_price_com_override")
                    or selected_module["price_com_bdi_per_kwp"]
                ),
            )
        with p2:
            ctx.active_scenario["inverter_price_sem_override"] = brl_text_input(
                add_abbreviation_meanings("Inversor SEM BDI (R$/unidade)"),
                state_key=f"{scenario_key}_inverter_price_sem_override",
                default_value=float(
                    ctx.active_scenario.get("inverter_price_sem_override")
                    or selected_inverter["price_sem_bdi"]
                ),
            )
            ctx.active_scenario["inverter_price_com_override"] = brl_text_input(
                add_abbreviation_meanings("Inversor COM BDI (R$/unidade)"),
                state_key=f"{scenario_key}_inverter_price_com_override",
                default_value=float(
                    ctx.active_scenario.get("inverter_price_com_override")
                    or selected_inverter["price_com_bdi"]
                ),
            )
    else:
        ctx.active_scenario["module_price_sem_override"] = None
        ctx.active_scenario["module_price_com_override"] = None
        ctx.active_scenario["inverter_price_sem_override"] = None
        ctx.active_scenario["inverter_price_com_override"] = None

    s1, s2, s3 = st.columns(3)
    ctx.active_scenario["modules_per_string"] = s1.slider(
        "Modulos por string",
        min_value=10,
        max_value=40,
        value=int(ctx.active_scenario.get("modules_per_string", 28)),
        step=1,
    )
    ctx.active_scenario["strings_per_combiner"] = int(
        s2.number_input(
            "Strings por combiner",
            min_value=1,
            value=int(ctx.active_scenario.get("strings_per_combiner", 24)),
            step=1,
        )
    )
    ctx.active_scenario["spare_factor"] = s3.number_input(
        "Fator de reserva de combiner",
        min_value=1.0,
        value=float(ctx.active_scenario.get("spare_factor", 1.05)),
        step=0.01,
    )

    st.divider()

    sizing = compute_sizing_metrics(ctx.setup, ctx.active_scenario, selected_module, selected_inverter)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(add_abbreviation_meanings("AC kWp"), f"{sizing['ac_kwp']:,.0f}")
    m2.metric(add_abbreviation_meanings("DC kWp"), f"{sizing['dc_kwp']:,.0f}")
    m3.metric("Quantidade de modulos", f"{sizing['module_count']:,}")
    m4.metric("Quantidade de inversores", f"{sizing['inverter_qty']:,}")

    x1, x2, x3, x4 = st.columns(4)
    x1.metric("Modulos/string", f"{sizing['modules_per_string']}")
    x2.metric(add_abbreviation_meanings("Vmp da string (STC)"), f"{sizing['vstring_vmp_stc']:.0f} V")
    x3.metric("Quantidade de strings", f"{sizing['strings']:,}")
    x4.metric("Combiners (+reserva)", f"{sizing['combiners_with_spare']:,}")

    st.write(
        f"Estimativa Voc da string (frio): `{sizing['vstring_voc_cold']:.0f} V` | "
        f"Estimativa Vmp da string (quente): `{sizing['vstring_vmp_hot']:.0f} V`"
    )
    st.write(
        f"{add_abbreviation_meanings('Custo estimado COM BDI')} (modulos + inversores): "
        f"`{format_brl(sizing['modules_inverters_total_com'])}`"
    )
    for warning in sizing["warnings"]:
        st.warning(warning)

    section_end()
    render_nav_buttons(ctx.project)
