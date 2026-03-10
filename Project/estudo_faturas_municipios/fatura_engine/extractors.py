from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Iterable, List, Optional

import pandas as pd
import pdfplumber
from tqdm import tqdm

from .helpers import (
    normalize_whitespace,
    parse_ptbr_number,
    yyyymm_to_ref,
    date_to_ref,
    normalize_uc,
    normalize_reference_token,
)
from .models import UCMonthRecord
from . import regex as R


def br_to_float(x: str) -> float:
    # "1.234,56" -> 1234.56
    if x is None:
        return 0.0
    s = str(x).strip()
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def _normalize_ascii_upper(text: str) -> str:
    s = unicodedata.normalize("NFKD", text or "")
    s = s.encode("ASCII", "ignore").decode("ASCII")
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


def _month_ref(mon3: str, year: str) -> str:
    month_map = {
        "JAN": "01",
        "FEV": "02",
        "MAR": "03",
        "ABR": "04",
        "MAI": "05",
        "JUN": "06",
        "JUL": "07",
        "AGO": "08",
        "SET": "09",
        "OUT": "10",
        "NOV": "11",
        "DEZ": "12",
    }
    mm = month_map.get((mon3 or "").upper())
    if not mm:
        return ""
    yy = str(year or "").strip()
    if len(yy) == 2:
        yy = "20" + yy
    if len(yy) != 4:
        return ""
    return f"{mm}/{yy}"


REF_TOKEN_PATTERN = r"(?:[A-Z]{3}[/-]?\d{2,4}|(?:0?[1-9]|1[0-2])[/-]\d{2,4}|\d{6})"


def _extract_reference_from_text(text: str) -> str:
    if not text:
        return ""

    raw = normalize_whitespace(text)
    t = _normalize_ascii_upper(raw)

    labeled_patterns = [
        rf"\bREFERENCIA\b\s*[:\-]?\s*({REF_TOKEN_PATTERN})\b",
        rf"\bMES\s*/?\s*ANO\b\s*[:\-]?\s*({REF_TOKEN_PATTERN})\b",
        rf"\bCOMPETENCIA\b\s*[:\-]?\s*({REF_TOKEN_PATTERN})\b",
    ]
    for rx in labeled_patterns:
        m = re.search(rx, t, flags=re.IGNORECASE)
        if not m:
            continue
        ref = normalize_reference_token(m.group(1))
        if ref:
            return ref

    for m in re.finditer(r"\b(?:[A-Z]{3}[/-]?\d{2,4}|(?:0?[1-9]|1[0-2])[/-]\d{2,4})\b", t, flags=re.IGNORECASE):
        ref = normalize_reference_token(m.group(0))
        if ref:
            return ref

    return ""


