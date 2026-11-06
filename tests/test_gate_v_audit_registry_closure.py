"""N2-b1b — CLÔTURE des écarts (mission « final hardening ») : détail `READ_ERROR` retiré, jonctions Windows et noms 8.3 (RQ3), plan V2 qui grossit pendant la séquence (DR14), anciens A0 (NW4), ordre de
`scandir` forcé (ST1c), lien Claim ↔ CONSUMPTION non vérifié (SG9 / H11), plus les défauts de test restants (DR6, CC8, `_stage`, GU1, doublon d'échantillon, SG8).

Fixtures SYNTHÉTIQUES dans `tmp_path` (basetemp sur D:) ; les jonctions ne sont créées que sous `tmp_path`. Aucun A0 réel, aucune admission, aucune écriture de registre par l'audit, aucune donnée de marché,
aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_registry_fixtures as fx
import gate_v_audit_protocol as ap
import gate_v_audit_registry as ar
import gate_v_registry_audit_support as sup
import gate_v_registry_chain as chain_module
import gate_v_registry_model as model
import gate_v_registry_store as store
from gate_v_exposure_inventory import AccountingViews, RegistryRecordFact, RegistryView, assemble_exposure_inventory
from gate_v_final_holdout_protocol import OwnCampaignContext, OwnRecordStage, SourceKind
from gate_v_registry_store import ReadFailure, RegistryReadError
from tests.gate_v_audit_protocol_support import campaign_spec, request_for
from tests.gate_v_manifest_scenarios import CID, SCENARIOS, realise
from tests.test_gate_v_audit_registry_derived import audit, entries as derived_entries, run as derived_run, world        # noqa: F401  (fixtures importées)
from tests.test_gate_v_audit_registry_hardening import (A_, C_, CAMPAIGN_ID, R_, SpyB4, assess_roots, claim_world, config, refused)
from tests.test_gate_v_audit_registry_protocol import OWN_RESERVED, request, setup_world
from tests.test_gate_v_exposure_interpreters import claim_record

WN = sup.WN
EARLY = ("2025-01-01T00:00:00.000000Z", "2025-02-01T00:00:00.000000Z")
B = sup.foreign_id(0xB)
OWN = CID
MAX_JSON = 1_000_000
R = ap.RefusalCode
ADAPTER_SOURCE = Path(ar.__file__).read_text(encoding="utf-8")


# ── A : le détail `READ_ERROR` n'existe plus ; une erreur de validation du store n'est pas un échec de lecture ─────────────────────────────────

def test_a_store_validation_error_is_not_converted_into_a_read_failure(tmp_path, monkeypatch):
    root = sup.new_registry(tmp_path)
    monkeypatch.setattr(store, "MAX_SLOTS", 5)                                                                   # constantes du store et de l'adaptateur divergent : incohérence, pas un registre illisible
    with pytest.raises(ValueError):
        ar.read(config(root, max_slots=100), own_campaign_id=OWN, window=WN)


def test_a_store_validation_error_ends_as_a_typed_internal_failure_in_the_protocol(tmp_path, monkeypatch):
    audit_dir, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    monkeypatch.setattr(store, "MAX_SLOTS", 5)
    report = ap.audit_campaign_exposure(request(audit_dir, cfg))
    assert report.receivability is ap.Receivability.REFUSED and len(report.refusals) == 1
    defect = report.refusals[0]
    assert (defect.code, defect.stage, defect.detail) == (R.AUDIT_INTERNAL_FAILURE, ap.Stage.PROTOCOL, "ValueError")
    assert report.registry_id is None and report.b4_completeness is ap.Completeness.NOT_BUILT


def _emitted_detail_pieces():
    """Constantes de texte transmises comme détail à `_refuse` / `RegistryAuditRefused` dans le source de l'adaptateur (extraites de l'AST, jamais écrites à la main)."""
    pieces = set()
    for node in ast.walk(ast.parse(ADAPTER_SOURCE)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None)
        if name not in {"_refuse", "RegistryAuditRefused", "refuse"} or len(node.args) < (1 if name == "refuse" else 2):
            continue
        for part in ast.walk(node.args[0 if name == "refuse" else 1]):
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                pieces.add(part.value)
    return pieces


APPROVED_DETAILS = {"REGISTRY_CONFIG", "REGISTRY_ROOT_OVERLAP", "REGISTRY_TOO_LARGE", "OWN_RECORD_WINDOW", "FACT_CONSTRUCTION", "ASSEMBLY", "IDENTITY_CHANGED", "DIVERGED", "INSTANCE_CHANGED",
                    "EXTENDED", "STAGE_RECORD_MULTIPLE", "STAGE_RECORD_UNRESOLVED", "STAGE_RECORD_OTHER_CAMPAIGN", "STAGE_RECORD_WINDOW", "STAGE_RECORD_OUTSIDE_OWN_ROOT",
                    "STAGE_RECORD_WITHOUT_PRIOR", "STAGE_CONSUMED_WITHOUT_RECORD", "R2:", "CHAIN:", "@"}
FORBIDDEN_SUBSTRINGS = ("FRESH", "NO_OVERLAP", "ADMIT", "ADMISSION", "CLAIM", "AUTHORI", "ABSENCE_ESTABLISHED", "EXCLUSION")
FORBIDDEN_TOKENS = {"PASS", "OK", "VALID", "CLEAN", "CLEARED", "ALLOWED", "GRANTED", "ACCESS"}


def test_gu1_every_detail_the_adapter_can_emit_belongs_to_the_approved_closed_set():
    pieces = _emitted_detail_pieces()
    assert pieces and "READ_ERROR" not in ADAPTER_SOURCE
    assert {"STAGE_RECORD_MULTIPLE", "STAGE_RECORD_UNRESOLVED", "STAGE_RECORD_OTHER_CAMPAIGN", "STAGE_RECORD_WINDOW", "STAGE_RECORD_OUTSIDE_OWN_ROOT", "STAGE_RECORD_WITHOUT_PRIOR",
            "STAGE_CONSUMED_WITHOUT_RECORD", "FACT_CONSTRUCTION", "ASSEMBLY", "OWN_RECORD_WINDOW"} <= pieces                                      # témoin de non-vacuité : les sept détails d'étage sont extraits
    assert pieces <= APPROVED_DETAILS, pieces - APPROVED_DETAILS
    for detail in pieces | {f"CHAIN:{code.value}@3" for code in chain_module.RegistryRefusalCode} | {f.value for f in ReadFailure}:
        upper = detail.upper()
        assert not any(bad in upper for bad in FORBIDDEN_SUBSTRINGS) and not FORBIDDEN_TOKENS & set(upper.replace(":", "_").replace("@", "_").split("_")), detail


# ── B : RQ3 — jonctions Windows et noms 8.3 ──────────────────────────────────────────────────────────────────────────────────────────────────────

windows_only = pytest.mark.skipif(os.name != "nt", reason="jonctions NTFS : Windows seulement (aucun privilège requis pour `_winapi.CreateJunction`, vérifié)")


def junction(target: Path, link: Path) -> None:
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


@windows_only
def test_rq3_a_registry_root_that_is_itself_a_junction_is_refused(tmp_path):
    real = sup.new_registry(tmp_path, "real")
    junction(real, tmp_path / "link")
    assert refused(ar.read, config(tmp_path / "link"), own_campaign_id=OWN, window=WN) == ("REGISTRY_UNREADABLE", "ROOT_UNUSABLE")


@windows_only
def test_rq3_a_junction_in_a_parent_component_hides_the_overlap_from_the_config_guard_but_never_silently(tmp_path):
    """Limite consignée (T24) : le garde de recouvrement travaille sans accès disque et ne suit pas les jonctions d'un parent. Le registre est ici PHYSIQUEMENT dans la racine d'audit ; l'audit ne
    peut pas rendre ce montage « complet » (B2 voit une entrée inconnue)."""
    audit_dir = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    witness = ap.audit_campaign_exposure(request_for(campaign_spec(audit_dir), own=CID))
    assert witness.b3_completeness is ap.Completeness.COMPLETE                                                   # témoin : sans le registre dans la racine, B3 est COMPLET
    sup.new_registry(audit_dir, "reg")                                                                           # registre physiquement dans la racine d'audit
    junction(audit_dir, tmp_path / "alias")
    cfg = ar.RegistryConfig(root_path=str(tmp_path / "alias" / "reg"), max_slots=100, max_total_bytes=10 ** 7)
    assert ar.validate_config(cfg, audit_root_paths=(str(audit_dir),)) > 0                                       # non vu par le garde textuel (caractérisation)
    report = ap.audit_campaign_exposure(request(audit_dir, cfg))
    assert report.receivability is ap.Receivability.REFUSED or report.b3_completeness is ap.Completeness.INCOMPLETE
    assert not (report.b3_completeness is ap.Completeness.COMPLETE and report.b4_completeness is ap.Completeness.COMPLETE)


def _short_name(path: Path):
    import ctypes
    buffer = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 1024)
    return buffer.value


@windows_only
def test_rq3_8dot3_names_hide_the_overlap_when_the_volume_generates_them(tmp_path):
    audit_dir = realise(tmp_path / "a_long_directory_name_for_short_names", SCENARIOS["01-ready-initial"])
    short = _short_name(audit_dir)
    if short.lower() == str(audit_dir).lower():
        pytest.skip("noms 8.3 désactivés sur ce volume (`GetShortPathNameW` renvoie le nom long) : preuve technique du blocage, cas NON validé ici")
    cfg = ar.RegistryConfig(root_path=str(Path(short) / "reg"), max_slots=100, max_total_bytes=10 ** 7)
    assert ar.validate_config(cfg, audit_root_paths=(str(audit_dir),)) > 0                                       # le nom court n'est pas reconnu comme recouvrant (caractérisation)


@pytest.mark.parametrize("prefix", ["\\\\?\\", "\\\\.\\", "//?/", "//./", "\\\\?\\UNC\\", "\\/?\\", "/\\?/", "//?\\", "\\\\.//"])      # formes littérales ET à barres mélangées
def test_rq3_windows_extended_path_prefixes_are_refused_without_any_disk_access(prefix):
    """Les racines d'audit refusent déjà ces préfixes (scanner) : le garde de recouvrement par composantes ne doit pas les laisser passer pour un autre lecteur."""
    from unittest import mock

    def boom(*args, **kwargs):
        raise AssertionError("accès disque")

    cfg = ar.RegistryConfig(root_path=prefix + "C:\\registry", max_slots=10, max_total_bytes=1000)
    with mock.patch.multiple(os, lstat=boom, scandir=boom, open=boom, stat=boom):                           # restaurés dès la sortie : le rapport d'échec de pytest utilise `os`
        with pytest.raises(ar.RegistryAuditRefused) as caught:
            ar.validate_config(cfg, audit_root_paths=())
    assert (caught.value.code, caught.value.detail) == ("REQUEST_INVALID", "REGISTRY_CONFIG")


