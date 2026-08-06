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


# ═══════════════════════════════════════════════════════════════════════════════
# Unités calendaires (semaine, mois) — voir docs/adr/0004-calendar-timeframe-resampling.md
# ═══════════════════════════════════════════════════════════════════════════════


def test_timeframe_to_minutes_rejects_calendar_units_explicitly():
    # W1/MO1 sont des codes syntaxiquement valides (voir is_derivable) mais n'ont pas de durée
    # fixe en minutes : timeframe_to_minutes() continue de lever ResampleError pour eux.
    with pytest.raises(ResampleError):
        timeframe_to_minutes("W1")
    with pytest.raises(ResampleError):
        timeframe_to_minutes("MO1")


def test_is_derivable_week_and_month_only_from_daily_source():
    assert is_derivable("D1", "W1") is True
    assert is_derivable("D1", "MO1") is True
    assert is_derivable("M3", "W1") is False   # seule une source D1 est autorisée (ADR 0004)
    assert is_derivable("M3", "MO1") is False
    assert is_derivable("H4", "W1") is False
    assert is_derivable("W1", "D1") is False   # pas de dérivation inverse
    assert is_derivable("D1", "W2") is False   # seul le multiplicateur 1 est pris en charge


def _daily_dataframe(start: str, periods: int):
    return pd.DataFrame(
        {
            "time": pd.date_range(start, periods=periods, freq="1D"),
            "open": [100 + i for i in range(periods)],
            "high": [105 + i for i in range(periods)],
            "low": [95 + i for i in range(periods)],
            "close": [102 + i for i in range(periods)],
            "volume": [10 + i for i in range(periods)],
        }
    )


def test_resample_ohlcv_daily_to_weekly_aggregates_monday_to_sunday():
    # Lundi 2024-01-01 -> dimanche 2024-01-14 : deux semaines complètes (7 + 7 jours).
    df = _daily_dataframe("2024-01-01", periods=14)

    result = resample_ohlcv(df, source_timeframe="D1", target_timeframe="W1")

    assert len(result.dataframe) == 2
    first_week = result.dataframe.iloc[0]
    assert first_week["time"] == pd.Timestamp("2024-01-01")  # étiqueté par le lundi
    assert first_week["open"] == df["open"].iloc[0]      # premier open de la semaine
    assert first_week["high"] == df["high"].iloc[0:7].max()
    assert first_week["low"] == df["low"].iloc[0:7].min()
    assert first_week["close"] == df["close"].iloc[6]    # dernier close de la semaine
    assert first_week["volume"] == df["volume"].iloc[0:7].sum()
    assert result.incomplete_last_bar is False  # la source couvre bien jusqu'au dimanche


def test_resample_ohlcv_daily_to_weekly_flags_incomplete_last_week():
    # Lundi 2024-01-01 -> mercredi 2024-01-03 : la semaine n'est pas terminée dans la source.
    df = _daily_dataframe("2024-01-01", periods=3)

    result = resample_ohlcv(df, source_timeframe="D1", target_timeframe="W1")

    assert len(result.dataframe) == 1
    assert result.incomplete_last_bar is True
    assert "incomplète" in result.message


def test_resample_ohlcv_daily_to_monthly_aggregates_calendar_month():
    # Janvier 2024 complet (31 jours) + février partiel (5 jours).
    df = _daily_dataframe("2024-01-01", periods=36)

    result = resample_ohlcv(df, source_timeframe="D1", target_timeframe="MO1")

    assert len(result.dataframe) == 2
    january = result.dataframe.iloc[0]
    assert january["time"] == pd.Timestamp("2024-01-01")
    assert january["open"] == df["open"].iloc[0]
    assert january["high"] == df["high"].iloc[0:31].max()
    assert january["low"] == df["low"].iloc[0:31].min()
    assert january["close"] == df["close"].iloc[30]
    assert january["volume"] == df["volume"].iloc[0:31].sum()

    february = result.dataframe.iloc[1]
    assert february["time"] == pd.Timestamp("2024-02-01")
    assert result.incomplete_last_bar is True  # février s'arrête au 5, pas le 29 (2024 bissextile)


def test_resample_ohlcv_daily_to_monthly_complete_month_not_flagged_incomplete():
    df = _daily_dataframe("2024-01-01", periods=31)  # janvier 2024 exactement

    result = resample_ohlcv(df, source_timeframe="D1", target_timeframe="MO1")

    assert len(result.dataframe) == 1
    assert result.incomplete_last_bar is False


def test_resample_ohlcv_rejects_weekly_target_from_non_daily_source():
    df = _m3_dataframe()
    with pytest.raises(ResampleError):
        resample_ohlcv(df, source_timeframe="M3", target_timeframe="W1")
