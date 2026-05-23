"""
report_generator.py — Génération du rapport automatique orienté décision.
Fonctions pures : pas d'I/O, pas de Streamlit.
"""

import math


# ══════════════════════════════════════════════════════════════════════════════
# CATÉGORISATION DU MEILLEUR RÉSULTAT
# ══════════════════════════════════════════════════════════════════════════════

def categorize_result(top1: dict, train_test_enabled: bool = False) -> str:
    """
    Retourne l'une des 4 catégories :
    - "Réglage recommandé"
    - "Réglage agressif"
    - "Réglage défensif"
    - "Réglage à éviter"
    """
    score       = top1.get("score", 0)
    stats       = top1.get("stats", {})
    dd          = stats.get("max_dd_pct", 100.0)
    pf          = stats.get("profit_factor", 0.0)
    degradation = top1.get("degradation_pct", 0.0)

    if score < 40 or (train_test_enabled and degradation > 50):
        return "Réglage à éviter"
    elif dd > 20 or (not math.isinf(pf) and pf > 3.5):
        return "Réglage agressif"
    elif dd < 10 and pf < 1.5:
        return "Réglage défensif"
    else:
        return "Réglage recommandé"


def _risk_level(degradation_pct: float) -> str:
    if degradation_pct < 15:
        return "Faible"
    elif degradation_pct < 30:
        return "Modéré"
    else:
        return "Élevé"


# ══════════════════════════════════════════════════════════════════════════════
# POINTS FORTS / POINTS FAIBLES
# ══════════════════════════════════════════════════════════════════════════════

def _analyse_strengths(top1: dict, config_dict: dict) -> list:
    stats = top1.get("stats", {})
    pf    = stats.get("profit_factor", 0)
    dd    = stats.get("max_dd_pct", 0)
    n     = stats.get("n_trades", stats.get("total_trades", 0))
    wr    = stats.get("win_rate", 0)
    r_sq  = stats.get("equity_r_squared", 0)
    gain  = stats.get("net_ret_pct", 0)

    points = []

    if not math.isinf(pf) and pf >= 2.0:
        points.append(f"Profit Factor solide à {pf:.2f}")
    elif not math.isinf(pf) and pf >= 1.5:
        points.append(f"Profit Factor correct à {pf:.2f}")

    if dd <= 10:
        points.append(f"Drawdown très maîtrisé à {dd:.1f}%")
    elif dd <= 15:
        points.append(f"Drawdown maîtrisé à {dd:.1f}%")

    if r_sq >= 0.85:
        points.append(f"Equity curve très régulière (R²={r_sq:.2f})")
    elif r_sq >= 0.70:
        points.append(f"Equity curve régulière (R²={r_sq:.2f})")

    if n >= 100:
        points.append(f"{n} trades : résultat statistiquement très significatif")
    elif n >= 50:
        points.append(f"{n} trades : résultat statistiquement significatif")
    elif n >= 30:
        points.append(f"{n} trades : statistiques minimales respectées")

    if wr >= 60:
        points.append(f"Winrate élevé à {wr:.1f}%")
    elif wr >= 50:
        points.append(f"Winrate positif à {wr:.1f}%")

    if gain >= 100:
        points.append(f"Performance brute attractive : +{gain:.1f}%")

    if not points:
        points.append("Paramètres valides selon les filtres de base")

    return points


def _analyse_weaknesses(top1: dict, config_dict: dict, sensitivity: dict) -> list:
    stats  = top1.get("stats", {})
    params = top1.get("params", {})
    pf     = stats.get("profit_factor", 0)
    dd     = stats.get("max_dd_pct", 0)
    n      = stats.get("n_trades", stats.get("total_trades", 0))
    wr     = stats.get("win_rate", 0)
    r_sq   = stats.get("equity_r_squared", 0)

    points   = []
    warnings = top1.get("warnings", [])

    # Avertissements de scoring
    for w in warnings:
        points.append(w)

    # Peu de trades
    if n < 50 and n > 0:
        points.append(
            f"Seulement {n} trades — résultat peu fiable statistiquement. "
            "Idéalement 50+ trades."
        )

    # DD élevé
    if dd > 20:
        points.append(f"Drawdown élevé à {dd:.1f}% — à surveiller en trading réel")

    # Equity irrégulière
    if r_sq < 0.60:
        points.append(f"Equity curve peu régulière (R²={r_sq:.2f}) — "
                      "la performance n'est pas constante dans le temps")

    # Paramètres extrêmes
    param_ranges = config_dict.get("param_ranges", [])
    for pr in param_ranges:
        if not pr.get("enabled", True):
            continue
        name = pr.get("name")
        if name and params.get(name) is not None:
            val = params[name]
            if pr.get("param_type") == "number":
                min_v = pr.get("min_val")
                max_v = pr.get("max_val")
                step  = pr.get("step", 1)
                if min_v is not None and abs(val - min_v) < step * 0.01:
                    points.append(
                        f"{pr.get('label', name)} à la valeur minimum du range — "
                        "tester des valeurs inférieures recommandé"
                    )
                elif max_v is not None and abs(val - max_v) < step * 0.01:
                    points.append(
                        f"{pr.get('label', name)} à la valeur maximum du range — "
                        "tester des valeurs supérieures recommandé"
                    )

    # Winrate bas
    if 0 < wr < 40:
        points.append(f"Winrate bas à {wr:.1f}% — nécessite un bon ratio gain/perte")

    if not points:
        points.append(
            "Résultat à vérifier sur d'autres périodes de marché avant de trader en réel"
        )

    return points[:6]  # Limiter à 6 points faibles max