# ── C : DR14 — plan V2 modifié ou agrandi pendant la séquence ────────────────────────────────────────────────────────────────────────────────────

def _protocol_request(tmp_path, audit):
    root = sup.new_registry(tmp_path, "reg")
    sup.populate(root, sup.build_chain([("R", audit.a, *WN), ("R", audit.b, *EARLY)]))
    cfg = ar.RegistryConfig(root_path=str(root), max_slots=1000, max_total_bytes=100_000)
    return request_for(campaign_spec(audit.path_a, label="own"), campaign_spec(audit.path_b, label="b"), own=audit.a, registry=cfg,
                       protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=10 ** 12))


def test_dr14_the_untouched_candidate_plan_is_the_baseline(tmp_path, audit):
    report = ap.audit_campaign_exposure(_protocol_request(tmp_path, audit))
    assert report.receivability is ap.Receivability.RECEIVABLE, report.refusals
    assert report.derived_root_labels == ("b",) and report.registry_coverage is ar.RegistryCoverage.ALL_CHAIN_CAMPAIGNS_HAVE_ROOT


def test_dr14_a_candidate_plan_enlarged_after_the_first_scan_and_kept_is_a_rescan_drift(tmp_path, audit, monkeypatch):
    plan_file = audit.path_b / "plan.json"
    request_ = _protocol_request(tmp_path, audit)
    calls, real = [], ap.interpret_audit_roots_v6

    def scan_then_enlarge(*a, **k):
        result = real(*a, **k)
        calls.append(1)
        if len(calls) == 1:
            plan_file.write_bytes(plan_file.read_bytes() + b"\n" * 4096)
        return result

    monkeypatch.setattr(ap, "interpret_audit_roots_v6", scan_then_enlarge)
    report = ap.audit_campaign_exposure(request_)
    assert [d.code for d in report.refusals] == [R.RESCAN_FACT_DRIFT] and report.registry_id is None            # la modification qui persiste jusqu'à S2 est détectée


