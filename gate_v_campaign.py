"""Deterministic preparation for a GATE V campaign (ADR 0024).

This module only builds a plan from existing metadata. It does not run a
scientific campaign or read market data.
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
from typing import Optional, Union

from atomic_json_store import load_json_tolerant, save_atomic, validate_portable_identifier
from dataset_split import (
    assert_oos_window_matches_split, dataset_split_plan_fingerprint, load_dataset_split_plan,
)
from strategy_contracts import DailyStateReadiness
from validation_run import (
    MONTE_CARLO_SEMANTICS_VERSION,
    PARAMETER_STABILITY_SEMANTICS_VERSION,
    VALIDATION_TYPE_OOS,
    OosValidationSpecification,
    WalkForwardSpecification,
    load_validation_run,
)
from walk_forward import build_walk_forward_specification, compute_fold_definitions


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
    fold_payload = json.dumps(
        [dataclasses.asdict(fold) for fold in fold_definitions],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    expected_fold_definitions_hash = hashlib.sha256(fold_payload.encode("utf-8")).hexdigest()
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
