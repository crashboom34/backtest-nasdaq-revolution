"""Journal append-only des décisions utilisateur liées à un job."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping


DECISIONS_FILENAME = "job_decisions.json"
CATEGORY_ANNOTATION = "annotation"
CATEGORY_EXPORT = "export"
CATEGORY_ACTION = "action"
CATEGORY_SETTINGS = "settings"
DECISION_CATEGORIES = (
    CATEGORY_ANNOTATION,
    CATEGORY_EXPORT,
    CATEGORY_ACTION,
    CATEGORY_SETTINGS,
)


@dataclass(frozen=True)
class DecisionEvent:
    timestamp: str
    event_type: str
    category: str
    message: str
    old_state: dict | None = None
    new_state: dict | None = None


def decisions_path(job_dir: str | Path) -> Path:
    base = Path(job_dir).resolve()
    if not base.is_dir():
        raise ValueError(f"Dossier job introuvable : {job_dir}")
    return base / DECISIONS_FILENAME


def load_decision_events(job_dir: str | Path) -> list[DecisionEvent]:
    try:
        path = decisions_path(job_dir)
    except ValueError:
        return []
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("events", []) if isinstance(payload, dict) else []
    events: list[DecisionEvent] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_type = str(row.get("event_type", "") or "")
        category = str(row.get("category", "") or "")
        message = str(row.get("message", "") or "")
        if not event_type or category not in DECISION_CATEGORIES or not message:
            continue
        events.append(DecisionEvent(
            timestamp=str(row.get("timestamp", "") or ""),
            event_type=event_type,
            category=category,
            message=message,
            old_state=_state(row.get("old_state")),
            new_state=_state(row.get("new_state")),
        ))
    return events


def append_decision_event(
    job_dir: str | Path,
    event_type: str,
    category: str,
    message: str,
    old_state: Mapping | None = None,
    new_state: Mapping | None = None,
) -> DecisionEvent:
    if category not in DECISION_CATEGORIES:
        raise ValueError(f"Catégorie d'événement invalide : {category}")
    if not str(event_type).strip() or not str(message).strip():
        raise ValueError("Type et message d'événement requis")

    event = DecisionEvent(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        event_type=str(event_type).strip(),
        category=category,
        message=str(message).strip(),
        old_state=_state(old_state),
        new_state=_state(new_state),
    )
    path = decisions_path(job_dir)
    events = load_decision_events(job_dir)
    events.append(event)
    payload = {
        "version": 1,
        "events": [asdict(item) for item in events],
    }
    temp = path.with_suffix(".json.tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass
    return event


def record_annotation_changes(job_dir: str | Path, old, new) -> list[DecisionEvent]:
    events: list[DecisionEvent] = []
    if old.status != new.status:
        events.append(append_decision_event(
            job_dir,
            "annotation_status_changed",
            CATEGORY_ANNOTATION,
            f"Classement modifié : {old.status or 'Non classé'} → {new.status or 'Non classé'}.",
            old_state={"status": old.status},
            new_state={"status": new.status},
        ))
    if old.note != new.note:
        events.append(append_decision_event(
            job_dir,
            "annotation_note_changed",
            CATEGORY_ANNOTATION,
            "Note utilisateur modifiée.",
            old_state={"note": old.note},
            new_state={"note": new.note},
        ))
    if tuple(old.tags) != tuple(new.tags):
        events.append(append_decision_event(
            job_dir,
            "annotation_tags_changed",
            CATEGORY_ANNOTATION,
            "Tags utilisateur modifiés.",
            old_state={"tags": list(old.tags)},
            new_state={"tags": list(new.tags)},
        ))
    return events


def filter_decision_events(
    events: Iterable[DecisionEvent],
    category: str | None = None,
) -> list[DecisionEvent]:
    items = list(events)
    if not category:
        return items
    return [event for event in items if event.category == category]


def _state(value) -> dict | None:
    if value is None:
        return None
    return dict(value) if isinstance(value, Mapping) else None
