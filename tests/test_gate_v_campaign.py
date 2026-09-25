"""AF-V-08 slice 1: deterministic GATE V campaign preparation only.

All split plans and identifiers here are synthetic. No market data is loaded.
"""

from __future__ import annotations

import os
import sys
import dataclasses
import inspect
import json
import shutil
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_split import (
    build_dataset_split_plan,
    build_split_boundary,
    save_dataset_split_plan,
)
from gate_v_campaign import build_gate_v_campaign_plan
import gate_v_campaign
from strategy_contracts import DailyStateReadiness
from validation_run import (
    MONTE_CARLO_SEMANTICS_VERSION,
    PARAMETER_STABILITY_SEMANTICS_VERSION,
    VALIDATION_TYPE_OOS,
    build_oos_validation_evidence,
    build_oos_validation_specification,
    build_validation_run,
    save_validation_run,
)
from walk_forward import WALK_FORWARD_SEMANTICS_VERSION


_SNAPSHOT_ID = "synthetic_csv:sha256:" + "ab" * 32


def _split_plan_path(tmp_path, *, split_plan_id="synthetic_split", snapshot_id=_SNAPSHOT_ID,
                     with_validation=True, validation_start="2022-01-01T00:00:00+00:00"):
    plan = build_dataset_split_plan(
        split_plan_id=split_plan_id,
        dataset_snapshot_id=snapshot_id,
        train=build_split_boundary("2020-01-01T00:00:00+00:00", validation_start),
        validation=(
            build_split_boundary(validation_start, "2025-01-01T00:00:00+00:00")
            if with_validation else None
        ),
        final_holdout=build_split_boundary(
            "2025-01-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00"
        ),
        created_at="2025-01-01T00:00:00+00:00",
    )
    path = tmp_path / f"{split_plan_id}.json"
    save_dataset_split_plan(path, plan)
    return path


def _plan_kwargs(tmp_path):
    return {
        "research_run_id": "research_synthetic_001",
        "dataset_snapshot_id": _SNAPSHOT_ID,
        "split_plan_id": "synthetic_split",
        "split_plan_path": _split_plan_path(tmp_path),
        "strategy_name": "Synthetic Strategy",
        "base_params": {"lookback": 12},
        "search_mode": "grid",
        "search_space_hash": "a" * 12,
        "budget_per_fold": 20,
        "geometry": "rolling",
        "train_period": "P24M",
        "test_period": "P6M",
        "step_period": "P6M",
        "readiness_spec": None,
        "master_seed": None,
    }


def test_identical_synthetic_inputs_produce_identical_campaign_and_folds(tmp_path):
    """ADR 0024 D3/D5/D13: preparation is deterministic and uses validation only."""
    inputs = _plan_kwargs(tmp_path)
    first = build_gate_v_campaign_plan(**inputs)
    second = build_gate_v_campaign_plan(**inputs)

    assert first.campaign_id == second.campaign_id
    assert first.campaign_id != inputs["research_run_id"]
    assert first.expected_fold_ids == second.expected_fold_ids == ("fold_000", "fold_001")


def test_same_fold_ids_with_different_boundaries_produce_distinct_campaigns(tmp_path):
    """Fold IDs alone cannot fingerprint the scientific windows of a campaign."""
    first_inputs = _plan_kwargs(tmp_path / "first")
    second_inputs = dict(first_inputs)
    second_inputs["split_plan_path"] = _split_plan_path(
        tmp_path / "second", validation_start="2021-12-01T00:00:00+00:00",
    )
    first = build_gate_v_campaign_plan(**first_inputs)
    second = build_gate_v_campaign_plan(**second_inputs)
    assert first.expected_fold_ids == second.expected_fold_ids
    assert first.campaign_id != second.campaign_id


