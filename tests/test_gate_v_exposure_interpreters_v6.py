"""N-VIDE-1 / B3 v6 — complétude manifeste → preuves attendues (fail-closed).

Décision de l'utilisateur (2026-10-26) : lorsqu'un manifeste de campagne indique une exécution en cours, échouée, incomplète, ou RÉFÉRENCE une ValidationRun dont la chaîne attendue est
absente ou incomplète, B3 doit produire un inventaire INCOMPLET — par une version distincte `gate_v_exposure_interpreters_v6`, sans modifier v2/v3/v4/v5. N-VIDE-2, N-VIDE-3, R9 et D1-D9
ne sont PAS acceptés. Aucun SourceKind, aucun verdict d'absence d'exposition, aucune admission, aucun FINAL_HOLDOUT. Fixtures SYNTHÉTIQUES sur disque (`tmp_path`).

Structure : (1) le défaut démontré sur v4 ET v5 (gelé, historique) ; (2) la matrice de décisions v6 (raisons EXACTES) ; (3) invariants différentiels v5 → v6 : v6 n'est jamais moins
bloquant, n'invente ni finding ni hash ; (4) attribution (racines, campagne, référence) ; (5) hooks, instabilité, racines `may_be_empty` ; (6) version, digests, activation explicite.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import time
from pathlib import Path

import pytest

import gate_v_exposure_interpreters as b3
import gate_v_exposure_interpreters_v5 as v5
import gate_v_exposure_interpreters_v6 as v6
import gate_v_exposure_scan as scan
from gate_v_exposure_scan import AuditRoot, ExposureScanRefusal, ScanHooks, ScanLimits
from tests.gate_v_exposure_support import LIMITS, W, write_json
from tests.gate_v_manifest_scenarios import (
    CAMPAIGN, HL, OTHER_CID, OTHER_WF, RUN_MC, RUN_PS, RUN_WF, RUN_WF_UPPER, SCENARIOS, assess, interpret_v4, interpret_v5, realise, roots_of,
)
from tests.test_gate_v_exposure_interpreters_v4 import CID, manifest_record

FRESH = "FRESH_UNEXPOSED_DECLARED"
WF_FIELD = "walk_forward_validation_run_id"
MC_FIELD = "monte_carlo_validation_run_id"
PS_FIELD = "parameter_stability_validation_run_ids_by_fold[fold_000]"


def interpret_v6(roots, **kwargs):
    return v6.interpret_audit_roots_v6(roots, LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1], **kwargs)


def reason(code: str, reference: str, label: str = "camp") -> str:
    return f"{code}:{label}/manifest.json#{reference}"


def path_of(run: str, name: str) -> str:
    return f"validations/{run}/{name}"


# Raisons NOUVELLES attendues de v6 par rapport à v5 (chaînes EXACTES : code, racine, manifeste, référence). `set()` : v6 ne change rien.
INCOMPLETE = reason("MANIFEST_EVIDENCE_INCOMPLETE", "status")
COMPLETE_VS_REFERENCES = reason("MANIFEST_STATE_CONTRADICTION", "complete_vs_references")      # EVIDENCE_COMPLETE affirmé sans référencer tous les runs attendus (WF, MC, PS)
NEW_REASONS = {
    "01-ready-initial": set(),
    "02-wf-declared-directory-absent": {INCOMPLETE, reason("MANIFEST_RUN_ABSENT", f"{WF_FIELD}->{path_of(RUN_WF, 'validation_run.json')}")},
    "03-wf-declared-directory-empty": {INCOMPLETE, reason("MANIFEST_RUN_ABSENT", f"{WF_FIELD}->{path_of(RUN_WF, 'validation_run.json')}")},
    "04-record-without-coverage": {INCOMPLETE, *(reason("MANIFEST_RUN_EVIDENCE_MISSING", f"{WF_FIELD}->{path_of(RUN_WF, n)}")
                                                 for n in ("run_data_coverage.json", "run_session_0001.json", "run_seal.json"))},
    "05-coverage-without-session": {INCOMPLETE, *(reason("MANIFEST_RUN_EVIDENCE_MISSING", f"{WF_FIELD}->{path_of(RUN_WF, n)}") for n in ("run_session_0001.json", "run_seal.json"))},
    "06-session-without-seal": {INCOMPLETE, reason("MANIFEST_RUN_EVIDENCE_MISSING", f"{WF_FIELD}->{path_of(RUN_WF, 'run_seal.json')}")},
    "07-running-validations-empty": {reason("MANIFEST_RUN_IN_PROGRESS", "status")},
    "08-technical-failure-validations-empty": {reason("MANIFEST_TECHNICAL_FAILURE", "status")},
    "09-evidence-incomplete-nothing-declared": {INCOMPLETE},
    "10-complete-claimed-seal-missing": {reason("MANIFEST_RUN_EVIDENCE_MISSING", f"{WF_FIELD}->{path_of(RUN_WF, 'run_seal.json')}")},
    "11-monte-carlo-declared-absent": {reason("MANIFEST_RUN_ABSENT", f"{MC_FIELD}->{path_of(RUN_MC, 'validation_run.json')}")},
    "12-parameter-stability-declared-absent": {reason("MANIFEST_RUN_ABSENT", f"{PS_FIELD}->{path_of(RUN_PS, 'validation_run.json')}")},
    "13-several-runs-one-missing": {reason("MANIFEST_RUN_ABSENT", f"{MC_FIELD}->{path_of(RUN_MC, 'validation_run.json')}"),
                                    reason("MANIFEST_RUN_ABSENT", f"{PS_FIELD}->{path_of(RUN_PS, 'validation_run.json')}")},
    "14-foreign-manifest": set(),
    "15-exposure-empty-ready": set(),
    "16a-manifest-corrupt-bytes": set(),
    "16b-manifest-invalid-schema": set(),
    "17-complete-claimed-without-any-reference": {COMPLETE_VS_REFERENCES},
    "18-no-manifest-validations-empty": set(),
    "19-ready-but-artefacts-present": {reason("MANIFEST_ARTEFACTS_WITHOUT_EXECUTION", path_of(RUN_WF, "run_data_coverage.json"))},
    "20-foreign-run-reference": {INCOMPLETE, reason("MANIFEST_RUN_FOREIGN", f"{WF_FIELD}={OTHER_WF}")},
    "21-wrong-kind-reference": {INCOMPLETE, reason("MANIFEST_RUN_ID_INVALID", f"{WF_FIELD}={RUN_MC}")},
    "22-running-flag-without-running-status": {reason("MANIFEST_STATE_CONTRADICTION", "running_vs_status")},
    "23-ready-with-failure-reason": {reason("MANIFEST_STATE_CONTRADICTION", "failure_reason_vs_status")},
    "24-walk-forward-outputs-with-ready-manifest": {reason("MANIFEST_ARTEFACTS_WITHOUT_EXECUTION", "walk_forward/manifest.json")},
    "25-all-declared-runs-present": set(),
    "26-complete-claimed-without-monte-carlo-reference": {COMPLETE_VS_REFERENCES},
    "27-complete-claimed-without-parameter-stability-references": {COMPLETE_VS_REFERENCES},
    "29-ready-with-revision-above-zero": {reason("MANIFEST_STATE_CONTRADICTION", "ready_vs_revision")},         # le producteur réel incrémente la révision à chaque commande
    "30-ready-with-reference-not-started": {reason("MANIFEST_STATE_CONTRADICTION", "ready_vs_activity"),
                                            reason("MANIFEST_RUN_ABSENT", f"{WF_FIELD}->{path_of(RUN_WF, 'validation_run.json')}")},
    "31-session-in-another-run-directory": {INCOMPLETE, reason("MANIFEST_RUN_EVIDENCE_MISSING", f"{WF_FIELD}->{path_of(RUN_WF, 'run_session_0001.json')}")},
    "32-uppercase-hex-reference": {INCOMPLETE, reason("MANIFEST_RUN_ID_INVALID", f"{WF_FIELD}={RUN_WF_UPPER}")},
    "28-ready-with-empty-walk-forward-directory": set(),            # un répertoire n'est pas un artefact d'exécution ici : v5 bloque déjà le squelette
}
# Historique mesuré sur v4 ET v5 (défaut démontré) : scénarios dont l'inventaire est complet, FRESH-éligible et effectivement classé FRESH.
HISTORICAL_FRESH = {"01-ready-initial", "02-wf-declared-directory-absent", "07-running-validations-empty", "08-technical-failure-validations-empty",
                    "09-evidence-incomplete-nothing-declared", "15-exposure-empty-ready", "17-complete-claimed-without-any-reference",
                    "18-no-manifest-validations-empty", "20-foreign-run-reference", "21-wrong-kind-reference", "22-running-flag-without-running-status", "23-ready-with-failure-reason", "29-ready-with-revision-above-zero",
                    "30-ready-with-reference-not-started", "32-uppercase-hex-reference"}
LEGITIMATE = {"01-ready-initial", "15-exposure-empty-ready", "18-no-manifest-validations-empty"}      # aucune exécution déclarée : rien à corriger


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    base = tmp_path_factory.mktemp("n_vide_1")
    out = {}
    for name, scenario in SCENARIOS.items():
        directory = realise(base / name, scenario)
        roots = roots_of(directory)
        i4, i5, i6 = interpret_v4(roots), interpret_v5(roots), interpret_v6(roots)
        out[name] = (i4, i5, i6, assess(i4), assess(i5), assess(i6))
    return out


# ══ 1. Le défaut, démontré sur B3 v4 ET B3 v5 (historique gelé) ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_historically_v4_and_v5_agree_and_the_defect_is_pinned_down(results, name):
    a4, a5 = results[name][3], results[name][4]
    assert (a4.classification == FRESH) == (a5.classification == FRESH) == (name in HISTORICAL_FRESH), (name, a4.classification, a5.classification)
    assert a4.fresh_eligible == a5.fresh_eligible == (name in HISTORICAL_FRESH)
    if name in HISTORICAL_FRESH - LEGITIMATE:
        assert a4.complete and a5.complete and a5.reasons == () and a5.reservation == ()           # inventaire « complet » ET la précondition RESERVATION ne refuse pas : le défaut


def test_the_defect_scenarios_are_exactly_those_where_a_declaration_is_contradicted_or_ignored():
    assert HISTORICAL_FRESH - LEGITIMATE == {"29-ready-with-revision-above-zero", "30-ready-with-reference-not-started", "32-uppercase-hex-reference", "02-wf-declared-directory-absent", "07-running-validations-empty", "08-technical-failure-validations-empty",
                                             "09-evidence-incomplete-nothing-declared", "17-complete-claimed-without-any-reference", "20-foreign-run-reference",
                                             "21-wrong-kind-reference", "22-running-flag-without-running-status", "23-ready-with-failure-reason"}


# ══ 2. Matrice de décisions v6 : raisons exactes, complétude, classification ════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_v6_adds_exactly_the_expected_manifest_reasons_and_nothing_else(results, name):
    _, _, _, _, a5, a6 = results[name]
    assert set(a6.reasons) - set(a5.reasons) == NEW_REASONS[name]
    assert set(a5.reasons) <= set(a6.reasons)
    assert a6.reasons == tuple(sorted(set(a6.reasons)))                                         # déterministes : triées, sans doublon
    assert a6.semantics_version == "gate_v_exposure_interpreters_v6" and a5.semantics_version == v5.B3_V5_SEMANTICS_VERSION


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_v6_removes_every_fresh_eligibility_that_a_declaration_contradicts_and_keeps_the_legitimate_ones(results, name):
    _, _, _, _, a5, a6 = results[name]
    if name in LEGITIMATE:
        assert (a6.complete, a6.fresh_eligible, a6.classification) == (a5.complete, a5.fresh_eligible, a5.classification) == (True, True, FRESH)
    elif NEW_REASONS[name]:
        assert a6.complete is False and a6.fresh_eligible is False and a6.classification != FRESH and a6.inventory_complete is False
    else:
        assert (a6.complete, a6.fresh_eligible) == (a5.complete, a5.fresh_eligible)
    if name in HISTORICAL_FRESH - LEGITIMATE:
        assert a6.classification != FRESH and a6.complete is False and a6.fresh_eligible is False


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_an_incomplete_v6_inventory_is_never_a_retrospective_exposure_and_gets_no_new_source_kind(results, name):
    i5, i6 = results[name][1], results[name][2]
    assert i6.findings == i5.findings                                                              # AUCUN finding fabriqué : une preuve manquante n'est pas une exposition
    assert not any(f.source_id.startswith("campaign.manifest") for f in i6.findings)               # le manifeste de campagne n'est jamais un finding
    assert {f.source_kind for f in i6.findings} <= {f.source_kind for f in i5.findings}
    for field in ("scans", "plans", "non_oos_validations", "exposure_evidence", "holdout_window_start_utc", "holdout_window_end_utc"):
        assert getattr(i6, field) == getattr(i5, field), field


def test_a_new_inventory_identity_is_acceptable_only_when_complete_changes(results):
    for name, (_, _, _, _, a5, a6) in results.items():
        if not NEW_REASONS[name]:
            assert a6.inventory_id == a5.inventory_id and a6.classification == a5.classification and (a6.reservation, a6.admission) == (a5.reservation, a5.admission), name
        else:
            assert a6.inventory_complete is False


# ══ 3. Invariants différentiels v5 → v6 ═════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_v6_is_never_less_blocking_than_v5(results, name):
    _, _, _, a4, a5, a6 = results[name]
    assert (not a5.complete) <= (not a6.complete)
    assert a5.unresolved <= a6.unresolved
    assert a6.fresh_eligible <= a5.fresh_eligible
    assert (a6.classification == FRESH) <= (a5.classification == FRESH)
    assert set(a5.reservation) <= set(a6.reservation) and set(a5.admission) <= set(a6.admission)
    assert a6.findings == a5.findings


def test_v5_that_is_undetermined_on_unverified_evidence_is_never_fresh_under_v6_by_recognition_alone(results):
    for name in ("05-coverage-without-session", "06-session-without-seal", "10-complete-claimed-seal-missing", "26-complete-claimed-without-monte-carlo-reference",
                 "25-all-declared-runs-present", "04-record-without-coverage"):
        _, _, _, _, a5, a6 = results[name]
        assert a5.classification != FRESH and a6.classification != FRESH and a6.complete is False, name
    for name in ("25-all-declared-runs-present",):
        a5, a6 = results[name][4], results[name][5]
        assert "RUN_EVIDENCE_UNVERIFIED" in {r.split(":")[0] for r in a6.reasons}                    # v6 ne lève JAMAIS les raisons non résolues de v5
        assert not [r for r in a6.reasons if r.startswith("MANIFEST_")] and set(a6.reasons) == set(a5.reasons)


def test_a_complete_apparent_chain_is_not_an_exclusion_proof_and_declared_mc_ps_runs_do_not_lift_their_unresolved_reasons(results):
    a6 = results["25-all-declared-runs-present"][5]
    assert a6.complete is False and a6.fresh_eligible is False and a6.unresolved > 0
    assert any(r.startswith("RUN_EVIDENCE_UNVERIFIED:") for r in a6.reasons)


def test_every_new_reason_is_typed_and_attributable_to_the_root_the_manifest_and_the_reference(results):
    allowed = {"MANIFEST_RUN_IN_PROGRESS", "MANIFEST_TECHNICAL_FAILURE", "MANIFEST_EVIDENCE_INCOMPLETE", "MANIFEST_RUN_ABSENT", "MANIFEST_RUN_EVIDENCE_MISSING",
               "MANIFEST_RUN_FOREIGN", "MANIFEST_RUN_ID_INVALID", "MANIFEST_STATE_CONTRADICTION", "MANIFEST_ARTEFACTS_WITHOUT_EXECUTION"}
    produced = set()
    for name, (_, _, _, _, a5, a6) in results.items():
        for text in set(a6.reasons) - set(a5.reasons):
            code, _, rest = text.partition(":")
            assert code in allowed and rest.startswith("camp/manifest.json#") and len(rest) > len("camp/manifest.json#"), text
            produced.add(code)
    assert produced == allowed                                                                      # chaque code est exercé par au moins un scénario
    assert {getattr(v6, n) for n in dir(v6) if n.startswith("REASON_MANIFEST")} == allowed
    assert not allowed & {m.value for m in b3.IncompleteReason} and not allowed & {getattr(v5, n) for n in dir(v5) if type(getattr(v5, n)) is str}


# ══ 4. Attribution : racines, campagnes, références ══════════════════════════════════════════════════════════════════════════════════
def write_manifest(directory: Path, **changes) -> None:
    (directory / "manifest.json").write_bytes(json.dumps(manifest_record(**changes), indent=2).encode())


def test_reasons_are_attributed_to_the_root_whose_manifest_declares_them_and_never_to_another(tmp_path):
    first = realise(tmp_path / "a", SCENARIOS["07-running-validations-empty"])                     # campagne CID : RUNNING
    second = tmp_path / "b" / OTHER_CID
    write_json(second / "plan.json", {"campaign_id": OTHER_CID})
    write_manifest(second, campaign_id=OTHER_CID)                                                   # campagne étrangère : état initial légitime
    (second / "validations").mkdir()
    roots = (b3.LayoutRoot(CAMPAIGN, AuditRoot("first", str(first))), b3.LayoutRoot(CAMPAIGN, AuditRoot("second", str(second))))
    new = set(interpret_v6(roots).incomplete_reasons) - set(interpret_v5(roots).incomplete_reasons)
    assert new == {reason("MANIFEST_RUN_IN_PROGRESS", "status", "first")}


@pytest.mark.parametrize("label", ["alpha", "zeta-2", "A", "camp"])
def test_a_manifest_is_confronted_with_the_files_of_its_own_root_whatever_the_root_label(tmp_path, label):
    complete = realise(tmp_path / "complete", SCENARIOS["25-all-declared-runs-present"])
    roots = (b3.LayoutRoot(CAMPAIGN, AuditRoot(label, str(complete))),)
    assert set(interpret_v6(roots).incomplete_reasons) == set(interpret_v5(roots).incomplete_reasons)     # toutes les références présentes : aucune raison MANIFEST_*
    absent = realise(tmp_path / "absent", SCENARIOS["02-wf-declared-directory-absent"])
    new = set(interpret_v6((b3.LayoutRoot(CAMPAIGN, AuditRoot(label, str(absent))),)).incomplete_reasons) - set(
        interpret_v5((b3.LayoutRoot(CAMPAIGN, AuditRoot(label, str(absent))),)).incomplete_reasons)
    assert new == {reason(code, ref, label) for code, ref in ((
        "MANIFEST_RUN_ABSENT", f"{WF_FIELD}->{path_of(RUN_WF, 'validation_run.json')}"), ("MANIFEST_EVIDENCE_INCOMPLETE", "status"))}


def test_two_campaign_roots_are_judged_independently_each_against_its_own_files(tmp_path):
    full = realise(tmp_path / "a", SCENARIOS["25-all-declared-runs-present"])                      # références toutes présentes dans CETTE racine
    other = tmp_path / "b" / OTHER_CID
    write_json(other / "plan.json", {"campaign_id": OTHER_CID})
    write_manifest(other, campaign_id=OTHER_CID)                                                    # READY initial...
    (other / "walk_forward").mkdir()
    (other / "walk_forward" / "manifest.json").write_bytes(b"{}")                                   # ...mais des sorties d'exécution existent DANS CETTE racine seulement
    roots = (b3.LayoutRoot(CAMPAIGN, AuditRoot("a-full", str(full))), b3.LayoutRoot(CAMPAIGN, AuditRoot("b-ready", str(other))))
    new = set(interpret_v6(roots).incomplete_reasons) - set(interpret_v5(roots).incomplete_reasons)
    assert new == {reason("MANIFEST_ARTEFACTS_WITHOUT_EXECUTION", "walk_forward/manifest.json", "b-ready")}


def test_a_run_record_that_exists_only_in_another_root_does_not_satisfy_the_manifest_reference(tmp_path):
    own = realise(tmp_path / "own", SCENARIOS["02-wf-declared-directory-absent"])
    other = tmp_path / "other" / OTHER_CID
    write_json(other / "plan.json", {"campaign_id": OTHER_CID})
    write_json(other / "validations" / RUN_WF / "validation_run.json", {"x": 1})                    # le run de CID, déposé dans la racine d'une autre campagne
    roots = (b3.LayoutRoot(CAMPAIGN, AuditRoot("own", str(own))), b3.LayoutRoot(CAMPAIGN, AuditRoot("other", str(other))))
    new = set(interpret_v6(roots).incomplete_reasons) - set(interpret_v5(roots).incomplete_reasons)
    assert reason("MANIFEST_RUN_ABSENT", f"{WF_FIELD}->{path_of(RUN_WF, 'validation_run.json')}", "own") in new


def test_a_manifest_of_another_campaign_is_never_used_to_derive_expectations(tmp_path):
    """Manifeste conforme mais d'une AUTRE campagne que le dossier : B3 le déclare non conforme (INFORMATIVE_UNRESOLVED), v6 n'en tire aucune attente ni aucune référence."""
    directory = realise(tmp_path, SCENARIOS["14-foreign-manifest"])
    i5, i6 = interpret_v5(roots_of(directory)), interpret_v6(roots_of(directory))
    assert i6.incomplete_reasons == i5.incomplete_reasons and any(r.startswith("INFORMATIVE_UNRESOLVED:") for r in i6.incomplete_reasons)


def test_the_manifest_is_taken_from_the_scan_never_from_a_caller_supplied_object(tmp_path):
    import inspect
    assert list(inspect.signature(v6.interpret_audit_roots_v6).parameters) == ["roots", "limits", "hash_limits", "holdout_window_start_utc", "holdout_window_end_utc", "hooks"]
    directory = realise(tmp_path, SCENARIOS["02-wf-declared-directory-absent"])
    write_manifest(directory)                                                                       # le fichier sur disque redevient READY : v6 relit le disque
    assert set(interpret_v6(roots_of(directory)).incomplete_reasons) == set(interpret_v5(roots_of(directory)).incomplete_reasons)


def test_an_unreadable_manifest_follows_the_historical_blocking_path(tmp_path):
    directory = realise(tmp_path, SCENARIOS["16a-manifest-corrupt-bytes"])
    assert interpret_v6(roots_of(directory)).complete is False
    (directory / "manifest.json").write_bytes(b"\xff\xfe\x00")
    result = interpret_v6(roots_of(directory))
    assert result.complete is False and set(result.incomplete_reasons) == set(interpret_v5(roots_of(directory)).incomplete_reasons)


# ══ 5. Hooks, instabilité entre deux passes, racines may_be_empty ══════════════════════════════════════════════════════════════════
def test_a_scan_with_hooks_keeps_no_authority_under_v6(tmp_path):
    directory = realise(tmp_path, SCENARIOS["07-running-validations-empty"])
    calls = []
    hooked = interpret_v6(roots_of(directory), hooks=ScanHooks(after_first_pass=calls.append))
    assert calls and hooked.hooks_used is True and interpret_v6(roots_of(directory)).hooks_used is False
    assert hooked.incomplete_reasons == interpret_v6(roots_of(directory)).incomplete_reasons


@pytest.mark.parametrize("mutation", ["rewrite", "delete", "grow"])
def test_a_manifest_that_changes_or_disappears_between_the_two_passes_is_refused_not_interpreted(tmp_path, mutation):
    directory = realise(tmp_path, SCENARIOS["07-running-validations-empty"])
    target = directory / "manifest.json"

    def hook(attempt):
        if mutation == "rewrite":
            write_manifest(directory, status="READY_FOR_EXECUTION", execution_started=False, running=False)
        elif mutation == "delete":
            target.unlink()
        else:
            target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ExposureScanRefusal) as caught:
        interpret_v6(roots_of(directory), hooks=ScanHooks(after_first_pass=hook))
    assert caught.value.failure is scan.StructuralFailure.UNSTABLE_LISTING


def test_may_be_empty_roots_and_empty_directories_behave_like_v5(tmp_path):
    empty = tmp_path / "empty" / CID
    empty.mkdir(parents=True)
    roots = (b3.LayoutRoot(CAMPAIGN, AuditRoot("camp", str(empty), may_be_empty=True)),)
    assert interpret_v6(roots).incomplete_reasons == interpret_v5(roots).incomplete_reasons
    strict = (b3.LayoutRoot(CAMPAIGN, AuditRoot("camp", str(empty))),)
    with pytest.raises(ExposureScanRefusal):
        interpret_v6(strict)
    with pytest.raises(ExposureScanRefusal):
        interpret_v5(strict)


@pytest.mark.parametrize("extra", [{"stray.txt": b"x"}, {f"validations/{RUN_WF}/validation_run.json.{'ab' * 16}.tmp": b"half"}, {"walk_forward/folds/fold_000/notes.txt": b"x"}])
def test_orphans_unknown_files_stay_blocking_exactly_as_in_v5(tmp_path, extra):
    directory = realise(tmp_path, SCENARIOS["01-ready-initial"])
    for relative, data in extra.items():
        (directory / relative).parent.mkdir(parents=True, exist_ok=True)
        (directory / relative).write_bytes(data)
    r5, r6 = interpret_v5(roots_of(directory)), interpret_v6(roots_of(directory))
    assert r6.complete is False and set(r5.incomplete_reasons) <= set(r6.incomplete_reasons) and r6.findings == r5.findings


def test_a_v5_directory_skeleton_stays_blocking(tmp_path):
    skeleton = realise(tmp_path, SCENARIOS["01-ready-initial"])
    (skeleton / "walk_forward" / "folds" / "fold_000").mkdir(parents=True)
    assert interpret_v6(roots_of(skeleton)).complete is False


def test_hashed_walk_forward_outputs_and_proof_files_keep_their_unresolved_findings(results):
    i5, i6 = results["25-all-declared-runs-present"][1], results["25-all-declared-runs-present"][2]
    assert i6.findings == i5.findings and len(i6.findings) > 0
    assert all(f.status.value == "UNRESOLVED" for f in i6.findings if f.source_id.startswith(("validation.", "wf.")))


# ══ 6. Performance ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_v6_costs_a_small_constant_factor_over_v5_on_a_large_inventory(tmp_path):
    directory = realise(tmp_path, SCENARIOS["13-several-runs-one-missing"])
    for index in range(1500):
        run = f"gate_v_v2_{index:064x}_walk_forward"
        write_json(directory / "validations" / run / "validation_run.json", {"validation_run_id": run, "validation_type": "walk_forward"})
    limits = ScanLimits(max_roots=8, max_entries=20_000, max_depth=8, max_json_bytes=1_000_000, max_total_read_bytes=64_000_000, max_json_depth=32,
                        max_name_length=128, max_path_length=1_024, max_attempts=1)
    kwargs = dict(hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    started = time.perf_counter()
    r5 = v5.interpret_audit_roots_v5(roots_of(directory), limits, **kwargs)
    t5 = time.perf_counter() - started
    started = time.perf_counter()
    r6 = v6.interpret_audit_roots_v6(roots_of(directory), limits, **kwargs)
    t6 = time.perf_counter() - started
    assert len(r6.findings) > 1500 and r6.findings == r5.findings and set(r5.incomplete_reasons) < set(r6.incomplete_reasons)
    assert t6 < t5 * 1.6 + 1.0, (t5, t6)                                                              # le surcoût de v6 est linéaire et petit


# ══ 7. Version, digests, activation explicite, garde-fous ══════════════════════════════════════════════════════════════════════════
def oracle_digest(rules) -> str:
    """Oracle indépendant de `gate_v_exposure_scan._rules_digest` (même sérialisation canonique que le test de v5)."""
    lines = sorted(json.dumps({"segments": [s if type(s) is str else {"regex": s.regex} for s in r.segments], "entry_class": r.entry_class.value,
                               "expected_json": r.expected_json.value if r.expected_json else None, "tag": r.tag},
                              sort_keys=True, separators=(",", ":"), ensure_ascii=True) for r in rules)
    return hashlib.sha256("\n".join(lines).encode("ascii")).hexdigest()


def test_v6_has_its_own_semantic_version_and_leaves_every_historical_version_untouched():
    assert v6.B3_V6_SEMANTICS_VERSION == "gate_v_exposure_interpreters_v6"
    assert v6.B3_V6_SEMANTICS_VERSION not in b3.KNOWN_B3_VERSIONS and v6.B3_V6_SEMANTICS_VERSION != v5.B3_V5_SEMANTICS_VERSION
    assert b3.B3_SEMANTICS_VERSION == "gate_v_exposure_interpreters_v4" and v5.B3_V5_SEMANTICS_VERSION == "gate_v_exposure_interpreters_v5"
    assert len(b3.B3_RULES_DIGESTS) == 9 and len(v5.B3_V5_RULES_DIGESTS) == 3


def test_the_v6_table_is_strictly_the_v5_table_and_its_digest_is_recomputed_independently_not_imposed():
    for layout in b3.RootLayout:
        rules = v6.source_rules_v6(layout)
        assert rules == v5.source_rules_v5(layout)
        digest = {l: d for version, l, d in v6.B3_V6_RULES_DIGESTS if version == v6.B3_V6_SEMANTICS_VERSION}[layout]
        assert digest == scan._rules_digest(rules) == oracle_digest(rules)                           # recalcul par l'algorithme de B2 ET par un oracle écrit à part
    assert {l: d for _, l, d in v6.B3_V6_RULES_DIGESTS} == {l: d for _, l, d in v5.B3_V5_RULES_DIGESTS}   # égalité constatée, non imposée par construction
    assert {version for version, _, _ in v6.B3_V6_RULES_DIGESTS} == {v6.B3_V6_SEMANTICS_VERSION} and len(v6.B3_V6_RULES_DIGESTS) == 3


def test_v6_is_activated_only_by_its_explicit_api_and_v5_keeps_its_own_semantics(tmp_path):
    directory = realise(tmp_path, SCENARIOS["07-running-validations-empty"])
    assert interpret_v5(roots_of(directory)).semantics_version == v5.B3_V5_SEMANTICS_VERSION
    assert interpret_v4(roots_of(directory)).semantics_version == b3.B3_SEMANTICS_VERSION
    assert interpret_v6(roots_of(directory)).semantics_version == v6.B3_V6_SEMANTICS_VERSION
    assert "interpret_audit_roots_v6" not in vars(b3) and "interpret_audit_roots_v6" not in vars(v5) and "source_rules_v6" not in vars(b3)
    with pytest.raises(TypeError):
        v6.interpret_audit_roots_v6(roots_of(directory), LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])           # hash_limits obligatoire
    with pytest.raises(TypeError):
        v6.interpret_audit_roots_v6(roots_of(directory), LIMITS, hash_limits=object(), holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])


def test_the_v6_module_is_pure_independent_of_l3a_and_adds_no_source_kind():
    text = Path(v6.__file__).read_text(encoding="utf-8")
    tree = ast.parse(text)
    imported = {(n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
                for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (getattr(n, "names", None) or [None])}
    assert imported <= {"__future__", "dataclasses", "os", "re", "typing", "gate_v_exposure_interpreters", "gate_v_exposure_interpreters_v5", "gate_v_exposure_scan"}, imported
    assert "gate_v_k1s2" not in text                                                                 # L3-A ne sert jamais à octroyer une absence d'exposition
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "eval", "exec", "__import__", "compile", "print"}
    assert not {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} & {"read_bytes", "read_text", "write_bytes", "write_text", "scandir", "listdir", "walk", "unlink", "sha256"}
    assert "SourceKind" not in text and "ExposureFinding" not in text                               # aucune nouvelle valeur, aucune fabrication de finding


def test_only_b5_and_nothing_else_imports_or_calls_v6():
    root = Path(v6.__file__).parent
    importers, callers = set(), set()
    for directory, subdirectories, names in os.walk(root):
        subdirectories[:] = [d for d in subdirectories if d not in {".venv", "venv", ".git", "node_modules", "tests", "__pycache__", "frontend"}]
        for name in names:
            if not name.endswith(".py") or name == "gate_v_exposure_interpreters_v6.py":
                continue
            text = Path(directory, name).read_text(encoding="utf-8", errors="replace")
            relative = os.path.relpath(os.path.join(directory, name), root).replace(os.sep, "/")
            if "gate_v_exposure_interpreters_v6" in text:
                importers.add(relative)
            if "interpret_audit_roots_v6" in text:
                callers.add(relative)
    assert importers == {"gate_v_exposure_store.py"} and not callers, (importers, callers)


# ══ 8. Identités historiques gelées, identité d'un nouvel inventaire v6, énumération exhaustive de la fonction de décision ═════════════════════════
HISTORICAL_IDS = {                                   # littéraux mesurés AVANT toute modification de ce lot (B3 v4 / v5, B4, E3-A inchangés)
    "01-ready-initial": ("831ccdafe5dbe5949a93c37b59ed53f2d14dd41e82ed0594d56f4e8a72183ab5", "831ccdafe5dbe5949a93c37b59ed53f2d14dd41e82ed0594d56f4e8a72183ab5"),
    "14-foreign-manifest": ("1cfa0cf4a84dd30da631b836219a7f0d2ffe2b33cadd5a1185d09f453a38ffcc", "1cfa0cf4a84dd30da631b836219a7f0d2ffe2b33cadd5a1185d09f453a38ffcc"),
    "25-all-declared-runs-present": ("4c7a820960fab37db57991ed1a98a4a7d23fb924412d022c759d71aec211bb5a", "77efa48248349f7eb9d913715124797fd578029903791fc33c9ec944a65d7af7"),
}


@pytest.mark.parametrize("name", sorted(HISTORICAL_IDS))
def test_the_historical_v4_and_v5_inventory_identities_are_frozen_and_v6_does_not_rewrite_them(results, name):
    expected_v4, expected_v5 = HISTORICAL_IDS[name]
    assert results[name][3].inventory_id == expected_v4 and results[name][4].inventory_id == expected_v5
    if not NEW_REASONS[name]:
        assert results[name][5].inventory_id == expected_v5                                        # v6 sans raison nouvelle : même identité que v5


def test_a_corrected_completeness_yields_a_new_identity_only_for_the_new_v6_inventory(results):
    from tests.gate_v_manifest_scenarios import assess as _assess  # noqa: F401  (même chemin d'évaluation que les autres tests)
    a5, a6 = results["07-running-validations-empty"][4], results["07-running-validations-empty"][5]
    assert a5.inventory_id == "831ccdafe5dbe5949a93c37b59ed53f2d14dd41e82ed0594d56f4e8a72183ab5"       # l'identité historique de v5 est intacte
    assert a6.inventory_id != a5.inventory_id and a6.inventory_complete is False and a5.inventory_complete is True


def decision_record(**changes) -> dict:
    return manifest_record(**changes)


def test_a_ready_manifest_with_a_revision_above_zero_is_a_contradiction_for_every_other_input_and_a_non_ready_one_never_is():
    """Le producteur réel incrémente `manifest_revision` à chaque commande ; seul le manifeste initial (READY, révision 0) existe sans commande. Une révision > 0 est donc une preuve POSITIVE
    d'activité passée, portée par le manifeste lui-même (aucune inférence tirée d'un dossier vide)."""
    marker = reason("MANIFEST_STATE_CONTRADICTION", "ready_vs_revision")
    for revision in (0, 1, 5, 10 ** 6):
        for files in (set(), {path_of(RUN_WF, "validation_run.json")}, {"walk_forward/state.json"}):
            ready = v6._manifest_reasons("camp", CID, decision_record(manifest_revision=revision), files)
            assert (marker in ready) == (revision > 0), (revision, files)
            for status, extra in (("RUNNING", {"running": True}), ("TECHNICAL_FAILURE", {"technical_failure_reason": "x"}), ("EVIDENCE_INCOMPLETE", {}),
                                  ("EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT", {})):
                other = v6._manifest_reasons("camp", CID, decision_record(manifest_revision=revision, status=status, execution_started=True, **extra), files)
                assert marker not in other


def test_the_decision_function_is_silent_only_for_a_legitimate_initial_state_or_a_fully_referenced_complete_state():
    import itertools
    ids = {"wf": RUN_WF, "mc": RUN_MC, "ps": RUN_PS}
    pieces = {"wf": path_of(RUN_WF, "validation_run.json"), "mc": path_of(RUN_MC, "validation_run.json"), "ps": path_of(RUN_PS, "validation_run.json"),
              "cov": path_of(RUN_WF, "run_data_coverage.json"), "ses": path_of(RUN_WF, "run_session_0003.json"), "seal": path_of(RUN_WF, "run_seal.json"),
              "out": "walk_forward/state.json"}
    statuses = ("READY_FOR_EXECUTION", "RUNNING", "EVIDENCE_INCOMPLETE", "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT", "TECHNICAL_FAILURE")
    silent = cases = 0
    for status, started, running, failure in itertools.product(statuses, (False, True), (False, True), (None, "boom")):
        for declared in itertools.chain.from_iterable(itertools.combinations(("wf", "mc", "ps"), n) for n in range(4)):
            record = decision_record(status=status, execution_started=started, running=running, technical_failure_reason=failure,
                                     walk_forward_validation_run_id=ids["wf"] if "wf" in declared else None, monte_carlo_validation_run_id=ids["mc"] if "mc" in declared else None,
                                     parameter_stability_validation_run_ids_by_fold={"fold_000": ids["ps"]} if "ps" in declared else {})
            for present in itertools.chain.from_iterable(itertools.combinations(sorted(pieces), n) for n in range(len(pieces) + 1)):
                files = {pieces[key] for key in present}
                reasons = v6._manifest_reasons("camp", CID, record, files)
                assert reasons == v6._manifest_reasons("camp", CID, record, files)                                  # déterministe
                assert all(r.partition(":")[2].startswith("camp/manifest.json#") for r in reasons)
                initial = (status == "READY_FOR_EXECUTION" and not started and not running and failure is None and not declared and not present)
                full = (status == "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT" and not running and failure is None and set(declared) == {"wf", "mc", "ps"}
                        and {"wf", "mc", "ps", "cov", "ses", "seal"} <= set(present))           # sessions : un fichier numéroté quelconque suffit (ici 0003)
                if status in ("RUNNING", "TECHNICAL_FAILURE", "EVIDENCE_INCOMPLETE"):
                    assert reasons, (status, declared, present)                                                      # jamais silencieux sur un état d'activité, d'échec ou d'incomplétude
                if not reasons:
                    silent += 1
                    assert initial or full, (status, started, running, failure, declared, present)                  # le silence n'a que deux justifications
                if initial or full:
                    assert reasons == [], (status, declared, present, reasons)                                       # et elles ne produisent jamais de fausse alerte
                cases += 1
    assert cases == 5 * 2 * 2 * 2 * 8 * 128 and 0 < silent < cases
