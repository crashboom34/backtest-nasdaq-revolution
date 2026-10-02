"""
gate_v_campaign_plan_v2.py — GateVCampaignPlanV2 (AF-V-07 Slice C, ADR 0025 Décision 20).

Plan de campagne Gate V V2 : type DISTINCT de `gate_v_campaign.GateVCampaignPlan` (V1, jamais
importé ni modifié ici — même discipline de frontière que Slice A/B). Lié à une
`GateVPreRegistration` validée ; aucune evidence WF/MC/PS/OOS/FINAL_HOLDOUT, aucun horodatage,
aucun chemin runtime dans le contrat normatif ni dans l'identité.

Scope Slice C (STRICT) : type + `campaign_id` V2 + builder + persistance exclusive + chargeur pur +
revalidation cross-sources. AUCUN Manifest V2, AUCUNE exécution WF/MC/PS, AUCUN
`FinalHoldoutAccessClaim`, AUCUN `ValidationAssessment`/`GateVPolicyAssessment`, AUCUN accès
`FINAL_HOLDOUT` (tranches suivantes).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple, Union

from atomic_json_store import load_json_tolerant, save_exclusive, validate_portable_identifier
from dataset_split import DatasetSplitPlan, dataset_split_plan_fingerprint
from gate_v_preregistration import (
    CAMPAIGN_PLAN_SEMANTICS_VERSION_V2,
    FULL_GIT_OBJECT_ID_RE,
    GATE_V_PREREGISTRATION_SEMANTICS_VERSION,
    GATE_V_SEARCH_MODES,  # noqa: F401  (ré-exporté : unique source des modes de recherche)
    GateVPreRegistration,
    compute_campaign_protocol_fingerprint,
    compute_fold_geometry,
    compute_preregistration_content_hash,
    compute_preregistration_id,
    compute_scope_key,
    research_run_content_hash,
    validate_campaign_protocol_inputs,
    verify_policy_git_provenance_historical,
)
from gate_v_validation_policy import GateVValidationPolicyVersion, policy_content_hash as compute_policy_content_hash
from research_run import ResearchRun
from strategy_contracts import DailyStateReadiness
from validation_run import (
    MONTE_CARLO_SEMANTICS_VERSION,
    PARAMETER_STABILITY_SEMANTICS_VERSION,
    WalkForwardSpecification,
)

# Source de vérité unique de la constante : celle de Slice B (déjà incluse dans
# `compute_campaign_protocol_fingerprint()`), jamais une seconde copie littérale.
GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION = CAMPAIGN_PLAN_SEMANTICS_VERSION_V2

GATE_V_CAMPAIGN_ID_V2_PREFIX = "gate_v_v2_"


@dataclass(frozen=True)
class GateVCampaignPlanV2:
    """Enregistrement de préparation immuable, déterministe (ADR 0025 Décision 20.4) — EXACTEMENT
    27 champs normatifs. Aucun `created_at`/timestamp, aucun `oos_evidence_*`, aucun résultat
    scientifique, aucun chemin runtime. Construire exclusivement via
    `build_gate_v_campaign_plan_v2()` — jamais l'appel direct au constructeur, qui ne revalide rien."""

    campaign_plan_semantics_version: str
    campaign_id: str
    preregistration_id: str
    preregistration_content_hash: str
    campaign_protocol_fingerprint: str
    research_run_id: str
    research_run_content_hash: str
    dataset_snapshot_id: str
    split_plan_id: str
    split_plan_fingerprint: str
    strategy_name: str
    base_params: dict
    search_mode: str
    search_space_hash: str
    budget_per_fold: int
    walk_forward_specification: WalkForwardSpecification
    readiness_spec: Optional[DailyStateReadiness]
    expected_fold_ids: Tuple[str, ...]
    expected_fold_definitions_hash: str
    validation_zone_hash: str
    walk_forward_spec_semantics_version: str
    monte_carlo_semantics_version: str
    parameter_stability_semantics_version: str
    gate_v_validation_policy_id: str
    policy_content_hash: str
    assessment_semantics_version: str
    policy_git_sha: str


