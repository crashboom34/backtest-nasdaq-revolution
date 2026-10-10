"""
gate_v_campaign_manifest_v2.py — GateVCampaignManifestV2 (AF-V-07 Slices D2-D4, ADR 0025 Décision 21.4/21.5/21.8).

Manifest de campagne Gate V V2 : type DISTINCT de `gate_v_campaign.GateVCampaignManifest` (V1, jamais
importé ni modifié ici). Il porte seulement des pointeurs et des marqueurs d'exécution ; il ne déclare
JAMAIS une phase « complète » et ne produit aucun verdict scientifique. Aucune horloge, aucun hasard.

Scope Slice D2 (PUR) : constantes, type à 17 champs, builder initial EN MÉMOIRE, validation structurelle,
liaison au `GateVCampaignPlanV2`, conversion record pure.

Scope Slice D3 (PUR) : statut posé par les marqueurs (`derive_…_marker_status`, sur la vue des SEULES preuves
RÉFÉRENCÉES par le Manifest, jugées par D1) et six commandes pures (`Start`, `SetRunning`, `AttachWalkForward`,
`AttachMonteCarlo`, `AttachParameterStability`, `MarkTechnicalFailure`) appliquées par une seule fonction qui exige
`expected_revision`, ajoute exactement 1 à la révision d'une vraie transition et rend le même Manifest pour une
commande idempotente. Les preuves sont des `ValidationRun` DÉJÀ chargées par l'appelant.

Scope Slice D4 (persistance, seule partie qui touche le disque) : création EXCLUSIVE du Manifest initial, chargeur
strict, mise à jour SOUS le verrou transitoire `manifest.update.lock` (`O_CREAT|O_EXCL`, séquence en 11 étapes,
rechargement et contrôle de révision sous verrou, transition toujours calculée par D3), sentinelle d'échec technique
`technical_failure.json` (fait exclusif indépendant du verrou) et statut effectif. Le dossier de campagne
`<campaign_root>/<campaign_id>/` est TOUJOURS fourni par l'appelant. Aucun nettoyage automatique de verrou (ni délai,
ni âge, ni PID) : la récupération manuelle gouvernée d'un verrou résiduel reste une procédure documentée (ADR).
Dépendance de déploiement : le chemin canonique d'une preuve Parameter Stability peut dépasser `MAX_PATH` (260) sous
Windows avec une racine usuelle ; les identifiants ne sont jamais raccourcis : le support des chemins longs est requis.

HORS scope (tranches suivantes) : vérification publique des preuves persistées et précondition du Claim (D5),
discrimination de dossier (D6), Claim et FINAL_HOLDOUT. Ni le verrou ni la sentinelle ne sont un Claim.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping, Optional

from atomic_json_store import load_json_tolerant, save_atomic_overwrite, save_exclusive, validate_portable_identifier
from gate_v_campaign_plan_v2 import (
    GATE_V_CAMPAIGN_ID_V2_PREFIX,
    GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION,
    GateVCampaignPlanV2,
    compute_gate_v_campaign_id_v2,
    load_gate_v_campaign_plan_v2,
    validate_gate_v_campaign_plan_v2_structure,
)
from gate_v_evidence_completeness_v2 import (
    evaluate_pre_holdout_evidence_v2,
    gate_v_v2_validation_run_id,
    validate_scoped_evidence_run_v2,
)
from validation_run import (
    VALIDATION_TYPE_MONTE_CARLO,
    VALIDATION_TYPE_PARAMETER_STABILITY,
    VALIDATION_TYPE_WALK_FORWARD,
    ValidationRun,
    load_validation_run,
)

__all__ = [
    "GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION",
    "GATE_V_CAMPAIGN_V2_STATUSES",
    "GateVCampaignManifestV2",
    "build_gate_v_campaign_manifest_v2",
    "validate_gate_v_campaign_manifest_v2_structure",
    "validate_gate_v_campaign_manifest_v2_against_plan",
    "gate_v_campaign_manifest_v2_to_record",
    "gate_v_campaign_manifest_v2_from_record",
    "derive_gate_v_campaign_v2_marker_status",
    "validate_gate_v_campaign_manifest_v2_marker_status",
    "apply_gate_v_campaign_manifest_v2_command",
    "ManifestTransitionError",
    "Start",
    "SetRunning",
    "AttachWalkForward",
    "AttachMonteCarlo",
    "AttachParameterStability",
    "MarkTechnicalFailure",
    "create_gate_v_campaign_manifest_v2",
    "load_gate_v_campaign_manifest_v2",
    "update_gate_v_campaign_manifest_v2",
    "derive_gate_v_campaign_v2_effective_status",
    "GATE_V_TECHNICAL_FAILURE_SENTINEL_SEMANTICS_VERSION",
    "GATE_V_TECHNICAL_FAILURE_SENTINEL_UNREADABLE_REASON",
    "ManifestLockAcquisitionError",
    "ManifestWriteError",
    "ManifestWriteUncertainError",
    "ManifestLockReleaseError",
]

GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION = "gate_v_campaign_manifest_v2"

# Ensemble exact et factuel (ADR 0025 Décision 21.5) : jamais PASS/FAIL/Champion/verdict.
GATE_V_CAMPAIGN_V2_STATUSES = frozenset({
    "READY_FOR_EXECUTION",
    "RUNNING",
    "EVIDENCE_INCOMPLETE",
    "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT",
    "TECHNICAL_FAILURE",
})

_INITIAL_STATUS = "READY_FOR_EXECUTION"
_EVIDENCE_COMPLETE_STATUS = "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT"
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")
_CAMPAIGN_ID_V2_RE = re.compile(re.escape(GATE_V_CAMPAIGN_ID_V2_PREFIX) + r"[0-9a-f]{64}")
# Champs 13-17 : réservés, valeur imposée None tant qu'aucun Claim n'est implémenté (Décision 21.4).
_RESERVED_FIELDS = (
    "final_holdout_claim_id",
    "final_holdout_claim_content_hash",
    "holdout_access_event_id",
    "holdout_access_event_content_hash",
    "oos_evidence_validation_run_id",
)


class _FrozenDict(dict):
    """Copie immuable, compatible JSON, du mapping Parameter Stability (fold_id -> id de preuve).
    Duplication volontaire du helper de `gate_v_campaign_plan_v2` (privé, jamais importé entre modules)."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("Le mapping Parameter Stability d'un Manifest V2 est immuable.")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        return (_FrozenDict, (dict(self),))


@dataclass(frozen=True)
class GateVCampaignManifestV2:
    """Pointeurs et marqueurs d'exécution d'une campagne V2 (ADR 0025 Décision 21.4) — EXACTEMENT 17
    champs, aucun timestamp, aucun chemin, aucun verdict. Les champs 13-17 sont RÉSERVÉS : leur valeur est
    imposée `None` (aucun Claim n'existe en Slice D). Construire via `build_gate_v_campaign_manifest_v2()` ;
    le constructeur direct ne revalide rien (comme `GateVCampaignPlanV2`), il copie seulement le mapping
    Parameter Stability dans une structure immuable."""

    # Identité / liaison — immuables
    manifest_semantics_version: str
    campaign_id: str
    preregistration_id: str
    campaign_protocol_fingerprint: str
    # État de progression
    manifest_revision: int
    status: str
    execution_started: bool
    running: bool
    technical_failure_reason: Optional[str]
    walk_forward_validation_run_id: Optional[str]
    monte_carlo_validation_run_id: Optional[str]
    parameter_stability_validation_run_ids_by_fold: Mapping[str, str]
    # Réservés (valeur imposée None en Slice D)
    final_holdout_claim_id: Optional[str]
    final_holdout_claim_content_hash: Optional[str]
    holdout_access_event_id: Optional[str]
    holdout_access_event_content_hash: Optional[str]
    oos_evidence_validation_run_id: Optional[str]

    def __post_init__(self):
        mapping = self.parameter_stability_validation_run_ids_by_fold
        if isinstance(mapping, Mapping):
            object.__setattr__(self, "parameter_stability_validation_run_ids_by_fold", _FrozenDict(mapping))


