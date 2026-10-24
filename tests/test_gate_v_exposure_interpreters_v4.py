"""AF-V-07 Slice E3-E S-5a (lot Q-2, K1 Étage 1) — B3 v4 : dossier de campagne V2 réel.

Contrat accepté par l'utilisateur le 2026-10-24 (Q2-D1 Étage 1, Q2-D2, Q2-D3 option C) ; texte : `docs/adr/0025-proposal-E3E-Q2-FINAL-CONTRACT-PROPOSED.md`
(R8, prioritaire sur R7) et ADR 0025 23.33. Fixtures SYNTHÉTIQUES dans `tmp_path` : aucune donnée de marché, aucun FINAL_HOLDOUT.

Principes testés : WF/MC/PS pré-holdout restent `UNKNOWN_SOURCE` (absence d'exposition NON établie, jamais `NO_OVERLAP`) ; `manifest.json` est une source
informative à schéma strict ; `manifest.update.lock` et `technical_failure.json` restent des entrées inconnues bloquantes (comportement v3) ;
un même chemin ne correspond jamais à deux règles ; v2 et v3 restent lisibles avec leurs digests figés.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

import gate_v_campaign_manifest_v2 as m2
import gate_v_exposure_interpreters as b3
import gate_v_exposure_inventory as b4
from gate_v_campaign_plan_v2 import GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION, compute_gate_v_campaign_id_v2
from gate_v_exposure_scan import (
    AuditRoot,
    EntryClass,
    ExposureScanRefusal,
    JsonKind,
    ScanHooks,
    SegmentPattern,
    SourceRule,
    StructuralFailure,
    scan_audit_roots,
)
from gate_v_final_holdout_protocol import (
    ChronologyFacts,
    ClassificationInput,
    DeclarationSet,
    ExposureClass,
    OverlapVerdict,
    OwnCampaignContext,
    OwnRecordStage,
    SourceKind,
    SourceStatus,
    TimeProofFact,
    TimeProofStatus,
    UnresolvedCause,
    build_exposure_declaration,
    classify_exposure,
    compute_exposure_inventory_id,
    compute_static_sources_digest,
)
from tests.gate_v_exposure_support import LIMITS, W, write_json

PREREG, FINGERPRINT = "c" * 64, "d" * 64
CID = compute_gate_v_campaign_id_v2(campaign_plan_semantics_version=GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION,
                                    preregistration_id=PREREG, campaign_protocol_fingerprint=FINGERPRINT)
RUN_WF, RUN_MC, RUN_PS = f"{CID}_walk_forward", f"{CID}_monte_carlo", f"{CID}_parameter_stability_fold_000"
V2, V3, V4 = "gate_v_exposure_interpreters_v2", "gate_v_exposure_interpreters_v3", "gate_v_exposure_interpreters_v4"
CURRENT = "campaign_current"


# ── Fixtures : enregistrements aux formes des vrais producteurs ───────────────────────────────────────────────────────

def manifest_record(**changes) -> dict:
    """Record produit par le sérialiseur RÉEL de D2 (`gate_v_campaign_manifest_v2_to_record`) pour un manifeste initial valide."""
    manifest = m2.GateVCampaignManifestV2(
        manifest_semantics_version=m2.GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION, campaign_id=CID, preregistration_id=PREREG,
        campaign_protocol_fingerprint=FINGERPRINT, manifest_revision=0, status="READY_FOR_EXECUTION", execution_started=False, running=False,
        technical_failure_reason=None, walk_forward_validation_run_id=None, monte_carlo_validation_run_id=None,
        parameter_stability_validation_run_ids_by_fold={}, final_holdout_claim_id=None, final_holdout_claim_content_hash=None,
        holdout_access_event_id=None, holdout_access_event_content_hash=None, oos_evidence_validation_run_id=None)
    record = m2.gate_v_campaign_manifest_v2_to_record(manifest)
    record.update(changes)
    return record


def run_record(validation_type: str, run_id: str, evidence=None) -> dict:
    return {"validation_run_id": run_id, "research_run_id": "r", "split_plan_id": "s", "dataset_snapshot_id": "S0",
            "validation_type": validation_type, "strategy_name": "st", "strategy_params": {}, "evidence": evidence or {},
            "status": "completed", "completed_at": "2025-12-01T00:00:00+00:00"}


def fold(train_start, boundary, test_end) -> dict:
    return {"fold_id": "fold_000", "definition": {"fold_index": 0, "fold_id": "fold_000", "train_start": train_start,
            "requested_boundary": boundary, "effective_boundary": boundary, "boundary_adjusted": False, "requested_test_end": test_end,
            "effective_test_end": test_end, "test_end_adjusted": False, "is_last_fold": True}}


def wf_record(train_start, boundary, test_end) -> dict:
    return run_record("walk_forward", RUN_WF, {"fold_results": [fold(train_start, boundary, test_end)], "execution_status": "completed",
                                               "scientific_verdict": "PASS"})


PLAN = {"campaign_id": CID}


def build(tmp_path, files: dict, *, name: str = CID, dirs=()):
    """Écrit `files` (dict/list → JSON, bytes → octets bruts, None → fichier vide) sous `tmp_path/name`."""
    directory = tmp_path / name
    directory.mkdir(parents=True, exist_ok=True)
    for relative, value in files.items():
        path = directory / relative
        if isinstance(value, (dict, list)):
            write_json(path, value)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"" if value is None else value)
    for relative in dirs:
        (directory / relative).mkdir(parents=True, exist_ok=True)
    return directory


def interpret(directory, *, label="camp", hooks=None):
    root = b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, AuditRoot(label, str(directory)))
    return b3.interpret_audit_roots((root,), LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1], hooks=hooks)


def assembled(interpretation, context=OwnCampaignContext(CURRENT, OwnRecordStage.NO_OWN_RECORDS)):
    return b4.assemble_exposure_inventory(interpretation, registry=b4.RegistryView("reg", None, ()), accounting=b4.AccountingViews(),
                                          own_context=context, derived_root_labels=())


def classification(assembly):
    declaration = build_exposure_declaration(declaration_seq=1, declarant="Mira", inventory_id=assembly.inventory_id, prev_declaration_id=None,
                                             declared_exposures=(), declared_t_sel_utc=None, declared_trial_counts=None)
    chronology = ChronologyFacts(None, None, TimeProofFact(TimeProofStatus.ABSENT, None, None), None, None, None, None)
    return classify_exposure(ClassificationInput(assembly.inventory, DeclarationSet((declaration,), True), chronology, assembly.own_context))


def finding_for(result, suffix):
    (match,) = [f for f in result.findings if f.source_id.endswith(suffix)]
    return match


# ── 1. Version, digests historiques et règles de la table ──────────────────────────────────────────────────────────

def test_b3_is_version_4_and_still_knows_v2_and_v3():
    assert b3.B3_SEMANTICS_VERSION == V4
    assert b3.KNOWN_B3_VERSIONS == (V2, V3, V4)


def digests(version):
    return {layout: digest for known, layout, digest in b3.B3_RULES_DIGESTS if known == version}


V3_CAMPAIGN_RULE_COUNT = 9        # plan, Claim, puis les 7 règles de `exposure/` : table v3 intégrale, conservée en tête de la table v4


def test_v4_keeps_the_v3_campaign_table_first_and_its_historical_digest_reproducible(tmp_path):
    root = tmp_path / "camp"
    (root / "x").mkdir(parents=True)
    rules = b3.source_rules(b3.RootLayout.CAMPAIGN_DIR)
    assert len(rules) > V3_CAMPAIGN_RULE_COUNT
    scan = scan_audit_roots((AuditRoot("r", str(root)),), rules[:V3_CAMPAIGN_RULE_COUNT], LIMITS)
    assert scan.rules_digest == digests(V3)[b3.RootLayout.CAMPAIGN_DIR] == "7cc0cb309210f43cc0e6e00a2a220483196fdc3ff1d7e285aff758313de2e04f"


def test_v4_registry_pins_each_layout_and_changes_only_the_campaign_digest():
    assert set(digests(V4)) == set(b3.RootLayout)
    assert digests(V4)[b3.RootLayout.RESULTS] == digests(V3)[b3.RootLayout.RESULTS] == digests(V2)[b3.RootLayout.RESULTS]
    assert digests(V4)[b3.RootLayout.SPLIT_PLAN_DIR] == digests(V3)[b3.RootLayout.SPLIT_PLAN_DIR] == digests(V2)[b3.RootLayout.SPLIT_PLAN_DIR]
    assert digests(V4)[b3.RootLayout.CAMPAIGN_DIR] not in (digests(V3)[b3.RootLayout.CAMPAIGN_DIR], digests(V2)[b3.RootLayout.CAMPAIGN_DIR])
    assert digests(V2)[b3.RootLayout.CAMPAIGN_DIR] == "cb94f97f1b2c53f8839f90547b3ad619e5a3a64dacfb857071554d329a6a6fa7"
    assert len({(v, layout) for v, layout, _ in b3.B3_RULES_DIGESTS}) == len(b3.B3_RULES_DIGESTS) == 9


@pytest.mark.parametrize("layout", list(b3.RootLayout), ids=lambda layout: layout.value)
def test_the_v4_registry_entry_is_what_a_real_scan_of_the_implemented_table_yields(tmp_path, layout):
    root = tmp_path / layout.value
    (root / "x").mkdir(parents=True)
    scan = scan_audit_roots((AuditRoot("r", str(root)),), b3.source_rules(layout), LIMITS)
    assert digests(V4)[layout] == scan.rules_digest


# ── 2. manifest.json : source informative à schéma strict (Q2-D3, R8 section 5) ───────────────────────────────────────

def test_the_b3_manifest_contract_cannot_drift_from_the_d2_type():
    assert b3.MANIFEST_V2_KEYS == tuple(field.name for field in dataclasses.fields(m2.GateVCampaignManifestV2))
    assert b3.MANIFEST_V2_RESERVED == tuple(m2._RESERVED_FIELDS)
    assert b3.MANIFEST_V2_VERSION == m2.GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION
    assert set(b3.MANIFEST_V2_STATUSES) == set(m2.GATE_V_CAMPAIGN_V2_STATUSES)


def test_a_valid_initial_manifest_is_a_complete_informative_source_without_finding(tmp_path):
    record = manifest_record()
    assert m2.gate_v_campaign_manifest_v2_from_record(record).campaign_id == CID       # même record accepté par le chargeur D2
    result = interpret(build(tmp_path, {"plan.json": PLAN, "manifest.json": record}))
    assert result.complete is True and result.incomplete_reasons == () and result.findings == ()


def test_a_campaign_without_manifest_is_legal_before_the_d4_creation(tmp_path):
    result = interpret(build(tmp_path, {"plan.json": PLAN}))
    assert result.complete is True and result.findings == ()


@pytest.mark.parametrize("status, running, reason", [
    ("RUNNING", True, None), ("EVIDENCE_INCOMPLETE", False, None), ("TECHNICAL_FAILURE", False, "boom")])
def test_every_pre_claim_status_a_d2_manifest_can_have_is_accepted(tmp_path, status, running, reason):
    record = manifest_record(status=status, execution_started=True, running=running, technical_failure_reason=reason)
    result = interpret(build(tmp_path, {"plan.json": PLAN, "manifest.json": record}))
    assert result.complete is True and result.findings == ()


MUTATIONS = {
    "wrong_version": lambda r: {**r, "manifest_semantics_version": "gate_v_campaign_manifest_v1"},
    "campaign_id_other_directory": lambda r: {**r, "campaign_id": "gate_v_v2_" + "e" * 64},
    "campaign_id_bad_form": lambda r: {**r, "campaign_id": "campaign_x"},
    "extra_key": lambda r: {**r, "extra": 1},
    "missing_key": lambda r: {k: v for k, v in r.items() if k != "running"},
    "v1_manifest_shape": lambda r: {"campaign_id": CID, "oos_evidence_validation_run_id": None},
    "only_campaign_id": lambda r: {"campaign_id": CID},
    "preregistration_not_hex": lambda r: {**r, "preregistration_id": "Z" * 64},
    "fingerprint_short": lambda r: {**r, "campaign_protocol_fingerprint": "ab"},
    "revision_bool": lambda r: {**r, "manifest_revision": True},
    "revision_negative": lambda r: {**r, "manifest_revision": -1},
    "revision_float": lambda r: {**r, "manifest_revision": 1.5},
    "status_unknown": lambda r: {**r, "status": "DONE"},
    "started_string": lambda r: {**r, "execution_started": "yes"},
    "running_int": lambda r: {**r, "running": 1},
    "failure_reason_empty": lambda r: {**r, "technical_failure_reason": ""},
    "wf_id_empty": lambda r: {**r, "walk_forward_validation_run_id": ""},
    "mc_id_number": lambda r: {**r, "monte_carlo_validation_run_id": 3},
    "ps_mapping_list": lambda r: {**r, "parameter_stability_validation_run_ids_by_fold": []},
    "ps_mapping_value_empty": lambda r: {**r, "parameter_stability_validation_run_ids_by_fold": {"fold_000": ""}},
    "claim_id_set": lambda r: {**r, "final_holdout_claim_id": "claim_1"},
    "claim_hash_set": lambda r: {**r, "final_holdout_claim_content_hash": "a" * 64},
    "event_id_set": lambda r: {**r, "holdout_access_event_id": "evt"},
    "event_hash_set": lambda r: {**r, "holdout_access_event_content_hash": "a" * 64},
    "oos_run_set": lambda r: {**r, "oos_evidence_validation_run_id": "oos_" + "a" * 32},
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_a_non_conforming_manifest_makes_the_inventory_incomplete_with_a_reason_and_never_a_silent_pass(tmp_path, name):
    record = MUTATIONS[name](manifest_record())
    result = interpret(build(tmp_path, {"plan.json": PLAN, "manifest.json": record}))
    assert result.complete is False
    assert result.incomplete_reasons == ("INFORMATIVE_UNRESOLVED:camp/manifest.json",)
    assert result.findings == ()                                    # convention des informatifs : raison seule (R8 section 5, F1)
    assert classification(assembled(result)).classification is ExposureClass.UNDETERMINED


@pytest.mark.parametrize("raw", [b"[]", b'"x"', b"{", b'{"campaign_id": "a", "campaign_id": "b"}', b"\xef\xbb\xbf{}", b"\xff\xfe"])
def test_an_unreadable_or_non_object_manifest_is_an_informative_anomaly(tmp_path, raw):
    result = interpret(build(tmp_path, {"plan.json": PLAN, "manifest.json": raw}))
    assert result.complete is False and result.incomplete_reasons == ("INFORMATIVE_UNRESOLVED:camp/manifest.json",)


def test_the_manifest_content_is_not_an_identity_source_so_a_revision_change_does_not_move_the_inventory(tmp_path):
    first = assembled(interpret(build(tmp_path / "a", {"plan.json": PLAN, "manifest.json": manifest_record()})))
    second = assembled(interpret(build(tmp_path / "b", {"plan.json": PLAN, "manifest.json": manifest_record(
        manifest_revision=3, status="RUNNING", execution_started=True, running=True)})))
    assert first.inventory_id == second.inventory_id            # limite consignée (R8) : D5 8 bis détecte le changement de révision, pas B3


# ── 3. Validations pré-holdout WF/MC/PS : structure reconnue, verdict inchangé (K1 Étage 1) ───────────────────────────

def run_files(**runs) -> dict:
    return {"plan.json": PLAN, **{f"validations/{run_id}/validation_run.json": record for run_id, record in runs.items()}}


def test_a_walk_forward_run_is_an_identified_hashed_unknown_source_never_no_overlap(tmp_path):
    record = wf_record("2025-01-01T00:00:00+00:00", "2025-06-01T00:00:00+00:00", "2025-12-31T00:00:00+00:00")
    result = interpret(build(tmp_path, run_files(**{RUN_WF: record})))
    finding = finding_for(result, f"validations/{RUN_WF}/validation_run.json")
    assert finding.source_id.startswith("validation.run:camp/")
    assert (finding.source_kind, finding.status, finding.overlap) == (SourceKind.UNKNOWN_SOURCE, SourceStatus.UNRESOLVED, OverlapVerdict.UNKNOWN)
    assert finding.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN and finding.content_hash is not None
    assert [(n.validation_type, n.content_hash) for n in result.non_oos_validations] == [("walk_forward", finding.content_hash)]
    assert result.complete is True and result.incomplete_reasons == ()


@pytest.mark.parametrize("train_start, boundary, test_end", [
    ("2025-01-01T00:00:00+00:00", "2025-06-01T00:00:00+00:00", "2025-12-31T00:00:00+00:00"),     # fold avant W
    ("2025-06-01T00:00:00+00:00", "2025-12-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"),     # fold chevauchant W
    ("2026-05-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00"),     # fold après W
    ("2025-01-01T00:00:00", "2025-06-01T00:00:00", "2025-12-31T00:00:00"),                       # bornes naïves
    ("garbage", "garbage", "garbage"),                                                           # bornes invalides
    (None, None, None),                                                                          # période absente
])
def test_the_fold_windows_never_decide_anything_at_stage_1(tmp_path, train_start, boundary, test_end):
    """Aucune date de fold n'est une preuve d'exclusion (23.30.1) ni d'établissement à cet étage : même verdict dans tous les cas."""
    result = interpret(build(tmp_path, run_files(**{RUN_WF: wf_record(train_start, boundary, test_end)})))
    finding = finding_for(result, "validation_run.json")
    assert (finding.source_kind, finding.status, finding.overlap) == (SourceKind.UNKNOWN_SOURCE, SourceStatus.UNRESOLVED, OverlapVerdict.UNKNOWN)
    assert finding.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN
    assert classification(assembled(result)).classification is ExposureClass.UNDETERMINED


