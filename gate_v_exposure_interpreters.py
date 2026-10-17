"""
gate_v_exposure_interpreters.py — AF-V-07 Slice E3-B3 : interprètes de sources.

Contrat : ADR 0025 Décision 23 (23.3, 23.11 étape 1, 23.13, 23.27.1 à 23.27.3) ; design E3-B (AI_HANDOFF.md §44.1, §45) ;
préconditions B3 consignées par B2 (§47, docstring de `gate_v_exposure_scan.ExposureScan`). Version 2 : addendum 23.30 approuvé
par l'utilisateur (ADR 0025 §23.30) — fenêtre accessible au calcul et asymétrie des preuves (Q-6), identité d'un plan = identifiant +
empreinte recalculée (Q-7), absence de rapport avec W établie pour sortir de l'ensemble pertinent (Q-8).

Responsabilité de B3, et elle seule : posséder les tables FERMÉES de sources, appeler lui-même le scanner strict de B2, relier
chaque observation à sa règle par `rule_tag`, interpréter les contenus acceptés en `ExposureFinding` (E3-A) et rendre explicite tout
ce qui est incomplet, anormal ou non résolu. B3 n'assemble aucun `ExposureInventory` ni comptabilité (B4), ne persiste rien (B5),
ne lit aucune déclaration (B6), n'utilise ni le registre (E3-D), ni E2, ni le moteur, ni `dataset_split`, n'ouvre aucune donnée de
marché et ne classe rien (FRESH, RETROSPECTIVE, UNDETERMINED restent à E3-A).

Module placé à côté de `gate_v_exposure_sources.py` (B1) : la pureté de B1 (imports, absence d'état global) est verrouillée par ses
tests publiés, que B3 ne modifie pas.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from gate_v_exposure_scan import (
    AuditRoot,
    EntryClass,
    ExposureScan,
    ExposureScanRefusal,
    JsonKind,
    ScanHooks,
    ScanLimits,
    SegmentPattern,
    SourceAnomaly,
    SourceRule,
    StructuralFailure,
    scan_audit_roots,
)
from gate_v_final_holdout_claim import FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION, final_holdout_access_claim_from_record
from gate_v_exposure_sources import inclusive_window_to_half_open, normalize_window, overlap_verdict
from gate_v_final_holdout_protocol import (
    OverlapVerdict,
    SourceKind,
    SourceStatus,
    UnresolvedCause,
    build_exposure_finding,
    normalize_utc_instant,
)

B3_SEMANTICS_VERSION = "gate_v_exposure_interpreters_v2"


class RootLayout(str, Enum):
    """Disposition connue d'une racine d'audit : chacune a SA table fermée."""

    RESULTS = "RESULTS"              # répertoire `results/` d'un worktree (23.11 étape 1)
    CAMPAIGN_DIR = "CAMPAIGN_DIR"    # dossier `<gate_v>/campaigns/<campaign_id>/` ancré par son `plan.json`
    SPLIT_PLAN_DIR = "SPLIT_PLAN_DIR"  # répertoire d'un plan de split : `split_plan.json` + `holdout_access/` (23.11, 23.13)


@dataclass(frozen=True)
class LayoutRoot:
    layout: RootLayout
    root: AuditRoot

    def __post_init__(self) -> None:
        if type(self.layout) is not RootLayout:
            raise TypeError("layout doit être un RootLayout.")
        if type(self.root) is not AuditRoot:
            raise TypeError("root doit être un AuditRoot.")


# ── Tables fermées ───────────────────────────────────────────────────────────────────────────────────────────────
# Aucun joker : chaque fichier connu est nommé littéralement ou par un motif d'UN segment ; tout le reste est observé comme inconnu.
# Aucune règle INERT_DIRECTORY (l'ADR ne déclare aucun sous-arbre incapable de contenir une source) ; INERT_FILE = noms littéraux.

_JOB_DIR = SegmentPattern(r"job_[A-Za-z0-9_]+")
_ID_DIR = SegmentPattern(r"[A-Za-z0-9][A-Za-z0-9_.-]{3,127}")      # identifiant portable d'au moins 4 caractères
_EVENT_FILE = SegmentPattern(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.json")
# Fichiers d'un job réellement produits par `optimizer_process.py` / `job_store.py` (disposition constatée le 2026-10-16) : jamais
# ouverts. `data_manifest.json` n'en fait plus partie (B3 v2) : il est lu comme preuve d'établissement P2 (ADR 0025 23.30.1).
_JOB_INERT_FILES = ("archive.zip", "logs.txt", "meta.json", "metrics.json", "progress.json", "report.html", "tested.json",
                    "results.csv", "best_strategies.csv", "job_decisions.json", "job_notes.json", "stop.flag",
                    "research_run.json")
_EXPERIMENT_FILE = SegmentPattern(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.json")
# Données de marché et métadonnées d'un jeu de données : jamais ouvertes (§44.1).
_DATASET_INERT = (("raw", "ig_prices_raw.json"), ("raw", "manifest.json"), ("normalized", "ig_prices_normalized.csv"),
                  ("normalized", "manifest.json"))

TAG_JOB_DIRECTORY = "job.dir"
TAG_JOB_CONFIG = "job.config"
TAG_JOB_INERT = "job.inert"
TAG_JOB_MANIFEST = "job.manifest"
TAG_SPLITS = "splits.dir"
TAG_SPLIT_DIRECTORY = "split.dir"
TAG_SPLIT_PLAN = "split.plan"
TAG_SPLIT_EVENTS = "split.events"
TAG_SPLIT_EVENT = "split.event"
TAG_VALIDATIONS = "validations.dir"
TAG_VALIDATION_DIRECTORY = "validation.dir"
TAG_VALIDATION_RUN = "validation.run"
TAG_VALIDATION_INERT = "validation.inert"
TAG_EXPERIMENTS = "experiments.dir"
TAG_EXPERIMENT = "experiment"
TAG_DATASETS = "datasets.dir"
TAG_DATASET_DIRECTORY = "dataset.dir"
TAG_DATASET_PART = "dataset.part"
TAG_DATASET_INERT = "dataset.inert"

_RESULTS_RULES = (
    SourceRule((_JOB_DIR,), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_JOB_DIRECTORY),
    SourceRule((_JOB_DIR, "config_used.json"), EntryClass.EXPOSING_JSON, JsonKind.OBJECT, tag=TAG_JOB_CONFIG),
    SourceRule((_JOB_DIR, "data_manifest.json"), EntryClass.INFORMATIVE_JSON, JsonKind.OBJECT, tag=TAG_JOB_MANIFEST),
    *(SourceRule((_JOB_DIR, name), EntryClass.INERT_FILE, tag=TAG_JOB_INERT) for name in _JOB_INERT_FILES),
    SourceRule(("dataset_splits",), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_SPLITS),
    SourceRule(("dataset_splits", _ID_DIR), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_SPLIT_DIRECTORY),
    SourceRule(("dataset_splits", _ID_DIR, "split_plan.json"), EntryClass.INFORMATIVE_JSON, JsonKind.OBJECT, tag=TAG_SPLIT_PLAN),
    SourceRule(("dataset_splits", _ID_DIR, "holdout_access"), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_SPLIT_EVENTS),
    SourceRule(("dataset_splits", _ID_DIR, "holdout_access", _EVENT_FILE), EntryClass.EXPOSING_JSON, JsonKind.OBJECT,
               tag=TAG_SPLIT_EVENT),
    SourceRule(("validations",), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_VALIDATIONS),
    SourceRule(("validations", _ID_DIR), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_VALIDATION_DIRECTORY),
    SourceRule(("validations", _ID_DIR, "validation_run.json"), EntryClass.EXPOSING_JSON, JsonKind.OBJECT,
               tag=TAG_VALIDATION_RUN),
    SourceRule(("validations", _ID_DIR, "research_run.json"), EntryClass.INERT_FILE, tag=TAG_VALIDATION_INERT),
    SourceRule(("experiments",), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_EXPERIMENTS),
    SourceRule(("experiments", _EXPERIMENT_FILE), EntryClass.INFORMATIVE_JSON, JsonKind.OBJECT, tag=TAG_EXPERIMENT),
    SourceRule(("datasets",), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_DATASETS),
    SourceRule(("datasets", _ID_DIR), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_DATASET_DIRECTORY),
    SourceRule(("datasets", _ID_DIR, "research_run.json"), EntryClass.INERT_FILE, tag=TAG_DATASET_INERT),
    *(SourceRule(("datasets", _ID_DIR, part), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_DATASET_PART)
      for part in ("raw", "normalized")),
    *(SourceRule(("datasets", _ID_DIR, part, name), EntryClass.INERT_FILE, tag=TAG_DATASET_INERT) for part, name in _DATASET_INERT),
)

TAG_CAMPAIGN_PLAN = "campaign.plan"
TAG_CAMPAIGN_CLAIM = "campaign.claim"

# Dossier de campagne : seuls l'ancre et le Claim d'E2 (`final_holdout_access_claim.json`, Décision 9) sont interprétés ; tout autre
# fichier (manifeste, validations, walk-forward, `exposure/`) reste INCONNU donc UNRESOLVED tant que son interprète n'existe pas.
_CAMPAIGN_RULES = (
    SourceRule(("plan.json",), EntryClass.INFORMATIVE_JSON, JsonKind.OBJECT, tag=TAG_CAMPAIGN_PLAN),
    SourceRule(("final_holdout_access_claim.json",), EntryClass.EXPOSING_JSON, JsonKind.OBJECT, tag=TAG_CAMPAIGN_CLAIM),
)

# Répertoire d'un plan configuré comme racine d'audit (« répertoires d'événements des plans », 23.11 étape 1).
_SPLIT_PLAN_DIR_RULES = (
    SourceRule(("split_plan.json",), EntryClass.INFORMATIVE_JSON, JsonKind.OBJECT, tag=TAG_SPLIT_PLAN),
    SourceRule(("holdout_access",), EntryClass.STRUCTURAL_DIRECTORY, tag=TAG_SPLIT_EVENTS),
    SourceRule(("holdout_access", _EVENT_FILE), EntryClass.EXPOSING_JSON, JsonKind.OBJECT, tag=TAG_SPLIT_EVENT),
)

_TABLES = {RootLayout.RESULTS: _RESULTS_RULES, RootLayout.CAMPAIGN_DIR: _CAMPAIGN_RULES,
           RootLayout.SPLIT_PLAN_DIR: _SPLIT_PLAN_DIR_RULES}
# Fichier-ancre exigé à la RACINE d'une disposition (B2 n'observe jamais une absence).
_ROOT_ANCHORS = {RootLayout.CAMPAIGN_DIR: "plan.json", RootLayout.SPLIT_PLAN_DIR: "split_plan.json"}


def source_rules(layout: RootLayout) -> tuple:
    """Table fermée EXACTE appliquée par B3 à une disposition (exposée pour l'audit et les tests de fermeture)."""
    return _TABLES[layout]


# ── Résultat ─────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InterpretedScan:
    """Un scan de B2, épinglé tel quel : `rules_digest`, `limits`, `may_be_empty` par racine et `hooks_used`."""

    layout: RootLayout
    scan: ExposureScan


@dataclass(frozen=True)
class PlanIndexEntry:
    """Plan de split lu et validé : INFORMATIF (23.27.1), jamais un finding ; sert à résoudre les fenêtres des sources qui le citent."""

    source_id: str
    split_plan_id: str
    fingerprint: str              # SHA-256 du JSON canonique de l'enregistrement (formule de `dataset_split_plan_fingerprint`)
    dataset_snapshot_id: str
    final_holdout_start_utc: str
    final_holdout_end_utc: str
    content_hash: str


@dataclass(frozen=True)
class NonOosValidationRun:
    """Nature RÉELLE d'un `ValidationRun` non OOS lu (walk-forward, Monte-Carlo, stabilité ou type inconnu). Informatif : E3-A n'a
    aucun `SourceKind` pour ces exécutions, leur finding est `UNKNOWN_SOURCE` ; cette note évite de perdre leur type."""

    source_id: str
    validation_type: str
    content_hash: str


class EvidenceStatus(str, Enum):
    """État de preuve d'une source d'exécution (ADR 0025 23.30.1) : exposition ÉTABLIE (et par quelle preuve), absence ÉTABLIE
    (preuve d'exclusion liée à l'exécution ; aucune n'existe à ce jour), ou absence NON ÉTABLIE — jamais une absence d'exposition."""

    ESTABLISHED_BY_EXECUTION_WINDOW = "ESTABLISHED_BY_EXECUTION_WINDOW"    # P1 : `X ∩ W ≠ ∅`
    ESTABLISHED_BY_LOADED_COVERAGE = "ESTABLISHED_BY_LOADED_COVERAGE"      # P2 : couverture chargée d'un manifeste attribuable
    ABSENCE_ESTABLISHED = "ABSENCE_ESTABLISHED"
    ABSENCE_NOT_ESTABLISHED = "ABSENCE_NOT_ESTABLISHED"


@dataclass(frozen=True)
class ExposureEvidence:
    """Relevé des preuves d'exposition (23.30.1) : informatif, jamais un finding, jamais compté, hors `inventory_id`. Une source
    arrêtée à l'étape 1 (anomalie, schéma invalide) n'y figure pas : son finding porte déjà son anomalie."""

    source_id: str
    status: EvidenceStatus
    manifest_source_id: Optional[str] = None      # manifeste utilisé par P2, sinon None
    manifest_content_hash: Optional[str] = None

    def __post_init__(self) -> None:
        if type(self.source_id) is not str or not self.source_id:
            raise TypeError("source_id doit être une chaîne non vide.")
        if type(self.status) is not EvidenceStatus:
            raise TypeError("status doit être un EvidenceStatus.")
        by_coverage = self.status is EvidenceStatus.ESTABLISHED_BY_LOADED_COVERAGE
        manifest = (self.manifest_source_id, self.manifest_content_hash)
        if by_coverage != all(type(v) is str and v for v in manifest) or (not by_coverage and manifest != (None, None)):
            raise ValueError("Le manifeste est renseigné si et seulement si l'exposition est établie par la couverture chargée.")


@dataclass(frozen=True)
class _Outcome:
    """Résultat uniforme d'un interprète : un finding, au plus une entrée du relevé, et les raisons d'incomplétude relevées."""

    finding: object
    evidence: Optional[ExposureEvidence] = None
    reasons: tuple = ()


@dataclass(frozen=True)
class SourceInterpretation:
    semantics_version: str
    holdout_window_start_utc: str
    holdout_window_end_utc: str
    scans: tuple
    findings: tuple               # `ExposureFinding` triés par `source_id`
    plans: tuple                  # `PlanIndexEntry` triés par `source_id`
    complete: bool                # faux dès qu'une entrée n'est pas énumérée, résolue ou présente ; jamais vrai par défaut
    incomplete_reasons: tuple     # raisons triées « CODE:<label>/<chemin> » (ou « CODE:<label> » pour une racine)
    non_oos_validations: tuple    # `NonOosValidationRun` triés par `source_id` (informatif ; ni finding ni comptabilité)
    exposure_evidence: tuple      # `ExposureEvidence` triés par `source_id` (informatif ; ni finding ni comptabilité)

    def __post_init__(self) -> None:
        if type(self.complete) is not bool:
            raise TypeError("complete doit être un booléen.")
        for name in ("scans", "findings", "plans", "incomplete_reasons", "non_oos_validations", "exposure_evidence"):
            if type(getattr(self, name)) is not tuple:
                raise TypeError(f"{name} doit être un tuple.")
        if self.complete == bool(self.incomplete_reasons):
            raise ValueError("complete est vrai si et seulement si aucune raison d'incomplétude n'existe.")

    @property
    def hooks_used(self) -> bool:
        """Vrai si un scan a reçu des `ScanHooks` (outil de test) : aucune autorité de production, E3-J doit le refuser."""
        return any(item.scan.hooks_used for item in self.scans)


# ── Instants et fenêtres ─────────────────────────────────────────────────────────────────────────────────────────

def _unresolved(source_id: str, kind: SourceKind, cause: UnresolvedCause, content_hash: Optional[str]):
    return build_exposure_finding(source_id=source_id, source_kind=kind, status=SourceStatus.UNRESOLVED,
                                  overlap=OverlapVerdict.UNKNOWN, content_hash=content_hash, unresolved_cause=cause)


def _resolved(source_id: str, kind: SourceKind, content_hash: str, start_utc: str, end_utc: str, window: tuple,
              campaign_id: Optional[str] = None):
    return build_exposure_finding(
        source_id=source_id, source_kind=kind, status=SourceStatus.RESOLVED,
        overlap=overlap_verdict(start_utc, end_utc, window[0], window[1]), content_hash=content_hash,
        window_start_utc=start_utc, window_end_utc=end_utc, campaign_id=campaign_id,
    )


def _instant_cause(value) -> Optional[UnresolvedCause]:
    """None si `value` est un instant ISO-8601 avec fuseau ; sinon la cause : date civile ou instant naïf = fuseau inconnu
    (Paris ou UTC implicites ne sont jamais supposés), toute autre forme = schéma invalide."""
    if type(value) is not str:
        return UnresolvedCause.INVALID_SCHEMA
    try:
        normalize_utc_instant(value)
        return None
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return UnresolvedCause.INVALID_SCHEMA
    return UnresolvedCause.TIMEZONE_UNKNOWN if parsed.tzinfo is None else UnresolvedCause.INVALID_SCHEMA


def _utc(value: str) -> datetime:
    """Instant aware → datetime UTC (comparaison sur datetimes, jamais lexicale : idiome de B1)."""
    return datetime.fromisoformat(normalize_utc_instant(value)[:-1] + "+00:00")


def _bounds_cause(start, end) -> Optional[UnresolvedCause]:
    """None si les deux bornes sont des instants aware ; sinon la cause la plus grave (schéma invalide > fuseau inconnu)."""
    if start is None or end is None:
        return UnresolvedCause.WINDOW_UNKNOWN
    causes = {cause for cause in (_instant_cause(start), _instant_cause(end)) if cause is not None}
    if not causes:
        return None
    return UnresolvedCause.INVALID_SCHEMA if UnresolvedCause.INVALID_SCHEMA in causes else UnresolvedCause.TIMEZONE_UNKNOWN


def _execution_window(start, end, *, inclusive: bool) -> tuple:
    """`(cause, X)` : fenêtre d'exécution CONFIGURÉE `X`, ou None et la cause qui l'empêche. `inclusive` : source passant par le
    défaut inclusif du moteur (`[start, end]` → `[start, end + 1µs)`, B1) ; sinon `[start, end)` exacte (job ISO-T, `time_paris <
    end`). Fenêtre vide ou inversée : INVALID_SCHEMA ; fin inclusive maximale : non représentable, jamais tronquée (B1)."""
    cause = _bounds_cause(start, end)
    if cause is UnresolvedCause.TIMEZONE_UNKNOWN and _naive_inverted(start, end):
        return UnresolvedCause.INVALID_SCHEMA, None
    if cause is not None:
        return cause, None
    if inclusive:
        if _utc(end) < _utc(start):
            return UnresolvedCause.INVALID_SCHEMA, None
        try:
            return None, inclusive_window_to_half_open(start, end)
        except ValueError:
            return UnresolvedCause.WINDOW_UNKNOWN, None
    try:
        return None, normalize_window(start, end)
    except ValueError:
        return UnresolvedCause.INVALID_SCHEMA, None


def _naive_inverted(start, end) -> bool:
    """Deux bornes sans fuseau (date civile ou instant naïf) se comparent entre elles : une fin antérieure au début est un schéma
    invalide, même si aucune ne peut être placée en UTC."""
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except (TypeError, ValueError):
        return False
    return first.tzinfo is None and last.tzinfo is None and last < first


def _overlaps(start_utc: str, end_utc: str, window: tuple) -> bool:
    return overlap_verdict(start_utc, end_utc, window[0], window[1]) is OverlapVerdict.OVERLAPS


def _execution_verdict(source_id: str, kind: SourceKind, observation, window: tuple, start, end, *, inclusive: bool,
                       coverage: Optional[_LoadedCoverage] = None) -> _Outcome:
    """Verdict d'une source d'exécution (ADR 0025 23.30.1), dans l'ordre :
    1. schéma invalide → UNRESOLVED ; aucune preuve ne le neutralise ;
    2. P1 (`X ∩ W ≠ ∅`) ou P2 (couverture chargée attribuable recoupant `W`) → exposition ÉTABLIE ;
    3. preuve d'exclusion liée à l'exécution → absence établie : AUCUNE n'existe à ce jour (ni `X`, ni un manifeste n'excluent) ;
    4. sinon absence NON ÉTABLIE (UNRESOLVED), jamais NO_OVERLAP.
    Le relevé (`ExposureEvidence`) ne couvre que les étapes 2 à 4."""
    cause, execution = _execution_window(start, end, inclusive=inclusive)
    if cause is UnresolvedCause.INVALID_SCHEMA:
        return _Outcome(_unresolved(source_id, kind, cause, observation.content_hash))
    if execution is not None and _overlaps(*execution, window):
        return _Outcome(_resolved(source_id, kind, observation.content_hash, *execution, window),
                        ExposureEvidence(source_id, EvidenceStatus.ESTABLISHED_BY_EXECUTION_WINDOW))
    if coverage is not None and _overlaps(coverage.start_utc, coverage.end_utc, window):
        return _Outcome(_resolved(source_id, kind, observation.content_hash, coverage.start_utc, coverage.end_utc, window),
                        ExposureEvidence(source_id, EvidenceStatus.ESTABLISHED_BY_LOADED_COVERAGE, coverage.source_id,
                                         coverage.content_hash))
    final = UnresolvedCause.TIMEZONE_UNKNOWN if cause is UnresolvedCause.TIMEZONE_UNKNOWN else UnresolvedCause.WINDOW_UNKNOWN
    return _Outcome(_unresolved(source_id, kind, final, observation.content_hash),
                    ExposureEvidence(source_id, EvidenceStatus.ABSENCE_NOT_ESTABLISHED))


def _is_text(value) -> bool:
    return type(value) is str and bool(value.strip())


# ── Plans de split (informatifs) ─────────────────────────────────────────────────────────────────────────────────

_PLAN_KEYS = frozenset({"split_plan_id", "dataset_snapshot_id", "train", "final_holdout", "validation", "discovery_oos",
                        "created_at"})


def _half_open_boundary(value) -> Optional[tuple]:
    """Zone `{start, end}` d'un plan : déjà demi-ouverte et exacte (jamais convertie) ; None si invalide."""
    if type(value) is not dict or set(value) != {"start", "end"}:
        return None
    if _instant_cause(value["start"]) is not None or _instant_cause(value["end"]) is not None:
        return None
    try:
        return normalize_window(value["start"], value["end"])
    except ValueError:
        return None


def _plan_entry(source_id: str, observation) -> Optional[PlanIndexEntry]:
    record = observation.value
    if set(record) != _PLAN_KEYS or not all(_is_text(record[k]) for k in ("split_plan_id", "dataset_snapshot_id", "created_at")):
        return None
    final_holdout = _half_open_boundary(record["final_holdout"])
    if final_holdout is None or _half_open_boundary(record["train"]) is None:
        return None
    for optional in ("validation", "discovery_oos"):
        if record[optional] is not None and _half_open_boundary(record[optional]) is None:
            return None
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return PlanIndexEntry(source_id, record["split_plan_id"], hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                          record["dataset_snapshot_id"], final_holdout[0], final_holdout[1], observation.content_hash)


@dataclass(frozen=True)
class _Context:
    window: tuple
    plans: tuple
    root_names: dict      # label → nom du répertoire racine (ancre d'un dossier de campagne)
    coverages: dict       # (label, dossier de job) → `_LoadedCoverage` attribuable (P2)

    def _unique_window(self, designates) -> Optional[tuple]:
        windows = {(p.final_holdout_start_utc, p.final_holdout_end_utc) for p in self.plans if designates(p)}
        return windows.pop() if len(windows) == 1 else None

    def has_plan(self, split_plan_id: str) -> bool:
        return any(p.split_plan_id == split_plan_id for p in self.plans)

    def plan_window_by_key(self, split_plan_id: str, fingerprint: str) -> Optional[tuple]:
        """Fenêtre du plan désigné par un Claim : identifiant ET empreinte recalculée (23.30.2)."""
        return self._unique_window(lambda p: p.split_plan_id == split_plan_id and p.fingerprint == fingerprint)

    def plan_window_by_id(self, split_plan_id: str, dataset_snapshot_id: str) -> Optional[tuple]:
        """Fenêtre FINAL_HOLDOUT du plan désigné par un événement legacy, qui ne porte pas d'empreinte (23.30.2) : plans valides
        de même identifiant ET de même snapshot que l'événement. Les plans d'un autre snapshot sont des plans distincts (aucune
        concordance exigée) ; des plans désignés aux fenêtres divergentes, ou aucun plan désigné → None (plan non désignable)."""
        return self._unique_window(lambda p: p.split_plan_id == split_plan_id and p.dataset_snapshot_id == dataset_snapshot_id)


# ── Interprètes de sources exposantes ────────────────────────────────────────────────────────────────────────────

def _interpret_job(source_id: str, observation, context: _Context):
    """`config_used.json` : la fenêtre d'exécution CONFIGURÉE `X` vient de `opt_start_date` / `opt_end_date` (ISO-T aware :
    `[start, end)` exacte, `time_paris < opt_end_date` d'`optimizer.resolve_execution_window` ; forme civile : TIMEZONE_UNKNOWN).
    `X` établit une exposition (P1) mais n'en exclut aucune : le job charge tout son `data_file` (23.30.1). La couverture chargée
    du `data_manifest.json` attribuable du même dossier établit aussi (P2)."""
    config = observation.value
    return _execution_verdict(source_id, SourceKind.JOB_EXECUTION, observation, context.window, config.get("opt_start_date"),
                              config.get("opt_end_date"), inclusive=False,
                              coverage=context.coverages.get((observation.root_label, _directory(observation))))


_EVENT_REQUIRED = frozenset({"split_plan_id", "dataset_snapshot_id", "research_run_id", "reason", "locked_state", "accessed_at",
                             "event_id"})
_EVENT_OPTIONAL = frozenset({"validation_run_id"})


def _interpret_event(source_id: str, observation, context: _Context):
    """`HoldoutAccessEvent` LEGACY (`dataset_split`, 7 ou 8 champs) : consultation du FINAL_HOLDOUT du plan `split_plan_id`.
    Tout champ additionnel (événement étendu 23.13) reste INVALID_SCHEMA tant qu'E3-G n'a pas défini son schéma strict."""
    kind = SourceKind.HOLDOUT_ACCESS_EVENT
    event = observation.value
    keys = set(event)
    valid = (_EVENT_REQUIRED <= keys <= _EVENT_REQUIRED | _EVENT_OPTIONAL
             and all(_is_text(event[k]) for k in _EVENT_REQUIRED)
             and (event.get("validation_run_id") is None or _is_text(event["validation_run_id"])))
    if not valid:
        return _Outcome(_unresolved(source_id, kind, UnresolvedCause.INVALID_SCHEMA, observation.content_hash))
    window = context.plan_window_by_id(event["split_plan_id"], event["dataset_snapshot_id"])
    if window is None:
        return _Outcome(_unresolved(source_id, kind, UnresolvedCause.PLAN_UNRESOLVED, observation.content_hash))
    return _Outcome(_resolved(source_id, kind, observation.content_hash, window[0], window[1], context.window))


_VALIDATION_REQUIRED = frozenset({"validation_run_id", "research_run_id", "split_plan_id", "dataset_snapshot_id", "validation_type",
                                  "strategy_name", "strategy_params", "evidence", "status", "completed_at"})
_VALIDATION_OPTIONAL = frozenset({"specification"})   # absente des enregistrements AF-V-01 relus, présente depuis AF-V-06
_VALIDATION_OOS = "oos"
# Types enregistrés dont la fenêtre exposée N'EST PAS TRANCHÉE (Q-2, ADR 23.29.7) : jamais interprétés ici.
_VALIDATION_TYPES_WINDOW_OPEN = frozenset({"walk_forward", "monte_carlo", "parameter_stability"})


def _validation_type(record) -> Optional[str]:
    value = record.get("validation_type")
    return value if _is_text(value) else None


def _interpret_validation(source_id: str, observation, context: _Context):
    """`ValidationRun` : typé `VALIDATION_RUN_OOS` seulement si son contenu établit `validation_type == "oos"` (exécution
    inclusive sur `evidence.period_start`/`period_end`, moteur inclusif par défaut à AF-V-01). Tout autre cas a une nature que
    E3-A ne sait pas représenter : `UNKNOWN_SOURCE` (jamais RESOLVED) — WF/MC/PS = fenêtre inconnue (Q-2), type inconnu =
    version inconnue, type absent = schéma invalide. Leur nature réelle est consignée dans `non_oos_validations`."""
    record = observation.value
    validation_type = _validation_type(record)
    kind = SourceKind.VALIDATION_RUN_OOS if validation_type == _VALIDATION_OOS else SourceKind.UNKNOWN_SOURCE
    keys = set(record)
    if not _VALIDATION_REQUIRED <= keys <= _VALIDATION_REQUIRED | _VALIDATION_OPTIONAL or validation_type is None:
        return _Outcome(_unresolved(source_id, kind, UnresolvedCause.INVALID_SCHEMA, observation.content_hash))
    if validation_type in _VALIDATION_TYPES_WINDOW_OPEN:
        return _Outcome(_unresolved(source_id, kind, UnresolvedCause.WINDOW_UNKNOWN, observation.content_hash))
    if validation_type != _VALIDATION_OOS:
        return _Outcome(_unresolved(source_id, kind, UnresolvedCause.UNKNOWN_SCHEMA_VERSION, observation.content_hash))
    evidence = record["evidence"]
    if type(evidence) is not dict or "period_start" not in evidence or "period_end" not in evidence:
        return _Outcome(_unresolved(source_id, kind, UnresolvedCause.INVALID_SCHEMA, observation.content_hash))
    return _execution_verdict(source_id, kind, observation, context.window, evidence["period_start"], evidence["period_end"],
                              inclusive=True)


def _interpret_claim(source_id: str, observation, context: _Context):
    """Claim d'E2, relu par le parseur STRICT d'E1 (14 clés, hashes recalculés). Le Claim ne porte aucune fenêtre : la sienne est
    la fenêtre FINAL_HOLDOUT du plan désigné par `(split_plan_id, split_plan_fingerprint)` ; introuvable → WINDOW_UNKNOWN (23.27.2)."""
    kind = SourceKind.FINAL_HOLDOUT_CLAIM
    record = observation.value
    version = record.get("claim_semantics_version")
    if _is_text(version) and version != FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION:
        return _Outcome(_unresolved(source_id, kind, UnresolvedCause.UNKNOWN_SCHEMA_VERSION, observation.content_hash))
    try:
        claim = final_holdout_access_claim_from_record(record)
    except ValueError:
        return _Outcome(_unresolved(source_id, kind, UnresolvedCause.INVALID_SCHEMA, observation.content_hash))
    window = context.plan_window_by_key(claim.split_plan_id, claim.split_plan_fingerprint)
    if window is None:
        # Empreinte revendiquée incompatible avec un plan valide lu du même identifiant : incohérence explicite (23.30.2).
        reasons = (f"{REASON_PLAN_FINGERPRINT_MISMATCH}:{_location(observation)}",) if context.has_plan(claim.split_plan_id) else ()
        return _Outcome(_unresolved(source_id, kind, UnresolvedCause.WINDOW_UNKNOWN, observation.content_hash), reasons=reasons)
    return _Outcome(_resolved(source_id, kind, observation.content_hash, window[0], window[1], context.window, claim.campaign_id))


_INTERPRETERS = {TAG_JOB_CONFIG: _interpret_job, TAG_SPLIT_EVENT: _interpret_event, TAG_VALIDATION_RUN: _interpret_validation,
                 TAG_CAMPAIGN_CLAIM: _interpret_claim}
# Type d'une source exposante dont le CONTENU n'a pas pu être interprété (anomalie, ancre absente). Un `validation_run.json`
# illisible n'établit pas qu'il s'agit d'un OOS : sa nature reste inconnue.
_FALLBACK_KINDS = {TAG_JOB_CONFIG: SourceKind.JOB_EXECUTION, TAG_SPLIT_EVENT: SourceKind.HOLDOUT_ACCESS_EVENT,
                   TAG_VALIDATION_RUN: SourceKind.UNKNOWN_SOURCE, TAG_CAMPAIGN_CLAIM: SourceKind.FINAL_HOLDOUT_CLAIM}
_INFORMATIVE_TAGS = frozenset({TAG_SPLIT_PLAN, TAG_EXPERIMENT, TAG_CAMPAIGN_PLAN, TAG_JOB_MANIFEST})
_EXPERIMENT_KEYS = frozenset({"created_at", "experiment_id", "hypothesis"})   # `research_run.Experiment` (job_store)


def _informative_ok(observation, context: _Context) -> bool:
    """Contenu informatif accepté : un plan valide (indexé ailleurs), un enregistrement d'expérience exact, ou l'ancre d'un
    dossier de campagne dont le `campaign_id` est le nom du dossier. Un fichier déposé là n'est jamais cru sur parole."""
    if observation.rule_tag == TAG_CAMPAIGN_PLAN:
        record = observation.value
        return _is_text(record.get("campaign_id")) and record["campaign_id"] == context.root_names[observation.root_label]
    if observation.rule_tag == TAG_EXPERIMENT:
        record = observation.value
        return set(record) == _EXPERIMENT_KEYS and all(_is_text(record[k]) for k in ("created_at", "experiment_id"))
    return True

# ── Rattachement observation ↔ règle ─────────────────────────────────────────────────────────────────────────────

# Anomalie de SOURCE (B2) → cause de non-résolution (E3-A). Contenu non lisible strictement : UNREADABLE ; forme contraire à la
# règle : INVALID_SCHEMA ; entrée hors table : UNKNOWN_SOURCE_TYPE. Toutes donnent UNRESOLVED, jamais une absence de source.
_ANOMALY_CAUSES = {
    **dict.fromkeys((SourceAnomaly.INVALID_JSON, SourceAnomaly.DUPLICATE_KEY, SourceAnomaly.NON_FINITE, SourceAnomaly.BOM,
                     SourceAnomaly.NOT_UTF8, SourceAnomaly.LONE_SURROGATE, SourceAnomaly.DEPTH_EXCEEDED,
                     SourceAnomaly.TOO_LARGE, SourceAnomaly.UNREADABLE), UnresolvedCause.UNREADABLE),
    SourceAnomaly.UNEXPECTED_JSON_TYPE: UnresolvedCause.INVALID_SCHEMA,
    SourceAnomaly.KIND_MISMATCH: UnresolvedCause.INVALID_SCHEMA,
    **dict.fromkeys((SourceAnomaly.UNKNOWN_FILE, SourceAnomaly.UNKNOWN_DIRECTORY, SourceAnomaly.UNKNOWN_TEMP_FILE),
                    UnresolvedCause.UNKNOWN_SOURCE_TYPE),
}
_UNKNOWN_ENTRY_ANOMALIES = frozenset({SourceAnomaly.UNKNOWN_FILE, SourceAnomaly.UNKNOWN_DIRECTORY, SourceAnomaly.UNKNOWN_TEMP_FILE})

class IncompleteReason(str, Enum):
    """Code d'une raison d'incomplétude ; la raison complète est « CODE:<label>/<chemin> » (ou « CODE:<label> »)."""

    SOURCE_ANOMALY = "SOURCE_ANOMALY"                  # source reconnue, contenu ou nature non résolus
    UNKNOWN_ENTRY = "UNKNOWN_ENTRY"                    # entrée hors table (jamais ouverte ni descendue)
    INFORMATIVE_UNRESOLVED = "INFORMATIVE_UNRESOLVED"  # plan, expérience ou ancre illisible ou non conforme
    MISSING_REQUIRED = "MISSING_REQUIRED"              # fichier-ancre exigé absent
    ROOT_WITHOUT_SOURCE = "ROOT_WITHOUT_SOURCE"        # racine vide ou entièrement inerte
    PLAN_FINGERPRINT_MISMATCH = "PLAN_FINGERPRINT_MISMATCH"  # Claim : empreinte incompatible avec un plan lu du même id


REASON_SOURCE_ANOMALY = IncompleteReason.SOURCE_ANOMALY.value
REASON_UNKNOWN_ENTRY = IncompleteReason.UNKNOWN_ENTRY.value
REASON_INFORMATIVE_UNRESOLVED = IncompleteReason.INFORMATIVE_UNRESOLVED.value
REASON_MISSING_REQUIRED = IncompleteReason.MISSING_REQUIRED.value
REASON_ROOT_WITHOUT_SOURCE = IncompleteReason.ROOT_WITHOUT_SOURCE.value
REASON_PLAN_FINGERPRINT_MISMATCH = IncompleteReason.PLAN_FINGERPRINT_MISMATCH.value

# Ancres : un répertoire structurel reconnu EXIGE ce fichier enfant (B2 n'observe jamais une absence). Fichier manquant d'une
# source exposante → finding UNRESOLVED de ce type à l'emplacement attendu (« dossier d'ancrage sans fichier-ancre », §44.1) ;
# fichier informatif manquant → raison d'incomplétude seulement (un plan n'est jamais un finding).
_ANCHORS = {
    TAG_JOB_DIRECTORY: ("config_used.json", TAG_JOB_CONFIG),
    TAG_SPLIT_DIRECTORY: ("split_plan.json", TAG_SPLIT_PLAN),
    TAG_VALIDATION_DIRECTORY: ("validation_run.json", TAG_VALIDATION_RUN),
}


def _source_id(observation) -> str:
    return f"{observation.rule_tag or 'unknown'}:{observation.root_label}/{observation.relative_path}"


def _location(observation) -> str:
    return f"{observation.root_label}/{observation.relative_path}"


@dataclass(frozen=True)
class _LoadedCoverage:
    """P2 : instants d'ouverture des barres chargées par un job, `[period_start, period_end + 1µs)` (23.30.1)."""

    source_id: str
    content_hash: str
    start_utc: str
    end_utc: str


# `BacktestManifest` (market_data/backtest_manifest.py) : 18 champs, types exacts.
_MANIFEST_TEXT = frozenset({"provider", "instrument", "provider_symbol", "source_timeframe", "timezone", "session",
                            "partial_bar_handling", "strategy_version", "engine_version", "launched_at"})
_MANIFEST_OPTIONAL_TEXT = frozenset({"asset_type", "snapshot_id", "content_hash", "period_start", "period_end",
                                     "derived_timeframe", "git_commit"})
_MANIFEST_KEYS = _MANIFEST_TEXT | _MANIFEST_OPTIONAL_TEXT | {"resample_options"}
_HEX_DIGITS = frozenset("0123456789abcdef")


def _is_sha256_hex(value) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _HEX_DIGITS


def _directory(observation) -> str:
    return observation.relative_path.rsplit("/", 1)[0]


def _instrument_of(data_file) -> Optional[str]:
    """Dérivation de `job_store.write_data_manifest` (`splitext(basename(data_file))[0]`), indépendante du système de
    l'auditeur : le nom de base se coupe sur la barre oblique ET la barre oblique inverse ; l'extension est retirée au dernier
    point, sauf pour un nom fait de points en tête (règle de `splitext`). None si `data_file` n'est pas un texte non vide ou ne
    donne aucun nom."""
    if not _is_text(data_file):
        return None
    name = data_file.replace("\\", "/").rsplit("/", 1)[-1]
    if len(name) >= 2 and name[1] == ":" and name[0].isalpha():      # lecteur relatif `C:fichier` (`ntpath.basename`)
        name = name[2:]
    dot = name.rfind(".")
    stem = name[:dot] if dot > 0 and name[:dot].lstrip(".") else name
    return stem or None


def _coverage(source_id: str, observation, config) -> tuple:
    """`(couverture ou None, anomalie)` d'un manifeste lu sans anomalie de scan. Bornes nulles (chemin legacy prévu par
    `write_data_manifest`) : pas de preuve, pas d'anomalie. Schéma inexact, bornes naïves ou inversées, fin non représentable,
    `data_file` absent ou `instrument` différent : anomalie de la preuve (jamais une preuve)."""
    record = observation.value
    if (set(record) != _MANIFEST_KEYS or any(type(record[k]) is not str for k in _MANIFEST_TEXT)
            or any(record[k] is not None and type(record[k]) is not str for k in _MANIFEST_OPTIONAL_TEXT)
            or type(record["resample_options"]) is not dict):
        return None, True
    nulls = [record[k] is None for k in ("period_start", "period_end", "content_hash")]
    if all(nulls):                          # chemin legacy : `write_data_manifest` met les trois à None ensemble
        return None, False
    if any(nulls) or not _is_sha256_hex(record["content_hash"]):
        return None, True
    start, end = record["period_start"], record["period_end"]
    if _instant_cause(start) is not None or _instant_cause(end) is not None or _utc(end) < _utc(start):
        return None, True
    try:
        start_utc, end_utc = inclusive_window_to_half_open(start, end)
    except ValueError:
        return None, True
    if config is None or _instrument_of(config.get("data_file")) != record["instrument"]:
        return None, True
    return _LoadedCoverage(source_id, observation.content_hash, start_utc, end_utc), False


def _index_coverages(observations: list, reasons: list) -> dict:
    """Couvertures chargées attribuables, par `(label, dossier de job)`. Le `config_used.json` du même dossier doit être lu sans
    anomalie pour attribuer le manifeste ; sinon le manifeste n'est pas attribuable."""
    configs = {(o.root_label, _directory(o)): o.value for o in observations
               if o.rule_tag == TAG_JOB_CONFIG and o.anomaly is None and o.value_parsed}
    coverages = {}
    for observation in observations:
        if observation.rule_tag != TAG_JOB_MANIFEST or observation.anomaly is not None or not observation.value_parsed:
            continue
        key = (observation.root_label, _directory(observation))
        coverage, anomalous = _coverage(_source_id(observation), observation, configs.get(key))
        if anomalous:
            reasons.append(f"{REASON_INFORMATIVE_UNRESOLVED}:{_location(observation)}")
        elif coverage is not None:
            coverages[key] = coverage
    return coverages


def _index_plans(observations: list, reasons: list) -> tuple:
    plans = []
    for observation in observations:
        if observation.rule_tag != TAG_SPLIT_PLAN or observation.anomaly is not None:
            continue
        entry = _plan_entry(_source_id(observation), observation)
        if entry is None:
            reasons.append(f"{REASON_INFORMATIVE_UNRESOLVED}:{_location(observation)}")
        else:
            plans.append(entry)
    return tuple(sorted(plans, key=lambda p: p.source_id))


def _bind(observation, context: _Context, findings: list, evidence: list, reasons: list) -> bool:
    """Relie UNE observation à sa règle par `rule_tag` ; rend vrai si elle atteste une source lue sans anomalie."""
    tag = observation.rule_tag
    if observation.anomaly is not None:
        unknown = observation.anomaly in _UNKNOWN_ENTRY_ANOMALIES
        if tag in _INFORMATIVE_TAGS:
            reasons.append(f"{REASON_INFORMATIVE_UNRESOLVED}:{_location(observation)}")
            return False
        reasons.append(f"{REASON_UNKNOWN_ENTRY if unknown else REASON_SOURCE_ANOMALY}:{_location(observation)}")
        kind = _FALLBACK_KINDS.get(tag, SourceKind.UNKNOWN_SOURCE)
        findings.append(_unresolved(_source_id(observation), kind, _ANOMALY_CAUSES[observation.anomaly],
                                    observation.content_hash))
        return False
    if tag in _INFORMATIVE_TAGS and observation.value_parsed and not _informative_ok(observation, context):
        reasons.append(f"{REASON_INFORMATIVE_UNRESOLVED}:{_location(observation)}")
        return False
    interpreter = _INTERPRETERS.get(tag)
    if interpreter is not None:
        outcome = interpreter(_source_id(observation), observation, context)
        findings.append(outcome.finding)
        if outcome.evidence is not None:
            evidence.append(outcome.evidence)
        reasons.extend(outcome.reasons)
    return observation.value_parsed


def _check_anchors(observations: list, present: set, findings: list, reasons: list) -> None:
    for observation in observations:
        anchor = _ANCHORS.get(observation.rule_tag)
        if anchor is None or observation.anomaly is not None:
            continue
        name, child_tag = anchor
        path = f"{observation.relative_path}/{name}"
        if (observation.root_label, path) in present:
            continue
        location = f"{observation.root_label}/{path}"
        reasons.append(f"{REASON_MISSING_REQUIRED}:{location}")
        kind = _FALLBACK_KINDS.get(child_tag)
        if kind is not None:
            findings.append(_unresolved(f"{child_tag}:{location}", kind, UnresolvedCause.INVALID_SCHEMA, None))


def _refuse_cross_layout_overlap(roots: tuple) -> None:
    """B2 refuse les racines imbriquées ou en double À L'INTÉRIEUR d'un scan ; B3 scanne une table par disposition, donc
    contrôle lui-même labels et chemins entre dispositions (sinon une même source serait inventoriée deux fois)."""
    labels = [item.root.label for item in roots]
    if len(set(labels)) != len(labels):
        raise ExposureScanRefusal(StructuralFailure.DUPLICATE_ROOT_LABEL, "label de racine en double entre dispositions")
    paths = [os.path.normcase(os.path.realpath(item.root.path)) for item in roots]
    for i, first in enumerate(paths):
        for second in paths[i + 1:]:
            if os.path.splitdrive(first)[0] != os.path.splitdrive(second)[0]:
                continue             # deux lecteurs : disjoints (`commonpath` lèverait une ValueError non typée)
            if os.path.commonpath([first, second]) in (first, second):
                raise ExposureScanRefusal(StructuralFailure.ROOT_OVERLAP, "racines imbriquées ou identiques entre dispositions")


def _non_oos_validations(observations: list) -> tuple:
    notes = []
    for o in observations:
        if o.rule_tag != TAG_VALIDATION_RUN or o.anomaly is not None or not o.value_parsed:
            continue
        validation_type = _validation_type(o.value)
        if validation_type not in (None, _VALIDATION_OOS):
            notes.append(NonOosValidationRun(_source_id(o), validation_type, o.content_hash))
    return tuple(sorted(notes, key=lambda note: note.source_id))


def _check_root_anchors(scans: list, present: set, reasons: list) -> None:
    for item in scans:
        name = _ROOT_ANCHORS.get(item.layout)
        if name is None:
            continue
        for root in item.scan.roots:
            if (root.label, name) not in present:
                reasons.append(f"{REASON_MISSING_REQUIRED}:{root.label}/{name}")


def interpret_audit_roots(roots: tuple, limits: ScanLimits, *, holdout_window_start_utc: str, holdout_window_end_utc: str,
                          hooks: Optional[ScanHooks] = None) -> SourceInterpretation:
    """Scanne les racines (B2, tables de B3), relie chaque observation à sa règle et l'interprète. Aucune observation n'est
    jamais reçue d'un appelant : seules celles que `scan_audit_roots` retourne font foi."""
    window = normalize_window(holdout_window_start_utc, holdout_window_end_utc)
    if type(roots) is not tuple or any(type(item) is not LayoutRoot for item in roots):
        raise TypeError("roots doit être un tuple de LayoutRoot.")
    _refuse_cross_layout_overlap(roots)
    scans, observations, reasons = [], [], []
    for layout in RootLayout:
        group = tuple(item.root for item in roots if item.layout is layout)
        if group:
            scan = scan_audit_roots(group, source_rules(layout), limits, hooks=hooks)
            scans.append(InterpretedScan(layout, scan))
            observations.extend(scan.observations)
    root_names = {root.label: os.path.basename(root.path) for item in scans for root in item.scan.roots}
    context = _Context(window, _index_plans(observations, reasons), root_names, _index_coverages(observations, reasons))
    findings, evidence, sourced = [], [], set()
    for observation in observations:
        if _bind(observation, context, findings, evidence, reasons):
            sourced.add(observation.root_label)
    present = {(o.root_label, o.relative_path) for o in observations}
    _check_anchors(observations, present, findings, reasons)
    _check_root_anchors(scans, present, reasons)
    # Une racine vide ou entièrement inerte ne prouve rien : jamais « complète » (précondition B3 n° 2).
    reasons.extend(f"{REASON_ROOT_WITHOUT_SOURCE}:{root.label}"
                   for item in scans for root in item.scan.roots if root.label not in sourced)
    return SourceInterpretation(B3_SEMANTICS_VERSION, window[0], window[1], tuple(scans),
                                tuple(sorted(findings, key=lambda f: f.source_id)), context.plans,
                                complete=not reasons, incomplete_reasons=tuple(sorted(set(reasons))),
                                non_oos_validations=_non_oos_validations(observations),
                                exposure_evidence=tuple(sorted(evidence, key=lambda e: e.source_id)))
