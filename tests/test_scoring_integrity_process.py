"""Scoring Integrity — `optimizer_process.py` (ADR 0029 : C14/G-7, F-4, version, S-1 L2, G-4, G-5).

Seam : le script `optimizer_process.py` exécuté EN PROCESSUS via `runpy.run_path(run_name="__main__")`
(F-3) avec un faux `engine.run_backtest` — même chemin que `job_launcher`, sans sous-processus,
pour pouvoir compter les backtests réellement lancés.
"""
from __future__ import annotations

import json
import os
import runpy
import sys

import pandas as pd
import pytest

import engine
import job_launcher as jl
from tests.test_job_resume import REPO_ROOT, _minimal_config, _synth_ohlcv_csv, isolated_job_base  # noqa: F401
from tests.test_scoring_integrity_pipeline import GOOD

SCRIPT = os.path.join(REPO_ROOT, "optimizer_process.py")


class CountingEngine:
    def __init__(self, test_result=None):
        self.calls, self.test_result = [], test_result

    def __call__(self, df, strat, params, **kw):
        self.calls.append(kw.get("end_boundary", "inclusive"))
        if kw.get("end_boundary") == "inclusive" and self.test_result is not None and len(self.calls) > 1:
            trades, equity, stats = self.test_result
        else:
            trades, equity, stats = GOOD
        return trades.copy(), equity.copy(), dict(stats)


def run_job(monkeypatch, cfg, fake):
    monkeypatch.setattr(engine, "run_backtest", fake)
    job_id, job_dir, config_path, _ = jl.prepare_job_config(cfg)
    monkeypatch.setattr(sys, "argv", [SCRIPT, job_id, config_path, job_dir])
    error = None
    try:
        runpy.run_path(SCRIPT, run_name="__main__")
    except SystemExit as exc:
        error = exc
    return job_id, job_dir, error


def read_json(job_dir, name):
    path = os.path.join(job_dir, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_r44_config_used_records_the_scoring_semantics(monkeypatch, isolated_job_base, tmp_path):
    cfg = _minimal_config(_synth_ohlcv_csv(tmp_path / "d.csv", n_days=3), run_id="sem_ok")
    _job, job_dir, error = run_job(monkeypatch, cfg, CountingEngine())
    assert error is None
    assert read_json(job_dir, "config_used.json")["scoring_semantics_version"] == "finite-metrics-v1"


def test_r40_g7_invalid_configuration_stops_before_save_config_data_load_and_benchmark(
    monkeypatch, isolated_job_base, tmp_path,
):
    cfg = _minimal_config(_synth_ohlcv_csv(tmp_path / "d.csv", n_days=3), run_id="bad_weights")
    cfg["score_weights"]["win_rate"] = -1.0
    fake = CountingEngine()
    _job, job_dir, error = run_job(monkeypatch, cfg, fake)
    assert error is not None and error.code not in (0, None)
    assert fake.calls == []  # aucun benchmark, aucun backtest
    # `prepare_job_config` écrit la config d'ENTRÉE ; save_config() (qui l'enrichit) n'a pas tourné.
    assert "scoring_semantics_version" not in (read_json(job_dir, "config_used.json") or {})
    progress = read_json(job_dir, "progress.json")
    assert progress["status"] == "error" and "weights.win_rate" in progress["error_message"]


def test_r45_f4_resume_from_legacy_job_is_refused_before_hashes_and_benchmark(
    monkeypatch, isolated_job_base, tmp_path,
):
    data = _synth_ohlcv_csv(tmp_path / "d.csv", n_days=3)
    src_job, src_dir, error = run_job(monkeypatch, _minimal_config(data, run_id="src"), CountingEngine())
    assert error is None
    legacy = read_json(src_dir, "config_used.json")
    legacy.pop("scoring_semantics_version")  # job legacy : clé absente
    with open(os.path.join(src_dir, "config_used.json"), "w", encoding="utf-8") as fh:
        json.dump(legacy, fh)
    import optimization_store
    loaded = []
    monkeypatch.setattr(optimization_store, "load_tested_hashes", lambda *a, **k: loaded.append(1) or set())
    fake = CountingEngine()
    import optimizer
    with pytest.raises(optimizer.ScoringSemanticsMismatch):
        run_job(monkeypatch, _minimal_config(data, run_id="resume", resume_run_id=src_job), fake)
    assert loaded == [] and fake.calls == []


def _tt(cfg):
    cfg["train_test"]["enabled"] = True
    cfg["train_test"]["train_ratio"] = 0.5
    return cfg


def test_r56_g4_g5_invalid_legacy_test_fails_closed(monkeypatch, isolated_job_base, tmp_path):
    trades = GOOD[0].copy()
    trades.loc[0, "resultat_net"] = float("nan")
    cfg = _tt(_minimal_config(_synth_ohlcv_csv(tmp_path / "d.csv", n_days=8), run_id="tt_bad"))
    _job, job_dir, error = run_job(monkeypatch, cfg, CountingEngine(test_result=(trades, GOOD[1], GOOD[2])))
    progress = read_json(job_dir, "progress.json")
    assert progress["status"] == "error"
    assert "INVALID_METRIC:NON_FINITE:trades.resultat_net" in (progress["error_message"] or "")
    assert progress["best_score"] == 0 and progress["best_params"] == {}
    meta = read_json(job_dir, "meta.json")
    assert meta["status"] == "error" and meta["top_100"] == []
    assert "error" in meta.get("report", {})
    metrics = read_json(job_dir, "metrics.json")
    assert metrics is None or "best_score_test" not in metrics


def test_valid_train_test_job_is_unchanged(monkeypatch, isolated_job_base, tmp_path):
    cfg = _tt(_minimal_config(_synth_ohlcv_csv(tmp_path / "d.csv", n_days=8), run_id="tt_ok"))
    _job, job_dir, error = run_job(monkeypatch, cfg, CountingEngine())
    meta = read_json(job_dir, "meta.json")
    assert meta["status"] == "completed" and meta["top_100"]
    assert meta["top_100"][0]["score_test"] == meta["top_100"][0]["score_train"]