def _transient(tmp_path, audit, monkeypatch, *, restore_mtime):
    plan_file = audit.path_b / "plan.json"
    original, info = plan_file.read_bytes(), os.stat(plan_file)
    request_ = _protocol_request(tmp_path, audit)
    calls, real = [], ap.interpret_audit_roots_v6

    def transient(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            plan_file.write_bytes(original)                                                                      # restauré AVANT le second scan
            if restore_mtime:
                os.utime(plan_file, ns=(info.st_atime_ns, info.st_mtime_ns))
        result = real(*a, **k)
        if len(calls) == 1:
            plan_file.write_bytes(original + b"\n" * 4096)                                                       # modifié APRÈS le premier scan (avant `assess`)
        return result

    monkeypatch.setattr(ap, "interpret_audit_roots_v6", transient)
    return ap.audit_campaign_exposure(request_)


def test_dr14_a_transient_change_restored_by_content_is_still_caught_by_the_identity_projection(tmp_path, audit, monkeypatch):
    """Les octets sont revenus à l'identique, mais la projection d'identité I (mtime, inode) du second scan diffère : refus. C'est une détection par métadonnées, pas un instantané."""
    report = _transient(tmp_path, audit, monkeypatch, restore_mtime=False)
    assert [d.code for d in report.refusals] == [R.RESCAN_IDENTITY_DRIFT] and report.registry_id is None


def test_dr14_a_transient_change_that_also_restores_the_mtime_is_not_detected_and_leaves_the_root_static(tmp_path, audit, monkeypatch):
    """Limite consignée (T18, ABA) : ce n'est PAS un instantané atomique. Si même la date de modification est restaurée, l'audit reste recevable ; la racine candidate est traitée comme non
    attribuable (jamais dérivée)."""
    report = _transient(tmp_path, audit, monkeypatch, restore_mtime=True)
    assert report.receivability is ap.Receivability.RECEIVABLE, report.refusals
    assert report.derived_root_labels == () and report.registry_coverage is ar.RegistryCoverage.PARTIAL and report.registry_uncovered_sample == (audit.b,)
    assert "SNAPSHOT_ATOMICITY" in report.not_proven and report.window_provenance is ap.WindowProvenance.UNVERIFIED


# ── D : NW4 — anciens A0 : lus par le scan seulement, jamais requalifiés ─────────────────────────────────────────────────────────────────────────

def _old_a0(directory: Path, *, claimed_stage="CLAIMED", other_inventory="ab" * 32):
    import json
    exposure = directory / "exposure"
    exposure.mkdir(exist_ok=True)
    path = exposure / f"inventory_{'1' * 64}.json"
    path.write_bytes(json.dumps({"semantics_version": "gate_v_exposure_inventory_assembly_v1", "inventory_id": other_inventory, "own_record_stage": claimed_stage,
                                 "registry_chain_head": "c" * 64, "trial_accounting": {"campaigns": 99}}).encode("utf-8"))
    return path


def test_nw4_an_old_a0_is_read_by_the_scans_only_and_never_reinterpreted(tmp_path, monkeypatch):
    spy = SpyB4(monkeypatch)
    audit_dir = realise(tmp_path / "q", SCENARIOS["01-ready-initial"])
    a0 = _old_a0(audit_dir)
    before = (a0.read_bytes(), a0.stat().st_mtime_ns)
    opens, real_open = [], os.open
    monkeypatch.setattr(os, "open", lambda path, *args, **kwargs: (opens.append(str(path)), real_open(path, *args, **kwargs))[1])
    without = ap.audit_campaign_exposure(request_for(campaign_spec(audit_dir), own=CID))                          # mode sans registre, même dossier
    opens_without = [p for p in opens if p.endswith(a0.name)]
    opens.clear()
    with_registry = ap.audit_campaign_exposure(_registry_request(tmp_path / "w2", audit_dir))
    opens_with = [p for p in opens if p.endswith(a0.name)]
    monkeypatch.undo()
    assert without.receivability is with_registry.receivability is ap.Receivability.RECEIVABLE
    assert opens_without and len(opens_with) == len(opens_without)                                               # l'A0 n'est ouvert que par les scans : ni l'adaptateur ni le protocole n'ajoutent une lecture
    assert (with_registry.b3_completeness, with_registry.incomplete_reasons) == (without.b3_completeness, without.incomplete_reasons)      # B3 le traite comme avant, avec ou sans registre
    assert (with_registry.facts_s1, with_registry.identity_s1, with_registry.facts_s2, with_registry.identity_s2) == (without.facts_s1, without.identity_s1, without.facts_s2, without.identity_s2)
    assert [call["own_context"].own_record_stage for call in spy.calls] == [OwnRecordStage.RESERVED]            # l'étage vient du registre, jamais de l'A0 qui prétend « CLAIMED »
    assert with_registry.trial_counters[2].value == 0                                                            # « campaigns: 99 » de l'A0 n'est jamais repris
    assert (a0.read_bytes(), a0.stat().st_mtime_ns) == before
    for text in (repr(with_registry.registry_id), repr(with_registry.registry_chain_head), repr(with_registry.b4_incomplete_reasons), repr(with_registry.trial_counters),
                 repr(with_registry.derived_root_labels), repr(with_registry.trial_counter_reasons)):
        assert "ab" * 32 not in text and "c" * 64 not in text                                                    # l'identifiant et la tête cités par l'A0 n'apparaissent nulle part


def _registry_request(base: Path, audit_dir: Path):
    base.mkdir(parents=True, exist_ok=True)
    root = sup.new_registry(base, "registry")
    sup.populate(root, sup.build_chain(OWN_RESERVED))
    cfg = ar.RegistryConfig(root_path=str(root), max_slots=1000, max_total_bytes=10 ** 7)
    return request(audit_dir, cfg)


# ── E : ST1c — ordre de `scandir` forcé, déterministe ───────────────────────────────────────────────────────────────────────────────────────────

class ForcedScan:
    def __init__(self, entries):
        self.entries = entries

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self.entries)


