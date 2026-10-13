"""Modèles purs et classification d'exposition — AF-V-07 Slice E3-A (ADR 0025, Décision 23.27 et 23.28).

Cœur strictement PUR : types immuables, invariants, classification déterministe, identités SHA-256 et refus
de classification. Aucune lecture de fichier, aucun registre, aucune horloge, aucun moteur, aucun Claim, aucune
donnée de marché, aucune persistance, aucun appel à E1/E2. Bibliothèque standard uniquement.

Instancier ou classifier ici n'autorise AUCUN accès au FINAL_HOLDOUT : un tuple de refus vide n'est jamais une
autorisation (l'autorité d'exclusivité est le registre, 23.10, et la création exclusive du Claim, E2).
Les verdicts de recouvrement, les étages réels, la durabilité et les preuves de temps sont des FAITS fournis par
l'appelant (E3-B, E3-D, E3-E, E3-J) ; ce module ne les établit jamais.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

# ============================================================================================
# Énumérations fermées (11)
# ============================================================================================


class ExposureClass(str, Enum):
    FRESH_UNEXPOSED_DECLARED = "FRESH_UNEXPOSED_DECLARED"
    RETROSPECTIVE_EXPOSED = "RETROSPECTIVE_EXPOSED"
    UNDETERMINED = "UNDETERMINED"


class ChronologyLevel(str, Enum):
    PROSPECTIVE_ANCHORED = "PROSPECTIVE_ANCHORED"
    UNSEEN_HISTORICAL = "UNSEEN_HISTORICAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class OverlapVerdict(str, Enum):
    OVERLAPS = "OVERLAPS"
    NO_OVERLAP = "NO_OVERLAP"
    UNKNOWN = "UNKNOWN"


class SourceStatus(str, Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


class SourceKind(str, Enum):
    # 8 sources exposantes (une donnée a été, ou est déclarée avoir été, lue)
    HOLDOUT_ACCESS_EVENT = "HOLDOUT_ACCESS_EVENT"
    VALIDATION_RUN_OOS = "VALIDATION_RUN_OOS"
    JOB_EXECUTION = "JOB_EXECUTION"
    V1_CAMPAIGN_OOS = "V1_CAMPAIGN_OOS"
    FINAL_HOLDOUT_CLAIM = "FINAL_HOLDOUT_CLAIM"
    CONSUMPTION = "CONSUMPTION"
    READ_INTENT = "READ_INTENT"
    DECLARED_UNRECORDED_WORK = "DECLARED_UNRECORDED_WORK"
    # 2 enregistrements du registre non exposants (aucune donnée lue)
    REGISTRY_RESERVATION = "REGISTRY_RESERVATION"
    REGISTRY_ADMISSION = "REGISTRY_ADMISSION"
    # 2 sources de capacité inconnue : jamais RESOLVED
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
    REGISTRY_UNREADABLE = "REGISTRY_UNREADABLE"

    @property
    def exposes_data(self) -> bool:
        return self in _EXPOSING_KINDS

    @property
    def capability_unknown(self) -> bool:
        return self in _UNKNOWN_CAPABILITY_KINDS


_EXPOSING_KINDS = frozenset({
    SourceKind.HOLDOUT_ACCESS_EVENT, SourceKind.VALIDATION_RUN_OOS, SourceKind.JOB_EXECUTION,
    SourceKind.V1_CAMPAIGN_OOS, SourceKind.FINAL_HOLDOUT_CLAIM, SourceKind.CONSUMPTION,
    SourceKind.READ_INTENT, SourceKind.DECLARED_UNRECORDED_WORK,
})
_UNKNOWN_CAPABILITY_KINDS = frozenset({SourceKind.UNKNOWN_SOURCE, SourceKind.REGISTRY_UNREADABLE})


class UnresolvedCause(str, Enum):
    UNREADABLE = "UNREADABLE"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    UNKNOWN_SCHEMA_VERSION = "UNKNOWN_SCHEMA_VERSION"
    WINDOW_UNKNOWN = "WINDOW_UNKNOWN"
    TIMEZONE_UNKNOWN = "TIMEZONE_UNKNOWN"
    PLAN_UNRESOLVED = "PLAN_UNRESOLVED"
    UNKNOWN_SOURCE_TYPE = "UNKNOWN_SOURCE_TYPE"


class ConditionStatus(str, Enum):
    MET = "MET"
    NOT_MET = "NOT_MET"
    UNVERIFIED = "UNVERIFIED"


class TimeProofStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNVERIFIABLE = "UNVERIFIABLE"
    ABSENT = "ABSENT"


class ReasonCode(str, Enum):
    # 7 codes de niveau classe
    EXPOSURE_ESTABLISHED_INVENTORY = "EXPOSURE_ESTABLISHED_INVENTORY"
    EXPOSURE_ESTABLISHED_DECLARED = "EXPOSURE_ESTABLISHED_DECLARED"
    UNRESOLVED_SOURCE = "UNRESOLVED_SOURCE"
    INVENTORY_INCOMPLETE = "INVENTORY_INCOMPLETE"
    T_SEL_LOWERING_IGNORED = "T_SEL_LOWERING_IGNORED"
    OVERLAPPING_REGISTRATION = "OVERLAPPING_REGISTRATION"
    OWN_REGISTRATION_ANOMALY = "OWN_REGISTRATION_ANOMALY"
    # 25 codes de conditions F1..F6
    F1_EXPOSURE_ESTABLISHED = "F1_EXPOSURE_ESTABLISHED"
    F1_SOURCES_UNRESOLVED = "F1_SOURCES_UNRESOLVED"
    F1_INVENTORY_INCOMPLETE = "F1_INVENTORY_INCOMPLETE"
    F1_OWN_ANOMALY = "F1_OWN_ANOMALY"
    F2_EXPOSURE_WINDOW_UNKNOWN = "F2_EXPOSURE_WINDOW_UNKNOWN"
    F2_T_SEL_MISSING = "F2_T_SEL_MISSING"
    F2_ANCHOR_UNKNOWN = "F2_ANCHOR_UNKNOWN"
    F2_EXPOSURE_AFTER_WS = "F2_EXPOSURE_AFTER_WS"
    F2_T_SEL_AFTER_WS = "F2_T_SEL_AFTER_WS"
    F2_T_SEL_AFTER_ANCHOR = "F2_T_SEL_AFTER_ANCHOR"
    F3_S0_MAX_TIME_MISSING = "F3_S0_MAX_TIME_MISSING"
    F3_S0_NOT_BEFORE_WINDOW = "F3_S0_NOT_BEFORE_WINDOW"
    F4_RESERVATION_UNKNOWN = "F4_RESERVATION_UNKNOWN"
    F4_RESERVATION_NOT_DURABLE = "F4_RESERVATION_NOT_DURABLE"
    F4_PROOF_ABSENT = "F4_PROOF_ABSENT"
    F4_PROOF_UNVERIFIABLE = "F4_PROOF_UNVERIFIABLE"
    F4_PROOF_INVALID = "F4_PROOF_INVALID"
    F4_PROOF_NOT_OWN_RESERVATION = "F4_PROOF_NOT_OWN_RESERVATION"
    F4_MARGIN_MISSING = "F4_MARGIN_MISSING"
    F4_MARGIN_NOT_POSITIVE = "F4_MARGIN_NOT_POSITIVE"
    F4_ANCHORED_TOO_LATE = "F4_ANCHORED_TOO_LATE"
    F5_INGESTION_MISSING = "F5_INGESTION_MISSING"
    F5_INGESTED_BEFORE_WINDOW_END = "F5_INGESTED_BEFORE_WINDOW_END"
    F5_RANGE_MISMATCH = "F5_RANGE_MISMATCH"
    F6_HASH_LINK_BROKEN = "F6_HASH_LINK_BROKEN"


class AdmissionRefusal(str, Enum):
    CLASS_RETROSPECTIVE_EXPOSED = "CLASS_RETROSPECTIVE_EXPOSED"
    CLASS_UNDETERMINED = "CLASS_UNDETERMINED"
    LEVEL_NOT_PROSPECTIVE_ANCHORED = "LEVEL_NOT_PROSPECTIVE_ANCHORED"
    OVERLAPPING_REGISTRATION = "OVERLAPPING_REGISTRATION"


class OwnRecordStage(str, Enum):
    NO_OWN_RECORDS = "NO_OWN_RECORDS"
    RESERVED = "RESERVED"
    ADMITTED = "ADMITTED"
    CLAIMED = "CLAIMED"
    CONSUMED = "CONSUMED"


# ============================================================================================
# Instants UTC normalisés
# ============================================================================================

# Instant ISO-8601 AVEC fuseau explicite (Z ou ±HH:MM), chiffres ASCII uniquement.
_AWARE_INSTANT_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


def _parse_aware(value: str) -> datetime:
    """Parse une chaîne ISO-8601 avec fuseau explicite ; `ValueError` si le format ou l'instant est invalide."""
    if _AWARE_INSTANT_RE.fullmatch(value) is None:
        raise ValueError("Instant invalide : ISO-8601 avec heure, secondes et fuseau explicite (Z ou ±HH:MM) requis.")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        instant = datetime.fromisoformat(text)
        return instant.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError("Instant invalide : valeur calendaire ou fuseau impossible.") from exc


