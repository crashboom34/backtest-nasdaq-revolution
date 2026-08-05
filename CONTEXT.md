# Backtest Nasdaq Revolution — CONTEXT.md

Logiciel de backtest de stratégies de trading algorithmique, centré aujourd'hui sur l'indice
US100 (NASDAQ) en timeframe M3, alimenté par des données MetaTrader 5. Ce document est le
langage commun entre l'utilisateur, Claude Code, Codex et les futurs développeurs — voir
`docs/agents/domain.md` pour la manière dont les agents doivent le lire et le mettre à jour.

Statut de ce document : première version, construite par lecture directe du code
(`engine.py`, `get_data.py`, `strategies/`, `job_*.py`, `champion_*.py`, `retest_*.py`,
`data_validator.py`, `path_resolver.py`, `optimizer*.py`, `scoring.py`). Chaque terme est
marqué **Confirmé** (constaté dans le code) ou **À confirmer** (absent du code actuel, ou
usage flou) — ne jamais traiter une entrée **À confirmer** comme une décision validée.

Mise à jour du 2026-08-05 : ajout du vocabulaire du socle "Data Center" (`market_data/`),
construit par lecture de `market_data/schema.py`, `ports.py`, `adapters/local_csv.py`,
`catalog.py`, `resample.py`, `derived.py`, et des ADR 0002/0003.

Dépôt mono-contexte : un seul `CONTEXT.md` à la racine, pas de `CONTEXT-MAP.md`.

## Langage

**Moteur de backtest** :
Le composant central (`engine.py`, fonction `run_backtest()`) qui simule l'exécution d'une
stratégie sur des données historiques : gestion des positions, des coûts (spread, slippage),
du P&L et du drawdown. Renvoie trades, courbe d'équity et statistiques.
_À ne pas confondre avec_ : l'optimiseur (`optimizer.py`), qui appelle le moteur en boucle sur
des jeux de paramètres.
Statut : **Confirmé**.

**Stratégie de trading** :
Un module Python (ex. `strategies/perfect_revolution_v1.py`) exposant un contrat
`prepare` / `on_bar` / `reset`, consommé par le moteur pour générer des signaux d'entrée et de
sortie. Chaque stratégie déclare son propre `PARAM_SCHEMA` pour générer l'UI de configuration.
Statut : **Confirmé**.

**Version de stratégie** :
Il n'existe pas de mécanisme de versioning formel des stratégies ; seule une chaîne de
caractères libre (ex. `"NASDAQ Perfect Revolution V1.1"`) sert d'étiquette d'affichage.
_À ne pas confondre avec_ : un futur système de versions structurées (numéro, changelog) — non
implémenté à ce jour.
Statut : **À confirmer**.

**Données historiques** :
Séries de bougies passées, téléchargées depuis MetaTrader 5 (`get_data.py`) et persistées par
actif/timeframe (`path_resolver.py`), utilisées comme entrée du moteur de backtest.
Statut : **Confirmé**.

**Fournisseur de données** :
Aujourd'hui, un seul fournisseur réellement utilisé par le moteur : MetaTrader 5 (MT5), via le
module `MetaTrader5` (`get_data.py`) et le CSV qu'il produit. Une abstraction multi-
fournisseurs existe désormais dans `market_data/` (voir *Port de données de marché*) mais
n'est **pas encore branchée** sur `engine.py` ni sur `get_data.py` : elle ne dessert pour
l'instant qu'un adaptateur CSV local.
_À ne pas confondre avec_ : un import CSV manuel, qui est une voie d'entrée de données
distincte (voir *Import CSV*) et ne passe pas par MT5.
Statut : **Confirmé** (fournisseur unique réellement utilisé par le moteur ; abstraction de
port créée mais non connectée — voir *Port de données de marché*).

