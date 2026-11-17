"""Scoring Integrity — Walk-Forward (ADR 0029 : C9, C12, U-8, U-9, versionnement, C14 à l'entrée).

Seams : `walk_forward.run_fold_test`, `_load_train_progress`, `select_fold_top1`,
`build_walk_forward_manifest`, `_fold_definition_fingerprint`, `check_resume_fingerprint`,
`run_walk_forward` / `resume_walk_forward_run`.
"""
from __future__ import annotations

import dataclasses
import json

import pandas as pd
import pytest

import engine
import walk_forward as wf
from optimizer import FilterConfig, ScoreWeights, params_hash
from tests.test_scoring_integrity_pipeline import GOOD, NEUTRAL, FakeEngine, zero_trade
from tests.test_walk_forward import (
    _build_synthetic_wf_df, _fold_selection, _minimal_optimizer_config, _readiness, _spec,
    _wf_fold, _write_test_data_manifest, _zone,
)

NAN = float("nan")


def _setup(monkeypatch, test_result, **cfg):
    df = _build_synthetic_wf_df(200)
    fold = _wf_fold(df["time_paris"].iloc[0].isoformat(), df["time_paris"].iloc[100].isoformat(),
                    df["time_paris"].iloc[199].isoformat())
    monkeypatch.setattr(engine, "run_backtest", FakeEngine(test_result))
    config = _minimal_optimizer_config(filters=NEUTRAL, **cfg)
    return fold, _fold_selection(fold), config, df


# ── C9 / U-8 : une métrique TEST invalide est un échec technique, jamais un score ────────────────

def test_c9_invalid_test_metric_raises_fold_test_execution_failed(monkeypatch):
    trades = GOOD[0].copy()
    trades.loc[0, "resultat_net"] = NAN
    fold, sel, cfg, df = _setup(monkeypatch, (trades, GOOD[1], GOOD[2]))
    with pytest.raises(wf.FoldTestExecutionFailed, match="INVALID_METRIC:NON_FINITE"):
        wf.run_fold_test(fold, sel, cfg, df)


@pytest.mark.parametrize("result", [
    (pd.DataFrame(), GOOD[1], {}),
    zero_trade((10_000.0, NAN)),
], ids=["malformed_zero_trade", "zero_trade_nan_equity"])
def test_u8_invalid_zero_trade_is_never_zero_trade_oos(monkeypatch, result):
    fold, sel, cfg, df = _setup(monkeypatch, result)
    with pytest.raises(wf.FoldTestExecutionFailed):
        wf.run_fold_test(fold, sel, cfg, df)


def test_u8_invalid_configuration_on_test_is_a_technical_failure(monkeypatch):
    fold, sel, cfg, df = _setup(monkeypatch, GOOD,
                                score_weights=dataclasses.replace(ScoreWeights(), win_rate=-1.0))
    with pytest.raises(wf.FoldTestExecutionFailed, match="INVALID_CONFIG"):
        wf.run_fold_test(fold, sel, cfg, df)


def test_authentic_zero_trade_test_is_still_zero_trade_oos(monkeypatch):
    fold, sel, cfg, df = _setup(monkeypatch, zero_trade())
    assert wf.run_fold_test(fold, sel, cfg, df).zero_trade_oos is True


def test_poor_but_valid_test_performance_is_a_measured_fact(monkeypatch):
    from tests.test_scoring_integrity_pipeline import engine_result
    fold, sel, cfg, df = _setup(monkeypatch, engine_result([-5.0, -3.0, 1.0, -4.0]))
    result = wf.run_fold_test(fold, sel, cfg, df)
    assert result.zero_trade_oos is False and result.n_trades == 4


# ── C12 : reprise TRAIN depuis train_progress.csv ───────────────────────────────────────────────

@pytest.mark.parametrize("bad_score", ["nan", "inf", "-inf", "-1", "100.5"])
def test_c12_non_finite_or_out_of_range_reused_score_is_never_reloaded(tmp_path, bad_score):
    df = _build_synthetic_wf_df(200)
    fold = _wf_fold(df["time_paris"].iloc[0].isoformat(), df["time_paris"].iloc[100].isoformat(),
                    df["time_paris"].iloc[199].isoformat())
    cfg = _minimal_optimizer_config(filters=NEUTRAL)
    wf._write_train_progress(tmp_path, fold, cfg, [{"params": {"a": 1}, "score": 50.0, "filter_reason": ""}])
    path = wf._train_progress_path(tmp_path)
    frame = pd.read_csv(path)
    assert "filter_reason" in frame.columns  # U-9 : motif persisté par candidat
    frame["score"] = frame["score"].astype(object)
    frame.loc[0, "score"] = bad_score
    frame.to_csv(path, index=False)
    assert wf._load_train_progress(tmp_path, fold, cfg) == []


def test_c12_valid_reused_candidate_keeps_its_reason(tmp_path):
    df = _build_synthetic_wf_df(200)
    fold = _wf_fold(df["time_paris"].iloc[0].isoformat(), df["time_paris"].iloc[100].isoformat(),
                    df["time_paris"].iloc[199].isoformat())
    cfg = _minimal_optimizer_config(filters=NEUTRAL)
    wf._write_train_progress(tmp_path, fold, cfg, [
        {"params": {"a": 1}, "score": 50.0, "filter_reason": ""},
        {"params": {"a": 2}, "score": 0.0, "filter_reason": "INVALID_METRIC:NON_FINITE:payoff"},
    ])
    loaded = wf._load_train_progress(tmp_path, fold, cfg)
    assert [c["filter_reason"] for c in loaded] == ["", "INVALID_METRIC:NON_FINITE:payoff"]


# ── U-9 : populations TRAIN distinguées, sans seuil d'abandon ───────────────────────────────────