def _canonical_json(record) -> str:
    """Canonicalisation V2 de la Décision 20.3 — duplication volontaire de `gate_v_preregistration.
    _canonical_json` (privée, non importée entre modules) ; l'égalité de sortie est verrouillée par
    `test_canonical_json_matches_slice_b_canonicalisation`."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _required_str(value, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} est obligatoire et doit être une chaîne non vide.")
    return value


def compute_gate_v_campaign_id_v2(
    *,
    campaign_plan_semantics_version: str,
    preregistration_id: str,
    campaign_protocol_fingerprint: str,
) -> str:
    """Fonction pure canonique (ADR 0025 Décision 20.3) : hash-de-hashes, aucun timestamp, aucun
    chemin, aucune evidence. `preregistration_id` inclut transitivement `policy_git_sha` que
    `campaign_protocol_fingerprint` seul n'inclut pas."""
    if campaign_plan_semantics_version != GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION:
        raise ValueError(
            "campaign_plan_semantics_version inconnue ou incorrecte : attendu "
            f"{GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION!r}, reçu {campaign_plan_semantics_version!r}."
        )
    record = {
        "campaign_plan_semantics_version": campaign_plan_semantics_version,
        "preregistration_id": _required_str(preregistration_id, "preregistration_id"),
        "campaign_protocol_fingerprint": _required_str(
            campaign_protocol_fingerprint, "campaign_protocol_fingerprint"
        ),
    }
    digest = hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()
    return GATE_V_CAMPAIGN_ID_V2_PREFIX + digest


# ---------------------------------------------------------------------------------------------
# Immutabilité profonde (copie JSON gelée — helper local, jamais importé depuis le V1)
# ---------------------------------------------------------------------------------------------

_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")
_CAMPAIGN_ID_V2_RE = re.compile(re.escape(GATE_V_CAMPAIGN_ID_V2_PREFIX) + r"[0-9a-f]{64}")


