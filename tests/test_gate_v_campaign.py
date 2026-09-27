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
    build_monte_carlo_specification,
    build_oos_validation_evidence,
    build_oos_validation_specification,
    build_parameter_stability_specification,
    build_validation_run,
    save_validation_run,
)
from walk_forward import WALK_FORWARD_SEMANTICS_VERSION, compute_fold_definitions


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
