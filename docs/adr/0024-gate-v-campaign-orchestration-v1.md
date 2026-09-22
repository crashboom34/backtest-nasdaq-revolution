# GATE V Campaign Orchestration V1 (`AF-V-08`) : plan de campagne immuable, exécution en deux niveaux, reprise sans doublon, jamais une déclaration PASS

Status: Proposé

**Contexte** : `AF-V-02`/`AF-V-03`/`AF-V-04` (Walk-Forward, Monte-Carlo, Parameter Stability) sont
désormais tous construits et testés au niveau bibliothèque (`AI_HANDOFF.md` §33/34) — chacun
délibérément conçu pour consommer des FAITS déjà calculés par un appelant, **aucun code existant ne
relie aujourd'hui un run Walk-Forward réel à Monte-Carlo/Parameter Stability** (`AI_HANDOFF.md`
§35, écart d'orchestration identifié le 2026-09-22). Cette ADR ferme cet écart — **au niveau
CONCEPTION uniquement, aucune exécution réelle autorisée par cette mission** (ni backtest, ni
recherche `Optimizer`, ni téléchargement, ni accès `FINAL_HOLDOUT`).

**Ticket** : `AF-V-08` — identifiant disponible confirmé (`grep -rn "AF-V-08" docs/` : aucune
occurrence avant cette ADR), ne collisionne ni avec `AF-V-05` (Stress/Noise, réservé et distinct)
ni avec `AF-V-06`/`AF-V-07` (déjà attribués). **ADR** : `0024` — prochain numéro disponible
(`0023` = Parameter Stability, dernier attribué).

**Prérequis vérifié avant conception (jamais supposé)** : `build_walk_forward_validation_run()`
(`walk_forward.py`, Slice 8 AF-V-02) assemble déjà une `ValidationRun` Walk-Forward à partir d'un
`WalkForwardRunOutcome`/`AggregateResult` déjà obtenus — reçoit `research_run_id`/`validation_run_id`
explicites, ne persiste rien elle-même. `persist_walk_forward_run()` (Slice 4) écrit déjà, PAR
FOLD, `folds/fold_NNN/{definition,selection,test_result}.json` et
`{train_candidates,oos_trades,oos_equity}.csv` — `selection.json` porte `FoldSelection.selected_params`/
`score_train` (le Top-1 TRAIN réel de CE fold), `train_candidates.csv` le pool TRAIN complet de CE
fold. `resume_walk_forward_run()` (Slice 5) sait déjà reprendre un run Walk-Forward interrompu
(SKIP/REPLAY_TEST/REDO) — **cette ADR ne réimplémente JAMAIS cette reprise, elle la RÉUTILISE**.

## Décision 1 — Modèle de campagne : un `GateVCampaignPlan` immuable, distinct de toute `ValidationRun`

Une **campagne `GATE V`** est l'orchestration coordonnée, pour UNE stratégie sur UN
`dataset_snapshot_id`, de : (a) une référence à une preuve `OOS` déjà existante (jamais relancée
ici — Décision 9), (b) UN run Walk-Forward réel, (c) UN Monte-Carlo dérivé de ce Walk-Forward (ADR
0022, un seul, toutes trades TEST concaténées), (d) N Parameter Stability, un PAR FOLD Walk-Forward
terminé (ADR 0023, jamais fusionnés — Décision 6).

