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
from typing import Optional, Tuple

import pandas as pd

from dataset_split import SplitBoundary
from optimizer import (
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
from validation_run import FoldDefinition, FoldResult, FoldSelection, WalkForwardSpecification

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

    Retourne `(all_results, sensitivity)` — même contrat que `Optimizer.run()`, `all_results`
    déjà trié par score TRAIN décroissant."""
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
        seed=fold_seed,
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
    authentique zéro-trade, les deux produisant identiquement `stats.get("n_trades", 0) == 0`."""
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
    n_trades = stats.get("n_trades", 0)
    zero_trade = n_trades == 0

    if zero_trade:
        expectancy = None
        forced_closes = 0
        score_test = test_result["score"]
    else:
        expectancy = float(trades["resultat_net"].mean())
        forced_closes = int((trades["raison_sortie"] == "fin-donnees").sum())
        # Recalcul INDÉPENDANT de l'éligibilité TRAIN, à partir des MÊMES `stats` (aucun second
        # backtest) — voir _UNFILTERED_TEST_SCORING et le finding BLOQUANT qu'il corrige.
        score_test, _, _, _ = compute_score(
            stats, base_config.score_weights, _UNFILTERED_TEST_SCORING,
            params=selection.selected_params, param_ranges=base_config.param_ranges,
        )

    ts_boundary = pd.Timestamp(fold.effective_boundary)
    ts_test_end = pd.Timestamp(fold.effective_test_end)
    coverage_bars = int(
        ((df["time_paris"] >= ts_boundary) & (df["time_paris"] < ts_test_end)).sum()
    )

    return FoldResult(
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
    )


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
