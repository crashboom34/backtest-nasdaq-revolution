"""
gate_v_exposure_interpreters_v5.py — AF-V-07 B3 v5-A : tables FERMÉES des artefacts K1 (reconnaissance structurelle seulement).

Module FRÈRE de `gate_v_exposure_interpreters` (B3, v4), qu'il ne modifie pas : les tables, digests, versions et signatures de B3 publiés restent
byte pour byte ceux de v4, et les consommateurs historiques ne basculent pas en silence — v5 s'active en appelant `interpret_audit_roots_v5`
(voir B5 : un A0 de v5 est LISIBLE mais `rules_versions.is_current()` reste faux tant qu'aucune décision d'activation n'a changé la version courante).

Ce lot RECONNAÎT des artefacts réels ou prévus ; il ne conclut RIEN sur l'absence d'exposition (ADR 0025 23.30.1) :
- sorties Walk-Forward (`walk_forward/**`, checkpoints V1 compris) : `HASHED_FILE`, lues par B2 pour leur seul SHA-256, jamais interprétées ; leurs RÉPERTOIRES
  comptent aussi (un dossier de fold n'existe qu'après le calcul du fold : un squelette vidé reste une source non résolue, comme en v4) ;
- preuves de run `run_data_coverage.json`, `run_session_NNNN.json`, `run_seal.json` d'un run Walk-Forward : lues strictement (contrats purs de L2,
  `gate_v_run_evidence_models`), aucune vérification croisée (relève de L3) ; la couverture `DERIVED` (MC/PS) n'est pas acceptée ;
- orphelins de `save_atomic` (`publication_orphan_pattern`) pour les seules cibles écrites par le code réel.
Toute source reconnue reste BLOQUANTE : un finding `UNRESOLVED` (jamais `RESOLVED`, jamais `NO_OVERLAP`), le `content_hash` des octets bruts quand il
existe, et une raison d'incomplétude. Aucun nouveau `SourceKind`, aucune formule d'E3-A modifiée, aucun FRESH nouveau.
"""

from __future__ import annotations

import os
from typing import Optional

import gate_v_exposure_interpreters as _b3          # internes de B3 partagés avec ce module frère (B3 n'est pas modifié : il reste verrouillé par ses tests)
import gate_v_run_evidence_models as ev
from gate_v_exposure_interpreters import _CAMPAIGN_RUN_DIR, LayoutRoot, RootLayout, SourceInterpretation, source_rules
from gate_v_exposure_scan import (
    EntryClass,
    HashLimits,
    JsonKind,
    ScanHooks,
    ScanLimits,
    SegmentPattern,
    SourceRule,
    publication_orphan_pattern,
    scan_audit_roots,
)
from gate_v_exposure_sources import normalize_window
from gate_v_final_holdout_protocol import SourceKind, UnresolvedCause

B3_V5_SEMANTICS_VERSION = "gate_v_exposure_interpreters_v5"

TAG_WF_DIR = "wf.output.dir"
TAG_WF_FOLDS = "wf.output.folds"
TAG_WF_FOLD = "wf.output.fold"
TAG_WF_MANIFEST = "wf.output.manifest"
TAG_WF_STATE = "wf.output.state"
TAG_WF_AGGREGATE = "wf.output.aggregate"
TAG_WF_FOLD_JSON = "wf.output.fold_json"
TAG_WF_FOLD_CSV = "wf.output.fold_csv"
TAG_WF_ORPHAN = "wf.output.orphan"
TAG_CHECKPOINT_DIR = "wf.checkpoint.dir"
TAG_CHECKPOINT_MANIFEST = "wf.checkpoint.manifest"
TAG_CHECKPOINT_FOLDS = "wf.checkpoint.folds"
TAG_CHECKPOINT_FOLD = "wf.checkpoint.fold"
TAG_COVERAGE = "validation.coverage"
TAG_SESSION = "validation.session"
TAG_SEAL = "validation.seal"
TAG_RUN_ORPHAN = "validation.run.orphan"

