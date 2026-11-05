"""N2-b1b — DURCISSEMENT (2ᵉ passe de la revue des tests) : B3 complet et B4 incomplet (adaptateur et bout en bout), chaîne avec REBIND, bascule statique → dérivé observée sur l'identité de l'inventaire,
précédence de `compare` sur l'identité (mode, profil, instance), rapport à exactement 64 raisons.

Fixtures SYNTHÉTIQUES (`tmp_path`). Aucun A0, aucune admission, aucune écriture de registre, aucune donnée de marché, aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_registry_fixtures as fx
import gate_v_audit_protocol as ap
import gate_v_audit_registry as ar
import gate_v_registry_audit_support as sup
from gate_v_exposure_inventory import RegistryRecordFact, RegistryView
from gate_v_final_holdout_protocol import SourceKind
from tests.gate_v_manifest_scenarios import CID, SCENARIOS, realise
from tests.test_gate_v_audit_registry_hardening import fake_snapshot, run_compare, H1, H2
from tests.test_gate_v_audit_registry_protocol import OWN_RESERVED, request, setup_world

WN = sup.WN
EARLY = ("2025-01-01T00:00:00.000000Z", "2025-02-01T00:00:00.000000Z")
B = sup.foreign_id(0xB)
OWN = CID
MAX_JSON = 1_000_000


def forged_unresolved_view(count):
    facts = tuple(RegistryRecordFact(seq=i, kind=SourceKind.REGISTRY_RESERVATION, campaign_id=None, content_hash=fx.h(f"f{i}"), window_start_utc=None, window_end_utc=None)
                  for i in range(count))
    return RegistryView(registry_id="r", chain_head=None, records=facts), 0


# ── B3 COMPLET et B4 INCOMPLET : jamais l'inverse, et la raison propre de B4 est rendue ──────────────────────────────────────────────────────────

def test_b3_complete_and_b4_incomplete_through_the_adapter(tmp_path, monkeypatch):
    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    s1 = sup.interpret_campaigns([("camp", audit)])
    assert s1.complete is True                                                                                   # B3 COMPLET (anti-vacuité)
    monkeypatch.setattr(ar, "_convert", lambda chain: forged_unresolved_view(2))
    registry = sup.new_registry(tmp_path, "registry")
    handle = ar.read(ar.RegistryConfig(root_path=str(registry), max_slots=100, max_total_bytes=10 ** 7), own_campaign_id=OWN, window=WN)
    result = ar.assess(handle, s1, own_campaign_id=OWN, window=WN, campaign_roots=(("camp", str(audit), OWN),), max_json_bytes=MAX_JSON)
    assert result.b4_complete is False
    assert result.b4_incomplete_reasons == ("REGISTRY_RECORD_UNRESOLVED:registry.reservation:r/000000", "REGISTRY_RECORD_UNRESOLVED:registry.reservation:r/000001")


def test_b3_complete_and_b4_incomplete_end_to_end_report(tmp_path, monkeypatch):
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    monkeypatch.setattr(ar, "_convert", lambda chain: forged_unresolved_view(1))
    report = ap.audit_campaign_exposure(request(audit, cfg))
    assert report.receivability is ap.Receivability.RECEIVABLE, report.refusals
    assert report.b3_completeness is ap.Completeness.COMPLETE and report.b4_completeness is ap.Completeness.INCOMPLETE
    assert report.b4_incomplete_reasons == ("REGISTRY_RECORD_UNRESOLVED:registry.reservation:r/000000",)
    assert report.b4_inventory is ap.Completeness.INCOMPLETE and report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE


def test_a_report_with_exactly_64_b4_reasons_is_valid_and_65_is_not(tmp_path, monkeypatch):
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    monkeypatch.setattr(ar, "_convert", lambda chain: forged_unresolved_view(64))
    report = ap.audit_campaign_exposure(request(audit, cfg))
    assert report.receivability is ap.Receivability.RECEIVABLE and len(report.b4_incomplete_reasons) == 64
    base = {f.name: getattr(report, f.name) for f in dataclasses.fields(ap.AuditReport)}
    with pytest.raises(ValueError, match="champs de registre"):
        ap.AuditReport(**{**base, "b4_incomplete_reasons": tuple(sorted(report.b4_incomplete_reasons + ("ZZZ",)))})
    with pytest.raises(ValueError, match="champs de registre"):
        ap.AuditReport(**{**base, "registry_uncovered_count": 1, "registry_other_campaign_count": 1, "registry_coverage": ar.RegistryCoverage.PARTIAL,
                          "registry_uncovered_sample": (B, B)})                                                  # doublon dans l'échantillon


# ── REBIND : compté, seq non contiguës acceptées par B4 ───────────────────────────────────────────────────────────────────────────────────────

def test_a_chain_with_a_rebind_reports_the_count_and_b4_accepts_the_seq_gap(tmp_path):
    audit, _root, cfg = setup_world(tmp_path, [("R", CID, *WN), ("B", "c" * 32, None, None), ("R", B, *EARLY)])
    report = ap.audit_campaign_exposure(request(audit, cfg))
    assert report.receivability is ap.Receivability.RECEIVABLE, report.refusals
    assert (report.registry_slot_count, report.registry_rebind_count, report.registry_other_campaign_count) == (3, 1, 1)
    assert report.trial_counters[2].value == 1 and report.b4_completeness is ap.Completeness.COMPLETE


# ── compare : l'identité (mode, profil) décide avant l'instance ; l'échec de lecture porte le préfixe R2 ─────────────────────────────────────────

@pytest.mark.parametrize("changes", [dict(profile="POSIX_DIR_FSYNC"), dict(genesis="b" * 32), dict(registry_id="other")])
def test_compare_identity_members_each_decide_alone(monkeypatch, changes):
    first, second = fake_snapshot(hashes=(H1,)), fake_snapshot(hashes=(H1,), **changes)
    assert run_compare(monkeypatch, first, second) == ("REGISTRY_CHAIN_HEAD_CHANGED", "IDENTITY_CHANGED")


def test_compare_identity_beats_instance_change(monkeypatch):
    assert run_compare(monkeypatch, fake_snapshot(hashes=(H1,)), fake_snapshot(registry_id="other", instance="b" * 32, hashes=(H1, H2))) == ("REGISTRY_CHAIN_HEAD_CHANGED", "IDENTITY_CHANGED")


def test_compare_mode_member_of_the_stamp_decides(monkeypatch):
    import types
    first, second = fake_snapshot(hashes=(H1,)), fake_snapshot(hashes=(H1,))
    second.identity.mode = types.SimpleNamespace(value="REAL")
    assert run_compare(monkeypatch, first, second) == ("REGISTRY_CHAIN_HEAD_CHANGED", "IDENTITY_CHANGED")


def test_compare_passes_the_r2_prefix_to_the_read(monkeypatch):
    first = fake_snapshot(hashes=(H1,))
    handle = ar.RegistryHandle(ar._TOKEN, first, ar._stamp(first), (H1,))
    seen = []
    monkeypatch.setattr(ar, "_read_snapshot", lambda config, prefix: (seen.append(prefix), first)[1])
    ar.compare(handle, object())
    assert seen == ["R2:"]