def build_gate_v_campaign_manifest_v2(plan: GateVCampaignPlanV2) -> GateVCampaignManifestV2:
    """État initial, en mémoire, d'une campagne V2 : non démarrée, aucune preuve référencée."""
    validate_gate_v_campaign_plan_v2_structure(plan)
    return GateVCampaignManifestV2(
        manifest_semantics_version=GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION,
        campaign_id=plan.campaign_id,
        preregistration_id=plan.preregistration_id,
        campaign_protocol_fingerprint=plan.campaign_protocol_fingerprint,
        manifest_revision=0,
        status=_INITIAL_STATUS,
        execution_started=False,
        running=False,
        technical_failure_reason=None,
        walk_forward_validation_run_id=None,
        monte_carlo_validation_run_id=None,
        parameter_stability_validation_run_ids_by_fold={},
        final_holdout_claim_id=None,
        final_holdout_claim_content_hash=None,
        holdout_access_event_id=None,
        holdout_access_event_content_hash=None,
        oos_evidence_validation_run_id=None,
    )


# ---------------------------------------------------------------------------------------------
# Validation structurelle PURE (aucune E/S, aucune preuve lue, aucun plan nécessaire)
# ---------------------------------------------------------------------------------------------


def _is_non_empty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_hex64(value, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256_HEX_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} doit être un SHA-256 hexadécimal minuscule de 64 caractères.")


def _require_deterministic_proof_id(value, expected: str, field_name: str) -> None:
    """Identifiant de preuve == chaîne déterministe de la campagne (ADR 0025 §21.6) ET identifiant portable.
    Contrôle STRUCTUREL interne : l'autorité canonique reste `gate_v_v2_validation_run_id()` (D1), utilisée par
    `validate_..._against_plan()` ; ce n'est pas une seconde API."""
    if value != expected:
        raise ValueError(f"{field_name} doit être l'identifiant déterministe de la campagne : {expected!r}.")
    validate_portable_identifier(value, field_name)


def _statuses_compatible_with_markers(manifest: GateVCampaignManifestV2) -> frozenset:
    """Statuts que les SEULS marqueurs d'exécution autorisent (condition nécessaire, sans preuve). Ne choisit
    jamais entre les deux statuts de preuve : cette dérivation, qui lit les preuves, n'est pas de ce module."""
    if manifest.technical_failure_reason is not None:
        return frozenset({"TECHNICAL_FAILURE"})
    if manifest.running:
        return frozenset({"RUNNING"})
    if not manifest.execution_started:
        return frozenset({_INITIAL_STATUS})
    return frozenset({"EVIDENCE_INCOMPLETE", _EVIDENCE_COMPLETE_STATUS})


def validate_gate_v_campaign_manifest_v2_structure(manifest: GateVCampaignManifestV2) -> None:
    """Validation PURE d'un Manifest V2 : types et formats des 17 champs, `campaign_id` recalculé par la
    fonction canonique de la Slice C, implications entre marqueurs et références, champs réservés `None`,
    statut compatible avec les marqueurs. Ne lit aucune preuve, aucun fichier ; la liaison à un plan précis
    (identifiants déterministes, folds attendus) relève de `validate_..._against_plan()`."""
    if not isinstance(manifest, GateVCampaignManifestV2):
        raise ValueError("manifest doit être un GateVCampaignManifestV2.")
    if manifest.manifest_semantics_version != GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION:
        raise ValueError(
            "manifest_semantics_version inconnue : attendu "
            f"{GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION!r}, reçu {manifest.manifest_semantics_version!r}."
        )
    if not isinstance(manifest.campaign_id, str) or _CAMPAIGN_ID_V2_RE.fullmatch(manifest.campaign_id) is None:
        raise ValueError("campaign_id doit avoir la forme 'gate_v_v2_' + 64 hexadécimaux minuscules.")
    _require_hex64(manifest.preregistration_id, "preregistration_id")
    _require_hex64(manifest.campaign_protocol_fingerprint, "campaign_protocol_fingerprint")
    recomputed = compute_gate_v_campaign_id_v2(
        campaign_plan_semantics_version=GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION,
        preregistration_id=manifest.preregistration_id,
        campaign_protocol_fingerprint=manifest.campaign_protocol_fingerprint,
    )
    if manifest.campaign_id != recomputed:
        raise ValueError("campaign_id différent du campaign_id recalculé (preregistration_id, empreinte).")
    revision = manifest.manifest_revision
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("manifest_revision doit être un entier non booléen >= 0.")
    if not isinstance(manifest.status, str) or manifest.status not in GATE_V_CAMPAIGN_V2_STATUSES:
        raise ValueError(f"Statut de campagne V2 inconnu : {manifest.status!r}.")
    if not isinstance(manifest.execution_started, bool) or not isinstance(manifest.running, bool):
        raise ValueError("execution_started et running doivent être booléens.")
    reason = manifest.technical_failure_reason
    if reason is not None and not _is_non_empty_str(reason):
        raise ValueError("technical_failure_reason doit être None ou une chaîne non vide.")
    for field_name in ("walk_forward_validation_run_id", "monte_carlo_validation_run_id"):
        value = getattr(manifest, field_name)
        if value is not None and not _is_non_empty_str(value):
            raise ValueError(f"{field_name} doit être None ou une chaîne non vide.")
    by_fold = manifest.parameter_stability_validation_run_ids_by_fold
    if not isinstance(by_fold, dict) or any(
        not _is_non_empty_str(fold_id) or not _is_non_empty_str(run_id) for fold_id, run_id in by_fold.items()
    ):
        raise ValueError("Le mapping Parameter Stability doit associer des fold_id non vides à des ids non vides.")
    # Identifiants de preuve DÉTERMINISTES dès la structure (le membership de `expected_fold_ids` reste à
    # `validate_..._against_plan()`, qui seul connaît le plan).
    if manifest.walk_forward_validation_run_id is not None:
        _require_deterministic_proof_id(
            manifest.walk_forward_validation_run_id, f"{manifest.campaign_id}_{VALIDATION_TYPE_WALK_FORWARD}",
            "walk_forward_validation_run_id",
        )
    if manifest.monte_carlo_validation_run_id is not None:
        _require_deterministic_proof_id(
            manifest.monte_carlo_validation_run_id, f"{manifest.campaign_id}_{VALIDATION_TYPE_MONTE_CARLO}",
            "monte_carlo_validation_run_id",
        )
    for fold_id, run_id in by_fold.items():
        # Contrat portable CANONIQUE, sans longueur maximale : D2 n'est pas plus strict que ce contrat, que
        # le Plan V2 ou D1. La longueur des chemins matérialisés relève de D4.
        validate_portable_identifier(fold_id, "fold_id Parameter Stability")
        _require_deterministic_proof_id(
            run_id, f"{manifest.campaign_id}_{VALIDATION_TYPE_PARAMETER_STABILITY}_{fold_id}",
            "parameter_stability_validation_run_ids_by_fold",
        )
    for field_name in _RESERVED_FIELDS:
        if getattr(manifest, field_name) is not None:
            raise ValueError(
                f"{field_name} est réservé : acquisition du claim non implémentée, valeur imposée None."
            )
    started, running = manifest.execution_started, manifest.running
    if running and not started:
        raise ValueError("Un manifeste RUNNING doit avoir démarré l'exécution.")
    if reason is not None and (not started or running):
        raise ValueError("technical_failure_reason exige une exécution démarrée et non en cours.")
    wf_id, mc_id = manifest.walk_forward_validation_run_id, manifest.monte_carlo_validation_run_id
    if (wf_id is not None or mc_id is not None or by_fold) and not started:
        raise ValueError("Une preuve interne ne peut pas précéder le démarrage de la campagne.")
    if wf_id is None and (mc_id is not None or by_fold):
        raise ValueError("Monte-Carlo et Parameter Stability exigent une preuve source Walk-Forward.")
    if manifest.status not in _statuses_compatible_with_markers(manifest):
        raise ValueError("Le statut du manifeste contredit ses marqueurs d'exécution.")
    if manifest.status == _EVIDENCE_COMPLETE_STATUS and (wf_id is None or mc_id is None or not by_fold):
        raise ValueError("Un manifeste complet doit référencer Walk-Forward, Monte-Carlo et Parameter Stability.")