def test_monte_carlo_and_parameter_stability_runs_are_unresolved_with_no_window_copied_from_any_parent(tmp_path):
    files = run_files(**{RUN_MC: run_record("monte_carlo", RUN_MC, {"n_input_trades": 3}),
                         RUN_PS: run_record("parameter_stability", RUN_PS, {"n_candidates_total": 2})})
    result = interpret(build(tmp_path, files))          # aucun WF présent : le parent est absent, le verdict ne dépend pas de lui
    for run_id in (RUN_MC, RUN_PS):
        finding = finding_for(result, f"validations/{run_id}/validation_run.json")
        assert (finding.status, finding.overlap, finding.window_start_utc, finding.window_end_utc) == (SourceStatus.UNRESOLVED, OverlapVerdict.UNKNOWN, None, None)
    assert sorted(n.validation_type for n in result.non_oos_validations) == ["monte_carlo", "parameter_stability"]


def test_a_full_pre_holdout_directory_is_undetermined_and_blocks_a_reservation(tmp_path):
    files = run_files(**{RUN_WF: wf_record("2025-01-01T00:00:00+00:00", "2025-06-01T00:00:00+00:00", "2025-12-31T00:00:00+00:00"),
                         RUN_MC: run_record("monte_carlo", RUN_MC), RUN_PS: run_record("parameter_stability", RUN_PS)})
    files["manifest.json"] = manifest_record()
    assembly = assembled(interpret(build(tmp_path, files)))
    assert classification(assembly).classification is ExposureClass.UNDETERMINED
    relevant = [f for f in assembly.inventory.findings if f.overlap is not OverlapVerdict.NO_OVERLAP]
    assert len(relevant) == 3                                         # ensemble pertinent non vide : la RESERVATION reste refusée (23.10)
    empty = assembled(interpret(build(tmp_path / "empty", {"plan.json": PLAN})))
    assert compute_static_sources_digest(assembly.inventory, assembly.own_context) != compute_static_sources_digest(empty.inventory, assembly.own_context)


