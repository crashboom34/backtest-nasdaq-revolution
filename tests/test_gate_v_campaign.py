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
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_split import (
    build_dataset_split_plan,
    build_split_boundary,
    load_dataset_split_plan,
    save_dataset_split_plan,
)
from gate_v_campaign import build_gate_v_campaign_plan
import gate_v_campaign
import walk_forward
from market_data.backtest_manifest import build_backtest_manifest, save_backtest_manifest
from optimizer import FilterConfig, OptimizationConfig, ScoreWeights, TrainTestConfig, params_hash
from strategy_contracts import DailyStateReadiness
from validation_run import (
    AggregateResult,
    FoldResult,
    FoldSelection,
    MONTE_CARLO_SEMANTICS_VERSION,
    MonteCarloEvidence,
    PARAMETER_STABILITY_SEMANTICS_VERSION,
    PercentileDistributionSummary,
    ParameterStabilityEvidence,
    VALIDATION_TYPE_MONTE_CARLO,
    VALIDATION_TYPE_OOS,
    VALIDATION_TYPE_PARAMETER_STABILITY,
    VALIDATION_TYPE_WALK_FORWARD,
    WalkForwardEvidence,
    WalkForwardRunOutcome,
    build_monte_carlo_specification,
    build_oos_validation_evidence,
    build_oos_validation_specification,
    build_parameter_stability_specification,
    build_validation_run,
    load_validation_run,
    save_validation_run,
)
from parameter_stability import analyze_parameter_stability
from walk_forward import (
    FoldArtifacts,
    WALK_FORWARD_SEMANTICS_VERSION,
    WalkForwardCapturedRunV1,
    build_aggregate_result,
    compute_fold_definitions,
    load_walk_forward_captured_run_v1,
    persist_walk_forward_run,
)


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


def _synthetic_campaign_evidence(tmp_path):
    """Typed, minimal evidence from synthetic folds; never invokes a scientific engine."""
    from dataset_split import load_dataset_split_plan
    from gate_v_campaign import gate_v_validation_run_id

    oos_path = tmp_path / "synthetic_oos.json"
    oos = _synthetic_oos_run(oos_path)
    plan = build_gate_v_campaign_plan(
        **_plan_kwargs(tmp_path),
        oos_evidence_validation_run_id=oos.validation_run_id,
        oos_evidence_path=oos_path,
    )
    split = load_dataset_split_plan(plan.split_plan_path)
    definitions = compute_fold_definitions(
        split.validation, plan.walk_forward_specification, plan.readiness_spec,
    )
    results = tuple(
        FoldResult(
            fold_id=definition.fold_id,
            definition=definition,
            selection=FoldSelection(
                fold_id=definition.fold_id, selected_params={"lookback": 12},
                selected_params_hash="synthetic_hash", score_train=1.0,
                rank_in_train=1, train_candidates_evaluated=2,
                train_candidates_unique=2, train_candidates_eligible=2,
                search_space_hash=plan.search_space_hash, algorithm=plan.search_mode,
                fold_seed=None,
            ),
            n_trades=0, net_ret_pct=0.0, max_dd_pct=None, profit_factor=None,
            win_rate=None, expectancy=None, score_test=0.0,
            zero_trade_oos=True, forced_closes=0, coverage_bars=1,
        ) for definition in definitions
    )
    aggregate = AggregateResult(
        n_folds=len(results), n_folds_zero_trade=len(results), total_oos_trades=0,
        oos_net_return_pct=0.0, oos_max_dd_pct=None, oos_profit_factor=None,
        oos_win_rate=None, oos_sharpe=None, mean_fold_score_test=0.0,
        median_fold_score_test=0.0, worst_fold_id=results[0].fold_id,
    )
    wf_id = gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
    mc_id = gate_v_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO)
    common = dict(
        research_run_id=plan.research_run_id,
        split_plan_id=plan.split_plan_id,
        dataset_snapshot_id=plan.dataset_snapshot_id,
        strategy_name=plan.strategy_name,
        strategy_params=dict(plan.base_params),
        completed_at="2025-07-01T00:00:00+00:00",
    )
    wf = build_validation_run(
        validation_run_id=wf_id, validation_type=VALIDATION_TYPE_WALK_FORWARD,
        specification=plan.walk_forward_specification,
        evidence=WalkForwardEvidence(results, aggregate, "completed", "INCONCLUSIVE", ()),
        **common,
    )
    mc = build_validation_run(
        validation_run_id=mc_id, validation_type=VALIDATION_TYPE_MONTE_CARLO,
        specification=build_monte_carlo_specification(wf_id, True),
        evidence=MonteCarloEvidence(
            n_input_trades=0, zero_trade_input=True, observed_net_ret_pct=None,
            observed_max_dd_trade_close_basis_pct=None,
            observed_lag1_autocorrelation=None, observed_longest_losing_streak=None,
            sequence_risk_max_dd_trade_close_basis_pct=None,
            sequence_risk_longest_losing_streak=None,
            sampling_uncertainty_net_ret_pct=None,
            sampling_uncertainty_max_dd_trade_close_basis_pct=None,
            execution_status="completed", scientific_verdict="INCONCLUSIVE",
            verdict_reasons=(),
        ),
        **common,
    )
    runs = {run.validation_run_id: run for run in (oos, wf, mc)}
    ps_by_fold = {}
    neighbor_summary = PercentileDistributionSummary(0.1, 0.1, 0.1, 0.1, 0.1)
    for fold_id in plan.expected_fold_ids:
        ps_id = gate_v_validation_run_id(
            plan, VALIDATION_TYPE_PARAMETER_STABILITY, fold_id=fold_id,
        )
        ps_by_fold[fold_id] = ps_id
        ps = build_validation_run(
            validation_run_id=ps_id, validation_type=VALIDATION_TYPE_PARAMETER_STABILITY,
            specification=build_parameter_stability_specification(
                wf_id, plan.search_mode, True, source_fold_id=fold_id,
            ),
            evidence=ParameterStabilityEvidence(
                n_candidates_total=2, zero_candidates_input=False,
                search_mode=plan.search_mode,
                neighborhood_applicability="local_neighborhood_available",
                best_score=1.0, best_params={"lookback": 12},
                sensitivity={"lookback": 0.0}, sensitivity_sample_size_by_param={"lookback": 2},
                n_neighbors_total_by_param={"lookback": 1},
                n_neighbors_rejected_by_param={"lookback": 0},
                degradation_by_param={"lookback": neighbor_summary},
                degradation_points_by_param={"lookback": neighbor_summary},
                n_hamming_le_2_total=1, n_hamming_le_2_rejected=0,
                degradation_hamming_le_2=neighbor_summary, execution_status="completed",
                scientific_verdict="INCONCLUSIVE", verdict_reasons=(),
            ),
            **common,
        )
        runs[ps_id] = ps
    return plan, runs, wf_id, mc_id, ps_by_fold


def _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold):
    from gate_v_campaign import build_gate_v_campaign_manifest

    return dataclasses.replace(
        build_gate_v_campaign_manifest(plan), execution_started=True,
        walk_forward_validation_run_id=wf_id,
        monte_carlo_validation_run_id=mc_id,
        parameter_stability_validation_run_ids_by_fold=ps_by_fold,
    )


def test_manifest_statuses_are_the_exact_six_non_verdict_states(tmp_path):
    from gate_v_campaign import GATE_V_CAMPAIGN_STATUSES, build_gate_v_campaign_manifest

    assert GATE_V_CAMPAIGN_STATUSES == frozenset({
        "NOT_READY", "READY_FOR_EXECUTION", "RUNNING", "EVIDENCE_INCOMPLETE",
        "EVIDENCE_COMPLETE_AWAITING_POLICY", "TECHNICAL_FAILURE",
    })
    plan = build_gate_v_campaign_plan(**_plan_kwargs(tmp_path))
    manifest = build_gate_v_campaign_manifest(plan)
    assert manifest.status == "READY_FOR_EXECUTION"
    assert manifest.campaign_id == plan.campaign_id
    assert manifest.expected_fold_ids == plan.expected_fold_ids
    assert manifest.oos_evidence_validation_run_id is None


