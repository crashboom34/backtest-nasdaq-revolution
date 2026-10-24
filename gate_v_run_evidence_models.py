"""
gate_v_run_evidence_models.py — K1 Étape 2, lot L2 : modèles purs `RunDataCoverage`, `RunSession`, `RunSeal` (contrat R9 section 5, PROPOSED).

Module PUR : stdlib et `gate_v_frame_digest` (L1) seulement, aucun accès disque, réseau, registre, horloge ni pandas. Il ne représente que des
FAITS et des RÉFÉRENCES DE HASH fournis par l'appelant, vérifie leur cohérence interne et croisée, et refuse tout le reste. Il n'observe aucune
lecture réelle d'un worker, ne prouve ni chronologie ni durabilité (un état terminal PUR n'est pas une preuve d'ordre dans le temps), n'invente
aucune couverture à partir de TRAIN/TEST, et n'émet aucun verdict FRESH / NO_OVERLAP / admission / Claim ni aucun objet d'autorisation.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from functools import cached_property
from datetime import datetime
from enum import Enum

import gate_v_frame_digest as fd

__all__ = [
    "BINDING_DERIVED", "BINDING_MARKET_DATA_FRAME", "COVERAGE_SEMANTICS_VERSION", "EvidenceRefusal", "EvidenceRefused", "LOADER_ID",
    "EvidenceChainFacts", "PHASE_COVERED", "PHASE_EMPTY", "PHASE_IN_SESSIONS", "PHASE_RUN_RECORDED", "PHASE_SEALED", "RunDataCoverage", "RunEvidenceState",
    "RunSeal", "RunSession", "SEAL_SEMANTICS_VERSION", "SESSION_SEMANTICS_VERSION", "WALK_FORWARD_OUTPUT_ROOT", "apply_coverage", "apply_run_record",
    "apply_seal", "apply_session", "initial_state", "normative_json_bytes", "parse_normative_json", "replay", "verify_run_evidence",
]

COVERAGE_SEMANTICS_VERSION = "gate_v_run_data_coverage_v1"
SESSION_SEMANTICS_VERSION = "gate_v_run_session_v1"
BINDING_MARKET_DATA_FRAME = "MARKET_DATA_FRAME"
BINDING_DERIVED = "DERIVED"
LOADER_ID = "gate_v_s0_frame_loader_v1"
SNAPSHOT_PREFIX = "local_csv:sha256:"


class EvidenceRefusal(str, Enum):
    """Vocabulaire FERMÉ des refus : une entrée hors contrat ne produit aucun modèle."""

    BAD_TYPE = "BAD_TYPE"                    # type Python inattendu (bool pour un entier, sous-classe de dict, ...)
    BAD_VALUE = "BAD_VALUE"                  # valeur hors du domaine (constante différente, nombre hors borne, texte vide)
    BAD_VERSION = "BAD_VERSION"
    BAD_RUN_ID = "BAD_RUN_ID"
    BAD_HEX = "BAD_HEX"
    BAD_INSTANT = "BAD_INSTANT"
    BAD_FRAME = "BAD_FRAME"                  # faits de trame incohérents entre eux (bornes, durée, colonnes)
    SNAPSHOT_MISMATCH = "SNAPSHOT_MISMATCH"  # identité de snapshot différente de `local_csv:sha256:<source_sha256>`
    MISSING_FIELD = "MISSING_FIELD"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    FLOAT_FORBIDDEN = "FLOAT_FORBIDDEN"      # aucun flottant dans le JSON normatif
    BOM = "BOM"
    NOT_UTF8 = "NOT_UTF8"
    JSON_INVALID = "JSON_INVALID"
    NOT_OBJECT = "NOT_OBJECT"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    NON_CANONICAL = "NON_CANONICAL"          # JSON valide mais octets différents des octets normatifs
    OUTPUT_CONFLICT = "OUTPUT_CONFLICT"      # liste de sorties qu'aucun système de fichiers ne peut contenir (fichier/dossier, casse)
    UNSUPPORTED_BINDING_KIND = "UNSUPPORTED_BINDING_KIND"  # `DERIVED` : hors du périmètre de ce lot
    FRAME_BEFORE_MISMATCH = "FRAME_BEFORE_MISMATCH"  # digest de la trame présentée à la session différent de celui de la couverture
    ROW_COUNT_MISMATCH = "ROW_COUNT_MISMATCH"
    VALIDATION_TYPE_MISMATCH = "VALIDATION_TYPE_MISMATCH"  # type déclaré différent de celui que porte l'identité du run
    SESSION_MISSING = "SESSION_MISSING"      # session attendue ou listée mais absente
    SESSION_DUPLICATE = "SESSION_DUPLICATE"
    SESSION_GAP = "SESSION_GAP"              # indices de session non consécutifs 1..n
    SEAL_ORDER = "SEAL_ORDER"                # liste non triée dans l'ordre canonique
    OUTPUT_ORDER = "OUTPUT_ORDER"
    OUTPUT_DUPLICATE = "OUTPUT_DUPLICATE"
    OUTPUT_PATH = "OUTPUT_PATH"
    FRAME_AFTER_MISSING = "FRAME_AFTER_MISSING"        # sceau de calcul sans digest « après »
    FRAME_AFTER_UNEXPECTED = "FRAME_AFTER_UNEXPECTED"  # sceau de récupération avec un digest « après »
    DERIVED_CONTENT = "DERIVED_CONTENT"      # un sceau de run dérivé ne porte ni session, ni sortie, ni digest « après »
    HASH_ROLE_COLLISION = "HASH_ROLE_COLLISION"  # un même hash ne peut pas jouer deux rôles (couverture, run, session)
    WRONG_RUN = "WRONG_RUN"                  # session, couverture ou sceau d'un autre run
    COVERAGE_MISMATCH = "COVERAGE_MISMATCH"  # session ou sceau liés à une autre couverture que celle fournie
    SESSION_NOT_LISTED = "SESSION_NOT_LISTED"
    SESSION_HASH_MISMATCH = "SESSION_HASH_MISMATCH"
    RUN_RECORD_MISMATCH = "RUN_RECORD_MISMATCH"
    FRAME_AFTER_MISMATCH = "FRAME_AFTER_MISMATCH"
    CIRCULAR_REFERENCE = "CIRCULAR_REFERENCE"
    MACHINE_ORDER = "MACHINE_ORDER"          # événement hors de l'ordre couverture → sessions → run → sceau
    BINDING_CONFLICT = "BINDING_CONFLICT"    # seconde couverture sémantiquement différente de l'existante
    SEALED_RUN_TERMINAL = "SEALED_RUN_TERMINAL"  # R0 : un run scellé est terminal
    SEAL_DUPLICATE = "SEAL_DUPLICATE"        # second sceau différent du premier


class EvidenceRefused(ValueError):
    """Entrée hors du contrat R9 : aucun modèle. `code` ∈ `EvidenceRefusal`."""

    def __init__(self, code: EvidenceRefusal, message: str = "") -> None:
        super().__init__(f"{code.value}: {message}" if message else code.value)
        self.code = code
        self.detail = message

    def __reduce__(self):  # picklable et copiable
        return (EvidenceRefused, (self.code, self.detail))


def _refuse(code: EvidenceRefusal, message: str):
    raise EvidenceRefused(code, message)


# ── JSON normatif (ADR 0025 23.29.4), réimplémenté ici pour rester pur ; l'identité des octets avec E3-C est verrouillée par test ─────────
def _check_value(value) -> None:
    kind = type(value)
    if value is None or kind in (bool, int, str):
        return
    if kind is float:
        _refuse(EvidenceRefusal.FLOAT_FORBIDDEN, "aucun flottant dans le JSON normatif")
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                _refuse(EvidenceRefusal.BAD_TYPE, "clé non textuelle")
            _check_value(item)
        return
    if kind is list:
        for item in value:
            _check_value(item)
        return
    _refuse(EvidenceRefusal.BAD_TYPE, f"type {kind.__name__} hors du JSON normatif")


def normative_json_bytes(record) -> bytes:
    """Octets normatifs : clés triées, `indent=2`, LF final, UTF-8, `allow_nan=False`, racine objet, aucun flottant."""
    if type(record) is not dict:
        _refuse(EvidenceRefusal.BAD_TYPE, "la racine doit être un objet JSON (dict)")
    try:
        _check_value(record)
        return (json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except EvidenceRefused:
        raise
    except RecursionError:
        _refuse(EvidenceRefusal.BAD_VALUE, "imbrication trop profonde ou structure cyclique")
    except (ValueError, UnicodeEncodeError):
        _refuse(EvidenceRefusal.BAD_VALUE, "représentation impossible (texte non encodable, entier démesuré)")


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            _refuse(EvidenceRefusal.DUPLICATE_KEY, f"clé en double : {key!r}")
        out[key] = value
    return out


def parse_normative_json(raw) -> dict:
    """Octets → objet, en refusant tout ce qui n'est pas EXACTEMENT les octets normatifs de l'objet décodé (BOM, CRLF, indentation, ordre des
    clés, LF final manquant ou double, doublons, NaN/Infinity, flottants, entiers démesurés, imbrication excessive)."""
    if type(raw) is not bytes:
        _refuse(EvidenceRefusal.BAD_TYPE, "raw doit être de type bytes")
    if raw.startswith(b"\xef\xbb\xbf"):
        _refuse(EvidenceRefusal.BOM, "BOM UTF-8 refusé")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _refuse(EvidenceRefusal.NOT_UTF8, "octets non UTF-8")
    try:
        # flottants, NaN et Infinity sont refusés plus bas par normative_json_bytes (FLOAT_FORBIDDEN) : un seul point de refus
        value = json.loads(text, object_pairs_hook=_unique_pairs)
    except EvidenceRefused:
        raise
    except (ValueError, RecursionError):
        _refuse(EvidenceRefusal.JSON_INVALID, "JSON mal formé ou démesuré")
    if type(value) is not dict:
        _refuse(EvidenceRefusal.NOT_OBJECT, "la racine doit être un objet JSON")
    if normative_json_bytes(value) != raw:
        _refuse(EvidenceRefusal.NON_CANONICAL, "octets différents des octets normatifs")
    return value


# ── Primitives de validation (aucune conversion, aucune correction) ───────────────────────────────────────────────────────────────────
_HEX64 = re.compile(r"[0-9a-f]{64}")
_INSTANT = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})\.([0-9]{6})Z")
_RUN_ID = re.compile(r"gate_v_v2_([0-9a-f]{64})_(walk_forward|monte_carlo|parameter_stability_[A-Za-z0-9_-]{1,64})")
_INT64_MAX = 2**63 - 1
_EPOCH = datetime(1970, 1, 1)


def _keys(record, expected, where: str) -> None:
    if type(record) is not dict:
        _refuse(EvidenceRefusal.BAD_TYPE, f"{where} : un objet JSON (dict exact) est exigé")
    if any(type(k) is not str for k in record):
        _refuse(EvidenceRefusal.BAD_TYPE, f"{where} : clé non textuelle")
    missing = sorted(set(expected) - set(record))
    if missing:
        _refuse(EvidenceRefusal.MISSING_FIELD, f"{where} : champ manquant {missing[0]!r}")
    unknown = sorted(set(record) - set(expected))
    if unknown:
        _refuse(EvidenceRefusal.UNKNOWN_FIELD, f"{where} : champ inconnu {unknown[0]!r}")


def _str(value, where: str) -> str:
    if type(value) is not str:
        _refuse(EvidenceRefusal.BAD_TYPE, f"{where} : texte exigé")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        _refuse(EvidenceRefusal.BAD_VALUE, f"{where} : texte non encodable en UTF-8")
    return value


def _hex(value, where: str) -> str:
    if _HEX64.fullmatch(_str(value, where)) is None:
        _refuse(EvidenceRefusal.BAD_HEX, f"{where} : 64 hexadécimaux minuscules exigés")
    return value


def _int(value, where: str, minimum: int, maximum: int = _INT64_MAX) -> int:
    if type(value) is float:
        _refuse(EvidenceRefusal.FLOAT_FORBIDDEN, f"{where} : un entier est exigé, jamais un flottant")
    if type(value) is not int:
        _refuse(EvidenceRefusal.BAD_TYPE, f"{where} : entier exigé (ni booléen, ni texte)")
    if not minimum <= value <= maximum:
        _refuse(EvidenceRefusal.BAD_VALUE, f"{where} : hors de [{minimum}, {maximum}]")
    return value


def _bool(value, where: str) -> bool:
    if type(value) is not bool:
        _refuse(EvidenceRefusal.BAD_TYPE, f"{where} : booléen exigé (ni entier, ni texte)")
    return value


def _const(value, expected: str, where: str, code: EvidenceRefusal = EvidenceRefusal.BAD_VALUE) -> None:
    if _str(value, where) != expected:
        _refuse(code, f"{where} : {expected!r} exigé")


def _instant_us(value, where: str) -> int:
    match = _INSTANT.fullmatch(_str(value, where))
    if match is None:
        _refuse(EvidenceRefusal.BAD_INSTANT, f"{where} : format YYYY-MM-DDTHH:MM:SS.ffffffZ exigé")
    try:
        moment = datetime(*(int(g) for g in match.groups()[:6]))
    except ValueError:
        _refuse(EvidenceRefusal.BAD_INSTANT, f"{where} : date ou heure inexistante")
    delta = moment - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + int(match.group(7))


def _run_id(value, where: str) -> tuple:
    """(identifiant de campagne, type de validation) d'un `validation_run_id` V2 ; le type de Parameter Stability est suivi de son fold."""
    match = _RUN_ID.fullmatch(_str(value, where))
    if match is None:
        _refuse(EvidenceRefusal.BAD_RUN_ID, f"{where} : forme gate_v_v2_<64 hex>_<type> exigée")
    kind = match.group(2)
    return match.group(1), "parameter_stability" if kind.startswith("parameter_stability_") else kind


