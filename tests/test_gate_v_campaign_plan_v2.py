"""
tests/test_gate_v_campaign_plan_v2.py — AF-V-07 Slice C : GateVCampaignPlanV2.

Contrat normatif : ADR 0025 Décision 20 (20.1-20.10). Plan de campagne V2, distinct du plan V1
(`gate_v_campaign.GateVCampaignPlan`), lié à une `GateVPreRegistration` validée, sans aucune
evidence WF/MC/PS/OOS/FINAL_HOLDOUT et sans horodatage.

Aucun accès FINAL_HOLDOUT, aucune campagne réelle, aucune donnée marché — synthétique uniquement.
Les tests Git utilisent un dépôt temporaire local hermétique (aucun réseau).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json as _json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass as _dataclass

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_split import build_dataset_split_plan, build_split_boundary, dataset_split_plan_fingerprint
from gate_v_campaign_plan_v2 import (
    GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION,
    GateVCampaignPlanV2,
    compute_gate_v_campaign_id_v2,
)
from gate_v_preregistration import (
    GitProvenanceError,
    build_gate_v_preregistration,
    compute_campaign_protocol_fingerprint,
    compute_fold_geometry,
    compute_preregistration_content_hash,
    compute_preregistration_id,
    research_run_content_hash,
)
from gate_v_validation_policy import (
    OosPolicyCriterion,
    WalkForwardPolicyCriterion,
    build_gate_v_validation_policy,
    policy_content_hash as compute_policy_content_hash,
    save_gate_v_validation_policy,
)
from research_run import build_research_run
from strategy_contracts import DailyStateReadiness
from validation_run import MONTE_CARLO_SEMANTICS_VERSION, PARAMETER_STABILITY_SEMANTICS_VERSION
from walk_forward import build_walk_forward_specification

_EXPECTED_FIELDS = (
    "campaign_plan_semantics_version",
    "campaign_id",
    "preregistration_id",
    "preregistration_content_hash",
    "campaign_protocol_fingerprint",
    "research_run_id",
    "research_run_content_hash",
    "dataset_snapshot_id",
    "split_plan_id",
    "split_plan_fingerprint",
    "strategy_name",
    "base_params",
    "search_mode",
    "search_space_hash",
    "budget_per_fold",
    "walk_forward_specification",
    "readiness_spec",
    "expected_fold_ids",
    "expected_fold_definitions_hash",
    "validation_zone_hash",
    "walk_forward_spec_semantics_version",
    "monte_carlo_semantics_version",
    "parameter_stability_semantics_version",
    "gate_v_validation_policy_id",
    "policy_content_hash",
    "assessment_semantics_version",
    "policy_git_sha",
)


# -- Contrat structurel (Décision 20.4) --------------------------------------------------


def test_semantics_version_constant_exact_value():
    assert GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION == "gate_v_campaign_plan_v2"


def test_plan_v2_has_exactly_the_27_normative_fields_in_order():
    names = tuple(f.name for f in dataclasses.fields(GateVCampaignPlanV2))
    assert len(names) == 27
    assert names == _EXPECTED_FIELDS


def test_plan_v2_has_no_created_at_or_any_timestamp_field():
    names = {f.name for f in dataclasses.fields(GateVCampaignPlanV2)}
    assert "created_at" not in names
    assert not any("time" in n or n.endswith("_at") for n in names)


def test_plan_v2_structurally_excludes_oos_evidence_fields():
    names = {f.name for f in dataclasses.fields(GateVCampaignPlanV2)}
    assert names.isdisjoint({
        "oos_evidence_validation_run_id", "oos_evidence_hash", "oos_evidence_path",
    })
    assert not any(n.startswith("oos_evidence") for n in names)


def test_plan_v2_carries_no_scientific_result_or_runtime_path_field():
    names = {f.name for f in dataclasses.fields(GateVCampaignPlanV2)}
    forbidden_fragments = ("evidence", "verdict", "result", "holdout", "path", "aggregate")
    assert not [n for n in names if any(fragment in n for fragment in forbidden_fragments)]


def test_plan_v2_is_a_distinct_type_from_v1_plan():
    import gate_v_campaign

    assert GateVCampaignPlanV2 is not gate_v_campaign.GateVCampaignPlan
    assert not issubclass(GateVCampaignPlanV2, gate_v_campaign.GateVCampaignPlan)
    assert not issubclass(gate_v_campaign.GateVCampaignPlan, GateVCampaignPlanV2)
    v1_names = {f.name for f in dataclasses.fields(gate_v_campaign.GateVCampaignPlan)}
    v2_names = {f.name for f in dataclasses.fields(GateVCampaignPlanV2)}
    assert "policy_git_sha" in v2_names - v1_names


# -- campaign_id V2 : fonction pure canonique (Décision 20.3) ------------------------------

_PID = "a" * 64
_FP = "b" * 64


def test_campaign_id_v2_matches_independent_known_vector():
    # Vecteur calculé HORS du code testé : SHA256 du JSON canonique écrit à la main
    # (clés triées, séparateurs compacts).
    manual = (
        '{"campaign_plan_semantics_version":"gate_v_campaign_plan_v2",'
        '"campaign_protocol_fingerprint":"' + _FP + '",'
        '"preregistration_id":"' + _PID + '"}'
    )
    expected = "gate_v_v2_" + hashlib.sha256(manual.encode("utf-8")).hexdigest()
    assert expected == "gate_v_v2_d825bcd4cfeaa4a1199c48d21fafd5f68936ce7c0ede5b5322c9440a8196ad07"
    assert compute_gate_v_campaign_id_v2(
        campaign_plan_semantics_version="gate_v_campaign_plan_v2",
        preregistration_id=_PID,
        campaign_protocol_fingerprint=_FP,
    ) == expected


def test_campaign_id_v2_uses_ensure_ascii_false_utf8():
    # ensure_ascii=False : les non-ASCII sont hachés en UTF-8 brut, pas échappés en \uXXXX.
    got = compute_gate_v_campaign_id_v2(
        campaign_plan_semantics_version="gate_v_campaign_plan_v2",
        preregistration_id="é" * 3,
        campaign_protocol_fingerprint=_FP,
    )
    assert got == "gate_v_v2_d3dd580349867ea18b3e431813fae08e9ccce25d26726d15b314905ada5b4e7b"


def test_campaign_id_v2_is_deterministic_and_prefixed():
    kwargs = dict(
        campaign_plan_semantics_version="gate_v_campaign_plan_v2",
        preregistration_id=_PID, campaign_protocol_fingerprint=_FP,
    )
    first = compute_gate_v_campaign_id_v2(**kwargs)
    assert first == compute_gate_v_campaign_id_v2(**kwargs)
    assert re.fullmatch(r"gate_v_v2_[0-9a-f]{64}", first)


def test_campaign_id_v2_depends_on_preregistration_id_and_fingerprint():
    base = dict(
        campaign_plan_semantics_version="gate_v_campaign_plan_v2",
        preregistration_id=_PID, campaign_protocol_fingerprint=_FP,
    )
    reference = compute_gate_v_campaign_id_v2(**base)
    assert compute_gate_v_campaign_id_v2(**{**base, "preregistration_id": "c" * 64}) != reference
    assert compute_gate_v_campaign_id_v2(**{**base, "campaign_protocol_fingerprint": "c" * 64}) != reference


def test_campaign_id_v2_rejects_unknown_semantics_version():
    for bad in ("gate_v_campaign_plan_v3", "", "gate_v_campaign_plan_v1", None):
        with pytest.raises(ValueError):
            compute_gate_v_campaign_id_v2(
                campaign_plan_semantics_version=bad,
                preregistration_id=_PID, campaign_protocol_fingerprint=_FP,
            )


def test_campaign_id_v2_rejects_empty_or_non_string_inputs():
    for pid, fp in (("", _FP), (_PID, ""), (None, _FP), (_PID, None), (1, _FP)):
        with pytest.raises(ValueError):
            compute_gate_v_campaign_id_v2(
                campaign_plan_semantics_version="gate_v_campaign_plan_v2",
                preregistration_id=pid, campaign_protocol_fingerprint=fp,
            )


def test_campaign_id_v2_namespace_never_matches_v1_shape():
    v2 = compute_gate_v_campaign_id_v2(
        campaign_plan_semantics_version="gate_v_campaign_plan_v2",
        preregistration_id=_PID, campaign_protocol_fingerprint=_FP,
    )
    # V1 = "gate_v_" + 64 hex ; V2 = "gate_v_v2_" + 64 hex : jamais confondables.
    assert re.fullmatch(r"gate_v_[0-9a-f]{64}", v2) is None


def test_canonical_json_matches_slice_b_canonicalisation():
    """Garde anti-dérive : la canonicalisation V2 locale == celle de Slice B (`_canonical_json`)."""
    import gate_v_campaign_plan_v2 as plan_module
    import gate_v_preregistration as prereg_module

    sample = {"b": [1, 2.5, "é"], "a": {"z": None, "y": True}}
    assert plan_module._canonical_json(sample) == prereg_module._canonical_json(sample)
    with pytest.raises(ValueError):
        plan_module._canonical_json({"x": float("nan")})


# ============================================================================================
# Fixtures : dépôt Git temporaire réel + PreRegistration réelle (Slice B) + sources réelles
# ============================================================================================

_SNAPSHOT_ID = "local_csv:sha256:" + "ab" * 32
_ASSESSMENT_SEMANTICS_VERSION = "gate_v_assessment_v1"


def _run_git(args, cwd):
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout


def _init_git_repo(tmp_path):
    repo_dir = tmp_path / f"repo_{uuid.uuid4().hex[:8]}"
    repo_dir.mkdir(parents=True)
    _run_git(["init"], repo_dir)
    _run_git(["config", "user.email", "test@example.com"], repo_dir)
    _run_git(["config", "user.name", "Test"], repo_dir)
    return repo_dir


def _policy(policy_id="pol_test", threshold=0.0):
    return build_gate_v_validation_policy(
        policy_id,
        {
            "oos": (OosPolicyCriterion(metric="net_ret_pct", operator=">", threshold=threshold),),
            "walk_forward": (
                WalkForwardPolicyCriterion(metric="oos_net_return_pct", operator=">", threshold=0.0),
            ),
        },
    )


def _commit_policy(tmp_path, policy_id="pol_test"):
    repo_dir = _init_git_repo(tmp_path)
    policies_dir = repo_dir / "validation_policies"
    policies_dir.mkdir()
    policy_path = policies_dir / f"{policy_id}.json"
    policy = _policy(policy_id)
    save_gate_v_validation_policy(policy_path, policy)
    _run_git(["add", "validation_policies"], repo_dir)
    _run_git(["commit", "-m", f"add policy {uuid.uuid4().hex}"], repo_dir)
    sha = _run_git(["rev-parse", "HEAD"], repo_dir).strip()
    return repo_dir, policy_path, sha, policy


def _commit_unrelated(repo_dir, content=None):
    (repo_dir / "README.md").write_text(content or uuid.uuid4().hex, encoding="utf-8")
    _run_git(["add", "README.md"], repo_dir)
    _run_git(["commit", "-m", f"unrelated {uuid.uuid4().hex}"], repo_dir)
    return _run_git(["rev-parse", "HEAD"], repo_dir).strip()


def _research_run(**kwargs):
    kwargs.setdefault("research_run_id", "run_x")
    kwargs.setdefault("experiment_id", "exp_x")
    kwargs.setdefault("dataset_snapshot_id", _SNAPSHOT_ID)
    kwargs.setdefault("git_sha", None)
    return build_research_run(**kwargs)


def _split_plan(**kwargs):
    kwargs.setdefault("split_plan_id", "plan_x")
    kwargs.setdefault("dataset_snapshot_id", _SNAPSHOT_ID)
    kwargs.setdefault("train", build_split_boundary("2020-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00"))
    kwargs.setdefault("final_holdout", build_split_boundary("2024-06-01T00:00:00+00:00", "2024-09-01T00:00:00+00:00"))
    kwargs.setdefault("validation", build_split_boundary("2024-01-01T00:00:00+00:00", "2024-06-01T00:00:00+00:00"))
    return build_dataset_split_plan(**kwargs)


def _wf_spec(**kwargs):
    kwargs.setdefault("base_params", {"n_neighbors": 5})
    kwargs.setdefault("geometry", "rolling")
    kwargs.setdefault("train_period", "P1M")
    kwargs.setdefault("test_period", "P1M")
    kwargs.setdefault("step_period", "P1M")
    return build_walk_forward_specification(**kwargs)


@_dataclass
class _World:
    repo_dir: object
    policy_path: object
    policy_sha: str
    policy: object
    research_run: object
    split_plan: object
    protocol: dict
    prereg: object


def _world(tmp_path, readiness_spec=None, **protocol_overrides):
    """PreRegistration RÉELLE créée à HEAD == policy_git_sha (règle de création de Slice B)."""
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    research_run, split_plan = _research_run(), _split_plan()
    protocol = dict(
        strategy_name="perfect_revolution_v1", base_params={"n_neighbors": 5}, search_mode="single_var",
        search_space_hash="a" * 12, budget_per_fold=10, walk_forward_specification=_wf_spec(),
        readiness_spec=readiness_spec,
    )
    protocol.update(protocol_overrides)
    prereg = build_gate_v_preregistration(
        research_run=research_run, split_plan=split_plan, policy=policy, policy_path=policy_path,
        assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION, repo_dir=repo_dir, **protocol,
    )
    return _World(repo_dir, policy_path, sha, policy, research_run, split_plan, protocol, prereg)


def _build(world, **overrides):
    from gate_v_campaign_plan_v2 import build_gate_v_campaign_plan_v2

    kwargs = dict(
        preregistration=world.prereg, research_run=world.research_run, split_plan=world.split_plan,
        policy=world.policy, policy_path=world.policy_path, repo_dir=world.repo_dir,
        **{k: v for k, v in world.protocol.items()},
    )
    kwargs.update(overrides)
    return build_gate_v_campaign_plan_v2(**kwargs)


def _validate_sources(world, plan, **overrides):
    from gate_v_campaign_plan_v2 import validate_gate_v_campaign_plan_v2_sources

    kwargs = dict(
        preregistration=world.prereg, research_run=world.research_run, split_plan=world.split_plan,
        policy=world.policy, policy_path=world.policy_path, repo_dir=world.repo_dir,
    )
    kwargs.update(overrides)
    return validate_gate_v_campaign_plan_v2_sources(plan, **kwargs)


def _prereg_kwargs(pre):
    return dict(
        scope_key=pre.scope_key, campaign_protocol_fingerprint=pre.campaign_protocol_fingerprint,
        research_run_id=pre.research_run_id, research_run_content_hash=pre.research_run_content_hash,
        dataset_snapshot_id=pre.dataset_snapshot_id, split_plan_id=pre.split_plan_id,
        strategy_name=pre.strategy_name, gate_v_validation_policy_id=pre.gate_v_validation_policy_id,
        policy_content_hash=pre.policy_content_hash, policy_git_sha=pre.policy_git_sha,
        assessment_semantics_version=pre.assessment_semantics_version,
        preregistration_semantics_version=pre.preregistration_semantics_version,
    )


def _forge_preregistration(pre, **changes):
    """PreRegistration AUTO-COHÉRENTE (id/hash recalculés honnêtement) mais aux champs modifiés —
    modélise un attaquant qui recalcule l'identité de la PreRegistration."""
    fields = {**_prereg_kwargs(pre), **changes}
    pid = compute_preregistration_id(**fields)
    chash = compute_preregistration_content_hash(preregistration_id=pid, **fields)
    return dataclasses.replace(
        pre, **{k: v for k, v in changes.items()},
        preregistration_id=pid, preregistration_content_hash=chash,
    )


