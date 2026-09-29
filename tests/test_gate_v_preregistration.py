"""
tests/test_gate_v_preregistration.py — AF-V-07 Slice B : GateVPreRegistration.

Liaison immuable ResearchRun + protocole complet + policy Gate V, AVANT toute exécution
scientifique et AVANT tout FINAL_HOLDOUT — ADR 0025 Décision 6/7/8 (corrigée en 0f0df82 :
`preregistration_id`/`preregistration_content_hash` incluent directement `research_run_content_hash`
et `policy_git_sha`). Provenance Git de la policy fail-closed, jamais depuis le working tree.

Aucun accès FINAL_HOLDOUT, aucune campagne réelle, aucune donnée marché — synthétique uniquement.
Les tests Git utilisent un dépôt temporaire local hermétique (aucun réseau, aucun GitHub).
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_split import build_dataset_split_plan, build_split_boundary
from gate_v_validation_policy import (
    OosPolicyCriterion,
    WalkForwardPolicyCriterion,
    build_gate_v_validation_policy,
    policy_content_hash as compute_policy_content_hash,
    save_gate_v_validation_policy,
)
from research_run import build_research_run
from walk_forward import build_walk_forward_specification

from gate_v_preregistration import (
    GATE_V_PREREGISTRATION_SEMANTICS_VERSION,
    GateVPreRegistration,
    GitProvenanceError,
    build_gate_v_preregistration,
    compute_campaign_protocol_fingerprint,
    compute_preregistration_content_hash,
    compute_preregistration_id,
    compute_scope_key,
    load_gate_v_preregistration,
    research_run_content_hash,
    save_gate_v_preregistration,
    verify_policy_git_provenance,
)

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


def _policy(policy_id="pol_test"):
    return build_gate_v_validation_policy(
        policy_id,
        {
            "oos": (OosPolicyCriterion(metric="net_ret_pct", operator=">", threshold=0.0),),
            "walk_forward": (
                WalkForwardPolicyCriterion(metric="oos_net_return_pct", operator=">", threshold=0.0),
            ),
        },
    )


def _commit_policy(tmp_path, policy_id="pol_test"):
    """Real git repo, policy committed. Returns (repo_dir, policy_path, sha, policy)."""
    repo_dir = _init_git_repo(tmp_path)
    policies_dir = repo_dir / "validation_policies"
    policies_dir.mkdir()
    policy_path = policies_dir / f"{policy_id}.json"
    policy = _policy(policy_id)
    save_gate_v_validation_policy(policy_path, policy)
    _run_git(["add", "validation_policies"], repo_dir)
    # Unique message: two repos with byte-identical content/parent/author/second-precision
    # timestamp would otherwise produce the SAME commit object (and thus the same SHA).
    _run_git(["commit", "-m", f"add policy {uuid.uuid4().hex}"], repo_dir)
    sha = _run_git(["rev-parse", "HEAD"], repo_dir).strip()
    return repo_dir, policy_path, sha, policy


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


def _preregistration(tmp_path, policy_id="pol_test", **overrides):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path, policy_id)
    kwargs = dict(
        research_run=_research_run(),
        split_plan=_split_plan(),
        strategy_name="perfect_revolution_v1",
        base_params={"n_neighbors": 5},
        search_mode="single_var",
        search_space_hash="a" * 12,
        budget_per_fold=10,
        walk_forward_specification=_wf_spec(),
        readiness_spec=None,
        policy=policy,
        policy_path=policy_path,
        assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION,
        repo_dir=repo_dir,
    )
    kwargs.update(overrides)
    return build_gate_v_preregistration(**kwargs)


# -- Construction valide -----------------------------------------------------


def test_semantics_version_constant():
    assert GATE_V_PREREGISTRATION_SEMANTICS_VERSION == "gate_v_preregistration_v1"


def test_valid_construction(tmp_path):
    pre = _preregistration(tmp_path)
    assert isinstance(pre, GateVPreRegistration)
    assert pre.research_run_id == "run_x"
    assert pre.preregistration_semantics_version == GATE_V_PREREGISTRATION_SEMANTICS_VERSION


def _build_twice_from_same_commit(tmp_path, **overrides):
    """Two independent builds from the SAME committed policy/sha -- true determinism check
    (unlike `_preregistration()`, which commits a fresh repo, and thus a fresh `policy_git_sha`,
    on every call -- appropriate for other tests, wrong for a same-input-same-output check)."""
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    kwargs = dict(
        research_run=_research_run(), split_plan=_split_plan(), strategy_name="perfect_revolution_v1",
        base_params={"n_neighbors": 5}, search_mode="single_var", search_space_hash="a" * 12,
        budget_per_fold=10, walk_forward_specification=_wf_spec(), readiness_spec=None,
        policy=policy, policy_path=policy_path, assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION,
        repo_dir=repo_dir, policy_git_sha=sha,
    )
    kwargs.update(overrides)
    return build_gate_v_preregistration(**kwargs), build_gate_v_preregistration(**kwargs)


def test_preregistration_id_deterministic(tmp_path):
    a, b = _build_twice_from_same_commit(tmp_path)
    assert a.preregistration_id == b.preregistration_id


def test_preregistration_content_hash_deterministic(tmp_path):
    a, b = _build_twice_from_same_commit(tmp_path)
    assert a.preregistration_content_hash == b.preregistration_content_hash


def test_campaign_protocol_fingerprint_deterministic():
    kwargs = dict(
        research_run_id="run_x", research_run_content_hash="h" * 64,
        dataset_snapshot_id=_SNAPSHOT_ID, split_plan_id="plan_x",
        split_plan_fingerprint="f" * 64, strategy_name="perfect_revolution_v1",
        base_params={"n_neighbors": 5}, search_mode="single_var",
        search_space_hash="a" * 12, budget_per_fold=10,
        walk_forward_specification=_wf_spec(), readiness_spec=None,
        expected_fold_ids=("fold_0",), expected_fold_definitions_hash="e" * 64,
        validation_zone_hash="z" * 64,
        walk_forward_spec_semantics_version="wf_v1", monte_carlo_semantics_version="mc_v1",
        parameter_stability_semantics_version="ps_v1",
        gate_v_validation_policy_id="pol_test", policy_content_hash="p" * 64,
        assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION,
    )
    assert compute_campaign_protocol_fingerprint(**kwargs) == compute_campaign_protocol_fingerprint(**kwargs)


# -- Hashing -------------------------------------------------------------


def test_research_run_content_hash_changes_on_content_change():
    run_a = _research_run()
    run_b = _research_run(seed=42)
    assert research_run_content_hash(run_a) != research_run_content_hash(run_b)


def test_preregistration_id_changes_with_research_run_content_hash(tmp_path):
    base = _preregistration(tmp_path / "base")
    changed = _preregistration(tmp_path / "changed", research_run=_research_run(seed=42))
    assert base.research_run_content_hash != changed.research_run_content_hash
    assert base.preregistration_id != changed.preregistration_id
    assert base.preregistration_content_hash != changed.preregistration_content_hash


def test_preregistration_id_changes_with_policy_git_sha(tmp_path):
    """`policy_git_sha` participates in the hash -- demonstrated with two INDEPENDENT repos,
    each accepted at its own current HEAD (a non-HEAD sha is rejected outright, see
    test_git_provenance_rejects_non_head_sha -- so this can no longer be shown within one repo
    by pointing at an old commit)."""
    pre_a = _preregistration(tmp_path / "a")
    pre_b = _preregistration(tmp_path / "b")
    assert pre_a.policy_git_sha != pre_b.policy_git_sha
    assert pre_a.preregistration_id != pre_b.preregistration_id
    assert pre_a.preregistration_content_hash != pre_b.preregistration_content_hash


def test_created_at_excluded_from_id_and_hash(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    kwargs = dict(
        research_run=_research_run(), split_plan=_split_plan(), strategy_name="perfect_revolution_v1",
        base_params={"n_neighbors": 5}, search_mode="single_var", search_space_hash="a" * 12,
        budget_per_fold=10, walk_forward_specification=_wf_spec(), readiness_spec=None,
        policy=policy, policy_path=policy_path, assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION,
        repo_dir=repo_dir, policy_git_sha=sha,
    )
    a = build_gate_v_preregistration(**kwargs, created_at="2024-01-01T00:00:00+00:00")
    b = build_gate_v_preregistration(**kwargs, created_at="2025-06-15T00:00:00+00:00")
    assert a.created_at != b.created_at
    assert a.preregistration_id == b.preregistration_id
    assert a.preregistration_content_hash == b.preregistration_content_hash


def test_preregistration_content_hash_excludes_itself(tmp_path):
    pre = _preregistration(tmp_path)
    recomputed = compute_preregistration_content_hash(
        preregistration_id=pre.preregistration_id,
        scope_key=pre.scope_key,
        campaign_protocol_fingerprint=pre.campaign_protocol_fingerprint,
        research_run_id=pre.research_run_id,
        research_run_content_hash=pre.research_run_content_hash,
        dataset_snapshot_id=pre.dataset_snapshot_id,
        split_plan_id=pre.split_plan_id,
        strategy_name=pre.strategy_name,
        gate_v_validation_policy_id=pre.gate_v_validation_policy_id,
        policy_content_hash=pre.policy_content_hash,
        policy_git_sha=pre.policy_git_sha,
        assessment_semantics_version=pre.assessment_semantics_version,
        preregistration_semantics_version=pre.preregistration_semantics_version,
    )
    assert recomputed == pre.preregistration_content_hash


# -- Scope -----------------------------------------------------------------


def test_scope_key_unaffected_by_policy():
    key_a = compute_scope_key("run_x", _SNAPSHOT_ID, "plan_x", "perfect_revolution_v1")
    key_b = compute_scope_key("run_x", _SNAPSHOT_ID, "plan_x", "perfect_revolution_v1")
    assert key_a == key_b  # policy plays no role in scope_key's inputs at all


def test_scope_key_changes_with_research_run_id():
    a = compute_scope_key("run_x", _SNAPSHOT_ID, "plan_x", "perfect_revolution_v1")
    b = compute_scope_key("run_y", _SNAPSHOT_ID, "plan_x", "perfect_revolution_v1")
    assert a != b


def test_scope_key_changes_with_strategy_name():
    a = compute_scope_key("run_x", _SNAPSHOT_ID, "plan_x", "perfect_revolution_v1")
    b = compute_scope_key("run_x", _SNAPSHOT_ID, "plan_x", "other_strategy")
    assert a != b


# -- Unicite -----------------------------------------------------------------


def test_second_preregistration_same_scope_refused(tmp_path):
    pre = _preregistration(tmp_path)
    path = tmp_path / "preregistrations" / f"{pre.scope_key}.json"
    save_gate_v_preregistration(path, pre)
    other_policy_pre = _preregistration(tmp_path, policy_id="pol_other")
    assert other_policy_pre.scope_key == pre.scope_key  # same scientific scope
    with pytest.raises(FileExistsError):
        save_gate_v_preregistration(path, other_policy_pre)


# -- Git provenance ----------------------------------------------------------


def test_git_provenance_nominal(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    verify_policy_git_provenance(
        policy_path=policy_path,
        validation_policy_id=policy.validation_policy_id,
        expected_policy_content_hash=compute_policy_content_hash(policy),
        policy_git_sha=sha,
        repo_dir=repo_dir,
    )  # no exception


def test_git_provenance_untracked_file_refused(tmp_path):
    repo_dir = _init_git_repo(tmp_path)
    policies_dir = repo_dir / "validation_policies"
    policies_dir.mkdir()
    policy_path = policies_dir / "pol_untracked.json"
    policy = _policy("pol_untracked")
    save_gate_v_validation_policy(policy_path, policy)
    # A commit exists but never included this file.
    (repo_dir / "README.md").write_text("x", encoding="utf-8")
    _run_git(["add", "README.md"], repo_dir)
    _run_git(["commit", "-m", "init"], repo_dir)
    sha = _run_git(["rev-parse", "HEAD"], repo_dir).strip()
    with pytest.raises(GitProvenanceError):
        verify_policy_git_provenance(
            policy_path=policy_path, validation_policy_id=policy.validation_policy_id,
            expected_policy_content_hash=compute_policy_content_hash(policy),
            policy_git_sha=sha, repo_dir=repo_dir,
        )


def test_git_provenance_invalid_sha_refused(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    with pytest.raises(GitProvenanceError):
        verify_policy_git_provenance(
            policy_path=policy_path, validation_policy_id=policy.validation_policy_id,
            expected_policy_content_hash=compute_policy_content_hash(policy),
            policy_git_sha="0" * 40, repo_dir=repo_dir,
        )


def test_git_provenance_hash_mismatch_refused(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    with pytest.raises(GitProvenanceError):
        verify_policy_git_provenance(
            policy_path=policy_path, validation_policy_id=policy.validation_policy_id,
            expected_policy_content_hash="0" * 64,
            policy_git_sha=sha, repo_dir=repo_dir,
        )


def test_git_provenance_working_tree_modified_committed_bytes_win(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    expected_hash = compute_policy_content_hash(policy)
    # Corrupt the working tree copy -- must NOT affect verification (never read as source of truth).
    policy_path.write_text('{"validation_policy_id": "pol_test", "scientific_criteria": {}}', encoding="utf-8")
    verify_policy_git_provenance(
        policy_path=policy_path, validation_policy_id=policy.validation_policy_id,
        expected_policy_content_hash=expected_hash,
        policy_git_sha=sha, repo_dir=repo_dir,
    )  # no exception: committed blob still matches


def test_git_provenance_policy_id_mismatch_refused(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path, policy_id="pol_test")
    with pytest.raises(GitProvenanceError):
        verify_policy_git_provenance(
            policy_path=policy_path, validation_policy_id="pol_different",
            expected_policy_content_hash=compute_policy_content_hash(policy),
            policy_git_sha=sha, repo_dir=repo_dir,
        )


def test_build_preregistration_fails_closed_on_bad_provenance(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    with pytest.raises(GitProvenanceError):
        build_gate_v_preregistration(
            research_run=_research_run(), split_plan=_split_plan(), strategy_name="perfect_revolution_v1",
            base_params={"n_neighbors": 5}, search_mode="single_var", search_space_hash="a" * 12,
            budget_per_fold=10, walk_forward_specification=_wf_spec(), readiness_spec=None,
            policy=policy, policy_path=policy_path, assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION,
            repo_dir=repo_dir, policy_git_sha="0" * 40,
        )


# -- Persistence -------------------------------------------------------------


def test_save_load_round_trip(tmp_path):
    pre = _preregistration(tmp_path)
    path = tmp_path / "preregistrations" / f"{pre.scope_key}.json"
    save_gate_v_preregistration(path, pre)
    loaded = load_gate_v_preregistration(path)
    assert loaded == pre


def test_save_refuses_overwrite(tmp_path):
    pre = _preregistration(tmp_path)
    path = tmp_path / "preregistrations" / f"{pre.scope_key}.json"
    save_gate_v_preregistration(path, pre)
    with pytest.raises(FileExistsError):
        save_gate_v_preregistration(path, pre)


def test_load_rejects_missing_file(tmp_path):
    with pytest.raises(ValueError):
        load_gate_v_preregistration(tmp_path / "absent.json")


def test_load_rejects_tampered_preregistration_id(tmp_path):
    pre = _preregistration(tmp_path)
    path = tmp_path / "preregistrations" / f"{pre.scope_key}.json"
    save_gate_v_preregistration(path, pre)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["preregistration_id"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_gate_v_preregistration(path)


def test_load_rejects_tampered_semantics_version(tmp_path):
    pre = _preregistration(tmp_path)
    path = tmp_path / "preregistrations" / f"{pre.scope_key}.json"
    save_gate_v_preregistration(path, pre)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["preregistration_semantics_version"] = "gate_v_preregistration_v2_fake"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_gate_v_preregistration(path)


def test_load_rejects_unknown_field(tmp_path):
    pre = _preregistration(tmp_path)
    path = tmp_path / "preregistrations" / f"{pre.scope_key}.json"
    save_gate_v_preregistration(path, pre)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["smuggled_field"] = "x"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_gate_v_preregistration(path)


def test_load_rejects_missing_required_field(tmp_path):
    pre = _preregistration(tmp_path)
    path = tmp_path / "preregistrations" / f"{pre.scope_key}.json"
    save_gate_v_preregistration(path, pre)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["policy_git_sha"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_gate_v_preregistration(path)


# -- Protocol fingerprint -----------------------------------------------------


def test_protocol_fingerprint_changes_with_policy_content_hash():
    base_kwargs = dict(
        research_run_id="run_x", research_run_content_hash="h" * 64,
        dataset_snapshot_id=_SNAPSHOT_ID, split_plan_id="plan_x",
        split_plan_fingerprint="f" * 64, strategy_name="perfect_revolution_v1",
        base_params={"n_neighbors": 5}, search_mode="single_var",
        search_space_hash="a" * 12, budget_per_fold=10,
        walk_forward_specification=_wf_spec(), readiness_spec=None,
        expected_fold_ids=("fold_0",), expected_fold_definitions_hash="e" * 64,
        validation_zone_hash="z" * 64,
        walk_forward_spec_semantics_version="wf_v1", monte_carlo_semantics_version="mc_v1",
        parameter_stability_semantics_version="ps_v1",
        gate_v_validation_policy_id="pol_test",
        assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION,
    )
    fp_a = compute_campaign_protocol_fingerprint(**base_kwargs, policy_content_hash="p" * 64)
    fp_b = compute_campaign_protocol_fingerprint(**base_kwargs, policy_content_hash="q" * 64)
    assert fp_a != fp_b


def test_protocol_fingerprint_has_no_final_holdout_parameter():
    import inspect

    params = set(inspect.signature(compute_campaign_protocol_fingerprint).parameters)
    forbidden = {"oos_evidence_hash", "oos_evidence_validation_run_id", "final_holdout", "holdout_access_event_id"}
    assert forbidden.isdisjoint(params)


# -- policy_git_sha must equal current HEAD (not just any commit with matching content) -----


def test_git_provenance_rejects_non_head_sha(tmp_path):
    repo_dir, policy_path, sha_a, policy = _commit_policy(tmp_path)
    (repo_dir / "README.md").write_text("unrelated change", encoding="utf-8")
    _run_git(["add", "README.md"], repo_dir)
    _run_git(["commit", "-m", "unrelated, policy.json untouched"], repo_dir)
    sha_b = _run_git(["rev-parse", "HEAD"], repo_dir).strip()
    assert sha_a != sha_b
    # sha_a's blob content/hash still match -- but sha_a is no longer HEAD.
    with pytest.raises(GitProvenanceError):
        verify_policy_git_provenance(
            policy_path=policy_path, validation_policy_id=policy.validation_policy_id,
            expected_policy_content_hash=compute_policy_content_hash(policy),
            policy_git_sha=sha_a, repo_dir=repo_dir,
        )
    # sha_b == HEAD, policy content unchanged since commit A -- accepted.
    verify_policy_git_provenance(
        policy_path=policy_path, validation_policy_id=policy.validation_policy_id,
        expected_policy_content_hash=compute_policy_content_hash(policy),
        policy_git_sha=sha_b, repo_dir=repo_dir,
    )


def test_git_provenance_accepts_short_sha_resolved_to_head(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    short_sha = sha[:10]
    verify_policy_git_provenance(
        policy_path=policy_path, validation_policy_id=policy.validation_policy_id,
        expected_policy_content_hash=compute_policy_content_hash(policy),
        policy_git_sha=short_sha, repo_dir=repo_dir,
    )  # short SHA resolving to the same commit as HEAD must be accepted


def test_git_provenance_rejects_sha_that_does_not_resolve_to_a_commit(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    with pytest.raises(GitProvenanceError):
        verify_policy_git_provenance(
            policy_path=policy_path, validation_policy_id=policy.validation_policy_id,
            expected_policy_content_hash=compute_policy_content_hash(policy),
            policy_git_sha="not_a_commit_ish", repo_dir=repo_dir,
        )


def test_git_provenance_head_and_dirty_working_tree_together(tmp_path):
    """Combines Décision 6 (policy_git_sha must equal HEAD) and the dirty-working-tree contract
    (committed blob is the only source of truth) -- both must hold simultaneously."""
    repo_dir, policy_path, sha_a, policy = _commit_policy(tmp_path)
    (repo_dir / "README.md").write_text("x", encoding="utf-8")
    _run_git(["add", "README.md"], repo_dir)
    _run_git(["commit", "-m", "unrelated"], repo_dir)
    sha_b = _run_git(["rev-parse", "HEAD"], repo_dir).strip()
    policy_path.write_text('{"validation_policy_id": "pol_test", "scientific_criteria": {}}', encoding="utf-8")
    verify_policy_git_provenance(
        policy_path=policy_path, validation_policy_id=policy.validation_policy_id,
        expected_policy_content_hash=compute_policy_content_hash(policy),
        policy_git_sha=sha_b, repo_dir=repo_dir,
    )  # HEAD == sha_b, committed blob at B matches -- accepted despite dirty working tree


def test_git_provenance_resolves_repo_independent_of_process_cwd(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    original_cwd = os.getcwd()
    os.chdir(elsewhere)
    try:
        verify_policy_git_provenance(
            policy_path=policy_path, validation_policy_id=policy.validation_policy_id,
            expected_policy_content_hash=compute_policy_content_hash(policy),
            policy_git_sha=sha, repo_dir=repo_dir,
        )  # must resolve the repo via explicit repo_dir, never the process CWD
    finally:
        os.chdir(original_cwd)


# -- genuine 2-process race on the SAME scope_key -----------------------------------------


def test_two_process_race_exactly_one_winner(tmp_path):
    pre_a = _preregistration(tmp_path, policy_id="pol_race_a")
    pre_b = _preregistration(tmp_path, policy_id="pol_race_b")
    assert pre_a.scope_key == pre_b.scope_key
    assert pre_a.preregistration_id != pre_b.preregistration_id

    target_path = tmp_path / "preregistrations" / f"{pre_a.scope_key}.json"
    barrier_path = tmp_path / "barrier"
    worker_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_gate_v_preregistration_race_worker.py")

    procs = []
    for label, pre in (("a", pre_a), ("b", pre_b)):
        data_path = tmp_path / f"data_{label}.json"
        data_path.write_text(json.dumps(dataclasses.asdict(pre)), encoding="utf-8")
        result_path = tmp_path / f"result_{label}.txt"
        proc = subprocess.Popen(
            [sys.executable, worker_script, str(data_path), str(target_path), str(barrier_path), str(result_path)]
        )
        procs.append((label, proc, result_path))

    time.sleep(0.3)  # let both workers reach the barrier busy-wait
    barrier_path.write_text("go", encoding="utf-8")

    for label, proc, result_path in procs:
        proc.wait(timeout=15)

    results = {label: result_path.read_text(encoding="utf-8") for label, _, result_path in procs}
    outcomes = list(results.values())
    assert outcomes.count("OK") == 1, f"expected exactly 1 winner, got {results}"
    assert sum(1 for o in outcomes if o.startswith("FAIL:FileExistsError")) == 1, f"expected exactly 1 refusal, got {results}"

    winner_label = next(label for label, outcome in results.items() if outcome == "OK")
    winner_pre = pre_a if winner_label == "a" else pre_b
    loaded = load_gate_v_preregistration(target_path)
    assert loaded == winner_pre  # artifact on disk is exactly the winner's full content, never a mix
