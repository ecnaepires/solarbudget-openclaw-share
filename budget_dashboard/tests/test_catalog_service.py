"""Tests for catalog_service: float parsing, load, upsert, filter, options."""
import csv
from pathlib import Path
from unittest.mock import patch

import pytest

import services.catalog_service as cs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_modules_csv(path: Path, rows=None):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cs.MODULE_COLUMNS)
        writer.writeheader()
        for row in (rows or []):
            writer.writerow({k: row.get(k, "") for k in cs.MODULE_COLUMNS})


def _write_inverters_csv(path: Path, rows=None):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cs.INVERTER_COLUMNS)
        writer.writeheader()
        for row in (rows or []):
            writer.writerow({k: row.get(k, "") for k in cs.INVERTER_COLUMNS})


# ---------------------------------------------------------------------------
# _to_float
# ---------------------------------------------------------------------------

class TestToFloat:
    def test_none_returns_none(self):
        assert cs._to_float(None) is None

    def test_none_with_default(self):
        assert cs._to_float(None, default=0.0) == 0.0

    def test_int(self):
        assert cs._to_float(42) == 42.0

    def test_float_passthrough(self):
        assert cs._to_float(3.14) == pytest.approx(3.14)

    def test_plain_string(self):
        assert cs._to_float("100") == 100.0

    def test_brl_prefix_stripped(self):
        assert cs._to_float("R$ 1.234,56") == pytest.approx(1234.56)

    def test_br_format_comma_decimal(self):
        assert cs._to_float("1.234,56") == pytest.approx(1234.56)

    def test_us_format_period_decimal(self):
        assert cs._to_float("1,234.56") == pytest.approx(1234.56)

    def test_comma_only_decimal(self):
        assert cs._to_float("3,14") == pytest.approx(3.14)

    def test_empty_string_returns_default(self):
        assert cs._to_float("", default=0.0) == 0.0

    def test_invalid_string_returns_default(self):
        assert cs._to_float("abc", default=99.0) == 99.0

    def test_zero(self):
        assert cs._to_float(0) == 0.0

    def test_negative(self):
        assert cs._to_float(-5.5) == pytest.approx(-5.5)


# ---------------------------------------------------------------------------
# _normalize_for_save
# ---------------------------------------------------------------------------

class TestNormalizeForSave:
    def test_float_uses_12g_format(self):
        row = {"wp": 550.0, "model": "X", "supplier": "S", "pricing_version": "V1"}
        saved = cs._normalize_for_save(row, ["model", "wp", "supplier", "pricing_version"])
        assert saved["wp"] == "550"

    def test_none_becomes_empty_string(self):
        row = {"model": None}
        saved = cs._normalize_for_save(row, ["model"])
        assert saved["model"] == ""

    def test_missing_key_becomes_empty_string(self):
        saved = cs._normalize_for_save({}, ["model"])
        assert saved["model"] == ""

    def test_int_becomes_string(self):
        row = {"wp": 600}
        saved = cs._normalize_for_save(row, ["wp"])
        assert saved["wp"] == "600"


# ---------------------------------------------------------------------------
# upsert_module_catalog_row — insert + update
# ---------------------------------------------------------------------------

