# Parameter Stability V1 : plateau de voisinage déterministe, réutilisation de l'analyse de sensibilité existante, verdict structurellement INCONCLUSIVE sans politique

Status: Proposé

**Contexte** : `AF-V-04` (Parameter Stability) est `READY` (`AF-V-01` terminé, précédence
architecturale `AF-V-06 = DONE`) mais **ne possède aucune ADR scientifique** —
`docs/roadmap/EPICS_AND_TICKETS.md` ne porte que le statut et l'effort estimé, aucun protocole. La
seule trace conceptuelle existante, `docs/architecture/TEST_AND_VALIDATION_ARCHITECTURE.md` §5
point 6, décrit l'intention (« performance médiane autour du "champion" pas radicalement différente
du point testé, signe que le résultat n'est pas un pic isolé ») sans protocole précis.
`docs/architecture/DOMAIN_MODEL.md` confirme que `parameter_stability` est un `validation_type` de
`ValidationRun` au même titre que `walk_forward`/`monte_carlo` (jamais une entité séparée).

**Constat vérifié, prérequis central de cette ADR** : ce dépôt possède déjà, RÉELLEMENT implémenté
et utilisé, un mécanisme d'analyse de sensibilité — `scoring.py::compute_sensitivity_filtered()`
(modes `"single_var"`/`"cross_zone"`/`"grid"`, réunis dans la constante
`optimizer.DETERMINISTIC_DISPATCH_MODES`, ligne 152 : écart-type des scores parmi les candidats
déjà évalués partageant TOUS les autres paramètres avec `best_params`) et
`compute_sensitivity_correlation()` (mode `"general"` : corrélation de rang de Spearman entre la
valeur d'un paramètre et le score) — câblées dans `Optimizer.run()` (lignes ~1180-1194), retournant
`sensitivity: Dict[str, float]` (une valeur par paramètre actif) EN PLUS de `all_results`. Cette
ADR **réutilise ce mécanisme TEL QUEL, jamais réimplémenté** — voir Décision 2. `all_results`
(candidats déjà évalués, `params`/`score`) est également déjà persisté PAR FOLD Walk-Forward
(`train_candidates.csv`, ADR 0021 Décision 12/Slice 4, `walk_forward.py::_train_candidates_to_dataframe()`).

**Conséquence directe de ce constat, cohérente avec l'instruction explicite de l'utilisateur de ne
lancer aucune campagne scientifique réelle coûteuse avant que Walk-Forward/Monte-Carlo/Parameter
Stability soient tous prêts** : Parameter Stability V1 est conçue comme une **ré-analyse purement
statistique et déterministe d'un pool de candidats DÉJÀ évalués** par une recherche `Optimizer`
déjà terminée — **jamais un nouveau backtest, jamais une nouvelle recherche déclenchée**, même
principe que Monte-Carlo V1 (ADR 0022) pour les trades déjà observés.

**Aucun code n'est modifié par cette ADR.** Le statut reste `Proposé` tant que l'utilisateur n'a
pas validé explicitement les décisions ci-dessous, ou tant qu'aucun `HUMAN_GATE_REQUIRED` consolidé
n'a été nécessaire pour un choix scientifique matériellement ambigu.

## Décision 1 — Objet analysé : le pool de candidats DÉJÀ évalués d'une recherche `Optimizer` terminée, jamais un nouveau backtest

**Contrat d'entrée** : une séquence de candidats déjà évalués (`Tuple[dict, ...]`, chaque élément
portant au minimum `params: dict` et `score: float` — même forme que les éléments d'`all_results`
retournés par `Optimizer.run()`, ou rechargés depuis `train_candidates.csv` d'un fold Walk-Forward
persisté), le `best_params: dict` déjà sélectionné (Top-1, ADR 0021 Décision 6 pour Walk-Forward —
mais ce module reste générique, jamais spécifique à Walk-Forward), et le `search_mode: str`
(`"single_var"`/`"cross_zone"`/`"grid"`/`"general"`, EXACTEMENT les valeurs réelles de `cfg.mode`
dans ce dépôt, jamais un nom inventé) sous lequel ces candidats ont été produits. **Ce module ne
sait ni ne doit savoir d'où ces candidats proviennent** (Optimizer TRAIN d'un fold Walk-Forward,
une recherche OOS, une recherche exploratoire) — même principe que Monte-Carlo V1 (ADR 0022
Décision 1/10) : voir Décision 10 pour pourquoi ceci garantit structurellement qu'aucun accès à
`FINAL_HOLDOUT` n'a lieu ici, et qu'aucun nouveau backtest n'est jamais exécuté par ce module.

**Avertissement de circularité, PLUS FORT qu'en Monte-Carlo (finding MAJOR M1, revue scientifique
indépendante)** : `best_params` EST l'argmax in-sample sur ce MÊME pool selon le SCORE utilisé pour
le sélectionner — la dégradation d'un voisin par rapport au vainqueur est donc `>= 0` **pour ce
même score, sur la portion du pool réellement couverte par la grille**, tant qu'aucune autre logique
de sélection Top-1 externe (ex. un critère TEST distinct du score TRAIN d'origine, une contrainte
supplémentaire) n'entre en jeu — **jamais une garantie mathématique absolue en toutes
circonstances** : un `best_params` sélectionné selon un critère DIFFÉRENT de `neighbor_score` (cas
synthétique de test, Décision 13) peut légitimement produire une dégradation négative, jamais
tronquée à zéro silencieusement (voir Décision 13, ligne « Dégradation correctement signée »). Dans
le cas normal (Top-1 par le score lui-même), un paramètre SANS AUCUN effet réel produirait une
dégradation proche de zéro — le plateau "le plus robuste" possible — sans porter la moindre
information de robustesse. **Ce n'est PAS une preuve d'absence de surapprentissage, seulement
l'absence de preuve LOCALE d'un pic isolé sur les axes déjà couverts par la grille** (voir aussi
Décision 3). `ParameterStabilitySpecification.source_candidates_from_optimized_search:
bool` (Décision 11, mirroring `MonteCarloSpecification.source_trades_from_optimized_params`) rend
ce fait explicite et auditable — jamais vérifié automatiquement ici (ce module n'a pas connaissance
de la provenance des candidats au-delà de ce booléen déclaratif).

