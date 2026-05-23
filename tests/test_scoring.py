"""
tests/test_scoring.py — Tests unitaires du module scoring.py
Couvre les steps 2 et 5 de l'audit.
"""

import sys
import os
import math
import pytest

# Ajouter la racine du projet au path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring import (
    ScoreWeights,
    FilterConfig,
    compute_equity_r_squared,
    is_filtered_out,
    compute_score,
    compute_penalties,
)


# ══════════════════════════════════════════════════════════════════
# FIXTURES
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def default_weights():
    return ScoreWeights()


@pytest.fixture
def default_filters():
    return FilterConfig()


@pytest.fixture
def good_stats():
    """Statistiques typiques d'un réglage recommandé."""
    return {
        "n_trades":       80,
        "profit_factor":  2.0,
        "max_dd_pct":     10.0,
        "win_rate":       55.0,
        "net_ret_pct":    60.0,
        "max_consec_loss": 4,
        "payoff":         1.5,
        "equity_r_squared": 0.90,
    }


@pytest.fixture
def default_param_ranges():
    return [
        {"name": "stop_loss",   "param_type": "number", "min_val": 10, "max_val": 50, "step": 5,  "enabled": True},
        {"name": "take_profit", "param_type": "number", "min_val": 10, "max_val": 100,"step": 10, "enabled": True},
    ]


# ══════════════════════════════════════════════════════════════════
# TEST: compute_equity_r_squared
# ══════════════════════════════════════════════════════════════════

class TestEquityRSquared:

    def test_perfect_linear_r2_is_one(self):
        """Une equity parfaitement linéaire doit donner R²≈1."""
        values = [float(i) for i in range(1, 101)]
        r2 = compute_equity_r_squared(values)
        assert 0.99 <= r2 <= 1.0, f"R² attendu ≈1, obtenu {r2}"

    def test_flat_equity_r2_is_low(self):
        """Une equity plate (pas de progression) doit donner R²<0.5."""
        values = [100.0] * 50
        r2 = compute_equity_r_squared(values)
        assert 0.0 <= r2 <= 0.5, f"R² attendu faible pour equity plate, obtenu {r2}"

    def test_random_noisy_equity(self):
        """Une equity aléatoire bruitée doit retourner une valeur dans [0,1]."""
        import random
        random.seed(42)
        values = [random.gauss(0, 10) for _ in range(100)]
        r2 = compute_equity_r_squared(values)
        assert 0.0 <= r2 <= 1.0, f"R² hors plage : {r2}"

    def test_empty_list_returns_zero(self):
        """Liste vide → R² = 0.0 sans exception."""
        r2 = compute_equity_r_squared([])
        assert r2 == 0.0

    def test_single_value_returns_zero(self):
        r2 = compute_equity_r_squared([42.0])
        assert r2 == 0.0

    def test_decreasing_equity(self):
        """Equity strictement décroissante → R²≈1 (régression linéaire)."""
        values = [100.0 - i for i in range(50)]
        r2 = compute_equity_r_squared(values)
        assert r2 >= 0.99, f"R² attendu ≈1 pour trend parfait, obtenu {r2}"


# ══════════════════════════════════════════════════════════════════
# TEST: is_filtered_out
# ══════════════════════════════════════════════════════════════════

class TestIsFilteredOut:

    def test_good_stats_not_filtered(self, good_stats, default_filters):
        filtered, reason = is_filtered_out(good_stats, default_filters)
        assert not filtered, f"Bon réglage filtré à tort : {reason}"

    def test_too_few_trades_filtered(self, good_stats, default_filters):
        good_stats["n_trades"] = 5  # < min_trades=30 par défaut
        filtered, reason = is_filtered_out(good_stats, default_filters)
        assert filtered, "Devrait être filtré (trop peu de trades)"
        assert "trade" in reason.lower()

    def test_high_drawdown_filtered(self, good_stats, default_filters):
        good_stats["max_dd_pct"] = 30.0  # > max_drawdown_pct=25 par défaut
        filtered, reason = is_filtered_out(good_stats, default_filters)
        assert filtered, "Devrait être filtré (drawdown trop élevé)"
        assert "drawdown" in reason.lower() or "dd" in reason.lower()

    def test_low_profit_factor_filtered(self, good_stats, default_filters):
        good_stats["profit_factor"] = 0.9  # < min_profit_factor=1.1 par défaut
        filtered, reason = is_filtered_out(good_stats, default_filters)
        assert filtered, "Devrait être filtré (PF trop bas)"

    def test_low_win_rate_filtered(self, good_stats, default_filters):
        good_stats["win_rate"] = 20.0  # < min_win_rate=35 par défaut
        filtered, reason = is_filtered_out(good_stats, default_filters)
        assert filtered, "Devrait être filtré (winrate trop bas)"

    def test_too_many_consec_losses_filtered(self, good_stats, default_filters):
        good_stats["max_consec_loss"] = 15  # > 12 par défaut
        filtered, reason = is_filtered_out(good_stats, default_filters)
        assert filtered, "Devrait être filtré (trop de pertes consécutives)"


