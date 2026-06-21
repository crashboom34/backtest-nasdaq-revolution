import json
from pathlib import Path

from job_comparison import (
    best_job,
    comparison_issues,
    load_comparison_records,
    load_job_record,
    validate_selection,
)
from job_annotations import save_annotation


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _job(tmp_path: Path, job_id: str, status: str = "completed") -> tuple[dict, Path]:
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    return {
        "job_id": job_id,
        "job_dir": str(job_dir),
        "status": status,
        "date": "2026-06-20T12:00:00",
    }, job_dir


def test_comparison_with_complete_jobs(tmp_path):
    job, job_dir = _job(tmp_path, "job_complete")
    _write_json(job_dir / "config_used.json", {
        "asset": "NASDAQ",
        "timeframe": "M3",
        "preset_name": "Test moyen",
        "data_file": "nasdaq_3m.csv",
        "strategy_name": "Strategy",
    })
    _write_json(job_dir / "metrics.json", {
        "status": "completed",
        "best_score": 42.5,
        "best_total_trades": 31,
        "best_win_rate": 54.2,
        "best_max_dd_pct": 8.4,
        "duration_seconds": 120,
        "total_combinations": 100,
    })

    record = load_job_record(job)

    assert record is not None
    assert record.score == 42.5
    assert record.trades == 31
    assert record.win_rate == 54.2
    assert record.drawdown_pct == 8.4
    assert record.missing_metrics == ()


def test_job_with_missing_metrics_is_compatible(tmp_path):
    job, job_dir = _job(tmp_path, "job_legacy")
    _write_json(job_dir / "config_used.json", {"data_file": "nasdaq_3m.csv"})
    (job_dir / "results.csv").write_text(
        "score,stat_n_trades,stat_win_rate,stat_max_dd_pct\n"
        "12.5,19,36.8,6.3\n",
        encoding="utf-8",
    )

    record = load_job_record(job)

    assert record is not None
    assert record.preset == "Ancien job"
    assert record.score == 12.5
    assert record.trades == 19
    assert record.duration_seconds is None
    assert "duration" in record.missing_metrics


def test_no_completed_jobs_returns_empty(tmp_path):
    running, _ = _job(tmp_path, "job_running", status="running")
    stopped, _ = _job(tmp_path, "job_stopped", status="stopped")

    assert load_comparison_records([running, stopped]) == []


def test_best_job_detected():
    from job_comparison import JobComparisonRecord

    common = dict(
        job_dir="x",
        date="",
        asset="NASDAQ",
        timeframe="M3",
        preset="Test",
        status="completed",
        trades=1,
        win_rate=50.0,
        drawdown_pct=5.0,
        duration_seconds=1.0,
        combinations=12,
        data_file="nasdaq.csv",
        strategy_name="S",
    )
    low = JobComparisonRecord(job_id="low", score=10.0, **common)
    high = JobComparisonRecord(job_id="high", score=55.0, **common)

    assert best_job([low, high]).job_id == "high"


def test_non_comparable_jobs_report_issue(tmp_path):
    jobs = []
    for job_id, asset in (("job_a", "NASDAQ"), ("job_b", "DAX")):
        job, job_dir = _job(tmp_path, job_id)
        _write_json(job_dir / "config_used.json", {
            "asset": asset,
            "timeframe": "M3",
            "data_file": f"{asset}.csv",
            "strategy_name": "Strategy",
        })
        _write_json(job_dir / "metrics.json", {"best_score": 1, "best_total_trades": 0})
        jobs.append(job)

    records = load_comparison_records(jobs)

    assert any("même stratégie" in issue for issue in comparison_issues(records))
    assert any("Aucun des jobs" in issue for issue in comparison_issues(records))


def test_selection_limited_to_two_to_five_jobs():
    assert validate_selection(["a"])[0] is False
    assert validate_selection(["a", "b"])[0] is True
    assert validate_selection(["a", "b", "c", "d", "e"])[0] is True
    assert validate_selection(["a", "b", "c", "d", "e", "f"])[0] is False


def test_comparison_record_includes_annotation(tmp_path):
    job, job_dir = _job(tmp_path, "job_annotated")
    _write_json(job_dir / "config_used.json", {"data_file": "nasdaq_3m.csv"})
    _write_json(job_dir / "metrics.json", {"best_score": 10})
    save_annotation(job_dir, status="Champion", note="Référence", tags=["prometteur"])

    record = load_job_record(job)

    assert record.annotation.status == "Champion"
    assert record.annotation.note == "Référence"
    assert record.annotation.tags == ("prometteur",)
