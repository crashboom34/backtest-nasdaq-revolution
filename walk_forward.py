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

import dataclasses
import hashlib
import json
import re
import statistics
from pathlib import Path
from typing import Optional, Tuple, Union

import pandas as pd

from atomic_json_store import load_json_tolerant, load_tolerant, save_atomic
from dataset_split import DatasetSplitPlan, SplitBoundary
from market_data.backtest_manifest import load_backtest_manifest
from optimizer import (
    STATE_READINESS_SEMANTICS_VERSION,
    TRAIN_TEST_SEMANTICS_VERSION,
    FilterConfig,
    NoStateReadyBoundary,
    Optimizer,
    TrainTestConfig,
    compute_score,
    count_combinations,
    params_hash,
    reaches_stratified_sample,
)
from strategy_contracts import DailyStateReadiness, resolve_state_ready_boundary
from validation_run import (
    VALIDATION_TYPE_WALK_FORWARD,
    AggregateResult,
    FoldDefinition,
    FoldResult,
    FoldSelection,
    ValidationRun,
    WalkForwardRunOutcome,
    WalkForwardSpecification,
    build_validation_run,
    build_walk_forward_evidence,
)

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


# ══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 2 — Optimizer TRAIN-only + sélection Top-1 + exécution TEST par fold
# (ADR 0021 Décisions 4/6/7). Orchestration réelle : la géométrie pure ci-dessus reste inchangée
# (Slice 1, figée) ; ce qui suit consomme ses `FoldDefinition` pour produire un `FoldResult` par
# fold, en mémoire uniquement (persistance/agrégation/verdict scientifique hors scope, Décision
# 12/13/15 — tranche suivante).
# ══════════════════════════════════════════════════════════════════════════════


class NoEligibleTrainCandidate(ValueError):
    """Levée quand TOUS les candidats TRAIN d'un fold sont à zéro trade/filtrés (score <= 0) —
    le fold n'a pas de `FoldSelection` possible (ADR 0021 Décision 15). Distincte du cas TEST à
    zéro trade (`FoldResult.zero_trade_oos=True`), qui reste une observation scientifique valide,
    jamais une erreur."""


class FoldTestExecutionFailed(RuntimeError):
    """Levée si l'UNIQUE exécution TEST d'un fold échoue techniquement (exception interne à
    `engine.run_backtest()`, absorbée par `optimizer._run_single()` sous la forme
    `filtered=True, filter_reason="Exception: ..."`, `stats={}`) — jamais traduite
    silencieusement en `FoldResult(zero_trade_oos=True)`, qui doit rester réservé à une
    authentique absence de trade (ADR 0021 Décision 15) : les deux cas produisent tous deux
    `stats.get("n_trades", 0) == 0` et seraient sinon indiscernables. Symétrique à
    `NoEligibleTrainCandidate` côté TRAIN : un échec technique se propage, il ne devient jamais
    une observation scientifique."""


class NonDeterministicSearchWithoutSeed(ValueError):
    """Levée dans `run_fold_train()` quand la recherche TRAIN d'un fold atteindrait
    `optimizer._run_stratified_sample()` (mode="general", 50 000 < candidats déclarés <= 500 000,
    aucun `max_combinations`) SANS `fold_seed` fourni (ADR 0021 Décisions 9/11).

    `_run_stratified_sample()` tire ses combinaisons via `random.choice()` — le module `random`
    GLOBAL si aucun seed n'est transmis à `Optimizer.run()` (voir AF-V-02 Slice 2,
    `Optimizer._search_seed`) : sans seed, deux exécutions du même fold (ou une reprise) peuvent
    sélectionner des candidats TRAIN différents, donc un Top-1 différent — contredit la garantie
    de déterminisme de la Décision 9 ("fold_seed... déterministe, indépendant du nombre de
    workers"). Trouvaille de revue indépendante (tentative 2) : la Décision 9 affirme ce cas "sans
    objet" pour les modes actuellement supportés par `optimizer.py` ("single_var/cross_zone/grid/
    general, tous déterministes") — affirmation FACTUELLEMENT INCORRECTE pour "general" au-delà de
    50 000 combinaisons déclarées, corrigée ici par un garde explicite (`docs/adr/` hors des
    chemins autorisés de cette mission, jamais réécrit)."""


def _train_search_reaches_stratified_sample(base_config) -> bool:
    """Délègue à `optimizer.reaches_stratified_sample()` — point de vérité UNIQUE pour la
    condition de branchement d'`optimizer.Optimizer.run()` menant à `_run_stratified_sample()`
    (le SEUL point de hasard non-seedé de `optimizer.py`). `walk_forward.py` ne maintient plus sa
    propre réplique de la table de dispatch/des seuils 50 000-500 000 : toute évolution
    d'`optimizer.py` (renommage de mode, changement de seuil) se propage ici automatiquement, et
    `Optimizer.run()` lui-même casse immédiatement (assertion runtime) si son dispatch dict
    divergeait un jour de `optimizer.DETERMINISTIC_DISPATCH_MODES` — trouvaille de revue
    indépendante (tentative 3, finding MAJEUR) : une réplique locale, même exacte au moment où elle
    est écrite, ne peut pas rester synchronisée avec optimizer.py sans mécanisme de vérification."""
    return reaches_stratified_sample(base_config)


def run_fold_train(
    fold: FoldDefinition,
    base_config,
    df,
    progress_cb=None,
    stop_flag_fn=None,
    fold_seed: Optional[int] = None,
    already_tested: Optional[set] = None,
) -> Tuple[list, dict]:
    """Exécute la phase TRAIN-only d'UN fold (ADR 0021 Décision 6) : `Optimizer.run(
    run_test_validation=False)`, `train_test.enabled=False` — le bloc `if tt.enabled:` de
    `Optimizer.run()` n'est donc jamais atteint pour cet appel, `resolve_state_ready_boundary()`
    n'est PAS rappelée ici : elle a déjà été résolue exactement une fois pour cette frontière de
    fold par `compute_fold_definitions()` (Décision 4). Fenêtre d'exécution bornée DIRECTEMENT à
    `[fold.train_start, fold.effective_boundary)` via `opt_start_date`/`opt_end_date` — jamais un
    second split interne (voir `optimizer.resolve_execution_window()`, AF-V-02 Slice 2, pour le
    mode ISO-8601 complet qui rend cette borne EXCLUSIVE exacte à la seconde, plutôt que le mode
    "YYYY-MM-DD" historique). `max_rows` de `base_config` est neutralisé (`None`) sur cette copie
    de configuration : `resolve_execution_window()` applique `max_rows` APRÈS le filtrage par
    dates et tronquerait silencieusement cette fenêtre si `base_config` en héritait un (ex. preset
    `quick_validation_mode`) — la fenêtre TRAIN documentée ci-dessus doit rester exacte quel que
    soit le `base_config` fourni par l'appelant (review indépendante, tentative 1).

    `fold_seed` (ADR 0021 Décisions 9/11, review indépendante tentative 2) : transmis tel quel à
    `Optimizer.run(seed=fold_seed)` — seede réellement `_run_stratified_sample()` quand fourni
    (déterminisme réel, pas seulement un garde contourné). Si `fold_seed is None` ET que
    `base_config` atteindrait `_run_stratified_sample()` (mode="general", 50 000 à 500 000
    combinaisons déclarées), lève `NonDeterministicSearchWithoutSeed` AVANT tout backtest — jamais
    une recherche TRAIN silencieusement non-reproductible.

    `already_tested` (AF-V-02 Slice 5, extension additive — ADR 0021 Décision 12) : transmis TEL
    QUEL à `Optimizer.run(already_tested=...)`, le mécanisme de reprise déjà existant et
    non-Walk-Forward (`optimizer._run_batch_sequential`/`_run_batch_parallel`) — tout candidat dont
    `optimizer.params_hash(params)` y figure est SAUTÉ (jamais réexécuté), et n'apparaît PAS dans
    `all_results` retourné par cet appel (voir leur propre docstring : seuls les candidats
    RÉELLEMENT réexécutés sont retournés). `None` (défaut, tout appelant existant — Slice 2/3/4,
    `execute_walk_forward_fold()`) laisse le comportement strictement inchangé, `Optimizer.run()`
    traitant `None` exactement comme `set()`. Voir `_redo_fold_reusing_train_candidates()` pour
    l'appelant réel de ce paramètre (reconstruction du `FoldSelection` Top-1 à partir de l'UNION
    des candidats rechargés et de `all_results`, jamais de ce dernier seul).

    Retourne `(all_results, sensitivity)` — même contrat que `Optimizer.run()`, `all_results`
    déjà trié par score TRAIN décroissant PARMI LES SEULS candidats réexécutés à cet appel (voir
    `already_tested` ci-dessus)."""
    if fold_seed is None and _train_search_reaches_stratified_sample(base_config):
        active_ranges = [pr for pr in base_config.param_ranges if pr.enabled]
        raise NonDeterministicSearchWithoutSeed(
            f"{fold.fold_id} : base_config.mode='general' sur "
            f"{count_combinations(active_ranges)} candidats déclarés atteindrait "
            "optimizer._run_stratified_sample() (tirage random.choice() non-seedé) sans "
            "fold_seed — non-déterministe, refusé (ADR 0021 Décisions 9/11). Fournir un "
            "fold_seed entier à execute_walk_forward_fold()/run_fold_train(), ou changer le "
            "search space pour sortir de cette plage (<=50 000 ou >500 000 combinaisons, toutes "
            "deux déterministes)."
        )
    train_config = dataclasses.replace(
        base_config,
        train_test=TrainTestConfig(enabled=False),
        opt_start_date=fold.train_start,
        opt_end_date=fold.effective_boundary,
        max_rows=None,
    )
    optimizer = Optimizer(train_config, df)
    return optimizer.run(
        progress_cb=progress_cb, stop_flag_fn=stop_flag_fn, run_test_validation=False,
        seed=fold_seed, already_tested=already_tested,
    )


def _search_space_hash(param_ranges) -> str:
    """Hash stable du search space déclaré pour un fold — même convention que
    `optimizer.params_hash()` (md5 tronqué, JSON trié) mais appliquée aux `ParamRange`
    (dataclasses, pas des `dict`) plutôt qu'à un jeu de paramètres résolu."""
    serialized = json.dumps(
        [dataclasses.asdict(pr) for pr in param_ranges], sort_keys=True, ensure_ascii=False,
    )
    return hashlib.md5(serialized.encode()).hexdigest()[:12]


def select_fold_top1(
    fold: FoldDefinition,
    all_results: list,
    base_config,
    fold_seed: Optional[int] = None,
) -> FoldSelection:
    """Sélection TRAIN Top-1 d'un fold (ADR 0021 Décision 6) : `all_results[0]` (meilleur score
    TRAIN, déjà trié par `Optimizer.run()`) devient `FoldSelection.selected_params`. "Éligible" =
    score TRAIN > 0 (candidat non filtré/zéro-trade — même convention que `run_mode1()`..
    `run_mode4()` dans `optimizer.py`) : si AUCUN candidat n'est éligible, lève
    `NoEligibleTrainCandidate` (Décision 15) — rien à sélectionner, jamais une `FoldSelection`
    construite sur un candidat filtré. `train_candidates_unique` compte les hash de paramètres
    DISTINCTS parmi TOUS les candidats évalués (pas seulement les éligibles) — une recherche
    multi-passes (ex. mode "general") peut réévaluer la même combinaison plusieurs fois."""
    eligible = [r for r in all_results if r["score"] > 0]
    if not eligible:
        raise NoEligibleTrainCandidate(
            f"{fold.fold_id} : aucun candidat TRAIN éligible parmi "
            f"{len(all_results)} évalué(s) (tous à zéro trade/filtrés) — impossible de "
            "construire une FoldSelection (ADR 0021 Décision 15)."
        )
    best = all_results[0]
    unique_hashes = {params_hash(r["params"]) for r in all_results}
    return FoldSelection(
        fold_id=fold.fold_id,
        selected_params=dict(best["params"]),
        selected_params_hash=params_hash(best["params"]),
        score_train=best["score"],
        rank_in_train=1,
        train_candidates_evaluated=len(all_results),
        train_candidates_unique=len(unique_hashes),
        train_candidates_eligible=len(eligible),
        search_space_hash=_search_space_hash(base_config.param_ranges),
        algorithm=base_config.mode,
        fold_seed=fold_seed,
    )