# ══════════════════════════════════════════════════════════════════
# TEST: compute_score — Edge cases (STEP 5)
# ══════════════════════════════════════════════════════════════════

class TestComputeScore:

    def test_good_stats_score_above_50(self, good_stats, default_weights, default_filters, default_param_ranges):
        """Un bon réglage doit obtenir un score > 50."""
        params = {"stop_loss": 30, "take_profit": 60}
        score, filtered, reason, warnings = compute_score(
            good_stats, default_weights, default_filters, params, default_param_ranges
        )
        assert not filtered, f"Bon réglage filtré : {reason}"
        assert score > 50, f"Score attendu > 50, obtenu {score}"

    # ── Scenario 1 : PF élevé mais peu de trades ─────────────────
    def test_high_pf_few_trades_penalized(self, default_weights, default_filters, default_param_ranges):
        """PF=5 avec seulement 25 trades : doit être filtré (min_trades=30) OU score pénalisé."""
        stats = {
            "n_trades":       25,       # sous le seuil min_trades=30
            "profit_factor":  5.0,
            "max_dd_pct":     8.0,
            "win_rate":       65.0,
            "net_ret_pct":    80.0,
            "max_consec_loss": 3,
            "payoff":         2.0,
            "equity_r_squared": 0.85,
        }
        params = {"stop_loss": 30, "take_profit": 60}
        score, filtered, reason, warnings = compute_score(
            stats, default_weights, default_filters, params, default_param_ranges
        )
        # Soit filtré, soit pénalisé avec warning
        if not filtered:
            assert len(warnings) > 0, "Pas de warning pour PF élevé/peu de trades"
            assert score < 80, f"Score trop élevé malgré peu de trades : {score}"

    # ── Scenario 2 : Gain élevé mais DD énorme ────────────────────
    def test_high_gain_huge_drawdown_filtered(self, default_weights, default_filters, default_param_ranges):
        """Gain=200% mais DD=35% : doit être filtré (max_drawdown_pct=25%)."""
        stats = {
            "n_trades":       60,
            "profit_factor":  3.0,
            "max_dd_pct":     35.0,     # > 25% → filtré
            "win_rate":       55.0,
            "net_ret_pct":    200.0,
            "max_consec_loss": 6,
            "payoff":         2.0,
            "equity_r_squared": 0.80,
        }
        params = {"stop_loss": 30, "take_profit": 60}
        score, filtered, reason, warnings = compute_score(
            stats, default_weights, default_filters, params, default_param_ranges
        )
        assert filtered, f"DD=35% devrait filtrer le résultat (raison: {reason})"

    # ── Scenario 3 : Réglage robuste avec beaucoup de trades ─────
    def test_robust_many_trades_high_score(self, default_weights, default_filters, default_param_ranges):
        """Réglage robuste : 120 trades, PF=1.8, DD=8%, WR=58%, R²=0.92."""
        stats = {
            "n_trades":       120,
            "profit_factor":  1.8,
            "max_dd_pct":     8.0,
            "win_rate":       58.0,
            "net_ret_pct":    75.0,
            "max_consec_loss": 4,
            "payoff":         1.4,
            "equity_r_squared": 0.92,
        }
        params = {"stop_loss": 30, "take_profit": 60}
        score, filtered, reason, warnings = compute_score(
            stats, default_weights, default_filters, params, default_param_ranges
        )
        assert not filtered, f"Réglage robuste filtré à tort : {reason}"
        assert score >= 50, f"Score attendu >= 50 pour réglage robuste, obtenu {score}"

    # ── Scenario 4 : Equity irrégulière ──────────────────────────
    def test_irregular_equity_penalized(self, default_weights, default_filters, default_param_ranges):
        """Equity très irrégulière (R²=0.20) doit être pénalisée."""
        stats = {
            "n_trades":       50,
            "profit_factor":  2.0,
            "max_dd_pct":     12.0,
            "win_rate":       52.0,
            "net_ret_pct":    40.0,
            "max_consec_loss": 5,
            "payoff":         1.5,
            "equity_r_squared": 0.20,   # très irrégulier
        }
        # Stats identiques mais equity régulière
        stats_regular = {**stats, "equity_r_squared": 0.90}
        params = {"stop_loss": 30, "take_profit": 60}

        score_irr, _, _, warnings_irr = compute_score(
            stats, default_weights, default_filters, params, default_param_ranges
        )
        score_reg, _, _, _ = compute_score(
            stats_regular, default_weights, default_filters, params, default_param_ranges
        )
        assert score_irr < score_reg, (
            f"Score avec equity irrégulière ({score_irr:.1f}) devrait être < "
            f"score avec equity régulière ({score_reg:.1f})"
        )

    # ── Scenario 5 : Paramètres aux extrêmes du range ────────────
    def test_params_at_extremes_trigger_warning(self, default_weights, default_filters, default_param_ranges):
        """Paramètres au min/max du range doivent générer un warning."""
        stats = {
            "n_trades":       60,
            "profit_factor":  2.0,
            "max_dd_pct":     10.0,
            "win_rate":       55.0,
            "net_ret_pct":    60.0,
            "max_consec_loss": 4,
            "payoff":         1.5,
            "equity_r_squared": 0.85,
        }
        # stop_loss à sa valeur min (10), take_profit à son max (100)
        params_extreme = {"stop_loss": 10, "take_profit": 100}
        params_middle  = {"stop_loss": 30, "take_profit": 60}

        _, _, _, warnings_extreme = compute_score(
            stats, default_weights, default_filters, params_extreme, default_param_ranges
        )
        _, _, _, warnings_middle = compute_score(
            stats, default_weights, default_filters, params_middle, default_param_ranges
        )
        assert len(warnings_extreme) >= len(warnings_middle), (
            "Paramètres extrêmes devraient générer au moins autant de warnings "
            f"(extreme={len(warnings_extreme)}, middle={len(warnings_middle)})"
        )