def test_same_folds_with_different_unexecuted_validation_tail_produce_distinct_campaigns(tmp_path):
    """ADR 0021 D1: the unexecuted partial tail remains part of the split identity."""
    inputs = _plan_kwargs(tmp_path)
    first = build_gate_v_campaign_plan(**inputs)
    record = json.loads(Path(inputs["split_plan_path"]).read_text(encoding="utf-8"))
    record["validation"]["end"] = "2025-02-01T00:00:00+00:00"
    record["final_holdout"]["start"] = "2025-02-01T00:00:00+00:00"
    Path(inputs["split_plan_path"]).write_text(json.dumps(record), encoding="utf-8")
    second = build_gate_v_campaign_plan(**inputs)
    assert first.expected_fold_ids == second.expected_fold_ids
    assert first.expected_fold_definitions_hash == second.expected_fold_definitions_hash
    assert first.campaign_id != second.campaign_id


@pytest.mark.parametrize(
    "field",
    [
        "research_run_id", "dataset_snapshot_id", "split_plan_id", "split_plan_path",
        "strategy_name", "base_params", "search_mode", "search_space_hash",
        "budget_per_fold", "geometry", "train_period", "test_period", "step_period",
        "readiness_spec", "master_seed",
    ],
)
def test_each_missing_required_input_fails_before_loading_split(tmp_path, monkeypatch, field):
    """ADR 0024 D3: each missing scientific input raises ValueError, before disk validation."""
    inputs = _plan_kwargs(tmp_path)
    inputs.pop(field)
    monkeypatch.setattr(
        gate_v_campaign, "load_dataset_split_plan",
        lambda *_: pytest.fail("split plan loaded before required input validation"),
    )
    with pytest.raises(ValueError, match=field):
        build_gate_v_campaign_plan(**inputs)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("research_run_id", ""), ("dataset_snapshot_id", " "), ("split_plan_id", ""),
        ("split_plan_path", ""), ("strategy_name", ""), ("base_params", {}),
        ("search_mode", ""), ("search_space_hash", ""), ("budget_per_fold", 0),
        ("budget_per_fold", True), ("geometry", ""), ("train_period", ""),
        ("test_period", ""), ("step_period", ""),
    ],
)
def test_empty_or_invalid_required_input_is_rejected(tmp_path, field, bad_value):
    inputs = _plan_kwargs(tmp_path)
    inputs[field] = bad_value
    with pytest.raises(ValueError, match=field):
        build_gate_v_campaign_plan(**inputs)


def test_unsafe_research_run_id_is_rejected(tmp_path):
    inputs = _plan_kwargs(tmp_path)
    inputs["research_run_id"] = "../another-run"
    with pytest.raises(ValueError, match="research_run_id"):
        build_gate_v_campaign_plan(**inputs)


def test_general_search_preserves_explicit_seed_choice(tmp_path):
    """The runtime config must reject unseeded stratified sampling before execution."""
    inputs = _plan_kwargs(tmp_path)
    inputs["search_mode"] = "general"
    assert build_gate_v_campaign_plan(**inputs).walk_forward_specification.master_seed is None
    inputs["master_seed"] = 42
    assert build_gate_v_campaign_plan(**inputs).walk_forward_specification.master_seed == 42


def test_search_space_hash_uses_walk_forward_twelve_hex_contract(tmp_path):
    """Regression: Walk-Forward uses a 12-character MD5 prefix, not SHA-256."""
    inputs = _plan_kwargs(tmp_path)
    inputs["search_space_hash"] = "a1b2c3d4e5f6"
    assert build_gate_v_campaign_plan(**inputs).search_space_hash == "a1b2c3d4e5f6"


def test_plan_captures_current_semantics_and_explicit_readiness(tmp_path):
    inputs = _plan_kwargs(tmp_path)
    inputs["readiness_spec"] = DailyStateReadiness(15, 30, "Europe/Paris")
    plan = build_gate_v_campaign_plan(**inputs)
    assert plan.walk_forward_spec_semantics_version == WALK_FORWARD_SEMANTICS_VERSION
    assert plan.monte_carlo_semantics_version == MONTE_CARLO_SEMANTICS_VERSION
    assert plan.parameter_stability_semantics_version == PARAMETER_STABILITY_SEMANTICS_VERSION
    assert plan.walk_forward_specification.train_period == "P24M"
    assert plan.walk_forward_specification.test_period == "P6M"
    assert plan.walk_forward_specification.step_period == "P6M"
    assert plan.walk_forward_specification.base_params == inputs["base_params"]
    assert plan.readiness_spec == inputs["readiness_spec"]


