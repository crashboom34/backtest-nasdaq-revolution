"""
tests/test_gate_v_evidence_completeness_v2.py — AF-V-07 Slice D1 (ADR 0025 Décision 21.6/21.11).

Prédicats de complétude structurelle WF/MC/PS pour un `GateVCampaignPlanV2`, réimplémentés
ADDITIVEMENT dans `gate_v_evidence_completeness_v2.py` (V1 `gate_v_campaign.py` reste gelé et n'est
jamais importé par le module testé). La duplication est acceptée PARCE QUE ces tests différentiels
V1/V2 la verrouillent : mêmes `ValidationRun` synthétiques, même protocole scientifique, jugées par
les prédicats privés V1 et par les prédicats V2 — résultats ET type d'exception égaux, sauf
divergence explicitement décidée (Décision 21) et testée comme telle.

Fixtures SYNTHÉTIQUES uniquement : aucun backtest, aucune donnée de marché, aucun accès
FINAL_HOLDOUT. Les tests Git (plan V2 réel) utilisent un dépôt temporaire local hermétique.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import subprocess
import sys
import uuid
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_v_campaign
import gate_v_evidence_completeness_v2 as c2
from dataset_split import (
    build_dataset_split_plan,
    build_split_boundary,
    save_dataset_split_plan,
)
from gate_v_campaign import build_gate_v_campaign_plan
from gate_v_campaign_plan_v2 import GateVCampaignPlanV2, build_gate_v_campaign_plan_v2
from gate_v_preregistration import build_gate_v_preregistration
from gate_v_validation_policy import (
    OosPolicyCriterion,
    WalkForwardPolicyCriterion,
    build_gate_v_validation_policy,
    save_gate_v_validation_policy,
)
from research_run import build_research_run
from validation_run import (
    FoldResult,
    FoldSelection,
    MonteCarloEvidence,
    ParameterStabilityEvidence,
    PercentileDistributionSummary,
    VALIDATION_TYPE_MONTE_CARLO,
    VALIDATION_TYPE_OOS,
    VALIDATION_TYPE_PARAMETER_STABILITY,
    VALIDATION_TYPE_WALK_FORWARD,
    WalkForwardEvidence,
    build_monte_carlo_specification,
    build_oos_validation_evidence,
    build_oos_validation_specification,
    build_parameter_stability_specification,
    build_validation_run,
    load_validation_run,
    save_validation_run,
)
from walk_forward import build_aggregate_result, build_walk_forward_specification, compute_fold_definitions

_SNAPSHOT_ID = "synthetic_csv:sha256:" + "ab" * 32
_STRATEGY = "Synthetic Strategy"
_RESEARCH_RUN_ID = "research_synthetic_001"
_SPLIT_PLAN_ID = "synthetic_split"
_PROTOCOL = dict(base_params={"lookback": 12}, search_mode="grid", search_space_hash="a" * 12, budget_per_fold=20)


# ============================================================================================
# Fixtures : DEUX mondes scientifiquement compatibles (même split, même protocole, mêmes folds)
#   - V1 : GateVCampaignPlan réel (+ OOS V1, nécessaire au statut composé V1)
#   - V2 : GateVCampaignPlanV2 réel (PreRegistration + provenance Git d'un dépôt temporaire)
# ============================================================================================


def _run_git(args, cwd):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    result = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull, *args],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout


def _commit_policy(root):
    repo_dir = root / f"repo_{uuid.uuid4().hex[:8]}"
    (repo_dir / "validation_policies").mkdir(parents=True)
    _run_git(["init"], repo_dir)
    _run_git(["config", "user.email", "test@example.com"], repo_dir)
    _run_git(["config", "user.name", "Test"], repo_dir)
    policy = build_gate_v_validation_policy(
        "pol_d1",
        {
            "oos": (OosPolicyCriterion(metric="net_ret_pct", operator=">", threshold=0.0),),
            "walk_forward": (WalkForwardPolicyCriterion(metric="oos_net_return_pct", operator=">", threshold=0.0),),
        },
    )
    policy_path = repo_dir / "validation_policies" / "pol_d1.json"
    save_gate_v_validation_policy(policy_path, policy)
    _run_git(["add", "validation_policies"], repo_dir)
    _run_git(["commit", "-m", f"add policy {uuid.uuid4().hex}"], repo_dir)
    return repo_dir, policy_path, policy


def _split_plan():
    return build_dataset_split_plan(
        split_plan_id=_SPLIT_PLAN_ID,
        dataset_snapshot_id=_SNAPSHOT_ID,
        train=build_split_boundary("2020-01-01T00:00:00+00:00", "2021-07-01T00:00:00+00:00"),
        validation=build_split_boundary("2021-07-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
        final_holdout=build_split_boundary("2025-01-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00"),
        created_at="2025-01-01T00:00:00+00:00",
    )


def _synthetic_v1_oos_run(path):
    run = build_validation_run(
        validation_run_id="synthetic_oos_d1", research_run_id="external_research_synthetic",
        split_plan_id=_SPLIT_PLAN_ID, dataset_snapshot_id=_SNAPSHOT_ID, strategy_name=_STRATEGY,
        strategy_params={"lookback": 12},
        specification=build_oos_validation_specification("2025-01-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00"),
        evidence=build_oos_validation_evidence("2025-01-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00", 0, 0.0),
        validation_type=VALIDATION_TYPE_OOS, completed_at="2025-07-01T00:00:00+00:00",
    )
    save_validation_run(path, run)
    return run


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    root = tmp_path_factory.mktemp("d1_worlds")
    split = _split_plan()
    split_path = root / "split.json"
    save_dataset_split_plan(split_path, split)
    oos_path = root / "oos.json"
    oos_run = _synthetic_v1_oos_run(oos_path)
    v1_plan = build_gate_v_campaign_plan(
        research_run_id=_RESEARCH_RUN_ID, dataset_snapshot_id=_SNAPSHOT_ID, split_plan_id=_SPLIT_PLAN_ID,
        split_plan_path=split_path, strategy_name=_STRATEGY, geometry="rolling", train_period="P24M",
        test_period="P6M", step_period="P6M", readiness_spec=None, master_seed=None,
        oos_evidence_validation_run_id=oos_run.validation_run_id, oos_evidence_path=oos_path, **_PROTOCOL,
    )
    repo_dir, policy_path, policy = _commit_policy(root)
    research_run = build_research_run(
        research_run_id=_RESEARCH_RUN_ID, experiment_id="exp_d1", dataset_snapshot_id=_SNAPSHOT_ID, git_sha=None,
    )
    spec = build_walk_forward_specification(
        base_params=dict(_PROTOCOL["base_params"]), geometry="rolling", train_period="P24M",
        test_period="P6M", step_period="P6M",
    )
    protocol = dict(strategy_name=_STRATEGY, walk_forward_specification=spec, readiness_spec=None, **_PROTOCOL)
    prereg = build_gate_v_preregistration(
        research_run=research_run, split_plan=split, policy=policy, policy_path=policy_path,
        assessment_semantics_version="gate_v_assessment_v1", repo_dir=repo_dir, **protocol,
    )
    v2_plan = build_gate_v_campaign_plan_v2(
        preregistration=prereg, research_run=research_run, split_plan=split, policy=policy,
        policy_path=policy_path, repo_dir=repo_dir, **protocol,
    )
    assert v1_plan.expected_fold_ids == v2_plan.expected_fold_ids
    assert len(v2_plan.expected_fold_ids) == 3
    assert v1_plan.expected_fold_definitions_hash == v2_plan.expected_fold_definitions_hash
    return SimpleNamespace(split=split, v1_plan=v1_plan, v2_plan=v2_plan, oos_run=oos_run)


# ============================================================================================
# Tranche 1 — identifiant déterministe des preuves d'une campagne V2 (Décision 21.6)
# ============================================================================================


def test_v2_validation_run_id_is_campaign_scoped_with_the_v1_shape_but_a_disjoint_namespace(worlds):
    plan = worlds.v2_plan
    assert c2.gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD) == f"{plan.campaign_id}_walk_forward"
    assert c2.gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO) == f"{plan.campaign_id}_monte_carlo"
    fold_id = plan.expected_fold_ids[1]
    assert (
        c2.gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_PARAMETER_STABILITY, fold_id=fold_id)
        == f"{plan.campaign_id}_parameter_stability_{fold_id}"
    )
    # Espace disjoint de V1 : "gate_v_v2_<hex>_..." ne peut jamais valoir un identifiant "gate_v_<hex>_...".
    assert plan.campaign_id.startswith("gate_v_v2_")
    assert gate_v_campaign.gate_v_validation_run_id(worlds.v1_plan, VALIDATION_TYPE_WALK_FORWARD) != (
        c2.gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
    )


def test_v2_validation_run_id_rejects_unknown_types_and_misplaced_or_foreign_folds(worlds):
    plan = worlds.v2_plan
    for bad_type in (VALIDATION_TYPE_OOS, "stress", "", None, "walk-forward"):
        with pytest.raises(ValueError):
            c2.gate_v_v2_validation_run_id(plan, bad_type)
    with pytest.raises(ValueError):  # fold_id interdit hors Parameter Stability
        c2.gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD, fold_id=plan.expected_fold_ids[0])
    with pytest.raises(ValueError):
        c2.gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO, fold_id=plan.expected_fold_ids[0])
    for bad_fold in (None, "", "fold_999", "foreign", 0):
        with pytest.raises(ValueError):  # Parameter Stability exige un fold ATTENDU
            c2.gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_PARAMETER_STABILITY, fold_id=bad_fold)


def test_v2_functions_refuse_a_v1_plan_and_any_non_plan_object(worlds):
    for bad_plan in (worlds.v1_plan, None, {}, dataclasses.asdict(worlds.v2_plan), "plan"):
        with pytest.raises(ValueError):
            c2.gate_v_v2_validation_run_id(bad_plan, VALIDATION_TYPE_WALK_FORWARD)
    assert isinstance(worlds.v2_plan, GateVCampaignPlanV2)


# ============================================================================================
# Constructeurs de preuves synthétiques IDENTIQUES pour les deux mondes (mêmes folds, mêmes
# métriques ; seuls les identifiants de run — espace V1 vs V2 — diffèrent)
# ============================================================================================

_COMPLETED_AT = "2025-07-01T00:00:00+00:00"
_SUMMARY = PercentileDistributionSummary(0.1, 0.2, 0.3, 0.4, 0.5)
_PS_TYPE = VALIDATION_TYPE_PARAMETER_STABILITY
_ROLE_TYPES = {"wf": VALIDATION_TYPE_WALK_FORWARD, "mc": VALIDATION_TYPE_MONTE_CARLO}


def _role_ids(plan, run_id_fn):
    ids = {
        "wf": run_id_fn(plan, VALIDATION_TYPE_WALK_FORWARD),
        "mc": run_id_fn(plan, VALIDATION_TYPE_MONTE_CARLO),
    }
    for fold_id in plan.expected_fold_ids:
        ids[f"ps:{fold_id}"] = run_id_fn(plan, _PS_TYPE, fold_id=fold_id)
    return ids


def _role_type(role):
    return _PS_TYPE if role.startswith("ps:") else _ROLE_TYPES[role]


def _fold_selection(index):
    """Sélection TRAIN propre à chaque fold (paramètres, score et pool distincts) : un PS rapproché du
    mauvais fold source ne peut donc jamais passer par homogénéité accidentelle des fixtures."""
    return dict(selected_params={"lookback": 12 + index}, score_train=1.0 + index, candidates=2 + index)


def _fold_result(definition, plan, *, traded, index):
    chosen = _fold_selection(index)
    selection = FoldSelection(
        fold_id=definition.fold_id, selected_params=chosen["selected_params"], selected_params_hash="synthetic_hash",
        score_train=chosen["score_train"], rank_in_train=1, train_candidates_evaluated=chosen["candidates"],
        train_candidates_unique=chosen["candidates"], train_candidates_eligible=chosen["candidates"],
        search_space_hash=plan.search_space_hash, algorithm=plan.search_mode, fold_seed=None,
    )
    if traded:
        return FoldResult(
            fold_id=definition.fold_id, definition=definition, selection=selection, n_trades=5, net_ret_pct=1.0,
            max_dd_pct=0.5, profit_factor=1.5, win_rate=60.0, expectancy=0.2, score_test=1.0,
            zero_trade_oos=False, forced_closes=0, coverage_bars=100, gross_win=3.0, gross_loss=2.0, n_win=3,
        )
    return FoldResult(
        fold_id=definition.fold_id, definition=definition, selection=selection, n_trades=0, net_ret_pct=0.0,
        max_dd_pct=None, profit_factor=None, win_rate=None, expectancy=None, score_test=0.0,
        zero_trade_oos=True, forced_closes=0, coverage_bars=1,
    )


def _campaign_roles(plan, split, run_id_fn, *, traded):
    """Preuves WF/MC/PS COMPLÈTES, synthétiques (aucun moteur), pour le plan donné."""
    definitions = compute_fold_definitions(split.validation, plan.walk_forward_specification, plan.readiness_spec)
    results = tuple(
        _fold_result(definition, plan, traded=traded, index=index) for index, definition in enumerate(definitions)
    )
    n_folds = len(results)
    total = 5 * n_folds if traded else 0
    aggregate = build_aggregate_result(results)  # le PRODUCTEUR réel, pas un agrégat écrit à la main
    ids = _role_ids(plan, run_id_fn)
    common = dict(
        research_run_id=plan.research_run_id, split_plan_id=plan.split_plan_id,
        dataset_snapshot_id=plan.dataset_snapshot_id, strategy_name=plan.strategy_name,
        strategy_params=dict(plan.base_params), completed_at=_COMPLETED_AT,
    )
    roles = {
        "wf": build_validation_run(
            validation_run_id=ids["wf"], validation_type=VALIDATION_TYPE_WALK_FORWARD,
            specification=plan.walk_forward_specification,
            evidence=WalkForwardEvidence(results, aggregate, "completed", "INCONCLUSIVE", ()), **common,
        ),
        "mc": build_validation_run(
            validation_run_id=ids["mc"], validation_type=VALIDATION_TYPE_MONTE_CARLO,
            specification=build_monte_carlo_specification(ids["wf"], True),
            evidence=MonteCarloEvidence(
                n_input_trades=total, zero_trade_input=not traded,
                observed_net_ret_pct=3.0 if traded else None,
                observed_max_dd_trade_close_basis_pct=1.0 if traded else None,
                observed_lag1_autocorrelation=0.0 if traded else None,
                observed_longest_losing_streak=2 if traded else None,
                sequence_risk_max_dd_trade_close_basis_pct=_SUMMARY if traded else None,
                sequence_risk_longest_losing_streak=_SUMMARY if traded else None,
                sampling_uncertainty_net_ret_pct=_SUMMARY if traded else None,
                sampling_uncertainty_max_dd_trade_close_basis_pct=_SUMMARY if traded else None,
                execution_status="completed", scientific_verdict="INCONCLUSIVE", verdict_reasons=(),
            ), **common,
        ),
    }
    for index, fold_id in enumerate(plan.expected_fold_ids):
        chosen = _fold_selection(index)
        roles[f"ps:{fold_id}"] = build_validation_run(
            validation_run_id=ids[f"ps:{fold_id}"], validation_type=_PS_TYPE,
            specification=build_parameter_stability_specification(
                ids["wf"], plan.search_mode, True, source_fold_id=fold_id,
            ),
            evidence=ParameterStabilityEvidence(
                n_candidates_total=chosen["candidates"], zero_candidates_input=False, search_mode=plan.search_mode,
                neighborhood_applicability="local_neighborhood_available", best_score=chosen["score_train"],
                best_params=dict(chosen["selected_params"]), sensitivity={"lookback": 0.0},
                sensitivity_sample_size_by_param={"lookback": 2}, n_neighbors_total_by_param={"lookback": 1},
                n_neighbors_rejected_by_param={"lookback": 0}, degradation_by_param={"lookback": _SUMMARY},
                degradation_points_by_param={"lookback": _SUMMARY}, n_hamming_le_2_total=1,
                n_hamming_le_2_rejected=0, degradation_hamming_le_2=_SUMMARY, execution_status="completed",
                scientific_verdict="INCONCLUSIVE", verdict_reasons=(),
            ), **common,
        )
    return roles


def _mapping(plan, run_id_fn, roles):
    """Mapping clé = identifiant DÉTERMINISTE du rôle ; la valeur peut être altérée par une mutation."""
    ids = _role_ids(plan, run_id_fn)
    return {ids[role]: run for role, run in roles.items() if run is not None}


@pytest.fixture(scope="module")
def scratch(tmp_path_factory):
    return tmp_path_factory.mktemp("d1_json")


def _json_variant(run, scratch):
    """La même preuve rechargée depuis JSON : enregistrements imbriqués = dict/list, pas dataclass."""
    path = scratch / f"{uuid.uuid4().hex}.json"
    save_validation_run(path, run)
    return load_validation_run(path)


def _outcome(call):
    """Résultat observable comparable V1/V2 : type d'exception, ou 'ok' / 'none'."""
    try:
        result = call()
    except Exception as exc:  # noqa: BLE001 — l'oracle compare le TYPE d'exception, pas le message
        return type(exc).__name__
    if isinstance(result, bool):
        return "complete" if result else "incomplete"
    return "none" if result is None else "ok"


