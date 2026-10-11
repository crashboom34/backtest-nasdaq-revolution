"""
tests/test_gate_v_final_holdout_claim_acquisition.py — AF-V-07 Slice E2 : acquisition exclusive du Claim.

Contrat normatif : ADR 0025 Décisions 9, 10, 11 (acquisition, course, crash), 21.7 (précondition D5) et 22
(22.5 frontière de confiance, 22.6 séquence, 22.7 état du fichier, 22.9-22.11). Aucune donnée de marché, aucun
`run_oos_validation`, aucun FINAL_HOLDOUT : campagnes SYNTHÉTIQUES dans des dossiers temporaires, crashs durs
simulés dans des processus enfants (`os._exit`) sur ces seuls dossiers.

Catégories : [U] unitaire · [FI] défaillance simulée (injection dans `atomic_json_store.os`) ·
[MP] processus réels · [Q] qualification du vrai filesystem = NON démontrable ici (condition ultérieure).
"""

from __future__ import annotations

import ast
import builtins
import dataclasses
import datetime
import errno
import hashlib
import inspect
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_claim_world as cw
import _store_fault_injection as faults
import atomic_json_store as store
import gate_v_campaign_manifest_v2 as m2
import gate_v_final_holdout_claim as e1
import gate_v_final_holdout_claim_acquisition as acq
from gate_v_campaign_plan_v2 import GateVCampaignPlanV2
from gate_v_preregistration import build_gate_v_preregistration

CREATED = "2026-10-11T10:00:00+00:00"
_FIELDS = tuple(f.name for f in dataclasses.fields(e1.FinalHoldoutAccessClaim))
_LINK_FIELDS = (
    "campaign_id", "preregistration_id", "preregistration_content_hash", "campaign_protocol_fingerprint",
    "research_run_id", "research_run_content_hash", "dataset_snapshot_id", "split_plan_id",
    "split_plan_fingerprint", "assessment_semantics_version",
)
_WORKER = Path(__file__).with_name("_gate_v_final_holdout_claim_worker.py")


# ============================================================================================
# Fixtures et aides
# ============================================================================================


@pytest.fixture(scope="module")
def base_world(tmp_path_factory):
    return cw.build_world(tmp_path_factory.mktemp("e2") / "base")


@pytest.fixture(scope="module")
def incomplete_base(tmp_path_factory):
    return cw.build_world(tmp_path_factory.mktemp("e2i") / "base", attach_all_parameter_stability=False)


@pytest.fixture
def world(base_world, tmp_path):
    return base_world.clone_into(tmp_path / "w")


@pytest.fixture
def incomplete(incomplete_base, tmp_path):
    return incomplete_base.clone_into(tmp_path / "w")


def acquire(world, *, campaign_dir=None, created_at=CREATED, **overrides):
    kwargs = {**world.sources(), **overrides}
    target = world.campaign_dir if campaign_dir is None else campaign_dir
    return acq.acquire_final_holdout_access_claim(target, created_at=created_at, **kwargs)


def state(world):
    return cw.snapshot(world.root)


def assert_refused(world, error=ValueError, **kwargs):
    """Refus AVANT toute création : exception typée, aucun Claim, AUCUN octet modifié, jamais PostAcquisition."""
    before = state(world)
    with pytest.raises(error) as raised:
        acquire(world, **kwargs)
    assert not isinstance(raised.value, (acq.FinalHoldoutClaimPostAcquisitionError, acq.FinalHoldoutClaimAlreadyConsumedError))
    assert not world.claim_path.exists()
    assert state(world) == before
    return raised.value


def spy_d5(monkeypatch):
    calls, real = [], acq.assert_gate_v_pre_holdout_evidence_complete

    def wrapper(plan, campaign_dir):
        calls.append(campaign_dir)
        return real(plan, campaign_dir)

    monkeypatch.setattr(acq, "assert_gate_v_pre_holdout_evidence_complete", wrapper)
    return calls


def wrap_save(monkeypatch, after=None):
    calls, real = [], acq.save_exclusive

    def wrapper(path, data, kind, *, durable=False):
        calls.append({"path": Path(path), "kind": kind, "durable": durable, "data": data})
        result = real(path, data, kind, durable=durable)
        if after is not None:
            after(Path(path))
        return result

    monkeypatch.setattr(acq, "save_exclusive", wrapper)
    return calls


def guard_opens(monkeypatch, forbidden=None):
    """Enregistre TOUT chemin ouvert via `io.open`/`open` (donc `Path.read_*`) ; interdit la lecture de `forbidden`."""
    opened, real = [], io.open
    forbidden_norm = None if forbidden is None else os.path.normcase(os.path.abspath(forbidden))

    def guarded(file, *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)):
            name = os.path.normcase(os.path.abspath(os.fsdecode(file)))
            opened.append(name)
            if name == forbidden_norm:
                raise AssertionError(f"lecture interdite de {name}")
        return real(file, *args, **kwargs)

    monkeypatch.setattr(io, "open", guarded)
    monkeypatch.setattr(builtins, "open", guarded)
    return opened


def digest(record):
    text = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reseal(record):
    """Recalcule HONNÊTEMENT les deux hashes d'un record modifié (attaquant auto-cohérent)."""
    pre = {name: record[name] for name in (*_LINK_FIELDS, "claim_semantics_version")}
    claim_id = digest(pre)
    return {**record, "claim_id": claim_id, "claim_content_hash": digest({**pre, "claim_id": claim_id})}


def valid_record(plan, created_at=CREATED):
    return e1.final_holdout_access_claim_to_record(e1.build_final_holdout_access_claim(plan, created_at=created_at))


def as_text(record):
    return json.dumps(record, indent=2, ensure_ascii=False) + "\n"


def bad_claim_contents(world, other_plan):
    record = valid_record(world.plan)
    text = as_text(record)
    raw = text.encode("utf-8")
    return {
        "empty": b"",
        "truncated": raw[:40],
        "garbage": b"\x00\xff\xfe not json",
        "json_array": b"[]",
        "json_null": b"null",
        "bom": b"\xef\xbb\xbf" + raw,
        "invalid_utf8": raw[:60] + b"\xff\xfe" + raw[60:],
        "nan_constant": text.replace(f'"{CREATED}"', "NaN").encode("utf-8"),
        "duplicate_key": text.replace('  "created_at"', f'  "created_at": "{CREATED}",\n  "created_at"', 1).encode("utf-8"),
        "trailing_garbage": (text + "garbage").encode("utf-8"),
        "extra_key": as_text({**record, "extra": "x"}).encode("utf-8"),
        "missing_key": as_text({k: v for k, v in record.items() if k != "claim_id"}).encode("utf-8"),
        "non_str_value": as_text({**record, "claim_id": 7}).encode("utf-8"),
        "forged_hash": as_text({**record, "claim_content_hash": "0" * 64}).encode("utf-8"),
        "self_coherent_foreign_link": as_text(reseal({**record, "research_run_id": "run_foreign"})).encode("utf-8"),
        "claim_of_another_campaign": as_text(valid_record(other_plan)).encode("utf-8"),
    }


