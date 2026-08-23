"""
validation_run.py — ValidationRun / OosValidationEvidence, première validation réelle (AF-V-01).

Track V (Scientific Validation), premier consommateur réel de `dataset_split.py` (Track R,
`AF-R-03`). Voir `docs/architecture/DOMAIN_MODEL.md` §7 pour le concept d'origine
(`ValidationRun`/`ValidationCampaign`/`RobustnessTest`) et §12 pour `DatasetSplitPlan`/
`HoldoutAccessEvent`.

**Résolution `/domain-modeling` (AF-V-01, 2026-08-15)** — tension documentaire trouvée et
tranchée, pas une invention : DOMAIN_MODEL.md ligne 369 dit `ValidationRun` "Rattaché à un
`CandidateStrategy` ou `Champion`, **pas nécessairement** à un `ResearchRun`". Lecture retenue :
"pas nécessairement" = pas une exigence universelle (ex. re-validation future d'un `Champion` sans
nouveau `ResearchRun`), **pas** une interdiction de référencer un `ResearchRun` quand un existe
réellement — c'est justement le cas ici : `CandidateStrategy`/`Champion` sont des concepts
Discovery `PROPOSED`, jamais implémentés en code, explicitement hors scope de ce ticket (aucune
config testée via l'optimiseur, `Perfect Revolution` utilise directement `DEFAULT_PARAMS`, jamais
réglé par ce dépôt). `ValidationRun.research_run_id` est donc cohérent avec le Domain Model
existant, pas une contradiction — aucun STOP nécessaire.

**Modèle retenu** : `ResearchRun` (Track R, exécution de recherche générale) et `ValidationRun`
(Track V, verdict de validation typé) restent **deux objets distincts** liés par référence — pas
fusionnés, même s'il existe une relation 1:1 dans ce ticket. Une seule `ResearchRun` pourrait à
l'avenir déclencher plusieurs `ValidationRun` (OOS, Walk-Forward, Monte-Carlo... — voir
`ValidationCampaign`, déjà `PROPOSED` pour ce regroupement). `ValidationRun` porte **directement**
`research_run_id`, `split_plan_id` **et** `dataset_snapshot_id` — jamais seulement l'un via une
jointure implicite sur l'autre, même principe déjà établi pour `HoldoutAccessEvent` (`AF-R-03`) :
la preuve que CE `ResearchRun`/CETTE `ValidationRun` a utilisé CE `split_plan_id` vit sur
`ValidationRun` elle-même (pas rajoutée rétroactivement sur `ResearchRun`, qui reste inchangée —
voir `research_run.py`, aucune modification pour ce ticket). Aucune relation bidirectionnelle
redondante (`ResearchRun`/`DatasetSplitPlan` ne listent pas leurs `ValidationRun` en retour).

**`validation_type` fixé à `"oos"` pour ce ticket** : DOMAIN_MODEL.md (lignes 453-454) est explicite
— "chaque `ValidationRun` porte une `ValidationSpecification` et une `ValidationEvidence` **typées
selon son `validation_type`**, pas un simple couple générique". `AF-V-06` traite la généralisation
future (Walk-Forward/Monte-Carlo/Stress) ; ce module ne construit **pas** de framework
polymorphique prématuré — `OosValidationEvidence` est le seul type d'évidence, `validation_type`
reste une chaîne fixe validée `"oos"`, pas un `Enum`/registre extensible à ce stade.

**Aucun jugement subjectif** : `OosValidationEvidence` ne porte que des métriques **factuelles**
déjà natives du moteur (`engine.py::_compute_stats()`) — jamais un score "robustness", jamais un
champ "champion"/"verdict" évaluatif. Le verdict scientifique honnête de ce ticket porte
uniquement sur CETTE preuve OOS (voir mission AF-V-01 §16) ; `status="completed"` est purement
structurel (le run a eu lieu et produit une évidence), pas une promesse de robustesse.

**Aucun champ "untouched"/fraîcheur ici, intentionnellement (correctif AF-V-01, 2026-08-15)** :
`ValidationRun` ne revendique et ne stocke jamais qu'une période donnée était "vierge" avant
évaluation — ni ici, ni sur `HoldoutAccessEvent`/`DatasetSplitPlan`. C'est délibéré : un cas réel
(`GATE DATA`, backtest complet antérieur du même `dataset_snapshot_id` avec la même stratégie,
trades matérialisés jusque dans la fenêtre calendaire qu'un plan ultérieur désignerait
`FINAL_HOLDOUT`) a confirmé que ce module ne peut techniquement pas prouver l'absence d'exposition
antérieure — voir `docs/architecture/DOMAIN_MODEL.md` §12 ("Search History Leakage confirmé sur un
cas réel") et `validation_oos.py` pour le détail. Toute affirmation de fraîcheur d'une
`ValidationRun` (rapport, documentation, futur `Champion`) doit être établie **hors** de ce module,
en auditant l'historique réel des exécutions sur ce `dataset_snapshot_id` — jamais présumée par
défaut du seul fait que `validation_type="oos"`.

**Aucun lifecycle** : comme `ResearchRun` (`AF-R-01`), pas de state machine — l'existence du
fichier signifie "cette validation est terminée". `status` reste une constante interne
(`"completed"`), jamais un paramètre du constructeur.

Même motif que `research_run.py`/`dataset_split.py` : dataclasses `frozen`, écriture atomique,
lecture tolérante, réutilise `atomic_json_store.py` (aucune nouvelle copie de ces primitives).
`load_validation_run()` reste une fonction dédiée (pas un simple `load_tolerant()`) :
`ValidationRun` a un champ dataclass imbriqué (`OosValidationEvidence`) que la reconstruction
générique `cls(**data)` ne rehydrate pas automatiquement.

**Découplage du moteur (`/codebase-design`)** : ce module n'importe **jamais** `engine.py`/
`optimizer.py` — `build_oos_validation_evidence()` reçoit des métriques déjà calculées en
paramètres, il ne sait pas exécuter de backtest. La traduction `stats_dict` (moteur) ->
`OosValidationEvidence` est la responsabilité de `validation_oos.py` (orchestration dédiée), le
seul module autorisé à connaître à la fois le moteur et la persistance Track R/V.

**Hors scope explicite** : aucun câblage `job_store.py`/`optimizer_process.py` (voir
`validation_oos.py` pour l'orchestration manuelle, pas un mode du pipeline job existant). Aucun
`Champion`, aucune `ValidationPolicyVersion`, aucun `ValidationCampaign` construit ici.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from atomic_json_store import load_json_tolerant, save_atomic, validate_portable_identifier

VALIDATION_TYPE_OOS = "oos"


@dataclass(frozen=True)
class OosValidationEvidence:
    """Résultat observé d'une validation `"oos"` — voir docstring du module : uniquement des
    métriques factuelles, jamais un jugement subjectif. `profit_factor`/`win_rate`/`max_dd_pct`
    restent `None` quand `n_trades == 0` (`engine.py::_compute_stats()` ne les calcule pas dans ce
    cas) — jamais une valeur inventée à la place."""

    period_start: str
    period_end: str
    n_trades: int
    net_ret_pct: float
    profit_factor: Optional[float]
    win_rate: Optional[float]
    max_dd_pct: Optional[float]


@dataclass(frozen=True)
class ValidationRun:
    """Enregistrement immuable d'une validation `"oos"` précise — voir docstring du module pour
    le modèle de relations retenu (`research_run_id`/`split_plan_id`/`dataset_snapshot_id`
    directs, jamais par jointure implicite)."""

    validation_run_id: str
    research_run_id: str
    split_plan_id: str
    dataset_snapshot_id: str
    validation_type: str
    strategy_name: str
    strategy_params: dict
    evidence: OosValidationEvidence
    status: str
    completed_at: str


def _parse_offset_aware(value: str, field_name: str) -> datetime:
    """Dupliqué intentionnellement de `dataset_split.py` (2ᵉ occurrence seulement — Rule of Three
    pas encore atteinte, pas d'extraction prématurée vers `atomic_json_store.py`)."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} doit être un timestamp ISO-8601 valide : {value!r}")
    if parsed.tzinfo is None:
        raise ValueError(
            f"{field_name} doit être offset-aware (UTC explicite, ex. '...+00:00') : {value!r}"
        )
    return parsed


def build_oos_validation_evidence(
    period_start: str,
    period_end: str,
    n_trades: int,
    net_ret_pct: float,
    profit_factor: Optional[float] = None,
    win_rate: Optional[float] = None,
    max_dd_pct: Optional[float] = None,
) -> OosValidationEvidence:
    """Construit une `OosValidationEvidence`. `period_start`/`period_end` : ISO-8601 offset-aware,
    `period_start` doit strictement précéder `period_end` (même discipline que `SplitBoundary`)."""
    start_dt = _parse_offset_aware(period_start, "period_start")
    end_dt = _parse_offset_aware(period_end, "period_end")
    if not start_dt < end_dt:
        raise ValueError(
            f"period_start ({period_start!r}) doit strictement précéder period_end "
            f"({period_end!r})."
        )
    return OosValidationEvidence(
        period_start=period_start,
        period_end=period_end,
        n_trades=n_trades,
        net_ret_pct=net_ret_pct,
        profit_factor=profit_factor,
        win_rate=win_rate,
        max_dd_pct=max_dd_pct,
    )


def build_validation_run(
    validation_run_id: str,
    research_run_id: str,
    split_plan_id: str,
    dataset_snapshot_id: str,
    strategy_name: str,
    strategy_params: dict,
    evidence: OosValidationEvidence,
    validation_type: str = VALIDATION_TYPE_OOS,
    completed_at: Optional[str] = None,
) -> ValidationRun:
    """Construit une `ValidationRun`. Lève `ValueError` si `validation_run_id`/`research_run_id`/
    `split_plan_id` sont invalides (voir `validate_portable_identifier()`), si
    `dataset_snapshot_id` est absent/vide, ou si `validation_type` n'est pas `"oos"` (seul type
    supporté par ce ticket — voir docstring du module)."""
    if validation_type != VALIDATION_TYPE_OOS:
        raise ValueError(
            f"validation_type={validation_type!r} non supporté par ce ticket — seul "
            f"{VALIDATION_TYPE_OOS!r} est implémenté (AF-V-06 traitera la généralisation future)."
        )
    if not isinstance(dataset_snapshot_id, str) or not dataset_snapshot_id.strip():
        raise ValueError(
            "dataset_snapshot_id est obligatoire pour une ValidationRun — référence directe "
            "exigée (même principe que HoldoutAccessEvent, DOMAIN_MODEL.md §12)."
        )

    return ValidationRun(
        validation_run_id=validate_portable_identifier(validation_run_id, "validation_run_id"),
        research_run_id=validate_portable_identifier(research_run_id, "research_run_id"),
        split_plan_id=validate_portable_identifier(split_plan_id, "split_plan_id"),
        dataset_snapshot_id=dataset_snapshot_id,
        validation_type=validation_type,
        strategy_name=strategy_name,
        strategy_params=dict(strategy_params),
        evidence=evidence,
        status="completed",
        completed_at=completed_at or datetime.now(timezone.utc).isoformat(),
    )


def save_validation_run(path: Union[str, Path], run: ValidationRun) -> Path:
    """Écriture atomique de la `ValidationRun`. Lève `FileExistsError` si déjà écrite (immuable —
    un seul enregistrement par `validation_run_id`)."""
    return save_atomic(path, asdict(run), "validation_run")


def load_validation_run(path: Union[str, Path]) -> Optional[ValidationRun]:
    """Lecture tolérante avec rehydratation de l'`OosValidationEvidence` imbriquée (voir docstring
    du module — `cls(**data)` générique ne suffit pas pour un champ dataclass imbriqué)."""
    data = load_json_tolerant(path)
    if data is None:
        return None
    try:
        return ValidationRun(
            validation_run_id=data["validation_run_id"],
            research_run_id=data["research_run_id"],
            split_plan_id=data["split_plan_id"],
            dataset_snapshot_id=data["dataset_snapshot_id"],
            validation_type=data["validation_type"],
            strategy_name=data["strategy_name"],
            strategy_params=data["strategy_params"],
            evidence=OosValidationEvidence(**data["evidence"]),
            status=data["status"],
            completed_at=data["completed_at"],
        )
    except (TypeError, KeyError):
        return None
