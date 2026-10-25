"""AF-V-07 B3 v5-A — suite DIFFÉRENTIELLE v4 / v5 (audit de sécurité final).

Invariant obligatoire : aucune reconnaissance supplémentaire de v5 ne doit améliorer l'éligibilité scientifique d'une campagne en l'absence d'une preuve réellement
vérifiée (le vérificateur L3 n'existe pas). Pour chaque scénario, v5 est comparée à v4 sur `inventory.complete`, les raisons d'incomplétude, les findings non résolus, la
comptabilité des essais, les identités, la classification E3-A (FRESH) et les refus de préconditions RESERVATION / ADMISSION : v5 peut classer autrement, jamais débloquer.
Fixtures SYNTHÉTIQUES (`tmp_path`) : aucune donnée de marché réelle, aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

import gate_v_exposure_interpreters as b3
import gate_v_exposure_interpreters_v5 as v5
import gate_v_exposure_inventory as b4
from gate_v_exposure_scan import AuditRoot
from gate_v_final_holdout_protocol import (
    ChronologyFacts, ClassificationInput, DeclarationSet, ExposureClass, OwnCampaignContext, OwnRecordStage, SourceStatus, TimeProofFact, TimeProofStatus,
    build_exposure_declaration, classify_exposure,
)
from gate_v_inventory_preconditions import RegistryRecordType, inventory_precondition_refusals
from tests.gate_v_exposure_support import LIMITS, W
from tests.test_gate_v_exposure_interpreters_v5 import A32, HL, RUN_MC_ID, RUN_PS_ID, RUN_WF_ID, build, evidence_files, run_record, wf_outputs

CAMPAIGN = b3.RootLayout.CAMPAIGN_DIR
FRESH = ExposureClass.FRESH_UNEXPOSED_DECLARED
OTHER_WF = "gate_v_v2_" + "ab" * 32 + "_walk_forward"                  # run d'une AUTRE campagne
FOREIGN_CID = "gate_v_v2_" + "ee" * 32


def json_bytes(value) -> bytes:
    return json.dumps(value, indent=2).encode("utf-8")


def evidence_of_another_run() -> dict:
    """Preuves cohérentes DE L'AUTRE run, déposées dans le dossier du run courant (identifiant ≠ nom du dossier)."""
    return {path.replace(OTHER_WF, RUN_WF_ID): data for path, data in evidence_files(OTHER_WF).items()}