# ============================================================================================
# Tranche 2 — preuve « scoped » (Décision 21.6, reprise des règles V1 sans le cas OOS)
# ============================================================================================

_FOREIGN_SNAPSHOT = "synthetic_csv:sha256:" + "cd" * 32


def _replace_run(**changes):
    return lambda run: dataclasses.replace(run, **changes)


def _replace_evidence(**changes):
    return lambda run: dataclasses.replace(run, evidence=dataclasses.replace(run.evidence, **changes))


# (nom, mutation, rôles concernés, issue DÉCLARÉE — jamais dérivée de V1)
_SCOPED_MUTATIONS = [
    ("foreign_snapshot", _replace_run(dataset_snapshot_id=_FOREIGN_SNAPSHOT), "all", "ValueError"),
    ("foreign_split", _replace_run(split_plan_id="other_split"), "all", "ValueError"),
    ("foreign_strategy", _replace_run(strategy_name="Other Strategy"), "all", "ValueError"),
    ("foreign_research_run", _replace_run(research_run_id="other_research"), "all", "ValueError"),
    ("status_not_completed", _replace_run(status="failed"), "all", "ValueError"),
    ("wrong_validation_type", _replace_run(validation_type=VALIDATION_TYPE_OOS), "all", "ValueError"),
    ("run_id_differs_from_key", _replace_run(validation_run_id="foreign_run_id"), "all", "ValueError"),
    ("verdict_pass_without_policy", _replace_evidence(scientific_verdict="PASS"), "all", "ValueError"),
    ("verdict_missing", _replace_evidence(scientific_verdict=None), "all", "ValueError"),
    ("not_a_validation_run", lambda run: dataclasses.asdict(run), "all", "ValueError"),
    ("foreign_strategy_params", _replace_run(strategy_params={"lookback": 99}), "wf_mc", "ValueError"),
    # Parité V1 : les paramètres de stratégie ne sont contrôlés que pour WF et MC, pas pour PS.
    ("foreign_strategy_params", _replace_run(strategy_params={"lookback": 99}), "ps", "ok"),
]


def _scoped_cases():
    for name, mutation, scope, expected in _SCOPED_MUTATIONS:
        for role in ("wf", "mc", "ps:first", "ps:last"):
            kind = "ps" if role.startswith("ps") else "wf_mc"
            if scope in ("all", kind):
                yield pytest.param(name, mutation, role, expected, id=f"{name}-{role}")


def _resolve_role(plan, role):
    if role == "ps:first":
        return f"ps:{plan.expected_fold_ids[0]}"
    if role == "ps:last":
        return f"ps:{plan.expected_fold_ids[-1]}"
    return role


@pytest.mark.parametrize("variant", ["objects", "json"])
@pytest.mark.parametrize("traded", [False, True])
def test_scoped_run_accepts_complete_campaign_evidence_exactly_like_v1(worlds, scratch, traded, variant):
    for plan, run_id_fn, scoped in (
        (worlds.v1_plan, gate_v_campaign.gate_v_validation_run_id, gate_v_campaign._validate_scoped_run),
        (worlds.v2_plan, c2.gate_v_v2_validation_run_id, c2.validate_scoped_evidence_run_v2),
    ):
        roles = _campaign_roles(plan, worlds.split, run_id_fn, traded=traded)
        if variant == "json":
            roles = {role: _json_variant(run, scratch) for role, run in roles.items()}
        mapping = _mapping(plan, run_id_fn, roles)
        ids = _role_ids(plan, run_id_fn)
        for role, run in roles.items():
            assert scoped(plan, ids[role], _role_type(role), mapping) is run


def test_scoped_run_treats_an_absent_reference_as_missing_not_as_evidence_like_v1(worlds):
    for plan, run_id_fn, scoped in (
        (worlds.v1_plan, gate_v_campaign.gate_v_validation_run_id, gate_v_campaign._validate_scoped_run),
        (worlds.v2_plan, c2.gate_v_v2_validation_run_id, c2.validate_scoped_evidence_run_v2),
    ):
        ids = _role_ids(plan, run_id_fn)
        for role, run_id in ids.items():
            assert scoped(plan, run_id, _role_type(role), {}) is None


@pytest.mark.parametrize("name,mutation,role,expected", list(_scoped_cases()))
def test_scoped_run_mutation_catalog_has_the_declared_outcome_in_v1_and_in_v2(worlds, name, mutation, role, expected):
    outcomes = {}
    for label, plan, run_id_fn, scoped in (
        ("v1", worlds.v1_plan, gate_v_campaign.gate_v_validation_run_id, gate_v_campaign._validate_scoped_run),
        ("v2", worlds.v2_plan, c2.gate_v_v2_validation_run_id, c2.validate_scoped_evidence_run_v2),
    ):
        roles = _campaign_roles(plan, worlds.split, run_id_fn, traded=False)
        target = _resolve_role(plan, role)
        roles[target] = mutation(roles[target])
        mapping = _mapping(plan, run_id_fn, roles)
        run_id = _role_ids(plan, run_id_fn)[target]
        outcomes[label] = _outcome(lambda: scoped(plan, run_id, _role_type(target), mapping))
    assert outcomes == {"v1": expected, "v2": expected}


def test_scoped_run_rejects_a_non_mapping_and_a_v1_plan_in_v2(worlds):
    plan = worlds.v2_plan
    run_id = c2.gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
    with pytest.raises(ValueError):
        c2.validate_scoped_evidence_run_v2(worlds.v1_plan, run_id, VALIDATION_TYPE_WALK_FORWARD, {})
    for bad_mapping in (None, [], "mapping"):
        with pytest.raises(ValueError):
            c2.validate_scoped_evidence_run_v2(plan, run_id, VALIDATION_TYPE_WALK_FORWARD, bad_mapping)
    with pytest.raises(ValueError):  # l'OOS n'est jamais une preuve interne V2 (Décision 21.6)
        c2.validate_scoped_evidence_run_v2(plan, run_id, VALIDATION_TYPE_OOS, {})


# ============================================================================================
# Tranche 3 — Walk-Forward complet (Décision 21.6) : différentiel V1/V2 + issues DÉCLARÉES
# ============================================================================================

_WRONG_WF_SPEC = build_walk_forward_specification(
    base_params=dict(_PROTOCOL["base_params"]), geometry="rolling", train_period="P18M",
    test_period="P6M", step_period="P6M",
)


def _judge(worlds, scratch, *, traded, role, mutation, as_json, v1_call, v2_call):
    """Même mutation, mêmes preuves synthétiques ; jugées par le prédicat V1 puis par le prédicat V2."""
    outcomes = {}
    for label, plan, run_id_fn, call in (
        ("v1", worlds.v1_plan, gate_v_campaign.gate_v_validation_run_id, v1_call),
        ("v2", worlds.v2_plan, c2.gate_v_v2_validation_run_id, v2_call),
    ):
        roles = _campaign_roles(plan, worlds.split, run_id_fn, traded=traded)
        target = _resolve_role(plan, role)
        if mutation is not None:
            roles[target] = mutation(roles[target])
        if as_json:
            roles = {name: None if run is None else _json_variant(run, scratch) for name, run in roles.items()}
        outcomes[label] = _outcome(lambda: call(plan, roles))
    return outcomes


def _fold_edit(index, edit):
    def mutate(run):
        folds = list(run.evidence.fold_results)
        folds[index] = edit(folds[index])
        return dataclasses.replace(run, evidence=dataclasses.replace(run.evidence, fold_results=tuple(folds)))
    return mutate


def _fold_replace(index, **changes):
    return _fold_edit(index, lambda fold: dataclasses.replace(fold, **changes))


def _selection_replace(index, **changes):
    return _fold_edit(
        index, lambda fold: dataclasses.replace(fold, selection=dataclasses.replace(fold.selection, **changes)),
    )


def _definition_replace(index, **changes):
    return _fold_edit(
        index, lambda fold: dataclasses.replace(fold, definition=dataclasses.replace(fold.definition, **changes)),
    )


def _aggregate_replace(**changes):
    return lambda run: dataclasses.replace(
        run, evidence=dataclasses.replace(
            run.evidence, aggregate=dataclasses.replace(run.evidence.aggregate, **changes),
        ),
    )


def _folds_edit(edit):
    return lambda run: dataclasses.replace(
        run, evidence=dataclasses.replace(run.evidence, fold_results=tuple(edit(list(run.evidence.fold_results)))),
    )


def _wf_v1(plan, roles):
    return gate_v_campaign._walk_forward_complete(plan, roles["wf"])


def _wf_v2(plan, roles):
    return c2.walk_forward_evidence_complete_v2(plan, roles["wf"])


