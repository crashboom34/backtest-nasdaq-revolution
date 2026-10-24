"""
gate_v_frame_digest.py — K1 Étape 2, lot L1 : empreinte déterministe d'une trame de marché (contrat R9 section 3, PROPOSED).

Module PUR : stdlib seule, aucun accès disque, réseau, registre ni pandas. Il ne calcule que des FAITS démontrables à partir
d'octets ou de colonnes typées fournis par l'appelant : l'empreinte d'une trame décodée, ses bornes temporelles, et, pour des octets
de snapshot S0, leur SHA-256. Il n'affirme jamais qu'un calcul a consommé cette trame, qu'une exécution est exposée ou non, ni
qu'une campagne est admissible : aucun verdict FRESH / NO_OVERLAP / admission / Claim n'existe ici.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

__all__ = [
    "FRAME_DIGEST_VERSION", "KIND_F64", "KIND_I64", "KIND_TIME_US", "TIME_COLUMN", "TIME_SEMANTICS", "FrameColumn", "FrameFacts",
    "FrameRefusal", "FrameRefused", "S0FrameFacts", "columns_from_csv_bytes", "compute_frame_digest", "compute_frame_facts",
    "compute_s0_frame_facts",
]

FRAME_DIGEST_VERSION = "gate_v_frame_digest_v1"
KIND_TIME_US = "time_us"
KIND_I64 = "i64"
KIND_F64 = "f64"
TIME_COLUMN = "time"


class FrameRefusal(str, Enum):
    """Vocabulaire FERMÉ des refus : une entrée hors contrat ne produit ni empreinte ni fait."""

    EMPTY = "EMPTY"                      # aucune colonne, aucune ligne, aucun octet
    NO_TIME_COLUMN = "NO_TIME_COLUMN"    # il faut exactement une colonne `time` de kind `time_us`, et aucune autre de ce kind
    COLUMN_LENGTH = "COLUMN_LENGTH"
    DUPLICATE_COLUMN = "DUPLICATE_COLUMN"
    BAD_COLUMN = "BAD_COLUMN"            # colonne mal formée : type Python, nom, kind, conteneur
    BAD_VALUE = "BAD_VALUE"              # valeur dont le type Python n'est pas EXACTEMENT celui du kind (bool, int pour f64, ...)
    NON_FINITE = "NON_FINITE"
    INT_RANGE = "INT_RANGE"
    BOM = "BOM"
    NOT_UTF8 = "NOT_UTF8"
    CSV_DIALECT = "CSV_DIALECT"          # ligne vide, CR isolé, pas de fin de ligne finale, guillemets mal formés
    CSV_RAGGED = "CSV_RAGGED"
    TIME_FORMAT = "TIME_FORMAT"          # seul `YYYY-MM-DD HH:MM:SS` (naïf, à la seconde) est accepté
    MISSING_VALUE = "MISSING_VALUE"
    FLOAT_TEXT = "FLOAT_TEXT"
    BAD_BAR = "BAD_BAR"                  # durée de barre déclarée : entier Python strictement positif exigé
    BAR_DURATION_MISMATCH = "BAR_DURATION_MISMATCH"  # plus petit écart mesuré ≠ durée déclarée (timeframes mêlés, déclaration fausse)
    BAR_GRID = "BAR_GRID"                # un écart n'est pas multiple de la durée déclarée
    NOT_STRICTLY_INCREASING = "NOT_STRICTLY_INCREASING"
    SUB_SECOND = "SUB_SECOND"            # un écart entre deux barres n'est pas un nombre entier de secondes
    TOO_FEW_ROWS = "TOO_FEW_ROWS"        # au moins deux barres pour mesurer un écart
    TIME_RANGE = "TIME_RANGE"            # instant hors du calendrier représentable (années 1 à 9999)


class FrameRefused(ValueError):
    """Entrée hors du contrat R9 : aucune empreinte, aucun fait. `code` ∈ `FrameRefusal`."""

    def __init__(self, code: FrameRefusal, message: str = "") -> None:
        super().__init__(f"{code.value}: {message}" if message else code.value)
        self.code = code
        self.detail = message

    def __reduce__(self):  # picklable et copiable : les workers passent des exceptions entre processus
        return (FrameRefused, (self.code, self.detail))


@dataclass(frozen=True)
class FrameColumn:
    """Colonne source typée : `time_us` (microsecondes depuis 1970-01-01, naïf interprété UTC), `i64` ou `f64`."""

    name: str
    kind: str
    values: tuple


_KINDS = (KIND_TIME_US, KIND_I64, KIND_F64)
_INT64_MIN, _INT64_MAX = -(2**63), 2**63 - 1


def _validate_columns(columns) -> int:
    """Contrôle strict des entrées explicites ; rend le nombre de lignes. Ne convertit rien, ne corrige rien."""
    if type(columns) not in (tuple, list):
        raise FrameRefused(FrameRefusal.BAD_COLUMN, "columns doit être un tuple ou une liste de FrameColumn")
    if not columns:
        raise FrameRefused(FrameRefusal.EMPTY, "aucune colonne")
    for c in columns:
        if type(c) is not FrameColumn:
            raise FrameRefused(FrameRefusal.BAD_COLUMN, "chaque colonne doit être un FrameColumn")
        if type(c.name) is not str or not c.name.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in c.name):
            raise FrameRefused(FrameRefusal.BAD_COLUMN, "nom de colonne vide, non textuel ou à caractère de contrôle")
        try:
            c.name.encode("utf-8")
        except UnicodeEncodeError:
            raise FrameRefused(FrameRefusal.BAD_COLUMN, "nom de colonne non encodable en UTF-8 (substitut isolé)") from None
        if type(c.kind) is not str or c.kind not in _KINDS or type(c.values) is not tuple:
            raise FrameRefused(FrameRefusal.BAD_COLUMN, f"kind inconnu ou values non tuple : {c.name!r}")
    n = len(columns[0].values)
    if n == 0:
        raise FrameRefused(FrameRefusal.EMPTY, "aucune ligne")
    times = [c for c in columns if c.kind == KIND_TIME_US or c.name == TIME_COLUMN]
    if len(times) != 1 or times[0].kind != KIND_TIME_US or times[0].name != TIME_COLUMN:
        raise FrameRefused(FrameRefusal.NO_TIME_COLUMN, "exactement une colonne 'time' de kind time_us est exigée")
    if any(len(c.values) != n for c in columns):
        raise FrameRefused(FrameRefusal.COLUMN_LENGTH, "colonnes de longueurs différentes")
    if len({c.name for c in columns}) != len(columns):
        raise FrameRefused(FrameRefusal.DUPLICATE_COLUMN, "nom de colonne en double")
    for c in columns:
        if c.kind == KIND_F64:
            for v in c.values:
                if type(v) is not float:
                    raise FrameRefused(FrameRefusal.BAD_VALUE, f"{c.name!r} : un f64 doit être un float Python exact")
                if not math.isfinite(v):
                    raise FrameRefused(FrameRefusal.NON_FINITE, f"{c.name!r} : NaN et infinis sont refusés")
        else:
            for v in c.values:
                if type(v) is not int:
                    raise FrameRefused(FrameRefusal.BAD_VALUE, f"{c.name!r} : un entier Python exact est exigé")
                if not _INT64_MIN <= v <= _INT64_MAX:
                    raise FrameRefused(FrameRefusal.INT_RANGE, f"{c.name!r} : hors de l'intervalle int64")
    return n


def compute_frame_digest(columns) -> str:
    """SHA-256 de la préimage R9 3.2 : version, en-tête JSON compact, puis, par colonne, nom, longueur et valeurs big-endian."""
    n = _validate_columns(columns)
    header = json.dumps({"columns": [{"kind": c.kind, "name": c.name} for c in columns], "row_count": n}, sort_keys=True,
                        separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256()
    digest.update((FRAME_DIGEST_VERSION + "\n").encode("ascii") + header + b"\n")
    for c in columns:
        digest.update(b"column:" + c.name.encode("utf-8") + b"\n" + struct.pack(">Q", 8 * n))
        digest.update(struct.pack(">%d%s" % (n, "d" if c.kind == KIND_F64 else "q"), *c.values))
    return digest.hexdigest()


_INT_RE = re.compile(r"[+-]?[0-9]+")
# Sans quantificateurs gloutons adjacents sur la même classe (« [0-9]+\.?[0-9]* » était quadratique : ReDoS sur « 111…1x »).
_FLOAT_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_TIME_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2}) ([0-9]{2}):([0-9]{2}):([0-9]{2})")
_NON_FINITE_WORDS = ("nan", "inf", "infinity")
_EPOCH = datetime(1970, 1, 1)
_BOM = b"\xef\xbb\xbf"


def _epoch_us(text: str) -> int:
    match = _TIME_RE.fullmatch(text)
    if match is None:
        raise FrameRefused(FrameRefusal.TIME_FORMAT, f"format attendu YYYY-MM-DD HH:MM:SS (naïf, à la seconde) : {text!r}")
    try:
        delta = datetime(*(int(g) for g in match.groups())) - _EPOCH
    except ValueError:
        raise FrameRefused(FrameRefusal.TIME_FORMAT, f"date ou heure inexistante : {text!r}") from None
    return (delta.days * 86400 + delta.seconds) * 1_000_000


def _float_cell(text: str) -> float:
    if text.lower().lstrip("+-") in _NON_FINITE_WORDS:
        raise FrameRefused(FrameRefusal.NON_FINITE, f"valeur non finie : {text!r}")
    if _FLOAT_RE.fullmatch(text) is None:
        raise FrameRefused(FrameRefusal.FLOAT_TEXT, f"hors de la grammaire décimale stricte : {text!r}")
    value = float(text)
    if not math.isfinite(value):
        raise FrameRefused(FrameRefusal.NON_FINITE, f"dépassement de capacité vers l'infini : {text!r}")
    return value


def _int_cell(name: str, text: str) -> int:
    """Entier décimal dans int64, sinon refus. Les zéros de tête sont retirés AVANT toute conversion (aucune limite des 4300 chiffres
    de Python à franchir, aucun coût quadratique) ; plus de 19 chiffres significatifs ⇒ hors int64."""
    digits = text.lstrip("+-").lstrip("0")
    if len(digits) > 19:
        raise FrameRefused(FrameRefusal.INT_RANGE, f"{name!r} : entier hors int64 (jamais élargi en flottant)")
    value = int(digits or "0")
    value = -value if text.startswith("-") else value
    if not _INT64_MIN <= value <= _INT64_MAX:
        raise FrameRefused(FrameRefusal.INT_RANGE, f"{name!r} : entier hors int64 (jamais élargi en flottant)")
    return value


def _typed_column(name: str, cells: list) -> FrameColumn:
    if name == TIME_COLUMN:
        return FrameColumn(name, KIND_TIME_US, tuple(_epoch_us(c) for c in cells))
    if all(_INT_RE.fullmatch(c) for c in cells):
        return FrameColumn(name, KIND_I64, tuple(_int_cell(name, c) for c in cells))
    values = []
    for c in cells:
        if _INT_RE.fullmatch(c):
            _int_cell(name, c)  # un entier hors int64 reste refusé dans une colonne décimale (jamais arrondi en silence)
        values.append(_float_cell(c))
    return FrameColumn(name, KIND_F64, tuple(values))


def columns_from_csv_bytes(raw: bytes) -> tuple:
    """Octets CSV → colonnes typées. Dialecte R9 3.2 : UTF-8 sans BOM, RFC 4180 strict, virgule, en-tête, LF ou CRLF, aucune ligne
    vide, aucun CR isolé, fin de ligne finale. Types inférés du TEXTE : `time` → `time_us`, entiers → `i64`, sinon `f64`."""
    if type(raw) is not bytes:
        raise FrameRefused(FrameRefusal.BAD_COLUMN, "raw doit être de type bytes")
    if not raw:
        raise FrameRefused(FrameRefusal.EMPTY, "aucun octet")
    if raw.startswith(_BOM):
        raise FrameRefused(FrameRefusal.BOM, "BOM UTF-8 refusé")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise FrameRefused(FrameRefusal.NOT_UTF8, "octets non UTF-8") from None
    unified = text.replace("\r\n", "\n")
    if "\r" in unified or not unified.endswith("\n") or "" in unified[:-1].split("\n"):
        raise FrameRefused(FrameRefusal.CSV_DIALECT, "CR isolé, fin de ligne finale absente ou ligne vide")
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as error:
        raise FrameRefused(FrameRefusal.CSV_DIALECT, f"CSV mal formé : {error}") from None
    header, body = rows[0], rows[1:]
    if not body:
        raise FrameRefused(FrameRefusal.EMPTY, "aucune ligne de données")
    if len(set(header)) != len(header):
        raise FrameRefused(FrameRefusal.DUPLICATE_COLUMN, "nom d'en-tête en double")
    if any(not name.strip() for name in header):
        raise FrameRefused(FrameRefusal.BAD_COLUMN, "nom d'en-tête vide")
    if any(len(r) != len(header) for r in body):
        raise FrameRefused(FrameRefusal.CSV_RAGGED, "nombre de cellules différent de l'en-tête")
    columns = []
    for j, name in enumerate(header):
        cells = [r[j] for r in body]
        if "" in cells:
            raise FrameRefused(FrameRefusal.MISSING_VALUE, f"{name!r} : cellule vide")
        columns.append(_typed_column(name, cells))
    _validate_columns(columns)
    return tuple(columns)


TIME_SEMANTICS = "naive_utc_declared"  # la colonne `time` est naïve, INTERPRÉTÉE UTC par convention (hypothèse déclarée, non prouvée)


def _iso_utc_us(us: int) -> str:
    seconds, micro = divmod(us, 1_000_000)
    try:
        moment = _EPOCH + timedelta(seconds=seconds)
    except OverflowError:
        raise FrameRefused(FrameRefusal.TIME_RANGE, f"instant hors du calendrier représentable : {us}") from None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%06dZ" % (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second, micro)


@dataclass(frozen=True)
class FrameFacts:
    """Faits d'une trame. Aucun champ ne qualifie une exposition ou une admission : ce sont des mesures sur des données."""

    frame_sha256: str
    row_count: int
    columns: tuple  # ((nom, kind), ...) dans l'ordre de la trame
    bar_duration_seconds: int
    first_open_utc: str
    last_open_utc: str
    last_close_utc_exclusive: str

    def to_record(self) -> dict:
        """Objet `frame` de R9 5.1 (9 clés exactes), sans flottant : sérialisable en JSON normatif."""
        return {
            "frame_digest_version": FRAME_DIGEST_VERSION, "frame_sha256": self.frame_sha256, "row_count": self.row_count,
            "columns": [{"name": name, "kind": kind} for name, kind in self.columns], "bar_duration_seconds": self.bar_duration_seconds,
            "first_open_utc": self.first_open_utc, "last_open_utc": self.last_open_utc,
            "last_close_utc_exclusive": self.last_close_utc_exclusive, "time_semantics": TIME_SEMANTICS,
        }


