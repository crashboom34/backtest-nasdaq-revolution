"""
tests/test_gate_v_final_holdout_claim.py — AF-V-07 Slice E1 : cœur PUR de `FinalHoldoutAccessClaim`.

Contrat normatif : ADR 0025 Décision 10 (identité et hash du claim) ; Décision 22 (E1 = cœur pur,
E2 = acquisition). Aucun fichier de Claim n'est jamais créé ici, aucune
horloge, aucune donnée marché, aucun accès FINAL_HOLDOUT, aucun réseau. Les sources du Plan V2 sont
synthétiques ; le dépôt Git est un dépôt temporaire local hermétique (même fixture que Slice C).
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataset_split import build_dataset_split_plan, build_split_boundary
from gate_v_campaign_plan_v2 import build_gate_v_campaign_plan_v2
from gate_v_final_holdout_claim import (
    FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION,
    FinalHoldoutAccessClaim,
    build_final_holdout_access_claim,
    compute_final_holdout_access_claim_content_hash,
    compute_final_holdout_access_claim_id,
    final_holdout_access_claim_from_record,
    final_holdout_access_claim_to_record,
    validate_final_holdout_access_claim_against_plan,
    validate_final_holdout_access_claim_structure,
)
from gate_v_preregistration import build_gate_v_preregistration
from gate_v_validation_policy import (
    OosPolicyCriterion,
    WalkForwardPolicyCriterion,
    build_gate_v_validation_policy,
    save_gate_v_validation_policy,
)
from research_run import build_research_run
from walk_forward import build_walk_forward_specification

_ROOT = Path(__file__).resolve().parent.parent
_CREATED = "2026-10-11T10:00:00+00:00"
_FIELDS = (
    "claim_semantics_version", "claim_id", "claim_content_hash", "campaign_id",
    "preregistration_id", "preregistration_content_hash", "campaign_protocol_fingerprint",
    "research_run_id", "research_run_content_hash", "dataset_snapshot_id", "split_plan_id",
    "split_plan_fingerprint", "assessment_semantics_version", "created_at",
)
_LINK_FIELDS = (
    "campaign_id", "preregistration_id", "preregistration_content_hash",
    "campaign_protocol_fingerprint", "research_run_id", "research_run_content_hash",
    "dataset_snapshot_id", "split_plan_id", "split_plan_fingerprint", "assessment_semantics_version",
)
_HEX64_FIELDS = (
    "claim_id", "claim_content_hash", "preregistration_id", "preregistration_content_hash",
    "campaign_protocol_fingerprint", "research_run_content_hash", "split_plan_fingerprint",
)


# ============================================================================================
# Fixture : Plan V2 RÉEL (Slice C) construit depuis des sources synthétiques et un dépôt Git local
# ============================================================================================


def _run_git(args, cwd):
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout.strip()


@pytest.fixture
def valid_plan(tmp_path):
    repo = tmp_path / f"repo_{uuid.uuid4().hex[:8]}"
    repo.mkdir()
    _run_git(["init"], repo)
    _run_git(["config", "user.email", "test@example.com"], repo)
    _run_git(["config", "user.name", "Test"], repo)
    policy_dir = repo / "validation_policies"
    policy_dir.mkdir()
    policy_path = policy_dir / "pol_test.json"
    policy = build_gate_v_validation_policy(
        "pol_test",
        {
            "oos": (OosPolicyCriterion(metric="net_ret_pct", operator=">", threshold=0.0),),
            "walk_forward": (
                WalkForwardPolicyCriterion(metric="oos_net_return_pct", operator=">", threshold=0.0),
            ),
        },
    )
    save_gate_v_validation_policy(policy_path, policy)
    _run_git(["add", "validation_policies"], repo)
    _run_git(["commit", "-m", "fixture policy"], repo)

    snapshot = "local_csv:sha256:" + "ab" * 32
    research_run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x", dataset_snapshot_id=snapshot, git_sha=None,
    )
    split = build_dataset_split_plan(
        split_plan_id="plan_x", dataset_snapshot_id=snapshot,
        train=build_split_boundary("2020-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00"),
        validation=build_split_boundary("2024-01-01T00:00:00+00:00", "2024-06-01T00:00:00+00:00"),
        final_holdout=build_split_boundary("2024-06-01T00:00:00+00:00", "2024-09-01T00:00:00+00:00"),
    )
    protocol = dict(
        strategy_name="perfect_revolution_v1", base_params={"n_neighbors": 5}, search_mode="single_var",
        search_space_hash="a" * 12, budget_per_fold=10,
        walk_forward_specification=build_walk_forward_specification(
            base_params={"n_neighbors": 5}, geometry="rolling",
            train_period="P1M", test_period="P1M", step_period="P1M",
        ),
        readiness_spec=None,
    )
    preregistration = build_gate_v_preregistration(
        research_run=research_run, split_plan=split, policy=policy, policy_path=policy_path,
        assessment_semantics_version="gate_v_assessment_v1", repo_dir=repo, **protocol,
    )
    return build_gate_v_campaign_plan_v2(
        preregistration=preregistration, research_run=research_run, split_plan=split,
        policy=policy, policy_path=policy_path, repo_dir=repo, **protocol,
    )


@pytest.fixture
def claim(valid_plan):
    return build_final_holdout_access_claim(valid_plan, created_at=_CREATED)


def _independent_digest(record):
    """Canonicalisation écrite à la main dans le test — jamais le helper du code testé."""
    text = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _preimage(record):
    return {name: record[name] for name in _LINK_FIELDS} | {
        "claim_semantics_version": record["claim_semantics_version"],
    }


def _reseal(record):
    """Recalcule HONNÊTEMENT les deux hashes d'un record modifié : modélise un attaquant auto-cohérent."""
    pre = _preimage(record)
    claim_id = _independent_digest(pre)
    return {**record, "claim_id": claim_id, "claim_content_hash": _independent_digest({**pre, "claim_id": claim_id})}


