import re
import unicodedata
from typing import Optional


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


def normalize_uc(uc_digits: str, target_len: int = 10) -> str:
    """
    UC is an identifier, not a number. Keep leading zeros stable.
    """
    uc_digits = re.sub(r"\D", "", uc_digits or "")
    if not uc_digits:
        return ""
    if len(uc_digits) < target_len:
        return uc_digits.zfill(target_len)
    return uc_digits


def normalize_reference_token(value: str) -> str:
    """
    Normalize multiple month reference formats to MM/YYYY.

    Supported examples:
      01/2025, 1/25, JAN/2025, JAN25, JAN-25, 202501
    """
    if value is None:
        return ""

    raw = str(value).strip()
    if not raw:
        return ""

    token = unicodedata.normalize("NFKD", raw).encode("ASCII", "ignore").decode("ASCII")
    token = re.sub(r"\s+", "", token.upper())

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

    def normalize_year(year_raw: str) -> str:
        year = re.sub(r"\D", "", year_raw or "")
        if len(year) == 2:
            return "20" + year
        if len(year) == 4:
            return year
        return ""

    m_num = re.match(r"^(0?[1-9]|1[0-2])[/-](\d{2,4})$", token)
    if m_num:
        mm = str(int(m_num.group(1))).zfill(2)
        yyyy = normalize_year(m_num.group(2))
        return f"{mm}/{yyyy}" if yyyy else ""

    m_mon = re.match(r"^(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)[/-]?(\d{2,4})$", token)
    if m_mon:
        mm = month_map.get(m_mon.group(1), "")
        yyyy = normalize_year(m_mon.group(2))
        return f"{mm}/{yyyy}" if mm and yyyy else ""

    m_yyyymm = re.match(r"^(\d{4})(0[1-9]|1[0-2])$", token)
    if m_yyyymm:
        return f"{m_yyyymm.group(2)}/{m_yyyymm.group(1)}"

    return ""
