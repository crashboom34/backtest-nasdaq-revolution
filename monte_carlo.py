"""
monte_carlo.py — Monte-Carlo V1 : rééchantillonnage de trades (AF-V-03 Slice 2).

Contrat de référence : `docs/adr/0022-monte-carlo-trade-resampling-v1.md` (Décisions 1-13). Module
top-level LEAF (Décision 11) : n'importe ni `engine.py`, ni `optimizer.py`, ni `dataset_split.py`,
ni `walk_forward.py` — preuve structurelle de la Décision 10 (impossibilité structurelle d'accéder
à la zone holdout finale réservée, jamais consultée ni consultable ici). Seul `validation_run.py`
(leaf lui-même) est importé, pour les contrats typés déjà posés par AF-V-03 Slice 1
(`MonteCarloSpecification`/`MonteCarloEvidence`/`PercentileDistributionSummary`) et
`UnknownVerdictPolicy` (réutilisée telle quelle, Décision 9/12).

`run_monte_carlo_simulation(trades, spec) -> MonteCarloEvidence` est la seule fonction publique :
fonction PURE, aucun accès disque/réseau (Décision 14 — arithmétique `numpy` vectorisée uniquement).
"""

from __future__ import annotations

import hashlib
import itertools
import math
from typing import Optional, Tuple

import numpy as np

from validation_run import (
    PercentileDistributionSummary,
    MonteCarloEvidence,
    MonteCarloSpecification,
    UnknownVerdictPolicy,
)

_MONTE_CARLO_SEED_DOMAIN_TAG = "mc-v1"
"""Tag de domaine SHA-256 pour la dérivation des graines PAR MÉTHODE depuis `spec.master_seed`
(ADR 0022 Décision 5) — distinct de `_MONTE_CARLO_MASTER_SEED_DOMAIN_TAG` (`validation_run.py`,
Slice 1, dérivation de `master_seed` lui-même depuis `source_validation_run_id`)."""

METHOD_SEQUENCE_RISK = "sequence_risk"
METHOD_SAMPLING_UNCERTAINTY = "sampling_uncertainty"
_VALID_METHODS = (METHOD_SEQUENCE_RISK, METHOD_SAMPLING_UNCERTAINTY)


def _derive_method_seed(master_seed: int, method: str) -> int:
    """Un seul flux aléatoire dérivé PAR MÉTHODE, jamais partagé entre `sequence_risk`/
    `sampling_uncertainty` (ADR 0022 Décision 5) : `sha256(f"{master_seed}:{method}:mc-v1")`,
    jamais `hash()`/`time.time()`/`random.randint()`. `method` inconnu -> `ValueError` immédiat
    (Décision 9), jamais une valeur par défaut silencieuse."""
    if method not in _VALID_METHODS:
        raise ValueError(
            f"method invalide : {method!r} — attendu un de {_VALID_METHODS!r} "
            "(ADR 0022 Décision 9)."
        )
    payload = f"{master_seed}:{method}:{_MONTE_CARLO_SEED_DOMAIN_TAG}"
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest(), 16)


def _chain_returns(returns: np.ndarray) -> np.ndarray:
    """Courbe(s) d'équité chaînée(s) par PRODUIT cumulatif `(1 + r_i/100)`, jamais une somme (ADR
    0022 Décision 1/2 — même convention que `walk_forward.build_aggregate_result()`). `returns` de
    forme `(..., n_trades)` ; retourne une courbe de forme `(..., n_trades + 1)` dont la première
    colonne vaut `1.0` (base avant tout trade, nécessaire pour mesurer le drawdown du tout premier
    trade)."""
    factors = 1.0 + returns / 100.0
    chained = np.cumprod(factors, axis=-1)
    ones = np.ones(chained.shape[:-1] + (1,), dtype=chained.dtype)
    return np.concatenate([ones, chained], axis=-1)


