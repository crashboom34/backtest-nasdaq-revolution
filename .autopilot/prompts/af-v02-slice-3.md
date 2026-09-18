# Mission AF-V-02 Slice 3 — Orchestration multi-fold + agrégation OOS en mémoire (Décision 15)

Slice 1 (géométrie déterministe des folds, `walk_forward.py`, commit `efe49ef`) et Slice 2
(exécution TRAIN-only + sélection Top-1 + exécution TEST par fold via
`execute_walk_forward_fold()`, commit `5afa7c8`) sont terminées et poussées — NE PAS les modifier,
NE PAS remettre en cause `compute_fold_definitions()`/`detect_partial_tail()`/`run_fold_train()`/
`select_fold_top1()`/`run_fold_test()`/`execute_walk_forward_fold()` déjà en place et testés.

Portée de cette tranche UNIQUEMENT — strictement dérivée de la section « Ce qui N'EST PAS dans
cette tranche » de `.autopilot/prompts/af-v02-slice-2.md` (item 2, « Agrégation OOS multi-fold »)
et de `docs/adr/0021-walk-forward-rolling-calendar-v1.md`, Décision 14 (indépendance stricte des
folds) et Décision 15 (agrégation concaténée), jamais inventée.

## Ce qui est DANS cette tranche

1. **Nouvel orchestrateur multi-fold**, dans `walk_forward.py` (nom à choisir par l'implémentation,
   ex. `run_walk_forward(validation_zone, spec, readiness_spec, base_config, df, progress_cb=None,
   stop_flag_fn=None)`) : appelle `compute_fold_definitions(validation_zone, spec, readiness_spec)`
   (Slice 1, EXACTEMENT une fois, jamais recalculée par fold) puis, pour CHAQUE `FoldDefinition`
   retournée dans l'ordre, `execute_walk_forward_fold(fold, base_config, df, progress_cb,
   stop_flag_fn, fold_seed=...)` (Slice 2). `fold_seed` par fold : dérivé selon ADR 0021 Décision 9
   (`fold_seed = sha256(f"{master_seed}:{validation_run_id}:{fold_index}:wf-fold-seed-v1")`,
   jamais `hash()`/`time.time()`/`random.randint()`) si `spec.master_seed` est fourni, sinon `None`
   propagé tel quel (le garde `NonDeterministicSearchWithoutSeed` de Slice 2 reste la seule
   protection, inchangé). Collecte les `FoldResult` retournés dans une `Tuple[FoldResult, ...]`
   **EN MÉMOIRE UNIQUEMENT** — aucune écriture disque dans cette tranche (Décision 12 exclue, voir
   ci-dessous).
2. **Aucune rétroaction inter-fold** (ADR 0021 Décision 14, à PROUVER par un test, pas seulement
   supposée) : le résultat TEST du fold `k` (`FoldResult`, `score_test`) ne doit JAMAIS influencer,
   pour le fold `k+1`, le search space/scoring/filtres/poids/seed/budget — tous fixés une fois pour
   toutes par `WalkForwardSpecification`/`base_config` au début du run. `position_transition_policy
   = "flat_each_fold_v1"` (déjà un champ de `WalkForwardSpecification`, Slice 1) : chaque fold garde
   son capital initial identique, aucune position/PnL reporté d'un fold à l'autre — déjà garanti
   par construction (`execute_walk_forward_fold()` charge une instance `Strategy()` fraîche à
   chaque fold via `run_fold_train()`/`run_fold_test()`, Slice 2, inchangé) : ce point est à
   VÉRIFIER par un test de régression sur l'orchestrateur, pas à réimplémenter.
3. **Construction d'`AggregateResult`** (déjà défini dans `validation_run.py`, forme figée
   « population différée » — cette tranche la peuple réellement) à partir de la série de
   `FoldResult` collectée, selon ADR 0021 Décision 15 :
   - `n_folds` = nombre de folds exécutés ; `n_folds_zero_trade` = nombre de folds avec
     `zero_trade_oos=True`.
   - Métrique OOS principale = la série **concaténée chronologiquement** des trades de tous les
     `TEST_k` (implique que `run_fold_test()`/`execute_walk_forward_fold()` exposent les trades
     individuels du fold, pas seulement les agrégats déjà dans `FoldResult` — vérifier ce qui est
     déjà disponible depuis Slice 2 et combler si nécessaire, en respectant strictement le contrat
     déjà figé de `FoldResult`/`run_fold_test()`, sans le modifier rétroactivement).
   - `total_oos_trades` = somme des `n_trades` de tous les folds.
   - `oos_profit_factor = gross_win_total / gross_loss_total` sur la série concaténée (mêmes noms
     de grandeur qu'`engine.py::_compute_stats()`, jamais `gross_profit`/`gross_loss` inventés) ;
     `gross_loss_total == 0` avec `total_oos_trades > 0` → `float("inf")` (convention déjà utilisée
     par `engine.py:502`) ; `None` réservé au seul cas `total_oos_trades == 0`.
   - `oos_win_rate = total_winners / total_trades` (jamais une moyenne de taux par fold).
   - Courbe d'equity OOS reconstruite en **chaînant les rendements normalisés** de chaque fold
     (JAMAIS une concaténation brute des valeurs de capital absolues — chaque fold redémarre au
     même `initial_capital`, `flat_each_fold_v1`) : exemple de référence de l'ADR, fold `k` `+5 %`
     puis fold `k+1` `-2 %` → `1.00 → 1.05 → 1.029`. `oos_max_dd_pct` calculé directement sur cette
     courbe normalisée (jamais une moyenne/le pire des `max_dd_pct` par fold).
   - `oos_net_return_pct` par composition chronologique (jamais une simple somme de pourcentages).
   - `oos_sharpe = None` en V1 (réservé, aucune convention d'annualisation figée par cette mission
     — jamais une valeur inventée pour remplir le champ).
   - `mean_fold_score_test`/`median_fold_score_test` : sur les `score_test` de tous les folds
     (diagnostics secondaires, jamais la mesure principale).
   - `worst_fold_id` : `fold_id` du fold au `score_test` le plus bas.
4. **Cas limite : zéro fold exécuté** — `compute_fold_definitions()` lève déjà
   `DatasetTooShortForWalkForward` avant que l'orchestrateur n'ait quoi que ce soit à agréger
   (Slice 1, inchangé) : ne pas dupliquer ce garde, laisser l'exception se propager telle quelle.
5. **`stop_flag_fn`** : si fourni et retournant `True` ENTRE deux folds, l'orchestrateur s'arrête
   proprement après le fold en cours (jamais en plein milieu d'un fold) — décrire précisément le
   comportement retourné dans ce cas (ex. lever une exception dédiée, ou retourner un résultat
   partiel explicitement marqué comme tel) et le documenter, TDD à l'appui. Ne pas inventer de
   mécanisme de reprise (Décision 12, hors scope — voir ci-dessous) : un arrêt ici n'a PAS besoin
   d'être repris automatiquement dans cette tranche.
6. Tests TDD (RED confirmé avant implémentation) — au minimum :
   - L'orchestrateur appelle `compute_fold_definitions()` EXACTEMENT une fois, jamais une fois par
     fold (test de comptage sur un `compute_fold_definitions` espionné/mocké).
   - Aucune rétroaction inter-fold : un `FoldResult` de fold `k` mutable, ou un `execute_walk_forward_fold`
     espionné, prouve que le search space/scoring/filtres/seed transmis au fold `k+1` sont
     identiques à ceux du fold `k` (Décision 14), jamais dérivés du résultat précédent.
   - Le calcul de la courbe d'equity chaînée reproduit EXACTEMENT l'exemple de référence de l'ADR
     (`1.00 → 1.05 → 1.029`) sur un cas construit à la main.
   - `oos_profit_factor` : cas `gross_loss_total == 0` avec des trades réels → `float("inf")` ;
     cas `total_oos_trades == 0` (tous les folds zéro-trade) → `None`.
   - `AggregateResult.n_folds_zero_trade` compte correctement un mélange de folds zéro-trade et
     non-zéro-trade.
   - `worst_fold_id` désigne bien le fold au score le plus bas parmi un jeu d'au moins 3 folds.
   - Régression complète (`tests/test_walk_forward.py`, `tests/test_optimizer.py`,
     `tests/test_validation_run.py` compris) reste 100 % verte sans modification des assertions
     déjà en place pour Slice 1/Slice 2.

## Ce qui N'EST PAS dans cette tranche (explicitement exclu, pour une tranche suivante)

- **Persistance sur disque** (`results/job_xxx/walk_forward/` — manifest/state/fold/aggregate,
  fichiers `oos_trades.csv`/`oos_equity.csv`, ADR 0021 Décision 12) : l'`AggregateResult`/les
  `FoldResult` de cette tranche restent des objets EN MÉMOIRE, jamais sauvegardés sur disque.
- **`execution_status`/`scientific_verdict`/`verdict_policy_id`/`WalkForwardEvidence`** complet
  (Décision 13) — PASS/INCONCLUSIVE/FAIL. Cette tranche produit un `AggregateResult`, pas un
  `WalkForwardEvidence` peuplé ni un appel à `validation_run.build_validation_run()`/
  `save_validation_run()`.
- **Reprise (`resume`) d'un run Walk-Forward interrompu** (fingerprint, Décision 12).
- Monte-Carlo, Parameter Stability.
- Toute modification de `FINAL_HOLDOUT`, de la stratégie étalon (Perfect Revolution V1), du
  `DatasetSplitPlan` déjà créé par Slice 1, ou du contrat déjà figé de `FoldResult`/`run_fold_test()`/
  `execute_walk_forward_fold()`/`select_fold_top1()`/`run_fold_train()` (Slice 2) au-delà de ce que
  cette tranche exige explicitement pour exposer les trades individuels nécessaires à
  l'agrégation — si une extension de leur contrat est nécessaire, elle doit être STRICTEMENT
  additive et rétrocompatible (mêmes principes que le seam `run_test_validation`/`seed` de Slice 2).

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `compute_fold_definitions()` appelée EXACTEMENT une fois par run, jamais une seconde fois par
  fold ni recalculée.
- `FINAL_HOLDOUT` jamais ouvert, jamais transformé en fold.
- Aucune modification d'`engine.py`, `compute_split_dates()`, `strategy_contracts.py`,
  `optimizer.py` au-delà de ce que cette tranche exige explicitement et documente.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète).
- Ne rien déclarer `PASS`/robuste sur la seule base de cette tranche — `AggregateResult` reste un
  fait mesuré, JAMAIS un verdict (Décision 13, hors scope ici de toute façon).
