import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import path_resolver


def test_resolve_data_csv_prefers_data_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)

    legacy = tmp_path / "nasdaq_3m.csv"
    legacy.write_text("legacy", encoding="utf-8")
    data_csv = tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv"
    data_csv.parent.mkdir(parents=True)
    data_csv.write_text("data", encoding="utf-8")

    resolved = path_resolver.resolve_data_csv("nasdaq", "m3")

    assert resolved.exists is True
    assert resolved.source == "data"
    assert resolved.path == data_csv.resolve()
    assert resolved.relative_path == "data/NASDAQ/M3/nasdaq_m3.csv"


def test_resolve_data_csv_falls_back_to_legacy_nasdaq_m3(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    legacy = tmp_path / "nasdaq_3m.csv"
    legacy.write_text("legacy", encoding="utf-8")

    resolved = path_resolver.resolve_data_csv("NASDAQ", "M3")

    assert resolved.exists is True
    assert resolved.source == "legacy"
    assert resolved.path == legacy.resolve()
    assert resolved.relative_path == "nasdaq_3m.csv"


def test_available_assets_and_timeframes_include_prepared_data_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    (tmp_path / "data" / "SP500" / "M15").mkdir(parents=True)
    (tmp_path / "data" / "DAX" / "H1").mkdir(parents=True)

    assert path_resolver.list_available_assets(include_legacy=False) == ["DAX", "SP500"]
    assert path_resolver.list_available_timeframes("sp500", include_legacy=False) == ["M15"]
    assert path_resolver.list_available_timeframes("dax", include_legacy=False) == ["H1"]


def test_missing_data_csv_returns_clear_message_without_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)

    resolved = path_resolver.resolve_data_csv("DAX", "H1")

    assert resolved.exists is False
    assert resolved.source == "missing"
    assert "Aucun CSV trouvé pour DAX/H1" in resolved.message


def test_missing_data_csv_can_raise_when_required(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)

    with pytest.raises(FileNotFoundError, match="Aucun CSV trouvé pour DAX/H1"):
        path_resolver.resolve_data_csv("DAX", "H1", required=True)
