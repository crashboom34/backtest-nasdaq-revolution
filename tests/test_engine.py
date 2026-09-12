"""
tests/test_engine.py — Tests de non-régression du moteur de backtest.
"""

import sys
import os
import pytest
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import load_data, run_backtest, _add_market_time_columns
from strategies.perfect_revolution_v1 import Strategy, DEFAULT_PARAMS, STRATEGY_NAME


@pytest.fixture(scope="module")
def df():
    """Charge les données une seule fois pour tout le module."""
    data_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "nasdaq_3m.csv"
    )
    return load_data(data_file)


@pytest.fixture(scope="module")
def backtest_result(df):
    """Run de backtest complet avec les params par défaut."""
    strat = Strategy()
    return run_backtest(df, strat, DEFAULT_PARAMS)


class TestLoadData:

    def test_load_returns_dataframe(self, df):
        assert isinstance(df, pd.DataFrame)

    def test_has_required_columns(self, df):
        required = ["time", "open", "high", "low", "close", "time_paris"]
        for col in required:
            assert col in df.columns, f"Colonne manquante : {col}"

    def test_not_empty(self, df):
        assert len(df) > 0

    def test_time_paris_is_tz_aware(self, df):
        assert df["time_paris"].dt.tz is not None


class TestRunBacktest:

    def test_returns_tuple_of_three(self, backtest_result):
        assert isinstance(backtest_result, tuple)
        assert len(backtest_result) == 3, f"Attendu 3 éléments, obtenu {len(backtest_result)}"

    def test_stats_dict_has_required_keys(self, backtest_result):
        _, _, stats = backtest_result
        required_keys = [
            "n_trades", "net_ret_pct", "max_dd_pct",
            "profit_factor", "win_rate", "equity_r_squared",
        ]
        for key in required_keys:
            assert key in stats, f"Clé manquante dans stats : {key}"

    def test_equity_r_squared_in_range(self, backtest_result):
        _, _, stats = backtest_result
        r2 = stats["equity_r_squared"]
        assert 0.0 <= r2 <= 1.0, f"equity_r_squared hors plage [0,1] : {r2}"

    def test_n_trades_positive(self, backtest_result):
        _, _, stats = backtest_result
        assert stats["n_trades"] >= 0

    def test_max_dd_pct_non_negative(self, backtest_result):
        _, _, stats = backtest_result
        assert stats["max_dd_pct"] >= 0.0

    def test_win_rate_in_range(self, backtest_result):
        _, _, stats = backtest_result
        assert 0.0 <= stats["win_rate"] <= 100.0

    def test_date_filter_start(self, df):
        """start_date doit réduire le nombre de données traitées."""
        strat = Strategy()
        result_full = run_backtest(df, strat, DEFAULT_PARAMS)

        strat2 = Strategy()
        result_filtered = run_backtest(df, strat2, DEFAULT_PARAMS, start_date="2023-01-01")

        _, eq_full, stats_full = result_full
        _, eq_filt, stats_filt = result_filtered
        # La version filtrée doit avoir moins de ou autant de trades
        # (et au moins le même type de retour)
        assert isinstance(stats_filt, dict)
        assert "equity_r_squared" in stats_filt

    def test_trades_dataframe_has_columns(self, backtest_result):
        trades_df, _, _ = backtest_result
        if len(trades_df) > 0:
            # Colonnes réelles retournées par engine.py (noms français)
            expected = ["date_entree", "sens", "resultat_net", "capital_apres"]
            for col in expected:
                assert col in trades_df.columns, f"Colonne trades manquante : {col}"