def normalize_utc_instant(value: str) -> str:
    """Normalise un instant ISO-8601 aware en `YYYY-MM-DDTHH:MM:SS.ffffffZ` (UTC, fraction fixe de 6 chiffres).
    `TypeError` si `value` n'est pas exactement un `str` ; `ValueError` si l'instant est naïf ou invalide."""
    if type(value) is not str:
        raise TypeError("normalize_utc_instant attend exactement un str.")
    return _parse_aware(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


# ============================================================================================
# Validateurs privés (conventions d'E1 : `type(x) is ...` strict, ValueError pour une valeur invalide)
# ============================================================================================

_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")
_DECLARED_PREFIX = "declared:"
_MISSING_PREFIX = "missing:"


def _require_str(value: object, name: str) -> str:
    # `type() is str` délibéré : bool, int, None, bytes et sous-classes de str ne sont pas du JSON normatif.
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} doit être une chaîne non vide de type str.")
    return value


def _require_optional_str(value: object, name: str) -> Optional[str]:
    return None if value is None else _require_str(value, name)


def _require_hex64(value: object, name: str) -> str:
    if type(value) is not str or _SHA256_HEX_RE.fullmatch(value) is None:
        raise ValueError(f"{name} doit être un SHA-256 hexadécimal minuscule (64 caractères).")
    return value


def _require_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} doit être un bool.")
    return value


def _require_optional_bool(value: object, name: str) -> Optional[bool]:
    return None if value is None else _require_bool(value, name)


def _require_int(value: object, name: str, *, minimum: int) -> int:
    # `bool` est une sous-classe de `int` : refusé explicitement par `type() is int`.
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} doit être un entier (non booléen) >= {minimum}.")
    return value


def _require_enum(value: object, enum_cls: type, name: str):
    if type(value) is not enum_cls:
        raise ValueError(f"{name} doit être un membre de {enum_cls.__name__}.")
    return value


def _require_instant(value: object, name: str) -> str:
    """Un instant DÉJÀ normalisé (forme `YYYY-MM-DDTHH:MM:SS.ffffffZ`) : le constructeur direct ne normalise pas."""
    if type(value) is not str:
        raise ValueError(f"{name} doit être un instant UTC normalisé de type str.")
    try:
        normalized = normalize_utc_instant(value)
    except ValueError as exc:
        raise ValueError(f"{name} : {exc}") from exc
    if normalized != value:
        raise ValueError(f"{name} doit être sous forme normalisée UTC (YYYY-MM-DDTHH:MM:SS.ffffffZ).")
    return value


def _require_optional_instant(value: object, name: str) -> Optional[str]:
    return None if value is None else _require_instant(value, name)


def _instant(value: str) -> datetime:
    return _parse_aware(value)


# ============================================================================================
# TrialAccounting
# ============================================================================================

_TRIAL_ACCOUNTING_FIELDS = (
    "research_runs", "strategies", "campaigns", "abandoned_reservations", "failed_ingestion_attempts",
    "void_commitments",
)


@dataclass(frozen=True)
class TrialAccounting:
    """Comptabilité des essais (23.27.5) : six compteurs entiers >= 0. Non décisionnelle pour la classe."""

    research_runs: int
    strategies: int
    campaigns: int
    abandoned_reservations: int
    failed_ingestion_attempts: int
    void_commitments: int

    def __post_init__(self) -> None:
        for name in _TRIAL_ACCOUNTING_FIELDS:
            _require_int(getattr(self, name), name, minimum=0)


# ============================================================================================
# ExposureFinding
# ============================================================================================

# Les cinq types d'enregistrement de campagne : `campaign_id` requis s'ils sont RESOLVED (23.27.2).
_CAMPAIGN_RECORD_KINDS = frozenset({
    SourceKind.REGISTRY_RESERVATION, SourceKind.REGISTRY_ADMISSION, SourceKind.FINAL_HOLDOUT_CLAIM,
    SourceKind.CONSUMPTION, SourceKind.READ_INTENT,
})


@dataclass(frozen=True)
class ExposureFinding:
    """Une source de l'inventaire ou une exposition déclarée (10 champs). Le verdict de recouvrement est un FAIT
    calculé hors de ce module (E3-B) ; `snapshot_id` est informatif et n'est jamais lu par la décision."""

    source_id: str
    source_kind: SourceKind
    status: SourceStatus
    overlap: OverlapVerdict
    content_hash: Optional[str]
    window_start_utc: Optional[str]
    window_end_utc: Optional[str]
    snapshot_id: Optional[str]
    campaign_id: Optional[str]
    unresolved_cause: Optional[UnresolvedCause]

    def __post_init__(self) -> None:
        _require_str(self.source_id, "source_id")
        _require_enum(self.source_kind, SourceKind, "source_kind")
        _require_enum(self.status, SourceStatus, "status")
        _require_enum(self.overlap, OverlapVerdict, "overlap")
        if self.content_hash is not None:
            _require_hex64(self.content_hash, "content_hash")
        _require_optional_instant(self.window_start_utc, "window_start_utc")
        _require_optional_instant(self.window_end_utc, "window_end_utc")
        _require_optional_str(self.snapshot_id, "snapshot_id")
        _require_optional_str(self.campaign_id, "campaign_id")
        if self.unresolved_cause is not None:
            _require_enum(self.unresolved_cause, UnresolvedCause, "unresolved_cause")

        if self.source_id.startswith(_MISSING_PREFIX):
            raise ValueError(f"source_id : le préfixe {_MISSING_PREFIX!r} est réservé aux identifiants d'anomalie.")
        declared_kind = self.source_kind is SourceKind.DECLARED_UNRECORDED_WORK
        if declared_kind != self.source_id.startswith(_DECLARED_PREFIX):
            raise ValueError(
                f"source_id : le préfixe {_DECLARED_PREFIX!r} est réservé aux expositions déclarées "
                "(et celles-ci l'exigent)."
            )
        if (self.window_start_utc is None) != (self.window_end_utc is None):
            raise ValueError("Les deux bornes de fenêtre doivent être présentes ensemble ou absentes ensemble.")
        if self.window_start_utc is not None and not _instant(self.window_start_utc) < _instant(self.window_end_utc):
            raise ValueError("La fenêtre doit vérifier début < fin.")

        if self.status is SourceStatus.RESOLVED:
            if self.source_kind.capability_unknown:
                raise ValueError(f"{self.source_kind.value} ne peut jamais être RESOLVED.")
            if self.overlap is OverlapVerdict.UNKNOWN:
                raise ValueError("Une source RESOLVED exige un verdict de recouvrement connu.")
            if self.window_start_utc is None:
                raise ValueError("Une source RESOLVED exige une fenêtre complète.")
            if self.unresolved_cause is not None:
                raise ValueError("Une source RESOLVED n'a pas de cause de non-résolution.")
            if declared_kind:
                if self.content_hash is not None:
                    raise ValueError("DECLARED_UNRECORDED_WORK n'a pas de content_hash.")
            elif self.content_hash is None:
                raise ValueError("Une source RESOLVED exige un content_hash SHA-256.")
            if self.source_kind in _CAMPAIGN_RECORD_KINDS and self.campaign_id is None:
                raise ValueError("campaign_id est requis pour un enregistrement de campagne RESOLVED.")
        else:
            if self.overlap is not OverlapVerdict.UNKNOWN:
                raise ValueError("Une source UNRESOLVED exige le verdict UNKNOWN.")
            if self.unresolved_cause is None:
                raise ValueError("Une source UNRESOLVED exige une cause.")
            if declared_kind and self.content_hash is not None:
                raise ValueError("DECLARED_UNRECORDED_WORK n'a pas de content_hash.")


def build_exposure_finding(
    *,
    source_id: str,
    source_kind: SourceKind,
    status: SourceStatus,
    overlap: OverlapVerdict,
    content_hash: Optional[str] = None,
    window_start_utc: Optional[str] = None,
    window_end_utc: Optional[str] = None,
    snapshot_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    unresolved_cause: Optional[UnresolvedCause] = None,
) -> ExposureFinding:
    """Construit un `ExposureFinding` en normalisant les instants (offsets acceptés, naïfs refusés)."""
    return ExposureFinding(
        source_id=source_id,
        source_kind=source_kind,
        status=status,
        overlap=overlap,
        content_hash=content_hash,
        window_start_utc=None if window_start_utc is None else normalize_utc_instant(window_start_utc),
        window_end_utc=None if window_end_utc is None else normalize_utc_instant(window_end_utc),
        snapshot_id=snapshot_id,
        campaign_id=campaign_id,
        unresolved_cause=unresolved_cause,
    )


# ============================================================================================
# ExposureInventory
# ============================================================================================

EXPOSURE_INVENTORY_SEMANTICS_VERSION = "gate_v_exposure_inventory_v1"


def _require_tuple(value: object, name: str) -> tuple:
    if type(value) is not tuple:
        raise ValueError(f"{name} doit être un tuple (collection immuable).")
    return value


def _windows_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    """Recouvrement de deux fenêtres semi-ouvertes `[début, fin)` : `a.début < b.fin ET b.début < a.fin`.
    Formule PRIVÉE : elle contrôle la cohérence des verdicts fournis, elle ne les calcule jamais (E3-B)."""
    return _instant(start_a) < _instant(end_b) and _instant(start_b) < _instant(end_a)


