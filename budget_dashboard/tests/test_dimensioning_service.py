"""Tests for dimensioning_service.dimensionar()."""
import pytest
import pandas as pd

from services.dimensioning_service import dimensionar


def _record(municipio="Cidade A", mwp=1.5, kwp=1875.0, **kwargs):
    base = {
        "municipio": municipio,
        "mwp": mwp,
        "kwp": kwp,
        "month_labels": ["Jan/25", "Feb/25"],
        "consumo_medio_mensal_kwh": {"B3": 50000.0},
        "warnings": [],
        "payback_needs_tariff_input": False,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Guard: empty records
# ---------------------------------------------------------------------------

def test_empty_records_raises():
    with pytest.raises(ValueError, match="sem registros"):
        dimensionar([])


# ---------------------------------------------------------------------------
# Single record: correct output shape
# ---------------------------------------------------------------------------

def test_single_record_output_shape():
    rec = _record()
    result = dimensionar([rec])

    assert result["mwp_ac"] == pytest.approx(1.5)
    assert result["kwp_total"] == pytest.approx(1875.0)
    assert "category_totals" in result
    assert "month_labels" in result
    assert "warnings" in result
    assert "needs_review" in result
    assert isinstance(result["warnings"], list)


# ---------------------------------------------------------------------------
# preferred_municipio match
# ---------------------------------------------------------------------------

def test_preferred_municipio_exact_match():
    recs = [_record("Cidade A", mwp=1.0), _record("Cidade B", mwp=3.0)]
    result = dimensionar(recs, preferred_municipio="Cidade A")
    assert result["mwp_ac"] == pytest.approx(1.0)


def test_preferred_municipio_case_insensitive():
    recs = [_record("Campos dos Goytacazes", mwp=2.0), _record("Ilhabela", mwp=5.0)]
    result = dimensionar(recs, preferred_municipio="campos dos goytacazes")
    assert result["mwp_ac"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Fallback: max MWp when preferred not found
# ---------------------------------------------------------------------------

def test_fallback_picks_max_mwp():
    recs = [_record("A", mwp=1.0), _record("B", mwp=4.0), _record("C", mwp=2.5)]
    result = dimensionar(recs, preferred_municipio="nonexistent")
    assert result["mwp_ac"] == pytest.approx(4.0)


def test_fallback_adds_warning_for_multiple_records():
    recs = [_record("A", mwp=1.0), _record("B", mwp=2.0)]
    result = dimensionar(recs)
    assert any("multiplos" in w.lower() for w in result["warnings"])


def test_single_record_no_multiple_warning():
    result = dimensionar([_record()])
    assert not any("multiplos" in w.lower() for w in result["warnings"])


# ---------------------------------------------------------------------------
# payback_needs_tariff_input warning
# ---------------------------------------------------------------------------

def test_payback_tariff_warning():
    rec = _record(payback_needs_tariff_input=True)
    result = dimensionar([rec])
    assert any("tarifa" in w.lower() or "payback" in w.lower() for w in result["warnings"])


def test_no_payback_warning_when_tariff_present():
    rec = _record(payback_needs_tariff_input=False)
    result = dimensionar([rec])
    assert not any("payback" in w.lower() and "tarifa" in w.lower() for w in result["warnings"])


# ---------------------------------------------------------------------------
# raw_df validation warnings
# ---------------------------------------------------------------------------

def test_raw_df_missing_categoria_sets_needs_review():
    rec = _record()
    df = pd.DataFrame({"uc": ["001"], "kwh_total_te": [1000.0], "referencia": ["01/2025"]})
    result = dimensionar([rec], raw_df=df, months_to_use=1)
    assert result["needs_review"] is True


def test_raw_df_categoria_unknown_sets_needs_review():
    rec = _record()
    df = pd.DataFrame({
        "uc": ["001"],
        "kwh_total_te": [1000.0],
        "referencia": ["01/2025"],
        "categoria": ["OUTROS"],
    })
    result = dimensionar([rec], raw_df=df, months_to_use=1)
    assert result["needs_review"] is True


def test_raw_df_valid_categoria_not_needs_review():
    rec = _record()
    df = pd.DataFrame({
        "uc": ["001"],
        "kwh_total_te": [1000.0],
        "referencia": ["01/2025"],
        "categoria": ["B3"],
    })
    result = dimensionar([rec], raw_df=df, months_to_use=1)
    assert result["needs_review"] is False


def test_no_raw_df_sets_needs_review():
    rec = _record()
    result = dimensionar([rec], raw_df=None)
    assert result["needs_review"] is True


# ---------------------------------------------------------------------------
# month coverage warning
# ---------------------------------------------------------------------------

def test_missing_months_warning():
    rec = _record()
    df = pd.DataFrame({
        "uc": ["001"],
        "kwh_total_te": [1000.0],
        "referencia": ["01/2025"],
        "categoria": ["B3"],
    })
    # months_to_use=13 but df only has 1 month → should warn
    result = dimensionar([rec], raw_df=df, months_to_use=13)
    assert any("mes" in w.lower() or "month" in w.lower() for w in result["warnings"])
