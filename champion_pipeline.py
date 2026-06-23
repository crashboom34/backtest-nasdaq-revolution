"""Vue pipeline pour suivre l'avancement des Champions et Favoris."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from champion_roadmap import (
    MATURITY_REJECTED,
    MATURITY_RETEST,
    MATURITY_SERIOUS,
    MATURITY_VALIDATE_HISTORY,
    RoadmapItem,
    build_roadmap,
)
from champion_validation import ChampionValidationSettings
from job_decisions import load_decision_events
from retest_plan import RETEST_PLAN_EVENT_LAUNCHED


STAGE_DETECTED = "Détecté"
STAGE_FAVORITE = "Favori"
STAGE_CHAMPION = "Champion"
STAGE_RETEST = "À retester"
STAGE_RETEST_LAUNCHED = "Retest lancé"
STAGE_SERIOUS = "Candidat sérieux"
STAGE_READY_ADVANCED = "Prêt validation avancée"
STAGE_REJECTED = "Rejeté"

PIPELINE_STAGES = (
    STAGE_DETECTED,
    STAGE_FAVORITE,
    STAGE_CHAMPION,
    STAGE_RETEST,
    STAGE_RETEST_LAUNCHED,
    STAGE_SERIOUS,
    STAGE_READY_ADVANCED,
    STAGE_REJECTED,
)


@dataclass(frozen=True)
class PipelineCard:
    item: RoadmapItem
    stage: str
    next_action: str
    last_decision: str

    @property
    def job_id(self) -> str:
        return self.item.job_id

    @property
    def annotation(self) -> str:
        return self.item.annotation

    @property
    def maturity_status(self) -> str:
        return self.item.maturity_status


@dataclass(frozen=True)
class Pipeline:
    cards: tuple[PipelineCard, ...]


@dataclass(frozen=True)
class PipelineSummary:
    stage_counts: dict[str, int]
    serious_count: int
    retest_count: int
    rejected_count: int


def build_pipeline(
    jobs: Iterable[dict],
    settings: ChampionValidationSettings | None = None,
) -> Pipeline:
    settings = settings or ChampionValidationSettings()
    roadmap = build_roadmap(jobs, settings=settings)
    cards = [
        PipelineCard(
            item=item,
            stage=_stage_for_item(item, settings),
            next_action=_next_action_for_item(item),
            last_decision=item.last_decision,
        )
        for item in roadmap.items
    ]
    return Pipeline(cards=tuple(sorted(cards, key=_card_sort_key)))


def pipeline_summary(cards: Iterable[PipelineCard]) -> PipelineSummary:
    rows = list(cards)
    stage_counts = {stage: 0 for stage in PIPELINE_STAGES}
    for card in rows:
        stage_counts[card.stage] = stage_counts.get(card.stage, 0) + 1
    return PipelineSummary(
        stage_counts=stage_counts,
        serious_count=stage_counts.get(STAGE_SERIOUS, 0)
        + stage_counts.get(STAGE_READY_ADVANCED, 0),
        retest_count=stage_counts.get(STAGE_RETEST, 0)
        + stage_counts.get(STAGE_RETEST_LAUNCHED, 0),
        rejected_count=stage_counts.get(STAGE_REJECTED, 0),
    )


def cards_by_stage(cards: Iterable[PipelineCard]) -> dict[str, list[PipelineCard]]:
    grouped = {stage: [] for stage in PIPELINE_STAGES}
    for card in cards:
        grouped.setdefault(card.stage, []).append(card)
    return grouped


def _stage_for_item(item: RoadmapItem, settings: ChampionValidationSettings) -> str:
    record = item.record
    annotation = record.annotation.status
    if annotation == "Rejeté" or item.maturity_status == MATURITY_REJECTED:
        return STAGE_REJECTED
    if _has_retest_launch(record.job_dir):
        return STAGE_RETEST_LAUNCHED
    if annotation == "À revoir":
        return STAGE_DETECTED
    if _needs_retest_stage(item, settings):
        return STAGE_RETEST
    if item.maturity_status == MATURITY_SERIOUS:
        return STAGE_READY_ADVANCED if annotation == "Champion" else STAGE_SERIOUS
    if annotation == "Champion":
        return STAGE_CHAMPION
    if annotation == "Favori":
        return STAGE_FAVORITE
    return STAGE_DETECTED


def _next_action_for_item(item: RoadmapItem) -> str:
    if item.maturity_status == MATURITY_REJECTED or item.annotation == "Rejeté":
        return "Conserver la trace, mais ne pas relancer en priorité."
    if _has_retest_launch(item.record.job_dir):
        return "Suivre le retest lancé puis comparer le nouveau job."
    if item.maturity_status == MATURITY_SERIOUS and item.annotation == "Champion":
        return "Préparer une validation avancée hors de ce module."
    return item.recommended_action


def _needs_retest_stage(
    item: RoadmapItem,
    settings: ChampionValidationSettings,
) -> bool:
    record = item.record
    tags = set(record.annotation.tags)
    if item.maturity_status == MATURITY_VALIDATE_HISTORY:
        return True
    if item.maturity_status != MATURITY_RETEST:
        return False
    if record.preset == "Test rapide local":
        return True
    if record.trades is not None and 0 < record.trades < settings.min_trades:
        return True
    if (
        record.combinations is not None
        and record.combinations < settings.min_combinations
    ):
        return True
    if {"à tester plus longtemps", "trop peu de trades"}.intersection(tags):
        return True
    return "plus d'historique" in item.recommended_action.lower()


def _has_retest_launch(job_dir: str) -> bool:
    return any(
        event.event_type == RETEST_PLAN_EVENT_LAUNCHED
        for event in load_decision_events(job_dir)
    )


def _card_sort_key(card: PipelineCard) -> tuple[int, str]:
    return (
        PIPELINE_STAGES.index(card.stage)
        if card.stage in PIPELINE_STAGES else len(PIPELINE_STAGES),
        card.item.record.date,
    )