# Producteurs réels : `walk_forward.persist_walk_forward_run` (manifest, state, aggregate, folds/fold_NNN/*), la capture V1 (`.gate_v_checkpoints_v1`),
# `gate_v_campaign._run_walk_forward_phase` (racine `<campagne>/walk_forward`). `train_progress.csv` (reprise héritée, supprimé en fin de fold) n'est
# PAS reconnu : un fichier laissé là est une trace d'exécution interrompue, donc une entrée inconnue bloquante.
_WF_DIR = "walk_forward"
_CHECKPOINT_DIR = ".gate_v_checkpoints_v1"
_FOLD_DIR = SegmentPattern(r"fold_[0-9]{3}")
_FOLD_JSON_FILE = SegmentPattern(r"fold_[0-9]{3}\.json")
_WF_RUN_DIR = SegmentPattern(r"gate_v_v2_[0-9a-f]{64}_walk_forward")
_SESSION_FILE = SegmentPattern(r"run_session_[0-9]{4}\.json")
_WF_OUTPUT_JSON = (("manifest.json", TAG_WF_MANIFEST), ("state.json", TAG_WF_STATE), ("aggregate.json", TAG_WF_AGGREGATE))
_FOLD_JSON = ("definition.json", "selection.json", "test_result.json")
_FOLD_CSV = ("train_candidates.csv", "oos_trades.csv", "oos_equity.csv")      # `pandas.to_csv` : écriture non atomique, donc aucun orphelin


def _wf_output_rules() -> tuple:
    root = (_WF_DIR,)
    rules = [SourceRule(root, EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_WF_DIR)]
    for name, tag in _WF_OUTPUT_JSON:
        rules.append(SourceRule(root + (name,), EntryClass.HASHED_FILE, tag=tag))
        rules.append(SourceRule(root + (publication_orphan_pattern(name),), EntryClass.TEMP_ORPHAN_FILE, tag=TAG_WF_ORPHAN))
    folds = root + ("folds",)
    rules.append(SourceRule(folds, EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_WF_FOLDS))
    rules.append(SourceRule(folds + (_FOLD_DIR,), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_WF_FOLD))
    for name in _FOLD_JSON:
        rules.append(SourceRule(folds + (_FOLD_DIR, name), EntryClass.HASHED_FILE, tag=TAG_WF_FOLD_JSON))
        rules.append(SourceRule(folds + (_FOLD_DIR, publication_orphan_pattern(name)), EntryClass.TEMP_ORPHAN_FILE, tag=TAG_WF_ORPHAN))
    for name in _FOLD_CSV:
        rules.append(SourceRule(folds + (_FOLD_DIR, name), EntryClass.HASHED_FILE, tag=TAG_WF_FOLD_CSV))
    checkpoint = root + (_CHECKPOINT_DIR,)
    rules.append(SourceRule(checkpoint, EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_CHECKPOINT_DIR))
    rules.append(SourceRule(checkpoint + ("manifest.json",), EntryClass.HASHED_FILE, tag=TAG_CHECKPOINT_MANIFEST))
    rules.append(SourceRule(checkpoint + (publication_orphan_pattern("manifest.json"),), EntryClass.TEMP_ORPHAN_FILE, tag=TAG_WF_ORPHAN))
    rules.append(SourceRule(checkpoint + ("folds",), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_CHECKPOINT_FOLDS))
    rules.append(SourceRule(checkpoint + ("folds", _FOLD_JSON_FILE), EntryClass.HASHED_FILE, tag=TAG_CHECKPOINT_FOLD))
    rules.append(SourceRule(checkpoint + ("folds", publication_orphan_pattern(_FOLD_JSON_FILE)), EntryClass.TEMP_ORPHAN_FILE, tag=TAG_WF_ORPHAN))
    return tuple(rules)