# ── RunDataCoverage (R9 5.1 ; binding_kind MARKET_DATA_FRAME seulement) ────────────────────────────────────────────────────────────────
_COVERAGE_KEYS = ("coverage_semantics_version", "binding_kind", "validation_run_id", "dataset_snapshot_id", "source_sha256", "source_size_bytes",
                  "loader_id", "frame", "runtime")
_FRAME_KEYS = ("frame_digest_version", "frame_sha256", "row_count", "columns", "bar_duration_seconds", "first_open_utc", "last_open_utc",
               "last_close_utc_exclusive", "time_semantics")
_RUNTIME_KEYS = ("numpy", "pandas", "python")


def _check_columns(columns) -> tuple:
    """Colonnes `[{name, kind}]` → ((nom, kind), ...) ; les règles de nommage et de kind sont celles de L1 (validées par son API publique)."""
    if type(columns) is not list:
        _refuse(EvidenceRefusal.BAD_TYPE, "frame.columns : liste exigée")
    pairs = []
    for index, column in enumerate(columns):
        _keys(column, ("name", "kind"), f"frame.columns[{index}]")
        pairs.append((_str(column["name"], "frame.columns.name"), _str(column["kind"], "frame.columns.kind")))
    try:
        fd.compute_frame_digest(tuple(fd.FrameColumn(name, kind, (0.0 if kind == fd.KIND_F64 else 0,)) for name, kind in pairs))
    except fd.FrameRefused as error:
        _refuse(EvidenceRefusal.BAD_FRAME, f"frame.columns refusées par L1 : {error.code.value}")
    return tuple(pairs)


