# Mission AF-V-08 Slice 4 — Phase Monte-Carlo (mapping TEST-only, ADR 0024 Décision 6-MC)

**Lire intégralement `docs/adr/0024-gate-v-campaign-orchestration-v1.md` avant de commencer,
notamment le paragraphe Monte-Carlo de la Décision 6 (mapping EXACT demandé par l'utilisateur) et
le paragraphe "Drapeaux de circularité" ajouté juste après (correctif BLOCKER de la revue
scientifique).** AF-V-08 Slices 1-3 sont terminées et poussées — NE PAS les modifier, réutiliser
telles quelles. `execute_gate_v_campaign()` (Slice 3) a déjà la phase Walk-Forward complète ; cette
tranche ajoute la phase Monte-Carlo IMMÉDIATEMENT après (dans le corps de la même fonction, en
remplaçant le `pass`/TODO documenté par Slice 3).

## Ce qui est DANS cette tranche

Ajouts à `gate_v_campaign.py` (phase Monte-Carlo de `execute_gate_v_campaign()`) :

1. **Reprise (Décision 8)** : relit le manifeste déjà persisté AVANT cette étape — si
   `manifest.monte_carlo_validation_run_id` est déjà renseigné ET que le fichier `ValidationRun`
   correspondant existe RÉELLEMENT sur disque (vérifié via `Path.is_file()`, jamais supposé),
   l'étape est SAUTÉE entièrement (jamais recalculée).
2. **Sinon, mapping EXACT (Décision 6)** :
   - Pour CHAQUE fold de `expected_fold_ids`, dans l'ordre `fold_index` croissant (garanti par
     `compute_fold_definitions()`, EST l'ordre chronologique, jamais un tri séparé réinventé), charge
     `folds/fold_NNN/oos_trades.csv` (JAMAIS `train_candidates.csv`) sous
     `output_dir_walk_forward/folds/<fold_id>/` (Slice 3, `walk_forward.persist_walk_forward_run()`).
   - **Concatène tous les folds dans cet ordre, chaque trade EXACTEMENT une fois** — vérifie
     EXPLICITEMENT que le nombre total de trades concaténés est égal à
     `aggregate.total_oos_trades` (le MÊME `AggregateResult` déjà obtenu en Slice 3, jamais recalculé
     indépendamment) : divergence -> `ValueError` explicite AVANT tout appel Monte-Carlo, jamais une
     valeur silencieusement tronquée/dupliquée.
   - **Bornes/ordre/doublons revérifiés comme preuve défensive** : les trades de chaque fold restent
     dans les bornes TEST de CE fold (`FoldDefinition.effective_boundary`/`effective_test_end`,
     vérifier les noms exacts de ces champs dans `walk_forward.py` avant d'écrire cette vérification) ;
     aucun trade dupliqué entre deux folds.
   - Assemble `MonteCarloSpecification` via `validation_run.build_monte_carlo_specification(source_validation_run_id=manifest.walk_forward_validation_run_id, source_trades_from_optimized_params=True, verdict_policy_id=plan.monte_carlo_verdict_policy_id)`
     — **`source_trades_from_optimized_params=True` EN DUR, JAMAIS un paramètre configurable de
     `GateVCampaignPlan`** (correctif BLOCKER, revue scientifique — les trades TEST Walk-Forward
     proviennent STRUCTURELLEMENT du Top-1 TRAIN-optimisé de chaque fold dans ce câblage, il ne peut
     structurellement jamais en être autrement).
   - Appelle `monte_carlo.run_monte_carlo_simulation()` (EXISTANT, vérifier la signature réelle avant
     d'écrire cet appel — NE PAS injecter cette fonction, appel DIRECT, Décision 5 : "fonctions PURES/
     déterministes... aucun équivalent du besoin `run_backtest_fn`").
   - Assemble UNE SEULE `ValidationRun` Monte-Carlo pour toute la campagne (jamais une par fold,
     cohérent avec ADR 0022 Décision 1) — `research_run_id=plan.research_run_id`,
     `validation_run_id` déterministe (ex. `f"{campaign_id}-monte-carlo"`, même convention que Slice 3).
     Persiste via `validation_run.save_validation_run()`.
   - Met à jour `manifest.monte_carlo_validation_run_id`, réécrit le manifeste ATOMIQUEMENT
     IMMÉDIATEMENT après (Décision 8 : "jamais en fin de campagne seulement").

3. Tests TDD (RED confirmé avant implémentation), reprendre PRÉCISÉMENT les lignes dédiées de la
   Décision 13 : un fold factice dont les trades TRAIN et TEST sont délibérément distincts/marqués —
   seuls les trades TEST apparaissent dans la séquence transmise à `run_monte_carlo_simulation()`
   (spy) ; compte total transmis == `AggregateResult.total_oos_trades` — divergence synthétique
   construite -> `ValueError` explicite AVANT tout appel Monte-Carlo (spy confirme ZÉRO appel dans ce
   cas) ; ordre chronologique respecté (folds factices dans un ordre délibérément non-trivial en
   entrée, ordre `fold_index` respecté en sortie, vérifié par spy sur les trades transmis) ; **les DEUX
   drapeaux `source_trades_from_optimized_params`/(rien pour PS ici, Slice 5) valent `True` sur la
   `ValidationRun` produite** ; reprise sans duplication — manifeste pré-rempli avec
   `monte_carlo_validation_run_id` + fichier `ValidationRun` réel sur disque (`tmp_path`) -> étape
   SAUTÉE, spy sur `run_monte_carlo_simulation` confirme ZÉRO appel.

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- Phase Parameter Stability — Slice 5, `pass`/TODO documenté conservé.
- Calcul du `status` final via `derive_gate_v_campaign_status()` — Slice 6.
- Toute modification de `monte_carlo.py`/`validation_run.py` — appelés TELS QUELS.

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `run_monte_carlo_simulation()` appelée DIRECTEMENT (import module-level), JAMAIS injectée —
  mirroring Décision 5, aucune doublure Monte-Carlo dans les tests, les trades synthétiques SONT
  l'entrée réelle de la fonction réelle.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète, y
  compris tous les tests de Slices 1-3, jamais modifiés).
- Ne rien déclarer `PASS`/robuste — `scientific_verdict` reste `INCONCLUSIVE` sans
  `verdict_policy_id` réel (`plan.monte_carlo_verdict_policy_id` reste `None` dans cette mission).
- Aucune exécution réelle sur `nasdaq_3m.csv`, aucun backtest, aucune recherche `Optimizer`, aucun
  téléchargement, aucun accès `FINAL_HOLDOUT`.
