"""
tests/test_gate_v_campaign_manifest_v2.py — AF-V-07 Slices D2, D3, D4 (ADR 0025 Décision 21.4 / 21.5 / 21.8 / 21.13).

D2 : type `GateVCampaignManifestV2` (17 champs), constantes, builder initial EN MÉMOIRE, validation structurelle
pure, liaison au `GateVCampaignPlanV2`, conversion record pure. D3 : statut posé par les marqueurs et six commandes
pures. D4 : création exclusive, chargeur strict, mise à jour sous `manifest.update.lock`, sentinelle
`technical_failure.json`, statut effectif, concurrence et crash entre PROCESSUS RÉELS (`spawn`). Aucune
vérification publique des preuves persistées ni précondition du Claim (D5), aucune discrimination de dossier (D6),
aucun Claim, aucun FINAL_HOLDOUT.

Fixtures SYNTHÉTIQUES : un dépôt Git temporaire hermétique fournit la provenance historique de la policy ;
aucune donnée de marché, aucun backtest.
"""

from __future__ import annotations

import ast
import dataclasses
import io
import json
import multiprocessing
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
from gate_v_campaign_plan_v2 import (
    GateVCampaignPlanV2,
    build_gate_v_campaign_plan_v2,
    load_gate_v_campaign_plan_v2,
    save_gate_v_campaign_plan_v2,
)
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
    save_validation_run,
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
    # D4 : création exclusive, chargeur strict, mise à jour sous verrou, sentinelle, statut effectif
    "create_gate_v_campaign_manifest_v2", "load_gate_v_campaign_manifest_v2", "update_gate_v_campaign_manifest_v2",
    "derive_gate_v_campaign_v2_effective_status", "GATE_V_TECHNICAL_FAILURE_SENTINEL_SEMANTICS_VERSION",
    "GATE_V_TECHNICAL_FAILURE_SENTINEL_UNREADABLE_REASON",
    # D4 : quatre issues de persistance distinctes
    "ManifestLockAcquisitionError", "ManifestWriteError", "ManifestWriteUncertainError", "ManifestLockReleaseError",
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


def test_the_module_imports_only_the_declared_dependencies_and_never_gate_v_campaign():
    """ADR 0025 §21.11 : imports DIRECTS limités à Plan V2, D1, `validation_run`, `atomic_json_store` (et la
    bibliothèque standard strictement nécessaire à la persistance D4) ; jamais V1, jamais un module de Claim."""
    imported = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {
        "__future__", "re", "dataclasses", "typing", "pathlib", "os", "json", "atomic_json_store",
        "gate_v_campaign_plan_v2", "gate_v_evidence_completeness_v2", "validation_run",
    }
    assert "gate_v_campaign" not in imported
    # Écritures permises : création EXCLUSIVE (Manifest initial, sentinelle) et écrasement atomique SOUS VERROU
    # (mise à jour) ; jamais `save_atomic` (refus d'écrasement non exclusif, TOCTOU) pour un fichier de campagne.
    imported_from_store = {
        alias.name for node in ast.walk(_module_tree())
        if isinstance(node, ast.ImportFrom) and node.module == "atomic_json_store" for alias in node.names
    }
    assert imported_from_store <= {
        "validate_portable_identifier", "load_json_tolerant", "save_exclusive", "save_atomic_overwrite",
    }


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


def test_the_module_uses_no_clock_randomness_hashing_process_identity_scanning_or_free_file_api():
    """Persistance D4 sans horloge (aucun stale-lock par âge ou délai), sans PID/hôte, sans hasard, sans balayage de
    dossiers (aucune adoption automatique), sans test d'existence préalable à `O_EXCL`, sans renommage ni
    suppression libre, sans `open()` libre : seules les primitives `os` du verrou et de la sentinelle sont utilisées."""
    tree = _module_tree()
    forbidden = {
        "sys", "subprocess", "shutil", "tempfile", "glob", "hashlib", "save_atomic", "rename", "replace", "rmtree",
        "mkdir", "makedirs", "rmdir", "listdir", "scandir", "iterdir", "walk", "rglob", "exists", "is_file",
        "isfile", "lexists", "time", "sleep", "monotonic", "datetime", "uuid", "random", "getpid", "getppid",
        "gethostname", "platform", "socket", "getmtime", "st_mtime", "st_ctime", "kill", "signal", "threading",
        "print", "input",
    }
    assert not _code_identifiers(tree) & forbidden
    assert not any(isinstance(node, ast.Name) and node.id == "open" for node in ast.walk(tree))  # pas d'open() libre
    os_attributes = {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os"
    }
    assert os_attributes <= {
        "open", "O_CREAT", "O_EXCL", "O_WRONLY", "write", "fstat", "stat", "lstat", "close", "unlink",
    }


def test_the_module_contains_no_claim_holdout_assessment_or_later_slice_logic():
    forbidden = {
        # Claim / FINAL_HOLDOUT / assessments
        "FinalHoldoutAccessClaim", "HoldoutAccessEvent", "run_gate_v_final_holdout_validation",
        "ValidationAssessment", "GateVPolicyAssessment", "validation_oos", "engine",
        # D5 : vérification publique des preuves persistées et précondition du Claim
        "assert_gate_v_pre_holdout_evidence_complete",
        # D6 : discrimination
        "classify_gate_v_campaign_dir", "GateVCampaignDiscriminationError",
        # Réimplémentation des prédicats de complétude : ils restent ceux de D1
        "walk_forward_evidence_complete_v2", "monte_carlo_evidence_complete_v2",
        "parameter_stability_evidence_complete_v2",
    }
    assert not _code_identifiers(_module_tree()) & forbidden
    for name in (
        # aucune écriture libre du Manifest : seules la création exclusive et la mise à jour par commande existent
        "save_gate_v_campaign_manifest_v2", "write_gate_v_campaign_manifest_v2",
        # aucun verrou exposé, aucune récupération ni nettoyage automatique de verrou (récupération manuelle gouvernée)
        "acquire_manifest_update_lock", "release_manifest_update_lock", "recover_manifest_update_lock",
        "clean_stale_manifest_update_lock", "mark_technical_failure_sentinel",
        # D5 / D6
        "assert_gate_v_pre_holdout_evidence_complete", "classify_gate_v_campaign_dir",
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


# ============================================================================================
# Tranche 10 — D4 : création EXCLUSIVE du Manifest initial et chargeur STRICT du Manifest persisté
#   (dossier canonique `<campaign_root>/<campaign_id>/`, toujours fourni par l'appelant)
# ============================================================================================

_LOCK = "manifest.update.lock"
_SENTINEL = "technical_failure.json"


_LONG_PATHS_CONFIRMED = []


def _require_long_path_support(root):
    """Prérequis de déploiement EXPLICITE (ADR 0025 §21.12 n° 30) : les chemins canoniques des preuves dépassent
    `MAX_PATH` (260) sous Windows. Sur un hôte sans chemins longs, échec clair plutôt qu'une WinError 3/206 obscure."""
    if sys.platform != "win32" or _LONG_PATHS_CONFIRMED:
        return
    probe_root = root / ("long_path_probe_" + "x" * 120)
    probe = probe_root / ("y" * 120) / "probe.txt"
    try:
        probe.parent.mkdir(parents=True)
        probe.write_text("ok", encoding="utf-8")
    except OSError as error:
        pytest.fail(
            "Prérequis : support des chemins longs Windows (LongPathsEnabled=1) exigé par la disposition canonique "
            f"des preuves (ADR 0025 §21.12 n° 30) ; chemin de {len(str(probe))} caractères refusé : {error}")
    probe.unlink()  # aucun résidu dans le dossier du test appelant
    probe.parent.rmdir()
    probe_root.rmdir()
    _LONG_PATHS_CONFIRMED.append(True)


def _campaign(root, plan):
    """Dossier canonique d'une campagne réelle : son seul `plan.json`, persisté par la Slice C (création exclusive)."""
    _require_long_path_support(root)
    return save_gate_v_campaign_plan_v2(root / "campaigns", plan).parent


def _files(directory):
    """Instantané octet par octet de TOUS les fichiers sous `directory` : preuve qu'une opération n'a rien écrit."""
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*")) if path.is_file()
    }


def _persisted_record(campaign_dir):
    return json.loads((campaign_dir / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(campaign_dir, manifest):
    """Écrit à la main un Manifest valide (rôle d'un écrivain antérieur), sans passer par l'API D4."""
    (campaign_dir / "manifest.json").write_text(json.dumps(_record(manifest)), encoding="utf-8")


def test_create_persists_exactly_the_initial_manifest_and_returns_it(worlds, tmp_path):
    plan = worlds.plan
    campaign_dir = _campaign(tmp_path, plan)
    created = m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
    assert created == _initial(plan)
    assert _persisted_record(campaign_dir) == _record(_initial(plan))
    assert (created.manifest_revision, created.status) == (0, "READY_FOR_EXECUTION")
    assert (created.execution_started, created.running, created.technical_failure_reason) == (False, False, None)
    assert _references(created) == [] and all(getattr(created, name) is None for name in _RESERVED_FIELDS)
    assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir) == created
    assert set(_files(campaign_dir)) == {"plan.json", "manifest.json"}  # ni verrou, ni sentinelle, ni Claim


def test_a_second_creator_gets_file_exists_error_and_never_overwrites_even_an_advanced_manifest(worlds, tmp_path):
    plan = worlds.plan
    campaign_dir = _campaign(tmp_path, plan)
    m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
    with pytest.raises(FileExistsError):
        m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
    _write_manifest(campaign_dir, _api_started(plan))  # Manifest déjà avancé (révision 1) par un autre écrivain
    before = _files(campaign_dir)
    with pytest.raises(FileExistsError):
        m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
    assert _files(campaign_dir) == before
    assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir).manifest_revision == 1


def test_a_truncated_manifest_consumes_the_path_and_is_refused_without_any_recovery(worlds, tmp_path):
    """Crash entre `O_EXCL` et l'écriture complète : le chemin reste consommé, jamais réparé ni recréé."""
    plan = worlds.plan
    campaign_dir = _campaign(tmp_path, plan)
    complete = json.dumps(_record(_initial(plan)))
    for content in ("", complete[: len(complete) // 2]):
        (campaign_dir / "manifest.json").write_text(content, encoding="utf-8")
        before = _files(campaign_dir)
        with pytest.raises(FileExistsError):
            m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
        with pytest.raises(ValueError):
            m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)
        assert _files(campaign_dir) == before  # aucun renommage, aucune copie `.corrupt`, aucune réécriture


def test_create_and_load_bind_the_canonical_directory_to_the_persisted_plan(worlds, tmp_path):
    plan, other = worlds.plan, worlds.other_plan
    valid = _campaign(tmp_path / "valid", plan)
    misnamed = tmp_path / "misnamed" / "not_the_campaign_id"
    without_plan = tmp_path / "without_plan" / plan.campaign_id
    foreign_plan = tmp_path / "foreign_plan" / plan.campaign_id  # bon nom, mais le plan.json d'une autre campagne
    for directory in (misnamed, without_plan, foreign_plan):
        directory.mkdir(parents=True)
    (misnamed / "plan.json").write_bytes((valid / "plan.json").read_bytes())
    (foreign_plan / "plan.json").write_bytes((_campaign(tmp_path / "other", other) / "plan.json").read_bytes())
    for directory in (misnamed, without_plan, foreign_plan):
        before = _files(directory)
        with pytest.raises(ValueError):
            m2.create_gate_v_campaign_manifest_v2(plan, directory)
        assert _files(directory) == before  # refus AVANT toute écriture
        _write_manifest(directory, _initial(plan))
        with pytest.raises(ValueError):  # le chargeur exige la même liaison, même avec un manifest.json valide
            m2.load_gate_v_campaign_manifest_v2(plan, directory)
    for bad_dir in (None, "", "   ", 5, ["x"]):
        for function in (m2.create_gate_v_campaign_manifest_v2, m2.load_gate_v_campaign_manifest_v2):
            with pytest.raises(ValueError):
                function(plan, bad_dir)
    for bad_plan in (worlds.v1_plan, None, {}, other):
        for function in (m2.create_gate_v_campaign_manifest_v2, m2.load_gate_v_campaign_manifest_v2):
            with pytest.raises(ValueError):
                function(bad_plan, valid)
    assert set(_files(valid)) == {"plan.json"}


def test_the_strict_loader_refuses_absent_unreadable_invalid_or_non_object_manifests(worlds, tmp_path):
    plan = worlds.plan
    campaign_dir = _campaign(tmp_path, plan)
    path = campaign_dir / "manifest.json"
    with pytest.raises(ValueError):  # absent : jamais un `None` silencieux
        m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)
    for content in ("{", "not json", "[]", "null", "42", '"manifest"', "﻿{}"):
        path.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError):
            m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)
    path.unlink()
    path.mkdir()  # un dossier à la place du fichier
    with pytest.raises(ValueError):
        m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)