def _cand(score, reason=None, params=None):
    c = {"params": params or {"x": score, "r": reason}, "score": score}
    if reason is not None:
        c["filtered"] = score <= 0
        c["filter_reason"] = reason
    return c


def _fold_and_cfg():
    df = _build_synthetic_wf_df(10)
    fold = _wf_fold(df["time_paris"].iloc[0].isoformat(), df["time_paris"].iloc[5].isoformat(),
                    df["time_paris"].iloc[9].isoformat())
    return fold, _minimal_optimizer_config(filters=NEUTRAL)


@pytest.mark.parametrize("population, expected", [
    ([_cand(0.0, "Trop peu de trades (3 < 30)"), _cand(0.0, "Aucun trade")],
     dict(n_non_performant=2, n_invalid_metric=0, n_invalid_config=0, n_exception=0, n_unclassified_reused=0)),
    ([_cand(0.0, "INVALID_METRIC:NON_FINITE:payoff"), _cand(0.0, "INVALID_METRIC:MISSING:gross_win")],
     dict(n_non_performant=0, n_invalid_metric=2, n_invalid_config=0, n_exception=0, n_unclassified_reused=0)),
    ([_cand(0.0, "INVALID_CONFIG:OUT_OF_DOMAIN:weights.total"), _cand(0.0, "Exception: boom"),
      _cand(0.0, "Drawdown trop élevé"), _cand(0.0)],
     dict(n_non_performant=1, n_invalid_metric=0, n_invalid_config=1, n_exception=1, n_unclassified_reused=1)),
], ids=["all_non_performant", "all_invalid", "mixed_with_reused"])
def test_u9_no_eligible_candidate_reports_typed_population_counts(population, expected):
    fold, cfg = _fold_and_cfg()
    with pytest.raises(wf.NoEligibleTrainCandidate) as exc:
        wf.select_fold_top1(fold, population, cfg)
    assert {k: getattr(exc.value, k) for k in expected} == expected
    for k, v in expected.items():
        assert f"{k}={v}" in str(exc.value)


def test_u9_invalid_candidates_are_never_selected_in_a_mixed_population():
    fold, cfg = _fold_and_cfg()
    population = [_cand(30.0, ""), _cand(0.0, "INVALID_METRIC:NON_FINITE:payoff")]
    assert wf.select_fold_top1(fold, population, cfg).score_train == 30.0


# ── Versionnement (finite-metrics-v1) ───────────────────────────────────────────────────────────

def test_run_manifest_carries_the_scoring_semantics(tmp_path):
    path, _ = _write_test_data_manifest(tmp_path)
    manifest = wf.build_walk_forward_manifest(_spec(), _minimal_optimizer_config(), path)
    assert manifest["scoring_semantics_version"] == "finite-metrics-v1"
    assert manifest["walk_forward_semantics_version"] != manifest["scoring_semantics_version"]


def test_fold_fingerprint_depends_on_the_scoring_semantics(monkeypatch):
    fold, cfg = _fold_and_cfg()
    current = wf._fold_definition_fingerprint(fold, cfg)
    monkeypatch.setattr(wf, "SCORING_SEMANTICS_VERSION", "legacy")
    assert wf._fold_definition_fingerprint(fold, cfg) != current


def test_g13_resume_of_a_legacy_run_manifest_is_refused(tmp_path):
    path, _ = _write_test_data_manifest(tmp_path)
    current = wf.build_walk_forward_manifest(_spec(), _minimal_optimizer_config(), path)
    legacy = {k: v for k, v in current.items() if k != "scoring_semantics_version"}
    out = tmp_path / "run"
    out.mkdir()
    (out / "manifest.json").write_text(json.dumps(legacy, default=str), encoding="utf-8")
    with pytest.raises(wf.WalkForwardResumeMismatch, match="scoring_semantics_version"):
        wf.check_resume_fingerprint(out, json.loads(json.dumps(current, default=str)))


# ── C14 : configuration invalide refusée à l'entrée, avant tout backtest ────────────────────────

@pytest.mark.parametrize("entry", ["run", "resume"])
def test_invalid_configuration_is_refused_before_any_walk_forward_backtest(monkeypatch, tmp_path, entry):
    fake = FakeEngine(GOOD)
    monkeypatch.setattr(engine, "run_backtest", fake)
    cfg = _minimal_optimizer_config(filters=FilterConfig(min_trades=NAN))
    df = _build_synthetic_wf_df(50)
    zone = _zone(df["time_paris"].iloc[0].isoformat(), df["time_paris"].iloc[-1].isoformat())
    import optimizer
    with pytest.raises(optimizer.InvalidScoringConfiguration):
        if entry == "run":
            wf.run_walk_forward(zone, _spec(), _readiness(), cfg, df)
        else:
            path, _ = _write_test_data_manifest(tmp_path)
            wf.resume_walk_forward_run(zone, _spec(), _readiness(), cfg, df, path, tmp_path / "out")
    assert fake.calls == []


def test_empty_test_equity_on_a_covered_window_is_never_zero_trade_oos(monkeypatch):
    fold, sel, cfg, df = _setup(monkeypatch, (pd.DataFrame(), pd.DataFrame(), {"n_trades": 0}))
    with pytest.raises(wf.FoldTestExecutionFailed, match="equity TEST vide"):
        wf.run_fold_test(fold, sel, cfg, df)


def test_c12_forged_eligible_row_with_a_technical_reason_is_never_reloaded(tmp_path):
    fold, cfg = _fold_and_cfg()
    wf._write_train_progress(tmp_path, fold, cfg, [
        {"params": {"a": 1}, "score": 50.0, "filter_reason": "INVALID_METRIC:NON_FINITE:payoff"},
    ])
    assert wf._load_train_progress(tmp_path, fold, cfg) == []
