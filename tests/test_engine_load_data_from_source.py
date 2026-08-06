"""
tests/test_engine_load_data_from_source.py — Équivalence entre engine.load_data() (chemin CSV
direct, utilisé partout dans l'application) et engine.load_data_from_source() (nouveau chemin
additif via market_data.ports.MarketDataSource, pas encore appelé ailleurs).

Objectif : prouver que brancher le port ne change aucun comportement — load_data() reste
inchangé, load_data_from_source() produit exactement le même résultat sur le même fichier.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import path_resolver
from engine import load_data, load_data_from_source
from market_data.adapters.local_csv import LocalCsvMarketDataSource
from market_data.adapters.single_file_csv import SingleFileCsvMarketDataSource
from market_data.schema import MarketDataResult, MarketDatasetInfo

_CSV_CONTENT = (
    "time,open,high,low,close,volume\n"
    "2024-01-01 00:00:00,100,105,99,101,10\n"
    "2024-01-01 00:03:00,101,106,100,103,11\n"
    "2024-01-01 00:06:00,103,107,102,104,12\n"
)


def _write_csv(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_load_data_from_source_matches_load_data_exactly(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    csv_path = tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv"
    _write_csv(csv_path, _CSV_CONTENT)

    via_direct_path = load_data(str(csv_path))
    via_port = load_data_from_source(LocalCsvMarketDataSource(), "NASDAQ", "M3")

    pd.testing.assert_frame_equal(via_direct_path, via_port)


def test_load_data_from_source_has_same_derived_columns_as_load_data(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    csv_path = tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv"
    _write_csv(csv_path, _CSV_CONTENT)

    result = load_data_from_source(LocalCsvMarketDataSource(), "NASDAQ", "M3")

    for col in ("time", "open", "high", "low", "close", "time_paris", "date_p", "h_p", "m_p", "dow_p", "hm_p"):
        assert col in result.columns


def test_load_data_from_source_raises_explicit_error_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)

    with pytest.raises(ValueError, match="NASDAQ/M3"):
        load_data_from_source(LocalCsvMarketDataSource(), "NASDAQ", "M3")


class _FakeAlwaysOkSource:
    """Source minimale conforme au port, indépendante de LocalCsvMarketDataSource, pour
    prouver que load_data_from_source() fonctionne avec n'importe quel MarketDataSource."""

    def list_available(self):
        return []

    def load(self, asset, timeframe):
        info = MarketDatasetInfo(
            provider="fake", asset=asset, timeframe=timeframe, source="fake", exists=True
        )
        df = pd.DataFrame(
            {
                "time": pd.to_datetime(["2024-01-01 00:00:00", "2024-01-01 00:03:00"]),
                "open": [1.0, 2.0],
                "high": [1.5, 2.5],
                "low": [0.5, 1.5],
                "close": [1.2, 2.2],
                "volume": [10, 20],
            }
        )
        return MarketDataResult(info=info, dataframe=df, ok=True, message="OK")


def test_load_data_from_source_works_with_any_conforming_source():
    result = load_data_from_source(_FakeAlwaysOkSource(), "FAKE", "M1")

    assert len(result) == 2
    assert "time_paris" in result.columns


def test_single_file_csv_source_matches_load_data_exactly(tmp_path):
    """Même équivalence que LocalCsvMarketDataSource ci-dessus, pour l'adaptateur utilisé par
    optimizer_process.py/optimizer.py (Phase 11, façade de compatibilité) — prouve que le swap
    load_data(config.data_file) -> load_data_from_source(SingleFileCsvMarketDataSource(...))
    est strictement transparent."""
    csv_path = tmp_path / "any_path.csv"
    _write_csv(csv_path, _CSV_CONTENT)

    via_direct_path = load_data(str(csv_path))
    via_port = load_data_from_source(SingleFileCsvMarketDataSource(csv_path), "job", "job")

    pd.testing.assert_frame_equal(via_direct_path, via_port)


@pytest.mark.skipif(
    not os.path.isfile(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nasdaq_3m.csv")),
    reason="nasdaq_3m.csv absent (fichier volumineux non versionné) — test seulement possible en local",
)
def test_single_file_csv_source_matches_load_data_on_the_real_nasdaq_csv():
    """Caractérisation la plus forte possible (Phase 11) : équivalence vérifiée sur le vrai
    fichier de production, lu en lecture seule, jamais modifié."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    real_csv = os.path.join(repo_root, "nasdaq_3m.csv")

    via_direct_path = load_data(real_csv)
    via_port = load_data_from_source(SingleFileCsvMarketDataSource(real_csv), "job", "job")

    pd.testing.assert_frame_equal(via_direct_path, via_port)