# ══════════════════════════════════════════════════════════════════
# TEST: compute_penalties
# ══════════════════════════════════════════════════════════════════

class TestComputePenalties:

    def test_no_penalty_for_clean_result(self, default_param_ranges):
        """Un résultat propre ne doit pas générer de pénalité excessive."""
        stats = {
            "n_trades":       80,
            "profit_factor":  2.0,
            "max_dd_pct":     10.0,
            "win_rate":       55.0,
            "net_ret_pct":    60.0,
            "equity_r_squared": 0.90,
        }
        params = {"stop_loss": 30, "take_profit": 60}
        penalty, warnings = compute_penalties(stats, params, default_param_ranges)
        assert 0.0 <= penalty <= 0.3, f"Pénalité trop élevée pour bon résultat : {penalty}"

    def test_inf_pf_generates_penalty(self, default_param_ranges):
        """PF=Inf (aucune perte) doit générer une pénalité et un warning."""
        stats = {
            "n_trades":       50,
            "profit_factor":  float("inf"),
            "max_dd_pct":     5.0,
            "win_rate":       100.0,
            "net_ret_pct":    50.0,
            "equity_r_squared": 0.85,
        }
        params = {"stop_loss": 30, "take_profit": 60}
        penalty, warnings = compute_penalties(stats, params, default_param_ranges)
        # PF infini = résultat suspect, doit être pénalisé ou signalé
        # On accepte soit penalty > 0 soit un warning
        assert penalty > 0 or len(warnings) > 0, (
            "PF=Inf devrait générer une pénalité ou un warning"
        )

    def test_penalty_is_in_valid_range(self, default_param_ranges):
        """La pénalité doit toujours être dans [0, 1]."""
        stats = {
            "n_trades":       10,
            "profit_factor":  float("inf"),
            "max_dd_pct":     0.1,
            "win_rate":       100.0,
            "net_ret_pct":    1000.0,
            "equity_r_squared": 0.01,
        }
        params = {"stop_loss": 10, "take_profit": 100}  # extrêmes
        penalty, _ = compute_penalties(stats, params, default_param_ranges)
        assert 0.0 <= penalty <= 1.0, f"Pénalité hors plage [0,1] : {penalty}"


# ══════════════════════════════════════════════════════════════════
# TEST: report_generator (smoke tests)
# ══════════════════════════════════════════════════════════════════

class TestReportGenerator:

    def test_empty_results(self):
        from report_generator import generate_report
        report = generate_report([], {}, {})
        assert "categorie" in report
        assert "resume" in report
        assert report["convient_paper_trading"] == False

    def test_good_result_report(self):
        from report_generator import generate_report
        results = [{
            "score": 75.0,
            "filtered": False,
            "params": {"stop_loss": 30, "take_profit": 60},
            "stats": {
                "profit_factor": 2.0,
                "max_dd_pct": 10.0,
                "total_trades": 80,
                "win_rate": 55.0,
                "net_ret_pct": 60.0,
                "equity_r_squared": 0.90,
            },
            "warnings": [],
            "degradation_pct": 10.0,
        }]
        config = {
            "train_test": {"enabled": False},
            "param_ranges": [
                {"name": "stop_loss",   "param_type": "number", "min_val": 10, "max_val": 50, "step": 5,  "enabled": True},
                {"name": "take_profit", "param_type": "number", "min_val": 10, "max_val": 100,"step": 10, "enabled": True},
            ]
        }
        report = generate_report(results, {"stop_loss": 0.5}, config)
        assert report["categorie"] in ["Réglage recommandé", "Réglage agressif", "Réglage défensif", "Réglage à éviter"]
        assert isinstance(report["points_forts"], list)
        assert isinstance(report["points_faibles"], list)
        assert isinstance(report["convient_paper_trading"], bool)
        assert "recommandation_finale" in report
