import csv
import gzip
import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple
from urllib.error import URLError
from urllib.request import urlopen

from config import CATALOG_DIR, LOCATIONS_CSV_PATH


IBGE_MUNICIPALITIES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?orderBy=nome"
LOCATION_COLUMNS = ["ibge_code", "city", "state_uf", "state_name", "city_search"]


def normalize_search_text(text: str) -> str:
    base = unicodedata.normalize("NFKD", str(text))
    no_marks = "".join(char for char in base if not unicodedata.combining(char))
    return no_marks.lower().strip()


def _read_csv(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [dict(row) for row in reader]


def _write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=LOCATION_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in LOCATION_COLUMNS})


def fetch_municipalities_from_ibge(*, timeout: int = 10, retries: int = 1) -> List[dict]:
    """Fetch municipalities from IBGE API with timeout and single retry."""
    last_exc: Exception = OSError("No fetch attempted")
    for _attempt in range(retries + 1):
        try:
            with urlopen(IBGE_MUNICIPALITIES_URL, timeout=timeout) as response:
                raw_content = response.read()
                encoding = str(response.headers.get("Content-Encoding", "")).lower()
                if encoding == "gzip" or raw_content[:2] == b"\x1f\x8b":
                    raw_content = gzip.decompress(raw_content)
                payload = json.loads(raw_content.decode("utf-8"))

            rows: List[dict] = []
            for item in payload:
                uf_data = {}
                micro = item.get("microrregiao")
                if isinstance(micro, dict):
                    meso = micro.get("mesorregiao")
                    if isinstance(meso, dict):
                        uf_data = meso.get("UF") or {}

                if not uf_data:
                    reg_imediata = item.get("regiao-imediata") or {}
                    reg_inter = reg_imediata.get("regiao-intermediaria") or {}
                    uf_data = reg_inter.get("UF") or {}

                city_name = str(item.get("nome", "")).strip()
                row = {
                    "ibge_code": str(item.get("id", "")),
                    "city": city_name,
                    "state_uf": str(uf_data.get("sigla", "")).strip().upper(),
                    "state_name": str(uf_data.get("nome", "")).strip(),
                    "city_search": normalize_search_text(city_name),
                }
                if row["city"] and row["state_uf"]:
                    rows.append(row)

            rows.sort(key=lambda r: (r["state_uf"], r["city_search"]))
            return rows

        except (URLError, TimeoutError, OSError) as exc:
            last_exc = exc

    raise last_exc


def ensure_locations_catalog(path: Path = LOCATIONS_CSV_PATH) -> Tuple[bool, str]:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return True, ""

    try:
        rows = fetch_municipalities_from_ibge()
    except (URLError, TimeoutError, OSError) as exc:
        return False, f"Unable to download IBGE municipalities catalog: {exc}"

    if not rows:
        return False, "IBGE municipalities API returned no rows."

    _write_csv(path, rows)
    clear_location_cache()
    return True, ""


@lru_cache(maxsize=1)
def load_locations_catalog(path: Path = LOCATIONS_CSV_PATH) -> List[dict]:
    rows = _read_csv(path)
    cleaned: List[dict] = []
    for row in rows:
        state_uf = str(row.get("state_uf", "")).strip().upper()
        city = str(row.get("city", "")).strip()
        if not state_uf or not city:
            continue

        cleaned.append(
            {
                "ibge_code": str(row.get("ibge_code", "")).strip(),
                "city": city,
                "state_uf": state_uf,
                "state_name": str(row.get("state_name", "")).strip(),
                "city_search": str(row.get("city_search", "")).strip() or normalize_search_text(city),
            }
        )
    return cleaned


@lru_cache(maxsize=1)
def load_state_options() -> List[dict]:
    rows = load_locations_catalog()
    state_map = {}
    for row in rows:
        uf = row["state_uf"]
        if uf not in state_map:
            state_map[uf] = row.get("state_name", "")
    return [{"uf": uf, "name": state_map[uf]} for uf in sorted(state_map.keys())]


def get_cities_by_state(state_uf: str) -> List[dict]:
    uf = str(state_uf).strip().upper()
    rows = load_locations_catalog()
    return [row for row in rows if row["state_uf"] == uf]


def filter_cities(cities: List[dict], search: str, limit: int = 400) -> List[dict]:
    search_key = normalize_search_text(search)
    if not search_key:
        return cities[:limit]

    matches = [row for row in cities if search_key in row["city_search"]]
    return matches[:limit]


def clear_location_cache() -> None:
    load_locations_catalog.cache_clear()
    load_state_options.cache_clear()