SCAN_CALLS = []

ORDERS = {"ascending": lambda items: sorted(items, key=lambda e: e.name), "descending": lambda items: sorted(items, key=lambda e: e.name, reverse=True),
          "rotated": lambda items: (lambda s: s[len(s) // 2:] + s[:len(s) // 2])(sorted(items, key=lambda e: e.name)),
          "shuffled_seed_7": lambda items: random.Random(7).sample(sorted(items, key=lambda e: e.name), len(items))}


@pytest.fixture(params=sorted(ORDERS))
def forced_order(request, monkeypatch):
    real, reorder = os.scandir, ORDERS[request.param]

    SCAN_CALLS.clear()

    def scandir(path="."):
        SCAN_CALLS.append(str(path))
        with real(path) as iterator:
            entries = list(iterator)
        return ForcedScan(reorder(entries))

    monkeypatch.setattr(os, "scandir", scandir)
    return request.param


def failure_of(root, **kwargs):
    with pytest.raises(RegistryReadError) as caught:
        store.read_registry(root, barrier=False, **kwargs)
    return caught.value.failure


def test_st1c_the_entry_cap_wins_over_an_unknown_entry_in_every_order(tmp_path, forced_order):
    root = sup.new_registry(tmp_path)
    for index in range(3 + store.MAX_ORPHAN_ENTRIES + 2):
        (root / "admissions" / f"junk_{index:05d}.txt").write_bytes(b"x")
    assert failure_of(root, max_slots=3, max_total_bytes=1000) is ReadFailure.TOO_MANY_SLOTS
    assert SCAN_CALLS                                                                                            # anti-vacuité : l'énumération forcée est bien celle utilisée


def test_st1c_an_unknown_entry_wins_over_the_slot_count_in_every_order(tmp_path, forced_order):
    root = sup.new_registry(tmp_path)
    for seq in range(4):
        (root / "admissions" / model.slot_file_name(seq)).write_bytes(b"x")
    (root / "admissions" / "notes.txt").write_bytes(b"x")
    assert failure_of(root, max_slots=3, max_total_bytes=1000) is ReadFailure.UNKNOWN_ENTRY
    assert SCAN_CALLS


def test_st1c_gap_orphan_directory_and_healthy_chain_are_order_independent(tmp_path, forced_order):
    records = sup.three_records()
    gap = sup.new_registry(tmp_path, "gap")
    sup.put_slot(gap, 0, records[0])
    sup.put_slot(gap, 2, records[2])
    assert failure_of(gap, max_slots=10, max_total_bytes=10 ** 6) is ReadFailure.SLOT_GAP
    directory = sup.new_registry(tmp_path, "dir")
    sup.populate(directory, records)
    (directory / "admissions" / sup.orphan_name()).mkdir()
    assert failure_of(directory, max_slots=10, max_total_bytes=10 ** 6) is ReadFailure.NOT_REGULAR
    healthy = sup.new_registry(tmp_path, "healthy")
    sup.populate(healthy, records)
    limited = store.read_registry(healthy, barrier=False, max_slots=10, max_total_bytes=10 ** 6)
    default = store.read_registry(healthy, barrier=False)
    assert limited.chain.head_content_hash == default.chain.head_content_hash == sup.H(records[-1]) and limited.chain.next_seq == 3
    assert SCAN_CALLS


def test_st1c_the_default_path_is_never_capped_in_any_order(tmp_path, forced_order):
    root = sup.new_registry(tmp_path)
    sup.put_orphans(root / "admissions", store.MAX_ORPHAN_ENTRIES + 6)
    assert store.read_registry(root, barrier=False).chain.next_seq == 0


# ── F : SG9 / H11 — la liaison Claim ↔ CONSUMPTION n'est PAS vérifiée ───────────────────────────────────────────────────────────────────────────

def _consumed_chain(claim_overrides):
    records = sup.build_chain([R_(), A_()])
    consumption = fx.consumption(2, sup.H(records[-1]), records[1], sup.H(records[1]), **claim_overrides)
    return records + [consumption]


def test_sg9_a_consumption_that_cites_another_or_the_same_claim_gives_the_same_stage_and_identity(tmp_path, monkeypatch):
    spy = SpyB4(monkeypatch)
    s1, roots = claim_world(tmp_path, own_dir_claim=True)
    observed = claim_record(CAMPAIGN_ID)
    variants = {"unrelated": {}, "matching": {"claim_id": observed["claim_id"], "claim_content_hash": observed["claim_content_hash"]}}
    for name, overrides in variants.items():
        records = _consumed_chain(overrides)
        assert (records[2]["claim_id"] == observed["claim_id"]) is (name == "matching")                         # anti-vacuité : les deux variantes diffèrent bien
        registry = sup.new_registry(tmp_path, f"registry_{name}")
        sup.populate(registry, records)
        handle = ar.read(config(registry), own_campaign_id=CAMPAIGN_ID, window=WN)
        result = ar.assess(handle, s1, own_campaign_id=CAMPAIGN_ID, window=WN, campaign_roots=tuple(roots), max_json_bytes=MAX_JSON)
        assert result.b4_complete is s1.complete
    assert [call["own_context"].own_record_stage for call in spy.calls] == [OwnRecordStage.CONSUMED, OwnRecordStage.CONSUMED]
    unrelated, matching = spy.results
    assert unrelated.inventory_id == matching.inventory_id                                                      # le contenu du lien n'entre ni dans l'étage ni dans l'identité : non vérifié


def test_sg9_the_adapter_never_reads_the_claim_link_fields_and_the_report_says_so():
    assert "claim_id" not in ADAPTER_SOURCE and "claim_content_hash" not in ADAPTER_SOURCE
    assert "STAGE_CONSUMPTION_LINK_UNVERIFIED" in ap._NOT_PROVEN and ap._NOT_PROVEN[-1] == "STAGE_CONSUMPTION_LINK_UNVERIFIED"


# ── Défauts de test restants ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("variant,reason", [("missing", "MISSING_REQUIRED:b/plan.json"), ("another_campaigns_plan", "INFORMATIVE_UNRESOLVED:b/plan.json"),
                                            ("garbage", "INFORMATIVE_UNRESOLVED:b/plan.json"), ("bom", "INFORMATIVE_UNRESOLVED:b/plan.json")])