Une campagne N'EST PAS une `ValidationRun` (elle en agrège PLUSIEURS, de `validation_type`
différents) — nouveau type dédié `GateVCampaignPlan` (immuable, Décision 5) et
`GateVCampaignManifest` (mutable de façon contrôlée, append-only par construction — Décision 6),
tous deux dans un nouveau module leaf `gate_v_campaign.py` (jamais dans `validation_run.py`, qui
reste sans connaissance d'aucun concept de "campagne").

**Risque de comparaisons multiples entre CAMPAGNES — hérité, non outillé, explicitement restaté ici
(précision MINEURE, revue scientifique)** : ADR 0022 Décision 2/ADR 0023 Décision 6 signalent déjà
ce risque au niveau d'un run Monte-Carlo/Parameter Stability unique ("jamais outillé en V1"). Ce
même risque existe, non atténué, au niveau d'une campagne entière : `campaign_id` est un
identifiant librement créable (Décision 2), rien dans ce câblage n'empêche ni ne trace le lancement
de PLUSIEURS campagnes réelles (`base_params`/espace de recherche différents) suivi du rapport
sélectif de la seule campagne au résultat le plus favorable. Ce câblage reste honnête et exhaustif
À L'INTÉRIEUR d'une campagne (Décision 6) ; l'absence d'outillage anti-cherry-picking ENTRE
campagnes reste un risque humain/process, hors du périmètre technique de cette ADR — mais
explicitement noté ici plutôt que silencieusement absent, à charge du futur processus de décision
Human Gate (Décision 15) de ne jamais accepter un rapport de campagne sans lister TOUTES les
campagnes réellement lancées pour cette stratégie/ce `dataset_snapshot_id`.

## Décision 2 — Identifiants et filiation `ResearchRun`/`ValidationRun`

Mirroring exact du modèle déjà établi par `validation_run.py`/`research_run.py` (aucune invention) :
UN `ResearchRun` (`research_run.py::build_research_run()`, déjà réel, exige `dataset_snapshot_id`)
est le PARENT de toute la campagne — `research_run_id` unique, partagé par TOUTES les
`ValidationRun` produites (le champ `ValidationRun.research_run_id` existe déjà, direct, jamais une
jointure implicite — `validation_run.py` docstring module). `GateVCampaignPlan.campaign_id` reste
un identifiant DISTINCT de `research_run_id` (une campagne pourrait en principe référencer un
`ResearchRun` déjà existant pour une ré-analyse — hors scope V1, mais la distinction reste
structurellement correcte dès maintenant, jamais un raccourci qui fusionnerait les deux concepts).

`GateVCampaignManifest` référence, PAR TYPE :
- `oos_evidence_validation_run_id: Optional[str]` — RÉFÉRENCE une `ValidationRun` OOS EXISTANTE
  (Décision 9), jamais un identifiant généré par cette campagne.
- `walk_forward_validation_run_id: Optional[str]` — généré/assigné à l'exécution (Décision 4).
- `monte_carlo_validation_run_id: Optional[str]` — idem.
- `parameter_stability_validation_run_ids_by_fold: Dict[str, str]` — `fold_id -> validation_run_id`,
  un par fold ATTENDU (Décision 6).

## Décision 3 — Entrées obligatoires, jamais un défaut silencieux

`GateVCampaignPlan` (construit UNIQUEMENT par `build_gate_v_campaign_plan()`, jamais directement)
exige, sans AUCUN défaut :

- `dataset_snapshot_id: str` — doit correspondre EXACTEMENT au `dataset_snapshot_id` du
  `split_plan_id` fourni (vérifié à la construction, Décision 5).
- `split_plan_id: str` — DOIT référencer un `DatasetSplitPlan` réel, DÉJÀ écrit sur disque, avec
  `validation` NON `None` (Décision 5 — ex. `split_perfect_revolution_v1_walk_forward_v2`, Slice 7
  AF-V-02, réel).
- `strategy_name: str`, `base_params: dict` (NON vide) — **jamais un `DEFAULT_PARAMS` implicite** :
  l'appelant doit les fournir explicitement, même s'ils reproduisent la valeur par défaut d'une
  stratégie (fail-closed, aucune supposition).
- `search_mode: str` (une des 4 valeurs réelles, mirroring la validation déjà établie par
  `build_parameter_stability_specification()`), `search_space_hash: str` (empreinte du
  `param_ranges` réellement utilisé — jamais le contenu brut, qui appartient à `OptimizationConfig`,
  hors scope de ce module), `budget_per_fold: int` (`> 0`, nombre maximal de candidats TRAIN
  évalués par fold — plafond explicite, jamais un budget illimité implicite).
- `walk_forward_spec_semantics_version` / `monte_carlo_semantics_version` /
  `parameter_stability_semantics_version` : capturées TELLES QUELLES depuis les constantes module
  RÉELLES au moment de la construction (`WALK_FORWARD_SEMANTICS_VERSION`/
  `MONTE_CARLO_SEMANTICS_VERSION`/`PARAMETER_STABILITY_SEMANTICS_VERSION`), jamais choisies par
  l'appelant — même discipline que chaque `build_*_specification()` déjà existant.
- `monte_carlo_verdict_policy_id: Optional[str]`/`parameter_stability_verdict_policy_id: Optional[str]`/
  `walk_forward_verdict_policy_id: Optional[str]` — `None` par défaut EXPLICITE (aucune politique
  n'existe encore dans ce dépôt, Décision 8) ; si une future ADR enregistre une politique réelle,
  ces champs restent le SEUL point d'entrée, jamais une politique inventée en cours de route.
- `oos_evidence_validation_run_id: Optional[str]` — Décision 9, `None` tant qu'aucune preuve OOS
  fraîche n'est disponible.

**Refuse (`ValueError` immédiat, AVANT toute validation de disque) toute construction avec un champ
manquant ou vide** — mirroring la taxonomie fail-closed déjà établie (ADR 0021 Décision 11, ADR
0022/0023 Décision 9).

## Décision 4 — Artefacts produits

- `GateVCampaignPlan` : persisté UNE SEULE FOIS, immuable (`save_atomic()`, refuse un
  `campaign_id` déjà écrit — mirroring `save_dataset_split_plan()`/`save_validation_run()`), sous
  `results/job_xxx/gate_v_campaign/<campaign_id>/plan.json`.
- `GateVCampaignManifest` : réécrit ATOMIQUEMENT à chaque étape franchie (jamais un fichier
  mutable non-atomique) — même répertoire, `manifest.json` — porte le `status` courant (Décision
  7), les `validation_run_id` déjà produits, la liste `expected_fold_ids` (Décision 6).
- Les `ValidationRun` elles-mêmes (`OOS` référencée, `WalkForward`/`MonteCarlo`/
  `ParameterStability` × N folds produites) : persistées via `save_validation_run()` EXISTANT,
  jamais un mécanisme parallèle.
- Les artefacts Walk-Forward bruts (`folds/fold_NNN/*`) : délégués ENTIÈREMENT à
  `persist_walk_forward_run()` EXISTANT (Slice 4), jamais dupliqués ici — sous un `output_dir`
  DISTINCT du répertoire de campagne (`.../<campaign_id>/walk_forward/`), qui porte SON PROPRE
  `manifest.json` écrit par `persist_walk_forward_run()` (`_MANIFEST_FILENAME`, `walk_forward.py`
  ligne 1179). **Ce `manifest.json` Walk-Forward n'est PAS le `GateVCampaignManifest.manifest.json`
  du paragraphe précédent** — deux fichiers de même nom, à deux niveaux de répertoire différents,
  jamais confondus (Décision 6/8 ci-dessous se réfèrent explicitement à l'un ou l'autre).

## Décision 5 — Deux niveaux structurellement séparés : préparation déterministe (A) vs exécution explicite (B)

**Niveau A — `build_gate_v_campaign_plan(...) -> GateVCampaignPlan`** (préparation, jamais
d'exécution) :
- Valide TOUTES les entrées obligatoires (Décision 3).
- Charge le `DatasetSplitPlan` réel (`dataset_split.load_dataset_split_plan()`, DÉJÀ existant,
  jamais réimplémenté) — vérifie `split_plan.validation is not None` et
  `split_plan.dataset_snapshot_id == dataset_snapshot_id` fourni — **lit UNIQUEMENT
  `split_plan.validation`, ne référence JAMAIS `split_plan.final_holdout`** (Décision 10, vérifié
  par un test d'absence de référence).
- Calcule `expected_fold_ids` en appelant `walk_forward.compute_fold_definitions()` (fonction PURE
  déjà existante, ADR 0021 — aucun backtest, aucune donnée marché) sur `split_plan.validation` +
  une `WalkForwardSpecification` construite depuis les entrées du plan.
- **Ne charge AUCUNE donnée de marché** (`nasdaq_3m.csv` jamais ouvert), **n'importe ni n'appelle
  `engine.py`/`optimizer.py::Optimizer.run()`**, **ne consomme aucun budget de calcul scientifique
  réel** — entièrement local, déterministe, rejouable à l'identique.
- Retourne un `GateVCampaignPlan` FROZEN — une fois construit, IMMUABLE (aucune méthode de
  mutation), persisté une seule fois (Décision 4).

**Niveau B — `execute_gate_v_campaign(plan: GateVCampaignPlan, *, run_walk_forward_fn, resume_walk_forward_fn, load_market_data_fn, manifest_dir, ...) -> GateVCampaignManifest`**
(exécution, JAMAIS appelée automatiquement — Décision 11) :
- **N'accepte QU'UN `GateVCampaignPlan` DÉJÀ construit et validé** — ne reconstruit, ne dérive, ne
  devine AUCUN paramètre elle-même ; si `plan` est incohérent (jamais censé arriver après le
  Niveau A, mais revérifié quand même — fail-closed), refuse plutôt que de deviner.
- **`run_walk_forward_fn`/`resume_walk_forward_fn`/`load_market_data_fn` (et tout autre
  collaborateur touchant réellement le moteur/les données) sont INJECTÉS, jamais importés
  directement dans le corps de la fonction d'orchestration** — mirroring le PRINCIPE établi par
  `validation_oos.py::run_oos_validation(run_backtest_fn: Callable, ...)` (injection = testabilité
  sans donnée réelle), **jamais sa signature exacte** : contrairement à `run_backtest_fn` (un seul
  collaborateur, une seule fonction réelle derrière), Walk-Forward expose DEUX fonctions réelles de
  signatures et de types de retour DIFFÉRENTS (`walk_forward.run_walk_forward(...) ->
  WalkForwardRunOutcome` vs `walk_forward.resume_walk_forward_run(..., data_manifest_path,
  output_dir) -> Tuple[WalkForwardRunOutcome, AggregateResult]`, vérifié dans le code source, ADR
  0021 Slices 3/5) — **une seule fonction injectée ne peut structurellement pas représenter les
  deux**. `execute_gate_v_campaign()` accepte donc DEUX collaborateurs SÉPARÉS, keyword-only, SANS
  valeur par défaut, et choisit lui-même lequel appeler selon qu'un `manifest.json` Walk-Forward
  existe déjà sous `.../walk_forward/` (Décision 6, logique de sélection détaillée ; reprise à
  l'identique par Décision 8) — jamais l'appelant, qui ne fournit que les DEUX
  fonctions, jamais un choix déjà fait en amont. Un futur appelant réel passe directement
  `walk_forward.run_walk_forward`/`walk_forward.resume_walk_forward_run` ; un test passe deux
  doublures synthétiques (Décision 12).
- **`run_monte_carlo_simulation()`/`analyze_parameter_stability()` NE SONT PAS injectées** —
  appelées DIRECTEMENT (import module-level), contrairement à Walk-Forward : ce sont des fonctions
  PURES/déterministes opérant sur des trades déjà en mémoire (aucun accès disque/marché/moteur
  propre), sans équivalent du besoin `run_backtest_fn` (isoler un accès I/O coûteux et non
  déterministe). Les tests les exercent réellement (jamais une doublure), avec des trades
  synthétiques en entrée (Décision 12/13) — surface d'injection volontairement plus étroite que ne
  le suggérait la formulation initiale "mirroring exact" (finding MINEUR, revue architecture).
- **AUCUN paramètre par défaut permettant un déclenchement accidentel** — chaque collaborateur
  requis est un paramètre keyword-only SANS valeur par défaut.
- **Ne peut structurellement jamais accéder `FINAL_HOLDOUT`** : `gate_v_campaign.py` n'importe
  jamais `dataset_split.FINAL_HOLDOUT`-related, n'importe jamais `validation_oos.py` (le seul
  module autorisé à consulter le holdout) — vérifié par un test d'import statique (Décision 13). Ce
  test couvre UNIQUEMENT les imports propres de `gate_v_campaign.py` — voir la limite de portée
  explicite ajoutée à Décision 10.

## Décision 6 — Connecter Walk-Forward, Monte-Carlo et Parameter Stability (mapping scientifique précis)

**Walk-Forward** : `execute_gate_v_campaign()` teste d'abord si `.../walk_forward/manifest.json`
existe déjà sur disque (test EXISTANT, `Path.is_file()`, jamais une hypothèse) :
- **Absent** → appelle `run_walk_forward_fn` (= `walk_forward.run_walk_forward` en usage réel) avec
  `split_plan.validation`, la `WalkForwardSpecification` du plan, `base_params`, et
  `output_dir = .../walk_forward/` — obtient un `WalkForwardRunOutcome`. **`run_walk_forward()`
  retourne SEULEMENT un `WalkForwardRunOutcome` (JAMAIS un `AggregateResult` — vérifié,
  `walk_forward.py` ligne 799-808), contrairement à `resume_walk_forward_run()` (précision MINEURE,
  revue scientifique)** : `execute_gate_v_campaign()` DOIT donc appeler explicitement
  `walk_forward.build_aggregate_result(outcome.fold_results)` (EXISTANT, `walk_forward.py` ligne
  863) dans CETTE branche pour obtenir l'`AggregateResult` — jamais un `aggregate=None` transmis à
  `persist_walk_forward_run()` ci-dessous, qui casserait silencieusement le marqueur de complétion
  (`aggregate.json` n'est écrit QUE si `aggregate is not None`, `walk_forward.py` lignes 1210-1214)
  dont dépend la garde de non-double-persistance ci-dessous.
- **Présent** → appelle `resume_walk_forward_fn` (= `walk_forward.resume_walk_forward_run` en usage
  réel, signature RÉELLE distincte — Décision 5) avec les DEUX paramètres supplémentaires qu'elle
  exige (`data_manifest_path`, `output_dir`) — obtient le même couple
  `WalkForwardRunOutcome`/`AggregateResult`.

**Persistance appelée AU PLUS UNE FOIS par campagne (correctif BLOCKER, revue architecture)** :
`persist_walk_forward_run()` (Slice 4) est un appel UNIQUE, tout-ou-rien — elle écrit
`.../walk_forward/manifest.json` en PREMIER (`walk_forward.py` ligne 1179) puis, séquentiellement,
chaque fichier par fold, `state.json`, et enfin `aggregate.json` EN DERNIER
(`walk_forward.py` lignes 1210-1214) ; sa propre docstring documente qu'elle n'est "pas conçue pour
ré-écrire" un run déjà persisté — **elle N'EST DONC JAMAIS rappelée après un `resume_walk_forward_fn`
qui aurait déjà été précédé d'un appel `persist_walk_forward_run()` réussi**, sous peine de
`FileExistsError` dès sa toute première écriture (`manifest.json`, déjà présent par construction
puisque c'est CE fichier qui a déclenché le choix `resume_walk_forward_fn` ci-dessus). Règle
précise appliquée par `execute_gate_v_campaign()` : APRÈS avoir obtenu un `WalkForwardRunOutcome`
COMPLET (fresh ou résumé — un outcome partiel/interrompu n'est JAMAIS transmis à la persistance),
teste si `.../walk_forward/aggregate.json` (dernier fichier écrit par `persist_walk_forward_run()`,
donc marqueur fiable de complétion totale) existe déjà : si OUI, la persistance Walk-Forward de
cette campagne est DÉJÀ terminée, `persist_walk_forward_run()` n'est PAS rappelée ; si NON, elle est
appelée EXACTEMENT une fois, sur l'outcome complet. Voir Décision 8 pour la reprise et la limite
résiduelle connue (crash pendant cet unique appel).

Assemble la `ValidationRun` Walk-Forward via `build_walk_forward_validation_run()` (EXISTANT, Slice
8) — `research_run_id` commun à la campagne, `validation_run_id` généré par la campagne (Décision
2).

**Monte-Carlo — mapping EXACT demandé par l'utilisateur, chaque règle testée séparément
(Décision 12)** :
- Consomme **UNIQUEMENT** les trades **TEST** de CHAQUE fold (`folds/fold_NNN/oos_trades.csv`,
  Slice 4 — **jamais** `train_candidates.csv`).
- **Concatène tous les folds dans l'ordre CHRONOLOGIQUE** — l'ordre de `fold_index` croissant
  (garanti par `compute_fold_definitions()`, ADR 0021, déjà déterministe et non chevauchant en
  TEST, Décision 4 de cette même ADR) EST l'ordre chronologique, jamais un tri séparé réinventé.
- **Chaque trade conservé EXACTEMENT une fois** avant rééchantillonnage — vérifié explicitement :
  le nombre total de trades concaténés DOIT être égal à `AggregateResult.total_oos_trades` (le
  MÊME calcul déjà produit par `build_aggregate_result()`, Slice 3, jamais recalculé
  indépendamment) — divergence -> erreur explicite (Décision 8), jamais une valeur silencieusement
  tronquée/dupliquée.
- **Bornes/ordre/doublons vérifiés** : les trades de chaque fold restent dans les bornes TEST de CE
  fold (`FoldDefinition.effective_boundary`/`effective_test_end`) ; aucun trade dupliqué entre deux
  folds (les fenêtres TEST ne se chevauchent jamais, ADR 0021 Décision 4 — revérifié ici comme
  preuve défensive, jamais supposé silencieusement).
- Assemble `MonteCarloSpecification` via `build_monte_carlo_specification()` (EXISTANT,
  `source_validation_run_id` = le `validation_run_id` Walk-Forward de CETTE campagne,
  `source_trades_from_optimized_params = True` — voir justification ci-dessous),
  `run_monte_carlo_simulation()` (EXISTANT), puis une `ValidationRun` Monte-Carlo — **UNE SEULE**
  pour toute la campagne (jamais une par fold, cohérent avec ADR 0022 Décision 1).

**Drapeaux de circularité — jamais laissés implicites (correctif BLOCKER, revue scientifique)** :
`build_monte_carlo_specification()`/`build_parameter_stability_specification()` exigent tous deux
`source_trades_from_optimized_params`/`source_candidates_from_optimized_search` comme paramètres
POSITIONNELS SANS défaut (`validation_run.py` — `MonteCarloSpecification`/`ParameterStabilitySpecification`,
champs `bool` sans valeur par défaut). **`execute_gate_v_campaign()` fixe les DEUX à `True`, en dur,
jamais un paramètre configurable de `GateVCampaignPlan`** : dans une campagne `GATE V` réelle, les
trades TEST Walk-Forward proviennent STRUCTURELLEMENT du Top-1 TRAIN-optimisé de chaque fold (ADR
0021 Décision 6, "S1 = Top-1 TRAIN"), et le pool `train_candidates.csv` consommé par Parameter
Stability EST le pool de CETTE MÊME recherche optimisée — il ne peut structurellement JAMAIS en être
autrement dans ce câblage. Mettre `False` ici (ou laisser un appelant le choisir) masquerait
exactement la circularité que ADR 0022 Décision 1/ADR 0023 Décision 1 ont introduit ces drapeaux
pour signaler ("PLUS FORT qu'en Monte-Carlo" pour Parameter Stability, `best_params` étant par
construction l'argmax in-sample du pool analysé) — une évidence `ValidationRun` immuable
(`save_atomic()`) avec un mauvais drapeau serait indétectable après coup sans audit manuel.

**Parameter Stability — mapping EXACT demandé par l'utilisateur (Décision 12)** :
- **Un pool par fold, jamais fusionné entre folds** : pour CHAQUE fold `f` de `expected_fold_ids`
  DÉJÀ terminé (Décision 7), charge `folds/fold_f/train_candidates.csv` (pool TRAIN complet de CE
  fold) et `folds/fold_f/selection.json` (`FoldSelection.selected_params`/`score_train` — le Top-1
  RÉELLEMENT sélectionné pour CE MÊME fold, jamais un Top-1 d'un autre fold ni un "meilleur global"
  inventé).
- Assemble `ParameterStabilitySpecification` via `build_parameter_stability_specification()`
  (EXISTANT, ÉTENDU pour cette mission — voir Décision 14) avec `source_validation_run_id` = le
  `validation_run_id` Walk-Forward de la campagne, `source_fold_id = f` (traçabilité corrigée,
  Décision 14) ET `source_candidates_from_optimized_search = True` en dur (drapeau de circularité,
  voir justification ci-dessus au paragraphe Monte-Carlo — s'applique à l'identique ici, "PLUS FORT"
  per ADR 0023 Décision 1) ; `analyze_parameter_stability()` (EXISTANT) avec les candidats/
  `best_params` de CE fold uniquement.
- **TOUS les folds terminés sont traités, jamais seulement le meilleur ou le plus favorable** :
  `execute_gate_v_campaign()` itère `expected_fold_ids` dans l'ordre, sans aucune logique de
  sélection/filtrage du fold "le plus intéressant" — une `ValidationRun` ParameterStability PAR
  fold, chacune persistée séparément (Décision 4), référencée dans
  `parameter_stability_validation_run_ids_by_fold` (Décision 2).
- **Jamais de fusion artificielle en un score unique** : `GateVCampaignManifest` ne porte JAMAIS de
  champ "parameter_stability_combined_score"/équivalent — uniquement la liste des
  `validation_run_id` par fold, chacune consultable individuellement.
- **Signalement honnête des folds sans voisinage exploitable** : `execute_gate_v_campaign()` ne
  filtre ni ne masque un fold dont l'évidence produite a `neighborhood_applicability =
  "global_correlation_only"` (ADR 0023 Décision 3) — cette évidence est persistée et référencée
  EXACTEMENT comme les autres, son statut reste lisible directement dans son propre
  `ParameterStabilityEvidence.neighborhood_applicability`, jamais résumé/caché au niveau campagne.
- **Contribution Parameter Stability "prête pour `GATE V`" — deux conditions CUMULATIVES, jamais
  un simple décompte de fichiers (correctif MAJEUR, revue scientifique)** :
  1. `len(parameter_stability_validation_run_ids_by_fold) == len(expected_fold_ids)` (présence —
     un sous-ensemble, même partiellement favorable, ne satisfait jamais cette condition seule,
     Décision 7/8, jamais de cherry-picking structurel) ; **ET**
  2. **ADR 0023 Décision 3 exige DÉJÀ, verbatim, exactement ce contrôle pour "un futur agrégateur
     GATE V"** : pour CHAQUE `ParameterStabilityEvidence` produite, (a)
     `neighborhood_applicability == "local_neighborhood_available"` (jamais
     `"global_correlation_only"` seul, qui "NE SATISFAIT PAS l'exigence de preuve
     parameter_stability de GATE V") ET (b) au moins un paramètre avec
     `n_neighbors_total_by_param[param] - n_neighbors_rejected_by_param[param] > 0` (ADR 0023
     Décision 3, finding N2). **`execute_gate_v_campaign()`/`GateVCampaignManifest` implémente
     CETTE ADR 0024 est le PREMIER agrégateur réel (Décision 14) — cette condition n'est PAS
     optionnelle ici : si un fold ne la satisfait pas, sa `ValidationRun` reste produite et
     référencée (jamais masquée, signalement honnête ci-dessus), mais la contribution Parameter
     Stability GLOBALE de la campagne reste `EVIDENCE_INCOMPLETE`, jamais
     `EVIDENCE_COMPLETE_AWAITING_POLICY`** (Décision 7, corrigé symétriquement ci-dessous). Cette
     ADR 0024 EST ce "futur agrégateur GATE V" annoncé par ADR 0023 (Décision 14 : "le PREMIER
     appelant réel" de `ParameterStabilitySpecification`/`source_fold_id`) — implémenter cette
     condition n'est donc PAS optionnel ici. Un `search_mode` non-déterministe (Décision 3 — 4
     valeurs légales acceptées) ou une grille de recherche clairsemée peuvent légitimement produire
     zéro voisin exploitable pour tous les folds d'une campagne réelle ; ce cas ne doit JAMAIS être
     lu comme "preuve complète en attente de seuils".

## Décision 7 — États factuels : préparation / exécution / complétion / échec

`GateVCampaignManifest.status` ∈ EXACTEMENT (jamais un état supplémentaire inventé, correspond
EXACTEMENT à la liste imposée par l'utilisateur) :

| État | Condition |
|---|---|
| `NOT_READY` | `GateVCampaignPlan` invalide/incomplet (Niveau A a refusé la construction — cet état n'est en réalité JAMAIS persisté, puisque Niveau A échoue AVANT de produire un plan ; documenté ici pour exhaustivité conceptuelle) |
| `READY_FOR_EXECUTION` | `GateVCampaignPlan` valide et persisté, `execute_gate_v_campaign()` jamais encore appelée pour ce `campaign_id` |
| `RUNNING` | `execute_gate_v_campaign()` en cours (manifeste réécrit AVANT chaque étape coûteuse, jamais après coup — permet une reprise fidèle même sur un crash en plein milieu, Décision 8) |
| `EVIDENCE_INCOMPLETE` | Exécution terminée (normalement ou interrompue) mais au moins une preuve attendue manque OU ne satisfait pas sa condition de qualité — Walk-Forward incomplet, Monte-Carlo absent, `len(parameter_stability_validation_run_ids_by_fold) < len(expected_fold_ids)`, **OU au moins un fold Parameter Stability présent mais sans voisinage exploitable réel** (correctif MAJEUR, revue scientifique — condition précise à Décision 6 : `neighborhood_applicability != "local_neighborhood_available"` ou aucun paramètre avec un voisin non rejeté, ADR 0023 Décision 3) |
| `EVIDENCE_COMPLETE_AWAITING_POLICY` | LES QUATRE catégories de preuve sont RÉELLEMENT complètes (OOS référencée + Walk-Forward + Monte-Carlo + TOUS les Parameter Stability attendus, **CHACUN satisfaisant la condition de qualité ADR 0023 Décision 3 ci-dessus — jamais un simple décompte de fichiers présents**, Décision 6) — mais AUCUN verdict n'est `PASS`/`FAIL` faute de politique enregistrée (`scientific_verdict` de chaque evidence reste `INCONCLUSIVE`, ADR 0021/22/23 Décision 13/12/12) |
| `TECHNICAL_FAILURE` | Une exception technique NON gérée a interrompu l'exécution — **jamais traduite en `EVIDENCE_INCOMPLETE` ni en un verdict scientifique `FAIL`** (mirroring ADR 0021 Décision 13 : une erreur technique reste distincte d'un jugement scientifique) |

**Ce câblage ne déclare JAMAIS `GATE V PASS`** — aucun de ces six états n'implique/n'autorise à
lire "GATE V est passée" (Décision 15).

## Décision 8 — Reprise après interruption, sans doublon

**Walk-Forward** : délègue ENTIÈREMENT à `resume_walk_forward_fn`/`resume_walk_forward_run()`
(EXISTANT, Slice 5 — SKIP/REPLAY_TEST/REDO déjà prouvé sans doublon) pour la reprise de la
recherche TRAIN/TEST elle-même — `execute_gate_v_campaign()` choisit `resume_walk_forward_fn`
plutôt que `run_walk_forward_fn` dès qu'un `manifest.json` Walk-Forward existe déjà sous
`.../walk_forward/`, jamais une logique de reprise réinventée (Décision 5/6).

**Limite résiduelle connue et acceptée, non corrigée par cette ADR (finding BLOCKER, revue
architecture — périmètre de la correction expliqué ici)** : la reprise ci-dessus couvre une
interruption PENDANT la recherche TRAIN/TEST (potentiellement longue, heures). Elle NE couvre PAS
une interruption PENDANT l'unique appel `persist_walk_forward_run()` lui-même (Décision 6) — cette
fonction (Slice 4, EXISTANTE, explicitement non modifiée par cette mission : "jamais réimplémentée")
n'a aucune tolérance à une ré-écriture partielle, chaque `save_atomic()` refusant tout fichier déjà
présent. Un crash entre deux écritures de cet appel unique (ex. après `fold_002/definition.json`,
avant `fold_003/`) laisserait `.../walk_forward/` dans un état ni "absent" (donc pas de nouveau
`run_walk_forward_fn` propre) ni "complet" (`aggregate.json` absent, donc pas de skip Décision 6) —
un second appel `persist_walk_forward_run()` échouerait immédiatement (`FileExistsError` sur les
fichiers déjà écrits). **Ce cas précis reste une limitation connue, documentée, à résolution
MANUELLE** (supprimer `.../walk_forward/` et relancer `run_walk_forward_fn` depuis zéro pour cette
campagne) — accepté comme risque résiduel proportionné : `persist_walk_forward_run()` n'exécute que
des écritures disque atomiques rapides (pas de recherche TRAIN, pas d'accès réseau), une fenêtre
d'exposition très inférieure à celle de la recherche elle-même. La rendre elle-même tolérante à une
reprise partielle exigerait de modifier le contrat gelé de Slice 4 (AF-V-02) — hors périmètre de
cette mission (câblage d'orchestration uniquement) ; à traiter par un futur ticket dédié,
séparément revu, si ce cas est un jour réellement observé.

**Monte-Carlo/Parameter Stability** : le `GateVCampaignManifest` déjà persisté est relu AVANT
chaque étape — si `monte_carlo_validation_run_id` est déjà renseigné (le fichier `ValidationRun`
correspondant existe RÉELLEMENT sur disque, vérifié, jamais supposé), l'étape est SAUTÉE (jamais
recalculée) ; idem pour CHAQUE entrée déjà présente dans
`parameter_stability_validation_run_ids_by_fold`. Le manifeste est réécrit ATOMIQUEMENT
IMMÉDIATEMENT après CHAQUE `ValidationRun` individuelle produite (jamais en fin de campagne
seulement) — une interruption entre deux folds Parameter Stability ne perd et ne duplique aucune
preuve déjà produite.

## Décision 9 — Référencer une future preuve OOS fraîche sans la déclencher

`GateVCampaignPlan.oos_evidence_validation_run_id: Optional[str]` — si fourni, DOIT référencer un
`validation_run_id` d'une `ValidationRun` `"oos"` RÉELLEMENT déjà persistée sur disque (vérifié à
la construction du plan, Niveau A — `load_validation_run()` EXISTANT, jamais réimplémenté) ; si
`None`, la contribution OOS de la campagne reste `EVIDENCE_INCOMPLETE` indéfiniment, jusqu'à ce
qu'un futur appelant fournisse un `validation_run_id` réel via un NOUVEAU `GateVCampaignPlan`
(immuable — jamais une mutation du plan existant, Décision 1). **`execute_gate_v_campaign()`
n'appelle JAMAIS `validation_oos.run_oos_validation()`** — aucun import de ce module, aucune
notion d'exécuter un OOS depuis cette orchestration, EN AUCUN CAS (mirroring Décision 5/13).

## Décision 10 — Impossibilité structurelle d'accéder à `FINAL_HOLDOUT`

`gate_v_campaign.py` lit `DatasetSplitPlan.validation` (Niveau A) et transmet cette SEULE zone à
`compute_fold_definitions()`/`run_walk_forward_fn`/`resume_walk_forward_fn` — ne lit, ne transmet,
ne référence JAMAIS `DatasetSplitPlan.final_holdout`. **`gate_v_campaign.py` n'importe jamais
`validation_oos.py`** (le seul module autorisé à connaître le holdout, `validation_oos.py`
docstring module) — vérifié par un test d'import statique dédié (Décision 13).

**Portée exacte de cette garantie (finding MAJEUR, revue architecture — précision ajoutée, aucune
garantie retirée)** : le test d'import statique ne prouve l'absence d'accès `FINAL_HOLDOUT` que
pour les imports PROPRES de `gate_v_campaign.py` — il ne peut structurellement rien prouver sur le
CONTENU des fonctions `run_walk_forward_fn`/`resume_walk_forward_fn`/`load_market_data_fn` INJECTÉES
par un appelant réel (Décision 5), puisque l'injection existe précisément pour que ce contenu reste
extérieur au module. **Un futur appelant qui passerait, par erreur ou par malveillance, une
implémentation de ces collaborateurs qui accède elle-même à `validation_oos`/`FINAL_HOLDOUT`
contournerait cette garantie** — ce n'est PAS un trou dans cette ADR, mais une frontière de
confiance DISTINCTE et EXPLICITE : la garantie structurelle décrite ici protège contre un accès
`FINAL_HOLDOUT` **depuis `gate_v_campaign.py` lui-même**, jamais contre un appelant réel qui
brancherait délibérément un mauvais collaborateur. La sécurité de cette seconde frontière reste
entièrement une responsabilité humaine — revue de code du futur script d'appel réel (hors scope de
cette ADR, Décision 11), jamais un test automatisé de ce module.

## Décision 11 — Aucun déclenchement automatique

`execute_gate_v_campaign()` n'est appelée par AUCUN code existant — ni `resume.ps1`, ni la tâche
planifiée Windows `AlphaForgeAutopilot`, ni le pipeline `job_store.py`/`optimizer_process.py`, ni
un `if __name__ == "__main__":` de `gate_v_campaign.py` lui-même (ce module N'EST PAS un script
exécutable — un futur script dédié, hors scope de cette mission, en sera l'unique point d'entrée
manuel explicite). L'Autopilot lui-même (`scripts/autopilot/`) n'a et ne gagne AUCUN chemin de code
qui importerait `gate_v_campaign.execute_gate_v_campaign` — vérifié par un test d'absence
d'import dans `scripts/autopilot/`.

## Décision 12 — Tests d'intégration sans données réelles, collaborateurs injectés/doublures

Mirroring le PRINCIPE déjà établi pour `validation_oos.run_oos_validation(run_backtest_fn)`, jamais
sa signature exacte (Décision 5) : tous les tests de `execute_gate_v_campaign()` injectent
`run_walk_forward_fn`/`resume_walk_forward_fn`/`load_market_data_fn` FACTICES (retournent un
`WalkForwardRunOutcome`/`Tuple[WalkForwardRunOutcome, AggregateResult]`/`DataFrame` synthétique
construit à la main, jamais `nasdaq_3m.csv`) — AUCUN test de cette mission ne charge de donnée
réelle ni n'appelle le moteur réel. `run_monte_carlo_simulation()`/`analyze_parameter_stability()`
restent les fonctions RÉELLES (non injectées, Décision 5) exercées directement sur des trades
synthétiques. Un test d'intégration complet (Décision 13) prouve que le PIPELINE ENTIER
(préparation -> exécution -> 4 catégories de preuve -> manifeste complet) fonctionne de bout en bout
sur des doublures, sans jamais toucher `engine.py`/`nasdaq_3m.csv`.

## Décision 13 — Matrice TDD (liste non exhaustive, complétée par chaque tranche d'implémentation)

| Cas | Test |
|---|---|
| Aucune exécution réelle pendant la préparation | `build_gate_v_campaign_plan()` : test d'absence d'appel à tout collaborateur d'exécution (aucun paramètre de ce type n'existe même dans sa signature) |
| Aucun accès `FINAL_HOLDOUT` | Test d'import statique : `gate_v_campaign.py` n'importe jamais `validation_oos` ; aucune référence textuelle à `final_holdout`/`FINAL_HOLDOUT` dans son code source |
| Refus des paramètres/budgets manquants | `ValueError` pour chaque champ obligatoire manquant de `GateVCampaignPlan` (Décision 3), testé individuellement |
| Refus d'un fold absent/dupliqué/incohérent | `execute_gate_v_campaign()` refuse si un `run_walk_forward_fn` factice retourne un `WalkForwardRunOutcome` dont les `fold_id` ne correspondent pas exactement à `expected_fold_ids` (ni manquant, ni supplémentaire, ni dupliqué) |
| Absence de sélection du fold le plus favorable | Sur 3 folds factices de qualité très différente, les 3 `ValidationRun` ParameterStability sont produites, aucune n'est omise, aucun score combiné n'existe nulle part dans le manifeste |
| Monte-Carlo alimenté seulement par les trades TEST chronologiques | Un fold factice dont les trades TRAIN et TEST sont délibérément distincts/marqués : seuls les trades TEST apparaissent dans la séquence transmise à `run_monte_carlo_simulation()` (vérifié par spy) |
| Cohérence du nombre de trades Monte-Carlo | Compte total transmis à Monte-Carlo == `AggregateResult.total_oos_trades` — divergence synthétique construite -> erreur explicite |
| Parameter Stability exécutée pour chaque fold attendu | `len(parameter_stability_validation_run_ids_by_fold) == len(expected_fold_ids)` après une exécution complète factice |
| Reprise sans duplication | Manifeste pré-rempli avec 2 folds ParameterStability déjà produits (fichiers `ValidationRun` réels sur disque, tmp_path) -> reprise ne recalcule QUE le fold manquant, spy sur `analyze_parameter_stability` confirme exactement 1 appel |
| Aucune preuve d'une mission antérieure réutilisée | Un `campaign_id` différent ne référence jamais les `ValidationRun` d'un `campaign_id` distinct — chaque manifeste reste scopé à son propre répertoire |
| Aucune déclaration PASS automatique | `GateVCampaignManifest.status` ne contient JAMAIS la chaîne `"PASS"` — test de présence exhaustive des 6 valeurs autorisées uniquement (Décision 7), aucun code de ce module ne compare `scientific_verdict` à quoi que ce soit pour en dériver un état de campagne |
| Reproductibilité exacte du plan/identifiants | Deux appels à `build_gate_v_campaign_plan()` avec les mêmes entrées produisent des `campaign_id`/`expected_fold_ids` identiques (déterminisme de `compute_fold_definitions()`, déjà garanti par ADR 0021) |
| Aucun déclenchement automatique | Test d'absence d'import de `gate_v_campaign` dans `scripts/autopilot/` (Décision 11) |
| Intégration bout-en-bout sans données réelles | Pipeline complet préparation -> exécution -> `EVIDENCE_COMPLETE_AWAITING_POLICY` sur doublures uniquement (Décision 12) |
| Drapeaux de circularité jamais laissés à `False`/absents | `MonteCarloSpecification.source_trades_from_optimized_params` et `ParameterStabilitySpecification.source_candidates_from_optimized_search` valent `True` sur CHAQUE `ValidationRun` produite par une exécution complète factice (Décision 6, correctif BLOCKER) |
| Contribution Parameter Stability incomplète si aucun voisinage exploitable | Fold factice avec `neighborhood_applicability="global_correlation_only"` (ou tous les `n_neighbors_total_by_param - n_neighbors_rejected_by_param == 0`) -> statut de campagne reste `EVIDENCE_INCOMPLETE` malgré `len(parameter_stability_validation_run_ids_by_fold) == len(expected_fold_ids)` ; ne devient `EVIDENCE_COMPLETE_AWAITING_POLICY` que si CHAQUE fold a `neighborhood_applicability="local_neighborhood_available"` ET au moins un paramètre avec un voisin non rejeté (Décision 6/7, correctif MAJEUR, ADR 0023 Décision 3) |
| Sélection du bon collaborateur Walk-Forward | Sans `.../walk_forward/manifest.json` préexistant -> `run_walk_forward_fn` appelé, `resume_walk_forward_fn` jamais appelé (spy) ; avec `.../walk_forward/manifest.json` préexistant (fixture tmp_path) -> l'inverse (Décision 5/6) |
| `persist_walk_forward_run()` jamais rappelée après une reprise déjà persistée | Fixture tmp_path avec `.../walk_forward/aggregate.json` déjà présent (persistance antérieure complète simulée) -> `execute_gate_v_campaign()` ne rappelle PAS le collaborateur de persistance (spy, zéro appel), aucune `FileExistsError` levée (Décision 6/8, correctif BLOCKER) |
| Persistance Walk-Forward appelée au plus une fois par campagne | Sur un run frais complet en une seule passe, le collaborateur de persistance est appelé EXACTEMENT une fois (spy) — jamais zéro, jamais deux (Décision 6) |
| `build_aggregate_result()` réellement appelée dans la branche run frais | Sur un run frais factice, `walk_forward.build_aggregate_result` est appelé EXACTEMENT une fois (spy) AVANT l'appel au collaborateur de persistance, et l'`aggregate` transmis à ce dernier n'est JAMAIS `None` — sans ce test, un oubli de cet appel romprait silencieusement le marqueur de complétion (`aggregate.json`) sans faire échouer le test "appelée une fois" (Décision 6, gap comblé après confirmation revue scientifique) |

## Décision 14 — Correctif de traçabilité, appliqué immédiatement (versionné, rétrocompatible)

**`source_validation_run_id` seul, sur `ParameterStabilitySpecification`, était insuffisant** pour
identifier QUEL FOLD d'un Walk-Forward multi-fold a produit un pool de candidats donné — corrigé
**avant** l'écriture de cette ADR (commit `c7b3aab`, déjà revu indépendamment, déjà intégré sur
`origin/master`) : `ParameterStabilitySpecification.source_fold_id: Optional[str] = None` (additif,
rétrocompatible — aucun artefact réel n'existait encore sous l'ancien contrat),
`PARAMETER_STABILITY_SEMANTICS_VERSION` porté à `"param-stability-neighborhood-v2"`. Cette
orchestration (Décision 6) est le PREMIER appelant réel à fournir `source_fold_id` systématiquement.
**`MonteCarloSpecification` confirmée NE PAS avoir besoin d'un correctif équivalent** — une seule
`ValidationRun` Monte-Carlo par campagne, jamais par fold (ADR 0022 Décision 1), `source_validation_run_id`
identifie déjà sans ambiguïté le run Walk-Forward source complet.

## Décision 15 — Différence entre « techniquement prête », « exécutée » et `GATE V` réellement passée

- **Techniquement prête** = `READY_FOR_EXECUTION` (Décision 7) : `GateVCampaignPlan` valide,
  construit, persisté — RIEN n'a encore été exécuté, aucune preuve n'existe.
- **Exécutée** = `RUNNING` puis `EVIDENCE_INCOMPLETE` ou `EVIDENCE_COMPLETE_AWAITING_POLICY` — des
  preuves ont été RÉELLEMENT produites, mais ceci NE DIT RIEN sur la qualité de la stratégie
  (`scientific_verdict` de chaque evidence reste structurellement `INCONCLUSIVE` sans politique).
- **`GATE V` réellement passée** exige, en plus et hors du périmètre de ce câblage : (1) une
  preuve OOS EXTERNE fraîche et non-inconclusive (nouveau `DatasetSnapshot`, accès `FINAL_HOLDOUT`
  explicitement autorisé — action séparée, `MASTER_ROADMAP.md` §4, jamais déclenchée ici) ; (2) une
  campagne réelle complète (`EVIDENCE_COMPLETE_AWAITING_POLICY` atteint pour de vrai, pas
  seulement sur doublures) ; (3) TOUTES les preuves attendues réellement présentes (Décision 6/7) ;
  (4) une politique scientifique de seuils PRÉ-ENREGISTRÉE (`AF-V-07`, `ValidationPolicyVersion`,
  actuellement `READY`/non commencé — hors scope de cette ADR, jamais inventée ici) ; (5) aucun
  résultat `INCONCLUSIVE` incompatible avec cette politique une fois appliquée. **Ce câblage ne
  produit et ne peut jamais produire l'état "GATE V PASS" lui-même** — cette décision reste
  humaine/produit, hors de portée du code (Décision 7).

## Conséquences

- **`AF-V-08` reste `implementation: NOT STARTED`** — cette ADR ne modifie aucun code au-delà du
  correctif de traçabilité déjà appliqué (Décision 14, déjà committé séparément).
- **Nouveau module `gate_v_campaign.py`** identifié, jamais encore créé — implémentation en
  plusieurs tranches TDD (voir mission de suite).
- **Dépendance explicite sur `AF-V-07`** (`ValidationPolicyVersion`) pour que `GATE V` passe
  RÉELLEMENT un jour — non bloquante pour CETTE ADR (`EVIDENCE_COMPLETE_AWAITING_POLICY` reste un
  état factuel valide et utile sans elle), mais nécessaire pour aller au-delà.
- **Points restant à valider explicitement par l'utilisateur avant implémentation, si un désaccord
  matériel apparaît** : aucun identifié à ce stade — chaque choix découle directement des contrats
  déjà réels et déjà revus (ADR 0021/0022/0023) ; voir le rapport de revue joint pour confirmation
  indépendante avant de lever ce statut `Proposé`.
