"""
tests/test_gate_v_campaign_manifest_v2.py — AF-V-07 Slice D2 (ADR 0025 Décision 21.4 / 21.5 / 21.13).

Type `GateVCampaignManifestV2` (17 champs), constantes, builder initial EN MÉMOIRE, validation structurelle
pure, liaison au `GateVCampaignPlanV2`, conversion record pure. Aucune persistance, aucune dérivation de
statut depuis les preuves (D3), aucun verrou/sentinelle (D4), aucun rechargement de preuves (D5), aucune
discrimination de dossier (D6), aucun Claim, aucun FINAL_HOLDOUT.

Fixtures SYNTHÉTIQUES : un dépôt Git temporaire hermétique fournit la provenance historique de la policy ;
aucune donnée de marché, aucun backtest.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Mapping
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_v_campaign
import gate_v_campaign_manifest_v2 as m2
from dataset_split import build_dataset_split_plan, build_split_boundary, save_dataset_split_plan
from gate_v_campaign_plan_v2 import GateVCampaignPlanV2, build_gate_v_campaign_plan_v2
from gate_v_evidence_completeness_v2 import gate_v_v2_validation_run_id
from gate_v_preregistration import build_gate_v_preregistration
from gate_v_validation_policy import (
    OosPolicyCriterion,
    WalkForwardPolicyCriterion,
    build_gate_v_validation_policy,
    save_gate_v_validation_policy,
)
from research_run import build_research_run
from validation_run import (
    VALIDATION_TYPE_MONTE_CARLO,
    VALIDATION_TYPE_PARAMETER_STABILITY,
    VALIDATION_TYPE_WALK_FORWARD,
    FoldResult,
    FoldSelection,
    MonteCarloEvidence,
    ParameterStabilityEvidence,
    PercentileDistributionSummary,
    WalkForwardEvidence,
    build_monte_carlo_specification,
    build_parameter_stability_specification,
    build_validation_run,
)
from walk_forward import build_aggregate_result, build_walk_forward_specification, compute_fold_definitions

_SNAPSHOT_ID = "synthetic_csv:sha256:" + "ab" * 32
_STRATEGY = "Synthetic Strategy"
_RESEARCH_RUN_ID = "research_synthetic_001"
_SPLIT_PLAN_ID = "synthetic_split"
_PROTOCOL = dict(base_params={"lookback": 12}, search_mode="grid", search_space_hash="a" * 12)
_WF = VALIDATION_TYPE_WALK_FORWARD
_MC = VALIDATION_TYPE_MONTE_CARLO
_PS = VALIDATION_TYPE_PARAMETER_STABILITY

_EXPECTED_FIELDS = (
    "manifest_semantics_version", "campaign_id", "preregistration_id", "campaign_protocol_fingerprint",
    "manifest_revision", "status", "execution_started", "running", "technical_failure_reason",
    "walk_forward_validation_run_id", "monte_carlo_validation_run_id",
    "parameter_stability_validation_run_ids_by_fold",
    "final_holdout_claim_id", "final_holdout_claim_content_hash", "holdout_access_event_id",
    "holdout_access_event_content_hash", "oos_evidence_validation_run_id",
)
_RESERVED_FIELDS = _EXPECTED_FIELDS[12:]
_EXPECTED_STATUSES = {
    "READY_FOR_EXECUTION", "RUNNING", "EVIDENCE_INCOMPLETE", "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT",
    "TECHNICAL_FAILURE",
}


# ============================================================================================
# Fixtures : deux Plans V2 réels (campagnes DIFFÉRENTES) et un Plan V1 réel
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
        "pol_d2",
        {
            "oos": (OosPolicyCriterion(metric="net_ret_pct", operator=">", threshold=0.0),),
            "walk_forward": (WalkForwardPolicyCriterion(metric="oos_net_return_pct", operator=">", threshold=0.0),),
        },
    )
    policy_path = repo_dir / "validation_policies" / "pol_d2.json"
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


def _build_plan_v2(root, split, *, budget_per_fold):
    repo_dir, policy_path, policy = _commit_policy(root)
    research_run = build_research_run(
        research_run_id=_RESEARCH_RUN_ID, experiment_id="exp_d2", dataset_snapshot_id=_SNAPSHOT_ID, git_sha=None,
    )
    spec = build_walk_forward_specification(
        base_params=dict(_PROTOCOL["base_params"]), geometry="rolling", train_period="P24M",
        test_period="P6M", step_period="P6M",
    )
    protocol = dict(
        strategy_name=_STRATEGY, walk_forward_specification=spec, readiness_spec=None,
        budget_per_fold=budget_per_fold, **_PROTOCOL,
    )
    prereg = build_gate_v_preregistration(
        research_run=research_run, split_plan=split, policy=policy, policy_path=policy_path,
        assessment_semantics_version="gate_v_assessment_v1", repo_dir=repo_dir, **protocol,
    )
    return build_gate_v_campaign_plan_v2(
        preregistration=prereg, research_run=research_run, split_plan=split, policy=policy,
        policy_path=policy_path, repo_dir=repo_dir, **protocol,
    )


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    root = tmp_path_factory.mktemp("d2_worlds")
    split = _split_plan()
    split_path = root / "split.json"
    save_dataset_split_plan(split_path, split)
    plan = _build_plan_v2(root, split, budget_per_fold=20)
    other_plan = _build_plan_v2(root, split, budget_per_fold=21)
    v1_plan = gate_v_campaign.build_gate_v_campaign_plan(
        research_run_id=_RESEARCH_RUN_ID, dataset_snapshot_id=_SNAPSHOT_ID, split_plan_id=_SPLIT_PLAN_ID,
        split_plan_path=split_path, strategy_name=_STRATEGY, geometry="rolling", train_period="P24M",
        test_period="P6M", step_period="P6M", readiness_spec=None, master_seed=None, budget_per_fold=20,
        **_PROTOCOL,
    )
    assert plan.campaign_id != other_plan.campaign_id
    assert len(plan.expected_fold_ids) == 3
    return SimpleNamespace(plan=plan, other_plan=other_plan, v1_plan=v1_plan, split=split)


# ============================================================================================
# Tranche 1 — constantes, type, builder initial
# ============================================================================================


def test_semantics_version_constant_is_exact():
    assert m2.GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION == "gate_v_campaign_manifest_v2"


def test_v2_statuses_are_exactly_the_five_factual_states():
    assert m2.GATE_V_CAMPAIGN_V2_STATUSES == frozenset(_EXPECTED_STATUSES)


def test_no_status_segment_is_a_verdict_word_and_technical_failure_stays_valid():
    """Par SEGMENTS (split sur « _ ») et jamais par sous-chaîne : TECHNICAL_FAILURE contient « FAIL »."""
    forbidden = {"PASS", "FAIL", "CHAMPION", "OOS", "VERDICT"}
    for status in m2.GATE_V_CAMPAIGN_V2_STATUSES:
        assert not set(status.split("_")) & forbidden, status
    assert "TECHNICAL_FAILURE" in m2.GATE_V_CAMPAIGN_V2_STATUSES
    assert "FAIL" in "TECHNICAL_FAILURE"  # la sous-chaîne existe : c'est pourquoi le test est par segments


def test_the_v1_only_status_awaiting_policy_is_not_a_v2_status():
    assert "EVIDENCE_COMPLETE_AWAITING_POLICY" not in m2.GATE_V_CAMPAIGN_V2_STATUSES
    assert "NOT_READY" not in m2.GATE_V_CAMPAIGN_V2_STATUSES


def test_manifest_is_a_frozen_dataclass_with_exactly_the_17_fields_in_order():
    assert dataclasses.is_dataclass(m2.GateVCampaignManifestV2)
    assert tuple(field.name for field in dataclasses.fields(m2.GateVCampaignManifestV2)) == _EXPECTED_FIELDS
    assert len(_EXPECTED_FIELDS) == 17
    assert m2.GateVCampaignManifestV2.__dataclass_params__.frozen is True


def test_the_initial_manifest_is_built_in_memory_from_a_v2_plan(worlds):
    plan = worlds.plan
    manifest = m2.build_gate_v_campaign_manifest_v2(plan)
    assert isinstance(manifest, m2.GateVCampaignManifestV2)
    assert manifest.manifest_semantics_version == m2.GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION
    assert manifest.campaign_id == plan.campaign_id
    assert manifest.preregistration_id == plan.preregistration_id
    assert manifest.campaign_protocol_fingerprint == plan.campaign_protocol_fingerprint
    assert manifest.manifest_revision == 0 and type(manifest.manifest_revision) is int
    assert manifest.status == "READY_FOR_EXECUTION"
    assert manifest.execution_started is False and manifest.running is False
    assert manifest.technical_failure_reason is None
    assert manifest.walk_forward_validation_run_id is None and manifest.monte_carlo_validation_run_id is None
    assert dict(manifest.parameter_stability_validation_run_ids_by_fold) == {}
    for name in _RESERVED_FIELDS:
        assert getattr(manifest, name) is None, name


def test_the_builder_refuses_a_v1_plan_and_any_non_plan_object(worlds):
    for bad in (worlds.v1_plan, None, {}, dataclasses.asdict(worlds.plan), "plan"):
        with pytest.raises(ValueError):
            m2.build_gate_v_campaign_manifest_v2(bad)


def test_the_builder_is_deterministic_and_does_not_mutate_the_plan(worlds):
    before = dataclasses.asdict(worlds.plan)
    assert m2.build_gate_v_campaign_manifest_v2(worlds.plan) == m2.build_gate_v_campaign_manifest_v2(worlds.plan)
    assert dataclasses.asdict(worlds.plan) == before


def test_direct_assignment_on_a_manifest_is_refused(worlds):
    manifest = m2.build_gate_v_campaign_manifest_v2(worlds.plan)
    for field_name in ("status", "manifest_revision", "walk_forward_validation_run_id"):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(manifest, field_name, "x")
    with pytest.raises(TypeError):
        manifest.parameter_stability_validation_run_ids_by_fold["fold_000"] = "x"


# ============================================================================================
# Tranche 2 — validation structurelle PURE (aucune preuve lue, aucun plan nécessaire)
# ============================================================================================


def _initial(plan):
    return m2.build_gate_v_campaign_manifest_v2(plan)


def _with(manifest, **changes):
    """`dataclasses.replace` : le constructeur ne revalide rien, donc un état invalide est constructible."""
    return dataclasses.replace(manifest, **changes)


def _ids(plan):
    return dict(
        wf=gate_v_v2_validation_run_id(plan, _WF),
        mc=gate_v_v2_validation_run_id(plan, _MC),
        ps={fold: gate_v_v2_validation_run_id(plan, _PS, fold_id=fold) for fold in plan.expected_fold_ids},
    )


def _started(plan, *, status="EVIDENCE_INCOMPLETE", **changes):
    return _with(_initial(plan), execution_started=True, status=status, **changes)


def _complete(plan):
    ids = _ids(plan)
    return _started(
        plan, status="EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT", walk_forward_validation_run_id=ids["wf"],
        monte_carlo_validation_run_id=ids["mc"], parameter_stability_validation_run_ids_by_fold=ids["ps"],
    )


def _flip_last_hex_digit(value):
    return value[:-1] + ("0" if value[-1] != "0" else "1")


def test_a_valid_manifest_passes_the_structural_validator_in_every_legal_marker_state(worlds):
    plan = worlds.plan
    ids = _ids(plan)
    first_fold = plan.expected_fold_ids[0]
    valid = [
        _initial(plan),
        _with(_initial(plan), execution_started=True, running=True, status="RUNNING"),
        _started(plan),
        _started(plan, walk_forward_validation_run_id=ids["wf"]),
        _started(plan, walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=ids["mc"]),
        _started(plan, walk_forward_validation_run_id=ids["wf"],
                 parameter_stability_validation_run_ids_by_fold={first_fold: ids["ps"][first_fold]}),
        _with(_initial(plan), execution_started=True, status="TECHNICAL_FAILURE", technical_failure_reason="boom"),
        _complete(plan),
        _with(_initial(plan), manifest_revision=7),
    ]
    for manifest in valid:
        assert m2.validate_gate_v_campaign_manifest_v2_structure(manifest) is None


def test_the_structural_validator_refuses_anything_that_is_not_a_v2_manifest(worlds):
    v1_manifest = gate_v_campaign.build_gate_v_campaign_manifest(worlds.v1_plan)
    for bad in (v1_manifest, None, {}, dataclasses.asdict(_initial(worlds.plan)), "manifest", worlds.plan):
        with pytest.raises(ValueError):
            m2.validate_gate_v_campaign_manifest_v2_structure(bad)


@pytest.mark.parametrize("bad_version", ["gate_v_campaign_manifest_v1", "gate_v_campaign_manifest_v3", "", None, 2])
def test_an_unknown_semantics_version_is_refused(worlds, bad_version):
    manifest = _with(_initial(worlds.plan), manifest_semantics_version=bad_version)
    with pytest.raises(ValueError):
        m2.validate_gate_v_campaign_manifest_v2_structure(manifest)


def test_a_falsified_campaign_id_is_refused_by_the_internal_recomputation(worlds):
    manifest = _initial(worlds.plan)
    v1_shaped = "gate_v_" + manifest.campaign_id.removeprefix("gate_v_v2_")
    forged = [
        _flip_last_hex_digit(manifest.campaign_id),  # forme valide, valeur fausse : seul le recalcul le voit
        worlds.other_plan.campaign_id,  # ID VALIDE d'une autre campagne
        v1_shaped, "gate_v_v2_" + "A" * 64, "gate_v_v2_" + "a" * 63, manifest.campaign_id + "x", "", None, 7,
    ]
    for campaign_id in forged:
        with pytest.raises(ValueError):
            m2.validate_gate_v_campaign_manifest_v2_structure(_with(manifest, campaign_id=campaign_id))


def test_a_falsified_preregistration_id_or_fingerprint_diverges_from_the_recomputed_campaign_id(worlds):
    manifest = _initial(worlds.plan)
    for field_name in ("preregistration_id", "campaign_protocol_fingerprint"):
        value = getattr(manifest, field_name)
        with pytest.raises(ValueError):  # hex64 valide mais différent : le campaign_id ne correspond plus
            m2.validate_gate_v_campaign_manifest_v2_structure(
                _with(manifest, **{field_name: _flip_last_hex_digit(value)}))
        for malformed in (value.upper(), value[:-1], value + "0", "x", "", None, 5):
            with pytest.raises(ValueError):
                m2.validate_gate_v_campaign_manifest_v2_structure(_with(manifest, **{field_name: malformed}))


@pytest.mark.parametrize("bad_revision", [True, False, -1, "0", 1.0, 1.5, None, [0]])
def test_the_revision_must_be_a_non_boolean_non_negative_integer(worlds, bad_revision):
    manifest = _with(_initial(worlds.plan), manifest_revision=bad_revision)
    with pytest.raises(ValueError):
        m2.validate_gate_v_campaign_manifest_v2_structure(manifest)


@pytest.mark.parametrize("bad_status", [
    "PASS", "FAIL", "CHAMPION", "EVIDENCE_COMPLETE_AWAITING_POLICY", "NOT_READY", "FINAL_HOLDOUT_CLAIMED", "", None, 3,
    ["READY_FOR_EXECUTION"], {}, {"RUNNING"},  # non hachables : ValueError, jamais un TypeError brut
])
def test_an_unknown_status_is_refused(worlds, bad_status):
    with pytest.raises(ValueError):
        m2.validate_gate_v_campaign_manifest_v2_structure(_with(_initial(worlds.plan), status=bad_status))


@pytest.mark.parametrize("field_name", ["execution_started", "running"])
@pytest.mark.parametrize("bad_flag", [1, 0, "yes", "", None, [True]])
def test_execution_markers_must_be_booleans(worlds, field_name, bad_flag):
    with pytest.raises(ValueError):
        m2.validate_gate_v_campaign_manifest_v2_structure(_with(_initial(worlds.plan), **{field_name: bad_flag}))


@pytest.mark.parametrize("bad_reason", ["", "   ", "\n", 5, ["x"], True])
def test_a_technical_failure_reason_is_none_or_a_non_empty_string(worlds, bad_reason):
    manifest = _with(
        _initial(worlds.plan), execution_started=True, status="TECHNICAL_FAILURE", technical_failure_reason=bad_reason,
    )
    with pytest.raises(ValueError):
        m2.validate_gate_v_campaign_manifest_v2_structure(manifest)


def test_structurally_contradictory_marker_combinations_are_refused(worlds):
    plan = worlds.plan
    ids = _ids(plan)
    first_fold = plan.expected_fold_ids[0]
    contradictions = {
        "running_without_started": _with(_initial(plan), running=True, status="RUNNING"),
        "failure_reason_without_started": _with(
            _initial(plan), technical_failure_reason="boom", status="TECHNICAL_FAILURE"),
        "failure_reason_while_running": _with(
            _initial(plan), execution_started=True, running=True, technical_failure_reason="boom",
            status="TECHNICAL_FAILURE"),
        "walk_forward_reference_before_start": _with(_initial(plan), walk_forward_validation_run_id=ids["wf"]),
        "monte_carlo_reference_before_start": _with(_initial(plan), monte_carlo_validation_run_id=ids["mc"]),
        "parameter_stability_reference_before_start": _with(
            _initial(plan), parameter_stability_validation_run_ids_by_fold={first_fold: ids["ps"][first_fold]}),
        "monte_carlo_without_walk_forward": _started(plan, monte_carlo_validation_run_id=ids["mc"]),
        "parameter_stability_without_walk_forward": _started(
            plan, parameter_stability_validation_run_ids_by_fold={first_fold: ids["ps"][first_fold]}),
    }
    for name, manifest in contradictions.items():
        with pytest.raises(ValueError):
            m2.validate_gate_v_campaign_manifest_v2_structure(manifest)
        assert name  # le nom documente le cas dans le rapport d'échec


@pytest.mark.parametrize("bad_run_id", ["", "   ", 5, ["x"], True])
def test_a_proof_reference_is_none_or_a_non_empty_string(worlds, bad_run_id):
    plan = worlds.plan
    wf_id = _ids(plan)["wf"]
    with pytest.raises(ValueError):
        m2.validate_gate_v_campaign_manifest_v2_structure(_started(plan, walk_forward_validation_run_id=bad_run_id))
    with pytest.raises(ValueError):
        m2.validate_gate_v_campaign_manifest_v2_structure(
            _started(plan, walk_forward_validation_run_id=wf_id, monte_carlo_validation_run_id=bad_run_id))


def test_the_parameter_stability_mapping_must_map_fold_ids_to_non_empty_run_ids(worlds):
    plan = worlds.plan
    ids = _ids(plan)
    first_fold = plan.expected_fold_ids[0]
    malformed_mappings = (
        [("fold_000", "x")], "mapping", None, {1: "x"}, {"": "x"}, {first_fold: ""}, {first_fold: 5}, {first_fold: None},
    )
    for bad in malformed_mappings:
        manifest = _started(
            plan, walk_forward_validation_run_id=ids["wf"], parameter_stability_validation_run_ids_by_fold=bad,
        )
        with pytest.raises(ValueError):
            m2.validate_gate_v_campaign_manifest_v2_structure(manifest)


@pytest.mark.parametrize("field_name", _RESERVED_FIELDS)
@pytest.mark.parametrize("value", ["x", "", 0, False, {}, "a" * 64])
def test_each_reserved_field_must_be_none_in_slice_d(worlds, field_name, value):
    with pytest.raises(ValueError):
        m2.validate_gate_v_campaign_manifest_v2_structure(_with(_initial(worlds.plan), **{field_name: value}))
    with pytest.raises(ValueError):
        m2.validate_gate_v_campaign_manifest_v2_structure(_with(_complete(worlds.plan), **{field_name: value}))


def test_a_status_that_contradicts_the_markers_is_refused_without_reading_any_proof(worlds):
    """Condition NÉCESSAIRE calculable sans I/O (ADR 0025 21.4) ; le choix entre les deux statuts de preuve
    appartient à la dérivation (D3), jamais à D2."""
    plan = worlds.plan
    ids = _ids(plan)
    complete_status = "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT"
    wrong = {
        "ready_but_started": _with(_initial(plan), execution_started=True),
        "running_flag_with_incomplete_status": _with(
            _initial(plan), execution_started=True, running=True, status="EVIDENCE_INCOMPLETE"),
        "running_status_without_running_flag": _with(_initial(plan), execution_started=True, status="RUNNING"),
        "failure_status_without_reason": _started(plan, status="TECHNICAL_FAILURE"),
        "reason_with_incomplete_status": _started(plan, technical_failure_reason="boom"),
        "reason_with_ready_status": _with(_initial(plan), technical_failure_reason="boom"),
        "evidence_status_before_start": _with(_initial(plan), status="EVIDENCE_INCOMPLETE"),
        "complete_without_any_reference": _started(plan, status=complete_status),
        "complete_without_monte_carlo": _started(
            plan, status=complete_status, walk_forward_validation_run_id=ids["wf"],
            parameter_stability_validation_run_ids_by_fold=ids["ps"]),
        "complete_without_parameter_stability": _started(
            plan, status=complete_status, walk_forward_validation_run_id=ids["wf"],
            monte_carlo_validation_run_id=ids["mc"]),
    }
    for name, manifest in wrong.items():
        with pytest.raises(ValueError):
            m2.validate_gate_v_campaign_manifest_v2_structure(manifest)
        assert name


def test_d2_does_not_derive_the_evidence_status_from_the_references(worlds):
    """Frontière D2/D3 : toutes les références présentes ne prouvent pas la complétude (qualité des preuves) ;
    un statut « incomplet » reste donc structurellement valide — D3 décidera sur les preuves."""
    plan = worlds.plan
    ids = _ids(plan)
    all_references_but_incomplete = _started(
        plan, status="EVIDENCE_INCOMPLETE", walk_forward_validation_run_id=ids["wf"],
        monte_carlo_validation_run_id=ids["mc"], parameter_stability_validation_run_ids_by_fold=ids["ps"],
    )
    assert m2.validate_gate_v_campaign_manifest_v2_structure(all_references_but_incomplete) is None


def test_the_structural_validator_is_pure_deterministic_and_does_not_mutate(worlds):
    manifest = _complete(worlds.plan)
    before = dataclasses.asdict(manifest)
    for _ in range(2):
        assert m2.validate_gate_v_campaign_manifest_v2_structure(manifest) is None
    assert dataclasses.asdict(manifest) == before


# ============================================================================================
# Tranche 3 — liaison au Plan V2 : identité, identifiants de preuves déterministes (importés de D1)
# ============================================================================================


def _against(manifest, plan):
    return m2.validate_gate_v_campaign_manifest_v2_against_plan(manifest, plan)


def test_manifests_bound_to_their_own_plan_are_valid_in_every_legal_state(worlds):
    plan = worlds.plan
    ids = _ids(plan)
    first_fold = plan.expected_fold_ids[0]
    valid = [
        _initial(plan),
        _with(_initial(plan), execution_started=True, running=True, status="RUNNING"),
        _started(plan, walk_forward_validation_run_id=ids["wf"]),
        _started(plan, walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=ids["mc"]),
        _started(plan, walk_forward_validation_run_id=ids["wf"],
                 parameter_stability_validation_run_ids_by_fold={first_fold: ids["ps"][first_fold]}),
        _with(_initial(plan), execution_started=True, status="TECHNICAL_FAILURE", technical_failure_reason="boom"),
        _complete(plan),
    ]
    for manifest in valid:
        assert _against(manifest, plan) is None


def test_the_plan_binding_refuses_a_v1_plan_a_non_plan_and_a_non_manifest(worlds):
    manifest = _initial(worlds.plan)
    for bad_plan in (worlds.v1_plan, None, {}, dataclasses.asdict(worlds.plan), "plan", manifest):
        with pytest.raises(ValueError):
            _against(manifest, bad_plan)
    v1_manifest = gate_v_campaign.build_gate_v_campaign_manifest(worlds.v1_plan)
    for bad_manifest in (v1_manifest, None, {}, dataclasses.asdict(manifest), "manifest", worlds.plan):
        with pytest.raises(ValueError):
            _against(bad_manifest, worlds.plan)


def test_a_manifest_of_another_campaign_is_refused(worlds):
    foreign = _initial(worlds.other_plan)
    assert m2.validate_gate_v_campaign_manifest_v2_structure(foreign) is None  # valide... pour SA campagne
    with pytest.raises(ValueError):
        _against(foreign, worlds.plan)
    with pytest.raises(ValueError):
        _against(_initial(worlds.plan), worlds.other_plan)


def test_the_plan_binding_revalidates_the_plan_structure_and_the_manifest_structure(worlds):
    plan = worlds.plan
    tampered_plan = dataclasses.replace(plan, campaign_id=_flip_last_hex_digit(plan.campaign_id))
    with pytest.raises(ValueError):
        _against(_initial(plan), tampered_plan)
    with pytest.raises(ValueError):
        _against(_with(_initial(plan), final_holdout_claim_id="x"), plan)
    with pytest.raises(ValueError):
        _against(_with(_initial(plan), status="PASS"), plan)
    # Plan falsifié dont l'IDENTITÉ (campagne, pré-enregistrement, empreinte) reste égale à celle du manifeste :
    # seule la revalidation structurelle du plan (barrière d'empreinte) le refuse.
    for tampered in (
        dataclasses.replace(plan, strategy_name="Other Strategy"),
        dataclasses.replace(plan, search_space_hash="b" * 12),
        dataclasses.replace(plan, expected_fold_ids=plan.expected_fold_ids[:2]),
    ):
        assert (tampered.campaign_id, tampered.preregistration_id, tampered.campaign_protocol_fingerprint) == (
            plan.campaign_id, plan.preregistration_id, plan.campaign_protocol_fingerprint)
        with pytest.raises(ValueError):
            _against(_initial(plan), tampered)


def test_identity_fields_must_equal_the_plan_fields(worlds):
    """Même après une structure valide : un Manifest recalculé pour une AUTRE campagne ne se lie pas au plan."""
    plan, other = worlds.plan, worlds.other_plan
    for field_name in ("campaign_id", "preregistration_id", "campaign_protocol_fingerprint"):
        swapped = _with(_initial(plan), **{field_name: getattr(other, field_name)})
        with pytest.raises(ValueError):
            _against(swapped, plan)


def test_foreign_or_misplaced_proof_identifiers_are_refused(worlds):
    plan, other = worlds.plan, worlds.other_plan
    ids, other_ids = _ids(plan), _ids(other)
    first, second = plan.expected_fold_ids[0], plan.expected_fold_ids[1]
    bad = {
        "walk_forward_free_form_id": _started(plan, walk_forward_validation_run_id="free_form_id"),
        "walk_forward_of_another_campaign": _started(plan, walk_forward_validation_run_id=other_ids["wf"]),
        "walk_forward_is_the_monte_carlo_id": _started(plan, walk_forward_validation_run_id=ids["mc"]),
        "monte_carlo_free_form_id": _started(
            plan, walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id="free_form_id"),
        "monte_carlo_of_another_campaign": _started(
            plan, walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=other_ids["mc"]),
        "monte_carlo_is_the_walk_forward_id": _started(
            plan, walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=ids["wf"]),
        "parameter_stability_free_form_id": _started(
            plan, walk_forward_validation_run_id=ids["wf"],
            parameter_stability_validation_run_ids_by_fold={first: "free_form_id"}),
        "parameter_stability_of_another_campaign": _started(
            plan, walk_forward_validation_run_id=ids["wf"],
            parameter_stability_validation_run_ids_by_fold={first: other_ids["ps"][first]}),
        "parameter_stability_id_of_another_fold": _started(
            plan, walk_forward_validation_run_id=ids["wf"],
            parameter_stability_validation_run_ids_by_fold={first: ids["ps"][second]}),
        "parameter_stability_swapped_folds": _started(
            plan, walk_forward_validation_run_id=ids["wf"],
            parameter_stability_validation_run_ids_by_fold={first: ids["ps"][second], second: ids["ps"][first]}),
        "parameter_stability_unexpected_fold": _started(
            plan, walk_forward_validation_run_id=ids["wf"],
            parameter_stability_validation_run_ids_by_fold={
                "fold_999": f"{plan.campaign_id}_parameter_stability_fold_999"}),
        "parameter_stability_walk_forward_id": _started(
            plan, walk_forward_validation_run_id=ids["wf"],
            parameter_stability_validation_run_ids_by_fold={first: ids["wf"]}),
        "parameter_stability_one_good_one_foreign": _started(
            plan, walk_forward_validation_run_id=ids["wf"],
            parameter_stability_validation_run_ids_by_fold={first: ids["ps"][first], second: "free_form_id"}),
    }
    # Frontière D2 : la STRUCTURE refuse tout identifiant qui n'est pas la chaîne déterministe de la campagne ;
    # seul un fold syntaxiquement valide mais HORS plan reste structurellement valide (le membership de
    # `expected_fold_ids` est la responsabilité exclusive de la liaison au plan).
    structurally_valid = {"parameter_stability_unexpected_fold"}
    for name, manifest in bad.items():
        if name in structurally_valid:
            assert m2.validate_gate_v_campaign_manifest_v2_structure(manifest) is None, name
        else:
            with pytest.raises(ValueError):
                m2.validate_gate_v_campaign_manifest_v2_structure(manifest)
        with pytest.raises(ValueError):
            _against(manifest, plan)
    # La garde « fold attendu » du Manifest répond avant l'identifiant déterministe de D1 (message dédié).
    with pytest.raises(ValueError, match="étranger aux folds attendus"):
        _against(bad["parameter_stability_unexpected_fold"], plan)


def test_the_complete_status_requires_every_expected_fold_once_bound_to_the_plan(worlds):
    plan = worlds.plan
    ids = _ids(plan)
    first_fold = plan.expected_fold_ids[0]
    partial = _started(
        plan, status="EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT", walk_forward_validation_run_id=ids["wf"],
        monte_carlo_validation_run_id=ids["mc"],
        parameter_stability_validation_run_ids_by_fold={first_fold: ids["ps"][first_fold]},
    )
    assert m2.validate_gate_v_campaign_manifest_v2_structure(partial) is None  # une entrée PS au minimum
    with pytest.raises(ValueError):
        _against(partial, plan)
    assert _against(_complete(plan), plan) is None


def test_an_incomplete_manifest_may_reference_only_some_expected_folds(worlds):
    plan = worlds.plan
    ids = _ids(plan)
    subset = {fold: ids["ps"][fold] for fold in plan.expected_fold_ids[:2]}
    manifest = _started(
        plan, walk_forward_validation_run_id=ids["wf"], parameter_stability_validation_run_ids_by_fold=subset,
    )
    assert _against(manifest, plan) is None


def test_the_plan_binding_is_pure_and_does_not_mutate_either_object(worlds):
    plan = worlds.plan
    manifest = _complete(plan)
    manifest_before, plan_before = dataclasses.asdict(manifest), dataclasses.asdict(plan)
    for _ in range(2):
        assert _against(manifest, plan) is None
    assert dataclasses.asdict(manifest) == manifest_before and dataclasses.asdict(plan) == plan_before


# ============================================================================================
# Tranche 4 — record pur (17 clés exactes), incompatibilité V1/V2, immutabilité, copies défensives
# ============================================================================================


def _record(manifest):
    return m2.gate_v_campaign_manifest_v2_to_record(manifest)


def _from_record(record):
    return m2.gate_v_campaign_manifest_v2_from_record(record)


def test_the_record_has_exactly_the_17_keys_in_order_with_plain_json_types(worlds):
    manifest = _complete(worlds.plan)
    record = _record(manifest)
    assert tuple(record) == _EXPECTED_FIELDS
    assert type(record) is dict and type(record["parameter_stability_validation_run_ids_by_fold"]) is dict
    assert json.loads(json.dumps(record, sort_keys=True)) == record


def test_a_record_round_trips_to_an_equal_manifest_directly_and_through_json(worlds):
    plan = worlds.plan
    for manifest in (_initial(plan), _started(plan), _complete(plan), _with(_initial(plan), manifest_revision=3)):
        record = _record(manifest)
        assert _from_record(record) == manifest
        assert _from_record(json.loads(json.dumps(record))) == manifest


def test_to_record_refuses_an_invalid_manifest_and_a_non_manifest(worlds):
    for bad in (_with(_initial(worlds.plan), final_holdout_claim_id="x"), None, {}, "manifest", worlds.plan):
        with pytest.raises(ValueError):
            _record(bad)


def test_from_record_requires_the_exact_key_set(worlds):
    record = _record(_complete(worlds.plan))
    for field_name in _EXPECTED_FIELDS:
        missing = {key: value for key, value in record.items() if key != field_name}
        with pytest.raises(ValueError):
            _from_record(missing)
    for extra_key in ("unknown_key", "created_at", "manifest_content_hash", "expected_fold_ids", "status_derived"):
        with pytest.raises(ValueError):
            _from_record({**record, extra_key: 1})
    for not_a_record in (None, [], "record", [(k, v) for k, v in record.items()], 7):
        with pytest.raises(ValueError):
            _from_record(not_a_record)


@pytest.mark.parametrize("bad_version", ["gate_v_campaign_manifest_v1", "gate_v_campaign_manifest_v3", "", None, 2])
def test_from_record_refuses_an_unknown_version_without_any_fallback(worlds, bad_version):
    record = {**_record(_initial(worlds.plan)), "manifest_semantics_version": bad_version}
    with pytest.raises(ValueError):
        _from_record(record)


def test_from_record_revalidates_the_structure_of_the_record_it_receives(worlds):
    record = _record(_complete(worlds.plan))
    forged = [
        {"campaign_id": _flip_last_hex_digit(record["campaign_id"])},
        {"manifest_revision": True},
        {"manifest_revision": -1},
        {"status": "EVIDENCE_COMPLETE_AWAITING_POLICY"},
        {"status": "PASS"},
        {"execution_started": 1},
        {"running": "no"},
        {"technical_failure_reason": ""},
        {"walk_forward_validation_run_id": ""},
        {"parameter_stability_validation_run_ids_by_fold": ["fold_000"]},
        {"parameter_stability_validation_run_ids_by_fold": {"fold_000": 5}},
        {"final_holdout_claim_id": "x"}, {"final_holdout_claim_content_hash": "x"},
        {"holdout_access_event_id": "x"}, {"holdout_access_event_content_hash": "x"},
        {"oos_evidence_validation_run_id": "x"},
        {"execution_started": False},  # preuves référencées avant le démarrage
    ]
    for change in forged:
        with pytest.raises(ValueError):
            _from_record({**record, **change})


def test_a_v1_record_is_refused_by_v2_and_a_v2_record_is_refused_by_v1(worlds):
    v1_manifest = gate_v_campaign.build_gate_v_campaign_manifest(worlds.v1_plan)
    v1_record = dataclasses.asdict(v1_manifest)
    with pytest.raises(ValueError):
        _from_record(v1_record)
    with pytest.raises(ValueError):  # même avec la clé de version V2 ajoutée : jamais de repli ni de fusion
        _from_record({**v1_record, "manifest_semantics_version": m2.GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION})
    v2_record = _record(_initial(worlds.plan))
    with pytest.raises(TypeError):  # le chargeur historique V1 construit `GateVCampaignManifest(**record)` (ADR 21.2)
        gate_v_campaign.GateVCampaignManifest(**v2_record)
    assert set(v1_record).isdisjoint({"manifest_semantics_version", "manifest_revision", "preregistration_id"})


def test_the_pure_conversions_never_touch_the_filesystem(worlds, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("D2 est pure : aucune E/S fichier")
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(os, "replace", forbidden)
    manifest = m2.build_gate_v_campaign_manifest_v2(worlds.plan)
    assert _from_record(_record(manifest)) == manifest
    assert m2.validate_gate_v_campaign_manifest_v2_against_plan(manifest, worlds.plan) is None


# --- Immutabilité et copies défensives du mapping Parameter Stability -----------------------


def test_the_manifest_never_aliases_the_mapping_given_by_the_caller(worlds):
    plan = worlds.plan
    ids = _ids(plan)
    source = {fold: ids["ps"][fold] for fold in plan.expected_fold_ids[:1]}
    manifest = _started(plan, walk_forward_validation_run_id=ids["wf"], parameter_stability_validation_run_ids_by_fold=source)
    snapshot = dict(manifest.parameter_stability_validation_run_ids_by_fold)
    source["evil"] = "evil_run_id"
    source[plan.expected_fold_ids[0]] = "tampered"
    del source[plan.expected_fold_ids[0]]
    assert dict(manifest.parameter_stability_validation_run_ids_by_fold) == snapshot
    assert manifest.parameter_stability_validation_run_ids_by_fold is not source
    assert m2.validate_gate_v_campaign_manifest_v2_against_plan(manifest, plan) is None


def test_a_manifest_rebuilt_from_a_record_never_aliases_the_record(worlds):
    plan = worlds.plan
    record = _record(_complete(plan))
    manifest = _from_record(record)
    snapshot = dict(manifest.parameter_stability_validation_run_ids_by_fold)
    record["parameter_stability_validation_run_ids_by_fold"]["evil"] = "evil_run_id"
    record["parameter_stability_validation_run_ids_by_fold"].clear()
    assert dict(manifest.parameter_stability_validation_run_ids_by_fold) == snapshot
    assert m2.validate_gate_v_campaign_manifest_v2_against_plan(manifest, plan) is None


def test_the_record_returned_by_to_record_is_a_copy(worlds):
    plan = worlds.plan
    manifest = _complete(plan)
    record = _record(manifest)
    record["parameter_stability_validation_run_ids_by_fold"]["evil"] = "evil_run_id"
    record["status"] = "RUNNING"
    assert "evil" not in manifest.parameter_stability_validation_run_ids_by_fold
    assert manifest.status == "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT"
    assert m2.validate_gate_v_campaign_manifest_v2_against_plan(manifest, plan) is None


def test_every_mutation_of_the_stored_mapping_is_refused(worlds):
    mapping = _complete(worlds.plan).parameter_stability_validation_run_ids_by_fold
    first = next(iter(mapping))
    mutations = [
        lambda: mapping.__setitem__("evil", "x"), lambda: mapping.__delitem__(first), lambda: mapping.pop(first),
        lambda: mapping.popitem(), lambda: mapping.clear(), lambda: mapping.update({"evil": "x"}),
        lambda: mapping.setdefault("evil", "x"), lambda: mapping.__ior__({"evil": "x"}),
    ]
    for mutate in mutations:
        with pytest.raises(TypeError):
            mutate()
    assert len(mapping) == 3


def test_copy_deepcopy_and_pickle_keep_an_equal_and_immutable_manifest(worlds):
    import copy
    import pickle

    manifest = _complete(worlds.plan)
    for clone in (copy.copy(manifest), copy.deepcopy(manifest), pickle.loads(pickle.dumps(manifest))):
        assert clone == manifest
        with pytest.raises(TypeError):
            clone.parameter_stability_validation_run_ids_by_fold["evil"] = "x"
        assert m2.validate_gate_v_campaign_manifest_v2_against_plan(clone, worlds.plan) is None


def test_the_campaign_directory_name_length_is_known_without_creating_any_path(worlds):
    """Longueur du seul nom `gate_v_v2_<64 hex>` (le test transversal de chemin complet relève de la Slice D4)."""
    assert len(worlds.plan.campaign_id) == len("gate_v_v2_") + 64 == 74
    assert not os.path.exists(worlds.plan.campaign_id)


# ============================================================================================
# Tranche 5 — architecture : module pur, sans V1, sans E/S, sans D3-D6, sans Claim, surface minimale
# ============================================================================================

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gate_v_campaign_manifest_v2.py",
)
_DECLARED_API = {
    # D2 : type, constantes, builder, validations, record
    "GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION", "GATE_V_CAMPAIGN_V2_STATUSES", "GateVCampaignManifestV2",
    "build_gate_v_campaign_manifest_v2", "validate_gate_v_campaign_manifest_v2_structure",
    "validate_gate_v_campaign_manifest_v2_against_plan", "gate_v_campaign_manifest_v2_to_record",
    "gate_v_campaign_manifest_v2_from_record",
    # D3 : dérivation du statut posé par les marqueurs, six commandes pures, erreur de transition
    "derive_gate_v_campaign_v2_marker_status", "validate_gate_v_campaign_manifest_v2_marker_status",
    "apply_gate_v_campaign_manifest_v2_command", "ManifestTransitionError", "Start", "SetRunning",
    "AttachWalkForward", "AttachMonteCarlo", "AttachParameterStability", "MarkTechnicalFailure",
}


def _module_tree():
    with open(_MODULE_PATH, encoding="utf-8") as handle:
        return ast.parse(handle.read())


def _code_identifiers(tree):
    """Identifiants de CODE (noms, attributs, définitions, imports) — jamais les docstrings ni les chaînes."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add(node.name.split(".")[0])
            names.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_public_surface_is_explicit_and_exactly_the_declared_api():
    assert set(m2.__all__) == _DECLARED_API
    namespace = {}
    exec("from gate_v_campaign_manifest_v2 import *", namespace)  # noqa: S102 — surface d'export seulement
    assert {name for name in namespace if not name.startswith("__")} == _DECLARED_API


