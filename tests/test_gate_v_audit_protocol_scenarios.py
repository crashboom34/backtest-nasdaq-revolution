"""N-VIDE-2 / N2-a — protocole d'audit : scénarios réels sur disque, par l'INTERFACE PUBLIQUE (requête → rapport). Les attendus sont des littéraux écrits à part
(statut du manifeste, catégorie de vide, état de la chaîne, blocages) ; aucun n'est recalculé par le code testé."""

from __future__ import annotations

import json

import pytest

import gate_v_audit_protocol as ap
import gate_v_k1s2_verifier as vf
from tests.gate_v_audit_protocol_support import request_of, scenario_dir, tree_digest
from tests.gate_v_manifest_scenarios import SCENARIOS

M, E, C = ap.ManifestState, ap.ChainStatus, ap.BlockCode
NE, CO, IN = E.NOT_EVALUATED, E.COHERENT, E.INCOHERENT
BOTH, CHAIN, EMPTY, NONE = {C.CHAIN_INCOHERENT, C.EMPTINESS_BLOCKING}, {C.CHAIN_INCOHERENT}, {C.EMPTINESS_BLOCKING}, set()
A_, B_, C_, X_, N_ = ("A_EMPTY_NO_DECLARATION", "B_ARTEFACT_IMPOSED_BUT_ABSENT", "C_ATTESTED_INTERRUPTION", "CONTRADICTORY", "NOT_EMPTY")

# nom → (B3 v6 complet ?, état du manifeste, catégorie de vide, état de la chaîne, blocages). Mesurés sur les raisons v6 (N-VIDE-1) et les règles de L3-A, écrits en littéraux.
EXPECTED = {
    "01-ready-initial": (True, M.INITIAL, A_, NE, NONE),
    "02-wf-declared-directory-absent": (False, M.EVIDENCE_INCOMPLETE, B_, IN, BOTH),
    "03-wf-declared-directory-empty": (False, M.EVIDENCE_INCOMPLETE, B_, IN, BOTH),
    "04-record-without-coverage": (False, M.EVIDENCE_INCOMPLETE, B_, IN, BOTH),
    "05-coverage-without-session": (False, M.EVIDENCE_INCOMPLETE, B_, IN, BOTH),
    "06-session-without-seal": (False, M.EVIDENCE_INCOMPLETE, B_, IN, BOTH),
    "07-running-validations-empty": (False, M.RUNNING, C_, NE, EMPTY),
    "08-technical-failure-validations-empty": (False, M.TECHNICAL_FAILURE, C_, NE, EMPTY),
    "09-evidence-incomplete-nothing-declared": (False, M.EVIDENCE_INCOMPLETE, C_, NE, EMPTY),
    "10-complete-claimed-seal-missing": (False, M.EVIDENCE_COMPLETE, B_, IN, BOTH),
    "11-monte-carlo-declared-absent": (False, M.EVIDENCE_COMPLETE, B_, IN, BOTH),
    "12-parameter-stability-declared-absent": (False, M.EVIDENCE_COMPLETE, B_, IN, BOTH),
    "13-several-runs-one-missing": (False, M.EVIDENCE_COMPLETE, B_, IN, BOTH),
    "14-foreign-manifest": (False, M.FOREIGN, X_, NE, EMPTY),
    "15-exposure-empty-ready": (True, M.INITIAL, A_, NE, NONE),
    "16a-manifest-corrupt-bytes": (False, M.UNREADABLE_OR_NONCONFORMING, X_, NE, EMPTY),
    "16b-manifest-invalid-schema": (False, M.UNREADABLE_OR_NONCONFORMING, X_, NE, EMPTY),
    "17-complete-claimed-without-any-reference": (False, M.EVIDENCE_COMPLETE, C_, NE, EMPTY),
    "18-no-manifest-validations-empty": (True, M.ABSENT, A_, NE, NONE),
    "19-ready-but-artefacts-present": (False, M.INITIAL, X_, IN, BOTH),
    "20-foreign-run-reference": (False, M.EVIDENCE_INCOMPLETE, X_, IN, BOTH),
    "21-wrong-kind-reference": (False, M.EVIDENCE_INCOMPLETE, X_, IN, BOTH),
    "22-running-flag-without-running-status": (False, M.INITIAL, X_, NE, EMPTY),
    "23-ready-with-failure-reason": (False, M.INITIAL, X_, NE, EMPTY),
    "24-walk-forward-outputs-with-ready-manifest": (False, M.INITIAL, X_, IN, BOTH),
    "25-all-declared-runs-present": (False, M.EVIDENCE_COMPLETE, N_, IN, CHAIN),
    "26-complete-claimed-without-monte-carlo-reference": (False, M.EVIDENCE_COMPLETE, N_, IN, CHAIN),
    "27-complete-claimed-without-parameter-stability-references": (False, M.EVIDENCE_COMPLETE, N_, IN, CHAIN),
    "28-ready-with-empty-walk-forward-directory": (False, M.INITIAL, A_, IN, CHAIN),
    "29-ready-with-revision-above-zero": (False, M.INITIAL, A_, NE, NONE),
    "30-ready-with-reference-not-started": (False, M.INITIAL, X_, IN, BOTH),
    "31-session-in-another-run-directory": (False, M.EVIDENCE_INCOMPLETE, B_, IN, BOTH),
    "32-uppercase-hex-reference": (False, M.EVIDENCE_INCOMPLETE, X_, IN, BOTH),
}


