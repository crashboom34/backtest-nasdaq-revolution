"""
tests/test_ui_data_center.py — Tests des fonctions d'assemblage de ui_data_center.py
(build_data_center_rows, build_provider_rows), indépendantes de Streamlit.

Le rendu Streamlit (render_data_center_tab) n'est pas testé ici — comme le reste de
l'application (aucun test_app.py n'existe), il sera validé visuellement (Playwright/manuel).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import path_resolver
from market_data.adapters.local_csv import LocalCsvMarketDataSource
from market_data.summary import build_data_center_summary
from ui_data_center import build_data_center_rows, build_provider_rows


def _write_csv(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


_VALID_M3 = (
    "time,open,high,low,close,volume\n"
    "2024-01-01 00:00:00,100,105,99,101,10\n"
    "2024-01-01 00:03:00,101,106,100,103,11\n"
)


def test_build_data_center_rows_for_existing_dataset(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    _write_csv(tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv", _VALID_M3)

    summaries = build_data_center_summary(LocalCsvMarketDataSource())
    rows = build_data_center_rows(summaries)

    matching = [r for r in rows if r["Actif"] == "NASDAQ" and r["Timeframe"] == "M3"]
    assert len(matching) == 1
    row = matching[0]
    assert row["Disponible"] == "Oui"
    assert row["Lignes"] == 2
    assert row["Qualité (score)"] == "100.0 %"
    assert row["Anomalies"] == "—"
    assert row["UT calculables"] > 0


def test_build_data_center_rows_for_missing_dataset_shows_dashes(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)

    summaries = build_data_center_summary(LocalCsvMarketDataSource())
    rows = build_data_center_rows(summaries)

    assert len(rows) == 1
    row = rows[0]
    assert row["Disponible"] == "Non"
    assert row["Lignes"] == "—"
    assert row["Qualité (score)"] == "—"


def test_build_data_center_rows_reports_quality_anomalies(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    dirty_csv = (
        "time,open,high,low,close,volume\n"
        "2024-01-01 00:00:00,100,105,99,101,10\n"
        "2024-01-01 00:00:00,101,106,100,103,11\n"  # timestamp dupliqué
    )
    _write_csv(tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv", dirty_csv)

    summaries = build_data_center_summary(LocalCsvMarketDataSource())
    rows = build_data_center_rows(summaries)

    row = rows[0]
    assert row["Qualité (score)"] != "100.0 %"
    assert "duplicate_bar" in row["Anomalies"]


def test_build_provider_rows_never_exposes_the_secret_value(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKTEST_EODHD_API_KEY", "super-secret-value")
    isolated_path = tmp_path / "data_providers.json"

    rows = build_provider_rows(providers=("eodhd", "ig"), path=isolated_path)

    eodhd_row = next(r for r in rows if r["Fournisseur"] == "EODHD")
    assert eodhd_row["Configuré"] == "Oui"
    assert eodhd_row["Origine"] == "env"
    assert "super-secret-value" not in eodhd_row["Détail"]

    ig_row = next(r for r in rows if r["Fournisseur"] == "IG")
    assert ig_row["Configuré"] == "Non"


def test_build_provider_rows_covers_all_known_future_providers(tmp_path):
    rows = build_provider_rows(path=tmp_path / "data_providers.json")

    names = {r["Fournisseur"] for r in rows}
    assert names == {"EODHD", "DUKASCOPY", "FIRSTRATE", "IG", "BINANCE", "ALPACA"}
