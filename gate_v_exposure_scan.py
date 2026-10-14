"""
gate_v_exposure_scan.py — AF-V-07 Slice E3-B2 : scanner strict des racines d'audit.

Contrat : ADR 0025 Décision 23, 23.11 étape 1 (listage strict), 23.29.1 (arborescence `exposure/`) et 23.29.6 (double passe) ;
design E3-B (AI_HANDOFF.md §44.1).

Ce module réalise VOLONTAIREMENT des entrées/sorties de fichiers en lecture seule, et seulement celles-ci : `lstat`, `scandir`,
ouverture en lecture des fichiers que la table de sources fournie par l'appelant (B3) classe comme lisibles. Il n'ouvre jamais un
fichier inerte, inconnu ou orphelin, jamais une donnée de marché, n'écrit rien, ne lit aucune horloge et n'utilise ni le registre,
ni E2, ni le moteur, ni E3-A. Il ne construit aucun `ExposureFinding`, ne classe rien (FRESH, RETROSPECTIVE, UNDETERMINED), ne conclut
jamais qu'une période est vierge ou exposée.

Deux familles d'échec, typées et distinctes :
- défaillance de STRUCTURE (`ExposureScanRefusal`, `StructuralFailure`) : le scan est refusé, aucun résultat partiel ;
- anomalie de SOURCE (`SourceAnomaly`, portée par une `ScanObservation`) : observation non résolue transmise à B3/B4, jamais une
  absence silencieuse.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import warnings
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Optional

_UTF8_BOM = b"\xef\xbb\xbf"
_LONE_SURROGATE_RE = re.compile("[\\ud800-\\udfff]")
_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_LITERAL_SEGMENT_RE = re.compile(r"[A-Za-z0-9_.-]+")
_MAX_PATTERN_LENGTH = 300
_FIXED_REPEAT_RE = re.compile(r"\{[0-9]+\}")
_TAG_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")
_MAX_VARIABLE_ELEMENTS = 2       # k éléments variables : au plus (n+1)^k chemins de retour arrière × O(n) = O(n^(k+1)) ; k = 2 : ≤ ~2 M de pas à n = 128
_MAX_ROOT_PATH_LENGTH = 4096
_MAX_NAME_LENGTH = 128           # plafond du plafond : le coût d'appariement d'un motif croît comme n^(k+1) (k ≤ 2 éléments variables) avec la longueur
_EXTENDED_PATH_PREFIXES = ("\\\\?\\", "\\\\.\\")

# Orphelin de publication (ADR 23.29.1) : `.exposure.tmp.<32 hexadécimaux>`. Une règle `TEMP_ORPHAN_FILE` DOIT l'utiliser comme dernier
# segment : aucun autre nom ne peut être déclaré « orphelin autorisé » (donc non lu) par une table.
EXPOSURE_TEMP_ORPHAN_PATTERN = r"\.exposure\.tmp\.[0-9a-f]{32}"


def _risky_quantified_group(regex: str) -> bool:
    """Vrai si un groupe répété (`+`, `*`, `{n,m}`) contient une alternance ou une répétition variable, ou si le motif utilise une
    construction de groupe non analysée (`(?i)`, `(?P<n>…)`, lookaround) : risque de retour catastrophique sur un nom hostile.

    Heuristique conservatrice : un groupe de longueur fixe (`(?:[0-9]{4})+`, `(?:-[0-9]{2}){2}`) reste accepté.
    """
    stack = []                       # un booléen par groupe ouvert : son corps est-il à longueur variable ?
    starts = []                      # position du premier caractère du corps de chaque groupe ouvert (détecte un groupe vide)
    variable_elements = 0           # quantificateurs variables et alternances du motif entier (hors répétitions fixes `{n}`)
    position, size, in_class = 0, len(regex), False
    while position < size:
        char = regex[position]
        if char == "\\":
            escaped = regex[position + 1:position + 2]
            if not in_class and ((escaped.isdigit() and escaped != "0") or escaped in ("b", "B", "A", "Z")):
                return True          # rétroréférence ou assertion de largeur nulle (dans une classe : octal ou retour arrière, inoffensifs)
            position += 2
            continue
        if in_class:
            in_class = char != "]"
            position += 1
            continue
        if char == "[":
            in_class = True
            position += 1
            if regex[position:position + 1] == "^":
                position += 1
            if regex[position:position + 1] == "]":
                position += 1
            continue
        if char in "^$":
            return True              # ancre de largeur nulle : inutile avec `fullmatch`, et répétable sans que le nom borne le coût
        if char == "(":
            non_capturing = regex.startswith("(?:", position)
            if regex.startswith("(?", position) and not non_capturing:
                return True
            body_start = position + (3 if non_capturing else 1)
            stack.append(False)
            starts.append(body_start)
            position = body_start
            continue
        if char == ")":
            if starts and starts.pop() == position:
                return True          # groupe vide : largeur nulle
            variable = stack.pop() if stack else False
            if variable and regex[position + 1:position + 2] in ("+", "*", "{"):
                return True
            if stack and variable:
                stack[-1] = True
        elif char == "|" or char in "+*?":
            variable_elements += 1
            if stack:
                stack[-1] = True
        elif char == "{":
            fixed = _FIXED_REPEAT_RE.match(regex, position)
            if fixed:
                count = int(fixed.group()[1:-1])
                if count == 0 or count > _MAX_NAME_LENGTH:
                    return True      # `{0}` (largeur nulle) ou répétition fixe supérieure à tout nom admissible
                position = fixed.end()
                continue
            variable_elements += 1
            if stack:
                stack[-1] = True
        position += 1
    return variable_elements > _MAX_VARIABLE_ELEMENTS
# Garde « jamais de joker » : un motif de segment qui accepte TOUS ces noms (ou un nom vide) rendrait n'importe quel fichier « connu ».
_WORD_PROBES = ("a", "Z", "0", "_", "abc", "ABC", "a1", "A_1")
_CHARSET_PROBES = _WORD_PROBES + ("x-y", "x.y", "a.b-c_d")


class SourceAnomaly(str, Enum):
    """Anomalie de SOURCE : le contenu ou l'entrée n'est pas résolu ; jamais interprété comme « aucun événement »."""

    INVALID_JSON = "INVALID_JSON"          # vide, tronqué, mal formé, données en trop
    DUPLICATE_KEY = "DUPLICATE_KEY"
    NON_FINITE = "NON_FINITE"              # NaN, Infinity, -Infinity, 1e999
    BOM = "BOM"
    NOT_UTF8 = "NOT_UTF8"
    LONE_SURROGATE = "LONE_SURROGATE"      # substitut isolé, non encodable en UTF-8
    DEPTH_EXCEEDED = "DEPTH_EXCEEDED"
    TOO_LARGE = "TOO_LARGE"
    UNEXPECTED_JSON_TYPE = "UNEXPECTED_JSON_TYPE"  # le type JSON de plus haut niveau n'est pas celui attendu par la table
    KIND_MISMATCH = "KIND_MISMATCH"                # nom connu, mais fichier à la place d'un répertoire (ou l'inverse)
    UNKNOWN_FILE = "UNKNOWN_FILE"                  # fichier hors table : constaté par `lstat`, jamais ouvert
    UNKNOWN_DIRECTORY = "UNKNOWN_DIRECTORY"        # répertoire hors table : constaté, jamais descendu
    UNKNOWN_TEMP_FILE = "UNKNOWN_TEMP_FILE"        # fichier `.tmp` hors de l'emplacement exact d'un orphelin autorisé
    UNREADABLE = "UNREADABLE"                      # fichier reconnu dont l'ouverture ou la lecture échoue


class StrictJsonError(ValueError):
    """Document refusé par `parse_strict_json` ; `anomaly` porte la cause typée."""

    def __init__(self, anomaly: SourceAnomaly, detail: str) -> None:
        super().__init__(f"{anomaly.value} : {detail}")
        self.anomaly = anomaly
        self.detail = detail


class _DuplicateKey(Exception):
    pass


class _NonFinite(Exception):
    pass


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} doit être un entier (reçu {type(value).__name__}).")
    if value < 1:
        raise ValueError(f"{name} doit être un entier strictement positif.")
    return value


def _reject_duplicate_keys(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise _DuplicateKey()
    return dict(pairs)


def _reject_non_finite_constant(_name):
    raise _NonFinite()


def _finite_float(text: str) -> float:
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):
        raise _NonFinite()
    return value


def _nesting_depth_exceeds(text: str, max_depth: int) -> bool:
    """Parcours itératif (jamais récursif) : vrai si l'imbrication `{`/`[` hors chaînes dépasse `max_depth`."""
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
            if depth > max_depth:
                return True
        elif char in "}]":
            depth -= 1
    return False


