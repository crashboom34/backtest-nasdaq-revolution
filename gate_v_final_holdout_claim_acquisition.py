"""Acquisition exclusive et durable du FinalHoldoutAccessClaim — AF-V-07 Slice E2 (ADR 0025, Décisions 9, 10, 11
et 22.5 à 22.11).

Ce module CONSOMME de façon irréversible le droit scientifique d'accéder une fois au FINAL_HOLDOUT d'une campagne
(création exclusive du fichier `final_holdout_access_claim.json`, Décision 9). Il n'accède lui-même à AUCUNE donnée
de marché, n'appelle ni le moteur ni la validation OOS, ne crée aucun événement d'accès et ne modifie ni le Plan V2,
ni le Manifest, ni les preuves : ces responsabilités relèvent de la future Slice E3.

**Aucune exception levée ici n'autorise un accès au marché.** Le Claim existe SEULEMENT si `acquire_...` retourne.

Frontière de confiance (22.5) : aucune source métier n'est acceptée en mémoire. Tout est rechargé depuis des CHEMINS
persistés par les chargeurs stricts existants, puis recoupé par `validate_gate_v_campaign_plan_v2_sources` ; la
préenregistrement doit être le fichier canonique `<gate_v>/preregistrations/<scope_key>.json`, frère de
`<gate_v>/campaigns/`. Un objet en mémoire cohérent ne prouve pas sa provenance persistée.

Séquence (22.6), la création n'ayant lieu qu'à l'étape 7 — chaque erreur des étapes 1 à 6 laisse le disque intact :
    1-4  plan persisté, préenregistrement ancrée, autres sources, validation croisée aux sources et Git historique
    5    `assert_gate_v_pre_holdout_evidence_complete` : l'UNIQUE prédicat de complétude (Décision 21.7)
    6    `created_at` (horloge UTC lue UNE fois si absent) puis Claim construit par E1
    7    création exclusive durable, SANS test d'existence préalable ; `FileExistsError` = déjà consommé
    8    relecture stricte, liaison au plan, égalité avec le record voulu
    8bis seconde vérification D5, Manifest strictement égal à celui d'avant
Toute erreur des étapes 8 et 8bis est `FinalHoldoutClaimPostAcquisitionError` : le Claim reste consommé.

`FinalHoldoutClaimAlreadyConsumedError` correspond EXCLUSIVEMENT au refus d'`O_EXCL` du chemin du Claim ; une erreur
survenue avant cette tentative (parent qui n'est pas un répertoire, sonde du répertoire, encodage) n'est jamais lue
comme « consommé » et ne crée rien. Limite constatée sous Windows : `O_EXCL` suit un lien symbolique ORPHELIN et crée
sa cible (POSIX le refuse avec EEXIST) ; le contrat interdisant tout contrôle avant `O_EXCL`, un lien au chemin du
Claim est détecté APRÈS coup par la relecture (`lstat`) et signalé en `PostAcquisitionError`, jamais retourné.
Cette détection ne concerne que ce cas (lien orphelin, Windows) : tout autre lien est refusé par `O_EXCL` lui-même
(`AlreadyConsumed`). Sous Windows, un répertoire, une jonction ou un lien de répertoire au chemin du Claim donne un
`PermissionError` BRUT : rien n'a été créé ni retourné, ce n'est ni « consommé » ni un échec post-acquisition (une
permission refusée peut avoir d'autres causes) — jamais de nouvelle tentative sans décision humaine. Les répertoires
intermédiaires éventuellement créés par `mkdir` ne sont pas synchronisés (le dossier de campagne existe déjà).

Une interruption (`KeyboardInterrupt`, autre `BaseException`) survenant après la création n'est PAS rangée en
`FinalHoldoutClaimPostAcquisitionError` : elle se propage telle quelle, le Claim restant consommé et aucun accès
au marché ne suivant. Jamais de suppression, de renommage, de réparation ni de nouvelle tentative automatique d'un
Claim. Limites de
durabilité (Windows, POSIX, volume OCI) : voir `atomic_json_store.save_exclusive`. Garantie d'exclusivité : celle de
`O_CREAT|O_EXCL` sur un système de fichiers local qualifié — jamais NFS/SMB/object-store (Décision 9).
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from atomic_json_store import ExclusiveCreationIncompleteError, save_exclusive
from dataset_split import load_dataset_split_plan
from gate_v_campaign_manifest_v2 import assert_gate_v_pre_holdout_evidence_complete
from gate_v_campaign_plan_v2 import (
    load_gate_v_campaign_plan_v2,
    validate_gate_v_campaign_plan_v2_sources,
    validate_gate_v_campaign_plan_v2_structure,
)
from gate_v_final_holdout_claim import (
    build_final_holdout_access_claim,
    final_holdout_access_claim_from_record,
    final_holdout_access_claim_to_record,
    validate_final_holdout_access_claim_against_plan,
)
from gate_v_preregistration import load_gate_v_preregistration
from gate_v_validation_policy import load_gate_v_validation_policy
from research_run import load_research_run

FINAL_HOLDOUT_ACCESS_CLAIM_FILE = "final_holdout_access_claim.json"

_PLAN_FILE = "plan.json"
_CAMPAIGNS_DIR = "campaigns"
_PREREGISTRATIONS_DIR = "preregistrations"
_KIND = "FinalHoldoutAccessClaim"


class FinalHoldoutClaimAlreadyConsumedError(FileExistsError):
    """Le chemin du Claim existe déjà (valide, vide, tronqué ou corrompu) : le droit est consommé pour toujours.
    Levée sans avoir lu, inspecté, modifié ni supprimé le fichier existant, sans nouvelle tentative."""


class FinalHoldoutClaimPostAcquisitionError(Exception):
    """Le Claim a été CRÉÉ par cet appel mais sa durabilité, sa relecture ou la revérification post-acquisition a
    échoué. Le fichier reste en place (consommé pour toujours) ; l'erreur d'origine est en `__cause__`.
    **Aucun accès au marché n'est autorisé.** Cette erreur n'est jamais un `FileExistsError`."""


def _path_argument(value: object, name: str) -> Path:
    """Chemin absolu normalisé. Jamais un objet métier, un booléen, un nombre, du vide : un argument invalide est
    refusé avant tout accès disque."""
    if isinstance(value, bool) or not isinstance(value, (str, os.PathLike)):
        raise ValueError(f"{name} doit être un chemin (str ou Path), jamais un objet en mémoire : {type(value).__name__}.")
    text = os.fspath(value)
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{name} doit être un chemin non vide.")
    return Path(os.path.abspath(text))


def _require_campaign_directory(directory: Path, plan) -> None:
    if directory.name != plan.campaign_id:
        raise ValueError("campaign_dir doit être le dossier <campaign_root>/<campaign_id> de ce plan.")


def _reject_duplicate_keys(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("FinalHoldoutAccessClaim : clé JSON dupliquée (le chargeur standard l'accepterait en silence).")
    return dict(pairs)


def _reject_non_finite_constant(name):
    raise ValueError(f"FinalHoldoutAccessClaim : constante JSON non finie {name!r} refusée.")


def _read_claim(path: Path, plan):
    """Lecture STRICTE et en lecture seule : octets UTF-8 stricts, JSON sans clé dupliquée ni constante non finie,
    14 clés exactes (E1), hashes recalculés, puis liaison au plan. Jamais de réparation, jamais de `None`."""
    try:
        info = os.lstat(path)  # le chemin lui-même, sans suivre de lien : FileNotFoundError = réellement absent
    except FileNotFoundError:
        raise
    except OSError as error:
        raise ValueError(f"FinalHoldoutAccessClaim illisible à {path} : {error}") from error
    if stat.S_ISLNK(info.st_mode):
        # Un lien (orphelin ou non) n'est jamais un Claim : sous Windows `O_EXCL` suit un lien orphelin et crée sa
        # cible hors de la campagne. Détecté ici, après coup ; jamais suivi, jamais « absent », jamais « valide ».
        raise ValueError(f"FinalHoldoutAccessClaim : {path} est un lien symbolique — refusé, jamais suivi.")
    if not stat.S_ISREG(info.st_mode):  # répertoire, jonction, FIFO...: refusé AVANT toute lecture (aucun blocage)
        raise ValueError(f"FinalHoldoutAccessClaim : {path} n'est pas un fichier ordinaire — refusé.")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError(f"FinalHoldoutAccessClaim illisible à {path} : {error}") from error
    try:
        record = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_non_finite_constant,
        )
    except RecursionError as error:  # JSON hostilement imbriqué : le contrat du chargeur reste `ValueError`
        raise ValueError(f"FinalHoldoutAccessClaim : JSON trop profondément imbriqué à {path}") from error
    claim = final_holdout_access_claim_from_record(record)
    validate_final_holdout_access_claim_against_plan(claim, plan)
    return claim


def load_final_holdout_access_claim(plan, campaign_dir):
    """Chargeur d'AUDIT, lecture seule (22.7) : `FileNotFoundError` si le Claim est absent, `ValueError` s'il est
    illisible, mal formé, incohérent ou étranger à ce plan. Ne répare ni ne supprime rien et ne retourne jamais
    `None`. Un fichier présent mais invalide n'est JAMAIS traité comme absent."""
    validate_gate_v_campaign_plan_v2_structure(plan)
    directory = _path_argument(campaign_dir, "campaign_dir")
    _require_campaign_directory(directory, plan)
    return _read_claim(directory / FINAL_HOLDOUT_ACCESS_CLAIM_FILE, plan)