_UNFILTERED_TEST_SCORING = FilterConfig(
    min_trades=0, max_drawdown_pct=float("inf"), min_profit_factor=0.0,
    max_consecutive_losses=2**31 - 1, min_win_rate=0.0,
)
"""`FilterConfig` neutralisé (AF-V-02 Slice 2, review indépendante tentative 2, finding BLOQUANT) :
les seuils d'éligibilité de `base_config.filters` (`min_trades`/`max_drawdown_pct`/
`min_profit_factor`/`max_consecutive_losses`/`min_win_rate`) sont une convention TRAIN (garder/
écarter un candidat avant sélection). Appliqués tels quels à l'UNIQUE exécution TEST d'un fold via
`optimizer._run_single()` -> `compute_score()` -> `is_filtered_out()`, ils collapsaient
silencieusement `score_test` à 0.0 dès qu'un seuil TRAIN était franchi — même avec des trades réels
et des métriques saines (`n_trades>0`, PF/win-rate corrects) : exactement le signal d'overfitting
que Walk-Forward existe pour révéler. `run_fold_test()` recalcule `score_test` avec cette instance
neutralisée (toute condition de `is_filtered_out()` devient triviale) à partir des MÊMES `stats`
déjà produites par l'unique exécution TEST (aucun second backtest) — `score_test` reflète ainsi
TOUJOURS le score pondéré réel de `compute_score()`, jamais un 0.0 emprunté à un filtre TRAIN sans
rapport (ADR 0021 Décision 13 : "FoldResult ne porte que des faits mesurés")."""


def _run_fold_test_core(
    fold: FoldDefinition,
    selection: FoldSelection,
    base_config,
    df,
) -> Tuple[FoldResult, "pd.DataFrame", "pd.DataFrame"]:
    """Cœur partagé de `run_fold_test()`/`execute_walk_forward_fold_with_artifacts()` (extrait en
    AF-V-02 Slice 4, mécanique pure — comportement identique à l'ancien corps de `run_fold_test()`,
    voir sa docstring pour le détail scientifique complet) : exécute EXACTEMENT une fois la phase
    TEST du fold et retourne `(FoldResult, trades, equity)`. `run_fold_test()` (Slice 2, signature
    et comportement externes inchangés) ignore les deux derniers éléments ;
    `execute_walk_forward_fold_with_artifacts()` (Slice 4) les capture pour la persistance disque
    (`oos_trades.csv`/`oos_equity.csv`) — dans les deux cas, un seul backtest réel par fold,
    jamais deux."""
    from optimizer import _run_single as _optimizer_run_single

    test_result = _optimizer_run_single(
        selection.selected_params, base_config, df,
        fold.effective_boundary, fold.effective_test_end,
        end_boundary="exclusive", include_artifacts=True,
    )
    if test_result["filtered"] and (test_result["filter_reason"] or "").startswith("Exception:"):
        raise FoldTestExecutionFailed(
            f"{fold.fold_id} : l'exécution TEST a échoué techniquement "
            f"({test_result['filter_reason']}) — jamais traduite en zero_trade_oos=True "
            "(ADR 0021 Décision 15)."
        )
    stats = test_result["stats"]
    trades = test_result["trades"]
    equity = test_result["equity"]
    n_trades = stats.get("n_trades", 0)
    zero_trade = n_trades == 0

    if zero_trade:
        expectancy = None
        forced_closes = 0
        score_test = test_result["score"]
        gross_win = 0.0
        gross_loss = 0.0
        n_win = 0
    else:
        expectancy = float(trades["resultat_net"].mean())
        forced_closes = int((trades["raison_sortie"] == "fin-donnees").sum())
        # Recalcul INDÉPENDANT de l'éligibilité TRAIN, à partir des MÊMES `stats` (aucun second
        # backtest) — voir _UNFILTERED_TEST_SCORING et le finding BLOQUANT qu'il corrige.
        score_test, _, _, _ = compute_score(
            stats, base_config.score_weights, _UNFILTERED_TEST_SCORING,
            params=selection.selected_params, param_ranges=base_config.param_ranges,
        )
        # gross_win/gross_loss/n_win (AF-V-02 Slice 3, extension additive de FoldResult) : mêmes
        # noms de grandeur qu'engine.py::_compute_stats(), lus depuis les MÊMES stats déjà
        # produites — .get(..., défaut) car un faux run_backtest de test peut légitimement ne pas
        # les fournir (ex. _ScoreByParamRunBacktest, Slice 2).
        gross_win = float(stats.get("gross_win", 0.0))
        gross_loss = float(stats.get("gross_loss", 0.0))
        n_win = int(stats.get("n_win", 0))

    ts_boundary = pd.Timestamp(fold.effective_boundary)
    ts_test_end = pd.Timestamp(fold.effective_test_end)
    coverage_bars = int(
        ((df["time_paris"] >= ts_boundary) & (df["time_paris"] < ts_test_end)).sum()
    )

    fold_result = FoldResult(
        fold_id=fold.fold_id,
        definition=fold,
        selection=selection,
        n_trades=n_trades,
        net_ret_pct=0 if zero_trade else stats.get("net_ret_pct", 0.0),
        max_dd_pct=stats.get("max_dd_pct"),
        profit_factor=stats.get("profit_factor"),
        win_rate=stats.get("win_rate"),
        expectancy=expectancy,
        score_test=score_test,
        zero_trade_oos=zero_trade,
        forced_closes=forced_closes,
        coverage_bars=coverage_bars,
        gross_win=gross_win,
        gross_loss=gross_loss,
        n_win=n_win,
    )
    return fold_result, trades, equity


def run_fold_test(
    fold: FoldDefinition,
    selection: FoldSelection,
    base_config,
    df,
) -> FoldResult:
    """Exécute EXACTEMENT une fois la phase TEST du fold (ADR 0021 Décision 6), sur
    `[fold.effective_boundary, fold.effective_test_end)`, `end_boundary="exclusive"` pour TOUT
    fold y compris le dernier (Décision 4 — plus d'exception terminale). Réutilise
    `optimizer._run_single()` telle quelle via un import LOCAL (mirroring le propre import local
    `from engine import run_backtest` de `_run_single()` elle-même) — ne lie jamais `_run_single`/
    `run_backtest` dans l'espace de noms module de `walk_forward` (invariant Slice 1 préservé :
    `walk_forward` reste découplé d'`engine.py`).

    Zéro trade TEST (ADR 0021 Décision 15) : observation scientifique valide, jamais une erreur —
    `zero_trade_oos=True`, `n_trades=0`, `net_ret_pct=0`,
    `profit_factor=win_rate=expectancy=None`. `expectancy` = PnL net moyen par trade
    (`trades["resultat_net"].mean()`, Décision 6) ; `forced_closes` = trades clôturés de force en
    fin de fenêtre (`raison_sortie == "fin-donnees"`, Décision 14) ; `coverage_bars` = nombre de
    barres du DataFrame source dont `time_paris` tombe dans `[effective_boundary,
    effective_test_end)` — mesuré indépendamment du moteur (jamais déduit de `equity`, dont la
    longueur dépend du warmup interne, non spécifiée par cette mission).

    `score_test` (review indépendante tentative 2, finding BLOQUANT) : recalculé via
    `compute_score()` avec `_UNFILTERED_TEST_SCORING` — INDÉPENDANT de l'éligibilité TRAIN
    (`base_config.filters`), jamais silencieusement mis à 0.0 par un seuil TRAIN franchi alors que
    les trades/métriques TEST sont réels et sains. Voir docstring de `_UNFILTERED_TEST_SCORING`.

    Lève `FoldTestExecutionFailed` si cette exécution TEST échoue techniquement (exception interne
    à `run_backtest()`, `filter_reason` préfixé par `"Exception:"` — voir `optimizer._run_single()`)
    : un échec technique sur l'UNIQUE exécution TEST du fold ne doit jamais être confondu avec un
    authentique zéro-trade, les deux produisant identiquement `stats.get("n_trades", 0) == 0`.

    AF-V-02 Slice 4 : le corps de cette fonction a été extrait tel quel dans `_run_fold_test_core()`
    (mécanique pure) — signature et valeur de retour de `run_fold_test()` elle-même restent
    strictement inchangées, comportement inchangé pour tout appelant existant."""
    fold_result, _trades, _equity = _run_fold_test_core(fold, selection, base_config, df)
    return fold_result


def execute_walk_forward_fold(
    fold: FoldDefinition,
    base_config,
    df,
    progress_cb=None,
    stop_flag_fn=None,
    fold_seed: Optional[int] = None,
) -> FoldResult:
    """Orchestration complète d'UN fold (ADR 0021 Décisions 6/7) : TRAIN-only ->
    sélection Top-1 -> EXACTEMENT une exécution TEST. Isolation TEST structurelle (Décision 7) :
    garantie par ce séquencement lui-même — aucun code ci-dessous ne rappelle `run_fold_train()`
    après `select_fold_top1()`, pas par un verrou objet (même dette assumée que
    `ValidationRun`/`DatasetSplitPlan`, voir docstring de `validation_run.py`).

    `fold_seed` est transmis À LA FOIS à `run_fold_train()` (seede réellement la recherche TRAIN
    si `_run_stratified_sample()` est atteinte, ou déclenche `NonDeterministicSearchWithoutSeed`
    si elle l'est sans seed — ADR 0021 Décisions 9/11) et à `select_fold_top1()` (métadonnée
    `FoldSelection.fold_seed`)."""
    all_results, _sensitivity = run_fold_train(
        fold, base_config, df, progress_cb=progress_cb, stop_flag_fn=stop_flag_fn,
        fold_seed=fold_seed,
    )
    selection = select_fold_top1(fold, all_results, base_config, fold_seed=fold_seed)
    return run_fold_test(fold, selection, base_config, df)


# ══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 3 — Orchestration multi-fold + agrégation OOS en mémoire
# (ADR 0021 Décisions 9/14/15). Consomme `execute_walk_forward_fold()` (Slice 2, inchangée)
# fold par fold ; aucune persistance disque, aucun `WalkForwardEvidence`/verdict scientifique ici
# (Décisions 12/13, hors scope de cette tranche).
# ══════════════════════════════════════════════════════════════════════════════


_FOLD_SEED_DOMAIN_TAG = "wf-fold-seed-v1"


def _derive_fold_seed(
    master_seed: Optional[int], validation_run_id: Optional[str], fold_index: int,
) -> Optional[int]:
    """ADR 0021 Décision 9 : `fold_seed = sha256(f"{master_seed}:{validation_run_id}:"
    f"{fold_index}:wf-fold-seed-v1")`, jamais `hash()`/`time.time()`/`random.randint()`. Retourne
    `None` tel quel si `master_seed` n'est pas fourni (le garde `NonDeterministicSearchWithoutSeed`
    de `run_fold_train()`, Slice 2, reste la seule protection dans ce cas)."""
    if master_seed is None:
        return None
    payload = f"{master_seed}:{validation_run_id}:{fold_index}:{_FOLD_SEED_DOMAIN_TAG}"
    return int(hashlib.sha256(payload.encode()).hexdigest(), 16)


