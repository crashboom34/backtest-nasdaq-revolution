"""
tests/test_validation_oos.py — AF-V-01 : orchestration de la première ValidationRun OOS réelle.

validation_oos.py::run_oos_validation() est une fonction PURE (`/codebase-design`) : reçoit un
`run_backtest_fn` injectable (jamais un import direct de engine.py — testable sans moteur réel,
sans accès à nasdaq_3m.csv), retourne des VALEURS (ValidationRun, HoldoutAccessEvent), ne persiste
rien elle-même — la persistance reste la responsabilité de l'appelant (script d'exécution réelle).

Invariant central testé ici : le Final Holdout n'est JAMAIS consulté avant l'étape finale, et
l'accès (HoldoutAccessEvent) n'est créé qu'APRÈS l'exécution réelle du backtest sur cette période
— jamais avant, toujours même si le backtest produit zéro trade.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_split import build_dataset_split_plan, build_split_boundary
from validation_oos import run_oos_validation

_SNAPSHOT_ID = "local_csv:sha256:" + "ab" * 32


def _split_plan():
    return build_dataset_split_plan(
        split_plan_id="plan_x",
        dataset_snapshot_id=_SNAPSHOT_ID,
        train=build_split_boundary("2017-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
        final_holdout=build_split_boundary("2025-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )


class _RecordingFakeEngine:
    """Fake engine.run_backtest() — enregistre les arguments reçus (preuve que seule la période
    FINAL_HOLDOUT est évaluée) et retourne des stats synthétiques fixées à l'avance."""

    def __init__(self, stats: dict):
        self._stats = stats
        self.calls = []

    def __call__(self, df, strategy, params, **kwargs):
        self.calls.append({"df": df, "strategy": strategy, "params": params, **kwargs})
        trades_df = pd.DataFrame() if self._stats.get("n_trades", 0) == 0 else pd.DataFrame(
            [{"resultat_net": 1.0}]
        )
        equity_df = pd.DataFrame([{"capital": 10_000.0, "drawdown": 0.0}])
        return trades_df, equity_df, self._stats


_SYNTHETIC_DF = pd.DataFrame({"time_paris": pd.to_datetime(["2020-01-01"])})
_SYNTHETIC_STRATEGY = object()
_SYNTHETIC_PARAMS = {"stop_pct": 1.2}


def _run_validation(fake_stats, **kwargs):
    fake_engine = _RecordingFakeEngine(fake_stats)
    kwargs.setdefault("df", _SYNTHETIC_DF)
    kwargs.setdefault("strategy", _SYNTHETIC_STRATEGY)
    kwargs.setdefault("params", _SYNTHETIC_PARAMS)
    kwargs.setdefault("split_plan", _split_plan())
    kwargs.setdefault("research_run_id", "run_x")
    kwargs.setdefault("validation_run_id", "val_x")
    kwargs.setdefault("strategy_name", "NASDAQ Perfect Revolution V1.1")
    kwargs.setdefault("reason", "AF-V-01 final OOS evaluation")
    kwargs.setdefault("run_backtest_fn", fake_engine)
    result = run_oos_validation(**kwargs)
    return result, fake_engine


# ═══════════════════════════════════════════════════════════════════════════════
# E. Final Holdout absent des phases pré-verdict — preuve par les arguments d'appel
# ═══════════════════════════════════════════════════════════════════════════════


def test_run_oos_validation_evaluates_exactly_the_final_holdout_period():
    """E. Le run_backtest_fn injecté ne doit être appelé qu'avec les bornes FINAL_HOLDOUT du plan
    — jamais la période complète, jamais TRAIN."""
    split_plan = _split_plan()
    (validation_run, event), fake_engine = _run_validation(
        {"n_trades": 3, "net_ret_pct": 2.0, "profit_factor": 1.5, "win_rate": 66.7, "max_dd_pct": 1.0},
        split_plan=split_plan,
    )

    assert len(fake_engine.calls) == 1
    call = fake_engine.calls[0]
    assert call["start_date"] == split_plan.final_holdout.start
    assert call["end_date"] == split_plan.final_holdout.end


# ═══════════════════════════════════════════════════════════════════════════════
# F, G. Exactement un HoldoutAccessEvent créé, jamais avant l'accès
# ═══════════════════════════════════════════════════════════════════════════════


def test_run_oos_validation_creates_exactly_one_holdout_access_event():
    """F. L'accès final crée exactement un HoldoutAccessEvent."""
    (validation_run, event), fake_engine = _run_validation(
        {"n_trades": 3, "net_ret_pct": 2.0, "profit_factor": 1.5, "win_rate": 66.7, "max_dd_pct": 1.0},
    )

    assert event is not None
    assert event.split_plan_id == "plan_x"
    assert event.research_run_id == "run_x"
    assert event.validation_run_id == "val_x"


def test_run_oos_validation_creates_the_event_only_after_the_backtest_ran():
    """G. Aucun événement avant l'accès réel — l'ordre d'appel prouve que le backtest s'est
    exécuté avant que l'événement existe (le fake enregistre l'appel ; l'événement référence le
    même research_run_id/split_plan_id, construit seulement après le retour du fake)."""
    fake_engine = _RecordingFakeEngine(
        {"n_trades": 3, "net_ret_pct": 2.0, "profit_factor": 1.5, "win_rate": 66.7, "max_dd_pct": 1.0}
    )
    assert len(fake_engine.calls) == 0  # aucun accès avant l'appel

    validation_run, event = run_oos_validation(
        df=_SYNTHETIC_DF, strategy=_SYNTHETIC_STRATEGY, params=_SYNTHETIC_PARAMS,
        split_plan=_split_plan(), research_run_id="run_x", validation_run_id="val_x",
        strategy_name="NASDAQ Perfect Revolution V1.1", reason="AF-V-01 final OOS evaluation",
        run_backtest_fn=fake_engine,
    )

    assert len(fake_engine.calls) == 1  # exactement un accès, après quoi l'event existe
    assert event.accessed_at  # l'event est bien construit, après l'exécution