class _FrozenDict(dict):
    """Copie immuable, compatible JSON, d'un mapping de paramètres."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("Les paramètres d'un plan de campagne V2 sont immuables.")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        # `pickle`/`copy.copy` reconstruiraient sinon via le `__setitem__` bloqué : on repasse par
        # le constructeur (`dict.__init__`, non bloqué) avec une copie simple du contenu.
        return (_FrozenDict, (dict(self),))


def _freeze_json(value):
    """Copie gelée STRUCTURELLE (dict -> `_FrozenDict`, list/tuple -> tuple). Ne valide RIEN : la
    validité JSON/finitude de `base_params` est décidée par l'unique validation canonique de Slice B
    (`validate_campaign_protocol_inputs()`), appelée avant et après tout gel."""
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value):
    if isinstance(value, dict):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _plan_record(plan: "GateVCampaignPlanV2") -> dict:
    """Types JSON simples (dict/list) pour persistance et comparaison — jamais de chemin runtime."""
    return _thaw_json(dataclasses.asdict(plan))


# ---------------------------------------------------------------------------------------------
# Validation structurelle + barrières internes (pure : aucune E/S, aucun Git)
# ---------------------------------------------------------------------------------------------


def _require_hex64(value, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256_HEX_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} doit être un SHA-256 hexadécimal minuscule de 64 caractères.")


def _recompute_protocol_fingerprint(plan: "GateVCampaignPlanV2") -> str:
    """Recalcule l'empreinte via l'UNIQUE fonction canonique de Slice B, depuis les champs primitifs
    du plan — aucune seconde formule."""
    try:
        return compute_campaign_protocol_fingerprint(
            research_run_id=plan.research_run_id,
            research_run_content_hash=plan.research_run_content_hash,
            dataset_snapshot_id=plan.dataset_snapshot_id,
            split_plan_id=plan.split_plan_id,
            split_plan_fingerprint=plan.split_plan_fingerprint,
            strategy_name=plan.strategy_name,
            base_params=plan.base_params,
            search_mode=plan.search_mode,
            search_space_hash=plan.search_space_hash,
            budget_per_fold=plan.budget_per_fold,
            walk_forward_specification=plan.walk_forward_specification,
            readiness_spec=plan.readiness_spec,
            expected_fold_ids=plan.expected_fold_ids,
            expected_fold_definitions_hash=plan.expected_fold_definitions_hash,
            validation_zone_hash=plan.validation_zone_hash,
            walk_forward_spec_semantics_version=plan.walk_forward_spec_semantics_version,
            monte_carlo_semantics_version=plan.monte_carlo_semantics_version,
            parameter_stability_semantics_version=plan.parameter_stability_semantics_version,
            gate_v_validation_policy_id=plan.gate_v_validation_policy_id,
            policy_content_hash=plan.policy_content_hash,
            assessment_semantics_version=plan.assessment_semantics_version,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"GateVCampaignPlanV2 : empreinte de protocole non calculable : {exc}") from exc


def validate_gate_v_campaign_plan_v2_structure(plan: "GateVCampaignPlanV2") -> None:
    """Validation PURE (aucune E/S, aucun Git) : types/formats des 27 champs, invariants de la
    `WalkForwardSpecification` imbriquée, puis les deux barrières INTERNES de la Décision 20.6 étape 5 :
    (a) `campaign_protocol_fingerprint` recalculé depuis les champs primitifs ; (b) `campaign_id`
    recalculé depuis `{semantics_version, preregistration_id, campaign_protocol_fingerprint}`.
    Ne prouve PAS l'intégrité contre les sources externes (limite acceptée, Décision 20.6) — voir
    `validate_gate_v_campaign_plan_v2_sources()`."""
    if not isinstance(plan, GateVCampaignPlanV2):
        raise ValueError("plan doit être un GateVCampaignPlanV2.")
    if plan.campaign_plan_semantics_version != GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION:
        raise ValueError(
            f"campaign_plan_semantics_version inconnue : attendu {GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION!r}, "
            f"reçu {plan.campaign_plan_semantics_version!r}."
        )
    if not isinstance(plan.campaign_id, str) or _CAMPAIGN_ID_V2_RE.fullmatch(plan.campaign_id) is None:
        raise ValueError("campaign_id doit avoir la forme 'gate_v_v2_' + 64 hexadécimaux minuscules.")
    validate_portable_identifier(plan.campaign_id, "campaign_id")
    for name in (
        "preregistration_id", "preregistration_content_hash", "campaign_protocol_fingerprint",
        "research_run_content_hash", "split_plan_fingerprint", "expected_fold_definitions_hash",
        "validation_zone_hash", "policy_content_hash",
    ):
        _require_hex64(getattr(plan, name), name)
    validate_portable_identifier(plan.research_run_id, "research_run_id")
    validate_portable_identifier(plan.split_plan_id, "split_plan_id")
    validate_portable_identifier(plan.gate_v_validation_policy_id, "gate_v_validation_policy_id")
    for name in (
        "dataset_snapshot_id", "strategy_name", "walk_forward_spec_semantics_version",
        "monte_carlo_semantics_version", "parameter_stability_semantics_version",
        "assessment_semantics_version",
    ):
        _required_str(getattr(plan, name), name)
    if not isinstance(plan.policy_git_sha, str) or FULL_GIT_OBJECT_ID_RE.fullmatch(plan.policy_git_sha) is None:
        raise ValueError("policy_git_sha doit être un identifiant d'objet Git complet (40 ou 64 hex minuscules).")
    if (
        not isinstance(plan.expected_fold_ids, tuple) or not plan.expected_fold_ids
        or any(not isinstance(fold_id, str) or not fold_id for fold_id in plan.expected_fold_ids)
    ):
        raise ValueError("expected_fold_ids doit être un tuple non vide d'identifiants de fold.")
    # Validation canonique UNIQUE du protocole (Slice B) — la même que celle de la PreRegistration.
    canonical_search_space_hash = validate_campaign_protocol_inputs(
        base_params=plan.base_params, search_mode=plan.search_mode, search_space_hash=plan.search_space_hash,
        budget_per_fold=plan.budget_per_fold, walk_forward_specification=plan.walk_forward_specification,
        readiness_spec=plan.readiness_spec,
    )
    if canonical_search_space_hash != plan.search_space_hash:
        raise ValueError("search_space_hash doit être persisté sous sa forme canonique (minuscule).")
    if plan.walk_forward_specification.walk_forward_semantics_version != plan.walk_forward_spec_semantics_version:
        raise ValueError("walk_forward_spec_semantics_version incohérente avec walk_forward_specification.")

    if _recompute_protocol_fingerprint(plan) != plan.campaign_protocol_fingerprint:
        raise ValueError(
            "GateVCampaignPlanV2 incohérent (barrière 1 interne) : campaign_protocol_fingerprint ne "
            "correspond pas aux champs de protocole du plan."
        )
    expected_campaign_id = compute_gate_v_campaign_id_v2(
        campaign_plan_semantics_version=plan.campaign_plan_semantics_version,
        preregistration_id=plan.preregistration_id,
        campaign_protocol_fingerprint=plan.campaign_protocol_fingerprint,
    )
    if expected_campaign_id != plan.campaign_id:
        raise ValueError(
            "GateVCampaignPlanV2 incohérent (barrière 2 interne) : campaign_id ne correspond pas à "
            "{semantics_version, preregistration_id, campaign_protocol_fingerprint}."
        )


# ---------------------------------------------------------------------------------------------
# Builder + validation cross-sources (Décision 20.2/20.10)
# ---------------------------------------------------------------------------------------------


def _assert_preregistration_integrity(preregistration) -> None:
    """La PreRegistration fournie est recalculée (scope/id/hash), jamais crue sur parole — même
    logique de revalidation que `load_gate_v_preregistration()`, via les fonctions canoniques."""
    if not isinstance(preregistration, GateVPreRegistration):
        raise ValueError("preregistration doit être une GateVPreRegistration validée.")
    if preregistration.preregistration_semantics_version != GATE_V_PREREGISTRATION_SEMANTICS_VERSION:
        raise ValueError("preregistration_semantics_version inconnue.")
    try:
        scope_key = compute_scope_key(
            preregistration.research_run_id, preregistration.dataset_snapshot_id,
            preregistration.split_plan_id, preregistration.strategy_name,
        )
        id_kwargs = dict(
            scope_key=preregistration.scope_key,
            campaign_protocol_fingerprint=preregistration.campaign_protocol_fingerprint,
            research_run_id=preregistration.research_run_id,
            research_run_content_hash=preregistration.research_run_content_hash,
            dataset_snapshot_id=preregistration.dataset_snapshot_id,
            split_plan_id=preregistration.split_plan_id,
            strategy_name=preregistration.strategy_name,
            gate_v_validation_policy_id=preregistration.gate_v_validation_policy_id,
            policy_content_hash=preregistration.policy_content_hash,
            policy_git_sha=preregistration.policy_git_sha,
            assessment_semantics_version=preregistration.assessment_semantics_version,
            preregistration_semantics_version=preregistration.preregistration_semantics_version,
        )
        preregistration_id = compute_preregistration_id(**id_kwargs)
        content_hash = compute_preregistration_content_hash(preregistration_id=preregistration_id, **id_kwargs)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"GateVPreRegistration non recalculable : {exc}") from exc
    if scope_key != preregistration.scope_key:
        raise ValueError("GateVPreRegistration incohérente : scope_key ne correspond pas aux champs référencés.")
    if preregistration_id != preregistration.preregistration_id:
        raise ValueError("GateVPreRegistration incohérente : preregistration_id ne correspond pas au contenu.")
    if content_hash != preregistration.preregistration_content_hash:
        raise ValueError("GateVPreRegistration incohérente : preregistration_content_hash ne correspond pas au contenu.")


def _require_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise ValueError(message)


def _derive_plan(
    *,
    preregistration: GateVPreRegistration,
    research_run: ResearchRun,
    split_plan: DatasetSplitPlan,
    policy: GateVValidationPolicyVersion,
    policy_path: Union[str, Path],
    repo_dir: Optional[Union[str, Path]],
    strategy_name: str,
    base_params: Mapping,
    search_mode: str,
    search_space_hash: str,
    budget_per_fold: int,
    walk_forward_specification: WalkForwardSpecification,
    readiness_spec: Optional[DailyStateReadiness],
) -> "GateVCampaignPlanV2":
    """Chemin UNIQUE de dérivation, partagé par le builder ET la revalidation cross-sources : tout
    hash dérivé est RECALCULÉ depuis les vraies sources, jamais accepté d'un appelant."""
    _assert_preregistration_integrity(preregistration)
    if not isinstance(research_run, ResearchRun):
        raise ValueError("research_run doit être un ResearchRun.")
    if not isinstance(split_plan, DatasetSplitPlan):
        raise ValueError("split_plan doit être un DatasetSplitPlan.")
    if not isinstance(policy, GateVValidationPolicyVersion):
        raise ValueError("policy doit être une GateVValidationPolicyVersion.")
    _required_str(strategy_name, "strategy_name")
    # Validation canonique UNIQUE du protocole (Slice B), identique à celle de la PreRegistration ;
    # `search_space_hash` ressort normalisé en minuscule (comme le V1 avant fingerprint).
    search_space_hash = validate_campaign_protocol_inputs(
        base_params=base_params, search_mode=search_mode, search_space_hash=search_space_hash,
        budget_per_fold=budget_per_fold, walk_forward_specification=walk_forward_specification,
        readiness_spec=readiness_spec,
    )
    if research_run.dataset_snapshot_id != split_plan.dataset_snapshot_id:
        raise ValueError("research_run.dataset_snapshot_id ne correspond pas au split_plan référencé.")
    if split_plan.validation is None:
        raise ValueError("Le DatasetSplitPlan doit contenir une zone validation pour Walk-Forward.")

    frozen_params = _freeze_json(base_params)
    frozen_spec = dataclasses.replace(
        walk_forward_specification, base_params=_freeze_json(walk_forward_specification.base_params),
    )
    research_run_hash = research_run_content_hash(research_run)
    policy_hash = compute_policy_content_hash(policy)
    split_fingerprint = dataset_split_plan_fingerprint(split_plan)
    fold_ids, fold_definitions_hash, zone_hash = compute_fold_geometry(
        split_plan, walk_forward_specification, readiness_spec,
    )

    # Cross-check contre la PreRegistration validée (Décision 20.10, mission §13) — jamais de
    # correction silencieuse.
    _require_equal(research_run.research_run_id, preregistration.research_run_id, "research_run_id ne correspond pas à la PreRegistration.")
    _require_equal(research_run_hash, preregistration.research_run_content_hash, "research_run_content_hash ne correspond pas à la PreRegistration.")
    _require_equal(research_run.dataset_snapshot_id, preregistration.dataset_snapshot_id, "dataset_snapshot_id ne correspond pas à la PreRegistration.")
    _require_equal(split_plan.split_plan_id, preregistration.split_plan_id, "split_plan_id ne correspond pas à la PreRegistration.")
    _require_equal(strategy_name, preregistration.strategy_name, "strategy_name ne correspond pas à la PreRegistration.")
    _require_equal(policy.validation_policy_id, preregistration.gate_v_validation_policy_id, "gate_v_validation_policy_id ne correspond pas à la PreRegistration.")
    _require_equal(policy_hash, preregistration.policy_content_hash, "policy_content_hash ne correspond pas à la PreRegistration.")

    # Barrière 1 : empreinte de protocole recalculée depuis les vraies sources == PreRegistration.
    computed_fingerprint = compute_campaign_protocol_fingerprint(
        research_run_id=research_run.research_run_id,
        research_run_content_hash=research_run_hash,
        dataset_snapshot_id=research_run.dataset_snapshot_id,
        split_plan_id=split_plan.split_plan_id,
        split_plan_fingerprint=split_fingerprint,
        strategy_name=strategy_name,
        base_params=frozen_params,
        search_mode=search_mode,
        search_space_hash=search_space_hash,
        budget_per_fold=budget_per_fold,
        walk_forward_specification=frozen_spec,
        readiness_spec=readiness_spec,
        expected_fold_ids=fold_ids,
        expected_fold_definitions_hash=fold_definitions_hash,
        validation_zone_hash=zone_hash,
        walk_forward_spec_semantics_version=frozen_spec.walk_forward_semantics_version,
        monte_carlo_semantics_version=MONTE_CARLO_SEMANTICS_VERSION,
        parameter_stability_semantics_version=PARAMETER_STABILITY_SEMANTICS_VERSION,
        gate_v_validation_policy_id=policy.validation_policy_id,
        policy_content_hash=policy_hash,
        assessment_semantics_version=preregistration.assessment_semantics_version,
    )
    _require_equal(
        computed_fingerprint, preregistration.campaign_protocol_fingerprint,
        "Barrière 1 : le protocole recalculé depuis les sources ne correspond pas à "
        "preregistration.campaign_protocol_fingerprint (protocole modifié après préenregistrement).",
    )

    # Provenance HISTORIQUE du commit/blob de policy pinné (jamais HEAD courant, jamais working tree).
    verify_policy_git_provenance_historical(
        policy_path=policy_path, validation_policy_id=policy.validation_policy_id,
        expected_policy_content_hash=policy_hash, policy_git_sha=preregistration.policy_git_sha,
        repo_dir=repo_dir,
    )

    # Barrière 2 : identité de campagne recalculée depuis les entrées VALIDÉES.
    campaign_id = compute_gate_v_campaign_id_v2(
        campaign_plan_semantics_version=GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION,
        preregistration_id=preregistration.preregistration_id,
        campaign_protocol_fingerprint=computed_fingerprint,
    )
    plan = GateVCampaignPlanV2(
        campaign_plan_semantics_version=GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION,
        campaign_id=campaign_id,
        preregistration_id=preregistration.preregistration_id,
        preregistration_content_hash=preregistration.preregistration_content_hash,
        campaign_protocol_fingerprint=computed_fingerprint,
        research_run_id=research_run.research_run_id,
        research_run_content_hash=research_run_hash,
        dataset_snapshot_id=research_run.dataset_snapshot_id,
        split_plan_id=split_plan.split_plan_id,
        split_plan_fingerprint=split_fingerprint,
        strategy_name=strategy_name,
        base_params=frozen_params,
        search_mode=search_mode,
        search_space_hash=search_space_hash,
        budget_per_fold=budget_per_fold,
        walk_forward_specification=frozen_spec,
        readiness_spec=readiness_spec,
        expected_fold_ids=fold_ids,
        expected_fold_definitions_hash=fold_definitions_hash,
        validation_zone_hash=zone_hash,
        walk_forward_spec_semantics_version=frozen_spec.walk_forward_semantics_version,
        monte_carlo_semantics_version=MONTE_CARLO_SEMANTICS_VERSION,
        parameter_stability_semantics_version=PARAMETER_STABILITY_SEMANTICS_VERSION,
        gate_v_validation_policy_id=policy.validation_policy_id,
        policy_content_hash=policy_hash,
        assessment_semantics_version=preregistration.assessment_semantics_version,
        policy_git_sha=preregistration.policy_git_sha,
    )
    validate_gate_v_campaign_plan_v2_structure(plan)
    return plan


