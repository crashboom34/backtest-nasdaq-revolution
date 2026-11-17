"""Scoring Integrity (finite-metrics-v1) — chemins scientifiques (ADR 0029, C13-C15, S-1, F-1..F-16).

Seams : `optimizer._run_single` (frontière moteur → optimizer), `Optimizer._run_batch_sequential` /
`_run_batch_parallel`, `Optimizer.run`, `optimizer.validate_resume_scoring_semantics`.
Moteur réel remplacé par un faux qui rend des artefacts COHÉRENTS calculés par le vrai
`engine._compute_stats` (aucune valeur attendue recalculée « comme le code »).
"""
from __future__ import annotations

import concurrent.futures
import math

import numpy as np
import pandas as pd
import pytest

import engine
import optimizer
from optimizer import FilterConfig, Optimizer, ScoreWeights, TrainTestConfig, _run_single, params_hash
from tests.test_optimizer import _build_synthetic_df, _minimal_config

NAN = float("nan")
INF = float("inf")
NEUTRAL = FilterConfig(min_trades=0, max_drawdown_pct=INF, min_profit_factor=0.0,
                       max_consecutive_losses=2**31 - 1, min_win_rate=0.0)
REQUIRED = ("n_trades", "n_win", "n_loss", "win_rate", "profit_factor", "payoff", "gross_win",
            "gross_loss", "max_dd_pct", "max_dd_usd", "max_consec_loss", "net_ret_pct",
            "net_ret_usd", "equity_r_squared")


def engine_result(pnls, capital=10_000.0, equity_override=None):
    """(trades, equity, stats) cohérents : stats produites par le VRAI engine._compute_stats."""
    n = len(pnls)
    t0 = pd.Timestamp("2024-01-02 10:00", tz="UTC")
    entries = [t0 + pd.Timedelta(minutes=30 * i) for i in range(n)]
    trades = pd.DataFrame({
        "resultat_net": [float(p) for p in pnls],
        "date_entree": entries,
        "date_sortie": [e + pd.Timedelta(minutes=3) for e in entries],
        "raison_sortie": ["target"] * n,
    })
    caps = list(np.cumsum([capital] + [float(p) for p in pnls]))
    if equity_override is not None:
        caps = list(equity_override)
    equity = pd.DataFrame({
        "date": [t0 + pd.Timedelta(minutes=3 * i) for i in range(len(caps))],
        "capital": caps,
    })
    stats = engine._compute_stats(trades, equity, capital, caps[-1]) if n else {"n_trades": 0}
    return trades, equity, stats


GOOD = engine_result([10.0, -5.0, 12.0, -4.0, 8.0, 7.0, -3.0, 9.0, 11.0, -2.0, 6.0, 5.0])


def zero_trade(equity_caps=(10_000.0, 10_000.0, 10_000.0)):
    _t, equity, _s = engine_result([], equity_override=list(equity_caps))
    return pd.DataFrame(), equity, {"n_trades": 0}


class FakeEngine:
    """Remplace `engine.run_backtest` ; `by_boundary` permet de distinguer TRAIN (exclusive) et
    TEST (inclusive) dans `Optimizer.run`."""

    def __init__(self, result=None, by_boundary=None, raise_on=None):
        self.result, self.by_boundary, self.raise_on, self.calls = result, by_boundary or {}, raise_on, []

    def __call__(self, df, strat, params, **kw):
        self.calls.append(dict(kw, params=params))
        boundary = kw.get("end_boundary", "inclusive")
        if self.raise_on == boundary:
            raise RuntimeError("moteur en panne")
        trades, equity, stats = self.by_boundary.get(boundary, self.result)
        return trades.copy(), equity.copy(), dict(stats)


def run_single(monkeypatch, result, **kw):
    monkeypatch.setattr(engine, "run_backtest", FakeEngine(result))
    return _run_single({}, _minimal_config(filters=NEUTRAL), _build_synthetic_df(5), None, None, **kw)


def assert_typed(result, code, field):
    assert result["score"] == 0.0 and result["filtered"] is True, result
    assert result["filter_reason"] == f"INVALID_METRIC:{code}:{field}", result["filter_reason"]


# ── Frontière moteur → optimizer (C13, U-2 strict) ───────────────────────────────────────────────

def test_good_engine_result_is_scored(monkeypatch):
    res = run_single(monkeypatch, GOOD)
    assert res["filtered"] is False and res["score"] > 0


