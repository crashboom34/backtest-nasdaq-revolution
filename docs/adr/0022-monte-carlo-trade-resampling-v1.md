# Monte-Carlo V1 : rééchantillonnage de trades, risque de séquence vs incertitude d'échantillonnage, verdict structurellement INCONCLUSIVE sans politique

Status: Proposé

**Contexte** : `AF-V-03` (Monte-Carlo) est `READY` (`AF-V-01` terminé, précédence architecturale
`AF-V-06 = DONE`) mais **ne possède aucune ADR scientifique** — `docs/roadmap/EPICS_AND_TICKETS.md`
ne porte que le statut et l'effort estimé, aucun protocole. La seule trace conceptuelle existante,
`docs/architecture/TEST_AND_VALIDATION_ARCHITECTURE.md` §2 (« architecture uniquement, non
implémentée »), esquissait un Monte-Carlo fondé sur des **perturbations d'exécution** (ordre des
trades, spread, slippage, échecs d'exécution simulés) — un protocole nécessitant un moteur
d'exécution stochastique qui n'existe pas aujourd'hui (`CONTEXT.md` : spread/slippage sont des
hypothèses **fixes**, jamais aléatoires ; `docs/architecture/TEST_AND_VALIDATION_ARCHITECTURE.md`
§3 liste latence/liquidité/tailles minimales comme absents). Cette ADR **remplace explicitement**
cette esquisse par un protocole de **rééchantillonnage statistique des trades déjà observés**
(bootstrap/permutation), seul compatible avec les données réellement disponibles aujourd'hui —
aucune ré-exécution du moteur, aucune modélisation stochastique de l'exécution inventée pour
l'occasion. `docs/architecture/DOMAIN_MODEL.md` confirme que `monte_carlo` est un `validation_type`
de `ValidationRun` au même titre que `walk_forward` (jamais une entité séparée) — cette ADR
s'inscrit dans le socle typé déjà posé par `AF-V-06`/`validation_run.py`.

**Aucun code n'est modifié par cette ADR.** Le statut reste `Proposé` tant que l'utilisateur n'a
pas validé explicitement les décisions ci-dessous, ou tant qu'aucun `HUMAN_GATE_REQUIRED` consolidé
n'a été nécessaire pour un choix scientifique matériellement ambigu (voir section « Conséquences »).

## Décision 1 — Objet rééchantillonné : le PnL individuel de chaque trade, jamais le PnL journalier ni la courbe d'equity brute

