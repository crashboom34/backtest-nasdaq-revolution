"""
tests/test_unified_catalog.py — Tests de market_data/unified_catalog.py.

Vérifie que build_unified_catalog() combine catalogue CSV local (market_data.catalog) et
snapshots EODHD (market_data.eodhd.storage) en une liste unique, sans modifier ni recalculer
leurs sources respectives, et sans lever si l'une des deux sources est absente/vide.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import path_resolver
from market_data.adapters.local_csv import LocalCsvMarketDataSource
from market_data.eodhd.storage import save_normalized
from market_data.unified_catalog import build_unified_catalog


def _write_csv(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _sample_df():
    import pandas as pd
    return pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-07-28", "2026-07-29"]),
            "open": [1.0, 2.0], "high": [1.5, 2.5], "low": [0.9, 1.9], "close": [1.2, 2.2],
            "volume": [100, 200],
        }
    )


def test_build_unified_catalog_with_only_local_source(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(
        tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv",
        "time,open,high,low,close,volume\n2024-01-01 00:00:00,100,105,99,101,10\n",
    )

    rows = build_unified_catalog(local_source=LocalCsvMarketDataSource())

    matching = [r for r in rows if r.asset == "NASDAQ" and r.timeframe == "M3"]
    assert len(matching) == 1
    assert matching[0].provider == "local_csv"
    assert matching[0].exists is True


def test_build_unified_catalog_with_only_eodhd_source(tmp_path):
    save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=_sample_df(), source_ticker="AAPL.US", source="eod")

    rows = build_unified_catalog(eodhd_data_dir=tmp_path)

    assert len(rows) == 1
    assert rows[0].provider == "eodhd"
    assert rows[0].asset == "AAPL_US"
    assert rows[0].extra == "AAPL.US"


def test_build_unified_catalog_combines_both_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(
        tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv",
        "time,open,high,low,close,volume\n2024-01-01 00:00:00,100,105,99,101,10\n",
    )
    save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=_sample_df(), source_ticker="AAPL.US", source="eod")

    rows = build_unified_catalog(local_source=LocalCsvMarketDataSource(), eodhd_data_dir=tmp_path)

    providers = {r.provider for r in rows}
    assert providers == {"local_csv", "eodhd"}


def test_build_unified_catalog_with_no_source_returns_empty_list():
    assert build_unified_catalog() == []


def test_build_unified_catalog_tolerates_a_data_dir_with_nothing_stored(tmp_path):
    rows = build_unified_catalog(eodhd_data_dir=tmp_path / "empty_does_not_exist")
    assert rows == []
