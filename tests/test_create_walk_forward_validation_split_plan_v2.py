"""
tests/test_create_walk_forward_validation_split_plan_v2.py — AF-V-02 Slice 7, allocation
VALIDATION de 54 mois / 5 folds (ADR 0021 Décision 8, décision d'allocation explicite de
l'utilisateur, 2026-09-21) — mirroring exact de
tests/test_create_walk_forward_validation_split_plan.py (Slice 1, v1), jamais modifié ici.

Teste uniquement la fonction PURE de dérivation du nouveau plan v2 (aucun accès disque) — le plan
historique réel n'est jamais lu ni modifié ici, un plan synthétique équivalent est utilisé pour ne
dépendre d'aucun état local (`results/` est hors dépôt, `.gitignore`).
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_split import build_dataset_split_plan, build_split_boundary
from scripts.create_walk_forward_validation_split_plan_v2 import (
    NEW_SPLIT_PLAN_ID,
    VALIDATION_MONTHS,
    build_walk_forward_validation_split_plan_v2,
)

_SNAPSHOT_ID = "local_csv:sha256:" + "cd" * 32


def _historical_plan():
    return build_dataset_split_plan(
        split_plan_id="split_perfect_revolution_v1_final_holdout",
        dataset_snapshot_id=_SNAPSHOT_ID,
        train=build_split_boundary("2017-10-31T00:00:00+00:00", "2025-05-19T00:00:00+00:00"),
        final_holdout=build_split_boundary("2025-05-19T00:00:00+00:00", "2026-05-20T00:00:00+00:00"),
    )


def test_new_plan_has_a_new_split_plan_id_distinct_from_the_historical_one():
    historical = _historical_plan()
    new_plan = build_walk_forward_validation_split_plan_v2(historical)
    assert new_plan.split_plan_id == NEW_SPLIT_PLAN_ID
    assert new_plan.split_plan_id != historical.split_plan_id


def test_new_plan_split_plan_id_is_distinct_from_the_v1_walk_forward_plan():
    historical = _historical_plan()
    new_plan = build_walk_forward_validation_split_plan_v2(historical)
    assert new_plan.split_plan_id != "split_perfect_revolution_v1_walk_forward_v1"


def test_new_plan_reuses_the_same_dataset_snapshot_id():
    historical = _historical_plan()
    new_plan = build_walk_forward_validation_split_plan_v2(historical)
    assert new_plan.dataset_snapshot_id == historical.dataset_snapshot_id


def test_new_plan_preserves_final_holdout_exactly_unchanged():
    """Règle absolue ADR 0021 Décision 8 : FINAL_HOLDOUT n'est jamais déplacé."""
    historical = _historical_plan()
    new_plan = build_walk_forward_validation_split_plan_v2(historical)
    assert new_plan.final_holdout == historical.final_holdout


def test_new_plan_populates_validation_immediately_before_final_holdout():
    historical = _historical_plan()
    new_plan = build_walk_forward_validation_split_plan_v2(historical)
    assert new_plan.validation is not None
    assert new_plan.validation.end == historical.final_holdout.start


def test_new_plan_train_zone_is_shortened_but_starts_the_same():
    historical = _historical_plan()
    new_plan = build_walk_forward_validation_split_plan_v2(historical)
    assert new_plan.train.start == historical.train.start
    assert new_plan.train.end == new_plan.validation.start


def test_validation_zone_duration_matches_the_documented_allocation():
    """54 mois = train_period(24) + 5 * step_period(6) — exactement 5 folds, zéro reliquat pour
    cette allocation précise (voir docstring du script)."""
    import pandas as pd
    historical = _historical_plan()
    new_plan = build_walk_forward_validation_split_plan_v2(historical)
    start = pd.Timestamp(new_plan.validation.start)
    end = pd.Timestamp(new_plan.validation.end)
    assert (start + pd.DateOffset(months=VALIDATION_MONTHS)) == end


def test_validation_zone_yields_exactly_five_folds_with_zero_remainder():
    """Preuve d'intégration : la géométrie Rolling par défaut, appliquée à ce plan, génère
    exactement 5 folds sans reliquat."""
    from walk_forward import build_walk_forward_specification, compute_fold_definitions, detect_partial_tail

    historical = _historical_plan()
    new_plan = build_walk_forward_validation_split_plan_v2(historical)
    spec = build_walk_forward_specification(base_params={"or_start_h": 15, "or_start_m": 30})

    folds = compute_fold_definitions(new_plan.validation, spec, readiness_spec=None)

    assert len(folds) == 5
    assert detect_partial_tail(new_plan.validation, spec, n_folds_generated=5) is None


def test_new_plan_does_not_mutate_the_historical_plan_object():
    historical = _historical_plan()
    build_walk_forward_validation_split_plan_v2(historical)
    # dataclass frozen : toute tentative de mutation lèverait — ici on vérifie simplement que les
    # valeurs originales sont restées accessibles et inchangées après l'appel.
    assert historical.train.end == "2025-05-19T00:00:00+00:00"
    assert historical.validation is None
