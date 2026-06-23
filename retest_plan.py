"""Plans de retest pour confirmer un Champion ou Favori prometteur."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from champion_validation import (
    VERDICT_INCOMPLETE,
    ChampionValidationSettings,
    evaluate_champion,
)
from job_comparison import JobComparisonRecord
from job_decisions import CATEGORY_ACTION, append_decision_event
from job_launcher import clone_config_for_new_job
from optimization_presets import get_preset


RETEST_PLAN_EVENT_DUPLICATED = "retest_plan_duplicated"
RETEST_PLAN_EVENT_LAUNCHED = "retest_plan_launched"
RETEST_PLAN_EVENT_NOTE_TAGGED = "retest_plan_note_tagged"


@dataclass(frozen=True)
class RetestPlan:
    source_job_id: str
    recommended_preset: str
    max_rows: Optional[int]
    max_combinations: Optional[int]
    workers: int
    benchmark_n_sample: int
    justification: str
    suggested_tags: tuple[str, ...] = ()
    launch_warning: str = ""

    @property
    def is_limited_enough_to_launch(self) -> bool:
        return self.max_combinations is not None and self.max_combinations <= 300


def build_retest_plan(
    record: JobComparisonRecord,
    settings: ChampionValidationSettings | None = None,
    cpu_count: int | None = None,
) -> RetestPlan:
    settings = settings or ChampionValidationSettings()
    validation = evaluate_champion(record, settings)
    workers_medium = _bounded_workers(cpu_count, preferred=2)
    workers_full = _bounded_workers(cpu_count, preferred=4)

    essential_missing = {"score", "trades", "drawdown", "combinaisons"}.intersection(
        record.missing_metrics
    )
    if validation.verdict == VERDICT_INCOMPLETE or essential_missing:
        return RetestPlan(
            source_job_id=record.job_id,
            recommended_preset="Personnalisé",
            max_rows=None,
            max_combinations=100,
            workers=workers_medium,
            benchmark_n_sample=3,
            justification=(
                "Données incomplètes : vérifie les métriques et importe plus de données "
                "avant de tirer une conclusion."
            ),
            suggested_tags=("à tester plus longtemps",),
        )

    if record.preset == "Test rapide local":
        return RetestPlan(
            source_job_id=record.job_id,
            recommended_preset="Test moyen",
            max_rows=100_000,
            max_combinations=100,
            workers=workers_medium,
            benchmark_n_sample=3,
            justification=(
                "Test rapide local : le pipeline est validé, mais il faut un échantillon "
                "plus large pour savoir si le signal tient."
            ),
            suggested_tags=("à tester plus longtemps",),
        )

    if record.trades is not None and 0 < record.trades < settings.min_trades:
        return RetestPlan(
            source_job_id=record.job_id,
            recommended_preset="Optimisation complète",
            max_rows=None,
            max_combinations=300,
            workers=workers_full,
            benchmark_n_sample=5,
            justification=(
                f"Trop peu de trades ({record.trades}) : relancer sur plus d'historique "
                "pour obtenir un échantillon plus fiable."
            ),
            suggested_tags=("trop peu de trades", "à tester plus longtemps"),
        )

    if (
        record.drawdown_pct is not None
        and record.drawdown_pct >= settings.watch_drawdown_pct
    ):
        return RetestPlan(
            source_job_id=record.job_id,
            recommended_preset="Test moyen",
            max_rows=100_000,
            max_combinations=100,
            workers=workers_medium,
            benchmark_n_sample=3,
            justification=(
                f"Drawdown élevé ({record.drawdown_pct:.1f} %) : retester prudemment "
                "avant de considérer ce job comme robuste."
            ),
            suggested_tags=("drawdown élevé",),
        )

    return RetestPlan(
        source_job_id=record.job_id,
        recommended_preset="Optimisation complète",
        max_rows=None,
        max_combinations=300,
        workers=workers_full,
        benchmark_n_sample=5,
        justification=(
            "Candidat sérieux : relancer sur plus d'historique pour confirmer la robustesse."
        ),
        suggested_tags=("prometteur", "à tester plus longtemps"),
        launch_warning="Peut être long si tu retires la limite de combinaisons.",
    )


def apply_retest_plan_to_config(
    config: dict,
    plan: RetestPlan,
    source_job_id: str = "",
) -> dict:
    cfg = clone_config_for_new_job(deepcopy(config or {}), source_job_id or plan.source_job_id)
    preset = get_preset(plan.recommended_preset)
    cfg.update({
        "preset_name": plan.recommended_preset,
        "preset_description": preset.description,
        "max_rows": plan.max_rows,
        "max_combinations": plan.max_combinations,
        "benchmark_n_sample": int(plan.benchmark_n_sample),
        "workers": int(plan.workers),
        "n_workers": int(plan.workers),
        "quick_validation_mode": False,
        "retest_plan_source_job_id": source_job_id or plan.source_job_id,
        "retest_plan_justification": plan.justification,
    })
    return cfg


def record_retest_plan_decision(
    job_dir: str | Path,
    event_type: str,
    message: str,
    plan: RetestPlan,
    new_job_id: str = "",
) -> None:
    state = asdict(plan)
    state["suggested_tags"] = list(plan.suggested_tags)
    if new_job_id:
        state["new_job_id"] = new_job_id
    append_decision_event(
        job_dir,
        event_type,
        CATEGORY_ACTION,
        message,
        new_state=state,
    )


def _bounded_workers(cpu_count: int | None, preferred: int) -> int:
    cpu = int(cpu_count or preferred or 1)
    return max(1, min(preferred, cpu))