def _max_drawdown_trade_close_basis(equity_curves: np.ndarray) -> np.ndarray:
    """Max drawdown en base « clôture de trade » (ADR 0022 Décision 6), vectorisé sur la dernière
    dimension. `equity_curves` de forme `(n_rows, n_trades + 1)` (sortie de `_chain_returns()`) ;
    retourne un tableau `(n_rows,)`. Ignore structurellement l'excursion intra-trade — jamais
    comparable au `max_dd_pct` barre-par-barre du moteur (Décision 6)."""
    peaks = np.maximum.accumulate(equity_curves, axis=-1)
    drawdowns = np.where(peaks > 0, (peaks - equity_curves) / peaks * 100.0, 0.0)
    return drawdowns.max(axis=-1)


def _longest_losing_streak(returns: np.ndarray) -> np.ndarray:
    """Plus longue série de `r_i <= 0` consécutifs, vectorisée sur la dernière dimension (boucle
    sur `n_trades`, jamais sur `n_simulations` — reste dans le budget de calcul de la Décision 14).
    `returns` de forme `(n_rows, n_trades)` ; retourne un tableau entier `(n_rows,)`."""
    is_loss = returns <= 0
    n_trades = is_loss.shape[-1]
    streak = np.zeros(is_loss.shape, dtype=np.int64)
    streak[..., 0] = is_loss[..., 0].astype(np.int64)
    for i in range(1, n_trades):
        streak[..., i] = np.where(is_loss[..., i], streak[..., i - 1] + 1, 0)
    return streak.max(axis=-1)


def _distribution_summary(values: np.ndarray, method: str = "linear") -> PercentileDistributionSummary:
    """Résumé en percentiles `p5`/`p25`/`p50`/`p75`/`p95` (ADR 0022 Décision 6). `method="lower"`
    réservé à `sequence_risk_longest_losing_streak` (Décision 11 — valeurs ENTIÈRES réellement
    observées dans l'échantillon simulé, jamais interpolées linéairement)."""
    p5, p25, p50, p75, p95 = np.percentile(values, [5, 25, 50, 75, 95], method=method)
    return PercentileDistributionSummary(
        p5=float(p5), p25=float(p25), p50=float(p50), p75=float(p75), p95=float(p95),
    )


def _draw_sequence_risk_permutations(
    trades_arr: np.ndarray, n_simulations: int, master_seed: int,
) -> np.ndarray:
    """Tirage brut des permutations pour `sequence_risk` (ADR 0022 Décision 2.1/4/5), séparé de
    l'agrégation pour rester directement testable (chaque ligne = une permutation valide et
    indépendante) : si `n_trades! < n_simulations`, énumération EXHAUSTIVE et déterministe
    (`itertools.permutations`, `rng` non consommé) plutôt qu'un tirage aléatoire avec répétitions
    inutiles (Décision 4/9) ; sinon, tirage vectorisé de `n_simulations` permutations distinctes via
    `rng.permuted()` en un seul appel (Décision 5). Retourne un tableau `(n_rows, n_trades)`."""
    n_trades = trades_arr.shape[0]
    if math.factorial(n_trades) < n_simulations:
        perms = np.array(list(itertools.permutations(range(n_trades))))
        return trades_arr[perms]
    method_seed = _derive_method_seed(master_seed, METHOD_SEQUENCE_RISK)
    rng = np.random.default_rng(method_seed)
    base = np.tile(trades_arr, (n_simulations, 1))
    return rng.permuted(base, axis=1)


def _draw_sampling_uncertainty_samples(
    trades_arr: np.ndarray, n_simulations: int, master_seed: int,
) -> np.ndarray:
    """Tirage brut du bootstrap pour `sampling_uncertainty` (ADR 0022 Décision 2.2/5), séparé de
    l'agrégation pour rester directement testable : `n_simulations` échantillons de taille
    `n_trades` AVEC REMISE, tirés en un seul appel vectorisé (`rng.integers()`). Retourne un
    tableau `(n_simulations, n_trades)`."""
    n_trades = trades_arr.shape[0]
    method_seed = _derive_method_seed(master_seed, METHOD_SAMPLING_UNCERTAINTY)
    rng = np.random.default_rng(method_seed)
    idx = rng.integers(0, n_trades, size=(n_simulations, n_trades))
    return trades_arr[idx]


