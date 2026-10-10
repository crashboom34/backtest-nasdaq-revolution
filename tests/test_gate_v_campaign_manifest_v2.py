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
)
from walk_forward import build_walk_forward_specification

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
    return SimpleNamespace(plan=plan, other_plan=other_plan, v1_plan=v1_plan)


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
    "GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION", "GATE_V_CAMPAIGN_V2_STATUSES", "GateVCampaignManifestV2",
    "build_gate_v_campaign_manifest_v2", "validate_gate_v_campaign_manifest_v2_structure",
    "validate_gate_v_campaign_manifest_v2_against_plan", "gate_v_campaign_manifest_v2_to_record",
    "gate_v_campaign_manifest_v2_from_record",
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
        # D3 : dérivation de statut et commandes
        "derive_gate_v_campaign_v2_status", "marker_status", "effective_status", "ManifestTransitionError",
        # D4 : persistance, verrou, sentinelle
        "ManifestWriteError", "ManifestWriteUncertainError", "ManifestLockReleaseError",
        # D5 : vérification des preuves persistées
        "assert_gate_v_pre_holdout_evidence_complete", "evaluate_pre_holdout_evidence_v2",
        "walk_forward_evidence_complete_v2", "monte_carlo_evidence_complete_v2",
        "parameter_stability_evidence_complete_v2", "load_validation_run",
        # D6 : discrimination
        "classify_gate_v_campaign_dir", "GateVCampaignDiscriminationError",
    }
    assert not _code_identifiers(_module_tree()) & forbidden
    for name in (
        "start_gate_v_campaign_v2", "set_running", "attach_walk_forward", "attach_monte_carlo",
        "attach_parameter_stability", "mark_technical_failure", "derive_gate_v_campaign_v2_status",
        "save_gate_v_campaign_manifest_v2", "load_gate_v_campaign_manifest_v2", "classify_gate_v_campaign_dir",
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
    identifiers = _code_identifiers(_module_tree())
    assert not {name for name in identifiers if "MAX" in name.upper() and "LEN" in name.upper()}
    assert "len" not in identifiers


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
