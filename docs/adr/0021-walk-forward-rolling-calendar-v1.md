# Walk-Forward V1 : géométrie rolling calendaire, folds indépendants, Top-1 TRAIN, agrégation OOS concaténée

Status: Proposé

**Contexte** : `AF-V-02` (Walk-Forward) est `READY` — toutes les préconditions scientifiques
identifiées avant lui sont `DONE` (Dette A, Dette B, correction TRAIN/TEST exacte — ADR 0018,
WARMUP dynamique — ADR 0019, State/Session Readiness V1 — ADR 0020). Cette mission est une
**conception documentaire finale**, immédiatement avant l'implémentation : elle fige la
géométrie, le modèle de domaine, les invariants scientifiques, la persistance/reprise et la
matrice TDD. **Aucun code n'est modifié par cette mission.** Le statut reste `Proposé` tant que
l'utilisateur n'a pas validé explicitement les décisions ci-dessous — voir la section
« Conséquences » en fin de document pour la liste des points restant à valider.

**Constat de départ, vérifié dans le dépôt réel (pas supposé)** : `optimizer.py::Optimizer.run()`
(lignes ~952-1080) couple aujourd'hui la recherche TRAIN et une phase de validation TEST qui
évalue **plusieurs** candidats (`top_to_validate = [...][:cfg.top_k_save]`, `top_k_save` par
défaut = 100) — un comportement scientifiquement inadapté à Walk-Forward, qui doit préserver
l'indépendance de TEST (voir Décision 6). Le `DatasetSplitPlan` réel de Perfect Revolution
(`results/dataset_splits/split_perfect_revolution_v1_final_holdout/split_plan.json`) a
`validation: null` — la zone `VALIDATION` n'a **jamais** eu de consommateur réel jusqu'ici ; ce
sera donc le premier (voir Décision 8).

## Décision 1 — Géométrie Rolling, préréglage P24M/P6M/P6M, durées calendaires

`WalkForwardSpecification.geometry = "rolling"` pour V1. `train_period="P24M"`,
`test_period="P6M"`, `step_period="P6M"` (invariant V1 : `step_period == test_period`, seule
condition garantissant des fenêtres TEST contiguës et non chevauchantes par construction — voir
Décision 4). Durées **calendaires** (mois civils), jamais un nombre de barres — un nombre de
barres varierait avec les week-ends/jours fériés/qualité des données, cassant la comparabilité
d'un fold à l'autre. Le champ `geometry` reste un point d'extension explicite :
`geometry != "rolling"` lève `UnsupportedWalkForwardGeometry`, jamais une conversion silencieuse.
`WalkForwardSpecification.allow_partial_last_fold = False`, **fixé, non paramétrable en V1** : si
le dernier segment restant après le dernier fold complet est plus court qu'un `test_period` entier,
il est **enregistré** (dans `state.json`/`manifest.json`, pour audit et pour ne pas redonner
l'impression qu'une portion de `VALIDATION` a été silencieusement ignorée) mais **jamais exécuté
ni compté** comme fold comparable — aucun `TEST` raccourci, jamais de dégradation silencieuse de
la géométrie déclarée.

**Alternatives rejetées pour V1, gardées FUTURE** : **Anchored** (TRAIN démarre toujours au même
point, grandit à chaque fold) — utile pour mesurer la dégradation d'un jeu de paramètres figé
dans le temps, mais change la question scientifique posée (stabilité d'un choix vs. capacité de
ré-optimisation périodique) ; **Hybride** — combinaison des deux, complexité non justifiée sans
un premier retour d'expérience Rolling. Aucune des deux n'est implémentée, même partiellement.

## Décision 2 — Modèle de domaine : pas de `WalkForwardRun`, extension du registre `ValidationRun`

`validation_run.py::_VALIDATION_TYPES` gagne une entrée `VALIDATION_TYPE_WALK_FORWARD =
"walk_forward"` → `(WalkForwardSpecification, WalkForwardEvidence)`, exactement le mécanisme déjà
posé par `AF-V-06` pour `"oos"`. **Aucun nouveau `WalkForwardRun`** : `ValidationRun` porte déjà
`research_run_id`/`split_plan_id`/`dataset_snapshot_id`/`strategy_name`/`strategy_params` — un
objet parallèle dupliquerait ces champs sans capacité nouvelle (test de suppression : si
`WalkForwardRun` disparaît, rien ne devient impossible, `ValidationRun` couvre déjà le rôle).
Relation `ResearchRun` : **1:1** pour V1 (un Walk-Forward = un effort de recherche global ; les
recherches TRAIN par fold restent un détail d'exécution interne du protocole, jamais réifiées en
`ResearchRun` séparées — `ValidationCampaign`, déjà `PROPOSED`, couvrira un futur 1:N si besoin).