# -- Contrat structurel (Décisions 10 et 22.3) -----------------------------------------------


def test_semantics_version_constant_exact_value():
    assert FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION == "final_holdout_access_claim_v1"


def test_claim_has_exactly_14_fields_in_normative_order_and_is_frozen():
    assert tuple(f.name for f in dataclasses.fields(FinalHoldoutAccessClaim)) == _FIELDS
    assert len(_FIELDS) == 14
    assert FinalHoldoutAccessClaim.__dataclass_params__.frozen


def test_claim_carries_no_authorization_policy_or_market_field():
    names = {f.name for f in dataclasses.fields(FinalHoldoutAccessClaim)}
    assert not [n for n in names if any(w in n for w in ("verdict", "evidence", "path", "status", "granted"))]
    assert "policy_git_sha" not in names and "gate_v_validation_policy_id" not in names  # transitifs (D10)


# -- Hashes (Décision 10) : vecteurs INDÉPENDANTS --------------------------------------------

_VEC = dict(
    campaign_id="gate_v_v2_" + "1" * 64, preregistration_id="4" * 64,
    preregistration_content_hash="2" * 64, campaign_protocol_fingerprint="3" * 64,
    research_run_id="run_x", research_run_content_hash="5" * 64,
    dataset_snapshot_id="local_csv:sha256:" + "ab" * 32, split_plan_id="plan_x",
    split_plan_fingerprint="6" * 64, assessment_semantics_version="gate_v_assessment_v1",
    claim_semantics_version="final_holdout_access_claim_v1",
)
# Calculés HORS du code testé (JSON canonique écrit à la main, hashlib seul) puis figés.
_VEC_ID = "b90512362558be9b235ea7fc1272a97f45e63b4c0ff3f9201755a8eea435c521"
_VEC_HASH = "a1d80a5c67aed566d591cdb2d9ca5def066b98a2422abc5669022bd09114bb50"


def test_claim_id_matches_fixed_literal_vector():
    assert compute_final_holdout_access_claim_id(**_VEC) == _VEC_ID


def test_claim_content_hash_matches_fixed_literal_vector_and_excludes_itself():
    assert compute_final_holdout_access_claim_content_hash(claim_id=_VEC_ID, **_VEC) == _VEC_HASH
    assert _VEC_HASH != _VEC_ID


def test_built_claim_hashes_equal_independent_recomputation(claim):
    record = final_holdout_access_claim_to_record(claim)
    pre = _preimage(record)
    assert claim.claim_id == _independent_digest(pre)
    assert claim.claim_content_hash == _independent_digest({**pre, "claim_id": claim.claim_id})