def scenarios() -> dict:
    """id → (fichiers, run_record_for, répertoires vides, racines étrangères éventuelles {nom: fichiers})."""
    outputs, evidence = wf_outputs(), evidence_files()
    partial_outputs = {path: data for path, data in outputs.items() if "fold_001" not in path}
    no_aggregate = {path: data for path, data in outputs.items() if path != "walk_forward/aggregate.json"}
    mixed = {f"validations/{RUN_MC_ID}/validation_run.json": json_bytes(run_record(RUN_MC_ID, "monte_carlo")),
             f"validations/{RUN_PS_ID}/validation_run.json": json_bytes(run_record(RUN_PS_ID, "parameter_stability"))}
    seal = {p: d for p, d in evidence.items() if p.endswith("run_seal.json")}
    coverage_in_mc = {f"validations/{RUN_MC_ID}/run_data_coverage.json": evidence[f"validations/{RUN_WF_ID}/run_data_coverage.json"],
                      f"validations/{RUN_MC_ID}/validation_run.json.{A32}.tmp": b"half"}
    return {
        "clean-anchor-only": ({}, None, [], {}),
        "validation-run-without-evidence-files": ({}, RUN_WF_ID, [], {}),
        "empty-walk-forward": ({}, None, ["walk_forward"], {}),
        "empty-fold-directories": ({}, None, ["walk_forward/folds/fold_000", "walk_forward/folds/fold_001"], {}),
        "directories-only-partial-skeleton": ({}, RUN_WF_ID, ["walk_forward/folds/fold_000", "walk_forward/.gate_v_checkpoints_v1/folds"], {}),
        "coverage-without-session": ({p: d for p, d in evidence.items() if p.endswith("run_data_coverage.json")}, RUN_WF_ID, [], {}),
        "session-without-seal": ({p: d for p, d in evidence.items() if not p.endswith("run_seal.json")}, RUN_WF_ID, [], {}),
        "seal-without-coverage": (seal, RUN_WF_ID, [], {}),
        "seal-without-validation-run": (seal, None, [], {}),
        "complete-looking-but-unverified": ({**outputs, **evidence}, RUN_WF_ID, [], {}),
        "complete-looking-without-validation-run": ({**outputs, **evidence}, None, [], {}),
        "missing-output-file": ({**no_aggregate, **evidence}, RUN_WF_ID, [], {}),
        "partial-outputs": ({**partial_outputs, **evidence}, RUN_WF_ID, [], {}),
        "unknown-file-added": ({**outputs, "walk_forward/notes.txt": b"x"}, RUN_WF_ID, [], {}),
        "extra-checkpoint": ({**outputs, "walk_forward/.gate_v_checkpoints_v1/folds/fold_999.json": b"{}"}, RUN_WF_ID, [], {}),
        "orphan-alone": ({f"walk_forward/aggregate.json.{A32}.tmp": b"half"}, None, [], {}),
        "orphan-of-validation-run-alone": ({f"validations/{RUN_WF_ID}/validation_run.json.{A32}.tmp": b"half"}, None, [], {}),
        "foreign-campaign-with-anomaly": ({}, None, [], {FOREIGN_CID: {"mystery.bin": b"x"}}),
        "foreign-campaign-with-an-unknown-file-in-walk-forward": ({}, None, [], {FOREIGN_CID: {"walk_forward/mystery.bin": b"x"}}),
        "foreign-campaign-with-recognised-outputs": ({**outputs}, RUN_WF_ID, [], {FOREIGN_CID: {**outputs}}),
        "several-runs-one-incomplete": ({**outputs, **evidence, **coverage_in_mc}, RUN_WF_ID, [], {}),
        "wf-mc-ps-mix": ({**outputs, **evidence, **mixed}, RUN_WF_ID, [], {}),
        "evidence-of-another-run-in-the-current-directory": (evidence_of_another_run(), RUN_WF_ID, [], {}),
        "hostile-names-in-walk-forward": ({"walk_forward/folds/fold_000/DEFINITION.json": b"x", "walk_forward/folds/fold_00/definition.json": b"x",
                                           f"walk_forward/.exposure.tmp.{A32}": b"x"}, RUN_WF_ID, [], {}),
        "hostile-names-at-the-root": ({"notes.txt": b"x", f"manifest.json.{A32}.tmp": b"x", f".exposure.tmp.{A32}": b"x", "plan.json.bak": b"x"}, RUN_WF_ID, [], {}),
    }


SCENARIOS = scenarios()
ARTEFACT_FREE = {"clean-anchor-only", "validation-run-without-evidence-files", "foreign-campaign-with-anomaly", "hostile-names-at-the-root"}
V5_ARTEFACT_SCENARIOS = [name for name in sorted(SCENARIOS) if name not in ARTEFACT_FREE]


def realise(tmp_path, scenario_id):
    files, run_record_for, directories, foreign = SCENARIOS[scenario_id]
    own = build(tmp_path / "own", files, run_record_for=run_record_for)
    for relative in directories:
        (own / relative).mkdir(parents=True, exist_ok=True)
    roots = [b3.LayoutRoot(CAMPAIGN, AuditRoot("camp", str(own)))]
    for name, foreign_files in foreign.items():
        foreign_root = build(tmp_path / "foreign", foreign_files, name=name, run_record_for=None)
        roots.append(b3.LayoutRoot(CAMPAIGN, AuditRoot("foreign", str(foreign_root))))
    return tuple(roots)