# (nom, mutation, variantes, issue DÉCLARÉE). Jamais dérivée de V1.
_BOTH, _ZERO, _TRADED = ("zero", "traded"), ("zero",), ("traded",)
_WF_MUTATIONS = [
    ("baseline_complete", None, _BOTH, "complete"),
    ("specification_differs_from_plan", _replace_run(specification=_WRONG_WF_SPEC), _BOTH, "ValueError"),
    ("specification_missing", _replace_run(specification=None), _BOTH, "ValueError"),
    ("execution_status_not_completed", _replace_evidence(execution_status="failed"), _BOTH, "incomplete"),
    ("aggregate_missing", _replace_evidence(aggregate=None), _BOTH, "incomplete"),
    ("expected_fold_missing", _folds_edit(lambda folds: folds[:-1]), _BOTH, "incomplete"),
    ("unexpected_duplicate_fold", _folds_edit(lambda folds: folds + [folds[0]]), _BOTH, "incomplete"),
    ("folds_out_of_order", _folds_edit(lambda folds: list(reversed(folds))), _BOTH, "incomplete"),
    ("fold_id_unknown", _fold_replace(0, fold_id="fold_999"), _BOTH, "incomplete"),
    ("n_trades_negative", _fold_replace(0, n_trades=-1), _BOTH, "ValueError"),
    ("n_trades_bool", _fold_replace(0, n_trades=True), _TRADED, "ValueError"),
    ("zero_flag_true_with_trades", _fold_replace(0, zero_trade_oos=True), _TRADED, "ValueError"),
    ("zero_flag_false_without_trades", _fold_replace(0, zero_trade_oos=False), _ZERO, "ValueError"),
    ("zero_trade_invented_net_ret", _fold_replace(0, net_ret_pct=1.0), _ZERO, "ValueError"),
    ("zero_trade_invented_profit_factor", _fold_replace(0, profit_factor=1.0), _ZERO, "ValueError"),
    ("zero_trade_invented_win_rate", _fold_replace(0, win_rate=50.0), _ZERO, "ValueError"),
    ("zero_trade_invented_expectancy", _fold_replace(0, expectancy=0.1), _ZERO, "ValueError"),
    ("definition_fold_id_mismatch", _definition_replace(0, fold_id="fold_999"), _BOTH, "ValueError"),
    ("definition_missing", _fold_replace(0, definition=None), _BOTH, "ValueError"),
    ("selection_missing", _fold_replace(0, selection=None), _BOTH, "ValueError"),
    ("selection_fold_id_mismatch", _selection_replace(0, fold_id="fold_999"), _BOTH, "ValueError"),
    ("selection_not_top_1", _selection_replace(0, rank_in_train=2), _BOTH, "ValueError"),
    ("selection_search_space_hash_differs", _selection_replace(0, search_space_hash="b" * 12), _BOTH, "ValueError"),
    ("selection_algorithm_differs", _selection_replace(0, algorithm="general"), _BOTH, "ValueError"),
    ("selection_no_candidate", _selection_replace(0, train_candidates_evaluated=0), _BOTH, "ValueError"),
    ("selection_over_budget", _selection_replace(0, train_candidates_evaluated=21), _BOTH, "ValueError"),
    ("selection_candidates_not_int", _selection_replace(0, train_candidates_evaluated="2"), _BOTH, "ValueError"),
    ("fold_bounds_differ_from_plan", _definition_replace(1, requested_boundary="2020-02-01T00:00:00+00:00"),
     _BOTH, "ValueError"),
    ("aggregate_n_folds_differs", _aggregate_replace(n_folds=2), _BOTH, "incomplete"),
    ("aggregate_total_trades_differs", _aggregate_replace(total_oos_trades=99), _BOTH, "ValueError"),
    ("aggregate_zero_fold_count_differs", _aggregate_replace(n_folds_zero_trade=1), _BOTH, "ValueError"),
    # Dernier fold (index 2) : une régression « saute le dernier fold » ne doit pas passer inaperçue.
    ("last_fold_not_top_1", _selection_replace(2, rank_in_train=2), _BOTH, "ValueError"),
    ("last_fold_n_trades_negative", _fold_replace(2, n_trades=-1), _BOTH, "ValueError"),
    ("last_fold_definition_fold_id_mismatch", _definition_replace(2, fold_id="fold_999"), _BOTH, "ValueError"),
    ("last_fold_bounds_differ_from_plan", _definition_replace(2, requested_test_end="2025-12-01T00:00:00+00:00"),
     _BOTH, "ValueError"),
    ("last_fold_zero_trade_invented_net_ret", _fold_replace(2, net_ret_pct=1.0), _ZERO, "ValueError"),
    ("first_fold_bounds_differ_from_plan", _definition_replace(0, effective_boundary="2020-03-01T00:00:00+00:00"),
     _BOTH, "ValueError"),
    # Borne exacte du budget : `train_candidates_evaluated == budget_per_fold` est valide (20), 21 ne l'est pas.
    ("selection_exactly_at_the_budget", _selection_replace(0, train_candidates_evaluated=20), _BOTH, "complete"),
]


# `save_validation_run` refuse une specification absente : ce cas n'a donc aucune forme JSON.
_WITHOUT_JSON_FORM = frozenset({"specification_missing"})


def _wf_cases():
    for name, mutation, variants, expected in _WF_MUTATIONS:
        for variant in variants:
            for as_json in (False,) if name in _WITHOUT_JSON_FORM else (False, True):
                label = "json" if as_json else "objects"
                yield pytest.param(
                    name, mutation, variant == "traded", as_json, expected, id=f"{name}-{variant}-{label}",
                )


@pytest.mark.parametrize("name,mutation,traded,as_json,expected", list(_wf_cases()))
def test_walk_forward_completeness_has_the_declared_outcome_in_v1_and_in_v2(
    worlds, scratch, name, mutation, traded, as_json, expected,
):
    outcomes = _judge(
        worlds, scratch, traded=traded, role="wf", mutation=mutation, as_json=as_json, v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": expected, "v2": expected}, name


def _json_wf_with_edited_definition(worlds, scratch, plan, run_id_fn, edit):
    roles = _campaign_roles(plan, worlds.split, run_id_fn, traded=False)
    wf = _json_variant(roles["wf"], scratch)
    edit(wf.evidence.fold_results[0]["definition"])
    return wf


@pytest.mark.parametrize(
    "name,edit",
    [
        ("definition_extra_key", lambda definition: definition.update(extra=1)),
        ("definition_missing_key", lambda definition: definition.pop("effective_test_end")),
        ("definition_value_type_changed", lambda definition: definition.update(fold_index="0")),
    ],
)
def test_walk_forward_json_definition_shapes_are_refused_like_v1(worlds, scratch, name, edit):
    outcomes = {}
    for label, plan, run_id_fn, judge in (
        ("v1", worlds.v1_plan, gate_v_campaign.gate_v_validation_run_id, gate_v_campaign._walk_forward_complete),
        ("v2", worlds.v2_plan, c2.gate_v_v2_validation_run_id, c2.walk_forward_evidence_complete_v2),
    ):
        wf = _json_wf_with_edited_definition(worlds, scratch, plan, run_id_fn, edit)
        outcomes[label] = _outcome(lambda: judge(plan, wf))
    assert outcomes == {"v1": "ValueError", "v2": "ValueError"}, name


def test_walk_forward_completeness_is_pure_and_does_not_mutate_its_inputs(worlds):
    plan = worlds.v2_plan
    roles = _campaign_roles(plan, worlds.split, c2.gate_v_v2_validation_run_id, traded=True)
    before = dataclasses.asdict(roles["wf"])
    assert c2.walk_forward_evidence_complete_v2(plan, roles["wf"]) is True
    assert c2.walk_forward_evidence_complete_v2(plan, roles["wf"]) is True
    assert dataclasses.asdict(roles["wf"]) == before


def test_v2_diverges_from_v1_by_refusing_a_bool_as_the_train_candidate_count(worlds, scratch):
    """Divergence DÉCIDÉE (D1) : ``True`` est un ``int`` Python ; V1 l'accepte comme 1 candidat évalué.
    Une preuve produite par le moteur n'a jamais un booléen ici : V2 le refuse comme ``n_trades``."""
    outcomes = _judge(
        worlds, scratch, traded=False, role="wf", mutation=_selection_replace(0, train_candidates_evaluated=True),
        as_json=False, v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "ValueError"}


def test_walk_forward_completeness_refuses_a_v1_plan_and_a_non_run(worlds):
    roles = _campaign_roles(worlds.v2_plan, worlds.split, c2.gate_v_v2_validation_run_id, traded=False)
    with pytest.raises(ValueError):
        c2.walk_forward_evidence_complete_v2(worlds.v1_plan, roles["wf"])
    for bad in (None, {}, dataclasses.asdict(roles["wf"]), "run"):
        with pytest.raises(ValueError):
            c2.walk_forward_evidence_complete_v2(worlds.v2_plan, bad)


# ============================================================================================
# Tranche 4 — Monte-Carlo complet (Décision 21.6)
# ============================================================================================

_NAN = float("nan")
_INF = float("inf")


def _mc_v1(plan, roles):
    return gate_v_campaign._monte_carlo_complete(plan, roles["wf"], roles["mc"])


def _mc_v2(plan, roles):
    return c2.monte_carlo_evidence_complete_v2(plan, roles["wf"], roles["mc"])


def _mc_without_wf_v1(plan, roles):
    return gate_v_campaign._monte_carlo_complete(plan, None, roles["mc"])


def _mc_without_wf_v2(plan, roles):
    return c2.monte_carlo_evidence_complete_v2(plan, None, roles["mc"])


def _wf_aggregate_missing(roles):
    roles["wf"] = dataclasses.replace(roles["wf"], evidence=dataclasses.replace(roles["wf"].evidence, aggregate=None))


def _wrong_mc_spec(**changes):
    """Spécification MC construite pour un AUTRE run source / autre option que celle du plan."""
    def mutate(run):
        spec = build_monte_carlo_specification(
            changes.get("source", run.specification.source_validation_run_id),
            changes.get("optimized", True), changes.get("policy"),
        )
        return dataclasses.replace(run, specification=spec)
    return mutate


# Seul un type d'evidence incohérent n'a aucune forme JSON à recharger (NaN/inf, eux, font l'aller-retour).
_NO_JSON_NAN = frozenset({"evidence_wrong_type"})
_MC_MUTATIONS = [
    ("baseline_complete", None, _BOTH, "complete"),
    ("evidence_wrong_type", _replace_run(evidence=_SUMMARY), _BOTH, "ValueError"),
    ("specification_missing", _replace_run(specification=None), _BOTH, "ValueError"),
    ("specification_from_foreign_walk_forward", _wrong_mc_spec(source="gate_v_v2_other_walk_forward"), _BOTH,
     "ValueError"),
    ("specification_not_declared_circular", _wrong_mc_spec(optimized=False), _BOTH, "ValueError"),
    ("specification_with_verdict_policy", _wrong_mc_spec(policy="some_policy"), _BOTH, "ValueError"),
    ("n_input_trades_differs_from_walk_forward", _replace_evidence(n_input_trades=99), _BOTH, "ValueError"),
    ("zero_flag_true_with_trades", _replace_evidence(zero_trade_input=True), _TRADED, "ValueError"),
    ("zero_flag_false_without_trades", _replace_evidence(zero_trade_input=False), _ZERO, "ValueError"),
    ("zero_trade_invented_observed_net_ret", _replace_evidence(observed_net_ret_pct=1.0), _ZERO, "ValueError"),
    ("zero_trade_invented_streak", _replace_evidence(observed_longest_losing_streak=1), _ZERO, "ValueError"),
    ("zero_trade_invented_distribution", _replace_evidence(sampling_uncertainty_net_ret_pct=_SUMMARY), _ZERO,
     "ValueError"),
    ("execution_status_not_completed", _replace_evidence(execution_status="failed"), _BOTH, "incomplete"),
    ("observed_net_ret_pct_missing", _replace_evidence(observed_net_ret_pct=None), _TRADED, "incomplete"),
    ("observed_net_ret_pct_nan", _replace_evidence(observed_net_ret_pct=_NAN), _TRADED, "incomplete"),
    ("observed_max_dd_infinite", _replace_evidence(observed_max_dd_trade_close_basis_pct=_INF), _TRADED,
     "incomplete"),
    ("observed_streak_missing", _replace_evidence(observed_longest_losing_streak=None), _TRADED, "incomplete"),
    ("observed_streak_negative", _replace_evidence(observed_longest_losing_streak=-1), _TRADED, "incomplete"),
    ("observed_streak_float", _replace_evidence(observed_longest_losing_streak=1.5), _TRADED, "incomplete"),
    ("distribution_missing", _replace_evidence(sequence_risk_max_dd_trade_close_basis_pct=None), _TRADED,
     "incomplete"),
    ("percentile_missing", _replace_evidence(
        sampling_uncertainty_net_ret_pct=PercentileDistributionSummary(0.1, 0.2, None, 0.4, 0.5)), _TRADED,
     "incomplete"),
    ("percentile_nan", _replace_evidence(
        sequence_risk_longest_losing_streak=PercentileDistributionSummary(0.1, 0.2, _NAN, 0.4, 0.5)), _TRADED,
     "incomplete"),
    ("percentile_not_a_number", _replace_evidence(
        sampling_uncertainty_max_dd_trade_close_basis_pct=PercentileDistributionSummary(0.1, 0.2, "x", 0.4, 0.5)),
     _TRADED, "incomplete"),
]


def _mc_cases():
    for name, mutation, variants, expected in _MC_MUTATIONS:
        for variant in variants:
            for as_json in (False,) if name in _WITHOUT_JSON_FORM | _NO_JSON_NAN else (False, True):
                label = "json" if as_json else "objects"
                yield pytest.param(
                    name, mutation, variant == "traded", as_json, expected, id=f"{name}-{variant}-{label}",
                )


@pytest.mark.parametrize("name,mutation,traded,as_json,expected", list(_mc_cases()))
def test_monte_carlo_completeness_has_the_declared_outcome_in_v1_and_in_v2(
    worlds, scratch, name, mutation, traded, as_json, expected,
):
    outcomes = _judge(
        worlds, scratch, traded=traded, role="mc", mutation=mutation, as_json=as_json, v1_call=_mc_v1, v2_call=_mc_v2,
    )
    assert outcomes == {"v1": expected, "v2": expected}, name


@pytest.mark.parametrize("traded,mutation,expected", [
    # Règle de saut héritée de V1, explicitée (21.6) : sans WF ou sans agrégat WF, le compte de trades
    # MC n'est PAS comparé ; la WF est alors elle-même incomplète, donc le statut reste incomplet.
    (True, _replace_evidence(n_input_trades=99), "complete"),
    (False, None, "complete"),
])
def test_monte_carlo_skips_the_trade_count_comparison_when_there_is_no_walk_forward_like_v1(
    worlds, scratch, traded, mutation, expected,
):
    outcomes = _judge(
        worlds, scratch, traded=traded, role="mc", mutation=mutation, as_json=False,
        v1_call=_mc_without_wf_v1, v2_call=_mc_without_wf_v2,
    )
    assert outcomes == {"v1": expected, "v2": expected}


def test_monte_carlo_skips_the_trade_count_comparison_when_the_walk_forward_has_no_aggregate_like_v1(worlds, scratch):
    outcomes = {}
    for label, plan, run_id_fn, call in (
        ("v1", worlds.v1_plan, gate_v_campaign.gate_v_validation_run_id, _mc_v1),
        ("v2", worlds.v2_plan, c2.gate_v_v2_validation_run_id, _mc_v2),
    ):
        roles = _campaign_roles(plan, worlds.split, run_id_fn, traded=True)
        roles["mc"] = _replace_evidence(n_input_trades=99)(roles["mc"])
        _wf_aggregate_missing(roles)
        outcomes[label] = _outcome(lambda: call(plan, roles))
    assert outcomes == {"v1": "complete", "v2": "complete"}


@pytest.mark.parametrize("name,mutation", [
    ("observed_net_ret_pct_is_a_bool", _replace_evidence(observed_net_ret_pct=True)),
    ("observed_max_dd_is_a_bool", _replace_evidence(observed_max_dd_trade_close_basis_pct=False)),
    ("observed_streak_is_a_bool", _replace_evidence(observed_longest_losing_streak=True)),
    ("percentile_is_a_bool", _replace_evidence(
        sampling_uncertainty_net_ret_pct=PercentileDistributionSummary(0.1, 0.2, True, 0.4, 0.5))),
])
def test_v2_diverges_from_v1_by_refusing_a_bool_as_a_monte_carlo_number(worlds, scratch, name, mutation):
    """Divergence DÉCIDÉE (D1), même classe que le nombre de candidats TRAIN : ``bool`` est un ``int`` Python,
    V1 l'accepte comme valeur finie. Aucune preuve produite par le moteur n'y met un booléen : V2 le
    traite comme valeur absente (preuve incomplète), jamais comme une mesure."""
    outcomes = _judge(
        worlds, scratch, traded=True, role="mc", mutation=mutation, as_json=False, v1_call=_mc_v1, v2_call=_mc_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "incomplete"}, name


def test_monte_carlo_completeness_is_pure_and_refuses_a_v1_plan_and_non_runs(worlds):
    plan = worlds.v2_plan
    roles = _campaign_roles(plan, worlds.split, c2.gate_v_v2_validation_run_id, traded=True)
    before = dataclasses.asdict(roles["mc"])
    assert c2.monte_carlo_evidence_complete_v2(plan, roles["wf"], roles["mc"]) is True
    assert dataclasses.asdict(roles["mc"]) == before
    with pytest.raises(ValueError):
        c2.monte_carlo_evidence_complete_v2(worlds.v1_plan, roles["wf"], roles["mc"])
    for bad in (None, {}, "run"):
        with pytest.raises(ValueError):
            c2.monte_carlo_evidence_complete_v2(plan, roles["wf"], bad)
    for bad_wf in ({}, "run", roles["mc"]):  # une WF absente est None ; tout autre non-WF est une erreur
        with pytest.raises(ValueError):
            c2.monte_carlo_evidence_complete_v2(plan, bad_wf, roles["mc"])


# ============================================================================================
# Tranche 5 — Parameter Stability complète pour UN fold (Décision 21.6)
# ============================================================================================


def _source_fold(roles, index):
    return roles["wf"].evidence.fold_results[index]


def _ps_v1(plan, roles, *, source=True):
    fold_id = plan.expected_fold_ids[0]
    return gate_v_campaign._parameter_stability_quality(
        plan, roles[f"ps:{fold_id}"], fold_id, gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD),
        _source_fold(roles, 0) if source else None,
    )