def test_manifest_complete_requires_all_four_categories_and_every_quality_fold(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    assert derive_gate_v_campaign_status(plan, manifest, runs) == "EVIDENCE_COMPLETE_AWAITING_POLICY"
    assert derive_gate_v_campaign_status(plan, manifest, runs) == "EVIDENCE_COMPLETE_AWAITING_POLICY"
    assert not hasattr(manifest, "parameter_stability_combined_score")


@pytest.mark.parametrize("missing", ["oos", "walk_forward", "monte_carlo", "parameter_stability"])
def test_manifest_missing_any_evidence_category_stays_incomplete(tmp_path, missing):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    if missing == "oos":
        plan = dataclasses.replace(plan, oos_evidence_validation_run_id=None, oos_evidence_hash=None)
        manifest = dataclasses.replace(manifest, oos_evidence_validation_run_id=None)
    elif missing == "walk_forward":
        manifest = dataclasses.replace(
            manifest, walk_forward_validation_run_id=None,
            monte_carlo_validation_run_id=None,
            parameter_stability_validation_run_ids_by_fold={},
        )
    elif missing == "monte_carlo":
        manifest = dataclasses.replace(manifest, monte_carlo_validation_run_id=None)
    else:
        manifest = dataclasses.replace(manifest, parameter_stability_validation_run_ids_by_fold={})
    assert derive_gate_v_campaign_status(plan, manifest, runs) == "EVIDENCE_INCOMPLETE"


def test_manifest_one_missing_fold_or_missing_referenced_run_stays_incomplete(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    missing_fold = plan.expected_fold_ids[-1]
    incomplete = dataclasses.replace(
        manifest, parameter_stability_validation_run_ids_by_fold={
            fold_id: run_id for fold_id, run_id in ps_by_fold.items() if fold_id != missing_fold
        },
    )
    assert derive_gate_v_campaign_status(plan, incomplete, runs) == "EVIDENCE_INCOMPLETE"
    missing_run = {key: run for key, run in runs.items() if key != ps_by_fold[missing_fold]}
    assert derive_gate_v_campaign_status(plan, manifest, missing_run) == "EVIDENCE_INCOMPLETE"


@pytest.mark.parametrize("applicability,total,rejected", [
    ("global_correlation_only", 1, 0),
    ("local_neighborhood_available", 0, 0),
    ("local_neighborhood_available", 1, 1),
])
def test_manifest_each_fold_needs_real_local_usable_neighbor(
    tmp_path, applicability, total, rejected,
):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    one_id = ps_by_fold[plan.expected_fold_ids[-1]]
    bad_evidence = dataclasses.replace(
        runs[one_id].evidence, neighborhood_applicability=applicability,
        n_neighbors_total_by_param={"lookback": total},
        n_neighbors_rejected_by_param={"lookback": rejected},
    )
    runs[one_id] = dataclasses.replace(runs[one_id], evidence=bad_evidence)
    assert derive_gate_v_campaign_status(plan, manifest, runs) == "EVIDENCE_INCOMPLETE"
    assert one_id in manifest.parameter_stability_validation_run_ids_by_fold.values()


def test_manifest_rejects_parameter_stability_from_wrong_top1(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    one_id = ps_by_fold[plan.expected_fold_ids[0]]
    runs[one_id] = dataclasses.replace(
        runs[one_id], evidence=dataclasses.replace(
            runs[one_id].evidence, best_params={"lookback": 999},
        ),
    )
    with pytest.raises(ValueError, match="Top-1|best_params|fold"):
        derive_gate_v_campaign_status(plan, manifest, runs)


def test_manifest_usable_neighbor_without_degradation_summary_stays_incomplete(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    one_id = ps_by_fold[plan.expected_fold_ids[0]]
    runs[one_id] = dataclasses.replace(
        runs[one_id], evidence=dataclasses.replace(
            runs[one_id].evidence, degradation_by_param={"lookback": None},
        ),
    )
    assert derive_gate_v_campaign_status(plan, manifest, runs) == "EVIDENCE_INCOMPLETE"


def test_manifest_rejects_impossible_neighbor_count_for_training_pool(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    one_id = ps_by_fold[plan.expected_fold_ids[0]]
    runs[one_id] = dataclasses.replace(
        runs[one_id], evidence=dataclasses.replace(
            runs[one_id].evidence, n_neighbors_total_by_param={"lookback": 999},
        ),
    )
    with pytest.raises(ValueError, match="voisin|candidat|pool"):
        derive_gate_v_campaign_status(plan, manifest, runs)


def test_manifest_rejects_parameter_stability_unregistered_policy(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    one_id = ps_by_fold[plan.expected_fold_ids[0]]
    runs[one_id] = dataclasses.replace(
        runs[one_id], specification=dataclasses.replace(
            runs[one_id].specification, verdict_policy_id="unregistered",
        ),
    )
    with pytest.raises(ValueError, match="policy|Parameter Stability|provenance"):
        derive_gate_v_campaign_status(plan, manifest, runs)


def test_manifest_rejects_wrong_walk_forward_search_space(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    first = runs[wf_id].evidence.fold_results[0]
    altered = dataclasses.replace(
        first, selection=dataclasses.replace(first.selection, search_space_hash="foreign_hash"),
    )
    runs[wf_id] = dataclasses.replace(
        runs[wf_id], evidence=dataclasses.replace(
            runs[wf_id].evidence, fold_results=(altered, *runs[wf_id].evidence.fold_results[1:]),
        ),
    )
    with pytest.raises(ValueError, match="search_space_hash|TRAIN|fold"):
        derive_gate_v_campaign_status(plan, manifest, runs)


def test_manifest_rejects_monte_carlo_spec_or_params_outside_plan(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    bad_spec = dataclasses.replace(runs[mc_id].specification, n_simulations=1, master_seed=12345)
    with pytest.raises(ValueError, match="Monte-Carlo|spécification|seed"):
        derive_gate_v_campaign_status(
            plan, manifest, {**runs, mc_id: dataclasses.replace(runs[mc_id], specification=bad_spec)},
        )
    with pytest.raises(ValueError, match="[Pp]aram|Monte-Carlo"):
        derive_gate_v_campaign_status(
            plan, manifest, {**runs, mc_id: dataclasses.replace(
                runs[mc_id], strategy_params={"lookback": 999},
            )},
        )


def test_manifest_rejects_foreign_campaign_proof_and_wrong_fold_provenance(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    wrong_wf = dataclasses.replace(runs[wf_id], validation_run_id="foreign_campaign_walk_forward")
    with pytest.raises(ValueError, match="campagne|validation_run_id"):
        derive_gate_v_campaign_status(plan, manifest, {**runs, wf_id: wrong_wf})
    one_id = ps_by_fold[plan.expected_fold_ids[0]]
    wrong_spec = dataclasses.replace(
        runs[one_id].specification, source_fold_id=plan.expected_fold_ids[-1],
    )
    with pytest.raises(ValueError, match="fold|provenance"):
        derive_gate_v_campaign_status(
            plan, manifest, {**runs, one_id: dataclasses.replace(runs[one_id], specification=wrong_spec)},
        )
    with pytest.raises(ValueError, match="fold|campagne"):
        derive_gate_v_campaign_status(
            plan, dataclasses.replace(manifest, parameter_stability_validation_run_ids_by_fold={
                **ps_by_fold, "foreign_fold": "foreign_campaign_parameter_stability"
            }), runs,
        )


def test_manifest_rejects_foreign_referenced_proof_even_when_another_category_is_missing(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    manifest = dataclasses.replace(manifest, monte_carlo_validation_run_id=None)
    runs[wf_id] = dataclasses.replace(runs[wf_id], research_run_id="foreign_research")
    with pytest.raises(ValueError, match="ResearchRun|campagne"):
        derive_gate_v_campaign_status(plan, manifest, runs)


def test_manifest_rejects_monte_carlo_trade_count_inconsistent_with_walk_forward(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    runs[mc_id] = dataclasses.replace(
        runs[mc_id], evidence=dataclasses.replace(
            runs[mc_id].evidence, n_input_trades=1, zero_trade_input=False,
        ),
    )
    with pytest.raises(ValueError, match="trades|Monte-Carlo"):
        derive_gate_v_campaign_status(plan, manifest, runs)


def test_manifest_rejects_invented_monte_carlo_metric_for_zero_trades(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    runs[mc_id] = dataclasses.replace(
        runs[mc_id], evidence=dataclasses.replace(
            runs[mc_id].evidence, observed_net_ret_pct=50.0,
        ),
    )
    with pytest.raises(ValueError, match="zéro|Monte-Carlo|métrique"):
        derive_gate_v_campaign_status(plan, manifest, runs)


def test_manifest_positive_trade_monte_carlo_requires_computed_metrics(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    wf_evidence = runs[wf_id].evidence
    first = dataclasses.replace(wf_evidence.fold_results[0], n_trades=1, zero_trade_oos=False)
    runs[wf_id] = dataclasses.replace(runs[wf_id], evidence=dataclasses.replace(
        wf_evidence,
        fold_results=(first, *wf_evidence.fold_results[1:]),
        aggregate=dataclasses.replace(
            wf_evidence.aggregate, total_oos_trades=1,
            n_folds_zero_trade=wf_evidence.aggregate.n_folds_zero_trade - 1,
        ),
    ))
    runs[mc_id] = dataclasses.replace(runs[mc_id], evidence=dataclasses.replace(
        runs[mc_id].evidence, n_input_trades=1, zero_trade_input=False,
    ))
    assert derive_gate_v_campaign_status(plan, manifest, runs) == "EVIDENCE_INCOMPLETE"


def test_manifest_rejects_walk_forward_fold_zero_trade_contradiction(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    wf_evidence = runs[wf_id].evidence
    first = dataclasses.replace(wf_evidence.fold_results[0], n_trades=1)
    runs[wf_id] = dataclasses.replace(runs[wf_id], evidence=dataclasses.replace(
        wf_evidence,
        fold_results=(first, *wf_evidence.fold_results[1:]),
        aggregate=dataclasses.replace(wf_evidence.aggregate, total_oos_trades=1),
    ))
    runs[mc_id] = dataclasses.replace(runs[mc_id], evidence=dataclasses.replace(
        runs[mc_id].evidence, n_input_trades=1, zero_trade_input=False,
    ))
    with pytest.raises(ValueError, match="zéro trade|fold"):
        derive_gate_v_campaign_status(plan, manifest, runs)


def test_manifest_rejects_invented_return_for_zero_trade_fold(tmp_path):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    evidence = runs[wf_id].evidence
    first = dataclasses.replace(evidence.fold_results[0], net_ret_pct=25.0)
    runs[wf_id] = dataclasses.replace(runs[wf_id], evidence=dataclasses.replace(
        evidence, fold_results=(first, *evidence.fold_results[1:]),
    ))
    with pytest.raises(ValueError, match="zéro trade|fold"):
        derive_gate_v_campaign_status(plan, manifest, runs)


def test_manifest_status_is_pure_and_rejects_unregistered_scientific_verdict(tmp_path, monkeypatch):
    from gate_v_campaign import derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    changed = {
        key: dataclasses.replace(
            run, evidence=dataclasses.replace(run.evidence, scientific_verdict="PASS"),
        ) if key != plan.oos_evidence_validation_run_id else run
        for key, run in runs.items()
    }
    def forbidden(*args, **kwargs):
        raise AssertionError("status calculation accessed disk or network")
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    assert derive_gate_v_campaign_status(plan, manifest, runs) == "EVIDENCE_COMPLETE_AWAITING_POLICY"
    with pytest.raises(ValueError, match="verdict|policy|PASS"):
        derive_gate_v_campaign_status(plan, manifest, changed)


def test_manifest_running_survives_persistence_and_failure_is_distinct(tmp_path):
    from gate_v_campaign import (
        build_gate_v_campaign_manifest, derive_gate_v_campaign_status,
        load_gate_v_campaign_manifest, save_gate_v_campaign_manifest,
    )

    plan = build_gate_v_campaign_plan(**_plan_kwargs(tmp_path))
    ready = build_gate_v_campaign_manifest(plan)
    running = dataclasses.replace(ready, execution_started=True, running=True, status="RUNNING")
    assert derive_gate_v_campaign_status(plan, running, {}) == "RUNNING"
    root = tmp_path / "gate_v_campaign"
    from gate_v_campaign import save_gate_v_campaign_plan
    save_gate_v_campaign_plan(root, plan)
    path = save_gate_v_campaign_manifest(root, plan, running)
    assert path == root / plan.campaign_id / "manifest.json"
    assert load_gate_v_campaign_manifest(path, plan) == running
    assert not list(path.parent.glob("*.tmp"))
    failed = dataclasses.replace(
        running, running=False, technical_failure_reason="synthetic interruption",
        status="TECHNICAL_FAILURE",
    )
    assert derive_gate_v_campaign_status(plan, failed, {}) == "TECHNICAL_FAILURE"
    save_gate_v_campaign_manifest(root, plan, failed)
    assert load_gate_v_campaign_manifest(path, plan) == failed


def test_manifest_save_rejects_state_and_status_disagreement(tmp_path):
    from gate_v_campaign import build_gate_v_campaign_manifest, save_gate_v_campaign_manifest

    plan = build_gate_v_campaign_plan(**_plan_kwargs(tmp_path))
    ready = build_gate_v_campaign_manifest(plan)
    with pytest.raises(ValueError, match="statut|status|RUNNING"):
        save_gate_v_campaign_manifest(
            tmp_path / "gate_v_campaign", plan,
            dataclasses.replace(ready, status="RUNNING"),
        )
    assert not (tmp_path / "gate_v_campaign" / plan.campaign_id / "manifest.json").exists()


def test_manifest_rejects_null_fold_reference_and_dependent_proof_without_walk_forward(tmp_path):
    from gate_v_campaign import build_gate_v_campaign_manifest, derive_gate_v_campaign_status

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    bad_mapping = dataclasses.replace(
        manifest, parameter_stability_validation_run_ids_by_fold={plan.expected_fold_ids[0]: None},
    )
    with pytest.raises(ValueError, match="fold|Parameter Stability|None"):
        derive_gate_v_campaign_status(plan, bad_mapping, runs)
    without_wf = dataclasses.replace(manifest, walk_forward_validation_run_id=None)
    with pytest.raises(ValueError, match="Walk-Forward|filiation|source"):
        derive_gate_v_campaign_status(plan, without_wf, runs)


def test_manifest_save_requires_persisted_plan_and_revalidates_plan_identity(tmp_path):
    from gate_v_campaign import build_gate_v_campaign_manifest, save_gate_v_campaign_manifest

    plan = build_gate_v_campaign_plan(**_plan_kwargs(tmp_path))
    manifest = build_gate_v_campaign_manifest(plan)
    root = tmp_path / "gate_v_campaign"
    with pytest.raises(ValueError, match="plan.json|plan"):
        save_gate_v_campaign_manifest(root, plan, manifest)
    forged = dataclasses.replace(plan, campaign_id="../foreign")
    forged_manifest = dataclasses.replace(manifest, campaign_id="../foreign")
    with pytest.raises(ValueError, match="plan|campaign_id"):
        save_gate_v_campaign_manifest(root, forged, forged_manifest)


def test_manifest_load_rejects_foreign_fold_mapping_before_execution(tmp_path):
    from gate_v_campaign import (
        build_gate_v_campaign_manifest, load_gate_v_campaign_manifest,
        save_gate_v_campaign_manifest,
    )

    plan = build_gate_v_campaign_plan(**_plan_kwargs(tmp_path))
    manifest = build_gate_v_campaign_manifest(plan)
    from gate_v_campaign import save_gate_v_campaign_plan
    root = tmp_path / "gate_v_campaign"
    save_gate_v_campaign_plan(root, plan)
    path = save_gate_v_campaign_manifest(root, plan, manifest)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["parameter_stability_validation_run_ids_by_fold"] = {
        "foreign_fold": "foreign_campaign_parameter_stability",
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="fold|campagne"):
        load_gate_v_campaign_manifest(path, plan)


def test_manifest_save_refuses_to_erase_completed_phase_references(tmp_path):
    from gate_v_campaign import (
        build_gate_v_campaign_manifest, gate_v_validation_run_id,
        save_gate_v_campaign_manifest, load_gate_v_campaign_manifest,
    )

    plan, runs, wf_id, _mc_id, _ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    root = tmp_path / "gate_v_campaign"
    from gate_v_campaign import save_gate_v_campaign_plan
    save_gate_v_campaign_plan(root, plan)
    ready = build_gate_v_campaign_manifest(plan)
    running = dataclasses.replace(ready, execution_started=True, running=True, status="RUNNING")
    save_gate_v_campaign_manifest(root, plan, running)
    save_validation_run(
        root / plan.campaign_id / "validations" / wf_id / "validation_run.json", runs[wf_id],
    )
    progressed = dataclasses.replace(
        running, walk_forward_validation_run_id=wf_id,
        status="EVIDENCE_INCOMPLETE", running=False,
    )
    path = save_gate_v_campaign_manifest(root, plan, progressed)
    with pytest.raises(ValueError, match="preuve|référence|effac"):
        save_gate_v_campaign_manifest(
            root, plan, dataclasses.replace(progressed, walk_forward_validation_run_id=None),
        )
    assert load_gate_v_campaign_manifest(path, plan) == progressed


def test_manifest_save_refuses_unpersisted_reference_even_if_incomplete(tmp_path):
    from gate_v_campaign import (
        build_gate_v_campaign_manifest, gate_v_validation_run_id,
        save_gate_v_campaign_manifest, save_gate_v_campaign_plan,
    )

    plan = build_gate_v_campaign_plan(**_plan_kwargs(tmp_path))
    root = tmp_path / "gate_v_campaign"
    save_gate_v_campaign_plan(root, plan)
    manifest = dataclasses.replace(
        build_gate_v_campaign_manifest(plan), execution_started=True,
        status="EVIDENCE_INCOMPLETE",
        walk_forward_validation_run_id=gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD),
    )
    with pytest.raises(ValueError, match="preuve|fichier|ValidationRun"):
        save_gate_v_campaign_manifest(root, plan, manifest)


def test_manifest_load_rejects_corrupt_existing_file(tmp_path):
    from gate_v_campaign import load_gate_v_campaign_manifest

    plan = build_gate_v_campaign_plan(**_plan_kwargs(tmp_path))
    path = tmp_path / "gate_v_campaign" / plan.campaign_id / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text("{bad-json", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest.json"):
        load_gate_v_campaign_manifest(path, plan)


def test_manifest_load_rejects_missing_persisted_plan(tmp_path):
    from gate_v_campaign import (
        build_gate_v_campaign_manifest, load_gate_v_campaign_manifest,
        save_gate_v_campaign_manifest, save_gate_v_campaign_plan,
    )

    plan = build_gate_v_campaign_plan(**_plan_kwargs(tmp_path))
    root = tmp_path / "gate_v_campaign"
    plan_path = save_gate_v_campaign_plan(root, plan)
    manifest_path = save_gate_v_campaign_manifest(root, plan, build_gate_v_campaign_manifest(plan))
    plan_path.unlink()
    with pytest.raises(ValueError, match="plan.json"):
        load_gate_v_campaign_manifest(manifest_path, plan)


def test_manifest_cannot_persist_complete_status_without_verified_evidence(tmp_path):
    from gate_v_campaign import save_gate_v_campaign_manifest

    plan, runs, wf_id, mc_id, ps_by_fold = _synthetic_campaign_evidence(tmp_path)
    manifest = dataclasses.replace(
        _complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold),
        status="EVIDENCE_COMPLETE_AWAITING_POLICY",
    )
    root = tmp_path / "gate_v_campaign"
    from gate_v_campaign import save_gate_v_campaign_plan
    save_gate_v_campaign_plan(root, plan)
    with pytest.raises(ValueError, match="preuve|evidence|statut"):
        save_gate_v_campaign_manifest(root, plan, manifest)
    with pytest.raises(ValueError, match="persist|fichier|preuve"):
        save_gate_v_campaign_manifest(
            root, plan, manifest, evidence_by_validation_run_id=runs,
        )
    paths = {}
    for run_id, run in runs.items():
        if run_id == plan.oos_evidence_validation_run_id:
            paths[run_id] = plan.oos_evidence_path
        else:
            path = root / plan.campaign_id / "validations" / run_id / "validation_run.json"
            save_validation_run(path, run)
            paths[run_id] = path
    path = save_gate_v_campaign_manifest(
        root, plan, manifest, evidence_by_validation_run_id=runs,
        evidence_paths_by_validation_run_id=paths,
    )
    assert path.is_file()
    from gate_v_campaign import load_gate_v_campaign_manifest
    assert load_gate_v_campaign_manifest(path, plan) == manifest
    paths[ps_by_fold[plan.expected_fold_ids[0]]].unlink()
    with pytest.raises(ValueError, match="preuve|fichier|ValidationRun"):
        load_gate_v_campaign_manifest(path, plan)


# ══════════════════════════════════════════════════════════════════════════════
# AF-V-08 Slice 3 — execute_gate_v_campaign(), phase Walk-Forward uniquement.
# Monte-Carlo/Parameter Stability restent hors scope (slices suivantes) : ces fixtures ne les
# construisent ni ne les référencent jamais. Aucun test ici n'ouvre nasdaq_3m.csv ni n'accède
# FINAL_HOLDOUT -- load_market_data_fn est toujours une doublure retournant un DataFrame vide.
# ══════════════════════════════════════════════════════════════════════════════

def _execute_data_manifest(tmp_path):
    manifest = build_backtest_manifest(
        provider="mt5", instrument="US100", provider_symbol="US100Cash",
        source_timeframe="M3", snapshot_id="snap-gate-v-slice3",
        content_hash="hash-gate-v-slice3", git_commit="deadbeefcafe",
        strategy_version="perfect_revolution_v1",
    )
    path = tmp_path / "data_manifest.json"
    save_backtest_manifest(path, manifest)
    return path


def _execute_base_config(plan):
    return OptimizationConfig(
        run_id="gate_v_slice3_test", strategy_module="strategies.perfect_revolution_v1",
        strategy_name=plan.strategy_name, data_file="unused.csv",
        base_params=dict(plan.base_params), param_ranges=[], mode=plan.search_mode,
        score_weights=ScoreWeights(), filters=FilterConfig(), train_test=TrainTestConfig(),
        global_params={}, n_workers=1,
    )


def _execute_ready_campaign(tmp_path, **plan_overrides):
    from gate_v_campaign import save_gate_v_campaign_plan

    inputs = _plan_kwargs(tmp_path)
    inputs.update(plan_overrides)
    plan = build_gate_v_campaign_plan(**inputs)
    campaign_root = tmp_path / "gate_v_campaign"
    save_gate_v_campaign_plan(campaign_root, plan)
    split_plan = load_dataset_split_plan(plan.split_plan_path)
    return plan, split_plan, campaign_root


def _execute_fold_results_and_artifacts(plan, split_plan, fold_ids=None):
    definitions = compute_fold_definitions(
        split_plan.validation, plan.walk_forward_specification, plan.readiness_spec,
    )
    if fold_ids is not None:
        definitions = [d for d in definitions if d.fold_id in fold_ids]
    results, artifacts = [], []
    for definition in definitions:
        selection = FoldSelection(
            fold_id=definition.fold_id, selected_params={"lookback": 12},
            selected_params_hash=params_hash({"lookback": 12}), score_train=1.0, rank_in_train=1,
            train_candidates_evaluated=1, train_candidates_unique=1, train_candidates_eligible=1,
            search_space_hash=plan.search_space_hash, algorithm=plan.search_mode, fold_seed=None,
        )
        results.append(FoldResult(
            fold_id=definition.fold_id, definition=definition, selection=selection,
            n_trades=0, net_ret_pct=0.0, max_dd_pct=None, profit_factor=None,
            win_rate=None, expectancy=None, score_test=0.0, zero_trade_oos=True,
            forced_closes=0, coverage_bars=1,
        ))
        artifacts.append(FoldArtifacts(
            fold_id=definition.fold_id,
            train_candidates=[{
                "params": {"lookback": 12}, "score": 1.0, "stats": {"n_trades": 0},
                "filtered": False, "filter_reason": None,
            }],
            test_trades=pd.DataFrame({"resultat_net": pd.Series(dtype=float)}),
            test_equity=pd.DataFrame({"capital": [10_000.0]}),
        ))
    return tuple(results), tuple(artifacts)


def _execute_fold_results_and_artifacts_with_trades(plan, split_plan, trades_by_fold):
    """`trades_by_fold` : `{fold_id: [{"resultat_net":..., "capital_apres":...}, ...]}`, ordre
    chronologique. `date_entree`/`date_sortie` sont auto-remplies dans la fenêtre TEST effective
    RÉELLE de leur fold (sauf si déjà fournies par l'appelant, pour les tests négatifs) --
    jamais des dates hors bornes par défaut. Fold absent du mapping -> zéro trade, avec la même
    forme `pd.DataFrame()` (colonnes vides) que `engine.py::run_backtest()` produit réellement
    pour un fold zéro-trade (`trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()`)
    -- jamais un DataFrame "zéro ligne mais avec colonnes", qui ne reproduirait pas fidèlement
    `EmptyDataError` au rechargement CSV réel."""
    from datetime import timedelta

    definitions = compute_fold_definitions(
        split_plan.validation, plan.walk_forward_specification, plan.readiness_spec,
    )
    results, artifacts = [], []
    for definition in definitions:
        raw_rows = trades_by_fold.get(definition.fold_id, [])
        rows = []
        boundary = datetime.fromisoformat(definition.effective_boundary)
        for idx, row in enumerate(raw_rows):
            filled = dict(row)
            entry = boundary + timedelta(days=idx)
            filled.setdefault("date_entree", entry.isoformat())
            filled.setdefault("date_sortie", (entry + timedelta(hours=1)).isoformat())
            rows.append(filled)
        n_trades = len(rows)
        selection = FoldSelection(
            fold_id=definition.fold_id, selected_params={"lookback": 12},
            selected_params_hash=params_hash({"lookback": 12}), score_train=1.0, rank_in_train=1,
            train_candidates_evaluated=1, train_candidates_unique=1, train_candidates_eligible=1,
            search_space_hash=plan.search_space_hash, algorithm=plan.search_mode, fold_seed=None,
        )
        results.append(FoldResult(
            fold_id=definition.fold_id, definition=definition, selection=selection,
            n_trades=n_trades,
            net_ret_pct=0.0 if n_trades == 0 else 1.0,
            max_dd_pct=None if n_trades == 0 else 0.5,
            profit_factor=None if n_trades == 0 else 1.2,
            win_rate=None if n_trades == 0 else 50.0,
            expectancy=None if n_trades == 0 else 1.0,
            score_test=0.0, zero_trade_oos=(n_trades == 0), forced_closes=0, coverage_bars=1,
        ))
        artifacts.append(FoldArtifacts(
            fold_id=definition.fold_id,
            train_candidates=[{
                "params": {"lookback": 12}, "score": 1.0, "stats": {"n_trades": n_trades},
                "filtered": False, "filter_reason": None,
            }],
            test_trades=pd.DataFrame(rows) if rows else pd.DataFrame(),
            test_equity=pd.DataFrame({"capital": [10_000.0]}),
        ))
    return tuple(results), tuple(artifacts)


def _real_capture_delegate(results, artifacts, *, resume=False):
    """AF-V-08 Slice 5 : doublure run_walk_forward_fn/resume_walk_forward_fn qui délègue à la
    VRAIE `run_walk_forward_with_artifacts_v1()`/`resume_walk_forward_with_artifacts_v1()`, avec
    UNIQUEMENT `execute_walk_forward_fold_with_artifacts` monkeypatché (même technique que
    Parameter Stability -- jamais de logique de checkpoint dupliquée ici) -- écrit donc de VRAIS
    checkpoints V1 sur disque, requis depuis que Parameter Stability s'enchaîne automatiquement
    après Monte-Carlo dans le même appel `execute_gate_v_campaign()`."""
    results_by_id = {r.fold_id: r for r in results}
    artifacts_by_id = {a.fold_id: a for a in artifacts}

    def low_level(fold, base_config, df, progress_cb=None, stop_flag_fn=None, fold_seed=None):
        return results_by_id[fold.fold_id], artifacts_by_id[fold.fold_id]

    real_fn = (
        walk_forward.resume_walk_forward_with_artifacts_v1 if resume
        else walk_forward.run_walk_forward_with_artifacts_v1
    )

    def fn(validation_zone, spec, readiness_spec, base_config, df, *,
           data_manifest_path, output_dir, progress_cb=None, stop_flag_fn=None,
           validation_run_id):
        original = walk_forward.execute_walk_forward_fold_with_artifacts
        walk_forward.execute_walk_forward_fold_with_artifacts = low_level
        try:
            return real_fn(
                validation_zone, spec, readiness_spec, base_config, df,
                data_manifest_path=data_manifest_path, output_dir=output_dir,
                progress_cb=progress_cb, stop_flag_fn=stop_flag_fn,
                validation_run_id=validation_run_id,
            )
        finally:
            walk_forward.execute_walk_forward_fold_with_artifacts = original
    return fn


def _execute_fake_run_with_trades(plan, split_plan, trades_by_fold, *, wrong_validation_run_id=None):
    calls = []
    results, artifacts = _execute_fold_results_and_artifacts_with_trades(plan, split_plan, trades_by_fold)

    if wrong_validation_run_id is None:
        delegate = _real_capture_delegate(results, artifacts)

        def fn(*args, **kwargs):
            calls.append(kwargs["validation_run_id"])
            return delegate(*args, **kwargs)
        return fn, calls

    def fn(validation_zone, spec, readiness_spec, base_config, df, *,
           data_manifest_path, output_dir, progress_cb=None, stop_flag_fn=None,
           validation_run_id):
        calls.append(validation_run_id)
        outcome = WalkForwardRunOutcome(fold_results=results, stopped_early=False)
        aggregate = build_aggregate_result(results)
        return WalkForwardCapturedRunV1(
            outcome=outcome, fold_artifacts=artifacts,
            validation_run_id=wrong_validation_run_id or validation_run_id,
            aggregate=aggregate,
        )
    return fn, calls


def _execute_fake_run(plan, split_plan, *, stopped_early=False, fold_ids=None,
                       wrong_validation_run_id=None):
    """Doublure de run_walk_forward_fn/resume_walk_forward_fn -- ne touche jamais l'Optimizer/
    le moteur réel. Cas complet (pas d'arrêt anticipé, pas de sous-ensemble de folds, pas d'ID
    forgé) : délègue à `_real_capture_delegate()` -- écrit de VRAIS checkpoints V1, requis par
    Parameter Stability (Slice 5) qui s'enchaîne automatiquement après Monte-Carlo. Cas
    dégénérés/négatifs (utilisés pour tester le rejet AVANT toute persistance -- Parameter
    Stability jamais atteinte dans ces scénarios) : construit toujours un WalkForwardCapturedRunV1
    synthétique en mémoire, comme avant Slice 5."""
    calls = []
    results, artifacts = _execute_fold_results_and_artifacts(plan, split_plan, fold_ids=fold_ids)
    use_real_checkpoint = not stopped_early and fold_ids is None and wrong_validation_run_id is None

    if use_real_checkpoint:
        delegate = _real_capture_delegate(results, artifacts)

        def fn(*args, **kwargs):
            calls.append(kwargs["validation_run_id"])
            return delegate(*args, **kwargs)
        return fn, calls

    def fn(validation_zone, spec, readiness_spec, base_config, df, *,
           data_manifest_path, output_dir, progress_cb=None, stop_flag_fn=None,
           validation_run_id):
        calls.append(validation_run_id)
        outcome = WalkForwardRunOutcome(fold_results=results, stopped_early=stopped_early)
        aggregate = build_aggregate_result(results)
        return WalkForwardCapturedRunV1(
            outcome=outcome, fold_artifacts=artifacts,
            validation_run_id=wrong_validation_run_id or validation_run_id,
            aggregate=aggregate,
        )
    return fn, calls


def _never_called(name):
    def fn(*args, **kwargs):
        raise AssertionError(f"{name} ne devait jamais être appelé dans ce scénario.")
    return fn


def _execute(plan, campaign_root, tmp_path, *, run_walk_forward_fn, resume_walk_forward_fn,
             load_market_data_fn=None, base_config=None, data_manifest_path=None,
             progress_cb=None, stop_flag_fn=None):
    from gate_v_campaign import execute_gate_v_campaign

    return execute_gate_v_campaign(
        plan, campaign_root=campaign_root,
        base_config=base_config or _execute_base_config(plan),
        data_manifest_path=data_manifest_path or _execute_data_manifest(tmp_path),
        load_market_data_fn=load_market_data_fn or (lambda: pd.DataFrame()),
        run_walk_forward_fn=run_walk_forward_fn, resume_walk_forward_fn=resume_walk_forward_fn,
        progress_cb=progress_cb, stop_flag_fn=stop_flag_fn,
    )


class TestExecuteGateVCampaignWalkForwardPhase:
    """AF-V-08 Slice 3 : squelette Niveau B (ADR 0024 Décision 5), phase Walk-Forward
    uniquement. Monte-Carlo/Parameter Stability : hors scope, jamais appelés ici."""

    def test_fresh_calls_run_once_never_resume_and_attaches_evidence(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, run_calls = _execute_fake_run(plan, split_plan)
        resume_fn = _never_called("resume_walk_forward_fn")

        manifest = _execute(
            plan, campaign_root, tmp_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=resume_fn,
        )

        assert len(run_calls) == 1
        wf_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
        assert manifest.walk_forward_validation_run_id == wf_id
        assert manifest.execution_started is True
        assert manifest.running is False
        assert manifest.status == "EVIDENCE_INCOMPLETE"  # aucune preuve OOS/MC/PS ici
        assert "PASS" not in manifest.status
        wf_run_path = campaign_root / plan.campaign_id / "validations" / wf_id / "validation_run.json"
        assert wf_run_path.is_file()
        persisted = load_validation_run(wf_run_path)
        assert persisted.validation_run_id == wf_id
        assert (campaign_root / plan.campaign_id / "walk_forward" / "aggregate.json").is_file()

    def test_resumes_when_checkpoint_present_never_calls_run(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        results, artifacts = _execute_fold_results_and_artifacts(plan, split_plan)
        data_manifest_path = _execute_data_manifest(tmp_path)
        wf_output_dir = campaign_root / plan.campaign_id / "walk_forward"
        wf_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
        # Checkpoint V1 RÉEL et déjà complet (simule une capture antérieure terminée mais dont
        # la ValidationRun n'a jamais été persistée/rattachée) -- requis depuis Slice 5 puisque
        # Parameter Stability relit ces checkpoints après Walk-Forward+Monte-Carlo.
        _real_capture_delegate(results, artifacts)(
            split_plan.validation, plan.walk_forward_specification, plan.readiness_spec,
            _execute_base_config(plan), pd.DataFrame(),
            data_manifest_path=data_manifest_path, output_dir=wf_output_dir,
            validation_run_id=wf_id,
        )
        resume_delegate = _real_capture_delegate(results, artifacts, resume=True)
        resume_calls = []

        def resume_fn(*args, **kwargs):
            resume_calls.append(kwargs["validation_run_id"])
            return resume_delegate(*args, **kwargs)
        run_fn = _never_called("run_walk_forward_fn")

        manifest = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=resume_fn,
        )

        assert len(resume_calls) == 1
        assert manifest.walk_forward_validation_run_id is not None

    def test_already_persisted_skips_run_resume_and_persist(self, tmp_path, monkeypatch):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        results, artifacts = _execute_fold_results_and_artifacts(plan, split_plan)
        aggregate = build_aggregate_result(results)
        outcome = WalkForwardRunOutcome(fold_results=results, stopped_early=False)
        wf_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
        wf_output_dir = campaign_root / plan.campaign_id / "walk_forward"
        data_manifest_path = _execute_data_manifest(tmp_path)
        # Checkpoint V1 RÉEL correspondant (requis depuis Slice 5 : Parameter Stability relit ces
        # checkpoints après Walk-Forward+Monte-Carlo, même quand Walk-Forward est reconciliée
        # depuis une ValidationRun déjà persistée plutôt que recalculée dans cet appel) -- écrit
        # AVANT `persist_walk_forward_run()` : `_prepare_captured_run(resume=False)` refuse une
        # capture fraîche si le manifeste LEGACY (`walk_forward/manifest.json`) existe déjà.
        _real_capture_delegate(results, artifacts)(
            split_plan.validation, plan.walk_forward_specification, plan.readiness_spec,
            _execute_base_config(plan), pd.DataFrame(),
            data_manifest_path=data_manifest_path, output_dir=wf_output_dir,
            validation_run_id=wf_id,
        )
        persist_walk_forward_run(
            outcome, artifacts, aggregate, plan.walk_forward_specification,
            _execute_base_config(plan), data_manifest_path, wf_output_dir,
            validation_run_id=wf_id,
        )
        persist_calls = []
        monkeypatch.setattr(
            gate_v_campaign, "persist_walk_forward_run",
            lambda *a, **k: persist_calls.append(1) or (_ for _ in ()).throw(
                AssertionError("persist_walk_forward_run ne devait jamais être rappelée")
            ),
        )

        manifest = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=_never_called("run_walk_forward_fn"),
            resume_walk_forward_fn=_never_called("resume_walk_forward_fn"),
            load_market_data_fn=_never_called("load_market_data_fn"),
        )

        assert manifest.walk_forward_validation_run_id == wf_id
        assert persist_calls == []

    def test_fresh_complete_persists_walk_forward_exactly_once(self, tmp_path, monkeypatch):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run(plan, split_plan)
        real_persist = gate_v_campaign.persist_walk_forward_run
        persist_calls = []

        def spy_persist(*args, **kwargs):
            persist_calls.append(1)
            return real_persist(*args, **kwargs)
        monkeypatch.setattr(gate_v_campaign, "persist_walk_forward_run", spy_persist)

        _execute(
            plan, campaign_root, tmp_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )

        assert len(persist_calls) == 1

    def test_partial_stop_never_persisted_as_complete_walk_forward(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, run_calls = _execute_fake_run(
            plan, split_plan, stopped_early=True, fold_ids=[plan.expected_fold_ids[0]],
        )

        manifest = _execute(
            plan, campaign_root, tmp_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )

        assert len(run_calls) == 1
        assert manifest.walk_forward_validation_run_id is None
        assert manifest.status == "EVIDENCE_INCOMPLETE"
        assert manifest.running is False
        assert manifest.execution_started is True
        # AF-V-08 checkpoint de stabilisation (2026-09-28) -- une interruption COOPÉRATIVE
        # (stopped_early=True, aucune exception levée) n'est jamais une TECHNICAL_FAILURE.
        assert manifest.status != "TECHNICAL_FAILURE"
        assert manifest.technical_failure_reason is None
        wf_output_dir = campaign_root / plan.campaign_id / "walk_forward"
        assert not (wf_output_dir / "aggregate.json").exists()

    def test_rejects_captured_run_with_missing_fold_claimed_complete(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run(
            plan, split_plan, stopped_early=False, fold_ids=[plan.expected_fold_ids[0]],
        )

        with pytest.raises(ValueError, match="fold|stopped_early"):
            _execute(
                plan, campaign_root, tmp_path,
                run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
            )

    def test_rejects_captured_run_with_duplicate_fold(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        results, artifacts = _execute_fold_results_and_artifacts(plan, split_plan)
        duplicated_results = (results[0], results[0])
        duplicated_artifacts = (artifacts[0], artifacts[0])

        def run_fn(validation_zone, spec, readiness_spec, base_config, df, *,
                   data_manifest_path, output_dir, progress_cb=None, stop_flag_fn=None,
                   validation_run_id):
            return WalkForwardCapturedRunV1(
                outcome=WalkForwardRunOutcome(fold_results=duplicated_results, stopped_early=False),
                fold_artifacts=duplicated_artifacts, validation_run_id=validation_run_id,
                aggregate=build_aggregate_result(duplicated_results),
            )

        with pytest.raises(ValueError, match="fold"):
            _execute(
                plan, campaign_root, tmp_path,
                run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
            )

    def test_rejects_wrong_validation_run_id_from_collaborator(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run(
            plan, split_plan, wrong_validation_run_id="foreign_walk_forward_id",
        )

        with pytest.raises(ValueError, match="validation_run_id"):
            _execute(
                plan, campaign_root, tmp_path,
                run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
            )

    def test_rejects_base_config_diverging_from_plan(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        wrong_config = dataclasses.replace(_execute_base_config(plan), mode="general")

        with pytest.raises(ValueError, match="base_config"):
            _execute(
                plan, campaign_root, tmp_path, base_config=wrong_config,
                run_walk_forward_fn=_never_called("run"),
                resume_walk_forward_fn=_never_called("resume"),
                load_market_data_fn=_never_called("load_market_data_fn"),
            )

    def test_rejects_forged_plan(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        forged = dataclasses.replace(plan, campaign_id="forged_campaign_id")

        with pytest.raises(ValueError, match="plan"):
            _execute(
                forged, campaign_root, tmp_path,
                run_walk_forward_fn=_never_called("run"),
                resume_walk_forward_fn=_never_called("resume"),
                load_market_data_fn=_never_called("load_market_data_fn"),
            )

    def test_rejects_incoherent_aggregate_before_persisting_evidence(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        results, artifacts = _execute_fold_results_and_artifacts(plan, split_plan)
        bad_aggregate = dataclasses.replace(build_aggregate_result(results), n_folds=999)

        def run_fn(validation_zone, spec, readiness_spec, base_config, df, *,
                   data_manifest_path, output_dir, progress_cb=None, stop_flag_fn=None,
                   validation_run_id):
            return WalkForwardCapturedRunV1(
                outcome=WalkForwardRunOutcome(fold_results=results, stopped_early=False),
                fold_artifacts=artifacts, validation_run_id=validation_run_id,
                aggregate=bad_aggregate,
            )

        with pytest.raises(ValueError, match="incomplète|incohérente"):
            _execute(
                plan, campaign_root, tmp_path,
                run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
            )
        wf_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
        wf_run_path = campaign_root / plan.campaign_id / "validations" / wf_id / "validation_run.json"
        assert not wf_run_path.exists()

    def test_persists_running_manifest_before_costly_walk_forward_call(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        base_run_fn, _calls = _execute_fake_run(plan, split_plan)
        observed = {}

        def spying_run_fn(*args, **kwargs):
            record = json.loads(manifest_path.read_text(encoding="utf-8"))
            observed["status"] = record["status"]
            observed["running"] = record["running"]
            observed["execution_started"] = record["execution_started"]
            return base_run_fn(*args, **kwargs)

        _execute(
            plan, campaign_root, tmp_path,
            run_walk_forward_fn=spying_run_fn, resume_walk_forward_fn=_never_called("resume"),
        )

        assert observed == {"status": "RUNNING", "running": True, "execution_started": True}

    def test_technical_exception_propagates_and_persists_technical_failure(self, tmp_path):
        """AF-V-08 checkpoint de stabilisation (2026-09-28), corrige ADR 0024 Décision 7 :
        une exception technique NON gérée survenue APRÈS le passage à `running=True` doit être
        persistée comme `TECHNICAL_FAILURE` (jamais laissée `RUNNING`, jamais traduite en
        `EVIDENCE_INCOMPLETE`) -- puis l'exception originale continue de remonter intacte."""
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)

        def failing_run_fn(*args, **kwargs):
            raise RuntimeError("synthetic engine crash")

        with pytest.raises(RuntimeError, match="synthetic engine crash"):
            _execute(
                plan, campaign_root, tmp_path,
                run_walk_forward_fn=failing_run_fn, resume_walk_forward_fn=_never_called("resume"),
            )

        from gate_v_campaign import load_gate_v_campaign_manifest
        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        reloaded = load_gate_v_campaign_manifest(manifest_path, plan)
        assert reloaded.status == "TECHNICAL_FAILURE"
        assert reloaded.running is False
        assert reloaded.execution_started is True
        assert isinstance(reloaded.technical_failure_reason, str) and reloaded.technical_failure_reason.strip()
        assert "synthetic engine crash" in reloaded.technical_failure_reason
        assert reloaded.walk_forward_validation_run_id is None

    def test_refuses_retry_on_technical_failure_manifest(self, tmp_path):
        from gate_v_campaign import build_gate_v_campaign_manifest, save_gate_v_campaign_manifest

        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        failed = dataclasses.replace(
            build_gate_v_campaign_manifest(plan), execution_started=True,
            technical_failure_reason="synthetic interruption", status="TECHNICAL_FAILURE",
        )
        save_gate_v_campaign_manifest(campaign_root, plan, failed)

        with pytest.raises(ValueError, match="TECHNICAL_FAILURE"):
            _execute(
                plan, campaign_root, tmp_path,
                run_walk_forward_fn=_never_called("run"),
                resume_walk_forward_fn=_never_called("resume"),
                load_market_data_fn=_never_called("load_market_data_fn"),
            )

    def test_reconciles_already_persisted_validation_run_without_recompute(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, run_calls = _execute_fake_run(plan, split_plan)
        data_manifest_path = _execute_data_manifest(tmp_path)

        manifest = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )
        assert len(run_calls) == 1

        # Simule un crash APRES save_validation_run() mais AVANT la mise a jour du manifeste
        # (risque explicitement anticipe par la mission AF-V-08 precedente). Depuis la Slice 4,
        # un appel complet rattache AUSSI Monte-Carlo dans la foulee, et depuis la Slice 5
        # Parameter Stability aussi -- reinitialiser les TROIS references (jamais MC/PS seules
        # sans WF, regle structurelle deja existante, Slice 2) pour rester un manifeste valide a
        # relire.
        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        record["walk_forward_validation_run_id"] = None
        record["monte_carlo_validation_run_id"] = None
        record["parameter_stability_validation_run_ids_by_fold"] = {}
        record["status"] = "RUNNING"
        record["running"] = True
        manifest_path.write_text(json.dumps(record), encoding="utf-8")

        reconciled = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=_never_called("run_walk_forward_fn"),
            resume_walk_forward_fn=_never_called("resume_walk_forward_fn"),
            load_market_data_fn=_never_called("load_market_data_fn"),
        )

        assert reconciled.walk_forward_validation_run_id == manifest.walk_forward_validation_run_id
        assert reconciled.monte_carlo_validation_run_id == manifest.monte_carlo_validation_run_id

    def test_parameter_stability_wired_but_never_injected(self):
        """Depuis la Slice 5, Parameter Stability s'enchaîne automatiquement après Walk-Forward+
        Monte-Carlo dans `execute_gate_v_campaign()` (via `_run_parameter_stability_phase`) --
        `run_monte_carlo_simulation()`/`analyze_parameter_stability()` restent, elles, appelées
        DIRECTEMENT (fonctions pures, jamais injectées, ADR 0024 Décision 5)."""
        source = inspect.getsource(gate_v_campaign.execute_gate_v_campaign)
        assert "_run_parameter_stability_phase" in source
        signature = inspect.signature(gate_v_campaign.execute_gate_v_campaign)
        assert "run_monte_carlo_fn" not in signature.parameters
        assert "analyze_parameter_stability_fn" not in signature.parameters

    def test_collaborators_are_keyword_only_without_default(self):
        signature = inspect.signature(gate_v_campaign.execute_gate_v_campaign)
        for name in ("run_walk_forward_fn", "resume_walk_forward_fn", "load_market_data_fn"):
            param = signature.parameters[name]
            assert param.kind == inspect.Parameter.KEYWORD_ONLY
            assert param.default is inspect.Parameter.empty


# ══════════════════════════════════════════════════════════════════════════════
# AF-V-08 Slice 4, vague 1 — dérivation du rendement % par trade TEST depuis la trajectoire de
# capital réellement persistée (Human Gate 2026-09-27, ADR 0022 amendement, jamais depuis
# resultat_net directement -- invariant d'audit seulement). Fonction PURE, aucun I/O.
# ══════════════════════════════════════════════════════════════════════════════

def _fold_trades(rows):
    return pd.DataFrame(rows)


class TestDeriveFoldTestTradeReturnsPct:
    def test_first_trade_derived_from_initial_capital(self):
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        trades = _fold_trades([{"resultat_net": 100.0, "capital_apres": 10_100.0}])
        result = _derive_fold_test_trade_returns_pct(trades, 10_000.0)
        assert result == pytest.approx((1.0,))

    def test_subsequent_trades_chain_from_previous_capital_apres(self):
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        trades = _fold_trades([
            {"resultat_net": 100.0, "capital_apres": 10_100.0},
            {"resultat_net": -50.0, "capital_apres": 10_050.0},
        ])
        result = _derive_fold_test_trade_returns_pct(trades, 10_000.0)
        assert result[0] == pytest.approx(1.0)
        assert result[1] == pytest.approx((10_050.0 / 10_100.0 - 1.0) * 100.0)

    def test_two_independent_folds_each_reset_to_their_own_initial_capital(self):
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        fold_a = _fold_trades([{"resultat_net": 500.0, "capital_apres": 10_500.0}])
        fold_b = _fold_trades([{"resultat_net": 500.0, "capital_apres": 10_500.0}])
        result_a = _derive_fold_test_trade_returns_pct(fold_a, 10_000.0)
        result_b = _derive_fold_test_trade_returns_pct(fold_b, 10_000.0)
        assert result_a == result_b  # aucune fuite d'état entre deux folds (flat_each_fold_v1)

    def test_zero_trade_fold_returns_empty_tuple(self):
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        assert _derive_fold_test_trade_returns_pct(_fold_trades([]), 10_000.0) == ()

    def test_non_positive_capital_before_on_next_trade_raises(self):
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        trades = _fold_trades([
            {"resultat_net": -10_500.0, "capital_apres": -500.0},
            {"resultat_net": 10.0, "capital_apres": -490.0},
        ])
        with pytest.raises(ValueError, match="capital_before"):
            _derive_fold_test_trade_returns_pct(trades, 10_000.0)

    def test_first_trade_allows_return_at_or_below_minus_100_percent(self):
        """Un rendement réel <= -100 % n'est jamais censuré (fait persisté, pas une erreur)."""
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        trades = _fold_trades([{"resultat_net": -10_500.0, "capital_apres": -500.0}])
        result = _derive_fold_test_trade_returns_pct(trades, 10_000.0)
        assert result[0] == pytest.approx(-105.0)

    def test_non_finite_resultat_net_raises(self):
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        trades = _fold_trades([{"resultat_net": float("nan"), "capital_apres": 10_100.0}])
        with pytest.raises(ValueError, match="fini"):
            _derive_fold_test_trade_returns_pct(trades, 10_000.0)

    def test_non_finite_capital_apres_raises(self):
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        trades = _fold_trades([{"resultat_net": 100.0, "capital_apres": float("inf")}])
        with pytest.raises(ValueError, match="fini"):
            _derive_fold_test_trade_returns_pct(trades, 10_000.0)

    def test_missing_resultat_net_column_raises(self):
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        trades = pd.DataFrame({"capital_apres": [10_100.0]})
        with pytest.raises(ValueError, match="resultat_net"):
            _derive_fold_test_trade_returns_pct(trades, 10_000.0)

    def test_missing_capital_apres_column_raises(self):
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        trades = pd.DataFrame({"resultat_net": [100.0]})
        with pytest.raises(ValueError, match="capital_apres"):
            _derive_fold_test_trade_returns_pct(trades, 10_000.0)

    def test_incoherent_capital_trajectory_beyond_tolerance_raises(self):
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        trades = _fold_trades([{"resultat_net": 100.0, "capital_apres": 10_200.0}])
        with pytest.raises(ValueError, match="[Ii]ncohérence"):
            _derive_fold_test_trade_returns_pct(trades, 10_000.0)

    def test_cent_rounding_discrepancy_within_tolerance_accepted(self):
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        trades = _fold_trades([{"resultat_net": 100.01, "capital_apres": 10_100.0}])
        result = _derive_fold_test_trade_returns_pct(trades, 10_000.0)
        assert result[0] == pytest.approx(1.0, abs=1e-3)

    def test_chained_returns_reconstruct_serialized_capital_trajectory_exactly(self):
        rows = [
            {"resultat_net": 100.0, "capital_apres": 10_100.0},
            {"resultat_net": -200.0, "capital_apres": 9_900.0},
            {"resultat_net": 50.0, "capital_apres": 9_950.0},
        ]
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        returns = _derive_fold_test_trade_returns_pct(_fold_trades(rows), 10_000.0)
        rebuilt_capital = 10_000.0
        for r in returns:
            rebuilt_capital *= (1.0 + r / 100.0)
        assert rebuilt_capital == pytest.approx(rows[-1]["capital_apres"])

    def test_initial_capital_must_be_finite_and_positive(self):
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        trades = _fold_trades([{"resultat_net": 100.0, "capital_apres": 100.0}])
        for bad in (0.0, -1.0, float("nan"), float("inf")):
            with pytest.raises(ValueError, match="initial_capital"):
                _derive_fold_test_trade_returns_pct(trades, bad)

    def test_survives_real_csv_round_trip_numpy_dtypes(self, tmp_path):
        """oos_trades.csv est écrit/relu via pandas -- numpy.float64/int64 ne sont pas des
        sous-classes de float/int Python ; une validation isinstance() stricte les rejetterait
        à tort."""
        from gate_v_campaign import _derive_fold_test_trade_returns_pct

        rows = [
            {"resultat_net": 100.0, "capital_apres": 10_100.0},
            {"resultat_net": -50.0, "capital_apres": 10_050.0},
        ]
        path = tmp_path / "oos_trades.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        reloaded = pd.read_csv(path)
        result = _derive_fold_test_trade_returns_pct(reloaded, 10_000.0)
        assert result[0] == pytest.approx(1.0)
        assert result[1] == pytest.approx((10_050.0 / 10_100.0 - 1.0) * 100.0)


def _execute_base_config_stub():
    return OptimizationConfig(
        run_id="mc_stub", strategy_module="strategies.perfect_revolution_v1",
        strategy_name="test", data_file="unused.csv", base_params={"lookback": 12},
        param_ranges=[], mode="grid", score_weights=ScoreWeights(), filters=FilterConfig(),
        train_test=TrainTestConfig(), global_params={}, n_workers=1,
    )


class TestInitialCapitalFromBaseConfig:
    """ADR 0022 amendement : même clé/valeur par défaut que optimizer.py::_run_single()."""

    def test_defaults_to_ten_thousand_matching_run_single(self):
        from gate_v_campaign import _initial_capital_from_base_config

        base_config = dataclasses.replace(_execute_base_config_stub(), global_params={})
        assert _initial_capital_from_base_config(base_config) == 10_000.0

    def test_uses_explicit_value_when_present(self):
        from gate_v_campaign import _initial_capital_from_base_config

        base_config = dataclasses.replace(
            _execute_base_config_stub(), global_params={"initial_capital": 25_000.0},
        )
        assert _initial_capital_from_base_config(base_config) == 25_000.0

    @pytest.mark.parametrize("bad", [0.0, -5.0, float("nan"), float("inf")])
    def test_rejects_non_finite_or_non_positive(self, bad):
        from gate_v_campaign import _initial_capital_from_base_config

        base_config = dataclasses.replace(
            _execute_base_config_stub(), global_params={"initial_capital": bad},
        )
        with pytest.raises(ValueError, match="initial_capital"):
            _initial_capital_from_base_config(base_config)


# ══════════════════════════════════════════════════════════════════════════════
# AF-V-08 Slice 4, vague 2 — phase Monte-Carlo de execute_gate_v_campaign(), après une preuve
# Walk-Forward complète et validée. Parameter Stability reste totalement hors scope : aucun test
# ici ne l'appelle/l'importe/l'approche.
# ══════════════════════════════════════════════════════════════════════════════

_MC_TRADES_BY_FOLD = {
    "fold_000": [
        {"resultat_net": 100.0, "capital_apres": 10_100.0},
        {"resultat_net": -50.0, "capital_apres": 10_050.0},
    ],
    "fold_001": [
        {"resultat_net": 200.0, "capital_apres": 10_200.0},
    ],
}

_MC_TRADES_BY_FOLD_WITH_ONE_ZERO_TRADE_FOLD = {
    "fold_000": [
        {"resultat_net": 100.0, "capital_apres": 10_100.0},
        {"resultat_net": -50.0, "capital_apres": 10_050.0},
    ],
    # fold_001 absent -> pd.DataFrame() sans colonnes, forme EXACTE d'engine.py pour un fold
    # zero-trade (trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()) -- déclenche
    # réellement pandas.errors.EmptyDataError à la relecture CSV, jamais un DataFrame "0 ligne
    # mais avec colonnes" qui contournerait ce cas précis.
}


class TestExecuteGateVCampaignMonteCarloPhase:
    def test_fresh_walk_forward_run_continues_into_monte_carlo_in_same_call(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, run_calls = _execute_fake_run_with_trades(plan, split_plan, _MC_TRADES_BY_FOLD)

        manifest = _execute(
            plan, campaign_root, tmp_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )

        assert len(run_calls) == 1
        wf_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
        mc_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO)
        assert manifest.walk_forward_validation_run_id == wf_id
        assert manifest.monte_carlo_validation_run_id == mc_id
        assert manifest.status == "EVIDENCE_INCOMPLETE"  # Parameter Stability toujours absente
        assert "PASS" not in manifest.status

        mc_run_path = campaign_root / plan.campaign_id / "validations" / mc_id / "validation_run.json"
        assert mc_run_path.is_file()
        mc_run = load_validation_run(mc_run_path)
        assert mc_run.validation_run_id == mc_id
        assert mc_run.specification.source_validation_run_id == wf_id
        assert mc_run.specification.source_trades_from_optimized_params is True
        assert mc_run.evidence.n_input_trades == 3
        assert mc_run.evidence.zero_trade_input is False
        assert mc_run.evidence.execution_status == "completed"

    def test_trades_concatenated_in_fold_order_never_train_candidates(self, tmp_path):
        """Rendements attendus : fold_000 [1.0, -0.495...], fold_001 [2.0] -- jamais depuis
        train_candidates.csv (jamais lu par cette phase)."""
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run_with_trades(plan, split_plan, _MC_TRADES_BY_FOLD)

        manifest = _execute(
            plan, campaign_root, tmp_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )

        mc_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO)
        mc_run_path = campaign_root / plan.campaign_id / "validations" / mc_id / "validation_run.json"
        mc_run = load_validation_run(mc_run_path)
        expected_r2 = (10_050.0 / 10_100.0 - 1.0) * 100.0
        expected_net_ret = ((1.0 + 1.0 / 100.0) * (1.0 + expected_r2 / 100.0) * (1.0 + 2.0 / 100.0) - 1.0) * 100.0
        assert mc_run.evidence.observed_net_ret_pct == pytest.approx(expected_net_ret)

    def test_rejects_trade_outside_its_fold_test_window(self, tmp_path):
        """ADR 0021 Décision 4 : un trade daté hors de la fenêtre TEST de SON fold est refusé --
        c'est aussi le mécanisme de détection de duplication inter-fold (§7.5), les fenêtres TEST
        ne se chevauchant jamais entre folds."""
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        foreign_row = {
            "resultat_net": 100.0, "capital_apres": 10_100.0,
            "date_entree": "1999-01-01T00:00:00+00:00",  # bien avant toute fenêtre TEST réelle
        }
        run_fn, _calls = _execute_fake_run_with_trades(
            plan, split_plan, {"fold_000": [foreign_row]},
        )

        with pytest.raises(ValueError, match="fenêtre TEST|date_entree"):
            _execute(
                plan, campaign_root, tmp_path,
                run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
            )

    def test_rejects_missing_date_entree_column(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        definitions = compute_fold_definitions(
            split_plan.validation, plan.walk_forward_specification, plan.readiness_spec,
        )
        selection = FoldSelection(
            fold_id=definitions[0].fold_id, selected_params={"lookback": 12},
            selected_params_hash="synthetic_hash", score_train=1.0, rank_in_train=1,
            train_candidates_evaluated=2, train_candidates_unique=2, train_candidates_eligible=2,
            search_space_hash=plan.search_space_hash, algorithm=plan.search_mode, fold_seed=None,
        )
        results = [FoldResult(
            fold_id=d.fold_id, definition=d, selection=dataclasses.replace(selection, fold_id=d.fold_id),
            n_trades=(1 if d.fold_id == definitions[0].fold_id else 0),
            net_ret_pct=0.0, max_dd_pct=None, profit_factor=None, win_rate=None, expectancy=None,
            score_test=0.0, zero_trade_oos=(d.fold_id != definitions[0].fold_id),
            forced_closes=0, coverage_bars=1,
        ) for d in definitions]
        artifacts = [FoldArtifacts(
            fold_id=d.fold_id,
            train_candidates=[{
                "params": {"lookback": 12}, "score": 1.0, "stats": {"n_trades": 0},
                "filtered": False, "filter_reason": None,
            }],
            # Colonne date_entree délibérément absente, contrairement au schéma réel engine.py.
            test_trades=(
                pd.DataFrame({"resultat_net": [100.0], "capital_apres": [10_100.0]})
                if d.fold_id == definitions[0].fold_id else pd.DataFrame()
            ),
            test_equity=pd.DataFrame({"capital": [10_000.0]}),
        ) for d in definitions]

        def run_fn(validation_zone, spec, readiness_spec, base_config, df, *,
                   data_manifest_path, output_dir, progress_cb=None, stop_flag_fn=None,
                   validation_run_id):
            outcome = WalkForwardRunOutcome(fold_results=tuple(results), stopped_early=False)
            return WalkForwardCapturedRunV1(
                outcome=outcome, fold_artifacts=tuple(artifacts),
                validation_run_id=validation_run_id, aggregate=build_aggregate_result(results),
            )

        with pytest.raises(ValueError, match="date_entree"):
            _execute(
                plan, campaign_root, tmp_path,
                run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
            )

    def test_one_zero_trade_fold_among_others_hits_empty_csv_read_path(self, tmp_path):
        """Reproduit la forme EXACTE d'un oos_trades.csv réellement écrit par engine.py pour un
        fold zéro-trade (pandas.errors.EmptyDataError à la relecture) -- jamais la forme "0 ligne
        mais colonnes définies" utilisée par la fixture Slice 3 pour un autre usage."""
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run_with_trades(
            plan, split_plan, _MC_TRADES_BY_FOLD_WITH_ONE_ZERO_TRADE_FOLD,
        )

        manifest = _execute(
            plan, campaign_root, tmp_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )

        mc_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO)
        mc_run_path = campaign_root / plan.campaign_id / "validations" / mc_id / "validation_run.json"
        mc_run = load_validation_run(mc_run_path)
        assert mc_run.evidence.n_input_trades == 2  # seulement fold_000, fold_001 contribue 0
        assert mc_run.evidence.zero_trade_input is False

    def test_global_zero_trades_still_executes_monte_carlo(self, tmp_path):
        """ADR 0022 Décision 7 : zéro trade global reste un cas valide, jamais une exception."""
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run(plan, split_plan)  # fixture Slice 3 : folds zéro-trade

        manifest = _execute(
            plan, campaign_root, tmp_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )

        assert manifest.monte_carlo_validation_run_id is not None
        mc_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO)
        mc_run_path = campaign_root / plan.campaign_id / "validations" / mc_id / "validation_run.json"
        mc_run = load_validation_run(mc_run_path)
        assert mc_run.evidence.zero_trade_input is True
        assert mc_run.evidence.n_input_trades == 0
        assert mc_run.evidence.observed_net_ret_pct is None
        # AF-V-08 checkpoint de stabilisation (2026-09-28) -- zéro trade Monte-Carlo est un fait
        # scientifique honnête, jamais une TECHNICAL_FAILURE.
        assert manifest.status != "TECHNICAL_FAILURE"
        assert manifest.technical_failure_reason is None

    def test_persists_monte_carlo_exactly_once(self, tmp_path, monkeypatch):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run_with_trades(plan, split_plan, _MC_TRADES_BY_FOLD)
        import monte_carlo
        real_run = monte_carlo.run_monte_carlo_simulation
        calls = []

        def spy(*args, **kwargs):
            calls.append(1)
            return real_run(*args, **kwargs)
        monkeypatch.setattr(gate_v_campaign, "run_monte_carlo_simulation", spy)

        _execute(
            plan, campaign_root, tmp_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )

        assert len(calls) == 1

    def test_monte_carlo_already_attached_is_idempotent_no_recompute(self, tmp_path, monkeypatch):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run_with_trades(plan, split_plan, _MC_TRADES_BY_FOLD)
        data_manifest_path = _execute_data_manifest(tmp_path)
        first = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )
        assert first.monte_carlo_validation_run_id is not None

        monkeypatch.setattr(
            gate_v_campaign, "run_monte_carlo_simulation",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("run_monte_carlo_simulation ne devait jamais être rappelée")
            ),
        )
        second = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )
        assert second == first

    def test_reconciles_monte_carlo_already_persisted_without_recompute(self, tmp_path, monkeypatch):
        """Crash APRES save_validation_run() MC, AVANT mise à jour du manifeste (le risque
        principal de cette slice)."""
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run_with_trades(plan, split_plan, _MC_TRADES_BY_FOLD)
        data_manifest_path = _execute_data_manifest(tmp_path)
        completed = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )
        assert completed.monte_carlo_validation_run_id is not None

        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        record["monte_carlo_validation_run_id"] = None
        record["status"] = "RUNNING"
        record["running"] = True
        manifest_path.write_text(json.dumps(record), encoding="utf-8")

        monkeypatch.setattr(
            gate_v_campaign, "run_monte_carlo_simulation",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("run_monte_carlo_simulation ne devait jamais être rappelée")
            ),
        )
        reconciled = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )
        assert reconciled.monte_carlo_validation_run_id == completed.monte_carlo_validation_run_id

    def test_refused_when_walk_forward_proof_missing_from_disk(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run_with_trades(plan, split_plan, _MC_TRADES_BY_FOLD)
        data_manifest_path = _execute_data_manifest(tmp_path)
        _execute(
            plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )

        wf_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
        campaign_dir = campaign_root / plan.campaign_id
        (campaign_dir / "validations" / wf_id / "validation_run.json").unlink()
        manifest_path = campaign_dir / "manifest.json"
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        record["monte_carlo_validation_run_id"] = None
        record["status"] = "RUNNING"
        record["running"] = True
        manifest_path.write_text(json.dumps(record), encoding="utf-8")

        # Le manifeste lui-même redevient illisible dès qu'une preuve qu'il référence disparaît
        # (garde Slice 2, `load_gate_v_campaign_manifest`/`_load_manifest_proofs`) -- fail-closed
        # atteint avant même la précondition Monte-Carlo spécifique à cette slice.
        with pytest.raises(ValueError, match="ValidationRun|preuve"):
            _execute(
                plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
                run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
            )

    def test_refused_when_walk_forward_proof_incoherent_with_plan(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run_with_trades(plan, split_plan, _MC_TRADES_BY_FOLD)
        data_manifest_path = _execute_data_manifest(tmp_path)
        _execute(
            plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )

        wf_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
        campaign_dir = campaign_root / plan.campaign_id
        wf_path = campaign_dir / "validations" / wf_id / "validation_run.json"
        record = json.loads(wf_path.read_text(encoding="utf-8"))
        record["dataset_snapshot_id"] = "foreign_snapshot"
        wf_path.write_text(json.dumps(record), encoding="utf-8")
        manifest_path = campaign_dir / "manifest.json"
        manifest_record = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_record["monte_carlo_validation_run_id"] = None
        manifest_record["status"] = "RUNNING"
        manifest_record["running"] = True
        manifest_path.write_text(json.dumps(manifest_record), encoding="utf-8")

        with pytest.raises(ValueError):
            _execute(
                plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
                run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
            )

    def test_persists_running_manifest_before_costly_monte_carlo_call(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run_with_trades(plan, split_plan, _MC_TRADES_BY_FOLD)
        data_manifest_path = _execute_data_manifest(tmp_path)
        _execute(
            plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )
        mc_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO)
        mc_dir = campaign_root / plan.campaign_id / "validations" / mc_id
        shutil.rmtree(mc_dir)  # force un calcul FRAIS, jamais la réconciliation
        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        record["monte_carlo_validation_run_id"] = None
        record["status"] = "RUNNING"
        record["running"] = True
        manifest_path.write_text(json.dumps(record), encoding="utf-8")

        observed = {}
        import monte_carlo
        real_run = monte_carlo.run_monte_carlo_simulation

        def spying_run(*args, **kwargs):
            reloaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            observed["status"] = reloaded["status"]
            observed["running"] = reloaded["running"]
            return real_run(*args, **kwargs)

        import gate_v_campaign as gvc
        old = gvc.run_monte_carlo_simulation
        gvc.run_monte_carlo_simulation = spying_run
        try:
            _execute(
                plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
                run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
            )
        finally:
            gvc.run_monte_carlo_simulation = old

        assert observed == {"status": "RUNNING", "running": True}

    def test_technical_exception_during_monte_carlo_propagates_and_persists_technical_failure(
        self, tmp_path, monkeypatch,
    ):
        """AF-V-08 checkpoint de stabilisation (2026-09-28), corrige ADR 0024 Décision 7 : voir
        `test_technical_exception_propagates_and_persists_technical_failure` (phase WF) pour la
        justification complète -- même contrat, ici pour Monte-Carlo. La preuve Walk-Forward déjà
        attachée AVANT le crash Monte-Carlo doit rester référencée."""
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run_with_trades(plan, split_plan, _MC_TRADES_BY_FOLD)
        data_manifest_path = _execute_data_manifest(tmp_path)
        completed_wf = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )
        mc_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO)
        mc_dir = campaign_root / plan.campaign_id / "validations" / mc_id
        shutil.rmtree(mc_dir)  # force un calcul FRAIS, jamais la réconciliation
        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        record["monte_carlo_validation_run_id"] = None
        record["status"] = "RUNNING"
        record["running"] = True
        manifest_path.write_text(json.dumps(record), encoding="utf-8")

        def failing_run(*args, **kwargs):
            raise RuntimeError("synthetic monte-carlo crash")
        monkeypatch.setattr(gate_v_campaign, "run_monte_carlo_simulation", failing_run)

        with pytest.raises(RuntimeError, match="synthetic monte-carlo crash"):
            _execute(
                plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
                run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
            )

        from gate_v_campaign import load_gate_v_campaign_manifest
        reloaded = load_gate_v_campaign_manifest(manifest_path, plan)
        assert reloaded.status == "TECHNICAL_FAILURE"
        assert reloaded.running is False
        assert reloaded.execution_started is True
        assert isinstance(reloaded.technical_failure_reason, str) and reloaded.technical_failure_reason.strip()
        assert "synthetic monte-carlo crash" in reloaded.technical_failure_reason
        assert reloaded.monte_carlo_validation_run_id is None
        assert reloaded.walk_forward_validation_run_id == completed_wf.walk_forward_validation_run_id

    def test_monte_carlo_phase_itself_never_references_parameter_stability(self):
        """`_run_monte_carlo_phase()` (la phase MC elle-même) reste totalement ignorante de
        Parameter Stability -- seul l'orchestrateur `execute_gate_v_campaign()` (Slice 5) enchaîne
        les deux phases, jamais la phase MC elle-même."""
        source = inspect.getsource(gate_v_campaign._run_monte_carlo_phase)
        assert "analyze_parameter_stability" not in source
        assert "ParameterStabilitySpecification" not in source
        assert "parameter_stability_validation_run_ids_by_fold" not in source

    def test_one_monte_carlo_validation_run_per_campaign(self, tmp_path):
        plan, split_plan, campaign_root = _execute_ready_campaign(tmp_path)
        run_fn, _calls = _execute_fake_run_with_trades(plan, split_plan, _MC_TRADES_BY_FOLD)
        _execute(
            plan, campaign_root, tmp_path,
            run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"),
        )
        validations_dir = campaign_root / plan.campaign_id / "validations"
        mc_dirs = [
            p for p in validations_dir.iterdir()
            if p.is_dir() and VALIDATION_TYPE_MONTE_CARLO in p.name
        ]
        assert len(mc_dirs) == 1


# ══════════════════════════════════════════════════════════════════════════════
# AF-V-08 Slice 5 — phase Parameter Stability, APRÈS Walk-Forward ET Monte-Carlo complets et
# validés. Un pool TRAIN exact PAR fold, relu via load_walk_forward_captured_run_v1() (jamais
# train_candidates.csv). Une ValidationRun PS PAR fold attendu, jamais fusionnée.
# ══════════════════════════════════════════════════════════════════════════════

def _ps_pool_for_fold(best_params, *, extra_candidates=None, extra_params=None):
    """Pool TRAIN synthétique : `best_params` en position 0 (vrai Top-1, `score=1.0`), plus un
    voisin structurel `score>0` non rejeté (même clés, un seul paramètre différent) -- produit
    `neighborhood_applicability="local_neighborhood_available"` avec >=1 voisin utilisable sous
    `search_mode="grid"` (`DETERMINISTIC_DISPATCH_MODES`)."""
    neighbor_params = dict(best_params)
    key = next(iter(best_params))
    neighbor_params[key] = extra_params if extra_params is not None else best_params[key] - 2
    candidates = [
        {"params": dict(best_params), "score": 1.0, "stats": {"n_trades": 3},
         "filtered": False, "filter_reason": None},
        {"params": neighbor_params, "score": 0.8, "stats": {"n_trades": 2},
         "filtered": False, "filter_reason": None},
    ]
    if extra_candidates:
        candidates.extend(extra_candidates)
    return candidates


def _ps_fake_execute_fold(plan, pools_by_fold):
    """Doublure de `execute_walk_forward_fold_with_artifacts()` (le SEUL point bas-niveau
    monkeypatché) -- la VRAIE `run_walk_forward_with_artifacts_v1()` orchestre au-dessus, donc
    écrit RÉELLEMENT les checkpoints V1 sur disque (source exacte que
    `load_walk_forward_captured_run_v1()` doit pouvoir relire pour Parameter Stability)."""
    def execute(fold, base_config, df, progress_cb=None, stop_flag_fn=None, fold_seed=None):
        best_params = {"lookback": 12}
        pool = pools_by_fold.get(fold.fold_id) or _ps_pool_for_fold(best_params)
        selection = FoldSelection(
            fold_id=fold.fold_id, selected_params=dict(pool[0]["params"]),
            selected_params_hash=params_hash(pool[0]["params"]),
            score_train=pool[0]["score"], rank_in_train=1,
            train_candidates_evaluated=len(pool), train_candidates_unique=len(pool),
            train_candidates_eligible=len(pool),
            search_space_hash=plan.search_space_hash, algorithm=plan.search_mode,
            fold_seed=fold_seed,
        )
        result = FoldResult(
            fold_id=fold.fold_id, definition=fold, selection=selection,
            n_trades=1, net_ret_pct=1.0, max_dd_pct=0.5, profit_factor=1.2, win_rate=50.0,
            expectancy=1.0, score_test=1.0, zero_trade_oos=False, forced_closes=0, coverage_bars=1,
        )
        trades = pd.DataFrame({
            "resultat_net": [50.0], "capital_apres": [10_050.0],
            "date_entree": [fold.effective_boundary],
        })
        equity = pd.DataFrame({"capital": [10_000.0]})
        return result, FoldArtifacts(fold.fold_id, pool, trades, equity)
    return execute


def _ps_setup(tmp_path, monkeypatch, *, pools_by_fold=None):
    """Prépare campagne + doublure bas-niveau (checkpoints V1 RÉELLEMENT écrits par la VRAIE
    `run_walk_forward_with_artifacts_v1()`) SANS appeler `execute_gate_v_campaign()` -- laisse
    l'appelant faire son propre appel `_execute()` unique (nécessaire pour observer/interrompre
    l'état pendant la phase Parameter Stability, qui s'enchaîne automatiquement après Monte-Carlo
    dans le même appel)."""
    plan, _split_plan, campaign_root = _execute_ready_campaign(tmp_path)
    monkeypatch.setattr(
        walk_forward, "execute_walk_forward_fold_with_artifacts",
        _ps_fake_execute_fold(plan, pools_by_fold or {}),
    )
    data_manifest_path = _execute_data_manifest(tmp_path)
    return plan, campaign_root, data_manifest_path


def _execute_ps_ready_campaign(tmp_path, monkeypatch, *, pools_by_fold=None):
    """Complète Walk-Forward + Monte-Carlo + Parameter Stability (les trois s'enchaînent dans un
    seul appel `execute_gate_v_campaign()` une fois qu'aucune interruption ne se produit)."""
    plan, campaign_root, data_manifest_path = _ps_setup(
        tmp_path, monkeypatch, pools_by_fold=pools_by_fold,
    )
    manifest = _execute(
        plan, campaign_root, tmp_path, data_manifest_path=data_manifest_path,
        run_walk_forward_fn=walk_forward.run_walk_forward_with_artifacts_v1,
        resume_walk_forward_fn=_never_called("resume"),
    )
    assert manifest.walk_forward_validation_run_id is not None
    assert manifest.monte_carlo_validation_run_id is not None
    return plan, campaign_root, manifest, data_manifest_path


class TestExecuteGateVCampaignParameterStabilityPhase:
    def test_one_validation_run_per_expected_fold(self, tmp_path, monkeypatch):
        plan, campaign_root, _manifest, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)

        final = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )

        assert set(final.parameter_stability_validation_run_ids_by_fold) == set(plan.expected_fold_ids)
        assert len(set(final.parameter_stability_validation_run_ids_by_fold.values())) == len(
            plan.expected_fold_ids
        )  # IDs distincts par fold

    def test_pools_never_merged_across_folds_and_top1_exact(self, tmp_path, monkeypatch):
        plan, campaign_root, _manifest, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)
        final = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )
        for fold_id, ps_id in final.parameter_stability_validation_run_ids_by_fold.items():
            path = campaign_root / plan.campaign_id / "validations" / ps_id / "validation_run.json"
            run = load_validation_run(path)
            assert run.evidence.n_candidates_total == 2  # pool de CE fold seulement
            assert run.evidence.best_params == {"lookback": 12}
            assert run.specification.source_fold_id == fold_id

    def test_specification_provenance_exact(self, tmp_path, monkeypatch):
        plan, campaign_root, manifest, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)
        final = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )
        for fold_id, ps_id in final.parameter_stability_validation_run_ids_by_fold.items():
            path = campaign_root / plan.campaign_id / "validations" / ps_id / "validation_run.json"
            run = load_validation_run(path)
            assert run.specification.source_validation_run_id == manifest.walk_forward_validation_run_id
            assert run.specification.source_candidates_from_optimized_search is True
            assert run.specification.search_mode == plan.search_mode
            assert run.evidence.search_mode == plan.search_mode

    def test_zero_neighbor_ps_stays_evidence_incomplete_never_technical_failure(
        self, tmp_path, monkeypatch,
    ):
        """AF-V-08 checkpoint de stabilisation (2026-09-28), mission §7 item 10 -- un pool TRAIN
        réduit au seul Top-1 (aucun voisin structurel, zéro voisin utilisable) sous `search_mode`
        déterministe reste un résultat scientifique honnête défavorable (ADR 0023 Décision 3),
        jamais une TECHNICAL_FAILURE. Aucun seuil >0 inventé au-delà du sens strict déjà défini."""
        zero_neighbor_pool = [{
            "params": {"lookback": 12}, "score": 1.0, "stats": {"n_trades": 3},
            "filtered": False, "filter_reason": None,
        }]
        pools_by_fold = {f"fold_{i:03d}": zero_neighbor_pool for i in range(10)}
        plan, campaign_root, dmp = _ps_setup(tmp_path, monkeypatch, pools_by_fold=pools_by_fold)

        final = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=walk_forward.run_walk_forward_with_artifacts_v1,
            resume_walk_forward_fn=_never_called("resume"),
        )

        assert set(final.parameter_stability_validation_run_ids_by_fold) == set(plan.expected_fold_ids)
        for ps_id in final.parameter_stability_validation_run_ids_by_fold.values():
            path = campaign_root / plan.campaign_id / "validations" / ps_id / "validation_run.json"
            run = load_validation_run(path)
            assert run.evidence.neighborhood_applicability == "local_neighborhood_available"
            usable = {
                p: run.evidence.n_neighbors_total_by_param[p] - run.evidence.n_neighbors_rejected_by_param[p]
                for p in run.evidence.n_neighbors_total_by_param
            }
            assert all(v == 0 for v in usable.values())
        assert final.status == "EVIDENCE_INCOMPLETE"
        assert final.status != "TECHNICAL_FAILURE"
        assert final.technical_failure_reason is None

    def test_deterministic_grid_mode_with_real_neighbor_is_locally_applicable(
        self, tmp_path, monkeypatch,
    ):
        plan, campaign_root, _manifest, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)
        final = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )
        for ps_id in final.parameter_stability_validation_run_ids_by_fold.values():
            path = campaign_root / plan.campaign_id / "validations" / ps_id / "validation_run.json"
            run = load_validation_run(path)
            assert run.evidence.neighborhood_applicability == "local_neighborhood_available"
            usable = {
                p: run.evidence.n_neighbors_total_by_param[p] - run.evidence.n_neighbors_rejected_by_param[p]
                for p in run.evidence.n_neighbors_total_by_param
            }
            assert any(v > 0 for v in usable.values())
        assert final.status == "EVIDENCE_INCOMPLETE"  # OOS absente -- jamais EVIDENCE_COMPLETE ici

    def test_general_search_mode_persists_but_stays_incomplete(self, tmp_path, monkeypatch):
        # Campagne dédiée avec search_mode="general" -- neighborhood_applicability devient
        # honnêtement global_correlation_only, jamais convertie en erreur.
        general_dir = tmp_path / "general"
        plan2, _split_plan2, campaign_root2 = _execute_ready_campaign(
            general_dir, search_mode="general",
        )
        monkeypatch.setattr(
            walk_forward, "execute_walk_forward_fold_with_artifacts",
            _ps_fake_execute_fold(plan2, {}),
        )
        data_manifest_path = _execute_data_manifest(general_dir)
        final = _execute(
            plan2, campaign_root2, general_dir, data_manifest_path=data_manifest_path,
            run_walk_forward_fn=walk_forward.run_walk_forward_with_artifacts_v1,
            resume_walk_forward_fn=_never_called("resume"),
        )
        assert set(final.parameter_stability_validation_run_ids_by_fold) == set(plan2.expected_fold_ids)
        for ps_id in final.parameter_stability_validation_run_ids_by_fold.values():
            path = campaign_root2 / plan2.campaign_id / "validations" / ps_id / "validation_run.json"
            run = load_validation_run(path)
            assert run.evidence.neighborhood_applicability == "global_correlation_only"
        assert final.status == "EVIDENCE_INCOMPLETE"
        # AF-V-08 checkpoint de stabilisation (2026-09-28) -- un résultat scientifique honnête
        # défavorable (`global_correlation_only`) n'est jamais une TECHNICAL_FAILURE.
        assert final.status != "TECHNICAL_FAILURE"
        assert final.technical_failure_reason is None

    def test_already_attached_folds_are_idempotent_no_recompute(self, tmp_path, monkeypatch):
        plan, campaign_root, _manifest, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)
        first = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )
        monkeypatch.setattr(
            gate_v_campaign, "analyze_parameter_stability",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("analyze_parameter_stability ne devait jamais être rappelée")
            ),
        )
        second = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )
        assert second == first

    def test_reconciles_one_fold_persisted_but_not_attached(self, tmp_path, monkeypatch):
        """Crash APRES save_validation_run() PS d'UN fold, AVANT mise à jour du manifeste."""
        plan, campaign_root, _manifest, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)
        completed = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )
        target_fold = plan.expected_fold_ids[0]
        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        del record["parameter_stability_validation_run_ids_by_fold"][target_fold]
        record["status"] = "RUNNING"
        record["running"] = True
        manifest_path.write_text(json.dumps(record), encoding="utf-8")

        monkeypatch.setattr(
            gate_v_campaign, "analyze_parameter_stability",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("analyze_parameter_stability ne devait jamais être rappelée")
            ),
        )
        reconciled = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )
        assert reconciled.parameter_stability_validation_run_ids_by_fold == (
            completed.parameter_stability_validation_run_ids_by_fold
        )

    def test_partial_multi_fold_resume_computes_only_missing_fold(self, tmp_path, monkeypatch):
        """fold attaché -> préservé ; fold persisté-non-attaché -> réconcilié SANS recalcul ;
        fold réellement absent (fichier ET référence supprimés) -> calculé UNE fois."""
        plan, campaign_root, completed, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)
        assert len(plan.expected_fold_ids) >= 2
        untouched_fold = plan.expected_fold_ids[0]
        persisted_not_attached_fold = plan.expected_fold_ids[-1]
        persisted_not_attached_id = completed.parameter_stability_validation_run_ids_by_fold[
            persisted_not_attached_fold
        ]

        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        del record["parameter_stability_validation_run_ids_by_fold"][persisted_not_attached_fold]
        record["status"] = "RUNNING"
        record["running"] = True
        manifest_path.write_text(json.dumps(record), encoding="utf-8")

        calls = []
        real_analyze = gate_v_campaign.analyze_parameter_stability

        def spy(*args, **kwargs):
            calls.append(1)
            return real_analyze(*args, **kwargs)
        monkeypatch.setattr(gate_v_campaign, "analyze_parameter_stability", spy)

        reconciled = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )
        assert len(calls) == 0  # le fichier PS existait déjà -- réconciliation, jamais un recalcul
        assert reconciled.parameter_stability_validation_run_ids_by_fold[untouched_fold] == (
            completed.parameter_stability_validation_run_ids_by_fold[untouched_fold]
        )
        assert reconciled.parameter_stability_validation_run_ids_by_fold[
            persisted_not_attached_fold
        ] == persisted_not_attached_id

    def test_truly_missing_fold_is_computed_exactly_once_others_untouched(self, tmp_path, monkeypatch):
        plan, campaign_root, completed, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)
        assert len(plan.expected_fold_ids) >= 2
        untouched_fold = plan.expected_fold_ids[0]
        missing_fold = plan.expected_fold_ids[-1]

        missing_id = completed.parameter_stability_validation_run_ids_by_fold[missing_fold]
        (
            campaign_root / plan.campaign_id / "validations" / missing_id / "validation_run.json"
        ).unlink()
        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        del record["parameter_stability_validation_run_ids_by_fold"][missing_fold]
        record["status"] = "RUNNING"
        record["running"] = True
        manifest_path.write_text(json.dumps(record), encoding="utf-8")

        calls = []
        real_analyze = gate_v_campaign.analyze_parameter_stability

        def spy(*args, **kwargs):
            calls.append(1)
            return real_analyze(*args, **kwargs)
        monkeypatch.setattr(gate_v_campaign, "analyze_parameter_stability", spy)

        recomputed = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )
        assert len(calls) == 1
        assert recomputed.parameter_stability_validation_run_ids_by_fold[untouched_fold] == (
            completed.parameter_stability_validation_run_ids_by_fold[untouched_fold]
        )
        assert recomputed.parameter_stability_validation_run_ids_by_fold[missing_fold] == missing_id

    def test_manifest_updated_after_each_fold_not_only_at_the_end(self, tmp_path, monkeypatch):
        plan, campaign_root, dmp = _ps_setup(tmp_path, monkeypatch)
        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        observed_counts = []
        real_analyze = gate_v_campaign.analyze_parameter_stability

        def spying(*args, **kwargs):
            evidence = real_analyze(*args, **kwargs)
            record = json.loads(manifest_path.read_text(encoding="utf-8"))
            observed_counts.append(len(record["parameter_stability_validation_run_ids_by_fold"]))
            return evidence
        monkeypatch.setattr(gate_v_campaign, "analyze_parameter_stability", spying)

        _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=walk_forward.run_walk_forward_with_artifacts_v1,
            resume_walk_forward_fn=_never_called("resume"),
        )
        # Après le calcul du fold i (avant que celui-ci soit rattaché), i-1 folds déjà rattachés.
        assert observed_counts == list(range(len(plan.expected_fold_ids)))

    def test_never_reads_train_candidates_csv_as_source(self, tmp_path):
        source = inspect.getsource(gate_v_campaign._run_parameter_stability_phase)
        assert "train_candidates.csv" not in source

    def test_never_calls_engine_optimizer_or_new_backtest(self):
        source = inspect.getsource(gate_v_campaign)
        assert "import engine" not in source
        assert "import optimizer" not in source
        assert "Optimizer(" not in source

    def test_rejects_foreign_parameter_stability_proof(self, tmp_path, monkeypatch):
        plan, campaign_root, _manifest, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)
        completed = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )
        target_fold = plan.expected_fold_ids[0]
        ps_id = completed.parameter_stability_validation_run_ids_by_fold[target_fold]
        path = campaign_root / plan.campaign_id / "validations" / ps_id / "validation_run.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["dataset_snapshot_id"] = "foreign_snapshot"
        path.write_text(json.dumps(record), encoding="utf-8")

        from gate_v_campaign import load_gate_v_campaign_manifest
        with pytest.raises(ValueError):
            load_gate_v_campaign_manifest(
                campaign_root / plan.campaign_id / "manifest.json", plan,
            )

    def test_reconciliation_rejects_persisted_run_with_wrong_source_fold_id(
        self, tmp_path, monkeypatch,
    ):
        """Une ValidationRun PS persistée mais non rattachée, dont `specification.source_fold_id`
        a été altéré pour référencer un AUTRE fold que celui associé à son propre fichier, doit
        être rejetée à la réconciliation -- jamais rattachée telle quelle (ADR 0023 Décision 11,
        traçabilité par fold). Vérifie que la garde de provenance de `_parameter_stability_quality()`
        s'applique aussi bien aux folds réconciliés qu'aux folds fraîchement calculés."""
        plan, campaign_root, completed, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)
        assert len(plan.expected_fold_ids) >= 2
        target_fold = plan.expected_fold_ids[0]
        foreign_fold = plan.expected_fold_ids[1]
        ps_id = completed.parameter_stability_validation_run_ids_by_fold[target_fold]
        path = campaign_root / plan.campaign_id / "validations" / ps_id / "validation_run.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["specification"]["source_fold_id"] = foreign_fold
        path.write_text(json.dumps(record), encoding="utf-8")

        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        manifest_record = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest_record["parameter_stability_validation_run_ids_by_fold"][target_fold]
        manifest_record["status"] = "RUNNING"
        manifest_record["running"] = True
        manifest_path.write_text(json.dumps(manifest_record), encoding="utf-8")

        with pytest.raises(ValueError, match="Provenance Parameter Stability incorrecte"):
            _execute(
                plan, campaign_root, tmp_path, data_manifest_path=dmp,
                run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
            )

    def test_manifest_before_costly_ps_call_is_running(self, tmp_path, monkeypatch):
        plan, campaign_root, _manifest, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)
        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        observed = []
        real_analyze = gate_v_campaign.analyze_parameter_stability

        def spying(*args, **kwargs):
            record = json.loads(manifest_path.read_text(encoding="utf-8"))
            observed.append((record["status"], record["running"]))
            return real_analyze(*args, **kwargs)
        import gate_v_campaign as gvc
        old = gvc.analyze_parameter_stability
        gvc.analyze_parameter_stability = spying
        try:
            _execute(
                plan, campaign_root, tmp_path, data_manifest_path=dmp,
                run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
            )
        finally:
            gvc.analyze_parameter_stability = old
        assert all(status == "RUNNING" and running is True for status, running in observed)

    def test_technical_exception_during_ps_propagates_and_persists_technical_failure(
        self, tmp_path, monkeypatch,
    ):
        """AF-V-08 checkpoint de stabilisation (2026-09-28), corrige ADR 0024 Décision 7 : même
        contrat que la phase WF/MC, ici pour Parameter Stability -- crash sur le premier fold
        (aucun fold PS encore attaché). Walk-Forward/Monte-Carlo, déjà complets AVANT cette phase,
        restent référencés."""
        plan, campaign_root, dmp = _ps_setup(tmp_path, monkeypatch)

        def failing(*args, **kwargs):
            raise RuntimeError("synthetic parameter-stability crash")
        monkeypatch.setattr(gate_v_campaign, "analyze_parameter_stability", failing)

        with pytest.raises(RuntimeError, match="synthetic parameter-stability crash"):
            _execute(
                plan, campaign_root, tmp_path, data_manifest_path=dmp,
                run_walk_forward_fn=walk_forward.run_walk_forward_with_artifacts_v1,
                resume_walk_forward_fn=_never_called("resume"),
            )

        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        from gate_v_campaign import load_gate_v_campaign_manifest
        reloaded = load_gate_v_campaign_manifest(manifest_path, plan)
        assert reloaded.status == "TECHNICAL_FAILURE"
        assert reloaded.running is False
        assert reloaded.execution_started is True
        assert isinstance(reloaded.technical_failure_reason, str) and reloaded.technical_failure_reason.strip()
        assert "synthetic parameter-stability crash" in reloaded.technical_failure_reason
        assert reloaded.walk_forward_validation_run_id is not None
        assert reloaded.monte_carlo_validation_run_id is not None
        assert reloaded.parameter_stability_validation_run_ids_by_fold == {}

    def test_technical_exception_during_ps_preserves_already_attached_folds(
        self, tmp_path, monkeypatch,
    ):
        """AF-V-08 checkpoint de stabilisation (2026-09-28), mission §6 -- cas critique multi-fold :
        le PREMIER fold est déjà persisté et attaché, exception technique pendant le calcul du
        fold SUIVANT. Après l'exception : TECHNICAL_FAILURE, running=False, le premier fold
        TOUJOURS référencé (aucune référence déjà persistée perdue), le fold en crash jamais
        fabriqué. Preuve que `_mark_technical_failure_if_running()` recharge réellement le DERNIER
        manifeste persisté (celui écrit fold par fold par `_run_parameter_stability_phase`),
        jamais un objet `manifest` périmé détenu par l'appelant."""
        plan, campaign_root, completed, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)
        assert len(plan.expected_fold_ids) >= 2
        first_two = plan.expected_fold_ids[:1]
        crash_fold = plan.expected_fold_ids[1]
        preserved_ids = {
            fold_id: completed.parameter_stability_validation_run_ids_by_fold[fold_id]
            for fold_id in first_two
        }
        # Supprime aussi le fichier persisté du fold en crash (pas seulement sa référence
        # manifeste) -- sinon _run_parameter_stability_phase le retrouverait et le RÉCONCILIERAIT
        # sans jamais rappeler analyze_parameter_stability, et le crash synthétique ne se
        # produirait pas.
        crash_ps_id = completed.parameter_stability_validation_run_ids_by_fold[crash_fold]
        (
            campaign_root / plan.campaign_id / "validations" / crash_ps_id / "validation_run.json"
        ).unlink()

        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        for fold_id in plan.expected_fold_ids:
            if fold_id not in first_two:
                record["parameter_stability_validation_run_ids_by_fold"].pop(fold_id, None)
        record["status"] = "RUNNING"
        record["running"] = True
        manifest_path.write_text(json.dumps(record), encoding="utf-8")

        real_analyze = gate_v_campaign.analyze_parameter_stability
        crash_message = f"synthetic parameter-stability crash on {crash_fold}"

        def crash_on_third_fold(pool, best_params, spec):
            if spec.source_fold_id == crash_fold:
                raise RuntimeError(crash_message)
            return real_analyze(pool, best_params, spec)
        monkeypatch.setattr(gate_v_campaign, "analyze_parameter_stability", crash_on_third_fold)

        with pytest.raises(RuntimeError, match=crash_message):
            _execute(
                plan, campaign_root, tmp_path, data_manifest_path=dmp,
                run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
            )

        from gate_v_campaign import load_gate_v_campaign_manifest
        reloaded = load_gate_v_campaign_manifest(manifest_path, plan)
        assert reloaded.status == "TECHNICAL_FAILURE"
        assert reloaded.running is False
        assert reloaded.execution_started is True
        assert crash_message in reloaded.technical_failure_reason
        assert reloaded.parameter_stability_validation_run_ids_by_fold == preserved_ids
        assert crash_fold not in reloaded.parameter_stability_validation_run_ids_by_fold
        crashed_ps_id = gate_v_campaign.gate_v_validation_run_id(
            plan, VALIDATION_TYPE_PARAMETER_STABILITY, fold_id=crash_fold,
        )
        crashed_ps_path = (
            campaign_root / plan.campaign_id / "validations" / crashed_ps_id / "validation_run.json"
        )
        assert not crashed_ps_path.exists()

    def test_refused_without_complete_monte_carlo(self, tmp_path, monkeypatch):
        plan, campaign_root, manifest, dmp = _execute_ps_ready_campaign(tmp_path, monkeypatch)
        mc_id = manifest.monte_carlo_validation_run_id
        mc_path = campaign_root / plan.campaign_id / "validations" / mc_id / "validation_run.json"
        mc_path.unlink()
        manifest_path = campaign_root / plan.campaign_id / "manifest.json"
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        record["parameter_stability_validation_run_ids_by_fold"] = {}
        record["status"] = "RUNNING"
        record["running"] = True
        manifest_path.write_text(json.dumps(record), encoding="utf-8")

        with pytest.raises(ValueError):
            _execute(
                plan, campaign_root, tmp_path, data_manifest_path=dmp,
                run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
            )


