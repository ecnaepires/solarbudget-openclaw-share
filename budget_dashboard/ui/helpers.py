"""Shared UI helper functions: formatting, BRL parsing, abbreviations, Excel utilities."""
from __future__ import annotations

import re
import tempfile
import unicodedata
from io import BytesIO
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

from excel_engine import write_full_budget_excel


STEP_FLOW = [
    ("A", "Configuracao do Projeto"),
    ("B", "Equipamentos"),
    ("C", "BOS (Balance of System) / Civil / Administrativo"),
    ("D", "Revisao"),
    ("E", "Gerar"),
]
SCALING_RULE_OPTIONS = ["fixed", "per_mwp_ac", "per_kwp_dc", "per_string", "percent_of_capex"]
EXTRACTION_NUMERIC_COLUMNS = [
    "kwh_total_te",
    "demanda_item",
    "dif_demanda",
    "demanda_contratada_kw",
    "demanda_hp_kw",
    "demanda_fhp_kw",
    "consumo_hp_kwh",
    "consumo_fhp_kwh",
    "total_fatura_rs",
    "itens_fatura_total_valor_rs",
    "itens_fatura_energia_valor_rs",
    "itens_fatura_energia_kwh",
    "itens_fatura_preco_medio_rs_kwh",
    "itens_fatura_preco_all_in_fhp_rs_kwh",
    "itens_fatura_preco_all_in_hp_rs_kwh",
    "itens_fatura_preco_all_in_blended_rs_kwh",
]


def render_nav_buttons(project: dict) -> None:
    step_codes = [code for code, _ in STEP_FLOW]
    current_idx = step_codes.index(project["wizard_step"])

    st.markdown("<div style='height: 12px'></div>", unsafe_allow_html=True)
    nav_left, nav_mid, nav_right = st.columns([1, 2, 1])
    if current_idx > 0:
        prev_code = step_codes[current_idx - 1]
        prev_name = dict(STEP_FLOW).get(prev_code, "")
        if nav_left.button(f"\u2190  {prev_code}. {prev_name}", key=f"back_{project['wizard_step']}"):
            project["wizard_step"] = prev_code
            st.rerun()
    if current_idx < len(step_codes) - 1:
        next_code = step_codes[current_idx + 1]
        next_name = dict(STEP_FLOW).get(next_code, "")
        if nav_right.button(f"{next_code}. {next_name}  \u2192", key=f"next_{project['wizard_step']}"):
            project["wizard_step"] = next_code
            st.rerun()
    nav_mid.caption("Use a barra lateral para navegar entre as etapas.")


def safe_index(options: List[str], value: str) -> int:
    if value in options:
        return options.index(value)
    return 0


def format_all_option(value: str) -> str:
    return "Todos" if value == "All" else value


def format_scenario_name(value: str) -> str:
    return value.replace("Scenario", "Cenario")


ABBREVIATION_MEANINGS = {
    "UFV": "Usina Fotovoltaica",
    "B3": "Grupo B3",
    "B4A": "Grupo B4A",
    "A4": "Grupo A4 (media tensao)",
    "HP": "Horario de Ponta",
    "FHP": "Fora de Horario de Ponta",
    "IP": "Iluminacao Publica",
    "UC": "Unidade Consumidora",
    "AC": "Corrente Alternada",
    "DC": "Corrente Continua",
    "kWh": "Quilowatt-hora",
    "kWp": "Quilowatt-pico",
    "MWp": "Megawatt-pico",
    "HSP": "Horas de Sol Pleno",
    "PR": "Performance Ratio",
    "MPPT": "Maximum Power Point Tracking",
    "STC": "Condicoes Padrao de Teste",
    "CAPEX": "Investimento Inicial",
    "OPEX": "Custo Operacional",
    "BOS": "Balance of System",
    "BDI": "Bonificacao e Despesas Indiretas",
}
_ABBREVIATION_PATTERN = re.compile(
    r"\b(" + "|".join(sorted((re.escape(k) for k in ABBREVIATION_MEANINGS), key=len, reverse=True)) + r")\b"
)