**Rejeté — relancer de nouveaux backtests à des points perturbés autour de `best_params`** :
techniquement plus proche de l'intention littérale de `TEST_AND_VALIDATION_ARCHITECTURE.md` §5
point 6, mais constituerait une VÉRITABLE campagne scientifique réelle (ré-exécution du moteur),
explicitement exclue par l'instruction de l'utilisateur tant que Walk-Forward/Monte-Carlo/Parameter
Stability ne sont pas tous prêts et qu'aucun budget/identifiants n'est enregistré. Réservé à une
future V2 explicitement autorisée, jamais silencieusement implémenté ici.

## Décision 2 — Méthode : réutilisation directe de `compute_sensitivity_filtered()`/`compute_sensitivity_correlation()`, complétée par une dégradation de voisinage directement interprétable

**`ParameterStabilityEvidence.sensitivity` réutilise TEL QUEL le dictionnaire déjà produit par
`Optimizer.run()`** (`scoring.compute_sensitivity_filtered()`/`compute_sensitivity_correlation()`
selon `search_mode`, jamais réimplémenté, jamais une seconde variante subtilement différente) — un
appelant qui dispose déjà de ce dictionnaire (produit lors de la recherche originale) le transmet
directement ; un appelant qui ne dispose que d'`all_results` le fait recalculer en appelant CES
MÊMES fonctions `scoring.py`, jamais une fonction dupliquée dans ce nouveau module.

