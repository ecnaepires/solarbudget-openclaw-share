import re

# UC (keep digits; do NOT strip leading zeros here)
RE_UC = re.compile(r"\bUC:\s*([0-9]{6,12})\b", re.IGNORECASE)
RE_INSTALACAO = re.compile(r"\bInstala[cç][aã]o:\s*([0-9]{6,12})\b", re.IGNORECASE)
RE_UNIDADE_CONSUMIDORA = re.compile(r"\bUnidade\s+Consumidora:\s*([0-9]{6,12})\b", re.IGNORECASE)
RE_NUMERO_CLIENTE = re.compile(r"\bN[uú]mero\s+(?:do\s+)?Cliente:\s*([0-9]{6,12})\b", re.IGNORECASE)

# Reference
RE_REF = re.compile(r"\bRefer[êe]ncia:\s*(\d{2}/\d{4})\b", re.IGNORECASE)
RE_MES_ANO = re.compile(r"\bM[eê]s/Ano:\s*(\d{2}/\d{4})\b", re.IGNORECASE)
RE_PERIODO_REF = re.compile(
    r"\bPer[ií]odo\s*(?:de\s*)?Refer[eê]ncia:\s*(\d{2}/\d{4})\b",
    re.IGNORECASE,
)

# "Fatura: 202511-070356859" => use 202511
RE_FATURA_YYYYMM = re.compile(r"\bFatura:\s*(\d{6})[-/]\d+\b", re.IGNORECASE)

# "Data Faturamento: 24/11/2025" => derive 11/2025
RE_DATA_FAT = re.compile(r"\bData\s*Faturamento:\s*(\d{2}/\d{2}/\d{4})\b", re.IGNORECASE)

# "Grupo / Subgrupo Tensão:B-B4A"
RE_GRUPO = re.compile(
    r"\bGrupo\s*/\s*Subgrupo\s*Tens[aã]o:\s*([AB])\s*-\s*([A-Z0-9]+)\b",
    re.IGNORECASE,
)

# "Classificação / Modalidade Tarifária / Tipo de Fornecimento:.... Município:"
RE_CLASSIF = re.compile(
    r"\bClassifica[cç][aã]o\s*/\s*Modalidade\s*Tarif[aá]ria\s*/\s*Tipo\s*de\s*Fornecimento:\s*(.+?)\bMunic[ií]pio:",
    re.IGNORECASE | re.DOTALL,
)

RE_ORIGEM = re.compile(r"\bOrigem:\s*([A-Za-zÀ-ÿ ]{0,40})\b", re.IGNORECASE)

RE_NOME = re.compile(r"\bNome:\s*(.+?)\bEndere[cç]o:", re.IGNORECASE | re.DOTALL)
RE_END = re.compile(r"\bEndere[cç]o:\s*(.+?)\bEtapa:", re.IGNORECASE | re.DOTALL)

# Fallback patterns for Nome / Endereço
RE_NOME_FALLBACK = re.compile(
    r"\bNome:\s*(.+?)(?:\bEndere[cç]o:|\bMunic[ií]pio:|\bOrigem:|\bGrupo\s*/\s*Subgrupo|\bClassifica|$)",
    re.IGNORECASE | re.DOTALL,
)

RE_END_FALLBACK = re.compile(
    r"\bEndere[cç]o:\s*(.+?)(?:\bEtapa:|\bMunic[ií]pio:|\bOrigem:|\bGrupo\s*/\s*Subgrupo|\bClassifica|$)",
    re.IGNORECASE | re.DOTALL,
)