def test_the_strict_loader_never_falls_back_to_v1_and_refuses_a_foreign_or_forged_record(worlds, tmp_path):
    plan = worlds.plan
    campaign_dir = _campaign(tmp_path, plan)
    v1_record = dataclasses.asdict(gate_v_campaign.build_gate_v_campaign_manifest(worlds.v1_plan))
    forged = [
        v1_record,
        {**v1_record, "manifest_semantics_version": m2.GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION},
        _record(_initial(worlds.other_plan)),  # Manifest valide d'une AUTRE campagne
        {**_record(_initial(plan)), "final_holdout_claim_id": "claim_added_by_hand"},
        {**_record(_initial(plan)), "unknown_key": None},
        {**_record(_initial(plan)), "status": "EVIDENCE_COMPLETE_AWAITING_POLICY"},
        {**_record(_initial(plan)), "manifest_semantics_version": "gate_v_campaign_manifest_v3"},
    ]
    for record in forged:
        (campaign_dir / "manifest.json").write_text(json.dumps(record), encoding="utf-8")
        with pytest.raises(ValueError):
            m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)


def test_the_loader_reads_while_the_update_lock_exists_and_never_takes_touches_or_deletes_it(worlds, tmp_path):
    """Moitié D4 du test ADR §21.13 n° 11 : les lecteurs ne prennent jamais le verrou (la précondition du Claim,
    qui exige son absence, relève de D5)."""
    plan = worlds.plan
    campaign_dir = _campaign(tmp_path, plan)
    m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
    lock = campaign_dir / _LOCK
    lock.write_bytes(b"held by another writer")
    identity = (os.stat(lock).st_dev, os.stat(lock).st_ino)
    before = _files(campaign_dir)
    assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir) == _initial(plan)
    assert _files(campaign_dir) == before
    assert (os.stat(lock).st_dev, os.stat(lock).st_ino) == identity


def test_a_sentinel_ahead_of_the_manifest_never_makes_the_manifest_unloadable(worlds, tmp_path):
    """Sentinelle et marqueur sont deux faits distincts : une sentinelle « en avance » (même illisible) laisse le
    Manifest chargeable, avec son statut posé par les marqueurs."""
    plan = worlds.plan
    campaign_dir = _campaign(tmp_path, plan)
    started = _api_started(plan)
    _write_manifest(campaign_dir, started)
    valid = json.dumps({
        "technical_failure_sentinel_semantics_version": "gate_v_technical_failure_sentinel_v1",
        "campaign_id": plan.campaign_id, "reason": "worker crashed",
    })
    for content in (valid, "", valid[:10], "garbage"):
        (campaign_dir / _SENTINEL).write_text(content, encoding="utf-8")
        loaded = m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)
        assert loaded == started and loaded.status == "EVIDENCE_INCOMPLETE"


# ============================================================================================
# Tranche 11 — D4 : transaction de mise à jour SOUS `manifest.update.lock` (ADR 0025 §21.8, étapes 1 à 11)
#   rechargement et contrôle de révision SOUS le verrou, transition calculée par D3, écriture puis relecture
# ============================================================================================


def _update(plan, campaign_dir, command, *, expected_revision=_CURRENT_REVISION):
    """Mise à jour persistée ; par défaut l'appelant relit d'abord la révision courante (rôle d'un vrai appelant)."""
    if expected_revision is _CURRENT_REVISION:
        expected_revision = m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir).manifest_revision
    return m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, command, expected_revision=expected_revision)


def _persist(campaign_dir, *runs):
    """Persiste des preuves à leur chemin CANONIQUE `validations/<validation_run_id>/validation_run.json`."""
    for run in runs:
        save_validation_run(campaign_dir / "validations" / run.validation_run_id / "validation_run.json", run)


def _started_campaign(root, plan):
    campaign_dir = _campaign(root, plan)
    m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
    _update(plan, campaign_dir, m2.Start())
    return campaign_dir


def _identity(path):
    status = os.stat(path)
    return status.st_dev, status.st_ino


def test_an_effective_update_persists_exactly_the_d3_result_one_revision_later_and_removes_the_lock(worlds, tmp_path):
    plan = worlds.plan
    campaign_dir = _campaign(tmp_path, plan)
    m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
    started = m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, m2.Start(), expected_revision=0)
    assert started == _api_started(plan) and started.manifest_revision == 1
    assert _persisted_record(campaign_dir) == _record(started)
    assert set(_files(campaign_dir)) == {"plan.json", "manifest.json"}  # verrou supprimé, aucun autre fichier


def test_the_whole_lifecycle_through_persistence_equals_the_pure_d3_path_on_proofs_reloaded_from_disk(
    worlds, proofs, tmp_path,
):
    """D4 n'implémente aucune transition : chaque version persistée est EXACTEMENT celle que calcule D3, alors que
    les preuves sont rechargées du disque (sous-objets en dict) et non fournies en mémoire."""
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _campaign(tmp_path, plan)
    m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
    _persist(campaign_dir, *proofs.values())
    commands = [m2.Start(), m2.AttachWalkForward(ids["wf"]), m2.AttachMonteCarlo(ids["mc"])]
    commands += [m2.AttachParameterStability(fold, ids["ps"][fold]) for fold in plan.expected_fold_ids]
    expected_path = _api_path(plan, proofs)
    for command, expected in zip(commands, expected_path[1:]):
        assert _update(plan, campaign_dir, command) == expected
        assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir) == expected
        assert not (campaign_dir / _LOCK).exists()
    assert expected_path[-1].status == _COMPLETE
    assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir).manifest_revision == len(commands)


def test_an_idempotent_command_still_takes_the_lock_but_writes_nothing(worlds, tmp_path, monkeypatch):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    started = m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)
    before = _files(campaign_dir)

    def no_write(*args, **kwargs):
        raise AssertionError("une commande idempotente n'écrit jamais")
    monkeypatch.setattr(m2, "save_atomic_overwrite", no_write)
    for command in (m2.Start(), m2.SetRunning(False)):
        replay = m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, command, expected_revision=1)
        assert replay == started and replay.manifest_revision == 1
        assert _files(campaign_dir) == before  # rien d'écrit, verrou libéré
    (campaign_dir / _LOCK).write_bytes(b"")  # preuve que le verrou est pris même pour une commande idempotente
    with pytest.raises(FileExistsError):
        m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, m2.Start(), expected_revision=1)


def test_a_stale_expected_revision_is_refused_under_the_lock_without_rebase_or_write(worlds, tmp_path):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    _update(plan, campaign_dir, m2.SetRunning(True))  # révision 2
    before = _files(campaign_dir)
    for command in (m2.SetRunning(False), m2.SetRunning(True), m2.Start()):  # effective, puis deux idempotentes
        for stale in (0, 1, 3):
            with pytest.raises(m2.ManifestTransitionError):
                m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, command, expected_revision=stale)
            assert _files(campaign_dir) == before  # aucun rebase, aucune écriture, verrou libéré


def test_the_revision_is_compared_only_after_the_lock_is_acquired(worlds, tmp_path):
    """`manifest_revision` n'est jamais un compare-and-swap : aucune comparaison sur une lecture antérieure au verrou.
    Verrou occupé + révision périmée -> `FileExistsError` (l'étape 4 n'est jamais atteinte sans le verrou)."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    (campaign_dir / _LOCK).write_bytes(b"")
    for stale in (0, 7):
        with pytest.raises(FileExistsError):
            m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, m2.SetRunning(True), expected_revision=stale)


def test_expected_revision_is_a_mandatory_keyword_validated_before_any_side_effect(worlds, tmp_path):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    before = _files(campaign_dir)
    with pytest.raises(TypeError):
        m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, m2.Start())
    with pytest.raises(TypeError):
        m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, m2.Start(), 1)
    for bad_revision in (None, True, False, -1, 1.0, "1"):
        for command in (m2.Start(), m2.SetRunning(True), m2.MarkTechnicalFailure("boom")):
            with pytest.raises(ValueError):
                m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, command, expected_revision=bad_revision)
    assert _files(campaign_dir) == before  # ni verrou, ni sentinelle, ni écriture
    (campaign_dir / _LOCK).write_bytes(b"busy")  # validée AVANT toute tentative de verrou
    with pytest.raises(ValueError):
        m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, m2.SetRunning(True), expected_revision=-1)


def test_only_the_six_commands_are_accepted_and_a_refused_argument_has_no_side_effect(worlds, tmp_path):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    before = _files(campaign_dir)

    class SneakyStart(m2.Start):
        pass
    for bad_command in (None, {}, "Start", m2.Start, SneakyStart(), object(), _initial(plan)):
        with pytest.raises(ValueError):
            m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, bad_command, expected_revision=1)
    for bad_plan in (worlds.v1_plan, None, worlds.other_plan):
        with pytest.raises(ValueError):
            m2.update_gate_v_campaign_manifest_v2(bad_plan, campaign_dir, m2.Start(), expected_revision=1)
    for bad_dir in (None, "", campaign_dir.parent, tmp_path):
        with pytest.raises(ValueError):
            m2.update_gate_v_campaign_manifest_v2(plan, bad_dir, m2.Start(), expected_revision=1)
    assert _files(campaign_dir) == before
    (campaign_dir / _LOCK).write_bytes(b"busy")  # validation des arguments AVANT toute tentative de verrou
    for bad_command in (None, SneakyStart()):
        with pytest.raises(ValueError):
            m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, bad_command, expected_revision=1)


def test_a_busy_lock_refuses_every_mutation_and_the_loser_never_touches_it(worlds, proofs, tmp_path):
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _started_campaign(tmp_path, plan)
    _persist(campaign_dir, proofs[ids["wf"]])
    lock = campaign_dir / _LOCK
    lock.write_bytes(b'{"command": "held by another writer"}')
    identity = _identity(lock)
    before = _files(campaign_dir)
    for command in (m2.Start(), m2.SetRunning(True), m2.SetRunning(False), m2.AttachWalkForward(ids["wf"])):
        with pytest.raises(FileExistsError):
            m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, command, expected_revision=1)
        assert _files(campaign_dir) == before and _identity(lock) == identity


def test_a_residual_lock_is_never_cleaned_whatever_its_age_or_content(worlds, tmp_path):
    """Aucun stale-lock : ni délai, ni âge du fichier, ni contenu (illisible ou d'apparence valide), ni retry."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    lock = campaign_dir / _LOCK
    for content in (b"", b"garbage", b'{"command": "Start", "campaign_id": "x", "expected_revision": 0}'):
        lock.write_bytes(content)
        os.utime(lock, (946684800, 946684800))  # 2000-01-01 : un verrou « ancien » reste un verrou
        before = _files(campaign_dir)
        for _ in range(3):
            with pytest.raises(FileExistsError):
                m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, m2.SetRunning(True), expected_revision=1)
        assert _files(campaign_dir) == before and os.stat(lock).st_mtime == 946684800
        lock.unlink()  # rôle de la récupération manuelle gouvernée : jamais faite par le module


def test_every_refusal_before_the_write_releases_the_lock_and_leaves_the_manifest_unchanged(worlds, tmp_path):
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _started_campaign(tmp_path, plan)
    before = _files(campaign_dir)
    refusals = (
        (m2.SetRunning("yes"), 1, ValueError),  # charge invalide (D3)
        (m2.AttachMonteCarlo(ids["mc"]), 1, m2.ManifestTransitionError),  # transition interdite (D3)
        (m2.AttachWalkForward("not_the_deterministic_id"), 1, ValueError),
        (m2.SetRunning(True), 0, m2.ManifestTransitionError),  # révision périmée
    )
    for command, revision, error in refusals:
        with pytest.raises(error):
            m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, command, expected_revision=revision)
        assert _files(campaign_dir) == before  # verrou libéré : sortie avant l'étape 9
    (campaign_dir / "manifest.json").write_text("{", encoding="utf-8")  # Manifest illisible relu à l'étape 3
    with pytest.raises(ValueError):
        m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, m2.SetRunning(True), expected_revision=1)
    assert not (campaign_dir / _LOCK).exists()


# ============================================================================================
# Tranche 12 — D4 : preuves RECHARGÉES SOUS LE VERROU (références du Manifest + candidate d'un Attach)
#   Manifest « en avance » = erreur fermée ; Manifest « en retard » = preuve orpheline ignorée jusqu'à l'adoption
# ============================================================================================


def _proof_path(campaign_dir, run_id):
    return campaign_dir / "validations" / run_id / "validation_run.json"


