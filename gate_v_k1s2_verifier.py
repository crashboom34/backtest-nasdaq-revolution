"""
gate_v_k1s2_verifier.py — K1 Étape 2, lot L3-A : vérificateur PUR de la chaîne de preuves Walk-Forward (contrat R9 sections 5 à 7, PROPOSED).

Entrée : des OBSERVATIONS explicites (`ObservedItem`, `ObservedRunTree`) d'un dossier de campagne, produites par un scan B2 / B3 v5-A et fournies par l'appelant.
Sortie : un `ChainVerification` — la liste fermée des défauts (`ChainRefusal`) ou, sans défaut, les faits de hash de la chaîne.

Ce que ce module ÉTABLIT, et seulement cela : « la chaîne examinée est structurellement et cryptographiquement cohérente avec les observations qui lui ont été
fournies » — attribution au run exact, versions, hashs des octets exacts, références croisées couverture → sessions → run → sceau (contrats purs de L2, qui
reste le filet de sécurité final), exhaustivité des sessions et des sorties `walk_forward/**` OBSERVÉES face au sceau, absence d'entrée inconnue, d'anomalie ou
d'orphelin dans son périmètre.

Ce qu'il NE PROUVE PAS (`NOT_PROVEN`, `requires_independent_rescan`) : la lecture réelle du DataFrame par un worker, l'exclusivité des sources chargées, l'antériorité du
sceau, la durabilité, ni — surtout — l'absence d'exposition. Un objet d'observation construit à la main n'est pas une preuve de lecture indépendante : E3-J devra
RESCANNER les sources et recalculer. Aucun verdict n'existe ici (ni FRESH, ni NO_OVERLAP, ni admission, ni Claim, ni autorisation FINAL_HOLDOUT) ; les raisons
`RUN_OUTPUT_UNVERIFIED` / `RUN_EVIDENCE_UNVERIFIED` de B3 v5-A ne sont PAS levées par ce lot.

Module PUR : aucun accès disque, réseau, horloge ni registre. Le seul calcul cryptographique propre est le SHA-256 d'octets BRUTS observés (la définition d'un
`content_hash` de B2) ; aucune préimage de L1 / L2 n'est recalculée.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import gate_v_run_evidence_models as ev
from gate_v_exposure_scan import StrictJsonError, parse_strict_json

__all__ = [
    "MAX_CONTENT_BYTES", "MAX_ITEMS", "NOT_PROVEN", "TABLE_DIGEST", "TABLE_VERSION", "ancestor_directories", "ChainFacts", "ChainRefusal", "ChainVerification", "Defect", "ObservationRefusal", "ObservationRefused",
    "ObservedItem", "ObservedKind", "ObservedRunTree", "verify_run_chain",
]

MAX_ITEMS = 100_000                  # un arbre de campagne réel en compte quelques centaines ; au-delà : entrée hostile
MAX_CONTENT_BYTES = 4 * 1024 * 1024  # octets conservés par entrée (preuves JSON, ValidationRun) ; les sorties ne sont que hachées
MAX_TOTAL_CONTENT_BYTES = 64 * 1024 * 1024
_MAX_PATH_CHARS = 1024               # plafond par défaut de B2 (`max_path_length`) : au-delà, entrée hostile
_MAX_DEPTH = 32                      # segments ; la complexité des ancêtres reste ainsi bornée par MAX_ITEMS x 32 x 1024
_MAX_SEGMENT_BYTES = 255
_MAX_HEX_RUN = 256                   # une suite hexadécimale plus longue dans le run n'est pas une citation de hash exploitable : refus conservateur
_RUN_JSON_MAX_DEPTH = 64
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX_RUN = re.compile(r"[0-9a-f]{64,}")
_CAMPAIGN_NAME = re.compile(r"gate_v_v2_[0-9a-f]{64}")
_WF_RUN_ID = re.compile(r"(gate_v_v2_[0-9a-f]{64})_walk_forward")
_SESSION_FILE = re.compile(r"run_session_([0-9]{4})\.json")
_ANOMALY_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
# Identité de la table fermée de B3 v5-A (disposition CAMPAIGN_DIR), FIGÉE ici : un garde-fou de B3 interdit qu'un autre module que B5 référence le module v5, y compris par son nom.
# Les tests comparent ces valeurs à `B3_V5_SEMANTICS_VERSION` et `B3_V5_RULES_DIGESTS` (aucune dérive possible sans test rouge).
TABLE_VERSION = "gate_v_exposure_interpreters_" + "v5"
TABLE_DIGEST = "aa389aca9e29052ce9812c766f99abaf95a2bb656a3e82fcff17ab041d4a10af"
_RUN_FILE_NAMES = frozenset({"validation_run.json", "run_data_coverage.json", "run_seal.json"})

# Garanties que ce module ne fournit PAS, quel que soit le résultat (frontière scientifique, R9 section 5.3 et ADR 0025 23.30.1).
NOT_PROVEN = ("WORKER_READ", "SOURCE_EXCLUSIVITY", "SEAL_ANTERIORITY", "ABSENCE_OF_EXPOSURE", "DURABILITY")


# ── Observations explicites ───────────────────────────────────────────────────────────────────────────────────────────────────────────
class ObservationRefusal(str, Enum):
    BAD_PATH = "BAD_PATH"
    BAD_KIND = "BAD_KIND"
    BAD_SIZE = "BAD_SIZE"
    BAD_HASH = "BAD_HASH"
    BAD_CONTENT = "BAD_CONTENT"
    INCONSISTENT = "INCONSISTENT"
    BAD_TREE = "BAD_TREE"


class ObservationRefused(ValueError):
    """Observation hostile ou contradictoire : aucun objet n'est construit. `code` ∈ `ObservationRefusal`."""

    def __init__(self, code: ObservationRefusal, message: str = "") -> None:
        super().__init__(f"{code.value}: {message}" if message else code.value)
        self.code = code
        self.detail = message

    def __reduce__(self):
        return (ObservationRefused, (self.code, self.detail))


