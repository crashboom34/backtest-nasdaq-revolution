"""K1 Étape 2, lot L3-A, section 6 : caractérisation des répertoires VIDES et diagnostic A / B / C (`gate_v_k1s2_emptiness`).

Deux familles de tests :
 1. CARACTÉRISATION, séparément pour B3 v4 (publié) et B3 v5-A, sur des arbres réels (`tmp_path`, contenus synthétiques) : ce que B3 fait AUJOURD'HUI. Plusieurs
    situations qu'un manifeste impose (run déclaré absent, RUNNING, TECHNICAL_FAILURE) restent FRESH-éligibles : lacune PRÉEXISTANTE, identique en v4 et v5, NON
    corrigée ici (modules historiques hors périmètre). Ces tests la figent pour qu'un changement futur de B3 soit délibéré, jamais silencieux.
 2. DIAGNOSTIC : la catégorie rendue par le module pur pour les mêmes arbres, lus par le vrai scan B2 puis convertis.
Aucune donnée de marché, aucun FINAL_HOLDOUT. Le diagnostic n'émet aucun verdict.
"""

from __future__ import annotations

import ast
import hashlib
import json
import time
from pathlib import Path

import pytest

import gate_v_exposure_interpreters as b3
import gate_v_exposure_interpreters_v5 as v5
import gate_v_exposure_scan as scan
import gate_v_k1s2_emptiness as em
import gate_v_k1s2_observations as obs
import gate_v_k1s2_verifier as vf
from gate_v_exposure_scan import AuditRoot, HashLimits
from tests.gate_v_exposure_support import LIMITS, W, write_json
from tests.test_gate_v_exposure_interpreters_v4 import CID as REAL_CID, manifest_record
from tests.test_gate_v_exposure_interpreters_v5 import run_record
from tests.test_gate_v_exposure_v4_v5_differential import freshable
from tests.test_gate_v_k1s2_verifier import world

HL = HashLimits(max_hashed_file_bytes=65_536, max_total_hashed_bytes=2_000_000, max_hashed_files=200)
CAMPAIGN = b3.RootLayout.CAMPAIGN_DIR
RUN_ID = f"{REAL_CID}_walk_forward"
C = em.EmptinessCategory
R = em.EmptinessReason
ORPHAN_NAME = "." + "ab" * 16 + ".tmp"
STARTED = {"execution_started": True}
DECLARES = {"walk_forward_validation_run_id": RUN_ID, "status": "EVIDENCE_INCOMPLETE", **STARTED}
RUNNING = {"status": "RUNNING", "running": True, **STARTED}
FAILED = {"status": "TECHNICAL_FAILURE", "technical_failure_reason": "boom", **STARTED}
EXPECTED_BLOCKING_RUN_ID = f"validations/{RUN_ID}"


def realise(base: Path, *, manifest=None, dirs=(), files=None, run_record_for=None) -> Path:
    directory = base / REAL_CID
    write_json(directory / "plan.json", {"campaign_id": REAL_CID})
    if manifest is not None:
        (directory / "manifest.json").write_bytes(json.dumps(manifest_record(**manifest), indent=2).encode())
    if run_record_for:
        write_json(directory / "validations" / run_record_for / "validation_run.json", run_record(run_record_for))
    for relative, data in (files or {}).items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for relative in dirs:
        (directory / relative).mkdir(parents=True, exist_ok=True)
    return directory


