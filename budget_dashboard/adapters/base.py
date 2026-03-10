from __future__ import annotations

import unicodedata
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable

import pandas as pd


MONTH_MAP = {
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


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.lower().split())


def find_first_column(columns: Iterable[str], aliases: Iterable[str]) -> str | None:
    normalized_cols = {col: normalize_text(col) for col in columns}
    normalized_aliases = [normalize_text(alias) for alias in aliases]
    for alias in normalized_aliases:
        for col, col_norm in normalized_cols.items():
            if col_norm == alias or alias in col_norm:
                return col
    return None


def to_float_series(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    text = text.str.replace("R$", "", regex=False).str.replace("r$", "", regex=False)
    text = text.str.replace(" ", "", regex=False)

    comma_dot = text.str.contains(",", regex=False) & text.str.contains(".", regex=False)
    comma_only = text.str.contains(",", regex=False) & ~text.str.contains(".", regex=False)
    dot_before_comma = comma_dot & (text.str.rfind(",") > text.str.rfind("."))

    text = text.where(~dot_before_comma, text.str.replace(".", "", regex=False))
    text = text.where(~comma_dot, text.str.replace(",", ".", regex=False))
    text = text.where(~comma_only, text.str.replace(",", ".", regex=False))
    return pd.to_numeric(text, errors="coerce")


def parse_reference_date(value) -> pd.Timestamp:
    if value is None:
        return pd.NaT
    text = str(value).strip()
    if not text:
        return pd.NaT

    mm_yyyy = pd.to_datetime(text, format="%m/%Y", errors="coerce")
    if pd.notna(mm_yyyy):
        return mm_yyyy

    upper = text.upper()
    if len(upper) >= 7:
        for mon, mon_num in MONTH_MAP.items():
            if upper.startswith(f"{mon}/") or upper.startswith(f"{mon}-"):
                year = upper.split("/")[-1] if "/" in upper else upper.split("-")[-1]
                year = year[-4:] if len(year) >= 4 else f"20{year.zfill(2)}"
                return pd.to_datetime(f"{year}-{mon_num}-01", errors="coerce")

    return pd.to_datetime(text, errors="coerce", dayfirst=True)


class BaseAdapter(ABC):
    name = "base"
    description = "Base adapter interface"

    @abstractmethod
    def adapt(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Return DataFrame with standard schema used by budget pipeline.
        """
        raise NotImplementedError

    def _empty_standard_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "municipio",
                "uc",
                "consumer_class",
                "reference_date",
                "reference_month",
                "consumption_kwh",
                "demand_kw",
                "source_file",
                "adapter_name",
                "adapted_at",
            ]
        )

    def _stamp(self, df: pd.DataFrame) -> pd.DataFrame:
        local = df.copy()
        local["adapter_name"] = self.name
        local["adapted_at"] = datetime.now().isoformat()
        return local
