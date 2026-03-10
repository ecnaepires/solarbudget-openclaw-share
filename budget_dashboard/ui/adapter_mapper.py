"""Streamlit UI component for visually creating/editing adapter configs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from adapters.config_loader import (
    ADAPTER_CONFIGS_DIR,
    AdapterConfig,
    ClassRule,
    ColumnMapping,
    DetectionHints,
    load_all_adapter_configs,
    save_adapter_config,
)
from adapters.config_adapter import ConfigDrivenAdapter


STANDARD_FIELDS = [
    {
        "key": "municipio",
        "label": "Municipio",
        "description": "Coluna com o nome do municipio/cidade",
        "required": False,
    },
    {
        "key": "uc",
        "label": "UC (Unidade Consumidora)",
        "description": "Coluna com o numero da unidade consumidora",
        "required": False,
    },
    {
        "key": "consumer_class",
        "label": "Classe/Categoria",
        "description": "Coluna com a classificacao (B3, A4, IP, etc.)",
        "required": False,
    },
    {
        "key": "reference_date",
        "label": "Data de Referencia",
        "description": "Coluna com a data/mes de referencia da fatura",
        "required": False,
    },
    {
        "key": "consumption_kwh",
        "label": "Consumo (kWh)",
        "description": "Coluna com o consumo total em kWh",
        "required": True,
    },
    {
        "key": "demand_kw",
        "label": "Demanda (kW)",
        "description": "Coluna com a demanda em kW",
        "required": False,
    },
    {
        "key": "source_file",
        "label": "Arquivo Origem",
        "description": "Coluna com o nome do arquivo de origem",
        "required": False,
    },
]

DEFAULT_CLASS_RULES = [
    {"pattern": "^ip$|iluminacao publica|^ip ", "value": "IP"},
    {"pattern": "a4|grupo a|alta tensao|\\bmt\\b", "value": "A4"},
    {"pattern": "b3|grupo b|comercial", "value": "B3"},
    {"default": "OUTROS"},
]

FALLBACK_MODES = {
    "uc": "index",
    "reference_date": "today_first_of_month",
}

FALLBACK_DEFAULTS = {
    "municipio": "NAO INFORMADO",
    "consumer_class": "OUTROS",
    "demand_kw": 0.0,
    "source_file": "extraction_output",
}


def _build_config_from_ui(
    adapter_name: str,
    description: str,
    column_selections: dict[str, str | None],
    detection_keywords: list[str],
) -> AdapterConfig:
    """Build an AdapterConfig from UI selections."""
    mappings: dict[str, ColumnMapping] = {}
    for field_info in STANDARD_FIELDS:
        key = field_info["key"]
        selected = column_selections.get(key)
        aliases = [selected] if selected else []
        mappings[key] = ColumnMapping(
            aliases=aliases,
            required=field_info["required"],
            fallback=FALLBACK_DEFAULTS.get(key),
            fallback_mode=FALLBACK_MODES.get(key),
            parse_as="float" if key in ("consumption_kwh", "demand_kw") else None,
        )

    class_rules = [
        ClassRule(pattern=r["pattern"], value=r["value"])
        if "pattern" in r
        else ClassRule(value=r["default"], is_default=True)
        for r in DEFAULT_CLASS_RULES
    ]

    clean_name = adapter_name.strip().lower().replace(" ", "_")
    keywords = [kw.strip().lower() for kw in detection_keywords if kw.strip()]

    return AdapterConfig(
        name=clean_name,
        description=description or f"Adapter para {adapter_name}",
        version="1.0",
        column_mappings=mappings,
        consumer_class_rules=class_rules,
        detection_hints=DetectionHints(
            column_keywords=keywords,
            content_keywords=keywords,
            column_signature=[],
            signature_score_boost=1.5,
        ),
    )


def render_adapter_mapper() -> None:
    """Render the adapter mapper UI inside a Streamlit expander/section."""

    st.markdown("##### Configurar Novo Adaptador de Distribuidora")
    st.caption(
        "Carregue um CSV de exemplo da nova distribuidora e mapeie as colunas "
        "para o schema padrao. O mapeamento sera salvo como configuracao YAML reutilizavel."
    )

    # Show existing configs
    existing = load_all_adapter_configs()
    if existing:
        st.markdown(
            f"**Adaptadores configurados:** {', '.join(sorted(existing.keys()))}"
        )

    uploaded = st.file_uploader(
        "CSV de exemplo da nova distribuidora",
        type=["csv", "xlsx", "xls"],
        key="adapter_mapper_upload",
    )
    if uploaded is None:
        return

    # Load sample data
    try:
        if uploaded.name.endswith(".csv"):
            sample_df = pd.read_csv(uploaded, encoding="utf-8-sig", nrows=100)
        else:
            sample_df = pd.read_excel(uploaded, nrows=100)
    except Exception as exc:
        st.error(f"Erro ao ler arquivo: {exc}")
        return

    if sample_df.empty:
        st.warning("Arquivo vazio.")
        return

    csv_columns = list(sample_df.columns)
    st.markdown(f"**Colunas encontradas ({len(csv_columns)}):** `{'`, `'.join(csv_columns)}`")

    with st.expander("Pre-visualizar dados (primeiras 5 linhas)", expanded=False):
        st.dataframe(sample_df.head(5), use_container_width=True)

    st.markdown("---")
    st.markdown("##### Mapeamento de Colunas")

    col1, col2 = st.columns(2)
    with col1:
        adapter_name = st.text_input(
            "Nome do adaptador (ex: equatorial, light, cemig)",
            key="adapter_mapper_name",
        )
    with col2:
        description = st.text_input(
            "Descricao (opcional)",
            key="adapter_mapper_desc",
            placeholder="Adapter para faturas da distribuidora X",
        )

    detection_keywords_str = st.text_input(
        "Palavras-chave para deteccao automatica (separadas por virgula)",
        key="adapter_mapper_keywords",
        placeholder="equatorial, eqtl",
        help="Palavras que aparecem nos nomes de colunas ou conteudo das faturas desta distribuidora",
    )
    detection_keywords = [kw.strip() for kw in detection_keywords_str.split(",") if kw.strip()]

    st.markdown("---")

    # Column mapping selectboxes
    none_option = "(nenhuma)"
    options = [none_option] + csv_columns
    column_selections: dict[str, str | None] = {}

    for field_info in STANDARD_FIELDS:
        key = field_info["key"]
        label = field_info["label"]
        desc = field_info["description"]
        required = field_info["required"]

        suffix = " *" if required else ""
        selected = st.selectbox(
            f"{label}{suffix}",
            options,
            key=f"adapter_mapper_col_{key}",
            help=desc,
        )
        column_selections[key] = selected if selected != none_option else None

    # Validate required
    missing_required = [
        f["label"]
        for f in STANDARD_FIELDS
        if f["required"] and not column_selections.get(f["key"])
    ]

    if missing_required:
        st.warning(f"Campos obrigatorios nao mapeados: {', '.join(missing_required)}")

    if not adapter_name or not adapter_name.strip():
        st.info("Informe o nome do adaptador para continuar.")
        return

    # Preview button
    st.markdown("---")
    if st.button("Pre-visualizar adaptacao", key="adapter_mapper_preview_btn"):
        config = _build_config_from_ui(
            adapter_name, description, column_selections, detection_keywords
        )
        try:
            adapter = ConfigDrivenAdapter(config)
            preview_df = adapter.adapt(sample_df)
            st.success(f"Adaptacao gerou {len(preview_df)} linhas.")
            st.dataframe(preview_df.head(10), use_container_width=True)
            st.session_state["_adapter_mapper_preview_config"] = config
        except Exception as exc:
            st.error(f"Erro na adaptacao: {exc}")

    # Save button
    can_save = not missing_required and adapter_name.strip()
    if can_save and st.button("Salvar adaptador", key="adapter_mapper_save_btn", type="primary"):
        config = _build_config_from_ui(
            adapter_name, description, column_selections, detection_keywords
        )
        try:
            out_path = save_adapter_config(config)
            st.success(f"Adaptador '{config.name}' salvo em: {out_path.name}")
            st.caption("Recarregue a pagina para usar o novo adaptador.")
            # Reload registry so it's immediately available
            from adapters import reload_registry
            reload_registry()
        except Exception as exc:
            st.error(f"Erro ao salvar: {exc}")
