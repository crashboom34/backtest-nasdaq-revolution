"""
tests/test_walk_forward.py — AF-V-02 Slice 1 : géométrie déterministe Walk-Forward, guards
scientifiques, règle terminale V2.

Contrat de référence : docs/adr/0021-walk-forward-rolling-calendar-v1.md (`Décision` N cité dans
chaque docstring de test qui vérifie un invariant précis de l'ADR), corrigé le 2026-09-15 AVANT
toute implémentation (voir Décisions 1/3/4/6/9/10). `WALK_FORWARD_SEMANTICS_VERSION =
"rolling-calendar-v2"`.

Slice 1 scope strict : géométrie pure (aucun backtest, aucun résultat de performance consulté,
aucune dépendance au nombre de workers), résolution readiness, guards structurels. Aucun
Optimizer/TEST OOS/persistence — voir walk_forward.py pour le détail du découplage.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_split import build_dataset_split_plan, build_split_boundary
from engine import _add_market_time_columns
from strategy_contracts import DailyStateReadiness
from validation_run import (
    VALIDATION_TYPE_WALK_FORWARD,
    AggregateResult,
    FoldDefinition,
    FoldResult,
    FoldSelection,
    WalkForwardEvidence,
    WalkForwardRunOutcome,
    load_validation_run,
    save_validation_run,
)
from walk_forward import (
    WALK_FORWARD_SEMANTICS_VERSION,
    RESUME_ACTION_REDO,
    RESUME_ACTION_REPLAY_TEST,
    RESUME_ACTION_SKIP,
    DatasetTooShortForWalkForward,
    FinalHoldoutOverlapError,
    FoldArtifactConflict,
    FoldArtifacts,
    FoldResumeDecision,
    FoldTestExecutionFailed,
    InsufficientWarmupHistory,
    NoEligibleTrainCandidate,
    NonDeterministicSearchWithoutSeed,
    OosOverlapError,
    UnsupportedWalkForwardGeometry,
    WalkForwardOrphanedFoldArtifacts,
    WalkForwardResumeMismatch,
    WalkForwardSemanticsMismatch,
    build_aggregate_result,
    build_walk_forward_manifest,
    build_walk_forward_specification,
    build_walk_forward_validation_run,
    check_no_final_holdout_overlap,
    check_no_oos_overlap,
    check_resume_fingerprint,
    check_warmup_sufficiency,
    compute_fold_definitions,
    decide_fold_resume_action,
    detect_partial_tail,
    execute_walk_forward_fold,
    execute_walk_forward_fold_with_artifacts,
    persist_walk_forward_run,
    resume_walk_forward_run,
    run_fold_test,
    run_fold_train,
    run_walk_forward,
    select_fold_top1,
    validate_resume_walk_forward_semantics,
)
import walk_forward as walk_forward_module
import optimizer
from optimizer import (
    STATE_READINESS_SEMANTICS_VERSION,
    TRAIN_TEST_SEMANTICS_VERSION,
    FilterConfig,
    NoStateReadyBoundary,
    OptimizationConfig,
    Optimizer,
    ParamRange,
    ScoreWeights,
    TrainTestConfig,
    compute_score,
    params_hash,
)
from market_data.backtest_manifest import build_backtest_manifest, save_backtest_manifest

_BASE_PARAMS = {"or_start_h": 15, "or_start_m": 30, "ema_trend_len": 120}


def _spec(**kwargs):
    kwargs.setdefault("base_params", dict(_BASE_PARAMS))
    return build_walk_forward_specification(**kwargs)


def _readiness(hour=15, minute=30, tz="Europe/Paris"):
    return DailyStateReadiness(latest_safe_start_hour=hour, latest_safe_start_minute=minute, timezone=tz)


def _zone(start, end):
    return build_split_boundary(start, end)


# ═══════════════════════════════════════════════════════════════════════════════
# Specification
# ═══════════════════════════════════════════════════════════════════════════════


def test_rolling_geometry_is_accepted():
    spec = _spec(geometry="rolling")
    assert spec.geometry == "rolling"


def test_anchored_geometry_is_rejected():
    """Décision 1 — Anchored reste FUTURE, jamais une conversion silencieuse."""
    with pytest.raises(UnsupportedWalkForwardGeometry):
        _spec(geometry="anchored")


def test_hybrid_geometry_is_rejected():
    with pytest.raises(UnsupportedWalkForwardGeometry):
        _spec(geometry="hybrid")


def test_step_period_must_equal_test_period():
    """Décision 1/4 — seule condition garantissant des fenêtres TEST contiguës et non
    chevauchantes par construction."""
    with pytest.raises(ValueError):
        _spec(test_period="P6M", step_period="P3M")


def test_allow_partial_last_fold_true_is_rejected_in_v1():
    """Décision 1 — fixé, non paramétrable en V1."""
    with pytest.raises(ValueError):
        _spec(allow_partial_last_fold=True)


def test_specification_records_current_semantics_version():
    spec = _spec()
    assert spec.walk_forward_semantics_version == "rolling-calendar-v2" == WALK_FORWARD_SEMANTICS_VERSION


def test_specification_requires_base_params():
    with pytest.raises(ValueError):
        build_walk_forward_specification(base_params=None)


def test_specification_rejects_empty_base_params():
    """Décision 4 — base_params fige la readiness de TOUS les folds, ne peut pas être vide."""
    with pytest.raises(ValueError):
        build_walk_forward_specification(base_params={})


def test_specification_default_preset_is_p24m_p6m_p6m():
    spec = _spec()
    assert (spec.train_period, spec.test_period, spec.step_period) == ("P24M", "P6M", "P6M")


def test_specification_default_position_transition_policy():
    spec = _spec()
    assert spec.position_transition_policy == "flat_each_fold_v1"


def test_specification_base_params_is_copied_not_aliased():
    """Une mutation du dict appelant ne doit jamais affecter la spec déjà construite (immuabilité
    de fait, même sans frozen sur le dict lui-même)."""
    source = dict(_BASE_PARAMS)
    spec = build_walk_forward_specification(base_params=source)
    source["or_start_h"] = 99
    assert spec.base_params["or_start_h"] == 15


@pytest.mark.parametrize("bad_period", ["24M", "P24D", "P2Y", "P0M", "P-1M", "", None, 24])
def test_period_format_must_be_pnm(bad_period):
    with pytest.raises(ValueError):
        _spec(train_period=bad_period)


# ═══════════════════════════════════════════════════════════════════════════════
# Géométrie — génération des folds
# ═══════════════════════════════════════════════════════════════════════════════


def test_single_fold_exact_fit():
    """VALIDATION dure exactement train_period+test_period : un seul fold, terminal."""
    spec = _spec(train_period="P24M", test_period="P6M", step_period="P6M")
    zone = _zone("2020-01-01T00:00:00+00:00", "2022-07-01T00:00:00+00:00")

    folds = compute_fold_definitions(zone, spec, readiness_spec=None)

    assert len(folds) == 1
    fold = folds[0]
    assert fold.fold_index == 0
    assert fold.is_last_fold is True
    assert fold.train_start == "2020-01-01T00:00:00+00:00"
    assert fold.requested_boundary == "2022-01-01T00:00:00+00:00"
    assert fold.requested_test_end == "2022-07-01T00:00:00+00:00"


def test_multiple_contiguous_folds_exact_fit():
    """36 mois = 24 + 6*2 : exactement 2 folds, zéro reliquat."""
    spec = _spec()
    zone = _zone("2020-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00")

    folds = compute_fold_definitions(zone, spec, readiness_spec=None)

    assert len(folds) == 2
    assert folds[0].is_last_fold is False
    assert folds[1].is_last_fold is True
    assert folds[1].train_start == "2020-07-01T00:00:00+00:00"
    assert detect_partial_tail(zone, spec, n_folds_generated=2) is None


def test_dataset_exactly_sufficient_for_one_fold_does_not_raise():
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T00:00:00+00:00", "2023-03-01T00:00:00+00:00")

    folds = compute_fold_definitions(zone, spec, readiness_spec=None)
    assert len(folds) == 1


def test_dataset_too_short_raises():
    spec = _spec(train_period="P24M", test_period="P6M", step_period="P6M")
    zone = _zone("2020-01-01T00:00:00+00:00", "2020-06-01T00:00:00+00:00")

    with pytest.raises(DatasetTooShortForWalkForward):
        compute_fold_definitions(zone, spec, readiness_spec=None)


def test_partial_tail_is_registered_not_executed():
    """Décision 1/16 — allow_partial_last_fold=False : le reliquat est détectable, jamais un
    fold raccourci. Avec train=test=step=P1M, N folds couvrent (N+1) mois — 4 folds couvrent
    exactement 5 mois (2023-01-01 -> 2023-06-01) ; ajouter 14 jours au-delà laisse un reliquat réel
    trop court pour un 5e fold complet."""
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T00:00:00+00:00", "2023-06-15T00:00:00+00:00")

    folds = compute_fold_definitions(zone, spec, readiness_spec=None)
    assert len(folds) == 4

    tail = detect_partial_tail(zone, spec, n_folds_generated=len(folds))
    assert tail is not None
    assert tail.start == "2023-06-01T00:00:00+00:00"
    assert tail.end == "2023-06-15T00:00:00+00:00"


def test_stopping_condition_exact_boundary():
    """Le fold candidat dont requested_test_end == VALIDATION.end doit être généré (<=, pas <)."""
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T00:00:00+00:00", "2023-03-01T00:00:00+00:00")

    folds = compute_fold_definitions(zone, spec, readiness_spec=None)
    assert len(folds) == 1
    assert folds[0].requested_test_end == zone.end


def test_no_test_overlap_between_folds():
    spec = _spec()
    zone = _zone("2020-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00")
    folds = compute_fold_definitions(zone, spec, readiness_spec=None)
    check_no_oos_overlap(folds)  # ne lève pas


def test_month_length_rollover_end_of_month():
    """31 janvier + 1 mois -> 28 février (année non bissextile) : comportement pandas pinné,
    jamais un calcul de "30 jours fixes"."""
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-31T00:00:00+00:00", "2023-04-30T00:00:00+00:00")

    folds = compute_fold_definitions(zone, spec, readiness_spec=None)
    assert folds[0].requested_boundary == "2023-02-28T00:00:00+00:00"


def test_leap_year_february_29():
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2024-02-29T00:00:00+00:00", "2024-04-29T00:00:00+00:00")

    folds = compute_fold_definitions(zone, spec, readiness_spec=None)
    assert folds[0].requested_boundary == "2024-03-29T00:00:00+00:00"
    assert folds[0].requested_test_end == "2024-04-29T00:00:00+00:00"


def test_year_boundary_crossing():
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-12-01T00:00:00+00:00", "2024-02-01T00:00:00+00:00")

    folds = compute_fold_definitions(zone, spec, readiness_spec=None)
    assert folds[0].requested_boundary == "2024-01-01T00:00:00+00:00"
    assert folds[0].requested_test_end == "2024-02-01T00:00:00+00:00"


def test_geometry_never_calls_engine_or_optimizer_backtest():
    """Fonction pure — aucun accès à un résultat de performance : vérifié en confirmant que le
    module walk_forward n'importe ni engine.run_backtest ni optimizer._run_single."""
    import walk_forward as wf

    assert not hasattr(wf, "run_backtest")
    assert not hasattr(wf, "_run_single")


# ═══════════════════════════════════════════════════════════════════════════════
# Readiness
# ═══════════════════════════════════════════════════════════════════════════════


def test_stateless_strategy_no_adjustment_anywhere():
    spec = _spec()
    zone = _zone("2020-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00")
    folds = compute_fold_definitions(zone, spec, readiness_spec=None)
    for fold in folds:
        assert fold.boundary_adjusted is False
        assert fold.test_end_adjusted is False
        assert fold.effective_boundary == fold.requested_boundary
        assert fold.effective_test_end == fold.requested_test_end


def test_boundary_before_cutoff_is_unchanged():
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T10:00:00+00:00", "2023-04-01T10:00:00+00:00")
    readiness = _readiness(hour=15, minute=30)

    folds = compute_fold_definitions(zone, spec, readiness_spec=readiness)
    for fold in folds:
        assert fold.boundary_adjusted is False


def test_non_terminal_boundary_after_cutoff_is_adjusted():
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T16:00:00+00:00", "2023-05-01T16:00:00+00:00")
    readiness = _readiness(hour=15, minute=30)

    folds = compute_fold_definitions(zone, spec, readiness_spec=readiness)
    assert len(folds) == 3
    # fold 0 et 1 sont non terminaux : leur effective_boundary ET leur effective_test_end
    # doivent être décalés (16:00 UTC == 17h/18h Paris > 15:30).
    assert folds[0].boundary_adjusted is True
    assert folds[0].test_end_adjusted is True
    assert folds[1].boundary_adjusted is True
    assert folds[1].test_end_adjusted is True


def test_base_params_derived_readiness_is_identical_across_all_folds():
    """Décision 4 — un seul readiness_spec (dérivé de base_params) utilisé pour tous les folds,
    jamais un par fold."""
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T16:00:00+00:00", "2023-05-01T16:00:00+00:00")
    readiness = DailyStateReadiness(
        latest_safe_start_hour=spec.base_params["or_start_h"],
        latest_safe_start_minute=spec.base_params["or_start_m"],
        timezone="Europe/Paris",
    )

    folds = compute_fold_definitions(zone, spec, readiness_spec=readiness)
    # Les deux folds non-terminaux subissent exactement le même type de décalage (même règle).
    assert folds[0].boundary_adjusted == folds[1].boundary_adjusted is True


def test_dst_spring_forward_boundary_is_dst_safe():
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    # requested_boundary du fold 0 tombe le 2024-03-30 16:00 UTC (veille du changement d'heure).
    zone = _zone("2024-02-29T16:00:00+00:00", "2024-05-29T16:00:00+00:00")
    readiness = _readiness(hour=15, minute=30)

    folds = compute_fold_definitions(zone, spec, readiness_spec=readiness)
    assert folds[0].requested_boundary == "2024-03-29T16:00:00+00:00"
    # NB: le vrai jour de bascule DST 2024 est le 31 mars ; la frontière ci-dessus (29 mars) ne le
    # touche pas directement — test de robustesse générale du calendrier autour de la période DST,
    # complété par le test dédié ci-dessous qui cible exactement le jour de bascule.


def test_dst_spring_forward_exact_transition_day_is_safe():
    """Cible directement le calcul resolve_state_ready_boundary via la geometry, sur une frontière
    dont le décalage tombe précisément la veille du changement d'heure de printemps (2024-03-31)."""
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2024-02-29T16:00:00+00:00", "2024-04-29T16:00:00+00:00")
    readiness = _readiness(hour=15, minute=30)

    folds = compute_fold_definitions(zone, spec, readiness_spec=readiness)
    assert len(folds) == 1
    # requested_boundary = 2024-03-29T16:00:00+00:00 (Paris local 17:00, > cutoff) -> décalée.
    # Puisque train_period==test_period==step_period=P1M et 1 seul fold, ce fold est TERMINAL :
    # son effective_boundary (interne) EST résolue, son effective_test_end NE L'EST PAS.
    assert folds[0].boundary_adjusted is True
    assert folds[0].effective_boundary == "2024-03-30T00:00:00+01:00"
    assert folds[0].test_end_adjusted is False
    assert folds[0].effective_test_end == folds[0].requested_test_end


def test_dst_fall_back_boundary_is_dst_safe():
    """Frontière interne (non-terminale) dont le décalage tombe précisément la veille du
    changement d'heure d'automne (2024-10-27)."""
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2024-09-26T16:00:00+00:00", "2024-12-26T16:00:00+00:00")
    readiness = _readiness(hour=15, minute=30)

    folds = compute_fold_definitions(zone, spec, readiness_spec=readiness)
    assert len(folds) == 2
    # fold 0 non terminal : requested_boundary = 2024-10-26T16:00:00+00:00 (Paris local 18:00
    # CEST, > cutoff) -> décalée au minuit local DST-safe du 2024-10-27.
    assert folds[0].boundary_adjusted is True
    assert folds[0].effective_boundary == "2024-10-27T00:00:00+02:00"


# ═══════════════════════════════════════════════════════════════════════════════
# Règle terminale V2 (correction du 2026-09-15) — critique
# ═══════════════════════════════════════════════════════════════════════════════


def test_terminal_test_end_is_never_adjusted_even_after_cutoff():
    """LE test de non-régression du blocker corrigé : sans le correctif, ce test échouerait
    (effective_test_end du dernier fold serait décalé vers/au-delà de FINAL_HOLDOUT)."""
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T16:00:00+00:00", "2023-03-01T16:00:00+00:00")
    readiness = _readiness(hour=15, minute=30)

    folds = compute_fold_definitions(zone, spec, readiness_spec=readiness)
    assert len(folds) == 1
    last = folds[0]
    assert last.is_last_fold is True
    assert last.effective_test_end == last.requested_test_end == zone.end
    assert last.test_end_adjusted is False


def test_terminal_internal_boundary_is_still_readiness_resolved():
    """Seule la borne de FIN du dernier fold est exemptée — sa frontière TRAIN/TEST interne reste
    résolue normalement (Décision 3/4)."""
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T16:00:00+00:00", "2023-03-01T16:00:00+00:00")
    readiness = _readiness(hour=15, minute=30)

    folds = compute_fold_definitions(zone, spec, readiness_spec=readiness)
    last = folds[0]
    assert last.boundary_adjusted is True
    assert last.effective_boundary != last.requested_boundary


def test_non_terminal_fold_test_end_is_still_adjusted_when_after_cutoff():
    """Contraste direct avec la règle terminale : un fold NON terminal reste normalement ajusté."""
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T16:00:00+00:00", "2023-04-01T16:00:00+00:00")
    readiness = _readiness(hour=15, minute=30)

    folds = compute_fold_definitions(zone, spec, readiness_spec=readiness)
    assert folds[0].is_last_fold is False
    assert folds[0].test_end_adjusted is True
    assert folds[0].effective_test_end != folds[0].requested_test_end


# ═══════════════════════════════════════════════════════════════════════════════
# Half-open / continuité — aucune frontière commune incluse deux fois
# ═══════════════════════════════════════════════════════════════════════════════


def test_effective_test_end_never_exceeds_validation_end():
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T16:00:00+00:00", "2023-04-01T16:00:00+00:00")
    readiness = _readiness(hour=15, minute=30)

    folds = compute_fold_definitions(zone, spec, readiness_spec=readiness)
    for fold in folds:
        assert pd.Timestamp(fold.effective_test_end) <= pd.Timestamp(zone.end)


