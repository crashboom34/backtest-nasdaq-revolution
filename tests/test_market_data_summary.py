"""
tests/test_market_data_summary.py — Tests de market_data/summary.py.

Vérifie que build_dataset_summary()/build_data_center_summary() assemblent correctement
catalogue, statut des timeframes et rapport qualité, sans modifier aucune donnée.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import path_resolver
from market_data.adapters.local_csv import LocalCsvMarketDataSource
from market_data.summary import build_data_center_summary, build_dataset_summary


def _write_csv(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


_VALID_M3 = (
    "time,open,high,low,close,volume\n"
    "2024-01-01 00:00:00,100,105,99,101,10\n"
    "2024-01-01 00:03:00,101,106,100,103,11\n"
)


def test_build_dataset_summary_for_existing_dataset(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv", _VALID_M3)

    summary = build_dataset_summary(
        LocalCsvMarketDataSource(), "NASDAQ", "M3", candidate_timeframes=("M3", "M15")
    )

    assert summary is not None
    assert summary.catalog_entry.asset == "NASDAQ"
    assert summary.catalog_entry.row_count == 2
    assert summary.quality is not None
    assert summary.quality.row_count == 2
    assert summary.quality_error is None

    by_tf = {s.timeframe: s.status for s in summary.timeframe_statuses}
    assert by_tf["M3"] == "source"
    assert by_tf["M15"] == "calculable_not_cached"


def test_build_dataset_summary_returns_none_for_unknown_asset_timeframe(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)

    summary = build_dataset_summary(LocalCsvMarketDataSource(), "SP500", "H1")

    assert summary is None


def test_build_dataset_summary_missing_dataset_has_no_quality_report(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)

    summary = build_dataset_summary(LocalCsvMarketDataSource(), "NASDAQ", "M3")

    assert summary is not None
    assert summary.catalog_entry.exists is False
    assert summary.quality is None
    assert summary.quality_error is None


def test_build_dataset_summary_invalid_csv_reports_quality_error(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv", "time,price\n2024-01-01,1\n")

    summary = build_dataset_summary(LocalCsvMarketDataSource(), "NASDAQ", "M3")

    assert summary is not None
    assert summary.quality is None
    assert summary.quality_error is not None


def test_build_data_center_summary_covers_all_catalog_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv", _VALID_M3)
    _write_csv(tmp_path / "data" / "SP500" / "M15" / "sp500_m15.csv", _VALID_M3)

    summaries = build_data_center_summary(LocalCsvMarketDataSource())

    keys = {(s.catalog_entry.asset, s.catalog_entry.timeframe) for s in summaries}
    assert ("NASDAQ", "M3") in keys
    assert ("SP500", "M15") in keys
