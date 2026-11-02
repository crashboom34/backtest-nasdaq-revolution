"""Support de tests N-VIDE-1 / B3 v6 : scénarios « manifeste de campagne → preuves attendues », réalisés SUR DISQUE (`tmp_path`, contenus synthétiques) et rejoués par le chemin
complet B3 → B4 → E3-A (classification) → préconditions du registre. Aucune donnée de marché, aucun FINAL_HOLDOUT, aucune admission.

Ce module ne contient aucune attente : il construit les arbres et MESURE (`assess`). Les attentes vivent dans les tests, séparément pour B3 v4, v5 et v6.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import gate_v_exposure_interpreters as b3
from gate_v_exposure_scan import AuditRoot, HashLimits
from gate_v_final_holdout_protocol import SourceStatus
from gate_v_inventory_preconditions import RegistryRecordType
from tests.gate_v_exposure_support import LIMITS, W, write_json
from tests.test_gate_v_exposure_interpreters_v4 import CID, manifest_record
from tests.test_gate_v_exposure_interpreters_v5 import evidence_files, run_record
from tests.test_gate_v_exposure_v4_v5_differential import assemble, classify, refusals

HL = HashLimits(max_hashed_file_bytes=65_536, max_total_hashed_bytes=2_000_000, max_hashed_files=200)
CAMPAIGN = b3.RootLayout.CAMPAIGN_DIR
OTHER_CID = "gate_v_v2_" + "ee" * 32
RUN_WF = f"{CID}_walk_forward"
RUN_MC = f"{CID}_monte_carlo"
RUN_PS = f"{CID}_parameter_stability_fold_000"
OTHER_WF = f"{OTHER_CID}_walk_forward"
STARTED = {"execution_started": True}
DECLARES_WF = {"walk_forward_validation_run_id": RUN_WF, "status": "EVIDENCE_INCOMPLETE", **STARTED}
DECLARES_WF_COMPLETE = {"walk_forward_validation_run_id": RUN_WF, "status": "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT", **STARTED}
FULL_DECLARATION = {**DECLARES_WF_COMPLETE, "monte_carlo_validation_run_id": RUN_MC, "parameter_stability_validation_run_ids_by_fold": {"fold_000": RUN_PS}}
RUN_WF_UPPER = "gate_v_v2_" + CID[len("gate_v_v2_"):].upper() + "_walk_forward"          # même campagne, hexadécimal en majuscules : pas un identifiant de run
OTHER_SESSION = f"validations/{OTHER_WF}/run_session_0001.json"
RUNNING = {"status": "RUNNING", "running": True, **STARTED}
FAILED = {"status": "TECHNICAL_FAILURE", "technical_failure_reason": "boom", **STARTED}
_EVIDENCE = evidence_files(RUN_WF)
COVERAGE, SESSION, SEAL = (f"validations/{RUN_WF}/{name}" for name in ("run_data_coverage.json", "run_session_0001.json", "run_seal.json"))
WF_CHAIN = {COVERAGE: _EVIDENCE[COVERAGE], SESSION: _EVIDENCE[SESSION], SEAL: _EVIDENCE[SEAL]}


@dataclass(frozen=True)
class Scenario:
    manifest: object = None                               # None : aucun manifest.json ; dict : champs modifiés d'un enregistrement D2 valide ; bytes : octets bruts
    records: tuple = ()                                   # (run_id, validation_type) dont `validation_run.json` est écrit
    files: dict = field(default_factory=dict, hash=False)  # chemin relatif → octets
    dirs: tuple = ()                                      # répertoires (éventuellement vides)


SCENARIOS = {
    "01-ready-initial": Scenario(manifest={}),
    "02-wf-declared-directory-absent": Scenario(manifest=DECLARES_WF),
    "03-wf-declared-directory-empty": Scenario(manifest=DECLARES_WF, dirs=(f"validations/{RUN_WF}",)),
    "04-record-without-coverage": Scenario(manifest=DECLARES_WF, records=((RUN_WF, "walk_forward"),)),
    "05-coverage-without-session": Scenario(manifest=DECLARES_WF, records=((RUN_WF, "walk_forward"),), files={COVERAGE: WF_CHAIN[COVERAGE]}),
    "06-session-without-seal": Scenario(manifest=DECLARES_WF, records=((RUN_WF, "walk_forward"),), files={COVERAGE: WF_CHAIN[COVERAGE], SESSION: WF_CHAIN[SESSION]}),
    "07-running-validations-empty": Scenario(manifest=RUNNING, dirs=("validations",)),
    "08-technical-failure-validations-empty": Scenario(manifest=FAILED, dirs=("validations",)),
    "09-evidence-incomplete-nothing-declared": Scenario(manifest={"status": "EVIDENCE_INCOMPLETE", **STARTED}, dirs=("validations",)),
    "10-complete-claimed-seal-missing": Scenario(
        manifest=FULL_DECLARATION, records=((RUN_WF, "walk_forward"), (RUN_MC, "monte_carlo"), (RUN_PS, "parameter_stability")), files={COVERAGE: WF_CHAIN[COVERAGE], SESSION: WF_CHAIN[SESSION]}),
    "11-monte-carlo-declared-absent": Scenario(manifest=FULL_DECLARATION, records=((RUN_WF, "walk_forward"), (RUN_PS, "parameter_stability")), files=WF_CHAIN),
    "12-parameter-stability-declared-absent": Scenario(manifest=FULL_DECLARATION, records=((RUN_WF, "walk_forward"), (RUN_MC, "monte_carlo")), files=WF_CHAIN),
    "13-several-runs-one-missing": Scenario(manifest=FULL_DECLARATION, records=((RUN_WF, "walk_forward"),), files=WF_CHAIN),
    "14-foreign-manifest": Scenario(manifest={"campaign_id": OTHER_CID}),
    "15-exposure-empty-ready": Scenario(manifest={}, dirs=("exposure",)),
    "16a-manifest-corrupt-bytes": Scenario(manifest=b"{"),
    "16b-manifest-invalid-schema": Scenario(manifest=b'{"campaign_id": "x"}'),
    "17-complete-claimed-without-any-reference": Scenario(manifest={"status": "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT", **STARTED}, dirs=("validations",)),
    "18-no-manifest-validations-empty": Scenario(manifest=None, dirs=("validations",)),
    "19-ready-but-artefacts-present": Scenario(manifest={}, records=((RUN_WF, "walk_forward"),), files=WF_CHAIN),
    "20-foreign-run-reference": Scenario(manifest={"walk_forward_validation_run_id": OTHER_WF, "status": "EVIDENCE_INCOMPLETE", **STARTED}, dirs=("validations",)),
    "21-wrong-kind-reference": Scenario(manifest={"walk_forward_validation_run_id": RUN_MC, "status": "EVIDENCE_INCOMPLETE", **STARTED}, dirs=("validations",)),
    "22-running-flag-without-running-status": Scenario(manifest={"running": True}, dirs=("validations",)),
    "23-ready-with-failure-reason": Scenario(manifest={"technical_failure_reason": "x"}, dirs=("validations",)),
    "24-walk-forward-outputs-with-ready-manifest": Scenario(manifest={}, files={"walk_forward/manifest.json": b"{}"}),
    "25-all-declared-runs-present": Scenario(
        manifest=FULL_DECLARATION, records=((RUN_WF, "walk_forward"), (RUN_MC, "monte_carlo"), (RUN_PS, "parameter_stability")), files=WF_CHAIN),
    "29-ready-with-revision-above-zero": Scenario(manifest={"manifest_revision": 5}, dirs=("validations",)),
    "30-ready-with-reference-not-started": Scenario(manifest={"walk_forward_validation_run_id": RUN_WF}, dirs=("validations",)),
    "31-session-in-another-run-directory": Scenario(
        manifest=DECLARES_WF, records=((RUN_WF, "walk_forward"),), files={COVERAGE: WF_CHAIN[COVERAGE], SEAL: WF_CHAIN[SEAL], OTHER_SESSION: evidence_files(OTHER_WF)[OTHER_SESSION]}),
    "32-uppercase-hex-reference": Scenario(manifest={"walk_forward_validation_run_id": RUN_WF_UPPER, "status": "EVIDENCE_INCOMPLETE", **STARTED}, dirs=("validations",)),
    "28-ready-with-empty-walk-forward-directory": Scenario(manifest={}, dirs=("walk_forward/folds/fold_000",)),
    "26-complete-claimed-without-monte-carlo-reference": Scenario(
        manifest={**DECLARES_WF_COMPLETE, "parameter_stability_validation_run_ids_by_fold": {"fold_000": RUN_PS}}, records=((RUN_WF, "walk_forward"), (RUN_PS, "parameter_stability")), files=WF_CHAIN),
    "27-complete-claimed-without-parameter-stability-references": Scenario(
        manifest={**DECLARES_WF_COMPLETE, "monte_carlo_validation_run_id": RUN_MC}, records=((RUN_WF, "walk_forward"), (RUN_MC, "monte_carlo")), files=WF_CHAIN),
}


def realise(base: Path, scenario: Scenario, *, name: str = CID) -> Path:
    directory = base / name
    write_json(directory / "plan.json", {"campaign_id": name})
    if scenario.manifest is not None:
        data = scenario.manifest if isinstance(scenario.manifest, bytes) else json.dumps(manifest_record(**scenario.manifest), indent=2).encode()
        (directory / "manifest.json").write_bytes(data)
    for run_id, validation_type in scenario.records:
        write_json(directory / "validations" / run_id / "validation_run.json", run_record(run_id, validation_type))
    for relative, data in scenario.files.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for relative in scenario.dirs:
        (directory / relative).mkdir(parents=True, exist_ok=True)
    return directory


def roots_of(directory: Path, label: str = "camp", **root_kwargs) -> tuple:
    return (b3.LayoutRoot(CAMPAIGN, AuditRoot(label, str(directory), **root_kwargs)),)


@dataclass(frozen=True)
class Assessment:
    """Ce que le chemin B3 → B4 → E3-A → préconditions produit pour un arbre. `fresh_eligible` = inventaire complet, aucun finding non résolu, tous `NO_OVERLAP` (précondition de
    B3 pour FRESH) ; `classification` = la classe EFFECTIVEMENT calculée par E3-A ; `reservation` / `admission` = codes de refus des préconditions du registre (aucun droit n'est accordé)."""

    complete: bool
    reasons: tuple
    unresolved: int
    findings: int
    fresh_eligible: bool
    inventory_complete: bool
    inventory_id: str
    classification: str
    reservation: tuple
    admission: tuple
    semantics_version: str


def assess(interpretation) -> Assessment:
    assembly = assemble(interpretation)
    unresolved = sum(1 for finding in interpretation.findings if finding.status is SourceStatus.UNRESOLVED)
    fresh_eligible = interpretation.complete and unresolved == 0 and all(f.overlap.value == "NO_OVERLAP" for f in interpretation.findings)
    return Assessment(
        complete=interpretation.complete, reasons=interpretation.incomplete_reasons, unresolved=unresolved, findings=len(interpretation.findings), fresh_eligible=fresh_eligible,
        inventory_complete=assembly.inventory.complete, inventory_id=assembly.inventory_id, classification=classify(assembly).name,
        reservation=tuple(sorted(str(r) for r in refusals(assembly, RegistryRecordType.RESERVATION))),
        admission=tuple(sorted(str(r) for r in refusals(assembly, RegistryRecordType.ADMISSION))), semantics_version=interpretation.semantics_version)


def interpret_v4(roots: tuple):
    return b3.interpret_audit_roots(roots, LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])


def interpret_v5(roots: tuple, **kwargs):
    import gate_v_exposure_interpreters_v5 as v5
    return v5.interpret_audit_roots_v5(roots, LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1], **kwargs)


def reason_codes(assessment: Assessment) -> set:
    return {reason.split(":", 1)[0] for reason in assessment.reasons}