def build_gate_v_campaign_plan_v2(
    *,
    preregistration: GateVPreRegistration,
    research_run: ResearchRun,
    split_plan: DatasetSplitPlan,
    policy: GateVValidationPolicyVersion,
    policy_path: Union[str, Path],
    strategy_name: str,
    base_params: Mapping,
    search_mode: str,
    search_space_hash: str,
    budget_per_fold: int,
    walk_forward_specification: WalkForwardSpecification,
    readiness_spec: Optional[DailyStateReadiness],
    repo_dir: Optional[Union[str, Path]] = None,
) -> "GateVCampaignPlanV2":
    """Construit un `GateVCampaignPlanV2` APRÈS la PreRegistration (ADR 0025 Décision 20).

    Reçoit les VRAIES sources (jamais des hashes dérivés) et refuse fail-closed : PreRegistration
    non intègre ; désaccord avec la PreRegistration ; protocole recalculé != empreinte préenregistrée
    (barrière 1) ; provenance Git HISTORIQUE de la policy invalide (jamais `HEAD == policy_git_sha`
    exigé ici : cette règle ne vaut qu'à la CRÉATION de la PreRegistration) ; puis `campaign_id`
    recalculé depuis les entrées validées (barrière 2)."""
    return _derive_plan(
        preregistration=preregistration, research_run=research_run, split_plan=split_plan,
        policy=policy, policy_path=policy_path, repo_dir=repo_dir, strategy_name=strategy_name,
        base_params=base_params, search_mode=search_mode, search_space_hash=search_space_hash,
        budget_per_fold=budget_per_fold, walk_forward_specification=walk_forward_specification,
        readiness_spec=readiness_spec,
    )