`WalkForwardSpecification`/`WalkForwardEvidence` et leurs types imbriqués (`FoldDefinition`,
`FoldSelection`, `FoldResult`, `AggregateResult`) sont définis **dans `validation_run.py`**
(jamais dans `walk_forward.py`) — mirroring exact d'`OosValidationSpecification`/
`OosValidationEvidence`. **Alternative rejetée** : les définir dans `walk_forward.py` et les
importer dans `validation_run.py` pour le registre — rejetée à cause du sens de dépendance :
`walk_forward.py` a besoin d'appeler `validation_run.build_validation_run()` en fin de run, donc
`walk_forward.py → validation_run.py` est le seul sens d'import viable sans cycle ; l'inverse
créerait un import circulaire. `validation_run.py` reste ainsi l'unique source canonique de toute
forme `Specification`/`Evidence` typée, quel que soit le `validation_type`.

## Décision 3 — `FoldDefinition` minimal : pas de champ `train_start` "requested" (jamais ajusté)

```text
FoldDefinition (frozen) :
    fold_index: int
    fold_id: str                  # f"fold_{fold_index:03d}"
    train_start: str              # calendaire pur, jamais ajusté (voir ci-dessous)
    requested_boundary: str       # = train_start + train_period (cible calendaire)
    effective_boundary: str       # resolve_state_ready_boundary(requested_boundary, spec)
    boundary_adjusted: bool
    requested_test_end: str       # = requested_boundary + test_period (cible calendaire)
    effective_test_end: str       # resolve_state_ready_boundary(requested_test_end, spec)
    test_end_adjusted: bool
    is_last_fold: bool
```

`train_start` n'a **jamais** de variante `effective` : ce n'est pas un oubli, c'est le même
traitement que le début d'une sélection d'exécution aujourd'hui (`ExecutionWindow`/
`resolve_execution_window()`) — seule une frontière **interne** à une exécution continue (un
point de split, où la stratégie doit reprendre un état de session cohérent) a besoin d'un
ajustement readiness ; un point de **démarrage** n'a pas de session précédente à honorer, le
moteur démarre simplement à la première barre disponible (même principe que l'ADR 0020, Décision
2 : "le moteur démarre à la première barre réellement disponible — aucune donnée perdue"). Une
Opening Range partiellement fausse le tout premier jour d'un fold TRAIN est un bruit local,
borné à ce seul jour, qui n'affecte ni l'indépendance TRAIN/TEST ni la comparabilité inter-fold —
ce n'est donc pas une dette supplémentaire.

**Champs explicitement écartés** (test de suppression, `/domain-modeling` + `/codebase-design`) :
`requested_train_start`/`effective_train_start` (jamais divergents, aucun consommateur) ;
`test_start` comme champ séparé (serait toujours strictement égal à `effective_boundary` — le
dupliquer romprait le principe déjà établi par `TrainTestWindows`, où **une seule** valeur
`boundary` sert les deux rôles TRAIN-end/TEST-start, jamais deux champs pouvant diverger par
erreur).

## Décision 4 — Non-chevauchement OOS garanti par déterminisme, jamais par coordination inter-fold

Chaque fold résout **indépendamment** ses deux frontières (`effective_boundary`,
`effective_test_end`) via `resolve_state_ready_boundary()`, réutilisée telle quelle depuis
`strategy_contracts.py` — **aucune donnée n'est jamais passée d'un fold à l'autre pour ce calcul**.
La non-duplication/non-perte de barres entre `TEST_k` et `TEST_{k+1}` n'est donc pas assurée par
une coordination explicite, mais **dérivée par construction** : avec `step_period == test_period`,
`requested_test_end` du fold `k` est arithmétiquement identique à `requested_boundary` du fold
`k+1` (même instant calendaire) ; `resolve_state_ready_boundary()` étant une fonction **pure**
(mêmes entrées → même sortie), `effective_test_end_k == effective_boundary_{k+1}` est **garanti**,
**à condition que `readiness_spec` soit LUI AUSSI identique aux deux appels** — prémisse qui doit
être rendue explicite, pas seulement supposée (trouvaille `/code-review`, revue adversariale de
cette mission) : **`WalkForwardSpecification` fige UN SEUL `base_params`**, utilisé à la fois
comme `ValidationRun.strategy_params` (le même champ, même sémantique que pour `"oos"` : un jeu de
paramètres fixe décrivant le run, pas une valeur par fold) et comme argument unique de
`strategy.state_readiness(base_params)` pour **la résolution de frontière de TOUS les folds**,
quel que soit ce que la recherche TRAIN de chaque fold sélectionne ensuite pour les dimensions
réellement balayées (`FoldSelection.selected_params`, distinct, jamais utilisé pour la readiness).
Concrètement aujourd'hui, `or_start_h`/`or_start_m` (les seuls paramètres lus par
`Strategy.state_readiness()`, voir `strategies/perfect_revolution_v1.py`) ne font pas partie du
`PARAM_SCHEMA` balayable — cette prémisse est donc automatiquement vraie avec l'espace de recherche
actuel, mais **doit rester une invariant explicite de `WalkForwardSpecification`**, pas une
coïncidence non documentée : si une future stratégie exposait `or_start_h`/`or_start_m` comme
paramètres balayables, ce théorème de non-chevauchement cesserait de tenir et devrait être
reconsidéré avant d'autoriser leur ajout au search space d'un Walk-Forward. Un test de régression
dédié (voir matrice TDD) doit vérifier `effective_test_end_k == effective_boundary_{k+1}`
directement sur l'implémentation, jamais seulement supposer l'argument ci-dessus.