def test_the_module_imports_only_the_declared_pure_dependencies_and_never_gate_v_campaign():
    imported = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported == {
        "__future__", "re", "dataclasses", "typing", "atomic_json_store", "gate_v_campaign_plan_v2",
        "gate_v_evidence_completeness_v2", "validation_run",
    }
    # `atomic_json_store` contient aussi les écritures : seul le validateur d'identifiant portable en est importé.
    imported_from_store = {
        alias.name for node in ast.walk(_module_tree())
        if isinstance(node, ast.ImportFrom) and node.module == "atomic_json_store" for alias in node.names
    }
    assert imported_from_store == {"validate_portable_identifier"}


def test_the_module_never_loads_v1_the_oos_runner_or_the_engine_even_transitively():
    code = (
        "import sys, gate_v_campaign_manifest_v2;"
        "banned = {'gate_v_campaign', 'validation_oos', 'engine'};"
        "assert not banned & set(sys.modules), sorted(banned & set(sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=os.path.dirname(_MODULE_PATH), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_the_module_uses_no_filesystem_clock_randomness_or_hashing_api():
    forbidden = {
        "open", "os", "sys", "subprocess", "pathlib", "Path", "shutil", "tempfile", "glob", "json", "hashlib",
        "save_exclusive", "save_atomic_overwrite", "load_json_tolerant", "unlink", "replace", "rename", "mkdir",
        "time", "datetime", "uuid", "random", "print", "input",
    }
    assert not _code_identifiers(_module_tree()) & forbidden


def test_the_module_contains_no_claim_holdout_assessment_or_later_slice_logic():
    forbidden = {
        # Claim / FINAL_HOLDOUT / assessments
        "FinalHoldoutAccessClaim", "HoldoutAccessEvent", "run_gate_v_final_holdout_validation",
        "ValidationAssessment", "GateVPolicyAssessment", "validation_oos", "engine",
        # D4 : persistance, verrou, sentinelle, valeur effective (dépend de technical_failure.json)
        "effective_status", "ManifestWriteError", "ManifestWriteUncertainError", "ManifestLockReleaseError",
        "ManifestLockAcquisitionError", "technical_failure",
        # D5 : vérification des preuves persistées et précondition du Claim
        "assert_gate_v_pre_holdout_evidence_complete", "load_validation_run",
        # D6 : discrimination
        "classify_gate_v_campaign_dir", "GateVCampaignDiscriminationError",
        # Réimplémentation des prédicats de complétude : ils restent ceux de D1
        "walk_forward_evidence_complete_v2", "monte_carlo_evidence_complete_v2",
        "parameter_stability_evidence_complete_v2",
    }
    assert not _code_identifiers(_module_tree()) & forbidden
    for name in (
        "save_gate_v_campaign_manifest_v2", "load_gate_v_campaign_manifest_v2", "classify_gate_v_campaign_dir",
        "acquire_manifest_update_lock", "mark_technical_failure_sentinel",
    ):
        assert not hasattr(m2, name), name


def test_the_proof_identifier_function_and_the_campaign_id_formula_are_reused_never_redefined():
    import gate_v_campaign_plan_v2 as plan_module
    import gate_v_evidence_completeness_v2 as completeness_module

    assert m2.gate_v_v2_validation_run_id is completeness_module.gate_v_v2_validation_run_id
    assert m2.compute_gate_v_campaign_id_v2 is plan_module.compute_gate_v_campaign_id_v2
    defined = {node.name for node in ast.walk(_module_tree()) if isinstance(node, ast.FunctionDef)}
    assert "gate_v_v2_validation_run_id" not in defined and "compute_gate_v_campaign_id_v2" not in defined


def test_the_builder_refuses_a_plan_whose_internal_barriers_fail(worlds):
    tampered = dataclasses.replace(worlds.plan, campaign_id=_flip_last_hex_digit(worlds.plan.campaign_id))
    with pytest.raises(ValueError):
        m2.build_gate_v_campaign_manifest_v2(tampered)


# ============================================================================================
# Tranche 6 — identifiants de preuve DÉTERMINISTES dès la validation structurelle (ADR 0025 §21.4/§21.6)
#   STRUCTURE : relation campagne / type / fold, types, portabilité.   AGAINST_PLAN : membership des folds.
# ============================================================================================

_CYRILLIC_A = "а"  # « а » cyrillique, visuellement identique à « a » latin
_CYRILLIC_O = "о"  # « о » cyrillique
_ZERO_WIDTH_SPACE = "​"
_LONG = "x" * 1_000_000


def _record_of(manifest):
    """Record construit À LA MAIN : `to_record` valide, il ne peut donc pas servir à fabriquer un record forgé."""
    record = {field.name: getattr(manifest, field.name) for field in dataclasses.fields(manifest)}
    record["parameter_stability_validation_run_ids_by_fold"] = dict(
        manifest.parameter_stability_validation_run_ids_by_fold)
    return record


def _refused_by_structure_and_by_from_record(manifest):
    """Refus FERMÉ aux deux points d'entrée, sans jamais appeler `against_plan`."""
    with pytest.raises(ValueError):
        m2.validate_gate_v_campaign_manifest_v2_structure(manifest)
    with pytest.raises(ValueError):
        m2.gate_v_campaign_manifest_v2_from_record(_record_of(manifest))


def _accepted_by_structure_and_by_from_record(manifest):
    assert m2.validate_gate_v_campaign_manifest_v2_structure(manifest) is None
    assert m2.gate_v_campaign_manifest_v2_from_record(_record_of(manifest)) == manifest


def _bad_proof_ids(canonical, other_campaign, wrong_type, lookalike):
    """Identifiants qui ne sont PAS exactement `canonical` : libre, autre campagne, autre type de preuve,
    lookalike Unicode, caractère de largeur nulle, espaces, casse, très long, mauvais types."""
    return {
        "free_form": "free",
        "another_campaign": other_campaign,
        "another_proof_type": wrong_type,
        "unicode_lookalike": lookalike,
        "zero_width_character": canonical + _ZERO_WIDTH_SPACE,
        "leading_space": " " + canonical,
        "trailing_newline": canonical + "\n",
        "upper_case": canonical.upper(),
        "truncated": canonical[:-1],
        "suffix_appended": canonical + "_x",
        "very_long": canonical + _LONG,
        "very_long_free_form": _LONG,
        "integer": 5, "boolean": True, "list": [canonical], "bytes": canonical.encode("ascii"), "dict": {canonical: 1},
    }


def test_a_walk_forward_id_that_is_not_the_deterministic_campaign_id_is_refused_by_the_structure_itself(worlds):
    plan, other = worlds.plan, worlds.other_plan
    ids, other_ids = _ids(plan), _ids(other)
    lookalike = ids["wf"].replace("walk", "w" + _CYRILLIC_A + "lk")
    for name, bad in _bad_proof_ids(ids["wf"], other_ids["wf"], ids["mc"], lookalike).items():
        manifest = _started(plan, walk_forward_validation_run_id=bad)
        try:
            _refused_by_structure_and_by_from_record(manifest)
        except BaseException as exc:  # noqa: BLE001 — ajoute le cas fautif au rapport
            raise AssertionError(f"walk_forward id accepté ou erreur non typée : {name}") from exc


def test_a_monte_carlo_id_that_is_not_the_deterministic_campaign_id_is_refused_by_the_structure_itself(worlds):
    plan, other = worlds.plan, worlds.other_plan
    ids, other_ids = _ids(plan), _ids(other)
    lookalike = ids["mc"].replace("carlo", "c" + _CYRILLIC_A + "rlo")
    for name, bad in _bad_proof_ids(ids["mc"], other_ids["mc"], ids["wf"], lookalike).items():
        manifest = _started(plan, walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=bad)
        try:
            _refused_by_structure_and_by_from_record(manifest)
        except BaseException as exc:  # noqa: BLE001
            raise AssertionError(f"monte_carlo id accepté ou erreur non typée : {name}") from exc


def test_a_parameter_stability_id_that_is_not_the_deterministic_fold_id_is_refused_by_the_structure_itself(worlds):
    plan, other = worlds.plan, worlds.other_plan
    ids, other_ids = _ids(plan), _ids(other)
    first, second = plan.expected_fold_ids[0], plan.expected_fold_ids[1]
    canonical = ids["ps"][first]
    lookalike = canonical.replace("stability", "st" + _CYRILLIC_A + "bility")
    bad_values = _bad_proof_ids(canonical, other_ids["ps"][first], ids["ps"][second], lookalike)
    bad_values.update({"workflow_id": ids["wf"], "monte_carlo_id": ids["mc"], "none": None, "empty": ""})
    for name, bad in bad_values.items():
        manifest = _started(
            plan, walk_forward_validation_run_id=ids["wf"], parameter_stability_validation_run_ids_by_fold={first: bad})
        try:
            _refused_by_structure_and_by_from_record(manifest)
        except BaseException as exc:  # noqa: BLE001
            raise AssertionError(f"parameter_stability id accepté ou erreur non typée : {name}") from exc


def test_a_parameter_stability_fold_id_that_is_not_a_portable_identifier_is_refused_by_the_structure(worlds):
    """Refus par l'ALPHABET et le contrat portable canonique — jamais par une longueur."""
    plan = worlds.plan
    ids = _ids(plan)
    bad_fold_ids = {
        "empty": "", "blank": "   ", "cyrillic_letter": "f" + _CYRILLIC_O + "ld_000", "fullwidth_digit": "fold_00０",
        "zero_width": "fold_000" + _ZERO_WIDTH_SPACE, "slash": "fold/000", "backslash": "fold\\000",
        "dot_dot": "..", "embedded_dot_dot": "fold..000", "space": "fold 000", "colon": "fold:000",
        "newline": "fold_000\n", "star": "fold*", "integer": 1, "none": None, "tuple": ("fold_000",),
        # Très long ET contenant un caractère interdit : refusé par l'alphabet, pas par sa taille.
        "very_long_with_a_slash": "f" * 1_000_000 + "/", "very_long_with_a_cyrillic_letter": "f" * 100_000 + _CYRILLIC_O,
    }
    for name, fold_id in bad_fold_ids.items():
        run_id = f"{plan.campaign_id}_parameter_stability_{fold_id}" if isinstance(fold_id, str) else "free"
        manifest = _started(
            plan, walk_forward_validation_run_id=ids["wf"], parameter_stability_validation_run_ids_by_fold={fold_id: run_id})
        try:
            _refused_by_structure_and_by_from_record(manifest)
        except BaseException as exc:  # noqa: BLE001
            raise AssertionError(f"fold_id accepté ou erreur non typée : {name}") from exc


def test_a_parameter_stability_id_must_match_the_key_it_is_stored_under(worlds):
    plan, other = worlds.plan, worlds.other_plan
    ids = _ids(plan)
    first, second = plan.expected_fold_ids[0], plan.expected_fold_ids[1]
    mismatched = {
        "id_of_another_fold": {first: ids["ps"][second]},
        "swapped_folds": {first: ids["ps"][second], second: ids["ps"][first]},
        "one_good_one_foreign": {first: ids["ps"][first], second: "free"},
        "campaign_of_another_plan": {first: _ids(other)["ps"][first]},
    }
    for name, mapping in mismatched.items():
        manifest = _started(plan, walk_forward_validation_run_id=ids["wf"], parameter_stability_validation_run_ids_by_fold=mapping)
        try:
            _refused_by_structure_and_by_from_record(manifest)
        except BaseException as exc:  # noqa: BLE001
            raise AssertionError(f"identifiant PS non lié à sa clé accepté : {name}") from exc


def test_canonical_proof_ids_stay_structurally_valid_for_every_state_and_round_trip(worlds):
    plan = worlds.plan
    ids = _ids(plan)
    folds = plan.expected_fold_ids
    states = {
        "initial": _initial(plan),
        "started_incomplete": _started(plan),
        "walk_forward_attached": _started(plan, walk_forward_validation_run_id=ids["wf"]),
        "walk_forward_and_monte_carlo": _started(
            plan, walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=ids["mc"]),
        "walk_forward_monte_carlo_and_some_parameter_stability": _started(
            plan, walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=ids["mc"],
            parameter_stability_validation_run_ids_by_fold={folds[0]: ids["ps"][folds[0]]}),
        "complete_awaiting_final_holdout": _complete(plan),
    }
    for name, manifest in states.items():
        _accepted_by_structure_and_by_from_record(manifest)
        record = m2.gate_v_campaign_manifest_v2_to_record(manifest)
        assert m2.gate_v_campaign_manifest_v2_from_record(record) == manifest, name
        assert m2.gate_v_campaign_manifest_v2_from_record(json.loads(json.dumps(record))) == manifest, name
        assert m2.validate_gate_v_campaign_manifest_v2_against_plan(manifest, plan) is None, name


def test_the_structural_rule_agrees_with_the_d1_function_for_every_expected_fold(worlds):
    """Le contrôle structurel interne n'est PAS une seconde API : il doit rester identique à D1, qui reste l'autorité
    (`against_plan`). Toute dérive du format entre D1 et D2 casse ce test."""
    plan = worlds.plan
    wf = gate_v_v2_validation_run_id(plan, _WF)
    mc = gate_v_v2_validation_run_id(plan, _MC)
    _accepted_by_structure_and_by_from_record(_started(
        plan, walk_forward_validation_run_id=wf, monte_carlo_validation_run_id=mc))
    for fold_id in plan.expected_fold_ids:
        canonical = gate_v_v2_validation_run_id(plan, _PS, fold_id=fold_id)
        _accepted_by_structure_and_by_from_record(_started(
            plan, walk_forward_validation_run_id=wf, parameter_stability_validation_run_ids_by_fold={fold_id: canonical}))
        for tampered in (canonical + "0", canonical[:-1], canonical.replace("_parameter_stability_", "_monte_carlo_")):
            _refused_by_structure_and_by_from_record(_started(
                plan, walk_forward_validation_run_id=wf,
                parameter_stability_validation_run_ids_by_fold={fold_id: tampered}))


def test_a_syntactically_valid_fold_outside_the_plan_is_structurally_valid_but_refused_by_the_plan_binding(worlds):
    """Frontière D2 : la structure ne connaît pas `expected_fold_ids` ; `against_plan` reste l'autorité du membership."""
    plan, other = worlds.plan, worlds.other_plan
    ids = _ids(plan)
    for fold_id in ("fold_999", "fold_1000", "fold-x.y_z", "f" * 129, "f" * 100_000):
        manifest = _started(
            plan, walk_forward_validation_run_id=ids["wf"],
            parameter_stability_validation_run_ids_by_fold={fold_id: f"{plan.campaign_id}_parameter_stability_{fold_id}"})
        _accepted_by_structure_and_by_from_record(manifest)
        with pytest.raises(ValueError, match="étranger aux folds attendus"):
            _against(manifest, plan)
    # Un fold de l'AUTRE plan n'est pas davantage un fold de CE plan (même nom de fold, autre campagne).
    assert other.expected_fold_ids == plan.expected_fold_ids


def test_the_structure_imposes_no_local_length_rule_on_a_portable_fold_id(worlds):
    """Contrat canonique = `validate_portable_identifier` (alphabet `[A-Za-z0-9_.-]+`, ni `/`, ni `\\`, ni `..`),
    SANS longueur maximale. D2 n'invente pas une règle plus stricte que ce contrat, que `GateVCampaignPlanV2` et D1.
    (Le risque de longueur de chemin Windows relève de D4, où les chemins sont matérialisés.)"""
    plan = worlds.plan
    ids = _ids(plan)
    for length in (128, 129, 255, 1_000, 100_000):
        fold_id = "f" * length
        run_id = f"{plan.campaign_id}_parameter_stability_{fold_id}"
        manifest = _started(
            plan, walk_forward_validation_run_id=ids["wf"], parameter_stability_validation_run_ids_by_fold={fold_id: run_id})
        _accepted_by_structure_and_by_from_record(manifest)
        record = m2.gate_v_campaign_manifest_v2_to_record(manifest)
        assert m2.gate_v_campaign_manifest_v2_from_record(json.loads(json.dumps(record))) == manifest
        with pytest.raises(ValueError, match="étranger aux folds attendus"):  # fold étranger : le membership décide
            _against(manifest, plan)
        # Le lien clé / identifiant reste strict quelle que soit la longueur.
        for wrong_run_id in (run_id + "x", run_id[:-1], f"{plan.campaign_id}_parameter_stability_{fold_id}_x"):
            _refused_by_structure_and_by_from_record(_started(
                plan, walk_forward_validation_run_id=ids["wf"],
                parameter_stability_validation_run_ids_by_fold={fold_id: wrong_run_id}))
        # Et l'alphabet reste décisif : la même longueur avec un caractère interdit est refusée.
        for forbidden in ("/", "\\", " ", _CYRILLIC_O, ".."):
            bad_fold = "f" * length + forbidden
            _refused_by_structure_and_by_from_record(_started(
                plan, walk_forward_validation_run_id=ids["wf"],
                parameter_stability_validation_run_ids_by_fold={
                    bad_fold: f"{plan.campaign_id}_parameter_stability_{bad_fold}"}))


def test_the_module_source_carries_no_local_fold_id_length_constant():
    """Pas de constante de longueur : la garantie comportementale est portée par
    `test_the_structure_imposes_no_local_length_rule_on_a_portable_fold_id` (un `len()` légitime ailleurs, p. ex. en D3,
    ne doit pas casser ce test)."""
    identifiers = _code_identifiers(_module_tree())
    assert not {name for name in identifiers if "MAX" in name.upper() and "LEN" in name.upper()}


@pytest.mark.parametrize("diverging_type", [_WF, _MC, _PS])
def test_the_plan_binding_keeps_the_d1_function_as_its_canonical_authority(worlds, monkeypatch, diverging_type):
    """Si la fonction canonique de D1 change de format, `against_plan` doit le voir : il la consulte pour chaque
    type de preuve au lieu de se contenter du contrôle structurel interne (qui ne doit donc jamais la remplacer)."""
    plan = worlds.plan
    manifest = _complete(plan)
    assert _against(manifest, plan) is None

    def diverging(plan_arg, validation_type, *, fold_id=None):
        canonical = gate_v_v2_validation_run_id(plan_arg, validation_type, fold_id=fold_id)
        return canonical + "X" if validation_type == diverging_type else canonical
    monkeypatch.setattr(m2, "gate_v_v2_validation_run_id", diverging)
    with pytest.raises(ValueError):
        _against(manifest, plan)


def test_the_structural_checks_do_not_need_a_plan_and_stay_pure_and_deterministic(worlds):
    plan = worlds.plan
    manifest = _complete(plan)
    before = dataclasses.asdict(manifest)
    for _ in range(2):
        _accepted_by_structure_and_by_from_record(manifest)
    assert dataclasses.asdict(manifest) == before


# ============================================================================================
# Tranche 7 — D3 : statut posé par les marqueurs, sur la vue des SEULES preuves RÉFÉRENCÉES
#   (preuves = ValidationRun DÉJÀ chargées par l'appelant ; D3 ne lit aucun fichier)
# ============================================================================================

_COMPLETED_AT = "2025-07-01T00:00:00+00:00"
_SUMMARY = PercentileDistributionSummary(0.1, 0.2, 0.3, 0.4, 0.5)


def _synthetic_proofs(plan, split):
    """WF + MC + une PS par fold attendu, COMPLÈTES (D1 le confirme ci-dessous), sans aucun moteur.
    Sélection TRAIN distincte par fold : une PS rapprochée du mauvais fold source ne passerait pas."""
    definitions = compute_fold_definitions(split.validation, plan.walk_forward_specification, plan.readiness_spec)
    results = tuple(
        FoldResult(
            fold_id=definition.fold_id, definition=definition,
            selection=FoldSelection(
                fold_id=definition.fold_id, selected_params={"lookback": 12 + index},
                selected_params_hash="synthetic_hash", score_train=1.0 + index, rank_in_train=1,
                train_candidates_evaluated=2 + index, train_candidates_unique=2 + index,
                train_candidates_eligible=2 + index, search_space_hash=plan.search_space_hash,
                algorithm=plan.search_mode, fold_seed=None,
            ),
            n_trades=0, net_ret_pct=0.0, max_dd_pct=None, profit_factor=None, win_rate=None, expectancy=None,
            score_test=0.0, zero_trade_oos=True, forced_closes=0, coverage_bars=1,
        ) for index, definition in enumerate(definitions)
    )
    ids = _ids(plan)
    common = dict(
        research_run_id=plan.research_run_id, split_plan_id=plan.split_plan_id,
        dataset_snapshot_id=plan.dataset_snapshot_id, strategy_name=plan.strategy_name,
        strategy_params=dict(plan.base_params), completed_at=_COMPLETED_AT,
    )
    proofs = {
        ids["wf"]: build_validation_run(
            validation_run_id=ids["wf"], validation_type=_WF, specification=plan.walk_forward_specification,
            evidence=WalkForwardEvidence(results, build_aggregate_result(results), "completed", "INCONCLUSIVE", ()),
            **common),
        ids["mc"]: build_validation_run(
            validation_run_id=ids["mc"], validation_type=_MC,
            specification=build_monte_carlo_specification(ids["wf"], True),
            evidence=MonteCarloEvidence(
                n_input_trades=0, zero_trade_input=True, observed_net_ret_pct=None,
                observed_max_dd_trade_close_basis_pct=None, observed_lag1_autocorrelation=None,
                observed_longest_losing_streak=None, sequence_risk_max_dd_trade_close_basis_pct=None,
                sequence_risk_longest_losing_streak=None, sampling_uncertainty_net_ret_pct=None,
                sampling_uncertainty_max_dd_trade_close_basis_pct=None, execution_status="completed",
                scientific_verdict="INCONCLUSIVE", verdict_reasons=()),
            **common),
    }
    for index, fold_id in enumerate(plan.expected_fold_ids):
        proofs[ids["ps"][fold_id]] = build_validation_run(
            validation_run_id=ids["ps"][fold_id], validation_type=_PS,
            specification=build_parameter_stability_specification(
                ids["wf"], plan.search_mode, True, source_fold_id=fold_id),
            evidence=ParameterStabilityEvidence(
                n_candidates_total=2 + index, zero_candidates_input=False, search_mode=plan.search_mode,
                neighborhood_applicability="local_neighborhood_available", best_score=1.0 + index,
                best_params={"lookback": 12 + index}, sensitivity={"lookback": 0.0},
                sensitivity_sample_size_by_param={"lookback": 2}, n_neighbors_total_by_param={"lookback": 1},
                n_neighbors_rejected_by_param={"lookback": 0}, degradation_by_param={"lookback": _SUMMARY},
                degradation_points_by_param={"lookback": _SUMMARY}, n_hamming_le_2_total=1,
                n_hamming_le_2_rejected=0, degradation_hamming_le_2=_SUMMARY, execution_status="completed",
                scientific_verdict="INCONCLUSIVE", verdict_reasons=()),
            **common)
    return proofs


@pytest.fixture(scope="module")
def proofs(worlds):
    return _synthetic_proofs(worlds.plan, worlds.split)


def _evidence_edit(**changes):
    return lambda run: dataclasses.replace(run, evidence=dataclasses.replace(run.evidence, **changes))


def _poor_parameter_stability(run):
    """Preuve COHÉRENTE mais de qualité insuffisante : voisinage entièrement rejeté (D1 : incomplète, pas une erreur)."""
    return _evidence_edit(n_neighbors_rejected_by_param={"lookback": 1})(run)


def _derive(plan, manifest, evidence):
    return m2.derive_gate_v_campaign_v2_marker_status(plan, manifest, evidence)


def test_the_synthetic_proofs_are_complete_for_d1_so_the_complete_status_tests_are_meaningful(worlds, proofs):
    from gate_v_evidence_completeness_v2 import evaluate_pre_holdout_evidence_v2

    facts = evaluate_pre_holdout_evidence_v2(worlds.plan, dict(proofs))
    assert facts.pre_holdout_evidence_complete is True
    assert len(proofs) == 2 + len(worlds.plan.expected_fold_ids)


def test_marker_status_follows_the_exact_priority_failure_running_ready_then_evidence(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    with_references = dict(
        walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=ids["mc"],
        parameter_stability_validation_run_ids_by_fold=ids["ps"],
    )
    assert _derive(plan, _initial(plan), {}) == "READY_FOR_EXECUTION"
    assert _derive(plan, _started(plan), {}) == "EVIDENCE_INCOMPLETE"
    assert _derive(plan, _with(_initial(plan), execution_started=True, running=True, status="RUNNING"), {}) == "RUNNING"
    assert _derive(plan, _with(
        _initial(plan), execution_started=True, status="TECHNICAL_FAILURE", technical_failure_reason="boom",
    ), {}) == "TECHNICAL_FAILURE"
    # La priorité tient aussi quand toutes les preuves sont référencées et complètes.
    running_with_everything = _with(
        _initial(plan), execution_started=True, running=True, status="RUNNING", **with_references)
    assert _derive(plan, running_with_everything, dict(proofs)) == "RUNNING"
    failed_with_everything = _with(
        _initial(plan), execution_started=True, status="TECHNICAL_FAILURE", technical_failure_reason="boom",
        **with_references)
    assert _derive(plan, failed_with_everything, dict(proofs)) == "TECHNICAL_FAILURE"
    assert _derive(plan, _complete(plan), dict(proofs)) == "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT"


def test_a_proof_present_in_the_mapping_but_not_referenced_by_the_manifest_never_counts(worlds, proofs):
    """Point critique : une preuve écrite mais jamais adoptée ne doit pas faire passer le statut à « complet »."""
    plan = worlds.plan
    ids = _ids(plan)
    everything = dict(proofs)
    only_wf = _started(plan, walk_forward_validation_run_id=ids["wf"])
    wf_and_mc = _started(plan, walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=ids["mc"])
    some_folds = _started(
        plan, walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=ids["mc"],
        parameter_stability_validation_run_ids_by_fold={f: ids["ps"][f] for f in plan.expected_fold_ids[:-1]})
    for manifest in (_started(plan), only_wf, wf_and_mc, some_folds):
        assert _derive(plan, manifest, everything) == "EVIDENCE_INCOMPLETE"
    # Même une preuve non référencée INCOHÉRENTE est ignorée (elle n'a aucune autorité), sans erreur.
    foreign_unreferenced = dataclasses.replace(proofs[ids["mc"]], strategy_name="Other Strategy")
    with_poison = dict(proofs)
    with_poison[ids["mc"]] = foreign_unreferenced
    assert _derive(plan, only_wf, with_poison) == "EVIDENCE_INCOMPLETE"
    # Une entrée libre dans le mapping n'est jamais une référence.
    with_noise = {**proofs, "free_form_id": proofs[ids["wf"]], 7: None}
    assert _derive(plan, only_wf, with_noise) == "EVIDENCE_INCOMPLETE"


def test_a_referenced_proof_absent_from_the_mapping_is_a_closed_error_not_an_incomplete_status(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]
    manifest = _complete(plan)
    for missing in (ids["wf"], ids["mc"], ids["ps"][first]):
        mapping = {key: run for key, run in proofs.items() if key != missing}
        with pytest.raises(ValueError):
            _derive(plan, manifest, mapping)
    with pytest.raises(ValueError):
        _derive(plan, manifest, {})
    # Un Manifest « en avance sur les preuves » reste refusé pour RUNNING ; seul l'état TERMINAL d'échec technique
    # fait exception (il doit rester dérivable quand une preuve est précisément devenue inutilisable) : voir
    # `test_a_terminal_technical_failure_stays_derivable_without_any_usable_proof`.
    running = _with(
        _initial(plan), execution_started=True, running=True, status="RUNNING", walk_forward_validation_run_id=ids["wf"])
    with pytest.raises(ValueError):
        _derive(plan, running, {})


def test_missing_poor_or_incomplete_referenced_proofs_leave_the_campaign_incomplete(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    first, last = plan.expected_fold_ids[0], plan.expected_fold_ids[-1]
    manifest = _complete(plan)

    def mapping_with(proof_id, edit):
        return {**proofs, proof_id: edit(proofs[proof_id])}
    cases = {
        "poor_parameter_stability_first_fold": mapping_with(ids["ps"][first], _poor_parameter_stability),
        "poor_parameter_stability_last_fold": mapping_with(ids["ps"][last], _poor_parameter_stability),
        "walk_forward_not_completed": mapping_with(ids["wf"], _evidence_edit(execution_status="failed")),
        "monte_carlo_not_completed": mapping_with(ids["mc"], _evidence_edit(execution_status="failed")),
    }
    for name, mapping in cases.items():
        assert _derive(plan, manifest, mapping) == "EVIDENCE_INCOMPLETE", name
    # PS manquante côté Manifest (jamais attachée) : incomplet ; ce n'est PAS une erreur.
    missing_fold = _started(
        plan, walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=ids["mc"],
        parameter_stability_validation_run_ids_by_fold={f: ids["ps"][f] for f in plan.expected_fold_ids[:-1]})
    assert _derive(plan, missing_fold, dict(proofs)) == "EVIDENCE_INCOMPLETE"


def test_an_incoherent_or_foreign_referenced_proof_is_an_error_never_a_status(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]
    manifest = _complete(plan)
    for proof_id in (ids["wf"], ids["mc"], ids["ps"][first]):
        for edit in (
            lambda run: dataclasses.replace(run, strategy_name="Other Strategy"),
            lambda run: dataclasses.replace(run, dataset_snapshot_id=_FOREIGN_SNAPSHOT_ID),
            lambda run: dataclasses.replace(run, research_run_id="other_research"),
            lambda run: dataclasses.replace(run, status="failed"),
            lambda run: dataclasses.replace(run, validation_run_id="free_form_id"),
            _evidence_edit(scientific_verdict="PASS"),
        ):
            with pytest.raises(ValueError):
                _derive(plan, manifest, {**proofs, proof_id: edit(proofs[proof_id])})


_FOREIGN_SNAPSHOT_ID = "synthetic_csv:sha256:" + "cd" * 32


def test_marker_status_never_mutates_its_inputs_and_keeps_no_alias(worlds, proofs):
    plan = worlds.plan
    manifest = _complete(plan)
    mapping = dict(proofs)
    manifest_before, mapping_before = dataclasses.asdict(manifest), dict(mapping)
    proofs_before = {key: dataclasses.asdict(run) for key, run in mapping.items()}
    for _ in range(2):
        assert _derive(plan, manifest, mapping) == "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT"
    assert dataclasses.asdict(manifest) == manifest_before and mapping == mapping_before
    assert {key: dataclasses.asdict(run) for key, run in mapping.items()} == proofs_before


def test_marker_status_refuses_bad_plans_manifests_and_mappings(worlds, proofs):
    plan = worlds.plan
    manifest = _complete(plan)
    for bad_plan in (worlds.v1_plan, None, {}, "plan"):
        with pytest.raises(ValueError):
            _derive(bad_plan, manifest, dict(proofs))
    v1_manifest = gate_v_campaign.build_gate_v_campaign_manifest(worlds.v1_plan)
    for bad_manifest in (v1_manifest, None, {}, "manifest", _with(manifest, final_holdout_claim_id="x"),
                         _initial(worlds.other_plan)):
        with pytest.raises(ValueError):
            _derive(plan, bad_manifest, dict(proofs))
    for bad_mapping in (None, [], "mapping", [proofs]):
        with pytest.raises(ValueError):
            _derive(plan, manifest, bad_mapping)


def test_the_persisted_status_must_equal_the_derived_marker_status(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]

    def check(manifest, mapping=None):
        return m2.validate_gate_v_campaign_manifest_v2_marker_status(
            manifest, plan, dict(proofs) if mapping is None else mapping)
    assert check(_complete(plan)) is None
    assert check(_initial(plan), {}) is None
    # Structurellement valide (références + marqueurs) mais le statut persisté n'est pas celui des preuves.
    understated = _with(_complete(plan), status="EVIDENCE_INCOMPLETE")
    assert m2.validate_gate_v_campaign_manifest_v2_against_plan(understated, plan) is None
    with pytest.raises(ValueError):
        check(understated)
    overstated = _complete(plan)
    with pytest.raises(ValueError):
        check(overstated, {**proofs, ids["ps"][first]: _poor_parameter_stability(proofs[ids["ps"][first]])})
    assert check(_with(_complete(plan), status="EVIDENCE_INCOMPLETE"),
                 {**proofs, ids["ps"][first]: _poor_parameter_stability(proofs[ids["ps"][first]])}) is None
    for status in sorted(m2.GATE_V_CAMPAIGN_V2_STATUSES - {"EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT"}):
        with pytest.raises(ValueError):
            check(_with(_complete(plan), status=status))


# ============================================================================================
# Tranche 8 — D3 : six commandes pures, expected_revision obligatoire, +1 exact, idempotence, terminalité
# ============================================================================================

_COMPLETE = "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT"


_CURRENT_REVISION = object()  # sentinelle : `None` doit pouvoir être transmis tel quel (cas invalide)


def _step(plan, manifest, command, evidence, *, expected_revision=_CURRENT_REVISION):
    revision = manifest.manifest_revision if expected_revision is _CURRENT_REVISION else expected_revision
    return m2.apply_gate_v_campaign_manifest_v2_command(
        plan, manifest, command, evidence, expected_revision=revision)


def _api_started(plan):
    return _step(plan, _initial(plan), m2.Start(), {})


def _api_with_walk_forward(plan, proofs):
    return _step(plan, _api_started(plan), m2.AttachWalkForward(_ids(plan)["wf"]), dict(proofs))


def _api_path(plan, proofs):
    """Start -> WF -> MC -> PS de chaque fold, par l'API : la liste COMPLÈTE des manifests successifs."""
    ids = _ids(plan)
    path = [_initial(plan), _api_started(plan)]
    commands = [m2.AttachWalkForward(ids["wf"]), m2.AttachMonteCarlo(ids["mc"])]
    commands += [m2.AttachParameterStability(fold, ids["ps"][fold]) for fold in plan.expected_fold_ids]
    for command in commands:
        path.append(_step(plan, path[-1], command, dict(proofs)))
    return path


def test_the_six_commands_are_a_closed_set_of_frozen_dataclasses_and_the_transition_error_is_a_value_error():
    expected_fields = {
        m2.Start: (), m2.SetRunning: ("running",), m2.AttachWalkForward: ("run_id",),
        m2.AttachMonteCarlo: ("run_id",), m2.AttachParameterStability: ("fold_id", "run_id"),
        m2.MarkTechnicalFailure: ("reason",),
    }
    for command_class, names in expected_fields.items():
        assert dataclasses.is_dataclass(command_class) and command_class.__dataclass_params__.frozen is True
        assert tuple(field.name for field in dataclasses.fields(command_class)) == names
    assert issubclass(m2.ManifestTransitionError, ValueError)
    command = m2.AttachWalkForward("x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        command.run_id = "y"


def test_only_the_six_command_types_are_accepted_never_a_free_form_mutation(worlds, proofs):
    plan = worlds.plan
    manifest = _api_started(plan)

    class SneakyStart(m2.Start):
        pass
    for bad in (None, {}, {"command": "Start"}, "Start", ("Start",), 7, object(), m2.Start, SneakyStart(),
                lambda manifest: manifest, dataclasses.replace(manifest)):
        with pytest.raises(ValueError):
            _step(plan, manifest, bad, dict(proofs))


def test_expected_revision_is_mandatory_a_non_boolean_integer_and_compared_before_anything_else(worlds, proofs):
    plan = worlds.plan
    manifest = _api_started(plan)  # révision 1
    with pytest.raises(TypeError):  # mot-clé obligatoire : jamais de valeur par défaut silencieuse
        m2.apply_gate_v_campaign_manifest_v2_command(plan, manifest, m2.Start(), {})
    for bad in (True, False, "1", 1.0, None, [1], -1):
        with pytest.raises(ValueError) as excinfo:
            _step(plan, manifest, m2.Start(), {}, expected_revision=bad)
        # Un type invalide n'est PAS une révision périmée : erreur de contrat, pas de transition.
        assert not isinstance(excinfo.value, m2.ManifestTransitionError), bad
    for stale in (0, 2, 99):
        with pytest.raises(m2.ManifestTransitionError):
            _step(plan, manifest, m2.SetRunning(True), {}, expected_revision=stale)


def test_a_stale_revision_is_refused_even_for_a_command_that_would_be_idempotent(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    manifest = _api_with_walk_forward(plan, proofs)  # révision 2
    assert manifest.manifest_revision == 2
    idempotent_commands = (
        m2.Start(), m2.SetRunning(False), m2.AttachWalkForward(ids["wf"]),
    )
    for command in idempotent_commands:
        assert _step(plan, manifest, command, dict(proofs)) is manifest  # sanity : réellement idempotente
        for stale in (0, 1, 3):
            with pytest.raises(m2.ManifestTransitionError):
                _step(plan, manifest, command, dict(proofs), expected_revision=stale)


def test_the_command_application_refuses_a_bad_plan_a_bad_manifest_and_a_bad_mapping(worlds, proofs):
    plan = worlds.plan
    manifest = _api_started(plan)
    for bad_plan in (worlds.v1_plan, None, {}, "plan"):
        with pytest.raises(ValueError):
            _step(bad_plan, manifest, m2.Start(), {}, expected_revision=1)
    v1_manifest = gate_v_campaign.build_gate_v_campaign_manifest(worlds.v1_plan)
    for bad_manifest in (v1_manifest, None, {}, "manifest", _initial(worlds.other_plan),
                         _with(manifest, final_holdout_claim_id="x"), _with(manifest, status="PASS")):
        with pytest.raises(ValueError):
            _step(plan, bad_manifest, m2.Start(), {}, expected_revision=1)
    for bad_mapping in (None, [], "mapping"):
        with pytest.raises(ValueError):
            _step(plan, manifest, m2.Start(), bad_mapping)


# --- Start -----------------------------------------------------------------------------------


def test_start_marks_the_campaign_started_once_with_exactly_one_revision(worlds):
    plan = worlds.plan
    initial = _initial(plan)
    started = _step(plan, initial, m2.Start(), {})
    assert started.execution_started is True and started.running is False
    assert started.status == "EVIDENCE_INCOMPLETE"
    assert started.manifest_revision == initial.manifest_revision + 1 == 1
    assert started.technical_failure_reason is None
    assert started.walk_forward_validation_run_id is None and started.monte_carlo_validation_run_id is None
    assert dict(started.parameter_stability_validation_run_ids_by_fold) == {}
    for name in _RESERVED_FIELDS:
        assert getattr(started, name) is None
    assert m2.validate_gate_v_campaign_manifest_v2_against_plan(started, plan) is None
    assert initial.execution_started is False and initial.manifest_revision == 0  # entrée intacte


def test_start_replay_is_idempotent_and_keeps_every_reference(worlds, proofs):
    plan = worlds.plan
    started = _api_started(plan)
    assert _step(plan, started, m2.Start(), {}) is started
    path = _api_path(plan, proofs)
    complete = path[-1]
    replay = _step(plan, complete, m2.Start(), dict(proofs))
    assert replay is complete and replay.manifest_revision == complete.manifest_revision
    assert replay.walk_forward_validation_run_id and replay.monte_carlo_validation_run_id
    assert set(replay.parameter_stability_validation_run_ids_by_fold) == set(plan.expected_fold_ids)


# --- SetRunning ------------------------------------------------------------------------------


def test_set_running_requires_a_started_campaign_and_a_real_boolean(worlds):
    plan = worlds.plan
    for flag in (True, False):
        with pytest.raises(m2.ManifestTransitionError):
            _step(plan, _initial(plan), m2.SetRunning(flag), {})
    started = _api_started(plan)
    for bad in (1, 0, "True", None, [True]):
        with pytest.raises(ValueError):
            _step(plan, started, m2.SetRunning(bad), {})


def test_set_running_true_then_false_changes_the_status_and_replays_are_idempotent(worlds, proofs):
    plan = worlds.plan
    started = _api_started(plan)
    running = _step(plan, started, m2.SetRunning(True), {})
    assert running.running is True and running.status == "RUNNING" and running.manifest_revision == 2
    assert _step(plan, running, m2.SetRunning(True), {}) is running
    stopped = _step(plan, running, m2.SetRunning(False), {})
    assert stopped.running is False and stopped.status == "EVIDENCE_INCOMPLETE" and stopped.manifest_revision == 3
    assert _step(plan, stopped, m2.SetRunning(False), {}) is stopped  # déjà faux : idempotence exacte
    assert _step(plan, started, m2.SetRunning(False), {}) is started


def test_set_running_false_rederives_the_status_from_the_referenced_proofs_and_never_drops_a_reference(worlds, proofs):
    plan = worlds.plan
    complete = _api_path(plan, proofs)[-1]
    running = _step(plan, complete, m2.SetRunning(True), dict(proofs))
    assert running.status == "RUNNING"
    for name in ("walk_forward_validation_run_id", "monte_carlo_validation_run_id"):
        assert getattr(running, name) == getattr(complete, name)
    stopped = _step(plan, running, m2.SetRunning(False), dict(proofs))
    assert stopped.status == _COMPLETE and stopped.running is False
    assert stopped.manifest_revision == complete.manifest_revision + 2
    assert dict(stopped.parameter_stability_validation_run_ids_by_fold) == dict(
        complete.parameter_stability_validation_run_ids_by_fold)


# --- AttachWalkForward -----------------------------------------------------------------------


def test_attach_walk_forward_requires_a_started_campaign_the_deterministic_id_and_a_scoped_proof(worlds, proofs):
    plan, other = worlds.plan, worlds.other_plan
    ids = _ids(plan)
    with pytest.raises(m2.ManifestTransitionError):  # avant Start
        _step(plan, _initial(plan), m2.AttachWalkForward(ids["wf"]), dict(proofs))
    started = _api_started(plan)
    for bad_id in ("free_form_id", _ids(other)["wf"], ids["mc"], "", None, 5):
        with pytest.raises(ValueError):
            _step(plan, started, m2.AttachWalkForward(bad_id), {**proofs, "free_form_id": proofs[ids["wf"]]})
    with pytest.raises(ValueError):  # preuve ABSENTE du mapping
        _step(plan, started, m2.AttachWalkForward(ids["wf"]), {})
    foreign_edits = (
        lambda run: dataclasses.replace(run, strategy_name="Other Strategy"),
        lambda run: dataclasses.replace(run, dataset_snapshot_id=_FOREIGN_SNAPSHOT_ID),
        lambda run: dataclasses.replace(run, research_run_id="other_research"),
        lambda run: dataclasses.replace(run, status="failed"),
        lambda run: dataclasses.replace(run, validation_run_id="free_form_id"),
        _evidence_edit(scientific_verdict="PASS"),
    )
    for edit in foreign_edits:
        with pytest.raises(ValueError):
            _step(plan, started, m2.AttachWalkForward(ids["wf"]), {**proofs, ids["wf"]: edit(proofs[ids["wf"]])})


def test_attach_refusals_state_their_reason_so_a_redundant_guard_cannot_hide_behind_another(worlds, proofs):
    """Les refus d'un `Attach…` viennent de plusieurs gardes qui se recouvrent (identifiant, présence, scope D1,
    fold attendu) : on fige ici la RAISON de chacun pour qu'aucune garde ne puisse disparaître sans qu'un test le voie."""
    plan = worlds.plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]
    started = _api_started(plan)
    with_wf = _api_with_walk_forward(plan, proofs)
    free_form = {**proofs, "free_form_id": proofs[ids["wf"]]}
    with pytest.raises(ValueError, match="identifiant déterministe"):
        _step(plan, started, m2.AttachWalkForward("free_form_id"), free_form)
    with pytest.raises(ValueError, match="identifiant déterministe"):
        _step(plan, with_wf, m2.AttachMonteCarlo("free_form_id"), {**free_form, "free_form_id": proofs[ids["mc"]]})
    with pytest.raises(ValueError, match="identifiant déterministe"):
        _step(plan, with_wf, m2.AttachParameterStability(first, "free_form_id"), free_form)
    for command, base in (
        (m2.AttachWalkForward(ids["wf"]), started),
        (m2.AttachMonteCarlo(ids["mc"]), with_wf),
        (m2.AttachParameterStability(first, ids["ps"][first]), with_wf),
    ):
        only_what_is_referenced = {key: run for key, run in proofs.items() if key == ids["wf"] and base is with_wf}
        with pytest.raises(ValueError, match="n'est pas dans les preuves fournies"):
            _step(plan, base, command, only_what_is_referenced)
    with pytest.raises(ValueError, match="étranger aux folds attendus"):
        _step(plan, with_wf, m2.AttachParameterStability("fold_999", f"{plan.campaign_id}_parameter_stability_fold_999"),
              dict(proofs))
    with pytest.raises(m2.ManifestTransitionError, match="Walk-Forward doit être rattachée"):
        _step(plan, started, m2.AttachMonteCarlo(ids["mc"]), dict(proofs))
    with pytest.raises(m2.ManifestTransitionError, match="ne se remplace jamais"):
        _step(plan, with_wf, m2.AttachWalkForward("free_form_id"), free_form)


def test_attach_walk_forward_attaches_clears_running_in_the_same_version_and_adds_one_revision(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    running = _step(plan, _api_started(plan), m2.SetRunning(True), {})  # révision 2, running
    attached = _step(plan, running, m2.AttachWalkForward(ids["wf"]), dict(proofs))
    assert attached.walk_forward_validation_run_id == ids["wf"]
    assert attached.running is False and attached.status == "EVIDENCE_INCOMPLETE"
    assert attached.manifest_revision == running.manifest_revision + 1 == 3  # une seule unité, jamais +2
    assert m2.validate_gate_v_campaign_manifest_v2_marker_status(attached, plan, dict(proofs)) is None
    assert running.running is True and running.walk_forward_validation_run_id is None  # entrée intacte


def test_attach_walk_forward_replay_is_idempotent_and_a_replacement_is_a_transition_error(worlds, proofs):
    plan, other = worlds.plan, worlds.other_plan
    ids = _ids(plan)
    attached = _api_with_walk_forward(plan, proofs)
    assert _step(plan, attached, m2.AttachWalkForward(ids["wf"]), dict(proofs)) is attached
    for other_value in ("free_form_id", _ids(other)["wf"], ids["mc"]):
        with pytest.raises(m2.ManifestTransitionError):
            _step(plan, attached, m2.AttachWalkForward(other_value), dict(proofs))
    # Rejeu pendant une exécution (running vrai) : aucune écriture, donc running n'est pas touché.
    running = _step(plan, attached, m2.SetRunning(True), dict(proofs))
    assert _step(plan, running, m2.AttachWalkForward(ids["wf"]), dict(proofs)) is running


def test_a_coherent_but_incomplete_walk_forward_is_attachable_and_leaves_the_status_incomplete(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    incomplete = {**proofs, ids["wf"]: _evidence_edit(execution_status="failed")(proofs[ids["wf"]])}
    attached = _step(plan, _api_started(plan), m2.AttachWalkForward(ids["wf"]), incomplete)
    assert attached.walk_forward_validation_run_id == ids["wf"] and attached.status == "EVIDENCE_INCOMPLETE"


def test_an_unreferenced_proof_in_the_mapping_never_completes_the_campaign_through_a_command(worlds, proofs):
    plan = worlds.plan
    attached = _api_with_walk_forward(plan, proofs)  # mapping complet fourni, seule la WF est référencée
    assert attached.status == "EVIDENCE_INCOMPLETE"
    assert attached.monte_carlo_validation_run_id is None
    assert dict(attached.parameter_stability_validation_run_ids_by_fold) == {}


# --- AttachMonteCarlo ------------------------------------------------------------------------


def test_attach_monte_carlo_requires_walk_forward_the_deterministic_id_and_a_scoped_proof(worlds, proofs):
    plan, other = worlds.plan, worlds.other_plan
    ids = _ids(plan)
    with pytest.raises(m2.ManifestTransitionError):  # pas de WF
        _step(plan, _api_started(plan), m2.AttachMonteCarlo(ids["mc"]), dict(proofs))
    with_wf = _api_with_walk_forward(plan, proofs)
    for bad_id in ("free_form_id", _ids(other)["mc"], ids["wf"], "", None, 5):
        with pytest.raises(ValueError):
            _step(plan, with_wf, m2.AttachMonteCarlo(bad_id), {**proofs, "free_form_id": proofs[ids["mc"]]})
    only_wf = {key: run for key, run in proofs.items() if key != ids["mc"]}
    with pytest.raises(ValueError):
        _step(plan, with_wf, m2.AttachMonteCarlo(ids["mc"]), only_wf)
    for edit in (lambda run: dataclasses.replace(run, strategy_name="Other Strategy"),
                 _evidence_edit(scientific_verdict="PASS"),
                 lambda run: dataclasses.replace(run, specification=build_monte_carlo_specification("other_wf", True))):
        with pytest.raises(ValueError):
            _step(plan, with_wf, m2.AttachMonteCarlo(ids["mc"]), {**proofs, ids["mc"]: edit(proofs[ids["mc"]])})


def test_attach_monte_carlo_attaches_clears_running_and_is_idempotent_or_refused_on_replacement(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    running = _step(plan, _api_with_walk_forward(plan, proofs), m2.SetRunning(True), dict(proofs))
    attached = _step(plan, running, m2.AttachMonteCarlo(ids["mc"]), dict(proofs))
    assert attached.monte_carlo_validation_run_id == ids["mc"] and attached.running is False
    assert attached.status == "EVIDENCE_INCOMPLETE"  # aucune PS référencée
    assert attached.manifest_revision == running.manifest_revision + 1
    assert _step(plan, attached, m2.AttachMonteCarlo(ids["mc"]), dict(proofs)) is attached
    with pytest.raises(m2.ManifestTransitionError):
        _step(plan, attached, m2.AttachMonteCarlo("free_form_id"), dict(proofs))
    with pytest.raises(m2.ManifestTransitionError):
        _step(plan, attached, m2.AttachMonteCarlo(ids["wf"]), dict(proofs))


def test_an_insufficient_monte_carlo_is_attachable_and_keeps_the_campaign_incomplete(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    poor = {**proofs, ids["mc"]: _evidence_edit(execution_status="failed")(proofs[ids["mc"]])}
    attached = _step(plan, _api_with_walk_forward(plan, poor), m2.AttachMonteCarlo(ids["mc"]), poor)
    assert attached.monte_carlo_validation_run_id == ids["mc"] and attached.status == "EVIDENCE_INCOMPLETE"


# --- AttachParameterStability ----------------------------------------------------------------


def test_attach_parameter_stability_requires_walk_forward_an_expected_fold_and_the_exact_id(worlds, proofs):
    plan, other = worlds.plan, worlds.other_plan
    ids = _ids(plan)
    first, second = plan.expected_fold_ids[0], plan.expected_fold_ids[1]
    with pytest.raises(m2.ManifestTransitionError):  # pas de WF
        _step(plan, _api_started(plan), m2.AttachParameterStability(first, ids["ps"][first]), dict(proofs))
    with_wf = _api_with_walk_forward(plan, proofs)
    foreign_fold = f"{plan.campaign_id}_parameter_stability_fold_999"
    bad_commands = (
        m2.AttachParameterStability("fold_999", foreign_fold),  # fold étranger au plan
        m2.AttachParameterStability(first, ids["ps"][second]),  # id d'un autre fold
        m2.AttachParameterStability(first, _ids(other)["ps"][first]),  # autre campagne
        m2.AttachParameterStability(first, "free_form_id"), m2.AttachParameterStability(first, ids["wf"]),
        m2.AttachParameterStability("", ids["ps"][first]), m2.AttachParameterStability(None, ids["ps"][first]),
        m2.AttachParameterStability(first, None), m2.AttachParameterStability(5, 5),
    )
    for command in bad_commands:
        with pytest.raises(ValueError):
            _step(plan, with_wf, command, {**proofs, foreign_fold: proofs[ids["ps"][first]]})
    absent = {key: run for key, run in proofs.items() if key != ids["ps"][first]}
    with pytest.raises(ValueError):
        _step(plan, with_wf, m2.AttachParameterStability(first, ids["ps"][first]), absent)


def test_attach_parameter_stability_refuses_a_proof_with_a_wrong_provenance(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    first, second = plan.expected_fold_ids[0], plan.expected_fold_ids[1]
    with_wf = _api_with_walk_forward(plan, proofs)
    wrong_spec = build_parameter_stability_specification(ids["wf"], plan.search_mode, True, source_fold_id=second)
    wrong_source = build_parameter_stability_specification("other_wf", plan.search_mode, True, source_fold_id=first)
    for edit in (lambda run: dataclasses.replace(run, specification=wrong_spec),
                 lambda run: dataclasses.replace(run, specification=wrong_source),
                 lambda run: dataclasses.replace(run, strategy_name="Other Strategy"),
                 _evidence_edit(search_mode="general"),
                 _evidence_edit(best_params={"lookback": 999})):  # Top-1 TRAIN du fold non respecté
        with pytest.raises(ValueError):
            _step(plan, with_wf, m2.AttachParameterStability(first, ids["ps"][first]),
                  {**proofs, ids["ps"][first]: edit(proofs[ids["ps"][first]])})


def test_attach_parameter_stability_adds_the_entry_clears_running_and_keeps_the_mapping_immutable(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    first, second = plan.expected_fold_ids[0], plan.expected_fold_ids[1]
    running = _step(plan, _api_with_walk_forward(plan, proofs), m2.SetRunning(True), dict(proofs))
    after_first = _step(plan, running, m2.AttachParameterStability(first, ids["ps"][first]), dict(proofs))
    assert dict(after_first.parameter_stability_validation_run_ids_by_fold) == {first: ids["ps"][first]}
    assert after_first.running is False and after_first.status == "EVIDENCE_INCOMPLETE"
    assert after_first.manifest_revision == running.manifest_revision + 1
    after_second = _step(plan, after_first, m2.AttachParameterStability(second, ids["ps"][second]), dict(proofs))
    assert dict(after_second.parameter_stability_validation_run_ids_by_fold) == {
        first: ids["ps"][first], second: ids["ps"][second]}
    assert dict(after_first.parameter_stability_validation_run_ids_by_fold) == {first: ids["ps"][first]}  # intact
    assert after_second.parameter_stability_validation_run_ids_by_fold is not (
        after_first.parameter_stability_validation_run_ids_by_fold)
    with pytest.raises(TypeError):
        after_second.parameter_stability_validation_run_ids_by_fold["evil"] = "x"
    assert _step(plan, after_second, m2.AttachParameterStability(first, ids["ps"][first]), dict(proofs)) is after_second
    with pytest.raises(m2.ManifestTransitionError):  # même fold, autre valeur
        _step(plan, after_second, m2.AttachParameterStability(first, ids["ps"][second]), dict(proofs))


def test_a_parameter_stability_of_insufficient_quality_is_attachable_but_never_completes_the_campaign(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    last = plan.expected_fold_ids[-1]
    poor = {**proofs, ids["ps"][last]: _poor_parameter_stability(proofs[ids["ps"][last]])}
    path = _api_path(plan, poor)
    assert path[-1].status == "EVIDENCE_INCOMPLETE"  # tous les folds rattachés, dont un de qualité insuffisante
    assert set(path[-1].parameter_stability_validation_run_ids_by_fold) == set(plan.expected_fold_ids)
    # Un fold faible au MILIEU : rattachable lui aussi ; aucun « meilleur fold », aucune moyenne.
    middle = plan.expected_fold_ids[1]
    poor_middle = {**proofs, ids["ps"][middle]: _poor_parameter_stability(proofs[ids["ps"][middle]])}
    assert _api_path(plan, poor_middle)[-1].status == "EVIDENCE_INCOMPLETE"


def test_the_complete_status_appears_only_when_every_fold_is_attached_and_d1_agrees(worlds, proofs):
    plan = worlds.plan
    path = _api_path(plan, proofs)
    folds = len(plan.expected_fold_ids)
    assert [manifest.status for manifest in path[:-1]] == ["READY_FOR_EXECUTION"] + ["EVIDENCE_INCOMPLETE"] * (folds + 2)
    assert path[-1].status == _COMPLETE
    assert [manifest.manifest_revision for manifest in path] == list(range(len(path)))  # +1 exact à chaque pas
    for manifest in path:
        assert m2.validate_gate_v_campaign_manifest_v2_marker_status(manifest, plan, dict(proofs)) is None
        for name in _RESERVED_FIELDS:
            assert getattr(manifest, name) is None
    expected = _complete(plan)
    assert {f.name: getattr(path[-1], f.name) for f in dataclasses.fields(path[-1]) if f.name != "manifest_revision"} == {
        f.name: getattr(expected, f.name) for f in dataclasses.fields(expected) if f.name != "manifest_revision"}


# --- MarkTechnicalFailure --------------------------------------------------------------------


def test_mark_technical_failure_requires_a_started_campaign_and_a_non_empty_reason(worlds):
    plan = worlds.plan
    with pytest.raises(m2.ManifestTransitionError):
        _step(plan, _initial(plan), m2.MarkTechnicalFailure("boom"), {})
    started = _api_started(plan)
    for bad in ("", "   ", "\n", None, 5, ["boom"], True):
        with pytest.raises(ValueError):
            _step(plan, started, m2.MarkTechnicalFailure(bad), {})


def test_mark_technical_failure_is_terminal_clears_running_and_costs_one_revision(worlds, proofs):
    plan = worlds.plan
    running = _step(plan, _api_started(plan), m2.SetRunning(True), {})
    failed = _step(plan, running, m2.MarkTechnicalFailure("boom"), {})
    assert failed.technical_failure_reason == "boom" and failed.running is False
    assert failed.status == "TECHNICAL_FAILURE" and failed.execution_started is True
    assert failed.manifest_revision == running.manifest_revision + 1
    assert _step(plan, failed, m2.MarkTechnicalFailure("boom"), {}) is failed  # même motif : idempotent
    with pytest.raises(m2.ManifestTransitionError):
        _step(plan, failed, m2.MarkTechnicalFailure("another reason"), {})
    assert m2.validate_gate_v_campaign_manifest_v2_marker_status(failed, plan, {}) is None


def test_a_technical_failure_keeps_every_attached_reference_and_refuses_every_other_command(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    complete = _api_path(plan, proofs)[-1]
    failed = _step(plan, complete, m2.MarkTechnicalFailure("boom"), dict(proofs))
    assert failed.status == "TECHNICAL_FAILURE"
    assert failed.walk_forward_validation_run_id == complete.walk_forward_validation_run_id
    assert failed.monte_carlo_validation_run_id == complete.monte_carlo_validation_run_id
    assert dict(failed.parameter_stability_validation_run_ids_by_fold) == dict(
        complete.parameter_stability_validation_run_ids_by_fold)
    first = plan.expected_fold_ids[0]
    terminal_refusals = (
        m2.Start(), m2.SetRunning(True), m2.SetRunning(False), m2.AttachWalkForward(ids["wf"]),
        m2.AttachMonteCarlo(ids["mc"]), m2.AttachParameterStability(first, ids["ps"][first]),
        m2.MarkTechnicalFailure("another reason"),
    )
    for command in terminal_refusals:
        with pytest.raises(m2.ManifestTransitionError):
            _step(plan, failed, command, dict(proofs))
    started_failed = _step(plan, _api_started(plan), m2.MarkTechnicalFailure("boom"), {})
    for command in terminal_refusals[:3]:
        with pytest.raises(m2.ManifestTransitionError):
            _step(plan, started_failed, command, dict(proofs))


# --- Pureté, absence d'alias, immutabilité des entrées ----------------------------------------


def test_commands_never_mutate_the_evidence_the_manifest_or_the_plan_and_keep_no_alias(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    mapping = dict(proofs)
    proofs_before = {key: dataclasses.asdict(run) for key, run in mapping.items()}
    plan_before = dataclasses.asdict(plan)
    manifest = _api_started(plan)
    before = dataclasses.asdict(manifest)
    result = _step(plan, manifest, m2.AttachWalkForward(ids["wf"]), mapping)
    assert dataclasses.asdict(manifest) == before and dataclasses.asdict(plan) == plan_before
    assert {key: dataclasses.asdict(run) for key, run in mapping.items()} == proofs_before
    assert set(mapping) == set(proofs)
    mapping.clear()  # l'appelant détruit son mapping : le Manifest produit ne doit pas bouger
    assert result.walk_forward_validation_run_id == ids["wf"]
    assert m2.validate_gate_v_campaign_manifest_v2_against_plan(result, plan) is None


def test_applying_the_same_command_twice_to_the_same_input_is_deterministic(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    manifest = _api_started(plan)
    first = _step(plan, manifest, m2.AttachWalkForward(ids["wf"]), dict(proofs))
    second = _step(plan, manifest, m2.AttachWalkForward(ids["wf"]), dict(proofs))
    assert first == second and first is not second


def test_a_referenced_proof_that_is_none_or_not_a_validation_run_is_a_closed_error_at_every_status(worlds, proofs):
    """Une référence dont la valeur est `None` (ou n'est pas une ValidationRun) est une preuve ABSENTE : D1 la traite
    comme manquante, donc sans cette garde un Manifest « en avance sur ses preuves » obtiendrait un statut."""
    plan = worlds.plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]
    with_everything = dict(
        walk_forward_validation_run_id=ids["wf"], monte_carlo_validation_run_id=ids["mc"],
        parameter_stability_validation_run_ids_by_fold=ids["ps"])
    manifests = {
        "complete": _complete(plan),
        "incomplete_with_walk_forward": _started(plan, walk_forward_validation_run_id=ids["wf"]),
        "running_with_walk_forward": _with(
            _initial(plan), execution_started=True, running=True, status="RUNNING", **with_everything),
        # L'état d'échec technique est volontairement ABSENT ici : il ne dépend d'aucune preuve (test dédié).
    }
    not_proofs = (None, "run", 7, {}, [], object(), dataclasses.asdict(proofs[ids["wf"]]))
    for name, manifest in manifests.items():
        for proof_id in (ids["wf"], ids["mc"], ids["ps"][first]):
            if proof_id != ids["wf"] and name in ("incomplete_with_walk_forward",):
                continue  # MC / PS ne sont pas référencées par ce Manifest
            for bad in not_proofs:
                mapping = {**proofs, proof_id: bad}
                with pytest.raises(ValueError):
                    _derive(plan, manifest, mapping)
                with pytest.raises(ValueError):
                    m2.validate_gate_v_campaign_manifest_v2_marker_status(manifest, plan, mapping)
                # `MarkTechnicalFailure` est la SEULE exception : elle ne regarde aucune preuve (test dédié).
                for command in (m2.Start(), m2.SetRunning(True), m2.SetRunning(False)):
                    with pytest.raises(ValueError):
                        _step(plan, manifest, command, mapping)


def test_a_stale_revision_is_refused_before_the_evidence_and_the_command_are_even_looked_at(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    attached = _api_with_walk_forward(plan, proofs)  # révision 2
    for evidence in ({ids["wf"]: None}, {}, None, "not a mapping"):
        with pytest.raises(m2.ManifestTransitionError):
            _step(plan, attached, m2.Start(), evidence, expected_revision=1)
    for command in (None, {"command": "Start"}, object(), m2.SetRunning(1)):
        with pytest.raises(m2.ManifestTransitionError):
            _step(plan, attached, command, dict(proofs), expected_revision=1)


def test_an_input_manifest_that_is_ahead_of_its_proofs_is_refused_before_any_command_is_applied(worlds, proofs):
    plan = worlds.plan
    attached = _api_with_walk_forward(plan, proofs)
    # Start / SetRunning / Attach* restent fail-closed. `MarkTechnicalFailure` est l'exception explicite : une preuve
    # absente est précisément ce qu'un échec technique doit pouvoir enregistrer (test dédié).
    for command in (m2.Start(), m2.SetRunning(True), m2.SetRunning(False)):
        with pytest.raises(ValueError):  # la WF référencée n'est pas fournie : fail-closed
            _step(plan, attached, command, {})


def test_an_input_manifest_whose_persisted_status_contradicts_its_proofs_is_refused(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    complete = _api_path(plan, proofs)[-1]
    understated = _with(complete, status="EVIDENCE_INCOMPLETE")
    with pytest.raises(ValueError):
        _step(plan, understated, m2.Start(), dict(proofs))
    poor = {**proofs, ids["ps"][plan.expected_fold_ids[0]]: _poor_parameter_stability(
        proofs[ids["ps"][plan.expected_fold_ids[0]]])}
    with pytest.raises(ValueError):  # statut « complet » alors que la PS référencée est devenue insuffisante
        _step(plan, complete, m2.SetRunning(True), poor)


# ============================================================================================
# Tranche 9 — D3 : MarkTechnicalFailure et le statut terminal ne dépendent d'AUCUNE preuve référencée
#   (une preuve absente, illisible ou corrompue est précisément ce qu'un échec technique doit pouvoir enregistrer)
# ============================================================================================


def _references(manifest):
    return [
        reference for reference in (
            manifest.walk_forward_validation_run_id, manifest.monte_carlo_validation_run_id,
            *manifest.parameter_stability_validation_run_ids_by_fold.values())
        if reference is not None
    ]


def _unusable_evidence(manifest, proofs):
    """Mappings où CHAQUE preuve référencée est absente ou inutilisable (absente, None, objet, dict, ValidationRun
    étrangère)."""
    foreign_run = dataclasses.replace(next(iter(proofs.values())), strategy_name="Other Strategy")
    references = _references(manifest)
    return {
        "empty": {},
        "none_values": {reference: None for reference in references},
        "bare_object": {reference: object() for reference in references},
        "invalid_dict": {reference: {"validation_run_id": reference} for reference in references},
        "string": {reference: "not a run" for reference in references},
        "foreign_validation_run": {reference: foreign_run for reference in references},
    }


class _Tripwire(Mapping):
    """Mapping qui ne doit JAMAIS être inspecté : toute lecture, itération ou test d'appartenance échoue."""

    def __getitem__(self, key):
        raise AssertionError("les preuves ne doivent pas être inspectées")

    def __iter__(self):
        raise AssertionError("les preuves ne doivent pas être inspectées")

    def __len__(self):
        raise AssertionError("les preuves ne doivent pas être inspectées")


def _states_with_references(plan, proofs):
    ids = _ids(plan)
    with_wf = _api_with_walk_forward(plan, proofs)
    with_mc = _step(plan, with_wf, m2.AttachMonteCarlo(ids["mc"]), dict(proofs))
    first = plan.expected_fold_ids[0]
    return {
        "walk_forward_only": with_wf,
        "walk_forward_and_monte_carlo": with_mc,
        "walk_forward_monte_carlo_and_one_fold": _step(
            plan, with_mc, m2.AttachParameterStability(first, ids["ps"][first]), dict(proofs)),
        "walk_forward_monte_carlo_and_every_fold": _api_path(plan, proofs)[-1],
        "running_with_walk_forward": _step(plan, with_wf, m2.SetRunning(True), dict(proofs)),
    }


def test_mark_technical_failure_succeeds_whatever_the_state_of_the_referenced_proofs(worlds, proofs):
    plan = worlds.plan
    for state_name, state in _states_with_references(plan, proofs).items():
        assert _references(state), state_name
        before = dataclasses.asdict(state)
        for kind, mapping in _unusable_evidence(state, proofs).items():
            failed = _step(plan, state, m2.MarkTechnicalFailure("proof_unreadable"), mapping)
            where = f"{state_name}/{kind}"
            assert failed.status == "TECHNICAL_FAILURE", where
            assert failed.technical_failure_reason == "proof_unreadable" and failed.running is False, where
            assert failed.execution_started is True, where
            assert failed.manifest_revision == state.manifest_revision + 1, where  # N -> N+1, jamais +2
            for name in ("walk_forward_validation_run_id", "monte_carlo_validation_run_id"):
                assert getattr(failed, name) == getattr(state, name), where  # aucune référence effacée
            assert dict(failed.parameter_stability_validation_run_ids_by_fold) == dict(
                state.parameter_stability_validation_run_ids_by_fold), where
            for name in _RESERVED_FIELDS:
                assert getattr(failed, name) is None, where
            assert m2.validate_gate_v_campaign_manifest_v2_against_plan(failed, plan) is None, where
            assert dataclasses.asdict(state) == before, where  # entrée intacte


def test_mark_technical_failure_never_inspects_the_evidence_at_all(worlds, proofs, monkeypatch):
    plan = worlds.plan

    def must_not_run(*args, **kwargs):
        raise AssertionError("D1 ne doit pas être appelé pour un échec technique")
    state = _api_path(plan, proofs)[-1]
    monkeypatch.setattr(m2, "evaluate_pre_holdout_evidence_v2", must_not_run)
    monkeypatch.setattr(m2, "validate_scoped_evidence_run_v2", must_not_run)
    failed = _step(plan, state, m2.MarkTechnicalFailure("proof_unreadable"), _Tripwire())
    assert failed.status == "TECHNICAL_FAILURE"
    assert _step(plan, failed, m2.MarkTechnicalFailure("proof_unreadable"), _Tripwire()) is failed
    assert _derive(plan, failed, _Tripwire()) == "TECHNICAL_FAILURE"
    assert m2.validate_gate_v_campaign_manifest_v2_marker_status(failed, plan, _Tripwire()) is None


def test_mark_technical_failure_replay_is_idempotent_and_another_reason_is_refused_without_any_proof(worlds, proofs):
    plan = worlds.plan
    failed = _step(plan, _states_with_references(plan, proofs)["walk_forward_and_monte_carlo"],
                   m2.MarkTechnicalFailure("proof_unreadable"), {})
    for kind, mapping in _unusable_evidence(failed, proofs).items():
        replay = _step(plan, failed, m2.MarkTechnicalFailure("proof_unreadable"), mapping)
        assert replay is failed and replay.manifest_revision == failed.manifest_revision, kind
        with pytest.raises(m2.ManifestTransitionError):
            _step(plan, failed, m2.MarkTechnicalFailure("autre raison"), mapping)
        with pytest.raises(m2.ManifestTransitionError):  # révision périmée : même refus, sans preuve
            _step(plan, failed, m2.MarkTechnicalFailure("proof_unreadable"), mapping, expected_revision=0)


def test_a_terminal_technical_failure_stays_derivable_without_any_usable_proof(worlds, proofs):
    plan = worlds.plan
    for state_name, state in _states_with_references(plan, proofs).items():
        failed = _step(plan, state, m2.MarkTechnicalFailure("proof_unreadable"), {})
        for kind, mapping in _unusable_evidence(failed, proofs).items():
            assert _derive(plan, failed, mapping) == "TECHNICAL_FAILURE", f"{state_name}/{kind}"
            assert m2.validate_gate_v_campaign_manifest_v2_marker_status(failed, plan, mapping) is None


def test_every_other_command_on_a_terminal_failure_is_a_transition_error_whatever_the_proofs(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]
    failed = _step(plan, _states_with_references(plan, proofs)["walk_forward_only"],
                   m2.MarkTechnicalFailure("proof_unreadable"), {})
    commands = (
        m2.Start(), m2.SetRunning(True), m2.SetRunning(False), m2.AttachWalkForward(ids["wf"]),
        m2.AttachMonteCarlo(ids["mc"]), m2.AttachParameterStability(first, ids["ps"][first]),
    )
    for kind, mapping in _unusable_evidence(failed, proofs).items():
        for command in commands:
            with pytest.raises(m2.ManifestTransitionError):
                _step(plan, failed, command, mapping)


def test_the_other_preconditions_of_mark_technical_failure_do_not_depend_on_the_proofs_either(worlds, proofs):
    plan = worlds.plan
    started = _api_started(plan)
    with pytest.raises(m2.ManifestTransitionError):  # non démarrée
        _step(plan, _initial(plan), m2.MarkTechnicalFailure("boom"), {})
    for bad_reason in ("", "   ", None, 5, ["x"], True):
        with pytest.raises(ValueError):
            _step(plan, started, m2.MarkTechnicalFailure(bad_reason), {})
    with_wf = _states_with_references(plan, proofs)["walk_forward_only"]
    with pytest.raises(m2.ManifestTransitionError):  # révision périmée
        _step(plan, with_wf, m2.MarkTechnicalFailure("boom"), {}, expected_revision=with_wf.manifest_revision + 1)
    for bad_plan in (worlds.v1_plan, None, {}):  # le Plan et le Manifest restent validés
        with pytest.raises(ValueError):
            _step(bad_plan, with_wf, m2.MarkTechnicalFailure("boom"), {}, expected_revision=2)
    for bad_manifest in (None, {}, _with(with_wf, final_holdout_claim_id="x"), _initial(worlds.other_plan)):
        with pytest.raises(ValueError):
            _step(plan, bad_manifest, m2.MarkTechnicalFailure("boom"), {}, expected_revision=2)


def test_the_other_commands_stay_fail_closed_when_a_referenced_proof_is_unusable(worlds, proofs):
    """Aucune relaxation globale : seul `MarkTechnicalFailure` ignore les preuves ; Start / SetRunning / Attach* exigent
    toujours des preuves référencées présentes et valides."""
    plan = worlds.plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]
    state = _states_with_references(plan, proofs)["walk_forward_and_monte_carlo"]
    commands = (
        m2.Start(), m2.SetRunning(True), m2.SetRunning(False),
        m2.AttachParameterStability(first, ids["ps"][first]), m2.AttachWalkForward(ids["wf"]),
        m2.AttachMonteCarlo(ids["mc"]),
    )
    for kind, mapping in _unusable_evidence(state, proofs).items():
        for command in commands:
            with pytest.raises(ValueError):
                _step(plan, state, command, mapping)
        with pytest.raises(ValueError):
            _derive(plan, state, mapping)


# --- Les trois arbitrages figés (règle d'idempotence de l'ADR §21.8) ---------------------------


def test_arbitration_a_set_running_false_when_not_running_is_idempotent(worlds, proofs):
    plan = worlds.plan
    started = _api_started(plan)
    assert _step(plan, started, m2.SetRunning(False), {}) is started
    attached = _api_with_walk_forward(plan, proofs)
    assert _step(plan, attached, m2.SetRunning(False), dict(proofs)) is attached
    assert attached.manifest_revision == 2


def test_arbitration_b_a_different_id_on_an_attached_reference_is_a_transition_error_before_any_proof_check(
    worlds, proofs,
):
    plan, other = worlds.plan, worlds.other_plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]
    state = _states_with_references(plan, proofs)["walk_forward_monte_carlo_and_one_fold"]
    # Le NOUVEL identifiant n'a aucune preuve dans le mapping : le refus est quand même un conflit de transition.
    replacements = (
        m2.AttachWalkForward("never_provided_id"), m2.AttachWalkForward(_ids(other)["wf"]),
        m2.AttachMonteCarlo("never_provided_id"), m2.AttachMonteCarlo(ids["wf"]),
        m2.AttachParameterStability(first, "never_provided_id"),
        m2.AttachParameterStability(first, _ids(other)["ps"][first]),
    )
    for command in replacements:
        with pytest.raises(m2.ManifestTransitionError):
            _step(plan, state, command, dict(proofs))


def test_arbitration_c_replaying_an_attach_while_running_is_a_no_op_that_keeps_running_true(worlds, proofs):
    plan = worlds.plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]
    state = _states_with_references(plan, proofs)["walk_forward_monte_carlo_and_one_fold"]
    running = _step(plan, state, m2.SetRunning(True), dict(proofs))
    assert running.running is True
    for command in (
        m2.AttachWalkForward(ids["wf"]), m2.AttachMonteCarlo(ids["mc"]),
        m2.AttachParameterStability(first, ids["ps"][first]),
    ):
        replay = _step(plan, running, command, dict(proofs))
        assert replay is running and replay.running is True
        assert replay.manifest_revision == running.manifest_revision
