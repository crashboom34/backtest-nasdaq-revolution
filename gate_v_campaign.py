"""GATE V campaign preparation and orchestration (ADR 0024).

Niveau A (`build_gate_v_campaign_plan()`) only builds a plan from existing metadata --
deterministic, no execution, no market data. Niveau B (`execute_gate_v_campaign()`, AF-V-08
Slice 3) DOES trigger real execution, but only through explicitly injected collaborators
(`run_walk_forward_fn`/`resume_walk_forward_fn`/`load_market_data_fn`) -- this module itself
never imports an execution engine or opens market data directly.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional, Tuple, Union

import pandas as pd

from atomic_json_store import (
    load_json_tolerant, save_atomic, save_atomic_overwrite, validate_portable_identifier,
)
from dataset_split import (
    assert_oos_window_matches_split, dataset_split_plan_fingerprint, load_dataset_split_plan,
)
from strategy_contracts import DailyStateReadiness
from monte_carlo import run_monte_carlo_simulation
from parameter_stability import analyze_parameter_stability
from validation_run import (
    MONTE_CARLO_SEMANTICS_VERSION,
    PARAMETER_STABILITY_SEMANTICS_VERSION,
    VALIDATION_TYPE_MONTE_CARLO,
    VALIDATION_TYPE_OOS,
    VALIDATION_TYPE_PARAMETER_STABILITY,
    VALIDATION_TYPE_WALK_FORWARD,
    AggregateResult,
    FoldDefinition,
    FoldResult,
    FoldSelection,
    MonteCarloEvidence,
    MonteCarloSpecification,
    OosValidationSpecification,
    ParameterStabilityEvidence,
    ParameterStabilitySpecification,
    build_monte_carlo_specification,
    build_parameter_stability_specification,
    build_validation_run,
    ValidationRun,
    WalkForwardEvidence,
    WalkForwardRunOutcome,
    WalkForwardSpecification,
    load_validation_run,
    save_validation_run,
)
from walk_forward import (
    FoldArtifacts,
    WalkForwardCapturedRunV1,
    build_walk_forward_specification,
    build_walk_forward_validation_run,
    compute_fold_definitions,
    load_walk_forward_captured_run_v1,
    persist_walk_forward_run,
)


_REQUIRED = object()
_SEARCH_SPACE_HASH_RE = re.compile(r"[0-9a-fA-F]{12}\Z")
_SEARCH_MODES = frozenset({"single_var", "cross_zone", "grid", "general"})


class _FrozenDict(dict):
    """JSON-compatible immutable copy of a parameter mapping."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("Les paramètres d'un plan de campagne sont immuables.")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable

    def __deepcopy__(self, memo):
        return self


