import hashlib
import json
from pathlib import Path

from job_annotations import save_annotation
from job_decisions import (
    CATEGORY_ACTION,
    CATEGORY_ANNOTATION,
    CATEGORY_EXPORT,
    append_decision_event,
    filter_decision_events,
    load_decision_events,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job_dir(tmp_path: Path) -> Path:
    job_dir = tmp_path / "job_decisions"
    job_dir.mkdir()
    return job_dir


def test_create_decision_event(tmp_path):
    job_dir = _job_dir(tmp_path)

    event = append_decision_event(
        job_dir,
        event_type="export_markdown",
        category=CATEGORY_EXPORT,
        message="Rapport Markdown exporté.",
        new_state={"format": "md"},
    )

    loaded = load_decision_events(job_dir)
    assert event.timestamp
    assert loaded == [event]
    assert (job_dir / "job_decisions.json").is_file()


def test_legacy_job_without_history_is_readable(tmp_path):
    job_dir = _job_dir(tmp_path)

    assert load_decision_events(job_dir) == []


def test_annotation_status_note_and_tags_are_traced(tmp_path):
    job_dir = _job_dir(tmp_path)
    save_annotation(job_dir, status="Favori", note="Première note")

    save_annotation(
        job_dir,
        status="Champion",
        note="Note renforcée.",
        tags=["prometteur"],
    )

    events = load_decision_events(job_dir)
    event_types = [event.event_type for event in events]
    assert "annotation_status_changed" in event_types
    assert "annotation_note_changed" in event_types
    assert "annotation_tags_changed" in event_types
    assert all(event.category == CATEGORY_ANNOTATION for event in events)
    status_event = next(
        event for event in events
        if event.event_type == "annotation_status_changed"
        and event.new_state == {"status": "Champion"}
    )
    assert status_event.old_state == {"status": "Favori"}


def test_export_duplication_and_relaunch_events_are_filterable(tmp_path):
    job_dir = _job_dir(tmp_path)
    append_decision_event(
        job_dir,
        "export_html",
        CATEGORY_EXPORT,
        "Rapport HTML exporté.",
    )
    append_decision_event(
        job_dir,
        "config_duplicated",
        CATEGORY_ACTION,
        "Configuration dupliquée.",
    )
    append_decision_event(
        job_dir,
        "config_relaunched",
        CATEGORY_ACTION,
        "Configuration relancée.",
        new_state={"new_job_id": "job_new"},
    )

    events = load_decision_events(job_dir)

    assert [event.event_type for event in filter_decision_events(
        events, CATEGORY_EXPORT
    )] == ["export_html"]
    assert [event.event_type for event in filter_decision_events(
        events, CATEGORY_ACTION
    )] == ["config_duplicated", "config_relaunched"]


def test_decision_log_does_not_modify_raw_results(tmp_path):
    job_dir = _job_dir(tmp_path)
    raw_names = ("config_used.json", "metrics.json", "results.csv")
    for filename in raw_names:
        (job_dir / filename).write_text(
            json.dumps({"filename": filename}),
            encoding="utf-8",
        )
    before = {name: _hash(job_dir / name) for name in raw_names}

    append_decision_event(
        job_dir,
        "config_duplicated",
        CATEGORY_ACTION,
        "Configuration dupliquée.",
    )

    assert {name: _hash(job_dir / name) for name in raw_names} == before