def _plan_fingerprint(plan):
    return compute_campaign_protocol_fingerprint(
        research_run_id=plan.research_run_id, research_run_content_hash=plan.research_run_content_hash,
        dataset_snapshot_id=plan.dataset_snapshot_id, split_plan_id=plan.split_plan_id,
        split_plan_fingerprint=plan.split_plan_fingerprint, strategy_name=plan.strategy_name,
        base_params=plan.base_params, search_mode=plan.search_mode,
        search_space_hash=plan.search_space_hash, budget_per_fold=plan.budget_per_fold,
        walk_forward_specification=plan.walk_forward_specification, readiness_spec=plan.readiness_spec,
        expected_fold_ids=plan.expected_fold_ids,
        expected_fold_definitions_hash=plan.expected_fold_definitions_hash,
        validation_zone_hash=plan.validation_zone_hash,
        walk_forward_spec_semantics_version=plan.walk_forward_spec_semantics_version,
        monte_carlo_semantics_version=plan.monte_carlo_semantics_version,
        parameter_stability_semantics_version=plan.parameter_stability_semantics_version,
        gate_v_validation_policy_id=plan.gate_v_validation_policy_id,
        policy_content_hash=plan.policy_content_hash,
        assessment_semantics_version=plan.assessment_semantics_version,
    )