**Port de données de marché (`MarketDataSource`)** *(terme additionnel, socle Data Center)* :
Interface définie dans `market_data/ports.py` (`list_available()`, `load(asset, timeframe)`)
que tout futur adaptateur fournisseur (EODHD, Dukascopy, FirstRate, IG...) devra respecter.
Un seul adaptateur existe à ce jour : `LocalCsvMarketDataSource`. Le moteur de backtest
(`engine.load_data()`) ne consomme pas encore ce port — il continue de lire un chemin CSV
directement. Décision documentée dans `docs/adr/0002-canonical-market-data-schema.md`.
Statut : **Confirmé** (code existant), **À confirmer** (branchement effectif sur le moteur —
étape future distincte, non réalisée).

**Schéma canonique de données de marché** :
Forme commune que doit respecter une bougie normalisée, indépendamment du fournisseur
d'origine : `time, open, high, low, close, volume` (`market_data/schema.py`). Version
volontairement réduite — pas encore de bid/ask, dividendes, splits ni options (voir
`docs/adr/0002-...`).
Statut : **Confirmé**.

**Adaptateur de données de marché** :
Implémentation concrète du port `MarketDataSource` pour un fournisseur donné. Le seul
adaptateur existant est `LocalCsvMarketDataSource` (`market_data/adapters/local_csv.py`), qui
réutilise `path_resolver.py` sans dupliquer sa logique de résolution de chemin.
Statut : **Confirmé** (un seul adaptateur existant).

**Catalogue de données** :
Inventaire local des jeux de données disponibles (`market_data/catalog.py`), persisté en JSON
dans `settings/data_catalog.json` (ignoré par Git, régénéré à la demande). Distingue aussi, par
timeframe candidat, les statuts `source`, `calculable_cached`, `calculable_not_cached` et
`not_calculable` (voir *Timeframe dérivé*). Pas encore affiché dans l'interface Streamlit.
Statut : **Confirmé** (code et persistance existants), **À confirmer** (aucune page UI ne le
consulte encore).

**Timeframe dérivé (resampling)** :
Unité de temps supérieure calculée à partir d'un timeframe source déjà présent en local (ex.
M15 dérivé de M3), via `market_data/resample.py`. Un timeframe cible n'est calculable que s'il
est un multiple entier du timeframe source ; l'ancrage est UTC uniquement pour l'instant, sans
calendrier de marché (limitation documentée dans `docs/adr/0003-timeframe-resampling-rules.md`).
_À ne pas confondre avec_ : *Split train/test*, qui est un sens totalement différent du mot
"split" dans ce dépôt (voir plus haut).
Statut : **Confirmé**.

**Cache de timeframe dérivé** :
Fichier CSV + métadonnées JSON stockés dans `derived_data/` (ignoré par Git), produits par
`market_data/derived.get_or_generate()`. Le cache est invalidé automatiquement si le nombre de
lignes ou le dernier timestamp de la source change ; il n'est pas encore consulté par le moteur
de backtest.
Statut : **Confirmé**.

**Contrôle qualité (quality_flags)** :
Constat chiffré, en lecture seule, produit par `market_data/quality.analyze_quality()` sur un
DataFrame canonique : doublons de timestamp, `high < low`, prix nul/négatif, valeur manquante,
ordre chronologique, plus un score simple. Ne corrige jamais les données ; se contente de les
qualifier. Version volontairement grossière — pas encore de détection de trous pendant les
heures de séance (nécessite un calendrier de marché absent du dépôt).
Statut : **Confirmé**.

**Configuration fournisseur (clé API)** :
Emplacement générique (`market_data/provider_config.py`) où une future clé API de fournisseur
(EODHD, IG...) sera lue : variable d'environnement `BACKTEST_<PROVIDER>_API_KEY` en priorité,
sinon `settings/data_providers.json` (fichier local, jamais versionné). Aucun connecteur réel
ne consomme encore cette clé.
Statut : **Confirmé** (mécanisme existant), **À confirmer** (aucun fournisseur réel branché
dessus à ce jour).

**Synthèse Data Center (`DatasetSummary`)** :
Structure assemblée par `market_data/summary.py`, combinant une entrée de catalogue, le statut
des timeframes candidats et un rapport de qualité pour un actif/timeframe donné. Fondation
prévue pour une future page Streamlit "Data Center" ; aucune page de ce type n'existe encore.
Statut : **Confirmé** (code existant), **À confirmer** (aucune UI ne le consomme).

