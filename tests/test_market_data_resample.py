"""
tests/test_market_data_resample.py — Tests de market_data/resample.py.

Vérifie les règles documentées dans docs/adr/0003-timeframe-resampling-rules.md :
  - conversion de code timeframe en minutes ;
  - compatibilité stricte (multiple entier, >= source) ;
  - agrégation OHLCV correcte sur un cas simple, à la main ;
  - détection de la dernière bougie incomplète ;
  - erreurs explicites (jamais d'exception silencieuse ou de résultat faux) pour les cas
    incompatibles, les colonnes manquantes et les données vides.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.resample import ResampleError, is_derivable, resample_ohlcv, timeframe_to_minutes


def test_timeframe_to_minutes_parses_known_units():
    assert timeframe_to_minutes("M3") == 3
    assert timeframe_to_minutes("M15") == 15
    assert timeframe_to_minutes("H1") == 60
    assert timeframe_to_minutes("H4") == 240
    assert timeframe_to_minutes("D1") == 1440


def test_timeframe_to_minutes_rejects_unknown_format():
    with pytest.raises(ResampleError):
        timeframe_to_minutes("W1")
    with pytest.raises(ResampleError):
        timeframe_to_minutes("M0")
    with pytest.raises(ResampleError):
        timeframe_to_minutes("")


def test_is_derivable_allows_exact_multiples_only():
    assert is_derivable("M3", "M15") is True   # 15 = 3 * 5
    assert is_derivable("M3", "M3") is True    # identité
    assert is_derivable("M3", "M5") is False   # pas un multiple
    assert is_derivable("M5", "M3") is False   # cible < source
    assert is_derivable("H1", "M30") is False  # cible < source


def _m3_dataframe():
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01 00:00:00", periods=5, freq="3min"),
            "open": [100, 101, 103, 104, 105],
            "high": [105, 106, 107, 108, 109],
            "low": [99, 100, 102, 103, 104],
            "close": [101, 103, 104, 105, 106],
            "volume": [10, 11, 12, 13, 14],
        }
    )


def test_resample_ohlcv_aggregates_complete_bucket_correctly():
    df = _m3_dataframe()

    result = resample_ohlcv(df, source_timeframe="M3", target_timeframe="M15")

    assert len(result.dataframe) == 1
    row = result.dataframe.iloc[0]
    assert row["time"] == pd.Timestamp("2024-01-01 00:00:00")
    assert row["open"] == 100     # first
    assert row["high"] == 109     # max
    assert row["low"] == 99       # min
    assert row["close"] == 106    # last
    assert row["volume"] == 60    # sum
    assert result.incomplete_last_bar is False


def test_resample_ohlcv_flags_incomplete_last_bucket():
    df = _m3_dataframe().iloc[:3]  # seulement 3 des 5 bougies M3 attendues sur le bucket M15

    result = resample_ohlcv(df, source_timeframe="M3", target_timeframe="M15")

    assert len(result.dataframe) == 1
    assert result.incomplete_last_bar is True
    assert "incomplète" in result.message


def test_resample_ohlcv_same_timeframe_returns_input_unchanged():
    df = _m3_dataframe()

    result = resample_ohlcv(df, source_timeframe="M3", target_timeframe="M3")

    assert len(result.dataframe) == len(df)
    assert result.incomplete_last_bar is False
    assert list(result.dataframe["close"]) == list(df["close"])


def test_resample_ohlcv_rejects_incompatible_timeframe():
    df = _m3_dataframe()

    with pytest.raises(ResampleError):
        resample_ohlcv(df, source_timeframe="M3", target_timeframe="M5")


def test_resample_ohlcv_rejects_missing_canonical_columns():
    df = _m3_dataframe().drop(columns=["close"])

    with pytest.raises(ResampleError):
        resample_ohlcv(df, source_timeframe="M3", target_timeframe="M15")


def test_resample_ohlcv_handles_empty_dataframe():
    df = _m3_dataframe().iloc[0:0]

    result = resample_ohlcv(df, source_timeframe="M3", target_timeframe="M15")

    assert result.dataframe.empty
    assert result.incomplete_last_bar is False