def run_walk_forward(
    validation_zone: SplitBoundary,
    spec: WalkForwardSpecification,
    readiness_spec: Optional[DailyStateReadiness],
    base_config,
    df,
    progress_cb=None,
    stop_flag_fn=None,
    validation_run_id: Optional[str] = None,
) -> WalkForwardRunOutcome:
    """Orchestrateur multi-fold (ADR 0021 Décisions 9/14) : appelle `compute_fold_definitions()`
    EXACTEMENT une fois, puis `execute_walk_forward_fold()` (Slice 2, inchangée) pour chaque
    `FoldDefinition` dans l'ordre, en mémoire uniquement. `base_config`/`spec`/`readiness_spec`
    sont fixés une fois pour toutes avant la boucle et jamais dérivés d'un `FoldResult` précédent
    (Décision 14 — aucune rétroaction inter-fold) ; `flat_each_fold_v1` (chaque fold repart du même
    capital initial) est déjà garanti par construction par `execute_walk_forward_fold()` lui-même.

    `validation_run_id` est obligatoire dès que `spec.master_seed` est fourni (lève `ValueError`
    AVANT tout calcul de fold sinon) — nécessaire pour dériver un `fold_seed` déterministe par
    fold (Décision 9). Si `spec.master_seed is None`, `fold_seed=None` est propagé tel quel à
    chaque fold.

    `stop_flag_fn`, si fourni et retournant `True` ENTRE deux folds, interrompt proprement la
    boucle (jamais en plein milieu d'un fold) : retourne alors un `WalkForwardRunOutcome` avec
    `stopped_early=True` et `fold_results` limité au préfixe déjà exécuté — jamais une exception
    dédiée (voir `WalkForwardRunOutcome` dans `validation_run.py` : l'ADR 0021 Décision 11 fige une
    taxonomie d'erreurs exhaustive qui n'inclut pas ce cas, une annulation coopérative n'étant pas
    une erreur). Aucune reprise automatique (Décision 12, hors scope). Ce `stop_flag_fn` est
    STRICTEMENT une barrière inter-fold : il n'est PAS transmis à `execute_walk_forward_fold()`/
    `run_fold_train()`/`Optimizer.run()`, dont le paramètre `stop_flag_fn` interne interrompt la
    recherche TRAIN à l'intérieur même d'un fold (via `_run_batch_sequential`/
    `_run_batch_parallel`, `optimizer.py`) et produirait un `FoldResult` silencieusement tronqué et
    indiscernable d'un résultat complet — ce que Décision 6 (Top-1 sélectionné sur TOUT le TRAIN)
    et l'esprit de Décision 13 (jamais de valeur trompeuse produite silencieusement) excluent. Une
    fois un fold démarré, il va donc toujours à son terme.

    Lève `DatasetTooShortForWalkForward` telle quelle si `compute_fold_definitions()` ne génère
    aucun fold (Slice 1, jamais dupliquée ici)."""
    if spec.master_seed is not None and validation_run_id is None:
        raise ValueError(
            "validation_run_id est obligatoire quand spec.master_seed est fourni — nécessaire "
            "pour dériver un fold_seed déterministe par fold (ADR 0021 Décision 9)."
        )

    fold_definitions = compute_fold_definitions(validation_zone, spec, readiness_spec)

    fold_results = []
    for fold in fold_definitions:
        if stop_flag_fn is not None and stop_flag_fn():
            return WalkForwardRunOutcome(
                fold_results=tuple(fold_results), stopped_early=True,
            )
        fold_seed = _derive_fold_seed(spec.master_seed, validation_run_id, fold.fold_index)
        # stop_flag_fn=None volontaire (pas la barrière inter-fold ci-dessus) : voir docstring —
        # un fold démarré va toujours à son terme, jamais interrompu en cours de recherche TRAIN.
        result = execute_walk_forward_fold(
            fold, base_config, df, progress_cb=progress_cb, stop_flag_fn=None,
            fold_seed=fold_seed,
        )
        fold_results.append(result)

    return WalkForwardRunOutcome(fold_results=tuple(fold_results), stopped_early=False)


def build_aggregate_result(fold_results: Tuple[FoldResult, ...]) -> AggregateResult:
    """Peuple `AggregateResult` (ADR 0021 Décision 15) — fonction PURE, aucun backtest.

    `oos_profit_factor`/`oos_win_rate` : sommés sur la série OOS concaténée (`gross_win`/
    `gross_loss`/`n_win`/`n_trades` de chaque `FoldResult`, sommes séparables — jamais une moyenne
    de ratios par fold). `gross_loss_total == 0` avec `total_oos_trades > 0` -> `float("inf")`
    (même convention qu'`engine.py::_compute_stats()`) ; `None` réservé au seul cas
    `total_oos_trades == 0`.

    Courbe d'equity OOS reconstruite en chaînant les RENDEMENTS normalisés de chaque fold
    (`flat_each_fold_v1` : chaque fold redémarre au même capital initial 1.0) — jamais une
    concaténation brute de capital absolu. `oos_max_dd_pct` calculé directement sur cette courbe
    normalisée (jamais une moyenne/le pire des `max_dd_pct` par fold)."""
    n_folds = len(fold_results)
    n_folds_zero_trade = sum(1 for r in fold_results if r.zero_trade_oos)
    total_oos_trades = sum(r.n_trades for r in fold_results)
    gross_win_total = sum(r.gross_win for r in fold_results)
    gross_loss_total = sum(r.gross_loss for r in fold_results)
    n_win_total = sum(r.n_win for r in fold_results)

    if total_oos_trades == 0:
        oos_profit_factor = None
        oos_win_rate = None
    else:
        oos_profit_factor = (
            float("inf") if gross_loss_total == 0 else gross_win_total / gross_loss_total
        )
        oos_win_rate = n_win_total / total_oos_trades

    equity_curve = [1.0]
    for r in fold_results:
        equity_curve.append(equity_curve[-1] * (1.0 + r.net_ret_pct / 100.0))
    oos_net_return_pct = (equity_curve[-1] - 1.0) * 100.0

    peak = equity_curve[0]
    oos_max_dd_pct = 0.0
    for value in equity_curve[1:]:
        peak = max(peak, value)
        if peak > 0:
            oos_max_dd_pct = max(oos_max_dd_pct, (peak - value) / peak * 100.0)

    scores = [r.score_test for r in fold_results]
    mean_fold_score_test = statistics.mean(scores) if scores else None
    median_fold_score_test = statistics.median(scores) if scores else None
    worst_fold_id = (
        min(fold_results, key=lambda r: r.score_test).fold_id if fold_results else None
    )

    return AggregateResult(
        n_folds=n_folds,
        n_folds_zero_trade=n_folds_zero_trade,
        total_oos_trades=total_oos_trades,
        oos_net_return_pct=oos_net_return_pct,
        oos_max_dd_pct=oos_max_dd_pct,
        oos_profit_factor=oos_profit_factor,
        oos_win_rate=oos_win_rate,
        oos_sharpe=None,
        mean_fold_score_test=mean_fold_score_test,
        median_fold_score_test=median_fold_score_test,
        worst_fold_id=worst_fold_id,
    )


# ══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 4 — Persistance disque des artefacts Walk-Forward (Décision 12, ÉCRITURE SEULE).
# Consomme un `WalkForwardRunOutcome` déjà obtenu (Slice 3, inchangée) ; n'est JAMAIS appelée
# automatiquement par `run_walk_forward()` (qui reste un orchestrateur EN MÉMOIRE pur) — un
# appelant explicite invoque `persist_walk_forward_run()` après coup. Aucune reprise (le
# `state.json` produit ici n'est jamais relu pour sauter un fold), aucun `WalkForwardEvidence`/
# `validation_run.json`/verdict scientifique (Décision 13, tranche séparée ultérieure).
# ══════════════════════════════════════════════════════════════════════════════


@dataclasses.dataclass(frozen=True)
class FoldArtifacts:
    """Bundle purement local à `walk_forward.py` (jamais dans `validation_run.py` : ce n'est ni
    une `Specification` ni une `Evidence` typée, juste de la plomberie de persistance) — tout ce
    qu'`execute_walk_forward_fold_with_artifacts()` produit EN PLUS du `FoldResult` déjà existant,
    nécessaire pour écrire `train_candidates.csv`/`oos_trades.csv`/`oos_equity.csv` (Décision 12)
    sans jamais relancer de second backtest : `train_candidates` est le `all_results` déjà retourné
    par `run_fold_train()` (une entrée par candidat TRAIN évalué, contrat `Optimizer.run()`
    inchangé) ; `test_trades`/`test_equity` sont les DataFrames réels de l'UNIQUE exécution TEST du
    fold (`_run_fold_test_core()`), vides (jamais `None`) pour un fold `zero_trade_oos=True`.

    `fold_id` (review indépendante, tentative 2, finding PLAUSIBLE) : `persist_walk_forward_run()`
    associait `fold_results`/`fold_artifacts` par SEULE position de tuple (longueurs vérifiées,
    jamais l'identité) — un appelant qui construirait ces deux tuples dans un ordre divergent
    écrirait silencieusement les `trades`/`equity` d'un fold sous le répertoire d'un AUTRE fold.
    Porter `fold_id` ici permet à `persist_walk_forward_run()` de vérifier explicitement cette
    correspondance et de lever une erreur claire plutôt que d'associer silencieusement les mauvais
    artefacts."""

    fold_id: str
    train_candidates: list
    test_trades: "pd.DataFrame"
    test_equity: "pd.DataFrame"


def execute_walk_forward_fold_with_artifacts(
    fold: FoldDefinition,
    base_config,
    df,
    progress_cb=None,
    stop_flag_fn=None,
    fold_seed: Optional[int] = None,
) -> Tuple[FoldResult, FoldArtifacts]:
    """Variante additive d'`execute_walk_forward_fold()` (Slice 2, JAMAIS modifiée — même
    signature, même comportement, toujours utilisable telle quelle par tout appelant qui n'a pas
    besoin des artefacts bruts) : même orchestration TRAIN -> Top-1 -> EXACTEMENT une exécution
    TEST, mais retourne EN PLUS un `FoldArtifacts` capturé au même site d'exécution — jamais un
    second backtest pour produire cette capture (`_run_fold_test_core()` est le même cœur partagé
    que `run_fold_test()`, un seul appel réel à `optimizer._run_single()` par fold).

    Choix d'implémentation (ADR 0021 Décision 12, mission Slice 4, section 27) : plutôt que
    d'ajouter un paramètre `capture_test_artifacts` à `execute_walk_forward_fold()` elle-même (ce
    qui rendrait son type de retour conditionnel au flag, un anti-motif), cette fonction NOUVELLE
    duplique les deux lignes d'orchestration TRAIN/sélection (`run_fold_train()` +
    `select_fold_top1()`, déjà testées indépendamment Slice 2) plutôt que de risquer de
    déstabiliser `execute_walk_forward_fold()` — dette mineure assumée (deux lignes), jamais
    `execute_walk_forward_fold()` elle-même n'est touchée.

    `fold_seed` (review indépendante, tentative 2, finding PLAUSIBLE) : transmis tel quel, exactement
    comme `execute_walk_forward_fold()` — cette fonction ne dérive JAMAIS elle-même de `fold_seed`
    via `_derive_fold_seed()`. Un futur appelant qui persiste un run produit par `run_walk_forward()`
    (`master_seed`/`validation_run_id` donnés) est responsable de dériver le MÊME `fold_seed` par
    fold (`_derive_fold_seed(spec.master_seed, validation_run_id, fold.fold_index)`) que celui que
    `run_walk_forward()` a réellement utilisé en interne pour ce fold — sinon les artefacts persistés
    ne correspondraient pas au fingerprint `master_seed` enregistré dans `manifest.json`. Cette
    orchestration bout-en-bout (future intégration `app.py`) est explicitement hors scope de cette
    tranche (voir mission)."""
    all_results, _sensitivity = run_fold_train(
        fold, base_config, df, progress_cb=progress_cb, stop_flag_fn=stop_flag_fn,
        fold_seed=fold_seed,
    )
    selection = select_fold_top1(fold, all_results, base_config, fold_seed=fold_seed)
    fold_result, trades, equity = _run_fold_test_core(fold, selection, base_config, df)
    return fold_result, FoldArtifacts(
        fold_id=fold.fold_id, train_candidates=all_results, test_trades=trades, test_equity=equity,
    )


_MANIFEST_FILENAME = "manifest.json"
_STATE_FILENAME = "state.json"
_AGGREGATE_FILENAME = "aggregate.json"
_FOLDS_DIRNAME = "folds"


def _fold_dir(output_dir: Union[str, Path], fold_id: str) -> Path:
    return Path(output_dir) / _FOLDS_DIRNAME / fold_id


