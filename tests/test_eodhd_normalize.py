"""
tests/test_eodhd_normalize.py — Tests de market_data/eodhd/normalize.py.

Utilise des enregistrements bruts au format exact confirmé via le MCP EODHD le 2026-08-06 (voir
AI_HANDOFF.md) — jamais un format deviné. Vérifie la conversion vers le schéma canonique
(market_data.schema.CANONICAL_COLUMNS) en UTC, et le comportement sur données vides/malformées.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.eodhd.errors import EodhdResponseError
from market_data.eodhd.normalize import (
    normalize_dividend_records,
    normalize_eod_records,
    normalize_intraday_records,
    normalize_split_records,
)
from market_data.schema import CANONICAL_COLUMNS


def test_normalize_eod_records_produces_canonical_columns():
    records = [
        {"date": "2026-07-28", "open": 340.03, "high": 342.89, "low": 335.6, "close": 340.08,
         "adjusted_close": 340.08, "volume": 51859000},
        {"date": "2026-07-29", "open": 339.73, "high": 344.57, "low": 337.35, "close": 338.19,
         "adjusted_close": 338.19, "volume": 56090800},
    ]

    df = normalize_eod_records(records)

    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert len(df) == 2
    assert df["time"].iloc[0] == pd.Timestamp("2026-07-28")
    assert df["time"].dt.tz is None  # tz-naive, convention existante (voir engine.py)
    assert df["open"].iloc[0] == 340.03
    assert df["volume"].iloc[0] == 51859000


def test_normalize_eod_records_sorts_chronologically():
    records = [
        {"date": "2026-07-29", "open": 1, "high": 1, "low": 1, "close": 1},
        {"date": "2026-07-28", "open": 2, "high": 2, "low": 2, "close": 2},
    ]
    df = normalize_eod_records(records)
    assert df["time"].is_monotonic_increasing


def test_normalize_eod_records_empty_list_returns_empty_canonical_dataframe():
    df = normalize_eod_records([])
    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert len(df) == 0


def test_normalize_eod_records_missing_required_field_raises_response_error():
    with pytest.raises(EodhdResponseError):
        normalize_eod_records([{"date": "2026-07-28", "open": 1, "high": 1}])  # low/close absents


def test_normalize_intraday_records_produces_canonical_columns():
    records = [
        {"timestamp": 1785830400, "gmtoffset": 0, "datetime": "2026-08-04 08:00:00",
         "open": 304.1, "high": 304.8, "low": 303.0455, "close": 303.51, "volume": 25227},
        {"timestamp": 1785830460, "gmtoffset": 0, "datetime": "2026-08-04 08:01:00",
         "open": 303.54, "high": 304.82, "low": 303.46, "close": 304.17, "volume": 72283},
    ]

    df = normalize_intraday_records(records)

    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert len(df) == 2
    assert df["time"].dt.tz is None
    # timestamp Unix UTC fait foi, pas le champ "datetime" (voir docstring du module).
    assert df["time"].iloc[0] == pd.Timestamp("2026-08-04 08:00:00")


def test_normalize_intraday_records_deduplicates_and_sorts_by_timestamp():
    records = [
        {"timestamp": 1785830460, "open": 2, "high": 2, "low": 2, "close": 2, "volume": 1},
        {"timestamp": 1785830400, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"timestamp": 1785830400, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},  # doublon exact
    ]
    df = normalize_intraday_records(records)
    assert len(df) == 2
    assert df["time"].is_monotonic_increasing


def test_normalize_intraday_records_empty_list_returns_empty_canonical_dataframe():
    df = normalize_intraday_records([])
    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert len(df) == 0


def test_normalize_dividend_records_keeps_provider_fields_not_canonical_ohlcv():
    records = [
        {"date": "2025-02-10", "declarationDate": "2025-01-30", "recordDate": "2025-02-10",
         "paymentDate": "2025-02-13", "period": "Quarterly", "value": 0.25,
         "unadjustedValue": 0.25, "currency": "USD"},
    ]
    df = normalize_dividend_records(records)

    assert "ex_dividend_date" in df.columns
    assert "value" in df.columns
    assert "currency" in df.columns
    # Volontairement hors du schéma canonique OHLCV (voir docs/adr/0002-...).
    assert "open" not in df.columns
    assert df["ex_dividend_date"].iloc[0] == pd.Timestamp("2025-02-10")


def test_normalize_dividend_records_empty_list_returns_empty_dataframe():
    df = normalize_dividend_records([])
    assert len(df) == 0


def test_normalize_split_records_parses_ratio_string():
    records = [{"date": "2020-08-31", "split": "4.000000/1.000000"}]
    df = normalize_split_records(records)

    assert df["date"].iloc[0] == pd.Timestamp("2020-08-31")
    assert df["split_from"].iloc[0] == pytest.approx(1.0)
    assert df["split_to"].iloc[0] == pytest.approx(4.0)
    assert df["split_ratio"].iloc[0] == pytest.approx(4.0)


def test_normalize_split_records_empty_list_returns_empty_dataframe():
    df = normalize_split_records([])
    assert len(df) == 0
