# extract_celesc_pvh.py
# Usage:
#   python extract_celesc_pvh.py <PDF_PATH> <OUT_PREFIX>
# Example:
#   python extract_celesc_pvh.py "Palhoça_Faturas-1.pdf" "palhoca_1"

from __future__ import annotations

import os
import re
import sys
import unicodedata
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict

import pandas as pd
import pdfplumber
from tqdm import tqdm


# -----------------------------
# Helpers
# -----------------------------
def normalize_whitespace(s: str) -> str:
    if not s:
        return ""
    # keep line breaks for some patterns, but squash excessive spaces
    s = s.replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n+", "\n", s)
    return s.strip()


def parse_ptbr_number(s: str) -> Optional[float]:
    """
    Converts Brazilian number formats safely:
      1.700,00 -> 1700.00
      1.700    -> 1700.00  (common in PDFs)
      1700     -> 1700.00
      742.835,781 -> 742835.781
    """
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None

    # Remove thousand separators then convert decimal comma to dot
    s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def yyyymm_to_ref(yyyymm: str) -> str:
    # "202511" -> "11/2025"
    yyyymm = re.sub(r"\D", "", yyyymm or "")
    if len(yyyymm) != 6:
        return ""
    yyyy = yyyymm[:4]
    mm = yyyymm[4:]
    return f"{mm}/{yyyy}"


def date_to_ref(ddmmyyyy: str) -> str:
    # "24/11/2025" -> "11/2025"
    m = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", ddmmyyyy or "")
    if not m:
        return ""
    mm = m.group(2)
    yyyy = m.group(3)
    return f"{mm}/{yyyy}"

def extract_page_default_ref(page_text: str) -> str:
    """
    Try to get the month reference for the whole page.
    Priority:
      1) 'Referência: MM/AAAA'
      2) 'Fatura: YYYYMM-...'
      3) 'Data Faturamento: DD/MM/AAAA'
    """
    t = normalize_whitespace(page_text or "")

    m = RE_REF.search(t)
    if m:
        return m.group(1)

    m = RE_FATURA_YYYYMM.search(t)
    if m:
        return yyyymm_to_ref(m.group(1))

    m = RE_DATA_FAT.search(t)
    if m:
        return date_to_ref(m.group(1))

    return ""

# -----------------------------
# Regex
# -----------------------------
RE_UC = re.compile(r"\bUC:\s*([0-9]{6,12})\b", re.IGNORECASE)

def normalize_uc(uc_digits: str, target_len: int = 10) -> str:
    uc_digits = re.sub(r"\D", "", uc_digits or "")
    if not uc_digits:
        return ""
    # If UC is shorter than target, pad left with zeros (keeps UC identity stable)
    if len(uc_digits) < target_len:
        return uc_digits.zfill(target_len)
    return uc_digits

# Reference (most bills show "Referência: 11/2024" somewhere; adjust if needed)
RE_REF = re.compile(r"\bRefer[êe]ncia:\s*(\d{2}/\d{4})\b", re.IGNORECASE)

# "Fatura: 202511-070356859" => use 202511 as month/year
RE_FATURA_YYYYMM = re.compile(r"\bFatura:\s*(\d{6})[-/]\d+\b", re.IGNORECASE)

# "Data Faturamento: 24/11/2025" => derive 11/2025
RE_DATA_FAT = re.compile(r"\bData\s*Faturamento:\s*(\d{2}/\d{2}/\d{4})\b", re.IGNORECASE)

# "Grupo / Subgrupo Tensão:B-B4A"
RE_GRUPO = re.compile(r"\bGrupo\s*/\s*Subgrupo\s*Tens[aã]o:\s*([AB])\s*-\s*([A-Z0-9]+)\b", re.IGNORECASE)

# "Classificação / Modalidade Tarifária / Tipo de Fornecimento:...."
RE_CLASSIF = re.compile(r"\bClassifica[cç][aã]o\s*/\s*Modalidade\s*Tarif[aá]ria\s*/\s*Tipo\s*de\s*Fornecimento:\s*(.+?)\bMunic[ií]pio:", re.IGNORECASE | re.DOTALL)

RE_ORIGEM = re.compile(r"\bOrigem:\s*([A-Za-zÀ-ÿ ]{0,40})\b", re.IGNORECASE)

RE_NOME = re.compile(r"\bNome:\s*(.+?)\bEndere[cç]o:", re.IGNORECASE | re.DOTALL)
RE_END = re.compile(r"\bEndere[cç]o:\s*(.+?)\bEtapa:", re.IGNORECASE | re.DOTALL)

# Fallback patterns for Nome / Endereço (when Etapa: or other markers are missing)
RE_NOME_FALLBACK = re.compile(
    r"\bNome:\s*(.+?)(?:\bEndere[cç]o:|\bMunic[ií]pio:|\bOrigem:|\bGrupo\s*/\s*Subgrupo|\bClassifica|$)",
    re.IGNORECASE | re.DOTALL
)

