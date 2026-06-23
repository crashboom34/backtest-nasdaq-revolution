import hashlib
import json
from pathlib import Path

import job_launcher
from job_annotations import save_annotation
from job_comparison import load_job_record
from job_decisions import CATEGORY_ACTION, load_decision_events
from retest_plan import (
    RETEST_PLAN_EVENT_DUPLICATED,
    RETEST_PLAN_EVENT_LAUNCHED,
    apply_retest_plan_to_config,
    build_retest_plan,
    record_retest_plan_decision,
)


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job(
    tmp_path: Path,
    job_id: str = "job_retest",
    preset: str = "Test rapide local",
    max_rows=20_000,
    max_combinations=12,
    trades: int | None = 40,
    score: float | None = 35.0,
    drawdown: float | None = 8.0,
):
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    config = {
        "asset": "NASDAQ",
        "timeframe": "M3",
        "preset_name": preset,
        "data_file": "nasdaq_3m.csv",
        "strategy_name": "Strategy",
        "mode": "general",
        "max_rows": max_rows,
        "max_combinations": max_combinations,
        "n_workers": 1,
        "benchmark_n_sample": 1,
    }
    metrics = {
        "status": "completed",
        "duration_seconds": 12,
    }
    if score is not None:
        metrics["best_score"] = score
    if trades is not None:
        metrics["best_total_trades"] = trades
    if drawdown is not None:
        metrics["best_max_dd_pct"] = drawdown
    if max_combinations is not None:
        metrics["total_combinations"] = max_combinations
    _write_json(job_dir / "config_used.json", config)
    _write_json(job_dir / "metrics.json", metrics)
    save_annotation(job_dir, status="Champion", note="Prometteur")
    return {
        "job_id": job_id,
        "job_dir": str(job_dir),
        "status": "completed",
        "date": "2026-06-23T10:00:00",
    }, job_dir


def _record(job: dict):
    record = load_job_record(job)
    assert record is not None
    return record


def test_plan_from_quick_local_preset(tmp_path):
    job, _ = _job(tmp_path)

    plan = build_retest_plan(_record(job), cpu_count=8)

    assert plan.recommended_preset == "Test moyen"
    assert plan.max_rows == 100_000
    assert plan.max_combinations == 100
    assert plan.workers == 2
    assert plan.benchmark_n_sample == 3
    assert "Test rapide local" in plan.justification


def test_plan_from_low_trade_count_uses_more_history(tmp_path):
    job, _ = _job(
        tmp_path,
        preset="Test moyen",
        max_rows=100_000,
        max_combinations=100,
        trades=12,
        score=22.0,
    )

    plan = build_retest_plan(_record(job), cpu_count=8)

    assert plan.recommended_preset == "Optimisation complète"
    assert plan.max_rows is None
    assert plan.max_combinations == 300
    assert "Trop peu de trades" in plan.justification


def test_plan_with_high_drawdown_is_prudent(tmp_path):
    job, _ = _job(
        tmp_path,
        preset="Test moyen",
        max_rows=100_000,
        max_combinations=100,
        drawdown=24.0,
    )

    plan = build_retest_plan(_record(job), cpu_count=8)

    assert plan.recommended_preset == "Test moyen"
    assert plan.max_combinations == 100
    assert "drawdown élevé" in plan.suggested_tags
    assert "Drawdown élevé" in plan.justification


def test_plan_with_incomplete_data_asks_for_more_data(tmp_path):
    job, _ = _job(
        tmp_path,
        preset="Ancien job",
        max_rows=None,
        max_combinations=None,
        trades=None,
        score=None,
        drawdown=None,
    )

    plan = build_retest_plan(_record(job), cpu_count=8)

    assert plan.recommended_preset == "Personnalisé"
    assert plan.max_rows is None
    assert plan.max_combinations == 100
    assert "Données incomplètes" in plan.justification


def test_apply_retest_plan_to_config_without_launching(tmp_path):
    job, _ = _job(tmp_path)
    record = _record(job)
    plan = build_retest_plan(record, cpu_count=8)

    planned = apply_retest_plan_to_config(record.config, plan, source_job_id=record.job_id)

    assert planned["preset_name"] == plan.recommended_preset
    assert planned["max_rows"] == plan.max_rows
    assert planned["max_combinations"] == plan.max_combinations
    assert planned["n_workers"] == plan.workers
    assert planned["workers"] == plan.workers
    assert planned["benchmark_n_sample"] == plan.benchmark_n_sample
    assert planned["retest_plan_source_job_id"] == record.job_id
    assert "run_id" not in planned


def test_launch_retest_creates_new_job_without_overwriting_old(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKTEST_BASE_DIR", str(tmp_path))

    class FakeProcess:
        pass

    monkeypatch.setattr(job_launcher.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    job, job_dir = _job(tmp_path, job_id="job_source")
    record = _record(job)
    plan = build_retest_plan(record, cpu_count=8)
    planned = apply_retest_plan_to_config(record.config, plan, source_job_id=record.job_id)

    launched = job_launcher.launch_optimizer_job(planned)

    assert launched.job_id != record.job_id
    assert Path(launched.job_dir).is_dir()
    assert (job_dir / "config_used.json").is_file()


def test_retest_plan_decision_is_journalized(tmp_path):
    job, job_dir = _job(tmp_path)
    record = _record(job)
    plan = build_retest_plan(record, cpu_count=8)

    record_retest_plan_decision(
        job_dir,
        RETEST_PLAN_EVENT_DUPLICATED,
        "Plan dupliqué vers Configuration.",
        plan,
    )

    events = load_decision_events(job_dir)
    assert events[-1].event_type == RETEST_PLAN_EVENT_DUPLICATED
    assert events[-1].category == CATEGORY_ACTION
    assert events[-1].new_state["recommended_preset"] == plan.recommended_preset


def test_retest_launch_decision_is_journalized(tmp_path):
    job, job_dir = _job(tmp_path)
    record = _record(job)
    plan = build_retest_plan(record, cpu_count=8)

    record_retest_plan_decision(
        job_dir,
        RETEST_PLAN_EVENT_LAUNCHED,
        "Retest lancé dans job_new.",
        plan,
        new_job_id="job_new",
    )

    assert load_decision_events(job_dir)[-1].new_state["new_job_id"] == "job_new"


def test_retest_plan_does_not_modify_raw_results(tmp_path):
    job, job_dir = _job(tmp_path)
    raw_names = ("config_used.json", "metrics.json")
    before = {name: _hash(job_dir / name) for name in raw_names}

    build_retest_plan(_record(job), cpu_count=8)

    assert {name: _hash(job_dir / name) for name in raw_names} == before
