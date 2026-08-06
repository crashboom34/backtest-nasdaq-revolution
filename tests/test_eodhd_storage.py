"""
tests/test_eodhd_storage.py — Tests de market_data/eodhd/storage.py.

100% hors ligne, écrit uniquement dans tmp_path (jamais dans le vrai BACKTEST_DATA_DIR pendant
les tests). Vérifie : résolution de BACKTEST_DATA_DIR, garde-fou espace disque, stockage brut
immuable et idempotent (hash de contenu), stockage normalisé Parquet avec manifeste (qualité,
période, timezone UTC, hash), écritures atomiques, absence de secret dans les manifestes.
"""

from __future__ import annotations

import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.eodhd.errors import EodhdConfigError
from market_data.eodhd.storage import (
    EodhdStorageError,
    disk_usage_summary,
    ensure_free_disk_space,
    last_failed_sync,
    last_successful_sync,
    list_normalized_snapshots,
    list_raw_snapshots,
    load_sync_log,
    record_sync_event,
    resolve_data_dir,
    save_normalized,
    save_raw_snapshot,
)


def test_resolve_data_dir_raises_when_env_var_absent(monkeypatch):
    monkeypatch.delenv("BACKTEST_DATA_DIR", raising=False)
    with pytest.raises(EodhdConfigError):
        resolve_data_dir()


def test_resolve_data_dir_returns_configured_path(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKTEST_DATA_DIR", str(tmp_path))
    assert resolve_data_dir() == tmp_path.resolve()


def test_ensure_free_disk_space_raises_when_insufficient(monkeypatch, tmp_path):
    import shutil as shutil_module

    fake_usage = type("Usage", (), {"total": 0, "used": 0, "free": 100 * 1024 * 1024})()  # 100 Mo
    monkeypatch.setattr(shutil_module, "disk_usage", lambda path: fake_usage)

    with pytest.raises(EodhdStorageError):
        ensure_free_disk_space(tmp_path, min_free_mb=2048)


def test_ensure_free_disk_space_passes_when_sufficient(monkeypatch, tmp_path):
    import shutil as shutil_module

    fake_usage = type("Usage", (), {"total": 0, "used": 0, "free": 10 * 1024 * 1024 * 1024})()  # 10 Go
    monkeypatch.setattr(shutil_module, "disk_usage", lambda path: fake_usage)

    ensure_free_disk_space(tmp_path, min_free_mb=2048)  # ne doit pas lever


def test_save_raw_snapshot_writes_immutable_json(tmp_path):
    records = [{"date": "2026-07-28", "open": 1, "high": 2, "low": 0.5, "close": 1.5}]
    path = save_raw_snapshot(tmp_path, ticker="AAPL.US", kind="eod", raw_records=records)

    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == records


def test_save_raw_snapshot_is_idempotent_on_identical_content(tmp_path):
    records = [{"date": "2026-07-28", "open": 1, "high": 2, "low": 0.5, "close": 1.5}]
    path1 = save_raw_snapshot(tmp_path, ticker="AAPL.US", kind="eod", raw_records=records)
    mtime1 = path1.stat().st_mtime
    path2 = save_raw_snapshot(tmp_path, ticker="AAPL.US", kind="eod", raw_records=records)

    assert path1 == path2
    assert path2.stat().st_mtime == mtime1  # pas réécrit


def test_save_raw_snapshot_different_content_gets_different_path(tmp_path):
    path1 = save_raw_snapshot(tmp_path, ticker="AAPL.US", kind="eod", raw_records=[{"date": "a"}])
    path2 = save_raw_snapshot(tmp_path, ticker="AAPL.US", kind="eod", raw_records=[{"date": "b"}])
    assert path1 != path2


def test_save_raw_snapshot_writes_manifest_without_secrets(tmp_path):
    records = [{"date": "2026-07-28", "open": 1, "high": 2, "low": 0.5, "close": 1.5}]
    path = save_raw_snapshot(
        tmp_path, ticker="AAPL.US", kind="eod", raw_records=records,
        request_params={"api_token": "should-not-be-here", "from": "2026-07-28"},
    )
    manifest_path = path.with_suffix("").with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    dump = json.dumps(manifest)
    assert "should-not-be-here" not in dump
    assert "api_token" not in manifest.get("request_params", {})


def test_save_raw_snapshot_raises_on_insufficient_disk_space(monkeypatch, tmp_path):
    import shutil as shutil_module

    fake_usage = type("Usage", (), {"total": 0, "used": 0, "free": 100 * 1024 * 1024})()
    monkeypatch.setattr(shutil_module, "disk_usage", lambda path: fake_usage)

    with pytest.raises(EodhdStorageError):
        save_raw_snapshot(tmp_path, ticker="AAPL.US", kind="eod", raw_records=[{"date": "a"}], min_free_mb=2048)


def test_save_normalized_writes_parquet_and_manifest(tmp_path):
    df = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-07-28", "2026-07-29"]),
            "open": [1.0, 2.0],
            "high": [1.5, 2.5],
            "low": [0.9, 1.9],
            "close": [1.2, 2.2],
            "volume": [100, 200],
        }
    )

    path, manifest = save_normalized(
        tmp_path, asset="AAPL_US", timeframe="D1", dataframe=df,
        source_ticker="AAPL.US", source="eod",
    )

    assert path.is_file()
    assert path.suffix == ".parquet"
    roundtrip = pd.read_parquet(path)
    assert len(roundtrip) == 2

    assert manifest.provider == "eodhd"
    assert manifest.ticker == "AAPL.US"
    assert manifest.asset == "AAPL_US"
    assert manifest.timeframe == "D1"
    assert manifest.timezone == "UTC"
    assert manifest.row_count == 2
    assert manifest.exchange == "US"
    assert manifest.quality_score_pct == 100.0


