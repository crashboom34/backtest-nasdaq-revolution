import hashlib
import json
from pathlib import Path

from job_annotations import (
    clear_annotation,
    featured_jobs,
    filter_jobs_by_annotation,
    load_annotation,
    save_annotation,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job_dir(tmp_path: Path, name: str = "job_test") -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def test_create_annotation(tmp_path):
    job_dir = _job_dir(tmp_path)

    saved = save_annotation(
        job_dir,
        status="Champion",
        note="Bon équilibre.",
        tags=["prometteur"],
    )
    loaded = load_annotation(job_dir)

    assert saved.status == "Champion"
    assert loaded.status == "Champion"
    assert loaded.note == "Bon équilibre."
    assert loaded.tags == ("prometteur",)


def test_modify_annotation(tmp_path):
    job_dir = _job_dir(tmp_path)
    save_annotation(job_dir, status="Favori", note="Première note")

    save_annotation(
        job_dir,
        status="À revoir",
        note="Tester davantage.",
        tags=["à tester plus longtemps", "drawdown élevé"],
    )
    loaded = load_annotation(job_dir)

    assert loaded.status == "À revoir"
    assert loaded.note == "Tester davantage."
    assert loaded.tags == ("à tester plus longtemps", "drawdown élevé")


def test_clear_annotation_keeps_empty_file(tmp_path):
    job_dir = _job_dir(tmp_path)
    save_annotation(job_dir, status="Rejeté", note="Non retenu")

    cleared = clear_annotation(job_dir)

    assert cleared.is_empty
    assert (job_dir / "job_notes.json").is_file()
    assert load_annotation(job_dir).is_empty


def test_legacy_job_without_annotation_is_readable(tmp_path):
    job_dir = _job_dir(tmp_path)

    annotation = load_annotation(job_dir)

    assert annotation.is_empty


def test_filter_champions_and_favorites(tmp_path):
    champion_dir = _job_dir(tmp_path, "job_champion")
    favorite_dir = _job_dir(tmp_path, "job_favorite")
    review_dir = _job_dir(tmp_path, "job_review")
    save_annotation(champion_dir, status="Champion")
    save_annotation(favorite_dir, status="Favori")
    save_annotation(review_dir, status="À revoir")
    jobs = [
        {"job_id": "job_champion", "job_dir": str(champion_dir)},
        {"job_id": "job_favorite", "job_dir": str(favorite_dir)},
        {"job_id": "job_review", "job_dir": str(review_dir)},
    ]

    assert [job["job_id"] for job in featured_jobs(jobs)] == [
        "job_champion",
        "job_favorite",
    ]
    assert [job["job_id"] for job in filter_jobs_by_annotation(jobs, ["Champion"])] == [
        "job_champion",
    ]


def test_raw_result_files_are_not_modified(tmp_path):
    job_dir = _job_dir(tmp_path)
    raw_files = {}
    for filename in ("config_used.json", "metrics.json", "results.csv"):
        path = job_dir / filename
        path.write_text(json.dumps({"file": filename}), encoding="utf-8")
        raw_files[filename] = _hash(path)

    save_annotation(job_dir, status="Champion", note="Séparé des résultats.")

    assert (job_dir / "job_notes.json").is_file()
    assert {
        filename: _hash(job_dir / filename)
        for filename in raw_files
    } == raw_files
