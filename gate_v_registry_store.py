"""AF-V-07 Slice E3-D — initialisation et LECTURE STRICTE du registre sur disque (ADR 0025 Décisions 23.9 et 23.10 étape 1). Mode `SYNTHETIC` seulement.

Disposition (PROPOSÉE, P14 ; l'ADR nomme `identity.json` et le motif `admissions/admission_<seq>.json` sans fixer le reste) :

    <racine>/identity.json                       {registry_identity_version, registry_id, instance_id, mode, durability_profile}
    <racine>/admissions/admission_<6 chiffres>.json

`instance_id` d'`identity.json` est celui du slot 0 (genèse) ; l'instance en vigueur se lit dans la chaîne (`REBIND`). Un registre `REAL` est REFUSÉ à la lecture (`REAL` est
DÉSACTIVÉ, 23.2) : la liaison physique (volume, inode, hôte, permissions) relève de la configuration root et reste BLOQUÉE.

Lecture : ÉCHEC FERMÉ. Table fermée des entrées (seuls `identity.json`, `admissions/`, `admission_<seq>.json` et les orphelins `.registry.tmp.<uuid4>` de la primitive E3-C), refus de
tout lien symbolique ou point d'analyse, plafonds de lecture provisoires (P8), JSON strict (UTF-8 sans BOM, sans clé dupliquée, sans constante non finie, sans flottant) dont les octets
égalent EXACTEMENT ceux du JSON normatif d'E3-C (point fixe), numérotation dense depuis 0, nom de fichier égal à `seq`, puis vérification de la chaîne (`gate_v_registry_chain`). Un
fichier présent mais invalide, illisible ou trop gros n'est JAMAIS traité comme absent. La lecture ne crée, ne modifie, ne supprime ni ne répare rien.

Ordre (23.10 étape 1) : lire la chaîne PUIS barrière de lecture (`barrier=True`) ; la barrière s'applique à `admissions/`.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from atomic_json_store import (
    DurabilityProfile,
    LinkPublicationError,
    NormativeJsonError,
    TempNaming,
    directory_read_barrier,
    is_publication_temp_name,
    publish_json_by_link,
    serialize_normative_json,
)
from gate_v_registry_chain import RegistryChain, verify_chain
from gate_v_registry_model import (
    RegistryMode,
    genesis_prev_content_hash,
    parse_slot_file_name,
    slot_file_name,
    validate_instance_id,
    validate_registry_id,
)

IDENTITY_FILE = "identity.json"
ADMISSIONS_DIR = "admissions"
IDENTITY_VERSION = "gate_v_registry_identity_v1"          # PROPOSÉ (P14)
_IDENTITY_KEYS = frozenset({"registry_identity_version", "registry_id", "instance_id", "mode", "durability_profile"})

# PROPOSÉ (P8) : plafonds provisoires, aucune valeur dans l'ADR (23.24 « limite mémoire du chargeur »).
MAX_SLOT_BYTES = 262144
MAX_IDENTITY_BYTES = 4096
MAX_SLOTS = 100000
# PROPOSÉ (P20) : nombre de listages de `admissions/` avant de conclure à un trou (un listage peut être déchiré par un ajout concurrent).
LISTING_ATTEMPTS = 3

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class ReadFailure(str, Enum):
    """Vocabulaire FERME des échecs de lecture/initialisation (aucun repli)."""

    ROOT_UNUSABLE = "ROOT_UNUSABLE"
    ROOT_EXISTS = "ROOT_EXISTS"
    UNKNOWN_ENTRY = "UNKNOWN_ENTRY"
    NOT_REGULAR = "NOT_REGULAR"
    IDENTITY_MISSING = "IDENTITY_MISSING"
    IDENTITY_INVALID = "IDENTITY_INVALID"
    MODE_REFUSED = "MODE_REFUSED"
    SLOT_UNREADABLE = "SLOT_UNREADABLE"
    SLOT_INVALID = "SLOT_INVALID"
    SLOT_GAP = "SLOT_GAP"
    SLOT_NAME_MISMATCH = "SLOT_NAME_MISMATCH"
    TOO_LARGE = "TOO_LARGE"
    TOO_MANY_SLOTS = "TOO_MANY_SLOTS"
    BARRIER_FAILED = "BARRIER_FAILED"


class RegistryReadError(Exception):
    """Le registre n'a pas pu être lu ou initialisé de façon sûre. Une chaîne lisible mais incohérente lève, elle, `RegistryChainError`."""

    def __init__(self, failure: ReadFailure, message: str) -> None:
        super().__init__(f"{failure.value} : {message}")
        self.failure = failure
        self.message = message


