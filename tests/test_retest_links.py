import hashlib
import json
from pathlib import Path

from job_annotations import save_annotation
from job_decisions import CATEGORY_ACTION, append_decision_event
from retest_links import UNKNOWN_VALUE, build_retest_link_index
from retest_plan import RETEST_PLAN_EVENT_LAUNCHED


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job(
    tmp_path: Path,
    job_id: str,
    status: str = "completed",
    config: dict | None = None,
    metrics: dict | None = None,
    annotation: str = "",
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
    _write_json(job_dir / "metrics.json", metrics if metrics is not None else {
        "status": status,
        "best_score": 42.0,
        "best_total_trades": 64,
        "best_win_rate": 55.0,
        "best_max_dd_pct": 9.5,
        "duration_seconds": 90,
        "total_combinations": 120,
    })
    if annotation:
        save_annotation(job_dir, status=annotation, note="Source")
    return {
        "job_id": job_id,
        "job_dir": str(job_dir),
        "status": status,
        "date": "2026-06-23T10:00:00",
    }, job_dir


def test_retest_linked_to_champion_source_from_config_and_decision(tmp_path):
    source, source_dir = _job(tmp_path, "job_source", annotation="Champion")
    retest, _ = _job(
        tmp_path,
        "job_retest",
        config={"retest_plan_source_job_id": "job_source"},
    )
    append_decision_event(
        source_dir,
        RETEST_PLAN_EVENT_LAUNCHED,
        CATEGORY_ACTION,
        "Retest lancé dans job_retest.",
        new_state={"new_job_id": "job_retest"},
    )

    links = build_retest_link_index([source, retest])

    assert len(links["job_source"]) == 1
    link = links["job_source"][0]
    assert link.source_job_id == "job_source"
    assert link.retest_job_id == "job_retest"
    assert link.retest_status == "completed"
    assert link.score == 42.0
    assert link.trades == 64
    assert link.drawdown_pct == 9.5


def test_old_job_without_retest_link_has_no_entry(tmp_path):
    source, _ = _job(tmp_path, "job_old", annotation="Favori")

    links = build_retest_link_index([source])

    assert links == {}


def test_retest_with_missing_metrics_stays_readable(tmp_path):
    source, _ = _job(tmp_path, "job_source", annotation="Champion")
    retest, _ = _job(
        tmp_path,
        "job_retest_missing",
        config={"retest_plan_source_job_id": "job_source"},
        metrics={"status": "completed"},
    )

    link = build_retest_link_index([source, retest])["job_source"][0]

    assert link.retest_job_id == "job_retest_missing"
    assert link.retest_status == "completed"
    assert link.score is None
    assert link.trades is None
    assert link.drawdown_pct is None
    assert "score" in link.missing_metrics


def test_decision_only_link_handles_missing_retest_job(tmp_path):
    source, source_dir = _job(tmp_path, "job_source", annotation="Champion")
    append_decision_event(
        source_dir,
        RETEST_PLAN_EVENT_LAUNCHED,
        CATEGORY_ACTION,
        "Retest lancé dans job_missing.",
        new_state={"new_job_id": "job_missing"},
    )

    link = build_retest_link_index([source])["job_source"][0]

    assert link.retest_job_id == "job_missing"
    assert link.retest_status == UNKNOWN_VALUE


def test_retest_links_do_not_modify_raw_results(tmp_path):
    source, _ = _job(tmp_path, "job_source", annotation="Champion")
    retest, retest_dir = _job(
        tmp_path,
        "job_retest",
        config={"retest_plan_source_job_id": "job_source"},
    )
    raw_names = ("config_used.json", "metrics.json")
    before = {name: _hash(retest_dir / name) for name in raw_names}

    build_retest_link_index([source, retest])

    assert {name: _hash(retest_dir / name) for name in raw_names} == before