def _refuse(code: ObservationRefusal, message: str):
    raise ObservationRefused(code, message)


class ObservedKind(str, Enum):
    FILE = "FILE"            # fichier régulier reconnu, lu sans anomalie : taille et SHA-256 des octets bruts
    DIRECTORY = "DIRECTORY"  # répertoire reconnu
    INERT = "INERT"          # fichier reconnu par son nom, jamais ouvert ni haché : présent, mais sans empreinte (jamais une sortie ni une preuve vérifiable)
    ORPHAN = "ORPHAN"        # résidu de publication interrompue : reconnu, jamais lu, jamais une sortie
    UNKNOWN = "UNKNOWN"      # entrée hors table
    ANOMALY = "ANOMALY"      # entrée reconnue mais en anomalie de source (illisible, trop grande, nature fausse, lien...)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_path(path) -> str:
    if type(path) is not str or not path or len(path) > _MAX_PATH_CHARS or not path.isascii():
        _refuse(ObservationRefusal.BAD_PATH, f"chemin texte ASCII non vide de au plus {_MAX_PATH_CHARS} caractères exigé")
    parts = path.split("/")
    if len(parts) > _MAX_DEPTH:
        _refuse(ObservationRefusal.BAD_PATH, f"plus de {_MAX_DEPTH} segments")
    for part in parts:
        if (not part or part in (".", "..") or part.endswith((".", " ")) or len(part.encode("utf-8")) > _MAX_SEGMENT_BYTES
                or any(ch in part for ch in ("\\", ":")) or any(ord(ch) < 32 or ord(ch) == 127 for ch in part)):
            _refuse(ObservationRefusal.BAD_PATH, f"chemin relatif POSIX normalisé exigé : {path[:80]!r}")
    return path