def test_dr6_anchor_variants_carry_the_measured_b3_reasons_and_stay_static(tmp_path, audit, variant, reason):
    plan_file = audit.path_b / "plan.json"
    if variant == "missing":
        plan_file.unlink()
        (audit.path_b / "notes.txt").write_bytes(b"x")
    elif variant == "another_campaigns_plan":
        plan_file.write_bytes((audit.path_a / "plan.json").read_bytes())
    elif variant == "garbage":
        plan_file.write_bytes(b"{")
    else:
        plan_file.write_bytes(b"\xef\xbb\xbf" + plan_file.read_bytes())
    s1 = sup.interpret_campaigns([("own", audit.path_a), ("b", audit.path_b)])
    assert reason in s1.incomplete_reasons                                                                       # littéral mesuré (H3)
    result = derived_run(tmp_path, audit, derived_entries(audit, audit.b), [("own", audit.path_a, audit.a), ("b", audit.path_b, audit.b)])
    assert result.derived_root_labels == () and result.registry_coverage is ar.RegistryCoverage.PARTIAL


def test_dr6_a_hard_linked_plan_and_an_oversized_plan_stay_static(tmp_path, audit):
    os.link(audit.path_b / "plan.json", audit.path_b / "plan_alias.json")                                        # deux noms pour un fichier : `st_nlink != 1`
    linked = derived_run(tmp_path, audit, derived_entries(audit, audit.b), [("own", audit.path_a, audit.a), ("b", audit.path_b, audit.b)], name="linked")
    assert linked.derived_root_labels == ()
    os.unlink(audit.path_b / "plan_alias.json")
    root = sup.new_registry(tmp_path, "small")
    sup.populate(root, sup.build_chain(derived_entries(audit, audit.b)))
    handle = ar.read(config(root), own_campaign_id=audit.a, window=WN)
    s1 = sup.interpret_campaigns([("own", audit.path_a), ("b", audit.path_b)])
    small = ar.assess(handle, s1, own_campaign_id=audit.a, window=WN, campaign_roots=(("own", str(audit.path_a), audit.a), ("b", str(audit.path_b), audit.b)), max_json_bytes=100)
    assert small.derived_root_labels == ()                                                                       # la limite transmise est appliquée par la lecture gardée
    handle = ar.read(config(_populated(tmp_path, audit, "full")), own_campaign_id=audit.a, window=WN)
    full = ar.assess(handle, s1, own_campaign_id=audit.a, window=WN, campaign_roots=(("own", str(audit.path_a), audit.a), ("b", str(audit.path_b), audit.b)), max_json_bytes=MAX_JSON)
    assert full.derived_root_labels == ("b",)                                                                    # anti-vacuité : la même racine est dérivée avec la limite normale


