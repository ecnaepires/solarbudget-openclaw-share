import re
import os
import unicodedata
from pathlib import Path

import pdfplumber
import pandas as pd

import gspread
from google.oauth2.service_account import Credentials

# =========================
# CONFIG (EDIT THESE)
# =========================
BASE_DIR = Path(__file__).resolve().parent
PDF_PATH = str(BASE_DIR / "PalhoÃ§a_Faturas-2.pdf")
CREDS_PATH = str(BASE_DIR / "credentials.json")

SPREADSHEET_ID = "18oIOyTvWeIwPToM8-O0vBA8UMXFToJ5zTi3-5bSLnt4"

TAB_B3 = "B3_Faturas"
TAB_A4 = "A4_Faturas"


# =========================
# HELPERS (TEXT)
# =========================
def split_uc_blocks(text: str):
    parts = re.split(r"\bUC:\s*", text)
    return ["UC: " + p.strip() for p in parts[1:]]

def find_first(pattern: str, text: str) -> str:
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""

def clean_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def norm(s: str) -> str:
    """Uppercase + remove accents + collapse whitespace."""
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s

def build_fuzzy_label_regex(label: str) -> str:
    """Match labels even if PDF breaks lines/spaces between words."""
    words = norm(label).split(" ")
    words = [re.escape(w) for w in words if w]
    return r"\b" + r"\s+".join(words) + r"\b"

def find_item_qty(block_text: str, labels: list[str]) -> str:
    """
    Finds the first number after any label (whitespace flexible, accent-insensitive).
    Example: 'CONSUMO TE 874 0,36503 ...' -> returns '874'
    """
    txt = norm(block_text)
    for label in labels:
        label_rx = build_fuzzy_label_regex(label)
        rx = label_rx + r"\s+([0-9][0-9\.,]*)"
        m = re.search(rx, txt, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""

def ensure_worksheet(sh, title: str, rows: int = 2000, cols: int = 30):
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=rows, cols=cols)

def write_df_to_worksheet(ws, df: pd.DataFrame):
    ws.clear()
    values = [df.columns.tolist()] + df.astype(str).values.tolist()
    ws.resize(rows=len(values), cols=len(df.columns))
    ws.update(values)