def test_plan_is_immutable_even_when_caller_changes_base_params(tmp_path):
    inputs = _plan_kwargs(tmp_path)
    plan = build_gate_v_campaign_plan(**inputs)
    inputs["base_params"]["lookback"] = 99
    assert plan.base_params["lookback"] == 12
    assert plan.walk_forward_specification.base_params["lookback"] == 12
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.campaign_id = "replacement"
    with pytest.raises(TypeError):
        plan.base_params["lookback"] = 99


@pytest.mark.parametrize("field", ["split_plan_id", "dataset_snapshot_id"])
def test_plan_rejects_identifier_inconsistent_with_persisted_split(tmp_path, field):
    inputs = _plan_kwargs(tmp_path)
    inputs[field] = "other_id"
    with pytest.raises(ValueError, match=field):
        build_gate_v_campaign_plan(**inputs)


def test_plan_rejects_missing_or_unreadable_split(tmp_path):
    inputs = _plan_kwargs(tmp_path)
    inputs["split_plan_path"] = tmp_path / "missing_split.json"
    with pytest.raises(ValueError, match="split_plan_path"):
        build_gate_v_campaign_plan(**inputs)


def test_plan_rejects_split_without_validation_zone(tmp_path):
    inputs = _plan_kwargs(tmp_path)
    inputs["split_plan_path"] = _split_plan_path(tmp_path, split_plan_id="no_validation",
                                                  with_validation=False)
    inputs["split_plan_id"] = "no_validation"
    with pytest.raises(ValueError, match="validation"):
        build_gate_v_campaign_plan(**inputs)


def test_plan_rejects_persisted_split_with_overlapping_zones(tmp_path):
    """A directly persisted split must not extend validation into another zone."""
    inputs = _plan_kwargs(tmp_path)
    record = json.loads(Path(inputs["split_plan_path"]).read_text(encoding="utf-8"))
    record["validation"]["end"] = "2025-02-01T00:00:00+00:00"
    Path(inputs["split_plan_path"]).write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="chevauche"):
        build_gate_v_campaign_plan(**inputs)


def test_plan_rejects_persisted_split_with_reversed_boundary(tmp_path):
    inputs = _plan_kwargs(tmp_path)
    record = json.loads(Path(inputs["split_plan_path"]).read_text(encoding="utf-8"))
    record["final_holdout"]["end"] = "2024-01-01T00:00:00+00:00"
    Path(inputs["split_plan_path"]).write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="chronologique"):
        build_gate_v_campaign_plan(**inputs)


def test_same_validation_with_different_split_remainder_changes_campaign_id(tmp_path):
    inputs = _plan_kwargs(tmp_path)
    first = build_gate_v_campaign_plan(**inputs)
    record = json.loads(Path(inputs["split_plan_path"]).read_text(encoding="utf-8"))
    record["final_holdout"]["start"] = "2025-07-01T00:00:00+00:00"
    record["final_holdout"]["end"] = "2026-01-01T00:00:00+00:00"
    Path(inputs["split_plan_path"]).write_text(json.dumps(record), encoding="utf-8")
    second = build_gate_v_campaign_plan(**inputs)
    assert first.expected_fold_definitions_hash == second.expected_fold_definitions_hash
    assert first.campaign_id != second.campaign_id


def _synthetic_oos_run(path, *, validation_run_id="synthetic_oos_001", snapshot_id=_SNAPSHOT_ID,
                       split_plan_id="synthetic_split", strategy_name="Synthetic Strategy"):
    run = build_validation_run(
        validation_run_id=validation_run_id,
        research_run_id="external_research_synthetic",
        split_plan_id=split_plan_id,
        dataset_snapshot_id=snapshot_id,
        strategy_name=strategy_name,
        strategy_params={"lookback": 12},
        specification=build_oos_validation_specification(
            "2025-01-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00"
        ),
        evidence=build_oos_validation_evidence(
            "2025-01-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00", 0, 0.0
        ),
        validation_type=VALIDATION_TYPE_OOS,
        completed_at="2025-07-01T00:00:00+00:00",
    )
    save_validation_run(path, run)
    return run


