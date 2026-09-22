# Mission AF-V-08 Slice 3 — Niveau B squelette : phase Walk-Forward, double injection, garde persist-once (ADR 0024 Décisions 5/6-WF/8-WF/10/11)

**Lire intégralement `docs/adr/0024-gate-v-campaign-orchestration-v1.md` avant de commencer,
notamment la Décision 5 (double collaborateur `run_walk_forward_fn`/`resume_walk_forward_fn`,
signatures RÉELLES différentes), la Décision 6 paragraphe Walk-Forward (garde persist-once,
correctif BLOCKER), la Décision 8 paragraphe Walk-Forward (limite résiduelle connue, résolution
MANUELLE), et la Décision 10 (portée exacte de la garantie FINAL_HOLDOUT).** AF-V-08 Slices 1-2
sont terminées et poussées — NE PAS les modifier, réutiliser telles quelles.

## Ce qui est DANS cette tranche

Ajouts à `gate_v_campaign.py` :

1. **`execute_gate_v_campaign(plan: GateVCampaignPlan, *, run_walk_forward_fn, resume_walk_forward_fn, manifest_dir: Union[str, Path], ...) -> GateVCampaignManifest`**
   (Décision 5 Niveau B) — **cette tranche implémente UNIQUEMENT la phase Walk-Forward** ; les phases
   Monte-Carlo/Parameter Stability (Slices 4/5) restent des `pass`/TODO explicites documentés, PAS
   encore appelées. Vérifier les signatures RÉELLES exactes de `walk_forward.run_walk_forward()`
   (ligne 799) et `walk_forward.resume_walk_forward_run()` (ligne 1791) dans le code source AVANT
   d'écrire cette fonction — ne jamais deviner leurs paramètres.
   - **N'accepte QU'UN `GateVCampaignPlan` DÉJÀ construit** — aucun paramètre par défaut permettant
     un déclenchement accidentel (`run_walk_forward_fn`/`resume_walk_forward_fn` keyword-only, SANS
     valeur par défaut, Décision 5).
   - Écrit/lit le manifeste `GateVCampaignManifest` (Slice 2) sous
     `<manifest_dir>/<campaign_id>/manifest.json` (Décision 4 — chemin DISTINCT de `plan.json`, DISTINCT
     du futur `.../walk_forward/manifest.json` de Walk-Forward lui-même, Décision 4 précision
     "deux fichiers de même nom, à deux niveaux de répertoire différents"). Premier appel : construit
     un manifeste initial `status="RUNNING"` (réécrit ATOMIQUEMENT AVANT chaque étape coûteuse — Décision
     7 : "permet une reprise fidèle même sur un crash en plein milieu").
   - **Sélection du collaborateur (Décision 6/8)** : teste `Path(<output_dir_walk_forward>/"manifest.json").is_file()`
     où `output_dir_walk_forward = .../<campaign_id>/walk_forward/` (Décision 4) :
     - Absent -> appelle `run_walk_forward_fn(split_plan.validation, wf_spec, plan.base_params, output_dir=output_dir_walk_forward)`
       -> `WalkForwardRunOutcome` SEUL. **Appelle ENSUITE explicitement
       `walk_forward.build_aggregate_result(outcome.fold_results)`** (EXISTANT, ligne 863) pour obtenir
       l'`AggregateResult` — JAMAIS `aggregate=None` transmis à la persistance ci-dessous (correctif
       MINEUR de la revue scientifique — sans cet appel, le marqueur de complétion `aggregate.json`
       ne serait jamais écrit, cassant silencieusement la garde de non-double-persistance).
     - Présent -> appelle `resume_walk_forward_fn(split_plan.validation, wf_spec, plan.base_params, data_manifest_path=..., output_dir=output_dir_walk_forward)`
       -> `Tuple[WalkForwardRunOutcome, AggregateResult]` (signature RÉELLE distincte, Décision 5).
   - **Garde persist-once (Décision 6, correctif BLOCKER — le cœur de cette tranche)** : teste
     `Path(output_dir_walk_forward / "aggregate.json").is_file()` (dernier fichier écrit par
     `persist_walk_forward_run()`, marqueur fiable de complétion totale) :
     - Présent -> `persist_walk_forward_run()` N'EST PAS rappelée (déjà fait, charge l'état déjà
       persisté depuis le disque si nécessaire pour la suite).
     - Absent -> appelle `walk_forward.persist_walk_forward_run(outcome, fold_artifacts, aggregate, spec, plan.base_params, data_manifest_path, output_dir_walk_forward, validation_run_id=<walk_forward_validation_run_id de la campagne>)`
       (EXISTANT, JAMAIS RÉIMPLÉMENTÉE) EXACTEMENT une fois sur l'outcome COMPLET.
   - Assemble la `ValidationRun` Walk-Forward via `walk_forward.build_walk_forward_validation_run()`
     (EXISTANT, Slice 8 AF-V-02) avec `research_run_id=plan.research_run_id`,
     `validation_run_id` généré par la campagne (convention à documenter explicitement dans le
     docstring — ex. `f"{campaign_id}-walk-forward"`, déterministe, jamais aléatoire). Persiste via
     `validation_run.save_validation_run()` (EXISTANT). Met à jour
     `manifest.walk_forward_validation_run_id`, réécrit le manifeste ATOMIQUEMENT.
   - **Ne peut structurellement jamais accéder `FINAL_HOLDOUT`** : n'importe jamais `validation_oos.py`
     (test d'import statique, Slice 1 déjà couvert — reconfirmer qu'il reste vert). **Cette garantie
     couvre UNIQUEMENT les imports propres de `gate_v_campaign.py`, jamais le contenu réel de
     `run_walk_forward_fn`/`resume_walk_forward_fn` injectés** (Décision 10, "frontière de confiance
     DISTINCTE" — cette tranche ne peut PAS et ne doit PAS essayer de le vérifier, c'est une
     responsabilité humaine hors scope).