def _freeze_json(value):
    if isinstance(value, dict):
        if any(not isinstance(key, str) or not key for key in value):
            raise ValueError("base_params doit avoir des clés non vides de type chaîne.")
        return _FrozenDict({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError(f"base_params contient une valeur non JSON ou non finie : {type(value).__name__}.")


@dataclass(frozen=True)
class GateVCampaignPlan:
    """Immutable preparation record; no evidence or scientific verdict lives here."""

    campaign_id: str
    research_run_id: str
    dataset_snapshot_id: str
    split_plan_id: str
    split_plan_path: str
    strategy_name: str
    base_params: dict
    search_mode: str
    search_space_hash: str
    budget_per_fold: int
    walk_forward_specification: WalkForwardSpecification
    readiness_spec: Optional[DailyStateReadiness]
    expected_fold_ids: tuple[str, ...]
    expected_fold_definitions_hash: str
    validation_zone_hash: str
    split_plan_fingerprint: str
    walk_forward_spec_semantics_version: str
    monte_carlo_semantics_version: str
    parameter_stability_semantics_version: str
    monte_carlo_verdict_policy_id: Optional[str]
    parameter_stability_verdict_policy_id: Optional[str]
    walk_forward_verdict_policy_id: Optional[str]
    oos_evidence_validation_run_id: Optional[str]
    oos_evidence_hash: Optional[str]
    oos_evidence_path: Optional[str]


def _fold_definitions_hash(fold_definitions) -> str:
    """Same serialization used at plan-build time (Décision 3) and reused, never duplicated,
    by `execute_gate_v_campaign()`'s pre-execution fold-drift check (Slice 3)."""
    payload = json.dumps(
        [dataclasses.asdict(fold) for fold in fold_definitions],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _required_text(value, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} est obligatoire et ne peut pas être vide.")
    return value


def _optional_id(value, field_name: str) -> Optional[str]:
    if value is None:
        return None
    return validate_portable_identifier(value, field_name)


def build_gate_v_campaign_plan(
    *,
    research_run_id=_REQUIRED,
    dataset_snapshot_id=_REQUIRED,
    split_plan_id=_REQUIRED,
    split_plan_path=_REQUIRED,
    strategy_name=_REQUIRED,
    base_params=_REQUIRED,
    search_mode=_REQUIRED,
    search_space_hash=_REQUIRED,
    budget_per_fold=_REQUIRED,
    geometry=_REQUIRED,
    train_period=_REQUIRED,
    test_period=_REQUIRED,
    step_period=_REQUIRED,
    readiness_spec=_REQUIRED,
    master_seed=_REQUIRED,
    monte_carlo_verdict_policy_id: Optional[str] = None,
    parameter_stability_verdict_policy_id: Optional[str] = None,
    walk_forward_verdict_policy_id: Optional[str] = None,
    oos_evidence_validation_run_id: Optional[str] = None,
    oos_evidence_path: Optional[Union[str, Path]] = None,
) -> GateVCampaignPlan:
    """Validate all explicit scientific inputs before reading any persisted metadata."""
    research_run_id = validate_portable_identifier(research_run_id, "research_run_id")
    dataset_snapshot_id = _required_text(dataset_snapshot_id, "dataset_snapshot_id")
    split_plan_id = validate_portable_identifier(split_plan_id, "split_plan_id")
    strategy_name = _required_text(strategy_name, "strategy_name")
    if not isinstance(base_params, dict) or not base_params:
        raise ValueError("base_params est obligatoire et doit être un dictionnaire non vide.")
    frozen_params = _freeze_json(base_params)
    if not isinstance(search_mode, str) or search_mode not in _SEARCH_MODES:
        raise ValueError(f"search_mode est obligatoire et doit être dans {sorted(_SEARCH_MODES)}.")
    if not isinstance(search_space_hash, str) or not _SEARCH_SPACE_HASH_RE.fullmatch(search_space_hash):
        raise ValueError("search_space_hash est obligatoire et doit être l'empreinte Walk-Forward de 12 chiffres hexadécimaux.")
    if isinstance(budget_per_fold, bool) or not isinstance(budget_per_fold, int) or budget_per_fold <= 0:
        raise ValueError("budget_per_fold est obligatoire et doit être un entier strictement positif.")
    geometry = _required_text(geometry, "geometry")
    train_period = _required_text(train_period, "train_period")
    test_period = _required_text(test_period, "test_period")
    step_period = _required_text(step_period, "step_period")
    if readiness_spec is _REQUIRED or (
        readiness_spec is not None and not isinstance(readiness_spec, DailyStateReadiness)
    ):
        raise ValueError("readiness_spec est obligatoire (DailyStateReadiness ou None explicite).")
    if master_seed is _REQUIRED or (
        master_seed is not None and (isinstance(master_seed, bool) or not isinstance(master_seed, int))
    ):
        raise ValueError("master_seed est obligatoire (entier ou None explicite).")
    if not isinstance(split_plan_path, (str, Path)) or not str(split_plan_path).strip():
        raise ValueError("split_plan_path est obligatoire et ne peut pas être vide.")
    split_plan_path = str(split_plan_path)
    for name, value in (
        ("monte_carlo_verdict_policy_id", monte_carlo_verdict_policy_id),
        ("parameter_stability_verdict_policy_id", parameter_stability_verdict_policy_id),
        ("walk_forward_verdict_policy_id", walk_forward_verdict_policy_id),
    ):
        _optional_id(value, name)
        if value is not None:
            raise ValueError(f"{name}: aucune policy de verdict n'est enregistrée pour cette campagne.")
    oos_evidence_validation_run_id = _optional_id(
        oos_evidence_validation_run_id, "oos_evidence_validation_run_id"
    )
    if (oos_evidence_validation_run_id is None) != (oos_evidence_path is None):
        raise ValueError("oos_evidence_validation_run_id et oos_evidence_path doivent être fournis ensemble.")

    split_plan = load_dataset_split_plan(split_plan_path, strict=True)
    if split_plan is None:
        raise ValueError(f"split_plan_path ne référence aucun DatasetSplitPlan lisible : {split_plan_path}.")
    if split_plan.split_plan_id != split_plan_id:
        raise ValueError("split_plan_id ne correspond pas au DatasetSplitPlan persisté.")
    if split_plan.dataset_snapshot_id != dataset_snapshot_id:
        raise ValueError("dataset_snapshot_id ne correspond pas au DatasetSplitPlan persisté.")
    if split_plan.validation is None:
        raise ValueError("Le DatasetSplitPlan doit contenir une zone validation pour Walk-Forward.")

    oos_evidence_hash = None
    if oos_evidence_path is not None:
        oos_evidence_path = str(oos_evidence_path)
        oos_run = load_validation_run(oos_evidence_path)
        if oos_run is None or (
            oos_run.validation_run_id != oos_evidence_validation_run_id
            or oos_run.validation_type != VALIDATION_TYPE_OOS
            or oos_run.dataset_snapshot_id != dataset_snapshot_id
            or oos_run.split_plan_id != split_plan_id
            or oos_run.strategy_name != strategy_name
        ):
            raise ValueError("La preuve OOS référencée est absente ou étrangère à cette campagne.")
        if (
            oos_run.status != "completed"
            or not isinstance(oos_run.specification, OosValidationSpecification)
            or oos_run.specification.holdout_start != oos_run.evidence.period_start
            or oos_run.specification.holdout_end != oos_run.evidence.period_end
        ):
            raise ValueError("La preuve OOS référencée a un statut ou une fenêtre incohérente.")
        try:
            proof_start = datetime.fromisoformat(oos_run.specification.holdout_start)
            validation_end = datetime.fromisoformat(split_plan.validation.end)
            proof_end = datetime.fromisoformat(oos_run.specification.holdout_end)
            if (proof_start.tzinfo is None or validation_end.tzinfo is None
                    or proof_end.tzinfo is None or proof_start < validation_end
                    or proof_start >= proof_end):
                raise ValueError("La preuve OOS référencée précède la fin de validation.")
        except (TypeError, ValueError) as exc:
            raise ValueError("La preuve OOS référencée a une fenêtre invalide.") from exc
        try:
            assert_oos_window_matches_split(
                split_plan, oos_run.specification.holdout_start,
                oos_run.specification.holdout_end,
            )
        except ValueError as exc:
            raise ValueError("La preuve OOS référencée ne correspond pas au split.") from exc
        oos_payload = json.dumps(
            dataclasses.asdict(oos_run), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
        oos_evidence_hash = hashlib.sha256(oos_payload.encode("utf-8")).hexdigest()

    specification = build_walk_forward_specification(
        base_params=frozen_params,
        geometry=geometry,
        train_period=train_period,
        test_period=test_period,
        step_period=step_period,
        allow_partial_last_fold=False,
        position_transition_policy="flat_each_fold_v1",
        verdict_policy_id=walk_forward_verdict_policy_id,
        master_seed=master_seed,
    )
    # The existing builder copies its input; freeze that copy as well.
    specification = dataclasses.replace(specification, base_params=_freeze_json(specification.base_params))
    fold_definitions = compute_fold_definitions(
        split_plan.validation, specification, readiness_spec,
    )
    expected_fold_ids = tuple(fold.fold_id for fold in fold_definitions)
    expected_fold_definitions_hash = _fold_definitions_hash(fold_definitions)
    zone_payload = json.dumps(
        dataclasses.asdict(split_plan.validation), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False,
    )
    validation_zone_hash = hashlib.sha256(zone_payload.encode("utf-8")).hexdigest()
    fingerprint = {
        "research_run_id": research_run_id,
        "dataset_snapshot_id": dataset_snapshot_id,
        "split_plan_id": split_plan_id,
        "strategy_name": strategy_name,
        "base_params": frozen_params,
        "search_mode": search_mode,
        "search_space_hash": search_space_hash.lower(),
        "budget_per_fold": budget_per_fold,
        "walk_forward_specification": {
            "geometry": specification.geometry,
            "train_period": specification.train_period,
            "test_period": specification.test_period,
            "step_period": specification.step_period,
            "allow_partial_last_fold": specification.allow_partial_last_fold,
            "position_transition_policy": specification.position_transition_policy,
            "master_seed": specification.master_seed,
        },
        "readiness_spec": dataclasses.asdict(readiness_spec) if readiness_spec is not None else None,
        "expected_fold_ids": expected_fold_ids,
        "expected_fold_definitions_hash": expected_fold_definitions_hash,
        "validation_zone_hash": validation_zone_hash,
        "split_plan_fingerprint": dataset_split_plan_fingerprint(split_plan),
        "walk_forward_spec_semantics_version": specification.walk_forward_semantics_version,
        "monte_carlo_semantics_version": MONTE_CARLO_SEMANTICS_VERSION,
        "parameter_stability_semantics_version": PARAMETER_STABILITY_SEMANTICS_VERSION,
        "monte_carlo_verdict_policy_id": monte_carlo_verdict_policy_id,
        "parameter_stability_verdict_policy_id": parameter_stability_verdict_policy_id,
        "walk_forward_verdict_policy_id": walk_forward_verdict_policy_id,
        "oos_evidence_validation_run_id": oos_evidence_validation_run_id,
        "oos_evidence_hash": oos_evidence_hash,
    }
    payload = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    campaign_id = validate_portable_identifier(
        "gate_v_" + hashlib.sha256(payload.encode("utf-8")).hexdigest(), "campaign_id"
    )
    if campaign_id == research_run_id:
        raise ValueError("campaign_id doit être distinct de research_run_id.")
    return GateVCampaignPlan(
        campaign_id=campaign_id,
        research_run_id=research_run_id,
        dataset_snapshot_id=dataset_snapshot_id,
        split_plan_id=split_plan_id,
        split_plan_path=split_plan_path,
        strategy_name=strategy_name,
        base_params=frozen_params,
        search_mode=search_mode,
        search_space_hash=search_space_hash.lower(),
        budget_per_fold=budget_per_fold,
        walk_forward_specification=specification,
        readiness_spec=readiness_spec,
        expected_fold_ids=expected_fold_ids,
        expected_fold_definitions_hash=expected_fold_definitions_hash,
        validation_zone_hash=validation_zone_hash,
        split_plan_fingerprint=dataset_split_plan_fingerprint(split_plan),
        walk_forward_spec_semantics_version=specification.walk_forward_semantics_version,
        monte_carlo_semantics_version=MONTE_CARLO_SEMANTICS_VERSION,
        parameter_stability_semantics_version=PARAMETER_STABILITY_SEMANTICS_VERSION,
        monte_carlo_verdict_policy_id=monte_carlo_verdict_policy_id,
        parameter_stability_verdict_policy_id=parameter_stability_verdict_policy_id,
        walk_forward_verdict_policy_id=walk_forward_verdict_policy_id,
        oos_evidence_validation_run_id=oos_evidence_validation_run_id,
        oos_evidence_hash=oos_evidence_hash,
        oos_evidence_path=str(oos_evidence_path) if oos_evidence_path is not None else None,
    )


def _plan_record(plan: GateVCampaignPlan) -> dict:
    """Convert frozen nested values to plain JSON types for persistence/comparison."""
    data = dataclasses.asdict(plan)
    # Runtime paths belong to the caller's checkout, never to the portable plan.
    data.pop("split_plan_path")
    data.pop("oos_evidence_path")
    return json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False))


def _rebuild_plan(plan: GateVCampaignPlan) -> GateVCampaignPlan:
    specification = plan.walk_forward_specification
    return build_gate_v_campaign_plan(
        research_run_id=plan.research_run_id,
        dataset_snapshot_id=plan.dataset_snapshot_id,
        split_plan_id=plan.split_plan_id,
        split_plan_path=plan.split_plan_path,
        strategy_name=plan.strategy_name,
        base_params=dict(plan.base_params),
        search_mode=plan.search_mode,
        search_space_hash=plan.search_space_hash,
        budget_per_fold=plan.budget_per_fold,
        geometry=specification.geometry,
        train_period=specification.train_period,
        test_period=specification.test_period,
        step_period=specification.step_period,
        readiness_spec=plan.readiness_spec,
        master_seed=specification.master_seed,
        monte_carlo_verdict_policy_id=plan.monte_carlo_verdict_policy_id,
        parameter_stability_verdict_policy_id=plan.parameter_stability_verdict_policy_id,
        walk_forward_verdict_policy_id=plan.walk_forward_verdict_policy_id,
        oos_evidence_validation_run_id=plan.oos_evidence_validation_run_id,
        oos_evidence_path=plan.oos_evidence_path,
    )


def save_gate_v_campaign_plan(campaign_root: Union[str, Path], plan: GateVCampaignPlan) -> Path:
    """Write ``<campaign_root>/<campaign_id>/plan.json`` once, using atomic_json_store."""
    if not isinstance(plan, GateVCampaignPlan):
        raise ValueError("plan doit être un GateVCampaignPlan validé.")
    if not isinstance(campaign_root, (str, Path)) or not str(campaign_root).strip():
        raise ValueError("campaign_root est obligatoire et ne peut pas être vide.")
    if plan != _rebuild_plan(plan):
        raise ValueError("GateVCampaignPlan incohérent ou modifié après sa construction.")
    path = Path(campaign_root) / validate_portable_identifier(plan.campaign_id, "campaign_id") / "plan.json"
    return save_atomic(path, _plan_record(plan), "gate_v_campaign_plan")


def load_gate_v_campaign_plan(
    path: Union[str, Path], *, split_plan_path: Union[str, Path],
    oos_evidence_path: Optional[Union[str, Path]] = None,
) -> Optional[GateVCampaignPlan]:
    """Read a portable plan using caller-supplied paths to its immutable sources."""
    record = load_json_tolerant(path)
    if record is None:
        return None
    try:
        specification = record["walk_forward_specification"]
        readiness = record["readiness_spec"]
        plan = build_gate_v_campaign_plan(
            research_run_id=record["research_run_id"],
            dataset_snapshot_id=record["dataset_snapshot_id"],
            split_plan_id=record["split_plan_id"],
            split_plan_path=split_plan_path,
            strategy_name=record["strategy_name"],
            base_params=record["base_params"],
            search_mode=record["search_mode"],
            search_space_hash=record["search_space_hash"],
            budget_per_fold=record["budget_per_fold"],
            geometry=specification["geometry"],
            train_period=specification["train_period"],
            test_period=specification["test_period"],
            step_period=specification["step_period"],
            readiness_spec=DailyStateReadiness(**readiness) if readiness is not None else None,
            master_seed=specification["master_seed"],
            monte_carlo_verdict_policy_id=record["monte_carlo_verdict_policy_id"],
            parameter_stability_verdict_policy_id=record["parameter_stability_verdict_policy_id"],
            walk_forward_verdict_policy_id=record["walk_forward_verdict_policy_id"],
            oos_evidence_validation_run_id=record["oos_evidence_validation_run_id"],
            oos_evidence_path=oos_evidence_path,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"plan.json invalide : {path}.") from exc
    if Path(path).parent.name != plan.campaign_id or record.get("campaign_id") != plan.campaign_id:
        raise ValueError(f"plan.json incohérent avec sa campagne ou son contrat : {path}.")
    if record != _plan_record(plan):
        raise ValueError(f"plan.json contient des champs inattendus ou modifiés : {path}.")
    return plan


GATE_V_CAMPAIGN_STATUSES = frozenset({
    "NOT_READY", "READY_FOR_EXECUTION", "RUNNING", "EVIDENCE_INCOMPLETE",
    "EVIDENCE_COMPLETE_AWAITING_POLICY", "TECHNICAL_FAILURE",
})


@dataclass(frozen=True)
class GateVCampaignManifest:
    """Factually scoped campaign progress; no scientific verdict or combined score."""

    campaign_id: str
    expected_fold_ids: tuple[str, ...]
    status: str
    oos_evidence_validation_run_id: Optional[str]
    walk_forward_validation_run_id: Optional[str]
    monte_carlo_validation_run_id: Optional[str]
    parameter_stability_validation_run_ids_by_fold: dict[str, str]
    execution_started: bool
    running: bool
    technical_failure_reason: Optional[str]


def gate_v_validation_run_id(
    plan: GateVCampaignPlan, validation_type: str, *, fold_id: Optional[str] = None,
) -> str:
    """Reserve a deterministic campaign-scoped ID for internally produced evidence."""
    if not isinstance(plan, GateVCampaignPlan):
        raise ValueError("plan doit être un GateVCampaignPlan validé.")
    if validation_type not in {
        VALIDATION_TYPE_WALK_FORWARD, VALIDATION_TYPE_MONTE_CARLO,
        VALIDATION_TYPE_PARAMETER_STABILITY,
    }:
        raise ValueError("validation_type doit être une preuve interne GATE V reconnue.")
    if validation_type == VALIDATION_TYPE_PARAMETER_STABILITY:
        if fold_id not in plan.expected_fold_ids:
            raise ValueError("source_fold_id doit appartenir aux folds attendus de la campagne.")
        suffix = f"_{fold_id}"
    elif fold_id is not None:
        raise ValueError("fold_id n'est autorisé que pour Parameter Stability.")
    else:
        suffix = ""
    return validate_portable_identifier(
        f"{plan.campaign_id}_{validation_type}{suffix}", "validation_run_id",
    )


def build_gate_v_campaign_manifest(plan: GateVCampaignPlan) -> GateVCampaignManifest:
    """Create the initial, unexecuted manifest from a validated campaign plan."""
    if not isinstance(plan, GateVCampaignPlan):
        raise ValueError("plan doit être un GateVCampaignPlan validé.")
    return GateVCampaignManifest(
        campaign_id=plan.campaign_id, expected_fold_ids=plan.expected_fold_ids,
        status="READY_FOR_EXECUTION",
        oos_evidence_validation_run_id=plan.oos_evidence_validation_run_id,
        walk_forward_validation_run_id=None, monte_carlo_validation_run_id=None,
        parameter_stability_validation_run_ids_by_fold={},
        execution_started=False, running=False, technical_failure_reason=None,
    )


def _validate_gate_v_manifest_structure(
    plan: GateVCampaignPlan, manifest: GateVCampaignManifest, *, enforce_status_markers: bool = False,
) -> None:
    if not isinstance(plan, GateVCampaignPlan) or not isinstance(manifest, GateVCampaignManifest):
        raise ValueError("plan et manifest doivent être des contrats GATE V validés.")
    if manifest.campaign_id != plan.campaign_id or tuple(manifest.expected_fold_ids) != plan.expected_fold_ids:
        raise ValueError("Le manifeste appartient à une autre campagne ou à d'autres folds.")
    if manifest.status not in GATE_V_CAMPAIGN_STATUSES:
        raise ValueError(f"Statut de campagne inconnu : {manifest.status!r}.")
    if manifest.oos_evidence_validation_run_id != plan.oos_evidence_validation_run_id:
        raise ValueError("La référence OOS du manifeste diffère du plan de campagne.")
    if not isinstance(manifest.execution_started, bool) or not isinstance(manifest.running, bool):
        raise ValueError("Les marqueurs d'exécution du manifeste doivent être booléens.")
    if manifest.running and not manifest.execution_started:
        raise ValueError("Un manifeste RUNNING doit avoir démarré l'exécution.")
    if manifest.technical_failure_reason is not None and (
        not isinstance(manifest.technical_failure_reason, str)
        or not manifest.technical_failure_reason.strip()
        or not manifest.execution_started
    ):
        raise ValueError("technical_failure_reason exige une exécution démarrée et un motif non vide.")
    if manifest.technical_failure_reason is not None and manifest.running:
        raise ValueError("Une erreur technique ne peut pas rester RUNNING.")
    if not isinstance(manifest.parameter_stability_validation_run_ids_by_fold, dict):
        raise ValueError("Le mapping Parameter Stability doit être un dictionnaire fold -> run ID.")
    unexpected = set(manifest.parameter_stability_validation_run_ids_by_fold) - set(plan.expected_fold_ids)
    if unexpected:
        raise ValueError(f"Le manifeste contient des folds étrangers à la campagne : {sorted(unexpected)}.")
    for field_name, run_id, validation_type, fold_id in (
        ("walk_forward_validation_run_id", manifest.walk_forward_validation_run_id,
         VALIDATION_TYPE_WALK_FORWARD, None),
        ("monte_carlo_validation_run_id", manifest.monte_carlo_validation_run_id,
         VALIDATION_TYPE_MONTE_CARLO, None),
        *((f"parameter_stability_validation_run_ids_by_fold[{fold_id}]", run_id,
           VALIDATION_TYPE_PARAMETER_STABILITY, fold_id)
          for fold_id, run_id in manifest.parameter_stability_validation_run_ids_by_fold.items()),
    ):
        if fold_id is not None and run_id is None:
            raise ValueError(f"{field_name} ne peut pas être null pour un fold référencé.")
        if run_id is not None and run_id != gate_v_validation_run_id(
            plan, validation_type, fold_id=fold_id,
        ):
            raise ValueError(f"{field_name} est étranger à cette campagne ou à ce fold.")
    if not manifest.execution_started and (
        manifest.walk_forward_validation_run_id is not None
        or manifest.monte_carlo_validation_run_id is not None
        or manifest.parameter_stability_validation_run_ids_by_fold
    ):
        raise ValueError("Une preuve interne ne peut pas précéder le démarrage de la campagne.")
    if manifest.walk_forward_validation_run_id is None and (
        manifest.monte_carlo_validation_run_id is not None
        or manifest.parameter_stability_validation_run_ids_by_fold
    ):
        raise ValueError("Monte-Carlo et Parameter Stability exigent une preuve source Walk-Forward.")
    if manifest.status == "EVIDENCE_COMPLETE_AWAITING_POLICY" and (
        manifest.oos_evidence_validation_run_id is None
        or manifest.walk_forward_validation_run_id is None
        or manifest.monte_carlo_validation_run_id is None
        or set(manifest.parameter_stability_validation_run_ids_by_fold) != set(plan.expected_fold_ids)
    ):
        raise ValueError("Un manifeste complet doit référencer les quatre catégories et tous les folds.")
    if enforce_status_markers:
        if manifest.technical_failure_reason is not None:
            expected_statuses = {"TECHNICAL_FAILURE"}
        elif manifest.running:
            expected_statuses = {"RUNNING"}
        elif not manifest.execution_started:
            expected_statuses = {"READY_FOR_EXECUTION"}
        else:
            expected_statuses = {"EVIDENCE_INCOMPLETE", "EVIDENCE_COMPLETE_AWAITING_POLICY"}
        if manifest.status not in expected_statuses:
            raise ValueError("Le statut du manifeste contredit ses marqueurs d'exécution.")


def _evidence_field(value, name: str):
    """Nested ValidationRun records may be dataclasses in memory or dicts after JSON load."""
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _validate_scoped_run(
    plan: GateVCampaignPlan, run_id: str, validation_type: str,
    evidence_by_validation_run_id: Mapping[str, ValidationRun],
) -> Optional[ValidationRun]:
    run = evidence_by_validation_run_id.get(run_id)
    if run is None:
        return None
    if not isinstance(run, ValidationRun) or run.validation_run_id != run_id:
        raise ValueError(f"validation_run_id {run_id!r} incohérent ou étranger à la campagne.")
    if (
        run.validation_type != validation_type
        or run.dataset_snapshot_id != plan.dataset_snapshot_id
        or run.split_plan_id != plan.split_plan_id
        or run.strategy_name != plan.strategy_name
        or run.status != "completed"
    ):
        raise ValueError(f"Preuve {run_id!r} de type, statut ou provenance étrangère à la campagne.")
    if validation_type != VALIDATION_TYPE_OOS and run.research_run_id != plan.research_run_id:
        raise ValueError(f"Preuve {run_id!r} issue d'un autre ResearchRun/campagne.")
    if validation_type != VALIDATION_TYPE_OOS and _evidence_field(
        run.evidence, "scientific_verdict"
    ) != "INCONCLUSIVE":
        raise ValueError(f"Preuve {run_id!r} avec verdict scientifique sans policy enregistrée.")
    if validation_type in (VALIDATION_TYPE_WALK_FORWARD, VALIDATION_TYPE_MONTE_CARLO) and (
        run.strategy_params != plan.base_params
    ):
        raise ValueError(f"Paramètres de stratégie {validation_type} étrangers au plan.")
    return run


def _walk_forward_complete(plan: GateVCampaignPlan, run: ValidationRun) -> bool:
    if not isinstance(run.specification, WalkForwardSpecification) or run.specification != plan.walk_forward_specification:
        raise ValueError("La spécification Walk-Forward diffère du plan de campagne.")
    if not isinstance(run.evidence, WalkForwardEvidence):
        raise ValueError("Preuve Walk-Forward de type incohérent.")
    evidence = run.evidence
    if evidence.execution_status != "completed" or evidence.aggregate is None:
        return False
    folds = evidence.fold_results
    if tuple(_evidence_field(fold, "fold_id") for fold in folds) != plan.expected_fold_ids:
        return False
    for fold in folds:
        fold_id = _evidence_field(fold, "fold_id")
        definition = _evidence_field(fold, "definition")
        selection = _evidence_field(fold, "selection")
        n_trades = _evidence_field(fold, "n_trades")
        zero_trade = _evidence_field(fold, "zero_trade_oos")
        if (not isinstance(n_trades, int) or isinstance(n_trades, bool) or n_trades < 0
                or not isinstance(zero_trade, bool) or zero_trade != (n_trades == 0)):
            raise ValueError(f"Fold {fold_id} : compte ou indicateur zéro trade TEST incohérent.")
        if n_trades == 0 and (
            _evidence_field(fold, "net_ret_pct") != 0.0
            or any(_evidence_field(fold, name) is not None for name in (
                "profit_factor", "win_rate", "expectancy",
            ))
        ):
            raise ValueError(f"Fold {fold_id} : métrique inventée sur zéro trade TEST.")
        if (
            _evidence_field(definition, "fold_id") != fold_id
            or _evidence_field(selection, "fold_id") != fold_id
            or _evidence_field(selection, "rank_in_train") != 1
            or _evidence_field(selection, "search_space_hash") != plan.search_space_hash
            or _evidence_field(selection, "algorithm") != plan.search_mode
            or not isinstance(_evidence_field(selection, "train_candidates_evaluated"), int)
            or not 0 < _evidence_field(selection, "train_candidates_evaluated") <= plan.budget_per_fold
        ):
            raise ValueError(f"Top-1 TRAIN ou search_space_hash incohérent pour {fold_id}.")
    definitions = [_evidence_field(fold, "definition") for fold in folds]
    if any(definition is None for definition in definitions):
        return False
    payload = json.dumps(
        [dataclasses.asdict(item) if dataclasses.is_dataclass(item) else item for item in definitions],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != plan.expected_fold_definitions_hash:
        raise ValueError("Les bornes Walk-Forward ne correspondent pas aux folds de la campagne.")
    aggregate = evidence.aggregate
    if _evidence_field(aggregate, "n_folds") != len(plan.expected_fold_ids):
        return False
    if _evidence_field(aggregate, "total_oos_trades") != sum(
        _evidence_field(fold, "n_trades") for fold in folds
    ):
        raise ValueError("Le compte des trades Walk-Forward diffère de l'agrégat.")
    if _evidence_field(aggregate, "n_folds_zero_trade") != sum(
        _evidence_field(fold, "zero_trade_oos") for fold in folds
    ):
        raise ValueError("Le compte des folds zéro trade Walk-Forward diffère de l'agrégat.")
    return True


def _parameter_stability_quality(
    plan: GateVCampaignPlan, run: ValidationRun, fold_id: str, wf_id: str,
    source_fold_result=None,
) -> bool:
    specification, evidence = run.specification, run.evidence
    if not isinstance(specification, ParameterStabilitySpecification) or not isinstance(
        evidence, ParameterStabilityEvidence,
    ):
        raise ValueError("Preuve Parameter Stability de type incohérent.")
    if (
        specification != build_parameter_stability_specification(
            wf_id, plan.search_mode, True, source_fold_id=fold_id,
        )
        or evidence.search_mode != plan.search_mode
    ):
        raise ValueError(f"Provenance Parameter Stability incorrecte pour le fold {fold_id}.")
    if evidence.execution_status != "completed":
        return False
    if source_fold_result is not None:
        selection = _evidence_field(source_fold_result, "selection")
        if (
            selection is None
            or evidence.best_params != _evidence_field(selection, "selected_params")
            or evidence.best_score != _evidence_field(selection, "score_train")
            or evidence.n_candidates_total != _evidence_field(selection, "train_candidates_evaluated")
        ):
            raise ValueError(f"Parameter Stability {fold_id} ne correspond pas au Top-1/pool TRAIN du fold.")
    totals = evidence.n_neighbors_total_by_param
    rejected = evidence.n_neighbors_rejected_by_param
    if not isinstance(totals, dict) or not isinstance(rejected, dict):
        raise ValueError(f"Compteurs de voisins invalides pour le fold {fold_id}.")
    for param, total in totals.items():
        rejection = rejected.get(param)
        if (
            not isinstance(total, int) or isinstance(total, bool) or total < 0
            or not isinstance(rejection, int) or isinstance(rejection, bool)
            or rejection < 0 or rejection > total
            or total > evidence.n_candidates_total - 1
        ):
            raise ValueError(f"Compteurs de voisins incohérents pour le fold {fold_id}.")
    if set(rejected) != set(totals):
        raise ValueError(f"Compteurs de voisins incomplets pour le fold {fold_id}.")
    usable = [param for param, total in totals.items() if total - rejected[param] > 0]
    if evidence.neighborhood_applicability != "local_neighborhood_available" or not usable:
        return False
    for param in usable:
        for summaries in (evidence.degradation_by_param, evidence.degradation_points_by_param):
            summary = summaries.get(param) if isinstance(summaries, dict) else None
            if summary is None or any(
                not isinstance(_evidence_field(summary, percentile), (int, float))
                or not math.isfinite(_evidence_field(summary, percentile))
                for percentile in ("p5", "p25", "p50", "p75", "p95")
            ):
                return False
    return True


def _monte_carlo_complete(
    plan: GateVCampaignPlan, wf: Optional[ValidationRun], mc: ValidationRun,
) -> bool:
    """Extrait de `derive_gate_v_campaign_status()` (Slice 2, comportement inchangé — pur
    extract-method) pour être réutilisable comme garde de pré-persistance par
    `execute_gate_v_campaign()` (Slice 4) avant d'écrire une `ValidationRun` Monte-Carlo
    immuable — jamais réimplémentée séparément."""
    if not isinstance(mc.specification, MonteCarloSpecification) or not isinstance(mc.evidence, MonteCarloEvidence):
        raise ValueError("Preuve Monte-Carlo de type incohérent.")
    if mc.specification != build_monte_carlo_specification(
        gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD), True,
    ):
        raise ValueError("Provenance Monte-Carlo étrangère à la campagne Walk-Forward.")
    if wf is not None and wf.evidence.aggregate is not None:
        expected_trades = _evidence_field(wf.evidence.aggregate, "total_oos_trades")
        if (mc.evidence.n_input_trades != expected_trades
                or mc.evidence.zero_trade_input != (expected_trades == 0)):
            raise ValueError("Le compte des trades Monte-Carlo diffère du Walk-Forward.")
    if mc.evidence.zero_trade_input and any(
        getattr(mc.evidence, field_name) is not None for field_name in (
            "observed_net_ret_pct", "observed_max_dd_trade_close_basis_pct",
            "observed_lag1_autocorrelation", "observed_longest_losing_streak",
            "sequence_risk_max_dd_trade_close_basis_pct",
            "sequence_risk_longest_losing_streak",
            "sampling_uncertainty_net_ret_pct",
            "sampling_uncertainty_max_dd_trade_close_basis_pct",
        )
    ):
        raise ValueError("Monte-Carlo à zéro trade ne peut contenir de métrique inventée.")
    mc_complete = mc.evidence.execution_status == "completed"
    if not mc.evidence.zero_trade_input:
        observed = (
            mc.evidence.observed_net_ret_pct,
            mc.evidence.observed_max_dd_trade_close_basis_pct,
        )
        distributions = (
            mc.evidence.sequence_risk_max_dd_trade_close_basis_pct,
            mc.evidence.sequence_risk_longest_losing_streak,
            mc.evidence.sampling_uncertainty_net_ret_pct,
            mc.evidence.sampling_uncertainty_max_dd_trade_close_basis_pct,
        )
        mc_complete = mc_complete and (
            mc.evidence.n_input_trades > 0
            and all(isinstance(value, (int, float)) and math.isfinite(value) for value in observed)
            and isinstance(mc.evidence.observed_longest_losing_streak, int)
            and mc.evidence.observed_longest_losing_streak >= 0
            and all(summary is not None and all(
                isinstance(_evidence_field(summary, percentile), (int, float))
                and math.isfinite(_evidence_field(summary, percentile))
                for percentile in ("p5", "p25", "p50", "p75", "p95")
            ) for summary in distributions)
        )
    return mc_complete


def derive_gate_v_campaign_status(
    plan: GateVCampaignPlan, manifest: GateVCampaignManifest,
    evidence_by_validation_run_id: Mapping[str, ValidationRun],
) -> str:
    """Pure structural status; never reads files or derives a scientific PASS/FAIL."""
    _validate_gate_v_manifest_structure(plan, manifest)
    if not isinstance(evidence_by_validation_run_id, Mapping):
        raise ValueError("evidence_by_validation_run_id doit être un mapping de ValidationRun.")
    oos_id = manifest.oos_evidence_validation_run_id
    wf_id = manifest.walk_forward_validation_run_id
    mc_id = manifest.monte_carlo_validation_run_id
    oos = (_validate_scoped_run(plan, oos_id, VALIDATION_TYPE_OOS, evidence_by_validation_run_id)
           if oos_id is not None else None)
    wf = (_validate_scoped_run(plan, wf_id, VALIDATION_TYPE_WALK_FORWARD, evidence_by_validation_run_id)
          if wf_id is not None else None)
    mc = (_validate_scoped_run(plan, mc_id, VALIDATION_TYPE_MONTE_CARLO, evidence_by_validation_run_id)
          if mc_id is not None else None)
    if oos is not None and plan.oos_evidence_hash is not None:
        payload = json.dumps(
            dataclasses.asdict(oos), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != plan.oos_evidence_hash:
            raise ValueError("La preuve OOS ne correspond plus à l'empreinte du plan de campagne.")
    wf_complete = _walk_forward_complete(plan, wf) if wf is not None else False
    mc_complete = _monte_carlo_complete(plan, wf, mc) if mc is not None else False
    ps_complete = set(manifest.parameter_stability_validation_run_ids_by_fold) == set(plan.expected_fold_ids)
    source_folds = {
        _evidence_field(fold, "fold_id"): fold for fold in wf.evidence.fold_results
    } if wf is not None and isinstance(wf.evidence, WalkForwardEvidence) else {}
    for fold_id, ps_id in manifest.parameter_stability_validation_run_ids_by_fold.items():
        ps = _validate_scoped_run(
            plan, ps_id,
            VALIDATION_TYPE_PARAMETER_STABILITY, evidence_by_validation_run_id,
        )
        if ps is None or not _parameter_stability_quality(
            plan, ps, fold_id, gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD),
            source_folds.get(fold_id),
        ):
            ps_complete = False
    if manifest.technical_failure_reason is not None:
        return "TECHNICAL_FAILURE"
    if manifest.running:
        return "RUNNING"
    if not manifest.execution_started:
        return "READY_FOR_EXECUTION"
    if oos is None or not wf_complete or not mc_complete or not ps_complete:
        return "EVIDENCE_INCOMPLETE"
    return "EVIDENCE_COMPLETE_AWAITING_POLICY"


def _load_manifest_proofs(
    plan: GateVCampaignPlan, manifest: GateVCampaignManifest, campaign_dir: Path,
) -> tuple[dict[str, ValidationRun], dict[str, Path]]:
    """Reload every referenced immutable proof from its campaign-scoped location."""
    paths = {}
    if manifest.oos_evidence_validation_run_id is not None:
        if plan.oos_evidence_path is None:
            raise ValueError("Chemin de la preuve OOS absent du plan chargé.")
        paths[manifest.oos_evidence_validation_run_id] = Path(plan.oos_evidence_path)
    internal_ids = [
        manifest.walk_forward_validation_run_id,
        manifest.monte_carlo_validation_run_id,
        *manifest.parameter_stability_validation_run_ids_by_fold.values(),
    ]
    for run_id in internal_ids:
        if run_id is not None:
            paths[run_id] = campaign_dir / "validations" / run_id / "validation_run.json"
    runs = {}
    for run_id, path in paths.items():
        run = load_validation_run(path)
        if run is None or run.validation_run_id != run_id:
            raise ValueError(f"Fichier de preuve ValidationRun absent ou incohérent : {path}.")
        runs[run_id] = run
    return runs, paths


def save_gate_v_campaign_manifest(
    campaign_root: Union[str, Path], plan: GateVCampaignPlan,
    manifest: GateVCampaignManifest,
    *, evidence_by_validation_run_id: Optional[Mapping[str, ValidationRun]] = None,
    evidence_paths_by_validation_run_id: Optional[Mapping[str, Union[str, Path]]] = None,
) -> Path:
    """Atomically replace only this plan's campaign manifest after structural checks."""
    _validate_gate_v_manifest_structure(plan, manifest, enforce_status_markers=True)
    if plan != _rebuild_plan(plan):
        raise ValueError("Le plan de campagne est incohérent ou forgé.")
    if not isinstance(campaign_root, (str, Path)) or not str(campaign_root).strip():
        raise ValueError("campaign_root est obligatoire et ne peut pas être vide.")
    path = Path(campaign_root) / plan.campaign_id / "manifest.json"
    if load_json_tolerant(path.parent / "plan.json") != _plan_record(plan):
        raise ValueError("plan.json validé doit être persisté avant le manifeste.")
    persisted_runs, canonical_paths = _load_manifest_proofs(plan, manifest, path.parent)
    actual_status = derive_gate_v_campaign_status(plan, manifest, persisted_runs)
    if actual_status != manifest.status:
        raise ValueError("Le statut du manifeste contredit ses preuves persistées.")
    if manifest.status == "EVIDENCE_COMPLETE_AWAITING_POLICY":
        if evidence_by_validation_run_id is None or derive_gate_v_campaign_status(
            plan, manifest, evidence_by_validation_run_id,
        ) != "EVIDENCE_COMPLETE_AWAITING_POLICY":
            raise ValueError("Le statut complet exige toutes les preuves vérifiées en mémoire.")
        required_ids = {
            manifest.oos_evidence_validation_run_id,
            manifest.walk_forward_validation_run_id,
            manifest.monte_carlo_validation_run_id,
            *manifest.parameter_stability_validation_run_ids_by_fold.values(),
        }
        if not isinstance(evidence_paths_by_validation_run_id, Mapping) or not required_ids.issubset(
            evidence_paths_by_validation_run_id
        ):
            raise ValueError("Le statut complet exige les fichiers de preuve persistés.")
        for run_id in required_ids:
            proof_path = Path(evidence_paths_by_validation_run_id[run_id])
            if proof_path.resolve() != canonical_paths[run_id].resolve():
                raise ValueError(f"Chemin de preuve non canonique pour {run_id}.")
            persisted = persisted_runs[run_id]
            expected_run = evidence_by_validation_run_id.get(run_id)
            expected_record = (
                json.loads(json.dumps(dataclasses.asdict(expected_run), ensure_ascii=False))
                if isinstance(expected_run, ValidationRun) else None
            )
            if persisted is None or load_json_tolerant(proof_path) != expected_record:
                raise ValueError(f"La preuve persistée {run_id} est absente ou différente.")
    if path.exists():
        previous = load_gate_v_campaign_manifest(path, plan)
        if previous is None:
            raise ValueError("Le manifeste existant est illisible ; écrasement refusé.")
        if previous.execution_started and not manifest.execution_started:
            raise ValueError("Une campagne démarrée ne peut pas revenir à READY_FOR_EXECUTION.")
        for name in ("walk_forward_validation_run_id", "monte_carlo_validation_run_id"):
            old_id, new_id = getattr(previous, name), getattr(manifest, name)
            if old_id is not None and new_id != old_id:
                raise ValueError(f"La référence de preuve {name} ne peut pas être effacée ou changée.")
        for fold_id, old_id in previous.parameter_stability_validation_run_ids_by_fold.items():
            if manifest.parameter_stability_validation_run_ids_by_fold.get(fold_id) != old_id:
                raise ValueError(f"La référence de preuve Parameter Stability {fold_id} ne peut pas être effacée.")
    record = dataclasses.asdict(manifest)
    return save_atomic_overwrite(path, record, "gate_v_campaign_manifest")


def load_gate_v_campaign_manifest(
    path: Union[str, Path], plan: GateVCampaignPlan,
) -> Optional[GateVCampaignManifest]:
    """Load a manifest and reject foreign campaign/fold IDs before any execution."""
    record = load_json_tolerant(path)
    if record is None:
        if Path(path).exists():
            raise ValueError(f"manifest.json existant illisible ou corrompu : {path}.")
        return None
    try:
        manifest = GateVCampaignManifest(**record)
        _validate_gate_v_manifest_structure(plan, manifest, enforce_status_markers=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"manifest.json invalide ou étranger à la campagne : {path}.") from exc
    if Path(path).parent.name != plan.campaign_id or Path(path).name != "manifest.json":
        raise ValueError("manifest.json est situé hors du répertoire de sa campagne.")
    if plan != _rebuild_plan(plan):
        raise ValueError("Le plan de campagne chargé est incohérent ou forgé.")
    if load_json_tolerant(Path(path).parent / "plan.json") != _plan_record(plan):
        raise ValueError("plan.json validé doit être persisté avec manifest.json.")
    persisted_runs, _paths = _load_manifest_proofs(plan, manifest, Path(path).parent)
    if derive_gate_v_campaign_status(plan, manifest, persisted_runs) != manifest.status:
        raise ValueError("Le statut du manifeste ne correspond plus aux preuves persistées.")
    return dataclasses.replace(manifest, expected_fold_ids=tuple(manifest.expected_fold_ids))


# ══════════════════════════════════════════════════════════════════════════════
# Niveau B (ADR 0024 Décision 5) — AF-V-08 Slice 3 : PHASE WALK-FORWARD UNIQUEMENT.
# Monte-Carlo/Parameter Stability restent hors scope (slices suivantes) — ce câblage ne peut
# donc jamais, à lui seul, faire passer une campagne à EVIDENCE_COMPLETE_AWAITING_POLICY, sauf si
# ces preuves existent déjà, produites hors de cette exécution (jamais fabriquées ici).
# ══════════════════════════════════════════════════════════════════════════════

# Contrat de chemins Walk-Forward (ADR 0021 Décision 12, ADR 0024 Décision 6/8/amendement AF-V-08)
# — dupliqué ici en littéraux documentés plutôt qu'importé depuis les noms privés de
# `walk_forward.py` (jamais réimplémenté : ce sont les MÊMES chaînes, jamais une seconde
# convention inventée).
_WALK_FORWARD_DIRNAME = "walk_forward"
_WALK_FORWARD_CHECKPOINT_DIRNAME = ".gate_v_checkpoints_v1"
_WALK_FORWARD_MANIFEST_FILENAME = "manifest.json"
_WALK_FORWARD_AGGREGATE_FILENAME = "aggregate.json"
_WALK_FORWARD_FOLDS_DIRNAME = "folds"
_WALK_FORWARD_TEST_RESULT_FILENAME = "test_result.json"
_WALK_FORWARD_OOS_TRADES_FILENAME = "oos_trades.csv"
_VALIDATIONS_DIRNAME = "validations"
_VALIDATION_RUN_FILENAME = "validation_run.json"


def _reload_persisted_walk_forward_outcome(
    output_dir: Path, expected_fold_ids: Tuple[str, ...],
) -> Tuple[WalkForwardRunOutcome, AggregateResult]:
    """Relit un run Walk-Forward DÉJÀ persisté par `persist_walk_forward_run()` (ADR 0021
    Décision 12, EXISTANTE, jamais rappelée ici) — aucun second calcul, aucune API de capture V1
    rappelée. La cohérence scientifique complète (Top-1, search_space_hash, zéro-trade, hash des
    définitions, totaux d'agrégat) est revérifiée ENSUITE par `_walk_forward_complete()`, jamais
    supposée ici : cette fonction ne fait que désérialiser des JSON déjà écrits."""
    fold_results = []
    for fold_id in expected_fold_ids:
        path = (
            output_dir / _WALK_FORWARD_FOLDS_DIRNAME / fold_id / _WALK_FORWARD_TEST_RESULT_FILENAME
        )
        raw = load_json_tolerant(path)
        if raw is None:
            raise ValueError(
                f"Persistance Walk-Forward annoncée complète mais {path} absent ou illisible."
            )
        try:
            definition = FoldDefinition(**raw["definition"])
            selection = FoldSelection(**raw["selection"])
            remainder = {k: v for k, v in raw.items() if k not in ("definition", "selection")}
            fold_results.append(FoldResult(definition=definition, selection=selection, **remainder))
        except (KeyError, TypeError) as exc:
            raise ValueError(f"{path} : contenu incohérent avec FoldResult.") from exc
    aggregate_path = output_dir / _WALK_FORWARD_AGGREGATE_FILENAME
    aggregate_raw = load_json_tolerant(aggregate_path)
    if aggregate_raw is None:
        raise ValueError(f"{aggregate_path} annoncé présent mais illisible.")
    try:
        aggregate = AggregateResult(**aggregate_raw)
    except TypeError as exc:
        raise ValueError(f"{aggregate_path} : contenu incohérent avec AggregateResult.") from exc
    return WalkForwardRunOutcome(fold_results=tuple(fold_results), stopped_early=False), aggregate


def _validate_captured_run(
    plan: GateVCampaignPlan, captured: WalkForwardCapturedRunV1, expected_validation_run_id: str,
) -> None:
    """Revalide strictement un `WalkForwardCapturedRunV1` retourné par un collaborateur injecté
    — jamais fait confiance aveuglément avant persistance (ADR 0024 Décision 5)."""
    if not isinstance(captured, WalkForwardCapturedRunV1):
        raise ValueError(
            "run_walk_forward_fn/resume_walk_forward_fn doit retourner un WalkForwardCapturedRunV1."
        )
    if captured.validation_run_id != expected_validation_run_id:
        raise ValueError(
            f"validation_run_id retourné {captured.validation_run_id!r} != attendu "
            f"{expected_validation_run_id!r} — preuve étrangère à cette campagne refusée."
        )
    if captured.aggregate is None:
        raise ValueError("WalkForwardCapturedRunV1.aggregate est None — jamais persisté comme preuve.")
    got_ids = tuple(result.fold_id for result in captured.outcome.fold_results)
    expected_prefix = plan.expected_fold_ids[: len(got_ids)]
    if got_ids != expected_prefix:
        raise ValueError(
            f"Folds retournés {got_ids!r} ne correspondent pas au préfixe attendu "
            f"{expected_prefix!r} de la campagne — fold absent, supplémentaire, dupliqué ou "
            "mal ordonné."
        )
    if not captured.outcome.stopped_early and got_ids != plan.expected_fold_ids:
        raise ValueError(
            f"outcome.stopped_early=False mais seuls {got_ids!r} sur "
            f"{plan.expected_fold_ids!r} attendus sont présents — un outcome partiel doit "
            "être signalé stopped_early=True, jamais présenté comme complet."
        )
    artifact_ids = tuple(artifacts.fold_id for artifacts in captured.fold_artifacts)
    if artifact_ids != got_ids:
        raise ValueError(
            "fold_artifacts et outcome.fold_results divergent — jamais réassociés silencieusement."
        )


def _run_walk_forward_phase(
    plan: GateVCampaignPlan, campaign_root: Union[str, Path], campaign_dir: Path,
    manifest: GateVCampaignManifest, split_plan, base_config, data_manifest_path,
    load_market_data_fn, run_walk_forward_fn, resume_walk_forward_fn, progress_cb, stop_flag_fn,
) -> GateVCampaignManifest:
    """AF-V-08 Slice 3 — phase Walk-Forward (ADR 0024 Décision 5/6/8, comportement inchangé,
    extraite telle quelle de `execute_gate_v_campaign()` pour la Slice 4). Retourne soit un
    manifeste avec `walk_forward_validation_run_id` attaché, soit un manifeste EN PAUSE
    (`stopped_early`, `walk_forward_validation_run_id` toujours `None`) — l'appelant ne tente
    JAMAIS Monte-Carlo tant que ce second cas se produit."""
    running_manifest = dataclasses.replace(
        manifest, execution_started=True, running=True, status="RUNNING",
    )
    save_gate_v_campaign_manifest(campaign_root, plan, running_manifest)

    wf_validation_run_id = gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
    wf_output_dir = campaign_dir / _WALK_FORWARD_DIRNAME
    wf_run_path = (
        campaign_dir / _VALIDATIONS_DIRNAME / wf_validation_run_id / _VALIDATION_RUN_FILENAME
    )
    existing_run = load_validation_run(wf_run_path)
    if existing_run is not None and existing_run.validation_run_id != wf_validation_run_id:
        raise ValueError(f"ValidationRun persistée à {wf_run_path} étrangère à cette campagne.")

    if existing_run is not None:
        # Reprise sans recalcul (ADR 0024 §5 de la mission précédente) : save_validation_run()
        # a pu réussir avant un crash antérieur à la mise à jour du manifeste — la preuve
        # déterministe déjà persistée est retrouvée et rattachée, jamais recalculée.
        wf_run = existing_run
    else:
        checkpoint_manifest_path = (
            wf_output_dir / _WALK_FORWARD_CHECKPOINT_DIRNAME / _WALK_FORWARD_MANIFEST_FILENAME
        )
        aggregate_path = wf_output_dir / _WALK_FORWARD_AGGREGATE_FILENAME
        if aggregate_path.is_file():
            outcome, aggregate = _reload_persisted_walk_forward_outcome(
                wf_output_dir, plan.expected_fold_ids,
            )
        else:
            df = load_market_data_fn()
            call_fn = resume_walk_forward_fn if checkpoint_manifest_path.is_file() else run_walk_forward_fn
            captured = call_fn(
                split_plan.validation, plan.walk_forward_specification, plan.readiness_spec,
                base_config, df,
                data_manifest_path=data_manifest_path, output_dir=wf_output_dir,
                progress_cb=progress_cb, stop_flag_fn=stop_flag_fn,
                validation_run_id=wf_validation_run_id,
            )
            _validate_captured_run(plan, captured, wf_validation_run_id)
            if captured.outcome.stopped_early:
                paused_manifest = dataclasses.replace(running_manifest, running=False)
                persisted_runs, _paths = _load_manifest_proofs(plan, paused_manifest, campaign_dir)
                status = derive_gate_v_campaign_status(plan, paused_manifest, persisted_runs)
                paused_manifest = dataclasses.replace(paused_manifest, status=status)
                save_gate_v_campaign_manifest(campaign_root, plan, paused_manifest)
                return paused_manifest
            persist_walk_forward_run(
                captured.outcome, captured.fold_artifacts, captured.aggregate,
                plan.walk_forward_specification, base_config, data_manifest_path, wf_output_dir,
                validation_run_id=wf_validation_run_id,
            )
            outcome, aggregate = captured.outcome, captured.aggregate
        wf_run = build_walk_forward_validation_run(
            outcome, aggregate, plan.walk_forward_specification, split_plan, plan.research_run_id,
            wf_validation_run_id, plan.strategy_name, dict(plan.base_params),
        )
        if not _walk_forward_complete(plan, wf_run):
            raise ValueError(
                f"Preuve Walk-Forward construite pour {plan.campaign_id!r} incomplète ou "
                "incohérente avec le plan de campagne — refus de persister (ADR 0024 Décision 13)."
            )
        save_validation_run(wf_run_path, wf_run)

    final_manifest = dataclasses.replace(
        running_manifest, walk_forward_validation_run_id=wf_validation_run_id, running=False,
    )
    persisted_runs, evidence_paths = _load_manifest_proofs(plan, final_manifest, campaign_dir)
    status = derive_gate_v_campaign_status(plan, final_manifest, persisted_runs)
    final_manifest = dataclasses.replace(final_manifest, status=status)
    save_gate_v_campaign_manifest(
        campaign_root, plan, final_manifest,
        evidence_by_validation_run_id=persisted_runs,
        evidence_paths_by_validation_run_id=evidence_paths,
    )
    return final_manifest


def _load_complete_walk_forward_run(
    plan: GateVCampaignPlan, manifest: GateVCampaignManifest, campaign_dir: Path,
) -> ValidationRun:
    """Précondition absolue Monte-Carlo (ADR 0024 §3, amendement AF-V-08) : recharge et
    revalide strictement la ValidationRun Walk-Forward de CETTE campagne — jamais une preuve
    partielle/étrangère/incohérente. Réutilise `_validate_scoped_run()`/`_walk_forward_complete()`
    (Slice 2), jamais réimplémentés."""
    wf_id = manifest.walk_forward_validation_run_id
    if wf_id is None:
        raise ValueError(
            "Aucune preuve Walk-Forward rattachée à cette campagne — Monte-Carlo refusé "
            "(ADR 0024 §3)."
        )
    wf_path = campaign_dir / _VALIDATIONS_DIRNAME / wf_id / _VALIDATION_RUN_FILENAME
    wf_run = load_validation_run(wf_path)
    if wf_run is None:
        raise ValueError(
            f"ValidationRun Walk-Forward {wf_id!r} absente ou illisible à {wf_path} — "
            "Monte-Carlo refusé (ADR 0024 §3)."
        )
    validated = _validate_scoped_run(plan, wf_id, VALIDATION_TYPE_WALK_FORWARD, {wf_id: wf_run})
    if validated is None or not _walk_forward_complete(plan, validated):
        raise ValueError(
            f"ValidationRun Walk-Forward {wf_id!r} incomplète, étrangère ou incohérente avec "
            "cette campagne — Monte-Carlo refusé (ADR 0024 §3)."
        )
    return validated


def _validate_trades_within_fold_test_window(
    fold_id: str, definition, fold_trades: "pd.DataFrame",
) -> None:
    """ADR 0021 Décision 4 : chaque trade TEST appartient à `[effective_boundary,
    effective_test_end)` de SON fold — les fenêtres TEST ne se chevauchant JAMAIS entre folds
    (même Décision, code gelé, jamais revérifié ici), cette borne PAR FOLD suffit à exclure toute
    duplication inter-fold sans identité de trade forte (`oos_trades.csv` ne porte aucune colonne
    d'identifiant, `net_ret_pct` seul n'identifie jamais un trade — deux trades distincts peuvent
    légitimement avoir le même rendement)."""
    if fold_trades.empty:
        return
    if "date_entree" not in fold_trades.columns:
        raise ValueError(f"Fold {fold_id!r} : colonne date_entree absente des trades TEST.")
    effective_boundary = _evidence_field(definition, "effective_boundary")
    effective_test_end = _evidence_field(definition, "effective_test_end")
    boundary = datetime.fromisoformat(effective_boundary)
    test_end = datetime.fromisoformat(effective_test_end)
    for index, raw in enumerate(fold_trades["date_entree"]):
        if raw is None or (isinstance(raw, float) and math.isnan(raw)):
            raise ValueError(f"Fold {fold_id!r}, trade {index} : date_entree absente.")
        try:
            entry = datetime.fromisoformat(str(raw))
        except ValueError as exc:
            raise ValueError(
                f"Fold {fold_id!r}, trade {index} : date_entree={raw!r} illisible."
            ) from exc
        if not (boundary <= entry < test_end):
            raise ValueError(
                f"Fold {fold_id!r}, trade {index} : date_entree={raw!r} hors de la fenêtre TEST "
                f"[{effective_boundary}, {effective_test_end}) — trade étranger à ce fold, ou "
                "dupliqué depuis un autre fold, refusé."
            )


def _assemble_monte_carlo_trades(
    plan: GateVCampaignPlan, wf_run: ValidationRun, wf_output_dir: Path, initial_capital: float,
) -> Tuple[float, ...]:
    """Consomme UNIQUEMENT les trades TEST persistés (`folds/<fold_id>/oos_trades.csv`, jamais
    `train_candidates.csv`), dans l'ordre `plan.expected_fold_ids` (ordre chronologique garanti
    par `compute_fold_definitions()`, ADR 0021) — chaque trade conservé exactement une fois,
    vérifié contre les comptes déjà persistés dans la preuve Walk-Forward (ADR 0024 Décision 6,
    amendement AF-V-08) ET contre la fenêtre TEST de son propre fold. Un fold zéro-trade produit
    un `oos_trades.csv` réellement vide (`engine.py::run_backtest()` -> `pd.DataFrame()` sans
    colonnes) — `pandas.errors.EmptyDataError` à la relecture est donc un état ATTENDU pour ce cas
    précis, jamais une erreur technique."""
    fold_results_by_id = {
        _evidence_field(fold, "fold_id"): fold for fold in wf_run.evidence.fold_results
    }
    all_returns = []
    for fold_id in plan.expected_fold_ids:
        fold_result = fold_results_by_id.get(fold_id)
        if fold_result is None:
            raise ValueError(f"Fold {fold_id!r} absent de la preuve Walk-Forward — Monte-Carlo refusé.")
        path = (
            wf_output_dir / _WALK_FORWARD_FOLDS_DIRNAME / fold_id / _WALK_FORWARD_OOS_TRADES_FILENAME
        )
        if not path.is_file():
            raise ValueError(f"{path} absent — trades TEST introuvables pour {fold_id!r}.")
        try:
            fold_trades = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            fold_trades = pd.DataFrame()
        _validate_trades_within_fold_test_window(
            fold_id, _evidence_field(fold_result, "definition"), fold_trades,
        )
        fold_returns = _derive_fold_test_trade_returns_pct(fold_trades, initial_capital)
        expected_n = _evidence_field(fold_result, "n_trades")
        if len(fold_returns) != expected_n:
            raise ValueError(
                f"Fold {fold_id!r} : {len(fold_returns)} trade(s) TEST lu(s) depuis {path} != "
                f"{expected_n} attendu(s) (FoldResult.n_trades)."
            )
        all_returns.extend(fold_returns)
    expected_total = _evidence_field(wf_run.evidence.aggregate, "total_oos_trades")
    if len(all_returns) != expected_total:
        raise ValueError(
            f"{len(all_returns)} trade(s) TEST concaténé(s) != {expected_total} attendu(s) "
            "(AggregateResult.total_oos_trades)."
        )
    return tuple(all_returns)


def _run_monte_carlo_phase(
    plan: GateVCampaignPlan, campaign_root: Union[str, Path], campaign_dir: Path,
    manifest: GateVCampaignManifest, base_config,
) -> GateVCampaignManifest:
    """AF-V-08 Slice 4 — phase Monte-Carlo, APRÈS une preuve Walk-Forward complète et validée.
    `run_monte_carlo_simulation()`/`build_monte_carlo_specification()` appelées DIRECTEMENT,
    jamais injectées (ADR 0024 Décision 5 : fonctions pures, sans I/O, sans moteur, sans accès
    les données réservées de validation finale). `source_trades_from_optimized_params=True` EN DUR (jamais un paramètre de
    cette fonction ni de `execute_gate_v_campaign()`) — les trades TEST proviennent
    structurellement du Top-1 TRAIN-optimisé de chaque fold (ADR 0021 Décision 6)."""
    wf_run = _load_complete_walk_forward_run(plan, manifest, campaign_dir)

    running_manifest = dataclasses.replace(
        manifest, execution_started=True, running=True, status="RUNNING",
    )
    save_gate_v_campaign_manifest(campaign_root, plan, running_manifest)

    mc_validation_run_id = gate_v_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO)
    mc_run_path = (
        campaign_dir / _VALIDATIONS_DIRNAME / mc_validation_run_id / _VALIDATION_RUN_FILENAME
    )
    existing_run = load_validation_run(mc_run_path)
    if existing_run is not None and existing_run.validation_run_id != mc_validation_run_id:
        raise ValueError(f"ValidationRun persistée à {mc_run_path} étrangère à cette campagne.")

    if existing_run is not None:
        # Même reconciliation qu'en phase Walk-Forward (crash après save_validation_run(), avant
        # mise à jour du manifeste) : la preuve déterministe déjà persistée est retrouvée et
        # rattachée, jamais recalculée.
        mc_run = existing_run
    else:
        initial_capital = _initial_capital_from_base_config(base_config)
        wf_output_dir = campaign_dir / _WALK_FORWARD_DIRNAME
        trades = _assemble_monte_carlo_trades(plan, wf_run, wf_output_dir, initial_capital)
        mc_specification = build_monte_carlo_specification(
            manifest.walk_forward_validation_run_id, True, plan.monte_carlo_verdict_policy_id,
        )
        mc_evidence = run_monte_carlo_simulation(trades, mc_specification)
        mc_run = build_validation_run(
            validation_run_id=mc_validation_run_id, research_run_id=plan.research_run_id,
            split_plan_id=plan.split_plan_id, dataset_snapshot_id=plan.dataset_snapshot_id,
            strategy_name=plan.strategy_name, strategy_params=dict(plan.base_params),
            specification=mc_specification, evidence=mc_evidence,
            validation_type=VALIDATION_TYPE_MONTE_CARLO,
        )
        if not _monte_carlo_complete(plan, wf_run, mc_run):
            raise ValueError(
                f"Preuve Monte-Carlo construite pour {plan.campaign_id!r} incomplète ou "
                "incohérente avec le plan de campagne — refus de persister (ADR 0024 Décision 13)."
            )
        save_validation_run(mc_run_path, mc_run)

    final_manifest = dataclasses.replace(
        running_manifest, monte_carlo_validation_run_id=mc_validation_run_id, running=False,
    )
    persisted_runs, evidence_paths = _load_manifest_proofs(plan, final_manifest, campaign_dir)
    status = derive_gate_v_campaign_status(plan, final_manifest, persisted_runs)
    final_manifest = dataclasses.replace(final_manifest, status=status)
    save_gate_v_campaign_manifest(
        campaign_root, plan, final_manifest,
        evidence_by_validation_run_id=persisted_runs,
        evidence_paths_by_validation_run_id=evidence_paths,
    )
    return final_manifest


def _load_complete_monte_carlo_run(
    plan: GateVCampaignPlan, manifest: GateVCampaignManifest, campaign_dir: Path,
    wf_run: ValidationRun,
) -> ValidationRun:
    """Précondition absolue Parameter Stability (ADR 0024 §5, amendement AF-V-08) : recharge et
    revalide strictement la ValidationRun Monte-Carlo de CETTE campagne — jamais une preuve
    partielle/étrangère/incohérente. Réutilise `_validate_scoped_run()`/`_monte_carlo_complete()`
    (Slice 4), jamais réimplémentés."""
    mc_id = manifest.monte_carlo_validation_run_id
    if mc_id is None:
        raise ValueError(
            "Aucune preuve Monte-Carlo rattachée à cette campagne — Parameter Stability refusé "
            "(ADR 0024 §5)."
        )
    mc_path = campaign_dir / _VALIDATIONS_DIRNAME / mc_id / _VALIDATION_RUN_FILENAME
    mc_run = load_validation_run(mc_path)
    if mc_run is None:
        raise ValueError(
            f"ValidationRun Monte-Carlo {mc_id!r} absente ou illisible à {mc_path} — "
            "Parameter Stability refusé (ADR 0024 §5)."
        )
    validated = _validate_scoped_run(plan, mc_id, VALIDATION_TYPE_MONTE_CARLO, {mc_id: mc_run})
    if validated is None or not _monte_carlo_complete(plan, wf_run, validated):
        raise ValueError(
            f"ValidationRun Monte-Carlo {mc_id!r} incomplète, étrangère ou incohérente avec "
            "cette campagne — Parameter Stability refusé (ADR 0024 §5)."
        )
    return validated


def _run_parameter_stability_phase(
    plan: GateVCampaignPlan, campaign_root: Union[str, Path], campaign_dir: Path,
    manifest: GateVCampaignManifest, split_plan, base_config, data_manifest_path,
) -> GateVCampaignManifest:
    """AF-V-08 Slice 5 — phase Parameter Stability, APRÈS Walk-Forward ET Monte-Carlo complets et
    validés (ADR 0024 §5). Un pool TRAIN EXACT par fold, relu via
    `load_walk_forward_captured_run_v1()` (jamais le CSV de candidats TRAIN par fold, dont la
    sérialisation peut perdre une ULP sur `score` — ADR 0024 §3 amendement AF-V-08).
    `analyze_parameter_stability()` appelée DIRECTEMENT, jamais injectée (fonction pure).

    Le manifeste est mis à jour ATOMIQUEMENT après CHAQUE fold traité, jamais seulement à la fin
    — réduit la fenêtre de crash. Une `ValidationRun` PS peut satisfaire ou non la condition de
    qualité ADR 0023 Décision 3 : dans les deux cas, elle est persistée et référencée telle
    quelle, JAMAIS filtrée/masquée (`_parameter_stability_quality()` ne lève que sur une
    incohérence structurelle réelle, jamais sur un résultat scientifique honnête défavorable)."""
    wf_run = _load_complete_walk_forward_run(plan, manifest, campaign_dir)
    _load_complete_monte_carlo_run(plan, manifest, campaign_dir, wf_run)

    wf_output_dir = campaign_dir / _WALK_FORWARD_DIRNAME
    captured = load_walk_forward_captured_run_v1(
        split_plan.validation, plan.walk_forward_specification, plan.readiness_spec, base_config,
        data_manifest_path=data_manifest_path, output_dir=wf_output_dir,
        validation_run_id=manifest.walk_forward_validation_run_id,
    )
    fold_artifacts_by_id = {artifacts.fold_id: artifacts for artifacts in captured.fold_artifacts}
    fold_results_by_id = {
        _evidence_field(fold, "fold_id"): fold for fold in wf_run.evidence.fold_results
    }

    current_manifest = manifest
    for fold_id in plan.expected_fold_ids:
        if fold_id in current_manifest.parameter_stability_validation_run_ids_by_fold:
            continue  # Déjà rattaché -- idempotent, jamais recalculé.

        running_manifest = dataclasses.replace(
            current_manifest, execution_started=True, running=True, status="RUNNING",
        )
        save_gate_v_campaign_manifest(campaign_root, plan, running_manifest)

        ps_id = gate_v_validation_run_id(plan, VALIDATION_TYPE_PARAMETER_STABILITY, fold_id=fold_id)
        ps_run_path = campaign_dir / _VALIDATIONS_DIRNAME / ps_id / _VALIDATION_RUN_FILENAME
        existing_run = load_validation_run(ps_run_path)
        if existing_run is not None and existing_run.validation_run_id != ps_id:
            raise ValueError(f"ValidationRun persistée à {ps_run_path} étrangère à cette campagne.")

        if existing_run is not None:
            # Reprise sans recalcul (même schéma que WF/MC) : save_validation_run() a pu réussir
            # avant un crash antérieur à la mise à jour du manifeste pour CE fold.
            ps_run = existing_run
        else:
            fold_artifacts = fold_artifacts_by_id.get(fold_id)
            fold_result = fold_results_by_id.get(fold_id)
            if fold_artifacts is None or fold_result is None:
                raise ValueError(
                    f"Fold {fold_id!r} absent de la capture Walk-Forward -- Parameter Stability "
                    "refusé."
                )
            selection = _evidence_field(fold_result, "selection")
            pool = tuple(fold_artifacts.train_candidates)
            if not pool:
                raise ValueError(f"Fold {fold_id!r} : pool TRAIN vide -- Parameter Stability refusé.")
            if _evidence_field(selection, "rank_in_train") != 1:
                raise ValueError(f"Fold {fold_id!r} : selection.rank_in_train != 1.")
            if _evidence_field(selection, "train_candidates_evaluated") != len(pool):
                raise ValueError(
                    f"Fold {fold_id!r} : train_candidates_evaluated != len(pool) réellement capturé."
                )
            best_params = _evidence_field(selection, "selected_params")
            if pool[0].get("params") != best_params or pool[0].get("score") != _evidence_field(
                selection, "score_train",
            ):
                raise ValueError(f"Fold {fold_id!r} : premier candidat du pool != vrai Top-1.")
            ps_spec = build_parameter_stability_specification(
                manifest.walk_forward_validation_run_id, plan.search_mode, True,
                plan.parameter_stability_verdict_policy_id, source_fold_id=fold_id,
            )
            ps_evidence = analyze_parameter_stability(pool, best_params, ps_spec)
            ps_run = build_validation_run(
                validation_run_id=ps_id, research_run_id=plan.research_run_id,
                split_plan_id=plan.split_plan_id, dataset_snapshot_id=plan.dataset_snapshot_id,
                strategy_name=plan.strategy_name, strategy_params=dict(plan.base_params),
                specification=ps_spec, evidence=ps_evidence,
                validation_type=VALIDATION_TYPE_PARAMETER_STABILITY,
            )
            # Peut retourner False pour un résultat scientifique honnête (ADR 0023 D3) -- ne
            # lève QUE sur une incohérence structurelle réelle ; la valeur de retour n'est
            # jamais utilisée pour décider de persister ou non (Décision 11 de la mission).
            _parameter_stability_quality(
                plan, ps_run, fold_id, manifest.walk_forward_validation_run_id, fold_result,
            )
            save_validation_run(ps_run_path, ps_run)

        updated_map = dict(current_manifest.parameter_stability_validation_run_ids_by_fold)
        updated_map[fold_id] = ps_id
        current_manifest = dataclasses.replace(
            running_manifest, parameter_stability_validation_run_ids_by_fold=updated_map,
            running=False,
        )
        persisted_runs, evidence_paths = _load_manifest_proofs(plan, current_manifest, campaign_dir)
        status = derive_gate_v_campaign_status(plan, current_manifest, persisted_runs)
        current_manifest = dataclasses.replace(current_manifest, status=status)
        save_gate_v_campaign_manifest(
            campaign_root, plan, current_manifest,
            evidence_by_validation_run_id=persisted_runs,
            evidence_paths_by_validation_run_id=evidence_paths,
        )
    return current_manifest


def execute_gate_v_campaign(
    plan: GateVCampaignPlan,
    *,
    campaign_root: Union[str, Path],
    base_config,
    data_manifest_path: Union[str, Path],
    load_market_data_fn,
    run_walk_forward_fn,
    resume_walk_forward_fn,
    progress_cb=None,
    stop_flag_fn=None,
) -> GateVCampaignManifest:
    """AF-V-08 Slices 3-5 — Niveau B, phases Walk-Forward, Monte-Carlo puis Parameter Stability
    (ADR 0024 Décision 5). Le statut final ne peut être `EVIDENCE_COMPLETE_AWAITING_POLICY` que
    si une preuve OOS existe déjà sur disque, référencée par le plan — jamais fabriquée ici.

    `run_walk_forward_fn`/`resume_walk_forward_fn`/`load_market_data_fn` sont INJECTÉS,
    keyword-only, SANS valeur par défaut — jamais importés ici (un appelant réel passe
    `walk_forward.run_walk_forward_with_artifacts_v1`/`resume_walk_forward_with_artifacts_v1` et
    un vrai chargeur des données de marché réelles). `run_monte_carlo_simulation()`/
    `analyze_parameter_stability()` restent, elles, appelées DIRECTEMENT (fonctions pures, sans
    I/O, ADR 0024 Décision 5) — jamais injectées.

    Un appel unique enchaîne les trois phases si la Walk-Forward se termine sans interruption
    coopérative dans ce même appel ; un `stop_flag_fn` déclenché entre deux folds retourne un
    manifeste EN PAUSE avant tout calcul Monte-Carlo/Parameter Stability (jamais sur un
    Walk-Forward partiel)."""
    if not isinstance(plan, GateVCampaignPlan) or plan != _rebuild_plan(plan):
        raise ValueError("plan doit être un GateVCampaignPlan validé, non forgé.")
    for name, collaborator in (
        ("run_walk_forward_fn", run_walk_forward_fn),
        ("resume_walk_forward_fn", resume_walk_forward_fn),
        ("load_market_data_fn", load_market_data_fn),
    ):
        if collaborator is None or not callable(collaborator):
            raise ValueError(f"{name} est obligatoire et doit être un collaborateur injecté callable.")
    if (
        getattr(base_config, "base_params", None) != plan.base_params
        or getattr(base_config, "mode", None) != plan.search_mode
    ):
        raise ValueError(
            "base_config.base_params/mode divergent du plan de campagne — refusé avant tout "
            "appel coûteux. search_space_hash/budget_per_fold restent vérifiés a posteriori sur "
            "les faits réellement produits par _walk_forward_complete() (ADR 0024 Décision 13), "
            "jamais devinés depuis un champ de base_config qui ne les porte pas (ADR 0024 "
            "Décision 5 : aucun paramètre déduit silencieusement)."
        )

    campaign_dir = Path(campaign_root) / plan.campaign_id
    if load_json_tolerant(campaign_dir / "plan.json") != _plan_record(plan):
        raise ValueError("plan.json validé doit être persisté avant toute exécution.")
    split_plan = load_dataset_split_plan(plan.split_plan_path, strict=True)
    if (
        split_plan is None or split_plan.split_plan_id != plan.split_plan_id
        or split_plan.dataset_snapshot_id != plan.dataset_snapshot_id
        or split_plan.validation is None
    ):
        raise ValueError("split_plan_path ne correspond plus au plan de campagne persisté.")
    fold_definitions = compute_fold_definitions(
        split_plan.validation, plan.walk_forward_specification, plan.readiness_spec,
    )
    if (
        tuple(fold.fold_id for fold in fold_definitions) != plan.expected_fold_ids
        or _fold_definitions_hash(fold_definitions) != plan.expected_fold_definitions_hash
    ):
        raise ValueError("Les folds recalculés divergent du plan de campagne persisté.")

    manifest_path = campaign_dir / "manifest.json"
    manifest = load_gate_v_campaign_manifest(manifest_path, plan)
    if manifest is None:
        manifest = build_gate_v_campaign_manifest(plan)
    if manifest.technical_failure_reason is not None:
        raise ValueError(
            f"Campagne {plan.campaign_id!r} déjà marquée TECHNICAL_FAILURE — reprise manuelle "
            "requise, jamais un nouvel essai automatique."
        )

    if manifest.walk_forward_validation_run_id is None:
        manifest = _run_walk_forward_phase(
            plan, campaign_root, campaign_dir, manifest, split_plan, base_config,
            data_manifest_path, load_market_data_fn, run_walk_forward_fn, resume_walk_forward_fn,
            progress_cb, stop_flag_fn,
        )
        if manifest.walk_forward_validation_run_id is None:
            return manifest  # Arrêt coopératif -- jamais de Monte-Carlo sur un WF partiel.

    if manifest.monte_carlo_validation_run_id is None:
        manifest = _run_monte_carlo_phase(plan, campaign_root, campaign_dir, manifest, base_config)

    if set(manifest.parameter_stability_validation_run_ids_by_fold) != set(plan.expected_fold_ids):
        manifest = _run_parameter_stability_phase(
            plan, campaign_root, campaign_dir, manifest, split_plan, base_config,
            data_manifest_path,
        )

    return manifest


# ══════════════════════════════════════════════════════════════════════════════
# AF-V-08 Slice 4, vague 1 — dérivation du rendement % par trade TEST (Human Gate 2026-09-27,
# ADR 0022 amendement du 2026-09-27, corrige Décision 1 de cette même ADR). `resultat_net` et
# `capital_apres` (persistés dans oos_trades.csv, engine.py) sont chacun arrondis
# INDÉPENDAMMENT à 2 décimales à l'écriture — la trajectoire de capital réellement sérialisée
# (capital_apres) est la source primaire du rendement, jamais resultat_net directement, qui
# devient un simple invariant d'audit de cette trajectoire.
# ══════════════════════════════════════════════════════════════════════════════

_TRADE_RETURN_INTEGRITY_TOLERANCE = 0.015
"""Écart maximal toléré, en unité monétaire, entre `capital_apres - capital_before` et
`resultat_net` pour un même trade (ADR 0022 amendement AF-V-08 2026-09-27). Trois quantités
indépendamment arrondies au centime (`capital_before`, `capital_apres`, `resultat_net`)
contribuent chacune jusqu'à 0,005 dans le pire cas -> 0,015 conservateur (le premier trade d'un
fold n'a en réalité que deux quantités arrondies, `capital_before` étant alors `initial_capital`,
une valeur de configuration exacte -- 0,015 reste sûr, seulement plus large que nécessaire dans
ce cas précis)."""


def _as_finite_float(value, field_name: str) -> float:
    """Conversion stricte vers un flottant fini — accepte tout scalaire numérique réel
    (`int`/`float` Python, `numpy.float64`/`numpy.int64` issus de `pandas.read_csv()`, qui ne
    sont pas tous des sous-classes de `int`/`float` Python), rejette `bool` explicitement (jamais
    une valeur booléenne silencieusement acceptée comme 0/1) et toute valeur non convertible/
    non finie (NaN/Inf/chaîne/`None`)."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} ne peut pas être un booléen : {value!r}.")
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} non numérique ou absent : {value!r}.") from None
    if not math.isfinite(as_float):
        raise ValueError(f"{field_name} non fini : {value!r}.")
    return as_float


def _derive_fold_test_trade_returns_pct(
    fold_trades: "pd.DataFrame", initial_capital: float,
) -> Tuple[float, ...]:
    """Rendement % de chaque trade TEST d'UN fold, dérivé de la trajectoire de capital
    réellement persistée (`capital_apres_i / capital_before_i - 1`) — jamais de `resultat_net`
    directement. `capital_before` repart de `initial_capital` pour le premier trade
    (`flat_each_fold_v1`, ADR 0021 Décision 14 — capital gelé, jamais réinitialisé ici), puis
    chaîne depuis `capital_apres` du trade précédent DU MÊME FOLD — cette fonction est appelée
    UNE FOIS PAR FOLD, jamais sur une concaténation multi-fold (le capital ne traverse jamais une
    frontière de fold).

    Un rendement réel `<= -100 %` n'est jamais censuré (fait persisté). Un `capital_before <= 0`
    au trade SUIVANT rend le rapport financièrement non défini -> `ValueError` fail-closed, avant
    tout calcul sur ce trade."""
    initial_capital = _as_finite_float(initial_capital, "initial_capital")
    if initial_capital <= 0:
        raise ValueError(f"initial_capital doit être strictement positif : {initial_capital!r}.")
    if fold_trades.empty:
        return ()
    for column in ("resultat_net", "capital_apres"):
        if column not in fold_trades.columns:
            raise ValueError(f"Colonne obligatoire absente des trades TEST : {column!r}.")

    returns = []
    capital_before = initial_capital
    for _, row in fold_trades.iterrows():
        resultat_net = _as_finite_float(row["resultat_net"], "resultat_net")
        capital_apres = _as_finite_float(row["capital_apres"], "capital_apres")
        if capital_before <= 0:
            raise ValueError(
                f"capital_before={capital_before!r} <= 0 — rendement du trade suivant non "
                "défini financièrement, refusé avant tout calcul (fail-closed)."
            )
        if abs((capital_apres - capital_before) - resultat_net) > _TRADE_RETURN_INTEGRITY_TOLERANCE:
            raise ValueError(
                f"Incohérence entre capital_before={capital_before!r}, "
                f"capital_apres={capital_apres!r} et resultat_net={resultat_net!r} — écart "
                f"supérieur à la tolérance d'arrondi ({_TRADE_RETURN_INTEGRITY_TOLERANCE})."
            )
        returns.append((capital_apres / capital_before - 1.0) * 100.0)
        capital_before = float(capital_apres)
    return tuple(returns)


def _initial_capital_from_base_config(base_config) -> float:
    """Même clé/valeur par défaut que `optimizer.py::_run_single()`
    (`gp.get("initial_capital", 10_000.0)`) — jamais une autre valeur par défaut inventée ici."""
    global_params = getattr(base_config, "global_params", None)
    if not isinstance(global_params, dict):
        raise ValueError("base_config.global_params est obligatoire et doit être un dictionnaire.")
    value = _as_finite_float(
        global_params.get("initial_capital", 10_000.0), "global_params['initial_capital']",
    )
    if value <= 0:
        raise ValueError(f"initial_capital doit être strictement positif : {value!r}.")
    return value
