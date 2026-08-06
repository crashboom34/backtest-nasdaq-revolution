"""
tests/test_market_data_derived.py — Tests du cache disque de timeframes dérivés
(market_data/derived.py).

Vérifie :
  - premier appel : calcule, met en cache, from_cache=False ;
  - second appel avec source inchangée : sert depuis le cache, from_cache=True ;
  - source modifiée (plus de lignes) : cache invalidé, recalculé ;
  - source indisponible ou timeframe cible incompatible : échec explicite, pas d'exception ;
  - cache corrompu : ne casse rien, régénère proprement.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import path_resolver
from market_data.adapters.local_csv import LocalCsvMarketDataSource
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

_M3_8_BARS = _M3_5_BARS + (
    "2024-01-01 00:15:00,106,110,105,107,15\n"
    "2024-01-01 00:18:00,107,111,106,108,16\n"
    "2024-01-01 00:21:00,108,112,107,109,17\n"
)


def test_first_call_generates_and_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv", _M3_5_BARS)
    cache_dir = tmp_path / "derived_data"

    result = get_or_generate(LocalCsvMarketDataSource(), "NASDAQ", "M3", "M15", cache_dir=cache_dir)

    assert result.ok is True
    assert result.from_cache is False
    assert len(result.dataframe) == 1
    assert (cache_dir / "NASDAQ" / "M15__from_M3.csv").is_file()
    assert (cache_dir / "NASDAQ" / "M15__from_M3.meta.json").is_file()


def test_second_call_with_unchanged_source_uses_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv", _M3_5_BARS)
    cache_dir = tmp_path / "derived_data"
    source = LocalCsvMarketDataSource()

    first = get_or_generate(source, "NASDAQ", "M3", "M15", cache_dir=cache_dir)
    second = get_or_generate(source, "NASDAQ", "M3", "M15", cache_dir=cache_dir)

    assert first.from_cache is False
    assert second.from_cache is True
    assert list(second.dataframe["close"]) == list(first.dataframe["close"])


def test_cache_is_invalidated_when_source_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    csv_path = tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv"
    _write_csv(csv_path, _M3_5_BARS)
    cache_dir = tmp_path / "derived_data"
    source = LocalCsvMarketDataSource()

    first = get_or_generate(source, "NASDAQ", "M3", "M15", cache_dir=cache_dir)
    assert len(first.dataframe) == 1

    _write_csv(csv_path, _M3_8_BARS)
    second = get_or_generate(source, "NASDAQ", "M3", "M15", cache_dir=cache_dir)

    assert second.from_cache is False
    assert len(second.dataframe) == 2


def test_missing_source_returns_explicit_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    cache_dir = tmp_path / "derived_data"

    result = get_or_generate(LocalCsvMarketDataSource(), "NASDAQ", "M3", "M15", cache_dir=cache_dir)

    assert result.ok is False
    assert result.dataframe is None
    assert result.message


def test_incompatible_target_timeframe_returns_explicit_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv", _M3_5_BARS)
    cache_dir = tmp_path / "derived_data"

    result = get_or_generate(LocalCsvMarketDataSource(), "NASDAQ", "M3", "M5", cache_dir=cache_dir)

    assert result.ok is False
    assert result.dataframe is None
    assert "multiple entier" in result.message


_D1_9_DAYS = (
    "time,open,high,low,close,volume\n"
    "2024-01-01,100,105,99,101,10\n"
    "2024-01-02,101,106,100,103,11\n"
    "2024-01-03,103,107,102,104,12\n"
    "2024-01-04,104,108,103,105,13\n"
    "2024-01-05,105,109,104,106,14\n"
    "2024-01-06,106,110,105,107,15\n"
    "2024-01-07,107,111,106,108,16\n"
    "2024-01-08,108,112,107,109,17\n"
    "2024-01-09,109,113,108,110,18\n"
)


def test_weekly_timeframe_is_generated_and_cached_from_daily_source(monkeypatch, tmp_path):
    # Voir docs/adr/0004-calendar-timeframe-resampling.md : W1 dérivable depuis D1.
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(tmp_path / "data" / "NASDAQ" / "D1" / "nasdaq_d1.csv", _D1_9_DAYS)
    cache_dir = tmp_path / "derived_data"
    source = LocalCsvMarketDataSource()

    first = get_or_generate(source, "NASDAQ", "D1", "W1", cache_dir=cache_dir)
    assert first.ok is True
    assert first.from_cache is False
    assert len(first.dataframe) == 2  # semaine du 1er (lun->dim) + semaine du 8 (partielle)
    assert (cache_dir / "NASDAQ" / "W1__from_D1.csv").is_file()

    second = get_or_generate(source, "NASDAQ", "D1", "W1", cache_dir=cache_dir)
    assert second.from_cache is True
    assert list(second.dataframe["close"]) == list(first.dataframe["close"])


def test_corrupted_cache_metadata_falls_back_to_regeneration(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv", _M3_5_BARS)
    cache_dir = tmp_path / "derived_data"
    source = LocalCsvMarketDataSource()

    first = get_or_generate(source, "NASDAQ", "M3", "M15", cache_dir=cache_dir)
    assert first.ok is True

    meta_path = cache_dir / "NASDAQ" / "M15__from_M3.meta.json"
    meta_path.write_text("{not valid json", encoding="utf-8")

    second = get_or_generate(source, "NASDAQ", "M3", "M15", cache_dir=cache_dir)

    assert second.ok is True
    assert second.from_cache is False
    assert len(second.dataframe) == 1
