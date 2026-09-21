# Mission AF-V-02 Slice 8 — Assemblage `ValidationRun` Walk-Forward (câblage laissé ouvert par Slice 6, débloqué par Slice 7)

Slices 1 à 7 (géométrie, exécution, orchestration, persistance, reprise, `WalkForwardEvidence`,
`DatasetSplitPlan` v2 avec `VALIDATION` réellement peuplée, commit `88c9cf1`) sont terminées et
poussées — NE PAS les modifier.

Slice 6 a explicitement laissé hors scope le câblage `walk_forward.py` -> `build_walk_forward_evidence()`
-> `build_validation_run()`, en l'absence d'un `split_plan_id` réel transporté par quoi que ce soit
— voir son propre commentaire dans `validation_run.py` (« câbler cela sans appelant réel serait
spéculatif »). Slice 7 a produit un `split_plan_id` réel
(`split_perfect_revolution_v1_walk_forward_v2`) — cette tranche construit la fonction d'assemblage
elle-même, PAS encore un appelant réel bout-en-bout (`app.py` reste hors scope, comme toujours).

## Précédent exact à mirorer, jamais réinventer

`validation_oos.py::run_oos_validation()` est déjà le précédent établi pour EXACTEMENT ce rôle,
côté `"oos"` : reçoit `split_plan: DatasetSplitPlan` (l'objet ENTIER, jamais seulement son id),
`research_run_id`/`validation_run_id`/`strategy_name` fournis par l'APPELANT (jamais générés ni
devinés ici), construit l'evidence puis appelle `build_validation_run()`, et — point capital —
**ne persiste RIEN elle-même** (« la persistance... reste la responsabilité de l'appelant réel »).
Cette tranche applique EXACTEMENT le même principe côté Walk-Forward, avec une différence
structurelle : `run_oos_validation()` EXÉCUTE elle-même un backtest (`run_backtest_fn` injecté) ;
la fonction Walk-Forward, elle, ne doit RIEN exécuter — `outcome`/`aggregate` sont déjà le résultat
d'un appel séparé et antérieur à `run_walk_forward()`/`resume_walk_forward_run()` (Slices 3/5,
jamais rappelées ici), exactement comme `persist_walk_forward_run()` (Slice 4) le suppose déjà.

## Emplacement — décidé, pas laissé à deviner

Dans `walk_forward.py`, à côté de `persist_walk_forward_run()` — PAS un nouveau module
`validation_walk_forward.py` séparé. Justification (à confirmer par la mission, mais fortement
recommandée, documentée si un obstacle réel apparaît) : `validation_oos.py` est séparé de
`engine.py` uniquement parce qu'il doit connaître À LA FOIS le moteur ET la persistance Track R/V
(voir sa propre docstring) — cette nouvelle fonction ne connaît ni `engine.py` ni `optimizer.py`,
et `walk_forward.py` importe déjà `validation_run.py` extensivement (Slices 3/4/5/6) ; ajouter
`from dataset_split import DatasetSplitPlan` est une extension triviale d'un import déjà établi
(`from dataset_split import SplitBoundary`, ligne ~39). Créer un nouveau module séparé pour ce seul
ajout serait une séparation architecturale sans justification équivalente à celle de
`validation_oos.py`.

## Ce qui est DANS cette tranche