**Précision importante sur le filtre réellement réutilisé (correction du finding BLOCKER B1/MAJOR
architecture, les deux revues indépendantes convergent sur ce point) — le filtre de
`compute_sensitivity_filtered()` (`scoring.py` lignes 367-373) comporte DEUX clauses, pas une
seule** : (a) « tous les autres paramètres identiques à `best_params` » ET (b) `r.get("score", 0) >
0` — cette seconde clause exclut SILENCIEUSEMENT tout candidat rejeté par un filtre éliminatoire
dur (`compute_score()` retourne exactement `0.0` pour un candidat rejeté, `scoring.py` ligne ~301).
**Cette exclusion NE DOIT PAS être héritée telle quelle par la statistique de dégradation de
voisinage de cette ADR** : les voisins REJETÉS (score `<= 0`) sont précisément ceux qui
démontreraient le plus fortement un pic isolé (un paramètre légèrement décalé fait s'effondrer la
stratégie au point d'être rejetée) — les censurer produirait une statistique **structurellement
biaisée vers "plateau"**, et rendrait `n_neighbors_by_param[param] == 0` ambigu entre « la grille ne
couvre pas ce voisinage » (aucune preuve) et « tous les voisins ont été rejetés » (la preuve la plus
forte possible d'un pic isolé) — deux lectures opposées, une seule sortie.

**Filtre de voisinage retenu pour la dégradation (délibérément DIFFÉRENT de
`compute_sensitivity_filtered()` sur ce point précis, documenté explicitement, jamais un
"EXACTEMENT le même filtre" trompeur)** : un candidat est un voisin structurel d'un paramètre
`param_name` si (i) son ensemble de CLÉS de paramètres est IDENTIQUE à celui de `best_params`
(jamais seulement itérer les clés de `best_params`, qui laisserait passer un candidat portant des
clés supplémentaires non trackées — finding MINEUR des deux revues) ET (ii) tous ses paramètres
SAUF `param_name` sont égaux à ceux de `best_params` ET (iii) le candidat n'est PAS `best_params`
lui-même (exclusion explicite — `best_params` satisferait trivialement (i)/(ii) pour tout
`param_name`, injectant un point de dégradation `0` garanti dans sa propre distribution, finding
MAJEUR M4 de la revue scientifique) — **AUCUNE exclusion sur le score**. Pour chaque paramètre :

- `n_neighbors_total_by_param[param]` : nombre de voisins structurels trouvés (toutes valeurs de
  score confondues).
- `n_neighbors_rejected_by_param[param]` : parmi eux, combien ont `score <= 0` (rejetés par un
  filtre éliminatoire dur en amont) — un FAIT séparé, jamais fusionné silencieusement dans la
  distribution de dégradation.
- `degradation_by_param[param]` : distribution de dégradation calculée UNIQUEMENT sur les voisins
  NON rejetés (`score > 0`) — un candidat rejeté n'a pas de score réel comparable (`0.0` est un
  SENTINEL technique, jamais une vraie mesure de performance, voir Décision 6) ; son existence est
  déjà rapportée par `n_neighbors_rejected_by_param`, jamais transformée en une valeur numérique
  fabriquée.

**Formule de dégradation** (sur les voisins non rejetés uniquement) :
`(best_score - neighbor_score) / abs(best_score)` si `best_score != 0`, sinon `None` pour ce
candidat (jamais une division par zéro masquée). **Limite explicite de cette formule (finding
MINEUR des deux revues, à documenter, jamais à corriger silencieusement)** : `score` est un
composite BORNÉ (`[0, 100]` dans ce dépôt, `scoring.py`), pas une grandeur à échelle de ratio — un
pourcentage de dégradation n'est donc pas une unité physiquement homogène d'un run à l'autre, et le
dénominateur `abs(best_score)` peut amplifier artificiellement la dégradation relative quand
`best_score` est proche de zéro (même sans y être exactement égal). **`degradation_points_by_param`
(champ séparé, Décision 6/11) rapporte donc AUSSI le delta absolu de points de score**
(`best_score - neighbor_score`, même unité que `score` lui-même, jamais divisée) en plus du
pourcentage de `degradation_by_param` — jamais un seul chiffre sans son complément directement
comparable entre runs.

**Limite structurelle explicite : analyse « un paramètre à la fois », jamais une preuve de
robustesse JOINTE (finding MAJEUR M2, revue scientifique indépendante)** — cette dégradation ne
varie QU'UN SEUL paramètre en maintenant tous les autres strictement fixés à `best_params` : elle
ne peut JAMAIS détecter un pic isolé qui ne serait visible que sur une combinaison de PLUSIEURS
paramètres variant ensemble (une diagonale/un pic joint dans l'espace des paramètres). **Cette
analyse peut donc seulement INFIRMER une robustesse** (trouver une vraie dégradation sur un seul
axe est une preuve réelle d'instabilité) **jamais la CONFIRMER** (l'absence de dégradation sur
chaque axe pris séparément ne prouve rien sur les combinaisons). Pour partiellement compenser, à
coût nul (même pool déjà évalué, aucun nouveau backtest) : `degradation_hamming_le_2` (Décision 6)
agrège, TOUS PARAMÈTRES CONFONDUS, la dégradation des candidats déjà évalués différant de
`best_params` sur **STRICTEMENT ENTRE 1 ET 2 dimensions simultanément** (`1 <= distance de Hamming
<= 2`, JAMAIS `0` — correction du finding MAJOR N1, seconde lecture de la revue scientifique
indépendante : une distance de Hamming `0` désignerait `best_params` lui-même, réintroduisant
exactement le point de dégradation `0` garanti que l'exclusion de la Décision 2 vient de retirer du
cas par-paramètre) — un signal JOINT partiel, toujours purement descriptif, jamais présenté comme
une preuve de robustesse multi-dimensionnelle complète (qui resterait hors scope V1). **Mêmes
compagnons de comptage que le cas par-paramètre, pour la même raison (Décision 6)** :
`n_hamming_le_2_total`/`n_hamming_le_2_rejected` — sans ces deux compteurs, un `degradation_hamming_le_2`
absent serait à nouveau ambigu entre « aucun candidat à distance 1-2 dans le pool » et « tous
rejetés » (la preuve la plus forte d'un pic joint), exactement l'ambiguïté que ce champ a été ajouté
pour compenser au niveau par-paramètre (finding BLOCKER B1) — jamais réintroduite ici sans y penser.

## Décision 3 — Applicabilité limitée aux modes de recherche déterministes ; `"general"` reste honnêtement sans preuve de voisinage LOCAL, jamais confondu avec une preuve de robustesse

Le filtre de voisinage (Décision 2) ne trouve un nombre de voisins statistiquement exploitable QUE
si la recherche source a systématiquement couvert une grille (`search_mode` ∈
`DETERMINISTIC_DISPATCH_MODES` = `{"single_var", "cross_zone", "grid"}`, constante RÉELLE
d'`optimizer.py`, jamais un ensemble inventé) — sous `search_mode="general"`
(échantillonnage/recherche non structurée), quasiment AUCUN candidat déjà évalué ne partage
exactement tous les autres paramètres avec `best_params` par pur hasard. **Jamais un repli
silencieux ou un nombre de voisins gonflé artificiellement** : sous `"general"`, la statistique de
dégradation de voisinage (Décision 2) reste vide, `n_neighbors_total_by_param`/
`n_neighbors_rejected_by_param` honnêtement à `0`.

**`neighborhood_applicability` — champ EXPLICITE, jamais inféré implicitement de champs vides
(correction du finding MAJEUR M3, revue scientifique indépendante)** :
`ParameterStabilityEvidence.neighborhood_applicability` ∈
`{"local_neighborhood_available", "global_correlation_only"}` — fixé directement depuis
`search_mode` (Décision 9 : `DETERMINISTIC_DISPATCH_MODES` -> `"local_neighborhood_available"`,
`"general"` -> `"global_correlation_only"`), jamais déduit après coup d'un dictionnaire vide (un
lecteur qui ne consulterait que les champs numériques ne doit jamais pouvoir confondre « aucune
donnée disponible » avec « analysé et trouvé stable »).

**Précision explicite pour `GATE V` (les deux revues convergent sur ce point)** : `|corrélation de
Spearman|` (mode `"general"`, `sensitivity`) est une statistique de **tendance monotone globale**,
PAS une mesure de plateau LOCAL — une corrélation proche de zéro est parfaitement compatible avec
un pic isolé noyé dans un grand espace de recherche non structuré (elle indique l'absence de
tendance globale, jamais l'absence de sensibilité locale autour de `best_params`). **Un run
`ParameterStabilityEvidence` avec `neighborhood_applicability="global_correlation_only"` NE
SATISFAIT PAS l'exigence de preuve `parameter_stability` de `GATE V`** (`docs/roadmap/MASTER_ROADMAP.md`
§4) — cette évidence reste honnête et persistée (jamais refusée), mais un futur agrégateur `GATE V`
doit exiger `neighborhood_applicability="local_neighborhood_available"` pour compter cette preuve
comme une contribution réelle.

**Précision supplémentaire, `neighborhood_applicability` seul NE SUFFIT PAS (correction du finding
MAJOR N2, seconde lecture de la revue scientifique indépendante)** : `neighborhood_applicability`
est dérivé UNIQUEMENT de `search_mode` (Décision 9), jamais du voisinage RÉELLEMENT trouvé — une
grille clairsemée ou partiellement couverte produit `search_mode` déterministe donc
`neighborhood_applicability="local_neighborhood_available"` **même si `n_neighbors_total_by_param`
vaut `0` pour tous les paramètres** (aucun voisin structurel réellement trouvé) : exactement la
même défaillance que celle que M3 corrigeait, par une seconde voie. **Un futur agrégateur `GATE V`
doit donc exiger LES DEUX conditions, jamais l'une sans l'autre** : (1)
`neighborhood_applicability == "local_neighborhood_available"` ET (2) au moins un paramètre avec
`n_neighbors_total_by_param[param] - n_neighbors_rejected_by_param[param] > 0` (au moins UN voisin
non rejeté réellement observé, quelque part) — un seuil de couverture `> 0` n'est jamais un seuil
inventé (c'est la frontière littérale entre "une preuve existe" et "aucune preuve n'existe"),
jamais un nombre minimal arbitraire au-delà de ce strict minimum.

## Décision 4 — Aucun nombre de simulations, aucune taille d'échantillon à choisir : entièrement déterminé par les candidats déjà évalués

Contrairement à Monte-Carlo V1 (ADR 0022 Décision 4), Parameter Stability V1 n'introduit AUCUN
paramètre de type `n_simulations` — le nombre de voisins analysés par paramètre est EXACTEMENT le
nombre de candidats déjà évalués satisfaisant le filtre de la Décision 2, ni plus ni moins, jamais
un sous-échantillonnage ni un objectif de taille inventé.

## Décision 5 — Aucune graine requise : protocole entièrement déterministe, aucun tirage aléatoire

**Différence majeure et délibérée avec Monte-Carlo V1** (ADR 0022 Décision 5) : cette ADR
n'introduit AUCUN mécanisme de rééchantillonnage aléatoire — chaque statistique (Décision 2) est un
calcul FERMÉ sur un ensemble de candidats déjà entièrement déterminé par la recherche source (déjà
réellement exécutée, déjà déterministe ou déjà seedée selon ADR 0021 Décision 9 pour son propre
compte). Deux appels avec le MÊME pool de candidats, DANS LE MÊME ORDRE, produisent donc des
`ParameterStabilityEvidence` **bit-à-bit identiques PAR CONSTRUCTION** (aucune graine à dériver,
aucun générateur à instancier) — propriété plus forte qu'une simple reproductibilité testée, une
conséquence directe de l'absence totale de hasard dans ce protocole V1. **Précision honnête
(revue architecture indépendante)** : « même pool » signifie ICI même SÉQUENCE ordonnée, pas
seulement même ENSEMBLE de candidats — l'ordre de sommation en virgule flottante (`numpy`, calcul
de percentiles) est techniquement sensible à l'ordre d'entrée ; ce n'est jamais un problème en
pratique puisque `all_results` est déjà produit dans un ordre déterministe stable en amont (trié
par score, `Optimizer.run()`), jamais un `set`/`dict` non ordonné — mais la garantie porte sur la
SÉQUENCE, pas sur un ensemble abstrait.

## Décision 6 — Métriques strictement factuelles ; jamais un jugement "stable"/"instable"

Cohérent avec l'ADR 0021 Décision 13/l'ADR 0022 Décision 6/12 — `ParameterStabilityEvidence` ne
porte QUE des statistiques descriptives :

- `sensitivity: Dict[str, float]` — réutilisé tel quel (Décision 2).
- **`sensitivity_sample_size_by_param: Dict[str, int]` (correction du finding BLOCKER B2, revue
  scientifique indépendante)** : `compute_sensitivity_filtered()` retourne le SENTINEL `0.0` quand
  `len(filtered) < 3`, et `compute_sensitivity_correlation()` retourne `0.0` quand `< 10` paires
  valides OU une corrélation `NaN` (variance nulle) — dans les DEUX cas, `0.0` est INDISCERNABLE
  d'une sensibilité RÉELLEMENT nulle sans connaître la taille d'échantillon sous-jacente. Ce champ
  compte, PAR paramètre, le nombre RÉEL de candidats utilisés en interne par
  `compute_sensitivity_filtered()`/`compute_sensitivity_correlation()` (mêmes critères EXACTS que
  ces fonctions — `score > 0` ET voisinage pour le mode filtré ; `score > 0` ET valeur non-`None`
  pour le mode corrélation — un comptage-seul, jamais une réimplémentation du calcul lui-même,
  intégralement délégué à `scoring.py`). Un `sensitivity[param] == 0.0` avec
  `sensitivity_sample_size_by_param[param] < 3` (mode filtré) ou `< 10` (mode corrélation) DOIT être
  lu comme « non calculable », jamais comme « sensibilité nulle confirmée ». **Limite résiduelle
  honnêtement documentée, jamais silencieusement corrigée (finding MINEUR, seconde lecture de la
  revue scientifique indépendante)** : `compute_sensitivity_correlation()` peut ÉGALEMENT retourner
  `0.0` avec `>= 10` paires si la corrélation calculée est `NaN` (variance nulle du paramètre ou du
  score sur l'échantillon) — un TROISIÈME cas sentinel que `sensitivity_sample_size_by_param` seul
  ne distingue PAS d'une sensibilité réellement nulle à taille suffisante. Non résolu en V1 (résoudre
  proprement exigerait soit de réimplémenter la détection de variance nulle en dehors de
  `scoring.py`, soit de modifier `compute_sensitivity_correlation()` elle-même — les deux hors
  scope d'une réutilisation "telle quelle") — limite explicitement connue plutôt que masquée.
- `n_neighbors_total_by_param: Dict[str, int]` / `n_neighbors_rejected_by_param: Dict[str, int]`
  (Décision 2) — toujours rapportés, y compris `0`, jamais fusionnés en un seul nombre.
- `degradation_by_param: Dict[str, Optional[PercentileDistributionSummary]]` (type générique déjà
  défini par l'ADR 0022 pour `MonteCarloEvidence`, renommé `PercentileDistributionSummary` — revue
  architecture, jamais `MonteCarloDistributionSummary` qui suggérerait à tort une origine unique —
  percentiles `p5`/`p25`/`p50`/`p75`/`p95` de la dégradation en POURCENTAGE parmi les voisins NON
  rejetés, Décision 2) — absent pour un paramètre dont `n_neighbors_total_by_param[param] -
  n_neighbors_rejected_by_param[param] == 0`, jamais une valeur inventée.
- `degradation_points_by_param: Dict[str, Optional[PercentileDistributionSummary]]` — même
  distribution mais en DELTA ABSOLU de points de score (`best_score - neighbor_score`), jamais
  divisé (Décision 2, limite de l'échelle bornée du score).
- `n_hamming_le_2_total: int` / `n_hamming_le_2_rejected: int` (Décision 2) — mêmes compagnons de
  comptage que `n_neighbors_total_by_param`/`n_neighbors_rejected_by_param`, jamais omis.
- `degradation_hamming_le_2: Optional[PercentileDistributionSummary]` (Décision 2) — signal JOINT
  partiel, tous paramètres confondus, `1 <= distance de Hamming <= 2` par rapport à `best_params`
  (jamais `0`, jamais `best_params` lui-même), calculé UNIQUEMENT sur les candidats non rejetés —
  absent si `n_hamming_le_2_total - n_hamming_le_2_rejected == 0`.
- `neighborhood_applicability: str` (Décision 3) — `"local_neighborhood_available"` ou
  `"global_correlation_only"`, jamais inféré implicitement.
- `best_score`/`best_params` : rapportés tels quels (faits de référence).
- `n_candidates_total: int` : taille totale du pool de candidats fourni en entrée.
- `search_mode: str` : rapporté tel quel.

**Aucun jugement "plateau large"/"pic isolé"/"stable"/"instable" n'est produit** — ce jugement
resterait de la responsabilité exclusive d'une politique de verdict pré-enregistrée (Décision 12),
exactement comme pour Walk-Forward/Monte-Carlo.

**Risque de comparaisons multiples explicitement signalé, jamais outillé en V1 (mirroring l'ADR
0022 Décision 2, absent de la version initiale de cette ADR — trouvaille Q5, revue scientifique
indépendante)** : invoquer ce module sur de nombreux vainqueurs candidats (plusieurs folds, plusieurs
recherches) et ne retenir que celui dont le plateau apparaît le plus favorable (« cherry-pick du
plateau le plus plat ») est une forme de data-snooping NON tracée par ce protocole —
`UnknownVerdictPolicy` ferme le canal d'un verdict inventé POUR UN run donné, mais ne referme PAS ce
canal-ci. Une correction appropriée resterait une **extension V2 réservée**, jamais inventée ici.

## Décision 7 — Comportement avec peu ou aucun candidat/voisin : jamais une erreur, une observation factuelle honnête

**Pool de candidats vide (`n_candidates_total == 0`)** : mathématiquement indéfini (mirroring
Décision 7 de l'ADR 0022) — `ParameterStabilityEvidence` reste produite avec
`zero_candidates_input=True`, **jamais une exception**. Tous les champs `Optional[...]`
(`sensitivity`, `degradation_by_param`, `degradation_points_by_param`, `degradation_hamming_le_2`,
`best_score`/`best_params`) restent `None`/vides — jamais une valeur inventée. Les champs
COMPTEURS non-`Optional` (`n_neighbors_total_by_param`/`n_neighbors_rejected_by_param`/
`n_hamming_le_2_total`/`n_hamming_le_2_rejected`) valent honnêtement `0` (un compte réel et exact
de zéro candidat, jamais `None` — `0` est la valeur EXACTE, pas une absence de valeur, précision
apportée en seconde lecture de la revue scientifique indépendante). **Aucun voisin non rejeté pour
un paramètre donné (cas général, candidats non vides)**
(`n_neighbors_total_by_param[param] - n_neighbors_rejected_by_param[param] == 0`, cas normal sous
`"general"` ou une grille clairsemée, ou si tous les voisins structurels ont été rejetés) : jamais
bloquant, `degradation_by_param[param]`/`degradation_points_by_param[param]` restent absents/`None`,
jamais une valeur inventée — les faits `n_neighbors_total_by_param[param]`/
`n_neighbors_rejected_by_param[param]` sont eux-mêmes la réponse honnête (et, si
`n_neighbors_rejected_by_param[param]` est élevé, la preuve la plus forte possible d'un pic isolé
sur cet axe — Décision 2).

## Décision 8 — Persistance et fingerprint, mais AUCUN mécanisme de reprise incrémentale (mirroring de la justification de l'ADR 0022 Décision 8)

Structure additive sous `results/job_xxx/parameter_stability/` (`atomic_json_store.save_atomic()`,
jamais un `open()`/`json.dump()` direct) — `manifest.json` (fingerprint : `search_mode`,
`search_space_hash` si disponible — réutilise `walk_forward._search_space_hash()` si l'appelant en
dispose, jamais recalculé indépendamment ici puisque ce module reste sans dépendance vers
`walk_forward.py`, voir Décision 10 — `n_candidates_total`, `parameter_stability_semantics_version`,
`verdict_policy_id`) et `evidence.json`. **Aucun mécanisme de reprise incrémentale** : ce protocole
est un calcul déterministe fermé sur un pool déjà en mémoire (Décision 14, budget de calcul) — une
interruption/reprise serait une complexité non justifiée par un coût réel (`YAGNI`, même
raisonnement que l'ADR 0022).

## Décision 9 — Taxonomie d'erreurs explicite, fail-closed

| Condition | Comportement |
|---|---|
| `n_candidates_total == 0` | **Jamais une erreur** — `zero_candidates_input=True` (Décision 7) |
| `search_mode` inconnu (hors `DETERMINISTIC_DISPATCH_MODES ∪ {"general"}`) | `ValueError` immédiat, jamais une valeur par défaut silencieuse |
| `best_params` absent du pool de candidats fourni | `ValueError` immédiat — un `best_params` qui ne correspond à AUCUN candidat évalué serait incohérent, jamais résolu à l'aveugle. **Égalité par égalité stricte de `dict`** (`==`, même clés/mêmes valeurs — comparaison `float` standard Python, jamais `np.isclose` : les valeurs de paramètres de ce dépôt sont des points de grille déjà discrets, aucune tolérance flottante à inventer ici) |
| Relecture d'une évidence persistée sous une version de sémantique différente | Nouvelle exception `ParameterStabilitySemanticsMismatch(ValueError)`, mirroring exact de `WalkForwardSemanticsMismatch`/`MonteCarloSemanticsMismatch` |
| `verdict_policy_id` fourni mais aucune politique enregistrée | `UnknownVerdictPolicy` — **RÉUTILISE TELLE QUELLE** l'exception déjà définie dans `validation_run.py`, jamais une classe dupliquée (troisième réutilisation après Walk-Forward et Monte-Carlo) |

## Décision 10 — Impossibilité structurelle d'accéder à `FINAL_HOLDOUT`

Parameter Stability V1 **ne connaît ni `engine.py`, ni `optimizer.py`, ni `DatasetSplitPlan`, ni
`FINAL_HOLDOUT`, ni `nasdaq_3m.csv`** — son seul contrat d'entrée est un pool de candidats déjà
évalués (Décision 1). Il ne peut donc STRUCTURELLEMENT jamais déclencher un nouvel accès au holdout
ni une nouvelle recherche. **Réutilise `scoring.compute_sensitivity_filtered()`/
`compute_sensitivity_correlation()` (Décision 2)** — `scoring.py` est lui-même un module de calcul
pur (aucune connaissance de `FINAL_HOLDOUT`), ce qui préserve l'invariant.

## Décision 11 — `ParameterStabilitySpecification`/`ParameterStabilityEvidence`, nouveau `validation_type = "parameter_stability"`

Mirroring exact de `WalkForwardSpecification`/`WalkForwardEvidence` (ADR 0021) et
`MonteCarloSpecification`/`MonteCarloEvidence` (ADR 0022), ajoutés à `validation_run.py` :

```python
VALIDATION_TYPE_PARAMETER_STABILITY = "parameter_stability"  # déjà utilisé par DOMAIN_MODEL.md

@dataclass(frozen=True)
class ParameterStabilitySpecification:
    source_validation_run_id: str  # traçabilité, mirroring ADR 0022 Décision 5
    search_mode: str
    source_candidates_from_optimized_search: bool  # avertissement de circularité, Décision 1
    parameter_stability_semantics_version: str
    verdict_policy_id: Optional[str] = None

def build_parameter_stability_specification(
    source_validation_run_id: str,
    search_mode: str,
    source_candidates_from_optimized_search: bool,
    verdict_policy_id: Optional[str] = None,
) -> ParameterStabilitySpecification:
    """SEULE construction sanctionnée — valide search_mode (Décision 9),
    parameter_stability_semantics_version toujours fixée en interne (même principe qu'ADR 0022
    Décision 5 pour monte_carlo_semantics_version — jamais un paramètre)."""
    ...

@dataclass(frozen=True)
class ParameterStabilityEvidence:
    n_candidates_total: int
    zero_candidates_input: bool
    search_mode: str
    neighborhood_applicability: str  # "local_neighborhood_available" | "global_correlation_only", Décision 3
    best_score: Optional[float]
    best_params: Optional[dict]
    sensitivity: Dict[str, float]
    sensitivity_sample_size_by_param: Dict[str, int]  # Décision 6, correction BLOCKER B2
    n_neighbors_total_by_param: Dict[str, int]
    n_neighbors_rejected_by_param: Dict[str, int]  # Décision 2/6, correction BLOCKER B1
    degradation_by_param: Dict[str, Optional["PercentileDistributionSummary"]]  # type renommé, revue architecture
    degradation_points_by_param: Dict[str, Optional["PercentileDistributionSummary"]]  # Décision 6, delta absolu
    n_hamming_le_2_total: int  # Décision 2/6, compagnon de comptage (correction N1)
    n_hamming_le_2_rejected: int  # Décision 2/6, compagnon de comptage (correction N1)
    degradation_hamming_le_2: Optional["PercentileDistributionSummary"]  # Décision 2/6, signal joint partiel, distance 1-2 uniquement
    execution_status: str
    scientific_verdict: str
    verdict_reasons: Tuple[str, ...]

# _VALIDATION_TYPES : QUATRIÈME entrée du dict littéral existant, jamais une affectation a
# posteriori (même correction de forme qu'ADR 0022 Décision 11) :
#
# _VALIDATION_TYPES: Dict[str, Tuple[type, type]] = {
#     VALIDATION_TYPE_OOS: (OosValidationSpecification, OosValidationEvidence),
#     VALIDATION_TYPE_WALK_FORWARD: (WalkForwardSpecification, WalkForwardEvidence),
#     VALIDATION_TYPE_MONTE_CARLO: (MonteCarloSpecification, MonteCarloEvidence),
#     VALIDATION_TYPE_PARAMETER_STABILITY: (ParameterStabilitySpecification, ParameterStabilityEvidence),
# }
```

`execution_status` ∈ {`"completed"`} uniquement en V1 (même raisonnement que l'ADR 0022 Décision 11
— aucune notion d'interruption, calcul trop court/déterministe).

**Placement du code exécutable** — nouveau module top-level `parameter_stability.py` (jamais dans
`validation_run.py`, qui reste un leaf sans algorithme ; jamais dans `scoring.py`, qui reste
l'unique source des fonctions de sensibilité réutilisées, jamais dupliquées) :
`analyze_parameter_stability(candidates: Tuple[dict, ...], best_params: dict, spec:
ParameterStabilitySpecification) -> ParameterStabilityEvidence`, fonction pure, aucun import
`engine.py`/`optimizer.py`/`dataset_split.py`/`walk_forward.py` — seul import autorisé hors
`validation_run.py` : `scoring.compute_sensitivity_filtered`/`compute_sensitivity_correlation`
(Décision 2/10 — `scoring.py` est déjà un module de calcul pur, aucune régression d'invariant).

## Décision 12 — Séparation stricte preuve factuelle / verdict scientifique (mirroring exact de l'ADR 0021 Décision 13/ADR 0022 Décision 12)

`scientific_verdict` reste **TOUJOURS `"INCONCLUSIVE"`** sans `verdict_policy_id` enregistré —
même philosophie, même mécanisme, **même exception `UnknownVerdictPolicy`** (troisième
réutilisation). Aucune politique concrète de seuils "plateau acceptable"/"pic isolé" n'existe dans
ce dépôt à ce jour, cette ADR n'en invente aucune — même discipline de pré-enregistrement que l'ADR
0022 Décision 12 (toute future politique doit être définie/committée AVANT le run qu'elle juge).

## Décision 13 — Matrice TDD

| Cas | Test |
|---|---|
| Déterminisme bit-à-bit | Deux appels, même pool de candidats DANS LE MÊME ORDRE -> `ParameterStabilityEvidence` strictement égale (propriété garantie PAR CONSTRUCTION, Décision 5 — pas seulement testée empiriquement ; l'ordre d'entrée fait partie du contrat, `all_results` étant déjà trié de façon déterministe en amont, jamais un `set`/`dict` non ordonné) |
| `sensitivity` réutilisé tel quel | Sur un pool synthétique, `sensitivity` produit par ce module est BYTE-IDENTIQUE à un appel direct de `scoring.compute_sensitivity_filtered()`/`compute_sensitivity_correlation()` sur les mêmes données |
| `sensitivity` sentinel jamais confondu avec une valeur réelle | Un pool avec `< 3` voisins filtrés (mode déterministe) ou `< 10` paires (mode `"general"`) produit `sensitivity[param] == 0.0` ET `sensitivity_sample_size_by_param[param]` reflétant le compte réel insuffisant — distingué d'un pool avec un vrai zéro statistique à taille suffisante |
| Filtre de voisinage JAMAIS identique à `compute_sensitivity_filtered()` sur la clause de score | Un pool synthétique avec des voisins structurels À LA FOIS `score > 0` ET `score <= 0` (rejetés) : `n_neighbors_total_by_param` compte les DEUX, `n_neighbors_rejected_by_param` compte UNIQUEMENT les rejetés, `degradation_by_param`/`degradation_points_by_param` n'agrègent QUE les non-rejetés — preuve que ce module NE réutilise PAS aveuglément la clause `score > 0` de `compute_sensitivity_filtered()` (Décision 2) |
| `best_params` exclu de son propre voisinage | `best_params` lui-même n'apparaît JAMAIS dans les candidats comptés par `n_neighbors_total_by_param`/agrégés par `degradation_by_param` (n'injecte jamais un point de dégradation `0` garanti) |
| Clés de paramètres exactes | Un candidat portant une clé de paramètre SUPPLÉMENTAIRE absente de `best_params` n'est JAMAIS compté comme voisin structurel (Décision 2, exclusion des "faux voisins") |
| Dégradation correctement signée | Un voisin STRICTEMENT MEILLEUR que `best_params` (cas synthétique construit) produit une dégradation NÉGATIVE, jamais tronquée à zéro silencieusement ; `degradation_points_by_param` reste cohérent en signe avec `degradation_by_param` |
| `degradation_hamming_le_2` distinct de l'analyse par paramètre | Sur un pool synthétique où un candidat variant 2 paramètres simultanément dégrade fortement le score mais où chaque paramètre pris séparément (Hamming=1) ne montre AUCUNE dégradation, `degradation_hamming_le_2` capture cette dégradation alors que `degradation_by_param` ne la voit pas — preuve de la limite « un paramètre à la fois » (Décision 2) et de la valeur ajoutée de ce signal complémentaire |
| `degradation_hamming_le_2` exclut `best_params` lui-même | `best_params` (distance de Hamming `0`) n'est JAMAIS compté dans `n_hamming_le_2_total` ni agrégé dans `degradation_hamming_le_2` (correction du finding MAJEUR N1) |
| `n_hamming_le_2_total`/`n_hamming_le_2_rejected` toujours rapportés séparément | Un pool synthétique avec des candidats à distance 1-2 À LA FOIS `score > 0` et rejetés (`score <= 0`) : les deux compteurs divergent, `degradation_hamming_le_2` n'agrège que les non-rejetés (même discipline que le cas par-paramètre, correction N1) |
| `search_mode="general"` | `neighborhood_applicability == "global_correlation_only"`, `n_neighbors_total_by_param`/`n_neighbors_rejected_by_param` valent `0` pour chaque paramètre sur un pool synthétique sans coïncidence exacte de voisinage ; `sensitivity` reste peuplé (Spearman) |
| `search_mode` déterministe | `neighborhood_applicability == "local_neighborhood_available"` |
| `n_candidates_total == 0` | `zero_candidates_input=True`, tous les champs `None`/vides, aucune exception |
| `best_params` absent du pool | `ValueError` |
| `search_mode` invalide | `ValueError` |
| `verdict_policy_id=None` | `scientific_verdict == "INCONCLUSIVE"` |
| `verdict_policy_id` fourni | `UnknownVerdictPolicy` levée (réutilisation directe) |
| Round-trip disque | `ParameterStabilityEvidence` -> `build_validation_run()` -> `save_validation_run()` -> `load_validation_run()` préserve tous les champs, y compris les dicts imbriqués et `degradation_hamming_le_2` |
| Fingerprint | Relecture sous une `parameter_stability_semantics_version` différente lève `ParameterStabilitySemanticsMismatch` |
| Aucune dépendance moteur | Test d'import statique : `parameter_stability.py` n'importe ni `engine`, ni `optimizer`, ni `dataset_split`, ni `walk_forward` (seul `scoring`/`validation_run` autorisés) |
| Aucun accès holdout | `parameter_stability.py`/ses tests ne référencent jamais `FINAL_HOLDOUT`/`HoldoutAccessEvent` |
| Cohérence avec un run Walk-Forward réel | Sur `train_candidates.csv` d'un fold Walk-Forward réel (fixture existante de `tests/test_walk_forward.py`), `analyze_parameter_stability()` produit un `sensitivity`/`degradation_by_param` cohérent avec les paramètres réellement variés dans ce fold |

## Décision 14 — Budget de calcul estimé pour une exécution réelle

**Coût négligeable, encore plus faible que Monte-Carlo V1 (ADR 0022 Décision 14)** : aucune
ré-exécution du moteur, aucun tirage aléatoire, un simple filtrage/agrégation sur un pool de
candidats déjà en mémoire (typiquement quelques dizaines à quelques milliers de candidats pour une
recherche réelle de ce dépôt) — de l'ordre de la **fraction de seconde à quelques secondes** sur un
poste de travail standard. Ne consomme AUCUN budget Claude/crédit d'API.

## Conséquences

- **`AF-V-04` reste `implementation: NOT STARTED`** — cette ADR ne modifie aucun code.
- Réutilise directement `scoring.compute_sensitivity_filtered()`/`compute_sensitivity_correlation()`
  (déjà implémentées et utilisées par `Optimizer.run()`) — première réutilisation explicite d'un
  mécanisme de calcul pré-existant par le socle `ValidationEvidence` typé (AF-V-06).
- **Nouvelle dépendance d'implémentation identifiée** : comme pour Monte-Carlo (ADR 0022,
  Conséquences), un futur appelant réel devra assembler `candidates`/`best_params`/`search_mode`
  depuis un run déjà exécuté — `train_candidates.csv` (Walk-Forward, Slice 4) fournit déjà cette
  donnée réelle par fold ; un futur appelant côté OOS/exploration générale devra transporter
  `all_results` directement depuis `Optimizer.run()`, jamais relu depuis une structure qui ne
  l'expose pas aujourd'hui.
- **Points restant à valider explicitement par l'utilisateur avant implémentation, si un désaccord
  matériel apparaît** : aucun identifié à ce stade — chaque choix est justifié par un mécanisme déjà
  réellement implémenté dans ce dépôt (`scoring.py`) plutôt qu'une préférence esthétique ; voir le
  rapport de revue joint pour confirmation indépendante avant de lever ce statut `Proposé`.
- **Impact cross-ADR déjà appliqué (2026-09-22, revue architecture)** : la Décision 6 réutilise
  `PercentileDistributionSummary` (ADR 0022), renommée depuis `MonteCarloDistributionSummary` dans
  le code réel déjà mergé (`validation_run.py`/`monte_carlo.py`/leurs tests) précisément pour
  permettre cette réutilisation sans ambiguïté de nommage — voir l'amendement post-merge documenté
  dans les Conséquences de l'ADR 0022 elle-même. Corrigé aussi dans le même geste : `ValidationSpecification`/
  `ValidationEvidence` (`validation_run.py`, alias `Union` typés) n'avaient jamais été étendus pour
  inclure `MonteCarloSpecification`/`MonteCarloEvidence` lors de leur ajout (Slice 1 AF-V-03,
  lacune pré-existante non introduite par cette ADR, trouvée par la revue architecture indépendante
  d'ADR 0023) — corrigé en même temps que le renommage ; la future implémentation d'AF-V-04 devra
  y ajouter `ParameterStabilitySpecification`/`ParameterStabilityEvidence` à son tour.
