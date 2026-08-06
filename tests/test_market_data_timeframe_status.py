"""
tests/test_market_data_timeframe_status.py — Tests de catalog.list_timeframe_status().

Vérifie la distinction en trois statuts demandée dans la spécification initiale du Data Center
(section 3) : unité source / unité calculable (en cache ou non) / unité non calculable.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import path_resolver
from market_data.adapters.local_csv import LocalCsvMarketDataSource
from market_data.catalog import list_timeframe_status
from market_data.derived import get_or_generate


def _write_csv(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


_M3_5_BARS = (
    "time,open,high,low,close,volume\n"
    "2024-01-01 00:00:00,100,105,99,101,10\n"
    "2024-01-01 00:03:00,101,106,100,103,11\n"
    "2024-01-01 00:06:00,103,107,102,104,12\n"
    "2024-01-01 00:09:00,104,108,103,105,13\n"
    "2024-01-01 00:12:00,105,109,104,106,14\n"
)


def test_source_timeframe_is_flagged_as_source(tmp_path):
    statuses = list_timeframe_status(
        "NASDAQ", "M3", candidate_timeframes=("M3", "M15"), cache_dir=tmp_path / "derived_data"
    )
    by_tf = {s.timeframe: s.status for s in statuses}
    assert by_tf["M3"] == "source"


def test_derivable_timeframe_without_cache_is_calculable_not_cached(tmp_path):
    statuses = list_timeframe_status(
        "NASDAQ", "M3", candidate_timeframes=("M3", "M15"), cache_dir=tmp_path / "derived_data"
    )
    by_tf = {s.timeframe: s.status for s in statuses}
    assert by_tf["M15"] == "calculable_not_cached"


def test_non_multiple_timeframe_is_not_calculable(tmp_path):
    statuses = list_timeframe_status(
        "NASDAQ", "M3", candidate_timeframes=("M5", "M7"), cache_dir=tmp_path / "derived_data"
    )
    by_tf = {s.timeframe: s.status for s in statuses}
    assert by_tf["M5"] == "not_calculable"
    assert by_tf["M7"] == "not_calculable"


def test_timeframe_becomes_cached_after_get_or_generate(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv", _M3_5_BARS)
    cache_dir = tmp_path / "derived_data"

    before = list_timeframe_status(
        "NASDAQ", "M3", candidate_timeframes=("M15",), cache_dir=cache_dir
    )
    assert before[0].status == "calculable_not_cached"

    result = get_or_generate(LocalCsvMarketDataSource(), "NASDAQ", "M3", "M15", cache_dir=cache_dir)
    assert result.ok is True

    after = list_timeframe_status(
        "NASDAQ", "M3", candidate_timeframes=("M15",), cache_dir=cache_dir
    )
    assert after[0].status == "calculable_cached"


def test_default_candidate_timeframes_cover_common_units(tmp_path):
    statuses = list_timeframe_status("NASDAQ", "M3", cache_dir=tmp_path / "derived_data")
    timeframes = {s.timeframe for s in statuses}
    assert {"M3", "M15", "H1", "H4", "H6", "H12", "D1", "W1", "MO1"}.issubset(timeframes)


def test_weekly_and_monthly_are_not_calculable_from_a_non_daily_source(tmp_path):
    # Source M3 (ex. NASDAQ) : W1/MO1 ne sont dérivables que depuis D1 (voir ADR 0004).
    statuses = list_timeframe_status(
        "NASDAQ", "M3", candidate_timeframes=("W1", "MO1"), cache_dir=tmp_path / "derived_data"
    )
    by_tf = {s.timeframe: s.status for s in statuses}
    assert by_tf["W1"] == "not_calculable"
    assert by_tf["MO1"] == "not_calculable"


def test_weekly_and_monthly_are_calculable_from_a_daily_source(tmp_path):
    statuses = list_timeframe_status(
        "NASDAQ", "D1", candidate_timeframes=("D1", "W1", "MO1"), cache_dir=tmp_path / "derived_data"
    )
    by_tf = {s.timeframe: s.status for s in statuses}
    assert by_tf["D1"] == "source"
    assert by_tf["W1"] == "calculable_not_cached"
    assert by_tf["MO1"] == "calculable_not_cached"