def _contains_lone_surrogate(value: object) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if _LONE_SURROGATE_RE.search(item):
                return True
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def parse_strict_json(raw: bytes, *, max_bytes: int, max_depth: int) -> object:
    """Lit un document JSON STRICT depuis des octets bruts ; `StrictJsonError` (avec `anomaly`) au moindre défaut.

    Refuse : taille au-delà de `max_bytes`, BOM, UTF-8 invalide, imbrication au-delà de `max_depth` (un scalaire a la profondeur 0),
    JSON vide, tronqué ou mal formé, clé dupliquée (après décodage des échappements), constante ou valeur non finie, substitut isolé.
    Aucune conversion silencieuse, aucune réparation, aucun repli. `TypeError` si `raw` n'est pas exactement un `bytes`.
    """
    _positive_int(max_bytes, "max_bytes")
    _positive_int(max_depth, "max_depth")
    if type(raw) is not bytes:
        raise TypeError(f"raw doit être exactement un bytes (reçu {type(raw).__name__}).")
    if len(raw) > max_bytes:
        raise StrictJsonError(SourceAnomaly.TOO_LARGE, f"{len(raw)} octets > {max_bytes}")
    if raw.startswith(_UTF8_BOM):
        raise StrictJsonError(SourceAnomaly.BOM, "BOM UTF-8 interdit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StrictJsonError(SourceAnomaly.NOT_UTF8, str(error)) from None
    if _nesting_depth_exceeds(text, max_depth):
        raise StrictJsonError(SourceAnomaly.DEPTH_EXCEEDED, f"imbrication > {max_depth}")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
            parse_float=_finite_float,
        )
    except _DuplicateKey:
        raise StrictJsonError(SourceAnomaly.DUPLICATE_KEY, "clé JSON dupliquée") from None
    except _NonFinite:
        raise StrictJsonError(SourceAnomaly.NON_FINITE, "valeur ou constante non finie") from None
    except RecursionError:
        raise StrictJsonError(SourceAnomaly.DEPTH_EXCEEDED, "imbrication excessive") from None
    except ValueError as error:   # JSONDecodeError et entier trop long
        raise StrictJsonError(SourceAnomaly.INVALID_JSON, str(error)) from None
    if _contains_lone_surrogate(value):
        raise StrictJsonError(SourceAnomaly.LONE_SURROGATE, "substitut isolé dans une clé ou une valeur")
    return value


class JsonKind(str, Enum):
    """Type JSON de plus haut niveau attendu d'un artefact lisible (B2 ne valide que ce type, jamais le schéma métier)."""

    OBJECT = "OBJECT"
    ARRAY = "ARRAY"
    STRING = "STRING"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    NULL = "NULL"


class EntryClass(str, Enum):
    """Classe d'une entrée reconnue par la table de sources fournie par l'appelant (B3)."""

    EXPOSING_JSON = "EXPOSING_JSON"                # artefact scientifique reconnu : lu strictement
    INFORMATIVE_JSON = "INFORMATIVE_JSON"          # artefact informatif : lu strictement
    INERT_FILE = "INERT_FILE"                      # constaté par son nom : jamais ouvert
    TEMP_ORPHAN_FILE = "TEMP_ORPHAN_FILE"          # orphelin de publication à l'emplacement exact : consigné, jamais lu
    INERT_DIRECTORY = "INERT_DIRECTORY"            # constaté, jamais descendu
    STRUCTURAL_DIRECTORY = "STRUCTURAL_DIRECTORY"  # structure connue : descendue

    @property
    def is_read(self) -> bool:
        return self in (EntryClass.EXPOSING_JSON, EntryClass.INFORMATIVE_JSON)

    @property
    def is_file(self) -> bool:
        return self in (EntryClass.EXPOSING_JSON, EntryClass.INFORMATIVE_JSON, EntryClass.INERT_FILE, EntryClass.TEMP_ORPHAN_FILE)

    @property
    def is_directory(self) -> bool:
        return not self.is_file

    @property
    def is_descended(self) -> bool:
        return self is EntryClass.STRUCTURAL_DIRECTORY