def _corrupt_proof_files(campaign_dir, run_id, proofs):
    """Fichiers de preuve inutilisables au chemin canonique : JSON tronqué (lu comme absent), type inconnu et evidence
    incohérente (`IncoherentValidationRunError`), preuve étrangère (autre stratégie, même identifiant)."""
    path = _proof_path(campaign_dir, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_validation_run(path, dataclasses.replace(proofs[run_id], strategy_name="Other Strategy"))
    foreign = path.read_bytes()
    record = json.loads(foreign)
    return {
        "truncated_json": foreign[: len(foreign) // 2],
        "unknown_validation_type": json.dumps({**record, "validation_type": "stress"}).encode(),
        "incoherent_evidence": json.dumps({**record, "evidence": {"bogus": 1}}).encode(),
        "foreign_provenance": foreign,
    }


def _campaign_with(root, plan, proofs, commands):
    """Campagne démarrée, TOUTES les preuves persistées, puis les `commands` appliquées par l'API persistée."""
    campaign_dir = _started_campaign(root, plan)
    _persist(campaign_dir, *proofs.values())
    for command in commands:
        _update(plan, campaign_dir, command)
    return campaign_dir


def test_a_manifest_ahead_of_its_proofs_fails_closed_before_any_write(worlds, proofs, tmp_path):
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [m2.AttachWalkForward(ids["wf"])])
    _proof_path(campaign_dir, ids["wf"]).unlink()  # la référence persistée n'a plus de preuve
    before = _files(campaign_dir)
    for command in (m2.Start(), m2.SetRunning(True), m2.SetRunning(False), m2.AttachMonteCarlo(ids["mc"])):
        with pytest.raises(ValueError):  # jamais traité comme un simple « incomplet »
            _update(plan, campaign_dir, command)
        assert _files(campaign_dir) == before  # rien d'écrit, verrou libéré


def test_a_corrupt_or_foreign_referenced_proof_fails_closed_before_any_write(worlds, proofs, tmp_path):
    plan = worlds.plan
    ids = _ids(plan)
    for kind, content in _corrupt_proof_files(tmp_path / "scratch", ids["wf"], proofs).items():
        campaign_dir = _campaign_with(tmp_path / kind, plan, proofs, [m2.AttachWalkForward(ids["wf"])])
        _proof_path(campaign_dir, ids["wf"]).write_bytes(content)
        before = _files(campaign_dir)
        for command in (m2.SetRunning(True), m2.SetRunning(False), m2.AttachMonteCarlo(ids["mc"])):
            with pytest.raises(ValueError):
                _update(plan, campaign_dir, command)
            assert _files(campaign_dir) == before, kind


def test_an_orphan_proof_is_ignored_until_an_explicit_attach_adopts_it(worlds, proofs, tmp_path):
    """Manifest « en retard » (preuve persistée, jamais rattachée) : légal ; la preuve n'a aucune autorité tant
    qu'un `Attach…` explicite ne l'a pas validée puis adoptée — jamais une adoption par balayage."""
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [m2.AttachWalkForward(ids["wf"])])
    assert _proof_path(campaign_dir, ids["mc"]).is_file()  # orpheline : persistée, non référencée
    running = _update(plan, campaign_dir, m2.SetRunning(True))
    stopped = _update(plan, campaign_dir, m2.SetRunning(False))
    assert running.monte_carlo_validation_run_id is None and stopped.monte_carlo_validation_run_id is None
    assert stopped.status == "EVIDENCE_INCOMPLETE"  # l'orpheline ne compte jamais
    adopted = _update(plan, campaign_dir, m2.AttachMonteCarlo(ids["mc"]))
    assert adopted.monte_carlo_validation_run_id == ids["mc"] and adopted.running is False
    assert adopted.parameter_stability_validation_run_ids_by_fold == {}  # les PS orphelines restent ignorées


def test_an_attach_loads_its_candidate_at_the_canonical_path_and_refuses_an_absent_or_corrupt_one(
    worlds, proofs, tmp_path,
):
    plan = worlds.plan
    ids = _ids(plan)
    corrupt = _corrupt_proof_files(tmp_path / "scratch", ids["mc"], proofs)
    for kind, content in {"absent": None, **corrupt}.items():
        campaign_dir = _started_campaign(tmp_path / kind, plan)
        _persist(campaign_dir, proofs[ids["wf"]])
        _update(plan, campaign_dir, m2.AttachWalkForward(ids["wf"]))
        if content is not None:
            _proof_path(campaign_dir, ids["mc"]).parent.mkdir(parents=True)
            _proof_path(campaign_dir, ids["mc"]).write_bytes(content)
        before = _files(campaign_dir)
        with pytest.raises(ValueError):
            _update(plan, campaign_dir, m2.AttachMonteCarlo(ids["mc"]))
        assert _files(campaign_dir) == before, kind
    # Identifiant candidat non portable : jamais un chemin hors de `validations/`, refus par D3.
    for bad_run_id in ("../../plan", "..\\..\\plan", "", ["list"], None):
        with pytest.raises(ValueError):
            _update(plan, campaign_dir, m2.AttachMonteCarlo(bad_run_id))


def test_arbitration_b_holds_through_persistence_even_when_the_new_candidate_file_is_corrupt(
    worlds, proofs, tmp_path,
):
    """Remplacer une référence rattachée reste un conflit de transition AVANT tout jugement de la nouvelle preuve,
    même si le fichier de cette preuve est corrompu : D4 ne change jamais l'ordre des refus de D3."""
    plan = worlds.plan
    ids = _ids(plan)
    first, second = plan.expected_fold_ids[:2]
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [
        m2.AttachWalkForward(ids["wf"]), m2.AttachParameterStability(first, ids["ps"][first])])
    for run_id in (ids["mc"], ids["ps"][second]):  # fichiers candidats incohérents (type de validation inconnu)
        _proof_path(campaign_dir, run_id).write_text(
            json.dumps({**_record_of_run(proofs[run_id]), "validation_type": "stress"}), encoding="utf-8")
    before = _files(campaign_dir)
    for command in (
        m2.AttachWalkForward(ids["mc"]),  # emplacement WF déjà rempli par un autre id ; fichier « mc » incohérent
        m2.AttachParameterStability(first, ids["ps"][second]),
    ):
        with pytest.raises(m2.ManifestTransitionError):
            _update(plan, campaign_dir, command)
        assert _files(campaign_dir) == before


def test_d3_refusal_order_is_kept_for_a_corrupt_candidate_when_walk_forward_is_missing(worlds, proofs, tmp_path):
    plan = worlds.plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]
    campaign_dir = _started_campaign(tmp_path, plan)
    for run_id in (ids["mc"], ids["ps"][first]):
        _proof_path(campaign_dir, run_id).parent.mkdir(parents=True)
        _proof_path(campaign_dir, run_id).write_text(
            json.dumps({**_record_of_run(proofs[run_id]), "validation_type": "stress"}), encoding="utf-8")
    before = _files(campaign_dir)
    for command in (m2.AttachMonteCarlo(ids["mc"]), m2.AttachParameterStability(first, ids["ps"][first])):
        with pytest.raises(m2.ManifestTransitionError):  # « WF d'abord » (D3) prime sur le fichier incohérent
            _update(plan, campaign_dir, command)
        assert _files(campaign_dir) == before


def _record_of_run(run):
    """Record JSON d'une ValidationRun tel que `save_validation_run` le persiste."""
    return json.loads(json.dumps(dataclasses.asdict(run)))


# ============================================================================================
# Tranche 13 — D4 : sentinelle `technical_failure.json` (fait exclusif, indépendant du verrou) et statut EFFECTIF
#   existence = le fait ; première sentinelle gagnante ; jamais supprimée, réparée ni réécrite
# ============================================================================================

_UNREADABLE = "technical_failure_sentinel_unreadable"


def _sentinel_record(plan, reason):
    return {
        "technical_failure_sentinel_semantics_version": "gate_v_technical_failure_sentinel_v1",
        "campaign_id": plan.campaign_id, "reason": reason,
    }


def _effective(plan, campaign_dir, evidence=None):
    manifest = m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)
    return m2.derive_gate_v_campaign_v2_effective_status(plan, campaign_dir, manifest, evidence or {})


def test_the_sentinel_constants_are_exact():
    assert m2.GATE_V_TECHNICAL_FAILURE_SENTINEL_SEMANTICS_VERSION == "gate_v_technical_failure_sentinel_v1"
    assert m2.GATE_V_TECHNICAL_FAILURE_SENTINEL_UNREADABLE_REASON == _UNREADABLE


def test_mark_technical_failure_records_the_exact_three_field_sentinel_then_reconciles_the_manifest(worlds, tmp_path):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    _update(plan, campaign_dir, m2.SetRunning(True))
    failed = _update(plan, campaign_dir, m2.MarkTechnicalFailure("worker crashed"))
    sentinel = json.loads((campaign_dir / _SENTINEL).read_text(encoding="utf-8"))
    assert sentinel == _sentinel_record(plan, "worker crashed")  # 3 clés exactes : ni horodatage, PID, hôte, chemin
    assert (failed.status, failed.technical_failure_reason, failed.running) == (
        "TECHNICAL_FAILURE", "worker crashed", False)
    assert failed.manifest_revision == 3 and m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir) == failed
    assert set(_files(campaign_dir)) == {"plan.json", "manifest.json", _SENTINEL}  # verrou supprimé, aucun Claim


def test_mark_technical_failure_requires_a_started_campaign_and_never_poses_a_sentinel_otherwise(worlds, tmp_path):
    plan = worlds.plan
    campaign_dir = _campaign(tmp_path, plan)
    with pytest.raises(ValueError):  # Manifest absent : lecture non verrouillée impossible, aucun fait posé
        m2.update_gate_v_campaign_manifest_v2(
            plan, campaign_dir, m2.MarkTechnicalFailure("boom"), expected_revision=0)
    m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
    before = _files(campaign_dir)
    with pytest.raises(m2.ManifestTransitionError):
        m2.update_gate_v_campaign_manifest_v2(
            plan, campaign_dir, m2.MarkTechnicalFailure("boom"), expected_revision=0)
    for bad_reason in ("", "   ", None, 7):
        with pytest.raises(ValueError):
            m2.update_gate_v_campaign_manifest_v2(
                plan, campaign_dir, m2.MarkTechnicalFailure(bad_reason), expected_revision=0)
    assert _files(campaign_dir) == before  # ni sentinelle irréconciliable, ni verrou
    _update(plan, campaign_dir, m2.Start())
    started = _files(campaign_dir)
    for bad_reason in ("", "   ", None, 7, ["boom"]):  # campagne démarrée : motif invalide, toujours AUCUNE sentinelle
        with pytest.raises(ValueError):
            _update(plan, campaign_dir, m2.MarkTechnicalFailure(bad_reason))
    assert _files(campaign_dir) == started