def test_the_expected_table_covers_every_scenario_exactly():
    assert set(EXPECTED) == set(SCENARIOS)


@pytest.fixture(scope="module")
def reports(tmp_path_factory):
    base = tmp_path_factory.mktemp("n2a_scenarios")
    return {name: ap.audit_campaign_exposure(request_of(scenario_dir(base, name))) for name in SCENARIOS}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_each_scenario_gets_the_expected_axes_and_never_a_positive_authority(reports, name):
    report = reports[name]
    complete, manifest, emptiness, chain, blocks = EXPECTED[name]
    assert report.refusals == () and report.receivability is ap.Receivability.RECEIVABLE
    assert report.b3_semantics_version == "gate_v_exposure_interpreters_v6"
    assert (report.b3_completeness is ap.Completeness.COMPLETE) is complete
    assert report.incomplete_reasons == () if complete else report.incomplete_reasons != ()
    (root,) = report.roots
    assert (root.manifest_state, root.emptiness_category, root.chain, {b.code for b in report.blocks}) == (manifest, emptiness, chain, blocks)
    assert report.rescan is ap.RescanStatus.PROTOCOL_RESCAN_MATCHED and report.facts_s1 == report.facts_s2 and report.identity_s1 == report.identity_s2
    assert report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE and report.grants == () and report.e3j_prerequisites_unmet != ()


def test_only_the_initial_manifest_and_the_absent_manifest_cases_are_complete_and_they_differ_by_manifest_state(reports):
    complete = {name for name, report in reports.items() if report.b3_completeness is ap.Completeness.COMPLETE}
    assert complete == {"01-ready-initial", "15-exposure-empty-ready", "18-no-manifest-validations-empty"}
    assert reports["01-ready-initial"].roots[0].manifest_state is M.INITIAL and reports["18-no-manifest-validations-empty"].roots[0].manifest_state is M.ABSENT
    assert reports["01-ready-initial"] != reports["18-no-manifest-validations-empty"]


def test_a_complete_report_still_establishes_no_absence_and_names_what_is_not_done(reports):
    report = reports["01-ready-initial"]
    assert report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE and report.grants == () and report.grants_nothing is True
    assert set(ap.E3J_PREREQUISITES_UNMET) <= set(report.e3j_prerequisites_unmet)
    assert report.independent_rescan_required is True and set(vf.NOT_PROVEN) <= set(report.not_proven)
    assert {"SNAPSHOT_ATOMICITY", "CHRONOLOGY", "INDEPENDENT_RESCAN", "S0_RECOMPUTATION"} <= set(report.not_proven)


def test_the_window_is_configured_by_the_operator_and_reported_unverified(reports):
    report = reports["01-ready-initial"]
    assert report.window == ("2026-01-01T00:00:00.000000Z", "2026-04-01T00:00:00.000000Z")
    assert report.window_provenance is ap.WindowProvenance.UNVERIFIED and report.window_declared_source is ap.WindowDeclaredSource.OPERATOR_CONFIGURED


def test_declared_empty_directories_and_artefact_counts_are_exposed_per_root(reports):
    assert reports["01-ready-initial"].roots[0].observed_execution_artefacts == 0
    assert reports["19-ready-but-artefacts-present"].roots[0].observed_execution_artefacts > 0
    assert reports["07-running-validations-empty"].roots[0].observed_execution_artefacts == 0
    assert reports["15-exposure-empty-ready"].roots[0].empty_directories == ("exposure",)


def test_chain_defects_keep_the_l3a_codes_and_paths(reports):
    codes = {d.code for d in reports["06-session-without-seal"].roots[0].chain_defects}
    assert codes == {"NO_SEAL"}
    assert {d.code for d in reports["31-session-in-another-run-directory"].roots[0].chain_defects} >= {"MIXED_RUNS", "SESSION_MISSING"}