1. **`build_walk_forward_validation_run(outcome, aggregate, spec, split_plan, research_run_id, validation_run_id, strategy_name, strategy_params) -> ValidationRun`**,
   nouvelle fonction additive dans `walk_forward.py` :
   - `outcome: WalkForwardRunOutcome`, `aggregate: Optional[AggregateResult]` — déjà obtenus par
     un appel séparé et antérieur, jamais recalculés ni ré-exécutés ici.
   - `spec: WalkForwardSpecification` — sert de `specification` DIRECTEMENT à `build_validation_run()`
     (contrairement à `"oos"`, `WalkForwardSpecification` porte déjà l'intention figée AVANT
     exécution — aucune fonction `build_..._specification()` intermédiaire à inventer, voir sa
     propre docstring). Fournit aussi `spec.verdict_policy_id` à `build_walk_forward_evidence()`.
   - `split_plan: DatasetSplitPlan` — fournit `split_plan.split_plan_id`/`split_plan.dataset_snapshot_id`
     à `build_validation_run()`. Ne lit PAS `split_plan.validation` (aucune vérification de
     cohérence entre `outcome`/`split_plan` n'est faite ici — voir « hors scope » ci-dessous).
   - `research_run_id`/`validation_run_id`/`strategy_name`/`strategy_params` : fournis TELS QUELS
     par l'appelant, jamais générés/devinés/dérivés ici (même principe que `run_oos_validation()`).
   - Corps : `evidence = build_walk_forward_evidence(outcome, aggregate, spec.verdict_policy_id)`
     puis `return build_validation_run(validation_run_id=..., research_run_id=...,
     split_plan_id=split_plan.split_plan_id, dataset_snapshot_id=split_plan.dataset_snapshot_id,
     strategy_name=..., strategy_params=..., specification=spec, evidence=evidence,
     validation_type=VALIDATION_TYPE_WALK_FORWARD)`.
   - **Ne persiste RIEN** (ni `save_validation_run()`, ni `persist_walk_forward_run()`) — retourne
     uniquement la `ValidationRun` construite. Un futur appelant explicite reste responsable de la
     persistance, comme pour `run_oos_validation()`.
   - Import additif nécessaire : `from dataset_split import DatasetSplitPlan` (extension triviale
     de l'import déjà présent `from dataset_split import SplitBoundary`).
2. Tests TDD (RED confirmé avant implémentation) — au minimum :
   - Un appel réel avec un `outcome`/`aggregate` construits à la main (mirroring les fixtures déjà
     utilisées ailleurs dans `tests/test_walk_forward.py`, ex. `_fold_result_stub()`) et un
     `DatasetSplitPlan` réel (`build_dataset_split_plan()`, mirroring
     `tests/test_create_walk_forward_validation_split_plan_v2.py`) produit une `ValidationRun`
     dont `validation_type == VALIDATION_TYPE_WALK_FORWARD`, `split_plan_id`/`dataset_snapshot_id`
     correspondent exactement à `split_plan`, `specification is spec` (ou égal), `evidence` est
     bien la `WalkForwardEvidence` attendue.
   - `verdict_policy_id=None` sur `spec` -> `evidence.scientific_verdict == "INCONCLUSIVE"` (reuse
     direct du comportement déjà testé de `build_walk_forward_evidence()`, Slice 6 — pas une
     réimplémentation, juste une preuve de câblage correct).
   - Round-trip réel sur disque : `build_walk_forward_validation_run()` -> `save_validation_run()`
     -> `load_validation_run()` préserve tous les champs.
   - Preuve explicite que la fonction ne persiste rien elle-même (ex. : appelée dans un répertoire
     `tmp_path` vide, aucun fichier n'apparaît après l'appel, avant tout `save_validation_run()`
     explicite du test).
   - Régression complète (`tests/test_walk_forward.py`, `tests/test_validation_run.py`) reste
     100 % verte sans modification des assertions déjà en place pour Slices 1 à 7.

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- Toute vérification de cohérence entre `outcome`/`split_plan.validation` (ex. que les folds de
  `outcome` ont réellement été calculés depuis CETTE zone `VALIDATION` précise) — non fait ici,
  responsabilité de l'appelant, jamais silencieusement supposée vérifiée.
- Toute persistance réelle (`save_validation_run()` appelé automatiquement) — cette tranche
  construit, jamais n'écrit sur disque.
- Intégration `app.py` (déclenchement UI, génération réelle de `research_run_id`/
  `validation_run_id`) — toujours hors scope, une future tranche d'orchestration bout-en-bout.
- Toute politique concrète de seuils PASS/FAIL (Décision 13) — toujours hors scope, jamais à
  inventer.
- Toute modification de `run_walk_forward()`/`resume_walk_forward_run()`/`persist_walk_forward_run()`
  (Slices 3/4/5, inchangées) — cette nouvelle fonction reste additive et séparée, jamais appelée
  automatiquement par elles.
- Toute modification de `validation_oos.py`/`run_oos_validation()` (précédent lu, jamais modifié).
- Toute modification des scripts/tests v1/v2 de `DatasetSplitPlan` (Slices 1/7, intacts).

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `FINAL_HOLDOUT` jamais ouvert, jamais transformé en fold.
- Aucune modification d'`engine.py`, `optimizer.py`, `optimization_store.py`, `strategy_contracts.py`,
  `compute_split_dates()`, `dataset_split.py`, `validation_run.py`, `validation_oos.py`.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète).
- Ne rien déclarer `PASS`/robuste sur la seule base de cette tranche — le verdict reste
  structurellement `INCONCLUSIVE` tant qu'aucune politique n'est enregistrée (Slice 6, inchangé).