def validate_gate_v_campaign_manifest_v2_against_plan(
    manifest: GateVCampaignManifestV2, plan: GateVCampaignPlanV2,
) -> None:
    """Liaison PURE d'un Manifest V2 à SON `GateVCampaignPlanV2` : revalide la structure des deux objets,
    exige l'identité (campagne, pré-enregistrement, empreinte) égale à celle du plan, et chaque identifiant
    de preuve égal à l'identifiant déterministe de la Décision 21.6 (fonction de D1, jamais redéfinie ici) ;
    toute entrée Parameter Stability doit viser un fold attendu. Un manifeste « complet » doit couvrir TOUS
    les folds attendus. Ne lit aucune preuve : le jugement de complétude relève des tranches suivantes."""
    if not isinstance(plan, GateVCampaignPlanV2):
        raise ValueError("plan doit être un GateVCampaignPlanV2 validé.")
    if not isinstance(manifest, GateVCampaignManifestV2):
        raise ValueError("manifest doit être un GateVCampaignManifestV2.")
    validate_gate_v_campaign_plan_v2_structure(plan)
    validate_gate_v_campaign_manifest_v2_structure(manifest)
    if (
        manifest.campaign_id != plan.campaign_id
        or manifest.preregistration_id != plan.preregistration_id
        or manifest.campaign_protocol_fingerprint != plan.campaign_protocol_fingerprint
    ):
        raise ValueError("Le manifeste appartient à une autre campagne que le plan.")
    wf_id, mc_id = manifest.walk_forward_validation_run_id, manifest.monte_carlo_validation_run_id
    if wf_id is not None and wf_id != gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD):
        raise ValueError("walk_forward_validation_run_id est étranger à cette campagne.")
    if mc_id is not None and mc_id != gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO):
        raise ValueError("monte_carlo_validation_run_id est étranger à cette campagne.")
    for fold_id, run_id in manifest.parameter_stability_validation_run_ids_by_fold.items():
        if fold_id not in plan.expected_fold_ids:
            raise ValueError(f"Fold Parameter Stability {fold_id!r} étranger aux folds attendus de la campagne.")
        if run_id != gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_PARAMETER_STABILITY, fold_id=fold_id):
            raise ValueError(f"Identifiant Parameter Stability du fold {fold_id!r} étranger à cette campagne.")
    if manifest.status == _EVIDENCE_COMPLETE_STATUS and set(
        manifest.parameter_stability_validation_run_ids_by_fold
    ) != set(plan.expected_fold_ids):
        raise ValueError("Un manifeste complet doit référencer Parameter Stability pour TOUS les folds attendus.")


# ---------------------------------------------------------------------------------------------
# Record pur (types JSON simples) — aucune lecture ni écriture de fichier
# ---------------------------------------------------------------------------------------------


def gate_v_campaign_manifest_v2_to_record(manifest: GateVCampaignManifestV2) -> dict:
    """Record à EXACTEMENT 17 clés (ordre du type), types JSON simples, sans alias vers le manifeste.
    Refuse un manifeste structurellement invalide : aucun état invalide n'est sérialisable."""
    validate_gate_v_campaign_manifest_v2_structure(manifest)
    record = {field.name: getattr(manifest, field.name) for field in fields(GateVCampaignManifestV2)}
    record["parameter_stability_validation_run_ids_by_fold"] = dict(
        manifest.parameter_stability_validation_run_ids_by_fold
    )
    return record


def gate_v_campaign_manifest_v2_from_record(record: dict) -> GateVCampaignManifestV2:
    """Reconstruit puis revalide un Manifest V2 depuis un record déjà fourni. Ensemble de clés EXACT (clé
    inconnue ou manquante : refus), version exacte, structure revalidée ; jamais de repli vers V1 et jamais
    de fusion d'un record V1 (aucune clé de version, dix champs) avec le schéma V2."""
    if not isinstance(record, dict):
        raise ValueError("Le record d'un Manifest V2 doit être un objet (dict).")
    expected_keys = {field.name for field in fields(GateVCampaignManifestV2)}
    if set(record) != expected_keys:
        missing = sorted(expected_keys - set(record), key=str)
        unknown = sorted(set(record) - expected_keys, key=str)
        raise ValueError(f"Clés du record de Manifest V2 invalides : manquantes {missing}, inconnues {unknown}.")
    manifest = GateVCampaignManifestV2(**record)
    validate_gate_v_campaign_manifest_v2_structure(manifest)
    return manifest


# ---------------------------------------------------------------------------------------------
# Slice D3 — statut posé par les marqueurs (PUR : les preuves sont des ValidationRun DÉJÀ chargées)
# ---------------------------------------------------------------------------------------------


def _proof_references(manifest: GateVCampaignManifestV2) -> list:
    """Identifiants de preuve que le Manifest RÉFÉRENCE (WF, MC, puis PS par fold), sans les références vides."""
    references = [
        manifest.walk_forward_validation_run_id, manifest.monte_carlo_validation_run_id,
        *manifest.parameter_stability_validation_run_ids_by_fold.values(),
    ]
    return [reference for reference in references if reference is not None]


def _referenced_evidence(manifest: GateVCampaignManifestV2, evidence_by_validation_run_id) -> dict:
    """Vue FILTRÉE : uniquement les preuves que le Manifest référence. Une preuve présente dans le mapping
    mais non référencée n'a aucune autorité (écrite, jamais adoptée) ; une référence sans preuve fournie est un
    Manifest « en avance sur les preuves » (ADR 0025 §21.6) : erreur fermée, jamais un simple statut incomplet."""
    if not isinstance(evidence_by_validation_run_id, Mapping):
        raise ValueError("evidence_by_validation_run_id doit être un mapping de ValidationRun.")
    view = {}
    for run_id in _proof_references(manifest):
        # Lecture UNIQUE : une valeur `None` (ou qui n'est pas une ValidationRun) est une preuve ABSENTE, comme
        # pour D1 ; un simple test d'appartenance laisserait un Manifest « en avance » obtenir un statut.
        proof = evidence_by_validation_run_id.get(run_id)
        if not isinstance(proof, ValidationRun):
            raise ValueError(f"La preuve référencée {run_id!r} est absente des preuves fournies.")
        view[run_id] = proof
    return view