def _check_overlap_geometry(finding: ExposureFinding, window_start_utc: str, window_end_utc: str) -> None:
    """Un verdict RESOLVED qui contredit les fenêtres est refusé (`ValueError`)."""
    if finding.status is not SourceStatus.RESOLVED:
        return
    geometric = _windows_overlap(finding.window_start_utc, finding.window_end_utc, window_start_utc, window_end_utc)
    if geometric != (finding.overlap is OverlapVerdict.OVERLAPS):
        raise ValueError(f"Le verdict de recouvrement de {finding.source_id!r} contredit les fenêtres.")


@dataclass(frozen=True)
class ExposureInventory:
    """Inventaire A0 : sources trouvées dans les racines d'audit STATIQUES (`scanned_roots`), triées par
    `source_id`. `complete` et les verdicts de recouvrement sont des faits fournis (E3-B), jamais calculés ici."""

    version: str
    window_start_utc: str
    window_end_utc: str
    findings: tuple
    complete: bool
    scanned_roots: tuple
    trial_accounting: TrialAccounting

    def __post_init__(self) -> None:
        if self.version != EXPOSURE_INVENTORY_SEMANTICS_VERSION:
            raise ValueError(f"version inconnue : attendu {EXPOSURE_INVENTORY_SEMANTICS_VERSION!r}.")
        _require_instant(self.window_start_utc, "window_start_utc")
        _require_instant(self.window_end_utc, "window_end_utc")
        if not _instant(self.window_start_utc) < _instant(self.window_end_utc):
            raise ValueError("La fenêtre W doit vérifier début < fin.")
        _require_tuple(self.findings, "findings")
        for finding in self.findings:
            if type(finding) is not ExposureFinding:
                raise ValueError("findings ne contient que des ExposureFinding.")
            if finding.source_kind is SourceKind.DECLARED_UNRECORDED_WORK:
                raise ValueError("DECLARED_UNRECORDED_WORK est interdit dans l'inventaire (déclarations seulement).")
            _check_overlap_geometry(finding, self.window_start_utc, self.window_end_utc)
        ids = [finding.source_id for finding in self.findings]
        if ids != sorted(set(ids)):
            raise ValueError("findings doit être trié par source_id, sans identifiant dupliqué.")
        _require_bool(self.complete, "complete")
        _require_tuple(self.scanned_roots, "scanned_roots")
        for root in self.scanned_roots:
            _require_str(root, "scanned_roots[]")
        if list(self.scanned_roots) != sorted(set(self.scanned_roots)):
            raise ValueError("scanned_roots doit être trié, sans doublon.")
        if self.complete and not self.scanned_roots:
            raise ValueError("Un inventaire complet exige au moins une racine d'audit scannée.")
        if type(self.trial_accounting) is not TrialAccounting:
            raise ValueError("trial_accounting doit être un TrialAccounting.")


def _as_sequence(value: object, name: str) -> tuple:
    if type(value) not in (list, tuple):
        raise TypeError(f"{name} doit être une liste ou un tuple.")
    return tuple(value)


def _sorted_findings(value: object, name: str) -> tuple:
    """Trie des `ExposureFinding` par `source_id` ; un élément d'un autre type est une valeur invalide (`ValueError`)."""
    items = _as_sequence(value, name)
    if any(type(item) is not ExposureFinding for item in items):
        raise ValueError(f"{name} ne contient que des ExposureFinding.")
    return tuple(sorted(items, key=lambda finding: finding.source_id))


def _sorted_unique_roots(value: object) -> tuple:
    """Racines d'audit : ensemble canonique trié et dédupliqué ; un élément non `str` est une valeur invalide."""
    roots = _as_sequence(value, "scanned_roots")
    if any(type(root) is not str for root in roots):
        raise ValueError("scanned_roots ne contient que des str.")
    return tuple(sorted(set(roots)))


def build_exposure_inventory(
    *,
    window_start_utc: str,
    window_end_utc: str,
    findings,
    complete: bool,
    scanned_roots,
    trial_accounting: TrialAccounting,
) -> ExposureInventory:
    """Construit un inventaire : normalise la fenêtre, trie les findings par `source_id` et les racines.
    Un identifiant dupliqué est refusé, jamais fusionné. L'ordre d'entrée n'a aucune influence."""
    return ExposureInventory(
        version=EXPOSURE_INVENTORY_SEMANTICS_VERSION,
        window_start_utc=normalize_utc_instant(window_start_utc),
        window_end_utc=normalize_utc_instant(window_end_utc),
        findings=_sorted_findings(findings, "findings"),
        complete=complete,
        scanned_roots=_sorted_unique_roots(scanned_roots),
        trial_accounting=trial_accounting,
    )


# ============================================================================================
# Canonicalisation et enregistrements d'identité (SHA-256 du JSON canonique, SANS horodatage)
# ============================================================================================


