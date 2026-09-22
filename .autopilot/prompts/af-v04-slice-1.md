# Mission AF-V-04 Slice 1 — Contrats typés `ParameterStabilitySpecification`/`ParameterStabilityEvidence` (ADR 0023)

**Lire intégralement `docs/adr/0023-parameter-stability-plateau-v1.md` avant de commencer** —
cette ADR a été rédigée, revue par deux revues indépendantes SUR TROIS PASSES (2 BLOCKER + 6 MAJEUR
en première passe, 2 nouveaux MAJEUR introduits par les corrections elles-mêmes détectés en
seconde passe, 3 mineurs en troisième passe — toutes corrigées et reconfirmées propres), et
committée (`ca321f1`). Cette mission implémente STRICTEMENT ses Décisions 6/9/11/12 — ne
réinterprète rien, ne réintroduit AUCUNE des formulations déjà corrigées par la revue. En
particulier, jamais :
- fusionner `n_neighbors_total_by_param` et `n_neighbors_rejected_by_param` en un seul nombre ;
- omettre `sensitivity_sample_size_by_param` (le `sensitivity` réutilisé porte un sentinel `0.0`
  ambigu sans ce compagnon) ;
- inclure la distance de Hamming `0` (c'est-à-dire `best_params` lui-même) dans
  `n_hamming_le_2_total`/`degradation_hamming_le_2` ;
- dupliquer `source_candidates_from_optimized_search` dans `ParameterStabilityEvidence` (reste
  UNIQUEMENT dans `ParameterStabilitySpecification`, mirroring exact de
  `MonteCarloSpecification.source_trades_from_optimized_params`) ;
- omettre `neighborhood_applicability` ou le déduire implicitement d'un champ vide.

## Ce qui est DANS cette tranche

Ajouts à `validation_run.py` (module leaf, aucun nouvel import d'`engine.py`/`optimizer.py`/
`dataset_split.py`/`walk_forward.py`/`scoring.py` — cette dernière n'est utilisée QUE par le module
algorithmique de Slice 2, jamais ici) — Décision 11 de l'ADR pour le détail exact des champs :

1. `VALIDATION_TYPE_PARAMETER_STABILITY = "parameter_stability"`.
2. `ParameterStabilitySpecification` (frozen) — champs exacts de la Décision 11 :
   `source_validation_run_id: str`, `search_mode: str`,
   `source_candidates_from_optimized_search: bool`, `parameter_stability_semantics_version: str`,
   `verdict_policy_id: Optional[str] = None`.
3. `ParameterStabilityEvidence` (frozen) — champs exacts de la Décision 6/11 (liste complète,
   aucun oubli) : `n_candidates_total: int`, `zero_candidates_input: bool`, `search_mode: str`,
   `neighborhood_applicability: str`, `best_score: Optional[float]`, `best_params: Optional[dict]`,
   `sensitivity: Dict[str, float]`, `sensitivity_sample_size_by_param: Dict[str, int]`,
   `n_neighbors_total_by_param: Dict[str, int]`, `n_neighbors_rejected_by_param: Dict[str, int]`,
   `degradation_by_param: Dict[str, Optional[PercentileDistributionSummary]]`,
   `degradation_points_by_param: Dict[str, Optional[PercentileDistributionSummary]]`,
   `n_hamming_le_2_total: int`, `n_hamming_le_2_rejected: int`,
   `degradation_hamming_le_2: Optional[PercentileDistributionSummary]`, `execution_status: str`,
   `scientific_verdict: str`, `verdict_reasons: Tuple[str, ...]`.
   **`PercentileDistributionSummary` existe DÉJÀ** (`validation_run.py`, ADR 0022, renommée depuis
   `MonteCarloDistributionSummary` — commit `85dbba0`) — réutilisée TELLE QUELLE, jamais un type
   dupliqué.
4. `PARAMETER_STABILITY_SEMANTICS_VERSION` (constante module, mirroring
   `MONTE_CARLO_SEMANTICS_VERSION`).
5. `ParameterStabilitySemanticsMismatch(ValueError)` — mirroring EXACT de
   `WalkForwardSemanticsMismatch`/`MonteCarloSemanticsMismatch`.
6. `build_parameter_stability_specification(source_validation_run_id: str, search_mode: str, source_candidates_from_optimized_search: bool, verdict_policy_id: Optional[str] = None) -> ParameterStabilitySpecification`
   — SEULE construction sanctionnée (Décision 9/11) : `ValueError` si `source_validation_run_id`
   absent/vide (AVANT tout calcul) ; `ValueError` si `search_mode` n'est pas l'une des 4 valeurs
   valides. **`validation_run.py` NE DOIT JAMAIS importer `optimizer.py`, pas même pour une seule
   constante** (invariant "leaf" déjà vérifié à deux reprises par les revues indépendantes d'ADR
   0022/0023, jamais à régresser ici) — dupliquer LOCALEMENT, comme une constante module de
   `validation_run.py` elle-même, l'ensemble `{"single_var", "cross_zone", "grid", "general"}`
   (valeurs LITTÉRALES identiques à `optimizer.DETERMINISTIC_DISPATCH_MODES ∪ {"general"}`, jamais
   un import — un commentaire explicite doit signaler que ces chaînes doivent rester synchronisées
   avec `optimizer.py` si ce dernier venait à changer, mais aucun couplage fonctionnel réel).
   Fixe `parameter_stability_semantics_version` à la constante module, jamais un paramètre.
7. **`UnknownVerdictPolicy` n'est PAS recréée** — réutilise directement la classe déjà existante
   dans `validation_run.py` (troisième réutilisation après Walk-Forward et Monte-Carlo).
8. `_VALIDATION_TYPES` — ajouter une QUATRIÈME entrée au dict LITTÉRAL existant (jamais une
   affectation a posteriori, Décision 11 de l'ADR) :
   `VALIDATION_TYPE_PARAMETER_STABILITY: (ParameterStabilitySpecification, ParameterStabilityEvidence)`.
9. **`ValidationSpecification`/`ValidationEvidence`** (alias `Union`, `validation_run.py` lignes
   ~508-514) — étendre avec `ParameterStabilitySpecification`/`ParameterStabilityEvidence`
   (troisième membre après `MonteCarloSpecification`/`MonteCarloEvidence`, corrigées commit
   `85dbba0` — NE PAS reproduire l'oubli qui avait affecté Slice 1 d'AF-V-03).
10. Tests TDD (RED confirmé avant implémentation), au minimum : `build_parameter_stability_specification()`
    valide `search_mode` correctement (accepte les 4 valeurs réelles, refuse tout le reste) ;
    `ValueError` sur `source_validation_run_id` vide/absent ; round-trip réel sur disque
    (`build_validation_run(validation_type=VALIDATION_TYPE_PARAMETER_STABILITY, ...)` ->
    `save_validation_run()` -> `load_validation_run()`, préservation de TOUS les champs, y compris
    les dicts imbriqués de `PercentileDistributionSummary` et les compteurs `n_hamming_le_2_*`) ;
    `build_validation_run()` refuse une `evidence`/`specification` incohérente avec
    `validation_type="parameter_stability"` (mirroring des tests déjà existants pour
    `"monte_carlo"`) ; régression complète de `tests/test_validation_run.py` reste 100 % verte, y
    compris tous les tests Walk-Forward/Monte-Carlo déjà en place, jamais modifiés.

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- L'ALGORITHME lui-même (`analyze_parameter_stability()`, filtre de voisinage, dégradation,
  réutilisation de `scoring.compute_sensitivity_filtered()`/`compute_sensitivity_correlation()`) —
  nouveau module `parameter_stability.py`, tranche suivante (AF-V-04 Slice 2). Cette tranche ne
  construit QUE la forme typée, jamais peuplée par un calcul réel.
- Toute politique concrète de seuils PASS/FAIL — jamais inventée.
- Toute modification de `validation_run.py` au-delà des ajouts additifs listés ci-dessus (jamais
  toucher `WalkForwardSpecification`/`WalkForwardEvidence`/`MonteCarloSpecification`/
  `MonteCarloEvidence`/`OosValidationEvidence`/`build_validation_run()`/`save_validation_run()`/
  `load_validation_run()`/`_VALIDATION_TYPES`'s entrées existantes/`PercentileDistributionSummary`).
- Intégration `app.py`, câblage `walk_forward.py`/`optimizer.py`/`scoring.py` réel — hors scope.

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `validation_run.py` reste un leaf (import de `DETERMINISTIC_DISPATCH_MODES` depuis `optimizer.py`
  toléré UNIQUEMENT comme constante de validation, jamais un appel fonctionnel).
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète).
- Ne rien déclarer `PASS`/robuste — cette tranche ne produit aucune évidence réelle, seulement la
  forme typée.
