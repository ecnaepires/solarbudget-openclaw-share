from __future__ import annotations

import pandas as pd

from .base import BaseAdapter, find_first_column, normalize_text, parse_reference_date, to_float_series
from .config_loader import AdapterConfig


class ConfigDrivenAdapter(BaseAdapter):
    """Adapter driven by a YAML/JSON config instead of hardcoded Python logic."""

    def __init__(self, config: AdapterConfig):
        self.config = config
        self.name = config.name
        self.description = config.description

    def _map_consumer_class(self, value: str) -> str:
        text = normalize_text(value)
        if not text:
            return "OUTROS"
        for rule in self.config.consumer_class_rules:
            if rule.matches(text):
                return rule.value
        return "OUTROS"

    def adapt(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return self._empty_standard_df()

        local = df.copy()
        columns = list(local.columns)
        mappings = self.config.column_mappings

        # Resolve each column from aliases
        resolved: dict[str, str | None] = {}
        for field_name, mapping in mappings.items():
            resolved[field_name] = find_first_column(columns, mapping.aliases)

        # Check required columns
        kwh_field = resolved.get("consumption_kwh")
        if kwh_field is None:
            kwh_mapping = mappings.get("consumption_kwh")
            if kwh_mapping and kwh_mapping.required:
                raise ValueError("No consumption column found (expected kWh column).")

        # Apply fallbacks for missing columns
        uc_col = resolved.get("uc")
        if uc_col is None:
            uc_mapping = mappings.get("uc")
            if uc_mapping and uc_mapping.fallback_mode == "index":
                uc_col = "__uc_fallback__"
                local[uc_col] = local.index.astype(str)
            resolved["uc"] = uc_col

        ref_col = resolved.get("reference_date")
        if ref_col is None:
            ref_mapping = mappings.get("reference_date")
            if ref_mapping and ref_mapping.fallback_mode == "today_first_of_month":
                ref_col = "__reference_fallback__"
                local[ref_col] = pd.Timestamp.today().replace(day=1)
            resolved["reference_date"] = ref_col

        # Build standard DataFrame
        standard = pd.DataFrame()

        # municipio
        municipio_col = resolved.get("municipio")
        municipio_fallback = (mappings.get("municipio") or object).__dict__.get("fallback", "NAO INFORMADO") if mappings.get("municipio") else "NAO INFORMADO"
        standard["municipio"] = (
            local[municipio_col].astype(str).str.strip()
            if municipio_col
            else municipio_fallback
        )

        # uc
        uc = resolved.get("uc")
        standard["uc"] = (
            local[uc].astype(str).str.strip()
            if uc
            else local.index.astype(str)
        )

        # consumer_class
        class_col = resolved.get("consumer_class")
        if class_col:
            standard["consumer_class"] = local[class_col].astype(str).map(self._map_consumer_class)
        else:
            class_fallback = mappings.get("consumer_class")
            standard["consumer_class"] = (
                str(class_fallback.fallback) if class_fallback and class_fallback.fallback else "OUTROS"
            )

        # reference_date
        ref = resolved.get("reference_date")
        if ref:
            standard["reference_date"] = local[ref].map(parse_reference_date)
        else:
            standard["reference_date"] = pd.Timestamp.today().replace(day=1)
        standard["reference_month"] = standard["reference_date"].dt.strftime("%Y-%m")

        # consumption_kwh
        if kwh_field:
            standard["consumption_kwh"] = to_float_series(local[kwh_field]).fillna(0.0)
        else:
            standard["consumption_kwh"] = 0.0
        standard["consumption_kwh"] = standard["consumption_kwh"].clip(lower=0.0)

        # demand_kw
        demand_col = resolved.get("demand_kw")
        if demand_col:
            standard["demand_kw"] = to_float_series(local[demand_col]).fillna(0.0)
        else:
            standard["demand_kw"] = 0.0

        # source_file
        source_col = resolved.get("source_file")
        source_fallback = mappings.get("source_file")
        if source_col:
            standard["source_file"] = local[source_col].astype(str).str.strip()
        else:
            standard["source_file"] = (
                str(source_fallback.fallback) if source_fallback and source_fallback.fallback else "extraction_output"
            )

        # Enforce valid consumer classes
        standard["consumer_class"] = standard["consumer_class"].where(
            standard["consumer_class"].isin({"B3", "IP", "A4"}),
            "OUTROS",
        )

        return self._stamp(standard.reset_index(drop=True))
