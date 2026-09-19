# Mission AF-V-02 Slice 5 — Reprise (resume) d'un run Walk-Forward interrompu (ADR 0021 Décision 12, complément)

Slices 1/2/3/4 (géométrie des folds, exécution TRAIN-only + Top-1 + TEST par fold, orchestrateur
multi-fold `run_walk_forward()`/`build_aggregate_result()`, persistance disque ÉCRITURE SEULE via
`persist_walk_forward_run()`/`build_walk_forward_manifest()`/`FoldArtifacts`/
`execute_walk_forward_fold_with_artifacts()`, commit `3e4e1ad`) sont terminées et poussées — NE
PAS les modifier, NE PAS remettre en cause leur contrat déjà en place et testé. La docstring de
`persist_walk_forward_run()` le dit explicitement : `state.json` est produit à titre PUREMENT
DESCRIPTIF, « aucune logique de reprise ne le relit encore (tranche suivante) » — et sa section
sur `tested.json` conclut que l'instrumentation incrémentale réelle de la boucle TRAIN « reste
entièrement à la charge de la tranche de reprise future (hors scope Slice 4) ». C'est cette
tranche.

Portée strictement dérivée d'`docs/adr/0021-walk-forward-rolling-calendar-v1.md`, Décision 12,
dernier paragraphe : « Un fold déjà terminé (artefacts complets et cohérents avec le fingerprint)
est sauté à la reprise ; un TRAIN interrompu réutilise les candidats déjà exécutés (fingerprint
identique) ; un TEST interrompu est **rejoué entièrement** avec la `FoldSelection` déjà figée
(jamais une nouvelle sélection) ; un agrégat interrompu est **recalculé intégralement** depuis les
folds terminés. » Ne rien inventer au-delà de cette phrase — en cas d'ambiguïté d'implémentation,
trancher explicitement dans le code/la review, comme Slice 4 l'a fait pour `tested.json`.

## Ce qui est DANS cette tranche

1. **Décision par fold à la reprise**, fonction pure ou quasi-pure prenant en entrée le
   `manifest.json`/`state.json`/artefacts déjà écrits sous un `output_dir` (lus via
   `atomic_json_store`, jamais un `open()`/`json.load()` direct) et le fingerprint du run courant
   (`WalkForwardSpecification` + `base_config` + `data_manifest_path`, mêmes entrées que
   `build_walk_forward_manifest()`), retournant pour chaque fold une décision explicite parmi :
   `SKIP` (fold déjà complet ET fingerprint identique à `manifest.json`), `REPLAY_TEST`
   (fold dont la `FoldSelection` est déjà figée et persistée mais dont `test_result.json`/les CSV
   TEST sont absents ou incomplets — rejoue uniquement l'exécution TEST avec cette
   `FoldSelection`, JAMAIS une nouvelle sélection TRAIN), `REDO` (fold absent, incomplet sans
   sélection figée, ou fingerprint divergent). Un fingerprint divergent (toute divergence sur les
   TROIS versions de sémantique, le `data_manifest.content_hash`, ou la spécification elle-même)
   ne doit JAMAIS être traité comme un `SKIP`/`REPLAY_TEST` silencieux — lever une erreur explicite
   de la taxonomie existante (Décision 11) plutôt que produire une reprise scientifiquement
   incohérente.
2. **Réutilisation des candidats TRAIN déjà exécutés d'un fold interrompu** — la phrase de
   Décision 12 la plus difficile à câbler : investiguer D'ABORD si le mécanisme de reprise déjà
   existant d'`optimizer.py`/`optimization_store.py` (hashs de candidats déjà évalués,
   `load_tested_hashes()`/`save_tested_hashes()`, déjà utilisé par des runs `Optimizer` non-Walk-
   Forward) peut être réutilisé TEL QUEL par fold (chaque TRAIN de fold étant déjà un
   `Optimizer.run()` distinct, Décision 6) avant d'inventer un mécanisme parallèle. Documenter le
   choix retenu et pourquoi, comme Slice 4 l'a fait pour `tested.json`/`selection.json` — jamais
   un second format de suivi de candidats dupliquant celui qui existe déjà si celui-ci convient.