def test_the_failure_fact_is_recorded_while_the_lock_is_busy_and_reconciled_later_with_its_reason(worlds, tmp_path):
    """ADR §21.13 n° 13 : sentinelle créée même verrou occupé (et seulement campagne démarrée) ; le Manifest est
    simplement « en retard » (légal, chargeable) jusqu'à la réconciliation par la SEULE reason de la sentinelle."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    lock = campaign_dir / _LOCK
    lock.write_bytes(b"held by another writer")
    identity = _identity(lock)
    with pytest.raises(FileExistsError):
        _update(plan, campaign_dir, m2.MarkTechnicalFailure("worker crashed"))
    assert json.loads((campaign_dir / _SENTINEL).read_text(encoding="utf-8")) == _sentinel_record(
        plan, "worker crashed")
    assert _identity(lock) == identity and lock.read_bytes() == b"held by another writer"
    behind = m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)
    assert behind.technical_failure_reason is None and behind.status == "EVIDENCE_INCOMPLETE"  # en retard, légal
    assert _effective(plan, campaign_dir) == "TECHNICAL_FAILURE"
    lock.unlink()  # rôle de la récupération manuelle gouvernée
    sentinel_bytes = (campaign_dir / _SENTINEL).read_bytes()
    with pytest.raises(m2.ManifestTransitionError):  # une autre reason ne réconcilie jamais
        _update(plan, campaign_dir, m2.MarkTechnicalFailure("another reason"))
    reconciled = _update(plan, campaign_dir, m2.MarkTechnicalFailure("worker crashed"))
    assert reconciled.status == "TECHNICAL_FAILURE" and reconciled.manifest_revision == 2
    assert _update(plan, campaign_dir, m2.MarkTechnicalFailure("worker crashed")) == reconciled  # idempotente
    assert (campaign_dir / _SENTINEL).read_bytes() == sentinel_bytes  # jamais réécrite


def test_a_second_technical_failure_never_overwrites_the_first_sentinel(worlds, tmp_path, monkeypatch):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    first = _update(plan, campaign_dir, m2.MarkTechnicalFailure("first failure"))
    before = _files(campaign_dir)
    with pytest.raises(m2.ManifestTransitionError):
        _update(plan, campaign_dir, m2.MarkTechnicalFailure("second failure"))
    assert _files(campaign_dir) == before  # la première sentinelle gagne, rien n'est réécrit

    def no_write(*args, **kwargs):
        raise AssertionError("une réconciliation déjà faite n'écrit plus rien")
    monkeypatch.setattr(m2, "save_atomic_overwrite", no_write)
    assert _update(plan, campaign_dir, m2.MarkTechnicalFailure("first failure")) == first
    assert _files(campaign_dir) == before


def _unusable_sentinel_contents(plan, other_plan):
    valid = _sentinel_record(plan, "worker crashed")
    return {
        "empty": b"",
        "truncated": json.dumps(valid).encode()[:25],
        "not_json": b"garbage",
        "json_list": b"[]",
        "wrong_version": json.dumps({**valid, "technical_failure_sentinel_semantics_version": "v0"}).encode(),
        "foreign_campaign": json.dumps({**valid, "campaign_id": other_plan.campaign_id}).encode(),
        "extra_key": json.dumps({**valid, "pid": 1234}).encode(),
        "missing_key": json.dumps({"campaign_id": plan.campaign_id, "reason": "worker crashed"}).encode(),
        "empty_reason": json.dumps({**valid, "reason": ""}).encode(),
        "blank_reason": json.dumps({**valid, "reason": "   "}).encode(),
        "non_string_reason": json.dumps({**valid, "reason": 42}).encode(),
        # JSON ASCII valide (échappement \udc80) mais motif NON persistable : jamais un motif autoritaire
        "unpersistable_reason": json.dumps({**valid, "reason": "disk \udc80 full"}).encode(),
    }


def test_an_unreadable_or_nonconforming_sentinel_is_a_failure_reconciled_only_with_the_fixed_reason(
    worlds, tmp_path,
):
    """ADR §21.8 : existence = le fait (même vide ou tronquée après un crash entre `O_EXCL` et l'écriture) ; motif de
    réconciliation fixe ; jamais supprimée, réparée ni réécrite."""
    plan = worlds.plan
    for kind, content in _unusable_sentinel_contents(plan, worlds.other_plan).items():
        campaign_dir = _started_campaign(tmp_path / kind, plan)
        (campaign_dir / _SENTINEL).write_bytes(content)
        assert _effective(plan, campaign_dir) == "TECHNICAL_FAILURE", kind
        before = _files(campaign_dir)
        with pytest.raises(m2.ManifestTransitionError):
            _update(plan, campaign_dir, m2.MarkTechnicalFailure("worker crashed"))
        assert _files(campaign_dir) == before, kind
        reconciled = _update(plan, campaign_dir, m2.MarkTechnicalFailure(_UNREADABLE))
        assert reconciled.technical_failure_reason == _UNREADABLE and reconciled.status == "TECHNICAL_FAILURE", kind
        assert (campaign_dir / _SENTINEL).read_bytes() == content, kind  # jamais réparée


def test_the_fixed_unreadable_reason_recorded_in_the_manifest_is_tolerated_permanently(worlds, tmp_path, monkeypatch):
    """Sentinelle lisible mais illisible AU MOMENT de la réconciliation (lecture transitoire bloquée) : le Manifest
    garde `technical_failure_sentinel_unreadable` pour toujours, sans jamais être réécrit avec la vraie reason."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    (campaign_dir / _LOCK).write_bytes(b"")
    with pytest.raises(FileExistsError):
        _update(plan, campaign_dir, m2.MarkTechnicalFailure("disk full"))
    (campaign_dir / _LOCK).unlink()
    real_load = m2.load_json_tolerant

    def sentinel_blocked(path):
        return None if os.path.basename(path) == _SENTINEL else real_load(path)
    with monkeypatch.context() as patched:
        patched.setattr(m2, "load_json_tolerant", sentinel_blocked)
        reconciled = _update(plan, campaign_dir, m2.MarkTechnicalFailure(_UNREADABLE))
    assert reconciled.technical_failure_reason == _UNREADABLE
    before = _files(campaign_dir)
    assert _update(plan, campaign_dir, m2.MarkTechnicalFailure(_UNREADABLE)) == reconciled  # tolérée, idempotente
    with pytest.raises(m2.ManifestTransitionError):  # la vraie reason, redevenue lisible, ne réécrit jamais le Manifest
        _update(plan, campaign_dir, m2.MarkTechnicalFailure("disk full"))
    assert _files(campaign_dir) == before


def test_every_other_command_is_refused_once_the_sentinel_exists_even_without_the_manifest_marker(
    worlds, proofs, tmp_path,
):
    """Étape 5 : « sans échec » inclut l'existence de la sentinelle ; TECHNICAL_FAILURE est terminal effectivement."""
    plan = worlds.plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [m2.AttachWalkForward(ids["wf"])])
    for content in (json.dumps(_sentinel_record(plan, "worker crashed")).encode(), b""):
        (campaign_dir / _SENTINEL).write_bytes(content)
        before = _files(campaign_dir)
        for command in (
            m2.Start(), m2.SetRunning(True), m2.SetRunning(False), m2.AttachWalkForward(ids["wf"]),
            m2.AttachMonteCarlo(ids["mc"]), m2.AttachParameterStability(first, ids["ps"][first]),
        ):
            with pytest.raises(m2.ManifestTransitionError):
                _update(plan, campaign_dir, command)
            assert _files(campaign_dir) == before  # rien d'écrit, verrou libéré


def test_effective_status_is_technical_failure_as_soon_as_the_sentinel_path_exists_else_the_marker_status(
    worlds, proofs, tmp_path,
):
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _campaign(tmp_path, plan)
    m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
    assert _effective(plan, campaign_dir) == "READY_FOR_EXECUTION"
    _persist(campaign_dir, *proofs.values())
    commands = [m2.Start(), m2.SetRunning(True), m2.AttachWalkForward(ids["wf"]), m2.AttachMonteCarlo(ids["mc"])]
    commands += [m2.AttachParameterStability(fold, ids["ps"][fold]) for fold in plan.expected_fold_ids]
    for command in commands:
        manifest = _update(plan, campaign_dir, command)
        assert _effective(plan, campaign_dir, dict(proofs)) == _derive(plan, manifest, dict(proofs)) == manifest.status
    assert manifest.status == _COMPLETE
    sentinel = campaign_dir / _SENTINEL
    for make in (lambda: sentinel.write_bytes(b""), lambda: sentinel.write_bytes(b"{trunc"), sentinel.mkdir):
        make()
        # existence seule : aucune lecture de preuve, même un mapping piégé n'est jamais inspecté
        assert m2.derive_gate_v_campaign_v2_effective_status(plan, campaign_dir, manifest, _Tripwire()) == (
            "TECHNICAL_FAILURE")
        assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir).status == _COMPLETE  # le marqueur, distinct
        sentinel.rmdir() if sentinel.is_dir() else sentinel.unlink()
    for sentinel_present in (False, True):  # le Manifest fourni reste validé, sentinelle ou non
        if sentinel_present:
            sentinel.write_bytes(b"")
        for bad_manifest in (_initial(worlds.other_plan), None, _with(manifest, final_holdout_claim_id="x")):
            with pytest.raises(ValueError):
                m2.derive_gate_v_campaign_v2_effective_status(plan, campaign_dir, bad_manifest, dict(proofs))
        with pytest.raises(ValueError):
            m2.derive_gate_v_campaign_v2_effective_status(plan, campaign_dir.parent, manifest, dict(proofs))


def test_mark_technical_failure_needs_no_usable_proof_through_persistence(worlds, proofs, tmp_path):
    """Exception D3 conservée par D4 : l'échec s'enregistre même si les preuves référencées sont absentes ou
    corrompues (aucun rechargement de preuve pour `MarkTechnicalFailure`)."""
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [
        m2.AttachWalkForward(ids["wf"]), m2.AttachMonteCarlo(ids["mc"])])
    _proof_path(campaign_dir, ids["wf"]).unlink()
    _proof_path(campaign_dir, ids["mc"]).write_text(  # incohérente : la RECHARGER lèverait une erreur
        json.dumps({**_record_of_run(proofs[ids["mc"]]), "validation_type": "stress"}), encoding="utf-8")
    failed = _update(plan, campaign_dir, m2.MarkTechnicalFailure("proof unreadable"))
    assert failed.status == "TECHNICAL_FAILURE" and failed.manifest_revision == 4
    assert (failed.walk_forward_validation_run_id, failed.monte_carlo_validation_run_id) == (ids["wf"], ids["mc"])
    assert json.loads((campaign_dir / _SENTINEL).read_text(encoding="utf-8")) == _sentinel_record(
        plan, "proof unreadable")


