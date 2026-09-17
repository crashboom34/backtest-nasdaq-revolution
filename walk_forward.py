"""
walk_forward.py — Walk-Forward V1 : géométrie Rolling déterministe, guards scientifiques (AF-V-02).

Track V (Scientific Validation), Slice 1 — DatasetSplitPlan VALIDATION + cœur déterministe
Walk-Forward, conformément à `docs/adr/0021-walk-forward-rolling-calendar-v1.md`
(`WALK_FORWARD_SEMANTICS_VERSION = "rolling-calendar-v2"`, corrigée AVANT toute implémentation le
2026-09-15 — voir Décisions 1/3/4/6/9/10 pour la règle terminale actuelle, notamment le fait que la
borne de FIN du dernier fold n'est jamais résolue par readiness).

**Slice 1 scope, strict** : géométrie pure, résolution readiness, guards structurels. AUCUN
Optimizer TRAIN-only, AUCUN Top-1 réel, AUCUNE exécution TEST OOS, AUCUNE persistence complète —
voir ADR 0021 Décisions 6/12 pour ce qui reste hors scope de ce module pour l'instant (le futur
seam `Optimizer.run(..., run_test_validation=False)` n'est PAS câblé ici).

**Découplage (`/codebase-design`)** : ce module importe `FoldDefinition`/`WalkForwardSpecification`/
`WalkForwardEvidence` DEPUIS `validation_run.py` (jamais l'inverse — `validation_run.py` reste un
leaf module générique, voir sa propre docstring, ADR 0021 Décision 2) ; `resolve_state_ready_
boundary`/`DailyStateReadiness` depuis `strategy_contracts.py` (réutilisés tels quels, mirroring
exact du précédent déjà établi dans `optimizer.py` pour State/Session Readiness) ; `SplitBoundary`
depuis `dataset_split.py` (les zones VALIDATION/FINAL_HOLDOUT d'un `DatasetSplitPlan`, jamais
dupliquées) ; `NoStateReadyBoundary` depuis `optimizer.py` (réutilisée comme TYPE — ADR 0021
Décision 11 — les messages sont reconstruits ici avec un contexte fold explicite, jamais le message
générique verbatim).
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

import pandas as pd

from dataset_split import SplitBoundary
from optimizer import NoStateReadyBoundary
from strategy_contracts import DailyStateReadiness, resolve_state_ready_boundary
from validation_run import FoldDefinition, WalkForwardSpecification

# Identifie la sémantique du protocole Walk-Forward — géométrie, inclusivité des frontières, règle
# terminale. Indépendante de TRAIN_TEST_SEMANTICS_VERSION ("exact-boundary-v2")/
# STATE_READINESS_SEMANTICS_VERSION ("daily-state-ready-v1"), toutes deux dans optimizer.py :
# trois contrats scientifiques distincts, jamais fusionnés (ADR 0021 Décision 9).
# "v2" — corrigée le 2026-09-15 AVANT toute implémentation/tout run réel (ADR 0021 Décision 9,
# mirroring TRAIN_TEST_SEMANTICS_VERSION="exact-boundary-v2") : v1 résolvait à tort la borne
# terminale du dernier fold par readiness et la déclarait inclusive ; v2 ne fait ni l'un ni l'autre.
WALK_FORWARD_SEMANTICS_VERSION = "rolling-calendar-v2"

_SUPPORTED_GEOMETRY = "rolling"


class UnsupportedWalkForwardGeometry(ValueError):
    """Levée si `WalkForwardSpecification.geometry != "rolling"` — V1 ne supporte que Rolling,
    jamais une conversion silencieuse vers/depuis Anchored ou Hybride (ADR 0021 Décision 1)."""


class DatasetTooShortForWalkForward(ValueError):
    """Levée si la zone VALIDATION ne permet de générer aucun fold complet (dataset/zone trop
    courts pour la géométrie déclarée). Absorbe le cas "aucun fold valide" — même remède : élargir
    VALIDATION ou réduire la géométrie (ADR 0021 Décision 11, taxonomie consolidée)."""


class InsufficientWarmupHistory(ValueError):
    """Levée si l'historique causal disponible avant le `train_start` du premier fold est plus
    court que le warmup maximal requis par le search space — seul le fold 0 peut être concerné,
    tout fold suivant dispose strictement de plus d'historique par construction (ADR 0021
    Décision 5)."""


class FinalHoldoutOverlapError(ValueError):
    """Levée si la zone VALIDATION chevauche FINAL_HOLDOUT du même `DatasetSplitPlan` — garde
    défensive, PAS le mécanisme principal garantissant l'absence de fuite (celui-ci est structurel,
    voir `compute_fold_definitions()`) : `build_dataset_split_plan()` refuse déjà ce chevauchement
    pour un plan bien formé, ce garde protège contre un plan construit hors du chemin normal (ADR
    0021 Décision 10)."""


class WalkForwardSemanticsMismatch(ValueError):
    """Levée quand un job repris a été créé sous une `WALK_FORWARD_SEMANTICS_VERSION` différente
    de la courante (absente = legacy) — mirroring exact de
    `optimizer.TrainTestSemanticsMismatch`/`StateReadinessSemanticsMismatch` (ADR 0021 Décision
    9). Jamais un mélange silencieux de frontières résolues sous deux contrats différents."""


class OosOverlapError(ValueError):
    """Garde défensive interne (ADR 0021 Décision 11) — devrait être mathématiquement impossible à
    déclencher si `compute_fold_definitions()` est correcte (non-chevauchement dérivé par
    déterminisme, Décision 4) : un filet de sécurité testé, jamais une erreur utilisateur
    réaliste."""


_PERIOD_RE = re.compile(r"^P(\d+)M$")


def _period_to_months(period, field_name: str) -> int:
    """Parse un format `"PnM"` (mois calendaires uniquement — V1 ne supporte pas d'autre
    granularité ISO-8601 ; aucune bibliothèque de calendrier générique dupliquée, voir docstring du
    module)."""
    match = _PERIOD_RE.fullmatch(period) if isinstance(period, str) else None
    if not match:
        raise ValueError(
            f"{field_name} doit être au format 'PnM' (mois calendaires) — reçu {period!r}. Seule "
            "la granularité mensuelle est supportée en V1."
        )
    months = int(match.group(1))
    if months <= 0:
        raise ValueError(f"{field_name} doit être strictement positif : {period!r}")
    return months


def _add_months(ts: pd.Timestamp, months: int) -> pd.Timestamp:
    return ts + pd.DateOffset(months=months)


def _intervals_overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def build_walk_forward_specification(
    base_params: dict,
    geometry: str = "rolling",
    train_period: str = "P24M",
    test_period: str = "P6M",
    step_period: str = "P6M",
    allow_partial_last_fold: bool = False,
    position_transition_policy: str = "flat_each_fold_v1",
    verdict_policy_id: Optional[str] = None,
    master_seed: Optional[int] = None,
) -> WalkForwardSpecification:
    """Construit une `WalkForwardSpecification` V1.

    Lève `UnsupportedWalkForwardGeometry` si `geometry != "rolling"` (jamais une conversion
    silencieuse vers Anchored/Hybride, qui restent FUTURE, non implémentées). Lève `ValueError` si
    `step_period != test_period` (seule condition garantissant des fenêtres TEST contiguës et non
    chevauchantes par construction, ADR 0021 Décision 1/4), si `allow_partial_last_fold` est
    `True` (fixé à `False`, non paramétrable en V1, Décision 1), ou si `base_params` est absent/
    vide (fige LE SEUL jeu de paramètres utilisé pour la résolution readiness de TOUS les folds,
    Décision 4 — jamais les `selected_params` variables par fold d'une future recherche TRAIN)."""
    if geometry != _SUPPORTED_GEOMETRY:
        raise UnsupportedWalkForwardGeometry(
            f"geometry={geometry!r} non supportée en V1 — seule 'rolling' est implémentée "
            "(Anchored/Hybride restent FUTURE, jamais une conversion silencieuse)."
        )
    if not isinstance(base_params, dict) or not base_params:
        raise ValueError(
            "base_params est obligatoire et non vide — c'est le seul jeu de paramètres utilisé "
            "pour la résolution readiness de TOUS les folds (ADR 0021 Décision 4)."
        )
    if allow_partial_last_fold is not False:
        raise ValueError(
            "allow_partial_last_fold doit être False — fixé, non paramétrable en V1 (ADR 0021 "
            "Décision 1)."
        )
    _period_to_months(train_period, "train_period")
    test_months = _period_to_months(test_period, "test_period")
    step_months = _period_to_months(step_period, "step_period")
    if step_months != test_months:
        raise ValueError(
            f"step_period ({step_period!r}) doit être égal à test_period ({test_period!r}) — "
            "seule condition garantissant des fenêtres TEST contiguës et non chevauchantes par "
            "construction (ADR 0021 Décision 1/4)."
        )
    return WalkForwardSpecification(
        geometry=geometry,
        train_period=train_period,
        test_period=test_period,
        step_period=step_period,
        allow_partial_last_fold=allow_partial_last_fold,
        position_transition_policy=position_transition_policy,
        walk_forward_semantics_version=WALK_FORWARD_SEMANTICS_VERSION,
        base_params=dict(base_params),
        verdict_policy_id=verdict_policy_id,
        master_seed=master_seed,
    )


def check_no_final_holdout_overlap(
    validation_zone: SplitBoundary, final_holdout_zone: SplitBoundary,
) -> None:
    """Garde défensive (ADR 0021 Décision 10) — N'EST PAS le mécanisme principal garantissant
    l'absence de fuite : `compute_fold_definitions()` borne déjà structurellement chaque fold à
    `VALIDATION.end` (condition de génération), et la règle terminale V2 empêche tout décalage de
    `effective_test_end` au-delà. Ce garde protège contre un `DatasetSplitPlan` construit hors du
    chemin normal (`build_dataset_split_plan()` refuse déjà ce chevauchement pour un plan bien
    formé)."""
    v_start, v_end = pd.Timestamp(validation_zone.start), pd.Timestamp(validation_zone.end)
    h_start, h_end = pd.Timestamp(final_holdout_zone.start), pd.Timestamp(final_holdout_zone.end)
    if _intervals_overlap(v_start, v_end, h_start, h_end):
        raise FinalHoldoutOverlapError(
            f"VALIDATION [{validation_zone.start}, {validation_zone.end}) chevauche FINAL_HOLDOUT "
            f"[{final_holdout_zone.start}, {final_holdout_zone.end}) — un Walk-Forward ne doit "
            "jamais pouvoir accéder à FINAL_HOLDOUT."
        )


def check_no_oos_overlap(folds: Tuple[FoldDefinition, ...]) -> None:
    """Garde défensive interne (ADR 0021 Décision 11) — devrait être mathématiquement impossible à
    déclencher si `compute_fold_definitions()` est correcte (non-chevauchement dérivé par
    déterminisme, Décision 4)."""
    for a, b in zip(folds, folds[1:]):
        if pd.Timestamp(a.effective_test_end) > pd.Timestamp(b.effective_boundary):
            raise OosOverlapError(
                f"{a.fold_id}.effective_test_end ({a.effective_test_end}) dépasse "
                f"{b.fold_id}.effective_boundary ({b.effective_boundary}) — chevauchement OOS, ne "
                "devrait jamais se produire avec une géométrie correctement construite."
            )


def check_warmup_sufficiency(
    bars_available_before_first_fold: int, required_warmup_bars: int,
) -> None:
    """Garde-fou propre à Walk-Forward (ADR 0021 Décision 5) : seul le fold 0 peut être concerné
    (tout fold suivant dispose strictement de plus d'historique par construction). Volontairement
    exprimée en BARRES (pas en durée calendaire) : traduire un nombre de barres requis en durée
    calendaire dépendrait de la densité réelle des données (week-ends, jours fériés, timeframe) —
    hors scope de cette fonction pure. L'appelant (future orchestration, hors Slice 1) est
    responsable de compter les barres réellement disponibles avant `train_start` du fold 0."""
    if bars_available_before_first_fold < required_warmup_bars:
        raise InsufficientWarmupHistory(
            f"Historique disponible avant le premier fold ({bars_available_before_first_fold} "
            f"barres) insuffisant pour le warmup maximal requis par le search space "
            f"({required_warmup_bars} barres) — un fold 0 sous-alimenté ne serait pas comparable "
            "aux folds suivants (ADR 0021 Décision 5)."
        )


def validate_resume_walk_forward_semantics(
    current_is_walk_forward: bool, source_config: Optional[dict], source_run_id: str,
) -> None:
    """Garde de reprise cross-version (ADR 0021 Décision 9) — mirroring exact de
    `optimizer.validate_resume_train_test_semantics()`/`validate_resume_state_readiness_semantics()`.
    Ne s'applique QUE si le run courant est un Walk-Forward — jamais bloquante sinon, quelle que
    soit la source."""
    if not current_is_walk_forward:
        return
    source_version = (source_config or {}).get("walk_forward_semantics_version")
    if source_version != WALK_FORWARD_SEMANTICS_VERSION:
        raise WalkForwardSemanticsMismatch(
            f"Reprise refusée : le job source {source_run_id!r} utilise la sémantique "
            f"Walk-Forward {source_version!r} (legacy si absente), incompatible avec la version "
            f"courante {WALK_FORWARD_SEMANTICS_VERSION!r}. Mélanger, au sein d'un même run repris, "
            "des frontières résolues sous deux contrats Walk-Forward différents produirait des "
            "métriques scientifiquement incohérentes. Relancer un nouveau run sans "
            "resume_run_id plutôt que de reprendre ce job source."
        )


def detect_partial_tail(
    validation_zone: SplitBoundary, spec: WalkForwardSpecification, n_folds_generated: int,
) -> Optional[SplitBoundary]:
    """Fonction PURE (ADR 0021 Décision 1) : calcule le segment résiduel de `VALIDATION` après
    les `n_folds_generated` folds réellement générés, s'il en reste un — jamais exécuté ni compté
    comme fold, mais détectable/enregistrable pour audit (`allow_partial_last_fold=False` fixé en
    V1). Retourne `None` si les folds couvrent exactement `VALIDATION` jusqu'à son terme (aucune
    queue)."""
    train_months = _period_to_months(spec.train_period, "train_period")
    step_months = _period_to_months(spec.step_period, "step_period")
    validation_start = pd.Timestamp(validation_zone.start)
    validation_end = pd.Timestamp(validation_zone.end)
    # Couverture réelle après n_folds_generated folds = requested_test_end du dernier généré =
    # VALIDATION.start + n*step + train + test ; avec step==test (invariant V1), simplifié en
    # n*step + train. Ne PAS confondre avec "VALIDATION.start + n*step" seul, qui n'est que le
    # train_start du fold candidat SUIVANT (non généré) — sous-estimerait la couverture réelle dès
    # que train_period > step_period (folds Rolling volontairement chevauchants en TRAIN).
    tail_start = _add_months(validation_start, n_folds_generated * step_months + train_months)
    if tail_start >= validation_end:
        return None
    return SplitBoundary(start=tail_start.isoformat(), end=validation_zone.end)


def compute_fold_definitions(
    validation_zone: SplitBoundary,
    spec: WalkForwardSpecification,
    readiness_spec: Optional[DailyStateReadiness],
) -> Tuple[FoldDefinition, ...]:
    """Génération DÉTERMINISTE, PURE de la géométrie Rolling — aucun backtest, aucun résultat de
    performance consulté, aucune dépendance au nombre de workers (ADR 0021 Décision 1). Résout la
    readiness fold par fold en réutilisant `resolve_state_ready_boundary()` telle quelle
    (`strategy_contracts.py`) — jamais réimplémentée.

    **Condition de génération** (ADR 0021 Décision 1, formalisée) : le fold `k` (0-indexé) est
    généré SI ET SEULEMENT SI `train_start_k + train_period + test_period <= VALIDATION.end`, avec
    `train_start_k = VALIDATION.start + k * step_period` — comparaison sur les cibles calendaires
    BRUTES (`requested_*`), avant toute résolution readiness. La génération s'arrête au premier `k`
    où cette inégalité échoue ; aucun fold n'est jamais "réparé" après coup pour tenir.

    **Règle terminale V2** (ADR 0021 Décision 4, corrigée 2026-09-15) : pour le DERNIER fold généré
    uniquement, `effective_test_end = requested_test_end` INCONDITIONNELLEMENT (jamais résolu par
    `resolve_state_ready_boundary()`), `test_end_adjusted = False` toujours — aucun successeur à
    protéger, un décalage en avant risquerait `FINAL_HOLDOUT`. Tous les autres folds résolvent leur
    `effective_test_end` indépendamment via `resolve_state_ready_boundary()`. `effective_boundary`
    (frontière TRAIN/TEST interne) reste résolue par readiness pour TOUS les folds, y compris le
    dernier.

    Lève `UnsupportedWalkForwardGeometry` si `spec.geometry != "rolling"` (défense en profondeur —
    `build_walk_forward_specification()` valide déjà ce point ; revalidé ici au cas où l'appelant
    aurait construit une `WalkForwardSpecification` directement, sans passer par le builder).
    Lève `ValueError` si `step_period != test_period` (même raison). Lève
    `DatasetTooShortForWalkForward` si zéro fold n'est généré. Lève `NoStateReadyBoundary`
    (réutilisée comme TYPE, message contextualisé par fold — Décision 11) si une frontière résolue
    collapse `train_start < effective_boundary < effective_test_end`. Lève `OosOverlapError` en
    garde défensive finale (ne devrait jamais se déclencher, Décision 4)."""
    if spec.geometry != _SUPPORTED_GEOMETRY:
        raise UnsupportedWalkForwardGeometry(
            f"geometry={spec.geometry!r} non supportée en V1 — seule 'rolling' est implémentée."
        )
    train_months = _period_to_months(spec.train_period, "train_period")
    test_months = _period_to_months(spec.test_period, "test_period")
    step_months = _period_to_months(spec.step_period, "step_period")
    if step_months != test_months:
        raise ValueError(
            f"step_period ({spec.step_period!r}) doit être égal à test_period "
            f"({spec.test_period!r}) — invariant V1 (ADR 0021 Décision 1/4)."
        )

    validation_start = pd.Timestamp(validation_zone.start)
    validation_end = pd.Timestamp(validation_zone.end)

    # Trouvaille /code-review (revue scientifique de cette mission) : les trois bornes de CHAQUE
    # fold sont calculées comme UN SEUL SAUT depuis validation_start (jamais chaînées entre elles
    # via des additions successives, ex. train_start_k + train_period PUIS +test_period).
    # L'arithmétique mensuelle avec clampage de fin de mois (ex. 31 janvier + 1 mois = 28 février)
    # n'est PAS associative : (d+1mo)+3mo peut différer de d+4mo si un clampage intervient au
    # milieu de la chaîne (reproduit empiriquement : 2023-01-31 → chaîné = 2023-05-28, direct =
    # 2023-05-31). Calculer chaque borne comme validation_start + DateOffset(months=TOTAL) rend
    # requested_test_end du fold k et requested_boundary du fold k+1 IDENTIQUES PAR CONSTRUCTION
    # (même expression, même total de mois k*step+train+test == (k+1)*step+train puisque
    # step==test est un invariant déjà validé) — le théorème de non-chevauchement de la Décision 4
    # devient une garantie littérale, plus seulement supposée sous une hypothèse d'associativité.
    raw_folds = []
    k = 0
    while True:
        train_start_k = _add_months(validation_start, k * step_months)
        requested_boundary = _add_months(validation_start, k * step_months + train_months)
        requested_test_end = _add_months(
            validation_start, k * step_months + train_months + test_months,
        )
        if requested_test_end > validation_end:
            break
        raw_folds.append((k, train_start_k, requested_boundary, requested_test_end))
        k += 1

    if not raw_folds:
        raise DatasetTooShortForWalkForward(
            f"Aucun fold ne tient dans VALIDATION [{validation_zone.start}, "
            f"{validation_zone.end}) avec train_period={spec.train_period!r}/"
            f"test_period={spec.test_period!r} — élargir VALIDATION ou réduire la géométrie."
        )

    last_index = len(raw_folds) - 1
    fold_definitions = []
    for k, train_start_k, requested_boundary, requested_test_end in raw_folds:
        is_last_fold = k == last_index
        train_start_iso = train_start_k.isoformat()
        requested_boundary_iso = requested_boundary.isoformat()
        requested_test_end_iso = requested_test_end.isoformat()
        fold_id = f"fold_{k:03d}"

        boundary_resolution = resolve_state_ready_boundary(requested_boundary_iso, readiness_spec)
        effective_boundary_iso = boundary_resolution.effective_boundary
        boundary_adjusted = boundary_resolution.adjusted

        if is_last_fold:
            # Règle terminale V2 — jamais résolue par readiness (voir docstring ci-dessus).
            effective_test_end_iso = requested_test_end_iso
            test_end_adjusted = False
        else:
            test_end_resolution = resolve_state_ready_boundary(
                requested_test_end_iso, readiness_spec,
            )
            effective_test_end_iso = test_end_resolution.effective_boundary
            test_end_adjusted = test_end_resolution.adjusted

        ts_train_start = pd.Timestamp(train_start_iso)
        ts_effective_boundary = pd.Timestamp(effective_boundary_iso)
        ts_effective_test_end = pd.Timestamp(effective_test_end_iso)
        if not (ts_train_start < ts_effective_boundary < ts_effective_test_end):
            raise NoStateReadyBoundary(
                f"{fold_id} : aucune frontière effective ne satisfait train_start < "
                f"effective_boundary < effective_test_end (train_start={train_start_iso!r}, "
                f"effective_boundary={effective_boundary_iso!r} "
                f"[requested={requested_boundary_iso!r}], "
                f"effective_test_end={effective_test_end_iso!r} "
                f"[requested={requested_test_end_iso!r}]). Jamais une fenêtre TEST vide ou un "
                "repli silencieux vers la frontière demandée."
            )

        fold_definitions.append(FoldDefinition(
            fold_index=k,
            fold_id=fold_id,
            train_start=train_start_iso,
            requested_boundary=requested_boundary_iso,
            effective_boundary=effective_boundary_iso,
            boundary_adjusted=boundary_adjusted,
            requested_test_end=requested_test_end_iso,
            effective_test_end=effective_test_end_iso,
            test_end_adjusted=test_end_adjusted,
            is_last_fold=is_last_fold,
        ))

    result = tuple(fold_definitions)
    check_no_oos_overlap(result)
    return result
