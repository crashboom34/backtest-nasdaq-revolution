"""
gate_v_audit_window.py — N-VIDE-2 / N2-b1a : provenance DÉCLARATIVE de la fenêtre W (module interne, lecture seule).

Question posée : la fenêtre W est-elle la frontière `final_holdout` du plan de split que le plan de campagne V2 référence, et les deux artefacts concordent-ils (campagne, identifiant
du plan de split, snapshot de jeu de données, empreinte RECALCULÉE) ? Réponse possible : cohérence de MÉTADONNÉES, jamais authenticité, chronologie, absence d'exposition ni droit
d'accès. Une falsification totalement auto-cohérente n'est pas détectable ici ; la revalidation contre les sources (Git, pré-enregistrement) reste hors de cette tranche.

Autorité : les OCTETS STRICTS observés par le premier scan. Le plan de split est reconstruit depuis ces octets (aucun chargeur tolérant, aucune horloge ; la reconstruction ne lit pas le disque, seuls les gardes et le chargeur du plan V2 le lisent, six lectures au plus). Le plan
de campagne V2 passe par son chargeur historique (validation de structure et barrières internes) ENCADRÉ par deux lectures gardées dont l'empreinte doit égaler celle de S1 ; ses champs
sont ensuite confrontés à l'enregistrement strict de S1. Après le second scan, une relecture gardée des deux fichiers doit redonner les empreintes de S1 : un changement APRÈS cette
relecture, ou un retour à l'identique entre deux lectures, reste indétectable (ce n'est ni un instantané atomique ni le rescan indépendant d'E3-J).

Ce module n'écrit rien, n'ouvre aucune donnée de marché, ne lance aucun sous-processus et n'accorde aucun droit : il rend un résultat typé ou lève `WindowSourceRefused`.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import os
import stat

from dataset_split import build_dataset_split_plan, build_split_boundary, dataset_split_plan_fingerprint
from gate_v_campaign_plan_v2 import load_gate_v_campaign_plan_v2
from gate_v_exposure_interpreters import TAG_SPLIT_PLAN, RootLayout
from gate_v_exposure_scan import EntryKind
from gate_v_exposure_sources import normalize_window

__all__ = ["DerivedWindow", "WindowFailure", "WindowSourceRefused", "derive_window", "plan_root_attributed", "recheck_sources"]

PLAN_FILE = "plan.json"
SPLIT_FILE = "split_plan.json"
_SPLIT_KEYS = frozenset({"split_plan_id", "dataset_snapshot_id", "train", "final_holdout", "validation", "discovery_oos", "created_at"})
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CHUNK = 1 << 16


class WindowFailure(str, enum.Enum):
    INVALID = "INVALID"                  # source absente, mal formée, non strictement observée, non canonique ou non lisible
    CONTRADICTION = "CONTRADICTION"      # les deux artefacts, lus correctement, ne concordent pas
    CHANGED = "CHANGED"                  # un fichier ne porte plus les octets observés par le premier scan


class WindowSourceRefused(Exception):
    def __init__(self, failure: WindowFailure, detail: str) -> None:
        super().__init__(f"{failure.value}: {detail}")
        self.failure = failure
        self.detail = detail


@dataclasses.dataclass(frozen=True)
class DerivedWindow:
    """Fenêtre `[start, end)` normalisée et identités dont elle dérive. Diagnostic : n'accorde rien."""

    window: tuple
    split_plan_id: str
    dataset_snapshot_id: str
    split_plan_fingerprint: str
    plan_sha256: str
    split_sha256: str


# ── Lecture gardée : même test structurel que le scanner, octets liés par empreinte ─────────────────────────────────────────────────────────────
class _GuardFailure(Exception):
    pass