**Sémantique d'inclusivité, TRAIN et TEST** : `TRAIN_k = [train_start_k, effective_boundary_k)`
(exclusif — même contrat que `TrainTestWindows`, jamais deux valeurs indépendantes pouvant
diverger). `TEST_k = [effective_boundary_k, effective_test_end_k)` (demi-ouvert)
pour tout fold **non terminal** — sinon la barre exactement à la frontière partagée serait comptée
deux fois. `TEST_N = [effective_boundary_N, effective_test_end_N]` (**inclusif**) pour le
**dernier** fold uniquement — généralisation directe et non inventive du précédent déjà établi par
`TrainTestWindows` (`TRAIN` exclusif / `TEST` terminal inclusif), étendue à N zones chaînées au
lieu de 2. `WALK_FORWARD_SEMANTICS_VERSION = "rolling-calendar-v1"` fige ce contrat, indépendant
de `TRAIN_TEST_SEMANTICS_VERSION`/`STATE_READINESS_SEMANTICS_VERSION` (troisième contrat
scientifique distinct, même famille de garde de reprise — voir Décision 9).

## Décision 5 — Common Window Rule et warmup causal déjà satisfaits par l'architecture existante, aucun nouveau mécanisme

Le risque identifié par la mission (avantager un candidat parce qu'il aurait "vu" plus ou moins de
données que ses concurrents) est **déjà structurellement exclu** par `resolve_execution_window()`
(Dette A) : `context_df` est le même historique complet pour **tous** les candidats d'un même
fold TRAIN — seul `loop_start = max(exec_start_idx, required_warmup(params))` varie par candidat,
et varier ce seuil selon le warmup réel de CHAQUE candidat est correct (représenter fidèlement son
besoin), pas un avantage. **Aucun nouveau mécanisme de "fenêtre commune" n'est nécessaire** :
Walk-Forward doit seulement réutiliser `resolve_execution_window()`/`required_warmup()` sans les
réimplémenter ni les contourner par une troncature de contexte par candidat.

**Warmup causal** (précision terminologique de clôture) : « causal » signifie ici que la
convergence d'un indicateur à l'instant `i` ne dépend jamais de barres postérieures à `i` —
propriété déjà garantie par `required_warmup(params)`/`loop_start` (ADR 0019), simplement
réutilisée ici, jamais réimplémentée. **Nouveau garde-fou, propre à Walk-Forward** :
`InsufficientWarmupHistory` est levée **avant**
l'exécution du fold 0 si l'historique disponible avant son `train_start` est plus court que
`max(strategy.required_warmup(p) for p in search_space)` — contrairement au moteur/Optimizer
générique (qui dégrade silencieusement via `loop_start`, ADR 0019, section Conséquences), Walk-Forward est ici
volontairement **plus strict** que le comportement legacy : un premier fold sous-alimenté en
warmup ne serait pas comparable aux suivants (qui héritent toujours de plus d'historique par
construction), ce qui biaiserait spécifiquement l'analyse inter-fold (Parameter Stability future).
Seul le fold 0 peut être concerné — tout fold suivant dispose strictement de plus d'historique.

## Décision 6 — Sélection TRAIN Top-1, seam `Optimizer` TRAIN-only

`S1 = Top-1 TRAIN` (mission, section 11) : un seul `ParameterSet` par fold est exposé à TEST,
choisi exclusivement sur les données TRAIN. **`Optimizer.run()` n'est pas réutilisée telle
quelle** : sa phase de validation actuelle (`top_to_validate = [...][:cfg.top_k_save]`) évalue
**plusieurs** candidats sur TEST — la réutiliser gaspillerait jusqu'à `top_k_save` backtests TEST
par fold et surtout romprait `S1`/l'isolation TEST (Décision 7). **Nouveau seam minimal, additif** :
`Optimizer.run(..., run_test_validation: bool = True)` — `False` saute la phase de validation
existante (lignes ~1044-1065) sans y toucher autrement ; comportement par défaut **strictement
inchangé** pour tout appelant existant (`app.py`, tout job actuel). Walk-Forward appelle
`Optimizer.run(run_test_validation=False)`, prend `all_results[0]` (meilleur score TRAIN) comme
`FoldSelection.selected_params`, puis exécute **exactement une fois** `optimizer._run_single()`
(réutilisée telle quelle, déjà top-level et picklable) sur `[effective_boundary, effective_test_end]`
pour produire le `FoldResult`.