def derive_gate_v_campaign_v2_marker_status(
    plan: GateVCampaignPlanV2, manifest: GateVCampaignManifestV2,
    evidence_by_validation_run_id: Mapping[str, ValidationRun],
) -> str:
    """Statut dérivé des MARQUEURS du Manifest et des seules preuves qu'il RÉFÉRENCE (jamais d'E/S, jamais de
    verdict). Valide d'abord le Manifest et sa liaison au Plan V2, puis, par priorité : motif d'échec
    technique -> `TECHNICAL_FAILURE` ; `running` -> `RUNNING` ; non démarrée -> `READY_FOR_EXECUTION` ; sinon la
    complétude des preuves référencées, jugée par D1 (`evaluate_pre_holdout_evidence_v2`, autorité unique)
    -> `EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT` ou `EVIDENCE_INCOMPLETE`. Ne connaît pas la sentinelle d'échec
    technique : la valeur EFFECTIVE qui en tient compte est `derive_gate_v_campaign_v2_effective_status` (D4).

    Exception explicite : un Manifest portant un motif d'échec technique est TERMINAL et reste dérivable SANS
    inspecter aucune preuve — l'échec peut précisément venir d'une preuve absente, illisible ou corrompue, et
    exiger ces preuves rendrait l'échec inenregistrable."""
    validate_gate_v_campaign_manifest_v2_against_plan(manifest, plan)
    if manifest.technical_failure_reason is not None:
        return "TECHNICAL_FAILURE"
    referenced = _referenced_evidence(manifest, evidence_by_validation_run_id)
    by_markers = _statuses_compatible_with_markers(manifest)
    if len(by_markers) == 1:
        return next(iter(by_markers))
    facts = evaluate_pre_holdout_evidence_v2(plan, referenced)
    return _EVIDENCE_COMPLETE_STATUS if facts.pre_holdout_evidence_complete else "EVIDENCE_INCOMPLETE"


def validate_gate_v_campaign_manifest_v2_marker_status(
    manifest: GateVCampaignManifestV2, plan: GateVCampaignPlanV2,
    evidence_by_validation_run_id: Mapping[str, ValidationRun],
) -> None:
    """Le statut PERSISTÉ doit être exactement le statut dérivé des marqueurs et des preuves référencées
    (autocohérence du fichier ; réutilisable après rechargement des preuves)."""
    derived = derive_gate_v_campaign_v2_marker_status(plan, manifest, evidence_by_validation_run_id)
    if manifest.status != derived:
        raise ValueError(f"Statut persisté {manifest.status!r} différent du statut dérivé {derived!r}.")


# ---------------------------------------------------------------------------------------------
# Slice D3 — six commandes PURES (ensemble fermé, ADR 0025 §21.8) et leur application
# ---------------------------------------------------------------------------------------------


class ManifestTransitionError(ValueError):
    """Transition refusée : mauvaise transition, révision périmée, remplacement d'une référence ou commande
    interdite en état terminal (marqueur ou sentinelle d'échec). Refus : rien n'est écrit. Jamais une erreur de
    système de fichiers : celles de la persistance D4 ont leurs propres types (verrou, écriture, libération)."""


@dataclass(frozen=True)
class Start:
    """Démarre la campagne (`execution_started = True`)."""


@dataclass(frozen=True)
class SetRunning:
    """Pose `running` (`True` avant une phase coûteuse ; `False` pour un arrêt coopératif)."""

    running: bool


@dataclass(frozen=True)
class AttachWalkForward:
    """Rattache la preuve Walk-Forward et efface `running` dans la même nouvelle version."""

    run_id: str


@dataclass(frozen=True)
class AttachMonteCarlo:
    """Rattache la preuve Monte-Carlo (Walk-Forward déjà rattachée) et efface `running`."""

    run_id: str


@dataclass(frozen=True)
class AttachParameterStability:
    """Rattache la preuve Parameter Stability d'un fold attendu (Walk-Forward déjà rattachée) et efface
    `running`."""

    fold_id: str
    run_id: str


@dataclass(frozen=True)
class MarkTechnicalFailure:
    """Enregistre un échec technique (état terminal) et efface `running`."""

    reason: str


# `type(command) in` : une sous-classe d'une commande n'est jamais une commande.
_COMMAND_TYPES = (
    Start, SetRunning, AttachWalkForward, AttachMonteCarlo, AttachParameterStability, MarkTechnicalFailure,
)


def _require_revision_argument(expected_revision) -> None:
    """`expected_revision` : argument OBLIGATOIRE, entier non booléen >= 0 (contrôle partagé par D3 et D4)."""
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValueError("expected_revision doit être un entier non booléen >= 0.")


def _require_command(command) -> None:
    """Une des six commandes de l'ensemble fermé, jamais une sous-classe (contrôle partagé par D3 et D4)."""
    if type(command) not in _COMMAND_TYPES:
        raise ValueError("command doit être l'une des six commandes du Manifest V2.")


def _evolve(manifest: GateVCampaignManifestV2, **changes) -> GateVCampaignManifestV2:
    """Nouveau Manifest = ancien + `changes` (le mapping Parameter Stability est recopié, jamais aliasé)."""
    values = {field.name: getattr(manifest, field.name) for field in fields(GateVCampaignManifestV2)}
    values.update(changes)
    return GateVCampaignManifestV2(**values)


def _attach_changes(plan, manifest, command, evidence_by_validation_run_id):
    """Champs modifiés par un `Attach…`, ou `None` si la même référence est déjà rattachée (idempotence).
    Une preuve est rattachable si elle est présente, de l'identifiant déterministe et « scoped » (D1) ; sa
    COMPLÉTUDE n'est pas une condition d'adoption (elle relève de la dérivation du statut)."""
    run_id = command.run_id
    if not _is_non_empty_str(run_id):
        raise ValueError("run_id doit être une chaîne non vide.")
    command_type = type(command)
    if command_type is AttachWalkForward:
        validation_type, fold_id = VALIDATION_TYPE_WALK_FORWARD, None
        current = manifest.walk_forward_validation_run_id
    else:
        if manifest.walk_forward_validation_run_id is None:
            raise ManifestTransitionError("La preuve Walk-Forward doit être rattachée en premier.")
        if command_type is AttachMonteCarlo:
            validation_type, fold_id = VALIDATION_TYPE_MONTE_CARLO, None
            current = manifest.monte_carlo_validation_run_id
        else:
            validation_type, fold_id = VALIDATION_TYPE_PARAMETER_STABILITY, command.fold_id
            if not _is_non_empty_str(fold_id) or fold_id not in plan.expected_fold_ids:
                raise ValueError(f"Fold Parameter Stability {fold_id!r} étranger aux folds attendus.")
            current = manifest.parameter_stability_validation_run_ids_by_fold.get(fold_id)
    if current is not None:
        if current == run_id:
            return None
        raise ManifestTransitionError("Une référence déjà rattachée ne se remplace jamais.")
    if run_id != gate_v_v2_validation_run_id(plan, validation_type, fold_id=fold_id):
        raise ValueError("run_id n'est pas l'identifiant déterministe de cette preuve pour cette campagne.")
    if validate_scoped_evidence_run_v2(plan, run_id, validation_type, evidence_by_validation_run_id) is None:
        raise ValueError(f"La preuve {run_id!r} n'est pas dans les preuves fournies.")
    if command_type is AttachWalkForward:
        return {"walk_forward_validation_run_id": run_id, "running": False}
    if command_type is AttachMonteCarlo:
        return {"monte_carlo_validation_run_id": run_id, "running": False}
    return {
        "parameter_stability_validation_run_ids_by_fold": {
            **manifest.parameter_stability_validation_run_ids_by_fold, fold_id: run_id},
        "running": False,
    }


