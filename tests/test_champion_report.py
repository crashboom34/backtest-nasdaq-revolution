import hashlib
import json
from pathlib import Path

from champion_report import (
    DECISION_OBSERVE,
    DECISION_REJECT,
    DECISION_RELAUNCH,
    DECISION_TEST_LONGER,
    load_champion_report,
)
from job_annotations import save_annotation


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job(tmp_path: Path, job_id: str = "job_champion") -> tuple[dict, Path]:
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    job = {
        "job_id": job_id,
        "job_dir": str(job_dir),
        "status": "completed",
        "date": "2026-06-21T12:00:00",
    }
    return job, job_dir


def _write_complete_job(job_dir: Path) -> None:
    _write_json(job_dir / "config_used.json", {
        "asset": "NASDAQ",
        "timeframe": "M3",
        "preset_name": "Test moyen",
        "data_file": "nasdaq_3m.csv",
        "strategy_name": "Perfect Revolution",
    })
    _write_json(job_dir / "metrics.json", {
        "status": "completed",
        "best_score": 48.5,
        "best_total_trades": 64,
        "best_win_rate": 57.2,
        "best_max_dd_pct": 8.1,
        "duration_seconds": 145,
        "combinations_tested": 86,
        "total_combinations": 100,
    })
    (job_dir / "results.csv").write_text("score\n48.5\n", encoding="utf-8")


def test_report_for_complete_champion(tmp_path):
    job, job_dir = _job(tmp_path)
    _write_complete_job(job_dir)
    save_annotation(
        job_dir,
        status="Champion",
        note="Bon équilibre rendement / risque.",
        tags=["prometteur"],
    )

    report = load_champion_report(job)

    assert report is not None
    assert report.record.job_id == "job_champion"
    assert report.record.annotation.status == "Champion"
    assert report.record.annotation.note == "Bon équilibre rendement / risque."
    assert report.record.asset == "NASDAQ"
    assert report.record.timeframe == "M3"
    assert report.record.score == 48.5
    assert report.record.combinations == 86
    assert "results.csv" in report.available_files
    assert report.decision.code == DECISION_RELAUNCH
    assert any("score positif" in point.lower() for point in report.strengths)


def test_report_for_favorite_job(tmp_path):
    job, job_dir = _job(tmp_path, "job_favorite")
    _write_complete_job(job_dir)
    save_annotation(job_dir, status="Favori", tags=["à tester plus longtemps"])

    report = load_champion_report(job)

    assert report is not None
    assert report.record.annotation.status == "Favori"
    assert report.decision.code == DECISION_TEST_LONGER


def test_job_without_metrics_remains_compatible(tmp_path):
    job, job_dir = _job(tmp_path, "job_legacy")
    _write_json(job_dir / "config_used.json", {"data_file": "legacy.csv"})
    save_annotation(job_dir, status="Champion")

    report = load_champion_report(job)

    assert report is not None
    assert report.record.preset == "Ancien job"
    assert report.decision.code == DECISION_OBSERVE
    assert report.missing_metrics
    assert any("absente" in alert.lower() for alert in report.alerts)


def test_job_with_no_trades_is_rejected(tmp_path):
    job, job_dir = _job(tmp_path, "job_no_trades")
    _write_complete_job(job_dir)
    metrics = json.loads((job_dir / "metrics.json").read_text(encoding="utf-8"))
    metrics["best_total_trades"] = 0
    _write_json(job_dir / "metrics.json", metrics)
    save_annotation(job_dir, status="Champion")

    report = load_champion_report(job)

    assert report is not None
    assert report.decision.code == DECISION_REJECT
    assert any("aucun trade" in alert.lower() for alert in report.alerts)


def test_low_trade_count_recommends_longer_test(tmp_path):
    job, job_dir = _job(tmp_path, "job_few_trades")
    _write_complete_job(job_dir)
    metrics = json.loads((job_dir / "metrics.json").read_text(encoding="utf-8"))
    metrics["best_total_trades"] = 12
    _write_json(job_dir / "metrics.json", metrics)
    save_annotation(job_dir, status="Favori")

    report = load_champion_report(job)

    assert report.decision.code == DECISION_TEST_LONGER
    assert any("peu de trades" in alert.lower() for alert in report.alerts)


def test_annotation_update_does_not_modify_raw_results(tmp_path):
    job, job_dir = _job(tmp_path, "job_raw_files")
    _write_complete_job(job_dir)
    raw_names = ("config_used.json", "metrics.json", "results.csv")
    before = {name: _hash(job_dir / name) for name in raw_names}

    save_annotation(
        job_dir,
        status="Champion",
        note="Nouvelle décision.",
        tags=["prometteur", "à tester plus longtemps"],
    )
    report = load_champion_report(job)

    assert report.record.annotation.note == "Nouvelle décision."
    assert {name: _hash(job_dir / name) for name in raw_names} == before


def test_non_featured_job_has_no_champion_report(tmp_path):
    job, job_dir = _job(tmp_path, "job_review")
    _write_complete_job(job_dir)
    save_annotation(job_dir, status="À revoir")

    assert load_champion_report(job) is None