@pytest.mark.parametrize("field", _LINK_FIELDS)
def test_every_link_field_changes_both_hashes(field):
    other = {**_VEC, field: _VEC[field][:-1] + ("0" if _VEC[field][-1] != "0" else "1")}
    assert compute_final_holdout_access_claim_id(**other) != _VEC_ID
    assert compute_final_holdout_access_claim_content_hash(claim_id=_VEC_ID, **other) != _VEC_HASH


def test_claim_semantics_version_participates_in_both_hashes():
    other = {**_VEC, "claim_semantics_version": "final_holdout_access_claim_v2"}
    assert compute_final_holdout_access_claim_id(**other) != _VEC_ID
    assert compute_final_holdout_access_claim_content_hash(claim_id=_VEC_ID, **other) != _VEC_HASH


@pytest.mark.parametrize("bad", (None, "", "   ", 3, True, float("nan"), b"x"))
def test_hash_functions_refuse_non_str_or_empty_inputs(bad):
    with pytest.raises(ValueError):
        compute_final_holdout_access_claim_id(**{**_VEC, "research_run_id": bad})
    with pytest.raises(ValueError):
        compute_final_holdout_access_claim_content_hash(claim_id=_VEC_ID, **{**_VEC, "research_run_id": bad})
    with pytest.raises(ValueError):
        compute_final_holdout_access_claim_content_hash(claim_id=bad, **_VEC)


# -- Builder pur -----------------------------------------------------------------------------


def test_builder_projects_the_real_plan_and_validates(claim, valid_plan):
    for name in _LINK_FIELDS:
        assert getattr(claim, name) == getattr(valid_plan, name)
    assert claim.claim_semantics_version == FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION
    assert claim.created_at == _CREATED
    validate_final_holdout_access_claim_structure(claim)
    validate_final_holdout_access_claim_against_plan(claim, valid_plan)
    with pytest.raises(dataclasses.FrozenInstanceError):
        claim.claim_id = "0" * 64


def test_builder_is_deterministic_and_leaves_the_plan_untouched(valid_plan):
    before = dataclasses.asdict(valid_plan)
    first = build_final_holdout_access_claim(valid_plan, created_at=_CREATED)
    second = build_final_holdout_access_claim(valid_plan, created_at=_CREATED)
    assert first == second
    assert dataclasses.asdict(valid_plan) == before


def test_created_at_is_excluded_from_both_hashes_and_kept_verbatim(valid_plan):
    first = build_final_holdout_access_claim(valid_plan, created_at="2026-10-11T10:00:00Z")
    second = build_final_holdout_access_claim(valid_plan, created_at="2027-01-02T14:30:00.123456+02:00")
    assert (first.claim_id, first.claim_content_hash) == (second.claim_id, second.claim_content_hash)
    assert first.created_at == "2026-10-11T10:00:00Z"
    assert second.created_at == "2027-01-02T14:30:00.123456+02:00"  # jamais normalisé ni réécrit


def test_builder_requires_created_at_explicitly(valid_plan):
    with pytest.raises(TypeError):
        build_final_holdout_access_claim(valid_plan)


@pytest.mark.parametrize("bad_time", (
    "", "   ", "2026-10-11T10:00:00", "2026-10-11", "tomorrow", "2026-13-11T10:00:00Z",
    "2026-10-11T25:00:00+00:00", "2026-10-11 10:00:00+00:00", "2026-10-11T10:00Z",
    "2026-10-11T10:00:00+24:00", "2026-10-11T10:00:00+99:99", "2026-10-11T10:00:00Z\n",
    " 2026-10-11T10:00:00Z", "２０２６-10-11T10:00:00Z", None, 20261011, True, b"2026-10-11T10:00:00Z",
))
def test_builder_refuses_invalid_naive_or_non_str_created_at(valid_plan, bad_time):
    with pytest.raises(ValueError):
        build_final_holdout_access_claim(valid_plan, created_at=bad_time)


class _StrSub(str):
    pass


def test_builder_refuses_str_subclass_created_at(valid_plan):
    with pytest.raises(ValueError):
        build_final_holdout_access_claim(valid_plan, created_at=_StrSub(_CREATED))