def _require_canonical_preregistration(directory: Path, preregistration_path: Path, preregistration) -> None:
    """22.5-2 : la préenregistrement fournie DOIT être le fichier persisté à son emplacement exclusif par scope,
    `<gate_v>/preregistrations/<scope_key>.json`, frère de `<gate_v>/campaigns/` (Décision 16)."""
    expected_name = f"{preregistration.scope_key}.json"
    if preregistration_path.name != expected_name:
        raise ValueError("Le fichier de préenregistrement doit être nommé <scope_key>.json (emplacement exclusif par scope).")
    if directory.parent.name != _CAMPAIGNS_DIR:
        raise ValueError("campaign_dir doit se trouver sous <gate_v>/campaigns/ (disposition canonique, Décision 16).")
    canonical = directory.parent.parent / _PREREGISTRATIONS_DIR / expected_name
    try:
        same_file = canonical.is_file() and os.path.samefile(canonical, preregistration_path)
    except OSError:
        same_file = False
    if not same_file:
        raise ValueError(
            "La préenregistrement fournie n'est pas le fichier canonique <gate_v>/preregistrations/<scope_key>.json "
            "de cette campagne : sa provenance persistée n'est pas prouvée."
        )


def acquire_final_holdout_access_claim(
    campaign_dir,
    *,
    preregistration_path,
    research_run_path,
    split_plan_path,
    policy_path,
    repo_dir=None,
    created_at=None,
):
    """Acquiert le Claim exclusif de la campagne (22.6). Retourne le Claim relu strictement depuis le disque, et
    UNIQUEMENT si les étapes 1 à 8bis ont toutes réussi.

    Erreurs SANS création (disque intact) : `ValueError` (dont `GitProvenanceError`), `OSError` (dont une
    permission refusée à l'ouverture), `FinalHoldoutClaimAlreadyConsumedError` (le chemin existait). Erreur AVEC
    création : `FinalHoldoutClaimPostAcquisitionError` (consommé). Dans tous les cas d'exception, aucun accès au
    marché n'est autorisé."""
    directory = _path_argument(campaign_dir, "campaign_dir")
    preregistration_file = _path_argument(preregistration_path, "preregistration_path")
    research_run_file = _path_argument(research_run_path, "research_run_path")
    split_plan_file = _path_argument(split_plan_path, "split_plan_path")
    policy_file = _path_argument(policy_path, "policy_path")
    repository = None if repo_dir is None else _path_argument(repo_dir, "repo_dir")

    # Étapes 1 à 4 : tout est rechargé depuis des chemins persistés (22.5).
    plan = load_gate_v_campaign_plan_v2(directory / _PLAN_FILE)
    _require_campaign_directory(directory, plan)
    preregistration = load_gate_v_preregistration(preregistration_file)
    _require_canonical_preregistration(directory, preregistration_file, preregistration)
    research_run = load_research_run(research_run_file)
    if research_run is None:
        raise ValueError(f"ResearchRun absent, illisible ou invalide : {research_run_file}")
    split_plan = load_dataset_split_plan(split_plan_file, strict=True)
    if split_plan is None:
        raise ValueError(f"DatasetSplitPlan absent, illisible ou invalide : {split_plan_file}")
    policy = load_gate_v_validation_policy(policy_file)
    validate_gate_v_campaign_plan_v2_sources(
        plan, preregistration=preregistration, research_run=research_run, split_plan=split_plan,
        policy=policy, policy_path=policy_file, repo_dir=repository,
    )

    # Étape 5 : l'unique prédicat de complétude des preuves persistées (Décision 21.7).
    manifest_before = assert_gate_v_pre_holdout_evidence_complete(plan, directory)

    # Étape 6 : horloge lue UNE seule fois, seulement si created_at n'est pas fourni ; Claim construit par E1.
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()
    claim = build_final_holdout_access_claim(plan, created_at=created_at)
    record = final_holdout_access_claim_to_record(claim)

    # Étape 7 : création exclusive durable. AUCUN test d'existence préalable ; FileExistsError = déjà consommé.
    claim_path = directory / FINAL_HOLDOUT_ACCESS_CLAIM_FILE
    try:
        save_exclusive(claim_path, record, kind=_KIND, durable=True)
    except ExclusiveCreationIncompleteError as error:
        raise FinalHoldoutClaimPostAcquisitionError(
            f"Le Claim a été créé à {claim_path} mais son écriture durable est incomplète : le droit est CONSOMMÉ, "
            "aucun accès au marché n'est autorisé."
        ) from error
    except FileExistsError as error:
        raise FinalHoldoutClaimAlreadyConsumedError(
            f"Un chemin de Claim existe déjà à {claim_path} : le droit d'accès à ce FINAL_HOLDOUT est consommé pour "
            "toujours (le fichier existant n'a pas été lu, aucune nouvelle tentative)."
        ) from error

    # Étapes 8 et 8bis : toute erreur ici laisse le Claim consommé et interdit tout accès au marché.
    try:
        stored = _read_claim(claim_path, plan)
        if final_holdout_access_claim_to_record(stored) != record:
            raise ValueError("Le Claim relu diffère du record voulu.")
        manifest_after = assert_gate_v_pre_holdout_evidence_complete(plan, directory)
        if manifest_after != manifest_before:
            raise ValueError("Le Manifest a changé pendant l'acquisition : instantané périmé.")
    except Exception as error:
        raise FinalHoldoutClaimPostAcquisitionError(
            f"Le Claim a été créé à {claim_path} mais sa vérification post-acquisition a échoué : {error} Le droit "
            "est CONSOMMÉ, aucun accès au marché n'est autorisé."
        ) from error
    return stored
