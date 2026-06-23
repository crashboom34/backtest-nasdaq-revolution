import hashlib
import json
from pathlib import Path

from champion_pipeline import (
    STAGE_CHAMPION,
    STAGE_DETECTED,
    STAGE_FAVORITE,
    STAGE_READY_ADVANCED,
    STAGE_REJECTED,
    STAGE_RETEST,
    STAGE_RETEST_LAUNCHED,
    STAGE_SERIOUS,
    build_pipeline,
    cards_by_stage,
    pipeline_summary,
)
from job_annotations import save_annotation
from job_decisions import CATEGORY_ACTION, append_decision_event
from retest_plan import RETEST_PLAN_EVENT_LAUNCHED


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job(
    tmp_path: Path,
    job_id: str,
    annotation: str,
    metrics: dict | None = None,
    config: dict | None = None,
):
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    _write_json(job_dir / "config_used.json", {
        "asset": "NASDAQ",
        "timeframe": "M3",
        "preset_name": "Test moyen",
        "data_file": "nasdaq_3m.csv",
        "strategy_name": "Strategy",
        "max_rows": 100_000,
        **(config or {}),
    })
    _write_json(job_dir / "metrics.json", metrics or {
        "status": "completed",
        "best_score": 45.0,
        "best_total_trades": 60,
        "best_win_rate": 55.0,
        "best_max_dd_pct": 8.0,
        "duration_seconds": 120,
        "total_combinations": 150,
    })
    save_annotation(job_dir, status=annotation, note="Note courte", tags=["prometteur"])
    return {
        "job_id": job_id,
        "job_dir": str(job_dir),
        "status": "completed",
        "date": "2026-06-21T12:00:00",
    }, job_dir


def _single_stage(job: dict) -> str:
    cards = build_pipeline([job]).cards
    assert len(cards) == 1
    return cards[0].stage


def test_empty_pipeline():
    pipeline = build_pipeline([])
    summary = pipeline_summary(pipeline.cards)

    assert pipeline.cards == ()
    assert summary.serious_count == 0
    assert summary.retest_count == 0
    assert summary.rejected_count == 0


def test_favorite_stage(tmp_path):
    job, _ = _job(
        tmp_path,
        "job_favorite",
        "Favori",
        metrics={
            "best_score": 20,
            "best_total_trades": 35,
            "best_win_rate": 35,
            "best_max_dd_pct": 10,
            "total_combinations": 120,
        },
        config={"max_rows": None},
    )

    assert _single_stage(job) == STAGE_FAVORITE


def test_champion_stage(tmp_path):
    job, _ = _job(
        tmp_path,
        "job_champion",
        "Champion",
        metrics={
            "best_score": 20,
            "best_total_trades": 35,
            "best_win_rate": 35,
            "best_max_dd_pct": 10,
            "total_combinations": 120,
        },
        config={"max_rows": None},
    )

    assert _single_stage(job) == STAGE_CHAMPION


def test_detected_stage_for_review_annotation(tmp_path):
    job, _ = _job(tmp_path, "job_detected", "À revoir")

    assert _single_stage(job) == STAGE_DETECTED


def test_retest_stage(tmp_path):
    job, _ = _job(
        tmp_path,
        "job_retest",
        "Favori",
        metrics={
            "best_score": 25,
            "best_total_trades": 12,
            "best_win_rate": 50,
            "best_max_dd_pct": 8,
            "total_combinations": 150,
        },
    )

    assert _single_stage(job) == STAGE_RETEST


def test_retest_launched_stage(tmp_path):
    job, job_dir = _job(tmp_path, "job_launched", "Favori")
    append_decision_event(
        job_dir,
        RETEST_PLAN_EVENT_LAUNCHED,
        CATEGORY_ACTION,
        "Retest lancé dans job_new.",
    )

    pipeline = build_pipeline([job])

    assert pipeline.cards[0].stage == STAGE_RETEST_LAUNCHED
    assert "Suivre le retest" in pipeline.cards[0].next_action


def test_serious_candidate_stage_for_favorite(tmp_path):
    job, _ = _job(
        tmp_path,
        "job_serious",
        "Favori",
        config={"max_rows": None},
    )

    assert _single_stage(job) == STAGE_SERIOUS


def test_ready_for_advanced_validation_stage_for_champion(tmp_path):
    job, _ = _job(
        tmp_path,
        "job_ready",
        "Champion",
        config={"max_rows": None},
    )

    assert _single_stage(job) == STAGE_READY_ADVANCED


def test_rejected_stage(tmp_path):
    job, _ = _job(tmp_path, "job_rejected", "Rejeté")

    assert _single_stage(job) == STAGE_REJECTED


def test_legacy_job_compatible(tmp_path):
    job, job_dir = _job(tmp_path, "job_legacy", "À revoir", metrics={}, config={})
    (job_dir / "metrics.json").write_text("{}", encoding="utf-8")

    pipeline = build_pipeline([job])

    assert pipeline.cards[0].stage == STAGE_DETECTED
    assert pipeline.cards[0].item.maturity_status == "Données incomplètes"


def test_summary_and_grouping(tmp_path):
    ready, _ = _job(tmp_path, "job_ready", "Champion", config={"max_rows": None})
    retest, _ = _job(
        tmp_path,
        "job_retest",
        "Favori",
        metrics={
            "best_score": 25,
            "best_total_trades": 12,
            "best_win_rate": 50,
            "best_max_dd_pct": 8,
            "total_combinations": 150,
        },
    )
    rejected, _ = _job(tmp_path, "job_rejected", "Rejeté")

    pipeline = build_pipeline([ready, retest, rejected])
    summary = pipeline_summary(pipeline.cards)
    grouped = cards_by_stage(pipeline.cards)

    assert summary.serious_count == 1
    assert summary.retest_count == 1
    assert summary.rejected_count == 1
    assert grouped[STAGE_READY_ADVANCED][0].job_id == "job_ready"


def test_pipeline_does_not_modify_raw_results(tmp_path):
    job, job_dir = _job(tmp_path, "job_raw", "Champion")
    raw_names = ("config_used.json", "metrics.json")
    before = {name: _hash(job_dir / name) for name in raw_names}

    build_pipeline([job])

    assert {name: _hash(job_dir / name) for name in raw_names} == before