def _check_frame(frame) -> tuple:
    _keys(frame, _FRAME_KEYS, "frame")
    _const(frame["frame_digest_version"], fd.FRAME_DIGEST_VERSION, "frame.frame_digest_version", EvidenceRefusal.BAD_VERSION)
    sha = _hex(frame["frame_sha256"], "frame.frame_sha256")
    rows = _int(frame["row_count"], "frame.row_count", 1)
    bar = _int(frame["bar_duration_seconds"], "frame.bar_duration_seconds", 1)
    _const(frame["time_semantics"], fd.TIME_SEMANTICS, "frame.time_semantics")
    first = _instant_us(frame["first_open_utc"], "frame.first_open_utc")
    last = _instant_us(frame["last_open_utc"], "frame.last_open_utc")
    close = _instant_us(frame["last_close_utc_exclusive"], "frame.last_close_utc_exclusive")
    columns = _check_columns(frame["columns"])
    step = bar * 1_000_000
    if rows < 2:
        _refuse(EvidenceRefusal.BAD_FRAME, "au moins deux barres")
    if close != last + step:
        _refuse(EvidenceRefusal.BAD_FRAME, "clôture exclusive différente de la dernière ouverture + la durée déclarée")
    if (last - first) % step or rows - 1 > (last - first) // step:
        # rows - 1 <= (last - first) // step couvre aussi « première ouverture strictement avant la dernière » (écart <= 0 ⇒ refus)
        _refuse(EvidenceRefusal.BAD_FRAME, "écart total non multiple de la durée déclarée, ou plus de lignes que de barres possibles")
    return sha, rows, columns, bar, frame["first_open_utc"], frame["last_open_utc"], frame["last_close_utc_exclusive"]


def _check_coverage_record(record) -> dict:
    """Valide un enregistrement de couverture ; rend les champs normalisés (tuples). Aucun champ n'est converti ni corrigé."""
    if type(record) is dict and type(record.get("binding_kind")) is str and record["binding_kind"] == BINDING_DERIVED:
        _refuse(EvidenceRefusal.UNSUPPORTED_BINDING_KIND, "la couverture DERIVED (MC / PS) est hors du périmètre de ce lot")
    _keys(record, _COVERAGE_KEYS, "coverage")
    _const(record["coverage_semantics_version"], COVERAGE_SEMANTICS_VERSION, "coverage_semantics_version", EvidenceRefusal.BAD_VERSION)
    _const(record["binding_kind"], BINDING_MARKET_DATA_FRAME, "binding_kind")
    _, run_type = _run_id(record["validation_run_id"], "validation_run_id")
    if run_type != "walk_forward":
        _refuse(EvidenceRefusal.BAD_RUN_ID, "une couverture MARKET_DATA_FRAME ne concerne qu'un run walk_forward")
    source = _hex(record["source_sha256"], "source_sha256")
    size = _int(record["source_size_bytes"], "source_size_bytes", 1)
    _const(record["loader_id"], LOADER_ID, "loader_id")
    frame = _check_frame(record["frame"])
    if source == frame[0]:
        _refuse(EvidenceRefusal.HASH_ROLE_COLLISION, "le hash des octets de S0 et le digest de la trame sont deux objets distincts (R9 section 2)")
    runtime = record["runtime"]
    _keys(runtime, _RUNTIME_KEYS, "runtime")
    for key in _RUNTIME_KEYS:
        text = _str(runtime[key], f"runtime.{key}")
        if not text.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
            _refuse(EvidenceRefusal.BAD_VALUE, f"runtime.{key} : texte non blanc, sans caractère de contrôle, exigé")
    if _str(record["dataset_snapshot_id"], "dataset_snapshot_id") != SNAPSHOT_PREFIX + source:
        _refuse(EvidenceRefusal.SNAPSHOT_MISMATCH, "dataset_snapshot_id doit valoir local_csv:sha256:<source_sha256>")
    return {"validation_run_id": record["validation_run_id"], "dataset_snapshot_id": record["dataset_snapshot_id"], "source_sha256": source,
            "source_size_bytes": size, "frame_sha256": frame[0], "row_count": frame[1], "columns": frame[2], "bar_duration_seconds": frame[3],
            "first_open_utc": frame[4], "last_open_utc": frame[5], "last_close_utc_exclusive": frame[6],
            "runtime": tuple((key, runtime[key]) for key in _RUNTIME_KEYS)}