def test_shared_boundary_never_duplicated_between_adjacent_folds():
    """effective_test_end_k == effective_boundary_(k+1) pour tout k < N — dérivé par
    déterminisme (Décision 4), vérifié directement sur l'implémentation, pas seulement supposé."""
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T16:00:00+00:00", "2023-05-01T16:00:00+00:00")
    readiness = _readiness(hour=15, minute=30)

    folds = compute_fold_definitions(zone, spec, readiness_spec=readiness)
    assert len(folds) == 3
    for k in range(len(folds) - 1):
        assert folds[k].effective_test_end == folds[k + 1].effective_boundary


def test_shared_boundary_holds_even_with_day_of_month_clamping_and_non_multiple_of_12_train_period():
    """Trouvaille /code-review (revue scientifique de cette mission) : `train_period` non multiple
    de 12 mois + `VALIDATION.start` sur un jour de fin de mois (31) exerçait un clampage de date
    différent selon que la borne était calculée en chaînant les additions (train_start+train,
    PUIS +test) ou en un seul saut depuis VALIDATION.start — cassant le théorème "garanti par
    construction" de la Décision 4 (`(d+1mo)+3mo` peut différer de `d+4mo`, reproduit
    empiriquement : 2023-01-31 chaîné -> 2023-05-28, direct -> 2023-05-31). Corrigé en calculant
    CHAQUE borne comme un unique saut depuis `VALIDATION.start`. Ce test aurait échoué (assertion
    violée, potentiellement `OosOverlapError`) avant le correctif."""
    spec = _spec(train_period="P1M", test_period="P3M", step_period="P3M")
    zone = _zone("2023-01-31T00:00:00+00:00", "2023-12-31T00:00:00+00:00")

    folds = compute_fold_definitions(zone, spec, readiness_spec=None)
    assert len(folds) >= 2
    for k in range(len(folds) - 1):
        assert folds[k].requested_test_end == folds[k + 1].requested_boundary
        assert folds[k].effective_test_end == folds[k + 1].effective_boundary
    check_no_oos_overlap(folds)  # ne lève pas


def test_check_no_oos_overlap_raises_on_manually_constructed_violation():
    """Garde défensive interne — devrait être impossible via compute_fold_definitions(), testée
    directement en contournant la construction normale (Décision 11 : "filet de sécurité testé")."""
    fold_a = FoldDefinition(
        fold_index=0, fold_id="fold_000",
        train_start="2023-01-01T00:00:00+00:00",
        requested_boundary="2023-02-01T00:00:00+00:00", effective_boundary="2023-02-01T00:00:00+00:00",
        boundary_adjusted=False,
        requested_test_end="2023-03-01T00:00:00+00:00", effective_test_end="2023-03-05T00:00:00+00:00",
        test_end_adjusted=True, is_last_fold=False,
    )
    fold_b = FoldDefinition(
        fold_index=1, fold_id="fold_001",
        train_start="2023-02-01T00:00:00+00:00",
        requested_boundary="2023-03-01T00:00:00+00:00", effective_boundary="2023-03-01T00:00:00+00:00",
        boundary_adjusted=False,
        requested_test_end="2023-04-01T00:00:00+00:00", effective_test_end="2023-04-01T00:00:00+00:00",
        test_end_adjusted=False, is_last_fold=True,
    )
    with pytest.raises(OosOverlapError):
        check_no_oos_overlap((fold_a, fold_b))


# ═══════════════════════════════════════════════════════════════════════════════
# FINAL_HOLDOUT
# ═══════════════════════════════════════════════════════════════════════════════


def test_validation_ending_before_holdout_start_is_accepted():
    validation_zone = _zone("2020-01-01T00:00:00+00:00", "2022-01-01T00:00:00+00:00")
    holdout_zone = _zone("2022-06-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00")
    check_no_final_holdout_overlap(validation_zone, holdout_zone)  # ne lève pas


def test_validation_ending_exactly_at_holdout_start_is_accepted():
    """[start,end) : VALIDATION.end == FINAL_HOLDOUT.start est une adjacence valide, jamais un
    chevauchement."""
    validation_zone = _zone("2020-01-01T00:00:00+00:00", "2022-01-01T00:00:00+00:00")
    holdout_zone = _zone("2022-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00")
    check_no_final_holdout_overlap(validation_zone, holdout_zone)  # ne lève pas


def test_overlap_between_validation_and_final_holdout_is_rejected():
    validation_zone = _zone("2020-01-01T00:00:00+00:00", "2022-06-01T00:00:00+00:00")
    holdout_zone = _zone("2022-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00")
    with pytest.raises(FinalHoldoutOverlapError):
        check_no_final_holdout_overlap(validation_zone, holdout_zone)


def test_synthetic_timestamp_exactly_at_holdout_start_is_never_the_test_end_of_a_non_terminal_fold():
    """Le dernier fold généré, quand VALIDATION.end == FINAL_HOLDOUT.start, a
    effective_test_end == FINAL_HOLDOUT.start — jamais au-delà (demi-ouvert : cet instant précis
    n'est jamais consommé par le TEST du Walk-Forward, il appartient à FINAL_HOLDOUT)."""
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    validation_zone = _zone("2023-01-01T00:00:00+00:00", "2023-03-01T00:00:00+00:00")
    holdout_zone = _zone("2023-03-01T00:00:00+00:00", "2023-06-01T00:00:00+00:00")

    check_no_final_holdout_overlap(validation_zone, holdout_zone)
    folds = compute_fold_definitions(validation_zone, spec, readiness_spec=None)
    last = folds[-1]
    assert last.effective_test_end == holdout_zone.start


def test_walk_forward_module_never_creates_a_holdout_access_event():
    """Le fonctionnement normal Walk-Forward ne doit jamais créer de HoldoutAccessEvent — vérifié
    en confirmant que le module ne l'importe même pas."""
    import walk_forward as wf

    assert not hasattr(wf, "HoldoutAccessEvent")
    assert not hasattr(wf, "build_holdout_access_event")


# ═══════════════════════════════════════════════════════════════════════════════
# Warmup causal
# ═══════════════════════════════════════════════════════════════════════════════


def test_insufficient_warmup_history_raises():
    with pytest.raises(InsufficientWarmupHistory):
        check_warmup_sufficiency(bars_available_before_first_fold=100, required_warmup_bars=282)


def test_sufficient_warmup_history_does_not_raise():
    check_warmup_sufficiency(bars_available_before_first_fold=1000, required_warmup_bars=282)


def test_exact_warmup_history_boundary_does_not_raise():
    check_warmup_sufficiency(bars_available_before_first_fold=282, required_warmup_bars=282)


# ═══════════════════════════════════════════════════════════════════════════════
# Fold IDs — identité déterministe
# ═══════════════════════════════════════════════════════════════════════════════


def test_fold_ids_are_deterministic_across_calls():
    spec = _spec()
    zone = _zone("2020-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00")

    folds_a = compute_fold_definitions(zone, spec, readiness_spec=None)
    folds_b = compute_fold_definitions(zone, spec, readiness_spec=None)

    assert [f.fold_id for f in folds_a] == [f.fold_id for f in folds_b]


def test_fold_ids_follow_stable_naming_and_order():
    spec = _spec()
    zone = _zone("2020-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00")
    folds = compute_fold_definitions(zone, spec, readiness_spec=None)
    assert [f.fold_id for f in folds] == ["fold_000", "fold_001"]
    assert [f.fold_index for f in folds] == [0, 1]


# ═══════════════════════════════════════════════════════════════════════════════
# NoStateReadyBoundary — réutilisation comme TYPE, message contextualisé par fold
# ═══════════════════════════════════════════════════════════════════════════════


def test_collapsed_boundary_raises_no_state_ready_boundary_with_fold_context(monkeypatch):
    """Décision 11 — réutilisation du TYPE, jamais du message générique verbatim : le message doit
    mentionner le fold concerné. Un collapse réel est structurellement quasi impossible avec des
    périodes en mois entiers et un décalage readiness borné à ~24h (c'est précisément pourquoi
    l'ADR qualifie ce garde de "défensif") : ce test force le collapse directement en
    monkeypatchant `resolve_state_ready_boundary` (tel qu'importé dans walk_forward), plutôt que de
    chercher une géométrie réaliste qui ne peut pas exister — même technique déjà établie ailleurs
    dans ce dépôt pour tester un garde défensif (monkeypatch `compute_score`, `optimizer.py`)."""
    import walk_forward as wf
    from strategy_contracts import StateReadinessResolution

    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T00:00:00+00:00", "2023-03-01T00:00:00+00:00")

    def _fake_resolve(requested_boundary, readiness_spec):
        # Fold unique (dernier ET premier) : seul effective_boundary passe par cette fonction
        # (effective_test_end du dernier fold est désormais exempté par construction, règle
        # terminale V2). Le forcer au-delà de requested_test_end réel (2023-03-01) suffit donc à
        # provoquer le collapse train_start < effective_boundary < effective_test_end.
        return StateReadinessResolution(
            requested_boundary=requested_boundary,
            effective_boundary="2023-03-15T00:00:00+00:00",
            adjusted=True,
        )

    monkeypatch.setattr(wf, "resolve_state_ready_boundary", _fake_resolve)

    with pytest.raises(NoStateReadyBoundary) as excinfo:
        compute_fold_definitions(zone, spec, readiness_spec=_readiness())
    assert "fold_" in str(excinfo.value)


# ═══════════════════════════════════════════════════════════════════════════════
# Reprise cross-version — WalkForwardSemanticsMismatch
# ═══════════════════════════════════════════════════════════════════════════════


def test_resume_guard_is_noop_when_current_run_is_not_walk_forward():
    validate_resume_walk_forward_semantics(False, None, "run_x")  # ne lève pas


def test_resume_guard_rejects_missing_source_version_as_legacy():
    with pytest.raises(WalkForwardSemanticsMismatch):
        validate_resume_walk_forward_semantics(True, {}, "run_x")


def test_resume_guard_rejects_mismatched_version():
    with pytest.raises(WalkForwardSemanticsMismatch):
        validate_resume_walk_forward_semantics(
            True, {"walk_forward_semantics_version": "rolling-calendar-v1"}, "run_x",
        )


def test_resume_guard_accepts_matching_version():
    validate_resume_walk_forward_semantics(
        True, {"walk_forward_semantics_version": "rolling-calendar-v2"}, "run_x",
    )  # ne lève pas


# ═══════════════════════════════════════════════════════════════════════════════
# Découplage / absence de dépendance circulaire
# ═══════════════════════════════════════════════════════════════════════════════


def test_walk_forward_module_does_not_import_engine():
    import walk_forward as wf
    assert not hasattr(wf, "run_backtest")


def test_validation_run_module_does_not_import_walk_forward():
    """Sens de dépendance imposé par l'ADR 0021 Décision 2 : walk_forward.py -> validation_run.py,
    jamais l'inverse (évite tout import circulaire)."""
    import validation_run as vr
    assert not hasattr(vr, "compute_fold_definitions")
    assert not hasattr(vr, "build_walk_forward_specification")


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 2 — Optimizer TRAIN-only + sélection Top-1 + exécution TEST par fold
# (ADR 0021 Décisions 4/6/7). Stratégie et DataFrame 100% synthétiques (même discipline que
# test_optimizer.py) ; le moteur réel (`engine.run_backtest`) est monkeypatché pour verrouiller
# QUELLES bornes/QUEL ORDRE d'appels TRAIN/TEST sont produits, sans dépendre d'une stratégie réelle
# générant des trades.
# ═══════════════════════════════════════════════════════════════════════════════


def _build_synthetic_wf_df(n_bars, start="2020-01-01T00:00:00", freq_minutes=1440):
    times = pd.date_range(start, periods=n_bars, freq=f"{freq_minutes}min")
    price = 100.0 + pd.Series(range(n_bars), dtype=float) * 0.01
    raw = pd.DataFrame({
        "time":  times,
        "open":  price.values,
        "high":  (price + 0.5).values,
        "low":   (price - 0.5).values,
        "close": price.values,
    })
    return _add_market_time_columns(raw)


def _minimal_optimizer_config(**overrides):
    from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
    defaults = dict(
        run_id="wf_fold_test",
        strategy_module="strategies.perfect_revolution_v1",
        strategy_name="test",
        data_file="unused.csv",
        base_params=dict(DEFAULT_PARAMS),
        param_ranges=[],
        mode="grid",
        score_weights=ScoreWeights(),
        filters=FilterConfig(),
        train_test=TrainTestConfig(),
        global_params={},
        n_workers=1,
    )
    defaults.update(overrides)
    return OptimizationConfig(**defaults)


def _param_ranges_3_values():
    return [ParamRange(
        name="ema_trend_len", param_type="number", label="x",
        min_val=100, max_val=140, step=20,
    )]


def _wf_fold(train_start, boundary, test_end, index=0, is_last=True):
    fold_id = f"fold_{index:03d}"
    return FoldDefinition(
        fold_index=index, fold_id=fold_id,
        train_start=train_start,
        requested_boundary=boundary, effective_boundary=boundary, boundary_adjusted=False,
        requested_test_end=test_end, effective_test_end=test_end, test_end_adjusted=False,
        is_last_fold=is_last,
    )


def _same_instant(iso_a, iso_b):
    return pd.Timestamp(iso_a, tz="Europe/Paris") == pd.Timestamp(iso_b, tz="Europe/Paris")


def _fold_selection(fold, params=None):
    params = params if params is not None else {"ema_trend_len": 140}
    return FoldSelection(
        fold_id=fold.fold_id,
        selected_params=dict(params),
        selected_params_hash=params_hash(params),
        score_train=1.4,
        rank_in_train=1,
        train_candidates_evaluated=3,
        train_candidates_unique=3,
        train_candidates_eligible=3,
        search_space_hash="deadbeef",
        algorithm="grid",
        fold_seed=None,
    )


class _ScoreByParamRunBacktest:
    """Faux `engine.run_backtest()` déterministe : score proportionnel à
    `params['ema_trend_len']` (via `compute_score()` monkeypatché sur `net_ret_pct`) — permet de
    savoir à coup sûr quel candidat doit gagner TRAIN. Enregistre l'ORDRE et les bornes exactes de
    chaque appel : utilisé pour prouver l'isolation TEST structurelle (Décision 7), aucun appel
    TEST ne devant précéder la sélection Top-1."""

    def __init__(self):
        self.calls = []

    def __call__(self, df, strategy, params, **kwargs):
        self.calls.append({
            "params":       dict(params),
            "start_date":   kwargs.get("start_date"),
            "end_date":     kwargs.get("end_date"),
            # Pas de défaut ambigu : un appel qui omettrait `end_boundary` doit se voir
            # attribuer ce sentinelle et non une valeur plausible ("inclusive"), pour que
            # `test_train_calls_always_use_inclusive_end_boundary` détecte une régression où
            # la production cesserait de le transmettre explicitement (finding MAJEUR, review
            # indépendante tentative 1).
            "end_boundary": kwargs.get("end_boundary", "__END_BOUNDARY_NOT_PASSED__"),
        })
        net_ret = params.get("ema_trend_len", 0) / 100.0
        trades = pd.DataFrame([{"resultat_net": 10.0, "raison_sortie": "fin-donnees"}])
        equity = pd.DataFrame([{"date": "2020-01-01", "capital": 10_000.0 + net_ret}])
        return trades, equity, {"n_trades": 1, "net_ret_pct": net_ret}


def _patch_score_by_net_ret(monkeypatch):
    monkeypatch.setattr(
        "optimizer.compute_score",
        lambda stats, *a, **k: (stats.get("net_ret_pct", 0.0), False, None, []),
    )


