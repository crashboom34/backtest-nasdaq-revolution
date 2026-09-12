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

**AF-V-06 (2026-09-12) — socle `ValidationSpecification`/`ValidationEvidence` typé par
`validation_type`** : `DOMAIN_MODEL.md` (lignes 453-454) exige que chaque `ValidationRun` porte
une `ValidationSpecification` **et** une `ValidationEvidence` typées selon son `validation_type` —
jamais un couple `dict`/`dict` générique opaque. Ce ticket introduit ce contrat, avec `"oos"`
(déjà réel depuis AF-V-01) comme premier cas concret, **sans** inventer les variantes futures
(Walk-Forward/Monte-Carlo/Parameter Stability/Stress restent au ticket qui les consommera).

- **Registre explicite, pas un ABC/Protocol** : `_VALIDATION_TYPES` associe chaque
  `validation_type` enregistré à sa paire `(classe specification, classe evidence)`. Un seul type
  concret existe aujourd'hui (`"oos"`) — une hiérarchie abstraite pour un seul cas serait de la
  sur-ingénierie (même principe déjà retenu pour `ExecutionModel`, `DOMAIN_MODEL.md` §10 : "un
  seul adapter = seam hypothétique"). Ce registre EST le contrat commun explicite : il sert à la
  fois à valider la cohérence à la construction (`build_validation_run()`) et à la désérialisation
  (`load_validation_run()`).
- **`ValidationSpecification`/`ValidationEvidence`** : alias `Union` ("tagged union" — option
  explicitement acceptée par la mission AF-V-06), extensibles en ajoutant un membre par futur
  ticket, sans jamais toucher `ValidationRun` elle-même.
- **`OosValidationSpecification` (nouveau)** : décrit la fenêtre `FINAL_HOLDOUT` **demandée/prévue**
  — `holdout_start`/`holdout_end`, fixés AVANT l'appel au moteur. `OosValidationEvidence` porte les
  métriques **effectivement retournées par l'exécution**, et les bornes de période associées à
  cette évidence. **Précision honnête (durcissement 2026-09-12)** : dans l'orchestration OOS
  actuelle (`validation_oos.py`), `evidence.period_start`/`period_end` reprennent aujourd'hui les
  **mêmes** bornes demandées que `specification.holdout_start`/`holdout_end` (les deux sont
  dérivées du même `split_plan.final_holdout`, au même site d'appel) — elles ne sont **pas**
  recalculées à partir des timestamps réellement présents dans les trades/l'equity retournés par le
  moteur. Les deux champs restent néanmoins séparés, jamais fusionnés : la distinction devient
  significative dès qu'un futur type de validation dériverait `evidence` d'une couverture réelle
  effectivement observée (ex. données partielles, gap), sans que ce socle ait besoin d'être modifié
  pour ça. Duplication délibérée des bornes déjà présentes sur le `DatasetSplitPlan` référencé (via
  `split_plan_id`) — même principe déjà établi pour `HoldoutAccessEvent` (référence directe plutôt
  que jointure implicite, `DOMAIN_MODEL.md` §12) : une `ValidationRun` reste interprétable seule,
  même si le fichier `DatasetSplitPlan` d'origine devient inaccessible. **`OosValidationEvidence`
  reste strictement inchangée** (ses 7 champs, `period_start`/`period_end` compris) — les modifier
  casserait la relecture des artefacts réels déjà produits par AF-V-01
  (`results/validations/*/validation_run.json`, jamais lus ni modifiés par ce ticket). **Aucun
  contrôle croisé** `specification.holdout_start == evidence.period_start` n'est imposé au niveau
  du socle commun (délibéré, pas un oubli) : pour `"oos"` ce serait tautologique (mêmes valeurs,
  même site d'appel) ; l'imposer maintenant risquerait d'être une contrainte fausse pour un futur
  type (Walk-Forward) où une évidence pourrait légitimement refléter une couverture réelle
  partielle — à décider avec un cas d'usage réel, pas ici par anticipation.
- **Rétrocompatibilité AF-V-01 (option A retenue, la plus honnête — durcie le 2026-09-12)** :
  `ValidationRun.specification` est `Optional[ValidationSpecification]`. `build_validation_run()`
  (construction d'un NOUVEAU run) l'exige et la valide par `isinstance` contre le registre — aucun
  `None` accepté pour un run construit aujourd'hui. `load_validation_run()` (lecture) tolère en
  revanche son absence **complète** dans un JSON historique — confirmé sur les deux artefacts réels
  d'AF-V-01, qui n'ont **jamais** eu de clé `"specification"` — et restitue alors
  `specification=None`, **jamais reconstruite ou devinée** à partir de l'evidence. **Distinction
  stricte, non accidentelle (durcissement 2026-09-12, trouvaille de revue adversariale)** : `None`
  n'est une représentation honnête QUE d'une clé `"specification"` **totalement absente** du JSON —
  jamais d'une clé présente avec la valeur `null` explicite, qui est désormais traitée comme un
  format incohérent (`IncoherentValidationRunError`), jamais silencieusement assimilée au legacy
  réel. Symétriquement, `save_validation_run()` refuse d'écrire un `ValidationRun` dont
  `specification is None` — `specification=None` est une représentation **exclusivement de
  lecture** d'un ancien enregistrement, jamais un format valide pour créer/re-persister un
  artefact ; cela empêche notamment qu'un enchaînement `load_validation_run()` (legacy) ->
  `save_validation_run()` (nouveau chemin) ne produise silencieusement un fichier "moderne" avec
  `"specification": null`, indiscernable d'un vrai historique à la relecture. Ni B (reconstruction
  en mémoire) ni C (représentation legacy dédiée) n'ont été retenues pour la lecture : rien ne
  prouve qu'une intention de specification ait réellement été formée le 2026-08-23, l'inventer
  serait un faux historique.
- **Cohérence stricte, échec tôt et clair (pas de résolution silencieuse)** : `build_validation_run()`
  rejette (`ValueError`) tout `validation_type` non enregistré, ou toute `specification`/`evidence`
  dont le type Python ne correspond pas à celui attendu par le registre — y compris un
  intervertissement `specification`/`evidence`. `load_validation_run()` distingue explicitement
  **trois** catégories, jamais confondues : (1) fichier absent/illisible/JSON invalide, ou forme de
  base incomplète -> `None` (tolérance historique inchangée, comme `dataset_split.py`/
  `research_run.py`) ; (2) clé `"specification"` totalement absente -> legacy honnête,
  `specification=None` ; (3) JSON structurellement incohérent (`validation_type` inconnu,
  `specification`/`evidence` dont les champs ne correspondent pas au type attendu, **ou clé
  `"specification"` présente avec la valeur `null` explicite**) -> lève
  `IncoherentValidationRunError`, jamais un simple `None` qui masquerait silencieusement une donnée
  corrompue ou un format nouveau mal formé.
- **Construction directe de la dataclass (revue adversariale, dette assumée)** : `ValidationRun`
  n'a pas de `__post_init__` — comme `ResearchRun`/`DatasetSplitPlan`/`SplitBoundary`/
  `HoldoutAccessEvent` partout ailleurs dans ce dépôt, toute la validation vit dans les fonctions
  `build_*()`, jamais au niveau de la dataclass elle-même. `build_validation_run()` reste donc le
  **seul chemin sanctionné** pour créer un nouveau run cohérent ; rien n'empêche techniquement une
  construction directe de `ValidationRun(...)` avec une combinaison incohérente, exactement comme
  pour les autres dataclasses de ce dépôt — dette acceptée, pas un `__post_init__` ajouté par
  principe pour ce seul module. `specification=None` construit directement (hors builder) resterait
  également bloqué à l'écriture par `save_validation_run()` (voir ci-dessus), qui ne fait pas
  confiance à la provenance de l'objet reçu.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

from atomic_json_store import load_json_tolerant, save_atomic, validate_portable_identifier

VALIDATION_TYPE_OOS = "oos"

_SPECIFICATION_KEY_ABSENT = object()
"""Sentinelle interne (durcissement 2026-09-12) — distingue explicitement une clé `"specification"`
totalement absente d'un JSON (legacy honnête, voir `load_validation_run()`) d'une clé présente
portant la valeur `null` (incohérent, jamais confondu avec le premier cas). `dict.get(key, default)`
avec `None` comme défaut ne permettrait pas cette distinction, puisque `None` est aussi la valeur
JSON réelle de `null` une fois désérialisé."""


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
class OosValidationSpecification:
    """Décrit la fenêtre `FINAL_HOLDOUT` demandée/prévue pour une validation `"oos"` (AF-V-06),
    fixée AVANT l'appel au moteur. Contrepartie de `OosValidationEvidence` (qui porte les métriques
    effectivement retournées par l'exécution, et les bornes de période associées à cette évidence)
    — voir docstring du module pour la justification complète de la distinction, de la non-fusion,
    et la précision honnête sur ce que "observé" signifie réellement aujourd'hui pour `"oos"`."""

    holdout_start: str
    holdout_end: str


ValidationSpecification = Union[OosValidationSpecification]
"""Contrat commun explicite (tagged union, AF-V-06) — étendre en ajoutant un membre par futur
`validation_type`, jamais en élargissant `OosValidationSpecification` elle-même."""

ValidationEvidence = Union[OosValidationEvidence]
"""Contrat commun explicite (tagged union, AF-V-06) — même principe que `ValidationSpecification`."""


@dataclass(frozen=True)
class ValidationRun:
    """Enregistrement immuable d'une validation précise — voir docstring du module pour le modèle
    de relations retenu (`research_run_id`/`split_plan_id`/`dataset_snapshot_id` directs, jamais
    par jointure implicite) et pour le contrat `ValidationSpecification`/`ValidationEvidence`
    typé par `validation_type` (AF-V-06).

    `specification` est `Optional` **uniquement** pour représenter honnêtement un ancien
    enregistrement AF-V-01 relu (jamais de `None` pour un run construit aujourd'hui via
    `build_validation_run()`, qui l'exige et la valide)."""

    validation_run_id: str
    research_run_id: str
    split_plan_id: str
    dataset_snapshot_id: str
    validation_type: str
    strategy_name: str
    strategy_params: dict
    specification: Optional[ValidationSpecification]
    evidence: ValidationEvidence
    status: str
    completed_at: str


_VALIDATION_TYPES: Dict[str, Tuple[type, type]] = {
    VALIDATION_TYPE_OOS: (OosValidationSpecification, OosValidationEvidence),
}
"""Registre explicite `validation_type -> (classe specification, classe evidence)` — voir
docstring du module (AF-V-06). Étendre en ajoutant une entrée par futur ticket
(Walk-Forward/Monte-Carlo/Parameter Stability/Stress), jamais en généralisant ce module en `dict`
opaque."""


class IncoherentValidationRunError(ValueError):
    """Levée quand un `ValidationRun` persisté associe un `validation_type` à une
    `specification`/`evidence` structurellement incohérente (type non enregistré, ou champs ne
    correspondant pas à la classe attendue) — jamais résolu silencieusement en `None`. Distincte du
    cas fichier absent/illisible/JSON invalide, qui reste tolérant (voir docstring du module)."""


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


def build_oos_validation_specification(
    holdout_start: str,
    holdout_end: str,
) -> OosValidationSpecification:
    """Construit une `OosValidationSpecification` (AF-V-06) : la fenêtre `FINAL_HOLDOUT` qui
    devait être évaluée (l'intention), par opposition à `OosValidationEvidence.period_start`/
    `period_end` (ce qui a réellement été observé) — voir docstring du module pour la distinction.
    `holdout_start`/`holdout_end` : ISO-8601 offset-aware, `holdout_start` doit strictement
    précéder `holdout_end` (même discipline que `SplitBoundary`/`OosValidationEvidence`)."""
    start_dt = _parse_offset_aware(holdout_start, "holdout_start")
    end_dt = _parse_offset_aware(holdout_end, "holdout_end")
    if not start_dt < end_dt:
        raise ValueError(
            f"holdout_start ({holdout_start!r}) doit strictement précéder holdout_end "
            f"({holdout_end!r})."
        )
    return OosValidationSpecification(holdout_start=holdout_start, holdout_end=holdout_end)


def build_validation_run(
    validation_run_id: str,
    research_run_id: str,
    split_plan_id: str,
    dataset_snapshot_id: str,
    strategy_name: str,
    strategy_params: dict,
    specification: ValidationSpecification,
    evidence: ValidationEvidence,
    validation_type: str = VALIDATION_TYPE_OOS,
    completed_at: Optional[str] = None,
) -> ValidationRun:
    """Construit une `ValidationRun`. Lève `ValueError` si `validation_run_id`/`research_run_id`/
    `split_plan_id` sont invalides (voir `validate_portable_identifier()`), si
    `dataset_snapshot_id` est absent/vide, si `validation_type` n'est pas enregistré (voir
    `_VALIDATION_TYPES`, AF-V-06), ou si `specification`/`evidence` ne sont pas du type Python
    attendu pour ce `validation_type` (échec tôt et clair — jamais une combinaison incohérente
    acceptée silencieusement, voir docstring du module)."""
    binding = _VALIDATION_TYPES.get(validation_type)
    if binding is None:
        raise ValueError(
            f"validation_type={validation_type!r} non supporté — types enregistrés : "
            f"{sorted(_VALIDATION_TYPES)} (AF-V-06 pose le socle typé ; les futures variantes "
            "Walk-Forward/Monte-Carlo/Parameter Stability/Stress seront ajoutées par leur propre "
            "ticket, jamais présumées ici)."
        )
    specification_cls, evidence_cls = binding
    if not isinstance(specification, specification_cls):
        raise ValueError(
            f"specification incohérente avec validation_type={validation_type!r} : attendu "
            f"{specification_cls.__name__}, reçu {type(specification).__name__}."
        )
    if not isinstance(evidence, evidence_cls):
        raise ValueError(
            f"evidence incohérente avec validation_type={validation_type!r} : attendu "
            f"{evidence_cls.__name__}, reçu {type(evidence).__name__}."
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
        specification=specification,
        evidence=evidence,
        status="completed",
        completed_at=completed_at or datetime.now(timezone.utc).isoformat(),
    )


def save_validation_run(path: Union[str, Path], run: ValidationRun) -> Path:
    """Écriture atomique de la `ValidationRun`. Lève `FileExistsError` si déjà écrite (immuable —
    un seul enregistrement par `validation_run_id`).

    Lève `ValueError` si `run.specification is None` (durcissement 2026-09-12) : cette
    représentation n'est honnête qu'en LECTURE d'un ancien enregistrement AF-V-01
    (`load_validation_run()`), jamais un format valide à l'écriture — sans ce refus, un
    enchaînement `load_validation_run()` (legacy) -> `save_validation_run()` (nouveau chemin)
    produirait silencieusement un fichier "moderne" avec `"specification": null`, indiscernable
    d'un vrai historique à la relecture (voir docstring du module). Échoue **avant** toute écriture
    disque — le chemin cible n'est jamais créé."""
    if run.specification is None:
        raise ValueError(
            "save_validation_run() refuse d'écrire une ValidationRun dont specification is "
            "None — cette représentation est réservée à la lecture rétrocompatible d'un ancien "
            "enregistrement AF-V-01 (voir load_validation_run()), jamais un format valide pour "
            "créer ou re-persister un artefact. Utilise build_validation_run() avec une "
            "specification réelle pour tout nouveau run."
        )
    return save_atomic(path, asdict(run), "validation_run")


def load_validation_run(path: Union[str, Path]) -> Optional[ValidationRun]:
    """Lecture tolérante avec rehydratation de la `specification`/`evidence` imbriquées (voir
    docstring du module — `cls(**data)` générique ne suffit pas pour des champs dataclass
    imbriqués). Trois catégories distinctes (AF-V-06, durcies le 2026-09-12), jamais confondues :

    - fichier absent/illisible/JSON invalide, ou forme de base incomplète (clés obligatoires
      manquantes) -> `None`, jamais d'exception — tolérance historique inchangée depuis AF-V-01 ;
    - clé `"specification"` **totalement absente** du JSON -> legacy honnête, `specification=None`
      (la forme réelle de tout enregistrement AF-V-01 antérieur à AF-V-06 — jamais reconstruite ou
      devinée à partir de l'evidence) ;
    - JSON structurellement incohérent (`validation_type` non enregistré, `specification`/
      `evidence` dont les champs ne correspondent pas au type attendu, **ou clé `"specification"`
      présente avec la valeur `null` explicite** — distinct d'une absence totale, voir
      `_SPECIFICATION_KEY_ABSENT`) -> lève `IncoherentValidationRunError`, jamais un `None` qui
      masquerait silencieusement une donnée corrompue ou un nouveau format mal formé."""
    data = load_json_tolerant(path)
    if data is None:
        return None
    try:
        validation_run_id = data["validation_run_id"]
        research_run_id = data["research_run_id"]
        split_plan_id = data["split_plan_id"]
        dataset_snapshot_id = data["dataset_snapshot_id"]
        validation_type = data["validation_type"]
        strategy_name = data["strategy_name"]
        strategy_params = data["strategy_params"]
        raw_specification = data.get("specification", _SPECIFICATION_KEY_ABSENT)
        raw_evidence = data["evidence"]
        status = data["status"]
        completed_at = data["completed_at"]
    except (TypeError, KeyError):
        return None  # forme de base incomplète/corrompue -> tolérant, comme avant AF-V-06

    binding = _VALIDATION_TYPES.get(validation_type)
    if binding is None:
        raise IncoherentValidationRunError(
            f"validation_type={validation_type!r} non reconnu dans {path} — types enregistrés : "
            f"{sorted(_VALIDATION_TYPES)}. Fichier potentiellement produit par une version future "
            "non supportée par ce socle, ou corrompu : à examiner manuellement, jamais ignoré "
            "silencieusement."
        )
    specification_cls, evidence_cls = binding

    try:
        evidence = evidence_cls(**raw_evidence)
    except TypeError as exc:
        raise IncoherentValidationRunError(
            f"evidence de {path} incohérente avec validation_type={validation_type!r} (attendu "
            f"{evidence_cls.__name__}) : {exc}"
        ) from exc

    if raw_specification is _SPECIFICATION_KEY_ABSENT:
        # Clé totalement absente du JSON : forme réelle de tout enregistrement AF-V-01 antérieur
        # à AF-V-06 — seul cas où `None` est une représentation honnête (legacy réel).
        specification = None
    elif raw_specification is None:
        # Clé PRÉSENTE avec la valeur `null` explicite : jamais confondu avec une absence totale
        # (voir _SPECIFICATION_KEY_ABSENT et docstring du module, durcissement 2026-09-12) — un
        # nouveau format ne peut pas prétendre au statut legacy en persistant `null` explicitement.
        raise IncoherentValidationRunError(
            f"specification=null explicite dans {path} pour validation_type={validation_type!r} "
            "— incohérent : `None` n'est une représentation honnête que d'une clé "
            "\"specification\" totalement ABSENTE (legacy AF-V-01 réel), jamais d'une clé "
            "présente avec la valeur null. Si ce fichier est authentiquement un ancien "
            "enregistrement AF-V-01, retirer la clé plutôt que de la mettre à null ; sinon, "
            "construire une specification réelle via build_oos_validation_specification()."
        )
    else:
        try:
            specification = specification_cls(**raw_specification)
        except TypeError as exc:
            raise IncoherentValidationRunError(
                f"specification de {path} incohérente avec validation_type={validation_type!r} "
                f"(attendu {specification_cls.__name__}) : {exc}"
            ) from exc

    return ValidationRun(
        validation_run_id=validation_run_id,
        research_run_id=research_run_id,
        split_plan_id=split_plan_id,
        dataset_snapshot_id=dataset_snapshot_id,
        validation_type=validation_type,
        strategy_name=strategy_name,
        strategy_params=strategy_params,
        specification=specification,
        evidence=evidence,
        status=status,
        completed_at=completed_at,
    )
