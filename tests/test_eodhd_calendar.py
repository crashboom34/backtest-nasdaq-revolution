"""
tests/test_eodhd_calendar.py — Tests de market_data/eodhd/calendar.py.

Utilise l'échantillon réel capturé via le MCP EODHD le 2026-08-06 (exchange "US") — jamais un
format deviné. Vérifie le parsing en structure exploitable (fuseau, heures UTC, jours ouvrés,
jours fériés) et les fonctions de calendrier (is_trading_day, is_holiday).
"""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.eodhd.calendar import ExchangeCalendar, is_trading_day, parse_exchange_calendar

_REAL_US_EXCHANGE_DETAILS_SAMPLE = {
    "Name": "USA Stocks", "Code": "US", "Country": "USA", "Currency": "USD",
    "Timezone": "America/New_York",
    "ExchangeHolidays": {
        "0": {"Holiday": "Washington's Birthday", "Date": "2026-02-16", "Type": "official"},
        "1": {"Holiday": "Good Friday", "Date": "2026-04-03", "Type": "official"},
    },
    "ExchangeEarlyCloseDays": {
        "0": {"Holiday": "Post-Thanksgiving Day Friday 2026", "Date": "2026-11-27",
              "Type": "official", "EarlyClose": "13:00"},
    },
    "isOpen": False,
    "TradingHours": {
        "Open": "09:30:00", "Close": "16:00:00", "OpenUTC": "13:30:00", "CloseUTC": "20:00:00",
        "WorkingDays": "Mon,Tue,Wed,Thu,Fri",
    },
    "ActiveTickers": 51550,
}


def test_parse_exchange_calendar_extracts_timezone_and_hours():
    calendar = parse_exchange_calendar(_REAL_US_EXCHANGE_DETAILS_SAMPLE)

    assert isinstance(calendar, ExchangeCalendar)
    assert calendar.exchange_code == "US"
    assert calendar.timezone == "America/New_York"
    assert calendar.open_utc == "13:30:00"
    assert calendar.close_utc == "20:00:00"
    assert calendar.working_days == ("Mon", "Tue", "Wed", "Thu", "Fri")


def test_parse_exchange_calendar_extracts_holidays():
    calendar = parse_exchange_calendar(_REAL_US_EXCHANGE_DETAILS_SAMPLE)

    assert date(2026, 2, 16) in calendar.holidays
    assert date(2026, 4, 3) in calendar.holidays
    assert len(calendar.holidays) == 2


def test_parse_exchange_calendar_extracts_early_close_days():
    calendar = parse_exchange_calendar(_REAL_US_EXCHANGE_DETAILS_SAMPLE)
    assert date(2026, 11, 27) in calendar.early_close_days


def test_parse_exchange_calendar_tolerates_missing_optional_fields():
    minimal = {"Code": "US", "Timezone": "America/New_York"}
    calendar = parse_exchange_calendar(minimal)
    assert calendar.holidays == ()
    assert calendar.working_days == ()


def test_is_trading_day_true_on_a_regular_weekday():
    calendar = parse_exchange_calendar(_REAL_US_EXCHANGE_DETAILS_SAMPLE)
    # 2026-08-04 est un mardi, pas un jour férié listé.
    assert is_trading_day(calendar, date(2026, 8, 4)) is True


def test_is_trading_day_false_on_a_weekend():
    calendar = parse_exchange_calendar(_REAL_US_EXCHANGE_DETAILS_SAMPLE)
    # 2026-08-08 est un samedi.
    assert is_trading_day(calendar, date(2026, 8, 8)) is False


def test_is_trading_day_false_on_a_holiday():
    calendar = parse_exchange_calendar(_REAL_US_EXCHANGE_DETAILS_SAMPLE)
    assert is_trading_day(calendar, date(2026, 4, 3)) is False  # Good Friday


def test_is_trading_day_true_on_an_early_close_day():
    calendar = parse_exchange_calendar(_REAL_US_EXCHANGE_DETAILS_SAMPLE)
    # Fermeture anticipée != fermé : la séance a bien lieu, juste plus courte.
    assert is_trading_day(calendar, date(2026, 11, 27)) is True