def test_a_stale_mark_technical_failure_keeps_the_fact_but_refuses_the_transition(worlds, tmp_path):
    """La sentinelle ne dépend d'aucune révision (fait indépendant du verrou) ; la transition du Manifest, elle,
    exige la révision rechargée sous verrou : refus, verrou libéré, réconciliation par rejeu à la bonne révision."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    with pytest.raises(m2.ManifestTransitionError):
        m2.update_gate_v_campaign_manifest_v2(
            plan, campaign_dir, m2.MarkTechnicalFailure("worker crashed"), expected_revision=0)
    assert (campaign_dir / _SENTINEL).is_file() and not (campaign_dir / _LOCK).exists()
    assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir).technical_failure_reason is None
    assert _effective(plan, campaign_dir) == "TECHNICAL_FAILURE"
    assert _update(plan, campaign_dir, m2.MarkTechnicalFailure("worker crashed")).status == "TECHNICAL_FAILURE"


def test_a_sentinel_appearing_after_the_linearization_point_lets_the_attach_commit_without_losing_the_fact(
    worlds, proofs, tmp_path, monkeypatch,
):
    """S6 (version en un seul processus ; la course entre processus réels est testée plus bas) : la sentinelle
    apparaît pendant l'étape 6 d'un `Attach…` ; l'Attach aboutit (aucune revérification après l'étape 5), le fait
    est conservé (`effective_status`), puis `MarkTechnicalFailure` réconcilie le Manifest."""
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [m2.AttachWalkForward(ids["wf"])])
    real_load = m2.load_validation_run

    def sentinel_appears(path):
        if not (campaign_dir / _SENTINEL).exists():
            (campaign_dir / _SENTINEL).write_text(
                json.dumps(_sentinel_record(plan, "worker crashed")), encoding="utf-8")
        return real_load(path)
    with monkeypatch.context() as patched:
        patched.setattr(m2, "load_validation_run", sentinel_appears)
        attached = _update(plan, campaign_dir, m2.AttachMonteCarlo(ids["mc"]))
    assert attached.monte_carlo_validation_run_id == ids["mc"] and attached.status == "EVIDENCE_INCOMPLETE"
    assert _effective(plan, campaign_dir) == "TECHNICAL_FAILURE"
    reconciled = _update(plan, campaign_dir, m2.MarkTechnicalFailure("worker crashed"))
    assert reconciled.status == "TECHNICAL_FAILURE" and reconciled.monte_carlo_validation_run_id == ids["mc"]


# ============================================================================================
# Tranche 14 — D4 : propriété et libération du verrou, classification des échecs d'écriture (ADR 0025 §21.8)
#   refus (rien d'écrit) / validé avec verrou résiduel / incertain : trois catégories jamais confondues
# ============================================================================================


class _LockSyscalls:
    """Espionne et perturbe les SEULS appels système visant `manifest.update.lock` ; tous les autres sont délégués
    tels quels. Simule les échecs Windows (antivirus, indexeur, suppression différée) sans aucun crochet de test
    dans le code de production."""

    def __init__(self, monkeypatch, campaign_dir):
        self.lock_path = campaign_dir / _LOCK
        self._normalized = os.path.normcase(os.path.abspath(self.lock_path))
        self.calls = []
        self.fds = set()
        self.open_error = None
        self.write_error = None
        self.fstat_error = None
        self.unlink_errors = []  # erreurs des PROCHAINS `unlink` du verrou, dans l'ordre
        self.stat_errors = []  # erreurs des PROCHAINS `os.stat` du verrou (lecture d'identité transitoirement bloquée)
        self.after_close = None  # appelé une fois, juste après la fermeture du descripteur du verrou
        # `os.stat(verrou)` décrit un AUTRE fichier tant que le descripteur du propriétaire est OUVERT (renommage
        # gouverné possible sous POSIX pendant la détention), puis de nouveau le fichier du propriétaire.
        self.foreign_identity_while_open = False
        self.zero_identity = False  # `os.fstat(fd)` sans identité de fichier (`st_ino == 0`, système non conforme)
        self.real = SimpleNamespace(
            open=os.open, write=os.write, fstat=os.fstat, close=os.close, unlink=os.unlink, stat=os.stat)
        for name in ("open", "write", "fstat", "close", "unlink", "stat"):
            monkeypatch.setattr(os, name, getattr(self, "_" + name))

    def _is_lock(self, path):
        if isinstance(path, int):
            return False
        return os.path.normcase(os.path.abspath(os.fspath(path))) == self._normalized

    def _open(self, path, flags, *args, **kwargs):
        if not self._is_lock(path):
            return self.real.open(path, flags, *args, **kwargs)
        self.calls.append(("open", flags))
        if self.open_error is not None:
            raise self.open_error
        fd = self.real.open(path, flags, *args, **kwargs)
        self.fds.add(fd)
        return fd

    def _write(self, fd, data):
        if fd in self.fds:
            self.calls.append(("write", bytes(data)))
            if self.write_error is not None:
                raise self.write_error
        return self.real.write(fd, data)

    def _fstat(self, fd, *args, **kwargs):
        result = self.real.fstat(fd, *args, **kwargs)
        if fd not in self.fds:
            return result
        self.calls.append(("fstat", None))
        if self.fstat_error is not None:
            raise self.fstat_error
        if not self.zero_identity:
            return result
        values = list(result[:10])
        values[1] = 0  # st_ino non fourni
        return os.stat_result(values)

    def _close(self, fd):
        if fd not in self.fds:
            return self.real.close(fd)
        self.calls.append(("close", None))
        self.fds.discard(fd)
        self.real.close(fd)
        hook, self.after_close = self.after_close, None
        if hook is not None:
            hook()
        return None

    def _unlink(self, path, *args, **kwargs):
        if not self._is_lock(path):
            return self.real.unlink(path, *args, **kwargs)
        self.calls.append(("unlink", None))
        if self.unlink_errors:
            raise self.unlink_errors.pop(0)
        return self.real.unlink(path, *args, **kwargs)

    def _stat(self, path, *args, **kwargs):
        if not self._is_lock(path):
            return self.real.stat(path, *args, **kwargs)
        self.calls.append(("stat", None))
        if self.stat_errors:
            raise self.stat_errors.pop(0)
        result = self.real.stat(path, *args, **kwargs)
        if not (self.foreign_identity_while_open and self.fds):
            return result
        values = list(result[:10])
        values[1] += 1  # st_ino d'un autre fichier, même volume
        return os.stat_result(values)

    def operations(self):
        return [operation for operation, _ in self.calls]


def _antivirus(*args, **kwargs):
    raise PermissionError(13, "fichier tenu ouvert par un antivirus")


def test_the_four_persistence_outcomes_are_distinct_types_never_merged():
    errors = (m2.ManifestLockAcquisitionError, m2.ManifestWriteError, m2.ManifestWriteUncertainError,
              m2.ManifestLockReleaseError)
    for error in errors:
        assert issubclass(error, Exception)
        assert not issubclass(error, (ValueError, OSError)), error  # ni une transition refusée, ni un verrou occupé
        assert not any(issubclass(error, other) for other in errors if other is not error), error
    for committed in (True, False):
        assert m2.ManifestLockReleaseError("lock left", committed=committed).committed is committed
    with pytest.raises(TypeError):  # `committed` est toujours explicite
        m2.ManifestLockReleaseError("lock left")


def test_the_lock_is_one_exclusive_os_open_with_the_mandated_flags_and_no_prior_existence_check(worlds, tmp_path,
                                                                                               monkeypatch):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    syscalls = _LockSyscalls(monkeypatch, campaign_dir)
    _update(plan, campaign_dir, m2.SetRunning(True))
    assert syscalls.calls[0] == ("open", os.O_CREAT | os.O_EXCL | os.O_WRONLY)  # l'appel exclusif EST l'autorité
    # Propriété vérifiée juste avant l'écriture (étape 9) ; libération normale : identité vérifiée descripteur ouvert,
    # fermeture, identité revérifiée, PUIS suppression.
    assert syscalls.operations() == ["open", "fstat", "write", "stat", "stat", "close", "stat", "unlink"]
    content = json.loads(next(data for operation, data in syscalls.calls if operation == "write"))
    assert content == {"command": "SetRunning", "campaign_id": plan.campaign_id, "expected_revision": 1}


def test_a_busy_lock_loser_never_enters_the_release_logic(worlds, tmp_path, monkeypatch):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    (campaign_dir / _LOCK).write_bytes(b"winner")
    syscalls = _LockSyscalls(monkeypatch, campaign_dir)
    with pytest.raises(FileExistsError):
        _update(plan, campaign_dir, m2.SetRunning(True))
    assert syscalls.operations() == ["open"]  # ni stat, ni close, ni unlink du verrou du gagnant
    assert (campaign_dir / _LOCK).read_bytes() == b"winner"


def test_any_other_os_error_at_acquisition_is_a_typed_refusal_that_never_touches_the_existing_path(
    worlds, tmp_path, monkeypatch,
):
    """ADR §21.13 n° 14 et 17 : sous Windows un verrou en suppression différée lève `PermissionError`, pas
    `FileExistsError` ; refus fermé, aucune écriture, et le chemin existant n'est jamais supprimé."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    for pre_existing in (True, False):
        lock = campaign_dir / _LOCK
        if pre_existing:
            lock.write_bytes(b"delete pending")
        before = _files(campaign_dir)
        with monkeypatch.context() as patched:
            syscalls = _LockSyscalls(patched, campaign_dir)
            syscalls.open_error = PermissionError(13, "suppression différée en cours")
            with pytest.raises(m2.ManifestLockAcquisitionError) as raised:
                _update(plan, campaign_dir, m2.SetRunning(True))
        assert isinstance(raised.value.__cause__, PermissionError)
        assert syscalls.operations() == ["open"]  # aucune libération : ce verrou n'a jamais été acquis
        assert _files(campaign_dir) == before
        if pre_existing:
            lock.unlink()


def test_a_lock_content_write_failure_releases_the_lock_before_any_manifest_write(worlds, tmp_path, monkeypatch):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    before = _files(campaign_dir)
    syscalls = _LockSyscalls(monkeypatch, campaign_dir)
    syscalls.write_error = OSError(28, "disque plein")
    with pytest.raises(OSError) as raised:
        _update(plan, campaign_dir, m2.SetRunning(True))
    assert raised.value.errno == 28
    assert syscalls.operations()[-1] == "unlink" and _files(campaign_dir) == before  # libéré, rien d'écrit


def test_a_failed_release_before_any_write_reports_not_committed_without_any_second_attempt(
    worlds, tmp_path, monkeypatch,
):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    manifest_before = (campaign_dir / "manifest.json").read_bytes()
    for command, revision in ((m2.SetRunning(True), 0), (m2.Start(), 1)):  # refus (révision périmée), idempotente
        with monkeypatch.context() as patched:
            syscalls = _LockSyscalls(patched, campaign_dir)
            syscalls.unlink_errors = [PermissionError(13, "antivirus")]
            with pytest.raises(m2.ManifestLockReleaseError) as raised:
                m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, command, expected_revision=revision)
        assert raised.value.committed is False  # rien n'a été écrit par cette transaction
        assert syscalls.operations().count("unlink") == 1  # la nouvelle tentative est réservée au commit vérifié
        assert (campaign_dir / _LOCK).exists() and (campaign_dir / "manifest.json").read_bytes() == manifest_before
        (campaign_dir / _LOCK).unlink()  # récupération manuelle gouvernée


def test_an_unlink_failure_after_a_verified_commit_gets_exactly_one_immediate_retry(worlds, tmp_path, monkeypatch):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    syscalls = _LockSyscalls(monkeypatch, campaign_dir)
    syscalls.unlink_errors = [PermissionError(13, "antivirus")]
    running = _update(plan, campaign_dir, m2.SetRunning(True))
    assert running.manifest_revision == 2 and m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir) == running
    assert syscalls.operations().count("unlink") == 2 and not (campaign_dir / _LOCK).exists()


def test_a_second_unlink_failure_after_a_verified_commit_is_committed_with_a_residual_lock(
    worlds, tmp_path, monkeypatch,
):
    """ADR §21.13 n° 16 : la transaction est VALIDÉE (jamais rapportée comme « rien d'écrit ») mais le verrou reste."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    syscalls = _LockSyscalls(monkeypatch, campaign_dir)
    syscalls.unlink_errors = [PermissionError(13, "antivirus"), PermissionError(13, "antivirus")]
    with pytest.raises(m2.ManifestLockReleaseError) as raised:
        _update(plan, campaign_dir, m2.SetRunning(True))
    assert raised.value.committed is True
    assert syscalls.operations().count("unlink") == 2  # jamais une troisième tentative, aucune attente
    assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir).manifest_revision == 2
    assert (campaign_dir / _LOCK).exists()
    with pytest.raises(FileExistsError):  # le verrou résiduel bloque toute mutation suivante
        _update(plan, campaign_dir, m2.SetRunning(False))


def test_the_owner_never_unlinks_a_lock_replaced_right_after_it_closed_its_descriptor(worlds, tmp_path, monkeypatch):
    """Renommage gouverné RÉEL puis nouveau verrou au même chemin, dans la fenêtre fermeture -> suppression (la seule
    où Windows permet de renommer le verrou d'un propriétaire) : l'identité revérifiée diffère, rien n'est supprimé."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    lock, recovered = campaign_dir / _LOCK, campaign_dir / (_LOCK + ".recovered.1")
    syscalls = _LockSyscalls(monkeypatch, campaign_dir)

    def governed_recovery_then_new_writer():
        os.rename(lock, recovered)
        fd = syscalls.real.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        syscalls.real.write(fd, b"new writer")
        syscalls.real.close(fd)
    syscalls.after_close = governed_recovery_then_new_writer
    with pytest.raises(m2.ManifestLockReleaseError) as raised:
        _update(plan, campaign_dir, m2.SetRunning(True))
    assert raised.value.committed is True  # Manifest vérifié persisté avant la libération
    assert "unlink" not in syscalls.operations()
    assert lock.read_bytes() == b"new writer" and recovered.exists()
    assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir).manifest_revision == 2
    lock.unlink()  # récupération manuelle gouvernée (journalisée par l'espion : journal remis à zéro ci-dessous)
    syscalls.calls.clear()
    # Verrou disparu (hors API) dans la même fenêtre : identité illisible = non possédé, aucune suppression tentée.
    syscalls.after_close = lambda: os.rename(lock, campaign_dir / "gone.lock")
    with pytest.raises(m2.ManifestLockReleaseError) as raised:
        _update(plan, campaign_dir, m2.SetRunning(False))
    assert raised.value.committed is True and "unlink" not in syscalls.operations()


def test_the_owner_never_unlinks_a_lock_whose_identity_changed_while_it_was_held(worlds, tmp_path, monkeypatch):
    """Identité au chemin différente de `os.fstat(fd)` constatée descripteur ENCORE OUVERT : jamais de suppression,
    même si une lecture ultérieure redonnait la bonne identité. Étape 9 « uniquement sous un verrou possédé » : une
    commande effective n'écrit RIEN (jamais deux écrivains validés) ; erreur typée `committed=False`."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    manifest_before = (campaign_dir / "manifest.json").read_bytes()
    for command in (m2.SetRunning(True), m2.Start()):  # effective, idempotente
        with monkeypatch.context() as patched:
            writes = _persistence_spy(patched, lambda path, data, kind, real: real(path, data, kind))
            syscalls = _LockSyscalls(patched, campaign_dir)
            syscalls.foreign_identity_while_open = True
            with pytest.raises(m2.ManifestLockReleaseError) as raised:
                _update(plan, campaign_dir, command)
        assert raised.value.committed is False and writes == []  # aucune tentative d'écriture
        assert "unlink" not in syscalls.operations() and "close" in syscalls.operations()
        assert (campaign_dir / _LOCK).exists()
        (campaign_dir / _LOCK).unlink()  # récupération manuelle gouvernée
    assert (campaign_dir / "manifest.json").read_bytes() == manifest_before


def test_an_identity_that_cannot_be_read_after_acquisition_leaves_the_lock_and_writes_nothing(
    worlds, tmp_path, monkeypatch,
):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    manifest_before = (campaign_dir / "manifest.json").read_bytes()
    syscalls = _LockSyscalls(monkeypatch, campaign_dir)
    syscalls.fstat_error = OSError(5, "erreur d'entrée-sortie")
    with pytest.raises(m2.ManifestLockReleaseError) as raised:
        _update(plan, campaign_dir, m2.SetRunning(True))
    assert raised.value.committed is False
    assert syscalls.operations() == ["open", "fstat", "close"]  # descripteur fermé, verrou jamais supprimé
    assert (campaign_dir / _LOCK).exists()
    assert (campaign_dir / "manifest.json").read_bytes() == manifest_before


def _persistence_spy(monkeypatch, write):
    """Remplace l'écriture atomique du Manifest par `write(path, data, kind, real)` ; compte les appels."""
    real = m2.save_atomic_overwrite
    calls = []

    def spy(path, data, kind):
        calls.append(path)
        return write(path, data, kind, real)
    monkeypatch.setattr(m2, "save_atomic_overwrite", spy)
    return calls