def test_no_run_can_disappear_from_the_audit_and_a_one_byte_change_moves_the_identities(tmp_path):
    record = wf_record("2025-01-01T00:00:00+00:00", "2025-06-01T00:00:00+00:00", "2025-12-31T00:00:00+00:00")
    other = {**record, "strategy_name": "st2"}
    context = OwnCampaignContext(CURRENT, OwnRecordStage.NO_OWN_RECORDS)
    present = assembled(interpret(build(tmp_path / "p", run_files(**{RUN_WF: record}))))
    changed = assembled(interpret(build(tmp_path / "c", run_files(**{RUN_WF: other}))))
    removed = assembled(interpret(build(tmp_path / "r", {"plan.json": PLAN})))
    ids = {compute_exposure_inventory_id(a.inventory, context) for a in (present, changed, removed)}
    digests_ = {compute_static_sources_digest(a.inventory, context) for a in (present, changed, removed)}
    assert len(ids) == 3 and len(digests_) == 3


def test_a_run_directory_without_its_anchor_is_unresolved_never_silently_accepted(tmp_path):
    result = interpret(build(tmp_path, {"plan.json": PLAN}, dirs=[f"validations/{RUN_WF}"]))
    assert result.complete is False and f"MISSING_REQUIRED:camp/validations/{RUN_WF}/validation_run.json" in result.incomplete_reasons
    assert any(f.status is SourceStatus.UNRESOLVED for f in result.findings)


