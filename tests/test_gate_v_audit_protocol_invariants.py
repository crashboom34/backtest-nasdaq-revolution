"""N-VIDE-2 / N2-a — invariants du rapport (aucun pouvoir d'autorisation, aucun justificatif transportable), vocabulaire fermé, pureté et graphe d'imports."""

from __future__ import annotations

import ast
import dataclasses
import enum
import inspect
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import gate_v_audit_protocol as ap
import gate_v_k1s2_verifier as vf
from tests.gate_v_audit_protocol_support import request_of, scenario_dir

ROOT = Path(ap.__file__).parent
SOURCE = Path(ap.__file__).read_text(encoding="utf-8")
FORBIDDEN_SUBSTRINGS = ("FRESH", "NO_OVERLAP", "ADMIT", "ADMISSION", "CLAIM", "AUTHORI", "ABSENCE_ESTABLISHED", "EXCLUSION")
FORBIDDEN_TOKENS = {"PASS", "OK", "VALID", "CLEAN", "CLEARED", "ALLOWED", "GRANTED", "ACCESS"}
E3J_LITERALS = ("INDEPENDENT_RESCAN", "CHRONOLOGY_PROOF", "SEAL_ANTERIORITY", "D5_PREDICATE", "S0_RECOMPUTATION", "INVENTORY_CONTENT_DIGEST_RECHECK", "ATTESTATION",
                "AUTHORIZATION", "COMMITMENT", "RESERVATION_TIME_PROOF", "REGISTRY_CHAIN_STRICT_READ", "ADMISSION_WRITER")


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    return ap.audit_campaign_exposure(request_of(scenario_dir(tmp_path_factory.mktemp("n2a_inv"), "01-ready-initial")))


def test_the_authority_constants_are_locked_to_exact_literals(report):
    assert report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE and ap.AbsenceEvidence.UNAVAILABLE.value == "UNAVAILABLE"
    assert report.auxiliary_runs is ap.AuxiliaryRuns.UNQUALIFIED and ap.AuxiliaryRuns.UNQUALIFIED.value == "UNQUALIFIED"
    assert report.s0_facts is ap.S0Facts.NOT_VERIFIED and ap.S0Facts.NOT_VERIFIED.value == "NOT_VERIFIED"
    assert report.persistence is ap.Persistence.NOT_PERSISTED and ap.Persistence.NOT_PERSISTED.value == "NOT_PERSISTED"
    assert report.window_provenance is ap.WindowProvenance.UNVERIFIED       # requête par défaut (sans window_source) : jamais plus que la fenêtre de l'opérateur
    assert [m.value for m in ap.WindowProvenance] == ["UNVERIFIED", "SPLIT_PLAN_FINGERPRINT_MATCHED"]      # N2-b1a : un seul niveau ajouté, dérivé d'une dérivation réussie
    assert report.grants == () and report.grants_nothing is True and report.independent_rescan_required is True
    assert ap.E3J_PREREQUISITES_UNMET == E3J_LITERALS and report.e3j_prerequisites_unmet == E3J_LITERALS
    assert report.not_proven == vf.NOT_PROVEN + ("SNAPSHOT_ATOMICITY", "CHRONOLOGY", "INDEPENDENT_RESCAN", "S0_RECOMPUTATION", "PLAN_SOURCES_AUTHENTICITY",      # N2-b1a : le plan V2 n'est pas revalidé contre ses sources
                                                 "CAMPAIGNS_OUTSIDE_REGISTRY", "TRIAL_ACCOUNTING", "DERIVED_ROOT_CONTENT_ATTRIBUTION", "REGISTRY_NOT_REAL_BOUND",
                                                 "STAGE_CONSUMPTION_LINK_UNVERIFIED")      # N2-b1b : cinq littéraux CONSTANTS, avec ou sans registre
    assert ap.AUDIT_PROTOCOL_VERSION == "gate_v_audit_protocol_v1" and report.protocol_version == ap.AUDIT_PROTOCOL_VERSION
    assert report.b4_inventory is ap.Completeness.NOT_BUILT


def test_the_authority_fields_cannot_be_supplied_by_a_constructor_nor_mutated(report):
    names = {f.name for f in dataclasses.fields(ap.AuditReport)}
    for constant in ("absence_evidence", "auxiliary_runs", "s0_facts", "persistence", "grants", "e3j_prerequisites_unmet", "not_proven", "independent_rescan_required",
                     "window_provenance", "protocol_version"):
        assert constant not in names, constant
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.receivability = ap.Receivability.REFUSED
    with pytest.raises((TypeError, ValueError)):
        dataclasses.replace(report, grants=("ADMISSION",))