@pytest.mark.parametrize("make_bad", (
    lambda p: dataclasses.replace(p, campaign_id="0" * 64),
    lambda p: dataclasses.replace(p, campaign_id="gate_v_v2_" + "0" * 64),   # id ≠ recalcul (barrière 2)
    lambda p: dataclasses.replace(p, campaign_protocol_fingerprint="0" * 64),  # barrière 1
    lambda p: dataclasses.replace(p, campaign_plan_semantics_version="gate_v_campaign_plan_v3"),
    lambda p: None, lambda p: {}, lambda p: "plan",
))
def test_builder_refuses_an_invalid_or_foreign_plan(valid_plan, make_bad):
    with pytest.raises(ValueError):
        build_final_holdout_access_claim(make_bad(valid_plan), created_at=_CREATED)


def test_builder_never_reads_the_clock(valid_plan, monkeypatch):
    import datetime as dt

    class _Boom(dt.datetime):
        @classmethod
        def now(cls, *a, **k):  # pragma: no cover - ne doit jamais être appelé
            raise AssertionError("E1 ne doit jamais lire l'horloge")

        @classmethod
        def utcnow(cls):  # pragma: no cover
            raise AssertionError("E1 ne doit jamais lire l'horloge")

    import gate_v_final_holdout_claim as module

    monkeypatch.setattr(module, "datetime", _Boom)
    build_final_holdout_access_claim(valid_plan, created_at=_CREATED)


# -- Record strict : to_record / from_record -------------------------------------------------


def test_record_has_exactly_14_keys_in_order_and_roundtrips(claim):
    record = final_holdout_access_claim_to_record(claim)
    assert tuple(record) == _FIELDS
    assert all(type(value) is str for value in record.values())
    assert json.loads(json.dumps(record)) == record
    assert final_holdout_access_claim_from_record(record) == claim
    assert final_holdout_access_claim_to_record(final_holdout_access_claim_from_record(record)) == record


def test_from_record_refuses_extra_and_missing_keys(claim):
    record = final_holdout_access_claim_to_record(claim)
    with pytest.raises(ValueError):
        final_holdout_access_claim_from_record({**record, "extra": "x"})
    for name in _FIELDS:
        with pytest.raises(ValueError):
            final_holdout_access_claim_from_record({k: v for k, v in record.items() if k != name})


class _DictSub(dict):
    pass


@pytest.mark.parametrize("bad", (None, [], "string", 2, ()))
def test_from_record_refuses_non_object(bad):
    with pytest.raises(ValueError):
        final_holdout_access_claim_from_record(bad)


def test_from_record_refuses_dict_subclass(claim):
    with pytest.raises(ValueError):
        final_holdout_access_claim_from_record(_DictSub(final_holdout_access_claim_to_record(claim)))


@pytest.mark.parametrize("field", _FIELDS)
def test_every_field_refuses_non_str_empty_or_str_subclass(claim, field):
    record = final_holdout_access_claim_to_record(claim)
    for invalid in (None, False, True, 3, 1.5, float("nan"), b"x", [], "", "   ", _StrSub(record[field])):
        with pytest.raises(ValueError):
            final_holdout_access_claim_from_record({**record, field: invalid})


@pytest.mark.parametrize("field", _HEX64_FIELDS)
def test_hash_shaped_fields_refuse_malformed_sha256(claim, field):
    record = final_holdout_access_claim_to_record(claim)
    valid = record[field]
    for invalid in (valid.upper(), valid[:-1], valid + "0", "z" * 64, valid + "\n", " " + valid, "٠" * 64):
        with pytest.raises(ValueError):
            final_holdout_access_claim_from_record({**record, field: invalid})


@pytest.mark.parametrize("field", (
    "preregistration_id", "preregistration_content_hash", "campaign_protocol_fingerprint",
    "research_run_content_hash", "split_plan_fingerprint",
))
def test_a_resealed_claim_with_non_canonical_hex_is_refused_by_format_not_only_by_hash(claim, field):
    """Un attaquant qui RECALCULE les deux hashes ne doit pas pouvoir faire passer un hex non canonique."""
    record = final_holdout_access_claim_to_record(claim)
    assert record[field].upper() != record[field]  # garde du test : la valeur contient bien des lettres
    for invalid in (record[field].upper(), record[field] + "0", record[field][:-1]):
        with pytest.raises(ValueError):
            final_holdout_access_claim_from_record(_reseal({**record, field: invalid}))


