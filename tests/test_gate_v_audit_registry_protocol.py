"""N2-b1b, tranche T7 — INTÉGRATION dans `audit_campaign_exposure` (seam S-c) : requête, budget, séquence R1 < S1 < L3-A < assess < S2 < relecture < R2, refus typés, rapport (invariants 1 à 9),
absence d'écriture et d'autorité, graphe d'imports (groupes RQ, RD, RP, NW, GU de la note section 19.13).

Fixtures SYNTHÉTIQUES (`tmp_path`). Aucun A0, aucune admission, aucune écriture de registre par l'audit, aucune donnée de marché, aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gate_v_audit_protocol as ap
import gate_v_audit_registry as ar
import gate_v_k1s2_verifier as vf
import gate_v_registry_audit_support as sup
from gate_v_exposure_scan import scan_worst_case_read_bytes
from tests.gate_v_audit_protocol_support import PROTOCOL_LIMITS, campaign_spec, request_for, tree_digest
from tests.gate_v_exposure_support import LIMITS
from tests.gate_v_manifest_scenarios import CID, HL, SCENARIOS, realise

R = ap.RefusalCode
WN = sup.WN
EARLY = ("2025-01-01T00:00:00.000000Z", "2025-02-01T00:00:00.000000Z")
INSIDE = ("2026-02-01T00:00:00.000000Z", "2026-02-10T00:00:00.000000Z")
B = sup.foreign_id(0xB)
SOURCE = Path(ap.__file__).read_text(encoding="utf-8")
FIVE = ("CAMPAIGNS_OUTSIDE_REGISTRY", "TRIAL_ACCOUNTING", "DERIVED_ROOT_CONTENT_ATTRIBUTION", "REGISTRY_NOT_REAL_BOUND", "STAGE_CONSUMPTION_LINK_UNVERIFIED")
B1A_NOT_PROVEN = vf.NOT_PROVEN + ("SNAPSHOT_ATOMICITY", "CHRONOLOGY", "INDEPENDENT_RESCAN", "S0_RECOMPUTATION", "PLAN_SOURCES_AUTHENTICITY")
SCAN_BUDGET = 2 * scan_worst_case_read_bytes(LIMITS, HL)
MAX_TOTAL = 10 ** 7


def setup_world(tmp_path, entries, *, scenario="01-ready-initial", cfg_changes=None, name="registry"):
    audit = realise(tmp_path / "audit", SCENARIOS[scenario])
    root = sup.new_registry(tmp_path, name)
    sup.populate(root, sup.build_chain(entries))
    fields = dict(root_path=str(root), max_slots=1000, max_total_bytes=MAX_TOTAL)
    fields.update(cfg_changes or {})
    return audit, root, ar.RegistryConfig(**fields)


def request(audit, cfg, **changes):
    fields = dict(registry=cfg, protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=SCAN_BUDGET + 2 * (cfg.max_total_bytes + 4098)))
    fields.update(changes)
    return request_for(campaign_spec(audit), own=CID, **fields)


def refusal(report):
    assert report.receivability is ap.Receivability.REFUSED and len(report.refusals) == 1
    return report.refusals[0]


OWN_RESERVED = [("R", CID, *WN)]


# ── Mode sans registre : inchangé ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_without_a_registry_block_the_report_is_the_n2b1a_report(tmp_path):
    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    report = ap.audit_campaign_exposure(request_for(campaign_spec(audit), own=CID))
    assert report.receivability is ap.Receivability.RECEIVABLE
    assert report.b4_completeness is ap.Completeness.NOT_BUILT and report.b4_inventory is ap.Completeness.NOT_BUILT
    assert report.registry_coverage is ar.RegistryCoverage.NOT_ASSESSED and report.registry_id is None and report.trial_counters == () and report.derived_root_labels == ()
    assert report.registry_other_campaign_count is None and report.registry_uncovered_count is None and report.registry_uncovered_sample == () and report.b4_incomplete_reasons == ()
    assert not [b for b in report.blocks if b.code is ap.BlockCode.DERIVED_COVERAGE_PARTIAL]


def test_registry_does_not_alter_the_scan_projections(tmp_path):
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    plain = ap.audit_campaign_exposure(request_for(campaign_spec(audit), own=CID))
    with_registry = ap.audit_campaign_exposure(request(audit, cfg))
    assert (plain.facts_s1, plain.identity_s1, plain.facts_s2, plain.identity_s2) == (with_registry.facts_s1, with_registry.identity_s1, with_registry.facts_s2, with_registry.identity_s2)
    assert plain.b3_completeness is with_registry.b3_completeness and plain.incomplete_reasons == with_registry.incomplete_reasons


# ── Nominal avec registre ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_registry_audit_reports_three_distinct_dimensions_and_nothing_else(tmp_path):
    audit, root, cfg = setup_world(tmp_path, OWN_RESERVED + [("R", B, *EARLY)])
    report = ap.audit_campaign_exposure(request(audit, cfg))
    assert report.receivability is ap.Receivability.RECEIVABLE
    assert report.b3_completeness is ap.Completeness.COMPLETE and report.b4_completeness is ap.Completeness.COMPLETE
    assert report.registry_coverage is ar.RegistryCoverage.PARTIAL                                           # B4 COMPLETE et couverture PARTIAL : exposés tels quels
    assert (report.registry_other_campaign_count, report.registry_uncovered_count, report.registry_uncovered_sample) == (1, 1, (B,))
    partial = [b for b in report.blocks if b.code is ap.BlockCode.DERIVED_COVERAGE_PARTIAL]
    assert len(partial) == 1 and partial[0].root_label == "(registry)" and partial[0].detail == "UNCOVERED:1/1"
    assert report.registry_id == "synthetic-registry-1" and report.registry_slot_count == 2 and report.registry_rebind_count == 0
    assert report.registry_durability_profile == "SIMULATED_DURABLE" and report.b4_semantics_version == "gate_v_exposure_inventory_assembly_v1"
    assert [c.name for c in report.trial_counters] == ["research_runs", "strategies", "campaigns", "abandoned_reservations", "failed_ingestion_attempts", "void_commitments"]
    assert [c.value for c in report.trial_counters] == [None, None, 1, None, None, None]
    assert report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE and report.grants == () and report.persistence is ap.Persistence.NOT_PERSISTED
    assert report.e3j_prerequisites_unmet == ap.E3J_PREREQUISITES_UNMET and "REGISTRY_CHAIN_STRICT_READ" in report.e3j_prerequisites_unmet


def test_not_proven_is_constant_with_or_without_a_registry(tmp_path):
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    plain = ap.audit_campaign_exposure(request_for(campaign_spec(audit), own=CID))
    with_registry = ap.audit_campaign_exposure(request(audit, cfg))
    assert plain.not_proven == with_registry.not_proven == B1A_NOT_PROVEN + FIVE


def test_an_empty_registry_never_reads_as_global_completeness(tmp_path):
    audit, _root, cfg = setup_world(tmp_path, [])
    report = ap.audit_campaign_exposure(request(audit, cfg))
    assert report.b4_completeness is ap.Completeness.COMPLETE and report.registry_coverage is ar.RegistryCoverage.ALL_CHAIN_CAMPAIGNS_HAVE_ROOT
    assert report.registry_other_campaign_count == 0 and report.trial_counters[2].value == 0                  # le vide est lisible
    assert report.registry_durability_profile == "SIMULATED_DURABLE" and "REGISTRY_NOT_REAL_BOUND" in report.not_proven
    assert report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE


# ── RQ : requête, recouvrement, budget ────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def no_registry_read(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("lecture du registre avant un refus de requête")
    monkeypatch.setattr(ar, "read_registry", boom)


@pytest.mark.parametrize("hostile", [True, 0, "registry", {"root_path": "x"}, object()])
def test_rq1_a_hostile_registry_block_is_request_invalid_without_any_read(tmp_path, no_registry_read, hostile):
    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    defect = refusal(ap.audit_campaign_exposure(request_for(campaign_spec(audit), own=CID, registry=hostile)))
    assert (defect.code, defect.stage, defect.detail) == (R.REQUEST_INVALID, ap.Stage.REQUEST, "REGISTRY_CONFIG")


def test_rq1_a_subclass_of_the_config_is_refused(tmp_path, no_registry_read):
    class Sub(ar.RegistryConfig):
        pass

    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    defect = refusal(ap.audit_campaign_exposure(request_for(campaign_spec(audit), own=CID, registry=Sub(root_path=str(tmp_path / "r"), max_slots=1, max_total_bytes=1))))
    assert defect.detail == "REGISTRY_CONFIG"


@pytest.mark.parametrize("where", ["equal", "inside", "ancestor"])
def test_rq2_a_registry_overlapping_an_audit_root_is_refused_before_any_read(tmp_path, no_registry_read, where):
    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    path = {"equal": audit, "inside": audit / "registry", "ancestor": audit.parent}[where]
    cfg = ar.RegistryConfig(root_path=str(path), max_slots=10, max_total_bytes=1000)
    defect = refusal(ap.audit_campaign_exposure(request_for(campaign_spec(audit), own=CID, registry=cfg)))
    assert (defect.code, defect.detail) == (R.REQUEST_INVALID, "REGISTRY_ROOT_OVERLAP")


def test_rq2_a_sibling_with_a_common_text_prefix_is_not_an_overlap(tmp_path):
    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    sibling = Path(str(audit) + "2")
    cfg = ar.RegistryConfig(root_path=str(sibling), max_slots=10, max_total_bytes=1000)
    report = ap.audit_campaign_exposure(request(audit, cfg))
    assert refusal(report).code is R.REGISTRY_UNREADABLE                                # pas de recouvrement : la lecture échoue ensuite (racine absente)


def test_rq5_budget_boundary_is_exact_and_checked_before_any_access(tmp_path, no_registry_read):
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    needed = SCAN_BUDGET + 2 * (cfg.max_total_bytes + 4098)                                                    # oracle littéral : un seul groupe, aucune autre campagne
    over = ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=needed - 1)
    defect = refusal(ap.audit_campaign_exposure(request(audit, cfg, protocol_limits=over)))
    assert (defect.code, defect.stage, defect.detail) == (R.RESOURCE_BUDGET_EXCEEDED, ap.Stage.REQUEST, "REGISTRY_BUDGET")


def test_rq5_budget_exactly_enough_is_accepted(tmp_path):
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    exact = ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=SCAN_BUDGET + 2 * (cfg.max_total_bytes + 4098))
    assert ap.audit_campaign_exposure(request(audit, cfg, protocol_limits=exact)).receivability is ap.Receivability.RECEIVABLE


def test_rq5_candidate_roots_add_three_json_reads_each(tmp_path):
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    other = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"], name=B)
    specs = (campaign_spec(audit), campaign_spec(other, label="other"))
    needed = 2 * 1 * scan_worst_case_read_bytes(LIMITS, HL) + 2 * (cfg.max_total_bytes + 4098) + 3 * LIMITS.max_json_bytes * 1
    ok = request_for(*specs, own=CID, registry=cfg, protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=needed))
    assert ap.audit_campaign_exposure(ok).receivability is ap.Receivability.RECEIVABLE
    short = request_for(*specs, own=CID, registry=cfg, protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=needed - 1))
    assert refusal(ap.audit_campaign_exposure(short)).detail == "REGISTRY_BUDGET"


def test_rq5_without_registry_the_n2b1a_budget_is_unchanged(tmp_path):
    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    exact = ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=SCAN_BUDGET)
    assert ap.audit_campaign_exposure(request_for(campaign_spec(audit), own=CID, protocol_limits=exact)).receivability is ap.Receivability.RECEIVABLE
    short = ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=SCAN_BUDGET - 1)
    assert "majorant de lecture" in refusal(ap.audit_campaign_exposure(request_for(campaign_spec(audit), own=CID, protocol_limits=short))).detail


# ── RD : séquence et refus typés ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_rd8_the_call_order_is_r1_s1_assess_s2_r2_with_real_barriers(tmp_path, monkeypatch):
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    log = []
    for name in ("read", "assess", "compare"):
        real = getattr(ar, name)
        monkeypatch.setattr(ap.registry_audit, name, (lambda real, name: lambda *a, **k: (log.append(name), real(*a, **k))[1])(real, name))
    real_scan = ap.interpret_audit_roots_v6
    monkeypatch.setattr(ap, "interpret_audit_roots_v6", lambda *a, **k: (log.append("scan"), real_scan(*a, **k))[1])
    barrier_calls, real_read = [], ar.read_registry
    monkeypatch.setattr(ar, "read_registry", lambda path, **k: (barrier_calls.append(k["barrier"]), real_read(path, **k))[1])
    assert ap.audit_campaign_exposure(request(audit, cfg)).receivability is ap.Receivability.RECEIVABLE
    assert log == ["read", "scan", "assess", "scan", "compare"] and barrier_calls == [True, True]


@pytest.mark.parametrize("breaker,code,detail", [
    ("absent", R.REGISTRY_UNREADABLE, "ROOT_UNUSABLE"), ("gap", R.REGISTRY_UNREADABLE, "SLOT_GAP"), ("too_big", R.RESOURCE_BUDGET_EXCEEDED, "REGISTRY_TOO_LARGE"),
    ("own_window", R.WINDOW_MISMATCH, "OWN_RECORD_WINDOW")])
def test_rd_first_read_failures_refuse_before_any_scan(tmp_path, monkeypatch, breaker, code, detail):
    entries = OWN_RESERVED
    cfg_changes = None
    if breaker == "own_window":
        entries = [("R", CID, WN[0], "2026-03-01T00:00:00.000000Z")]
    audit, root, cfg = setup_world(tmp_path, entries, cfg_changes=cfg_changes)
    if breaker == "absent":
        cfg = dataclasses.replace(cfg, root_path=str(tmp_path / "absent"))
    elif breaker == "gap":
        (root / "admissions" / "admission_000000.json").rename(root / "admissions" / "admission_000002.json")
    elif breaker == "too_big":
        cfg = dataclasses.replace(cfg, max_slots=1, max_total_bytes=1)
        sup.put_slot(root, 1, None, raw=b"x")
    scans = []
    real_scan = ap.interpret_audit_roots_v6
    monkeypatch.setattr(ap, "interpret_audit_roots_v6", lambda *a, **k: (scans.append(1), real_scan(*a, **k))[1])
    report = ap.audit_campaign_exposure(request(audit, cfg))
    defect = refusal(report)
    assert (defect.code, defect.stage, defect.detail) == (code, ap.Stage.REGISTRY, detail) and not scans
    assert report.registry_id is None and report.b4_completeness is ap.Completeness.NOT_BUILT and report.blocks == () and report.roots == ()


def test_rd_a_corrupted_own_claim_refuses_the_stage_after_s1(tmp_path):
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    (audit / "final_holdout_access_claim.json").write_bytes(b"{")
    defect = refusal(ap.audit_campaign_exposure(request(audit, cfg)))
    assert (defect.code, defect.stage, defect.detail) == (R.STAGE_NOT_DERIVABLE, ap.Stage.REGISTRY, "STAGE_RECORD_UNRESOLVED")


def test_rd_assembly_failures_are_typed_and_unexpected_errors_stay_internal(tmp_path, monkeypatch):
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    monkeypatch.setattr(ar, "assemble_exposure_inventory", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
    assert refusal(ap.audit_campaign_exposure(request(audit, cfg))).code is R.B4_ASSEMBLY_REFUSED
    monkeypatch.setattr(ar, "assemble_exposure_inventory", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert refusal(ap.audit_campaign_exposure(request(audit, cfg))).code is R.AUDIT_INTERNAL_FAILURE


def test_cc_a_registry_extended_during_the_audit_invalidates_it_and_keeps_the_scan_evidence(tmp_path, monkeypatch):
    audit, root, cfg = setup_world(tmp_path, OWN_RESERVED)
    longer = sup.build_chain(OWN_RESERVED + [("R", B, *EARLY)])
    calls = []
    real_scan = ap.interpret_audit_roots_v6

    def scan_then_extend(*a, **k):
        result = real_scan(*a, **k)
        calls.append(1)
        if len(calls) == 2:                                                                                   # entre S2 et R2 : une modification RÉELLE du disque
            sup.put_slot(root, 1, longer[1])
        return result

    monkeypatch.setattr(ap, "interpret_audit_roots_v6", scan_then_extend)
    report = ap.audit_campaign_exposure(request(audit, cfg))
    defect = refusal(report)
    assert (defect.code, defect.stage, defect.detail) == (R.REGISTRY_CHAIN_HEAD_CHANGED, ap.Stage.REGISTRY, "EXTENDED")
    assert report.rescan is ap.RescanStatus.PROTOCOL_RESCAN_MATCHED and report.facts_s1 is not None and report.facts_s1 == report.facts_s2
    assert report.window_declared_source is ap.WindowDeclaredSource.OPERATOR_CONFIGURED and report.registry_id is None


# ── RP : invariants du rapport ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def good(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("n2b1b_rp")
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED + [("R", B, *EARLY)])
    return ap.audit_campaign_exposure(request(audit, cfg))


def test_rp1_each_report_invariant_clause_is_enforced_alone(good):
    counters = good.trial_counters
    block = ap.AuditBlock(ap.BlockCode.DERIVED_COVERAGE_PARTIAL, "(registry)", "UNCOVERED:1/1")
    cases = {
        "1a registry_id None with other fields": dict(registry_id=None),
        "1b NOT_BUILT with registry": dict(b4_completeness=ap.Completeness.NOT_BUILT),
        "1c NOT_ASSESSED with registry": dict(registry_coverage=ar.RegistryCoverage.NOT_ASSESSED),
        "1d counters empty with registry": dict(trial_counters=()),
        "1e slot count None with registry": dict(registry_slot_count=None),
        "2a B4 COMPLETE with B3 INCOMPLETE": dict(b3_completeness=ap.Completeness.INCOMPLETE, incomplete_reasons=("X:y",)),
        "2b B4 COMPLETE with reasons": dict(b4_incomplete_reasons=("X",)),
        "3a PARTIAL without block": dict(blocks=()),
        "3b block without PARTIAL": dict(registry_coverage=ar.RegistryCoverage.ALL_CHAIN_CAMPAIGNS_HAVE_ROOT, registry_uncovered_count=0, registry_uncovered_sample=(), derived_root_labels=("x",)),
        "3c uncovered above others": dict(registry_uncovered_count=2, registry_other_campaign_count=1, registry_uncovered_sample=(B, B + "x")),
        "4a sample too long": dict(registry_uncovered_sample=(B, sup.foreign_id(0xC))),
        "4b sample unsorted": dict(registry_other_campaign_count=2, registry_uncovered_count=2, registry_uncovered_sample=(sup.foreign_id(0xC), B)),
        "5b counters order altered": dict(trial_counters=(counters[1], counters[0]) + counters[2:]),
        "5c five counters": dict(trial_counters=counters[:5]),
        "6a reasons unsorted": dict(b3_completeness=ap.Completeness.INCOMPLETE, incomplete_reasons=("X:y",), b4_completeness=ap.Completeness.INCOMPLETE, b4_incomplete_reasons=("b", "a")),
        "6b reasons above 64": dict(b3_completeness=ap.Completeness.INCOMPLETE, incomplete_reasons=("X:y",), b4_completeness=ap.Completeness.INCOMPLETE,
                                    b4_incomplete_reasons=tuple(sorted(f"R{i:03d}" for i in range(65)))),
        "8 B4 INCOMPLETE with B3 COMPLETE and no reasons": dict(b4_completeness=ap.Completeness.INCOMPLETE),
        "9 labels plus uncovered differ from others": dict(derived_root_labels=("x",)),
    }
    for label, changes in cases.items():
        with pytest.raises(ValueError, match="champs de registre"):
            dataclasses.replace(good, **changes)
        assert label


def test_rp1_clause_7_a_refused_report_carries_no_registry_field(good):
    defect = ap.AuditDefect(R.REQUEST_INVALID, ap.Stage.REQUEST)
    with pytest.raises(ValueError):
        ap.AuditReport(ap.Receivability.REFUSED, refusals=(defect,), registry_id="x", b4_completeness=ap.Completeness.COMPLETE, registry_coverage=ar.RegistryCoverage.PARTIAL)
    with pytest.raises(ValueError):
        ap.AuditReport(ap.Receivability.REFUSED, refusals=(defect,), registry_slot_count=0)
    ap.AuditReport(ap.Receivability.REFUSED, refusals=(defect,))


def test_rp2_authority_constants_are_unchanged(good):
    assert good.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE and good.grants == () and good.grants_nothing and good.independent_rescan_required
    assert good.auxiliary_runs is ap.AuxiliaryRuns.UNQUALIFIED and good.s0_facts is ap.S0Facts.NOT_VERIFIED and good.persistence is ap.Persistence.NOT_PERSISTED
    assert good.window_provenance is ap.WindowProvenance.UNVERIFIED and good.not_proven == B1A_NOT_PROVEN + FIVE
    names = {f.name for f in dataclasses.fields(ap.AuditReport)}
    assert not {"absence_evidence", "grants", "not_proven", "persistence", "inventory_id", "inventory_content_digest"} & names


def test_the_report_exposes_no_aggregate_of_the_three_dimensions(good):
    members = {f.name for f in dataclasses.fields(ap.AuditReport)} | {name for name, value in inspect.getmembers(ap.AuditReport) if isinstance(value, property)}
    allowed = {"b3_completeness", "b4_completeness"}
    for name in members - allowed:
        assert not {"complete", "overall", "global", "all"} & set(name.split("_")), name
    assert "inventory_id" not in members and not any("inventory" in name for name in members - {"b4_inventory"})


def test_the_report_and_its_new_types_have_no_serialisation_api():
    for cls in (ap.AuditReport, ar.TrialCounter, ar.RegistryConfig, ar.RegistryAssessment):
        methods = {n for n, v in vars(cls).items() if inspect.isfunction(v) and not n.startswith("_")}
        assert not any(re.match(r"(to_|from_|canonical|serial)", n) for n in methods), (cls.__name__, methods)


# ── NW : aucune écriture, aucune autorité ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_nw_the_audit_writes_nothing_creates_no_a0_no_record_and_never_opens_market_data(tmp_path, monkeypatch):
    audit, root, cfg = setup_world(tmp_path, OWN_RESERVED + [("R", B, *EARLY)])
    sentinel = tmp_path / "nasdaq_3m.csv"
    sentinel.write_bytes(b"time,open\n")
    before = (tree_digest(audit), tree_digest(root), tree_digest(tmp_path / "audit"))
    seen = []
    real_open, real_scandir = os.open, os.scandir
    monkeypatch.setattr(os, "open", lambda path, *a, **k: (seen.append(str(path)), real_open(path, *a, **k))[1])
    monkeypatch.setattr(os, "scandir", lambda path=".", *a, **k: (seen.append(str(path)), real_scandir(path, *a, **k))[1])
    report = ap.audit_campaign_exposure(request(audit, cfg))
    monkeypatch.undo()
    assert report.receivability is ap.Receivability.RECEIVABLE
    assert (tree_digest(audit), tree_digest(root), tree_digest(tmp_path / "audit")) == before
    assert not any("nasdaq_3m" in path for path in seen) and sentinel.read_bytes() == b"time,open\n"
    assert not any("exposure_inventory" in p.name or "final_holdout_access_claim" in p.name for p in tmp_path.rglob("*"))


# ── GU : gardes de graphe d'imports et de noms ────────────────────────────────────────────────────────────────────────────────────────────────

def test_gu_the_protocol_reads_only_the_documented_attributes_of_the_adapter_and_names_no_write_primitive():
    tree = ast.parse(SOURCE)
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "registry_audit"}
    assert attributes <= {"validate_config", "read", "assess", "compare", "RegistryAuditRefused"}, attributes
    handle_uses = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "handle"]
    assert handle_uses == []                                                                                  # la poignée n'est qu'un argument, jamais lue
    adapter = Path(ar.__file__).read_text(encoding="utf-8")
    for forbidden in ("initialize_synthetic_registry", "publish_json_by_link", "publish_bytes_by_link", "save_exclusive", "save_atomic", "assemble_record"):
        assert forbidden not in SOURCE and forbidden not in adapter, forbidden


EXPECTED_GATE_MODULES = {"gate_v_audit_protocol", "gate_v_audit_window", "gate_v_campaign_plan_v2", "gate_v_exposure_interpreters", "gate_v_exposure_interpreters_v5",
                         "gate_v_exposure_interpreters_v6", "gate_v_exposure_scan", "gate_v_exposure_sources", "gate_v_final_holdout_claim", "gate_v_final_holdout_protocol",
                         "gate_v_frame_digest", "gate_v_k1s2_emptiness", "gate_v_k1s2_observations", "gate_v_k1s2_verifier", "gate_v_preregistration", "gate_v_run_evidence_models",
                         "gate_v_validation_policy",                                                         # base mesurée sur HEAD 47317a9 (17 modules)
                         "gate_v_audit_registry", "gate_v_registry_store", "gate_v_registry_chain", "gate_v_registry_model", "gate_v_exposure_inventory"}      # N2-b1b : exactement cinq


ROOT = Path(ap.__file__).parent


def _subprocess(code: str):
    out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=240, cwd=str(ROOT))
    assert out.returncode == 0, out.stderr[-800:]
    return out.stdout.strip()


def test_gu_importing_the_protocol_loads_exactly_the_expected_gate_modules():
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import gate_v_audit_protocol; print(sorted(m for m in sys.modules if m.startswith('gate_v_')))"
    assert set(eval(_subprocess(code))) == EXPECTED_GATE_MODULES


def test_gu_an_audit_with_a_registry_loads_no_additional_module_and_no_writer(tmp_path):
    audit, root, cfg = setup_world(tmp_path, OWN_RESERVED)
    code = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
import gate_v_audit_protocol as ap, gate_v_audit_registry as ar
from gate_v_exposure_scan import ScanLimits, HashLimits
limits = ScanLimits(max_roots=8, max_entries=2000, max_depth=8, max_json_bytes=1000000, max_total_read_bytes=8000000, max_json_depth=32, max_name_length=128, max_path_length=1024, max_attempts=1)
hl = HashLimits(max_hashed_file_bytes=65536, max_total_hashed_bytes=2000000, max_hashed_files=200)
spec = ap.AuditRootSpec(label='camp', path={str(audit)!r}, layout=__import__('gate_v_exposure_interpreters').RootLayout.CAMPAIGN_DIR, expected_name={CID!r})
request = ap.AuditRequest(own_campaign_id={CID!r}, roots=(spec,), limits=limits, hash_limits=hl, protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=10**12),
    window_start_utc='2026-01-01T00:00:00+00:00', window_end_utc='2026-04-01T00:00:00+00:00', window_declared_source=ap.WindowDeclaredSource.OPERATOR_CONFIGURED,
    registry=ar.RegistryConfig(root_path={cfg.root_path!r}, max_slots=1000, max_total_bytes=10000000))
report = ap.audit_campaign_exposure(request)
bad = [m for m in sys.modules if m.startswith(('gate_v_registry_append', 'gate_v_registry_views', 'gate_v_exposure_store', 'gate_v_inventory_preconditions', 'gate_v_exposure_declarations',
                                               'gate_v_final_holdout_claim_acquisition', 'gate_v_campaign_manifest'))]
print(report.receivability.value, sorted(bad), sorted(m for m in sys.modules if m.startswith('gate_v_')) == sorted({sorted(EXPECTED_GATE_MODULES)!r}))
"""
    assert _subprocess(code) == "RECEIVABLE [] True"


