"""
scoring.py — Module de scoring pour l'optimisateur.
Fonctions pures : pas d'I/O, pas de Streamlit, pas d'état global.
"""

import math
import numpy as np
from dataclasses import dataclass, field


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURES DE DONNÉES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScoreWeights:
    """Pondération des métriques dans le score global."""
    profit_factor:          float = 3.0   # Très important
    max_drawdown:           float = 3.0   # Très important
    total_trades:           float = 2.0   # Important (anti-PF artificiel)
    max_consecutive_losses: float = 2.0   # Important
    pct_gain:               float = 2.0   # Important
    win_rate:               float = 1.0   # Secondaire
    avg_win_loss_ratio:     float = 1.5   # Intermédiaire
    equity_regularity:      float = 1.5   # Intermédiaire (R² de l'equity curve)
    recovery_factor:        float = 1.0   # Secondaire


@dataclass
class FilterConfig:
    """Filtres éliminatoires appliqués AVANT le calcul du score."""
    min_trades:             int   = 30     # Nombre minimum de trades valides
    max_drawdown_pct:       float = 25.0   # Drawdown maximum toléré (%)
    min_profit_factor:      float = 1.1    # PF minimum
    max_consecutive_losses: int   = 12     # Pertes consécutives max
    min_win_rate:           float = 35.0   # Winrate minimum (%)


# ══════════════════════════════════════════════════════════════════════════════
# CALCUL R² DE L'EQUITY CURVE
# ══════════════════════════════════════════════════════════════════════════════

def compute_equity_r_squared(equity_values: list) -> float:
    """
    Mesure si l'equity curve ressemble à une droite montante.
    R²=1 : croissance parfaitement régulière
    R²=0 : aucune tendance linéaire détectable

    Fonction utilitaire utilisée par engine.py lors du calcul des stats.
    """
    if len(equity_values) <= 1:
        return 0.0  # Impossible de calculer une régression sur 0 ou 1 point
    if len(equity_values) < 10:
        return 0.5  # Insuffisant pour calculer, valeur neutre

    x = np.arange(len(equity_values), dtype=float)
    y = np.array(equity_values, dtype=float)

    x_m = x.mean()
    y_m = y.mean()

    ss_tot = ((y - y_m) ** 2).sum()
    if ss_tot == 0:
        return 0.5  # Ligne plate = pas de gain = neutre

    x_dev = x - x_m
    denom = (x_dev ** 2).sum()
    if denom == 0:
        return 0.5

    slope  = (x_dev * (y - y_m)).sum() / denom
    y_pred = slope * x + (y_m - slope * x_m)
    r_sq   = 1.0 - ((y - y_pred) ** 2).sum() / ss_tot

    return float(np.clip(r_sq, 0.0, 1.0))


# ══════════════════════════════════════════════════════════════════════════════
# FILTRES ÉLIMINATOIRES
# ══════════════════════════════════════════════════════════════════════════════

def is_filtered_out(stats: dict, filters: FilterConfig) -> tuple:
    """
    Vérifie si un résultat doit être éliminé avant le calcul du score.

    Retourne (est_éliminé: bool, raison: str)
    """
    n_trades = stats.get("n_trades", stats.get("total_trades", 0))
    dd       = stats.get("max_dd_pct", 0.0)
    pf       = stats.get("profit_factor", 0.0)
    # PF infini = pas de pertes, on le laisse passer les filtres (pénalisé ensuite)
    if math.isinf(pf):
        pf_check = False
    else:
        pf_check = pf < filters.min_profit_factor

    consec   = stats.get("max_consec_loss", stats.get("max_consecutive_losses", 0))
    wr       = stats.get("win_rate", 0.0)

    checks = [
        (n_trades < filters.min_trades,
         f"Trop peu de trades ({n_trades} < {filters.min_trades})"),
        (dd > filters.max_drawdown_pct,
         f"Drawdown trop élevé ({dd:.1f}% > {filters.max_drawdown_pct}%)"),
        (pf_check,
         f"Profit Factor insuffisant ({pf:.2f})"),
        (consec > filters.max_consecutive_losses,
         f"Pertes consécutives excessives ({consec})"),
        (wr < filters.min_win_rate,
         f"Winrate insuffisant ({wr:.1f}%)"),
    ]
    for condition, reason in checks:
        if condition:
            return True, reason
    return False, ""