def test_a_permission_error_at_the_write_with_the_old_manifest_on_disk_is_a_refusal_that_releases_the_lock(
    worlds, tmp_path, monkeypatch,
):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    before = _files(campaign_dir)
    calls = _persistence_spy(monkeypatch, lambda path, data, kind, real: _antivirus())
    with pytest.raises(m2.ManifestWriteError) as raised:
        _update(plan, campaign_dir, m2.SetRunning(True))
    assert isinstance(raised.value.__cause__, PermissionError)
    assert len(calls) == 1  # aucun retry automatique de l'écriture
    assert _files(campaign_dir) == before  # rien d'écrit, verrou libéré


def test_a_replacement_that_happened_despite_the_permission_error_is_a_committed_success(worlds, tmp_path,
                                                                                       monkeypatch):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)

    def replaced_then_failed(path, data, kind, real):
        real(path, data, kind)
        _antivirus()
    calls = _persistence_spy(monkeypatch, replaced_then_failed)
    running = _update(plan, campaign_dir, m2.SetRunning(True))
    assert running.manifest_revision == 2 and running.running is True and len(calls) == 1
    assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir) == running
    assert not (campaign_dir / _LOCK).exists()


def test_a_write_error_followed_by_an_impossible_reread_is_uncertain_and_keeps_the_lock(worlds, tmp_path,
                                                                                       monkeypatch):
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    real_load = m2.load_json_tolerant
    failed = []

    def failed_write(path, data, kind, real):
        failed.append(True)
        _antivirus()

    def reread_impossible(path):
        if failed and os.path.basename(path) == "manifest.json":
            raise PermissionError(13, "relecture bloquée")
        return real_load(path)
    calls = _persistence_spy(monkeypatch, failed_write)
    monkeypatch.setattr(m2, "load_json_tolerant", reread_impossible)
    with monkeypatch.context() as patched:
        syscalls = _LockSyscalls(patched, campaign_dir)
        with pytest.raises(m2.ManifestWriteUncertainError) as raised:
            _update(plan, campaign_dir, m2.SetRunning(True))
    assert isinstance(raised.value.__cause__, PermissionError) and len(calls) == 1
    assert (campaign_dir / _LOCK).exists()  # état incertain : verrou CONSERVÉ
    assert syscalls.operations()[-1] == "close" and "unlink" not in syscalls.operations()  # descripteur fermé
    monkeypatch.setattr(m2, "load_json_tolerant", real_load)
    with pytest.raises(FileExistsError):
        _update(plan, campaign_dir, m2.SetRunning(True))


def test_a_persisted_state_that_is_neither_old_nor_new_after_the_write_is_uncertain_and_keeps_the_lock(
    worlds, tmp_path, monkeypatch,
):
    plan = worlds.plan
    third = _record(_with(_api_started(plan), manifest_revision=9))  # Manifest valide, ni l'ancien ni le nouveau
    for raises in (True, False):  # pendant l'écriture (étape 9) ou à la vérification (étape 10)
        campaign_dir = _started_campaign(tmp_path / str(raises), plan)

        def wrote_something_else(path, data, kind, real, raises=raises):
            real(path, third, kind)
            if raises:
                _antivirus()
        with monkeypatch.context() as patched:
            calls = _persistence_spy(patched, wrote_something_else)
            with pytest.raises(m2.ManifestWriteUncertainError):
                _update(plan, campaign_dir, m2.SetRunning(True))
        assert len(calls) == 1 and (campaign_dir / _LOCK).exists()


def test_a_write_that_returned_but_left_the_old_manifest_follows_the_same_rule_as_a_failed_write(
    worlds, tmp_path, monkeypatch,
):
    """Étape 10 : relecture == ancien -> rien n'est validé : verrou libéré, `ManifestWriteError` (même règle)."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    before = _files(campaign_dir)
    _persistence_spy(monkeypatch, lambda path, data, kind, real: None)
    with pytest.raises(m2.ManifestWriteError):
        _update(plan, campaign_dir, m2.SetRunning(True))
    assert _files(campaign_dir) == before


# ============================================================================================
# Tranche 15 — D4 : concurrence et crash entre PROCESSUS RÉELS (`spawn`, jamais des threads ni des mocks)
#   synchronisation par barrière et événements ; les délais ne sont que des garde-fous, jamais une synchronisation
# ============================================================================================

_SPAWN = multiprocessing.get_context("spawn")
_GUARD_TIMEOUT = 60  # secondes : un processus bloqué fait échouer le test, il ne le synchronise jamais
_CRASH_EXIT_CODE = 17


def _plan_of(campaign_dir):
    return load_gate_v_campaign_plan_v2(os.path.join(campaign_dir, "plan.json"))


def _process_create(campaign_dir, start, outcomes, label):
    """Processus créateur réel : attend la barrière commune puis tente la création initiale exclusive."""
    plan = _plan_of(campaign_dir)
    start.wait(_GUARD_TIMEOUT)
    try:
        m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
        outcomes.put((label, "OK"))
    except BaseException as error:  # rapporté au parent, jamais avalé
        outcomes.put((label, type(error).__name__))


def _process_update(campaign_dir, command, expected_revision, outcomes, label, *, start=None, hold_at=None,
                    held=None, release=None):
    """Processus écrivain réel. `hold_at` : nom d'une fonction PRIVÉE du module remplacée DANS CE SEUL PROCESSUS
    par une version qui signale `held` puis attend `release` : la fenêtre de course est forcée par synchronisation
    (aucun crochet de test dans le code de production, aucune attente temporisée)."""
    plan = _plan_of(campaign_dir)
    if hold_at is not None:
        original = getattr(m2, hold_at)

        def holding(*args, **kwargs):
            held.set()
            if not release.wait(_GUARD_TIMEOUT):
                raise TimeoutError("release jamais signalé par le parent")
            return original(*args, **kwargs)
        setattr(m2, hold_at, holding)
    if start is not None:
        start.wait(_GUARD_TIMEOUT)
    try:
        result = m2.update_gate_v_campaign_manifest_v2(
            plan, campaign_dir, command, expected_revision=expected_revision)
        outcomes.put((label, "OK", result.manifest_revision))
    except BaseException as error:  # rapporté au parent, jamais avalé
        outcomes.put((label, type(error).__name__, None))


def _process_crash(campaign_dir, command, expected_revision, crash_at):
    """Crash DUR (`os._exit`) au point `crash_at` d'une mise à jour : aucun `finally`, aucune libération."""
    plan = _plan_of(campaign_dir)

    def crash(*args, **kwargs):
        os._exit(_CRASH_EXIT_CODE)
    if crash_at == "inside_save_atomic_overwrite":
        def crash_mid_write(path, data, kind):
            temporary = path.with_name(path.name + ".crashed.tmp")  # temporaire partiel, jamais remplacé
            temporary.write_text(json.dumps(data)[:40], encoding="utf-8")
            crash()
        m2.save_atomic_overwrite = crash_mid_write
    else:
        setattr(m2, crash_at, crash)
    m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, command, expected_revision=expected_revision)
    os._exit(0)  # jamais atteint si le crash a eu lieu


def _start(*processes):
    for process in processes:
        process.start()


def _join(*processes):
    for process in processes:
        process.join(_GUARD_TIMEOUT)
        if process.is_alive():
            process.kill()
            process.join(_GUARD_TIMEOUT)


def _race_on_the_lock(campaign_dir, commands_by_label, expected_revision):
    """Deux processus réels, même révision : barrière commune, le gagnant TIENT le verrou juste après l'acquisition
    jusqu'à ce que le perdant ait rapporté son issue — le perdant a donc forcément tenté pendant la détention."""
    start, held, release, outcomes = _SPAWN.Barrier(2), _SPAWN.Event(), _SPAWN.Event(), _SPAWN.Queue()
    workers = [
        _SPAWN.Process(target=_process_update, args=(str(campaign_dir), command, expected_revision, outcomes, label),
                       kwargs=dict(start=start, hold_at="_write_lock_content", held=held, release=release))
        for label, command in commands_by_label.items()
    ]
    _start(*workers)
    try:
        assert held.wait(_GUARD_TIMEOUT), "aucun processus n'a acquis le verrou"
        lock_identity = _identity(campaign_dir / _LOCK)
        loser = outcomes.get(timeout=_GUARD_TIMEOUT)
        lock_untouched = _identity(campaign_dir / _LOCK) == lock_identity  # le perdant n'a rien supprimé
        release.set()
        winner = outcomes.get(timeout=_GUARD_TIMEOUT)
    finally:
        release.set()
        _join(*workers)
    assert all(worker.exitcode == 0 for worker in workers)
    return loser, winner, lock_untouched


def test_two_real_processes_creating_the_initial_manifest_have_exactly_one_winner(worlds, tmp_path):
    plan = worlds.plan
    campaign_dir = _campaign(tmp_path, plan)
    start, outcomes = _SPAWN.Barrier(2), _SPAWN.Queue()
    creators = [_SPAWN.Process(target=_process_create, args=(str(campaign_dir), start, outcomes, label))
                for label in ("a", "b")]
    _start(*creators)
    try:
        results = sorted(outcomes.get(timeout=_GUARD_TIMEOUT)[1] for _ in creators)
    finally:
        _join(*creators)
    assert results == ["FileExistsError", "OK"]
    assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir) == _initial(plan)  # révision 0, jamais écrasé
    assert _persisted_record(campaign_dir) == _record(_initial(plan))


def test_s1_two_real_processes_racing_on_the_same_transition_commit_it_exactly_once(worlds, proofs, tmp_path):
    """ADR §21.13 n° 1 à 4 : un seul acquiert le verrou, l'autre reçoit `FileExistsError` sans toucher au verrou du
    gagnant ; la transition est appliquée UNE fois, révision + 1 ; le rejeu périmé est refusé, le rejeu à jour est un
    no-op idempotent."""
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _started_campaign(tmp_path, plan)
    _persist(campaign_dir, proofs[ids["wf"]])
    command = m2.AttachWalkForward(ids["wf"])
    loser, winner, lock_untouched = _race_on_the_lock(campaign_dir, {"a": command, "b": command}, 1)
    assert loser[1] == "FileExistsError" and lock_untouched
    assert winner[1:] == ("OK", 2) and {loser[0], winner[0]} == {"a", "b"}
    persisted = m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)
    assert persisted.walk_forward_validation_run_id == ids["wf"] and persisted.manifest_revision == 2
    assert not (campaign_dir / _LOCK).exists()
    with pytest.raises(m2.ManifestTransitionError):  # le perdant rejoue avec sa révision : refus, jamais de rebase
        m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, command, expected_revision=1)
    assert m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, command, expected_revision=2) == persisted


def test_s2_two_real_processes_with_different_transitions_both_land_after_an_explicit_replay(worlds, proofs, tmp_path):
    """ADR §21.13 n° 12 : aucune perte de mise à jour ni last-write-wins ; le perdant n'est jamais rejoué en interne,
    l'appelant recharge et rejoue sa commande avec la nouvelle révision."""
    plan = worlds.plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [m2.AttachWalkForward(ids["wf"])])  # révision 2
    commands = {"mc": m2.AttachMonteCarlo(ids["mc"]), "ps": m2.AttachParameterStability(first, ids["ps"][first])}
    loser, winner, lock_untouched = _race_on_the_lock(campaign_dir, commands, 2)
    assert loser[1] == "FileExistsError" and lock_untouched and winner[1:] == ("OK", 3)
    with pytest.raises(m2.ManifestTransitionError):  # rejeu avec la révision d'avant la course : refus fermé
        m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, commands[loser[0]], expected_revision=2)
    final = _update(plan, campaign_dir, commands[loser[0]])  # rejeu EXPLICITE après rechargement
    assert final.manifest_revision == 4
    assert final.monte_carlo_validation_run_id == ids["mc"]
    assert dict(final.parameter_stability_validation_run_ids_by_fold) == {first: ids["ps"][first]}
    assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir) == final


