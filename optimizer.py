"""
optimizer.py — Moteur d'optimisation de stratégies.
Standalone : fonctionne sans Streamlit, testable en ligne de commande.

Modes disponibles :
  1 - Optimisation variable par variable (séquentiel)
  2 - Optimisation croisée autour des meilleures zones
  3 - Grille complète
  4 - Optimisation générale intelligente (auto selon N)
"""

import math
import time
import hashlib
import json
import random
import statistics
import importlib
import itertools
import os
from dataclasses import dataclass, field
from typing import Optional, Callable

import numpy as np

from scoring import (
    ScoreWeights, FilterConfig,
    compute_score,
    compute_sensitivity_filtered,
    compute_sensitivity_correlation,
)


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURES DE DONNÉES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParamRange:
    """Définit la plage de valeurs à tester pour un paramètre."""
    name:       str
    param_type: str          # "number" | "bool" | "select"
    label:      str
    min_val:    float = None
    max_val:    float = None
    step:       float = None
    options:    list  = None
    enabled:    bool  = True

    def generate_values(self) -> list:
        """Génère toutes les valeurs à tester pour ce paramètre."""
        if not self.enabled:
            return []
        if self.param_type == "number":
            values = []
            v = self.min_val
            while v <= self.max_val + self.step * 0.001:
                values.append(round(v, 10))
                v += self.step
            return values
        elif self.param_type in ("bool", "select"):
            return list(self.options) if self.options else [True, False]
        return []


@dataclass
class TrainTestConfig:
    """Configuration du split train/test."""
    enabled:             bool  = False
    split_method:        str   = "ratio"   # "ratio" | "date"
    train_ratio:         float = 0.70
    split_date:          str   = None      # "YYYY-MM-DD"
    alert_degradation_pct: float = 30.0


@dataclass
class OptimizationConfig:
    """Configuration complète d'un run d'optimisation."""
    run_id:          str
    strategy_module: str
    strategy_name:   str
    data_file:       str
    base_params:     dict
    param_ranges:    list           # list[ParamRange]
    mode:            str            # "single_var" | "cross_zone" | "grid" | "general"
    score_weights:   ScoreWeights
    filters:         FilterConfig
    train_test:      TrainTestConfig
    global_params:   dict           # initial_capital, spread, slip_in, slip_out
    n_workers:       int
    max_combinations_warning: int  = 100_000
    max_combinations: Optional[int] = None
    top_k_save:      int            = 100
    top_k_display:   int            = 10
    resume_run_id:   str            = None
    # ── Période réduite ────────────────────────────────────────────────────────
    opt_start_date:         Optional[str] = None   # "YYYY-MM-DD" ou None
    opt_end_date:           Optional[str] = None   # "YYYY-MM-DD" ou None
    max_rows:               Optional[int] = None   # nb de lignes max après filtre date
    # ── Benchmark configurable ─────────────────────────────────────────────────
    benchmark_n_sample:     int           = 5      # nombre d'échantillons benchmark
    # ── Mode validation rapide ─────────────────────────────────────────────────
    quick_validation_mode:  bool          = False  # presets 100k rows / 16 combos


# ══════════════════════════════════════════════════════════════════════════════
# UTILITAIRES
# ══════════════════════════════════════════════════════════════════════════════

def params_hash(params: dict) -> str:
    """Hash stable d'un dict de paramètres (12 caractères hex)."""
    serialized = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(serialized.encode()).hexdigest()[:12]


def count_combinations(param_ranges: list) -> int:
    """Calcule le nombre total de combinaisons pour une grille complète."""
    total = 1
    for pr in param_ranges:
        if pr.enabled:
            vals = pr.generate_values()
            total *= max(1, len(vals))
    return total


def normalize_max_combinations(max_combinations) -> Optional[int]:
    """Retourne une limite exploitable, ou None si aucune limite n'est demandée."""
    if max_combinations is None:
        return None
    try:
        value = int(max_combinations)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def effective_combinations_total(total_combinations: int, max_combinations=None) -> int:
    """Nombre de combinaisons réellement planifiées après limite optionnelle."""
    total = max(0, int(total_combinations or 0))
    limit = normalize_max_combinations(max_combinations)
    return min(total, limit) if limit is not None else total


