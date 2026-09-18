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

import hashlib
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_split import build_split_boundary
from engine import _add_market_time_columns
from strategy_contracts import DailyStateReadiness
from validation_run import (
    AggregateResult,
    FoldDefinition,
    FoldResult,
    FoldSelection,
    WalkForwardRunOutcome,
)
from walk_forward import (
    WALK_FORWARD_SEMANTICS_VERSION,
    DatasetTooShortForWalkForward,
    FinalHoldoutOverlapError,
    FoldTestExecutionFailed,
    InsufficientWarmupHistory,
    NoEligibleTrainCandidate,
    NonDeterministicSearchWithoutSeed,
    OosOverlapError,
    UnsupportedWalkForwardGeometry,
    WalkForwardSemanticsMismatch,
    build_aggregate_result,
    build_walk_forward_specification,
    check_no_final_holdout_overlap,
    check_no_oos_overlap,
    check_warmup_sufficiency,
    compute_fold_definitions,
    detect_partial_tail,
    execute_walk_forward_fold,
    run_fold_test,
    run_fold_train,
    run_walk_forward,
    select_fold_top1,
    validate_resume_walk_forward_semantics,
)
import walk_forward as walk_forward_module
import optimizer
from optimizer import (
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