@dataclass(frozen=True)
class RunDataCoverage:
    """Couverture d'un run walk-forward : identité exacte du run, du snapshot S0 et de la trame ENTIÈRE de S0. DÉCLARATION scellée de
    l'orchestrateur, jamais preuve d'exécution. Elle ne référence ni le run, ni ses sessions, ni le sceau (graphe acyclique)."""

    validation_run_id: str
    dataset_snapshot_id: str
    source_sha256: str
    source_size_bytes: int
    frame_sha256: str
    row_count: int
    columns: tuple  # ((nom, kind), ...)
    bar_duration_seconds: int
    first_open_utc: str
    last_open_utc: str
    last_close_utc_exclusive: str
    runtime: tuple  # (("numpy", v), ("pandas", v), ("python", v)) : informatif

    def __post_init__(self) -> None:
        if type(self.columns) is not tuple or any(type(c) is not tuple or len(c) != 2 for c in self.columns):
            _refuse(EvidenceRefusal.BAD_TYPE, "columns doit être un tuple de paires (nom, kind)")
        if type(self.runtime) is not tuple or len(self.runtime) != 3 or any(type(p) is not tuple or len(p) != 2 or type(p[0]) is not str for p in self.runtime) \
                or tuple(p[0] for p in self.runtime) != _RUNTIME_KEYS:
            _refuse(EvidenceRefusal.BAD_TYPE, "runtime doit être le tuple ordonné de paires (numpy, pandas, python)")
        _check_coverage_record(self.to_record())

    def __reduce__(self):  # pickle / copy repassent par la validation : aucune porte dérobée autour de `from_record`
        return (type(self).from_record, (self.to_record(),))

    @classmethod
    def from_record(cls, record) -> "RunDataCoverage":
        return cls(**_check_coverage_record(record))

    @classmethod
    def from_bytes(cls, raw) -> "RunDataCoverage":
        return cls.from_record(parse_normative_json(raw))

    @classmethod
    def from_s0_facts(cls, validation_run_id, s0, runtime) -> "RunDataCoverage":
        """Couverture depuis les faits S0 calculés par L1 : le digest de trame n'est JAMAIS recalculé ici ; l'objet reçu est re-validé."""
        if type(s0) is not fd.S0FrameFacts or type(s0.frame) is not fd.FrameFacts:
            _refuse(EvidenceRefusal.BAD_TYPE, "s0 doit être un S0FrameFacts de L1")
        try:
            frame = s0.frame.to_record()
        except (TypeError, ValueError):
            _refuse(EvidenceRefusal.BAD_TYPE, "faits de trame mal formés")
        return cls.from_record({
            "coverage_semantics_version": COVERAGE_SEMANTICS_VERSION, "binding_kind": BINDING_MARKET_DATA_FRAME,
            "validation_run_id": validation_run_id, "dataset_snapshot_id": s0.dataset_snapshot_id, "source_sha256": s0.source_sha256,
            "source_size_bytes": s0.source_size_bytes, "loader_id": LOADER_ID, "frame": frame, "runtime": runtime,
        })

    def to_record(self) -> dict:
        return {
            "coverage_semantics_version": COVERAGE_SEMANTICS_VERSION, "binding_kind": BINDING_MARKET_DATA_FRAME,
            "validation_run_id": self.validation_run_id, "dataset_snapshot_id": self.dataset_snapshot_id, "source_sha256": self.source_sha256,
            "source_size_bytes": self.source_size_bytes, "loader_id": LOADER_ID,
            "frame": {
                "frame_digest_version": fd.FRAME_DIGEST_VERSION, "frame_sha256": self.frame_sha256, "row_count": self.row_count,
                "columns": [{"name": name, "kind": kind} for name, kind in self.columns], "bar_duration_seconds": self.bar_duration_seconds,
                "first_open_utc": self.first_open_utc, "last_open_utc": self.last_open_utc,
                "last_close_utc_exclusive": self.last_close_utc_exclusive, "time_semantics": fd.TIME_SEMANTICS,
            },
            "runtime": dict(self.runtime),
        }

    def to_bytes(self) -> bytes:
        return normative_json_bytes(self.to_record())

    @cached_property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()

    def semantically_equals(self, other) -> bool:
        """Comparaison de récupération R9 6.2 : tous les champs SAUF `runtime` (informatif)."""
        if type(other) is not RunDataCoverage:
            _refuse(EvidenceRefusal.BAD_TYPE, "une RunDataCoverage est exigée")
        mine, theirs = self.to_record(), other.to_record()
        del mine["runtime"], theirs["runtime"]
        return mine == theirs


# ── RunSession (R9 5.2) ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
_SESSION_KEYS = ("session_semantics_version", "validation_run_id", "coverage_sha256", "session_index", "frame_sha256_before", "frame_row_count", "resumed")
_MAX_SESSION_INDEX = 9999  # `run_session_NNNN.json` : quatre chiffres


def _check_session_record(record) -> dict:
    _keys(record, _SESSION_KEYS, "session")
    _const(record["session_semantics_version"], SESSION_SEMANTICS_VERSION, "session_semantics_version", EvidenceRefusal.BAD_VERSION)
    _, run_type = _run_id(record["validation_run_id"], "validation_run_id")
    if run_type != "walk_forward":
        _refuse(EvidenceRefusal.BAD_RUN_ID, "une session de calcul ne concerne qu'un run walk_forward")
    return {"validation_run_id": record["validation_run_id"], "coverage_sha256": _hex(record["coverage_sha256"], "coverage_sha256"),
            "session_index": _int(record["session_index"], "session_index", 1, _MAX_SESSION_INDEX),
            "frame_sha256_before": _hex(record["frame_sha256_before"], "frame_sha256_before"),
            "frame_row_count": _int(record["frame_row_count"], "frame_row_count", 1), "resumed": _bool(record["resumed"], "resumed")}


@dataclass(frozen=True)
class RunSession:
    """Une session d'exécution d'un run walk-forward, destinée à être créée AVANT son calcul (R9 6.2 ; ce modèle ne prouve pas cet ordre) : elle
    référence la couverture (jamais l'inverse) et déclare le digest de la trame qu'on lui a PRÉSENTÉE. Ce n'est pas une preuve que le worker a lu
    cette trame. Le digest « après » n'existe pas ici : il est postérieur au calcul et vit dans le `RunSeal`. `resumed` est une déclaration
    libre (aucune contrainte croisée n'est imposée)."""

    validation_run_id: str
    coverage_sha256: str
    session_index: int
    frame_sha256_before: str
    frame_row_count: int
    resumed: bool

    def __post_init__(self) -> None:
        _check_session_record(self.to_record())

    def __reduce__(self):
        return (type(self).from_record, (self.to_record(),))

    @classmethod
    def from_record(cls, record) -> "RunSession":
        return cls(**_check_session_record(record))

    @classmethod
    def from_bytes(cls, raw) -> "RunSession":
        return cls.from_record(parse_normative_json(raw))

    @classmethod
    def open_for(cls, coverage, session_index, frame_sha256_before, frame_row_count, resumed) -> "RunSession":
        """Ouverture d'une session contre une couverture : si la trame présentée diffère (digest ou nombre de lignes), AUCUNE session n'est
        produite (R9 I-C4 : sans session, aucune session ne peut être référencée par la suite de la chaîne)."""
        if type(coverage) is not RunDataCoverage:
            _refuse(EvidenceRefusal.BAD_TYPE, "coverage doit être une RunDataCoverage")
        session = cls.from_record({
            "session_semantics_version": SESSION_SEMANTICS_VERSION, "validation_run_id": coverage.validation_run_id,
            "coverage_sha256": coverage.sha256, "session_index": session_index, "frame_sha256_before": frame_sha256_before,
            "frame_row_count": frame_row_count, "resumed": resumed,
        })
        if session.frame_sha256_before != coverage.frame_sha256:
            _refuse(EvidenceRefusal.FRAME_BEFORE_MISMATCH, "la trame présentée n'a pas le digest de la couverture")
        if session.frame_row_count != coverage.row_count:
            _refuse(EvidenceRefusal.ROW_COUNT_MISMATCH, "la trame présentée n'a pas le nombre de lignes de la couverture")
        return session

    def to_record(self) -> dict:
        return {"session_semantics_version": SESSION_SEMANTICS_VERSION, "validation_run_id": self.validation_run_id,
                "coverage_sha256": self.coverage_sha256, "session_index": self.session_index, "frame_sha256_before": self.frame_sha256_before,
                "frame_row_count": self.frame_row_count, "resumed": self.resumed}

    def to_bytes(self) -> bytes:
        return normative_json_bytes(self.to_record())

    @cached_property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()


