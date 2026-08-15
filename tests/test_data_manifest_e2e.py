"""
tests/test_data_manifest_e2e.py — AF-DATA-04A : preuve end-to-end du vrai câblage
content_hash/snapshot_id/period_start/period_end à travers le vrai `optimizer_process.py` (en
subprocess, comme un job réel), pas une injection manuelle de valeurs dans job_store.

Données synthétiques minimales (jamais nasdaq_3m.csv), BACKTEST_BASE_DIR isolé (tmp_path) — même
motif que tests/test_job_resume.py, dupliqué localement pour garder ce fichier indépendant.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import optimization_store as store
import job_launcher as jl
from market_data.content_hash import content_hash


def _synth_ohlcv_csv(path, n_days=3):
    """Petit échantillon OHLCV synthétique (M3), suffisant pour dépasser WARMUP=130.
    Déterministe (seed fixe) : les bornes period_start/period_end attendues se dérivent de ce
    même générateur, jamais codées en dur séparément."""
    rng = np.random.default_rng(123)
    rows = []
    price = 20000.0
    start = pd.Timestamp("2026-01-05 00:00:00")  # lundi
    day = 0
    added = 0
    while added < n_days:
        d = start + pd.Timedelta(days=day)
        day += 1
        if d.weekday() >= 5:
            continue
        added += 1
        for m in range(0, 24 * 60, 3):
            ts = d + pd.Timedelta(minutes=m)
            price = max(100.0, price + rng.normal(0, 3.0))
            o = price
            h = o + abs(rng.normal(0, 4))
            l = o - abs(rng.normal(0, 4))
            c = o + rng.normal(0, 2)
            v = int(abs(rng.normal(500, 100)))
            rows.append((ts, o, h, l, c, v))
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df.to_csv(path, index=False)
    return df  # retourné pour dériver les bornes attendues, jamais codées en dur


def _minimal_config(data_file, run_id):
    strat_spec = importlib.util.spec_from_file_location(
        "prv1_manifest_e2e_test", os.path.join(REPO_ROOT, "strategies", "perfect_revolution_v1.py")
    )
    strat_mod = importlib.util.module_from_spec(strat_spec)
    strat_spec.loader.exec_module(strat_mod)

    return {
        "run_id": run_id,
        "strategy_module": os.path.join(REPO_ROOT, "strategies", "perfect_revolution_v1.py"),
        "strategy_name": strat_mod.STRATEGY_NAME,
        "data_file": str(data_file),
        "base_params": strat_mod.DEFAULT_PARAMS,
        "param_ranges": [
            {"name": "stop_pct", "param_type": "number", "label": "Stop %",
             "min_val": 0.8, "max_val": 1.2, "step": 0.4, "options": None, "enabled": True},
        ],
        "mode": "grid",
        "score_weights": {
            "profit_factor": 3.0, "max_drawdown": 3.0, "total_trades": 2.0,
            "max_consecutive_losses": 2.0, "pct_gain": 2.0, "win_rate": 1.0,
            "avg_win_loss_ratio": 1.5, "equity_regularity": 1.5, "recovery_factor": 1.0,
        },
        "filters": {
            "min_trades": 0, "max_drawdown_pct": 100.0, "min_profit_factor": 0.0,
            "max_consecutive_losses": 100, "min_win_rate": 0.0,
        },
        "train_test": {"enabled": False, "split_method": "ratio", "train_ratio": 0.7,
                        "split_date": None, "alert_degradation_pct": 30.0},
        "global_params": {"initial_capital": 10000.0, "spread": 1.0, "slip_in": 0.5, "slip_out": 0.5},
        "n_workers": 1,
        "top_k_save": 5,
        "top_k_display": 5,
        "total_combinations": 2,
        "max_rows": None,
        "benchmark_n_sample": 1,
        "quick_validation_mode": True,
    }


def _run_job_sync(config, timeout=120):
    job_id, job_dir, config_path, cfg = jl.prepare_job_config(config)
    cmd = jl.build_optimizer_command(job_id, config_path, job_dir)
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    assert proc.returncode == 0, f"optimizer_process a échoué:\n{proc.stdout}\n{proc.stderr}"
    return job_id, job_dir


@pytest.fixture
def isolated_job_base(tmp_path, monkeypatch):
    """Isole BACKTEST_BASE_DIR sur un répertoire temporaire — jamais le vrai results/."""
    monkeypatch.setenv("BACKTEST_BASE_DIR", str(tmp_path))
    monkeypatch.delenv("BACKTEST_EODHD_API_KEY", raising=False)
    monkeypatch.delenv("BACKTEST_IG_API_KEY", raising=False)
    monkeypatch.delenv("BACKTEST_IG_PASSWORD", raising=False)
    importlib.reload(store)
    importlib.reload(jl)
    return tmp_path


def test_real_pipeline_produces_a_coherent_data_manifest(isolated_job_base, tmp_path):
    """K + test end-to-end permanent (§17) : un vrai job optimizer_process.py sur un CSV
    synthétique produit un data_manifest.json avec content_hash/snapshot_id/period_start/
    period_end/source_timeframe réels et cohérents — pas des valeurs injectées à la main."""
    csv_dir = tmp_path / "csv_source"
    csv_dir.mkdir()
    csv_path = csv_dir / "synth.csv"
    synth_df = _synth_ohlcv_csv(csv_path, n_days=3)
    expected_hash = content_hash(csv_path)
    expected_snapshot_id = f"local_csv:sha256:{expected_hash}"
    expected_period_start = pd.Timestamp(synth_df["time"].min()).tz_localize("UTC").isoformat()
    expected_period_end = pd.Timestamp(synth_df["time"].max()).tz_localize("UTC").isoformat()

    cfg = _minimal_config(csv_path, run_id="af_data_04a_e2e_stable")
    _job_id, job_dir = _run_job_sync(cfg)

    manifest_path = os.path.join(job_dir, "data_manifest.json")
    assert os.path.isfile(manifest_path)
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["provider"] == "local_csv"
    assert manifest["content_hash"] == expected_hash
    assert manifest["snapshot_id"] == expected_snapshot_id
    assert manifest["period_start"] == expected_period_start
    assert manifest["period_end"] == expected_period_end
    assert manifest["source_timeframe"] == "M3"


def test_real_pipeline_period_bounds_are_not_altered_by_opt_date_filters(isolated_job_base, tmp_path):
    """H, I, J : period_start/period_end décrivent le dataset SOURCE COMPLET, jamais la
    sélection réduite par opt_start_date/opt_end_date/max_rows (Track R, hors scope DATA) —
    prouvé via le vrai pipeline, pas seulement par construction du code."""
    csv_dir = tmp_path / "csv_source"
    csv_dir.mkdir()
    csv_path = csv_dir / "synth.csv"
    synth_df = _synth_ohlcv_csv(csv_path, n_days=3)
    expected_period_start = pd.Timestamp(synth_df["time"].min()).tz_localize("UTC").isoformat()
    expected_period_end = pd.Timestamp(synth_df["time"].max()).tz_localize("UTC").isoformat()

    cfg = _minimal_config(csv_path, run_id="af_data_04a_e2e_filtered")
    # Filtre Track R appliqué : ne doit réduire QUE les lignes utilisées par l'optimisation,
    # jamais les bornes DATA du dataset source dans le manifeste.
    cfg["opt_start_date"] = "2026-01-06"
    cfg["opt_end_date"] = "2026-01-06"
    cfg["max_rows"] = 50

    _job_id, job_dir = _run_job_sync(cfg)

    manifest_path = os.path.join(job_dir, "data_manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["period_start"] == expected_period_start
    assert manifest["period_end"] == expected_period_end
