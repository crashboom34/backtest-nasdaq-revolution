"""
gate_v_exposure_store.py — AF-V-07 Slice E3-B5 : persistance et relecture stricte du A0 (inventaire d'exposition).

Contrat normatif : ADR 0025 Décision 23, 23.11 étape 1, 23.13 (chemin et version), 23.27.3 (trois identités), 23.29.4 (sérialisation,
lectures strictes), 23.29.5 (provenance des compteurs), 23.30.1 (relevé des preuves) ; design E3-B (AI_HANDOFF.md §44.1, §45, §52, §53).

Fichier : `<campaign_dir>/exposure/inventory_<inventory_content_hash>.json`, version `gate_v_exposure_inventory_v1`. Plusieurs A0 de
même `inventory_id` coexistent (comptabilité, provenance ou `created_at` différents). Jamais d'écrasement ni de suppression.

Trois identités distinctes, aucune ne remplace l'autre :
- `inventory_id` : identité SCIENTIFIQUE (E3-A) ; ni comptabilité, ni provenance, ni étage, ni horodatage ;
- `inventory_content_digest` : `inventory_id` + les six compteurs (E3-A), sans provenance ;
- `inventory_content_hash` : SHA-256 du JSON canonique compact (Décision 20.3) de TOUT le contenu persisté sauf cette clé, `created_at`
  compris. La provenance des compteurs, le relevé des preuves, les épinglages de scan et le contexte propre y sont donc couverts, sans
  jamais entrer dans une formule d'E3-A.

Les `resolved_path` des pins de scan sont des données d'AUDIT LOCAL (absolues, propres à la machine) : elles sont couvertes par
`inventory_content_hash`, qui est donc l'identité d'un FICHIER sur une machine, jamais une identité portable. Les identités scientifiques
et portables sont `inventory_id`, `inventory_content_digest`, `static_sources_digest` et `overlap_projection_hash`. Le relevé des preuves
et les notes non OOS sont contrôlés à la relecture contre les findings auxquels ils se rattachent (`_check_audit_coherence`), sans relire
aucune source : ils ne créent aucun finding et ne transforment jamais une absence non établie en absence établie.

Représentation persistée NORMATIVE (distincte de la préimage du hash) : `json.dumps(record, sort_keys=True, ensure_ascii=False,
indent=2, allow_nan=False) + "\\n"`, UTF-8 sans BOM, fins de ligne LF, sans flottant. `save_exclusive` ne trie pas les clés et n'interdit pas
les valeurs non finies : B5 lui passe un `dict` déjà trié récursivement dont la sérialisation est vérifiée octet pour octet.

Versions de règles (ADR 0025 23.31.6) : l'A0 enregistre les versions appliquées et le `rules_digest` de chaque table scannée. La relecture
exige des versions CONNUES et des digests égaux à ceux de la version de B3 enregistrée (`B3_RULES_DIGESTS`). Un A0 d'une version antérieure
connue (B3 v2) est une LECTURE HISTORIQUE intègre (`rules_versions.is_current()` faux), jamais une requalification avec les règles courantes
(recalcul par E3-J) ; aucun artefact n'est réécrit.

Le module reste sans horloge : `created_at` est INJECTÉ. Les garanties de durabilité sont celles de `save_exclusive(durable=True)` :
sous Windows le `fsync` de répertoire n'est pas démontrable depuis Python (journal NTFS) ; les garanties POSIX exigées par le mode
`REAL` (désactivé et non qualifié) ne sont PAS établies par ce module. La création de `exposure/` (`os.mkdir`) n'est jamais synchronisée
dans `campaign_dir` : après un crash, le fichier peut être durable alors que son répertoire parent a disparu.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from atomic_json_store import ExclusiveCreationIncompleteError, save_exclusive
from gate_v_exposure_interpreters import (
    B3_RULES_DIGESTS,
    B3_SEMANTICS_VERSION,
    KNOWN_B3_VERSIONS,
    EvidenceStatus,
    ExposureEvidence,
    NonOosValidationRun,
    PlanIndexEntry,
    RootLayout,
)
from gate_v_exposure_inventory import (
    B4_SEMANTICS_VERSION,
    CounterProvenance,
    ExposureInventoryAssembly,
    TrialAccountingProvenance,
)
from gate_v_exposure_scan import ScanLimits, StrictJsonError, parse_strict_json
from gate_v_exposure_sources import normalize_window
from gate_v_final_holdout_protocol import (
    EXPOSURE_CLASSIFICATION_RULES_VERSION,
    EXPOSURE_INVENTORY_SEMANTICS_VERSION,
    ExposureFinding,
    ExposureInventory,
    OverlapVerdict,
    OwnCampaignContext,
    OwnRecordStage,
    SourceKind,
    SourceStatus,
    TrialAccounting,
    UnresolvedCause,
    compute_exposure_inventory_id,
    compute_inventory_content_digest,
    compute_overlap_projection_hash,
    compute_static_sources_digest,
    normalize_utc_instant,
)

A0_RECORD_KEYS = (
    "version", "created_at", "campaign_id", "own_record_stage", "window_start_utc", "window_end_utc", "complete", "scanned_roots",
    "findings", "trial_accounting", "trial_accounting_provenance", "incomplete_reasons", "inventory_id", "inventory_content_digest",
    "static_sources_digest", "overlap_projection_hash", "registry", "derived_root_labels", "rules_versions", "scan_pins", "plans",
    "non_oos_validations", "exposure_evidence", "inventory_content_hash",
)
_COUNTER_NAMES = ("research_runs", "strategies", "campaigns", "abandoned_reservations", "failed_ingestion_attempts", "void_commitments")
_LIMIT_NAMES = ("max_roots", "max_entries", "max_depth", "max_json_bytes", "max_total_read_bytes", "max_json_depth",
                "max_name_length", "max_path_length", "max_attempts")


class StoreFailure(str, Enum):
    """Cause typée d'un refus de lecture ou d'écriture : l'appelant distingue absence, corruption et refus de structure."""

    ABSENT = "ABSENT"
    NOT_REGULAR_FILE = "NOT_REGULAR_FILE"
    LINK_OR_REPARSE_POINT = "LINK_OR_REPARSE_POINT"
    TOO_LARGE = "TOO_LARGE"
    UNREADABLE = "UNREADABLE"
    UNSTABLE = "UNSTABLE"
    NOT_JSON = "NOT_JSON"
    SCHEMA = "SCHEMA"
    UNKNOWN_VERSION = "UNKNOWN_VERSION"
    NAME_MISMATCH = "NAME_MISMATCH"
    HASH_MISMATCH = "HASH_MISMATCH"
    NOT_FIXED_POINT = "NOT_FIXED_POINT"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    NAME_CONSUMED = "NAME_CONSUMED"
    INCOMPLETE_WRITE = "INCOMPLETE_WRITE"
    BAD_DIRECTORY = "BAD_DIRECTORY"
    CAMPAIGN_MISMATCH = "CAMPAIGN_MISMATCH"              # déclaration d'une autre campagne que celle attendue (ADR 0025 23.31.1)
    RULES_DIGEST_MISMATCH = "RULES_DIGEST_MISMATCH"      # `rules_digest` épinglé ≠ table de la version de B3 enregistrée (23.31.6)