@pytest.mark.parametrize("campaign_id", (
    "0" * 64, "gate_v_" + "0" * 64, "gate_v_v2_" + "0" * 63, "gate_v_v2_" + "0" * 65, "gate_v_v2_" + "G" * 64,
    "gate_v_v2_" + "0" * 64 + "\n",
))
def test_campaign_id_must_have_the_v2_shape(claim, campaign_id):
    record = _reseal({**final_holdout_access_claim_to_record(claim), "campaign_id": campaign_id})
    with pytest.raises(ValueError):
        final_holdout_access_claim_from_record(record)


def test_unknown_semantics_version_is_refused_even_when_rehashed(claim):
    record = _reseal({**final_holdout_access_claim_to_record(claim), "claim_semantics_version": "future_v2"})
    with pytest.raises(ValueError):
        final_holdout_access_claim_from_record(record)


@pytest.mark.parametrize("bad_time", (
    "2026-10-11T10:00:00", "2026-10-11", "2026-10-11T10:00:00+24:00", "２０２６-10-11T10:00:00Z",
    "2026-10-11T10:00:00Z\n", "tomorrow", "",
))
def test_from_record_refuses_invalid_naive_or_non_ascii_created_at_even_when_rehashed(claim, bad_time):
    """created_at est hors des hashes : la validation de son format ne peut pas venir du recalcul."""
    record = _reseal({**final_holdout_access_claim_to_record(claim), "created_at": bad_time})
    with pytest.raises(ValueError):
        final_holdout_access_claim_from_record(record)


@pytest.mark.parametrize("field", ("claim_id", "claim_content_hash"))
def test_a_forged_but_well_formed_hash_is_refused(claim, field):
    record = final_holdout_access_claim_to_record(claim)
    with pytest.raises(ValueError):
        final_holdout_access_claim_from_record({**record, field: "0" * 64})


@pytest.mark.parametrize("field", _LINK_FIELDS)
def test_tampering_one_link_field_with_a_still_valid_format_is_caught_by_recalculation(claim, field):
    record = final_holdout_access_claim_to_record(claim)
    old = record[field]
    tampered = {**record, field: old[:-1] + ("0" if old[-1] != "0" else "1")}  # format préservé
    with pytest.raises(ValueError, match="incohérent"):
        final_holdout_access_claim_from_record(tampered)


def test_to_record_and_structure_refuse_a_directly_instantiated_invalid_claim(claim):
    forged = dataclasses.replace(claim, claim_content_hash="0" * 64)  # l'instanciation directe ne revalide rien
    with pytest.raises(ValueError):
        final_holdout_access_claim_to_record(forged)
    with pytest.raises(ValueError):
        validate_final_holdout_access_claim_structure(forged)
    for bad in (None, {}, "claim", 3):
        with pytest.raises(ValueError):
            validate_final_holdout_access_claim_structure(bad)
        with pytest.raises(ValueError):
            final_holdout_access_claim_to_record(bad)


# -- Liaison au Plan V2 ----------------------------------------------------------------------


def test_against_plan_accepts_the_matching_plan_only(claim, valid_plan):
    validate_final_holdout_access_claim_against_plan(claim, valid_plan)
    with pytest.raises(ValueError):
        validate_final_holdout_access_claim_against_plan(claim, None)


@pytest.mark.parametrize("field", _LINK_FIELDS)
def test_a_self_coherent_claim_with_one_diverging_link_is_refused_against_the_plan(claim, valid_plan, field):
    record = final_holdout_access_claim_to_record(claim)
    old = record[field]
    altered = final_holdout_access_claim_from_record(
        _reseal({**record, field: old[:-1] + ("0" if old[-1] != "0" else "1")})
    )
    validate_final_holdout_access_claim_structure(altered)  # auto-cohérent : la structure seule ne le voit pas
    with pytest.raises(ValueError, match=field):
        validate_final_holdout_access_claim_against_plan(altered, valid_plan)


def test_against_plan_refuses_an_internally_invalid_plan(claim, valid_plan):
    with pytest.raises(ValueError):
        validate_final_holdout_access_claim_against_plan(claim, dataclasses.replace(valid_plan, campaign_id="0" * 64))


