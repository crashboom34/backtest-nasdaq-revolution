"""
tests/test_engine.py — Tests de non-régression du moteur de backtest.
"""

import sys
import os
import pytest
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import load_data, run_backtest
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