@dataclass(frozen=True)
class AuditRoot:
    """Racine d'audit EXPLICITEMENT configurée : `label` portable (entre dans les identifiants de source), `path` absolu sans `..`."""

    label: str
    path: str
    may_be_empty: bool = False

    def __post_init__(self) -> None:
        if type(self.may_be_empty) is not bool:
            raise TypeError("may_be_empty doit être un booléen.")
        if type(self.label) is not str:
            raise TypeError(f"label doit être exactement un str (reçu {type(self.label).__name__}).")
        if _LABEL_RE.fullmatch(self.label) is None:
            raise ValueError("label de racine non portable : [A-Za-z0-9][A-Za-z0-9_-]{0,63} attendu.")
        raw = os.fspath(self.path) if isinstance(self.path, (str, os.PathLike)) else self.path
        if type(raw) is not str:
            raise TypeError(f"path doit être un chemin textuel (reçu {type(self.path).__name__}).")
        if not raw or "\x00" in raw:
            raise ValueError("path de racine vide ou contenant un octet nul.")
        if len(raw) > _MAX_ROOT_PATH_LENGTH:
            raise ValueError(f"path de racine plus long que {_MAX_ROOT_PATH_LENGTH} caractères.")
        if raw.replace("/", "\\").startswith(_EXTENDED_PATH_PREFIXES):
            raise ValueError("path de racine : les préfixes de chemin étendu Windows (`\\\\?\\`, `\\\\.\\`) sont refusés.")
        if not os.path.isabs(raw):
            raise ValueError("path de racine : un chemin ABSOLU est exigé (aucune résolution relative implicite).")
        if ".." in re.split(r"[\\/]", raw):
            raise ValueError("path de racine : le segment `..` est refusé.")
        object.__setattr__(self, "path", os.path.normpath(raw))


@dataclass(frozen=True)
class SegmentPattern:
    """Motif d'UN SEUL segment de chemin (`fullmatch`), jamais de joker multi-niveaux.

    Garde-fous HEURISTIQUES, pas des garanties : un motif qui accepte tous les noms-sondes ou un nom vide est refusé, ainsi qu'un
    quantificateur imbriqué (risque de retour catastrophique sur un nom hostile). La fermeture réelle de la table (aucun motif trop
    large) reste de la responsabilité de l'appelant (B3), qui doit la tester ; la longueur des noms est bornée par `max_name_length`.
    """

    regex: str
    _compiled: "re.Pattern[str]" = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.regex) is not str:
            raise TypeError(f"regex doit être exactement un str (reçu {type(self.regex).__name__}).")
        if not self.regex or len(self.regex) > _MAX_PATTERN_LENGTH:
            raise ValueError(f"regex de segment vide ou plus longue que {_MAX_PATTERN_LENGTH} caractères.")
        if _risky_quantified_group(self.regex):
            raise ValueError("groupe répété à longueur variable ou construction non analysée refusés : risque de retour catastrophique.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error")      # `FutureWarning` de syntaxe d'ensemble (`[[a]`, `[a&&b]`) : motif ambigu, refusé
                compiled = re.compile(self.regex)
        except (re.error, OverflowError, RecursionError, FutureWarning) as error:
            raise ValueError(f"regex de segment invalide ou ambiguë : {error}") from None
        if compiled.fullmatch("") is not None:
            raise ValueError("un motif de segment ne doit jamais accepter un nom vide.")
        if all(compiled.fullmatch(p) for p in _WORD_PROBES) or all(compiled.fullmatch(p) for p in _CHARSET_PROBES):
            raise ValueError("motif de segment permissif refusé : il rendrait tout nom « connu » (table fermée exigée).")
        object.__setattr__(self, "_compiled", compiled)

    def matches(self, name: str) -> bool:
        return type(name) is str and self._compiled.fullmatch(name) is not None


@dataclass(frozen=True)
class SourceRule:
    """Une entrée de la table fermée de sources : profondeur FIXE, segments littéraux ou `SegmentPattern`, classe de l'entrée.

    Aucun joker `**` : tout chemin hors table est observé comme inconnu, jamais ignoré ni lu.
    """

    segments: tuple
    entry_class: EntryClass
    expected_json: Optional[JsonKind] = None
    tag: Optional[str] = None      # étiquette opaque rendue telle quelle dans l'observation : B3 y relie le type de source

    def __post_init__(self) -> None:
        if self.tag is not None:
            if type(self.tag) is not str:
                raise TypeError("tag doit être un str ou None.")
            if _TAG_RE.fullmatch(self.tag) is None:
                raise ValueError("tag : identifiant portable de 1 à 64 caractères [A-Za-z0-9_.-] attendu.")
        if type(self.segments) is not tuple:
            raise TypeError("segments doit être un tuple de segments littéraux ou de SegmentPattern.")
        if not self.segments:
            raise ValueError("une règle de source a au moins un segment.")
        for segment in self.segments:
            if type(segment) is str:
                if _LITERAL_SEGMENT_RE.fullmatch(segment) is None or segment in (".", ".."):
                    raise ValueError(f"segment littéral non portable ou interdit : {segment!r}.")
            elif type(segment) is not SegmentPattern:
                raise TypeError("un segment est un str littéral ou un SegmentPattern.")
        if type(self.entry_class) is not EntryClass:
            raise TypeError("entry_class doit être un EntryClass.")
        if self.entry_class is EntryClass.TEMP_ORPHAN_FILE:
            last = self.segments[-1]
            if type(last) is not SegmentPattern or last.regex != EXPOSURE_TEMP_ORPHAN_PATTERN:
                raise ValueError("une règle TEMP_ORPHAN_FILE doit se terminer par SegmentPattern(EXPOSURE_TEMP_ORPHAN_PATTERN) : aucun autre nom n'est un orphelin autorisé.")
        if self.expected_json is not None:
            if type(self.expected_json) is not JsonKind:
                raise TypeError("expected_json doit être un JsonKind ou None.")
            if not self.entry_class.is_read:
                raise ValueError("expected_json n'a de sens que pour une classe lue (EXPOSING_JSON, INFORMATIVE_JSON).")

    @property
    def depth(self) -> int:
        return len(self.segments)

    def matches(self, names: tuple) -> bool:
        if len(names) != len(self.segments):
            return False
        return all(
            (segment.matches(name) if type(segment) is SegmentPattern else segment == name)
            for segment, name in zip(self.segments, names)
        )


