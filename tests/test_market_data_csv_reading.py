"""
tests/test_market_data_csv_reading.py — Tests de market_data/csv_reading.py.

Module extrait de market_data/adapters/local_csv.py (Phase 11) pour être partagé avec
SingleFileCsvMarketDataSource sans dupliquer la logique de lecture/validation CSV.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from market_data.csv_reading import read_canonical_csv, read_raw_validated_csv
from market_data.schema import CANONICAL_COLUMNS


def _write_csv(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_read_canonical_csv_normalizes_columns(tmp_path):
    path = tmp_path / "data.csv"
    _write_csv(path, "time,open,high,low,close,volume\n2024-01-01 00:00:00,100,105,99,101,10\n")

    outcome = read_canonical_csv(path)

    assert outcome.ok is True
    assert list(outcome.dataframe.columns) == list(CANONICAL_COLUMNS)
    assert len(outcome.dataframe) == 1


def test_read_canonical_csv_fills_missing_volume_with_na(tmp_path):
    path = tmp_path / "data.csv"
    _write_csv(path, "time,open,high,low,close\n2024-01-01 00:00:00,100,105,99,101\n")

    outcome = read_canonical_csv(path)

    assert outcome.ok is True
    assert outcome.dataframe["volume"].isna().all()


def test_read_canonical_csv_reports_missing_columns(tmp_path):
    path = tmp_path / "data.csv"
    _write_csv(path, "time,open,high\n2024-01-01 00:00:00,100,105\n")

    outcome = read_canonical_csv(path)

    assert outcome.ok is False
    assert outcome.dataframe is None
    assert "close" in outcome.message


def test_read_canonical_csv_reports_missing_file(tmp_path):
    outcome = read_canonical_csv(tmp_path / "does_not_exist.csv")
    assert outcome.ok is False
    assert outcome.dataframe is None


def test_read_canonical_csv_never_raises_on_garbage_content(tmp_path):
    path = tmp_path / "garbage.csv"
    path.write_bytes(b"\x00\x01\x02not,a,csv,file\xff\xfe")
    outcome = read_canonical_csv(path)
    assert isinstance(outcome.ok, bool)  # ne doit jamais lever, quel que soit le contenu


def test_read_canonical_csv_preserves_extra_non_canonical_columns(tmp_path):
    """Comme le vrai nasdaq_3m.csv (tick_volume, spread) : les colonnes non canoniques ne sont
    jamais perdues silencieusement, seulement déplacées après les colonnes canoniques."""
    path = tmp_path / "data.csv"
    _write_csv(
        path,
        "time,open,high,low,close,tick_volume,spread\n"
        "2024-01-01 00:00:00,100,105,99,101,10,180\n",
    )
    outcome = read_canonical_csv(path)

    assert outcome.ok is True
    assert "tick_volume" in outcome.dataframe.columns
    assert "spread" in outcome.dataframe.columns
    assert "volume" in outcome.dataframe.columns  # synthétisé (NA), comportement canonique
    assert outcome.dataframe["volume"].isna().all()


def test_read_raw_validated_csv_is_a_transparent_passthrough(tmp_path):
    path = tmp_path / "data.csv"
    _write_csv(
        path,
        "time,open,high,low,close,tick_volume,spread\n"
        "2024-01-01 00:00:00,100,105,99,101,10,180\n",
    )
    direct = pd.read_csv(path, parse_dates=["time"])
    outcome = read_raw_validated_csv(path)

    assert outcome.ok is True
    assert list(outcome.dataframe.columns) == list(direct.columns)
    assert "volume" not in outcome.dataframe.columns  # aucune colonne synthétisée
    pd.testing.assert_frame_equal(direct, outcome.dataframe)


def test_read_raw_validated_csv_still_requires_canonical_columns(tmp_path):
    path = tmp_path / "data.csv"
    _write_csv(path, "time,price\n2024-01-01 00:00:00,100\n")
    outcome = read_raw_validated_csv(path)
    assert outcome.ok is False
    assert "manquantes" in outcome.message