def _run_evidence_rules() -> tuple:
    """Preuves d'un run Walk-Forward UNIQUEMENT (couverture `MARKET_DATA_FRAME`) ; les dossiers MC/PS restent ceux de v4 (couverture `DERIVED` non acceptée)."""
    return (
        SourceRule(("validations", _WF_RUN_DIR, "run_data_coverage.json"), EntryClass.EXPOSING_JSON, JsonKind.OBJECT, tag=TAG_COVERAGE),
        SourceRule(("validations", _WF_RUN_DIR, _SESSION_FILE), EntryClass.EXPOSING_JSON, JsonKind.OBJECT, tag=TAG_SESSION),
        SourceRule(("validations", _WF_RUN_DIR, "run_seal.json"), EntryClass.EXPOSING_JSON, JsonKind.OBJECT, tag=TAG_SEAL),
        # `validation_run.json` est écrit par `save_validation_run` (`save_atomic`) : son orphelin est un résidu connu, jamais le fichier attendu.
        SourceRule(("validations", _CAMPAIGN_RUN_DIR, publication_orphan_pattern("validation_run.json")), EntryClass.TEMP_ORPHAN_FILE, tag=TAG_RUN_ORPHAN),
    )


# Table v5 : RESULTS et SPLIT_PLAN_DIR sont EXACTEMENT celles de v4 (mêmes objets) ; CAMPAIGN_DIR = table v4 INCHANGÉE, en tête et dans le même ordre,
# puis les ajouts ci-dessus.
_CAMPAIGN_RULES_V5 = (*source_rules(RootLayout.CAMPAIGN_DIR), *_wf_output_rules(), *_run_evidence_rules())
_TABLES_V5 = {RootLayout.RESULTS: source_rules(RootLayout.RESULTS), RootLayout.CAMPAIGN_DIR: _CAMPAIGN_RULES_V5,
              RootLayout.SPLIT_PLAN_DIR: source_rules(RootLayout.SPLIT_PLAN_DIR)}


def source_rules_v5(layout: RootLayout) -> tuple:
    """Table fermée EXACTE appliquée par B3 v5 à une disposition (exposée pour l'audit, les tests de fermeture et la concordance B5)."""
    return _TABLES_V5[layout]


# `rules_digest` de la table appliquée par v5, par disposition : valeurs FIGÉES, mesurées avec l'algorithme de B2 (`_rules_digest`) le 2026-10-25 et revérifiées
# par un test (algorithme de B2 ET oracle indépendant). RESULTS et SPLIT_PLAN_DIR : identiques à v4 (tables inchangées).
_V5 = B3_V5_SEMANTICS_VERSION
B3_V5_RULES_DIGESTS = (                                           # (version, disposition, rules_digest) : immuable
    (_V5, RootLayout.RESULTS, "9014a865e7c5c4fea0ec7fc4cbcd3e8d76357a51693c339981e50f523ae51960"),
    (_V5, RootLayout.CAMPAIGN_DIR, "aa389aca9e29052ce9812c766f99abaf95a2bb656a3e82fcff17ab041d4a10af"),
    (_V5, RootLayout.SPLIT_PLAN_DIR, "e98082afc0482e2afdce61884f0da5f264a943defd666ca4aedd8b75ec217f29"),
)


# ── Interprétation ───────────────────────────────────────────────────────────────────────────────────────────────
# Raisons d'incomplétude ajoutées par v5 (chaînes « CODE:<label>/<chemin> », comme celles de B3). Toute source reconnue ici BLOQUE : aucune n'établit
# l'absence d'exposition, aucune ne prouve qu'un run est terminé, que ses sorties sont exhaustives ni qu'une donnée a réellement été lue.
REASON_RUN_OUTPUT_UNVERIFIED = "RUN_OUTPUT_UNVERIFIED"        # sortie Walk-Forward hachée, non vérifiée par un scellement (L3)
REASON_RUN_EVIDENCE_UNVERIFIED = "RUN_EVIDENCE_UNVERIFIED"    # couverture, session ou sceau syntaxiquement valides, non vérifiés (chaîne, chronologie)
REASON_RUN_ORPHAN = "RUN_ORPHAN"                              # résidu d'une écriture interrompue : ni sortie, ni preuve, jamais supprimé

