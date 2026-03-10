import csv
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from config import CATALOG_DIR


MODULES_CSV = CATALOG_DIR / "modules.csv"
INVERTERS_CSV = CATALOG_DIR / "inverters.csv"
BOS_CSV = CATALOG_DIR / "bos_costs.csv"
PRICING_VERSIONS_CSV = CATALOG_DIR / "pricing_versions.csv"
MODULE_COLUMNS = [
    "model",
    "brand",
    "wp",
    "vmp",
    "voc",
    "temp_coeff_voc",
    "price_sem_bdi_per_kwp",
    "price_com_bdi_per_kwp",
    "supplier",
    "notes",
    "pricing_version",
]
INVERTER_COLUMNS = [
    "model",
    "brand",
    "kw",
    "mppt_min_v",
    "mppt_max_v",
    "price_sem_bdi",
    "price_com_bdi",
    "supplier",
    "notes",
    "pricing_version",
]


def _to_float(value, default: Optional[float] = None) -> Optional[float]:
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


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [dict(row) for row in reader]


def _normalize_cell(value) -> str:
    return "" if value is None else str(value).strip()


def _normalize_for_save(row: dict, columns: List[str]) -> Dict[str, str]:
    saved: Dict[str, str] = {}
    for key in columns:
        value = row.get(key, "")
        if isinstance(value, float):
            saved[key] = f"{value:.12g}"
        elif isinstance(value, int):
            saved[key] = str(value)
        else:
            saved[key] = _normalize_cell(value)
    return saved


def _write_csv(path: Path, fieldnames: List[str], rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


@lru_cache(maxsize=1)
def load_modules_catalog() -> List[dict]:
    rows = _read_csv(MODULES_CSV)
    modules: List[dict] = []

    for row in rows:
        modules.append(
            {
                "model": _normalize_cell(row.get("model")),
                "brand": _normalize_cell(row.get("brand")),
                "wp": _to_float(row.get("wp"), 0.0) or 0.0,
                "vmp": _to_float(row.get("vmp"), 0.0) or 0.0,
                "voc": _to_float(row.get("voc"), 0.0) or 0.0,
                "temp_coeff_voc": _to_float(row.get("temp_coeff_voc"), 0.0) or 0.0,
                "price_sem_bdi_per_kwp": _to_float(row.get("price_sem_bdi_per_kwp"), 0.0) or 0.0,
                "price_com_bdi_per_kwp": _to_float(row.get("price_com_bdi_per_kwp"), 0.0) or 0.0,
                "supplier": _normalize_cell(row.get("supplier")),
                "notes": _normalize_cell(row.get("notes")),
                "pricing_version": _normalize_cell(row.get("pricing_version")),
            }
        )

    return modules


@lru_cache(maxsize=1)
def load_inverters_catalog() -> List[dict]:
    rows = _read_csv(INVERTERS_CSV)
    inverters: List[dict] = []

    for row in rows:
        inverters.append(
            {
                "model": _normalize_cell(row.get("model")),
                "brand": _normalize_cell(row.get("brand")),
                "kw": _to_float(row.get("kw"), 0.0) or 0.0,
                "mppt_min_v": _to_float(row.get("mppt_min_v"), 0.0) or 0.0,
                "mppt_max_v": _to_float(row.get("mppt_max_v"), 0.0) or 0.0,
                "price_sem_bdi": _to_float(row.get("price_sem_bdi"), 0.0) or 0.0,
                "price_com_bdi": _to_float(row.get("price_com_bdi"), 0.0) or 0.0,
                "supplier": _normalize_cell(row.get("supplier")),
                "notes": _normalize_cell(row.get("notes")),
                "pricing_version": _normalize_cell(row.get("pricing_version")),
            }
        )

    return inverters


@lru_cache(maxsize=1)
def load_bos_catalog() -> List[dict]:
    rows = _read_csv(BOS_CSV)
    items: List[dict] = []

    for row in rows:
        items.append(
            {
                "item_code": _normalize_cell(row.get("item_code")),
                "item_name": _normalize_cell(row.get("item_name")),
                "unit": _normalize_cell(row.get("unit")),
                "base_qty_per_mwp": _to_float(row.get("base_qty_per_mwp")),
                "base_qty_per_kwp": _to_float(row.get("base_qty_per_kwp")),
                "base_qty_fixed": _to_float(row.get("base_qty_fixed")),
                "base_qty_per_string": _to_float(row.get("base_qty_per_string")),
                "unit_price_sem": _to_float(row.get("unit_price_sem"), 0.0) or 0.0,
                "unit_price_com": _to_float(row.get("unit_price_com"), 0.0) or 0.0,
                "bdi_rule": _normalize_cell(row.get("bdi_rule")) or "direct_com_bdi",
                "scaling_rule": _normalize_cell(row.get("scaling_rule")) or "fixed",
            }
        )

    return items


@lru_cache(maxsize=1)
def load_pricing_versions() -> List[dict]:
    rows = _read_csv(PRICING_VERSIONS_CSV)
    versions: List[dict] = []

    for row in rows:
        versions.append(
            {
                "version_id": _normalize_cell(row.get("version_id")),
                "date": _normalize_cell(row.get("date")),
                "description": _normalize_cell(row.get("description")),
                "source": _normalize_cell(row.get("source")),
            }
        )

    return versions


def clear_catalog_cache() -> None:
    load_modules_catalog.cache_clear()
    load_inverters_catalog.cache_clear()
    load_bos_catalog.cache_clear()
    load_pricing_versions.cache_clear()


_CATALOG_KEY_FIELDS = ("model", "supplier", "pricing_version")


def _upsert_catalog_row(path: Path, columns: List[str], row: dict) -> str:
    rows = _read_csv(path)
    saved_row = _normalize_for_save(row, columns)
    key = tuple(saved_row[f].casefold() for f in _CATALOG_KEY_FIELDS)

    replaced_index = None
    for idx, existing in enumerate(rows):
        existing_key = tuple(_normalize_cell(existing.get(f)).casefold() for f in _CATALOG_KEY_FIELDS)
        if existing_key == key:
            replaced_index = idx
            break

    if replaced_index is None:
        rows.append(saved_row)
        action = "added"
    else:
        rows[replaced_index] = saved_row
        action = "updated"

    _write_csv(path, columns, rows)
    clear_catalog_cache()
    return action


def upsert_module_catalog_row(module_row: dict) -> str:
    return _upsert_catalog_row(MODULES_CSV, MODULE_COLUMNS, module_row)


def upsert_inverter_catalog_row(inverter_row: dict) -> str:
    return _upsert_catalog_row(INVERTERS_CSV, INVERTER_COLUMNS, inverter_row)
    return action


def filter_catalog_rows(
    rows: List[dict],
    brand: str = "All",
    supplier: str = "All",
    pricing_version: str = "All",
) -> List[dict]:
    filtered: List[dict] = []
    for row in rows:
        row_brand = row.get("brand", "")
        row_supplier = row.get("supplier", "")
        row_version = row.get("pricing_version", "")

        if brand != "All" and row_brand != brand:
            continue
        if supplier != "All" and row_supplier != supplier:
            continue
        if pricing_version != "All" and row_version not in {"", pricing_version}:
            continue

        filtered.append(row)

    return filtered


def catalog_value_options(rows: List[dict], key: str) -> List[str]:
    values = sorted({row.get(key, "") for row in rows if row.get(key, "")})
    return ["All"] + values
