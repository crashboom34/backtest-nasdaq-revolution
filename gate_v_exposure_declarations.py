"""
gate_v_exposure_declarations.py — AF-V-07 Slice E3-B6 (partie INDÉPENDANTE d'E3-C) : déclarations, chaînes, lignée et chargeur du
`DeclarationSet`.

Contrat normatif : ADR 0025 Décision 23, 23.11 étape 2, 23.13, 23.27.6, 23.29.1 à 23.29.4, 23.29.8 ; design E3-B (AI_HANDOFF.md §44.1, §45).

CE QUE FAIT CE MODULE (lecture et vérification, plus des constructeurs PURS) :
- construire et sérialiser l'enveloppe d'une déclaration (`gate_v_exposure_declaration_v1`) : octets normatifs, `declaration_id`
  (E3-A, inchangé) et `declaration_content_hash` ;
- relire strictement un fichier de déclaration, découvrir toutes les chaînes d'`<campaign_dir>/exposure/`, vérifier la lignée
  (linéarité, épinglage `carried_from`, report cumulatif des expositions, `t_sel` jamais abaissé, retour à un ancien inventaire) ;
- produire un `DeclarationSet` d'E3-A SEULEMENT dans `load_declaration_lineage`, le chargeur autorisé, après vérification complète ;
- proposer un brouillon de report (`draft_first_declaration_carry`) et lister/relire les slots d'attestation (chemins, densité,
  octets, point fixe de la sérialisation normative, aucun flottant) sans évaluer leurs épinglages ni leur schéma (E3-E, E3-J) : l'intégrité
  des octets est prouvée, la VALIDITÉ d'une attestation ne l'est jamais ici (`highest_attestation_slot` désigne un slot, pas une attestation
  valide). Avant l'`ADMISSION`, tous les slots sont lus ; après, seule l'attestation qu'elle épingle l'est (`admitted_attestation`, 23.31.4) ;
- dire le niveau de preuve atteint sur les épinglages d'A0 (`PinningReport`, 23.31.3) : seuls ceux de l'`ADMISSION` fournis par l'appelant
  sont vérifiés ; une citation d'un A0 illisible dans une attestation est une référence NON RÉSOLUE (refus), jamais une preuve ;
- exiger du chargeur la campagne attendue (`campaign_id`) : seul un A0 dont le contexte propre validé porte cette campagne compte, et CHAQUE
  déclaration de chaque chaîne porte cette campagne dans son enveloppe (23.31.1, couverte par `declaration_content_hash`, jamais par
  `declaration_id`). LIMITE : une intégrité SHA-256 recalculable sans secret révèle une COPIE, pas une falsification volontaire (réécriture
  de `campaign_id` puis des hashs) ; aucune liaison cryptographique à la campagne n'est revendiquée.
  La géométrie des expositions déclarées de la chaîne terminale est contrôlée contre `W` par `ClassificationInput` (E3-A, non recopié).

CE QUE CE MODULE NE FAIT PAS (dépendance E3-C, décision de l'utilisateur) : AUCUNE publication de déclaration ni d'attestation. La
publication durable de ces artefacts exige la primitive de publication par lien d'E3-C (`tmp + fsync + os.link + fsync`, complète ou
absente, 23.29.4) ; elle n'est ni inventée ici, ni remplacée par `O_EXCL` (un slot tronqué consommerait la chaîne dense sans
réparation possible). Un constructeur ou un brouillon valide n'est PAS une publication autorisée.

Aucune suppression, aucune rétractation, aucune réécriture d'un fichier existant : le module n'écrit rien.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import stat
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from gate_v_exposure_scan import EXPOSURE_TEMP_ORPHAN_PATTERN
from gate_v_exposure_store import (
    MAX_A0_BYTES,
    OPERATIONAL_LIMITS_QUALIFIED_FOR_REAL,
    ExposureStoreError,
    StoreFailure,
    finding_from_record,
    finding_to_record,
    load_exposure_inventory,
    lstat_directory,
    parse_strict_record,
    read_strict_file,
)
from gate_v_final_holdout_protocol import (
    EXPOSURE_DECLARATION_SEMANTICS_VERSION,
    ChronologyFacts,
    ClassificationInput,
    DeclarationSet,
    ExposureDeclaration,
    TimeProofFact,
    TimeProofStatus,
    TrialAccounting,
    build_exposure_declaration,
    compute_declaration_id,
    normalize_utc_instant,
)

DECLARATION_ENVELOPE_KEYS = (
    "version", "campaign_id", "declaration", "declaration_id", "prev_declaration_content_hash", "carried_from", "created_at",
    "declaration_content_hash",
)
_DECLARATION_KEYS = ("version", "declaration_seq", "declarant", "inventory_id", "prev_declaration_id", "declared_exposures",
                     "declared_t_sel_utc", "declared_trial_counts")
_CARRIED_KEYS = ("inventory_id", "tip_seq", "tip_declaration_id", "tip_declaration_content_hash")
_COUNTER_NAMES = ("research_runs", "strategies", "campaigns", "abandoned_reservations", "failed_ingestion_attempts", "void_commitments")
MAX_SEQ = 9999                                                       # capacité du format `seq4` / `declared:<seq4>:<pos4>` (23.29.1)
_HEX64_RE = re.compile(r"[0-9a-f]{64}")


# ── Validation et canonicalisation (duplication volontaire : helpers privés non importés entre modules) ────────────────

def _canonical_json(record: object) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sorted_deep(value):
    if isinstance(value, dict):
        return {key: _sorted_deep(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_sorted_deep(item) for item in value]
    return value


def _require_hex(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} doit être exactement un str.")
    if _HEX64_RE.fullmatch(value) is None:
        raise ValueError(f"{name} doit être un SHA-256 hexadécimal minuscule de 64 caractères.")
    return value


def _require_campaign_id(value: object, name: str) -> str:
    """Même règle que `OwnCampaignContext.current_campaign_id` (E3-A) : texte non vide."""
    if type(value) is not str:
        raise TypeError(f"{name} doit être un texte.")
    if not value.strip():
        raise ValueError(f"{name} ne peut pas être vide.")
    return value


def _require_seq(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} doit être exactement un int.")
    if not 1 <= value <= MAX_SEQ:
        raise ValueError(f"{name} doit être compris entre 1 et {MAX_SEQ}.")
    return value


@dataclass(frozen=True)
class CarriedFrom:
    """Épinglage du sommet de la chaîne précédente par la PREMIÈRE déclaration d'une chaîne non racine (23.29.2)."""

    inventory_id: str
    tip_seq: int
    tip_declaration_id: str
    tip_declaration_content_hash: str

    def __post_init__(self) -> None:
        _require_hex(self.inventory_id, "carried_from.inventory_id")
        _require_seq(self.tip_seq, "carried_from.tip_seq")
        _require_hex(self.tip_declaration_id, "carried_from.tip_declaration_id")
        _require_hex(self.tip_declaration_content_hash, "carried_from.tip_declaration_content_hash")

    def to_record(self) -> dict:
        return {name: getattr(self, name) for name in _CARRIED_KEYS}


def _carried_from(value: object) -> CarriedFrom:
    if type(value) is CarriedFrom:
        return value
    if type(value) is not dict or set(value) != set(_CARRIED_KEYS):
        raise ValueError("carried_from doit avoir exactement les clés " + ", ".join(_CARRIED_KEYS) + ".")
    return CarriedFrom(**value)


def _normalized_created_at(created_at: object) -> str:
    if type(created_at) is not str:
        raise TypeError("created_at doit être un str (instant ISO-8601 avec fuseau explicite, injecté).")
    return normalize_utc_instant(created_at)


# ── Enveloppe d'une déclaration (constructeurs PURS : aucune écriture) ───────────────────────────────────────────────

def _declaration_to_dict(declaration: ExposureDeclaration) -> dict:
    counts = declaration.declared_trial_counts
    return {
        "version": declaration.version,
        "declaration_seq": declaration.declaration_seq,
        "declarant": declaration.declarant,
        "inventory_id": declaration.inventory_id,
        "prev_declaration_id": declaration.prev_declaration_id,
        "declared_exposures": [finding_to_record(finding) for finding in declaration.declared_exposures],
        "declared_t_sel_utc": declaration.declared_t_sel_utc,
        "declared_trial_counts": None if counts is None else {name: getattr(counts, name) for name in _COUNTER_NAMES},
    }


