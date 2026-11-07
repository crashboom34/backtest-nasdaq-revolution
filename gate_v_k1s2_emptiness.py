"""
gate_v_k1s2_emptiness.py — K1 Étape 2, lot L3-A : DIAGNOSTIC PUR des situations de répertoires vides ou incomplets d'une campagne Walk-Forward.

Constat mesuré (B3 v4 publié ET B3 v5-A, identiques) : une campagne dont `validations/` et/ou `exposure/` est vide, même si son `manifest.json` déclare un run
Walk-Forward absent (`EVIDENCE_INCOMPLETE`), un état `RUNNING` ou un `TECHNICAL_FAILURE`, reste éligible à FRESH : B3 n'impose pas l'artefact qu'un manifeste annonce.
Ce module ne corrige PAS B3 (historique, hors périmètre) ; il CLASSE ce que les observations fournies permettent de dire, pour qu'un futur consommateur (E3-J) ne
traite jamais un vide comme une absence établie lorsqu'une déclaration impose un artefact.

Catégories (jamais un verdict) :
  A  vide, et RIEN dans l'arbre ni dans le manifeste ne déclare ou n'atteste une exécution (aucun artefact, aucune entrée inconnue) — ce n'est ni « non exposé » ni « aucune
     exécution attendue » : seule une relecture indépendante pourra s'en servir ;
  B  un manifeste, un état ou une référence IMPOSE un artefact (run déclaré, ValidationRun sans preuves, sorties sans preuves...) qui manque ;
  C  interruption ATTESTÉE (manifeste `RUNNING` ou `TECHNICAL_FAILURE`, résidu de publication, exécution démarrée sans artefact) ;
  CONTRADICTORY  déclaration illisible, étrangère ou incohérente avec l'arbre ;
  UNRESOLVED_ENTRIES  entrée inconnue ou en anomalie quelque part dans l'arbre ;
  NOT_EMPTY  des artefacts existent sans que ce diagnostic y voie un manque : il n'accorde RIEN (la vérification de chaîne s'applique seule).
B, C, UNRESOLVED_ENTRIES et CONTRADICTORY ne bénéficient JAMAIS d'une absence établie (`absence_consideration_blocked`). Ce drapeau est un BLOCAGE ; son absence (catégorie A) n'est pas une
autorisation. Aucune sortie de ce module n'est FRESH, NO_OVERLAP, admission, Claim ou autorisation FINAL_HOLDOUT.

Module PUR : aucune E/S ; il lit les octets du `manifest.json` déjà conservés par `gate_v_k1s2_observations`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import gate_v_k1s2_verifier as vf
from gate_v_exposure_interpreters import MANIFEST_V2_KEYS, _manifest_v2_conforms     # schéma EXACT de B3 (aucune copie qui puisse dériver)
from gate_v_exposure_scan import StrictJsonError, parse_strict_json

__all__ = ["EmptinessCategory", "EmptinessDiagnostic", "EmptinessReason", "diagnose_emptiness"]

_MANIFEST = "manifest.json"
_SESSION = re.compile(r"run_session_[0-9]{4}\.json")
_JSON_DEPTH = 64


class EmptinessCategory(str, Enum):
    NOT_EMPTY = "NOT_EMPTY"                                  # rien de vide ni d'imposé qui manque : la vérification de chaîne s'applique seule
    A_EMPTY_NO_DECLARATION = "A_EMPTY_NO_DECLARATION"
    B_ARTEFACT_IMPOSED_BUT_ABSENT = "B_ARTEFACT_IMPOSED_BUT_ABSENT"
    C_ATTESTED_INTERRUPTION = "C_ATTESTED_INTERRUPTION"
    UNRESOLVED_ENTRIES = "UNRESOLVED_ENTRIES"                # entrée inconnue ou en anomalie quelque part : aucune absence ne peut être considérée
    CONTRADICTORY = "CONTRADICTORY"
    BAD_INPUT = "BAD_INPUT"


class EmptinessReason(str, Enum):
    BAD_INPUT = "BAD_INPUT"
    NO_DECLARATION_FOUND = "NO_DECLARATION_FOUND"                            # A
    DECLARED_RUN_DIRECTORY_ABSENT = "DECLARED_RUN_DIRECTORY_ABSENT"          # B
    DECLARED_RUN_DIRECTORY_EMPTY = "DECLARED_RUN_DIRECTORY_EMPTY"
    DECLARED_RUN_WITHOUT_RECORD = "DECLARED_RUN_WITHOUT_RECORD"
    RUN_RECORD_WITHOUT_EVIDENCE = "RUN_RECORD_WITHOUT_EVIDENCE"
    EVIDENCE_WITHOUT_RUN_RECORD = "EVIDENCE_WITHOUT_RUN_RECORD"
    OUTPUTS_WITHOUT_EVIDENCE = "OUTPUTS_WITHOUT_EVIDENCE"
    STATUS_IMPOSES_EVIDENCE = "STATUS_IMPOSES_EVIDENCE"
    DECLARED_AUXILIARY_RUN_ABSENT = "DECLARED_AUXILIARY_RUN_ABSENT"          # run Monte-Carlo / stabilité déclaré, validation_run.json absent
    MANIFEST_RUNNING = "MANIFEST_RUNNING"                                    # C
    MANIFEST_TECHNICAL_FAILURE = "MANIFEST_TECHNICAL_FAILURE"
    EXECUTION_STARTED_WITHOUT_ARTEFACT = "EXECUTION_STARTED_WITHOUT_ARTEFACT"
    PUBLICATION_ORPHAN = "PUBLICATION_ORPHAN"
    UNRESOLVED_ENTRY_PRESENT = "UNRESOLVED_ENTRY_PRESENT"
    MANIFEST_UNREADABLE = "MANIFEST_UNREADABLE"                              # CONTRADICTORY : la déclaration ne peut pas être crue
    MANIFEST_NOT_CONFORMING = "MANIFEST_NOT_CONFORMING"
    FOREIGN_MANIFEST = "FOREIGN_MANIFEST"
    DECLARED_RUN_MISMATCH = "DECLARED_RUN_MISMATCH"
    STATE_FLAGS_CONTRADICTION = "STATE_FLAGS_CONTRADICTION"
    ARTEFACTS_WITHOUT_EXECUTION = "ARTEFACTS_WITHOUT_EXECUTION"


_B = frozenset({EmptinessReason.DECLARED_RUN_DIRECTORY_ABSENT, EmptinessReason.DECLARED_RUN_DIRECTORY_EMPTY, EmptinessReason.DECLARED_RUN_WITHOUT_RECORD,
                EmptinessReason.RUN_RECORD_WITHOUT_EVIDENCE, EmptinessReason.EVIDENCE_WITHOUT_RUN_RECORD, EmptinessReason.OUTPUTS_WITHOUT_EVIDENCE,
                EmptinessReason.STATUS_IMPOSES_EVIDENCE, EmptinessReason.DECLARED_AUXILIARY_RUN_ABSENT})
_C = frozenset({EmptinessReason.MANIFEST_RUNNING, EmptinessReason.MANIFEST_TECHNICAL_FAILURE, EmptinessReason.EXECUTION_STARTED_WITHOUT_ARTEFACT,
                EmptinessReason.PUBLICATION_ORPHAN})
_CONTRADICTORY = frozenset({EmptinessReason.MANIFEST_UNREADABLE, EmptinessReason.MANIFEST_NOT_CONFORMING, EmptinessReason.FOREIGN_MANIFEST,
                            EmptinessReason.DECLARED_RUN_MISMATCH, EmptinessReason.STATE_FLAGS_CONTRADICTION, EmptinessReason.ARTEFACTS_WITHOUT_EXECUTION})


@dataclass(frozen=True)
class EmptinessDiagnostic:
    category: EmptinessCategory
    reasons: tuple
    empty_directories: tuple
    declared_run_id: Optional[str] = None

    def __post_init__(self) -> None:
        if (type(self.category) is not EmptinessCategory or type(self.reasons) is not tuple or any(type(r) is not EmptinessReason for r in self.reasons)
                or type(self.empty_directories) is not tuple or any(type(d) is not str for d in self.empty_directories)
                or (self.declared_run_id is not None and type(self.declared_run_id) is not str)):
            raise ValueError("EmptinessDiagnostic mal formé")

    @property
    def absence_consideration_blocked(self) -> bool:
        """Vrai pour B, C, CONTRADICTORY et BAD_INPUT : aucune absence ne peut être « établie » à partir de ces observations. Faux ne signifie PAS autorisé."""
        return self.category in (EmptinessCategory.B_ARTEFACT_IMPOSED_BUT_ABSENT, EmptinessCategory.C_ATTESTED_INTERRUPTION, EmptinessCategory.CONTRADICTORY,
                                 EmptinessCategory.UNRESOLVED_ENTRIES, EmptinessCategory.BAD_INPUT)

    @property
    def requires_independent_rescan(self) -> bool:
        return True

    @property
    def not_proven(self) -> tuple:
        return vf.NOT_PROVEN


def _under(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory + "/")


def _manifest_facts(tree, reasons: set):
    """Enregistrement d'un manifeste lisible et conforme ; sinon `None` et une raison. Schéma : celui de B3 (`_manifest_v2_conforms`), jamais plus faible."""
    item = next((i for i in tree.items if i.path == _MANIFEST), None)
    if item is None:
        return None
    if item.kind is not vf.ObservedKind.FILE or item.content is None:
        reasons.add(EmptinessReason.MANIFEST_UNREADABLE)
        return None
    try:
        record = parse_strict_json(item.content, max_bytes=vf.MAX_CONTENT_BYTES, max_depth=_JSON_DEPTH)
    except StrictJsonError:
        reasons.add(EmptinessReason.MANIFEST_UNREADABLE)
        return None
    campaign_id = record.get("campaign_id") if type(record) is dict else None
    if type(campaign_id) is not str or not _manifest_v2_conforms(record, campaign_id):          # schéma complet de B3 ; l'égalité au dossier est testée ensuite
        reasons.add(EmptinessReason.MANIFEST_NOT_CONFORMING)
        return None
    if record["campaign_id"] != tree.campaign_dir_name:
        reasons.add(EmptinessReason.FOREIGN_MANIFEST)
        return None
    return record


