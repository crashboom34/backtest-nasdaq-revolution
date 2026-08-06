"""
tests/test_eodhd_adapter.py — Tests de market_data/eodhd/adapter.py (EodhdMarketDataSource).

Vérifie que l'adaptateur respecte le contrat du port MarketDataSource (market_data/ports.py) :
lecture seule de snapshots déjà stockés localement (jamais de téléchargement déclenché ici),
échec explicite si rien n'est stocké ou si BACKTEST_DATA_DIR est absent, et — point clé de la
Phase 11 — que engine.load_data_from_source() fonctionne de façon identique avec cet adaptateur
qu'avec LocalCsvMarketDataSource, sans qu'engine.py connaisse EODHD.
"""

from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine
from market_data.eodhd.adapter import EodhdMarketDataSource
from market_data.eodhd.storage import save_normalized
from market_data.ports import MarketDataSource


def _sample_df():
    return pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-07-28 00:00:00", "2026-07-29 00:00:00"]),
            "open": [1.0, 2.0], "high": [1.5, 2.5], "low": [0.9, 1.9], "close": [1.2, 2.2],
            "volume": [100, 200],
        }
    )


def test_eodhd_source_satisfies_the_market_data_source_protocol():
    assert isinstance(EodhdMarketDataSource(data_dir="/tmp/whatever"), MarketDataSource)


def test_list_available_empty_when_nothing_stored(tmp_path):
    source = EodhdMarketDataSource(data_dir=tmp_path)
    assert source.list_available() == []


def test_list_available_reflects_stored_snapshots(tmp_path):
    save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=_sample_df(), source_ticker="AAPL.US", source="eod")
    source = EodhdMarketDataSource(data_dir=tmp_path)

    infos = source.list_available()
    assert len(infos) == 1
    assert infos[0].asset == "AAPL_US"
    assert infos[0].timeframe == "D1"
    assert infos[0].exists is True


def test_load_returns_explicit_failure_when_nothing_stored(tmp_path):
    source = EodhdMarketDataSource(data_dir=tmp_path)
    result = source.load("AAPL_US", "D1")

    assert result.ok is False
    assert result.dataframe is None
    assert result.message


def test_load_returns_canonical_dataframe_for_stored_snapshot(tmp_path):
    save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=_sample_df(), source_ticker="AAPL.US", source="eod")
    source = EodhdMarketDataSource(data_dir=tmp_path)

    result = source.load("AAPL_US", "D1")
    assert result.ok is True
    assert len(result.dataframe) == 2
    assert list(result.dataframe.columns) == ["time", "open", "high", "low", "close", "volume"]


def test_load_uses_the_most_recent_snapshot_when_several_exist(tmp_path):
    older = _sample_df()
    newer = pd.concat([_sample_df(), pd.DataFrame({
        "time": [pd.Timestamp("2026-07-30")], "open": [3.0], "high": [3.5], "low": [2.9], "close": [3.2], "volume": [300],
    })], ignore_index=True)

    save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=older, source_ticker="AAPL.US", source="eod")
    save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=newer, source_ticker="AAPL.US", source="eod")

    source = EodhdMarketDataSource(data_dir=tmp_path)
    result = source.load("AAPL_US", "D1")
    assert result.ok is True
    assert len(result.dataframe) == 3  # le plus récent (3 lignes), pas l'ancien (2 lignes)


def test_load_without_data_dir_configured_returns_explicit_failure(monkeypatch):
    monkeypatch.delenv("BACKTEST_DATA_DIR", raising=False)
    source = EodhdMarketDataSource()  # pas de data_dir explicite -> résolution via env
    result = source.load("AAPL_US", "D1")
    assert result.ok is False
    assert "BACKTEST_DATA_DIR" in result.message


def test_engine_load_data_from_source_works_identically_with_eodhd_source(tmp_path):
    """Le cœur de la Phase 11 : engine.py ne connaît que le port MarketDataSource, jamais
    EODHD directement — cette même fonction fonctionne avec n'importe quel adaptateur."""
    save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=_sample_df(), source_ticker="AAPL.US", source="eod")
    source = EodhdMarketDataSource(data_dir=tmp_path)

    df = engine.load_data_from_source(source, "AAPL_US", "D1")

    assert len(df) == 2
    assert "time_paris" in df.columns  # colonnes dérivées ajoutées comme pour n'importe quelle source
    assert "date_p" in df.columns
