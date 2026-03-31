"""Tests for pure helper functions in ui/helpers.py — no Streamlit rendering."""
import pytest
import pandas as pd

from ui.helpers import (
    add_abbreviation_meanings,
    format_all_option,
    format_brl,
    format_ptbr_number,
    format_scenario_name,
    parse_brl_value,
    safe_index,
    df_to_csv_bytes,
    slugify_filename,
)


# ---------------------------------------------------------------------------
# format_ptbr_number
# ---------------------------------------------------------------------------

class TestFormatPtbrNumber:
    def test_basic(self):
        assert format_ptbr_number(1234.56) == "1.234,56"

    def test_zero(self):
        assert format_ptbr_number(0) == "0,00"

    def test_large_number(self):
        assert format_ptbr_number(1_000_000.0) == "1.000.000,00"

    def test_zero_decimals(self):
        assert format_ptbr_number(1234.0, decimals=0) == "1.234"

    def test_none_treated_as_zero(self):
        assert format_ptbr_number(None) == "0,00"

    def test_negative(self):
        result = format_ptbr_number(-500.5)
        assert result == "-500,50"


# ---------------------------------------------------------------------------
# format_brl
# ---------------------------------------------------------------------------

class TestFormatBrl:
    def test_basic(self):
        assert format_brl(1234.56) == "R$ 1.234,56"

    def test_zero(self):
        assert format_brl(0) == "R$ 0,00"

    def test_large(self):
        assert format_brl(8_500_000.0) == "R$ 8.500.000,00"


# ---------------------------------------------------------------------------
# parse_brl_value
# ---------------------------------------------------------------------------

class TestParseBrlValue:
    def test_none_returns_none(self):
        assert parse_brl_value(None) is None

    def test_empty_string_returns_none(self):
        assert parse_brl_value("") is None

    def test_int_passthrough(self):
        assert parse_brl_value(42) == pytest.approx(42.0)

    def test_float_passthrough(self):
        assert parse_brl_value(3.14) == pytest.approx(3.14)

    def test_br_format_both_separators(self):
        assert parse_brl_value("1.234,56") == pytest.approx(1234.56)

    def test_br_format_comma_only(self):
        assert parse_brl_value("3,14") == pytest.approx(3.14)

    def test_us_format(self):
        assert parse_brl_value("1,234.56") == pytest.approx(1234.56)

    def test_brl_prefix(self):
        assert parse_brl_value("R$ 8.500.000,00") == pytest.approx(8_500_000.0)

    def test_plain_integer_string(self):
        assert parse_brl_value("1000") == pytest.approx(1000.0)

    def test_invalid_returns_none(self):
        assert parse_brl_value("not-a-number") is None

    def test_thousand_dots_only(self):
        # "1.000.000" should parse as one million
        result = parse_brl_value("1.000.000")
        assert result == pytest.approx(1_000_000.0)


# ---------------------------------------------------------------------------
# add_abbreviation_meanings
# ---------------------------------------------------------------------------

class TestAddAbbreviationMeanings:
    def test_known_abbreviation_expanded(self):
        result = add_abbreviation_meanings("Fonte kWh fallback")
        assert "Quilowatt-hora" in result

    def test_multiple_abbreviations(self):
        result = add_abbreviation_meanings("kWp e MWp do projeto")
        assert "Quilowatt-pico" in result
        assert "Megawatt-pico" in result

    def test_unknown_token_unchanged(self):
        result = add_abbreviation_meanings("XYZABC test")
        assert "XYZABC" in result

    def test_empty_string_passthrough(self):
        assert add_abbreviation_meanings("") == ""

    def test_first_call_expands(self):
        # First call must expand the abbreviation
        result = add_abbreviation_meanings("kWh")
        assert "kWh" in result
        assert "Quilowatt-hora" in result


# ---------------------------------------------------------------------------
# safe_index
# ---------------------------------------------------------------------------

class TestSafeIndex:
    def test_found(self):
        assert safe_index(["a", "b", "c"], "b") == 1

    def test_not_found_returns_zero(self):
        assert safe_index(["a", "b"], "z") == 0

    def test_first_item(self):
        assert safe_index(["x", "y"], "x") == 0


# ---------------------------------------------------------------------------
# format_all_option / format_scenario_name
# ---------------------------------------------------------------------------

def test_format_all_option_translates():
    assert format_all_option("All") == "Todos"


def test_format_all_option_passthrough():
    assert format_all_option("BrandX") == "BrandX"


def test_format_scenario_name():
    assert format_scenario_name("Scenario A") == "Cenario A"


def test_format_scenario_name_no_match():
    assert format_scenario_name("Custom Name") == "Custom Name"


# ---------------------------------------------------------------------------
# df_to_csv_bytes
# ---------------------------------------------------------------------------

def test_df_to_csv_bytes_returns_bytes():
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    result = df_to_csv_bytes(df)
    assert isinstance(result, bytes)


def test_df_to_csv_bytes_roundtrip():
    df = pd.DataFrame({"col1": [10, 20], "col2": ["hello", "world"]})
    raw = df_to_csv_bytes(df)
    restored = pd.read_csv(pd.io.common.BytesIO(raw), encoding="utf-8-sig")
    assert list(restored.columns) == ["col1", "col2"]
    assert list(restored["col1"]) == [10, 20]


def test_df_to_csv_bytes_empty_dataframe():
    df = pd.DataFrame()
    result = df_to_csv_bytes(df)
    assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# slugify_filename
# ---------------------------------------------------------------------------

def test_slugify_filename_basic():
    from ui.helpers import slugify_filename
    assert slugify_filename("Meu Projeto") == "meu_projeto"


def test_slugify_filename_special_chars():
    from ui.helpers import slugify_filename
    result = slugify_filename("São Paulo! #2025")
    assert " " not in result
    assert "#" not in result