@pytest.mark.parametrize("name", [
    "gate_v_1234abcd_walk_forward",                          # identifiant V1
    f"{CID}_walk_forward_x", f"{CID}_oos", f"{CID}_parameter_stability_fold_1000", f"{CID}_parameter_stability_fold_01",
    f"{CID}_PARAMETER_STABILITY_FOLD_000", "gate_v_v2_" + "A" * 64 + "_walk_forward", "gate_v_v2_" + "a" * 63 + "_walk_forward",
    "oos_" + "c" * 32])
def test_a_run_directory_outside_the_strict_v2_pattern_is_an_unknown_blocking_entry(tmp_path, name):
    result = interpret(build(tmp_path, {"plan.json": PLAN, f"validations/{name}/validation_run.json": run_record("walk_forward", name)}))
    assert result.complete is False and f"UNKNOWN_ENTRY:camp/validations/{name}" in result.incomplete_reasons
    assert any(f.source_kind is SourceKind.UNKNOWN_SOURCE and f.content_hash is None for f in result.findings)


def test_other_files_inside_a_run_directory_stay_unknown(tmp_path):
    files = run_files(**{RUN_WF: run_record("walk_forward", RUN_WF)})
    files[f"validations/{RUN_WF}/research_run.json"] = {"x": 1}
    result = interpret(build(tmp_path, files))
    assert f"UNKNOWN_ENTRY:camp/validations/{RUN_WF}/research_run.json" in result.incomplete_reasons