_LIMIT_FIELDS = (
    "max_roots", "max_entries", "max_depth", "max_json_bytes", "max_total_read_bytes", "max_json_depth",
    "max_name_length", "max_path_length", "max_attempts",
)


@dataclass(frozen=True, kw_only=True)
class ScanLimits:
    """Contrat de ressources d'un scan : TOUTES les bornes sont explicites (aucune valeur par défaut, aucune constante normative).

    `max_attempts` est le nombre d'essais de la double passe (valeur opérationnelle de 23.24 ; un essai suffit en `SYNTHETIC`).
    """

    max_roots: int
    max_entries: int
    max_depth: int
    max_json_bytes: int
    max_total_read_bytes: int
    max_json_depth: int
    max_name_length: int
    max_path_length: int
    max_attempts: int

    def __post_init__(self) -> None:
        for name in _LIMIT_FIELDS:
            _positive_int(getattr(self, name), name)
        if self.max_json_bytes > self.max_total_read_bytes:
            raise ValueError("max_json_bytes ne peut pas dépasser max_total_read_bytes.")
        if self.max_name_length > _MAX_NAME_LENGTH:
            raise ValueError(f"max_name_length ne peut pas dépasser {_MAX_NAME_LENGTH} (coût d'appariement des motifs, longueur d'un nom de répertoire d'audit).")


@dataclass(frozen=True)
class ScanHooks:
    """Injections OPTIONNELLES pour les tests de concurrence et de mutation ; jamais utilisées en production."""

    after_first_pass: Optional[Callable[[int], None]] = None
    after_file_read: Optional[Callable[[str, str], None]] = None

    def __post_init__(self) -> None:
        for name in ("after_first_pass", "after_file_read"):
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise TypeError(f"{name} doit être appelable ou None.")


class StructuralFailure(str, Enum):
    """Défaillance de STRUCTURE : le scan est refusé (aucun résultat partiel, aucun A0)."""

    ROOT_MISSING = "ROOT_MISSING"
    ROOT_NOT_DIRECTORY = "ROOT_NOT_DIRECTORY"
    ROOT_EMPTY = "ROOT_EMPTY"
    ROOT_UNREADABLE = "ROOT_UNREADABLE"
    DUPLICATE_ROOT_LABEL = "DUPLICATE_ROOT_LABEL"
    ROOT_OVERLAP = "ROOT_OVERLAP"                          # racines imbriquées, identiques ou même répertoire sous deux labels
    LINK_OR_REPARSE_POINT = "LINK_OR_REPARSE_POINT"        # lien symbolique, jonction, point d'analyse : jamais suivi
    SPECIAL_FILE = "SPECIAL_FILE"                          # FIFO, socket, périphérique : jamais ouvert
    NON_PORTABLE_NAME = "NON_PORTABLE_NAME"
    RESERVED_NAME = "RESERVED_NAME"                        # CON, PRN, AUX, NUL, COM0-9, LPT0-9
    CASE_COLLISION = "CASE_COLLISION"
    SUBDIRECTORY_UNREADABLE = "SUBDIRECTORY_UNREADABLE"
    ENTRY_UNREADABLE = "ENTRY_UNREADABLE"                  # `lstat` d'un nom listé en échec : jamais « absent »
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"                      # un plafond du contrat `ScanLimits` : refus, jamais troncature
    AMBIGUOUS_SOURCE_TABLE = "AMBIGUOUS_SOURCE_TABLE"      # plusieurs règles reconnaissent la même entrée
    UNSTABLE_LISTING = "UNSTABLE_LISTING"                  # un changement observable entre les deux passes persiste après les essais


class ExposureScanRefusal(ValueError):
    """Scan refusé pour une défaillance de STRUCTURE ; `failure` est typée, `root_label` et `relative_path` situent l'échec."""

    def __init__(self, failure: StructuralFailure, detail: str, *, root_label: Optional[str] = None,
                 relative_path: Optional[str] = None) -> None:
        super().__init__(f"{failure.value} : {detail}")
        self.failure = failure
        self.detail = detail
        self.root_label = root_label
        self.relative_path = relative_path


class EntryKind(str, Enum):
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


