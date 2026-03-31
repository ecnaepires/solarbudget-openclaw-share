"""Simple (one-shot) mode for the SolarBudget dashboard.

Extracted from app.py to keep the main entry point as a thin orchestration layer.
All business logic lives in services/; this module only handles UI flow for the
simple PDF-upload → extract → budget → download workflow.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, List

import pandas as pd
import streamlit as st

from config import DEFAULT_CAPEX_BRL_PER_MWP, DEFAULT_MONTHS_TO_USE
from services.extraction_bridge_service import default_extraction_root
from services.scenario_bundle_service import build_scenario_bundle
from ui.extraction_helpers import (
    _merge_warning_messages,
    dimensionar,
    exportar_extracao,
    orcamentar as _orcamentar_ui,
    process_pdfs,
)
from ui.helpers import (
    add_abbreviation_meanings,
    brl_text_input,
    format_brl,
    slugify_filename as _slugify_filename,
)
from ui.style import render_dash_stats, render_empty_state, section_end, section_start


def _orcamentar(
    project: dict,
    scenario_name: str,
    modules_catalog: List[dict],
    inverters_catalog: List[dict],
    excel_map: dict,
    *,
    mwp_ac: float,
) -> dict:
    """Thin wrapper that injects build_scenario_bundle into the shared orcamentar fn."""
    return _orcamentar_ui(
        project,
        scenario_name,
        modules_catalog,
        inverters_catalog,
        excel_map,
        mwp_ac=mwp_ac,
        build_scenario_bundle_fn=build_scenario_bundle,
    )


def _describe_error(exc: Exception) -> tuple[str, str]:
    """Return (title, guidance) for known error types."""
    exc_type = type(exc).__name__

    if isinstance(exc, FileNotFoundError):
        return (
            f"Arquivo nao encontrado [{exc_type}]",
            f"{exc}\n\nVerifique se o arquivo template.xlsx esta presente na pasta "
            "budget_dashboard/ e se o caminho do catalogo esta correto.",
        )

    if isinstance(exc, ImportError):
        return (
            f"Motor de extracao nao encontrado [{exc_type}]",
            f"{exc}\n\nVerifique se a pasta Project/estudo_faturas_municipios existe "
            "no mesmo nivel que budget_dashboard/ e se as dependencias estao instaladas.",
        )

    if isinstance(exc, ValueError):
        return (
            f"Erro de dados [{exc_type}]",
            f"{exc}\n\nProvaveis causas: adaptador nao corresponde a distribuidora dos PDFs, "
            "MWp calculado como zero (consumo insuficiente), ou colunas obrigatorias ausentes.",
        )

    if isinstance(exc, KeyError):
        return (
            f"Campo ausente [{exc_type}]: {exc}",
            "Um campo esperado nao foi encontrado nos dados extraidos. "
            "Verifique se o adaptador correto esta selecionado para sua distribuidora.",
        )

    return (
        f"Falha no processamento [{exc_type}]",
        f"{exc}\n\nVerifique se: os PDFs nao estao protegidos por senha, o adaptador "
        "corresponde a sua distribuidora, e o arquivo template.xlsx esta presente.",
    )


def render_simple_mode(
    *,
    project: dict,
    scenario_names: list[str],
    modules_catalog: list[dict],
    inverters_catalog: list[dict],
    excel_map: dict,
) -> None:
    setup = project["setup"]
    active_scenario_name = project.get("active_scenario", scenario_names[0] if scenario_names else "")
    if active_scenario_name not in scenario_names and scenario_names:
        active_scenario_name = scenario_names[0]
        project["active_scenario"] = active_scenario_name

    # ── Project info card ─────────────────────────────────────────
    section_start("Dados do Projeto", chip="1. Configurar")
    c1, c2 = st.columns(2)
    setup["client"] = c1.text_input("Cliente", value=str(setup.get("client", "") or ""), key="simple_client")
    setup["project_name"] = c1.text_input(
        "Projeto",
        value=str(setup.get("project_name", "Projeto Solar") or "Projeto Solar"),
        key="simple_project_name",
    )
    setup["city"] = c2.text_input("Cidade", value=str(setup.get("city", "") or ""), key="simple_city")
    setup["state"] = c2.text_input("UF", value=str(setup.get("state", "SP") or "SP"), key="simple_state").upper().strip()
    section_end()

    # ── Upload section ─────────────────────────────────────────────
    section_start("Upload de Faturas", chip="2. Enviar PDFs")
    uploaded_pdfs = st.file_uploader(
        "Arraste ou selecione os PDFs de faturas de energia",
        type=["pdf"],
        accept_multiple_files=True,
        key="simple_uploaded_invoice_pdfs",
    )
    section_end()

    pdf_count = len(uploaded_pdfs) if uploaded_pdfs else 0
    last_run_iso = str(st.session_state.get("simple_last_run_at", "") or "")
    last_run_text = "-"
    if last_run_iso:
        try:
            last_run_text = datetime.fromisoformat(last_run_iso).strftime("%d/%m/%Y %H:%M")
        except Exception:
            last_run_text = last_run_iso

    # ── Quick stats bar ────────────────────────────────────────────
    render_dash_stats([
        {"label": "Cliente", "value": setup.get("client", "") or "-"},
        {"label": "Projeto", "value": setup.get("project_name", "") or "-"},
        {"label": "PDFs carregados", "value": str(pdf_count), "accent": pdf_count > 0},
        {"label": "Ultimo processamento", "value": last_run_text},
    ])

    with st.expander("Parametros de Dimensionamento", expanded=False):
        dim_col_1, dim_col_2, dim_col_3 = st.columns(3)
        dim_col_1.number_input(
            "Janela de meses",
            min_value=1, max_value=36,
            value=int(st.session_state.get("dim_months_to_use", DEFAULT_MONTHS_TO_USE)),
            step=1, key="dim_months_to_use",
        )
        dim_col_2.number_input(
            add_abbreviation_meanings("HSP"),
            min_value=0.01,
            value=float(st.session_state.get("dim_hsp", 4.9)),
            step=0.1, key="dim_hsp",
        )
        dim_col_3.number_input(
            add_abbreviation_meanings("PR (eficiência)"),
            min_value=0.01, max_value=1.50,
            value=float(st.session_state.get("dim_pr", 0.80)),
            step=0.01, key="dim_pr",
        )
        dim_col_4, dim_col_5, dim_col_6 = st.columns(3)
        dim_col_4.number_input(
            "Dias por mês",
            min_value=1.0,
            value=float(st.session_state.get("dim_days", 30.0)),
            step=1.0, key="dim_days",
        )
        dim_col_5.number_input(
            add_abbreviation_meanings("Fator A4 HP"),
            min_value=0.01,
            value=float(st.session_state.get("dim_a4_hp_factor", 1.0)),
            step=0.05, key="dim_a4_hp_factor",
        )
        with dim_col_6:
            brl_text_input(
                add_abbreviation_meanings("CAPEX (R$/MWp)"),
                state_key="dim_capex_brl_per_mwp",
                default_value=float(st.session_state.get("dim_capex_brl_per_mwp", DEFAULT_CAPEX_BRL_PER_MWP)),
            )
        tariff_col_1, tariff_col_2, tariff_col_3, tariff_col_4 = st.columns(4)
        with tariff_col_1:
            brl_text_input(
                add_abbreviation_meanings("Tarifa B3 (R$/kWh)"),
                state_key="dim_tariff_b3",
                default_value=float(st.session_state.get("dim_tariff_b3", 0.0)),
                placeholder="Ex: R$ 0,85",
            )
        with tariff_col_2:
            brl_text_input(
                add_abbreviation_meanings("Tarifa B4A (R$/kWh)"),
                state_key="dim_tariff_b4a",
                default_value=float(st.session_state.get("dim_tariff_b4a", 0.0)),
                placeholder="Ex: R$ 0,80",
            )
        with tariff_col_3:
            brl_text_input(
                add_abbreviation_meanings("Tarifa A4 HP (R$/kWh)"),
                state_key="dim_tariff_a4_hp",
                default_value=float(st.session_state.get("dim_tariff_a4_hp", 0.0)),
                placeholder="Ex: R$ 0,95",
            )
        with tariff_col_4:
            brl_text_input(
                add_abbreviation_meanings("Tarifa A4 FHP (R$/kWh)"),
                state_key="dim_tariff_a4_fhp",
                default_value=float(st.session_state.get("dim_tariff_a4_fhp", 0.0)),
                placeholder="Ex: R$ 0,70",
            )

    default_extraction_root_path = Path(st.session_state.get("extraction_root_path", default_extraction_root())).expanduser()
    extraction_root_path = default_extraction_root_path if default_extraction_root_path.exists() else default_extraction_root()

    # ── Process action ─────────────────────────────────────────────
    st.markdown("")
    btn_col, info_col = st.columns([1, 2])
    process_clicked = btn_col.button(
        "Processar PDFs e gerar orcamento",
        type="primary",
        disabled=not uploaded_pdfs,
        key="simple_processar_btn",
        use_container_width=True,
    )
    info_col.caption(f"Pasta de extracao: `{extraction_root_path}`")

    if process_clicked:
        st.session_state.pop("simple_generated_outputs", None)
        status = st.status("Processando PDFs...", expanded=True)
        progress_bar = status.progress(0.0)

        ordered_names = [str(getattr(item, "name", "uploaded.pdf") or "uploaded.pdf") for item in (uploaded_pdfs or [])]
        file_index_by_name: dict[str, int] = {}
        for idx, file_name in enumerate(ordered_names, start=1):
            if file_name not in file_index_by_name:
                file_index_by_name[file_name] = idx
        total_files = max(1, len(ordered_names))

        def _on_simple_progress(event: dict[str, Any]) -> None:
            progress = float(event.get("progress", 0.0) or 0.0)
            progress = max(0.0, min(1.0, progress))
            progress_bar.progress(progress)

            total_pages = int(event.get("total_pages", 0) or 0)
            pages_processed = int(event.get("pages_processed", 0) or 0)
            current_pdf_name = str(event.get("current_pdf_name", "") or "")
            pdf_page_no = int(event.get("pdf_page_no", 0) or 0)
            pdf_pages = int(event.get("pdf_pages", 0) or 0)
            file_no = file_index_by_name.get(current_pdf_name, 0)
            percent_text = f"{int(progress * 100)}%"

            if total_pages > 0 and file_no > 0 and pdf_pages > 0:
                status.write(
                    f"Arquivo {file_no}/{total_files} | Pagina {pdf_page_no}/{pdf_pages} | "
                    f"{percent_text} | Global {pages_processed}/{total_pages}"
                )
            elif total_pages > 0:
                status.write(f"{percent_text} | Global {pages_processed}/{total_pages}")
            else:
                status.write("Processando PDFs...")

        try:
            months_to_use = int(st.session_state.get("dim_months_to_use", DEFAULT_MONTHS_TO_USE) or DEFAULT_MONTHS_TO_USE)
            hsp = float(st.session_state.get("dim_hsp", 4.9) or 4.9)
            performance_ratio = float(st.session_state.get("dim_pr", 0.80) or 0.80)
            days_per_month = float(st.session_state.get("dim_days", 30.0) or 30.0)
            a4_hp_factor = float(st.session_state.get("dim_a4_hp_factor", 1.0) or 1.0)
            capex_brl_per_mwp = float(st.session_state.get("dim_capex_brl_per_mwp", DEFAULT_CAPEX_BRL_PER_MWP) or DEFAULT_CAPEX_BRL_PER_MWP)

            tariff_b3 = float(st.session_state.get("dim_tariff_b3", 0.0) or 0.0)
            tariff_b4a = float(st.session_state.get("dim_tariff_b4a", 0.0) or 0.0)
            tariff_a4_hp = float(st.session_state.get("dim_tariff_a4_hp", 0.0) or 0.0)
            tariff_a4_fhp = float(st.session_state.get("dim_tariff_a4_fhp", 0.0) or 0.0)

            extraction_result = process_pdfs(
                uploaded_pdfs=uploaded_pdfs,
                extraction_root=extraction_root_path,
                municipio_override=str(setup.get("city", "") or ""),
                expand_a4_historico=True,
                months_to_use=months_to_use,
                hsp=hsp,
                performance_ratio=performance_ratio,
                days_per_month=days_per_month,
                a4_hp_factor=a4_hp_factor,
                capex_brl_per_mwp=capex_brl_per_mwp,
                tariff_b3_rs_kwh=tariff_b3 if tariff_b3 > 0 else None,
                tariff_b4a_rs_kwh=tariff_b4a if tariff_b4a > 0 else None,
                tariff_a4_hp_rs_kwh=tariff_a4_hp if tariff_a4_hp > 0 else None,
                tariff_a4_fhp_rs_kwh=tariff_a4_fhp if tariff_a4_fhp > 0 else None,
                progress_callback=_on_simple_progress,
            )

            raw_df = extraction_result["raw_df"]
            records = extraction_result["records"]
            dimensionamento = dimensionar(
                records=records,
                raw_df=raw_df,
                preferred_municipio=str(setup.get("city", "") or ""),
                months_to_use=months_to_use,
            )
            mwp_final = float(dimensionamento["mwp_ac"] or 0.0)
            if mwp_final <= 0:
                raise ValueError("Nao foi possivel obter MWp final da extracao.")

            setup["mwp_ac"] = mwp_final
            setup["extraction_source_file"] = str(dimensionamento["selected_record"].get("source_file", "PDF upload"))
            setup["extraction_scenario"] = str(dimensionamento["selected_record"].get("cenario", "Dimensionamento Previo UFV"))
            setup["extraction_imported_mwp"] = mwp_final
            setup["extraction_imported_at"] = datetime.now().isoformat()

            orcamento = _orcamentar(
                project=project,
                scenario_name=active_scenario_name,
                modules_catalog=modules_catalog,
                inverters_catalog=inverters_catalog,
                excel_map=excel_map,
                mwp_ac=mwp_final,
            )

            now = datetime.now()
            project_slug = _slugify_filename(setup.get("project_name", setup.get("city", "projeto")))
            timestamp_slug = now.strftime("%Y-%m-%d_%H-%M-%S")
            extraction_name = f"{project_slug}_{timestamp_slug}_extracao.xlsx"
            budget_name = f"{project_slug}_{timestamp_slug}_orcamento.xlsx"

            resumo = {
                "generated_at": now.isoformat(),
                "client": str(setup.get("client", "") or ""),
                "project_name": str(setup.get("project_name", "") or ""),
                "municipio": str(setup.get("city", "") or ""),
                "state": str(setup.get("state", "") or ""),
                "scenario": active_scenario_name,
                "mwp_ac": mwp_final,
                "kwp_total": float(dimensionamento["kwp_total"] or 0.0),
                "pdf_count": pdf_count,
            }
            extraction_xlsx_bytes = exportar_extracao(raw_df=raw_df, records=records, resumo=resumo)
            budget_xlsx_bytes = orcamento["budget_xlsx_bytes"]

            warnings = _merge_warning_messages(
                extraction_result.get("warnings", []),
                dimensionamento.get("warnings", []),
                orcamento.get("warnings", []),
            )

            st.session_state["latest_extracted_raw_df"] = raw_df.copy() if isinstance(raw_df, pd.DataFrame) else pd.DataFrame()
            st.session_state["latest_extracted_records"] = deepcopy(records)
            st.session_state["simple_generated_outputs"] = {
                "generated_at": now.isoformat(),
                "mwp_final": mwp_final,
                "capex_final": float(orcamento["totals"]["grand_total_com_bdi"]),
                "warnings": warnings,
                "extraction_xlsx_bytes": extraction_xlsx_bytes,
                "budget_xlsx_bytes": budget_xlsx_bytes,
                "extraction_name": extraction_name,
                "budget_name": budget_name,
            }
            st.session_state["simple_last_run_at"] = now.isoformat()
            progress_bar.progress(1.0)
            status.update(label="Processamento finalizado.", state="complete", expanded=False)

        except FileNotFoundError as exc:
            title, guidance = _describe_error(exc)
            st.session_state["simple_generated_outputs"] = {}
            status.update(label="Falha no processamento.", state="error", expanded=True)
            st.error(f"**{title}**\n\n{guidance}")

        except ImportError as exc:
            title, guidance = _describe_error(exc)
            st.session_state["simple_generated_outputs"] = {}
            status.update(label="Falha no processamento.", state="error", expanded=True)
            st.error(f"**{title}**\n\n{guidance}")

        except (ValueError, KeyError) as exc:
            title, guidance = _describe_error(exc)
            st.session_state["simple_generated_outputs"] = {}
            status.update(label="Falha no processamento.", state="error", expanded=True)
            st.error(f"**{title}**\n\n{guidance}")

        except Exception as exc:
            title, guidance = _describe_error(exc)
            st.session_state["simple_generated_outputs"] = {}
            status.update(label="Falha no processamento.", state="error", expanded=True)
            st.error(f"**{title}**\n\n{guidance}")

    generated = st.session_state.get("simple_generated_outputs") or {}
    if generated:
        st.markdown("---")
        mwp_val = float(generated.get("mwp_final", 0.0) or 0.0)
        capex_val = float(generated.get("capex_final", 0.0) or 0.0)
        warnings = list(generated.get("warnings") or [])

        render_dash_stats([
            {"label": "MWp final", "value": f"{mwp_val:.3f}", "sub": "Megawatt-pico AC", "accent": True},
            {"label": "CAPEX total", "value": format_brl(capex_val), "sub": "COM BDI", "accent": True},
            {"label": "Avisos", "value": str(len(warnings)), "sub": "do processamento"},
        ])

        if warnings:
            with st.expander(f"Ver {len(warnings)} aviso(s)", expanded=False):
                for message in warnings:
                    st.warning(add_abbreviation_meanings(str(message)))

        section_start("Arquivos Gerados", chip="3. Download")
        d1, d2 = st.columns(2)
        d1.download_button(
            "Baixar Extracao (.xlsx)",
            data=generated.get("extraction_xlsx_bytes", b""),
            file_name=generated.get("extraction_name", "extracao.xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="simple_download_extracao_btn",
            use_container_width=True,
        )
        d2.download_button(
            "Baixar Orcamento (.xlsx)",
            data=generated.get("budget_xlsx_bytes", b""),
            file_name=generated.get("budget_name", "orcamento.xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="simple_download_orcamento_btn",
            use_container_width=True,
        )
        section_end()
    else:
        # No results yet — show empty state so the user knows what to expect
        render_empty_state(
            "☀️",
            "Nenhum resultado ainda",
            "Carregue os PDFs de faturas e clique em 'Processar' para gerar a extracao e o orcamento.",
        )
