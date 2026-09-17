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

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_split import build_split_boundary
from strategy_contracts import DailyStateReadiness
from validation_run import FoldDefinition
from walk_forward import (
    WALK_FORWARD_SEMANTICS_VERSION,
    DatasetTooShortForWalkForward,
    FinalHoldoutOverlapError,
    InsufficientWarmupHistory,
    OosOverlapError,
    UnsupportedWalkForwardGeometry,
    WalkForwardSemanticsMismatch,
    build_walk_forward_specification,
    check_no_final_holdout_overlap,
    check_no_oos_overlap,
    check_warmup_sufficiency,
    compute_fold_definitions,
    detect_partial_tail,
    validate_resume_walk_forward_semantics,
)
from optimizer import NoStateReadyBoundary

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