@dataclass(frozen=True)
class ScanObservation:
    """Fait observé sur une entrée ; `anomaly` est non nul pour une entrée non résolue (anomalie de SOURCE).

    `entry_class` est `None` pour une entrée hors table. `content_hash` = SHA-256 des octets BRUTS réellement lus (jamais d'un JSON
    reformaté) ; `None` si le fichier n'a pas été lu en entier.

    Intégrité de la preuve : pour un JSON accepté (`value_parsed`), l'observation conserve les octets exacts (`content_bytes`, immuables)
    et SA CONSTRUCTION REFUSE des octets qui contredisent `content_hash`. `value` n'est PAS un champ : c'est une COPIE FRAÎCHE, rendue
    par un nouvel appel au lecteur strict à chaque accès ; la modifier n'altère ni l'observation ni la preuve (seuls `content_bytes`
    et `content_hash` font foi). `None` si le contenu n'a pas été accepté.
    """

    root_label: str
    relative_path: str          # séparateur POSIX
    kind: EntryKind
    entry_class: Optional[EntryClass]
    anomaly: Optional[SourceAnomaly]
    size: Optional[int]
    mtime_ns: Optional[int]
    st_ino: Optional[int]
    st_dev: Optional[int]
    content_hash: Optional[str]
    value_parsed: bool = False
    content_bytes: Optional[bytes] = field(default=None, repr=False)
    rule_tag: Optional[str] = None   # `tag` de la règle appariée (None pour une entrée hors table)

    def __post_init__(self) -> None:
        read_file = self.kind is EntryKind.FILE and self.entry_class is not None and self.entry_class.is_read
        if self.value_parsed:
            if not read_file or self.anomaly is not None:
                raise ValueError("seul un fichier de classe lue SANS anomalie peut être analysé (value_parsed).")
            if type(self.content_bytes) is not bytes or self.content_hash is None:
                raise TypeError("une observation analysée porte ses octets (bytes) et son content_hash.")
            if hashlib.sha256(self.content_bytes).hexdigest() != self.content_hash:
                raise ValueError("content_bytes contredit content_hash : preuve incohérente refusée.")
            if self.size != len(self.content_bytes):
                raise ValueError("la taille observée contredit la longueur des octets conservés.")
        else:
            if self.content_bytes is not None:
                raise ValueError("content_bytes n'est conservé que pour un contenu JSON accepté (value_parsed).")
            if read_file and self.anomaly is None:
                raise ValueError("un fichier de classe lue sans anomalie doit être analysé : jamais « propre » sans preuve.")
        self._check_entry_consistency()

    def _check_entry_consistency(self) -> None:
        """Seuls les états que le scan peut produire sont constructibles : jamais une entrée « propre » incohérente."""
        unknown = (SourceAnomaly.UNKNOWN_FILE, SourceAnomaly.UNKNOWN_TEMP_FILE, SourceAnomaly.UNKNOWN_DIRECTORY)
        if self.entry_class is None:
            if self.anomaly not in unknown:
                raise ValueError("une entrée hors table porte toujours une anomalie UNKNOWN_*.")
            if (self.anomaly is SourceAnomaly.UNKNOWN_DIRECTORY) != (self.kind is EntryKind.DIRECTORY):
                raise ValueError("l'anomalie UNKNOWN_* ne correspond pas à la nature de l'entrée.")
            return
        if self.anomaly in unknown:
            raise ValueError("une entrée reconnue par la table ne peut pas porter une anomalie UNKNOWN_*.")
        mismatch = self.entry_class.is_file != (self.kind is EntryKind.FILE)
        if mismatch != (self.anomaly is SourceAnomaly.KIND_MISMATCH):
            raise ValueError("KIND_MISMATCH si et seulement si la nature de l'entrée contredit sa classe.")
        if not mismatch and self.anomaly is not None and not (self.kind is EntryKind.FILE and self.entry_class.is_read):
            raise ValueError("une anomalie de contenu ne concerne qu'un fichier de classe lue.")

    @property
    def value(self) -> object:
        if not self.value_parsed:
            return None
        if hashlib.sha256(self.content_bytes).hexdigest() != self.content_hash:
            raise ValueError("content_bytes ne correspond plus à content_hash : observation altérée après sa construction.")
        size = len(self.content_bytes)
        return parse_strict_json(self.content_bytes, max_bytes=max(size, 1), max_depth=size + 1)


@dataclass(frozen=True)
class ScannedRoot:
    label: str
    path: str
    st_dev: int
    st_ino: int
    may_be_empty: bool     # politique de vacuité sous laquelle la racine a été scannée

    def __post_init__(self) -> None:
        for name, expected in (("label", str), ("path", str), ("st_dev", int), ("st_ino", int), ("may_be_empty", bool)):
            if type(getattr(self, name)) is not expected:
                raise TypeError(f"{name} doit être exactement un {expected.__name__}.")


@dataclass(frozen=True)
class ExposureScan:
    """Résultat d'un scan : racines et observations triées de façon déterministe. Aucune classification, aucun `ExposureFinding`.

    `rules_digest` épingle la table de sources EXACTE appliquée (SHA-256 d'une sérialisation canonique, indépendante de l'ordre des
    règles) : B3/B5 le consignent pour qu'un A0 ne puisse pas être rejoué avec une autre table. `hooks_used` est vrai si des
    `ScanHooks` (outil de test) ont accompagné le scan : un tel résultat n'a AUCUNE autorité de production (E3-J doit le refuser).

    `limits` épingle les plafonds sous lesquels les anomalies (`TOO_LARGE`, `DEPTH_EXCEEDED`…) ont été produites ; `ScannedRoot.may_be_empty`
    épingle la politique de vacuité de chaque racine.

    PRÉCONDITIONS pour les couches supérieures (B3, B4, E3-J), à tester par B3 :
    1. La table fournie doit être CLOSE : pour chaque règle `INERT_FILE` ou `INERT_DIRECTORY`, un test énumère les noms attendus et vérifie
       qu'aucun nom inconnu ou hostile n'est apparié ; `INERT_DIRECTORY` n'est admis que pour un sous-arbre qui ne peut contenir ni source
       exposante ni nom inconnu, sinon `STRUCTURAL_DIRECTORY` plus `INERT_FILE` enfants énumérés.
    2. `INERT_DIRECTORY` et `UNKNOWN_DIRECTORY` désignent des sous-arbres NON énumérés : une observation sans anomalie ne prouve jamais
       l'absence de source ni la complétude d'une racine.
    3. Est non résolue toute observation avec `anomaly` non nulle ; seul un contenu avec `value_parsed` est interprétable, et uniquement
       à partir de `content_bytes` / `value` (jamais d'une relecture du fichier).
    4. Une entrée requise absente n'est pas observée : B3 en vérifie lui-même la présence.
    5. B3/B5 épinglent `rules_digest`, `limits` et `may_be_empty` ; E3-J refuse un résultat avec `hooks_used` et recalcule le scan.
    """

    roots: tuple
    observations: tuple
    attempts_used: int
    bytes_read: int
    rules_digest: str
    hooks_used: bool
    limits: ScanLimits

    def __post_init__(self) -> None:
        if type(self.roots) is not tuple or any(type(root) is not ScannedRoot for root in self.roots):
            raise TypeError("roots doit être un tuple de ScannedRoot.")
        if type(self.observations) is not tuple or any(type(item) is not ScanObservation for item in self.observations):
            raise TypeError("observations doit être un tuple de ScanObservation.")
        for name, minimum in (("attempts_used", 1), ("bytes_read", 0)):
            value = getattr(self, name)
            if type(value) is not int:
                raise TypeError(f"{name} doit être un entier.")
            if value < minimum:
                raise ValueError(f"{name} doit être au moins {minimum}.")
        if type(self.rules_digest) is not str or _SHA256_HEX_RE.fullmatch(self.rules_digest) is None:
            raise ValueError("rules_digest doit être un SHA-256 hexadécimal minuscule de 64 caractères.")
        if type(self.hooks_used) is not bool:
            raise TypeError("hooks_used doit être un booléen.")
        if type(self.limits) is not ScanLimits:
            raise TypeError("limits doit être un ScanLimits.")
        if self.attempts_used > self.limits.max_attempts:
            raise ValueError("attempts_used dépasse limits.max_attempts.")
        if self.bytes_read > self.limits.max_total_read_bytes:
            raise ValueError("bytes_read dépasse limits.max_total_read_bytes.")


