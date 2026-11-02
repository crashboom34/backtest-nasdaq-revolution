"""
gate_v_k1s2_observations.py — K1 Étape 2, lot L3-A : conversion PURE d'un `ExposureScan` de B2 (table fermée de B3 v5-A, disposition CAMPAIGN_DIR) en
`ObservedRunTree` pour `gate_v_k1s2_verifier`.

Frontière : ce module ne lit PAS le disque et ne rescanne rien. Il traduit les faits qu'un scan déjà exécuté a consignés (nature, classe, anomalie, taille,
SHA-256 des octets bruts, octets conservés des JSON acceptés). Le futur adaptateur d'audit (E3-J) devra lui-même exécuter le scan sur une racine d'audit
configurée, vérifier qu'il n'a pas été produit avec des hooks, puis appeler cette conversion : un `ExposureScan` fabriqué à la main reste une limite
documentée de B2 (jamais une preuve de lecture indépendante). Aucune préimage n'est recalculée ici ; aucun verdict n'existe.
"""

from __future__ import annotations

import re
from typing import Optional

import gate_v_k1s2_verifier as vf
from gate_v_exposure_scan import EntryClass, EntryKind, ExposureScan, ScanObservation

__all__ = ["observed_item_from_scan", "observed_tree_from_scan"]

_SEPARATORS = re.compile(r"[\\/]+")
_MANIFEST = "manifest.json"          # déclaration de la campagne : octets conservés pour le diagnostic des répertoires vides


def _refuse(message: str):
    raise vf.ObservationRefused(vf.ObservationRefusal.BAD_TREE, message)


def _under(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory + "/")


def observed_item_from_scan(observation: ScanObservation, run_dir: Optional[str] = None) -> vf.ObservedItem:
    """Traduit UNE observation de B2, sans en perdre aucune : un fichier propre sans SHA-256 (classe inerte, constatée par son nom) devient `INERT` — présent, jamais
    « vérifié » ; le vérificateur le refuse dans `walk_forward/**` et dans le dossier du run. Les octets ne sont conservés que sous `run_dir` (preuves JSON acceptées
    et ValidationRun) et pour le `manifest.json` racine, et seulement s'ils tiennent dans `MAX_CONTENT_BYTES`."""
    if type(observation) is not ScanObservation:
        _refuse("observation de scan attendue")
    path, kind = observation.relative_path, vf.ObservedKind
    if observation.entry_class is None:
        return vf.ObservedItem(path, kind.UNKNOWN, anomaly=observation.anomaly.value)
    if observation.anomaly is not None:
        return vf.ObservedItem(path, kind.ANOMALY, anomaly=observation.anomaly.value)
    if observation.entry_class is EntryClass.TEMP_ORPHAN_FILE:
        return vf.ObservedItem(path, kind.ORPHAN)
    if observation.kind is EntryKind.DIRECTORY:
        return vf.ObservedItem(path, kind.DIRECTORY)
    if observation.content_hash is None or observation.size is None:
        return vf.ObservedItem(path, kind.INERT)
    kept = (run_dir is not None and _under(path, run_dir)) or path == _MANIFEST
    retained = observation.content_bytes if kept and observation.value_parsed and len(observation.content_bytes) <= vf.MAX_CONTENT_BYTES else None
    return vf.ObservedItem(path, kind.FILE, size=observation.size, sha256=observation.content_hash, content=retained)


def observed_tree_from_scan(scan: ExposureScan, *, root_label: str, campaign_dir_name: str) -> vf.ObservedRunTree:
    """Observations de la racine `root_label` d'un scan produit sous la table FERMÉE de B3 v5-A (digest CAMPAIGN_DIR vérifié, scan sans hooks). Refus typé
    (`ObservationRefused`, BAD_TREE) pour un scan d'une autre table, un scan à hooks, une racine absente ou ambiguë, ou une racine dont le dernier segment n'est pas
    `campaign_dir_name`."""
    if type(scan) is not ExposureScan:
        _refuse("ExposureScan attendu")
    if type(root_label) is not str or type(campaign_dir_name) is not str:
        _refuse("root_label et campaign_dir_name doivent être des textes")
    if scan.rules_digest != vf.TABLE_DIGEST:
        _refuse("le scan n'a pas été produit sous la table fermée de B3 v5-A (CAMPAIGN_DIR)")
    if scan.hooks_used:
        _refuse("un scan produit avec des hooks n'a aucune autorité")
    roots = [root for root in scan.roots if root.label == root_label]
    if len(roots) != 1:
        _refuse("la racine demandée doit exister exactement une fois dans le scan")
    segments = [part for part in _SEPARATORS.split(roots[0].path) if part]
    if not segments or segments[-1] != campaign_dir_name:
        _refuse("le dossier racine du scan n'est pas le dossier de campagne annoncé")
    run_dir = f"validations/{campaign_dir_name}_walk_forward"
    items = [observed_item_from_scan(observation, run_dir) for observation in scan.observations if observation.root_label == root_label]
    return vf.ObservedRunTree(campaign_dir_name, vf.TABLE_VERSION, vf.TABLE_DIGEST, tuple(sorted(items, key=lambda item: item.path)))
