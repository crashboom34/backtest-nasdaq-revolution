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


# -- Slice C : provenance Git HISTORIQUE (ADR 0025 Décision 20.10) ---------------------------
# `verify_policy_git_provenance()` reste la règle de CRÉATION (policy_git_sha == HEAD courant).
# `verify_policy_git_provenance_historical()` sert la construction du Plan V2 et toute relecture :
# jamais de comparaison au HEAD courant, jamais de lecture du working tree comme vérité.


def _historical(**kwargs):
    from gate_v_preregistration import verify_policy_git_provenance_historical

    return verify_policy_git_provenance_historical(**kwargs)


def _hist_kwargs(policy_path, policy, sha, repo_dir):
    return dict(
        policy_path=policy_path, validation_policy_id=policy.validation_policy_id,
        expected_policy_content_hash=compute_policy_content_hash(policy),
        policy_git_sha=sha, repo_dir=repo_dir,
    )


def _commit_unrelated(repo_dir, name="README.md", content="unrelated change"):
    (repo_dir / name).write_text(content, encoding="utf-8")
    _run_git(["add", name], repo_dir)
    _run_git(["commit", "-m", f"unrelated {uuid.uuid4().hex}"], repo_dir)
    return _run_git(["rev-parse", "HEAD"], repo_dir).strip()


def test_historical_provenance_boundary_creation_refuses_old_sha_historical_accepts(tmp_path):
    """TEST CRITIQUE de frontière (Décision 20.10) : commit A = policy, commit B = changement sans
    rapport, HEAD = B. La création (HEAD exigé) refuse SHA A ; l'API historique l'accepte."""
    repo_dir, policy_path, sha_a, policy = _commit_policy(tmp_path)
    sha_b = _commit_unrelated(repo_dir)
    assert sha_a != sha_b
    assert _run_git(["rev-parse", "HEAD"], repo_dir).strip() == sha_b

    with pytest.raises(GitProvenanceError):
        verify_policy_git_provenance(**_hist_kwargs(policy_path, policy, sha_a, repo_dir))
    _historical(**_hist_kwargs(policy_path, policy, sha_a, repo_dir))  # accepté, HEAD == B ignoré

    # La création, elle, reste inchangée : SHA == HEAD courant accepté.
    verify_policy_git_provenance(**_hist_kwargs(policy_path, policy, sha_b, repo_dir))


