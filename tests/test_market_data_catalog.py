"""
tests/test_market_data_catalog.py — Tests du catalogue local minimal (market_data/catalog.py).

Vérifie :
  - build_catalog() calcule row_count/start/end pour un dataset existant ;
  - build_catalog(compute_stats=False) reste rapide, sans stats ;
  - un dataset invalide (colonnes manquantes) produit un stats_error, pas une exception ;
  - save_catalog()/load_catalog() font un aller-retour fidèle ;
  - load_catalog() est tolérant à un fichier absent ou corrompu ;
  - refresh_catalog() reconstruit et persiste en une seule étape.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import path_resolver
from market_data.adapters.local_csv import LocalCsvMarketDataSource
from market_data.catalog import build_catalog, load_catalog, refresh_catalog, save_catalog


def _write_csv(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_build_catalog_computes_stats_for_existing_dataset(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(
        tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv",
        "time,open,high,low,close,volume\n"
        "2024-01-01 00:00:00,100,105,99,104,10\n"
        "2024-01-01 00:03:00,104,108,103,107,12\n",
    )

    entries = build_catalog(LocalCsvMarketDataSource())

    assert len(entries) == 1
    entry = entries[0]
    assert entry.asset == "NASDAQ"
    assert entry.timeframe == "M3"
    assert entry.exists is True
    assert entry.row_count == 2
    assert entry.start == "2024-01-01 00:00:00"
    assert entry.end == "2024-01-01 00:03:00"
    assert entry.stats_error is None


def test_build_catalog_without_stats_is_fast_and_leaves_fields_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(
        tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv",
        "time,open,high,low,close,volume\n2024-01-01 00:00:00,100,105,99,104,10\n",
    )

    entries = build_catalog(LocalCsvMarketDataSource(), compute_stats=False)

    assert len(entries) == 1
    assert entries[0].row_count is None
    assert entries[0].start is None


def test_build_catalog_reports_stats_error_without_raising(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(
        tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv",
        "time,price\n2024-01-01 00:00:00,100\n",
    )

    entries = build_catalog(LocalCsvMarketDataSource())

    assert len(entries) == 1
    assert entries[0].row_count is None
    assert entries[0].stats_error is not None


def test_build_catalog_missing_dataset_has_no_stats(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)

    entries = build_catalog(LocalCsvMarketDataSource())

    assert len(entries) == 1
    assert entries[0].exists is False
    assert entries[0].row_count is None
    assert entries[0].stats_error is None


def test_save_and_load_catalog_roundtrip(tmp_path):
    monkeypatch_path = tmp_path / "settings" / "data_catalog.json"

    from market_data.catalog import CatalogEntry

    original = [
        CatalogEntry(
            provider="local_csv",
            asset="NASDAQ",
            timeframe="M3",
            source="data",
            exists=True,
            relative_path="data/NASDAQ/M3/nasdaq_m3.csv",
            message="OK",
            row_count=2,
            start="2024-01-01 00:00:00",
            end="2024-01-01 00:03:00",
        )
    ]

    save_catalog(original, path=monkeypatch_path)
    assert monkeypatch_path.is_file()

    loaded = load_catalog(path=monkeypatch_path)
    assert loaded == original


def test_load_catalog_tolerates_missing_file(tmp_path):
    assert load_catalog(path=tmp_path / "does_not_exist.json") == []


def test_load_catalog_tolerates_corrupted_file(tmp_path):
    corrupted = tmp_path / "data_catalog.json"
    corrupted.write_text("{not valid json", encoding="utf-8")

    assert load_catalog(path=corrupted) == []


def test_refresh_catalog_builds_and_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(
        tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv",
        "time,open,high,low,close,volume\n2024-01-01 00:00:00,100,105,99,104,10\n",
    )
    catalog_path = tmp_path / "settings" / "data_catalog.json"

    entries = refresh_catalog(LocalCsvMarketDataSource(), path=catalog_path)

    assert catalog_path.is_file()
    reloaded = load_catalog(path=catalog_path)
    assert reloaded == entries
    assert reloaded[0].row_count == 1
