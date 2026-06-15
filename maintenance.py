"""
maintenance.py - Analyse et nettoyage local securise.

Ce module ne supprime rien par defaut. Il prepare des plans de nettoyage
et limite toute suppression reelle a des dossiers explicitement autorises.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from path_resolver import BASE_DIR, to_relative_path


TERMINAL_STATUSES = {"completed", "failed", "error", "stopped"}
ACTIVE_STATUSES = {"created", "benchmarking", "running"}
TEST_DATA_PREFIX = "PWCSV"

PROTECTED_NAMES = {
    ".env",
    ".venv",
    ".git",
    "nasdaq_3m.csv",
    "credentials.toml",
    "app_corrupted_backup.py",
}


@dataclass(frozen=True)
class MaintenanceItem:
    kind: str
    identifier: str
    path: Path
    relative_path: str
    status: str = ""
    date: str = ""
    asset: str = ""
    timeframe: str = ""
    size_bytes: int = 0
    file_count: int = 0
    archive_exists: bool = False
    active: bool = False
    deletable: bool = False
    reason: str = ""


@dataclass(frozen=True)
class CleanupPlan:
    items: list[MaintenanceItem]
    total_size_bytes: int
    total_file_count: int


@dataclass(frozen=True)
class CleanupResult:
    dry_run: bool
    deleted: list[str]
    skipped: list[str]
    errors: list[str]
    reclaimed_bytes: int


def disk_usage_for_base(base_dir: Path = BASE_DIR) -> dict[str, int]:
    usage = shutil.disk_usage(Path(base_dir).resolve().anchor)
    return {
        "total": int(usage.total),
        "used": int(usage.used),
        "free": int(usage.free),
    }


def folder_size(path: str | Path) -> int:
    root = Path(path)
    if not root.exists():
        return 0
    if root.is_file():
        try:
            return int(root.stat().st_size)
        except OSError:
            return 0

    total = 0
    for item in root.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return int(total)


def count_files(path: str | Path) -> int:
    root = Path(path)
    if not root.exists():
        return 0
    if root.is_file():
        return 1
    return sum(1 for item in root.rglob("*") if item.is_file())


def _read_json(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def _mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return ""


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(date_value: str, fallback_path: Path, now: Optional[datetime] = None) -> float:
    now_dt = now or datetime.now(timezone.utc)
    parsed = _parse_iso(date_value)
    if parsed is None:
        parsed = _parse_iso(_mtime_iso(fallback_path))
    if parsed is None:
        return 0.0
    return max(0.0, (now_dt - parsed).total_seconds() / 86400)


def _relative(path: Path, base_dir: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def inspect_job_dir(job_dir: str | Path, base_dir: Path = BASE_DIR) -> MaintenanceItem:
    path = Path(job_dir).resolve()
    job_id = path.name
    progress = _read_json(path / "progress.json")
    config = _read_json(path / "config_used.json")
    meta = _read_json(path / "meta.json")

    status = str(progress.get("status") or meta.get("status") or ("created" if config else "unknown"))
    date = str(progress.get("started_at") or meta.get("date") or _mtime_iso(path))
    asset = str(config.get("asset") or meta.get("asset") or "")
    timeframe = str(config.get("timeframe") or meta.get("timeframe") or "")
    active = status in ACTIVE_STATUSES
    archive_exists = (path / "archive.zip").is_file()

    if active:
        deletable = False
        reason = "job actif protege"
    elif status in TERMINAL_STATUSES:
        deletable = True
        reason = "job termine supprimable"
    else:
        deletable = False
        reason = f"statut non terminal protege : {status}"

    return MaintenanceItem(
        kind="job",
        identifier=job_id,
        path=path,
        relative_path=_relative(path, base_dir),
        status=status,
        date=date,
        asset=asset,
        timeframe=timeframe,
        size_bytes=folder_size(path),
        file_count=count_files(path),
        archive_exists=archive_exists,
        active=active,
        deletable=deletable,
        reason=reason,
    )


def list_job_items(base_dir: Path = BASE_DIR) -> list[MaintenanceItem]:
    results_dir = Path(base_dir) / "results"
    if not results_dir.is_dir():
        return []
    items = [
        inspect_job_dir(path, base_dir=base_dir)
        for path in results_dir.iterdir()
        if path.is_dir() and path.name.startswith("job_")
    ]
    return sorted(items, key=lambda item: item.date, reverse=True)


def list_pwcsv_data_items(base_dir: Path = BASE_DIR) -> list[MaintenanceItem]:
    data_dir = Path(base_dir) / "data"
    if not data_dir.is_dir():
        return []
    items: list[MaintenanceItem] = []
    for path in data_dir.iterdir():
        if not path.is_dir() or not path.name.startswith(TEST_DATA_PREFIX):
            continue
        items.append(MaintenanceItem(
            kind="test_data",
            identifier=path.name,
            path=path.resolve(),
            relative_path=_relative(path, base_dir),
            status="test",
            date=_mtime_iso(path),
            size_bytes=folder_size(path),
            file_count=count_files(path),
            deletable=True,
            reason="dossier de test Playwright PWCSV",
        ))
    return sorted(items, key=lambda item: item.date, reverse=True)


def select_cleanup_jobs(
    jobs: list[MaintenanceItem],
    include_completed: bool = True,
    include_errors: bool = False,
    older_than_days: int = 0,
    heaviest_limit: int = 0,
    now: Optional[datetime] = None,
) -> list[MaintenanceItem]:
    selected: list[MaintenanceItem] = []
    for job in jobs:
        if not job.deletable or job.active:
            continue
        status = job.status.lower()
        if status == "completed" and not include_completed:
            continue
        if status in {"failed", "error", "stopped"} and not include_errors:
            continue
        if older_than_days > 0 and _age_days(job.date, job.path, now=now) < older_than_days:
            continue
        selected.append(job)

    selected.sort(key=lambda item: item.size_bytes, reverse=True)
    if heaviest_limit > 0:
        return selected[:heaviest_limit]
    return selected


def build_cleanup_plan(items: Iterable[MaintenanceItem]) -> CleanupPlan:
    clean_items = list(items)
    return CleanupPlan(
        items=clean_items,
        total_size_bytes=sum(item.size_bytes for item in clean_items),
        total_file_count=sum(item.file_count for item in clean_items),
    )


def _path_contains_protected_name(path: Path) -> bool:
    paths = [path]
    if path.is_dir():
        try:
            paths.extend(path.rglob("*"))
        except OSError:
            return True
    for item in paths:
        if item.name in PROTECTED_NAMES:
            return True
        parts = set(item.parts)
        if ".git" in parts or ".venv" in parts:
            return True
        if ".streamlit" in parts and item.name == "credentials.toml":
            return True
    return False


def is_allowed_delete_path(path: str | Path, base_dir: Path = BASE_DIR) -> bool:
    target = Path(path).resolve()
    base = Path(base_dir).resolve()
    try:
        rel = target.relative_to(base)
    except ValueError:
        return False

    parts = rel.parts
    if len(parts) != 2:
        return False

    if _path_contains_protected_name(target):
        return False

    if parts[0] == "results" and parts[1].startswith("job_") and target.is_dir():
        return True
    if parts[0] == "data" and parts[1].startswith(TEST_DATA_PREFIX) and target.is_dir():
        return True
    return False


def delete_items(
    items: Iterable[MaintenanceItem],
    base_dir: Path = BASE_DIR,
    dry_run: bool = True,
) -> CleanupResult:
    deleted: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    reclaimed = 0

    for item in items:
        label = item.relative_path or str(item.path)
        if not item.deletable or item.active:
            skipped.append(f"{label} : {item.reason or 'protege'}")
            continue
        if not is_allowed_delete_path(item.path, base_dir=base_dir):
            skipped.append(f"{label} : chemin non autorise")
            continue
        if dry_run:
            skipped.append(f"{label} : simulation")
            reclaimed += item.size_bytes
            continue
        try:
            size_before = folder_size(item.path)
            shutil.rmtree(item.path)
            deleted.append(label)
            reclaimed += size_before
        except OSError as exc:
            errors.append(f"{label} : {exc}")

    return CleanupResult(
        dry_run=dry_run,
        deleted=deleted,
        skipped=skipped,
        errors=errors,
        reclaimed_bytes=reclaimed,
    )