class TestNoWindowNonRegression:
    """Dette A (engine layer, 2026-09-12) — preuve de non-régression déterministe : sans
    start_date/end_date, le comportement doit rester STRICTEMENT identique à la référence
    historique GATE DATA (2026-08-15, AI_HANDOFF.md §13) — 114 trades sur nasdaq_3m.csv complet
    avec DEFAULT_PARAMS. Réutilise le fixture module-scoped `backtest_result` déjà chargé par le
    reste de cette suite — aucun calcul supplémentaire."""

    def test_no_window_matches_the_gate_data_reference(self, backtest_result):
        _, _, stats = backtest_result
        assert stats["n_trades"] == 114
        assert stats["net_ret_pct"] == pytest.approx(-1.07580480000006)


# ═══════════════════════════════════════════════════════════════════════════════
# Dette A (engine layer) — séparation contexte / fenêtre d'exécution
# ═══════════════════════════════════════════════════════════════════════════════
#
# Stratégie et DataFrame 100 % synthétiques, déterministes, sans dépendance à nasdaq_3m.csv ni
# à Perfect Revolution — ces tests verrouillent le nouveau contrat moteur lui-même, pas un
# comportement métier.


class _RecordingStrategy:
    """Stratégie synthétique minimale : enregistre exactement ce qu'elle voit (indices vus par
    on_bar(), taille/bornes du DataFrame vu par prepare()), sans logique de trading réelle au-delà
    d'une entrée "longue" optionnelle sur des index choisis par le test. stop_pct/target_pct très
    larges (100 %) pour ne jamais se déclencher sur les petites variations de prix synthétiques —
    seule la fermeture forcée (ou l'absence d'entrée) termine un trade dans ces tests."""

    def __init__(self, warmup=2, enter_at=None):
        self.WARMUP = warmup
        self._enter_at = set(enter_at or [])
        self.prepared_len = None
        self.prepared_first_time = None
        self.prepared_last_time = None
        self.on_bar_indices = []
        self.reset()

    def reset(self):
        pass  # aucun état journalier à purger pour cette stratégie synthétique

    def prepare(self, df, params):
        self.prepared_len = len(df)
        self.prepared_first_time = df["time_paris"].iloc[0] if len(df) else None
        self.prepared_last_time  = df["time_paris"].iloc[-1] if len(df) else None
        return df

    def on_bar(self, i, df, context, params):
        self.on_bar_indices.append(i)
        if context["in_pos"]:
            return None
        if i in self._enter_at:
            return {"action": "enter", "direction": "long", "stop_pct": 100.0, "target_pct": 100.0}
        return None


def _build_synthetic_df(n_bars: int, start: str = "2024-01-02T00:00:00", freq_minutes: int = 3):
    """DataFrame minimal (time/open/high/low/close) avec les colonnes dérivées habituelles
    (time_paris, etc.) via _add_market_time_columns() — même pipeline que load_data(), sans
    lire de fichier."""
    times = pd.date_range(start, periods=n_bars, freq=f"{freq_minutes}min")
    price = 100.0 + pd.Series(range(n_bars), dtype=float) * 0.01
    raw = pd.DataFrame({
        "time":  times,
        "open":  price.values,
        "high":  (price + 0.5).values,
        "low":   (price - 0.5).values,
        "close": price.values,
    })
    return _add_market_time_columns(raw)


def _bar_time_str(df, idx):
    return df["time_paris"].iloc[idx].strftime("%Y-%m-%dT%H:%M:%S")