def _ps_v2(plan, roles, *, source=True):
    fold_id = plan.expected_fold_ids[0]
    return c2.parameter_stability_evidence_complete_v2(
        plan, roles[f"ps:{fold_id}"], fold_id, _source_fold(roles, 0) if source else None,
    )


def _ps_v1_without_source(plan, roles):
    return _ps_v1(plan, roles, source=False)


def _ps_v2_without_source(plan, roles):
    return _ps_v2(plan, roles, source=False)


def _ps_spec(**changes):
    """Spécification PS reconstruite avec un seul paramètre altéré (les autres viennent de la preuve)."""
    def mutate(run):
        base = run.specification
        spec = build_parameter_stability_specification(
            changes.get("source", base.source_validation_run_id), changes.get("mode", base.search_mode),
            changes.get("circular", base.source_candidates_from_optimized_search), changes.get("policy"),
            changes.get("fold", base.source_fold_id),
        )
        return dataclasses.replace(run, specification=spec)
    return mutate


_NO_JSON_PS = frozenset()
_PS_MUTATIONS = [
    ("baseline_complete", None, "complete"),
    ("specification_missing", _replace_run(specification=None), "ValueError"),
    ("evidence_wrong_type", _replace_run(evidence=_SUMMARY), "ValueError"),
    ("specification_from_foreign_walk_forward", _ps_spec(source="gate_v_v2_other_walk_forward"), "ValueError"),
    ("specification_for_another_fold", _ps_spec(fold="fold_999"), "ValueError"),
    ("specification_search_mode_differs", _ps_spec(mode="general"), "ValueError"),
    ("specification_not_declared_circular", _ps_spec(circular=False), "ValueError"),
    ("specification_with_verdict_policy", _ps_spec(policy="some_policy"), "ValueError"),
    ("evidence_search_mode_differs", _replace_evidence(search_mode="general"), "ValueError"),
    ("execution_status_not_completed", _replace_evidence(execution_status="failed"), "incomplete"),
    ("best_params_differ_from_top_1_train", _replace_evidence(best_params={"lookback": 13}), "ValueError"),
    ("best_score_differs_from_top_1_train", _replace_evidence(best_score=2.0), "ValueError"),
    ("candidate_pool_differs_from_train", _replace_evidence(n_candidates_total=3), "ValueError"),
    ("neighbor_counters_not_dicts", _replace_evidence(n_neighbors_total_by_param=[1]), "ValueError"),
    ("neighbor_total_negative", _replace_evidence(n_neighbors_total_by_param={"lookback": -1}), "ValueError"),
    ("neighbor_rejected_above_total", _replace_evidence(n_neighbors_rejected_by_param={"lookback": 2}), "ValueError"),
    ("neighbor_total_above_pool", _replace_evidence(n_neighbors_total_by_param={"lookback": 2}), "ValueError"),
    ("neighbor_total_bool", _replace_evidence(n_neighbors_total_by_param={"lookback": True}), "ValueError"),
    ("neighbor_rejected_bool", _replace_evidence(n_neighbors_rejected_by_param={"lookback": False}), "ValueError"),
    ("neighbor_counters_incomplete", _replace_evidence(n_neighbors_rejected_by_param={}), "ValueError"),
    ("neighborhood_fully_rejected", _replace_evidence(n_neighbors_rejected_by_param={"lookback": 1}), "incomplete"),
    ("neighborhood_empty", _replace_evidence(
        n_neighbors_total_by_param={"lookback": 0}, n_neighbors_rejected_by_param={"lookback": 0}), "incomplete"),
    ("neighborhood_not_applicable", _replace_evidence(neighborhood_applicability="no_local_neighborhood"),
     "incomplete"),
    ("degradation_missing", _replace_evidence(degradation_by_param={}), "incomplete"),
    ("degradation_points_none", _replace_evidence(degradation_points_by_param={"lookback": None}), "incomplete"),
    ("degradation_not_a_dict", _replace_evidence(degradation_by_param=[_SUMMARY]), "incomplete"),
    ("percentile_missing", _replace_evidence(
        degradation_by_param={"lookback": PercentileDistributionSummary(0.1, None, 0.3, 0.4, 0.5)}), "incomplete"),
    ("percentile_nan", _replace_evidence(
        degradation_points_by_param={"lookback": PercentileDistributionSummary(0.1, 0.2, _NAN, 0.4, 0.5)}),
     "incomplete"),
    ("percentile_not_a_number", _replace_evidence(
        degradation_by_param={"lookback": PercentileDistributionSummary(0.1, 0.2, "x", 0.4, 0.5)}), "incomplete"),
]


def _ps_cases():
    for name, mutation, expected in _PS_MUTATIONS:
        for traded in (False, True):
            for as_json in (False,) if name in _WITHOUT_JSON_FORM | _NO_JSON_PS | {"evidence_wrong_type"} else (False, True):
                label = "json" if as_json else "objects"
                yield pytest.param(
                    name, mutation, traded, as_json, expected, id=f"{name}-{'traded' if traded else 'zero'}-{label}",
                )


@pytest.mark.parametrize("name,mutation,traded,as_json,expected", list(_ps_cases()))
def test_parameter_stability_completeness_has_the_declared_outcome_in_v1_and_in_v2(
    worlds, scratch, name, mutation, traded, as_json, expected,
):
    outcomes = _judge(
        worlds, scratch, traded=traded, role="ps:first", mutation=mutation, as_json=as_json,
        v1_call=_ps_v1, v2_call=_ps_v2,
    )
    assert outcomes == {"v1": expected, "v2": expected}, name


@pytest.mark.parametrize("name,mutation,expected", [
    # Règle de saut héritée de V1, explicitée (21.6) : sans fold WF source, la correspondance
    # Top-1/pool TRAIN est sautée (la WF est alors elle-même incomplète).
    ("best_params_not_compared_without_source_fold", _replace_evidence(best_params={"lookback": 13}), "complete"),
    ("baseline_without_source_fold", None, "complete"),
    ("provenance_still_checked_without_source_fold", _ps_spec(fold="fold_999"), "ValueError"),
])
def test_parameter_stability_skips_the_top_1_match_without_a_source_fold_like_v1(
    worlds, scratch, name, mutation, expected,
):
    outcomes = _judge(
        worlds, scratch, traded=False, role="ps:first", mutation=mutation, as_json=False,
        v1_call=_ps_v1_without_source, v2_call=_ps_v2_without_source,
    )
    assert outcomes == {"v1": expected, "v2": expected}, name


def test_parameter_stability_refuses_a_source_fold_without_a_selection_like_v1(worlds, scratch):
    outcomes = {}
    for label, plan, run_id_fn, call in (
        ("v1", worlds.v1_plan, gate_v_campaign.gate_v_validation_run_id, "v1"),
        ("v2", worlds.v2_plan, c2.gate_v_v2_validation_run_id, "v2"),
    ):
        roles = _campaign_roles(plan, worlds.split, run_id_fn, traded=False)
        fold_id = plan.expected_fold_ids[0]
        source = dataclasses.replace(_source_fold(roles, 0), selection=None)
        ps = roles[f"ps:{fold_id}"]
        if call == "v1":
            wf_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
            outcomes[label] = _outcome(
                lambda: gate_v_campaign._parameter_stability_quality(plan, ps, fold_id, wf_id, source),
            )
        else:
            outcomes[label] = _outcome(
                lambda: c2.parameter_stability_evidence_complete_v2(plan, ps, fold_id, source),
            )
    assert outcomes == {"v1": "ValueError", "v2": "ValueError"}


