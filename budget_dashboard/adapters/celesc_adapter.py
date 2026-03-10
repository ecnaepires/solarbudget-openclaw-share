from __future__ import annotations

import pandas as pd

from .base import BaseAdapter, find_first_column, normalize_text, parse_reference_date, to_float_series


def _map_consumer_class(value: str) -> str:
    text = normalize_text(value)
    if not text:
        return "OUTROS"

    if text == "ip" or "iluminacao publica" in text or text.startswith("ip "):
        return "IP"
    if "a4" in text or "grupo a" in text or "alta tensao" in text or "mt" in text:
        return "A4"
    if "b3" in text or "grupo b" in text or "comercial" in text:
        return "B3"
    return "OUTROS"


class CelescAdapter(BaseAdapter):
    name = "celesc"
    description = "Adapter para contrato padrao a partir de outputs da extracao CELESC."

    def adapt(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return self._empty_standard_df()

        local = df.copy()
        columns = list(local.columns)

        municipio_col = find_first_column(columns, ["municipio", "municÃ­pio", "cidade"])
        uc_col = find_first_column(
            columns,
            ["uc", "unidade consumidora", "unidade_consumidora", "instalacao", "numero uc"],
        )
        class_col = find_first_column(
            columns,
            [
                "classe",
                "subclasse",
                "grupo tarifario",
                "grupo_tarifario",
                "subgrupo",
                "modalidade tarifaria",
                "tipo cliente",
            ],
        )
        reference_col = find_first_column(
            columns,
            ["reference_date", "data_referencia", "referencia", "competencia", "mes referencia"],
        )
        kwh_col = find_first_column(
            columns,
            ["kwh_total_te", "itens_fatura_energia_kwh", "consumo_kwh", "energia_kwh", "kwh"],
        )
        demand_col = find_first_column(
            columns,
            ["demanda_kw", "demanda registrada", "demanda faturada", "demanda", "kw"],
        )
        source_col = find_first_column(columns, ["source_file", "arquivo_origem", "arquivo"])

        if uc_col is None:
            uc_col = "__uc_fallback__"
            local[uc_col] = local.index.astype(str)
        if kwh_col is None:
            raise ValueError("No consumption column found (expected kWh column).")
        if reference_col is None:
            reference_col = "__reference_fallback__"
            local[reference_col] = pd.Timestamp.today().replace(day=1)

        standard = pd.DataFrame()
        standard["municipio"] = (
            local[municipio_col].astype(str).str.strip()
            if municipio_col
            else "NAO INFORMADO"
        )
        standard["uc"] = local[uc_col].astype(str).str.strip()
        standard["consumer_class"] = (
            local[class_col].astype(str).map(_map_consumer_class)
            if class_col
            else "OUTROS"
        )
        standard["reference_date"] = local[reference_col].map(parse_reference_date)
        standard["reference_month"] = standard["reference_date"].dt.strftime("%Y-%m")
        standard["consumption_kwh"] = to_float_series(local[kwh_col]).fillna(0.0)
        standard["demand_kw"] = (
            to_float_series(local[demand_col]).fillna(0.0)
            if demand_col
            else 0.0
        )
        standard["source_file"] = (
            local[source_col].astype(str).str.strip()
            if source_col
            else "extraction_output"
        )

        standard["consumer_class"] = standard["consumer_class"].where(
            standard["consumer_class"].isin({"B3", "IP", "A4"}),
            "OUTROS",
        )
        standard["consumption_kwh"] = standard["consumption_kwh"].clip(lower=0.0)

        return self._stamp(standard.reset_index(drop=True))