def test_an_inconsistent_report_cannot_be_built():
    refusal = ap.AuditDefect(ap.RefusalCode.REQUEST_INVALID, ap.Stage.REQUEST)
    block = ap.AuditBlock(ap.BlockCode.CHAIN_INCOHERENT, "camp")
    inconsistent = [
        dict(receivability=ap.Receivability.REFUSED),                                                                        # REFUSED sans motif
        dict(receivability=ap.Receivability.RECEIVABLE, refusals=(refusal,)),                                                # RECEIVABLE avec un motif de refus
        dict(receivability=ap.Receivability.REFUSED, refusals=(refusal,), blocks=(block,)),                                  # un refus n'expose aucun statut de couche
        dict(receivability=ap.Receivability.REFUSED, refusals=(refusal,), b3_completeness=ap.Completeness.COMPLETE),
        dict(receivability=ap.Receivability.RECEIVABLE, b3_completeness=ap.Completeness.COMPLETE),                           # recevable sans rescan terminé
        dict(receivability=ap.Receivability.RECEIVABLE, b3_completeness=ap.Completeness.COMPLETE, rescan=ap.RescanStatus.PROTOCOL_RESCAN_MATCHED,
             incomplete_reasons=("X:y",)),                                                                                   # COMPLETE avec une raison d'incomplétude
        dict(receivability=ap.Receivability.RECEIVABLE, b3_completeness=ap.Completeness.NOT_BUILT, rescan=ap.RescanStatus.PROTOCOL_RESCAN_MATCHED),
        dict(receivability="RECEIVABLE"),
    ]
    for fields in inconsistent:
        with pytest.raises(ValueError):
            ap.AuditReport(**fields)
    ap.AuditReport(ap.Receivability.REFUSED, refusals=(refusal,))                                                            # le cas cohérent reste constructible


def test_the_report_has_no_serialisation_api():
    members = {name for name, _ in inspect.getmembers(ap.AuditReport)}
    for name in members:
        assert not re.match(r"(to_|from_|canonical|serial|dump|digest)", name), name
    assert not {"canonical_bytes", "report_digest"} & set(vars(ap.AuditReport))
    for cls in (ap.AuditReport, ap.RootReport, ap.AuditDefect, ap.AuditBlock, ap.ChainDefect):
        methods = {n for n, v in vars(cls).items() if inspect.isfunction(v) and not n.startswith("__")}
        assert not any(re.match(r"(to_|from_|canonical|serial)", n) for n in methods), (cls.__name__, methods)


def test_the_closed_vocabulary_is_respected_by_every_enumeration_value_and_public_identifier():
    enums = [obj for obj in vars(ap).values() if inspect.isclass(obj) and issubclass(obj, enum.Enum) and obj.__module__ == ap.__name__]
    assert len(enums) >= 10
    names = [m.value for e in enums for m in e] + [m.name for e in enums for m in e] + list(ap.__all__)
    for name in names:
        upper = name.upper()
        assert not any(bad in upper for bad in FORBIDDEN_SUBSTRINGS), name
        assert not FORBIDDEN_TOKENS & set(upper.split("_")), name
    for field in (f.name for cls in (ap.AuditReport, ap.RootReport, ap.AuditRequest) for f in dataclasses.fields(cls)):
        assert not any(bad in field.upper() for bad in FORBIDDEN_SUBSTRINGS), field
        assert not FORBIDDEN_TOKENS & set(field.upper().split("_")), field


def test_the_vocabulary_check_is_not_vacuous_it_flags_a_planted_verdict():
    assert any(bad in "FRESH_CONFIRMED" for bad in FORBIDDEN_SUBSTRINGS) and FORBIDDEN_TOKENS & set("RESCAN_OK".split("_")) and FORBIDDEN_TOKENS & set("PASS".split("_"))
    assert not FORBIDDEN_TOKENS & set("REQUEST_INVALID".split("_")) and not FORBIDDEN_TOKENS & set("SCAN_HOOKS_PRESENT".split("_"))


def test_only_the_declared_exemption_names_what_is_missing():
    """L'exemption est réelle et se limite au tuple de prérequis : lui seul contient des noms interdits ailleurs."""
    assert any("ADMISSION" in item for item in ap.E3J_PREREQUISITES_UNMET) and any("AUTHORI" in item for item in ap.E3J_PREREQUISITES_UNMET)
    assert "E3J_PREREQUISITES_UNMET" in ap.__all__ and not any(bad in "E3J_PREREQUISITES_UNMET" for bad in FORBIDDEN_SUBSTRINGS)


