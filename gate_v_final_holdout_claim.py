"""FinalHoldoutAccessClaim — AF-V-07 Slice E1 (ADR 0025, Décisions 10 et 22).

Cœur strictement PUR : objet immuable, hashes sémantiques, validation et sérialisation.
Instancier un `FinalHoldoutAccessClaim` n'autorise AUCUN accès au FINAL_HOLDOUT : l'autorité
d'exclusivité sera, en E2, la création exclusive du fichier (Décision 9), jamais cet objet.
Aucune lecture de fichier, horloge, moteur, donnée marché ou persistance dans ce module ;
`created_at` est fourni par l'appelant, conservé tel quel, et exclu des deux hashes (audit seul).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from datetime import datetime

from gate_v_campaign_plan_v2 import (
    GATE_V_CAMPAIGN_ID_V2_PREFIX,
    GateVCampaignPlanV2,
    validate_gate_v_campaign_plan_v2_structure,
)

FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION = "final_holdout_access_claim_v1"

# Les 10 champs de liaison, tous portés par `GateVCampaignPlanV2` (ordre du contrat JSON, D22.3).
_LINK_FIELDS = (
    "campaign_id",
    "preregistration_id",
    "preregistration_content_hash",
    "campaign_protocol_fingerprint",
    "research_run_id",
    "research_run_content_hash",
    "dataset_snapshot_id",
    "split_plan_id",
    "split_plan_fingerprint",
    "assessment_semantics_version",
)
# Préimage de la Décision 10 : les 10 champs de liaison + la version sémantique du claim (11 champs).
_PREIMAGE_FIELDS = (*_LINK_FIELDS, "claim_semantics_version")
_HEX64_FIELDS = (
    "claim_id", "claim_content_hash", "preregistration_id", "preregistration_content_hash",
    "campaign_protocol_fingerprint", "research_run_content_hash", "split_plan_fingerprint",
)
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")
# Préfixe lu depuis le Plan V2 (source unique de l'espace d'identifiants V2), jamais recopié.
_CAMPAIGN_ID_V2_RE = re.compile(re.escape(GATE_V_CAMPAIGN_ID_V2_PREFIX) + r"[0-9a-f]{64}")
# Instant ISO-8601 AVEC fuseau explicite (Z ou ±HH:MM), chiffres ASCII uniquement ; la valeur est conservée verbatim.
_AWARE_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)


@dataclass(frozen=True)
class FinalHoldoutAccessClaim:
    """Exactement 14 champs persistés (ADR 0025 Décision 22.3), tous des `str`. Construire via
    `build_final_holdout_access_claim()` ou `final_holdout_access_claim_from_record()` — l'appel direct
    au constructeur ne revalide rien."""

    claim_semantics_version: str
    claim_id: str
    claim_content_hash: str
    campaign_id: str
    preregistration_id: str
    preregistration_content_hash: str
    campaign_protocol_fingerprint: str
    research_run_id: str
    research_run_content_hash: str
    dataset_snapshot_id: str
    split_plan_id: str
    split_plan_fingerprint: str
    assessment_semantics_version: str
    created_at: str


def _require_str(value: object, name: str) -> str:
    # `type() is str` délibéré : bool, int, None, bytes et sous-classes de str ne sont pas du JSON normatif.
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} doit être une chaîne non vide de type str.")
    return value


def _require_hex64(value: object, name: str) -> None:
    if type(value) is not str or _SHA256_HEX_RE.fullmatch(value) is None:
        raise ValueError(f"{name} doit être un SHA-256 hexadécimal minuscule (64 caractères).")


def _validate_created_at(value: object) -> None:
    _require_str(value, "created_at")
    if _AWARE_TIMESTAMP_RE.fullmatch(value) is None:
        raise ValueError("created_at doit être ISO-8601 avec heure, secondes et fuseau explicite (Z ou ±HH:MM).")
    try:
        instant = datetime.fromisoformat(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("created_at doit être un instant ISO-8601 valide.") from exc
    if instant.utcoffset() is None:
        raise ValueError("created_at doit porter un fuseau explicite.")


def _canonical_json(record: dict) -> str:
    """Canonicalisation de la Décision 20.3 — duplication volontaire (helpers privés non importés entre
    modules) ; l'égalité de sortie avec le Plan V2 et la Slice B est verrouillée par un test."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256_hex(record: dict) -> str:
    return hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()