RE_END_FALLBACK = re.compile(
    r"\bEndere[cç]o:\s*(.+?)(?:\bEtapa:|\bMunic[ií]pio:|\bOrigem:|\bGrupo\s*/\s*Subgrupo|\bClassifica|$)",
    re.IGNORECASE | re.DOTALL
)


# B3/IP energy patterns
RE_CONS_TE = re.compile(r"\bConsumo\s*TE\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)

RE_CONS_IP_TE = re.compile(r"\bConsumo\s+IP\s+TE\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)
# Broken line variants: "Consumo IP\nTE 742.835,781"
RE_CONS_IP_GENERIC = re.compile(r"\bConsumo\s+IP\b[\s\S]{0,60}?\bTE\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)

# Some pages show "Energia TE <num>"
RE_ENERGIA_TE = re.compile(r"\bEnergia\s*TE\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)

# Sometimes only the measured section exists:
RE_ENERGIA_UNICO_APURADO = re.compile(
    r"\bEnergia\s+Único\b.*?\bApurado\b\s+([0-9\.\,]+)\b", re.IGNORECASE | re.DOTALL
)

# Generic kWh fallback
RE_KWH_GENERIC = re.compile(r"\bkWh\b\s*([0-9\.\,]+)\b", re.IGNORECASE)
RE_KWH_BROKEN  = re.compile(r"\bkW\s*h\b\s*([0-9\.\,]+)\b", re.IGNORECASE)

# A4 energy
RE_A4_FP_TE = re.compile(r"\bConsumo\s*Fora\s*Ponta\s*TE\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)
RE_A4_P_TE  = re.compile(r"\bConsumo\s*Ponta\s*TE\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)

# Optional demand (if you use later)
RE_DEMANDA_ITEM = re.compile(r"\bDemanda\b[\s\S]{0,40}?\bQuantidade\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)
RE_DIF_DEMANDA  = re.compile(r"\bDiferen[cç]a\s+da\s+Demanda\s+Contratad[aã]\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)


# -----------------------------
# Data model
# -----------------------------
@dataclass
class UCMonthRecord:
    uc: str
    referencia: str
    grupo_tensao: str
    subgrupo: str
    categoria: str
    tipo_fornecimento: str
    origem: str
    nome: str
    endereco: str

    # Energy (kWh)
    kwh_b3_ip: Optional[float] = None
    kwh_a4_fp_te: Optional[float] = None
    kwh_a4_p_te: Optional[float] = None
    kwh_total_te: Optional[float] = None  # A4: fp+p; B3/IP: TE (or fallback)

    # Optional (economics)
    demanda_item: Optional[float] = None
    dif_demanda: Optional[float] = None

    # Trace
    pdf_source: str = ""
    page_first_seen: int = -1


# -----------------------------
# Categorization / block split / tipo
# -----------------------------
def categorize(grupo_tensao: str, subgrupo: str, classif_line: str) -> str:
    sub = (subgrupo or "").upper().strip()
    cls = (classif_line or "").upper()

    # A4
    if (grupo_tensao or "").upper() == "A" and sub == "A4":
        return "A4"

    # Explicit iluminação pública
    if "ILUMINAÇÃO PÚBLICA" in cls or "ILUMINACAO PUBLICA" in cls:
        return "IP"

    # Often IP is B4A/B4B
    if (grupo_tensao or "").upper() == "B" and sub in {"B4A", "B4B"}:
        return "IP"

    if (grupo_tensao or "").upper() == "B" and sub == "B3":
        return "B3"

    return "OUTROS"


def split_into_uc_blocks(page_text: str) -> List[str]:
    """
    Split a page into segments starting at each 'UC:' occurrence.
    """
    text = normalize_whitespace(page_text)
    starts = [m.start() for m in RE_UC.finditer(text)]
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


# -----------------------------
# Extraction from a UC block
# -----------------------------
def extract_from_uc_block(
    block_text: str,
    page_index: int,
    pdf_source: str,
    default_ref: str = "",
) -> Optional[UCMonthRecord]:
    t = normalize_whitespace(block_text)

    m_uc = RE_UC.search(t)
    if not m_uc:
        return None

    # Normalize UC to fixed length (Celesc commonly 10 digits)
    uc = normalize_uc(m_uc.group(1), target_len=10)

    # Reference: inside block, else page header default, else Fatura YYYYMM, else Data Faturamento
    m_ref = RE_REF.search(t)
    referencia = m_ref.group(1) if m_ref else default_ref

    if not referencia:
        m_fat = RE_FATURA_YYYYMM.search(t)
        if m_fat:
            referencia = yyyymm_to_ref(m_fat.group(1))

    if not referencia:
        m_df = RE_DATA_FAT.search(t)
        if m_df:
            referencia = date_to_ref(m_df.group(1))

    # Group
    m_gr = RE_GRUPO.search(t)
    grupo_tensao = m_gr.group(1).upper() if m_gr else ""
    subgrupo = m_gr.group(2).upper() if m_gr else ""

    # Classif + origem
    m_cls = RE_CLASSIF.search(t)
    classif_line = m_cls.group(1).strip() if m_cls else ""

    tipo_fornecimento = extract_tipo_fornecimento(classif_line)
    if not tipo_fornecimento:
        tipo_fornecimento = extract_tipo_fornecimento(t)

    m_or = RE_ORIGEM.search(t)
    origem = m_or.group(1).strip() if m_or else ""

    # Nome / Endereço (with fallbacks)
    nome = ""
    endereco = ""

    m_nome = RE_NOME.search(t) or RE_NOME_FALLBACK.search(t)
    if m_nome:
        nome = m_nome.group(1).split("\n")[0].strip()
        nome = nome.replace("Endereço:", "").replace("Endereco:", "").strip()

    m_end = RE_END.search(t) or RE_END_FALLBACK.search(t)
    if m_end:
        endereco = m_end.group(1).split("\n")[0].strip()
        endereco = endereco.replace("Etapa:", "").strip()

    categoria = categorize(grupo_tensao, subgrupo, classif_line)

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
        pdf_source=pdf_source,
        page_first_seen=page_index + 1,  # 1-based for humans
    )

    # -------------------------
    # Energy extraction rules
    # -------------------------

    # A4 = Fora Ponta TE + Ponta TE
    if categoria == "A4":
        m_fp = RE_A4_FP_TE.search(t)
        m_p  = RE_A4_P_TE.search(t)

        if m_fp:
            rec.kwh_a4_fp_te = parse_ptbr_number(m_fp.group(1))
        if m_p:
            rec.kwh_a4_p_te = parse_ptbr_number(m_p.group(1))

        fp = rec.kwh_a4_fp_te if rec.kwh_a4_fp_te is not None else 0.0
        p  = rec.kwh_a4_p_te  if rec.kwh_a4_p_te  is not None else 0.0

        if (rec.kwh_a4_fp_te is not None) or (rec.kwh_a4_p_te is not None):
            rec.kwh_total_te = fp + p

        # Optional demand (if present)
        m_dem = RE_DEMANDA_ITEM.search(t)
        if m_dem:
            rec.demanda_item = parse_ptbr_number(m_dem.group(1))
        m_dif = RE_DIF_DEMANDA.search(t)
        if m_dif:
            rec.dif_demanda = parse_ptbr_number(m_dif.group(1))

        return rec

    # B3/IP = Consumo TE (or Consumo IP TE) with fallbacks
    if categoria in {"B3", "IP"}:
        m_te = RE_CONS_IP_TE.search(t)
        if not m_te:
            m_te = RE_CONS_IP_GENERIC.search(t)
        if not m_te:
            m_te = RE_CONS_TE.search(t)
        if not m_te:
            m_te = RE_ENERGIA_TE.search(t)

        if m_te:
            rec.kwh_b3_ip = parse_ptbr_number(m_te.group(1))
            rec.kwh_total_te = rec.kwh_b3_ip
        else:
            m_ap = RE_ENERGIA_UNICO_APURADO.search(t)
            if m_ap:
                rec.kwh_b3_ip = parse_ptbr_number(m_ap.group(1))
                rec.kwh_total_te = rec.kwh_b3_ip

        # Fallback: generic kWh patterns
        if rec.kwh_total_te is None:
            m_kwh = RE_KWH_GENERIC.search(t)
            if not m_kwh:
                m_kwh = RE_KWH_BROKEN.search(t)
            if m_kwh:
                rec.kwh_b3_ip = parse_ptbr_number(m_kwh.group(1))
                rec.kwh_total_te = rec.kwh_b3_ip

        # Optional demand fields
        m_dem = RE_DEMANDA_ITEM.search(t)
        if m_dem:
            rec.demanda_item = parse_ptbr_number(m_dem.group(1))
        m_dif = RE_DIF_DEMANDA.search(t)
        if m_dif:
            rec.dif_demanda = parse_ptbr_number(m_dif.group(1))

        return rec

    # OUTROS: still return record (no kWh)
    return rec


# -----------------------------
# PDF Extraction
# -----------------------------
def extract_pdf(pdf_path: str) -> pd.DataFrame:
    pdf_source = os.path.basename(pdf_path)

    rows: List[UCMonthRecord] = []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(tqdm(pdf.pages, desc="Reading pages")):
            txt = page.extract_text() or ""
            if "UC:" not in txt:
                continue

            default_ref = extract_page_default_ref(txt)

            blocks = split_into_uc_blocks(txt)
            for block_text in blocks:
                rec = extract_from_uc_block(block_text, i, pdf_source, default_ref=default_ref)

                if rec is None:
                    continue
                # Some blocks might have no reference at all; keep but warn later
                rows.append(rec)

    df = pd.DataFrame([asdict(r) for r in rows])

    # Normalize UC string and reference formatting
    if "uc" in df.columns:
        df["uc"] = df["uc"].astype(str)

    return df


def build_uc_x_mes(df: pd.DataFrame, out_xlsx: str) -> None:
    """
    Builds a matrix UC x Referência with kwh_total_te as values.
    """
    if df.empty:
        pd.DataFrame().to_excel(out_xlsx, index=False)
        return

    temp = df.copy()

        # Ensure UC remains string (preserve leading zeros)
    if "uc" in temp.columns:
        temp["uc"] = temp["uc"].astype(str)


    # Keep only the columns we need
    # If there are duplicates for same UC + month, sum is safe.
    pivot = temp.pivot_table(
        index=["nome", "endereco", "uc", "categoria", "tipo_fornecimento", "pdf_source"],
        columns="referencia",
        values="kwh_total_te",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()

    pivot.to_excel(out_xlsx, index=False)


def build_audit_pdf_pages(df: pd.DataFrame) -> pd.DataFrame:
    """
    Creates an audit trail per UC:
      audit_pdf_pages = "file1.pdf: 1, 10 | file2.pdf: 3"
    Uses pdf_source + page_first_seen.
    """
    if df.empty:
        return df

    temp = df.copy()

    # Ensure types
    temp["uc"] = temp["uc"].astype(str)
    temp["pdf_source"] = temp["pdf_source"].astype(str)
    temp["page_first_seen"] = pd.to_numeric(temp["page_first_seen"], errors="coerce")

    # Keep only valid pages
    temp = temp.dropna(subset=["page_first_seen"])
    temp["page_first_seen"] = temp["page_first_seen"].astype(int)

    # Unique (UC, PDF, Page)
    temp = temp[["uc", "pdf_source", "page_first_seen"]].drop_duplicates()

    # Sort for clean formatting
    temp = temp.sort_values(["uc", "pdf_source", "page_first_seen"])

    def fmt_group(g: pd.DataFrame) -> str:
        parts = []
        for pdf, gg in g.groupby("pdf_source", sort=True):
            pages = gg["page_first_seen"].tolist()
            pages_str = ", ".join(str(p) for p in pages)
            parts.append(f"{pdf}: {pages_str}")
        return " | ".join(parts)

    audit = temp.groupby("uc", as_index=False).apply(fmt_group)
    audit = audit.rename(columns={None: "audit_pdf_pages"})

    return audit


def main(pdf_path: str, out_prefix: str) -> None:
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    df = extract_pdf(pdf_path)
    
    # Build audit trail: PDF + pages per UC
    audit_df = build_audit_pdf_pages(df)
    df = df.merge(audit_df, on="uc", how="left")

    # Ensure UC is always stored as string (preserve leading zeros)
    if "uc" in df.columns:
        df["uc"] = df["uc"].astype(str)

    # Stats + warnings
    rows = len(df)
    missing_ref = int(df["referencia"].isna().sum()) if "referencia" in df.columns else 0
    blank_kwh = int(df["kwh_total_te"].isna().sum()) if "kwh_total_te" in df.columns else 0

    # Categoria counts
    cat_counts = df["categoria"].value_counts(dropna=False) if "categoria" in df.columns else pd.Series()

    if missing_ref:
        print(f"WARNING: {missing_ref} rows without 'referencia' (MM/AAAA).")
    if blank_kwh:
        print(f"WARNING: {blank_kwh} rows without kWh total (kwh_total_te).")

    out_csv = f"{out_prefix}.csv"
    out_tsv = f"{out_prefix}.tsv"
    out_xlsx = f"{out_prefix}_uc_x_mes.xlsx"

    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    df.to_csv(out_tsv, sep="\t", index=False, encoding="utf-8-sig")
    build_uc_x_mes(df, out_xlsx)

    print(f"Saved: {out_csv}, {out_tsv}, {out_xlsx}")
    print(f"rows= {rows}")
    print(f"missing_ref= {missing_ref}")
    print(f"blank_kwh= {blank_kwh}")
    if len(cat_counts):
        print("categoria")
        print(cat_counts.to_string())


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage:\n  python extract_celesc_pvh.py <PDF_PATH> <OUT_PREFIX>")
        print("Example:\n  python extract_celesc_pvh.py 'Palhoça_Faturas-1.pdf' 'palhoca_1'")
        sys.exit(1)

    main(sys.argv[1], sys.argv[2])
