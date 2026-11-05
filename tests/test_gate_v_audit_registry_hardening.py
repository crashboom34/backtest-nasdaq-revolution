"""N2-b1b — DURCISSEMENT des tests après la revue indépendante des tests et les mutants survivants (note section 19.13) : transmission à B4 observable, étage RÉEL avec Claim résolu, égalité conditionnelle
B3 / B4 sur les 33 scénarios, précédence de `compare`, séparation des raisons de B4, bornes littérales du store, ordre de la validation, orphelin disparu pendant le listage.

Fixtures SYNTHÉTIQUES (`tmp_path`). Aucun A0, aucune admission, aucune écriture de registre, aucune donnée de marché, aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_registry_fixtures as fx
import gate_v_audit_registry as ar
import gate_v_registry_audit_support as sup
import gate_v_registry_model as model
import gate_v_registry_store as store
from atomic_json_store import serialize_normative_json
from gate_v_exposure_inventory import AccountingViews, RegistryRecordFact, RegistryView, assemble_exposure_inventory
from gate_v_final_holdout_protocol import OwnCampaignContext, OwnRecordStage, SourceKind
from gate_v_registry_store import ReadFailure, RegistryReadError
from tests.gate_v_manifest_scenarios import CID, SCENARIOS, realise
from tests.test_gate_v_exposure_interpreters import (CAMPAIGN_ID, PLAN, claim_record, clean_results, interpret as b3_interpret, make_campaign, make_split, results_root,
                                                      campaign_root)

WN = sup.WN
EARLY = ("2025-01-01T00:00:00.000000Z", "2025-02-01T00:00:00.000000Z")
B = sup.foreign_id(0xB)
OWN = CID
OTHER_ID = "gate_v_v2_" + "cd" * 32
MAX_JSON = 1_000_000


def config(root, **changes):
    fields = dict(root_path=str(root), max_slots=1000, max_total_bytes=10 ** 7)
    fields.update(changes)
    return ar.RegistryConfig(**fields)


def refused(call, *args, **kwargs):
    with pytest.raises(ar.RegistryAuditRefused) as caught:
        call(*args, **kwargs)
    return caught.value.code, caught.value.detail


class SpyB4:
    """Enveloppe `assemble_exposure_inventory` de l'adaptateur : enregistre les arguments RÉELS et l'assemblage retourné (rien n'est simulé)."""

    def __init__(self, monkeypatch):
        self.calls, self.results = [], []
        real = ar.assemble_exposure_inventory

        def spy(interpretation, **kwargs):
            self.calls.append(kwargs)
            assembly = real(interpretation, **kwargs)
            self.results.append(assembly)
            return assembly

        monkeypatch.setattr(ar, "assemble_exposure_inventory", spy)


def assess_roots(tmp_path, entries, roots, s1, *, own=OWN, name="registry", window=WN):
    registry = sup.new_registry(tmp_path, name)
    sup.populate(registry, sup.build_chain(entries))
    handle = ar.read(config(registry), own_campaign_id=own, window=window)
    return ar.assess(handle, s1, own_campaign_id=own, window=window, campaign_roots=tuple(roots), max_json_bytes=MAX_JSON)


# ── Transmission à B4 observable (B5, SG8, AC4) ───────────────────────────────────────────────────────────────────────────────────────────────

def test_b4_receives_the_converted_view_an_empty_accounting_and_the_derived_stage(tmp_path, monkeypatch):
    spy = SpyB4(monkeypatch)
    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    entries = [("R", OWN, *WN), ("A", OWN, None, None), ("R", B, *EARLY)]
    records = sup.build_chain(entries)
    s1 = sup.interpret_campaigns([("camp", audit)])
    assess_roots(tmp_path, entries, [("camp", str(audit), OWN)], s1)
    (kwargs,) = spy.calls
    assert kwargs["accounting"] == AccountingViews() and kwargs["derived_root_labels"] == ()
    assert kwargs["own_context"] == OwnCampaignContext(current_campaign_id=OWN, own_record_stage=OwnRecordStage.ADMITTED)
    by_hand = RegistryView(registry_id=fx.REGISTRY_ID, chain_head=sup.H(records[-1]), records=tuple(
        RegistryRecordFact(seq=seq, kind=kind, campaign_id=record["campaign_id"], content_hash=sup.H(record), window_start_utc=record["window_start_utc"],
                           window_end_utc=record["window_end_utc"]) for seq, (record, kind) in enumerate(zip(records, (SourceKind.REGISTRY_RESERVATION, SourceKind.REGISTRY_ADMISSION,
                                                                                                                  SourceKind.REGISTRY_RESERVATION)))))
    assert kwargs["registry"] == by_hand                                                                       # vue écrite à la main, hashes indépendants
    direct = assemble_exposure_inventory(s1, registry=by_hand, accounting=AccountingViews(), own_context=OwnCampaignContext(OWN, OwnRecordStage.ADMITTED))
    assert spy.results[0].inventory_id == direct.inventory_id and spy.results[0].inventory_content_digest == direct.inventory_content_digest      # différentiel contre l'appel direct


@pytest.mark.parametrize("entries,expected", [
    ([], OwnRecordStage.NO_OWN_RECORDS), ([("R", OWN, *WN)], OwnRecordStage.RESERVED), ([("R", OWN, *WN), ("A", OWN, None, None)], OwnRecordStage.ADMITTED)])
def test_the_stage_without_a_claim_reaches_b4(tmp_path, monkeypatch, entries, expected):
    spy = SpyB4(monkeypatch)
    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    assess_roots(tmp_path, entries, [("camp", str(audit), OWN)], sup.interpret_campaigns([("camp", audit)]))
    assert spy.calls[0]["own_context"].own_record_stage is expected


# ── SG : étage RÉEL avec un Claim résolu (plan de split réel dans une racine RESULTS) ─────────────────────────────────────────────────────────

def claim_world(tmp_path, *, own_dir_claim=True, other_claim_for=None):
    """Racine de résultats portant le plan de split `plan-alpha` (final_holdout = W) ; campagne propre `CAMPAIGN_ID` (avec ou sans Claim) ; éventuellement une autre racine qui porte un Claim."""
    results = clean_results(tmp_path / "w")
    make_split(results, events=())
    own = tmp_path / "c" / CAMPAIGN_ID
    from tests.test_gate_v_exposure_interpreters import write_json
    write_json(own / "plan.json", {"campaign_id": CAMPAIGN_ID})
    if own_dir_claim:
        write_json(own / "final_holdout_access_claim.json", claim_record(CAMPAIGN_ID))
    roots = [results_root(results), campaign_root(own, "camp")]
    campaign_roots = [("camp", str(own), CAMPAIGN_ID)]
    if other_claim_for is not None:
        other = make_campaign(tmp_path / "o", claim=claim_record(other_claim_for), plan_campaign_id=OTHER_ID, name=OTHER_ID)
        roots.append(campaign_root(other, "other"))
        campaign_roots.append(("other", str(other), OTHER_ID))
    return b3_interpret(*roots), campaign_roots


R_ = lambda: ("R", CAMPAIGN_ID, *WN)       # noqa: E731
A_ = lambda: ("A", CAMPAIGN_ID, None, None)      # noqa: E731
C_ = lambda: ("C", CAMPAIGN_ID, None, None)      # noqa: E731


@pytest.mark.parametrize("entries,claim,expected", [
    ([], False, OwnRecordStage.NO_OWN_RECORDS), ([R_()], False, OwnRecordStage.RESERVED), ([R_(), A_()], False, OwnRecordStage.ADMITTED),
    ([R_(), A_()], True, OwnRecordStage.CLAIMED), ([R_(), A_(), C_()], True, OwnRecordStage.CONSUMED)])
def test_sg1_real_resolved_claim_five_pairs_reach_b4(tmp_path, monkeypatch, entries, claim, expected):
    spy = SpyB4(monkeypatch)
    s1, roots = claim_world(tmp_path, own_dir_claim=claim)
    assert (any(f.source_kind is SourceKind.FINAL_HOLDOUT_CLAIM and f.status.value == "RESOLVED" for f in s1.findings)) is claim            # anti-vacuité : le Claim est RÉSOLU
    assess_roots(tmp_path, entries, roots, s1, own=CAMPAIGN_ID)
    assert spy.calls[0]["own_context"].own_record_stage is expected


@pytest.mark.parametrize("entries,claim,detail", [
    ([R_()], True, "STAGE_RECORD_WITHOUT_PRIOR"), ([], True, "STAGE_RECORD_WITHOUT_PRIOR"), ([R_(), A_(), C_()], False, "STAGE_CONSUMED_WITHOUT_RECORD")])
def test_sg1_real_resolved_claim_refused_pairs(tmp_path, entries, claim, detail):
    s1, roots = claim_world(tmp_path, own_dir_claim=claim)
    registry = sup.new_registry(tmp_path, "registry")
    sup.populate(registry, sup.build_chain(entries))
    handle = ar.read(config(registry), own_campaign_id=CAMPAIGN_ID, window=WN)
    assert refused(ar.assess, handle, s1, own_campaign_id=CAMPAIGN_ID, window=WN, campaign_roots=tuple(roots), max_json_bytes=MAX_JSON) == ("STAGE_NOT_DERIVABLE", detail)


def test_sg6_a_resolved_claim_of_another_campaign_in_another_root_leaves_the_stage_unchanged(tmp_path, monkeypatch):
    spy = SpyB4(monkeypatch)
    s1, roots = claim_world(tmp_path, own_dir_claim=False, other_claim_for=OTHER_ID)
    assert any(f.source_id == "campaign.claim:other/final_holdout_access_claim.json" and f.campaign_id == OTHER_ID and f.status.value == "RESOLVED" for f in s1.findings)
    assess_roots(tmp_path, [R_()], roots, s1, own=CAMPAIGN_ID)
    assert spy.calls[0]["own_context"].own_record_stage is OwnRecordStage.RESERVED


def test_sg7_the_own_claim_found_in_another_root_is_refused(tmp_path):
    s1, roots = claim_world(tmp_path, own_dir_claim=False, other_claim_for=CAMPAIGN_ID)
    registry = sup.new_registry(tmp_path, "registry")
    sup.populate(registry, sup.build_chain([R_(), A_()]))
    handle = ar.read(config(registry), own_campaign_id=CAMPAIGN_ID, window=WN)
    assert refused(ar.assess, handle, s1, own_campaign_id=CAMPAIGN_ID, window=WN, campaign_roots=tuple(roots), max_json_bytes=MAX_JSON) == ("STAGE_NOT_DERIVABLE", "STAGE_RECORD_OUTSIDE_OWN_ROOT")


@pytest.mark.parametrize("label", ["a", "A" * 64, "camp-1_x", "0" + "z" * 63])
def test_h7_claim_source_id_has_the_frozen_form_for_boundary_labels(tmp_path, label):
    from tests.test_gate_v_exposure_interpreters import write_json
    results = clean_results(tmp_path / "w")
    make_split(results, events=())
    own = tmp_path / "c" / CAMPAIGN_ID
    write_json(own / "plan.json", {"campaign_id": CAMPAIGN_ID})
    write_json(own / "final_holdout_access_claim.json", claim_record(CAMPAIGN_ID))
    s1 = b3_interpret(results_root(results), campaign_root(own, label))
    assert [f.source_id for f in s1.findings if f.source_kind is SourceKind.FINAL_HOLDOUT_CLAIM] == [f"campaign.claim:{label}/final_holdout_access_claim.json"]
    assert ar.derive_stage(ar.CampaignState.ADMITTED, tuple(f for f in s1.findings if f.source_kind is SourceKind.FINAL_HOLDOUT_CLAIM), (), WN, CAMPAIGN_ID) is OwnRecordStage.CLAIMED


# ── B3 / B4 sur les 33 scénarios ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_h10_b4_equals_b3_on_all_33_scenarios_with_three_registry_montages(tmp_path):
    assert len(SCENARIOS) == 33
    complete_everywhere = {}
    for index, name in enumerate(sorted(SCENARIOS)):
        audit = realise(tmp_path / f"audit{index}", SCENARIOS[name])
        s1 = sup.interpret_campaigns([("camp", audit)])
        for montage, entries in (("empty", []), ("own_reserved", [("R", OWN, *WN)]), ("own_reserved_foreign_without_root", [("R", OWN, *WN), ("R", B, *EARLY)])):
            result = assess_roots(tmp_path / f"audit{index}", entries, [("camp", str(audit), OWN)], s1, name=f"reg_{montage}")
            assert not (result.b4_complete and not s1.complete), (name, montage)                                     # jamais B4 COMPLETE avec B3 INCOMPLETE
            assert result.b4_complete is s1.complete, (name, montage)                                                # égalité conditionnelle : le registre ne change rien ici
            complete_everywhere.setdefault(name, set()).add(result.b4_complete)
    assert {name for name, values in complete_everywhere.items() if values == {True}} == {"01-ready-initial", "15-exposure-empty-ready", "18-no-manifest-validations-empty"}


def test_b4_reasons_of_the_registry_are_separated_from_those_of_b3_and_capped_at_64(tmp_path, monkeypatch):
    audit = realise(tmp_path / "audit", SCENARIOS["02-wf-declared-directory-absent"])                       # B3 INCOMPLET
    s1 = sup.interpret_campaigns([("camp", audit)])
    assert not s1.complete and s1.incomplete_reasons

    def forged_view(count):
        facts = tuple(RegistryRecordFact(seq=i, kind=SourceKind.REGISTRY_RESERVATION, campaign_id=None, content_hash=fx.h(f"f{i}"), window_start_utc=None, window_end_utc=None)
                      for i in range(count))
        return RegistryView(registry_id="r", chain_head=None, records=facts), 0

    for count, outcome in ((1, "ok"), (64, "ok"), (65, "ASSEMBLY")):
        monkeypatch.setattr(ar, "_convert", lambda chain, count=count: forged_view(count))
        (tmp_path / f"n{count}").mkdir()
        registry = sup.new_registry(tmp_path / f"n{count}", "registry")
        handle = ar.read(config(registry), own_campaign_id=OWN, window=WN)
        kwargs = dict(own_campaign_id=OWN, window=WN, campaign_roots=(("camp", str(audit), OWN),), max_json_bytes=MAX_JSON)
        if outcome == "ASSEMBLY":
            assert refused(ar.assess, handle, s1, **kwargs) == ("B4_ASSEMBLY_REFUSED", "ASSEMBLY")
            continue
        result = ar.assess(handle, s1, **kwargs)
        assert len(result.b4_incomplete_reasons) == count and result.b4_incomplete_reasons == tuple(sorted(result.b4_incomplete_reasons))
        assert set(result.b4_incomplete_reasons).isdisjoint(s1.incomplete_reasons)                              # raisons de B3 NON recopiées ici
        assert all(reason.startswith("REGISTRY_RECORD_UNRESOLVED:registry.reservation:r/") for reason in result.b4_incomplete_reasons)
    assert not result.b4_complete


def test_a_derived_label_that_b3_did_not_scan_is_an_assembly_refusal(tmp_path, monkeypatch):
    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    monkeypatch.setattr(ar, "_derived_roots", lambda *a, **k: (("ghost", B),))
    registry = sup.new_registry(tmp_path, "registry")
    handle = ar.read(config(registry), own_campaign_id=OWN, window=WN)
    assert refused(ar.assess, handle, sup.interpret_campaigns([("camp", audit)]), own_campaign_id=OWN, window=WN, campaign_roots=(("camp", str(audit), OWN),),
                   max_json_bytes=MAX_JSON) == ("B4_ASSEMBLY_REFUSED", "ASSEMBLY")


# ── compare : précédence ordonnée, avec des empreintes forgées ───────────────────────────────────────────────────────────────────────────────────

def fake_snapshot(*, registry_id="r", genesis="a" * 32, instance="a" * 32, profile="SIMULATED_DURABLE", hashes=()):
    entries = tuple(types.SimpleNamespace(content_hash=h) for h in hashes)
    chain = types.SimpleNamespace(current_instance_id=instance, head_content_hash=hashes[-1] if hashes else "0" * 64, next_seq=len(hashes), entries=entries)
    identity = types.SimpleNamespace(registry_id=registry_id, instance_id=genesis, mode=types.SimpleNamespace(value="SYNTHETIC"), durability_profile=types.SimpleNamespace(value=profile))
    return types.SimpleNamespace(identity=identity, chain=chain)


def run_compare(monkeypatch, first, second):
    handle = ar.RegistryHandle(ar._TOKEN, first, ar._stamp(first), tuple(e.content_hash for e in first.chain.entries))
    monkeypatch.setattr(ar, "_read_snapshot", lambda config, prefix: second)
    return refused(ar.compare, handle, object())


H1, H2, H3, X = "1" * 64, "2" * 64, "3" * 64, "9" * 64


@pytest.mark.parametrize("first,second,expected", [
    (dict(hashes=(H1, H2)), dict(registry_id="other", hashes=(H1,)), "IDENTITY_CHANGED"),                     # identité ET troncature : l'identité décide
    (dict(hashes=(H1,)), dict(genesis="b" * 32, hashes=(H1, H2)), "IDENTITY_CHANGED"),
    (dict(hashes=(H1, H2)), dict(hashes=(H1,)), "DIVERGED"),                                                    # troncature
    (dict(hashes=(H1,)), dict(hashes=(X, H2)), "DIVERGED"),                                                     # préfixe modifié ET étendu : DIVERGED avant EXTENDED
    (dict(hashes=(H1,)), dict(instance="b" * 32, hashes=(X, H2)), "DIVERGED"),                                  # instance changée ET préfixe divergent : DIVERGED avant INSTANCE_CHANGED
    (dict(hashes=(H1,)), dict(instance="b" * 32, hashes=(H1, H2)), "INSTANCE_CHANGED"),                        # instance changée ET étendu : INSTANCE_CHANGED avant EXTENDED
    (dict(hashes=(H1,)), dict(hashes=(H1, H2)), "EXTENDED"),
])
def test_compare_rules_are_ordered(monkeypatch, first, second, expected):
    assert run_compare(monkeypatch, fake_snapshot(**first), fake_snapshot(**second)) == ("REGISTRY_CHAIN_HEAD_CHANGED", expected)


def test_compare_accepts_an_identical_second_read(monkeypatch):
    first = fake_snapshot(hashes=(H1, H2))
    handle = ar.RegistryHandle(ar._TOKEN, first, ar._stamp(first), (H1, H2))
    monkeypatch.setattr(ar, "_read_snapshot", lambda config, prefix: fake_snapshot(hashes=(H1, H2)))
    ar.compare(handle, object())


@pytest.mark.skipif(os.name != "nt", reason="la barrière POSIX_DIR_FSYNC n'est refusée qu'hors POSIX")
def test_cc5_a_profile_only_change_on_windows_is_a_prefixed_barrier_failure(tmp_path):
    root = sup.new_registry(tmp_path)
    cfg = config(root)
    handle = ar.read(cfg, own_campaign_id=OWN, window=WN)
    identity = {"registry_identity_version": store.IDENTITY_VERSION, "registry_id": fx.REGISTRY_ID, "instance_id": fx.INSTANCE_ID, "mode": "SYNTHETIC", "durability_profile": "POSIX_DIR_FSYNC"}
    (root / "identity.json").write_bytes(serialize_normative_json(identity))
    assert refused(ar.compare, handle, cfg) == ("REGISTRY_UNREADABLE", "R2:BARRIER_FAILED")


# ── Lecture : écarts de début, SLOT_NAME_MISMATCH, libération, bornes acceptées ─────────────────────────────────────────────────────────────────

def test_own_window_start_only_difference_is_refused_and_each_own_record_type_is_checked(tmp_path):
    registry = sup.new_registry(tmp_path)
    sup.populate(registry, sup.build_chain([("R", OWN, "2026-01-01T00:00:00.000001Z", WN[1])]))
    assert refused(ar.read, config(registry), own_campaign_id=OWN, window=WN) == ("WINDOW_MISMATCH", "OWN_RECORD_WINDOW")
    other = sup.new_registry(tmp_path, "other")
    sup.populate(other, sup.build_chain([("R", OWN, *WN), ("A", OWN, None, None), ("C", OWN, None, None)]))
    assert ar.read(config(other), own_campaign_id=OWN, window=WN) is not None
    assert refused(ar.read, config(other), own_campaign_id=OWN, window=("2026-01-01T00:00:00.000000Z", "2026-04-01T00:00:00.000001Z")) == ("WINDOW_MISMATCH", "OWN_RECORD_WINDOW")


def test_cv4_a_slot_whose_seq_differs_from_its_name_is_refused_and_no_identifier_is_inferred_from_names(tmp_path):
    registry = sup.new_registry(tmp_path)
    sup.put_slot(registry, 0, fx.reservation(5, sup.GENESIS, B, *EARLY))
    assert refused(ar.read, config(registry), own_campaign_id=OWN, window=WN) == ("REGISTRY_UNREADABLE", "SLOT_NAME_MISMATCH")


def test_cv1_conversion_locks_kind_campaign_and_window_per_record():
    import gate_v_registry_chain as chain_module
    records = sup.build_chain([("R", B, *EARLY), ("A", B, None, None), ("C", B, None, None)])
    verified = chain_module.verify_chain(records, registry_id=fx.REGISTRY_ID, genesis_instance_id=fx.INSTANCE_ID)
    view, _ = ar._convert(verified)
    assert [(f.seq, f.kind, f.campaign_id, f.window_start_utc, f.window_end_utc) for f in view.records] == [
        (0, SourceKind.REGISTRY_RESERVATION, B, *EARLY), (1, SourceKind.REGISTRY_ADMISSION, B, *EARLY), (2, SourceKind.CONSUMPTION, B, *EARLY)]


def test_rd9_the_snapshot_is_released_after_a_refusal_and_stamps_survive_on_a_real_chain(tmp_path, monkeypatch):
    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    registry = sup.new_registry(tmp_path, "registry")
    sup.populate(registry, sup.build_chain([("R", OWN, *WN), ("R", B, *EARLY)]))
    s1 = sup.interpret_campaigns([("camp", audit)])
    kwargs = dict(own_campaign_id=OWN, window=WN, campaign_roots=(("camp", str(audit), OWN),), max_json_bytes=MAX_JSON)
    handle = ar.read(config(registry), **{k: kwargs[k] for k in ("own_campaign_id", "window")})
    ar.assess(handle, s1, **kwargs)
    assert handle._state[0] is None and handle._state[1][6] == 2 and len(handle._state[2]) == 2
    failing = ar.read(config(registry), own_campaign_id=OWN, window=WN)
    monkeypatch.setattr(ar, "assemble_exposure_inventory", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
    assert refused(ar.assess, failing, s1, **kwargs) == ("B4_ASSEMBLY_REFUSED", "ASSEMBLY")
    assert failing._state[0] is None                                                                           # libérée aussi sur refus (finally)


def test_validate_config_accepted_boundaries(tmp_path):
    base = str(tmp_path / "reg")
    for slots, total in ((1, 1), (store.MAX_SLOTS, 1), (1, store.MAX_SLOTS * store.MAX_SLOT_BYTES)):
        assert ar.validate_config(ar.RegistryConfig(root_path=base, max_slots=slots, max_total_bytes=total), audit_root_paths=()) == 2 * (total + 4096 + 2)


# ── Store : bornes littérales, ordre de la validation, orphelin disparu pendant le listage ───────────────────────────────────────────────────────

def test_the_orphan_margin_and_the_default_ceilings_are_pinned_to_literals():
    assert store.MAX_ORPHAN_ENTRIES == 1024 and store.MAX_SLOTS == 100000 and store.MAX_SLOT_BYTES == 262144 and store.MAX_IDENTITY_BYTES == 4096 and store.LISTING_ATTEMPTS == 3


def test_admissions_cap_is_exactly_max_slots_plus_1024_in_literal_numbers(tmp_path):
    root = sup.new_registry(tmp_path)
    sup.put_orphans(root / "admissions", 1026)                                                                  # max_slots (2) + 1 024 = 1 026 entrées de toute nature : accepté
    assert store.read_registry(root, barrier=False, max_slots=2, max_total_bytes=100).chain.next_seq == 0
    sup.put_orphans(root / "admissions", 1)
    with pytest.raises(RegistryReadError) as caught:
        store.read_registry(root, barrier=False, max_slots=2, max_total_bytes=100)
    assert caught.value.failure is ReadFailure.TOO_MANY_SLOTS
    other = sup.new_registry(tmp_path, "other")
    sup.put_orphans(other, 1024)
    assert store.read_registry(other, barrier=False, max_slots=2, max_total_bytes=100).chain.next_seq == 0
    sup.put_orphans(other, 1)
    with pytest.raises(RegistryReadError):
        store.read_registry(other, barrier=False, max_slots=2, max_total_bytes=100)


@pytest.mark.parametrize("kwargs,exception", [
    ({"max_slots": 0, "max_total_bytes": 5.0}, TypeError), ({"max_slots": True, "max_total_bytes": 0}, TypeError), ({"max_slots": 100001, "max_total_bytes": "x"}, TypeError),
    ({"max_slots": 0, "max_total_bytes": 0}, ValueError), ({"max_slots": 100001, "max_total_bytes": 1}, ValueError)])
def test_st2_the_validation_steps_are_ordered_type_before_range_before_bound(tmp_path, kwargs, exception):
    with pytest.raises(exception):
        store.read_registry(tmp_path / "x", barrier=False, **kwargs)


def test_st4_an_orphan_that_vanishes_during_the_listing_is_still_counted(tmp_path, monkeypatch):
    root = sup.new_registry(tmp_path)
    admissions = root / "admissions"
    sup.put_orphans(admissions, 3 + store.MAX_ORPHAN_ENTRIES + 3)
    real = os.lstat

    def vanishing(path, *args, **kwargs):
        if os.path.dirname(str(path)) == str(admissions) and os.path.basename(str(path)).startswith(".registry.tmp."):
            raise FileNotFoundError(path)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", vanishing)
    with pytest.raises(RegistryReadError) as caught:
        store.read_registry(root, barrier=False, max_slots=3, max_total_bytes=1000)
    assert caught.value.failure is ReadFailure.TOO_MANY_SLOTS                                                    # compté AVANT `lstat` : les disparus comptent
    monkeypatch.setattr(os, "lstat", real)
    assert store.read_registry(root, barrier=False).chain.next_seq == 0                                          # chemin par défaut : jamais plafonné