def test_oos_reference_requires_an_existing_matching_persisted_run(tmp_path):
    """ADR 0024 D9: a caller supplied OOS ID is verified, never generated here."""
    inputs = _plan_kwargs(tmp_path)
    inputs["oos_evidence_validation_run_id"] = "synthetic_oos_001"
    with pytest.raises(ValueError, match="oos_evidence_path"):
        build_gate_v_campaign_plan(**inputs)
    inputs["oos_evidence_path"] = tmp_path / "not_written.json"
    with pytest.raises(ValueError, match="OOS"):
        build_gate_v_campaign_plan(**inputs)
    _synthetic_oos_run(inputs["oos_evidence_path"])
    assert build_gate_v_campaign_plan(**inputs).oos_evidence_validation_run_id == "synthetic_oos_001"


@pytest.mark.parametrize(
    ("oos_override", "value"),
    [("validation_run_id", "different_oos"), ("snapshot_id", "other_snapshot"),
     ("split_plan_id", "other_split"), ("strategy_name", "Other Strategy")],
)
def test_oos_reference_rejects_foreign_identity(tmp_path, oos_override, value):
    inputs = _plan_kwargs(tmp_path)
    inputs["oos_evidence_validation_run_id"] = "synthetic_oos_001"
    inputs["oos_evidence_path"] = tmp_path / "synthetic_oos.json"
    _synthetic_oos_run(inputs["oos_evidence_path"], **{oos_override: value})
    with pytest.raises(ValueError, match="OOS"):
        build_gate_v_campaign_plan(**inputs)


def test_oos_reference_rejects_training_period_or_incoherent_evidence(tmp_path):
    """An externally supplied OOS record cannot point into the training window."""
    inputs = _plan_kwargs(tmp_path)
    inputs["oos_evidence_validation_run_id"] = "synthetic_oos_001"
    inputs["oos_evidence_path"] = tmp_path / "synthetic_oos.json"
    _synthetic_oos_run(inputs["oos_evidence_path"])
    record = json.loads(inputs["oos_evidence_path"].read_text(encoding="utf-8"))
    record["specification"]["holdout_start"] = "2018-01-01T00:00:00+00:00"
    record["specification"]["holdout_end"] = "2018-07-01T00:00:00+00:00"
    record["evidence"]["period_start"] = "2018-01-01T00:00:00+00:00"
    record["evidence"]["period_end"] = "2018-07-01T00:00:00+00:00"
    inputs["oos_evidence_path"].write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="OOS"):
        build_gate_v_campaign_plan(**inputs)


def test_oos_reference_rejects_reversed_period(tmp_path):
    inputs = _plan_kwargs(tmp_path)
    inputs["oos_evidence_validation_run_id"] = "synthetic_oos_001"
    inputs["oos_evidence_path"] = tmp_path / "synthetic_oos.json"
    _synthetic_oos_run(inputs["oos_evidence_path"])
    record = json.loads(inputs["oos_evidence_path"].read_text(encoding="utf-8"))
    record["specification"]["holdout_end"] = "2024-07-01T00:00:00+00:00"
    record["evidence"]["period_end"] = "2024-07-01T00:00:00+00:00"
    inputs["oos_evidence_path"].write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="OOS"):
        build_gate_v_campaign_plan(**inputs)


def test_oos_reference_rejects_window_from_replaced_split(tmp_path):
    inputs = _plan_kwargs(tmp_path)
    inputs["oos_evidence_validation_run_id"] = "synthetic_oos_001"
    inputs["oos_evidence_path"] = tmp_path / "synthetic_oos.json"
    _synthetic_oos_run(inputs["oos_evidence_path"])
    record = json.loads(Path(inputs["split_plan_path"]).read_text(encoding="utf-8"))
    record["final_holdout"]["start"] = "2025-07-01T00:00:00+00:00"
    record["final_holdout"]["end"] = "2026-01-01T00:00:00+00:00"
    Path(inputs["split_plan_path"]).write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="OOS"):
        build_gate_v_campaign_plan(**inputs)