def test_s6_a_sentinel_created_while_a_real_process_holds_the_lock_after_step_5_never_aborts_its_attach(
    worlds, proofs, tmp_path,
):
    """ADR §21.13 n° 13 et 19 : l'écrivain A (processus réel) a franchi l'étape 5 sans sentinelle et tient le verrou ;
    l'écrivain B enregistre l'échec (sentinelle) puis échoue sur le verrou. A aboutit, le fait n'est jamais perdu
    (`effective_status`), puis `MarkTechnicalFailure` réconcilie le Manifest."""
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [m2.AttachWalkForward(ids["wf"])])  # révision 2
    held, release, outcomes = _SPAWN.Event(), _SPAWN.Event(), _SPAWN.Queue()
    writer_a = _SPAWN.Process(
        target=_process_update, args=(str(campaign_dir), m2.AttachMonteCarlo(ids["mc"]), 2, outcomes, "a"),
        kwargs=dict(hold_at="_proofs_for_update", held=held, release=release))  # étape 6 : après l'étape 5
    _start(writer_a)
    try:
        assert held.wait(_GUARD_TIMEOUT), "l'écrivain A n'a pas atteint l'étape 6"
        with pytest.raises(FileExistsError):  # écrivain B : ce processus
            m2.update_gate_v_campaign_manifest_v2(
                plan, campaign_dir, m2.MarkTechnicalFailure("worker crashed"), expected_revision=2)
        sentinel_bytes = (campaign_dir / _SENTINEL).read_bytes()
        assert json.loads(sentinel_bytes) == _sentinel_record(plan, "worker crashed")
        assert (campaign_dir / _LOCK).exists()
        release.set()
        outcome_a = outcomes.get(timeout=_GUARD_TIMEOUT)
    finally:
        release.set()
        _join(writer_a)
    assert outcome_a == ("a", "OK", 3) and writer_a.exitcode == 0  # A n'est jamais interrompu après l'étape 5
    behind = m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)
    assert behind.monte_carlo_validation_run_id == ids["mc"] and behind.technical_failure_reason is None
    assert behind.status == "EVIDENCE_INCOMPLETE"
    assert _effective(plan, campaign_dir) == "TECHNICAL_FAILURE"
    reconciled = _update(plan, campaign_dir, m2.MarkTechnicalFailure("worker crashed"))
    assert reconciled.status == "TECHNICAL_FAILURE" and reconciled.manifest_revision == 4
    assert (campaign_dir / _SENTINEL).read_bytes() == sentinel_bytes


@pytest.mark.parametrize("crash_at, lock_left, committed", [
    ("_acquire_update_lock", False, False),  # crash avant l'acquisition : aucun effet
    ("_write_lock_content", True, False),  # crash après l'acquisition, avant toute modification
    ("inside_save_atomic_overwrite", True, False),  # crash pendant l'écriture : ancien Manifest complet
    ("_release_update_lock", True, True),  # crash après l'écriture vérifiée, avant la suppression du verrou
])
def test_a_hard_crash_at_each_point_of_the_transaction_never_cleans_up_or_corrupts(
    worlds, tmp_path, crash_at, lock_left, committed,
):
    """Matrice de crash ADR §21.8 / §21.13 n° 6-7 : un crash dur ne libère rien ; le Manifest est ancien OU nouveau
    complet, jamais partiel ; un verrou résiduel bloque toute mutation suivante sans aucun nettoyage automatique
    (le PID du processus mort, l'âge et le contenu du verrou ne sont jamais consultés) ; les lecteurs lisent."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    before = m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)
    crashed = _SPAWN.Process(target=_process_crash, args=(str(campaign_dir), m2.SetRunning(True), 1, crash_at))
    _start(crashed)
    _join(crashed)
    assert crashed.exitcode == _CRASH_EXIT_CODE
    persisted = m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)  # lecteur : jamais bloqué par le verrou
    if committed:
        assert persisted.manifest_revision == 2 and persisted.running is True
    else:
        assert persisted == before
    assert (campaign_dir / _LOCK).exists() is lock_left
    if lock_left:
        lock_bytes = (campaign_dir / _LOCK).read_bytes()
        for _ in range(3):
            with pytest.raises(FileExistsError):
                _update(plan, campaign_dir, m2.SetRunning(False))
        assert (campaign_dir / _LOCK).read_bytes() == lock_bytes  # jamais nettoyé ni réécrit
    else:
        assert _update(plan, campaign_dir, m2.SetRunning(True)).manifest_revision == 2  # nouvelle tentative possible


# ============================================================================================
# Tranche 16 — D4 : architecture (écritures confinées, couche pure intacte, aucun Claim) et chemins longs Windows
# ============================================================================================


def _enclosing_functions_of_calls(tree, name):
    """Nom de la fonction englobante de chaque appel `name(...)` ou `<objet>.name(...)` du module."""
    found = []
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                callee = node.func
                called = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", None)
                if called == name:
                    found.append(function.name)
    return found


def test_manifest_writes_are_confined_to_exclusive_creation_and_the_locked_update():
    """Création initiale et sentinelle : `save_exclusive` seulement ; écrasement atomique : uniquement dans la
    transaction verrouillée ; une seule ouverture système (l'acquisition exclusive) et une seule suppression, celle
    du verrou POSSÉDÉ (jamais la sentinelle, jamais un autre fichier)."""
    tree = _module_tree()
    assert _enclosing_functions_of_calls(tree, "save_atomic_overwrite") == ["update_gate_v_campaign_manifest_v2"]
    assert sorted(_enclosing_functions_of_calls(tree, "save_exclusive")) == [
        "_record_technical_failure_sentinel", "create_gate_v_campaign_manifest_v2"]
    assert _enclosing_functions_of_calls(tree, "open") == ["_acquire_update_lock"]
    unlinks = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute) and node.func.attr == "unlink"]
    assert len(unlinks) == 1 and ast.unparse(unlinks[0]) == "os.unlink(lock.path)"
    assert _enclosing_functions_of_calls(tree, "update_gate_v_campaign_manifest_v2") == []  # aucun retry interne


def test_the_d2_and_d3_pure_layer_still_never_touches_the_filesystem(worlds, proofs, monkeypatch):
    plan = worlds.plan

    def forbidden(*args, **kwargs):
        raise AssertionError("la couche pure D2/D3 ne fait aucune E/S")
    for name in ("open", "stat", "lstat", "fstat", "replace", "unlink", "write", "close"):
        monkeypatch.setattr(os, name, forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(io, "open", forbidden)  # chemin des lectures/écritures `pathlib`
    path = _api_path(plan, proofs)
    assert path[-1].status == _COMPLETE
    assert _derive(plan, path[-1], dict(proofs)) == _COMPLETE
    assert m2.validate_gate_v_campaign_manifest_v2_marker_status(path[-1], plan, dict(proofs)) is None
    failed = _step(plan, path[-1], m2.MarkTechnicalFailure("boom"), {})
    assert _from_record(_record(failed)) == failed


def test_no_d4_operation_ever_creates_a_claim_or_any_file_beyond_the_campaign_artifacts(worlds, proofs, tmp_path):
    """ADR §21.13 n° 9-10 : ni le verrou ni la sentinelle ne sont un Claim ; après création, cycle complet,
    idempotence, refus et échec technique, seuls existent plan, Manifest, preuves et sentinelle — aucun Claim,
    aucun événement d'accès, aucune preuve OOS, aucun verrou restant."""
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _campaign(tmp_path, plan)
    m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)
    _persist(campaign_dir, *proofs.values())
    commands = [m2.Start(), m2.SetRunning(True), m2.AttachWalkForward(ids["wf"]), m2.AttachMonteCarlo(ids["mc"])]
    commands += [m2.AttachParameterStability(fold, ids["ps"][fold]) for fold in plan.expected_fold_ids]
    for command in commands + [m2.Start()]:
        _update(plan, campaign_dir, command)
    with pytest.raises(m2.ManifestTransitionError):
        _update(plan, campaign_dir, m2.SetRunning(True), expected_revision=0)
    assert _update(plan, campaign_dir, m2.MarkTechnicalFailure("worker crashed")).status == "TECHNICAL_FAILURE"
    prefix = f"campaigns/{plan.campaign_id}/"
    expected = {prefix + "plan.json", prefix + "manifest.json", prefix + _SENTINEL}
    expected |= {f"{prefix}validations/{run_id}/validation_run.json" for run_id in proofs}
    assert set(_files(tmp_path)) == expected
    for name in _files(tmp_path):
        assert not any(word in name.lower() for word in ("claim", "holdout", "event", "oos", ".lock")), name


def test_windows_long_path_regression_the_longest_canonical_proof_path_is_documented_never_shortened(worlds):
    """ADR 0025 §21.12 n° 30 : avec la racine usuelle `results/job_xxx/gate_v/campaigns/`, le chemin canonique le
    plus long approche `MAX_PATH` (260) — dépendance de déploiement EXPLICITE au support des chemins longs Windows.
    Aucune règle locale de longueur de fold_id, aucun raccourcissement ni hachage d'identifiant. Construction
    déterministe : le résultat ne dépend jamais du réglage MAX_PATH de l'hôte."""
    plan = worlds.plan
    root = "results/job_xxx/gate_v/campaigns/"
    longest_fold = max(plan.expected_fold_ids, key=len)
    proof_id = gate_v_v2_validation_run_id(plan, _PS, fold_id=longest_fold)
    relative = f"{plan.campaign_id}/validations/{proof_id}/validation_run.json"
    assert proof_id == f"{plan.campaign_id}_parameter_stability_{longest_fold}"  # jamais raccourci ni haché
    assert len(root) == 33 and len(relative) == 74 + 1 + 11 + 1 + (74 + 21 + len(longest_fold)) + 1 + 19 == 210
    assert 260 - len(root + relative) == 17  # 17 caractères pour TOUT le préfixe absolu de l'application
    assert len("C:\\Users\\someone\\Desktop\\app\\" + root + relative) > 260
    long_fold = "fold_" + "x" * 150  # identifiant portable plus long : accepté, aucune limite locale inventée
    long_manifest = _started(plan, walk_forward_validation_run_id=_ids(plan)["wf"],
                             parameter_stability_validation_run_ids_by_fold={
                                 long_fold: f"{plan.campaign_id}_parameter_stability_{long_fold}"})
    assert m2.validate_gate_v_campaign_manifest_v2_structure(long_manifest) is None
    constants = {node.value for node in ast.walk(_module_tree()) if isinstance(node, ast.Constant)}
    assert not constants & {260, 248, 255, "MAX_PATH"}  # aucun contournement local de longueur


# ============================================================================================
# Tranche 17 — D4 : ordre exact des contrôles de la transaction et cas limites de la sentinelle
# ============================================================================================


def test_a_stale_revision_is_refused_before_any_proof_is_reloaded(worlds, proofs, tmp_path):
    """Étape 4 avant l'étape 6 : une révision périmée est refusée comme telle, même si une preuve référencée est
    incohérente (son rechargement lèverait une autre erreur)."""
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [m2.AttachWalkForward(ids["wf"])])
    _proof_path(campaign_dir, ids["wf"]).write_text(
        json.dumps({**_record_of_run(proofs[ids["wf"]]), "validation_type": "stress"}), encoding="utf-8")
    with pytest.raises(m2.ManifestTransitionError):
        m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, m2.SetRunning(True), expected_revision=1)
    with pytest.raises(ValueError):  # à la bonne révision, la preuve incohérente est bien refusée fermée
        m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, m2.SetRunning(True), expected_revision=2)


