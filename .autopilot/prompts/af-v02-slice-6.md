# Mission AF-V-02 Slice 6 — WalkForwardEvidence : assemblage de la preuve + verdict scientifique (ADR 0021 Décision 13)

Slices 1 à 5 (géométrie des folds, exécution TRAIN-only + Top-1 + TEST par fold, orchestrateur
multi-fold, persistance disque, reprise SKIP/REPLAY_TEST/REDO, commit `525f28f`) sont terminées et
poussées — NE PAS les modifier, NE PAS remettre en cause leur contrat déjà en place et testé.

`WalkForwardEvidence` existe déjà comme forme figée dans `validation_run.py` (ligne ~364) — sa
propre docstring cite explicitement l'ADR 0021 Décision 13, mais **aucune fonction ne la
construit encore**, et **aucune politique de verdict de seuils (PASS/FAIL) n'existe nulle part
dans ce dépôt** (`OosValidationEvidence`, le seul autre type d'evidence existant, ne porte AUCUN
champ de verdict). `_VALIDATION_TYPES` (même fichier, ligne ~412) enregistre déjà
`VALIDATION_TYPE_WALK_FORWARD: (WalkForwardSpecification, WalkForwardEvidence)` — `build_validation_run()`/
`save_validation_run()` sont donc **déjà** génériques et fonctionnels pour Walk-Forward, AUCUNE
modification n'y est nécessaire ni autorisée par cette tranche.

## Contrainte absolue, non négociable, rappelée explicitement par l'utilisateur

**N'invente aucun seuil scientifique absent.** Aucune politique concrète de seuils PASS/FAIL
(ex. « PASS si oos_profit_factor > X ») n'existe dans ce dépôt à ce jour. Décider quels seuils
constitueraient un verdict scientifique valide est une décision scientifique/produit distincte,
que cette tranche NE DOIT PAS prendre à la place de l'utilisateur — ni en silence, ni en
choisissant une valeur "raisonnable". La seule politique acceptable ici est L'ABSENCE de politique
concrète, gérée explicitement (voir ci-dessous).

## Ce qui est DANS cette tranche

1. **`build_walk_forward_evidence(outcome: WalkForwardRunOutcome, aggregate: Optional[AggregateResult], verdict_policy_id: Optional[str]) -> WalkForwardEvidence`**,
   dans `validation_run.py` (mirroring exact de `build_oos_validation_evidence()` — même style,
   à côté de `WalkForwardEvidence` elle-même, ce module reste un leaf, aucun import de
   `walk_forward.py`/`engine.py`/`optimizer.py`).
   - `execution_status` : `"completed"` si `not outcome.stopped_early`, `"stopped_early"` si
     `outcome.stopped_early` — EXACTEMENT ces deux valeurs, jamais une troisième inventée. Une
     erreur technique réelle ne produit JAMAIS de `WalkForwardEvidence` (Décision 13 : l'exception
     remonte AVANT qu'un objet complet n'existe) — cette fonction n'a donc structurellement rien à
     gérer pour ce cas, ne pas ajouter de branche pour un scénario qui ne peut pas l'atteindre.
   - `scientific_verdict`/`verdict_reasons` — règles, dans cet ordre :
     a. `verdict_policy_id is None` -> TOUJOURS `"INCONCLUSIVE"`, avec une raison explicite
        (ex. « aucune politique de verdict pré-enregistrée (verdict_policy_id=None) — ADR 0021
        Décision 13 »). C'est le cas normal/attendu tant qu'aucune politique concrète n'existe.
     b. `outcome.stopped_early is True` (même si `verdict_policy_id` est fourni) -> TOUJOURS
        `"INCONCLUSIVE"`, avec une raison explicite distincte (l'agrégat ne couvre qu'un préfixe
        des folds attendus — évaluer une politique de seuils calibrée pour l'ensemble complet
        contre un sous-ensemble produirait un jugement trompeur, dans l'esprit du dernier
        paragraphe de la Décision 13 : « jamais une valeur trompeuse produite silencieusement »).
        Documenter ce choix explicitement dans le code (docstring), ce n'est pas une déduction
        automatique du typage mais une décision de cette mission.
     c. `verdict_policy_id` fourni ET `outcome.stopped_early is False` -> AUCUNE politique n'est
        encore enregistrée dans ce dépôt : lever explicitement une nouvelle exception
        `UnknownVerdictPolicy(ValueError)` (taxonomie ADR 0021 Décision 11 — fail closed, refuser
        plutôt que deviner) plutôt que de retomber silencieusement sur `INCONCLUSIVE` ou d'inventer
        un seuil. Message d'erreur explicite : aucune politique de verdict n'est enregistrée dans
        ce dépôt à ce jour ; définir une politique concrète est une décision scientifique/produit
        distincte, hors périmètre de cette tranche.
   - `fold_results`/`aggregate` : passés tels quels depuis `outcome`/`aggregate` (des faits, jamais
     recalculés ni filtrés ici).