# ── 4. Q2-D2 : deux familles de chemins, jamais deux règles pour un même chemin ───────────────────────────────────────

OOS_FINAL = b3.CAMPAIGN_OOS_FINAL_FILE                           # motif RÉSERVÉ du chemin FUTUR de la ValidationRun OOS finale (ADR 23.13), sans producteur
assert OOS_FINAL.regex == r"oos_[0-9a-f]{32}\.json"
RUN_PATTERN = next((rule.segments[1] for rule in b3.source_rules(b3.RootLayout.CAMPAIGN_DIR)
                    if len(rule.segments) == 2 and rule.segments[0] == "validations"), SegmentPattern(r"absent_rule_v4"))


def test_the_future_final_oos_path_is_disjoint_from_the_pre_holdout_run_pattern():
    oos = "oos_" + "c" * 32 + ".json"
    assert OOS_FINAL.matches(oos) and not RUN_PATTERN.matches(oos)
    for run in (RUN_WF, RUN_MC, RUN_PS):
        assert RUN_PATTERN.matches(run) and not OOS_FINAL.matches(run)


def test_the_final_oos_file_is_not_in_the_v4_table_and_stays_an_unknown_blocking_entry(tmp_path):
    name = "oos_" + "c" * 32 + ".json"
    evidence = {"period_start": "2026-01-10T00:00:00+00:00", "period_end": "2026-02-01T00:00:00+00:00"}
    result = interpret(build(tmp_path, {"plan.json": PLAN, f"validations/{name}": run_record("oos", "oos_x", evidence)}))
    assert result.complete is False and f"UNKNOWN_ENTRY:camp/validations/{name}" in result.incomplete_reasons