def test_the_persisted_plan_is_reloaded_under_the_lock(worlds, tmp_path, monkeypatch):
    """Étape 3 : `plan.json` relu SOUS le verrou (pas seulement avant) ; un plan persisté différent à cet instant est
    un refus fermé avant toute écriture, verrou libéré."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    before = _files(campaign_dir)
    real_load = m2.load_gate_v_campaign_plan_v2
    reads = []

    def plan_changed_under_the_lock(path):
        reads.append(path)
        return real_load(path) if len(reads) == 1 else worlds.other_plan
    monkeypatch.setattr(m2, "load_gate_v_campaign_plan_v2", plan_changed_under_the_lock)
    with pytest.raises(ValueError):
        _update(plan, campaign_dir, m2.SetRunning(True), expected_revision=1)
    assert len(reads) == 2 and _files(campaign_dir) == before


def test_proofs_are_reloaded_only_from_the_references_and_the_portable_candidate_never_by_scanning(
    worlds, proofs, tmp_path, monkeypatch,
):
    plan = worlds.plan
    ids = _ids(plan)
    first = plan.expected_fold_ids[0]
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [m2.AttachWalkForward(ids["wf"])])  # + orphelines
    real_load = m2.load_validation_run
    read = []

    def spy(path):
        read.append(os.path.relpath(path, campaign_dir).replace(os.sep, "/"))
        return real_load(path)
    monkeypatch.setattr(m2, "load_validation_run", spy)
    _update(plan, campaign_dir, m2.SetRunning(True))
    assert read == [f"validations/{ids['wf']}/validation_run.json"]  # référence seule : aucune orpheline lue
    read.clear()
    _update(plan, campaign_dir, m2.AttachParameterStability(first, ids["ps"][first]))
    assert read == [f"validations/{ids['wf']}/validation_run.json",
                    f"validations/{ids['ps'][first]}/validation_run.json"]
    read.clear()
    for bad_run_id in ("../../plan", "..\\x", "a/b", "", None):  # jamais un chemin hors de `validations/`
        with pytest.raises(ValueError):
            _update(plan, campaign_dir, m2.AttachMonteCarlo(bad_run_id))
    assert set(read) == {f"validations/{ids['wf']}/validation_run.json",
                         f"validations/{ids['ps'][first]}/validation_run.json"}
    read.clear()
    _update(plan, campaign_dir, m2.MarkTechnicalFailure("worker crashed"))
    assert read == []  # un échec technique ne recharge aucune preuve


def test_a_sentinel_that_cannot_be_examined_is_never_read_as_no_failure(worlds, tmp_path, monkeypatch):
    """Toute erreur autre que l'absence en examinant la sentinelle est propagée (fail-closed) : jamais « aucun échec »,
    ni pour le statut effectif ni à l'étape 5."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    before = _files(campaign_dir)
    real_lstat = os.lstat

    def blocked(path, *args, **kwargs):
        if os.path.basename(os.fspath(path)) == _SENTINEL:
            raise PermissionError(13, "accès refusé à la sentinelle")
        return real_lstat(path, *args, **kwargs)
    monkeypatch.setattr(os, "lstat", blocked)
    manifest = m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir)
    with pytest.raises(PermissionError):
        m2.derive_gate_v_campaign_v2_effective_status(plan, campaign_dir, manifest, {})
    with pytest.raises(PermissionError):
        _update(plan, campaign_dir, m2.SetRunning(True))
    assert _files(campaign_dir) == before  # rien d'écrit, verrou libéré (sortie avant l'étape 9)


def test_a_different_reason_is_refused_deterministically_even_while_the_lock_is_busy(worlds, tmp_path):
    """La sentinelle existante gagne AVANT toute tentative de verrou : une reason différente est une transition
    refusée, jamais un simple « verrou occupé »."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    _update(plan, campaign_dir, m2.MarkTechnicalFailure("first failure"))
    (campaign_dir / _LOCK).write_bytes(b"busy")
    before = _files(campaign_dir)
    with pytest.raises(m2.ManifestTransitionError):
        _update(plan, campaign_dir, m2.MarkTechnicalFailure("second failure"))
    with pytest.raises(FileExistsError):  # la même reason, elle, passe le constat puis rencontre le verrou
        _update(plan, campaign_dir, m2.MarkTechnicalFailure("first failure"))
    assert _files(campaign_dir) == before


def test_a_manifest_reason_diverging_from_a_readable_sentinel_is_refused_except_the_tolerated_fixed_reason(
    worlds, tmp_path,
):
    plan = worlds.plan
    for recorded, accepted in (("reason x", False), (_UNREADABLE, True)):
        campaign_dir = _started_campaign(tmp_path / str(accepted), plan)
        failed = _step(plan, _api_started(plan), m2.MarkTechnicalFailure(recorded), {})
        _write_manifest(campaign_dir, failed)  # écrit hors API : Manifest marqué « reason x » ou motif fixe
        (campaign_dir / _SENTINEL).write_text(json.dumps(_sentinel_record(plan, "reason y")), encoding="utf-8")
        before = _files(campaign_dir)
        if accepted:
            assert _update(plan, campaign_dir, m2.MarkTechnicalFailure(recorded)) == failed  # tolérée, jamais réécrite
        else:
            with pytest.raises(m2.ManifestTransitionError):  # divergence avec la sentinelle lisible : refus fermé
                _update(plan, campaign_dir, m2.MarkTechnicalFailure(recorded))
        with pytest.raises(m2.ManifestTransitionError):  # la reason de la sentinelle ne réécrit jamais le Manifest
            _update(plan, campaign_dir, m2.MarkTechnicalFailure("reason y"))
        assert _files(campaign_dir) == before


def test_a_sentinel_removed_between_its_creation_and_the_linearization_point_is_a_closed_refusal(
    worlds, tmp_path, monkeypatch,
):
    """Hors modèle (suppression manuelle) mais fermé : à l'étape 5, une sentinelle disparue n'est jamais recréée ni
    ignorée ; même le motif fixe déjà enregistré ne passe pas."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    sentinel = campaign_dir / _SENTINEL
    sentinel.write_bytes(b"")
    reconciled = _update(plan, campaign_dir, m2.MarkTechnicalFailure(_UNREADABLE))
    real_load = m2.load_gate_v_campaign_plan_v2
    reads = []

    def remove_sentinel_under_the_lock(path):
        reads.append(path)
        if len(reads) == 2:  # 1 : liaison avant le verrou ; 2 : étape 3 sous le verrou, après constat, avant étape 5
            sentinel.unlink()
        return real_load(path)
    monkeypatch.setattr(m2, "load_gate_v_campaign_plan_v2", remove_sentinel_under_the_lock)
    with pytest.raises(m2.ManifestTransitionError):
        m2.update_gate_v_campaign_manifest_v2(
            plan, campaign_dir, m2.MarkTechnicalFailure(_UNREADABLE), expected_revision=reconciled.manifest_revision)
    assert len(reads) == 2
    assert not sentinel.exists() and not (campaign_dir / _LOCK).exists()
    assert m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir) == reconciled


# ============================================================================================
# Tranche 18 — D4 : durcissements issus des revues ciblées (scientifique, architecture/reproductibilité)
# ============================================================================================


def test_a_reason_that_cannot_be_persisted_is_refused_before_any_sentinel_or_lock(worlds, tmp_path):
    """Un motif non encodable en UTF-8 (surrogate isolé, ex. `str(OSError)` d'un chemin POSIX non décodable) est un
    argument invalide : `ValueError` SANS effet — jamais une sentinelle vide irréversible qui perdrait le vrai motif."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    before = _files(campaign_dir)
    for unencodable in ("\ud800", "disk \udcff full"):
        with pytest.raises(ValueError) as raised:
            _update(plan, campaign_dir, m2.MarkTechnicalFailure(unencodable))
        assert not isinstance(raised.value, UnicodeError)  # refus d'argument, pas un échec d'écriture
    assert _files(campaign_dir) == before


def test_a_manifest_already_marked_never_gets_a_new_sentinel_even_if_its_sentinel_was_removed(worlds, tmp_path):
    """Hors modèle (sentinelle supprimée à la main) mais fermé : une sentinelle n'est créée que pour une campagne dont
    le Manifest ne porte encore aucun motif ; une commande refusée ne laisse jamais de sentinelle divergente."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    _update(plan, campaign_dir, m2.MarkTechnicalFailure("first failure"))
    (campaign_dir / _SENTINEL).unlink()
    before = _files(campaign_dir)
    for reason in ("other failure", "first failure"):
        with pytest.raises(m2.ManifestTransitionError):
            _update(plan, campaign_dir, m2.MarkTechnicalFailure(reason))
        assert _files(campaign_dir) == before  # aucune sentinelle recréée, divergente ou non


def test_a_terminal_manifest_refuses_every_other_command_without_reloading_any_proof(worlds, proofs, tmp_path):
    """Propriété figée de D3 conservée par D4 : le refus d'un Manifest terminal ne dépend d'aucune preuve, même sans
    sentinelle (hors modèle) et même si une preuve référencée est incohérente sur disque."""
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [
        m2.AttachWalkForward(ids["wf"]), m2.MarkTechnicalFailure("boom")])
    (campaign_dir / _SENTINEL).unlink()  # hors modèle : seul le marqueur du Manifest reste
    _proof_path(campaign_dir, ids["wf"]).write_text(
        json.dumps({**_record_of_run(proofs[ids["wf"]]), "validation_type": []}), encoding="utf-8")
    before = _files(campaign_dir)
    for command in (m2.Start(), m2.SetRunning(True), m2.AttachMonteCarlo(ids["mc"])):
        with pytest.raises(m2.ManifestTransitionError):
            _update(plan, campaign_dir, command)
        assert _files(campaign_dir) == before


def test_the_reserved_unreadable_reason_never_creates_a_sentinel(worlds, tmp_path):
    """Le motif fixe sert UNIQUEMENT à réconcilier une sentinelle existante illisible : il ne crée jamais une
    sentinelle « lisible » qui prétendrait faussement avoir été illisible."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    before = _files(campaign_dir)
    with pytest.raises(m2.ManifestTransitionError):
        _update(plan, campaign_dir, m2.MarkTechnicalFailure(_UNREADABLE))
    assert _files(campaign_dir) == before
    (campaign_dir / _SENTINEL).write_text(json.dumps(_sentinel_record(plan, "worker crashed")), encoding="utf-8")
    with pytest.raises(m2.ManifestTransitionError):  # une sentinelle LISIBLE ne se réconcilie jamais avec lui
        _update(plan, campaign_dir, m2.MarkTechnicalFailure(_UNREADABLE))


def test_a_referenced_proof_of_unexpected_json_shape_is_a_typed_closed_refusal(worlds, proofs, tmp_path):
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [m2.AttachWalkForward(ids["wf"])])
    _proof_path(campaign_dir, ids["wf"]).write_text(
        json.dumps({**_record_of_run(proofs[ids["wf"]]), "validation_type": []}), encoding="utf-8")
    before = _files(campaign_dir)
    with pytest.raises(ValueError) as raised:  # catégorie documentée « preuve incohérente », cause conservée
        _update(plan, campaign_dir, m2.SetRunning(True))
    assert isinstance(raised.value.__cause__, TypeError)
    assert _files(campaign_dir) == before


def test_the_release_error_that_carries_committed_survives_pickle_and_copy():
    """L'exception « validé, verrou résiduel » traverse une frontière de processus sans perdre `committed`."""
    import copy
    import pickle

    for committed in (True, False):
        error = m2.ManifestLockReleaseError("verrou résiduel", committed=committed)
        for clone in (pickle.loads(pickle.dumps(error)), copy.copy(error), copy.deepcopy(error)):
            assert type(clone) is m2.ManifestLockReleaseError and clone.committed is committed
            assert str(clone) == "verrou résiduel"


def test_a_file_system_without_file_identity_never_lets_the_owner_delete_by_path(worlds, tmp_path, monkeypatch):
    """`st_ino == 0` : le système de fichiers ne fournit pas d'identité, la propriété est invérifiable -> verrou laissé,
    rien d'écrit, `ManifestLockReleaseError(committed=False)`, jamais une suppression « à l'aveugle »."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    manifest_before = (campaign_dir / "manifest.json").read_bytes()
    syscalls = _LockSyscalls(monkeypatch, campaign_dir)
    syscalls.zero_identity = True
    with pytest.raises(m2.ManifestLockReleaseError) as raised:
        _update(plan, campaign_dir, m2.SetRunning(True))
    assert raised.value.committed is False
    assert syscalls.operations() == ["open", "fstat", "close"] and (campaign_dir / _LOCK).exists()
    assert (campaign_dir / "manifest.json").read_bytes() == manifest_before


def test_arbitration_c_holds_through_persistence_an_attach_replay_while_running_writes_nothing(
    worlds, proofs, tmp_path,
):
    plan = worlds.plan
    ids = _ids(plan)
    campaign_dir = _campaign_with(tmp_path, plan, proofs, [m2.AttachWalkForward(ids["wf"]), m2.SetRunning(True)])
    before = _files(campaign_dir)
    replay = _update(plan, campaign_dir, m2.AttachWalkForward(ids["wf"]))
    assert (replay.running, replay.status, replay.manifest_revision) == (True, "RUNNING", 3)
    assert _files(campaign_dir) == before


def test_an_unverifiable_ownership_right_before_the_write_never_writes_outside_the_lock(worlds, tmp_path, monkeypatch):
    """Étape 9 : propriété non vérifiable à l'instant d'écrire (lecture d'identité transitoirement bloquée) -> AUCUNE
    écriture, jamais après la libération du verrou ; le verrou, revérifié possédé, est libéré ; `ManifestWriteError`."""
    plan = worlds.plan
    campaign_dir = _started_campaign(tmp_path, plan)
    before = _files(campaign_dir)
    writes = _persistence_spy(monkeypatch, lambda path, data, kind, real: real(path, data, kind))
    syscalls = _LockSyscalls(monkeypatch, campaign_dir)
    syscalls.stat_errors = [PermissionError(13, "antivirus")]  # seule la vérification de l'étape 9 est bloquée
    with pytest.raises(m2.ManifestWriteError):
        _update(plan, campaign_dir, m2.SetRunning(True))
    assert writes == [] and _files(campaign_dir) == before  # rien d'écrit, verrou libéré
    assert syscalls.operations()[-1] == "unlink"
