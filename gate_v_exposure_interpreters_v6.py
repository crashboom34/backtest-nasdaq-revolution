"""
gate_v_exposure_interpreters_v6.py — AF-V-07 B3 v6 (N-VIDE-1) : COMPLÉTUDE manifeste → preuves attendues, fail-closed.

Module FRÈRE de B3 v4 et de B3 v5-A, qu'il ne modifie pas. Constat mesuré (v4 ET v5, identiques) : un manifeste de campagne qui annonce une exécution en cours, échouée, incomplète, ou qui
RÉFÉRENCE une ValidationRun dont la chaîne attendue manque, laisse l'inventaire « complet » et même FRESH-éligible — B3 ne confrontait jamais le manifeste aux artefacts observés.
v6 ajoute cette confrontation, et SEULEMENT elle :

- v6 = interprétation v5 (mêmes tables, mêmes scans, mêmes findings, mêmes raisons) + des raisons d'incomplétude « MANIFEST_… » dérivées du `manifest.json` RÉELLEMENT observé par B2
  (jamais un objet fourni par l'appelant). Par construction, v6 est au moins aussi conservateur que v5 : ses raisons sont un sur-ensemble de celles de v5, ses findings sont identiques.
- Une preuve positive est exigée : manifeste lu strictement ET conforme au schéma de B3 ET propre à la campagne du dossier ; un état d'activité ou d'échec, une référence explicite,
  ou une contradiction avec les artefacts observés. Un `validations/` ou un `exposure/` vide, seul, n'est pas converti en exposition ni en incomplétude par v6 (comportement de v5 inchangé :
  les répertoires de sorties Walk-Forward et de run restent, eux, des squelettes bloquants comme en v5) ; un manifeste absent n'est pas inventé (aucune attente).
- Aucun finding, aucun hash, aucun type de source n'est fabriqué : une preuve manquante est une INCOMPLÉTUDE, pas une exposition rétrospective.
- Les raisons non résolues de v5 (sorties et preuves de run non vérifiées) ne sont JAMAIS levées. La présence de toute la chaîne apparente n'est pas une preuve d'exclusion ; la
  vérification croisée (L3), le prédicat D5, le recalcul indépendant du scan et la chronologie restent hors périmètre (N-VIDE-2, E3-J).

Activation EXPLICITE par `interpret_audit_roots_v6` ; B5 lit la version v6 sans la rendre « courante » (`RulesVersions.is_current()` inchangé).
"""

from __future__ import annotations

import dataclasses
import os
import re
from typing import Optional

import gate_v_exposure_interpreters as _b3          # internes de B3 partagés (B3 n'est pas modifié : il reste verrouillé par ses tests)
from gate_v_exposure_interpreters import RootLayout, SourceInterpretation
from gate_v_exposure_interpreters_v5 import interpret_audit_roots_v5, source_rules_v5
from gate_v_exposure_scan import EntryKind, HashLimits, ScanHooks, ScanLimits

B3_V6_SEMANTICS_VERSION = "gate_v_exposure_interpreters_v6"

# Table de reconnaissance STRICTEMENT identique à celle de v5 (mêmes objets de règles) : les `rules_digest` sont donc égaux à ceux de v5. Les valeurs sont écrites ici en LITTÉRAUX
# et un test les recalcule indépendamment (algorithme de B2 et oracle écrit à part) ; l'égalité avec v5 est constatée, jamais imposée par construction.
B3_V6_RULES_DIGESTS = (                                           # (version, disposition, rules_digest) : immuable
    (B3_V6_SEMANTICS_VERSION, RootLayout.RESULTS, "9014a865e7c5c4fea0ec7fc4cbcd3e8d76357a51693c339981e50f523ae51960"),
    (B3_V6_SEMANTICS_VERSION, RootLayout.CAMPAIGN_DIR, "aa389aca9e29052ce9812c766f99abaf95a2bb656a3e82fcff17ab041d4a10af"),
    (B3_V6_SEMANTICS_VERSION, RootLayout.SPLIT_PLAN_DIR, "e98082afc0482e2afdce61884f0da5f264a943defd666ca4aedd8b75ec217f29"),
)


def source_rules_v6(layout: RootLayout) -> tuple:
    """Table fermée EXACTE appliquée par v6 : celle de v5 (aucune règle ajoutée, aucune supprimée)."""
    return source_rules_v5(layout)


