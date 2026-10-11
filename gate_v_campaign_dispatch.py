"""
gate_v_campaign_dispatch.py — discrimination V1/V2 d'un dossier de campagne GATE V (AF-V-07 Slice D6, ADR 0025
Décision 21.9 / 21.11).

`classify_gate_v_campaign_dir(campaign_dir) -> "v1" | "v2"` répond UNE seule question : de quelle VERSION de format
est ce dossier ? Elle lit au plus `plan.json` puis `manifest.json` (deux chemins canoniques connus, jamais un
inventaire du dossier) et ne regarde que quelques clés JSON. « dispatch » signifie ici DISCRIMINATION DE VERSION, pas
exécution : ce module ne valide rien scientifiquement, ne charge aucune preuve, n'exécute rien, ne prend aucun verrou
et n'accorde aucun droit FINAL_HOLDOUT. « v2 » n'implique ni robuste, ni complet, ni éligible. Les chargeurs stricts
V1/V2 — que l'appelant choisit ensuite — font les validations correspondantes.

Indépendance volontaire : stdlib uniquement, aucun module scientifique importé (ni `gate_v_campaign`, ni Plan/Manifest
V2). Les deux littéraux sémantiques V2 et les formes d'identifiant sont dupliqués ici ; des tests les comparent aux
constantes publiques V2 pour détecter toute dérive, sans dépendance à l'exécution.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

__all__ = ["GateVCampaignDiscriminationError", "classify_gate_v_campaign_dir"]

_PLAN_FILE = "plan.json"
_MANIFEST_FILE = "manifest.json"
_PLAN_VERSION_KEY = "campaign_plan_semantics_version"
_MANIFEST_VERSION_KEY = "manifest_semantics_version"
_PLAN_V2_SEMANTICS_VERSION = "gate_v_campaign_plan_v2"
_MANIFEST_V2_SEMANTICS_VERSION = "gate_v_campaign_manifest_v2"
# Formes EXACTES (fullmatch) : le segment `v2_` n'est pas hexadécimal, les deux espaces d'identifiants sont disjoints.
_CAMPAIGN_ID_FORMS = {
    "v1": re.compile(r"gate_v_[0-9a-f]{64}"),
    "v2": re.compile(r"gate_v_v2_[0-9a-f]{64}"),
}


class GateVCampaignDiscriminationError(ValueError):
    """Dossier de campagne impossible, ambigu ou malformé : version non discriminable. Jamais de repli."""


def _read_json_object(path: Path, label: str, *, absent_ok: bool = False):
    """Objet JSON lu à `path`. `absent_ok` : seul un fichier RÉELLEMENT introuvable (`FileNotFoundError`) retourne
    `None` ; un fichier présent mais illisible, vide, tronqué, non objet ou un dossier à ce chemin lève toujours."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        if absent_ok:
            return None
        raise GateVCampaignDiscriminationError(f"{label} absent : {path}") from error
    except (OSError, ValueError, RecursionError) as error:  # illisible, non UTF-8, JSON invalide ou trop profond
        raise GateVCampaignDiscriminationError(f"{label} illisible ou JSON invalide : {path}") from error
    if not isinstance(data, dict):
        raise GateVCampaignDiscriminationError(f"{label} doit être un objet JSON : {path}")
    return data


def classify_gate_v_campaign_dir(campaign_dir) -> str:
    """Retourne `"v1"` ou `"v2"` selon l'algorithme exact de l'ADR 0025 §21.9 ; lève
    `GateVCampaignDiscriminationError` pour tout autre état. Lecture seule."""
    if not isinstance(campaign_dir, (str, Path)) or not str(campaign_dir).strip():
        raise GateVCampaignDiscriminationError("campaign_dir doit être un chemin non vide (str ou Path).")
    directory = Path(campaign_dir)
    plan = _read_json_object(directory / _PLAN_FILE, "plan.json")
    # Égalité à un `str` : aucun type JSON non-`str` (None, nombre, bool, liste, objet) ne peut lui être égal.
    if _PLAN_VERSION_KEY not in plan:
        plan_kind = "v1"
    elif plan[_PLAN_VERSION_KEY] == _PLAN_V2_SEMANTICS_VERSION:
        plan_kind = "v2"
    else:
        raise GateVCampaignDiscriminationError(
            f"{_PLAN_VERSION_KEY} inconnue : {plan[_PLAN_VERSION_KEY]!r} (clé absente = v1, "
            f"{_PLAN_V2_SEMANTICS_VERSION!r} = v2, toute autre valeur refusée sans repli).")
    campaign_id = plan.get("campaign_id")
    if not isinstance(campaign_id, str) or _CAMPAIGN_ID_FORMS[plan_kind].fullmatch(campaign_id) is None:
        raise GateVCampaignDiscriminationError(
            f"campaign_id du plan absent ou de forme invalide pour un plan {plan_kind} : {campaign_id!r}.")
    if directory.name != campaign_id:
        raise GateVCampaignDiscriminationError(
            f"Le nom du dossier {directory.name!r} diffère de l'identifiant du plan {campaign_id!r} "
            "(contrôle de cohérence APRÈS discrimination par le contenu).")
    manifest = _read_json_object(directory / _MANIFEST_FILE, "manifest.json", absent_ok=True)
    if manifest is None:  # le Plan peut être persisté avant le Manifest : absence réelle = état normal
        return plan_kind
    if _MANIFEST_VERSION_KEY not in manifest:
        manifest_kind = "v1"
    elif manifest[_MANIFEST_VERSION_KEY] == _MANIFEST_V2_SEMANTICS_VERSION:
        manifest_kind = "v2"
    else:
        raise GateVCampaignDiscriminationError(
            f"{_MANIFEST_VERSION_KEY} inconnue : {manifest[_MANIFEST_VERSION_KEY]!r} (clé absente = v1, "
            f"{_MANIFEST_V2_SEMANTICS_VERSION!r} = v2, toute autre valeur refusée sans repli).")
    if manifest_kind != plan_kind:
        raise GateVCampaignDiscriminationError(
            f"État hybride : plan {plan_kind} mais manifest {manifest_kind} (aucune préférence, aucun repli).")
    if manifest.get("campaign_id") != campaign_id:  # un `str` seul peut égaler le `str` du plan ; pas de recalcul
        raise GateVCampaignDiscriminationError(
            f"campaign_id du manifest absent ou différent de celui du plan {campaign_id!r} : "
            f"{manifest.get('campaign_id')!r}.")
    return plan_kind