# ── RunSeal (R9 5.3) ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
SEAL_SEMANTICS_VERSION = "gate_v_run_seal_v1"
_VALIDATION_TYPES = ("walk_forward", "monte_carlo", "parameter_stability")
_SEAL_KEYS = ("seal_semantics_version", "validation_run_id", "validation_type", "run_record_sha256", "coverage_sha256", "sessions", "output_artifacts",
              "frame_sha256_after", "finalized_by_recovery")
WALK_FORWARD_OUTPUT_ROOT = "walk_forward/"


_MAX_PATH_CHARS = 4096     # bornes de prudence communes aux systèmes de fichiers courants ; protègent aussi la validation (entrées hostiles)
_MAX_SEGMENT_BYTES = 255


def _output_path(value, where: str) -> str:
    path = _str(value, where)
    if len(path) > _MAX_PATH_CHARS or any(len(part.encode("utf-8")) > _MAX_SEGMENT_BYTES for part in path.split("/")):
        _refuse(EvidenceRefusal.OUTPUT_PATH, f"{where} : chemin de plus de {_MAX_PATH_CHARS} caractères ou segment de plus de {_MAX_SEGMENT_BYTES} octets")
    if ("\\" in path or ":" in path or any(not part or part.endswith((".", " ")) for part in path.split("/"))  # « . » et « .. » se terminent par un point
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in path) or unicodedata.normalize("NFC", path) != path):
        _refuse(EvidenceRefusal.OUTPUT_PATH, f"{where} : chemin relatif POSIX normalisé NFC exigé (ni vide, ni absolu, ni '..', ni '\\', ni ':', "
                                             "ni segment terminé par un point ou une espace)")
    return path


def _check_seal_sessions(sessions) -> tuple:
    if type(sessions) is not list:
        _refuse(EvidenceRefusal.BAD_TYPE, "sessions : liste exigée")
    entries = []
    for index, entry in enumerate(sessions):
        _keys(entry, ("session_index", "session_sha256"), f"sessions[{index}]")
        entries.append((_int(entry["session_index"], "sessions.session_index", 1, _MAX_SESSION_INDEX), _hex(entry["session_sha256"], "sessions.session_sha256")))
    indices = [i for i, _ in entries]
    if len(set(indices)) != len(indices) or len({h for _, h in entries}) != len(entries):
        _refuse(EvidenceRefusal.SESSION_DUPLICATE, "indice ou hash de session répété")
    if sorted(indices) != list(range(1, len(indices) + 1)):
        _refuse(EvidenceRefusal.SESSION_GAP, "les indices de session doivent être consécutifs à partir de 1")
    if indices != sorted(indices):
        _refuse(EvidenceRefusal.SEAL_ORDER, "sessions non triées par indice")
    return tuple(entries)


def _check_seal_outputs(outputs) -> tuple:
    if type(outputs) is not list:
        _refuse(EvidenceRefusal.BAD_TYPE, "output_artifacts : liste exigée")
    entries = []
    for index, entry in enumerate(outputs):
        _keys(entry, ("path", "sha256", "size"), f"output_artifacts[{index}]")
        entries.append((_output_path(entry["path"], "output_artifacts.path"), _hex(entry["sha256"], "output_artifacts.sha256"),
                        _int(entry["size"], "output_artifacts.size", 0)))
    paths = [p for p, _, _ in entries]
    if len(set(paths)) != len(paths):
        _refuse(EvidenceRefusal.OUTPUT_DUPLICATE, "chemin de sortie répété")
    if paths != sorted(paths):
        _refuse(EvidenceRefusal.OUTPUT_ORDER, "sorties non triées par chemin")
    folded = [p.casefold() for p in paths]
    if len(set(folded)) != len(folded):
        _refuse(EvidenceRefusal.OUTPUT_CONFLICT, "deux sorties ne diffèrent que par la casse")
    # « / » → NUL (inférieur à tout caractère admis) : les descendants d'un chemin suivent ce chemin immédiatement ⇒ contrôle des voisins, O(n log n)
    ordered = sorted(p.replace("/", "\0") for p in folded)
    if any(following.startswith(path + "\0") for path, following in zip(ordered, ordered[1:])):
        _refuse(EvidenceRefusal.OUTPUT_CONFLICT, "un chemin est à la fois fichier et dossier")
    return tuple(entries)


def _check_seal_record(record) -> dict:
    _keys(record, _SEAL_KEYS, "seal")
    _const(record["seal_semantics_version"], SEAL_SEMANTICS_VERSION, "seal_semantics_version", EvidenceRefusal.BAD_VERSION)
    _, run_type = _run_id(record["validation_run_id"], "validation_run_id")
    declared = _str(record["validation_type"], "validation_type")
    if declared not in _VALIDATION_TYPES:
        _refuse(EvidenceRefusal.BAD_VALUE, "validation_type hors de walk_forward / monte_carlo / parameter_stability")
    if declared != run_type:
        _refuse(EvidenceRefusal.VALIDATION_TYPE_MISMATCH, "validation_type différent de celui de l'identité du run")
    run_hash, coverage_hash = _hex(record["run_record_sha256"], "run_record_sha256"), _hex(record["coverage_sha256"], "coverage_sha256")
    after = record["frame_sha256_after"]
    if after is not None:
        _hex(after, "frame_sha256_after")
    recovery = _bool(record["finalized_by_recovery"], "finalized_by_recovery")
    if declared == "walk_forward":
        sessions, outputs = _check_seal_sessions(record["sessions"]), _check_seal_outputs(record["output_artifacts"])
        if not sessions:
            _refuse(EvidenceRefusal.SESSION_MISSING, "un walk-forward scellé liste au moins une session")
        if any(not path.startswith(WALK_FORWARD_OUTPUT_ROOT) for path, _, _ in outputs):
            _refuse(EvidenceRefusal.OUTPUT_PATH, "toute sortie scellée d'un walk-forward est sous walk_forward/")
        if after is None and not recovery:
            _refuse(EvidenceRefusal.FRAME_AFTER_MISSING, "un sceau de calcul porte le digest « après »")
        if after is not None and recovery:
            _refuse(EvidenceRefusal.FRAME_AFTER_UNEXPECTED, "un sceau de récupération ne porte aucun digest « après »")
    else:
        if type(record["sessions"]) is not list or type(record["output_artifacts"]) is not list:
            _refuse(EvidenceRefusal.BAD_TYPE, "sessions et output_artifacts : listes exigées")
        if record["sessions"] or record["output_artifacts"] or after is not None:
            _refuse(EvidenceRefusal.DERIVED_CONTENT, "un sceau dérivé ne porte ni session, ni sortie, ni digest « après »")
        sessions, outputs = (), ()
    if run_hash == coverage_hash or {run_hash, coverage_hash} & {h for _, h in sessions}:
        _refuse(EvidenceRefusal.HASH_ROLE_COLLISION, "un même hash ne peut pas désigner à la fois la couverture, le run et une session")
    return {"validation_run_id": record["validation_run_id"], "validation_type": declared, "run_record_sha256": run_hash, "coverage_sha256": coverage_hash,
            "sessions": sessions, "output_artifacts": outputs, "frame_sha256_after": after, "finalized_by_recovery": recovery}


