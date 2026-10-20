"""AF-V-07 Slice E3-D — modèle PUR des enregistrements du registre append-only des réservations et admissions (ADR 0025 Décision 23.10).

Aucune E/S, aucune horloge, aucun accès au marché. Les règles ACCEPTED (écrites dans l'ADR) et les choix PROPOSÉS (absents de l'ADR, nécessaires pour coder) sont
séparés dans `docs/adr/0025-proposal-E3D-REGISTRY-MATRIX-PROPOSED.md` ; chaque constante PROPOSÉE ci-dessous est nommée comme telle et peut changer sans toucher à la
logique. `REAL` reste DÉSACTIVÉ : ce module n'établit aucune preuve d'admission.

Un enregistrement est un `dict` JSON : clés EXACTES par type, types stricts (`type(x) is ...`), aucun flottant. L'ADMISSION porte `attestation_hash` et `authorization_hash`
(ACCEPTED, 23.10 : « hashs d'attestation et d'autorisation » ; ce que le hash d'attestation couvre reste à figer par F5 / E3-E, jamais interprété ici) et `attestation_observation`,
un conteneur OPAQUE borné (PROPOSÉ, P9, orientation F1 §0.3 non normative : plus haut slot d'attestation observé à l'ADMISSION) couvert par le hash du contenu sans être interprété.
Tout enregistrement valide tient dans `MAX_RECORD_BYTES` : l'écrivain ne peut pas produire un slot que le lecteur strict refuserait.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum

from atomic_json_store import NormativeJsonError, serialize_normative_json
from gate_v_campaign_plan_v2 import GATE_V_CAMPAIGN_ID_V2_PREFIX
from gate_v_final_holdout_protocol import normalize_utc_instant

# PROPOSÉ (P6) : l'ADR nomme le champ `admission_semantics_version` sans en fixer la valeur.
REGISTRY_RECORD_VERSION = "gate_v_registry_record_v1"
# ACCEPTED (23.10) : préfixe littéral de la valeur de genèse.
GENESIS_PREFIX = "gate_v_registry_genesis:"
# PROPOSÉ (P1) : largeur du numéro de slot ; l'ADR dit `admission_<seq>.json`.
SLOT_DIGITS = 6
MAX_SEQ = 10 ** SLOT_DIGITS - 1
# PROPOSÉ (P8) : plafonds provisoires (aucune valeur dans l'ADR).
MAX_OPAQUE_DEPTH = 8
MAX_OPAQUE_BYTES = 16384          # taille JSON normative du conteneur opaque
MAX_RECORD_BYTES = 65536          # taille JSON normative d'un enregistrement complet ; DOIT rester <= au plafond de lecture du store
MAX_SHORT_TEXT = 256
MAX_LONG_TEXT = 4096

_SLOT_NAME_RE = re.compile(r"admission_([0-9]{%d})\.json" % SLOT_DIGITS)
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_INSTANCE_ID_RE = re.compile(r"[0-9a-f]{32}")                      # PROPOSÉ (P4)
_REGISTRY_ID_RE = re.compile(r"[A-Za-z0-9_.-]{1,128}")             # PROPOSÉ (P4)
_CAMPAIGN_ID_RE = re.compile(re.escape(GATE_V_CAMPAIGN_ID_V2_PREFIX) + r"[0-9a-f]{64}")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


class RecordType(str, Enum):
    """ACCEPTED (23.10) : les quatre types d'enregistrement."""

    RESERVATION = "RESERVATION"
    ADMISSION = "ADMISSION"
    CONSUMPTION = "CONSUMPTION"
    REBIND = "REBIND"


class RegistryMode(str, Enum):
    """ACCEPTED (23.9) : `identity.json` porte un mode. Seul `SYNTHETIC` est implémenté ; `REAL` est DÉSACTIVÉ (23.2) et refusé partout."""

    SYNTHETIC = "SYNTHETIC"
    REAL = "REAL"


COMMON_FIELDS = ("admission_semantics_version", "registry_id", "instance_id", "seq", "prev_content_hash", "record_type", "created_at")
CAMPAIGN_FIELDS = ("campaign_id", "window_start_utc", "window_end_utc", "commitment_id", "commitment_content_hash", "code_identity_hash", "campaign_dir_locator")
OPAQUE_FIELDS = ("attestation_observation",)