class TestRunFoldTrain:
    """ADR 0021 Décision 6 — Optimizer.run(run_test_validation=False), train_test.enabled=False,
    fenêtre bornée EXACTEMENT à [fold.train_start, fold.effective_boundary)."""

    def test_train_only_never_executes_a_backtest_touching_the_test_window(self, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        all_results, _sensitivity = run_fold_train(fold, config, df)

        assert fake.calls, "au moins un backtest TRAIN attendu"
        for call in fake.calls:
            assert pd.Timestamp(call["end_date"], tz="Europe/Paris") < pd.Timestamp(
                fold.effective_boundary)

    def test_train_calls_always_use_inclusive_end_boundary(self, monkeypatch):
        """Régression review indépendante (tentative 2, finding MAJEUR) : rien ne verrouillait
        `end_boundary="inclusive"` côté TRAIN — un futur refactor qui ferait passer
        `end_boundary_for_optimization` à `"exclusive"` pour le chemin `train_test.enabled=False`
        (optimizer.py, ~ligne 1017) perdrait silencieusement la dernière bougie de
        `[train_start, effective_boundary)` sans qu'aucun test ne le détecte. Miroir exact de
        l'assertion `end_boundary == "exclusive"` déjà présente côté TestRunFoldTest pour TEST."""
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        run_fold_train(fold, config, df)

        assert fake.calls, "au moins un backtest TRAIN attendu"
        for call in fake.calls:
            assert call["end_boundary"] == "inclusive"

    def test_train_results_are_sorted_best_score_first(self, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        all_results, _sensitivity = run_fold_train(fold, config, df)

        assert all_results[0]["params"]["ema_trend_len"] == 140

    def test_train_uses_the_full_search_space_declared_by_the_config(self, monkeypatch):
        """Décision 14 — chaque fold repart du search space complet, jamais réduit par un fold
        antérieur : trois combinaisons déclarées -> trois candidats évalués."""
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        all_results, _sensitivity = run_fold_train(fold, config, df)

        assert len(all_results) == 3

    def test_max_rows_inherited_from_base_config_never_truncates_the_train_window(
        self, monkeypatch,
    ):
        """Régression review indépendante (tentative 1, finding MAJEUR) : la docstring de
        run_fold_train() promet une fenêtre TRAIN bornée EXACTEMENT à [fold.train_start,
        fold.effective_boundary), mais `base_config.max_rows` était hérité tel quel dans
        `dataclasses.replace()`. `optimizer.resolve_execution_window()` applique `max_rows` APRÈS
        le filtrage par dates (optimizer.py) et tronque silencieusement `execution_df`/le
        `context_df` transmis à `run_backtest()` si `max_rows` est plus petit que la fenêtre
        réellement demandée — aucune exception, aucun avertissement. run_fold_train() doit
        neutraliser `max_rows` pour garantir la fenêtre exacte documentée, quel que soit le preset
        hérité par `base_config` (ex. quick_validation_mode)."""
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        seen_df_lengths = []

        def fake_run_backtest(df_, strategy, params, **kwargs):
            seen_df_lengths.append(len(df_))
            trades = pd.DataFrame([{"resultat_net": 10.0, "raison_sortie": "fin-donnees"}])
            equity = pd.DataFrame([{"date": "2020-01-01", "capital": 10_010.0}])
            return trades, equity, {"n_trades": 1, "net_ret_pct": 0.1}

        import engine
        monkeypatch.setattr(engine, "run_backtest", fake_run_backtest)
        config = _minimal_optimizer_config(
            mode="grid", param_ranges=_param_ranges_3_values(), max_rows=10,
        )

        run_fold_train(fold, config, df)

        assert seen_df_lengths, "au moins un backtest TRAIN attendu"
        # [train_start, effective_boundary) == barres d'indices 0..99 == 100 barres. Si max_rows=10
        # hérité de base_config n'était pas neutralisé, chaque appel ne verrait que 10 barres.
        assert min(seen_df_lengths) == 100, (
            f"la fenêtre TRAIN complète (100 barres) a été tronquée à {min(seen_df_lengths)} — "
            "base_config.max_rows ne doit jamais réduire silencieusement [train_start, "
            "effective_boundary)"
        )


class TestSelectFoldTop1:

    def test_selects_the_best_scoring_train_candidate(self):
        fold = _wf_fold(
            train_start="2020-01-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )
        config = _minimal_optimizer_config(param_ranges=_param_ranges_3_values())
        all_results = [
            {"score": 1.4, "params": {"ema_trend_len": 140}},
            {"score": 1.2, "params": {"ema_trend_len": 120}},
            {"score": 1.0, "params": {"ema_trend_len": 100}},
        ]

        selection = select_fold_top1(fold, all_results, config)

        assert selection.fold_id == fold.fold_id
        assert selection.selected_params == {"ema_trend_len": 140}
        assert selection.selected_params_hash == params_hash({"ema_trend_len": 140})
        assert selection.score_train == 1.4
        assert selection.rank_in_train == 1
        assert selection.train_candidates_evaluated == 3
        assert selection.train_candidates_eligible == 3

    def test_all_zero_trade_candidates_raises_no_eligible_train_candidate(self):
        fold = _wf_fold(
            train_start="2020-01-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )
        config = _minimal_optimizer_config()
        all_results = [
            {"score": 0.0, "params": {"ema_trend_len": 140}},
            {"score": 0.0, "params": {"ema_trend_len": 100}},
        ]

        with pytest.raises(NoEligibleTrainCandidate):
            select_fold_top1(fold, all_results, config)

    def test_no_candidates_at_all_raises_no_eligible_train_candidate(self):
        fold = _wf_fold(
            train_start="2020-01-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )
        config = _minimal_optimizer_config()

        with pytest.raises(NoEligibleTrainCandidate):
            select_fold_top1(fold, [], config)


class TestRunFoldTest:

    def test_executes_exactly_one_backtest_bounded_to_the_test_window(self, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = _minimal_optimizer_config()
        selection = _fold_selection(fold)

        result = run_fold_test(fold, selection, config, df)

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert _same_instant(call["start_date"], fold.effective_boundary)
        assert _same_instant(call["end_date"], fold.effective_test_end)
        assert call["end_boundary"] == "exclusive"
        assert call["params"] == selection.selected_params
        assert isinstance(result, FoldResult)

    def test_builds_fold_result_from_the_real_trades_and_equity(self, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[110].isoformat(),
        )
        trades = pd.DataFrame([
            {"resultat_net": 10.0, "raison_sortie": "target"},
            {"resultat_net": -4.0, "raison_sortie": "stop"},
            {"resultat_net": 2.0, "raison_sortie": "fin-donnees"},
        ])
        equity = pd.DataFrame([{"date": "x", "capital": 10_008.0}])
        stats = {
            "n_trades": 3, "net_ret_pct": 0.08, "max_dd_pct": 1.5,
            "profit_factor": 2.1, "win_rate": 66.7,
        }

        def fake_run_backtest(df_, strategy, params, **kwargs):
            return trades, equity, stats

        import engine
        monkeypatch.setattr(engine, "run_backtest", fake_run_backtest)
        config = _minimal_optimizer_config()
        selection = _fold_selection(fold)

        result = run_fold_test(fold, selection, config, df)

        assert result.fold_id == fold.fold_id
        assert result.definition == fold
        assert result.selection == selection
        assert result.n_trades == 3
        assert result.net_ret_pct == 0.08
        assert result.max_dd_pct == 1.5
        assert result.profit_factor == 2.1
        assert result.win_rate == 66.7
        assert result.expectancy == pytest.approx((10.0 - 4.0 + 2.0) / 3)
        assert result.forced_closes == 1
        assert result.zero_trade_oos is False
        assert result.coverage_bars == 10  # indices 100..109 : [boundary, test_end)

    def test_zero_trade_test_produces_the_adr_mandated_observation_fields(self, monkeypatch):
        """Décision 15 — zéro trade TEST est une observation scientifique valide, jamais une
        erreur : n_trades=0, net_ret_pct=0, profit_factor/win_rate/expectancy=None."""
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[110].isoformat(),
        )
        empty_trades, empty_equity = pd.DataFrame(), pd.DataFrame()

        import engine
        monkeypatch.setattr(
            engine, "run_backtest",
            lambda *a, **k: (empty_trades, empty_equity, {"n_trades": 0}),
        )
        config = _minimal_optimizer_config()
        selection = _fold_selection(fold)

        result = run_fold_test(fold, selection, config, df)

        assert result.zero_trade_oos is True
        assert result.n_trades == 0
        assert result.net_ret_pct == 0
        assert result.profit_factor is None
        assert result.win_rate is None
        assert result.expectancy is None
        assert result.max_dd_pct is None
        assert result.score_test == 0.0
        assert result.forced_closes == 0

    def test_score_test_is_never_silently_zeroed_by_a_train_oriented_eligibility_filter(
        self, monkeypatch,
    ):
        """Régression review indépendante (tentative 2, finding BLOQUANT) : `FilterConfig`
        (`min_trades`/`max_drawdown_pct`/`min_profit_factor`/`max_consecutive_losses`/
        `min_win_rate`) est une convention d'ÉLIGIBILITÉ TRAIN — appliquée telle quelle à
        l'UNIQUE exécution TEST d'un fold via `optimizer._run_single()`, elle collapsait
        silencieusement `score_test` à 0.0 dès qu'un seuil TRAIN était franchi, même avec des
        trades réels et des métriques saines. Reproduit empiriquement le cas du finding : 3
        trades, PF=2.1, win_rate=66.7%, net_ret_pct=0.08 (tous des chiffres sains) avec
        `FilterConfig()` par défaut (`min_trades=30 > 3`) — `score_test` doit refléter le score
        pondéré RÉEL de `compute_score()` sur ces `stats`, jamais un 0.0 emprunté au filtre
        d'éligibilité TRAIN (ADR 0021 Décision 13 : "FoldResult ne porte que des faits mesurés")."""
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[110].isoformat(),
        )
        trades = pd.DataFrame([
            {"resultat_net": 10.0, "raison_sortie": "target"},
            {"resultat_net": -4.0, "raison_sortie": "stop"},
            {"resultat_net": 2.0, "raison_sortie": "fin-donnees"},
        ])
        equity = pd.DataFrame([{"date": "x", "capital": 10_008.0}])
        stats = {
            "n_trades": 3, "net_ret_pct": 0.08, "max_dd_pct": 1.5,
            "profit_factor": 2.1, "win_rate": 66.7,
        }

        def fake_run_backtest(df_, strategy, params, **kwargs):
            return trades, equity, stats

        import engine
        monkeypatch.setattr(engine, "run_backtest", fake_run_backtest)
        # FilterConfig() par défaut : min_trades=30, largement au-dessus des 3 trades réels —
        # is_filtered_out() renverrait filtered=True sur ce seul critère, alors que PF/win_rate
        # sont sains.
        config = _minimal_optimizer_config(filters=FilterConfig())
        selection = _fold_selection(fold)

        result = run_fold_test(fold, selection, config, df)

        permissive_filters = FilterConfig(
            min_trades=0, max_drawdown_pct=float("inf"), min_profit_factor=0.0,
            max_consecutive_losses=2**31 - 1, min_win_rate=0.0,
        )
        expected_score, expected_filtered, _reason, _warnings = compute_score(
            stats, config.score_weights, permissive_filters,
            params=selection.selected_params, param_ranges=config.param_ranges,
        )
        assert expected_filtered is False
        assert expected_score > 0.0
        assert result.score_test == pytest.approx(expected_score)
        assert result.score_test > 0.0
        assert result.n_trades == 3
        assert result.profit_factor == 2.1

    def test_technical_exception_during_test_execution_is_never_reported_as_zero_trade(
        self, monkeypatch,
    ):
        """Régression review indépendante (tentative 1, finding MAJEUR) : une exception technique
        levée par `engine.run_backtest()` est absorbée par `optimizer._run_single()` sous la forme
        `filtered=True, filter_reason="Exception: ..."`, `stats={}` — ce qui satisfait
        `n_trades == 0` EXACTEMENT comme un authentique "Aucun trade". Les deux cas ne doivent
        jamais produire le même `FoldResult(zero_trade_oos=True)` (ADR 0021 Décision 15) : un
        échec technique de l'UNIQUE exécution TEST d'un fold doit se propager, jamais être
        traduit silencieusement en observation scientifique."""
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[110].isoformat(),
        )

        def boom(*a, **k):
            raise ValueError("colonne manquante")

        import engine
        monkeypatch.setattr(engine, "run_backtest", boom)
        config = _minimal_optimizer_config()
        selection = _fold_selection(fold)

        with pytest.raises(FoldTestExecutionFailed):
            run_fold_test(fold, selection, config, df)


class TestExecuteWalkForwardFold:

    def test_test_execution_happens_strictly_after_all_train_calls(self, monkeypatch):
        """Décision 7 — isolation TEST structurelle : aucun appel TEST ne doit précéder la
        sélection Top-1. Prouvé ici en vérifiant que le SEUL appel TEST est le DERNIER de la
        séquence enregistrée (3 candidats TRAIN + exactement 1 exécution TEST = 4 appels)."""
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        result = execute_walk_forward_fold(fold, config, df)

        assert len(fake.calls) == 4
        test_calls = [
            c for c in fake.calls if _same_instant(c["start_date"], fold.effective_boundary)
        ]
        assert len(test_calls) == 1
        assert fake.calls[-1] is test_calls[0]
        assert result.selection.selected_params["ema_trend_len"] == 140
        assert isinstance(result, FoldResult)

    def test_no_eligible_train_candidate_propagates_before_any_test_call(self, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        monkeypatch.setattr(
            "optimizer.compute_score", lambda *a, **k: (0.0, True, "filtré", []))
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        with pytest.raises(NoEligibleTrainCandidate):
            execute_walk_forward_fold(fold, config, df)

        # Les 3 candidats TRAIN ont bien été évalués (nécessaire pour établir qu'aucun n'est
        # éligible) — mais aucun appel TEST (start_date == effective_boundary) n'a eu lieu.
        assert len(fake.calls) == 3
        assert not [
            c for c in fake.calls if _same_instant(c["start_date"], fold.effective_boundary)
        ], "aucun appel TEST ne doit avoir lieu quand aucun candidat TRAIN n'est éligible"


class TestAdjacentFoldsShareTheBoundaryExactlyInTheImplementation:
    """Régression directe sur l'IMPLÉMENTATION (pas seulement la géométrie pure déjà couverte par
    Slice 1) : aucune barre TEST perdue/dupliquée entre deux folds adjacents réellement exécutés
    via execute_walk_forward_fold() (ADR 0021 Décision 4)."""

    def test_fold_k_test_end_equals_fold_k_plus_1_train_start_in_the_actual_calls(
        self, monkeypatch,
    ):
        df = _build_synthetic_wf_df(300)
        fold_0 = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
            index=0, is_last=False,
        )
        fold_1 = _wf_fold(
            train_start=df["time_paris"].iloc[50].isoformat(),
            boundary=df["time_paris"].iloc[150].isoformat(),
            test_end=df["time_paris"].iloc[200].isoformat(),
            index=1, is_last=True,
        )
        assert fold_0.effective_test_end == fold_1.effective_boundary  # rappel géométrie Slice 1

        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        execute_walk_forward_fold(fold_0, config, df)
        n_calls_after_fold0 = len(fake.calls)
        execute_walk_forward_fold(fold_1, config, df)

        fold0_test_call = fake.calls[n_calls_after_fold0 - 1]  # dernier appel de fold_0 = TEST
        fold1_test_calls = [
            c for c in fake.calls[n_calls_after_fold0:]
            if _same_instant(c["start_date"], fold_1.effective_boundary)
        ]
        assert len(fold1_test_calls) == 1
        # Aucune barre dupliquée : fold_0 TEST se termine (exclusif) exactement là où fold_1 TEST
        # démarre (inclusif) — même instant partagé, aucun trou, aucun recouvrement (Décision 4).
        assert _same_instant(fold0_test_call["end_date"], fold_1.effective_boundary)
        assert _same_instant(fold1_test_calls[0]["start_date"], fold_0.effective_test_end)


class TestFoldOrchestrationAlwaysOverridesRunTestValidationDefault:

    def test_run_fold_train_always_passes_run_test_validation_false_to_optimizer_run(
        self, monkeypatch,
    ):
        """Non-régression explicite (mission AF-V-02 Slice 2, preuve de complétion) :
        run_fold_train() doit systématiquement appeler Optimizer.run(run_test_validation=False)
        — jamais laisser le défaut True, qui romprait l'isolation TEST (Décision 7).

        Espionne directement `Optimizer.run` plutôt que d'inférer l'effet via
        `train_test.enabled` (déjà forcé à `False` par ailleurs dans ce chemin d'appel — un test
        basé sur l'absence d'appel TEST resterait vert même si `run_test_validation=False` était
        purement et simplement supprimé de l'appel, review indépendante tentative 1). En espionnant
        les kwargs réels transmis à `Optimizer.run`, la suppression de cet argument (ou son
        remplacement par `True`) fait échouer CE test, peu importe la valeur de `train_test.enabled`."""
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        captured_kwargs = {}
        real_run = Optimizer.run

        def spy_run(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
            return real_run(self, *args, **kwargs)

        monkeypatch.setattr(Optimizer, "run", spy_run)

        run_fold_train(fold, config, df)

        assert "run_test_validation" in captured_kwargs, (
            "run_fold_train() doit transmettre explicitement run_test_validation à "
            "Optimizer.run() — jamais compter sur son défaut"
        )
        assert captured_kwargs["run_test_validation"] is False


class TestRunFoldTrainRefusesNonDeterministicSearchWithoutSeed:
    """ADR 0021 Décisions 9/11, régression review indépendante (tentative 2, finding MAJEUR) : la
    Décision 9 affirme que `master_seed`/`fold_seed` sont "sans objet" pour les modes actuellement
    supportés par `optimizer.py` ("tous déterministes") — affirmation FACTUELLEMENT INCORRECTE :
    mode="general" avec 50 000 < N candidats déclarés <= 500 000 dispatche vers
    `optimizer._run_stratified_sample()`, qui tire ses combinaisons via `random.choice()` GLOBAL,
    non-seedé nulle part dans `optimizer.py`. `run_fold_train()` doit refuser ce cas SANS
    `fold_seed` (jamais produire silencieusement un Top-1 non-reproductible), et transmettre
    réellement le `fold_seed` fourni à `Optimizer.run(seed=...)` quand il existe (pas seulement
    contourner le garde — le seed doit réellement seeder le tirage, voir TestStratifiedSampleSeed
    dans tests/test_optimizer.py pour la preuve côté RNG)."""

    def _fold(self, df):
        return _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )

    def _general_config_in_stratified_range(self):
        # 4 paramètres * 20 valeurs = 160 000 combinaisons déclarées : > 50 000, <= 500 000 —
        # exactement la plage qui dispatche vers _run_stratified_sample() (optimizer.run_mode4()).
        ranges = [
            ParamRange(
                name=f"p{i}", param_type="number", label=f"p{i}", min_val=0, max_val=19, step=1,
            )
            for i in range(4)
        ]
        return _minimal_optimizer_config(mode="general", param_ranges=ranges)

    def test_raises_before_any_backtest_when_reachable_without_a_fold_seed(self, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = self._fold(df)
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = self._general_config_in_stratified_range()

        with pytest.raises(NonDeterministicSearchWithoutSeed):
            run_fold_train(fold, config, df, fold_seed=None)

        assert not fake.calls, (
            "aucun backtest ne doit être lancé une fois le garde déclenché — la recherche "
            "TRAIN entière doit être refusée avant tout tirage non-seedé"
        )

    def test_deterministic_grid_mode_never_raises_even_without_a_fold_seed(self, monkeypatch):
        """Non-régression : mode="grid" (déterministe, aucun random.choice()) ne doit jamais être
        bloqué par ce garde, avec ou sans fold_seed — même les search spaces déjà couverts par la
        suite existante (mode="grid", 3 combinaisons)."""
        df = _build_synthetic_wf_df(200)
        fold = self._fold(df)
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        run_fold_train(fold, config, df, fold_seed=None)  # ne doit pas lever

        assert fake.calls

    def test_raises_for_an_unrecognized_mode_string_that_falls_through_to_run_mode4(
        self, monkeypatch,
    ):
        """Régression review indépendante (finding CONFIRMÉ, axe Spec) :
        `optimizer.Optimizer.run()` dispatche via `{"single_var":..., "cross_zone":...,
        "grid":..., "general":...}.get(cfg.mode, self.run_mode4)` — TOUT `mode` non reconnu (pas
        seulement `"general"`) retombe sur `run_mode4()`, donc peut atteindre
        `_run_stratified_sample()` exactement comme `"general"`. Un garde qui ne teste que
        `mode == "general"` serait une approximation qui dérive silencieusement de la vraie
        condition de branchement dès qu'un `mode` mal orthographié/inconnu est utilisé."""
        df = _build_synthetic_wf_df(200)
        fold = self._fold(df)
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        ranges = [
            ParamRange(
                name=f"p{i}", param_type="number", label=f"p{i}", min_val=0, max_val=19, step=1,
            )
            for i in range(4)
        ]
        config = _minimal_optimizer_config(mode="not_a_real_mode", param_ranges=ranges)

        with pytest.raises(NonDeterministicSearchWithoutSeed):
            run_fold_train(fold, config, df, fold_seed=None)

        assert not fake.calls

    def test_forwards_fold_seed_to_optimizer_run_when_provided(self, monkeypatch):
        """Un fold_seed fourni désamorce le garde ET doit être transmis tel quel à
        `Optimizer.run(seed=...)` — `Optimizer.run` est ESPIONNÉ (jamais réellement exécuté avec
        50 000 tirages ici, hors de portée d'un test unitaire) : seul le contrat d'appel est
        vérifié, la preuve du seeding réel du RNG vit dans tests/test_optimizer.py."""
        df = _build_synthetic_wf_df(200)
        fold = self._fold(df)
        config = self._general_config_in_stratified_range()

        captured_kwargs = {}

        def fake_run(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
            return [], {}

        monkeypatch.setattr(Optimizer, "run", fake_run)

        run_fold_train(fold, config, df, fold_seed=999)

        assert captured_kwargs.get("seed") == 999


class TestRunFoldTrainGuardIsNotALocalCopyOfOptimizerThresholds:
    """Régression review indépendante (tentative 3, finding MAJEUR) : `walk_forward.py` dupliquait
    en dur la table de dispatch/les seuils 50 000-500 000 d'`optimizer.py` au lieu de les
    consulter. `_train_search_reaches_stratified_sample()` délègue maintenant à
    `optimizer.reaches_stratified_sample()` — ces tests le prouvent en faisant varier les VRAIES
    constantes d'`optimizer.py` et en observant que le garde de `run_fold_train()` suit, ce
    qu'une réplique locale figée ne pourrait jamais faire."""

    def _fold(self, df):
        return _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )

    def test_lowering_optimizers_max_threshold_stops_the_guard_from_firing(self, monkeypatch):
        """Un search space "general" à 160 000 combinaisons déclarées atteint normalement
        `_run_stratified_sample()` (dans ]50k, 500k]). En abaissant
        `optimizer.STRATIFIED_SAMPLE_MAX_COMBINATIONS` sous ce nombre, `run_mode4()` router
        désormais vers `_run_progressive_grid()` (déterministe) — le garde de `run_fold_train()`
        DOIT suivre et ne plus lever, preuve qu'il ne recopie pas 500_000 en dur."""
        df = _build_synthetic_wf_df(200)
        fold = self._fold(df)
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        ranges = [
            ParamRange(
                name=f"p{i}", param_type="number", label=f"p{i}", min_val=0, max_val=19, step=1,
            )
            for i in range(4)
        ]
        config = _minimal_optimizer_config(mode="general", param_ranges=ranges)
        monkeypatch.setattr(optimizer, "STRATIFIED_SAMPLE_MAX_COMBINATIONS", 100)

        run_fold_train(fold, config, df, fold_seed=None)  # ne doit pas lever

    def test_raising_optimizers_min_threshold_makes_the_guard_fire(self, monkeypatch):
        """Un search space "general" à 30 combinaisons déclarées (<=50 000) reste normalement en
        dessous du seuil, donc déterministe (`run_mode3()`). En abaissant
        `optimizer.STRATIFIED_SAMPLE_MIN_COMBINATIONS` sous 30, ce même search space bascule dans
        la plage stratifiée — le garde DOIT se déclencher, preuve qu'il ne recopie pas 50_000 en
        dur non plus."""
        df = _build_synthetic_wf_df(200)
        fold = self._fold(df)
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        ranges = [
            ParamRange(
                name=f"p{i}", param_type="number", label=f"p{i}", min_val=0, max_val=4, step=1,
            )
            for i in range(2)
        ]  # 5 * 5 = 25 combinaisons déclarées
        config = _minimal_optimizer_config(mode="general", param_ranges=ranges)
        monkeypatch.setattr(optimizer, "STRATIFIED_SAMPLE_MIN_COMBINATIONS", 10)

        with pytest.raises(NonDeterministicSearchWithoutSeed):
            run_fold_train(fold, config, df, fold_seed=None)

        assert not fake.calls

    def test_removing_a_mode_from_deterministic_dispatch_modes_makes_the_guard_fire_for_it(
        self, monkeypatch,
    ):
        """Si `optimizer.DETERMINISTIC_DISPATCH_MODES` ne contenait plus "grid" (ex. `run()`
        changeait un jour son dispatch dict pour router "grid" vers `run_mode4()`), le garde DOIT
        recommencer à s'en méfier — preuve qu'il consulte l'ensemble réel, pas une copie figée
        `{"single_var", "cross_zone", "grid"}` écrite en dur dans walk_forward.py."""
        df = _build_synthetic_wf_df(200)
        fold = self._fold(df)
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        ranges = [
            ParamRange(
                name=f"p{i}", param_type="number", label=f"p{i}", min_val=0, max_val=19, step=1,
            )
            for i in range(4)
        ]  # 160 000 combinaisons déclarées — dans ]50k, 500k]
        config = _minimal_optimizer_config(mode="grid", param_ranges=ranges)
        monkeypatch.setattr(
            optimizer, "DETERMINISTIC_DISPATCH_MODES", frozenset({"single_var", "cross_zone"}),
        )

        with pytest.raises(NonDeterministicSearchWithoutSeed):
            run_fold_train(fold, config, df, fold_seed=None)

        assert not fake.calls


class TestExecuteWalkForwardFoldForwardsFoldSeed:

    def test_forwards_fold_seed_to_run_fold_train(self, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        captured = {}
        real_run_fold_train = walk_forward_module.run_fold_train

        def spy_run_fold_train(fold_, base_config, df_, progress_cb=None, stop_flag_fn=None,
                                fold_seed=None):
            captured["fold_seed"] = fold_seed
            return real_run_fold_train(
                fold_, base_config, df_, progress_cb=progress_cb, stop_flag_fn=stop_flag_fn,
                fold_seed=fold_seed,
            )

        monkeypatch.setattr(walk_forward_module, "run_fold_train", spy_run_fold_train)

        execute_walk_forward_fold(fold, config, df, fold_seed=2024)

        assert captured["fold_seed"] == 2024


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 3 — Orchestration multi-fold + agrégation OOS en mémoire
# (ADR 0021 Décisions 9/14/15). `run_walk_forward()` orchestre `execute_walk_forward_fold()`
# (Slice 2, inchangée) fold par fold ; `build_aggregate_result()` peuple `AggregateResult` (déjà
# défini dans validation_run.py) à partir de la série de `FoldResult` collectée. Aucune
# persistance disque, aucun `WalkForwardEvidence`/verdict scientifique ici (hors scope).
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunFoldTestExposesGrossWinLossForAggregation:
    """`FoldResult.gross_win`/`gross_loss`/`n_win` (extension additive Slice 3) : population
    directe depuis les mêmes `stats` déjà produites par l'unique exécution TEST du fold — aucun
    second backtest, mêmes noms de grandeur qu'`engine.py::_compute_stats()`."""

    def test_gross_win_loss_and_n_win_populated_from_stats(self, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[110].isoformat(),
        )
        trades = pd.DataFrame([
            {"resultat_net": 10.0, "raison_sortie": "target"},
            {"resultat_net": -4.0, "raison_sortie": "stop"},
            {"resultat_net": 2.0, "raison_sortie": "fin-donnees"},
        ])
        equity = pd.DataFrame([{"date": "x", "capital": 10_008.0}])
        stats = {
            "n_trades": 3, "net_ret_pct": 0.08, "max_dd_pct": 1.5,
            "profit_factor": 2.1, "win_rate": 66.7,
            "gross_win": 12.0, "gross_loss": 4.0, "n_win": 2,
        }

        def fake_run_backtest(df_, strategy, params, **kwargs):
            return trades, equity, stats

        import engine
        monkeypatch.setattr(engine, "run_backtest", fake_run_backtest)
        config = _minimal_optimizer_config()
        selection = _fold_selection(fold)

        result = run_fold_test(fold, selection, config, df)

        assert result.gross_win == 12.0
        assert result.gross_loss == 4.0
        assert result.n_win == 2

    def test_gross_win_loss_and_n_win_are_zero_for_zero_trade_fold(self, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[110].isoformat(),
        )
        empty_trades, empty_equity = pd.DataFrame(), pd.DataFrame()

        import engine
        monkeypatch.setattr(
            engine, "run_backtest",
            lambda *a, **k: (empty_trades, empty_equity, {"n_trades": 0}),
        )
        config = _minimal_optimizer_config()
        selection = _fold_selection(fold)

        result = run_fold_test(fold, selection, config, df)

        assert result.gross_win == 0.0
        assert result.gross_loss == 0.0
        assert result.n_win == 0


def _fold_result_stub(
    fold, selection=None, score_test=1.0, net_ret_pct=0.0, n_trades=1,
    zero_trade_oos=False, gross_win=0.0, gross_loss=0.0, n_win=0,
):
    """Construit un `FoldResult` directement (sans backtest réel) pour les tests
    d'orchestration/d'agrégation Slice 3 — mêmes principes que `_wf_fold()`/`_fold_selection()`
    ci-dessus pour Slice 1/2."""
    selection = selection if selection is not None else _fold_selection(fold)
    return FoldResult(
        fold_id=fold.fold_id,
        definition=fold,
        selection=selection,
        n_trades=n_trades,
        net_ret_pct=net_ret_pct,
        max_dd_pct=None,
        profit_factor=None,
        win_rate=None,
        expectancy=None,
        score_test=score_test,
        zero_trade_oos=zero_trade_oos,
        forced_closes=0,
        coverage_bars=10,
        gross_win=gross_win,
        gross_loss=gross_loss,
        n_win=n_win,
    )


class TestBuildAggregateResult:
    """`build_aggregate_result()` — fonction PURE, aucun backtest, ADR 0021 Décision 15."""

    def _folds(self, n, step_months=1):
        zone = _zone("2023-01-01T00:00:00+00:00", "2023-12-01T00:00:00+00:00")
        folds = []
        for k in range(n):
            train_start = pd.Timestamp("2023-01-01T00:00:00+00:00") + pd.DateOffset(
                months=k * step_months,
            )
            boundary = train_start + pd.DateOffset(months=step_months)
            test_end = boundary + pd.DateOffset(months=step_months)
            folds.append(_wf_fold(
                train_start=train_start.isoformat(), boundary=boundary.isoformat(),
                test_end=test_end.isoformat(), index=k, is_last=(k == n - 1),
            ))
        return folds

    def test_equity_curve_matches_the_adr_reference_example(self):
        """Exemple de référence de l'ADR (Décision 15) : fold k +5%, fold k+1 -2% ->
        1.00 -> 1.05 -> 1.029. Jamais une concaténation brute de capital absolu."""
        fold0, fold1 = self._folds(2)
        r0 = _fold_result_stub(fold0, net_ret_pct=5.0)
        r1 = _fold_result_stub(fold1, net_ret_pct=-2.0)

        agg = build_aggregate_result((r0, r1))

        assert agg.oos_net_return_pct == pytest.approx(2.9)
        # peak=1.05, trough final=1.029 : (1.05-1.029)/1.05*100 == 2.0.
        assert agg.oos_max_dd_pct == pytest.approx(2.0)

    def test_profit_factor_is_inf_when_gross_loss_total_is_zero_with_real_trades(self):
        """gross_loss_total == 0 avec des trades réels -> float('inf') (même convention
        qu'engine.py::_compute_stats(), ligne ~502)."""
        fold0, = self._folds(1)
        r0 = _fold_result_stub(fold0, n_trades=5, gross_win=100.0, gross_loss=0.0, n_win=5)

        agg = build_aggregate_result((r0,))

        assert agg.oos_profit_factor == float("inf")
        assert agg.total_oos_trades == 5
        assert agg.oos_win_rate == pytest.approx(1.0)

    def test_profit_factor_and_win_rate_are_none_when_total_oos_trades_is_zero(self):
        """`None` réservé au seul cas total_oos_trades == 0 (tous les folds zéro-trade)."""
        fold0, fold1 = self._folds(2)
        r0 = _fold_result_stub(fold0, n_trades=0, zero_trade_oos=True)
        r1 = _fold_result_stub(fold1, n_trades=0, zero_trade_oos=True)

        agg = build_aggregate_result((r0, r1))

        assert agg.oos_profit_factor is None
        assert agg.oos_win_rate is None
        assert agg.total_oos_trades == 0

    def test_profit_factor_sums_gross_win_loss_across_folds_not_averaged(self):
        fold0, fold1 = self._folds(2)
        r0 = _fold_result_stub(fold0, n_trades=2, gross_win=10.0, gross_loss=5.0, n_win=1)
        r1 = _fold_result_stub(fold1, n_trades=3, gross_win=6.0, gross_loss=1.0, n_win=2)

        agg = build_aggregate_result((r0, r1))

        # gross_win_total=16, gross_loss_total=6 -> 16/6, jamais moyenne de (10/5=2.0, 6/1=6.0).
        assert agg.oos_profit_factor == pytest.approx(16.0 / 6.0)
        assert agg.total_oos_trades == 5
        assert agg.oos_win_rate == pytest.approx(3 / 5)

    def test_n_folds_zero_trade_counts_a_mix_correctly(self):
        fold0, fold1, fold2 = self._folds(3)
        r0 = _fold_result_stub(fold0, zero_trade_oos=True, n_trades=0)
        r1 = _fold_result_stub(fold1, zero_trade_oos=False, n_trades=2)
        r2 = _fold_result_stub(fold2, zero_trade_oos=True, n_trades=0)

        agg = build_aggregate_result((r0, r1, r2))

        assert agg.n_folds == 3
        assert agg.n_folds_zero_trade == 2

    def test_worst_fold_id_is_the_lowest_score_test_among_at_least_three_folds(self):
        fold0, fold1, fold2 = self._folds(3)
        r0 = _fold_result_stub(fold0, score_test=1.0)
        r1 = _fold_result_stub(fold1, score_test=-5.0)
        r2 = _fold_result_stub(fold2, score_test=3.0)

        agg = build_aggregate_result((r0, r1, r2))

        assert agg.worst_fold_id == fold1.fold_id

    def test_mean_and_median_fold_score_test_are_diagnostics_not_the_primary_measure(self):
        fold0, fold1, fold2 = self._folds(3)
        r0 = _fold_result_stub(fold0, score_test=1.0)
        r1 = _fold_result_stub(fold1, score_test=2.0)
        r2 = _fold_result_stub(fold2, score_test=10.0)

        agg = build_aggregate_result((r0, r1, r2))

        assert agg.mean_fold_score_test == pytest.approx(13.0 / 3.0)
        assert agg.median_fold_score_test == pytest.approx(2.0)

    def test_oos_sharpe_stays_none_in_v1(self):
        fold0, = self._folds(1)
        r0 = _fold_result_stub(fold0)

        agg = build_aggregate_result((r0,))

        assert agg.oos_sharpe is None

    def test_returns_an_aggregate_result_instance(self):
        fold0, = self._folds(1)
        r0 = _fold_result_stub(fold0)

        agg = build_aggregate_result((r0,))

        assert isinstance(agg, AggregateResult)


class TestRunWalkForwardOrchestration:
    """`run_walk_forward()` — ADR 0021 Décision 14 (aucune rétroaction inter-fold), Décision 9
    (dérivation `fold_seed`). `execute_walk_forward_fold()` est remplacée par un double de test
    dans la plupart de ces tests : sa propre substance (TRAIN/Top-1/TEST) reste couverte par les
    tests Slice 2 ci-dessus, jamais dupliquée ici."""

    def _spec_and_zone(self, **spec_overrides):
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M", **spec_overrides)
        zone = _zone("2023-01-01T00:00:00+00:00", "2023-04-01T00:00:00+00:00")
        return spec, zone

    def test_compute_fold_definitions_is_called_exactly_once(self, monkeypatch):
        spec, zone = self._spec_and_zone()
        calls = {"count": 0}
        real_compute = walk_forward_module.compute_fold_definitions

        def spy_compute(*a, **k):
            calls["count"] += 1
            return real_compute(*a, **k)

        monkeypatch.setattr(walk_forward_module, "compute_fold_definitions", spy_compute)
        monkeypatch.setattr(
            walk_forward_module, "execute_walk_forward_fold",
            lambda fold, *a, **k: _fold_result_stub(fold),
        )

        outcome = run_walk_forward(zone, spec, None, _minimal_optimizer_config(), None)

        assert calls["count"] == 1
        assert isinstance(outcome, WalkForwardRunOutcome)
        assert outcome.stopped_early is False
        assert len(outcome.fold_results) == 2

    def test_folds_are_executed_in_order_and_results_collected(self, monkeypatch):
        spec, zone = self._spec_and_zone()
        order = []

        def fake_execute(fold, base_config, df, progress_cb=None, stop_flag_fn=None,
                          fold_seed=None):
            order.append(fold.fold_id)
            return _fold_result_stub(fold, score_test=float(fold.fold_index))

        monkeypatch.setattr(walk_forward_module, "execute_walk_forward_fold", fake_execute)

        outcome = run_walk_forward(zone, spec, None, _minimal_optimizer_config(), None)

        assert order == ["fold_000", "fold_001"]
        assert [r.fold_id for r in outcome.fold_results] == ["fold_000", "fold_001"]

    def test_no_cross_fold_feedback_base_config_and_seed_independent_of_prior_result(
        self, monkeypatch,
    ):
        """Décision 14 — un score TRAIN/TEST extrême du fold 0 ne doit jamais influencer le
        `base_config`/`fold_seed` transmis au fold 1."""
        spec, zone = self._spec_and_zone(master_seed=777)
        captured = []

        def fake_execute(fold, base_config, df, progress_cb=None, stop_flag_fn=None,
                          fold_seed=None):
            captured.append(
                {"fold_id": fold.fold_id, "base_config": base_config, "fold_seed": fold_seed},
            )
            score = -999999.0 if fold.fold_index == 0 else 1.0
            return _fold_result_stub(fold, score_test=score)

        monkeypatch.setattr(walk_forward_module, "execute_walk_forward_fold", fake_execute)
        base_config = _minimal_optimizer_config()

        run_walk_forward(
            zone, spec, None, base_config, None, validation_run_id="wf_run_abc",
        )

        assert captured[0]["base_config"] is base_config
        assert captured[1]["base_config"] is base_config
        expected_seed_0 = int(
            hashlib.sha256(b"777:wf_run_abc:0:wf-fold-seed-v1").hexdigest(), 16,
        )
        expected_seed_1 = int(
            hashlib.sha256(b"777:wf_run_abc:1:wf-fold-seed-v1").hexdigest(), 16,
        )
        assert captured[0]["fold_seed"] == expected_seed_0
        assert captured[1]["fold_seed"] == expected_seed_1

    def test_fold_seed_is_none_when_master_seed_not_provided(self, monkeypatch):
        spec, zone = self._spec_and_zone()
        captured = []

        def fake_execute(fold, base_config, df, progress_cb=None, stop_flag_fn=None,
                          fold_seed=None):
            captured.append(fold_seed)
            return _fold_result_stub(fold)

        monkeypatch.setattr(walk_forward_module, "execute_walk_forward_fold", fake_execute)

        run_walk_forward(zone, spec, None, _minimal_optimizer_config(), None)

        assert captured == [None, None]

    def test_master_seed_without_validation_run_id_raises_early(self):
        spec, zone = self._spec_and_zone(master_seed=777)

        with pytest.raises(ValueError):
            run_walk_forward(zone, spec, None, _minimal_optimizer_config(), None)

    def test_stop_flag_fn_between_folds_returns_partial_results_marked_stopped(
        self, monkeypatch,
    ):
        spec, zone = self._spec_and_zone()
        executed = []

        def fake_execute(fold, base_config, df, progress_cb=None, stop_flag_fn=None,
                          fold_seed=None):
            executed.append(fold.fold_id)
            return _fold_result_stub(fold)

        monkeypatch.setattr(walk_forward_module, "execute_walk_forward_fold", fake_execute)

        state = {"n": 0}

        def stop_flag_fn():
            state["n"] += 1
            return state["n"] > 1  # False avant fold_000, True avant fold_001.

        outcome = run_walk_forward(
            zone, spec, None, _minimal_optimizer_config(), None, stop_flag_fn=stop_flag_fn,
        )

        assert executed == ["fold_000"]
        assert outcome.stopped_early is True
        assert [r.fold_id for r in outcome.fold_results] == ["fold_000"]

    def test_dataset_too_short_propagates_untouched_never_duplicated(self):
        spec, _zone_unused = self._spec_and_zone()
        zone_too_short = _zone("2023-01-01T00:00:00+00:00", "2023-01-15T00:00:00+00:00")

        with pytest.raises(DatasetTooShortForWalkForward):
            run_walk_forward(zone_too_short, spec, None, _minimal_optimizer_config(), None)

    def test_integration_with_real_execute_walk_forward_fold(self, monkeypatch):
        """Bout-en-bout avec la vraie `execute_walk_forward_fold()` (Slice 2, inchangée) — moteur
        monkeypatché comme les tests Slice 2 ci-dessus, jamais une stratégie réelle."""
        df = _build_synthetic_wf_df(400)
        spec, _zone_unused = self._spec_and_zone()
        zone = _zone(
            df["time_paris"].iloc[0].isoformat(), df["time_paris"].iloc[300].isoformat(),
        )
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        outcome = run_walk_forward(zone, spec, None, config, df)
        results = outcome.fold_results

        assert outcome.stopped_early is False
        assert len(results) >= 2
        assert all(isinstance(r, FoldResult) for r in results)
        assert [r.fold_id for r in results] == sorted(r.fold_id for r in results)

    def test_stop_flag_fn_is_never_forwarded_into_the_real_fold_train_search(
        self, monkeypatch,
    ):
        """Fix du finding BLOCKER : le `stop_flag_fn` de frontière inter-fold ne doit jamais
        atteindre `Optimizer.run()` à l'intérieur d'un fold — sinon une recherche TRAIN encore en
        cours serait tronquée silencieusement par `_run_batch_sequential`/`_run_batch_parallel`
        (`optimizer.py`), produisant un `FoldResult` indiscernable d'un résultat complet (viole
        Décision 6 — Top-1 sélectionné sur TOUT le TRAIN — et l'esprit de Décision 13). Utilise la
        vraie `execute_walk_forward_fold()` (comme le test d'intégration ci-dessus), jamais un
        double, pour exercer le chemin réel `run_fold_train -> Optimizer.run(stop_flag_fn=...)`."""
        df = _build_synthetic_wf_df(400)
        spec, _zone_unused = self._spec_and_zone()
        zone = _zone(
            df["time_paris"].iloc[0].isoformat(), df["time_paris"].iloc[300].isoformat(),
        )
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        calls = {"n": 0}

        def stop_flag_fn():
            calls["n"] += 1
            return False  # ne déclenche jamais l'arrêt — sert uniquement à compter les appels

        outcome = run_walk_forward(zone, spec, None, config, df, stop_flag_fn=stop_flag_fn)
        results = outcome.fold_results

        assert len(results) >= 2
        # Une seule vérification entre-folds par fold exécuté. Si stop_flag_fn avait été transmis
        # jusqu'à Optimizer.run(), il aurait été interrogé une fois par combinaison TRAIN évaluée
        # (>= 3 avec _param_ranges_3_values, par fold) — donc bien plus que len(results) au total.
        assert calls["n"] == len(results)

    def test_no_capital_or_pnl_carried_over_between_folds_flat_each_fold_v1(
        self, monkeypatch,
    ):
        """Spec item 2 (mission Slice 3) : `flat_each_fold_v1` (chaque fold repart du même
        capital initial, aucune position/PnL reportée d'un fold à l'autre) est « à VÉRIFIER par un
        test de régression sur l'orchestrateur, pas à réimplémenter ». Utilise la vraie
        `execute_walk_forward_fold()` (comme les tests d'intégration ci-dessus, jamais un double)
        pour prouver, à l'échelle de `run_walk_forward()`, que `initial_capital` transmis à
        `engine.run_backtest()` (TRAIN et TEST confondus) reste IDENTIQUE d'un fold à l'autre même
        quand le premier fold produit un gain massif (x100) — la seule façon dont un capital de
        fold précédent pourrait fuir vers le fold suivant dans ce codebase, `initial_capital`
        provenant uniquement de `base_config.global_params` (jamais mutée entre folds, déjà prouvé
        par `test_no_cross_fold_feedback_...` ci-dessus)."""
        df = _build_synthetic_wf_df(400)
        spec, _zone_unused = self._spec_and_zone()
        zone = _zone(
            df["time_paris"].iloc[0].isoformat(), df["time_paris"].iloc[300].isoformat(),
        )

        class _CapitalTrackingRunBacktest:
            def __init__(self):
                self.initial_capitals = []
                self.call_index = 0

            def __call__(self, df_, strategy, params, **kwargs):
                self.call_index += 1
                initial_capital = kwargs["initial_capital"]
                self.initial_capitals.append(initial_capital)
                # Le tout premier appel (fold 0) simule un gain massif — si ce gain fuyait vers le
                # fold suivant, son `initial_capital` s'écarterait de la valeur fixe de config.
                net_ret = 1_000.0 if self.call_index == 1 else params.get("ema_trend_len", 0) / 100.0
                trades = pd.DataFrame([{"resultat_net": 10.0, "raison_sortie": "fin-donnees"}])
                equity = pd.DataFrame([{"date": "2020-01-01", "capital": initial_capital + net_ret}])
                return trades, equity, {"n_trades": 1, "net_ret_pct": net_ret}

        fake = _CapitalTrackingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())
        expected_initial_capital = config.global_params.get("initial_capital", 10_000.0)

        outcome = run_walk_forward(zone, spec, None, config, df)

        assert len(outcome.fold_results) >= 2
        assert fake.initial_capitals, "au moins un backtest attendu"
        assert fake.initial_capitals == [expected_initial_capital] * len(fake.initial_capitals)


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 4 — Persistance disque des artefacts Walk-Forward (Décision 12, écriture seule).
# `execute_walk_forward_fold()`/`run_fold_test()` restent inchangées (Slice 2, tests ci-dessus) ;
# `execute_walk_forward_fold_with_artifacts()` est une fonction NOUVELLE, additive, qui délègue
# au même cœur interne (`_run_fold_test_core()`) — un seul backtest réel par fold, jamais deux.
# ═══════════════════════════════════════════════════════════════════════════════


def _write_test_data_manifest(tmp_path, **overrides):
    defaults = dict(
        provider="mt5", instrument="US100", provider_symbol="US100Cash",
        source_timeframe="M3", snapshot_id="snap-wf-slice4", content_hash="hash-wf-slice4",
        git_commit="deadbeefcafe", strategy_version="perfect_revolution_v1",
    )
    defaults.update(overrides)
    manifest = build_backtest_manifest(**defaults)
    path = tmp_path / "data_manifest.json"
    save_backtest_manifest(path, manifest)
    return path, manifest


def _execute_persistable_fold(monkeypatch, df, fold, config=None):
    fake = _ScoreByParamRunBacktest()
    import engine
    monkeypatch.setattr(engine, "run_backtest", fake)
    _patch_score_by_net_ret(monkeypatch)
    config = config or _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())
    fold_result, artifacts = execute_walk_forward_fold_with_artifacts(fold, config, df)
    return fold_result, artifacts, config, fake


class TestExecuteWalkForwardFoldWithArtifacts:
    """Nouvelle fonction additive (Slice 4) — même orchestration que
    `execute_walk_forward_fold()` (jamais modifiée), capture en plus les DataFrames TEST bruts
    pour la persistance disque, sans jamais déclencher un second backtest."""

    def test_returns_a_fold_result_and_fold_artifacts(self, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fold_result, artifacts, _config, fake = _execute_persistable_fold(monkeypatch, df, fold)

        assert isinstance(fold_result, FoldResult)
        assert isinstance(artifacts, FoldArtifacts)
        assert len(fake.calls) == 4  # 3 candidats TRAIN + 1 TEST — jamais un second backtest
        assert len(artifacts.train_candidates) == 3
        assert list(artifacts.test_trades["resultat_net"]) == [10.0]
        assert list(artifacts.test_equity["capital"]) == pytest.approx([10_001.4])

    def test_does_not_add_a_backtest_call_compared_to_execute_walk_forward_fold(self, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        import engine

        fake_a = _ScoreByParamRunBacktest()
        monkeypatch.setattr(engine, "run_backtest", fake_a)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())
        execute_walk_forward_fold(fold, config, df)
        assert len(fake_a.calls) == 4

        fake_b = _ScoreByParamRunBacktest()
        monkeypatch.setattr(engine, "run_backtest", fake_b)
        execute_walk_forward_fold_with_artifacts(fold, config, df)
        assert len(fake_b.calls) == 4

    def test_run_fold_test_behaviour_is_unchanged_after_the_extraction(self, monkeypatch):
        """Régression non-fonctionnelle : `run_fold_test()` doit toujours renvoyer un SEUL
        `FoldResult` (jamais un tuple) après l'extraction de `_run_fold_test_core()`."""
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = _minimal_optimizer_config()
        selection = _fold_selection(fold)

        result = run_fold_test(fold, selection, config, df)

        assert isinstance(result, FoldResult)


class TestBuildWalkForwardManifest:
    """`build_walk_forward_manifest()` — fingerprint de reprise (ADR 0021 Décision 12) : les
    trois versions de sémantique, le search space/scoring/filtres réels de `base_config`, et une
    référence explicite au `data_manifest.json` existant, jamais un git SHA recalculé
    indépendamment (`build_backtest_manifest(git_commit=...)` fixe ici une valeur non-plausible
    pour prouver l'absence de recalcul)."""

    def test_includes_search_space_scoring_and_filters_from_base_config(self, tmp_path):
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        config = _minimal_optimizer_config(
            mode="grid", param_ranges=_param_ranges_3_values(),
            score_weights=ScoreWeights(profit_factor=9.0), filters=FilterConfig(min_trades=5),
        )
        manifest_path, _dm = _write_test_data_manifest(tmp_path)

        data = build_walk_forward_manifest(spec, config, manifest_path)

        assert data["search_space"] == [dataclasses.asdict(pr) for pr in config.param_ranges]
        assert data["scoring"]["profit_factor"] == 9.0
        assert data["filters"]["min_trades"] == 5
        assert data["strategy_name"] == config.strategy_name
        assert data["strategy_module"] == config.strategy_module

    def test_raises_before_any_use_if_data_manifest_is_unreadable(self, tmp_path):
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        config = _minimal_optimizer_config()

        with pytest.raises(ValueError):
            build_walk_forward_manifest(spec, config, tmp_path / "does_not_exist.json")

    def test_includes_validation_run_id(self, tmp_path):
        """Correction review indépendante tentative 10, finding MAJEUR : `validation_run_id`
        pilote `_derive_fold_seed()` mais n'apparaissait dans aucune clé de `manifest.json` — une
        reprise fournissant un `validation_run_id` différent de la tentative originale passait donc
        le fingerprint RUN-LEVEL silencieusement (`check_resume_fingerprint()` compare pourtant
        déjà TOUTES les clés du manifest, hors `data_manifest_path` — il suffit de l'y inclure)."""
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        config = _minimal_optimizer_config()
        manifest_path, _dm = _write_test_data_manifest(tmp_path)

        data = build_walk_forward_manifest(
            spec, config, manifest_path, validation_run_id="wf_run_abc",
        )

        assert data["validation_run_id"] == "wf_run_abc"


class TestPersistWalkForwardRun:
    """`persist_walk_forward_run()` (ADR 0021 Décision 12, écriture seule) — structure
    `manifest.json`/`state.json`/`folds/fold_NNN/*.json`/`*.csv`/`aggregate.json`. Jamais de
    reprise, jamais de `WalkForwardEvidence`/verdict scientifique (hors scope, tranche
    suivante)."""

    def _one_fold_run(self, monkeypatch, df=None):
        df = df if df is not None else _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fold_result, artifacts, config, _fake = _execute_persistable_fold(monkeypatch, df, fold)
        outcome = WalkForwardRunOutcome(fold_results=(fold_result,), stopped_early=False)
        aggregate = build_aggregate_result((fold_result,))
        return outcome, (artifacts,), aggregate, config

    def test_manifest_json_carries_the_three_semantics_versions(self, tmp_path, monkeypatch):
        outcome, artifacts, aggregate, config = self._one_fold_run(monkeypatch)
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M", master_seed=42)
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"

        persist_walk_forward_run(
            outcome, artifacts, aggregate, spec, config, manifest_path, output_dir,
        )

        data = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
        assert data["walk_forward_semantics_version"] == WALK_FORWARD_SEMANTICS_VERSION
        assert data["train_test_semantics_version"] == TRAIN_TEST_SEMANTICS_VERSION
        assert data["state_readiness_semantics_version"] == STATE_READINESS_SEMANTICS_VERSION
        assert data["master_seed"] == 42
        assert data["verdict_policy_id"] is None

    def test_manifest_json_references_the_existing_data_manifest_without_recomputing_git_sha(
        self, tmp_path, monkeypatch,
    ):
        outcome, artifacts, aggregate, config = self._one_fold_run(monkeypatch)
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(
            tmp_path, git_commit="not-a-real-git-sha-99", snapshot_id="snap-xyz",
        )
        output_dir = tmp_path / "walk_forward"

        persist_walk_forward_run(
            outcome, artifacts, aggregate, spec, config, manifest_path, output_dir,
        )

        data = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
        assert data["data_manifest"]["git_commit"] == "not-a-real-git-sha-99"
        assert data["data_manifest"]["snapshot_id"] == "snap-xyz"
        assert data["data_manifest_path"] == str(manifest_path)

    def test_missing_data_manifest_path_raises_before_any_write(self, tmp_path, monkeypatch):
        outcome, artifacts, aggregate, config = self._one_fold_run(monkeypatch)
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        output_dir = tmp_path / "walk_forward"

        with pytest.raises(ValueError):
            persist_walk_forward_run(
                outcome, artifacts, aggregate, spec, config,
                tmp_path / "does_not_exist.json", output_dir,
            )
        assert not output_dir.exists()

    def test_state_json_lists_completed_fold_ids_in_order(self, tmp_path, monkeypatch):
        df = _build_synthetic_wf_df(260)
        fold0 = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
            index=0, is_last=False,
        )
        fold1 = _wf_fold(
            train_start=df["time_paris"].iloc[50].isoformat(),
            boundary=df["time_paris"].iloc[150].isoformat(),
            test_end=df["time_paris"].iloc[200].isoformat(),
            index=1, is_last=True,
        )
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0)
        r1, a1, _c1, _f1 = _execute_persistable_fold(monkeypatch, df, fold1, config=config)
        outcome = WalkForwardRunOutcome(fold_results=(r0, r1), stopped_early=False)
        aggregate = build_aggregate_result((r0, r1))
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"

        persist_walk_forward_run(
            outcome, (a0, a1), aggregate, spec, config, manifest_path, output_dir,
        )

        state = json.loads((output_dir / "state.json").read_text(encoding="utf-8"))
        assert state["completed_fold_ids"] == [fold0.fold_id, fold1.fold_id]

    def test_fold_definition_and_selection_json_deserialize_to_real_values(
        self, tmp_path, monkeypatch,
    ):
        outcome, artifacts, aggregate, config = self._one_fold_run(monkeypatch)
        fold_result = outcome.fold_results[0]
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"

        persist_walk_forward_run(
            outcome, artifacts, aggregate, spec, config, manifest_path, output_dir,
        )

        fold_dir = output_dir / "folds" / fold_result.fold_id
        definition = json.loads((fold_dir / "definition.json").read_text(encoding="utf-8"))
        assert definition == dataclasses.asdict(fold_result.definition)
        selection = json.loads((fold_dir / "selection.json").read_text(encoding="utf-8"))
        assert selection == dataclasses.asdict(fold_result.selection)
        test_result = json.loads((fold_dir / "test_result.json").read_text(encoding="utf-8"))
        assert test_result["fold_id"] == fold_result.fold_id
        assert test_result["score_test"] == pytest.approx(fold_result.score_test)
        assert test_result["n_trades"] == fold_result.n_trades

    def test_aggregate_json_deserializes_to_the_real_aggregate_result(
        self, tmp_path, monkeypatch,
    ):
        outcome, artifacts, aggregate, config = self._one_fold_run(monkeypatch)
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"

        persist_walk_forward_run(
            outcome, artifacts, aggregate, spec, config, manifest_path, output_dir,
        )

        data = json.loads((output_dir / "aggregate.json").read_text(encoding="utf-8"))
        assert data == dataclasses.asdict(aggregate)

    def test_aggregate_json_is_not_written_when_aggregate_is_none(self, tmp_path, monkeypatch):
        outcome, artifacts, _aggregate, config = self._one_fold_run(monkeypatch)
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"

        persist_walk_forward_run(
            outcome, artifacts, None, spec, config, manifest_path, output_dir,
        )

        assert not (output_dir / "aggregate.json").exists()

    def test_train_candidates_csv_contains_the_real_evaluated_candidates(
        self, tmp_path, monkeypatch,
    ):
        outcome, artifacts, aggregate, config = self._one_fold_run(monkeypatch)
        fold_result = outcome.fold_results[0]
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"

        persist_walk_forward_run(
            outcome, artifacts, aggregate, spec, config, manifest_path, output_dir,
        )

        csv_path = output_dir / "folds" / fold_result.fold_id / "train_candidates.csv"
        candidates = pd.read_csv(csv_path)
        assert len(candidates) == 3
        assert sorted(candidates["ema_trend_len"].tolist()) == [100, 120, 140]
        best_row = candidates.loc[candidates["ema_trend_len"] == 140]
        assert best_row["score"].iloc[0] == pytest.approx(1.4)

    def test_oos_trades_and_equity_csv_contain_the_real_test_rows(self, tmp_path, monkeypatch):
        outcome, artifacts, aggregate, config = self._one_fold_run(monkeypatch)
        fold_result = outcome.fold_results[0]
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"

        persist_walk_forward_run(
            outcome, artifacts, aggregate, spec, config, manifest_path, output_dir,
        )

        fold_dir = output_dir / "folds" / fold_result.fold_id
        trades = pd.read_csv(fold_dir / "oos_trades.csv")
        equity = pd.read_csv(fold_dir / "oos_equity.csv")
        assert trades["resultat_net"].tolist() == [10.0]
        assert equity["capital"].tolist() == pytest.approx([10_001.4])

    def test_zero_trade_oos_fold_produces_empty_but_valid_csvs(self, tmp_path, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        import engine
        empty_trades, empty_equity = pd.DataFrame(), pd.DataFrame()
        real_trades = pd.DataFrame([{"resultat_net": 5.0, "raison_sortie": "target"}])
        real_equity = pd.DataFrame([{"date": "x", "capital": 10_005.0}])
        calls = {"count": 0}

        def fake_run_backtest(df_, strategy, params, **kwargs):
            # 1er appel = candidat TRAIN unique (param_ranges=[] par défaut) : doit être
            # éligible (score > 0) pour que select_fold_top1() produise une FoldSelection.
            # 2e appel = l'UNIQUE exécution TEST du fold, volontairement zéro-trade.
            calls["count"] += 1
            if calls["count"] == 1:
                return real_trades, real_equity, {"n_trades": 1, "net_ret_pct": 1.0}
            return empty_trades, empty_equity, {"n_trades": 0}

        monkeypatch.setattr(engine, "run_backtest", fake_run_backtest)
        _patch_score_by_net_ret(monkeypatch)
        config = _minimal_optimizer_config()
        fold_result, artifacts = execute_walk_forward_fold_with_artifacts(fold, config, df)
        assert fold_result.zero_trade_oos is True
        outcome = WalkForwardRunOutcome(fold_results=(fold_result,), stopped_early=False)
        aggregate = build_aggregate_result((fold_result,))
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"

        persist_walk_forward_run(
            outcome, (artifacts,), aggregate, spec, config, manifest_path, output_dir,
        )

        fold_dir = output_dir / "folds" / fold_result.fold_id
        trades_path = fold_dir / "oos_trades.csv"
        equity_path = fold_dir / "oos_equity.csv"
        assert trades_path.is_file()
        assert equity_path.is_file()
        # DataFrame vide SANS schéma de colonnes (même convention que le reste de la suite pour
        # une observation zéro-trade, ex. TestRunFoldTest) — to_csv() écrit un fichier vide, sans
        # exception : "pas d'erreur", jamais un pd.read_csv() qui suppose des colonnes réelles.
        assert trades_path.read_text(encoding="utf-8").strip() == ""
        assert equity_path.read_text(encoding="utf-8").strip() == ""

    def test_every_json_file_is_written_through_save_atomic(self, tmp_path, monkeypatch):
        """Test de câblage — jamais un open()/json.dump() direct qui contournerait l'écriture
        atomique (ADR 0021 Décision 12)."""
        outcome, artifacts, aggregate, config = self._one_fold_run(monkeypatch)
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"

        real_save_atomic = walk_forward_module.save_atomic
        calls = []

        def spy(path, data, kind):
            calls.append(Path(path))
            return real_save_atomic(path, data, kind)

        monkeypatch.setattr(walk_forward_module, "save_atomic", spy)

        persist_walk_forward_run(
            outcome, artifacts, aggregate, spec, config, manifest_path, output_dir,
        )

        json_files_on_disk = sorted(str(p) for p in output_dir.rglob("*.json"))
        json_files_via_save_atomic = sorted(str(p) for p in calls)
        assert json_files_on_disk == json_files_via_save_atomic
        assert len(calls) == 1 + 1 + 1 + 3  # manifest + state + aggregate + 3 par fold (1 fold)

    def test_csv_writes_do_not_implicitly_depend_on_a_preceding_json_write_creating_the_dir(
        self, tmp_path, monkeypatch,
    ):
        """Régression review indépendante (finding MAJEUR) : `to_csv()` ne crée jamais son
        répertoire parent lui-même — si `persist_walk_forward_run()` comptait implicitement sur
        le `mkdir()` interne d'un `save_atomic()` JSON précédent pour que `fold_dir` existe déjà
        au moment des trois écritures CSV, un `save_atomic` qui ne crée plus ce répertoire (stub
        ci-dessous, simulant un réordonnancement futur où les CSV seraient écrits avant tout JSON)
        ferait échouer les CSV avec un `FileNotFoundError` — jamais toléré ici."""
        outcome, artifacts, aggregate, config = self._one_fold_run(monkeypatch)
        fold_result = outcome.fold_results[0]
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        output_dir.mkdir(parents=True)  # seul répertoire pré-existant — jamais `folds/fold_NNN/`.

        def save_atomic_without_mkdir(path, data, kind):
            path = Path(path)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return path

        monkeypatch.setattr(walk_forward_module, "save_atomic", save_atomic_without_mkdir)

        persist_walk_forward_run(
            outcome, artifacts, aggregate, spec, config, manifest_path, output_dir,
        )

        fold_dir = output_dir / "folds" / fold_result.fold_id
        assert (fold_dir / "oos_trades.csv").is_file()
        assert (fold_dir / "oos_equity.csv").is_file()
        assert (fold_dir / "train_candidates.csv").is_file()

    def test_fold_artifacts_length_must_match_fold_results_length(self, tmp_path, monkeypatch):
        outcome, artifacts, aggregate, config = self._one_fold_run(monkeypatch)
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"

        with pytest.raises(ValueError):
            persist_walk_forward_run(
                outcome, (), aggregate, spec, config, manifest_path, output_dir,
            )

    def test_fold_artifacts_out_of_order_relative_to_fold_results_is_rejected(
        self, tmp_path, monkeypatch,
    ):
        """Régression review indépendante (tentative 2, finding PLAUSIBLE) : l'appariement
        `fold_results`/`fold_artifacts` par seule position de tuple, sans vérifier l'identité,
        écrirait silencieusement les trades/equity d'un fold sous le répertoire d'un AUTRE fold
        si l'appelant les fournissait dans un ordre divergent — doit être rejeté explicitement."""
        df = _build_synthetic_wf_df(260)
        fold0 = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
            index=0, is_last=False,
        )
        fold1 = _wf_fold(
            train_start=df["time_paris"].iloc[50].isoformat(),
            boundary=df["time_paris"].iloc[150].isoformat(),
            test_end=df["time_paris"].iloc[200].isoformat(),
            index=1, is_last=True,
        )
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0)
        r1, a1, _c1, _f1 = _execute_persistable_fold(monkeypatch, df, fold1, config=config)
        outcome = WalkForwardRunOutcome(fold_results=(r0, r1), stopped_early=False)
        aggregate = build_aggregate_result((r0, r1))
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"

        with pytest.raises(ValueError):
            persist_walk_forward_run(
                # a1/a0 volontairement inversés par rapport à r0/r1.
                outcome, (a1, a0), aggregate, spec, config, manifest_path, output_dir,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 5 — Reprise (resume) d'un run Walk-Forward interrompu (Décision 12, complément).
# `run_walk_forward()`/`build_aggregate_result()`/`persist_walk_forward_run()` (Slices 3/4) restent
# INCHANGÉES — cette tranche ne fait que lire, en sens inverse, ce que Slice 4 a écrit.
# ═══════════════════════════════════════════════════════════════════════════════


def _real_two_fold_setup():
    """Deux VRAIS folds (via `compute_fold_definitions()`, jamais construits à la main) sur une
    zone VALIDATION de 3 mois calendaires avec un préréglage P1M/P1M/P1M — `resume_walk_forward_run()`
    recalculera EXACTEMENT les deux mêmes folds (fonction pure), garantissant que les fold_id
    persistés dans les tests ci-dessous correspondent à ceux que la reprise recalculera."""
    df = _build_synthetic_wf_df(100, start="2023-01-01T00:00:00", freq_minutes=1440)
    spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
    zone = _zone("2023-01-01T00:00:00+00:00", "2023-04-01T00:00:00+00:00")
    folds = compute_fold_definitions(zone, spec, None)
    assert len(folds) == 2
    return df, spec, zone, folds


class TestCheckResumeFingerprint:
    """`check_resume_fingerprint()` — garde run-level (ADR 0021 Décision 11/12), appelée une
    seule fois avant toute décision par fold."""

    def test_returns_none_when_no_manifest_persisted_yet(self, tmp_path):
        assert check_resume_fingerprint(tmp_path / "walk_forward", {"a": 1}) is None

    def test_returns_persisted_manifest_when_fingerprint_matches(self, tmp_path):
        output_dir = tmp_path / "walk_forward"
        manifest = {"walk_forward_semantics_version": "x", "data_manifest_path": "/some/path"}
        walk_forward_module.save_atomic(output_dir / "manifest.json", manifest, "test")
        current = dict(manifest)
        # data_manifest_path est un CHEMIN filesystem, jamais une dimension de fingerprint —
        # doit pouvoir diverger sans lever WalkForwardResumeMismatch.
        current["data_manifest_path"] = "/different/path/but/irrelevant"

        result = check_resume_fingerprint(output_dir, current)

        assert result == manifest

    def test_raises_on_divergent_specification(self, tmp_path):
        output_dir = tmp_path / "walk_forward"
        persisted = {"specification": {"train_period": "P24M"}, "data_manifest_path": "p"}
        walk_forward_module.save_atomic(output_dir / "manifest.json", persisted, "test")
        current = {"specification": {"train_period": "P12M"}, "data_manifest_path": "q"}

        with pytest.raises(WalkForwardResumeMismatch):
            check_resume_fingerprint(output_dir, current)

    def test_raises_on_divergent_data_manifest_content_hash(self, tmp_path):
        output_dir = tmp_path / "walk_forward"
        persisted = {"data_manifest": {"content_hash": "hash-A"}, "data_manifest_path": "p"}
        walk_forward_module.save_atomic(output_dir / "manifest.json", persisted, "test")
        current = {"data_manifest": {"content_hash": "hash-B"}, "data_manifest_path": "q"}

        with pytest.raises(WalkForwardResumeMismatch):
            check_resume_fingerprint(output_dir, current)

    def test_raises_on_divergent_semantics_version(self, tmp_path):
        output_dir = tmp_path / "walk_forward"
        persisted = {"state_readiness_semantics_version": "daily-state-ready-v1", "data_manifest_path": "p"}
        walk_forward_module.save_atomic(output_dir / "manifest.json", persisted, "test")
        current = {"state_readiness_semantics_version": "daily-state-ready-v2", "data_manifest_path": "q"}

        with pytest.raises(WalkForwardResumeMismatch):
            check_resume_fingerprint(output_dir, current)


class TestLoadTrainProgress:
    """`_load_train_progress()`/`_write_train_progress()` (ADR 0021 Décision 12, AF-V-02 Slice 5) —
    artefact de continuité de reprise pour un TRAIN interrompu, jamais une source de vérité
    scientifique : dégrade silencieusement vers `[]` plutôt que de lever une erreur."""

    def test_absent_file_returns_no_candidates(self, tmp_path):
        fold = _wf_fold(
            train_start="2020-01-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )
        config = _minimal_optimizer_config()
        assert walk_forward_module._load_train_progress(tmp_path, fold, config) == []

    def test_round_trips_written_candidates(self, tmp_path):
        fold = _wf_fold(
            train_start="2020-01-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )
        config = _minimal_optimizer_config()
        candidates = [
            {"params": {"ema_trend_len": 100}, "score": 1.0},
            {"params": {"ema_trend_len": 120}, "score": 1.2},
        ]
        walk_forward_module._write_train_progress(tmp_path, fold, config, candidates)

        assert walk_forward_module._load_train_progress(tmp_path, fold, config) == candidates

    def test_mismatched_fold_geometry_is_never_reused(self, tmp_path):
        """Une dérive de géométrie (`validation_zone`/`readiness_spec` différents entre deux
        tentatives) ne doit JAMAIS faire réutiliser des candidats évalués sous une fenêtre TRAIN
        différente — même esprit que la garde `FoldArtifactConflict` sur `definition.json`, mais
        appliquée à cet artefact de continuité qui, lui, dégrade silencieusement plutôt que de
        lever une erreur (ce n'est qu'une optimisation, jamais un artefact scientifique)."""
        original_fold = _wf_fold(
            train_start="2020-01-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )
        drifted_fold = _wf_fold(
            train_start="2019-06-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )
        config = _minimal_optimizer_config()
        walk_forward_module._write_train_progress(
            tmp_path, original_fold, config, [{"params": {"ema_trend_len": 100}, "score": 1.0}],
        )

        assert walk_forward_module._load_train_progress(tmp_path, drifted_fold, config) == []

    def test_mismatched_base_config_is_never_reused(self, tmp_path):
        """Un `base_config.base_params` différent entre deux tentatives (ex. un paramètre FIXE hors
        search space modifié) ne doit JAMAIS faire réutiliser des candidats évalués sous une
        configuration différente — même si la géométrie de fold, elle, est identique (review
        indépendante, tentative 3, finding MAJEUR : `check_resume_fingerprint()` run-level ne couvre
        pas `base_config.base_params`)."""
        fold = _wf_fold(
            train_start="2020-01-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )
        original_config = _minimal_optimizer_config()
        drifted_config = _minimal_optimizer_config(
            base_params=dict(original_config.base_params, ema_trend_len=999),
        )
        walk_forward_module._write_train_progress(
            tmp_path, fold, original_config, [{"params": {"ema_trend_len": 100}, "score": 1.0}],
        )

        assert walk_forward_module._load_train_progress(tmp_path, fold, drifted_config) == []


class TestDecideFoldResumeAction:
    """`decide_fold_resume_action()` — décision par fold (ADR 0021 Décision 12), suppose le
    fingerprint du run déjà validé (n'en revalide aucun aspect)."""

    def test_missing_fold_directory_is_redo(self, tmp_path):
        fold = _wf_fold(
            train_start="2020-01-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )

        decision = decide_fold_resume_action(fold, tmp_path / "walk_forward")

        assert decision.action == RESUME_ACTION_REDO
        assert decision.selection is None
        assert decision.fold_result is None

    def test_selection_without_test_result_is_replay_test_with_the_frozen_selection(self, tmp_path):
        fold = _wf_fold(
            train_start="2020-01-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )
        selection = _fold_selection(fold)
        fold_dir = tmp_path / "walk_forward" / "folds" / fold.fold_id
        walk_forward_module.save_atomic(fold_dir / "definition.json", dataclasses.asdict(fold), "test")
        walk_forward_module.save_atomic(
            fold_dir / "selection.json", dataclasses.asdict(selection), "test",
        )

        decision = decide_fold_resume_action(fold, tmp_path / "walk_forward")

        assert decision.action == RESUME_ACTION_REPLAY_TEST
        assert decision.selection == selection
        assert decision.fold_result is None

    def test_test_result_without_selection_raises_fold_artifact_conflict(self, tmp_path):
        fold = _wf_fold(
            train_start="2020-01-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )
        fold_dir = tmp_path / "walk_forward" / "folds" / fold.fold_id
        walk_forward_module.save_atomic(fold_dir / "definition.json", dataclasses.asdict(fold), "test")
        walk_forward_module.save_atomic(
            fold_dir / "test_result.json", {"fold_id": fold.fold_id}, "test",
        )

        with pytest.raises(FoldArtifactConflict):
            decide_fold_resume_action(fold, tmp_path / "walk_forward")

    def test_selection_without_definition_raises_fold_artifact_conflict(self, tmp_path):
        fold = _wf_fold(
            train_start="2020-01-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )
        selection = _fold_selection(fold)
        fold_dir = tmp_path / "walk_forward" / "folds" / fold.fold_id
        walk_forward_module.save_atomic(
            fold_dir / "selection.json", dataclasses.asdict(selection), "test",
        )

        with pytest.raises(FoldArtifactConflict):
            decide_fold_resume_action(fold, tmp_path / "walk_forward")

    def test_definition_only_drifted_raises_fold_artifact_conflict(self, tmp_path):
        """Correction review indépendante tentative 10, finding MAJEUR : la version précédente du
        fallthrough REDO ne validait `definition_is_consistent` que dans les branches SKIP/
        REPLAY_TEST — un `definition.json` seul (ni `selection.json` ni `test_result.json`, le cas
        « TRAIN interrompu avant toute FoldSelection ») dont la géométrie a dérivé passait
        silencieusement en REDO au lieu d'être refusé, contredisant la docstring de la fonction et
        l'invariant ADR 0021 Décision 11 (« refuser plutôt que deviner »)."""
        fold = _wf_fold(
            train_start="2020-01-01T00:00:00+00:00",
            boundary="2020-02-01T00:00:00+00:00",
            test_end="2020-03-01T00:00:00+00:00",
        )
        drifted_definition = dataclasses.asdict(fold)
        drifted_definition["train_start"] = "2019-01-01T00:00:00+00:00"
        fold_dir = tmp_path / "walk_forward" / "folds" / fold.fold_id
        walk_forward_module.save_atomic(fold_dir / "definition.json", drifted_definition, "test")

        with pytest.raises(FoldArtifactConflict):
            decide_fold_resume_action(fold, tmp_path / "walk_forward")

    def test_complete_fold_is_skip_with_the_persisted_result_reloaded(self, tmp_path, monkeypatch):
        df = _build_synthetic_wf_df(200)
        fold = _wf_fold(
            train_start=df["time_paris"].iloc[0].isoformat(),
            boundary=df["time_paris"].iloc[100].isoformat(),
            test_end=df["time_paris"].iloc[150].isoformat(),
        )
        fold_result, artifacts, config, _fake = _execute_persistable_fold(monkeypatch, df, fold)
        outcome = WalkForwardRunOutcome(fold_results=(fold_result,), stopped_early=False)
        aggregate = build_aggregate_result((fold_result,))
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M")
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, (artifacts,), aggregate, spec, config, manifest_path, output_dir,
        )

        decision = decide_fold_resume_action(fold, output_dir)

        assert decision.action == RESUME_ACTION_SKIP
        assert decision.fold_result.fold_id == fold_result.fold_id
        assert decision.fold_result.score_test == pytest.approx(fold_result.score_test)
        assert decision.fold_result.n_trades == fold_result.n_trades


class TestResumeWalkForwardRun:
    """`resume_walk_forward_run()` — point d'entrée de reprise (ADR 0021 Décision 12). Preuves de
    complétion de la mission Slice 5 : un fold complet est sauté (jamais ré-exécuté), un fold à
    sélection figée rejoue uniquement TEST, un fold absent est refait entièrement, un fingerprint
    divergent est refusé explicitement, l'agrégat couvre tous les folds."""

    def test_master_seed_without_validation_run_id_raises_early(self, tmp_path):
        spec = _spec(
            train_period="P1M", test_period="P1M", step_period="P1M", master_seed=777,
        )
        zone = _zone("2023-01-01T00:00:00+00:00", "2023-04-01T00:00:00+00:00")

        with pytest.raises(ValueError):
            resume_walk_forward_run(
                zone, spec, None, _minimal_optimizer_config(), None,
                tmp_path / "unused.json", tmp_path / "walk_forward",
            )

    def test_redo_propagates_the_same_fold_seed_run_walk_forward_would_have_produced(
        self, tmp_path, monkeypatch,
    ):
        """Finding MAJOR de la revue indépendante (Slice 5) : aucun test n'exerçait
        `resume_walk_forward_run()` avec `spec.master_seed` réellement défini pour vérifier que
        `fold_seed` (ADR 0021 Décision 9, `_derive_fold_seed()`) est bien propagé au chemin REDO
        (`_redo_fold_reusing_train_candidates()`) — une régression sur ce calcul (mauvais
        paramètre, ordre inversé, `fold_id` au lieu de `fold_index`) n'aurait fait échouer aucun
        test existant de cette classe, tous construits avec `master_seed=None`. Compare
        directement le `fold_seed` effectivement transmis lors d'un REDO après interruption (rien
        n'est encore persisté -> les deux folds sont REDO, `test_missing_fold_directory_is_redo`)
        à celui qu'un `run_walk_forward()` non interrompu, sur le MÊME
        `validation_run_id`/`fold_index`, aurait produit — jamais une valeur recalculée
        indépendamment qui masquerait une erreur symétrique dans les deux chemins."""
        df, _plain_spec, zone, _folds = _real_two_fold_setup()
        spec = _spec(train_period="P1M", test_period="P1M", step_period="P1M", master_seed=4242)
        validation_run_id = "wf_run_seed_check"
        config = _minimal_optimizer_config()
        output_dir = tmp_path / "walk_forward"
        manifest_path, _dm = _write_test_data_manifest(tmp_path)

        redo_seeds = {}

        def fake_redo(fold, base_config, df, output_dir, progress_cb=None, fold_seed=None):
            redo_seeds[fold.fold_index] = fold_seed
            return _fold_result_stub(fold)

        monkeypatch.setattr(walk_forward_module, "_redo_fold_reusing_train_candidates", fake_redo)

        resume_walk_forward_run(
            zone, spec, None, config, df, manifest_path, output_dir,
            validation_run_id=validation_run_id,
        )

        assert set(redo_seeds) == {0, 1}
        assert all(seed is not None for seed in redo_seeds.values())

        reference_seeds = {}

        def fake_execute(fold, base_config, df, progress_cb=None, stop_flag_fn=None, fold_seed=None):
            reference_seeds[fold.fold_index] = fold_seed
            return _fold_result_stub(fold)

        monkeypatch.setattr(walk_forward_module, "execute_walk_forward_fold", fake_execute)

        run_walk_forward(zone, spec, None, config, df, validation_run_id=validation_run_id)

        assert redo_seeds == reference_seeds

    def test_completed_run_is_fully_skipped_never_re_executed(self, tmp_path, monkeypatch):
        df, spec, zone, folds = _real_two_fold_setup()
        config = None
        results, artifacts_list = [], []
        for fold in folds:
            r, a, config, _fake = _execute_persistable_fold(monkeypatch, df, fold, config=config)
            results.append(r)
            artifacts_list.append(a)
        outcome = WalkForwardRunOutcome(fold_results=tuple(results), stopped_early=False)
        aggregate = build_aggregate_result(tuple(results))
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, tuple(artifacts_list), aggregate, spec, config, manifest_path, output_dir,
        )

        def _fail_if_called(*a, **k):
            raise AssertionError("un fold déjà complet (SKIP) ne doit jamais être ré-exécuté")

        monkeypatch.setattr(walk_forward_module, "execute_walk_forward_fold", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "run_fold_test", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "run_fold_train", _fail_if_called)

        resumed, resumed_aggregate = resume_walk_forward_run(
            zone, spec, None, config, df, manifest_path, output_dir,
        )

        assert resumed.stopped_early is False
        assert [r.fold_id for r in resumed.fold_results] == [f.fold_id for f in folds]
        for original, reloaded in zip(results, resumed.fold_results):
            assert reloaded.score_test == pytest.approx(original.score_test)
            assert reloaded.n_trades == original.n_trades
        assert resumed_aggregate.n_folds == len(folds)

    def test_fold_with_frozen_selection_but_no_test_result_replays_only_the_test(
        self, tmp_path, monkeypatch,
    ):
        df, spec, zone, folds = _real_two_fold_setup()
        fold0, fold1 = folds
        config = None
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0, config=config)

        fake1 = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake1)
        _patch_score_by_net_ret(monkeypatch)
        all_results, _sensitivity = run_fold_train(fold1, config, df)
        selection1 = select_fold_top1(fold1, all_results, config)

        outcome = WalkForwardRunOutcome(fold_results=(r0,), stopped_early=False)
        aggregate = build_aggregate_result((r0,))
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, (a0,), aggregate, spec, config, manifest_path, output_dir,
        )

        # fold1 : TRAIN mené jusqu'à une FoldSelection figée, TEST jamais exécuté (interruption
        # simulée) — persisté manuellement avec la MÊME primitive que persist_walk_forward_run()
        # (atomic_json_store.save_atomic(), jamais un open()/json.dump() direct).
        fold1_dir = output_dir / "folds" / fold1.fold_id
        walk_forward_module.save_atomic(
            fold1_dir / "definition.json", dataclasses.asdict(fold1), "test",
        )
        walk_forward_module.save_atomic(
            fold1_dir / "selection.json", dataclasses.asdict(selection1), "test",
        )

        def _fail_if_train_called(*a, **k):
            raise AssertionError("REPLAY_TEST ne doit jamais relancer une recherche TRAIN")

        monkeypatch.setattr(walk_forward_module, "run_fold_train", _fail_if_train_called)

        captured_selections = []
        real_run_fold_test = walk_forward_module.run_fold_test

        def spy_run_fold_test(fold, selection, base_config, df_):
            captured_selections.append(selection)
            return real_run_fold_test(fold, selection, base_config, df_)

        monkeypatch.setattr(walk_forward_module, "run_fold_test", spy_run_fold_test)

        resumed, _resumed_aggregate = resume_walk_forward_run(
            zone, spec, None, config, df, manifest_path, output_dir,
        )

        assert len(captured_selections) == 1
        assert captured_selections[0] == selection1
        assert [r.fold_id for r in resumed.fold_results] == [fold0.fold_id, fold1.fold_id]
        assert resumed.fold_results[1].selection == selection1

    def test_fold_with_no_persisted_state_is_redone_entirely(self, tmp_path, monkeypatch):
        df, spec, zone, folds = _real_two_fold_setup()
        fold0, fold1 = folds
        config = None
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0, config=config)
        outcome = WalkForwardRunOutcome(fold_results=(r0,), stopped_early=False)
        aggregate = build_aggregate_result((r0,))
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, (a0,), aggregate, spec, config, manifest_path, output_dir,
        )
        # fold1 : rien persisté du tout.

        fake_redo = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake_redo)
        _patch_score_by_net_ret(monkeypatch)

        resumed, resumed_aggregate = resume_walk_forward_run(
            zone, spec, None, config, df, manifest_path, output_dir,
        )

        assert [r.fold_id for r in resumed.fold_results] == [fold0.fold_id, fold1.fold_id]
        assert fake_redo.calls, "fold1 doit être réellement exécuté (TRAIN+TEST)"
        assert isinstance(resumed.fold_results[1], FoldResult)
        assert resumed_aggregate.n_folds == 2

    def test_train_interrupted_with_definition_only_reuses_already_tested_candidates(
        self, tmp_path, monkeypatch,
    ):
        """ADR 0021 Décision 12 : « un TRAIN interrompu réutilise les candidats déjà exécutés
        (fingerprint identique) ». Cas ADR-nommé « TRAIN interrompu », DISTINCT de
        `test_fold_with_no_persisted_state_is_redone_entirely` (« rien persisté du tout ») : ici
        `definition.json` ET un candidat TRAIN déjà exécuté (`train_progress.csv`, mécanisme réel
        de reprise Slice 5) sont présents pour fold1, mais AUCUN `selection.json` (le TRAIN a été
        interrompu EN COURS, pas avant de commencer) — `decide_fold_resume_action()` retourne donc
        toujours `RESUME_ACTION_REDO` (même triplet SKIP/REPLAY_TEST/REDO qu'avant cette tranche),
        mais l'EXÉCUTION de ce REDO doit réutiliser réellement le candidat déjà exécuté plutôt que
        de tout refaire depuis zéro (review indépendante, tentative 3, finding MAJEUR)."""
        df, spec, zone, folds = _real_two_fold_setup()
        fold0, fold1 = folds
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0, config=config)
        outcome = WalkForwardRunOutcome(fold_results=(r0,), stopped_early=False)
        aggregate = build_aggregate_result((r0,))
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, (a0,), aggregate, spec, config, manifest_path, output_dir,
        )

        # fold1 : TRAIN interrompu EN COURS — definition.json persisté (primitive Slice 4), UN des
        # 3 candidats déclarés déjà exécuté et persisté via le mécanisme de continuité Slice 5
        # (train_progress.csv, jamais selection.json : le TRAIN n'a pas atteint sa fin).
        fold1_dir = output_dir / "folds" / fold1.fold_id
        walk_forward_module.save_atomic(
            fold1_dir / "definition.json", dataclasses.asdict(fold1), "test",
        )
        already_run_params = dict(config.base_params, ema_trend_len=100)
        walk_forward_module._write_train_progress(
            fold1_dir, fold1, config, [{"params": already_run_params, "score": 1.0}],
        )

        assert decide_fold_resume_action(fold1, output_dir).action == RESUME_ACTION_REDO

        fake_redo = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake_redo)
        _patch_score_by_net_ret(monkeypatch)

        resumed, resumed_aggregate = resume_walk_forward_run(
            zone, spec, None, config, df, manifest_path, output_dir,
        )

        fold1_call_params = [c["params"] for c in fake_redo.calls]
        assert already_run_params not in fold1_call_params, (
            "le candidat déjà exécuté avant l'interruption ne doit JAMAIS être réexécuté"
        )
        # 3 candidats déclarés - 1 déjà réutilisé = 2 nouveaux appels TRAIN + 1 appel TEST.
        assert len(fake_redo.calls) == 3
        assert [r.fold_id for r in resumed.fold_results] == [fold0.fold_id, fold1.fold_id]
        assert resumed_aggregate.n_folds == 2
        assert not (fold1_dir / "train_progress.csv").exists(), (
            "l'artefact de continuité doit être nettoyé après un REDO réussi"
        )

    def test_train_interrupted_reuse_is_never_applied_outside_the_proven_safe_modes(
        self, tmp_path, monkeypatch,
    ):
        """Réciproque de `test_train_interrupted_with_definition_only_reuses_already_tested_
        candidates` (review indépendante Slice 5, finding MAJEUR) : `_TRAIN_PROGRESS_REUSE_SAFE_
        MODES` ne contient QUE `{"grid"}` — `mode="single_var"` (`run_mode1()`, PROGRESSIF à
        étages, voir la docstring de `_TRAIN_PROGRESS_REUSE_SAFE_MODES`) doit ignorer un
        `train_progress.csv` par ailleurs valide (même fingerprint de géométrie/config que la
        tentative courante) et repartir d'un REDO complet — jamais réutiliser via `already_tested`
        le candidat déjà exécuté avant l'interruption. Sans ce test, un futur élargissement
        accidentel de `_TRAIN_PROGRESS_REUSE_SAFE_MODES` (ou un bris de la condition `if
        base_config.mode in _TRAIN_PROGRESS_REUSE_SAFE_MODES` dans
        `_redo_fold_reusing_train_candidates()`) romprait silencieusement cet invariant
        scientifique — un Top-1 biaisé pour un mode progressif — sans qu'aucun test rouge ne le
        détecte."""
        df, spec, zone, folds = _real_two_fold_setup()
        fold0, fold1 = folds
        config = _minimal_optimizer_config(mode="single_var", param_ranges=_param_ranges_3_values())
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0, config=config)
        outcome = WalkForwardRunOutcome(fold_results=(r0,), stopped_early=False)
        aggregate = build_aggregate_result((r0,))
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, (a0,), aggregate, spec, config, manifest_path, output_dir,
        )

        # fold1 : mêmes artefacts qu'un TRAIN interrompu EN COURS que le test mode="grid" jumeau
        # ci-dessus (definition.json + un candidat déjà exécuté persisté dans train_progress.csv,
        # même fingerprint de géométrie/config) — seule la valeur de base_config.mode diffère.
        fold1_dir = output_dir / "folds" / fold1.fold_id
        walk_forward_module.save_atomic(
            fold1_dir / "definition.json", dataclasses.asdict(fold1), "test",
        )
        already_run_params = dict(config.base_params, ema_trend_len=100)
        walk_forward_module._write_train_progress(
            fold1_dir, fold1, config, [{"params": already_run_params, "score": 1.0}],
        )

        assert decide_fold_resume_action(fold1, output_dir).action == RESUME_ACTION_REDO

        fake_redo = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake_redo)
        _patch_score_by_net_ret(monkeypatch)

        resumed, resumed_aggregate = resume_walk_forward_run(
            zone, spec, None, config, df, manifest_path, output_dir,
        )

        fold1_call_params = [c["params"] for c in fake_redo.calls]
        assert already_run_params in fold1_call_params, (
            "mode='single_var' n'est pas dans _TRAIN_PROGRESS_REUSE_SAFE_MODES — le candidat "
            "déjà exécuté avant l'interruption doit être RÉÉVALUÉ, jamais sauté via "
            "already_tested (réutilisation prouvée sûre uniquement pour mode='grid')"
        )
        # 3 candidats déclarés, AUCUN sauté (mode non prouvé sûr) + 1 appel TEST.
        assert len(fake_redo.calls) == 4
        assert [r.fold_id for r in resumed.fold_results] == [fold0.fold_id, fold1.fold_id]
        assert resumed_aggregate.n_folds == 2
        assert not (fold1_dir / "train_progress.csv").exists(), (
            "l'artefact de continuité doit être nettoyé après un REDO réussi, même hors mode sûr"
        )

    def test_divergent_fingerprint_is_refused_before_any_fold_is_touched(
        self, tmp_path, monkeypatch,
    ):
        df, spec, zone, folds = _real_two_fold_setup()
        fold0, fold1 = folds
        config = None
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0, config=config)
        outcome = WalkForwardRunOutcome(fold_results=(r0,), stopped_early=False)
        aggregate = build_aggregate_result((r0,))
        manifest_path, _dm = _write_test_data_manifest(tmp_path, content_hash="hash-A")
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, (a0,), aggregate, spec, config, manifest_path, output_dir,
        )

        other_dir = tmp_path / "other"
        other_dir.mkdir()
        other_manifest_path, _dm2 = _write_test_data_manifest(other_dir, content_hash="hash-B")

        def _fail_if_called(*a, **k):
            raise AssertionError("aucun fold ne doit être touché avant la validation du fingerprint")

        monkeypatch.setattr(walk_forward_module, "execute_walk_forward_fold", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "run_fold_test", _fail_if_called)

        with pytest.raises(WalkForwardResumeMismatch):
            resume_walk_forward_run(zone, spec, None, config, df, other_manifest_path, output_dir)

    def test_aggregate_over_the_resumed_outcome_covers_skipped_and_new_folds_together(
        self, tmp_path, monkeypatch,
    ):
        df, spec, zone, folds = _real_two_fold_setup()
        fold0, fold1 = folds
        config = None
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0, config=config)
        outcome = WalkForwardRunOutcome(fold_results=(r0,), stopped_early=False)
        aggregate = build_aggregate_result((r0,))
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, (a0,), aggregate, spec, config, manifest_path, output_dir,
        )

        fake_redo = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake_redo)
        _patch_score_by_net_ret(monkeypatch)

        resumed, returned_aggregate = resume_walk_forward_run(
            zone, spec, None, config, df, manifest_path, output_dir,
        )
        full_aggregate = build_aggregate_result(resumed.fold_results)

        assert full_aggregate.n_folds == 2
        # L'agrégat retourné par resume_walk_forward_run() lui-même (ADR 0021 Décision 12,
        # dernier paragraphe : "puis appelle build_aggregate_result() ... pour produire un
        # agrégat recalculé intégralement") doit être ce MÊME agrégat complet, jamais partiel.
        assert returned_aggregate == full_aggregate

    def test_resuming_with_the_same_validation_run_id_skips_normally(self, tmp_path, monkeypatch):
        """Preuve, en miroir de `test_resuming_with_a_different_validation_run_id_is_refused`, que
        `resume_walk_forward_run()` transmet bien SON PROPRE `validation_run_id` au fingerprint —
        pas seulement `None` par défaut : rejouer la MÊME valeur non-`None` que la persistance
        originale doit rester un SKIP normal, jamais un faux positif."""
        df, spec, zone, folds = _real_two_fold_setup()
        config = None
        results, artifacts_list = [], []
        for fold in folds:
            r, a, config, _fake = _execute_persistable_fold(monkeypatch, df, fold, config=config)
            results.append(r)
            artifacts_list.append(a)
        outcome = WalkForwardRunOutcome(fold_results=tuple(results), stopped_early=False)
        aggregate = build_aggregate_result(tuple(results))
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, tuple(artifacts_list), aggregate, spec, config, manifest_path, output_dir,
            validation_run_id="wf_run_same",
        )

        def _fail_if_called(*a, **k):
            raise AssertionError("un fold déjà complet (SKIP) ne doit jamais être ré-exécuté")

        monkeypatch.setattr(walk_forward_module, "execute_walk_forward_fold", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "run_fold_test", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "run_fold_train", _fail_if_called)

        resumed, resumed_aggregate = resume_walk_forward_run(
            zone, spec, None, config, df, manifest_path, output_dir,
            validation_run_id="wf_run_same",
        )

        assert [r.fold_id for r in resumed.fold_results] == [f.fold_id for f in folds]
        assert resumed_aggregate.n_folds == len(folds)

    def test_resuming_with_a_different_validation_run_id_is_refused(self, tmp_path, monkeypatch):
        """Correction review indépendante tentative 10, finding MAJEUR : sans cette garde, une
        reprise avec un `validation_run_id` différent de la tentative originale mélangerait, au
        sein d'un même `WalkForwardRunOutcome`, des folds SKIP dont le `fold_seed` a été figé sous
        l'ancien `validation_run_id` et des folds REDO/REPLAY_TEST dérivés du nouveau — une
        incohérence scientifique jamais détectée avant cette correction."""
        df, spec, zone, folds = _real_two_fold_setup()
        fold0 = folds[0]
        config = None
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0, config=config)
        outcome = WalkForwardRunOutcome(fold_results=(r0,), stopped_early=False)
        aggregate = build_aggregate_result((r0,))
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, (a0,), aggregate, spec, config, manifest_path, output_dir,
            validation_run_id="wf_run_original",
        )

        def _fail_if_called(*a, **k):
            raise AssertionError("aucun fold ne doit être touché avant la validation du fingerprint")

        monkeypatch.setattr(walk_forward_module, "execute_walk_forward_fold", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "run_fold_test", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "run_fold_train", _fail_if_called)

        with pytest.raises(WalkForwardResumeMismatch):
            resume_walk_forward_run(
                zone, spec, None, config, df, manifest_path, output_dir,
                validation_run_id="wf_run_different",
            )

    def test_geometry_drift_on_a_later_fold_is_caught_before_an_earlier_fold_is_really_executed(
        self, tmp_path, monkeypatch,
    ):
        """`validation_zone`/`readiness_spec` ne font PAS partie du fingerprint run-level de
        `check_resume_fingerprint()` (ils ne sont pas des clés de `manifest.json`) — une dérive de
        géométrie n'est détectable que PAR FOLD, via `decide_fold_resume_action()`. Revue
        indépendante Slice 5 : cette détection par fold doit intervenir AVANT tout backtest réel,
        jamais entrelacée avec l'exécution — sinon un fold antérieur (ici fold0, REDO) serait
        réellement ré-exécuté avant que la dérive du fold suivant (fold1) ne soit détectée."""
        df, spec, zone, folds = _real_two_fold_setup()
        fold0, fold1 = folds
        # fold1 : TRAIN mené jusqu'à une FoldSelection figée (comme un TEST interrompu), mais le
        # definition.json persisté ne correspond PLUS à ce que compute_fold_definitions()
        # recalcule pour ce fold_id (dérive de géométrie simulée) — un mismatch détectable
        # seulement au travers de decide_fold_resume_action(), jamais de check_resume_fingerprint().
        drifted_definition = dataclasses.asdict(fold1)
        drifted_definition["train_start"] = "2019-01-01T00:00:00+00:00"
        fold1_dir = tmp_path / "walk_forward" / "folds" / fold1.fold_id
        walk_forward_module.save_atomic(fold1_dir / "definition.json", drifted_definition, "test")
        walk_forward_module.save_atomic(
            fold1_dir / "selection.json", dataclasses.asdict(_fold_selection(fold1)), "test",
        )
        # fold0 : rien persisté — nécessiterait un REDO (TRAIN+TEST réels) si jamais exécuté.
        output_dir = tmp_path / "walk_forward"
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())
        manifest_path, _dm = _write_test_data_manifest(tmp_path)

        def _fail_if_called(*a, **k):
            raise AssertionError(
                "fold0 (REDO) ne doit jamais être réellement exécuté avant que la dérive de "
                "géométrie de fold1 ne soit détectée"
            )

        monkeypatch.setattr(walk_forward_module, "execute_walk_forward_fold", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "run_fold_test", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "run_fold_train", _fail_if_called)

        with pytest.raises(FoldArtifactConflict):
            resume_walk_forward_run(zone, spec, None, config, df, manifest_path, output_dir)

    def test_shrunk_validation_zone_leaves_an_orphaned_fold_dir_and_is_refused(
        self, tmp_path, monkeypatch,
    ):
        """Review indépendante Slice 5, finding MAJEUR : `validation_zone`/`readiness_spec` ne
        font PAS partie du fingerprint run-level de `check_resume_fingerprint()` (ce ne sont pas
        des clés de `manifest.json`) — si une tentative ultérieure fournit une `validation_zone`
        plus restrictive que celle qui a produit l'état disque (donc MOINS de folds recalculés par
        `compute_fold_definitions()`), un `fold_dir` déjà persisté au-delà de ce nouveau compte ne
        doit JAMAIS être silencieusement ignoré : `resume_walk_forward_run()` itérerait sinon sur
        le sous-ensemble recalculé, renverrait `stopped_early=False`, et
        `build_aggregate_result()` produirait un agrégat présenté comme COMPLET en ignorant ce
        fold — exactement l'agrégat partiel silencieux que Décision 12 (dernier paragraphe)
        exclut explicitement."""
        df, spec, zone, folds = _real_two_fold_setup()
        fold0, fold1 = folds
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0, config=config)
        r1, a1, _c1, _f1 = _execute_persistable_fold(monkeypatch, df, fold1, config=config)
        outcome = WalkForwardRunOutcome(fold_results=(r0, r1), stopped_early=False)
        aggregate = build_aggregate_result((r0, r1))
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, (a0, a1), aggregate, spec, config, manifest_path, output_dir,
        )

        # Fold "orphelin" : simule l'état disque résiduel d'une tentative ANTÉRIEURE menée sous
        # une validation_zone plus large (3 folds) — jamais réellement exécuté par ce test, juste
        # fabriqué, pour être absent de la géométrie que la tentative COURANTE (zone/folds
        # ci-dessus, 2 folds) recalcule.
        orphan_dir = output_dir / "folds" / "fold_002"
        walk_forward_module.save_atomic(
            orphan_dir / "selection.json", dataclasses.asdict(_fold_selection(fold1)), "test",
        )

        def _fail_if_called(*a, **k):
            raise AssertionError(
                "aucun fold ne doit être touché avant la détection du fold_dir orphelin"
            )

        monkeypatch.setattr(walk_forward_module, "execute_walk_forward_fold", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "run_fold_test", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "run_fold_train", _fail_if_called)

        with pytest.raises(WalkForwardOrphanedFoldArtifacts):
            resume_walk_forward_run(zone, spec, None, config, df, manifest_path, output_dir)

    def test_orphaned_fold_dir_without_selection_or_test_result_is_not_flagged(
        self, tmp_path, monkeypatch,
    ):
        """Symétrique du test ci-dessus : un `fold_dir` hors géométrie courante qui ne porte QUE
        `train_progress.csv`/`definition.json` (jamais de TRAIN mené jusqu'à une `FoldSelection`)
        ne représente rien qui serait silencieusement perdu de l'agrégat — `_fold_has_persisted_
        state()` ne doit se déclencher que sur `selection.json`/`test_result.json`, jamais sur la
        seule présence du répertoire."""
        df, spec, zone, folds = _real_two_fold_setup()
        fold0, fold1 = folds
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0, config=config)
        r1, a1, _c1, _f1 = _execute_persistable_fold(monkeypatch, df, fold1, config=config)
        outcome = WalkForwardRunOutcome(fold_results=(r0, r1), stopped_early=False)
        aggregate = build_aggregate_result((r0, r1))
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, (a0, a1), aggregate, spec, config, manifest_path, output_dir,
        )

        orphan_dir = output_dir / "folds" / "fold_002"
        orphan_dir.mkdir(parents=True)
        (orphan_dir / "train_progress.csv").write_text("fold_fingerprint,params_json,score\n")

        resumed, resumed_aggregate = resume_walk_forward_run(
            zone, spec, None, config, df, manifest_path, output_dir,
        )

        assert [r.fold_id for r in resumed.fold_results] == [fold0.fold_id, fold1.fold_id]
        assert resumed_aggregate.n_folds == 2

    def test_redo_with_reused_train_candidates_reconstructs_the_same_selection_as_a_full_redo(
        self, tmp_path, monkeypatch,
    ):
        """MAJEUR (review indépendante) : la docstring de `_redo_fold_reusing_train_candidates()`
        revendique explicitement reconstruire la MÊME `FoldSelection` Top-1 qu'un REDO complet
        aurait produite — jamais une sélection biaisée par l'ORDRE de fusion `reused + new`. Les
        tests `test_train_interrupted_with_definition_only_reuses_already_tested_candidates`/
        `test_train_interrupted_reuse_is_never_applied_outside_the_proven_safe_modes` ne vérifient
        QUE le nombre/les params des appels `engine.run_backtest` — jamais que le `FoldResult`
        obtenu APRÈS réutilisation est identique à celui d'un run de référence non interrompu sur
        le même fold/mêmes 3 candidats. Preuve directe ici : (1) un REDO plein via
        `execute_walk_forward_fold()` (Slice 2, inchangée) sert de référence, (2) une reprise avec
        1 des 3 candidats déjà exécuté (`train_progress.csv`) recalcule fold1, (3) les deux
        `FoldSelection`/`score_test`/`n_trades` doivent être IDENTIQUES."""
        df, spec, zone, folds = _real_two_fold_setup()
        fold0, fold1 = folds
        config = _minimal_optimizer_config(mode="grid", param_ranges=_param_ranges_3_values())

        # Référence : REDO complet non interrompu de fold1, jamais via resume_walk_forward_run().
        reference_fake = _ScoreByParamRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", reference_fake)
        _patch_score_by_net_ret(monkeypatch)
        reference_result = execute_walk_forward_fold(fold1, config, df)

        # fold0 complet et persisté normalement (fingerprint run-level valide + un fold SKIP).
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0, config=config)
        outcome = WalkForwardRunOutcome(fold_results=(r0,), stopped_early=False)
        aggregate = build_aggregate_result((r0,))
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, (a0,), aggregate, spec, config, manifest_path, output_dir,
        )

        # fold1 : TRAIN interrompu EN COURS — un des 3 candidats déclarés (ema_trend_len=100) déjà
        # exécuté et persisté via train_progress.csv, même géométrie/config que la référence.
        fold1_dir = output_dir / "folds" / fold1.fold_id
        walk_forward_module.save_atomic(
            fold1_dir / "definition.json", dataclasses.asdict(fold1), "test",
        )
        already_run_params = dict(config.base_params, ema_trend_len=100)
        walk_forward_module._write_train_progress(
            fold1_dir, fold1, config, [{"params": already_run_params, "score": 1.0}],
        )

        resume_fake = _ScoreByParamRunBacktest()
        monkeypatch.setattr(engine, "run_backtest", resume_fake)

        resumed, _resumed_aggregate = resume_walk_forward_run(
            zone, spec, None, config, df, manifest_path, output_dir,
        )

        resumed_fold1 = resumed.fold_results[1]
        assert resumed_fold1.selection == reference_result.selection
        assert resumed_fold1.score_test == pytest.approx(reference_result.score_test)
        assert resumed_fold1.n_trades == reference_result.n_trades

    def test_stop_flag_fn_between_folds_stops_before_untouched_folds_with_partial_results(
        self, tmp_path, monkeypatch,
    ):
        """MAJEUR (review indépendante) : `resume_walk_forward_run()` réimplémente indépendamment
        la même barrière `stop_flag_fn` INTER-fold que `run_walk_forward()` (déjà testée via
        `TestRunWalkForwardOrchestration.test_stop_flag_fn_between_folds_returns_partial_results_
        marked_stopped`) — mais aucun test ne couvrait encore cette branche neuve pour la reprise.
        Preuve : fold0 (SKIP, déjà persisté) est bien inclus dans le résultat partiel ; fold1
        (REDO, rien persisté) n'est JAMAIS touché — ni TRAIN ni TEST, ni même
        `decide_fold_resume_action()` ré-exécuté — quand `stop_flag_fn` interrompt la boucle juste
        avant lui ; `stopped_early` reflète l'arrêt et l'agrégat ne porte que sur le préfixe déjà
        décidé/exécuté."""
        df, spec, zone, folds = _real_two_fold_setup()
        fold0, fold1 = folds
        config = None
        r0, a0, config, _f0 = _execute_persistable_fold(monkeypatch, df, fold0, config=config)
        outcome = WalkForwardRunOutcome(fold_results=(r0,), stopped_early=False)
        aggregate = build_aggregate_result((r0,))
        manifest_path, _dm = _write_test_data_manifest(tmp_path)
        output_dir = tmp_path / "walk_forward"
        persist_walk_forward_run(
            outcome, (a0,), aggregate, spec, config, manifest_path, output_dir,
        )
        # fold1 : rien persisté — nécessiterait un REDO (TRAIN+TEST réels) s'il était atteint.

        def _fail_if_called(*a, **k):
            raise AssertionError(
                "fold1 ne doit jamais être touché après l'arrêt anticipé avant lui"
            )

        monkeypatch.setattr(walk_forward_module, "run_fold_train", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "run_fold_test", _fail_if_called)
        monkeypatch.setattr(walk_forward_module, "execute_walk_forward_fold", _fail_if_called)

        stop_calls = []

        def stop_flag_fn():
            stop_calls.append(1)
            return len(stop_calls) > 1  # False avant fold0 (traité), True avant fold1 (arrêt).

        resumed, resumed_aggregate = resume_walk_forward_run(
            zone, spec, None, config, df, manifest_path, output_dir, stop_flag_fn=stop_flag_fn,
        )

        assert resumed.stopped_early is True
        assert [r.fold_id for r in resumed.fold_results] == [fold0.fold_id]
        assert resumed.fold_results[0].score_test == pytest.approx(r0.score_test)
        assert resumed_aggregate.n_folds == 1


