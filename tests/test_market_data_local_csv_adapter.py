"""
tests/test_market_data_local_csv_adapter.py — Tests de LocalCsvMarketDataSource.

Vérifie que le premier adaptateur du port MarketDataSource se comporte comme un simple
habillage de path_resolver.py, sans dupliquer ni modifier son comportement :
  - liste les jeux de données disponibles (data/{ASSET}/{TIMEFRAME}/ et fallback legacy) ;
  - charge un CSV existant et le normalise sur le schéma canonique ;
  - renvoie un échec explicite (pas d'exception) si le CSV est absent ou invalide.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import path_resolver
from market_data.adapters.local_csv import LocalCsvMarketDataSource
from market_data.schema import CANONICAL_COLUMNS


def _write_csv(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_list_available_detects_data_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(
        tmp_path / "data" / "SP500" / "M15" / "sp500_m15.csv",
        "time,open,high,low,close,volume\n2024-01-01 00:00:00,1,2,0.5,1.5,10",
    )

    source = LocalCsvMarketDataSource()
    infos = source.list_available()

    matches = [i for i in infos if i.asset == "SP500" and i.timeframe == "M15"]
    assert len(matches) == 1
    assert matches[0].provider == "local_csv"
    assert matches[0].exists is True
    assert matches[0].source == "data"


def test_list_available_handles_empty_data_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)

    source = LocalCsvMarketDataSource()
    infos = source.list_available()

    # Pas de dossier data/ du tout : path_resolver retombe sur NASDAQ/M3 par défaut.
    assert len(infos) == 1
    assert infos[0].asset == "NASDAQ"
    assert infos[0].timeframe == "M3"
    assert infos[0].exists is False


def test_load_normalizes_existing_csv_to_canonical_schema(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(
        tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv",
        "time,open,high,low,close,volume\n"
        "2024-01-01 00:00:00,100,105,99,104,10\n"
        "2024-01-01 00:03:00,104,108,103,107,12\n",
    )

    source = LocalCsvMarketDataSource()
    result = source.load("NASDAQ", "M3")

    assert result.ok is True
    assert result.dataframe is not None
    assert list(result.dataframe.columns) == list(CANONICAL_COLUMNS)
    assert len(result.dataframe) == 2


def test_load_fills_missing_volume_with_na(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(
        tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv",
        "time,open,high,low,close\n2024-01-01 00:00:00,100,105,99,104\n",
    )

    source = LocalCsvMarketDataSource()
    result = source.load("NASDAQ", "M3")

    assert result.ok is True
    assert "volume" in result.dataframe.columns
    assert result.dataframe["volume"].isna().all()


def test_load_returns_explicit_failure_when_csv_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)

    source = LocalCsvMarketDataSource()
    result = source.load("NASDAQ", "M3")

    assert result.ok is False
    assert result.dataframe is None
    assert result.message  # message explicatif non vide, pas d'exception levée


def test_load_returns_explicit_failure_on_missing_canonical_columns(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(
        tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv",
        "time,price\n2024-01-01 00:00:00,100\n",
    )

    source = LocalCsvMarketDataSource()
    result = source.load("NASDAQ", "M3")

    assert result.ok is False
    assert result.dataframe is None
    assert "manquantes" in result.message