def test_a_table_where_one_path_matches_two_rules_is_refused_with_ambiguous_source_table(tmp_path):
    """Le motif large `_ID_DIR` (qui admet le point) apparie `oos_<hex>.json` : un scan réel est REFUSÉ (démonstration du risque de R8, cas 1)."""
    directory = build(tmp_path, {"plan.json": PLAN, "validations/" + "oos_" + "c" * 32 + ".json": None})
    wide = (SourceRule(("validations",), EntryClass.STRUCTURAL_DIRECTORY, tag="t.v"),
            SourceRule(("validations", b3._ID_DIR), EntryClass.STRUCTURAL_DIRECTORY, tag="t.d"),
            SourceRule(("validations", OOS_FINAL), EntryClass.EXPOSING_JSON, JsonKind.OBJECT, tag="t.o"))
    with pytest.raises(ExposureScanRefusal) as caught:
        scan_audit_roots((AuditRoot("r", str(directory)),), wide, LIMITS)
    assert caught.value.failure is StructuralFailure.AMBIGUOUS_SOURCE_TABLE
    narrow = wide[:1] + (SourceRule(("validations", RUN_PATTERN), EntryClass.STRUCTURAL_DIRECTORY, tag="t.d"), wide[2])
    scan_audit_roots((AuditRoot("r", str(directory)),), narrow, LIMITS)         # table étroite : aucune ambiguïté