# ══════════════════════════════════════════════════════════════════════════════
# RECOMMANDATIONS FINALES
# ══════════════════════════════════════════════════════════════════════════════

def _paper_trading_advice(top1: dict, train_test_enabled: bool) -> tuple:
    """Retourne (convient_paper: bool, raison: str)"""
    stats       = top1.get("stats", {})
    score       = top1.get("score", 0)
    dd          = stats.get("max_dd_pct", 0)
    wr          = stats.get("win_rate", 0)
    degradation = top1.get("degradation_pct", 0)

    if score < 40:
        return False, "Score trop faible (< 40). Continuer à optimiser."
    if dd > 25:
        return False, f"Drawdown trop élevé ({dd:.1f}%). Risque réel inacceptable."
    if train_test_enabled and degradation > 50:
        return False, f"Dégradation train/test de {degradation:.1f}% — fort risque d'overfitting."
    if dd <= 15 and wr >= 45:
        return True, f"Drawdown <15% et winrate ≥45%. Score de robustesse satisfaisant."
    if score >= 60:
        return True, f"Score de robustesse correct ({score:.1f}). Paper trading envisageable avec prudence."
    return False, f"Score ({score:.1f}) insuffisant pour engager du capital, même virtuel."


# ══════════════════════════════════════════════════════════════════════════════
# GÉNÉRATION DU RAPPORT
# ══════════════════════════════════════════════════════════════════════════════