def both(roots):
    historical = b3.interpret_audit_roots(roots, LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    current = v5.interpret_audit_roots_v5(roots, LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    return historical, current


def assemble(interpretation):
    return b4.assemble_exposure_inventory(interpretation, registry=b4.RegistryView("reg", None, ()), accounting=b4.AccountingViews(),
                                          own_context=OwnCampaignContext("campaign_current", OwnRecordStage.NO_OWN_RECORDS), derived_root_labels=())


def classify(assembly):
    declaration = build_exposure_declaration(declaration_seq=1, declarant="Mira", inventory_id=assembly.inventory_id, prev_declaration_id=None,
                                             declared_exposures=(), declared_t_sel_utc=None, declared_trial_counts=None)
    chronology = ChronologyFacts(None, None, TimeProofFact(TimeProofStatus.ABSENT, None, None), None, None, None, None)
    return classify_exposure(ClassificationInput(assembly.inventory, DeclarationSet((declaration,), True), chronology, assembly.own_context)).classification


def refusals(assembly, record_type):
    stage = OwnRecordStage.NO_OWN_RECORDS if record_type is RegistryRecordType.RESERVATION else OwnRecordStage.RESERVED
    return inventory_precondition_refusals(record_type, assembly.inventory, OwnCampaignContext("campaign_current", stage)).refusals


def unresolved(interpretation) -> bool:
    return any(f.status is SourceStatus.UNRESOLVED for f in interpretation.findings)


def freshable(interpretation) -> bool:
    """Précondition de B3 pour FRESH : inventaire complet et uniquement des sources résolues sans recouvrement."""
    return interpretation.complete and not unresolved(interpretation) and all(f.overlap.value == "NO_OVERLAP" for f in interpretation.findings)


@pytest.mark.parametrize("scenario_id", sorted(SCENARIOS))
def test_v5_never_unblocks_a_campaign_that_v4_blocks_whatever_the_scenario(tmp_path, scenario_id):
    historical, current = both(realise(tmp_path, scenario_id))
    a_v4, a_v5 = assemble(historical), assemble(current)
    # 1. complétude, raisons et findings non résolus : v4 incomplet ⇒ v5 incomplet ; v4 non résolu ⇒ v5 non résolu
    assert (not historical.complete) <= (not current.complete), (historical.incomplete_reasons, current.incomplete_reasons)
    assert unresolved(historical) <= unresolved(current)
    # 2. comptabilité des essais : calculée par B4 à partir des vues de l'appelant, jamais par B3 — identique
    assert a_v4.inventory.trial_accounting == a_v5.inventory.trial_accounting
    # 3. classification E3-A : FRESH en v5 ⇒ FRESH en v4
    assert (classify(a_v5) is FRESH) <= (classify(a_v4) is FRESH), scenario_id
    # 4. préconditions RESERVATION / ADMISSION : un refus de v4 subsiste en v5 (la nature du refus peut changer, jamais disparaître)
    for record_type in RegistryRecordType:
        assert bool(refusals(a_v4, record_type)) <= bool(refusals(a_v5, record_type)), (scenario_id, record_type)
    # 5. éligibilité composite : v5 « fraîchable » ⇒ v4 l'est aussi
    assert freshable(current) <= freshable(historical)


@pytest.mark.parametrize("scenario_id", sorted(ARTEFACT_FREE))
def test_a_scenario_without_any_v5_artefact_is_interpreted_identically_by_v4_and_v5(tmp_path, scenario_id):
    historical, current = both(realise(tmp_path, scenario_id))
    fields = ("findings", "plans", "complete", "incomplete_reasons", "non_oos_validations", "exposure_evidence")
    assert [getattr(historical, name) for name in fields] == [getattr(current, name) for name in fields]
    a_v4, a_v5 = assemble(historical), assemble(current)
    assert (a_v4.inventory_id, a_v4.inventory_content_digest) == (a_v5.inventory_id, a_v5.inventory_content_digest)         # identités inchangées


@pytest.mark.parametrize("scenario_id", V5_ARTEFACT_SCENARIOS)
def test_every_scenario_holding_a_recognised_artefact_ends_blocked_for_registry_records_and_never_fresh(tmp_path, scenario_id):
    """Plus fort que la comparaison : un artefact reconnu (même vide, isolé, ou d'un autre run) bloque TOUJOURS, quel que soit le comportement de v4."""
    _, current = both(realise(tmp_path, scenario_id))
    assembly = assemble(current)
    assert current.complete is False and unresolved(current), scenario_id          # les DEUX : inventaire incomplet ET finding non résolu (invariant de v5)
    assert classify(assembly) is not FRESH
    for record_type in RegistryRecordType:
        assert refusals(assembly, record_type), (scenario_id, record_type)


ROOT = Path(__file__).resolve().parent.parent


def test_the_v5_module_has_no_io_hashing_classification_or_primitive_of_its_own():
    tree = ast.parse((ROOT / "gate_v_exposure_interpreters_v5.py").read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported <= {"__future__", "os", "typing", "gate_v_exposure_interpreters", "gate_v_run_evidence_models", "gate_v_exposure_scan",
                        "gate_v_exposure_sources", "gate_v_final_holdout_protocol"}, imported          # ni hashlib, ni json, ni pandas, ni L1 : aucune primitive recalculée
    called = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & {"open", "eval", "exec", "__import__", "compile"}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attributes & {"read_bytes", "read_text", "scandir", "listdir", "walk", "sha256", "md5", "sha1", "write", "write_bytes", "unlink", "remove", "rename",
                             "replace", "mkdir", "stat", "lstat", "open", "classify_exposure", "build_exposure_inventory"}
    os_uses = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os"}
    assert os_uses <= {"path"}                                                                        # `os.path.basename` du dossier racine, rien d'autre


def test_v5_is_never_activated_silently_only_the_b5_store_imports_it_and_nothing_calls_its_interpreter():
    importers, callers = set(), set()
    for directory, subdirectories, names in os.walk(ROOT):                    # racine ET sous-paquets (api/, services/, knowledge/…), hors environnements et tests
        subdirectories[:] = [d for d in subdirectories if d not in {".venv", "venv", ".git", "node_modules", "tests", "__pycache__", "frontend"}]
        for name in names:
            if not name.endswith(".py") or name == "gate_v_exposure_interpreters_v5.py":
                continue
            relative = os.path.relpath(os.path.join(directory, name), ROOT).replace(os.sep, "/")
            text = Path(directory, name).read_text(encoding="utf-8", errors="replace")
            if "gate_v_exposure_interpreters_v5" in text:
                importers.add(relative)
            if "interpret_audit_roots_v5" in text:
                callers.add(relative)
    assert importers == {"gate_v_exposure_store.py"} and not callers, (importers, callers)           # B5 n'en lit que les digests ; aucun module de production ne l'appelle
    assert b3.B3_SEMANTICS_VERSION == "gate_v_exposure_interpreters_v4" and v5.B3_V5_SEMANTICS_VERSION not in b3.KNOWN_B3_VERSIONS
    assert "interpret_audit_roots_v5" not in vars(b3) and "source_rules_v5" not in vars(b3)


def test_the_scenario_set_covers_every_case_required_by_the_audit_and_is_not_vacuous():
    assert len(SCENARIOS) >= 24 and len(V5_ARTEFACT_SCENARIOS) >= 18
    required = {"empty-walk-forward", "empty-fold-directories", "directories-only-partial-skeleton", "coverage-without-session", "session-without-seal",
                "seal-without-coverage", "validation-run-without-evidence-files", "complete-looking-but-unverified", "missing-output-file", "unknown-file-added",
                "extra-checkpoint", "orphan-alone", "foreign-campaign-with-anomaly", "several-runs-one-incomplete", "wf-mc-ps-mix",
                "evidence-of-another-run-in-the-current-directory"}
    assert required <= set(SCENARIOS)


@pytest.mark.parametrize("scenario_id", ["empty-walk-forward", "empty-fold-directories", "directories-only-partial-skeleton"])
def test_the_skeleton_scenarios_are_blocked_by_v4_and_by_v5_which_was_the_defect_found_by_the_review(tmp_path, scenario_id):
    historical, current = both(realise(tmp_path, scenario_id))
    assert historical.complete is False and current.complete is False and unresolved(historical) and unresolved(current)