def test_oos_evidence_content_changes_campaign_id_even_with_same_run_id(tmp_path):
    inputs = _plan_kwargs(tmp_path)
    inputs["oos_evidence_validation_run_id"] = "synthetic_oos_001"
    inputs["oos_evidence_path"] = tmp_path / "synthetic_oos.json"
    _synthetic_oos_run(inputs["oos_evidence_path"])
    first = build_gate_v_campaign_plan(**inputs)
    record = json.loads(inputs["oos_evidence_path"].read_text(encoding="utf-8"))
    record["evidence"]["net_ret_pct"] = 2.0
    inputs["oos_evidence_path"].write_text(json.dumps(record), encoding="utf-8")
    second = build_gate_v_campaign_plan(**inputs)
    assert first.campaign_id != second.campaign_id


@pytest.mark.parametrize("field", [
    "monte_carlo_verdict_policy_id", "parameter_stability_verdict_policy_id",
    "walk_forward_verdict_policy_id",
])
def test_plan_rejects_unregistered_verdict_policy(tmp_path, field):
    """No scientific policy registry exists yet for these three validation types."""
    inputs = _plan_kwargs(tmp_path)
    inputs[field] = "policy_not_registered"
    with pytest.raises(ValueError, match="policy"):
        build_gate_v_campaign_plan(**inputs)


def test_plan_can_be_saved_once_and_loaded_from_real_json(tmp_path):
    """ADR 0024 D4: plan.json is an immutable atomic artifact in the campaign directory."""
    from gate_v_campaign import load_gate_v_campaign_plan, save_gate_v_campaign_plan

    plan = build_gate_v_campaign_plan(**_plan_kwargs(tmp_path))
    root = tmp_path / "gate_v_campaign"
    path = save_gate_v_campaign_plan(root, plan)
    assert path == root / plan.campaign_id / "plan.json"
    assert json.loads(path.read_text(encoding="utf-8"))["campaign_id"] == plan.campaign_id
    assert load_gate_v_campaign_plan(path, split_plan_path=plan.split_plan_path) == plan
    with pytest.raises(FileExistsError):
        save_gate_v_campaign_plan(root, plan)
    assert load_gate_v_campaign_plan(path, split_plan_path=plan.split_plan_path) == plan
    assert not list(path.parent.glob("*.tmp"))


def test_saved_plan_is_portable_across_two_synthetic_worktrees(tmp_path):
    """Regression: persisted plan contains IDs, never machine-specific absolute paths."""
    from gate_v_campaign import load_gate_v_campaign_plan, save_gate_v_campaign_plan

    source = tmp_path / "source_checkout"
    target = tmp_path / "target_checkout"
    source.mkdir()
    target.mkdir()
    source_inputs = _plan_kwargs(source)
    plan = build_gate_v_campaign_plan(**source_inputs)
    source_path = save_gate_v_campaign_plan(source / "results" / "gate_v_campaign", plan)
    record = json.loads(source_path.read_text(encoding="utf-8"))
    assert "split_plan_path" not in record
    assert "oos_evidence_path" not in record
    assert str(source) not in source_path.read_text(encoding="utf-8")

    target_inputs = _plan_kwargs(target)
    target_plan = build_gate_v_campaign_plan(**target_inputs)
    assert target_plan.campaign_id == plan.campaign_id
    target_path = target / "results" / "gate_v_campaign" / plan.campaign_id / "plan.json"
    target_path.parent.mkdir(parents=True)
    shutil.copyfile(source_path, target_path)
    loaded = load_gate_v_campaign_plan(target_path, split_plan_path=target_inputs["split_plan_path"])
    assert loaded == target_plan


def test_preparation_has_no_execution_collaborator_or_market_data_access(tmp_path, monkeypatch):
    """ADR 0024 D5/D10/D13: only persisted metadata and pure fold geometry are used."""
    source = inspect.getsource(gate_v_campaign)
    assert "import validation_oos" not in source
    assert "import engine" not in source
    assert "nasdaq_3m.csv" not in source
    assert "final_holdout" not in source.lower()
    signature = inspect.signature(build_gate_v_campaign_plan)
    assert "run_walk_forward_fn" not in signature.parameters
    assert "load_market_data_fn" not in signature.parameters

    original_read_text = Path.read_text

    def json_only_read_text(path, *args, **kwargs):
        assert path.suffix == ".json", "market data read during campaign preparation"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", json_only_read_text)
    build_gate_v_campaign_plan(**_plan_kwargs(tmp_path))