**Précision issue de la revue adversariale de cette mission** : l'appel `Optimizer.run()` fait
pour la recherche TRAIN d'un fold doit être configuré avec `train_test.enabled=False` (fenêtre
d'exécution bornée directement à `[train_start_k, effective_boundary_k)` via
`opt_start_date`/`opt_end_date`, jamais un second split interne) — cela évite structurellement
toute double résolution de frontière : `resolve_state_ready_boundary()` n'est appelée **qu'une
seule fois par frontière de fold**, par `walk_forward.py` lui-même (Décision 4), jamais une
seconde fois à l'intérieur de l'appel `Optimizer.run()` du fold (qui, avec `train_test.enabled=
False`, ne passe jamais par `compute_split_dates()`/`resolve_state_ready_boundary()` en interne —
voir `optimizer.py`, le bloc `if tt.enabled:` n'est jamais atteint dans ce cas).

**Alternative rejetée** : une nouvelle méthode publique `Optimizer.run_train_only()` dupliquant la
signature de `run()` — rejetée : un simple paramètre booléen additif évite de maintenir deux
points d'entrée documentés pour un seul comportement de recherche, sans rien retirer à la
lisibilité (nom explicite, défaut rétrocompatible).

**Précision issue de la relecture de clôture de cette mission** : `_run_single()`, telle qu'elle
existe réellement (`optimizer.py:266`, `_, _, stats = run_backtest(...)`), **jette** les DataFrames
`trades`/`equity` renvoyés par `run_backtest()` et ne garde que `stats`. Or la persistance déclarée
en Décision 12 exige `oos_trades.csv`/`oos_equity.csv` **par fold**, et `FoldResult.expectancy`
(Décision 15) se calcule à partir des trades individuels, pas de `stats` seul (`engine.py`
n'expose aucun champ `expectancy`, `CONTEXT.md` le documente déjà comme non défini
projet-wide). **La phase TEST d'un fold ne peut donc pas réutiliser `_run_single()` telle quelle
sans modification** : soit `_run_single()` gagne un paramètre optionnel renvoyant aussi
`trades`/`equity` (rétrocompatible, `None` par défaut pour tout appelant existant), soit
`walk_forward.py` appelle `run_backtest()` directement pour la phase TEST (même chemin que
`_run_single()` emprunte déjà en interne, sans repasser par son enveloppe qui les jette) — choix
d'implémentation à trancher lors de la mission suivante, pas une décision scientifique. Ce que
cette ADR fige : **`expectancy` est une métrique introduite par Walk-Forward lui-même**, pas un
champ natif d'`engine.py` — `PnL net moyen par trade = trades["resultat_net"].mean()` sur les
trades du `TEST_k` considéré, même unité que les trades (devise du capital), `None` si
`n_trades == 0` (jamais une valeur inventée pour combler l'absence de trades).

## Décision 7 — Isolation TEST structurelle, pas de verrou objet

Après construction de `FoldSelection` (frozen dataclass), aucun code de `walk_forward.py` ne
rappelle la phase TRAIN pour ce fold — l'isolation est **garantie par le flux du protocole**
(séquencement), pas par une protection mémoire Python (qui ne peut de toute façon pas empêcher une
mutation interne d'un `dict` référencé). C'est la même dette assumée que celle déjà documentée
pour `ValidationRun`/`DatasetSplitPlan` (pas de `__post_init__`, la discipline vient des fonctions
`build_*()`/de l'appelant, pas de l'objet) — cohérent avec le reste du dépôt, pas une régression
propre à Walk-Forward.

## Décision 8 — Les folds Walk-Forward consomment la zone `VALIDATION` du `DatasetSplitPlan`

`ValidationRun.split_plan_id` référence un `DatasetSplitPlan` dont la zone `VALIDATION` est
**non nulle** et sert de conteneur macro pour l'ensemble des fenêtres de fold (TRAIN **et** TEST
confondus) — jamais la zone `TRAIN` macro (réservée à Discovery) ni `FINAL_HOLDOUT` (Décision 10).
**Terminologie explicitement désambiguïsée** : le "TRAIN"/"TEST" d'un fold Walk-Forward est un
concept **imbriqué**, distinct de la partition macro à 4 zones `TRAIN`/`VALIDATION`/
`DISCOVERY_OOS`/`FINAL_HOLDOUT` — toujours qualifiés "fold TRAIN"/"fold TEST" dans le code et la
documentation pour éviter la confusion déjà identifiée par `CONTEXT.md` sur le mot "split".

**Constat vérifié, pas supposé** : le `DatasetSplitPlan` réel utilisé pour Perfect Revolution
(`split_perfect_revolution_v1_final_holdout`) a `validation: null` — `VALIDATION` n'a jamais eu de
consommateur réel. **Aucun plan existant n'est modifié** (`DatasetSplitPlan` est immuable,
`save_dataset_split_plan()` refuse un `split_plan_id` déjà écrit) : la mission d'implémentation
devra construire un **nouveau** `DatasetSplitPlan` (nouveau `split_plan_id`), réutilisant le même
`dataset_snapshot_id`, avec `final_holdout` **identique** à l'existant
(`2025-05-19T00:00:00+00:00` → `2026-05-20T00:00:00+00:00`, jamais déplacé) et une zone
`VALIDATION` découpée dans l'actuelle zone macro `TRAIN` (qui couvre aujourd'hui `2017-10-31` →
`2025-05-19`, soit ~7,5 ans au total). **Aucune borne précise pour `VALIDATION` n'est fixée par
cette ADR** — un exemple à 5 folds a été construit à titre purement illustratif (dates fictives,
non retenues) pour vérifier la faisabilité calendaire, jamais comme une allocation actée : le
choix exact de la durée/des bornes
de `VALIDATION` (combien d'années réserver à Walk-Forward vs. laisser à Discovery) reste un
**prérequis d'implémentation à trancher séparément**, pas une décision scientifique de cette ADR
(voir section « Conséquences » ci-dessous).

## Décision 9 — Versioning et garde de reprise, troisième contrat indépendant

`WALK_FORWARD_SEMANTICS_VERSION = "rolling-calendar-v1"`, indépendante de
`TRAIN_TEST_SEMANTICS_VERSION`/`STATE_READINESS_SEMANTICS_VERSION` — même famille de garde,
`validate_resume_walk_forward_semantics()` mirroring exact des deux fonctions existantes,
`WalkForwardSemanticsMismatch(ValueError)`. `fold_seed = sha256(f"{master_seed}:
{validation_run_id}:{fold_index}:wf-fold-seed-v1")` (jamais `hash()`/`time.time()`/
`random.randint()` — déterministe, indépendant du nombre de workers). `master_seed` obligatoire
uniquement si l'algorithme de recherche est stochastique (`NonDeterministicSearchWithoutSeed`
sinon) — sans objet pour les modes actuellement supportés par `optimizer.py`
(`single_var`/`cross_zone`/`grid`/`general`, tous déterministes), champ posé par anticipation d'un
futur mode stochastique (Random/Genetic/Bayesian/CMA-ES, hors scope V1).