def _command_changes(plan, manifest, command, evidence_by_validation_run_id):
    """Champs modifiés par la commande, ou `None` si elle est idempotente. Lève `ManifestTransitionError` pour une
    transition interdite, `ValueError` pour une charge utile invalide ou une preuve étrangère."""
    command_type = type(command)
    failed = manifest.technical_failure_reason is not None
    if command_type is MarkTechnicalFailure:
        if not _is_non_empty_str(command.reason):
            raise ValueError("reason doit être une chaîne non vide.")
        if not manifest.execution_started:
            raise ManifestTransitionError("Un échec technique exige une campagne démarrée.")
        if failed:
            if command.reason == manifest.technical_failure_reason:
                return None
            raise ManifestTransitionError("Un échec technique déjà enregistré ne change jamais de motif.")
        return {"technical_failure_reason": command.reason, "running": False}
    if command_type is SetRunning and not isinstance(command.running, bool):
        raise ValueError("running doit être un booléen.")
    if failed:
        raise ManifestTransitionError("TECHNICAL_FAILURE est terminal : aucune autre commande n'est acceptée.")
    if command_type is Start:
        return None if manifest.execution_started else {"execution_started": True}
    if not manifest.execution_started:
        raise ManifestTransitionError("La commande exige une campagne démarrée.")
    if command_type is SetRunning:
        return None if command.running == manifest.running else {"running": command.running}
    return _attach_changes(plan, manifest, command, evidence_by_validation_run_id)


def apply_gate_v_campaign_manifest_v2_command(
    plan: GateVCampaignPlanV2, manifest: GateVCampaignManifestV2, command,
    evidence_by_validation_run_id: Mapping[str, ValidationRun], *, expected_revision: int,
) -> GateVCampaignManifestV2:
    """Applique UNE commande à un Manifest, sans E/S, et retourne le Manifest résultant. Ordre : liaison au plan
    -> `expected_revision` (entier non booléen, égal à la révision du Manifest, même pour une commande qui serait
    idempotente ; aucun rebase) -> commande de l'ensemble fermé -> statut persisté de l'entrée cohérent avec ses
    preuves référencées (sauf `MarkTechnicalFailure`, indépendante des preuves) -> transition -> statut dérivé
    -> `manifest_revision + 1` exactement. Commande idempotente : le MÊME Manifest est retourné, révision inchangée.
    Le Manifest d'entrée, le plan et les preuves ne sont jamais modifiés ; le résultat n'alias aucun d'eux."""
    validate_gate_v_campaign_manifest_v2_against_plan(manifest, plan)
    _require_revision_argument(expected_revision)
    if expected_revision != manifest.manifest_revision:
        raise ManifestTransitionError(
            f"Révision périmée : attendue {expected_revision}, Manifest à {manifest.manifest_revision}.")
    _require_command(command)
    if type(command) is not MarkTechnicalFailure:
        # `MarkTechnicalFailure` est la SEULE commande qui ne dépend d'aucune preuve référencée (ni de leur
        # présence ni de leur validité) : un échec technique peut venir d'une preuve inutilisable. Toutes les
        # autres commandes restent fail-closed sur le statut persisté et les preuves référencées.
        validate_gate_v_campaign_manifest_v2_marker_status(manifest, plan, evidence_by_validation_run_id)
    changes = _command_changes(plan, manifest, command, evidence_by_validation_run_id)
    if changes is None:
        return manifest
    candidate = _evolve(manifest, **changes)
    by_markers = _statuses_compatible_with_markers(candidate)
    provisional = "EVIDENCE_INCOMPLETE" if "EVIDENCE_INCOMPLETE" in by_markers else next(iter(by_markers))
    candidate = _evolve(candidate, status=provisional)
    result = _evolve(
        candidate, status=derive_gate_v_campaign_v2_marker_status(plan, candidate, evidence_by_validation_run_id),
        manifest_revision=manifest.manifest_revision + 1,
    )
    validate_gate_v_campaign_manifest_v2_marker_status(result, plan, evidence_by_validation_run_id)
    return result


# ---------------------------------------------------------------------------------------------
# Slice D4 — persistance (ADR 0025 §21.5, §21.8) : création exclusive, chargeur strict, mise à jour sous
# `manifest.update.lock`, sentinelle d'échec technique, statut effectif. Tout jugement reste celui de D1/D3.
# ---------------------------------------------------------------------------------------------

GATE_V_TECHNICAL_FAILURE_SENTINEL_SEMANTICS_VERSION = "gate_v_technical_failure_sentinel_v1"
# Motif FIXE de réconciliation d'une sentinelle illisible, tronquée ou non conforme (ADR 0025 §21.8).
GATE_V_TECHNICAL_FAILURE_SENTINEL_UNREADABLE_REASON = "technical_failure_sentinel_unreadable"

_PLAN_FILE = "plan.json"
_MANIFEST_FILE = "manifest.json"
_MANIFEST_KIND = "GateVCampaignManifestV2"
_SENTINEL_FILE = "technical_failure.json"
# Exactement trois clés : ni horodatage, ni PID, ni hôte, ni chemin, ni révision.
_SENTINEL_KEYS = frozenset({"technical_failure_sentinel_semantics_version", "campaign_id", "reason"})


def _require_persisted_plan(plan: GateVCampaignPlanV2, directory: Path) -> None:
    if load_gate_v_campaign_plan_v2(directory / _PLAN_FILE) != plan:
        raise ValueError("Le plan.json persisté de la campagne diffère du plan fourni : refus fermé.")


def _campaign_directory(plan: GateVCampaignPlanV2, campaign_dir) -> Path:
    """`campaign_dir` (fourni par l'appelant, jamais résolu ici) est le dossier `<campaign_root>/<campaign_id>` du
    plan ET son `plan.json` persisté, relu par le chargeur strict de la Slice C, est égal au plan fourni."""
    if not isinstance(plan, GateVCampaignPlanV2):
        raise ValueError("plan doit être un GateVCampaignPlanV2 validé.")
    validate_gate_v_campaign_plan_v2_structure(plan)
    if not isinstance(campaign_dir, (str, Path)) or not str(campaign_dir).strip():
        raise ValueError("campaign_dir est obligatoire : il est toujours fourni par l'appelant.")
    directory = Path(campaign_dir)
    if directory.name != plan.campaign_id:
        raise ValueError("campaign_dir doit être le dossier <campaign_root>/<campaign_id> de ce plan.")
    _require_persisted_plan(plan, directory)
    return directory


def _read_manifest(plan: GateVCampaignPlanV2, directory: Path) -> GateVCampaignManifestV2:
    record = load_json_tolerant(directory / _MANIFEST_FILE)
    if record is None:
        raise ValueError("manifest.json absent, illisible ou JSON invalide : refus fermé, jamais réparé.")
    manifest = gate_v_campaign_manifest_v2_from_record(record)
    validate_gate_v_campaign_manifest_v2_against_plan(manifest, plan)
    return manifest


def create_gate_v_campaign_manifest_v2(plan: GateVCampaignPlanV2, campaign_dir) -> GateVCampaignManifestV2:
    """Crée `<campaign_dir>/manifest.json` UNE SEULE FOIS, par création exclusive (`save_exclusive`, jamais un
    écrasement) : Manifest initial déterministe (révision 0, non démarré, aucune référence, champs 13-17 `None`).
    Un second créateur reçoit `FileExistsError` : rien n'est écrasé, réparé ni recréé, même un fichier tronqué."""
    directory = _campaign_directory(plan, campaign_dir)
    manifest = build_gate_v_campaign_manifest_v2(plan)
    save_exclusive(directory / _MANIFEST_FILE, gate_v_campaign_manifest_v2_to_record(manifest), kind=_MANIFEST_KIND)
    return manifest