def test_r34_authentic_zero_trade_keeps_its_historical_contract(monkeypatch):
    res = run_single(monkeypatch, zero_trade())
    assert res["filter_reason"] == "Aucun trade" and res["score"] == 0.0


@pytest.mark.parametrize("trades, stats", [
    (pd.DataFrame(), {}),
    (pd.DataFrame(), {"n_trades": 0, "profit_factor": 2.0}),
    (pd.DataFrame(), {"n_trades": False}),
    (pd.DataFrame(), dict(GOOD[2])),
    (GOOD[0], {"n_trades": 0}),
], ids=["empty_dict", "extra_keys", "bool_zero", "trades_missing", "trades_present"])
def test_r35_malformed_zero_trade_is_never_a_zero_trade(monkeypatch, trades, stats):
    res = run_single(monkeypatch, (trades, GOOD[1], stats))
    assert_typed(res, "INCOHERENT", "zero_trade")


def test_f8_zero_trade_with_non_finite_equity_is_invalid(monkeypatch):
    res = run_single(monkeypatch, zero_trade((10_000.0, NAN, 10_000.0)))
    assert_typed(res, "NON_FINITE", "equity.capital")


@pytest.mark.parametrize("key", REQUIRED)
def test_r36_missing_required_metric_is_rejected(monkeypatch, key):
    stats = {k: v for k, v in GOOD[2].items() if k != key}
    res = run_single(monkeypatch, (GOOD[0], GOOD[1], stats))
    assert_typed(res, "MISSING", key)


def test_r37_non_finite_trade_pnl_is_rejected(monkeypatch):
    trades = GOOD[0].copy()
    trades.loc[3, "resultat_net"] = NAN
    res = run_single(monkeypatch, (trades, GOOD[1], GOOD[2]))
    assert_typed(res, "NON_FINITE", "trades.resultat_net")


def test_r38_masked_drawdown_from_non_finite_equity_is_rejected(monkeypatch):
    pnls = [10.0, -5.0, 12.0, -4.0]
    caps = [10_000.0, 10_010.0, NAN, 10_017.0, 10_013.0]
    trades, equity, stats = engine_result(pnls, equity_override=caps)
    assert stats["max_dd_pct"] == 0.0  # le moteur masque le NaN (SI-11a)
    res = run_single(monkeypatch, (trades, equity, stats))
    assert_typed(res, "NON_FINITE", "equity.capital")


def test_r39_trade_count_must_match_trades(monkeypatch):
    res = run_single(monkeypatch, (GOOD[0].iloc[:-1], GOOD[1], GOOD[2]))
    assert_typed(res, "INCOHERENT", "n_trades")


@pytest.mark.parametrize("artifacts, field, code", [
    ((GOOD[0], GOOD[1], None), "stats", "TYPE"),
    ((None, GOOD[1], GOOD[2]), "trades", "TYPE"),
    ((GOOD[0], None, GOOD[2]), "equity", "TYPE"),
    ((GOOD[0].drop(columns=["resultat_net"]), GOOD[1], GOOD[2]), "trades.resultat_net", "MISSING"),
    ((GOOD[0], GOOD[1].drop(columns=["capital"]), GOOD[2]), "equity.capital", "MISSING"),
    ((GOOD[0].astype({"resultat_net": object}), GOOD[1], GOOD[2]), "trades.resultat_net", "TYPE"),
], ids=["stats_none", "trades_none", "equity_none", "no_pnl_col", "no_capital_col", "object_dtype"])
def test_boundary_is_total_on_malformed_artifacts(monkeypatch, artifacts, field, code):
    class _Raw(FakeEngine):
        def __call__(self, df, strat, params, **kw):
            return artifacts
    monkeypatch.setattr(engine, "run_backtest", _Raw())
    res = _run_single({}, _minimal_config(filters=NEUTRAL), _build_synthetic_df(5), None, None)
    assert_typed(res, code, field)


def test_boundary_rejection_keeps_artifacts_when_requested(monkeypatch):
    trades = GOOD[0].copy()
    trades.loc[0, "resultat_net"] = NAN
    res = run_single(monkeypatch, (trades, GOOD[1], GOOD[2]), include_artifacts=True)
    assert res["filter_reason"].startswith("INVALID_METRIC:")
    assert res["trades"] is not None and res["equity"] is not None


# ── Configuration avant tout calcul (C14) ────────────────────────────────────────────────────────