def _preimage(**values: object) -> dict:
    """Les 11 champs exacts de la préimage de la Décision 10 — jamais `created_at`, jamais un hash."""
    if set(values) != set(_PREIMAGE_FIELDS):
        raise ValueError(f"Préimage du Claim incorrecte : exactement {sorted(_PREIMAGE_FIELDS)} sont requis.")
    return {name: _require_str(values[name], name) for name in _PREIMAGE_FIELDS}


def compute_final_holdout_access_claim_id(
    *,
    campaign_id: str,
    preregistration_id: str,
    preregistration_content_hash: str,
    campaign_protocol_fingerprint: str,
    research_run_id: str,
    research_run_content_hash: str,
    dataset_snapshot_id: str,
    split_plan_id: str,
    split_plan_fingerprint: str,
    assessment_semantics_version: str,
    claim_semantics_version: str,
) -> str:
    """Décision 10 : `SHA256(canonical_json({les 11 champs de la préimage}))`. `created_at` exclu."""
    return _sha256_hex(_preimage(
        campaign_id=campaign_id,
        preregistration_id=preregistration_id,
        preregistration_content_hash=preregistration_content_hash,
        campaign_protocol_fingerprint=campaign_protocol_fingerprint,
        research_run_id=research_run_id,
        research_run_content_hash=research_run_content_hash,
        dataset_snapshot_id=dataset_snapshot_id,
        split_plan_id=split_plan_id,
        split_plan_fingerprint=split_plan_fingerprint,
        assessment_semantics_version=assessment_semantics_version,
        claim_semantics_version=claim_semantics_version,
    ))


def compute_final_holdout_access_claim_content_hash(
    *,
    claim_id: str,
    campaign_id: str,
    preregistration_id: str,
    preregistration_content_hash: str,
    campaign_protocol_fingerprint: str,
    research_run_id: str,
    research_run_content_hash: str,
    dataset_snapshot_id: str,
    split_plan_id: str,
    split_plan_fingerprint: str,
    assessment_semantics_version: str,
    claim_semantics_version: str,
) -> str:
    """Décision 10 : `SHA256(canonical_json({claim_id, les 11 champs de la préimage}))`.
    `claim_content_hash` est exclu de sa propre préimage (aucune définition circulaire) ; `created_at` aussi."""
    record = _preimage(
        campaign_id=campaign_id,
        preregistration_id=preregistration_id,
        preregistration_content_hash=preregistration_content_hash,
        campaign_protocol_fingerprint=campaign_protocol_fingerprint,
        research_run_id=research_run_id,
        research_run_content_hash=research_run_content_hash,
        dataset_snapshot_id=dataset_snapshot_id,
        split_plan_id=split_plan_id,
        split_plan_fingerprint=split_plan_fingerprint,
        assessment_semantics_version=assessment_semantics_version,
        claim_semantics_version=claim_semantics_version,
    )
    record["claim_id"] = _require_str(claim_id, "claim_id")
    return _sha256_hex(record)


def build_final_holdout_access_claim(plan: GateVCampaignPlanV2, *, created_at: str) -> FinalHoldoutAccessClaim:
    """Projection PURE d'un Plan V2 structurellement valide ; ne lit jamais l'horloge, aucune E/S.
    `created_at` est obligatoire, ISO-8601 avec fuseau, conservé verbatim et exclu des hashes."""
    validate_gate_v_campaign_plan_v2_structure(plan)
    _validate_created_at(created_at)
    links = {name: getattr(plan, name) for name in _LINK_FIELDS}
    preimage = _preimage(**links, claim_semantics_version=FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION)
    claim_id = compute_final_holdout_access_claim_id(**preimage)
    claim = FinalHoldoutAccessClaim(
        claim_semantics_version=FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION,
        claim_id=claim_id,
        claim_content_hash=compute_final_holdout_access_claim_content_hash(claim_id=claim_id, **preimage),
        **links,
        created_at=created_at,
    )
    validate_final_holdout_access_claim_structure(claim)
    return claim