def test_run_oos_validation_creates_an_event_even_on_zero_trades():
    """G (précision mission §10) : le backtest a réellement lu/évalué le holdout même s'il produit
    zéro trade — l'accès a eu lieu, l'événement doit exister."""
    (validation_run, event), fake_engine = _run_validation({"n_trades": 0})

    assert event is not None
    assert validation_run.evidence.n_trades == 0


def test_run_oos_validation_reason_is_a_stable_explicit_formulation():
    """Mission §10 : le reason doit être une formulation stable et explicite."""
    (validation_run, event), fake_engine = _run_validation(
        {"n_trades": 3, "net_ret_pct": 2.0, "profit_factor": 1.5, "win_rate": 66.7, "max_dd_pct": 1.0},
        reason="AF-V-01 final OOS evaluation",
    )

    assert event.reason == "AF-V-01 final OOS evaluation"


# ═══════════════════════════════════════════════════════════════════════════════
# B, C, D. Liens non ambigus, cohérence dataset_snapshot_id
# ═══════════════════════════════════════════════════════════════════════════════


def test_run_oos_validation_links_are_all_consistent():
    """B, C, D. ValidationRun ET HoldoutAccessEvent référencent exactement le même research_run_id/
    split_plan_id/dataset_snapshot_id — jamais divergents."""
    split_plan = _split_plan()
    (validation_run, event), fake_engine = _run_validation(
        {"n_trades": 3, "net_ret_pct": 2.0, "profit_factor": 1.5, "win_rate": 66.7, "max_dd_pct": 1.0},
        split_plan=split_plan, research_run_id="run_x", validation_run_id="val_x",
    )

    assert validation_run.research_run_id == event.research_run_id == "run_x"
    assert validation_run.split_plan_id == event.split_plan_id == "plan_x"
    assert validation_run.dataset_snapshot_id == event.dataset_snapshot_id == split_plan.dataset_snapshot_id


# ═══════════════════════════════════════════════════════════════════════════════
# J. Evidence contient réellement la période OOS évaluée
# ═══════════════════════════════════════════════════════════════════════════════


def test_run_oos_validation_evidence_period_matches_the_final_holdout_boundaries():
    """J. La période portée par l'evidence correspond exactement au FINAL_HOLDOUT du plan."""
    split_plan = _split_plan()
    (validation_run, event), fake_engine = _run_validation(
        {"n_trades": 3, "net_ret_pct": 2.0, "profit_factor": 1.5, "win_rate": 66.7, "max_dd_pct": 1.0},
        split_plan=split_plan,
    )

    assert validation_run.evidence.period_start == split_plan.final_holdout.start
    assert validation_run.evidence.period_end == split_plan.final_holdout.end


def test_run_oos_validation_evidence_reflects_the_engine_stats_honestly():
    """Aucune transformation/arrondi/invention — les métriques de l'evidence viennent
    directement du stats_dict retourné par le moteur (via le fake ici)."""
    (validation_run, event), fake_engine = _run_validation(
        {"n_trades": 7, "net_ret_pct": 12.5, "profit_factor": 2.3, "win_rate": 71.4, "max_dd_pct": 3.2},
    )

    assert validation_run.evidence.n_trades == 7
    assert validation_run.evidence.net_ret_pct == 12.5
    assert validation_run.evidence.profit_factor == 2.3
    assert validation_run.evidence.win_rate == 71.4
    assert validation_run.evidence.max_dd_pct == 3.2


def test_run_oos_validation_never_calls_run_backtest_fn_more_than_once():
    """Discipline de coût (mission §14) : un seul backtest OOS ciblé, jamais un sweep."""
    (validation_run, event), fake_engine = _run_validation(
        {"n_trades": 3, "net_ret_pct": 2.0, "profit_factor": 1.5, "win_rate": 66.7, "max_dd_pct": 1.0},
    )

    assert len(fake_engine.calls) == 1


def test_run_oos_validation_uses_the_strategy_params_exactly_as_given():
    """Mission §13 : aucun tuning après observation — les params passés au moteur doivent être
    EXACTEMENT ceux fixés par l'appelant, jamais modifiés par l'orchestration elle-même."""
    fixed_params = {"stop_pct": 1.2, "target_pct": 6.75}
    (validation_run, event), fake_engine = _run_validation(
        {"n_trades": 3, "net_ret_pct": 2.0, "profit_factor": 1.5, "win_rate": 66.7, "max_dd_pct": 1.0},
        params=fixed_params,
    )

    assert fake_engine.calls[0]["params"] == fixed_params
    assert validation_run.strategy_params == fixed_params


def test_validation_oos_module_does_not_import_engine_directly():
    """`/codebase-design` : run_backtest_fn est injecté, jamais un import direct de engine.py —
    seul le SCRIPT d'exécution réelle (hors ce module) importe engine.py."""
    import validation_oos as module

    import_lines = "\n".join(
        line for line in open(module.__file__, encoding="utf-8")
        if line.strip().startswith(("import ", "from "))
    ).lower()

    assert "import engine" not in import_lines
    assert "from engine" not in import_lines