def test_r41_invalid_weights_stop_optimizer_run_before_any_backtest(monkeypatch):
    fake = FakeEngine(GOOD)
    monkeypatch.setattr(engine, "run_backtest", fake)
    import dataclasses
    cfg = _minimal_config(filters=NEUTRAL, score_weights=dataclasses.replace(ScoreWeights(), win_rate=INF))
    with pytest.raises(optimizer.InvalidScoringConfiguration):
        Optimizer(cfg, _build_synthetic_df(10)).run(progress_cb=None, stop_flag_fn=None, already_tested=set())
    assert fake.calls == []


# ── Séquentiel / parallèle (C15, G-1, G-2, G-3) ──────────────────────────────────────────────────

class DeferredPool:
    """Faux `ProcessPoolExecutor` : vraies `Future`, exécution DIFFÉRÉE dans un unique thread (les
    futures en file restent annulables), enregistre `shutdown()` et `cancel()`."""
    instances = []

    def __init__(self, max_workers=None, initializer=None, initargs=()):
        if initializer:
            initializer(*initargs)
        self._inner = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.shutdown_calls, self.futures = [], []
        DeferredPool.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.shutdown(wait=True)
        return False

    def submit(self, fn, *args, **kwargs):
        fut = self._inner.submit(fn, *args, **kwargs)
        self.futures.append(fut)
        return fut

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdown_calls.append({"wait": wait, "cancel_futures": cancel_futures})
        self._inner.shutdown(wait=wait, cancel_futures=cancel_futures)


def _combos(n):
    return [{"stop_pct": 1.0 + i / 10} for i in range(n)]


@pytest.fixture
def deferred_pool(monkeypatch):
    DeferredPool.instances = []
    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", DeferredPool)
    return DeferredPool


def test_parallel_and_sequential_give_the_same_typed_rejection(monkeypatch, deferred_pool):
    trades = GOOD[0].copy()
    trades.loc[0, "resultat_net"] = NAN
    monkeypatch.setattr(engine, "run_backtest", FakeEngine((trades, GOOD[1], GOOD[2])))
    seq = Optimizer(_minimal_config(filters=NEUTRAL), _build_synthetic_df(10))
    par = Optimizer(_minimal_config(filters=NEUTRAL, n_workers=2), _build_synthetic_df(10))
    r_seq = seq._run_batch_sequential(_combos(2))
    r_par = par._run_batch_parallel(_combos(2))
    assert {r["filter_reason"] for r in r_seq} == {r["filter_reason"] for r in r_par} == {
        "INVALID_METRIC:NON_FINITE:trades.resultat_net"}


def test_r43_worker_error_propagates_and_cancels_pending_candidates(monkeypatch, deferred_pool):
    import threading
    gate = threading.Event()
    calls = {"n": 0}

    def worker(*args, **kwargs):  # erreur d'infrastructure du worker, hors de run_backtest
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("worker crash")
        gate.wait(0.5)
        raise RuntimeError("worker crash bis")

    monkeypatch.setattr(optimizer, "_worker_run_single", worker)
    opt = Optimizer(_minimal_config(filters=NEUTRAL, n_workers=2), _build_synthetic_df(10))
    tested = {"hash-de-reprise"}  # reprise : l'ensemble du processus est partagé (alias)
    with pytest.raises(RuntimeError, match="worker crash"):
        opt._run_batch_parallel(_combos(5), already_tested=tested)
    gate.set()
    pool = deferred_pool.instances[-1]
    assert any(c["cancel_futures"] for c in pool.shutdown_calls)
    assert sum(f.cancelled() for f in pool.futures) >= 1
    assert tested == {"hash-de-reprise"}  # aucun candidat non reçu n'est marqué testé


def test_g1_g2_cooperative_stop_harvests_completed_and_never_marks_cancelled_as_tested(
    monkeypatch, deferred_pool,
):
    import threading
    import time
    calls = {"n": 0}
    lock = threading.Lock()

    class _Slow(FakeEngine):
        def __call__(self, df, strat, params, **kw):
            with lock:
                calls["n"] += 1
                first = calls["n"] == 1
            if not first:
                time.sleep(0.3)  # le 2e candidat est EN COURS quand l'arrêt est demandé
            return super().__call__(df, strat, params, **kw)

    monkeypatch.setattr(engine, "run_backtest", _Slow(GOOD))
    opt = Optimizer(_minimal_config(filters=NEUTRAL, n_workers=2), _build_synthetic_df(10))
    tested = {"hash-de-reprise"}
    seen = []
    results = opt._run_batch_parallel(
        _combos(6), progress_cb=lambda d, t, r: seen.append(r), stop_flag_fn=lambda: len(seen) >= 1,
        already_tested=tested,
    )
    pool = deferred_pool.instances[-1]
    completed = [f for f in pool.futures if f.done() and not f.cancelled()]
    assert len(results) == len(completed) and 1 <= len(results) < 6
    assert tested == {"hash-de-reprise"} | {params_hash(r["params"]) for r in results}
    assert len(seen) == len(results)