def _populated(tmp_path, audit, name):
    root = sup.new_registry(tmp_path, name)
    sup.populate(root, sup.build_chain(derived_entries(audit, audit.b)))
    return root


def test_the_protocol_passes_the_scan_json_limit_to_the_adapter(tmp_path, monkeypatch):
    from tests.gate_v_exposure_support import LIMITS
    audit_dir, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    seen, real = [], ap.registry_audit.assess
    monkeypatch.setattr(ap.registry_audit, "assess", lambda *a, **k: (seen.append(k["max_json_bytes"]), real(*a, **k))[1])
    report = ap.audit_campaign_exposure(request(audit_dir, cfg, limits=dataclasses.replace(LIMITS, max_json_bytes=777_777)))
    assert report.receivability is ap.Receivability.RECEIVABLE, report.refusals
    assert seen == [777_777]                                                                                     # valeur distincte de toute constante de test : jamais un littéral du protocole


def test_cc8_a_slot_appended_after_the_second_read_is_invisible_to_it_and_visible_to_the_next(tmp_path):
    root = sup.new_registry(tmp_path)
    sup.populate(root, sup.build_chain([("R", B, *EARLY)]))
    cfg = config(root)
    handle = ar.read(cfg, own_campaign_id=OWN, window=WN)
    ar.compare(handle, cfg)                                                                                      # R2 réussit : rien n'a bougé jusque-là
    sup.put_slot(root, 1, sup.build_chain([("R", B, *EARLY), ("R", sup.foreign_id(0xE), "2027-01-01T00:00:00.000000Z", "2027-02-01T00:00:00.000000Z")])[1])
    assert refused(ar.compare, handle, cfg) == ("REGISTRY_CHAIN_HEAD_CHANGED", "EXTENDED")                      # une lecture ULTÉRIEURE le verrait : il n'y en a plus dans l'audit (limite)