## Décision 10 — `FINAL_HOLDOUT` structurellement inaccessible, jamais un fold implicite

Aucun champ de `WalkForwardSpecification`/`FoldDefinition`/`WalkForwardEvidence` ne référence
jamais `FINAL_HOLDOUT` — l'exclusion est **architecturale** (les fenêtres de fold sont dérivées
exclusivement de la zone `VALIDATION` du plan référencé), pas seulement documentée. Avant
exécution, `walk_forward.py` vérifie que la zone `VALIDATION` du plan ne chevauche pas
`final_holdout` du même plan (`FinalHoldoutOverlapError` sinon — garde défensive, la construction
correcte d'un `DatasetSplitPlan` via `build_dataset_split_plan()` refuse déjà tout chevauchement
entre zones adjacentes, donc ce garde ne devrait jamais se déclencher avec un plan bien formé,
mais protège contre un plan construit hors du chemin normal). Aucun `HoldoutAccessEvent` n'est
jamais créé par un Walk-Forward normal. `FINAL_HOLDOUT` ne devient **jamais** un dernier fold
implicite — principe déjà acté dans `dataset_split.py`/`EPICS_AND_TICKETS.md` (AF-V-02), confirmé
inchangé ici.

## Décision 11 — Taxonomie d'erreurs consolidée, réutilisation prioritaire

Consolidation par rapport à la liste initiale de la mission (section 34), sur le principe "ne pas
créer une classe par micro-cas" :