def _sequence_risk(
    trades_arr: np.ndarray, n_simulations: int, master_seed: int,
) -> Tuple[PercentileDistributionSummary, PercentileDistributionSummary]:
    """Permutation/réordonnancement (ADR 0022 Décision 2.1) : reconstruit la courbe d'équité
    chaînée pour chaque permutation tirée par `_draw_sequence_risk_permutations()`, agrège le max
    drawdown et la plus longue série de pertes consécutives en `PercentileDistributionSummary`."""
    permuted = _draw_sequence_risk_permutations(trades_arr, n_simulations, master_seed)

    curves = _chain_returns(permuted)
    max_dd = _max_drawdown_trade_close_basis(curves)
    streaks = _longest_losing_streak(permuted)

    return (
        _distribution_summary(max_dd, method="linear"),
        _distribution_summary(streaks.astype(np.float64), method="lower"),
    )


def _sampling_uncertainty(
    trades_arr: np.ndarray, n_simulations: int, master_seed: int,
) -> Tuple[PercentileDistributionSummary, PercentileDistributionSummary]:
    """Bootstrap avec remise (ADR 0022 Décision 2.2) : reconstruit la courbe d'équité chaînée pour
    chaque échantillon tiré par `_draw_sampling_uncertainty_samples()`, agrège le rendement net
    final ET le max drawdown en `PercentileDistributionSummary`."""
    sampled = _draw_sampling_uncertainty_samples(trades_arr, n_simulations, master_seed)

    curves = _chain_returns(sampled)
    net_ret = (curves[:, -1] - 1.0) * 100.0
    max_dd = _max_drawdown_trade_close_basis(curves)

    return _distribution_summary(net_ret), _distribution_summary(max_dd)


def _lag1_autocorrelation(trades_arr: np.ndarray) -> Optional[float]:
    """Autocorrélation empirique standard des `net_ret_pct` à l'ordre 1 (ADR 0022 Décision 3) —
    `None` si `n_trades < 3` (mathématiquement indéfini, jamais une valeur inventée). Il faut au
    moins 2 PAIRES `(x_i, x_i+1)` pour une corrélation de Pearson définie, donc au moins 3 trades
    — avec exactement 2 trades, `trades_arr[:-1]`/`trades_arr[1:]` sont chacun des tableaux à un
    seul élément (degrés de liberté = 0 pour `np.corrcoef`), qui produirait `nan`, jamais `None`
    (revue indépendante, correction du seuil `< 2` -> `< 3`). Même indétermination mathématique
    pour `n_trades >= 3` dès que `trades_arr[:-1]` ou `trades_arr[1:]` a une variance nulle (ex.
    plusieurs `net_ret_pct` consécutifs strictement identiques, plausible avec une taille de
    position/distance de stop fixe) — `np.corrcoef` produit alors `0/0 = nan`, silencieusement
    masqué par `np.errstate` mais jamais converti en `None` : détecté explicitement ci-dessous
    (finding MAJOR, revue indépendante) plutôt que laissé fuiter dans `MonteCarloEvidence`."""
    if trades_arr.shape[0] < 3:
        return None
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(trades_arr[:-1], trades_arr[1:])[0, 1]
    if np.isnan(corr):
        return None
    return float(corr)


def _resolve_verdict(spec: MonteCarloSpecification) -> Tuple[str, Tuple[str, ...]]:
    """Séparation stricte preuve factuelle / verdict scientifique (ADR 0022 Décision 12, mirroring
    exact de Walk-Forward) : `scientific_verdict` reste TOUJOURS `"INCONCLUSIVE"` sans
    `verdict_policy_id` enregistré ; `verdict_policy_id` fourni -> `UnknownVerdictPolicy` levée
    (réutilisée telle quelle depuis `validation_run.py`, jamais une classe dupliquée) — aucune
    politique concrète de seuils PASS/FAIL n'existe dans ce dépôt à ce jour."""
    if spec.verdict_policy_id is None:
        return "INCONCLUSIVE", (
            "Aucun verdict_policy_id enregistré pour cette MonteCarloSpecification — le verdict "
            "reste structurellement INCONCLUSIVE (ADR 0022 Décision 12).",
        )
    raise UnknownVerdictPolicy(
        f"verdict_policy_id={spec.verdict_policy_id!r} ne correspond à aucune politique "
        "enregistrée — aucune politique concrète de seuils PASS/FAIL n'existe encore dans ce "
        "dépôt (ADR 0022 Décision 12)."
    )