# ══════════════════════════════════════════════════════════════════════════════
# AF-V-08 Slice 6 -- fermeture de l'intégration bout-en-bout SYNTHÉTIQUE de la campagne GATE V.
# Aucune donnée marché réelle, aucun FINAL_HOLDOUT réel, aucun AF-V-07, aucun PASS/Champion.
# ══════════════════════════════════════════════════════════════════════════════

def _e2e_ready_campaign(tmp_path, monkeypatch, *, pools_by_fold=None):
    """Campagne prête avec preuve OOS SYNTHÉTIQUE déjà référencée par le plan (persistée AVANT le
    plan, via le helper `_synthetic_oos_run()` DÉJÀ EXISTANT plus haut dans ce fichier -- jamais
    dupliqué ici), et checkpoints V1 RÉELS écrits par la VRAIE
    `run_walk_forward_with_artifacts_v1()` (même technique que Slice 5 : seul
    `execute_walk_forward_fold_with_artifacts` est monkeypatché -- jamais toute la phase
    Walk-Forward remplacée par un mock)."""
    oos_path = tmp_path / "oos_synthetic" / "validation_run.json"
    oos_run = _synthetic_oos_run(oos_path)

    plan, _split_plan, campaign_root = _execute_ready_campaign(
        tmp_path, oos_evidence_validation_run_id=oos_run.validation_run_id,
        oos_evidence_path=oos_path,
    )
    monkeypatch.setattr(
        walk_forward, "execute_walk_forward_fold_with_artifacts",
        _ps_fake_execute_fold(plan, pools_by_fold or {}),
    )
    data_manifest_path = _execute_data_manifest(tmp_path)
    return plan, campaign_root, data_manifest_path, oos_run


