import json
import math
from pathlib import Path
from typing import Dict, List, Tuple

from config import EXCEL_MAP_PATH


def load_excel_map(map_path: Path = EXCEL_MAP_PATH) -> dict:
    if not map_path.exists():
        raise FileNotFoundError(f"Excel map not found: {map_path}")

    with map_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _safe_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return default

    text = text.replace("R$", "").replace("r$", "").replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return default


def _apply_rounding(value: float, rounding: str) -> float:
    round_key = str(rounding or "").strip().lower()
    if round_key == "ceil":
        return float(math.ceil(value))
    if round_key == "floor":
        return float(math.floor(value))
    return float(value)


def _quantity_from_rule(
    base_quantity: float,
    scaling_rule: str,
    sizing: dict,
    reference_mwp_ac: float,
    reference_dc_kwp: float,
    capex_com: float,
) -> float:
    rule = str(scaling_rule or "fixed").strip().lower()

    if rule == "per_mwp_ac":
        if reference_mwp_ac <= 0:
            return base_quantity
        return base_quantity * (float(sizing["mwp_ac"]) / reference_mwp_ac)

    if rule == "per_kwp_dc":
        if reference_dc_kwp <= 0:
            return base_quantity
        return base_quantity * (float(sizing["dc_kwp"]) / reference_dc_kwp)

    if rule == "per_string":
        return base_quantity * float(sizing["strings"])

    if rule == "percent_of_capex":
        # Here base_quantity stores a fraction (e.g. 0.05 for 5%).
        return base_quantity * capex_com

    return base_quantity


def _quantity_from_bos_override(
    override: dict,
    sizing: dict,
    capex_com: float,
) -> float:
    rule = str(override.get("scaling_rule", "fixed")).strip().lower()
    per_mwp = override.get("base_qty_per_mwp")
    per_kwp = override.get("base_qty_per_kwp")
    fixed_qty = override.get("base_qty_fixed")
    per_string = override.get("base_qty_per_string")

    if rule == "per_mwp_ac":
        return _safe_float(per_mwp) * float(sizing["mwp_ac"])
    if rule == "per_kwp_dc":
        return _safe_float(per_kwp) * float(sizing["dc_kwp"])
    if rule == "per_string":
        return _safe_float(per_string) * float(sizing["strings"])
    if rule == "percent_of_capex":
        return _safe_float(fixed_qty) * capex_com
    return _safe_float(fixed_qty)


def _apply_lookup_key(
    lookup_key: str,
    quantity: float,
    price_sem: float,
    price_com: float,
    sizing: dict,
) -> Tuple[float, float, float]:
    key = str(lookup_key or "").strip().lower()
    if not key:
        return quantity, price_sem, price_com

    if key == "pv.modules_dc_kwp":
        return float(sizing["dc_kwp"]), float(sizing["module_price_sem"]), float(sizing["module_price_com"])

    if key == "pv.inverter_qty":
        return float(sizing["inverter_qty"]), float(sizing["inverter_price_sem"]), float(sizing["inverter_price_com"])

    if key == "pv.module_count":
        return float(sizing["module_count"]), price_sem, price_com

    if key == "pv.strings":
        return float(sizing["strings"]), price_sem, price_com

    if key == "pv.combiners":
        return float(sizing["combiners_with_spare"]), price_sem, price_com

    return quantity, price_sem, price_com


