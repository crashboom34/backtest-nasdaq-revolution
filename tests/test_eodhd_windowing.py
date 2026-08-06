"""
tests/test_eodhd_windowing.py — Tests de market_data/eodhd/windowing.py.

Vérifie le découpage des téléchargements intraday selon les fenêtres réellement documentées par
EODHD (voir market_data/eodhd/windowing.py) : 1m -> 120 jours, 5m -> 600 jours, 1h -> 7200 jours.
Aucun appel réseau : module pur.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.eodhd.errors import EodhdWindowLimitError
from market_data.eodhd.windowing import max_days_for_interval, split_intraday_windows


def test_max_days_for_interval_matches_documented_eodhd_limits():
    assert max_days_for_interval("1m") == 120
    assert max_days_for_interval("5m") == 600
    assert max_days_for_interval("1h") == 7200


def test_max_days_for_interval_rejects_unknown_interval():
    with pytest.raises(ValueError):
        max_days_for_interval("15m")


def test_range_within_a_single_window_returns_one_window():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=10)

    windows = split_intraday_windows(start, end, "1m")

    assert len(windows) == 1
    assert windows[0].start == start
    assert windows[0].end == end


def test_range_longer_than_limit_is_split_into_multiple_windows():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=250)  # > 2 x 120 jours (1m)

    windows = split_intraday_windows(start, end, "1m")

    assert len(windows) == 3
    # Fenêtres contiguës, dans l'ordre chronologique, sans trou ni chevauchement.
    assert windows[0].start == start
    for i in range(len(windows) - 1):
        assert windows[i].end == windows[i + 1].start
    assert windows[-1].end == end
    for window in windows:
        assert (window.end - window.start) <= timedelta(days=120)


def test_windows_never_exceed_the_interval_limit():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=1500)  # nécessite plusieurs fenêtres de 600 jours (5m)

    windows = split_intraday_windows(start, end, "5m")

    for window in windows:
        assert (window.end - window.start) <= timedelta(days=600)
    assert windows[0].start == start
    assert windows[-1].end == end


def test_too_many_windows_raises_explicit_error_instead_of_silently_downloading():
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=120 * 100)  # nécessiterait 100 fenêtres de 1m

    with pytest.raises(EodhdWindowLimitError):
        split_intraday_windows(start, end, "1m", max_windows=10)


def test_start_must_be_strictly_before_end():
    same = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        split_intraday_windows(same, same, "1m")
    with pytest.raises(ValueError):
        split_intraday_windows(same, same - timedelta(days=1), "1m")