def validate_final_holdout_access_claim_structure(claim: FinalHoldoutAccessClaim) -> None:
    """Validation PURE, fermée à l'échec : types stricts, formats, version sémantique exacte, puis
    recalcul des DEUX hashes depuis la préimage de la Décision 10. Ne prouve pas la liaison à un plan
    (voir `validate_final_holdout_access_claim_against_plan`) : un Claim auto-cohérent est valide ici."""
    if type(claim) is not FinalHoldoutAccessClaim:
        raise ValueError("claim doit être un FinalHoldoutAccessClaim.")
    for field in fields(FinalHoldoutAccessClaim):
        _require_str(getattr(claim, field.name), field.name)
    if claim.claim_semantics_version != FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION:
        raise ValueError(
            f"claim_semantics_version inconnue : attendu {FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION!r}, "
            f"reçu {claim.claim_semantics_version!r}."
        )
    if _CAMPAIGN_ID_V2_RE.fullmatch(claim.campaign_id) is None:
        raise ValueError(
            f"campaign_id doit avoir la forme {GATE_V_CAMPAIGN_ID_V2_PREFIX!r} + 64 hexadécimaux minuscules."
        )
    for name in _HEX64_FIELDS:
        _require_hex64(getattr(claim, name), name)
    _validate_created_at(claim.created_at)
    preimage = {name: getattr(claim, name) for name in _PREIMAGE_FIELDS}
    expected_id = compute_final_holdout_access_claim_id(**preimage)
    if claim.claim_id != expected_id:
        raise ValueError("FinalHoldoutAccessClaim incohérent : claim_id ne correspond pas à la préimage (Décision 10).")
    expected_hash = compute_final_holdout_access_claim_content_hash(claim_id=expected_id, **preimage)
    if claim.claim_content_hash != expected_hash:
        raise ValueError(
            "FinalHoldoutAccessClaim incohérent : claim_content_hash ne correspond pas à la préimage (Décision 10)."
        )


def validate_final_holdout_access_claim_against_plan(claim: FinalHoldoutAccessClaim, plan: GateVCampaignPlanV2) -> None:
    """Liaison stricte : le Claim est structurellement valide, le Plan V2 l'est aussi (barrières internes,
    aucune E/S ni vérification aux sources), et les 10 champs de liaison sont égaux au plan."""
    validate_final_holdout_access_claim_structure(claim)
    validate_gate_v_campaign_plan_v2_structure(plan)
    for name in _LINK_FIELDS:
        if getattr(claim, name) != getattr(plan, name):
            raise ValueError(f"FinalHoldoutAccessClaim : {name} diverge du Plan V2.")


def final_holdout_access_claim_to_record(claim: FinalHoldoutAccessClaim) -> dict:
    """Record JSON à exactement 14 clés, dans l'ordre normatif ; un Claim invalide est refusé."""
    validate_final_holdout_access_claim_structure(claim)
    return {field.name: getattr(claim, field.name) for field in fields(FinalHoldoutAccessClaim)}


def final_holdout_access_claim_from_record(record: dict) -> FinalHoldoutAccessClaim:
    """Reconstruction STRICTE : `dict` exact, clés exactement les 14 attendues (aucune tolérance), puis
    validation structurelle complète (hashes recalculés). Jamais de repli, jamais de `None`."""
    if type(record) is not dict:
        raise ValueError("FinalHoldoutAccessClaim : objet JSON (dict) attendu.")
    expected = tuple(field.name for field in fields(FinalHoldoutAccessClaim))
    unknown = sorted(set(record) - set(expected), key=str)
    missing = sorted(set(expected) - set(record))
    if unknown or missing:
        raise ValueError(f"FinalHoldoutAccessClaim : clés inconnues {unknown} ; clés manquantes {missing}.")
    claim = FinalHoldoutAccessClaim(**{name: record[name] for name in expected})
    validate_final_holdout_access_claim_structure(claim)
    return claim
