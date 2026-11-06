"""N2-b1b, tranches T2 à T6 — ADAPTATEUR `gate_v_audit_registry` (seam S-b : `validate_config`, `read`, `assess`, `compare`) : groupes RQ, RD, CC, CV, SG, AC, B4 de la note section 19.13.

Fixtures SYNTHÉTIQUES (`tmp_path`) : registres `SYNTHETIC` / `SIMULATED_DURABLE`, arbres de campagne des scénarios historiques, S1 réel par B3 v6. Aucune donnée de marché, aucun FINAL_HOLDOUT, aucune écriture
de registre par l'adaptateur (preuve : empreinte d'arbre identique avant / après). Les attendus sont des LITTÉRAUX ou des formules indépendantes écrites ici.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_registry_fixtures as fx
import gate_v_audit_registry as ar
import gate_v_registry_audit_support as sup
import gate_v_registry_chain as chain_module
import gate_v_registry_model as model
import gate_v_registry_store as store
from atomic_json_store import DurabilityProfile, serialize_normative_json
from gate_v_final_holdout_protocol import OwnRecordStage, SourceStatus
from gate_v_registry_chain import CampaignState, RegistryChainError
from gate_v_registry_store import ReadFailure, RegistryReadError
from tests.gate_v_manifest_scenarios import CID, SCENARIOS, realise
from tests.gate_v_audit_protocol_support import tree_digest

OWN = CID
WN = sup.WN
EARLY = ("2025-01-01T00:00:00.000000Z", "2025-02-01T00:00:00.000000Z")          # disjointe de W
INSIDE = ("2026-02-01T00:00:00.000000Z", "2026-02-10T00:00:00.000000Z")         # recoupe W
B, C_ = sup.foreign_id(0xB), sup.foreign_id(0xC)


def config(root, **changes):
    fields = dict(root_path=str(root), max_slots=100, max_total_bytes=10 ** 7)
    fields.update(changes)
    return ar.RegistryConfig(**fields)


def refused(call, *args, **kwargs):
    with pytest.raises(ar.RegistryAuditRefused) as caught:
        call(*args, **kwargs)
    return caught.value.code, caught.value.detail


def registry_of(tmp_path, entries, name="registry"):
    root = sup.new_registry(tmp_path, name)
    sup.populate(root, sup.build_chain(entries))
    return root


def own_dir(tmp_path, scenario="01-ready-initial"):
    return realise(tmp_path / "audit", SCENARIOS[scenario])


# ── RQ : configuration, sans accès disque ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def no_disk(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("accès disque")

    for owner, name in ((os, "lstat"), (os, "scandir"), (os, "open"), (os, "stat")):
        monkeypatch.setattr(owner, name, boom)


GOOD = str(Path("D:/registry" if os.name == "nt" else "/registry"))
BASE = Path("D:/audit" if os.name == "nt" else "/audit")


@pytest.mark.parametrize("changes", [
    {"root_path": b"bytes"}, {"root_path": ""}, {"root_path": "relative/path"}, {"root_path": GOOD + "/../x"}, {"root_path": GOOD + "\x00x"},
    {"max_slots": True}, {"max_slots": 0}, {"max_slots": -1}, {"max_slots": 1.5}, {"max_total_bytes": False}, {"max_total_bytes": 0}, {"max_total_bytes": "9"},
    {"max_slots": store.MAX_SLOTS + 1}, {"max_total_bytes": store.MAX_SLOTS * store.MAX_SLOT_BYTES + 1}])
def test_rq1_hostile_configs_are_request_invalid(no_disk, changes):
    fields = dict(root_path=GOOD, max_slots=10, max_total_bytes=100)
    fields.update(changes)
    assert refused(ar.validate_config, ar.RegistryConfig(**fields), audit_root_paths=()) == ("REQUEST_INVALID", "REGISTRY_CONFIG")


def test_rq1_subclass_and_non_config_are_refused(no_disk):
    class Sub(ar.RegistryConfig):
        pass

    assert refused(ar.validate_config, Sub(root_path=GOOD, max_slots=1, max_total_bytes=1), audit_root_paths=()) == ("REQUEST_INVALID", "REGISTRY_CONFIG")
    assert refused(ar.validate_config, {"root_path": GOOD}, audit_root_paths=()) == ("REQUEST_INVALID", "REGISTRY_CONFIG")


def test_rq1_budget_part_is_two_reads_of_total_plus_identity_bound(no_disk):
    got = ar.validate_config(ar.RegistryConfig(root_path=GOOD, max_slots=10, max_total_bytes=1000), audit_root_paths=())
    assert got == 2 * (1000 + 4096 + 2) == 10196                                      # littéral indépendant de la formule du module


@pytest.mark.parametrize("registry,audit,overlap", [
    (str(BASE), str(BASE), True), (str(BASE / "reg"), str(BASE), True), (str(BASE), str(BASE / "camp"), True),
    (str(BASE / "reg"), str(BASE / "reg2"), False),                                    # préfixe frère : jamais un préfixe de texte
    (str(BASE / "reg"), str(BASE / "other"), False), (str(BASE / "reg") + os.sep, str(BASE / "reg"), True),
])
def test_rq2_overlap_is_decided_on_path_components(no_disk, registry, audit, overlap):
    cfg = ar.RegistryConfig(root_path=registry, max_slots=10, max_total_bytes=100)
    if overlap:
        assert refused(ar.validate_config, cfg, audit_root_paths=(audit,)) == ("REQUEST_INVALID", "REGISTRY_ROOT_OVERLAP")
    else:
        assert ar.validate_config(cfg, audit_root_paths=(audit,)) > 0


@pytest.mark.skipif(os.name != "nt", reason="casse et lecteurs : Windows")
def test_rq2_windows_case_insensitivity_and_different_drives(no_disk):
    cfg = ar.RegistryConfig(root_path="D:\\Audit\\Reg", max_slots=10, max_total_bytes=100)
    assert refused(ar.validate_config, cfg, audit_root_paths=("d:\\audit\\reg\\x",)) == ("REQUEST_INVALID", "REGISTRY_ROOT_OVERLAP")
    assert ar.validate_config(cfg, audit_root_paths=("C:\\Audit\\Reg",)) > 0           # lecteurs différents : disjoints


# ── RD : lecture, refus typés, table exhaustive ───────────────────────────────────────────────────────────────────────────────────────────────

def test_rd1_healthy_empty_registry_reads_and_assesses(tmp_path):
    root, audit = sup.new_registry(tmp_path), own_dir(tmp_path)
    handle = ar.read(config(root), own_campaign_id=OWN, window=WN)
    result = ar.assess(handle, sup.interpret_campaigns([("camp", audit)]), own_campaign_id=OWN, window=WN, campaign_roots=(("camp", str(audit), OWN),), max_json_bytes=1_000_000)
    assert result.b4_complete is True and result.b4_incomplete_reasons == ()
    assert result.registry_id == fx.REGISTRY_ID and result.registry_slot_count == 0 and result.registry_rebind_count == 0
    assert result.registry_durability_profile == "SIMULATED_DURABLE" and result.registry_chain_head == sup.GENESIS
    assert result.registry_coverage is ar.RegistryCoverage.ALL_CHAIN_CAMPAIGNS_HAVE_ROOT and result.registry_other_campaign_count == 0 and result.registry_uncovered_count == 0
    assert [(c.name, c.value, c.provenance) for c in result.trial_counters] == [
        ("research_runs", None, ar.CounterState.NOT_OBSERVED), ("strategies", None, ar.CounterState.NOT_OBSERVED), ("campaigns", 0, ar.CounterState.OBSERVED),
        ("abandoned_reservations", None, ar.CounterState.NOT_OBSERVED), ("failed_ingestion_attempts", None, ar.CounterState.NOT_OBSERVED),
        ("void_commitments", None, ar.CounterState.NOT_OBSERVED)]
    assert result.trial_counter_reasons == ("abandoned_reservations:CLOSING_VIEW_NOT_PROVIDED", "failed_ingestion_attempts:VIEW_NOT_PROVIDED", "trials:VIEW_NOT_PROVIDED",
                                            "void_commitments:VIEW_NOT_PROVIDED")


def test_rd2_missing_root_and_missing_identity(tmp_path):
    assert refused(ar.read, config(tmp_path / "absent"), own_campaign_id=OWN, window=WN) == ("REGISTRY_UNREADABLE", "ROOT_UNUSABLE")
    root = sup.new_registry(tmp_path)
    (root / "identity.json").unlink()
    assert refused(ar.read, config(root), own_campaign_id=OWN, window=WN) == ("REGISTRY_UNREADABLE", "IDENTITY_MISSING")


def test_rd3_rd4_broken_chain_and_slot_gap(tmp_path):
    root = sup.new_registry(tmp_path)
    r = fx.reservation(0, sup.GENESIS, B, *EARLY)
    sup.put_slot(root, 0, r)
    sup.put_slot(root, 1, fx.reservation(1, fx.h("wrong"), C_, *INSIDE))
    assert refused(ar.read, config(root), own_campaign_id=OWN, window=WN) == ("REGISTRY_UNREADABLE", "CHAIN:CHAIN_LINK_BROKEN@1")
    gap = sup.new_registry(tmp_path, "gap")
    records = sup.build_chain([("R", B, *EARLY), ("R", C_, *INSIDE)])
    sup.put_slot(gap, 0, records[0])
    sup.put_slot(gap, 2, records[1])
    assert refused(ar.read, config(gap), own_campaign_id=OWN, window=WN) == ("REGISTRY_UNREADABLE", "SLOT_GAP")


def test_rd5_real_mode_is_refused(tmp_path):
    root = sup.new_registry(tmp_path)
    identity = {"registry_identity_version": store.IDENTITY_VERSION, "registry_id": fx.REGISTRY_ID, "instance_id": fx.INSTANCE_ID, "mode": "REAL", "durability_profile": "SIMULATED_DURABLE"}
    (root / "identity.json").write_bytes(serialize_normative_json(identity))
    assert refused(ar.read, config(root), own_campaign_id=OWN, window=WN) == ("REGISTRY_UNREADABLE", "MODE_REFUSED")


@pytest.mark.skipif(os.name != "nt", reason="la barrière POSIX_DIR_FSYNC n'est refusée qu'hors POSIX")
def test_rd6_posix_profile_fails_the_barrier_on_windows(tmp_path):
    root = sup.new_registry(tmp_path)
    identity = {"registry_identity_version": store.IDENTITY_VERSION, "registry_id": fx.REGISTRY_ID, "instance_id": fx.INSTANCE_ID, "mode": "SYNTHETIC", "durability_profile": "POSIX_DIR_FSYNC"}
    (root / "identity.json").write_bytes(serialize_normative_json(identity))
    assert refused(ar.read, config(root), own_campaign_id=OWN, window=WN) == ("REGISTRY_UNREADABLE", "BARRIER_FAILED")


def test_rd7_audit_ceilings_map_to_resource_budget(tmp_path):
    root = registry_of(tmp_path, [("R", B, *EARLY), ("R", C_, *INSIDE)])
    assert refused(ar.read, config(root, max_slots=1), own_campaign_id=OWN, window=WN) == ("RESOURCE_BUDGET_EXCEEDED", "REGISTRY_TOO_LARGE")
    assert refused(ar.read, config(root, max_total_bytes=10), own_campaign_id=OWN, window=WN) == ("RESOURCE_BUDGET_EXCEEDED", "REGISTRY_TOO_LARGE")


def test_rd8_read_uses_the_barrier_and_the_configured_ceilings(tmp_path, monkeypatch):
    root = sup.new_registry(tmp_path)
    calls = []
    real = ar.read_registry

    def spy(path, **kwargs):
        calls.append(kwargs)
        return real(path, **kwargs)

    monkeypatch.setattr(ar, "read_registry", spy)
    ar.read(config(root, max_slots=7, max_total_bytes=777), own_campaign_id=OWN, window=WN)
    assert calls == [{"barrier": True, "max_slots": 7, "max_total_bytes": 777}]


READ_TABLE = {ReadFailure.ROOT_UNUSABLE: "REGISTRY_UNREADABLE", ReadFailure.ROOT_EXISTS: "REGISTRY_UNREADABLE", ReadFailure.UNKNOWN_ENTRY: "REGISTRY_UNREADABLE",
              ReadFailure.NOT_REGULAR: "REGISTRY_UNREADABLE", ReadFailure.IDENTITY_MISSING: "REGISTRY_UNREADABLE", ReadFailure.IDENTITY_INVALID: "REGISTRY_UNREADABLE",
              ReadFailure.MODE_REFUSED: "REGISTRY_UNREADABLE", ReadFailure.SLOT_UNREADABLE: "REGISTRY_UNREADABLE", ReadFailure.SLOT_INVALID: "REGISTRY_UNREADABLE",
              ReadFailure.SLOT_GAP: "REGISTRY_UNREADABLE", ReadFailure.SLOT_NAME_MISMATCH: "REGISTRY_UNREADABLE", ReadFailure.TOO_LARGE: "RESOURCE_BUDGET_EXCEEDED",
              ReadFailure.TOO_MANY_SLOTS: "RESOURCE_BUDGET_EXCEEDED", ReadFailure.BARRIER_FAILED: "REGISTRY_UNREADABLE"}


@pytest.mark.parametrize("failure_code", list(ReadFailure), ids=[f.value for f in ReadFailure])
@pytest.mark.parametrize("prefix", ["", "R2:"])
def test_rd10_every_read_failure_maps_to_a_literal_refusal(failure_code, prefix):
    refusal = ar._read_error(RegistryReadError(failure_code, "x"), prefix)
    assert refusal.code == READ_TABLE[failure_code]
    assert refusal.detail == prefix + ("REGISTRY_TOO_LARGE" if READ_TABLE[failure_code] == "RESOURCE_BUDGET_EXCEEDED" else failure_code.value)


def test_rd10_table_is_exhaustive_over_read_failure_and_chain_codes():
    assert set(READ_TABLE) == set(ReadFailure) and len(ReadFailure) == 14
    from gate_v_registry_chain import RegistryRefusalCode
    for code in RegistryRefusalCode:
        refusal = ar._read_error(RegistryChainError(code, "m", index=3), "")
        assert (refusal.code, refusal.detail) == ("REGISTRY_UNREADABLE", f"CHAIN:{code.value}@3")


def test_rd_closed_code_set_and_malformed_refusals():
    assert ar.REGISTRY_REFUSAL_CODES == ("REQUEST_INVALID", "RESOURCE_BUDGET_EXCEEDED", "REGISTRY_UNREADABLE", "REGISTRY_CHAIN_HEAD_CHANGED", "WINDOW_MISMATCH", "STAGE_NOT_DERIVABLE",
                                         "B4_ASSEMBLY_REFUSED")
    with pytest.raises(ValueError):
        ar.RegistryAuditRefused("NOT_A_CODE", "x")
    with pytest.raises(ValueError):
        ar.RegistryAuditRefused("REQUEST_INVALID", "x" * 301)


def test_rd_own_record_window_is_checked_immediately(tmp_path):
    root = registry_of(tmp_path, [("R", OWN, WN[0], "2026-03-01T00:00:00.000000Z")])
    assert refused(ar.read, config(root), own_campaign_id=OWN, window=WN) == ("WINDOW_MISMATCH", "OWN_RECORD_WINDOW")
    equal = registry_of(tmp_path, [("R", OWN, *WN)], "equal")
    assert ar.read(config(equal), own_campaign_id=OWN, window=WN) is not None
    one_microsecond = registry_of(tmp_path, [("R", OWN, WN[0], "2026-04-01T00:00:00.000001Z")], "micro")
    assert refused(ar.read, config(one_microsecond), own_campaign_id=OWN, window=WN) == ("WINDOW_MISMATCH", "OWN_RECORD_WINDOW")


# ── Poignée opaque ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_handle_is_opaque_frozen_and_not_transportable(tmp_path):
    import copy
    import pickle
    handle = ar.read(config(sup.new_registry(tmp_path)), own_campaign_id=OWN, window=WN)
    assert not [name for name in dir(handle) if not name.startswith("_")]
    for operation in (lambda: copy.copy(handle), lambda: copy.deepcopy(handle), lambda: pickle.dumps(handle)):
        with pytest.raises(TypeError):
            operation()
    with pytest.raises(AttributeError):
        handle.value = 1
    with pytest.raises(TypeError):
        ar.RegistryHandle(object(), None, (), ())


def test_assess_consumes_the_handle_and_releases_the_snapshot(tmp_path):
    root, audit = sup.new_registry(tmp_path), own_dir(tmp_path)
    handle = ar.read(config(root), own_campaign_id=OWN, window=WN)
    args = dict(own_campaign_id=OWN, window=WN, campaign_roots=(("camp", str(audit), OWN),), max_json_bytes=1_000_000)
    s1 = sup.interpret_campaigns([("camp", audit)])
    ar.assess(handle, s1, **args)
    assert handle._state[0] is None and handle._state[1][6] == 0 and handle._state[2] == ()
    with pytest.raises(TypeError):
        ar.assess(handle, s1, **args)


# ── CC : concurrence (modifications réelles du disque entre R1 et R2) ────────────────────────────────────────────────────────────────────────────

def _r1(tmp_path, entries, **config_changes):
    root = registry_of(tmp_path, entries)
    cfg = config(root, **config_changes)
    return root, cfg, ar.read(cfg, own_campaign_id=OWN, window=WN)


def test_cc0_unchanged_registry_compares_equal(tmp_path):
    _root, cfg, handle = _r1(tmp_path, [("R", B, *EARLY)])
    ar.compare(handle, cfg)


def test_cc1_extension_is_a_change(tmp_path):
    root, cfg, handle = _r1(tmp_path, [("R", B, *EARLY)])
    longer = sup.build_chain([("R", B, *EARLY), ("R", C_, *INSIDE)])
    sup.put_slot(root, 1, longer[1])
    assert refused(ar.compare, handle, cfg) == ("REGISTRY_CHAIN_HEAD_CHANGED", "EXTENDED")


def test_cc2_cc4_modified_prefix_and_truncation_are_divergence(tmp_path):
    root, cfg, handle = _r1(tmp_path, [("R", B, *EARLY), ("R", C_, *INSIDE)])
    sup.put_slot(root, 0, sup.build_chain([("R", sup.foreign_id(0xD), *EARLY)])[0])
    assert refused(ar.compare, handle, cfg) == ("REGISTRY_UNREADABLE", "R2:CHAIN:CHAIN_LINK_BROKEN@1")      # le préfixe modifié casse d'abord la chaîne lue
    (tmp_path / "two").mkdir()
    root2, cfg2, handle2 = _r1(tmp_path / "two", [("R", B, *EARLY), ("R", C_, *INSIDE)])
    (root2 / "admissions" / model.slot_file_name(1)).unlink()
    assert refused(ar.compare, handle2, cfg2) == ("REGISTRY_CHAIN_HEAD_CHANGED", "DIVERGED")
    (tmp_path / "three").mkdir()
    root3, cfg3, handle3 = _r1(tmp_path / "three", [("R", B, *EARLY)])
    sup.put_slot(root3, 0, sup.build_chain([("R", sup.foreign_id(0xD), *EARLY)])[0])
    assert refused(ar.compare, handle3, cfg3) == ("REGISTRY_CHAIN_HEAD_CHANGED", "DIVERGED")


def test_cc3_a_rebind_is_an_instance_change(tmp_path):
    root, cfg, handle = _r1(tmp_path, [("R", B, *EARLY)])
    longer = sup.build_chain([("R", B, *EARLY), ("B", "c" * 32, None, None)])
    sup.put_slot(root, 1, longer[1])
    assert refused(ar.compare, handle, cfg) == ("REGISTRY_CHAIN_HEAD_CHANGED", "INSTANCE_CHANGED")


def test_cc5_replaced_identity_of_an_empty_registry_is_an_identity_change(tmp_path):
    root, cfg, handle = _r1(tmp_path, [])
    identity = {"registry_identity_version": store.IDENTITY_VERSION, "registry_id": "another-registry", "instance_id": fx.INSTANCE_ID, "mode": "SYNTHETIC",
                "durability_profile": "SIMULATED_DURABLE"}
    (root / "identity.json").write_bytes(serialize_normative_json(identity))
    assert refused(ar.compare, handle, cfg) == ("REGISTRY_CHAIN_HEAD_CHANGED", "IDENTITY_CHANGED")
    (tmp_path / "x").mkdir()
    other = sup.new_registry(tmp_path / "x", "r")
    cfg2 = config(other)
    handle2 = ar.read(cfg2, own_campaign_id=OWN, window=WN)
    new_instance = {"registry_identity_version": store.IDENTITY_VERSION, "registry_id": fx.REGISTRY_ID, "instance_id": "b" * 32, "mode": "SYNTHETIC",
                    "durability_profile": "SIMULATED_DURABLE"}
    (other / "identity.json").write_bytes(serialize_normative_json(new_instance))
    assert refused(ar.compare, handle2, cfg2) == ("REGISTRY_CHAIN_HEAD_CHANGED", "IDENTITY_CHANGED")


def test_cc6_removed_registry_or_unreadable_slot_is_a_prefixed_read_failure(tmp_path):
    root, cfg, handle = _r1(tmp_path, [("R", B, *EARLY)])
    (root / "admissions" / model.slot_file_name(0)).write_bytes(b"{")
    assert refused(ar.compare, handle, cfg) == ("REGISTRY_UNREADABLE", "R2:SLOT_INVALID")
    (tmp_path / "two").mkdir()
    root2, cfg2, handle2 = _r1(tmp_path / "two", [])
    for child in sorted(root2.rglob("*"), reverse=True):
        child.unlink() if child.is_file() else child.rmdir()
    root2.rmdir()
    assert refused(ar.compare, handle2, cfg2) == ("REGISTRY_UNREADABLE", "R2:ROOT_UNUSABLE")


def test_cc6b_growth_beyond_the_ceiling_between_reads_is_a_prefixed_budget_refusal(tmp_path):
    root, cfg, handle = _r1(tmp_path, [("R", B, *EARLY)], max_slots=1)
    sup.put_slot(root, 1, None, raw=b"x")
    assert refused(ar.compare, handle, cfg) == ("RESOURCE_BUDGET_EXCEEDED", "R2:REGISTRY_TOO_LARGE")


def test_cc8_cc9_append_after_the_second_read_and_aba_are_not_detected(tmp_path):
    root, cfg, handle = _r1(tmp_path, [("R", B, *EARLY), ("R", C_, *INSIDE)])
    slot = root / "admissions" / model.slot_file_name(1)
    saved = slot.read_bytes()
    slot.unlink()
    slot.write_bytes(saved)                                                      # ABA : supprimé puis restauré à l'identique
    ar.compare(handle, cfg)                                                      # limite consignée (T18) : non détecté
    sup.put_slot(root, 2, sup.build_chain([("R", B, *EARLY), ("R", C_, *INSIDE), ("R", sup.foreign_id(0xE), "2027-01-01T00:00:00.000000Z", "2027-02-01T00:00:00.000000Z")])[2])
    # un ajout APRÈS la deuxième lecture ne peut pas être détecté : il n'y a plus de lecture ensuite


def test_compare_precedence_of_rules(tmp_path):
    # identité différente ET préfixe divergent : la première règle de l'ordre décide
    root, cfg, handle = _r1(tmp_path, [("R", B, *EARLY)])
    identity = {"registry_identity_version": store.IDENTITY_VERSION, "registry_id": "another-registry", "instance_id": fx.INSTANCE_ID, "mode": "SYNTHETIC",
                "durability_profile": "SIMULATED_DURABLE"}
    (root / "identity.json").write_bytes(serialize_normative_json(identity))
    code, detail = refused(ar.compare, handle, cfg)
    assert (code, detail) == ("REGISTRY_UNREADABLE", "R2:CHAIN:REGISTRY_MISMATCH@0")      # la lecture échoue avant toute comparaison : jamais présenté comme un changement de tête


# ── CV : conversion (fonction pure) ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _canonical_hash(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _chain_from(entries):
    records = sup.build_chain(entries)
    return chain_module.verify_chain(records, registry_id=fx.REGISTRY_ID, genesis_instance_id=fx.INSTANCE_ID), records


def test_cv1_lossless_conversion_with_independent_hashes():
    chain, records = _chain_from([("R", B, *EARLY), ("A", B, None, None), ("B", "c" * 32, None, None), ("R", C_, *INSIDE), ("A", C_, None, None), ("C", B, None, None)])
    view, rebinds = ar._convert(chain)
    assert rebinds == 1 and len(view.records) + rebinds == chain.next_seq == 6
    assert [fact.seq for fact in view.records] == [0, 1, 3, 4, 5]
    assert [fact.content_hash for fact in view.records] == [_canonical_hash(records[i]) for i in (0, 1, 3, 4, 5)]
    assert all(fact.snapshot_id is None for fact in view.records)
    assert view.chain_head == _canonical_hash(records[-1]) and view.unreadable_record_ids == ()


def test_cv2_record_type_to_source_kind_is_exhaustive():
    from gate_v_registry_model import RecordType
    assert set(ar._KINDS) == {RecordType.RESERVATION, RecordType.ADMISSION, RecordType.CONSUMPTION} == set(RecordType) - {RecordType.REBIND}
    assert {k.value for k in ar._KINDS.values()} == {"REGISTRY_RESERVATION", "REGISTRY_ADMISSION", "CONSUMPTION"}


def test_cv3_a_forged_entry_without_campaign_or_window_is_refused_never_degraded():
    chain, _records = _chain_from([("R", B, *EARLY)])
    import dataclasses
    for changes in ({"campaign_id": None}, {"window": None}):
        forged = types.SimpleNamespace(entries=(dataclasses.replace(chain.entries[0], **changes),), next_seq=1, registry_id=chain.registry_id, head_content_hash=chain.head_content_hash)
        assert refused(ar._convert, forged) == ("B4_ASSEMBLY_REFUSED", "FACT_CONSTRUCTION")


def test_cv3_a_lost_record_is_refused():
    chain, _records = _chain_from([("R", B, *EARLY), ("R", C_, *INSIDE)])
    forged = types.SimpleNamespace(entries=chain.entries, next_seq=3, registry_id=chain.registry_id, head_content_hash=chain.head_content_hash)
    assert refused(ar._convert, forged) == ("B4_ASSEMBLY_REFUSED", "FACT_CONSTRUCTION")


@pytest.mark.parametrize("window", [("0001-01-01T00:00:00.000000Z", "0001-01-01T00:00:00.000001Z"), ("9999-12-31T23:59:59.999998Z", "9999-12-31T23:59:59.999999Z")])
def test_cv5_extreme_windows_are_accepted(window):
    chain, _records = _chain_from([("R", B, *window)])
    view, _ = ar._convert(chain)
    assert (view.records[0].window_start_utc, view.records[0].window_end_utc) == window


def test_cv5_adjacent_windows_do_not_overlap_and_one_microsecond_overlap_does():
    # fenêtre propre W = [2026-01-01, 2026-04-01) ; voisine adjacente et voisine empiétant de 1 µs
    from gate_v_exposure_sources import overlap_verdict
    assert overlap_verdict("2025-12-01T00:00:00.000000Z", "2026-01-01T00:00:00.000000Z", *WN).value == "NO_OVERLAP"
    assert overlap_verdict("2025-12-01T00:00:00.000000Z", "2026-01-01T00:00:00.000001Z", *WN).value == "OVERLAPS"


def test_cv7_campaign_counter_excludes_the_own_campaign(tmp_path):
    root = registry_of(tmp_path, [("R", OWN, *WN), ("R", B, *EARLY), ("R", C_, "2025-03-01T00:00:00.000000Z", "2025-04-01T00:00:00.000000Z")])
    audit = own_dir(tmp_path)
    handle = ar.read(config(root), own_campaign_id=OWN, window=WN)
    result = ar.assess(handle, sup.interpret_campaigns([("camp", audit)]), own_campaign_id=OWN, window=WN, campaign_roots=(("camp", str(audit), OWN),), max_json_bytes=1_000_000)
    assert [c.value for c in result.trial_counters if c.name == "campaigns"] == [2] and result.registry_other_campaign_count == 2


# ── SG : étage de l'enregistrement propre ────────────────────────────────────────────────────────────────────────────────────────────────────────

def claim(status=SourceStatus.RESOLVED, campaign=OWN, window=WN):
    return types.SimpleNamespace(status=status, campaign_id=campaign, window_start_utc=window[0], window_end_utc=window[1])


S = CampaignState
ST = OwnRecordStage
STAGE_TABLE = [(S.ABSENT, 0, ST.NO_OWN_RECORDS), (S.RESERVED, 0, ST.RESERVED), (S.ADMITTED, 0, ST.ADMITTED), (S.ADMITTED, 1, ST.CLAIMED), (S.CONSUMED, 1, ST.CONSUMED)]


@pytest.mark.parametrize("state,count,expected", STAGE_TABLE)
def test_sg1_rule_8_five_pairs(state, count, expected):
    assert ar.derive_stage(state, tuple(claim() for _ in range(count)), (), WN, OWN) is expected


@pytest.mark.parametrize("state,count,detail", [(S.ABSENT, 1, "STAGE_RECORD_WITHOUT_PRIOR"), (S.RESERVED, 1, "STAGE_RECORD_WITHOUT_PRIOR"), (S.CONSUMED, 0, "STAGE_CONSUMED_WITHOUT_RECORD")])
def test_sg1_the_three_other_pairs_are_refused(state, count, detail):
    assert refused(ar.derive_stage, state, tuple(claim() for _ in range(count)), (), WN, OWN) == ("STAGE_NOT_DERIVABLE", detail)


def test_sg2_each_rule_once_in_order():
    assert refused(ar.derive_stage, S.ADMITTED, (claim(), claim()), (), WN, OWN)[1] == "STAGE_RECORD_MULTIPLE"                                    # 1
    assert refused(ar.derive_stage, S.ADMITTED, (claim(SourceStatus.UNRESOLVED, None),), (), WN, OWN)[1] == "STAGE_RECORD_UNRESOLVED"            # 2
    assert refused(ar.derive_stage, S.ADMITTED, (claim(campaign=B),), (), WN, OWN)[1] == "STAGE_RECORD_OTHER_CAMPAIGN"                         # 3
    assert refused(ar.derive_stage, S.ADMITTED, (claim(window=EARLY),), (), WN, OWN)[1] == "STAGE_RECORD_WINDOW"                               # 4
    assert refused(ar.derive_stage, S.ADMITTED, (), (claim(),), WN, OWN)[1] == "STAGE_RECORD_OUTSIDE_OWN_ROOT"                                  # 5
    assert refused(ar.derive_stage, S.RESERVED, (claim(),), (), WN, OWN)[1] == "STAGE_RECORD_WITHOUT_PRIOR"                                     # 6
    assert refused(ar.derive_stage, S.CONSUMED, (), (), WN, OWN)[1] == "STAGE_CONSUMED_WITHOUT_RECORD"                                          # 7


def test_sg2_precedence_when_two_rules_apply():
    assert refused(ar.derive_stage, S.ABSENT, (claim(campaign=B),), (), WN, OWN)[1] == "STAGE_RECORD_OTHER_CAMPAIGN"                           # règle 3 avant la règle 6
    assert refused(ar.derive_stage, S.ABSENT, (claim(SourceStatus.UNRESOLVED, None),), (), WN, OWN)[1] == "STAGE_RECORD_UNRESOLVED"            # règle 2 avant la règle 6
    assert refused(ar.derive_stage, S.CONSUMED, (), (claim(),), WN, OWN)[1] == "STAGE_RECORD_OUTSIDE_OWN_ROOT"                                 # règle 5 avant la règle 7


def test_sg2_the_table_is_total_over_the_eight_pairs():
    seen = set()
    for state in (S.ABSENT, S.RESERVED, S.ADMITTED, S.CONSUMED):
        for count in (0, 1):
            try:
                ar.derive_stage(state, tuple(claim() for _ in range(count)), (), WN, OWN)
            except ar.RegistryAuditRefused:
                pass
            seen.add((state, count))
    assert len(seen) == 8


def test_sg4_sg5_a_corrupted_claim_file_is_unresolved_whatever_the_registry_state(tmp_path):
    audit = own_dir(tmp_path)
    (audit / "final_holdout_access_claim.json").write_bytes(b"{")
    s1 = sup.interpret_campaigns([("camp", audit)])
    for entries in ([], [("R", OWN, *WN)], [("R", OWN, *WN), ("A", OWN, None, None)], [("R", OWN, *WN), ("A", OWN, None, None), ("C", OWN, None, None)]):
        root = registry_of(tmp_path, entries, f"reg{len(entries)}")
        handle = ar.read(config(root), own_campaign_id=OWN, window=WN)
        assert refused(ar.assess, handle, s1, own_campaign_id=OWN, window=WN, campaign_roots=(("camp", str(audit), OWN),), max_json_bytes=1_000_000) == (
            "STAGE_NOT_DERIVABLE", "STAGE_RECORD_UNRESOLVED")


def test_sg4_claim_without_split_plan_is_unresolved_while_b3_stays_complete(tmp_path):
    audit = own_dir(tmp_path)
    (audit / "final_holdout_access_claim.json").write_bytes(b'{"claim_semantics_version": "x"}')
    s1 = sup.interpret_campaigns([("camp", audit)])
    claims = [f for f in s1.findings if f.source_kind.value == "FINAL_HOLDOUT_CLAIM"]
    assert claims and claims[0].source_id == "campaign.claim:camp/final_holdout_access_claim.json"
    assert claims[0].status is SourceStatus.UNRESOLVED and claims[0].campaign_id is None


def test_sg6_sg7_claims_of_other_roots(tmp_path):
    own = own_dir(tmp_path)
    other = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"], name=B)
    (other / "final_holdout_access_claim.json").write_bytes(b"{")
    s1 = sup.interpret_campaigns([("camp", own), ("other", other)])
    root = sup.new_registry(tmp_path)
    handle = ar.read(config(root), own_campaign_id=OWN, window=WN)
    result = ar.assess(handle, s1, own_campaign_id=OWN, window=WN, campaign_roots=(("camp", str(own), OWN), ("other", str(other), B)), max_json_bytes=1_000_000)
    assert result.registry_other_campaign_count == 0                                                           # le Claim d'une autre racine n'a aucun effet sur l'étage
    assert result.b4_complete is False                                                                          # mais la source exposante non résolue rend B4 incomplet


# ── AC et B4 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

SOURCE = Path(ar.__file__).read_text(encoding="utf-8")


def test_ac2_accounting_views_are_built_empty_and_never_invented():
    tree = ast.parse(SOURCE)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "AccountingViews"]
    assert len(calls) == 1 and not calls[0].args and not calls[0].keywords


def test_ac1_trial_counter_invariant_and_order():
    assert [name for name in ar._COUNTER_NAMES] == ["research_runs", "strategies", "campaigns", "abandoned_reservations", "failed_ingestion_attempts", "void_commitments"]
    with pytest.raises(ValueError):
        ar.TrialCounter("research_runs", 0, ar.CounterState.NOT_OBSERVED)
    with pytest.raises(ValueError):
        ar.TrialCounter("campaigns", None, ar.CounterState.OBSERVED)
    assert ar.TrialCounter("campaigns", 0, ar.CounterState.OBSERVED).value == 0


def test_counter_state_matches_b4_provenance_exhaustively():
    from gate_v_exposure_inventory import CounterProvenance
    assert {p.value for p in CounterProvenance} == {s.value for s in ar.CounterState} and set(ar._STATE_OF) == set(CounterProvenance)


@pytest.mark.parametrize("scenario,b3_complete", [("01-ready-initial", True), ("15-exposure-empty-ready", True), ("18-no-manifest-validations-empty", True),
                                                   ("02-wf-declared-directory-absent", False), ("14-foreign-manifest", False), ("10-complete-claimed-seal-missing", False)])
def test_b3_b4_conditional_equality_with_an_empty_registry(tmp_path, scenario, b3_complete):
    audit = own_dir(tmp_path, scenario)
    root = sup.new_registry(tmp_path)
    s1 = sup.interpret_campaigns([("camp", audit)])
    assert s1.complete is b3_complete                                                                          # anti-vacuité : les deux cas sont exercés
    handle = ar.read(config(root), own_campaign_id=OWN, window=WN)
    result = ar.assess(handle, s1, own_campaign_id=OWN, window=WN, campaign_roots=(("camp", str(audit), OWN),), max_json_bytes=1_000_000)
    assert result.b4_complete is b3_complete
    if not b3_complete:
        assert result.b4_complete is False                                                                      # jamais B4 COMPLETE avec B3 INCOMPLETE
    assert result.b4_incomplete_reasons == ()                                                                   # B4 n'ajoute aucune raison propre avec un registre vide


def test_b2_b4_can_add_its_own_reason_without_b3_incompleteness(tmp_path):
    """B3 complet mais registre contenant un enregistrement propre sans fenêtre résolvable ne peut pas être construit par l'API publique : la raison propre se teste sur le B4 direct (vue forgée)."""
    from gate_v_exposure_inventory import AccountingViews, RegistryRecordFact, RegistryView, assemble_exposure_inventory
    from gate_v_final_holdout_protocol import OwnCampaignContext, SourceKind
    audit = own_dir(tmp_path)
    s1 = sup.interpret_campaigns([("camp", audit)])
    forged = RegistryView(registry_id="r", chain_head=None, records=(RegistryRecordFact(seq=0, kind=SourceKind.REGISTRY_RESERVATION, campaign_id=None, content_hash="a" * 64,
                                                                                         window_start_utc=None, window_end_utc=None),))
    assembly = assemble_exposure_inventory(s1, registry=forged, accounting=AccountingViews(), own_context=OwnCampaignContext(OWN, OwnRecordStage.NO_OWN_RECORDS))
    assert s1.complete and not assembly.inventory.complete
    assert any(reason.startswith("REGISTRY_RECORD_UNRESOLVED:") for reason in assembly.incomplete_reasons)