# B3/IP energy patterns
RE_CONS_TE = re.compile(r"\bConsumo\s*TE\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)
RE_CONS_IP_TE = re.compile(r"\bConsumo\s+IP\s+TE\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)
RE_CONS_IP_GENERIC = re.compile(r"\bConsumo\s+IP\b[\s\S]{0,60}?\bTE\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)
RE_ENERGIA_TE = re.compile(r"\bEnergia\s*TE\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)
RE_ENERGIA_ATIVA = re.compile(r"\bEnergia\s+Ativa\b[\s:]+([0-9\.\,]+)", re.IGNORECASE)
RE_ENERGIA_ELETRICA = re.compile(r"\bEnergia\s+El[eé]trica\b[\s:]+([0-9\.\,]+)", re.IGNORECASE)
RE_CONSUMO_KWH = re.compile(r"\bConsumo\s*\(?kWh\)?\s*:?\s*([0-9\.\,]+)", re.IGNORECASE)

# --- Itens da Fatura: Consumo TE/TUSD rows (Quantidade is the FIRST numeric after the label) ---
# Matches examples like:
#   "Consumo TE 267 0,1234 32,91"
#   "Consumo TE kWh 267 0,1234 32,91"
RE_ITEM_CONSUMO_TE_QTD = re.compile(
    r"\bCONSUMO\s+TE\b(?:\s+[A-Z/%()\-]+){0,3}\s+([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]+(?:,[0-9]+)?)\b",
    re.IGNORECASE,
)

RE_ITEM_CONSUMO_TUSD_QTD = re.compile(
    r"\bCONSUMO\s+TUSD\b(?:\s+[A-Z/%()\-]+){0,3}\s+([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]+(?:,[0-9]+)?)\b",
    re.IGNORECASE,
)

# IP variants commonly used
RE_ITEM_CONSUMO_IP_TE_QTD = re.compile(
    r"\bCONSUMO\s+IP\s+TE\b(?:\s+[A-Z/%()\-]+){0,3}\s+([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]+(?:,[0-9]+)?)\b",
    re.IGNORECASE,
)

# Some CELESC layouts use "Energia Único" in Itens
RE_ITEM_ENERGIA_UNICO_QTD = re.compile(
    r"\bENERGIA\s+UNICO\b(?:\s+[A-Z/%()\-]+){0,3}\s+([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]+(?:,[0-9]+)?)\b",
    re.IGNORECASE,
)

# Optional A4 itens-table helpers
RE_ITEM_CONSUMO_FORA_PONTA_TE_QTD = re.compile(
    r"\bCONSUMO\s+(?:HORARIA\s+)?FORA\s+PONTA\s+TE\b(?:\s+[A-Z/%()\-]+){0,3}\s+([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]+(?:,[0-9]+)?)\b",
    re.IGNORECASE,
)

RE_ITEM_CONSUMO_PONTA_TE_QTD = re.compile(
    r"\bCONSUMO\s+PONTA\s+TE\b(?:\s+[A-Z/%()\-]+){0,3}\s+([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]+(?:,[0-9]+)?)\b",
    re.IGNORECASE,
)

RE_ENERGIA_UNICO_APURADO = re.compile(
    r"\bEnergia\s+Único\b.*?\bApurado\b\s+([0-9\.\,]+)\b",
    re.IGNORECASE | re.DOTALL,
)

RE_KWH_GENERIC = re.compile(r"\bkWh\b\s*([0-9\.\,]+)\b", re.IGNORECASE)
RE_KWH_BROKEN = re.compile(r"\bkW\s*h\b\s*([0-9\.\,]+)\b", re.IGNORECASE)

# A4 energy
RE_A4_FP_TE = re.compile(r"\bConsumo\s*Fora\s*Ponta\s*TE\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)
RE_A4_P_TE = re.compile(r"\bConsumo\s*Ponta\s*TE\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)

# Optional demand
RE_DEMANDA_ITEM = re.compile(r"\bDemanda\b[\s\S]{0,40}?\bQuantidade\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)
RE_DIF_DEMANDA = re.compile(r"\bDiferen[cç]a\s+da\s+Demanda\s+Contratad[aã]\b[\s:]+([0-9\.\,]+)\b", re.IGNORECASE)
RE_DEMANDA_CONTRATADA = re.compile(r"\bDemanda\s+Contratada\b[\s:]+([0-9\.\,]+)", re.IGNORECASE)
RE_DEMANDA_REGISTRADA = re.compile(r"\bDemanda\s+Registrada\b[\s:]+([0-9\.\,]+)", re.IGNORECASE)
RE_DEMANDA_MEDIDA = re.compile(r"\bDemanda\s+Medida\b[\s:]+([0-9\.\,]+)", re.IGNORECASE)

# Consumer class alternatives
RE_SUBGRUPO = re.compile(r"\bSubgrupo:\s*([AB]\d[A-Za-z]?)\b", re.IGNORECASE)
RE_CLASSE_CONSUMO = re.compile(r"\bClasse\s+(?:de\s+)?Consumo:\s*(.+?)(?:\n|$)", re.IGNORECASE)
RE_MODALIDADE = re.compile(r"\bModalidade\s+Tarif[aá]ria:\s*(.+?)(?:\n|$)", re.IGNORECASE)

# Monetary totals
RE_VALOR_BLOCO_RS = re.compile(r"\bValor:\s*R\$\s*([0-9][0-9\.\,]*)\b", re.IGNORECASE)
RE_TOTAL_A_PAGAR_RS = re.compile(
    r"\bTotal\s+a\s+Pagar(?:\s*\(R\$\))?\s*:?\s*R?\$?\s*([0-9][0-9\.\,]*)\b",
    re.IGNORECASE,
)
RE_VALOR_TOTAL = re.compile(r"\bValor\s+Total\s*:?\s*R\$\s*([0-9\.\,]+)", re.IGNORECASE)
RE_TOTAL_FATURA = re.compile(r"\bTotal\s+(?:da\s+)?Fatura\s*:?\s*R\$\s*([0-9\.\,]+)", re.IGNORECASE)
