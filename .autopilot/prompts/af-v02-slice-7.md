# Mission AF-V-02 Slice 7 — Nouveau DatasetSplitPlan (v2) avec zone VALIDATION de 54 mois / 5 folds (ADR 0021 Décision 8, décision d'allocation de l'utilisateur)

Slices 1 à 6 (géométrie, exécution TRAIN-only + Top-1 + TEST par fold, orchestrateur multi-fold,
persistance disque, reprise, `WalkForwardEvidence`, commit `2a49b11`) sont terminées et poussées —
NE PAS les modifier.

## Contexte — un plan v1 existe déjà, NE JAMAIS le toucher

`scripts/create_walk_forward_validation_split_plan.py` (Slice 1, déjà committé, `NE PAS MODIFIER`)
a déjà construit et **réellement écrit** un premier `DatasetSplitPlan`
(`split_perfect_revolution_v1_walk_forward_v1`, `VALIDATION_MONTHS=42`, 3 folds) — artefact réel
présent localement dans `results/dataset_splits/split_perfect_revolution_v1_walk_forward_v1/split_plan.json`
(`results/` est `.gitignore`, jamais versionné, mais l'artefact existe bel et bien sur disque dans
le checkout principal, `created_at: 2026-09-15T05:35:40`). `DatasetSplitPlan` est IMMUABLE
(`save_dataset_split_plan()` refuse d'écraser un `split_plan_id` déjà écrit) — cette tranche NE
DOIT NI MODIFIER NI SUPPRIMER ce script ni cet artefact existants. L'allocation 42 mois avait été
choisie par la mission Slice 1 elle-même comme un défaut raisonné, jamais explicitement confirmée
par l'utilisateur à l'époque ; ce dernier a désormais tranché une allocation DIFFÉRENTE et
DÉLIBÉRÉE, décrite ci-dessous — cette tranche construit un **second** plan, sous un **nouveau**
`split_plan_id` distinct, sans jamais toucher au premier.

## Décision d'allocation (fournie explicitement par l'utilisateur — 2026-09-21, ne pas rediscuter)

- Zone macro `TRAIN` (réservée à Discovery) : `[2017-10-31T00:00:00+00:00, 2020-11-19T00:00:00+00:00)`
- Zone `VALIDATION` (réservée au Walk-Forward) : `[2020-11-19T00:00:00+00:00, 2025-05-19T00:00:00+00:00)`
  — 54 mois calendaires exactement.
- `FINAL_HOLDOUT` **inchangé**, jamais déplacé : `[2025-05-19T00:00:00+00:00, 2026-05-20T00:00:00+00:00)`.

**Vérifié avant mise en file, avec les fonctions calendaires réelles du dépôt**
(`build_walk_forward_specification`/`compute_fold_definitions`/`detect_partial_tail`, préréglage
Rolling par défaut `P24M`/`P6M`/`P6M`) : cette zone `VALIDATION` produit EXACTEMENT 5 folds
TEST complets, non chevauchants (`fold_000`…`fold_004`), le dernier `test_end` tombant
EXACTEMENT sur `2025-05-19T00:00:00+00:00` = `VALIDATION.end` = `FINAL_HOLDOUT.start` (contigu,
aucun écart), et `detect_partial_tail()` retourne `None` (aucun reliquat partiel). Cette
vérification n'est PAS à refaire par la mission — reproduite ici pour référence, mais si le
Developer souhaite la revérifier lui-même par acquis de conscience, c'est bienvenu, jamais
bloquant.

## Ce qui est DANS cette tranche

1. **Nouveau script** `scripts/create_walk_forward_validation_split_plan_v2.py` — mirroring EXACT
   de `scripts/create_walk_forward_validation_split_plan.py` (Slice 1), avec :
   - `NEW_SPLIT_PLAN_ID = "split_perfect_revolution_v1_walk_forward_v2"`.
   - `NEW_SPLIT_PLAN_PATH = Path(f"results/dataset_splits/{NEW_SPLIT_PLAN_ID}/split_plan.json")`.
   - `VALIDATION_MONTHS = 54` (au lieu de `42`) — docstring mise à jour expliquant que cette
     allocation est une décision explicite de l'utilisateur (2026-09-21), remplaçant le défaut
     raisonné mais jamais confirmé de Slice 1, dimensionnée pour 5 folds P24M/P6M/P6M sans
     reliquat sur cette allocation précise (même style de justification que le script v1).
   - `build_walk_forward_validation_split_plan_v2(historical: DatasetSplitPlan) -> DatasetSplitPlan` —
     même logique pure que la fonction v1 (`old_train_end - DateOffset(months=VALIDATION_MONTHS)`),
     jamais un import croisé entre les deux scripts (chacun reste autonome, mirroring délibéré du
     style déjà établi, pas une factorisation prématurée — Rule of Three pas atteinte avec
     seulement 2 occurrences).
   - `main()` : lit le MÊME plan historique (`HISTORICAL_SPLIT_PLAN_PATH`, inchangé,
     `split_perfect_revolution_v1_final_holdout`), écrit le nouveau plan v2, affiche les bornes —
     jamais un accès au plan v1 (les deux plans dérivent indépendamment du même historique).
2. Tests TDD (RED confirmé avant implémentation), mirroring EXACT de
   `tests/test_create_walk_forward_validation_split_plan.py` (Slice 1), adapté à 54 mois/5 folds —
   nouveau fichier `tests/test_create_walk_forward_validation_split_plan_v2.py` (jamais modifier le
   fichier de test v1) :
   - nouveau `split_plan_id` distinct du plan historique ET du plan v1 ;
   - même `dataset_snapshot_id` réutilisé ;
   - `final_holdout` strictement inchangé ;
   - `validation` peuplée, immédiatement contiguë à `final_holdout` (zéro écart) ;
   - `train` raccourci, même début, fin = `validation.start` ;
   - durée `VALIDATION` = exactement 54 mois (`pd.DateOffset(months=54)`) ;
   - preuve d'intégration : `compute_fold_definitions()` sur ce plan avec la géométrie Rolling par
     défaut produit EXACTEMENT 5 folds, `detect_partial_tail()` retourne `None` ;
   - le plan historique n'est jamais muté par l'appel (objet frozen).
   - Régression complète (`tests/test_create_walk_forward_validation_split_plan.py`,
     `tests/test_dataset_split.py`, `tests/test_walk_forward.py`) reste 100 % verte, en particulier
     le fichier de test v1 — preuve que le plan v1/son script restent intacts.
3. **Exécution réelle du script**, une fois les tests verts : lancer
   `python scripts/create_walk_forward_validation_split_plan_v2.py` pour de vrai dans le worktree
   permanent (pas seulement testé en mémoire) — produit l'artefact réel
   `results/dataset_splits/split_perfect_revolution_v1_walk_forward_v2/split_plan.json`
   (`results/` reste `.gitignore`, jamais commité, mais l'exécution réelle doit avoir eu lieu et
   son résultat vérifié — mêmes bornes que celles données ci-dessus, `FINAL_HOLDOUT` identique au
   plan historique). Documenter la sortie exacte de cette exécution dans le rapport de mission.

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- Toute modification de `scripts/create_walk_forward_validation_split_plan.py` ou de
  `tests/test_create_walk_forward_validation_split_plan.py` (v1) — intacts, jamais touchés.
- Toute suppression/modification de l'artefact v1 déjà réel sur disque
  (`results/dataset_splits/split_perfect_revolution_v1_walk_forward_v1/`).
- Le câblage `walk_forward.py` -> `build_walk_forward_evidence()` -> `build_validation_run()` ->
  `save_validation_run()` (Slice 6 l'a explicitement laissé hors scope, faute d'appelant réel
  transportant `research_run_id`/`split_plan_id`/`dataset_snapshot_id`/`strategy_name`/
  `strategy_params`) — cette tranche construit UNIQUEMENT le `DatasetSplitPlan`, jamais ce câblage
  (candidat naturel d'une tranche suivante, maintenant que `split_plan_id` existe réellement).
- Toute politique concrète de seuils PASS/FAIL (Décision 13) — toujours hors scope, toujours à ne
  jamais inventer.
- Toute modification de `FINAL_HOLDOUT`, de la stratégie étalon (Perfect Revolution V1), du
  contrat déjà figé de `DatasetSplitPlan`/`SplitBoundary`/`FoldDefinition`/`FoldSelection`/
  `FoldResult`/`AggregateResult`/`WalkForwardRunOutcome`/`WalkForwardSpecification`/
  `WalkForwardEvidence`.
- `discovery_oos` reste `None` (même choix que le plan v1 — hors scope, jamais peuplé ici).

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `DatasetSplitPlan` reste immuable — `save_dataset_split_plan()` (jamais réimplémentée,
  réutilisée telle quelle) refuse tout écrasement d'un `split_plan_id` déjà écrit ; ne jamais
  contourner cette garde.
- `FINAL_HOLDOUT` jamais ouvert, jamais transformé en fold, jamais déplacé.
- Aucune modification d'`engine.py`, `optimizer.py`, `optimization_store.py`, `strategy_contracts.py`,
  `compute_split_dates()`, `walk_forward.py`, `validation_run.py`.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète).
- Ne rien déclarer `PASS`/robuste sur la seule base de cette tranche — cette tranche construit un
  plan de split, jamais un verdict scientifique.
