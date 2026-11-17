"""Helpers de tests partagés — ADR 0029 (Scoring Integrity, U-2 strict).

Les faux `engine.run_backtest()` historiques rendaient des `stats` PARTIELS (souvent
`{"n_trades": 1, "net_ret_pct": x}` avec des DataFrames vides). Sur un chemin scientifique, la
frontière moteur → optimizer exige désormais les 14 métriques et des artefacts cohérents. Ce
helper complète un faux avec EXACTEMENT les valeurs implicites que `compute_score` lisait pour une
clé absente (profit_factor → 0.0 avec gross_win 0 / gross_loss > 0, win_rate 0.0 avec n_win 0,
payoff 1.0, max_dd_pct 0.0, max_dd_usd 1.0, equity_r_squared 0.5, max_consec_loss 0,
net_ret_usd 0.0) : le score d'un faux adapté reste identique au score historique tant que
`net_ret_pct / 1.0 <= 25` (seule divergence connue : la pénalité gain/DD lit `max_dd_pct` absent
comme 1.0, voir contrat §8 U-2).
"""
import pandas as pd


def legacy_equivalent_stats(n_trades: int = 1, net_ret_pct: float = 0.0, **overrides) -> dict:
    stats = {
        "n_trades": n_trades, "n_win": 0, "n_loss": n_trades, "win_rate": 0.0,
        "gross_win": 0.0, "gross_loss": float(n_trades), "profit_factor": 0.0, "payoff": 1.0,
        "max_dd_pct": 0.0, "max_dd_usd": 1.0, "max_consec_loss": 0,
        "net_ret_pct": net_ret_pct, "net_ret_usd": 0.0, "equity_r_squared": 0.5,
    }
    stats.update(overrides)
    return stats


def legacy_equivalent_artifacts(n_trades: int = 1, net_ret_pct: float = 0.0, start=None, **overrides):
    """(trades, equity, stats) cohérents au sens de la frontière C13 (len(trades) == n_trades,
    PnL et capital finis), stats = `legacy_equivalent_stats`."""
    t0 = pd.Timestamp(start) if start is not None else pd.Timestamp("2024-01-02 10:00", tz="UTC")
    entries = [t0 + pd.Timedelta(minutes=30 * i) for i in range(n_trades)]
    trades = pd.DataFrame({
        "resultat_net": [-1.0] * n_trades,
        "date_entree": entries,
        "date_sortie": [e + pd.Timedelta(minutes=3) for e in entries],
        "raison_sortie": ["target"] * n_trades,
    })
    equity = pd.DataFrame({
        "date": [t0 + pd.Timedelta(minutes=3 * i) for i in range(n_trades + 1)],
        "capital": [10_000.0 - i for i in range(n_trades + 1)],
    })
    return trades, equity, legacy_equivalent_stats(n_trades, net_ret_pct, **overrides)