@dataclass(frozen=True)
class ObservedItem:
    """Fait observé sur une entrée du dossier de campagne (chemin relatif POSIX). Seul un FILE propre porte taille, SHA-256 et, éventuellement, ses octets bruts ;
    s'ils sont fournis, ils DOIVENT hacher au SHA-256 annoncé (un objet contradictoire ne se construit pas). Une anomalie n'existe que pour ANOMALY (obligatoire)
    et UNKNOWN (facultative)."""

    path: str
    kind: ObservedKind
    size: Optional[int] = None
    sha256: Optional[str] = None
    content: Optional[bytes] = None
    anomaly: Optional[str] = None

    def __post_init__(self) -> None:
        _check_path(self.path)
        if type(self.kind) is not ObservedKind:
            _refuse(ObservationRefusal.BAD_KIND, "kind doit être un ObservedKind")
        if self.kind is ObservedKind.FILE:
            if type(self.size) is not int or self.size < 0:
                _refuse(ObservationRefusal.BAD_SIZE, "un fichier porte sa taille (entier positif ou nul)")
            if type(self.sha256) is not str or _HEX64.fullmatch(self.sha256) is None:
                _refuse(ObservationRefusal.BAD_HASH, "un fichier porte son SHA-256 (64 hexadécimaux minuscules)")
            if self.content is not None:
                if type(self.content) is not bytes:
                    _refuse(ObservationRefusal.BAD_CONTENT, "content doit être de type bytes")
                if len(self.content) > MAX_CONTENT_BYTES:
                    _refuse(ObservationRefusal.BAD_CONTENT, "octets conservés trop volumineux")
                if len(self.content) != self.size or _digest(self.content) != self.sha256:
                    _refuse(ObservationRefusal.INCONSISTENT, "les octets fournis contredisent la taille ou le SHA-256 annoncés")
        elif self.size is not None or self.sha256 is not None or self.content is not None:
            _refuse(ObservationRefusal.INCONSISTENT, "seul un fichier propre porte taille, SHA-256 ou octets")
        if self.kind is ObservedKind.ANOMALY:
            if type(self.anomaly) is not str or _ANOMALY_CODE.fullmatch(self.anomaly) is None:
                _refuse(ObservationRefusal.INCONSISTENT, "une entrée en anomalie porte son code d'anomalie (MAJUSCULES_ET_TIRETS_BAS)")
        elif self.kind is ObservedKind.UNKNOWN:
            if self.anomaly is not None and (type(self.anomaly) is not str or _ANOMALY_CODE.fullmatch(self.anomaly) is None):
                _refuse(ObservationRefusal.INCONSISTENT, "code d'anomalie mal formé")
        elif self.anomaly is not None:
            _refuse(ObservationRefusal.INCONSISTENT, "une anomalie n'existe que pour les entrées ANOMALY et UNKNOWN")


@dataclass(frozen=True)
class ObservedRunTree:
    """Observations d'UN dossier de campagne, issues du scan B2 sous les tables FERMÉES de B3 v5-A (`table_version` + `rules_digest` sont vérifiés : une autre table
    n'est pas acceptée). Chemins uniques ; l'ordre des entrées est indifférent au résultat."""

    campaign_dir_name: str
    table_version: str
    rules_digest: str
    items: tuple

    def __post_init__(self) -> None:
        if type(self.campaign_dir_name) is not str or _CAMPAIGN_NAME.fullmatch(self.campaign_dir_name) is None:
            _refuse(ObservationRefusal.BAD_TREE, "le dossier de campagne s'appelle gate_v_v2_<64 hexadécimaux>")
        if type(self.table_version) is not str or type(self.rules_digest) is not str or _HEX64.fullmatch(self.rules_digest) is None:
            _refuse(ObservationRefusal.BAD_TREE, "version de table (texte) et digest de table (64 hexadécimaux) exigés")
        if type(self.items) is not tuple or any(type(item) is not ObservedItem for item in self.items):
            _refuse(ObservationRefusal.BAD_TREE, "items doit être un tuple d'ObservedItem")
        if len(self.items) > MAX_ITEMS:
            _refuse(ObservationRefusal.BAD_TREE, f"plus de {MAX_ITEMS} entrées")
        if len({item.path for item in self.items}) != len(self.items):
            _refuse(ObservationRefusal.BAD_TREE, "chemin observé en double")
        if sum(len(item.content) for item in self.items if item.content is not None) > MAX_TOTAL_CONTENT_BYTES:
            _refuse(ObservationRefusal.BAD_TREE, "octets conservés trop volumineux au total")