- **Réutilisée comme TYPE, jamais avec le message générique tel quel** : `NoStateReadyBoundary`
  (`optimizer.py`) — une frontière de fold qui collapse est structurellement le même problème
  qu'une frontière de split TRAIN/TEST classique, et conserver le même type permet à tout code
  appelant (garde de reprise, tests) de traiter les deux cas uniformément (`except
  NoStateReadyBoundary`). **Précision issue de la revue adversariale de cette mission** : le
  message actuel de `optimizer.py` est câblé pour un seul triplet `(train_start, effective_
  boundary, test_end)` et ne mentionne aucun fold — le réutiliser **verbatim** produirait un
  message trompeur pour l'un des deux effondrements possibles par fold (`effective_boundary`
  collapsée, ou `effective_test_end` collapsée) et ne dirait jamais QUEL fold a échoué parmi N.
  `walk_forward.py` doit donc construire son **propre message** à chaque site de levée (incluant
  `fold_id`/`fold_index` et lequel des deux calculs a échoué) tout en levant la **même classe**
  `NoStateReadyBoundary` — réutilisation du type, jamais du texte.
- **Nouvelles, nécessaires** : `UnsupportedWalkForwardGeometry`, `DatasetTooShortForWalkForward`
  (zéro fold calculable — absorbe les cas "dataset trop court" et "aucun fold valide", même
  remède : élargir `VALIDATION` ou réduire la géométrie), `InsufficientWarmupHistory` (fold 0
  uniquement), `NonDeterministicSearchWithoutSeed`, `NoEligibleTrainCandidate`,
  `FinalHoldoutOverlapError`, `WalkForwardResumeMismatch`, `WalkForwardSemanticsMismatch`,
  `FoldArtifactConflict`, `OosOverlapError` (garde défensive interne — devrait être
  mathématiquement impossible à déclencher si la Décision 4 est correctement implémentée ; gardée
  comme filet de sécurité testé, pas comme une erreur utilisateur réaliste).
- **Écartées, redondantes** : `NoValidWalkForwardFold` (fusionnée dans
  `DatasetTooShortForWalkForward`), `EmptyTrainWindow`/`EmptyTestWindow` (structurellement
  impossibles — une durée `train_period`/`test_period` positive ne peut produire une fenêtre vide ;
  le seul cas d'effondrement réel est déjà couvert par `NoStateReadyBoundary` réutilisée).

## Décision 12 — Persistance additive, `results/job_xxx/walk_forward/`

Structure proposée par la mission (section 27) confirmée, sans modification : `manifest.json`
(fingerprint de reprise), `state.json` (folds terminés), `folds/fold_NNN/{definition,tested,
selection,test_result}.json` + `{train_candidates,oos_trades,oos_equity}.csv`, `aggregate.json`,
`validation_run.json` (produit via `validation_run.save_validation_run()`, jamais un format
parallèle). Réutilise `atomic_json_store.py` (écriture atomique, lecture tolérante) — aucune
primitive dupliquée. Fingerprint de reprise : dataset snapshot, stratégie, git SHA (déjà capturé
par `data_manifest.json`, réutilisé, jamais recalculé indépendamment), search space, scoring,
filtres, géométrie, versions de sémantique (x3), `master_seed`, référence de politique de verdict.
Un fold déjà terminé (artefacts complets et cohérents avec le fingerprint) est sauté à la reprise ;
un TRAIN interrompu réutilise les candidats déjà exécutés (fingerprint identique) ; un TEST
interrompu est **rejoué entièrement** avec la `FoldSelection` déjà figée (jamais une nouvelle
sélection) ; un agrégat interrompu est **recalculé intégralement** depuis les folds terminés.

## Décision 13 — Séparation stricte preuve factuelle / verdict scientifique

`FoldResult`/`AggregateResult` ne portent que des faits mesurés (section 20/22 de la mission :
zéro valeur inventée, `None` explicite si non calculable — ex. `profit_factor=None` si
`n_trades=0`). `WalkForwardEvidence.scientific_verdict ∈ {"PASS","INCONCLUSIVE","FAIL"}` est la
**seule** valeur de jugement, elle-même contrainte : `PASS` est **structurellement impossible**
sans `WalkForwardSpecification.verdict_policy_id` non-`None` référençant une politique de seuils
**pré-enregistrée** (jamais inventée après coup) — en son absence, le verdict est toujours
`INCONCLUSIVE` avec une raison explicite (`verdict_reasons`), jamais un repli silencieux vers
`PASS`/`FAIL`. Ce verdict n'est **pas** une décision Champion : une future notion de Champion
(hors scope) agrégera plusieurs types de validation (`GATE V` : OOS + Walk-Forward + Monte-Carlo +
Parameter Stability) et sa propre politique — `PASS` ici est nécessaire mais jamais suffisant pour
un futur Champion.

**`execution_status` distinct de `scientific_verdict`** (précision ajoutée en relecture finale,
checklist de clôture) : `WalkForwardEvidence.execution_status` (ex. `"completed"`, mirroring
`ValidationRun.status` existant, purement structurel) répond à « le run a-t-il pu s'exécuter
jusqu'au bout, sans lever d'exception non gérée ? ». `scientific_verdict` répond à une question
totalement différente : « la preuve produite satisfait-elle une politique scientifique
pré-enregistrée ? ». Une erreur technique (ex. un crash de process, un fichier corrompu détecté à
la reprise) **n'est jamais** traduite en `FAIL` scientifique — elle interrompt le run avant qu'un
`WalkForwardEvidence` complet n'existe (l'exception remonte, voir taxonomie Décision 11), elle ne
produit jamais une `WalkForwardEvidence` avec `execution_status="completed"` et
`scientific_verdict="FAIL"` pour une raison purement technique.