def diagnose_emptiness(tree) -> EmptinessDiagnostic:
    """Classe la situation de vide / d'artefacts imposés d'un `ObservedRunTree`. FONCTION TOTALE et déterministe, SAUF épuisement de ressources (`MemoryError`,
    `RecursionError`), qui se propage (B2 ne la convertit plus en raison typée sur un document d'imbrication <= 64) ; ne prononce aucun verdict. Une observation FORGÉE qui ferait échouer le calcul est classée `BAD_INPUT` (blocage), jamais une exception."""
    try:
        return _diagnose_emptiness(tree)
    except (MemoryError, RecursionError):                        # P5-bis (A1) : épuisement de ressources, jamais un défaut des données ; se propage (le protocole rend AUDIT_INTERNAL_FAILURE)
        raise
    except Exception:                                            # noqa: BLE001 — voie conservatrice (inchangée : `RuntimeError` hors ressources comprise)
        return EmptinessDiagnostic(EmptinessCategory.BAD_INPUT, (EmptinessReason.BAD_INPUT,), ())


def _diagnose_emptiness(tree) -> EmptinessDiagnostic:
    if type(tree) is not vf.ObservedRunTree:
        return EmptinessDiagnostic(EmptinessCategory.BAD_INPUT, (EmptinessReason.BAD_INPUT,), ())
    run_id = f"{tree.campaign_dir_name}_walk_forward"
    run_dir = f"validations/{run_id}"
    reasons: set = set()
    content = [i for i in tree.items if i.kind is not vf.ObservedKind.DIRECTORY]
    populated = vf.ancestor_directories(i.path for i in content)                                                  # ancêtres de tout contenu (linéaire)
    relevant = lambda p: p in ("validations", "exposure", "walk_forward") or _under(p, "walk_forward") or p == run_dir  # noqa: E731
    empty = tuple(sorted(i.path for i in tree.items if i.kind is vf.ObservedKind.DIRECTORY and relevant(i.path) and i.path not in populated))
    in_run = [i for i in tree.items if i.path != run_dir and _under(i.path, run_dir)]
    run_content = [i for i in in_run if i.kind is not vf.ObservedKind.DIRECTORY]
    outputs = [i for i in content if _under(i.path, "walk_forward") and i.kind is not vf.ObservedKind.ORPHAN]
    orphans = [i for i in content if i.kind is vf.ObservedKind.ORPHAN]                                              # un résidu de publication, où qu'il soit
    unresolved = [i for i in tree.items if i.kind in (vf.ObservedKind.UNKNOWN, vf.ObservedKind.ANOMALY)]
    validations_content = [i for i in content if _under(i.path, "validations")]                                      # tout run, de tout type
    files = {i.path[len(run_dir) + 1:] for i in run_content if i.kind is vf.ObservedKind.FILE}
    has_record, has_seal, has_coverage = "validation_run.json" in files, "run_seal.json" in files, "run_data_coverage.json" in files
    has_session = any(_SESSION.fullmatch(name) for name in files)
    evidence = has_coverage or has_seal or has_session
    evidence_complete = has_coverage and has_seal and has_session
    run_dir_known = any(i.path == run_dir for i in tree.items) or bool(in_run)
    artefacts = bool(validations_content or outputs or orphans)

    manifest = _manifest_facts(tree, reasons)
    declared = None
    if manifest is not None:
        status, started, running, declared = manifest["status"], manifest["execution_started"], manifest["running"], manifest["walk_forward_validation_run_id"]
        auxiliary = [rid for rid in (manifest["monte_carlo_validation_run_id"], *manifest["parameter_stability_validation_run_ids_by_fold"].values()) if rid is not None]
        failure = manifest["technical_failure_reason"]
        if declared is not None and declared != run_id:
            reasons.add(EmptinessReason.DECLARED_RUN_MISMATCH)
        if (running != (status == "RUNNING")) or (status == "READY_FOR_EXECUTION" and (started or running or declared is not None or auxiliary)) \
                or (status == "TECHNICAL_FAILURE" and failure is None) or (failure is not None and status != "TECHNICAL_FAILURE"):
            reasons.add(EmptinessReason.STATE_FLAGS_CONTRADICTION)
        if status == "READY_FOR_EXECUTION" and artefacts:
            reasons.add(EmptinessReason.ARTEFACTS_WITHOUT_EXECUTION)
        if status == "RUNNING":
            reasons.add(EmptinessReason.MANIFEST_RUNNING)
        if status == "TECHNICAL_FAILURE":
            reasons.add(EmptinessReason.MANIFEST_TECHNICAL_FAILURE)
        present_files = {i.path for i in content if i.kind is vf.ObservedKind.FILE}
        if any(f"validations/{rid}/validation_run.json" not in present_files for rid in auxiliary):                      # run déclaré, enregistrement absent
            reasons.add(EmptinessReason.DECLARED_AUXILIARY_RUN_ABSENT)
        if status in ("EVIDENCE_INCOMPLETE", "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT"):
            if declared == run_id:
                if not run_dir_known:
                    reasons.add(EmptinessReason.DECLARED_RUN_DIRECTORY_ABSENT)
                elif not run_content:
                    reasons.add(EmptinessReason.DECLARED_RUN_DIRECTORY_EMPTY)
                elif not has_record:
                    reasons.add(EmptinessReason.DECLARED_RUN_WITHOUT_RECORD)
            elif declared is None and started and not artefacts:
                reasons.add(EmptinessReason.EXECUTION_STARTED_WITHOUT_ARTEFACT)
            if status == "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT" and not (has_record and evidence_complete):
                reasons.add(EmptinessReason.STATUS_IMPOSES_EVIDENCE)
    if orphans:
        reasons.add(EmptinessReason.PUBLICATION_ORPHAN)
    if unresolved:
        reasons.add(EmptinessReason.UNRESOLVED_ENTRY_PRESENT)
    if has_record and not evidence_complete:
        reasons.add(EmptinessReason.RUN_RECORD_WITHOUT_EVIDENCE)
    if evidence and not has_record:
        reasons.add(EmptinessReason.EVIDENCE_WITHOUT_RUN_RECORD)
    if outputs and not evidence_complete:
        reasons.add(EmptinessReason.OUTPUTS_WITHOUT_EVIDENCE)

    if reasons & _CONTRADICTORY:
        category = EmptinessCategory.CONTRADICTORY
    elif reasons & _C:
        category = EmptinessCategory.C_ATTESTED_INTERRUPTION
    elif reasons & _B:
        category = EmptinessCategory.B_ARTEFACT_IMPOSED_BUT_ABSENT
    elif unresolved:
        category = EmptinessCategory.UNRESOLVED_ENTRIES
    elif not artefacts:
        category = EmptinessCategory.A_EMPTY_NO_DECLARATION
        reasons.add(EmptinessReason.NO_DECLARATION_FOUND)
    else:
        category = EmptinessCategory.NOT_EMPTY
    return EmptinessDiagnostic(category, tuple(sorted(reasons, key=lambda r: r.value)), empty, declared)