# ── Résultat ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
class ChainRefusal(str, Enum):
    """Vocabulaire FERMÉ des défauts (reprend les motifs de R9 section 7.5 là où ils existent). Aucun mot de verdict."""

    BAD_INPUT = "BAD_INPUT"
    WRONG_TABLE = "WRONG_TABLE"                              # observations produites sous une autre table que celle de B3 v5-A
    FOREIGN_CAMPAIGN = "FOREIGN_CAMPAIGN"                    # le run attendu n'appartient pas à ce dossier de campagne
    MIXED_RUNS = "MIXED_RUNS"                                # un second run Walk-Forward dans la même campagne
    NO_VALIDATION_RUN = "NO_VALIDATION_RUN"
    RUN_NOT_ATTRIBUTABLE = "RUN_NOT_ATTRIBUTABLE"
    RUN_ALTERED = "RUN_ALTERED"                              # le sceau référence d'autres octets de run que ceux observés
    NO_COVERAGE = "NO_COVERAGE"
    COVERAGE_INVALID = "COVERAGE_INVALID"
    COVERAGE_NOT_ATTRIBUTABLE = "COVERAGE_NOT_ATTRIBUTABLE"
    COVERAGE_ALTERED = "COVERAGE_ALTERED"                    # le sceau référence une autre couverture que celle observée
    SESSION_MISSING = "SESSION_MISSING"
    SESSION_GAP = "SESSION_GAP"
    SESSION_INVALID = "SESSION_INVALID"
    SESSION_NOT_ATTRIBUTABLE = "SESSION_NOT_ATTRIBUTABLE"
    SESSION_FILE_MISMATCH = "SESSION_FILE_MISMATCH"          # numéro du fichier ≠ indice de la session
    SESSION_ALTERED = "SESSION_ALTERED"
    SESSION_COVERAGE_MISMATCH = "SESSION_COVERAGE_MISMATCH"  # la session référence une autre couverture que celle observée
    SESSION_FRAME_MISMATCH = "SESSION_FRAME_MISMATCH"
    SESSION_UNLISTED = "SESSION_UNLISTED"
    NO_SEAL = "NO_SEAL"
    SEAL_INVALID = "SEAL_INVALID"
    SEAL_NOT_ATTRIBUTABLE = "SEAL_NOT_ATTRIBUTABLE"
    FRAME_AFTER_MISMATCH = "FRAME_AFTER_MISMATCH"
    OUTPUT_MISSING = "OUTPUT_MISSING"                        # sortie scellée, non observée
    OUTPUT_UNSEALED = "OUTPUT_UNSEALED"                      # sortie observée, non scellée
    OUTPUT_ALTERED = "OUTPUT_ALTERED"                        # hash ou taille observés ≠ ceux du sceau
    OUTPUT_ANOMALY = "OUTPUT_ANOMALY"
    OUTPUT_ORPHAN = "OUTPUT_ORPHAN"
    EMPTY_OUTPUT_DIRECTORY = "EMPTY_OUTPUT_DIRECTORY"
    UNKNOWN_RUN_FILE = "UNKNOWN_RUN_FILE"
    RUN_FILE_ANOMALY = "RUN_FILE_ANOMALY"
    RUN_FILE_ORPHAN = "RUN_FILE_ORPHAN"
    UNKNOWN_ENTRY_IN_TREE = "UNKNOWN_ENTRY_IN_TREE"
    ENTRY_ANOMALY = "ENTRY_ANOMALY"
    HASH_ROLE_COLLISION = "HASH_ROLE_COLLISION"
    REFERENCE_CYCLE = "REFERENCE_CYCLE"
    CHAIN_REFUSED = "CHAIN_REFUSED"                          # refus de L2 sans équivalent plus précis (code L2 dans `l2_code`)


@dataclass(frozen=True)
class Defect:
    code: ChainRefusal
    detail: str
    path: Optional[str] = None
    l2_code: Optional[str] = None

    def __post_init__(self) -> None:
        if type(self.code) is not ChainRefusal or type(self.detail) is not str or (self.path is not None and type(self.path) is not str) \
                or (self.l2_code is not None and type(self.l2_code) is not str):
            raise ValueError("Defect mal formé")


@dataclass(frozen=True)
class ChainFacts:
    """Hashs d'une chaîne jugée COHÉRENTE avec les observations fournies. Ni verdict, ni autorisation, ni preuve d'absence d'exposition."""

    validation_run_id: str
    coverage_sha256: str
    session_sha256s: tuple
    run_record_sha256: str
    seal_sha256: str
    finalized_by_recovery: bool
    session_count: int
    output_count: int
    output_bytes: int