def _forge_plan(plan, **changes):
    """Plan AUTO-COHÉRENT (fingerprint ET campaign_id recalculés honnêtement) mais modifié —
    modélise la limite acceptée de la Décision 20.6 : indétectable en interne, détectable aux sources."""
    forged = dataclasses.replace(plan, **changes)
    fingerprint = _plan_fingerprint(forged)
    forged = dataclasses.replace(forged, campaign_protocol_fingerprint=fingerprint)
    campaign_id = compute_gate_v_campaign_id_v2(
        campaign_plan_semantics_version=forged.campaign_plan_semantics_version,
        preregistration_id=forged.preregistration_id, campaign_protocol_fingerprint=fingerprint,
    )
    return dataclasses.replace(forged, campaign_id=campaign_id)


# -- Builder nominal (Décision 20.2/20.3/20.10) ---------------------------------------------


def test_builder_nominal_builds_a_plan_bound_to_the_preregistration(tmp_path):
    world = _world(tmp_path)
    plan = _build(world)
    pre = world.prereg
    assert isinstance(plan, GateVCampaignPlanV2)
    assert plan.campaign_plan_semantics_version == "gate_v_campaign_plan_v2"
    assert plan.preregistration_id == pre.preregistration_id
    assert plan.preregistration_content_hash == pre.preregistration_content_hash
    assert plan.campaign_protocol_fingerprint == pre.campaign_protocol_fingerprint
    assert plan.research_run_id == pre.research_run_id == "run_x"
    assert plan.research_run_content_hash == pre.research_run_content_hash
    assert plan.dataset_snapshot_id == pre.dataset_snapshot_id
    assert plan.split_plan_id == pre.split_plan_id == "plan_x"
    assert plan.split_plan_fingerprint == dataset_split_plan_fingerprint(world.split_plan)
    assert plan.strategy_name == "perfect_revolution_v1"
    assert plan.gate_v_validation_policy_id == pre.gate_v_validation_policy_id
    assert plan.policy_content_hash == pre.policy_content_hash == compute_policy_content_hash(world.policy)
    assert plan.policy_git_sha == pre.policy_git_sha == world.policy_sha
    assert plan.assessment_semantics_version == _ASSESSMENT_SEMANTICS_VERSION
    assert plan.monte_carlo_semantics_version == MONTE_CARLO_SEMANTICS_VERSION
    assert plan.parameter_stability_semantics_version == PARAMETER_STABILITY_SEMANTICS_VERSION
    assert plan.walk_forward_spec_semantics_version == plan.walk_forward_specification.walk_forward_semantics_version


def test_builder_campaign_id_follows_the_v2_formula_on_validated_inputs(tmp_path):
    world = _world(tmp_path)
    plan = _build(world)
    assert plan.campaign_id == compute_gate_v_campaign_id_v2(
        campaign_plan_semantics_version="gate_v_campaign_plan_v2",
        preregistration_id=world.prereg.preregistration_id,
        campaign_protocol_fingerprint=world.prereg.campaign_protocol_fingerprint,
    )
    assert re.fullmatch(r"gate_v_v2_[0-9a-f]{64}", plan.campaign_id)


def test_builder_recomputes_fold_geometry_from_real_structures(tmp_path):
    world = _world(tmp_path, readiness_spec=DailyStateReadiness(latest_safe_start_hour=9, latest_safe_start_minute=30))
    plan = _build(world)
    fold_ids, definitions_hash, zone_hash = compute_fold_geometry(
        world.split_plan, world.protocol["walk_forward_specification"], world.protocol["readiness_spec"],
    )
    assert plan.expected_fold_ids == fold_ids
    assert plan.expected_fold_definitions_hash == definitions_hash
    assert plan.validation_zone_hash == zone_hash
    assert plan.readiness_spec == DailyStateReadiness(latest_safe_start_hour=9, latest_safe_start_minute=30)


def test_builder_is_deterministic_for_identical_sources(tmp_path):
    world = _world(tmp_path)
    first, second = _build(world), _build(world)
    assert first == second
    assert first.campaign_id == second.campaign_id


def test_builder_after_head_advanced_uses_historical_provenance_not_head(tmp_path):
    """Frontière Décision 20.10 : le plan est construit APRÈS la PreRegistration ; HEAD a avancé.
    Le builder ne doit JAMAIS exiger HEAD == preregistration.policy_git_sha."""
    world = _world(tmp_path)
    head_after = _commit_unrelated(world.repo_dir)
    assert head_after != world.policy_sha
    assert _run_git(["rev-parse", "HEAD"], world.repo_dir).strip() == head_after
    plan = _build(world)
    assert plan.policy_git_sha == world.policy_sha != head_after


def test_builder_uses_committed_blob_not_working_tree_policy(tmp_path):
    world = _world(tmp_path)
    _commit_unrelated(world.repo_dir)
    world.policy_path.write_text('{"validation_policy_id": "pol_test", "scientific_criteria": {}}', encoding="utf-8")
    _build(world)  # working tree falsifié : le blob historique reste la source de vérité
    world.policy_path.unlink()
    _build(world)  # working tree supprimé : idem