def test_no_path_of_the_v4_campaign_table_matches_two_rules():
    rules = b3.source_rules(b3.RootLayout.CAMPAIGN_DIR)
    samples = [("plan.json",), ("manifest.json",), ("manifest.update.lock",), ("technical_failure.json",), ("final_holdout_access_claim.json",),
               ("validations",), ("validations", RUN_WF), ("validations", RUN_WF, "validation_run.json"), ("validations", RUN_PS),
               ("validations", "oos_" + "c" * 32 + ".json"), ("exposure",), ("exposure", "inventory_" + "a" * 64 + ".json"),
               ("exposure", "a" * 64), ("exposure", "a" * 64, "declaration_0001.json"), ("exposure", "a" * 64, "attestation_0001.json")]
    for names in samples:
        assert len([rule for rule in rules if rule.matches(names)]) <= 1, names


# ── 5. Q2-D3 option C : verrou et sentinelle restent des entrées inconnues bloquantes (comportement v3) ─────────────────

TECHNICAL = ("manifest.update.lock", "technical_failure.json")
STATES = {"valid_json": b'{"technical_failure_sentinel_semantics_version": "v1", "campaign_id": "x", "reason": "r"}', "empty": None,
          "truncated": b'{"technical_failure_sentinel_semantics_version": "v1", "campa', "garbage": b"\x00\xff\xfe binary \x01", "text": b"locked by pid 12"}


@pytest.mark.parametrize("state", sorted(STATES))
@pytest.mark.parametrize("name", TECHNICAL)
@pytest.mark.parametrize("label", ["camp", "foreign_campaign_root"])
def test_a_lock_or_sentinel_is_an_unknown_blocking_source_in_any_state_for_any_campaign(tmp_path, name, state, label):
    result = interpret(build(tmp_path, {"plan.json": PLAN, name: STATES[state]}), label=label)
    assert result.complete is False and result.incomplete_reasons == (f"UNKNOWN_ENTRY:{label}/{name}",)
    finding = finding_for(result, name)
    assert (finding.source_kind, finding.status, finding.overlap) == (SourceKind.UNKNOWN_SOURCE, SourceStatus.UNRESOLVED, OverlapVerdict.UNKNOWN)
    assert finding.unresolved_cause is UnresolvedCause.UNKNOWN_SOURCE_TYPE and finding.content_hash is None      # jamais ouvert, jamais ignoré
    assert classification(assembled(result)).classification is ExposureClass.UNDETERMINED


@pytest.mark.parametrize("name", TECHNICAL)
def test_a_lock_or_sentinel_directory_is_an_unknown_directory_never_descended(tmp_path, name):
    result = interpret(build(tmp_path, {"plan.json": PLAN}, dirs=[name]))
    assert result.complete is False and result.incomplete_reasons == (f"UNKNOWN_ENTRY:camp/{name}",)
    assert finding_for(result, name).content_hash is None