def _load_strategy(module_path: str):
    """Charge dynamiquement un module stratégie et retourne (module, Strategy())."""
    if os.path.sep in module_path or module_path.endswith(".py"):
        # Chemin de fichier absolu ou relatif
        spec = importlib.util.spec_from_file_location("_opt_strategy", module_path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    else:
        # Module Python (ex: "strategies.perfect_revolution_v1")
        mod = importlib.import_module(module_path)
    return mod, mod.Strategy()


def _run_single(params: dict, config: OptimizationConfig,
                df, start_date=None, end_date=None) -> dict:
    """
    Lance un backtest unique et retourne le résultat scoré.
    Fonction top-level pour être picklable dans ProcessPoolExecutor.

    Retourne un dict avec : score, params, stats, filtered, filter_reason, warnings
    """
    from engine import run_backtest

    gp = config.global_params
    # Instanciation de la stratégie locale (chaque worker a sa propre instance)
    mod, strat = _load_strategy(config.strategy_module)

    try:
        _, _, stats = run_backtest(
            df,
            strat,
            params,
            initial_capital=gp.get("initial_capital", 10_000.0),
            spread=gp.get("spread", 1.0),
            slip_in=gp.get("slip_in", 0.5),
            slip_out=gp.get("slip_out", 0.5),
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        return {
            "score": 0.0, "params": params, "stats": {},
            "filtered": True, "filter_reason": f"Exception: {e}", "warnings": [],
        }

    if stats.get("n_trades", 0) == 0:
        return {
            "score": 0.0, "params": params, "stats": stats,
            "filtered": True, "filter_reason": "Aucun trade", "warnings": [],
        }

    score, filtered, reason, warnings = compute_score(
        stats,
        config.score_weights,
        config.filters,
        params=params,
        param_ranges=config.param_ranges,
    )

    return {
        "score":         score,
        "params":        params,
        "stats":         stats,
        "filtered":      filtered,
        "filter_reason": reason,
        "warnings":      warnings,
    }


# ══════════════════════════════════════════════════════════════════════════════
# BENCHMARK DE VITESSE
# ══════════════════════════════════════════════════════════════════════════════

def benchmark_speed(config: OptimizationConfig, df, n_sample: int = 20) -> float:
    """
    Lance n_sample backtests avec les paramètres de base.
    Retourne le temps médian en millisecondes par backtest.
    """
    from engine import run_backtest

    mod, strat = _load_strategy(config.strategy_module)
    gp = config.global_params
    times = []

    for _ in range(n_sample):
        t0 = time.perf_counter()
        try:
            strat.reset()
            run_backtest(
                df, strat, config.base_params,
                initial_capital=gp.get("initial_capital", 10_000.0),
                spread=gp.get("spread", 1.0),
                slip_in=gp.get("slip_in", 0.5),
                slip_out=gp.get("slip_out", 0.5),
            )
        except Exception:
            pass
        times.append((time.perf_counter() - t0) * 1000)

    return statistics.median(times) if times else 500.0


# ══════════════════════════════════════════════════════════════════════════════
# CALCUL DES DATES DE SPLIT TRAIN / TEST
# ══════════════════════════════════════════════════════════════════════════════

def compute_split_dates(df, train_test: TrainTestConfig):
    """
    Retourne (train_start, train_end, test_start, test_end) en str "YYYY-MM-DD".
    """
    import pandas as pd

    times = df["time_paris"]
    global_start = times.min()
    global_end   = times.max()

    if train_test.split_method == "date" and train_test.split_date:
        split = pd.Timestamp(train_test.split_date, tz="Europe/Paris")
    else:
        # Méthode ratio
        duration = (global_end - global_start).total_seconds()
        split    = global_start + pd.Timedelta(seconds=duration * train_test.train_ratio)

    train_start = global_start.strftime("%Y-%m-%d")
    train_end   = split.strftime("%Y-%m-%d")
    test_start  = (split + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    test_end    = global_end.strftime("%Y-%m-%d")

    return train_start, train_end, test_start, test_end


# ══════════════════════════════════════════════════════════════════════════════
# MODES D'OPTIMISATION
# ══════════════════════════════════════════════════════════════════════════════

class Optimizer:
    """
    Moteur d'optimisation.

    Utilisation :
        opt = Optimizer(config, df)
        results, sensitivity = opt.run(progress_callback, stop_flag_fn)
    """

    def __init__(self, config: OptimizationConfig, df):
        self.config = config
        self.df     = df
        self._active_ranges = [pr for pr in config.param_ranges if pr.enabled]
        self._max_combinations = normalize_max_combinations(config.max_combinations)
        self._scheduled_combinations = 0

    def _remaining_combination_slots(self) -> Optional[int]:
        if self._max_combinations is None:
            return None
        return max(0, self._max_combinations - self._scheduled_combinations)

    def _apply_max_combinations(self, combos: list) -> list:
        """Applique un plafond global de combinaisons planifiées pour ce run."""
        combos = list(combos)
        remaining = self._remaining_combination_slots()
        if remaining is None:
            return combos
        if remaining <= 0:
            return []
        limited = combos[:remaining]
        self._scheduled_combinations += len(limited)
        return limited

    # ── Exécution séquentielle (un backtest à la fois) ─────────────────────
    def _run_batch_sequential(self, combos: list,
                              progress_cb: Callable = None,
                              stop_flag_fn: Callable = None,
                              already_tested: set = None,
                              start_date=None, end_date=None) -> list:
        """
        Lance une liste de combinaisons de paramètres.
        Retourne une liste de résultats.
        """
        results = []
        total   = len(combos)
        tested  = already_tested or set()

        for idx, params in enumerate(combos):
            if stop_flag_fn and stop_flag_fn():
                break

            h = params_hash(params)
            if h in tested:
                continue
            tested.add(h)

            result = _run_single(params, self.config, self.df, start_date, end_date)
            results.append(result)

            if progress_cb:
                progress_cb(idx + 1, total, result)

        return results

    # ── Exécution parallèle (ProcessPoolExecutor) ──────────────────────────
    def _run_batch_parallel(self, combos: list,
                            progress_cb: Callable = None,
                            stop_flag_fn: Callable = None,
                            already_tested: set = None,
                            start_date=None, end_date=None) -> list:
        """
        Lance les combinaisons en parallèle.
        Taille du pool = config.n_workers.
        """
        from concurrent.futures import ProcessPoolExecutor, as_completed

        results  = []
        total    = len(combos)
        tested   = already_tested or set()
        filtered = [p for p in combos if params_hash(p) not in tested]

        if not filtered:
            return results

        # Pré-ajouter les hashs
        for p in filtered:
            tested.add(params_hash(p))

        futures = {}
        with ProcessPoolExecutor(
            max_workers=self.config.n_workers,
            initializer=_worker_init,
            initargs=(self.df,),
        ) as pool:
            for params in filtered:
                fut = pool.submit(
                    _worker_run_single,
                    params,
                    self.config,
                    start_date,
                    end_date,
                )
                futures[fut] = params

            done_count = 0
            for fut in as_completed(futures):
                if stop_flag_fn and stop_flag_fn():
                    for f in futures:
                        f.cancel()
                    break
                try:
                    result = fut.result()
                except Exception as e:
                    result = {
                        "score": 0.0, "params": futures[fut], "stats": {},
                        "filtered": True, "filter_reason": f"Worker error: {e}",
                        "warnings": [],
                    }
                results.append(result)
                done_count += 1
                if progress_cb:
                    progress_cb(done_count, total, result)

        return results

    def _run_batch(self, combos, progress_cb=None, stop_flag_fn=None,
                   already_tested=None, start_date=None, end_date=None):
        """Dispatche vers séquentiel ou parallèle selon n_workers."""
        combos = self._apply_max_combinations(combos)
        if not combos:
            return []
        if self.config.n_workers <= 1:
            return self._run_batch_sequential(
                combos, progress_cb, stop_flag_fn, already_tested, start_date, end_date)
        else:
            return self._run_batch_parallel(
                combos, progress_cb, stop_flag_fn, already_tested, start_date, end_date)

    # ── Mode 1 : Variable par variable ────────────────────────────────────
    def run_mode1(self, progress_cb=None, stop_flag_fn=None,
                  already_tested=None, train_start=None, train_end=None) -> list:
        """
        Optimise chaque variable indépendamment, en gardant le meilleur réglage.
        """
        best_params = dict(self.config.base_params)
        all_results = []

        for pr in self._active_ranges:
            if stop_flag_fn and stop_flag_fn():
                break
            values = pr.generate_values()
            combos = []
            for v in values:
                p = dict(best_params)
                p[pr.name] = v
                combos.append(p)

            batch = self._run_batch(
                combos, progress_cb, stop_flag_fn, already_tested, train_start, train_end)
            all_results.extend(batch)

            # Garder le meilleur
            valid = [r for r in batch if r["score"] > 0]
            if valid:
                best = max(valid, key=lambda r: r["score"])
                best_params[pr.name] = best["params"][pr.name]

        return all_results

    # ── Mode 2 : Croisée autour des meilleures zones ───────────────────────
    def run_mode2(self, prior_results: list,
                  progress_cb=None, stop_flag_fn=None,
                  already_tested=None, train_start=None, train_end=None) -> list:
        """
        Teste le produit cartésien des valeurs prometteuses (top 30%).
        Nécessite des résultats préalables (mode1 ou run existant).
        """
        # Identifier les zones prometteuses par paramètre
        promising_zones = {}
        for pr in self._active_ranges:
            values = pr.generate_values()
            if not values:
                promising_zones[pr.name] = [self.config.base_params.get(pr.name)]
                continue

            # Scores moyens par valeur
            score_by_val = {}
            for r in prior_results:
                if r["score"] > 0:
                    val = r["params"].get(pr.name)
                    if val is not None:
                        if val not in score_by_val:
                            score_by_val[val] = []
                        score_by_val[val].append(r["score"])

            if not score_by_val:
                promising_zones[pr.name] = values
                continue

            avg_by_val = {v: sum(ss) / len(ss) for v, ss in score_by_val.items()}
            threshold  = np.percentile(list(avg_by_val.values()), 70)
            top_vals   = [v for v, s in avg_by_val.items() if s >= threshold]

            # Si trop peu de valeurs, garder au moins 2
            if len(top_vals) < 2:
                top_vals = sorted(avg_by_val, key=lambda v: avg_by_val[v], reverse=True)[:3]

            promising_zones[pr.name] = top_vals

        # Produit cartésien des zones prometteuses
        names  = list(promising_zones.keys())
        combos = []
        for combo_vals in itertools.product(*[promising_zones[n] for n in names]):
            p = dict(self.config.base_params)
            for name, val in zip(names, combo_vals):
                p[name] = val
            combos.append(p)

        return self._run_batch(
            combos, progress_cb, stop_flag_fn, already_tested, train_start, train_end)

    # ── Mode 3 : Grille complète ───────────────────────────────────────────
    def run_mode3(self, progress_cb=None, stop_flag_fn=None,
                  already_tested=None, train_start=None, train_end=None) -> list:
        """Teste toutes les combinaisons possibles."""
        names  = [pr.name for pr in self._active_ranges]
        values = [pr.generate_values() for pr in self._active_ranges]
        remaining = self._remaining_combination_slots()

        combos = []
        for combo_vals in itertools.product(*values):
            p = dict(self.config.base_params)
            for name, val in zip(names, combo_vals):
                p[name] = val
            combos.append(p)
            if remaining is not None and len(combos) >= remaining:
                break

        return self._run_batch(
            combos, progress_cb, stop_flag_fn, already_tested, train_start, train_end)

    # ── Mode 4 : Optimisation générale intelligente ────────────────────────
    def run_mode4(self, progress_cb=None, stop_flag_fn=None,
                  already_tested=None, train_start=None, train_end=None) -> list:
        """
        Sélectionne automatiquement la méthode selon N_combinations :
        - N ≤ 50 000 : grille complète
        - 50 000 < N ≤ 500 000 : échantillonnage stratifié (50 000 tirages)
        - N > 500 000 : grille progressive 3 passes
        """
        n_total = count_combinations(self._active_ranges)

        if self._max_combinations is not None:
            return self.run_mode3(progress_cb, stop_flag_fn, already_tested, train_start, train_end)

        if n_total <= 50_000:
            return self.run_mode3(progress_cb, stop_flag_fn, already_tested, train_start, train_end)

        elif n_total <= 500_000:
            return self._run_stratified_sample(
                50_000, progress_cb, stop_flag_fn, already_tested, train_start, train_end)

        else:
            return self._run_progressive_grid(
                progress_cb, stop_flag_fn, already_tested, train_start, train_end)

    # ── Échantillonnage stratifié ─────────────────────────────────────────
    def _run_stratified_sample(self, n_sample: int,
                               progress_cb=None, stop_flag_fn=None,
                               already_tested=None, train_start=None, train_end=None) -> list:
        """Tire n_sample combinaisons aléatoires, réparties uniformément."""
        names  = [pr.name for pr in self._active_ranges]
        values = [pr.generate_values() for pr in self._active_ranges]

        seen   = set()
        combos = []

        # Tirage aléatoire sans remise (autant que possible)
        max_attempts = n_sample * 5
        for _ in range(max_attempts):
            if len(combos) >= n_sample:
                break
            combo_vals = tuple(random.choice(v) for v in values)
            h = hashlib.md5(str(combo_vals).encode()).hexdigest()[:8]
            if h not in seen:
                seen.add(h)
                p = dict(self.config.base_params)
                for name, val in zip(names, combo_vals):
                    p[name] = val
                combos.append(p)

        return self._run_batch(
            combos, progress_cb, stop_flag_fn, already_tested, train_start, train_end)

    # ── Grille progressive (3 passes) ─────────────────────────────────────
    def _run_progressive_grid(self, progress_cb=None, stop_flag_fn=None,
                              already_tested=None, train_start=None, train_end=None) -> list:
        """
        Pass 1 : grille grossière (step × 4)
        Pass 2 : grille fine autour du top 20% de la pass 1
        Pass 3 : (non implémentée automatiquement, déclenchée manuellement)
        """
        all_results = []

        # Pass 1 : step grossier
        coarse_ranges = []
        for pr in self._active_ranges:
            if pr.param_type == "number" and pr.step:
                coarse = ParamRange(
                    name=pr.name, param_type=pr.param_type, label=pr.label,
                    min_val=pr.min_val, max_val=pr.max_val, step=pr.step * 4,
                    enabled=True,
                )
            else:
                coarse = pr
            coarse_ranges.append(coarse)

        orig_ranges = self._active_ranges
        self._active_ranges = [r for r in coarse_ranges if r.enabled]
        pass1_results = self.run_mode3(progress_cb, stop_flag_fn, already_tested, train_start, train_end)
        all_results.extend(pass1_results)

        if stop_flag_fn and stop_flag_fn():
            self._active_ranges = orig_ranges
            return all_results

        # Pass 2 : autour du top 20%
        valid_p1 = [r for r in pass1_results if r["score"] > 0]
        if valid_p1:
            threshold = np.percentile([r["score"] for r in valid_p1], 80)
            top_p1    = [r for r in valid_p1 if r["score"] >= threshold]

            # Raffiner les ranges autour des meilleures zones
            self._active_ranges = orig_ranges
            fine_results = self.run_mode2(top_p1, progress_cb, stop_flag_fn, already_tested, train_start, train_end)
            all_results.extend(fine_results)

        self._active_ranges = orig_ranges
        return all_results

    # ── Run principal ──────────────────────────────────────────────────────
    def run(self, progress_cb: Callable = None, stop_flag_fn: Callable = None,
            already_tested: set = None) -> tuple:
        """
        Lance l'optimisation selon le mode configuré.

        Gère le split train/test si activé.

        Retourne
        --------
        (all_results: list, sensitivity: dict)
        """
        cfg = self.config
        tt  = cfg.train_test

        # ── Calcul des dates de split ──────────────────────────
        train_start = train_end = test_start = test_end = None
        if tt.enabled:
            train_start, train_end, test_start, test_end = compute_split_dates(self.df, tt)

        # ── Phase optimisation ─────────────────────────────────
        mode_fn = {
            "single_var": self.run_mode1,
            "cross_zone": lambda pc, sf, at, ts, te: self.run_mode2(
                [], pc, sf, at, ts, te),  # pas de prior = zones pleines
            "grid":       self.run_mode3,
            "general":    self.run_mode4,
        }.get(cfg.mode, self.run_mode4)

        all_results = mode_fn(
            progress_cb, stop_flag_fn, already_tested or set(),
            train_start, train_end,
        )

        # Tri par score décroissant
        all_results.sort(key=lambda r: r["score"], reverse=True)

        # ── Phase validation (train/test) ──────────────────────
        if tt.enabled and test_start and all_results:
            top_to_validate = [r for r in all_results if r["score"] > 0][:cfg.top_k_save]
            for result in top_to_validate:
                test_result = _run_single(
                    result["params"], cfg, self.df, test_start, test_end)
                result["score_train"]      = result["score"]
                result["score_test"]       = test_result["score"]
                result["stats_test"]       = test_result.get("stats", {})
                denom = result["score_train"] or 1.0
                result["degradation_pct"]  = (
                    (result["score_train"] - result["score_test"]) / denom * 100
                )
                result["overfitting_alert"] = (
                    result["degradation_pct"] > tt.alert_degradation_pct
                )

        # ── Analyse de sensibilité ─────────────────────────────
        sensitivity = {}
        use_correlation = cfg.mode in ("general",)
        best_params = all_results[0]["params"] if all_results else {}

        for pr in self._active_ranges:
            if use_correlation:
                sensitivity[pr.name] = compute_sensitivity_correlation(
                    all_results, pr.name)
            else:
                sensitivity[pr.name] = compute_sensitivity_filtered(
                    all_results, pr.name, best_params)

        return all_results, sensitivity


# ══════════════════════════════════════════════════════════════════════════════
# FONCTION WORKER (picklable pour ProcessPoolExecutor)
# ══════════════════════════════════════════════════════════════════════════════

# DataFrame global partagé par chaque worker process (initialisé une seule fois
# via ProcessPoolExecutor(initializer=_worker_init, initargs=(df,))).
# Évite de recharger le CSV complet (1M lignes) à chaque combinaison.
_worker_df_global = None


def _worker_init(df):
    """
    Initializer pour ProcessPoolExecutor.
    Appelé UNE SEULE FOIS par worker process au démarrage du pool.
    Stocke le DataFrame pré-filtré dans un global de process.
    """
    global _worker_df_global
    _worker_df_global = df


def _worker_run_single(params: dict, config: OptimizationConfig,
                       start_date=None, end_date=None) -> dict:
    """
    Point d'entrée top-level pour ProcessPoolExecutor.
    Doit être au module level pour être picklable sous Windows.

    Utilise _worker_df_global (chargé par _worker_init) si disponible.
    Fallback sur load_data + filtrage si appelé sans initializer.
    """
    global _worker_df_global

    if _worker_df_global is not None:
        # Cas nominal : DataFrame pré-filtré disponible — zéro I/O disque
        df = _worker_df_global
    else:
        # Fallback (appel direct sans initializer, ou n_workers=1 séquentiel)
        import pandas as pd
        from engine import load_data_from_source
        from market_data.adapters.single_file_csv import (
            SingleFileCsvMarketDataSource, PLACEHOLDER_ASSET, PLACEHOLDER_TIMEFRAME,
        )

        # Façade de compatibilité (Data Center Phase 11), même swap que optimizer_process.py —
        # résultat strictement identique à l'ancien load_data(config.data_file), voir
        # tests/test_engine_load_data_from_source.py.
        df = load_data_from_source(
            SingleFileCsvMarketDataSource(config.data_file), PLACEHOLDER_ASSET, PLACEHOLDER_TIMEFRAME
        )

        if config.opt_start_date:
            ts_start = pd.Timestamp(config.opt_start_date, tz="Europe/Paris")
            df = df[df["time_paris"] >= ts_start].reset_index(drop=True)

        if config.opt_end_date:
            ts_end = pd.Timestamp(config.opt_end_date + " 23:59:59", tz="Europe/Paris")
            df = df[df["time_paris"] <= ts_end].reset_index(drop=True)

        if config.max_rows and len(df) > config.max_rows:
            df = df.iloc[:config.max_rows].reset_index(drop=True)

    return _run_single(params, config, df, start_date, end_date)


# ══════════════════════════════════════════════════════════════════════════════
# UTILITAIRES EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

def estimate_duration(n_combinations: int, ms_per_backtest: float, n_workers: int) -> float:
    """Retourne la durée estimée en secondes."""
    if n_workers <= 0:
        n_workers = 1
    return (n_combinations * ms_per_backtest / 1000) / n_workers


def format_duration(seconds: float) -> str:
    """Formate une durée en texte lisible."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s:02d}s"
    else:
        h, rem = divmod(int(seconds), 3600)
        m = rem // 60
        return f"{h}h {m:02d}m"