2. **Point d'appel reliant le chemin complet** `walk_forward.py` -> `build_walk_forward_evidence()`
   -> `build_validation_run()` -> `save_validation_run()` — aujourd'hui totalement absent pour
   Walk-Forward (à la différence de `validation_oos.py::run_oos_validation()`, qui le fait déjà
   pour `"oos"`). Choix d'implémentation à trancher PAR CETTE MISSION et à documenter (comme
   Slice 4 l'a fait pour `tested.json`) : soit une nouvelle fonction additive dans `walk_forward.py`
   (ex. `build_and_save_walk_forward_validation_run(outcome, aggregate, spec, ..., path) -> ValidationRun`)
   qui orchestre les trois appels, soit laisser cette orchestration à un futur appelant externe
   (auquel cas cette tranche expose seulement `build_walk_forward_evidence()` elle-même, testée en
   isolation, sans nouvelle fonction dans `walk_forward.py`). Dans les deux cas, ne PAS appeler ce
   nouveau chemin automatiquement depuis `run_walk_forward()`/`resume_walk_forward_run()`
   elles-mêmes (qui restent des orchestrateurs EN MÉMOIRE purs, Slices 3/5, jamais modifiées) —
   un appelant explicite reste responsable de construire/persister l'evidence après coup, même
   principe que `persist_walk_forward_run()` (Slice 4).
3. Tests TDD (RED confirmé avant implémentation) — au minimum :
   - `verdict_policy_id=None` -> `scientific_verdict="INCONCLUSIVE"`, `verdict_reasons` non vide.
   - Tout `verdict_policy_id` non-`None` sur un run complet (`stopped_early=False`) -> lève
     `UnknownVerdictPolicy`, jamais un verdict silencieux.
   - `outcome.stopped_early=True` avec un `verdict_policy_id` fourni -> `scientific_verdict`
     reste `"INCONCLUSIVE"` (jamais l'exception `UnknownVerdictPolicy` dans ce cas précis : le
     stopped_early prime, documenté au point 1.b — sinon dans ce cas précis un run interrompu avec
     policy fournie deviendrait indiscernable en test de b vs c, à couvrir explicitement par un
     test dédié qui le distingue d'un test policy+run complet).
   - `execution_status` correct dans les deux cas (`"completed"`/`"stopped_early"`).
   - Une `WalkForwardEvidence` complète (verdict `INCONCLUSIVE`, cas normal sans policy) survit un
     aller-retour réel `build_validation_run()` -> `save_validation_run()` -> `load_validation_run()`
     (fichier réel sur disque, jamais un round-trip en mémoire seul) sans perte/mutation de champ.
   - Régression complète (`tests/test_validation_run.py`, `tests/test_walk_forward.py`) reste
     100 % verte sans modification des assertions déjà en place pour Slices 1 à 5.

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- **Toute politique concrète de seuils PASS/FAIL** — aucun seuil scientifique n'existe dans ce
  dépôt aujourd'hui ; ce n'est structurellement pas à cette tranche de l'inventer (voir contrainte
  absolue ci-dessus). Si un jour une politique réelle doit être définie, cela exige une décision
  scientifique/produit explicite de l'utilisateur — déclencher `HUMAN_GATE_REQUIRED` plutôt que de
  deviner si cette question se pose réellement pendant cette tranche.
- Intégration `app.py` (déclenchement UI, affichage du verdict) — hors scope, une future tranche
  d'orchestration bout-en-bout.
- Monte-Carlo, Parameter Stability.
- Toute modification de `FINAL_HOLDOUT`, de la stratégie étalon (Perfect Revolution V1), du
  `DatasetSplitPlan`, ou du contrat déjà figé de `FoldResult`/`FoldSelection`/`FoldDefinition`/
  `AggregateResult`/`WalkForwardRunOutcome`/`WalkForwardSpecification`/`run_walk_forward()`/
  `resume_walk_forward_run()`/`persist_walk_forward_run()`/`build_walk_forward_manifest()`.
- Toute modification de `build_validation_run()`/`save_validation_run()`/`load_validation_run()`/
  `_VALIDATION_TYPES` eux-mêmes (déjà génériques et fonctionnels pour Walk-Forward, aucun
  changement nécessaire).

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `validation_run.py` reste un leaf (aucun nouvel import d'`engine.py`/`optimizer.py`/
  `walk_forward.py`).
- `FINAL_HOLDOUT` jamais ouvert, jamais transformé en fold.
- Aucune modification d'`engine.py`, `compute_split_dates()`, `strategy_contracts.py`,
  `optimizer.py`, `optimization_store.py`, `dataset_split.py` au-delà de ce que cette tranche
  exige explicitement et documente (a priori : aucune de ces modifications n'est nécessaire).
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète).
- Ne rien déclarer `PASS`/robuste sur la seule base de cette tranche — cette tranche construit le
  MÉCANISME du verdict, jamais un verdict positif réel (qui resterait de toute façon
  structurellement `INCONCLUSIVE` tant qu'aucune politique n'est enregistrée).