# ══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 8 — build_walk_forward_validation_run() : assemblage d'une ValidationRun réelle
# à partir d'un WalkForwardRunOutcome/AggregateResult déjà obtenus (mirroring exact du précédent
# établi par validation_oos.py::run_oos_validation() côté "oos"). Ne persiste rien elle-même.
# ══════════════════════════════════════════════════════════════════════════════


def _wf_split_plan():
    return build_dataset_split_plan(
        split_plan_id="split_perfect_revolution_v1_walk_forward_v2",
        dataset_snapshot_id="local_csv:sha256:" + "cd" * 32,
        train=build_split_boundary("2017-10-31T00:00:00+00:00", "2020-11-30T00:00:00+00:00"),
        validation=build_split_boundary("2020-11-30T00:00:00+00:00", "2025-05-19T00:00:00+00:00"),
        final_holdout=build_split_boundary("2025-05-19T00:00:00+00:00", "2026-05-20T00:00:00+00:00"),
    )


class TestBuildWalkForwardValidationRun:
    """`build_walk_forward_validation_run()` — mirroring `run_oos_validation()` côté Walk-Forward :
    reçoit `outcome`/`aggregate` déjà obtenus séparément, jamais recalculés/ré-exécutés ici."""

    def _outcome_and_aggregate(self):
        zone = _zone("2023-01-01T00:00:00+00:00", "2023-12-01T00:00:00+00:00")
        fold0 = _wf_fold(
            train_start="2023-01-01T00:00:00+00:00", boundary="2023-06-01T00:00:00+00:00",
            test_end="2023-12-01T00:00:00+00:00", index=0, is_last=True,
        )
        r0 = _fold_result_stub(fold0, net_ret_pct=5.0, n_trades=3)
        outcome = WalkForwardRunOutcome(fold_results=(r0,), stopped_early=False)
        aggregate = build_aggregate_result((r0,))
        return outcome, aggregate

    def test_produces_a_validation_run_with_the_expected_walk_forward_shape(self):
        outcome, aggregate = self._outcome_and_aggregate()
        spec = build_walk_forward_specification(base_params={"or_start_h": 15, "or_start_m": 30})
        split_plan = _wf_split_plan()

        run = build_walk_forward_validation_run(
            outcome, aggregate, spec, split_plan,
            research_run_id="rr_wf_slice8", validation_run_id="vr_wf_slice8",
            strategy_name="NASDAQ Perfect Revolution V1.1", strategy_params={"or_start_h": 15},
        )

        assert run.validation_type == VALIDATION_TYPE_WALK_FORWARD
        assert run.split_plan_id == split_plan.split_plan_id
        assert run.dataset_snapshot_id == split_plan.dataset_snapshot_id
        assert run.specification == spec
        assert isinstance(run.evidence, WalkForwardEvidence)
        assert run.evidence.fold_results == outcome.fold_results
        assert run.evidence.aggregate == aggregate
        assert run.research_run_id == "rr_wf_slice8"
        assert run.validation_run_id == "vr_wf_slice8"
        assert run.strategy_name == "NASDAQ Perfect Revolution V1.1"
        assert run.strategy_params == {"or_start_h": 15}

    def test_verdict_is_inconclusive_when_the_spec_has_no_verdict_policy(self):
        outcome, aggregate = self._outcome_and_aggregate()
        spec = build_walk_forward_specification(
            base_params={"or_start_h": 15, "or_start_m": 30}, verdict_policy_id=None,
        )
        split_plan = _wf_split_plan()

        run = build_walk_forward_validation_run(
            outcome, aggregate, spec, split_plan,
            research_run_id="rr_wf_slice8b", validation_run_id="vr_wf_slice8b",
            strategy_name="NASDAQ Perfect Revolution V1.1", strategy_params={},
        )

        assert run.evidence.scientific_verdict == "INCONCLUSIVE"

    def test_round_trips_through_save_and_load_validation_run(self, tmp_path):
        """Round-trip du contenu significatif — pas une égalité stricte d'objet : `fold_results`
        redevient une `list` de `dict` après un aller-retour JSON générique (même limitation
        connue, non spécifique à cette tranche, que
        test_save_and_load_validation_run_round_trips_a_walk_forward_run() dans
        tests/test_validation_run.py, Slice 6)."""
        outcome, aggregate = self._outcome_and_aggregate()
        spec = build_walk_forward_specification(base_params={"or_start_h": 15, "or_start_m": 30})
        split_plan = _wf_split_plan()

        run = build_walk_forward_validation_run(
            outcome, aggregate, spec, split_plan,
            research_run_id="rr_wf_slice8c", validation_run_id="vr_wf_slice8c",
            strategy_name="NASDAQ Perfect Revolution V1.1", strategy_params={"or_start_h": 15},
        )

        path = save_validation_run(tmp_path / "validation_run.json", run)
        loaded = load_validation_run(path)

        assert loaded.validation_run_id == run.validation_run_id
        assert loaded.research_run_id == run.research_run_id
        assert loaded.split_plan_id == run.split_plan_id
        assert loaded.dataset_snapshot_id == run.dataset_snapshot_id
        assert loaded.validation_type == run.validation_type
        assert loaded.strategy_name == run.strategy_name
        assert loaded.strategy_params == run.strategy_params
        assert loaded.specification.geometry == run.specification.geometry
        assert loaded.specification.base_params == run.specification.base_params
        assert loaded.evidence.execution_status == run.evidence.execution_status
        assert loaded.evidence.scientific_verdict == run.evidence.scientific_verdict
        assert list(loaded.evidence.verdict_reasons) == list(run.evidence.verdict_reasons)
        assert len(loaded.evidence.fold_results) == len(run.evidence.fold_results)
        assert loaded.evidence.fold_results[0]["fold_id"] == run.evidence.fold_results[0].fold_id

    def test_does_not_persist_anything_itself(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        outcome, aggregate = self._outcome_and_aggregate()
        spec = build_walk_forward_specification(base_params={"or_start_h": 15, "or_start_m": 30})
        split_plan = _wf_split_plan()

        build_walk_forward_validation_run(
            outcome, aggregate, spec, split_plan,
            research_run_id="rr_wf_slice8d", validation_run_id="vr_wf_slice8d",
            strategy_name="NASDAQ Perfect Revolution V1.1", strategy_params={},
        )

        assert list(tmp_path.iterdir()) == []