@dataclass(frozen=True)
class ChainVerification:
    """Résultat total : `defects` vide ⇔ `facts` présent. `established` signifie « cohérent avec les observations fournies », rien de plus."""

    run_id: str
    defects: tuple
    facts: Optional[ChainFacts]

    def __post_init__(self) -> None:
        if type(self.run_id) is not str or type(self.defects) is not tuple or any(type(d) is not Defect for d in self.defects):
            raise ValueError("ChainVerification mal formé")
        if bool(self.defects) == (self.facts is not None) or (self.facts is not None and type(self.facts) is not ChainFacts):
            raise ValueError("les faits existent si et seulement si aucun défaut n'est relevé")

    @property
    def established(self) -> bool:
        return not self.defects

    @property
    def requires_independent_rescan(self) -> bool:
        """Toujours vrai : les observations sont fournies par l'appelant ; E3-J doit rescanner et recalculer."""
        return True

    @property
    def not_proven(self) -> tuple:
        return NOT_PROVEN


# ── Vérification ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _report(run_id: str, found: list, facts: Optional[ChainFacts] = None) -> ChainVerification:
    unique = {(d.code.value, d.path or "", d.detail): d for d in found}
    ordered = tuple(unique[key] for key in sorted(unique))
    return ChainVerification(run_id, ordered, None if ordered else facts)


def _under(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory + "/")


def ancestor_directories(paths) -> set:
    """Tous les répertoires ancêtres des `paths` (chemins POSIX normalisés), en temps linéaire : on remonte jusqu'à un ancêtre déjà vu."""
    seen: set = set()
    for path in paths:
        parent = path.rpartition("/")[0]
        while parent and parent not in seen:
            seen.add(parent)
            parent = parent.rpartition("/")[0]
    return seen


def _cited_hashes(text: str):
    """(hashs de 64 hexadécimaux cités dans `text`, suite hexadécimale trop longue ?). Une seule passe ; insensible à la casse ; un hash noyé dans une suite
    plus longue (jusqu'à `_MAX_HEX_RUN`) compte comme cité. Au-delà, la suite est refusée par l'appelant (pas de balayage quadratique)."""
    cited, overlong = set(), False
    for run in _HEX_RUN.findall(text.lower()):
        if len(run) > _MAX_HEX_RUN:
            overlong = True
            continue
        cited.update(run[start:start + 64] for start in range(len(run) - 63))
    return cited, overlong


def _l2_defect(refusal: ev.EvidenceRefused, code: ChainRefusal, path: Optional[str] = None) -> Defect:
    return Defect(code, f"refus de L2 ({refusal.code.value}) : {refusal.detail}"[:300], path, refusal.code.value)


_L2_CHAIN_CODES = {"HASH_ROLE_COLLISION": ChainRefusal.HASH_ROLE_COLLISION, "CIRCULAR_REFERENCE": ChainRefusal.REFERENCE_CYCLE}


def verify_run_chain(tree, expected_run_id) -> ChainVerification:
    """Vérifie la chaîne de preuves Walk-Forward du run `expected_run_id` contre les observations `tree`. FONCTION TOTALE, SAUF épuisement de ressources (`MemoryError`,
    `RecursionError`), qui se propage (B2 et L2 ne la convertissent plus en défaut typé sur un document d'imbrication <= 64) : un argument hostile donne un rapport `BAD_INPUT`, jamais une exception. Tous les défauts décelables sont rapportés, dans un ordre
    déterministe. Un objet d'observation FORGÉ (champs altérés après construction, contournant `__post_init__`) qui ferait échouer le calcul est rapporté `BAD_INPUT` : jamais « établi »."""
    try:
        return _verify_run_chain(tree, expected_run_id)
    except (MemoryError, RecursionError):                        # P5-bis (A1) : épuisement de ressources, jamais un défaut des données ; se propage (le protocole rend AUDIT_INTERNAL_FAILURE)
        raise
    except Exception:                                            # noqa: BLE001 — voie conservatrice : une exception inattendue ne peut jamais produire « établi » (`RuntimeError` hors ressources comprise)
        return _report(expected_run_id if type(expected_run_id) is str else "", [Defect(ChainRefusal.BAD_INPUT, "observations incohérentes ou forgées")])