def validate_gate_v_campaign_plan_v2_sources(
    plan: "GateVCampaignPlanV2",
    *,
    preregistration: GateVPreRegistration,
    research_run: ResearchRun,
    split_plan: DatasetSplitPlan,
    policy: GateVValidationPolicyVersion,
    policy_path: Union[str, Path],
    repo_dir: Optional[Union[str, Path]] = None,
) -> None:
    """Revalidation CROSS-SOURCES explicite d'un plan déjà chargé (ADR 0025 Décision 20.10) — étape
    séparée du chargeur pur, jamais cachée dedans. Re-dérive le plan depuis les vraies sources
    (mêmes barrières que le builder, provenance Git historique incluse) en n'empruntant au plan que
    les entrées de protocole, puis exige l'égalité champ à champ. Un plan auto-cohérent mais
    incohérent avec les sources (limite acceptée, Décision 20.6) est refusé ici."""
    validate_gate_v_campaign_plan_v2_structure(plan)
    derived = _derive_plan(
        preregistration=preregistration, research_run=research_run, split_plan=split_plan,
        policy=policy, policy_path=policy_path, repo_dir=repo_dir, strategy_name=plan.strategy_name,
        base_params=plan.base_params, search_mode=plan.search_mode,
        search_space_hash=plan.search_space_hash, budget_per_fold=plan.budget_per_fold,
        walk_forward_specification=plan.walk_forward_specification, readiness_spec=plan.readiness_spec,
    )
    _require_equal(
        plan.campaign_protocol_fingerprint, derived.campaign_protocol_fingerprint,
        "Barrière 1 : plan.campaign_protocol_fingerprint != empreinte recalculée depuis les sources.",
    )
    _require_equal(
        plan.campaign_id, derived.campaign_id,
        "Barrière 2 : plan.campaign_id != expected_campaign_id_v2 recalculé depuis les entrées validées.",
    )
    differing = [
        field.name for field in dataclasses.fields(GateVCampaignPlanV2)
        if getattr(plan, field.name) != getattr(derived, field.name)
    ]
    if differing:
        raise ValueError(f"GateVCampaignPlanV2 incohérent avec ses sources : champ(s) {differing}.")