def _run_regex_cascade(
    text: str,
    entries: Iterable[tuple[Any, str, Callable[[Any], Any]]],
    validator: Optional[Callable[[Any], bool]] = None,
) -> tuple[Any, str]:
    if not text:
        return None, ""

    def _default_validator(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    is_valid = validator or _default_validator
    for pattern, source_name, transform in entries:
        if pattern is None:
            continue
        match = pattern.search(text)
        if not match:
            continue
        try:
            value = transform(match)
        except Exception:
            continue
        if is_valid(value):
            return value, source_name
    return None, ""


def _find_uc_block_starts(text: str) -> list[int]:
    if not text:
        return []
    starts: set[int] = set()
    for pattern in (R.RE_UC, R.RE_INSTALACAO, R.RE_UNIDADE_CONSUMIDORA, R.RE_NUMERO_CLIENTE):
        starts.update(match.start() for match in pattern.finditer(text))
    return sorted(starts)


def _set_cached_page_text(page_texts: Optional[list[str]], page_index: int, text: str) -> None:
    if page_texts is None:
        return
    if 0 <= page_index < len(page_texts):
        page_texts[page_index] = text or ""


def _extract_uc_digit_fallback(text: str, target_len: int = 10) -> str:
    lines = [ln.strip() for ln in normalize_whitespace(text or "").split("\n") if ln.strip()]
    for line in lines[:12]:
        digits = re.sub(r"\D", "", line)
        if 6 <= len(digits) <= 12:
            return normalize_uc(digits, target_len=target_len)

    match = re.search(r"\b([0-9]{6,12})\b", _normalize_ascii_upper(text or ""))
    if not match:
        return ""
    return normalize_uc(match.group(1), target_len=target_len)


def _extract_uc_cascade(text: str, target_len: int = 10) -> tuple[str, str]:
    uc, source = _run_regex_cascade(
        normalize_whitespace(text or ""),
        [
            (R.RE_UC, "UC", lambda m: normalize_uc(m.group(1), target_len=target_len)),
            (R.RE_INSTALACAO, "INSTALACAO", lambda m: normalize_uc(m.group(1), target_len=target_len)),
            (
                R.RE_UNIDADE_CONSUMIDORA,
                "UNIDADE_CONSUMIDORA",
                lambda m: normalize_uc(m.group(1), target_len=target_len),
            ),
            (R.RE_NUMERO_CLIENTE, "NUMERO_CLIENTE", lambda m: normalize_uc(m.group(1), target_len=target_len)),
        ],
        validator=lambda value: bool(str(value or "").strip()),
    )
    if uc:
        return str(uc), source

    fallback = _extract_uc_digit_fallback(text or "", target_len=target_len)
    if fallback:
        return fallback, "DIGIT_FALLBACK"
    return "", ""


def _extract_reference_cascade(text: str) -> tuple[str, str]:
    ref, source = _run_regex_cascade(
        normalize_whitespace(text or ""),
        [
            (R.RE_REF, "REFERENCIA", lambda m: normalize_reference_token(m.group(1))),
            (R.RE_MES_ANO, "MES_ANO", lambda m: normalize_reference_token(m.group(1))),
            (R.RE_FATURA_YYYYMM, "FATURA_YYYYMM", lambda m: yyyymm_to_ref(m.group(1))),
            (R.RE_DATA_FAT, "DATA_FATURAMENTO", lambda m: date_to_ref(m.group(1))),
            (R.RE_PERIODO_REF, "PERIODO_REFERENCIA", lambda m: normalize_reference_token(m.group(1))),
        ],
        validator=lambda value: bool(str(value or "").strip()),
    )
    if ref:
        return str(ref), source

    fallback = _extract_reference_from_text(text or "")
    if fallback:
        return fallback, "GENERIC_REF_TOKEN"
    return "", ""


def _extract_kwh_cascade(text: str, section_text: str = "") -> tuple[Optional[float], str]:
    section = section_text or _extract_itens_da_fatura_section(text or "") or (text or "")
    value, source = _run_regex_cascade(
        section,
        [
            (R.RE_ITEM_CONSUMO_IP_TE_QTD, "ITEM_CONSUMO_IP_TE_QTD", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_ITEM_CONSUMO_TE_QTD, "ITEM_CONSUMO_TE_QTD", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_ITEM_ENERGIA_UNICO_QTD, "ITEM_ENERGIA_UNICO_QTD", lambda m: parse_ptbr_number(m.group(1))),
        ],
        validator=lambda value: value is not None and float(value) > 0,
    )
    if value is not None:
        return float(value), source

    value, source = _run_regex_cascade(
        text or "",
        [
            (R.RE_CONS_IP_TE, "CONS_IP_TE", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_CONS_IP_GENERIC, "CONS_IP_GENERIC", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_CONS_TE, "CONS_TE", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_ENERGIA_TE, "ENERGIA_TE", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_ENERGIA_ATIVA, "ENERGIA_ATIVA", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_ENERGIA_ELETRICA, "ENERGIA_ELETRICA", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_CONSUMO_KWH, "CONSUMO_KWH", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_ENERGIA_UNICO_APURADO, "ENERGIA_UNICO_APURADO", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_KWH_GENERIC, "KWH_GENERIC", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_KWH_BROKEN, "KWH_BROKEN", lambda m: parse_ptbr_number(m.group(1))),
        ],
        validator=lambda value: value is not None and float(value) > 0,
    )
    if value is not None:
        return float(value), source
    return None, ""


def _extract_demand_cascade(text: str) -> tuple[Optional[float], str]:
    value, source = _run_regex_cascade(
        text or "",
        [
            (R.RE_DEMANDA_ITEM, "DEMANDA_ITEM", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_DEMANDA_CONTRATADA, "DEMANDA_CONTRATADA", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_DEMANDA_REGISTRADA, "DEMANDA_REGISTRADA", lambda m: parse_ptbr_number(m.group(1))),
            (R.RE_DEMANDA_MEDIDA, "DEMANDA_MEDIDA", lambda m: parse_ptbr_number(m.group(1))),
        ],
        validator=lambda value: value is not None and float(value) > 0,
    )
    if value is not None:
        return float(value), source
    return None, ""


def _extract_classificacao_cascade(text: str) -> tuple[str, str]:
    classif, source = _run_regex_cascade(
        text or "",
        [
            (R.RE_CLASSIF, "CLASSIFICACAO_HEADER", lambda m: _clean_classificacao_text(m.group(1).strip())),
            (R.RE_CLASSE_CONSUMO, "CLASSE_CONSUMO", lambda m: _clean_classificacao_text(m.group(1).strip())),
            (R.RE_MODALIDADE, "MODALIDADE", lambda m: _clean_classificacao_text(m.group(1).strip())),
        ],
        validator=lambda value: bool(str(value or "").strip()),
    )
    if classif:
        return str(classif), source

    header = _extract_header_classificacao(text or "")
    if header:
        return header, "HEADER_CLASSIFICACAO"
    return "", ""


def _extract_categoria_bundle(text: str) -> dict[str, str]:
    grupo_tensao = ""
    subgrupo = ""
    source_pattern = ""

    match_grupo = R.RE_GRUPO.search(text or "")
    if match_grupo:
        grupo_tensao = match_grupo.group(1).upper()
        subgrupo = match_grupo.group(2).upper()
        source_pattern = "GRUPO_SUBGRUPO"
    else:
        match_subgrupo = R.RE_SUBGRUPO.search(text or "")
        if match_subgrupo:
            subgrupo = match_subgrupo.group(1).upper()
            grupo_tensao = subgrupo[:1]
            source_pattern = "SUBGRUPO"

    classif_line, classif_source = _extract_classificacao_cascade(text or "")
    categoria = categorize(grupo_tensao, subgrupo, classif_line)

    if categoria == "OUTROS" and classif_line:
        classif_norm = _normalize_ascii_upper(classif_line)
        if "ILUMINACAO PUBLICA" in classif_norm:
            categoria = "IP"
        elif "PODER PUBLICO" in classif_norm and "A4" not in classif_norm:
            categoria = "B3"

    return {
        "grupo_tensao": grupo_tensao,
        "subgrupo": subgrupo,
        "classificacao_uc": classif_line,
        "categoria": categoria,
        "source_pattern": classif_source or source_pattern,
    }


def _compose_kwh_source(bucket: str, detail: str) -> str:
    bucket_clean = str(bucket or "").strip()
    detail_clean = str(detail or "").strip()
    if not bucket_clean:
        return detail_clean
    if not detail_clean:
        return bucket_clean
    if detail_clean == bucket_clean:
        return bucket_clean
    return f"{bucket_clean}/{detail_clean}"


def _ref_to_ts(ref: str) -> pd.Timestamp:
    try:
        mm, yyyy = str(ref).split("/")
        return pd.Timestamp(int(yyyy), int(mm), 1)
    except Exception:
        return pd.NaT


def _normalize_month_rows_contiguous(
    rows: list[dict],
    value_keys: list[str],
    months: int = 13,
) -> list[dict]:
    if not rows:
        return []

    tmp: dict[str, dict] = {}
    for row in rows:
        ref = str(row.get("referencia", "")).strip()
        if not ref:
            continue
        ts = _ref_to_ts(ref)
        if pd.isna(ts):
            continue
        clean = {"referencia": ref}
        for key in value_keys:
            val = row.get(key)
            clean[key] = float(val) if val is not None else 0.0
        tmp[ref] = clean

    if not tmp:
        return []

    latest_ts = max(_ref_to_ts(r) for r in tmp.keys())
    out: list[dict] = []
    for i in range(months - 1, -1, -1):
        ts = latest_ts - pd.DateOffset(months=i)
        ref = f"{int(ts.month):02d}/{int(ts.year)}"
        base = {"referencia": ref}
        for key in value_keys:
            base[key] = 0.0
        if ref in tmp:
            for key in value_keys:
                base[key] = float(tmp[ref].get(key) or 0.0)
        out.append(base)
    return out


def _extract_header_block_lines(page_text: str) -> list[str]:
    lines = [ln.strip() for ln in normalize_whitespace(page_text).split("\n") if ln.strip()]
    markers = [
        "ITENS DE FATURA",
        "DESCRICAO DO FATURAMENTO",
        "MÊS/ANO",
        "MES/ANO",
        "MEDIDOR GRANDEZAS",
        "HISTORICO",
    ]
    out: list[str] = []
    for line in lines:
        norm_line = _normalize_ascii_upper(line)
        if any(m in norm_line for m in markers):
            break
        out.append(line)
    return out


def _extract_header_classificacao(page_text: str) -> str:
    header_lines = _extract_header_block_lines(page_text)
    if not header_lines:
        return ""
    for line in header_lines:
        norm_line = _normalize_ascii_upper(line)
        if re.search(r"\bA4\b.*\bHOROSAZONAL\b", norm_line):
            return _clean_classificacao_text(line)
        if re.search(r"\bB3\b", norm_line):
            return _clean_classificacao_text(line)
        if re.search(r"\bB4[AB]?\b", norm_line) or "ILUMINACAO PUBLICA" in norm_line:
            return _clean_classificacao_text(line)
    return ""


def _extract_itens_da_fatura_section(text: str) -> str:
    """
    Return normalized text limited to "Itens da Fatura" section.
    This prevents mixing values from "Valores Medidos".
    """
    if not text:
        return ""

    t_norm = _normalize_ascii_upper(text)
    m_start = re.search(r"\bITENS?\s+(?:DA|DE)\s+FATURA\b", t_norm)
    if not m_start:
        return ""

    start = m_start.start()
    end = len(t_norm)
    end_markers = [
        "VALORES MEDIDOS",
        "HISTORICO",
        "HISTORICO DO FATURAMENTO",
        "HISTORICO DE FATURAMENTO",
        "NOVO MODELO DE NOTA FISCAL",
        "MÊS/ANO",
        "MES/ANO",
        "INFORMACOES COMPLEMENTARES",
        "INFORMACOES IMPORTANTES",
        "RESERVADO AO FISCO",
    ]
    for marker in end_markers:
        pos = t_norm.find(marker, m_start.end())
        if pos != -1:
            end = min(end, pos)

    return t_norm[start:end]


def _extract_grandezas_contratadas_section(text: str) -> str:
    """
    Return normalized text limited to "Grandezas Contratadas" section.
    """
    if not text:
        return ""

    t_norm = _normalize_ascii_upper(text)
    m_start = re.search(r"\bGRANDEZA(?:S)?\s+CONTRATADA(?:S)?\b", t_norm)
    if not m_start:
        return ""

    start = m_start.start()
    end = len(t_norm)
    end_markers = [
        "ITENS DE FATURA",
        "ITENS DA FATURA",
        "HISTORICO",
        "VALORES MEDIDOS",
        "DETALHAMENTO DA CONTA",
        "INFORMACOES COMPLEMENTARES",
        "INFORMACOES IMPORTANTES",
        "RESERVADO AO FISCO",
    ]
    for marker in end_markers:
        pos = t_norm.find(marker, m_start.end())
        if pos != -1:
            end = min(end, pos)

    return t_norm[start:end]


def _build_fuzzy_label_regex(label: str) -> str:
    words = [re.escape(w) for w in label.upper().split() if w]
    if not words:
        return ""
    return r"\b" + r"\s+".join(words) + r"\b"


def _extract_item_quantity(section_text: str, labels: list[str]) -> Optional[float]:
    if not section_text:
        return None

    for label in labels:
        label_rx = _build_fuzzy_label_regex(label)
        if not label_rx:
            continue
        patterns = [
            label_rx + r"(?:\s*[-:]\s*|\s+)([0-9][0-9\.,]*)",
            label_rx + r"(?:\s+[A-Z/%()\-]+){0,3}\s+([0-9][0-9\.,]*)",
        ]
        for rx in patterns:
            m = re.search(rx, section_text, flags=re.IGNORECASE)
            if m:
                return parse_ptbr_number(m.group(1))
    return None


def _extract_itens_price_value_items(text: str) -> list[dict]:
    """
    Parse item-level tuples from "Itens da Fatura":
      item label + Quantidade + Preco Unitario c/ tributos + Valor.
    """
    section = _extract_itens_da_fatura_section(text)
    if not section:
        return []

    num_pat = r"-?[0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|-?[0-9]+(?:,[0-9]+)?"
    item_labels = [
        "DEMANDA DE ULTRAPASSAGEM",
        "DIFERENCA DA DEMANDA CONTRATADA",
        "DIFERENCA DA DEMANDA CONTRATAD",
        "DEMANDA NAO UTILIZADA FORA PONTA",
        "DEMANDA NAO UTILIZADA",
        "DEMANDA HORARIA FORA PONTA",
        "DEMANDA FORA PONTA",
        "CONSUMO HORARIA FORA PONTA TUSD",
        "CONSUMO HORARIA FORA PONTA TE",
        "CONSUMO FORA PONTA TUSD",
        "CONSUMO FORA PONTA TE",
        "CONSUMO PONTA TUSD",
        "CONSUMO PONTA TE",
        "CONSUMO IP TE",
        "CONSUMO TUSD",
        "CONSUMO TE",
        "ENERGIA UNICO",
        "DEMANDA",
    ]

    candidates: list[dict] = []
    for label in item_labels:
        label_rx = _build_fuzzy_label_regex(label)
        if not label_rx:
            continue
        for m in re.finditer(label_rx, section, flags=re.IGNORECASE):
            tail = section[m.end(): m.end() + 220]
            nums = re.findall(num_pat, tail)
            if len(nums) < 3:
                continue

            quantidade = parse_ptbr_number(nums[0])
            preco_unit = parse_ptbr_number(nums[1])
            valor = parse_ptbr_number(nums[2])
            if quantidade is None or preco_unit is None or valor is None:
                continue

            candidates.append(
                {
                    "start": m.start(),
                    "label_len": len(label),
                    "item": label,
                    "quantidade": float(quantidade),
                    "preco_unitario_com_tributos": float(preco_unit),
                    "valor": float(valor),
                }
            )

    if not candidates:
        return []

    candidates.sort(key=lambda x: (x["start"], -x["label_len"]))
    deduped: list[dict] = []
    for cand in candidates:
        if deduped and abs(cand["start"] - deduped[-1]["start"]) <= 2:
            continue
        deduped.append(cand)

    items: list[dict] = []
    for row in deduped:
        items.append(
            {
                "item": row["item"],
                "quantidade": row["quantidade"],
                "preco_unitario_com_tributos": row["preco_unitario_com_tributos"],
                "valor": row["valor"],
            }
        )
    return items


def _dedupe_item_rows(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple] = set()
    for row in items or []:
        key = (
            str(row.get("item", "")).strip().upper(),
            round(float(row.get("quantidade") or 0.0), 6),
            round(float(row.get("preco_unitario_com_tributos") or 0.0), 8),
            round(float(row.get("valor") or 0.0), 6),
            str(row.get("posto", "")).strip().upper(),
            str(row.get("componente", "")).strip().upper(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _extract_energy_items_from_stream(stream_text: str, categoria_hint: str = "") -> list[dict]:
    if not stream_text:
        return []

    t = _normalize_ascii_upper(stream_text)
    num = r"([0-9][0-9\.,]*)"
    items: list[dict] = []

    # A4: energy split by posto + TE/TUSD.
    rx_a4 = re.compile(
        r"\bENERGIA\s+(?:ATV|ATIVA)\s+(?:FORN|FORNECIDA)\s+"
        r"(F\s*PONTA|FORA\s+PONTA|PONTA)\s+"
        r"(TE|TUSD)\s+K\s*W\s*H\s*"
        + num
        + r"\s+"
        + num
        + r"\s+"
        + num,
        flags=re.IGNORECASE,
    )
    for m in rx_a4.finditer(t):
        posto_raw = _normalize_ascii_upper(m.group(1))
        posto = "FHP" if ("FORA" in posto_raw or posto_raw.startswith("F")) else "HP"
        comp = "TUSD" if "TUSD" in _normalize_ascii_upper(m.group(2)) else "TE"
        quantidade = parse_ptbr_number(m.group(3))
        preco_unit = parse_ptbr_number(m.group(4))
        valor = parse_ptbr_number(m.group(5))
        if quantidade is None or preco_unit is None or valor is None:
            continue
        items.append(
            {
                "item": f"ENERGIA ATIVA FORNECIDA {posto} {comp}",
                "posto": posto,
                "componente": comp,
                "quantidade": float(quantidade),
                "preco_unitario_com_tributos": float(preco_unit),
                "valor": float(valor),
                "fonte": "ITENS_DE_FATURA",
            }
        )

    # B3/IP: TE/TUSD rows without posto split.
    rx_b = re.compile(
        r"\bENERGIA\s+(?:ATV|ATIVA)\s+(?:FORN|FORNECIDA)\s+"
        r"(TE|TUSD)\s+K\s*W\s*H\s*"
        + num
        + r"\s+"
        + num
        + r"\s+"
        + num,
        flags=re.IGNORECASE,
    )
    for m in rx_b.finditer(t):
        comp_raw = _normalize_ascii_upper(m.group(1))
        comp = "TUSD" if "TUSD" in comp_raw else "TE"
        quantidade = parse_ptbr_number(m.group(2))
        preco_unit = parse_ptbr_number(m.group(3))
        valor = parse_ptbr_number(m.group(4))
        if quantidade is None or preco_unit is None or valor is None:
            continue
        items.append(
            {
                "item": f"ENERGIA ATIVA FORNECIDA {comp}",
                "posto": "UNICO",
                "componente": comp,
                "quantidade": float(quantidade),
                "preco_unitario_com_tributos": float(preco_unit),
                "valor": float(valor),
                "fonte": "ITENS_DE_FATURA",
            }
        )

    # Keep only rows aligned with the target category when hint is explicit.
    cat = str(categoria_hint or "").upper()
    if cat in {"B3", "IP"}:
        items = [r for r in items if str(r.get("posto", "")).upper() == "UNICO"]
    if cat == "A4":
        items = [r for r in items if str(r.get("posto", "")).upper() in {"HP", "FHP"}]

    return _dedupe_item_rows(items)


def _summarize_itens_price_value(items: list[dict]) -> dict[str, Optional[float]]:
    if not items:
        return {
            "itens_fatura_total_valor_rs": None,
            "itens_fatura_energia_valor_rs": None,
            "itens_fatura_energia_kwh": None,
            "itens_fatura_preco_medio_rs_kwh": None,
            "itens_fatura_preco_all_in_fhp_rs_kwh": None,
            "itens_fatura_preco_all_in_hp_rs_kwh": None,
            "itens_fatura_preco_all_in_blended_rs_kwh": None,
        }

    total_valor = 0.0
    energia_valor = 0.0
    energia_kwh = 0.0
    sums: dict[str, float] = {
        "fhp_te_valor": 0.0,
        "fhp_tusd_valor": 0.0,
        "fhp_te_kwh": 0.0,
        "fhp_tusd_kwh": 0.0,
        "hp_te_valor": 0.0,
        "hp_tusd_valor": 0.0,
        "hp_te_kwh": 0.0,
        "hp_tusd_kwh": 0.0,
        "unico_te_valor": 0.0,
        "unico_tusd_valor": 0.0,
        "unico_te_kwh": 0.0,
        "unico_tusd_kwh": 0.0,
    }

    for item in items:
        valor = float(item.get("valor") or 0.0)
        quantidade = float(item.get("quantidade") or 0.0)
        nome = str(item.get("item") or "").upper()
        posto = str(item.get("posto") or "").upper()
        comp = str(item.get("componente") or "").upper()

        total_valor += valor
        if "CONSUMO" in nome or "ENERGIA" in nome:
            energia_valor += valor
            energia_kwh += quantidade
            if posto == "FHP":
                if comp == "TE":
                    sums["fhp_te_valor"] += valor
                    sums["fhp_te_kwh"] += quantidade
                if comp == "TUSD":
                    sums["fhp_tusd_valor"] += valor
                    sums["fhp_tusd_kwh"] += quantidade
            elif posto == "HP":
                if comp == "TE":
                    sums["hp_te_valor"] += valor
                    sums["hp_te_kwh"] += quantidade
                if comp == "TUSD":
                    sums["hp_tusd_valor"] += valor
                    sums["hp_tusd_kwh"] += quantidade
            elif posto in {"UNICO", ""}:
                if comp == "TE":
                    sums["unico_te_valor"] += valor
                    sums["unico_te_kwh"] += quantidade
                if comp == "TUSD":
                    sums["unico_tusd_valor"] += valor
                    sums["unico_tusd_kwh"] += quantidade

    fhp_base_kwh = max(sums["fhp_te_kwh"], sums["fhp_tusd_kwh"])
    hp_base_kwh = max(sums["hp_te_kwh"], sums["hp_tusd_kwh"])
    unico_base_kwh = max(sums["unico_te_kwh"], sums["unico_tusd_kwh"])

    energia_kwh_unique = energia_kwh
    if fhp_base_kwh > 0 or hp_base_kwh > 0:
        energia_kwh_unique = fhp_base_kwh + hp_base_kwh
    elif unico_base_kwh > 0:
        energia_kwh_unique = unico_base_kwh

    preco_medio = None
    if energia_kwh_unique > 0:
        preco_medio = energia_valor / energia_kwh_unique

    preco_all_in_fhp = None
    if fhp_base_kwh > 0:
        preco_all_in_fhp = (sums["fhp_te_valor"] + sums["fhp_tusd_valor"]) / fhp_base_kwh

    preco_all_in_hp = None
    if hp_base_kwh > 0:
        preco_all_in_hp = (sums["hp_te_valor"] + sums["hp_tusd_valor"]) / hp_base_kwh

    preco_all_in_blended = None
    if unico_base_kwh > 0:
        preco_all_in_blended = (sums["unico_te_valor"] + sums["unico_tusd_valor"]) / unico_base_kwh
    elif energia_kwh_unique > 0:
        preco_all_in_blended = energia_valor / energia_kwh_unique

    return {
        "itens_fatura_total_valor_rs": total_valor if total_valor > 0 else None,
        "itens_fatura_energia_valor_rs": energia_valor if energia_valor > 0 else None,
        "itens_fatura_energia_kwh": energia_kwh_unique if energia_kwh_unique > 0 else None,
        "itens_fatura_preco_medio_rs_kwh": preco_medio,
        "itens_fatura_preco_all_in_fhp_rs_kwh": preco_all_in_fhp,
        "itens_fatura_preco_all_in_hp_rs_kwh": preco_all_in_hp,
        "itens_fatura_preco_all_in_blended_rs_kwh": preco_all_in_blended,
    }


def _extract_a4_itens_metrics(text: str) -> dict[str, Optional[float]]:
    """
    Extract A4 monthly values from Itens da Fatura (Quantidade column semantics).
    """
    section = _extract_itens_da_fatura_section(text)
    out: dict[str, Optional[float]] = {
        "demanda_hp_kw": None,
        "demanda_fhp_kw": None,
        "demanda_ultrapassagem_kw": None,
        "demanda_nao_utilizada_kw": None,
        "consumo_hp_kwh": None,
        "consumo_fhp_kwh": None,
    }
    if not section:
        return out

    m_dem_hp = re.search(
        r"\bDEMANDA\b(?!\s+(?:DE|FORA|PONTA|HORARIA|NAO|CONTRATAD))(?:\s*[-:]\s*|\s+)([0-9][0-9\.,]*)",
        section,
        flags=re.IGNORECASE,
    )
    if not m_dem_hp:
        m_dem_hp = re.search(
            r"\bDEMANDA\b(?!\s+(?:DE|FORA|PONTA|HORARIA|NAO|CONTRATAD))(?:\s+[A-Z/%()\-]+){0,1}\s+([0-9][0-9\.,]*)",
            section,
            flags=re.IGNORECASE,
        )
    out["demanda_hp_kw"] = parse_ptbr_number(m_dem_hp.group(1)) if m_dem_hp else None
    out["demanda_fhp_kw"] = _extract_item_quantity(section, [
        "DEMANDA FORA PONTA",
        "DEMANDA HORARIA FORA PONTA",
    ])
    out["demanda_ultrapassagem_kw"] = _extract_item_quantity(section, [
        "DEMANDA DE ULTRAPASSAGEM",
        "DIFERENCA DA DEMANDA CONTRATADA",
        "DIFERENCA DA DEMANDA CONTRATAD",
    ])
    out["demanda_nao_utilizada_kw"] = _extract_item_quantity(section, [
        "DEMANDA NAO UTILIZADA",
        "DEMANDA NAO UTILIZADA FORA PONTA",
    ])

    out["consumo_hp_kwh"] = _extract_item_quantity(section, [
        "CONSUMO PONTA TE",
        "CONSUMO PONTA",
    ])
    out["consumo_fhp_kwh"] = _extract_item_quantity(section, [
        "CONSUMO FORA PONTA TE",
        "CONSUMO HORARIA FORA PONTA TE",
        "CONSUMO FORA PONTA",
        "CONSUMO UNICO TE",
        "CONSUMO UNICO",
    ])

    if out["demanda_fhp_kw"] is None and out["demanda_hp_kw"] is not None:
        out["demanda_fhp_kw"] = out["demanda_hp_kw"]

    return out


def parse_demanda_contratada(text: str) -> float:
    """
    Extract contracted demand (kW) for A4.
    Priority:
      1) "Grandezas Contratadas" -> "DEMANDA FORA PONTA - KW <valor>"
      2) Explicit line: "DEMANDA FORA PONTA - KW <valor>"
      3) ITENS DE FATURA demand row quantity ("Demanda Ativa kW" / "Demanda kW")
    """
    if not text:
        return 0.0

    # Campos/CELESC rule: prioritize "Grandezas Contratadas" explicit field.
    grandezas = _extract_grandezas_contratadas_section(text)
    if grandezas:
        grandezas_patterns = [
            r"\bDEMANDA\s+FORA\s+PONTA\s*-\s*KW\b(?:\s*[:\-])?\s*([0-9][0-9\.,]*)\b",
            r"\bDEMANDA\s+FORA\s+PONTA\s+KW\b(?:\s*[:\-])?\s*([0-9][0-9\.,]*)\b",
        ]
        for pat in grandezas_patterns:
            m0 = re.search(pat, grandezas, flags=re.IGNORECASE)
            if not m0:
                continue
            val0 = parse_ptbr_number(m0.group(1))
            if val0 is not None:
                return float(val0)

    # Explicit contracted demand line in header/footer.
    m = re.search(r"DEMANDA\s+FORA\s+PONTA\s*-\s*KW\s*([0-9\.,]+)", text, flags=re.IGNORECASE)
    if m:
        return br_to_float(m.group(1))

    t = _normalize_ascii_upper(text)
    demand_patterns = [
        r"\bDEMANDA\s+ATIVA\s+KW\b\s+([0-9][0-9\.,]*)\b",
        r"\bDEMANDA\s+FATURADA\s*-\s*KW\b[\s:]+([0-9][0-9\.,]*)\b",
        r"\bDEMANDA\s+KW\b\s+([0-9][0-9\.,]*)\b",
    ]
    for pat in demand_patterns:
        m2 = re.search(pat, t, flags=re.IGNORECASE)
        if m2:
            val = parse_ptbr_number(m2.group(1))
            if val is not None and val > 0:
                return float(val)

    vals = _extract_a4_itens_metrics(text)
    demanda = vals.get("demanda_hp_kw")
    if demanda is not None and demanda > 0:
        return float(demanda)

    demanda_cascade, _ = _extract_demand_cascade(text)
    if demanda_cascade is not None and demanda_cascade > 0:
        return float(demanda_cascade)

    return 0.0


def parse_a4_historico(text: str) -> list[dict]:
    """
    Returns 13 rows (one per month) with:
      demanda_hp_kw, demanda_fhp_kw, consumo_hp_kwh, consumo_fhp_kwh

    Strategy:
      A) Row-based: each month line contains 4 values
      B) Fallback: parse month list + 4 series of 13 values
         (HP/FHP demand, HP/FHP consumo)
    """
    if not text:
        return []

    # Prefer full digit runs so values like "1513,01" are not split into "151" + "3,01".
    num_pat = re.compile(r"\d+(?:\.\d{3})*(?:,\d+)?")
    month_pat = re.compile(
        r"\b((?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)[/\-]?\d{2,4}|(?:0?[1-9]|1[0-2])[/\-]\d{2,4})\b",
        re.I,
    )

    def to_float(s: str) -> float:
        s = str(s).strip().replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0

    # A) row-based parse.
    rows: list[dict] = []
    month_hits = list(month_pat.finditer(text.upper()))
    for i, m in enumerate(month_hits):
        ref = normalize_reference_token(m.group(1))
        if not ref:
            continue
        next_start = month_hits[i + 1].start() if i + 1 < len(month_hits) else len(text)
        seg = text[m.end():next_start]
        vals = [to_float(n) for n in num_pat.findall(seg)]
        if len(vals) >= 4:
            rows.append(
                {
                    "referencia": ref,
                    "demanda_hp_kw": vals[0],
                    "demanda_fhp_kw": vals[1],
                    "consumo_hp_kwh": vals[2],
                    "consumo_fhp_kwh": vals[3],
                }
            )

    row_based = _normalize_month_rows_contiguous(
        rows=rows,
        value_keys=["demanda_hp_kw", "demanda_fhp_kw", "consumo_hp_kwh", "consumo_fhp_kwh"],
        months=13,
    )
    if row_based:
        return row_based

    # B) fallback series parse.
    month_tokens: list[str] = []
    for m in month_pat.finditer(text.upper()):
        ref = normalize_reference_token(m.group(1))
        if ref:
            month_tokens.append(ref)

    seen: set[str] = set()
    month_refs: list[str] = []
    for r in month_tokens:
        if r not in seen:
            seen.add(r)
            month_refs.append(r)
        if len(month_refs) >= 13:
            break

    if len(month_refs) < 1:
        return []
    month_refs = month_refs[:13]

    t_norm = _normalize_ascii_upper(text)
    hist_pos = t_norm.find("HISTORICO")
    section = t_norm[hist_pos:] if hist_pos >= 0 else t_norm

    series_specs = [
        ("demanda_hp_kw", re.compile(r"\bDEMANDA\s+(?:HP|PONTA)\b")),
        ("demanda_fhp_kw", re.compile(r"\bDEMANDA\s+(?:FHP|FORA\s+PONTA)\b")),
        ("consumo_hp_kwh", re.compile(r"\bCONSUMO\s+(?:HP|PONTA)\b")),
        ("consumo_fhp_kwh", re.compile(r"\bCONSUMO\s+(?:FHP|FORA\s+PONTA)\b")),
    ]

    starts: list[tuple[str, int, int]] = []
    for key, pat in series_specs:
        m = pat.search(section)
        if not m:
            starts = []
            break
        starts.append((key, m.start(), m.end()))

    series_values: dict[str, list[float]] = {}
    if len(starts) == 4:
        starts = sorted(starts, key=lambda x: x[1])
        for i, (key, _st, en) in enumerate(starts):
            next_st = starts[i + 1][1] if i + 1 < len(starts) else len(section)
            seg = section[en:next_st]
            vals = [to_float(n) for n in num_pat.findall(seg)]
            if len(vals) < 13:
                series_values = {}
                break
            series_values[key] = vals[:13]

    if len(series_values) != 4:
        all_nums = [to_float(n) for n in num_pat.findall(section)]
        if len(all_nums) < 52:
            return []
        block = all_nums[-52:]
        series_values = {
            "demanda_hp_kw": block[0:13],
            "demanda_fhp_kw": block[13:26],
            "consumo_hp_kwh": block[26:39],
            "consumo_fhp_kwh": block[39:52],
        }

    out_rows: list[dict] = []
    for i, ref in enumerate(month_refs):
        out_rows.append(
            {
                "referencia": ref,
                "demanda_hp_kw": series_values["demanda_hp_kw"][i],
                "demanda_fhp_kw": series_values["demanda_fhp_kw"][i],
                "consumo_hp_kwh": series_values["consumo_hp_kwh"][i],
                "consumo_fhp_kwh": series_values["consumo_fhp_kwh"][i],
            }
        )

    return _normalize_month_rows_contiguous(
        rows=out_rows,
        value_keys=["demanda_hp_kw", "demanda_fhp_kw", "consumo_hp_kwh", "consumo_fhp_kwh"],
        months=13,
    )


def parse_b3_ip_historico(text: str) -> list[dict]:
    """
    Returns up to 13 monthly rows for B3/IP historical consumo:
      [{"referencia":"MM/YYYY","consumo_kwh":...}, ...]
    Source must be HISTORICO table rows.
    """
    if not text:
        return []

    lines = [ln.strip() for ln in normalize_whitespace(text).split("\n") if ln.strip()]
    rows: list[dict] = []

    rx_slash = re.compile(
        r"^\s*(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)/(\d{2,4})\s+([0-9][0-9\.,]*)\s*(?:[0-9]{1,3})?\s*$",
        flags=re.IGNORECASE,
    )
    rx_compact = re.compile(
        r"^\s*(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)(\d{2,4})\s+([0-9][0-9\.,]*)\s+[0-9]{1,3}\s+(?:LID|MIN)\s*$",
        flags=re.IGNORECASE,
    )
    rx_numeric = re.compile(
        r"^\s*((?:0?[1-9]|1[0-2])[/\-]\d{2,4})\s+([0-9][0-9\.,]*)\s*(?:[0-9]{1,3})?\s*$",
        flags=re.IGNORECASE,
    )

    for line in lines:
        m = rx_slash.match(line) or rx_compact.match(line)
        if m:
            ref = _month_ref(m.group(1), m.group(2))
            consumo = _parse_flexible_number(m.group(3))
            if not ref or consumo is None:
                continue
            rows.append({"referencia": ref, "consumo_kwh": float(consumo)})
            continue

        m_num = rx_numeric.match(line)
        if not m_num:
            continue
        ref = normalize_reference_token(m_num.group(1))
        consumo = _parse_flexible_number(m_num.group(2))
        if not ref or consumo is None:
            continue
        rows.append({"referencia": ref, "consumo_kwh": float(consumo)})

    row_based = _normalize_month_rows_contiguous(
        rows=rows,
        value_keys=["consumo_kwh"],
        months=13,
    )
    if row_based:
        return row_based

    # Fallback for layouts where month labels and kWh values are split across two lines, e.g.:
    #   "4240 2600 3160 ... 0 0"
    #   "SET/25 AGO/25 JUL/25 ... SET/24"
    month_token_rx = re.compile(
        r"\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s*/\s*(\d{2,4})\b",
        flags=re.IGNORECASE,
    )
    # Capture full numeric tokens (e.g. "4240", "12.00", "1.234,56") without splitting digits.
    num_token_rx = re.compile(r"-?\d[\d\.,]*", flags=re.IGNORECASE)

    for idx, line in enumerate(lines):
        mm = month_token_rx.findall(line.upper())
        if len(mm) < 6:
            continue

        refs: list[str] = []
        for mon3, year in mm[:13]:
            ref = _month_ref(mon3, year)
            if ref:
                refs.append(ref)
        if not refs:
            continue

        for off in (-1, -2, 1):
            j = idx + off
            if j < 0 or j >= len(lines):
                continue
            vals_raw = num_token_rx.findall(lines[j])
            vals: list[float] = []
            for tok in vals_raw:
                v = _parse_flexible_number(tok)
                if v is not None:
                    vals.append(float(v))
            if len(vals) < len(refs):
                continue

            paired = [
                {"referencia": refs[i], "consumo_kwh": float(vals[i])}
                for i in range(min(13, len(refs)))
            ]
            normalized = _normalize_month_rows_contiguous(
                rows=paired,
                value_keys=["consumo_kwh"],
                months=13,
            )
            if normalized:
                return normalized

    return []


def extract_demanda_values(text: str) -> tuple[Optional[float], Optional[float]]:
    """
    Robust fallback parser for demand fields in A4 layouts where labels/columns shift.
    Returns: (demanda_item, dif_demanda)
    """
    t_norm = _normalize_ascii_upper(text)

    m_dem = re.search(r"\bDEMANDA\b(?!\s*(?:FORA|PONTA|DE))\s*([0-9][0-9\.,]*)", t_norm)
    m_dif = re.search(
        r"\b(?:DIFERENCA\s+DA\s+DEMANDA\s+CONTRATAD\w*|DEMANDA\s+DE\s+ULTRAPASSAGEM)\b\s*([0-9][0-9\.,]*)",
        t_norm,
    )

    dem = parse_ptbr_number(m_dem.group(1)) if m_dem else None
    dif = parse_ptbr_number(m_dif.group(1)) if m_dif else None
    return dem, dif


def extract_page_default_ref(page_text: str) -> str:
    """
    Try to get the month reference for the whole page.
    Priority:
      1) 'Referencia: MM/AAAA'
      2) 'Fatura: YYYYMM-...'
      3) 'Data Faturamento: DD/MM/AAAA'
    """
    t = normalize_whitespace(page_text or "")
    ref, _ = _extract_reference_cascade(t)
    return ref


def categorize(grupo_tensao: str, subgrupo: str, classif_line: str) -> str:
    sub = (subgrupo or "").upper().strip()
    grp = (grupo_tensao or "").upper().strip()
    cls_raw = (classif_line or "").upper()
    cls = unicodedata.normalize("NFKD", cls_raw).encode("ASCII", "ignore").decode("ASCII")

    # Priority 1: explicit class in the classification text.
    # This avoids false IP mapping when subgrupo metadata is noisy/inconsistent.
    if re.search(r"\bA4\b", cls):
        return "A4"
    if re.search(r"\bB3\b", cls):
        return "B3"
    if re.search(r"\bB4[AB]?\b", cls) or "ILUMINACAO PUBLICA" in cls:
        return "IP"

    # Priority 2: fallback to group/subgroup.
    if grp == "A" and sub == "A4":
        return "A4"
    if grp == "B" and sub == "B3":
        return "B3"
    if grp == "B" and sub in {"B4A", "B4B"}:
        return "IP"

    return "OUTROS"


def split_into_uc_blocks(page_text: str) -> List[str]:
    """
    Split a page into segments starting at each 'UC:' occurrence.
    """
    text = normalize_whitespace(page_text)
    starts = _find_uc_block_starts(text)
    if not starts:
        return []
    blocks: List[str] = []
    for i, st in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        blocks.append(text[st:end].strip())
    return blocks


def extract_tipo_fornecimento(classif_line: str) -> str:
    s = (classif_line or "").upper()
    s_ascii = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")
    if ("TRIFASICO" in s_ascii) or ("TRIFASIC" in s_ascii):
        return "TRIFÁSICO"
    if ("BIFASICO" in s_ascii) or ("BIFASIC" in s_ascii):
        return "BIFÁSICO"
    if ("MONOFASICO" in s_ascii) or ("MONOFASIC" in s_ascii):
        return "MONOFÁSICO"
    return ""


def extract_from_uc_block(
    block_text: str,
    page_index: int,
    pdf_source: str,
    default_ref: str = "",
) -> Optional[UCMonthRecord]:
    t = normalize_whitespace(block_text)
    t_ascii = _normalize_ascii_upper(t)

    uc, _ = _extract_uc_cascade(t, target_len=10)
    if not uc:
        return None

    # Reference
    referencia, _ = _extract_reference_cascade(t)
    if not referencia:
        referencia = normalize_reference_token(default_ref)
    if not referencia:
        referencia = extract_page_default_ref(t)

    categoria_info = _extract_categoria_bundle(t)
    grupo_tensao = categoria_info["grupo_tensao"]
    subgrupo = categoria_info["subgrupo"]
    classif_line = categoria_info["classificacao_uc"]
    if not classif_line:
        m_cls_ascii = re.search(
            r"\bCLASSIFICACAO\s*/\s*MODALIDADE\s*TARIFARIA\s*/\s*TIPO\s*DE\s*FORNECIMENTO:\s*(.+?)(?:\bMUNICIPIO:|\bORIGEM:|$)",
            t_ascii,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if m_cls_ascii:
            classif_line = _clean_classificacao_text(m_cls_ascii.group(1).strip())
    tipo_fornecimento = extract_tipo_fornecimento(classif_line)
    if not tipo_fornecimento:
        tipo_fornecimento = extract_tipo_fornecimento(t)

    m_or = R.RE_ORIGEM.search(t)
    origem = m_or.group(1).strip() if m_or else ""

    # Nome / Endereco
    nome = ""
    endereco = ""

    m_nome = R.RE_NOME.search(t) or R.RE_NOME_FALLBACK.search(t)
    if m_nome:
        nome = m_nome.group(1).split("\n")[0].strip()
        nome = nome.replace("Endereço:", "").replace("Endereco:", "").strip()

    m_end = R.RE_END.search(t) or R.RE_END_FALLBACK.search(t)
    if m_end:
        endereco = m_end.group(1).split("\n")[0].strip()
        endereco = endereco.replace("Etapa:", "").strip()

    categoria = categoria_info["categoria"] or categorize(grupo_tensao, subgrupo, classif_line)

    rec = UCMonthRecord(
        uc=uc,
        referencia=referencia,
        grupo_tensao=grupo_tensao,
        subgrupo=subgrupo,
        categoria=categoria,
        tipo_fornecimento=tipo_fornecimento,
        origem=origem,
        nome=nome,
        endereco=endereco,
        classificacao_uc=classif_line,
        pdf_source=pdf_source,
        page_first_seen=page_index + 1,  # 1-based for humans
        audit_header_page=page_index + 1,
    )

    # Invoice amount appears inline as "Valor: R$...".
    m_total = R.RE_VALOR_BLOCO_RS.search(t)
    if not m_total:
        m_total = R.RE_TOTAL_A_PAGAR_RS.search(t)
    if not m_total:
        m_total = R.RE_VALOR_TOTAL.search(t)
    if not m_total:
        m_total = R.RE_TOTAL_FATURA.search(t)
    if m_total:
        rec.total_fatura_rs = parse_ptbr_number(m_total.group(1))

    # Item-level prices and values from "Itens da Fatura".
    itens = _extract_itens_price_value_items(t)
    itens_energy = _extract_energy_items_from_stream(t, categoria_hint=categoria)
    if itens_energy:
        itens = _dedupe_item_rows((itens or []) + itens_energy)
    if itens:
        rec.itens_fatura_json = json.dumps(itens, ensure_ascii=False)
        resumo = _summarize_itens_price_value(itens)
        rec.itens_fatura_total_valor_rs = resumo["itens_fatura_total_valor_rs"]
        rec.itens_fatura_energia_valor_rs = resumo["itens_fatura_energia_valor_rs"]
        rec.itens_fatura_energia_kwh = resumo["itens_fatura_energia_kwh"]
        rec.itens_fatura_preco_medio_rs_kwh = resumo["itens_fatura_preco_medio_rs_kwh"]
        rec.itens_fatura_preco_all_in_fhp_rs_kwh = resumo["itens_fatura_preco_all_in_fhp_rs_kwh"]
        rec.itens_fatura_preco_all_in_hp_rs_kwh = resumo["itens_fatura_preco_all_in_hp_rs_kwh"]
        rec.itens_fatura_preco_all_in_blended_rs_kwh = resumo["itens_fatura_preco_all_in_blended_rs_kwh"]
        rec.audit_itens_page = page_index + 1

    # Energy extraction rules
    if categoria == "A4":
        itens_vals = _extract_a4_itens_metrics(t)
        hist_rows = parse_a4_historico(t)
        hist_map = {r.get("referencia"): r for r in (hist_rows or []) if r.get("referencia")}

        if referencia in hist_map:
            h = hist_map[referencia]
            rec.demanda_hp_kw = h.get("demanda_hp_kw")
            rec.demanda_fhp_kw = h.get("demanda_fhp_kw")
            rec.consumo_hp_kwh = h.get("consumo_hp_kwh")
            rec.consumo_fhp_kwh = h.get("consumo_fhp_kwh")
            rec.audit_historico_page = page_index + 1
        else:
            rec.demanda_hp_kw = itens_vals.get("demanda_hp_kw")
            rec.demanda_fhp_kw = itens_vals.get("demanda_fhp_kw")
            rec.consumo_hp_kwh = itens_vals.get("consumo_hp_kwh")
            rec.consumo_fhp_kwh = itens_vals.get("consumo_fhp_kwh")
            if hist_rows:
                rec.audit_historico_page = page_index + 1

        rec.demanda_item = rec.demanda_hp_kw
        rec.dif_demanda = itens_vals.get("demanda_ultrapassagem_kw")
        rec.demanda_contratada_kw = parse_demanda_contratada(t)
        if rec.demanda_item is None:
            demanda_item, _ = _extract_demand_cascade(t)
            rec.demanda_item = demanda_item
        if rec.demanda_contratada_kw <= 0:
            demanda_cascade, _ = _extract_demand_cascade(t)
            rec.demanda_contratada_kw = float(demanda_cascade or 0.0)

        rec.kwh_a4_p_te = rec.consumo_hp_kwh
        rec.kwh_a4_fp_te = rec.consumo_fhp_kwh
        rec.kwh_total_te = (rec.consumo_hp_kwh or 0.0) + (rec.consumo_fhp_kwh or 0.0)

        return rec

    # B3/IP = prioritize ITENS DA FATURA "Consumo TE" quantidade; then fallback chain.
    if categoria in {"B3", "IP"}:
        hist_rows_b = parse_b3_ip_historico(t)
        if hist_rows_b:
            rec.audit_historico_page = page_index + 1
        hist_map_b = {
            str(r.get("referencia", "")).strip(): float(r.get("consumo_kwh") or 0.0)
            for r in (hist_rows_b or [])
            if r.get("referencia")
        }

        section = _extract_itens_da_fatura_section(t)
        te_qty: Optional[float] = None
        te_source = ""

        # 1) Source-of-truth for CELESC and similar layouts: ITENS DA FATURA quantidade do Consumo TE.
        if section:
            te_qty, te_source = _extract_kwh_cascade(t, section_text=section)
            if te_source and not te_source.startswith("ITEM_"):
                te_qty = None
                te_source = ""

            if te_qty is None:
                te_qty = _extract_item_quantity(
                    section,
                    ["CONSUMO TE", "CONSUMO IP TE", "CONSUMO UNICO TE", "ENERGIA UNICO TE"],
                )
                if te_qty is not None:
                    te_source = "ITEM_QUANTITY_FALLBACK"

        if te_qty is not None and te_qty >= 0:
            rec.kwh_b3_ip = float(te_qty)
            rec.kwh_total_te = float(te_qty)
            rec.audit_kwh_source = _compose_kwh_source("ITENS_CONSUMO_TE", te_source)
        else:
            # 2) Explicit TE text-line patterns.
            kwh_val, kwh_source = _extract_kwh_cascade(t)
            text_sources = {
                "ITEM_CONSUMO_IP_TE_QTD",
                "ITEM_CONSUMO_TE_QTD",
                "ITEM_ENERGIA_UNICO_QTD",
                "CONS_IP_TE",
                "CONS_IP_GENERIC",
                "CONS_TE",
                "ENERGIA_TE",
                "ENERGIA_ATIVA",
                "ENERGIA_ELETRICA",
                "CONSUMO_KWH",
            }
            generic_sources = {
                "ENERGIA_UNICO_APURADO",
                "KWH_GENERIC",
                "KWH_BROKEN",
            }

            if kwh_val is not None and kwh_source in text_sources:
                rec.kwh_b3_ip = float(kwh_val)
                rec.kwh_total_te = rec.kwh_b3_ip
                rec.audit_kwh_source = _compose_kwh_source("TEXTO_CONSUMO_TE", kwh_source)
            elif rec.referencia in hist_map_b:
                # 3) Historico table month -> kWh.
                rec.kwh_b3_ip = float(hist_map_b.get(rec.referencia, 0.0))
                rec.kwh_total_te = rec.kwh_b3_ip
                rec.audit_kwh_source = "HISTORICO_CONSUMO_KWH"

            # 4) Generic fallback chain.
            if rec.kwh_total_te is None and kwh_val is not None and kwh_source in generic_sources:
                rec.kwh_b3_ip = float(kwh_val)
                rec.kwh_total_te = rec.kwh_b3_ip
                rec.audit_kwh_source = _compose_kwh_source("GENERIC_KWH", kwh_source)

        demanda_val, _ = _extract_demand_cascade(t)
        if demanda_val is not None:
            rec.demanda_item = float(demanda_val)
        m_dif = R.RE_DIF_DEMANDA.search(t)
        if m_dif:
            rec.dif_demanda = parse_ptbr_number(m_dif.group(1))

        return rec

    # OUTROS: still return record (no kWh)
    return rec


def expand_a4_record_from_block(
    block_text: str,
    page_index: int,
    pdf_source: str,
    base_rec: UCMonthRecord,
    default_ref: str = "",
) -> List[UCMonthRecord]:
    """
    Expand a single A4 record into monthly historico rows when present.
    Keeps backward compatibility by also filling legacy fields.
    """
    if (base_rec.categoria or "").upper() != "A4":
        return [base_rec]

    raw_block = block_text or ""
    if "HISTORICO" not in _normalize_ascii_upper(raw_block):
        return [base_rec]
    t = normalize_whitespace(raw_block)
    historico_rows = parse_a4_historico(raw_block)
    if not historico_rows:
        return [base_rec]

    demanda_contratada = parse_demanda_contratada(t)
    expanded: List[UCMonthRecord] = []
    base_ref = str(base_rec.referencia or "").strip()

    for r in historico_rows:
        rec = replace(base_rec)
        rec.referencia = r.get("referencia", rec.referencia or default_ref)

        # Keep invoice/item totals only on the invoice reference month to avoid duplication.
        if str(rec.referencia or "").strip() != base_ref:
            rec.total_fatura_rs = None
            rec.itens_fatura_json = ""
            rec.itens_fatura_total_valor_rs = None
            rec.itens_fatura_energia_valor_rs = None
            rec.itens_fatura_energia_kwh = None
            rec.itens_fatura_preco_medio_rs_kwh = None
            rec.itens_fatura_preco_all_in_fhp_rs_kwh = None
            rec.itens_fatura_preco_all_in_hp_rs_kwh = None
            rec.itens_fatura_preco_all_in_blended_rs_kwh = None

        rec.demanda_contratada_kw = demanda_contratada if demanda_contratada > 0 else rec.demanda_item
        rec.demanda_hp_kw = r.get("demanda_hp_kw")
        rec.demanda_fhp_kw = r.get("demanda_fhp_kw")
        rec.consumo_hp_kwh = r.get("consumo_hp_kwh")
        rec.consumo_fhp_kwh = r.get("consumo_fhp_kwh")

        rec.kwh_total_te = (rec.consumo_hp_kwh or 0.0) + (rec.consumo_fhp_kwh or 0.0)
        rec.demanda_item = rec.demanda_contratada_kw if rec.demanda_contratada_kw is not None else rec.demanda_item

        expanded.append(rec)

    return expanded


def expand_b3_ip_record_from_block(
    block_text: str,
    base_rec: UCMonthRecord,
) -> List[UCMonthRecord]:
    if (base_rec.categoria or "").upper() not in {"B3", "IP"}:
        return [base_rec]

    historico_rows = parse_b3_ip_historico(block_text or "")
    if not historico_rows:
        return [base_rec]

    return _expand_b3_ip_from_month_rows(base_rec, historico_rows)


def _strip_cid_tokens(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\(cid:\d+\)", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _clean_classificacao_text(text: str) -> str:
    if not text:
        return ""
    cleaned = _strip_cid_tokens(text)

    # Remove bill cycle/date tokens that can appear on the same header line.
    cleaned = re.sub(r"\b\d{2}/\d{2}/\d{4}\b", " ", cleaned)
    cleaned = re.sub(r"\b\d{1,2}\b(?=\s+\d{2}/\d{2}/\d{4})", " ", cleaned)
    cleaned = re.sub(r"(?:\s+\d{1,2})+\s*$", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")

    return cleaned


def _parse_flexible_number(value: str) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip().replace(" ", "")
    if not s:
        return None

    # pt-BR (thousands "." + decimal ",")
    if "," in s:
        return parse_ptbr_number(s)

    # Dot decimal from some OCR/token streams (e.g. "231.00")
    if "." in s:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) <= 2:
            try:
                return float(s)
            except Exception:
                return None
        try:
            return float(s.replace(".", ""))
        except Exception:
            return None

    try:
        return float(s)
    except Exception:
        return None


def _extract_month_rows_from_lines(page_text: str) -> list[dict]:
    line_patterns = [
        re.compile(
            r"^\s*(?P<ref>(?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)[/\-]?\d{2,4})\s+"
            r"(?P<v1>[0-9][0-9\.,]*)\s+(?P<v2>[0-9][0-9\.,]*)\s+(?P<v3>[0-9][0-9\.,]*)\s+(?P<v4>[0-9][0-9\.,]*)"
            r"(?:\s+[0-9]{1,3})?\s*$",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?P<ref>(?:0?[1-9]|1[0-2])[/\-]\d{2,4})\s+"
            r"(?P<v1>[0-9][0-9\.,]*)\s+(?P<v2>[0-9][0-9\.,]*)\s+(?P<v3>[0-9][0-9\.,]*)\s+(?P<v4>[0-9][0-9\.,]*)"
            r"(?:\s+[0-9]{1,3})?\s*$",
            flags=re.IGNORECASE,
        ),
    ]

    rows: list[dict] = []
    for line in normalize_whitespace(page_text).split("\n"):
        stripped = line.strip()
        m = None
        for rx in line_patterns:
            m = rx.match(stripped)
            if m:
                break
        if not m:
            continue

        referencia = normalize_reference_token(m.group("ref"))
        if not referencia:
            continue

        demanda_hp = parse_ptbr_number(m.group("v1"))
        demanda_fhp = parse_ptbr_number(m.group("v2"))
        consumo_hp = parse_ptbr_number(m.group("v3"))
        consumo_fhp = parse_ptbr_number(m.group("v4"))
        if any(v is None for v in (demanda_hp, demanda_fhp, consumo_hp, consumo_fhp)):
            continue

        rows.append(
            {
                "referencia": referencia,
                "demanda_hp_kw": float(demanda_hp),
                "demanda_fhp_kw": float(demanda_fhp),
                "consumo_hp_kwh": float(consumo_hp),
                "consumo_fhp_kwh": float(consumo_fhp),
            }
        )

    if not rows:
        return []

    dedup: dict[str, dict] = {}
    for row in rows:
        if row["referencia"] not in dedup:
            dedup[row["referencia"]] = row

    def ref_key(ref: str) -> tuple[int, int]:
        mm, yyyy = ref.split("/")
        return int(yyyy), int(mm)

    return [dedup[r] for r in sorted(dedup.keys(), key=ref_key)]


def _extract_ref_and_total_from_due_line(page_text: str) -> tuple[str, Optional[float]]:
    t = normalize_whitespace(page_text)
    t_norm = _normalize_ascii_upper(t)
    m = re.search(
        rf"\b({REF_TOKEN_PATTERN})\s+\d{{2}}/\d{{2}}/\d{{4}}\s+R\$\s*([0-9][0-9\.,]*)\b",
        t_norm,
        flags=re.IGNORECASE,
    )
    if m:
        ref = normalize_reference_token(m.group(1))
        total = parse_ptbr_number(m.group(2))
        if ref:
            return ref, total

    ref = extract_page_default_ref(t)

    m_total = R.RE_TOTAL_A_PAGAR_RS.search(t)
    if not m_total:
        m_total = re.search(r"\bVALOR\s+A\s+PAGAR\b[\s:R\$]*([0-9][0-9\.,]*)\b", t, flags=re.IGNORECASE)
    if not m_total:
        m_total = re.search(r"\bTOTAL\b[\s:R\$]*([0-9][0-9\.,]*)\b", t, flags=re.IGNORECASE)
    total = parse_ptbr_number(m_total.group(1)) if m_total else None

    return ref, total


def _extract_non_uc_identifier(page_text: str) -> str:
    header_text = " ".join(_extract_header_block_lines(page_text))
    t_ascii = _normalize_ascii_upper(header_text)
    patterns = [
        r"\bNO\s+DO\s+CLIENTE\b[^0-9]{0,30}([0-9]{4,12})\b",
        r"\bUNIDADE\s+CONSUMIDORA\b[^0-9]{0,30}([0-9]{4,12})\b",
        r"\bINSTALACAO\b[^0-9]{0,30}([0-9]{4,12})\b",
        r"\bCODIGO\s+([0-9]{4,12})\b",
        r"\b([0-9]{4,12})\s+NOTA\s+FISCAL\b",
        r"^\s*([0-9]{4,12})\b.*\bCFOP\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, t_ascii, flags=re.IGNORECASE | re.MULTILINE)
        if not m:
            continue
        uc = re.sub(r"\D", "", m.group(1))
        if uc:
            return uc
    return ""


def _extract_non_uc_identifier_from_word_stream(word_stream: str) -> str:
    if not word_stream:
        return ""
    tokens = [t for t in str(word_stream).split() if t]
    month_rx = re.compile(r"^\d{2}/\d{4}$")
    uc_rx = re.compile(r"^\d{4,12}$")

    for i, tok in enumerate(tokens):
        if not month_rx.match(tok):
            continue
        for j in (i - 1, i - 2, i - 3):
            if j < 0:
                continue
            cand = re.sub(r"\D", "", tokens[j])
            if uc_rx.match(cand):
                return cand
    return ""


def _extract_non_uc_name_address(page_text: str) -> tuple[str, str, str]:
    lines = [ln.strip() for ln in _extract_header_block_lines(page_text) if ln.strip()]
    norm_lines = [_normalize_ascii_upper(ln) for ln in lines]

    nome = ""
    endereco = ""
    origem = ""

    for idx, norm_line in enumerate(norm_lines):
        if "PODER PUBLICO MUNICIPAL" not in norm_line:
            continue
        origem = "Poder publico Municipal"
        if idx + 1 < len(lines):
            nome = _strip_cid_tokens(lines[idx + 1])
        if idx + 2 < len(lines):
            endereco_candidate = _strip_cid_tokens(lines[idx + 2])
            if "NOTA FISCAL" not in _normalize_ascii_upper(endereco_candidate):
                endereco = endereco_candidate
        break

    if nome:
        return nome, endereco, origem

    for line, norm_line in zip(lines, norm_lines):
        if "MUNICIPIO DE" in norm_line:
            nome = _strip_cid_tokens(line)
            break
    if nome:
        try:
            idx = lines.index(nome)
            if idx + 1 < len(lines):
                cand = _strip_cid_tokens(lines[idx + 1])
                if "NOTA FISCAL" not in _normalize_ascii_upper(cand):
                    endereco = cand
        except ValueError:
            pass

    return nome, endereco, origem


def _expand_a4_from_month_rows(
    base_rec: UCMonthRecord,
    month_rows: list[dict],
    demanda_contratada: float,
) -> List[UCMonthRecord]:
    expanded: List[UCMonthRecord] = []
    base_ref = str(base_rec.referencia or "").strip()
    for row in month_rows:
        rec = replace(base_rec)
        rec.referencia = row.get("referencia", rec.referencia)

        # Keep invoice/item totals only on the invoice reference month to avoid duplication.
        if str(rec.referencia or "").strip() != base_ref:
            rec.total_fatura_rs = None
            rec.itens_fatura_json = ""
            rec.itens_fatura_total_valor_rs = None
            rec.itens_fatura_energia_valor_rs = None
            rec.itens_fatura_energia_kwh = None
            rec.itens_fatura_preco_medio_rs_kwh = None
            rec.itens_fatura_preco_all_in_fhp_rs_kwh = None
            rec.itens_fatura_preco_all_in_hp_rs_kwh = None
            rec.itens_fatura_preco_all_in_blended_rs_kwh = None

        rec.demanda_hp_kw = row.get("demanda_hp_kw")
        rec.demanda_fhp_kw = row.get("demanda_fhp_kw")
        rec.consumo_hp_kwh = row.get("consumo_hp_kwh")
        rec.consumo_fhp_kwh = row.get("consumo_fhp_kwh")

        rec.kwh_a4_p_te = rec.consumo_hp_kwh
        rec.kwh_a4_fp_te = rec.consumo_fhp_kwh
        rec.kwh_total_te = (rec.consumo_hp_kwh or 0.0) + (rec.consumo_fhp_kwh or 0.0)

        if demanda_contratada > 0:
            rec.demanda_contratada_kw = demanda_contratada
            rec.demanda_item = demanda_contratada
        else:
            rec.demanda_contratada_kw = rec.demanda_hp_kw
            rec.demanda_item = rec.demanda_hp_kw

        expanded.append(rec)
    return expanded


def _extract_month_rows_b3_ip(word_stream: str) -> list[dict]:
    if not word_stream:
        return []

    rows: list[dict] = []
    rx_slash = re.compile(
        r"\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)/(\d{2,4})\s+([0-9][0-9\.,]*)\s+[0-9]{1,3}\b",
        flags=re.IGNORECASE,
    )
    rx_compact = re.compile(
        r"\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)(\d{2,4})\s+([0-9][0-9\.,]*)\s+[0-9]{1,3}\s+(?:LID|MIN)\b",
        flags=re.IGNORECASE,
    )
    rx_numeric = re.compile(
        r"\b((?:0?[1-9]|1[0-2])[/\-]\d{2,4})\s+([0-9][0-9\.,]*)\s+[0-9]{1,3}\b",
        flags=re.IGNORECASE,
    )

    for rx in (rx_slash, rx_compact):
        for m in rx.finditer(word_stream):
            referencia = _month_ref(m.group(1), m.group(2))
            consumo = _parse_flexible_number(m.group(3))
            if not referencia or consumo is None:
                continue
            rows.append({"referencia": referencia, "consumo_kwh": float(consumo)})

    for m in rx_numeric.finditer(word_stream):
        referencia = normalize_reference_token(m.group(1))
        consumo = _parse_flexible_number(m.group(2))
        if not referencia or consumo is None:
            continue
        rows.append({"referencia": referencia, "consumo_kwh": float(consumo)})

    if not rows:
        return []

    return _normalize_month_rows_contiguous(
        rows=rows,
        value_keys=["consumo_kwh"],
        months=13,
    )


def _detect_b_subgrupo_and_category(page_text: str) -> tuple[str, str, str]:
    t_ascii = _normalize_ascii_upper(page_text)
    classif = _normalize_ascii_upper(_extract_header_classificacao(page_text))

    # Priority 1: explicit classification from header block.
    if re.search(r"\bB3\b", classif):
        return "B", "B3", "B3"
    if "B4A" in classif:
        return "B", "B4A", "IP"
    if "B4B" in classif:
        return "B", "B4B", "IP"
    if "ILUMINACAO PUBLICA" in classif:
        return "B", "B4A", "IP"

    # Priority 2: page-level fallback heuristics.
    if re.search(r"\bB3\b", t_ascii):
        return "B", "B3", "B3"
    if "B4A" in t_ascii:
        return "B", "B4A", "IP"
    if "B4B" in t_ascii:
        return "B", "B4B", "IP"
    if "ILUMINACAO PUBLICA" in t_ascii:
        return "B", "B4A", "IP"
    return "", "", ""


def _extract_non_uc_name_address_b(page_text: str) -> tuple[str, str, str]:
    lines_raw = [ln.strip() for ln in _extract_header_block_lines(page_text) if ln.strip()]
    lines = [_strip_cid_tokens(ln) for ln in lines_raw]
    norm_lines = [_normalize_ascii_upper(ln) for ln in lines]

    origem = ""
    if any("PODER PUBLICO MUNICIPAL" in n for n in norm_lines):
        origem = "Poder publico Municipal"
    elif any("ILUMINACAO PUBLICA" in n for n in norm_lines):
        origem = "Iluminacao Publica"

    nome = ""
    for line, norm_line in zip(lines, norm_lines):
        if "MUNICIPIO DE" in norm_line:
            nome = line
            break

    endereco = ""
    for line, norm_line in zip(lines, norm_lines):
        if "UNIDADE CONSUMIDORA" in norm_line:
            if "CLASSIFIC" in norm_line or "TIPO DE FORNECIMENTO" in norm_line:
                continue
            endereco = re.split(r"UNIDADE\s+CONSUMIDORA", line, flags=re.IGNORECASE)[0].strip(" -:")
            if len(endereco) < 6:
                endereco = ""
                continue
            break

    if not endereco:
        street_rx = re.compile(
            r"^(RUA|R\b|AV\b|AVENIDA|ESTRADA|EST\b|RODOVIA|ROD\b|PRACA|PCA\b|TRAVESSA|TV\b)\b",
            flags=re.IGNORECASE,
        )
        if nome:
            try:
                idx_name = lines.index(nome)
                near_lines = lines[idx_name + 1: idx_name + 6]
            except ValueError:
                near_lines = lines
        else:
            near_lines = lines

        for cand in near_lines:
            cand_clean = cand.strip()
            if not cand_clean:
                continue
            if "NOTA FISCAL" in _normalize_ascii_upper(cand_clean):
                continue
            if street_rx.search(cand_clean):
                endereco = cand_clean
                break

    return nome, endereco, origem


def _expand_b3_ip_from_month_rows(
    base_rec: UCMonthRecord,
    month_rows: list[dict],
) -> List[UCMonthRecord]:
    expanded: List[UCMonthRecord] = []
    base_ref = str(base_rec.referencia or "").strip()
    for row in month_rows:
        rec = replace(base_rec)
        rec.referencia = row.get("referencia", rec.referencia)

        # Keep invoice/item totals only on the invoice reference month to avoid duplication.
        if str(rec.referencia or "").strip() != base_ref:
            rec.total_fatura_rs = None
            rec.itens_fatura_json = ""
            rec.itens_fatura_total_valor_rs = None
            rec.itens_fatura_energia_valor_rs = None
            rec.itens_fatura_energia_kwh = None
            rec.itens_fatura_preco_medio_rs_kwh = None
            rec.itens_fatura_preco_all_in_fhp_rs_kwh = None
            rec.itens_fatura_preco_all_in_hp_rs_kwh = None
            rec.itens_fatura_preco_all_in_blended_rs_kwh = None

        consumo = float(row.get("consumo_kwh") or 0.0)
        rec.kwh_b3_ip = consumo
        rec.kwh_total_te = consumo

        expanded.append(rec)
    return expanded


def _extract_from_non_uc_b3_ip_page(
    page_text: str,
    page_index: int,
    pdf_source: str,
    expand_a4_historico: bool = False,
    page_obj=None,
) -> List[UCMonthRecord]:
    if not page_text:
        return []

    t_ascii = _normalize_ascii_upper(page_text)
    if "NOTA FISCAL" not in t_ascii:
        return []

    grupo, subgrupo, categoria = _detect_b_subgrupo_and_category(page_text)
    if categoria not in {"B3", "IP"}:
        return []

    referencia, total_fatura = _extract_ref_and_total_from_due_line(page_text)
    classificacao_uc = _extract_header_classificacao(page_text)

    if page_obj is not None:
        try:
            words = page_obj.extract_words(use_text_flow=True, keep_blank_chars=False)
            word_stream = " ".join(w.get("text", "") for w in words if w.get("text"))
        except Exception:
            word_stream = normalize_whitespace(page_text).replace("\n", " ")
    else:
        word_stream = normalize_whitespace(page_text).replace("\n", " ")

    uc = _extract_non_uc_identifier(page_text)
    if not uc:
        uc = _extract_non_uc_identifier_from_word_stream(word_stream)
    if not uc:
        return []

    month_rows = _extract_month_rows_b3_ip(word_stream)
    if not month_rows:
        return []

    if not referencia:
        referencia = month_rows[-1]["referencia"]

    selected_row = next((r for r in month_rows if r["referencia"] == referencia), month_rows[-1])
    consumo_kwh = float(selected_row.get("consumo_kwh") or 0.0)

    nome, endereco, origem = _extract_non_uc_name_address_b(page_text)
    tipo_fornecimento = extract_tipo_fornecimento(page_text)

    rec = UCMonthRecord(
        uc=uc,
        referencia=referencia,
        grupo_tensao=grupo,
        subgrupo=subgrupo,
        categoria=categoria,
        tipo_fornecimento=tipo_fornecimento,
        origem=origem,
        nome=nome,
        endereco=endereco,
        classificacao_uc=classificacao_uc,
        pdf_source=pdf_source,
        page_first_seen=page_index + 1,
        total_fatura_rs=total_fatura,
        kwh_b3_ip=consumo_kwh,
        kwh_total_te=consumo_kwh,
        audit_header_page=page_index + 1,
        audit_historico_page=page_index + 1,
        audit_kwh_source="HISTORICO_CONSUMO_KWH",
    )

    itens_energy = _extract_energy_items_from_stream(word_stream, categoria_hint=categoria)
    if itens_energy:
        rec.itens_fatura_json = json.dumps(itens_energy, ensure_ascii=False)
        resumo = _summarize_itens_price_value(itens_energy)
        rec.itens_fatura_total_valor_rs = resumo["itens_fatura_total_valor_rs"]
        rec.itens_fatura_energia_valor_rs = resumo["itens_fatura_energia_valor_rs"]
        rec.itens_fatura_energia_kwh = resumo["itens_fatura_energia_kwh"]
        rec.itens_fatura_preco_medio_rs_kwh = resumo["itens_fatura_preco_medio_rs_kwh"]
        rec.itens_fatura_preco_all_in_fhp_rs_kwh = resumo["itens_fatura_preco_all_in_fhp_rs_kwh"]
        rec.itens_fatura_preco_all_in_hp_rs_kwh = resumo["itens_fatura_preco_all_in_hp_rs_kwh"]
        rec.itens_fatura_preco_all_in_blended_rs_kwh = resumo["itens_fatura_preco_all_in_blended_rs_kwh"]
        rec.audit_itens_page = page_index + 1
        te_qty = _extract_te_quantity_from_items(itens_energy)
        if te_qty > 0:
            rec.kwh_b3_ip = float(te_qty)
            rec.kwh_total_te = float(te_qty)
            rec.audit_kwh_source = _compose_kwh_source("ITENS_CONSUMO_TE", "ITEMS_SUMMARY")

    if not str(rec.audit_kwh_source or "").upper().startswith("ITENS_CONSUMO_TE"):
        te_val, te_source = _extract_kwh_cascade(page_text)
        if te_val is not None and te_source in {
            "CONS_IP_TE",
            "CONS_IP_GENERIC",
            "CONS_TE",
            "ENERGIA_TE",
            "ENERGIA_ATIVA",
            "ENERGIA_ELETRICA",
            "CONSUMO_KWH",
        }:
            rec.kwh_b3_ip = float(te_val)
            rec.kwh_total_te = float(te_val)
            rec.audit_kwh_source = _compose_kwh_source("TEXTO_CONSUMO_TE", te_source)

    if expand_a4_historico:
        return _expand_b3_ip_from_month_rows(rec, month_rows)

    return [rec]


def _extract_from_non_uc_page(
    page_text: str,
    page_index: int,
    pdf_source: str,
    expand_a4_historico: bool = False,
    page_obj=None,
) -> List[UCMonthRecord]:
    if not page_text:
        return []

    t_ascii = _normalize_ascii_upper(page_text)
    if "NOTA FISCAL" not in t_ascii:
        return []
    if "A4" not in t_ascii and "HOROSAZONAL" not in t_ascii:
        return []

    month_rows = _extract_month_rows_from_lines(page_text)
    if not month_rows:
        return []

    referencia, total_fatura = _extract_ref_and_total_from_due_line(page_text)
    if not referencia:
        referencia = month_rows[-1]["referencia"]
    classificacao_uc = _extract_header_classificacao(page_text)

    selected_row = next((r for r in month_rows if r["referencia"] == referencia), month_rows[-1])

    nome, endereco, origem = _extract_non_uc_name_address(page_text)
    tipo_fornecimento = extract_tipo_fornecimento(page_text)

    item_stream = normalize_whitespace(page_text).replace("\n", " ")
    if page_obj is not None:
        try:
            words = page_obj.extract_words(use_text_flow=True, keep_blank_chars=False)
            item_stream = " ".join(w.get("text", "") for w in words if w.get("text"))
        except Exception:
            pass

    uc = _extract_non_uc_identifier(page_text)
    if not uc:
        uc = _extract_non_uc_identifier_from_word_stream(item_stream)
    if not uc:
        return []

    demanda_contratada = parse_demanda_contratada(page_text)
    if demanda_contratada <= 0:
        # Some PDFs lose this field in extract_text(); word stream often preserves it.
        demanda_contratada = parse_demanda_contratada(item_stream)
    if demanda_contratada <= 0:
        demanda_contratada = float(
            selected_row.get("demanda_fhp_kw") or selected_row.get("demanda_hp_kw") or 0.0
        )

    rec = UCMonthRecord(
        uc=uc,
        referencia=referencia,
        grupo_tensao="A",
        subgrupo="A4",
        categoria="A4",
        tipo_fornecimento=tipo_fornecimento,
        origem=origem,
        nome=nome,
        endereco=endereco,
        classificacao_uc=classificacao_uc,
        pdf_source=pdf_source,
        page_first_seen=page_index + 1,
        total_fatura_rs=total_fatura,
        audit_header_page=page_index + 1,
        audit_historico_page=page_index + 1,
    )

    rec.demanda_hp_kw = selected_row.get("demanda_hp_kw")
    rec.demanda_fhp_kw = selected_row.get("demanda_fhp_kw")
    rec.consumo_hp_kwh = selected_row.get("consumo_hp_kwh")
    rec.consumo_fhp_kwh = selected_row.get("consumo_fhp_kwh")
    rec.kwh_a4_p_te = rec.consumo_hp_kwh
    rec.kwh_a4_fp_te = rec.consumo_fhp_kwh
    rec.kwh_total_te = (rec.consumo_hp_kwh or 0.0) + (rec.consumo_fhp_kwh or 0.0)
    rec.demanda_item = rec.demanda_hp_kw
    rec.demanda_contratada_kw = demanda_contratada if demanda_contratada > 0 else rec.demanda_item

    itens_energy = _extract_energy_items_from_stream(item_stream, categoria_hint="A4")
    if itens_energy:
        rec.itens_fatura_json = json.dumps(itens_energy, ensure_ascii=False)
        resumo = _summarize_itens_price_value(itens_energy)
        rec.itens_fatura_total_valor_rs = resumo["itens_fatura_total_valor_rs"]
        rec.itens_fatura_energia_valor_rs = resumo["itens_fatura_energia_valor_rs"]
        rec.itens_fatura_energia_kwh = resumo["itens_fatura_energia_kwh"]
        rec.itens_fatura_preco_medio_rs_kwh = resumo["itens_fatura_preco_medio_rs_kwh"]
        rec.itens_fatura_preco_all_in_fhp_rs_kwh = resumo["itens_fatura_preco_all_in_fhp_rs_kwh"]
        rec.itens_fatura_preco_all_in_hp_rs_kwh = resumo["itens_fatura_preco_all_in_hp_rs_kwh"]
        rec.itens_fatura_preco_all_in_blended_rs_kwh = resumo["itens_fatura_preco_all_in_blended_rs_kwh"]
        rec.audit_itens_page = page_index + 1

    if expand_a4_historico:
        return _expand_a4_from_month_rows(rec, month_rows, demanda_contratada)

    return [rec]


def _extract_with_fallback_layouts(
    page_text: str,
    page_index: int,
    pdf_source: str,
    expand_a4_historico: bool = False,
    page_obj=None,
) -> List[UCMonthRecord]:
    # Adapter registry: add future municipality/utility layouts here.
    adapters = [
        _extract_from_non_uc_page,
        _extract_from_non_uc_b3_ip_page,
        _extract_from_elektro_page,
    ]
    for adapter in adapters:
        rows = adapter(
            page_text=page_text,
            page_index=page_index,
            pdf_source=pdf_source,
            expand_a4_historico=expand_a4_historico,
            page_obj=page_obj,
        )
        if rows:
            return rows
    return []


def _extract_from_elektro_page(
    page_text: str,
    page_index: int,
    pdf_source: str,
    expand_a4_historico: bool = False,
    page_obj=None,
) -> List[UCMonthRecord]:
    _ = page_obj
    t_ascii = _normalize_ascii_upper(page_text or "")
    if (
        "CCI" not in t_ascii
        and "DETALHAMENTO DA CONTA" not in t_ascii
        and "NEOENERGIA" not in t_ascii
        and "ELEKTRO" not in t_ascii
    ):
        return []
    rec = _extract_elektro_record_from_block(page_text or "", page_index, pdf_source)
    if rec is None:
        return []
    if expand_a4_historico and (rec.categoria or "").upper() in {"B3", "IP"}:
        return expand_b3_ip_record_from_block(page_text or "", rec)
    return [rec]


def _split_into_uc_blocks_loose(page_text: str) -> list[str]:
    text = normalize_whitespace(page_text or "")
    starts = _find_uc_block_starts(text)
    if not starts:
        return []
    blocks: list[str] = []
    for i, st in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        blocks.append(text[st:end].strip())
    return blocks


@dataclass(frozen=True)
class LayoutProfile:
    layout: str
    detection_markers: tuple[str, ...]
    reference_extractors: tuple[str, ...]
    uc_extractors: tuple[str, ...]
    categoria_extractors: tuple[str, ...]
    itens_extractors: tuple[str, ...]
    kwh_extractors: tuple[str, ...]
    historico_extractors: tuple[str, ...]
    demand_extractors: tuple[str, ...]
    row_extractor_name: str


def get_layout_profiles() -> dict[str, LayoutProfile]:
    return {
        "CELESC_COLETIVA": LayoutProfile(
            layout="CELESC_COLETIVA",
            detection_markers=("RELACAO DE UCS DA COLETIVA", "ITENS DA FATURA", "UC:"),
            reference_extractors=("REFERENCIA", "FATURA YYYYMM", "DATA FATURAMENTO"),
            uc_extractors=("UC BLOCK",),
            categoria_extractors=("GRUPO/SUBGRUPO", "CLASSIFICACAO HEADER"),
            itens_extractors=("ITENS DA FATURA QUANTIDADE",),
            kwh_extractors=("ITENS_CONSUMO_TE", "TEXTO_CONSUMO_TE", "HISTORICO_CONSUMO_KWH", "GENERIC_KWH"),
            historico_extractors=("A4_HISTORICO", "B3_IP_HISTORICO"),
            demand_extractors=("DEMANDA CONTRATADA", "DEMANDA ITEM"),
            row_extractor_name="_extract_celesc_coletiva_pdf_rows",
        ),
        "ENEL_A4": LayoutProfile(
            layout="ENEL_A4",
            detection_markers=("DOCUMENTO AUXILIAR DA NOTA FISCAL", "ITENS DE FATURA", "MES/ANO"),
            reference_extractors=("HEADER REF TOKEN", "EMISSAO DATE"),
            uc_extractors=("UC:", "UNIDADE CONSUMIDORA"),
            categoria_extractors=("CLASSIFICACAO HEADER",),
            itens_extractors=("ITENS DE FATURA UNID QUANT",),
            kwh_extractors=("ITENS_CONSUMO_TE", "TEXTO_CONSUMO_TE", "HISTORICO_CONSUMO_KWH", "GENERIC_KWH"),
            historico_extractors=("A4_HISTORICO",),
            demand_extractors=("DEMANDA HP/FHP",),
            row_extractor_name="_extract_enel_historico_pdf_rows",
        ),
        "NEOENERGIA_ELEKTRO": LayoutProfile(
            layout="NEOENERGIA_ELEKTRO",
            detection_markers=("CCI", "DESCRICAO DO PRODUTO", "GBELEKTRO"),
            reference_extractors=("MES POR EXTENSO", "EMISSAO DATE", "MES/ANO TOKEN"),
            uc_extractors=("UC:", "CCI", "FIRST LINE DIGITS"),
            categoria_extractors=("CLASSIFICACAO HEADER", "PODER PUBLICO"),
            itens_extractors=("CCI* DESCRICAO DO PRODUTO",),
            kwh_extractors=("ITENS_CONSUMO_TE", "TEXTO_CONSUMO_TE", "HISTORICO_CONSUMO_KWH", "GENERIC_KWH"),
            historico_extractors=("B3_IP_HISTORICO",),
            demand_extractors=("A4 DEMANDA",),
            row_extractor_name="_extract_elektro_cci_pdf_rows",
        ),
        "CPFL": LayoutProfile(
            layout="CPFL",
            detection_markers=("CPFL", "DISTRIBUIDORA", "ITENS DA FATURA"),
            reference_extractors=("REFERENCIA", "MES_ANO", "PERIODO_REFERENCIA", "FATURA_YYYYMM"),
            uc_extractors=("UC", "INSTALACAO", "UNIDADE_CONSUMIDORA", "NUMERO_CLIENTE", "DIGIT_FALLBACK"),
            categoria_extractors=("GRUPO_SUBGRUPO", "SUBGRUPO", "CLASSE_CONSUMO", "MODALIDADE"),
            itens_extractors=("GENERIC ITENS",),
            kwh_extractors=("ITEM_CONSUMO_TE_QTD", "CONS_TE", "ENERGIA_ATIVA", "ENERGIA_ELETRICA", "CONSUMO_KWH", "KWH_GENERIC"),
            historico_extractors=("GENERIC HISTORICO",),
            demand_extractors=("DEMANDA_ITEM", "DEMANDA_CONTRATADA", "DEMANDA_REGISTRADA", "DEMANDA_MEDIDA"),
            row_extractor_name="_extract_generic_pdf_rows",
        ),
        "CEMIG": LayoutProfile(
            layout="CEMIG",
            detection_markers=("CEMIG", "DISTRIBUICAO S.A", "CONTA DE ENERGIA"),
            reference_extractors=("REFERENCIA", "MES_ANO", "PERIODO_REFERENCIA", "FATURA_YYYYMM"),
            uc_extractors=("UC", "INSTALACAO", "UNIDADE_CONSUMIDORA", "NUMERO_CLIENTE", "DIGIT_FALLBACK"),
            categoria_extractors=("GRUPO_SUBGRUPO", "SUBGRUPO", "CLASSE_CONSUMO", "MODALIDADE"),
            itens_extractors=("GENERIC ITENS",),
            kwh_extractors=("ITEM_CONSUMO_TE_QTD", "CONS_TE", "ENERGIA_ATIVA", "ENERGIA_ELETRICA", "CONSUMO_KWH", "KWH_GENERIC"),
            historico_extractors=("GENERIC HISTORICO",),
            demand_extractors=("DEMANDA_ITEM", "DEMANDA_CONTRATADA", "DEMANDA_REGISTRADA", "DEMANDA_MEDIDA"),
            row_extractor_name="_extract_generic_pdf_rows",
        ),
        "COPEL": LayoutProfile(
            layout="COPEL",
            detection_markers=("COPEL", "COMPANHIA PARANAENSE", "DESCRICAO DO FATURAMENTO"),
            reference_extractors=("REFERENCIA", "MES_ANO", "PERIODO_REFERENCIA", "FATURA_YYYYMM"),
            uc_extractors=("UC", "INSTALACAO", "UNIDADE_CONSUMIDORA", "NUMERO_CLIENTE", "DIGIT_FALLBACK"),
            categoria_extractors=("GRUPO_SUBGRUPO", "SUBGRUPO", "CLASSE_CONSUMO", "MODALIDADE"),
            itens_extractors=("GENERIC ITENS",),
            kwh_extractors=("ITEM_CONSUMO_TE_QTD", "CONS_TE", "ENERGIA_ATIVA", "ENERGIA_ELETRICA", "CONSUMO_KWH", "KWH_GENERIC"),
            historico_extractors=("GENERIC HISTORICO",),
            demand_extractors=("DEMANDA_ITEM", "DEMANDA_CONTRATADA", "DEMANDA_REGISTRADA", "DEMANDA_MEDIDA"),
            row_extractor_name="_extract_generic_pdf_rows",
        ),
        "EQUATORIAL": LayoutProfile(
            layout="EQUATORIAL",
            detection_markers=("EQUATORIAL", "EQUATORIAL ENERGIA", "FATURA"),
            reference_extractors=("REFERENCIA", "MES_ANO", "PERIODO_REFERENCIA", "FATURA_YYYYMM"),
            uc_extractors=("UC", "INSTALACAO", "UNIDADE_CONSUMIDORA", "NUMERO_CLIENTE", "DIGIT_FALLBACK"),
            categoria_extractors=("GRUPO_SUBGRUPO", "SUBGRUPO", "CLASSE_CONSUMO", "MODALIDADE"),
            itens_extractors=("GENERIC ITENS",),
            kwh_extractors=("ITEM_CONSUMO_TE_QTD", "CONS_TE", "ENERGIA_ATIVA", "ENERGIA_ELETRICA", "CONSUMO_KWH", "KWH_GENERIC"),
            historico_extractors=("GENERIC HISTORICO",),
            demand_extractors=("DEMANDA_ITEM", "DEMANDA_CONTRATADA", "DEMANDA_REGISTRADA", "DEMANDA_MEDIDA"),
            row_extractor_name="_extract_generic_pdf_rows",
        ),
        "ENERGISA": LayoutProfile(
            layout="ENERGISA",
            detection_markers=("ENERGISA", "CONTA DE ENERGIA", "FATURA"),
            reference_extractors=("REFERENCIA", "MES_ANO", "PERIODO_REFERENCIA", "FATURA_YYYYMM"),
            uc_extractors=("UC", "INSTALACAO", "UNIDADE_CONSUMIDORA", "NUMERO_CLIENTE", "DIGIT_FALLBACK"),
            categoria_extractors=("GRUPO_SUBGRUPO", "SUBGRUPO", "CLASSE_CONSUMO", "MODALIDADE"),
            itens_extractors=("GENERIC ITENS",),
            kwh_extractors=("ITEM_CONSUMO_TE_QTD", "CONS_TE", "ENERGIA_ATIVA", "ENERGIA_ELETRICA", "CONSUMO_KWH", "KWH_GENERIC"),
            historico_extractors=("GENERIC HISTORICO",),
            demand_extractors=("DEMANDA_ITEM", "DEMANDA_CONTRATADA", "DEMANDA_REGISTRADA", "DEMANDA_MEDIDA"),
            row_extractor_name="_extract_generic_pdf_rows",
        ),
        "LIGHT": LayoutProfile(
            layout="LIGHT",
            detection_markers=("LIGHT", "SERVICOS DE ELETRICIDADE", "FATURA"),
            reference_extractors=("REFERENCIA", "MES_ANO", "PERIODO_REFERENCIA", "FATURA_YYYYMM"),
            uc_extractors=("UC", "INSTALACAO", "UNIDADE_CONSUMIDORA", "NUMERO_CLIENTE", "DIGIT_FALLBACK"),
            categoria_extractors=("GRUPO_SUBGRUPO", "SUBGRUPO", "CLASSE_CONSUMO", "MODALIDADE"),
            itens_extractors=("GENERIC ITENS",),
            kwh_extractors=("ITEM_CONSUMO_TE_QTD", "CONS_TE", "ENERGIA_ATIVA", "ENERGIA_ELETRICA", "CONSUMO_KWH", "KWH_GENERIC"),
            historico_extractors=("GENERIC HISTORICO",),
            demand_extractors=("DEMANDA_ITEM", "DEMANDA_CONTRATADA", "DEMANDA_REGISTRADA", "DEMANDA_MEDIDA"),
            row_extractor_name="_extract_generic_pdf_rows",
        ),
        "COELBA": LayoutProfile(
            layout="COELBA",
            detection_markers=("COELBA", "NEOENERGIA COELBA", "FATURA"),
            reference_extractors=("REFERENCIA", "MES_ANO", "PERIODO_REFERENCIA", "FATURA_YYYYMM"),
            uc_extractors=("UC", "INSTALACAO", "UNIDADE_CONSUMIDORA", "NUMERO_CLIENTE", "DIGIT_FALLBACK"),
            categoria_extractors=("GRUPO_SUBGRUPO", "SUBGRUPO", "CLASSE_CONSUMO", "MODALIDADE"),
            itens_extractors=("GENERIC ITENS",),
            kwh_extractors=("ITEM_CONSUMO_TE_QTD", "CONS_TE", "ENERGIA_ATIVA", "ENERGIA_ELETRICA", "CONSUMO_KWH", "KWH_GENERIC"),
            historico_extractors=("GENERIC HISTORICO",),
            demand_extractors=("DEMANDA_ITEM", "DEMANDA_CONTRATADA", "DEMANDA_REGISTRADA", "DEMANDA_MEDIDA"),
            row_extractor_name="_extract_generic_pdf_rows",
        ),
        "GENERIC": LayoutProfile(
            layout="GENERIC",
            detection_markers=(),
            reference_extractors=("REFERENCIA", "MES_ANO", "PERIODO_REFERENCIA", "FATURA_YYYYMM", "GENERIC_REF_TOKEN"),
            uc_extractors=("UC", "INSTALACAO", "UNIDADE_CONSUMIDORA", "NUMERO_CLIENTE", "DIGIT_FALLBACK"),
            categoria_extractors=("GRUPO_SUBGRUPO", "SUBGRUPO", "CLASSE_CONSUMO", "MODALIDADE", "GENERIC HEADER"),
            itens_extractors=("GENERIC ITENS",),
            kwh_extractors=(
                "ITEM_CONSUMO_TE_QTD",
                "CONS_TE",
                "ENERGIA_TE",
                "ENERGIA_ATIVA",
                "ENERGIA_ELETRICA",
                "CONSUMO_KWH",
                "HISTORICO_CONSUMO_KWH",
                "KWH_GENERIC",
            ),
            historico_extractors=("GENERIC HISTORICO",),
            demand_extractors=("DEMANDA_ITEM", "DEMANDA_CONTRATADA", "DEMANDA_REGISTRADA", "DEMANDA_MEDIDA"),
            row_extractor_name="_extract_generic_pdf_rows",
        ),
    }


def _score_layout_by_markers(text: str, profile: LayoutProfile) -> int:
    if not text or not profile.detection_markers:
        return 0
    t = _normalize_ascii_upper(text)
    return sum(1 for marker in profile.detection_markers if marker and marker in t)


def detect_layout(text: str) -> str:
    t = _normalize_ascii_upper(text or "")
    if not t:
        return "GENERIC"

    # Strong hard markers first.
    if "RELACAO DE UCS DA COLETIVA" in t and ("ITENS DA FATURA" in t or "ITENS DE FATURA" in t):
        return "CELESC_COLETIVA"
    if "CELESC" in t and ("ITENS DA FATURA" in t or "ITENS DE FATURA" in t):
        return "CELESC_COLETIVA"

    if "DOCUMENTO AUXILIAR DA NOTA FISCAL" in t and (
        "ITENS DE FATURA" in t or "MES/ANO" in t or "HISTORICO DO FATURAMENTO" in t
    ):
        return "ENEL_A4"
    if ("ENEL" in t or "AMPLA" in t) and ("MES/ANO" in t or "HISTORICO DO FATURAMENTO" in t):
        return "ENEL_A4"

    if (
        ("NEOENERGIA" in t or "ELEKTRO" in t or "GBELEKTRO" in t or "CCI*" in t or re.search(r"\bCCI\b", t))
        and ("DESCRICAO DO PRODUTO" in t or "DETALHAMENTO DA CONTA" in t)
    ):
        return "NEOENERGIA_ELEKTRO"

    if ("CPFL" in t or "CPFL PAULISTA" in t or "RGE" in t) and (
        "ITENS DA FATURA" in t
        or "ITENS DE FATURA" in t
        or "DESCRICAO DO FATURAMENTO" in t
        or "DESCRICAO DO PRODUTO" in t
    ):
        return "CPFL"

    if "CEMIG" in t and ("CONTA DE ENERGIA" in t or "ITENS DE FATURA" in t or "DESCRICAO DO FATURAMENTO" in t):
        return "CEMIG"

    if "COPEL" in t and ("ITENS DA FATURA" in t or "DESCRICAO DO FATURAMENTO" in t):
        return "COPEL"

    if "EQUATORIAL" in t and ("ITENS" in t or "FATURA" in t or "DESCRICAO DO FATURAMENTO" in t):
        return "EQUATORIAL"

    if "ENERGISA" in t and ("ITENS" in t or "FATURA" in t or "DESCRICAO DO FATURAMENTO" in t):
        return "ENERGISA"

    if ("LIGHT" in t and "ELETRICIDADE" in t) or ("LIGHT S" in t):
        return "LIGHT"

    if (
        "COELBA" in t
        or "COSERN" in t
        or ("NEOENERGIA" in t and "COELBA" not in t and "ELEKTRO" not in t)
    ):
        return "COELBA"

    # Marker scoring fallback.
    profiles = get_layout_profiles()
    candidates = [p for p in profiles.values() if p.layout != "GENERIC"]
    scored = sorted(
        ((p.layout, _score_layout_by_markers(t, p)) for p in candidates),
        key=lambda x: x[1],
        reverse=True,
    )
    if scored and scored[0][1] >= 2:
        return scored[0][0]
    return "GENERIC"


def detect_utility_template(full_text: str) -> str:
    # Backward-compatible alias.
    return detect_layout(full_text)


def detect_template(full_text: str) -> str:
    # Backward-compatible alias.
    return detect_layout(full_text)


def _detect_layout_scored(full_text: str) -> str:
    # Kept as a separate helper for compatibility with existing probe flow.
    return detect_layout(full_text)


def _detect_template_scored(full_text: str) -> str:
    # Backward-compatible alias.
    return _detect_layout_scored(full_text)


def _extract_generic_pdf_rows(
    pdf,
    pdf_source: str,
    expand_a4_historico: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    page_texts: Optional[list[str]] = None,
) -> List[UCMonthRecord]:
    rows: List[UCMonthRecord] = []
    total_pages = len(pdf.pages)
    page_iter = pdf.pages if progress_callback else tqdm(pdf.pages, desc="Reading pages")
    for i, page in enumerate(page_iter):
        txt = ""
        if page_texts is not None and i < len(page_texts):
            txt = page_texts[i] or ""
        if not txt:
            txt = page.extract_text() or ""
        _set_cached_page_text(page_texts, i, txt)

        before_page_rows = len(rows)

        if _find_uc_block_starts(normalize_whitespace(txt)):
            default_ref = extract_page_default_ref(txt)
            blocks = split_into_uc_blocks(txt)
            if not blocks:
                blocks = _split_into_uc_blocks_loose(txt)
            for block_text in blocks:
                rec = extract_from_uc_block(block_text, i, pdf_source, default_ref=default_ref)
                if rec is None:
                    continue
                if expand_a4_historico and (rec.categoria or "").upper() in {"A4", "B3", "IP"}:
                    if (rec.categoria or "").upper() == "A4":
                        rows.extend(
                            expand_a4_record_from_block(
                                block_text=block_text,
                                page_index=i,
                                pdf_source=pdf_source,
                                base_rec=rec,
                                default_ref=default_ref,
                            )
                        )
                    else:
                        rows.extend(
                            expand_b3_ip_record_from_block(
                                block_text=block_text,
                                base_rec=rec,
                            )
                        )
                else:
                    rows.append(rec)

        # Keep current behavior first; only try alternate layouts when primary extraction got no rows.
        if len(rows) == before_page_rows:
            fallback_rows = _extract_with_fallback_layouts(
                page_text=txt,
                page_index=i,
                pdf_source=pdf_source,
                expand_a4_historico=expand_a4_historico,
                page_obj=page,
            )
            if fallback_rows:
                rows.extend(fallback_rows)

        if progress_callback:
            progress_callback(i + 1, total_pages)

    return rows


def _extract_celesc_coletiva_pdf_rows(
    pdf,
    pdf_source: str,
    expand_a4_historico: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    page_texts: Optional[list[str]] = None,
) -> List[UCMonthRecord]:
    rows: List[UCMonthRecord] = []
    total_pages = len(pdf.pages)
    page_iter = pdf.pages if progress_callback else tqdm(pdf.pages, desc="Reading pages")
    for i, page in enumerate(page_iter):
        txt = ""
        if page_texts is not None and i < len(page_texts):
            txt = page_texts[i] or ""
        if not txt:
            txt = page.extract_text() or ""
        _set_cached_page_text(page_texts, i, txt)

        default_ref = extract_page_default_ref(txt)
        blocks = split_into_uc_blocks(txt)
        if not blocks:
            blocks = _split_into_uc_blocks_loose(txt)

        for block_text in blocks:
            rec = extract_from_uc_block(block_text, i, pdf_source, default_ref=default_ref)
            if rec is None:
                continue

            cat = (rec.categoria or "").upper()
            if expand_a4_historico and cat in {"A4", "B3", "IP"}:
                if cat == "A4":
                    rows.extend(
                        expand_a4_record_from_block(
                            block_text=block_text,
                            page_index=i,
                            pdf_source=pdf_source,
                            base_rec=rec,
                            default_ref=default_ref,
                        )
                    )
                else:
                    rows.extend(
                        expand_b3_ip_record_from_block(
                            block_text=block_text,
                            base_rec=rec,
                        )
                    )
            else:
                rows.append(rec)

        if progress_callback:
            progress_callback(i + 1, total_pages)

    # Safety fallback: if no rows were parsed from UC blocks, use generic parser.
    if not rows:
        return _extract_generic_pdf_rows(
            pdf=pdf,
            pdf_source=pdf_source,
            expand_a4_historico=expand_a4_historico,
            progress_callback=None,
            page_texts=page_texts,
        )

    return rows


def _extract_enel_historico_pdf_rows(
    pdf,
    pdf_source: str,
    expand_a4_historico: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    page_texts: Optional[list[str]] = None,
) -> List[UCMonthRecord]:
    return _extract_generic_pdf_rows(
        pdf=pdf,
        pdf_source=pdf_source,
        expand_a4_historico=expand_a4_historico,
        progress_callback=progress_callback,
        page_texts=page_texts,
    )


def _extract_elektro_cci_pdf_rows(
    pdf,
    pdf_source: str,
    expand_a4_historico: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    page_texts: Optional[list[str]] = None,
) -> List[UCMonthRecord]:
    # First, reuse generic extractor (covers most layouts).
    rows = _extract_generic_pdf_rows(
        pdf=pdf,
        pdf_source=pdf_source,
        expand_a4_historico=expand_a4_historico,
        progress_callback=progress_callback,
        page_texts=page_texts,
    )
    if rows:
        return rows

    # Dedicated CCI fallback when generic extraction yields no rows.
    out: list[UCMonthRecord] = []
    total_pages = len(pdf.pages)
    for i, page in enumerate(pdf.pages):
        txt = ""
        if page_texts is not None and i < len(page_texts):
            txt = page_texts[i] or ""
        if not txt:
            txt = page.extract_text() or ""
        _set_cached_page_text(page_texts, i, txt)

        t_ascii = _normalize_ascii_upper(txt)
        if "CCI" not in t_ascii and "UC:" not in t_ascii:
            continue

        block_texts = _split_into_cci_blocks(txt)
        if not block_texts:
            block_texts = [txt]

        for block in block_texts:
            rec = _extract_elektro_record_from_block(block, i, pdf_source)
            if rec is None:
                continue
            if expand_a4_historico and (rec.categoria or "").upper() in {"B3", "IP"}:
                out.extend(expand_b3_ip_record_from_block(block, rec))
            else:
                out.append(rec)

        if progress_callback:
            progress_callback(i + 1, total_pages)

    return out


def _build_probe_page_indexes(total_pages: int, max_probe_pages: int) -> list[int]:
    if total_pages <= 0:
        return []

    probe_n = min(max(1, int(max_probe_pages)), total_pages)
    if probe_n >= total_pages:
        return list(range(total_pages))

    head_n = min(max(1, probe_n // 2), total_pages)
    tail_n = min(max(1, probe_n // 4), total_pages - head_n)
    mid_n = max(0, probe_n - head_n - tail_n)

    idx: set[int] = set()
    for i in range(head_n):
        idx.add(i)
    for i in range(total_pages - tail_n, total_pages):
        idx.add(i)

    span_start = head_n
    span_end = max(span_start, total_pages - tail_n - 1)
    if mid_n > 0 and span_end >= span_start:
        for j in range(mid_n):
            frac = float(j + 1) / float(mid_n + 1)
            k = span_start + int(round(frac * float(span_end - span_start)))
            idx.add(k)

    if len(idx) < probe_n:
        for k in range(total_pages):
            if len(idx) >= probe_n:
                break
            idx.add(k)

    return sorted(idx)


def _detect_template_from_pdf_probe(pdf, max_probe_pages: int = 40) -> tuple[str, list[str]]:
    total_pages = len(pdf.pages)
    probe_idx = _build_probe_page_indexes(total_pages, max_probe_pages)
    probe_texts: list[str] = [""] * total_pages
    for i in probe_idx:
        probe_texts[i] = pdf.pages[i].extract_text() or ""

    probe_blob = "\n".join(probe_texts[i] for i in probe_idx if probe_texts[i])
    template = detect_utility_template(probe_blob)
    if template == "GENERIC":
        template = _detect_template_scored(probe_blob)
    return template, probe_texts


def _split_into_cci_blocks(page_text: str) -> list[str]:
    text = normalize_whitespace(page_text or "")
    starts = [m.start() for m in re.finditer(r"\bCCI\b[^0-9]{0,20}[0-9]{4,12}\b", text, flags=re.IGNORECASE)]
    if not starts:
        return []
    blocks: list[str] = []
    for i, st in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        blocks.append(text[st:end].strip())
    return blocks


def _categoria_from_text(text: str) -> str:
    t = _normalize_ascii_upper(text or "")
    if re.search(r"\bA4\b", t):
        return "A4"
    if re.search(r"\bB3\b", t):
        return "B3"
    if re.search(r"\bB4[AB]?\b", t) or "ILUMINACAO PUBLICA" in t:
        return "IP"
    # Neoenergia/Elektro grouped invoices often expose "PODER PUBLICO" without B3/B4 token.
    if "PODER PUBLICO" in t and "CONSUMO PONTA" not in t and "FORA PONTA" not in t:
        return "B3"
    return "OUTROS"


def _extract_elektro_record_from_block(block_text: str, page_index: int, pdf_source: str) -> Optional[UCMonthRecord]:
    if not block_text:
        return None
    t = normalize_whitespace(block_text)
    t_ascii = _normalize_ascii_upper(t)
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]

    m_uc = re.search(r"\bUC\s*:\s*([0-9]{3,12})\b", t_ascii, flags=re.IGNORECASE)
    if not m_uc:
        m_uc = re.search(r"\bCCI\b[^0-9]{0,20}([0-9]{3,12})\b", t_ascii, flags=re.IGNORECASE)
    uc = re.sub(r"\D", "", m_uc.group(1)) if m_uc else ""
    # Grouped invoices can have UC as a standalone first line (no "UC:" / "CCI 123").
    if not uc and lines:
        first_digits = re.sub(r"\D", "", lines[0])
        if 6 <= len(first_digits) <= 12:
            uc = first_digits
    if not uc:
        m_uc_footer = re.search(
            r"\bSEU\s+CODIGO\b[\s\S]{0,200}\b([0-9]{6,12})\b",
            t_ascii,
            flags=re.IGNORECASE,
        )
        if m_uc_footer:
            uc = re.sub(r"\D", "", m_uc_footer.group(1))
    if not uc:
        return None

    referencia = ""
    month_map = {
        "JANEIRO": "01",
        "FEVEREIRO": "02",
        "MARCO": "03",
        "ABRIL": "04",
        "MAIO": "05",
        "JUNHO": "06",
        "JULHO": "07",
        "AGOSTO": "08",
        "SETEMBRO": "09",
        "OUTUBRO": "10",
        "NOVEMBRO": "11",
        "DEZEMBRO": "12",
    }
    # Elektro grouped invoices usually print explicit month name in the header (e.g. "Setembro/2025").
    m_ref_name = re.search(
        r"\b(JANEIRO|FEVEREIRO|MARCO|ABRIL|MAIO|JUNHO|JULHO|AGOSTO|SETEMBRO|OUTUBRO|NOVEMBRO|DEZEMBRO)\s*/\s*(\d{4})\b",
        t_ascii,
        flags=re.IGNORECASE,
    )
    if m_ref_name:
        mm = month_map.get(m_ref_name.group(1).upper(), "")
        yyyy = m_ref_name.group(2)
        if mm:
            referencia = f"{mm}/{yyyy}"
    if not referencia:
        m_emissao = re.search(
            r"\bDATA\s+DE\s+EMISSAO\s*:\s*(\d{2}/\d{2}/\d{4})\b",
            t_ascii,
            flags=re.IGNORECASE,
        )
        if m_emissao:
            referencia = date_to_ref(m_emissao.group(1))
    if not referencia:
        m_ref_short = re.search(
            r"\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s*/\s*(\d{2,4})\b",
            t_ascii,
            flags=re.IGNORECASE,
        )
        if m_ref_short:
            referencia = _month_ref(m_ref_short.group(1).upper(), m_ref_short.group(2))
    if not referencia:
        m_ref = re.search(r"\b(\d{2}/\d{4})\b", t)
        if m_ref:
            referencia = m_ref.group(1)
    if not referencia:
        referencia = extract_page_default_ref(t)

    categoria = _categoria_from_text(t)
    if categoria == "OUTROS":
        # Common low-voltage grouped layout with TE/TUSD but without B3 token.
        if re.search(r"\bCONSUMO\s+TE\b", t_ascii) and "CONSUMO PONTA" not in t_ascii and "FORA PONTA" not in t_ascii:
            categoria = "B3"
    classif = _extract_header_classificacao(t)
    tipo = extract_tipo_fornecimento(t)
    nome = ""
    endereco = ""
    m_nome = re.search(r"\bNOME\s*:\s*(.+?)(?:\bENDERECO\b|$)", t, flags=re.IGNORECASE)
    if m_nome:
        nome = m_nome.group(1).strip()
    m_end = re.search(r"\bENDEREC[OÇ]\s*:\s*(.+?)(?:\bCCI\b|$)", t, flags=re.IGNORECASE)
    if m_end:
        endereco = m_end.group(1).strip()
    if not nome and len(lines) >= 2:
        first_digits = re.sub(r"\D", "", lines[0])
        if 6 <= len(first_digits) <= 12:
            name_candidate = lines[1].strip()
            if name_candidate:
                name_norm = _normalize_ascii_upper(name_candidate)
                if all(
                    token not in name_norm
                    for token in [
                        "DATA DE EMISSAO",
                        "DATA DE APRESENTACAO",
                        "CNPJ/CPF",
                        "CONTROLE",
                        "SEU CODIGO",
                    ]
                ):
                    nome = name_candidate
    if not endereco and len(lines) >= 2:
        start_idx = 1 if 6 <= len(re.sub(r"\D", "", lines[0])) <= 12 else 0
        if nome and start_idx < len(lines) and _normalize_ascii_upper(lines[start_idx]) == _normalize_ascii_upper(nome):
            start_idx += 1

        endereco_parts: list[str] = []
        stop_markers = [
            "DATA DE EMISSAO",
            "DATA DE APRESENTACAO",
            "CNPJ/CPF",
            "CONTROLE N",
            "DESCRICAO DO PRODUTO",
            "SEU CODIGO",
            "FATURA AGRUPADA",
            "GBELEKTRO",
        ]
        for ln in lines[start_idx:]:
            ln_clean = re.sub(r"(?i)\bData\s+de\s+Emiss[aã]o\s*:.*$", "", ln).strip(" -")
            if not ln_clean:
                continue
            ln_norm = _normalize_ascii_upper(ln_clean)
            if any(marker in ln_norm for marker in stop_markers):
                break
            if nome and ln_norm == _normalize_ascii_upper(nome):
                continue
            endereco_parts.append(ln_clean)
        endereco = " ".join(endereco_parts).strip()

    total_fatura = None
    m_total = re.search(r"\bTOTAL\s+A\s+PAGAR\b[\s:R\$]*([0-9][0-9\.,]*)", t_ascii, flags=re.IGNORECASE)
    if m_total:
        total_fatura = parse_ptbr_number(m_total.group(1))
    if total_fatura is None:
        rs_vals = re.findall(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})", t_ascii, flags=re.IGNORECASE)
        if rs_vals:
            total_fatura = parse_ptbr_number(rs_vals[-1])
    if total_fatura is None:
        m_total_line = re.search(
            r"(?im)^TOTAL\b[^\n]*?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\s*$",
            t_ascii,
            flags=re.IGNORECASE,
        )
        if m_total_line:
            total_fatura = parse_ptbr_number(m_total_line.group(1))

    rec = UCMonthRecord(
        uc=uc,
        referencia=referencia,
        grupo_tensao="",
        subgrupo="",
        categoria=categoria,
        tipo_fornecimento=tipo,
        origem="",
        nome=nome,
        endereco=endereco,
        classificacao_uc=classif,
        pdf_source=pdf_source,
        page_first_seen=page_index + 1,
        total_fatura_rs=total_fatura,
        audit_header_page=page_index + 1,
    )

    hist_rows_b = parse_b3_ip_historico(t)
    if hist_rows_b:
        rec.audit_historico_page = page_index + 1
    hist_map_b = {
        str(r.get("referencia", "")).strip(): float(r.get("consumo_kwh") or 0.0)
        for r in (hist_rows_b or [])
        if r.get("referencia")
    }

    # Rule B: when no historico is available, kwh_total_te must come from "Consumo TE" quantity.
    items = _extract_itens_price_value_items(t)
    if items:
        rec.itens_fatura_json = json.dumps(items, ensure_ascii=False)
        resumo = _summarize_itens_price_value(items)
        rec.itens_fatura_total_valor_rs = resumo["itens_fatura_total_valor_rs"]
        rec.itens_fatura_energia_valor_rs = resumo["itens_fatura_energia_valor_rs"]
        rec.itens_fatura_energia_kwh = resumo["itens_fatura_energia_kwh"]
        rec.itens_fatura_preco_medio_rs_kwh = resumo["itens_fatura_preco_medio_rs_kwh"]
        rec.itens_fatura_preco_all_in_fhp_rs_kwh = resumo["itens_fatura_preco_all_in_fhp_rs_kwh"]
        rec.itens_fatura_preco_all_in_hp_rs_kwh = resumo["itens_fatura_preco_all_in_hp_rs_kwh"]
        rec.itens_fatura_preco_all_in_blended_rs_kwh = resumo["itens_fatura_preco_all_in_blended_rs_kwh"]
        rec.audit_itens_page = page_index + 1
        te_qty = _extract_te_quantity_from_items(items)
        if te_qty > 0:
            rec.kwh_total_te = float(te_qty)
            if categoria in {"B3", "IP"}:
                rec.kwh_b3_ip = float(te_qty)
            rec.audit_kwh_source = "ITENS_CONSUMO_TE"
    # Universal B3/IP fallback priority:
    # 2) explicit TE line, 3) historico month, 4) generic kWh fallback.
    if rec.kwh_total_te is None and rec.categoria in {"B3", "IP"}:
        # 2) Fallback for Elektro grouped text rows:
        # "0601 CONSUMO TE <quantidade> <preco> <valor>"
        te_vals: list[float] = []
        for m in re.finditer(
            r"\b(?:CONSUMO(?:\s+[A-Z]+){0,4}|CUSTO\s+DISP\s+SISTEMA)\s+TE\b(?:\s+[A-Z/%()\-]+){0,3}\s+([0-9][0-9\.,]*)\b",
            t_ascii,
            flags=re.IGNORECASE,
        ):
            v = parse_ptbr_number(m.group(1))
            if v is not None:
                te_vals.append(float(v))

        if te_vals:
            te_total = float(sum(te_vals))
            rec.kwh_total_te = te_total
            rec.kwh_b3_ip = te_total
            rec.audit_kwh_source = "TEXTO_CONSUMO_TE"
            if rec.categoria == "OUTROS":
                rec.categoria = "B3"
        else:
            m_te = R.RE_CONS_IP_TE.search(t)
            if not m_te:
                m_te = R.RE_CONS_IP_GENERIC.search(t)
            if not m_te:
                m_te = R.RE_CONS_TE.search(t)
            if not m_te:
                m_te = R.RE_ENERGIA_TE.search(t)

            if m_te:
                te_val = parse_ptbr_number(m_te.group(1))
                if te_val is not None:
                    rec.kwh_total_te = float(te_val)
                    rec.kwh_b3_ip = float(te_val)
                    rec.audit_kwh_source = "TEXTO_CONSUMO_TE"
                    if rec.categoria == "OUTROS":
                        rec.categoria = "B3"
            elif rec.referencia in hist_map_b:
                rec.kwh_total_te = float(hist_map_b.get(rec.referencia, 0.0))
                rec.kwh_b3_ip = rec.kwh_total_te
                rec.audit_kwh_source = "HISTORICO_CONSUMO_KWH"

        # 4) Generic fallback for residual layouts.
        if rec.kwh_total_te is None:
            m_ap = R.RE_ENERGIA_UNICO_APURADO.search(t)
            if m_ap:
                kwh_ap = parse_ptbr_number(m_ap.group(1))
                if kwh_ap is not None:
                    rec.kwh_total_te = float(kwh_ap)
                    rec.kwh_b3_ip = rec.kwh_total_te
                    rec.audit_kwh_source = "ENERGIA_UNICO_APURADO"
        if rec.kwh_total_te is None:
            m_kwh = R.RE_KWH_GENERIC.search(t)
            if not m_kwh:
                m_kwh = R.RE_KWH_BROKEN.search(t)
            if m_kwh:
                kwh_generic = parse_ptbr_number(m_kwh.group(1))
                if kwh_generic is not None:
                    rec.kwh_total_te = float(kwh_generic)
                    rec.kwh_b3_ip = rec.kwh_total_te
                    rec.audit_kwh_source = "GENERIC_KWH"

    return rec


def _parse_items_json_safe(raw: str) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _safe_float(value) -> float:
    try:
        out = float(value)
        if pd.isna(out):
            return 0.0
        return out
    except Exception:
        return 0.0


def _extract_te_quantity_from_items(items: list[dict]) -> float:
    te_qty = 0.0
    for item in items:
        name = _normalize_ascii_upper(item.get("item", ""))
        comp = _normalize_ascii_upper(item.get("componente", ""))
        if ("CONSUMO" not in name and "ENERGIA" not in name) and comp not in {"TE", "TUSD"}:
            continue
        if "TUSD" in name or comp == "TUSD":
            continue
        if re.search(r"\bTE\b", name) or comp == "TE":
            te_qty += _safe_float(item.get("quantidade"))
    return te_qty


def _extract_te_tusd_components(items: list[dict]) -> dict[str, float]:
    te_qty = 0.0
    tusd_qty = 0.0
    te_val = 0.0
    tusd_val = 0.0
    te_unit_sum = 0.0
    tusd_unit_sum = 0.0

    for item in items:
        name = _normalize_ascii_upper(item.get("item", ""))
        comp = _normalize_ascii_upper(item.get("componente", ""))
        if ("CONSUMO" not in name and "ENERGIA" not in name) and comp not in {"TE", "TUSD"}:
            continue

        qty = _safe_float(item.get("quantidade"))
        unit = _safe_float(item.get("preco_unitario_com_tributos"))
        val = _safe_float(item.get("valor"))

        is_tusd = ("TUSD" in name) or comp == "TUSD"
        is_te = (re.search(r"\bTE\b", name) is not None) or comp == "TE"
        if is_tusd:
            tusd_qty += qty
            tusd_val += val
            tusd_unit_sum += unit * qty
        elif is_te:
            te_qty += qty
            te_val += val
            te_unit_sum += unit * qty

    preco_te = (te_unit_sum / te_qty) if te_qty > 0 else 0.0
    preco_tusd = (tusd_unit_sum / tusd_qty) if tusd_qty > 0 else 0.0
    return {
        "te_qty": te_qty,
        "tusd_qty": tusd_qty,
        "preco_te": preco_te,
        "preco_tusd": preco_tusd,
        "valor_te": te_val,
        "valor_tusd": tusd_val,
    }


def _row_has_historico_values(row: pd.Series) -> bool:
    keys = ["demanda_hp_kw", "demanda_fhp_kw", "consumo_hp_kwh", "consumo_fhp_kwh"]
    for k in keys:
        if k not in row.index:
            continue
        if _safe_float(row.get(k)) > 0:
            return True
    return False


def _disponibilidade_from_tipo(tipo: str) -> float:
    t = _normalize_ascii_upper(tipo or "")
    if "TRIF" in t:
        return 100.0
    if "BIF" in t:
        return 50.0
    if "MONO" in t:
        return 30.0
    return 0.0


def _fill_zero_metrics_with_disponibilidade(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "tipo_fornecimento" not in df.columns:
        return df

    out = df.copy()
    disp = out["tipo_fornecimento"].apply(_disponibilidade_from_tipo).astype(float)
    if "categoria" in out.columns:
        cat = out["categoria"].astype(str).str.upper()
    else:
        cat = pd.Series([""] * len(out), index=out.index)

    # Fill kWh when zero for any category.
    if "kwh_total_te" in out.columns:
        out["kwh_total_te"] = pd.to_numeric(out["kwh_total_te"], errors="coerce").fillna(0.0)
        mask = (out["kwh_total_te"].abs() <= 1e-9) & (disp > 0)
        out.loc[mask, "kwh_total_te"] = disp[mask]

    # A4 demand/consumption series: replace zeros with disponibilidade by supply type.
    a4_mask = cat.eq("A4")
    for col in ["demanda_hp_kw", "demanda_fhp_kw", "consumo_hp_kwh", "consumo_fhp_kwh"]:
        if col not in out.columns:
            continue
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
        mask = a4_mask & (out[col].abs() <= 1e-9) & (disp > 0)
        out.loc[mask, col] = disp[mask]

    return out


def _enforce_kwh_total_te_rule(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "itens_fatura_json" not in df.columns:
        return df
    out = df.copy()
    if "kwh_total_te" not in out.columns:
        out["kwh_total_te"] = 0.0
    if "kwh_b3_ip" not in out.columns:
        out["kwh_b3_ip"] = 0.0

    for idx, row in out.iterrows():
        items = _parse_items_json_safe(row.get("itens_fatura_json", ""))
        if not items:
            continue
        te_qty = _extract_te_quantity_from_items(items)
        if te_qty <= 0:
            continue
        if _row_has_historico_values(row):
            continue

        out.at[idx, "kwh_total_te"] = float(te_qty)
        cat = _normalize_ascii_upper(row.get("categoria", ""))
        if cat in {"B3", "IP"} or not cat:
            out.at[idx, "kwh_b3_ip"] = float(te_qty)

    return out


def _populate_pricing_component_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for col in ["preco_te", "preco_tusd", "valor_te", "valor_tusd", "preco_all_in_kwh"]:
        if col not in out.columns:
            out[col] = 0.0

    for idx, row in out.iterrows():
        items = _parse_items_json_safe(row.get("itens_fatura_json", ""))
        if not items:
            # Backward compatible fallback when only blended metric exists.
            existing_blended = _safe_float(row.get("itens_fatura_preco_all_in_blended_rs_kwh"))
            if existing_blended > 0:
                out.at[idx, "preco_all_in_kwh"] = existing_blended
            continue

        comps = _extract_te_tusd_components(items)
        out.at[idx, "preco_te"] = comps["preco_te"]
        out.at[idx, "preco_tusd"] = comps["preco_tusd"]
        out.at[idx, "valor_te"] = comps["valor_te"]
        out.at[idx, "valor_tusd"] = comps["valor_tusd"]

        kwh_base = _safe_float(row.get("kwh_total_te"))
        total_val = comps["valor_te"] + comps["valor_tusd"]
        if kwh_base > 0 and total_val > 0:
            out.at[idx, "preco_all_in_kwh"] = total_val / kwh_base
        else:
            existing_blended = _safe_float(row.get("itens_fatura_preco_all_in_blended_rs_kwh"))
            if existing_blended > 0:
                out.at[idx, "preco_all_in_kwh"] = existing_blended

    return out


def _is_discovery_mode_enabled(discovery_mode: Optional[bool] = None) -> bool:
    if discovery_mode is not None:
        return bool(discovery_mode)
    raw = str(os.getenv("DISCOVERY_MODE", "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _collect_discovery_from_page(summary: dict[str, Any], page_text: str) -> None:
    if not page_text:
        return
    lines = [ln.strip() for ln in normalize_whitespace(page_text).split("\n") if ln.strip()]
    if not lines:
        return

    known_header_tokens = [
        "ITENS DA FATURA",
        "ITENS DE FATURA",
        "ITENS DE FATURA UNID QUANT",
        "CCI* DESCRICAO DO PRODUTO",
    ]

    for line in lines:
        norm = _normalize_ascii_upper(line)
        if "DESCRICAO" in norm and ("QUANT" in norm or "QUANTIDADE" in norm):
            if not any(token in norm for token in known_header_tokens):
                summary["unmatched_itens_headers"].append(line)

        if "CONSUMO" in norm and any(k in norm for k in ["TE", "TUSD", "KWH", "ENERGIA"]):
            summary["candidate_consumption_lines"].append(line)

    month_tokens = re.findall(
        r"\b(?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s*/\s*\d{2,4}\b|\b(?:0?[1-9]|1[0-2])/\d{4}\b",
        _normalize_ascii_upper(page_text),
        flags=re.IGNORECASE,
    )
    summary["detected_month_tokens"].extend(month_tokens)


def _sample_page_text(page_texts: list[str], max_pages: int = 2) -> str:
    selected: list[str] = []
    for txt in page_texts:
        if not txt:
            continue
        selected.append(txt)
        if len(selected) >= max_pages:
            break
    return "\n\n".join(selected)


def _make_field_report_entry(value: Any, source_pattern: str) -> dict[str, Any]:
    found = False
    if isinstance(value, str):
        found = bool(value.strip())
    elif value is not None:
        found = True
    return {
        "found": bool(found),
        "source_pattern": str(source_pattern or ""),
        "value": value,
    }


def _build_field_extraction_report(text: str, out_df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    uc, uc_source = _extract_uc_cascade(text, target_len=10)
    referencia, ref_source = _extract_reference_cascade(text)
    kwh, kwh_source = _extract_kwh_cascade(text)
    demanda, demanda_source = _extract_demand_cascade(text)
    categoria_info = _extract_categoria_bundle(text)
    categoria = categoria_info.get("categoria", "")
    categoria_source = categoria_info.get("source_pattern", "")

    if out_df is not None and not out_df.empty:
        row = out_df.iloc[0]
        row_uc = str(row.get("uc", "") or "").strip()
        row_ref = str(row.get("referencia", "") or "").strip()
        row_categoria = str(row.get("categoria", "") or "").strip()
        row_kwh = _safe_float(row.get("kwh_total_te"))
        row_kwh_source = str(row.get("audit_kwh_source", "") or "").strip()
        row_demanda = max(
            _safe_float(row.get("demanda_item")),
            _safe_float(row.get("demanda_contratada_kw")),
            _safe_float(row.get("demanda_hp_kw")),
            _safe_float(row.get("demanda_fhp_kw")),
        )

        if not uc and row_uc:
            uc = row_uc
            uc_source = "FINAL_ROW"
        if not referencia and row_ref:
            referencia = row_ref
            ref_source = "FINAL_ROW"
        if (not categoria or categoria == "OUTROS") and row_categoria:
            categoria = row_categoria
            categoria_source = "FINAL_ROW"
        if (kwh is None or float(kwh) <= 0) and row_kwh > 0:
            kwh = row_kwh
            kwh_source = row_kwh_source or "FINAL_ROW"
        if (demanda is None or float(demanda) <= 0) and row_demanda > 0:
            demanda = row_demanda
            demanda_source = "FINAL_ROW"

    return {
        "uc": _make_field_report_entry(uc, uc_source),
        "reference": _make_field_report_entry(referencia, ref_source),
        "kwh": _make_field_report_entry(kwh, kwh_source),
        "demand": _make_field_report_entry(demanda, demanda_source),
        "categoria": _make_field_report_entry(categoria, categoria_source),
    }


def _write_discovery_summary(pdf_source: str, summary: dict[str, Any]) -> None:
    out_dir = str(os.getenv("DISCOVERY_OUTPUT_DIR", os.getcwd())).strip() or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)

    for key in ["unmatched_itens_headers", "candidate_consumption_lines", "detected_month_tokens"]:
        items = summary.get(key, [])
        if not isinstance(items, list):
            summary[key] = []
            continue
        deduped = list(dict.fromkeys([str(x).strip() for x in items if str(x).strip()]))
        summary[key] = deduped

    out_name = f"{os.path.splitext(pdf_source)[0]}_discovery.json"
    out_path = os.path.join(out_dir, out_name)
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False, indent=2)


def _apply_provider_layout_and_review_flags(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        out = df.copy()
        if "provider_layout" not in out.columns:
            out["provider_layout"] = ""
        if "needs_review" not in out.columns:
            out["needs_review"] = False
        return out

    out = df.copy()
    if "provider_layout" not in out.columns:
        out["provider_layout"] = out.get("template", "")
    out["provider_layout"] = out["provider_layout"].fillna("").astype(str)

    categoria = (
        out["categoria"].astype(str).str.upper()
        if "categoria" in out.columns
        else pd.Series([""] * len(out), index=out.index)
    )
    referencia = (
        out["referencia"].astype(str).str.strip()
        if "referencia" in out.columns
        else pd.Series([""] * len(out), index=out.index)
    )
    ref_valid = referencia.str.match(r"^\d{2}/\d{4}$")
    kwh_source = (
        out["audit_kwh_source"].astype(str).str.upper()
        if "audit_kwh_source" in out.columns
        else pd.Series([""] * len(out), index=out.index)
    )
    layout = out["provider_layout"].astype(str).str.upper()

    needs_review = pd.Series(False, index=out.index)
    needs_review = needs_review | layout.eq("GENERIC")
    needs_review = needs_review | categoria.eq("OUTROS")
    needs_review = needs_review | (~ref_valid)
    b3_ip = categoria.isin({"B3", "IP"})
    needs_review = needs_review | (b3_ip & (~kwh_source.str.startswith("ITENS_CONSUMO_TE")))

    out["needs_review"] = needs_review.astype(bool)
    return out


def _ensure_output_contract(df: pd.DataFrame) -> pd.DataFrame:
    text_cols = [
        "uc",
        "referencia",
        "categoria",
        "nome",
        "endereco",
        "tipo_fornecimento",
        "pdf_source",
        "audit_kwh_source",
        "provider_layout",
        "template",
    ]
    bool_cols = [
        "needs_review",
    ]
    numeric_cols = [
        "kwh_total_te",
        "demanda_hp_kw",
        "demanda_fhp_kw",
        "consumo_hp_kwh",
        "consumo_fhp_kwh",
        "demanda_contratada_kw",
        "dif_demanda",
        "page_first_seen",
        "preco_te",
        "preco_tusd",
        "valor_te",
        "valor_tusd",
        "preco_all_in_kwh",
    ]

    out = df.copy()
    for col in text_cols:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str)

    for col in bool_cols:
        if col not in out.columns:
            out[col] = False
        out[col] = out[col].fillna(False).astype(bool)

    for col in numeric_cols:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    return out


def _finalize_extracted_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "uc" in out.columns:
        out["uc"] = out["uc"].astype(str)

    out = _enforce_kwh_total_te_rule(out)
    out = _fill_zero_metrics_with_disponibilidade(out)
    out = _populate_pricing_component_columns(out)
    out = _apply_provider_layout_and_review_flags(out)
    out = _ensure_output_contract(out)
    return out


def _resolve_profile_extractor(layout: str) -> tuple[LayoutProfile, Callable[..., List[UCMonthRecord]]]:
    profiles = get_layout_profiles()
    profile = profiles.get(layout, profiles["GENERIC"])
    extractor = globals().get(profile.row_extractor_name)
    if not callable(extractor):
        extractor = _extract_generic_pdf_rows
    return profile, extractor


def extract_pdf(
    pdf_path: str,
    expand_a4_historico: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    discovery_mode: Optional[bool] = None,
) -> pd.DataFrame:
    pdf_source = os.path.basename(pdf_path)
    discovery_enabled = _is_discovery_mode_enabled(discovery_mode)
    discovery_summary: dict[str, Any] = {
        "pdf_source": pdf_source,
        "detected_layout": "",
        "effective_layout": "",
        "profile": {},
        "pages_scanned": 0,
        "rows_extracted": 0,
        "unmatched_itens_headers": [],
        "candidate_consumption_lines": [],
        "detected_month_tokens": [],
        "category_counts": {},
        "kwh_source_counts": {},
        "field_extraction_report": {},
        "unmatched_text_sample": "",
    }

    with pdfplumber.open(pdf_path) as pdf:
        # Probe a limited number of pages to classify template quickly.
        # This avoids a costly full pre-read pass on very large PDFs.
        layout_type, probe_texts = _detect_template_from_pdf_probe(pdf, max_probe_pages=40)
        detected_layout = layout_type
        # Reuse probe texts during extraction to avoid reading the same pages twice.
        page_texts = probe_texts

        profile, extractor = _resolve_profile_extractor(layout_type)
        rows = extractor(
            pdf=pdf,
            pdf_source=pdf_source,
            expand_a4_historico=expand_a4_historico,
            progress_callback=progress_callback,
            page_texts=page_texts,
        )

        # Profile-first extraction; fallback to GENERIC extractor when needed.
        if not rows and layout_type != "GENERIC":
            generic_profile, generic_extractor = _resolve_profile_extractor("GENERIC")
            rows = generic_extractor(
                pdf=pdf,
                pdf_source=pdf_source,
                expand_a4_historico=expand_a4_historico,
                progress_callback=progress_callback,
                page_texts=page_texts,
            )
            if rows:
                layout_type = generic_profile.layout
                profile = generic_profile

        if discovery_enabled:
            seen_pages = 0
            for txt in page_texts:
                if not txt:
                    continue
                _collect_discovery_from_page(discovery_summary, txt)
                seen_pages += 1
            discovery_summary["pages_scanned"] = int(seen_pages)
            discovery_summary["detected_layout"] = detected_layout
            discovery_summary["effective_layout"] = layout_type
            discovery_summary["profile"] = {
                "layout": profile.layout,
                "detection_markers": list(profile.detection_markers),
                "reference_extractors": list(profile.reference_extractors),
                "uc_extractors": list(profile.uc_extractors),
                "categoria_extractors": list(profile.categoria_extractors),
                "itens_extractors": list(profile.itens_extractors),
                "kwh_extractors": list(profile.kwh_extractors),
                "historico_extractors": list(profile.historico_extractors),
                "demand_extractors": list(profile.demand_extractors),
            }

    for rec in rows:
        rec.provider_layout = layout_type
        rec.template = layout_type

    df = pd.DataFrame([asdict(r) for r in rows])
    out_df = _finalize_extracted_df(df)

    if discovery_enabled:
        all_text = "\n\n".join(txt for txt in page_texts if txt)
        sample_text = _sample_page_text(page_texts, max_pages=2)
        discovery_summary["rows_extracted"] = int(len(out_df))
        discovery_summary["field_extraction_report"] = _build_field_extraction_report(all_text, out_df)
        discovery_summary["unmatched_text_sample"] = sample_text[:2000]
        if not out_df.empty:
            discovery_summary["category_counts"] = (
                out_df.get("categoria", pd.Series(dtype=str))
                .astype(str)
                .value_counts(dropna=False)
                .to_dict()
            )
            discovery_summary["kwh_source_counts"] = (
                out_df.get("audit_kwh_source", pd.Series(dtype=str))
                .astype(str)
                .value_counts(dropna=False)
                .to_dict()
            )
        out_df.attrs["discovery_summary"] = discovery_summary
        _write_discovery_summary(pdf_source, discovery_summary)

    return out_df