def test_b6_b4_assembly_errors_are_typed(tmp_path, monkeypatch):
    root, audit = sup.new_registry(tmp_path), own_dir(tmp_path)
    s1 = sup.interpret_campaigns([("camp", audit)])
    args = dict(own_campaign_id=OWN, window=WN, campaign_roots=(("camp", str(audit), OWN),), max_json_bytes=1_000_000)

    def raising(error):
        def boom(*a, **k):
            raise error
        return boom

    monkeypatch.setattr(ar, "assemble_exposure_inventory", raising(ValueError("x")))
    assert refused(ar.assess, ar.read(config(root), own_campaign_id=OWN, window=WN), s1, **args) == ("B4_ASSEMBLY_REFUSED", "ASSEMBLY")
    monkeypatch.setattr(ar, "assemble_exposure_inventory", raising(TypeError("x")))
    assert refused(ar.assess, ar.read(config(root), own_campaign_id=OWN, window=WN), s1, **args) == ("B4_ASSEMBLY_REFUSED", "ASSEMBLY")
    monkeypatch.setattr(ar, "assemble_exposure_inventory", raising(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        ar.assess(ar.read(config(root), own_campaign_id=OWN, window=WN), s1, **args)               # une erreur inattendue n'est PAS convertie (filet du protocole)
    monkeypatch.setattr(ar, "assemble_exposure_inventory", raising(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        ar.assess(ar.read(config(root), own_campaign_id=OWN, window=WN), s1, **args)


# ── NW / GU : aucune écriture, aucune autorité, imports ──────────────────────────────────────────────────────────────────────────────────────────

def test_nw1_nw3_the_adapter_writes_nothing_and_creates_no_record(tmp_path):
    root, audit = registry_of(tmp_path, [("R", B, *EARLY)]), own_dir(tmp_path)
    before = (tree_digest(root), tree_digest(audit))
    handle = ar.read(config(root), own_campaign_id=OWN, window=WN)
    ar.assess(handle, sup.interpret_campaigns([("camp", audit)]), own_campaign_id=OWN, window=WN, campaign_roots=(("camp", str(audit), OWN),), max_json_bytes=1_000_000)
    ar.compare(ar.read(config(root), own_campaign_id=OWN, window=WN), config(root))
    assert (tree_digest(root), tree_digest(audit)) == before
    assert not any(name in p.name for p in tmp_path.rglob("*") for name in ("exposure_inventory", "final_holdout_access_claim"))


def _imports():
    tree = ast.parse(SOURCE)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_gu_the_adapter_imports_only_the_documented_modules_and_no_dynamic_import():
    assert _imports() <= {"__future__", "dataclasses", "enum", "os", "typing", "gate_v_audit_window", "gate_v_exposure_interpreters", "gate_v_exposure_inventory",
                          "gate_v_final_holdout_protocol", "gate_v_registry_chain", "gate_v_registry_model", "gate_v_registry_store", "gate_v_audit_plan_declared"}, _imports()
    tree = ast.parse(SOURCE)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not {"__import__", "importlib", "import_module"} & names
    store_imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "gate_v_registry_store"]
    assert len(store_imports) == 1 and not [n for n in ast.walk(tree) if isinstance(n, ast.Import) and any(a.name == "gate_v_registry_store" for a in n.names)]


def test_gu_the_adapter_has_no_write_primitive_and_names_no_forbidden_module():
    tree = ast.parse(SOURCE)
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "open" not in calls and not {"write", "write_bytes", "write_text", "mkdir", "unlink", "rename", "replace", "remove", "rmdir", "makedirs", "utime", "now", "time", "popen", "system",
                                         "run"} & attributes
    for forbidden in ("save_exclusive", "save_atomic", "load_json_tolerant", "initialize_synthetic_registry", "publish_json_by_link", "publish_bytes_by_link", "assemble_record", "subprocess",
                      "datetime", "pandas", "read_csv", "nasdaq_3m", "mt5", "gate_v_audit_protocol", "gate_v_exposure_interpreters_v", "interpret_audit_roots", "gate_v_registry_append",
                      "gate_v_registry_views", "gate_v_exposure_store", "gate_v_exposure_declarations", "gate_v_inventory_preconditions", "gate_v_campaign_manifest"):
        assert forbidden not in SOURCE, forbidden
    assert SOURCE.count("final_holdout_access_claim.json") == 1                                               # littéral unique et privé


FORBIDDEN_SUBSTRINGS = ("FRESH", "NO_OVERLAP", "ADMIT", "ADMISSION", "CLAIM", "AUTHORI", "ABSENCE_ESTABLISHED", "EXCLUSION")
FORBIDDEN_TOKENS = {"PASS", "OK", "VALID", "CLEAN", "CLEARED", "ALLOWED", "GRANTED", "ACCESS"}


def test_gu1_vocabulary_of_the_adapter_public_names_and_types():
    names = list(ar.__all__) + [f.name for cls in (ar.RegistryConfig, ar.TrialCounter, ar.RegistryAssessment) for f in __import__("dataclasses").fields(cls)]
    names += [member.name for enum_class in (ar.CounterState, ar.RegistryCoverage) for member in enum_class] + [member.value for enum_class in (ar.CounterState, ar.RegistryCoverage) for member in enum_class]
    names += list(ar.REGISTRY_REFUSAL_CODES) + [n for n in ("REGISTRY_CONFIG", "REGISTRY_ROOT_OVERLAP", "REGISTRY_TOO_LARGE", "REGISTRY_BUDGET")]
    for name in names:
        upper = name.upper()
        assert not any(bad in upper for bad in FORBIDDEN_SUBSTRINGS), name
        assert not FORBIDDEN_TOKENS & set(upper.split("_")), name
    assert any(bad in "FRESH_X" for bad in FORBIDDEN_SUBSTRINGS) and FORBIDDEN_TOKENS & set("PASS".split("_"))        # témoin de non-vacuité


def test_gu_stage_details_are_a_closed_vocabulary_without_forbidden_substrings():
    details = ["STAGE_RECORD_MULTIPLE", "STAGE_RECORD_UNRESOLVED", "STAGE_RECORD_OTHER_CAMPAIGN", "STAGE_RECORD_WINDOW", "STAGE_RECORD_OUTSIDE_OWN_ROOT", "STAGE_RECORD_WITHOUT_PRIOR",
               "STAGE_CONSUMED_WITHOUT_RECORD", "IDENTITY_CHANGED", "DIVERGED", "INSTANCE_CHANGED", "EXTENDED", "OWN_RECORD_WINDOW", "FACT_CONSTRUCTION", "ASSEMBLY"]
    for detail in details:
        assert not any(bad in detail for bad in FORBIDDEN_SUBSTRINGS) and not FORBIDDEN_TOKENS & set(detail.split("_")), detail
