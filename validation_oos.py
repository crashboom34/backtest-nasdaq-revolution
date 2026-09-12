"""
validation_oos.py — Orchestration de la première ValidationRun OOS réelle (AF-V-01).

Le SEUL module autorisé à connaître à la fois le moteur (`engine.py`) et la persistance Track R/V
(`research_run.py`/`dataset_split.py`/`validation_run.py`) — voir `/codebase-design`. Relie :

    DatasetSplitPlan.FINAL_HOLDOUT → engine.run_backtest() → OosValidationEvidence
    → ValidationRun + HoldoutAccessEvent

`run_oos_validation()` est une fonction **pure** : reçoit `run_backtest_fn` en paramètre (jamais un
import direct de `engine.py` — testable avec un faux moteur synthétique, sans `nasdaq_3m.csv`),
retourne des **valeurs** (`ValidationRun`, `HoldoutAccessEvent`), ne persiste rien elle-même. La
persistance (où écrire les fichiers) reste la responsabilité de l'appelant réel (script
d'exécution, hors de ce module) — cohérent avec `research_run.py`/`dataset_split.py`, qui ne
résolvent jamais de répertoire eux-mêmes.

**Invariant central (mission AF-V-01 §6), PORTÉE STRICTEMENT LIMITÉE À CE CODE** : `run_oos_validation()`
elle-même ne consulte le `FINAL_HOLDOUT` qu'une seule fois, ici, à cet instant précis — aucun chemin
de code dans CE module ne le consulte avant ou ne le rappelle après avoir vu un résultat (aucun
sweep/tuning possible par construction). **Cette garantie NE dit RIEN sur l'historique du système
en dehors de ce code.** Correctif AF-V-01 (`/domain-modeling`, 2026-08-15, voir
`docs/architecture/DOMAIN_MODEL.md` §12 "Search History Leakage confirmé sur un cas réel") : une
exécution antérieure et indépendante (`GATE DATA`, avant ce ticket) a backtesté le `nasdaq_3m.csv`
**complet** avec la même stratégie/`DEFAULT_PARAMS`, produisant des trades individuellement datés
À L'INTÉRIEUR de la fenêtre calendaire qu'un `DatasetSplitPlan` ultérieur pourrait désigner
`FINAL_HOLDOUT`. **Une `ValidationRun` construite produite par cette fonction ne peut donc jamais être
qualifiée "final holdout untouched"/"jamais consultée" sans vérifier au préalable, HORS de ce
module, l'historique complet des exécutions antérieures sur ce même `dataset_snapshot_id`** — cette
vérification n'est PAS automatisée ici (voir DOMAIN_MODEL.md §12 pour pourquoi : absence de
`HoldoutAccessEvent` historique n'est jamais une preuve d'absence d'accès). Elle reste une evidence
honnête ("comment cette configuration se comporte sur cette période"), qualifiée au minimum
*retrospective OOS evidence* tant que cette vérification externe n'a pas positivement écarté toute
exposition antérieure. `start_date`/`end_date` transmis à `run_backtest_fn` correspondent EXACTEMENT
(mêmes valeurs, sans transformation) aux bornes `split_plan.final_holdout` — "exactement" porte sur
les VALEURS transmises, pas sur la sémantique d'inclusion appliquée ensuite par le moteur, voir
`dataset_split.py::SplitBoundary` pour l'écart confirmé (intervalle fermé côté
`engine.run_backtest`, sans impact constaté ici).

**`HoldoutAccessEvent` créé APRÈS l'exécution** (mission §10) : l'accès est constaté une fois que
`run_backtest_fn` est revenu avec succès — même si `n_trades == 0` (l'accès a réellement eu lieu,
un résultat vide n'est pas une absence d'accès). Si `run_backtest_fn` lève une exception, aucun
`ValidationRun`/`HoldoutAccessEvent` n'est produit — l'exception se propage telle quelle, pas
d'état partiel.

**Ne réutilise PAS le split train/test existant** (`optimizer.py::TrainTestConfig`) — utilise
directement les bornes `[start, end)` du `DatasetSplitPlan.FINAL_HOLDOUT` réel (Track R), passées
à `engine.run_backtest(start_date=..., end_date=...)` exactement comme le fait déjà
`optimizer.py::_run_single()` pour la période de test existante (même mécanisme de filtrage
interne déjà établi dans `engine.py`, aucune réinvention).

**AF-V-06 (2026-09-12)** : construit désormais aussi une `OosValidationSpecification` (les bornes
`FINAL_HOLDOUT` ciblées, avant exécution) en plus de l'`OosValidationEvidence` existante (ce qui a
été observé) — voir `validation_run.py` pour le contrat typé complet. Aucun changement de
signature, de sémantique `HoldoutAccessEvent`, ni du nombre d'accès au holdout (toujours
exactement un).
"""

from __future__ import annotations

from typing import Callable, Tuple

from dataset_split import DatasetSplitPlan, HoldoutAccessEvent, build_holdout_access_event
from validation_run import (
    ValidationRun,
    build_oos_validation_evidence,
    build_oos_validation_specification,
    build_validation_run,
)


def run_oos_validation(
    df,
    strategy,
    params: dict,
    split_plan: DatasetSplitPlan,
    research_run_id: str,
    validation_run_id: str,
    strategy_name: str,
    reason: str,
    run_backtest_fn: Callable,
) -> Tuple[ValidationRun, HoldoutAccessEvent]:
    """Exécute la première (et unique) évaluation OOS sur `split_plan.final_holdout`, construit
    et retourne `(ValidationRun, HoldoutAccessEvent)` — ne persiste rien.

    `run_backtest_fn` : callable compatible `engine.run_backtest(df, strategy, params,
    start_date=..., end_date=..., **kwargs) -> (trades_df, equity_df, stats_dict)` — injecté,
    jamais importé directement (voir docstring du module). `stats_dict` doit exposer au minimum
    `n_trades`/`net_ret_pct` ; `profit_factor`/`win_rate`/`max_dd_pct` restent absents (-> `None`)
    quand `n_trades == 0`, comme le fait réellement `engine.py::_compute_stats()`.
    """
    holdout = split_plan.final_holdout

    _trades_df, _equity_df, stats = run_backtest_fn(
        df, strategy, params, start_date=holdout.start, end_date=holdout.end,
    )

    specification = build_oos_validation_specification(
        holdout_start=holdout.start,
        holdout_end=holdout.end,
    )

    evidence = build_oos_validation_evidence(
        period_start=holdout.start,
        period_end=holdout.end,
        n_trades=stats.get("n_trades", 0),
        net_ret_pct=stats.get("net_ret_pct", 0.0),
        profit_factor=stats.get("profit_factor"),
        win_rate=stats.get("win_rate"),
        max_dd_pct=stats.get("max_dd_pct"),
    )

    validation_run = build_validation_run(
        validation_run_id=validation_run_id,
        research_run_id=research_run_id,
        split_plan_id=split_plan.split_plan_id,
        dataset_snapshot_id=split_plan.dataset_snapshot_id,
        strategy_name=strategy_name,
        strategy_params=dict(params),
        specification=specification,
        evidence=evidence,
    )

    # Créé APRÈS le retour de run_backtest_fn : l'accès est constaté, jamais anticipé.
    event = build_holdout_access_event(
        split_plan_id=split_plan.split_plan_id,
        dataset_snapshot_id=split_plan.dataset_snapshot_id,
        research_run_id=research_run_id,
        reason=reason,
        validation_run_id=validation_run_id,
    )

    return validation_run, event