## Décision 14 — Indépendance stricte des folds, `flat_each_fold_v1`, aucune rétroaction TEST inter-fold

**Trouvé manquant lors de la relecture finale de cette mission** (checklist explicite de clôture) —
deux garanties déjà décidées en amont mais jamais transcrites dans le corps de l'ADR.

`position_transition_policy = "flat_each_fold_v1"` (champ de `WalkForwardSpecification`) : chaque
exécution TEST d'un fold démarre avec une **instance `Strategy()` fraîche**, un **capital initial
identique** à celui de tout autre fold (`global_params.initial_capital`, jamais le capital
terminal d'un fold précédent), **aucune position ouverte héritée**, **aucun PnL reporté** — même
mécanisme déjà correct pour TRAIN/TEST classique (`_run_single()` charge une nouvelle instance via
`_load_strategy()` à chaque appel, réutilisée telle quelle, Décision 6). Toute clôture forcée en
fin de fenêtre de fold est comptée dans `FoldResult.forced_closes`, jamais silencieusement ignorée.
L'agrégateur reconstruit ensuite une **courbe OOS synthétique normalisée** en chaînant les
rendements de chaque fold (méthode précisée en Décision 15) — jamais une simple concaténation des
valeurs de capital absolues (`equity`), qui produirait un artefact en dents de scie à chaque
frontière de fold puisque `flat_each_fold_v1` réinitialise le capital à l'identique à chaque fold.
Le fold `k+1` n'est jamais réellement exécuté avec le capital terminal du fold `k`. Le report de
position entre folds n'est **pas** construit en
V1 (`flat_each_fold_v1` explicitement versionné pour permettre une politique différente plus tard
sans casser la sémantique actuelle).

**Aucune rétroaction d'un fold vers un autre** : le résultat TEST du fold `k` (`FoldResult`,
`score_test`, `AggregateResult` partiel) ne modifie **jamais**, pour le fold `k+1` ou suivant, le
search space, le scoring, les filtres, le poids, la stratégie, le broker model, le seed, la
méthode de recherche ni le budget — tous fixés une fois pour toutes par `WalkForwardSpecification`
au début du run. Seules les **données de prix** avancent dans le temps d'un fold à l'autre (le
TEST d'un ancien fold devient naturellement de l'historique disponible pour le TRAIN d'un fold
plus récent, par construction de la géométrie Rolling elle-même) — jamais les **résultats**. Pas
de warm-start de la recherche TRAIN avec le gagnant du fold précédent en V1 : chaque
`Optimizer.run(run_test_validation=False)` par fold repart du même search space complet, déclaré
une fois dans `WalkForwardSpecification`, jamais réduit/biaisé par un fold antérieur.

**Distinction avec la Décision 12 (reprise)**, à ne pas confondre : la reprise lit les artefacts
d'un fold déjà terminé pour décider de le **sauter** (bookkeeping de complétude — fingerprint,
présence des fichiers), elle ne lit **jamais** le résultat TEST d'un fold pour modifier le search
space/scoring/seed/budget d'un fold **différent**, terminé ou non — la garantie de cette Décision
14 porte sur le contenu du protocole, pas sur son état d'avancement.

## Décision 15 — Agrégation OOS concaténée, jamais une moyenne de ratios ; zéro-trade TEST = observation, jamais un FAIL automatique

**Également trouvé manquant lors de la relecture finale** — l'`AggregateResult` était nommé dans
le modèle de domaine sans que sa méthode de calcul soit figée par écrit.