_READ_FLAGS = (
    os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NONBLOCK", 0)      # POSIX : un FIFO substitué entre `lstat` et `open` ne doit jamais bloquer le scan
)
_READ_CHUNK = 65536


def _is_temp_name(name: str) -> bool:
    folded = name.casefold()
    return folded.endswith(".tmp") or ".tmp." in folded


def _json_kind(value: object) -> JsonKind:
    if value is None:
        return JsonKind.NULL
    if isinstance(value, bool):
        return JsonKind.BOOLEAN
    if isinstance(value, (int, float)):
        return JsonKind.NUMBER
    if isinstance(value, str):
        return JsonKind.STRING
    if isinstance(value, list):
        return JsonKind.ARRAY
    return JsonKind.OBJECT


class _ReadBudget:
    def __init__(self) -> None:
        self.bytes_read = 0
        self.entries = 0


class _Unstable(Exception):
    """Changement observable pendant une passe (nom disparu, fichier modifié ou remplacé) : l'essai est à recommencer."""


def _identity(info) -> tuple:
    return (info.st_ino, info.st_dev, info.st_size, info.st_mtime_ns)


def _refuse(failure: "StructuralFailure", detail: str, label: Optional[str] = None, names: tuple = ()) -> None:
    raise ExposureScanRefusal(failure, detail, root_label=label, relative_path="/".join(names) if names else None)