def build_walk_forward_manifest(
    spec: WalkForwardSpecification,
    base_config,
    data_manifest_path: Union[str, Path],
    validation_run_id: Optional[str] = None,
) -> dict:
    """Construit le contenu (dict JSON-sérialisable) de `manifest.json` (ADR 0021 Décision 12) —
    fingerprint de reprise, JAMAIS encore relu par une logique de reprise (hors scope Slice 4).

    Référence au `data_manifest.json` existant `data_manifest_path` (`market_data.
    backtest_manifest.load_backtest_manifest()`, JAMAIS un git SHA/snapshot recalculé
    indépendamment ici) — lève `ValueError` immédiatement si ce fichier est absent/illisible,
    avant tout calcul ou écriture (`persist_walk_forward_run()` échoue donc AVANT toute écriture
    disque dans ce cas). `search_space`/`scoring`/`filters` proviennent de `base_config`
    (`OptimizationConfig` réel utilisé pour le run TRAIN de tous les folds, Décision 4 : un seul
    search space partagé) — jamais de `WalkForwardSpecification`, qui ne porte que `base_params`
    (readiness), pas le search space de l'Optimizer.

    `validation_run_id` (Slice 5, correction review indépendante tentative 10, finding MAJEUR) est
    inclus tel quel dans le manifest, au même titre que `master_seed` (toujours présent, y compris
    `None`) — `_derive_fold_seed(master_seed, validation_run_id, fold_index)` en dépend pour
    dériver un `fold_seed` déterministe par fold (ADR 0021 Décision 9) ; sans cette clé, une
    reprise fournissant un `validation_run_id` différent de celui de la tentative originale
    passerait le fingerprint RUN-LEVEL (`check_resume_fingerprint()`, comparaison générique sur
    TOUTES les clés du manifest) silencieusement, produisant un `WalkForwardRunOutcome` dont les
    folds SKIP (fold_seed figé sous l'ancien `validation_run_id`) et les folds REDO/REPLAY_TEST
    (fold_seed dérivé du nouveau) mélangeraient deux graines incohérentes."""
    manifest = load_backtest_manifest(data_manifest_path)
    if manifest is None:
        raise ValueError(
            f"data_manifest_path={data_manifest_path!r} introuvable ou illisible — le fingerprint "
            "de reprise Walk-Forward (ADR 0021 Décision 12) doit référencer un data_manifest.json "
            "réel, jamais un git SHA/snapshot recalculé indépendamment ici."
        )
    return {
        "walk_forward_semantics_version": WALK_FORWARD_SEMANTICS_VERSION,
        "train_test_semantics_version": TRAIN_TEST_SEMANTICS_VERSION,
        "state_readiness_semantics_version": STATE_READINESS_SEMANTICS_VERSION,
        "master_seed": spec.master_seed,
        "validation_run_id": validation_run_id,
        "verdict_policy_id": spec.verdict_policy_id,
        "specification": dataclasses.asdict(spec),
        "search_space": [dataclasses.asdict(pr) for pr in base_config.param_ranges],
        "scoring": dataclasses.asdict(base_config.score_weights),
        "filters": dataclasses.asdict(base_config.filters),
        "strategy_name": base_config.strategy_name,
        "strategy_module": base_config.strategy_module,
        "data_manifest_path": str(Path(data_manifest_path)),
        "data_manifest": {
            "snapshot_id": manifest.snapshot_id,
            "content_hash": manifest.content_hash,
            "git_commit": manifest.git_commit,
            "provider": manifest.provider,
            "instrument": manifest.instrument,
            "strategy_version": manifest.strategy_version,
        },
    }


def _train_candidates_to_dataframe(train_candidates: list) -> "pd.DataFrame":
    """Aplatit `train_candidates` (contrat `Optimizer.run()` — une entrée par candidat TRAIN
    évalué : `score`/`params`/`stats`/`filtered`/`filter_reason`) en une ligne par candidat pour
    `train_candidates.csv` : colonnes des paramètres testés + `score`/`filtered`/`filter_reason`/
    `n_trades` (extrait de `stats`, `None` si absent — ex. candidat filtré par exception)."""
    rows = []
    for candidate in train_candidates:
        row = dict(candidate["params"])
        row["score"] = candidate["score"]
        row["filtered"] = candidate["filtered"]
        row["filter_reason"] = candidate["filter_reason"]
        row["n_trades"] = candidate["stats"].get("n_trades")
        rows.append(row)
    return pd.DataFrame(rows)


def persist_walk_forward_run(
    outcome: WalkForwardRunOutcome,
    fold_artifacts: Tuple[FoldArtifacts, ...],
    aggregate: Optional[AggregateResult],
    spec: WalkForwardSpecification,
    base_config,
    data_manifest_path: Union[str, Path],
    output_dir: Union[str, Path],
    validation_run_id: Optional[str] = None,
) -> Path:
    """Persiste sur disque les artefacts BRUTS d'un `WalkForwardRunOutcome` déjà obtenu (ADR 0021
    Décision 12, ÉCRITURE SEULE) — jamais appelée automatiquement par `run_walk_forward()`
    lui-même (qui reste un orchestrateur EN MÉMOIRE pur, Slice 3, inchangé) : un appelant explicite
    invoque cette fonction APRÈS avoir obtenu son `WalkForwardRunOutcome` (et, séparément,
    `fold_artifacts` — un `FoldArtifacts` par `FoldResult`, MÊME ORDRE, produit par
    `execute_walk_forward_fold_with_artifacts()`, jamais par un second backtest).

    Structure écrite sous `output_dir` (paramétrable par l'appelant, jamais un chemin codé en dur
    sous `results/` — voir `optimization_store.get_job_dir()` pour la convention établie ailleurs
    dans ce dépôt) :
    - `manifest.json` (`build_walk_forward_manifest()`) ;
    - `state.json` — PUREMENT DESCRIPTIF ici (liste des `fold_id` déjà écrits) : aucune logique de
      reprise ne le relit encore (tranche suivante) ;
    - `folds/fold_NNN/{definition,selection,test_result}.json` — sérialisation directe
      (`dataclasses.asdict()`) de `FoldDefinition`/`FoldSelection`/`FoldResult` ;
    - `folds/fold_NNN/{train_candidates,oos_trades,oos_equity}.csv` ;
    - `aggregate.json` (`dataclasses.asdict()` d'`AggregateResult`) si `aggregate is not None`.

    **Décision `tested.json`/`selection.json`** (mission Slice 4, section 27, choix explicitement
    laissé à l'implémentation — précisé en review indépendante tentative 3, la justification
    "redondance" de la tentative 2 lisait mal la convention établie du dépôt) : ailleurs dans ce
    dépôt (`optimization_store.py::load_tested_hashes()`/`save_tested_hashes()`), `tested.json`
    désigne un ensemble de hashs de candidats déjà évalués, écrit de façon INCRÉMENTALE PENDANT
    qu'un TRAIN est en cours, pour permettre à une reprise de sauter les candidats déjà exécutés
    sans les rejouer — exactement le mécanisme que Décision 12 évoque pour "un TRAIN interrompu
    réutilise les candidats déjà exécutés". Cette fonction-ci (`persist_walk_forward_run()`) ne
    peut structurellement PAS produire ce fichier avec ce sens : elle persiste un
    `WalkForwardRunOutcome` déjà COMPLET (TRAIN déjà entièrement terminé pour chaque fold), de
    façon post-hoc, en un seul appel — jamais pendant qu'un TRAIN tourne encore. Écrire ici un
    `tested.json` "statique" (snapshot final des hashs, plutôt qu'un flux incrémental pendant
    l'exécution) n'apporterait aucune capacité de reprise réelle et serait de toute façon
    intégralement reconstructible depuis `train_candidates.csv` déjà écrit. Choix retenu :
    **aucun fichier `tested.json` n'est écrit dans cette tranche** — le mécanisme incrémental
    réel (instrumentation de la boucle TRAIN elle-même, hors de `persist_walk_forward_run()`)
    reste entièrement à la charge de la tranche de reprise future (hors scope Slice 4), jamais
    simulé ici par un format parallèle qui n'en aurait que l'apparence.

    Toute écriture JSON passe par `atomic_json_store.save_atomic()` (jamais un `open()`/
    `json.dump()` direct) — seule garantie d'atomicité exigée par la mission (Décision 12 ne la
    demande que pour les fichiers JSON). Les CSV utilisent `pandas.DataFrame.to_csv()` direct
    (écriture non atomique, volontairement — le dépôt n'a pas de convention CSV atomique unique
    à répliquer ici : `optimization_store.py` écrit ses CSV en `csv.DictWriter` incrémental,
    `market_data/derived.py` écrit les siens en tmp+`os.replace()` ; aucun des deux n'est le
    format tabulaire par fold visé ici). Lève `ValueError` si `len(fold_artifacts)
    != len(outcome.fold_results)`, ou si un `fold_artifacts[i].fold_id` ne correspond pas à
    `outcome.fold_results[i].fold_id` (review indépendante tentative 2, finding PLAUSIBLE :
    l'appariement par seule position de tuple, sans vérifier l'identité, écrirait silencieusement
    les `trades`/`equity` d'un fold sous le répertoire d'un AUTRE fold en cas d'ordre divergent) —
    un `FoldArtifacts` par `FoldResult`, MÊME ORDRE, MÊME `fold_id`, jamais réassociés autrement.
    Lève `ValueError` (voir `build_walk_forward_manifest()`) AVANT toute écriture disque si
    `data_manifest_path` est introuvable/illisible.

    `validation_run_id` (Slice 5, correction review indépendante tentative 10, finding MAJEUR) est
    transmis tel quel à `build_walk_forward_manifest()` pour être inclus dans `manifest.json` —
    un appelant qui persiste un run mené avec un `validation_run_id` donné (même paramètre que
    celui passé à `run_walk_forward()`) doit repasser EXACTEMENT la même valeur ici pour que
    `check_resume_fingerprint()` puisse détecter, à la reprise, une divergence de
    `validation_run_id` (voir sa docstring)."""
    if len(fold_artifacts) != len(outcome.fold_results):
        raise ValueError(
            f"fold_artifacts ({len(fold_artifacts)} élément(s)) et outcome.fold_results "
            f"({len(outcome.fold_results)} élément(s)) doivent avoir la même longueur, dans le "
            "même ordre — un FoldArtifacts par FoldResult, jamais réassociés autrement."
        )
    for fold_result, artifacts in zip(outcome.fold_results, fold_artifacts):
        if artifacts.fold_id != fold_result.fold_id:
            raise ValueError(
                f"fold_artifacts et outcome.fold_results divergent à la même position : "
                f"FoldArtifacts.fold_id={artifacts.fold_id!r} != "
                f"FoldResult.fold_id={fold_result.fold_id!r} — jamais associés silencieusement "
                "sur la seule position de tuple (ordre attendu identique)."
            )

    # build_walk_forward_manifest() échoue ici, AVANT toute écriture disque, si data_manifest_path
    # est introuvable/illisible (voir sa docstring).
    manifest_data = build_walk_forward_manifest(
        spec, base_config, data_manifest_path, validation_run_id=validation_run_id,
    )

    output_path = Path(output_dir)
    save_atomic(output_path / _MANIFEST_FILENAME, manifest_data, "walk_forward_manifest")

    for fold_result, artifacts in zip(outcome.fold_results, fold_artifacts):
        fold_dir = _fold_dir(output_path, fold_result.fold_id)
        # Créé explicitement (review indépendante, finding MAJEUR) : les trois `.to_csv()`
        # ci-dessous ne créent jamais leur répertoire parent elles-mêmes — sans cette ligne,
        # leur succès dépendrait implicitement du fait que les `save_atomic()` JSON qui les
        # précèdent aient déjà créé `fold_dir` via leur propre `mkdir()` interne, un couplage
        # d'ordre non documenté qu'un futur réordonnancement casserait silencieusement.
        fold_dir.mkdir(parents=True, exist_ok=True)
        save_atomic(
            fold_dir / "definition.json", dataclasses.asdict(fold_result.definition),
            "walk_forward_fold_definition",
        )
        save_atomic(
            fold_dir / "selection.json", dataclasses.asdict(fold_result.selection),
            "walk_forward_fold_selection",
        )
        save_atomic(
            fold_dir / "test_result.json", dataclasses.asdict(fold_result),
            "walk_forward_fold_test_result",
        )
        _train_candidates_to_dataframe(artifacts.train_candidates).to_csv(
            fold_dir / "train_candidates.csv", index=False,
        )
        artifacts.test_trades.to_csv(fold_dir / "oos_trades.csv", index=False)
        artifacts.test_equity.to_csv(fold_dir / "oos_equity.csv", index=False)

    state_data = {"completed_fold_ids": [fr.fold_id for fr in outcome.fold_results]}
    save_atomic(output_path / _STATE_FILENAME, state_data, "walk_forward_state")

    if aggregate is not None:
        save_atomic(
            output_path / _AGGREGATE_FILENAME, dataclasses.asdict(aggregate),
            "walk_forward_aggregate",
        )

    return output_path


