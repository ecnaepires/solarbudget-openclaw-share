from copy import deepcopy
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
import hashlib
import importlib
import json
import re
import sys
import tempfile
from typing import Any, List, Optional
import unicodedata

import pandas as pd
import streamlit as st
from openpyxl import load_workbook

from adapters import detect_adapter, list_adapters, reload_registry
from adapters.base import MONTH_MAP
from budget import ContractSchemaError, REQUIRED_CONTRACT_COLUMNS
from budget.pipeline import BudgetInputs, build_budget_pipeline, read_contract_dataframe_raw
from config import (
    ASSETS_DIR,
    DEFAULT_CAPEX_BRL_PER_MWP,
    DEFAULT_MONTHS_TO_USE,
    DEFAULT_FUSION_EXPECTED_MONTHS,
    EXCEL_MAP_PATH,
    EXTRACTION_CONTRACT_MASTER_PATH,
    EXTRACTION_LOGS_DIR,
    EXTRACTION_OUTPUTS_DIR,
)
from excel_engine import apply_dynamic_totals
from extraction_runner import (
    build_run_id,
    contract_meta_path,
    copy_contract_file,
    ensure_contract_master,
    get_presets,
    load_contract_metadata,
    resolve_preset_command,
    run_extractor_cli,
    scan_run_history,
    tail_log_lines,
)
from services.catalog_service import (
    load_bos_catalog,
    load_inverters_catalog,
    load_modules_catalog,
    load_pricing_versions,
)
from services.excel_map_service import load_excel_map
from services.extraction_bridge_service import (
    default_extraction_root,
    extract_records_from_uploaded_pdfs,
    parse_dimensionamento_dataframe,
    parse_dimensionamento_records,
    parse_streamlit_export_dataframe,
    parse_streamlit_export_records,
    scan_dimensionamento_sources,
)
from services.location_service import (
    ensure_locations_catalog,
    filter_cities,
    get_cities_by_state,
    load_state_options,
)
from services.scenario_bundle_service import build_scenario_bundle
from services.scenario_service import (
    DEFAULT_SCENARIO_NAMES,
    compute_sizing_metrics,
    find_by_model,
    initialize_project_state,
)
from ui.adapter_mapper import render_adapter_mapper
from ui.context import DashboardContext
from ui.simple_mode import render_simple_mode
from ui.style import (
    apply_style,
    page_header,
    render_dash_stats,
    render_footer,
    render_sidebar_brand,
    render_sidebar_session,
    render_step_progress,
    section_start,
    section_end,
)
from ui.validators import render_validation_bar, step_completion_status
from ui.helpers import (
    STEP_FLOW,
    EXTRACTION_NUMERIC_COLUMNS,
    safe_index,
    format_scenario_name,
    add_abbreviation_meanings,
    df_to_csv_bytes,
    format_brl,
    brl_text_input,
    slugify_filename as _slugify_filename,
    render_nav_buttons,
)
from ui.extraction_helpers import (
    _coalesce_numeric_series,
    _weighted_average_positive,
    _sum_or_zero,
    _safe_div,
    _to_numeric_flexible,
    _parse_reference_series,
    _add_estimated_cost_columns,
    _build_monthly_financials,
    _build_itens_fatura_detail_table,
    _build_municipio_profile,
    _build_inefficiency_uc_table,
    _build_savings_opportunities,
    _reorder_original_extract_columns,
    _build_original_extraction_frames,
    _sanitize_export_name_like_streamlit,
    _resolve_streamlit_template_path,
    _import_run_full_study_from_root,
    _build_streamlit_exact_template_export_bytes,
    infer_tariffs_from_invoice_raw,
    apply_pending_tariff_autofill,
    recalculate_pdf_records_after_tariff_autofill,
    _normalize_header_name,
    _is_template_export_compatible_raw_df,
    _read_excel_prefer_extraction_sheet,
    _build_pdf_payload,
    _pdf_payload_signature,
    process_pdfs,
    dimensionar,
    orcamentar as _orcamentar_ui,
    exportar_extracao,
    _merge_warning_messages,
)


@st.cache_data(show_spinner=False)
def load_bootstrap_context() -> tuple[list[dict], list[dict], bool, Optional[str], list[dict]]:
    bos_catalog = load_bos_catalog()
    pricing_versions = load_pricing_versions()
    locations_ok, locations_error = ensure_locations_catalog()
    state_rows = load_state_options() if locations_ok else []
    return bos_catalog, pricing_versions, locations_ok, locations_error, state_rows


def render_logo() -> None:
    logo_path = ASSETS_DIR / "logo.png"
    if logo_path.exists():
        st.image(str(logo_path), width=180)


def render_dimensionamento_previo_details(record: dict) -> None:
    consumo = record.get("consumo_medio_mensal_kwh") or {}
    ufv = record.get("ufv_kwp_por_categoria") or {}
    if not consumo and not ufv:
        return

    st.markdown(f"**{add_abbreviation_meanings('Dimensionamento Previo UFV')} (logica do Excel)**")
    category_order = [("B3", "B3"), ("B4A", "B4A"), ("A4_HP", "A4 HP"), ("A4_FHP", "A4 FHP")]

    consumption_cols = st.columns(4)
    for col, (key, label) in zip(consumption_cols, category_order):
        col.metric(
            add_abbreviation_meanings(f"Consumo medio {label}"),
            f"{float(consumo.get(key, 0.0)):,.2f} kWh/mes",
        )

    sizing_cols = st.columns(4)
    for col, (key, label) in zip(sizing_cols, category_order):
        col.metric(add_abbreviation_meanings(f"UFV {label}"), f"{float(ufv.get(key, 0.0)):,.2f} kWp")

    total_kwp = float(record.get("ufv_total_kwp", record.get("kwp", 0.0)) or 0.0)
    total_mwp = float(record.get("ufv_total_mwp", record.get("mwp", 0.0)) or 0.0)
    capex_brl = float(record.get("investment_brl", 0.0) or 0.0)
    payback_months = record.get("payback_months")

    total_cols = st.columns(4)
    total_cols[0].metric(add_abbreviation_meanings("UFV total"), f"{total_kwp:,.2f} kWp")
    total_cols[1].metric(add_abbreviation_meanings("UFV total"), f"{total_mwp:,.4f} MWp")
    total_cols[2].metric(add_abbreviation_meanings("CAPEX total"), format_brl(capex_brl))
    total_cols[3].metric(
        "Payback simples",
        "-" if payback_months is None else f"{float(payback_months):.1f} meses",
    )

    monthly_cost = record.get("monthly_energy_cost_brl") or {}
    total_monthly_cost = monthly_cost.get("TOTAL")
    if total_monthly_cost is not None:
        st.caption(f"Custo mensal de energia (base tarifas): {format_brl(float(total_monthly_cost))}")
    elif record.get("payback_needs_tariff_input"):
        st.caption("Payback requer tarifas por categoria para todas as cargas com consumo.")

    dim_inputs = record.get("dimensionamento_inputs") or {}
    if dim_inputs:
        st.caption(
            "Parametros: "
            f"{add_abbreviation_meanings('HSP')}={float(dim_inputs.get('hsp', 0.0)):.3f} | "
            f"{add_abbreviation_meanings('PR')}={float(dim_inputs.get('performance_ratio', 0.0)):.3f} | "
            f"Dias={float(dim_inputs.get('days_per_month', 0.0)):.1f} | "
            f"Fator {add_abbreviation_meanings('A4 HP')}={float(dim_inputs.get('a4_hp_factor', 0.0)):.3f} | "
            f"{add_abbreviation_meanings('CAPEX')}={format_brl(float(dim_inputs.get('capex_brl_per_mwp', 0.0)))} / "
            f"{add_abbreviation_meanings('MWp')}"
        )

    month_labels = record.get("month_labels") or []
    if month_labels:
        st.caption("Janela mensal usada (com zero explicito para meses ausentes): " + ", ".join(month_labels))

    warnings = record.get("warnings") or []
    for warning_message in warnings:
        st.warning(add_abbreviation_meanings(str(warning_message)))




st.set_page_config(
    page_title="SolarBudget — Orcamento Solar",
    page_icon=":sunny:",
    layout="wide",
)
_theme_options = ["forest", "slate"]
_theme_labels = {
    "forest": "Forest Light",
    "slate": "Slate Dark",
}
_legacy_theme_map = {
    "aurora": "forest",
    "cyber": "slate",
}
_saved_theme = _legacy_theme_map.get(st.session_state.get("ui_theme", "forest"), st.session_state.get("ui_theme", "forest"))
if st.session_state.get("ui_theme") != _saved_theme:
    st.session_state["ui_theme"] = _saved_theme
_theme_index = _theme_options.index(_saved_theme) if _saved_theme in _theme_options else 0

# ─── Sidebar branding ─────────────────────────────────────────
_sidebar = st.sidebar
with _sidebar:
    render_sidebar_brand("SolarBudget", "Ferramenta Interna")
    theme = st.selectbox(
        "Aparencia",
        _theme_options,
        index=_theme_index,
        key="ui_theme",
        format_func=lambda value: _theme_labels.get(value, value),
    )
apply_style(theme)

try:
    excel_map = load_excel_map(EXCEL_MAP_PATH)
except Exception as exc:
    st.error(f"Falha ao carregar o mapa do Excel ({EXCEL_MAP_PATH}): {exc}")
    st.stop()