**Actif** :
L'instrument tradé, identifié par un symbole (ex. `NASDAQ` / `US100`), utilisé pour organiser
les données sur disque (`data/{actif}/{timeframe}/`) et pour la sélection dans l'UI
(`list_available_assets()`).
Statut : **Confirmé**.

**Instrument** :
Le code n'emploie pas ce mot ; le concept équivalent est nommé "actif" ou "symbole"
(`SYMBOL = "US100"`).
Statut : **À confirmer** (terme non utilisé — préférer "actif" tant qu'aucune distinction
actif/instrument n'est explicitement introduite dans le code).

**Marché** :
Le jeu de données de prix pour un actif donné ; les fichiers CSV importés sont qualifiés de
"CSV de marché" (`data_validator.py`). Un seul marché/symbole par jeu de données.
Statut : **Confirmé**.

**Bougie (candle)** :
Une barre OHLC(V) sur une unité de temps donnée (ex. bougies M3). Unité de base des données
historiques et de la simulation du moteur.
Statut : **Confirmé**.

**Tick** :
N'existe que comme champ de données optionnel (`tick_volume` / alias de volume dans
`data_validator.py`) ; il n'y a pas de simulation intra-bougie au tick.
_À ne pas confondre avec_ : une bougie — le moteur raisonne exclusivement en bougies, pas en
ticks.
Statut : **Confirmé** (comme champ de données), **À confirmer** (comme concept de simulation).

**Unité de temps (timeframe)** :
La granularité temporelle des bougies (ex. `M3`), configurable par actif
(`list_available_timeframes()`, `DEFAULT_TIMEFRAME = "M3"`).
Statut : **Confirmé**.

**Calendrier de marché** :
Aucun concept de calendrier de marché (jours fériés, horaires d'ouverture par marché) trouvé
dans le code.
Statut : **À confirmer**.

**Session de trading** :
"Sessions" n'apparaît que comme intitulé de section dans l'UI (`app.py`) ; il n'y a pas de
modélisation d'un calendrier de sessions (ouverture/fermeture, fuseaux horaires).
Statut : **À confirmer**.

**Signal d'entrée** :
Décision produite par une stratégie pour ouvrir une position (`sig["action"] == "enter"`),
portant une direction et des paramètres de stop/target.
Statut : **Confirmé**.

**Signal de sortie** :
Décision produite par une stratégie pour clôturer une position (`sig["action"] == "exit"`).
Statut : **Confirmé**.

**Ordre** :
Aucune abstraction "ordre" distincte dans le code : le moteur calcule directement les prix
d'exécution à partir des signaux, sans modéliser un objet ordre intermédiaire (type
marché/limite, statut, etc.).
Statut : **À confirmer**.