# ══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 8 — Assemblage d'une ValidationRun Walk-Forward réelle (ADR 0021 Décisions 8/13).
# Mirroring exact du précédent établi par validation_oos.py::run_oos_validation() côté "oos" :
# reçoit `outcome`/`aggregate` DÉJÀ obtenus par un appel séparé et antérieur (jamais recalculés ni
# ré-exécutés ici — contrairement à run_oos_validation(), cette fonction n'exécute elle-même aucun
# backtest), `research_run_id`/`validation_run_id`/`strategy_name`/`strategy_params` fournis TELS
# QUELS par l'appelant (jamais générés/devinés ici), et ne persiste RIEN elle-même — la persistance
# reste la responsabilité d'un futur appelant explicite (même principe que persist_walk_forward_run(),
# Slice 4, jamais rappelée automatiquement par cette fonction).
# ══════════════════════════════════════════════════════════════════════════════


def build_walk_forward_validation_run(
    outcome: WalkForwardRunOutcome,
    aggregate: Optional[AggregateResult],
    spec: WalkForwardSpecification,
    split_plan: DatasetSplitPlan,
    research_run_id: str,
    validation_run_id: str,
    strategy_name: str,
    strategy_params: dict,
) -> ValidationRun:
    """Assemble une `ValidationRun` Walk-Forward à partir d'un `outcome`/`aggregate` déjà obtenus
    (ADR 0021 Décisions 8/13) — mirroring `validation_oos.py::run_oos_validation()`, voir le
    commentaire de section ci-dessus pour la différence structurelle (aucune exécution ici, et
    aucun équivalent `HoldoutAccessEvent` retourné — Walk-Forward ne consulte pas `FINAL_HOLDOUT`,
    ce mécanisme est propre au chemin OOS).

    `spec` sert DIRECTEMENT de `specification` à `build_validation_run()` — contrairement à `"oos"`,
    `WalkForwardSpecification` porte déjà l'intention figée AVANT exécution, aucune fonction
    `build_..._specification()` intermédiaire n'est nécessaire. `spec.verdict_policy_id` est transmis
    à `build_walk_forward_evidence()` (Slice 6, inchangée) pour produire `evidence.scientific_verdict`.

    `split_plan.split_plan_id`/`split_plan.dataset_snapshot_id` fournissent les identifiants
    correspondants à `build_validation_run()` — `split_plan.validation` n'est PAS lu ici : aucune
    vérification de cohérence entre `outcome` et la zone `VALIDATION` réellement utilisée n'est faite
    (responsabilité de l'appelant, jamais silencieusement supposée vérifiée).

    Ne persiste rien (ni `save_validation_run()`, ni `persist_walk_forward_run()`) — retourne
    uniquement la `ValidationRun` construite."""
    evidence = build_walk_forward_evidence(outcome, aggregate, spec.verdict_policy_id)
    return build_validation_run(
        validation_run_id=validation_run_id,
        research_run_id=research_run_id,
        split_plan_id=split_plan.split_plan_id,
        dataset_snapshot_id=split_plan.dataset_snapshot_id,
        strategy_name=strategy_name,
        strategy_params=strategy_params,
        specification=spec,
        evidence=evidence,
        validation_type=VALIDATION_TYPE_WALK_FORWARD,
    )


# ══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 5 — Reprise (resume) d'un run Walk-Forward interrompu (ADR 0021 Décision 12,
# complément). Consomme les artefacts déjà ÉCRITS par persist_walk_forward_run() (Slice 4, JAMAIS
# modifiée) pour décider, fold par fold, s'il faut le SAUTER (déjà complet, fingerprint
# identique), rejouer UNIQUEMENT sa phase TEST (FoldSelection déjà figée mais TEST absent), ou le
# refaire ENTIÈREMENT (absent/incomplet, sans FoldSelection persistée — réutilisant RÉELLEMENT,
# dans ce dernier cas, les candidats TRAIN déjà exécutés d'une tentative interrompue via
# train_progress.csv, voir _redo_fold_reusing_train_candidates()). AUCUN WalkForwardEvidence/
# verdict scientifique ici (Décision 13, tranche séparée ultérieure). Reste, comme
# run_walk_forward() (Slice 3), un orchestrateur EN MÉMOIRE pur pour le WalkForwardRunOutcome/
# AggregateResult qu'il retourne — persist_walk_forward_run() n'est pas conçue pour ré-écrire
# par-dessus des folds déjà présents sous output_dir (save_atomic() refuse tout écrasement) ;
# persister un run repris reste une extension future, hors scope de cette tranche. SEULE
# exception, locale à un fold RESUME_ACTION_REDO : train_progress.csv (voir docstring de
# _redo_fold_reusing_train_candidates()), un artefact de CONTINUITÉ écrit/supprimé pendant la
# recherche TRAIN, jamais une source de vérité scientifique.
# ══════════════════════════════════════════════════════════════════════════════


class WalkForwardResumeMismatch(ValueError):
    """Levée quand le `manifest.json` déjà persisté sous `output_dir` diverge du fingerprint du
    run courant (ADR 0021 Décision 11/12) — toute divergence sur les TROIS versions de sémantique,
    `data_manifest.content_hash`, la spécification, le search space/scoring/filtres ou la
    stratégie référencée (toute clé de `manifest.json` SAUF `data_manifest_path`, un chemin
    filesystem, jamais une dimension de fingerprint scientifique). Jamais un
    `SKIP`/`REPLAY_TEST` silencieux sur un fingerprint divergent : mélanger, au sein d'un même run
    repris, des artefacts produits sous deux fingerprints différents produirait des métriques
    scientifiquement incohérentes — mirroring `WalkForwardSemanticsMismatch`/
    `optimizer.TrainTestSemanticsMismatch`, mais portant sur l'ENSEMBLE du fingerprint de reprise
    Walk-Forward (Décision 12), pas la seule version de sémantique Walk-Forward."""


class FoldArtifactConflict(ValueError):
    """Levée quand l'état persisté d'UN fold sous `output_dir` est structurellement incohérent —
    ne correspond à aucun des trois cas propres de reprise (`RESUME_ACTION_SKIP`/
    `RESUME_ACTION_REPLAY_TEST`/`RESUME_ACTION_REDO`), ex. `test_result.json` présent sans
    `selection.json`/`definition.json` valides, ou `selection.json` présent sans
    `definition.json` valide (écriture interrompue EN PLEIN MILIEU de la boucle par-fold de
    `persist_walk_forward_run()`, entre deux `save_atomic()`). Jamais deviné/réparé
    silencieusement : une reprise sur un répertoire de fold corrompu doit être refusée
    explicitement (ADR 0021 Décision 11), à charge pour l'appelant de nettoyer manuellement."""


class WalkForwardOrphanedFoldArtifacts(ValueError):
    """Levée quand `output_dir/folds/` contient un `fold_id` avec un `selection.json`/
    `test_result.json` déjà persisté, mais qui n'apparaît PAS parmi les `fold_id` recalculés par
    `compute_fold_definitions()` pour la tentative courante (ADR 0021 Décision 12, review
    indépendante Slice 5, finding MAJEUR) — typiquement une `validation_zone`/un `readiness_spec`
    devenu(e) plus restrictif(ve) entre deux tentatives (moins de folds qu'à l'origine).
    `validation_zone`/`readiness_spec` NE font PAS partie du fingerprint run-level de
    `check_resume_fingerprint()` (ce ne sont pas des clés de `manifest.json`) : sans cette garde,
    `resume_walk_forward_run()` itérerait silencieusement sur le sous-ensemble plus petit de folds
    recalculés, renverrait `stopped_early=False`, et `build_aggregate_result()` produirait un
    agrégat présenté comme COMPLET alors qu'il ignore les folds orphelins — exactement l'agrégat
    partiel SILENCIEUX que Décision 12 (dernier paragraphe) exclut explicitement. Jamais deviné/
    ignoré silencieusement : une reprise dont l'état disque déborde de la géométrie courante doit
    être refusée explicitement, à charge pour l'appelant de choisir un nouveau `output_dir` ou de
    restaurer la `validation_zone`/le `readiness_spec` d'origine."""


RESUME_ACTION_SKIP = "SKIP"
RESUME_ACTION_REPLAY_TEST = "REPLAY_TEST"
RESUME_ACTION_REDO = "REDO"


@dataclasses.dataclass(frozen=True)
class FoldResumeDecision:
    """Décision de reprise pour UN fold (ADR 0021 Décision 12) — jamais dans `validation_run.py`
    (même principe que `FoldArtifacts`, Slice 4 : pure plomberie de reprise locale à
    `walk_forward.py`, ni une `Specification` ni une `Evidence` typée). `selection` porté
    seulement pour `RESUME_ACTION_REPLAY_TEST` (la `FoldSelection` déjà figée à réutiliser TELLE
    QUELLE, jamais une nouvelle sélection) ; `fold_result` porté seulement pour
    `RESUME_ACTION_SKIP` (le `FoldResult` déjà persisté, relu tel quel — jamais recalculé)."""

    fold_id: str
    action: str
    selection: Optional[FoldSelection] = None
    fold_result: Optional[FoldResult] = None


def _load_fold_definition(fold_dir: Path) -> Optional[FoldDefinition]:
    """Lecture tolérante de `definition.json` — `FoldDefinition` est un dataclass PLAT (aucun
    champ imbriqué) : délègue directement à `atomic_json_store.load_tolerant()` (jamais un
    `open()`/`json.load()` direct, jamais une réplique locale de `load_tolerant()` elle-même —
    même primitive déjà réutilisée telle quelle par `dataset_split.py`/`research_run.py` pour
    leurs propres dataclasses plates)."""
    return load_tolerant(fold_dir / "definition.json", FoldDefinition)


def _load_fold_selection(fold_dir: Path) -> Optional[FoldSelection]:
    """Lecture tolérante de `selection.json` — même contrat que `_load_fold_definition()`."""
    return load_tolerant(fold_dir / "selection.json", FoldSelection)


def _load_fold_result(fold_dir: Path) -> Optional[FoldResult]:
    """Lecture tolérante de `test_result.json` — `FoldResult` a DEUX champs imbriqués
    (`definition: FoldDefinition`, `selection: FoldSelection`), reconstruits explicitement
    (`atomic_json_store.load_tolerant(path, cls)` ne suffit pas pour un dataclass imbriqué, voir
    sa propre docstring) — jamais un `cls(**data)` naïf qui laisserait `definition`/`selection`
    comme de simples `dict` bruts. `None` si le fichier est absent/illisible, ou si `definition`/
    `selection` sont absents/du mauvais type/incompatibles avec leurs dataclasses respectives."""
    data = load_json_tolerant(fold_dir / "test_result.json")
    if data is None:
        return None
    definition_data = data.get("definition")
    selection_data = data.get("selection")
    if not isinstance(definition_data, dict) or not isinstance(selection_data, dict):
        return None
    try:
        definition = FoldDefinition(**definition_data)
        selection = FoldSelection(**selection_data)
        rest = {k: v for k, v in data.items() if k not in ("definition", "selection")}
        return FoldResult(definition=definition, selection=selection, **rest)
    except TypeError:
        return None