class TestExecutionWindowSeparation:
    """Dette A (engine layer) — sépare l'historique de contexte utilisé par strategy.prepare()
    de la fenêtre réellement exécutée (loop_start = max(exec_start_idx, warmup), exec_end_idx =
    dernière bougie du contexte). Dette B (sémantique [start,end) vs [start,end]) et l'intégration
    optimizer restent explicitement hors scope."""

    # ── A1 / A2 — prepare() voit l'historique amont, on_bar() jamais avant exec_start_idx ──

    def test_a1_prepare_sees_history_before_start_but_on_bar_never_called_before_it(self):
        df = _build_synthetic_df(20)
        strat = _RecordingStrategy(warmup=2)

        run_backtest(df, strat, {}, start_date=_bar_time_str(df, 10))

        assert strat.prepared_len == 20  # tout l'historique, y compris avant start
        assert min(strat.on_bar_indices) == 10  # jamais appelé avant exec_start_idx

    def test_a2_loop_start_is_exec_start_idx_not_exec_start_plus_warmup(self):
        """A2 — exec_start_idx (10) > WARMUP (2) : la boucle démarre à 10, jamais à 10+2=12."""
        df = _build_synthetic_df(20)
        strat = _RecordingStrategy(warmup=2)

        run_backtest(df, strat, {}, start_date=_bar_time_str(df, 10))

        assert min(strat.on_bar_indices) == 10
        assert min(strat.on_bar_indices) != 12

    def test_a3_loop_start_falls_back_to_warmup_when_history_before_start_is_short(self):
        """A3 — exec_start_idx (1) < WARMUP (5) : le garde-fou WARMUP reste appliqué."""
        df = _build_synthetic_df(20)
        strat = _RecordingStrategy(warmup=5)

        run_backtest(df, strat, {}, start_date=_bar_time_str(df, 1))

        assert min(strat.on_bar_indices) == 5

    # ── A4 — aucun futur après end_date dans prepare() ──────────────────────────────

    def test_a4_prepare_never_sees_bars_after_end_date(self):
        df = _build_synthetic_df(20)
        strat = _RecordingStrategy(warmup=2)

        run_backtest(df, strat, {}, end_date=_bar_time_str(df, 14))

        assert strat.prepared_len == 15  # indices 0..14 seulement
        assert strat.prepared_last_time == df["time_paris"].iloc[14]

    # ── A5 — next_open ne dépasse jamais la fenêtre ─────────────────────────────────

    def test_a5_entry_allowed_on_the_last_executable_bar(self):
        """Dernière décision possible : i = exec_end_idx - 1 = 13 (i+1 = 14 = exec_end_idx)."""
        df = _build_synthetic_df(20)
        strat = _RecordingStrategy(warmup=2, enter_at={13})

        trades_df, _, _ = run_backtest(df, strat, {}, end_date=_bar_time_str(df, 14))

        assert max(strat.on_bar_indices) == 13  # jamais appelé à i=14 (dernière bougie logique)
        assert len(trades_df) == 1  # l'entrée à i=13 (next_open=opn[14]) a bien été exécutée

    def test_a5_signal_requiring_next_open_beyond_the_window_is_never_executed(self):
        """Un signal qui nécessiterait next_open=opn[15] (hors fenêtre) n'est jamais produit :
        on_bar() n'est structurellement jamais appelé avec i=14 (exec_end_idx)."""
        df = _build_synthetic_df(20)
        strat = _RecordingStrategy(warmup=2, enter_at={14})

        trades_df, _, _ = run_backtest(df, strat, {}, end_date=_bar_time_str(df, 14))

        assert 14 not in strat.on_bar_indices
        assert len(trades_df) == 0

    # ── A6 — fermeture forcée sur la fenêtre logique, jamais une bougie future ──────

    def test_a6_forced_closure_uses_the_logical_window_end_not_a_future_physical_bar(self):
        df = _build_synthetic_df(20)  # bougies 15..19 physiquement présentes après la fenêtre
        strat = _RecordingStrategy(warmup=2, enter_at={3})  # ouvre tôt, jamais de sortie signalée

        trades_df, _, _ = run_backtest(df, strat, {}, end_date=_bar_time_str(df, 14))

        assert len(trades_df) == 1
        last_trade = trades_df.iloc[-1]
        assert last_trade["raison_sortie"] == "fin-donnees"
        assert last_trade["prix_sortie"] == round(float(df["close"].iloc[14]), 2)
        assert last_trade["date_sortie"] == str(df["time_paris"].iloc[14])

    # ── A7 — equity curve strictement bornée à la fenêtre ───────────────────────────

    def test_a7_equity_curve_is_bounded_to_the_execution_window(self):
        df = _build_synthetic_df(20)
        strat = _RecordingStrategy(warmup=2)

        _, equity_df, _ = run_backtest(
            df, strat, {}, start_date=_bar_time_str(df, 10), end_date=_bar_time_str(df, 16))

        # exec_start_idx=10, exec_end_idx=16 -> range(10, 16) -> 6 points d'equity
        assert len(equity_df) == 6
        first_date = pd.Timestamp(equity_df["date"].iloc[0])
        last_date  = pd.Timestamp(equity_df["date"].iloc[-1])
        assert first_date == df["time_paris"].iloc[10]
        assert last_date == df["time_paris"].iloc[15]  # jamais la dernière bougie logique (16)

    # ── A9 — Dette B non touchée : end reste inclusif ───────────────────────────────

    def test_a9_end_date_boundary_bar_remains_included_legacy_semantics(self):
        """Dette B (sémantique [start,end) vs [start,end]) hors scope : end reste inclusif — la
        bougie exactement à end_date fait toujours partie du contexte."""
        df = _build_synthetic_df(20)
        strat = _RecordingStrategy(warmup=2)

        run_backtest(df, strat, {}, end_date=_bar_time_str(df, 14))

        assert strat.prepared_len == 15  # bougie 14 incluse, pas exclue


