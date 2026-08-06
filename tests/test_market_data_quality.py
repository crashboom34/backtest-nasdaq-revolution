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

from market_data.eodhd.calendar import parse_exchange_calendar
from market_data.quality import analyze_quality, detect_missing_trading_days


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


# ═══════════════════════════════════════════════════════════════════════════════
# detect_missing_trading_days() — additif, nécessite un calendrier (voir Phase 11 suite,
# market_data.eodhd.calendar), lève la limitation documentée depuis Phase 1.
# ═══════════════════════════════════════════════════════════════════════════════

_US_CALENDAR_SAMPLE = {
    "Code": "US", "Timezone": "America/New_York",
    "TradingHours": {"OpenUTC": "13:30:00", "CloseUTC": "20:00:00", "WorkingDays": "Mon,Tue,Wed,Thu,Fri"},
    # Le jour férié (2026-08-10, lundi) est délibérément distinct du "trou" testé plus bas
    # (2026-08-05) : un jour férié n'est jamais un jour de séance, donc jamais un "trou".
    "ExchangeHolidays": {"0": {"Date": "2026-08-10", "Holiday": "Test Holiday", "Type": "official"}},
}


def _daily_df(dates):
    return pd.DataFrame(
        {
            "time": pd.to_datetime(dates),
            "open": [1.0] * len(dates), "high": [1.0] * len(dates),
            "low": [1.0] * len(dates), "close": [1.0] * len(dates), "volume": [1] * len(dates),
        }
    )


def test_detect_missing_trading_days_finds_a_gap():
    calendar = parse_exchange_calendar(_US_CALENDAR_SAMPLE)
    # Lundi 2026-08-03, mardi 04, JEUDI 06 (mercredi 05 manque - pas un jour férié ici).
    df = _daily_df(["2026-08-03", "2026-08-04", "2026-08-06"])

    missing = detect_missing_trading_days(df, calendar)

    from datetime import date
    assert date(2026, 8, 5) in missing
    assert len(missing) == 1


def test_detect_missing_trading_days_ignores_weekends_and_holidays():
    calendar = parse_exchange_calendar(_US_CALENDAR_SAMPLE)
    # Lun 03 -> ven 07 présents, puis week-end (08-09) et lundi férié (10) absents mais PAS des
    # trous (ni jours ouvrés, ni jour de séance), puis mardi 11 présent.
    df = _daily_df(["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-11"])

    missing = detect_missing_trading_days(df, calendar)
    assert missing == ()


def test_detect_missing_trading_days_empty_dataframe_returns_empty_tuple():
    calendar = parse_exchange_calendar(_US_CALENDAR_SAMPLE)
    df = _clean_df().iloc[0:0]
    assert detect_missing_trading_days(df, calendar) == ()


def test_detect_missing_trading_days_requires_time_column():
    calendar = parse_exchange_calendar(_US_CALENDAR_SAMPLE)
    df = pd.DataFrame({"open": [1.0]})
    with pytest.raises(ValueError):
        detect_missing_trading_days(df, calendar)


def test_detect_missing_trading_days_never_mutates_input():
    calendar = parse_exchange_calendar(_US_CALENDAR_SAMPLE)
    df = _daily_df(["2026-08-03", "2026-08-06"])
    original = df.copy()

    detect_missing_trading_days(df, calendar)

    pd.testing.assert_frame_equal(df, original)