@pytest.mark.parametrize("name,mutation", [
    ("percentile_is_a_bool", _replace_evidence(
        degradation_by_param={"lookback": PercentileDistributionSummary(0.1, 0.2, True, 0.4, 0.5)})),
    ("points_percentile_is_a_bool", _replace_evidence(
        degradation_points_by_param={"lookback": PercentileDistributionSummary(False, 0.2, 0.3, 0.4, 0.5)})),
])
def test_v2_diverges_from_v1_by_refusing_a_bool_as_a_degradation_percentile(worlds, scratch, name, mutation):
    """Divergence DÉCIDÉE (D1), même classe que Walk-Forward/Monte-Carlo : ``bool`` n'est pas une mesure."""
    outcomes = _judge(
        worlds, scratch, traded=False, role="ps:first", mutation=mutation, as_json=False,
        v1_call=_ps_v1, v2_call=_ps_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "incomplete"}, name


def test_v2_diverges_from_v1_by_raising_value_error_instead_of_leaking_type_error(worlds, scratch):
    """Divergence DÉCIDÉE (D1) : sans fold source, ``n_candidates_total=None`` fait lever un ``TypeError``
    (``None - 1``) dans V1. Une preuve corrompue est une ``ValueError`` de contrat, jamais un crash non
    typé que l'appelant ne saurait pas classer."""
    outcomes = _judge(
        worlds, scratch, traded=False, role="ps:first", mutation=_replace_evidence(n_candidates_total=None),
        as_json=False, v1_call=_ps_v1_without_source, v2_call=_ps_v2_without_source,
    )
    assert outcomes == {"v1": "TypeError", "v2": "ValueError"}


def test_parameter_stability_completeness_refuses_a_v1_plan_a_foreign_fold_and_non_runs(worlds):
    plan = worlds.v2_plan
    roles = _campaign_roles(plan, worlds.split, c2.gate_v_v2_validation_run_id, traded=False)
    fold_id = plan.expected_fold_ids[0]
    ps = roles[f"ps:{fold_id}"]
    before = dataclasses.asdict(ps)
    assert c2.parameter_stability_evidence_complete_v2(plan, ps, fold_id, _source_fold(roles, 0)) is True
    assert dataclasses.asdict(ps) == before
    with pytest.raises(ValueError):
        c2.parameter_stability_evidence_complete_v2(worlds.v1_plan, ps, fold_id, None)
    for bad_fold in ("fold_999", None, ""):
        with pytest.raises(ValueError):
            c2.parameter_stability_evidence_complete_v2(plan, ps, bad_fold, None)
    for bad_run in (None, {}, "run"):
        with pytest.raises(ValueError):
            c2.parameter_stability_evidence_complete_v2(plan, bad_run, fold_id, None)


# ============================================================================================
# Tranche 6 — évaluateur de faits : WF + MC + PS de TOUS les folds attendus (Décision 21.6)
# ============================================================================================


def _composite_v1(worlds):
    """Statut composé V1 réduit à la seule question de complétude interne (OOS fourni et valide)."""
    def call(plan, roles):
        ids = _role_ids(plan, gate_v_campaign.gate_v_validation_run_id)
        manifest = dataclasses.replace(
            gate_v_campaign.build_gate_v_campaign_manifest(plan), execution_started=True,
            walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=ids["mc"],
            parameter_stability_validation_run_ids_by_fold={fold: ids[f"ps:{fold}"] for fold in plan.expected_fold_ids},
        )
        mapping = _mapping(plan, gate_v_campaign.gate_v_validation_run_id, roles)
        mapping[plan.oos_evidence_validation_run_id] = worlds.oos_run
        status = gate_v_campaign.derive_gate_v_campaign_status(plan, manifest, mapping)
        assert status in {"EVIDENCE_INCOMPLETE", "EVIDENCE_COMPLETE_AWAITING_POLICY"}
        return status == "EVIDENCE_COMPLETE_AWAITING_POLICY"
    return call


def _composite_v2(plan, roles):
    mapping = _mapping(plan, c2.gate_v_v2_validation_run_id, roles)
    return c2.evaluate_pre_holdout_evidence_v2(plan, mapping).pre_holdout_evidence_complete


def _composite_cases():
    for name, mutation, scope, _expected in _SCOPED_MUTATIONS:
        for role in ("wf", "mc", "ps:first", "ps:last"):
            if scope == "all" or scope == ("ps" if role.startswith("ps") else "wf_mc"):
                for traded in (False, True):
                    yield pytest.param(f"scoped_{name}", role, mutation, traded, False, id=f"scoped-{name}-{role}-{traded}")
    for catalog, role, no_json in (
        (_WF_MUTATIONS, "wf", _WITHOUT_JSON_FORM), (_MC_MUTATIONS, "mc", _WITHOUT_JSON_FORM | _NO_JSON_NAN),
        ([(n, m, None, e) for n, m, e in _PS_MUTATIONS], "ps:first", _WITHOUT_JSON_FORM | _NO_JSON_PS | {"evidence_wrong_type"}),
    ):
        for name, mutation, variants, _expected in catalog:
            for traded in (False, True):
                if variants is not None and ("traded" if traded else "zero") not in variants:
                    continue
                for as_json in (False,) if name in no_json else (False, True):
                    yield pytest.param(
                        f"{role}_{name}", role, mutation, traded, as_json,
                        id=f"{role}-{name}-{'traded' if traded else 'zero'}-{'json' if as_json else 'objects'}",
                    )


@pytest.mark.parametrize("name,role,mutation,traded,as_json", list(_composite_cases()))
def test_pre_holdout_evidence_facts_agree_with_the_v1_composed_status_on_every_mutation(
    worlds, scratch, name, role, mutation, traded, as_json,
):
    outcomes = _judge(
        worlds, scratch, traded=traded, role=role, mutation=mutation, as_json=as_json,
        v1_call=_composite_v1(worlds), v2_call=_composite_v2,
    )
    assert outcomes["v1"] == outcomes["v2"], f"{name}: {outcomes}"
    assert outcomes["v1"] in {"complete", "incomplete", "ValueError"}


@pytest.mark.parametrize("traded", [False, True])
@pytest.mark.parametrize("missing", ["wf", "mc", "ps:first", "ps:last", "all"])
def test_a_missing_proof_makes_the_evidence_incomplete_exactly_like_v1(worlds, scratch, traded, missing):
    def drop(run):
        return None
    outcomes = {}
    for label, plan, run_id_fn, call in (
        ("v1", worlds.v1_plan, gate_v_campaign.gate_v_validation_run_id, _composite_v1(worlds)),
        ("v2", worlds.v2_plan, c2.gate_v_v2_validation_run_id, _composite_v2),
    ):
        roles = _campaign_roles(plan, worlds.split, run_id_fn, traded=traded)
        if missing == "all":
            roles = {name: None for name in roles}
        else:
            roles[_resolve_role(plan, missing)] = drop(None)
        outcomes[label] = _outcome(lambda: call(plan, roles))
    assert outcomes == {"v1": "incomplete", "v2": "incomplete"}


@pytest.mark.parametrize("traded", [False, True])
def test_complete_evidence_is_complete_in_v1_and_v2_with_the_exact_facts(worlds, scratch, traded):
    outcomes = _judge(
        worlds, scratch, traded=traded, role="wf", mutation=None, as_json=False,
        v1_call=_composite_v1(worlds), v2_call=_composite_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "complete"}
    plan = worlds.v2_plan
    roles = _campaign_roles(plan, worlds.split, c2.gate_v_v2_validation_run_id, traded=traded)
    facts = c2.evaluate_pre_holdout_evidence_v2(plan, _mapping(plan, c2.gate_v_v2_validation_run_id, roles))
    assert facts == c2.GateVPreHoldoutEvidenceFacts(
        walk_forward_complete=True, monte_carlo_complete=True,
        parameter_stability_complete_fold_ids=plan.expected_fold_ids,
        parameter_stability_incomplete_fold_ids=(), pre_holdout_evidence_complete=True,
    )


def test_facts_name_each_incomplete_fold_and_never_complete_a_partial_campaign(worlds):
    plan = worlds.v2_plan
    folds = plan.expected_fold_ids
    roles = _campaign_roles(plan, worlds.split, c2.gate_v_v2_validation_run_id, traded=True)
    roles[f"ps:{folds[0]}"] = None  # preuve manquante
    roles[f"ps:{folds[2]}"] = _replace_evidence(n_neighbors_rejected_by_param={"lookback": 1})(roles[f"ps:{folds[2]}"])
    facts = c2.evaluate_pre_holdout_evidence_v2(plan, _mapping(plan, c2.gate_v_v2_validation_run_id, roles))
    assert facts.walk_forward_complete is True and facts.monte_carlo_complete is True
    assert facts.parameter_stability_complete_fold_ids == (folds[1],)
    assert facts.parameter_stability_incomplete_fold_ids == (folds[0], folds[2])
    assert facts.pre_holdout_evidence_complete is False


def test_facts_of_an_empty_mapping_are_all_incomplete(worlds):
    plan = worlds.v2_plan
    facts = c2.evaluate_pre_holdout_evidence_v2(plan, {})
    assert facts == c2.GateVPreHoldoutEvidenceFacts(
        walk_forward_complete=False, monte_carlo_complete=False, parameter_stability_complete_fold_ids=(),
        parameter_stability_incomplete_fold_ids=plan.expected_fold_ids, pre_holdout_evidence_complete=False,
    )


def test_unreferenced_and_foreign_entries_in_the_mapping_are_never_evidence(worlds):
    """Seuls les identifiants déterministes du plan font autorité : une entrée supplémentaire (même une
    run complète portant un autre fold ou un identifiant libre) est ignorée (Décision 21.6)."""
    plan = worlds.v2_plan
    roles = _campaign_roles(plan, worlds.split, c2.gate_v_v2_validation_run_id, traded=True)
    mapping = _mapping(plan, c2.gate_v_v2_validation_run_id, roles)
    extra = dataclasses.replace(roles["wf"], validation_run_id="free_form_id")
    mapping["free_form_id"] = extra
    mapping[f"{plan.campaign_id}_parameter_stability_fold_999"] = roles[f"ps:{plan.expected_fold_ids[0]}"]
    assert c2.evaluate_pre_holdout_evidence_v2(plan, mapping).pre_holdout_evidence_complete is True
    del mapping[c2.gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)]
    assert c2.evaluate_pre_holdout_evidence_v2(plan, mapping).walk_forward_complete is False


def test_facts_expose_no_verdict_and_are_immutable(worlds):
    fields = {field.name for field in dataclasses.fields(c2.GateVPreHoldoutEvidenceFacts)}
    assert fields == {
        "walk_forward_complete", "monte_carlo_complete", "parameter_stability_complete_fold_ids",
        "parameter_stability_incomplete_fold_ids", "pre_holdout_evidence_complete",
    }
    forbidden = {"pass", "fail", "champion", "verdict", "score", "status", "ready", "approved"}
    assert not {segment for name in fields for segment in name.split("_")} & forbidden
    facts = c2.evaluate_pre_holdout_evidence_v2(worlds.v2_plan, {})
    with pytest.raises(dataclasses.FrozenInstanceError):
        facts.pre_holdout_evidence_complete = True


def test_evaluator_is_deterministic_pure_and_refuses_a_v1_plan_and_a_non_mapping(worlds):
    plan = worlds.v2_plan
    roles = _campaign_roles(plan, worlds.split, c2.gate_v_v2_validation_run_id, traded=True)
    mapping = _mapping(plan, c2.gate_v_v2_validation_run_id, roles)
    snapshot = {key: dataclasses.asdict(run) for key, run in mapping.items()}
    assert c2.evaluate_pre_holdout_evidence_v2(plan, mapping) == c2.evaluate_pre_holdout_evidence_v2(plan, mapping)
    assert {key: dataclasses.asdict(run) for key, run in mapping.items()} == snapshot
    with pytest.raises(ValueError):
        c2.evaluate_pre_holdout_evidence_v2(worlds.v1_plan, mapping)
    for bad in (None, [], "mapping"):
        with pytest.raises(ValueError):
            c2.evaluate_pre_holdout_evidence_v2(plan, bad)


# ============================================================================================
# Tranche 7 — architecture : module pur, sans V1, sans I/O, surface minimale
# ============================================================================================

_MODULE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gate_v_evidence_completeness_v2.py")


def _module_tree():
    with open(_MODULE_PATH, encoding="utf-8") as handle:
        return ast.parse(handle.read())


def _imported_modules(tree):
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    return modules


def test_module_imports_only_the_declared_pure_dependencies_and_never_gate_v_campaign():
    assert _imported_modules(_module_tree()) == {
        "__future__", "math", "dataclasses", "typing", "atomic_json_store", "gate_v_campaign_plan_v2",
        "gate_v_preregistration", "validation_run", "walk_forward",
    }


