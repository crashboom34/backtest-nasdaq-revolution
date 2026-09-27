"""
tests/test_gate_v_campaign.py — AF-V-08 Slice 1 : GateVCampaignPlan + build_gate_v_campaign_plan()
Niveau A (ADR 0024 Décisions 1-5, partie Niveau A uniquement).

Aucune donnée de marché, aucun Optimizer, aucun backtest — toute la géométrie de folds est produite
par `walk_forward.compute_fold_definitions()` (fonction PURE déjà existante, ADR 0021) sur des
`DatasetSplitPlan` synthétiques construits ici avec `tmp_path` uniquement (jamais sous le vrai
`results/` du dépôt, qui contient déjà des `DatasetSplitPlan` réels).
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_v_campaign
from dataset_split import build_dataset_split_plan, build_split_boundary, save_dataset_split_plan
from validation_run import (
    MONTE_CARLO_SEMANTICS_VERSION,
    PARAMETER_STABILITY_SEMANTICS_VERSION,
    VALIDATION_TYPE_OOS,
    VALIDATION_TYPE_WALK_FORWARD,
    WalkForwardEvidence,
    WalkForwardSpecification,
    build_oos_validation_evidence,
    build_oos_validation_specification,
    build_validation_run,
    save_validation_run,
)
from walk_forward import WALK_FORWARD_SEMANTICS_VERSION
from gate_v_campaign import (
    GateVCampaignPlan,
    build_gate_v_campaign_plan,
    load_gate_v_campaign_plan,
)

_SNAPSHOT_ID = "local_csv:sha256:" + "cd" * 32
_BASE_PARAMS = {"or_start_h": 15, "or_start_m": 30}


def _boundary(start, end):
    return build_split_boundary(start=start, end=end)


def _save_split_plan(tmp_path, *, plan_id="plan_a", snapshot_id=_SNAPSHOT_ID, with_validation=True):
    kwargs = dict(
        split_plan_id=plan_id,
        dataset_snapshot_id=snapshot_id,
        train=_boundary("2018-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00"),
        # SplitBoundary terminale obligatoire du DatasetSplitPlan (contrat dataset_split.py, sans
        # rapport avec gate_v_campaign.py qui ne la lit jamais) — jamais consultée par ce module.
        final_holdout=_boundary("2023-01-01T00:00:00+00:00", "2023-06-01T00:00:00+00:00"),
    )
    if with_validation:
        kwargs["validation"] = _boundary(
            "2020-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00"
        )
    plan = build_dataset_split_plan(**kwargs)
    path = tmp_path / "split_plan.json"
    save_dataset_split_plan(path, plan)
    return path


def _kwargs(tmp_path, **overrides):
    split_plan_path = overrides.pop("split_plan_path", None)
    if split_plan_path is None:
        split_plan_path = _save_split_plan(tmp_path / "split")
    base = dict(
        campaign_id="campaign_a",
        research_run_id="run_a",
        dataset_snapshot_id=_SNAPSHOT_ID,
        split_plan_id="plan_a",
        strategy_name="Perfect Revolution V1",
        base_params=dict(_BASE_PARAMS),
        search_mode="general",
        search_space_hash="hash_abc123",
        budget_per_fold=50,
        split_plan_path=split_plan_path,
        job_dir=tmp_path / "job",
    )
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# Champs obligatoires manquants/vides — ValueError individuel (ADR 0024 Décision 3)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("field", ["campaign_id", "research_run_id", "dataset_snapshot_id",
                                    "split_plan_id", "strategy_name"])
@pytest.mark.parametrize("bad_value", ["", "   ", None])
def test_missing_required_string_field_raises_value_error(tmp_path, field, bad_value):
    kwargs = _kwargs(tmp_path, **{field: bad_value})
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**kwargs)


@pytest.mark.parametrize("bad_value", [{}, None, "not_a_dict"])
def test_missing_or_empty_base_params_raises_value_error(tmp_path, bad_value):
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**_kwargs(tmp_path, base_params=bad_value))


def test_invalid_search_mode_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**_kwargs(tmp_path, search_mode="not_a_real_mode"))


@pytest.mark.parametrize("search_mode", ["single_var", "cross_zone", "grid", "general"])
def test_each_real_search_mode_is_accepted(tmp_path, search_mode):
    plan = build_gate_v_campaign_plan(
        **_kwargs(tmp_path, campaign_id=f"campaign_{search_mode}", search_mode=search_mode)
    )
    assert plan.search_mode == search_mode


@pytest.mark.parametrize("bad_value", ["", "   ", None])
def test_missing_search_space_hash_raises_value_error(tmp_path, bad_value):
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**_kwargs(tmp_path, search_space_hash=bad_value))


@pytest.mark.parametrize("bad_value", [0, -1, -50, 1.5, "50", None])
def test_invalid_budget_per_fold_raises_value_error(tmp_path, bad_value):
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**_kwargs(tmp_path, budget_per_fold=bad_value))


# ═══════════════════════════════════════════════════════════════════════════════
# DatasetSplitPlan réel — cohérence et présence de la zone VALIDATION (Décision 5)
# ═══════════════════════════════════════════════════════════════════════════════


def test_nonexistent_split_plan_path_raises_value_error(tmp_path):
    missing = tmp_path / "nowhere" / "split_plan.json"
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**_kwargs(tmp_path, split_plan_path=missing))


def test_dataset_snapshot_id_mismatch_raises_value_error(tmp_path):
    real_path = _save_split_plan(tmp_path / "split", snapshot_id=_SNAPSHOT_ID)
    kwargs = _kwargs(
        tmp_path, split_plan_path=real_path, dataset_snapshot_id="local_csv:sha256:" + "ff" * 32,
    )
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**kwargs)


def test_split_plan_without_validation_zone_raises_value_error(tmp_path):
    path = _save_split_plan(tmp_path / "split", with_validation=False)
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**_kwargs(tmp_path, split_plan_path=path))


def test_split_plan_id_mismatch_with_loaded_plan_raises_value_error(tmp_path):
    real_path = _save_split_plan(tmp_path / "split", plan_id="plan_real")
    kwargs = _kwargs(tmp_path, split_plan_path=real_path, split_plan_id="plan_other")
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# Preuve OOS optionnelle référencée, jamais déclenchée (ADR 0024 Décision 9)
# ═══════════════════════════════════════════════════════════════════════════════


def _save_oos_validation_run(tmp_path, run_id="oos_run_1"):
    spec = build_oos_validation_specification(
        holdout_start="2023-01-01T00:00:00+00:00", holdout_end="2023-06-01T00:00:00+00:00",
    )
    evidence = build_oos_validation_evidence(
        period_start="2023-01-01T00:00:00+00:00", period_end="2023-06-01T00:00:00+00:00",
        n_trades=10, net_ret_pct=5.0,
    )
    run = build_validation_run(
        validation_run_id=run_id, research_run_id="run_a", split_plan_id="plan_a",
        dataset_snapshot_id=_SNAPSHOT_ID, strategy_name="Perfect Revolution V1",
        strategy_params=dict(_BASE_PARAMS), specification=spec, evidence=evidence,
        validation_type=VALIDATION_TYPE_OOS,
    )
    path = tmp_path / "oos_validation_run.json"
    save_validation_run(path, run)
    return path


def _save_walk_forward_validation_run(tmp_path, run_id="wf_run_1"):
    spec = WalkForwardSpecification(
        geometry="rolling", train_period="P24M", test_period="P6M", step_period="P6M",
        allow_partial_last_fold=False, position_transition_policy="flat_each_fold_v1",
        walk_forward_semantics_version=WALK_FORWARD_SEMANTICS_VERSION, base_params=dict(_BASE_PARAMS),
    )
    evidence = WalkForwardEvidence(
        fold_results=(), aggregate=None, execution_status="completed",
        scientific_verdict="INCONCLUSIVE", verdict_reasons=("aucune politique",),
    )
    run = build_validation_run(
        validation_run_id=run_id, research_run_id="run_a", split_plan_id="plan_a",
        dataset_snapshot_id=_SNAPSHOT_ID, strategy_name="Perfect Revolution V1",
        strategy_params=dict(_BASE_PARAMS), specification=spec, evidence=evidence,
        validation_type=VALIDATION_TYPE_WALK_FORWARD,
    )
    path = tmp_path / "wf_validation_run.json"
    save_validation_run(path, run)
    return path


def test_oos_evidence_id_and_path_must_both_be_provided_or_omitted(tmp_path):
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**_kwargs(tmp_path, oos_evidence_validation_run_id="oos_run_1"))


def test_missing_oos_evidence_validation_run_raises_value_error(tmp_path):
    missing = tmp_path / "nowhere" / "validation_run.json"
    kwargs = _kwargs(
        tmp_path, oos_evidence_validation_run_id="oos_run_1",
        oos_evidence_validation_run_path=missing,
    )
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**kwargs)


def test_oos_evidence_of_wrong_validation_type_raises_value_error(tmp_path):
    wf_path = _save_walk_forward_validation_run(tmp_path / "wf")
    kwargs = _kwargs(
        tmp_path, oos_evidence_validation_run_id="wf_run_1",
        oos_evidence_validation_run_path=wf_path,
    )
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**kwargs)


def test_oos_evidence_validation_run_id_mismatch_with_loaded_run_raises_value_error(tmp_path):
    # Le fichier référencé par oos_evidence_validation_run_path contient réellement
    # validation_run_id="oos_run_real" — mais l'appelant fournit un identifiant différent. Doit
    # échouer symétriquement à test_split_plan_id_mismatch_with_loaded_plan_raises_value_error,
    # jamais accepter silencieusement une preuve OOS d'un autre run (ADR 0024 Décision 9).
    oos_path = _save_oos_validation_run(tmp_path / "oos", run_id="oos_run_real")
    kwargs = _kwargs(
        tmp_path, oos_evidence_validation_run_id="oos_run_other",
        oos_evidence_validation_run_path=oos_path,
    )
    with pytest.raises(ValueError):
        build_gate_v_campaign_plan(**kwargs)


def test_real_oos_evidence_is_accepted_and_referenced_on_the_plan(tmp_path):
    oos_path = _save_oos_validation_run(tmp_path / "oos")
    kwargs = _kwargs(
        tmp_path, oos_evidence_validation_run_id="oos_run_1",
        oos_evidence_validation_run_path=oos_path,
    )
    plan = build_gate_v_campaign_plan(**kwargs)
    assert plan.oos_evidence_validation_run_id == "oos_run_1"


# ═══════════════════════════════════════════════════════════════════════════════
# Construction réussie — champs, versions de sémantique, expected_fold_ids
# ═══════════════════════════════════════════════════════════════════════════════


def test_successful_build_populates_semantics_versions_from_real_module_constants(tmp_path):
    plan = build_gate_v_campaign_plan(**_kwargs(tmp_path))
    assert plan.walk_forward_spec_semantics_version == WALK_FORWARD_SEMANTICS_VERSION
    assert plan.monte_carlo_semantics_version == MONTE_CARLO_SEMANTICS_VERSION
    assert plan.parameter_stability_semantics_version == PARAMETER_STABILITY_SEMANTICS_VERSION


def test_successful_build_computes_expected_fold_ids_deterministically(tmp_path):
    plan = build_gate_v_campaign_plan(**_kwargs(tmp_path))
    # VALIDATION [2020-01-01, 2023-01-01) avec train=P24M/test=P6M/step=P6M (défauts) -> 2 folds.
    assert plan.expected_fold_ids == ("fold_000", "fold_001")


def test_optional_policy_ids_default_to_none(tmp_path):
    plan = build_gate_v_campaign_plan(**_kwargs(tmp_path))
    assert plan.monte_carlo_verdict_policy_id is None
    assert plan.parameter_stability_verdict_policy_id is None
    assert plan.walk_forward_verdict_policy_id is None
    assert plan.oos_evidence_validation_run_id is None


def test_campaign_id_distinct_from_research_run_id(tmp_path):
    plan = build_gate_v_campaign_plan(
        **_kwargs(tmp_path, campaign_id="campaign_a", research_run_id="run_a")
    )
    assert plan.campaign_id == "campaign_a"
    assert plan.research_run_id == "run_a"
    assert plan.campaign_id != plan.research_run_id


def test_plan_is_frozen_immutable(tmp_path):
    plan = build_gate_v_campaign_plan(**_kwargs(tmp_path))
    with pytest.raises(FrozenInstanceError):
        plan.campaign_id = "other"


# ═══════════════════════════════════════════════════════════════════════════════
# Géométrie Walk-Forward — exposée explicitement à l'appelant, jamais figée en silence
# (finding MAJEUR, revue architecture — corrigé)
# ═══════════════════════════════════════════════════════════════════════════════


def test_walk_forward_geometry_defaults_match_walk_forward_module_defaults(tmp_path):
    plan = build_gate_v_campaign_plan(**_kwargs(tmp_path))
    assert plan.walk_forward_geometry == "rolling"
    assert plan.walk_forward_train_period == "P24M"
    assert plan.walk_forward_test_period == "P6M"
    assert plan.walk_forward_step_period == "P6M"
    assert plan.walk_forward_master_seed is None


def test_custom_walk_forward_geometry_is_used_for_fold_computation_and_stored_on_plan(tmp_path):
    plan = build_gate_v_campaign_plan(
        **_kwargs(
            tmp_path,
            walk_forward_train_period="P12M",
            walk_forward_test_period="P3M",
            walk_forward_step_period="P3M",
        )
    )
    assert plan.walk_forward_train_period == "P12M"
    assert plan.walk_forward_test_period == "P3M"
    assert plan.walk_forward_step_period == "P3M"
    # VALIDATION [2020-01-01, 2023-01-01) (36 mois) avec train=P12M/test=P3M/step=P3M -> 8 folds
    # (k*3+12+3<=36 => k<=7) : preuve que la géométrie personnalisée a bien été appliquée, jamais
    # silencieusement ignorée au profit des défauts.
    assert len(plan.expected_fold_ids) == 8


def test_walk_forward_master_seed_is_stored_on_plan(tmp_path):
    plan = build_gate_v_campaign_plan(**_kwargs(tmp_path, walk_forward_master_seed=42))
    assert plan.walk_forward_master_seed == 42


# ═══════════════════════════════════════════════════════════════════════════════
# Reproductibilité exacte (ADR 0024 Décision 13, déterminisme de compute_fold_definitions())
# ═══════════════════════════════════════════════════════════════════════════════


def test_two_calls_with_same_inputs_produce_identical_expected_fold_ids(tmp_path):
    split_plan_path = _save_split_plan(tmp_path / "split")
    plan_1 = build_gate_v_campaign_plan(
        **_kwargs(tmp_path, campaign_id="campaign_1", split_plan_path=split_plan_path,
                   job_dir=tmp_path / "job_1")
    )
    plan_2 = build_gate_v_campaign_plan(
        **_kwargs(tmp_path, campaign_id="campaign_2", split_plan_path=split_plan_path,
                   job_dir=tmp_path / "job_2")
    )
    assert plan_1.expected_fold_ids == plan_2.expected_fold_ids


# ═══════════════════════════════════════════════════════════════════════════════
# Persistance disque réelle — round-trip, refus d'écrasement (ADR 0024 Décision 4)
# ═══════════════════════════════════════════════════════════════════════════════


def test_plan_is_persisted_and_round_trips_with_all_fields_preserved(tmp_path):
    job_dir = tmp_path / "job"
    plan = build_gate_v_campaign_plan(**_kwargs(tmp_path, job_dir=job_dir))
    plan_path = job_dir / "gate_v_campaign" / "campaign_a" / "plan.json"
    assert plan_path.is_file()
    reloaded = load_gate_v_campaign_plan(plan_path)
    assert reloaded == plan


def test_second_call_with_same_campaign_id_refuses_to_overwrite(tmp_path):
    job_dir = tmp_path / "job"
    split_plan_path = _save_split_plan(tmp_path / "split")
    build_gate_v_campaign_plan(
        **_kwargs(tmp_path, split_plan_path=split_plan_path, job_dir=job_dir)
    )
    with pytest.raises(FileExistsError):
        build_gate_v_campaign_plan(
            **_kwargs(tmp_path, split_plan_path=split_plan_path, job_dir=job_dir)
        )


def test_load_gate_v_campaign_plan_returns_none_for_missing_file(tmp_path):
    assert load_gate_v_campaign_plan(tmp_path / "missing.json") is None


# ═══════════════════════════════════════════════════════════════════════════════
# Aucune exécution réelle pendant la préparation (ADR 0024 Décision 5/13)
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_signature_has_no_execution_collaborator_parameter():
    params = set(inspect.signature(build_gate_v_campaign_plan).parameters)
    forbidden_substrings = ("_fn", "run_backtest", "run_walk_forward", "load_market_data")
    for name in params:
        assert not any(token in name for token in forbidden_substrings), name


# ═══════════════════════════════════════════════════════════════════════════════
# Découplage structurel — import statique, aucune référence à la zone réservée
# (ADR 0024 Décision 10/13, mirroring tests/test_monte_carlo.py)
# ═══════════════════════════════════════════════════════════════════════════════


class TestStructuralIsolation:

    def test_static_import_analysis_finds_no_engine_optimizer_or_validation_oos(self):
        source = Path(gate_v_campaign.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        forbidden = {"engine", "optimizer", "validation_oos"}
        assert imported.isdisjoint(forbidden), imported & forbidden

    def test_module_never_references_the_reserved_holdout_zone(self):
        # Jetons reconstruits par concaténation : une vérification littérale de LEUR PROPRE
        # absence ne peut pas, par construction, contenir le jeton complet en clair.
        forbidden_token_upper = "FINAL_" + "HOLDOUT"
        forbidden_token_lower = "final_" + "holdout"
        module_source = Path(gate_v_campaign.__file__).read_text(encoding="utf-8")
        assert forbidden_token_upper not in module_source
        assert forbidden_token_lower not in module_source


# ═══════════════════════════════════════════════════════════════════════════════
# Aucun déclenchement automatique depuis l'Autopilot (ADR 0024 Décision 11/13)
# ═══════════════════════════════════════════════════════════════════════════════


def test_autopilot_scripts_never_import_gate_v_campaign():
    autopilot_dir = Path(__file__).resolve().parent.parent / "scripts" / "autopilot"
    for py_file in autopilot_dir.rglob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(alias.name.split(".")[0] == "gate_v_campaign" for alias in node.names), py_file
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] != "gate_v_campaign", py_file