@dataclass(frozen=True)
class RegistryIdentity:
    registry_id: str
    instance_id: str                      # instance de GENÈSE (slot 0)
    mode: RegistryMode
    durability_profile: DurabilityProfile


@dataclass(frozen=True)
class RegistrySnapshot:
    """Lecture complète et vérifiée à un instant : la chaîne ne peut que s'allonger ensuite (append-only)."""

    root: Path
    identity: RegistryIdentity
    chain: RegistryChain

    def slot_path(self, seq: int) -> Path:
        return self.root / ADMISSIONS_DIR / slot_file_name(seq)


def _fail(failure: ReadFailure, message: str):
    raise RegistryReadError(failure, message)


def _reject_duplicate_keys(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("clé JSON dupliquée.")
    return dict(pairs)


def _reject_constant(name):
    raise ValueError(f"constante JSON non finie {name!r} refusée.")


def _reject_float(text):
    raise ValueError(f"nombre non entier {text!r} : le JSON normatif n'admet aucun flottant.")


def _load_strict_json(raw: bytes, what: str) -> dict:
    """JSON strict : UTF-8 sans BOM, objet racine, sans clé dupliquée, constante non finie ni flottant ; `ValueError` sinon. N'établit PAS le point fixe d'octets."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{what} : BOM UTF-8 refusé.")
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant, parse_float=_reject_float)
    except RecursionError as error:
        raise ValueError(f"{what} : JSON trop profondément imbriqué.") from error
    except UnicodeDecodeError as error:
        raise ValueError(f"{what} : UTF-8 invalide ({error}).") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{what} : JSON invalide ({error}).") from error
    if type(value) is not dict:
        raise ValueError(f"{what} : un objet JSON est attendu à la racine.")
    try:
        serialize_normative_json(value)
    except NormativeJsonError as error:
        raise ValueError(f"{what} : {error}") from error
    return value


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _lstat_regular(path: Path, what: str) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(ReadFailure.SLOT_UNREADABLE, f"{what} inobservable ({error}).")
    if _is_link(info) or not stat.S_ISREG(info.st_mode):
        _fail(ReadFailure.NOT_REGULAR, f"{what} n'est pas un fichier ordinaire (lien, répertoire ou autre) : refusé, jamais suivi.")
    return info


_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)


def _read_slot_bytes(path: Path, limit: int) -> bytes:
    """Au plus `limit + 1` octets (la mémoire reste bornée) ; point d'injection de faute des tests. L'ouverture ne suit AUCUN lien final (`O_NOFOLLOW`, POSIX), ne bloque pas sur un
    FIFO (`O_NONBLOCK`) et vérifie que le fichier OUVERT est ordinaire (`fstat`) : un échange entre le `lstat` du lecteur et cette ouverture est donc refusé (TOCTOU)."""
    descriptor = os.open(path, _OPEN_FLAGS)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError(f"{path} n'est pas un fichier ordinaire au moment de l'ouverture.")
        chunks, remaining = [], limit + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_bounded(path: Path, limit: int, what: str) -> bytes:
    _lstat_regular(path, what)
    try:
        raw = _read_slot_bytes(path, limit)
    except OSError as error:
        _fail(ReadFailure.SLOT_UNREADABLE, f"{what} illisible ({error}).")
    if len(raw) > limit:
        _fail(ReadFailure.TOO_LARGE, f"{what} dépasse {limit} octets.")
    return raw


def _root_path(root: object) -> Path:
    if isinstance(root, bool) or not isinstance(root, (str, os.PathLike)):
        raise ValueError("root doit être un chemin (str ou Path).")
    path = Path(os.fspath(root))
    if not str(path).strip():
        raise ValueError("root doit être un chemin non vide.")
    return path


def _directory_entries(directory: Path, what: str) -> list:
    """Listage `(nom, lstat)`. Un temporaire `.registry.tmp.*` qui disparaît entre le listage et son `lstat` est celui d'un écrivain CONCURRENT (créé puis supprimé, 23.10 étape 7) :
    il est ignoré. La disparition de toute autre entrée (slot, identité, répertoire) est une anomalie : échec fermé."""
    entries = []
    try:
        with os.scandir(directory) as iterator:
            for entry in iterator:
                try:
                    info = os.lstat(entry.path)
                except FileNotFoundError:
                    if is_publication_temp_name(entry.name) is TempNaming.REGISTRY:
                        continue
                    _fail(ReadFailure.SLOT_UNREADABLE, f"{entry.name!r} a disparu pendant le listage de {what}.")
                entries.append((entry.name, info))
    except OSError as error:
        _fail(ReadFailure.ROOT_UNUSABLE, f"{what} illisible ({error}).")
    return entries


def _require_real_directory(path: Path, what: str) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        _fail(ReadFailure.ROOT_UNUSABLE, f"{what} absent.")
    except OSError as error:
        _fail(ReadFailure.ROOT_UNUSABLE, f"{what} inobservable ({error}).")
    if _is_link(info) or not stat.S_ISDIR(info.st_mode):
        _fail(ReadFailure.NOT_REGULAR if path.name == ADMISSIONS_DIR else ReadFailure.ROOT_UNUSABLE, f"{what} n'est pas un répertoire ordinaire.")


def _tolerated_orphan(name: str, info: os.stat_result) -> bool:
    """Orphelin `.registry.tmp.<uuid4>` de la primitive E3-C (23.10 étape 7) : inoffensif, jamais lu ; seul le nommage REGISTRY est toléré."""
    if is_publication_temp_name(name) is not TempNaming.REGISTRY:
        return False
    if _is_link(info) or not stat.S_ISREG(info.st_mode):
        _fail(ReadFailure.NOT_REGULAR, f"{name} n'est pas un fichier ordinaire.")
    return True


def _read_identity(root: Path) -> RegistryIdentity:
    path = root / IDENTITY_FILE
    try:
        os.lstat(path)
    except FileNotFoundError:
        _fail(ReadFailure.IDENTITY_MISSING, "identity.json est absent : un registre sans identité n'est pas lu.")
    except OSError as error:
        _fail(ReadFailure.ROOT_UNUSABLE, f"identity.json inobservable ({error}).")
    raw = _read_bounded(path, MAX_IDENTITY_BYTES, "identity.json")
    try:
        record = _load_strict_json(raw, "identity.json")
        if serialize_normative_json(record) != raw:
            raise ValueError("identity.json n'est pas dans la forme d'octets normative.")
        if set(record) != _IDENTITY_KEYS:
            raise ValueError(f"clés inattendues : {sorted(set(record) ^ _IDENTITY_KEYS)}.")
        if record["registry_identity_version"] != IDENTITY_VERSION:
            raise ValueError("registry_identity_version inconnue.")
        registry_id, instance_id = validate_registry_id(record["registry_id"]), validate_instance_id(record["instance_id"])
        mode_text, profile_text = record["mode"], record["durability_profile"]
        if type(mode_text) is not str or type(profile_text) is not str:
            raise ValueError("mode et durability_profile doivent être des str.")
        mode, profile = RegistryMode(mode_text), DurabilityProfile(profile_text)
    except ValueError as error:
        _fail(ReadFailure.IDENTITY_INVALID, str(error))
    if mode is not RegistryMode.SYNTHETIC:
        _fail(ReadFailure.MODE_REFUSED, "seul un registre SYNTHETIC est lu ; REAL est DÉSACTIVÉ / NON QUALIFIÉ (ADR 0025 23.2).")
    return RegistryIdentity(registry_id=registry_id, instance_id=instance_id, mode=mode, durability_profile=profile)


def _slot_sequence(admissions: Path) -> list:
    """Numéros des slots, denses depuis 0. Un répertoire n'est pas un instantané : pendant un ajout concurrent, UN listage peut montrer le slot n+1 sans le slot n. Un trou n'est donc
    conclu qu'après `LISTING_ATTEMPTS` listages successifs (re-observation, jamais une réparation) ; les appends ne font qu'ajouter des slots de rang plus élevé."""
    for _ in range(LISTING_ATTEMPTS):
        slots = {}
        for name, info in _directory_entries(admissions, "admissions/"):
            seq = parse_slot_file_name(name)
            if seq is None:
                if _tolerated_orphan(name, info):
                    continue
                _fail(ReadFailure.UNKNOWN_ENTRY, f"entrée inconnue dans admissions/ : {name!r}.")
            if _is_link(info) or not stat.S_ISREG(info.st_mode):
                _fail(ReadFailure.NOT_REGULAR, f"{name} n'est pas un fichier ordinaire (lien, répertoire ou autre) : refusé, jamais suivi.")
            slots[seq] = name
        if len(slots) > MAX_SLOTS:
            _fail(ReadFailure.TOO_MANY_SLOTS, f"plus de {MAX_SLOTS} slots.")
        ordered = sorted(slots)
        if ordered == list(range(len(ordered))):
            return ordered
    _fail(ReadFailure.SLOT_GAP, "la numérotation des slots n'est pas dense depuis 0 (slot manquant ou numéro inattendu), confirmée sur plusieurs listages : chaîne rompue.")


def _read_record(admissions: Path, seq: int) -> dict:
    name = slot_file_name(seq)
    raw = _read_bounded(admissions / name, MAX_SLOT_BYTES, name)
    try:
        record = _load_strict_json(raw, name)
        if serialize_normative_json(record) != raw:
            raise ValueError(f"{name} n'est pas dans la forme d'octets normative d'E3-C (point fixe).")
    except ValueError as error:
        _fail(ReadFailure.SLOT_INVALID, str(error))
    if record.get("seq") != seq or type(record.get("seq")) is not int:
        _fail(ReadFailure.SLOT_NAME_MISMATCH, f"{name} porte seq={record.get('seq')!r} : le nom du fichier doit égaler seq.")
    return record


def read_registry(root: object, *, barrier: bool) -> RegistrySnapshot:
    """Lecture stricte, complète et en lecture seule. `barrier` est OBLIGATOIRE (aucune valeur par défaut) : `True` ajoute, APRÈS la lecture, la barrière de répertoire sur
    `admissions/` (23.10 étape 1) ; un échec de barrière est `BARRIER_FAILED`. Lève `RegistryReadError` (disque) ou `RegistryChainError` (chaîne incohérente) ; jamais de repli."""
    if type(barrier) is not bool:
        raise TypeError("barrier doit être un bool explicite.")
    path = _root_path(root)
    if ".." in path.parts:
        _fail(ReadFailure.ROOT_UNUSABLE, "composante '..' interdite dans la racine.")
    _require_real_directory(path, "racine du registre")
    names = {}
    for name, info in _directory_entries(path, "racine du registre"):
        if name in (IDENTITY_FILE, ADMISSIONS_DIR) or _tolerated_orphan(name, info):
            names[name] = info
        else:
            _fail(ReadFailure.UNKNOWN_ENTRY, f"entrée inconnue à la racine du registre : {name!r}.")
    if ADMISSIONS_DIR in names:
        _require_real_directory(path / ADMISSIONS_DIR, "admissions/")
    identity = _read_identity(path)
    if ADMISSIONS_DIR not in names:
        _fail(ReadFailure.ROOT_UNUSABLE, "le répertoire admissions/ est absent.")
    admissions = path / ADMISSIONS_DIR
    records = [_read_record(admissions, seq) for seq in _slot_sequence(admissions)]
    chain = verify_chain(records, registry_id=identity.registry_id, genesis_instance_id=identity.instance_id)
    if barrier:
        try:
            directory_read_barrier(admissions, durability=identity.durability_profile)
        except (OSError, LinkPublicationError) as error:
            raise RegistryReadError(ReadFailure.BARRIER_FAILED, f"barrière de lecture en échec : {error}") from error
    return RegistrySnapshot(root=path, identity=identity, chain=chain)


def initialize_synthetic_registry(root: object, *, registry_id: str, instance_id: str, durability: DurabilityProfile) -> RegistryIdentity:
    """Crée un registre `SYNTHETIC` NEUF (jamais sur une racine existante, jamais d'écrasement) : répertoire, `admissions/`, puis `identity.json` publié par la primitive E3-C.
    Les répertoires créés sont rendus durables (barrière du parent, E3-C § durabilité du répertoire). Un échec en cours de route laisse une racine incomplète que
    `read_registry` REFUSE (`IDENTITY_MISSING`) : aucune réparation silencieuse. Le mode `REAL` n'existe pas ici (DÉSACTIVÉ)."""
    registry_id, instance_id = validate_registry_id(registry_id), validate_instance_id(instance_id)
    genesis_prev_content_hash(instance_id)
    if type(durability) is not DurabilityProfile:
        raise ValueError("durability doit être un DurabilityProfile.")
    path = _root_path(root)
    if ".." in path.parts:
        raise ValueError("composante '..' interdite dans la racine.")
    parent = path.parent
    directory_read_barrier(parent, durability=durability)        # PRÉFLIGHT : plateforme, parent existant et durabilisable AVANT tout mkdir (aucun résidu sur échec)
    try:
        os.mkdir(path)
    except FileExistsError:
        _fail(ReadFailure.ROOT_EXISTS, f"{path} existe déjà : un registre existant n'est jamais réinitialisé.")
    except OSError as error:
        _fail(ReadFailure.ROOT_UNUSABLE, f"création de la racine impossible ({error}).")
    os.mkdir(path / ADMISSIONS_DIR)
    directory_read_barrier(parent, durability=durability)        # l'entrée de la racine dans son parent
    directory_read_barrier(path, durability=durability)          # l'entrée de admissions/ dans la racine
    identity = {"registry_identity_version": IDENTITY_VERSION, "registry_id": registry_id, "instance_id": instance_id,
                "mode": RegistryMode.SYNTHETIC.value, "durability_profile": durability.value}
    publish_json_by_link(path / IDENTITY_FILE, identity, durability=durability, naming=TempNaming.REGISTRY, kind="identité du registre")
    return RegistryIdentity(registry_id=registry_id, instance_id=instance_id, mode=RegistryMode.SYNTHETIC, durability_profile=durability)