def test_module_never_loads_v1_the_oos_runner_or_the_engine_even_transitively():
    code = (
        "import sys, gate_v_evidence_completeness_v2;"
        "banned = {'gate_v_campaign', 'validation_oos', 'engine'};"
        "assert not banned & set(sys.modules), sorted(banned & set(sys.modules))"
    )
    root = os.path.dirname(_MODULE_PATH)
    result = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_module_performs_no_io_no_clock_no_randomness_and_no_holdout_access():
    forbidden = {
        "open", "os", "subprocess", "time", "datetime", "random", "uuid", "pathlib", "Path", "shutil", "socket",
        "print", "input", "pandas", "numpy", "json", "save_exclusive", "load_json_tolerant",
        "FinalHoldoutAccessClaim", "run_gate_v_final_holdout_validation", "HoldoutAccessEvent",
    }
    names = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    assert not names & forbidden, sorted(names & forbidden)


def test_public_surface_is_the_minimal_declared_api_without_verdict_vocabulary():
    public = {
        name for name, value in vars(c2).items()
        if not name.startswith("_") and getattr(value, "__module__", None) == c2.__name__
    }
    assert public == {
        "gate_v_v2_validation_run_id", "validate_scoped_evidence_run_v2", "walk_forward_evidence_complete_v2",
        "monte_carlo_evidence_complete_v2", "parameter_stability_evidence_complete_v2",
        "GateVPreHoldoutEvidenceFacts", "evaluate_pre_holdout_evidence_v2",
    }
    segments = {segment.lower() for name in public for segment in name.split("_")}
    assert not segments & {"pass", "fail", "champion", "verdict", "score", "claim", "manifest"}


def test_v2_diverges_from_v1_by_raising_value_error_instead_of_an_untyped_attribute_error_on_invalid_inputs(worlds):
    """Divergence DÉCIDÉE (D1, n°3) : une entrée qui n'est pas du type attendu est une ``ValueError`` de
    contrat en V2 ; V1 laisse remonter un ``AttributeError`` que l'appelant ne saurait pas classer."""
    v1, v2 = worlds.v1_plan, worlds.v2_plan
    v1_roles = _campaign_roles(v1, worlds.split, gate_v_campaign.gate_v_validation_run_id, traded=False)
    v2_roles = _campaign_roles(v2, worlds.split, c2.gate_v_v2_validation_run_id, traded=False)
    v1_wf_id = gate_v_campaign.gate_v_validation_run_id(v1, VALIDATION_TYPE_WALK_FORWARD)
    v2_wf_id = c2.gate_v_v2_validation_run_id(v2, VALIDATION_TYPE_WALK_FORWARD)
    cases = [
        (lambda: gate_v_campaign._validate_scoped_run(v1, v1_wf_id, VALIDATION_TYPE_WALK_FORWARD, None),
         lambda: c2.validate_scoped_evidence_run_v2(v2, v2_wf_id, VALIDATION_TYPE_WALK_FORWARD, None)),
        (lambda: gate_v_campaign._walk_forward_complete(v1, None),
         lambda: c2.walk_forward_evidence_complete_v2(v2, None)),
        (lambda: gate_v_campaign._monte_carlo_complete(v1, v1_roles["wf"], None),
         lambda: c2.monte_carlo_evidence_complete_v2(v2, v2_roles["wf"], None)),
    ]
    for v1_call, v2_call in cases:
        assert (_outcome(v1_call), _outcome(v2_call)) == ("AttributeError", "ValueError")


def test_module_states_that_v1_stays_frozen_and_is_protected_by_differential_tests():
    docstring = " ".join(ast.get_docstring(_module_tree()).split())
    assert (
        "V1 intentionally remains frozen. This V2 implementation is independently versioned and "
        "protected by differential tests."
    ) in docstring
    assert "identical forever" not in docstring.lower()


# ============================================================================================
# Tranche 8 — corrections issues de la revue adversariale (axes scientifique + architecture)
# ============================================================================================


def _all_folds_without_loss(run):
    """Preuve produite par le VRAI producteur d'agrégat quand aucun trade ne perd (profit factor = inf)."""
    folds = tuple(
        dataclasses.replace(fold, gross_loss=0.0, profit_factor=float("inf")) for fold in run.evidence.fold_results
    )
    return dataclasses.replace(
        run, evidence=dataclasses.replace(run.evidence, fold_results=folds, aggregate=build_aggregate_result(folds)),
    )


# Divergence V2 n°5 : l'agrégat doit être EXACTEMENT celui que le producteur recalcule depuis les folds
# (V1 ne compare que trois compteurs ; la policy lira pourtant `oos_net_return_pct` sans autre garde).
_FORGED_AGGREGATES = [
    ("net_return_forged", _aggregate_replace(oos_net_return_pct=-999.0), _TRADED),
    ("net_return_nan", _aggregate_replace(oos_net_return_pct=_NAN), _TRADED),
    ("max_drawdown_forged", _aggregate_replace(oos_max_dd_pct=12.0), _BOTH),
    ("profit_factor_forged", _aggregate_replace(oos_profit_factor=99.0), _BOTH),
    ("win_rate_forged", _aggregate_replace(oos_win_rate=0.99), _TRADED),
    ("worst_fold_foreign", _aggregate_replace(worst_fold_id="fold_999"), _BOTH),
    ("mean_score_forged", _aggregate_replace(mean_fold_score_test=42.0), _BOTH),
    ("sharpe_invented", _aggregate_replace(oos_sharpe=3.0), _BOTH),
    ("total_trades_is_a_float", _aggregate_replace(total_oos_trades=15.0), _TRADED),
    ("n_folds_is_a_float", _aggregate_replace(n_folds=3.0), _BOTH),
    ("zero_trade_profit_factor_invented", _aggregate_replace(oos_profit_factor=2.0), _ZERO),
]


def _forged_aggregate_cases():
    for name, mutation, variants in _FORGED_AGGREGATES:
        for variant in variants:
            for as_json in (False, True):
                label = "json" if as_json else "objects"
                yield pytest.param(name, mutation, variant == "traded", as_json, id=f"{name}-{variant}-{label}")


@pytest.mark.parametrize("name,mutation,traded,as_json", list(_forged_aggregate_cases()))
def test_v2_diverges_from_v1_by_recomputing_the_walk_forward_aggregate_from_the_folds(
    worlds, scratch, name, mutation, traded, as_json,
):
    outcomes = _judge(
        worlds, scratch, traded=traded, role="wf", mutation=mutation, as_json=as_json, v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "ValueError"}, name


@pytest.mark.parametrize("as_json", [False, True])
def test_an_infinite_profit_factor_from_the_real_producer_is_complete_in_v1_and_v2(worlds, scratch, as_json):
    outcomes = _judge(
        worlds, scratch, traded=True, role="wf", mutation=_all_folds_without_loss, as_json=as_json,
        v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "complete"}


# Divergence V2 n°2 (élargie) : un compteur structurel mal typé est TOUJOURS une ValueError.
@pytest.mark.parametrize("name,mutation,traded,v1_outcome", [
    ("n_input_trades_missing", _replace_evidence(n_input_trades=None), True, "TypeError"),
    ("n_input_trades_is_a_bool", _replace_evidence(n_input_trades=True), True, "complete"),
    ("n_input_trades_is_a_float", _replace_evidence(n_input_trades=15.0), True, "complete"),
    ("zero_trade_n_input_trades_is_a_bool", _replace_evidence(n_input_trades=False), False, "complete"),
])
def test_v2_diverges_from_v1_by_refusing_a_malformed_monte_carlo_trade_counter_in_every_branch(
    worlds, scratch, name, mutation, traded, v1_outcome,
):
    outcomes = _judge(
        worlds, scratch, traded=traded, role="mc", mutation=mutation, as_json=False,
        v1_call=_mc_without_wf_v1, v2_call=_mc_without_wf_v2,
    )
    assert outcomes == {"v1": v1_outcome, "v2": "ValueError"}, name


@pytest.mark.parametrize("name,mutation,v1_outcome", [
    ("pool_size_missing_with_empty_counters", _replace_evidence(
        n_candidates_total=None, best_params=None, n_neighbors_total_by_param={}, n_neighbors_rejected_by_param={},
        degradation_by_param={}, degradation_points_by_param={}), "incomplete"),
    ("pool_size_is_a_float", _replace_evidence(n_candidates_total=2.0), "complete"),
])
def test_v2_diverges_from_v1_by_refusing_a_malformed_parameter_stability_pool_size_in_every_branch(
    worlds, scratch, name, mutation, v1_outcome,
):
    v1_call, v2_call = (
        (_ps_v1, _ps_v2) if name == "pool_size_is_a_float" else (_ps_v1_without_source, _ps_v2_without_source)
    )
    outcomes = _judge(
        worlds, scratch, traded=False, role="ps:first", mutation=mutation, as_json=False,
        v1_call=v1_call, v2_call=v2_call,
    )
    assert outcomes == {"v1": v1_outcome, "v2": "ValueError"}, name


def _ps_calls(index):
    """PS du fold ``index`` jugée contre le fold WF source de MÊME rang."""
    def v1(plan, roles):
        fold_id = plan.expected_fold_ids[index]
        return gate_v_campaign._parameter_stability_quality(
            plan, roles[f"ps:{fold_id}"], fold_id,
            gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD), _source_fold(roles, index),
        )

    def v2(plan, roles):
        fold_id = plan.expected_fold_ids[index]
        return c2.parameter_stability_evidence_complete_v2(
            plan, roles[f"ps:{fold_id}"], fold_id, _source_fold(roles, index),
        )
    return v1, v2


@pytest.mark.parametrize("name,mutation,expected", [
    ("baseline_complete", None, "complete"),
    ("best_params_differ_from_top_1_train", _replace_evidence(best_params={"lookback": 99}), "ValueError"),
    ("best_score_differs_from_top_1_train", _replace_evidence(best_score=99.0), "ValueError"),
    ("candidate_pool_differs_from_train", _replace_evidence(n_candidates_total=99), "ValueError"),
    ("neighborhood_fully_rejected", _replace_evidence(n_neighbors_rejected_by_param={"lookback": 1}), "incomplete"),
    ("specification_for_another_fold", _ps_spec(fold="fold_000"), "ValueError"),
])
def test_parameter_stability_of_the_last_fold_is_judged_against_its_own_source_fold(
    worlds, scratch, name, mutation, expected,
):
    v1_call, v2_call = _ps_calls(len(worlds.v2_plan.expected_fold_ids) - 1)
    outcomes = _judge(
        worlds, scratch, traded=False, role="ps:last", mutation=mutation, as_json=False,
        v1_call=v1_call, v2_call=v2_call,
    )
    assert outcomes == {"v1": expected, "v2": expected}, name


def test_a_parameter_stability_matched_to_the_source_fold_of_another_fold_is_refused_like_v1(worlds, scratch):
    last = len(worlds.v2_plan.expected_fold_ids) - 1

    def v1(plan, roles):
        fold_id = plan.expected_fold_ids[last]
        return gate_v_campaign._parameter_stability_quality(
            plan, roles[f"ps:{fold_id}"], fold_id,
            gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD), _source_fold(roles, 0),
        )

    def v2(plan, roles):
        fold_id = plan.expected_fold_ids[last]
        return c2.parameter_stability_evidence_complete_v2(
            plan, roles[f"ps:{fold_id}"], fold_id, _source_fold(roles, 0),
        )
    outcomes = _judge(
        worlds, scratch, traded=False, role="ps:last", mutation=None, as_json=False, v1_call=v1, v2_call=v2,
    )
    assert outcomes == {"v1": "ValueError", "v2": "ValueError"}


# Divergence V2 n°4 : les compteurs de voisinage couvrent EXACTEMENT les paramètres sélectionnés
# (le producteur indexe par ``best_params.keys()``) ; V1 ne relie jamais ces clés à ``best_params``.
_OTHER_KEYED = dict(
    n_neighbors_total_by_param={"other": 1}, n_neighbors_rejected_by_param={"other": 0},
    degradation_by_param={"other": _SUMMARY}, degradation_points_by_param={"other": _SUMMARY},
)


def test_v2_diverges_from_v1_by_tying_neighbour_counters_to_the_selected_parameters(worlds, scratch):
    outcomes = _judge(
        worlds, scratch, traded=False, role="ps:first", mutation=_replace_evidence(**_OTHER_KEYED),
        as_json=False, v1_call=_ps_v1, v2_call=_ps_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "ValueError"}


def _two_parameter_roles(plan, split, run_id_fn, evidence_changes):
    """Fold 0 sélectionne DEUX paramètres (source WF et PS cohérents) ; ``evidence_changes`` altère la PS."""
    roles = _campaign_roles(plan, split, run_id_fn, traded=False)
    params = {"lookback": 12, "other": 3}
    roles["wf"] = _selection_replace(0, selected_params=dict(params))(roles["wf"])
    key = f"ps:{plan.expected_fold_ids[0]}"
    base = dict(
        best_params=dict(params), n_neighbors_total_by_param={"lookback": 1, "other": 1},
        n_neighbors_rejected_by_param={"lookback": 0, "other": 0},
        degradation_by_param={"lookback": _SUMMARY, "other": _SUMMARY},
        degradation_points_by_param={"lookback": _SUMMARY, "other": _SUMMARY},
        sensitivity={"lookback": 0.0, "other": 0.0}, sensitivity_sample_size_by_param={"lookback": 2, "other": 2},
    )
    roles[key] = _replace_evidence(**{**base, **evidence_changes})(roles[key])
    return roles