def load_gate_v_campaign_manifest_v2(plan: GateVCampaignPlanV2, campaign_dir) -> GateVCampaignManifestV2:
    """Chargeur STRICT du Manifest V2 persisté, en lecture seule : fichier absent, illisible, JSON invalide ou non
    objet -> refus ; reconstruction par `gate_v_campaign_manifest_v2_from_record` (jamais de repli V1) puis liaison
    au plan. Ne prend jamais `manifest.update.lock`, ne lit ni la sentinelle ni les preuves, n'écrit rien."""
    return _read_manifest(plan, _campaign_directory(plan, campaign_dir))


# --- Sentinelle `technical_failure.json` : fait d'échec exclusif, INDÉPENDANT du verrou (jamais un Claim) --------


def _is_persistable_reason(reason) -> bool:
    """Motif non vide ET encodable en UTF-8 : sinon la création exclusive consommerait le chemin de la sentinelle
    puis échouerait à l'écriture (sentinelle vide irréversible, vrai motif perdu)."""
    if not _is_non_empty_str(reason):
        return False
    try:
        reason.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _sentinel_exists(directory: Path) -> bool:
    """L'EXISTENCE du chemin est le fait (fichier vide, tronqué, illisible ou non conforme compris). Toute autre
    erreur que l'absence est propagée : jamais lue comme « aucun échec »."""
    try:
        os.lstat(directory / _SENTINEL_FILE)
    except FileNotFoundError:
        return False
    return True


def _sentinel_reason(plan: GateVCampaignPlanV2, directory: Path) -> Optional[str]:
    """`None` si la sentinelle est absente ; son `reason` si elle est lisible ET conforme (exactement les trois clés,
    version exacte, campagne du plan, motif non vide encodable en UTF-8) ; sinon le motif fixe « illisible ». Jamais
    réparée."""
    if not _sentinel_exists(directory):
        return None
    try:
        record = load_json_tolerant(directory / _SENTINEL_FILE)
    except Exception:  # toute lecture impossible = sentinelle illisible ; le fait reste son existence
        record = None
    if (
        isinstance(record, dict) and set(record) == _SENTINEL_KEYS
        and record["technical_failure_sentinel_semantics_version"]
        == GATE_V_TECHNICAL_FAILURE_SENTINEL_SEMANTICS_VERSION
        and record["campaign_id"] == plan.campaign_id and _is_persistable_reason(record["reason"])
    ):
        return record["reason"]
    return GATE_V_TECHNICAL_FAILURE_SENTINEL_UNREADABLE_REASON


def _require_reason_matching_sentinel(plan, directory: Path, manifest: GateVCampaignManifestV2, reason: str) -> None:
    """Seul le motif AUTORITAIRE de la sentinelle (ou le motif fixe si elle est illisible) réconcilie un Manifest
    sans marqueur ; un Manifest déjà marqué ne change jamais de motif, et ne peut diverger d'une sentinelle lisible
    que s'il porte le motif fixe « illisible », toléré pour toujours (jamais réécrit)."""
    authoritative = _sentinel_reason(plan, directory)
    if authoritative is None:
        raise ManifestTransitionError("Sentinelle d'échec technique absente : le fait ne se recrée jamais ici.")
    recorded = manifest.technical_failure_reason
    if recorded is None:
        consistent = reason == authoritative
    else:
        consistent = reason == recorded and recorded in (
            authoritative, GATE_V_TECHNICAL_FAILURE_SENTINEL_UNREADABLE_REASON)
    if not consistent:
        raise ManifestTransitionError(
            f"Motif {reason!r} incompatible avec la sentinelle (motif autoritaire {authoritative!r}) : la première "
            "sentinelle gagne et n'est jamais réécrite.")


def _record_technical_failure_sentinel(plan: GateVCampaignPlanV2, directory: Path, reason: str) -> None:
    """AVANT toute tentative de verrou (ADR 0025 §21.8) : lecture NON verrouillée stricte du Manifest ; campagne
    démarrée exigée (sinon aucune sentinelle, transition refusée) ; création EXCLUSIVE de la sentinelle, seulement
    pour un Manifest encore sans motif et jamais avec le motif fixe (réservé à la réconciliation d'une sentinelle
    illisible). Si elle existe déjà, elle gagne : la commande doit porter son motif autoritaire."""
    manifest = _read_manifest(plan, directory)
    if not manifest.execution_started:
        raise ManifestTransitionError("Un échec technique exige une campagne démarrée : aucune sentinelle n'est posée.")
    if manifest.technical_failure_reason is None and reason != GATE_V_TECHNICAL_FAILURE_SENTINEL_UNREADABLE_REASON:
        record = {
            "technical_failure_sentinel_semantics_version": GATE_V_TECHNICAL_FAILURE_SENTINEL_SEMANTICS_VERSION,
            "campaign_id": plan.campaign_id,
            "reason": reason,
        }
        try:
            save_exclusive(directory / _SENTINEL_FILE, record, kind="technical_failure sentinel")
            return
        except FileExistsError:
            pass  # la sentinelle existante gagne : son motif fait foi
    _require_reason_matching_sentinel(plan, directory, manifest, reason)


def _revalidate_at_linearization_point(plan, directory: Path, manifest: GateVCampaignManifestV2, command) -> None:
    """Étape 5, point de linéarisation : « sans échec » inclut l'existence de la sentinelle. Une sentinelle créée
    APRÈS cette étape laisse la commande aboutir (jamais revérifiée ensuite : le statut effectif prime)."""
    if type(command) is MarkTechnicalFailure:
        _require_reason_matching_sentinel(plan, directory, manifest, command.reason)
    elif _sentinel_exists(directory):
        raise ManifestTransitionError("La sentinelle technical_failure.json existe : TECHNICAL_FAILURE est terminal.")


def derive_gate_v_campaign_v2_effective_status(
    plan: GateVCampaignPlanV2, campaign_dir, manifest: GateVCampaignManifestV2,
    evidence_by_validation_run_id: Mapping[str, ValidationRun],
) -> str:
    """Statut EFFECTIF (ADR 0025 §21.5) : `TECHNICAL_FAILURE` dès que le CHEMIN `technical_failure.json` existe (son
    contenu n'est pas nécessaire au fait, aucune preuve n'est lue), sinon le statut posé par les marqueurs (D3, sur les
    preuves fournies). Une valeur dérivée, jamais une autorisation : n'accorde aucun droit d'accès FINAL_HOLDOUT."""
    directory = _campaign_directory(plan, campaign_dir)
    validate_gate_v_campaign_manifest_v2_against_plan(manifest, plan)
    if _sentinel_exists(directory):
        return "TECHNICAL_FAILURE"
    return derive_gate_v_campaign_v2_marker_status(plan, manifest, evidence_by_validation_run_id)


# --- Verrou transitoire `manifest.update.lock` (consultatif : il n'exclut que les écrivains de cette API) ---------
# Trois catégories d'issue, JAMAIS confondues : refus, rien d'écrit (`FileExistsError` du verrou occupé,
# `ManifestLockAcquisitionError`, `ManifestTransitionError`, `ManifestWriteError`) ; validé mais verrou résiduel
# (`ManifestLockReleaseError(committed=True)`) ; incertain (`ManifestWriteUncertainError`, verrou conservé).