@pytest.mark.parametrize("label", ["a", "A" * 64, "camp-1_x", "0" + "z" * 63])
def test_stage_formats_the_own_claim_source_for_boundary_labels_through_a_real_scan(tmp_path, label):
    from tests.test_gate_v_exposure_interpreters import clean_results, interpret as b3_interpret, make_split, results_root, campaign_root, write_json
    results = clean_results(tmp_path / "w")
    make_split(results, events=())
    own = tmp_path / "c" / CAMPAIGN_ID
    write_json(own / "plan.json", {"campaign_id": CAMPAIGN_ID})
    write_json(own / "final_holdout_access_claim.json", claim_record(CAMPAIGN_ID))
    s1 = b3_interpret(results_root(results), campaign_root(own, label))
    chain = chain_module.verify_chain(sup.build_chain([R_(), A_()]), registry_id=fx.REGISTRY_ID, genesis_instance_id=fx.INSTANCE_ID)
    assert ar._stage(chain, s1, own_campaign_id=CAMPAIGN_ID, own_label=label, window=WN) is OwnRecordStage.CLAIMED
    with pytest.raises(ar.RegistryAuditRefused) as caught:                                                       # un autre label : le Claim n'est plus « propre » ⇒ aucun Claim propre, règle 5
        ar._stage(chain, s1, own_campaign_id=CAMPAIGN_ID, own_label="elsewhere", window=WN)
    assert caught.value.detail == "STAGE_RECORD_OUTSIDE_OWN_ROOT"


