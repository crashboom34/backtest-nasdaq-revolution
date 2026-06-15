from pathlib import Path

import pytest

import job_artifacts


def _write_job_files(job_dir: Path, filenames: list[str]) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        (job_dir / filename).write_text(f"content for {filename}\n", encoding="utf-8")


def test_list_job_download_files_reports_present_and_missing(tmp_path):
    _write_job_files(tmp_path, ["results.csv", "metrics.json"])

    infos = job_artifacts.list_job_download_files(tmp_path)
    by_name = {info.filename: info for info in infos}

    assert by_name["results.csv"].can_download is True
    assert by_name["metrics.json"].can_download is True
    assert by_name["best_strategies.csv"].exists is False
    assert by_name["best_strategies.csv"].can_download is False


def test_build_job_archive_contains_available_source_files(tmp_path):
    _write_job_files(tmp_path, ["progress.json", "config_used.json", "results.csv"])

    archive = job_artifacts.build_job_archive(tmp_path)

    assert archive is not None
    assert archive.name == "archive.zip"
    assert job_artifacts.list_archive_contents(archive) == [
        "config_used.json",
        "progress.json",
        "results.csv",
    ]


def test_ensure_job_archive_regenerates_missing_archive(tmp_path):
    _write_job_files(tmp_path, ["progress.json", "config_used.json", "results.csv"])

    archive = job_artifacts.ensure_job_archive(tmp_path)

    assert archive is not None
    assert archive.exists()
    assert archive.stat().st_size > 0


def test_ensure_job_archive_regenerates_invalid_archive(tmp_path):
    _write_job_files(tmp_path, ["progress.json", "config_used.json"])
    (tmp_path / "archive.zip").write_text("not a zip", encoding="utf-8")

    archive = job_artifacts.ensure_job_archive(tmp_path)

    assert archive is not None
    assert job_artifacts.list_archive_contents(archive) == [
        "config_used.json",
        "progress.json",
    ]


def test_build_job_archive_returns_none_without_sources(tmp_path):
    tmp_path.mkdir(exist_ok=True)

    assert job_artifacts.build_job_archive(tmp_path) is None


def test_unreadable_file_is_reported_without_exception(monkeypatch, tmp_path):
    target = tmp_path / "metrics.json"
    target.write_text("{}", encoding="utf-8")
    real_open = Path.open

    def locked_open(self, *args, **kwargs):
        if self == target:
            raise PermissionError("locked for test")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", locked_open)

    info = job_artifacts.inspect_job_file(
        tmp_path,
        "metrics.json",
        "Metriques",
        "application/json",
    )

    assert info.exists is True
    assert info.readable is False
    assert info.can_download is False
    assert "locked for test" in info.error


def test_job_file_path_rejects_escape(tmp_path):
    with pytest.raises(ValueError):
        job_artifacts.job_file_path(tmp_path, "../outside.csv")