def compute_declaration_content_hash(envelope: dict) -> str:
    """SHA-256 du JSON canonique (Décision 20.3) de l'enveloppe SANS `declaration_content_hash`, `created_at` inclus (23.29.1)."""
    if type(envelope) is not dict:
        raise TypeError("envelope doit être un dict.")
    body = {key: value for key, value in envelope.items() if key != "declaration_content_hash"}
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _normative_bytes(record) -> bytes:
    """Sérialiseur normatif UNIQUE (23.29.4) appliqué à n'importe quel enregistrement relu : tri récursif, `indent=2`, `allow_nan=False`,
    LF final, UTF-8 sans BOM. Sert au point fixe d'octets des attestations, dont le schéma (E3-E) n'est pas interprété ici."""
    return (json.dumps(_sorted_deep(record), sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def serialize_declaration_envelope(envelope: dict) -> bytes:
    """Représentation persistée normative (23.29.4) : tri récursif, `indent=2`, `allow_nan=False`, LF final, UTF-8 sans BOM."""
    if type(envelope) is not dict:
        raise TypeError("envelope doit être un dict.")
    return (json.dumps(envelope, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def build_declaration_envelope(declaration: ExposureDeclaration, *, campaign_id: str, prev_declaration_content_hash: Optional[str],
                               carried_from, created_at: str) -> dict:
    """Enveloppe persistée d'une déclaration (23.29.1, 23.31.1). CONSTRUCTEUR PUR : il ne publie rien (la publication relève d'E3-C).

    `campaign_id` (obligatoire) est couvert par `declaration_content_hash`, jamais par `declaration_id` (E3-A inchangé) ;
    `prev_declaration_content_hash` est nul si et seulement si `seq` = 1 ; `carried_from` n'existe que pour `seq` = 1 d'une chaîne non
    racine et ne désigne jamais la chaîne elle-même ; `created_at` est injecté (jamais lu d'une horloge)."""
    if type(declaration) is not ExposureDeclaration:
        raise TypeError("declaration doit être un ExposureDeclaration.")
    _require_campaign_id(campaign_id, "campaign_id")
    seq = declaration.declaration_seq
    if (seq == 1) != (prev_declaration_content_hash is None):
        raise ValueError("prev_declaration_content_hash est nul si et seulement si la déclaration est la première (seq 1).")
    if prev_declaration_content_hash is not None:
        _require_hex(prev_declaration_content_hash, "prev_declaration_content_hash")
    carried = None
    if carried_from is not None:
        if seq != 1:
            raise ValueError("carried_from n'existe que pour la première déclaration (seq 1) d'une chaîne non racine.")
        carried = _carried_from(carried_from)
        if carried.inventory_id == declaration.inventory_id:
            raise ValueError("carried_from ne peut pas désigner la chaîne de la déclaration elle-même.")
    envelope = {
        "version": EXPOSURE_DECLARATION_SEMANTICS_VERSION,
        "campaign_id": campaign_id,
        "declaration": _declaration_to_dict(declaration),
        "declaration_id": compute_declaration_id(declaration),
        "prev_declaration_content_hash": prev_declaration_content_hash,
        "carried_from": None if carried is None else carried.to_record(),
        "created_at": _normalized_created_at(created_at),
    }
    envelope = _sorted_deep(envelope)
    envelope["declaration_content_hash"] = compute_declaration_content_hash(envelope)
    return _sorted_deep(envelope)


def declaration_path(campaign_dir, inventory_id: str, seq: int) -> Path:
    """`<campaign_dir>/exposure/<inventory_id>/declaration_<seq4>.json` (23.29.1) ; slots denses à partir de `0001`, plafond `9999`."""
    return Path(campaign_dir) / "exposure" / _require_hex(inventory_id, "inventory_id") / f"declaration_{_require_seq(seq, 'seq'):04d}.json"


def attestation_path(campaign_dir, inventory_id: str, seq: int) -> Path:
    """`<campaign_dir>/exposure/<inventory_id>/attestation_<seq4>.json` (23.29.3) ; séquence indépendante de celle des déclarations."""
    return Path(campaign_dir) / "exposure" / _require_hex(inventory_id, "inventory_id") / f"attestation_{_require_seq(seq, 'seq'):04d}.json"


# ── Relecture stricte d'un fichier de déclaration ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ParsedDeclaration:
    """Déclaration relue et VÉRIFIÉE : hash du fichier, octets au point fixe, schéma exact, `declaration_id` recalculé par E3-A."""

    declaration: ExposureDeclaration
    declaration_id: str
    content_hash: str
    prev_declaration_content_hash: Optional[str]
    carried_from: Optional[CarriedFrom]
    created_at: str
    file_sha256: str
    campaign_id: str                              # égal à la campagne attendue par le lecteur (23.31.1)


class _Schema(Exception):
    pass


def _schema(condition: bool, message: str) -> None:
    if not condition:
        raise _Schema(message)


def _declaration_from_dict(item: object) -> ExposureDeclaration:
    _schema(type(item) is dict and set(item) == set(_DECLARATION_KEYS), "declaration : jeu de clés inattendu")
    exposures = item["declared_exposures"]
    _schema(type(exposures) is list, "declared_exposures doit être une liste")
    counts = item["declared_trial_counts"]
    if counts is not None:
        _schema(type(counts) is dict and set(counts) == set(_COUNTER_NAMES), "declared_trial_counts : jeu de clés inattendu")
        try:
            counts = TrialAccounting(**{name: counts[name] for name in _COUNTER_NAMES})
        except (ValueError, TypeError) as error:
            raise _Schema(f"declared_trial_counts : {error}") from None
    try:
        return ExposureDeclaration(
            version=item["version"], declaration_seq=item["declaration_seq"], declarant=item["declarant"],
            inventory_id=item["inventory_id"], prev_declaration_id=item["prev_declaration_id"],
            declared_exposures=tuple(finding_from_record(finding, f"declared_exposures[{index}]")
                                     for index, finding in enumerate(exposures)),
            declared_t_sel_utc=item["declared_t_sel_utc"], declared_trial_counts=counts)
    except ExposureStoreError as error:
        raise _Schema(error.detail) from None
    except (ValueError, TypeError) as error:
        raise _Schema(f"declaration : {error}") from None


def parse_declaration_file(raw: bytes, *, inventory_id: str, seq: int, campaign_id: str) -> ParsedDeclaration:
    """Relit en échec fermé les octets d'`<inventory_id>/declaration_<seq4>.json` pour la campagne ATTENDUE `campaign_id` (obligatoire,
    23.31.1). Ordre : JSON strict, clés exactes, version, hash stocké = hash recalculé, point fixe d'octets, schéma exact (constructeurs
    d'E3-A), répertoire et nom = contenu, `declaration_id` recalculé, campagne = campagne attendue. `ExposureStoreError` typée
    (`NOT_JSON`, `SCHEMA`, `UNKNOWN_VERSION`, `HASH_MISMATCH`, `NOT_FIXED_POINT`, `NAME_MISMATCH`, `IDENTITY_MISMATCH`,
    `CAMPAIGN_MISMATCH`)."""
    _require_hex(inventory_id, "inventory_id")
    _require_seq(seq, "seq")
    _require_campaign_id(campaign_id, "campaign_id")
    envelope = parse_strict_record(raw)
    if type(envelope) is not dict or set(envelope) != set(DECLARATION_ENVELOPE_KEYS):
        raise ExposureStoreError(StoreFailure.SCHEMA, "jeu de clés de l'enveloppe inattendu")
    version = envelope["version"]
    if type(version) is not str:
        raise ExposureStoreError(StoreFailure.SCHEMA, "version doit être un texte")
    if version != EXPOSURE_DECLARATION_SEMANTICS_VERSION:
        raise ExposureStoreError(StoreFailure.UNKNOWN_VERSION, f"version inconnue : {version!r}")
    stored_hash = envelope["declaration_content_hash"]
    if type(stored_hash) is not str or _HEX64_RE.fullmatch(stored_hash) is None:
        raise ExposureStoreError(StoreFailure.SCHEMA, "declaration_content_hash doit être un SHA-256 hexadécimal minuscule")
    if compute_declaration_content_hash(envelope) != stored_hash:
        raise ExposureStoreError(StoreFailure.HASH_MISMATCH, "le hash recalculé de l'enveloppe diffère du hash stocké")
    if serialize_declaration_envelope(envelope) != raw:
        raise ExposureStoreError(StoreFailure.NOT_FIXED_POINT, "les octets lus ne sont pas la sérialisation normative du contenu")
    try:
        recorded_campaign = envelope["campaign_id"]
        _schema(type(recorded_campaign) is str and bool(recorded_campaign.strip()), "campaign_id doit être un texte non vide")
        declaration = _declaration_from_dict(envelope["declaration"])
        stored_id = envelope["declaration_id"]
        _schema(type(stored_id) is str and _HEX64_RE.fullmatch(stored_id) is not None, "declaration_id doit être un SHA-256 hexadécimal")
        prev_hash = envelope["prev_declaration_content_hash"]
        if declaration.declaration_seq == 1:
            _schema(prev_hash is None, "la première déclaration n'a pas de prev_declaration_content_hash")
        else:
            _schema(type(prev_hash) is str and _HEX64_RE.fullmatch(prev_hash) is not None,
                    "prev_declaration_content_hash doit être un SHA-256 hexadécimal (seq > 1)")
        carried_value = envelope["carried_from"]
        carried = None
        if carried_value is not None:
            _schema(declaration.declaration_seq == 1, "carried_from n'existe que pour la première déclaration")
            try:
                carried = _carried_from(carried_value)
            except (ValueError, TypeError) as error:
                raise _Schema(f"carried_from : {error}") from None
        created_at = envelope["created_at"]
        _schema(type(created_at) is str, "created_at doit être un texte")
        try:
            _schema(normalize_utc_instant(created_at) == created_at, "created_at doit être normalisé UTC")
        except ValueError as error:
            raise _Schema(f"created_at : {error}") from None
    except _Schema as error:
        raise ExposureStoreError(StoreFailure.SCHEMA, str(error)) from None
    if declaration.inventory_id != inventory_id or declaration.declaration_seq != seq:
        raise ExposureStoreError(StoreFailure.NAME_MISMATCH, "le répertoire ou le nom du fichier ne correspond pas au contenu")
    if compute_declaration_id(declaration) != stored_id:
        raise ExposureStoreError(StoreFailure.IDENTITY_MISMATCH, "declaration_id stocké ne correspond pas au recalcul d'E3-A")
    if recorded_campaign != campaign_id:
        raise ExposureStoreError(StoreFailure.CAMPAIGN_MISMATCH, f"déclaration de la campagne {recorded_campaign!r}, attendue {campaign_id!r}")
    return ParsedDeclaration(declaration, stored_id, stored_hash, prev_hash, carried, created_at, hashlib.sha256(raw).hexdigest(),
                             recorded_campaign)


# ── Découverte de `exposure/`, chaînes et lignée ─────────────────────────────────────────────────────────────────────

# Plafonds OPÉRATIONNELS PROVISOIRES, NON NORMATIFS (ADR 0025 23.31.5) : gardes SYNTHETIC, NON qualifiées pour REAL
# (`OPERATIONAL_LIMITS_QUALIFIED_FOR_REAL`, B5). Refus : excès d'entrées PENDANT le listage d'un répertoire ; excès de taille cumulée, chaque
# fichier étant compté par `lstat` au listage de son répertoire, avant sa lecture, et jamais lu au-delà de sa taille listée (`_read_cap` ; un
# fichier qui a grandi est refusé pour instabilité). Mémoire : les A0 valides restent en mémoire sous forme d'objets (pic mesuré ≈ ×6 la taille
# du fichier sur un A0 de 14,9 Mio, §55.5) ; la valeur au plafond n'a pas été mesurée.
MAX_DIRECTORY_ENTRIES = 100_000                                      # entrées listées sous exposure/ (refus avant toute lecture profonde) ; une chaîne pleine (9 999 + 9 999) tient, six non
MAX_TOTAL_READ_BYTES = 128 * 1024 * 1024                             # taille cumulée OBSERVÉE (lstat) des fichiers à lire ; les A0 valides sont gardés en mémoire (objets Python)
_A0_NAME_RE = re.compile(r"inventory_([0-9a-f]{64})\.json")
_DECLARATION_NAME_RE = re.compile(r"declaration_([0-9]{4})\.json")
_ATTESTATION_NAME_RE = re.compile(r"attestation_([0-9]{4})\.json")
_ORPHAN_NAME_RE = re.compile(EXPOSURE_TEMP_ORPHAN_PATTERN)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class LineageFailure(str, Enum):
    """Cause typée d'un refus de structure ou de lignée (échec fermé, aucune réparation automatique)."""

    BAD_DIRECTORY = "BAD_DIRECTORY"
    LINK_OR_REPARSE_POINT = "LINK_OR_REPARSE_POINT"
    NOT_REGULAR = "NOT_REGULAR"
    UNKNOWN_ENTRY = "UNKNOWN_ENTRY"
    TOO_MANY_ENTRIES = "TOO_MANY_ENTRIES"
    TOO_MUCH_DATA = "TOO_MUCH_DATA"
    SEQ_GAP = "SEQ_GAP"
    DECLARATION_INVALID = "DECLARATION_INVALID"
    ID_CHAIN_BROKEN = "ID_CHAIN_BROKEN"
    BROKEN_LINK = "BROKEN_LINK"
    ATTESTATION_GAP = "ATTESTATION_GAP"
    ATTESTATION_INVALID = "ATTESTATION_INVALID"
    ATTESTATION_WITHOUT_DECLARATION = "ATTESTATION_WITHOUT_DECLARATION"
    A0_MISSING = "A0_MISSING"
    CAMPAIGN_MISMATCH = "CAMPAIGN_MISMATCH"
    PINNED_A0_MISSING = "PINNED_A0_MISSING"
    WINDOW_NOT_FIXED = "WINDOW_NOT_FIXED"
    DECLARED_GEOMETRY_CONTRADICTION = "DECLARED_GEOMETRY_CONTRADICTION"
    PINNED_A0_UNREADABLE = "PINNED_A0_UNREADABLE"                  # A0 illisible épinglé par l'ADMISSION (fourni par l'appelant)
    A0_PIN_UNRESOLVED = "A0_PIN_UNRESOLVED"                        # A0 illisible CITÉ par une attestation pertinente : ni preuve ni absence (23.31.3)
    ADMITTED_ATTESTATION_MISSING = "ADMITTED_ATTESTATION_MISSING"  # attestation épinglée par l'ADMISSION absente (23.31.4)
    ADMITTED_ATTESTATION_REPLACED = "ADMITTED_ATTESTATION_REPLACED"  # octets différents de ceux épinglés (« remplacée », 23.10, 23.29.3)
    ADMITTED_CHAIN_NOT_TERMINAL = "ADMITTED_CHAIN_NOT_TERMINAL"      # l'attestation épinglée n'est pas dans la chaîne terminale : changement d'exposition
    ADMITTED_INVENTORY_CHANGED = "ADMITTED_INVENTORY_CHANGED"        # l'inventaire courant n'est plus celui de l'attestation épinglée (pas encore de chaîne)
    MISSING_CHAIN = "MISSING_CHAIN"
    FORK = "FORK"
    CYCLE = "CYCLE"
    UNLINKED_CHAIN = "UNLINKED_CHAIN"
    PIN_MISMATCH = "PIN_MISMATCH"
    CARRY_OVER_OMITTED = "CARRY_OVER_OMITTED"
    CARRY_OVER_TOO_LARGE = "CARRY_OVER_TOO_LARGE"
    T_SEL_LOWERED = "T_SEL_LOWERED"
    INVENTORY_REVERSION = "INVENTORY_REVERSION"


class LineageError(ValueError):
    """Refus du chargeur de lignée. `cause` porte la cause typée d'un défaut de fichier (`StoreFailure`) le cas échéant."""

    def __init__(self, failure: LineageFailure, detail: str, cause: Optional[StoreFailure] = None) -> None:
        super().__init__(f"{failure.value} : {detail}")
        self.failure = failure
        self.detail = detail
        self.cause = cause


class LineageState(str, Enum):
    NO_LINEAGE = "NO_LINEAGE"                          # aucune chaîne : aucune déclaration, donc aucune classification possible
    NO_CHAIN_FOR_CURRENT = "NO_CHAIN_FOR_CURRENT"      # l'inventaire courant n'a pas encore de chaîne (23.29.2, règle 6)
    CURRENT_IS_TERMINAL = "CURRENT_IS_TERMINAL"        # la chaîne de l'inventaire courant est la chaîne terminale


class IgnoredKind(str, Enum):
    PUBLICATION_ORPHAN = "PUBLICATION_ORPHAN"                      # `.exposure.tmp.<32 hex>` : ignoré, consigné, jamais lu
    EMPTY_INVENTORY_DIRECTORY = "EMPTY_INVENTORY_DIRECTORY"        # sans aucune déclaration : pas une chaîne
    UNREADABLE_INVENTORY = "UNREADABLE_INVENTORY"                  # `inventory_<hash>.json` illisible ou tronqué : orphelin, sauf s'il est épinglé
    FOREIGN_CAMPAIGN_INVENTORY = "FOREIGN_CAMPAIGN_INVENTORY"      # A0 valide dont le contexte propre porte une AUTRE campagne : écarté, consigné
    # Les deux étiquettes suivantes sont INFORMATIVES : elles ne neutralisent rien et ne PROUVENT pas la chronologie. Le « postérieur » ci-dessous se déduit de
    # 23.29.3 et suppose une ADMISSION conforme que B6 ne peut pas authentifier ; la preuve de chronologie relève de l'enregistrement ADMISSION du registre (E3-D / E3-J).
    ATTESTATION_WITHOUT_EFFECT = "ATTESTATION_WITHOUT_EFFECT"      # après l'ADMISSION, slot de seq > slot épinglé (même chaîne) : postérieur, sans effet (23.29.3)
    ATTESTATION_NOT_REREAD = "ATTESTATION_NOT_REREAD"              # après l'ADMISSION, slot antérieur ou d'une autre chaîne : NON relu, intégrité non revérifiée ici


class LineagePhase(str, Enum):
    PRE_ADMISSION = "PRE_ADMISSION"        # tous les slots d'attestation sont lus strictement ; candidat = plus haut slot de la chaîne terminale
    POST_ADMISSION = "POST_ADMISSION"      # seule l'attestation épinglée par l'ADMISSION est lue ; les autres slots n'ont aucun effet


@dataclass(frozen=True)
class IgnoredEntry:
    kind: IgnoredKind
    relative_path: str
    detail: str = ""


@dataclass(frozen=True)
class AttestationSlot:
    """Slot d'attestation : chemin, densité et octets seulement. Son schéma et ses épinglages relèvent d'E3-E et d'E3-J (23.29.3)."""

    inventory_id: str
    seq: int
    path: Path
    file_sha256: str


@dataclass(frozen=True)
class AttestationPin:
    """Attestation épinglée par l'`ADMISSION` (fournie par l'appelant, E3-D/E3-J) : répertoire, slot et SHA-256 des octets du fichier (égal,
    par le point fixe, au SHA-256 de la sérialisation normative).

    FORME PROVISOIRE ET NON AUTHENTIFIÉE. (1) Le SHA-256 du fichier est la lecture littérale de 23.29.3 (« fichier épinglé par hash ») et ne
    suppose aucun schéma d'attestation (E3-E) ; ce n'est PAS la formule normative recommandée en F5 (hash de contenu du record, dans
    `docs/adr/0025-proposal-E3B-F1-F5-PROPOSED.md`), qui remplacera ce champ quand E3-E fixera le record. (2) B6 reçoit ce témoin de l'appelant et ne
    peut pas prouver qu'il est celui de l'enregistrement `ADMISSION` du registre : seule la référence portée par cet enregistrement (E3-D) fait foi."""

    inventory_id: str
    seq: int
    file_sha256: str

    def __post_init__(self) -> None:
        _require_hex(self.inventory_id, "admitted_attestation.inventory_id")
        _require_seq(self.seq, "admitted_attestation.seq")
        _require_hex(self.file_sha256, "admitted_attestation.file_sha256")


@dataclass(frozen=True)
class PinningReport:
    """Niveau de preuve RÉELLEMENT atteint sur les épinglages d'A0 (ADR 0025 23.31.3). B6 ne déclare JAMAIS un épinglage entièrement
    vérifié : sans schéma d'attestation (E3-E), aucun champ n'est contractuel ; une citation d'un A0 illisible est refusée comme non
    résolue, et l'absence de citation détectée ne prouve pas l'absence d'épinglage (E3-J relit l'A0 épinglé par son hash)."""

    admission_pinned_a0_hashes: tuple     # fournis par l'appelant : chacun désigne un A0 présent, lisible et de la campagne attendue
    orphan_a0_hashes: tuple               # A0 illisibles, non épinglés par l'ADMISSION, sans citation détectée : épinglage par attestation NON évalué
    attestation_pins_evaluated: bool      # toujours faux dans B6


@dataclass(frozen=True)
class DeclarationChain:
    """Chaîne dense `declaration_0001..n` d'un répertoire d'inventaire, entièrement relue et vérifiée."""

    inventory_id: str
    declarations: tuple
    hash_linked: bool
    attestation_slots: tuple

    @property
    def tip(self) -> ParsedDeclaration:
        return self.declarations[-1]

    @property
    def first(self) -> ParsedDeclaration:
        return self.declarations[0]


@dataclass(frozen=True)
class LoadedLineage:
    """Résultat du chargeur de lignée, SEULE source d'un `DeclarationSet` destiné à la classification (23.29.2)."""

    current_inventory_id: str
    campaign_id: str
    state: LineageState
    chains: tuple                                   # racine → chaîne terminale
    inventories: tuple                              # A0 valides (`PersistedExposureInventory`)
    ignored: tuple                                  # orphelins et répertoires vides consignés
    declaration_set: Optional[DeclarationSet]       # non nul seulement si l'inventaire courant est la chaîne terminale
    terminal_inventory_id: Optional[str]
    declaration_lineage_digest: Optional[str]
    tip_seq: Optional[int]
    tip_declaration_content_hash: Optional[str]
    phase: LineagePhase
    admitted_attestation: Optional[AttestationSlot]  # après l'ADMISSION : le slot épinglé, relu strictement et de hash égal ; sinon None
    pinning: PinningReport


def _is_link(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool((getattr(info, "st_file_attributes", 0) or 0) & _REPARSE_POINT)


class _Budget:
    def __init__(self) -> None:
        self.entries = 0
        self.bytes = 0


def _list_directory(path: Path, budget: _Budget) -> list:
    """`[(nom, lstat)]` trié ; un lien ou point d'analyse est refusé, le plafond d'entrées est contrôlé avant toute lecture profonde."""
    names = []
    try:
        with os.scandir(path) as listing:
            for entry in listing:
                names.append(entry.name)
                if budget.entries + len(names) > MAX_DIRECTORY_ENTRIES:
                    raise LineageError(LineageFailure.TOO_MANY_ENTRIES, f"plus de {MAX_DIRECTORY_ENTRIES} entrées sous exposure/")
    except OSError as error:
        raise LineageError(LineageFailure.BAD_DIRECTORY, f"{path.name} illisible : {error}") from None
    names.sort()
    budget.entries += len(names)
    entries = []
    for name in names:
        try:
            info = os.lstat(path / name)
        except OSError as error:
            raise LineageError(LineageFailure.BAD_DIRECTORY, f"{name} illisible : {error}") from None
        if _is_link(info):
            raise LineageError(LineageFailure.LINK_OR_REPARSE_POINT, f"{name} est un lien ou un point d'analyse")
        if stat.S_ISREG(info.st_mode):
            budget.bytes += info.st_size
            if budget.bytes > MAX_TOTAL_READ_BYTES:
                raise LineageError(LineageFailure.TOO_MUCH_DATA, f"plus de {MAX_TOTAL_READ_BYTES} octets à lire sous exposure/")
        entries.append((name, info))
    return entries


def _checked_directory(path, what: str) -> None:
    """`lstat_directory` avec les causes typées de la lignée (un lien ou point d'analyse reste `LINK_OR_REPARSE_POINT`)."""
    try:
        lstat_directory(path, what)
    except ExposureStoreError as error:
        raise LineageError(LineageFailure.LINK_OR_REPARSE_POINT if error.failure is StoreFailure.LINK_OR_REPARSE_POINT
                           else LineageFailure.BAD_DIRECTORY, error.detail, error.failure) from None


def _read_cap(listed_size: int) -> int:
    """Plafond de lecture d'un fichier : sa taille LISTÉE (déjà comptée dans le budget cumulé), jamais plus que `MAX_A0_BYTES`."""
    return max(1, min(MAX_A0_BYTES, listed_size))


def _grown_since_listing(error: ExposureStoreError, listed_size: int) -> bool:
    """Un `TOO_LARGE` sur un fichier listé sous le plafond signifie qu'il a GRANDI depuis le listage : instabilité, pas contenu."""
    return error.failure is StoreFailure.TOO_LARGE and listed_size <= MAX_A0_BYTES


def _read_file(path: Path, failure: LineageFailure, listed_size: int) -> bytes:
    try:
        return read_strict_file(path, max_bytes=_read_cap(listed_size))
    except ExposureStoreError as error:
        cause = StoreFailure.UNSTABLE if _grown_since_listing(error, listed_size) else error.failure
        raise LineageError(failure, f"{path.name} : {error.detail}", cause) from None


def _read_chain(exposure: Path, inventory_id: str, campaign_id: str, admitted: Optional[AttestationPin], budget: _Budget, ignored: list,
                unreadable_hashes: frozenset, cited: set) -> Optional[DeclarationChain]:
    directory = exposure / inventory_id
    _checked_directory(directory, f"exposure/{inventory_id}")
    declaration_seqs, attestation_seqs, orphans, sizes = [], [], [], {}
    for name, info in _list_directory(directory, budget):
        sizes[name] = info.st_size
        file_like = _DECLARATION_NAME_RE.fullmatch(name) or _ATTESTATION_NAME_RE.fullmatch(name) or _ORPHAN_NAME_RE.fullmatch(name)
        if file_like is not None and not stat.S_ISREG(info.st_mode):
            raise LineageError(LineageFailure.NOT_REGULAR, f"{name} n'est pas un fichier régulier")
        if (match := _DECLARATION_NAME_RE.fullmatch(name)) is not None:
            declaration_seqs.append(int(match.group(1)))
        elif (match := _ATTESTATION_NAME_RE.fullmatch(name)) is not None:
            attestation_seqs.append(int(match.group(1)))
        elif _ORPHAN_NAME_RE.fullmatch(name) is not None:
            orphans.append(name)
        else:
            raise LineageError(LineageFailure.UNKNOWN_ENTRY, f"exposure/{inventory_id}/{name} n'est pas un nom connu")
    ignored.extend(IgnoredEntry(IgnoredKind.PUBLICATION_ORPHAN, f"exposure/{inventory_id}/{name}") for name in orphans)
    if not declaration_seqs:
        if attestation_seqs:
            raise LineageError(LineageFailure.ATTESTATION_WITHOUT_DECLARATION,
                               f"exposure/{inventory_id} contient une attestation mais aucune déclaration")
        ignored.append(IgnoredEntry(IgnoredKind.EMPTY_INVENTORY_DIRECTORY, f"exposure/{inventory_id}"))
        return None
    if sorted(declaration_seqs) != list(range(1, len(declaration_seqs) + 1)):
        raise LineageError(LineageFailure.SEQ_GAP, f"exposure/{inventory_id} : slots de déclaration non denses {sorted(declaration_seqs)[:6]}")
    parsed = []
    for seq in range(1, len(declaration_seqs) + 1):
        path = declaration_path(exposure.parent, inventory_id, seq)
        try:
            parsed.append(parse_declaration_file(_read_file(path, LineageFailure.DECLARATION_INVALID, sizes[path.name]),
                                                 inventory_id=inventory_id, seq=seq, campaign_id=campaign_id))
        except ExposureStoreError as error:
            failure = (LineageFailure.CAMPAIGN_MISMATCH if error.failure is StoreFailure.CAMPAIGN_MISMATCH
                       else LineageFailure.DECLARATION_INVALID)
            raise LineageError(failure, f"exposure/{inventory_id}/{path.name} : {error.detail}", error.failure) from None
    hash_linked = True
    for previous, current in zip(parsed, parsed[1:]):
        if current.declaration.prev_declaration_id != previous.declaration_id:
            raise LineageError(LineageFailure.ID_CHAIN_BROKEN,
                               f"exposure/{inventory_id} : la déclaration {current.declaration.declaration_seq} ne suit pas l'identité de la précédente")
        if current.prev_declaration_content_hash != previous.content_hash:
            hash_linked = False
    # Densité des NOMS de slots : règle de STRUCTURE (aucun slot n'est jamais supprimé, 23.29.3), contrôlée dans les deux phases.
    if sorted(attestation_seqs) != list(range(1, len(attestation_seqs) + 1)):
        raise LineageError(LineageFailure.ATTESTATION_GAP, f"exposure/{inventory_id} : slots d'attestation non denses {sorted(attestation_seqs)[:6]}")
    if admitted is None:                          # avant l'ADMISSION : tous les slots sont lus strictement (23.29.3)
        to_read = list(range(1, len(attestation_seqs) + 1))
    else:                                         # après l'ADMISSION : le seul slot épinglé ; les autres sont identifiés, sans effet
        to_read = [admitted.seq] if admitted.inventory_id == inventory_id and admitted.seq in attestation_seqs else []
        # « Postérieur » n'est jamais prouvé par une date : il se déduit de 23.29.3 (avant l'ADMISSION, l'attestation valide est le slot de plus haut
        # `seq`, que l'ADMISSION épingle) ; cette déduction suppose une ADMISSION conforme, que B6 ne peut pas authentifier (E3-D / E3-J).
        ignored.extend(IgnoredEntry(IgnoredKind.ATTESTATION_WITHOUT_EFFECT if inventory_id == admitted.inventory_id and seq > admitted.seq
                                    else IgnoredKind.ATTESTATION_NOT_REREAD, f"exposure/{inventory_id}/attestation_{seq:04d}.json")
                       for seq in sorted(attestation_seqs) if seq not in to_read)
    slots = []
    for seq in to_read:
        path = attestation_path(exposure.parent, inventory_id, seq)
        raw = _read_file(path, LineageFailure.ATTESTATION_INVALID, sizes[path.name])
        if admitted is not None and hashlib.sha256(raw).hexdigest() != admitted.file_sha256:
            raise LineageError(LineageFailure.ADMITTED_ATTESTATION_REPLACED, f"exposure/{inventory_id}/{path.name} : octets différents de ceux épinglés")
        try:
            value = parse_strict_record(raw)
        except ExposureStoreError as error:
            raise LineageError(LineageFailure.ATTESTATION_INVALID, f"{path.name} : {error.detail}", error.failure) from None
        if type(value) is not dict:
            raise LineageError(LineageFailure.ATTESTATION_INVALID, f"{path.name} doit être un objet JSON")
        if _normative_bytes(value) != raw:
            raise LineageError(LineageFailure.ATTESTATION_INVALID, f"{path.name} n'est pas la sérialisation normative de son contenu",
                               StoreFailure.NOT_FIXED_POINT)
        if unreadable_hashes:                     # références POTENTIELLES aux seuls A0 illisibles (casse ignorée, sous-chaîne comprise)
            for text in _strings_of(value):
                lowered = text.lower()
                cited.update(bad for bad in unreadable_hashes if bad in lowered)
        slots.append(AttestationSlot(inventory_id, seq, path, hashlib.sha256(raw).hexdigest()))
    return DeclarationChain(inventory_id, tuple(parsed), hash_linked, tuple(slots))


# Une occurrence du hash d'un A0 illisible dans une chaîne d'attestation (casse ignorée, y compris au sein d'une chaîne plus longue) est une
# RÉFÉRENCE POTENTIELLE, jamais la preuve d'un épinglage (aucun champ d'attestation n'est contractuel avant E3-E, 23.31.3). Seuls les hashs des
# A0 illisibles sont recherchés : aucune collection de toutes les fenêtres de 64 caractères (mémoire bornée par la taille du fichier).


def _strings_of(value) -> set:
    """Toutes les chaînes (clés et valeurs, à toute profondeur) d'une valeur JSON : le schéma d'attestation relève d'E3-E."""
    found, pending = set(), [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            found.add(item)
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return found


def _exposure_content(finding) -> tuple:
    """Contenu comparé pour le report : TOUS les champs d'`ExposureFinding` sauf `source_id` (renuméroté), en multiensemble (23.29.2)."""
    return (finding.source_kind, finding.status, finding.overlap, finding.content_hash, finding.window_start_utc,
            finding.window_end_utc, finding.snapshot_id, finding.campaign_id, finding.unresolved_cause)


def _declared_exposures(chain: DeclarationChain) -> list:
    return [finding for parsed in chain.declarations for finding in parsed.declaration.declared_exposures]


def _maximum_t_sel(chain: DeclarationChain) -> Optional[str]:
    """Maximum des `t_sel` déclarés d'une chaîne (instants normalisés à largeur fixe : l'ordre lexical est l'ordre chronologique)."""
    values = [parsed.declaration.declared_t_sel_utc for parsed in chain.declarations if parsed.declaration.declared_t_sel_utc is not None]
    return max(values) if values else None


def _verify_lineage(chains: list) -> list:
    """Linéarité, épinglage, report cumulatif et `t_sel` (23.29.2, règles 1 à 5). Retourne les chaînes de la racine à la terminale."""
    by_id = {chain.inventory_id: chain for chain in chains}
    for chain in chains:
        carried = chain.first.carried_from
        if carried is not None and carried.inventory_id not in by_id:
            raise LineageError(LineageFailure.MISSING_CHAIN, f"exposure/{chain.inventory_id} reprend une chaîne absente ou non lue : {carried.inventory_id[:12]}…")
    roots = [chain for chain in chains if chain.first.carried_from is None]
    if not roots:
        raise LineageError(LineageFailure.CYCLE, "aucune racine : toutes les chaînes en reprennent une autre")
    if len(roots) > 1:
        raise LineageError(LineageFailure.FORK, f"{len(roots)} racines : bifurcation")
    successors = {}
    for chain in chains:
        carried = chain.first.carried_from
        if carried is None:
            continue
        if carried.inventory_id == chain.inventory_id:
            raise LineageError(LineageFailure.CYCLE, f"exposure/{chain.inventory_id} se reprend elle-même")
        if carried.inventory_id in successors:
            raise LineageError(LineageFailure.FORK, f"exposure/{carried.inventory_id} a plusieurs successeurs : bifurcation")
        successors[carried.inventory_id] = chain
    # Terminaison : chaque chaîne a au plus UN prédécesseur (`carried_from`) et la racine n'en a aucun ; les bifurcations et auto-références sont
    # refusées ci-dessus, donc le parcours depuis la racine ne revisite jamais une chaîne. Un cycle hors racine laisse des chaînes non reliées.
    ordered = [roots[0]]
    while ordered[-1].inventory_id in successors:
        ordered.append(successors[ordered[-1].inventory_id])
    if len(ordered) != len(chains):
        raise LineageError(LineageFailure.UNLINKED_CHAIN, f"{len(chains) - len(ordered)} chaîne(s) non reliée(s) à la racine")
    for chain in ordered[:-1]:
        if not chain.hash_linked:
            raise LineageError(LineageFailure.BROKEN_LINK, f"exposure/{chain.inventory_id} : lien prev_declaration_content_hash rompu dans une chaîne non terminale")
    for previous, following in zip(ordered, ordered[1:]):
        carried, tip = following.first.carried_from, previous.tip
        if (carried.tip_seq, carried.tip_declaration_id, carried.tip_declaration_content_hash) != (
                tip.declaration.declaration_seq, tip.declaration_id, tip.content_hash):
            raise LineageError(LineageFailure.PIN_MISMATCH, f"exposure/{following.inventory_id} : carried_from ne désigne pas le sommet réel de {previous.inventory_id[:12]}…")
        if Counter(map(_exposure_content, _declared_exposures(previous))) - Counter(map(_exposure_content, following.first.declaration.declared_exposures)):
            raise LineageError(LineageFailure.CARRY_OVER_OMITTED, f"exposure/{following.inventory_id} : la première déclaration omet des expositions déclarées de la chaîne précédente")
        floor = _maximum_t_sel(previous)
        if floor is not None:
            reported = following.first.declaration.declared_t_sel_utc
            if reported is None or reported < floor:
                raise LineageError(LineageFailure.T_SEL_LOWERED, f"exposure/{following.inventory_id} : declared_t_sel_utc inférieur à {floor}")
    return ordered


def _lineage_digest(ordered: list) -> str:
    return hashlib.sha256(_canonical_json([{"inventory_id": c.inventory_id, "tip_seq": c.tip.declaration.declaration_seq,
                                             "tip_declaration_content_hash": c.tip.content_hash} for c in ordered]).encode("utf-8")).hexdigest()


# Chronologie NEUTRALE : `ClassificationInput` n'en lit rien pour valider la géométrie ; elle n'est jamais une preuve de temps.
_NEUTRAL_CHRONOLOGY = ChronologyFacts(None, None, TimeProofFact(TimeProofStatus.ABSENT, None, None), None, None, None, None)


def _a0_of(inventories, inventory_id: str):
    """Un A0 VALIDE de cette campagne pour `inventory_id` (le plus ancien, départagé par hash) : tous partagent la même fenêtre `W`,
    puisque `inventory_id` la couvre (23.27.3)."""
    candidates = [a0 for a0 in inventories if a0.inventory_id == inventory_id]
    return min(candidates, key=lambda a0: (a0.created_at, a0.inventory_content_hash)) if candidates else None


def _probe_declaration_set(declarations: tuple, hash_linked: bool) -> DeclarationSet:
    """Ensemble de SONDE du brouillon de report pour `ClassificationInput` : consommé sur place, jamais retourné, remis ni conservé."""
    return DeclarationSet(declarations, hash_linked)


def _check_declared_geometry(declaration_set: DeclarationSet, a0, where: str) -> None:
    """Un verdict `OVERLAPS` / `NO_OVERLAP` déclaré doit s'accorder avec sa fenêtre vis-à-vis de `W` de l'inventaire. La règle est celle
    d'E3-A : elle est EXERCÉE par `ClassificationInput` (fonction publique), jamais recopiée. Sans cela, une lignée relue puis refusée plus
    tard par la classification pourrait être présentée comme validée."""
    try:
        ClassificationInput(a0.inventory, declaration_set, _NEUTRAL_CHRONOLOGY, a0.own_context)
    except ValueError as error:
        raise LineageError(LineageFailure.DECLARED_GEOMETRY_CONTRADICTION, f"{where} : {error}") from None


def _declaration_set(chain: DeclarationChain) -> DeclarationSet:
    """SEUL point de construction d'un `DeclarationSet` REMIS par le lot B6 : appelé par `load_declaration_lineage` après toutes les
    vérifications (la sonde de géométrie du brouillon en construit un autre, consommé sur place et jamais remis)."""
    try:
        return DeclarationSet(tuple(parsed.declaration for parsed in chain.declarations), chain.hash_linked)
    except ValueError as error:
        raise LineageError(LineageFailure.DECLARATION_INVALID, f"exposure/{chain.inventory_id} : {error}") from None


# Seules les défaillances de CONTENU (JSON, schéma, hash, nom, point fixe, identité, version, taille) font d'un A0 un orphelin consigné, comme
# dans B3 ; une erreur d'E/S, d'instabilité, d'absence tardive ou de structure (lien, non régulier) est un refus.
_STRUCTURE_FAILURES = {
    StoreFailure.UNREADABLE: LineageFailure.BAD_DIRECTORY, StoreFailure.UNSTABLE: LineageFailure.BAD_DIRECTORY,
    StoreFailure.ABSENT: LineageFailure.BAD_DIRECTORY, StoreFailure.BAD_DIRECTORY: LineageFailure.BAD_DIRECTORY,
    StoreFailure.LINK_OR_REPARSE_POINT: LineageFailure.LINK_OR_REPARSE_POINT, StoreFailure.NOT_REGULAR_FILE: LineageFailure.NOT_REGULAR,
}


def load_declaration_lineage(campaign_dir, *, current_inventory_id: str, campaign_id: str, pinned_a0_hashes: frozenset,
                             admitted_attestation: Optional[AttestationPin]) -> LoadedLineage:
    """Découvre et vérifie TOUTES les chaînes d'`<campaign_dir>/exposure/` (échec fermé, aucune réparation, rien n'est écrit) et, si
    l'inventaire courant est la chaîne terminale de la lignée, remet son `DeclarationSet`. `pinned_a0_hashes` : `inventory_content_hash`
    épinglés par une `ADMISSION` (fournis par l'appelant, JAMAIS facultatifs : un oubli désactiverait le refus). Un A0 épinglé illisible
    (`PINNED_A0_UNREADABLE`), ABSENT (`PINNED_A0_MISSING`) ou d'une autre campagne (`CAMPAIGN_MISMATCH`) refuse. Un A0 illisible dont le
    hash est CITÉ (toute fenêtre de 64 hexadécimaux, casse ignorée) dans une attestation pertinente est une référence NON RÉSOLUE, refusée
    (`A0_PIN_UNRESOLVED`) ; ce n'est jamais une preuve d'épinglage ni d'absence d'épinglage (23.31.3). `pinning` dit le niveau de preuve
    atteint ; l'évaluation des épinglages d'une attestation reste à E3-E et E3-J.

    `admitted_attestation` (JAMAIS facultatif) : `None` avant l'`ADMISSION` (tous les slots lus, candidat = plus haut slot de la chaîne
    terminale) ; après l'`ADMISSION`, l'attestation qu'elle épingle : seul ce slot est lu (absent : `ADMITTED_ATTESTATION_MISSING`, octets
    différents : `ADMITTED_ATTESTATION_REPLACED`) ; les slots de `seq` supérieur dans la même chaîne sont consignés `ATTESTATION_WITHOUT_EFFECT`,
    les autres `ATTESTATION_NOT_REREAD` (23.29.3, 23.31.4). Refus si l'attestation épinglée n'est pas dans la chaîne terminale
    (`ADMITTED_CHAIN_NOT_TERMINAL`) ou si l'inventaire courant n'est plus le sien (`ADMITTED_INVENTORY_CHANGED`) : changement d'exposition. La
    structure reste stricte. Le témoin d'admission vient de l'appelant et n'est PAS authentifié par B6 (voir `AttestationPin`).

    `campaign_id` : la campagne ATTENDUE par l'appelant (obligatoire). Seul compte, pour « un A0 de cet `inventory_id` existe avant la
    première déclaration », un A0 dont le contexte propre VALIDÉ (`own_context.current_campaign_id`, couvert par son hash) est cette
    campagne ; un A0 valide d'une autre campagne est écarté, consigné (`FOREIGN_CAMPAIGN_INVENTORY`) et jamais remis. Chaque déclaration
    de chaque chaîne, terminale ou historique, doit porter cette campagne dans son enveloppe (`CAMPAIGN_MISMATCH` sinon, 23.31.1). LIMITE :
    une lignée remise n'est PAS prouvée liée cryptographiquement à la campagne ; ces contrôles révèlent une COPIE, pas une falsification (un
    A0 ou une enveloppe se réécrivent sans secret avec un autre `campaign_id` et des hashs recalculés)."""
    _require_hex(current_inventory_id, "current_inventory_id")
    if type(campaign_id) is not str:
        raise TypeError("campaign_id doit être un texte.")
    if not campaign_id.strip():
        raise ValueError("campaign_id ne peut pas être vide.")
    if type(pinned_a0_hashes) is not frozenset:
        raise TypeError("pinned_a0_hashes doit être un frozenset.")
    for pinned in pinned_a0_hashes:
        _require_hex(pinned, "pinned_a0_hashes[]")
    if admitted_attestation is not None and type(admitted_attestation) is not AttestationPin:
        raise TypeError("admitted_attestation doit être None (avant l'ADMISSION) ou un AttestationPin.")
    phase = LineagePhase.PRE_ADMISSION if admitted_attestation is None else LineagePhase.POST_ADMISSION
    try:
        lstat_directory(campaign_dir, "campaign_dir")
    except ExposureStoreError as error:
        raise LineageError(LineageFailure.BAD_DIRECTORY, error.detail, error.failure) from None
    exposure = Path(campaign_dir) / "exposure"
    try:
        os.lstat(exposure)
    except FileNotFoundError:
        if admitted_attestation is not None:
            raise LineageError(LineageFailure.ADMITTED_ATTESTATION_MISSING, "exposure/ absent : l'attestation épinglée n'existe pas") from None
        if pinned_a0_hashes:
            raise LineageError(LineageFailure.PINNED_A0_MISSING, "exposure/ absent : les A0 épinglés n'existent pas") from None
        return LoadedLineage(current_inventory_id, campaign_id, LineageState.NO_LINEAGE, (), (), (), None, None, None, None, None, phase, None,
                             PinningReport((), (), False))
    except OSError as error:
        raise LineageError(LineageFailure.BAD_DIRECTORY, f"exposure/ inobservable : {error}") from None
    _checked_directory(exposure, "exposure/")
    budget, ignored = _Budget(), []
    a0_paths, directories = [], []
    for name, info in _list_directory(exposure, budget):
        if _A0_NAME_RE.fullmatch(name) is not None:
            if not stat.S_ISREG(info.st_mode):
                raise LineageError(LineageFailure.NOT_REGULAR, f"{name} n'est pas un fichier régulier")
            a0_paths.append((exposure / name, info.st_size))
        elif _ORPHAN_NAME_RE.fullmatch(name) is not None:
            if not stat.S_ISREG(info.st_mode):
                raise LineageError(LineageFailure.NOT_REGULAR, f"{name} n'est pas un fichier régulier")
            ignored.append(IgnoredEntry(IgnoredKind.PUBLICATION_ORPHAN, f"exposure/{name}"))
        elif _HEX64_RE.fullmatch(name) is not None and stat.S_ISDIR(info.st_mode):
            directories.append(name)
        else:
            raise LineageError(LineageFailure.UNKNOWN_ENTRY, f"exposure/{name} n'est pas un nom connu")
    valid, unreadable = [], {}
    for path, listed_size in a0_paths:
        try:
            valid.append(load_exposure_inventory(path, max_bytes=_read_cap(listed_size)))
        except ExposureStoreError as error:
            if _grown_since_listing(error, listed_size):                  # a grandi depuis le listage : instabilité, refus
                raise LineageError(LineageFailure.BAD_DIRECTORY, f"{path.name} a changé depuis le listage", StoreFailure.UNSTABLE) from None
            if error.failure in _STRUCTURE_FAILURES:                      # défaillance d'E/S ou de structure : refus, jamais un orphelin
                raise LineageError(_STRUCTURE_FAILURES[error.failure], f"{path.name} : {error.detail}", error.failure) from None
            unreadable[_A0_NAME_RE.fullmatch(path.name).group(1)] = error
            ignored.append(IgnoredEntry(IgnoredKind.UNREADABLE_INVENTORY, f"exposure/{path.name}",
                                        f"{error.failure.value} ; épinglage par attestation non évalué (E3-E/E3-J)"))
    inventories = [a0 for a0 in valid if a0.own_context.current_campaign_id == campaign_id]
    foreign = [a0 for a0 in valid if a0.own_context.current_campaign_id != campaign_id]
    ignored.extend(IgnoredEntry(IgnoredKind.FOREIGN_CAMPAIGN_INVENTORY, f"exposure/{a0.path.name}", a0.own_context.current_campaign_id)
                   for a0 in foreign)
    cited = set()
    chains = [chain for name in directories
              if (chain := _read_chain(exposure, name, campaign_id, admitted_attestation, budget, ignored, frozenset(unreadable),
                                       cited)) is not None]
    admitted_slot = None
    if admitted_attestation is not None:
        found = [slot for chain in chains for slot in chain.attestation_slots]
        if not found:
            raise LineageError(LineageFailure.ADMITTED_ATTESTATION_MISSING,
                               f"exposure/{admitted_attestation.inventory_id}/attestation_{admitted_attestation.seq:04d}.json est absente")
        (admitted_slot,) = found
    for bad_hash in sorted(unreadable):
        if bad_hash in pinned_a0_hashes:
            raise LineageError(LineageFailure.PINNED_A0_UNREADABLE, f"le A0 illisible {bad_hash[:12]}… est épinglé par l'ADMISSION",
                               unreadable[bad_hash].failure)
        if bad_hash in cited:
            raise LineageError(LineageFailure.A0_PIN_UNRESOLVED, f"le A0 illisible {bad_hash[:12]}… est cité par une attestation : "
                               "épinglage non résolu sans le schéma d'E3-E", unreadable[bad_hash].failure)
    pinning = PinningReport(tuple(sorted(pinned_a0_hashes)), tuple(sorted(unreadable)), False)
    own_hashes, foreign_hashes = ({a0.inventory_content_hash for a0 in group} for group in (inventories, foreign))
    for pinned in sorted(pinned_a0_hashes):
        if pinned in own_hashes or pinned in unreadable:
            continue
        if pinned in foreign_hashes:
            raise LineageError(LineageFailure.CAMPAIGN_MISMATCH, f"le A0 épinglé {pinned[:12]}… appartient à une autre campagne que {campaign_id!r}")
        raise LineageError(LineageFailure.PINNED_A0_MISSING, f"le A0 épinglé {pinned[:12]}… est absent d'exposure/")
    for chain in chains:
        first = chain.first
        if not any(a0.inventory_id == chain.inventory_id and a0.created_at <= first.created_at for a0 in inventories):
            if not any(a0.inventory_id == chain.inventory_id for a0 in inventories) and any(
                    a0.inventory_id == chain.inventory_id for a0 in foreign):
                raise LineageError(LineageFailure.CAMPAIGN_MISMATCH,
                                   f"exposure/{chain.inventory_id} : les seuls A0 de cet inventaire appartiennent à une autre campagne que {campaign_id!r}")
            raise LineageError(LineageFailure.A0_MISSING,
                               f"exposure/{chain.inventory_id} : aucun A0 valide de cet inventaire antérieur à sa première déclaration")
    if not chains:
        return LoadedLineage(current_inventory_id, campaign_id, LineageState.NO_LINEAGE, (), tuple(inventories), tuple(ignored), None, None, None,
                             None, None, phase, admitted_slot, pinning)
    ordered = _verify_lineage(chains)
    windows = {(a0.inventory.window_start_utc, a0.inventory.window_end_utc) for a0 in (_a0_of(inventories, c.inventory_id) for c in ordered)}
    if len(windows) > 1:                                                  # « W étant fixe pour une campagne » (23.29.2)
        raise LineageError(LineageFailure.WINDOW_NOT_FIXED, f"les inventaires de la lignée ont {len(windows)} fenêtres W distinctes")
    terminal = ordered[-1]
    by_id = {chain.inventory_id: chain for chain in ordered}
    if current_inventory_id not in by_id:
        state, declaration_set = LineageState.NO_CHAIN_FOR_CURRENT, None
    elif current_inventory_id != terminal.inventory_id:
        raise LineageError(LineageFailure.INVENTORY_REVERSION, f"l'inventaire courant {current_inventory_id[:12]}… correspond à une chaîne non terminale")
    else:
        declaration_set = _declaration_set(terminal)
        _check_declared_geometry(declaration_set, _a0_of(inventories, terminal.inventory_id), f"exposure/{terminal.inventory_id}")
        state = LineageState.CURRENT_IS_TERMINAL
    if admitted_attestation is not None and admitted_attestation.inventory_id != terminal.inventory_id:
        raise LineageError(LineageFailure.ADMITTED_CHAIN_NOT_TERMINAL, f"l'attestation épinglée est dans exposure/{admitted_attestation.inventory_id[:12]}… "
                           f"mais la chaîne terminale est {terminal.inventory_id[:12]}… : changement d'exposition après l'ADMISSION (23.29.3)")
    if admitted_attestation is not None and admitted_attestation.inventory_id != current_inventory_id:     # reste : courant sans chaîne, épinglage sur la terminale
        raise LineageError(LineageFailure.ADMITTED_INVENTORY_CHANGED, f"l'inventaire courant {current_inventory_id[:12]}… n'est pas celui de "
                           f"l'attestation épinglée ({admitted_attestation.inventory_id[:12]}…) : changement d'exposition après l'ADMISSION (23.29.3)")
    return LoadedLineage(current_inventory_id, campaign_id, state, tuple(ordered), tuple(inventories), tuple(ignored), declaration_set,
                         terminal.inventory_id, _lineage_digest(ordered), terminal.tip.declaration.declaration_seq, terminal.tip.content_hash,
                         phase, admitted_slot, pinning)


# ── Brouillon de report et lecture d'un slot d'attestation (jamais une publication) ──────────────────────────────────

@dataclass(frozen=True)
class CarryOverDraft:
    """Brouillon de la PREMIÈRE déclaration d'une nouvelle chaîne : épinglage du sommet terminal, expositions reprises (multiplicité
    conservée, renumérotées `declared:0001:<pos4>`) et plancher de `t_sel`. Rien n'est écrit ni publié ; le déclarant reste nominatif."""

    carried_from: Optional[CarriedFrom]
    declared_exposures: tuple
    minimum_t_sel_utc: Optional[str]
    campaign_id: str                      # campagne de la lignée relue : celle que l'enveloppe à publier devra porter (23.31.1)


def draft_first_declaration_carry(lineage: LoadedLineage, new_inventory_id: str) -> CarryOverDraft:
    """Pré-remplit le report cumulatif (23.29.2) vers un nouvel `inventory_id`. Sans lignée, il n'y a rien à reprendre (chaîne racine).
    Refus : `inventory_id` malformé, ayant déjà une chaîne (`INVENTORY_REVERSION`), ou plus de 9 999 expositions à reprendre
    (`CARRY_OVER_TOO_LARGE` : aucune troncature, aucune répartition sur plusieurs déclarations). La géométrie des expositions reprises n'est
    contrôlée contre `W` que si l'A0 du NOUVEL inventaire est déjà dans `lineage.inventories` ; sinon le contrôle est reporté à son chargement."""
    if type(lineage) is not LoadedLineage:
        raise TypeError("lineage doit être un LoadedLineage.")
    _require_hex(new_inventory_id, "new_inventory_id")
    if not lineage.chains:
        return CarryOverDraft(None, (), None, lineage.campaign_id)
    if any(chain.inventory_id == new_inventory_id for chain in lineage.chains):
        raise LineageError(LineageFailure.INVENTORY_REVERSION, "cet inventory_id a déjà une chaîne : un retour à un ancien inventaire est refusé")
    terminal = lineage.chains[-1]
    exposures = _declared_exposures(terminal)
    if len(exposures) > MAX_SEQ:
        raise LineageError(LineageFailure.CARRY_OVER_TOO_LARGE, f"{len(exposures)} expositions à reprendre > {MAX_SEQ}")
    renumbered = tuple(dataclasses.replace(finding, source_id=f"declared:0001:{position:04d}") for position, finding in enumerate(exposures, start=1))
    new_a0 = _a0_of(lineage.inventories, new_inventory_id)
    if new_a0 is not None and renumbered:                                  # la fenêtre du nouvel inventaire n'est connue que si son A0 existe
        draft = build_exposure_declaration(declaration_seq=1, declarant="brouillon", inventory_id=new_inventory_id,
                                           prev_declaration_id=None, declared_exposures=renumbered, declared_t_sel_utc=None,
                                           declared_trial_counts=None)
        _check_declared_geometry(_probe_declaration_set((draft,), True), new_a0, f"report vers exposure/{new_inventory_id}")
    tip = terminal.tip
    return CarryOverDraft(CarriedFrom(terminal.inventory_id, tip.declaration.declaration_seq, tip.declaration_id, tip.content_hash),
                          renumbered, _maximum_t_sel(terminal), lineage.campaign_id)


@dataclass(frozen=True)
class AttestationRead:
    file_sha256: str
    value: dict


def highest_attestation_slot(lineage: LoadedLineage) -> Optional[AttestationSlot]:
    """Le slot de plus haut `seq` du répertoire de la chaîne TERMINALE (23.29.3, avant l'`ADMISSION`), ou `None` (aussi quand l'inventaire courant
    n'est pas cette chaîne : son attestation est alors périmée). Aucun repli sur un slot
    antérieur : la fonction ne retourne jamais qu'UN slot, le plus haut, dont les octets ont déjà été prouvés par le chargeur (JSON strict,
    point fixe normatif, slots denses ; un seul slot invalide refuse toute la lignée). Elle n'ÉVALUE AUCUN épinglage (`inventory_content_hash`,
    sommet de chaîne, `declaration_lineage_digest`) : ils relèvent d'E3-E et d'E3-J ; elle ne dit donc jamais qu'une attestation est VALIDE."""
    if type(lineage) is not LoadedLineage:
        raise TypeError("lineage doit être un LoadedLineage.")
    if (lineage.phase is not LineagePhase.PRE_ADMISSION or lineage.state is not LineageState.CURRENT_IS_TERMINAL
            or not lineage.chains[-1].attestation_slots):
        return None
    return lineage.chains[-1].attestation_slots[-1]


def read_attestation_slot(campaign_dir, inventory_id: str, seq: int) -> AttestationRead:
    """Lecture stricte d'un slot d'attestation : octets UTF-8 sans BOM, JSON strict (clés dupliquées et constantes non finies refusées), objet,
    POINT FIXE d'octets de la sérialisation normative. Le schéma, les épinglages et la validité relèvent d'E3-E et d'E3-J : cette lecture
    ne PROUVE que l'intégrité des octets, jamais une attestation valide."""
    path = attestation_path(campaign_dir, inventory_id, seq)
    lstat_directory(campaign_dir, "campaign_dir")
    lstat_directory(Path(campaign_dir) / "exposure", "exposure/")
    raw = read_strict_file(path)
    value = parse_strict_record(raw)
    if type(value) is not dict:
        raise ExposureStoreError(StoreFailure.SCHEMA, "une attestation doit être un objet JSON")
    if _normative_bytes(value) != raw:
        raise ExposureStoreError(StoreFailure.NOT_FIXED_POINT, "les octets lus ne sont pas la sérialisation normative de l'attestation")
    return AttestationRead(hashlib.sha256(raw).hexdigest(), value)