La métrique OOS principale est la **série concaténée chronologiquement** des trades de tous les
`TEST_k` (moyenne/médiane/pire-fold restent des diagnostics **secondaires**, jamais la mesure
principale). **Deux règles de concaténation distinctes, jamais confondues** (précision issue de la
relecture de clôture de cette mission — cette Décision et la Décision 14 devaient être réconciliées
sur ce point) : les **trades** individuels se concatènent **littéralement**, dans l'ordre
chronologique, valeurs de PnL inchangées (`gross_win_total`/`gross_loss_total`/comptage de trades
sont des sommes/dénombrements, insensibles au capital de base de chaque fold — aucune
renormalisation nécessaire) ; la **courbe d'équity** OOS, elle, ne peut **jamais** être une
concaténation brute des valeurs absolues de capital (chaque fold redémarre au même
`initial_capital`, `flat_each_fold_v1` — une simple concaténation produirait un artefact en dents
de scie à chaque frontière de fold) : elle est reconstruite en **chaînant les rendements
normalisés** de chaque fold (exemple : fold `k` `+5 %` puis fold `k+1` `-2 %` donne `1.00 → 1.05 →
1.029`, jamais `1.00 → 1.05` puis un nouveau `1.00 → 0.98` disjoint), et c'est **cette courbe
normalisée**, pas la courbe brute, qui sert de base à `oos_max_dd_pct`. Sur la série de trades
concaténée : `AggregateResult.oos_profit_factor = gross_win_
total / gross_loss_total` (mêmes noms de grandeur que `engine.py::_compute_stats()`, jamais un
renommage `gross_profit`/`gross_loss` inventé) — jamais la moyenne des `profit_factor` par fold
(une moyenne de ratios n'est pas le ratio de la somme, et masquerait un fold très négatif derrière
plusieurs folds neutres). **Casuistique alignée sur le moteur réel, pas inventée** (trouvaille de
relecture finale) : `gross_loss_total == 0` avec `total_oos_trades > 0` (aucun trade perdant sur
toute la série OOS) donne `oos_profit_factor = float("inf")` — exactement la convention déjà
utilisée par `engine.py:502` (`profit_factor = gross_win / gross_loss if gross_loss > 0 else
float("inf")`), jamais `None` dans ce cas précis ; `None` reste réservé au seul cas
`total_oos_trades == 0` (aucune donnée sur laquelle calculer quoi que ce soit), cohérent avec
`OosValidationEvidence`. `oos_win_rate = total_winners /
total_trades` (jamais une moyenne de taux) ; `oos_max_dd_pct` recalculé directement sur la courbe
OOS globale (jamais la moyenne/le pire des `max_dd_pct` par fold, qui ignorerait un drawdown
s'étalant sur la jonction entre deux folds) ; `oos_net_return_pct` par composition chronologique
(jamais une simple somme de pourcentages) ; `oos_sharpe` reste `None` en V1 (réservé — aucune
convention de rendement périodique/annualisation n'est figée par cette mission, jamais une valeur
inventée pour remplir le champ).

**Zéro trade** : au TRAIN, un candidat à zéro trade est **non éligible** (déjà filtré par
`compute_score()`/`_run_single()` existants, comportement inchangé) ; si **tous** les candidats
TRAIN d'un fold sont à zéro trade, `NoEligibleTrainCandidate` (Décision 11) — le fold n'a pas de
`FoldSelection`. Au **TEST**, zéro trade reste une **observation scientifique valide**, jamais une
erreur ni un repli automatique vers `FAIL` : `FoldResult.zero_trade_oos = True`,
`n_trades = 0`, `net_ret_pct = 0`, `profit_factor = win_rate = expectancy = None` (jamais une
valeur inventée) — ce fold contribue tel quel à `AggregateResult` (`n_folds_zero_trade`
incrémenté), et seule une politique de verdict explicite (`verdict_policy_id`, Décision 13) peut
décider si une proportion trop élevée de folds à zéro trade rend le run global `INCONCLUSIVE`.

## Conséquences

- **`AF-V-02 implementation: NOT STARTED`, `GATE V: NOT PASSED`** — cette mission ne modifie aucun
  code, aucune configuration, aucun comportement d'exécution.
- **Premier consommateur réel de la zone `VALIDATION`** de `DatasetSplitPlan`, jusqu'ici
  purement optionnelle et jamais exploitée.
- **Dépendance d'implémentation identifiée, non résolue par cette ADR** : construction d'un
  nouveau `DatasetSplitPlan` avec `VALIDATION` peuplée avant tout premier fold réel (voir
  Décision 8) — étape 0 de la future mission d'implémentation, pas une décision scientifique.
- **Points restant à valider explicitement par l'utilisateur avant implémentation** : préréglage
  exact d'allocation de `VALIDATION` (durée, bornes — Décision 8) ; choix définitif entre le flag
  `run_test_validation` et une méthode séparée sur `Optimizer` (Décision 6) ; confirmation
  qu'aucune politique de verdict (`verdict_policy_id`) n'existe encore — implique `INCONCLUSIVE`
  systématique en V1 tant qu'elle n'est pas fournie (Décision 13) ; et l'invariant « un seul
  `base_params` partagé par tous les folds pour la résolution de readiness » (Décision 4), à
  confirmer avant tout élargissement futur du search space de Perfect Revolution.
