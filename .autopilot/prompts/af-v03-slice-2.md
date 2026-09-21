# Mission AF-V-03 Slice 2 — Algorithme `monte_carlo.py` (permutation, bootstrap, ADR 0022)

**Lire intégralement `docs/adr/0022-monte-carlo-trade-resampling-v1.md`** (déjà revue/corrigée/
committée, `bfbc671`) avant de commencer — cette mission implémente STRICTEMENT ses Décisions
1 à 10/13/14. AF-V-03 Slice 1 (contrats typés `MonteCarloSpecification`/`MonteCarloEvidence`/
`MonteCarloDistributionSummary`/`MonteCarloSemanticsMismatch`/`build_monte_carlo_specification()`)
est terminée et poussée — NE PAS la modifier, réutiliser telle quelle.

## Ce qui est DANS cette tranche

Nouveau module top-level `monte_carlo.py` (Décision 11 de l'ADR : jamais dans `validation_run.py`,
jamais dans `walk_forward.py` — aucun import `engine.py`/`optimizer.py`/`dataset_split.py`/
`walk_forward.py`, preuve structurelle de la Décision 10 de l'ADR) :

1. **`run_monte_carlo_simulation(trades: Tuple[float, ...], spec: MonteCarloSpecification) -> MonteCarloEvidence`**
   — fonction pure, orchestre l'ensemble :
   - `n_trades = len(trades)`. Si `n_trades == 0` : retourne directement une `MonteCarloEvidence`
     avec `zero_trade_input=True`, tous les champs numériques `None`, `execution_status="completed"`
     (Décision 7 de l'ADR) — jamais une exception.
   - Dérivation du flux aléatoire, EXACTEMENT la formule de la Décision 5 de l'ADR : UN seul
     `numpy.random.default_rng(method_seed)` par méthode (`method_seed` dérivé par SHA-256 de
     `spec.master_seed`+`method`+`"mc-v1"`, jamais un générateur par simulation) — `sequence_risk`
     et `sampling_uncertainty` utilisent CHACUN leur propre générateur, jamais partagé.
   - `sequence_risk` : si `n_trades! < spec.n_simulations`, énumération EXHAUSTIVE
     (`itertools.permutations`, jamais de tirage aléatoire, `rng` non consommé) ; sinon, tirage
     vectorisé de `spec.n_simulations` permutations distinctes via le générateur seedé (ex.
     `rng.permuted()` sur un tableau `(n_simulations, n_trades)` en un seul appel, jamais une
     ré-instanciation de `default_rng()` par simulation). Pour chaque permutation : reconstruit la
     courbe d'équité PAR PRODUIT CUMULATIF `(1 + r_i/100)` (Décision 1/2, jamais une somme), calcule
     le max drawdown SUR CETTE COURBE (base clôture de trade — voir point 2) et la plus longue série
     de pertes consécutives (compte de `r_i <= 0` consécutifs). Agrège en
     `MonteCarloDistributionSummary` (percentiles `p5`/`p25`/`p50`/`p75`/`p95`) pour les deux —
     **`sequence_risk_longest_losing_streak` : percentiles en valeurs ENTIÈRES réellement observées
     dans l'échantillon simulé, interpolation `"lower"` (JAMAIS `"linear"`, le défaut `numpy`)** —
     voir le commentaire dédié dans la Décision 11 de l'ADR sur ce point précis.
   - `sampling_uncertainty` : tirage vectorisé de `spec.n_simulations` échantillons de taille
     `n_trades` AVEC REMISE (`rng.integers(0, n_trades, size=(n_simulations, n_trades))` puis
     indexation), reconstruit la courbe (même chaînage multiplicatif), calcule le rendement net
     final ET le max drawdown (base clôture de trade) pour chaque tirage — agrège en
     `MonteCarloDistributionSummary` pour les deux (percentiles interpolés normalement, valeurs
     continues).
   - `observed_net_ret_pct`/`observed_max_dd_trade_close_basis_pct` : calculés sur la séquence
     ORIGINALE `trades` (non rééchantillonnée), MÊME chaînage multiplicatif — voir point 3 sur la
     cohérence exigée avec `AggregateResult`.
   - `observed_lag1_autocorrelation` : autocorrélation empirique standard (`numpy.corrcoef` ou
     équivalent) des `net_ret_pct` à l'ordre 1, sur la séquence originale — `None` si `n_trades < 2`
     (mathématiquement indéfini, jamais une valeur inventée).
   - `observed_longest_losing_streak` : plus longue série de `r_i <= 0` consécutifs sur la séquence
     originale, un entier (`0` si aucune perte).
   - `scientific_verdict`/`verdict_reasons`/`execution_status` : EXACTEMENT les règles de la
     Décision 12 de l'ADR — `"completed"` toujours (V1, Décision 11 de l'ADR) ;
     `spec.verdict_policy_id is None` -> `"INCONCLUSIVE"` avec raison explicite ;
     `spec.verdict_policy_id` fourni -> lève `validation_run.UnknownVerdictPolicy` (réutilisée
     TELLE QUELLE, jamais une classe dupliquée) — **aucune règle "stopped_early" ici** (contrairement
     à Walk-Forward, Monte-Carlo V1 n'a aucune notion d'interruption).
2. **`n_trades == 1`** : `sequence_risk` sur l'unique permutation possible (`n_simulations` effectif
   = 1, jamais gonflé) ; bootstrap reste bien défini (tire toujours ce même trade unique).