# ---------------------------------------------------------------------------------------------
# Persistance exclusive + chargeur PUR (Décision 20.6)
# ---------------------------------------------------------------------------------------------

_PLAN_FIELD_NAMES = tuple(field.name for field in dataclasses.fields(GateVCampaignPlanV2))
_SPEC_FIELD_NAMES = frozenset(field.name for field in dataclasses.fields(WalkForwardSpecification))
_READINESS_FIELD_NAMES = frozenset(field.name for field in dataclasses.fields(DailyStateReadiness))


def save_gate_v_campaign_plan_v2(campaign_root: Union[str, Path], plan: "GateVCampaignPlanV2") -> Path:
    """Écrit ``<campaign_root>/<campaign_id>/plan.json`` UNE SEULE FOIS, par création exclusive
    (`save_exclusive()`, `os.O_CREAT|O_EXCL`) — jamais par écrasement atomique : un fichier déjà
    présent lève `FileExistsError`, aucun écrasement silencieux. `campaign_root` (conceptuellement
    `results/job_xxx/gate_v/campaigns/`) est toujours fourni par l'appelant ; ce module ne résout
    jamais lui-même un répertoire global. Le plan est revalidé (structure + barrières internes) AVANT
    toute écriture ; aucun chemin runtime ni timestamp n'est persisté."""
    if not isinstance(campaign_root, (str, Path)) or not str(campaign_root).strip():
        raise ValueError("campaign_root est obligatoire et ne peut pas être vide.")
    validate_gate_v_campaign_plan_v2_structure(plan)
    path = Path(campaign_root) / validate_portable_identifier(plan.campaign_id, "campaign_id") / "plan.json"
    return save_exclusive(path, _plan_record(plan), kind="GateVCampaignPlanV2")