_HASHED_TAGS = frozenset({TAG_WF_MANIFEST, TAG_WF_STATE, TAG_WF_AGGREGATE, TAG_WF_FOLD_JSON, TAG_WF_FOLD_CSV, TAG_CHECKPOINT_MANIFEST, TAG_CHECKPOINT_FOLD})
_ORPHAN_TAGS = frozenset({TAG_WF_ORPHAN, TAG_RUN_ORPHAN})
_EVIDENCE_TAGS = frozenset({TAG_COVERAGE, TAG_SESSION, TAG_SEAL})
# Les répertoires de sorties comptent AUSSI : un dossier de fold n'est créé qu'après le calcul du fold, donc un squelette vidé (dossiers sans fichier) est la trace
# d'un calcul. v4 le bloquait (dossier inconnu) ; v5 ne doit jamais être moins bloquant (défaut démontré par la revue indépendante, RED puis GREEN).
_STRUCTURAL_RUN_TAGS = frozenset({TAG_WF_DIR, TAG_WF_FOLDS, TAG_WF_FOLD, TAG_CHECKPOINT_DIR, TAG_CHECKPOINT_FOLDS})
_RUN_TAGS = _HASHED_TAGS | _ORPHAN_TAGS | _EVIDENCE_TAGS | _STRUCTURAL_RUN_TAGS


def _evidence_conforms(observation) -> bool:
    """Contrat pur de L2 (octets normatifs, clés et types exacts, versions) ET cohérence MINIMALE avec le chemin : identifiant de run = nom du dossier, indice
    de session = numéro du fichier, sceau d'un run Walk-Forward. Aucune vérification croisée entre fichiers (relève de L3)."""
    segments = observation.relative_path.split("/")
    run_directory, name = segments[-2], segments[-1]
    try:
        if observation.rule_tag == TAG_COVERAGE:
            return ev.RunDataCoverage.from_bytes(observation.content_bytes).validation_run_id == run_directory
        if observation.rule_tag == TAG_SESSION:
            session = ev.RunSession.from_bytes(observation.content_bytes)
            return session.validation_run_id == run_directory and name == f"run_session_{session.session_index:04d}.json"
        # Le type du sceau n'est pas revérifié ici : L2 refuse déjà tout sceau dont `validation_type` diffère du type porté par l'identifiant de run
        # (`VALIDATION_TYPE_MISMATCH`), et la règle n'admet que des dossiers `..._walk_forward` (équivalence prouvée par lecture de L2 et par mutation).
        return ev.RunSeal.from_bytes(observation.content_bytes).validation_run_id == run_directory
    except ev.EvidenceRefused:
        return False