3. **Point d'entrée de reprise** — fonction additive (ex. `resume_walk_forward_run(...)` ou un
   paramètre `resume_from: Optional[Path]` sur une nouvelle fonction dédiée) qui applique la
   décision par fold ci-dessus, exécute uniquement les folds `REDO`/`REPLAY_TEST` (jamais un fold
   `SKIP`), puis appelle `build_aggregate_result()` sur l'ENSEMBLE des `FoldResult` (folds
   sautés relus depuis `folds/fold_NNN/test_result.json`, jamais recalculés) pour produire un
   agrégat recalculé intégralement — jamais un agrégat partiel silencieux. `run_walk_forward()`
   lui-même (Slice 3) reste inchangé, EN MÉMOIRE pur, jamais appelé automatiquement en mode
   reprise sans passer par ce nouveau point d'entrée explicite.
4. Tests TDD (RED confirmé avant implémentation) — au minimum :
   - Un run interrompu après N folds complets, repris : les N premiers folds sont bien SKIP
     (aucun ré-exécution réelle — vérifié en observant qu'aucun nouveau `Optimizer.run()`/backtest
     n'est déclenché pour eux), les folds restants s'exécutent normalement, l'agrégat final couvre
     bien TOUS les folds (sautés + nouveaux).
   - Un fold dont la `FoldSelection` est déjà figée mais le TEST absent : `REPLAY_TEST` reproduit
     EXACTEMENT la même `FoldSelection` (pas une nouvelle sélection Top-1), ré-exécute uniquement
     le TEST.
   - Un fingerprint divergent (ex. `data_manifest.content_hash` différent, ou une version de
     sémantique différente) sur un fold par ailleurs "complet" : refuse explicitement (erreur
     taxonomie Décision 11), ne le traite jamais comme `SKIP`.
   - Régression complète (`tests/test_walk_forward.py`, `tests/test_optimizer.py`,
     `tests/test_optimization_store.py`, `tests/test_validation_run.py`) reste 100 % verte sans
     modification des assertions déjà en place pour Slices 1/2/3/4.

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- **`WalkForwardEvidence`/`execution_status`/`scientific_verdict`/`verdict_reasons`**, ni
  `validation_run.json`/`ValidationRun`/`save_validation_run()` — Décision 13, tranche séparée
  ultérieure, non commencée par cette tranche.
- Monte-Carlo, Parameter Stability.
- Intégration `app.py` (déclenchement UI d'une reprise) — hors scope, une future tranche
  d'orchestration bout-en-bout.
- Toute modification de `FINAL_HOLDOUT`, de la stratégie étalon (Perfect Revolution V1), du
  `DatasetSplitPlan`, ou du contrat déjà figé de `FoldResult`/`FoldSelection`/`FoldDefinition`/
  `AggregateResult`/`WalkForwardRunOutcome`/`run_walk_forward()`/`build_aggregate_result()`/
  `persist_walk_forward_run()`/`build_walk_forward_manifest()` au-delà de l'extension strictement
  additive nécessaire pour lire ces mêmes structures en sens inverse.
- Toute modification du comportement EXISTANT (non-Walk-Forward) d'`optimizer.py`/
  `optimization_store.py` — réutilisation en LECTURE de leur mécanisme de reprise si retenu au
  point 2, jamais une modification de leur contrat pour des appelants déjà existants.

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- Toute lecture des artefacts persistés passe par les mêmes primitives que Slice 4 a utilisées
  pour les écrire (`atomic_json_store`), jamais un `open()`/`json.load()` direct.
- `FINAL_HOLDOUT` jamais ouvert, jamais transformé en fold.
- Aucune modification d'`engine.py`, `compute_split_dates()`, `strategy_contracts.py` au-delà de
  ce que cette tranche exige explicitement et documente.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète).
- Ne rien déclarer `PASS`/robuste sur la seule base de cette tranche — aucun verdict scientifique
  n'est produit ici (hors scope de toute façon, voir ci-dessus).