# ══════════════════════════════════════════════════════════════════════════════
# NORMALISATION DES MÉTRIQUES
# ══════════════════════════════════════════════════════════════════════════════

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def normalize_profit_factor(pf: float) -> float:
    """
    PF=1→0, PF=2→0.50, PF=4+→1.
    Log car PF=3 n'est pas 3× meilleur que PF=2.
    PF=∞ → 0.95 (trop parfait = suspect).
    """
    if math.isinf(pf) or pf > 20.0:
        return 0.95
    if pf <= 1.0:
        return 0.0
    return _clamp(math.log(pf) / math.log(4.0))


def normalize_max_drawdown(dd_pct: float, max_dd_ref: float = 25.0) -> float:
    """0% DD→1, max_dd_ref DD→0. Inversé."""
    return _clamp(1.0 - (dd_pct / max_dd_ref))


def normalize_total_trades(n: int) -> float:
    """0→0, 30→0.64, 100→0.87, 150+→1. Log pénalise fortement les petits N."""
    if n <= 0:
        return 0.0
    return _clamp(math.log(max(1, n)) / math.log(150))


def normalize_consecutive_losses(n: int, max_ref: int = 12) -> float:
    """0→1, 6→0.5, 12+→0. Inversé."""
    return _clamp(1.0 - (n / max_ref))


def normalize_pct_gain(pct: float) -> float:
    """0%→0, 100%→0.5, 200%+→1."""
    return _clamp(pct / 200.0)


def normalize_win_rate(wr: float) -> float:
    """35%→0, 50%→0.5, 65%+→1."""
    return _clamp((wr - 35.0) / 30.0)


def normalize_avg_win_loss_ratio(ratio: float) -> float:
    """ratio=1→0.33, ratio=3+→1."""
    return _clamp(ratio / 3.0)


def normalize_equity_regularity(r_squared: float) -> float:
    """R²: 0→0, 0.5→0.5, 1→1. Linéaire direct."""
    return _clamp(r_squared)


def normalize_recovery_factor(rf: float) -> float:
    """RF=2.5→0.5, RF=5+→1."""
    if math.isinf(rf) or rf > 50.0:
        return 0.95
    return _clamp(rf / 5.0)


# ══════════════════════════════════════════════════════════════════════════════
# PÉNALITÉS ANTI-OVERFITTING
# ══════════════════════════════════════════════════════════════════════════════