@dataclass(frozen=True)
class RunSeal:
    """Sceau terminal d'un run : référence les octets du run, la couverture, TOUTES les sessions et les sorties, sans horodatage. L'état
    « scellé » de ce modèle pur est une DÉCLARATION cohérente, pas une preuve de chronologie ni de durabilité."""

    validation_run_id: str
    validation_type: str
    run_record_sha256: str
    coverage_sha256: str
    sessions: tuple           # ((session_index, session_sha256), ...)
    output_artifacts: tuple   # ((path, sha256, size), ...)
    frame_sha256_after: object  # hex ou None
    finalized_by_recovery: bool

    def __post_init__(self) -> None:
        if type(self.sessions) is not tuple or any(type(s) is not tuple or len(s) != 2 for s in self.sessions):
            _refuse(EvidenceRefusal.BAD_TYPE, "sessions doit être un tuple de paires (indice, hash)")
        if type(self.output_artifacts) is not tuple or any(type(o) is not tuple or len(o) != 3 for o in self.output_artifacts):
            _refuse(EvidenceRefusal.BAD_TYPE, "output_artifacts doit être un tuple de triplets (chemin, hash, taille)")
        _check_seal_record(self.to_record())

    def __reduce__(self):
        return (type(self).from_record, (self.to_record(),))

    @classmethod
    def from_record(cls, record) -> "RunSeal":
        return cls(**_check_seal_record(record))

    @classmethod
    def from_bytes(cls, raw) -> "RunSeal":
        return cls.from_record(parse_normative_json(raw))

    @classmethod
    def for_walk_forward(cls, coverage, sessions, run_record_sha256, output_artifacts, frame_sha256_after, finalized_by_recovery) -> "RunSeal":
        """Sceau d'un walk-forward construit DEPUIS les modèles : les sessions listées sont celles fournies (donc aucun sceau sur des sessions
        absentes), les sorties sont triées par chemin, puis toute la chaîne est vérifiée avant de rendre le sceau."""
        if type(coverage) is not RunDataCoverage:
            _refuse(EvidenceRefusal.BAD_TYPE, "coverage doit être une RunDataCoverage")
        ordered = sorted(_session_models(sessions), key=lambda s: s.session_index)
        if type(output_artifacts) not in (list, tuple) or any(type(o) is not tuple or len(o) != 3 or type(o[0]) is not str for o in output_artifacts):
            _refuse(EvidenceRefusal.BAD_TYPE, "output_artifacts : liste de triplets (chemin texte, sha256, taille) exigée")
        seal = cls.from_record({
            "seal_semantics_version": SEAL_SEMANTICS_VERSION, "validation_run_id": coverage.validation_run_id, "validation_type": "walk_forward",
            "run_record_sha256": run_record_sha256, "coverage_sha256": coverage.sha256,
            "sessions": [{"session_index": s.session_index, "session_sha256": s.sha256} for s in ordered],
            "output_artifacts": [{"path": p, "sha256": h, "size": n} for p, h, n in sorted(output_artifacts, key=lambda o: o[0])],
            "frame_sha256_after": frame_sha256_after, "finalized_by_recovery": finalized_by_recovery,
        })
        verify_run_evidence(coverage, ordered, seal, run_record_sha256)
        return seal

    def to_record(self) -> dict:
        return {
            "seal_semantics_version": SEAL_SEMANTICS_VERSION, "validation_run_id": self.validation_run_id, "validation_type": self.validation_type,
            "run_record_sha256": self.run_record_sha256, "coverage_sha256": self.coverage_sha256,
            "sessions": [{"session_index": index, "session_sha256": digest} for index, digest in self.sessions],
            "output_artifacts": [{"path": path, "sha256": digest, "size": size} for path, digest, size in self.output_artifacts],
            "frame_sha256_after": self.frame_sha256_after, "finalized_by_recovery": self.finalized_by_recovery,
        }

    def to_bytes(self) -> bytes:
        return normative_json_bytes(self.to_record())

    @cached_property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()


# ── Vérification croisée de la chaîne couverture → sessions → run → sceau ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class EvidenceChainFacts:
    """Hashs d'une chaîne que `verify_run_evidence` a jugée COHÉRENTE. Ce n'est ni un verdict, ni une autorisation, et ce n'est pas une preuve :
    ni d'absence d'exposition, ni de lecture réelle, ni d'ordre dans le temps. Seule la SORTIE de `verify_run_evidence` a un sens ; une
    construction directe (permise, car l'objet est un simple conteneur de hashs) applique les mêmes contrôles de format, d'unicité des sessions
    et de rôles de hash distincts, mais ne vérifie aucune référence croisée et ne prouve donc rien. Aucune API de ce module ne consomme cet objet."""

    validation_run_id: str
    coverage_sha256: str
    session_sha256s: tuple
    run_record_sha256: str
    seal_sha256: str
    finalized_by_recovery: bool

    def __post_init__(self) -> None:
        _, run_type = _run_id(self.validation_run_id, "validation_run_id")
        if run_type != "walk_forward":
            _refuse(EvidenceRefusal.BAD_RUN_ID, "une chaîne de preuve ne concerne qu'un run walk_forward")
        _hex(self.coverage_sha256, "coverage_sha256")
        _hex(self.run_record_sha256, "run_record_sha256")
        _hex(self.seal_sha256, "seal_sha256")
        _bool(self.finalized_by_recovery, "finalized_by_recovery")
        if type(self.session_sha256s) is not tuple:
            _refuse(EvidenceRefusal.BAD_TYPE, "session_sha256s doit être un tuple")
        if not self.session_sha256s:
            _refuse(EvidenceRefusal.SESSION_MISSING, "une chaîne walk_forward comporte au moins une session")
        for digest in self.session_sha256s:
            _hex(digest, "session_sha256s")
        if len(set(self.session_sha256s)) != len(self.session_sha256s):
            _refuse(EvidenceRefusal.SESSION_DUPLICATE, "hash de session répété")
        roles = (self.coverage_sha256, self.run_record_sha256, self.seal_sha256)
        if len(set(roles)) != 3 or set(roles) & set(self.session_sha256s):
            _refuse(EvidenceRefusal.HASH_ROLE_COLLISION, "couverture, run, sceau et sessions doivent avoir des hashs distincts")

    def __reduce__(self):
        return (type(self), (self.validation_run_id, self.coverage_sha256, self.session_sha256s, self.run_record_sha256, self.seal_sha256,
                             self.finalized_by_recovery))


def _session_models(sessions) -> tuple:
    if type(sessions) not in (list, tuple) or any(type(s) is not RunSession for s in sessions):
        _refuse(EvidenceRefusal.BAD_TYPE, "sessions : liste ou tuple de RunSession exigé")
    return tuple(sessions)


def _check_session_against(coverage: RunDataCoverage, s: RunSession) -> None:
    """Références d'une session à sa couverture : même run, même couverture, même digest « avant » et même nombre de lignes."""
    if s.validation_run_id != coverage.validation_run_id:
        _refuse(EvidenceRefusal.WRONG_RUN, f"session {s.session_index} : autre validation_run_id que la couverture")
    if s.coverage_sha256 != coverage.sha256:
        _refuse(EvidenceRefusal.COVERAGE_MISMATCH, f"session {s.session_index} : liée à une autre couverture")
    if s.frame_sha256_before != coverage.frame_sha256:
        _refuse(EvidenceRefusal.FRAME_BEFORE_MISMATCH, f"session {s.session_index} : digest « avant » différent de la couverture")
    if s.frame_row_count != coverage.row_count:
        _refuse(EvidenceRefusal.ROW_COUNT_MISMATCH, f"session {s.session_index} : nombre de lignes différent de la couverture")


