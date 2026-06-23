"""Annotations utilisateur séparées des artefacts bruts d'un job."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


ANNOTATION_FILENAME = "job_notes.json"
ANNOTATION_STATUSES = ("", "Champion", "Favori", "À revoir", "Rejeté")
ANNOTATION_TAGS = (
    "prometteur",
    "trop peu de trades",
    "drawdown élevé",
    "à tester plus longtemps",
)
FEATURED_STATUSES = {"Champion", "Favori"}


@dataclass(frozen=True)
class JobAnnotation:
    status: str = ""
    note: str = ""
    tags: tuple[str, ...] = ()
    updated_at: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.status and not self.note and not self.tags

    @property
    def is_featured(self) -> bool:
        return self.status in FEATURED_STATUSES


def annotation_path(job_dir: str | Path) -> Path:
    base = Path(job_dir).resolve()
    if not base.is_dir():
        raise ValueError(f"Dossier job introuvable : {job_dir}")
    return base / ANNOTATION_FILENAME


def load_annotation(job_dir: str | Path) -> JobAnnotation:
    """Charge une annotation. Un ancien job sans fichier reste lisible."""
    try:
        path = annotation_path(job_dir)
    except ValueError:
        return JobAnnotation()
    if not path.is_file():
        return JobAnnotation()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return JobAnnotation()
    if not isinstance(data, dict):
        return JobAnnotation()

    status = str(data.get("status", "") or "")
    if status not in ANNOTATION_STATUSES:
        status = ""
    note = str(data.get("note", "") or "")
    tags = _normalize_tags(data.get("tags", []))
    updated_at = str(data.get("updated_at", "") or "")
    return JobAnnotation(status=status, note=note, tags=tags, updated_at=updated_at)


def save_annotation(
    job_dir: str | Path,
    status: str = "",
    note: str = "",
    tags: Iterable[str] = (),
) -> JobAnnotation:
    """Écrit atomiquement job_notes.json sans toucher aux résultats du job."""
    if status not in ANNOTATION_STATUSES:
        raise ValueError(f"Statut d'annotation invalide : {status}")

    previous = load_annotation(job_dir)
    annotation = JobAnnotation(
        status=status,
        note=str(note or "").strip(),
        tags=_normalize_tags(tags),
        updated_at=datetime.now().isoformat(timespec="seconds"),
    )
    path = annotation_path(job_dir)
    tmp_path = path.with_suffix(".json.tmp")
    payload = asdict(annotation)
    payload["tags"] = list(annotation.tags)

    try:
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    from job_decisions import record_annotation_changes
    try:
        record_annotation_changes(job_dir, previous, annotation)
    except (OSError, ValueError):
        # L'annotation reste utilisable même si son journal annexe est indisponible.
        pass
    return annotation


def clear_annotation(job_dir: str | Path) -> JobAnnotation:
    """Vide l'annotation sans supprimer de fichier."""
    return save_annotation(job_dir, status="", note="", tags=())


def filter_jobs_by_annotation(
    jobs: Iterable[dict],
    statuses: Iterable[str] = (),
) -> list[dict]:
    wanted = {status for status in statuses if status in ANNOTATION_STATUSES}
    filtered: list[dict] = []
    for job in jobs:
        annotation = load_annotation(job.get("job_dir", ""))
        if wanted and annotation.status not in wanted:
            continue
        enriched = dict(job)
        enriched["annotation"] = annotation
        filtered.append(enriched)
    return filtered


def featured_jobs(jobs: Iterable[dict]) -> list[dict]:
    return filter_jobs_by_annotation(jobs, FEATURED_STATUSES)


def _normalize_tags(tags: Iterable[str]) -> tuple[str, ...]:
    if isinstance(tags, str):
        tags = [tags]
    clean: list[str] = []
    for tag in tags or ():
        value = str(tag).strip()
        if value in ANNOTATION_TAGS and value not in clean:
            clean.append(value)
    return tuple(clean)