RECORD_FIELDS = {
    RecordType.RESERVATION: (*COMMON_FIELDS, *CAMPAIGN_FIELDS, "static_sources_digest"),
    RecordType.ADMISSION: (*COMMON_FIELDS, *CAMPAIGN_FIELDS, "static_sources_digest", "overlap_projection_hash", "reservation_content_hash", "reservation_seq",
                           "attachment_id", "attachment_content_hash", "time_proof_content_hash", "attestation_hash", "authorization_hash", *OPAQUE_FIELDS),
    RecordType.CONSUMPTION: (*COMMON_FIELDS, *CAMPAIGN_FIELDS, "claim_id", "claim_content_hash", "admission_content_hash"),
    RecordType.REBIND: (*COMMON_FIELDS, "old_binding_hash", "new_binding_hash", "restored_head_seq", "restored_head_content_hash", "justification"),
}
CAMPAIGN_RECORD_TYPES = frozenset({RecordType.RESERVATION, RecordType.ADMISSION, RecordType.CONSUMPTION})

# ACCEPTED (23.10) : `admission_id` = hash sémantique SANS ces cinq champs.
_ADMISSION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "campaign_dir_locator", "reservation_seq", "created_at"})
_RESERVATION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "campaign_dir_locator", "created_at"})        # PROPOSÉ (P19)

_HEX64_FIELDS = frozenset({
    "prev_content_hash", "commitment_content_hash", "code_identity_hash", "static_sources_digest", "overlap_projection_hash", "reservation_content_hash",
    "attachment_content_hash", "time_proof_content_hash", "claim_id", "claim_content_hash", "admission_content_hash", "old_binding_hash", "new_binding_hash",
    "restored_head_content_hash", "attestation_hash", "authorization_hash"})
_SHORT_TEXT_FIELDS = frozenset({"commitment_id", "attachment_id"})
_LONG_TEXT_FIELDS = frozenset({"campaign_dir_locator", "justification"})