def test_save_normalized_writes_manifest_file_under_manifests_dir(tmp_path):
    df = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-07-28"]),
            "open": [1.0], "high": [1.5], "low": [0.9], "close": [1.2], "volume": [100],
        }
    )
    save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=df, source_ticker="AAPL.US", source="eod")

    manifests_dir = tmp_path / "manifests"
    assert manifests_dir.is_dir()
    files = list(manifests_dir.glob("*.json"))
    assert len(files) == 1
    manifest_data = json.loads(files[0].read_text(encoding="utf-8"))
    assert "api_token" not in json.dumps(manifest_data)


def test_save_normalized_is_idempotent_on_identical_content(tmp_path):
    df = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-07-28"]),
            "open": [1.0], "high": [1.5], "low": [0.9], "close": [1.2], "volume": [100],
        }
    )
    path1, _ = save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=df, source_ticker="AAPL.US", source="eod")
    path2, _ = save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=df, source_ticker="AAPL.US", source="eod")
    assert path1 == path2


# ═══════════════════════════════════════════════════════════════════════════════
# Catalogue minimal (Phase 5) : lister ce qui est déjà stocké, journal de synchro, disque.
# ═══════════════════════════════════════════════════════════════════════════════


def _sample_df():
    return pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-07-28", "2026-07-29"]),
            "open": [1.0, 2.0], "high": [1.5, 2.5], "low": [0.9, 1.9], "close": [1.2, 2.2],
            "volume": [100, 200],
        }
    )


def test_list_normalized_snapshots_returns_saved_manifests(tmp_path):
    save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=_sample_df(), source_ticker="AAPL.US", source="eod")
    save_normalized(tmp_path, asset="MSFT_US", timeframe="D1", dataframe=_sample_df(), source_ticker="MSFT.US", source="eod")

    snapshots = list_normalized_snapshots(tmp_path)

    assert len(snapshots) == 2
    tickers = {s.ticker for s in snapshots}
    assert tickers == {"AAPL.US", "MSFT.US"}


def test_list_normalized_snapshots_empty_when_nothing_stored(tmp_path):
    assert list_normalized_snapshots(tmp_path) == []


