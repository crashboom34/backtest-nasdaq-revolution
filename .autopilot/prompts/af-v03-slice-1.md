# Mission AF-V-03 Slice 1 — Contrats typés `MonteCarloSpecification`/`MonteCarloEvidence` (ADR 0022)

**Lire intégralement `docs/adr/0022-monte-carlo-trade-resampling-v1.md` avant de commencer** —
cette ADR a été rédigée, revue par deux revues indépendantes (validité scientifique/risque
d'overfitting ; architecture/reproductibilité/intégration), corrigée (2 BLOCKER + 6 MAJOR résolus,
confirmé par une seconde lecture des deux revues), et committée (`bfbc671`). Cette mission
implémente STRICTEMENT ses Décisions 5/8/9/11/12 — ne réinterprète rien, ne réintroduit AUCUNE des
formulations déjà corrigées par la revue (en particulier : jamais de `probability_of_ruin`, jamais
un drawdown nommé `max_dd_pct` seul sans le suffixe `_trade_close_basis_pct`, jamais `master_seed`
comme paramètre libre d'un builder public, jamais `n_simulations` comme paramètre libre d'un
builder public).

## Ce qui est DANS cette tranche

Ajouts à `validation_run.py` (module leaf, aucun nouvel import d'`engine.py`/`optimizer.py`/
`dataset_split.py`/`walk_forward.py`) — Décision 11 de l'ADR pour le détail exact des champs :

1. `VALIDATION_TYPE_MONTE_CARLO = "monte_carlo"`.
2. `MonteCarloDistributionSummary` (frozen, `p5`/`p25`/`p50`/`p75`/`p95`, tous `Optional[float]`).
3. `MonteCarloSpecification` (frozen) — champs exacts de la Décision 11 : `n_simulations: int`,
   `master_seed: int`, `source_validation_run_id: str`, `source_trades_from_optimized_params: bool`,
   `monte_carlo_semantics_version: str`, `verdict_policy_id: Optional[str] = None`.
4. `MonteCarloEvidence` (frozen) — champs exacts de la Décision 11/6 : `n_input_trades: int`,
   `zero_trade_input: bool`, `observed_net_ret_pct: Optional[float]`,
   `observed_max_dd_trade_close_basis_pct: Optional[float]`,
   `observed_lag1_autocorrelation: Optional[float]`, `observed_longest_losing_streak: Optional[int]`,
   `sequence_risk_max_dd_trade_close_basis_pct: Optional[MonteCarloDistributionSummary]`,
   `sequence_risk_longest_losing_streak: Optional[MonteCarloDistributionSummary]`,
   `sampling_uncertainty_net_ret_pct: Optional[MonteCarloDistributionSummary]`,
   `sampling_uncertainty_max_dd_trade_close_basis_pct: Optional[MonteCarloDistributionSummary]`,
   `execution_status: str`, `scientific_verdict: str`, `verdict_reasons: Tuple[str, ...]`.
5. `MONTE_CARLO_SEMANTICS_VERSION` (constante module, mirroring `WALK_FORWARD_SEMANTICS_VERSION`) et
   `MONTE_CARLO_DEFAULT_N_SIMULATIONS = 10_000` (constante module, Décision 4/5).
6. `MonteCarloSemanticsMismatch(ValueError)` — mirroring EXACT de `WalkForwardSemanticsMismatch`.
7. `build_monte_carlo_specification(source_validation_run_id: str, source_trades_from_optimized_params: bool, verdict_policy_id: Optional[str] = None) -> MonteCarloSpecification`
   — SEULE construction sanctionnée (Décision 5) : `ValueError` si `source_validation_run_id`
   absent/vide (AVANT tout calcul), dérive `master_seed` par SHA-256 depuis
   `source_validation_run_id` exactement selon la formule de la Décision 5
   (`_MONTE_CARLO_MASTER_SEED_DOMAIN_TAG = "mc-v1-master"`), fixe `n_simulations`/
   `monte_carlo_semantics_version` aux constantes module, jamais des paramètres.
8. **`UnknownVerdictPolicy` n'est PAS recréée** — réutilise directement la classe déjà existante
   dans `validation_run.py` (créée pour Walk-Forward, Slice 6) : générique, aucun champ spécifique
   à un `validation_type`, voir sa docstring actuelle avant d'écrire quoi que ce soit.
9. `_VALIDATION_TYPES` — ajouter une TROISIÈME entrée au dict LITTÉRAL existant (jamais une
   affectation `_VALIDATION_TYPES[...] = ...` a posteriori, voir Décision 11 de l'ADR pour la
   justification exacte) : `VALIDATION_TYPE_MONTE_CARLO: (MonteCarloSpecification, MonteCarloEvidence)`.
10. Tests TDD (RED confirmé avant implémentation), au minimum : `build_monte_carlo_specification()`
    dérive `master_seed` de façon déterministe (même `source_validation_run_id` -> même
    `master_seed` ; deux ids différents -> seeds différents) ; `ValueError` sur
    `source_validation_run_id` vide/absent ; round-trip réel sur disque
    (`build_validation_run(validation_type=VALIDATION_TYPE_MONTE_CARLO, ...)` ->
    `save_validation_run()` -> `load_validation_run()`, préservation de tous les champs, y compris
    les `MonteCarloDistributionSummary` imbriqués) ; `build_validation_run()` refuse une
    `evidence`/`specification` incohérente avec `validation_type="monte_carlo"` (mirroring des
    tests déjà existants pour `"walk_forward"`) ; régression complète de
    `tests/test_validation_run.py` reste 100 % verte, y compris tous les tests Walk-Forward
    déjà en place (Slices 1 à 8 d'AF-V-02), jamais modifiés.

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- L'ALGORITHME de simulation lui-même (permutation, bootstrap, percentiles, autocorrélation, série
  de pertes) — nouveau module `monte_carlo.py`, tranche suivante (AF-V-03 Slice 2). Cette tranche
  ne construit QUE la forme typée, jamais peuplée par un calcul réel (même principe que Slice 1
  d'AF-V-02 pour `WalkForwardEvidence`).
- Toute politique concrète de seuils PASS/FAIL (Décision 12 de l'ADR) — jamais inventée.
- Toute modification de `validation_run.py` au-delà des ajouts additifs listés ci-dessus (jamais
  toucher `WalkForwardSpecification`/`WalkForwardEvidence`/`OosValidationEvidence`/
  `build_validation_run()`/`save_validation_run()`/`load_validation_run()`/`_VALIDATION_TYPES`'s
  entrées existantes).
- Intégration `app.py`, câblage `walk_forward.py`/`validation_oos.py` — hors scope.

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `validation_run.py` reste un leaf.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète).
- Ne rien déclarer `PASS`/robuste — cette tranche ne produit aucune évidence réelle, seulement la
  forme typée.
