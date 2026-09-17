# Mission AF-V-02 Slice 2 — Optimizer TRAIN-only + sélection Top-1 + exécution TEST par fold

Slice 2 de AF-V-02 (Walk-Forward V1). Slice 1 (géométrie déterministe des folds,
`walk_forward.py`, commit `efe49ef`) est terminée et poussée — NE PAS la modifier, NE PAS la
reprendre, NE PAS remettre en cause `compute_fold_definitions()`/`detect_partial_tail()`/les
guards `FINAL_HOLDOUT`/OOS overlap déjà en place et testés.

Portée de cette tranche UNIQUEMENT — strictement celle déjà décidée par
`docs/adr/0021-walk-forward-rolling-calendar-v1.md`, Décision 6, jamais inventée :

## Ce qui est DANS cette tranche

1. **Nouveau seam additif sur `Optimizer.run()`** : ajouter un paramètre
   `run_test_validation: bool = True` (rétrocompatible — comportement strictement inchangé pour
   tout appelant existant, `app.py` compris). `False` saute la phase de validation TEST actuelle
   (`top_to_validate = [...][:cfg.top_k_save]`, ~lignes 1044-1065 d'`optimizer.py`) sans y toucher
   autrement.
2. **Appel TRAIN-only par fold** : pour chaque `FoldDefinition` produite par Slice 1, appeler
   `Optimizer.run(run_test_validation=False)` avec `train_test.enabled=False` et la fenêtre
   d'exécution bornée DIRECTEMENT à `[train_start_k, effective_boundary_k)` (via
   `opt_start_date`/`opt_end_date`, jamais un second split interne — évite toute seconde
   résolution de `resolve_state_ready_boundary()`, qui n'est appelée qu'UNE fois par frontière de
   fold, par `walk_forward.py` lui-même, Décision 4).
3. **Sélection Top-1 TRAIN** : `all_results[0]` (meilleur score TRAIN) devient
   `FoldSelection.selected_params` — construire l'objet `FoldSelection` (déjà défini dans
   `validation_run.py`) avec ses champs réels (`selected_params_hash`, `score_train`,
   `rank_in_train`, `train_candidates_evaluated/unique/eligible`, `search_space_hash`,
   `algorithm`, `fold_seed`).
4. **Exactement une exécution TEST par fold**, sur `[effective_boundary_k, effective_test_end_k)`
   avec `end_boundary="exclusive"` pour TOUT fold y compris le dernier (Décision 4 — plus aucune
   exception terminale). Choix d'implémentation à trancher PAR CETTE MISSION (pas déjà tranché par
   l'ADR) : soit `optimizer._run_single()` gagne un paramètre optionnel rétrocompatible renvoyant
   aussi `trades`/`equity` (nécessaires pour `oos_trades.csv`/`FoldResult.expectancy` d'une future
   tranche), soit `walk_forward.py` appelle `run_backtest()` directement (même chemin que
   `_run_single()` emprunte déjà en interne). Documenter le choix retenu et pourquoi.
5. **Construction de `FoldResult`** (déjà défini dans `validation_run.py`) à partir du résultat
   TEST réel : `n_trades`, `net_ret_pct`, `max_dd_pct`, `profit_factor`, `win_rate`, `expectancy`
   (= `trades["resultat_net"].mean()` sur les trades du `TEST_k`, `None` si `n_trades == 0` —
   métrique introduite par Walk-Forward lui-même, pas un champ natif d'`engine.py`), `score_test`,
   `zero_trade_oos`, `forced_closes`, `coverage_bars`.
6. **Isolation TEST structurelle** (Décision 7) : après construction de `FoldSelection`, aucun
   code ne doit rappeler la phase TRAIN pour ce fold — garantie par le séquencement du code, pas
   par un verrou objet (cohérent avec le reste du dépôt, `ValidationRun`/`DatasetSplitPlan`).
7. Tests TDD : géométrie déjà couverte par Slice 1, cette tranche doit prouver — au minimum —
   qu'un fold TRAIN-only n'exécute jamais de backtest sur `[effective_boundary_k,
   effective_test_end_k)` avant la sélection Top-1 ; que `FoldSelection.selected_params` correspond
   bien au meilleur score TRAIN parmi les candidats réellement évalués ; qu'aucune barre TEST n'est
   perdue/dupliquée entre folds adjacents (test de régression direct sur l'implémentation,
   `effective_test_end_k == effective_boundary_{k+1}`, Décision 4) ; que `run_test_validation=True`
   (défaut) laisse `Optimizer.run()` strictement inchangé pour tout appelant existant (non-
   régression explicite, tests `test_optimizer.py` existants doivent rester 100% verts sans
   modification de leurs assertions).

## Ce qui N'EST PAS dans cette tranche (explicitement exclu, pour une tranche suivante)

- Persistance sur disque (`results/job_xxx/walk_forward/` — manifest/state/fold/aggregate,
  Décision 12) : les `FoldSelection`/`FoldResult` de cette tranche restent des objets EN MÉMOIRE,
  pas encore sauvegardés.
- Agrégation OOS multi-fold (`AggregateResult`, Décision 15) et son calcul de
  `oos_profit_factor`/`oos_net_return_pct` par concaténation de trades/reconstruction de courbe
  d'equity chaînée.
- `execution_status`/`scientific_verdict`/`verdict_policy_id` (Décision 13) — PASS/INCONCLUSIVE/
  FAIL.
- Reprise (`resume`) d'un run Walk-Forward interrompu (fingerprint, Décision 12).
- Monte-Carlo, Parameter Stability.
- Toute modification de `FINAL_HOLDOUT`, de la stratégie étalon (Perfect Revolution V1), ou du
  `DatasetSplitPlan` déjà créé par Slice 1 (`split_perfect_revolution_v1_walk_forward_v1`).

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `resolve_state_ready_boundary()` appelée EXACTEMENT une fois par frontière de fold, jamais une
  seconde fois à l'intérieur de l'appel `Optimizer.run()` d'un fold.
- `FINAL_HOLDOUT` jamais ouvert, jamais transformé en fold.
- Aucune modification de `engine.py`, `compute_split_dates()`, `strategy_contracts.py`,
  `walk_forward.py` (Slice 1, déjà figé) au-delà de ce que cette tranche exige explicitement.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète).
- Ne rien déclarer `PASS`/robuste sur la seule base de cette tranche — aucune tranche partielle
  n'emporte de verdict scientifique (Décision 13, hors scope ici de toute façon).