def test_against_plan_catches_a_plan_field_outside_the_internal_plan_id_formula(claim, valid_plan):
    # `preregistration_content_hash` n'entre pas dans la préimage de `campaign_id` (D20.3/20.4) : seule la liaison le voit.
    forged_plan = dataclasses.replace(valid_plan, preregistration_content_hash="0" * 64)
    with pytest.raises(ValueError, match="preregistration_content_hash"):
        validate_final_holdout_access_claim_against_plan(claim, forged_plan)


# -- Canonicalisation (Décision 20.3) --------------------------------------------------------


def test_canonicalisation_matches_plan_v2_and_slice_b():
    import gate_v_campaign_plan_v2 as plan_module
    import gate_v_final_holdout_claim as claim_module
    import gate_v_preregistration as prereg_module

    sample = {"z": "é", "a": [3, 2.5, {"b": None, "c": True}]}
    assert claim_module._canonical_json(sample) == plan_module._canonical_json(sample)
    assert claim_module._canonical_json(sample) == prereg_module._canonical_json(sample)
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            claim_module._canonical_json({"a": bad})


# -- Architecture : pureté, frontières, aucune autorisation ----------------------------------

def _module_tree(name):
    return ast.parse((_ROOT / f"{name}.py").read_text(encoding="utf-8"))


def test_e1_imports_only_the_standard_library_subset_and_the_plan_v2_module():
    imported = set()
    for node in ast.walk(_module_tree("gate_v_final_holdout_claim")):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            imported.add((node.module or "").split(".")[0])
    # Égalité exacte volontaire : toute nouvelle dépendance d'un cœur PUR doit être un choix explicite.
    assert imported == {"__future__", "hashlib", "json", "re", "dataclasses", "datetime", "gate_v_campaign_plan_v2"}


def test_e1_contains_no_io_clock_engine_acquisition_or_authorization_call():
    source = (_ROOT / "gate_v_final_holdout_claim.py").read_text(encoding="utf-8")
    tokens = (
        "run_oos_validation", "run_backtest", "open(", "read_text", "write_text", "datetime.now", "utcnow",
        "os.open", "O_EXCL", "save_exclusive", "save_atomic", "unlink", "rename", "replace(",
        "HoldoutAccessEvent", "final_holdout_access_claim.json", "def acquire", "def load_final_holdout",
        "GATE V = PASS", "Champion",
    )
    assert [token for token in tokens if token in source] == []


def test_e1_defines_only_the_agreed_public_surface():
    import gate_v_final_holdout_claim as module

    public = {name for name in dir(module) if not name.startswith("_") and getattr(
        getattr(module, name), "__module__", None) == module.__name__}
    assert public == {
        "FinalHoldoutAccessClaim", "build_final_holdout_access_claim",
        "compute_final_holdout_access_claim_id", "compute_final_holdout_access_claim_content_hash",
        "validate_final_holdout_access_claim_structure", "validate_final_holdout_access_claim_against_plan",
        "final_holdout_access_claim_to_record", "final_holdout_access_claim_from_record",
    }


_MODULES_THAT_MUST_IGNORE_THE_CLAIM = (
    "gate_v_campaign", "gate_v_campaign_plan_v2", "gate_v_campaign_manifest_v2", "gate_v_campaign_dispatch",
    "gate_v_evidence_completeness_v2", "gate_v_preregistration", "gate_v_validation_policy",
    "atomic_json_store", "validation_oos", "validation_run", "dataset_split", "research_run",
)


@pytest.mark.parametrize("module_name", _MODULES_THAT_MUST_IGNORE_THE_CLAIM)
def test_historical_and_sibling_modules_never_reference_the_claim_core(module_name):
    """Le Manifest V2, le Plan V2, V1, la discrimination et le moteur d'OOS ignorent le Claim (ADR 21.10).
    Le futur module d'acquisition E2 est le seul consommateur prévu et n'est volontairement pas listé ici."""
    assert "gate_v_final_holdout_claim" not in (_ROOT / f"{module_name}.py").read_text(encoding="utf-8")


def test_building_a_claim_creates_no_file_anywhere(valid_plan, tmp_path):
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    claim = build_final_holdout_access_claim(valid_plan, created_at=_CREATED)
    final_holdout_access_claim_from_record(final_holdout_access_claim_to_record(claim))
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before
    assert not list(tmp_path.rglob("final_holdout_access_claim*"))