def test_the_v6_incomplete_reasons_are_carried_unfiltered_and_exact(reports):
    assert reports["29-ready-with-revision-above-zero"].incomplete_reasons == ("MANIFEST_STATE_CONTRADICTION:camp/manifest.json#ready_vs_revision",)
    assert "MANIFEST_RUN_IN_PROGRESS:camp/manifest.json#status" in reports["07-running-validations-empty"].incomplete_reasons
    assert "MANIFEST_TECHNICAL_FAILURE:camp/manifest.json#status" in reports["08-technical-failure-validations-empty"].incomplete_reasons


def test_every_run_stays_accounted_and_a_missing_run_never_disappears(reports):
    report = reports["02-wf-declared-directory-absent"]
    assert any(r.startswith("MANIFEST_RUN_ABSENT:camp/manifest.json#walk_forward_validation_run_id->validations/") and r.endswith("_walk_forward/validation_run.json")
               for r in report.incomplete_reasons)
    assert report.roots[0].chain is IN and report.roots[0].emptiness_category == B_ and C.EMPTINESS_BLOCKING in {b.code for b in report.blocks}


def test_auxiliary_runs_are_present_but_unqualified_and_lift_no_reason(reports):
    report = reports["25-all-declared-runs-present"]
    assert report.auxiliary_runs is ap.AuxiliaryRuns.UNQUALIFIED and report.b3_completeness is ap.Completeness.INCOMPLETE
    assert not any(r.startswith("MANIFEST_RUN_ABSENT") for r in report.incomplete_reasons)       # tous les runs déclarés sont présents ; MC / PS restent pourtant non qualifiés


# ── Chaîne cohérente construite uniquement à partir des observations ─────────────────────────────────────────────────────────────────────────────────
def coherent_campaign(tmp_path):
    from tests.test_gate_v_k1s2_verifier import CID as KCID, RUN as KRUN, world
    from tests.test_gate_v_exposure_interpreters_v4 import manifest_record
    directory = tmp_path / KCID
    for relative, data in world().items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (directory / "plan.json").write_text(json.dumps({"campaign_id": KCID}))
    record = manifest_record(campaign_id=KCID, walk_forward_validation_run_id=KRUN, status="EVIDENCE_INCOMPLETE", execution_started=True)
    (directory / "manifest.json").write_text(json.dumps(record, indent=2))
    return directory, KCID


def test_a_coherent_chain_is_coherent_only_with_the_observations_and_lifts_nothing(tmp_path):
    directory, cid = coherent_campaign(tmp_path)
    report = ap.audit_campaign_exposure(request_of(directory))
    (root,) = report.roots
    assert report.refusals == () and root.chain is ap.ChainStatus.COHERENT and root.chain_defects == ()
    assert C.CHAIN_INCOHERENT not in {b.code for b in report.blocks}
    assert report.b3_completeness is ap.Completeness.INCOMPLETE
    assert any(r.startswith("RUN_OUTPUT_UNVERIFIED") for r in report.incomplete_reasons) and any(r.startswith("RUN_EVIDENCE_UNVERIFIED") for r in report.incomplete_reasons)
    assert report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE and "SEAL_ANTERIORITY" in report.not_proven and "SEAL_ANTERIORITY" in report.e3j_prerequisites_unmet


def test_a_coherent_chain_with_an_output_changed_after_the_seal_is_incoherent(tmp_path):
    directory, _ = coherent_campaign(tmp_path)
    (directory / "walk_forward" / "manifest.json").write_bytes(b"altered after seal\n")
    report = ap.audit_campaign_exposure(request_of(directory))
    assert report.roots[0].chain is ap.ChainStatus.INCOHERENT and "OUTPUT_ALTERED" in {d.code for d in report.roots[0].chain_defects}
    assert C.CHAIN_INCOHERENT in {b.code for b in report.blocks}


def test_the_audit_writes_nothing_even_when_it_refuses_or_blocks(tmp_path):
    directory = scenario_dir(tmp_path, "08-technical-failure-validations-empty")
    before = tree_digest(tmp_path)
    for request in (request_of(directory), request_of(directory, hash_limits=None)):
        ap.audit_campaign_exposure(request)
        assert tree_digest(tmp_path) == before


def test_a_manifest_state_is_never_inferred_when_the_emptiness_diagnostic_is_unusable(tmp_path, monkeypatch):
    import gate_v_k1s2_emptiness as em
    directory = scenario_dir(tmp_path, "01-ready-initial")
    monkeypatch.setattr(em, "diagnose_emptiness", lambda tree: em.EmptinessDiagnostic(em.EmptinessCategory.BAD_INPUT, (em.EmptinessReason.BAD_INPUT,), ()))
    report = ap.audit_campaign_exposure(request_of(directory))
    assert report.roots[0].manifest_state is M.UNREADABLE_OR_NONCONFORMING and C.EMPTINESS_BLOCKING in {b.code for b in report.blocks}