def _bind_v5(observation, context, findings: list, evidence: list, reasons: list) -> bool:
    """Relie UNE observation à sa règle. Les sources historiques suivent B3 à l'identique ; une anomalie de source (illisible, trop grand, nature fausse,
    hors table) suit aussi le chemin de B3 (raison + finding non résolu). Une source v5 SANS anomalie est reconnue mais NON vérifiée : finding `UNRESOLVED`
    (jamais `RESOLVED`) et raison d'incomplétude."""
    tag = observation.rule_tag
    if tag not in _RUN_TAGS or observation.anomaly is not None:
        return _b3._bind(observation, context, findings, evidence, reasons)
    source_id, location = _b3._source_id(observation), _b3._location(observation)
    if tag in _ORPHAN_TAGS:
        reasons.append(f"{REASON_RUN_ORPHAN}:{location}")
        findings.append(_b3._unresolved(source_id, SourceKind.UNKNOWN_SOURCE, UnresolvedCause.UNKNOWN_SOURCE_TYPE, None))
        return False
    if tag in _HASHED_TAGS or tag in _STRUCTURAL_RUN_TAGS:        # un répertoire n'a pas de `content_hash` (None) ; un fichier haché porte le SHA-256 de ses octets
        reasons.append(f"{REASON_RUN_OUTPUT_UNVERIFIED}:{location}")
        findings.append(_b3._unresolved(source_id, SourceKind.UNKNOWN_SOURCE, UnresolvedCause.WINDOW_UNKNOWN, observation.content_hash))
        return False
    if _evidence_conforms(observation):
        reasons.append(f"{REASON_RUN_EVIDENCE_UNVERIFIED}:{location}")
        findings.append(_b3._unresolved(source_id, SourceKind.UNKNOWN_SOURCE, UnresolvedCause.WINDOW_UNKNOWN, observation.content_hash))
    else:
        reasons.append(f"{_b3.REASON_INFORMATIVE_UNRESOLVED}:{location}")
        findings.append(_b3._unresolved(source_id, SourceKind.UNKNOWN_SOURCE, UnresolvedCause.INVALID_SCHEMA, observation.content_hash))
    return observation.value_parsed


def interpret_audit_roots_v5(roots: tuple, limits: ScanLimits, *, hash_limits: HashLimits, holdout_window_start_utc: str, holdout_window_end_utc: str,
                             hooks: Optional[ScanHooks] = None) -> SourceInterpretation:
    """Équivalent de `gate_v_exposure_interpreters.interpret_audit_roots` pour les tables v5 (activation EXPLICITE de v5). `hash_limits` est OBLIGATOIRE,
    sans valeur par défaut ; il n'est appliqué (donc épinglé par B5) qu'aux dispositions dont la table comporte des règles `HASHED_FILE`. Aucune observation
    n'est jamais reçue d'un appelant : seules celles que `scan_audit_roots` retourne font foi."""
    if type(hash_limits) is not HashLimits:
        raise TypeError("hash_limits doit être un HashLimits : aucun plafond haché par défaut.")
    window = normalize_window(holdout_window_start_utc, holdout_window_end_utc)
    if type(roots) is not tuple or any(type(item) is not LayoutRoot for item in roots):
        raise TypeError("roots doit être un tuple de LayoutRoot.")
    _b3._refuse_cross_layout_overlap(roots)
    scans, observations, reasons = [], [], []
    for layout in RootLayout:
        group = tuple(item.root for item in roots if item.layout is layout)
        if group:
            rules = source_rules_v5(layout)
            applied = hash_limits if any(rule.entry_class.is_hashed for rule in rules) else None
            scan = scan_audit_roots(group, rules, limits, hooks=hooks, hash_limits=applied)
            scans.append(_b3.InterpretedScan(layout, scan))
            observations.extend(scan.observations)
    root_names = {root.label: os.path.basename(root.path) for item in scans for root in item.scan.roots}
    context = _b3._Context(window, _b3._index_plans(observations, reasons), root_names, _b3._index_coverages(observations, reasons))
    findings, evidence, sourced = [], [], set()
    for observation in observations:
        if _bind_v5(observation, context, findings, evidence, reasons):
            sourced.add(observation.root_label)
    present = {(o.root_label, o.relative_path) for o in observations}
    _b3._check_anchors(observations, present, findings, reasons)
    _b3._check_root_anchors(scans, present, reasons)
    reasons.extend(f"{_b3.REASON_ROOT_WITHOUT_SOURCE}:{root.label}" for item in scans for root in item.scan.roots if root.label not in sourced)
    return SourceInterpretation(B3_V5_SEMANTICS_VERSION, window[0], window[1], tuple(scans),
                                tuple(sorted(findings, key=lambda f: f.source_id)), context.plans,
                                complete=not reasons, incomplete_reasons=tuple(sorted(set(reasons))),
                                non_oos_validations=_b3._non_oos_validations(observations),
                                exposure_evidence=tuple(sorted(evidence, key=lambda e: e.source_id)))