modules_catalog = [dict(row) for row in load_modules_catalog()]
inverters_catalog = [dict(row) for row in load_inverters_catalog()]
bos_catalog, pricing_versions, locations_ok, locations_error, state_rows = load_bootstrap_context()

if not modules_catalog:
    st.error("Nenhum modelo de modulo encontrado em catalog/modules.csv")
    st.stop()
if not inverters_catalog:
    st.error("Nenhum modelo de inversor encontrado em catalog/inverters.csv")
    st.stop()
if not pricing_versions:
    st.error("Nenhuma versao de precos encontrada em catalog/pricing_versions.csv")
    st.stop()
if not state_rows:
    st.warning(
        "Catalogo IBGE de estado/cidade indisponivel no momento. "
        f"{locations_error or 'Usando preenchimento manual de cidade.'}"
    )

st.session_state["project"] = initialize_project_state(
    st.session_state.get("project"),
    modules_catalog,
    inverters_catalog,
    pricing_versions,
    bos_catalog,
)
project = st.session_state["project"]

scenario_names = list(project["scenarios"].keys())
active_scenario_name = project["active_scenario"]
if active_scenario_name not in scenario_names:
    active_scenario_name = DEFAULT_SCENARIO_NAMES[0]
    project["active_scenario"] = active_scenario_name
active_scenario = project["scenarios"][active_scenario_name]

simple_mode_enabled = st.toggle(
    "Modo simples",
    value=bool(st.session_state.get("ui_simple_mode", True)),
    key="ui_simple_mode",
    help=f"Desative para o Modo avancado (wizard A-E, {add_abbreviation_meanings('BOS')}, cenarios, debug).",
)

if simple_mode_enabled:
    render_logo()
    page_header(
        "Orcamento Solar",
        f"{project['setup'].get('project_name','Projeto Solar')} | Modo rapido",
        eyebrow="SolarBudget",
    )
    render_simple_mode(
        project=project,
        scenario_names=scenario_names,
        modules_catalog=modules_catalog,
        inverters_catalog=inverters_catalog,
        excel_map=excel_map,
    )
    render_footer("SolarBudget")
    st.stop()

sidebar = st.sidebar

with sidebar:
    st.markdown("### Cenario")
    selected_scenario = st.selectbox(
        "Cenario ativo",
        scenario_names,
        index=safe_index(scenario_names, project["active_scenario"]),
        format_func=format_scenario_name,
        label_visibility="collapsed",
    )
    project["active_scenario"] = selected_scenario
    active_scenario = project["scenarios"][selected_scenario]

    st.markdown("### Navegacao")
    step_labels = [f"{code}. {name}" for code, name in STEP_FLOW]
    current_step_label = f"{project['wizard_step']}. {dict(STEP_FLOW)[project['wizard_step']]}"
    selected_step_label = st.radio(
        "Etapa",
        step_labels,
        index=safe_index(step_labels, current_step_label),
        label_visibility="collapsed",
    )
    project["wizard_step"] = selected_step_label.split(".", 1)[0]

    st.markdown("---")

    copy_targets = [name for name in scenario_names if name != selected_scenario]
    if copy_targets:
        st.markdown("### Ferramentas")
        target_scenario = st.selectbox(
            "Copiar cenario ativo para",
            copy_targets,
            format_func=format_scenario_name,
        )
        if st.button("Copiar Cenario"):
            clone = deepcopy(active_scenario)
            clone["name"] = target_scenario
            project["scenarios"][target_scenario] = clone
            st.success(
                f"Cenario {format_scenario_name(selected_scenario)} copiado para {format_scenario_name(target_scenario)}."
            )
            st.rerun()

    if st.button("Limpar cache", type="secondary"):
        st.cache_data.clear()
        st.success("Cache limpo.")
        st.rerun()

setup = project["setup"]

# Build DashboardContext for validation and progress
ctx = DashboardContext(
    project=project,
    active_scenario=active_scenario,
    selected_scenario=selected_scenario,
    scenario_names=scenario_names,
    modules_catalog=modules_catalog,
    inverters_catalog=inverters_catalog,
    bos_catalog=bos_catalog,
    pricing_versions=pricing_versions,
    excel_map=excel_map,
    state_rows=state_rows,
)

# Render step progress indicator in sidebar
completion = step_completion_status(ctx)
with sidebar:
    st.markdown("---")
    render_step_progress(STEP_FLOW, project["wizard_step"], completion)
    render_sidebar_session(f"{setup.get('client') or 'Projeto'} — {format_scenario_name(selected_scenario)}")

render_logo()
page_header(
    "Orcamento Solar — Modo Avancado",
    f"{setup.get('project_name','Projeto Solar')} | Versao: {active_scenario.get('pricing_version','')} | "
    f"Cenario: {format_scenario_name(selected_scenario)}",
    eyebrow="SolarBudget",
)

# Render validation bar for current step
render_validation_bar(ctx)

