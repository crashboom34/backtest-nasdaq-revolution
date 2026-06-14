import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import path_resolver
from data_validator import validate_market_csv_bytes


def _csv_bytes(text: str) -> bytes:
    return text.strip().encode("utf-8")


def test_valid_csv_is_normalized_for_engine():
    result = validate_market_csv_bytes(_csv_bytes("""
time,open,high,low,close,volume
2024-01-01 00:00:00,100,105,99,104,10
2024-01-01 00:03:00,104,108,103,107,12
"""))

    assert result.can_save is True
    assert result.errors == []
    assert result.summary["row_count"] == 2
    assert result.summary["start"] == "2024-01-01 00:00:00"
    assert result.summary["end"] == "2024-01-01 00:03:00"
    assert list(result.dataframe.columns) == ["time", "open", "high", "low", "close", "volume"]


def test_csv_without_date_column_is_blocked():
    result = validate_market_csv_bytes(_csv_bytes("""
open,high,low,close
100,105,99,104
"""))

    assert result.can_save is False
    assert any("date/temps" in error for error in result.errors)


def test_csv_without_ohlc_columns_is_blocked():
    result = validate_market_csv_bytes(_csv_bytes("""
time,price
2024-01-01 00:00:00,100
"""))

    assert result.can_save is False
    assert any("Colonnes OHLC manquantes" in error for error in result.errors)


def test_csv_with_duplicate_dates_returns_warning():
    result = validate_market_csv_bytes(_csv_bytes("""
time,open,high,low,close
2024-01-01 00:00:00,100,105,99,104
2024-01-01 00:00:00,104,108,103,107
"""))

    assert result.can_save is True
    assert result.summary["duplicate_dates"] == 1
    assert any("dupliquee" in warning for warning in result.warnings)


def test_csv_with_missing_required_values_is_blocked():
    result = validate_market_csv_bytes(_csv_bytes("""
time,open,high,low,close
2024-01-01 00:00:00,100,105,99,
"""))

    assert result.can_save is False
    assert any("valeur" in error and "manquante" in error for error in result.errors)


def test_csv_with_high_below_low_is_blocked():
    result = validate_market_csv_bytes(_csv_bytes("""
time,open,high,low,close
2024-01-01 00:00:00,100,90,99,104
"""))

    assert result.can_save is False
    assert any("high < low" in error for error in result.errors)


def test_saved_csv_is_found_by_path_resolver(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    result = validate_market_csv_bytes(_csv_bytes("""
time,open,high,low,close
2024-01-01 00:00:00,100,105,99,104
2024-01-01 00:03:00,104,108,103,107
"""))

    target = path_resolver.data_csv_target_path("SP500", "M15")
    target.parent.mkdir(parents=True)
    result.dataframe.to_csv(target, index=False)

    resolved = path_resolver.resolve_data_csv("SP500", "M15")

    assert resolved.exists is True
    assert resolved.source == "data"
    assert resolved.relative_path == "data/SP500/M15/sp500_m15.csv"
    assert pd.read_csv(resolved.path).shape[0] == 2


def test_legacy_nasdaq_m3_fallback_still_works(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    (tmp_path / "nasdaq_3m.csv").write_text("legacy", encoding="utf-8")

    resolved = path_resolver.resolve_data_csv("NASDAQ", "M3")

    assert resolved.exists is True
    assert resolved.source == "legacy"
    assert resolved.relative_path == "nasdaq_3m.csv"