def add_abbreviation_meanings(text: str) -> str:
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        meaning = ABBREVIATION_MEANINGS.get(token)
        if not meaning:
            return token
        return f"{token} ({meaning})"

    return _ABBREVIATION_PATTERN.sub(_replace, text)


def _to_none_if_nan(value):
    if pd.isna(value):
        return None
    return float(value)


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def format_ptbr_number(value, decimals: int = 2) -> str:
    number = float(value or 0.0)
    usa = f"{number:,.{decimals}f}"
    return usa.replace(",", "_").replace(".", ",").replace("_", ".")


def format_brl(value) -> str:
    return f"R$ {format_ptbr_number(value, decimals=2)}"


def parse_brl_value(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    text = text.replace("R$", "").replace("r$", "").replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        if text.count(",") > 1:
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "." in text:
        dot_parts = text.split(".")
        if len(dot_parts) > 1 and all(part.isdigit() for part in dot_parts):
            if len(dot_parts) > 2 or all(len(part) == 3 for part in dot_parts[1:]):
                text = "".join(dot_parts)

    try:
        return float(text)
    except ValueError:
        return None


def brl_text_input(
    label: str,
    state_key: str,
    default_value: float,
    placeholder: str = "Ex: R$ 8.500.000,00",
) -> float:
    raw_key = f"{state_key}_raw"
    if raw_key not in st.session_state:
        st.session_state[raw_key] = format_brl(default_value)

    raw_value = st.text_input(label, key=raw_key, placeholder=placeholder)
    parsed = parse_brl_value(raw_value)
    if parsed is None:
        fallback = float(st.session_state.get(state_key, default_value) or default_value)
        if str(raw_value).strip():
            st.caption(f"Valor invalido em '{label}'. Mantido: {format_brl(fallback)}.")
        st.session_state[state_key] = fallback
        return fallback

    parsed_value = float(parsed)
    st.session_state[state_key] = parsed_value
    return parsed_value


def slugify_filename(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "arquivo"


# Keep old name for backward compat
_slugify_filename = slugify_filename


def _is_currency_column(column_name: str) -> bool:
    name = str(column_name or "").strip().lower()
    if not name:
        return False

    money_markers = (
        "r$", "_rs", "rs_", "brl", "valor", "price", "preco",
        "tarifa", "capex", "opex", "investment", "custo",
    )
    if "kwh" in name and "rs" not in name and "tarifa" not in name and "preco" not in name:
        return False
    return any(marker in name for marker in money_markers)


def _apply_currency_format_to_sheet(ws) -> None:
    currency_format = "[$R$-pt-BR] #,##0.00"
    headers = [ws.cell(row=1, column=col).value for col in range(1, ws.max_column + 1)]
    for col_idx, header in enumerate(headers, start=1):
        if not _is_currency_column(str(header or "")):
            continue
        for row_idx in range(2, ws.max_row + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            if isinstance(cell.value, (int, float)):
                cell.number_format = currency_format


def build_excel_bytes_from_frames(sheet_frames: Dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, frame in sheet_frames.items():
            df = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
            if df.empty:
                df = pd.DataFrame({"info": ["Sem dados para este bloco."]})
            safe_sheet = str(sheet_name)[:31] or "Sheet1"
            df.to_excel(writer, sheet_name=safe_sheet, index=False)

        workbook = writer.book
        for worksheet in workbook.worksheets:
            _apply_currency_format_to_sheet(worksheet)

    output.seek(0)
    return output.getvalue()


def write_budget_excel_bytes(updates: List[dict]) -> bytes:
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
            tmp_path = Path(tmp_file.name)
        write_full_budget_excel(updates, output_path=tmp_path)
        return tmp_path.read_bytes()
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