class TestUpsertModuleCatalogRow:
    def test_insert_new_row(self, tmp_path):
        csv_path = tmp_path / "modules.csv"
        _write_modules_csv(csv_path)
        cs.clear_catalog_cache()

        with patch.object(cs, "MODULES_CSV", csv_path):
            action = cs.upsert_module_catalog_row({
                "model": "MOD-A", "brand": "BrandX", "wp": 550.0,
                "vmp": 41.0, "voc": 49.5, "temp_coeff_voc": -0.29,
                "price_sem_bdi_per_kwp": 1200.0, "price_com_bdi_per_kwp": 1450.0,
                "supplier": "SupA", "notes": "", "pricing_version": "V1",
            })

        assert action == "added"
        rows = cs._read_csv(csv_path)
        assert len(rows) == 1
        assert rows[0]["model"] == "MOD-A"

    def test_update_existing_row(self, tmp_path):
        csv_path = tmp_path / "modules.csv"
        _write_modules_csv(csv_path, rows=[{
            "model": "MOD-A", "supplier": "SupA", "pricing_version": "V1", "wp": "550",
        }])
        cs.clear_catalog_cache()

        with patch.object(cs, "MODULES_CSV", csv_path):
            action = cs.upsert_module_catalog_row({
                "model": "MOD-A", "brand": "BrandX", "wp": 560.0,
                "supplier": "SupA", "pricing_version": "V1",
            })

        assert action == "updated"
        rows = cs._read_csv(csv_path)
        assert len(rows) == 1
        assert rows[0]["wp"] == "560"

    def test_case_insensitive_key_match(self, tmp_path):
        csv_path = tmp_path / "modules.csv"
        _write_modules_csv(csv_path, rows=[{
            "model": "MOD-B", "supplier": "SUPA", "pricing_version": "V1",
        }])
        cs.clear_catalog_cache()

        with patch.object(cs, "MODULES_CSV", csv_path):
            action = cs.upsert_module_catalog_row({
                "model": "mod-b", "brand": "B", "wp": 400.0,
                "supplier": "supa", "pricing_version": "v1",
            })

        assert action == "updated"
        rows = cs._read_csv(csv_path)
        assert len(rows) == 1

    def test_two_different_keys_both_kept(self, tmp_path):
        csv_path = tmp_path / "modules.csv"
        _write_modules_csv(csv_path)
        cs.clear_catalog_cache()

        with patch.object(cs, "MODULES_CSV", csv_path):
            cs.upsert_module_catalog_row({
                "model": "MOD-X", "supplier": "S1", "pricing_version": "V1",
            })
            cs.upsert_module_catalog_row({
                "model": "MOD-Y", "supplier": "S1", "pricing_version": "V1",
            })

        rows = cs._read_csv(csv_path)
        assert len(rows) == 2

    def test_cache_cleared_after_upsert(self, tmp_path):
        csv_path = tmp_path / "modules.csv"
        _write_modules_csv(csv_path)
        cs.clear_catalog_cache()

        with patch.object(cs, "MODULES_CSV", csv_path):
            cs.upsert_module_catalog_row({
                "model": "MOD-Z", "supplier": "S1", "pricing_version": "V1", "wp": 500.0,
            })
            # After upsert the cache should be clear; re-loading returns new data
            with patch.object(cs, "MODULES_CSV", csv_path):
                loaded = cs.load_modules_catalog()

        assert any(m["model"] == "MOD-Z" for m in loaded)


# ---------------------------------------------------------------------------
# filter_catalog_rows
# ---------------------------------------------------------------------------

class TestFilterCatalogRows:
    @pytest.fixture
    def rows(self):
        return [
            {"brand": "BrandA", "supplier": "S1", "pricing_version": "V1"},
            {"brand": "BrandB", "supplier": "S2", "pricing_version": "V2"},
            {"brand": "BrandA", "supplier": "S2", "pricing_version": "V1"},
        ]

    def test_no_filter_returns_all(self, rows):
        assert len(cs.filter_catalog_rows(rows)) == 3

    def test_filter_by_brand(self, rows):
        result = cs.filter_catalog_rows(rows, brand="BrandA")
        assert len(result) == 2
        assert all(r["brand"] == "BrandA" for r in result)

    def test_filter_by_supplier(self, rows):
        result = cs.filter_catalog_rows(rows, supplier="S2")
        assert len(result) == 2

    def test_filter_by_version(self, rows):
        result = cs.filter_catalog_rows(rows, pricing_version="V2")
        assert len(result) == 1

    def test_filter_combined(self, rows):
        result = cs.filter_catalog_rows(rows, brand="BrandA", supplier="S2")
        assert len(result) == 1

    def test_no_match_returns_empty(self, rows):
        result = cs.filter_catalog_rows(rows, brand="Unknown")
        assert result == []

    def test_empty_input(self):
        assert cs.filter_catalog_rows([]) == []


# ---------------------------------------------------------------------------
# catalog_value_options
# ---------------------------------------------------------------------------

class TestCatalogValueOptions:
    def test_returns_all_prefix(self):
        rows = [{"brand": "X"}, {"brand": "Y"}]
        options = cs.catalog_value_options(rows, "brand")
        assert options[0] == "All"

    def test_sorted_unique_values(self):
        rows = [{"brand": "C"}, {"brand": "A"}, {"brand": "B"}, {"brand": "A"}]
        options = cs.catalog_value_options(rows, "brand")
        assert options == ["All", "A", "B", "C"]

    def test_empty_values_excluded(self):
        rows = [{"brand": ""}, {"brand": "X"}]
        options = cs.catalog_value_options(rows, "brand")
        assert "" not in options