@pytest.mark.parametrize("name,changes,expected", [
    ("both_parameters_usable", {}, "complete"),
    ("one_parameter_fully_rejected_next_to_a_usable_one", dict(
        n_neighbors_rejected_by_param={"lookback": 1, "other": 0},
        degradation_by_param={"lookback": None, "other": _SUMMARY},
        degradation_points_by_param={"lookback": None, "other": _SUMMARY}), "complete"),
    ("usable_parameter_without_degradation", dict(degradation_by_param={"lookback": _SUMMARY}), "incomplete"),
    ("rejected_counters_with_an_extra_key", dict(
        n_neighbors_rejected_by_param={"lookback": 0, "other": 0, "ghost": 0}), "ValueError"),
    ("totals_with_an_extra_key", dict(
        n_neighbors_total_by_param={"lookback": 1, "other": 1, "ghost": 0},
        n_neighbors_rejected_by_param={"lookback": 0, "other": 0, "ghost": 0}), "ValueError_v2_only"),
    ("a_selected_parameter_has_no_counter", dict(
        n_neighbors_total_by_param={"lookback": 1}, n_neighbors_rejected_by_param={"lookback": 0}),
     "ValueError_v2_only"),
])
def test_parameter_stability_with_two_selected_parameters(worlds, name, changes, expected):
    outcomes = {}
    for label, plan, run_id_fn, call in (
        ("v1", worlds.v1_plan, gate_v_campaign.gate_v_validation_run_id, _ps_calls(0)[0]),
        ("v2", worlds.v2_plan, c2.gate_v_v2_validation_run_id, _ps_calls(0)[1]),
    ):
        roles = _two_parameter_roles(plan, worlds.split, run_id_fn, changes)
        outcomes[label] = _outcome(lambda: call(plan, roles))
    if expected == "ValueError_v2_only":  # divergence n°4 : V1 ne relie pas les clés à best_params
        assert outcomes["v2"] == "ValueError" and outcomes["v1"] in {"complete", "incomplete"}, name
    else:
        assert outcomes == {"v1": expected, "v2": expected}, name


def test_without_a_source_fold_only_the_top_1_match_is_skipped_and_the_other_ps_checks_still_apply(worlds, scratch):
    """ADR 0025 §21.6 : « sans fold WF source, la correspondance Top-1 d'un fold PS est sautée ». Seule cette
    comparaison est sautée ; spécification, compteurs, clés de paramètres, voisinage et distributions restent
    contrôlés, avec les mêmes issues que V1 (hors divergences décidées)."""
    cases = [
        ("top_1_best_params_not_compared", _replace_evidence(best_params={"lookback": 999}), "complete"),
        ("top_1_best_score_not_compared", _replace_evidence(best_score=-5.0), "complete"),
        ("top_1_pool_size_not_compared", _replace_evidence(n_candidates_total=7), "complete"),
        ("foreign_provenance_still_refused", _ps_spec(source="gate_v_v2_other_walk_forward"), "ValueError"),
        ("incoherent_counters_still_refused", _replace_evidence(n_neighbors_rejected_by_param={"lookback": 2}),
         "ValueError"),
        ("unusable_neighborhood_still_incomplete", _replace_evidence(n_neighbors_rejected_by_param={"lookback": 1}),
         "incomplete"),
        ("missing_degradation_still_incomplete", _replace_evidence(degradation_by_param={}), "incomplete"),
        ("execution_status_still_incomplete", _replace_evidence(execution_status="failed"), "incomplete"),
    ]
    for name, mutation, expected in cases:
        outcomes = _judge(
            worlds, scratch, traded=False, role="ps:first", mutation=mutation, as_json=False,
            v1_call=_ps_v1_without_source, v2_call=_ps_v2_without_source,
        )
        assert outcomes == {"v1": expected, "v2": expected}, name
    # Divergence n°4 (clés = best_params) s'applique aussi sans fold source : durcissement V2 indépendant du saut.
    outcomes = _judge(
        worlds, scratch, traded=False, role="ps:first", mutation=_replace_evidence(**_OTHER_KEYED),
        as_json=False, v1_call=_ps_v1_without_source, v2_call=_ps_v2_without_source,
    )
    assert outcomes == {"v1": "complete", "v2": "ValueError"}


def test_a_missing_wf_fold_keeps_each_ps_fact_but_the_composite_stays_incomplete(worlds):
    """Séparation normative : un PS individuellement exploitable est listé complet même sans fold WF source
    (règle de saut de §21.6) ; la complétude pré-FINAL_HOLDOUT reste fail-closed car la WF est incomplète."""
    plan = worlds.v2_plan
    folds = plan.expected_fold_ids
    roles = _campaign_roles(plan, worlds.split, c2.gate_v_v2_validation_run_id, traded=True)
    roles["wf"] = _folds_edit(lambda items: items[:-1])(roles["wf"])
    mapping = _mapping(plan, c2.gate_v_v2_validation_run_id, roles)
    facts = c2.evaluate_pre_holdout_evidence_v2(plan, mapping)
    assert facts.walk_forward_complete is False
    assert facts.parameter_stability_complete_fold_ids == folds
    assert facts.parameter_stability_incomplete_fold_ids == ()
    assert facts.pre_holdout_evidence_complete is False
    # Même séparation si la WF est entièrement absente : tous les PS exploitables, composite incomplet.
    del mapping[c2.gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)]
    facts = c2.evaluate_pre_holdout_evidence_v2(plan, mapping)
    assert facts.parameter_stability_complete_fold_ids == folds
    assert facts.pre_holdout_evidence_complete is False


def test_a_ps_with_an_unusable_neighborhood_stays_incomplete_even_when_the_wf_is_incomplete(worlds):
    plan = worlds.v2_plan
    folds = plan.expected_fold_ids
    roles = _campaign_roles(plan, worlds.split, c2.gate_v_v2_validation_run_id, traded=True)
    roles["wf"] = _folds_edit(lambda items: items[:-1])(roles["wf"])
    roles[f"ps:{folds[-1]}"] = _replace_evidence(n_neighbors_rejected_by_param={"lookback": 1})(roles[f"ps:{folds[-1]}"])
    facts = c2.evaluate_pre_holdout_evidence_v2(plan, _mapping(plan, c2.gate_v_v2_validation_run_id, roles))
    assert facts.parameter_stability_complete_fold_ids == folds[:-1]
    assert facts.parameter_stability_incomplete_fold_ids == (folds[-1],)
    assert facts.pre_holdout_evidence_complete is False


def test_scoped_run_refuses_an_unhashable_reference_with_a_value_error(worlds):
    with pytest.raises(ValueError):
        c2.validate_scoped_evidence_run_v2(worlds.v2_plan, ["not", "hashable"], VALIDATION_TYPE_WALK_FORWARD, {})


def test_public_surface_is_exported_explicitly_and_matches_the_declared_api():
    declared = {
        "gate_v_v2_validation_run_id", "validate_scoped_evidence_run_v2", "walk_forward_evidence_complete_v2",
        "monte_carlo_evidence_complete_v2", "parameter_stability_evidence_complete_v2",
        "GateVPreHoldoutEvidenceFacts", "evaluate_pre_holdout_evidence_v2",
    }
    assert set(c2.__all__) == declared
    namespace = {}
    exec("from gate_v_evidence_completeness_v2 import *", namespace)  # noqa: S102 — surface d'export seulement
    assert {name for name in namespace if not name.startswith("__")} == declared


def test_the_docstring_states_that_the_oos_case_is_out_of_v2_scope_without_a_seventh_divergence():
    docstring = ast.get_docstring(_module_tree())
    assert "Hors périmètre V2" in docstring and "OOS" in docstring.split("Hors périmètre V2", 1)[1]
    assert "(7)" not in docstring


def test_the_mandated_sentence_is_one_greppable_line_and_lists_every_decided_divergence():
    docstring = ast.get_docstring(_module_tree())
    sentence = (
        "V1 intentionally remains frozen. This V2 implementation is independently versioned and protected "
        "by differential tests."
    )
    assert any(sentence in line for line in docstring.splitlines())
    for number in range(1, 7):
        assert f"({number})" in docstring
    assert "six divergences" in docstring
    assert "faits élémentaires" in docstring.split("(6)", 1)[1]


# ============================================================================================
# Tranche 9 — revue finale : champs producteur d'un fold zéro trade, n_win borné, erreurs typées
# ============================================================================================


def _fold_replace_rebuilt(index, **changes):
    """Modifie un fold ET reconstruit l'agrégat avec le producteur : l'attaque réelle (l'agrégat recalculé
    colle alors à des entrées de fold falsifiées, donc le seul recalcul d'agrégat ne suffit pas)."""
    def mutate(run):
        folds = list(run.evidence.fold_results)
        folds[index] = dataclasses.replace(folds[index], **changes)
        folds = tuple(folds)
        return dataclasses.replace(
            run, evidence=dataclasses.replace(run.evidence, fold_results=folds, aggregate=build_aggregate_result(folds)),
        )
    return mutate


_ZERO_TRADE_FOLD = dict(
    n_trades=0, zero_trade_oos=True, net_ret_pct=0, max_dd_pct=None, profit_factor=None, win_rate=None,
    expectancy=None, forced_closes=0, gross_win=0.0, gross_loss=0.0, n_win=0, score_test=0.0,
)

# Divergence V2 n°6 : un fold zéro trade a gross_win == gross_loss == n_win == 0 (producteur
# walk_forward.py:664-666, FoldResult) et tout fold a 0 <= n_win <= n_trades entier ; V1 ne contrôle rien de cela.
_FORGED_FOLD_INPUTS = [
    ("zero_trade_fold_with_gross_win", {**_ZERO_TRADE_FOLD, "gross_win": 9.0}),
    ("zero_trade_fold_with_gross_loss", {**_ZERO_TRADE_FOLD, "gross_loss": 1.0}),
    ("zero_trade_fold_with_winners", {**_ZERO_TRADE_FOLD, "n_win": 3}),
    ("winners_exceed_trades", {"n_win": 6}),
    ("winners_negative", {"n_win": -1}),
    ("winners_is_a_float", {"n_win": 3.0}),
    ("winners_is_a_bool", {"n_win": True}),
]


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("name,changes", _FORGED_FOLD_INPUTS)
def test_v2_diverges_from_v1_by_checking_the_producer_fields_of_zero_trade_and_winner_counts(
    worlds, scratch, name, changes, as_json,
):
    outcomes = _judge(
        worlds, scratch, traded=True, role="wf", mutation=_fold_replace_rebuilt(0, **changes), as_json=as_json,
        v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "ValueError"}, name


def test_a_genuine_mixed_zero_trade_and_traded_walk_forward_stays_complete(worlds, scratch):
    outcomes = _judge(
        worlds, scratch, traded=True, role="wf", mutation=_fold_replace_rebuilt(0, **_ZERO_TRADE_FOLD),
        as_json=False, v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "complete"}


def test_an_unhashable_fold_id_in_a_reloaded_walk_forward_never_leaks_an_untyped_error(worlds, scratch):
    plan = worlds.v2_plan
    roles = _campaign_roles(plan, worlds.split, c2.gate_v_v2_validation_run_id, traded=True)
    wf = _json_variant(roles["wf"], scratch)
    wf.evidence.fold_results[0]["fold_id"] = ["not", "hashable"]
    roles["wf"] = wf
    facts = c2.evaluate_pre_holdout_evidence_v2(plan, _mapping(plan, c2.gate_v_v2_validation_run_id, roles))
    assert facts.walk_forward_complete is False and facts.pre_holdout_evidence_complete is False


def test_zero_candidate_parameter_stability_matches_v1_with_and_without_a_source_fold(worlds, scratch):
    """Cas producteur ``zero_candidates_input`` : aucun best_params, aucun compteur. Sans fold source : preuve
    incomplète ; avec fold source : la comparaison Top-1 échoue (pool différent) — erreur, jamais acceptation."""
    zero_candidates = _replace_evidence(
        zero_candidates_input=True, n_candidates_total=0, best_score=None, best_params=None,
        n_neighbors_total_by_param={}, n_neighbors_rejected_by_param={}, degradation_by_param={},
        degradation_points_by_param={}, sensitivity={}, sensitivity_sample_size_by_param={},
        degradation_hamming_le_2=None, n_hamming_le_2_total=0,
    )
    without = _judge(worlds, scratch, traded=False, role="ps:first", mutation=zero_candidates, as_json=False,
                     v1_call=_ps_v1_without_source, v2_call=_ps_v2_without_source)
    with_source = _judge(worlds, scratch, traded=False, role="ps:first", mutation=zero_candidates, as_json=False,
                         v1_call=_ps_v1, v2_call=_ps_v2)
    assert without == {"v1": "incomplete", "v2": "incomplete"}
    assert with_source == {"v1": "ValueError", "v2": "ValueError"}


# ============================================================================================
# Tranche 10 — invariants numériques de CHAQUE fold WF (le recalcul d'agrégat ne les remplace jamais)
# ============================================================================================

_NON_FINITE = (("nan", float("nan")), ("plus_inf", float("inf")), ("minus_inf", float("-inf")))