def _verify_run_chain(tree, expected_run_id) -> ChainVerification:
    run_id = expected_run_id if type(expected_run_id) is str else ""
    if type(tree) is not ObservedRunTree or type(expected_run_id) is not str:
        return _report(run_id, [Defect(ChainRefusal.BAD_INPUT, "tree doit être un ObservedRunTree et expected_run_id un texte")])
    if tree.table_version != TABLE_VERSION or tree.rules_digest != TABLE_DIGEST:
        return _report(run_id, [Defect(ChainRefusal.WRONG_TABLE, "les observations ne proviennent pas de la table fermée de B3 v5-A (CAMPAIGN_DIR)")])
    match = _WF_RUN_ID.fullmatch(expected_run_id)
    if match is None:
        return _report(run_id, [Defect(ChainRefusal.BAD_INPUT, "expected_run_id doit être l'identifiant d'un run walk_forward")])
    if match.group(1) != tree.campaign_dir_name:
        return _report(run_id, [Defect(ChainRefusal.FOREIGN_CAMPAIGN, "le run attendu n'appartient pas à ce dossier de campagne")])
    found: list = []
    by_path = {item.path: item for item in tree.items}
    run_dir = f"validations/{run_id}"
    outputs: dict = {}                                    # sorties observées : chemin → ObservedItem (FILE)
    output_directories: list = []
    sessions_seen: dict = {}                              # numéro de fichier → ObservedItem
    for item in tree.items:
        path = item.path
        in_outputs, in_run = _under(path, "walk_forward"), _under(path, run_dir)
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] == "validations" and parts[1] != run_id and _WF_RUN_ID.fullmatch(parts[1]) is not None:
            found.append(Defect(ChainRefusal.MIXED_RUNS, "un second run walk_forward existe dans cette campagne", f"validations/{parts[1]}"))
            continue
        if item.kind is ObservedKind.UNKNOWN:
            code = ChainRefusal.UNKNOWN_RUN_FILE if (in_outputs or in_run) else ChainRefusal.UNKNOWN_ENTRY_IN_TREE
            found.append(Defect(code, f"entrée inconnue ({item.anomaly or 'hors table'})", path))
        elif item.kind is ObservedKind.ANOMALY:
            code = ChainRefusal.OUTPUT_ANOMALY if in_outputs else ChainRefusal.RUN_FILE_ANOMALY if in_run else ChainRefusal.ENTRY_ANOMALY
            found.append(Defect(code, f"anomalie de source {item.anomaly}", path))
        elif item.kind is ObservedKind.INERT:
            if in_outputs:
                found.append(Defect(ChainRefusal.OUTPUT_ANOMALY, "fichier non haché dans les sorties : ni vérifiable ni scellable", path))
            elif in_run:
                found.append(Defect(ChainRefusal.RUN_FILE_ANOMALY, "fichier non haché dans le dossier du run : ni vérifiable ni attribuable", path))
        elif item.kind is ObservedKind.ORPHAN:
            if in_outputs:
                found.append(Defect(ChainRefusal.OUTPUT_ORPHAN, "résidu de publication interrompue : jamais une sortie", path))
            elif in_run:
                found.append(Defect(ChainRefusal.RUN_FILE_ORPHAN, "résidu de publication interrompue dans le dossier du run", path))
        elif item.kind is ObservedKind.DIRECTORY:
            if in_outputs:
                output_directories.append(path)
            elif in_run and path != run_dir:
                found.append(Defect(ChainRefusal.UNKNOWN_RUN_FILE, "sous-répertoire inattendu dans le dossier du run", path))
        elif in_outputs:
            outputs[path] = item
        elif in_run:
            name = path[len(run_dir) + 1:]
            number = _SESSION_FILE.fullmatch(name)
            if number is not None:
                sessions_seen[int(number.group(1))] = item
            elif name not in _RUN_FILE_NAMES:
                found.append(Defect(ChainRefusal.UNKNOWN_RUN_FILE, "fichier inconnu dans le dossier du run", path))
    non_empty = ancestor_directories(outputs)
    found.extend(Defect(ChainRefusal.EMPTY_OUTPUT_DIRECTORY, "répertoire de sorties sans aucun fichier scellable", d) for d in output_directories if d not in non_empty)

    def file_at(relative: str) -> Optional[ObservedItem]:
        item = by_path.get(f"{run_dir}/{relative}")
        return item if item is not None and item.kind is ObservedKind.FILE else None

    # ValidationRun : attribution au run exact (identifiant et type), octets observés
    run_item, cited = file_at("validation_run.json"), frozenset()
    if run_item is None:
        found.append(Defect(ChainRefusal.NO_VALIDATION_RUN, "validation_run.json absent", f"{run_dir}/validation_run.json"))
    elif run_item.content is None:
        found.append(Defect(ChainRefusal.RUN_NOT_ATTRIBUTABLE, "octets du run non fournis", run_item.path))
    else:
        try:
            record = parse_strict_json(run_item.content, max_bytes=MAX_CONTENT_BYTES, max_depth=_RUN_JSON_MAX_DEPTH)
        except StrictJsonError as error:
            record = None
            found.append(Defect(ChainRefusal.RUN_NOT_ATTRIBUTABLE, f"validation_run.json illisible ({error.anomaly.value})", run_item.path))
        else:
            if type(record) is not dict or record.get("validation_run_id") != run_id or record.get("validation_type") != "walk_forward":
                found.append(Defect(ChainRefusal.RUN_NOT_ATTRIBUTABLE, "validation_run.json n'est pas celui de ce run walk_forward", run_item.path))
        cited, overlong = _cited_hashes(run_item.content.decode("utf-8", "replace"))
        if overlong:
            found.append(Defect(ChainRefusal.RUN_NOT_ATTRIBUTABLE, "suite hexadécimale anormalement longue dans validation_run.json", run_item.path))
    # Couverture
    coverage, coverage_item = None, file_at("run_data_coverage.json")
    if coverage_item is None:
        found.append(Defect(ChainRefusal.NO_COVERAGE, "run_data_coverage.json absent", f"{run_dir}/run_data_coverage.json"))
    elif coverage_item.content is None:
        found.append(Defect(ChainRefusal.COVERAGE_INVALID, "octets de la couverture non fournis", coverage_item.path))
    else:
        try:
            coverage = ev.RunDataCoverage.from_bytes(coverage_item.content)
        except ev.EvidenceRefused as refusal:
            found.append(_l2_defect(refusal, ChainRefusal.COVERAGE_INVALID, coverage_item.path))
        else:
            if coverage.validation_run_id != run_id:
                found.append(Defect(ChainRefusal.COVERAGE_NOT_ATTRIBUTABLE, "couverture d'un autre run", coverage_item.path))
                coverage = None
    # Sessions
    session_models: dict = {}
    for number in sorted(sessions_seen):
        item = sessions_seen[number]
        if item.content is None:
            found.append(Defect(ChainRefusal.SESSION_INVALID, "octets de la session non fournis", item.path))
            continue
        try:
            session = ev.RunSession.from_bytes(item.content)
        except ev.EvidenceRefused as refusal:
            found.append(_l2_defect(refusal, ChainRefusal.SESSION_INVALID, item.path))
            continue
        if session.validation_run_id != run_id:
            found.append(Defect(ChainRefusal.SESSION_NOT_ATTRIBUTABLE, "session d'un autre run", item.path))
        elif session.session_index != number:
            found.append(Defect(ChainRefusal.SESSION_FILE_MISMATCH, f"le fichier porte le numéro {number} mais l'indice de la session est {session.session_index}", item.path))
        else:
            session_models[number] = session
    if sessions_seen and sorted(sessions_seen) != list(range(1, len(sessions_seen) + 1)):
        found.append(Defect(ChainRefusal.SESSION_GAP, "numéros de fichiers de session non consécutifs à partir de 1", run_dir))
    # Sceau
    seal, seal_item = None, file_at("run_seal.json")
    if seal_item is None:
        found.append(Defect(ChainRefusal.NO_SEAL, "run_seal.json absent", f"{run_dir}/run_seal.json"))
    elif seal_item.content is None:
        found.append(Defect(ChainRefusal.SEAL_INVALID, "octets du sceau non fournis", seal_item.path))
    else:
        try:
            seal = ev.RunSeal.from_bytes(seal_item.content)
        except ev.EvidenceRefused as refusal:
            found.append(_l2_defect(refusal, ChainRefusal.SEAL_INVALID, seal_item.path))
        else:
            if seal.validation_run_id != run_id:
                found.append(Defect(ChainRefusal.SEAL_NOT_ATTRIBUTABLE, "sceau d'un autre run", seal_item.path))
                seal = None
    if not sessions_seen and (seal is None or not seal.sessions):
        found.append(Defect(ChainRefusal.SESSION_MISSING, "aucune session observée", f"{run_dir}/run_session_0001.json"))
    if seal is not None:
        if run_item is not None and seal.run_record_sha256 != run_item.sha256:
            found.append(Defect(ChainRefusal.RUN_ALTERED, "le sceau référence d'autres octets de run que ceux observés", run_item.path))
        if coverage is not None and coverage_item is not None:
            if seal.coverage_sha256 != coverage_item.sha256:
                found.append(Defect(ChainRefusal.COVERAGE_ALTERED, "le sceau référence une autre couverture que celle observée", coverage_item.path))
            for number, session in sorted(session_models.items()):
                if session.coverage_sha256 != coverage_item.sha256:
                    found.append(Defect(ChainRefusal.SESSION_COVERAGE_MISMATCH, "la session référence une autre couverture que celle observée", sessions_seen[number].path))
                elif session.frame_sha256_before != coverage.frame_sha256 or session.frame_row_count != coverage.row_count:
                    found.append(Defect(ChainRefusal.SESSION_FRAME_MISMATCH, "trame présentée à la session différente de celle de la couverture", sessions_seen[number].path))
            if seal.frame_sha256_after is not None and seal.frame_sha256_after != coverage.frame_sha256:
                found.append(Defect(ChainRefusal.FRAME_AFTER_MISMATCH, "digest « après » différent de celui de la couverture", seal_item.path))
        listed = dict(seal.sessions)
        for index, digest in sorted(listed.items()):
            observed = sessions_seen.get(index)
            if observed is None:
                found.append(Defect(ChainRefusal.SESSION_MISSING, f"session {index} listée par le sceau, non observée", f"{run_dir}/run_session_{index:04d}.json"))
            elif index in session_models and observed.sha256 != digest:
                found.append(Defect(ChainRefusal.SESSION_ALTERED, f"session {index} : hash observé différent de celui du sceau", observed.path))
        found.extend(Defect(ChainRefusal.SESSION_UNLISTED, "session observée non listée par le sceau", sessions_seen[number].path) for number in sorted(sessions_seen) if number not in listed)
        if seal_item is not None and seal_item.sha256 in cited:
            found.append(Defect(ChainRefusal.REFERENCE_CYCLE, "les octets du run citent le hash du sceau qui référence le run", run_item.path if run_item else None))
        sealed = {path: (digest, size) for path, digest, size in seal.output_artifacts}
        for path, (digest, size) in sorted(sealed.items()):
            seen = outputs.get(path)
            if seen is None:
                found.append(Defect(ChainRefusal.OUTPUT_MISSING, "sortie scellée, non observée", path))
            elif seen.sha256 != digest or seen.size != size:
                what = "hash et taille" if seen.sha256 != digest and seen.size != size else "hash" if seen.sha256 != digest else "taille"
                found.append(Defect(ChainRefusal.OUTPUT_ALTERED, f"{what} observé(e) différent(e) de celui/celle du sceau", path))
        found.extend(Defect(ChainRefusal.OUTPUT_UNSEALED, "sortie observée, non scellée", path) for path in sorted(outputs) if path not in sealed)
    if found:
        return _report(run_id, found)
    # Filet final : les contrôles croisés de L2 (autorité), sur les modèles issus des octets observés.
    chain_sessions = [session_models[number] for number in sorted(session_models)]
    references = [h for h in (coverage_item.sha256, seal_item.sha256, *(item.sha256 for item in sessions_seen.values())) if h in cited]   # arêtes du graphe de L2
    try:
        chain = ev.verify_run_evidence(coverage, chain_sessions, seal, run_item.sha256, references)
    except ev.EvidenceRefused as refusal:
        return _report(run_id, [_l2_defect(refusal, _L2_CHAIN_CODES.get(refusal.code.value, ChainRefusal.CHAIN_REFUSED))])
    facts = ChainFacts(chain.validation_run_id, chain.coverage_sha256, chain.session_sha256s, chain.run_record_sha256, chain.seal_sha256, chain.finalized_by_recovery,
                       len(chain_sessions), len(seal.output_artifacts), sum(size for _, _, size in seal.output_artifacts))
    return _report(run_id, [], facts)