# ── Combinaison avec la provenance de W (N2-b1a) : registre ET window_source ─────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def world(tmp_path_factory):
    from tests.gate_v_audit_window_support import build_world
    return build_world(tmp_path_factory.mktemp("n2b1b_world"))


def _derived_setup(tmp_path, world, extra_entries=()):
    from tests.gate_v_audit_window_support import HOLDOUT_NORMALISED, derived_request, lay_out
    base = tmp_path / "aud"
    base.mkdir()
    layout = lay_out(base, world.plan, world.split_plan)
    root = sup.new_registry(tmp_path, "reg")
    sup.populate(root, sup.build_chain([("R", layout.campaign_id, *HOLDOUT_NORMALISED), *extra_entries]))
    cfg = ar.RegistryConfig(root_path=str(root), max_slots=1000, max_total_bytes=100_000)
    return layout, root, cfg, derived_request(layout, registry=cfg)


def test_registry_and_derived_window_combine_without_losing_either_provenance(tmp_path, world):
    layout, _root, _cfg, req = _derived_setup(tmp_path, world)
    report = ap.audit_campaign_exposure(req)
    assert report.receivability is ap.Receivability.RECEIVABLE, report.refusals
    assert report.window_declared_source is ap.WindowDeclaredSource.SPLIT_PLAN_REFERENCED and report.window_provenance is ap.WindowProvenance.SPLIT_PLAN_FINGERPRINT_MATCHED
    assert report.b4_completeness is ap.Completeness.COMPLETE and report.registry_id == "synthetic-registry-1" and report.registry_slot_count == 1


def test_cc7_a_plan_changed_and_a_registry_extended_at_the_same_point_report_the_window_first(tmp_path, world, monkeypatch):
    from tests.gate_v_audit_window_support import HOLDOUT_NORMALISED
    layout, root, _cfg, req = _derived_setup(tmp_path, world)
    longer = sup.build_chain([("R", layout.campaign_id, *HOLDOUT_NORMALISED), ("R", B, *EARLY)])
    calls = []
    real_scan = ap.interpret_audit_roots_v6

    def scan_then_change(*a, **k):
        result = real_scan(*a, **k)
        calls.append(1)
        if len(calls) == 2:
            layout.plan_file.write_bytes(layout.plan_file.read_bytes() + b"\n")
            sup.put_slot(root, 1, longer[1])
        return result

    monkeypatch.setattr(ap, "interpret_audit_roots_v6", scan_then_change)
    report = ap.audit_campaign_exposure(req)
    assert [d.code for d in report.refusals] == [R.WINDOW_SOURCE_CHANGED]                                  # l'ordre de b1a prime : la relecture de la fenêtre précède R2 (jamais comparé)
    assert report.registry_id is None and report.b4_completeness is ap.Completeness.NOT_BUILT
