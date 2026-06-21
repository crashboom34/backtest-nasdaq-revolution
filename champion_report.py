"""Synthèse lisible d'un job Champion ou Favori."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from job_annotations import FEATURED_STATUSES
from job_artifacts import list_job_download_files
from job_comparison import JobComparisonRecord, load_job_record
from champion_validation import (
    ChampionValidation,
    ChampionValidationSettings,
    evaluate_champion,
)


DECISION_TEST_LONGER = "test_longer"
DECISION_RELAUNCH = "relaunch"
DECISION_DUPLICATE = "duplicate"
DECISION_OBSERVE = "observe"
DECISION_REJECT = "reject"

GOOD_DRAWDOWN_PCT = 10.0


@dataclass(frozen=True)
class ChampionDecision:
    code: str
    title: str
    explanation: str


@dataclass(frozen=True)
class ChampionReport:
    record: JobComparisonRecord
    available_files: tuple[str, ...]
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    alerts: tuple[str, ...]
    decision: ChampionDecision
    validation: ChampionValidation

    @property
    def missing_metrics(self) -> tuple[str, ...]:
        return self.record.missing_metrics


def load_champion_report(
    job: dict,
    settings: ChampionValidationSettings | None = None,
) -> Optional[ChampionReport]:
    """Construit un rapport uniquement pour un job Champion ou Favori."""
    record = load_job_record(job)
    if record is None or record.annotation.status not in FEATURED_STATUSES:
        return None

    settings = settings or ChampionValidationSettings()
    files = tuple(
        info.filename
        for info in list_job_download_files(record.job_dir)
        if info.can_download
    )
    strengths = _strengths(record, settings)
    weaknesses = _weaknesses(record, settings)
    alerts = _alerts(record, settings)
    decision = _decision(record, settings)
    return ChampionReport(
        record=record,
        available_files=files,
        strengths=tuple(strengths),
        weaknesses=tuple(weaknesses),
        alerts=tuple(alerts),
        decision=decision,
        validation=evaluate_champion(record, settings),
    )


def _strengths(
    record: JobComparisonRecord,
    settings: ChampionValidationSettings,
) -> list[str]:
    points: list[str] = []
    if record.score is not None and record.score > settings.min_score:
        points.append(f"Score positif ({record.score:.1f}).")
    if record.trades is not None and record.trades >= settings.min_trades:
        points.append(f"Échantillon de {record.trades} trades, plus représentatif.")
    if record.win_rate is not None and record.win_rate >= settings.min_win_rate_pct:
        points.append(
            f"Win rate supérieur ou égal au seuil ({record.win_rate:.1f} %)."
        )
    if (
        record.drawdown_pct is not None
        and 0 <= record.drawdown_pct <= GOOD_DRAWDOWN_PCT
    ):
        points.append(f"Drawdown contenu ({record.drawdown_pct:.1f} %).")
    if not record.missing_metrics:
        points.append("Toutes les métriques principales sont disponibles.")
    return points


def _weaknesses(
    record: JobComparisonRecord,
    settings: ChampionValidationSettings,
) -> list[str]:
    points: list[str] = []
    if record.missing_metrics:
        points.append(
            "Métriques manquantes : " + ", ".join(record.missing_metrics) + "."
        )
    if record.score is not None and record.score <= settings.min_score:
        points.append("Le score n'atteint pas le seuil configuré.")
    if record.trades == 0:
        points.append("Le job n'a produit aucun trade.")
    elif record.trades is not None and record.trades < settings.min_trades:
        points.append(
            f"Seulement {record.trades} trades : l'échantillon est encore faible."
        )
    if record.win_rate is not None and record.win_rate < settings.min_win_rate_pct:
        points.append(f"Win rate faible ({record.win_rate:.1f} %).")
    if (
        record.drawdown_pct is not None
        and record.drawdown_pct >= settings.watch_drawdown_pct
    ):
        points.append(f"Drawdown élevé ({record.drawdown_pct:.1f} %).")
    return points


def _alerts(
    record: JobComparisonRecord,
    settings: ChampionValidationSettings,
) -> list[str]:
    alerts: list[str] = []
    if record.missing_metrics:
        alerts.append(
            "Une ou plusieurs métriques sont absentes. La décision doit rester prudente."
        )
    if record.trades == 0:
        alerts.append("Aucun trade : ce résultat ne permet pas de valider la stratégie.")
    elif record.trades is not None and record.trades < settings.min_trades:
        alerts.append(
            f"Trop peu de trades ({record.trades}) pour tirer une conclusion solide."
        )
    if record.score is not None and record.score <= settings.min_score:
        alerts.append("Score sous le seuil configuré : le job est trop faible en l'état.")
    if (
        record.drawdown_pct is not None
        and record.drawdown_pct >= settings.watch_drawdown_pct
    ):
        alerts.append(
            f"Drawdown élevé ({record.drawdown_pct:.1f} %) : le risque doit être réduit."
        )
    return alerts


def _decision(
    record: JobComparisonRecord,
    settings: ChampionValidationSettings,
) -> ChampionDecision:
    tags = set(record.annotation.tags)
    if (
        record.trades == 0
        or (record.score is not None and record.score <= settings.min_score)
    ):
        return ChampionDecision(
            DECISION_REJECT,
            "Rejeter en l'état",
            "Aucun trade exploitable ou score trop faible. Garde le job seulement comme trace.",
        )

    if "score" in record.missing_metrics or "trades" in record.missing_metrics:
        return ChampionDecision(
            DECISION_OBSERVE,
            "Garder en observation",
            "Les métriques essentielles sont incomplètes. Évite une relance coûteuse avant de les vérifier.",
        )

    if (
        "trop peu de trades" in tags
        or "à tester plus longtemps" in tags
        or (record.trades is not None and record.trades < settings.min_trades)
    ):
        return ChampionDecision(
            DECISION_TEST_LONGER,
            "Tester plus longtemps",
            "L'échantillon est prometteur mais trop court pour conclure avec confiance.",
        )

    if (
        "drawdown élevé" in tags
        or (
            record.drawdown_pct is not None
            and record.drawdown_pct >= settings.watch_drawdown_pct
        )
    ):
        return ChampionDecision(
            DECISION_DUPLICATE,
            "Dupliquer et ajuster la config",
            "Le risque est élevé. Charge la configuration et réduis son exposition avant une nouvelle optimisation.",
        )

    if record.missing_metrics:
        return ChampionDecision(
            DECISION_OBSERVE,
            "Garder en observation",
            "Le résultat est intéressant, mais certaines métriques secondaires manquent encore.",
        )

    return ChampionDecision(
        DECISION_RELAUNCH,
        "Relancer la même config",
        "Les indicateurs disponibles sont cohérents. Une relance sur davantage d'historique peut confirmer la robustesse.",
    )
