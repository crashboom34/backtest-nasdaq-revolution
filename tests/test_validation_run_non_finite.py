"""PN-1-S1 — sérialisation de `+inf` dans `validation_run.json` (marqueur B-M), refus des autres valeurs non finies.

Contrat : `PN1-S1-FINAL-CONTRACT-20261108.md` (S-1 à S-5). Fixtures synthétiques minuscules : aucun backtest, aucune donnée de marché,
aucun accès FINAL_HOLDOUT. L'ancien écrivain est reconstitué ici par son expression exacte (`save_atomic` : `json.dumps(asdict(run),
ensure_ascii=False, indent=2) + "\\n"`) pour prouver l'identité d'octets sur la même plateforme.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import validation_run as vr
import walk_forward
from validation_run import (
    FoldDefinition,
    FoldResult,
    FoldSelection,
    MonteCarloEvidence,
    ParameterStabilityEvidence,
    PercentileDistributionSummary,
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
    load_validation_run,
    save_validation_run,
)

INF = math.inf
MARKER = {"kind": "float", "value": "+inf"}
_START, _END = "2025-01-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00"


# ── fixtures ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _old_bytes(run) -> bytes:
    """Octets de l'ancien écrivain (`atomic_json_store.save_atomic`, l. 65) **sur la même plateforme** : `Path.write_text` traduit `\\n` en
    `os.linesep` (contrat §2 S-2 : l'identité se vérifie « ancien écrivain contre nouvel écrivain sur la même machine »)."""
    text = json.dumps(dataclasses.asdict(run), ensure_ascii=False, indent=2) + "\n"
    return text.replace("\n", os.linesep).encode("utf-8")


def oos_run(*, n_trades=3, net_ret_pct=1.5, **evidence):
    return build_validation_run(
        validation_run_id="oos_pn1", research_run_id="rr_pn1", split_plan_id="split_pn1", dataset_snapshot_id="snap_pn1",
        strategy_name="Strategy", strategy_params={"lookback": 12},
        specification=build_oos_validation_specification(_START, _END),
        evidence=build_oos_validation_evidence(_START, _END, n_trades, net_ret_pct, **evidence),
        validation_type=VALIDATION_TYPE_OOS, completed_at=_END,
    )


def fold(index, *, profit_factor, gross_win, gross_loss, n_trades, n_win):
    fold_id = f"fold_{index:03d}"
    zero = n_trades == 0
    return FoldResult(
        fold_id=fold_id,
        definition=FoldDefinition(
            fold_index=index, fold_id=fold_id, train_start="2020-01-01T00:00:00+00:00",
            requested_boundary="2022-01-01T00:00:00+00:00", effective_boundary="2022-01-01T00:00:00+00:00",
            boundary_adjusted=False, requested_test_end="2022-07-01T00:00:00+00:00",
            effective_test_end="2022-07-01T00:00:00+00:00", test_end_adjusted=False, is_last_fold=index == 1),
        selection=FoldSelection(
            fold_id=fold_id, selected_params={"lookback": 12}, selected_params_hash="a" * 12, score_train=1.0, rank_in_train=1,
            train_candidates_evaluated=3, train_candidates_unique=3, train_candidates_eligible=3, search_space_hash="b" * 12,
            algorithm="grid", fold_seed=None),
        n_trades=n_trades, net_ret_pct=0.0 if zero else 1.0, max_dd_pct=None if zero else 1.0, profit_factor=profit_factor,
        win_rate=None if zero else n_win / n_trades * 100, expectancy=None if zero else 1.0, score_test=0.0 if zero else 50.0,
        zero_trade_oos=zero, forced_closes=0, coverage_bars=10, gross_win=gross_win, gross_loss=gross_loss, n_win=n_win)


FINITE_FOLD = dict(profit_factor=2.0, gross_win=10.0, gross_loss=5.0, n_trades=3, n_win=2)
LOSS_FREE_FOLD = dict(profit_factor=INF, gross_win=10.0, gross_loss=0.0, n_trades=3, n_win=3)
ZERO_FOLD = dict(profit_factor=None, gross_win=0.0, gross_loss=0.0, n_trades=0, n_win=0)


def wf_run(*specs):
    folds = tuple(fold(i, **spec) for i, spec in enumerate(specs))
    specification = walk_forward.build_walk_forward_specification(
        base_params={"lookback": 12}, geometry="rolling", train_period="P24M", test_period="P6M", step_period="P6M")
    return build_validation_run(
        validation_run_id="wf_pn1", research_run_id="rr_pn1", split_plan_id="split_pn1", dataset_snapshot_id="snap_pn1",
        strategy_name="Strategy", strategy_params={"lookback": 12}, specification=specification,
        evidence=WalkForwardEvidence(folds, walk_forward.build_aggregate_result(folds), "completed", "INCONCLUSIVE", ()),
        validation_type=VALIDATION_TYPE_WALK_FORWARD, completed_at=_END)


def mc_run():
    wf_id = "wf_pn1"
    return build_validation_run(
        validation_run_id="mc_pn1", research_run_id="rr_pn1", split_plan_id="split_pn1", dataset_snapshot_id="snap_pn1",
        strategy_name="Strategy", strategy_params={"lookback": 12}, specification=build_monte_carlo_specification(wf_id, True),
        evidence=MonteCarloEvidence(
            n_input_trades=0, zero_trade_input=True, observed_net_ret_pct=None, observed_max_dd_trade_close_basis_pct=None,
            observed_lag1_autocorrelation=None, observed_longest_losing_streak=None, sequence_risk_max_dd_trade_close_basis_pct=None,
            sequence_risk_longest_losing_streak=None, sampling_uncertainty_net_ret_pct=None,
            sampling_uncertainty_max_dd_trade_close_basis_pct=None, execution_status="completed", scientific_verdict="INCONCLUSIVE",
            verdict_reasons=()),
        validation_type=VALIDATION_TYPE_MONTE_CARLO, completed_at=_END)


def ps_run():
    summary = PercentileDistributionSummary(0.1, 0.1, 0.1, 0.1, 0.1)
    return build_validation_run(
        validation_run_id="ps_pn1", research_run_id="rr_pn1", split_plan_id="split_pn1", dataset_snapshot_id="snap_pn1",
        strategy_name="Strategy", strategy_params={"lookback": 12},
        specification=build_parameter_stability_specification("wf_pn1", "grid", True, source_fold_id="fold_000"),
        evidence=ParameterStabilityEvidence(
            n_candidates_total=2, zero_candidates_input=False, search_mode="grid", neighborhood_applicability="local_neighborhood_available",
            best_score=1.0, best_params={"lookback": 12}, sensitivity={"lookback": 0.0}, sensitivity_sample_size_by_param={"lookback": 2},
            n_neighbors_total_by_param={"lookback": 1}, n_neighbors_rejected_by_param={"lookback": 0},
            degradation_by_param={"lookback": summary}, degradation_points_by_param={"lookback": summary}, n_hamming_le_2_total=1,
            n_hamming_le_2_rejected=0, degradation_hamming_le_2=summary, execution_status="completed", scientific_verdict="INCONCLUSIVE",
            verdict_reasons=()),
        validation_type=VALIDATION_TYPE_PARAMETER_STABILITY, completed_at=_END)


def with_fold(run, index, **changes):
    folds = list(run.evidence.fold_results)
    folds[index] = dataclasses.replace(folds[index], **changes)
    return dataclasses.replace(run, evidence=dataclasses.replace(run.evidence, fold_results=tuple(folds)))


def with_selection(run, index, **changes):
    folds = list(run.evidence.fold_results)
    folds[index] = dataclasses.replace(folds[index], selection=dataclasses.replace(folds[index].selection, **changes))
    return dataclasses.replace(run, evidence=dataclasses.replace(run.evidence, fold_results=tuple(folds)))


def with_aggregate(run, **changes):
    return dataclasses.replace(run, evidence=dataclasses.replace(run.evidence, aggregate=dataclasses.replace(run.evidence.aggregate, **changes)))


def written(tmp_path, run, name="validation_run.json") -> Path:
    return save_validation_run(tmp_path / name, run)


# ═══ 1. valeurs finies : octets strictement identiques à l'ancien écrivain ════════════════════════════════════════════════════════════

FINITE_RUNS = {
    "wf_finite": lambda: wf_run(FINITE_FOLD, FINITE_FOLD),
    "wf_zero_trade": lambda: wf_run(ZERO_FOLD, ZERO_FOLD),
    "wf_mixed_zero_and_finite": lambda: wf_run(FINITE_FOLD, ZERO_FOLD),
    "oos_finite": lambda: oos_run(profit_factor=1.75, win_rate=50.0, max_dd_pct=3.0),
    "oos_zero_trade": lambda: oos_run(n_trades=0, net_ret_pct=0.0),
    "monte_carlo": mc_run,
    "parameter_stability": ps_run,
    "wf_numpy_float64_values": lambda: with_fold(wf_run(FINITE_FOLD, FINITE_FOLD), 0, profit_factor=np.float64(2.0), net_ret_pct=np.float64(1.0)),
}


@pytest.mark.parametrize("label", sorted(FINITE_RUNS))
def test_finite_runs_are_written_with_the_exact_bytes_of_the_old_writer(tmp_path, label):
    run = FINITE_RUNS[label]()
    assert written(tmp_path, run).read_bytes() == _old_bytes(run)


def test_unknown_validation_type_with_finite_data_is_still_written_exactly_as_before(tmp_path):
    run = dataclasses.replace(oos_run(profit_factor=2.0), validation_type="future_type")
    assert written(tmp_path, run).read_bytes() == _old_bytes(run)


def test_a_str_subclass_dictionary_key_counts_as_text_and_bytes_stay_identical(tmp_path):
    class Key(str):
        pass
    run = dataclasses.replace(oos_run(profit_factor=2.0), strategy_params={Key("lookback"): 12})
    assert written(tmp_path, run).read_bytes() == _old_bytes(run)


# ═══ 2. +inf aux chemins autorisés : marqueur exact, aucun mot non standard ═══════════════════════════════════════════════════════════

def test_a_loss_free_fold_is_written_as_the_marker_and_never_as_infinity(tmp_path):
    path = written(tmp_path, wf_run(LOSS_FREE_FOLD, FINITE_FOLD))
    text = path.read_text(encoding="utf-8")
    assert "Infinity" not in text and "NaN" not in text
    record = json.loads(text)
    assert record["evidence"]["fold_results"][0]["profit_factor"] == MARKER
    assert record["evidence"]["fold_results"][1]["profit_factor"] == 2.0
    assert record["evidence"]["aggregate"]["oos_profit_factor"] == pytest.approx(20.0 / 5.0)


def test_the_aggregate_profit_factor_is_the_marker_when_every_fold_is_loss_free(tmp_path):
    run = wf_run(LOSS_FREE_FOLD, LOSS_FREE_FOLD)
    assert run.evidence.aggregate.oos_profit_factor == INF
    record = json.loads(written(tmp_path, run).read_text(encoding="utf-8"))
    assert record["evidence"]["aggregate"]["oos_profit_factor"] == MARKER
    assert [f["profit_factor"] for f in record["evidence"]["fold_results"]] == [MARKER, MARKER]


def test_an_oos_run_with_infinite_profit_factor_is_written_as_the_marker(tmp_path):
    record = json.loads(written(tmp_path, oos_run(profit_factor=INF, win_rate=100.0)).read_text(encoding="utf-8"))
    assert record["evidence"]["profit_factor"] == MARKER


def test_the_marker_is_written_with_its_frozen_key_order_kind_then_value(tmp_path):
    """Le marqueur est normatif et gelé (il entre dans `oos_evidence_hash`) : l'ordre d'écriture des clés est épinglé, pas seulement le
    contenu (une comparaison de dictionnaires ignore l'ordre)."""
    for run in (wf_run(LOSS_FREE_FOLD, FINITE_FOLD), oos_run(profit_factor=INF, win_rate=100.0)):
        text = written(tmp_path / run.validation_type, run).read_text(encoding="utf-8")
        marker_objects = []

        def keep(pairs):
            if [key for key, _ in pairs] == ["kind", "value"] or {key for key, _ in pairs} == {"kind", "value"}:
                marker_objects.append([key for key, _ in pairs])
            return dict(pairs)

        json.loads(text, object_pairs_hook=keep)
        assert marker_objects and all(order == ["kind", "value"] for order in marker_objects)
        assert '"kind": "float",\n' in text.replace("\r\n", "\n") and '"value": "+inf"' in text


def test_the_written_record_has_exactly_the_top_level_keys_of_the_old_writer(tmp_path):
    run = wf_run(LOSS_FREE_FOLD, FINITE_FOLD)
    record = json.loads(written(tmp_path, run).read_text(encoding="utf-8"))
    assert set(record) == set(dataclasses.asdict(run))


NUMPY_INFINITY_RUNS = {
    "fold": (lambda: with_fold(wf_run(FINITE_FOLD, FINITE_FOLD), 0, profit_factor=np.float64("inf"), gross_loss=0.0),
             lambda record: record["evidence"]["fold_results"][0]["profit_factor"]),
    "aggregate": (lambda: with_aggregate(wf_run(FINITE_FOLD, FINITE_FOLD), oos_profit_factor=np.float64("inf")),
                  lambda record: record["evidence"]["aggregate"]["oos_profit_factor"]),
    "oos": (lambda: oos_run(profit_factor=np.float64("inf"), win_rate=100.0),
            lambda record: record["evidence"]["profit_factor"]),
}


@pytest.mark.parametrize("label", sorted(NUMPY_INFINITY_RUNS))
def test_numpy_float64_infinity_is_encoded_like_a_python_float_at_every_closed_path(tmp_path, label):
    build, pick = NUMPY_INFINITY_RUNS[label]
    record = json.loads(written(tmp_path, build()).read_text(encoding="utf-8"))
    assert pick(record) == MARKER


def test_a_tuple_of_folds_and_a_list_of_folds_give_the_same_record():
    run = wf_run(LOSS_FREE_FOLD, FINITE_FOLD)
    as_tuple = vr.encode_validation_run_record(run)
    listed = dataclasses.replace(run, evidence=dataclasses.replace(run.evidence, fold_results=list(run.evidence.fold_results)))
    assert json.dumps(as_tuple) == json.dumps(vr.encode_validation_run_record(listed))


def test_encoding_does_not_mutate_the_run_nor_its_asdict_view():
    run = wf_run(LOSS_FREE_FOLD, FINITE_FOLD)
    before = dataclasses.asdict(run)
    vr.encode_validation_run_record(run)
    assert run.evidence.fold_results[0].profit_factor == INF
    assert json.dumps(before) == json.dumps(dataclasses.asdict(run))


# ═══ 3-5. refus : emplacement non autorisé, NaN, -inf, non finis, types NumPy et forgés ═══════════════════════════════════════════════

def _base_wf():
    return wf_run(FINITE_FOLD, FINITE_FOLD)


NON_FINITE_MUTATIONS = {
    "pf_minus_inf": lambda: with_fold(_base_wf(), 0, profit_factor=-INF),
    "pf_nan": lambda: with_fold(_base_wf(), 0, profit_factor=math.nan),
    "pf_numpy_nan": lambda: with_fold(_base_wf(), 0, profit_factor=np.float64("nan")),
    "net_ret_pct_inf": lambda: with_fold(_base_wf(), 0, net_ret_pct=INF),
    "win_rate_nan": lambda: with_fold(_base_wf(), 1, win_rate=math.nan),
    "expectancy_inf": lambda: with_fold(_base_wf(), 1, expectancy=INF),
    "gross_loss_minus_inf": lambda: with_fold(_base_wf(), 0, gross_loss=-INF),
    "score_train_inf": lambda: with_selection(_base_wf(), 0, score_train=INF),
    "selected_params_inf": lambda: with_selection(_base_wf(), 0, selected_params={"lookback": INF}),
    "strategy_params_nan": lambda: dataclasses.replace(_base_wf(), strategy_params={"x": math.nan}),
    "aggregate_net_return_inf": lambda: with_aggregate(_base_wf(), oos_net_return_pct=INF),
    "aggregate_pf_nan": lambda: with_aggregate(_base_wf(), oos_profit_factor=math.nan),
    "aggregate_pf_minus_inf": lambda: with_aggregate(_base_wf(), oos_profit_factor=-INF),
    "aggregate_pf_numpy_nan": lambda: with_aggregate(_base_wf(), oos_profit_factor=np.float64("nan")),
    "oos_pf_numpy_nan": lambda: oos_run(profit_factor=np.float64("nan")),
    "oos_pf_nan": lambda: oos_run(profit_factor=math.nan),
    "oos_pf_minus_inf": lambda: oos_run(profit_factor=-INF),
    "oos_net_ret_inf": lambda: oos_run(net_ret_pct=INF, profit_factor=2.0),
    "oos_win_rate_nan": lambda: oos_run(win_rate=math.nan),
    "mc_percentile_inf": lambda: dataclasses.replace(mc_run(), evidence=dataclasses.replace(mc_run().evidence, zero_trade_input=False, observed_net_ret_pct=INF)),
    "ps_best_score_nan": lambda: dataclasses.replace(ps_run(), evidence=dataclasses.replace(ps_run().evidence, best_score=math.nan)),
    "positive_inf_outside_closed_paths_in_ps": lambda: dataclasses.replace(ps_run(), evidence=dataclasses.replace(ps_run().evidence, best_score=INF)),
    "positive_inf_at_a_non_closed_path_of_an_oos_run": lambda: oos_run(profit_factor=2.0, win_rate=INF),
    "positive_inf_in_a_monte_carlo_run_has_no_closed_path": lambda: dataclasses.replace(mc_run(), strategy_params={"p": INF}),
}


@pytest.mark.parametrize("label", sorted(NON_FINITE_MUTATIONS))
def test_a_forbidden_non_finite_value_is_refused_before_anything_is_created(tmp_path, label):
    run = NON_FINITE_MUTATIONS[label]()
    target_dir = tmp_path / "not_created_yet"
    with pytest.raises(vr.NonFiniteMetricRefused) as excinfo:
        save_validation_run(target_dir / "validation_run.json", run)
    assert isinstance(excinfo.value, ValueError)
    assert not target_dir.exists(), "aucun répertoire ne doit être créé avant le refus"
    assert not list(tmp_path.rglob("*.tmp")) and not list(tmp_path.rglob("*validation_run*"))


def test_the_refusal_message_names_the_path_and_the_nature_of_the_value(tmp_path):
    with pytest.raises(vr.NonFiniteMetricRefused, match=r"fold_results.*profit_factor|profit_factor.*fold_results"):
        save_validation_run(tmp_path / "v.json", with_fold(_base_wf(), 0, profit_factor=math.nan))


def test_the_refusal_comes_before_the_existing_file_check_and_leaves_the_target_intact(tmp_path):
    target = written(tmp_path, wf_run(FINITE_FOLD, FINITE_FOLD))
    before = target.read_bytes()
    with pytest.raises(vr.NonFiniteMetricRefused):
        save_validation_run(target, with_fold(_base_wf(), 0, profit_factor=math.nan))
    assert target.read_bytes() == before


def test_an_existing_target_still_raises_file_exists_for_a_valid_run(tmp_path):
    target = written(tmp_path, wf_run(FINITE_FOLD, FINITE_FOLD))
    with pytest.raises(FileExistsError):
        save_validation_run(target, wf_run(FINITE_FOLD, FINITE_FOLD))


FORBIDDEN_TYPES_AT_CLOSED_PATH = {
    "numpy_float32_finite": np.float32(2.0),
    "numpy_float32_inf": np.float32("inf"),
    "numpy_int64": np.int64(3),
    "bool_true": True,
    "bool_false": False,
    "text": "inf",
    "list": [1.0],
    "dict_other": {"x": 1},
    "dict_equal_to_the_marker": dict(MARKER),
}


@pytest.mark.parametrize("label", sorted(FORBIDDEN_TYPES_AT_CLOSED_PATH))
def test_only_none_int_and_float_are_accepted_at_a_closed_path_fold(tmp_path, label):
    run = with_fold(_base_wf(), 0, profit_factor=FORBIDDEN_TYPES_AT_CLOSED_PATH[label])
    with pytest.raises(vr.NonFiniteMetricRefused):
        save_validation_run(tmp_path / "sub" / "v.json", run)
    assert not (tmp_path / "sub").exists()


@pytest.mark.parametrize("label", ["bool_true", "text", "dict_equal_to_the_marker"])
def test_the_same_type_rule_applies_to_the_aggregate_and_oos_closed_paths(tmp_path, label):
    value = FORBIDDEN_TYPES_AT_CLOSED_PATH[label]
    for run in (with_aggregate(_base_wf(), oos_profit_factor=value), oos_run(profit_factor=value)):
        with pytest.raises(vr.NonFiniteMetricRefused):
            save_validation_run(tmp_path / "x" / "v.json", run)
    assert not (tmp_path / "x").exists()


@pytest.mark.parametrize("value", [None, 0, 3, 0.0, 2.5, np.float64(2.5), INF])
def test_none_int_float_and_numpy_float64_are_accepted_at_a_closed_path(tmp_path, value):
    path = written(tmp_path, with_fold(_base_wf(), 0, profit_factor=value))
    assert path.is_file()


def test_a_non_text_dictionary_key_is_refused_before_any_io(tmp_path):
    run = dataclasses.replace(oos_run(profit_factor=2.0), strategy_params={1: "a", "1": "b"})
    with pytest.raises(vr.NonFiniteMetricRefused, match="clé"):
        save_validation_run(tmp_path / "d" / "v.json", run)
    assert not (tmp_path / "d").exists()


def test_a_lone_surrogate_is_refused_before_any_io_because_the_guard_mirrors_the_real_writer(tmp_path):
    run = dataclasses.replace(oos_run(profit_factor=2.0), strategy_name="bad\ud800name")
    with pytest.raises(ValueError):
        save_validation_run(tmp_path / "s" / "v.json", run)
    assert not (tmp_path / "s").exists()


def test_an_evidence_of_the_wrong_type_for_a_known_validation_type_is_refused_before_any_io(tmp_path):
    run = dataclasses.replace(wf_run(FINITE_FOLD, FINITE_FOLD), validation_type=VALIDATION_TYPE_OOS)
    with pytest.raises(ValueError):
        save_validation_run(tmp_path / "t" / "v.json", run)
    assert not (tmp_path / "t").exists()


def test_a_run_without_specification_is_still_refused_with_value_error(tmp_path):
    with pytest.raises(ValueError):
        save_validation_run(tmp_path / "v.json", dataclasses.replace(oos_run(profit_factor=2.0), specification=None))


def test_recursion_error_propagates_unchanged_and_nothing_is_written(tmp_path):
    deep = {}
    node = deep
    for _ in range(6000):
        node["n"] = {}
        node = node["n"]
    run = dataclasses.replace(oos_run(profit_factor=2.0), strategy_params=deep)
    with pytest.raises(RecursionError):
        save_validation_run(tmp_path / "r" / "v.json", run)
    assert not (tmp_path / "r").exists()


# ═══ 6-7. aller-retour et reconstruction exacte ═══════════════════════════════════════════════════════════════════════════════════════

def test_an_oos_run_with_infinite_profit_factor_round_trips_to_an_equal_run(tmp_path):
    run = oos_run(profit_factor=INF, win_rate=100.0, max_dd_pct=0.5)
    assert load_validation_run(written(tmp_path, run)) == run


def test_finite_runs_of_every_type_round_trip_to_equal_runs(tmp_path):
    for index, label in enumerate(sorted(FINITE_RUNS)):
        run = FINITE_RUNS[label]()
        loaded = load_validation_run(written(tmp_path, run, f"{index}.json"))
        assert loaded.validation_run_id == run.validation_run_id and loaded.specification == run.specification
        assert json.dumps(dataclasses.asdict(loaded), sort_keys=True) == json.dumps(dataclasses.asdict(run), sort_keys=True)


def test_a_walk_forward_run_reloads_in_the_current_tolerant_form_with_infinity_restored(tmp_path):
    run = wf_run(LOSS_FREE_FOLD, FINITE_FOLD)
    loaded = load_validation_run(written(tmp_path, run))
    expected = json.loads(json.dumps(dataclasses.asdict(run)))
    assert dataclasses.asdict(loaded)["evidence"] == expected["evidence"]
    assert loaded.evidence.fold_results[0]["profit_factor"] == INF
    assert loaded.evidence.aggregate["oos_profit_factor"] == pytest.approx(4.0)


def test_the_aggregate_marker_is_restored_to_infinity_on_reload(tmp_path):
    loaded = load_validation_run(written(tmp_path, wf_run(LOSS_FREE_FOLD, LOSS_FREE_FOLD)))
    assert loaded.evidence.aggregate["oos_profit_factor"] == INF


def test_decode_then_encode_is_stable_on_the_json_form():
    run = wf_run(LOSS_FREE_FOLD, LOSS_FREE_FOLD)
    encoded = json.loads(json.dumps(vr.encode_validation_run_record(run)))
    decoded = vr.decode_validation_run_record(encoded)
    assert decoded["evidence"]["fold_results"][0]["profit_factor"] == INF
    again = dataclasses.replace(run, evidence=WalkForwardEvidence(
        tuple(fold(i, **LOSS_FREE_FOLD) for i in range(2)), run.evidence.aggregate, "completed", "INCONCLUSIVE", ()))
    assert json.loads(json.dumps(vr.encode_validation_run_record(again))) == encoded


# ═══ décodeur : marqueur exact, chemins fermés, formes forgées, totalité ══════════════════════════════════════════════════════════════

def _record(run):
    return json.loads(json.dumps(vr.encode_validation_run_record(run)))


def test_the_decoder_replaces_only_the_exact_marker_at_the_closed_paths():
    record = _record(wf_run(LOSS_FREE_FOLD, FINITE_FOLD))
    assert vr.decode_validation_run_record(record)["evidence"]["fold_results"][0]["profit_factor"] == INF


def test_the_decoder_does_not_mutate_its_input():
    record = _record(wf_run(LOSS_FREE_FOLD, FINITE_FOLD))
    before = json.dumps(record, sort_keys=True)
    vr.decode_validation_run_record(record)
    assert json.dumps(record, sort_keys=True) == before


FORGED_MARKERS = {
    "extra_key": {"kind": "float", "value": "+inf", "x": 1},
    "minus_inf": {"kind": "float", "value": "-inf"},
    "nan": {"kind": "float", "value": "nan"},
    "capitalised": {"kind": "float", "value": "+Inf"},
    "infinity_word": {"kind": "float", "value": "Infinity"},
    "other_kind": {"kind": "int", "value": "+inf"},
    "missing_value": {"kind": "float"},
    "value_not_text": {"kind": "float", "value": 1},
    "empty": {},
    "plain_text": "+inf",
    "list": ["+inf"],
}


@pytest.mark.parametrize("label", sorted(FORGED_MARKERS))
def test_a_forged_marker_at_a_closed_path_is_left_untouched(label):
    record = _record(wf_run(LOSS_FREE_FOLD, FINITE_FOLD))
    record["evidence"]["fold_results"][0]["profit_factor"] = FORGED_MARKERS[label]
    assert vr.decode_validation_run_record(record)["evidence"]["fold_results"][0]["profit_factor"] == FORGED_MARKERS[label]


def test_a_marker_with_swapped_key_order_is_the_same_json_object_and_decodes():
    record = _record(wf_run(LOSS_FREE_FOLD, FINITE_FOLD))
    record["evidence"]["fold_results"][0]["profit_factor"] = {"value": "+inf", "kind": "float"}
    assert vr.decode_validation_run_record(record)["evidence"]["fold_results"][0]["profit_factor"] == INF


def test_a_marker_outside_the_closed_paths_stays_a_dictionary():
    record = _record(wf_run(LOSS_FREE_FOLD, FINITE_FOLD))
    record["evidence"]["fold_results"][0]["net_ret_pct"] = dict(MARKER)
    record["strategy_params"] = {"x": dict(MARKER)}
    decoded = vr.decode_validation_run_record(record)
    assert decoded["evidence"]["fold_results"][0]["net_ret_pct"] == MARKER and decoded["strategy_params"] == {"x": MARKER}


def test_a_marker_equal_dictionary_outside_the_closed_paths_is_written_as_is_and_reloaded_as_a_dictionary(tmp_path):
    """Contrat ligne 3 : côté écrivain, un dictionnaire égal au marqueur hors chemin fermé n'est ni refusé ni converti."""
    run = dataclasses.replace(oos_run(profit_factor=2.0, win_rate=50.0), strategy_params={"x": dict(MARKER)})
    path = written(tmp_path, run)
    assert json.loads(path.read_text(encoding="utf-8"))["strategy_params"] == {"x": MARKER}
    assert path.read_bytes() == _old_bytes(run)
    assert load_validation_run(path).strategy_params == {"x": MARKER}


def test_the_path_table_is_bound_to_the_validation_type_of_the_record():
    record = _record(wf_run(LOSS_FREE_FOLD, FINITE_FOLD))
    record["validation_type"] = VALIDATION_TYPE_MONTE_CARLO
    assert vr.decode_validation_run_record(record)["evidence"]["fold_results"][0]["profit_factor"] == MARKER


def test_a_marker_in_an_oos_evidence_is_decoded_only_for_the_oos_type():
    record = {"validation_type": VALIDATION_TYPE_OOS, "evidence": {"profit_factor": dict(MARKER)}}
    assert vr.decode_validation_run_record(record)["evidence"]["profit_factor"] == INF
    other = {"validation_type": VALIDATION_TYPE_WALK_FORWARD, "evidence": {"profit_factor": dict(MARKER)}}
    assert vr.decode_validation_run_record(other)["evidence"]["profit_factor"] == MARKER


TOTAL_DECODER_INPUTS = {
    "root_list": [1, 2],
    "root_text": "x",
    "root_none": None,
    "root_int": 3,
    "validation_type_list": {"validation_type": [], "evidence": {}},
    "validation_type_dict": {"validation_type": {}, "evidence": {}},
    "validation_type_int": {"validation_type": 1, "evidence": {}},
    "validation_type_none": {"validation_type": None, "evidence": {}},
    "validation_type_bool": {"validation_type": True, "evidence": {}},
    "no_validation_type": {"evidence": {}},
    "evidence_not_a_dict": {"validation_type": "walk_forward", "evidence": [1, 2]},
    "evidence_none": {"validation_type": "walk_forward", "evidence": None},
    "fold_results_dict": {"validation_type": "walk_forward", "evidence": {"fold_results": {"profit_factor": dict(MARKER)}}},
    "fold_results_text": {"validation_type": "walk_forward", "evidence": {"fold_results": "profit_factor"}},
    "fold_element_not_a_dict": {"validation_type": "walk_forward", "evidence": {"fold_results": [1, "x", None, [dict(MARKER)]]}},
    "aggregate_list": {"validation_type": "walk_forward", "evidence": {"aggregate": [dict(MARKER)]}},
    "tuple_folds": {"validation_type": "walk_forward", "evidence": {"fold_results": ({"profit_factor": dict(MARKER)},)}},
}


@pytest.mark.parametrize("label", sorted(TOTAL_DECODER_INPUTS))
def test_the_decoder_is_total_no_data_raises_an_exception(label):
    value = TOTAL_DECODER_INPUTS[label]
    snapshot = json.dumps(value, sort_keys=True, default=list)
    result = vr.decode_validation_run_record(value)
    assert json.dumps(value, sort_keys=True, default=list) == snapshot, "l'entrée n'est jamais modifiée"
    if label != "tuple_folds":      # seule forme décodée : le tuple de plis est traité comme une liste (test suivant)
        assert result == value, "une forme inattendue est rendue telle quelle, jamais « réparée »"


def test_the_decoder_treats_a_tuple_of_folds_like_a_list_of_folds():
    record = TOTAL_DECODER_INPUTS["tuple_folds"]
    assert vr.decode_validation_run_record(record)["evidence"]["fold_results"][0]["profit_factor"] == INF


def test_a_text_fold_results_is_never_iterated_character_by_character():
    decoded = vr.decode_validation_run_record(TOTAL_DECODER_INPUTS["fold_results_text"])
    assert decoded["evidence"]["fold_results"] == "profit_factor"


# ═══ 13, 15. lecteur : historique, absent, corrompu, forgé ═══════════════════════════════════════════════════════════════════════════

def test_a_historical_file_with_the_non_standard_infinity_token_loads_as_before(tmp_path):
    run = oos_run(profit_factor=INF, win_rate=100.0)
    path = tmp_path / "legacy.json"
    path.write_bytes(_old_bytes(run))
    assert b"Infinity" in path.read_bytes()
    assert load_validation_run(path) == run


def test_a_historical_walk_forward_file_loads_with_infinity_in_the_nested_dictionaries(tmp_path):
    path = tmp_path / "legacy_wf.json"
    path.write_bytes(_old_bytes(wf_run(LOSS_FREE_FOLD, FINITE_FOLD)))
    assert load_validation_run(path).evidence.fold_results[0]["profit_factor"] == INF


def test_a_historical_file_is_never_rewritten_by_the_loader(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_bytes(_old_bytes(oos_run(profit_factor=INF)))
    before = path.read_bytes()
    load_validation_run(path)
    assert path.read_bytes() == before


def test_a_missing_or_corrupted_file_loads_as_none(tmp_path):
    assert load_validation_run(tmp_path / "absent.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_validation_run(bad) is None
    truncated = written(tmp_path, wf_run(LOSS_FREE_FOLD, FINITE_FOLD))
    cut = tmp_path / "cut.json"
    cut.write_bytes(truncated.read_bytes()[:-40])
    assert load_validation_run(cut) is None


def test_a_forged_marker_in_an_oos_file_loads_without_exception_and_stays_a_dictionary(tmp_path):
    path = written(tmp_path, oos_run(profit_factor=INF, win_rate=100.0))
    record = json.loads(path.read_text(encoding="utf-8"))
    record["evidence"]["profit_factor"] = {"kind": "float", "value": "-inf"}
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps(record), encoding="utf-8")
    assert load_validation_run(forged).evidence.profit_factor == {"kind": "float", "value": "-inf"}


@pytest.mark.parametrize("bad_type", [[], {}])
def test_an_unhashable_validation_type_keeps_raising_type_error_in_the_loader(tmp_path, bad_type):
    record = json.loads(written(tmp_path, oos_run(profit_factor=2.0)).read_text(encoding="utf-8"))
    record["validation_type"] = bad_type
    path = tmp_path / "bad_type.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(TypeError):
        load_validation_run(path)


def test_the_tolerant_reader_and_the_strict_reader_agree_on_the_decoded_record(tmp_path):
    from gate_v_exposure_scan import parse_strict_json
    path = written(tmp_path, wf_run(LOSS_FREE_FOLD, LOSS_FREE_FOLD))
    tolerant = vr.decode_validation_run_record(json.loads(path.read_text(encoding="utf-8")))
    strict = vr.decode_validation_run_record(parse_strict_json(path.read_bytes(), max_bytes=10**7, max_depth=64))
    assert tolerant == strict


# ═══ canonique : charge utile de l'empreinte OOS ═══════════════════════════════════════════════════════════════════════════════════

def _old_payload(run) -> str:
    return json.dumps(dataclasses.asdict(run), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize("run", [oos_run(profit_factor=1.75, win_rate=50.0, max_dd_pct=3.0), oos_run(n_trades=0, net_ret_pct=0.0),
                                 oos_run(profit_factor=np.float64(2.0), win_rate=np.float64(50.0))])
def test_the_canonical_payload_of_a_finite_oos_run_equals_the_old_payload_byte_for_byte(run):
    assert vr.canonical_oos_evidence_payload(run) == _old_payload(run)


def test_the_canonical_payload_of_an_infinite_oos_run_is_computable_and_deterministic():
    run = oos_run(profit_factor=INF, win_rate=100.0)
    with pytest.raises(ValueError):
        _old_payload(run)
    payload = vr.canonical_oos_evidence_payload(run)
    assert payload == vr.canonical_oos_evidence_payload(run)
    assert '"profit_factor":{"kind":"float","value":"+inf"}' in payload and "Infinity" not in payload


def test_the_payload_of_a_reloaded_infinite_oos_run_equals_the_payload_of_the_original(tmp_path):
    run = oos_run(profit_factor=INF, win_rate=100.0)
    assert vr.canonical_oos_evidence_payload(load_validation_run(written(tmp_path, run))) == vr.canonical_oos_evidence_payload(run)


def test_the_canonical_payload_is_injective_between_the_marker_dictionary_and_infinity():
    with pytest.raises(vr.NonFiniteMetricRefused):
        vr.canonical_oos_evidence_payload(oos_run(profit_factor=dict(MARKER)))


def test_the_canonical_payload_refuses_non_text_keys_and_nan():
    with pytest.raises(vr.NonFiniteMetricRefused):
        vr.canonical_oos_evidence_payload(dataclasses.replace(oos_run(profit_factor=2.0), strategy_params={1: "a"}))
    with pytest.raises(vr.NonFiniteMetricRefused):
        vr.canonical_oos_evidence_payload(oos_run(profit_factor=math.nan))


# ═══ D-S1-1 : un fichier OOS historique à flottant non fini reste refusé (comportement actuel) ═════════════════════════════════════

def _legacy_oos_file(tmp_path, mutate=None, name="legacy_oos.json"):
    path = tmp_path / name
    text = _old_bytes(oos_run(profit_factor=2.0, win_rate=50.0)).decode("utf-8")
    if mutate is not None:
        text = mutate(text)
    path.write_text(text, encoding="utf-8")
    return path


LEGACY_NON_FINITE = {
    "infinity_token": lambda t: t.replace('"profit_factor": 2.0', '"profit_factor": Infinity'),
    "minus_infinity_token": lambda t: t.replace('"profit_factor": 2.0', '"profit_factor": -Infinity'),
    "nan_token": lambda t: t.replace('"profit_factor": 2.0', '"profit_factor": NaN'),
    "overflowing_literal": lambda t: t.replace('"profit_factor": 2.0', '"profit_factor": 1e999'),
    "infinity_in_strategy_params": lambda t: t.replace('"lookback": 12', '"lookback": Infinity'),
    "nan_in_evidence_net_return": lambda t: t.replace('"net_ret_pct": 1.5', '"net_ret_pct": NaN'),
}


@pytest.mark.parametrize("label", sorted(LEGACY_NON_FINITE))
def test_a_legacy_oos_file_with_a_non_finite_float_is_refused_with_an_oos_message(tmp_path, label):
    path = _legacy_oos_file(tmp_path, LEGACY_NON_FINITE[label])
    with pytest.raises(ValueError, match="OOS"):
        vr.require_no_legacy_non_finite_in_run_file(path)


def test_a_finite_oos_file_and_a_marker_file_pass_the_legacy_check(tmp_path):
    vr.require_no_legacy_non_finite_in_run_file(_legacy_oos_file(tmp_path))
    vr.require_no_legacy_non_finite_in_run_file(written(tmp_path, oos_run(profit_factor=INF, win_rate=100.0)))


def test_the_legacy_check_adds_no_refusal_for_duplicate_keys_nor_for_extra_top_level_keys(tmp_path):
    duplicate = _legacy_oos_file(tmp_path, lambda t: t.replace('"status": "completed"', '"status": "completed", "status": "completed"'), "dup.json")
    vr.require_no_legacy_non_finite_in_run_file(duplicate)
    extra = _legacy_oos_file(tmp_path, lambda t: t.replace('"status": "completed"', '"status": "completed", "extra": Infinity'), "extra.json")
    vr.require_no_legacy_non_finite_in_run_file(extra)


@pytest.mark.parametrize("make", [lambda p: p / "absent.json", lambda p: p])
def test_the_legacy_check_turns_unreadable_files_into_value_errors_naming_oos(tmp_path, make):
    target = make(tmp_path)
    with pytest.raises(ValueError, match="OOS"):
        vr.require_no_legacy_non_finite_in_run_file(target)


def test_the_legacy_check_turns_invalid_utf8_and_invalid_json_into_value_errors_naming_oos(tmp_path):
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValueError, match="OOS"):
        vr.require_no_legacy_non_finite_in_run_file(binary)
    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError, match="OOS"):
        vr.require_no_legacy_non_finite_in_run_file(broken)


# ═══ constantes, imports, périmètre, FINAL_HOLDOUT, surfaces ═══════════════════════════════════════════════════════════════════════

def test_the_encoding_version_is_a_module_constant_and_never_a_top_level_key(tmp_path):
    assert vr.NON_FINITE_ENCODING_VERSION == "validation_run_non_finite_encoding_v1"
    record = json.loads(written(tmp_path, wf_run(LOSS_FREE_FOLD, FINITE_FOLD)).read_text(encoding="utf-8"))
    assert vr.NON_FINITE_ENCODING_VERSION not in json.dumps(record)
    assert set(record) == {"validation_run_id", "research_run_id", "split_plan_id", "dataset_snapshot_id", "validation_type",
                           "strategy_name", "strategy_params", "specification", "evidence", "status", "completed_at"}


def test_validation_run_imports_only_the_standard_library_and_atomic_json_store():
    tree = ast.parse(Path(vr.__file__).read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    assert not {m for m in modules if m.startswith("gate_v_")}
    assert modules <= set(sys.stdlib_module_names) | {"atomic_json_store"}


# NB : la tranche PN-1-S2 modifiera `walk_forward.py` (3 lecteurs / écrivains intermédiaires) : elle devra mettre à jour explicitement l'épingle
# `walk_forward.py` ci-dessous, avec sa justification, et non la contourner.
_FORBIDDEN_MODULE_PINS = {
    "walk_forward.py": "dc83bcc4bf4912b3b165f04fd741bdfc43bd6921920efbd226fff7caf6a3879c",
    "engine.py": "451e80c4d74b4cb9fc0218736986d044fc39ff8a94c1393d82d75ee102e4e753",
    "scoring.py": "4919dcb8454a2f0995ef268bc84da565bde016e83d8c28185172e093a6f71d22",
    "atomic_json_store.py": "3e354c32797379aa6b5e2f28dff1e52f3844ee4a59f5c401718d0acb677da577",
    "validation_oos.py": "1d53cfcca02db38463d6b27ed26517a17c59ecaf7bad45f2e7e3a0f4a9f27c6c",
    "optimizer.py": "63e22aed2f3be03454013a35398bdfa690864467f0a6006ea4ec3bee6066bf59",
    "gate_v_exposure_scan.py": "dacc0f8ba1fda33dfd7bc9c8234a42e62309fe7dc6cd7ecabc087d8d98a194a2",
    "gate_v_exposure_interpreters.py": "a1f0da2573c8ed2935b89669d72ab87eab3d7b1382cfb592db2f7ce48eef330e",
    "gate_v_exposure_interpreters_v5.py": "9f6414ffe2a331e5b01bbaf7bbddffebf48850c59187728fd9ccee4b09392a88",
    "gate_v_exposure_interpreters_v6.py": "defd94c4614a54ea0e03f3915c3b2b8d3d1f0a13000767b4a77efed98ca00b14",
    "gate_v_k1s2_verifier.py": "ef542aa0d766765ee3d669fe6e3806827a3b7c4bb88a459214c2855e956d9547",
    "gate_v_k1s2_emptiness.py": "bf806b7e6e3d7557a6f21e7a06d6774bb4342b99707c3b287118957f9492acc6",
    "gate_v_evidence_completeness_v2.py": "191c77c0d50f362b7dd00a49f701e10ca99ca04223460d29c395825d9667f1f7",
    "gate_v_campaign_manifest_v2.py": "503f5b993870f50e2a838d42370f33dfa12b87c8a241db5a28e2db7c911dcf3f",
    "gate_v_final_holdout_protocol.py": "81fbb24b15a73b92f9926ff1478cc89a7f7a8af852f3edcdf2688c2978061b82",
    "gate_v_final_holdout_claim.py": "1bf2f88d75174150850f21995a6041b1f02b62f51103ecd180080116d608a0b8",
    "gate_v_final_holdout_claim_acquisition.py": "6b28e449d492ac4d3f0139e8166047c544dfd73d1f8c6c1df51e6f8f317350ff",
    "gate_v_registry_store.py": "48182a4ec82c36da009cd87ec9aad711c663d5258e62a503c440083b8c49c1ee",
    "gate_v_registry_chain.py": "b39839cb838c50ffa6b91263beed8a2097714fa8910f408df58184fb0fdb75f3",
    "gate_v_registry_append.py": "bf5d3a969260f7cfd17c7d747084c1e95afa351476b76b248d6f6e54f3865eec",
    "gate_v_registry_model.py": "59685d3a8fe9d69cc97c48ef092061c7a508f9944703d71835f6092036ffd361",
}


@pytest.mark.parametrize("name", sorted(_FORBIDDEN_MODULE_PINS))
def test_the_modules_outside_the_slice_are_unchanged_including_every_final_holdout_module(name):
    """Interdits de la tranche (contrat §5) : engine, scoring, walk_forward, B2/B3/L3-A, registre, FINAL_HOLDOUT, `validation_oos`."""
    data = (Path(vr.__file__).resolve().parent / name).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest() == _FORBIDDEN_MODULE_PINS[name]


_WRITER_SURFACES = {
    ("dataset_split.py", "save_dataset_split_plan", "save_atomic"),
    ("dataset_split.py", "save_holdout_access_event", "save_atomic"),
    ("gate_v_campaign.py", "save_gate_v_campaign_manifest", "save_atomic_overwrite"),
    ("gate_v_campaign.py", "save_gate_v_campaign_plan", "save_atomic"),
    ("gate_v_campaign_manifest_v2.py", "_record_technical_failure_sentinel", "save_exclusive"),
    ("gate_v_campaign_manifest_v2.py", "create_gate_v_campaign_manifest_v2", "save_exclusive"),
    ("gate_v_campaign_manifest_v2.py", "update_gate_v_campaign_manifest_v2", "save_atomic_overwrite"),
    ("gate_v_campaign_plan_v2.py", "save_gate_v_campaign_plan_v2", "save_exclusive"),
    ("gate_v_exposure_store.py", "publish_exposure_inventory", "save_exclusive"),
    ("gate_v_final_holdout_claim_acquisition.py", "acquire_final_holdout_access_claim", "save_exclusive"),
    ("gate_v_preregistration.py", "save_gate_v_preregistration", "save_exclusive"),
    ("gate_v_validation_policy.py", "save_gate_v_validation_policy", "save_atomic"),
    ("research_run.py", "save_experiment", "save_atomic"),
    ("research_run.py", "save_research_run", "save_atomic"),
    ("validation_run.py", "save_validation_run", "save_atomic"),
    ("walk_forward.py", "_prepare_captured_run", "save_atomic"),
    ("walk_forward.py", "_save_captured_fold", "save_atomic"),
    ("walk_forward.py", "persist_walk_forward_run", "save_atomic"),
}


def test_the_set_of_production_writers_that_can_still_emit_non_finite_json_is_pinned():
    """Surfaces d'écriture JSON par défaut (`json.dumps` sans `allow_nan=False`) : un nouvel écrivain fait échouer ce test (revue requise).
    Seul `save_validation_run` passe par la garde PN-1-S1 ; `walk_forward.py` (3 surfaces) relève de PN-1-S2."""
    root = Path(vr.__file__).resolve().parent
    names = {"save_atomic", "save_atomic_overwrite", "save_exclusive"}
    found = set()
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", "scripts/", ".venv/")) or "__pycache__" in rel:
            continue
        if rel == "exploration_campaign.py":
            continue    # écrivain de l'état d'une campagne d'exploration (autre programme, fichier présent seulement dans l'arbre de travail
            #            de C:) : hors périmètre PN-1 ; consigné comme risque ouvert dans le handoff
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        stack = []

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else None)
                if name in names:
                    found.add((rel, ".".join(stack) or "<module>", name))
                self.generic_visit(node)

        Visitor().visit(tree)
    assert found == _WRITER_SURFACES