def build_export_updates_from_map(
    excel_map: dict,
    setup: dict,
    scenario: dict,
    sizing: dict,
) -> Tuple[List[dict], List[dict]]:
    reference_mwp_ac = _safe_float(
        excel_map.get("reference_mwp_ac"),
        _safe_float(setup.get("reference_mwp_ac"), 30.0),
    )
    reference_dc_kwp = _safe_float(
        excel_map.get("reference_dc_kwp"),
        reference_mwp_ac * 1000.0,
    )

    bos_overrides = scenario.get("bos_overrides", {})
    capex_com = float(sizing.get("modules_inverters_total_com", 0.0))
    updates: List[dict] = []
    line_items: List[dict] = []

    for sheet_block in excel_map.get("sheets", []):
        sheet_name = sheet_block.get("sheet_name")
        for row in sheet_block.get("rows", []):
            item_code = str(row.get("item_code", ""))
            description = str(row.get("description", ""))
            has_quantity = bool(row.get("has_quantity", True))
            has_price_sem = bool(row.get("has_price_sem", True))
            has_price_com = bool(row.get("has_price_com", True))

            quantity = _safe_float(row.get("base_quantity"))
            price_sem = _safe_float(row.get("base_price_sem"))
            price_com = _safe_float(row.get("base_price_com"))
            scaling_rule = str(row.get("scaling_rule", "fixed"))
            rounding_rule = str(row.get("rounding", ""))
            lookup_key = str(row.get("lookup_key", ""))
            enabled = bool(row.get("default_enabled", True))

            if item_code in bos_overrides:
                bos_cfg = bos_overrides[item_code]
                enabled = bool(bos_cfg.get("enabled", enabled))
                scaling_rule = str(bos_cfg.get("scaling_rule", scaling_rule))
                quantity = _quantity_from_bos_override(
                    bos_cfg,
                    sizing=sizing,
                    capex_com=capex_com,
                )
                price_sem = _safe_float(bos_cfg.get("unit_price_sem"), price_sem)
                price_com = _safe_float(bos_cfg.get("unit_price_com"), price_com)
            else:
                quantity = _quantity_from_rule(
                    quantity,
                    scaling_rule=scaling_rule,
                    sizing=sizing,
                    reference_mwp_ac=reference_mwp_ac,
                    reference_dc_kwp=reference_dc_kwp,
                    capex_com=capex_com,
                )

            quantity, price_sem, price_com = _apply_lookup_key(
                lookup_key=lookup_key,
                quantity=quantity,
                price_sem=price_sem,
                price_com=price_com,
                sizing=sizing,
            )
            quantity = _apply_rounding(quantity, rounding_rule)

            if not enabled and lookup_key.lower() not in {"pv.modules_dc_kwp", "pv.inverter_qty"}:
                quantity_for_write = 0.0 if has_quantity else None
            else:
                quantity_for_write = quantity if has_quantity else None

            update = {
                "sheet_name": sheet_name,
                "quantity_cell": row.get("quantity_cell"),
                "price_sem_cell": row.get("price_sem_cell"),
                "price_com_cell": row.get("price_com_cell"),
                "quantity": quantity_for_write,
                "price_sem": price_sem if has_price_sem else None,
                "price_com": price_com if has_price_com else None,
            }
            updates.append(update)

            if has_quantity:
                subtotal_sem = _safe_float(quantity_for_write) * _safe_float(price_sem)
                subtotal_com = _safe_float(quantity_for_write) * _safe_float(price_com)
            else:
                subtotal_sem = _safe_float(price_sem)
                subtotal_com = _safe_float(price_com)

            line_items.append(
                {
                    "sheet": sheet_name,
                    "item_code": item_code,
                    "description": description,
                    "enabled": enabled,
                    "scaling_rule": scaling_rule,
                    "quantity": _safe_float(quantity_for_write),
                    "unit_price_sem": _safe_float(price_sem),
                    "unit_price_com": _safe_float(price_com),
                    "subtotal_sem": subtotal_sem,
                    "subtotal_com": subtotal_com,
                }
            )

    return updates, line_items


def summarize_sheet_totals(line_items: List[dict]) -> List[dict]:
    totals: Dict[str, dict] = {}
    for row in line_items:
        sheet_name = row["sheet"]
        if sheet_name not in totals:
            totals[sheet_name] = {"sheet": sheet_name, "total_sem_bdi": 0.0, "total_com_bdi": 0.0}
        totals[sheet_name]["total_sem_bdi"] += _safe_float(row.get("subtotal_sem"))
        totals[sheet_name]["total_com_bdi"] += _safe_float(row.get("subtotal_com"))
    return list(totals.values())