class ManifestLockAcquisitionError(Exception):
    """Étape 1 : `os.open(O_EXCL)` a échoué pour une autre raison qu'un verrou existant (sous Windows, un verrou en
    suppression différée lève `PermissionError`). Refus : rien d'écrit, le chemin existant n'est jamais touché."""


class ManifestWriteError(Exception):
    """Étape 9 ou 10 : la relecture SOUS le verrou montre l'ANCIEN Manifest, ou la propriété du verrou n'a pas pu être
    vérifiée juste avant l'écriture (aucune tentative d'écriture) : rien n'est validé, verrou libéré. Jamais un retry
    automatique de l'écriture."""


class ManifestWriteUncertainError(Exception):
    """Étape 9 ou 10 : le Manifest relu n'est ni l'ancien ni le nouveau, ou ne peut pas être relu : état incertain,
    verrou CONSERVÉ (toute mutation suivante échoue fermée jusqu'à la récupération manuelle gouvernée)."""


class ManifestLockReleaseError(Exception):
    """Le propriétaire n'a pas pu supprimer son verrou (identité changée, fermeture ou suppression en échec) : le
    verrou reste. `committed` : `True` si le nouveau Manifest est VÉRIFIÉ persisté (transaction validée, jamais
    « rien d'écrit »), `False` si cette transaction n'a définitivement rien validé."""

    def __init__(self, message: str, *, committed: bool):
        super().__init__(message)
        self.committed = committed

    def __reduce__(self):
        # `committed` doit survivre à pickle/copy (frontière de processus) : jamais perdu à la désérialisation.
        return (_rebuild_lock_release_error, (str(self), self.committed))


def _rebuild_lock_release_error(message: str, committed: bool) -> ManifestLockReleaseError:
    return ManifestLockReleaseError(message, committed=committed)


_LOCK_FILE = "manifest.update.lock"
_VALIDATIONS_DIR = "validations"
_VALIDATION_RUN_FILE = "validation_run.json"
_ATTACH_COMMANDS = (AttachWalkForward, AttachMonteCarlo, AttachParameterStability)
_NOT_OWNED = (
    f"Le fichier au chemin {_LOCK_FILE} n'est plus celui créé par ce propriétaire (identité de fichier différente) : "
    "il n'est jamais supprimé."
)
_UNVERIFIABLE_IDENTITY = (
    f"Identité de {_LOCK_FILE} illisible ou non fournie après acquisition : propriété invérifiable, le verrou ne sera "
    "jamais supprimé (rien d'écrit)."
)


@dataclass(frozen=True)
class _UpdateLock:
    """Verrou POSSÉDÉ : chemin, descripteur ouvert par l'acquisition exclusive, et identité de fichier capturée SUR
    ce descripteur (périphérique, inode/index de fichier) — jamais sur le contenu. Exige un système de fichiers qui
    fournit une identité stable et non nulle (NTFS, systèmes POSIX usuels) ; sinon, refus fermé à l'acquisition."""

    path: Path
    fd: int
    identity: tuple


def _close_quietly(fd: int) -> None:
    """Fermeture d'un descripteur dont le verrou RESTE de toute façon : un échec de fermeture ne change rien à
    l'issue, plus grave, que l'appelant lève."""
    try:
        os.close(fd)
    except OSError:
        pass


def _acquire_update_lock(directory: Path) -> _UpdateLock:
    """Étapes 1-2 : l'appel système exclusif EST l'autorité, sans aucun test d'existence préalable. Un verrou
    occupé propage `FileExistsError` ; tout autre `OSError` devient `ManifestLockAcquisitionError`. Dans les deux
    cas rien n'est écrit et le chemin existant n'est jamais touché (le perdant n'entre jamais dans la libération)."""
    path = directory / _LOCK_FILE
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise
    except OSError as error:
        raise ManifestLockAcquisitionError(f"Acquisition de {_LOCK_FILE} impossible : refus, rien d'écrit.") from error
    try:
        status = os.fstat(fd)
    except OSError as error:
        _close_quietly(fd)
        raise ManifestLockReleaseError(_UNVERIFIABLE_IDENTITY, committed=False) from error
    if not status.st_ino:  # identité non fournie par le système de fichiers : jamais de suppression « au chemin »
        _close_quietly(fd)
        raise ManifestLockReleaseError(_UNVERIFIABLE_IDENTITY, committed=False)
    return _UpdateLock(path=path, fd=fd, identity=(status.st_dev, status.st_ino))


def _write_lock_content(lock: _UpdateLock, command, campaign_id: str, expected_revision: int) -> None:
    """Étape 2 bis : contenu INFORMATIF (commande, campagne, révision attendue ; aucun horodatage, PID ni hôte),
    jamais relu pour décider de la propriété, de la vivacité, d'une expiration ou d'une récupération."""
    content = {"command": type(command).__name__, "campaign_id": campaign_id, "expected_revision": expected_revision}
    os.write(lock.fd, json.dumps(content, sort_keys=True).encode("utf-8"))


def _still_owned(lock: _UpdateLock) -> bool:
    """Le fichier au chemin est-il TOUJOURS celui créé par ce propriétaire ? (`os.stat` du chemin contre l'identité
    capturée par `os.fstat` à l'acquisition ; toute erreur de lecture = non, jamais une suppression à l'aveugle.)"""
    try:
        status = os.stat(lock.path)
    except OSError:
        return False
    return (status.st_dev, status.st_ino) == lock.identity


def _unlink_if_still_owned(lock: _UpdateLock, *, committed: bool) -> None:
    if not _still_owned(lock):
        raise ManifestLockReleaseError(_NOT_OWNED, committed=committed)
    os.unlink(lock.path)


def _release_update_lock(lock: _UpdateLock, *, committed: bool) -> None:
    """Étape 11 (et toute sortie avant l'étape 9) : SEUL le propriétaire libère. Identité vérifiée descripteur
    ENCORE OUVERT, fermeture PUIS suppression (sous Windows un fichier ouvert ne se supprime pas), identité
    revérifiée juste avant chaque suppression (fenêtre fermeture -> suppression). Après un commit vérifié, UNE
    seule nouvelle tentative immédiate de suppression ; jamais d'attente, jamais de décision sur le contenu."""
    owned = _still_owned(lock)
    try:
        os.close(lock.fd)
    except OSError as error:
        raise ManifestLockReleaseError(
            f"Fermeture de {_LOCK_FILE} impossible : verrou laissé en place.", committed=committed) from error
    if not owned:
        raise ManifestLockReleaseError(_NOT_OWNED, committed=committed)
    try:
        _unlink_if_still_owned(lock, committed=committed)
    except OSError as first_error:
        if not committed:
            raise ManifestLockReleaseError(
                f"Suppression de {_LOCK_FILE} impossible : verrou résiduel, rien n'a été écrit.",
                committed=False,
            ) from first_error
        try:
            _unlink_if_still_owned(lock, committed=True)
        except OSError as second_error:
            raise ManifestLockReleaseError(
                f"Manifest validé, mais {_LOCK_FILE} n'a pas pu être supprimé : verrou résiduel.", committed=True,
            ) from second_error


def _validation_run_path(directory: Path, run_id: str) -> Path:
    """Chemin CANONIQUE d'une preuve (ADR 0025 Décision 16, §21.6) ; aucun raccourcissement d'identifiant."""
    return directory / _VALIDATIONS_DIR / run_id / _VALIDATION_RUN_FILE


def _is_portable_identifier(value) -> bool:
    try:
        validate_portable_identifier(value, "run_id")
    except ValueError:
        return False
    return True


