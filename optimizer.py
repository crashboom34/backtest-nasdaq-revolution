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
from typing import Optional, Callable, Literal

import numpy as np
import pandas as pd

from scoring import (
    ScoreWeights, FilterConfig,
    compute_score,
    compute_sensitivity_filtered,
    compute_sensitivity_correlation,
)
from strategy_contracts import resolve_state_ready_boundary


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


@dataclass(frozen=True)
class ExecutionWindow:
    """Résultat de `resolve_execution_window()` (Dette A — Optimizer Integration, 2026-09-12).

    Sépare deux notions distinctes, jamais confondues :

    - `context_df` : DataFrame transmis à `engine.run_backtest()` — conserve tout l'historique
      disponible AVANT le début de la sélection d'exécution (warmup causal des indicateurs), mais
      ne contient JAMAIS de barre postérieure à la fin effective de cette sélection (pas de
      look-ahead, même contrat que le moteur — voir `engine.py`, correction Dette A Engine Layer).
    - `execution_df` : la sélection d'exécution EFFECTIVE elle-même, physiquement filtrée
      exactement comme le faisait l'ancien code (`opt_start_date` -> `opt_end_date` -> `max_rows`,
      dans cet ordre). N'est **jamais** transmise à `run_backtest()` ni utilisée pour un vrai
      backtest — sert uniquement de vue de compatibilité pour `compute_split_dates()` (Track
      Optimizer, non modifié par cette mission), afin que ses bornes TRAIN/TEST restent
      identiques à celles qu'il aurait produites sur l'ancien DataFrame physiquement réduit.

    `exec_start`/`exec_end` : bornes ISO-8601 (Europe/Paris) de `execution_df` — à transmettre
    telles quelles à `run_backtest(start_date=, end_date=)` pour tout backtest "période complète,
    sans TRAIN/TEST" (voir `Optimizer.run()`). `None` si `execution_df` est vide (sélection
    entièrement hors du dataset — dégradation gracieuse, jamais une exception).

    `exec_row_count` : `len(execution_df)` — jamais `len(context_df)`. C'est cette valeur, et
    elle seule, qui doit être exposée dans les métriques/manifests décrivant "les données
    utilisées pour la période optimisée" (voir `Optimizer.df_rows_used`)."""

    context_df: "pd.DataFrame"
    execution_df: "pd.DataFrame"
    exec_start: Optional[str]
    exec_end: Optional[str]
    exec_row_count: int