def test_builder_is_independent_of_process_cwd(tmp_path):
    world = _world(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    original_cwd = os.getcwd()
    os.chdir(elsewhere)
    try:
        assert _build(world).campaign_id
    finally:
        os.chdir(original_cwd)


# -- Barrière 1 : protocole recalculé depuis les vraies sources (Décision 20.10 c) -------------


def test_barrier_1_refuses_modified_base_params(tmp_path):
    world = _world(tmp_path)
    with pytest.raises(ValueError):
        _build(world, base_params={"n_neighbors": 6}, walk_forward_specification=_wf_spec(base_params={"n_neighbors": 6}))


def test_barrier_1_refuses_modified_seed(tmp_path):
    world = _world(tmp_path)
    with pytest.raises(ValueError):
        _build(world, walk_forward_specification=_wf_spec(master_seed=123))


def test_barrier_1_refuses_modified_readiness(tmp_path):
    world = _world(tmp_path)
    with pytest.raises(ValueError):
        _build(world, readiness_spec=DailyStateReadiness(latest_safe_start_hour=9, latest_safe_start_minute=30))


def test_barrier_1_refuses_modified_search_space_hash_search_mode_and_budget(tmp_path):
    world = _world(tmp_path)
    for override in ({"search_space_hash": "b" * 12}, {"search_mode": "grid"}, {"budget_per_fold": 11}):
        with pytest.raises(ValueError):
            _build(world, **override)


def test_barrier_1_refuses_modified_strategy_name(tmp_path):
    world = _world(tmp_path)
    with pytest.raises(ValueError):
        _build(world, strategy_name="another_strategy")


def test_barrier_1_refuses_modified_fold_geometry(tmp_path):
    world = _world(tmp_path)
    for spec in (
        _wf_spec(train_period="P2M"),
        _wf_spec(test_period="P2M", step_period="P2M"),
    ):
        with pytest.raises(ValueError):
            _build(world, walk_forward_specification=spec)


def test_barrier_1_refuses_modified_split_boundaries_same_split_plan_id(tmp_path):
    world = _world(tmp_path)
    other_split = _split_plan(
        validation=build_split_boundary("2024-01-01T00:00:00+00:00", "2024-05-01T00:00:00+00:00"),
    )
    assert other_split.split_plan_id == world.split_plan.split_plan_id
    with pytest.raises(ValueError):
        _build(world, split_plan=other_split)


def test_barrier_1_refuses_modified_policy_same_id_different_content(tmp_path):
    world = _world(tmp_path)
    other_policy = _policy("pol_test", threshold=1.0)
    assert other_policy.validation_policy_id == world.policy.validation_policy_id
    with pytest.raises(ValueError):
        _build(world, policy=other_policy)


def test_builder_refuses_policy_with_other_id(tmp_path):
    world = _world(tmp_path)
    with pytest.raises(ValueError):
        _build(world, policy=_policy("other_policy"))


# -- Cross-check avec la PreRegistration (Décision 20.10, mission §13) ------------------------


def test_builder_refuses_research_run_with_other_id(tmp_path):
    world = _world(tmp_path)
    with pytest.raises(ValueError):
        _build(world, research_run=_research_run(research_run_id="run_other"))


def test_builder_refuses_research_run_same_id_different_content(tmp_path):
    world = _world(tmp_path)
    same_id_other_content = _research_run(experiment_id="exp_other")
    assert same_id_other_content.research_run_id == world.research_run.research_run_id
    assert research_run_content_hash(same_id_other_content) != world.prereg.research_run_content_hash
    with pytest.raises(ValueError):
        _build(world, research_run=same_id_other_content)


def test_builder_refuses_split_plan_with_other_id(tmp_path):
    world = _world(tmp_path)
    with pytest.raises(ValueError):
        _build(world, split_plan=_split_plan(split_plan_id="plan_other"))


def test_builder_refuses_dataset_snapshot_mismatch_between_run_and_split(tmp_path):
    world = _world(tmp_path)
    other_snapshot = "local_csv:sha256:" + "cd" * 32
    with pytest.raises(ValueError):
        _build(world, research_run=_research_run(dataset_snapshot_id=other_snapshot))


def test_builder_refuses_split_plan_without_validation_zone(tmp_path):
    world = _world(tmp_path)
    no_validation = build_dataset_split_plan(
        split_plan_id="plan_x", dataset_snapshot_id=_SNAPSHOT_ID,
        train=build_split_boundary("2020-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00"),
        final_holdout=build_split_boundary("2024-06-01T00:00:00+00:00", "2024-09-01T00:00:00+00:00"),
    )
    with pytest.raises(ValueError):
        _build(world, split_plan=no_validation)


def test_builder_refuses_tampered_preregistration_fields(tmp_path):
    """Un PreRegistration falsifié en mémoire (id/hash/scope/fingerprint/champs) est refusé par
    recalcul de son intégrité, jamais accepté comme vérité."""
    world = _world(tmp_path)
    pre = world.prereg
    tampers = {
        "preregistration_id": "0" * 64,
        "preregistration_content_hash": "0" * 64,
        "scope_key": "0" * 64,
        "campaign_protocol_fingerprint": "0" * 64,
        "research_run_content_hash": "0" * 64,
        "policy_content_hash": "0" * 64,
        "policy_git_sha": "1" * 40,
        "strategy_name": "x",
        "assessment_semantics_version": "gate_v_assessment_v999",
        "preregistration_semantics_version": "gate_v_preregistration_v999",
    }
    for field_name, value in tampers.items():
        with pytest.raises(ValueError):
            _build(world, preregistration=dataclasses.replace(pre, **{field_name: value}))


def test_builder_refuses_non_preregistration_object(tmp_path):
    world = _world(tmp_path)
    for bad in (None, {}, "prereg", dataclasses.asdict(world.prereg)):
        with pytest.raises(ValueError):
            _build(world, preregistration=bad)


# -- policy_git_sha : provenance historique fail-closed au niveau du builder -------------------


def test_builder_refuses_preregistration_pinning_nonexistent_commit(tmp_path):
    world = _world(tmp_path)
    forged = _forge_preregistration(world.prereg, policy_git_sha="0" * 40)
    with pytest.raises(GitProvenanceError):
        _build(world, preregistration=forged)


def test_builder_refuses_preregistration_pinning_short_sha(tmp_path):
    """Slice B accepte un SHA court à la création ; le Plan V2 exige un identifiant complet."""
    world = _world(tmp_path)
    forged = _forge_preregistration(world.prereg, policy_git_sha=world.policy_sha[:12])
    with pytest.raises(GitProvenanceError):
        _build(world, preregistration=forged)


def test_builder_refuses_preregistration_pinning_symbolic_ref(tmp_path):
    world = _world(tmp_path)
    forged = _forge_preregistration(world.prereg, policy_git_sha="HEAD")
    with pytest.raises(GitProvenanceError):
        _build(world, preregistration=forged)


def test_builder_refuses_when_committed_blob_differs_from_pinned_policy_hash(tmp_path):
    """Commit C modifie le fichier de policy ; la PreRegistration forgée pointe vers C avec le hash
    de la policy d'origine : le blob à C ne correspond pas — refusé."""
    world = _world(tmp_path)
    world.policy_path.write_text(
        '{"validation_policy_id": "pol_test", "scientific_criteria": {"oos": [], "walk_forward": []}}',
        encoding="utf-8",
    )
    _run_git(["add", "validation_policies"], world.repo_dir)
    _run_git(["commit", "-m", f"change policy {uuid.uuid4().hex}"], world.repo_dir)
    sha_c = _run_git(["rev-parse", "HEAD"], world.repo_dir).strip()
    forged = _forge_preregistration(world.prereg, policy_git_sha=sha_c)
    with pytest.raises(GitProvenanceError):
        _build(world, preregistration=forged)


def test_builder_refuses_preregistration_pinning_commit_where_blob_is_absent(tmp_path):
    repo_dir = _init_git_repo(tmp_path)
    sha_before = _commit_unrelated(repo_dir)
    policies_dir = repo_dir / "validation_policies"
    policies_dir.mkdir()
    policy_path = policies_dir / "pol_test.json"
    policy = _policy("pol_test")
    save_gate_v_validation_policy(policy_path, policy)
    _run_git(["add", "validation_policies"], repo_dir)
    _run_git(["commit", "-m", f"add policy {uuid.uuid4().hex}"], repo_dir)
    sha_a = _run_git(["rev-parse", "HEAD"], repo_dir).strip()
    research_run, split_plan = _research_run(), _split_plan()
    protocol = dict(
        strategy_name="perfect_revolution_v1", base_params={"n_neighbors": 5}, search_mode="single_var",
        search_space_hash="a" * 12, budget_per_fold=10, walk_forward_specification=_wf_spec(), readiness_spec=None,
    )
    pre = build_gate_v_preregistration(
        research_run=research_run, split_plan=split_plan, policy=policy, policy_path=policy_path,
        assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION, repo_dir=repo_dir, **protocol,
    )
    world = _World(repo_dir, policy_path, sha_a, policy, research_run, split_plan, protocol, pre)
    forged = _forge_preregistration(pre, policy_git_sha=sha_before)
    with pytest.raises(GitProvenanceError):
        _build(world, preregistration=forged)


# -- Validation cross-sources explicite (Décision 20.10 b/c, mission §26) -----------------------


def test_cross_source_validation_accepts_a_faithful_plan_even_after_head_advanced(tmp_path):
    world = _world(tmp_path)
    plan = _build(world)
    _commit_unrelated(world.repo_dir)
    _validate_sources(world, plan)


def test_cross_source_validation_refuses_plan_with_isolated_preregistration_id_tamper(tmp_path):
    world = _world(tmp_path)
    plan = _build(world)
    with pytest.raises(ValueError):
        _validate_sources(world, dataclasses.replace(plan, preregistration_id="0" * 64))


def test_cross_source_validation_refuses_plan_with_policy_git_sha_mismatch(tmp_path):
    world = _world(tmp_path)
    plan = _build(world)
    other_sha = _commit_unrelated(world.repo_dir)
    with pytest.raises(ValueError):
        _validate_sources(world, dataclasses.replace(plan, policy_git_sha=other_sha))


def test_cross_source_validation_refuses_self_consistent_but_source_inconsistent_plan(tmp_path):
    """Plan auto-cohérent (fingerprint ET campaign_id recalculés) mais aux champs scientifiques
    modifiés : indétectable en interne (limite acceptée, Décision 20.6), détecté aux sources."""
    world = _world(tmp_path)
    plan = _build(world)
    forged = _forge_plan(plan, budget_per_fold=99)
    assert forged.campaign_protocol_fingerprint != plan.campaign_protocol_fingerprint
    assert forged.campaign_id != plan.campaign_id
    from gate_v_campaign_plan_v2 import validate_gate_v_campaign_plan_v2_structure

    validate_gate_v_campaign_plan_v2_structure(forged)  # cohérent en interne
    with pytest.raises(ValueError):
        _validate_sources(world, forged)  # mais incohérent avec la PreRegistration


def test_cross_source_validation_refuses_each_source_substitution(tmp_path):
    world = _world(tmp_path)
    plan = _build(world)
    substitutions = (
        {"research_run": _research_run(experiment_id="exp_other")},
        {"split_plan": _split_plan(split_plan_id="plan_other")},
        {"policy": _policy("pol_test", threshold=2.0)},
        {"preregistration": dataclasses.replace(world.prereg, preregistration_id="0" * 64)},
    )
    for override in substitutions:
        with pytest.raises(ValueError):
            _validate_sources(world, plan, **override)


def test_cross_source_validation_refuses_non_plan_object(tmp_path):
    world = _world(tmp_path)
    for bad in (None, {}, dataclasses.asdict(_build(world))):
        with pytest.raises(ValueError):
            _validate_sources(world, bad)


# -- Immutabilité profonde (mission §21) ---------------------------------------------------------

_NESTED_PARAMS = {"n_neighbors": 5, "nested": {"levels": [1, 2], "flag": True}}


def _json_clone(value):
    import json

    return json.loads(json.dumps(value))


def _nested_world(tmp_path):
    params = _json_clone(_NESTED_PARAMS)
    return _world(
        tmp_path, base_params=params, walk_forward_specification=_wf_spec(base_params=_json_clone(params)),
    )


def test_plan_is_isolated_from_later_mutation_of_caller_supplied_mappings(tmp_path):
    from gate_v_campaign_plan_v2 import validate_gate_v_campaign_plan_v2_structure

    world = _nested_world(tmp_path)
    plan = _build(world)
    reference_id = plan.campaign_id
    # Mutation APRÈS construction des objets fournis par l'appelant (dict d'origine + spec).
    world.protocol["base_params"]["nested"]["levels"].append(99)
    world.protocol["base_params"]["n_neighbors"] = 42
    world.protocol["walk_forward_specification"].base_params["nested"]["levels"].append(99)
    assert plan.base_params["nested"]["levels"] == (1, 2)
    assert plan.base_params["n_neighbors"] == 5
    assert plan.walk_forward_specification.base_params["nested"]["levels"] == (1, 2)
    assert plan.campaign_id == reference_id
    validate_gate_v_campaign_plan_v2_structure(plan)  # toujours cohérent en interne


def test_plan_nested_values_cannot_be_mutated_in_place(tmp_path):
    world = _nested_world(tmp_path)
    plan = _build(world)
    for target in (plan.base_params, plan.base_params["nested"], plan.walk_forward_specification.base_params):
        with pytest.raises(TypeError):
            target["injected"] = 1
        with pytest.raises(TypeError):
            del target["nested" if "nested" in target else "n_neighbors"]
        with pytest.raises(TypeError):
            target.update({"x": 1})
        with pytest.raises(TypeError):
            target.pop("n_neighbors" if "n_neighbors" in target else "levels", None)
        with pytest.raises(TypeError):
            target.setdefault("x", 1)
        with pytest.raises(TypeError):
            target.clear()
        with pytest.raises(TypeError):
            target |= {"x": 1}
    assert isinstance(plan.base_params["nested"]["levels"], tuple)  # list -> tuple : pas d'append possible
    assert not hasattr(plan.base_params["nested"]["levels"], "append")
    assert isinstance(plan.expected_fold_ids, tuple)


def test_plan_dataclasses_are_frozen(tmp_path):
    world = _world(tmp_path)
    plan = _build(world)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.campaign_id = "gate_v_v2_" + "0" * 64
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.policy_git_sha = "0" * 40
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.walk_forward_specification.master_seed = 7
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.base_params = {}


def test_plan_deepcopy_and_replace_preserve_immutability(tmp_path):
    import copy

    world = _nested_world(tmp_path)
    plan = _build(world)
    clone = copy.deepcopy(plan)
    assert clone == plan
    with pytest.raises(TypeError):
        clone.base_params["x"] = 1


def test_plan_survives_pickle_and_shallow_copy_and_stays_immutable(tmp_path):
    """Revue Spec (MINOR) : la copie gelée doit rester sérialisable (usage multiprocess futur) sans
    perdre son immutabilité — `pickle`/`copy.copy` reconstruisaient via le `__setitem__` bloqué."""
    import copy
    import pickle

    world = _nested_world(tmp_path)
    plan = _build(world)
    restored = pickle.loads(pickle.dumps(plan))
    assert restored == plan
    with pytest.raises(TypeError):
        restored.base_params["x"] = 1
    with pytest.raises(TypeError):
        restored.base_params["nested"]["levels"] = ()
    shallow = copy.copy(plan.base_params)
    assert shallow == plan.base_params
    with pytest.raises(TypeError):
        shallow["x"] = 1


def test_gate_v_campaign_plan_v2_module_never_imports_the_v1_orchestration_module():
    import ast
    import gate_v_campaign_plan_v2 as plan_module

    tree = ast.parse(open(plan_module.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert "gate_v_campaign" not in imported


# -- Persistance exclusive (mission §22) ---------------------------------------------------------


def _saved(world, tmp_path):
    from gate_v_campaign_plan_v2 import save_gate_v_campaign_plan_v2

    plan = _build(world)
    root = tmp_path / "results" / "job_x" / "gate_v" / "campaigns"
    return plan, root, save_gate_v_campaign_plan_v2(root, plan)


def test_save_writes_canonical_path_and_exactly_the_27_fields(tmp_path):
    world = _world(tmp_path)
    plan, root, path = _saved(world, tmp_path)
    assert path == root / plan.campaign_id / "plan.json"
    record = _json.loads(path.read_text(encoding="utf-8"))
    assert tuple(sorted(record)) == tuple(sorted(_EXPECTED_FIELDS))
    assert len(record) == 27
    text = path.read_text(encoding="utf-8")
    for forbidden in ("created_at", "oos_evidence", str(tmp_path).replace("\\", "\\\\"), "plan_path"):
        assert forbidden not in text


def test_save_is_exclusive_second_write_is_refused_without_touching_the_file(tmp_path):
    from gate_v_campaign_plan_v2 import save_gate_v_campaign_plan_v2

    world = _world(tmp_path)
    plan, root, path = _saved(world, tmp_path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        save_gate_v_campaign_plan_v2(root, plan)
    assert path.read_bytes() == before


def test_save_refuses_to_overwrite_a_different_existing_plan_file(tmp_path):
    from gate_v_campaign_plan_v2 import save_gate_v_campaign_plan_v2

    world = _world(tmp_path)
    plan = _build(world)
    root = tmp_path / "campaigns"
    target = root / plan.campaign_id / "plan.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"tampered": true}', encoding="utf-8")
    with pytest.raises(FileExistsError):
        save_gate_v_campaign_plan_v2(root, plan)
    assert target.read_text(encoding="utf-8") == '{"tampered": true}'


def test_save_uses_exclusive_creation_primitive_never_save_atomic(tmp_path, monkeypatch):
    import atomic_json_store
    import gate_v_campaign_plan_v2 as plan_module

    def _forbidden(*args, **kwargs):
        raise AssertionError("save_atomic()/save_atomic_overwrite() ne doivent jamais servir au plan V2")

    monkeypatch.setattr(atomic_json_store, "save_atomic", _forbidden)
    monkeypatch.setattr(atomic_json_store, "save_atomic_overwrite", _forbidden)
    assert not hasattr(plan_module, "save_atomic")
    calls = []
    original = plan_module.save_exclusive
    monkeypatch.setattr(plan_module, "save_exclusive", lambda *a, **k: calls.append(a) or original(*a, **k))
    world = _world(tmp_path)
    _saved(world, tmp_path)
    assert len(calls) == 1


def test_save_refuses_inconsistent_or_non_plan_objects_and_writes_nothing(tmp_path):
    from gate_v_campaign_plan_v2 import save_gate_v_campaign_plan_v2

    world = _world(tmp_path)
    plan = _build(world)
    root = tmp_path / "campaigns"
    bad_plans = (
        dataclasses.replace(plan, campaign_id="gate_v_v2_" + "0" * 64),
        dataclasses.replace(plan, preregistration_id="0" * 64),
        dataclasses.replace(plan, budget_per_fold=999),
        dataclasses.replace(plan, campaign_plan_semantics_version="gate_v_campaign_plan_v3"),
        None, {}, dataclasses.asdict(plan),
    )
    for bad in bad_plans:
        with pytest.raises(ValueError):
            save_gate_v_campaign_plan_v2(root, bad)
    for bad_root in ("", "   ", None, 12):
        with pytest.raises(ValueError):
            save_gate_v_campaign_plan_v2(bad_root, plan)
    assert not root.exists()


def test_saved_bytes_are_independent_of_runtime_location(tmp_path):
    """Chemins runtime hors identité ET hors contenu : même plan, deux racines, octets identiques."""
    from gate_v_campaign_plan_v2 import save_gate_v_campaign_plan_v2

    world = _world(tmp_path)
    plan = _build(world)
    first = save_gate_v_campaign_plan_v2(tmp_path / "a" / "deep" / "root", plan)
    second = save_gate_v_campaign_plan_v2(tmp_path / "b", plan)
    assert first.read_bytes() == second.read_bytes()


# -- Chargeur pur V2 (mission §23-25) ------------------------------------------------------------


def _load(path):
    from gate_v_campaign_plan_v2 import load_gate_v_campaign_plan_v2

    return load_gate_v_campaign_plan_v2(path)


def _rewrite(path, mutate):
    record = _json.loads(path.read_text(encoding="utf-8"))
    mutate(record)
    path.write_text(_json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_load_round_trip_returns_an_equal_immutable_plan(tmp_path):
    world = _nested_world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    loaded = _load(path)
    assert loaded == plan
    assert isinstance(loaded, GateVCampaignPlanV2)
    assert isinstance(loaded.expected_fold_ids, tuple)
    with pytest.raises(TypeError):
        loaded.base_params["x"] = 1
    with pytest.raises(TypeError):
        loaded.walk_forward_specification.base_params["x"] = 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        loaded.campaign_id = "x"


def test_load_round_trip_with_readiness_spec(tmp_path):
    world = _world(tmp_path, readiness_spec=DailyStateReadiness(latest_safe_start_hour=9, latest_safe_start_minute=30))
    plan, _, path = _saved(world, tmp_path)
    loaded = _load(path)
    assert loaded == plan
    assert loaded.readiness_spec == DailyStateReadiness(latest_safe_start_hour=9, latest_safe_start_minute=30)


def test_loaded_plan_passes_cross_source_validation_after_head_advanced(tmp_path):
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    _commit_unrelated(world.repo_dir)
    _validate_sources(world, _load(path))


def test_load_refuses_missing_corrupt_truncated_and_non_object_files(tmp_path):
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    good = path.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        _load(tmp_path / "does_not_exist" / "plan.json")
    bad_contents = ("", "not json at all", good[: len(good) // 2], "[]", "null", '"text"', "42", "{}")
    for index, content in enumerate(bad_contents):
        broken = tmp_path / f"broken_{index}.json"
        broken.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError):
            _load(broken)


def test_load_refuses_every_missing_field_and_any_unknown_field(tmp_path):
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    for name in _EXPECTED_FIELDS:
        variant = tmp_path / f"missing_{name}.json"
        variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        _rewrite(variant, lambda record, name=name: record.pop(name))
        with pytest.raises(ValueError):
            _load(variant)
    for extra in ("created_at", "oos_evidence_hash", "split_plan_path", "unknown_extra"):
        variant = tmp_path / f"extra_{extra}.json"
        variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        _rewrite(variant, lambda record, extra=extra: record.__setitem__(extra, "x"))
        with pytest.raises(ValueError):
            _load(variant)


def test_load_refuses_absent_or_unknown_semantics_version(tmp_path):
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    for value in ("gate_v_campaign_plan_v3", "gate_v_campaign_plan_v1", "", None, 2, ["gate_v_campaign_plan_v2"]):
        variant = tmp_path / f"semver_{abs(hash(repr(value)))}.json"
        variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        _rewrite(variant, lambda record, value=value: record.__setitem__("campaign_plan_semantics_version", value))
        with pytest.raises(ValueError):
            _load(variant)
    absent = tmp_path / "semver_absent.json"
    absent.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    _rewrite(absent, lambda record: record.pop("campaign_plan_semantics_version"))
    with pytest.raises(ValueError):
        _load(absent)


def test_load_refuses_a_real_v1_plan_json_and_never_falls_back_to_the_v1_loader(tmp_path, monkeypatch):
    import gate_v_campaign

    v1_root = tmp_path / "v1"
    split_path = v1_root / "split.json"
    v1_root.mkdir()
    from dataset_split import save_dataset_split_plan

    v1_split = build_dataset_split_plan(
        split_plan_id="synthetic_split", dataset_snapshot_id=_SNAPSHOT_ID,
        train=build_split_boundary("2020-01-01T00:00:00+00:00", "2022-01-01T00:00:00+00:00"),
        validation=build_split_boundary("2022-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
        final_holdout=build_split_boundary("2025-01-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00"),
        created_at="2025-01-01T00:00:00+00:00",
    )
    save_dataset_split_plan(split_path, v1_split)
    v1_plan = gate_v_campaign.build_gate_v_campaign_plan(
        research_run_id="research_synthetic_001", dataset_snapshot_id=_SNAPSHOT_ID,
        split_plan_id="synthetic_split", split_plan_path=split_path, strategy_name="Synthetic Strategy",
        base_params={"lookback": 12}, search_mode="grid", search_space_hash="a" * 12, budget_per_fold=20,
        geometry="rolling", train_period="P24M", test_period="P6M", step_period="P6M",
        readiness_spec=None, master_seed=None,
    )
    v1_path = gate_v_campaign.save_gate_v_campaign_plan(v1_root / "campaigns", v1_plan)
    assert v1_path.is_file()

    def _no_fallback(*args, **kwargs):
        raise AssertionError("le loader V2 ne doit jamais retomber sur le loader V1")

    monkeypatch.setattr(gate_v_campaign, "load_gate_v_campaign_plan", _no_fallback)
    with pytest.raises(ValueError):
        _load(v1_path)
    # Et l'inverse : le plan V2 n'est pas un plan V1 (jamais reclassé).
    world = _world(tmp_path)
    _, _, v2_path = _saved(world, tmp_path)
    assert "campaign_plan_semantics_version" in _json.loads(v2_path.read_text(encoding="utf-8"))
    assert "campaign_plan_semantics_version" not in _json.loads(v1_path.read_text(encoding="utf-8"))


def test_load_refuses_invalid_nested_walk_forward_specification(tmp_path):
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    mutations = {
        "not_an_object": lambda spec: "rolling",
        "missing_key": lambda spec: {k: v for k, v in spec.items() if k != "geometry"},
        "extra_key": lambda spec: {**spec, "extra": 1},
        "unsupported_geometry": lambda spec: {**spec, "geometry": "anchored"},
        "verdict_policy_set": lambda spec: {**spec, "verdict_policy_id": "some_policy"},
        "base_params_differ": lambda spec: {**spec, "base_params": {"n_neighbors": 6}},
        "partial_last_fold": lambda spec: {**spec, "allow_partial_last_fold": True},
        "step_ne_test": lambda spec: {**spec, "step_period": "P2M"},
        "seed_wrong_type": lambda spec: {**spec, "master_seed": "7"},
        "seed_bool": lambda spec: {**spec, "master_seed": True},
        "semantics_version_differs": lambda spec: {**spec, "walk_forward_semantics_version": "rolling-calendar-v0"},
    }
    for label, mutate in mutations.items():
        variant = tmp_path / f"wf_{label}.json"
        variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        _rewrite(variant, lambda record, mutate=mutate: record.__setitem__(
            "walk_forward_specification", mutate(record["walk_forward_specification"])))
        with pytest.raises(ValueError):
            _load(variant)


def test_load_refuses_invalid_nested_readiness_spec(tmp_path):
    world = _world(tmp_path, readiness_spec=DailyStateReadiness(latest_safe_start_hour=9, latest_safe_start_minute=30))
    plan, _, path = _saved(world, tmp_path)
    bad_values = (
        "9:30", [9, 30], {"latest_safe_start_hour": 9},
        {"latest_safe_start_hour": 9, "latest_safe_start_minute": 30, "timezone": "Europe/Paris", "extra": 1},
        {"latest_safe_start_hour": "9", "latest_safe_start_minute": 30, "timezone": "Europe/Paris"},
        {"latest_safe_start_hour": True, "latest_safe_start_minute": 30, "timezone": "Europe/Paris"},
        {"latest_safe_start_hour": 25, "latest_safe_start_minute": 30, "timezone": "Europe/Paris"},
        {"latest_safe_start_hour": 9, "latest_safe_start_minute": 30, "timezone": ""},
    )
    for index, bad in enumerate(bad_values):
        variant = tmp_path / f"readiness_{index}.json"
        variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        _rewrite(variant, lambda record, bad=bad: record.__setitem__("readiness_spec", bad))
        with pytest.raises(ValueError):
            _load(variant)


def test_load_refuses_structurally_invalid_field_values(tmp_path):
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    bad_values = {
        "policy_git_sha": ("HEAD", "abc123", plan.policy_git_sha.upper(), plan.policy_git_sha[:12], "", None, 5),
        "campaign_id": ("gate_v_" + "0" * 64, "gate_v_v2_short", "", None),
        "preregistration_id": ("xyz", "", None, "A" * 64),
        "preregistration_content_hash": ("xyz", None),
        "campaign_protocol_fingerprint": ("xyz", None),
        "research_run_content_hash": ("xyz", None),
        "split_plan_fingerprint": ("xyz", None),
        "expected_fold_definitions_hash": ("xyz", None),
        "validation_zone_hash": ("xyz", None),
        "policy_content_hash": ("xyz", None),
        "search_mode": ("random", "", None),
        "search_space_hash": ("A" * 12, "a" * 11, "g" * 12, None),
        "budget_per_fold": (0, -1, True, 1.5, "10", None),
        "base_params": ({}, [], "x", None),
        "expected_fold_ids": ([], "fold_000", [1], None, [""]),
        "strategy_name": ("", None, 3),
        "research_run_id": ("a/b", "..", "", None),
        "split_plan_id": ("a/b", "", None),
        "gate_v_validation_policy_id": ("a/b", "", None),
        "assessment_semantics_version": ("", None),
    }
    counter = 0
    for field_name, values in bad_values.items():
        for value in values:
            counter += 1
            variant = tmp_path / f"bad_{counter}.json"
            variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            _rewrite(variant, lambda record, field_name=field_name, value=value: record.__setitem__(field_name, value))
            with pytest.raises(ValueError):
                _load(variant)


def test_load_refuses_non_finite_or_non_json_base_params(tmp_path):
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    text = path.read_text(encoding="utf-8")
    nan_variant = tmp_path / "nan.json"
    nan_variant.write_text(text.replace('"n_neighbors": 5', '"n_neighbors": NaN', 1), encoding="utf-8")
    assert "NaN" in nan_variant.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        _load(nan_variant)


# -- Tampering : primitives -> barrière 1 ; preregistration_id seul -> barrière 2 -----------------


def test_primitive_field_tamper_is_rejected_by_fingerprint_barrier(tmp_path):
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    tampers = {
        "budget_per_fold": 11,
        "search_mode": "grid",
        "search_space_hash": "b" * 12,
        "strategy_name": "another_strategy",
        "dataset_snapshot_id": "local_csv:sha256:" + "cd" * 32,
        "split_plan_id": "plan_other",
        "research_run_id": "run_other",
        "research_run_content_hash": "0" * 64,
        "split_plan_fingerprint": "0" * 64,
        "expected_fold_definitions_hash": "0" * 64,
        "validation_zone_hash": "0" * 64,
        "policy_content_hash": "0" * 64,
        "gate_v_validation_policy_id": "pol_other",
        "assessment_semantics_version": "gate_v_assessment_v2",
        "monte_carlo_semantics_version": "monte-carlo-v0",
        "parameter_stability_semantics_version": "parameter-stability-v0",
        "walk_forward_spec_semantics_version": "rolling-calendar-v0",
        "expected_fold_ids": ["fold_000"],
    }
    for index, (field_name, value) in enumerate(tampers.items()):
        variant = tmp_path / f"tamper_{index}.json"
        variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        _rewrite(variant, lambda record, field_name=field_name, value=value: record.__setitem__(field_name, value))
        with pytest.raises(ValueError):
            _load(variant)


def test_nested_protocol_tamper_is_rejected(tmp_path):
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    for index, (key, value) in enumerate((("train_period", "P2M"), ("master_seed", 99), ("test_period", "P2M"))):
        variant = tmp_path / f"nested_{index}.json"
        variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

        def mutate(record, key=key, value=value):
            record["walk_forward_specification"][key] = value
            if key == "test_period":
                record["walk_forward_specification"]["step_period"] = value

        _rewrite(variant, mutate)
        with pytest.raises(ValueError):
            _load(variant)
    variant = tmp_path / "base_params_tamper.json"
    variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    _rewrite(variant, lambda record: (
        record["base_params"].__setitem__("n_neighbors", 6),
        record["walk_forward_specification"]["base_params"].__setitem__("n_neighbors", 6),
    ))
    with pytest.raises(ValueError):
        _load(variant)


def test_preregistration_id_only_tamper_is_rejected_by_the_campaign_id_barrier(tmp_path):
    """LE MAJOR fermé par la Décision 20 : `preregistration_id` n'entre PAS dans la préimage du
    fingerprint de protocole. Le fingerprint reste donc identique (barrière 1 muette), mais le
    `campaign_id` devient incohérent — seule la barrière 2 le détecte, et le chargement refuse."""
    from gate_v_campaign_plan_v2 import _recompute_protocol_fingerprint

    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    variant = tmp_path / "prereg_id_only.json"
    variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    forged_preregistration_id = "f" * 64
    assert forged_preregistration_id != plan.preregistration_id
    _rewrite(variant, lambda record: record.__setitem__("preregistration_id", forged_preregistration_id))

    # Le fingerprint n'a pas bougé : la barrière 1 ne peut pas voir cette falsification.
    forged = dataclasses.replace(plan, preregistration_id=forged_preregistration_id)
    assert _recompute_protocol_fingerprint(forged) == plan.campaign_protocol_fingerprint == forged.campaign_protocol_fingerprint
    # Seule la barrière 2 (campaign_id) refuse, au chargement comme à la validation interne.
    with pytest.raises(ValueError, match="barrière 2"):
        _load(variant)


def test_fields_bound_by_no_internal_barrier_are_only_caught_by_cross_source_validation(tmp_path):
    """LIMITE ACCEPTÉE et VERROUILLÉE (Décision 20.3/20.6) : `preregistration_content_hash` et
    `policy_git_sha` n'entrent NI dans le fingerprint de protocole NI dans la préimage du
    `campaign_id` (formules figées). Le chargeur PUR ne peut donc pas les détecter isolément ;
    la revalidation cross-sources (PreRegistration réelle) DOIT les refuser. Tout consommateur
    (Slice D) doit appeler `validate_gate_v_campaign_plan_v2_sources()` avant de s'y fier."""
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    other_sha = _commit_unrelated(world.repo_dir)
    for field_name, value in (("preregistration_content_hash", "0" * 64), ("policy_git_sha", other_sha)):
        assert value != getattr(plan, field_name)
        variant = tmp_path / f"unbound_{field_name}.json"
        variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        _rewrite(variant, lambda record, field_name=field_name, value=value: record.__setitem__(field_name, value))
        loaded = _load(variant)  # le chargeur pur l'accepte : limite documentée
        assert getattr(loaded, field_name) == value
        with pytest.raises(ValueError):
            _validate_sources(world, loaded)  # la revalidation cross-sources le refuse


def test_campaign_id_only_tamper_is_rejected(tmp_path):
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    variant = tmp_path / "campaign_id_only.json"
    variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    _rewrite(variant, lambda record: record.__setitem__("campaign_id", "gate_v_v2_" + "0" * 64))
    with pytest.raises(ValueError, match="barrière 2"):
        _load(variant)


def test_protocol_fingerprint_only_tamper_is_rejected_by_barrier_1(tmp_path):
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    variant = tmp_path / "fingerprint_only.json"
    variant.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    _rewrite(variant, lambda record: record.__setitem__("campaign_protocol_fingerprint", "0" * 64))
    with pytest.raises(ValueError, match="barrière 1"):
        _load(variant)


# -- Chargeur PUR : aucune E/S croisée cachée (mission §23) --------------------------------------


def test_loader_is_pure_no_git_no_cross_io_even_when_git_is_unavailable(tmp_path, monkeypatch):
    import gate_v_preregistration
    import subprocess as subprocess_module

    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)

    def _no_process(*args, **kwargs):
        raise AssertionError("le chargeur pur ne doit lancer AUCUN processus (ni Git ni autre)")

    monkeypatch.setattr(subprocess_module, "run", _no_process)
    monkeypatch.setattr(subprocess_module, "Popen", _no_process)
    monkeypatch.setattr(subprocess_module, "check_output", _no_process)
    monkeypatch.setattr(gate_v_preregistration, "_run_git", _no_process)
    monkeypatch.setattr(gate_v_preregistration, "verify_policy_git_provenance", _no_process)
    monkeypatch.setattr(gate_v_preregistration, "verify_policy_git_provenance_historical", _no_process)
    import gate_v_campaign_plan_v2 as plan_module

    monkeypatch.setattr(plan_module, "verify_policy_git_provenance_historical", _no_process)
    monkeypatch.setattr(os, "chdir", _no_process)
    assert _load(path) == plan


def test_loader_reads_only_the_plan_file_from_an_isolated_directory(tmp_path):
    """Sans dépôt Git, sans PreRegistration, sans ResearchRun, sans split, sans policy : le plan
    interne valide se charge quand même (aucune E/S croisée)."""
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    isolated = tmp_path / "isolated" / "somewhere" / "plan.json"
    isolated.parent.mkdir(parents=True)
    isolated.write_bytes(path.read_bytes())
    assert _load(isolated) == plan  # emplacement runtime hors identité


def test_loader_result_is_independent_of_process_cwd(tmp_path):
    world = _world(tmp_path)
    plan, _, path = _saved(world, tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    original_cwd = os.getcwd()
    os.chdir(elsewhere)
    try:
        assert _load(path) == plan
    finally:
        os.chdir(original_cwd)


# -- V1 non régressé et compatibilité de constantes ---------------------------------------------


def test_search_modes_single_source_matches_the_v1_reference_constant():
    import gate_v_campaign
    import gate_v_campaign_plan_v2 as plan_module
    import gate_v_preregistration as prereg_module

    assert plan_module.GATE_V_SEARCH_MODES is prereg_module.GATE_V_SEARCH_MODES
    assert plan_module.GATE_V_SEARCH_MODES == gate_v_campaign._SEARCH_MODES


def test_builder_normalizes_uppercase_search_space_hash_consistently_with_the_preregistration(tmp_path):
    world = _world(tmp_path, search_space_hash="ABCDEF012345")
    lower, upper = _build(world, search_space_hash="abcdef012345"), _build(world, search_space_hash="ABCDEF012345")
    assert lower == upper
    assert lower.search_space_hash == "abcdef012345"
    assert _saved(world, tmp_path)[0].search_space_hash == "abcdef012345"


def test_builder_uses_the_shared_canonical_protocol_validation(tmp_path):
    world = _world(tmp_path)
    cases = (
        ({"search_mode": "random"}, "search_mode"),
        ({"search_mode": None}, "search_mode"),
        ({"search_space_hash": "xyz"}, "search_space_hash"),
        ({"search_space_hash": "a" * 13}, "search_space_hash"),
        ({"budget_per_fold": 0}, "budget_per_fold"),
        ({"budget_per_fold": True}, "budget_per_fold"),
        ({"base_params": {}}, "base_params"),
        ({"base_params": {"x": float("nan")}}, "base_params"),
        ({"readiness_spec": "9:30"}, "readiness_spec"),
    )
    for overrides, expected_field in cases:
        with pytest.raises(ValueError, match=expected_field):
            _build(world, **overrides)


@pytest.mark.parametrize("entry_form", ["HEAD", "short", "branch", "auto"])
def test_preregistration_created_from_symbolic_or_short_entry_is_consumable_by_plan_v2_after_head_advances(
    tmp_path, entry_form,
):
    """MAJOR 1 de bout en bout : la PreRegistration persiste le SHA COMPLET canonique même quand
    elle est créée avec `HEAD`/SHA court/branche ; HEAD avance ; le Plan V2 (provenance historique)
    se construit, se sauvegarde, se recharge et se revalide aux sources."""
    repo_dir, policy_path, sha_a, policy = _commit_policy(tmp_path)
    entry = {
        "HEAD": "HEAD", "short": sha_a[:10], "auto": "auto",
        "branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_dir).strip(),
    }[entry_form]
    research_run, split_plan = _research_run(), _split_plan()
    protocol = dict(
        strategy_name="perfect_revolution_v1", base_params={"n_neighbors": 5}, search_mode="single_var",
        search_space_hash="a" * 12, budget_per_fold=10, walk_forward_specification=_wf_spec(), readiness_spec=None,
    )
    prereg = build_gate_v_preregistration(
        research_run=research_run, split_plan=split_plan, policy=policy, policy_path=policy_path,
        assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION, repo_dir=repo_dir,
        policy_git_sha=entry, **protocol,
    )
    assert prereg.policy_git_sha == sha_a  # SHA complet canonique, jamais la référence d'origine
    sha_b = _commit_unrelated(repo_dir)
    assert sha_b != sha_a
    world = _World(repo_dir, policy_path, sha_a, policy, research_run, split_plan, protocol, prereg)
    plan = _build(world)
    assert plan.policy_git_sha == sha_a
    plan_saved, _, path = _saved(world, tmp_path)
    assert plan_saved == plan
    _validate_sources(world, _load(path))


def test_v1_plan_type_and_campaign_id_shape_are_untouched():
    import gate_v_campaign

    v1_names = [f.name for f in dataclasses.fields(gate_v_campaign.GateVCampaignPlan)]
    assert v1_names[0] == "campaign_id"
    assert "oos_evidence_validation_run_id" in v1_names
    assert "campaign_plan_semantics_version" not in v1_names
    assert "policy_git_sha" not in v1_names
