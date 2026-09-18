# Mission AF-V-02 Slice 4 — Persistance disque des artefacts Walk-Forward (Décision 12, écriture seule)

Slices 1/2/3 (géométrie des folds, exécution TRAIN-only + Top-1 + TEST par fold, orchestrateur
multi-fold `run_walk_forward()` + `build_aggregate_result()`, commit `febe701`) sont terminées et
poussées — NE PAS les modifier, NE PAS remettre en cause `compute_fold_definitions()`/
`execute_walk_forward_fold()`/`run_walk_forward()`/`build_aggregate_result()`/`WalkForwardRunOutcome`
déjà en place et testés. `run_walk_forward()` reste EN MÉMOIRE UNIQUEMENT à ce jour — sa propre
docstring le dit explicitement : « aucune persistance disque, aucune reprise : ADR 0021 Décision 12
hors scope ».

Portée de cette tranche UNIQUEMENT — strictement dérivée d'`docs/adr/0021-walk-forward-rolling-calendar-v1.md`,
Décision 12, et limitée à l'ÉCRITURE des artefacts qu'elle nomme explicitement (jamais la reprise
elle-même, jamais le verdict scientifique — voir « hors scope » ci-dessous, jamais inventée).

## Ce qui est DANS cette tranche

1. **Structure de sortie** exactement celle de la Décision 12, sous `results/job_xxx/walk_forward/`
   (le nom exact du répertoire racine, paramétrable par l'appelant — ne jamais coder en dur un
   chemin sous `results/`, suivre la convention déjà établie ailleurs dans le dépôt pour les
   sorties de job, ex. `optimization_store.py`, à vérifier avant d'inventer) :
   - `manifest.json` — fingerprint de reprise : dataset snapshot, stratégie, git SHA (déjà capturé
     par `data_manifest.json` ailleurs dans le dépôt — réutiliser ce mécanisme existant, JAMAIS le
     recalculer indépendamment), search space, scoring, filtres, géométrie
     (`WalkForwardSpecification` sérialisée), les TROIS versions de sémantique
     (`WALK_FORWARD_SEMANTICS_VERSION`/`TRAIN_TEST_SEMANTICS_VERSION`/
     `STATE_READINESS_SEMANTICS_VERSION`), `master_seed`, référence de politique de verdict
     (`verdict_policy_id`, `None` accepté et persisté tel quel).
   - `state.json` — folds terminés (liste des `fold_id` dont les artefacts sont déjà écrits et
     cohérents avec le fingerprint courant). Dans cette tranche, ce fichier est produit à titre
     PUREMENT DESCRIPTIF (aucune logique de reprise ne le relit encore — voir « hors scope »).
   - `folds/fold_NNN/{definition,tested,selection,test_result}.json` par fold — sérialisation
     directe de `FoldDefinition`/`FoldSelection`/`FoldResult` (déjà des dataclasses frozen dans
     `validation_run.py`, `dataclasses.asdict()` ou équivalent, jamais un format parallèle
     réinventé). `tested` : nom à clarifier avec `train_candidates_evaluated` déjà présent dans
     `FoldSelection` — décrire précisément ce que ce fichier contient si son contenu diffère de
     `selection.json`, ou fusionner explicitement si redondant (documenter le choix).
   - `folds/fold_NNN/train_candidates.csv` / `oos_trades.csv` / `oos_equity.csv` — CSV par fold.
     Nécessite d'exposer les `trades`/`equity` individuels de la phase TEST d'un fold, aujourd'hui
     internes à `run_fold_test()` (Slice 2) et non retournés par `FoldResult` (qui ne porte que des
     agrégats). Choix d'implémentation à trancher PAR CETTE MISSION, strictement additif et
     rétrocompatible (même principe que le seam `run_test_validation`/`seed` de Slice 2) : soit
     `execute_walk_forward_fold()`/`run_fold_test()` gagnent un paramètre optionnel exposant aussi
     les DataFrames `trades`/`equity` du TEST (`None` par défaut, comportement inchangé pour tout
     appelant existant, y compris `run_walk_forward()` lui-même qui ne les demande pas), soit une
     fonction de persistance séparée réexécute `run_fold_test()`'s chemin d'accès aux données —
     JAMAIS un second backtest réel. Documenter le choix retenu et pourquoi.
   - `aggregate.json` — sérialisation directe d'`AggregateResult` (Slice 3, déjà peuplé par
     `build_aggregate_result()`).