# ── Raisons d'incomplétude ajoutées par v6 : « CODE:<racine>/manifest.json#<référence> » (campagne = racine, manifeste, référence exacte) ───────────────────────────────────────
REASON_MANIFEST_RUN_IN_PROGRESS = "MANIFEST_RUN_IN_PROGRESS"                    # statut RUNNING : l'exécution n'est pas terminée
REASON_MANIFEST_TECHNICAL_FAILURE = "MANIFEST_TECHNICAL_FAILURE"                # statut TECHNICAL_FAILURE : un échec technique n'est PAS une exposition prouvée
REASON_MANIFEST_EVIDENCE_INCOMPLETE = "MANIFEST_EVIDENCE_INCOMPLETE"            # statut EVIDENCE_INCOMPLETE : le manifeste déclare lui-même les preuves incomplètes
REASON_MANIFEST_RUN_ABSENT = "MANIFEST_RUN_ABSENT"                              # run référencé dont `validation_run.json` n'est pas observé
REASON_MANIFEST_RUN_EVIDENCE_MISSING = "MANIFEST_RUN_EVIDENCE_MISSING"          # run Walk-Forward référencé dont une pièce de la chaîne attendue n'est pas observée
REASON_MANIFEST_RUN_FOREIGN = "MANIFEST_RUN_FOREIGN"                            # run référencé qui appartient à une AUTRE campagne
REASON_MANIFEST_RUN_ID_INVALID = "MANIFEST_RUN_ID_INVALID"                      # identifiant référencé qui n'est pas un run de ce type
REASON_MANIFEST_STATE_CONTRADICTION = "MANIFEST_STATE_CONTRADICTION"            # drapeaux / statut / raison d'échec incohérents entre eux
REASON_MANIFEST_ARTEFACTS_WITHOUT_EXECUTION = "MANIFEST_ARTEFACTS_WITHOUT_EXECUTION"   # statut initial, mais des artefacts d'exécution sont observés

_RUN_ID = re.compile(r"(gate_v_v2_[0-9a-f]{64})_(walk_forward|monte_carlo|parameter_stability_fold_[0-9]{3})")
_SESSION = re.compile(r"validations/[^/]+/run_session_[0-9]{4}\.json")
_FIELD_KIND = (("walk_forward_validation_run_id", "walk_forward"), ("monte_carlo_validation_run_id", "monte_carlo"))
_WF_CHAIN = ("run_data_coverage.json", "run_session_0001.json", "run_seal.json")        # pièces de la chaîne attendue d'un run Walk-Forward (preuves de L2) ; un fichier de session suffit


def _ref(code: str, label: str, reference: str) -> str:
    return f"{code}:{label}/manifest.json#{reference}"


def _declared_runs(record: dict) -> list:
    """(champ, identifiant, type attendu) des runs RÉFÉRENCÉS par le manifeste, dans un ordre déterministe."""
    runs = [(field, record[field], kind) for field, kind in _FIELD_KIND if record[field] is not None]
    runs += [(f"parameter_stability_validation_run_ids_by_fold[{key}]", value, "parameter_stability_fold") for key, value in sorted(record["parameter_stability_validation_run_ids_by_fold"].items())]
    return runs


