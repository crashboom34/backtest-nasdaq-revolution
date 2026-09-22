# Mission AF-V-08 Slice 5 — Phase Parameter Stability (exhaustive par fold, ADR 0024 Décision 6-PS)

**Lire intégralement `docs/adr/0024-gate-v-campaign-orchestration-v1.md` avant de commencer,
notamment le paragraphe Parameter Stability de la Décision 6 (mapping EXACT demandé par
l'utilisateur, y compris "deux conditions CUMULATIVES" pour la contribution "prête pour GATE V") et
la Décision 14 (correctif de traçabilité `source_fold_id`, déjà committé).** AF-V-08 Slices 1-4 sont
terminées et poussées — NE PAS les modifier, réutiliser telles quelles. Cette tranche ajoute la
phase Parameter Stability à `execute_gate_v_campaign()`, en remplaçant le `pass`/TODO documenté par
Slice 3, et connecte enfin `derive_gate_v_campaign_status()` (Slice 2) pour calculer le `status`
final.

## Ce qui est DANS cette tranche

Ajouts à `gate_v_campaign.py` (phase Parameter Stability de `execute_gate_v_campaign()`) :

1. **Itère `expected_fold_ids` DANS L'ORDRE, SANS AUCUNE logique de sélection/filtrage du fold "le
   plus intéressant"** (Décision 6 — TOUS les folds terminés traités, jamais seulement le meilleur).
   Pour CHAQUE fold `f` :
   - **Reprise (Décision 8)** : si `manifest.parameter_stability_validation_run_ids_by_fold` contient
     DÉJÀ `f` ET que le fichier `ValidationRun` correspondant existe RÉELLEMENT sur disque (vérifié),
     ce fold est SAUTÉ (jamais recalculé) — passe au fold suivant SANS interrompre la boucle.
   - Sinon, charge `folds/<f>/train_candidates.csv` (pool TRAIN complet de CE fold) et
     `folds/<f>/selection.json` (`FoldSelection.selected_params`/`score_train` — le Top-1 RÉELLEMENT
     sélectionné pour CE MÊME fold, jamais un Top-1 d'un autre fold ni un "meilleur global" inventé)
     sous `output_dir_walk_forward/folds/<f>/`.
   - Assemble `ParameterStabilitySpecification` via
     `validation_run.build_parameter_stability_specification(source_validation_run_id=manifest.walk_forward_validation_run_id, search_mode=plan.search_mode, source_candidates_from_optimized_search=True, verdict_policy_id=plan.parameter_stability_verdict_policy_id, source_fold_id=f)`
     — **`source_candidates_from_optimized_search=True` EN DUR** (même justification que Slice 4/
     Décision 6, "PLUS FORT" per ADR 0023 Décision 1) ; **`source_fold_id=f`** (traçabilité corrigée,
     Décision 14 — cette orchestration est le PREMIER appelant réel à le fournir systématiquement).
   - Appelle `parameter_stability.analyze_parameter_stability(candidates=<train_candidates de CE fold>, best_params=<selection.selected_params>, spec=...)` (EXISTANT, appel DIRECT, jamais injecté —
     même justification que Monte-Carlo/Slice 4).
   - Assemble une `ValidationRun` ParameterStability DÉDIÉE à CE fold — `research_run_id=plan.research_run_id`,
     `validation_run_id` déterministe incluant `f` (ex. `f"{campaign_id}-parameter-stability-{f}"`).
     Persiste via `validation_run.save_validation_run()`.
   - **Signalement honnête des folds sans voisinage exploitable** : cette `ValidationRun` est persistée
     et référencée EXACTEMENT comme les autres, MÊME SI son `neighborhood_applicability` est
     `"global_correlation_only"` ou si elle n'a aucun voisin exploitable net — jamais filtrée/masquée
     (Décision 6). Met à jour `manifest.parameter_stability_validation_run_ids_by_fold[f]`, **réécrit
     le manifeste ATOMIQUEMENT IMMÉDIATEMENT après CE fold** (Décision 8 — "une interruption entre
     deux folds ne perd et ne duplique aucune preuve déjà produite" ; ne JAMAIS accumuler tous les
     folds en mémoire avant une seule écriture finale).
   - **Jamais de fusion artificielle en un score unique** : `GateVCampaignManifest` ne porte JAMAIS
     un champ "score combiné"/équivalent (vérifié par le contrat `GateVCampaignManifest` de Slice 2,
     inchangé ici).

2. **Calcul du `status` final** : après la boucle ci-dessus, construit les
   `ParameterStabilityQualityFacts` (Slice 2) pour CHAQUE fold DÉJÀ présent dans
   `manifest.parameter_stability_validation_run_ids_by_fold` (qu'il vienne d'être produit à l'instant
   ou d'une reprise antérieure) en relisant chaque `ValidationRun` réelle
   (`validation_run.load_validation_run()`, extraction de `neighborhood_applicability`/
   `n_neighbors_total_by_param`/`n_neighbors_rejected_by_param` depuis son `.evidence`), puis appelle
   `derive_gate_v_campaign_status()` (Slice 2, INCHANGÉE) avec ces faits + `walk_forward_complete=True`
   (Slice 3 garantit que cette phase n'est atteinte qu'après WF complet) +
   `monte_carlo_complete=(manifest.monte_carlo_validation_run_id is not None)` +
   `oos_evidence_present=(plan.oos_evidence_validation_run_id is not None)`. Assigne le résultat à
   `manifest.status`, réécrit le manifeste ATOMIQUEMENT une dernière fois.

3. Tests TDD (RED confirmé avant implémentation), reprendre PRÉCISÉMENT les lignes dédiées de la
   Décision 13 : sur 3 folds factices de qualité très différente, les 3 `ValidationRun`
   ParameterStability sont produites, AUCUNE n'est omise, aucun score combiné n'existe nulle part
   dans le manifeste ; `len(parameter_stability_validation_run_ids_by_fold) == len(expected_fold_ids)`
   après une exécution complète factice ; **reprise sans duplication** — manifeste pré-rempli avec 2
   folds DÉJÀ produits (fichiers `ValidationRun` réels sur disque, `tmp_path`) -> reprise ne
   recalcule QUE le fold manquant, spy sur `analyze_parameter_stability` confirme EXACTEMENT 1 appel ;
   `source_fold_id`/`source_candidates_from_optimized_search=True` corrects sur CHAQUE `ValidationRun`
   produite ; **statut final `EVIDENCE_INCOMPLETE` si au moins un fold a `neighborhood_applicability="global_correlation_only"`**
   même avec les 3 folds présents (test d'intégration bout-à-bout minimal, préfigure Slice 6) ;
   **aucune preuve d'une mission antérieure réutilisée** — un `campaign_id` DIFFÉRENT ne référence
   jamais les `ValidationRun` d'un `campaign_id` distinct (répertoires isolés par construction, testé
   explicitement).

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- Tests d'intégration bout-en-bout complets couvrant TOUTES les décisions de sécurité/anti-
  déclenchement (Décision 9/11/12, ligne finale de la Décision 13) — Slice 6.
- Toute modification de `parameter_stability.py`/`validation_run.py` — appelés TELS QUELS.
- Toute politique concrète de seuils PASS/FAIL — jamais inventée.

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `analyze_parameter_stability()` appelée DIRECTEMENT (import module-level), JAMAIS injectée.
- Manifeste réécrit ATOMIQUEMENT après CHAQUE fold Parameter Stability produit, jamais accumulé en
  mémoire — c'est la propriété testée qui prouve "reprise sans doublon" à ce niveau de granularité.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète, y
  compris tous les tests de Slices 1-4, jamais modifiés).
- Ne rien déclarer `PASS`/robuste.
- Aucune exécution réelle sur `nasdaq_3m.csv`, aucun backtest, aucune recherche `Optimizer`, aucun
  téléchargement, aucun accès `FINAL_HOLDOUT`.