def compute_penalties(stats: dict, params: dict, param_ranges: list) -> tuple:
    """
    Calcule les pénalités anti-overfitting.

    Paramètres
    ----------
    stats        : dict des métriques du backtest
    params       : dict des paramètres testés
    param_ranges : liste de ParamRange (pour détecter les valeurs extrêmes)

    Retourne
    --------
    (penalty_total: float [0..0.60], warnings: list[str])
    """
    warnings = []
    total_penalty = 0.0

    pf      = stats.get("profit_factor", 1.0)
    n       = stats.get("n_trades", stats.get("total_trades", 0))
    gain    = stats.get("net_ret_pct", stats.get("pct_gain", 0.0))
    dd      = stats.get("max_dd_pct", 1.0)
    r_sq    = stats.get("equity_r_squared", 0.5)

    # ── Pénalité 0 : PF infini → aucune perte, très suspect ──
    if math.isinf(pf):
        total_penalty += 0.10
        warnings.append(
            f"Profit Factor infini (aucune perte sur {n} trades) → statistiquement suspect"
        )

    # ── Pénalité 1 : PF élevé basé sur peu de trades ──────────
    if not math.isinf(pf) and pf > 3.5 and n < 50:
        # De 5% (trades proches de 50) à 25% (trades=0)
        severity = max(0.05, 0.25 * (1.0 - n / 50.0))
        total_penalty += severity
        warnings.append(
            f"PF élevé ({pf:.2f}) basé sur peu de trades ({n}) → peu fiable"
        )

    # ── Pénalité 2 : Paramètres aux valeurs extrêmes ──────────
    # Support both ParamRange dataclass and plain dict (config JSON)
    def _pr(obj, attr, default=None):
        return obj.get(attr, default) if isinstance(obj, dict) else getattr(obj, attr, default)

    extreme_count = 0
    for pr in param_ranges:
        if _pr(pr, "param_type") == "number" and _pr(pr, "min_val") is not None:
            name    = _pr(pr, "name")
            min_val = _pr(pr, "min_val")
            max_val = _pr(pr, "max_val")
            step    = _pr(pr, "step", 1)
            val = params.get(name)
            if val is not None and min_val is not None and max_val is not None:
                if abs(val - min_val) < step * 0.01 or abs(val - max_val) < step * 0.01:
                    extreme_count += 1

    if extreme_count >= 2:
        pen = min(0.05 * extreme_count, 0.25)
        total_penalty += pen
        warnings.append(
            f"{extreme_count} paramètre(s) sur valeur extrême du range → risque d'overfitting"
        )

    # ── Pénalité 3 : Ratio gain/DD irréaliste ─────────────────
    if dd > 0:
        ratio_gdd = gain / dd
        if ratio_gdd > 25.0:
            total_penalty += 0.15
            warnings.append(
                f"Ratio gain/drawdown suspect ({ratio_gdd:.1f}x)"
            )

    # ── Pénalité 4 : Equity irrégulière ───────────────────────
    if r_sq < 0.5:
        # 0% si r_sq=0.5, 20% si r_sq=0
        pen = 0.20 * (0.5 - r_sq) / 0.5
        total_penalty += pen
        warnings.append(
            f"Equity curve irrégulière (R²={r_sq:.2f}) → performance peu constante"
        )

    # Plafonner à 60%
    return min(total_penalty, 0.60), warnings


# ══════════════════════════════════════════════════════════════════════════════
# SCORE GLOBAL
# ══════════════════════════════════════════════════════════════════════════════