2. Tests TDD (RED confirmé avant implémentation), reprendre PRÉCISÉMENT les lignes dédiées de la
   Décision 13 : sélection du bon collaborateur (sans `manifest.json` WF préexistant -> `run_walk_forward_fn`
   appelé, `resume_walk_forward_fn` jamais appelé, spy ; avec -> l'inverse, fixture `tmp_path`) ;
   `persist_walk_forward_run()` jamais rappelée après une reprise déjà persistée (fixture `tmp_path`
   avec `.../walk_forward/aggregate.json` déjà présent -> zéro appel, spy, AUCUNE `FileExistsError`) ;
   persistance appelée EXACTEMENT une fois sur un run frais complet (spy) ; `build_aggregate_result()`
   appelé EXACTEMENT une fois dans la branche run frais, AVANT le collaborateur de persistance, et
   l'`aggregate` transmis n'est JAMAIS `None` (spy) ; manifeste réécrit ATOMIQUEMENT avant l'étape
   Walk-Forward (`status="RUNNING"`) puis après (`walk_forward_validation_run_id` renseigné) ; test
   d'import statique — aucun import `validation_oos`/référence `FINAL_HOLDOUT` (reconfirmer Slice 1) ;
   AUCUN test de cette mission ne charge `nasdaq_3m.csv` ni n'appelle le moteur réel — tous les
   `run_walk_forward_fn`/`resume_walk_forward_fn` injectés dans les tests sont des doublures
   FACTICES retournant un `WalkForwardRunOutcome`/`Tuple[...]` synthétique construit à la main.

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- Phases Monte-Carlo (Slice 4) et Parameter Stability (Slice 5) — `pass`/TODO explicite documenté
  dans le corps de `execute_gate_v_campaign()`, jamais un appel réel à
  `run_monte_carlo_simulation()`/`analyze_parameter_stability()` dans cette tranche.
- Calcul du `status` final via `derive_gate_v_campaign_status()` (Slice 2) — cette tranche assigne
  `RUNNING` directement, jamais `EVIDENCE_INCOMPLETE`/`EVIDENCE_COMPLETE_AWAITING_POLICY` (les 4
  catégories de preuve n'existent pas encore à ce stade de l'implémentation).
- `load_market_data_fn`/tout chargement réel de `nasdaq_3m.csv` — les doublures de test ne touchent
  jamais le disque de données réelles ; le paramètre peut être accepté par la signature (Décision 5)
  mais n'est PAS encore exercé par un test réel dans cette tranche si son usage réel dépend d'une
  tranche ultérieure — documenter ce choix explicitement si `load_market_data_fn` n'est pas encore
  utilisé concrètement ici.
- Le scénario de la limite résiduelle documentée en Décision 8 (crash PENDANT l'appel unique
  `persist_walk_forward_run()`) n'a PAS besoin d'un correctif de code — seulement d'un test qui
  PROUVE que la garde persist-once fonctionne pour le cas normal (reprise APRÈS persistance complète),
  jamais une tentative de rendre `persist_walk_forward_run()` elle-même tolérante à une écriture
  partielle (hors scope, Slice 4 AF-V-02 reste gelée).

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `persist_walk_forward_run()`/`resume_walk_forward_run()`/`run_walk_forward()`/`compute_fold_definitions()`/
  `build_walk_forward_validation_run()` (`walk_forward.py`) : JAMAIS modifiées, JAMAIS réimplémentées —
  uniquement appelées telles quelles.
- `gate_v_campaign.py` reste sans dépendance `engine.py`/`optimizer.py`/`validation_oos.py` — test
  d'import statique reconfirmé vert.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète, y
  compris tous les tests de Slices 1/2, jamais modifiés).
- Ne rien déclarer `PASS`/robuste.
- Aucune exécution réelle sur `nasdaq_3m.csv`, aucun backtest, aucune recherche `Optimizer`, aucun
  téléchargement, aucun accès `FINAL_HOLDOUT`.