def _numeric_fold_forgeries():
    """(nom, changements d'un fold, variantes). L'agrégat est reconstruit par le producteur : il est donc
    auto-cohérent avec le fold falsifié, et seul le contrôle des faits élémentaires peut refuser."""
    cases = []
    for field in ("net_ret_pct", "score_test", "gross_win", "gross_loss"):
        for label, value in _NON_FINITE:
            cases.append((f"{field}_{label}", {field: value}, ("traded", "zero")))
        cases.append((f"{field}_is_a_bool", {field: True}, ("traded", "zero")))
    cases += [
        ("gross_win_negative", {"gross_win": -1.0}, ("traded",)),
        ("gross_loss_negative", {"gross_loss": -1.0}, ("traded",)),
        ("zero_trade_net_ret_is_a_bool_false", {"net_ret_pct": False}, ("zero",)),
    ]
    return cases


def _numeric_fold_cases():
    for name, changes, variants in _numeric_fold_forgeries():
        for variant in variants:
            for as_json in (False, True):
                label = "json" if as_json else "objects"
                yield pytest.param(name, changes, variant == "traded", as_json, id=f"{name}-{variant}-{label}")


@pytest.mark.parametrize("name,changes,traded,as_json", list(_numeric_fold_cases()))
def test_v2_refuses_non_finite_boolean_or_negative_elementary_fold_facts_even_with_a_self_consistent_aggregate(
    worlds, scratch, name, changes, traded, as_json,
):
    """Divergence V2 n°6 (invariants producteur des folds) : V1 ne contrôle aucun de ces faits élémentaires."""
    outcomes = _judge(
        worlds, scratch, traded=traded, role="wf", mutation=_fold_replace_rebuilt(0, **changes), as_json=as_json,
        v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes["v2"] == "ValueError", (name, outcomes)


@pytest.mark.parametrize("name,changes", [
    ("n_win_is_a_bool", {"n_win": True}), ("n_win_is_a_float", {"n_win": 3.0}),
    ("n_win_negative", {"n_win": -1}), ("n_win_above_n_trades", {"n_win": 6}),
])
def test_v2_refuses_an_impossible_winner_count_even_with_a_self_consistent_aggregate(worlds, scratch, name, changes):
    outcomes = _judge(
        worlds, scratch, traded=True, role="wf", mutation=_fold_replace_rebuilt(0, **changes), as_json=False,
        v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "ValueError"}, name


def test_a_legitimate_infinite_profit_factor_stays_complete_and_a_zero_gross_loss_is_valid(worlds, scratch):
    """Cas producteur valide : des trades existent et aucune perte brute n'est observée -> profit factor +inf.
    ``math.isfinite`` n'est donc JAMAIS appliqué à ``oos_profit_factor`` ; ``gross_loss == 0`` reste valide."""
    mutation = _all_folds_without_loss
    plan = worlds.v2_plan
    roles = _campaign_roles(plan, worlds.split, c2.gate_v_v2_validation_run_id, traded=True)
    run = mutation(roles["wf"])
    assert run.evidence.aggregate.oos_profit_factor == float("inf")
    assert all(fold.gross_loss == 0.0 and fold.n_trades > 0 for fold in run.evidence.fold_results)
    for as_json in (False, True):
        outcomes = _judge(
            worlds, scratch, traded=True, role="wf", mutation=mutation, as_json=as_json, v1_call=_wf_v1, v2_call=_wf_v2,
        )
        assert outcomes == {"v1": "complete", "v2": "complete"}


# ============================================================================================
# Tranche 11 — score_test borné [0, 100] et nul sur zéro trade ; erreurs typées (revue post-correction)
# ============================================================================================


@pytest.mark.parametrize("name,changes,traded", [
    ("score_above_100", {"score_test": 100.5}, True),
    ("score_negative", {"score_test": -0.1}, True),
    ("score_astronomical", {"score_test": 1e300}, True),
    ("zero_trade_fold_with_a_score", {**_ZERO_TRADE_FOLD, "score_test": 50.0}, True),
    ("all_zero_trade_folds_with_a_score", {"score_test": 50.0}, False),
])
def test_v2_bounds_score_test_to_the_producer_range_and_pins_it_to_zero_on_a_zero_trade_fold(
    worlds, scratch, name, changes, traded,
):
    """Le producteur borne tout score à [0, 100] (``scoring.compute_score``) et vaut 0.0 sans trade
    (``optimizer.py``) : sinon ``mean_fold_score_test`` / ``worst_fold_id`` de l'agrégat recalculé seraient
    falsifiables par les entrées de fold. Fait partie de la divergence (6)."""
    outcomes = _judge(
        worlds, scratch, traded=traded, role="wf", mutation=_fold_replace_rebuilt(0, **changes), as_json=False,
        v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "ValueError"}, name


@pytest.mark.parametrize("score", [0.0, 0, 37.5, 100.0])
def test_every_producer_score_in_the_legitimate_range_is_accepted(worlds, scratch, score):
    outcomes = _judge(
        worlds, scratch, traded=True, role="wf", mutation=_fold_replace_rebuilt(1, score_test=score),
        as_json=False, v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "complete"}


def test_a_fold_definition_that_is_neither_a_dataclass_nor_a_dict_is_a_value_error_not_a_type_error(worlds, scratch):
    """Divergence (3) : une définition de fold de type inattendu (ici un objet à attributs) est une
    ``ValueError`` de contrat en V2 ; V1 laisse remonter un ``TypeError`` non typé."""
    def as_namespace(run):
        folds = list(run.evidence.fold_results)
        definition = folds[0].definition
        folds[0] = dataclasses.replace(folds[0], definition=SimpleNamespace(**dataclasses.asdict(definition)))
        return dataclasses.replace(run, evidence=dataclasses.replace(run.evidence, fold_results=tuple(folds)))
    outcomes = _judge(
        worlds, scratch, traded=False, role="wf", mutation=as_namespace, as_json=False, v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "TypeError", "v2": "ValueError"}


# ============================================================================================
# Tranche 12 — relations n_win / gross_win / gross_loss / win_rate / profit_factor (engine.py:490-502)
# ============================================================================================

_INF = float("inf")


def _traded_fold(n_win, gross_win, gross_loss, *, n_trades=5, win_rate=None, profit_factor=None):
    """Changements d'un fold avec trades COHÉRENTS avec le producteur : win_rate = n_win / n_trades * 100,
    profit_factor = gross_win / gross_loss si gross_loss > 0 sinon +inf. Un défaut explicite sert à falsifier."""
    derived_win_rate = n_win / n_trades * 100
    derived_profit_factor = gross_win / gross_loss if gross_loss > 0 else _INF
    return dict(
        n_trades=n_trades, zero_trade_oos=False, n_win=n_win, gross_win=gross_win, gross_loss=gross_loss,
        win_rate=derived_win_rate if win_rate is None else win_rate,
        profit_factor=derived_profit_factor if profit_factor is None else profit_factor,
    )


# Combinaisons IMPOSSIBLES selon engine.py : V1 les accepte, V2 les refuse (divergence 6).
_IMPOSSIBLE_WIN_LOSS_COMBINATIONS = [
    ("all_winners_but_no_gross_win", _traded_fold(5, 0.0, 0.0)),
    ("no_winner_but_gross_win", _traded_fold(0, 10.0, 5.0)),
    ("all_winners_but_gross_loss", _traded_fold(5, 10.0, 2.0)),
    ("some_winners_but_no_gross_win", _traded_fold(3, 0.0, 4.0)),
]


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("name,changes", _IMPOSSIBLE_WIN_LOSS_COMBINATIONS)
def test_v2_refuses_win_and_loss_combinations_impossible_for_the_engine_even_with_a_self_consistent_aggregate(
    worlds, scratch, name, changes, as_json,
):
    outcomes = _judge(
        worlds, scratch, traded=True, role="wf", mutation=_fold_replace_rebuilt(0, **changes), as_json=as_json,
        v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "ValueError"}, name


# Combinaisons LÉGITIMES : doivent rester complètes (V1 et V2).
_LEGITIMATE_WIN_LOSS_COMBINATIONS = [
    ("mixed_winners_and_losers", _traded_fold(3, 6.0, 4.0)),
    # Un trade à résultat exactement nul est classé « perte » (resultat_net <= 0) sans changer gross_loss :
    # gross_loss == 0 n'implique PAS n_win == n_trades.
    ("breakeven_trades_with_winners_and_no_gross_loss", _traded_fold(3, 6.0, 0.0)),
    ("all_trades_breakeven", _traded_fold(0, 0.0, 0.0)),
    ("all_winners", _traded_fold(5, 10.0, 0.0)),
    ("profit_factor_zero_when_no_gross_win", _traded_fold(0, 0.0, 4.0)),
]


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("name,changes", _LEGITIMATE_WIN_LOSS_COMBINATIONS)
def test_legitimate_win_loss_combinations_including_breakeven_and_infinite_profit_factor_stay_complete(
    worlds, scratch, name, changes, as_json,
):
    outcomes = _judge(
        worlds, scratch, traded=True, role="wf", mutation=_fold_replace_rebuilt(0, **changes), as_json=as_json,
        v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "complete"}, name


def test_the_all_breakeven_and_all_winner_folds_really_carry_a_canonical_infinite_profit_factor():
    assert _traded_fold(0, 0.0, 0.0)["profit_factor"] == _INF
    assert _traded_fold(5, 10.0, 0.0)["profit_factor"] == _INF
    assert _traded_fold(3, 6.0, 0.0)["profit_factor"] == _INF
    assert _traded_fold(0, 0.0, 4.0)["profit_factor"] == 0.0


# win_rate / profit_factor d'un fold avec trades sont DÉRIVABLES des faits du FoldResult : toute valeur
# incohérente, booléenne, NaN ou absente est refusée (V1 ne les contrôle pas).
_FORGED_DERIVED_METRICS = [
    ("win_rate_inflated", _traded_fold(3, 6.0, 4.0, win_rate=99.0)),
    ("win_rate_is_nan", _traded_fold(3, 6.0, 4.0, win_rate=float("nan"))),
    ("win_rate_is_a_bool", _traded_fold(3, 6.0, 4.0, win_rate=True)),
    ("win_rate_is_a_ratio_not_a_percentage", _traded_fold(3, 6.0, 4.0, win_rate=0.6)),
    ("win_rate_missing", {**_traded_fold(3, 6.0, 4.0), "win_rate": None}),
    ("profit_factor_inflated", _traded_fold(3, 6.0, 4.0, profit_factor=9.9)),
    ("profit_factor_is_nan", _traded_fold(3, 6.0, 4.0, profit_factor=float("nan"))),
    ("profit_factor_is_a_bool", _traded_fold(3, 6.0, 4.0, profit_factor=True)),
    ("profit_factor_missing", {**_traded_fold(3, 6.0, 4.0), "profit_factor": None}),
    ("profit_factor_minus_inf", _traded_fold(3, 6.0, 4.0, profit_factor=-_INF)),
    ("profit_factor_infinite_while_a_gross_loss_exists", _traded_fold(3, 6.0, 4.0, profit_factor=_INF)),
    ("profit_factor_finite_while_there_is_no_gross_loss", _traded_fold(3, 6.0, 0.0, profit_factor=5.0)),
    # Un booléen vaut 0/1 : il ne doit JAMAIS passer même lorsqu'il est égal à la valeur dérivée attendue.
    ("win_rate_false_equal_to_a_zero_percent_win_rate", _traded_fold(0, 0.0, 4.0, win_rate=False)),
    ("win_rate_true_equal_to_a_one_percent_win_rate", _traded_fold(1, 6.0, 4.0, n_trades=100, win_rate=True)),
    ("profit_factor_true_equal_to_a_unit_profit_factor", _traded_fold(3, 4.0, 4.0, profit_factor=True)),
    ("profit_factor_false_equal_to_a_zero_profit_factor", _traded_fold(0, 0.0, 4.0, profit_factor=False)),
]


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("name,changes", _FORGED_DERIVED_METRICS)
def test_v2_refuses_an_inconsistent_win_rate_or_profit_factor_derived_from_the_fold_facts(
    worlds, scratch, name, changes, as_json,
):
    outcomes = _judge(
        worlds, scratch, traded=True, role="wf", mutation=_fold_replace_rebuilt(0, **changes), as_json=as_json,
        v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "complete", "v2": "ValueError"}, name


@pytest.mark.parametrize("name,changes", [
    ("zero_trade_win_rate_set", {**_ZERO_TRADE_FOLD, "win_rate": 0.0}),
    ("zero_trade_profit_factor_set", {**_ZERO_TRADE_FOLD, "profit_factor": _INF}),
])
def test_zero_trade_folds_keep_their_none_win_rate_and_profit_factor_contract(worlds, scratch, name, changes):
    outcomes = _judge(
        worlds, scratch, traded=True, role="wf", mutation=_fold_replace_rebuilt(0, **changes), as_json=False,
        v1_call=_wf_v1, v2_call=_wf_v2,
    )
    assert outcomes == {"v1": "ValueError", "v2": "ValueError"}, name