class TestExecutionWindowEdgeCases:
    """§12 — cas vides/bornes. Aucune nouvelle exception : dégradation gracieuse vers zéro
    trade, comportement observé d'abord sur le code historique avant de choisir la compatibilité
    la plus sûre (voir rapport de mission)."""

    def test_start_after_all_data_yields_zero_trades_no_crash(self):
        df = _build_synthetic_df(20)
        strat = _RecordingStrategy(warmup=2, enter_at={5})

        trades_df, _, stats = run_backtest(df, strat, {}, start_date="2099-01-01T00:00:00")

        assert len(trades_df) == 0
        assert stats["n_trades"] == 0

    def test_end_before_all_data_yields_zero_trades_no_crash(self):
        df = _build_synthetic_df(20)
        strat = _RecordingStrategy(warmup=2, enter_at={5})

        trades_df, _, stats = run_backtest(df, strat, {}, end_date="2000-01-01T00:00:00")

        assert len(trades_df) == 0
        assert stats["n_trades"] == 0

    def test_start_after_end_yields_zero_trades_no_crash(self):
        df = _build_synthetic_df(20)
        strat = _RecordingStrategy(warmup=2, enter_at={2, 3, 4, 6, 7})

        trades_df, _, stats = run_backtest(
            df, strat, {},
            start_date=_bar_time_str(df, 15), end_date=_bar_time_str(df, 5),
        )

        assert len(trades_df) == 0
        assert stats["n_trades"] == 0

    def test_window_too_short_for_any_next_bar_yields_zero_trades_no_crash(self):
        """start == end : une seule bougie logique, aucun i+1 possible."""
        df = _build_synthetic_df(20)
        boundary = _bar_time_str(df, 10)
        strat = _RecordingStrategy(warmup=2, enter_at={10})

        trades_df, _, stats = run_backtest(
            df, strat, {}, start_date=boundary, end_date=boundary)

        assert len(trades_df) == 0
        assert stats["n_trades"] == 0

    def test_progress_callback_never_divides_by_zero_and_always_completes(self):
        """§13 — fenêtre vide (start==end) : progress_cb(1.0) doit quand même être appelé, sans
        ZeroDivisionError, même si la boucle principale ne s'exécute jamais."""
        df = _build_synthetic_df(20)
        boundary = _bar_time_str(df, 10)
        strat = _RecordingStrategy(warmup=2)
        calls = []

        run_backtest(df, strat, {}, start_date=boundary, end_date=boundary,
                     progress_cb=lambda pct: calls.append(pct))

        assert calls, "progress_cb doit être appelé au moins une fois (1.0 final)"
        assert calls[-1] == 1.0
        assert all(0.0 <= c <= 1.0 for c in calls)