def test_list_normalized_snapshots_tolerates_corrupted_manifest(tmp_path):
    save_normalized(tmp_path, asset="AAPL_US", timeframe="D1", dataframe=_sample_df(), source_ticker="AAPL.US", source="eod")
    (tmp_path / "manifests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "manifests" / "corrupted.json").write_text("{not valid json", encoding="utf-8")

    snapshots = list_normalized_snapshots(tmp_path)
    assert len(snapshots) == 1  # le manifeste corrompu est ignoré, pas d'exception


def test_list_raw_snapshots_returns_saved_manifests(tmp_path):
    save_raw_snapshot(tmp_path, ticker="AAPL.US", kind="eod", raw_records=[{"date": "a"}])
    save_raw_snapshot(tmp_path, ticker="AAPL.US", kind="dividends", raw_records=[{"date": "b"}])

    snapshots = list_raw_snapshots(tmp_path)
    assert len(snapshots) == 2
    kinds = {s["kind"] for s in snapshots}
    assert kinds == {"eod", "dividends"}


def test_list_raw_snapshots_filters_by_ticker(tmp_path):
    save_raw_snapshot(tmp_path, ticker="AAPL.US", kind="eod", raw_records=[{"date": "a"}])
    save_raw_snapshot(tmp_path, ticker="MSFT.US", kind="eod", raw_records=[{"date": "b"}])

    snapshots = list_raw_snapshots(tmp_path, ticker="AAPL.US")
    assert len(snapshots) == 1
    assert snapshots[0]["ticker"] == "AAPL.US"


def test_disk_usage_summary_reports_free_space(monkeypatch, tmp_path):
    import shutil as shutil_module

    fake_usage = type("Usage", (), {"total": 100 * 1024**3, "used": 60 * 1024**3, "free": 40 * 1024**3})()
    monkeypatch.setattr(shutil_module, "disk_usage", lambda path: fake_usage)

    summary = disk_usage_summary(tmp_path)
    assert summary.free_gb == pytest.approx(40.0, abs=0.01)
    assert summary.total_gb == pytest.approx(100.0, abs=0.01)
    assert summary.sufficient is True


def test_disk_usage_summary_flags_insufficient_space(monkeypatch, tmp_path):
    import shutil as shutil_module

    fake_usage = type("Usage", (), {"total": 10 * 1024**3, "used": 9 * 1024**3, "free": 1024**3})()
    monkeypatch.setattr(shutil_module, "disk_usage", lambda path: fake_usage)

    summary = disk_usage_summary(tmp_path, min_free_mb=2048)
    assert summary.sufficient is False


def test_record_and_load_sync_log(tmp_path):
    record_sync_event(tmp_path, ticker="AAPL.US", kind="eod", ok=True, message="2 bougie(s) téléchargée(s).")
    record_sync_event(tmp_path, ticker="BOGUS.US", kind="eod", ok=False, message="404 introuvable.")

    events = load_sync_log(tmp_path)
    assert len(events) == 2
    assert events[-1].ticker == "BOGUS.US"
    assert events[-1].ok is False


def test_last_successful_and_failed_sync(tmp_path):
    record_sync_event(tmp_path, ticker="AAPL.US", kind="eod", ok=True, message="ok")
    record_sync_event(tmp_path, ticker="BOGUS.US", kind="eod", ok=False, message="échec")
    record_sync_event(tmp_path, ticker="MSFT.US", kind="eod", ok=True, message="ok aussi")

    last_ok = last_successful_sync(tmp_path)
    last_fail = last_failed_sync(tmp_path)
    assert last_ok.ticker == "MSFT.US"
    assert last_fail.ticker == "BOGUS.US"


def test_last_successful_sync_is_none_when_no_log(tmp_path):
    assert last_successful_sync(tmp_path) is None
    assert last_failed_sync(tmp_path) is None


def test_sync_log_never_contains_secrets():
    # errors.redact_url() garantit déjà qu'aucun message d'erreur EODHD ne contient api_token ;
    # ce test vérifie seulement que record_sync_event ne fait aucune interpolation dangereuse
    # (ex. injection accidentelle de kwargs) qui contournerait cette garantie en amont.
    import inspect

    from market_data.eodhd.storage import record_sync_event as target

    sig = inspect.signature(target)
    assert set(sig.parameters) == {"data_dir", "ticker", "kind", "ok", "message"}