class _IncoherentCandidateProof:
    """Preuve candidate d'un `Attach…` présente sur disque mais incohérente : jamais une `ValidationRun`, donc refusée
    fermée par D1/D3 si — et seulement si — la commande en arrive à l'adopter ; l'ordre des refus de D3 est conservé
    (un remplacement de référence reste un conflit de transition, « Walk-Forward d'abord » prime)."""


def _proofs_for_update(directory: Path, manifest: GateVCampaignManifestV2, command) -> dict:
    """Étape 6 : recharge SOUS le verrou, à leur chemin canonique, les SEULES preuves nécessaires — chaque référence
    du Manifest rechargé (incohérente : erreur fermée immédiate), plus la preuve candidate d'un `Attach…` à
    identifiant portable. Aucun balayage de `validations/` : une preuve orpheline n'est jamais adoptée
    automatiquement. Le jugement (présence, provenance, complétude) reste celui de D3/D1."""
    if type(command) is MarkTechnicalFailure or manifest.technical_failure_reason is not None:
        return {}  # exception de D3 : un échec technique et l'état terminal ne dépendent d'aucune preuve
    proofs = {}
    for run_id in _proof_references(manifest):
        try:
            run = load_validation_run(_validation_run_path(directory, run_id))
        except TypeError as error:  # forme JSON inattendue : preuve référencée incohérente, refus fermé typé
            raise ValueError(f"Preuve référencée {run_id!r} incohérente sur disque : refus fermé.") from error
        if run is not None:
            proofs[run_id] = run
    candidate = command.run_id if type(command) in _ATTACH_COMMANDS else None
    if _is_portable_identifier(candidate) and candidate not in proofs:
        try:
            run = load_validation_run(_validation_run_path(directory, candidate))
        except (ValueError, TypeError):  # contenu incohérent : D3 tranchera, à son rang
            run = _IncoherentCandidateProof()
        if run is not None:
            proofs[candidate] = run
    return proofs


def _reread_manifest(plan: GateVCampaignPlanV2, directory: Path) -> Optional[GateVCampaignManifestV2]:
    try:
        return _read_manifest(plan, directory)
    except Exception:  # relecture impossible ou contenu invalide : ni l'ancien ni le nouveau, jamais un refus
        return None


def _settle_persisted_state(lock, plan, directory, previous, result, write_error) -> None:
    """Étapes 9-10 : jamais de suppression aveugle du verrou après une tentative d'écriture. Relecture SOUS le
    verrou : nouveau Manifest valide -> validé (retour normal) ; ancien -> rien d'écrit : verrou libéré,
    `ManifestWriteError` ; autre chose ou relecture impossible -> verrou CONSERVÉ, `ManifestWriteUncertainError`."""
    persisted = _reread_manifest(plan, directory)
    if persisted == result:
        return
    if persisted == previous:
        _release_update_lock(lock, committed=False)
        raise ManifestWriteError(
            "Manifest relu identique à l'ancien : rien n'a été écrit, verrou libéré.") from write_error
    _close_quietly(lock.fd)
    raise ManifestWriteUncertainError(
        f"Manifest persisté ni ancien ni nouveau, ou illisible : état incertain, {_LOCK_FILE} conservé.",
    ) from write_error


def update_gate_v_campaign_manifest_v2(
    plan: GateVCampaignPlanV2, campaign_dir, command, *, expected_revision: int,
) -> GateVCampaignManifestV2:
    """Applique UNE commande au Manifest PERSISTÉ et retourne le Manifest résultant (ADR 0025 §21.8). `plan` doit
    être égal au `plan.json` persisté (relu avant ET sous le verrou) ; arguments invalides : `ValueError`, sans effet.

    `MarkTechnicalFailure` d'abord, AVANT le verrou : motif non vide encodable en UTF-8, lecture non verrouillée,
    campagne démarrée exigée, sentinelle `technical_failure.json` créée exclusivement (ou constatée : la première
    gagne, son motif fait foi). Puis :
    1-2. `os.open(O_CREAT|O_EXCL|O_WRONLY)` de `manifest.update.lock` : verrou occupé -> `FileExistsError`, autre
         `OSError` -> `ManifestLockAcquisitionError` ; rien d'écrit, le chemin existant jamais touché.
    2 bis. contenu informatif du verrou ; 3. `plan.json` et `manifest.json` rechargés SOUS le verrou ;
    4. `expected_revision` == révision rechargée, même pour une commande idempotente, sinon
       `ManifestTransitionError` (jamais de rebase : `manifest_revision` détecte, il n'exclut pas) ;
    5. point de linéarisation : sentinelle présente -> seul `MarkTechnicalFailure` de son motif est admis ;
    6. preuves référencées + candidate rechargées à leur chemin canonique (aucune pour `MarkTechnicalFailure` ni
       pour un Manifest déjà terminal) ;
    7-8. transition calculée par D3 (`apply_gate_v_campaign_manifest_v2_command`, révision + 1 exactement) ;
         commande idempotente -> rien d'écrit, étapes 9-10 sautées ;
    9-10. verrou encore possédé (sinon rien d'écrit), `save_atomic_overwrite` puis relecture : nouveau -> validé ;
          ancien -> `ManifestWriteError` ; sinon -> `ManifestWriteUncertainError`, verrou conservé ;
    11. libération par le seul propriétaire.
    Toute sortie avant l'étape 9 libère le verrou ; un échec de libération lève `ManifestLockReleaseError`
    (`committed` exact). Aucun retry interne : l'appelant recharge puis rejoue explicitement."""
    directory = _campaign_directory(plan, campaign_dir)
    _require_revision_argument(expected_revision)
    _require_command(command)
    if type(command) is MarkTechnicalFailure:
        if not _is_persistable_reason(command.reason):
            raise ValueError("reason doit être une chaîne non vide encodable en UTF-8.")
        _record_technical_failure_sentinel(plan, directory, command.reason)
    lock = _acquire_update_lock(directory)
    try:
        _write_lock_content(lock, command, plan.campaign_id, expected_revision)
        _require_persisted_plan(plan, directory)
        manifest = _read_manifest(plan, directory)
        if manifest.manifest_revision != expected_revision:
            raise ManifestTransitionError(
                f"Révision périmée sous verrou : attendue {expected_revision}, persistée "
                f"{manifest.manifest_revision} (aucun rebase).")
        _revalidate_at_linearization_point(plan, directory, manifest, command)
        proofs = _proofs_for_update(directory, manifest, command)
        result = apply_gate_v_campaign_manifest_v2_command(
            plan, manifest, command, proofs, expected_revision=expected_revision)
    except Exception:
        _release_update_lock(lock, committed=False)  # sortie avant l'étape 9 : le Manifest est inchangé
        raise
    if result is manifest:  # commande idempotente : étapes 9-10 sautées, rien d'écrit
        _release_update_lock(lock, committed=False)
        return manifest
    if not _still_owned(lock):  # étape 9 : écriture UNIQUEMENT sous un verrou encore possédé, jamais deux validés
        _release_update_lock(lock, committed=False)  # identité changée : lève `ManifestLockReleaseError`
        raise ManifestWriteError(
            f"Propriété de {_LOCK_FILE} non vérifiable juste avant l'écriture : rien n'a été écrit, verrou libéré.")
    try:
        save_atomic_overwrite(
            directory / _MANIFEST_FILE, gate_v_campaign_manifest_v2_to_record(result), kind=_MANIFEST_KIND)
    except Exception as write_error:
        _settle_persisted_state(lock, plan, directory, manifest, result, write_error)
    else:
        _settle_persisted_state(lock, plan, directory, manifest, result, None)
    _release_update_lock(lock, committed=True)
    return result