def interpretations(directory: Path):
    roots = (b3.LayoutRoot(CAMPAIGN, AuditRoot("camp", str(directory))),)
    historical = b3.interpret_audit_roots(roots, LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    current = v5.interpret_audit_roots_v5(roots, LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    return historical, current


def diagnosis(directory: Path) -> em.EmptinessDiagnostic:
    result = scan.scan_audit_roots((AuditRoot("camp", str(directory)),), v5.source_rules_v5(CAMPAIGN), LIMITS, hash_limits=HL)
    return em.diagnose_emptiness(obs.observed_tree_from_scan(result, root_label="camp", campaign_dir_name=REAL_CID))


# nom → (arguments de `realise`, FRESH-éligible en v4, FRESH-éligible en v5, catégorie, raisons attendues)
SITUATIONS = {
    "anchor-only": (dict(), True, True, C.A_EMPTY_NO_DECLARATION, {R.NO_DECLARATION_FOUND}),
    "validations-empty": (dict(dirs=["validations"]), True, True, C.A_EMPTY_NO_DECLARATION, {R.NO_DECLARATION_FOUND}),
    "exposure-empty": (dict(dirs=["exposure"]), True, True, C.A_EMPTY_NO_DECLARATION, {R.NO_DECLARATION_FOUND}),
    "validations-and-exposure-empty": (dict(dirs=["validations", "exposure"]), True, True, C.A_EMPTY_NO_DECLARATION, {R.NO_DECLARATION_FOUND}),
    "ready-manifest-validations-empty": (dict(manifest={}, dirs=["validations"]), True, True, C.A_EMPTY_NO_DECLARATION, {R.NO_DECLARATION_FOUND}),
    # GAP préexistant : le manifeste annonce un run, rien n'est là, et B3 (v4 ET v5) laisse FRESH possible.
    "manifest-declares-run-validations-absent": (dict(manifest=DECLARES), True, True, C.B_ARTEFACT_IMPOSED_BUT_ABSENT, {R.DECLARED_RUN_DIRECTORY_ABSENT}),
    "manifest-declares-run-validations-empty": (dict(manifest=DECLARES, dirs=["validations"]), True, True, C.B_ARTEFACT_IMPOSED_BUT_ABSENT, {R.DECLARED_RUN_DIRECTORY_ABSENT}),
    "manifest-declares-run-run-directory-empty": (dict(manifest=DECLARES, dirs=[EXPECTED_BLOCKING_RUN_ID]), False, False, C.B_ARTEFACT_IMPOSED_BUT_ABSENT,
                                                  {R.DECLARED_RUN_DIRECTORY_EMPTY}),
    "running-manifest-validations-empty": (dict(manifest=RUNNING, dirs=["validations"]), True, True, C.C_ATTESTED_INTERRUPTION, {R.MANIFEST_RUNNING}),
    "running-manifest-empty-walk-forward": (dict(manifest=RUNNING, dirs=["walk_forward"]), False, False, C.C_ATTESTED_INTERRUPTION, {R.MANIFEST_RUNNING}),
    "technical-failure-validations-empty": (dict(manifest=FAILED, dirs=["validations"]), True, True, C.C_ATTESTED_INTERRUPTION, {R.MANIFEST_TECHNICAL_FAILURE}),
    "completed-state-run-record-without-proofs": (dict(manifest=DECLARES, run_record_for=RUN_ID), False, False, C.B_ARTEFACT_IMPOSED_BUT_ABSENT,
                                                  {R.RUN_RECORD_WITHOUT_EVIDENCE}),
    "run-directory-with-only-a-publication-orphan": (dict(files={f"validations/{RUN_ID}/validation_run.json{ORPHAN_NAME}": b"half"}), False, False,
                                                     C.C_ATTESTED_INTERRUPTION, {R.PUBLICATION_ORPHAN}),
    "foreign-manifest-contradictory-state": (dict(manifest={"campaign_id": "gate_v_v2_" + "ee" * 32}), False, False, C.CONTRADICTORY, {R.FOREIGN_MANIFEST}),
    "ready-manifest-but-outputs-present": (dict(manifest={}, files={"walk_forward/manifest.json": b"{}"}), False, False, C.CONTRADICTORY,
                                           {R.ARTEFACTS_WITHOUT_EXECUTION}),
}


@pytest.mark.parametrize("name", sorted(SITUATIONS))
def test_b3_v4_and_v5_behaviour_on_each_empty_directory_situation_is_pinned(tmp_path, name):
    arguments, fresh_v4, fresh_v5, _, _ = SITUATIONS[name]
    historical, current = interpretations(realise(tmp_path, **arguments))
    assert (freshable(historical), freshable(current)) == (fresh_v4, fresh_v5)


@pytest.mark.parametrize("name", sorted(SITUATIONS))
def test_the_diagnostic_classifies_each_situation_from_the_real_scan(tmp_path, name):
    arguments, _, _, category, reasons = SITUATIONS[name]
    result = diagnosis(realise(tmp_path, **arguments))
    assert result.category is category and reasons <= set(result.reasons), (result.category, result.reasons)
    assert result.requires_independent_rescan is True and set(result.not_proven) == set(vf.NOT_PROVEN)


def test_every_situation_that_b3_leaves_fresh_eligible_despite_an_imposed_artefact_is_blocked_by_the_diagnostic(tmp_path):
    """Le point central : là où B3 (v4 comme v5) ne bloque pas, le diagnostic bloque toute considération d'absence (B, C, CONTRADICTORY)."""
    gaps = []
    for name, (arguments, fresh_v4, fresh_v5, category, _) in SITUATIONS.items():
        diagnostic = diagnosis(realise(tmp_path / name, **arguments))
        if (fresh_v4 or fresh_v5) and category is not C.A_EMPTY_NO_DECLARATION:
            assert diagnostic.absence_consideration_blocked is True
            gaps.append(name)
    assert sorted(gaps) == ["manifest-declares-run-validations-absent", "manifest-declares-run-validations-empty", "running-manifest-validations-empty",
                            "technical-failure-validations-empty"]            # la lacune préexistante, exactement
    assert all(SITUATIONS[n][1] == SITUATIONS[n][2] for n in SITUATIONS)       # v4 et v5 se comportent à l'identique : v5 n'a rien aggravé ni amélioré


def test_only_category_a_leaves_the_absence_consideration_unblocked_and_even_then_it_is_not_an_authorisation(tmp_path):
    for name, (arguments, _, _, category, _) in SITUATIONS.items():
        diagnostic = diagnosis(realise(tmp_path / name, **arguments))
        assert diagnostic.absence_consideration_blocked is (category is not C.A_EMPTY_NO_DECLARATION), name
        assert diagnostic.requires_independent_rescan is True
    assert not any(word in member.value for member in (*C, *R) for word in ("FRESH", "NO_OVERLAP", "ADMISSION", "CLAIM", "AUTHORI", "EXPOSED_NOT"))


def test_a_complete_consistent_chain_is_not_an_empty_situation(tmp_path):
    directory = tmp_path / REAL_CID
    for relative, data in world(RUN_ID).items():
        (directory / relative).parent.mkdir(parents=True, exist_ok=True)
        (directory / relative).write_bytes(data)
    write_json(directory / "plan.json", {"campaign_id": REAL_CID})
    result = diagnosis(directory)
    assert result.category is C.NOT_EMPTY and result.reasons == () and result.empty_directories == ()


# ══ Diagnostic sur arbres observés (unitaire) ═══════════════════════════════════════════════════════════════════════════════════════
def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree(*items, name=REAL_CID):
    version, digest = vf.TABLE_VERSION, vf.TABLE_DIGEST
    return vf.ObservedRunTree(name, version, digest, tuple(items))


def directory(path):
    return vf.ObservedItem(path, vf.ObservedKind.DIRECTORY)


def manifest_item(**changes):
    data = json.dumps(manifest_record(**changes), indent=2).encode()
    return vf.ObservedItem("manifest.json", vf.ObservedKind.FILE, size=len(data), sha256=sha(data), content=data)


def test_non_trees_give_a_bad_input_diagnostic_never_an_exception():
    for bad in (None, 3, "tree", object(), [], ()):
        result = em.diagnose_emptiness(bad)
        assert result.category is C.BAD_INPUT and result.absence_consideration_blocked is True and result.reasons == (R.BAD_INPUT,)


def test_a_manifest_that_cannot_be_trusted_makes_the_state_contradictory_not_empty():
    unreadable = vf.ObservedItem("manifest.json", vf.ObservedKind.ANOMALY, anomaly="INVALID_JSON")
    no_bytes = vf.ObservedItem("manifest.json", vf.ObservedKind.FILE, size=2, sha256=sha(b"{}"))
    not_conforming = vf.ObservedItem("manifest.json", vf.ObservedKind.FILE, size=2, sha256=sha(b"{}"), content=b"{}")
    for item, reason in ((unreadable, R.MANIFEST_UNREADABLE), (no_bytes, R.MANIFEST_UNREADABLE), (not_conforming, R.MANIFEST_NOT_CONFORMING)):
        result = em.diagnose_emptiness(tree(item, directory("validations")))
        assert result.category is C.CONTRADICTORY and reason in result.reasons


def test_state_flags_and_declared_run_contradictions_are_detected():
    cases = ({"status": "RUNNING", "running": False, **STARTED}, {"running": True}, {"status": "TECHNICAL_FAILURE", **STARTED},
             {"status": "READY_FOR_EXECUTION", "execution_started": True}, {"walk_forward_validation_run_id": RUN_ID})
    for changes in cases:
        assert R.STATE_FLAGS_CONTRADICTION in em.diagnose_emptiness(tree(manifest_item(**changes))).reasons, changes
    other = em.diagnose_emptiness(tree(manifest_item(**{**DECLARES, "walk_forward_validation_run_id": "gate_v_v2_" + "ee" * 32 + "_walk_forward"})))
    assert other.category is C.CONTRADICTORY and R.DECLARED_RUN_MISMATCH in other.reasons


def test_a_stronger_category_is_never_downgraded_by_extra_empty_directories_or_a_weaker_reason():
    base = [manifest_item(**RUNNING), directory("validations"), directory("exposure"), directory("walk_forward"), directory("walk_forward/folds/fold_000")]
    result = em.diagnose_emptiness(tree(*base))
    assert result.category is C.C_ATTESTED_INTERRUPTION and "validations" in result.empty_directories and "walk_forward/folds/fold_000" in result.empty_directories
    orphan = vf.ObservedItem(f"walk_forward/manifest.json{ORPHAN_NAME}", vf.ObservedKind.ORPHAN)
    foreign = em.diagnose_emptiness(tree(manifest_item(**{**DECLARES, "campaign_id": "gate_v_v2_" + "ee" * 32}), orphan))
    assert foreign.category is C.CONTRADICTORY                                    # CONTRADICTORY > C > B > A


def test_an_inert_file_or_any_content_makes_a_directory_non_empty_and_unrelated_directories_are_ignored():
    inert = vf.ObservedItem("exposure/readme.txt", vf.ObservedKind.INERT)
    result = em.diagnose_emptiness(tree(directory("exposure"), inert, directory("validations"), directory("datasets"), directory("datasets/d1")))
    assert result.empty_directories == ("validations",)                           # `exposure` contient un fichier inerte ; `datasets/**` n'est pas dans le périmètre


def test_the_diagnostic_is_deterministic_total_and_independent_of_item_order():
    items = [manifest_item(**RUNNING), directory("validations"), directory(f"validations/{RUN_ID}"), directory("walk_forward"),
             vf.ObservedItem(f"{EXPECTED_BLOCKING_RUN_ID}/run_seal.json" + ORPHAN_NAME, vf.ObservedKind.ORPHAN)]
    first = em.diagnose_emptiness(tree(*items))
    assert em.diagnose_emptiness(tree(*reversed(items))) == first
    assert list(first.reasons) == sorted(first.reasons, key=lambda r: r.value)


def test_a_very_large_tree_is_diagnosed_in_linear_time():
    items = [directory(f"walk_forward/folds/fold_{i:03d}") for i in range(900)]
    items += [vf.ObservedItem(f"walk_forward/folds/fold_{i:03d}/definition.json", vf.ObservedKind.FILE, size=1, sha256="a" * 64) for i in range(0, 900, 2)]
    items += [vf.ObservedItem(f"exposure/{'a' * 63}{i:04d}" + ".json", vf.ObservedKind.FILE, size=1, sha256="b" * 64) for i in range(20_000)]
    started = time.perf_counter()
    result = em.diagnose_emptiness(tree(*items))
    assert time.perf_counter() - started < 5.0 and len(result.empty_directories) == 450


def test_the_emptiness_module_is_pure_and_carries_no_verdict_vocabulary():
    source = Path(em.__file__).read_text(encoding="utf-8")
    parsed = ast.parse(source)
    imported = {(node.module or "").split(".")[0] if isinstance(node, ast.ImportFrom) else alias.name.split(".")[0]
                for node in ast.walk(parsed) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in (getattr(node, "names", None) or [None])}
    assert imported <= {"__future__", "re", "dataclasses", "enum", "typing", "gate_v_k1s2_verifier", "gate_v_exposure_interpreters", "gate_v_exposure_scan"}, imported
    called = {n.func.id for n in ast.walk(parsed) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "eval", "exec", "__import__", "compile", "print"}
    attributes = {n.attr for n in ast.walk(parsed) if isinstance(n, ast.Attribute)}
    assert not attributes & {"read_bytes", "read_text", "scandir", "listdir", "walk", "stat", "lstat", "sha256", "hexdigest", "now", "getenv", "environ", "urlopen"}
    public = {name for name in dir(em) if not name.startswith("_")}
    assert not [name for name in public if any(word in name.upper() for word in ("FRESH", "NO_OVERLAP", "ADMISSION", "CLAIM", "AUTHORI"))]


# ══ Défauts démontrés par la relecture indépendante (RED puis GREEN) ═══════════════════════════════════════════════════════════════
from tests.test_gate_v_k1s2_verifier import CID as VCID, items_of  # noqa: E402

MC_ID = f"{REAL_CID}_monte_carlo"
WEAK_MANIFESTS = {
    "reserved-claim-id": {"final_holdout_claim_id": "claim-1"},
    "reserved-oos-run": {"oos_evidence_validation_run_id": "x"},
    "declared-monte-carlo-run": {"monte_carlo_validation_run_id": MC_ID},
    "declared-parameter-stability-run": {"parameter_stability_validation_run_ids_by_fold": {"0": "x"}, "status": "EVIDENCE_INCOMPLETE", **STARTED},
    "preregistration-not-hex": {"preregistration_id": "not-hex"},
    "negative-revision": {"manifest_revision": -1},
    "failure-reason-with-ready-status": {"technical_failure_reason": "x"},
    "campaign-id-without-prefix": {"campaign_id": "x" * 74},
}


@pytest.mark.parametrize("name", sorted(WEAK_MANIFESTS))
def test_a_manifest_that_b3_would_not_accept_or_that_declares_something_never_leaves_category_a(name):
    result = em.diagnose_emptiness(tree(manifest_item(**WEAK_MANIFESTS[name]), directory("validations"), directory("exposure")))
    assert result.category not in (C.A_EMPTY_NO_DECLARATION, C.NOT_EMPTY) and result.absence_consideration_blocked is True, (result.category, result.reasons)


def test_the_declared_monte_carlo_and_parameter_stability_runs_are_imposed_artefacts_too():
    ps_id = f"{REAL_CID}_parameter_stability_fold_000"
    declared = {"monte_carlo_validation_run_id": MC_ID, "parameter_stability_validation_run_ids_by_fold": {"0": ps_id}, "status": "EVIDENCE_INCOMPLETE", **STARTED}
    result = em.diagnose_emptiness(tree(manifest_item(**declared), directory("validations")))
    assert R.DECLARED_AUXILIARY_RUN_ABSENT in result.reasons and result.absence_consideration_blocked is True        # C l'emporte ici (exécution démarrée sans run WF déclaré)
    assert em.diagnose_emptiness(tree(manifest_item(**{**declared, "walk_forward_validation_run_id": RUN_ID}), directory("validations"))).category \
        is C.B_ARTEFACT_IMPOSED_BUT_ABSENT
    present = [vf.ObservedItem(f"validations/{rid}/validation_run.json", vf.ObservedKind.FILE, size=1, sha256="a" * 64) for rid in (MC_ID, ps_id)]
    assert R.DECLARED_AUXILIARY_RUN_ABSENT not in em.diagnose_emptiness(tree(manifest_item(**declared), *present)).reasons


def test_a_ready_manifest_that_declares_an_auxiliary_run_is_contradictory_even_when_that_run_exists():
    present = vf.ObservedItem(f"validations/{MC_ID}/validation_run.json", vf.ObservedKind.FILE, size=1, sha256="a" * 64)
    result = em.diagnose_emptiness(tree(manifest_item(monte_carlo_validation_run_id=MC_ID), present))
    assert R.STATE_FLAGS_CONTRADICTION in result.reasons and result.category is C.CONTRADICTORY


def test_an_empty_directory_next_to_a_complete_chain_is_not_category_a():
    items = [*items_of(world()), vf.ObservedItem("exposure", vf.ObservedKind.DIRECTORY), vf.ObservedItem("walk_forward/folds/fold_009", vf.ObservedKind.DIRECTORY)]
    result = em.diagnose_emptiness(tree(*items, name=VCID))
    assert result.category is C.NOT_EMPTY and set(result.empty_directories) == {"exposure", "walk_forward/folds/fold_009"} and result.reasons == ()


def test_a_declared_complete_state_with_an_empty_exposure_directory_is_not_category_a():
    result = em.diagnose_emptiness(tree(manifest_item(**{"status": "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT", "walk_forward_validation_run_id": RUN_ID, **STARTED}),
                                        directory("exposure")))
    assert result.category is C.B_ARTEFACT_IMPOSED_BUT_ABSENT


@pytest.mark.parametrize("path", ["exposure/" + ORPHAN_NAME, f"validations/{MC_ID}/validation_run.json{ORPHAN_NAME}", "exposure/" + "ab" * 32 + "/inventory.json" + ORPHAN_NAME])
def test_a_publication_orphan_anywhere_is_an_attested_interruption(path):
    result = em.diagnose_emptiness(tree(vf.ObservedItem(path, vf.ObservedKind.ORPHAN), directory("validations")))
    assert result.category is C.C_ATTESTED_INTERRUPTION and R.PUBLICATION_ORPHAN in result.reasons and result.absence_consideration_blocked is True


@pytest.mark.parametrize("kind,extra", [(vf.ObservedKind.UNKNOWN, {}), (vf.ObservedKind.UNKNOWN, {"anomaly": "UNKNOWN_FILE"}), (vf.ObservedKind.ANOMALY, {"anomaly": "UNREADABLE"})])
@pytest.mark.parametrize("path", ["manifest.update.lock", "technical_failure.json", "final_holdout_access_claim.json", "exposure/stray"])
def test_an_unknown_or_anomalous_entry_anywhere_blocks_the_absence_consideration(kind, extra, path):
    result = em.diagnose_emptiness(tree(vf.ObservedItem(path, kind, **extra), directory("validations")))
    assert result.category is C.UNRESOLVED_ENTRIES and R.UNRESOLVED_ENTRY_PRESENT in result.reasons and result.absence_consideration_blocked is True


@pytest.mark.parametrize("path", [f"validations/{MC_ID}/validation_run.json", f"validations/gate_v_v2_{'ee' * 32}_walk_forward/validation_run.json"])
def test_another_run_alone_means_artefacts_exist_so_the_situation_is_not_an_empty_one(path):
    result = em.diagnose_emptiness(tree(vf.ObservedItem(path, vf.ObservedKind.FILE, size=1, sha256="a" * 64)))
    assert result.category is C.NOT_EMPTY and result.absence_consideration_blocked is False        # le diagnostic n'accorde rien : il ne classe pas cette situation


# ── mutants survivants de la relecture : branches B / C auparavant non épinglées ────────────────────────────────────────────────────
def test_each_declared_or_evidenced_gap_has_its_exact_reason():
    file = lambda path: vf.ObservedItem(path, vf.ObservedKind.FILE, size=1, sha256="a" * 64)  # noqa: E731
    base = f"validations/{RUN_ID}"
    started_no_run = em.diagnose_emptiness(tree(manifest_item(status="EVIDENCE_INCOMPLETE", **STARTED), directory("validations")))
    assert (started_no_run.category, started_no_run.reasons) == (C.C_ATTESTED_INTERRUPTION, (R.EXECUTION_STARTED_WITHOUT_ARTEFACT,))
    outputs_only = em.diagnose_emptiness(tree(file("walk_forward/manifest.json")))
    assert (outputs_only.category, outputs_only.reasons) == (C.B_ARTEFACT_IMPOSED_BUT_ABSENT, (R.OUTPUTS_WITHOUT_EVIDENCE,))
    evidence_only = em.diagnose_emptiness(tree(file(f"{base}/run_data_coverage.json")))
    assert (evidence_only.category, evidence_only.reasons) == (C.B_ARTEFACT_IMPOSED_BUT_ABSENT, (R.EVIDENCE_WITHOUT_RUN_RECORD,))
    declared_no_record = em.diagnose_emptiness(tree(manifest_item(**DECLARES), file(f"{base}/run_data_coverage.json")))
    assert {R.DECLARED_RUN_WITHOUT_RECORD, R.EVIDENCE_WITHOUT_RUN_RECORD} == set(declared_no_record.reasons)
    complete_status = {"status": "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT", "walk_forward_validation_run_id": RUN_ID, **STARTED}
    imposes = em.diagnose_emptiness(tree(manifest_item(**complete_status), file(f"{base}/validation_run.json"), file(f"{base}/run_data_coverage.json")))
    assert R.STATUS_IMPOSES_EVIDENCE in imposes.reasons and R.RUN_RECORD_WITHOUT_EVIDENCE in imposes.reasons
    full = [file(f"{base}/validation_run.json"), file(f"{base}/run_data_coverage.json"), file(f"{base}/run_seal.json"), file(f"{base}/run_session_0001.json")]
    assert R.STATUS_IMPOSES_EVIDENCE not in em.diagnose_emptiness(tree(manifest_item(**complete_status), *full)).reasons


def test_the_diagnostic_is_linear_in_depth_and_refuses_pathologically_deep_paths():
    deep = "walk_forward/" + "/".join(["d"] * 40) + "/f.json"
    with pytest.raises(vf.ObservationRefused) as caught:
        vf.ObservedItem(deep, vf.ObservedKind.INERT)
    assert caught.value.code is vf.ObservationRefusal.BAD_PATH
    items = [vf.ObservedItem("walk_forward/" + "/".join([f"{'a' * 60}{i:04d}"] + ["b" * 28] * 28) + "/f", vf.ObservedKind.FILE, size=1, sha256="a" * 64) for i in range(3000)]
    started = time.perf_counter()
    assert em.diagnose_emptiness(tree(*items)).category is C.B_ARTEFACT_IMPOSED_BUT_ABSENT
    assert time.perf_counter() - started < 5.0