@pytest.mark.parametrize("name", TECHNICAL)
def test_a_lock_or_sentinel_symbolic_link_refuses_the_whole_scan(tmp_path, name):
    directory = build(tmp_path, {"plan.json": PLAN, "target.bin": b"x"})
    try:
        os.symlink(directory / "target.bin", directory / name)
    except (OSError, NotImplementedError):
        pytest.skip("création de lien symbolique non permise sur cette machine (privilège Windows)")
    with pytest.raises(ExposureScanRefusal) as caught:
        interpret(directory)
    assert caught.value.failure is StructuralFailure.LINK_OR_REPARSE_POINT


@pytest.mark.parametrize("name", TECHNICAL)
def test_a_lock_or_sentinel_appearing_during_the_scan_is_never_silently_ignored(tmp_path, name):
    directory = build(tmp_path, {"plan.json": PLAN})
    created = []

    def appear(_pass_index):
        if not created:
            (directory / name).write_bytes(b"late")
            created.append(True)

    try:
        result = interpret(directory, hooks=ScanHooks(after_first_pass=appear))
    except ExposureScanRefusal as refusal:
        assert refusal.failure is not None              # refus de scan : jamais un résultat qui ignore le fichier
        return
    assert f"UNKNOWN_ENTRY:camp/{name}" in result.incomplete_reasons and result.complete is False


def test_a_lock_or_sentinel_present_after_the_reservation_moves_the_inventory_and_the_static_digest(tmp_path):
    context = OwnCampaignContext(CURRENT, OwnRecordStage.NO_OWN_RECORDS)
    before = assembled(interpret(build(tmp_path / "a", {"plan.json": PLAN})))
    after = assembled(interpret(build(tmp_path / "b", {"plan.json": PLAN, "technical_failure.json": None})))
    assert compute_static_sources_digest(before.inventory, context) != compute_static_sources_digest(after.inventory, context)
    assert compute_exposure_inventory_id(before.inventory, context) != compute_exposure_inventory_id(after.inventory, context)


# ── 6. Artefacts sans producteur ou sans norme acceptée : restent inconnus ───────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "read_intent.json", "data_receipt.json", "final_holdout_closing_record.json", "prospective_commitment.json",
    "s0_provenance_declaration.json", "reservation_time_proof.json", "holdout_snapshot_attachment.json", "commitment_void_record.json",
    "acquisition_authorization_0001.json", "acquisition_authorization.json", "manifest.json.bak", "x.exposure.tmp." + "a" * 32,
    "manifest.json." + "a" * 32 + ".tmp", "walk_forward", ".gate_v_checkpoints_v1", "anything.json"])
def test_unlisted_campaign_artifacts_remain_unknown_and_blocking(tmp_path, name):
    result = interpret(build(tmp_path, {"plan.json": PLAN, name: {"x": 1}}))
    assert result.complete is False and f"UNKNOWN_ENTRY:camp/{name}" in result.incomplete_reasons


def test_the_published_b3_digests_for_results_and_split_plan_dirs_are_unchanged():
    assert digests(V4)[b3.RootLayout.RESULTS] == "9014a865e7c5c4fea0ec7fc4cbcd3e8d76357a51693c339981e50f523ae51960"
    assert digests(V4)[b3.RootLayout.SPLIT_PLAN_DIR] == "e98082afc0482e2afdce61884f0da5f264a943defd666ca4aedd8b75ec217f29"


# ── 7. Étages (R8 section 5) : jamais de faux FRESH ──────────────────────────────────────────────────────────────────

def test_a_real_looking_campaign_directory_never_reaches_fresh_at_any_stage(tmp_path):
    base = run_files(**{RUN_WF: wf_record("2025-01-01T00:00:00+00:00", "2025-06-01T00:00:00+00:00", "2025-12-31T00:00:00+00:00")})
    base["manifest.json"] = manifest_record()
    for index, extra in enumerate([{}, {"technical_failure.json": None}, {"manifest.update.lock": None}]):
        assembly = assembled(interpret(build(tmp_path / str(index), {**base, **extra})))
        assert classification(assembly).classification is ExposureClass.UNDETERMINED