def test_historical_provenance_accepts_head_itself(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    _historical(**_hist_kwargs(policy_path, policy, sha, repo_dir))


def test_historical_provenance_blob_at_sha_is_truth_not_working_tree_modified(tmp_path):
    repo_dir, policy_path, sha_a, policy = _commit_policy(tmp_path)
    _commit_unrelated(repo_dir)
    policy_path.write_text('{"validation_policy_id": "pol_test", "scientific_criteria": {}}', encoding="utf-8")
    _historical(**_hist_kwargs(policy_path, policy, sha_a, repo_dir))


def test_historical_provenance_blob_at_sha_is_truth_not_working_tree_deleted(tmp_path):
    repo_dir, policy_path, sha_a, policy = _commit_policy(tmp_path)
    _commit_unrelated(repo_dir)
    policy_path.unlink()
    assert not policy_path.exists()
    _historical(**_hist_kwargs(policy_path, policy, sha_a, repo_dir))


def test_historical_provenance_survives_policy_removed_in_later_commit(tmp_path):
    repo_dir, policy_path, sha_a, policy = _commit_policy(tmp_path)
    _run_git(["rm", "-q", "validation_policies/pol_test.json"], repo_dir)
    _run_git(["commit", "-m", f"remove policy {uuid.uuid4().hex}"], repo_dir)
    assert not policy_path.exists()
    _historical(**_hist_kwargs(policy_path, policy, sha_a, repo_dir))


def test_historical_provenance_refuses_nonexistent_sha(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    with pytest.raises(GitProvenanceError):
        _historical(**_hist_kwargs(policy_path, policy, "0" * 40, repo_dir))


def test_historical_provenance_refuses_sha_that_is_not_a_commit(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    blob_sha = _run_git(["rev-parse", f"{sha}:validation_policies/pol_test.json"], repo_dir).strip()
    tree_sha = _run_git(["rev-parse", f"{sha}^{{tree}}"], repo_dir).strip()
    for not_a_commit in (blob_sha, tree_sha):
        assert len(not_a_commit) == 40
        with pytest.raises(GitProvenanceError):
            _historical(**_hist_kwargs(policy_path, policy, not_a_commit, repo_dir))


def test_historical_provenance_refuses_symbolic_refs_and_short_or_non_canonical_shas(tmp_path):
    """Un ancrage historique doit être un identifiant d'objet immuable COMPLET : `HEAD`/nom de
    branche/tag bougent, un SHA court peut devenir ambigu, la casse non canonique n'est pas un
    identifiant canonique — tous refusés (jamais résolus silencieusement)."""
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_dir).strip()
    _run_git(["tag", "policy-tag"], repo_dir)
    for bad in ("HEAD", branch, "policy-tag", sha[:12], sha.upper(), f"{sha}~0", f"{sha}^{{commit}}", "", "  "):
        with pytest.raises(GitProvenanceError):
            _historical(**_hist_kwargs(policy_path, policy, bad, repo_dir))
    with pytest.raises(GitProvenanceError):
        _historical(**_hist_kwargs(policy_path, policy, None, repo_dir))


def test_historical_provenance_refuses_blob_absent_at_that_commit(tmp_path):
    repo_dir = _init_git_repo(tmp_path)
    sha_before = _commit_unrelated(repo_dir)  # commit sans policy
    policies_dir = repo_dir / "validation_policies"
    policies_dir.mkdir()
    policy_path = policies_dir / "pol_test.json"
    policy = _policy("pol_test")
    save_gate_v_validation_policy(policy_path, policy)
    _run_git(["add", "validation_policies"], repo_dir)
    _run_git(["commit", "-m", f"add policy {uuid.uuid4().hex}"], repo_dir)
    with pytest.raises(GitProvenanceError):
        _historical(**_hist_kwargs(policy_path, policy, sha_before, repo_dir))


def test_historical_provenance_refuses_invalid_json_blob(tmp_path):
    repo_dir = _init_git_repo(tmp_path)
    policies_dir = repo_dir / "validation_policies"
    policies_dir.mkdir()
    policy_path = policies_dir / "pol_test.json"
    policy_path.write_text("{ not json", encoding="utf-8")
    _run_git(["add", "validation_policies"], repo_dir)
    _run_git(["commit", "-m", f"broken policy {uuid.uuid4().hex}"], repo_dir)
    sha = _run_git(["rev-parse", "HEAD"], repo_dir).strip()
    with pytest.raises(GitProvenanceError):
        _historical(**_hist_kwargs(policy_path, _policy("pol_test"), sha, repo_dir))


def test_historical_provenance_refuses_malformed_committed_policy(tmp_path):
    repo_dir = _init_git_repo(tmp_path)
    policies_dir = repo_dir / "validation_policies"
    policies_dir.mkdir()
    policy_path = policies_dir / "pol_test.json"
    policy_path.write_text('{"validation_policy_id": "pol_test"}', encoding="utf-8")  # critères manquants
    _run_git(["add", "validation_policies"], repo_dir)
    _run_git(["commit", "-m", f"malformed policy {uuid.uuid4().hex}"], repo_dir)
    sha = _run_git(["rev-parse", "HEAD"], repo_dir).strip()
    with pytest.raises(GitProvenanceError):
        _historical(**_hist_kwargs(policy_path, _policy("pol_test"), sha, repo_dir))


def test_historical_provenance_refuses_policy_id_mismatch(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    kwargs = _hist_kwargs(policy_path, policy, sha, repo_dir)
    kwargs["validation_policy_id"] = "another_policy"
    with pytest.raises(GitProvenanceError):
        _historical(**kwargs)


def test_historical_provenance_refuses_policy_content_hash_mismatch(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    kwargs = _hist_kwargs(policy_path, policy, sha, repo_dir)
    kwargs["expected_policy_content_hash"] = "0" * 64
    with pytest.raises(GitProvenanceError):
        _historical(**kwargs)


def test_historical_provenance_refuses_policy_path_outside_repo(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    outside = tmp_path / "outside_policy.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(GitProvenanceError):
        _historical(**_hist_kwargs(outside, policy, sha, repo_dir))


def test_historical_provenance_independent_of_process_cwd(tmp_path):
    repo_dir, policy_path, sha_a, policy = _commit_policy(tmp_path)
    _commit_unrelated(repo_dir)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    original_cwd = os.getcwd()
    os.chdir(elsewhere)
    try:
        _historical(**_hist_kwargs(policy_path, policy, sha_a, repo_dir))
    finally:
        os.chdir(original_cwd)


def test_creation_provenance_signature_and_head_rule_unchanged():
    """Non-régression Slice B : la règle de création n'est ni affaiblie ni renommée."""
    import inspect

    params = inspect.signature(verify_policy_git_provenance).parameters
    assert list(params) == [
        "policy_path", "validation_policy_id", "expected_policy_content_hash", "policy_git_sha", "repo_dir",
    ]
    assert params["repo_dir"].default is None


# -- Slice C : helpers canoniques de géométrie de folds (aucune troisième formule) --------------
# La formule existe déjà dans `gate_v_campaign._fold_definitions_hash` (V1, référence de
# compatibilité) et dans `build_gate_v_preregistration()` (Slice B). Slice C ne doit PAS en créer
# une troisième : elle réutilise ces helpers publics de Slice B, dont la sortie est verrouillée
# ici contre la formule V1 indépendante (jamais recopiée dans le test : appel du code V1 réel).


def _fold_geometry_inputs(readiness_spec=None):
    from walk_forward import compute_fold_definitions

    split_plan = _split_plan()
    spec = _wf_spec()
    return split_plan, spec, readiness_spec, compute_fold_definitions(split_plan.validation, spec, readiness_spec)


def test_fold_definitions_hash_equals_v1_reference_formula():
    import gate_v_campaign
    from gate_v_preregistration import compute_fold_definitions_hash

    _, _, _, fold_definitions = _fold_geometry_inputs()
    assert len(fold_definitions) > 0
    assert compute_fold_definitions_hash(fold_definitions) == gate_v_campaign._fold_definitions_hash(fold_definitions)


def test_validation_zone_hash_equals_independent_canonical_formula():
    import hashlib

    from gate_v_preregistration import compute_validation_zone_hash

    split_plan = _split_plan()
    manual = json.dumps(
        dataclasses.asdict(split_plan.validation), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    assert compute_validation_zone_hash(split_plan.validation) == hashlib.sha256(manual.encode("utf-8")).hexdigest()


def test_fold_geometry_helper_matches_v1_plan_values_with_and_without_readiness():
    import gate_v_campaign
    from gate_v_preregistration import compute_fold_geometry
    from strategy_contracts import DailyStateReadiness

    for readiness in (None, DailyStateReadiness(latest_safe_start_hour=9, latest_safe_start_minute=30)):
        split_plan, spec, readiness_spec, fold_definitions = _fold_geometry_inputs(readiness)
        fold_ids, definitions_hash, zone_hash = compute_fold_geometry(split_plan, spec, readiness_spec)
        assert fold_ids == tuple(fold.fold_id for fold in fold_definitions)
        assert isinstance(fold_ids, tuple)
        assert definitions_hash == gate_v_campaign._fold_definitions_hash(fold_definitions)
        assert len(zone_hash) == 64


def test_fold_geometry_helper_requires_a_validation_zone():
    from gate_v_preregistration import compute_fold_geometry

    plan_without_validation = build_dataset_split_plan(
        split_plan_id="plan_nv", dataset_snapshot_id=_SNAPSHOT_ID,
        train=build_split_boundary("2020-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00"),
        final_holdout=build_split_boundary("2024-06-01T00:00:00+00:00", "2024-09-01T00:00:00+00:00"),
    )
    assert plan_without_validation.validation is None
    with pytest.raises(ValueError):
        compute_fold_geometry(plan_without_validation, _wf_spec(), None)


def test_preregistration_fingerprint_unchanged_by_helper_extraction(tmp_path):
    """Non-régression Slice B : l'empreinte de protocole construite par le builder doit rester
    égale à celle recalculée en appelant directement la fonction canonique avec les helpers."""
    from gate_v_preregistration import compute_fold_geometry
    from validation_run import MONTE_CARLO_SEMANTICS_VERSION, PARAMETER_STABILITY_SEMANTICS_VERSION
    from dataset_split import dataset_split_plan_fingerprint

    # Les hashes de ResearchRun/DatasetSplitPlan dépendent de leur horodatage interne : mêmes objets.
    split_plan, spec = _split_plan(), _wf_spec()
    pre = _preregistration(tmp_path, split_plan=split_plan, walk_forward_specification=spec)
    fold_ids, definitions_hash, zone_hash = compute_fold_geometry(split_plan, spec, None)
    recomputed = compute_campaign_protocol_fingerprint(
        research_run_id=pre.research_run_id, research_run_content_hash=pre.research_run_content_hash,
        dataset_snapshot_id=pre.dataset_snapshot_id, split_plan_id=pre.split_plan_id,
        split_plan_fingerprint=dataset_split_plan_fingerprint(split_plan),
        strategy_name=pre.strategy_name, base_params={"n_neighbors": 5}, search_mode="single_var",
        search_space_hash="a" * 12, budget_per_fold=10, walk_forward_specification=spec,
        readiness_spec=None, expected_fold_ids=fold_ids, expected_fold_definitions_hash=definitions_hash,
        validation_zone_hash=zone_hash, walk_forward_spec_semantics_version=spec.walk_forward_semantics_version,
        monte_carlo_semantics_version=MONTE_CARLO_SEMANTICS_VERSION,
        parameter_stability_semantics_version=PARAMETER_STABILITY_SEMANTICS_VERSION,
        gate_v_validation_policy_id=pre.gate_v_validation_policy_id, policy_content_hash=pre.policy_content_hash,
        assessment_semantics_version=pre.assessment_semantics_version,
    )
    assert recomputed == pre.campaign_protocol_fingerprint


# -- Slice C (MAJOR 1) : `policy_git_sha` TOUJOURS canonique (SHA complet) avant persistance ------
# Une entrée symbolique (`HEAD`, branche, tag) ou abrégée peut résoudre vers HEAD à la création
# mais DOIT être remplacée par l'identité immuable complète du commit : jamais un ref mutable dans
# l'artefact, l'id ou le hash. La règle de création (commit résolu == HEAD) reste intacte.


def _shared_sources():
    return _research_run(), _split_plan(), _wf_spec()


def _build_prereg_with_sha(repo_dir, policy_path, policy, sources, policy_git_sha):
    research_run, split_plan, spec = sources
    return build_gate_v_preregistration(
        research_run=research_run, split_plan=split_plan, strategy_name="perfect_revolution_v1",
        base_params={"n_neighbors": 5}, search_mode="single_var", search_space_hash="a" * 12,
        budget_per_fold=10, walk_forward_specification=spec, readiness_spec=None, policy=policy,
        policy_path=policy_path, assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION,
        repo_dir=repo_dir, policy_git_sha=policy_git_sha,
    )


def _symbolic_and_short_forms(repo_dir, sha):
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_dir).strip()
    tag = f"pol-tag-{uuid.uuid4().hex[:6]}"
    _run_git(["tag", tag], repo_dir)
    return {
        "auto": "auto", "HEAD": "HEAD", "branch": branch, "tag": tag,
        "short7": sha[:7], "short12": sha[:12], "full": sha, "HEAD_commitish": "HEAD^{commit}",
    }


def test_preregistration_persists_canonical_full_sha_for_every_accepted_form(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    assert len(sha) == 40
    sources = _shared_sources()
    forms = _symbolic_and_short_forms(repo_dir, sha)
    built = {label: _build_prereg_with_sha(repo_dir, policy_path, policy, sources, value)
             for label, value in forms.items()}
    head_full = _run_git(["rev-parse", "HEAD^{commit}"], repo_dir).strip()
    for label, pre in built.items():
        assert pre.policy_git_sha == head_full, f"{label}: {pre.policy_git_sha!r} != {head_full!r}"
    # Même identité quelle que soit la forme d'entrée (id/hash dérivés du SHA canonique).
    assert len({pre.preregistration_id for pre in built.values()}) == 1
    assert len({pre.preregistration_content_hash for pre in built.values()}) == 1


def test_saved_preregistration_artifact_contains_the_full_canonical_sha(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    pre = _build_prereg_with_sha(repo_dir, policy_path, policy, _shared_sources(), "HEAD")
    saved = save_gate_v_preregistration(tmp_path / "pre" / "p.json", pre)
    record = json.loads(saved.read_text(encoding="utf-8"))
    assert record["policy_git_sha"] == sha
    assert load_gate_v_preregistration(saved).policy_git_sha == sha


def test_preregistration_id_is_computed_from_the_canonical_sha_not_the_raw_input(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    pre = _build_prereg_with_sha(repo_dir, policy_path, policy, _shared_sources(), sha[:10])
    recomputed = compute_preregistration_id(
        scope_key=pre.scope_key, campaign_protocol_fingerprint=pre.campaign_protocol_fingerprint,
        research_run_id=pre.research_run_id, research_run_content_hash=pre.research_run_content_hash,
        dataset_snapshot_id=pre.dataset_snapshot_id, split_plan_id=pre.split_plan_id,
        strategy_name=pre.strategy_name, gate_v_validation_policy_id=pre.gate_v_validation_policy_id,
        policy_content_hash=pre.policy_content_hash, policy_git_sha=sha,
        assessment_semantics_version=pre.assessment_semantics_version,
        preregistration_semantics_version=pre.preregistration_semantics_version,
    )
    assert pre.preregistration_id == recomputed


def test_creation_still_refuses_any_form_of_an_old_commit_when_head_advanced(tmp_path):
    """La garantie de création `commit résolu == HEAD` reste intacte, pour TOUTE forme d'entrée
    désignant un ancien commit (SHA complet, court, tag)."""
    repo_dir, policy_path, sha_a, policy = _commit_policy(tmp_path)
    _run_git(["tag", "at-a"], repo_dir)
    sha_b = _commit_unrelated(repo_dir)
    assert sha_a != sha_b
    sources = _shared_sources()
    for old_form in (sha_a, sha_a[:12], "at-a", "HEAD~1", f"{sha_a}^{{commit}}"):
        with pytest.raises(GitProvenanceError):
            _build_prereg_with_sha(repo_dir, policy_path, policy, sources, old_form)
    # Et HEAD (nouveau) reste accepté, canonicalisé.
    pre = _build_prereg_with_sha(repo_dir, policy_path, policy, sources, "HEAD")
    assert pre.policy_git_sha == sha_b


def test_creation_refuses_unresolvable_refs_non_commits_and_option_like_values(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    blob_sha = _run_git(["rev-parse", f"{sha}:validation_policies/pol_test.json"], repo_dir).strip()
    tree_sha = _run_git(["rev-parse", f"{sha}^{{tree}}"], repo_dir).strip()
    sources = _shared_sources()
    for bad in ("no_such_branch", "0" * 40, blob_sha, tree_sha, "--all", "-h", "", "   ", None, 7, "HEAD\x00x", "\x00"):
        with pytest.raises(GitProvenanceError):
            _build_prereg_with_sha(repo_dir, policy_path, policy, sources, bad)


def test_resolve_policy_git_sha_returns_the_full_canonical_commit_id(tmp_path):
    from gate_v_preregistration import _resolve_policy_git_sha

    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    for value in ("auto", "HEAD", sha[:9], sha):
        assert _resolve_policy_git_sha(value, repo_dir) == sha


def test_preregistration_created_with_symbolic_head_is_consumable_historically_after_head_advances(tmp_path):
    """Scénario de bout en bout qui ferme le MAJOR : entrée symbolique `HEAD` -> artefact = SHA
    complet -> HEAD avance -> la vérification historique (Slice C) de l'ancien SHA réussit."""
    from gate_v_preregistration import verify_policy_git_provenance_historical

    repo_dir, policy_path, sha_a, policy = _commit_policy(tmp_path)
    pre = _build_prereg_with_sha(repo_dir, policy_path, policy, _shared_sources(), "HEAD")
    assert pre.policy_git_sha == sha_a
    sha_b = _commit_unrelated(repo_dir)
    assert sha_b != sha_a
    verify_policy_git_provenance_historical(
        policy_path=policy_path, validation_policy_id=pre.gate_v_validation_policy_id,
        expected_policy_content_hash=pre.policy_content_hash, policy_git_sha=pre.policy_git_sha,
        repo_dir=repo_dir,
    )
    # La vérification de création, elle, refuse désormais cet ancien SHA (HEAD a avancé).
    with pytest.raises(GitProvenanceError):
        verify_policy_git_provenance(
            policy_path=policy_path, validation_policy_id=pre.gate_v_validation_policy_id,
            expected_policy_content_hash=pre.policy_content_hash, policy_git_sha=pre.policy_git_sha,
            repo_dir=repo_dir,
        )


# -- Slice C (MAJOR 2) : protocole validé AVANT qu'un scope exclusif puisse être consommé ---------
# Le plan V1 impose déjà : search_mode dans 4 valeurs, search_space_hash = 12 hex (normalisé en
# minuscule avant fingerprint), budget_per_fold = int > 0 (bool interdit). Slice B ne doit JAMAIS
# accepter un protocole que le Plan V2 (Slice C) rejetterait ensuite : une seule validation
# canonique, partagée par `build_gate_v_preregistration()` et `build_gate_v_campaign_plan_v2()`.


def _prereg_with_protocol(tmp_path, **protocol_overrides):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    protocol = dict(
        strategy_name="perfect_revolution_v1", base_params={"n_neighbors": 5}, search_mode="single_var",
        search_space_hash="a" * 12, budget_per_fold=10, walk_forward_specification=_wf_spec(), readiness_spec=None,
    )
    protocol.update(protocol_overrides)
    return build_gate_v_preregistration(
        research_run=_research_run(), split_plan=_split_plan(), policy=policy, policy_path=policy_path,
        assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION, repo_dir=repo_dir, **protocol,
    )


def test_search_mode_constant_is_the_four_v1_modes():
    import gate_v_campaign
    from gate_v_preregistration import GATE_V_SEARCH_MODES

    assert GATE_V_SEARCH_MODES == frozenset({"single_var", "cross_zone", "grid", "general"})
    assert GATE_V_SEARCH_MODES == gate_v_campaign._SEARCH_MODES  # garde anti-dérive vs V1


def test_preregistration_accepts_the_four_historical_search_modes(tmp_path):
    from gate_v_preregistration import GATE_V_SEARCH_MODES

    for mode in sorted(GATE_V_SEARCH_MODES):
        assert _prereg_with_protocol(tmp_path, search_mode=mode).campaign_protocol_fingerprint


def test_preregistration_refuses_invalid_search_mode_before_any_scope_is_consumed(tmp_path):
    for bad in ("random", "", " grid", "GRID", "grid ", None, 5, ["grid"], b"grid"):
        with pytest.raises(ValueError):
            _prereg_with_protocol(tmp_path, search_mode=bad)


def test_preregistration_refuses_invalid_search_space_hash(tmp_path):
    for bad in ("", " ", "abc", "g" * 12, "a" * 11, "a" * 13, " " + "a" * 11, "a" * 11 + "\n", None, 123456789012, b"a" * 12):
        with pytest.raises(ValueError):
            _prereg_with_protocol(tmp_path, search_space_hash=bad)


def test_preregistration_normalizes_search_space_hash_to_lowercase_like_v1(tmp_path):
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    sources = _shared_sources()
    research_run, split_plan, spec = sources

    def _build(search_space_hash):
        return build_gate_v_preregistration(
            research_run=research_run, split_plan=split_plan, strategy_name="perfect_revolution_v1",
            base_params={"n_neighbors": 5}, search_mode="single_var", search_space_hash=search_space_hash,
            budget_per_fold=10, walk_forward_specification=spec, readiness_spec=None, policy=policy,
            policy_path=policy_path, assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION,
            repo_dir=repo_dir,
        )

    lower, upper, mixed = _build("abcdef012345"), _build("ABCDEF012345"), _build("AbCdEf012345")
    assert lower.campaign_protocol_fingerprint == upper.campaign_protocol_fingerprint == mixed.campaign_protocol_fingerprint
    assert lower.preregistration_id == upper.preregistration_id == mixed.preregistration_id


def test_preregistration_refuses_invalid_budget_per_fold(tmp_path):
    for bad in (0, -1, -10, True, False, 1.5, 10.0, "10", None, [10]):
        with pytest.raises(ValueError):
            _prereg_with_protocol(tmp_path, budget_per_fold=bad)
    assert _prereg_with_protocol(tmp_path, budget_per_fold=1).campaign_protocol_fingerprint


def test_invalid_protocol_never_consumes_the_exclusive_scope_path(tmp_path):
    """Un protocole invalide échoue à la CONSTRUCTION : aucun objet à sauvegarder, donc aucun
    fichier de scope créé ; le même scope reste ensuite disponible pour un protocole valide."""
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    research_run, split_plan, spec = _shared_sources()
    scope_path = tmp_path / "preregistrations" / f"{compute_scope_key(research_run.research_run_id, research_run.dataset_snapshot_id, split_plan.split_plan_id, 'perfect_revolution_v1')}.json"

    def _build(**overrides):
        kwargs = dict(
            research_run=research_run, split_plan=split_plan, strategy_name="perfect_revolution_v1",
            base_params={"n_neighbors": 5}, search_mode="single_var", search_space_hash="a" * 12,
            budget_per_fold=10, walk_forward_specification=spec, readiness_spec=None, policy=policy,
            policy_path=policy_path, assessment_semantics_version=_ASSESSMENT_SEMANTICS_VERSION,
            repo_dir=repo_dir,
        )
        kwargs.update(overrides)
        return build_gate_v_preregistration(**kwargs)

    for overrides in ({"search_mode": "random"}, {"search_space_hash": "xyz"}, {"budget_per_fold": 0}):
        with pytest.raises(ValueError):
            _build(**overrides)
        assert not scope_path.exists()
    pre = _build()
    assert save_gate_v_preregistration(scope_path, pre) == scope_path


def test_preregistration_refuses_other_protocol_inputs_that_plan_v2_would_reject(tmp_path):
    """Tout ce que le Plan V2 refuserait sur les ENTRÉES de protocole est refusé dès la PreRegistration."""
    from strategy_contracts import DailyStateReadiness

    spec = _wf_spec()
    bad_inputs = (
        {"base_params": {}},
        {"base_params": []},
        {"base_params": None},
        {"base_params": {"x": float("nan")}},
        {"base_params": {"x": float("inf")}},
        {"base_params": {1: "non-str key"}},
        {"base_params": {"x": object()}},
        {"base_params": {"n_neighbors": 6}},  # != walk_forward_specification.base_params
        {"walk_forward_specification": dataclasses.replace(spec, verdict_policy_id="some_policy")},
        {"walk_forward_specification": dataclasses.replace(spec, master_seed="7")},
        {"walk_forward_specification": dataclasses.replace(spec, master_seed=True)},
        {"walk_forward_specification": dataclasses.replace(spec, allow_partial_last_fold=True)},
        {"walk_forward_specification": dataclasses.replace(spec, geometry="anchored")},
        {"walk_forward_specification": "not a spec"},
        {"readiness_spec": "9:30"},
        {"readiness_spec": DailyStateReadiness(latest_safe_start_hour=25, latest_safe_start_minute=0)},
        {"readiness_spec": DailyStateReadiness(latest_safe_start_hour=9, latest_safe_start_minute=60)},
        {"readiness_spec": DailyStateReadiness(latest_safe_start_hour=True, latest_safe_start_minute=0)},
    )
    for overrides in bad_inputs:
        with pytest.raises(ValueError):
            _prereg_with_protocol(tmp_path, **overrides)


def test_canonical_protocol_validation_is_a_single_shared_implementation():
    """Aucune duplication de validation Slice B / Slice C : le module V2 réutilise les symboles de
    Slice B (mêmes objets), sans redéfinir ni ensemble de modes ni motif de hash."""
    import gate_v_campaign_plan_v2 as plan_module
    import gate_v_preregistration as prereg_module

    assert plan_module.validate_campaign_protocol_inputs is prereg_module.validate_campaign_protocol_inputs
    assert plan_module.GATE_V_SEARCH_MODES is prereg_module.GATE_V_SEARCH_MODES
    for duplicated in ("_SEARCH_MODES", "_SEARCH_SPACE_HASH_RE", "_validate_readiness"):
        assert not hasattr(plan_module, duplicated), duplicated


def test_preregistration_refuses_invalid_assessment_semantics_version_before_consuming_the_scope(tmp_path):
    """Revue finale (MAJOR) : le Plan V2 exige `assessment_semantics_version` = chaîne non vide ;
    la PreRegistration doit donc la refuser AVANT toute sauvegarde exclusive (sinon scope mort)."""
    repo_dir, policy_path, sha, policy = _commit_policy(tmp_path)
    research_run, split_plan, spec = _shared_sources()
    for bad in ("", "   ", "\n", None, 5, ["gate_v_assessment_v1"], b"gate_v_assessment_v1"):
        with pytest.raises(ValueError):
            build_gate_v_preregistration(
                research_run=research_run, split_plan=split_plan, strategy_name="perfect_revolution_v1",
                base_params={"n_neighbors": 5}, search_mode="single_var", search_space_hash="a" * 12,
                budget_per_fold=10, walk_forward_specification=spec, readiness_spec=None, policy=policy,
                policy_path=policy_path, assessment_semantics_version=bad, repo_dir=repo_dir,
            )
