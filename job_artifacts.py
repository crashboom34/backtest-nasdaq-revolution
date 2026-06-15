"""
job_artifacts.py - Utilitaires pour les fichiers telechargeables des jobs.

Objectif : rendre l'interface Streamlit robuste. Un bouton de telechargement
ne doit apparaitre que si le fichier existe, est un fichier, et peut etre lu.
"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


ARCHIVE_SOURCE_FILES = [
    "progress.json",
    "config_used.json",
    "results.csv",
    "metrics.json",
    "best_strategies.csv",
    "report.html",
    "logs.txt",
]

JOB_DOWNLOAD_SPECS = [
    ("results.csv", "Resultats complets", "text/csv"),
    ("best_strategies.csv", "Meilleures strategies", "text/csv"),
    ("metrics.json", "Metriques", "application/json"),
    ("config_used.json", "Configuration utilisee", "application/json"),
    ("progress.json", "Progression", "application/json"),
    ("report.html", "Rapport HTML", "text/html"),
    ("logs.txt", "Logs", "text/plain"),
    ("archive.zip", "Archive ZIP", "application/zip"),
]


@dataclass(frozen=True)
class JobFileInfo:
    filename: str
    label: str
    mime: str
    path: Path
    exists: bool
    readable: bool
    size: int
    error: str = ""

    @property
    def can_download(self) -> bool:
        return self.exists and self.readable and self.size > 0 and not self.error


def _job_dir_path(job_dir: str | Path) -> Path:
    return Path(job_dir).resolve()


def job_file_path(job_dir: str | Path, filename: str) -> Path:
    """Construit un chemin de fichier protege dans job_dir."""
    base = _job_dir_path(job_dir)
    requested = Path(filename)
    if requested.is_absolute() or requested.name != str(filename):
        raise ValueError(f"Fichier hors dossier job interdit : {filename}")
    candidate = (base / requested.name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Fichier hors dossier job interdit : {filename}") from exc
    return candidate


def inspect_job_file(job_dir: str | Path, filename: str, label: str, mime: str) -> JobFileInfo:
    path = job_file_path(job_dir, filename)
    if not path.exists():
        return JobFileInfo(filename, label, mime, path, False, False, 0, "absent")
    if not path.is_file():
        return JobFileInfo(filename, label, mime, path, True, False, 0, "n'est pas un fichier")

    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.read(1)
    except OSError as exc:
        return JobFileInfo(filename, label, mime, path, True, False, 0, str(exc))

    if size <= 0:
        return JobFileInfo(filename, label, mime, path, True, False, size, "fichier vide")

    return JobFileInfo(filename, label, mime, path, True, True, size)


def read_job_file_bytes(path: str | Path) -> bytes:
    """Lit un fichier et ferme immediatement le handle."""
    with Path(path).open("rb") as handle:
        return handle.read()


def list_job_download_files(job_dir: str | Path) -> list[JobFileInfo]:
    """Retourne l'etat present/absent/lisible de chaque fichier telechargeable."""
    return [
        inspect_job_file(job_dir, filename, label, mime)
        for filename, label, mime in JOB_DOWNLOAD_SPECS
    ]


def _archive_source_infos(job_dir: str | Path) -> list[JobFileInfo]:
    labels = {filename: label for filename, label, _mime in JOB_DOWNLOAD_SPECS}
    mimes = {filename: mime for filename, _label, mime in JOB_DOWNLOAD_SPECS}
    return [
        inspect_job_file(job_dir, filename, labels.get(filename, filename), mimes.get(filename, "application/octet-stream"))
        for filename in ARCHIVE_SOURCE_FILES
    ]


def build_job_archive(job_dir: str | Path) -> Optional[Path]:
    """
    Reconstruit archive.zip avec les fichiers utiles disponibles.

    L'archive ne contient jamais archive.zip lui-meme, ni tested.json/meta.json/stop.flag.
    """
    base = _job_dir_path(job_dir)
    if not base.is_dir():
        return None

    sources = [info for info in _archive_source_infos(base) if info.can_download]
    if not sources:
        return None

    archive_path = job_file_path(base, "archive.zip")
    tmp_path = archive_path.with_suffix(".zip.tmp")

    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for info in sources:
            zf.write(info.path, arcname=info.filename)

    os.replace(tmp_path, archive_path)
    return archive_path


def _zip_is_valid(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return zf.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def ensure_job_archive(job_dir: str | Path) -> Optional[Path]:
    """
    Cree ou regenere archive.zip si elle est absente, vide, invalide ou obsolete.
    """
    base = _job_dir_path(job_dir)
    if not base.is_dir():
        return None

    archive_path = job_file_path(base, "archive.zip")
    source_infos = [info for info in _archive_source_infos(base) if info.can_download]
    if not source_infos:
        return None

    needs_rebuild = not archive_path.exists() or not archive_path.is_file() or archive_path.stat().st_size <= 0
    if not needs_rebuild and not _zip_is_valid(archive_path):
        needs_rebuild = True
    if not needs_rebuild:
        archive_mtime = archive_path.stat().st_mtime
        newest_source = max(info.path.stat().st_mtime for info in source_infos)
        needs_rebuild = newest_source > archive_mtime

    if needs_rebuild:
        return build_job_archive(base)
    return archive_path


def list_archive_contents(archive_path: str | Path) -> list[str]:
    with zipfile.ZipFile(archive_path, "r") as zf:
        return sorted(zf.namelist())
