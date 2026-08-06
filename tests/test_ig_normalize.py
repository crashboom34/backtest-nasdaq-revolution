"""
tests/test_ig_normalize.py — Tests de market_data/ig/normalize.py.

Champs bruts confirmés via recoupement documentation officielle IG Labs + bibliothèque de
référence trading-ig (2026-08-06, voir AI_HANDOFF.md) : prices[].{snapshotTime, openPrice:
{bid,ask}, highPrice:{bid,ask}, lowPrice:{bid,ask}, closePrice:{bid,ask}, lastTradedVolume}.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.ig.errors import IgResponseError
from market_data.ig.normalize import normalize_price_records
from market_data.schema import CANONICAL_COLUMNS

_SAMPLE_PRICES = [
    {
        "snapshotTime": "2026/08/01 00:00:00",
        "openPrice": {"bid": 100.0, "ask": 100.4},
        "highPrice": {"bid": 105.0, "ask": 105.4},
        "lowPrice": {"bid": 99.0, "ask": 99.4},
        "closePrice": {"bid": 102.0, "ask": 102.4},
        "lastTradedVolume": 150,
    },
    {
        "snapshotTime": "2026/08/02 00:00:00",
        "openPrice": {"bid": 102.0, "ask": 102.4},
        "highPrice": {"bid": 106.0, "ask": 106.4},
        "lowPrice": {"bid": 101.0, "ask": 101.4},
        "closePrice": {"bid": 104.0, "ask": 104.4},
        "lastTradedVolume": 200,
    },
]


def test_normalize_price_records_produces_canonical_columns():
    df = normalize_price_records(_SAMPLE_PRICES)

    assert set(CANONICAL_COLUMNS).issubset(set(df.columns))
    assert len(df) == 2
    assert df["time"].iloc[0] == pd.Timestamp("2026-08-01 00:00:00")
    assert df["time"].dt.tz is None


def test_normalize_price_records_uses_bid_ask_midpoint():
    df = normalize_price_records(_SAMPLE_PRICES)
    row = df.iloc[0]

    assert row["open"] == pytest.approx((100.0 + 100.4) / 2)
    assert row["high"] == pytest.approx((105.0 + 105.4) / 2)
    assert row["low"] == pytest.approx((99.0 + 99.4) / 2)
    assert row["close"] == pytest.approx((102.0 + 102.4) / 2)
    assert row["volume"] == 150


def test_normalize_price_records_keeps_raw_bid_ask_columns():
    df = normalize_price_records(_SAMPLE_PRICES)
    row = df.iloc[0]

    assert row["open_bid"] == 100.0
    assert row["open_ask"] == 100.4
    assert row["close_bid"] == 102.0
    assert row["close_ask"] == 102.4


def test_normalize_price_records_sorts_chronologically():
    reversed_records = list(reversed(_SAMPLE_PRICES))
    df = normalize_price_records(reversed_records)
    assert df["time"].is_monotonic_increasing


def test_normalize_price_records_empty_list_returns_empty_canonical_dataframe():
    df = normalize_price_records([])
    assert set(CANONICAL_COLUMNS).issubset(set(df.columns))
    assert len(df) == 0


def test_normalize_price_records_missing_field_raises_response_error():
    with pytest.raises(IgResponseError):
        normalize_price_records([{"snapshotTime": "2026/08/01 00:00:00"}])