_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_PORTABLE_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
_RESERVED_STEMS = frozenset({"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(10)} | {f"lpt{i}" for i in range(10)})


def _structural_failure_for_stat(info) -> Optional["StructuralFailure"]:
    """Lien symbolique, jonction ou point d'analyse (jamais suivi) ; fichier spécial (FIFO, socket, périphérique)."""
    if stat.S_ISLNK(info.st_mode) or (getattr(info, "st_file_attributes", 0) or 0) & _REPARSE_POINT:
        return StructuralFailure.LINK_OR_REPARSE_POINT
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        return StructuralFailure.SPECIAL_FILE
    return None


def _portable_name_failure(name: str) -> Optional["StructuralFailure"]:
    if not name or _PORTABLE_NAME_RE.fullmatch(name) is None or name.endswith("."):
        return StructuralFailure.NON_PORTABLE_NAME
    if name.split(".", 1)[0].casefold() in _RESERVED_STEMS:
        return StructuralFailure.RESERVED_NAME
    return None


def _find_case_collision(names) -> Optional[tuple]:
    seen = {}
    for name in names:
        folded = name.casefold()
        if folded in seen:
            return seen[folded], name
        seen[folded] = name
    return None


def _observation(label, names, kind, entry_class, anomaly, info, content_hash=None, content_bytes=None) -> ScanObservation:
    return ScanObservation(
        root_label=label,
        relative_path="/".join(names),
        kind=kind,
        entry_class=entry_class,
        anomaly=anomaly,
        size=info.st_size if kind is EntryKind.FILE else None,
        mtime_ns=info.st_mtime_ns,
        st_ino=info.st_ino,
        st_dev=info.st_dev,
        content_hash=content_hash,
        value_parsed=content_bytes is not None,
        content_bytes=content_bytes,
    )


def _read_json_entry(label, names, path, info, rule, limits, budget, hooks) -> ScanObservation:
    entry_class = rule.entry_class
    if info.st_size > limits.max_json_bytes:
        return _observation(label, names, EntryKind.FILE, entry_class, SourceAnomaly.TOO_LARGE, info)
    try:
        descriptor = os.open(path, _READ_FLAGS)
    except FileNotFoundError:
        raise _Unstable(f"{'/'.join(names)} a disparu entre le lstat et l'ouverture") from None
    except OSError:
        return _observation(label, names, EntryKind.FILE, entry_class, SourceAnomaly.UNREADABLE, info)
    try:
        opened = os.fstat(descriptor)
        chunks = []
        total = 0
        while total <= limits.max_json_bytes:
            chunk = os.read(descriptor, min(_READ_CHUNK, limits.max_json_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after_read = os.fstat(descriptor)
    except OSError:
        return _observation(label, names, EntryKind.FILE, entry_class, SourceAnomaly.UNREADABLE, info)
    finally:
        os.close(descriptor)
    if hooks is not None and hooks.after_file_read is not None:
        hooks.after_file_read(label, "/".join(names))
    try:
        after = os.lstat(path)
    except OSError:
        raise _Unstable(f"{'/'.join(names)} n'est plus observable après sa lecture") from None
    if not (_identity(opened) == _identity(after_read) == _identity(info) == _identity(after)):
        raise _Unstable(f"{'/'.join(names)} a changé pendant sa lecture (métadonnées ou inode)")
    raw = b"".join(chunks)
    if len(raw) != info.st_size:
        raise _Unstable(f"{'/'.join(names)} : {len(raw)} octets lus pour une taille observée de {info.st_size}")
    budget.bytes_read += len(raw)
    if budget.bytes_read > limits.max_total_read_bytes:
        _refuse(StructuralFailure.LIMIT_EXCEEDED, "max_total_read_bytes dépassé", label, names)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        value = parse_strict_json(raw, max_bytes=limits.max_json_bytes, max_depth=limits.max_json_depth)
    except StrictJsonError as error:
        return _observation(label, names, EntryKind.FILE, entry_class, error.anomaly, info, content_hash=digest)
    if rule.expected_json is not None and _json_kind(value) is not rule.expected_json:
        return _observation(label, names, EntryKind.FILE, entry_class, SourceAnomaly.UNEXPECTED_JSON_TYPE, info, content_hash=digest)
    return _observation(label, names, EntryKind.FILE, entry_class, None, info, content_hash=digest, content_bytes=raw)


def _observe_entry(label, parent_path, prefix, name, rules, limits, budget, hooks):
    """Observe UNE entrée : retourne `(observation, descendre)` ou refuse sur une défaillance de structure."""
    names = prefix + (name,)
    path = os.path.join(parent_path, name)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise _Unstable(f"{'/'.join(names)} a disparu entre le listage et le lstat") from None
    except OSError as error:
        _refuse(StructuralFailure.ENTRY_UNREADABLE, f"lstat impossible : {error}", label, names)
    failure = _structural_failure_for_stat(info)
    if failure is not None:
        _refuse(failure, "lien, point d'analyse ou fichier spécial : jamais suivi ni lu", label, names)
    kind = EntryKind.DIRECTORY if stat.S_ISDIR(info.st_mode) else EntryKind.FILE
    matching = [rule for rule in rules if rule.matches(names)]
    if len(matching) > 1:
        _refuse(StructuralFailure.AMBIGUOUS_SOURCE_TABLE, "plusieurs règles de la table reconnaissent cette entrée", label, names)
    if not matching or (_is_temp_name(name) and matching[0].entry_class is not EntryClass.TEMP_ORPHAN_FILE):
        # un nom temporaire n'est jamais masqué par une règle autre que celle des orphelins de publication : il reste une anomalie
        if kind is EntryKind.DIRECTORY:
            anomaly = SourceAnomaly.UNKNOWN_DIRECTORY
        else:
            anomaly = SourceAnomaly.UNKNOWN_TEMP_FILE if _is_temp_name(name) else SourceAnomaly.UNKNOWN_FILE
        return _observation(label, names, kind, None, anomaly, info), False
    rule = matching[0]
    entry_class = rule.entry_class
    if entry_class.is_file != (kind is EntryKind.FILE):
        observation, descend = _observation(label, names, kind, entry_class, SourceAnomaly.KIND_MISMATCH, info), False
    elif entry_class.is_read:
        observation, descend = _read_json_entry(label, names, path, info, rule, limits, budget, hooks), False
    else:
        observation, descend = _observation(label, names, kind, entry_class, None, info), entry_class.is_descended
    return replace(observation, rule_tag=rule.tag), descend


def _list_directory(label, directory_path, prefix, limits, budget, is_root) -> list:
    """Liste et VALIDE les noms d'un répertoire AVANT tout `lstat` ou lecture d'une de ses entrées."""
    try:
        names = []
        with os.scandir(directory_path) as entries:
            for entry in entries:
                names.append(entry.name)
                if budget.entries + len(names) > limits.max_entries:    # plafond atteint : le listage n'est jamais matérialisé
                    _refuse(StructuralFailure.LIMIT_EXCEEDED, "max_entries dépassé", label, prefix)
    except FileNotFoundError:
        if not is_root:
            raise _Unstable(f"{'/'.join(prefix)} a disparu entre sa découverte et son listage") from None
        _refuse(StructuralFailure.ROOT_MISSING, "racine disparue pendant le scan", label)
    except OSError as error:
        failure = StructuralFailure.ROOT_UNREADABLE if is_root else StructuralFailure.SUBDIRECTORY_UNREADABLE
        _refuse(failure, f"listage impossible : {error}", label, prefix)
    names.sort()
    for name in names:
        if len(name) > limits.max_name_length:
            _refuse(StructuralFailure.LIMIT_EXCEEDED, "max_name_length dépassé", label, prefix + (name,))
        failure = _portable_name_failure(name)
        if failure is not None:
            _refuse(failure, f"nom non portable ou réservé : {name!r}", label, prefix + (name,))
    collision = _find_case_collision(names)
    if collision is not None:
        _refuse(StructuralFailure.CASE_COLLISION, f"collision de casse : {collision[0]!r} et {collision[1]!r}", label, prefix)
    for name in names:
        if len(os.path.join(directory_path, name)) > limits.max_path_length:
            _refuse(StructuralFailure.LIMIT_EXCEEDED, "max_path_length dépassé", label, prefix + (name,))
    if names and len(prefix) + 1 > limits.max_depth:
        _refuse(StructuralFailure.LIMIT_EXCEEDED, "max_depth dépassé", label, prefix + (names[0],))
    budget.entries += len(names)
    return names


def _scan_root(root, rules, limits, budget, hooks) -> tuple:
    observations = []
    root_names = _list_directory(root.label, root.path, (), limits, budget, True)
    if not root_names and not root.may_be_empty:
        _refuse(StructuralFailure.ROOT_EMPTY, "racine vide alors que sa structure est obligatoire", root.label)
    stack = [(root.path, (), iter(root_names))]
    while stack:
        parent_path, prefix, names = stack[-1]
        name = next(names, None)
        if name is None:
            stack.pop()
            continue
        observation, descend = _observe_entry(root.label, parent_path, prefix, name, rules, limits, budget, hooks)
        observations.append(observation)
        if descend:
            child_path = os.path.join(parent_path, name)
            child_names = _list_directory(root.label, child_path, prefix + (name,), limits, budget, False)
            stack.append((child_path, prefix + (name,), iter(child_names)))
    return tuple(observations)


def _textual_overlap(first: str, second: str) -> bool:
    first, second = os.path.normcase(first), os.path.normcase(second)
    return first == second or second.startswith(first.rstrip(os.sep) + os.sep) or first.startswith(second.rstrip(os.sep) + os.sep)


def _path_overlap(first: str, second: str) -> bool:
    """Imbrication ou identité, sur les chemins tels que donnés ET sur leurs chemins réels (lien ou jonction dans un composant parent)."""
    return _textual_overlap(first, second) or _textual_overlap(os.path.realpath(first), os.path.realpath(second))


def _validated_roots(roots: tuple, limits: ScanLimits) -> list:
    """Contrôles de STRUCTURE de l'ensemble des racines, avant tout parcours."""
    if len(roots) > limits.max_roots:
        _refuse(StructuralFailure.LIMIT_EXCEEDED, "max_roots dépassé")
    labels = [root.label for root in roots]
    if len(set(labels)) != len(labels):
        _refuse(StructuralFailure.DUPLICATE_ROOT_LABEL, "deux racines portent le même label")
    ordered = sorted(roots, key=lambda candidate: candidate.label)
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            if _path_overlap(first.path, second.path):
                _refuse(StructuralFailure.ROOT_OVERLAP, f"racines imbriquées ou identiques : {first.label!r} et {second.label!r}")
    checked = []
    for root in ordered:
        try:
            info = os.lstat(root.path)
        except FileNotFoundError:
            _refuse(StructuralFailure.ROOT_MISSING, "racine absente", root.label)
        except OSError as error:
            _refuse(StructuralFailure.ROOT_UNREADABLE, f"racine inaccessible : {error}", root.label)
        if _structural_failure_for_stat(info) is StructuralFailure.LINK_OR_REPARSE_POINT:
            _refuse(StructuralFailure.LINK_OR_REPARSE_POINT, "la racine est un lien ou un point d'analyse", root.label)
        if not stat.S_ISDIR(info.st_mode):
            _refuse(StructuralFailure.ROOT_NOT_DIRECTORY, "la racine n'est pas un répertoire", root.label)
        checked.append((root, info))
    identities = {}
    for root, info in checked:
        identity = (info.st_dev, info.st_ino)
        if identity in identities:
            _refuse(StructuralFailure.ROOT_OVERLAP, f"même répertoire sous deux labels : {identities[identity]!r} et {root.label!r}")
        identities[identity] = root.label
    return checked


def _single_pass(roots: tuple, rules: tuple, limits: ScanLimits, hooks: Optional[ScanHooks]) -> tuple:
    budget = _ReadBudget()
    scanned_roots = []
    observations = []
    for root, info in _validated_roots(roots, limits):
        scanned_roots.append(ScannedRoot(root.label, root.path, info.st_dev, info.st_ino, root.may_be_empty))
        observations.extend(_scan_root(root, rules, limits, budget, hooks))
    return tuple(scanned_roots), tuple(observations), budget.bytes_read


def _comparable(observation: ScanObservation) -> tuple:
    """Ce que la double passe compare : nom, nature, classe, anomalie ; pour un fichier LU, aussi métadonnées et SHA-256.

    Les fichiers inertes, inconnus, orphelins et les répertoires ne sont comparés que par leur nom (ADR 23.29.6).
    """
    identity = (observation.root_label, observation.relative_path, observation.kind, observation.entry_class, observation.anomaly)
    if observation.kind is EntryKind.FILE and observation.entry_class is not None and observation.entry_class.is_read:
        return identity + (observation.size, observation.mtime_ns, observation.st_ino, observation.st_dev, observation.content_hash)
    return identity


def _rules_digest(rules: tuple) -> str:
    """SHA-256 d'une sérialisation canonique de la table, indépendante de l'ordre des règles : épingle la table appliquée."""
    lines = sorted(
        json.dumps(
            {
                "segments": [segment if type(segment) is str else {"regex": segment.regex} for segment in rule.segments],
                "entry_class": rule.entry_class.value,
                "expected_json": rule.expected_json.value if rule.expected_json is not None else None,
                "tag": rule.tag,
            },
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        )
        for rule in rules
    )
    return hashlib.sha256("\n".join(lines).encode("ascii")).hexdigest()


def _first_difference(first: tuple, second: tuple) -> str:
    left = {(o.root_label, o.relative_path): _comparable(o) for o in first}
    right = {(o.root_label, o.relative_path): _comparable(o) for o in second}
    for key in sorted(set(left) | set(right)):
        if left.get(key) != right.get(key):
            return f"{key[0]}:{key[1]}"
    return "(racines)"


def scan_audit_roots(roots: tuple, rules: tuple, limits: ScanLimits, *, hooks: Optional[ScanHooks] = None) -> ExposureScan:
    """Scan strict, déterministe et en lecture seule des racines d'audit explicitement configurées.

    Retourne des OBSERVATIONS (faits de structure et de contenu brut) ; ne classe rien et ne conclut jamais qu'une période est
    vierge ou exposée. Une défaillance de STRUCTURE lève `ExposureScanRefusal` ; une anomalie de SOURCE est portée par l'observation.

    Double passe (ADR 23.29.6) : listage, lecture et hachage des fichiers reconnus, puis relistage et nouvelle lecture ; les noms, les
    `(st_ino, st_dev, size, mtime_ns)` et les SHA-256 des fichiers lus doivent coïncider (les autres entrées : le nom seulement).
    Un écart est une instabilité : l'essai est recommencé jusqu'à `limits.max_attempts`, puis `UNSTABLE_LISTING` refuse.
    La double passe DÉTECTE un changement observable ; elle ne GARANTIT PAS un instantané atomique des racines, ni l'absence de
    modification après la seconde passe, ni la détection d'une modification restaurée à l'identique entre les deux passes, ni celle
    d'une édition masquée par une résolution grossière de `mtime` (FAT, exFAT, partages réseau). Le résultat est une observation
    passée, jamais une vue vivante.
    """
    if type(roots) is not tuple or any(type(root) is not AuditRoot for root in roots):
        raise TypeError("roots doit être un tuple d'AuditRoot.")
    if not roots:
        raise ValueError("au moins une racine d'audit est exigée.")
    if type(rules) is not tuple or any(type(rule) is not SourceRule for rule in rules):
        raise TypeError("rules doit être un tuple de SourceRule.")
    if type(limits) is not ScanLimits:
        raise TypeError("limits doit être un ScanLimits.")
    if hooks is not None and type(hooks) is not ScanHooks:
        raise TypeError("hooks doit être un ScanHooks ou None.")
    last_difference = "aucune"
    for attempt in range(1, limits.max_attempts + 1):
        try:
            first_roots, first, bytes_read = _single_pass(roots, rules, limits, hooks)
            if hooks is not None and hooks.after_first_pass is not None:
                hooks.after_first_pass(attempt)
            second_roots, second, _ = _single_pass(roots, rules, limits, hooks)
        except _Unstable as unstable:
            last_difference = str(unstable)
            continue
        if first_roots == second_roots and [_comparable(o) for o in first] == [_comparable(o) for o in second]:
            return ExposureScan(
                roots=first_roots, observations=first, attempts_used=attempt, bytes_read=bytes_read,
                rules_digest=_rules_digest(rules), hooks_used=hooks is not None, limits=limits,
            )
        last_difference = _first_difference(first, second)
    _refuse(
        StructuralFailure.UNSTABLE_LISTING,
        f"racine instable après {limits.max_attempts} essai(s) ; dernier écart : {last_difference}",
    )