**Rééchantillonné : `net_ret_pct` (ou l'équivalent PnL) de chaque trade individuel**, tel que déjà
produit par `engine.run_backtest()`/`execute_walk_forward_fold()` — l'unité ATOMIQUE déjà calculée
et disponible dans ce dépôt (`FoldResult`/les CSV `oos_trades.csv` de Slice 4 exposent déjà les
trades individuels ; `OosValidationEvidence`, elle, ne porte que des agrégats — voir Décision 11
sur le contrat d'entrée qui en découle).

**Rejeté — PnL journalier** : nécessiterait de réagréger les trades sur un axe calendaire (quels
jours sans trade ? quel fuseau ? quelle définition d'une "journée" pour une position tenue
plusieurs jours ?) — une reconstruction non triviale, absente de tout contrat existant, qui
inventerait une nouvelle notion temporelle jamais validée par l'utilisateur. Le trade individuel,
lui, est déjà une unité de mesure existante et sans ambiguïté.

**Rejeté — courbe d'equity brute** : une courbe d'equity est un **produit cumulatif** (chaînage
multiplicatif des rendements, ADR 0021 Décision 15) dans un ORDRE donné, pas une collection
d'observations indépendantes — la rééchantillonner directement (ex. bootstrap sur les VALEURS de
la courbe) mélangerait des points structurellement auto-corrélés (chaque point dépend de tous les
précédents) et produirait des statistiques trompeuses. La courbe d'equity reste un **produit
dérivé** de la Décision 2 (reconstruite APRÈS rééchantillonnage des trades), jamais l'objet
rééchantillonné lui-même — même principe déjà retenu par l'ADR 0021 Décision 15 pour l'agrégation
OOS (« chaîner les rendements normalisés », jamais concaténer des valeurs absolues).

**Avertissement de biais de sélection (revue scientifique indépendante, finding MAJOR M1)** : si
la séquence de trades fournie provient d'une stratégie dont les paramètres ont été choisis par
`Optimizer` sur CES MÊMES données, le Monte-Carlo (permutation ET bootstrap) quantifie le bruit
d'échantillonnage **conditionnellement aux paramètres déjà retenus** — il ne quantifie JAMAIS le
biais de sélection lui-même (le fait que ces paramètres ont été choisis, parmi d'autres, pour bien
performer sur ces données). `MonteCarloSpecification.source_trades_from_optimized_params: bool`
(Décision 11) rend ce fait explicite et auditable plutôt que silencieusement supposé — jamais
vérifié automatiquement ici (ce module n'a pas connaissance de la provenance des trades au-delà de
ce booléen déclaratif fourni par l'appelant), mais consigné pour empêcher que ce module ne
produise, sans avertissement, l'illusion d'une rigueur statistique qu'il ne peut pas fournir seul.

**Contrat d'entrée** : le Monte-Carlo V1 consomme une **séquence ordonnée de rendements de trades**
(`Tuple[float, ...]`, `net_ret_pct` par trade, dans l'ordre chronologique d'observation) — fournie
par l'appelant, jamais recalculée en interne. Ce module ne sait ni ne doit savoir d'où ces trades
proviennent (OOS, Walk-Forward, un backtest simple) — voir Décision 10 pour pourquoi ceci
garantit structurellement qu'aucun accès à `FINAL_HOLDOUT` n'a lieu ici.

## Décision 2 — Deux méthodes retenues, jamais fusionnées : permutation (risque de séquence) et bootstrap avec remise (incertitude d'échantillonnage)

**Les deux méthodes classiques et complémentaires de la littérature sont retenues, produites
SÉPARÉMENT dans la même `MonteCarloEvidence`** (jamais une seule valeur composite qui masquerait
laquelle des deux questions est répondue) :

1. **`sequence_risk` (permutation/réordonnancement)** : ré-ordonne ALÉATOIREMENT le MÊME ensemble
   de trades observés (aucun trade ajouté, retiré ou dupliqué), reconstruit la courbe d'equity
   chaînée pour chaque permutation (même méthode de chaînage de rendements que l'ADR 0021 Décision
   15 — **produit** de `(1+r_i)`, jamais une somme), mesure la distribution du **max drawdown**
   observable sur cette trajectoire (voir Décision 6 pour la définition précise, distincte du
   `max_dd_pct` du moteur). Le rendement net final est **mathématiquement identique** à chaque
   permutation (la multiplication est commutative) — seule la trajectoire (et donc l'ampleur du
   pire creux en cours de route) varie. Répond à : *« Si j'avais vécu ces mêmes gains/pertes dans
   un ORDRE différent, quel aurait été mon pire creux de trajectoire ? »*
2. **`sampling_uncertainty` (bootstrap avec remise)** : tire, POUR CHAQUE simulation, `n_trades`
   trades **avec remise** parmi l'ensemble observé (même taille d'échantillon que l'observation
   réelle — un choix explicite, voir Décision 4), reconstruit la courbe et mesure la distribution
   du **rendement net final** ET du **max drawdown**. Contrairement à la permutation, le rendement
   final VARIE ici (un même trade gagnant peut être tiré plusieurs fois, ou jamais). Répond à :
   *« Si l'échantillon de trades observé n'était qu'un tirage parmi d'autres tirages possibles
   d'un même processus sous-jacent, quelle plage de résultats aurait été plausible ? »*

**Ces deux questions sont délibérément gardées SÉPARÉES** (exigence explicite de l'utilisateur) :
la permutation isole le risque de trajectoire à statistiques figées ; le bootstrap isole
l'incertitude d'échantillonnage à taille d'échantillon figée. Les fusionner (ex. un seul
"Monte-Carlo composite" mélangeant réordonnancement et rééchantillonnage avec remise) rendrait la
distribution résultante impossible à interpréter sans ambiguïté quant à SA cause.

**Ni l'une ni l'autre méthode n'est un test d'hypothèse (finding MAJOR M2, revue scientifique
indépendante)** : aucune hypothèse nulle n'est formulée, aucune p-value n'est calculée — les
percentiles produits (Décision 6) sont des statistiques DESCRIPTIVES de la distribution simulée,
jamais un test de significativité. **Risque de comparaisons multiples explicitement signalé,
jamais outillé en V1** : invoquer ce module sur `N` stratégies candidates puis retenir celle dont
le résultat observé tombe le plus favorablement dans sa propre distribution simulée (« cherry-pick
du meilleur p5 ») est une forme de data-snooping NON tracée par ce protocole — une correction
appropriée (ex. White's Reality Check, Hansen's SPA test, Deflated Sharpe Ratio) resterait une
**extension V2 réservée**, jamais inventée ici faute de politique déjà validée.

## Décision 3 — Dépendance temporelle et régimes de marché : délibérément NON préservés en V1, limitation explicite

**Ni la permutation ni le bootstrap ne préservent la dépendance temporelle ou les régimes** (les
deux méthodes traitent chaque trade comme une observation échangeable/i.i.d. conditionnellement à
la stratégie) — **choix V1 délibérément conservateur et explicite**, pas un oubli. Un bloc-bootstrap
(rééchantillonnage de BLOCS consécutifs de trades pour préserver l'autocorrélation locale/les
régimes) ou un modèle conditionnel aux régimes de marché sont des extensions **V2 réservées**,
nécessitant une définition explicite et validée de ce qu'est un "régime" dans ce dépôt (absente
aujourd'hui — `CONTEXT.md` ne définit aucune taxonomie de régime) : **hors scope de cette ADR**,
jamais inventée ici. `MonteCarloSpecification.monte_carlo_semantics_version` (Décision 8) versionne
explicitement ce choix pour qu'une future V2 (bloc-bootstrap) ne soit jamais confondue avec ces
résultats i.i.d.

**Sens du biais explicitement énoncé (correction du finding MAJOR M3, revue scientifique
indépendante — l'aveu initial de cette ADR disait « non préservé » sans dire dans quel sens cela
trompe)** : si les trades réels présentent une autocorrélation POSITIVE (regroupement de pertes en
série, régimes de marché défavorables prolongés — plausible pour une stratégie de suivi de
tendance sur NASDAQ M3, jamais vérifié ni supposé ici), alors la permutation **SOUS-ESTIME** le vrai
risque de queue (le pire drawdown réellement vécu, gouverné par les VRAIES séries consécutives,
sera pire que ce que suggère une distribution i.i.d. mélangée) — l'observation réelle tombera alors
en queue de la distribution simulée et pourrait être lue à tort comme « malchance isolée » plutôt
que comme un signe que l'hypothèse d'indépendance est fausse pour cette stratégie. **Jamais un
seuil inventé pour corriger ce biais** (contraire à la discipline de cette ADR) — à la place,
`MonteCarloEvidence` rapporte deux FAITS supplémentaires, purement descriptifs, permettant à un
lecteur de juger lui-même la plausibilité de l'hypothèse i.i.d. pour CE jeu de trades précis :
`observed_lag1_autocorrelation` (autocorrélation empirique des `net_ret_pct` à l'ordre 1) et
`observed_longest_losing_streak` (plus longue série de pertes consécutives réellement observée,
comparable visuellement à la distribution de cette même statistique sous les permutations simulées
— aucun seuil de significativité calculé ici, voir Décision 12).

## Décision 4 — 10 000 simulations par méthode, taille d'échantillon = `n_trades` observé, justification par l'erreur-type

**`n_simulations = 10 000`** (constante fixe V1, `MONTE_CARLO_DEFAULT_N_SIMULATIONS` — jamais un
paramètre d'appel librement re-choisi, voir Décision 5) **pour
CHAQUE méthode** (soit 20 000 tirages au total pour les deux). **Justification corrigée (revue
scientifique indépendante, réponse ciblée — l'argument initial de cette ADR était imprécis)** :
`1/sqrt(n)` est l'erreur-type d'une **proportion**, pas d'un **quantile** — l'erreur-type d'un
percentile estimé suit `sqrt(p(1-p)/n) / f(x_p)` (dépend de la densité locale `f` au point
considéré, plus large en queue `p5`/`p95` qu'au centre `p50`). Plus important encore :
`n_simulations` contrôle uniquement l'**erreur de simulation** — la précision avec laquelle on
estime les propriétés d'une distribution DÉJÀ entièrement déterminée par les trades observés. La
précision **statistique** réelle de l'exercice est gouvernée par `n_trades_observés` (typiquement
quelques dizaines sur un run réel de ce dépôt), pas par `n_simulations` : 10 000 tirages sur 40
trades produisent une estimation TRÈS précise d'une distribution dont le support ne compte que 40
atomes distincts — `n_simulations` élevé ne compense jamais un `n_trades_observés` faible.
`MonteCarloEvidence.n_input_trades` (Décision 11) reste donc la donnée à consulter en priorité pour
juger la portée réelle de tout percentile rapporté. `n_simulations=10 000` demeure un choix
défendable comme plancher de précision de SIMULATION (ordre de grandeur standard, 1 000-10 000+
dans la littérature), sans coût de calcul significatif (Décision 14 — aucune ré-exécution du
moteur). Pour la permutation, si `n_trades_observés! < n_simulations` (relation MATHÉMATIQUE,
jamais un seuil scientifique inventé — vaut `7! = 5040 < 10 000` avec le défaut V1, mais reste
correcte pour tout `n_simulations` paramétré différemment), l'espace des permutations DISTINCTES
est plus petit que `n_simulations` — **énumération exhaustive** de toutes les permutations
distinctes plutôt qu'un tirage aléatoire avec répétition de permutations identiques ; dans ce cas,
les percentiles rapportés sont **EXACTS** (calculés sur la distribution complète, jamais une
estimation Monte-Carlo) plutôt qu'estimés.

**Taille d'échantillon du bootstrap = `n_trades` observé** (jamais un nombre différent inventé) —
préserve la comparabilité directe avec la Décision 2 (répondre "à taille d'échantillon égale à
l'observation réelle, quelle plage de résultats est plausible ?"), cohérent avec la convention
bootstrap standard (rééchantillonner à la taille originale de l'échantillon).

## Décision 5 — `master_seed` OBLIGATOIRE (jamais `Optional`), dérivation SHA256 par domaine, reproductibilité exacte bit-à-bit

**`MonteCarloSpecification.master_seed: int` est OBLIGATOIRE** (contrairement à
`WalkForwardSpecification.master_seed: Optional[int]`, ADR 0021 Décision 9) : contrairement à
Walk-Forward (où un mode de recherche déterministe, ex. `grid`, reste reproductible sans seed —
ADR 0021, tests `TestRunFoldTrainRequiresSeedOrDeterministic`), **la sortie ENTIÈRE du Monte-Carlo
EST le rééchantillonnage aléatoire lui-même** — sans seed, AUCUN résultat ne serait jamais
reproductible, ce qui violerait la discipline de reproductibilité déjà établie dans tout ce dépôt
(ADR 0021 Décision 9, `atomic_json_store`, garde de reprise `_VERSION`).

**`master_seed` n'est JAMAIS un entier choisi librement par l'appelant (correction du finding
MAJOR M4, revue scientifique indépendante — « seed shopping »)** : rien n'empêcherait sinon de
rejouer un Monte-Carlo sur la même séquence de trades avec `master_seed=1, 2, 3, ...` jusqu'à
obtenir la distribution la plus favorable, un canal de p-hacking à coût nul pour l'appelant. **`master_seed`
est dérivé DÉTERMINISTIQUEMENT de `source_validation_run_id`** (jamais fourni directement) :

```
_MONTE_CARLO_MASTER_SEED_DOMAIN_TAG = "mc-v1-master"
master_seed = int(sha256(f"{source_validation_run_id}:{_MONTE_CARLO_MASTER_SEED_DOMAIN_TAG}").hexdigest(), 16)
```

Un `source_validation_run_id` donné produit donc TOUJOURS le même `master_seed` via
`build_monte_carlo_specification()`. **Précision honnête sur la portée de cette garantie (résidu
mineur relevé par la seconde lecture de la revue scientifique)** : comme pour la garde
`requires_clean_worktree`/l'attribution de l'ADR 0021 Décision 7, cette garantie reste
**disciplinaire, pas structurelle** — `MonteCarloSpecification` demeure une dataclass frozen
ordinaire, rien n'empêche mécaniquement un code appelant de construire l'objet directement en
contournant le builder (comme pour toute dataclass de ce dépôt) ; la discipline vient de n'utiliser
QUE `build_monte_carlo_specification()` en pratique, jamais un constructeur d'objet inviolable.

**`n_simulations` n'est pas non plus laissé librement re-choisissable par l'appelant, pour fermer
le même canal résiduel** : plutôt qu'un paramètre du builder, `n_simulations` est une constante
module `MONTE_CARLO_DEFAULT_N_SIMULATIONS = 10 000` (Décision 4), fixée en interne comme
`monte_carlo_semantics_version` — changer le nombre de simulations pour espérer une distribution
plus favorable (`10 000` puis `10 001`, ...) exigerait de modifier le CODE (un changement traçable
en git), jamais un paramètre d'appel librement rejouable.

`ValueError` immédiat si `source_validation_run_id` est absent/vide, avant tout calcul — mirroring
exact du garde-fou déjà utilisé pour `dataset_snapshot_id` (`build_validation_run()`,
`validation_run.py`).

**Dérivation du flux aléatoire par méthode, mirroring le PRINCIPE (jamais littéralement le code) de
`walk_forward._derive_fold_seed()`** (ADR 0021 Décision 9, `hashlib.sha256`, jamais
`hash()`/`time.time()`/`random.randint()`) — **UN seul générateur seedé par méthode**, jamais un
générateur par simulation (correction de conception, revue architecture — voir aussi Décision 14) :

```
_MONTE_CARLO_SEED_DOMAIN_TAG = "mc-v1"
method_seed = int(sha256(f"{master_seed}:{method}:{_MONTE_CARLO_SEED_DOMAIN_TAG}").hexdigest(), 16)
rng = numpy.random.default_rng(method_seed)
```

`method` (`"sequence_risk"` ou `"sampling_uncertainty"`) fait partie du payload — garantit que les
deux méthodes utilisent des flux aléatoires totalement indépendants (jamais le même flux réutilisé
entre deux méthodes différentes). Ce générateur UNIQUE par méthode produit ENSUITE les
`n_simulations` tirages en un nombre réduit d'appels vectorisés (ex. `rng.permuted()`/
`rng.integers()` sur un tableau de forme `(n_simulations, n_trades)` en un seul appel, jamais une
ré-instanciation de `default_rng()` par simulation) — cohérent avec le budget de calcul de la
Décision 14. Pour `n_trades_observés! < n_simulations` (Décision 4), l'énumération exhaustive des
permutations (`itertools.permutations`) est un calcul PUREMENT DÉTERMINISTE, sans tirage aléatoire
ni consommation du générateur `rng`.

`SeedSequence`/`default_rng` de `numpy` acceptent nativement un entier non-signé arbitrairement
grand (jusqu'à l'ordre de `2**256` produit par `sha256`), aucune troncature nécessaire — vérifié
directement. **Précision correction (revue architecture indépendante)** : ce dépôt n'a, à ce jour,
AUCUN usage préexistant d'une graine dérivée par SHA-256 alimentant `numpy.random.default_rng()` —
le seul consommateur de graine dérivée existant (`optimizer.py::_run_stratified_sample()`) l'injecte
dans `random.Random()` (Mersenne Twister de la bibliothèque standard), jamais dans `numpy`. Cette
ADR introduit donc un PREMIER usage de ce type dans ce dépôt, pas un mirroring d'un précédent
`numpy` déjà existant — seul le PRINCIPE de dérivation (SHA-256, jamais `hash()`/`time.time()`) est
mirroré, jamais la consommation en aval. `numpy.random.default_rng()` retourne un `Generator`
(PCG64) à état strictement LOCAL (jamais l'état global historique `numpy.random.seed()`), donc sans
dépendance cachée entre appels/processus — sûr pour la reproductibilité visée.

**Reproductibilité exacte** : deux appels avec le même `source_validation_run_id`/mêmes trades
produisent des `MonteCarloEvidence` **bit-à-bit identiques** — propriété testée explicitement
(Décision 13).

## Décision 6 — Métriques strictement factuelles ; percentiles de drawdown en base « clôture de trade », jamais un jugement

Cohérent avec l'ADR 0021 Décision 13 (« `FoldResult`/`AggregateResult` ne portent que des faits
mesurés ») — `MonteCarloEvidence` ne porte QUE des statistiques descriptives de la distribution
obtenue, jamais un jugement :

- Pour `sequence_risk` : percentiles `p5`/`p25`/`p50`/`p75`/`p95` du **max drawdown en base
  clôture de trade** (`max_dd_trade_close_basis_pct`, voir définition ci-dessous) ET de la **plus
  longue série de pertes consécutives** sous permutation, sur les `n_simulations` permutations
  (`net_ret_pct` final identique à chaque permutation, donc non rapporté ici — voir Décision 2) —
  cette seconde distribution permet de comparer visuellement `observed_longest_losing_streak` à ce
  qu'un ré-ordonnancement aléatoire produirait, sans calculer ni rapporter aucune signification
  statistique formelle (Décision 3).
- Pour `sampling_uncertainty` : percentiles `p5`/`p25`/`p50`/`p75`/`p95` du **net_ret_pct final**
  ET du **max drawdown en base clôture de trade** sur les `n_simulations` tirages bootstrap.
- `observed_net_ret_pct`/`observed_max_dd_trade_close_basis_pct` : les valeurs RÉELLEMENT observées
  sur la séquence de trades originale (non rééchantillonnée) — permettent de situer l'observation
  réelle dans sa propre distribution simulée, un fait de référence, jamais un verdict.
- `observed_lag1_autocorrelation`/`observed_longest_losing_streak` (Décision 3) : faits
  descriptifs supplémentaires sur la séquence originale, jamais rééchantillonnés.

**Définition précise du drawdown mesuré, et sa limite structurelle assumée (correction du finding
BLOCKER B2, revue scientifique indépendante)** : reconstruit depuis la seule séquence de
`net_ret_pct` PAR TRADE (Décision 1), ce drawdown n'est observable QU'AUX POINTS DE CLÔTURE de
chaque trade — il **ignore structurellement l'excursion adverse intra-trade** (MAE, mouvement
défavorable pendant qu'une position reste ouverte). Il **sous-estime donc systématiquement** le
drawdown réellement vécu, et n'est **PAS directement comparable** au `max_dd_pct` produit par
`engine.py::run_backtest()` (calculé, lui, sur une courbe d'équité BARRE PAR BARRE — mark-to-market,
capturant l'excursion intra-trade ; `engine.py` lignes ~504-508, `dd_arr` dérivé de
`edf["capital"]`). Nom de champ délibérément explicite (`*_trade_close_basis_pct`, jamais
`*_max_dd_pct` seul) pour empêcher toute confusion silencieuse entre les deux grandeurs dans un
futur rapport `GATE V` — jamais deux chiffres homonymes mais divergents présentés côte à côte sans
distinction.

**`probability_of_ruin` — SUPPRIMÉE de cette ADR (correction du finding BLOCKER B1, revue
scientifique indépendante)** : sous chaînage MULTIPLICATIF des rendements (Décisions 1/2 — la
seule convention retenue par cette ADR, cohérente avec l'ADR 0021 Décision 15), l'équité chaînée ne
peut atteindre exactement zéro QUE si un trade individuel a `net_ret_pct <= -100 %` — et si un tel
trade existe dans l'échantillon, le produit s'annule **quel que soit l'ordre** (la multiplication
est commutative), rendant une "probabilité de ruine" par permutation triviale et non informative
(`{0, 1}` exactement, jamais une vraie probabilité) ; sous bootstrap, elle ne serait qu'une
fonction triviale du COMPTAGE de tels trades dans l'échantillon original, jamais une propriété de
la simulation elle-même. En pratique, un tel trade est structurellement absent (stops), donc cette
métrique vaudrait **systématiquement zéro** — lisible à tort comme "risque de ruine nul" par un
futur lecteur. **Redéfinir "ruine" sur un seuil de perte partielle (ex. -20 %) inventerait
exactement le type de seuil scientifique que cette ADR interdit** (Décision 12) — cette ADR renonce
donc à toute métrique de "probabilité de ruine" en V1 ; les percentiles de max drawdown (ci-dessus)
restent le signal de risque rapporté, déjà non dégénéré et sans seuil inventé.

**Aucun intervalle de confiance qualifié "acceptable"/"robuste" n'est produit** — ce jugement
resterait de la responsabilité exclusive d'une politique de verdict pré-enregistrée (Décision 12),
exactement comme pour Walk-Forward.

## Décision 7 — Comportement avec peu de trades ou zéro trade : jamais une erreur, une observation factuelle honnête

**Zéro trade en entrée** : rééchantillonner un ensemble vide est mathématiquement indéfini (pas
"zéro", réellement indéfini) — mirroring exact de la convention déjà établie
(`FoldResult.zero_trade_oos`/`AggregateResult`, ADR 0021) : `MonteCarloEvidence.zero_trade_input =
True`, TOUS les champs de percentiles/`observed_*` valent `None` — **jamais une exception, jamais
une valeur inventée** (`n_trades == 0` est une observation scientifique valide, pas une erreur
technique, même philosophie que le TEST à zéro trade du protocole Walk-Forward).

**Peu de trades (`n_trades` faible, ex. 1 à 9)** : jamais bloquant, jamais un seuil minimal inventé
pour refuser de calculer — mais `MonteCarloEvidence.n_input_trades` est TOUJOURS rapporté
explicitement (fait brut), permettant à un futur consommateur/politique de verdict de juger lui-même
la significativité statistique, jamais cette ADR à sa place. Cas particulier `n_trades == 1` : la
permutation n'a qu'1 seul ordre possible (`1! = 1`) — `sequence_risk` est alors calculée sur cette
unique permutation (`n_simulations` effectif = 1, jamais gonflé artificiellement), rapporté tel
quel ; le bootstrap avec remise, lui, reste bien défini (tire le même trade unique à chaque fois,
distribution dégénérée mais mathématiquement valide, jamais un cas d'erreur).

## Décision 8 — Persistance et fingerprint, mais AUCUN mécanisme de reprise incrémentale (proportionnalité au coût réel)

**Persistance** : structure additive sous `results/job_xxx/monte_carlo/`, mirroring la convention
déjà établie par l'ADR 0021 Décision 12 (`atomic_json_store.save_atomic()` pour tout fichier JSON,
jamais un `open()`/`json.dump()` direct) — `manifest.json` (fingerprint : `master_seed`,
`n_simulations`, méthodes, `source_validation_run_id`, `monte_carlo_semantics_version`,
`verdict_policy_id`) et `evidence.json` (`dataclasses.asdict()` de `MonteCarloEvidence`).

**Aucun mécanisme de reprise incrémentale (SKIP/REPLAY/REDO par simulation) — différence
DÉLIBÉRÉE avec Walk-Forward (ADR 0021 Décision 12), justifiée par un coût structurellement
différent** : contrairement à un fold Walk-Forward (une vraie recherche `Optimizer.run()`,
potentiellement longue, avec de vrais appels moteur par candidat), le Monte-Carlo V1 n'exécute
JAMAIS le moteur de backtest — c'est de l'arithmétique vectorisée `numpy` pure sur une séquence de
trades déjà en mémoire (voir Décision 14, budget de calcul estimé). Une interruption/reprise pour
une opération de l'ordre de la seconde à la minute serait une complexité non justifiée par le coût
réel (`YAGNI`, cohérent avec la discipline anti-sur-ingénierie déjà appliquée ailleurs dans ce
dépôt, ex. registre `_VALIDATION_TYPES` plutôt qu'un `ABC` pour un type unique). Le fingerprint
sert uniquement à détecter, À LA LECTURE d'une évidence déjà persistée, une incohérence de
version/paramètres — jamais à décider un skip/redo partiel.

## Décision 9 — Taxonomie d'erreurs explicite, fail-closed, mirroring la Décision 11 de l'ADR 0021

| Condition | Comportement |
|---|---|
| `source_validation_run_id` absent/vide | `ValueError` immédiat, avant tout calcul (Décision 5 — `master_seed` en dépend directement) |
| `n_simulations <= 0` | `ValueError` immédiat |
| `method` inconnu (hors `"sequence_risk"`/`"sampling_uncertainty"`) | `ValueError` immédiat, jamais une valeur par défaut silencieuse |
| `n_trades == 0` | **Jamais une erreur** — `MonteCarloEvidence.zero_trade_input=True` (Décision 7) |
| Relecture d'une évidence persistée sous une version de sémantique différente (`monte_carlo_semantics_version`) | Nouvelle exception `MonteCarloSemanticsMismatch(ValueError)`, mirroring exact de `WalkForwardSemanticsMismatch` — refuse plutôt que de mélanger silencieusement deux contrats |
| `verdict_policy_id` fourni mais aucune politique enregistrée | `UnknownVerdictPolicy` — **RÉUTILISE TELLE QUELLE** l'exception déjà définie dans `validation_run.py` (Slice 6, ADR 0021 Décision 13) plutôt qu'une classe dupliquée : même principe sous-jacent (aucune politique de seuils n'existe encore dans ce dépôt, toutes validations confondues), voir Décision 12 |

## Décision 10 — Impossibilité structurelle d'accéder à `FINAL_HOLDOUT`

Le Monte-Carlo V1 **ne connaît ni `engine.py`, ni `DatasetSplitPlan`, ni `FINAL_HOLDOUT`, ni
`nasdaq_3m.csv`** — son seul contrat d'entrée est une séquence de `net_ret_pct` déjà calculée par
un appelant (Décision 1). Il ne peut donc STRUCTURELLEMENT jamais déclencher un nouvel accès au
holdout (aucun `HoldoutAccessEvent` n'est ni consulté ni produit par ce module). **Précision
explicite pour éviter tout blanchiment d'accès** : si la séquence de trades fournie provient
historiquement d'un run `FINAL_HOLDOUT` (OOS), consommer ces trades ici ne constitue PAS un nouvel
accès (aucun nouveau backtest n'est exécuté, aucune nouvelle observation du holdout n'a lieu) —
mais rééchantillonner des trades issus du holdout PLUSIEURS FOIS avec des paramètres différents
dans le but de comparer des variantes de stratégie reviendrait à un tuning déguisé sur le holdout,
une responsabilité de l'APPELANT à ne jamais déléguer silencieusement à ce module (jamais vérifié
automatiquement ici, hors scope structurel de ce module qui n'a pas connaissance de la provenance
métier des trades).

## Décision 11 — `MonteCarloSpecification`/`MonteCarloEvidence`, nouveau `validation_type = "monte_carlo"`

Mirroring exact de `WalkForwardSpecification`/`WalkForwardEvidence` (ADR 0021 Décision 2/13),
ajoutés à `validation_run.py` (module leaf, aucun changement à `_VALIDATION_TYPES` au-delà d'une
nouvelle entrée additive — cohérent avec sa propre docstring : « étendre en ajoutant une entrée par
futur ticket, jamais en généralisant ce module en dict opaque ») :

```python
VALIDATION_TYPE_MONTE_CARLO = "monte_carlo"  # nom déjà utilisé par DOMAIN_MODEL.md, jamais inventé

@dataclass(frozen=True)
class PercentileDistributionSummary:
    p5: Optional[float]
    p25: Optional[float]
    p50: Optional[float]
    p75: Optional[float]
    p95: Optional[float]

@dataclass(frozen=True)
class MonteCarloSpecification:
    n_simulations: int
    master_seed: int  # champ ordinaire — voir builder ci-dessous pour la seule construction sanctionnée
    source_validation_run_id: str  # traçabilité ET source de dérivation de master_seed (Décision 5)
    source_trades_from_optimized_params: bool  # avertissement de biais de sélection, Décision 1
    monte_carlo_semantics_version: str
    verdict_policy_id: Optional[str] = None

def build_monte_carlo_specification(
    source_validation_run_id: str,
    source_trades_from_optimized_params: bool,
    verdict_policy_id: Optional[str] = None,
) -> MonteCarloSpecification:
    """SEULE construction sanctionnée (Décision 5) — dérive `master_seed` depuis
    `source_validation_run_id`, jamais un entier fourni librement par l'appelant.
    `n_simulations`/`monte_carlo_semantics_version` ne sont PAS des paramètres : toujours fixés en
    interne aux constantes module `MONTE_CARLO_DEFAULT_N_SIMULATIONS`/`MONTE_CARLO_SEMANTICS_VERSION`
    courantes, jamais choisis par l'appelant (empêche un caller de rejouer avec un `n_simulations`
    différent en quête d'un résultat plus favorable, ou de silencieusement dater une spécification
    sous une version différente de celle réellement en vigueur). Mirroring du style déjà établi
    (`build_walk_forward_specification()`, `build_oos_validation_evidence()`) : valide puis
    construit la dataclass frozen, jamais un champ auto-calculé à l'intérieur de la dataclass
    elle-même (pattern absent d'ailleurs dans ce dépôt)."""
    ...  # ValueError si source_validation_run_id vide ; calcule master_seed (Décision 5)

@dataclass(frozen=True)
class MonteCarloEvidence:
    n_input_trades: int
    zero_trade_input: bool
    observed_net_ret_pct: Optional[float]
    observed_max_dd_trade_close_basis_pct: Optional[float]
    observed_lag1_autocorrelation: Optional[float]
    observed_longest_losing_streak: Optional[int]
    sequence_risk_max_dd_trade_close_basis_pct: Optional[PercentileDistributionSummary]
    # Interpolation "lower" (jamais "linear", le défaut numpy) pour ce champ précisément : une série
    # de pertes est un COMPTEUR entier, un percentile interpolé linéairement produirait une valeur
    # non entière ("p5 = 2.3 séries") non interprétable — chaque champ de ce PercentileDistributionSummary
    # reste donc une VALEUR ENTIÈRE RÉELLEMENT OBSERVÉE dans l'échantillon simulé, jamais interpolée.
    sequence_risk_longest_losing_streak: Optional[PercentileDistributionSummary]
    sampling_uncertainty_net_ret_pct: Optional[PercentileDistributionSummary]
    sampling_uncertainty_max_dd_trade_close_basis_pct: Optional[PercentileDistributionSummary]
    execution_status: str
    scientific_verdict: str
    verdict_reasons: Tuple[str, ...]

# _VALIDATION_TYPES est un dict LITTÉRAL au niveau module (validation_run.py, lignes ~412-415),
# jamais une affectation a posteriori par indice — la mission d'implémentation ajoute une TROISIÈME
# ligne au littéral existant, exactement comme les deux entrées "oos"/"walk_forward" déjà présentes
# (correction de forme, revue architecture indépendante) :
#
# _VALIDATION_TYPES: Dict[str, Tuple[type, type]] = {
#     VALIDATION_TYPE_OOS: (OosValidationSpecification, OosValidationEvidence),
#     VALIDATION_TYPE_WALK_FORWARD: (WalkForwardSpecification, WalkForwardEvidence),
#     VALIDATION_TYPE_MONTE_CARLO: (MonteCarloSpecification, MonteCarloEvidence),  # <- nouvelle ligne
# }
```

`execution_status` ∈ {`"completed"`} uniquement en V1 — contrairement à Walk-Forward, aucune
notion d'interruption coopérative n'existe ici (Décision 8 : pas de reprise, calcul trop court pour
justifier une barrière d'arrêt inter-simulation).

**Placement du code exécutable** — nouveau module top-level `monte_carlo.py` (jamais dans
`validation_run.py`, qui reste un leaf sans algorithme ; jamais dans `walk_forward.py`, sans
rapport de domaine) : `run_monte_carlo_simulation(trades: Tuple[float, ...], spec:
MonteCarloSpecification) -> MonteCarloEvidence`, fonction pure, aucun import
`engine.py`/`optimizer.py`/`dataset_split.py`/`walk_forward.py` — preuve structurelle de la
Décision 10.

## Décision 12 — Séparation stricte preuve factuelle / verdict scientifique (mirroring exact de la Décision 13 de l'ADR 0021)

`scientific_verdict` reste **TOUJOURS `"INCONCLUSIVE"`** sans `verdict_policy_id` enregistré — même
philosophie, même mécanisme, **même exception `UnknownVerdictPolicy`** que Walk-Forward (Slice 6) :
aucune politique concrète de seuils PASS/FAIL n'existe dans ce dépôt à ce jour, cette ADR n'en
invente aucune. `verdict_policy_id` fourni sans politique réellement enregistrée -> `UnknownVerdictPolicy`
levée, jamais un verdict deviné ni un repli silencieux. Cette ADR ne définit AUCUN critère
« intervalle de confiance acceptable » (contrairement à la suggestion non contraignante de
`docs/architecture/TEST_AND_VALIDATION_ARCHITECTURE.md` §5, point 5 — explicitement non actée ici,
resterait une décision produit/scientifique séparée et future).

**Discipline de pré-enregistrement, pour une future politique réelle (correction du finding MAJOR
M5, revue scientifique indépendante)** : `UnknownVerdictPolicy` empêche un verdict inventé, mais
n'empêche PAS, à elle seule, qu'une politique soit RÉDIGÉE après avoir déjà lu les percentiles d'un
run précis (choisir des seuils a posteriori pour faire coller un verdict favorable). **Cette ADR
n'implémente aucun mécanisme technique pour cela en V1** (aucune politique n'existe encore, la
question ne se pose donc pas concrètement aujourd'hui) — mais consigne explicitement, pour une
future ADR qui définirait un vrai registre de politiques : toute politique référencée par
`verdict_policy_id` doit être définie et committée (git) **avant** le run auquel elle s'applique
(ex. liée à un hash de contenu + un commit antérieur à `completed_at` de la `ValidationRun`),
jamais rédigée ou modifiée après observation du résultat qu'elle doit juger.

## Décision 13 — Matrice TDD

| Cas | Test |
|---|---|
| Déterminisme bit-à-bit | Deux appels, même `source_validation_run_id`/mêmes trades -> `MonteCarloEvidence` strictement égale |
| `master_seed` dérivé, jamais libre | `build_monte_carlo_specification()` avec le même `source_validation_run_id` produit TOUJOURS le même `master_seed` ; deux `source_validation_run_id` différents produisent des `master_seed` différents (anti "seed shopping", M4) |
| Graines indépendantes entre méthodes | `sequence_risk` et `sampling_uncertainty` ne partagent jamais un flux aléatoire identique (vérifié par un mock/spy sur `numpy.random.default_rng`) |
| `default_rng` instancié au plus 2 fois | Spy sur `numpy.random.default_rng` : exactement 1 appel par méthode utilisant réellement le tirage aléatoire (jamais 1 par simulation) — preuve du tirage vectorisé (Décision 5/14) |
| Chaque ligne du tirage vectorisé est une permutation/un tirage INDÉPENDANT (finding architecture, seconde revue) | Sur `n_simulations` petit (ex. 20) et `n_trades` non trivial, vérifier qu'aucune paire de lignes du tableau `(n_simulations, n_trades)` n'est identique par construction/bug d'axe (`axis=` erroné sur `rng.permuted()`/`rng.integers()`), et que chaque ligne contient bien une permutation valide (mêmes éléments, ordre différent) pour `sequence_risk` |
| Permutation préserve le rendement final | `net_ret_pct` final identique à travers toutes les permutations d'un même jeu de trades (propriété mathématique du produit commutatif, testée) |
| Bootstrap fait varier le rendement final | Sur un jeu de trades non trivial, `sampling_uncertainty_net_ret_pct.p5 != p95` |
| Drawdown trade-close jamais confondu avec le moteur | Un jeu de trades avec MAE intra-trade connue (fixture construite à la main) confirme que `observed_max_dd_trade_close_basis_pct` peut être strictement inférieur à un `max_dd_pct` de référence calculé barre par barre — jamais assertés égaux |
| Biais i.i.d. rapporté en fait, jamais en seuil | `observed_lag1_autocorrelation`/`observed_longest_losing_streak` calculés correctement sur un jeu de trades synthétique à corrélation connue ; aucun champ "significatif"/"anormal" n'existe dans `MonteCarloEvidence` |
| Cohérence avec `AggregateResult` (source Walk-Forward) | Sur la MÊME séquence ordonnée de `net_ret_pct` que celle utilisée par un `AggregateResult` réel (ADR 0021 Décision 15, chaînage multiplicatif par composition chronologique), `observed_net_ret_pct` recalculé par Monte-Carlo (même formule de chaînage, Décision 1/2) est **strictement égal** (tolérance flottante) à `AggregateResult.oos_net_return_pct` — assertion ferme, jamais une simple absence d'erreur |
| `n_trades == 0` | `zero_trade_input=True`, tous les champs numériques `None`, aucune exception |
| `n_trades == 1` | `sequence_risk` sur exactement 1 permutation, aucune erreur |
| `n_trades! < n_simulations` | Énumération exhaustive des permutations, percentiles rapportés EXACTS (pas estimés), jamais un tirage aléatoire avec répétitions inutiles — testé pour au moins deux valeurs de `n_simulations` différentes (preuve que le critère est relatif, pas un `7` câblé en dur) |
| `source_validation_run_id` vide | `ValueError` avant tout calcul |
| `n_simulations <= 0` | `ValueError` |
| `method` invalide | `ValueError` |
| `verdict_policy_id=None` | `scientific_verdict == "INCONCLUSIVE"` |
| `verdict_policy_id` fourni | `UnknownVerdictPolicy` levée (réutilisation directe de la classe `validation_run.UnknownVerdictPolicy`, jamais une classe dupliquée) |
| Round-trip disque | `MonteCarloEvidence` -> `build_validation_run()` -> `save_validation_run()` -> `load_validation_run()` préserve tous les champs |
| Fingerprint | Relecture sous une `monte_carlo_semantics_version` différente lève `MonteCarloSemanticsMismatch` |
| Aucune dépendance moteur | Test d'import statique : `monte_carlo.py` n'importe ni `engine`, ni `optimizer`, ni `dataset_split`, ni `walk_forward` |
| Aucun accès holdout | `monte_carlo.py`/ses tests ne référencent jamais `FINAL_HOLDOUT`/`HoldoutAccessEvent` |

## Décision 14 — Budget de calcul estimé pour une exécution réelle

**Coût négligeable, purement CPU, aucun appel externe** : `n_simulations=10 000` par méthode
(Décision 4), chaque simulation = un ré-échantillonnage vectorisé `numpy` d'un tableau de quelques
dizaines à quelques centaines de `float` (nombre de trades observés dans un run OOS/Walk-Forward
réel de ce dépôt) plus un chaînage multiplicatif cumulatif (Décision 1/2) — de l'ordre de
**quelques secondes à moins d'une
minute** au total sur un poste de travail standard, sans GPU, sans appel réseau/API/LLM, sans
ré-exécution du moteur de backtest. Ne consomme AUCUN budget Claude/crédit d'API — c'est un calcul
local pur, contrairement à une véritable campagne Walk-Forward (recherche `Optimizer.run()` réelle
par fold).

## Conséquences

- **`AF-V-03` reste `implementation: NOT STARTED`** — cette ADR ne modifie aucun code.
- Remplace explicitement l'esquisse non contraignante de
  `docs/architecture/TEST_AND_VALIDATION_ARCHITECTURE.md` §2/§3 (perturbations d'exécution) par un
  protocole de rééchantillonnage statistique — cohérent avec les données réellement disponibles
  aujourd'hui, jamais un moteur d'exécution stochastique inventé pour l'occasion.
- **Nouvelle dépendance d'implémentation identifiée** : le contrat d'entrée (Décision 1) suppose un
  appelant capable de fournir une séquence de trades individuels déjà observés — `OosValidationEvidence`
  ne les porte pas aujourd'hui (agrégats seulement) ; un futur appelant Monte-Carlo côté OOS devra
  soit consommer un `trades_df` produit directement par `run_backtest_fn` (jamais relu depuis
  `OosValidationEvidence`), soit cette limitation reste explicite et documentée. Côté Walk-Forward,
  les CSV `oos_trades.csv` par fold (Slice 4, ADR 0021 Décision 12) fournissent déjà cette donnée
  réelle.
- **Points restant à valider explicitement par l'utilisateur avant implémentation, si un désaccord
  matériel apparaît** : aucun identifié à ce stade — chaque choix ci-dessus est justifié par un
  fait déjà vérifié dans le dépôt (conventions existantes, contraintes du moteur réel) plutôt que
  par une préférence esthétique ; voir le rapport de revue joint pour confirmation indépendante
  avant de lever ce statut `Proposé`.
- **Amendement post-merge (2026-09-22, revue architecture d'ADR 0023)** : `MonteCarloDistributionSummary`
  a été renommée `PercentileDistributionSummary` (nom, jamais la forme/les champs) — la Décision 6
  de l'ADR 0023 (Parameter Stability) en devient le second consommateur, et ce dépôt applique déjà
  ailleurs (ex. `*_trade_close_basis_pct` vs `*_max_dd_pct`, Décision 6 ci-dessus) la discipline de
  ne jamais laisser un nom de type suggérer une origine unique qu'il n'a plus. Renommage mécanique
  appliqué au code réel déjà mergé (`validation_run.py`, `monte_carlo.py`, leurs tests), suite
  complète revérifiée verte avant re-intégration.