# ============================================================================================
# Surface publique [U]
# ============================================================================================


def test_constants_and_exception_hierarchy():
    assert acq.FINAL_HOLDOUT_ACCESS_CLAIM_FILE == "final_holdout_access_claim.json"
    assert issubclass(acq.FinalHoldoutClaimAlreadyConsumedError, FileExistsError)
    assert issubclass(acq.FinalHoldoutClaimPostAcquisitionError, Exception)
    assert not issubclass(acq.FinalHoldoutClaimPostAcquisitionError, OSError)
    assert not issubclass(acq.FinalHoldoutClaimPostAcquisitionError, acq.FinalHoldoutClaimAlreadyConsumedError)
    assert not issubclass(acq.FinalHoldoutClaimAlreadyConsumedError, acq.FinalHoldoutClaimPostAcquisitionError)


def test_signatures_are_exactly_those_of_decision_22():
    parameters = inspect.signature(acq.acquire_final_holdout_access_claim).parameters
    assert list(parameters) == [
        "campaign_dir", "preregistration_path", "research_run_path", "split_plan_path", "policy_path",
        "repo_dir", "created_at",
    ]
    assert parameters["campaign_dir"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for name, p in parameters.items() if name != "campaign_dir")
    assert parameters["repo_dir"].default is None and parameters["created_at"].default is None
    for name in ("preregistration_path", "research_run_path", "split_plan_path", "policy_path"):
        assert parameters[name].default is inspect.Parameter.empty
    # AUCUN objet métier source n'est accepté (22.5) : seulement des chemins
    assert not {"plan", "preregistration", "research_run", "split_plan", "policy", "claim", "manifest"} & set(parameters)
    assert list(inspect.signature(acq.load_final_holdout_access_claim).parameters) == ["plan", "campaign_dir"]


def test_public_surface_is_exactly_the_agreed_one():
    public = {name for name in dir(acq) if not name.startswith("_") and getattr(
        getattr(acq, name), "__module__", None) == acq.__name__}
    assert public == {
        "FinalHoldoutClaimAlreadyConsumedError", "FinalHoldoutClaimPostAcquisitionError",
        "load_final_holdout_access_claim", "acquire_final_holdout_access_claim",
    }


# ============================================================================================
# Cas nominal [U]
# ============================================================================================


def test_nominal_acquisition_creates_exactly_one_new_file_and_touches_nothing_else(world, monkeypatch):
    d5, saves = spy_d5(monkeypatch), wrap_save(monkeypatch)
    before = state(world)
    acquire(world)
    after = state(world)
    claim_relative = world.claim_path.relative_to(world.root).as_posix()
    assert set(after) - set(before) == {claim_relative}
    assert {key: value for key, value in after.items() if key != claim_relative} == before  # octet pour octet
    assert len(saves) == 1 and saves[0]["durable"] is True and saves[0]["path"] == world.claim_path
    assert isinstance(saves[0]["kind"], str) and saves[0]["kind"]
    assert len(d5) == 2  # D5 avant ET après l'acquisition


def test_the_returned_claim_is_the_strict_read_back_and_is_bound_to_the_plan(world):
    claim = acquire(world)
    assert type(claim) is e1.FinalHoldoutAccessClaim and claim.created_at == CREATED
    assert acq.load_final_holdout_access_claim(world.plan, world.campaign_dir) == claim
    e1.validate_final_holdout_access_claim_against_plan(claim, world.plan)
    record = json.loads(world.claim_path.read_text(encoding="utf-8"))
    assert tuple(record) == _FIELDS and record == e1.final_holdout_access_claim_to_record(claim)
    raw = world.claim_path.read_bytes()
    assert raw.decode("utf-8") == as_text(record) and b"\r" not in raw  # UTF-8, LF seul (mode durable binaire)


def test_acquisition_is_deterministic_apart_from_created_at(base_world, tmp_path):
    first = base_world.clone_into(tmp_path / "a")
    second = base_world.clone_into(tmp_path / "b")
    assert acquire(first).claim_id == acquire(second).claim_id
    assert first.claim_path.read_bytes() == second.claim_path.read_bytes()
    third = base_world.clone_into(tmp_path / "c")
    other = acquire(third, created_at="2027-01-02T03:04:05Z")
    assert other.claim_id == acquire(base_world.clone_into(tmp_path / "d")).claim_id  # created_at hors hash
    assert other.created_at == "2027-01-02T03:04:05Z"


def test_string_paths_are_accepted_like_path_objects(world):
    claim = acq.acquire_final_holdout_access_claim(
        str(world.campaign_dir), preregistration_path=str(world.preregistration_path),
        research_run_path=str(world.research_run_path), split_plan_path=str(world.split_plan_path),
        policy_path=str(world.policy_path), repo_dir=str(world.repo_dir), created_at=CREATED)
    assert claim.created_at == CREATED and world.claim_path.is_file()


def test_repo_dir_defaults_to_the_policy_parent_when_omitted(world):
    sources = world.sources()
    sources.pop("repo_dir")
    claim = acq.acquire_final_holdout_access_claim(world.campaign_dir, created_at=CREATED, **sources)
    assert claim.created_at == CREATED


@pytest.mark.parametrize("fraction", ("123456", "000000"))
def test_default_created_at_reads_the_utc_clock_exactly_once(world, monkeypatch, fraction):
    calls = []
    moment = datetime.datetime(2026, 10, 11, 12, 0, 0, int(fraction), tzinfo=datetime.timezone.utc)

    class _FrozenDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            calls.append(tz)
            return moment.astimezone(tz) if tz is not None else moment

    monkeypatch.setattr(acq, "datetime", _FrozenDatetime)
    claim = acq.acquire_final_holdout_access_claim(world.campaign_dir, **world.sources())
    assert calls == [datetime.timezone.utc]
    assert claim.created_at == moment.isoformat()  # aware, UTC, conforme à e1