def compute_frame_facts(columns, declared_bar_seconds) -> FrameFacts:
    """Empreinte et bornes d'une trame. La durée de barre est DÉCLARÉE (timeframe) et doit égaler le plus petit écart mesuré ; tous les
    écarts en sont multiples. La clôture exclusive de la dernière barre = ouverture + durée déclarée."""
    if type(declared_bar_seconds) is not int or declared_bar_seconds <= 0:
        raise FrameRefused(FrameRefusal.BAD_BAR, "la durée de barre déclarée doit être un entier Python strictement positif")
    n = _validate_columns(columns)
    digest = compute_frame_digest(columns)
    times = next(c for c in columns if c.name == TIME_COLUMN).values
    if n < 2:
        raise FrameRefused(FrameRefusal.TOO_FEW_ROWS, "au moins deux barres sont nécessaires")
    gaps = [b - a for a, b in zip(times, times[1:])]
    if min(gaps) <= 0:
        raise FrameRefused(FrameRefusal.NOT_STRICTLY_INCREASING, "horodatages dupliqués ou non croissants")
    if any(g % 1_000_000 for g in gaps):
        raise FrameRefused(FrameRefusal.SUB_SECOND, "écart entre barres non entier en secondes")
    if min(gaps) // 1_000_000 != declared_bar_seconds:
        raise FrameRefused(FrameRefusal.BAR_DURATION_MISMATCH, "plus petit écart mesuré différent de la durée déclarée")
    if any((g // 1_000_000) % declared_bar_seconds for g in gaps):
        raise FrameRefused(FrameRefusal.BAR_GRID, "écart non multiple de la durée déclarée")
    return FrameFacts(digest, n, tuple((c.name, c.kind) for c in columns), declared_bar_seconds, _iso_utc_us(times[0]), _iso_utc_us(times[-1]),
                      _iso_utc_us(times[-1] + declared_bar_seconds * 1_000_000))


@dataclass(frozen=True)
class S0FrameFacts:
    """Faits recalculables sur les octets d'un snapshot S0 : (1) le hash des OCTETS BRUTS, (2) l'empreinte de la TRAME DÉCODÉE. Deux
    objets distincts : des octets différents peuvent décoder la même trame (fins de ligne, zéros finaux, guillemets)."""

    source_sha256: str
    source_size_bytes: int
    dataset_snapshot_id: str
    frame: FrameFacts

    def to_record(self) -> dict:
        return {"source_sha256": self.source_sha256, "source_size_bytes": self.source_size_bytes,
                "dataset_snapshot_id": self.dataset_snapshot_id, "frame": self.frame.to_record()}


def compute_s0_frame_facts(raw: bytes, declared_bar_seconds) -> S0FrameFacts:
    """Faits S0 à partir des seuls octets : `source_sha256` = SHA-256 des octets exacts (identité `local_csv:sha256:<h>` existante),
    puis la trame décodée par `columns_from_csv_bytes`. Ne prouve pas qu'un calcul a lu ces octets."""
    columns = columns_from_csv_bytes(raw)
    frame = compute_frame_facts(columns, declared_bar_seconds)
    source = hashlib.sha256(raw).hexdigest()
    return S0FrameFacts(source, len(raw), "local_csv:sha256:" + source, frame)