def _spec_from_record(raw) -> WalkForwardSpecification:
    if not isinstance(raw, dict):
        raise ValueError("walk_forward_specification malformée : objet JSON attendu.")
    unknown, missing = set(raw) - _SPEC_FIELD_NAMES, _SPEC_FIELD_NAMES - set(raw)
    if unknown or missing:
        raise ValueError(
            f"walk_forward_specification malformée : champ(s) inconnu(s) {sorted(unknown)}, "
            f"manquant(s) {sorted(missing)}."
        )
    if not isinstance(raw["base_params"], dict):
        raise ValueError("walk_forward_specification.base_params malformé : objet JSON attendu.")
    return WalkForwardSpecification(**{**raw, "base_params": _freeze_json(raw["base_params"])})


def _readiness_from_record(raw) -> Optional[DailyStateReadiness]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("readiness_spec malformée : objet JSON ou null attendu.")
    unknown, missing = set(raw) - _READINESS_FIELD_NAMES, _READINESS_FIELD_NAMES - set(raw)
    if unknown or missing:
        raise ValueError(
            f"readiness_spec malformée : champ(s) inconnu(s) {sorted(unknown)}, manquant(s) {sorted(missing)}."
        )
    return DailyStateReadiness(**raw)


def load_gate_v_campaign_plan_v2(path: Union[str, Path]) -> "GateVCampaignPlanV2":
    """Chargeur V2 STRICT et PUR, fail-closed : l'E/S se limite au fichier `plan.json` lui-même. Ne
    charge AUCUNE PreRegistration/ResearchRun/DatasetSplitPlan/policy, ne lance AUCUNE commande Git
    (aucune E/S croisée cachée — l'intégrité contre les sources externes relève de
    `validate_gate_v_campaign_plan_v2_sources()`, étape explicite distincte).

    Discrimination V1/V2 par le CONTENU : `campaign_plan_semantics_version` absente (vrai plan V1) ou
    de valeur inconnue (V3 futur, corruption) = refus fermé. Jamais de repli vers le chargeur V1,
    jamais de `None` silencieux. Revalide types/formats, `WalkForwardSpecification`/`readiness_spec`
    imbriqués, puis les deux barrières internes (fingerprint de protocole, puis `campaign_id`).

    **Limite acceptée (ADR 0025 Décision 20.3/20.6)** : `preregistration_content_hash` et
    `policy_git_sha` n'entrent ni dans le fingerprint ni dans la préimage du `campaign_id` (formules
    figées) — une falsification ISOLÉE de l'un d'eux, ou une falsification totalement auto-cohérente,
    n'est pas détectable ici. Tout consommateur DOIT appeler
    `validate_gate_v_campaign_plan_v2_sources()` avant de se fier à un plan chargé."""
    data = load_json_tolerant(path)
    if data is None:
        raise ValueError(f"GateVCampaignPlanV2 illisible, invalide ou introuvable : {path}")
    version = data.get("campaign_plan_semantics_version", None)
    if "campaign_plan_semantics_version" not in data:
        raise ValueError(
            "campaign_plan_semantics_version absente : ce fichier n'est pas un GateVCampaignPlanV2 "
            "(plan V1 ou artefact étranger) — refusé, jamais reclassé."
        )
    if version != GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION:
        raise ValueError(
            f"campaign_plan_semantics_version inconnue : attendu {GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION!r}, "
            f"reçu {version!r} — refusé (jamais interprété comme V1 ni V2 par repli silencieux)."
        )
    unknown, missing = set(data) - set(_PLAN_FIELD_NAMES), set(_PLAN_FIELD_NAMES) - set(data)
    if unknown or missing:
        raise ValueError(
            f"GateVCampaignPlanV2 malformé : champ(s) inconnu(s) {sorted(unknown)}, manquant(s) {sorted(missing)}."
        )
    if not isinstance(data["base_params"], dict):
        raise ValueError("base_params malformé : objet JSON attendu.")
    if not isinstance(data["expected_fold_ids"], list):
        raise ValueError("expected_fold_ids malformé : liste JSON attendue.")
    try:
        plan = GateVCampaignPlanV2(**{
            **data,
            "base_params": _freeze_json(data["base_params"]),
            "walk_forward_specification": _spec_from_record(data["walk_forward_specification"]),
            "readiness_spec": _readiness_from_record(data["readiness_spec"]),
            "expected_fold_ids": tuple(data["expected_fold_ids"]),
        })
    except TypeError as exc:
        raise ValueError(f"GateVCampaignPlanV2 malformé : {exc}") from exc
    validate_gate_v_campaign_plan_v2_structure(plan)
    return plan