def test_the_sample_rejects_duplicates_and_accepts_a_sorted_distinct_sample(tmp_path):
    audit_dir, _root, cfg = setup_world(tmp_path, OWN_RESERVED + [("R", B, *EARLY)])
    good = ap.audit_campaign_exposure(request(audit_dir, cfg))
    base = {f.name: getattr(good, f.name) for f in dataclasses.fields(ap.AuditReport)}
    two = (sup.foreign_id(0xB), sup.foreign_id(0xC))
    two_unavailable = dataclasses.replace(base["plan_declared_diagnostic"], unavailable_campaign_count=2, unavailable_breakdown=(("NO_ATTRIBUTED_ROOT", 2),))          # N2-b2a : diagnostic cohérent (invariant 11)
    valid = {**base, "registry_other_campaign_count": 2, "registry_uncovered_count": 2, "registry_uncovered_sample": two, "plan_declared_diagnostic": two_unavailable}
    assert ap.AuditReport(**valid).registry_uncovered_sample == two                                              # bloc PARTIAL présent, comptes cohérents
    with pytest.raises(ValueError, match="champs de registre"):
        ap.AuditReport(**{**valid, "registry_uncovered_sample": (sup.foreign_id(0xB), sup.foreign_id(0xB))})


# ── SG8 : le remplacement par le différentiel B4 couvre bien la même garantie ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entries,claim,stage", [
    ([], False, OwnRecordStage.NO_OWN_RECORDS), ([R_()], False, OwnRecordStage.RESERVED), ([R_(), A_()], False, OwnRecordStage.ADMITTED),
    ([R_(), A_()], True, OwnRecordStage.CLAIMED), ([R_(), A_(), C_()], True, OwnRecordStage.CONSUMED)])
def test_sg8_adapter_identity_equals_the_direct_b4_call_with_the_hand_derived_stage(tmp_path, monkeypatch, entries, claim, stage):
    spy = SpyB4(monkeypatch)
    s1, roots = claim_world(tmp_path, own_dir_claim=claim)
    assess_roots(tmp_path, entries, roots, s1, own=CAMPAIGN_ID)
    kinds = {"R": SourceKind.REGISTRY_RESERVATION, "A": SourceKind.REGISTRY_ADMISSION, "C": SourceKind.CONSUMPTION}
    records = sup.build_chain(entries)
    view = RegistryView(registry_id=fx.REGISTRY_ID, chain_head=sup.H(records[-1]) if records else sup.GENESIS, records=tuple(
        RegistryRecordFact(seq=i, kind=kinds[kind], campaign_id=r["campaign_id"], content_hash=sup.H(r), window_start_utc=r["window_start_utc"], window_end_utc=r["window_end_utc"])
        for i, (r, (kind, *_rest)) in enumerate(zip(records, entries))))
    direct = assemble_exposure_inventory(s1, registry=view, accounting=AccountingViews(), own_context=OwnCampaignContext(CAMPAIGN_ID, stage))
    assert spy.results[0].inventory_id == direct.inventory_id and spy.calls[0]["own_context"].own_record_stage is stage


def test_sg8_the_stage_changes_the_inventory_identity_for_the_same_registry_view(tmp_path, monkeypatch):
    """Preuve que l'étage compte vraiment dans l'identité (sinon le différentiel ci-dessus serait vacueux) : même vue et même S1, deux étages calculés à la main, deux identités."""
    s1, _roots = claim_world(tmp_path, own_dir_claim=False)
    records = sup.build_chain([R_(), A_()])
    view = RegistryView(registry_id=fx.REGISTRY_ID, chain_head=sup.H(records[-1]), records=tuple(
        RegistryRecordFact(seq=i, kind=kind, campaign_id=CAMPAIGN_ID, content_hash=sup.H(r), window_start_utc=WN[0], window_end_utc=WN[1])
        for i, (r, kind) in enumerate(zip(records, (SourceKind.REGISTRY_RESERVATION, SourceKind.REGISTRY_ADMISSION)))))
    ids = {stage: assemble_exposure_inventory(s1, registry=view, accounting=AccountingViews(), own_context=OwnCampaignContext(CAMPAIGN_ID, stage)).inventory_id
           for stage in (OwnRecordStage.NO_OWN_RECORDS, OwnRecordStage.RESERVED, OwnRecordStage.ADMITTED)}
    assert ids[OwnRecordStage.ADMITTED] != ids[OwnRecordStage.NO_OWN_RECORDS] and len(set(ids.values())) >= 2
