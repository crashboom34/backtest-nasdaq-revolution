"""Liens en lecture seule entre un Champion/Favori source et ses retests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from job_comparison import load_job_record
from job_decisions import load_decision_events
from retest_plan import RETEST_PLAN_EVENT_LAUNCHED


UNKNOWN_VALUE = "non renseigné"
LEGACY_VALUE = "ancien job"


@dataclass(frozen=True)
class RetestLink:
    source_job_id: str
    retest_job_id: str
    retest_status: str
    score: float | None = None
    trades: int | None = None
    drawdown_pct: float | None = None
    preset: str = LEGACY_VALUE
    data_file: str = UNKNOWN_VALUE
    missing_metrics: tuple[str, ...] = ()


def build_retest_link_index(jobs: Iterable[dict]) -> dict[str, tuple[RetestLink, ...]]:
    """Construit source_job_id -> retests sans modifier les dossiers de job."""
    job_list = list(jobs)
    jobs_by_id = {
        str(job.get("job_id", "") or ""): job
        for job in job_list
        if job.get("job_id")
    }
    linked_ids: dict[str, list[str]] = {}

    for job in job_list:
        record = load_job_record(job)
        if record is None:
            continue
        source_id = _source_from_retest_config(record.config)
        if source_id:
            _append_unique(linked_ids, source_id, record.job_id)

    for source_job_id, job in jobs_by_id.items():
        for retest_job_id in _retests_from_decisions(job.get("job_dir", "")):
            _append_unique(linked_ids, source_job_id, retest_job_id)

    return {
        source_id: tuple(
            _build_link(source_id, retest_job_id, jobs_by_id.get(retest_job_id))
            for retest_job_id in retest_ids
        )
        for source_id, retest_ids in linked_ids.items()
    }


def _source_from_retest_config(config: dict) -> str:
    if not isinstance(config, dict):
        return ""
    return str(config.get("retest_plan_source_job_id") or "").strip()


def _retests_from_decisions(job_dir: str) -> list[str]:
    retest_ids: list[str] = []
    for event in load_decision_events(job_dir):
        if event.event_type != RETEST_PLAN_EVENT_LAUNCHED:
            continue
        new_state = event.new_state or {}
        retest_id = str(new_state.get("new_job_id") or "").strip()
        if retest_id:
            retest_ids.append(retest_id)
    return retest_ids


def _build_link(
    source_job_id: str,
    retest_job_id: str,
    retest_job: dict | None,
) -> RetestLink:
    if not retest_job:
        return RetestLink(
            source_job_id=source_job_id,
            retest_job_id=retest_job_id,
            retest_status=UNKNOWN_VALUE,
        )

    record = load_job_record(retest_job)
    if record is None:
        return RetestLink(
            source_job_id=source_job_id,
            retest_job_id=retest_job_id,
            retest_status=str(retest_job.get("status") or UNKNOWN_VALUE),
        )

    return RetestLink(
        source_job_id=source_job_id,
        retest_job_id=record.job_id,
        retest_status=record.status or str(retest_job.get("status") or UNKNOWN_VALUE),
        score=record.score,
        trades=record.trades,
        drawdown_pct=record.drawdown_pct,
        preset=record.preset or LEGACY_VALUE,
        data_file=record.data_file or UNKNOWN_VALUE,
        missing_metrics=record.missing_metrics,
    )


def _append_unique(mapping: dict[str, list[str]], source_id: str, retest_id: str) -> None:
    if not source_id or not retest_id or source_id == retest_id:
        return
    items = mapping.setdefault(source_id, [])
    if retest_id not in items:
        items.append(retest_id)
