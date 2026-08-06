"""
tests/test_market_data_single_file_csv_adapter.py — Tests de
market_data/adapters/single_file_csv.py (SingleFileCsvMarketDataSource).

Contrairement à LocalCsvMarketDataSource (résolution asset/timeframe via path_resolver), cet
adaptateur enveloppe un chemin CSV déjà connu à l'avance — utilisé par optimizer_process.py/
optimizer.py pour charger `config.data_file` via le port MarketDataSource plutôt qu'un appel
direct à engine.load_data() (Phase 11, façade de compatibilité).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.adapters.single_file_csv import SingleFileCsvMarketDataSource
from market_data.ports import MarketDataSource
from market_data.schema import CANONICAL_COLUMNS


def _write_csv(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_satisfies_the_market_data_source_protocol(tmp_path):
    source = SingleFileCsvMarketDataSource(tmp_path / "whatever.csv")
    assert isinstance(source, MarketDataSource)


def test_load_ignores_asset_and_timeframe_arguments(tmp_path):
    path = tmp_path / "data.csv"
    _write_csv(path, "time,open,high,low,close,volume\n2024-01-01 00:00:00,100,105,99,101,10\n")
    source = SingleFileCsvMarketDataSource(path)

    result_a = source.load("ANYTHING", "M3")
    result_b = source.load("SOMETHING_ELSE", "H1")

    assert result_a.ok is True
    assert result_b.ok is True
    assert list(result_a.dataframe["close"]) == list(result_b.dataframe["close"])


def test_load_returns_canonical_dataframe(tmp_path):
    path = tmp_path / "data.csv"
    _write_csv(
        path,
        "time,open,high,low,close,volume\n"
        "2024-01-01 00:00:00,100,105,99,101,10\n"
        "2024-01-01 00:03:00,101,106,100,103,11\n",
    )
    source = SingleFileCsvMarketDataSource(path)

    result = source.load("job", "job")
    assert result.ok is True
    assert list(result.dataframe.columns) == list(CANONICAL_COLUMNS)
    assert len(result.dataframe) == 2


def test_load_returns_explicit_failure_when_file_missing(tmp_path):
    source = SingleFileCsvMarketDataSource(tmp_path / "does_not_exist.csv")
    result = source.load("job", "job")
    assert result.ok is False
    assert result.dataframe is None


def test_list_available_reflects_the_wrapped_file(tmp_path):
    path = tmp_path / "data.csv"
    _write_csv(path, "time,open,high,low,close,volume\n2024-01-01 00:00:00,100,105,99,101,10\n")
    source = SingleFileCsvMarketDataSource(path)

    infos = source.list_available()
    assert len(infos) == 1
    assert infos[0].exists is True


def test_list_available_reports_missing_file_without_exception(tmp_path):
    source = SingleFileCsvMarketDataSource(tmp_path / "does_not_exist.csv")
    infos = source.list_available()
    assert len(infos) == 1
    assert infos[0].exists is False


def test_produces_identical_dataframe_to_a_direct_pandas_read_csv(tmp_path):
    """Passage strictement transparent : aucune colonne ajoutée/retirée/réordonnée, même sur un
    CSV avec des colonnes non canoniques (ex. tick_volume/spread du vrai nasdaq_3m.csv) — voir
    market_data.csv_reading.read_raw_validated_csv()."""
    import pandas as pd

    path = tmp_path / "data.csv"
    _write_csv(
        path,
        "time,open,high,low,close,tick_volume,spread\n"
        "2024-01-01 00:00:00,100,105,99,101,10,180\n",
    )
    direct = pd.read_csv(path, parse_dates=["time"])
    via_adapter = SingleFileCsvMarketDataSource(path).load("job", "job")

    assert via_adapter.ok is True
    assert list(via_adapter.dataframe.columns) == list(direct.columns)
    pd.testing.assert_frame_equal(direct, via_adapter.dataframe)