def generate_report(
    all_results: list,
    sensitivity: dict,
    config_dict: dict,
) -> dict:
    """
    Génère le rapport automatique orienté décision.

    Paramètres
    ----------
    all_results  : liste de tous les résultats scorés
    sensitivity  : dict {param_name: score_sensitivite}
    config_dict  : dict de configuration sérialisé

    Retourne
    --------
    dict du rapport (voir spec §13)
    """
    if not all_results:
        return {
            "categorie":           "Aucun résultat",
            "resume":              "L'optimisation n'a produit aucun résultat valide.",
            "points_forts":        [],
            "points_faibles":      ["Aucun résultat ne passe les filtres éliminatoires."],
            "risque_overfitting":  "N/A",
            "raison_overfitting":  "",
            "variables_sensibles": [],
            "variables_peu_sensibles": [],
            "convient_paper_trading": False,
            "raison_paper_trading": "Aucun résultat valide.",
            "retester_autre_periode": True,
            "raison_retester":     "Impossible d'évaluer sans résultats.",
            "recommandation_finale": "Revoir les filtres et les plages de paramètres.",
        }

    valid = [r for r in all_results if r.get("score", 0) > 0]
    if not valid:
        return {
            "categorie":           "Réglage à éviter",
            "resume":              "Aucun réglage ne passe les filtres de qualité minimale.",
            "points_forts":        [],
            "points_faibles":      ["Tous les résultats ont été éliminés par les filtres."],
            "risque_overfitting":  "N/A",
            "raison_overfitting":  "",
            "variables_sensibles": [],
            "variables_peu_sensibles": [],
            "convient_paper_trading": False,
            "raison_paper_trading": "Aucun résultat valide.",
            "retester_autre_periode": True,
            "raison_retester":     "",
            "recommandation_finale": "Assouplir les filtres ou élargir les plages de paramètres.",
        }

    valid.sort(key=lambda r: r["score"], reverse=True)
    top1 = valid[0]

    train_test_enabled = config_dict.get("train_test", {}).get("enabled", False)
    degradation        = top1.get("degradation_pct", 0.0)
    stats              = top1.get("stats", {})

    # ── Catégorie ─────────────────────────────────────────────
    categorie = categorize_result(top1, train_test_enabled)

    # ── Résumé ────────────────────────────────────────────────
    pf    = stats.get("profit_factor", 0)
    dd    = stats.get("max_dd_pct", 0)
    n     = stats.get("n_trades", stats.get("total_trades", 0))
    gain  = stats.get("net_ret_pct", 0)
    score = top1.get("score", 0)

    pf_str = f"{pf:.2f}" if not math.isinf(pf) else "∞"
    resume = (
        f"Le meilleur réglage offre un score de robustesse de {score:.1f}/100. "
        f"Gain de {gain:.1f}%, drawdown max {dd:.1f}%, "
        f"sur {n} trade{'s' if n != 1 else ''} avec un Profit Factor de {pf_str}."
    )
    if train_test_enabled:
        resume += (
            f" Dégradation train→test : {degradation:.1f}% "
            f"({'⚠️ overfitting détecté' if degradation > 30 else '✅ acceptable'})."
        )

    # ── Points forts / faibles ────────────────────────────────
    points_forts   = _analyse_strengths(top1, config_dict)
    points_faibles = _analyse_weaknesses(top1, config_dict, sensitivity)

    # ── Risque d'overfitting ──────────────────────────────────
    risque_level = _risk_level(degradation) if train_test_enabled else "Non évalué"
    raisons_of   = []

    if train_test_enabled:
        raisons_of.append(
            f"Dégradation train/test de {degradation:.1f}% "
            f"({'acceptable' if degradation <= 30 else 'importante'})."
        )
    else:
        raisons_of.append("Split train/test non activé — overfitting non quantifié.")

    warnings = top1.get("warnings", [])
    if warnings:
        raisons_of.extend(warnings[:2])

    raison_overfitting = " ".join(raisons_of)

    # ── Variables sensibles ───────────────────────────────────
    if sensitivity:
        sorted_sens = sorted(sensitivity.items(), key=lambda x: x[1], reverse=True)
        threshold   = 0.15  # Sensibilité ≥ 0.15 = variable importante
        variables_sensibles      = [f"{k} ({v:.2f})" for k, v in sorted_sens if v >= threshold]
        variables_peu_sensibles  = [f"{k} ({v:.2f})" for k, v in sorted_sens if v < threshold]
    else:
        variables_sensibles     = []
        variables_peu_sensibles = []

    # ── Conseil paper trading ─────────────────────────────────
    convient_paper, raison_paper = _paper_trading_advice(top1, train_test_enabled)

    # ── Conseil retester ──────────────────────────────────────
    retester = True
    if train_test_enabled and degradation <= 15 and score >= 65:
        retester = False

    if train_test_enabled:
        raison_retester = (
            f"Dégradation train/test de {degradation:.1f}% : "
            f"{'acceptable — valider sur un troisième jeu de données' if degradation <= 30 else 'importante — fortement conseillé de tester sur d autres périodes'}"
        )
    else:
        raison_retester = (
            "Le split train/test n'était pas activé. Tester ces paramètres "
            "sur une autre période est fortement recommandé avant tout trading réel."
        )

    # ── Recommandation finale ─────────────────────────────────
    if categorie == "Réglage recommandé" and convient_paper:
        recommandation = (
            f"Ce réglage est utilisable pour du paper trading avec les paramètres trouvés. "
            f"Avant le live, valider sur au moins 3 mois supplémentaires non vus par l'optimisateur."
        )
    elif categorie == "Réglage agressif":
        recommandation = (
            f"Réglage performant mais risqué (DD {dd:.1f}%). "
            "Réduire la taille des positions ou ajuster le stop loss avant de trader en réel."
        )
    elif categorie == "Réglage défensif":
        recommandation = (
            "Réglage peu risqué mais peu profitable. "
            "Envisager d'élargir les plages de stop loss et take profit."
        )
    else:
        recommandation = (
            "Ce réglage ne remplit pas les critères minimaux. "
            "Continuer l'optimisation avec des plages de paramètres différentes."
        )

    return {
        "categorie":              categorie,
        "resume":                 resume,
        "points_forts":           points_forts,
        "points_faibles":         points_faibles,
        "risque_overfitting":     risque_level,
        "raison_overfitting":     raison_overfitting,
        "variables_sensibles":    variables_sensibles,
        "variables_peu_sensibles": variables_peu_sensibles,
        "convient_paper_trading": convient_paper,
        "raison_paper_trading":   raison_paper,
        "retester_autre_periode": retester,
        "raison_retester":        raison_retester,
        "recommandation_finale":  recommandation,
    }