class ExposureStoreError(ValueError):
    """Refus de B5. Un A0 corrompu ou incohérent n'est JAMAIS transformé en inventaire valide."""

    def __init__(self, failure: StoreFailure, detail: str) -> None:
        super().__init__(f"{failure.value} : {detail}")
        self.failure = failure
        self.detail = detail


# ── Canonicalisation et sérialisation (23.29.4) ──────────────────────────────────────────────────────────────────────

def _sorted_deep(value):
    """Copie dont TOUS les dictionnaires imbriqués ont leurs clés triées (octets identiques à `sort_keys=True`)."""
    if isinstance(value, dict):
        return {key: _sorted_deep(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_sorted_deep(item) for item in value]
    return value


def _canonical_json(record: object) -> str:
    """Préimage du hash (Décision 20.3, duplication volontaire) : clés triées, séparateurs compacts, UTF-8 non échappé, NaN refusé."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def compute_inventory_content_hash(record: dict) -> str:
    """SHA-256 du JSON canonique de TOUT l'enregistrement sauf la clé `inventory_content_hash` (`created_at` inclus)."""
    if type(record) is not dict:
        raise TypeError("record doit être un dict.")
    body = {key: value for key, value in record.items() if key != "inventory_content_hash"}
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def serialize_exposure_inventory_record(record: dict) -> bytes:
    """Représentation persistée normative (23.29.4) : tri récursif, `indent=2`, `allow_nan=False`, LF final, UTF-8 sans BOM."""
    if type(record) is not dict:
        raise TypeError("record doit être un dict.")
    text = json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    return text.encode("utf-8")


# ── Construction de l'enregistrement ─────────────────────────────────────────────────────────────────────────────────

def _normalized_created_at(created_at: object) -> str:
    if type(created_at) is not str:
        raise TypeError("created_at doit être un str (instant ISO-8601 avec fuseau explicite, injecté).")
    return normalize_utc_instant(created_at)


def _finding_record(finding) -> dict:
    return {
        "source_id": finding.source_id,
        "source_kind": finding.source_kind.value,
        "status": finding.status.value,
        "overlap": finding.overlap.value,
        "content_hash": finding.content_hash,
        "window_start_utc": finding.window_start_utc,
        "window_end_utc": finding.window_end_utc,
        "snapshot_id": finding.snapshot_id,
        "campaign_id": finding.campaign_id,
        "unresolved_cause": None if finding.unresolved_cause is None else finding.unresolved_cause.value,
    }


def _scan_pins(interpretation) -> list:
    pins = []
    for item in sorted(interpretation.scans, key=lambda scanned: scanned.layout.value):
        scan = item.scan
        pins.append({
            "layout": item.layout.value,
            "rules_digest": scan.rules_digest,
            "limits": {name: getattr(scan.limits, name) for name in _LIMIT_NAMES},
            "hooks_used": scan.hooks_used,
            "roots": [{"label": root.label, "resolved_path": root.path, "may_be_empty": root.may_be_empty}
                      for root in sorted(scan.roots, key=lambda scanned_root: scanned_root.label)],
        })
    return pins


def build_exposure_inventory_record(assembly: ExposureInventoryAssembly, *, created_at: str) -> dict:
    """Enregistrement persisté du A0 (clés = `A0_RECORD_KEYS`), `inventory_content_hash` calculé. Pur : aucune E/S, aucune horloge."""
    if type(assembly) is not ExposureInventoryAssembly:
        raise TypeError("assembly doit être un ExposureInventoryAssembly.")
    if assembly.hooks_used:
        raise ValueError("Un assemblage issu d'un scan avec ScanHooks (outil de test) n'a aucune autorité : il n'est jamais persisté.")
    created = _normalized_created_at(created_at)
    inventory, context, interpretation = assembly.inventory, assembly.own_context, assembly.interpretation
    provenance = assembly.accounting_provenance
    record = {
        "version": EXPOSURE_INVENTORY_SEMANTICS_VERSION,
        "created_at": created,
        "campaign_id": context.current_campaign_id,
        "own_record_stage": context.own_record_stage.value,
        "window_start_utc": inventory.window_start_utc,
        "window_end_utc": inventory.window_end_utc,
        "complete": inventory.complete,
        "scanned_roots": list(inventory.scanned_roots),
        "findings": [_finding_record(finding) for finding in inventory.findings],
        "trial_accounting": {name: getattr(inventory.trial_accounting, name) for name in _COUNTER_NAMES},
        "trial_accounting_provenance": {**{name: getattr(provenance, name).value for name in _COUNTER_NAMES},
                                        "reasons": list(provenance.reasons)},
        "incomplete_reasons": list(assembly.incomplete_reasons),
        "inventory_id": assembly.inventory_id,
        "inventory_content_digest": assembly.inventory_content_digest,
        "static_sources_digest": compute_static_sources_digest(inventory, context),
        "overlap_projection_hash": compute_overlap_projection_hash(inventory, context),
        "registry": {"registry_id": assembly.registry_id, "chain_head": assembly.registry_chain_head},
        "derived_root_labels": list(assembly.derived_root_labels),
        "rules_versions": {
            "e3a_inventory": EXPOSURE_INVENTORY_SEMANTICS_VERSION,
            "e3a_classification": EXPOSURE_CLASSIFICATION_RULES_VERSION,
            "b3_interpreters": interpretation.semantics_version,
            "b4_assembly": assembly.semantics_version,
        },
        "scan_pins": _scan_pins(interpretation),
        "plans": [{"source_id": p.source_id, "split_plan_id": p.split_plan_id, "fingerprint": p.fingerprint,
                   "dataset_snapshot_id": p.dataset_snapshot_id, "final_holdout_start_utc": p.final_holdout_start_utc,
                   "final_holdout_end_utc": p.final_holdout_end_utc, "content_hash": p.content_hash}
                  for p in interpretation.plans],
        "non_oos_validations": [{"source_id": n.source_id, "validation_type": n.validation_type, "content_hash": n.content_hash}
                                for n in interpretation.non_oos_validations],
        "exposure_evidence": [{"source_id": e.source_id, "status": e.status.value, "manifest_source_id": e.manifest_source_id,
                               "manifest_content_hash": e.manifest_content_hash}
                              for e in interpretation.exposure_evidence],
    }
    record = _sorted_deep(record)
    record["inventory_content_hash"] = compute_inventory_content_hash(record)
    return _sorted_deep(record)


# ── Système de fichiers : lecture stricte d'un fichier régulier (partagée avec B6) ───────────────────────────────────

# Plafonds OPÉRATIONNELS PROVISOIRES, NON NORMATIFS (ADR 0025 23.31.5) : gardes de ressources pour les fixtures SYNTHETIC, pas des règles de
# l'ADR ni la « limite mémoire du chargeur » de 23.24. NON qualifiés pour REAL : B5/B6 n'ont aucun mode REAL ; E3-J devra fournir les
# valeurs de 23.24, dont l'absence refuse REAL (aucun défaut inventé n'est jamais une valeur REAL).
OPERATIONAL_LIMITS_QUALIFIED_FOR_REAL = False
MAX_A0_BYTES = 16 * 1024 * 1024        # taille maximale d'un fichier relu (refus avant lecture) ; défaut de `max_bytes`
MAX_JSON_DEPTH = 32                    # profondeur JSON maximale
_READ_CHUNK = 65536
_READ_FLAGS = (os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
               | getattr(os, "O_NONBLOCK", 0))          # POSIX : un FIFO substitué entre `lstat` et `open` ne bloque jamais
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_A0_NAME_RE = re.compile(r"inventory_([0-9a-f]{64})\.json")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def _is_link(info) -> bool:
    """Lien symbolique, jonction ou point d'analyse : jamais suivi."""
    return stat.S_ISLNK(info.st_mode) or bool((getattr(info, "st_file_attributes", 0) or 0) & _REPARSE_POINT)


def _identity(info) -> tuple:
    return (info.st_ino, info.st_dev, info.st_size, info.st_mtime_ns)


def lstat_directory(path, what: str) -> None:
    """La cible existe, est un VRAI répertoire (ni lien, ni jonction, ni fichier) ; sinon `ExposureStoreError`."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise ExposureStoreError(StoreFailure.BAD_DIRECTORY, f"{what} absent") from None
    except OSError as error:
        raise ExposureStoreError(StoreFailure.BAD_DIRECTORY, f"{what} illisible : {error}") from None
    if _is_link(info):
        raise ExposureStoreError(StoreFailure.LINK_OR_REPARSE_POINT, f"{what} est un lien ou un point d'analyse")
    if not stat.S_ISDIR(info.st_mode):
        raise ExposureStoreError(StoreFailure.BAD_DIRECTORY, f"{what} n'est pas un répertoire")


def read_strict_file(path, *, max_bytes: int = MAX_A0_BYTES) -> bytes:
    """Lit les octets d'un fichier RÉGULIER, sans jamais suivre un lien : absent, non régulier, lien, trop gros, illisible ou instable
    (inode, taille ou mtime changés pendant la lecture) donnent chacun une cause typée. Le répertoire parent doit être un vrai répertoire."""
    target = Path(path)
    try:
        info = os.lstat(target)
    except FileNotFoundError:
        raise ExposureStoreError(StoreFailure.ABSENT, f"{target.name} est absent") from None
    except OSError as error:
        raise ExposureStoreError(StoreFailure.UNREADABLE, f"{target.name} : {error}") from None
    if _is_link(info):
        raise ExposureStoreError(StoreFailure.LINK_OR_REPARSE_POINT, f"{target.name} est un lien ou un point d'analyse")
    if not stat.S_ISREG(info.st_mode):
        raise ExposureStoreError(StoreFailure.NOT_REGULAR_FILE, f"{target.name} n'est pas un fichier régulier")
    lstat_directory(target.parent, "répertoire parent")
    if info.st_size > max_bytes:
        raise ExposureStoreError(StoreFailure.TOO_LARGE, f"{target.name} : {info.st_size} octets > {max_bytes}")
    try:
        descriptor = os.open(target, _READ_FLAGS)
    except OSError as error:
        raise ExposureStoreError(StoreFailure.UNREADABLE, f"{target.name} : {error}") from None
    try:
        opened = os.fstat(descriptor)
        chunks, total = [], 0
        while total <= max_bytes:
            chunk = os.read(descriptor, min(_READ_CHUNK, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after_read = os.fstat(descriptor)
    except OSError as error:
        raise ExposureStoreError(StoreFailure.UNREADABLE, f"{target.name} : {error}") from None
    finally:
        os.close(descriptor)
    try:
        after = os.lstat(target)
    except OSError:
        raise ExposureStoreError(StoreFailure.UNSTABLE, f"{target.name} n'est plus observable après sa lecture") from None
    if not (_identity(opened) == _identity(after_read) == _identity(info) == _identity(after)):
        raise ExposureStoreError(StoreFailure.UNSTABLE, f"{target.name} a changé pendant sa lecture")
    raw = b"".join(chunks)
    if len(raw) != info.st_size:
        raise ExposureStoreError(StoreFailure.UNSTABLE, f"{target.name} : {len(raw)} octets lus pour {info.st_size} observés")
    return raw


def _contains_float(value) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is float:
            return True
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def parse_strict_record(raw: bytes, *, max_bytes: int = MAX_A0_BYTES):
    """JSON strict (B2) : BOM, UTF-8 invalide, clé dupliquée, constante non finie, troncature ou excès de profondeur refusés (`NOT_JSON`).
    Le format normatif des A0, déclarations et attestations est « sans flottant » (23.29.4) : tout nombre à fraction ou exposant est un
    défaut de schéma (`SCHEMA`), quel que soit l'artefact."""
    try:
        value = parse_strict_json(raw, max_bytes=max_bytes, max_depth=MAX_JSON_DEPTH)
    except StrictJsonError as error:
        raise ExposureStoreError(StoreFailure.NOT_JSON, str(error)) from None
    if _contains_float(value):
        raise ExposureStoreError(StoreFailure.SCHEMA, "nombre flottant interdit par le format normatif (23.29.4)")
    return value


# ── Publication (écriture exclusive durable) ─────────────────────────────────────────────────────────────────────────

def exposure_inventory_path(campaign_dir, inventory_content_hash: str) -> Path:
    """`<campaign_dir>/exposure/inventory_<inventory_content_hash>.json` (23.13)."""
    if type(inventory_content_hash) is not str or _HEX64_RE.fullmatch(inventory_content_hash) is None:
        raise ValueError("inventory_content_hash doit être un SHA-256 hexadécimal minuscule de 64 caractères.")
    return Path(campaign_dir) / "exposure" / f"inventory_{inventory_content_hash}.json"


def _prove_rereadable(record: dict, raw: bytes, target: Path) -> None:
    """Refuse AVANT toute écriture un enregistrement que la relecture stricte refuserait (jamais de A0 publié mais illisible) : taille,
    JSON strict (profondeur, aucun flottant), puis schéma et identités."""
    if len(raw) > MAX_A0_BYTES:
        raise ExposureStoreError(StoreFailure.TOO_LARGE, f"{target.name} : {len(raw)} octets > {MAX_A0_BYTES} ; la relecture le refuserait")
    parse_strict_record(raw)
    try:
        _parse_record(record, target, raw)
    except _Schema as error:
        raise ExposureStoreError(StoreFailure.SCHEMA, f"l'enregistrement ne serait pas relu : {error}") from None


def publish_exposure_inventory(campaign_dir, assembly: ExposureInventoryAssembly, *, created_at: str) -> Path:
    """Persiste le A0 par création EXCLUSIVE durable et retourne son chemin.

    - `campaign_dir` doit exister (jamais créé) ; `exposure/` est créé par `os.mkdir` SANS parents et doit être un vrai répertoire.
    - Plusieurs A0 coexistent ; aucun fichier existant n'est écrasé, supprimé ni réparé.
    - Même contenu publié deux fois : le fichier existant est relu ; s'il est octet pour octet identique, c'est l'idempotence. Un fichier
      différent ou tronqué au nom attendu (`NAME_CONSUMED`) impose un NOUVEAU `created_at` (nouveau nom), jamais une suppression.
    - Une écriture durable incomplète (`INCOMPLETE_WRITE`) laisse le chemin consommé en place.
    """
    record = build_exposure_inventory_record(assembly, created_at=created_at)
    raw = serialize_exposure_inventory_record(record)
    directory = Path(campaign_dir)
    _prove_rereadable(record, raw, directory / "exposure" / f"inventory_{record['inventory_content_hash']}.json")
    lstat_directory(directory, "campaign_dir")
    exposure = directory / "exposure"
    try:
        os.lstat(exposure)
    except FileNotFoundError:
        try:
            os.mkdir(exposure)
        except FileExistsError:
            pass                                                               # course : relecture ci-dessous
        except OSError as error:
            raise ExposureStoreError(StoreFailure.BAD_DIRECTORY, f"création de exposure/ impossible : {error}") from None
    except OSError as error:
        raise ExposureStoreError(StoreFailure.BAD_DIRECTORY, f"exposure/ inobservable : {error}") from None
    lstat_directory(exposure, "exposure/")
    target = exposure / f"inventory_{record['inventory_content_hash']}.json"
    data = _sorted_deep(record)
    if (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8") != raw:
        raise ExposureStoreError(StoreFailure.NOT_FIXED_POINT, "la sérialisation de save_exclusive diverge de la forme normative")
    try:
        save_exclusive(target, data, "inventaire d'exposition (A0)", durable=True)
    except FileExistsError:
        try:
            existing = read_strict_file(target)
        except ExposureStoreError as error:
            raise ExposureStoreError(StoreFailure.NAME_CONSUMED, f"{target.name} existe et est illisible ({error.failure.value}) ; "
                                     "utiliser un nouveau created_at") from None
        if existing != raw:
            raise ExposureStoreError(StoreFailure.NAME_CONSUMED, f"{target.name} existe avec un contenu différent ; "
                                     "utiliser un nouveau created_at") from None
    except ExclusiveCreationIncompleteError as error:
        raise ExposureStoreError(StoreFailure.INCOMPLETE_WRITE, f"{target.name} créé (chemin consommé) mais écriture incomplète : "
                                 f"{error}") from error
    except NotADirectoryError as error:
        raise ExposureStoreError(StoreFailure.BAD_DIRECTORY, str(error)) from error
    except OSError as error:
        raise ExposureStoreError(StoreFailure.UNREADABLE, f"{target.name} : écriture impossible : {error}") from error
    return target


# ── Relecture stricte ────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScanPinRoot:
    label: str
    resolved_path: str
    may_be_empty: bool


@dataclass(frozen=True)
class ScanPin:
    """Épinglage d'un scan de B2 (précondition n° 5) : la table appliquée (`rules_digest`), les plafonds, la vacuité des racines."""

    layout: RootLayout
    rules_digest: str
    limits: ScanLimits
    hooks_used: bool
    roots: tuple


_RULES_KEYS = ("e3a_inventory", "e3a_classification", "b3_interpreters", "b4_assembly")
_KNOWN_RULES_DIGESTS = {(version, layout): digest for version, layout, digest in B3_RULES_DIGESTS}


@dataclass(frozen=True)
class RulesVersions:
    """Versions de règles ENREGISTRÉES dans un A0 (ADR 0025 23.31.6). Une version antérieure CONNUE (B3 v2) donne une lecture historique
    intègre (octets, hash, schéma et identités E3-A vérifiés), jamais une qualification avec les règles courantes : celle-ci est le recalcul
    de l'A0 par E3-J. Rien n'est réécrit ni requalifié en silence."""

    e3a_inventory: str
    e3a_classification: str
    b3_interpreters: str
    b4_assembly: str

    def is_current(self) -> bool:
        return (self.e3a_inventory, self.e3a_classification, self.b3_interpreters, self.b4_assembly) == (
            EXPOSURE_INVENTORY_SEMANTICS_VERSION, EXPOSURE_CLASSIFICATION_RULES_VERSION, B3_SEMANTICS_VERSION, B4_SEMANTICS_VERSION)


@dataclass(frozen=True)
class PersistedExposureInventory:
    """A0 relu et VÉRIFIÉ : hash, nom, point fixe d'octets, schéma exact et les quatre identités recalculées par E3-A."""

    path: Path
    file_sha256: str
    created_at: str
    inventory_content_hash: str
    own_context: OwnCampaignContext
    inventory: ExposureInventory
    accounting_provenance: TrialAccountingProvenance
    incomplete_reasons: tuple
    inventory_id: str
    inventory_content_digest: str
    static_sources_digest: str
    overlap_projection_hash: str
    registry_id: str
    registry_chain_head: Optional[str]
    derived_root_labels: tuple
    scan_pins: tuple
    plans: tuple
    non_oos_validations: tuple
    exposure_evidence: tuple
    rules_versions: RulesVersions                 # versions effectivement appliquées ; `is_current()` faux = lecture historique


class _Schema(Exception):
    pass


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise _Schema(message)


def _object(value, keys, where: str) -> dict:
    _need(type(value) is dict and set(value) == set(keys), f"{where} : jeu de clés inattendu")
    return value


def _array(value, where: str) -> list:
    _need(type(value) is list, f"{where} doit être une liste")
    return value


def _text(value, where: str) -> str:
    _need(type(value) is str and bool(value.strip()), f"{where} doit être une chaîne non vide")
    return value


def _hex(value, where: str) -> str:
    _need(type(value) is str and _HEX64_RE.fullmatch(value) is not None, f"{where} doit être un SHA-256 hexadécimal minuscule")
    return value


def _flag(value, where: str) -> bool:
    _need(type(value) is bool, f"{where} doit être un booléen")
    return value


def _unique_sorted(items: list, where: str) -> tuple:
    _need(all(type(item) is str and item for item in items), f"{where} : chaînes non vides attendues")
    _need(items == sorted(set(items)), f"{where} doit être trié, sans doublon")
    return tuple(items)


def _build(factory, *args, where: str, **kwargs):
    """Construit un objet validé par E3-A/B3/B4 ; toute erreur de validation devient un défaut de schéma."""
    try:
        return factory(*args, **kwargs)
    except (ValueError, TypeError) as error:
        raise _Schema(f"{where} : {error}") from None


def _enum(enum_cls, value, where: str):
    _need(type(value) is str, f"{where} doit être un texte")
    try:
        return enum_cls(value)
    except ValueError:
        raise _Schema(f"{where} : valeur inconnue {value!r}") from None


_FINDING_KEYS = ("source_id", "source_kind", "status", "overlap", "content_hash", "window_start_utc", "window_end_utc", "snapshot_id",
                 "campaign_id", "unresolved_cause")


def _finding(item, where: str) -> ExposureFinding:
    item = _object(item, _FINDING_KEYS, where)
    cause = item["unresolved_cause"]
    return _build(
        ExposureFinding, where=where, source_id=item["source_id"], source_kind=_enum(SourceKind, item["source_kind"], where),
        status=_enum(SourceStatus, item["status"], where), overlap=_enum(OverlapVerdict, item["overlap"], where),
        content_hash=item["content_hash"], window_start_utc=item["window_start_utc"], window_end_utc=item["window_end_utc"],
        snapshot_id=item["snapshot_id"], campaign_id=item["campaign_id"],
        unresolved_cause=None if cause is None else _enum(UnresolvedCause, cause, where))


def finding_to_record(finding: ExposureFinding) -> dict:
    """Forme persistée (10 clés) d'un `ExposureFinding` : partagée avec B6 (expositions déclarées)."""
    if type(finding) is not ExposureFinding:
        raise TypeError("finding doit être un ExposureFinding.")
    return _finding_record(finding)


def finding_from_record(item, where: str = "finding") -> ExposureFinding:
    """Reconstruit un `ExposureFinding` par le constructeur d'E3-A (aucune normalisation) ; `ExposureStoreError(SCHEMA)` sinon."""
    try:
        return _finding(item, where)
    except _Schema as error:
        raise ExposureStoreError(StoreFailure.SCHEMA, str(error)) from None


def _counters(item, where: str) -> TrialAccounting:
    item = _object(item, _COUNTER_NAMES, where)
    return _build(TrialAccounting, where=where, **{name: item[name] for name in _COUNTER_NAMES})


def _provenance(item, where: str) -> TrialAccountingProvenance:
    item = _object(item, _COUNTER_NAMES + ("reasons",), where)
    reasons = _array(item["reasons"], f"{where}.reasons")
    _need(all(type(reason) is str and reason for reason in reasons), f"{where}.reasons : chaînes non vides attendues")
    return _build(TrialAccountingProvenance, where=where, reasons=tuple(reasons),
                  **{name: _enum(CounterProvenance, item[name], where) for name in _COUNTER_NAMES})


def _scan_pin(item, where: str) -> ScanPin:
    item = _object(item, ("layout", "rules_digest", "limits", "hooks_used", "roots"), where)
    limits = _object(item["limits"], _LIMIT_NAMES, f"{where}.limits")
    roots = []
    for index, root in enumerate(_array(item["roots"], f"{where}.roots")):
        root = _object(root, ("label", "resolved_path", "may_be_empty"), f"{where}.roots[{index}]")
        _need(type(root["label"]) is str and _LABEL_RE.fullmatch(root["label"]) is not None, f"{where}.roots[{index}].label non portable")
        _need(type(root["resolved_path"]) is str and bool(root["resolved_path"]) and "\x00" not in root["resolved_path"],
              f"{where}.roots[{index}].resolved_path invalide")
        roots.append(ScanPinRoot(root["label"], root["resolved_path"], _flag(root["may_be_empty"], f"{where}.roots[{index}].may_be_empty")))
    _need([r.label for r in roots] == sorted({r.label for r in roots}), f"{where}.roots doit être trié par label, sans doublon")
    _need(_flag(item["hooks_used"], f"{where}.hooks_used") is False, f"{where}.hooks_used : un scan avec ScanHooks n'est jamais persisté")
    return ScanPin(_enum(RootLayout, item["layout"], where), _hex(item["rules_digest"], f"{where}.rules_digest"),
                   _build(ScanLimits, where=f"{where}.limits", **limits), False, tuple(roots))


def _plan(item, where: str) -> PlanIndexEntry:
    item = _object(item, ("source_id", "split_plan_id", "fingerprint", "dataset_snapshot_id", "final_holdout_start_utc",
                          "final_holdout_end_utc", "content_hash"), where)
    for name in ("source_id", "split_plan_id", "dataset_snapshot_id"):
        _text(item[name], f"{where}.{name}")
    window = (_text(item["final_holdout_start_utc"], where), _text(item["final_holdout_end_utc"], where))
    _need(_build(normalize_window, *window, where=where) == window, f"{where} : fenêtre non normalisée")
    return PlanIndexEntry(item["source_id"], item["split_plan_id"], _hex(item["fingerprint"], where), item["dataset_snapshot_id"],
                          window[0], window[1], _hex(item["content_hash"], where))


def _non_oos(item, where: str) -> NonOosValidationRun:
    item = _object(item, ("source_id", "validation_type", "content_hash"), where)
    return NonOosValidationRun(_text(item["source_id"], where), _text(item["validation_type"], where), _hex(item["content_hash"], where))


def _evidence(item, where: str) -> ExposureEvidence:
    item = _object(item, ("source_id", "status", "manifest_source_id", "manifest_content_hash"), where)
    return _build(ExposureEvidence, where=where, source_id=item["source_id"], status=_enum(EvidenceStatus, item["status"], where),
                  manifest_source_id=item["manifest_source_id"], manifest_content_hash=item["manifest_content_hash"])


def _sorted_by_source_id(items: tuple, where: str) -> tuple:
    ids = [item.source_id for item in items]
    _need(ids == sorted(set(ids)), f"{where} doit être trié par source_id, sans doublon")
    return items


_EXECUTION_KINDS = (SourceKind.JOB_EXECUTION, SourceKind.VALIDATION_RUN_OOS)
_ESTABLISHED_EXPOSURE = (EvidenceStatus.ESTABLISHED_BY_EXECUTION_WINDOW, EvidenceStatus.ESTABLISHED_BY_LOADED_COVERAGE)
_UNESTABLISHED_CAUSES = (UnresolvedCause.WINDOW_UNKNOWN, UnresolvedCause.TIMEZONE_UNKNOWN)   # B3 émet alors TOUJOURS ABSENCE_NOT_ESTABLISHED


def _own_manifest_id(job_source_id: str) -> str:
    """Identifiant B3 du `data_manifest.json` du dossier du job : `job.config:<label>/<dossier>/config_used.json` → `job.manifest:<label>/<dossier>/data_manifest.json`."""
    label_and_path = job_source_id.partition(":")[2]
    return f"job.manifest:{label_and_path.rpartition('/')[0]}/data_manifest.json"


def _check_audit_coherence(findings: tuple, notes: tuple, evidence: tuple) -> None:
    """Le relevé des preuves et les notes non OOS sont INFORMATIFS (hors `inventory_id`) mais ne peuvent pas contredire les findings auxquels
    ils se rattachent : un hash valide ne rend pas cohérent un relevé forgé. Contrôles faits SANS relire de source, dans les limites de ce
    que B3 v2 produit : chaque entrée du relevé désigne un finding d'exécution (job ou OOS) dont l'état s'accorde avec elle (exposition
    établie = RESOLVED/OVERLAPS, la couverture P2 seulement pour un job et avec le manifeste de SON dossier ; absence NON établie = UNRESOLVED
    par fenêtre ou fuseau inconnus ; AUCUNE absence établie n'est acceptée : 23.30.1 ne reconnaît aucune preuve d'exclusion à ce jour) ; un finding
    d'exécution RESOLVED, ou UNRESOLVED pour fenêtre ou fuseau inconnus, a toujours son entrée ; une note non OOS désigne un finding UNKNOWN_SOURCE non
    résolu de même `content_hash`. Le relevé ne crée donc aucun finding, ne transforme aucune absence non établie en absence établie et
    n'efface aucune anomalie."""
    by_id = {finding.source_id: finding for finding in findings}
    covered = set()
    for item in evidence:
        finding = by_id.get(item.source_id)
        _need(finding is not None and finding.source_kind in _EXECUTION_KINDS,
              f"exposure_evidence {item.source_id!r} ne désigne aucun finding d'exécution")
        resolved = finding.status is SourceStatus.RESOLVED
        if item.status in _ESTABLISHED_EXPOSURE:
            ok = resolved and finding.overlap is OverlapVerdict.OVERLAPS
            if item.status is EvidenceStatus.ESTABLISHED_BY_LOADED_COVERAGE:      # P2 : couverture d'un manifeste de JOB, de son propre dossier
                ok = ok and finding.source_kind is SourceKind.JOB_EXECUTION and item.manifest_source_id == _own_manifest_id(finding.source_id)
        elif item.status is EvidenceStatus.ABSENCE_ESTABLISHED:
            ok = False                                    # 23.30.1 : « preuves d'exclusion reconnues : aucune à ce jour » ; jamais NO_OVERLAP (23.30.4)
        else:
            ok = finding.status is SourceStatus.UNRESOLVED and finding.unresolved_cause in _UNESTABLISHED_CAUSES
        _need(ok, f"exposure_evidence {item.source_id!r} contredit son finding ({item.status.value})")
        covered.add(item.source_id)
    for finding in findings:
        if finding.source_kind not in _EXECUTION_KINDS:
            continue
        if finding.status is SourceStatus.RESOLVED or finding.unresolved_cause in _UNESTABLISHED_CAUSES:
            _need(finding.source_id in covered, f"le finding {finding.source_id!r} n'a pas d'entrée dans exposure_evidence")
    for note in notes:
        finding = by_id.get(note.source_id)
        _need(finding is not None and finding.source_kind is SourceKind.UNKNOWN_SOURCE and finding.status is SourceStatus.UNRESOLVED
              and finding.content_hash == note.content_hash,
              f"non_oos_validations {note.source_id!r} ne correspond à aucun finding UNKNOWN_SOURCE non résolu de même contenu")


def _parse_record(record: dict, path: Path, raw: bytes) -> PersistedExposureInventory:
    created_at = _text(record["created_at"], "created_at")
    _need(_build(normalize_utc_instant, created_at, where="created_at") == created_at, "created_at doit être normalisé UTC")
    context = _build(OwnCampaignContext, _text(record["campaign_id"], "campaign_id"),
                     _enum(OwnRecordStage, record["own_record_stage"], "own_record_stage"), where="contexte propre")
    findings = tuple(_finding(item, f"findings[{index}]") for index, item in enumerate(_array(record["findings"], "findings")))
    complete = _flag(record["complete"], "complete")
    scanned_roots = _unique_sorted(_array(record["scanned_roots"], "scanned_roots"), "scanned_roots")
    inventory = _build(ExposureInventory, where="inventaire", version=EXPOSURE_INVENTORY_SEMANTICS_VERSION,
                       window_start_utc=record["window_start_utc"], window_end_utc=record["window_end_utc"], findings=findings,
                       complete=complete, scanned_roots=scanned_roots,
                       trial_accounting=_counters(record["trial_accounting"], "trial_accounting"))
    provenance = _provenance(record["trial_accounting_provenance"], "trial_accounting_provenance")
    reasons = _unique_sorted(_array(record["incomplete_reasons"], "incomplete_reasons"), "incomplete_reasons")
    _need(complete == (not reasons), "complete est vrai si et seulement si aucune raison d'incomplétude n'existe")
    registry = _object(record["registry"], ("registry_id", "chain_head"), "registry")
    registry_id = _text(registry["registry_id"], "registry.registry_id")
    chain_head = None if registry["chain_head"] is None else _hex(registry["chain_head"], "registry.chain_head")
    derived = _unique_sorted(_array(record["derived_root_labels"], "derived_root_labels"), "derived_root_labels")
    versions = _object(record["rules_versions"], _RULES_KEYS, "rules_versions")
    _need(all(type(value) is str for value in versions.values()), "rules_versions : textes attendus")
    recorded = RulesVersions(**versions)
    if (recorded.e3a_inventory, recorded.e3a_classification, recorded.b4_assembly) != (
            EXPOSURE_INVENTORY_SEMANTICS_VERSION, EXPOSURE_CLASSIFICATION_RULES_VERSION, B4_SEMANTICS_VERSION) or (
            recorded.b3_interpreters not in KNOWN_B3_VERSIONS):
        raise ExposureStoreError(StoreFailure.UNKNOWN_VERSION, f"rules_versions inconnues : {versions}")
    pins = tuple(_scan_pin(item, f"scan_pins[{index}]") for index, item in enumerate(_array(record["scan_pins"], "scan_pins")))
    _need([pin.layout.value for pin in pins] == sorted({pin.layout.value for pin in pins}), "scan_pins doit être trié par disposition, sans doublon")
    for pin in pins:                                     # la table épinglée doit être celle de la version de B3 enregistrée (23.31.6)
        if _KNOWN_RULES_DIGESTS[(recorded.b3_interpreters, pin.layout)] != pin.rules_digest:
            raise ExposureStoreError(StoreFailure.RULES_DIGEST_MISMATCH,
                                     f"scan_pins {pin.layout.value} : rules_digest différent de la table de {recorded.b3_interpreters}")
    labels = {root.label for pin in pins for root in pin.roots}
    _need(set(derived) <= labels, "derived_root_labels : un label ne correspond à aucune racine scannée")
    _need(scanned_roots == tuple(sorted(labels - set(derived))), "scanned_roots doit être égal aux racines scannées moins les racines dérivées")
    plans = _sorted_by_source_id(tuple(_plan(item, f"plans[{i}]") for i, item in enumerate(_array(record["plans"], "plans"))), "plans")
    notes = _sorted_by_source_id(tuple(_non_oos(item, f"non_oos_validations[{i}]")
                                       for i, item in enumerate(_array(record["non_oos_validations"], "non_oos_validations"))),
                                 "non_oos_validations")
    evidence = _sorted_by_source_id(tuple(_evidence(item, f"exposure_evidence[{i}]")
                                          for i, item in enumerate(_array(record["exposure_evidence"], "exposure_evidence"))),
                                    "exposure_evidence")
    _check_audit_coherence(findings, notes, evidence)
    stored = {name: _hex(record[name], name) for name in ("inventory_id", "inventory_content_digest", "static_sources_digest",
                                                          "overlap_projection_hash")}
    try:
        recomputed = {
            "inventory_id": compute_exposure_inventory_id(inventory, context),
            "inventory_content_digest": compute_inventory_content_digest(inventory, context),
            "static_sources_digest": compute_static_sources_digest(inventory, context),
            "overlap_projection_hash": compute_overlap_projection_hash(inventory, context),
        }
    except (ValueError, TypeError) as error:
        raise _Schema(f"identités incalculables : {error}") from None
    for name, value in recomputed.items():
        if stored[name] != value:
            raise ExposureStoreError(StoreFailure.IDENTITY_MISMATCH, f"{name} stocké ne correspond pas au recalcul d'E3-A")
    return PersistedExposureInventory(
        path=path, file_sha256=hashlib.sha256(raw).hexdigest(), created_at=created_at,
        inventory_content_hash=record["inventory_content_hash"], own_context=context, inventory=inventory,
        accounting_provenance=provenance, incomplete_reasons=reasons, inventory_id=stored["inventory_id"],
        inventory_content_digest=stored["inventory_content_digest"], static_sources_digest=stored["static_sources_digest"],
        overlap_projection_hash=stored["overlap_projection_hash"], registry_id=registry_id, registry_chain_head=chain_head,
        derived_root_labels=derived, scan_pins=pins, plans=plans, non_oos_validations=notes, exposure_evidence=evidence,
        rules_versions=recorded)


def load_exposure_inventory(path, *, max_bytes: int = MAX_A0_BYTES) -> PersistedExposureInventory:
    """Relit un A0 en échec fermé. Ordre des contrôles : fichier régulier sans lien, taille, JSON strict, jeu de clés exact, version,
    hash stocké = hash recalculé, nom = hash, point fixe d'octets de la sérialisation normative, schéma exact (constructeurs d'E3-A, de B3
    et de B4), cohérence des racines, puis recalcul des quatre identités par E3-A. Aucune réparation, aucun repli."""
    target = Path(path)
    raw = read_strict_file(target, max_bytes=max_bytes)
    record = parse_strict_record(raw, max_bytes=max_bytes)
    if type(record) is not dict or set(record) != set(A0_RECORD_KEYS):
        raise ExposureStoreError(StoreFailure.SCHEMA, "jeu de clés du A0 inattendu")
    version = record["version"]
    if type(version) is not str:
        raise ExposureStoreError(StoreFailure.SCHEMA, "version doit être un texte")
    if version != EXPOSURE_INVENTORY_SEMANTICS_VERSION:
        raise ExposureStoreError(StoreFailure.UNKNOWN_VERSION, f"version inconnue : {version!r}")
    stored_hash = record["inventory_content_hash"]
    if type(stored_hash) is not str or _HEX64_RE.fullmatch(stored_hash) is None:
        raise ExposureStoreError(StoreFailure.SCHEMA, "inventory_content_hash doit être un SHA-256 hexadécimal minuscule")
    if compute_inventory_content_hash(record) != stored_hash:
        raise ExposureStoreError(StoreFailure.HASH_MISMATCH, "le hash recalculé du contenu diffère du hash stocké")
    named = _A0_NAME_RE.fullmatch(target.name)
    if named is None or named.group(1) != stored_hash:
        raise ExposureStoreError(StoreFailure.NAME_MISMATCH, f"le nom {target.name!r} n'est pas inventory_<inventory_content_hash>.json")
    if serialize_exposure_inventory_record(record) != raw:
        raise ExposureStoreError(StoreFailure.NOT_FIXED_POINT, "les octets lus ne sont pas la sérialisation normative du contenu")
    try:
        return _parse_record(record, target, raw)
    except _Schema as error:
        raise ExposureStoreError(StoreFailure.SCHEMA, str(error)) from None


def read_exposure_inventory(campaign_dir, inventory_content_hash: str, *, max_bytes: int = MAX_A0_BYTES) -> PersistedExposureInventory:
    """Relit le A0 de hash donné sous `<campaign_dir>/exposure/` ; `campaign_dir` et `exposure/` doivent être de vrais répertoires
    (comme à la publication) ; `load_exposure_inventory` seul ne contrôle que le parent immédiat du fichier."""
    lstat_directory(campaign_dir, "campaign_dir")
    lstat_directory(Path(campaign_dir) / "exposure", "exposure/")
    return load_exposure_inventory(exposure_inventory_path(campaign_dir, inventory_content_hash), max_bytes=max_bytes)
