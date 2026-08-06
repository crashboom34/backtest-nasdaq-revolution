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
from market_data.eodhd.storage import save_normalized
from market_data.summary import build_data_center_summary
from ui_data_center import (
    build_data_center_rows,
    build_disk_usage_row,
    build_eodhd_catalog_rows,
    build_eodhd_status_row,
    build_ig_status_row,
    build_provider_rows,
    build_sync_status_rows,
    build_unified_catalog_rows,
)


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


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 10 : sections EODHD / IG / stockage de la page Data Center.
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_eodhd_status_row_never_exposes_the_key(monkeypatch):
    monkeypatch.setenv("BACKTEST_EODHD_API_KEY", "super-secret-value")
    row = build_eodhd_status_row()
    assert row["Configuré"] == "Oui"
    assert "super-secret-value" not in str(row)


def test_build_eodhd_status_row_reports_absent():
    row = build_eodhd_status_row()
    assert row["Configuré"] == "Non"


def test_build_ig_status_row_never_exposes_secrets_or_raw_environment(monkeypatch):
    monkeypatch.setenv("BACKTEST_IG_API_KEY", "super-secret-key")
    monkeypatch.setenv("BACKTEST_IG_IDENTIFIER", "my-identifier")
    monkeypatch.setenv("BACKTEST_IG_PASSWORD", "super-secret-password")
    monkeypatch.setenv("BACKTEST_IG_ENVIRONMENT", "demo")

    row = build_ig_status_row()
    dump = str(row)
    assert "super-secret-key" not in dump
    assert "my-identifier" not in dump
    assert "super-secret-password" not in dump
    assert row["Configuré"] == "Oui"
    assert row["Environnement"] == "demo (autorisé)"


def test_build_ig_status_row_never_echoes_a_live_value_verbatim(monkeypatch):
    monkeypatch.setenv("BACKTEST_IG_ENVIRONMENT", "live")
    row = build_ig_status_row()
    assert "live" not in row["Environnement"].lower()
    assert row["Environnement"] == "Valeur non autorisée (accès refusé — seul 'demo' est permis)"


def test_build_ig_status_row_reports_missing_when_nothing_configured():
    row = build_ig_status_row()
    assert row["Configuré"] == "Non"
    assert row["Environnement"] == "Non configuré"


def test_build_disk_usage_row_returns_none_when_data_dir_not_configured(monkeypatch):
    monkeypatch.delenv("BACKTEST_DATA_DIR", raising=False)
    assert build_disk_usage_row() is None


def test_build_disk_usage_row_reports_free_space(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKTEST_DATA_DIR", str(tmp_path))
    row = build_disk_usage_row()
    assert row is not None
    assert "Go" in row["Libre"]


def test_build_eodhd_catalog_rows_empty_when_data_dir_not_configured(monkeypatch):
    monkeypatch.delenv("BACKTEST_DATA_DIR", raising=False)
    assert build_eodhd_catalog_rows() == []


def test_build_eodhd_catalog_rows_lists_stored_snapshots(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKTEST_DATA_DIR", str(tmp_path))
    import pandas as pd

    df = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-07-28", "2026-07-29"]),
            "open": [1.0, 2.0], "high": [1.5, 2.5], "low": [0.9, 1.9], "close": [1.2, 2.2],
            "volume": [100, 200],
        }
    )
    save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=df, source_ticker="AAPL.US", source="eod")

    rows = build_eodhd_catalog_rows()
    assert len(rows) == 1
    assert rows[0]["Symbole fournisseur"] == "AAPL.US"
    assert rows[0]["Lignes"] == 2


def test_build_sync_status_rows_reports_none_when_nothing_synced(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKTEST_DATA_DIR", str(tmp_path))
    rows = build_sync_status_rows()
    by_type = {r["Type"]: r["Détail"] for r in rows}
    assert "Aucune" in by_type["Dernière synchronisation réussie"] or "Aucun" in by_type["Dernière synchronisation réussie"]


def test_build_sync_status_rows_handles_missing_data_dir_gracefully(monkeypatch):
    monkeypatch.delenv("BACKTEST_DATA_DIR", raising=False)
    rows = build_sync_status_rows()
    assert len(rows) == 2  # ne lève jamais, message explicite à la place


def test_build_unified_catalog_rows_combines_local_and_eodhd(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    monkeypatch.setenv("BACKTEST_DATA_DIR", str(tmp_path))
    _write_csv(tmp_path / "data" / "NASDAQ" / "M3" / "nasdaq_m3.csv", _VALID_M3)

    import pandas as pd
    from market_data.eodhd.storage import save_normalized

    save_normalized(
        tmp_path, asset="AAPL_US", timeframe="D1",
        dataframe=pd.DataFrame({
            "time": pd.to_datetime(["2026-07-28"]), "open": [1.0], "high": [1.5],
            "low": [0.9], "close": [1.2], "volume": [100],
        }),
        source_ticker="AAPL.US", source="eod",
    )

    rows = build_unified_catalog_rows()
    providers = {r["Fournisseur"] for r in rows}
    assert providers == {"LOCAL_CSV", "EODHD"}


def test_build_unified_catalog_rows_never_raises_without_data_dir(monkeypatch):
    monkeypatch.delenv("BACKTEST_DATA_DIR", raising=False)
    rows = build_unified_catalog_rows()
    assert isinstance(rows, list)  # au moins la partie CSV local, jamais d'exception