def _fingerprint_divergent_keys(persisted: dict, current: dict) -> list:
    """Compare le `manifest.json` persisté au manifest fraîchement reconstruit pour le run
    courant (`build_walk_forward_manifest()`, Slice 4, jamais réimplémenté) — TOUTES les clés SAUF
    `data_manifest_path` (un chemin filesystem, jamais une dimension de fingerprint scientifique :
    seul `data_manifest.content_hash`, imbriqué, en fait foi — ADR 0021 Décision 12). Retourne la
    liste triée des clés divergentes (vide si le fingerprint est identique)."""
    keys = sorted((set(persisted) | set(current)) - {"data_manifest_path"})
    return [k for k in keys if persisted.get(k) != current.get(k)]


def check_resume_fingerprint(
    output_dir: Union[str, Path], current_manifest: dict,
) -> Optional[dict]:
    """Garde de reprise RUN-LEVEL (ADR 0021 Décision 12), appelée UNE SEULE FOIS avant toute
    décision par fold (jamais revalidée par `decide_fold_resume_action()`) : compare
    `manifest.json` déjà persisté sous `output_dir` (s'il existe) au fingerprint du run courant.
    Retourne `None` si `output_dir/manifest.json` est absent (run neuf, aucun état antérieur à
    valider). Retourne le manifest persisté si présent ET identique au fingerprint courant. Lève
    `WalkForwardResumeMismatch` si présent mais divergent sur au moins une clé (hors
    `data_manifest_path`) — jamais un `SKIP`/`REPLAY_TEST` silencieux sur un fingerprint
    incohérent (ADR 0021 Décision 11/12)."""
    persisted = load_json_tolerant(Path(output_dir) / _MANIFEST_FILENAME)
    if persisted is None:
        return None
    divergent = _fingerprint_divergent_keys(persisted, current_manifest)
    if divergent:
        raise WalkForwardResumeMismatch(
            f"Reprise refusée sous {output_dir} : le manifest.json déjà persisté diverge du "
            f"fingerprint du run courant sur {divergent!r} — mélanger, au sein d'un même run "
            "repris, des artefacts produits sous deux fingerprints différents produirait des "
            "métriques scientifiquement incohérentes (ADR 0021 Décision 11/12). Relancer un "
            "nouveau run vers un nouveau output_dir plutôt que de reprendre celui-ci."
        )
    return persisted


def decide_fold_resume_action(
    fold: FoldDefinition, output_dir: Union[str, Path],
) -> FoldResumeDecision:
    """Décision de reprise pour UN fold (ADR 0021 Décision 12) — suppose le fingerprint du run
    déjà validé par `check_resume_fingerprint()` (appelée une seule fois, avant la boucle par
    fold, jamais revalidée ici).

    `RESUME_ACTION_SKIP` : `test_result.json` présent et cohérent (`selection.json`/
    `definition.json` également présents et lisibles) — le fold ne sera JAMAIS ré-exécuté, son
    `FoldResult` déjà persisté est relu tel quel. `RESUME_ACTION_REPLAY_TEST` : `selection.json`
    présent et cohérent (`definition.json` lisible) mais `test_result.json` absent/incomplet — la
    `FoldSelection` déjà figée est réutilisée TELLE QUELLE, jamais une nouvelle sélection TRAIN.
    `RESUME_ACTION_REDO` : aucun `selection.json` exploitable (fold absent, ou seul
    `definition.json` présent — TRAIN jamais mené à une sélection) — refait TRAIN -> Top-1 -> TEST,
    (revue indépendante Slice 5 : `SKIP`/`REPLAY_TEST` ne valident QUE la géométrie de fold
    [`definition.json`] et le fingerprint RUN-LEVEL [`check_resume_fingerprint()` — dataset,
    stratégie, search space, scoring, filtres, versions de sémantique, `master_seed`, politique de
    verdict, exactement la liste de l'ADR 0021 Décision 12] ; `base_config.base_params`/`mode`
    n'en font délibérément PAS partie, ni ici ni dans le fingerprint RUN-LEVEL — l'ADR ne les liste
    pas parmi les dimensions de fingerprint de reprise. Seul `_fold_definition_fingerprint()` (voir
    plus bas) les couvre, mais UNIQUEMENT pour la réutilisation de candidats via
    `train_progress.csv` [`RESUME_ACTION_REDO`], un mécanisme de continuité local à cette tranche,
    jamais pour décider `SKIP`/`REPLAY_TEST` d'un fold déjà figé)
    en réutilisant RÉELLEMENT tout candidat TRAIN déjà exécuté d'une tentative précédente quand
    `train_progress.csv` en porte (voir l'exécution de cette décision,
    `_redo_fold_reusing_train_candidates()`, jamais cette fonction-ci qui reste une pure lecture
    d'artefacts).

    Lève `FoldArtifactConflict` si l'état persisté est structurellement incohérent : un
    `test_result.json` présent sans `selection.json`/`definition.json` valides, un
    `selection.json` présent sans `definition.json` valide, OU un `definition.json` persisté qui
    ne correspond PAS exactement au `fold` fraîchement recalculé pour ce `fold_id` (défense en
    profondeur, review indépendante Slice 5 : `validation_zone`/`readiness_spec` ne font PAS
    partie du fingerprint de `check_resume_fingerprint()` — un appelant qui reprendrait le MÊME
    `output_dir` avec une `validation_zone`/un `readiness_spec` différent(e) recalculerait des
    frontières de fold différentes tout en trouvant un fingerprint manifest.json identique ; sans
    cette comparaison, `SKIP`/`REPLAY_TEST` accepterait silencieusement des artefacts dont la
    géométrie a dérivé). Jamais deviné/réparé silencieusement.

    **Réutilisation des candidats TRAIN déjà exécutés (ADR 0021 Décision 12)** : cette fonction ne
    décide QUE du triplet SKIP/REPLAY_TEST/REDO à partir de `selection.json`/`test_result.json`
    (inchangé depuis la première version de cette tranche) — la réutilisation réelle des candidats
    TRAIN pour un `RESUME_ACTION_REDO` est déléguée à l'EXÉCUTION de cette décision
    (`_redo_fold_reusing_train_candidates()`, appelée par `resume_walk_forward_run()`), jamais à
    cette fonction elle-même (qui reste une pure lecture d'artefacts, sans savoir combien de
    candidats TRAIN ont déjà été évalués). Choix retenu (correction review indépendante, tentative
    3, finding MAJEUR — la version précédente de cette docstring affirmait à tort qu'aucun candidat
    n'était jamais persisté avant la fin complète d'un fold, ce qui n'était vrai QUE parce que rien
    ne les persistait encore) : `_redo_fold_reusing_train_candidates()` persiste elle-même,
    INCRÉMENTALEMENT PENDANT la recherche TRAIN, chaque candidat réellement exécuté dans
    `train_progress.csv` (sous le même `fold_dir` que `definition.json`/`selection.json` — fichier
    NOUVEAU, distinct de `train_candidates.csv` que Slice 4 n'écrit que post-hoc pour un fold
    ENTIÈREMENT terminé), puis relit ce fichier au tout début de la reprise pour peupler
    `optimizer.Optimizer.run(already_tested=...)` — le paramètre `already_tested` de la reprise
    déjà existante, non-Walk-Forward (`optimizer._run_batch_sequential`/`_run_batch_parallel`),
    réutilisé TEL QUEL (jamais modifié, jamais dupliqué) pour SAUTER réellement les candidats déjà
    évalués. Précision (revue indépendante Slice 5, tentative 10) : SEUL ce paramètre
    `already_tested` est réutilisé ici — `optimization_store.load_tested_hashes()`/
    `save_tested_hashes()` (le mécanisme de PERSISTANCE des hashs pour ce même `already_tested`,
    ailleurs dans le dépôt pour un run `Optimizer` non-Walk-Forward) ne sont JAMAIS appelées par
    cette tranche : elles ne persistent que des hashs nus, insuffisants pour reconstruire les
    `score`/`params` par candidat qu'un TOP-1 réel exige après fusion des candidats rechargés et
    nouvellement exécutés (voir plus bas). `train_progress.csv` est donc un format NOUVEAU, mais
    strictement complémentaire (jamais un doublon de `tested.json`/`load_tested_hashes()` :
    ceux-ci ne couvriraient de toute façon pas le besoin), au sens de la Décision 12 qui exige la
    réutilisation du mécanisme EXISTANT quand il convient — ici seul le filtrage `already_tested`
    convient, pas sa couche de persistance hash-only. Un
    `RESUME_ACTION_REDO` dont le fold n'a par ailleurs RIEN persisté (`test_missing_fold_directory_
    is_redo`) dégrade silencieusement vers un REDO complet (`train_progress.csv` absent ->
    `already_tested` vide) — comportement identique à un REDO classique, jamais une régression.
    Voir `_redo_fold_reusing_train_candidates()`/`_load_train_progress()` pour le détail complet du
    mécanisme (fusion des candidats rechargés et nouvellement exécutés, re-tri par score décroissant
    avant `select_fold_top1()`, garde de fingerprint de géométrie PAR FOLD distincte du fingerprint
    RUN-LEVEL de `check_resume_fingerprint()`)."""
    fold_dir = _fold_dir(output_dir, fold.fold_id)
    persisted_definition = _load_fold_definition(fold_dir)
    definition_is_consistent = persisted_definition is not None and persisted_definition == fold
    have_selection_file = (fold_dir / "selection.json").is_file()
    have_test_result_file = (fold_dir / "test_result.json").is_file()

    if have_test_result_file:
        fold_result = _load_fold_result(fold_dir)
        selection = _load_fold_selection(fold_dir)
        if fold_result is None or selection is None or not definition_is_consistent:
            raise FoldArtifactConflict(
                f"{fold.fold_id} : test_result.json présent sous {fold_dir} mais incohérent — "
                "selection.json/definition.json manquant(s), illisible(s), ou definition.json ne "
                "correspond pas au fold fraîchement recalculé. Reprise refusée plutôt que "
                "devinée (ADR 0021 Décision 11)."
            )
        return FoldResumeDecision(
            fold_id=fold.fold_id, action=RESUME_ACTION_SKIP, fold_result=fold_result,
        )

    if have_selection_file:
        selection = _load_fold_selection(fold_dir)
        if selection is None or not definition_is_consistent:
            raise FoldArtifactConflict(
                f"{fold.fold_id} : selection.json présent sous {fold_dir} mais incohérent — "
                "illisible, definition.json manquant/illisible, ou definition.json ne "
                "correspond pas au fold fraîchement recalculé. Reprise refusée plutôt que "
                "devinée (ADR 0021 Décision 11)."
            )
        return FoldResumeDecision(
            fold_id=fold.fold_id, action=RESUME_ACTION_REPLAY_TEST, selection=selection,
        )

    if persisted_definition is not None and not definition_is_consistent:
        raise FoldArtifactConflict(
            f"{fold.fold_id} : definition.json présent sous {fold_dir} mais ne correspond pas au "
            "fold fraîchement recalculé (dérive de géométrie — validation_zone/readiness_spec "
            "modifié(e) entre deux tentatives), alors qu'aucun selection.json/test_result.json "
            "n'est encore présent. Reprise refusée plutôt que devinée (ADR 0021 Décision 11) — un "
            "REDO silencieux réutiliserait potentiellement un train_progress.csv accumulé sous "
            "l'ancienne géométrie."
        )

    return FoldResumeDecision(fold_id=fold.fold_id, action=RESUME_ACTION_REDO)


_TRAIN_PROGRESS_FILENAME = "train_progress.csv"


def _train_progress_path(fold_dir: Path) -> Path:
    return fold_dir / _TRAIN_PROGRESS_FILENAME