2. **Fonction(s) de persistance**, additive(s), dans `walk_forward.py` (ex.
   `persist_walk_forward_run(outcome: WalkForwardRunOutcome, aggregate: Optional[AggregateResult],
   spec: WalkForwardSpecification, output_dir, ...)`) — réutilise `atomic_json_store.save_atomic()`
   (écriture atomique, jamais une écriture directe `open()/json.dump()`) pour CHAQUE fichier JSON ;
   les CSV suivent la convention pandas déjà utilisée ailleurs dans le dépôt pour des sorties
   similaires (vérifier `optimization_store.py`/`research_run.py` avant d'inventer un format).
   Jamais appelée automatiquement par `run_walk_forward()` lui-même (qui reste un orchestrateur EN
   MÉMOIRE pur, Slice 3, inchangé) — un appelant explicite (test, ou future intégration `app.py`
   hors scope ici) invoque la persistance APRÈS avoir obtenu un `WalkForwardRunOutcome`.
3. Tests TDD (RED confirmé avant implémentation) — au minimum :
   - Chaque fichier JSON nommé par la Décision 12 est bien créé, avec un contenu qui désérialise
     vers les valeurs réelles de `FoldDefinition`/`FoldSelection`/`FoldResult`/`AggregateResult`/
     `WalkForwardSpecification` d'un run construit à la main (aucune valeur inventée/tronquée).
   - Les CSV (`train_candidates`/`oos_trades`/`oos_equity`) contiennent bien les lignes réelles
     issues du TEST du fold (vérifié par relecture pandas, pas seulement l'existence du fichier).
   - `manifest.json` porte bien les TROIS versions de sémantique ET une référence explicite au
     `data_manifest.json` existant (jamais un git SHA recalculé indépendamment).
   - `atomic_json_store.save_atomic()` est bien utilisé pour CHAQUE fichier JSON (jamais un
     `open()`/`json.dump()` direct qui contournerait l'écriture atomique) — test de câblage, pas
     seulement de contenu.
   - Un fold à `zero_trade_oos=True` produit des CSV vides (pas d'erreur), cohérent avec
     `FoldResult.n_trades=0`.
   - Régression complète (`tests/test_walk_forward.py`, `tests/test_optimizer.py`,
     `tests/test_validation_run.py`) reste 100 % verte sans modification des assertions déjà en
     place pour Slices 1/2/3.

## Ce qui N'EST PAS dans cette tranche (explicitement exclu, pour une tranche suivante)

- **Reprise (`resume`) d'un run interrompu** : `state.json` est produit dans cette tranche mais
  JAMAIS RELU pour sauter un fold déjà terminé, réutiliser des candidats TRAIN déjà exécutés, ou
  rejouer un TEST interrompu — cette logique de reprise (fingerprint de correspondance, décision
  sauter/rejouer par fold) est une tranche à part entière.
- **`WalkForwardEvidence`/`execution_status`/`scientific_verdict`/`verdict_reasons` peuplés**, ni
  `validation_run.json`/`ValidationRun`/`validation_run.build_validation_run()`/
  `save_validation_run()` — cette tranche persiste les artefacts BRUTS nommés par la Décision 12
  UNIQUEMENT (manifest/state/fold/aggregate/CSV), jamais l'enregistrement dans le registre
  `ValidationRun` ni un verdict (Décision 13, tranche séparée ultérieure).
- Monte-Carlo, Parameter Stability.
- Toute modification de `FINAL_HOLDOUT`, de la stratégie étalon (Perfect Revolution V1), du
  `DatasetSplitPlan`, ou du contrat déjà figé de `FoldResult`/`FoldSelection`/`FoldDefinition`/
  `AggregateResult`/`WalkForwardRunOutcome`/`run_walk_forward()`/`build_aggregate_result()`
  au-delà de l'extension strictement additive nécessaire pour exposer `trades`/`equity` du TEST.

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- Écriture atomique (`atomic_json_store.save_atomic()`) pour tout fichier JSON — jamais un
  `open()`/`json.dump()` direct.
- `FINAL_HOLDOUT` jamais ouvert, jamais transformé en fold.
- Aucune modification d'`engine.py`, `compute_split_dates()`, `strategy_contracts.py`,
  `optimizer.py` au-delà de ce que cette tranche exige explicitement et documente.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète).
- Ne rien déclarer `PASS`/robuste sur la seule base de cette tranche — aucun verdict scientifique
  n'est produit ici (hors scope de toute façon, voir ci-dessus).