**Exécution** :
Le remplissage implicite d'un signal : le moteur exécute au prix d'ouverture de la bougie
suivante, ajusté du spread et du slippage (`actual_entry = next_open + spread + slip_in`).
_À ne pas confondre avec_ : *Ordre*, qui n'est pas modélisé séparément.
Statut : **Confirmé** (mécanisme implicite, pas d'objet "exécution" explicite).

**Position** :
L'état d'engagement courant sur l'actif (en position ou non, direction, nombre de contrats),
suivi par le moteur pendant la simulation.
Statut : **Confirmé**.

**Trade** :
Un aller-retour entrée/sortie complet, enregistré comme dictionnaire (date d'entrée, sens, prix
d'entrée/sortie, résultat...) et agrégé dans `trades_df` en sortie du moteur.
Statut : **Confirmé**.

**Spread** :
Coût fixe en unités de prix appliqué à l'entrée et à la sortie d'un trade
(`spread: float = 1.0` dans `engine.py`).
Statut : **Confirmé**.

**Commission** :
Aucun coût de type "commission" distinct dans le moteur ; les coûts de transaction sont
modélisés uniquement via le spread et le slippage.
Statut : **À confirmer**.

**Slippage** :
Écart de prix additionnel appliqué à l'entrée et à la sortie (`slip_in`, `slip_out`),
représentant le glissement d'exécution.
Statut : **Confirmé**.

**Gestion du risque** :
Partiellement présente via des paramètres de stratégie (`max_daily_loss_pct`, `stop_pct`,
`target_pct`) ; il n'existe pas de module dédié de gestion du risque transverse aux stratégies.
Statut : **Confirmé** (partiel, au niveau stratégie).

**Taille de position** :
Calculée à partir de paramètres de stratégie (`use_compounding`, `base_contracts`,
`capital_per_contract`, `max_contracts`) pour produire un nombre de contrats (`nb_contracts`).
Statut : **Confirmé**.

**Capital** :
Le capital disponible, initialisé par `initial_capital` et mis à jour bougie par bougie par le
moteur au fil des trades.
Statut : **Confirmé**.

**Portefeuille** :
Aucun concept de portefeuille multi-actifs : le moteur suit le capital sur un seul actif à la
fois.
Statut : **À confirmer**.

**Drawdown** :
Baisse du capital depuis son plus haut (`peak_capital`), suivie en continu (`dd_now`) et
résumée en fin de run (`max_dd_pct`, `max_daily_dd`).
Statut : **Confirmé**.

**Dividende** :
Aucune gestion de dividende trouvée dans le code.
Statut : **À confirmer**.

**Split (action)** :
Aucune gestion de split d'action (corporate action) trouvée. **Attention à l'ambiguïté** : dans
ce code, "split" désigne quasi systématiquement le **split train/test** (séparation des
données en jeu d'entraînement et de test pour l'anti-overfitting, ex. `tt_method`,
`split_method`), pas un split d'action boursière.
Statut : **À confirmer** (split action boursière) ; **Confirmé** (split train/test, sens
différent — voir *Split train/test* ci-dessous).

**Split train/test** *(terme additionnel, hors liste initiale mais nécessaire pour lever
l'ambiguïté ci-dessus)* :
Séparation des données historiques en une portion d'entraînement/optimisation et une portion de
test, utilisée pour limiter l'overfitting (`app.py`, `tt_method`).
Statut : **Confirmé**.

**Prix ajusté** :
Aucune gestion de prix ajusté (dividendes, splits d'action) trouvée — cohérent avec l'absence
de gestion de dividende/split action ci-dessus.
Statut : **À confirmer**.

**Actif radié** :
Aucune gestion d'actif radié (delisting) trouvée dans le code.
Statut : **À confirmer**.

**Résultat de backtest** :
Le triplet renvoyé par le moteur : trades (`trades_df`), courbe d'équity (`equity_df`) et
statistiques (`stats`), persisté via `history_store.save_run()`.
Statut : **Confirmé**.

**Métrique de performance** :
Statistiques calculées en fin de run par le moteur (win rate, profit factor, max drawdown,
etc.), utilisées pour scorer et comparer des runs.
Statut : **Confirmé**.

**Profit factor** :
`gross_win / gross_loss`, calculé par le moteur et pondéré dans le scoring (`scoring.py`).
Statut : **Confirmé**.

**Taux de réussite (win rate)** :
`n_win / n_trades * 100`, calculé par le moteur et utilisé dans le scoring.
Statut : **Confirmé**.

**Espérance (expectancy)** :
Aucune métrique d'espérance mathématique trouvée dans `engine.py`, `scoring.py` ou
`optimizer.py`.
Statut : **À confirmer**.

**Optimisation** :
Recherche de paramètres de stratégie par balayage, exécutée en parallèle
(`ProcessPoolExecutor`) via `optimizer.py` / `optimizer_process.py`.
Statut : **Confirmé**.

**Scénario** :
Aucune abstraction "scénario" trouvée dans le code (au sens d'un scénario de marché ou de test
nommé).
Statut : **À confirmer**.

**Comparaison de stratégies** :
Fonctionnalité dédiée (`job_comparison.py`) qui charge des enregistrements de jobs et détermine
le meilleur run selon des critères de score (`best_job()`).
Statut : **Confirmé**.

**Import CSV** :
Import et validation de fichiers CSV de marché via l'UI (`app.py`, `data_validator.py`,
`validate_market_csv_bytes`).
Statut : **Confirmé**.

**Import ZIP** :
Le code produit des **exports** ZIP (archives de résultats de job), mais aucune fonctionnalité
d'**import** de données au format ZIP n'a été trouvée.
_À ne pas confondre avec_ : *Import CSV*, qui est la seule voie d'import de données de marché
confirmée.
Statut : **À confirmer** (comme voie d'import — seul l'export ZIP est confirmé).

**Import Parquet** :
Aucun support du format Parquet trouvé ; le CSV est le seul format de données de marché géré.
Statut : **À confirmer**.

**Actions (stocks)** :
Aucune donnée ni logique spécifique aux actions (par opposition aux indices/CFD) trouvée.
Statut : **À confirmer**.

**Indices** :
L'application cible aujourd'hui un indice (US100 / NASDAQ) comme actif principal (README.md).
Statut : **Confirmé** (cas d'usage unique constaté).

**Forex** :
Aucune donnée ni logique spécifique au Forex trouvée dans le code.
Statut : **À confirmer**.

**CFD** :
Le terme "CFD" n'apparaît pas explicitement dans le code, bien que US100 soit un produit de
type indice/CFD chez le broker sous-jacent (MT5).
Statut : **À confirmer**.

**Options (produit financier)** :
Aucune logique d'options financières trouvée ; "Options" n'apparaît que comme intitulé
générique de section de configuration dans l'UI.
Statut : **À confirmer**.

**Interface utilisateur (UI)** :
Application Streamlit (`app.py`, `ui_components.py`), avec génération automatique de formulaires
à partir du `PARAM_SCHEMA` de chaque stratégie.
Statut : **Confirmé**.

**Base de données** :
Aucune base de données (SQL ou autre) trouvée : la persistance est intégralement basée sur des
fichiers (JSON, CSV, pickle) via `history_store.py`, `job_store.py`, `optimization_store.py`.
Statut : **À confirmer** (absente — persistance fichier uniquement, confirmé).

**Cache** :
Usage ponctuel du cache Streamlit (`@st.cache_data`) côté UI, et d'un cache de précalcul numpy
au niveau du moteur (`engine.py`) ; pas de module de cache dédié et transverse.
Statut : **Confirmé** (usage local, pas de module dédié).

**File d'exécution (execution queue)** :
Aucune structure de file d'attente : les jobs sont lancés via `subprocess.Popen` /
`ProcessPoolExecutor`, avec un garde-fou empêchant plusieurs jobs actifs simultanément
(`assert_no_active_jobs()`), mais pas de file au sens structure de données.
Statut : **À confirmer**.

**Reproductibilité d'un backtest** :
La configuration d'un run est sauvegardée (`config_used.json`), ce qui permet de relancer un
backtest avec les mêmes paramètres ; en revanche, aucune graine aléatoire (seed) ni garantie
explicite de déterminisme n'a été trouvée.
Statut : **À confirmer**.

## Concepts additionnels constatés (hors liste initiale, mais utiles)

**Champion** *(à confirmer précisément avec l'équipe)* :
Vocabulaire fort et récurrent dans le code (`champion_validation.py`, `champion_pipeline.py`,
`champion_roadmap.py`, `champion_report.py`, `retest_plan.py`, `retest_links.py`) autour de la
validation et du "retest" de configurations gagnantes ("champion"/"favori"), avec des verdicts
(`VERDICT_SERIOUS`, `VERDICT_PROMISING`, ...). Mérite sa propre entrée de glossaire détaillée
lors d'une prochaine session `/domain-modeling` — non détaillé ici pour éviter d'inventer une
définition non confirmée par une discussion avec l'utilisateur.
Statut : **À confirmer** (existence du vocabulaire confirmée dans le code ; définition précise
et frontières du concept à valider avec l'utilisateur).
