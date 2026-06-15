import json
from datetime import datetime, timezone

import pytest

import maintenance


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_folder_size_counts_nested_files(tmp_path):
    (tmp_path / "a.txt").write_text("abc", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.txt").write_text("12345", encoding="utf-8")

    assert maintenance.folder_size(tmp_path) == 8
    assert maintenance.count_files(tmp_path) == 2


def test_completed_job_is_deletable(tmp_path):
    job = tmp_path / "results" / "job_done"
    _write_json(job / "progress.json", {
        "status": "completed",
        "started_at": "2026-06-01T10:00:00",
    })
    _write_json(job / "config_used.json", {
        "asset": "NASDAQ",
        "timeframe": "M3",
    })
    (job / "archive.zip").write_bytes(b"zip")

    item = maintenance.inspect_job_dir(job, base_dir=tmp_path)

    assert item.deletable is True
    assert item.active is False
    assert item.archive_exists is True
    assert item.asset == "NASDAQ"
    assert item.timeframe == "M3"


def test_active_job_is_protected(tmp_path):
    job = tmp_path / "results" / "job_running"
    _write_json(job / "progress.json", {"status": "running"})

    item = maintenance.inspect_job_dir(job, base_dir=tmp_path)
    result = maintenance.delete_items([item], base_dir=tmp_path, dry_run=True)

    assert item.deletable is False
    assert item.active is True
    assert job.exists()
    assert result.deleted == []
    assert result.skipped


def test_dry_run_does_not_delete(tmp_path):
    job = tmp_path / "results" / "job_done"
    _write_json(job / "progress.json", {"status": "completed"})
    item = maintenance.inspect_job_dir(job, base_dir=tmp_path)

    result = maintenance.delete_items([item], base_dir=tmp_path, dry_run=True)

    assert job.exists()
    assert result.dry_run is True
    assert result.deleted == []
    assert result.reclaimed_bytes == item.size_bytes


def test_delete_is_limited_to_allowed_paths(tmp_path):
    outside = tmp_path / "random_folder"
    outside.mkdir()
    item = maintenance.MaintenanceItem(
        kind="job",
        identifier="random_folder",
        path=outside,
        relative_path="random_folder",
        status="completed",
        deletable=True,
        size_bytes=0,
    )

    result = maintenance.delete_items([item], base_dir=tmp_path, dry_run=False)

    assert outside.exists()
    assert result.deleted == []
    assert "chemin non autorise" in result.skipped[0]


def test_allowed_completed_job_can_be_deleted_in_tmp_path(tmp_path):
    job = tmp_path / "results" / "job_done"
    _write_json(job / "progress.json", {"status": "completed"})
    item = maintenance.inspect_job_dir(job, base_dir=tmp_path)

    result = maintenance.delete_items([item], base_dir=tmp_path, dry_run=False)

    assert not job.exists()
    assert result.deleted == ["results/job_done"]
    assert result.errors == []


def test_protected_names_block_deletion(tmp_path):
    job = tmp_path / "results" / "job_done"
    _write_json(job / "progress.json", {"status": "completed"})
    (job / ".env").write_text("SECRET=1", encoding="utf-8")
    item = maintenance.inspect_job_dir(job, base_dir=tmp_path)

    result = maintenance.delete_items([item], base_dir=tmp_path, dry_run=False)

    assert job.exists()
    assert result.deleted == []
    assert "chemin non autorise" in result.skipped[0]


def test_pwcsv_data_folders_are_detected(tmp_path):
    pwcsv = tmp_path / "data" / "PWCSV123456" / "M1"
    pwcsv.mkdir(parents=True)
    (pwcsv / "pwcsv123456_m1.csv").write_text("time,open,high,low,close\n", encoding="utf-8")
    real = tmp_path / "data" / "NASDAQ" / "M3"
    real.mkdir(parents=True)
    (real / "nasdaq_m3.csv").write_text("user csv", encoding="utf-8")

    items = maintenance.list_pwcsv_data_items(base_dir=tmp_path)

    assert [item.identifier for item in items] == ["PWCSV123456"]
    assert items[0].deletable is True
    assert maintenance.is_allowed_delete_path(tmp_path / "data" / "NASDAQ", base_dir=tmp_path) is False


def test_select_cleanup_jobs_filters_status_age_and_heaviest(tmp_path):
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    small = maintenance.MaintenanceItem(
        kind="job",
        identifier="small",
        path=tmp_path / "results" / "job_small",
        relative_path="results/job_small",
        status="completed",
        date="2026-06-01T00:00:00",
        size_bytes=10,
        deletable=True,
    )
    heavy = maintenance.MaintenanceItem(
        kind="job",
        identifier="heavy",
        path=tmp_path / "results" / "job_heavy",
        relative_path="results/job_heavy",
        status="failed",
        date="2026-05-01T00:00:00",
        size_bytes=100,
        deletable=True,
    )

    selected = maintenance.select_cleanup_jobs(
        [small, heavy],
        include_completed=True,
        include_errors=True,
        older_than_days=7,
        heaviest_limit=1,
        now=now,
    )

    assert selected == [heavy]