# =========================
# EXTRACT FROM PDF (B3 + A4)
# =========================
def extract_from_pdf(pdf_path: str):
    pdf_name = os.path.basename(pdf_path)

    b3_rows = []
    a4_rows = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            blocks = split_uc_blocks(text)

            for b in blocks:
                # Shared fields
                nome = clean_spaces(find_first(r"\bNome:\s*(.+?)(?:\n|EndereÃ§o:|$)", b))
                endereco = clean_spaces(find_first(r"EndereÃ§o:\s*(.+?)(?:Etapa:|Chave de Acesso:|ClassificaÃ§Ã£o|$)", b))
                uc = find_first(r"UC:\s*([0-9]{6,12})", b)
                grupo_subgrupo = clean_spaces(find_first(r"Grupo\s*/\s*Subgrupo\s*TensÃ£o:\s*([A-Z0-9\-\s]+)", b))
                nb = norm(b)
                if ("TRIFASICO" in nb) or ("TRIFASIC" in nb):
                    tipo_fornecimento = "TRIFÃSICO"
                elif ("BIFASICO" in nb) or ("BIFASIC" in nb):
                    tipo_fornecimento = "BIFÃSICO"
                elif ("MONOFASICO" in nb) or ("MONOFASIC" in nb):
                    tipo_fornecimento = "MONOFÃSICO"
                else:
                    tipo_fornecimento = ""

                # A4 fields (robust label variants)
                demanda_kw = find_item_qty(b, [
                    "Demanda",
                    "Demanda Contratada",
                    "Demanda Medida",
                    "Demanda kW",
                ])

                ultrapassagem_kw = find_item_qty(b, [
                    "Ultrapassagem",
                    "Ultrapassagem Demanda",
                    "DiferenÃ§a da Demanda Contratada",
                    "Diferenca da Demanda Contratada",
                    "DiferenÃ§a da Demanda Contratad",
                    "Diferenca da Demanda Contratad",
                ])

                consumo_te_ponta = find_item_qty(b, [
                    "Consumo TE Ponta",
                    "Consumo Ponta TE",
                    "Consumo na Ponta",
                    "Consumo Ponta",
                ])

                consumo_te_fora = find_item_qty(b, [
                    "Consumo TE Fora Ponta",
                    "Consumo Fora Ponta TE",
                    "Consumo Fora da Ponta",
                    "Consumo Fora Ponta",
                ])

                # B3 field
                consumo_te_b3 = find_item_qty(b, ["Consumo TE"])

                # Decide A4 vs B3
                is_a4 = ("A4" in norm(b)) or any([demanda_kw, ultrapassagem_kw, consumo_te_ponta, consumo_te_fora])

                if is_a4:
                    a4_rows.append({
                        "Nome": nome,
                        "EndereÃ§o": endereco,
                        "UC": uc,
                        "Grupo/Subgrupo": grupo_subgrupo,
                        "Tipo de Fornecimento": tipo_fornecimento,
                        "Demanda (kW)": demanda_kw,
                        "Ultrapassagem/DiferenÃ§a (kW)": ultrapassagem_kw,
                        "Consumo TE Ponta (kWh)": consumo_te_ponta,
                        "Consumo TE Fora Ponta (kWh)": consumo_te_fora,
                        "PDF": pdf_name
                    })
                else:
                    b3_rows.append({
                        "Nome": nome,
                        "EndereÃ§o": endereco,
                        "UC": uc,
                        "Grupo/Subgrupo": grupo_subgrupo,
                        "Tipo de Fornecimento": tipo_fornecimento,
                        "Consumo TE (kWh)": consumo_te_b3,
                        "PDF": pdf_name
                    })

    df_b3 = pd.DataFrame(b3_rows)
    df_a4 = pd.DataFrame(a4_rows)

    # Enforce column order
    if not df_b3.empty:
        df_b3 = df_b3[["Nome", "EndereÃ§o", "UC", "Grupo/Subgrupo", "Tipo de Fornecimento", "Consumo TE (kWh)", "PDF"]]
    else:
        df_b3 = pd.DataFrame(columns=["Nome", "EndereÃ§o", "UC", "Grupo/Subgrupo", "Tipo de Fornecimento", "Consumo TE (kWh)", "PDF"])

    if not df_a4.empty:
        df_a4 = df_a4[[
            "Nome", "EndereÃ§o", "UC", "Grupo/Subgrupo", "Tipo de Fornecimento",
            "Demanda (kW)", "Ultrapassagem/DiferenÃ§a (kW)", "Consumo TE Ponta (kWh)", "Consumo TE Fora Ponta (kWh)",
            "PDF"
        ]]
    else:
        df_a4 = pd.DataFrame(columns=[
            "Nome", "EndereÃ§o", "UC", "Grupo/Subgrupo", "Tipo de Fornecimento",
            "Demanda (kW)", "Ultrapassagem/DiferenÃ§a (kW)", "Consumo TE Ponta (kWh)", "Consumo TE Fora Ponta (kWh)",
            "PDF"
        ])

    return df_b3, df_a4


# =========================
# UPLOAD BOTH TABS
# =========================
def upload_two_tabs(df_b3: pd.DataFrame, df_a4: pd.DataFrame):
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=scope)
    client = gspread.authorize(creds)

    sh = client.open_by_key(SPREADSHEET_ID)

    ws_b3 = ensure_worksheet(sh, TAB_B3)
    write_df_to_worksheet(ws_b3, df_b3)

    ws_a4 = ensure_worksheet(sh, TAB_A4)
    write_df_to_worksheet(ws_a4, df_a4)

    return sh.url


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    if not os.path.exists(PDF_PATH):
        raise FileNotFoundError(f"PDF not found: {PDF_PATH}")

    if not os.path.exists(CREDS_PATH):
        raise FileNotFoundError(f"credentials.json not found: {CREDS_PATH}")

    df_b3, df_a4 = extract_from_pdf(PDF_PATH)
    url = upload_two_tabs(df_b3, df_a4)

    print("Uploaded successfully to Google Sheets (auto-separated tabs):")
    print(url)
    print(f"B3 rows: {len(df_b3)} | A4 rows: {len(df_a4)}")