def compute_score(
    stats: dict,
    weights: ScoreWeights,
    filters: FilterConfig,
    params: dict = None,
    param_ranges: list = None,
) -> tuple:
    """
    Calcule le score global d'un résultat de backtest.

    Paramètres
    ----------
    stats        : dict retourné par engine._compute_stats()
    weights      : pondération des métriques
    filters      : filtres éliminatoires
    params       : dict des paramètres (pour les pénalités)
    param_ranges : liste de ParamRange (pour détecter les extrêmes)

    Retourne
    --------
    (score: float [0..100], filtered_out: bool, filter_reason: str, warnings: list[str])
    """
    # ── 1. Filtres éliminatoires ───────────────────────────────
    filtered, reason = is_filtered_out(stats, filters)
    if filtered:
        return 0.0, True, reason, []

    # ── 2. Extraction des métriques (défensive) ────────────────
    pf       = stats.get("profit_factor", 1.0)
    dd       = stats.get("max_dd_pct", 0.0)
    n        = stats.get("n_trades", stats.get("total_trades", 0))
    consec   = stats.get("max_consec_loss", stats.get("max_consecutive_losses", 0))
    gain_pct = stats.get("net_ret_pct", stats.get("pct_gain", 0.0))
    wr       = stats.get("win_rate", 0.0)
    payoff   = stats.get("payoff", stats.get("avg_win_loss_ratio", 1.0))
    r_sq     = stats.get("equity_r_squared", 0.5)

    # Recovery factor : net_profit / max_dd_usd
    net_profit = stats.get("net_ret_usd", stats.get("net_profit", 0.0))
    max_dd_usd = stats.get("max_dd_usd", 1.0)
    if max_dd_usd > 0:
        rf = net_profit / max_dd_usd
    else:
        rf = 0.0

    # ── 3. Normalisation ──────────────────────────────────────
    norms = {
        "profit_factor":          normalize_profit_factor(pf)          * weights.profit_factor,
        "max_drawdown":           normalize_max_drawdown(dd)            * weights.max_drawdown,
        "total_trades":           normalize_total_trades(n)             * weights.total_trades,
        "max_consecutive_losses": normalize_consecutive_losses(consec)  * weights.max_consecutive_losses,
        "pct_gain":               normalize_pct_gain(gain_pct)          * weights.pct_gain,
        "win_rate":               normalize_win_rate(wr)                * weights.win_rate,
        "avg_win_loss_ratio":     normalize_avg_win_loss_ratio(payoff)  * weights.avg_win_loss_ratio,
        "equity_regularity":      normalize_equity_regularity(r_sq)     * weights.equity_regularity,
        "recovery_factor":        normalize_recovery_factor(rf)         * weights.recovery_factor,
    }

    total_weight = (
        weights.profit_factor + weights.max_drawdown + weights.total_trades
        + weights.max_consecutive_losses + weights.pct_gain + weights.win_rate
        + weights.avg_win_loss_ratio + weights.equity_regularity + weights.recovery_factor
    )

    weighted_sum = sum(norms.values())
    base_score   = weighted_sum / total_weight if total_weight > 0 else 0.0

    # ── 4. Pénalités anti-overfitting ─────────────────────────
    penalty, warnings = compute_penalties(
        stats,
        params or {},
        param_ranges or [],
    )

    # ── 5. Score final ─────────────────────────────────────────
    final_score = 100.0 * base_score * (1.0 - penalty)
    final_score = max(0.0, min(100.0, final_score))

    return final_score, False, "", warnings


# ══════════════════════════════════════════════════════════════════════════════
# ANALYSE DE SENSIBILITÉ
# ══════════════════════════════════════════════════════════════════════════════

def compute_sensitivity_filtered(results: list, param_name: str, best_params: dict) -> float:
    """
    Méthode A — Modes 1, 2, 3 (grilles complètes).
    Filtre les résultats où tous les autres paramètres sont identiques
    à best_params, et calcule l'écart-type des scores sur ce param.
    """
    filtered = [
        r for r in results
        if r.get("score", 0) > 0 and all(
            r["params"].get(k) == best_params.get(k)
            for k in best_params if k != param_name
        )
    ]
    if len(filtered) < 3:
        return 0.0
    scores = [r["score"] for r in filtered]
    return round(float(np.std(scores)), 3)


def compute_sensitivity_correlation(results: list, param_name: str) -> float:
    """
    Méthode B — Mode 4 (échantillonnage aléatoire / grille progressive).
    Corrélation rang de Spearman entre la valeur du param et le score.
    """
    try:
        from scipy.stats import spearmanr
    except ImportError:
        # Fallback sans scipy : corrélation de Pearson
        pairs = [
            (r["params"].get(param_name), r["score"])
            for r in results
            if r.get("score", 0) > 0 and r["params"].get(param_name) is not None
        ]
        if len(pairs) < 10:
            return 0.0
        vals   = np.array([p[0] for p in pairs], dtype=float)
        scores = np.array([p[1] for p in pairs], dtype=float)
        if vals.std() == 0 or scores.std() == 0:
            return 0.0
        corr = np.corrcoef(vals, scores)[0, 1]
        return round(abs(float(corr)), 3)

    pairs = [
        (r["params"].get(param_name), r["score"])
        for r in results
        if r.get("score", 0) > 0 and r["params"].get(param_name) is not None
    ]
    if len(pairs) < 10:
        return 0.0
    vals   = [p[0] for p in pairs]
    scores = [p[1] for p in pairs]
    corr, _ = spearmanr(vals, scores)
    if math.isnan(corr):
        return 0.0
    return round(abs(float(corr)), 3)
