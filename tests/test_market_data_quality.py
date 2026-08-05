"""
tests/test_market_data_quality.py — Tests de market_data/quality.py.

Vérifie que analyze_quality() constate les anomalies sans jamais modifier les données ni lever
d'exception sur des données simplement imparfaites (seules des colonnes manquantes lèvent).
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.quality import analyze_quality


def _clean_df():
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01 00:00:00", periods=3, freq="3min"),
            "open": [100, 101, 102],
            "high": [105, 106, 107],
            "low": [99, 100, 101],
            "close": [101, 102, 103],
            "volume": [10, 11, 12],
        }
    )


def test_clean_dataset_has_no_flags_and_full_score():
    report = analyze_quality(_clean_df())

    assert report.row_count == 3
    assert report.quality_flags == ()
    assert report.quality_score_pct == 100.0
    assert report.duplicate_timestamps == 0
    assert report.invalid_ohlc == 0
    assert report.out_of_order is False


def test_duplicate_timestamps_are_flagged():
    df = _clean_df()
    df.loc[1, "time"] = df.loc[0, "time"]

    report = analyze_quality(df)

    assert report.duplicate_timestamps == 1
    assert "duplicate_bar" in report.quality_flags
    assert report.quality_score_pct < 100.0


def test_invalid_ohlc_high_below_low_is_flagged():
    df = _clean_df()
    df.loc[0, "high"] = 50  # high < low pour cette ligne

    report = analyze_quality(df)

    assert report.invalid_ohlc == 1
    assert "invalid_ohlc" in report.quality_flags


def test_non_positive_price_is_flagged():
    df = _clean_df()
    df.loc[0, "close"] = 0

    report = analyze_quality(df)

    assert report.non_positive_prices == 1
    assert "non_positive_price" in report.quality_flags


def test_missing_value_is_flagged():
    df = _clean_df()
    df.loc[0, "close"] = None

    report = analyze_quality(df)

    assert report.missing_values == 1
    assert "missing_value" in report.quality_flags


def test_out_of_order_rows_are_flagged():
    df = _clean_df()
    df = df.iloc[::-1].reset_index(drop=True)

    report = analyze_quality(df)

    assert report.out_of_order is True
    assert "out_of_order" in report.quality_flags


def test_empty_dataframe_returns_empty_dataset_flag_without_dividing_by_zero():
    df = _clean_df().iloc[0:0]

    report = analyze_quality(df)

    assert report.row_count == 0
    assert report.quality_flags == ("empty_dataset",)
    assert report.quality_score_pct == 0.0


def test_missing_canonical_columns_raises_value_error():
    df = _clean_df().drop(columns=["close"])

    with pytest.raises(ValueError):
        analyze_quality(df)


def test_analyze_quality_never_mutates_input_dataframe():
    df = _clean_df()
    original = df.copy()

    analyze_quality(df)

    pd.testing.assert_frame_equal(df, original)