def test_a_supplied_created_at_never_reads_the_clock(world, monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("l'horloge ne doit pas être lue quand created_at est fourni")

    class _NoClock(datetime.datetime):
        now = classmethod(forbidden)

    monkeypatch.setattr(acq, "datetime", _NoClock)
    assert acquire(world).created_at == CREATED


def test_after_acquisition_the_campaign_is_still_a_valid_v2_campaign(world):
    from gate_v_campaign_dispatch import classify_gate_v_campaign_dir

    before_manifest = (world.campaign_dir / "manifest.json").read_bytes()
    before_loaded = m2.load_gate_v_campaign_manifest_v2(world.plan, world.campaign_dir)
    acquire(world)
    assert classify_gate_v_campaign_dir(world.campaign_dir) == "v2"
    assert (world.campaign_dir / "manifest.json").read_bytes() == before_manifest
    assert m2.assert_gate_v_pre_holdout_evidence_complete(world.plan, world.campaign_dir) == before_loaded
    assert before_loaded.final_holdout_claim_id is None  # le miroir d'audit relève d'E3


def test_no_file_outside_the_world_is_opened_and_no_market_data_is_read(world, monkeypatch):
    opened = guard_opens(monkeypatch)
    acquire(world)
    root = os.path.normcase(os.path.abspath(world.root))
    assert opened and all(path.startswith(root) for path in opened), [p for p in opened if not p.startswith(root)]
    assert not [path for path in opened if path.endswith((".csv", ".parquet", ".feather"))]


# ============================================================================================
# Frontière de confiance des sources : refus AVANT création (22.5) [U]
# ============================================================================================


def _rewrite_json(path, edit):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    edit(data)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _flip(text):
    return text[:-1] + ("0" if text[-1] != "0" else "1")


def _unlink(path):
    Path(path).unlink()


def test_a_preregistration_that_is_not_persisted_is_refused(world):
    _unlink(world.preregistration_path)
    assert_refused(world)


def test_a_preregistration_outside_the_canonical_location_is_refused_even_if_identical(world):
    copy = world.root / "elsewhere" / world.preregistration_path.name
    copy.parent.mkdir()
    copy.write_bytes(world.preregistration_path.read_bytes())
    assert_refused(world, preregistration_path=copy)  # l'original canonique existe toujours : ce n'est pas LE fichier


def test_a_preregistration_not_named_by_its_scope_key_is_refused(world):
    renamed = world.preregistration_path.with_name("renamed.json")
    renamed.write_bytes(world.preregistration_path.read_bytes())
    assert_refused(world, preregistration_path=renamed)


def test_a_differently_named_hard_link_to_the_canonical_preregistration_is_refused(world):
    """`samefile` seul accepterait un alias : le nom du fichier doit AUSSI être exactement <scope_key>.json."""
    alias = world.preregistration_path.with_name("alias.json")
    try:
        os.link(world.preregistration_path, alias)
    except (OSError, NotImplementedError):
        pytest.skip("liens physiques indisponibles sur ce système de fichiers")
    assert_refused(world, preregistration_path=alias)


def test_a_tampered_persisted_preregistration_is_refused(world):
    _rewrite_json(world.preregistration_path, lambda d: d.update(research_run_content_hash=_flip(d["research_run_content_hash"])))
    assert_refused(world)


def test_a_different_self_consistent_preregistration_substituted_at_the_canonical_path_is_refused(world):
    """Même scope, autre protocole (budget 21) : cohérente en elle-même, mais ce n'est PAS celle qui épingle le plan."""
    alternative = build_gate_v_preregistration(
        research_run=world.research_run, split_plan=world.split, policy=world.policy, policy_path=world.policy_path,
        assessment_semantics_version="gate_v_assessment_v1", repo_dir=world.repo_dir, strategy_name=cw.STRATEGY,
        walk_forward_specification=world.plan.walk_forward_specification, readiness_spec=None,
        budget_per_fold=21, **cw.PROTOCOL)
    assert alternative.scope_key == world.preregistration.scope_key
    assert alternative.preregistration_id != world.preregistration.preregistration_id
    world.preregistration_path.write_text(json.dumps(dataclasses.asdict(alternative), indent=2), encoding="utf-8")
    assert_refused(world)


@pytest.mark.parametrize("name", ("research_run_path", "split_plan_path", "policy_path"))
def test_a_missing_persisted_source_is_refused(world, name):
    _unlink(world.sources()[name])
    assert_refused(world)


@pytest.mark.parametrize("name", ("research_run_path", "split_plan_path", "policy_path"))
def test_an_unparseable_persisted_source_is_refused(world, name):
    world.sources()[name].write_text("{", encoding="utf-8")
    assert_refused(world)


def test_a_changed_research_run_is_refused_by_its_pinned_hash(world):
    _rewrite_json(world.research_run_path, lambda d: d.update(experiment_id="exp_changed"))
    assert_refused(world)


def test_a_changed_split_plan_is_refused_by_its_pinned_fingerprint(world):
    _rewrite_json(world.split_plan_path, lambda d: d["final_holdout"].update(end="2026-01-01T00:00:00+00:00"))
    assert_refused(world)


def test_a_split_plan_failing_strict_validation_is_refused(world):
    _rewrite_json(world.split_plan_path, lambda d: d["train"].update(start="2022-01-01T00:00:00+00:00"))  # chevauche
    assert_refused(world)


def test_a_policy_whose_content_diverges_from_the_pinned_hash_is_refused(world):
    def edit(data):
        data["scientific_criteria"]["oos"][0]["threshold"] = 99.0

    _rewrite_json(world.policy_path, edit)
    assert_refused(world)


def test_a_repository_that_does_not_hold_the_pinned_policy_commit_is_refused(world):
    other = world.root / "other_repo"
    (other / "validation_policies").mkdir(parents=True)
    cw.run_git(["init"], other)
    copy = other / "validation_policies" / world.policy_path.name
    copy.write_bytes(world.policy_path.read_bytes())
    error = assert_refused(world, repo_dir=other, policy_path=copy)
    assert isinstance(error, ValueError)  # GitProvenanceError est une ValueError


def test_a_missing_or_tampered_plan_is_refused(base_world, tmp_path):
    tampered = base_world.clone_into(tmp_path / "tampered")
    _rewrite_json(tampered.campaign_dir / "plan.json", lambda d: d.update(budget_per_fold=d["budget_per_fold"] + 1))
    assert_refused(tampered)
    missing = base_world.clone_into(tmp_path / "missing")
    _unlink(missing.campaign_dir / "plan.json")
    assert_refused(missing)


def test_a_campaign_directory_not_named_by_the_campaign_id_is_refused(world):
    renamed = world.campaign_dir.with_name("not_the_campaign_id")
    world.campaign_dir.rename(renamed)
    before = state(world)
    with pytest.raises(ValueError):
        acquire(world, campaign_dir=renamed)
    assert state(world) == before and not (renamed / cw.CLAIM_FILE).exists()


def test_a_campaign_outside_the_canonical_layout_is_refused(world):
    moved = world.gate_v_dir / "runs" / world.plan.campaign_id
    moved.parent.mkdir()
    world.campaign_dir.rename(moved)
    before = state(world)
    with pytest.raises(ValueError):
        acquire(world, campaign_dir=moved)
    assert state(world) == before and not (moved / cw.CLAIM_FILE).exists()


@pytest.mark.parametrize("bad", (None, "", "   ", 7, object()))
def test_invalid_path_arguments_are_refused(world, bad):
    before = state(world)
    for name in ("preregistration_path", "research_run_path", "split_plan_path", "policy_path"):
        with pytest.raises(ValueError):
            acquire(world, **{name: bad})
    with pytest.raises(ValueError):  # appel direct : l'aide `acquire` lirait None comme « valeur par défaut »
        acq.acquire_final_holdout_access_claim(bad, created_at=CREATED, **world.sources())
    assert state(world) == before and not world.claim_path.exists()


def test_an_object_that_merely_stringifies_to_a_real_path_is_not_a_path(world):
    class _Stringifies:
        def __init__(self, path):
            self._path = str(path)

        def __str__(self):
            return self._path

    for name in ("preregistration_path", "research_run_path", "split_plan_path", "policy_path"):
        with pytest.raises(ValueError):
            acquire(world, **{name: _Stringifies(world.sources()[name])})
    with pytest.raises(ValueError):
        acq.acquire_final_holdout_access_claim(_Stringifies(world.campaign_dir), created_at=CREATED, **world.sources())
    assert not world.claim_path.exists()


def test_in_memory_source_objects_are_never_accepted_in_place_of_paths(world):
    for name, obj in (("preregistration_path", world.preregistration), ("research_run_path", world.research_run),
                      ("split_plan_path", world.split), ("policy_path", world.policy)):
        with pytest.raises(ValueError):
            acquire(world, **{name: obj})
    assert not world.claim_path.exists()


@pytest.mark.parametrize("bad", ("", "not a date", "2026-10-11T10:00:00", "2026-10-11", 20261011, True))
def test_an_invalid_created_at_is_refused_before_any_creation(world, bad):
    assert_refused(world, created_at=bad)


# ============================================================================================
# Préconditions D5 : refus AVANT création [U]
# ============================================================================================


def _update_manifest(world, command):
    revision = m2.load_gate_v_campaign_manifest_v2(world.plan, world.campaign_dir).manifest_revision
    return m2.update_gate_v_campaign_manifest_v2(world.plan, world.campaign_dir, command, expected_revision=revision)


def test_incomplete_evidence_is_refused(incomplete):
    assert_refused(incomplete)


def test_a_technical_failure_sentinel_is_refused_even_when_unreadable(world):
    (world.campaign_dir / cw.SENTINEL_FILE).write_bytes(b"")
    assert_refused(world)


def test_a_residual_manifest_update_lock_is_refused(world):
    (world.campaign_dir / cw.LOCK_FILE).write_bytes(b"")
    assert_refused(world)


def test_a_recorded_technical_failure_is_refused(world):
    _update_manifest(world, m2.MarkTechnicalFailure("boom"))
    assert_refused(world)


def test_a_running_campaign_is_refused(world):
    _update_manifest(world, m2.SetRunning(True))
    assert_refused(world)


def test_reserved_final_holdout_fields_already_set_are_refused(world):
    _rewrite_json(world.campaign_dir / "manifest.json", lambda d: d.update(final_holdout_claim_id="claim_added_by_hand"))
    assert_refused(world)


def test_a_missing_referenced_proof_is_refused(world):
    proof = next((world.campaign_dir / "validations").glob("*parameter_stability*")) / "validation_run.json"
    proof.unlink()
    assert_refused(world)


def test_a_missing_manifest_is_refused(world):
    _unlink(world.campaign_dir / "manifest.json")
    assert_refused(world)


def test_a_refusal_before_creation_consumes_nothing_and_a_later_attempt_succeeds(world):
    lock = world.campaign_dir / cw.LOCK_FILE
    lock.write_bytes(b"")
    assert_refused(world)
    lock.unlink()
    assert acquire(world).created_at == CREATED


# ============================================================================================
# Claim déjà présent : consommé pour toujours, jamais inspecté [U]
# ============================================================================================


def test_a_second_acquisition_is_refused_and_leaves_the_first_claim_byte_identical(world):
    acquire(world)
    first = world.claim_path.read_bytes()
    with pytest.raises(acq.FinalHoldoutClaimAlreadyConsumedError) as raised:
        acquire(world, created_at="2027-01-01T00:00:00Z")
    assert isinstance(raised.value, FileExistsError) and world.claim_path.read_bytes() == first


@pytest.mark.parametrize("existing", ("empty", "truncated", "garbage", "forged_hash", "claim_of_another_campaign"))
def test_any_existing_claim_content_means_consumed_without_ever_reading_it(world, incomplete_base, monkeypatch, existing):
    contents = bad_claim_contents(world, incomplete_base.plan)[existing]
    world.claim_path.write_bytes(contents)
    before = state(world)  # AVANT la garde : l'instantané lit lui-même le Claim
    d5, saves = spy_d5(monkeypatch), wrap_save(monkeypatch)
    guard_opens(monkeypatch, forbidden=world.claim_path)  # toute lecture du Claim existant lèverait
    with pytest.raises(acq.FinalHoldoutClaimAlreadyConsumedError):
        acquire(world)
    monkeypatch.undo()
    assert world.claim_path.read_bytes() == contents and state(world) == before
    assert len(saves) == 1 and len(d5) == 1  # aucune seconde tentative, aucune revérification post-acquisition


def test_no_existence_check_or_stat_touches_the_claim_path_before_the_exclusive_creation(world, monkeypatch):
    """Décision 11 / 22.6 étape 7 : AUCUN `exists()`/`stat()` préalable — seul `O_EXCL` fait autorité (sinon : TOCTOU)."""
    import pathlib

    claim_norm = os.path.normcase(os.path.abspath(world.claim_path))
    creation_started, touched = [], []

    def normalised(value):
        try:
            return os.path.normcase(os.path.abspath(os.fspath(value)))
        except TypeError:
            return None

    def watch(owner, name):
        real = getattr(owner, name)

        def wrapper(*args, **kwargs):
            if args and normalised(args[0]) == claim_norm and not creation_started:
                touched.append(name)
            return real(*args, **kwargs)

        monkeypatch.setattr(owner, name, wrapper)

    for name in ("stat", "lstat", "scandir", "listdir"):
        watch(os, name)
    for name in ("exists", "isfile", "lexists", "isdir"):
        watch(os.path, name)
    for name in ("exists", "is_file", "stat", "lstat", "is_dir", "iterdir"):
        watch(pathlib.Path, name)
    real_save = acq.save_exclusive

    def gate(path, data, kind, *, durable=False):
        creation_started.append(True)
        return real_save(path, data, kind, durable=durable)

    monkeypatch.setattr(acq, "save_exclusive", gate)
    acquire(world)
    assert creation_started and touched == []


def test_the_source_never_probes_the_claim_path_before_creating_it():
    import re

    probes = re.findall(
        r"claim_path\s*\.\s*(?:exists|is_file|is_dir|stat|lstat)\b"
        r"|os\.path\.(?:exists|isfile|lexists|isdir)\(\s*claim_path"
        r"|os\.(?:stat|lstat)\(\s*claim_path", _source())
    assert probes == []


def test_a_valid_claim_of_this_very_campaign_is_equally_consumed(world):
    world.claim_path.write_text(as_text(valid_record(world.plan)), encoding="utf-8")
    before = world.claim_path.read_bytes()
    with pytest.raises(acq.FinalHoldoutClaimAlreadyConsumedError):
        acquire(world)
    assert world.claim_path.read_bytes() == before


# ============================================================================================
# Échecs APRÈS création : le Claim reste consommé, aucun accès marché [U / FI]
# ============================================================================================


def _touch(name):
    return lambda claim_path: (claim_path.parent / name).write_bytes(b"x")


def _after_running(world):
    return lambda _path: _update_manifest(world, m2.SetRunning(True))


def _after_aba(world):
    def mutate(_path):
        _update_manifest(world, m2.SetRunning(True))
        _update_manifest(world, m2.SetRunning(False))
    return mutate


def _rewrite_claim_bytes(make_bytes):
    return lambda claim_path: claim_path.write_bytes(make_bytes(claim_path.read_bytes()))


_POST_CASES = {
    "sentinel_appears": lambda w, o: _touch(cw.SENTINEL_FILE),
    "update_lock_appears": lambda w, o: _touch(cw.LOCK_FILE),
    "manifest_becomes_running": lambda w, o: _after_running(w),
    "manifest_aba_revision_changed": lambda w, o: _after_aba(w),
    "claim_replaced_by_other_valid_created_at": lambda w, o: _rewrite_claim_bytes(
        lambda raw: as_text(valid_record(w.plan, "2030-01-01T00:00:00+00:00")).encode("utf-8")),
    "claim_truncated_to_empty": lambda w, o: _rewrite_claim_bytes(lambda raw: b""),
    "claim_with_duplicate_key": lambda w, o: _rewrite_claim_bytes(
        lambda raw: raw.decode("utf-8").replace('  "created_at"', f'  "created_at": "{CREATED}",\n  "created_at"', 1).encode("utf-8")),
    "claim_self_coherent_foreign_link": lambda w, o: _rewrite_claim_bytes(
        lambda raw: as_text(reseal({**valid_record(w.plan), "research_run_id": "run_foreign"})).encode("utf-8")),
    "claim_of_another_campaign": lambda w, o: _rewrite_claim_bytes(
        lambda raw: as_text(valid_record(o.plan)).encode("utf-8")),
    "claim_with_extra_key": lambda w, o: _rewrite_claim_bytes(
        lambda raw: as_text({**valid_record(w.plan), "extra": "x"}).encode("utf-8")),
}


_POST_CASES_REFUSED_BY_D5_ON_RETRY = {"sentinel_appears", "update_lock_appears", "manifest_becomes_running"}


@pytest.mark.parametrize("case", sorted(_POST_CASES))
def test_any_post_creation_inconsistency_is_a_post_acquisition_error_and_the_claim_stays_consumed(
    world, incomplete_base, monkeypatch, case,
):
    wrap_save(monkeypatch, after=_POST_CASES[case](world, incomplete_base))
    with pytest.raises(acq.FinalHoldoutClaimPostAcquisitionError) as raised:
        acquire(world)
    assert raised.value.__cause__ is not None
    assert world.claim_path.exists()  # JAMAIS supprimé
    monkeypatch.undo()
    left = world.claim_path.read_bytes()
    # Aucune nouvelle création n'est possible : refusé par D5 AVANT création (sentinelle, verrou, campagne en cours)
    # ou par l'exclusivité (AlreadyConsumed) ; dans tous les cas le Claim existant n'est pas touché.
    expected = ValueError if case in _POST_CASES_REFUSED_BY_D5_ON_RETRY else acq.FinalHoldoutClaimAlreadyConsumedError
    with pytest.raises(expected):
        acquire(world)
    assert world.claim_path.read_bytes() == left


def test_an_unexpected_exception_in_the_second_d5_is_a_post_acquisition_error(world, monkeypatch):
    calls, real = [], acq.assert_gate_v_pre_holdout_evidence_complete

    def flaky(plan, campaign_dir):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("lecture transitoire bloquée")
        return real(plan, campaign_dir)

    monkeypatch.setattr(acq, "assert_gate_v_pre_holdout_evidence_complete", flaky)
    with pytest.raises(acq.FinalHoldoutClaimPostAcquisitionError) as raised:
        acquire(world)
    assert isinstance(raised.value.__cause__, RuntimeError) and world.claim_path.exists()


def test_a_post_acquisition_error_is_never_a_file_exists_error(world, monkeypatch):
    wrap_save(monkeypatch, after=_touch(cw.SENTINEL_FILE))
    with pytest.raises(acq.FinalHoldoutClaimPostAcquisitionError) as raised:
        acquire(world)
    assert not isinstance(raised.value, FileExistsError)


_STORE_ERRORS = (
    OSError(errno.ENOSPC, "disque plein simulé"),
    PermissionError(errno.EACCES, "permission refusée simulée"),
    OSError(errno.EIO, "erreur d'E/S simulée"),
    FileExistsError(errno.EEXIST, "FileExistsError tardive simulée"),
)
# (étape, erreur) : 4 étapes x 4 erreurs, plus le fsync de répertoire POSIX (EIO simulée par l'outil, une seule fois)
_STORE_FAILURES = [(stage, error) for stage in ("write", "flush", "fsync", "close") for error in _STORE_ERRORS]
_STORE_FAILURES.append(("dirsync_after", None))


@pytest.mark.parametrize(
    "stage, error", _STORE_FAILURES,
    ids=lambda v: v if isinstance(v, str) else (type(v).__name__ + str(v.errno) if v is not None else "EIO"),
)
def test_durable_write_failures_after_creation_consume_the_claim_without_confusing_it_with_o_excl(
    world, monkeypatch, stage, error,
):
    if stage == "dirsync_after":
        faults.install_store_faults(monkeypatch, store, dir_sync=True, dir_sync_fail_on_call=2)
    else:
        faults.install_store_faults(monkeypatch, store, fail_at=stage, error=error)
    with pytest.raises(acq.FinalHoldoutClaimPostAcquisitionError) as raised:
        acquire(world)
    assert not isinstance(raised.value, acq.FinalHoldoutClaimAlreadyConsumedError)
    assert isinstance(raised.value.__cause__, store.ExclusiveCreationIncompleteError)
    assert world.claim_path.exists()
    if stage == "write":
        assert world.claim_path.read_bytes() == b""  # créé, jamais écrit : consommé quand même
        with pytest.raises(ValueError):
            acq.load_final_holdout_access_claim(world.plan, world.campaign_dir)
    with pytest.raises(acq.FinalHoldoutClaimAlreadyConsumedError):
        acquire(world)


def test_an_fsync_failure_leaves_a_complete_claim_that_is_nevertheless_a_failure(world, monkeypatch):
    faults.install_store_faults(monkeypatch, store, fail_at="fsync", error=OSError(errno.EIO, "fsync simulé"))
    with pytest.raises(acq.FinalHoldoutClaimPostAcquisitionError):
        acquire(world)
    monkeypatch.undo()
    # Le contenu est complet et valide, mais l'acquisition n'a PAS été confirmée : aucun accès marché n'en découle.
    assert acq.load_final_holdout_access_claim(world.plan, world.campaign_dir).created_at == CREATED


def test_a_permission_error_at_the_exclusive_open_creates_nothing_and_is_not_a_post_acquisition_error(world, monkeypatch):
    faults.install_store_faults(monkeypatch, store, open_error=PermissionError(errno.EACCES, "refusé simulé"))
    before = state(world)
    with pytest.raises(PermissionError) as raised:
        acquire(world)
    assert not isinstance(raised.value, (acq.FinalHoldoutClaimPostAcquisitionError, acq.FinalHoldoutClaimAlreadyConsumedError))
    assert not world.claim_path.exists() and state(world) == before
    monkeypatch.undo()
    assert acquire(world).created_at == CREATED  # rien n'avait été consommé


def test_a_file_exists_error_raised_before_the_exclusive_open_is_not_reported_as_consumed(world, monkeypatch):
    """`FinalHoldoutClaimAlreadyConsumedError` = EXCLUSIVEMENT le refus d'`O_EXCL` du chemin du Claim. Une
    `FileExistsError` du `mkdir` du parent (rien n'a été tenté sur le Claim) n'est pas « consommé »."""
    blocker = world.root / "blocker"
    blocker.write_bytes(b"x")
    real = acq.save_exclusive

    def misdirected(path, data, kind, *, durable=False):  # simule un parent qui n'est plus un répertoire
        return real(blocker / "claim.json", data, kind, durable=durable)

    monkeypatch.setattr(acq, "save_exclusive", misdirected)
    before = state(world)
    with pytest.raises(OSError) as raised:
        acquire(world)
    assert not isinstance(raised.value, (
        acq.FinalHoldoutClaimAlreadyConsumedError, acq.FinalHoldoutClaimPostAcquisitionError, FileExistsError))
    assert isinstance(raised.value, NotADirectoryError)
    monkeypatch.undo()
    assert not world.claim_path.exists() and state(world) == before


def test_an_interruption_after_creation_propagates_untouched_and_the_claim_stays_consumed(world, monkeypatch):
    """Une BaseException (Ctrl+C) n'est jamais déguisée en « échec avant création » : elle se propage telle quelle,
    le Claim éventuellement créé reste en place, aucune valeur n'est retournée, aucun accès au marché ne suit."""
    def interrupt(_path):
        raise KeyboardInterrupt()

    wrap_save(monkeypatch, after=interrupt)
    with pytest.raises(KeyboardInterrupt) as raised:
        acquire(world)
    assert not isinstance(raised.value, (acq.FinalHoldoutClaimPostAcquisitionError, acq.FinalHoldoutClaimAlreadyConsumedError))
    assert world.claim_path.exists()
    monkeypatch.undo()
    with pytest.raises(acq.FinalHoldoutClaimAlreadyConsumedError):
        acquire(world)


def test_a_symlink_at_the_claim_path_is_never_an_acquired_or_valid_claim(world):
    """Windows : `O_CREAT|O_EXCL` SUIT un lien orphelin et crée sa cible (POSIX refuse : EEXIST). Dans les deux cas,
    aucune valeur de Claim n'est retournée : refusé (consommé) ou signalé après création (PostAcquisition)."""
    victim = world.root / "victim.json"
    try:
        world.claim_path.symlink_to(victim)
    except (OSError, NotImplementedError):
        pytest.skip("liens symboliques indisponibles (privilège Windows requis)")
    try:
        acquire(world)
        outcome = None
    except (acq.FinalHoldoutClaimPostAcquisitionError, acq.FinalHoldoutClaimAlreadyConsumedError) as error:
        outcome = type(error)
    assert outcome is not None, "un Claim a été RETOURNÉ à travers un lien symbolique"
    # La branche réellement prise dépend de la plateforme et doit être cohérente avec ce qui est sur le disque :
    # cible créée à travers le lien (Windows) = signalé après coup ; cible non créée (POSIX, EEXIST) = consommé.
    expected = acq.FinalHoldoutClaimPostAcquisitionError if victim.exists() else acq.FinalHoldoutClaimAlreadyConsumedError
    assert outcome is expected
    with pytest.raises(ValueError):  # le chargeur d'audit refuse le lien, qu'il soit orphelin ou non
        acq.load_final_holdout_access_claim(world.plan, world.campaign_dir)
    with pytest.raises(acq.FinalHoldoutClaimAlreadyConsumedError):  # le chemin est désormais consommé pour toujours
        acquire(world)


def test_a_directory_at_the_claim_path_creates_nothing_and_is_never_returned(world):
    """POSIX : O_EXCL -> EEXIST -> AlreadyConsumed. Windows : PermissionError brut. Dans les deux cas rien n'est créé
    et rien n'est retourné ; ce n'est jamais une erreur POST-acquisition (aucune création n'a eu lieu)."""
    world.claim_path.mkdir()
    before = state(world)
    with pytest.raises((acq.FinalHoldoutClaimAlreadyConsumedError, PermissionError)) as raised:
        acquire(world)
    assert not isinstance(raised.value, acq.FinalHoldoutClaimPostAcquisitionError)
    assert world.claim_path.is_dir() and state(world) == before
    with pytest.raises(ValueError):
        acq.load_final_holdout_access_claim(world.plan, world.campaign_dir)


def test_loader_refuses_a_symlink_even_when_it_points_to_a_valid_claim(world):
    real_file = world.root / "real_claim.json"
    real_file.write_text(as_text(valid_record(world.plan)), encoding="utf-8")
    try:
        world.claim_path.symlink_to(real_file)
    except (OSError, NotImplementedError):
        pytest.skip("liens symboliques indisponibles (privilège Windows requis)")
    with pytest.raises(ValueError, match="lien"):
        acq.load_final_holdout_access_claim(world.plan, world.campaign_dir)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO : POSIX uniquement")
def test_a_fifo_at_the_claim_path_is_refused_without_blocking(world):
    os.mkfifo(world.claim_path)
    with pytest.raises(ValueError):  # lstat avant lecture : un FIFO ne bloque jamais le chargeur
        acq.load_final_holdout_access_claim(world.plan, world.campaign_dir)
    with pytest.raises(acq.FinalHoldoutClaimAlreadyConsumedError):  # O_EXCL le refuse sans le lire
        acquire(world)


def test_a_failing_directory_probe_creates_nothing(world, monkeypatch):
    faults.install_store_faults(monkeypatch, store, dir_sync=True, dir_sync_fail_on_call=1)
    before = state(world)
    with pytest.raises(OSError) as raised:
        acquire(world)
    assert not isinstance(raised.value, (acq.FinalHoldoutClaimPostAcquisitionError, store.ExclusiveCreationIncompleteError))
    assert not world.claim_path.exists() and state(world) == before


def test_the_descriptor_is_released_so_the_consumed_claim_can_be_removed_by_a_human(world, monkeypatch):
    faults.install_store_faults(monkeypatch, store, fail_at="write", error=OSError(errno.ENOSPC, "plein simulé"))
    with pytest.raises(acq.FinalHoldoutClaimPostAcquisitionError):
        acquire(world)
    monkeypatch.undo()
    world.claim_path.unlink()  # sous Windows échouerait si un descripteur était resté ouvert (récupération humaine, 22.9)


# ============================================================================================
# Chargeur d'audit strict, lecture seule [U]
# ============================================================================================


def test_loader_raises_file_not_found_for_an_absent_claim_and_never_returns_none(world):
    before = state(world)
    with pytest.raises(FileNotFoundError):
        acq.load_final_holdout_access_claim(world.plan, world.campaign_dir)
    assert state(world) == before


def test_loader_returns_the_exact_claim_and_changes_nothing(world):
    claim = acquire(world)
    before = state(world)
    assert acq.load_final_holdout_access_claim(world.plan, str(world.campaign_dir)) == claim
    assert state(world) == before


_BAD_NAMES = (
    "empty", "truncated", "garbage", "json_array", "json_null", "bom", "invalid_utf8", "nan_constant",
    "duplicate_key", "trailing_garbage", "extra_key", "missing_key", "non_str_value", "forged_hash",
    "self_coherent_foreign_link", "claim_of_another_campaign",
)


@pytest.mark.parametrize("name", _BAD_NAMES)
def test_loader_refuses_every_malformed_inconsistent_or_foreign_claim_without_repairing_it(world, incomplete_base, name):
    contents = bad_claim_contents(world, incomplete_base.plan)[name]
    world.claim_path.write_bytes(contents)
    before = state(world)
    with pytest.raises(ValueError):
        acq.load_final_holdout_access_claim(world.plan, world.campaign_dir)
    assert world.claim_path.read_bytes() == contents and state(world) == before


def test_loader_never_reports_a_dangling_symlink_as_absent(world):
    """22.7 : un chemin PRÉSENT n'est jamais « absent » (O_EXCL, lui, le refuserait comme existant)."""
    try:
        world.claim_path.symlink_to(world.root / "does_not_exist.json")
    except (OSError, NotImplementedError):
        pytest.skip("liens symboliques indisponibles (privilège Windows requis)")
    with pytest.raises(ValueError) as raised:
        acq.load_final_holdout_access_claim(world.plan, world.campaign_dir)
    assert not isinstance(raised.value, FileNotFoundError)


def test_loader_turns_hostile_json_nesting_into_a_value_error(world):
    world.claim_path.write_bytes(b"[" * 200_000 + b"]" * 200_000)
    with pytest.raises(ValueError):  # jamais un RecursionError : le contrat du chargeur est ValueError
        acq.load_final_holdout_access_claim(world.plan, world.campaign_dir)


def test_loader_refuses_a_directory_at_the_claim_path(world):
    world.claim_path.mkdir()
    with pytest.raises(ValueError):
        acq.load_final_holdout_access_claim(world.plan, world.campaign_dir)


def test_loader_refuses_a_plan_that_does_not_belong_to_the_directory(world, incomplete_base):
    acquire(world)
    with pytest.raises(ValueError):
        acq.load_final_holdout_access_claim(incomplete_base.plan, world.campaign_dir)
    for bad in (None, {}, "plan", dataclasses.replace(world.plan, campaign_id="0" * 64)):
        with pytest.raises(ValueError):
            acq.load_final_holdout_access_claim(bad, world.campaign_dir)
    with pytest.raises(ValueError):
        acq.load_final_holdout_access_claim(world.plan, "")


# ============================================================================================
# Architecture : pureté de la frontière, aucune lecture marché, aucune suppression [U]
# ============================================================================================

_ALLOWED_IMPORT_ROOTS = {
    "__future__", "datetime", "json", "os", "pathlib", "stat", "atomic_json_store", "dataset_split",
    "gate_v_campaign_manifest_v2", "gate_v_campaign_plan_v2", "gate_v_final_holdout_claim",
    "gate_v_preregistration", "gate_v_validation_policy", "research_run",
}
_MODULES_THAT_MUST_IGNORE_E2 = (
    "gate_v_campaign", "gate_v_campaign_plan_v2", "gate_v_campaign_manifest_v2", "gate_v_campaign_dispatch",
    "gate_v_evidence_completeness_v2", "gate_v_preregistration", "gate_v_validation_policy",
    "gate_v_final_holdout_claim", "atomic_json_store", "validation_oos", "validation_run", "dataset_split",
    "research_run",
)


def _source():
    return (_ROOT / "gate_v_final_holdout_claim_acquisition.py").read_text(encoding="utf-8")


def test_e2_imports_only_the_agreed_boundary():
    roots = set()
    for node in ast.walk(ast.parse(_source())):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            roots.add((node.module or "").split(".")[0])
    assert roots <= _ALLOWED_IMPORT_ROOTS, sorted(roots - _ALLOWED_IMPORT_ROOTS)
    assert {"atomic_json_store", "gate_v_campaign_manifest_v2", "gate_v_final_holdout_claim"} <= roots
    assert not roots & {"engine", "validation_oos", "walk_forward", "pandas", "numpy", "subprocess", "shutil",
                        "tempfile", "market_data", "job_store", "validation_run"}


def test_e2_contains_no_market_engine_event_or_deletion_call():
    import re

    source = _source()
    tokens = (
        "run_oos_validation", "run_backtest", "HoldoutAccessEvent", "read_csv", ".csv", "unlink",
        "rmtree", "os.remove", "os.rename", "os.replace", "shutil", "save_atomic", "retry", "time.sleep",
    )
    assert [token for token in tokens if token in source] == []
    assert re.search(r"\bload_data\b", source) is None  # `load_dataset_split_plan` n'est pas le chargeur de marché


def test_e2_creates_the_claim_only_through_the_durable_exclusive_primitive():
    calls = [
        node for node in ast.walk(ast.parse(_source()))
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "save_exclusive"
    ]
    assert len(calls) == 1
    durable = [kw for kw in calls[0].keywords if kw.arg == "durable"]
    assert len(durable) == 1 and isinstance(durable[0].value, ast.Constant) and durable[0].value.value is True


@pytest.mark.parametrize("module_name", _MODULES_THAT_MUST_IGNORE_E2)
def test_no_existing_module_references_the_acquisition_module(module_name):
    """Seul le futur E3 sera consommateur d'E2 (22.12) : E1, le Manifest, le Plan V2, V1 et le moteur d'OOS l'ignorent."""
    assert "gate_v_final_holdout_claim_acquisition" not in (_ROOT / f"{module_name}.py").read_text(encoding="utf-8")


# ============================================================================================
# [MP] Processus réels : exclusivité et crashs durs
# ============================================================================================


def _launch(world, tmp_path, modes, *, created_at=CREATED):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({**world.config(), "created_at": created_at}), encoding="utf-8")
    sync, go = tmp_path / "sync", tmp_path / "go"
    sync.mkdir()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    workers = []
    for index, mode in enumerate(modes):
        result, log = tmp_path / f"result_{index}.txt", tmp_path / f"stderr_{index}.txt"
        handle = log.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, str(_WORKER), str(config), mode, str(result), str(sync), str(go)],
            stdout=subprocess.DEVNULL, stderr=handle, env=env, cwd=str(_ROOT))
        workers.append((process, result, log, handle))
    try:
        deadline = time.monotonic() + 120
        while len(list(sync.glob("*.ready"))) < len(modes):
            for process, _result, log, _handle in workers:
                if process.poll() is not None and len(list(sync.glob("*.ready"))) < len(modes):
                    pytest.fail(f"un worker s'est arrêté avant la barrière : {log.read_text(encoding='utf-8')[-800:]}")
            assert time.monotonic() < deadline, "barrière non atteinte"
            time.sleep(0.01)
        go.write_text("go", encoding="utf-8")  # TOUS sont prêts : départ simultané au niveau d'O_EXCL
        codes = [process.wait(timeout=120) for process, *_ in workers]
    finally:
        for process, _result, _log, handle in workers:
            if process.poll() is None:
                process.kill()
            handle.close()
    results = [result.read_text(encoding="utf-8") if result.exists() else None for _p, result, _l, _h in workers]
    return codes, results


