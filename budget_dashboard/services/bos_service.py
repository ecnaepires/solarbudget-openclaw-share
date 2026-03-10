"""BOS override table helpers used in wizard step C."""
from __future__ import annotations

from typing import Dict

import pandas as pd


def _to_none_if_nan(value):
    if pd.isna(value):
        return None
    return float(value)


def bos_editor_dataframe(bos_catalog: list[dict], scenario: dict) -> pd.DataFrame:
    bos_overrides = scenario.get("bos_overrides", {})
    rows = []
    for item in bos_catalog:
        code = item["item_code"]
        override = bos_overrides.get(code, {})
        rows.append(
            {
                "item_code": code,
                "item_name": item["item_name"],
                "unit": item["unit"],
                "enabled": bool(override.get("enabled", True)),
                "scaling_rule": override.get("scaling_rule", item.get("scaling_rule", "fixed")),
                "base_qty_per_mwp": override.get("base_qty_per_mwp", item.get("base_qty_per_mwp")),
                "base_qty_per_kwp": override.get("base_qty_per_kwp", item.get("base_qty_per_kwp")),
                "base_qty_per_string": override.get("base_qty_per_string", item.get("base_qty_per_string")),
                "base_qty_fixed": override.get("base_qty_fixed", item.get("base_qty_fixed")),
                "unit_price_sem": float(override.get("unit_price_sem", item.get("unit_price_sem", 0.0))),
                "unit_price_com": float(override.get("unit_price_com", item.get("unit_price_com", 0.0))),
            }
        )
    return pd.DataFrame(rows)


def update_bos_overrides_from_editor(scenario: dict, edited_df: pd.DataFrame) -> None:
    overrides: Dict[str, dict] = {}
    for _, row in edited_df.iterrows():
        item_code = str(row["item_code"]).strip()
        overrides[item_code] = {
            "enabled": bool(row["enabled"]),
            "scaling_rule": str(row["scaling_rule"]).strip() or "fixed",
            "base_qty_per_mwp": _to_none_if_nan(row["base_qty_per_mwp"]),
            "base_qty_per_kwp": _to_none_if_nan(row["base_qty_per_kwp"]),
            "base_qty_per_string": _to_none_if_nan(row["base_qty_per_string"]),
            "base_qty_fixed": _to_none_if_nan(row["base_qty_fixed"]),
            "unit_price_sem": float(row["unit_price_sem"]),
            "unit_price_com": float(row["unit_price_com"]),
        }
    scenario["bos_overrides"] = overrides