class TestGateVCampaignSyntheticEndToEndIntegration:
    """AF-V-08 Slice 6 -- plan -> Walk-Forward -> Monte-Carlo -> Parameter Stability -> manifeste
    final, jusqu'à `EVIDENCE_COMPLETE_AWAITING_POLICY` sur fixtures synthétiques cohérentes."""

    def test_synthetic_end_to_end_reaches_evidence_complete_awaiting_policy(
        self, tmp_path, monkeypatch,
    ):
        plan, campaign_root, dmp, oos_run = _e2e_ready_campaign(tmp_path, monkeypatch)

        final = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=walk_forward.run_walk_forward_with_artifacts_v1,
            resume_walk_forward_fn=_never_called("resume"),
        )

        assert final.status == "EVIDENCE_COMPLETE_AWAITING_POLICY"
        assert final.execution_started is True
        assert final.running is False
        assert final.technical_failure_reason is None
        assert final.oos_evidence_validation_run_id == oos_run.validation_run_id
        assert final.walk_forward_validation_run_id is not None
        assert final.monte_carlo_validation_run_id is not None
        assert set(final.parameter_stability_validation_run_ids_by_fold) == set(plan.expected_fold_ids)
        assert "PASS" not in final.status
        assert "CHAMPION" not in final.status.upper()
        assert not any(f.name.lower() == "champion" for f in dataclasses.fields(final))

        # Le statut final provient UNIQUEMENT de derive_gate_v_campaign_status(), jamais forcé
        # manuellement -- preuve directe en recalculant depuis les preuves réellement persistées.
        campaign_dir = campaign_root / plan.campaign_id
        persisted_runs, _paths = gate_v_campaign._load_manifest_proofs(plan, final, campaign_dir)
        recomputed = gate_v_campaign.derive_gate_v_campaign_status(plan, final, persisted_runs)
        assert recomputed == "EVIDENCE_COMPLETE_AWAITING_POLICY"

    def test_disk_reload_fully_recomputes_evidence_complete_awaiting_policy(
        self, tmp_path, monkeypatch,
    ):
        plan, campaign_root, dmp, oos_run = _e2e_ready_campaign(tmp_path, monkeypatch)
        _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=walk_forward.run_walk_forward_with_artifacts_v1,
            resume_walk_forward_fn=_never_called("resume"),
        )

        campaign_dir = campaign_root / plan.campaign_id
        reloaded_plan = gate_v_campaign.load_gate_v_campaign_plan(
            campaign_dir / "plan.json", split_plan_path=plan.split_plan_path,
            oos_evidence_path=plan.oos_evidence_path,
        )
        assert reloaded_plan == plan
        reloaded_manifest = gate_v_campaign.load_gate_v_campaign_manifest(
            campaign_dir / "manifest.json", reloaded_plan,
        )
        reloaded_oos = load_validation_run(Path(plan.oos_evidence_path))
        assert reloaded_oos == oos_run
        wf_path = (
            campaign_dir / "validations" / reloaded_manifest.walk_forward_validation_run_id
            / "validation_run.json"
        )
        assert load_validation_run(wf_path) is not None
        mc_path = (
            campaign_dir / "validations" / reloaded_manifest.monte_carlo_validation_run_id
            / "validation_run.json"
        )
        assert load_validation_run(mc_path) is not None
        for fold_id, ps_id in reloaded_manifest.parameter_stability_validation_run_ids_by_fold.items():
            ps_path = campaign_dir / "validations" / ps_id / "validation_run.json"
            assert load_validation_run(ps_path) is not None

        # La capture Walk-Forward V1 elle-même reste relisible en lecture seule (Slice 5).
        split_plan = load_dataset_split_plan(reloaded_plan.split_plan_path)
        captured = load_walk_forward_captured_run_v1(
            split_plan.validation, reloaded_plan.walk_forward_specification,
            reloaded_plan.readiness_spec, _execute_base_config(reloaded_plan),
            data_manifest_path=dmp, output_dir=campaign_dir / "walk_forward",
            validation_run_id=reloaded_manifest.walk_forward_validation_run_id,
        )
        assert {a.fold_id for a in captured.fold_artifacts} == set(reloaded_plan.expected_fold_ids)

        persisted_runs, _paths = gate_v_campaign._load_manifest_proofs(
            reloaded_plan, reloaded_manifest, campaign_dir,
        )
        recomputed_status = gate_v_campaign.derive_gate_v_campaign_status(
            reloaded_plan, reloaded_manifest, persisted_runs,
        )
        assert recomputed_status == "EVIDENCE_COMPLETE_AWAITING_POLICY"

    def test_second_call_is_fully_idempotent_no_recompute(self, tmp_path, monkeypatch):
        plan, campaign_root, dmp, _oos_run = _e2e_ready_campaign(tmp_path, monkeypatch)
        first = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=walk_forward.run_walk_forward_with_artifacts_v1,
            resume_walk_forward_fn=_never_called("resume"),
        )
        assert first.status == "EVIDENCE_COMPLETE_AWAITING_POLICY"

        campaign_dir = campaign_root / plan.campaign_id
        wf_path = campaign_dir / "validations" / first.walk_forward_validation_run_id / "validation_run.json"
        mc_path = campaign_dir / "validations" / first.monte_carlo_validation_run_id / "validation_run.json"
        ps_paths = {
            fold_id: campaign_dir / "validations" / ps_id / "validation_run.json"
            for fold_id, ps_id in first.parameter_stability_validation_run_ids_by_fold.items()
        }
        mtimes_before = {
            path: path.stat().st_mtime_ns for path in (wf_path, mc_path, *ps_paths.values())
        }

        monkeypatch.setattr(
            gate_v_campaign, "run_monte_carlo_simulation",
            _never_called("run_monte_carlo_simulation"),
        )
        monkeypatch.setattr(
            gate_v_campaign, "analyze_parameter_stability",
            _never_called("analyze_parameter_stability"),
        )

        second = _execute(
            plan, campaign_root, tmp_path, data_manifest_path=dmp,
            run_walk_forward_fn=_never_called("run"), resume_walk_forward_fn=_never_called("resume"),
        )

        assert second == first
        for path, before in mtimes_before.items():
            assert path.stat().st_mtime_ns == before

    def test_ids_are_deterministic_across_independent_rebuilds(self, tmp_path, monkeypatch):
        first_dir = tmp_path / "first"
        second_dir = tmp_path / "second"
        plan1, campaign_root1, dmp1, _oos1 = _e2e_ready_campaign(first_dir, monkeypatch)
        final1 = _execute(
            plan1, campaign_root1, first_dir, data_manifest_path=dmp1,
            run_walk_forward_fn=walk_forward.run_walk_forward_with_artifacts_v1,
            resume_walk_forward_fn=_never_called("resume"),
        )
        plan2, campaign_root2, dmp2, _oos2 = _e2e_ready_campaign(second_dir, monkeypatch)
        final2 = _execute(
            plan2, campaign_root2, second_dir, data_manifest_path=dmp2,
            run_walk_forward_fn=walk_forward.run_walk_forward_with_artifacts_v1,
            resume_walk_forward_fn=_never_called("resume"),
        )

        assert plan1.campaign_id == plan2.campaign_id
        assert final1.walk_forward_validation_run_id == final2.walk_forward_validation_run_id
        assert final1.monte_carlo_validation_run_id == final2.monte_carlo_validation_run_id
        assert (
            final1.parameter_stability_validation_run_ids_by_fold
            == final2.parameter_stability_validation_run_ids_by_fold
        )
        source = inspect.getsource(gate_v_campaign.gate_v_validation_run_id)
        assert "uuid" not in source.lower()
        assert "random" not in source.lower()
        assert "time.time" not in source and "datetime.now" not in source

    def test_no_cli_entrypoint_or_automatic_wiring(self):
        """Consolide ce que le check module-level existant
        (`test_preparation_has_no_execution_collaborator_or_market_data_access`) ne couvre pas
        encore : aucun point d'entrée CLI, aucun wiring depuis un launcher/app/Autopilot."""
        source = inspect.getsource(gate_v_campaign)
        assert "__main__" not in source
        repo_root = Path(gate_v_campaign.__file__).resolve().parent
        for candidate in ("app.py", "optimizer_process.py"):
            path = repo_root / candidate
            if path.is_file():
                assert "gate_v_campaign" not in path.read_text(encoding="utf-8")
        autopilot_dir = repo_root / "scripts" / "autopilot"
        if autopilot_dir.is_dir():
            for script in autopilot_dir.rglob("*.py"):
                assert "gate_v_campaign" not in script.read_text(encoding="utf-8")