def _has_cycle(edges: dict) -> bool:
    state = {}
    for start in edges:
        if state.get(start):
            continue
        state[start] = 1
        stack = [(start, iter(edges.get(start, ())))]
        while stack:
            node, successors = stack[-1]
            for successor in successors:
                if state.get(successor) == 1:
                    return True
                if not state.get(successor):
                    state[successor] = 1
                    stack.append((successor, iter(edges.get(successor, ()))))
                    break
            else:
                state[node] = 2
                stack.pop()
    return False


def verify_run_evidence(coverage, sessions, seal, run_record_sha256, run_references=()) -> EvidenceChainFacts:
    """Vérifie les références croisées d'un walk-forward : même run, même couverture, digests « avant » et « après », exhaustivité et unicité des
    sessions, octets du run, rôles de hash distincts, graphe acyclique. `run_references` = hashs que les octets du run citent (fournis par
    l'appelant ; le run historique n'en contient aucun). Aucune lecture, aucun verdict ; le premier défaut rencontré est rapporté."""
    if type(coverage) is not RunDataCoverage or type(seal) is not RunSeal:
        _refuse(EvidenceRefusal.BAD_TYPE, "coverage et seal doivent être une RunDataCoverage et un RunSeal")
    supplied = _session_models(sessions)
    run_hash = _hex(run_record_sha256, "run_record_sha256")
    if type(run_references) not in (list, tuple, set, frozenset):
        _refuse(EvidenceRefusal.BAD_TYPE, "run_references : collection de hashs exigée")
    references = tuple(_hex(h, "run_references") for h in run_references)
    if seal.validation_type != "walk_forward":
        _refuse(EvidenceRefusal.UNSUPPORTED_BINDING_KIND, "la chaîne d'un run dérivé suppose une couverture DERIVED, hors du périmètre de ce lot")
    if seal.validation_run_id != coverage.validation_run_id:
        _refuse(EvidenceRefusal.WRONG_RUN, "couverture et sceau doivent porter le même validation_run_id")
    if seal.coverage_sha256 != coverage.sha256:
        _refuse(EvidenceRefusal.COVERAGE_MISMATCH, "sceau lié à une autre couverture")
    for s in supplied:
        _check_session_against(coverage, s)
    session_hashes = [s.sha256 for s in supplied]
    roles = (coverage.sha256, run_hash, seal.sha256)
    if len(set(roles)) != 3 or set(roles) & set(session_hashes) or run_hash in (coverage.frame_sha256, coverage.source_sha256):
        _refuse(EvidenceRefusal.HASH_ROLE_COLLISION, "couverture, run, sceau et sessions doivent avoir des hashs distincts")
    indices = [s.session_index for s in supplied]
    if len(set(indices)) != len(indices):
        _refuse(EvidenceRefusal.SESSION_DUPLICATE, "indice de session fourni plusieurs fois")
    if sorted(indices) != list(range(1, len(indices) + 1)):
        _refuse(EvidenceRefusal.SESSION_GAP, "les indices de session fournis doivent être consécutifs à partir de 1")
    by_index = {s.session_index: s for s in supplied}
    for index, digest in seal.sessions:
        if index not in by_index:
            _refuse(EvidenceRefusal.SESSION_MISSING, f"le sceau liste la session {index}, absente des sessions fournies")
        if by_index[index].sha256 != digest:
            _refuse(EvidenceRefusal.SESSION_HASH_MISMATCH, f"session {index} : hash différent de celui du sceau")
    if len(seal.sessions) != len(supplied):
        _refuse(EvidenceRefusal.SESSION_NOT_LISTED, "une session fournie n'est pas listée par le sceau")
    if seal.run_record_sha256 != run_hash:
        _refuse(EvidenceRefusal.RUN_RECORD_MISMATCH, "le sceau référence d'autres octets de run")
    if seal.frame_sha256_after is not None and seal.frame_sha256_after != coverage.frame_sha256:
        _refuse(EvidenceRefusal.FRAME_AFTER_MISMATCH, "digest « après » différent de celui de la couverture (la cause n'est pas établie par ce modèle)")
    edges = {coverage.sha256: (), run_hash: references, seal.sha256: (coverage.sha256, run_hash, *session_hashes)}
    edges.update({digest: (coverage.sha256,) for digest in session_hashes})
    if _has_cycle(edges):
        _refuse(EvidenceRefusal.CIRCULAR_REFERENCE, "le graphe de hash contient un cycle")
    return EvidenceChainFacts(coverage.validation_run_id, coverage.sha256, tuple(by_index[i].sha256 for i in sorted(by_index)), run_hash, seal.sha256,
                              seal.finalized_by_recovery)


# ── Machine d'états PURE : couverture → sessions → run → sceau terminal ──────────────────────────────────────────────────────────────
# Ce n'est PAS un journal ni une preuve : un état est une valeur immuable ; « scellé » signifie seulement qu'un sceau cohérent a été appliqué
# à cet état. Rien ici ne prouve l'ordre réel des écritures, leur durabilité, ni qu'aucun autre état concurrent n'existe (R-conc, R-mut).
PHASE_EMPTY = "EMPTY"
PHASE_COVERED = "COVERED"
PHASE_IN_SESSIONS = "IN_SESSIONS"
PHASE_RUN_RECORDED = "RUN_RECORDED"
PHASE_SEALED = "SEALED"


@dataclass(frozen=True)
class RunEvidenceState:
    """Valeur immuable : ce qui est accumulé sur un run (couverture, sessions, hash du run, sceau). Ce n'est pas un journal et cela ne prouve ni
    l'ordre réel des écritures, ni leur durabilité, ni l'absence d'un autre état concurrent. `phase` se déduit du CONTENU : un état construit
    directement avec des parties cohérentes est SEALED sans historique d'événements ; ce modèle ne prouve donc pas comment il a été atteint.
    Le constructeur rejette toute combinaison incohérente (point unique des invariants de la machine)."""

    coverage: object = None           # RunDataCoverage ou None
    sessions: tuple = ()               # RunSession consécutives 1..n
    run_record_sha256: object = None   # hex ou None
    seal: object = None                # RunSeal ou None

    def __post_init__(self) -> None:
        if self.coverage is not None and type(self.coverage) is not RunDataCoverage:
            _refuse(EvidenceRefusal.BAD_TYPE, "coverage doit être une RunDataCoverage ou None")
        if type(self.sessions) is not tuple or any(type(s) is not RunSession for s in self.sessions):
            _refuse(EvidenceRefusal.BAD_TYPE, "sessions doit être un tuple de RunSession")
        if self.seal is not None and type(self.seal) is not RunSeal:
            _refuse(EvidenceRefusal.BAD_TYPE, "seal doit être un RunSeal ou None")
        if self.run_record_sha256 is not None:
            _hex(self.run_record_sha256, "run_record_sha256")
        if (self.sessions and self.coverage is None) or (self.run_record_sha256 is not None and not self.sessions) \
                or (self.seal is not None and self.run_record_sha256 is None):
            _refuse(EvidenceRefusal.MACHINE_ORDER, "état incohérent : un élément suit un prédécesseur absent")
        for position, s in enumerate(self.sessions, start=1):
            _check_session_against(self.coverage, s)
            if s.session_index != position:
                _refuse(EvidenceRefusal.SESSION_GAP, "les sessions d'un état sont consécutives à partir de 1")
        if self.run_record_sha256 is not None and (
                self.run_record_sha256 in (self.coverage.sha256, self.coverage.frame_sha256, self.coverage.source_sha256)
                or self.run_record_sha256 in {s.sha256 for s in self.sessions}):
            _refuse(EvidenceRefusal.HASH_ROLE_COLLISION, "le hash du run ne peut pas être celui de la couverture, de sa trame, de sa source ou d'une session")
        if self.seal is not None:
            verify_run_evidence(self.coverage, self.sessions, self.seal, self.run_record_sha256)

    def __reduce__(self):  # le constructeur revalide l'état entier
        return (type(self), (self.coverage, self.sessions, self.run_record_sha256, self.seal))

    @property
    def phase(self) -> str:
        if self.seal is not None:
            return PHASE_SEALED
        if self.run_record_sha256 is not None:
            return PHASE_RUN_RECORDED
        if self.sessions:
            return PHASE_IN_SESSIONS
        return PHASE_COVERED if self.coverage is not None else PHASE_EMPTY