def resolve_execution_window(
    df, opt_start_date: Optional[str] = None, opt_end_date: Optional[str] = None,
    max_rows: Optional[int] = None,
) -> ExecutionWindow:
    """Fonction PURE (Dette A — Optimizer Integration) : résout, à partir du DataFrame source
    complet et de la période demandée, la séparation contexte/exécution nécessaire au moteur
    corrigé (`engine.run_backtest()`, Dette A Engine Layer). Point d'extension UNIQUE — réutilisée
    par le chemin nominal (`Optimizer.__init__`), `benchmark_speed()` et le fallback
    (`_worker_run_single()`) : jamais une seconde implémentation de ce filtrage.

    Reproduit EXACTEMENT l'ancien filtrage physique (`opt_start_date` -> `opt_end_date` ->
    `max_rows`, dans cet ordre — voir docstring de `ExecutionWindow`) pour calculer
    `execution_df`/`exec_row_count` : la période réellement optimisée ne change pas d'un seul
    timestamp par rapport au comportement historique. `context_df` ajoute ensuite l'historique
    amont disponible (jamais retiré), tout en supprimant strictement tout ce qui suit la dernière
    barre de `execution_df` (pas de futur visible par `strategy.prepare()`, même invariant que
    l'Engine Layer)."""
    execution_df = df
    if opt_start_date:
        ts_start = pd.Timestamp(opt_start_date, tz="Europe/Paris")
        execution_df = execution_df[execution_df["time_paris"] >= ts_start].reset_index(drop=True)
    if opt_end_date:
        ts_end = pd.Timestamp(opt_end_date + " 23:59:59", tz="Europe/Paris")
        execution_df = execution_df[execution_df["time_paris"] <= ts_end].reset_index(drop=True)
    if max_rows and len(execution_df) > max_rows:
        execution_df = execution_df.iloc[:max_rows].reset_index(drop=True)

    exec_row_count = len(execution_df)
    if exec_row_count > 0:
        exec_start = execution_df["time_paris"].iloc[0].strftime("%Y-%m-%dT%H:%M:%S")
        exec_end   = execution_df["time_paris"].iloc[-1].strftime("%Y-%m-%dT%H:%M:%S")
        # Contexte : tout l'historique du df source jusqu'à la dernière barre EFFECTIVEMENT
        # sélectionnée (pas jusqu'à opt_end_date brut — si max_rows termine la sélection plus tôt,
        # c'est cette borne réelle, plus précoce, qui fixe la fin du contexte, voir docstring).
        last_ts    = execution_df["time_paris"].iloc[-1]
        context_df = df[df["time_paris"] <= last_ts].reset_index(drop=True)
    else:
        # Sélection vide (start après toutes les données, end avant, etc.) : dégradation
        # gracieuse identique au comportement historique (0 ligne -> 0 trade, jamais de crash) —
        # aucun contexte n'est nécessaire puisqu'il n'y a rien à exécuter.
        exec_start = None
        exec_end   = None
        context_df = execution_df

    return ExecutionWindow(
        context_df=context_df,
        execution_df=execution_df,
        exec_start=exec_start,
        exec_end=exec_end,
        exec_row_count=exec_row_count,
    )


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
                df, start_date=None, end_date=None,
                end_boundary: Literal["inclusive", "exclusive"] = "inclusive") -> dict:
    """
    Lance un backtest unique et retourne le résultat scoré.
    Fonction top-level pour être picklable dans ProcessPoolExecutor.

    `end_boundary` (correction scientifique du split TRAIN/TEST, 2026-09-12) : transmis tel quel
    à `engine.run_backtest()` — `"inclusive"` (défaut, comportement historique) pour tout appel
    sans train/test ou pour la phase TEST ; `"exclusive"` pour la phase TRAIN uniquement (voir
    `Optimizer.run()`, `_TRAIN_END_BOUNDARY`/`_TEST_END_BOUNDARY`).

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
            end_boundary=end_boundary,
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

def benchmark_speed(
    config: OptimizationConfig, df, n_sample: int = 20,
    execution_window: Optional[ExecutionWindow] = None,
) -> float:
    """
    Lance n_sample backtests avec les paramètres de base.
    Retourne le temps médian en millisecondes par backtest.

    Dette A (Optimizer Integration) : benchmarke désormais le CONTEXTE réellement transmis à
    `run_backtest()` (historique amont compris) borné aux dates d'exécution effectives, pas tout
    le contexte sans bornes — l'estimation reste représentative du vrai coût d'un backtest réel
    (qui inclut, lui aussi, le balayage de cet historique par `strategy.prepare()`). `df` est le
    DataFrame SOURCE (non filtré) ; `execution_window` évite de recalculer la résolution si
    l'appelant l'a déjà fait (voir `optimizer_process.py`)."""
    from engine import run_backtest

    window = execution_window or resolve_execution_window(
        df, config.opt_start_date, config.opt_end_date, config.max_rows)

    mod, strat = _load_strategy(config.strategy_module)
    gp = config.global_params
    times = []

    for _ in range(n_sample):
        t0 = time.perf_counter()
        try:
            strat.reset()
            run_backtest(
                window.context_df, strat, config.base_params,
                initial_capital=gp.get("initial_capital", 10_000.0),
                spread=gp.get("spread", 1.0),
                slip_in=gp.get("slip_in", 0.5),
                slip_out=gp.get("slip_out", 0.5),
                start_date=window.exec_start,
                end_date=window.exec_end,
            )
        except Exception:
            pass
        times.append((time.perf_counter() - t0) * 1000)

    return statistics.median(times) if times else 500.0


# ══════════════════════════════════════════════════════════════════════════════
# CALCUL DES FENÊTRES DE SPLIT TRAIN / TEST (correction scientifique, 2026-09-12)
# ══════════════════════════════════════════════════════════════════════════════
#
# Écart historique corrigé ici (audit read-only préalable) : l'ancienne version tronquait
# train_end/test_start/test_end en chaîne "YYYY-MM-DD" (perte totale de l'heure), puis
# `engine.run_backtest()` interprétait ces dates en filtrage FERMÉ sur des timestamps minuit —
# créant un trou temporel silencieux d'au moins une journée de marché autour du split (quantifié
# empiriquement : jusqu'à 28.6% de barres perdues sur un exemple synthétique 7 jours), sans
# jamais lever d'erreur. Cette correction élimine à la fois la perte de précision ET le trou.

# Sémantique de frontière transmise à engine.run_backtest() — TRAIN s'arrête juste AVANT
# `boundary` (jamais la barre pile dessus), TEST commence PILE sur `boundary` (inclus) : la
# barre exactement à `boundary` appartient donc TOUJOURS à TEST, jamais aux deux, jamais à
# aucune. Constantes nommées pour éviter de disperser les littéraux "exclusive"/"inclusive" à
# travers la dizaine de signatures qui les relaient, sans introduire de nouvelle abstraction.
_TRAIN_END_BOUNDARY: Literal["exclusive"] = "exclusive"
_TEST_END_BOUNDARY:  Literal["inclusive"] = "inclusive"

# Identifie la sémantique exacte du contrat TRAIN/TEST produit par compute_split_dates() —
# distincte du `git_commit` déjà capturé automatiquement par ailleurs (data_manifest.json,
# market_data/backtest_manifest.py) : `git_commit` identifie le LOGICIEL exact, cette constante
# identifie le CONTRAT SCIENTIFIQUE train/test (indépendant, en principe, du reste du logiciel).
# Incrémenter uniquement si la sémantique TRAIN/TEST elle-même change à nouveau (jamais pour un
# changement de code sans impact sur les bornes produites) — voir validate_resume_train_test_
# semantics() et docs/adr/0018-*.md pour la garde de reprise cross-version associée.
TRAIN_TEST_SEMANTICS_VERSION = "exact-boundary-v2"


@dataclass(frozen=True)
class TrainTestWindows:
    """Fenêtres TRAIN/TEST résolues par `compute_split_dates()` — remplace l'ancien tuple
    `(train_start, train_end, test_start, test_end)` (4 chaînes "YYYY-MM-DD", ambiguïté
    d'inclusivité implicite, précision horaire perdue).

    Invariant UNIQUE, jamais deux valeurs indépendantes pouvant diverger : la même `boundary`
    est à la fois la fin EXCLUSIVE de TRAIN et le début INCLUSIF de TEST —

        TRAIN = [train_start, boundary)
        TEST  = [boundary,    test_end]

    Une bougie exactement à `boundary` appartient donc TOUJOURS à TEST, jamais aux deux, jamais
    à aucune (aucune barre perdue, aucune barre dupliquée entre TRAIN et TEST — la mécanique
    d'exclusion/inclusion elle-même est déjà garantie par le moteur, voir
    `engine.run_backtest(end_boundary=)`, Dette B, et son test `TestEndBoundarySemantics::
    test_b4_two_adjacent_windows_never_double_include_the_boundary_bar`).

    Les trois champs sont des chaînes ISO-8601 complètes (`.isoformat()` — offset ET fraction de
    seconde préservés, jamais tronqués à une date), acceptées telles quelles par
    `engine.run_backtest(start_date=, end_date=)` (voir `engine._parse_boundary_timestamp()`).
    `train_start`/`test_end` proviennent des bornes RÉELLES de `execution_df` (jamais une valeur
    fictive au-delà de la dernière barre effective)."""

    train_start: str
    boundary: str
    test_end: str


class TrainTestSemanticsMismatch(ValueError):
    """Levée quand un job repris (`resume_run_id`) a été créé sous une sémantique train/test
    différente de `TRAIN_TEST_SEMANTICS_VERSION` courante (absente = "legacy", antérieure à cette
    correction). Jamais un mélange silencieux de scores TRAIN/TEST calculés sous deux contrats
    différents — voir `validate_resume_train_test_semantics()`."""


def validate_resume_train_test_semantics(
    current_train_test: TrainTestConfig,
    source_config: Optional[dict],
    source_run_id: str,
) -> None:
    """Garde de reprise cross-version (mission §19-20, correction scientifique du split
    TRAIN/TEST). Ne s'applique QUE si le run COURANT active train/test — une reprise sans
    train/test n'est jamais bloquée par cette dette, quelle que soit la source.

    `source_config` : dict brut tel que chargé par `optimization_store.load_config()` pour le
    job source (`None` si introuvable/non chargé — traité comme "legacy", jamais silencieusement
    ignoré). Lève `TrainTestSemanticsMismatch` si la version de sémantique train/test du job
    source ne correspond pas EXACTEMENT à `TRAIN_TEST_SEMANTICS_VERSION` — y compris quand le
    champ est absent (job antérieur à cette correction)."""
    if not current_train_test.enabled:
        return
    source_version = (source_config or {}).get("train_test_semantics_version")
    if source_version != TRAIN_TEST_SEMANTICS_VERSION:
        raise TrainTestSemanticsMismatch(
            f"Reprise refusée : le job source {source_run_id!r} utilise la sémantique "
            f"train/test {source_version!r} (legacy si absente), incompatible avec la version "
            f"courante {TRAIN_TEST_SEMANTICS_VERSION!r}. Mélanger, au sein d'un même run repris, "
            "des scores TRAIN/TEST calculés sous deux contrats de frontière différents "
            "produirait des métriques scientifiquement incohérentes. Relancer un nouveau run "
            "sans resume_run_id plutôt que de reprendre ce job source."
        )


# Identifie la sémantique de la POLITIQUE de readiness d'état (State/Session Readiness, V1,
# 2026-09-14) — INDÉPENDANTE de TRAIN_TEST_SEMANTICS_VERSION : `exact-boundary-v2` décrit la
# géométrie temporelle TRAIN/TEST (compute_split_dates(), inchangée par cette mission) ;
# STATE_READINESS_SEMANTICS_VERSION décrit l'ajustement strategy-aware appliqué AU-DESSUS de
# cette géométrie. Deux contrats distincts, deux versions distinctes — ne jamais les fusionner
# (voir docs/adr à venir).
STATE_READINESS_SEMANTICS_VERSION = "daily-state-ready-v1"


class NoStateReadyBoundary(ValueError):
    """Levée quand aucune frontière effective ne peut satisfaire à la fois la readiness d'état
    déclarée par la stratégie ET `train_start < effective_boundary < test_end` — jamais une
    fenêtre TEST vide ou un repli silencieux vers `requested_boundary`."""


class StateReadinessSemanticsMismatch(ValueError):
    """Levée quand un job repris a été créé sous une politique de readiness différente de
    `STATE_READINESS_SEMANTICS_VERSION` courante (absente = "legacy", antérieure à cette
    mission) — jamais un mélange silencieux de scores calculés sous deux contrats de readiness
    différents. Contrat séparé de `TrainTestSemanticsMismatch` (voir constante ci-dessus)."""


def validate_resume_state_readiness_semantics(
    current_is_readiness_aware: bool,
    source_config: Optional[dict],
    source_run_id: str,
) -> None:
    """Garde de reprise cross-version dédiée à la readiness (State/Session Readiness V1,
    2026-09-14) — mirroring exact de `validate_resume_train_test_semantics()`.

    `current_is_readiness_aware` : `True` uniquement si le run COURANT active train/test ET que
    la stratégie chargée expose `state_readiness()` — une reprise sans train/test, ou avec une
    stratégie stateless, n'est JAMAIS bloquée par cette garde, quelle que soit la source."""
    if not current_is_readiness_aware:
        return
    source_version = (source_config or {}).get("state_readiness_semantics_version")
    if source_version != STATE_READINESS_SEMANTICS_VERSION:
        raise StateReadinessSemanticsMismatch(
            f"Reprise refusée : le job source {source_run_id!r} utilise la politique de "
            f"readiness d'état {source_version!r} (legacy si absente), incompatible avec la "
            f"version courante {STATE_READINESS_SEMANTICS_VERSION!r}. Mélanger, au sein d'un "
            "même run repris, des frontières TRAIN/TEST résolues sous deux politiques de "
            "readiness différentes produirait des métriques scientifiquement incohérentes. "
            "Relancer un nouveau run sans resume_run_id plutôt que de reprendre ce job source."
        )


def compute_split_dates(df, train_test: TrainTestConfig) -> TrainTestWindows:
    """Résout les fenêtres TRAIN/TEST à partir de la sélection d'exécution (`df` =
    `execution_df`, jamais le contexte élargi — comportement de sélection inchangé, voir
    `Optimizer.run()`).

    TRAIN = [train_start, boundary) exclusive ; TEST = [boundary, test_end] inclusive.

    Méthode "ratio" (par défaut) : `boundary` = ratio de DURÉE TEMPORELLE (jamais un ratio du
    nombre de barres) — `train_ratio` doit être strictement dans `]0, 1[`, sinon `ValueError`
    explicite (jamais une fenêtre TRAIN ou TEST vide masquée derrière une valeur limite).

    Méthode "date" : `split_date` est la date du PREMIER jour de TEST (décision D1, 2026-09-12 —
    généralisation cohérente avec la méthode ratio, PAS une restauration certaine de l'intention
    historique du code — voir docs/adr/0018-*.md). `boundary` = minuit Europe/Paris de cette
    date. `split_date` est obligatoire pour cette méthode : `ValueError` explicite s'il est
    absent, plutôt que l'ancien repli silencieux vers la méthode ratio.

    Validation stricte, dans tous les cas : `global_start < boundary < global_end` — une
    configuration incapable de produire deux régions temporelles non vides (dataset vide, une
    seule barre, `boundary` hors période ou confondu avec une extrémité) lève `ValueError`,
    jamais une fenêtre vide silencieuse. Le chemin SANS train/test (`Optimizer.run()` quand
    `train_test.enabled` est faux) n'appelle jamais cette fonction et reste inchangé, tolérant
    aux sélections vides."""
    times = df["time_paris"]
    if times.empty:
        raise ValueError(
            "compute_split_dates() : sélection vide — impossible de calculer un split "
            "train/test sur un DataFrame sans aucune barre."
        )
    global_start = times.min()
    global_end   = times.max()

    if train_test.split_method == "date":
        if not train_test.split_date:
            raise ValueError(
                "compute_split_dates() : split_method='date' exige train_test.split_date — "
                "jamais de repli silencieux vers la méthode 'ratio'."
            )
        boundary = pd.Timestamp(train_test.split_date, tz="Europe/Paris")
    else:
        if not (0 < train_test.train_ratio < 1):
            raise ValueError(
                f"compute_split_dates() : train_ratio={train_test.train_ratio!r} invalide — "
                "doit être strictement compris entre 0 et 1 (ratio de durée temporelle, jamais "
                "de ratio de barres). Une valeur <= 0 ou >= 1 produirait une fenêtre TRAIN ou "
                "TEST entièrement vide, jamais masquée silencieusement ici."
            )
        duration = (global_end - global_start).total_seconds()
        boundary = global_start + pd.Timedelta(seconds=duration * train_test.train_ratio)

    if not (global_start < boundary < global_end):
        raise ValueError(
            f"compute_split_dates() : boundary={boundary!r} doit être strictement compris "
            f"entre global_start={global_start!r} et global_end={global_end!r} — un dataset "
            "vide, insuffisant (une seule barre) ou une frontière confondue avec l'une des "
            "extrémités ne peut pas produire deux régions TRAIN/TEST non vides."
        )

    return TrainTestWindows(
        train_start=global_start.isoformat(),
        boundary=boundary.isoformat(),
        test_end=global_end.isoformat(),
    )


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

    def __init__(self, config: OptimizationConfig, df, execution_window: Optional[ExecutionWindow] = None):
        """`df` : DataFrame SOURCE (non filtré) — la séparation contexte/exécution (Dette A,
        Optimizer Integration) est résolue ici via `resolve_execution_window()` si
        `execution_window` n'est pas déjà fourni (évite une résolution redondante quand
        `optimizer_process.py` l'a déjà calculée pour `df_rows_used`/le logging).

        `self.df` devient le CONTEXTE élargi (historique amont conservé, jamais de futur au-delà
        de la fin effective) — c'est ce DataFrame, et lui seul, qui est transmis aux workers/
        `_run_single()`. `self.df_rows_used` reste la sélection d'EXÉCUTION effective (jamais la
        taille du contexte élargi) — voir docstring de `ExecutionWindow`."""
        window = execution_window or resolve_execution_window(
            df, config.opt_start_date, config.opt_end_date, config.max_rows)
        self.config = config
        self.df     = window.context_df
        self._execution_df = window.execution_df
        self._exec_start   = window.exec_start
        self._exec_end     = window.exec_end
        self.df_rows_used  = window.exec_row_count
        # Fenêtre TRAIN/TEST réellement résolue par compute_split_dates() (correction
        # scientifique du split, 2026-09-12) — None tant que run() ne l'a pas calculée, ou si
        # train/test n'est pas activé. Exposée pour permettre à optimizer_process.py de la
        # persister dans meta.json (voir job_store/build_meta) sans changer le contrat de
        # retour de run() (tuple (all_results, sensitivity) inchangé).
        self.resolved_train_test_windows: Optional[TrainTestWindows] = None
        # Résolution de readiness d'état (State/Session Readiness V1, 2026-09-14) — None tant
        # que run() ne l'a pas calculée, si train/test n'est pas activé, ou si la stratégie
        # n'expose pas state_readiness() (stateless, jamais bloquée par cette dette).
        self.state_readiness_resolution = None
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
                              start_date=None, end_date=None,
                              end_boundary: Literal["inclusive", "exclusive"] = "inclusive") -> list:
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

            result = _run_single(params, self.config, self.df, start_date, end_date, end_boundary)
            results.append(result)

            if progress_cb:
                progress_cb(idx + 1, total, result)

        return results

    # ── Exécution parallèle (ProcessPoolExecutor) ──────────────────────────
    def _run_batch_parallel(self, combos: list,
                            progress_cb: Callable = None,
                            stop_flag_fn: Callable = None,
                            already_tested: set = None,
                            start_date=None, end_date=None,
                            end_boundary: Literal["inclusive", "exclusive"] = "inclusive") -> list:
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
                    end_boundary,
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
                   already_tested=None, start_date=None, end_date=None,
                   end_boundary: Literal["inclusive", "exclusive"] = "inclusive"):
        """Dispatche vers séquentiel ou parallèle selon n_workers."""
        combos = self._apply_max_combinations(combos)
        if not combos:
            return []
        if self.config.n_workers <= 1:
            return self._run_batch_sequential(
                combos, progress_cb, stop_flag_fn, already_tested, start_date, end_date,
                end_boundary)
        else:
            return self._run_batch_parallel(
                combos, progress_cb, stop_flag_fn, already_tested, start_date, end_date,
                end_boundary)

    # ── Mode 1 : Variable par variable ────────────────────────────────────
    def run_mode1(self, progress_cb=None, stop_flag_fn=None,
                  already_tested=None, train_start=None, train_end=None,
                  end_boundary: Literal["inclusive", "exclusive"] = "inclusive") -> list:
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
                combos, progress_cb, stop_flag_fn, already_tested, train_start, train_end,
                end_boundary)
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
                  already_tested=None, train_start=None, train_end=None,
                  end_boundary: Literal["inclusive", "exclusive"] = "inclusive") -> list:
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
            combos, progress_cb, stop_flag_fn, already_tested, train_start, train_end,
            end_boundary)

    # ── Mode 3 : Grille complète ───────────────────────────────────────────
    def run_mode3(self, progress_cb=None, stop_flag_fn=None,
                  already_tested=None, train_start=None, train_end=None,
                  end_boundary: Literal["inclusive", "exclusive"] = "inclusive") -> list:
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
            combos, progress_cb, stop_flag_fn, already_tested, train_start, train_end,
            end_boundary)

    # ── Mode 4 : Optimisation générale intelligente ────────────────────────
    def run_mode4(self, progress_cb=None, stop_flag_fn=None,
                  already_tested=None, train_start=None, train_end=None,
                  end_boundary: Literal["inclusive", "exclusive"] = "inclusive") -> list:
        """
        Sélectionne automatiquement la méthode selon N_combinations :
        - N ≤ 50 000 : grille complète
        - 50 000 < N ≤ 500 000 : échantillonnage stratifié (50 000 tirages)
        - N > 500 000 : grille progressive 3 passes
        """
        n_total = count_combinations(self._active_ranges)

        if self._max_combinations is not None:
            return self.run_mode3(
                progress_cb, stop_flag_fn, already_tested, train_start, train_end, end_boundary)

        if n_total <= 50_000:
            return self.run_mode3(
                progress_cb, stop_flag_fn, already_tested, train_start, train_end, end_boundary)

        elif n_total <= 500_000:
            return self._run_stratified_sample(
                50_000, progress_cb, stop_flag_fn, already_tested, train_start, train_end,
                end_boundary)

        else:
            return self._run_progressive_grid(
                progress_cb, stop_flag_fn, already_tested, train_start, train_end, end_boundary)

    # ── Échantillonnage stratifié ─────────────────────────────────────────
    def _run_stratified_sample(self, n_sample: int,
                               progress_cb=None, stop_flag_fn=None,
                               already_tested=None, train_start=None, train_end=None,
                               end_boundary: Literal["inclusive", "exclusive"] = "inclusive") -> list:
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
            combos, progress_cb, stop_flag_fn, already_tested, train_start, train_end,
            end_boundary)

    # ── Grille progressive (3 passes) ─────────────────────────────────────
    def _run_progressive_grid(self, progress_cb=None, stop_flag_fn=None,
                              already_tested=None, train_start=None, train_end=None,
                              end_boundary: Literal["inclusive", "exclusive"] = "inclusive") -> list:
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
        pass1_results = self.run_mode3(
            progress_cb, stop_flag_fn, already_tested, train_start, train_end, end_boundary)
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
            fine_results = self.run_mode2(
                top_p1, progress_cb, stop_flag_fn, already_tested, train_start, train_end,
                end_boundary)
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

        # ── Calcul des fenêtres de split (correction scientifique, 2026-09-12) ──
        train_start = train_end = None
        end_boundary_for_optimization: Literal["inclusive", "exclusive"] = _TEST_END_BOUNDARY
        if tt.enabled:
            # compute_split_dates() voit la sélection d'EXÉCUTION (self._execution_df), jamais
            # self.df (le contexte élargi, qui déplacerait global_start vers l'historique amont
            # et fausserait le ratio train/test) — comportement de sélection hérité de Dette A,
            # inchangé par cette correction.
            windows = compute_split_dates(self._execution_df, tt)

            # ── State/Session Readiness V1 (2026-09-14) — étape SÉPARÉE, APRÈS
            # compute_split_dates(), jamais dedans (compute_split_dates() reste inchangé,
            # géométrie temporelle générique). La stratégie DÉCLARE (state_readiness(params)),
            # ce protocole RÉSOUT (resolve_state_ready_boundary(), pur, sans DataFrame) —
            # architecture READY-3, voir strategy_contracts.py. Stateless (pas de
            # state_readiness()) -> aucun ajustement, comportement identique à avant cette
            # mission.
            _mod, _strat_for_readiness = _load_strategy(cfg.strategy_module)
            readiness_spec = (
                _strat_for_readiness.state_readiness(cfg.base_params)
                if hasattr(_strat_for_readiness, "state_readiness") else None
            )
            resolution = resolve_state_ready_boundary(windows.boundary, readiness_spec)
            self.state_readiness_resolution = resolution if readiness_spec is not None else None

            # Validation stricte sur les INSTANTS réels (jamais une comparaison de chaînes ISO —
            # piège offset/DST déjà documenté), jamais un fallback silencieux ni une fenêtre
            # TEST vide.
            ts_train_start = pd.Timestamp(windows.train_start)
            ts_effective    = pd.Timestamp(resolution.effective_boundary)
            ts_test_end     = pd.Timestamp(windows.test_end)
            if not (ts_train_start < ts_effective < ts_test_end):
                raise NoStateReadyBoundary(
                    f"Aucune frontière effective ne satisfait à la fois la readiness d'état "
                    f"déclarée par la stratégie et train_start < effective_boundary < test_end "
                    f"(train_start={windows.train_start!r}, "
                    f"effective_boundary={resolution.effective_boundary!r} "
                    f"[requested={resolution.requested_boundary!r}], "
                    f"test_end={windows.test_end!r}). Jamais une fenêtre TEST vide ou un repli "
                    "silencieux vers la frontière demandée."
                )

            windows = TrainTestWindows(
                train_start=windows.train_start,
                boundary=resolution.effective_boundary,
                test_end=windows.test_end,
            )
            self.resolved_train_test_windows = windows
            train_start = windows.train_start
            train_end   = windows.boundary
            # TRAIN=[train_start, boundary) — la barre à `boundary` n'influence jamais TRAIN,
            # elle appartient exclusivement à TEST (voir TrainTestWindows, docs/adr/0018-*.md).
            end_boundary_for_optimization = _TRAIN_END_BOUNDARY
        else:
            # Sans train/test, self.df est le CONTEXTE élargi (historique amont compris) — un
            # backtest sans bornes explicites exécuterait alors sur tout ce contexte, y compris
            # avant la période demandée. Borner explicitement à la sélection d'exécution
            # effective (jamais (None, None) implicite) — comportement historique inchangé,
            # `end_boundary` reste "inclusive" (défaut).
            train_start, train_end = self._exec_start, self._exec_end

        # ── Phase optimisation ─────────────────────────────────
        mode_fn = {
            "single_var": self.run_mode1,
            "cross_zone": lambda pc, sf, at, ts, te, eb: self.run_mode2(
                [], pc, sf, at, ts, te, eb),  # pas de prior = zones pleines
            "grid":       self.run_mode3,
            "general":    self.run_mode4,
        }.get(cfg.mode, self.run_mode4)

        all_results = mode_fn(
            progress_cb, stop_flag_fn, already_tested or set(),
            train_start, train_end, end_boundary_for_optimization,
        )

        # Tri par score décroissant
        all_results.sort(key=lambda r: r["score"], reverse=True)

        # ── Phase validation (train/test) ──────────────────────
        if tt.enabled and all_results:
            windows = self.resolved_train_test_windows
            top_to_validate = [r for r in all_results if r["score"] > 0][:cfg.top_k_save]
            for result in top_to_validate:
                # TEST=[boundary, test_end] — début INCLUSIF explicite (même si c'est le défaut
                # de engine.run_backtest(), l'expliciter ici rend le contrat visible dans le
                # diff, conformément à la mission).
                test_result = _run_single(
                    result["params"], cfg, self.df, windows.boundary, windows.test_end,
                    end_boundary=_TEST_END_BOUNDARY,
                )
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
                       start_date=None, end_date=None,
                       end_boundary: Literal["inclusive", "exclusive"] = "inclusive") -> dict:
    """
    Point d'entrée top-level pour ProcessPoolExecutor.
    Doit être au module level pour être picklable sous Windows.

    Utilise _worker_df_global (chargé par _worker_init) si disponible.
    Fallback sur load_data + filtrage si appelé sans initializer.

    `end_boundary` : même contrat que `_run_single()`, transmis identiquement sur le chemin
    nominal ET le fallback (jamais une seconde sémantique de filtrage — correction scientifique
    du split TRAIN/TEST, 2026-09-12).
    """
    global _worker_df_global

    if _worker_df_global is not None:
        # Cas nominal : DataFrame de CONTEXTE (Dette A) pré-résolu disponible — zéro I/O disque
        df = _worker_df_global
    else:
        # Fallback (appel direct sans initializer, ou n_workers=1 séquentiel)
        from engine import load_data_from_source
        from market_data.adapters.single_file_csv import (
            SingleFileCsvMarketDataSource, PLACEHOLDER_ASSET, PLACEHOLDER_TIMEFRAME,
        )

        # Façade de compatibilité (Data Center Phase 11), même swap que optimizer_process.py —
        # résultat strictement identique à l'ancien load_data(config.data_file), voir
        # tests/test_engine_load_data_from_source.py.
        raw_df = load_data_from_source(
            SingleFileCsvMarketDataSource(config.data_file), PLACEHOLDER_ASSET, PLACEHOLDER_TIMEFRAME
        )

        # Dette A (Optimizer Integration) : MÊME resolver que le chemin nominal
        # (Optimizer.__init__/optimizer_process.py) — jamais une seconde implémentation de ce
        # filtrage qui pourrait diverger plus tard. Produit le CONTEXTE élargi (historique amont
        # conservé, aucun futur au-delà de la fin effective), pas le DataFrame physiquement
        # réduit à la période demandée.
        df = resolve_execution_window(
            raw_df, config.opt_start_date, config.opt_end_date, config.max_rows
        ).context_df

    return _run_single(params, config, df, start_date, end_date, end_boundary)


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