if project["wizard_step"] == "A":
    section_start("A. Configuração do Projeto", chip=format_scenario_name(selected_scenario))

    col1, col2 = st.columns(2)
    with col1:
        setup["client"] = st.text_input("Cliente", value=setup.get("client", ""))
        setup["project_name"] = st.text_input("Nome do Projeto", value=setup.get("project_name", "Projeto Solar"))
    with col2:
        setup_date = date.fromisoformat(setup.get("project_date", date.today().isoformat()))
        setup["project_date"] = st.date_input("Data", value=setup_date).isoformat()
        extracted_mwp = float(setup.get("mwp_ac", 0.0) or 0.0)
        st.caption(add_abbreviation_meanings("MWp AC do projeto e definido automaticamente a partir da extracao."))
        if extracted_mwp > 0:
            st.metric(add_abbreviation_meanings("MWp AC extraido"), f"{extracted_mwp:.3f}")
        else:
            st.warning(add_abbreviation_meanings("Extraia e aplique um dimensionamento para definir o MWp do projeto."))
    section_end()

    section_start("Localização", chip="IBGE", solid=True)
    loc_col1, loc_col2 = st.columns(2)
    if state_rows:
        state_options = [row["uf"] for row in state_rows]
        state_name_map = {row["uf"]: row["name"] for row in state_rows}
        current_state = str(setup.get("state", "SP") or "SP").upper()
        if current_state not in state_options:
            current_state = "SP" if "SP" in state_options else state_options[0]

        selected_state = loc_col1.selectbox(
            "Estado (UF)",
            options=state_options,
            index=safe_index(state_options, current_state),
            format_func=lambda uf: f"{uf} - {state_name_map.get(uf, '')}",
        )
        setup["state"] = selected_state

        all_state_cities = get_cities_by_state(selected_state)
        city_search = loc_col2.text_input(
            "Buscar cidade",
            value="",
            key=f"city_search_{selected_state}",
            placeholder="Digite para filtrar a lista de cidades",
        )
        filtered_cities = filter_cities(all_state_cities, city_search, limit=700)
        city_options = [row["city"] for row in filtered_cities]
        city_options_with_other = city_options + ["Outra (manual)"]

        current_city = str(setup.get("city", "") or "")
        if current_city in city_options_with_other:
            city_index = city_options_with_other.index(current_city)
        elif current_city:
            city_index = len(city_options_with_other) - 1
        else:
            city_index = 0

        selected_city = loc_col2.selectbox(
            "Cidade",
            options=city_options_with_other,
            index=city_index,
        )

        if selected_city == "Outra (manual)":
            if "manual_city_input" not in st.session_state:
                st.session_state["manual_city_input"] = ""
            setup["city"] = st.text_input(
                "Cidade (manual)",
                key="manual_city_input",
                placeholder="Ex: Palhoça",
            ).strip()
            setup["city_ibge_code"] = ""
        else:
            st.session_state.pop("manual_city_input", None)
            setup["city"] = selected_city
            selected_city_row = next(
                (row for row in all_state_cities if row["city"] == selected_city),
                None,
            )
            setup["city_ibge_code"] = (
                selected_city_row["ibge_code"] if selected_city_row else ""
            )

        if city_search and not filtered_cities:
            st.warning("Nenhuma cidade encontrada para este filtro no estado selecionado.")
    else:
        setup["state"] = loc_col1.text_input("Estado (UF)", value=str(setup.get("state", "SP"))).upper().strip()
        setup["city"] = loc_col2.text_input("Cidade", value=str(setup.get("city", "Sao Paulo")))
        setup["city_ibge_code"] = ""

    section_end()
    section_start("Integrações", chip="Extração → Orçamento", solid=True)
    with st.expander("Conectar projeto de extracao", expanded=False):
        default_root = str(default_extraction_root())
        extraction_root_value = st.text_input(
            "Pasta do projeto de extracao",
            value=st.session_state.get("extraction_root_path", default_root),
            help="Projeto esperado: estudo_faturas_municipios",
        ).strip().strip('"').strip("'")
        st.session_state["extraction_root_path"] = extraction_root_value
        extraction_root_path = Path(extraction_root_value).expanduser()
        st.caption(
            f"Caminho de extracao em uso: `{extraction_root_path}` | existe: `{extraction_root_path.exists()}`"
        )

        scan_col, refresh_col = st.columns([1, 1])
        if scan_col.button("Buscar arquivos de dimensionamento", key="scan_dimensionamento_btn"):
            sources = scan_dimensionamento_sources(extraction_root_path)
            st.session_state["dimensionamento_sources"] = sources
            if sources:
                dim_count = sum(1 for src in sources if src.get("kind") == "dimensionamento")
                streamlit_count = sum(1 for src in sources if src.get("kind") == "streamlit_export")
                st.success(
                    f"Encontrado(s) {len(sources)} arquivo(s): {dim_count} dimensionamento + "
                    f"{streamlit_count} exportacao streamlit."
                )
            else:
                st.warning("Nenhum arquivo compativel encontrado na pasta informada.")

        if refresh_col.button("Usar caminho padrao de extracao", key="default_extraction_path_btn"):
            st.session_state["extraction_root_path"] = default_root
            st.session_state["dimensionamento_sources"] = scan_dimensionamento_sources(Path(default_root))
            st.rerun()

        st.markdown("**Extracao direta de PDF (neste dashboard)**")
        uploaded_pdfs = st.file_uploader(
            "Enviar PDFs de faturas",
            type=["pdf"],
            accept_multiple_files=True,
            key="uploaded_invoice_pdfs_bridge",
        )
        pdf_municipio_override = st.text_input(
            "Municipio para sobrescrever na extracao de PDF (opcional)",
            value=str(setup.get("city", "") or ""),
            key="pdf_municipio_override_bridge",
        )
        if uploaded_pdfs and len(uploaded_pdfs) > 1 and not str(pdf_municipio_override or "").strip():
            st.info(
                "Municipio em branco com multiplos PDFs: o sistema vai consolidar o lote em um unico municipio "
                "automaticamente."
            )
        pdf_expand_historico = st.checkbox(
            add_abbreviation_meanings("Expandir historico (A4/B3/IP) durante a extracao"),
            value=True,
            key="pdf_expand_historico_bridge",
        )

        st.markdown(f"**{add_abbreviation_meanings('Dimensionamento Previo UFV')} (parametros)**")
        dim_col_1, dim_col_2, dim_col_3 = st.columns(3)
        dim_months_to_use = int(
            dim_col_1.number_input(
                "Janela de meses",
                min_value=1,
                max_value=36,
                value=int(st.session_state.get("dim_months_to_use", DEFAULT_MONTHS_TO_USE)),
                step=1,
                key="dim_months_to_use",
            )
        )
        dim_hsp = dim_col_2.number_input(
            add_abbreviation_meanings("HSP"),
            min_value=0.01,
            value=float(st.session_state.get("dim_hsp", 4.9)),
            step=0.1,
            key="dim_hsp",
        )
        dim_pr = dim_col_3.number_input(
            add_abbreviation_meanings("PR (eficiencia)"),
            min_value=0.01,
            max_value=1.50,
            value=float(st.session_state.get("dim_pr", 0.80)),
            step=0.01,
            key="dim_pr",
        )

        dim_col_4, dim_col_5, dim_col_6 = st.columns(3)
        dim_days = dim_col_4.number_input(
            "Dias por mes",
            min_value=1.0,
            value=float(st.session_state.get("dim_days", 30.0)),
            step=1.0,
            key="dim_days",
        )
        dim_a4_hp_factor = dim_col_5.number_input(
            add_abbreviation_meanings("Fator A4 HP (geracao)"),
            min_value=0.01,
            value=float(st.session_state.get("dim_a4_hp_factor", 1.0)),
            step=0.05,
            key="dim_a4_hp_factor",
        )
        with dim_col_6:
            dim_capex_brl_per_mwp = brl_text_input(
                add_abbreviation_meanings("CAPEX (R$ / MWp)"),
                state_key="dim_capex_brl_per_mwp",
                default_value=float(st.session_state.get("dim_capex_brl_per_mwp", DEFAULT_CAPEX_BRL_PER_MWP)),
            )

        apply_pending_tariff_autofill()
        tariff_col_1, tariff_col_2, tariff_col_3, tariff_col_4 = st.columns(4)
        with tariff_col_1:
            dim_tariff_b3 = brl_text_input(
                add_abbreviation_meanings("Tarifa B3 (R$/kWh)"),
                state_key="dim_tariff_b3",
                default_value=float(st.session_state.get("dim_tariff_b3", 0.0)),
                placeholder="Ex: R$ 0,85",
            )
        with tariff_col_2:
            dim_tariff_b4a = brl_text_input(
                add_abbreviation_meanings("Tarifa B4A (R$/kWh)"),
                state_key="dim_tariff_b4a",
                default_value=float(st.session_state.get("dim_tariff_b4a", 0.0)),
                placeholder="Ex: R$ 0,80",
            )
        with tariff_col_3:
            dim_tariff_a4_hp = brl_text_input(
                add_abbreviation_meanings("Tarifa A4 HP (R$/kWh)"),
                state_key="dim_tariff_a4_hp",
                default_value=float(st.session_state.get("dim_tariff_a4_hp", 0.0)),
                placeholder="Ex: R$ 0,95",
            )
        with tariff_col_4:
            dim_tariff_a4_fhp = brl_text_input(
                add_abbreviation_meanings("Tarifa A4 FHP (R$/kWh)"),
                state_key="dim_tariff_a4_fhp",
                default_value=float(st.session_state.get("dim_tariff_a4_fhp", 0.0)),
                placeholder="Ex: R$ 0,70",
            )

        last_autofill = st.session_state.get("last_tariff_autofill", {})
        if isinstance(last_autofill, dict) and last_autofill:
            parts = []
            if last_autofill.get("dim_tariff_b3") is not None:
                parts.append(f"{add_abbreviation_meanings('B3')}={format_brl(last_autofill['dim_tariff_b3'])}/kWh")
            if last_autofill.get("dim_tariff_b4a") is not None:
                parts.append(f"{add_abbreviation_meanings('B4A')}={format_brl(last_autofill['dim_tariff_b4a'])}/kWh")
            if last_autofill.get("dim_tariff_a4_hp") is not None:
                parts.append(
                    f"{add_abbreviation_meanings('A4 HP')}={format_brl(last_autofill['dim_tariff_a4_hp'])}/kWh"
                )
            if last_autofill.get("dim_tariff_a4_fhp") is not None:
                parts.append(
                    f"{add_abbreviation_meanings('A4 FHP')}={format_brl(last_autofill['dim_tariff_a4_fhp'])}/kWh"
                )
            if parts:
                st.caption("Tarifas preenchidas pela média das faturas: " + " | ".join(parts))

        tariff_b3_param = dim_tariff_b3 if dim_tariff_b3 > 0 else None
        tariff_b4a_param = dim_tariff_b4a if dim_tariff_b4a > 0 else None
        tariff_a4_hp_param = dim_tariff_a4_hp if dim_tariff_a4_hp > 0 else None
        tariff_a4_fhp_param = dim_tariff_a4_fhp if dim_tariff_a4_fhp > 0 else None

        should_try_payback_recalc = st.session_state.pop("tariff_autofill_applied", False)
        if not should_try_payback_recalc:
            should_try_payback_recalc = any(
                value is not None
                for value in (
                    tariff_b3_param,
                    tariff_b4a_param,
                    tariff_a4_hp_param,
                    tariff_a4_fhp_param,
                )
            )

        if should_try_payback_recalc:
            payback_recalculated = recalculate_pdf_records_after_tariff_autofill(
                months_to_use=dim_months_to_use,
                hsp=dim_hsp,
                performance_ratio=dim_pr,
                days_per_month=dim_days,
                a4_hp_factor=dim_a4_hp_factor,
                capex_brl_per_mwp=dim_capex_brl_per_mwp,
                tariff_b3_rs_kwh=tariff_b3_param,
                tariff_b4a_rs_kwh=tariff_b4a_param,
                tariff_a4_hp_rs_kwh=tariff_a4_hp_param,
                tariff_a4_fhp_rs_kwh=tariff_a4_fhp_param,
            )
            if payback_recalculated:
                st.success("Payback recalculado automaticamente com as tarifas medias das faturas.")

        if st.button("Extrair PDFs e montar cenarios de dimensionamento", key="extract_pdfs_bridge_btn"):
            if not uploaded_pdfs:
                st.warning("Envie pelo menos um PDF primeiro.")
            else:
                status = st.status("Extraindo PDFs...", expanded=True)
                progress_bar = status.progress(0.0)
                log = status.empty()

                def _on_pdf_progress(event: dict) -> None:
                    total_pages = int(event.get("total_pages", 0) or 0)
                    pages_processed_local = int(event.get("pages_processed", 0) or 0)
                    current_pdf_name = str(event.get("current_pdf_name", "") or "")
                    pdf_page_no = int(event.get("pdf_page_no", 0) or 0)
                    pdf_pages = int(event.get("pdf_pages", 0) or 0)
                    phase = str(event.get("phase", "") or "")

                    progress = float(event.get("progress", 0.0) or 0.0)
                    progress = max(0.0, min(1.0, progress))
                    progress_bar.progress(progress)

                    if total_pages <= 0:
                        status.write("Extraindo...")
                        return

                    percent_text = f"{int(progress * 100)}%"
                    page_text = f"Page {pages_processed_local} / {total_pages}"
                    if phase == "page_start":
                        next_page = min(total_pages, pages_processed_local + 1)
                        status.write(f"Reading page {next_page}/{total_pages} ...")
                        if current_pdf_name and pdf_pages > 0:
                            log.write(f"{current_pdf_name} (PDF page {pdf_page_no}/{pdf_pages})")
                        return

                    status.write(
                        "Extracting... "
                        f"{percent_text} — {page_text} — {current_pdf_name} "
                        f"(PDF page {pdf_page_no}/{pdf_pages})"
                    )

                try:
                    status.write("Preparando extracao...")
                    pdf_records, pdf_stats = extract_records_from_uploaded_pdfs(
                        uploaded_pdfs=uploaded_pdfs,
                        extraction_root=extraction_root_path,
                        municipio_override=pdf_municipio_override,
                        expand_a4_historico=pdf_expand_historico,
                        months_to_use=dim_months_to_use,
                        hsp=dim_hsp,
                        performance_ratio=dim_pr,
                        days_per_month=dim_days,
                        a4_hp_factor=dim_a4_hp_factor,
                        capex_brl_per_mwp=dim_capex_brl_per_mwp,
                        tariff_b3_rs_kwh=tariff_b3_param,
                        tariff_b4a_rs_kwh=tariff_b4a_param,
                        tariff_a4_hp_rs_kwh=tariff_a4_hp_param,
                        tariff_a4_fhp_rs_kwh=tariff_a4_fhp_param,
                        progress_callback=_on_pdf_progress,
                    )
                    st.session_state["pdf_bridge_records"] = pdf_records
                    st.session_state["pdf_bridge_stats"] = pdf_stats
                    st.session_state["latest_extracted_records"] = pdf_records
                    raw_pdf_df = pdf_stats.get("master_df")
                    if isinstance(raw_pdf_df, pd.DataFrame):
                        st.session_state["latest_extracted_raw_df"] = raw_pdf_df.copy()
                        inferred_tariffs = infer_tariffs_from_invoice_raw(raw_pdf_df)
                        if inferred_tariffs:
                            st.session_state["pending_tariff_autofill"] = inferred_tariffs

                    total_pages = int(pdf_stats.get("total_pages", 0) or 0)
                    progress_bar.progress(1.0)
                    if total_pages > 0:
                        status.update(
                            label=f"Extracao finalizada — {total_pages} paginas processadas",
                            state="complete", expanded=False,
                        )
                    else:
                        status.update(label="Extracao finalizada.", state="complete", expanded=False)
                    if st.session_state.get("pending_tariff_autofill"):
                        st.rerun()
                except Exception as exc:
                    st.session_state["pdf_bridge_records"] = []
                    st.session_state["pdf_bridge_stats"] = {}
                    status.update(label="Falha na extracao de PDF.", state="error", expanded=True)
                    st.error(
                        f"Falha na extracao de PDF [{type(exc).__name__}]: {exc}\n\n"
                        "Sugestoes: confirme que os PDFs nao estao protegidos por senha, "
                        "tente um PDF por vez para identificar o arquivo problematico, "
                        "e verifique se o adaptador correto esta selecionado para sua distribuidora."
                    )

        pdf_records = st.session_state.get("pdf_bridge_records", [])
        pdf_stats = st.session_state.get("pdf_bridge_stats", {})
        discovery_reports = pdf_stats.get("discovery_reports") or {}
        if discovery_reports:
            with st.expander("Diagnostico de extracao", expanded=False):
                for pdf_name, report in discovery_reports.items():
                    detected_layout = str(report.get("detected_layout", "") or "")
                    effective_layout = str(report.get("effective_layout", "") or detected_layout or "")
                    if effective_layout and effective_layout != detected_layout:
                        st.markdown(f"**{pdf_name}**: detectado `{detected_layout}` | extracao `{effective_layout}`")
                    else:
                        st.markdown(f"**{pdf_name}**: layout `{effective_layout or detected_layout or 'UNKNOWN'}`")

                    error_text = str(report.get("error", "") or "").strip()
                    if error_text:
                        st.caption(f"erro: {error_text}")

                    field_report = report.get("field_extraction_report") or {}
                    for field_name, info in field_report.items():
                        icon = "OK" if bool(info.get("found")) else "MISS"
                        source_pattern = str(info.get("source_pattern", "") or "-")
                        value = info.get("value")
                        st.caption(f"{field_name}: {icon} via {source_pattern} | value={value}")

                    sample_text = str(report.get("unmatched_text_sample", "") or "").strip()
                    if sample_text:
                        st.code(sample_text, language="text")

        if pdf_records:
            st.success(
                f"Extracao de PDF pronta: {pdf_stats.get('files_processed', 0)} arquivo(s), "
                f"{pdf_stats.get('rows_extracted', 0)} linha(s) extraida(s)."
            )
            raw_pdf_df = pdf_stats.get("master_df")
            if isinstance(raw_pdf_df, pd.DataFrame) and not raw_pdf_df.empty and "categoria" in raw_pdf_df.columns:
                cat_counts = (
                    raw_pdf_df["categoria"]
                    .fillna("N/A")
                    .astype(str)
                    .value_counts(dropna=False)
                    .to_dict()
                )
                if cat_counts:
                    cat_text = " | ".join(f"{key}: {value}" for key, value in cat_counts.items())
                    st.caption(f"Categorias extraidas (raw): {cat_text}")
            failed_pdf_files = pdf_stats.get("failed_files") or []
            if failed_pdf_files:
                st.warning("Arquivos com falha: " + ", ".join(failed_pdf_files))

            pdf_record_labels = [
                f"{rec['cenario']} | {rec['mwp']:.3f} {add_abbreviation_meanings('MWp')} | {rec['municipio'] or 'Municipio N/A'}"
                for rec in pdf_records
            ]
            selected_pdf_record_label = st.selectbox(
                "Cenario de dimensionamento a partir dos PDFs enviados",
                pdf_record_labels,
                key="pdf_bridge_record_select",
            )
            selected_pdf_record = pdf_records[pdf_record_labels.index(selected_pdf_record_label)]
            st.write(
                f"Dimensionamento extraido: `{selected_pdf_record['mwp']:.3f} {add_abbreviation_meanings('MWp')}` "
                f"({selected_pdf_record['kwp']:.1f} {add_abbreviation_meanings('kWp')}) de `{selected_pdf_record['source_file']}`"
            )
            if selected_pdf_record.get("total_kwh") is not None:
                st.write(
                    f"Energia total considerada: `{selected_pdf_record['total_kwh']:,.0f} {add_abbreviation_meanings('kWh')}`"
                )
            render_dimensionamento_previo_details(selected_pdf_record)

            update_project_name_pdf = st.checkbox(
                "Atualizar nome do projeto com o municipio importado (extracao PDF)",
                value=False,
                key="update_name_from_pdf_bridge",
            )
            if st.button("Aplicar dimensionamento do PDF", key="apply_pdf_mwp_btn"):
                imported_mwp = max(0.1, float(selected_pdf_record["mwp"]))
                setup["mwp_ac"] = imported_mwp
                setup["extraction_source_file"] = selected_pdf_record["source_file"]
                setup["extraction_scenario"] = selected_pdf_record["cenario"]
                setup["extraction_imported_mwp"] = imported_mwp
                setup["extraction_imported_at"] = datetime.now().isoformat()
                if update_project_name_pdf and selected_pdf_record.get("municipio"):
                    setup["project_name"] = f"Projeto Solar - {selected_pdf_record['municipio']}"
                st.success(f"Dimensionamento de PDF aplicado: {imported_mwp:.3f} {add_abbreviation_meanings('MWp')}")
                st.rerun()
        elif uploaded_pdfs:
            st.info(
                f"Clique em 'Extrair PDFs e montar cenarios de dimensionamento' para gerar opcoes de {add_abbreviation_meanings('MWp')}."
            )

        st.divider()

        uploaded_dimensionamento = st.file_uploader(
            "Ou envie arquivo de dimensionamento / exportacao streamlit (CSV/XLSX)",
            type=["csv", "xlsx"],
            key="uploaded_dimensionamento_file",
        )
        if uploaded_dimensionamento is not None:
            try:
                if uploaded_dimensionamento.name.lower().endswith(".csv"):
                    uploaded_df = pd.read_csv(uploaded_dimensionamento, encoding="utf-8-sig")
                else:
                    uploaded_df = _read_excel_prefer_extraction_sheet(uploaded_dimensionamento)
                uploaded_records = parse_dimensionamento_dataframe(
                    uploaded_df,
                    source_label=uploaded_dimensionamento.name,
                )
                if not uploaded_records:
                    uploaded_records = parse_streamlit_export_dataframe(
                        uploaded_df,
                        source_label=uploaded_dimensionamento.name,
                        months_to_use=dim_months_to_use,
                        hsp=dim_hsp,
                        performance_ratio=dim_pr,
                        days_per_month=dim_days,
                        a4_hp_factor=dim_a4_hp_factor,
                        capex_brl_per_mwp=dim_capex_brl_per_mwp,
                        tariff_b3_rs_kwh=tariff_b3_param,
                        tariff_b4a_rs_kwh=tariff_b4a_param,
                        tariff_a4_hp_rs_kwh=tariff_a4_hp_param,
                        tariff_a4_fhp_rs_kwh=tariff_a4_fhp_param,
                    )
                if (
                    not uploaded_records
                    and uploaded_dimensionamento.name.lower().endswith((".xlsx", ".xls", ".xlsm", ".xltx", ".xltm"))
                ):
                    tmp_upload_path = ""
                    try:
                        upload_suffix = Path(uploaded_dimensionamento.name).suffix or ".xlsx"
                        with tempfile.NamedTemporaryFile(delete=False, suffix=upload_suffix) as tmp_file:
                            tmp_file.write(uploaded_dimensionamento.getvalue())
                            tmp_upload_path = tmp_file.name

                        uploaded_records = parse_dimensionamento_records(Path(tmp_upload_path))
                        if not uploaded_records:
                            uploaded_records = parse_streamlit_export_records(
                                Path(tmp_upload_path),
                                months_to_use=dim_months_to_use,
                                hsp=dim_hsp,
                                performance_ratio=dim_pr,
                                days_per_month=dim_days,
                                a4_hp_factor=dim_a4_hp_factor,
                                capex_brl_per_mwp=dim_capex_brl_per_mwp,
                                tariff_b3_rs_kwh=tariff_b3_param,
                                tariff_b4a_rs_kwh=tariff_b4a_param,
                                tariff_a4_hp_rs_kwh=tariff_a4_hp_param,
                                tariff_a4_fhp_rs_kwh=tariff_a4_fhp_param,
                            )
                    finally:
                        if tmp_upload_path:
                            try:
                                Path(tmp_upload_path).unlink(missing_ok=True)
                            except Exception:
                                pass
            except Exception as exc:
                uploaded_records = []
                st.error(f"Nao foi possivel ler o arquivo enviado: {exc}")

            if uploaded_records:
                st.session_state["latest_extracted_records"] = uploaded_records
                if "uploaded_df" in locals() and isinstance(uploaded_df, pd.DataFrame):
                    if _is_template_export_compatible_raw_df(uploaded_df):
                        st.session_state["latest_extracted_raw_df"] = uploaded_df.copy()
                        inferred_tariffs_upload = infer_tariffs_from_invoice_raw(uploaded_df)
                        if inferred_tariffs_upload:
                            st.session_state["pending_tariff_autofill"] = inferred_tariffs_upload
                upload_labels = [
                    f"{rec['cenario']} | {rec['mwp']:.3f} {add_abbreviation_meanings('MWp')} | {rec['municipio'] or 'Municipio N/A'}"
                    for rec in uploaded_records
                ]
                selected_upload_label = st.selectbox(
                    "Cenario de dimensionamento do arquivo enviado",
                    upload_labels,
                    key="uploaded_dim_record_select",
                )
                selected_upload_record = uploaded_records[upload_labels.index(selected_upload_label)]
                st.write(
                    f"Dimensionamento enviado: `{selected_upload_record['mwp']:.3f} {add_abbreviation_meanings('MWp')}` "
                    f"({selected_upload_record['kwp']:.1f} {add_abbreviation_meanings('kWp')}) de `{selected_upload_record['source_file']}`"
                )
                render_dimensionamento_previo_details(selected_upload_record)
                update_project_name_upload = st.checkbox(
                    "Atualizar nome do projeto com o municipio importado (upload)",
                    value=False,
                    key="update_name_from_upload_dim",
                )
                if st.button("Aplicar dimensionamento enviado", key="apply_uploaded_mwp_btn"):
                    imported_mwp = max(0.1, float(selected_upload_record["mwp"]))
                    setup["mwp_ac"] = imported_mwp
                    setup["extraction_source_file"] = selected_upload_record["source_file"]
                    setup["extraction_scenario"] = selected_upload_record["cenario"]
                    setup["extraction_imported_mwp"] = imported_mwp
                    setup["extraction_imported_at"] = datetime.now().isoformat()
                    if update_project_name_upload and selected_upload_record.get("municipio"):
                        setup["project_name"] = f"Projeto Solar - {selected_upload_record['municipio']}"
                    st.success(
                        f"Dimensionamento enviado aplicado: {imported_mwp:.3f} {add_abbreviation_meanings('MWp')}"
                    )
                    st.rerun()
            else:
                st.info(
                    "O arquivo enviado nao possui linhas validas de dimensionamento. "
                    f"Esperado: colunas de dimensionamento ou exportacao streamlit com referencias de {add_abbreviation_meanings('kWh')}."
                )
            st.divider()

        if "dimensionamento_sources" not in st.session_state:
            st.session_state["dimensionamento_sources"] = scan_dimensionamento_sources(extraction_root_path)

        sources = st.session_state.get("dimensionamento_sources", [])
        if sources:
            source_labels = [
                f"{src['modified_at']} | {src.get('kind', 'file')} | {src['municipio'] or '-'} | {src['filename']}"
                for src in sources
            ]
            selected_source_label = st.selectbox("Arquivo fonte de dimensionamento", source_labels)
            selected_source = sources[source_labels.index(selected_source_label)]

            try:
                extracted_records = parse_dimensionamento_records(Path(selected_source["path"]))
                if not extracted_records:
                    extracted_records = parse_streamlit_export_records(
                        Path(selected_source["path"]),
                        months_to_use=dim_months_to_use,
                        hsp=dim_hsp,
                        performance_ratio=dim_pr,
                        days_per_month=dim_days,
                        a4_hp_factor=dim_a4_hp_factor,
                        capex_brl_per_mwp=dim_capex_brl_per_mwp,
                        tariff_b3_rs_kwh=tariff_b3_param,
                        tariff_b4a_rs_kwh=tariff_b4a_param,
                        tariff_a4_hp_rs_kwh=tariff_a4_hp_param,
                        tariff_a4_fhp_rs_kwh=tariff_a4_fhp_param,
                    )
            except Exception as exc:
                st.error(f"Nao foi possivel ler o arquivo selecionado: {exc}")
                extracted_records = []

            if extracted_records:
                source_template_raw_df = pd.DataFrame()
                try:
                    source_path = Path(selected_source["path"])
                    if source_path.suffix.lower() == ".csv":
                        loaded_df = pd.read_csv(source_path, encoding="utf-8-sig")
                    else:
                        loaded_df = _read_excel_prefer_extraction_sheet(source_path)
                    if _is_template_export_compatible_raw_df(loaded_df):
                        source_template_raw_df = loaded_df.copy()
                        inferred_tariffs_source = infer_tariffs_from_invoice_raw(loaded_df)
                        if inferred_tariffs_source:
                            st.session_state["pending_tariff_autofill"] = inferred_tariffs_source
                except Exception:
                    pass
                record_labels = [
                    f"{rec['cenario']} | {rec['mwp']:.3f} {add_abbreviation_meanings('MWp')} | {rec['municipio'] or 'Municipio N/A'}"
                    for rec in extracted_records
                ]
                selected_record_label = st.selectbox("Cenario de dimensionamento da extracao", record_labels)
                selected_record = extracted_records[record_labels.index(selected_record_label)]

                st.write(
                    f"Dimensionamento importado: `{selected_record['mwp']:.3f} {add_abbreviation_meanings('MWp')}` "
                    f"({selected_record['kwp']:.1f} {add_abbreviation_meanings('kWp')}) de `{selected_record['source_file']}`"
                )
                if selected_record.get("total_kwh") is not None:
                    st.write(
                        f"Energia total considerada: `{selected_record['total_kwh']:,.0f} {add_abbreviation_meanings('kWh')}`"
                    )
                render_dimensionamento_previo_details(selected_record)

                update_project_name = st.checkbox(
                    "Atualizar nome do projeto com o municipio importado",
                    value=False,
                )
                if st.button("Aplicar ao dimensionamento do projeto", key="apply_extracted_mwp_btn"):
                    imported_mwp = max(0.1, float(selected_record["mwp"]))
                    setup["mwp_ac"] = imported_mwp
                    setup["extraction_source_file"] = selected_record["source_file"]
                    setup["extraction_scenario"] = selected_record["cenario"]
                    setup["extraction_imported_mwp"] = imported_mwp
                    setup["extraction_imported_at"] = datetime.now().isoformat()
                    st.session_state["latest_extracted_records"] = deepcopy(extracted_records)
                    if isinstance(source_template_raw_df, pd.DataFrame) and not source_template_raw_df.empty:
                        st.session_state["latest_extracted_raw_df"] = source_template_raw_df.copy()
                    if update_project_name and selected_record.get("municipio"):
                        setup["project_name"] = f"Projeto Solar - {selected_record['municipio']}"
                    st.success(
                        f"Dimensionamento importado aplicado: {imported_mwp:.3f} {add_abbreviation_meanings('MWp')}"
                    )
                    st.rerun()
            else:
                st.info(
                    "O arquivo selecionado nao tem linhas validas de dimensionamento. "
                    "Ele pode nao ser um arquivo de dimensionamento/exportacao streamlit."
                )
        else:
            st.info(
                "Nenhuma fonte de extracao carregada ainda. Defina o caminho do projeto de extracao e clique em "
                "'Buscar arquivos de dimensionamento'."
            )

    with st.expander("Integracao segura (black-box): extracao -> orcamento", expanded=False):
        st.caption(
            "Nao altera o codigo do extrator. Apenas executa via wrapper e promove um contrato estavel."
        )

        adapter_options = ["auto"] + list_adapters()
        selected_adapter = st.selectbox(
            "Adapter da distribuidora",
            adapter_options,
            index=safe_index(adapter_options, st.session_state.get("fusion_adapter", "auto")),
            key="fusion_adapter",
        )
        stable_contract_path = Path(EXTRACTION_CONTRACT_MASTER_PATH).resolve()
        stable_meta_path = contract_meta_path(stable_contract_path)
        st.caption(f"Contrato estavel: `{stable_contract_path}`")
        st.caption(f"Metadata: `{stable_meta_path}`")

        mode = st.radio(
            "Modo",
            [
                "Somente carregar pasta de saida",
                "Executar CLI do extrator e depois carregar saida",
            ],
            key="fusion_mode",
        )

        if mode == "Executar CLI do extrator e depois carregar saida":
            default_workdir = str(st.session_state.get("extraction_root_path", default_extraction_root()))
            presets = get_presets(default_workdir=default_workdir)
            preset_keys = list(presets.keys())
            selected_preset_key = st.selectbox(
                "Preset de comando",
                preset_keys,
                index=safe_index(preset_keys, st.session_state.get("fusion_preset_key", preset_keys[0])),
                format_func=lambda key: presets[key].label,
                key="fusion_preset_key",
            )
            selected_preset = presets[selected_preset_key]
            st.caption(selected_preset.description)

            cli_workdir = st.text_input(
                "Pasta de trabalho para executar o extrator (CLI)",
                value=str(st.session_state.get("fusion_cli_workdir", selected_preset.workdir)),
                key="fusion_cli_workdir",
            )
            municipio_for_run = st.text_input(
                "Municipio para o run (usado no comando e no Run ID)",
                value=str(
                    st.session_state.get(
                        "fusion_municipio_for_run",
                        setup.get("city", selected_preset.default_municipio or "municipio"),
                    )
                ),
                key="fusion_municipio_for_run",
            ).strip()
            scan_dir_after_cli = st.text_input(
                "Pasta para buscar outputs apos a execucao",
                value=str(st.session_state.get("fusion_scan_dir_after_cli", cli_workdir)),
                key="fusion_scan_dir_after_cli",
            ).strip()
            pdf_folder = st.text_input(
                "Pasta com PDFs para o preset",
                value=str(st.session_state.get("fusion_pdf_folder", "")),
                key="fusion_pdf_folder",
            ).strip()

            def _load_pdfs_from_folder(folder_text: str) -> list[str]:
                if not folder_text:
                    return []
                pdf_root = Path(folder_text).expanduser()
                if not pdf_root.exists():
                    return []
                return sorted(str(p.resolve()) for p in pdf_root.glob("*.pdf"))

            current_pdf_folder_resolved = (
                str(Path(pdf_folder).expanduser().resolve()) if pdf_folder else ""
            )
            last_pdf_folder_loaded = str(st.session_state.get("fusion_pdf_folder_last_loaded", "") or "")
            if current_pdf_folder_resolved and current_pdf_folder_resolved != last_pdf_folder_loaded:
                auto_loaded_files = _load_pdfs_from_folder(pdf_folder)
                st.session_state["fusion_preset_pdf_files"] = auto_loaded_files
                st.session_state["fusion_selected_pdfs"] = auto_loaded_files
                st.session_state["fusion_pdf_folder_last_loaded"] = current_pdf_folder_resolved
                if auto_loaded_files:
                    st.success(f"{len(auto_loaded_files)} PDF(s) carregado(s) automaticamente da pasta.")
                else:
                    st.warning("Nenhum PDF encontrado na pasta informada.")

            if st.button("Ler PDFs da pasta para o preset", key="scan_preset_pdf_folder_btn"):
                pdf_files = _load_pdfs_from_folder(pdf_folder)
                if pdf_files:
                    st.session_state["fusion_preset_pdf_files"] = pdf_files
                    st.session_state["fusion_selected_pdfs"] = pdf_files
                    if current_pdf_folder_resolved:
                        st.session_state["fusion_pdf_folder_last_loaded"] = current_pdf_folder_resolved
                    st.success(f"{len(pdf_files)} PDF(s) carregado(s) para o preset.")
                else:
                    st.warning("Pasta de PDFs nao encontrada.")

            uploaded_pdfs_for_preset = st.file_uploader(
                "Ou selecione PDFs pelo navegador",
                type=["pdf"],
                accept_multiple_files=True,
                key="fusion_uploaded_pdfs",
            )

            uploaded_pdf_paths_for_preset: list[str] = []
            if uploaded_pdfs_for_preset:
                upload_dir_text = str(st.session_state.get("fusion_uploaded_pdf_dir", "") or "")
                if upload_dir_text:
                    upload_dir = Path(upload_dir_text)
                else:
                    upload_dir = Path(tempfile.mkdtemp(prefix="fusion_preset_pdfs_"))
                    st.session_state["fusion_uploaded_pdf_dir"] = str(upload_dir)

                upload_dir.mkdir(parents=True, exist_ok=True)
                for idx, uploaded_pdf in enumerate(uploaded_pdfs_for_preset, start=1):
                    upload_name = Path(getattr(uploaded_pdf, "name", f"upload_{idx}.pdf")).name
                    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", upload_name)
                    target_path = upload_dir / f"{idx:03d}_{safe_name}"
                    target_path.write_bytes(uploaded_pdf.getvalue())
                    uploaded_pdf_paths_for_preset.append(str(target_path.resolve()))
                st.caption(f"{len(uploaded_pdf_paths_for_preset)} PDF(s) carregado(s) via navegador.")

            available_pdfs = st.session_state.get("fusion_preset_pdf_files", [])
            selected_pdfs = st.multiselect(
                "PDFs usados no preset",
                options=available_pdfs,
                default=available_pdfs,
                key="fusion_selected_pdfs",
            )

            selected_pdf_paths_for_cmd = list(
                dict.fromkeys(list(selected_pdfs) + list(uploaded_pdf_paths_for_preset))
            )

            resolved_preset_cmd = resolve_preset_command(
                selected_preset,
                municipio=municipio_for_run,
                pdf_paths=selected_pdf_paths_for_cmd,
            )
            if resolved_preset_cmd:
                st.code(" ".join(resolved_preset_cmd), language="bash")

            if st.button("Executar preset de extracao", key="run_extractor_preset_btn"):
                selected_pdfs_to_run = list(selected_pdf_paths_for_cmd)
                if selected_preset.requires_pdfs and not selected_pdfs_to_run:
                    if available_pdfs:
                        selected_pdfs_to_run = list(available_pdfs)
                    elif pdf_folder:
                        pdf_root = Path(pdf_folder).expanduser()
                        if pdf_root.exists():
                            selected_pdfs_to_run = sorted(str(p.resolve()) for p in pdf_root.glob("*.pdf"))
                            if selected_pdfs_to_run:
                                st.session_state["fusion_preset_pdf_files"] = selected_pdfs_to_run
                    if selected_pdfs_to_run:
                        st.session_state["fusion_selected_pdfs"] = selected_pdfs_to_run
                        st.info(
                            f"Nenhum PDF selecionado. Usando automaticamente {len(selected_pdfs_to_run)} PDF(s)."
                        )

                resolved_cmd_to_run = resolve_preset_command(
                    selected_preset,
                    municipio=municipio_for_run,
                    pdf_paths=selected_pdfs_to_run,
                )

                if selected_preset.requires_pdfs and not selected_pdfs_to_run:
                    st.warning("Selecione ao menos um PDF para este preset.")
                elif not resolved_cmd_to_run:
                    st.error("Nao foi possivel montar o comando do preset.")
                else:
                    try:
                        run_id = build_run_id(municipio_for_run, selected_adapter)
                        run_dir = (Path(EXTRACTION_OUTPUTS_DIR) / run_id).resolve()
                        run_dir.mkdir(parents=True, exist_ok=True)
                        log_path = (Path(EXTRACTION_LOGS_DIR) / f"{run_id}_extractor.log").resolve()

                        cli_result = run_extractor_cli(
                            cmd=resolved_cmd_to_run,
                            workdir=cli_workdir,
                            log_path=log_path,
                            run_id=run_id,
                        )
                        st.session_state["fusion_cli_result"] = cli_result
                        st.session_state["fusion_run_id"] = run_id
                        st.session_state["fusion_run_dir"] = str(run_dir)

                        if cli_result.get("success"):
                            contract_result = ensure_contract_master(
                                scan_dir_after_cli,
                                stable_contract_path,
                                run_id=run_id,
                                adapter=selected_adapter,
                                required_columns=REQUIRED_CONTRACT_COLUMNS,
                            )
                            run_contract_path = run_dir / "contract_master.csv"
                            copy_contract_file(
                                contract_result["source_contract"],
                                run_contract_path,
                                run_id=run_id,
                                adapter=selected_adapter,
                                required_columns=REQUIRED_CONTRACT_COLUMNS,
                            )
                            st.session_state["fusion_found_outputs"] = contract_result["found_outputs"]
                            st.session_state["fusion_contract_source"] = contract_result["source_contract"]
                    except Exception as exc:
                        st.error(f"Falha ao executar preset/atualizar contrato: {exc}")

            cli_result = st.session_state.get("fusion_cli_result")
            if cli_result:
                status_text = (
                    f"CLI finalizado com sucesso em {cli_result['duration_sec']}s (returncode={cli_result.get('returncode')})."
                    if cli_result.get("success")
                    else f"CLI finalizado com erro (returncode={cli_result.get('returncode')})."
                )
                if cli_result.get("success"):
                    st.success(status_text)
                else:
                    st.error(status_text)
                    if cli_result.get("log_path"):
                        st.error(f"Verifique o log: {cli_result['log_path']}")

                if cli_result.get("log_path"):
                    st.caption(f"Log da execucao: `{cli_result['log_path']}`")
                    st.text_area(
                        "Ultimas 200 linhas do log",
                        tail_log_lines(cli_result["log_path"], max_lines=200),
                        height=220,
                    )

                if st.session_state.get("fusion_run_id"):
                    st.caption(
                        f"Run ID: `{st.session_state['fusion_run_id']}` | "
                        f"Pasta run: `{st.session_state.get('fusion_run_dir', '-')}`"
                    )

        default_output_dir = str(
            st.session_state.get(
                "fusion_output_dir",
                st.session_state.get("extraction_root_path", str(EXTRACTION_OUTPUTS_DIR)),
            )
        )
        output_dir_text = st.text_input(
            "Pasta com outputs da extracao (master.csv / outputs.xlsx)",
            value=default_output_dir,
            key="fusion_output_dir",
        ).strip()

        if st.button("Localizar outputs e promover contrato estavel", key="find_contract_files_btn"):
            try:
                run_id = st.session_state.get("fusion_run_id") or build_run_id(
                    setup.get("city", "municipio"),
                    selected_adapter,
                )
                contract_result = ensure_contract_master(
                    output_dir_text,
                    stable_contract_path,
                    run_id=run_id,
                    adapter=selected_adapter,
                    required_columns=REQUIRED_CONTRACT_COLUMNS,
                )
                st.session_state["fusion_found_outputs"] = contract_result["found_outputs"]
                st.session_state["fusion_contract_source"] = contract_result["source_contract"]
                if not st.session_state.get("fusion_run_id"):
                    run_dir = (Path(EXTRACTION_OUTPUTS_DIR) / run_id).resolve()
                    run_dir.mkdir(parents=True, exist_ok=True)
                    st.session_state["fusion_run_id"] = run_id
                    st.session_state["fusion_run_dir"] = str(run_dir)
                run_contract_path = Path(st.session_state["fusion_run_dir"]) / "contract_master.csv"
                copy_contract_file(
                    contract_result["source_contract"],
                    run_contract_path,
                    run_id=st.session_state["fusion_run_id"],
                    adapter=selected_adapter,
                    required_columns=REQUIRED_CONTRACT_COLUMNS,
                )
                st.success("Contrato estavel atualizado com sucesso.")
            except Exception as exc:
                st.error(f"Falha ao localizar/promover contrato: {exc}")

        found_outputs = st.session_state.get("fusion_found_outputs")
        if found_outputs and found_outputs.get("all_candidates"):
            st.caption(
                f"Arquivos detectados: {len(found_outputs['all_candidates'])} | "
                f"master.csv: {bool(found_outputs.get('master_csv'))} | "
                f"outputs.xlsx: {bool(found_outputs.get('outputs_xlsx'))}"
            )
            if st.session_state.get("fusion_contract_source"):
                st.caption(f"Fonte atual do contrato: `{st.session_state['fusion_contract_source']}`")
        elif found_outputs:
            st.warning("Nenhum arquivo de contrato encontrado na pasta informada.")

        if not stable_contract_path.exists():
            st.warning("Contrato estavel ainda nao existe. Rode a extracao ou promova um output primeiro.")
        else:
            st.success("Contrato estavel pronto para pipeline de orcamento.")
            stable_meta = load_contract_metadata(stable_meta_path)
            if stable_meta:
                st.caption(
                    f"Meta contrato: schema={stable_meta.get('schema_version')} | "
                    f"rows={stable_meta.get('row_count')} | uc={stable_meta.get('uc_count')} | "
                    f"meses={stable_meta.get('months_count')} | run={stable_meta.get('run_id')}"
                )
                if stable_meta.get("missing_columns"):
                    st.warning(
                        "Meta detectou colunas faltantes: " + ", ".join(stable_meta.get("missing_columns", []))
                    )
            else:
                st.warning("Metadata do contrato ausente (contract_master.meta.json).")

        if stable_contract_path.exists() and selected_adapter == "auto":
            try:
                raw_for_detection = read_contract_dataframe_raw(stable_contract_path)
                detection = detect_adapter(raw_for_detection, outputs_info=found_outputs)
                if detection.get("is_confident"):
                    st.success(
                        f"Deteccao AUTO: {str(detection.get('adapter', '')).upper()} "
                        f"(score={detection.get('confidence', 0):.2f})"
                    )
                else:
                    st.warning("AUTO sem confianca. Selecione manualmente CELESC/ENEL/CPFL.")
            except Exception as exc:
                st.warning(f"Nao foi possivel detectar adapter automaticamente: {exc}")

        p1, p2, p3 = st.columns(3)
        with p1:
            tariff_rs_kwh = brl_text_input(
                add_abbreviation_meanings("Tarifa para economia (R$/kWh)"),
                state_key="fusion_tariff_rs_kwh",
                default_value=float(st.session_state.get("fusion_tariff_rs_kwh", 0.85)),
                placeholder="Ex: R$ 0,85",
            )
        productivity = p2.number_input(
            add_abbreviation_meanings("Produtividade (kWh/kWp.ano)"),
            min_value=100.0,
            value=float(st.session_state.get("fusion_productivity", 1350.0)),
            step=10.0,
            key="fusion_productivity",
        )
        opex_pct = p3.number_input(
            add_abbreviation_meanings("OPEX anual (% CAPEX)"),
            min_value=0.0,
            max_value=1.0,
            value=float(st.session_state.get("fusion_opex_pct", 0.02)),
            step=0.005,
            key="fusion_opex_pct",
        )
        q1, q2, q3 = st.columns(3)
        ppp_share = q1.number_input(
            "PPP share investidor (0-1)",
            min_value=0.0,
            max_value=1.0,
            value=float(st.session_state.get("fusion_ppp_share", 0.70)),
            step=0.05,
            key="fusion_ppp_share",
        )
        with q2:
            additional_capex = brl_text_input(
                add_abbreviation_meanings("CAPEX adicional (R$)"),
                state_key="fusion_additional_capex",
                default_value=float(st.session_state.get("fusion_additional_capex", 0.0)),
            )
        expected_months = int(
            q3.number_input(
                "Meses esperados no contrato",
                min_value=1,
                max_value=36,
                value=int(st.session_state.get("fusion_expected_months", DEFAULT_FUSION_EXPECTED_MONTHS)),
                step=1,
                key="fusion_expected_months",
            )
        )
        allow_quality_override = st.checkbox(
            "Permitir calculo mesmo com gaps criticos de qualidade",
            value=False,
            key="fusion_allow_quality_override",
        )

        if st.button("Calcular pipeline de orcamento (contrato estavel)", key="run_fusion_pipeline_btn"):
            if not stable_contract_path.exists():
                st.error("Contrato estavel nao encontrado. Atualize contract_master.csv antes de calcular.")
            else:
                current_mwp_ac = float(setup.get("mwp_ac", 0.0) or 0.0)
                if current_mwp_ac <= 0:
                    st.error(
                        add_abbreviation_meanings(
                            "MWp AC do projeto nao definido. Aplique um dimensionamento na etapa de extracao antes de calcular."
                        )
                    )
                    st.stop()
                module_for_pipeline = find_by_model(modules_catalog, active_scenario.get("module_model", "")) or modules_catalog[0]
                inverter_for_pipeline = find_by_model(inverters_catalog, active_scenario.get("inverter_model", "")) or inverters_catalog[0]

                module_price_sem = (
                    active_scenario.get("module_price_sem_override")
                    if active_scenario.get("module_price_sem_override") is not None
                    else float(module_for_pipeline["price_sem_bdi_per_kwp"])
                )
                module_price_com = (
                    active_scenario.get("module_price_com_override")
                    if active_scenario.get("module_price_com_override") is not None
                    else float(module_for_pipeline["price_com_bdi_per_kwp"])
                )
                inverter_price_sem = (
                    active_scenario.get("inverter_price_sem_override")
                    if active_scenario.get("inverter_price_sem_override") is not None
                    else float(inverter_for_pipeline["price_sem_bdi"])
                )
                inverter_price_com = (
                    active_scenario.get("inverter_price_com_override")
                    if active_scenario.get("inverter_price_com_override") is not None
                    else float(inverter_for_pipeline["price_com_bdi"])
                )

                budget_inputs = BudgetInputs(
                    mwp_ac=current_mwp_ac,
                    dc_ac_ratio=float(active_scenario.get("dc_ac_ratio", 1.20)),
                    module_wp=float(module_for_pipeline["wp"]),
                    inverter_kw=float(inverter_for_pipeline["kw"]),
                    module_price_com_bdi_per_kwp=float(module_price_com),
                    inverter_price_com_bdi=float(inverter_price_com),
                    module_price_sem_bdi_per_kwp=float(module_price_sem),
                    inverter_price_sem_bdi=float(inverter_price_sem),
                    additional_capex=float(additional_capex),
                    opex_pct_capex=float(opex_pct),
                    productivity_kwh_kwp_year=float(productivity),
                    energy_tariff_rs_kwh=float(tariff_rs_kwh),
                    ppp_investor_share_pct=float(ppp_share),
                )

                try:
                    pipeline = build_budget_pipeline(
                        contract_path=stable_contract_path,
                        adapter_name=selected_adapter,
                        inputs=budget_inputs,
                        expected_months=expected_months,
                    )
                except ContractSchemaError as exc:
                    st.error(
                        "Contrato invalido para schema v1. Sugestao: selecione o adapter correto ou execute novamente a extracao."
                    )
                    st.write(f"Colunas faltantes: {', '.join(exc.missing_columns)}")
                    st.write(f"Colunas detectadas: {', '.join(exc.actual_columns)}")
                except Exception as exc:
                    st.error(
                        f"Falha no pipeline de fusao [{type(exc).__name__}]: {exc}\n\n"
                        "Verifique se o contrato CSV contem as colunas obrigatorias "
                        f"({', '.join(REQUIRED_CONTRACT_COLUMNS)}) e se os valores numericos "
                        "estao no formato correto (sem caracteres especiais inesperados)."
                    )
                else:
                    quality = pipeline["quality"]
                    st.session_state["fusion_quality_report"] = quality
                    st.session_state["fusion_pipeline_rows"] = {
                        "raw_rows": pipeline["raw_rows"],
                        "standardized_rows": pipeline["standardized_rows"],
                    }
                    st.session_state["fusion_pipeline_preview"] = pipeline["standardized_df"].head(200)
                    st.session_state["fusion_adapter_used"] = pipeline.get("adapter_used")
                    st.session_state["fusion_adapter_detection"] = pipeline.get("adapter_detection")
                    if quality.get("is_critical") and not allow_quality_override:
                        st.session_state["fusion_pipeline_metrics"] = None
                        st.warning("Qualidade critica detectada. Ajuste os dados ou ative override para liberar o calculo.")
                    else:
                        st.session_state["fusion_pipeline_metrics"] = pipeline["metrics"]
                        st.success("Pipeline de fusao executado com sucesso.")

        quality = st.session_state.get("fusion_quality_report")
        if quality:
            st.markdown("**Painel de Qualidade dos Dados**")
            qx1, qx2, qx3, qx4 = st.columns(4)
            qx1.metric("UCs (Unidades Consumidoras) unicas", f"{quality['unique_ucs']:,}")
            qx2.metric("Meses disponiveis", f"{quality['month_count']}")
            qx3.metric("Meses esperados", f"{quality['expected_months']}")
            qx4.metric("Linhas sem referencia", f"{quality['missing_reference_count']}")
            if quality.get("null_zero_stats_by_class"):
                st.dataframe(pd.DataFrame(quality["null_zero_stats_by_class"]), hide_index=True, width="stretch")

            missing_refs_df = pd.DataFrame(quality.get("missing_references_list", []))
            if not missing_refs_df.empty:
                st.write("Referencias ausentes:")
                st.dataframe(missing_refs_df, hide_index=True, width="stretch")
                st.download_button(
                    "Export missing refs CSV",
                    data=df_to_csv_bytes(missing_refs_df),
                    file_name="missing_references.csv",
                    mime="text/csv",
                    key="download_missing_refs_csv",
                )

            ucs_missing_df = pd.DataFrame(quality.get("ucs_with_missing_months", []))
            if not ucs_missing_df.empty:
                st.write("UCs (Unidades Consumidoras) com meses faltando:")
                st.dataframe(ucs_missing_df, hide_index=True, width="stretch")
                st.download_button(
                    "Export UCs (Unidades Consumidoras) missing months CSV",
                    data=df_to_csv_bytes(ucs_missing_df),
                    file_name="ucs_with_missing_months.csv",
                    mime="text/csv",
                    key="download_ucs_missing_months_csv",
                )

            ucs_zero_df = pd.DataFrame(quality.get("ucs_all_zero_kwh", []))
            if not ucs_zero_df.empty:
                st.write(add_abbreviation_meanings("UCs com kWh zerado em todos os registros:"))
                st.dataframe(ucs_zero_df, hide_index=True, width="stretch")

            if quality.get("is_critical"):
                for msg in quality.get("critical_messages", []):
                    st.warning(msg)
            else:
                st.success("Qualidade de dados dentro dos criterios minimos.")

        st.markdown("**Run History**")
        run_history = scan_run_history(EXTRACTION_OUTPUTS_DIR)
        if run_history:
            history_df = pd.DataFrame(run_history)
            st.dataframe(
                history_df[["run_id", "timestamp", "municipio", "adapter", "status", "row_count"]],
                hide_index=True,
                width="stretch",
            )
            loadable_runs = [row["run_id"] for row in run_history if row.get("contract_path")]
            if loadable_runs:
                selected_run_id = st.selectbox("Selecionar run para carregar", loadable_runs, key="history_run_select")
                if st.button("Load this run", key="load_run_history_btn"):
                    selected_row = next((row for row in run_history if row["run_id"] == selected_run_id), None)
                    if selected_row and selected_row.get("contract_path"):
                        try:
                            copy_contract_file(
                                selected_row["contract_path"],
                                stable_contract_path,
                                run_id=selected_row.get("run_id", ""),
                                adapter=selected_row.get("adapter", ""),
                                required_columns=REQUIRED_CONTRACT_COLUMNS,
                            )
                            st.session_state["fusion_run_id"] = selected_row.get("run_id", "")
                            st.session_state["fusion_run_dir"] = str(Path(EXTRACTION_OUTPUTS_DIR) / selected_row.get("run_id", ""))
                            st.success(f"Run carregado: {selected_run_id}")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Falha ao carregar run: {exc}")
        else:
            st.info("Nenhum run encontrado em data/outputs_extraction.")

        fusion_rows = st.session_state.get("fusion_pipeline_rows")
        fusion_metrics = st.session_state.get("fusion_pipeline_metrics")
        fusion_preview = st.session_state.get("fusion_pipeline_preview")
        if fusion_rows and fusion_metrics:
            st.caption(
                f"Linhas carregadas: bruto={fusion_rows['raw_rows']} | "
                f"padronizado={fusion_rows['standardized_rows']}"
            )
            if st.session_state.get("fusion_adapter_used"):
                st.caption(f"Adapter usado no calculo: {str(st.session_state['fusion_adapter_used']).upper()}")
            class_totals = fusion_metrics["consumption_by_class_kwh"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric(add_abbreviation_meanings("Consumo B3 (kWh)"), f"{class_totals['B3']:,.0f}")
            c2.metric(add_abbreviation_meanings("Consumo IP (kWh)"), f"{class_totals['IP']:,.0f}")
            c3.metric(add_abbreviation_meanings("Consumo A4 (kWh)"), f"{class_totals['A4']:,.0f}")
            c4.metric(add_abbreviation_meanings("Consumo total (kWh)"), f"{class_totals['TOTAL']:,.0f}")

            capex = fusion_metrics["capex_com_bdi"]
            ppp = fusion_metrics["ppp"]
            z1, z2, z3 = st.columns(3)
            z1.metric(add_abbreviation_meanings("CAPEX total COM BDI"), format_brl(capex["total"]))
            z2.metric(add_abbreviation_meanings("OPEX anual"), format_brl(fusion_metrics["opex"]["annual_opex"]))
            z3.metric(
                "Payback simples",
                "-" if ppp["simple_payback_years"] is None else f"{ppp['simple_payback_years']:.1f} anos",
            )
            st.write(
                f"PPP receita investidor anual: `{format_brl(ppp['annual_ppp_investor_revenue'])}` | "
                f"economia cliente anual: `{format_brl(ppp['annual_ppp_customer_savings'])}`"
            )
            if isinstance(fusion_preview, pd.DataFrame) and not fusion_preview.empty:
                st.dataframe(fusion_preview, hide_index=True, width="stretch")


    section_end()

    section_start("Configurar Adaptadores de Distribuidora", chip="Config", solid=True)
    with st.expander("Criar ou editar adaptador para nova distribuidora", expanded=False):
        render_adapter_mapper()
    section_end()

    section_start("Controles de Engenharia", chip="Sizing", solid=True)
    size_col, ratio_col = st.columns(2)
    current_mwp_ac = float(setup.get("mwp_ac", 0.0) or 0.0)
    if current_mwp_ac > 0:
        size_col.metric(add_abbreviation_meanings("Potencia da usina (MWp AC)"), f"{current_mwp_ac:.3f}")
        if setup.get("extraction_source_file"):
            size_col.caption(f"Fonte: {setup.get('extraction_source_file')}")
    else:
        size_col.warning(
            add_abbreviation_meanings("MWp AC nao definido. Use a etapa de extracao para aplicar um dimensionamento.")
        )
        size_col.metric(add_abbreviation_meanings("Potencia da usina (MWp AC)"), "N/D")
    active_scenario["dc_ac_ratio"] = ratio_col.number_input(
        add_abbreviation_meanings("Razao DC/AC (cenario ativo)"),
        min_value=0.8,
        value=float(active_scenario.get("dc_ac_ratio", 1.20)),
        step=0.05,
    )

    ac_kwp = current_mwp_ac * 1000.0
    dc_kwp = ac_kwp * float(active_scenario["dc_ac_ratio"])
    m1, m2, m3 = st.columns(3)
    m1.metric(add_abbreviation_meanings("Potencia AC (kWp)"), f"{ac_kwp:,.0f}")
    m2.metric(add_abbreviation_meanings("Potencia DC (kWp)"), f"{dc_kwp:,.0f}")
    m3.metric(add_abbreviation_meanings("Origem do MWp"), "Extracao" if current_mwp_ac > 0 else "Nao definida")

    section_end()
    render_nav_buttons(project)

elif project["wizard_step"] == "B":
    from pages.step_b import render_step_b

    render_step_b(ctx)

elif project["wizard_step"] == "C":
    from pages.step_c import render_step_c

    render_step_c(ctx)

elif project["wizard_step"] == "D":
    from pages.step_d import render_step_d

    render_step_d(ctx)

elif project["wizard_step"] == "E":
    from pages.step_e import render_step_e

    render_step_e(ctx)

render_footer("SolarBudget")
