import hashlib
import json
import os
from pathlib import Path

import optimization_store as opt_store
from demo_data import (
    COMPLETED_RETEST_JOB_ID,
    SOURCE_RETEST_JOB_ID,
    ensure_demo_dataset,
)
from job_annotations import load_annotation
from job_decisions import load_decision_events
from retest_links import build_retest_link_index
from retest_plan import RETEST_PLAN_EVENT_LAUNCHED


MINIMAL_FILES = {
    "config_used.json",
    "metrics.json",
    "progress.json",
    "results.csv",
    "best_strategies.csv",
    "job_notes.json",
    "job_decisions.json",
}


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_demo_dataset_generates_fake_jobs_with_minimal_files(tmp_path):
    dataset = ensure_demo_dataset(tmp_path / "demo")

    assert dataset.base_dir == (tmp_path / "demo").resolve()
    assert len(dataset.job_ids) >= 8
    for job_id in dataset.job_ids:
        job_dir = dataset.results_dir / job_id
        assert job_dir.is_dir()
        assert MINIMAL_FILES.issubset({path.name for path in job_dir.iterdir()})
        assert (job_dir / "archive.zip").stat().st_size > 0


def test_demo_annotations_are_readable(tmp_path):
    dataset = ensure_demo_dataset(tmp_path / "demo")

    champion = load_annotation(dataset.results_dir / "job_demo_champion")
    favorite = load_annotation(dataset.results_dir / "job_demo_favorite")
    rejected = load_annotation(dataset.results_dir / "job_demo_rejected")

    assert champion.status == "Champion"
    assert "prometteur" in champion.tags
    assert favorite.status == "Favori"
    assert rejected.status == "Rejeté"


def test_demo_decisions_include_retest_launch(tmp_path):
    dataset = ensure_demo_dataset(tmp_path / "demo")

    events = load_decision_events(dataset.results_dir / SOURCE_RETEST_JOB_ID)

    assert any(event.event_type == RETEST_PLAN_EVENT_LAUNCHED for event in events)
    assert any(
        (event.new_state or {}).get("new_job_id") == COMPLETED_RETEST_JOB_ID
        for event in events
    )


def test_demo_retest_link_is_visible_through_existing_reader(tmp_path, monkeypatch):
    dataset = ensure_demo_dataset(tmp_path / "demo")
    monkeypatch.setenv("BACKTEST_BASE_DIR", str(dataset.base_dir))
    jobs = opt_store.list_jobs()

    links = build_retest_link_index(jobs)

    assert SOURCE_RETEST_JOB_ID in links
    completed = [
        link for link in links[SOURCE_RETEST_JOB_ID]
        if link.retest_job_id == COMPLETED_RETEST_JOB_ID
    ][0]
    assert completed.retest_status == "completed"
    assert completed.score == 76.9
    assert completed.trades == 103


def test_demo_generation_does_not_change_environment(tmp_path, monkeypatch):
    real_base = tmp_path / "real_project"
    monkeypatch.setenv("BACKTEST_BASE_DIR", str(real_base))

    ensure_demo_dataset(tmp_path / "demo")

    assert os.environ["BACKTEST_BASE_DIR"] == str(real_base)


def test_demo_generation_does_not_modify_real_raw_results(tmp_path):
    real_job = tmp_path / "real_project" / "results" / "job_real"
    real_job.mkdir(parents=True)
    for filename in ("config_used.json", "metrics.json", "results.csv"):
        (real_job / filename).write_text(
            json.dumps({"real": True, "file": filename}),
            encoding="utf-8",
        )
    before = {
        filename: _hash(real_job / filename)
        for filename in ("config_used.json", "metrics.json", "results.csv")
    }

    ensure_demo_dataset(tmp_path / "demo")

    after = {
        filename: _hash(real_job / filename)
        for filename in ("config_used.json", "metrics.json", "results.csv")
    }
    assert after == before
    assert not (tmp_path / "real_project" / "results" / "job_demo_champion").exists()
