"""Step E renderer."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from config import EXCEL_MAP_PATH, OUTPUT_PATH
from excel_engine import write_full_budget_excel
from services.extraction_bridge_service import default_extraction_root
from services.output_service import append_audit_log, build_output_paths, save_snapshot
from services.scenario_bundle_service import build_scenario_bundle
from ui.context import DashboardContext
from ui.extraction_helpers import _latest_extraction_payload, exportar_extracao
from ui.helpers import (
    add_abbreviation_meanings,
    format_brl,
    format_scenario_name,
    render_nav_buttons,
    safe_index,
    slugify_filename,
    write_budget_excel_bytes,
)
from ui.style import section_end, section_start


def render_step_e(ctx: DashboardContext) -> None:
    section_start("E. Gerar", chip=format_scenario_name(ctx.selected_scenario), solid=True)
    st.caption(
        "Exporte o cenario escolhido para Excel versionado + snapshot JSON e registre no log de auditoria."
    )

    export_scenario = st.selectbox(
        "Cenario escolhido para exportacao",
        ctx.scenario_names,
        index=safe_index(ctx.scenario_names, ctx.selected_scenario),
        format_func=format_scenario_name,
    )
    scenario_for_export = ctx.project["scenarios"][export_scenario]
    bundle = build_scenario_bundle(
        ctx.project,
        export_scenario,
        ctx.modules_catalog,
        ctx.inverters_catalog,
        ctx.excel_map,
    )

    preview_col1, preview_col2 = st.columns(2)
    preview_col1.metric(add_abbreviation_meanings("Total COM BDI mapeado"), format_brl(bundle["totals"]["grand_total_com_bdi"]))
    preview_col2.metric("Quantidade de atualizacoes no Excel", f"{len(bundle['updates'])}")
    current_mwp_for_export = float(ctx.setup.get("mwp_ac", 0.0) or 0.0)
    if current_mwp_for_export <= 0:
        st.warning(
            add_abbreviation_meanings(
                "MWp AC nao definido. Aplique um dimensionamento na etapa de extracao antes de exportar."
            )
        )

    st.divider()

    if st.button("Gerar arquivos de saida", type="primary", disabled=current_mwp_for_export <= 0):
        st.session_state.pop("generated_downloads", None)
        now = datetime.now()
        version_id = scenario_for_export.get("pricing_version", "NO_VERSION")
        project_name = ctx.setup.get("project_name", "project")
        xlsx_path, json_path, stamp = build_output_paths(
            project_name=project_name,
            version_id=version_id,
            scenario_name=export_scenario,
            timestamp=now,
        )
        extracted_xlsx_path = xlsx_path.with_name(f"{xlsx_path.stem}_extracao.xlsx")
        municipio_slug = slugify_filename(ctx.setup.get("city", ctx.setup.get("project_name", "municipio")))
        date_stamp = now.strftime("%Y-%m-%d")
        download_extracted_name = f"{municipio_slug}_extracao_{date_stamp}.xlsx"
        download_budget_name = f"{municipio_slug}_orcamento_{date_stamp}.xlsx"

        try:
            write_full_budget_excel(bundle["updates"], output_path=xlsx_path)
        except Exception as exc:
            st.error(f"Falha ao gerar Excel versionado: {exc}")
            section_end()
            render_nav_buttons(ctx.project)
            return

        try:
            budget_excel_bytes = write_budget_excel_bytes(bundle["updates"])
        except Exception as exc:
            st.error(f"Falha ao montar Excel de orcamento para download: {exc}")
            section_end()
            render_nav_buttons(ctx.project)
            return

        extraction_raw_df, extraction_records, extraction_resumo = _latest_extraction_payload(ctx.setup)
        extraction_root_for_export = Path(
            st.session_state.get("extraction_root_path", str(default_extraction_root()))
        ).expanduser()
        try:
            extracted_excel_bytes = exportar_extracao(
                raw_df=extraction_raw_df,
                records=extraction_records,
                resumo=extraction_resumo,
                extraction_root=extraction_root_for_export,
            )
            extracted_xlsx_path.write_bytes(extracted_excel_bytes)
        except Exception as exc:
            st.error(f"Falha ao gerar Excel extraido: {exc}")
            section_end()
            render_nav_buttons(ctx.project)
            return

        legacy_warning = None
        try:
            write_full_budget_excel(bundle["updates"], output_path=OUTPUT_PATH)
        except Exception as exc:
            legacy_warning = str(exc)

        snapshot_payload = {
            "generated_at": now.isoformat(),
            "file_timestamp": stamp,
            "excel_map_path": str(EXCEL_MAP_PATH),
            "excel_map_version": ctx.excel_map.get("version", ""),
            "project_setup": ctx.setup,
            "scenario_name": export_scenario,
            "scenario_inputs": scenario_for_export,
            "selected_module": bundle["module"],
            "selected_inverter": bundle["inverter"],
            "sizing_results": bundle["sizing"],
            "sheet_totals": bundle["sheet_totals"],
            "totals": bundle["totals"],
            "line_items": bundle["line_items"],
            "excel_updates": bundle["updates"],
            "versioned_excel_output": str(xlsx_path),
            "versioned_extracted_output": str(extracted_xlsx_path),
            "legacy_excel_output": str(OUTPUT_PATH),
        }
        save_snapshot(json_path, snapshot_payload)
        append_audit_log(
            timestamp_iso=now.isoformat(),
            project_name=project_name,
            version_id=version_id,
            scenario_name=export_scenario,
            excel_path=xlsx_path,
            snapshot_path=json_path,
        )

        st.session_state["generated_downloads"] = {
            "generated_at": now.isoformat(),
            "excel_budget_bytes": budget_excel_bytes,
            "excel_extracted_bytes": extracted_excel_bytes,
            "excel_budget_name": download_budget_name,
            "excel_extracted_name": download_extracted_name,
            "excel_budget_path": str(xlsx_path),
            "excel_extracted_path": str(extracted_xlsx_path),
            "snapshot_path": str(json_path),
            "legacy_warning": legacy_warning,
        }

        st.success("Arquivos gerados com sucesso.")
        st.write(f"- Excel orcamento: `{xlsx_path}`")
        st.write(f"- Excel extraido: `{extracted_xlsx_path}`")
        st.write(f"- Registro JSON: `{json_path}`")
        st.write("- Log de auditoria: `outputs/audit_log.csv`")
        if legacy_warning:
            st.warning(
                "A saida versionada foi gerada, mas o output.xlsx legado nao pode ser sobrescrito: "
                f"{legacy_warning}"
            )

    generated_downloads = st.session_state.get("generated_downloads", {})
    if generated_downloads:
        st.divider()
        st.markdown("**Downloads**")
        d1, d2 = st.columns(2)
        d1.download_button(
            "Download Excel Extraido",
            data=generated_downloads.get("excel_extracted_bytes", b""),
            file_name=generated_downloads.get("excel_extracted_name", "extracao.xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_excel_extracted_btn",
        )
        d2.download_button(
            "Download Excel Orcamento",
            data=generated_downloads.get("excel_budget_bytes", b""),
            file_name=generated_downloads.get("excel_budget_name", "orcamento.xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_excel_budget_btn",
        )

    section_end()
    render_nav_buttons(ctx.project)
