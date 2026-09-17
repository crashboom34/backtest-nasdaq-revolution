# Vision produit AlphaForge V2 — Strategy Factory

> **Nature de ce document : direction produit acceptée, PAS un plan d'implémentation.** Rien ici
> n'est codé, testé ou planifié dans l'ordre. Chaque capacité porte un statut explicite (§0) et un
> renvoi vers le **track**/**gate** qui la gouverne déjà dans `docs/roadmap/MASTER_ROADMAP.md`
> (Track `DATA`/`R`/`F`/`V`/`S`/`E-FAST`/`E-PRECISION`/`D`/`P`/`U`/`DSL`/`O`/`INFRA`, gates
> `GATE DATA`/`GATE V`/`GATE D`/`GATE PRECISION`/`GATE CHAMPION`/`GATE PORTFOLIO`). **Ce document
> n'invente aucun nouveau track, aucune nouvelle gate, aucun nouvel ordre de dépendance** — il
> détaille, sous les tracks déjà posés, des sous-fonctionnalités que `MASTER_ROADMAP.md` ne
> descendait pas encore à ce niveau de granularité.
>
> Produit lors de la mission de synchronisation produit/UX/roadmap du 2026-09-16 (documentaire
> uniquement — voir le rapport de mission pour la liste des fichiers touchés). Checkpoint
> scientifique au moment de la rédaction : `AF-V-02` (Walk-Forward) **implémentation IN PROGRESS
> (Slice 1, non committée)**, `GATE V` **NON PASSÉE** — voir `AI_HANDOFF.md` pour le détail
> technique. Ce document ne modifie ni ne présume ce statut.

## 0. Vocabulaire de statut (obligatoire, utilisé strictement dans tout ce document)

| Statut | Signification |
|---|---|
| `IMPLEMENTED` | Code réellement présent dans le dépôt |
| `TESTED` | Couvert par une suite de tests réellement exécutée |
| `DOCUMENTED` | Décrit dans la documentation, sans code associé |
| `ACCEPTED` | Direction produit validée par l'utilisateur — pas encore de conception détaillée |
| `PROPOSED` | Suggéré, pas encore validé comme direction produit définitive |
| `PLANNED` | Accepté ET son track/gate d'entrée est déjà identifié dans `MASTER_ROADMAP.md` |
| `DEFERRED` | Volontairement reporté — ne doit pas être commencé avant que ses prérequis (gates) soient passés |
| `READY FOR DESIGN` | Prérequis scientifiques/architecturaux satisfaits, conception peut commencer |
| `READY FOR IMPLEMENTATION` | Conception figée (ADR/spec), implémentation peut commencer |
| `DONE` | Implémenté, testé, revu, aucune dette connue |

**Règle stricte de ce document** : sauf preuve contraire explicitement citée (fichier réel,
commit, test), toute capacité listée ci-dessous porte le statut composite
**`ACCEPTED PRODUCT DIRECTION / IMPLEMENTATION DEFERRED`** — jamais `IMPLEMENTED`, jamais `DONE`,
jamais `READY FOR IMPLEMENTATION`, uniquement parce qu'elle est décrite ici.

## 1. Principe directeur (hérité, pas réinventé)

`MASTER_ROADMAP.md` §1 fixe déjà, de façon non négociable :

```text
FIABILITÉ → REPRODUCTIBILITÉ → SÉCURITÉ → ARCHITECTURE → VALIDATION SCIENTIFIQUE
→ PERFORMANCE → STRATEGY DISCOVERY → PORTFOLIO → ERGONOMIE → FONCTIONNALITÉS
```

Ce document reformule ce principe en langage produit, sans le changer :

> **La puissance de calcul sert à explorer. La validation scientifique sert à éliminer.**
> Une stratégie au meilleur PnL historique n'est ni automatiquement la meilleure stratégie, ni une
> stratégie robuste — `GATE V` existe précisément pour empêcher cette confusion.

Architecture produit cible (résume, sans les remplacer, les tracks déjà posés) :

```text
DONNÉES (DATA) → CRÉATION/DISCOVERY (F, S, D, DSL) → BACKTEST (E-PRECISION/CURRENT REFERENCE ENGINE)
→ OPTIMISATION (Optimizer existant) → VALIDATION SCIENTIFIQUE (V) → CHAMPIONS (GATE CHAMPION)
→ PORTEFEUILLES (P) → EXPORT/ÉQUIVALENCE PRT (nouveau, voir §9) → PAPER/FORWARD (nouveau, voir §10)
→ STRATEGY HEALTH (§15 DOMAIN_MODEL.md, FUTURE)
```

**AlphaForge V2 est une Strategy Factory, pas un simple backtester** — mais rester générique
(§2) ne change ni ne relâche `GATE V`/`GATE D` : une usine qui produit plus de candidats n'a de
valeur que si l'élimination scientifique en aval reste intacte.

## 2. Généricité multi-actifs / multi-timeframes / multi-stratégies

**Statut : `ACCEPTED PRODUCT DIRECTION / IMPLEMENTATION DEFERRED`.**

Perfect Revolution reste la **stratégie étalon** de validation (référence historique 114 trades,
`net_ret_pct` connu — voir ADR 0018/0019/0020/0021), **jamais la limite produit**. Cible : l'
utilisateur choisit librement actif, timeframe, période, session, stratégie, paramètres, coûts,
modèle broker, risque, capital, méthode de recherche.

Deux notions de multi-timeframe déjà distinguées par `DOMAIN_MODEL.md` §16 (**ne pas les
confondre**, réutilisées ici telles quelles) :
- **(A) Test multi-timeframe** — la même `StrategyDefinition` évaluée séparément sur plusieurs
  timeframes → dimension du `ResearchScope` (Track `S`).
- **(B) Stratégie intrinsèquement multi-timeframe** — une seule `StrategyDefinition` combinant
  plusieurs timeframes dans sa propre logique → propriété interne à la `StrategyDefinition`
  (Track `F`), jamais une dimension de `ResearchScope`.

Rattachement : Track `DATA` (actifs/instruments), Track `F` (stratégies multiples), Track `S`
(dimension timeframe/période/session du `ResearchScope`). Aucun nouveau track nécessaire.

## 3. Matrice Actif × Timeframe

**Statut : `ACCEPTED / DEFERRED`.**

Tester automatiquement une stratégie sur une matrice Actifs × Timeframes (ex. NASDAQ/DAX/S&P500/
Gold × 1m/3m/5m/15m/H1) pour vérifier la généralisation, détecter les dépendances trop
spécifiques, comparer la robustesse entre marchés/UT. C'est une **extension du `ResearchScope`**
(Track `S`, dimension (A) du §16 `DOMAIN_MODEL.md` généralisée à plusieurs actifs simultanément),
consommée en aval par `V` (chaque cellule de la matrice reste soumise à `GATE V` indépendamment —
une matrice ne doit jamais devenir un moyen de contourner la validation scientifique en la diluant
sur davantage de cellules).

## 4. Univers d'indicateurs/features (Feature Registry)

**Statut : `ACCEPTED / DEFERRED`.**

Registre pouvant croître vers des centaines puis milliers d'indicateurs/features/transformations
(EMA/SMA, RSI, MACD, ATR, ADX, Bollinger, Donchian, Stochastique, CCI, ROC, momentum, volatilité,
volume, VWAP, z-score, percentiles, statistiques roulantes, transformations mathématiques,
distance prix/moyenne, pente, accélération, breakout, sessions, calendrier, régime, features
multi-timeframes). Chaque feature : **déterministe, versionnée, testable, reproductible**.

**Rattachement direct : Track `F` (Strategy Knowledge / Registries), `DOMAIN_MODEL.md` §3-4
(Knowledge Base, Registries)** — ce track existe déjà, `PROPOSED`, additif à l'existant ; ce
document ne fait qu'y verser le contenu concret attendu du futur registre. **Ne pas importer
maintenant des milliers d'indicateurs — préparer seulement l'architecture** (registre + contrat
déterministe/versionné) le moment venu.

## 5. Génération automatique de stratégies (Combination Engine)

**Statut : `ACCEPTED / DEFERRED`.**

Génération de candidats à partir d'indicateurs/features/règles/transformations/paramètres/
horaires/filtres/stops/targets/break-even/modèles de sortie (ex. `EMA rapide > EMA lente ET RSI <
seuil ET breakout N périodes ET volatilité > seuil` puis `Stop ATR×X / Target ATR×Y`). **Jamais un
brute-force naïf sur toutes les combinaisons possibles** — voir §6 (contrôle combinatoire).

**Rattachement : Track `D` (Strategy Discovery, `DOMAIN_MODEL.md` §5 origine "générée", §8
`SearchMethod`, §9 `CandidateStrategy`)**, déjà `PROPOSED`, déjà explicitement **algorithmique,
jamais IA générative autonome** (différée par décision antérieure, `MASTER_ROADMAP.md` §2) —
confirmé, pas réouvert ici. **`GATE V` reste l'entrée obligatoire de `D`** (`MASTER_ROADMAP.md`
§4) : aucune génération automatique de candidats à grande échelle avant que `AF-V-02`→`AF-V-05`
(OOS/WalkForward/MonteCarlo/ParameterStability) produisent tous une preuve réelle.

## 6. Contrôle de l'explosion combinatoire

**Statut : `ACCEPTED` (principe), `DEFERRED` (mécanismes).**

Obligatoire, pas optionnel, pour toute Strategy Factory réelle : univers d'indicateurs autorisé
par expérience, limites de complexité, nombre maximal de conditions, grammaire de règles valides,
search spaces explicites, élimination précoce, pénalisation de complexité, **multiple-testing
control**, budgets de calcul, seeds reproductibles — objectif : empêcher qu'un grand univers de
features devienne une machine à overfitting. Rattachement : Track `D` + Track `S` (search space),
et **directement lié au futur travail de multiple-testing déjà anticipé par
`docs/adr/0021-walk-forward-rolling-calendar-v1.md` Décision 17** (search space hash, candidats
évalués/uniques/éligibles conservés par fold — cette infrastructure de traçabilité, une fois
Walk-Forward implémenté, sert directement de fondation au contrôle combinatoire ici visé).

## 7. Méthodes de Discovery

**Statut : `ACCEPTED / DEFERRED`.** Random Search, Grid Search (quand pertinent), Genetic/
Evolutionary, Bayesian Optimization, CMA-ES, autres méthodes validées ultérieurement — toutes
**versionnées et reproductibles** (mirroring direct du contrat seed déjà figé dans ADR 0021
Décision 9 pour Walk-Forward : `fold_seed` dérivé d'un `master_seed`, jamais `time.time()`/
`random.randint()`/`hash()`). Rattachement : Track `D`, sous-composant `SearchMethod`
(`DOMAIN_MODEL.md` §8), déjà `PROPOSED`.

## 8. Optimisation multi-objectifs et frontière de Pareto

**Statut : `ACCEPTED / DEFERRED`.** Ne jamais sélectionner automatiquement sur le seul profit —
rendement, drawdown, Sharpe, Sortino, stabilité, nombre de trades, régularité, robustesse,
complexité, exposition, éventuellement coûts/capacité. Visualiser plusieurs compromis (frontière
de Pareto) sans imposer artificiellement un unique « meilleur candidat ». Rattachement : Track `D`
(sélection des candidats) et Track `V` (les objectifs de robustesse/stabilité recoupent
directement `ParameterStability`, `AF-V-04`, déjà dans le scope `GATE V`) — **aucun nouveau
concept de domaine requis**, seulement une future politique de scoring multi-critères sur des
preuves déjà prévues par `V`.

## 9. Analyse par régimes de marché

**Statut : `ACCEPTED / DEFERRED`.** Comprendre dans quelles conditions (bull/bear/range/tendance/
volatilité forte ou faible/sessions/autres régimes déterministes) une stratégie fonctionne ou
échoue. Rattachement : recoupe directement `DOMAIN_MODEL.md` §15 (`StrategyHealth`, `FUTURE` —
« sensibilité au régime de marché » y est déjà citée comme signal de dérive) et alimente Track `V`
(diagnostics secondaires, jamais un critère `GATE V` supplémentaire non prévu par l'ADR de
validation concerné).

## 10. Analyse avancée des trades

**Statut : `ACCEPTED / DEFERRED`.** MFE/MAE, durée, séquences gains/pertes, distribution,
heure/jour/session, contribution au PnL, excursions favorables/adverses, comportement avant
sortie — génèrent des **hypothèses**, jamais une preuve indépendante si elles réutilisent les
mêmes données pour modifier PUIS "confirmer" une stratégie (règle explicite, à respecter
strictement — c'est exactement la discipline anti-Search-History-Leakage déjà actée pour
`FINAL_HOLDOUT`, `DOMAIN_MODEL.md` §12). Rattachement : extension de `job_store.py`/
`report_generator` existants (Track `U` pour l'affichage), aucun nouveau track.

## 11. Strategy Genealogy (filiation entre versions)

**Statut : `ACCEPTED / DEFERRED` — concept de domaine nouveau, pas encore dans `DOMAIN_MODEL.md`.**
Conserver la filiation entre versions/variantes (ex. `V1 → V2 filtre tendance → V3 nouveau stop →
V3.1 session différente`) pour l'audit, la compréhension, éviter de perdre l'historique
intellectuel. **Une future session `/domain-modeling` devra formellement définir ce concept**
(relation à `StrategyDefinition`, `DOMAIN_MODEL.md` §5) avant toute implémentation — non fait ici
(cette mission ne modifie aucun contrat de domaine). Rattachement provisoire : Track `F`.

## 12. Conservation des échecs (Rejected Strategy History)

**Statut : `ACCEPTED / DEFERRED` — concept de domaine nouveau.** Historique des stratégies
rejetées (FAIL OOS/Walk-Forward/Monte-Carlo, overfitting paramètres, trop corrélé à un Champion,
données insuffisantes) pour ne pas répéter des expériences déjà invalidées. Recoupe directement le
principe déjà établi pour `HoldoutAccessEvent`/`ValidationRun` (**preuve factuelle jamais
supprimée, `DOMAIN_MODEL.md` §12/§18**) — même discipline d'append-only, étendue aux échecs de
Discovery. Rattachement provisoire : Track `D` + Track `V` (source des `ValidationEvidence`
négatives). Nécessite une future session `/domain-modeling` pour le contrat exact.

## 13. Détection de stratégies trop similaires

**Statut : `ACCEPTED / DEFERRED`.** Corrélation des rendements/trades/drawdowns/périodes
d'exposition/facteurs-régimes — éviter de compter comme « diversification » plusieurs stratégies
reposant sur la même source de rendement. Rattachement : Track `P` (Portfolio), prérequis direct
de `GATE PORTFOLIO` (`MASTER_ROADMAP.md` §4 : au moins 2 `StrategyDefinition` ayant chacune
franchi `GATE CHAMPION` — la détection de similarité est un raffinement de cette condition, pas
une nouvelle gate).

## 14. Recherche de diversification

**Statut : `ACCEPTED / DEFERRED`.** Rechercher des stratégies complémentaires à une stratégie/un
portefeuille existant (faible corrélation, autres actifs/horaires/régimes/drawdowns/logiques).
Rattachement : Track `P` + Track `D` (le moteur de génération de candidats, §5, devient ici une
recherche guidée par un objectif de complémentarité plutôt que de performance seule) — aucun
nouveau track.

## 15. Portfolio Engine

**Statut : `PLANNED / DEFERRED`** (le plus avancé de cette liste : track et gate déjà nommés).
Allocation, exposition, diversification, corrélations, drawdown portefeuille, concentration,
Portfolio Walk-Forward, Portfolio Monte-Carlo. **Déjà `DOMAIN_MODEL.md` §14 (`Portfolio`,
`Allocation`, `Exposure`, `PortfolioRun`, tous `PROPOSED`)**, Track `P`, **`GATE PORTFOLIO`** déjà
définie (`MASTER_ROADMAP.md` §4). Ce document n'ajoute rien de nouveau ici, seulement la confirmation
que Portfolio Walk-Forward/Monte-Carlo dépendent des mêmes moteurs `V` (une fois `AF-V-02`/`AF-V-03`
implémentés) — pas une nouvelle mécanique de validation séparée.

## 16. Replay de trade

**Statut : `ACCEPTED / DEFERRED`.** Rejouer un trade/une période bar-après-bar (signaux, état de
stratégie, entrée, stop, BE, sortie) pour compréhension, debugging, pédagogie, audit moteur.
Rattachement : Track `U` (interface) + `CURRENT REFERENCE ENGINE`/`engine.py` (source des données
de replay, déjà `IMPLEMENTED`/`TESTED` — le replay ne modifie jamais le moteur, il rejoue une
trace déjà produite).

## 17. Audit automatique d'un backtest

**Statut : `ACCEPTED / DEFERRED`.** Vérifier dataset/version/trous/timezone/session/warmup/State
Readiness/leakage/lookahead/coûts/boundaries/broker model/nombre de trades/reproductibilité/
validation scientifique exécutée ou non. **Konsolide exactement les contrats déjà posés et testés
séparément** (Dette A/B warmup — ADR 0019, Dette B boundaries — ADR 0018, State Readiness — ADR
0020, Walk-Forward — ADR 0021) **en une seule checklist d'audit UI**, sans inventer de nouveau
critère scientifique. Rattachement : Track `U` (présentation) — aucune nouvelle logique de
validation, uniquement l'agrégation lisible de preuves déjà produites par `V`.

## 18. Budget de calcul

**Statut : `ACCEPTED / DEFERRED`.** Estimer avant une grosse expérience : nombre de backtests,
temps estimé, CPU, RAM, machine, coût cloud — local/cloud/planification/arrêt automatique compute
éphémère. Rattachement : Track `INFRA` (OCI/staging, déjà scope de `PH0-OCI-02`→`10`) + Track `U`
pour l'affichage de l'estimation avant lancement.

## 19. Early stopping / pruning

**Statut : `ACCEPTED / DEFERRED`.** Éliminer tôt les candidats manifestement incompatibles avec
les critères durs (drawdown excessif, trades insuffisants, métriques catastrophiques, contraintes
dures violées) — **règles déterministes, auditables, ne doivent jamais biaiser silencieusement la
validation** (même discipline que le principe déjà établi pour `NoEligibleTrainCandidate` dans
l'ADR 0021 : un candidat filtré au TRAIN reste un fait auditable, jamais une élimination
silencieuse). Rattachement : Track `D` + Track `S` (search space), directement lié à §6 ci-dessus.

## 20. Construction de stratégies sans code

**Statut : `ACCEPTED / DEFERRED`.** Éditeur de règles visuel (`SI... ET... OU... ALORS...`) avec
indicateurs/comparateurs/sessions/stops/targets/sizing, produisant **un contrat déterministe et
versionné** — c'est-à-dire, in fine, une `StrategyDefinition` normale (`DOMAIN_MODEL.md` §5),
juste produite par un éditeur visuel plutôt qu'écrite à la main ou générée par `D`. Rattachement :
Track `DSL` (Strategy Authoring, **`DECISION PENDING`, ADR 0014** — la question Python vs DSL
n'est PAS tranchée par ce document, elle reste ouverte exactement comme avant) + Track `U`.

## 21. ProRealTime / ProOrder (export et équivalence PRT)

**Statut : `PLANNED / DEFERRED` — concept nouveau, pas encore dans `DOMAIN_MODEL.md`.** Après
qualification Champion : vérifier compatibilité (compatible / compatible avec adaptation / non
compatible), puis éventuellement génération ProOrder et comparaison AlphaForge ↔ PRT (timestamps,
signaux, entrées/sorties, stops, targets, sessions, trades, PnL). **Dépendance explicite,
cohérente avec la roadmap existante** : ce chantier ne peut être qu'en aval de `GATE CHAMPION`
(`MASTER_ROADMAP.md` §4) — jamais avant qu'une stratégie ait réellement franchi la validation
scientifique complète. Rattachement provisoire : nouveau sous-composant de Track `E-PRECISION`
(comparaison différentielle moteur ↔ PRT, même famille de test que `GATE PRECISION` — conformance
contre une référence externe plutôt qu'interne) ; **une future session `/domain-modeling` devra
statuer précisément sur ce rattachement**, non fait ici.

## 22. Paper / Forward testing

**Statut : `PLANNED / DEFERRED`.** Même un Champion n'est pas immédiatement exploitable en réel.
Pipeline cible : `DISCOVERY → OOS/WALK-FORWARD → validations complémentaires → FINAL_HOLDOUT →
CHAMPION → PAPER/FORWARD → surveillance`. **Aucun ordre IG live** — règle absolue déjà appliquée
partout ailleurs dans ce dépôt (connecteur IG strictement lecture seule, démo uniquement, voir
`CONTEXT.md`), confirmée ici sans exception. Rattachement : en aval de `GATE CHAMPION`, avant
`StrategyHealth` (`DOMAIN_MODEL.md` §15) dans le pipeline produit — track dédié non encore nommé
dans `MASTER_ROADMAP.md`, à créer lors d'une future révision de roadmap quand ce chantier
deviendra réellement prioritaire (pas ici).

## 23. Strategy Health

**Statut : `PROPOSED / DEFERRED`** (déjà nommé et distingué dans `DOMAIN_MODEL.md` §15, statut
`FUTURE`). Surveiller l'écart entre comportement historique et forward/paper (résultats récents,
expectancy, drawdown, fréquence, régime). États `NORMAL`/`WATCH`/`DEGRADED`/`RETIRED`. **Les
seuils devront être spécifiés scientifiquement avant toute implémentation** — explicitement pas
fait ici, pas un sujet documentaire mais une future conception à part entière, dépendant de
Champions opérationnels (`DOMAIN_MODEL.md` §15, déjà écrit ainsi).

## 24. Assistant de lecture (pédagogie automatisée)

**Statut : `ACCEPTED / DEFERRED`.** Synthèse pédagogique basée sur des règles/métriques
**réellement disponibles** — jamais un verdict scientifique inventé par un LLM. Ce principe est
absolu et rejoint directement la discipline de transparence déjà pratiquée dans les rapports de
mission de ce dépôt (ne jamais déclarer un skill/une preuve utilisée si elle ne l'a pas été). Voir
`docs/ux/UX_UI_PRODUCT_DIRECTION.md` §7 pour le détail UX de ce pattern.

## Récapitulatif des statuts

| # | Capacité | Statut | Track(s) |
|---|---|---|---|
| 2 | Généricité multi-actifs/TF/stratégies | ACCEPTED / DEFERRED | DATA, F, S |
| 3 | Matrice Actif × Timeframe | ACCEPTED / DEFERRED | S |
| 4 | Feature Registry | ACCEPTED / DEFERRED | F |
| 5 | Génération automatique de stratégies | ACCEPTED / DEFERRED | D (derrière GATE V) |
| 6 | Contrôle explosion combinatoire | ACCEPTED / DEFERRED | D, S |
| 7 | Méthodes de Discovery | ACCEPTED / DEFERRED | D |
| 8 | Multi-objectifs / Pareto | ACCEPTED / DEFERRED | D, V |
| 9 | Régimes de marché | ACCEPTED / DEFERRED | V, StrategyHealth (§15 DOMAIN_MODEL) |
| 10 | Analyse avancée des trades | ACCEPTED / DEFERRED | U |
| 11 | Strategy Genealogy | ACCEPTED / DEFERRED (concept nouveau) | F |
| 12 | Conservation des échecs | ACCEPTED / DEFERRED (concept nouveau) | D, V |
| 13 | Détection de similarité | ACCEPTED / DEFERRED | P (derrière GATE PORTFOLIO) |
| 14 | Recherche de diversification | ACCEPTED / DEFERRED | P, D |
| 15 | Portfolio Engine | PLANNED / DEFERRED | P (GATE PORTFOLIO déjà définie) |
| 16 | Replay de trade | ACCEPTED / DEFERRED | U |
| 17 | Audit automatique d'un backtest | ACCEPTED / DEFERRED | U (agrégation de preuves V) |
| 18 | Budget de calcul | ACCEPTED / DEFERRED | INFRA, U |
| 19 | Early stopping / pruning | ACCEPTED / DEFERRED | D, S |
| 20 | Construction sans code | ACCEPTED / DEFERRED | DSL (decision pending), U |
| 21 | ProRealTime / ProOrder | PLANNED / DEFERRED (concept nouveau) | E-PRECISION (provisoire) |
| 22 | Paper / Forward testing | PLANNED / DEFERRED | Track à créer, après GATE CHAMPION |
| 23 | Strategy Health | PROPOSED / DEFERRED | déjà DOMAIN_MODEL.md §15, FUTURE |
| 24 | Assistant de lecture | ACCEPTED / DEFERRED | U |

## Concepts de domaine nouveaux nécessitant une future session `/domain-modeling`

Ce document liste ces concepts pour la roadmap ; **il ne les définit pas formellement** (hors
scope d'une mission documentaire produit/roadmap — `/domain-modeling` doit être réellement
invoqué le moment venu, pas simulé ici) :

- **Strategy Genealogy** (§11) — relation de filiation entre `StrategyDefinition`.
- **Rejected Strategy History** (§12) — pendant négatif de `ValidationEvidence`.
- **ProRealTime/ProOrder equivalence** (§21) — rattachement exact à `E-PRECISION` ou nouveau track.
- **Paper/Forward Run** (§22) — track dédié, position exacte dans le graphe de dépendances.

## Risques / tensions déjà identifiés (voir aussi le rapport de mission)

1. **Navigation produit** : la liste de §29 de la mission source (12 espaces : Accueil / Créer une
   stratégie / Recherche & optimisation / Backtests / Validation / Stratégies / Champions /
   Portefeuilles / Données / Calculs / Suivi / Paramètres) **diffère** de la structure à 10 espaces
   déjà documentée dans `docs/architecture/UI_UX_ARCHITECTURE.md` §2 (Accueil / Data Center /
   Laboratoire de stratégies / Backtest / Optimisation / Validation / Résultats / Champions /
   Historique / Administration). **Non réconcilié ici** — voir
   `docs/ux/UX_UI_PRODUCT_DIRECTION.md` §8.
2. **Search History Leakage** : plusieurs capacités futures (§10 analyse de trades, §19 early
   stopping) touchent aux mêmes données utilisées pour décider — rappelées ici pour qu'un futur
   Autopilot ne les implémente jamais sans réappliquer explicitement la discipline anti-leakage
   déjà actée (`DOMAIN_MODEL.md` §12).
3. **Aucune contradiction trouvée** entre ce document et `MASTER_ROADMAP.md`/`DOMAIN_MODEL.md` sur
   l'ordre des gates — tout ce qui touche Discovery/Portfolio reste explicitement derrière
   `GATE V`/`GATE D`/`GATE CHAMPION`/`GATE PORTFOLIO`, sans exception proposée ici.