3. **Test de cohérence obligatoire** (Décision 13 de l'ADR) : sur une séquence de trades réellement
   concaténée depuis un run Walk-Forward construit dans le test (mirroring les fixtures de
   `tests/test_walk_forward.py`), `observed_net_ret_pct` calculé ici doit être STRICTEMENT ÉGAL
   (tolérance flottante) à `AggregateResult.oos_net_return_pct` du même run — assertion ferme, pas
   une tolérance "ou documenté".
4. Tests TDD (RED confirmé avant implémentation) — reprendre PRÉCISÉMENT la matrice de la Décision
   13 de l'ADR (déterminisme bit-à-bit, `default_rng` instancié au plus 2 fois, chaque ligne du
   tirage vectorisé indépendante, permutation préserve le rendement final, bootstrap fait varier le
   rendement final, drawdown trade-close jamais confondu avec le moteur, `n_trades! < n_simulations`
   testé pour au moins deux valeurs, `n_trades == 0`/`n_trades == 1`, `method` invalide -> `ValueError`,
   `verdict_policy_id` fourni -> `UnknownVerdictPolicy`, aucune dépendance moteur — test d'import
   statique, aucun accès holdout).
5. Régression complète (`tests/test_validation_run.py`, nouveau `tests/test_monte_carlo.py`) reste
   100 % verte, aucune modification des Slices AF-V-02/AF-V-03 Slice 1 déjà en place.

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- Persistance disque (`manifest.json`/`evidence.json` sous `results/job_xxx/monte_carlo/`, Décision
  8 de l'ADR) — tranche suivante si jugée nécessaire séparément, ou combinée si la mission juge le
  périmètre proportionné une fois l'algorithme terminé (à documenter le choix si combiné).
- Tout appelant réel produisant des trades pour Monte-Carlo (câblage OOS/Walk-Forward) — hors scope,
  `trades` reste un paramètre fourni par l'appelant, jamais recalculé ici.
- Toute politique concrète de seuils PASS/FAIL — jamais inventée.
- `n_simulations`/`master_seed` restent des CHAMPS de `spec` lus tels quels par cette fonction —
  cette tranche NE construit PAS de `MonteCarloSpecification` elle-même (déjà fait par
  `build_monte_carlo_specification()`, Slice 1), ne réinvente jamais cette discipline ici.

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `monte_carlo.py` reste un leaf sans dépendance moteur — vérifié par un test d'import statique.
- `FINAL_HOLDOUT` jamais mentionné/consulté — ce module n'a structurellement aucun moyen d'y accéder.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète).
- Ne rien déclarer `PASS`/robuste — le verdict reste structurellement `INCONCLUSIVE` sans politique.