def _canonical_json(record: object) -> str:
    """Canonicalisation de la Décision 20.3 — duplication volontaire (helpers privés non importés entre
    modules) : clés triées, séparateurs compacts, UTF-8 non échappé, NaN refusé."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256_hex(record: object) -> str:
    return hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()


def _finding_record(finding: ExposureFinding) -> dict:
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


def _accounting_record(accounting: Optional[TrialAccounting]) -> Optional[dict]:
    if accounting is None:
        return None
    return {name: getattr(accounting, name) for name in _TRIAL_ACCOUNTING_FIELDS}


# ============================================================================================
# ExposureDeclaration, DeclarationSet et t_sel effectif
# ============================================================================================

EXPOSURE_DECLARATION_SEMANTICS_VERSION = "gate_v_exposure_declaration_v1"
_MAX_DECLARED_INDEX = 9999


@dataclass(frozen=True)
class ExposureDeclaration:
    """Déclaration humaine nominative (sans authentification forte). Les expositions déclarées portent les
    identifiants `declared:<seq 4 chiffres>:<position 4 chiffres>` (position 1-based, dans l'ordre du tuple)."""

    version: str
    declaration_seq: int
    declarant: str
    inventory_id: str
    prev_declaration_id: Optional[str]
    declared_exposures: tuple
    declared_t_sel_utc: Optional[str]
    declared_trial_counts: Optional[TrialAccounting]

    def __post_init__(self) -> None:
        if self.version != EXPOSURE_DECLARATION_SEMANTICS_VERSION:
            raise ValueError(f"version inconnue : attendu {EXPOSURE_DECLARATION_SEMANTICS_VERSION!r}.")
        _require_int(self.declaration_seq, "declaration_seq", minimum=1)
        if self.declaration_seq > _MAX_DECLARED_INDEX:
            raise ValueError("declaration_seq dépasse la capacité du format d'identifiant (4 chiffres).")
        _require_str(self.declarant, "declarant")
        _require_hex64(self.inventory_id, "inventory_id")
        if self.declaration_seq == 1:
            if self.prev_declaration_id is not None:
                raise ValueError("La première déclaration n'a pas de prev_declaration_id.")
        else:
            _require_hex64(self.prev_declaration_id, "prev_declaration_id")
        _require_tuple(self.declared_exposures, "declared_exposures")
        if len(self.declared_exposures) > _MAX_DECLARED_INDEX:
            raise ValueError("Trop d'expositions déclarées pour le format d'identifiant (4 chiffres).")
        for position, exposure in enumerate(self.declared_exposures, start=1):
            if type(exposure) is not ExposureFinding or exposure.source_kind is not SourceKind.DECLARED_UNRECORDED_WORK:
                raise ValueError("declared_exposures ne contient que des DECLARED_UNRECORDED_WORK.")
            expected_id = f"{_DECLARED_PREFIX}{self.declaration_seq:04d}:{position:04d}"
            if exposure.source_id != expected_id:
                raise ValueError(f"Identifiant d'exposition déclarée inattendu : {expected_id!r} attendu.")
        _require_optional_instant(self.declared_t_sel_utc, "declared_t_sel_utc")
        if self.declared_trial_counts is not None and type(self.declared_trial_counts) is not TrialAccounting:
            raise ValueError("declared_trial_counts doit être None ou un TrialAccounting.")


def build_exposure_declaration(
    *,
    declaration_seq: int,
    declarant: str,
    inventory_id: str,
    prev_declaration_id: Optional[str],
    declared_exposures,
    declared_t_sel_utc: Optional[str],
    declared_trial_counts: Optional[TrialAccounting],
) -> ExposureDeclaration:
    """Construit une déclaration : normalise `t_sel` et ordonne les expositions déclarées par identifiant."""
    return ExposureDeclaration(
        version=EXPOSURE_DECLARATION_SEMANTICS_VERSION,
        declaration_seq=declaration_seq,
        declarant=declarant,
        inventory_id=inventory_id,
        prev_declaration_id=prev_declaration_id,
        declared_exposures=_sorted_findings(declared_exposures, "declared_exposures"),
        declared_t_sel_utc=None if declared_t_sel_utc is None else normalize_utc_instant(declared_t_sel_utc),
        declared_trial_counts=declared_trial_counts,
    )


def _declaration_record(declaration: ExposureDeclaration) -> dict:
    return {
        "version": declaration.version,
        "declaration_seq": declaration.declaration_seq,
        "declarant": declaration.declarant,
        "inventory_id": declaration.inventory_id,
        "prev_declaration_id": declaration.prev_declaration_id,
        "declared_t_sel_utc": declaration.declared_t_sel_utc,
        "declared_exposures": [_finding_record(f) for f in declaration.declared_exposures],
        "declared_trial_counts": _accounting_record(declaration.declared_trial_counts),
    }


def compute_declaration_id(declaration: ExposureDeclaration) -> str:
    """Identité SANS horloge : SHA-256 du JSON canonique de la déclaration complète (version, seq, déclarant,
    `inventory_id`, `prev_declaration_id`, `t_sel` déclaré, expositions déclarées, comptes déclarés)."""
    if type(declaration) is not ExposureDeclaration:
        raise TypeError("declaration doit être un ExposureDeclaration.")
    return _sha256_hex(_declaration_record(declaration))


@dataclass(frozen=True)
class DeclarationSet:
    """Chaîne dense de déclarations (`seq` 1..n, `prev_declaration_id` = identité de la précédente). `hash_linked`
    est un FAIT fourni par l'appelant : les déclarations persistées sont liées par `content_hash` (23.11)."""

    declarations: tuple
    hash_linked: bool

    def __post_init__(self) -> None:
        _require_tuple(self.declarations, "declarations")
        _require_bool(self.hash_linked, "hash_linked")
        previous_id = None
        for expected_seq, declaration in enumerate(self.declarations, start=1):
            if type(declaration) is not ExposureDeclaration:
                raise ValueError("declarations ne contient que des ExposureDeclaration.")
            if declaration.declaration_seq != expected_seq:
                raise ValueError("Les déclarations doivent former une chaîne dense de seq 1..n dans l'ordre.")
            if declaration.prev_declaration_id != previous_id:
                raise ValueError("prev_declaration_id ne correspond pas à l'identité de la déclaration précédente.")
            previous_id = compute_declaration_id(declaration)
        if not self.declarations and self.hash_linked:
            raise ValueError("Un ensemble vide de déclarations ne peut pas être hash_linked.")


def compute_effective_t_sel(commitment_t_sel_utc: Optional[str], declarations: tuple) -> tuple:
    """`t_sel` effectif = maximum courant entre l'engagement et les déclarations prises dans l'ordre des `seq`.
    Retourne `(t_sel_effectif | None, seq_ignorés)` : une déclaration qui ABAISSERAIT le maximum courant est
    ignorée et son `seq` listé. `None` si l'engagement n'a pas de `t_sel`. Jamais ramené dans le passé."""
    if type(declarations) is not tuple or any(type(d) is not ExposureDeclaration for d in declarations):
        raise TypeError("declarations doit être un tuple d'ExposureDeclaration.")
    if [d.declaration_seq for d in declarations] != sorted({d.declaration_seq for d in declarations}):
        raise ValueError("declarations doit être en ordre strictement croissant de declaration_seq.")
    if commitment_t_sel_utc is None:
        return None, ()
    current = _require_instant(commitment_t_sel_utc, "commitment_t_sel_utc")
    ignored = []
    for declaration in declarations:
        declared = declaration.declared_t_sel_utc
        if declared is None:
            continue
        if _instant(declared) < _instant(current):
            ignored.append(declaration.declaration_seq)
        else:
            current = declared
    return current, tuple(ignored)


# ============================================================================================
# Contexte de la campagne courante et absorption des enregistrements propres (23.27.2)
# ============================================================================================


@dataclass(frozen=True)
class OwnCampaignContext:
    """Campagne courante et étage des enregistrements propres. L'étage est un FAIT fourni : en production, E3-D et
    E3-J le dérivent des artefacts persistés ; ce module ne le prouve jamais, il le CONTRÔLE contre l'inventaire."""

    current_campaign_id: str
    own_record_stage: OwnRecordStage

    def __post_init__(self) -> None:
        _require_str(self.current_campaign_id, "current_campaign_id")
        _require_enum(self.own_record_stage, OwnRecordStage, "own_record_stage")


# Enregistrements propres attendus, cumulativement, à chaque étage (23.27.2). `READ_INTENT` n'est attendu à aucun.
_EXPECTED_OWN_KINDS = {
    OwnRecordStage.NO_OWN_RECORDS: (),
    OwnRecordStage.RESERVED: (SourceKind.REGISTRY_RESERVATION,),
    OwnRecordStage.ADMITTED: (SourceKind.REGISTRY_RESERVATION, SourceKind.REGISTRY_ADMISSION),
    OwnRecordStage.CLAIMED: (
        SourceKind.REGISTRY_RESERVATION, SourceKind.REGISTRY_ADMISSION, SourceKind.FINAL_HOLDOUT_CLAIM,
    ),
    OwnRecordStage.CONSUMED: (
        SourceKind.REGISTRY_RESERVATION, SourceKind.REGISTRY_ADMISSION, SourceKind.FINAL_HOLDOUT_CLAIM,
        SourceKind.CONSUMPTION,
    ),
}
_MISSING_LABELS = {
    SourceKind.REGISTRY_RESERVATION: "RESERVATION",
    SourceKind.REGISTRY_ADMISSION: "ADMISSION",
    SourceKind.FINAL_HOLDOUT_CLAIM: "FINAL_HOLDOUT_CLAIM",
    SourceKind.CONSUMPTION: "CONSUMPTION",
}


_REGISTRY_RIVAL_KINDS = frozenset({SourceKind.REGISTRY_RESERVATION, SourceKind.REGISTRY_ADMISSION})


def _require_listable_inventory(inventory: ExposureInventory, own_context: OwnCampaignContext) -> None:
    """Règle de listabilité (23.28) : une réservation ou admission ÉTRANGÈRE RESOLVED doit recouper `W` pour figurer
    dans l'inventaire (les autres ne sont comptées que dans `trial_accounting`). Appliquée par TOUTE fonction qui
    prend le contexte, afin qu'aucune identité ne soit calculable pour un inventaire que la classification refuse."""
    for finding in inventory.findings:
        if (
            finding.source_kind in _REGISTRY_RIVAL_KINDS
            and finding.status is SourceStatus.RESOLVED
            and finding.campaign_id != own_context.current_campaign_id
            and finding.overlap is not OverlapVerdict.OVERLAPS
        ):
            raise ValueError(
                "Une réservation ou admission étrangère RESOLVED doit recouper W pour être listée "
                f"({finding.source_id!r})."
            )


def _require_inventory_and_context(inventory: object, own_context: object) -> None:
    if type(inventory) is not ExposureInventory:
        raise TypeError("inventory doit être un ExposureInventory.")
    if type(own_context) is not OwnCampaignContext:
        raise TypeError("own_context doit être un OwnCampaignContext.")
    _require_listable_inventory(inventory, own_context)


def partition_own_records(inventory: ExposureInventory, own_context: OwnCampaignContext) -> tuple:
    """Partition des enregistrements propres (campagne courante) selon l'étage reçu. Retourne
    `(absorbés, restants, ids_d_anomalie)` :
    - un enregistrement attendu est ABSORBÉ s'il est unique pour son type (tous statuts confondus), RESOLVED, et,
      pour RESERVATION, ADMISSION, Claim et CONSUMPTION, de fenêtre égale à `W` ;
    - tout le reste reste dans `restants` (échec fermé : jamais masqué) ;
    - `ids_d_anomalie` = ids des enregistrements propres NON exposants non absorbés (RESERVATION, ADMISSION),
      plus `missing:<TYPE>` pour chaque type attendu dont il n'existe AUCUN enregistrement."""
    _require_inventory_and_context(inventory, own_context)
    expected = _EXPECTED_OWN_KINDS[own_context.own_record_stage]
    window = (inventory.window_start_utc, inventory.window_end_utc)
    absorbed = []
    anomalies = []
    for kind in sorted(_CAMPAIGN_RECORD_KINDS, key=lambda k: k.value):
        records = [
            f for f in inventory.findings
            if f.source_kind is kind and f.campaign_id == own_context.current_campaign_id
        ]
        if kind in expected:
            if not records:
                anomalies.append(_MISSING_PREFIX + _MISSING_LABELS[kind])
                continue
            only = records[0]
            if (
                len(records) == 1
                and only.status is SourceStatus.RESOLVED
                and (only.window_start_utc, only.window_end_utc) == window
            ):
                absorbed.append(only)
                continue
        if not kind.exposes_data:
            anomalies.extend(record.source_id for record in records)
    absorbed_ids = {finding.source_id for finding in absorbed}
    return (
        tuple(sorted(absorbed, key=lambda f: f.source_id)),
        tuple(f for f in inventory.findings if f.source_id not in absorbed_ids),
        tuple(sorted(anomalies)),
    )


def compute_exposure_inventory_id(inventory: ExposureInventory, own_context: OwnCampaignContext) -> str:
    """Identité SCIENTIFIQUE de l'inventaire (23.27.3), stable entre étages légitimes : SHA-256 de la version, de
    la fenêtre `W`, de `complete`, de `scanned_roots` et des findings NON absorbés. N'inclut ni `trial_accounting`,
    ni l'étage, ni horodatage."""
    _, remaining, _ = partition_own_records(inventory, own_context)
    return _sha256_hex({
        "version": inventory.version,
        "window_start_utc": inventory.window_start_utc,
        "window_end_utc": inventory.window_end_utc,
        "complete": inventory.complete,
        "scanned_roots": list(inventory.scanned_roots),
        "findings": [_finding_record(f) for f in remaining],
    })


# ============================================================================================
# Faits de chronologie (preuve de temps, ancrage, S0, ingestion) — fournis par l'appelant, jamais établis ici
# ============================================================================================


@dataclass(frozen=True)
class TimeProofFact:
    """Fait de preuve de temps vérifiée ailleurs (E3-E). `VALID` exige la borne et la cible ; sinon les deux sont None."""

    status: TimeProofStatus
    bound_utc: Optional[str]
    targets_own_reservation: Optional[bool]

    def __post_init__(self) -> None:
        _require_enum(self.status, TimeProofStatus, "status")
        _require_optional_instant(self.bound_utc, "bound_utc")
        _require_optional_bool(self.targets_own_reservation, "targets_own_reservation")
        if self.status is TimeProofStatus.VALID:
            if self.bound_utc is None or self.targets_own_reservation is None:
                raise ValueError("Une preuve VALID exige bound_utc et targets_own_reservation.")
        elif self.bound_utc is not None or self.targets_own_reservation is not None:
            raise ValueError("Une preuve non VALID n'a ni borne ni cible.")


@dataclass(frozen=True)
class ChronologyFacts:
    """Faits chronologiques de F2 à F5. `None` = inconnu (jamais une valeur par défaut) ; la marge d'ancrage est un
    fait fourni (secondes entières, de tout signe : une marge <= 0 est jugée `UNVERIFIED` par F4, jamais masquée),
    jamais une constante du module."""

    commitment_t_sel_utc: Optional[str]
    reservation_durable: Optional[bool]
    time_proof: TimeProofFact
    anchor_margin_seconds: Optional[int]
    s0_max_time_utc: Optional[str]
    ingested_at_utc: Optional[str]
    ingestion_range_matches: Optional[bool]

    def __post_init__(self) -> None:
        _require_optional_instant(self.commitment_t_sel_utc, "commitment_t_sel_utc")
        _require_optional_bool(self.reservation_durable, "reservation_durable")
        if type(self.time_proof) is not TimeProofFact:
            raise ValueError("time_proof doit être un TimeProofFact.")
        if self.anchor_margin_seconds is not None and type(self.anchor_margin_seconds) is not int:
            # Tout entier est un fait recevable : une marge <= 0 est jugée (F4 UNVERIFIED), jamais masquée.
            raise ValueError("anchor_margin_seconds doit être None ou un entier (non booléen) de secondes.")
        _require_optional_instant(self.s0_max_time_utc, "s0_max_time_utc")
        _require_optional_instant(self.ingested_at_utc, "ingested_at_utc")
        _require_optional_bool(self.ingestion_range_matches, "ingestion_range_matches")


def _normalize_optional_instant(value: Optional[str]) -> Optional[str]:
    return None if value is None else normalize_utc_instant(value)


def build_chronology_facts(
    *,
    commitment_t_sel_utc: Optional[str],
    reservation_durable: Optional[bool],
    time_proof: TimeProofFact,
    anchor_margin_seconds: Optional[int],
    s0_max_time_utc: Optional[str],
    ingested_at_utc: Optional[str],
    ingestion_range_matches: Optional[bool],
) -> ChronologyFacts:
    """Construit les faits chronologiques en normalisant les instants (offsets acceptés, naïfs refusés)."""
    return ChronologyFacts(
        commitment_t_sel_utc=_normalize_optional_instant(commitment_t_sel_utc),
        reservation_durable=reservation_durable,
        time_proof=time_proof,
        anchor_margin_seconds=anchor_margin_seconds,
        s0_max_time_utc=_normalize_optional_instant(s0_max_time_utc),
        ingested_at_utc=_normalize_optional_instant(ingested_at_utc),
        ingestion_range_matches=ingestion_range_matches,
    )


# ============================================================================================
# ClassificationInput
# ============================================================================================

EXPOSURE_CLASSIFICATION_RULES_VERSION = "gate_v_exposure_classification_v1"
_CONDITION_IDS = ("F1", "F2", "F3", "F4", "F5", "F6")
_REASON_ORDER = {code: index for index, code in enumerate(ReasonCode)}
_CONDITION_REASON_CODES = frozenset(list(ReasonCode)[7:])   # les 25 codes F1..F6 (les 7 premiers sont de niveau classe)
# Raisons de VIOLATION CONNUE (condition NOT_MET) ; les 13 autres codes F sont des données manquantes (UNVERIFIED).
# Les décomptes 12 et 13 sont verrouillés par un test.
_NOT_MET_REASON_CODES = frozenset({
    ReasonCode.F1_EXPOSURE_ESTABLISHED, ReasonCode.F2_EXPOSURE_AFTER_WS, ReasonCode.F2_T_SEL_AFTER_WS,
    ReasonCode.F2_T_SEL_AFTER_ANCHOR, ReasonCode.F3_S0_NOT_BEFORE_WINDOW, ReasonCode.F4_RESERVATION_NOT_DURABLE,
    ReasonCode.F4_PROOF_INVALID, ReasonCode.F4_PROOF_NOT_OWN_RESERVATION, ReasonCode.F4_ANCHORED_TOO_LATE,
    ReasonCode.F5_INGESTED_BEFORE_WINDOW_END, ReasonCode.F5_RANGE_MISMATCH, ReasonCode.F6_HASH_LINK_BROKEN,
})


@dataclass(frozen=True)
class ClassificationInput:
    """Entrée complète de la classification. La fenêtre `W` est celle de l'inventaire. Au moins une déclaration est
    exigée (la classe n'existe qu'après l'étape 2 de 23.11) et chacune doit référencer l'`inventory_id` courant."""

    inventory: ExposureInventory
    declarations: DeclarationSet
    chronology: ChronologyFacts
    own_context: OwnCampaignContext

    def __post_init__(self) -> None:
        if type(self.inventory) is not ExposureInventory:
            raise ValueError("inventory doit être un ExposureInventory.")
        if type(self.declarations) is not DeclarationSet:
            raise ValueError("declarations doit être un DeclarationSet.")
        if type(self.chronology) is not ChronologyFacts:
            raise ValueError("chronology doit être un ChronologyFacts.")
        if type(self.own_context) is not OwnCampaignContext:
            raise ValueError("own_context doit être un OwnCampaignContext.")
        if not self.declarations.declarations:
            raise ValueError("Au moins une déclaration est exigée pour classifier.")
        inventory_id = compute_exposure_inventory_id(self.inventory, self.own_context)   # refuse un inventaire non listable
        for declaration in self.declarations.declarations:
            if declaration.inventory_id != inventory_id:
                raise ValueError("Une déclaration référence un autre inventory_id que l'inventaire courant.")
            for exposure in declaration.declared_exposures:
                _check_overlap_geometry(exposure, self.inventory.window_start_utc, self.inventory.window_end_utc)


# ============================================================================================
# Résultat de la classification
# ============================================================================================


@dataclass(frozen=True)
class FConditionResult:
    """Résultat tri-état d'une condition fermée `F1`..`F6`. `MET` n'a aucune raison ; toute autre issue en a."""

    condition: str
    status: ConditionStatus
    reasons: tuple

    def __post_init__(self) -> None:
        if self.condition not in _CONDITION_IDS or type(self.condition) is not str:
            raise ValueError(f"condition doit être l'un de {_CONDITION_IDS}.")
        _require_enum(self.status, ConditionStatus, "status")
        _require_reason_tuple(self.reasons, "reasons")
        if any(not reason.value.startswith(self.condition + "_") for reason in self.reasons):
            raise ValueError(f"Les raisons de {self.condition} doivent porter le préfixe {self.condition}_.")
        if (self.status is ConditionStatus.MET) != (not self.reasons):
            raise ValueError("Une condition MET n'a aucune raison ; toute autre issue en exige au moins une.")
        # Le statut est la sévérité maximale de ses raisons : NOT_MET <=> au moins une violation connue ;
        # UNVERIFIED <=> uniquement des données manquantes.
        has_violation = any(reason in _NOT_MET_REASON_CODES for reason in self.reasons)
        if (self.status is ConditionStatus.NOT_MET) != has_violation:
            raise ValueError("NOT_MET <=> au moins une raison de violation connue ; UNVERIFIED <=> données manquantes seules.")


def _require_reason_tuple(value: object, name: str) -> tuple:
    _require_tuple(value, name)
    for reason in value:
        _require_enum(reason, ReasonCode, name + "[]")
    ordered = sorted(set(value), key=_REASON_ORDER.__getitem__)
    if list(value) != ordered:
        raise ValueError(f"{name} doit être trié selon l'ordre de ReasonCode, sans doublon.")
    return value


def _require_sorted_str_tuple(value: object, name: str) -> tuple:
    _require_tuple(value, name)
    for item in value:
        _require_str(item, name + "[]")
    if list(value) != sorted(set(value)):
        raise ValueError(f"{name} doit être trié, sans doublon.")
    return value


def _classification_id(
    *, rules_version, input_digest, classification, chronology_level, t_sel_effective_utc,
    t_sel_lowering_ignored_seqs, established_exposure_ids, unresolved_source_ids, overlapping_registration_ids,
    own_anomaly_ids, conditions, reasons,
) -> str:
    """SHA-256 du JSON canonique de la classification, SANS `absorbed_own_record_ids`, étage ni horodatage."""
    return _sha256_hex({
        "rules_version": rules_version,
        "input_digest": input_digest,
        "classification": classification.value,
        "chronology_level": chronology_level.value,
        "t_sel_effective_utc": t_sel_effective_utc,
        "t_sel_lowering_ignored_seqs": list(t_sel_lowering_ignored_seqs),
        "established_exposure_ids": list(established_exposure_ids),
        "unresolved_source_ids": list(unresolved_source_ids),
        "overlapping_registration_ids": list(overlapping_registration_ids),
        "own_anomaly_ids": list(own_anomaly_ids),
        "conditions": [
            {"condition": c.condition, "status": c.status.value, "reasons": [r.value for r in c.reasons]}
            for c in conditions
        ],
        "reasons": [r.value for r in reasons],
    })


@dataclass(frozen=True)
class ExposureClassificationResult:
    """Résultat de classification (16 champs). Il ne vaut JAMAIS autorisation d'accès : voir `admission_refusals`."""

    rules_version: str
    classification: ExposureClass
    chronology_level: ChronologyLevel
    inventory_id: str
    inventory_content_digest: str
    input_digest: str
    classification_id: str
    t_sel_effective_utc: Optional[str]
    t_sel_lowering_ignored_seqs: tuple
    established_exposure_ids: tuple
    unresolved_source_ids: tuple
    overlapping_registration_ids: tuple
    absorbed_own_record_ids: tuple
    own_anomaly_ids: tuple
    conditions: tuple
    reasons: tuple

    def __post_init__(self) -> None:
        if self.rules_version != EXPOSURE_CLASSIFICATION_RULES_VERSION:
            raise ValueError(f"rules_version inconnue : attendu {EXPOSURE_CLASSIFICATION_RULES_VERSION!r}.")
        _require_enum(self.classification, ExposureClass, "classification")
        _require_enum(self.chronology_level, ChronologyLevel, "chronology_level")
        for name in ("inventory_id", "inventory_content_digest", "input_digest", "classification_id"):
            _require_hex64(getattr(self, name), name)
        _require_optional_instant(self.t_sel_effective_utc, "t_sel_effective_utc")
        _require_tuple(self.t_sel_lowering_ignored_seqs, "t_sel_lowering_ignored_seqs")
        for seq in self.t_sel_lowering_ignored_seqs:
            _require_int(seq, "t_sel_lowering_ignored_seqs[]", minimum=1)
        if list(self.t_sel_lowering_ignored_seqs) != sorted(set(self.t_sel_lowering_ignored_seqs)):
            raise ValueError("t_sel_lowering_ignored_seqs doit être strictement croissant.")
        for name in (
            "established_exposure_ids", "unresolved_source_ids", "overlapping_registration_ids",
            "absorbed_own_record_ids", "own_anomaly_ids",
        ):
            _require_sorted_str_tuple(getattr(self, name), name)
        _require_tuple(self.conditions, "conditions")
        if len(self.conditions) != len(_CONDITION_IDS) or any(
            type(c) is not FConditionResult or c.condition != expected
            for c, expected in zip(self.conditions, _CONDITION_IDS)
        ):
            raise ValueError("conditions doit contenir exactement F1..F6, dans l'ordre.")
        _require_reason_tuple(self.reasons, "reasons")
        if {r for c in self.conditions for r in c.reasons} != set(self.reasons) & _CONDITION_REASON_CODES:
            raise ValueError("Les codes F de reasons doivent être exactement l'union des raisons des conditions.")

        retrospective = self.classification is ExposureClass.RETROSPECTIVE_EXPOSED
        if retrospective != bool(self.established_exposure_ids):
            raise ValueError("RETROSPECTIVE_EXPOSED <=> au moins une exposition établie.")
        if retrospective != (self.chronology_level is ChronologyLevel.NOT_APPLICABLE):
            raise ValueError("RETROSPECTIVE_EXPOSED <=> niveau NOT_APPLICABLE.")
        all_met = all(c.status is ConditionStatus.MET for c in self.conditions)
        if not retrospective:
            if (self.chronology_level is ChronologyLevel.PROSPECTIVE_ANCHORED) != all_met:
                raise ValueError("PROSPECTIVE_ANCHORED <=> les six conditions F1..F6 sont MET.")
            if all_met and self.classification is not ExposureClass.FRESH_UNEXPOSED_DECLARED:
                raise ValueError("Six conditions MET exigent la classe FRESH_UNEXPOSED_DECLARED.")
        for reason, ids in (
            (ReasonCode.UNRESOLVED_SOURCE, self.unresolved_source_ids),
            (ReasonCode.OVERLAPPING_REGISTRATION, self.overlapping_registration_ids),
            (ReasonCode.OWN_REGISTRATION_ANOMALY, self.own_anomaly_ids),
            (ReasonCode.T_SEL_LOWERING_IGNORED, self.t_sel_lowering_ignored_seqs),
        ):
            if (reason in self.reasons) != bool(ids):
                raise ValueError(f"La raison {reason.value} doit être présente si et seulement si ses identifiants le sont.")
        f1_reasons = self.conditions[0].reasons
        for class_code, f1_code in (
            (ReasonCode.UNRESOLVED_SOURCE, ReasonCode.F1_SOURCES_UNRESOLVED),
            (ReasonCode.INVENTORY_INCOMPLETE, ReasonCode.F1_INVENTORY_INCOMPLETE),
            (ReasonCode.OWN_REGISTRATION_ANOMALY, ReasonCode.F1_OWN_ANOMALY),
        ):
            if (class_code in self.reasons) != (f1_code in f1_reasons):
                raise ValueError(f"{class_code.value} doit être présent si et seulement si {f1_code.value} l'est.")
        established_reasons = (
            ReasonCode.EXPOSURE_ESTABLISHED_INVENTORY in self.reasons
            or ReasonCode.EXPOSURE_ESTABLISHED_DECLARED in self.reasons
        )
        if (
            bool(self.established_exposure_ids) != established_reasons
            or bool(self.established_exposure_ids) != (ReasonCode.F1_EXPOSURE_ESTABLISHED in f1_reasons)
        ):
            raise ValueError("Les raisons d'exposition établie doivent correspondre aux identifiants établis.")
        explained = (
            bool(self.unresolved_source_ids)
            or bool(self.own_anomaly_ids)
            or ReasonCode.INVENTORY_INCOMPLETE in self.reasons
        )
        if (self.classification is ExposureClass.UNDETERMINED) != (explained and not retrospective):
            raise ValueError("UNDETERMINED <=> (hors exposition établie) une source non résolue, une anomalie ou un inventaire incomplet.")
        expected_id = _classification_id(
            rules_version=self.rules_version, input_digest=self.input_digest, classification=self.classification,
            chronology_level=self.chronology_level, t_sel_effective_utc=self.t_sel_effective_utc,
            t_sel_lowering_ignored_seqs=self.t_sel_lowering_ignored_seqs,
            established_exposure_ids=self.established_exposure_ids, unresolved_source_ids=self.unresolved_source_ids,
            overlapping_registration_ids=self.overlapping_registration_ids, own_anomaly_ids=self.own_anomaly_ids,
            conditions=self.conditions, reasons=self.reasons,
        )
        if self.classification_id != expected_id:
            raise ValueError("classification_id ne correspond pas au contenu du résultat.")


# ============================================================================================
# Identités : contenu de l'inventaire et entrée de classification
# ============================================================================================


def compute_inventory_content_digest(inventory: ExposureInventory, own_context: OwnCampaignContext) -> str:
    """SHA-256 de `{inventory_id, trial_accounting}` (sans horloge) : intègre les compteurs que `inventory_id`
    exclut (23.27.3). Distinct de `inventory_content_hash` (contenu intégral persisté et horodaté, E3-B)."""
    _require_inventory_and_context(inventory, own_context)
    return _sha256_hex({
        "inventory_id": compute_exposure_inventory_id(inventory, own_context),
        "trial_accounting": _accounting_record(inventory.trial_accounting),
    })


def compute_static_sources_digest(inventory: ExposureInventory, own_context: OwnCampaignContext) -> str:
    """23.10 / 23.27.1 : SHA-256 de la liste canonique triée de l'ENSEMBLE PERTINENT (findings NON absorbés dont le
    verdict de recouvrement n'est pas NO_OVERLAP), `{source_id, content_hash}` seulement. Constant tant qu'aucune
    exposition ni aucun rival n'apparaît ; un ajout sans rapport avec `W` ne la modifie pas."""
    _require_inventory_and_context(inventory, own_context)
    _, remaining, _ = partition_own_records(inventory, own_context)
    return _sha256_hex([
        {"source_id": f.source_id, "content_hash": f.content_hash}
        for f in remaining
        if f.overlap is not OverlapVerdict.NO_OVERLAP
    ])


def compute_overlap_projection_hash(inventory: ExposureInventory, own_context: OwnCampaignContext) -> str:
    """23.10 : SHA-256 de la liste des réservations et admissions d'AUTRES campagnes qui recoupent `W`, ou illisibles
    (`REGISTRY_UNREADABLE`). Les enregistrements propres non absorbés n'en font jamais partie (jamais un rival)."""
    _require_inventory_and_context(inventory, own_context)
    _, remaining, _ = partition_own_records(inventory, own_context)
    return _sha256_hex([
        {"source_id": f.source_id, "content_hash": f.content_hash, "source_kind": f.source_kind.value}
        for f in remaining
        # Un rival RESOLVED listable recoupe toujours `W` (listabilité) ; un enregistrement illisible n'a pas
        # d'attribution fiable de campagne et figure donc toujours dans la projection.
        if f.source_kind is SourceKind.REGISTRY_UNREADABLE
        or (f.source_kind in _REGISTRY_RIVAL_KINDS and f.campaign_id != own_context.current_campaign_id)
    ])


def _chronology_record(chronology: ChronologyFacts) -> dict:
    proof = chronology.time_proof
    return {
        "commitment_t_sel_utc": chronology.commitment_t_sel_utc,
        "reservation_durable": chronology.reservation_durable,
        "time_proof": {
            "status": proof.status.value,
            "bound_utc": proof.bound_utc,
            "targets_own_reservation": proof.targets_own_reservation,
        },
        "anchor_margin_seconds": chronology.anchor_margin_seconds,
        "s0_max_time_utc": chronology.s0_max_time_utc,
        "ingested_at_utc": chronology.ingested_at_utc,
        "ingestion_range_matches": chronology.ingestion_range_matches,
    }


def compute_classification_input_digest(classification_input: ClassificationInput) -> str:
    """SHA-256 de la version des règles, de l'`inventory_id`, du `campaign_id` courant, des déclarations complètes, de
    `hash_linked` et de la chronologie complète. Exclut l'ÉTAGE, les enregistrements absorbés et la comptabilité."""
    if type(classification_input) is not ClassificationInput:
        raise TypeError("classification_input doit être un ClassificationInput.")
    return _sha256_hex({
        "rules_version": EXPOSURE_CLASSIFICATION_RULES_VERSION,
        "inventory_id": compute_exposure_inventory_id(classification_input.inventory, classification_input.own_context),
        "current_campaign_id": classification_input.own_context.current_campaign_id,
        "declarations": [_declaration_record(d) for d in classification_input.declarations.declarations],
        "hash_linked": classification_input.declarations.hash_linked,
        "chronology": _chronology_record(classification_input.chronology),
    })


# ============================================================================================
# Classification R1 / R2 / R3 et conditions F1..F6
# ============================================================================================

_OWN_ESTABLISHING_KINDS = frozenset({
    SourceKind.FINAL_HOLDOUT_CLAIM, SourceKind.CONSUMPTION, SourceKind.READ_INTENT,
})


def _reasons_sorted(codes) -> tuple:
    return tuple(sorted(set(codes), key=_REASON_ORDER.__getitem__))


def _condition(code: str, *, not_met=(), unverified=()) -> FConditionResult:
    """Statut = sévérité maximale ; une violation connue prime sur une donnée manquante ; raisons cumulées."""
    if not_met:
        status = ConditionStatus.NOT_MET
    elif unverified:
        status = ConditionStatus.UNVERIFIED
    else:
        status = ConditionStatus.MET
    return FConditionResult(condition=code, status=status, reasons=_reasons_sorted([*not_met, *unverified]))


def _evaluate_f1(*, established: bool, unresolved: bool, complete: bool, anomalies: bool) -> FConditionResult:
    not_met = [ReasonCode.F1_EXPOSURE_ESTABLISHED] if established else []
    unverified = []
    if unresolved:
        unverified.append(ReasonCode.F1_SOURCES_UNRESOLVED)
    if not complete:
        unverified.append(ReasonCode.F1_INVENTORY_INCOMPLETE)
    if anomalies:
        unverified.append(ReasonCode.F1_OWN_ANOMALY)
    return _condition("F1", not_met=not_met, unverified=unverified)


def _evaluate_f2(*, inventory, chronology, remaining, declared_exposures, t_sel_effective) -> FConditionResult:
    """F2 : `ws >= max(fin de E, t_sel)` et `t_sel <= t_anchor`. `E` = expositions RESOLVED (inventaire non absorbé
    et déclarées), tout verdict de recouvrement. `t_anchor` n'existe que pour une preuve VALID de SA réservation."""
    ws = _instant(inventory.window_start_utc)
    not_met, unverified = [], []
    candidates = (*remaining, *declared_exposures)
    if any(
        f.status is SourceStatus.UNRESOLVED and (f.source_kind.exposes_data or f.source_kind.capability_unknown)
        for f in candidates
    ):
        unverified.append(ReasonCode.F2_EXPOSURE_WINDOW_UNKNOWN)
    if any(
        f.status is SourceStatus.RESOLVED and f.source_kind.exposes_data and _instant(f.window_end_utc) > ws
        for f in candidates
    ):
        not_met.append(ReasonCode.F2_EXPOSURE_AFTER_WS)
    proof = chronology.time_proof
    anchor = (
        _instant(proof.bound_utc)
        if proof.status is TimeProofStatus.VALID and proof.targets_own_reservation
        else None
    )
    if anchor is None:
        unverified.append(ReasonCode.F2_ANCHOR_UNKNOWN)
    if t_sel_effective is None:
        unverified.append(ReasonCode.F2_T_SEL_MISSING)
    else:
        t_sel = _instant(t_sel_effective)
        if t_sel > ws:
            not_met.append(ReasonCode.F2_T_SEL_AFTER_WS)
        if anchor is not None and t_sel > anchor:
            not_met.append(ReasonCode.F2_T_SEL_AFTER_ANCHOR)
    return _condition("F2", not_met=not_met, unverified=unverified)


def _evaluate_f3(*, inventory, chronology, **_unused) -> FConditionResult:
    """F3 : `max(time)` de S0 strictement inférieur à `ws` (fait fourni par E3-H, jamais lu ici)."""
    if chronology.s0_max_time_utc is None:
        return _condition("F3", unverified=[ReasonCode.F3_S0_MAX_TIME_MISSING])
    if _instant(chronology.s0_max_time_utc) >= _instant(inventory.window_start_utc):
        return _condition("F3", not_met=[ReasonCode.F3_S0_NOT_BEFORE_WINDOW])
    return _condition("F3")


# Plafond de la marge comparée : très supérieur à l'étendue de `datetime` (~3,2e11 s) et inférieur au maximum de
# `timedelta` (~8,6e13 s) ; une marge au-delà est de toute façon « trop tard » sans calcul de date.
_MAX_MARGIN_SECONDS = 10**13


def _evaluate_f4(*, inventory, chronology, **_unused) -> FConditionResult:
    """F4 : réservation durable, puis preuve de temps VALID de SA réservation avec `borne + marge <= ws`. La marge
    est un fait fourni et doit être strictement positive ; la durabilité et la preuve sont vérifiées ailleurs."""
    ws = _instant(inventory.window_start_utc)
    not_met, unverified = [], []
    if chronology.reservation_durable is None:
        unverified.append(ReasonCode.F4_RESERVATION_UNKNOWN)
    elif not chronology.reservation_durable:
        not_met.append(ReasonCode.F4_RESERVATION_NOT_DURABLE)
    proof = chronology.time_proof
    if proof.status is TimeProofStatus.ABSENT:
        unverified.append(ReasonCode.F4_PROOF_ABSENT)
    elif proof.status is TimeProofStatus.UNVERIFIABLE:
        unverified.append(ReasonCode.F4_PROOF_UNVERIFIABLE)
    elif proof.status is TimeProofStatus.INVALID:
        not_met.append(ReasonCode.F4_PROOF_INVALID)
    elif not proof.targets_own_reservation:
        not_met.append(ReasonCode.F4_PROOF_NOT_OWN_RESERVATION)
    else:
        bound = _instant(proof.bound_utc)
        margin = chronology.anchor_margin_seconds
        if bound > ws:
            not_met.append(ReasonCode.F4_ANCHORED_TOO_LATE)
        if margin is None:
            unverified.append(ReasonCode.F4_MARGIN_MISSING)
        elif margin <= 0:
            unverified.append(ReasonCode.F4_MARGIN_NOT_POSITIVE)
        elif ws - bound < timedelta(seconds=min(margin, _MAX_MARGIN_SECONDS)):   # borne + marge > ws, sans débordement
            not_met.append(ReasonCode.F4_ANCHORED_TOO_LATE)
    return _condition("F4", not_met=not_met, unverified=unverified)


def _evaluate_f5(*, inventory, chronology, **_unused) -> FConditionResult:
    """F5 : S_H ingéré strictement après `we`, sur la plage engagée (faits fournis par E3-F)."""
    not_met, unverified = [], []
    ingested = chronology.ingested_at_utc
    if ingested is None or chronology.ingestion_range_matches is None:
        unverified.append(ReasonCode.F5_INGESTION_MISSING)
    if ingested is not None and _instant(ingested) <= _instant(inventory.window_end_utc):
        not_met.append(ReasonCode.F5_INGESTED_BEFORE_WINDOW_END)
    if chronology.ingestion_range_matches is False:
        not_met.append(ReasonCode.F5_RANGE_MISMATCH)
    return _condition("F5", not_met=not_met, unverified=unverified)


def _evaluate_f6(*, declarations, **_unused) -> FConditionResult:
    """F6 : les déclarations nominatives sont liées par hash (fait fourni ; la présence est exigée à l'entrée)."""
    if not declarations.hash_linked:
        return _condition("F6", not_met=[ReasonCode.F6_HASH_LINK_BROKEN])
    return _condition("F6")


def classify_exposure(classification_input: ClassificationInput) -> ExposureClassificationResult:
    """Classification PURE et déterministe (23.28). Précédence : R1 exposition établie => RETROSPECTIVE_EXPOSED ;
    R2 sinon source non résolue, inventaire incomplet ou anomalie propre => UNDETERMINED ; R3 sinon FRESH. Le niveau
    chronologique est une preuve complémentaire. Aucun accès n'est jamais autorisé par ce résultat."""
    if type(classification_input) is not ClassificationInput:
        raise TypeError("classification_input doit être un ClassificationInput.")
    inventory = classification_input.inventory
    own_context = classification_input.own_context
    chronology = classification_input.chronology
    declarations = classification_input.declarations

    absorbed, remaining, anomaly_ids = partition_own_records(inventory, own_context)
    declared_exposures = tuple(f for d in declarations.declarations for f in d.declared_exposures)

    def established(finding: ExposureFinding, *, own_unabsorbed: bool) -> bool:
        return (
            finding.status is SourceStatus.RESOLVED
            and finding.source_kind.exposes_data
            and (finding.overlap is OverlapVerdict.OVERLAPS or own_unabsorbed)
        )

    established_inventory = [
        f.source_id for f in remaining
        if established(
            f, own_unabsorbed=f.campaign_id == own_context.current_campaign_id and f.source_kind in _OWN_ESTABLISHING_KINDS,
        )
    ]
    established_declared = [f.source_id for f in declared_exposures if established(f, own_unabsorbed=False)]
    unresolved_ids = [f.source_id for f in (*remaining, *declared_exposures) if f.status is SourceStatus.UNRESOLVED]
    overlapping_ids = [
        f.source_id for f in remaining
        if f.source_kind in _REGISTRY_RIVAL_KINDS
        and f.status is SourceStatus.RESOLVED
        and f.campaign_id != own_context.current_campaign_id
        and f.overlap is OverlapVerdict.OVERLAPS
    ]
    established_ids = tuple(sorted({*established_inventory, *established_declared}))
    unresolved_ids_sorted = tuple(sorted(set(unresolved_ids)))
    overlapping_ids_sorted = tuple(sorted(set(overlapping_ids)))

    if established_ids:
        classification = ExposureClass.RETROSPECTIVE_EXPOSED
    elif unresolved_ids_sorted or not inventory.complete or anomaly_ids:
        classification = ExposureClass.UNDETERMINED
    else:
        classification = ExposureClass.FRESH_UNEXPOSED_DECLARED

    t_sel_effective, ignored_seqs = compute_effective_t_sel(
        chronology.commitment_t_sel_utc, declarations.declarations,
    )
    facts = dict(
        inventory=inventory, chronology=chronology, remaining=remaining, declared_exposures=declared_exposures,
        t_sel_effective=t_sel_effective,
    )
    conditions = (
        _evaluate_f1(
            established=bool(established_ids), unresolved=bool(unresolved_ids_sorted),
            complete=inventory.complete, anomalies=bool(anomaly_ids),
        ),
        _evaluate_f2(**facts),
        _evaluate_f3(**facts),
        _evaluate_f4(**facts),
        _evaluate_f5(**facts),
        _evaluate_f6(declarations=declarations),
    )

    class_reasons = []
    if established_inventory:
        class_reasons.append(ReasonCode.EXPOSURE_ESTABLISHED_INVENTORY)
    if established_declared:
        class_reasons.append(ReasonCode.EXPOSURE_ESTABLISHED_DECLARED)
    if unresolved_ids_sorted:
        class_reasons.append(ReasonCode.UNRESOLVED_SOURCE)
    if not inventory.complete:
        class_reasons.append(ReasonCode.INVENTORY_INCOMPLETE)
    if ignored_seqs:
        class_reasons.append(ReasonCode.T_SEL_LOWERING_IGNORED)
    if overlapping_ids_sorted:
        class_reasons.append(ReasonCode.OVERLAPPING_REGISTRATION)
    if anomaly_ids:
        class_reasons.append(ReasonCode.OWN_REGISTRATION_ANOMALY)
    reasons = _reasons_sorted([*class_reasons, *(r for c in conditions for r in c.reasons)])

    if classification is ExposureClass.RETROSPECTIVE_EXPOSED:
        level = ChronologyLevel.NOT_APPLICABLE
    elif all(c.status is ConditionStatus.MET for c in conditions):
        level = ChronologyLevel.PROSPECTIVE_ANCHORED
    else:
        level = ChronologyLevel.UNSEEN_HISTORICAL

    inventory_id = compute_exposure_inventory_id(inventory, own_context)
    input_digest = compute_classification_input_digest(classification_input)
    classification_id = _classification_id(
        rules_version=EXPOSURE_CLASSIFICATION_RULES_VERSION, input_digest=input_digest,
        classification=classification, chronology_level=level, t_sel_effective_utc=t_sel_effective,
        t_sel_lowering_ignored_seqs=ignored_seqs, established_exposure_ids=established_ids,
        unresolved_source_ids=unresolved_ids_sorted, overlapping_registration_ids=overlapping_ids_sorted,
        own_anomaly_ids=anomaly_ids, conditions=conditions, reasons=reasons,
    )
    return ExposureClassificationResult(
        rules_version=EXPOSURE_CLASSIFICATION_RULES_VERSION,
        classification=classification,
        chronology_level=level,
        inventory_id=inventory_id,
        inventory_content_digest=compute_inventory_content_digest(inventory, own_context),
        input_digest=input_digest,
        classification_id=classification_id,
        t_sel_effective_utc=t_sel_effective,
        t_sel_lowering_ignored_seqs=ignored_seqs,
        established_exposure_ids=established_ids,
        unresolved_source_ids=unresolved_ids_sorted,
        overlapping_registration_ids=overlapping_ids_sorted,
        absorbed_own_record_ids=tuple(f.source_id for f in absorbed),
        own_anomaly_ids=anomaly_ids,
        conditions=conditions,
        reasons=reasons,
    )


# ============================================================================================
# Refus d'admission et enregistrement JSON
# ============================================================================================


def admission_refusals(result: ExposureClassificationResult) -> tuple:
    """Refus de CLASSIFICATION, dans l'ordre : un refus de classe (`CLASS_RETROSPECTIVE_EXPOSED` ou
    `CLASS_UNDETERMINED`), SINON `LEVEL_NOT_PROSPECTIVE_ANCHORED` ; puis `OVERLAPPING_REGISTRATION` si un rival
    recoupe `W`. Un tuple vide n'est JAMAIS une autorisation : c'est une condition nécessaire, jamais suffisante.
    L'unicité par campagne du registre (23.10) et l'acquisition exclusive du Claim (E2) restent les seules
    autorités ; une classification d'étage ADMITTED à CONSUMED ne sert qu'à l'audit."""
    if type(result) is not ExposureClassificationResult:
        raise TypeError("result doit être un ExposureClassificationResult.")
    refusals = []
    if result.classification is ExposureClass.RETROSPECTIVE_EXPOSED:
        refusals.append(AdmissionRefusal.CLASS_RETROSPECTIVE_EXPOSED)
    elif result.classification is ExposureClass.UNDETERMINED:
        refusals.append(AdmissionRefusal.CLASS_UNDETERMINED)
    elif result.chronology_level is not ChronologyLevel.PROSPECTIVE_ANCHORED:
        refusals.append(AdmissionRefusal.LEVEL_NOT_PROSPECTIVE_ANCHORED)
    if result.overlapping_registration_ids:
        refusals.append(AdmissionRefusal.OVERLAPPING_REGISTRATION)
    return tuple(refusals)


def classification_result_to_record(result: ExposureClassificationResult) -> dict:
    """Enregistrement JSON-sérialisable du résultat : 16 clés dans l'ordre des champs, enums en `.value`,
    tuples en listes. Aucune horloge, aucune persistance."""
    if type(result) is not ExposureClassificationResult:
        raise TypeError("result doit être un ExposureClassificationResult.")
    return {
        "rules_version": result.rules_version,
        "classification": result.classification.value,
        "chronology_level": result.chronology_level.value,
        "inventory_id": result.inventory_id,
        "inventory_content_digest": result.inventory_content_digest,
        "input_digest": result.input_digest,
        "classification_id": result.classification_id,
        "t_sel_effective_utc": result.t_sel_effective_utc,
        "t_sel_lowering_ignored_seqs": list(result.t_sel_lowering_ignored_seqs),
        "established_exposure_ids": list(result.established_exposure_ids),
        "unresolved_source_ids": list(result.unresolved_source_ids),
        "overlapping_registration_ids": list(result.overlapping_registration_ids),
        "absorbed_own_record_ids": list(result.absorbed_own_record_ids),
        "own_anomaly_ids": list(result.own_anomaly_ids),
        "conditions": [
            {"condition": c.condition, "status": c.status.value, "reasons": [r.value for r in c.reasons]}
            for c in result.conditions
        ],
        "reasons": [r.value for r in result.reasons],
    }