def _fold_definition_fingerprint(fold: FoldDefinition, base_config) -> str:
    """Empreinte de géométrie ET de configuration TRAIN pour UN fold (AF-V-02 Slice 5) — jamais
    confondue avec le fingerprint RUN-LEVEL de `build_walk_forward_manifest()`/
    `check_resume_fingerprint()` (ADR 0021 Décision 12) : sert uniquement à valider que
    `train_progress.csv` (voir `_load_train_progress()`) a bien été accumulé pour la MÊME géométrie
    de fold ET le MÊME `base_config` que ceux de la tentative courante — jamais réutilisé après une
    dérive (review indépendante, tentative 3, finding MAJEUR : `check_resume_fingerprint()` ne
    couvre PAS `base_config.base_params`, les paramètres FIXES hors search space — un changement de
    l'un d'eux entre deux tentatives passerait le fingerprint RUN-LEVEL sans être détecté, mais
    produirait des scores TRAIN incomparables ; couvert ici explicitement, en plus de la géométrie
    de fold déjà couverte par `definition.json`/`decide_fold_resume_action()`, puisque ce
    fingerprint-ci EST celui qui protège concrètement la fusion `reused + new` de
    `_redo_fold_reusing_train_candidates()`). Inclut `base_params`/`param_ranges`/`score_weights`/
    `filters`/`mode`/`strategy_module` — tout ce qui influence le `score`/les `params` d'un candidat
    TRAIN — jamais `data_manifest_path`/champs runtime, mêmes principe que
    `_fingerprint_divergent_keys()`."""
    payload = {
        "fold": dataclasses.asdict(fold),
        "base_params": base_config.base_params,
        "param_ranges": [dataclasses.asdict(pr) for pr in base_config.param_ranges],
        "score_weights": dataclasses.asdict(base_config.score_weights),
        "filters": dataclasses.asdict(base_config.filters),
        "mode": base_config.mode,
        "strategy_module": base_config.strategy_module,
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(serialized.encode()).hexdigest()[:12]


def _load_train_progress(fold_dir: Path, fold: FoldDefinition, base_config) -> list:
    """Lecture TOLÉRANTE de `train_progress.csv` (ADR 0021 Décision 12, mécanisme réel de
    réutilisation des candidats TRAIN — AF-V-02 Slice 5) : candidats TRAIN déjà exécutés pour un
    fold dont le TRAIN a été interrompu AVANT d'atteindre une `FoldSelection` (aucun
    `selection.json` persisté). Fichier NOUVEAU, distinct de `train_candidates.csv` (Slice 4,
    écrit UNE SEULE FOIS, post-hoc, par `persist_walk_forward_run()` pour un fold ENTIÈREMENT
    terminé) : celui-ci est écrit INCRÉMENTALEMENT PENDANT la recherche TRAIN elle-même (voir
    `_redo_fold_reusing_train_candidates()`).

    Chaque ligne porte `fold_fingerprint` (voir `_fold_definition_fingerprint()` — géométrie DE
    FOLD **ET** configuration TRAIN, `base_config` compris) — si la première ligne lue ne
    correspond PAS à l'empreinte fraîchement recalculée, tout le fichier est ignoré (`[]`) plutôt
    que de mélanger des candidats évalués sous une géométrie/config différente.

    Jamais une source de vérité scientifique (contrairement à `definition.json`/`selection.json`/
    `test_result.json`, ADR 0021 Décision 11, dont la corruption DOIT bloquer la reprise via
    `FoldArtifactConflict`) : ce fichier n'est qu'un raccourci de reprise — absent, illisible, vide,
    ou de géométrie/config divergente, il dégrade silencieusement vers `[]` (aucun candidat
    réutilisé, REDO complet, comportement identique à avant ce mécanisme) plutôt que de lever une
    erreur."""
    path = _train_progress_path(fold_dir)
    if not path.is_file():
        return []
    try:
        progress_df = pd.read_csv(path)
    except Exception:
        return []
    if progress_df.empty:
        return []
    expected_fingerprint = _fold_definition_fingerprint(fold, base_config)
    candidates = []
    for _, row in progress_df.iterrows():
        try:
            if str(row["fold_fingerprint"]) != expected_fingerprint:
                return []
            params = json.loads(row["params_json"])
            score = float(row["score"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return []
        candidates.append({"params": params, "score": score})
    return candidates


def _write_train_progress(
    fold_dir: Path, fold: FoldDefinition, base_config, candidates: list,
) -> None:
    """Réécriture COMPLÈTE de `train_progress.csv` à chaque nouveau candidat TRAIN réellement
    exécuté — non-atomique (même convention que les CSV de `persist_walk_forward_run()`, Slice 4 :
    aucun format tabulaire atomique unique n'existe déjà dans ce dépôt pour ce cas), simplicité
    priorisée sur la performance (aucune contrainte de perf dans cette mission). Une interruption
    EN PLEIN MILIEU de cette écriture laisse au pire un fichier illisible/tronqué, dégradé
    silencieusement vers `[]` par `_load_train_progress()` (jamais une corruption qui bloquerait la
    reprise — voir sa docstring : ce fichier n'est jamais qu'une optimisation)."""
    fold_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _fold_definition_fingerprint(fold, base_config)
    rows = [
        {
            "fold_fingerprint": fingerprint,
            "params_json": json.dumps(c["params"], sort_keys=True, ensure_ascii=False),
            "score": c["score"],
        }
        for c in candidates
    ]
    pd.DataFrame(rows).to_csv(_train_progress_path(fold_dir), index=False)


_TRAIN_PROGRESS_REUSE_SAFE_MODES = frozenset({"grid"})
"""Modes `optimizer.py` pour lesquels la réutilisation de candidats via `already_tested` (Slice 5)
est PROUVÉE sûre — review indépendante, tentative 3, finding MAJEUR : `mode="grid"`
(`Optimizer.run_mode3()`) énumère un produit cartésien INDÉPENDANT du candidat par candidat
(`itertools.product`, jamais de dépendance à un résultat déjà obtenu) — sauter un candidat via
`already_tested` ne change donc RIEN aux autres candidats explorés. `mode="single_var"`
(`run_mode1()`) est PROGRESSIF/à ÉTAGES : `best_params[pr.name]` de chaque étage est dérivé du
MEILLEUR résultat de SON PROPRE batch (`optimizer.py::run_mode1`) — sauter le candidat qui aurait
été ce meilleur résultat (parce que déjà `already_tested`) ferait diverger silencieusement les
étages suivants d'un run non-interrompu, sans que la fusion/re-tri de
`_redo_fold_reusing_train_candidates()` puisse le rattraper (la divergence a lieu DANS la
génération des combos, pas dans leur classement final). `mode="general"` (`run_mode4()`) délègue
selon la taille déclarée à `run_mode3()` (sûr), `_run_stratified_sample()` (tirage aléatoire, non
audité pour ce risque) ou `_run_progressive_grid()` (3 passes, également à étages) — traité comme
non sûr par défaut, faute d'audit complet des trois branches. `mode="cross_zone"` (`run_mode2()`)
n'est jamais réellement appelé avec un historique via `Optimizer.run()` (toujours
`prior_results=[]`, voir son lambda de dispatch), mais cette garantie est un détail d'implémentation
d'`optimizer.py` (fichier INTERDIT à cette mission) — trop fragile pour s'y fier sans pouvoir le
vérifier par un test qui casserait si ça changeait. Pour tout mode HORS de cet ensemble,
`_redo_fold_reusing_train_candidates()` ignore `train_progress.csv` (aucun candidat rechargé,
`already_tested` vide) — dégrade vers un REDO complet, jamais vers une réutilisation non prouvée
sûre."""


def _redo_fold_reusing_train_candidates(
    fold: FoldDefinition,
    base_config,
    df,
    output_dir: Union[str, Path],
    progress_cb,
    fold_seed: Optional[int],
) -> FoldResult:
    """Exécute un `RESUME_ACTION_REDO` (ADR 0021 Décision 12) en réutilisant RÉELLEMENT les
    candidats TRAIN déjà exécutés d'une tentative interrompue, au lieu de systématiquement tout
    refaire depuis zéro (correction review indépendante, tentative 3, finding MAJEUR) — UNIQUEMENT
    pour `base_config.mode` dans `_TRAIN_PROGRESS_REUSE_SAFE_MODES` (voir sa docstring : les autres
    modes gardent le comportement REDO complet préexistant, une réutilisation non prouvée sûre
    étant pire qu'aucune réutilisation).

    Mécanisme : `_load_train_progress()` recharge les candidats déjà exécutés persistés par une
    tentative précédente (`[]` si aucun, ou si le mode courant n'est pas dans
    `_TRAIN_PROGRESS_REUSE_SAFE_MODES`) ; `run_fold_train(already_tested=...)` (extension additive
    Slice 5) transmet leurs hashs à `optimizer.Optimizer.run(already_tested=...)`, le mécanisme de
    reprise déjà existant et non-Walk-Forward — tout candidat déjà connu est SAUTÉ (jamais
    réexécuté) et n'apparaît PAS dans le `all_results` retourné par cet appel (voir la docstring de
    `run_fold_train()`). Les candidats rechargés et nouvellement exécutés sont fusionnés
    (`reused + new`) puis re-triés par score décroissant (même convention qu'`Optimizer.run()`)
    AVANT `select_fold_top1()`, pour reconstruire la MÊME `FoldSelection` Top-1 qu'un REDO complet
    aurait produite — jamais une sélection biaisée par l'ORDRE de fusion.

    Persiste elle-même, INCRÉMENTALEMENT PENDANT la recherche (via un `progress_cb` enveloppant
    celui de l'appelant), chaque nouveau candidat réellement exécuté dans `train_progress.csv` sous
    le fold concerné (`_write_train_progress()`) — la SEULE écriture disque de
    `resume_walk_forward_run()` (dont la docstring affirmait auparavant, à tort, ne rien persister
    elle-même : sans cette écriture, la réutilisation resterait un mécanisme qui ne sert jamais,
    faute du moindre candidat jamais accumulé avant la fin complète du fold). Fichier supprimé
    après un REDO réussi : le fold est alors complet, un futur `persist_walk_forward_run()` externe
    écrira `test_result.json`, après quoi une reprise ultérieure verra `RESUME_ACTION_SKIP` pour ce
    fold, plus jamais `RESUME_ACTION_REDO` — le fichier de continuité n'a alors plus d'usage.

    Portée réelle (review indépendante, tentative 3, finding MAJEUR) : cette fonction n'est
    invoquée QUE par `resume_walk_forward_run()` — le tout premier passage TRAIN d'un fold, via
    `run_walk_forward()`/`execute_walk_forward_fold()` (Slice 3, EN MÉMOIRE pur, jamais modifiée),
    n'écrit encore aucun `train_progress.csv`. Un fold dont le TRAIN est interrompu dès sa TOUTE
    PREMIÈRE tentative n'a donc rien à réutiliser (REDO complet, comportement inchangé) : la
    réutilisation ne devient réelle qu'à partir de la reprise d'un `RESUME_ACTION_REDO` LUI-MÊME
    interrompu une seconde fois — la seule granularité de persistance possible sans modifier
    `run_walk_forward()`/`persist_walk_forward_run()` (Slices 3/4, hors scope de cette tranche).

    `stop_flag_fn=None` transmis à `run_fold_train()` (jamais la barrière inter-fold de
    `resume_walk_forward_run()`) — même invariant qu'`execute_walk_forward_fold()`/
    `run_walk_forward()` : un fold démarré va toujours à son terme."""
    fold_dir = _fold_dir(output_dir, fold.fold_id)
    if base_config.mode in _TRAIN_PROGRESS_REUSE_SAFE_MODES:
        reused_candidates = _load_train_progress(fold_dir, fold, base_config)
    else:
        reused_candidates = []
    already_tested_hashes = {params_hash(c["params"]) for c in reused_candidates}
    accumulated = list(reused_candidates)

    def _persisting_progress_cb(done_in_batch, total_in_batch, result):
        accumulated.append({"params": result["params"], "score": result["score"]})
        if base_config.mode in _TRAIN_PROGRESS_REUSE_SAFE_MODES:
            _write_train_progress(fold_dir, fold, base_config, accumulated)
        if progress_cb is not None:
            progress_cb(done_in_batch, total_in_batch, result)

    new_results, _sensitivity = run_fold_train(
        fold, base_config, df, progress_cb=_persisting_progress_cb, stop_flag_fn=None,
        fold_seed=fold_seed, already_tested=already_tested_hashes,
    )
    merged_results = reused_candidates + new_results
    merged_results.sort(key=lambda r: r["score"], reverse=True)
    selection = select_fold_top1(fold, merged_results, base_config, fold_seed=fold_seed)
    fold_result = run_fold_test(fold, selection, base_config, df)

    progress_path = _train_progress_path(fold_dir)
    if progress_path.is_file():
        progress_path.unlink()

    return fold_result


def _fold_has_persisted_state(fold_dir: Path) -> bool:
    """Un fold_dir "compte" pour la détection d'orphelins (`_check_no_orphaned_fold_artifacts()`)
    dès qu'il porte un `selection.json` OU un `test_result.json` — même seuil que
    `decide_fold_resume_action()` (un `definition.json` seul, sans `selection.json`, ne représente
    aucun TRAIN mené à terme, rien à perdre silencieusement s'il est ignoré)."""
    return (fold_dir / "selection.json").is_file() or (fold_dir / "test_result.json").is_file()


def _check_no_orphaned_fold_artifacts(
    output_dir: Union[str, Path], fold_definitions: Tuple[FoldDefinition, ...],
) -> None:
    """Garde de reprise (ADR 0021 Décision 12, review indépendante Slice 5, finding MAJEUR) :
    lève `WalkForwardOrphanedFoldArtifacts` si `output_dir/folds/` contient un `fold_id` avec un
    état persisté (`_fold_has_persisted_state()`) qui n'apparaît PAS parmi
    `{fd.fold_id for fd in fold_definitions}` — voir la docstring de
    `WalkForwardOrphanedFoldArtifacts` pour le scénario (validation_zone/readiness_spec rétréci(e)
    entre deux tentatives). No-op si `output_dir/folds/` n'existe pas encore (run neuf)."""
    folds_root = Path(output_dir) / _FOLDS_DIRNAME
    if not folds_root.is_dir():
        return
    expected_fold_ids = {fd.fold_id for fd in fold_definitions}
    orphaned = sorted(
        entry.name for entry in folds_root.iterdir()
        if entry.is_dir()
        and entry.name not in expected_fold_ids
        and _fold_has_persisted_state(entry)
    )
    if orphaned:
        raise WalkForwardOrphanedFoldArtifacts(
            f"Reprise refusée sous {output_dir} : {len(orphaned)} répertoire(s) de fold "
            f"déjà persisté(s) {orphaned!r} ne correspond(ent) à AUCUN fold_id recalculé par "
            "compute_fold_definitions() pour la tentative courante — validation_zone/"
            "readiness_spec est probablement devenu(e) plus restrictif(ve) que lors de la "
            "tentative qui a produit ces artefacts (ADR 0021 Décision 12). Reprendre malgré "
            "cela produirait un agrégat silencieusement partiel. Choisir un nouveau output_dir, "
            "ou restaurer la validation_zone/le readiness_spec d'origine, plutôt que de "
            "reprendre celui-ci en l'état."
        )


def resume_walk_forward_run(
    validation_zone: SplitBoundary,
    spec: WalkForwardSpecification,
    readiness_spec: Optional[DailyStateReadiness],
    base_config,
    df,
    data_manifest_path: Union[str, Path],
    output_dir: Union[str, Path],
    progress_cb=None,
    stop_flag_fn=None,
    validation_run_id: Optional[str] = None,
) -> Tuple[WalkForwardRunOutcome, AggregateResult]:
    """Point d'entrée de reprise (ADR 0021 Décision 12) — mirroring `run_walk_forward()` (Slice 3,
    JAMAIS modifiée) : même géométrie (`compute_fold_definitions()` appelée EXACTEMENT une fois),
    même garde `master_seed`/`validation_run_id`, même barrière `stop_flag_fn` INTER-fold (jamais
    transmise à l'intérieur d'un fold). Diffère uniquement par la décision PAR FOLD
    (`decide_fold_resume_action()`) : `RESUME_ACTION_SKIP` relit le `FoldResult` déjà persisté
    (aucune ré-exécution, aucun nouveau backtest) ; `RESUME_ACTION_REPLAY_TEST` rejoue UNIQUEMENT
    `run_fold_test()` (Slice 2, INCHANGÉE) avec la `FoldSelection` déjà figée (jamais une nouvelle
    sélection TRAIN) ; `RESUME_ACTION_REDO` délègue à `_redo_fold_reusing_train_candidates()` —
    TRAIN -> Top-1 -> TEST, mais en réutilisant RÉELLEMENT les candidats TRAIN déjà exécutés d'une
    tentative interrompue (`train_progress.csv`, ADR 0021 Décision 12 — voir sa docstring pour le
    mécanisme complet ; correction review indépendante, tentative 3, finding MAJEUR : une version
    précédente refaisait ENTIÈREMENT le TRAIN dans tous les cas de REDO).

    Le fingerprint RUN-LEVEL est validé UNE SEULE FOIS, AVANT toute décision par fold
    (`check_resume_fingerprint()`) — un fingerprint divergent lève `WalkForwardResumeMismatch`
    immédiatement, avant tout calcul/exécution de fold. Ce fingerprint inclut désormais
    `validation_run_id` (Slice 5, correction review indépendante tentative 10, finding MAJEUR) :
    ce paramètre pilote `_derive_fold_seed()`, donc un `validation_run_id` différent de celui de la
    tentative persistée produirait, pour les folds REDO/REPLAY_TEST, un `fold_seed` incohérent
    avec celui déjà figé dans les `FoldSelection` des folds SKIP — refusé explicitement plutôt que
    mélangé silencieusement. `validation_zone`/`readiness_spec` ne font
    PAS partie de ce fingerprint run-level (ce sont des paramètres filesystem/runtime, pas des
    clés de `manifest.json`) — leur dérive éventuelle (géométrie de fold) est détectée PAR FOLD,
    dans `decide_fold_resume_action()` (comparaison `definition.json` persisté vs fold
    fraîchement recalculé), mais TOUJOURS en DEUX PHASES strictement séparées : la décision de
    TOUS les folds (`decide_fold_resume_action()`, pure lecture disque, AUCUN backtest) est
    calculée intégralement AVANT que le premier backtest réel ne démarre. Un fold tardif dont la
    géométrie a dérivé lève donc `FoldArtifactConflict` avant que des folds antérieurs aient été
    réellement ré-exécutés — jamais après coup, jamais fold par fold entrelacé avec l'exécution
    (review indépendante Slice 5 : un contrôle entrelacé aurait laissé des backtests réels
    s'exécuter pour les folds précédant celui où la dérive est détectée).

    Reste un orchestrateur EN MÉMOIRE pur pour le `WalkForwardRunOutcome`/`AggregateResult` qu'elle
    retourne (comme `run_walk_forward()`) : elle ne persiste JAMAIS elle-même `manifest.json`/
    `state.json`/`aggregate.json`/`test_result.json`/`selection.json` — `save_atomic()` refuse tout
    écrasement et `persist_walk_forward_run()` n'est pas conçue pour ré-écrire par-dessus des folds
    déjà présents, un appelant explicite reste responsable d'appeler `persist_walk_forward_run()`
    séparément s'il veut persister le résultat de cette reprise. SEULE exception, additive et
    strictement locale à un `RESUME_ACTION_REDO` (Slice 5, correction du finding MAJEUR
    ci-dessus) : `train_progress.csv` sous `fold_dir`, écrit/supprimé par
    `_redo_fold_reusing_train_candidates()` — un artefact de CONTINUITÉ de reprise, jamais une
    source de vérité scientifique (voir sa docstring), sans lequel la réutilisation des candidats
    TRAIN exigée par la Décision 12 resterait un mécanisme qui ne sert jamais.

    Retourne `(WalkForwardRunOutcome, AggregateResult)` — le `WalkForwardRunOutcome` couvre TOUS
    les folds (sautés + rejoués + refaits) dans l'ordre de `compute_fold_definitions()` ; l'appel
    explicite à `build_aggregate_result()` (Slice 3, INCHANGÉE, fonction pure) sur cet ensemble
    COMPLET produit un agrégat recalculé INTÉGRALEMENT — jamais un agrégat partiel SILENCIEUX (ADR
    0021 Décision 12, dernier paragraphe) : `build_aggregate_result()` ne distingue déjà pas
    l'origine (sauté/rejoué/refait) d'un `FoldResult`, seulement son contenu, donc aucune fonction
    d'agrégation dédiée à la reprise n'est nécessaire au-delà de cet appel explicite. SEULE
    exception, explicitement signalée et jamais silencieuse (même caveat que `run_walk_forward()`,
    Slice 3, ci-dessus) : `stop_flag_fn` interrompant la boucle ENTRE deux folds fait retourner un
    `WalkForwardRunOutcome` avec `stopped_early=True` et `fold_results` limité au préfixe déjà
    décidé/exécuté — l'agrégat retourné dans ce cas porte alors sur ce même préfixe, jamais sur
    l'ensemble des folds attendus, mais `stopped_early=True` le signale explicitement à
    l'appelant : ce n'est jamais un agrégat partiel produit SANS que l'appelant puisse le
    distinguer d'un agrégat complet."""
    if spec.master_seed is not None and validation_run_id is None:
        raise ValueError(
            "validation_run_id est obligatoire quand spec.master_seed est fourni — nécessaire "
            "pour dériver un fold_seed déterministe par fold (ADR 0021 Décision 9)."
        )

    fold_definitions = compute_fold_definitions(validation_zone, spec, readiness_spec)
    current_manifest = build_walk_forward_manifest(
        spec, base_config, data_manifest_path, validation_run_id=validation_run_id,
    )
    check_resume_fingerprint(output_dir, current_manifest)
    # validation_zone/readiness_spec ne font pas partie du fingerprint run-level ci-dessus (ce ne
    # sont pas des clés de manifest.json) — une réduction du nombre de folds recalculés entre deux
    # tentatives (zone/readiness plus restrictif) laisserait sinon des fold_dir déjà persistés
    # au-delà de ce nouveau compte silencieusement ignorés par la boucle ci-dessous, produisant un
    # agrégat partiel présenté comme complet (WalkForwardOrphanedFoldArtifacts, review indépendante
    # Slice 5, finding MAJEUR — voir sa docstring).
    _check_no_orphaned_fold_artifacts(output_dir, fold_definitions)

    # Phase 1 — décision de reprise pour TOUS les folds, avant tout backtest réel.
    # decide_fold_resume_action() ne fait QUE lire des artefacts disque (jamais de backtest) ;
    # calculer ici la décision de l'ENSEMBLE des folds garantit qu'un FoldArtifactConflict — y
    # compris une dérive géométrique validation_zone/readiness_spec détectée sur un fold tardif —
    # est levé avant que le moindre fold antérieur n'ait été réellement ré-exécuté.
    decisions = [decide_fold_resume_action(fold, output_dir) for fold in fold_definitions]

    # Phase 2 — exécution, fold par fold, dans l'ordre de compute_fold_definitions().
    fold_results = []
    for fold, decision in zip(fold_definitions, decisions):
        if stop_flag_fn is not None and stop_flag_fn():
            outcome = WalkForwardRunOutcome(fold_results=tuple(fold_results), stopped_early=True)
            return outcome, build_aggregate_result(outcome.fold_results)

        if decision.action == RESUME_ACTION_SKIP:
            fold_results.append(decision.fold_result)
            continue

        fold_seed = _derive_fold_seed(spec.master_seed, validation_run_id, fold.fold_index)

        if decision.action == RESUME_ACTION_REPLAY_TEST:
            fold_result = run_fold_test(fold, decision.selection, base_config, df)
        else:
            fold_result = _redo_fold_reusing_train_candidates(
                fold, base_config, df, output_dir, progress_cb=progress_cb, fold_seed=fold_seed,
            )
        fold_results.append(fold_result)

    outcome = WalkForwardRunOutcome(fold_results=tuple(fold_results), stopped_early=False)
    return outcome, build_aggregate_result(outcome.fold_results)