def initial_state() -> RunEvidenceState:
    return RunEvidenceState()


def _state(state) -> RunEvidenceState:
    if type(state) is not RunEvidenceState:
        _refuse(EvidenceRefusal.BAD_TYPE, "state doit être un RunEvidenceState")
    return state


def _terminal(state: RunEvidenceState) -> None:
    if state.seal is not None:
        _refuse(EvidenceRefusal.SEALED_RUN_TERMINAL, "R0 : un run scellé est terminal, aucun événement n'est accepté")


def apply_coverage(state, coverage) -> RunEvidenceState:
    """Publie la couverture. Déjà présente : l'existante FAIT FOI ; sémantiquement égale (hors `runtime`) ⇒ état inchangé, sinon BINDING_CONFLICT."""
    state = _state(state)
    if type(coverage) is not RunDataCoverage:
        _refuse(EvidenceRefusal.BAD_TYPE, "coverage doit être une RunDataCoverage")
    _terminal(state)
    if state.coverage is None:
        return RunEvidenceState(coverage, state.sessions, state.run_record_sha256, state.seal)
    if state.coverage.semantically_equals(coverage):
        return state
    _refuse(EvidenceRefusal.BINDING_CONFLICT, "couverture sémantiquement différente de celle déjà publiée")


def apply_session(state, session) -> RunEvidenceState:
    """Ouvre la session suivante. Une session ne se rejoue JAMAIS ; pas de session sans couverture ni après le run."""
    state = _state(state)
    if type(session) is not RunSession:
        _refuse(EvidenceRefusal.BAD_TYPE, "session doit être une RunSession")
    _terminal(state)
    if state.coverage is None or state.run_record_sha256 is not None:
        _refuse(EvidenceRefusal.MACHINE_ORDER, "une session suppose une couverture et précède le run")
    if session.session_index <= len(state.sessions):
        _refuse(EvidenceRefusal.SESSION_DUPLICATE, f"la session {session.session_index} existe déjà : une session ne se rejoue jamais")
    # indice consécutif, même run, même couverture, mêmes digests : imposés par RunEvidenceState.__post_init__ (point unique des invariants)
    return RunEvidenceState(state.coverage, state.sessions + (session,), state.run_record_sha256, state.seal)


def apply_run_record(state, run_record_sha256) -> RunEvidenceState:
    """Enregistre les octets du run (hash). Une seule fois : identique ⇒ inchangé ; différent ⇒ RUN_RECORD_MISMATCH (le modèle pur ne
    reproduit PAS le remplacement concurrent possible en réalité, R-conc)."""
    state = _state(state)
    run_hash = _hex(run_record_sha256, "run_record_sha256")
    _terminal(state)
    if state.run_record_sha256 is None:  # « le run suit au moins une session » : imposé par RunEvidenceState.__post_init__
        return RunEvidenceState(state.coverage, state.sessions, run_hash, state.seal)
    if state.run_record_sha256 == run_hash:
        return state
    _refuse(EvidenceRefusal.RUN_RECORD_MISMATCH, "un autre run est déjà enregistré")


def apply_seal(state, seal, expected_session_count=None) -> RunEvidenceState:
    """Applique le sceau terminal après vérification croisée complète. Sceau identique déjà appliqué ⇒ inchangé ; différent ⇒ SEAL_DUPLICATE.
    `expected_session_count` (optionnel) : nombre de sessions attendu par l'appelant, exigé égal à celui de l'état."""
    state = _state(state)
    if type(seal) is not RunSeal:
        _refuse(EvidenceRefusal.BAD_TYPE, "seal doit être un RunSeal")
    if expected_session_count is not None:
        _int(expected_session_count, "expected_session_count", 1, _MAX_SESSION_INDEX)
    if state.run_record_sha256 is None:
        _refuse(EvidenceRefusal.MACHINE_ORDER, "le sceau suit l'enregistrement du run")
    if expected_session_count is not None and expected_session_count != len(state.sessions):
        _refuse(EvidenceRefusal.SESSION_MISSING if len(state.sessions) < expected_session_count else EvidenceRefusal.SESSION_NOT_LISTED,
                "le nombre de sessions de l'état diffère du nombre attendu")
    if state.seal is not None:
        if state.seal.to_bytes() == seal.to_bytes():
            return state
        _refuse(EvidenceRefusal.SEAL_DUPLICATE, "un sceau différent est déjà appliqué")
    # la vérification croisée complète (verify_run_evidence) est exécutée par RunEvidenceState.__post_init__ du nouvel état scellé
    return RunEvidenceState(state.coverage, state.sessions, state.run_record_sha256, seal)


_TRANSITIONS = {"coverage": apply_coverage, "session": apply_session, "run_record": apply_run_record, "seal": apply_seal}


def replay(events, state=None) -> RunEvidenceState:
    """Rejoue des événements `(nom, charge)` à partir de `state` (défaut : état initial). Ce n'est pas un journal et cela ne prouve aucun ordre
    réel : l'état d'un préfixe est une valeur valide, qu'on peut reprendre avec la suite, pour SIMULER un arrêt entre deux états."""
    current = initial_state() if state is None else _state(state)
    try:
        sequence = iter(events)
    except TypeError:
        _refuse(EvidenceRefusal.BAD_TYPE, "events doit être une séquence d'événements")
    for event in sequence:
        if type(event) is not tuple or len(event) != 2 or type(event[0]) is not str:
            _refuse(EvidenceRefusal.BAD_TYPE, "un événement est un couple (nom texte, charge)")
        if event[0] not in _TRANSITIONS:
            _refuse(EvidenceRefusal.BAD_VALUE, f"événement inconnu : {event[0]!r}")
        current = _TRANSITIONS[event[0]](current, event[1])
    return current
