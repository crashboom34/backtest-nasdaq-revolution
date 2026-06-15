"""
dashboard.py - Resume lisible de l'etat local du projet.

Le module reste sans dependance Streamlit pour pouvoir etre teste facilement.
Il agrege les jobs, les donnees disponibles et quelques alertes simples.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import optimization_store as opt_store
from job_artifacts import list_job_download_files
from maintenance import disk_usage_for_base
from path_resolver import (
    BASE_DIR,
    list_available_assets,
    list_available_timeframes,
    resolve_data_csv,
)


ERROR_STATUSES = {"failed", "error"}
COMPLETED_STATUS = "completed"
ACTIVE_STATUS_LABELS = {"created", "benchmarking", "running"}
TERMINAL_STATUS_LABELS = {"completed", "failed", "error", "stopped"}
LOW_DISK_WARNING_BYTES = 5 * 1024**3
LOW_DISK_CRITICAL_BYTES = 2 * 1024**3
STALE_ACTIVE_SECONDS = 10 * 60
REQUIRED_TERMINAL_FILES = {
    "progress.json",
    "config_used.json",
    "results.csv",
    "archive.zip",
}


@dataclass(frozen=True)
class DashboardDataSource:
    asset: str
    timeframe: str
    source: str
    relative_path: str
    exists: bool
    message: str


@dataclass(frozen=True)
class DashboardAlert:
    level: str
    title: str
    message: str


@dataclass(frozen=True)
class DashboardSummary:
    disk_total_bytes: int
    disk_free_bytes: int
    total_jobs: int
    completed_jobs: int
    error_jobs: int
    active_jobs: int
    stale_active_jobs: int
    latest_job_id: str
    latest_job_status: str
    latest_job_date: str
    latest_completed_job_id: str
    latest_completed_job_date: str
    best_recent_score: Optional[float]
    data_sources: list[DashboardDataSource]
    missing_archives: int
    incomplete_jobs: int
    alerts: list[DashboardAlert]


def build_dashboard_summary(
    jobs: Optional[list[dict]] = None,
    data_sources: Optional[list[DashboardDataSource]] = None,
    disk_usage: Optional[dict[str, int]] = None,
    now: Optional[datetime] = None,
    base_dir: Path = BASE_DIR,
) -> DashboardSummary:
    """Construit le resume complet avec injections possibles pour les tests."""
    now_dt = now or datetime.now(timezone.utc)
    job_list = list(jobs if jobs is not None else _load_jobs_with_progress_updates())
    sources = list(data_sources if data_sources is not None else list_data_sources())
    disk = disk_usage if disk_usage is not None else disk_usage_for_base(base_dir)

    sorted_jobs = sorted(job_list, key=_job_sort_key, reverse=True)
    completed = [job for job in sorted_jobs if _status(job) == COMPLETED_STATUS]
    error_jobs = [job for job in sorted_jobs if _status(job) in ERROR_STATUSES]
    active_jobs = [job for job in sorted_jobs if _job_is_active(job)]
    stale_active = [
        job for job in active_jobs
        if _job_is_stale(job, now_dt=now_dt, stale_after_seconds=STALE_ACTIVE_SECONDS)
    ]

    missing_archives, incomplete_jobs = summarize_terminal_artifacts(sorted_jobs)
    best_recent_score = _best_recent_score(sorted_jobs)
    latest_job = sorted_jobs[0] if sorted_jobs else {}
    latest_completed = completed[0] if completed else {}

    summary_without_alerts = DashboardSummary(
        disk_total_bytes=int(disk.get("total", 0) or 0),
        disk_free_bytes=int(disk.get("free", 0) or 0),
        total_jobs=len(sorted_jobs),
        completed_jobs=len(completed),
        error_jobs=len(error_jobs),
        active_jobs=len(active_jobs),
        stale_active_jobs=len(stale_active),
        latest_job_id=str(latest_job.get("job_id", "")),
        latest_job_status=_status(latest_job),
        latest_job_date=str(latest_job.get("date", "")),
        latest_completed_job_id=str(latest_completed.get("job_id", "")),
        latest_completed_job_date=str(latest_completed.get("date", "")),
        best_recent_score=best_recent_score,
        data_sources=sources,
        missing_archives=missing_archives,
        incomplete_jobs=incomplete_jobs,
        alerts=[],
    )
    return DashboardSummary(
        **{
            **summary_without_alerts.__dict__,
            "alerts": build_dashboard_alerts(summary_without_alerts),
        }
    )


def list_data_sources() -> list[DashboardDataSource]:
    """Liste les couples actif/timeframe connus et leur source CSV."""
    sources: list[DashboardDataSource] = []
    for asset in list_available_assets():
        for timeframe in list_available_timeframes(asset):
            resolution = resolve_data_csv(asset, timeframe)
            sources.append(DashboardDataSource(
                asset=resolution.asset,
                timeframe=resolution.timeframe,
                source=resolution.source,
                relative_path=resolution.relative_path,
                exists=resolution.exists,
                message=resolution.message,
            ))
    return sorted(sources, key=lambda item: (item.asset, item.timeframe))


def summarize_terminal_artifacts(jobs: list[dict]) -> tuple[int, int]:
    """Compte les archives manquantes et les jobs terminaux incomplets."""
    missing_archives = 0
    incomplete_jobs = 0

    for job in jobs:
        if _status(job) not in TERMINAL_STATUS_LABELS:
            continue
        job_dir = job.get("job_dir")
        if not job_dir:
            continue
        path = Path(job_dir)
        if not path.is_dir():
            continue

        try:
            infos = list_job_download_files(path)
        except (OSError, ValueError):
            incomplete_jobs += 1
            continue

        by_name = {info.filename: info for info in infos}
        archive = by_name.get("archive.zip")
        if not archive or not archive.can_download:
            missing_archives += 1

        required_missing = [
            filename for filename in REQUIRED_TERMINAL_FILES
            if filename not in by_name or not by_name[filename].can_download
        ]
        if required_missing:
            incomplete_jobs += 1

    return missing_archives, incomplete_jobs


def build_dashboard_alerts(summary: DashboardSummary) -> list[DashboardAlert]:
    alerts: list[DashboardAlert] = []

    if summary.disk_free_bytes < LOW_DISK_CRITICAL_BYTES:
        alerts.append(DashboardAlert(
            "error",
            "Disque presque plein",
            "Il reste moins de 2 Go libres. Evite de lancer un nouveau job avant nettoyage.",
        ))
    elif summary.disk_free_bytes < LOW_DISK_WARNING_BYTES:
        alerts.append(DashboardAlert(
            "warning",
            "Espace disque a surveiller",
            "Il reste moins de 5 Go libres. Pense a nettoyer les anciens jobs si besoin.",
        ))

    if summary.error_jobs:
        alerts.append(DashboardAlert(
            "warning",
            "Jobs en erreur",
            f"{summary.error_jobs} job(s) sont en erreur ou ont echoue.",
        ))

    if summary.stale_active_jobs:
        alerts.append(DashboardAlert(
            "warning",
            "Job actif potentiellement bloque",
            f"{summary.stale_active_jobs} job(s) actif(s) n'ont pas ete mis a jour recemment.",
        ))

    if not any(source.exists for source in summary.data_sources):
        alerts.append(DashboardAlert(
            "error",
            "Aucune donnee CSV utilisable",
            "Importe un CSV dans Donnees ou ajoute le fichier legacy nasdaq_3m.csv.",
        ))

    if summary.missing_archives:
        alerts.append(DashboardAlert(
            "info",
            "Archives manquantes",
            f"{summary.missing_archives} job(s) termine(s) n'ont pas encore d'archive.zip lisible.",
        ))

    if summary.incomplete_jobs:
        alerts.append(DashboardAlert(
            "info",
            "Fichiers job incomplets",
            f"{summary.incomplete_jobs} job(s) termine(s) ont des artefacts absents ou illisibles.",
        ))

    return alerts


def _load_jobs_with_progress_updates() -> list[dict]:
    jobs = opt_store.list_jobs()
    for job in jobs:
        job_id = job.get("job_id")
        job_dir = job.get("job_dir")
        if not job_id or not job_dir:
            continue
        try:
            progress = opt_store.read_progress(job_id, job_dir=job_dir) or {}
        except Exception:
            progress = {}
        if progress.get("updated_at"):
            job["_updated_at"] = progress.get("updated_at")
        elif progress.get("started_at"):
            job["_updated_at"] = progress.get("started_at")
    return jobs


def _status(job: dict) -> str:
    return str(job.get("status", "") or "").lower()


def _job_is_active(job: dict) -> bool:
    try:
        return opt_store.is_active_job(job)
    except Exception:
        return _status(job) in ACTIVE_STATUS_LABELS


def _job_is_stale(job: dict, now_dt: datetime, stale_after_seconds: int) -> bool:
    if _status(job) not in ACTIVE_STATUS_LABELS:
        return False
    updated = _parse_datetime(job.get("_updated_at") or job.get("updated_at"))
    if updated is None:
        return False
    return (now_dt - updated).total_seconds() > stale_after_seconds


def _parse_datetime(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _job_sort_key(job: dict) -> datetime:
    return _parse_datetime(job.get("date") or job.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc)


def _best_recent_score(jobs: list[dict], window: int = 20) -> Optional[float]:
    scores: list[float] = []
    for job in jobs[:window]:
        try:
            scores.append(float(job.get("best_score", 0) or 0))
        except (TypeError, ValueError):
            continue
    if not scores:
        return None
    return max(scores)
