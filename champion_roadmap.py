"""Roadmap de validation des jobs annotés Champion/Favori/À revoir/Rejeté."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from champion_validation import (
    VERDICT_INCOMPLETE,
    VERDICT_INSUFFICIENT,
    VERDICT_PROMISING,
    VERDICT_SERIOUS,
    ChampionValidationSettings,
    evaluate_champion,
)
from job_annotations import ANNOTATION_STATUSES
from job_comparison import JobComparisonRecord, load_job_record
from job_decisions import load_decision_events


MATURITY_RETEST = "À retester"
MATURITY_VALIDATE_HISTORY = "À valider sur plus d'historique"
MATURITY_SERIOUS = "Candidat sérieux"
MATURITY_INCOMPLETE = "Données incomplètes"
MATURITY_REJECTED = "Rejeté"

ROADMAP_ANNOTATIONS = tuple(status for status in ANNOTATION_STATUSES if status)
ROADMAP_MATURITIES = (
    MATURITY_RETEST,
    MATURITY_VALIDATE_HISTORY,
    MATURITY_SERIOUS,
    MATURITY_INCOMPLETE,
    MATURITY_REJECTED,
)


@dataclass(frozen=True)
class RoadmapItem:
    record: JobComparisonRecord
    maturity_status: str
    validation_verdict: str
    recommended_action: str
    last_decision: str

    @property
    def job_id(self) -> str:
        return self.record.job_id

    @property
    def annotation(self) -> str:
        return self.record.annotation.status

    @property
    def note_short(self) -> str:
        note = self.record.annotation.note.strip()
        if len(note) <= 90:
            return note
        return note[:87].rstrip() + "..."

    @property
    def tags(self) -> tuple[str, ...]:
        return self.record.annotation.tags

    @property
    def asset_timeframe(self) -> str:
        return f"{self.record.asset}/{self.record.timeframe}"


@dataclass(frozen=True)
class Roadmap:
    items: tuple[RoadmapItem, ...]


@dataclass(frozen=True)
class RoadmapSummary:
    serious_count: int
    retest_count: int
    rejected_count: int
    priority_job_id: str
    priority_action: str


def build_roadmap(
    jobs: Iterable[dict],
    settings: ChampionValidationSettings | None = None,
) -> Roadmap:
    settings = settings or ChampionValidationSettings()
    items: list[RoadmapItem] = []
    for job in jobs:
        record = load_job_record(job)
        if record is None or record.annotation.status not in ROADMAP_ANNOTATIONS:
            continue
        validation = evaluate_champion(record, settings)
        maturity = _maturity_status(record, validation.verdict)
        items.append(RoadmapItem(
            record=record,
            maturity_status=maturity,
            validation_verdict=validation.verdict,
            recommended_action=_recommended_action(record, maturity, validation.recommendation),
            last_decision=_last_decision(record.job_dir),
        ))
    return Roadmap(items=tuple(sorted(
        items,
        key=lambda item: (_maturity_rank(item.maturity_status), item.record.date),
        reverse=False,
    )))


def filter_roadmap_items(
    items: Iterable[RoadmapItem],
    annotation: str = "",
    maturity_status: str = "",
    asset_timeframe: str = "",
    tag: str = "",
) -> list[RoadmapItem]:
    filtered = list(items)
    if annotation:
        filtered = [item for item in filtered if item.annotation == annotation]
    if maturity_status:
        filtered = [
            item for item in filtered
            if item.maturity_status == maturity_status
        ]
    if asset_timeframe:
        filtered = [
            item for item in filtered
            if item.asset_timeframe == asset_timeframe
        ]
    if tag:
        filtered = [item for item in filtered if tag in item.tags]
    return filtered


def roadmap_summary(items: Iterable[RoadmapItem]) -> RoadmapSummary:
    rows = list(items)
    serious_count = sum(1 for item in rows if item.maturity_status == MATURITY_SERIOUS)
    retest_count = sum(
        1 for item in rows
        if item.maturity_status in {MATURITY_RETEST, MATURITY_VALIDATE_HISTORY}
    )
    rejected_count = sum(1 for item in rows if item.maturity_status == MATURITY_REJECTED)
    priority = _priority_item(rows)
    return RoadmapSummary(
        serious_count=serious_count,
        retest_count=retest_count,
        rejected_count=rejected_count,
        priority_job_id=priority.job_id if priority else "",
        priority_action=priority.recommended_action if priority else "Aucune action prioritaire.",
    )


def _maturity_status(record: JobComparisonRecord, verdict: str) -> str:
    if record.annotation.status == "Rejeté":
        return MATURITY_REJECTED
    if verdict == VERDICT_INCOMPLETE:
        return MATURITY_INCOMPLETE
    if verdict == VERDICT_INSUFFICIENT:
        return MATURITY_REJECTED
    if verdict == VERDICT_SERIOUS:
        return MATURITY_SERIOUS
    if verdict == VERDICT_PROMISING and _needs_more_history(record):
        return MATURITY_VALIDATE_HISTORY
    return MATURITY_RETEST


def _recommended_action(
    record: JobComparisonRecord,
    maturity_status: str,
    validation_recommendation: str,
) -> str:
    if maturity_status == MATURITY_REJECTED:
        return "Rejeté : conserver la trace, mais ne pas relancer en priorité."
    if maturity_status == MATURITY_INCOMPLETE:
        return "Compléter ou vérifier les métriques avant de décider."
    if maturity_status == MATURITY_VALIDATE_HISTORY:
        return "Relancer sur plus d'historique avec un preset représentatif."
    if maturity_status == MATURITY_RETEST:
        return validation_recommendation
    if record.annotation.status == "Champion":
        return "Garder en observation et confirmer avant usage réel."
    return validation_recommendation


def _needs_more_history(record: JobComparisonRecord) -> bool:
    if record.preset == "Test rapide local":
        return True
    config = record.config or {}
    max_rows = config.get("max_rows")
    return max_rows is not None


def _last_decision(job_dir: str) -> str:
    events = load_decision_events(job_dir)
    return events[-1].message if events else "Aucune décision enregistrée."


def _priority_item(items: list[RoadmapItem]) -> RoadmapItem | None:
    candidates = [
        item for item in items
        if item.maturity_status != MATURITY_REJECTED
    ]
    if not candidates:
        return items[0] if items else None
    return min(candidates, key=lambda item: _maturity_rank(item.maturity_status))


def _maturity_rank(status: str) -> int:
    order = {
        MATURITY_INCOMPLETE: 0,
        MATURITY_VALIDATE_HISTORY: 1,
        MATURITY_RETEST: 2,
        MATURITY_SERIOUS: 3,
        MATURITY_REJECTED: 4,
    }
    return order.get(status, 99)
