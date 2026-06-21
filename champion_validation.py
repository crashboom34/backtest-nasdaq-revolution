"""Checklist simple pour juger la solidité d'un Champion ou Favori."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from job_comparison import JobComparisonRecord


STATUS_VALID = "Validé"
STATUS_WATCH = "À surveiller"
STATUS_BLOCKING = "Bloquant"
STATUS_UNKNOWN = "Inconnu"

VERDICT_SERIOUS = "Candidat sérieux"
VERDICT_PROMISING = "Prometteur mais à retester"
VERDICT_INSUFFICIENT = "Insuffisant"
VERDICT_INCOMPLETE = "Données incomplètes"

MIN_TRADES = 30
MIN_COMBINATIONS = 100
WATCH_DRAWDOWN_PCT = 20.0
BLOCKING_DRAWDOWN_PCT = 30.0
MIN_WIN_RATE_PCT = 40.0
MIN_ROWS = 100_000
MIN_PERIOD_DAYS = 180


@dataclass(frozen=True)
class ValidationCriterion:
    code: str
    label: str
    status: str
    detail: str


@dataclass(frozen=True)
class ChampionValidation:
    criteria: tuple[ValidationCriterion, ...]
    verdict: str
    recommendation: str


def evaluate_champion(record: JobComparisonRecord) -> ChampionValidation:
    criteria = (
        _trades_criterion(record),
        _score_criterion(record),
        _drawdown_criterion(record),
        _win_rate_criterion(record),
        _metrics_criterion(record),
        _preset_criterion(record),
        _combinations_criterion(record),
        _data_period_criterion(record),
    )
    verdict = _verdict(record, criteria)
    return ChampionValidation(
        criteria=criteria,
        verdict=verdict,
        recommendation=_recommendation(record, criteria, verdict),
    )


def _criterion(code: str, label: str, status: str, detail: str) -> ValidationCriterion:
    return ValidationCriterion(code=code, label=label, status=status, detail=detail)


def _trades_criterion(record: JobComparisonRecord) -> ValidationCriterion:
    if record.trades is None:
        return _criterion("trades", "Nombre de trades suffisant", STATUS_UNKNOWN, "Nombre de trades absent.")
    if record.trades == 0:
        return _criterion("trades", "Nombre de trades suffisant", STATUS_BLOCKING, "Aucun trade produit.")
    if record.trades < MIN_TRADES:
        return _criterion(
            "trades",
            "Nombre de trades suffisant",
            STATUS_WATCH,
            f"{record.trades} trades, seuil conseillé : {MIN_TRADES}.",
        )
    return _criterion(
        "trades",
        "Nombre de trades suffisant",
        STATUS_VALID,
        f"{record.trades} trades.",
    )


def _score_criterion(record: JobComparisonRecord) -> ValidationCriterion:
    if record.score is None:
        return _criterion("score", "Score positif", STATUS_UNKNOWN, "Score absent.")
    if record.score <= 0:
        return _criterion("score", "Score positif", STATUS_BLOCKING, f"Score {record.score:.2f}.")
    return _criterion("score", "Score positif", STATUS_VALID, f"Score {record.score:.2f}.")


def _drawdown_criterion(record: JobComparisonRecord) -> ValidationCriterion:
    value = record.drawdown_pct
    if value is None:
        return _criterion("drawdown", "Drawdown acceptable", STATUS_UNKNOWN, "Drawdown absent.")
    if value >= BLOCKING_DRAWDOWN_PCT:
        status = STATUS_BLOCKING
    elif value >= WATCH_DRAWDOWN_PCT:
        status = STATUS_WATCH
    else:
        status = STATUS_VALID
    return _criterion("drawdown", "Drawdown acceptable", status, f"Drawdown {value:.2f} %.")


def _win_rate_criterion(record: JobComparisonRecord) -> ValidationCriterion:
    value = record.win_rate
    if value is None:
        return _criterion("win_rate", "Win rate exploitable", STATUS_UNKNOWN, "Win rate absent.")
    status = STATUS_VALID if value >= MIN_WIN_RATE_PCT else STATUS_WATCH
    return _criterion("win_rate", "Win rate exploitable", status, f"Win rate {value:.2f} %.")


def _metrics_criterion(record: JobComparisonRecord) -> ValidationCriterion:
    essential = {"score", "trades", "drawdown", "combinaisons"}
    missing = sorted(essential.intersection(record.missing_metrics))
    if missing:
        return _criterion(
            "metrics",
            "Métriques essentielles présentes",
            STATUS_BLOCKING,
            "Manquantes : " + ", ".join(missing) + ".",
        )
    return _criterion(
        "metrics",
        "Métriques essentielles présentes",
        STATUS_VALID,
        "Score, trades, drawdown et combinaisons disponibles.",
    )


def _preset_criterion(record: JobComparisonRecord) -> ValidationCriterion:
    preset = record.preset or "Inconnu"
    if preset == "Test rapide local":
        return _criterion(
            "preset",
            "Optimisation représentative",
            STATUS_WATCH,
            "Le test rapide valide le pipeline, pas la robustesse.",
        )
    if preset == "Ancien job":
        return _criterion("preset", "Optimisation représentative", STATUS_UNKNOWN, "Preset non enregistré.")
    return _criterion("preset", "Optimisation représentative", STATUS_VALID, f"Preset : {preset}.")


def _combinations_criterion(record: JobComparisonRecord) -> ValidationCriterion:
    if record.combinations is None:
        return _criterion("combinations", "Assez de combinaisons testées", STATUS_UNKNOWN, "Nombre absent.")
    status = STATUS_VALID if record.combinations >= MIN_COMBINATIONS else STATUS_WATCH
    return _criterion(
        "combinations",
        "Assez de combinaisons testées",
        status,
        f"{record.combinations} combinaisons, seuil conseillé : {MIN_COMBINATIONS}.",
    )


def _data_period_criterion(record: JobComparisonRecord) -> ValidationCriterion:
    config = record.config or {}
    start = _parse_date(config.get("opt_start_date"))
    end = _parse_date(config.get("opt_end_date"))
    if start and end and end >= start:
        days = (end - start).days
        status = STATUS_VALID if days >= MIN_PERIOD_DAYS else STATUS_WATCH
        return _criterion(
            "data_period",
            "Période ou données suffisantes",
            status,
            f"Période de {days} jours, seuil conseillé : {MIN_PERIOD_DAYS}.",
        )
    if "max_rows" in config:
        max_rows = config.get("max_rows")
        if max_rows is None:
            return _criterion(
                "data_period",
                "Période ou données suffisantes",
                STATUS_VALID,
                "Historique complet demandé.",
            )
        status = STATUS_VALID if int(max_rows) >= MIN_ROWS else STATUS_WATCH
        return _criterion(
            "data_period",
            "Période ou données suffisantes",
            status,
            f"{int(max_rows):,} lignes maximum, seuil conseillé : {MIN_ROWS:,}.",
        )
    return _criterion(
        "data_period",
        "Période ou données suffisantes",
        STATUS_UNKNOWN,
        "Limite de lignes ou période non enregistrée.",
    )


def _verdict(
    record: JobComparisonRecord,
    criteria: tuple[ValidationCriterion, ...],
) -> str:
    essential_missing = {"score", "trades", "drawdown", "combinaisons"}.intersection(
        record.missing_metrics
    )
    if essential_missing:
        return VERDICT_INCOMPLETE
    if any(item.status == STATUS_BLOCKING for item in criteria):
        return VERDICT_INSUFFICIENT
    if all(item.status == STATUS_VALID for item in criteria):
        return VERDICT_SERIOUS
    return VERDICT_PROMISING


def _recommendation(
    record: JobComparisonRecord,
    criteria: tuple[ValidationCriterion, ...],
    verdict: str,
) -> str:
    by_code = {item.code: item for item in criteria}
    if verdict == VERDICT_INCOMPLETE:
        return "Garder en observation et compléter les métriques avant toute décision."
    if by_code["trades"].status == STATUS_BLOCKING or by_code["score"].status == STATUS_BLOCKING:
        return "Rejeter en l'état : le résultat ne contient pas de signal exploitable."
    if by_code["drawdown"].status == STATUS_BLOCKING:
        return "Vérifier le drawdown et réduire le risque avant toute nouvelle validation."
    if by_code["drawdown"].status == STATUS_WATCH:
        return "Vérifier le drawdown avant de retenir ce job comme référence."
    if by_code["preset"].status == STATUS_WATCH or by_code["data_period"].status == STATUS_WATCH:
        return "Relancer sur plus d'historique avec un preset représentatif."
    if by_code["trades"].status == STATUS_WATCH:
        return "Relancer sur plus d'historique pour obtenir davantage de trades."
    if by_code["combinations"].status == STATUS_WATCH:
        return "Augmenter le nombre de combinaisons avant validation définitive."
    return "Garder en observation et confirmer le résultat sur une prochaine exécution."


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