@pytest.mark.parametrize("count", (2, 8))
def test_real_concurrent_processes_produce_exactly_one_winner(world, tmp_path, count):
    before = state(world)
    codes, results = _launch(world, tmp_path, ["race"] * count)
    assert codes == [0] * count, results
    winners = [r for r in results if r and r.startswith("OK:")]
    assert len(winners) == 1 and sorted(r for r in results if r not in winners) == ["CONSUMED"] * (count - 1)
    claim = acq.load_final_holdout_access_claim(world.plan, world.campaign_dir)
    assert winners[0] == f"OK:{claim.claim_id}" and claim.created_at == CREATED
    after = state(world)
    claim_relative = world.claim_path.relative_to(world.root).as_posix()
    assert set(after) - set(before) == {claim_relative}  # un seul fichier créé : ni temporaire, ni doublon
    assert {k: v for k, v in after.items() if k != claim_relative} == before


_CRASH_EXPECTATIONS = {
    # mode: (le Claim existe, contenu valide)
    "crash_before_open": (False, None),
    "crash_after_open": (True, False),
    "crash_mid_write": (True, False),
    "crash_before_fsync": (True, True),
    "crash_after_fsync": (True, True),
}


@pytest.mark.parametrize("mode", sorted(_CRASH_EXPECTATIONS))
def test_a_hard_crash_at_each_point_of_the_durable_creation_follows_the_decision_11_matrix(world, tmp_path, mode):
    exists, valid = _CRASH_EXPECTATIONS[mode]
    codes, _results = _launch(world, tmp_path, [mode])
    assert codes == [9]  # mort dure : aucun nettoyage, aucun finally
    assert world.claim_path.exists() is exists
    if not exists:
        assert acquire(world).created_at == CREATED  # crash AVANT création : sûr, nouvelle tentative complète
        return
    leftover = world.claim_path.read_bytes()
    if valid:
        assert acq.load_final_holdout_access_claim(world.plan, world.campaign_dir).created_at == CREATED
    else:
        assert len(leftover) < len(as_text(valid_record(world.plan)).encode("utf-8"))
        with pytest.raises(ValueError):  # vide ou tronqué : jamais traité comme absent ni comme valide
            acq.load_final_holdout_access_claim(world.plan, world.campaign_dir)
    with pytest.raises(acq.FinalHoldoutClaimAlreadyConsumedError):  # consommé pour toujours, aucun retry
        acquire(world)
    assert world.claim_path.read_bytes() == leftover