def _require_text(value: object, name: str, *, maximum: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum or _CONTROL_CHAR_RE.search(value):
        raise ValueError(f"{name} doit être un texte non vide de {maximum} caractères au plus, sans caractère de contrôle.")
    return value


def _require_hex64(value: object, name: str) -> str:
    if type(value) is not str or _HEX64_RE.fullmatch(value) is None:
        raise ValueError(f"{name} doit être un SHA-256 hexadécimal minuscule (64 caractères).")
    return value


def _require_seq(value: object, name: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SEQ:
        raise ValueError(f"{name} doit être un entier (non booléen) entre 0 et {MAX_SEQ}.")
    return value


def _require_instant(value: object, name: str) -> str:
    """Un instant DÉJÀ normalisé (`YYYY-MM-DDTHH:MM:SS.ffffffZ`, UTC) : chronologie = ordre lexicographique."""
    if type(value) is not str:
        raise ValueError(f"{name} doit être un instant UTC normalisé de type str.")
    try:
        normalized = normalize_utc_instant(value)
    except ValueError as error:
        raise ValueError(f"{name} : {error}") from error
    if normalized != value:
        raise ValueError(f"{name} doit être sous forme normalisée UTC (YYYY-MM-DDTHH:MM:SS.ffffffZ).")
    return value


def _exceeds_depth(value: object, limit: int) -> bool:
    """Parcours ITÉRATIF (aucune récursion Python : une imbrication hostile ne peut pas lever `RecursionError`) ; vrai dès qu'un conteneur dépasse `limit` niveaux."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if type(item) is dict:
            children = item.values()
        elif type(item) is list:
            children = item
        else:
            continue
        if depth > limit:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


def _require_opaque(value: object, name: str) -> dict:
    if type(value) is not dict or not value:
        raise ValueError(f"{name} doit être un objet JSON non vide (conteneur opaque).")
    if _exceeds_depth(value, MAX_OPAQUE_DEPTH):             # AVANT toute sérialisation récursive
        raise ValueError(f"{name} : imbrication supérieure à {MAX_OPAQUE_DEPTH}.")
    try:
        size = len(serialize_normative_json(value))
    except NormativeJsonError as error:
        raise ValueError(f"{name} : {error}") from error
    if size > MAX_OPAQUE_BYTES:
        raise ValueError(f"{name} : {size} octets, au plus {MAX_OPAQUE_BYTES}.")
    return value


def genesis_prev_content_hash(instance_id: object) -> str:
    """ACCEPTED (23.10) : `prev_content_hash` du slot 0 = SHA-256 de la chaîne UTF-8 `"gate_v_registry_genesis:" + instance_id`."""
    if type(instance_id) is not str or _INSTANCE_ID_RE.fullmatch(instance_id) is None:
        raise ValueError("instance_id doit être 32 caractères hexadécimaux minuscules.")
    return hashlib.sha256((GENESIS_PREFIX + instance_id).encode("utf-8")).hexdigest()


def validate_registry_id(value: object) -> str:
    if type(value) is not str or _REGISTRY_ID_RE.fullmatch(value) is None:
        raise ValueError("registry_id : identifiant ASCII [A-Za-z0-9_.-] de 1 à 128 caractères attendu.")
    return value


def validate_campaign_id(value: object) -> str:
    if type(value) is not str or _CAMPAIGN_ID_RE.fullmatch(value) is None:
        raise ValueError(f"campaign_id doit avoir la forme {GATE_V_CAMPAIGN_ID_V2_PREFIX!r} + 64 hexadécimaux minuscules.")
    return value


def validate_instance_id(value: object) -> str:
    if type(value) is not str or _INSTANCE_ID_RE.fullmatch(value) is None:
        raise ValueError("instance_id doit être 32 caractères hexadécimaux minuscules.")
    return value


def slot_file_name(seq: object) -> str:
    return f"admission_{_require_seq(seq, 'seq'):0{SLOT_DIGITS}d}.json"


def parse_slot_file_name(name: object):
    """Le numéro d'un nom de slot EXACT, sinon `None` (aucune tolérance de casse, de largeur ni de suffixe)."""
    if type(name) is not str:
        return None
    match = _SLOT_NAME_RE.fullmatch(name)
    return None if match is None else int(match.group(1))


def windows_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    """ACCEPTED (23.10) : `a.start < b.end ∧ b.start < a.end`, fenêtres semi-ouvertes. Instants normalisés exigés."""
    start_a, end_a = _require_instant(start_a, "start_a"), _require_instant(end_a, "end_a")
    start_b, end_b = _require_instant(start_b, "start_b"), _require_instant(end_b, "end_b")
    return start_a < end_b and start_b < end_a


def validate_registry_record(record: object) -> RecordType:
    """Validation STRICTE et pure d'un enregistrement ; retourne son type. `ValueError` pour toute anomalie ; ne modifie jamais `record`."""
    if type(record) is not dict:
        raise ValueError("enregistrement : objet JSON (dict exact) attendu.")
    type_value = record.get("record_type")
    if type(type_value) is not str:
        raise ValueError("record_type doit être un str.")
    try:
        record_type = RecordType(type_value)
    except ValueError:
        raise ValueError(f"record_type inconnu : {type_value!r}.") from None
    expected = RECORD_FIELDS[record_type]
    unknown, missing = sorted(set(record) - set(expected), key=str), sorted(set(expected) - set(record))
    if unknown or missing:
        raise ValueError(f"{record_type.value} : clés inconnues {unknown} ; clés manquantes {missing}.")
    if record["admission_semantics_version"] != REGISTRY_RECORD_VERSION or type(record["admission_semantics_version"]) is not str:
        raise ValueError(f"admission_semantics_version inconnue : attendu {REGISTRY_RECORD_VERSION!r}.")
    if type(record["registry_id"]) is not str or _REGISTRY_ID_RE.fullmatch(record["registry_id"]) is None:
        raise ValueError("registry_id : identifiant ASCII [A-Za-z0-9_.-] de 1 à 128 caractères attendu.")
    if type(record["instance_id"]) is not str or _INSTANCE_ID_RE.fullmatch(record["instance_id"]) is None:
        raise ValueError("instance_id doit être 32 caractères hexadécimaux minuscules.")
    _require_seq(record["seq"], "seq")
    _require_instant(record["created_at"], "created_at")
    for name in expected:
        value = record[name]
        if name in _HEX64_FIELDS:
            _require_hex64(value, name)
        elif name in _SHORT_TEXT_FIELDS:
            _require_text(value, name, maximum=MAX_SHORT_TEXT)
        elif name in _LONG_TEXT_FIELDS:
            _require_text(value, name, maximum=MAX_LONG_TEXT)
        elif name in OPAQUE_FIELDS:
            _require_opaque(value, name)
    if record_type in CAMPAIGN_RECORD_TYPES:
        if type(record["campaign_id"]) is not str or _CAMPAIGN_ID_RE.fullmatch(record["campaign_id"]) is None:
            raise ValueError(f"campaign_id doit avoir la forme {GATE_V_CAMPAIGN_ID_V2_PREFIX!r} + 64 hexadécimaux minuscules.")
        start, end = _require_instant(record["window_start_utc"], "window_start_utc"), _require_instant(record["window_end_utc"], "window_end_utc")
        if not start < end:
            raise ValueError("la fenêtre doit avoir une durée strictement positive (window_start_utc < window_end_utc).")
    if record_type is RecordType.ADMISSION:
        _require_seq(record["reservation_seq"], "reservation_seq")
    if record_type is RecordType.REBIND:
        _require_seq(record["restored_head_seq"], "restored_head_seq")
        if record["old_binding_hash"] == record["new_binding_hash"]:    # PROPOSÉ (P16)
            raise ValueError("REBIND : old_binding_hash et new_binding_hash doivent différer.")
    try:
        size = len(serialize_normative_json(record))       # aucun flottant, tuple ni sous-classe, aucun substitut isolé
    except NormativeJsonError as error:
        raise ValueError(f"enregistrement hors du JSON normatif : {error}") from error
    if size > MAX_RECORD_BYTES:
        raise ValueError(f"enregistrement de {size} octets : au plus {MAX_RECORD_BYTES} (le lecteur strict doit pouvoir le relire).")
    return record_type


def serialize_for_slot(record: dict) -> bytes:
    """Les octets EXACTS qui seront publiés pour `record` (JSON normatif d'E3-C), après validation complète. Source unique des octets d'un slot."""
    validate_registry_record(record)
    return serialize_normative_json(record)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def compute_record_content_hash(record: dict) -> str:
    """ACCEPTED (23.10) : SHA-256 du JSON canonique (Décision 20.3, compact) de l'enregistrement COMPLET, `seq`, `prev_content_hash` et `created_at` inclus. Pour une
    `RESERVATION`, c'est `reservation_content_hash` ; pour une `ADMISSION`, `admission_content_hash` (PROPOSÉ P11 : c'est la même formule)."""
    validate_registry_record(record)
    return hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()


def compute_reservation_semantic_id(record: dict) -> str:
    """PROPOSÉ (P19) : identité sémantique d'une `RESERVATION` (l'ADR parle de « contenu sémantique identique » sans la définir) : même règle que `admission_id`, c'est-à-dire sans
    `seq`, `prev_content_hash`, `created_at` ni `campaign_dir_locator`. Sert uniquement à décider si une RESERVATION existante peut être RELUE et réutilisée sans rien publier."""
    if validate_registry_record(record) is not RecordType.RESERVATION:
        raise ValueError("compute_reservation_semantic_id attend une RESERVATION.")
    semantic = {name: value for name, value in record.items() if name not in _RESERVATION_ID_EXCLUDED}
    return hashlib.sha256(_canonical_json(semantic).encode("utf-8")).hexdigest()


def compute_admission_id(record: dict) -> str:
    """ACCEPTED (23.10) : hash sémantique d'une `ADMISSION`, SANS `seq`, `prev_content_hash`, `campaign_dir_locator`, `reservation_seq` ni `created_at`."""
    if validate_registry_record(record) is not RecordType.ADMISSION:
        raise ValueError("compute_admission_id attend une ADMISSION.")
    semantic = {name: value for name, value in record.items() if name not in _ADMISSION_ID_EXCLUDED}
    return hashlib.sha256(_canonical_json(semantic).encode("utf-8")).hexdigest()