def run_monte_carlo_simulation(
    trades: Tuple[float, ...], spec: MonteCarloSpecification,
) -> MonteCarloEvidence:
    """Orchestre l'ensemble du protocole Monte-Carlo V1 (ADR 0022) — fonction PURE. `trades` :
    séquence ORDONNÉE de `net_ret_pct` par trade (Décision 1), fournie par l'appelant, jamais
    recalculée ici. `n_trades == 0` -> `zero_trade_input=True`, tous les champs numériques `None`,
    jamais une exception (Décision 7). `execution_status` reste TOUJOURS `"completed"` en V1
    (Décision 11 — aucune notion d'interruption coopérative ici, contrairement à Walk-Forward).

    `spec.n_simulations <= 0` -> `ValueError` immédiat, avant tout calcul (Décision 9) : bien que
    `build_monte_carlo_specification()` (Slice 1) ne puisse structurellement pas produire cette
    valeur, `MonteCarloSpecification` reste une dataclass frozen ordinaire (dette disciplinaire
    assumée, Décision 5) — un appelant qui la construit directement en contournant le builder ne
    doit jamais silencieusement dégénérer vers un tirage vide/une erreur numpy sans rapport."""
    if spec.n_simulations <= 0:
        raise ValueError(
            f"n_simulations doit être strictement positif, reçu {spec.n_simulations!r} "
            "(ADR 0022 Décision 9)."
        )
    scientific_verdict, verdict_reasons = _resolve_verdict(spec)

    n_trades = len(trades)
    if n_trades == 0:
        return MonteCarloEvidence(
            n_input_trades=0,
            zero_trade_input=True,
            observed_net_ret_pct=None,
            observed_max_dd_trade_close_basis_pct=None,
            observed_lag1_autocorrelation=None,
            observed_longest_losing_streak=None,
            sequence_risk_max_dd_trade_close_basis_pct=None,
            sequence_risk_longest_losing_streak=None,
            sampling_uncertainty_net_ret_pct=None,
            sampling_uncertainty_max_dd_trade_close_basis_pct=None,
            execution_status="completed",
            scientific_verdict=scientific_verdict,
            verdict_reasons=verdict_reasons,
        )

    trades_arr = np.asarray(trades, dtype=np.float64)

    observed_curve = _chain_returns(trades_arr.reshape(1, -1))
    observed_net_ret_pct = float((observed_curve[0, -1] - 1.0) * 100.0)
    observed_max_dd = float(_max_drawdown_trade_close_basis(observed_curve)[0])
    observed_streak = int(_longest_losing_streak(trades_arr.reshape(1, -1))[0])
    observed_autocorr = _lag1_autocorrelation(trades_arr)

    seq_max_dd_summary, seq_streak_summary = _sequence_risk(
        trades_arr, spec.n_simulations, spec.master_seed,
    )
    boot_net_ret_summary, boot_max_dd_summary = _sampling_uncertainty(
        trades_arr, spec.n_simulations, spec.master_seed,
    )

    return MonteCarloEvidence(
        n_input_trades=n_trades,
        zero_trade_input=False,
        observed_net_ret_pct=observed_net_ret_pct,
        observed_max_dd_trade_close_basis_pct=observed_max_dd,
        observed_lag1_autocorrelation=observed_autocorr,
        observed_longest_losing_streak=observed_streak,
        sequence_risk_max_dd_trade_close_basis_pct=seq_max_dd_summary,
        sequence_risk_longest_losing_streak=seq_streak_summary,
        sampling_uncertainty_net_ret_pct=boot_net_ret_summary,
        sampling_uncertainty_max_dd_trade_close_basis_pct=boot_max_dd_summary,
        execution_status="completed",
        scientific_verdict=scientific_verdict,
        verdict_reasons=verdict_reasons,
    )