def test_g2_sequential_marks_only_received_results_and_keeps_caller_set(monkeypatch):
    monkeypatch.setattr(engine, "run_backtest", FakeEngine(GOOD))
    opt = Optimizer(_minimal_config(filters=NEUTRAL), _build_synthetic_df(10))
    tested = {"hash-de-reprise"}
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 2

    results = opt._run_batch_sequential(_combos(5), stop_flag_fn=stop, already_tested=tested)
    assert tested == {"hash-de-reprise"} | {params_hash(r["params"]) for r in results}
    assert len(results) == 2


# ── S-1 L1 : TEST legacy invalide = échec technique (U-6 reportée) ───────────────────────────────

def _tt_config(**kw):
    from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
    return _minimal_config(filters=NEUTRAL, base_params=dict(DEFAULT_PARAMS),
                           train_test=TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.5), **kw)


def _run_tt(monkeypatch, test_result=None, raise_on=None):
    fake = FakeEngine(GOOD, by_boundary={"exclusive": GOOD, "inclusive": test_result or GOOD},
                      raise_on=raise_on)
    monkeypatch.setattr(engine, "run_backtest", fake)
    cfg = _tt_config()
    cfg.param_ranges = []
    return Optimizer(cfg, _build_synthetic_df(30)).run(progress_cb=None, stop_flag_fn=None, already_tested=set())


def test_r53_invalid_legacy_test_metric_is_a_technical_failure(monkeypatch):
    trades = GOOD[0].copy()
    trades.loc[0, "resultat_net"] = NAN
    with pytest.raises(optimizer.LegacyTestValidationFailed, match="INVALID_METRIC:NON_FINITE"):
        _run_tt(monkeypatch, test_result=(trades, GOOD[1], GOOD[2]))


def test_r54_engine_exception_on_legacy_test_is_a_technical_failure(monkeypatch):
    with pytest.raises(optimizer.LegacyTestValidationFailed, match="Exception:"):
        _run_tt(monkeypatch, raise_on="inclusive")


def test_g6_malformed_zero_trade_on_legacy_test_is_a_technical_failure(monkeypatch):
    with pytest.raises(optimizer.LegacyTestValidationFailed, match="INVALID_METRIC:INCOHERENT:zero_trade"):
        _run_tt(monkeypatch, test_result=(pd.DataFrame(), GOOD[1], {}))


def test_r55_authentic_zero_trade_on_legacy_test_keeps_legacy_behaviour(monkeypatch):
    results, _ = _run_tt(monkeypatch, test_result=zero_trade())
    assert results[0]["score_test"] == 0.0


def test_valid_legacy_test_is_unchanged(monkeypatch):
    results, _ = _run_tt(monkeypatch)
    assert results[0]["score_test"] == results[0]["score_train"] > 0


# ── Reprise optimizer (F-4) ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("source", [None, {}, {"scoring_semantics_version": None},
                                    {"scoring_semantics_version": "legacy"}])
def test_f4_resume_from_legacy_job_is_refused_even_without_train_test(source):
    with pytest.raises(optimizer.ScoringSemanticsMismatch):
        optimizer.validate_resume_scoring_semantics(source, "src_run")


def test_f4_resume_from_same_semantics_is_accepted():
    optimizer.validate_resume_scoring_semantics({"scoring_semantics_version": "finite-metrics-v1"}, "src")


# ── Revue de code : totalité de la frontière ─────────────────────────────────────────────────────

@pytest.mark.parametrize("trades", [
    pd.concat([GOOD[0], GOOD[0][["resultat_net"]]], axis=1),
    GOOD[0].assign(resultat_net=GOOD[0]["resultat_net"].astype(complex)),
], ids=["duplicated_column", "complex_dtype"])
def test_boundary_rejects_ambiguous_or_complex_pnl_columns(monkeypatch, trades):
    res = run_single(monkeypatch, (trades, GOOD[1], GOOD[2]))
    assert_typed(res, "TYPE", "trades.resultat_net")