def _is_link_or_reparse(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool((getattr(info, "st_file_attributes", 0) or 0) & _REPARSE_POINT)


def _guarded_sha256(root: str, name: str, max_bytes: int) -> str:
    """SHA-256 des octets de `<root>/<name>` : racine répertoire non lien, nom EXACT présent dans le listage, fichier régulier non lien, un seul lien physique, taille bornée,
    ouverture sans suivre de lien, même fichier avant et après ouverture, lecture complète. Tout écart est une `_GuardFailure`."""
    try:
        root_info = os.lstat(root)
        if _is_link_or_reparse(root_info) or not stat.S_ISDIR(root_info.st_mode):
            raise _GuardFailure("racine absente, lien ou point d'analyse")
        with os.scandir(root) as entries:
            if name not in {entry.name for entry in entries}:
                raise _GuardFailure(f"{name} absent du listage exact de la racine")
        path = os.path.join(root, name)
        info = os.lstat(path)
        if _is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
            raise _GuardFailure(f"{name} n'est pas un fichier régulier non lien")
        if info.st_nlink != 1:
            raise _GuardFailure(f"{name} a plusieurs liens physiques")
        if info.st_size > max_bytes:
            raise _GuardFailure(f"{name} dépasse {max_bytes} octets")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (info.st_ino and opened.st_ino and (info.st_ino, info.st_dev) != (opened.st_ino, opened.st_dev)):
                raise _GuardFailure(f"{name} a été remplacé pendant l'ouverture")
            digest, total = hashlib.sha256(), 0
            while True:
                chunk = os.read(descriptor, _CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise _GuardFailure(f"{name} dépasse {max_bytes} octets à la lecture")
                digest.update(chunk)
        finally:
            os.close(descriptor)
        if total != opened.st_size:
            raise _GuardFailure(f"{name} : lecture partielle ou fichier modifié pendant la lecture")
        return digest.hexdigest()
    except OSError as error:
        raise _GuardFailure(f"{name} illisible : {type(error).__name__}") from None


def _same_bytes(root: str, name: str, expected_sha256: str, max_bytes: int, *, on_guard_failure: WindowFailure) -> None:
    try:
        found = _guarded_sha256(root, name, max_bytes)
    except _GuardFailure as error:
        raise WindowSourceRefused(on_guard_failure, str(error)) from None
    if found != expected_sha256:
        raise WindowSourceRefused(WindowFailure.CHANGED, f"{name} ne porte plus les octets observés par le premier scan")


# ── Reconstruction depuis les octets stricts de S1 ──────────────────────────────────────────────────────────────────────────────────────────────
def _observed(interpretation, layout: RootLayout, label: str, name: str):
    found = [o for item in interpretation.scans if item.layout is layout for o in item.scan.observations if o.root_label == label and o.relative_path == name]
    if len(found) != 1:
        raise WindowSourceRefused(WindowFailure.INVALID, f"{label}/{name} : {len(found)} observation(s) du premier scan, une seule attendue")
    observation = found[0]
    if observation.kind is not EntryKind.FILE or observation.anomaly is not None or not observation.value_parsed or observation.content_hash is None:
        raise WindowSourceRefused(WindowFailure.INVALID, f"{label}/{name} : non lu ou refusé par le scanner strict")
    record = observation.value
    if type(record) is not dict:
        raise WindowSourceRefused(WindowFailure.INVALID, f"{label}/{name} : objet JSON attendu")
    return observation, record


def _boundary(raw, *, required: bool):
    if raw is None and not required:
        return None
    if type(raw) is not dict or set(raw) != {"start", "end"}:
        raise WindowSourceRefused(WindowFailure.INVALID, "borne de split mal formée")
    return build_split_boundary(raw["start"], raw["end"])


def _split_from_record(record: dict):
    """Équivalent STRICT du chargeur historique, sans disque : sept clés exactes, textes non vides (aucune valeur par défaut tirée de l'horloge), bornes validées, forme canonique."""
    if set(record) != _SPLIT_KEYS:
        raise WindowSourceRefused(WindowFailure.INVALID, "split plan : jeu de clés différent des sept clés attendues")
    for key in ("split_plan_id", "dataset_snapshot_id", "created_at"):
        if type(record[key]) is not str or not record[key]:
            raise WindowSourceRefused(WindowFailure.INVALID, f"split plan : {key} doit être un texte non vide")
    try:
        plan = build_dataset_split_plan(split_plan_id=record["split_plan_id"], dataset_snapshot_id=record["dataset_snapshot_id"], train=_boundary(record["train"], required=True),
                                        final_holdout=_boundary(record["final_holdout"], required=True), validation=_boundary(record["validation"], required=False),
                                        discovery_oos=_boundary(record["discovery_oos"], required=False), created_at=record["created_at"])
    except (TypeError, ValueError):
        raise WindowSourceRefused(WindowFailure.INVALID, "split plan refusé par la construction stricte") from None
    if dataclasses.asdict(plan) != record:
        raise WindowSourceRefused(WindowFailure.INVALID, "split plan non canonique")
    return plan


def derive_window(interpretation, *, own_label: str, split_label: str, own_root_path: str, split_root_path: str, own_campaign_id: str, max_json_bytes: int) -> DerivedWindow:
    """Dérive W depuis les octets de S1 (`interpretation`), puis confronte le plan de campagne V2 chargé. Lève `WindowSourceRefused` ; ne compare PAS W à la fenêtre de l'opérateur
    (le protocole la compare : jamais de remplacement silencieux)."""
    plan_observation, plan_record = _observed(interpretation, RootLayout.CAMPAIGN_DIR, own_label, PLAN_FILE)
    split_observation, split_record = _observed(interpretation, RootLayout.SPLIT_PLAN_DIR, split_label, SPLIT_FILE)
    split = _split_from_record(split_record)
    try:
        bounds = normalize_window(split.final_holdout.start, split.final_holdout.end)
    except (TypeError, ValueError):
        raise WindowSourceRefused(WindowFailure.INVALID, "bornes final_holdout non normalisables") from None
    fingerprint = dataset_split_plan_fingerprint(split)
    # Lecture indépendante de B3 : le plan de split doit aussi être indexé par lui, avec les mêmes identités, bornes et octets.
    expected_source_id = f"{TAG_SPLIT_PLAN}:{split_label}/{SPLIT_FILE}"          # l'entrée doit venir de la racine DÉSIGNÉE, pas d'une racine homonyme
    if not any(entry.source_id == expected_source_id and entry.content_hash == split_observation.content_hash and entry.split_plan_id == split.split_plan_id
               and entry.fingerprint == fingerprint
               and entry.dataset_snapshot_id == split.dataset_snapshot_id and (entry.final_holdout_start_utc, entry.final_holdout_end_utc) == bounds
               for entry in interpretation.plans):
        raise WindowSourceRefused(WindowFailure.INVALID, "le plan de split n'est pas indexé à l'identique par l'interpréteur")
    _same_bytes(split_root_path, SPLIT_FILE, split_observation.content_hash, max_json_bytes, on_guard_failure=WindowFailure.INVALID)
    plan_sha256 = plan_observation.content_hash
    _same_bytes(own_root_path, PLAN_FILE, plan_sha256, max_json_bytes, on_guard_failure=WindowFailure.INVALID)
    try:
        plan = load_gate_v_campaign_plan_v2(os.path.join(own_root_path, PLAN_FILE))
    except (OSError, ValueError, TypeError):                     # P5 : erreurs de DONNÉES seulement ; MemoryError, RecursionError et toute RuntimeError se propagent (refus `AUDIT_INTERNAL_FAILURE`)
        raise WindowSourceRefused(WindowFailure.INVALID, "plan de campagne V2 refusé par son chargeur historique") from None
    _same_bytes(own_root_path, PLAN_FILE, plan_sha256, max_json_bytes, on_guard_failure=WindowFailure.CHANGED)
    pairs = (("campaign_id", plan.campaign_id, own_campaign_id), ("split_plan_id", plan.split_plan_id, split.split_plan_id),
             ("dataset_snapshot_id", plan.dataset_snapshot_id, split.dataset_snapshot_id), ("split_plan_fingerprint", plan.split_plan_fingerprint, fingerprint))
    for name, loaded, expected in pairs:
        if loaded != expected:
            raise WindowSourceRefused(WindowFailure.CONTRADICTION, f"plan de campagne ≠ attendu : {name}")
        if plan_record.get(name) != loaded:
            raise WindowSourceRefused(WindowFailure.CONTRADICTION, f"le plan chargé diffère de l'enregistrement strict de S1 : {name}")
    return DerivedWindow(bounds, split.split_plan_id, split.dataset_snapshot_id, fingerprint, plan_sha256, split_observation.content_hash)


def recheck_sources(derived: DerivedWindow, *, own_root_path: str, split_root_path: str, max_json_bytes: int) -> None:
    """Relecture gardée finale (après le second scan) : les deux fichiers doivent redonner les empreintes de S1. Tout écart ou toute lecture impossible est `CHANGED`."""
    _same_bytes(own_root_path, PLAN_FILE, derived.plan_sha256, max_json_bytes, on_guard_failure=WindowFailure.CHANGED)
    _same_bytes(split_root_path, SPLIT_FILE, derived.split_sha256, max_json_bytes, on_guard_failure=WindowFailure.CHANGED)


def plan_root_attributed(interpretation, *, label: str, root_path: str, expected_name: str, max_json_bytes: int) -> bool:
    """N2-b1b : le plan V2 d'une racine de campagne porte-t-il le nom attendu ? Vrai seulement si le premier scan contient EXACTEMENT une observation propre et lue de `plan.json` pour cette
    racine (objet JSON), et si le chargeur historique du plan V2 (qui RECALCULE le `campaign_id` depuis le contenu), encadré par deux lectures gardées dont l'empreinte égale celle du premier
    scan, rend un plan dont l'identifiant égale `expected_name` et l'enregistrement strict du premier scan. Toute autre issue est `False` (jamais un refus) : la racine reste STATIQUE.
    Ce n'est PAS une preuve que le dossier contienne les données réelles de la campagne : un plan authentique recopié dans un dossier de même nom passerait. Fonction nouvelle ; aucune
    fonction de b1a n'est modifiée ni appelée à sa place. Limites dites sans détour : le chargeur historique lit SANS plafond (un fichier qui grossit entre les deux lectures gardées est lu
    en entier avant d'être rejeté par l'empreinte : risque de mémoire, non imposé) ; un retour à l'identique entre les deux lectures gardées (ABA) n'est pas détecté.
    P5 : une défaillance CRITIQUE (`MemoryError`, `RecursionError`, toute autre `RuntimeError`) n'est jamais lue comme « non attribuée » : elle se propage (refus typé du protocole)."""
    try:
        observation, record = _observed(interpretation, RootLayout.CAMPAIGN_DIR, label, PLAN_FILE)
        sha256 = observation.content_hash
        _same_bytes(root_path, PLAN_FILE, sha256, max_json_bytes, on_guard_failure=WindowFailure.INVALID)
        plan = load_gate_v_campaign_plan_v2(os.path.join(root_path, PLAN_FILE))
        _same_bytes(root_path, PLAN_FILE, sha256, max_json_bytes, on_guard_failure=WindowFailure.CHANGED)
    except (WindowSourceRefused, OSError, ValueError, TypeError):
        return False
    return plan.campaign_id == expected_name and record.get("campaign_id") == plan.campaign_id