# ── Pureté, dépendances et graphe d'imports (AT-12, imports DIRECTS) ─────────────────────────────────────────────────────────────────────────────
def imported_modules() -> set:
    tree = ast.parse(SOURCE)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_the_protocol_imports_only_the_documented_modules():
    assert imported_modules() <= {"__future__", "dataclasses", "enum", "hashlib", "json", "os", "re", "typing",
                                   "gate_v_audit_registry", "gate_v_audit_window", "gate_v_exposure_interpreters", "gate_v_exposure_interpreters_v6", "gate_v_exposure_scan", "gate_v_exposure_sources",
                                   "gate_v_k1s2_emptiness", "gate_v_k1s2_observations", "gate_v_k1s2_verifier"}, imported_modules()
    forbidden = ("gate_v_exposure_store", "gate_v_exposure_inventory", "gate_v_inventory_preconditions", "gate_v_registry", "gate_v_final_holdout", "gate_v_campaign_manifest",
                 "gate_v_exposure_declarations", "time", "datetime", "random", "socket", "subprocess", "pathlib", "shutil", "tempfile", "urllib", "requests")
    assert not any(m.startswith(forbidden) for m in imported_modules())


def test_the_protocol_source_never_names_the_historical_b3_versions_it_refuses():
    """Garde du test historique de non-activation silencieuse de v5 (recherche de sous-chaîne dans tout module de production) : le refus se fait par liste blanche."""
    assert "gate_v_exposure_interpreters_v5" not in SOURCE and "interpret_audit_roots_v5" not in SOURCE
    assert "interpret_audit_roots(" not in SOURCE and "gate_v_exposure_interpreters_v4" not in SOURCE


def test_the_protocol_has_no_write_no_clock_no_network_no_default_limit():
    tree = ast.parse(SOURCE)
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "open" not in calls and not {"write", "write_bytes", "write_text", "mkdir", "unlink", "rename", "replace", "remove", "rmdir", "makedirs", "utime", "now", "time"} & attributes
    assert "scan_audit_roots" not in calls and "scan_audit_roots" not in SOURCE.replace("scan_audit_roots_v", "")   # jamais d'appel direct au scanner : seulement via B3 v6


def test_only_the_protocol_imports_l3a_and_no_other_production_module_names_the_protocol():
    seen_l3a, seen_self = set(), set()
    for directory, subdirectories, names in os.walk(ROOT):
        subdirectories[:] = [d for d in subdirectories if d not in {".venv", "venv", ".git", "node_modules", "tests", "__pycache__", "frontend"}]
        for name in names:
            if not name.endswith(".py") or name.startswith("gate_v_k1s2_") or name == "gate_v_audit_protocol.py":
                continue
            text = Path(directory, name).read_text(encoding="utf-8", errors="replace")
            if re.search(r"gate_v_k1s2_(verifier|observations|emptiness)", text):
                seen_l3a.add(name)
            if "gate_v_audit_protocol" in text:
                seen_self.add(name)
    assert seen_l3a == set() and seen_self == set()


def test_importing_the_protocol_loads_neither_b4_b5_the_registry_nor_the_preconditions():
    code = ("import sys; sys.path.insert(0, %r); import gate_v_audit_protocol; "
            "allowed = {'gate_v_registry_store', 'gate_v_registry_chain', 'gate_v_registry_model', 'gate_v_exposure_inventory'}; "
            "bad = [m for m in sys.modules if m.startswith(('gate_v_exposure_store', 'gate_v_exposure_inventory', 'gate_v_inventory_preconditions', 'gate_v_registry', "
            "'gate_v_final_holdout_claim_acquisition', 'gate_v_campaign_manifest', 'gate_v_exposure_declarations')) and m not in allowed]; print(sorted(bad))") % str(ROOT)
    out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip() == "[]", out.stdout


def test_the_protocol_wrote_no_a0_claim_or_registry_file_in_any_scenario(tmp_path):
    directory = scenario_dir(tmp_path, "25-all-declared-runs-present")
    before = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")}
    ap.audit_campaign_exposure(request_of(directory))
    after = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")}
    assert after == before and not any("exposure_inventory" in p or "final_holdout_access_claim" in p or "registry" in p for p in after - before)


def test_final_holdout_data_is_never_read_the_module_has_no_data_access_names():
    for word in ("final_holdout_access", "holdout_access", "load_data", "read_csv", "mt5", "ig_", "nasdaq_3m"):
        assert word not in SOURCE.lower().replace("holdout_window", ""), word


def test_pickling_or_copying_a_report_is_refused_because_it_is_not_a_portable_credential(report):
    import copy
    import pickle
    for operation in (pickle.dumps, copy.deepcopy, copy.copy):
        with pytest.raises(TypeError):
            operation(report)
    # limite de protocole assumée (T2) : en Python un objet du même processus reste forgeable (`object.__new__`) ; seuls l'absence de consommateur et la ré-exécution protègent.