def _manifest_reasons(label: str, campaign: str, record: dict, files: set) -> list:
    """Raisons d'un manifeste LU, CONFORME et propre à sa campagne, confronté aux fichiers observés de SA racine."""
    status, started, running, failure = record["status"], record["execution_started"], record["running"], record["technical_failure_reason"]
    reasons = []
    if status == "RUNNING":
        reasons.append(_ref(REASON_MANIFEST_RUN_IN_PROGRESS, label, "status"))
    elif status == "TECHNICAL_FAILURE":
        reasons.append(_ref(REASON_MANIFEST_TECHNICAL_FAILURE, label, "status"))
    elif status == "EVIDENCE_INCOMPLETE":
        reasons.append(_ref(REASON_MANIFEST_EVIDENCE_INCOMPLETE, label, "status"))
    if running != (status == "RUNNING"):
        reasons.append(_ref(REASON_MANIFEST_STATE_CONTRADICTION, label, "running_vs_status"))
    if (failure is None) == (status == "TECHNICAL_FAILURE"):
        reasons.append(_ref(REASON_MANIFEST_STATE_CONTRADICTION, label, "failure_reason_vs_status"))
    declared = _declared_runs(record)
    if status == "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT" and (record["walk_forward_validation_run_id"] is None or record["monte_carlo_validation_run_id"] is None
                                                                 or not record["parameter_stability_validation_run_ids_by_fold"]):
        reasons.append(_ref(REASON_MANIFEST_STATE_CONTRADICTION, label, "complete_vs_references"))      # « preuves complètes » sans référencer tous les runs attendus (contrat D2)
    if status == "READY_FOR_EXECUTION":
        if started or declared:
            reasons.append(_ref(REASON_MANIFEST_STATE_CONTRADICTION, label, "ready_vs_activity"))
        if record["manifest_revision"] > 0:        # le producteur réel (D2) incrémente la révision à chaque commande et `execution_started` ne revient jamais à faux : un manifeste initial a la révision 0
            reasons.append(_ref(REASON_MANIFEST_STATE_CONTRADICTION, label, "ready_vs_revision"))
        artefacts = sorted(path for path in files if path.startswith("walk_forward/") or (path.startswith("validations/") and path.count("/") >= 2))
        if artefacts:
            reasons.append(_ref(REASON_MANIFEST_ARTEFACTS_WITHOUT_EXECUTION, label, artefacts[0]))
    for field, run_id, kind in declared:
        match = _RUN_ID.fullmatch(run_id) if type(run_id) is str else None
        if match is None or not match.group(2).startswith(kind):
            reasons.append(_ref(REASON_MANIFEST_RUN_ID_INVALID, label, f"{field}={run_id}"))
        elif match.group(1) != campaign:
            reasons.append(_ref(REASON_MANIFEST_RUN_FOREIGN, label, f"{field}={run_id}"))
        elif f"validations/{run_id}/validation_run.json" not in files:
            reasons.append(_ref(REASON_MANIFEST_RUN_ABSENT, label, f"{field}->validations/{run_id}/validation_run.json"))
        elif kind == "walk_forward":
            prefix = f"validations/{run_id}/"
            for name in _WF_CHAIN:
                present = any(_SESSION.fullmatch(path) and path.startswith(prefix) for path in files) if name == "run_session_0001.json" else prefix + name in files
                if not present:
                    reasons.append(_ref(REASON_MANIFEST_RUN_EVIDENCE_MISSING, label, f"{field}->{prefix}{name}"))
    return reasons


def _manifest_completeness(scans: tuple) -> list:
    """Raisons v6 pour chaque racine de campagne dont le manifeste est lu sans anomalie, conforme et propre à la campagne. Sinon (absent, illisible, non conforme, étranger) : AUCUNE
    attente n'est inventée — v4/v5 bloquent déjà un manifeste non conforme (`INFORMATIVE_UNRESOLVED`) ou anormal."""
    root_names = {root.label: os.path.basename(root.path) for item in scans for root in item.scan.roots}
    files_by_root: dict = {}
    manifests: dict = {}
    for item in scans:
        for observation in item.scan.observations:
            if observation.kind is EntryKind.FILE:
                files_by_root.setdefault(observation.root_label, set()).add(observation.relative_path)
            if (observation.rule_tag == _b3.TAG_CAMPAIGN_MANIFEST and observation.relative_path == "manifest.json" and observation.anomaly is None and observation.value_parsed
                    and observation.root_label in root_names):
                manifests[observation.root_label] = observation.value
    reasons = []
    for label in sorted(manifests):
        record = manifests[label]
        if type(record) is dict and _b3._manifest_v2_conforms(record, root_names[label]):
            reasons.extend(_manifest_reasons(label, root_names[label], record, files_by_root.get(label, set())))
    return reasons


def interpret_audit_roots_v6(roots: tuple, limits: ScanLimits, *, hash_limits: HashLimits, holdout_window_start_utc: str, holdout_window_end_utc: str,
                             hooks: Optional[ScanHooks] = None) -> SourceInterpretation:
    """Équivalent de l'interprétation v5 avec la complétude manifeste → preuves (N-VIDE-1). Activation EXPLICITE ; `hash_limits` obligatoire, sans défaut. Aucune observation n'est jamais
    reçue d'un appelant : le manifeste vient du scan B2 de cette invocation. Les erreurs de structure et d'instabilité de B2 se propagent telles quelles."""
    base = interpret_audit_roots_v5(roots, limits, hash_limits=hash_limits, holdout_window_start_utc=holdout_window_start_utc,
                                    holdout_window_end_utc=holdout_window_end_utc, hooks=hooks)
    reasons = tuple(sorted(set(base.incomplete_reasons) | set(_manifest_completeness(base.scans))))
    return dataclasses.replace(base, semantics_version=B3_V6_SEMANTICS_VERSION, complete=not reasons, incomplete_reasons=reasons)
