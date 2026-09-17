# AI_HANDOFF.md — Contexte technique du projet

> **Consigne pour Claude Code, Codex ou tout assistant IA :**
> Lis ce fichier en entier avant de toucher quoi que ce soit dans ce projet.
> Il décrit l'état réel du code, ce qui a été fait, ce qui reste à faire, et les règles à respecter.

---

## 1. Ce que fait le projet

Plateforme de backtesting et d'optimisation de stratégies de trading sur le NASDAQ 100 (US100), timeframe M3 (3 minutes).

- Charge `nasdaq_3m.csv` (non versionné, à placer à la racine)
- Prépare aussi une organisation multi-actifs/timeframes dans `data/{ASSET}/{TIMEFRAME}/`
- Exécute la stratégie `strategies/perfect_revolution_v1.py` avec des combinaisons de paramètres
- Optimise par force brute (toutes les combinaisons) en parallèle avec `concurrent.futures.ProcessPoolExecutor`
- Interface web Streamlit (`app.py`) + lanceur CLI (`run_job.py`)
- Chaque job CLI génère un dossier `results/job_YYYYMMDD_HHMMSS_xxxx/` avec 7 artefacts

---

## 2. Architecture des fichiers principaux

| Fichier                  | Rôle                                                                 |
|--------------------------|----------------------------------------------------------------------|
| `app.py`                 | Interface Streamlit : config, lancement, suivi, résultats            |
| `run_job.py`             | Lanceur CLI : génère job_id, lance subprocess, affiche progression   |
| `optimizer_process.py`   | Subprocess d'optimisation : itère les combos, écrit les résultats    |
| `optimizer.py`           | Génère les combinaisons, calcule les bornes                          |
| `engine.py`              | Moteur de backtest : applique la stratégie sur les données           |
| `scoring.py`             | Calcule le score composite (Sharpe, winrate, drawdown, etc.)         |
| `optimization_store.py`  | Lit/écrit tous les fichiers de run (progress, config, meta, etc.)    |
| `job_store.py`           | Génère les artefacts de fin de job : metrics, HTML, CSV, zip         |
| `job_artifacts.py`       | Vérifie les fichiers de job, lit les bytes de téléchargement, régénère `archive.zip` |
| `path_resolver.py`       | Résout `BASE_DIR` (local vs serveur via `BACKTEST_BASE_DIR`)         |
| `data_validator.py`      | Valide et normalise les CSV importés avant sauvegarde dans `data/`   |
| `maintenance.py`         | Analyse les fichiers locaux générés et prépare des nettoyages sécurisés |
| `dashboard.py`           | Agrège les KPIs d'accueil : disque, jobs, données disponibles, alertes |
| `job_comparison.py`      | Normalise les métriques récentes/legacy et prépare la comparaison de 2 à 5 jobs |
| `job_annotations.py`     | Lit/écrit les classements, notes et tags dans `job_notes.json` sans toucher aux résultats |
| `job_decisions.py`       | Journalise atomiquement les décisions utilisateur dans `job_decisions.json` |
| `champion_report.py`     | Construit la fiche Champion/Favori, détecte forces/alertes et propose une décision simple |
| `champion_export.py`     | Génère en mémoire les exports Markdown et HTML du Rapport Champion |
| `champion_validation.py` | Évalue les 8 critères de sérieux d'un Champion/Favori et produit un verdict global |
| `champion_roadmap.py`    | Agrège les jobs annotés en statuts de maturité et prochaine action |
| `champion_pipeline.py`   | Regroupe les jobs annotés par étape visuelle de validation Champion |
| `retest_plan.py`         | Propose un plan de retest plus sérieux et applique ses limites à une config clonée |
| `retest_links.py`        | Lit le lien Champion source → retest → résultat sans modifier les artefacts bruts |
| `demo_data.py`           | Génère un jeu de jobs factices temporaire pour tester l'UI sans toucher aux vrais `results/` |
| `validation_settings.py` | Lit/écrit les seuils Champion globaux dans `settings/champion_validation.json` |
| `ui_components.py`       | Petits helpers d'affichage Streamlit : en-têtes, panneaux d'aide, étapes |
| `ui_data_center.py`      | Sous-onglet Streamlit "Data Center (aperçu)" en lecture seule (onglet Données) |
| `strategies/perfect_revolution_v1.py` | Stratégie principale avec ses paramètres                |
| `market_data/schema.py`  | Schéma canonique minimal d'une bougie (socle Data Center, voir ADR 0002) |
| `market_data/ports.py`   | Interface `MarketDataSource` (port hexagonal), pas encore branchée dans `engine.py` |
| `market_data/adapters/local_csv.py` | Premier adaptateur : habillage de `path_resolver.py`, aucune logique dupliquée |
| `market_data/catalog.py` | Catalogue local (JSON), statut source/calculable/en cache par timeframe |
| `market_data/resample.py` | Génère un timeframe supérieur à partir d'un timeframe source (ADR 0003) |
| `market_data/derived.py` | Cache disque des timeframes dérivés (`derived_data/`, invalidé si la source change) |
| `market_data/quality.py` | Contrôle qualité basique en lecture seule (`quality_flags`, score) |
| `market_data/provider_config.py` | Clés/identifiants fournisseurs (EODHD + IG typés), jamais versionné, jamais de secret dans repr/logs |
| `market_data/summary.py` | Assemble catalogue + statut timeframes + qualité (fondation future page Data Center) |
| `market_data/eodhd/`     | Connecteur REST EODHD (config, HTTP retry/backoff, fenêtrage, normalisation, stockage, adaptateur `MarketDataSource`) — voir section Data Center ci-dessous |
| `market_data/ig/`        | Connecteur IG démo lecture seule (config, session CST/token, client) — aucune fonction de trading |
| `market_data/backtest_manifest.py` | Manifeste reproductible d'un backtest — additif, pas encore branché dans `run_job.py` |
| `scripts/test_eodhd_connection.py` | Script de test de connexion EODHD pour débutant (aucun secret affiché, réseau désactivé par défaut) |
| `scripts/test_ig_connection.py` | Script de test de connexion IG démo pour débutant (même contrat, environnement live toujours refusé) |

### Organisation des données de marché

Structure cible progressive :

```
data/
├── NASDAQ/
│   └── M3/
├── SP500/
│   └── M3/
└── DAX/
    └── H1/
```

État actuel :

- `path_resolver.py` sait lister les actifs/timeframes préparés dans `data/`.
- `path_resolver.py` sait résoudre `data/{ASSET}/{TIMEFRAME}/*.csv`.
- Compatibilité legacy conservée : `NASDAQ/M3` retombe sur `nasdaq_3m.csv` à la racine si aucun CSV n'est encore dans `data/NASDAQ/M3/`.
- Onglet Streamlit `Données` : importe un CSV, valide sa qualité, puis sauvegarde dans `data/{ASSET}/{TIMEFRAME}/{asset}_{timeframe}.csv`.
- Validation CSV actuelle : fichier lisible, colonne date/temps, colonnes `open/high/low/close`, dates convertibles, ordre chronologique, doublons, valeurs manquantes, prix <= 0, cohérence `high >= low`, nombre de lignes, dates début/fin.
- Aucun gros CSV n'a été déplacé automatiquement.
- `.gitignore` ignore `data/**/*.csv`; seul le squelette vide avec `.gitkeep` peut être versionné.
- MT5 n'est pas encore branché.

### Data Center — socle local (Phase 1, depuis le 2026-08-05)

Démarrage du futur "Data Center" multi-fournisseurs (voir la demande utilisateur du
2026-08-05 et le rapport d'architecture associé). Portée volontairement réduite à un socle
100% local, sans aucun appel réseau, sans nouvelle dépendance, et **sans rien brancher dans
`app.py` ni `engine.py`** — le comportement existant de l'application n'est pas modifié.

Ce qui existe dans `market_data/` :

- **Schéma canonique minimal** (`schema.py`, ADR 0002) : `time, open, high, low, close, volume`.
- **Port `MarketDataSource`** (`ports.py`) : interface que devra respecter tout futur
  fournisseur (EODHD, Dukascopy, FirstRate, IG...).
- **Premier adaptateur `LocalCsvMarketDataSource`** (`adapters/local_csv.py`) : réutilise
  `path_resolver.py` et le comportement CSV existant, sans le dupliquer.
- **Catalogue local** (`catalog.py`) : inventaire JSON (`settings/data_catalog.json`, ignoré
  par Git) des datasets présents dans `data/`, avec `row_count`/`start`/`end` optionnels.
- **Génération de timeframes dérivés** (`resample.py`, ADR 0003) : dérive un timeframe
  supérieur multiple du timeframe source (ex. M3 → M15), ancrage UTC uniquement pour
  l'instant (pas de calendrier de marché — limitation documentée).
- **Cache disque des timeframes dérivés** (`derived.py`) : `derived_data/` (ignoré par Git),
  invalidé automatiquement si les données source changent.
- **Statut par timeframe** (`catalog.list_timeframe_status()`) : distingue `source`,
  `calculable_cached`, `calculable_not_cached`, `not_calculable` pour un actif donné.
- **Contrôle qualité basique** (`quality.py`) : `analyze_quality()` calcule des `quality_flags`
  (`duplicate_bar`, `invalid_ohlc`, `non_positive_price`, `missing_value`, `out_of_order`,
  `empty_dataset`) et un score simple sur un DataFrame canonique, sans jamais modifier ni
  "réparer" les données.
- **Emplacement générique pour les futures clés API** (`provider_config.py`) : résout une clé
  par variable d'environnement `BACKTEST_<PROVIDER>_API_KEY` en priorité, sinon
  `settings/data_providers.json` (fichier local, **jamais versionné** — ajouté au
  `.gitignore`). `credential_status()` ne renvoie jamais la valeur du secret, seulement son
  origine. Aucun fournisseur réel ne consomme encore cette clé (aucun connecteur EODHD/
  Dukascopy/FirstRate/IG/Binance/Alpaca n'existe à ce jour, voir plus bas).
- **Assembleur "Data Center"** (`summary.py`) : `build_dataset_summary()` /
  `build_data_center_summary()` combinent catalogue, statut des timeframes et qualité en une
  structure unique, en lecture seule — fondation d'une future page Streamlit "Data Center"
  (page non créée à cette étape).

**Comment tu fourniras tes clés API plus tard** : quand tu auras une clé (EODHD, IG...), deux
façons de la donner, sans jamais la coller dans un fichier suivi par Git :
1. Variable d'environnement, ex. `$env:BACKTEST_EODHD_API_KEY = "..."` avant de lancer l'app ;
2. Ou via `market_data.provider_config.save_api_key("eodhd", "...")`, qui écrit dans
   `settings/data_providers.json` (ignoré par Git).
Aucun de ces deux mécanismes n'est branché à un connecteur réel pour l'instant — ils servent à
préparer l'emplacement, pas encore à télécharger quoi que ce soit.

**Port branché (2026-08-05, suite)** :
- `engine.load_data_from_source(source, asset, timeframe)` : nouvelle fonction additive qui
  charge via un `MarketDataSource` au lieu d'un chemin CSV direct. Produit un résultat
  strictement identique à `engine.load_data()` (vérifié par test d'équivalence, y compris
  contre le vrai `nasdaq_3m.csv`). `load_data()` elle-même reste inchangée dans son
  comportement — un refactor interne (`_add_market_time_columns()`) partage juste la logique
  de fuseau horaire entre les deux fonctions. **`load_data_from_source()` n'est pas encore
  appelée par `run_job.py` ni par le lancement d'optimisation** : le chemin réellement utilisé
  pour tout backtest reste `load_data()` + CSV direct.
- `ui_data_center.py` + sous-onglet **"Data Center (aperçu)"** dans l'onglet Données de
  l'application (`app.py`) : lecture seule, affiche le catalogue local et le statut des futurs
  fournisseurs. L'import CSV existant devient le sous-onglet "Importer un CSV", comportement
  identique à avant (vérifié avec Playwright/Edge — capture d'écran identique au formulaire
  d'origine, aucune erreur).
- Validé en conditions réelles sur le vrai `nasdaq_3m.csv` (1 000 000 lignes) via le sous-onglet
  Data Center : catalogue, qualité (100 %) et statut des timeframes corrects, sans modifier le
  fichier.
- Playwright (Python, canal `msedge`, pas de Chromium téléchargé) a été installé dans `.venv`
  pour cette validation ponctuelle. Il n'est pas ajouté à `requirements.txt` ni à une suite de
  tests permanente à ce stade — à décider si une validation UI automatisée récurrente est
  souhaitée.

**Point d'attention disque** : ≈3,0 Go libres sur C: au début de la session du 2026-08-05,
≈6,3 Go plus tard dans la même session (espace libéré entre-temps, en dehors de ce projet).
≈5,2 Go libres au début de la session du 2026-08-06. Avant tout téléchargement réel de données,
vérifier l'espace disponible au moment voulu et prévoir, si besoin, de stocker les données de
marché sur un autre disque.

### Data Center — identifiants IG typés + connecteur REST EODHD (2026-08-06)

**Sécurité des identifiants (Phase 2)** — `market_data/provider_config.py` étendu sans casser le
mécanisme EODHD existant :
- `EodhdCredentials`, `IgCredentials`, `ProviderCredentialStatus` : dataclasses dédiées, `repr()`/
  `str()` ne révèlent jamais un secret (seulement "set"/"unset" par champ).
- `get_ig_credentials()` / `save_ig_credentials()` / `ig_credential_status()` : api_key,
  identifier, environment, account_id suivent la même priorité que EODHD (env puis
  `settings/data_providers.json["ig"]`) ; **`password` est résolu UNIQUEMENT depuis
  `BACKTEST_IG_PASSWORD`, jamais depuis le fichier** — `save_ig_credentials()` n'a
  structurellement aucun paramètre `password`, donc ne peut pas l'écrire par erreur.
- `tests/conftest.py` (nouveau) : fixture autouse qui neutralise les variables sensibles
  (`BACKTEST_EODHD_API_KEY`, `BACKTEST_IG_*`, `BACKTEST_RUN_LIVE_PROVIDER_TESTS`) avant chaque
  test — corrige un bug préexistant où 4 tests de `provider_config` lisaient la vraie clé EODHD
  de la machine de développement dès qu'elle était configurée.

**MCP EODHD (Phase 3)** : vérifié connecté (`get_user_details` — compte payant, quota
100 000 appels/jour + 500 extra). Utilisé uniquement pour confirmer format de réponse et
endpoints (`/eod`, `/intraday`, `/div`, `/splits`, `/search`, `/exchanges-list`,
`/exchange-symbol-list`, `/user`) avant d'écrire le connecteur — endpoints et limites
recoupés avec la documentation officielle eodhd.com (jamais devinés). Aucune dépendance runtime
au MCP : le connecteur ci-dessous appelle directement l'API REST.

**Connecteur REST EODHD (Phase 4)** — nouveau package `market_data/eodhd/`, aucun appel réseau à
l'import, 100% testé hors ligne (fixtures/faux client HTTP, 67 tests) :
- `errors.py` : hiérarchie d'exceptions (`EodhdAuthError` 401, `EodhdForbiddenError` 403,
  `EodhdNotFoundError` 404, `EodhdRateLimitError` 429, `EodhdServerError` 5xx,
  `EodhdResponseError`, `EodhdNetworkError`, `EodhdWindowLimitError`) ; `redact_url()` retire
  toujours `api_token` d'une URL avant tout message d'erreur.
- `config.py` : `EodhdConfig` (timeouts, retries, backoff, User-Agent explicite, taille de
  réponse plafonnée) résolu via `provider_config.get_api_key("eodhd", ...)` — mécanisme EODHD
  historique conservé tel quel.
- `http_client.py` : un seul point d'entrée réseau, retry/backoff sur erreurs réseau/429/5xx
  (respecte `Retry-After` si présent), mapping HTTP -> exceptions explicites, garde-fou taille de
  réponse.
- `windowing.py` : découpe un téléchargement intraday selon les limites EODHD confirmées (1m ->
  120 j, 5m -> 600 j, 1h -> 7200 j), lève une erreur explicite plutôt qu'un téléchargement
  silencieusement énorme si trop de fenêtres seraient nécessaires.
- `normalize.py` : EOD/intraday -> schéma canonique (`time` tz-naive représentant l'UTC, même
  convention que `local_csv`/`engine.py`) ; dividendes/splits normalisés séparément, hors du
  schéma canonique OHLCV (voir ADR 0002 — pas encore de colonnes dividendes/splits).
- `client.py` (`EodhdClient`) : `test_connection()`, `get_account_status()` (quota, jamais
  nom/email), `search_instruments()`, `list_exchanges()`, `list_exchange_symbols()` (dont
  `delisted=True` pour les titres radiés), `download_eod()`, `download_intraday()` (fenêtré
  automatiquement, déduplique les timestamps en bord de fenêtre), `download_dividends()`,
  `download_splits()`. Échecs réseau/HTTP renvoyés comme résultat `ok=False` explicite plutôt
  qu'une exception technique, sauf le garde-fou "trop de fenêtres" qui lève avant tout appel.
- `storage.py` : stockage sous `BACKTEST_DATA_DIR` — `raw/eodhd/{ticker}/{kind}/{hash}.json`
  (immuable, idempotent par hash de contenu) + manifeste sidecar ; `normalized/{asset}/
  {timeframe}/{hash}.parquet` (schéma canonique uniquement) + manifeste dans `manifests/`
  (qualité via `market_data.quality`, période couverte, timezone UTC, hash, date de synchro).
  Redaction défensive : toute clé `api_token`/`api_key`/`token`/`password` est retirée des
  manifestes même si transmise par erreur. `ensure_free_disk_space()` bloque toute écriture si
  moins de 2 Go libres.
- `scripts/test_eodhd_connection.py` (nouveau dossier `scripts/`) : script pour débutant,
  affiche uniquement configuré/non configuré/connexion réussie/échouée, aucun appel réseau sauf
  si `BACKTEST_RUN_LIVE_PROVIDER_TESTS=1`. Test réel limité à `AAPL.US`, 5 derniers jours, EOD.
- `requirements.txt`/`requirements-server.txt` : ajout de `requests==2.34.2` et
  `pyarrow==24.0.0` (déjà présents dans `.venv`, désormais épinglés pour la reproductibilité).

### Data Center — Phases 5 à 11 (2026-08-06, suite même session)

**Phase 6 — unités calendaires (ADR 0004)** : `market_data/resample.py` gère désormais W1
(semaine, ancrage lundi-dimanche UTC) et MO1 (mois civil UTC), dérivables uniquement depuis une
source D1 (jamais directement depuis un timeframe intraday). Détection d'incomplétude basée sur
la comparaison à la dernière donnée disponible (pas un comptage de barres attendues, qui
donnerait un faux "incomplet" chaque semaine à cause des week-ends). `DEFAULT_CANDIDATE_TIMEFRAMES`
étendu avec H6, H12, W1, MO1. Le petit test réel EODHD (Phase 9) et toutes les unités déjà
supportées (2m/3m/5m/10m/15m/4h/6h/12h) fonctionnaient déjà via le mécanisme générique existant.

**Phase 5 — catalogue/stockage EODHD** : `market_data/eodhd/storage.py` complété avec
`list_normalized_snapshots()`, `list_raw_snapshots()`, `disk_usage_summary()`, et un journal de
synchronisation (`record_sync_event()`/`load_sync_log()`/`last_successful_sync()`/
`last_failed_sync()`, plafonné à 200 événements, sous `manifests/sync_log.json`). Correction
d'un bug de collision de hash découvert par les tests : le hash de contenu d'un snapshot
normalisé inclut désormais `asset|timeframe|ticker|source`, pas seulement les valeurs OHLCV
(deux instruments différents avec des prix identiques auraient sinon partagé le même manifeste).

**Phase 7 — connecteur IG démo, lecture seule** (`market_data/ig/`) : endpoints confirmés par
recoupement documentation officielle IG Labs + bibliothèque de référence `trading-ig`
(2026-08-06) — `POST /session` (v2, login), `DELETE /session` (v1, logout), `GET /accounts`
(v1), `GET /markets?searchTerm=` (v1, recherche), `GET /markets/{epic}` (v3, détails),
`GET /prices/{epic}/{resolution}/{start}/{end}` (v2, historique — résolutions confirmées :
SECOND, MINUTE(_2/3/5/10/15/30), HOUR(_2/3/4), DAY, WEEK, MONTH ; format date
`"%Y/%m/%d %H:%M:%S"`). Base URL démo (`https://demo-api.ig.com/gateway/deal`) codée en dur,
non paramétrable — `IgConfig.__post_init__()` refuse toute autre URL, y compris la live. Session
CST/X-SECURITY-TOKEN en mémoire uniquement (`IgHttpClient`), jamais écrite sur disque. Aucune
méthode de trading n'existe (vérifié par un test qui énumère les méthodes publiques d'`IgClient`
et refuse toute mention position/order/deal/trade/close/otc/confirm). Identifiants IG absents
sur cette machine : tout construit et testé avec des fixtures/mocks (52 tests), 0 appel réseau
réel effectué. `scripts/test_ig_connection.py` reporte "non configuré" proprement.

**Phase 9 — test réel EODHD exécuté** (autorisation explicite utilisateur, 2026-08-06) :
`scripts\test_eodhd_connection.py` avec `BACKTEST_RUN_LIVE_PROVIDER_TESTS=1` (flag scopé à la
commande, jamais persisté) → connexion réussie, téléchargement de 3 bougies EOD réelles pour
`AAPL.US` (5 derniers jours). Confirme que le connecteur REST fonctionne de bout en bout contre
la vraie API, indépendamment de Claude Code/MCP.

**Phase 10 — page Data Center étendue** : `ui_data_center.py` (module existant, pas de refonte
d'`app.py`) complété avec 3 nouvelles sections : connecteur REST EODHD (statut, bouton de test
réel, catalogue des snapshots déjà téléchargés, journal de synchro, avertissement avant gros
téléchargement), connecteur IG démo (statut, bouton de test réel — jamais la valeur brute de
`BACKTEST_IG_ENVIRONMENT`, seulement "demo (autorisé)" ou un refus générique), stockage local
(espace disque). Validé avec Playwright (Edge, headless) : clic réel sur "Tester la connexion
EODHD" → bannière verte "Connexion EODHD réussie." après ~8 s (vrai appel réseau), aucune erreur
console, aucun secret visible dans le texte ni les captures. Note statique expliquant que le MCP
EODHD est un outil de développement Claude Code, non interrogeable depuis l'app en cours
d'exécution (processus différent).

**Phase 11 — façade de compatibilité + manifeste** :
- `market_data/eodhd/adapter.py` (`EodhdMarketDataSource`) : implémente le port
  `MarketDataSource` en relisant les snapshots normalisés déjà stockés localement (aucun
  téléchargement déclenché dans `list_available()`/`load()`, même contrat que
  `LocalCsvMarketDataSource`). Test clé : `engine.load_data_from_source()` fonctionne à
  l'identique avec cet adaptateur qu'avec le CSV local, sans qu'`engine.py` connaisse EODHD —
  c'est la façade de compatibilité demandée.
- `market_data/backtest_manifest.py` (`BacktestManifest`/`build_backtest_manifest()`/
  `save_backtest_manifest()`/`load_backtest_manifest()`) : manifeste reproductible avec tous les
  champs minimaux requis (fournisseur, instrument, symbole fournisseur, type d'actif, snapshot,
  hash, période, unité source/dérivée, timezone, séance, gestion des barres partielles, options
  de rééchantillonnage, version stratégie/moteur, commit Git si disponible, date de lancement).
  Écriture atomique, immuable (`FileExistsError` si le chemin existe déjà).
- **Branchement réel effectué (2026-08-06, autorisation explicite de l'utilisateur après
  disclosure du risque)** : `optimizer_process.py` et `optimizer.py` (fallback séquentiel)
  chargent désormais leurs données via `engine.load_data_from_source(SingleFileCsvMarketDataSource
  (config.data_file), ...)` au lieu d'un appel direct à `engine.load_data(config.data_file)`.
  `engine.load_data()` elle-même reste inchangée (toujours utilisée ailleurs, ex. `app.py`).
  - **Découverte critique pendant la caractérisation** : le vrai `nasdaq_3m.csv` a des colonnes
    non canoniques (`tick_volume`, `spread`) en plus des colonnes canoniques. Une première
    version de l'adaptateur (basée sur `LocalCsvMarketDataSource`, qui restreint au schéma
    canonique) aurait silencieusement perdu ces deux colonnes. Confirmé inoffensif par grep
    (aucun code de `engine.py`/`strategies/`/`scoring.py`/`optimizer.py` ne les lit), mais
    corrigé quand même par principe : nouveau module `market_data/csv_reading.py` avec deux
    fonctions distinctes — `read_canonical_csv()` (restreint + synthétise "volume", utilisé par
    `LocalCsvMarketDataSource`, comportement inchangé) et `read_raw_validated_csv()` (passage
    strictement transparent, utilisé par le nouvel adaptateur `SingleFileCsvMarketDataSource`
    dans `market_data/adapters/single_file_csv.py`).
  - **Preuve d'équivalence** : `tests/test_engine_load_data_from_source.py::
    test_single_file_csv_source_matches_load_data_on_the_real_nasdaq_csv` compare
    `pd.testing.assert_frame_equal` sur le vrai fichier (1 000 000 lignes) — vert.
  - **Validation end-to-end réelle** : deux jobs réels lancés avec `run_job.py` (preset
    équivalent "Test rapide local", 12 combinaisons, `max_rows=50000`) après le swap :
    `job_phase11_facade_check_001` et `job_phase11_manifest_check_001`, tous deux `completed`,
    12/12 testées, 7 fichiers générés. Laissés dans `results/` (jamais supprimés sans
    autorisation) — supprimables via l'onglet Maintenance si souhaité.
- **Manifeste branché** : `job_store.write_data_manifest()` écrit `data_manifest.json` dans
  chaque job (appelé depuis `finalize_job()`, après `write_archive()`). Champs disponibles avec
  les métadonnées actuelles du pipeline (`provider="local_csv"`, `instrument`/`provider_symbol`
  dérivés du nom de fichier, `strategy_version` depuis `meta`, `git_commit` auto-détecté,
  `launched_at`) ; `source_timeframe`/`period_start`/`period_end`/`snapshot_id`/`content_hash`
  restent `"unknown"`/`None` tant que le pipeline ne track pas ces informations plus finement
  (honnête plutôt que deviné). **Vérifié que `data_manifest.json` n'apparaît jamais dans
  `archive.zip`** (toujours exactement les 7 fichiers historiques — `ARCHIVE_SOURCE_FILES` est
  une liste explicite, jamais un scan de dossier).
- **Calendrier de marché (amorce)** : `EodhdClient.get_exchange_details()` (endpoint confirmé :
  `/exchange-details/{EXCHANGE_CODE}`) + nouveau module `market_data/eodhd/calendar.py`
  (`ExchangeCalendar`, `parse_exchange_calendar()`, `is_trading_day()`). Basé sur l'échantillon
  réel capturé via le MCP EODHD (exchange "US" : fuseau, heures UTC, jours ouvrés, jours fériés,
  fermetures anticipées). Pas encore consommé par `market_data.resample` (qui reste ancré UTC
  sans calendrier de marché, limitation documentée depuis l'ADR 0003) — c'est la brique de base,
  l'intégration dans le resampling reste à faire.
- **Catalogue unifié** : nouveau `market_data/unified_catalog.py`
  (`build_unified_catalog(local_source, eodhd_data_dir)`) combine le catalogue CSV local et les
  snapshots EODHD en une liste unique, sans dupliquer ni modifier `market_data.catalog` ou
  `market_data.eodhd.storage`. Nouvelle section "6. Catalogue unifié" dans `ui_data_center.py`.

**Commit effectué (2026-08-06, autorisation explicite)** : `51a35c2` — 59 fichiers, tout le
travail ci-dessus (Phases 2-11). Pas de push.

### Data Center — finalisation (2026-08-06, suite, "finalise tout ce qui reste à faire")

- **Détection de trous calendaire** : `market_data.quality.detect_missing_trading_days(df,
  calendar)` — additive, à côté d'`analyze_quality()` (qui reste sans dépendance fournisseur).
  Lève la limitation documentée depuis la Phase 1 ("pas de détection de trous pendant les heures
  de séance... nécessite un calendrier de marché absent du dépôt") maintenant que
  `market_data.eodhd.calendar` existe. Distingue jour férié (jamais un "trou") de fermeture
  anticipée (reste un jour de séance).
- **Manifeste enrichi avec le vrai timeframe** : `market_data.resample.infer_timeframe_from_series()`
  calcule le code timeframe (ex. "M3") depuis l'écart médian entre bougies réellement chargées —
  jamais deviné, dérivé des données. Branché dans `optimizer_process.py` juste après le
  chargement, transmis à `job_store.finalize_job()`/`write_data_manifest()`. Validé sur le vrai
  `nasdaq_3m.csv` (détecte "M3" exactement) et par un troisième job réel
  (`job_phase11_timeframe_check_001`, `data_manifest.json` contient bien `"source_timeframe":
  "M3"`). `snapshot_id`/`content_hash`/`period_start`/`period_end` restent `None` — nécessitent
  un suivi structuré du provenance des données que ce pipeline (CSV brut) n'a pas encore.
### Data Center — diagnostic HTTP 403 IG puis validation réelle complète (2026-08-06, suite)

**Diagnostic sûr des erreurs IG (403 rencontré par l'utilisateur)** :
- `IgHttpError` porte désormais un `error_code` optionnel (uniquement le champ `errorCode` du
  corps de réponse IG, jamais le reste du corps — voir `market_data.ig.http_client.
  extract_ig_error_code()`, appliqué à TOUTES les réponses d'erreur : 400 (nouvelle
  `IgBadRequestError`), 401/403/404/429/5xx, et tout statut non listé (nouvelle
  `IgUnexpectedStatusError`, remplace l'ancien fallback `IgResponseError` qui n'avait pas de
  `status_code` — voir section dédiée ci-dessous, suite au diagnostic du HTTP 400 de `get_prices()`).
- `market_data/ig/error_codes.py` (nouveau) : `explain_ig_error_code()`, explications lisibles
  pour les codes confirmés (`error.security.api-key-invalid`, `error.security.invalid-details`,
  `error.public-api.exceeded-api-key-allowance`), message générique honnête pour tout code
  inconnu (jamais une explication devinée).
- `IgLoginResult`/`ConnectionTestResult` exposent `status_code`/`error_code`.
- `scripts/test_ig_connection.py` affiche désormais, en cas d'échec : `Statut HTTP`, `Code IG
  (errorCode)`, `Explication`, en plus du message existant — jamais un secret.
- 18 nouveaux tests (`tests/test_ig_error_codes.py`), y compris une preuve qu'un corps de
  réponse contaminé avec de faux CST/X-SECURITY-TOKEN ne laisse fuiter que `errorCode`.
- **Non commité à cette étape** (demande explicite de l'utilisateur : diagnostic d'abord).

**Validation réelle complète du connecteur IG démo, lecture seule (identifiants maintenant
configurés par l'utilisateur)** — `BACKTEST_IG_ENVIRONMENT=demo` vérifié avant tout appel,
`BACKTEST_RUN_LIVE_PROVIDER_TESTS=1` utilisé uniquement le temps du script (jamais persisté) :
- **Connexion** : réussie (`login()` OK, tokens CST/X-SECURITY-TOKEN en mémoire uniquement).
- **Comptes** (`get_accounts()`) : 3 comptes détectés — un compte **CFD préféré** (celui utilisé
  par défaut), un second CFD ("Barrières et Options"), un compte PHYSICAL ("Turbo24"). Compte
  CFD démo confirmé présent.
- **Account ID** : `BACKTEST_IG_ACCOUNT_ID` n'était pas configuré explicitement → découverte
  automatique réussie depuis la réponse de session (compte CFD préféré), conforme à
  `discover_account_id()`.
- **Recherche de marché** (`search_markets("Nasdaq 100")`) : 15 résultats, tous `instrumentType:
  INDICES`. EPIC retenu : `IX.D.NASDAQ.IFD.IP` ("US Tech 100 au comptant (100$)").
- **Détails de marché** (`get_market_details()`) : récupérés avec succès — nom, type `INDICES`,
  devise `USD`, statut `TRADEABLE`.
- **Historique récent** (`get_prices()`) : premier essai (`MINUTE_30`, fenêtre de 2h) en échec
  HTTP 400 — **cause identifiée et corrigée, voir section dédiée ci-dessous**.
- **Aucune écriture disque** : confirmé — aucun nouveau fichier dans le dépôt après la session
  (le connecteur IG ne contient aucun code d'écriture disque, conception déjà sans état
  persistant pour les tokens).
- **Tests hors ligne re-exécutés après la validation réelle** : 80/80 passent, aucune régression.

### Data Center — diagnostic et correction du HTTP 400 sur get_prices() (2026-08-06, suite)

**Cause exacte identifiée** : `get_prices()` utilisait `GET /prices/{epic}/{resolution}/{start}/
{end}` avec `VERSION: 2` — une forme historiquement documentée par la bibliothèque `trading-ig`
mais qui n'est pas la forme actuellement supportée par l'API IG (recoupement documentation
officielle + plusieurs sources indépendantes, voir plus haut : la forme actuelle est `GET
/prices/{epic}` avec `VERSION: 3` et des paramètres de requête `resolution`/`from`/`to`/`max`/
`pageSize`/`pageNumber`, dates au format `yyyy-MM-dd'T'HH:mm:ss`).

**Diagnostic méthodique** (`/superpowers` → `/debug`, `/grill-with-docs` — voir note sur ce
dernier ci-dessous) : Phase 1 (investigation) a comparé `get_prices()` (échoue) aux endpoints
`get_market_details()`/`search_markets()` (fonctionnent, tous deux en chemin simple sans
segments de date) ; Phase 2 a confronté la forme actuelle du code à la documentation officielle
IG (bloquée par 403/429 côté labs.ig.com, contournée via recherche web ciblée + code source de
la bibliothèque de référence `trading-ig`) ; Phase 3 a formé une hypothèse unique (forme
d'endpoint obsolète) testée par le plus petit changement possible.

**Correction (TDD, `/tdd`)** :
- `get_prices()` (`market_data/ig/client.py`) utilise désormais `GET /prices/{epic}` (VERSION 3).
  Signature devenue `get_prices(epic, resolution, *, start=None, end=None, max_points=None)` —
  `start`/`end` optionnels (nécessaire pour permettre une requête sans plage de dates, comme
  demandé pour le premier test réel), format de date changé de `%Y/%m/%d %H:%M:%S` (ancien,
  toujours utilisé pour PARSER `snapshotTime` dans la réponse, inchangé) à `%Y-%m-%dT%H:%M:%S`
  pour les paramètres `from`/`to` de la REQUÊTE (jamais mélangés, deux constantes distinctes).
- Validations ajoutées avant tout appel réseau : résolution reconnue (déjà présent),
  `max_points` entier strictement positif, `start < end` si les deux fournis, `end` pas dans le
  futur.
- `IgPricesResult` expose désormais `status_code`/`error_code` (comme `IgLoginResult`/
  `ConnectionTestResult`) — corrige un gap trouvé par `/code-review` (deux sous-agents parallèles
  Standards/Spec) : la fonction même à l'origine du diagnostic HTTP 400 n'exposait pas ces
  champs à son appelant, et le test associé était tautologique (`"x" in msg or msg`, toujours
  vrai) — corrigé avec une assertion réelle sur `status_code`/`error_code`.
- `/simplify` (substitut de `/kaizenkaizen`, non reconnu dans cette installation — voir note) :
  `_error_details()` généralisé en `isinstance(exc, IgHttpError)` plutôt qu'un `getattr` par nom
  d'attribut ; validation `max_points` extraite en `_is_positive_int()` nommé et lisible.
- **27 nouveaux tests** (`tests/test_ig_http_client.py` : extraction `errorCode` sur 400 et tout
  statut non listé ; `tests/test_ig_client.py` : nouvelle forme v3, validations, non-fuite de
  secrets pour `get_prices()` spécifiquement).

**Validation réelle (une seule tentative, comme demandé)** : `get_prices("IX.D.NASDAQ.IFD.IP",
"MINUTE", max_points=5)` → **succès, 5 bougies reçues**, colonnes canoniques
(`time/open/high/low/close/volume`) + `open_bid/open_ask/high_bid/high_ask/low_bid/low_ask/
close_bid/close_ask` conservés séparément, timestamps chronologiques croissants, aucune valeur
fabriquée. `BACKTEST_RUN_LIVE_PROVIDER_TESTS` scopé à cette seule commande, jamais persisté.

**Note sur les skills demandés** : `/grill-with-docs` s'est révélé conçu pour une interview
interactive de modélisation de domaine (`/domain-modeling`, production d'ADR), pas pour une
vérification autonome de documentation API externe — utilisé tel quel puis complété directement
par recherche web ciblée (WebFetch/WebSearch) pour obtenir la confirmation documentaire réelle.
`/kaizenkaizen` n'est pas reconnu dans cette installation ; `/simplify` (skill disponible, même
finalité) a été utilisé à la place.

Le connecteur IG est maintenant validé en conditions réelles pour les 7 fonctions de lecture :
`login()`, `logout()`, `get_accounts()`, `discover_account_id()`, `search_markets()`,
`get_market_details()`, `get_prices()`.

---

## 3. Système de job directory (implémenté)

Chaque job CLI crée `results/job_YYYYMMDD_HHMMSS_xxxx/` avec :

```
results/job_xxx/
├── progress.json          # Progression temps réel (polling Streamlit ou CLI)
├── config_used.json       # Config relative (portable, pas de C:\Users\...)
├── results.csv            # Résultats cumulés de toutes les combos testées
├── tested.json            # Hashs des combos déjà testées (reprise)
├── meta.json              # Résultat interne complet
├── metrics.json           # KPI synthétiques
├── best_strategies.csv    # Top 100 stratégies
├── report.html            # Rapport standalone (pas de dépendances externes)
├── logs.txt               # Journal d'exécution
├── job_notes.json         # Annotation utilisateur optionnelle, séparée des résultats
├── job_decisions.json     # Historique optionnel des décisions et actions utilisateur
└── archive.zip            # 7 fichiers bundlés (exclut tested.json, meta.json, stop.flag)
```

**Compatibilité descendante** : `optimization_store.py` garde toujours `job_dir=None` en défaut — l'ancien mode `optimization_history/` fonctionne encore.

---

## 4. Comment lancer le projet

### Interface Streamlit (Windows)

```
Double-clic sur lancer_app.bat
→ http://localhost:8501
```

Ou en terminal :
```bash
.venv\Scripts\python.exe -m streamlit run app.py
```

### CLI sans interface

```bash
.venv\Scripts\python.exe run_job.py --config optimization_history/mon_run.config.json
.venv\Scripts\python.exe run_job.py --config mon_run.config.json --workers 4 --max-rows 50000
```

**Important** : toujours utiliser `.venv\Scripts\python.exe`, pas `python` (le Python système n'a pas les packages nécessaires).

---

## 5. Règles à respecter

- **Ne jamais mettre `C:\Users\...` dans un fichier JSON** — utiliser des chemins relatifs POSIX.
- **`progress.json` doit garder DEUX jeux de clés** : anciens (`completed`, `total_combinations`) ET nouveaux (`combinations_done`, `combinations_total`, `job_id`, `job_dir`) pour la compatibilité Streamlit.
- **`run_id == job_id`** en V1 pour la simplicité.
- **Pas de dépendances CDN dans `report.html`** — le rapport doit fonctionner hors ligne (CSS inline).
- **`archive.zip` contient exactement 7 fichiers** : exclut `tested.json`, `meta.json`, `stop.flag`.
- **Téléchargements job** : un bouton n'est affiché que si le fichier existe, est non vide et lisible. Les fichiers absents restent visibles comme `Indisponible`, sans bouton cassé.
- **Régénération archive** : `job_artifacts.ensure_job_archive()` recrée `archive.zip` si elle est absente, vide, invalide ou plus ancienne que les fichiers source.
- **`BACKTEST_BASE_DIR`** : variable d'environnement pour déploiement serveur (Linux). La fonction `_base_dir()` dans `optimization_store.py` la gère.
- **Données multi-actifs** : préférer `data/{ASSET}/{TIMEFRAME}/*.csv`; garder `nasdaq_3m.csv` comme fallback legacy pour `NASDAQ/M3`.
- **Import CSV Streamlit** : sauvegarde uniquement si `data_validator.py` ne remonte pas d'erreur bloquante. Les avertissements n'empêchent pas la sauvegarde.
- **Maintenance locale** : simulation obligatoire avant suppression. Ne supprime jamais un job actif, ni `nasdaq_3m.csv`, `.env`, `.venv`, `.git`, `.streamlit/credentials.toml`, `app_corrupted_backup.py`.
- **Chemins nettoyables** : uniquement `results/job_xxx/` terminés ou en erreur, et dossiers de test `data/PWCSV.../`. Les vrais CSV utilisateur sont dans une zone danger désactivée.
- **Accueil Streamlit** : `dashboard.py` calcule le résumé global sans dépendre de Streamlit. L'onglet `Accueil` affiche disque, jobs, données, alertes et actions rapides.
- **UX Streamlit** : préférer les composants Streamlit natifs. Les nouveaux helpers d'affichage restent dans `ui_components.py` et ne doivent pas contenir de logique métier.
- **Lancement optimisation** : Streamlit et `job_launcher.py` refusent de créer un nouveau job si `optimization_store.list_active_jobs()` trouve déjà un job actif.
- **Arrêt propre** : `stop.flag` reste le signal d'arrêt. Pendant que le flag existe sur un job `running` ou `benchmarking`, le job reste considéré actif et l'UI affiche `Arrêt demandé`.
- **Relance / duplication** : `Relancer même config` clone `config_used.json` dans un nouveau job. `Dupliquer config` charge les widgets de l'onglet Configuration sans lancer de job.
- **Comparaison jobs** : l'onglet `Optimisation > Comparaison de jobs` utilise `job_comparison.py`. Il lit d'abord `metrics.json`, puis retombe sur `meta.json` et `results.csv` pour les anciens jobs.
- **Comparabilité** : afficher un avertissement si stratégie, actif, timeframe ou fichier de données diffèrent. La page reste lisible et ne bloque pas les anciens jobs incomplets.
- **Annotations jobs** : `job_notes.json` contient uniquement `status`, `note`, `tags`, `updated_at`. Ne jamais écrire ces données dans `config_used.json`, `metrics.json` ou `results.csv`.
- **Journal des décisions** : `job_decisions.json` est append-only et séparé des résultats. Il trace les changements de statut, note, tags, les exports, les duplications, les relances et les changements de seuils liés au Champion sélectionné.
- **Écriture du journal** : chaque événement contient `timestamp`, `event_type`, `category`, `message`, `old_state` et `new_state`. L'écriture utilise un fichier temporaire puis `os.replace()`.
- **Compatibilité journal** : un job ancien sans `job_decisions.json`, avec un fichier absent ou illisible, reste affichable avec un historique vide.
- **Archive et annotations** : `job_notes.json` et `job_decisions.json` restent volontairement hors de `archive.zip`, qui conserve exactement ses 7 artefacts calculés.
- **Classements disponibles** : `Champion`, `Favori`, `À revoir`, `Rejeté`. Les anciens jobs sans `job_notes.json` sont affichés comme non classés.
- **Rapport Champion** : la sous-page `Optimisation > Rapport Champion` ne lit que les artefacts existants. Elle n'écrit jamais dans `config_used.json`, `metrics.json`, `results.csv` ou les autres résultats calculés.
- **Exports Rapport Champion** : Markdown et HTML sont générés en mémoire pour `st.download_button`. Ils ne sont pas écrits dans le dossier job et ne sont pas ajoutés à `archive.zip`.
- **Historique Rapport Champion** : le Rapport Champion et la section Champions/Favoris affichent le journal avec filtres annotations, exports, relances/duplications et réglages. Les exports Markdown/HTML incluent aussi cet historique.
- **Roadmap Champion** : la sous-page `Optimisation > Roadmap Champion` liste les jobs annotés `Champion`, `Favori`, `À revoir` et `Rejeté`. Elle calcule un statut de maturité en lecture seule : `À retester`, `À valider sur plus d'historique`, `Candidat sérieux`, `Données incomplètes`, `Rejeté`.
- **Filtres Roadmap** : annotation, maturité, actif/timeframe et tag. Les actions réutilisent les chemins existants : Rapport Champion pour Champion/Favori, Résultats, duplication, relance si aucun job actif, modification annotation/note/tags.
- **Accueil Roadmap** : l'Accueil affiche le nombre de candidats sérieux, à retester et rejetés, plus la prochaine action prioritaire.
- **Pipeline Champion** : la sous-page `Optimisation > Pipeline Champion` affiche les jobs annotés par étapes : `Détecté`, `Favori`, `Champion`, `À retester`, `Retest lancé`, `Candidat sérieux`, `Prêt validation avancée`, `Rejeté`.
- **Règles Pipeline** : le classement combine annotation, maturité Roadmap, historique `job_decisions.json`, retest lancé, preset et tags. `Test rapide local`, trop peu de trades, trop peu de combinaisons ou demande de plus d'historique poussent vers `À retester`; un événement `retest_plan_launched` pousse vers `Retest lancé`.
- **Actions Pipeline** : chaque carte propose Rapport Champion, Plan de retest, Résultats, duplication de config et relance si aucun job actif. Ces actions réutilisent les chemins existants et ne modifient jamais les résultats bruts.
- **Chaîne de retest Pipeline** : `retest_links.py` relie un Champion/Favori source à ses retests en lecture seule. Il lit `retest_plan_source_job_id` dans la config clonée du retest et `new_job_id` dans l'événement `retest_plan_launched` du `job_decisions.json` source, puis affiche statut, score, trades et drawdown si disponibles.
- **Compatibilité retests anciens** : si le retest ou ses métriques sont absents, l'UI affiche `non renseigné` ou `ancien job` sans crash. `config_used.json`, `metrics.json` et `results.csv` restent intacts.
- **Accueil Pipeline** : l'Accueil résume les jobs suivis, candidats sérieux, jobs à retester et rejetés, avec un raccourci vers le Pipeline.
- **Mode démo UI** : `demo_data.py` crée un `results/` factice dans le dossier temporaire système (`%TEMP%/backtest_nasdaq_demo_ui` sous Windows). Streamlit l'active depuis l'Accueil en pointant temporairement `BACKTEST_BASE_DIR` vers ce dossier, puis le restaure à la désactivation.
- **Isolation démo** : le mode démo n'écrit jamais dans les vrais `results/`, `history/` ou `nasdaq_3m.csv`. Il sert uniquement à tester Accueil, Historique, Résultats, Comparaison, Rapport Champion, Roadmap, Pipeline, Plan de retest et les liens Champion → retest avec des données factices.
- **Lancements en démo** : les boutons de lancement, relance et lancement de retest sont désactivés en mode démo UI pour éviter tout vrai backtest. Les actions de lecture, duplication, rapport, filtres et téléchargements restent disponibles.
- **Plan de retest** : la sous-page `Optimisation > Plan de retest` sélectionne un Champion/Favori terminé et propose un preset, `max_rows`, `max_combinations`, workers et benchmark selon checklist, preset, trades, score, drawdown et données.
- **Actions retest** : `Dupliquer vers Configuration` charge une config clonée avec les limites proposées. `Lancer le retest` crée un nouveau job sans écraser l'ancien si aucun job actif n'existe. `Ajouter note/tag` complète `job_notes.json` et le journal trace les actions dans `job_decisions.json`.
- **Règles retest** : `Test rapide local` monte vers `Test moyen`; trop peu de trades pousse vers plus d'historique; drawdown élevé reste prudent avec tag `drawdown élevé`; données incomplètes demandent vérification/import; candidat sérieux relance sur plus d'historique avec limite contrôlée.
- **Checklist Champion** : 8 critères sont calculés en lecture seule : trades, score, drawdown, win rate, métriques essentielles, preset, combinaisons et période/volume de données. Statuts possibles : `Validé`, `À surveiller`, `Bloquant`, `Inconnu`.
- **Verdict Champion** : priorité aux métriques essentielles manquantes (`Données incomplètes`), puis aux critères bloquants (`Insuffisant`). Un job n'est `Candidat sérieux` que si les 8 critères sont validés ; sinon il reste `Prometteur mais à retester`.
- **Seuils checklist** : 30 trades, score strictement positif, drawdown à surveiller dès 20 % et bloquant dès 30 %, win rate exploitable dès 40 %, au moins 100 combinaisons, au moins 100 000 lignes ou 180 jours si l'information existe. `Test rapide local` reste non représentatif.
- **Réglages checklist** : `Optimisation > Rapport Champion > Réglages validation` modifie les seuils globaux. Ils sont enregistrés atomiquement dans `settings/champion_validation.json`, jamais dans un job. Le fichier est ignoré par Git.
- **Tolérance réglages** : si `settings/champion_validation.json` est absent, illisible, invalide ou incohérent, l'application utilise tous les seuils par défaut sans bloquer l'affichage.
- **Propagation des seuils** : checklist, points forts/faibles, alertes, décision et exports Markdown/HTML utilisent la même configuration chargée.
- **Recommandations Champion** : règles pédagogiques simples, pas une validation financière. Zéro trade ou score nul/négatif entraîne un rejet en l'état ; moins de 30 trades recommande un test plus long ; un drawdown supérieur ou égal à 20 % recommande de dupliquer puis ajuster la config ; des métriques essentielles absentes imposent l'observation.
- **Téléchargements UX** : l'historique n'affiche plus de `download_button` pour chaque job afin d'éviter les sources Streamlit invalidées. Le bouton `Fichiers job` ouvre le job, et les vrais téléchargements restent dans l'onglet `Fichiers job`.

---

## 6. Dépendances

```bash
# Windows (développement)
pip install -r requirements.txt

# Linux/serveur
pip install -r requirements-server.txt
```

---

## 7. Fichiers à ne jamais envoyer sur GitHub

| Fichier / Dossier         | Raison                                         |
|---------------------------|------------------------------------------------|
| `nasdaq_3m.csv`           | Fichier volumineux de données                  |
| `data/**/*.csv`           | Historiques multi-actifs/timeframes volumineux |
| `.venv/`                  | Environnement virtuel Python                   |
| `optimization_history/`   | Résultats de runs (générés localement)         |
| `results/`                | Jobs CLI (générés localement)                  |
| `history/`                | Cache DataFrame compressé                      |
| `.streamlit/credentials.toml` | Peut contenir des identifiants Streamlit Cloud |
| `*.log`                   | Logs                                           |
| `.env`, `.env.*`          | Variables d'environnement sensibles            |
| `__pycache__/`            | Cache Python compilé                           |

---

## 8. État du projet au 2026-05-24

### Fait et validé

- [x] Moteur de backtest et scoring
- [x] Stratégie `perfect_revolution_v1.py`
- [x] Interface Streamlit (`app.py`) — fonctionnelle
- [x] Optimiseur parallèle (`optimizer_process.py`) avec `ProcessPoolExecutor`
- [x] Système de job directory (`results/job_xxx/`) complet
- [x] `optimization_store.py` avec `job_dir` optionnel (compatibilité descendante)
- [x] `job_store.py` : metrics, best_strategies, report HTML, logs, archive zip
- [x] `run_job.py` CLI : génération job_id, subprocess, polling progression, résumé final
- [x] `app.py` : liste les jobs `results/job_xxx/`, permet de consulter un job et de télécharger ses artefacts disponibles
- [x] `job_launcher.py` : création/lancement partagé des jobs `results/job_xxx/` pour Streamlit et CLI
- [x] `app.py` : le bouton d'optimisation lance maintenant un job `results/job_xxx/` au lieu de l'ancien mode `optimization_history/`
- [x] Progression jobs : `progress_pct` compte maintenant les combinaisons traitées (`completed + failed`), donc les filtres/rejets font avancer la barre
- [x] Reconnexion Streamlit : l'interface détecte les jobs actifs depuis `results/job_xxx/progress.json` et propose de reprendre le suivi après refresh
- [x] Reconnexion Streamlit durcie : les vieux jobs `created` ne sont plus considérés comme actifs ; les jobs `running` avec `stop.flag` restent visibles comme `Arrêt demandé`
- [x] UX benchmark : l'onglet Progression affiche un état dédié pendant `benchmarking` au lieu d'un trompeur `0/0`
- [x] UX débutant : Progression/Résultats/Historique utilisent des statuts lisibles, verdicts simples et messages explicatifs
- [x] UX progression : auto-actualisation sûre toutes les ~2,5 s pendant `created`, `benchmarking` et `running`
- [x] UX Historique/Résultats : cartes jobs rendues avec composants Streamlit natifs, mode rapide affiché comme test technique, top résultats simplifié sans table filtrée répétitive
- [x] Mode validation rapide : la limite 12 combinaisons est maintenant appliquée à l'exécution via `max_combinations`, pas seulement à l'affichage
- [x] Windows : `progress.json` garde l'écriture atomique avec retry court sur `PermissionError` / `WinError 5`
- [x] Historique Runs : le bouton `Voir` charge le job, force l'onglet `Résultats` et ne nécessite plus de second clic
- [x] Validation Playwright Edge : job rapide `job_20260614_190837_032a` terminé, 12/12 combinaisons, pas de `WinError`, téléchargements visibles
- [x] Données multi-actifs/timeframes : squelette `data/NASDAQ/M3/`, résolution CSV via `path_resolver.py`, fallback legacy `nasdaq_3m.csv`
- [x] Import CSV Streamlit : onglet `Données`, validation qualité via `data_validator.py`, sauvegarde dans `data/{ASSET}/{TIMEFRAME}/`
- [x] Téléchargements jobs : fichiers vérifiés avant bouton, `archive.zip` régénérée si nécessaire, `download_button` configuré sans rerun
- [x] Maintenance locale : onglet `Maintenance`, simulation de nettoyage, protection jobs actifs, nettoyage séparé des dossiers `data/PWCSV.../`
- [x] Tableau de bord d'accueil : KPIs disque/jobs, données disponibles, alertes simples et actions rapides vers Données/Optimisation/Historique/Maintenance
- [x] Nettoyage UX ciblé : onglets manuels clarifiés, Accueil guidé, Données en parcours étape par étape, Optimisation avec récapitulatif avant lancement, Maintenance avec zones danger plus explicites
- [x] Validation Playwright UX Edge : actions rapides testées, job rapide `job_20260615_184659_a272` terminé, 12/12 combinaisons, téléchargements OK, aucune erreur console
- [x] Tests validés : 12 combos / 1 worker et 42 combos / 2 workers → 7/7 fichiers présents
- [x] Dépôt GitHub créé (privé) : https://github.com/crashboom34/backtest-nasdaq-revolution
- [x] Préréglages d'optimisation Streamlit : `Test rapide local`, `Test moyen`, `Optimisation complète`, `Serveur puissant`, `Personnalisé`
- [x] Sécurité lancement jobs : blocage des doubles lancements, affichage job actif, arrêt propre visible, relance/duplication de config
- [x] Comparaison de jobs : sélection de 2 à 5 jobs terminés, tableau métriques, meilleur score, actions et compatibilité legacy
- [x] Favoris / champions : classement, note et tags par job, filtres, sous-page dédiée, affichage Résultats/Historique/Comparaison/Accueil
- [x] Rapport Champion : fiche synthèse Champion/Favori, forces/faiblesses, alertes, décision recommandée, fichiers et actions
- [x] Exports Rapport Champion : téléchargements Markdown et HTML générés en mémoire, sans dépendance externe
- [x] Checklist Champion : 8 critères, 4 statuts, verdict global et recommandation intégrés à l'UI et aux exports
- [x] Seuils Champion configurables : formulaire Streamlit, sauvegarde globale, reset défaut et repli robuste
- [x] Pipeline Champion : étapes visuelles, cartes par job, actions rapides et résumé Accueil
- [x] Mode démo UI : jobs factices temporaires, bannière visible, liens Champion → retest simulés et lancements désactivés
- [x] Data Center — socle local (2026-08-05) : schéma canonique (ADR 0002), port `MarketDataSource`, adaptateur CSV local, catalogue JSON, génération de timeframes dérivés (ADR 0003), cache disque des dérivés, statut source/calculable/en cache, contrôle qualité basique, emplacement générique pour les futures clés API, assembleur de synthèse
- [x] Data Center — port branché (2026-08-05, suite) : `engine.load_data_from_source()` additif (résultat identique à `load_data()`, vérifié y compris sur le vrai `nasdaq_3m.csv`), sous-onglet Streamlit "Data Center (aperçu)" dans l'onglet Données, validé avec Playwright/Edge sur les vraies données locales sans erreur ni modification
- [x] Data Center — identifiants IG typés (2026-08-06) : `EodhdCredentials`/`IgCredentials`/`ProviderCredentialStatus`, mot de passe IG env-only, `tests/conftest.py` isole la suite des vraies variables d'environnement
- [x] Data Center — connecteur REST EODHD (2026-08-06) : package `market_data/eodhd/` complet (config, client HTTP retry/backoff, fenêtrage intraday, normalisation, stockage brut+Parquet sous `BACKTEST_DATA_DIR`), 67 tests hors ligne, `scripts/test_eodhd_connection.py`. Endpoints/limites confirmés via le MCP EODHD + documentation officielle, jamais devinés.
- [x] Data Center — unités calendaires W1/MO1 (2026-08-06, ADR 0004) : `market_data.resample` dérive semaine/mois depuis une source D1 uniquement, ancrage lundi-dimanche/mois civil UTC.
- [x] Data Center — catalogue/journal de synchro EODHD (2026-08-06) : `list_normalized_snapshots()`, `list_raw_snapshots()`, `disk_usage_summary()`, journal de synchronisation plafonné.
- [x] Data Center — connecteur IG démo lecture seule (2026-08-06) : package `market_data/ig/` complet, base URL démo non paramétrable, aucune fonction de trading, 52 tests hors ligne (identifiants IG absents sur cette machine, tout testé via fixtures), `scripts/test_ig_connection.py`.
- [x] Data Center — test réel EODHD exécuté (2026-08-06) : connexion + téléchargement de 3 bougies AAPL.US réussis contre la vraie API.
- [x] Data Center — page Streamlit étendue (2026-08-06) : sections EODHD/IG/stockage dans `ui_data_center.py`, boutons de test réels, validés avec Playwright/Edge (clic réel → "Connexion EODHD réussie.", aucune erreur console, aucun secret affiché).
- [x] Data Center — façade de compatibilité + manifeste, branchement réel (2026-08-06, autorisation explicite) : `optimizer_process.py`/`optimizer.py` chargent via `engine.load_data_from_source(SingleFileCsvMarketDataSource(...))`, équivalence prouvée sur le vrai `nasdaq_3m.csv` (`pd.testing.assert_frame_equal`), 2 jobs réels exécutés avec succès. `job_store.write_data_manifest()` branché dans `finalize_job()` — chaque nouveau job écrit désormais `data_manifest.json`, sans casser l'invariant 7-fichiers d'`archive.zip`.
- [x] Data Center — calendrier de marché, amorce (2026-08-06) : `EodhdClient.get_exchange_details()` + `market_data/eodhd/calendar.py` (`ExchangeCalendar`, `is_trading_day()`), basé sur un échantillon réel. Pas encore consommé par `market_data.resample`.
- [x] Data Center — catalogue unifié (2026-08-06) : `market_data/unified_catalog.py` combine CSV local + EODHD, nouvelle section dans `ui_data_center.py`.
- [x] Data Center — détection de trous calendaire (2026-08-06) : `market_data.quality.detect_missing_trading_days()`, additif, basé sur `market_data.eodhd.calendar`.
- [x] Data Center — manifeste enrichi avec le timeframe réel (2026-08-06) : `market_data.resample.infer_timeframe_from_series()`, branché dans `optimizer_process.py`, validé sur le vrai `nasdaq_3m.csv` et par job réel (`source_timeframe: "M3"` dans `data_manifest.json`).
- [x] Data Center — diagnostic sûr des erreurs IG (2026-08-06) : `IgHttpError.error_code`, `extract_ig_error_code()`, `market_data/ig/error_codes.py`, script enrichi. Non commité (diagnostic demandé avant commit).
- [x] Data Center — **validation réelle complète du connecteur IG démo, les 7 fonctions de lecture** (2026-08-06) : connexion, comptes (CFD détecté), account ID auto-découvert, recherche "Nasdaq 100" → EPIC `IX.D.NASDAQ.IFD.IP`, détails de marché, **et `get_prices()` corrigé (v3) puis validé avec 5 bougies réelles reçues et normalisées**. Aucune écriture disque, aucun ordre, 99 tests hors ligne toujours verts.

### Reste à faire (prochaines étapes suggérées)

- [ ] Tester manuellement le lancement complet depuis Streamlit avec le nouveau système de jobs
- [ ] Documenter la source / format exact de `nasdaq_3m.csv` (inclure la présence des colonnes `tick_volume`/`spread`, découverte le 2026-08-06)
- [ ] Brancher plus tard MT5 ou une autre source d'import vers `data/{ASSET}/{TIMEFRAME}/`
- [ ] Ajouter plus tard une gestion avancée des formats CSV exotiques si nécessaire (fuseaux horaires spécifiques, colonnes renommées non standards)
- [ ] Éventuellement : déploiement serveur Linux avec `BACKTEST_BASE_DIR`
- [ ] `snapshot_id`/`content_hash`/`period_start`/`period_end` restent `None` dans `data_manifest.json` — nécessitent un suivi structuré de la provenance des données (asset/timeframe/snapshot), hors de portée sans redesign du format de config des jobs (aujourd'hui un chemin CSV brut)
- [ ] Intégrer le calendrier de marché (`market_data.eodhd.calendar`) dans `market_data.resample` pour un ancrage réel sur les séances (au lieu d'UTC pur) — la détection de trous existe déjà (`quality.detect_missing_trading_days`), l'ancrage du resampling lui-même reste à faire
- [x] ~~`get_prices()` IG renvoie HTTP 400~~ — **corrigé le 2026-08-06** (voir section dédiée : mauvaise version d'endpoint, passage à `/prices/{epic}` VERSION 3, validé avec 5 bougies réelles).
- [ ] Committer le diagnostic HTTP 403/error_code IG et la correction get_prices() (2026-08-06) — laissé en attente à la demande explicite de l'utilisateur
- [ ] Décider si Playwright doit devenir une dépendance permanente (`requirements.txt`) avec une suite de tests UI récurrente (utilisé ponctuellement pour la validation du 2026-08-05 et du 2026-08-06)
- [ ] Nettoyer (ou laisser, au choix) les jobs de test `results/job_phase11_facade_check_001/` et `results/job_phase11_manifest_check_001/` générés le 2026-08-06 pour valider le branchement réel — non supprimés automatiquement (voir Maintenance)

---

## 9. Problèmes connus

| Problème                              | Statut      | Note                                                      |
|---------------------------------------|-------------|-----------------------------------------------------------|
| `app.py` ne liste pas les jobs CLI    | Corrigé     | Les jobs `results/job_xxx/` sont visibles dans l'onglet Optimisation > Historique Runs |
| `app.py` lance encore dans `optimization_history/` | Corrigé | Le lancement Streamlit passe par `job_launcher.py` et crée `results/job_xxx/` |
| Progression Streamlit bloquée à 0% quand les combos sont filtrées | Corrigé | `optimizer_process.py` écrit `combinations_done = completed + failed` et calcule `progress_pct` sur ce total traité |
| Interface trop technique pour débutant | En amélioration | Statuts métiers, verdicts et messages d'explication ajoutés dans l'onglet Optimisation |
| Mode rapide affiche 12 combos mais en exécute plus | Corrigé | `app.py` enregistre `max_combinations=12`, `optimizer_process.py` calcule le total effectif, `optimizer.py` limite réellement les combinaisons planifiées |
| `PermissionError` Windows sur `progress.json` | Corrigé | `optimization_store.atomic_write_json()` retente `os.replace()` avec backoff court puis remonte une erreur explicite si le verrou persiste |
| Bouton `Voir` nécessite parfois un second clic | Corrigé | Les sous-onglets Optimisation utilisent `st.tabs(..., key=..., on_change="rerun")`; `Voir` force `📊 Résultats` avant le rerun |
| Python système sans packages          | Connu       | Toujours utiliser `.venv\Scripts\python.exe`              |
| `history/` pas dans .gitignore        | Corrigé     | Ajouté dans .gitignore                                    |
| `.streamlit/credentials.toml` suivi  | Corrigé     | Ajouté dans .gitignore + à retirer du suivi Git            |
| Benchmark très lent sur PC local (110 s/bt avec historique complet) | Corrigé | Mode validation rapide reconfiguré : `max_rows=20 000`, `benchmark_n_sample=1` |
| Aucun aperçu global au lancement | Corrigé | Onglet `Accueil` ajouté, calculs isolés dans `dashboard.py` et testés |
| Interface encore trop peu guidée pour débutant | En amélioration | Helpers `ui_components.py`, messages plus pédagogiques et parcours principaux clarifiés |
| Double clic sur lancement optimisation | Corrigé | Garde-fou UI + refus dans `job_launcher.py` si un job actif existe |
| Stop demandé peu visible | Corrigé | `stop.flag` maintient un état `Arrêt demandé` dans les cartes actives jusqu'à consommation par le process |
| Comparaison difficile entre optimisations | Corrigé | Sous-page native Streamlit avec score, trades, win rate, drawdown, durée, combinaisons et contexte des données |
| Aucun moyen de conserver un jugement humain sur un job | Corrigé | `job_notes.json` séparé, statuts Champion/Favori/À revoir/Rejeté, tags et note libre |
| Difficile de décider quoi faire d'un Champion/Favori | Corrigé | Rapport Champion natif avec contexte, métriques, alertes et recommandation pédagogique |
| Rapport Champion difficile à partager | Corrigé | Exports Markdown et HTML téléchargeables, autonomes et générés en mémoire |
| Champion marqué sans preuve de robustesse | Corrigé | Checklist explicite avec seuils, verdict global et recommandations de retest |
| Seuils Champion figés dans le code | Corrigé | Réglages globaux persistants avec valeurs par défaut et reset depuis Streamlit |
| Décisions Champion non traçables dans le temps | Corrigé | Journal atomique par job, affiché dans l'UI et inclus dans les exports |
| Difficile de savoir quoi faire ensuite avec plusieurs Champions/Favoris | Corrigé | Roadmap Champion avec maturité, filtres, prochaine action et résumé Accueil |
| Retester un Champion prometteur demande trop de réglages manuels | Corrigé | Plan de retest qui propose les limites, peut dupliquer la config ou lancer un nouveau job |
| Suivi visuel de l'avancement Champion absent | Corrigé | Pipeline Champion avec étapes, cartes, actions rapides et résumé Accueil |

---

## 11. Préréglages d'optimisation Streamlit

L'onglet **Optimisation > Configuration** propose maintenant un sélecteur de préréglage pour éviter de régler les limites à la main.

| Préréglage | `max_rows` | `max_combinations` | `n_workers` | `benchmark_n_sample` | Note |
|------------|------------|--------------------|-------------|----------------------|------|
| `Test rapide local` | 20 000 | 12 | 1 | 1 | Remplace l'ancien mode validation rapide |
| `Test moyen` | 100 000 | 100 | 2 | 3 | Test local plus représentatif |
| `Optimisation complète` | None | None | choisi par l'utilisateur | 5 | Peut être long |
| `Serveur puissant` | None | limite élevée configurable | workers élevés configurables | 5 | Prévu pour serveur |
| `Personnalisé` | manuel | manuel | manuel | manuel | L'utilisateur garde le contrôle |

Chaque nouveau job enregistre dans `config_used.json` et `meta.json` :

- `preset_name`
- `preset_description`
- `max_rows`
- `max_combinations`
- `benchmark_n_sample`
- `n_workers`

Compatibilité : les anciens jobs sans `preset_name` restent lisibles et sont affichés comme `Ancien job`. Les anciens jobs avec `quick_validation_mode=true` sont reconnus comme `Test rapide local`.

**Important** : les résultats obtenus avec `Test rapide local` ne sont **pas représentatifs** d'une vraie optimisation. Ce mode sert uniquement à vérifier que le pipeline fonctionne (benchmark → running → fichiers générés).

Dernière validation automatisée avant cette évolution :

- Compilation : `.\.venv\Scripts\python.exe -m py_compile app.py optimization_store.py optimizer_process.py job_store.py job_launcher.py run_job.py path_resolver.py optimizer.py`
- Tests : `.\.venv\Scripts\python.exe -m pytest --basetemp <temp dédié> tests\test_optimization_store.py tests\test_job_launcher.py tests\test_job_store.py` → 35 passed
- Playwright Edge (`channel: "msedge"`, sans Chromium téléchargé) → rapport `C:\Users\Mira Alexandre\AppData\Local\Temp\backtest-playwright-core\captures\visual-fix-final-report.json`

---

## 10. Commandes utiles

```bash
# Lancer l'interface
lancer_app.bat

# Lancer un job CLI
.venv\Scripts\python.exe run_job.py --config optimization_history/XXX.config.json

# Voir les jobs récents
dir results\

# Vérifier le suivi Git
git status
git ls-files optimization_history/
git ls-files history/

# Retirer credentials.toml du suivi Git (sans le supprimer localement)
git rm --cached .streamlit/credentials.toml
```

---

## 12. PH0-OCI-01 — Validation Linux réelle sur OCI (2026-08-14)

**Statut : PH0-OCI-01 clôturable.** Détail complet :
`docs/architecture/LINUX_PORTABILITY_REPORT.md` §15 ; ticket synchronisé :
`docs/roadmap/EPICS_AND_TICKETS.md` → `PH0-OCI-01`.

- **Environnement réel** : instance OCI `backtester-ph0-oci-01` (`VM.Standard.E4.Flex`, x86_64,
  **temporaire** — `VM.Standard.A1.Flex` visé pour la production a échoué "Out of capacity" à
  Marseille, décision de shape final encore ouverte, voir `PH0-OCI-10`), Ubuntu 24.04.4 LTS,
  Python 3.12.3, glibc 2.39. Dépendances `requirements-server.txt` installées réellement (51
  paquets, aucune compilation depuis les sources, `pip check` sans conflit).
- **Suite de tests** : `pytest` **546/546 passed** réellement sous Linux, avec les vraies
  données (`nasdaq_3m.csv` transféré depuis Windows, SHA256 identique des deux côtés). Inclut
  `tests/test_job_resume.py` (exécute réellement `optimizer_process.py` en subprocess, job de
  2 combinaisons + job de reprise) — couvre en conditions réelles Linux la reprise
  d'optimisation (`resume_run_id`), pas seulement le pipeline de base.
- **Streamlit** : `lancer_app.sh` exécuté réellement (`./lancer_app.sh`, mode Git `100755`),
  mode headless réel confirmé, HTTP 200 sur `/_stcore/health` et sur `/`, arrêt propre. Point de
  durcissement noté pour plus tard (pas un blocage) : Streamlit écoute par défaut sur `*:8501`,
  mais la Security List OCI garde ce port fermé — aucune exposition publique réelle.
- **Backtest comparatif Windows ↔ OCI** : `NASDAQ Perfect Revolution V1.1` + `DEFAULT_PARAMS`
  sur `nasdaq_3m.csv` complet (1 000 000 lignes), une seule exécution de chaque côté. **Verdict
  IDENTIQUE** : 114 trades, 999 869 points d'equity, toutes les métriques identiques valeur par
  valeur. Seul écart trouvé : terminateur de ligne CSV cosmétique (`pandas.to_csv()` /
  `os.linesep`, CRLF Windows vs LF Linux) — aucune différence numérique après normalisation.
- **Pour une future conversation** : PH0-OCI-01 n'a plus de critère ouvert — son blocage
  (`Blocked by: PH0-OCI-01`) sur les tickets `PH0-OCI-02`, `PH0-OCI-04`, `PH0-OCI-05`,
  `PH0-OCI-06`, etc. (voir `docs/roadmap/EPICS_AND_TICKETS.md`) est levé ; leur propre lecture et
  leurs propres critères restent à évaluer individuellement avant de les engager. Le shape de VM
  utilisé ici (`E4.Flex`) est temporaire, pas une décision finale de production.

## 13. DATA FOUNDATION — `GATE DATA = PASS` (2026-08-15)

**Statut : `AF-DATA-01`→`AF-DATA-04A` DONE, `GATE DATA = PASS`.** Détail complet :
`docs/roadmap/EPICS_AND_TICKETS.md` §10 (verdict, garanties IMPLEMENTED/FUTURE, tech debt) ;
`docs/roadmap/MASTER_ROADMAP.md` §4 (`GATE DATA`).

- **Ce qui a été livré** : `market_data/content_hash.py` (SHA-256 streamé de l'artefact CSV
  source) ; propagation dans `data_manifest.json` (`content_hash`, `snapshot_id =
  "local_csv:sha256:<hash>"`, `period_start`/`period_end` du dataset source complet,
  `source_timeframe`) via `optimizer_process.py`→`job_store.finalize_job()`; compatibilité legacy
  prouvée (READ OLD / WRITE NEW, aucun backfill) ; contrôle de stabilité filesystem (taille +
  `mtime_ns`) entre chargement et hachage, détecte une mutation ordinaire sans second SHA-256.
- **Séquence réelle du gate** (non réécrite) : `AF-DATA-04` (audit) → **`NOT READY`** (2 critères
  manquants + 1 risque TOCTOU) → `AF-DATA-04A` (correctif minimal, même journée) → revalidation
  réelle → **`PASS`**.
- **Validation Perfect Revolution réelle (2026-08-15)** : `NASDAQ Perfect Revolution V1.1` +
  `DEFAULT_PARAMS`, `nasdaq_3m.csv` complet (1 000 000 lignes, lecture seule, taille/mtime
  inchangés), via le **vrai pipeline job** (pas un script isolé). **114 trades**, stats
  strictement identiques entre un calcul direct (`engine.load_data`+`run_backtest`) et le job
  pipeline réel — cohérent avec la référence historique `PH0-OCI-01` (114 trades, 999 869 points
  d'equity, verdict Windows/OCI déjà IDENTIQUE). Manifeste réel produit :
  `provider="local_csv"`, `content_hash` SHA-256 réel, `snapshot_id` cohérent,
  `period_start`/`period_end` réels, `source_timeframe="M3"`. Job non versionné
  (`results/job_gate_data_validation/`, hors dépôt Git, `results/` non suivi).
- **Ce qui reste `FUTURE`** (ne pas sur-promettre) : catalogue `DatasetVersion`
  persistant/interrogeable (PostgreSQL, ADR 0007 toujours `Proposed`) ; `DATA-ADVANCED`
  (Dukascopy, corporate actions, sync incrémental) ; sélection/lignes après filtrage
  (`opt_start_date`/`opt_end_date`/`max_rows`).

**TRACK R FOUNDATION = COMPLETE — committé et poussé (2026-08-15, `90e3e29c4c994c4bb54e571240a4121d5d2b16ee`,
`origin/master`)** — `Experiment`/`ResearchRun` (`research_run.py`, `AF-R-01`), capture
`git_sha`/`seed`/`engine_version` (`AF-R-02`), `DatasetSplitPlan`/`HoldoutAccessEvent`
(`dataset_split.py`, `AF-R-03`), plomberie partagée (`atomic_json_store.py`). **Pas de `GATE R`
officiel** — la roadmap ne définit aucun gate de ce nom (`GATE R` a été renommée `GATE DATA` en
revue `AF-RM-01-QC`, voir `MASTER_ROADMAP.md`) ; ce track reste consommateur de `GATE DATA`, pas
producteur d'un gate propre.

- **IMPLEMENTED/TESTED** : `Experiment` (durable, `hypothesis` optionnelle) ; `ResearchRun`
  (immuable, `dataset_snapshot_id` **obligatoire**, `git_sha` auto-détecté via le mécanisme
  `market_data.backtest_manifest._current_git_commit()` déjà existant, `seed` optionnel jamais
  inventé, `engine_version` partagé avec `BacktestManifest.ENGINE_VERSION`) ; `DatasetSplitPlan`
  (identifié par son propre `split_plan_id`, **cardinalité 1 snapshot -> N plans** — corrigée en
  revue après une première erreur de modélisation, voir `DOMAIN_MODEL.md` §12) ; `HoldoutAccessEvent`
  (append-only, `split_plan_id`+`dataset_snapshot_id`+`research_run_id` directs, `reason`
  obligatoire) ; `has_holdout_access_events()` (jamais `is_untouched()`) ; validation stricte des
  identifiants utilisés en chemin de fichier (`validate_portable_identifier()` — rejette, ne
  sanitise jamais, pour éviter toute collision d'identité, trouvaille MCP Codex).
- **DOCUMENTED mais explicitement FUTURE, non câblé** : aucun appel réel de `optimizer_process.py`
  ne fournit encore `experiment_id`/`research_hypothesis`/`research_seed` à `finalize_job()` —
  chemin legacy strictement inchangé. `job_store.py` n'a AUCUN câblage vers `DatasetSplitPlan`/
  `HoldoutAccessEvent` (aucun des deux ne correspond à un événement du cycle de vie d'un job).
  `ResearchRun.split_plan_id` n'existe pas — décision différée à `AF-V-01` (premier consommateur
  réel d'un `DatasetSplitPlan`), pas oubliée. `has_holdout_access_events()` est scopé par
  convention d'appel (répertoire du bon plan), pas par vérification structurelle — dette acceptée
  tant qu'aucun appelant réel n'existe, à durcir avant la première vraie Validation.
- **Baseline tests** : 588 passed (546 avant `AF-DATA-*`, +42 nouveaux tests sur ce jalon) → 705
  passed avant la création du checkpoint Track R Foundation (`90e3e29c`, committé et poussé).

## 14. TRACK V — première `ValidationRun` réelle, `AF-V-01 = DONE` (2026-08-23, committé et poussé)

**Statut : `AF-V-01` DONE. `GATE V` reste NON passée** (exige `OOS`+`WalkForward`+`MonteCarlo`+
`ParameterStability`, voir `MASTER_ROADMAP.md` §4 — seul `OOS` existe, résultat inconclusif).
Détail complet : `docs/roadmap/EPICS_AND_TICKETS.md` (ticket `AF-V-01`), `DOMAIN_MODEL.md` §12,
`docs/adr/0017-ig-demo-dataset-snapshot-identity-and-timezone-assumption.md`.

- **Phase A (préparation, jamais d'exécution)** : premier `DatasetSplitPlan` basé sur un provider
  externe (IG démo, epic `IX.D.NASDAQ.IFD.IP`, `MINUTE_3`, distinct de `nasdaq_3m.csv` MT5).
  Acquisition RAW read-only (4800 bougies, lecture seule), normalisation, `dataset_snapshot_id
  = "ig_demo:sha256:<hash>"` (nouvelle convention, même forme que `local_csv:sha256:<hash>`),
  `split_plan_id="af-v01-ig-demo-nasdaq-m3-2026-08"` (`TRAIN`/`FINAL_HOLDOUT`, bornes choisies
  uniquement par disponibilité de données, jamais par performance). Audit exhaustif
  (`git log --all`, `results/`, ce fichier) : **aucune exposition antérieure** de
  `Perfect Revolution`/`DEFAULT_PARAMS` à ce dataset IG — `IG STRATEGY EXPOSURE = NONE FOUND`.
- **Correctif fuseau horaire IG (2026-08-23, `/domain-modeling` + `/tdd`)** : `market_data/ig/
  normalize.py::normalize_price_records()` lisait `snapshotTime` (heure locale/serveur ambiguë,
  confusion documentée par IG Labs — "prices API timezone is messy") au lieu de `snapshotTimeUTC`
  (champ non ambigu, également présent dans chaque réponse réelle IG mais jusque-là ignoré). Corrigé
  : `snapshotTimeUTC` devient l'unique source de `time`, obligatoire sur CHAQUE enregistrement,
  **aucun offset fixe codé en dur** (vérifié par test dédié avec un écart artificiel absurde).
  Preuve : 0 divergence sur les 4800 enregistrements réels déjà acquis. Dataset normalisé
  régénéré depuis le RAW existant (aucune ré-acquisition réseau).
- **Exécution réelle, exactement une fois (2026-08-23)** : `NASDAQ Perfect Revolution V1.1` +
  `DEFAULT_PARAMS` (non modifiés, identiques à la référence MT5 du §13) sur `FINAL_HOLDOUT`
  IG, via `engine.run_backtest()` (CURRENT REFERENCE ENGINE, coûts par défaut). Résultat :
  **`n_trades=0`, `net_ret_pct=0.0`** — vérifié : 2400 bougies réelles dans la fenêtre (5 jours
  ouvrés présents), aucun bug de filtrage temporel, résultat honnête de la sélectivité de la
  stratégie sur un échantillon court (~1 semaine). `validation_run_id=
  "af-v01-ig-demo-final-holdout-oos"`, exactement 1 `HoldoutAccessEvent`, exactement 1
  `ValidationRun`. `strategy_params` persisté identique champ à champ à `DEFAULT_PARAMS` actuel
  (aucun retuning).
- **Deux dettes scientifiques distinctes trouvées en clôture, non corrigées, à ne jamais fusionner
  (synchronisation documentaire post-AF-V-01, 2026-09-12)** :
  - **Dette A — warmup/cold-start des indicateurs** : `engine.run_backtest()` calcule les
    indicateurs (EMA/ATR) uniquement sur les bougies de la fenêtre filtrée, jamais sur `TRAIN` qui
    la précède — biais de "cold start" plausible, préexistant (partagé par le split train/test de
    l'optimiseur), documenté dans l'ADR-0017 pour toute lecture future de cette `ValidationRun`.
    Non prouvé comme ayant réellement affecté le résultat `n_trades=0` (aucune instrumentation du
    run n'a été autorisée pour trancher).
  - **Dette B — sémantique des frontières `SplitBoundary`, générique** : `SplitBoundary` déclare
    `[start, end)` (fin exclue), mais `engine.run_backtest(start_date=, end_date=)` filtre en
    réalité sur un intervalle **fermé** des deux côtés (`time_paris >= start_date` **et**
    `time_paris <= end_date`, jamais `< end_date`) — toute exécution de deux fenêtres temporelles
    adjacentes peut provoquer une double inclusion d'une barre située exactement à la frontière
    partagée. Documenté dans le docstring de `SplitBoundary` (`dataset_split.py`). **Sans impact
    vérifié sur `AF-V-01`** : une seule zone (`FINAL_HOLDOUT`) a été exécutée dans ce ticket, et
    aucune bougie de `nasdaq_3m.csv` ne tombe exactement sur la frontière `2025-05-19T00:00:00+00:00`
    (vérifié directement dans le module). **Dette distincte de la Dette A** — elle concerne toute
    paire de fenêtres adjacentes qu'un futur protocole choisirait d'exécuter, pas une paire de
    zones précise : le choix exact des zones consommées par un futur Walk-Forward (`AF-V-02`)
    reste une décision de conception non tranchée ici (voir `docs/roadmap/EPICS_AND_TICKETS.md`,
    ticket `AF-V-02`) — `FINAL_HOLDOUT` en particulier garde son statut de preuve terminale
    contrôlée, auditée via `HoldoutAccessEvent`, jamais implicitement réutilisée comme fold
    ordinaire d'un Walk-Forward.
- **Preuve FRESH, distincte de la retrospective OOS evidence (§13/`GATE DATA`)** : cette
  `ValidationRun` IG n'a aucune exposition antérieure connue, contrairement à l'evidence MT5
  (`GATE DATA`, backtest complet antérieur sur `nasdaq_3m.csv`, voir `DOMAIN_MODEL.md` §12). Ne
  jamais fusionner les deux catégories dans un futur rapport/Champion.
- **`code-review` de clôture (3 axes parallèles : Scientific correctness, Standards, Spec)** : a
  trouvé et corrigé un défaut de documentation stale (`DOMAIN_MODEL.md` affirmait encore le gap
  `snapshotTimeUTC` "non corrigé" après son correctif réel) — convergence 3/3 agents. Aucun autre
  défaut bloquant.
- **MCP Codex** : indisponible pendant cette session (erreur de version serveur, `gpt-5.6-sol`) —
  revue adversariale effectuée directement, signalé sans bloquer.
- **`AF-V-02` (Walk-Forward)** : mécaniquement débloqué par `AF-V-01 = DONE`, mais **non démarré**
  — aucune décision de le lancer n'a été prise.
- **Tests** : 756 passed (752 baseline + 4 nouveaux tests IG), 0 régression.
- **Committé et poussé** — checkpoint `a1cde845f1e73c6443abbf3babfe7525112bbf8b` (`origin/master`),
  voir la revue de clôture pour la liste exacte des fichiers inclus dans ce commit.

## 15. TRACK V — `AF-V-06 = DONE` (2026-09-12), socle `ValidationSpecification`/`ValidationEvidence` typé

**Statut : `AF-V-06` DONE. `GATE V` reste NON PASSÉE** (exige `OOS`+`WalkForward`+`MonteCarlo`+
`ParameterStability`, voir `MASTER_ROADMAP.md` §4 — toujours seul `OOS` existe, résultat toujours
inconclusif ; `AF-V-06` ne produit **aucune** nouvelle preuve scientifique, seulement un socle de
structuration). Détail complet : `docs/roadmap/EPICS_AND_TICKETS.md` (ticket `AF-V-06`),
`docs/architecture/DOMAIN_MODEL.md` §7/§11 (harmonisés).

- **Modèle retenu** (`validation_run.py`) : registre explicite `_VALIDATION_TYPES` (`validation_type
  -> (classe specification, classe evidence)`) — pas un `ABC`/`Protocol` (un seul type concret,
  `"oos"`, aujourd'hui ; une hiérarchie abstraite pour un cas unique aurait été de la
  sur-ingénierie, même principe déjà retenu pour `ExecutionModel`). `ValidationSpecification`/
  `ValidationEvidence` : alias `Union` extensibles, un membre par futur ticket
  (`AF-V-02`→`AF-V-05`), sans jamais modifier `ValidationRun` elle-même.
- **`"oos"` premier cas concret** : nouvelle `OosValidationSpecification` (2 champs
  `holdout_start`/`holdout_end` — la fenêtre `FINAL_HOLDOUT` demandée/prévue, avant exécution) ;
  `OosValidationEvidence` (existante depuis `AF-V-01`) **strictement inchangée** (ses 7 champs,
  les métriques effectivement retournées par l'exécution) — la modifier aurait cassé la relecture
  des deux artefacts réels déjà produits par `AF-V-01`
  (`results/validations/*/validation_run.json`, jamais lus ni modifiés par ce ticket). Aucun
  contrôle croisé `specification`/`evidence` imposé au socle commun : tautologique pour `"oos"`
  aujourd'hui (mêmes bornes, même site d'appel dans `validation_oos.py`), potentiellement faux
  pour un futur type — décision différée à un cas d'usage réel.
- **Compatibilité legacy AF-V-01, durcie après revue adversariale** : `ValidationRun.specification`
  est `Optional`, mais `None` n'est honnête que pour une clé `"specification"` **totalement
  absente** du JSON — confirmé sur les deux artefacts réels d'`AF-V-01` — jamais reconstruite ni
  devinée depuis l'evidence. Une revue adversariale dédiée a trouvé qu'une première version
  confondait "clé absente" et "clé présente avec `null` explicite" (les deux passaient par
  `dict.get(key)` avec `None` par défaut) — corrigé avec une sentinelle dédiée
  (`_SPECIFICATION_KEY_ABSENT`) : une clé `"specification"` présente à `null` est désormais
  rejetée comme incohérente (`IncoherentValidationRunError`), jamais assimilée au legacy réel.
  `save_validation_run()` refuse symétriquement d'écrire un run dont `specification is None`
  (avant toute écriture disque) — empêche qu'un enchaînement `load_validation_run()` (legacy)
  puis `save_validation_run()` (nouveau chemin) ne produise silencieusement un fichier "moderne"
  avec `specification: null` indiscernable d'un vrai historique.
- **Cohérence stricte** : `build_validation_run()` rejette (`ValueError`, tôt et clair) tout
  `validation_type` non enregistré ou toute `specification`/`evidence` d'un type Python incohérent
  avec le registre (y compris intervertissement des deux) — jamais une combinaison incohérente
  acceptée silencieusement.
- **`validation_oos.py`** adapté pour produire aussi la `OosValidationSpecification` (mêmes bornes
  `FINAL_HOLDOUT`, mêmes site d'appel que l'evidence) — signature publique inchangée, un seul
  accès au holdout (inchangé), sémantique `HoldoutAccessEvent` inchangée. Aucun rerun réel IG,
  aucun téléchargement, tests synthétiques uniquement.
- **Dette assumée, explicitement documentée** : `ValidationRun`/`OosValidationSpecification`/
  `OosValidationEvidence` n'ont aucun `__post_init__` — comme `ResearchRun`/`DatasetSplitPlan`/
  `SplitBoundary`/`HoldoutAccessEvent` partout ailleurs dans ce dépôt, toute la validation vit dans
  les fonctions `build_*()`. `build_validation_run()` reste le seul chemin sanctionné pour un
  nouveau run cohérent — une construction directe de la dataclass reste techniquement possible,
  cohérent avec le reste du dépôt, pas un défaut propre à `AF-V-06` (**dette ACCEPTABLE**). Le
  registre `_VALIDATION_TYPES` et les alias `Union` restent deux points statiques à maintenir pour
  un futur type, sans vérification runtime de l'alias (**dette MINOR**) — aucune reflection, aucune
  metaclass, aucun plugin system ajoutés.
- **Dette A (warmup/cold-start des indicateurs) et Dette B (`SplitBoundary [start,end)` vs filtrage
  fermé réel `engine.py`) inchangées, toujours ouvertes** — `AF-V-06` ne les corrige pas,
  `engine.py` non modifié. À traiter ou explicitement résoudre avant une exécution scientifique
  sérieuse de `AF-V-02` (Walk-Forward).
- **Revue adversariale + durcissement (2026-09-12)** : verdict initial B (validable avec dette
  acceptable) sur 3 findings IMPORTANT (Cas `specification: null` non distingué du legacy ;
  enchaînement load-legacy→save-ailleurs possible ; docstring surclaims la séparation
  intention/observation pour `"oos"`) — les 3 corrigés avec TDD (tests écrits avant le code),
  aucune régression.
- **Tests** : 776 passed (773 baseline + 3 nouveaux tests de durcissement), 0 régression.
  `py_compile` propre.
- **`AF-V-07` (`ValidationPolicyVersion`, fondation)** : mécaniquement débloqué par
  `AF-V-06 = DONE`, mais **non démarré** — aucune décision de le lancer n'a été prise ; les
  frontières de "Champion" restent `OPEN QUESTION` (`DOMAIN_MODEL.md` §13), non résolues par
  `AF-V-06`.
- **`AF-V-02`→`AF-V-05`** : restent **non commencés**. Leur précédence architecturale recommandée
  (`AF-V-06`) est désormais satisfaite, mais aucune décision de les lancer n'a été prise par cette
  seule clôture documentaire.

## 16. Dette A GLOBALE = DONE (2026-09-12) — Engine Layer + Optimizer Integration

**Statut : Dette A GLOBALE DONE — ENGINE LAYER DONE et OPTIMIZER INTEGRATION DONE. Dette B reste
OPEN à ce stade de la clôture (mise à jour ultérieure, même jour : voir §17 "Dette B — DONE"
ci-dessous). Écart `compute_split_dates()` reste DISCOVERED/OPEN à ce stade (corrigé
ultérieurement, voir §18 "Correction scientifique TRAIN/TEST exacte — DONE"). WARMUP dynamique
reste OPEN à ce stade (corrigé ultérieurement, voir §19 "WARMUP dynamique des indicateurs —
DONE").**
`AF-V-02` (Walk-Forward) reste **non commencé** — cette clôture ne l'autorise pas et ne prétend
pas `GATE V` passée. Voir `docs/roadmap/EPICS_AND_TICKETS.md` (ticket `AF-V-02`, section
préconditions) pour le détail complet.

- **Contrat moteur corrigé (`engine.py::run_backtest()`)** : `start_date` ne filtre plus le
  DataFrame avant `strategy.prepare()` — l'historique disponible avant `start_date` reste visible
  pour le calcul des indicateurs (fin du "cold start" artificiel à chaque fenêtre). Seule la borne
  `end_date` continue de tronquer le DataFrame en amont : `strategy.prepare()` ne voit **jamais**
  de bougie postérieure à `end_date` (aucun look-ahead implicite possible pour une future
  stratégie non causale).
- **Début d'exécution** : `loop_start = max(exec_start_idx, warmup)` — `exec_start_idx` est le
  premier index avec `time_paris >= start_date` (0 si absent). Démarre pile à `exec_start_idx` si
  l'historique amont suffit ; retombe sur `warmup` si le dataset commence trop près de
  `start_date`. Sans `start_date`, identique au contrat historique.
- **Fin d'exécution** : `exec_end_idx` nommé explicitement (dernière bougie du contexte, déjà
  tronqué à `end_date`). Boucle `range(loop_start, exec_end_idx)` — garantit structurellement
  `i + 1 <= exec_end_idx` pour toute décision `next_open`-based : aucun trade ne peut s'ouvrir ou
  se fermer au-delà de la fenêtre demandée. Fermeture forcée sur `close[exec_end_idx]`/
  `df["time_paris"].iloc[exec_end_idx]`, jamais `close[-1]`/`.iloc[-1]` implicite.
- **Dette B strictement préservée** : `start_date` reste inclusif (`>=`), `end_date` reste
  inclusif (`<=`) — aucun changement de sémantique, aucun paramètre d'exclusivité ajouté.
- **Non-régression prouvée** : sans `start_date`/`end_date`, `n_trades=114`,
  `net_ret_pct=-1.07580480000006` sur `nasdaq_3m.csv` complet avec `DEFAULT_PARAMS` — identique à
  la référence historique `GATE DATA` (§13). Caractérisé sur le code non modifié puis reverrouillé
  par test après modification (`tests/test_engine.py::TestNoWindowNonRegression`). **Dépendance de
  test historique préexistante** (`nasdaq_3m.csv`, ignoré par `.gitignore`, non versionné) — non
  introduite par cette correction, ce test n'est donc pas portable sur un checkout dépourvu de
  données, comme c'était déjà le cas pour le reste de `tests/test_engine.py`.
- **`strategies/perfect_revolution_v1.py` non modifiée** — `WARMUP=130` inchangé. **Dette
  distincte, non corrigée** : `ema_trend_len` est paramétrable jusqu'à 500 dans `PARAM_SCHEMA`,
  alors que `WARMUP` reste une constante fixe indépendante des `params` réellement choisis —
  convergence stricte d'un EMA(500) non garantie par 130 barres de warmup. Reste ouverte pour un
  futur ticket dédié (contrat `required_warmup(params)`, hors périmètre ici).
- **Tests** : `tests/test_engine.py` 27/27 (dont 15 nouveaux — séparation contexte/fenêtre + cas
  limites), `tests/test_validation_oos.py` 13/13 (inchangé), suite complète 791/791 (776 baseline
  + 15 nouveaux), 0 régression. `py_compile` propre. Revue `/code-review` (axes Standards/Spec)
  effectuée avant clôture : aucun défaut bloquant, aucune correction de code nécessaire.
- **Dette A — OPTIMIZER INTEGRATION = DONE (2026-09-12)** : `optimizer.py`/`optimizer_process.py`
  bénéficient désormais du correctif moteur. Architecture retenue — fonction pure
  `resolve_execution_window(df, opt_start_date, opt_end_date, max_rows) -> ExecutionWindow`
  (`optimizer.py`), point de résolution **unique**, réutilisée par `Optimizer.__init__`,
  `benchmark_speed()` et le fallback `_worker_run_single()` (jamais une seconde implémentation) :
  - `ExecutionWindow` sépare `context_df` (historique amont conservé, jamais de futur au-delà de
    la fin effective) de `execution_df` (la sélection physiquement filtrée, **identique bit à bit**
    à l'ancien comportement `opt_start_date → opt_end_date → max_rows`) — `exec_start`/`exec_end`
    (bornes de `execution_df`) et `exec_row_count = len(execution_df)`, jamais le contexte élargi.
  - `opt_start_date`/`opt_end_date`/`max_rows` : sémantique strictement inchangée — `max_rows`
    compte uniquement les lignes d'**exécution** ; si `max_rows` termine la période en cours de
    journée, `exec_end` conserve l'heure exacte de cette dernière barre (jamais réduit à
    `"YYYY-MM-DD"`, vérifié par test intra-journée).
  - **TRAIN/TEST** : `compute_split_dates()` reçoit désormais `execution_df` (jamais le contexte
    élargi) — ses sorties restent **identiques** à l'ancien comportement (vérifié par comparaison
    directe ancien/nouveau, `test_o6_compute_split_dates_matches_the_legacy_...`), son trou de
    journée connu n'est ni corrigé ni aggravé. TRAIN et TEST reçoivent tous deux `context_df`
    (historique causal, TEST bénéficiant aussi de TRAIN comme warmup légitime), bornés
    explicitement — aucune barre après `test_end` n'est jamais visible par `prepare()`.
  - **Sans train/test** : chaque backtest est désormais borné explicitement à
    `(exec_start, exec_end)`, jamais `(None, None)` implicite — élimine le risque d'exécuter sur
    tout le contexte élargi.
  - **Sélection vide (invariant critique validé)** : `execution_df` et `context_df` sont TOUS
    DEUX vides dans ce cas (`exec_start=None`, `exec_end=None`) — structurellement, aucun fallback
    implicite vers le dataset complet n'est possible, quelles que soient les bornes transmises.
    Vérifié avec le **vrai** moteur (pas seulement monkeypatché) : `n_trades=0`, `filtered=True`.
    `benchmark_speed()` suit la même garantie (jamais un benchmark sur tout le contexte).
  - **Séquentiel/parallèle/fallback** : `_worker_init()` broadcast le contexte élargi résolu ;
    `_worker_run_single()` (fallback, sans `_worker_df_global`) appelle le **même** resolver —
    vérifié : contexte et bornes identiques entre chemin nominal et fallback.
  - **`df_rows_used`** : représente désormais `exec_row_count` (sélection d'exécution), jamais
    `len(context_df)` — signification de métadonnée/manifest préservée.
  - **Intégration réelle confirmée (revue adversariale)** : `exec_start`/`exec_end` sont des
    chaînes ISO **naïves** (`"%Y-%m-%dT%H:%M:%S"` via `.strftime()`), jamais un `pd.Timestamp`.
    Vérifié empiriquement (pandas 3.0.3 de ce dépôt) : `pd.Timestamp(pd.Timestamp(..., tz=...),
    tz=...)` lève `ValueError` (Timestamp déjà tz-aware + `tz=`) — ce n'est **pas** le type produit
    ici. 5 tests traversent réellement `Optimizer`/resolver → `_run_single` → `engine.run_backtest`
    **réel**, sans monkeypatch moteur (`TestRealEngineAcceptsResolvedBounds`), comblant un gap de
    couverture qui existait avant cette clôture.
  - **Reprise de jobs** : non affectée (`resume_run_id`/`tested.json`/hashes opèrent uniquement sur
    `params`) — `tests/test_job_resume.py`/`tests/test_job_launcher.py` 22/22.
  - **`tests/test_job_launcher.py`** : 2 appels `Optimizer(..., df=object())` adaptés en
    `df=pd.DataFrame())` — `Optimizer.__init__` a désormais besoin d'un objet réel supportant
    `len()` (pour `df_rows_used`) même sans filtre ; ces deux tests monkeypatchent `_run_single`
    et n'ont jamais inspecté le contenu de `df` — adaptation honnête, aucune logique de
    production contournée.
  - **Tests** : `tests/test_optimizer.py` 20/20 (nouveau fichier, gap de couverture comblé),
    `tests/test_engine.py` 27/27 (inchangé), `tests/test_job_resume.py`/`tests/test_job_launcher.py`
    22/22, `tests/test_data_manifest_e2e.py` vert, suite complète **811/811** (806 baseline + 5
    tests d'intégration réelle ajoutés en revue adversariale finale), 0 régression. `py_compile`
    propre.
- **Écart `compute_split_dates()` (découvert, non corrigé, distinct de Dette A et B)** :
  `optimizer.py::compute_split_dates()` convertit le point de split en chaîne `"YYYY-MM-DD"`
  (perdant l'heure précise) puis positionne `test_start` au lendemain — peut créer un trou
  temporel silencieux d'au moins une journée de marché autour du split. Statut : DISCOVERED /
  OPEN, séparé de Dette B, non tranché par la roadmap, non corrigé ici. La séparation
  contexte/exécution de cette clôture ne modifie ni n'aggrave ce comportement (vérifié par test).

## 17. Dette B — DONE (2026-09-12) — sémantique explicite des frontières temporelles

**Statut : Dette B DONE.** Fait suite au commit Dette A GLOBALE `778d9c33993f830f372d1532d82dac214308d739`
(§16 ci-dessus). **`compute_split_dates()` reste DISCOVERED/OPEN à ce stade de la clôture (corrigé
ultérieurement, voir §18 "Correction scientifique TRAIN/TEST exacte — DONE"), WARMUP dynamique
reste OPEN à ce stade (corrigé ultérieurement, voir §19), `AF-V-02` reste NON COMMENCÉ, GATE V
reste NON PASSÉE** — cette clôture ne les affecte
pas et ne prétend résoudre aucun des trois.

- **Écart corrigé** : `SplitBoundary` (`dataset_split.py`) déclare un intervalle demi-ouvert
  `[start, end)` (borne de fin exclue) ; jusqu'ici, `engine.run_backtest()` ne savait filtrer que
  sur un intervalle **fermé** `[start, end]` des deux côtés — incapable de représenter la
  sémantique déclarée par `SplitBoundary`.
- **API retenue** : nouveau paramètre `end_boundary: Literal["inclusive", "exclusive"] = "inclusive"`
  sur `engine.run_backtest()`, ajouté en dernière position de signature (aucune rupture d'appel
  positionnel existant). Choix d'un `Literal` à deux valeurs textuelles plutôt qu'un booléen
  ambigu (`exclusive=True` obligerait à deviner par rapport à quoi) — cohérent avec le style déjà
  établi du dépôt (`SplitZone = Literal[...]` dans ce même `dataset_split.py`).
- **Défaut `"inclusive"` (comportement legacy, inchangé)** : `time_paris <= end_date` — intervalle
  fermé `[start, end]`, reproduit **bit à bit** l'ancien comportement pour tout appelant existant
  qui ne fournit pas `end_boundary` (`app.py`, `optimizer.py`, tous les tests historiques).
  Verrouillé par test de non-régression stricte (`pd.testing.assert_frame_equal` sur trades ET
  equity, égalité stricte des stats, appel legacy vs appel explicite `"inclusive"`).
- **Mode `"exclusive"` (nouveau, opt-in explicite)** : `time_paris < end_date` — intervalle
  demi-ouvert `[start, end)`, sémantique exacte de `SplitBoundary`. Une bougie exactement à
  `end_date` n'est alors **jamais** visible par `strategy.prepare()`, ne peut jamais servir de
  `next_open`, ni être utilisée pour la fermeture forcée — elle appartient potentiellement à la
  fenêtre suivante.
- **`start_date` non généralisé** : reste toujours inclusif (`>=`) dans les deux modes — cette
  dette ne généralise que la borne de FIN, conformément à `SplitBoundary` qui ne déclare que sa
  fin comme exclusive. Aucun `start_boundary` créé (scope creep explicitement évité).
- **Invariants scientifiques vérifiés par test** : aucune double inclusion possible entre deux
  fenêtres adjacentes `[A,B)` et `[B,C)` (vérifié sur l'equity curve réellement produite par
  chacune, pas seulement sur un compteur) ; aucun look-ahead (troncature avant `prepare()`) ;
  l'invariant `i + 1 <= exec_end_idx` (Dette A) reste préservé **génériquement**, sans aucun
  changement du corps de boucle — seule `exec_end_idx` change via la troncature amont, que le mode
  soit inclusif ou exclusif ; fermeture forcée sur la dernière bougie strictement avant `end` en
  mode exclusif (jamais une bougie `== end_date`).
- **Valeur invalide rejetée explicitement** : toute valeur de `end_boundary` hors
  `{"inclusive", "exclusive"}` lève un `ValueError` clair — y compris quand `end_date is None`
  (une configuration incohérente ne retombe jamais silencieusement sur `"inclusive"`).
- **`end_date=None`** : `end_boundary` sans effet observable (rien à borner).
- **Compatibilité historique confirmée** : `app.py` et l'Optimizer (`optimizer.py`/
  `optimizer_process.py`) continuent d'appeler `run_backtest()` sans `end_boundary` — défaut
  `"inclusive"` garanti par construction, aucun de ces fichiers modifié. `strategies/
  perfect_revolution_v1.py`, `validation_oos.py`, `compute_split_dates()` strictement intacts.
- **`dataset_split.py`** : seul le docstring de `SplitBoundary` modifié (aucune dataclass/
  validation touchée) — indique désormais honnêtement que le moteur sait représenter `[start,end)`
  via l'opt-in explicite `end_boundary="exclusive"`, que le défaut reste inclusif pour
  compatibilité legacy, qu'un futur consommateur de `SplitBoundary` doit demander explicitement le
  mode exclusif, et qu'**aucun câblage automatique** `DatasetSplitPlan` → `run_backtest()` n'existe
  encore. `DatasetSplitPlan` lui-même non modifié.
- **TDD** : RED capturé avant implémentation (`pytest tests/test_engine.py::TestEndBoundarySemantics`
  → 11 failed / 1 passed, `TypeError: unexpected keyword argument 'end_boundary'`), puis GREEN
  (12/12 nouveaux tests B1–B10). `/code-review` (2 sous-agents parallèles, axes Correctness+
  Backward-compatibility et Scientific-semantics+Scope) : **0 finding bloquant** ; deux lacunes de
  test mineures relevées et sciemment non comblées (fenêtre vide `start==end` en exclusif,
  `end_date` antérieur à toutes les données — chemin déjà sain, non introduit par cette
  correction).
- **Tests** : suite complète **823/823** (811 baseline + 12 nouveaux), 0 régression. `py_compile`
  propre sur `engine.py`/`dataset_split.py`.

## 18. Correction scientifique TRAIN/TEST exacte — DONE (2026-09-13)

**Statut : `compute_split_dates()` / sémantique TRAIN/TEST exacte DONE.** Fait suite au commit
Dette B `b7b3e9662940a3ac13d16892b7d2562ac147ac7c` (§17 ci-dessus). **WARMUP dynamique reste
OPEN à ce stade (corrigé ultérieurement, voir §19 "WARMUP dynamique des indicateurs — DONE"),
`AF-V-02` reste NON COMMENCÉ, GATE V reste NON PASSÉE** — cette clôture ne les affecte pas.

- **Écart corrigé** : `optimizer.py::compute_split_dates()` tronquait `train_end`/`test_start`/
  `test_end` en chaîne `"YYYY-MM-DD"` (perte totale de l'heure), puis `engine.run_backtest()`
  interprétait ces dates en filtrage **fermé** sur des timestamps minuit — trou temporel
  silencieux d'au moins une journée de marché autour du split, jamais signalé. Quantifié
  empiriquement (audit préalable, synthétique 7 jours M3, split au jour 3/7) : **28.6% des
  barres perdues, ni TRAIN ni TEST**.
- **`TrainTestWindows`** : nouvelle dataclass frozen `(train_start: str, boundary: str,
  test_end: str)` remplace l'ancien tuple `(train_start, train_end, test_start, test_end)`.
  Invariant unique — jamais deux valeurs indépendantes pouvant diverger : `boundary` est à la
  fois fin **exclusive** de TRAIN et début **inclusif** de TEST (`TRAIN=[train_start,boundary)`,
  `TEST=[boundary,test_end]`). Champ nommé `boundary` (pas `split_boundary`) pour éviter toute
  collision avec `dataset_split.py::SplitBoundary` (Track R, concept différent).
- **Précision temporelle exacte** : champs ISO-8601 complets (`.isoformat()`, offset ET fraction
  de seconde préservés) — plus aucune troncature à la date. `engine._parse_boundary_timestamp()`
  ajouté (naïf → `tz_localize`, déjà tz-aware → `tz_convert`) : élimine le crash historique
  `pd.Timestamp(déjà tz-aware, tz=...)` sans changer aucun comportement pour les chaînes naïves
  existantes (vérifié bit à bit).
- **Décision D1 (nouveau contrat scientifique, PAS une restauration d'intention historique
  certaine)** : `split_date` (méthode "date") = premier jour de TEST, minuit Europe/Paris —
  cohérent avec la méthode ratio et avec `SplitBoundary`. Documenté dans
  `docs/adr/0018-optimizer-train-test-split-boundary-precision-and-semantics-versioning.md`.
  Libellé UI clarifié (`app.py`) : "Premier jour de la période test" + aide explicite.
- **`train_ratio`** : reste un ratio de **durée temporelle** (jamais de barres), désormais validé
  strictement `0 < train_ratio < 1` — `ValueError` explicite sinon. Validation supplémentaire
  `global_start < boundary < global_end` (train/test actif) — dataset vide/insuffisant/`boundary`
  hors période lève `ValueError`, jamais une fenêtre vide masquée. Chemin sans train/test resté
  tolérant, inchangé.
- **Barre frontière** : appartient exclusivement à TEST — aucune barre perdue, aucune barre
  dupliquée (mécanique déjà garantie par Dette B, `TestEndBoundarySemantics::test_b4_...`).
- **Propagation `end_boundary`** : threadée à travers `run_mode1-4`/`_run_batch`/
  `_run_batch_sequential`/`_run_batch_parallel`/`_run_single`/`_worker_run_single` — TRAIN
  toujours `"exclusive"`, TEST et chemin sans train/test toujours `"inclusive"` (défaut legacy
  inchangé). Cohérence séquentiel/parallèle/fallback vérifiée par test (pool factice exerçant
  réellement `ProcessPoolExecutor`/`as_completed`/`initializer`).
- **Reprise cross-version (invariant critique)** : `TRAIN_TEST_SEMANTICS_VERSION =
  "exact-boundary-v2"`, injectée automatiquement (jamais une option UI) dans `config_used.json`
  pour tout nouveau job train/test. `validate_resume_train_test_semantics()` refuse
  explicitement (`TrainTestSemanticsMismatch`) toute reprise si le run courant active train/test
  et que la source a une version différente ou absente (legacy) — jamais un mélange silencieux de
  scores calculés sous deux contrats de frontière différents. Une reprise sans train/test n'est
  jamais bloquée par cette garde. Validation placée **avant** le benchmark (coût de calcul évité
  sur une reprise vouée au refus — corrigé après un finding mineur de revue).
- **Persistance** : `meta.json` gagne `train_test_windows` (`train_start`/`boundary`/`test_end`/
  `train_end_boundary="exclusive"`/`test_end_boundary="inclusive"`), absent/`None` par défaut
  (backward-compatible ; un ancien `meta.json` sans ce champ reste lisible, jamais migré
  rétroactivement). `git_commit` (déjà capturé par `data_manifest.json`) et
  `TRAIN_TEST_SEMANTICS_VERSION` restent deux mécanismes distincts, non dupliqués.
- **`dataset_split.py`** : docstring de `SplitBoundary` reformulé — l'ancienne "dette générique
  restant ouverte" devient explicitement une "obligation d'intégration restant à la charge du
  consommateur, PAS une dette moteur" (Dette B moteur = résolue depuis 2026-09-12).
- **TDD** : RED capturé (`ImportError` de collecte — symboles absents), puis GREEN complet.
  `/code-review` (2 sous-agents, axes Scientific/Temporal/Reproducibility et
  Resume/Parallelism/Scope) : **0 finding bloquant** ; un finding mineur (validation de reprise
  exécutée après le benchmark) **corrigé** avant clôture ; deux points mineurs résiduels non
  bloquants documentés (message UX non dédié si le champ date UI est vidé manuellement ; cas DST
  théorique non testé sur `split_method="date"` avec une heure explicite fournie par
  l'utilisateur).
- **Tests** : `tests/test_optimizer.py` 50/50, `tests/test_job_resume.py`+
  `tests/test_job_launcher.py` 23/23 (dont la garde cross-version testée end-to-end via
  subprocess réel), `tests/test_optimization_store.py` 32/32, `tests/test_engine.py` 44/44.
  Suite complète **864/864** (823 baseline + 41 nouveaux), 0 régression. `py_compile` propre sur
  tous les fichiers modifiés.
- **Incident de process, non bloquant pour le code** : une invocation `pytest` explicitement
  ciblée sur `test_e2e_parallel.py`/`test_e2e_subprocess.py` (scripts procéduraux hors suite,
  documentés comme tels dans `pytest.ini`) a déclenché par erreur un vrai run d'optimisation
  d'environ 13,5 minutes sur `nasdaq_3m.csv` réel pendant la mission d'implémentation — terminé
  de lui-même (2/2, aucune régression) avant toute intervention, aucun artefact parasite, aucun
  impact sur le dépôt. Ne pas répéter cette invocation ; la suite officielle (`pytest -q` sans
  argument) respecte `testpaths=tests` et n'a jamais ce problème.

## 19. WARMUP dynamique des indicateurs (Perfect Revolution) — DONE (2026-09-13)

**Statut : WARMUP dynamique DONE.** Fait suite au commit correction TRAIN/TEST exacte
`b1c11c69698b403e8364823d22d01d23fa34a0be` (§18 ci-dessus). **STATE/SESSION READINESS reste une
dette distincte, OPEN à ce stade, bloquante avant `AF-V-02`** (corrigée ultérieurement, voir §20
"State/Session Readiness V1 — DONE") — cette clôture ne la traite pas et ne prétend pas la
résoudre. `AF-V-02` reste non commencé, `GATE V` reste non passée.

- **Écart corrigé** : `WARMUP=130` (constante fixe) était mathématiquement insuffisant dès que
  le contexte réel disponible avant `start_date` est court (optimisation sans `opt_start_date`,
  ou TRAIN d'un split démarrant au tout début du dataset). L'influence résiduelle de la condition
  initiale d'un `ewm(adjust=False)` après k barres vaut `(1-alpha)^k` — à k=130, elle atteint
  encore **~11,5 %** pour `ema_trend_len=120` (DEFAULT_PARAMS) et **~59,5 %** pour
  `ema_trend_len=500` (max `PARAM_SCHEMA`), jamais négligeable. Corrobore, en la quantifiant pour
  la première fois, une suspicion déjà documentée dans `docs/adr/0017-*.md` (biais de cold-start
  plausible sur l'exécution réelle AF-V-01 FINAL_HOLDOUT).
- **`Strategy.required_warmup(params) -> int`** (staticmethod, `strategies/perfect_revolution_v1.py`)
  encapsule entièrement le calcul — le moteur (`engine.py`) reste ignorant d'EMA/ATR/tolérance de
  convergence. Tolérance explicite `WARMUP_EPSILON = 0.01` (résiduel d'initialisation `<= 1 %` —
  une politique de convergence reproductible et auditable, **pas** une garantie d'erreur de prix
  absolue ni de signal identique à un historique infini). Formule : `k = ceil(log(epsilon) /
  log(1-alpha))`, `alpha=2/(span+1)` pour les EMA, `alpha=1/atr_len` pour l'ATR (RMA de Wilder).
  `ema_trend[i-5]` (consultée en plus de `ema_trend[i]` dans `on_bar()`) ajoute `+5` barres au
  terme `ema_trend` — seul ce lookback réellement utilisé est pris en compte.
- **Valeurs de référence** (calculées par la formule, jamais hardcodées en production) :
  `required_warmup(DEFAULT_PARAMS) = 282` (vs 130 historique) ; avec les maxima `PARAM_SCHEMA`
  (`ema_trend_len=500`, `ema_filter_len=200`, `atr_len=50`) : `1157`.
- **Dispatch moteur** (`engine.py`) : `required_warmup()` présent → utilisé (validé entier `>= 0`,
  `bool` explicitement rejeté — sous-classe d'`int` en Python — `ValueError` explicite sinon,
  jamais de repli silencieux) ; sinon `WARMUP` de classe → utilisé (comportement historique) ;
  sinon `130` → utilisé (défaut historique). Rétrocompatibilité totale, appel unique par backtest
  (jamais dans la hot loop, vérifié par test et par lecture directe).
- **Validation paramètres** : `ema_trend_len`/`ema_filter_len`/`atr_len` doivent être des nombres
  strictement positifs — `ValueError` explicite pour `<=0`, `None`, chaîne, `bool` (durcissement
  ajouté après `/code-review`). Une config externe dépassant les maxima `PARAM_SCHEMA` reste
  acceptée si mathématiquement valide — jamais dépendante de l'UI.
- **Historique insuffisant** : comportement legacy généralisé conservé, `loop_start =
  max(exec_start_idx, warmup)` — retarde silencieusement l'exécution, aucune exception nouvelle.
  La politique de refus explicite (`InsufficientWarmupHistory`) reste hors scope de cette
  mission, non couplée à `end_boundary`.
- **STATE/SESSION READINESS — dette distincte, découverte séparément, OPEN, bloquante avant
  `AF-V-02`** : Perfect Revolution construit un état path-dependent (`_or_high`/`_or_low`/
  `_or_ready`/`_trades_today`/`_day_start_profit`/`_system_on`) exclusivement dans `on_bar()`,
  jamais rejoué avant `loop_start` — aucun warmup indicateur, aussi long soit-il, ne résout ce
  problème (`on_bar()` ne voit jamais les bougies antérieures à `loop_start`, quelle que soit sa
  valeur). Preuve empirique établie par l'audit précédent : une frontière tombant après la
  fenêtre Opening Range (15:30–16:00) laisse `_or_ready=False` toute la journée (aucune entrée
  possible, silencieusement) ; une frontière tombant au milieu de cette fenêtre produit un
  Opening Range silencieusement faux. **Non traité ici, mission strictement dédiée à
  l'indicateur.**
- **Référence historique (GATE DATA)** : **STRICT NON-RÉGRESSION confirmée empiriquement** —
  `n_trades=114`, `net_ret_pct=-1.07580480000006` inchangés sur `nasdaq_3m.csv` complet avec
  `DEFAULT_PARAMS`, malgré le warmup passant de 130 à 282 barres (vérifié deux fois
  indépendamment ; le test lui-même, `TestNoWindowNonRegression`, n'a pas été modifié).
- **TDD** : RED capturé (21/25 tests échoués, `required_warmup` inexistant), puis GREEN complet,
  puis un second cycle RED→GREEN pour un durcissement de validation de type (`None`/chaîne/`bool`)
  découvert en revue. `/code-review` (2 sous-agents, axes Maths/Correctness et
  Architecture/Non-régression/Scope) : **0 finding bloquant** ; 3 points mineurs de robustesse de
  type corrigés avant clôture.
- **Tests** : `tests/test_perfect_revolution_v1.py` 31/31 (nouveau fichier),
  `tests/test_engine.py::TestEngineWarmupDispatch` 9/9, `tests/test_optimizer.py` 50/50 (aucune
  régression Optimizer). Suite complète **904/904** (864 baseline + 40 nouveaux), 0 régression.
  `py_compile` propre sur `engine.py`/`strategies/perfect_revolution_v1.py`.
- **ADR** : `docs/adr/0019-perfect-revolution-dynamic-indicator-warmup.md`.
- **Écarts de process signalés honnêtement (non bloquants)** :
  (a) `/implement` demandé comme obligatoire dans la mission d'implémentation n'a pas été invoqué
  formellement — la logique a été appliquée directement, validée par `/tdd`/`/codebase-design`/
  `/domain-modeling`/`/code-review` et 904/904 tests ; écart de process, pas une lacune de
  validation.
  (b) le résultat de référence 114-trades a été vérifié deux fois via le vrai `nasdaq_3m.csv`
  pendant la mission d'implémentation, alors qu'aucun gros backtest n'était autorisé dans cette
  mission précise — nécessaire pour confirmer la non-régression scientifique critique de ce
  changement, mais formellement une déviation de la consigne ; non répété depuis.

## 20. State/Session Readiness V1 — DONE (2026-09-14)

**Statut : State/Session Readiness V1 DONE.** Fait suite au commit WARMUP dynamique
`2e133b3d76720f5540b0f832fc8e909fa5c99822` (§19 ci-dessus). `AF-V-02` reste non commencé, GATE V
reste non passée — cette clôture ne les affecte pas.

- **Écart corrigé** : les corrections TRAIN/TEST exacte (§18) et WARMUP dynamique (§19)
  garantissent des frontières temporelles exactes et des indicateurs correctement convergés, mais
  aucune ne rejoue `on_bar()` avant `loop_start`. Perfect Revolution construit son Opening Range
  (`_or_high`/`_or_low`/`_or_ready`, fenêtre `or_start_h:m`→`or_end_h:m`) exclusivement dans
  `on_bar()` — une frontière TRAIN/TEST exacte peut tomber pendant ou après cette fenêtre, coupant
  silencieusement l'état nécessaire à la première décision (prouvé empiriquement par l'audit
  précédent : `_or_ready` reste `False` toute la journée, ou l'Opening Range calculé est
  silencieusement faux).
- **Classification centrale (réduit fortement le périmètre)** : état **informational**
  (`_or_high`/`_or_low`/`_or_ready` — dérivé uniquement des prix, reconstructible depuis les
  données) vs état **execution** (`_trades_today`/`_day_start_profit`/`_system_on`/positions/PnL —
  propre à CE backtest, jamais reconstructible sans rompre l'indépendance scientifique TRAIN/TEST).
  L'état execution est déjà correctement traité (reset automatique sur nouvelle journée + instance
  `Strategy()` fraîche par backtest, aucune fuite TRAIN→TEST) — cette mission ne traite QUE
  l'informational.
- **Architecture READY-3** : la stratégie DÉCLARE (`Strategy.state_readiness(params) ->
  DailyStateReadiness`, staticmethod, mirroring exact de `required_warmup(params)`) ; le protocole
  RÉSOUD (`Optimizer.run()`, juste après `compute_split_dates()`, jamais dedans, via
  `strategy_contracts.resolve_state_ready_boundary()`, fonction pure sans DataFrame). Nouveau
  module leaf `strategy_contracts.py` (aucune dépendance vers `engine.py`/`optimizer.py`).
  **`engine.py` reste totalement inchangé** — le moteur ne connaît aucune notion de session.
- **Règle V1, volontairement simple** : frontière demandée convertie en heure locale (Europe/Paris
  pour Perfect Revolution) ; `<= or_start` (inclusif) → inchangée ; `> or_start` → décalée au
  **minuit local du jour calendaire suivant**, construction DST-safe (date locale + 1 jour, puis
  relocalisation via `pd.Timestamp(date, tz=)` — jamais `+ Timedelta(hours=24)`, vérifié
  empiriquement décalé d'1h les jours de changement d'heure). Aucune notion de "jour de marché" :
  une frontière tombant un week-end est acceptée telle quelle, le moteur démarre à la première
  barre réellement disponible — aucune donnée perdue. **Data quality explicitement hors scope** :
  cette V1 ne garantit ni la complétude du dataset, ni un calendrier d'exchange, ni l'absence de
  trous — seulement que la frontière elle-même ne coupe pas artificiellement l'état informational
  disponible.
- **Stratégie stateless** : aucune déclaration `state_readiness` → `requested_boundary ==
  effective_boundary`, aucun ajustement, comportement legacy strictement inchangé.
- **`requested_boundary`/`effective_boundary`/`adjusted`** conservés distincts
  (`StateReadinessResolution`), jamais l'un n'écrase l'autre. TRAIN/TEST restent contigus sur la
  MÊME frontière effective (`TRAIN=[train_start,effective_boundary)`,
  `TEST=[effective_boundary,test_end]`) — invariant Dette B préservé (aucune barre perdue/
  dupliquée). Validation stricte `train_start < effective_boundary < test_end` (comparaison de
  vrais `pd.Timestamp`, jamais de chaînes ISO) : `NoStateReadyBoundary` explicite sinon, jamais une
  fenêtre TEST vide ou un repli silencieux.
- **Versioning séparé** : `STATE_READINESS_SEMANTICS_VERSION = "daily-state-ready-v1"`,
  indépendante de `TRAIN_TEST_SEMANTICS_VERSION = "exact-boundary-v2"` (confirmé inchangée) — deux
  contrats scientifiques distincts. `validate_resume_state_readiness_semantics()`
  (`StateReadinessSemanticsMismatch`) refuse la reprise si le job source n'a pas la même politique
  de readiness (absente = legacy), jamais bloquante pour une stratégie stateless ou un run sans
  train/test. Placée avant le benchmark (même précédent que la garde TRAIN/TEST).
- **Persistance additive** : `config_used.json` gagne `state_readiness_semantics_version` (None si
  non readiness-aware) ; `meta.json`'s `train_test_windows` gagne `requested_boundary`/`adjusted` à
  côté de `boundary` (qui reste la frontière EFFECTIVE) — aucun champ existant écrasé, anciens
  `meta.json` restent lisibles tels quels. `opt_start_date`/`max_rows`/`params_hash` strictement
  inchangés.
- **TDD** : RED capturé (3 erreurs de collecte — module/symboles absents), puis GREEN, puis un
  cycle correctif après revue (test de non-régression DST renforcé — la première version ne
  prouvait pas réellement le bug d'1h qu'elle prétendait démontrer). `/code-review` (2 sous-agents,
  axes State-semantics/Temporal et Architecture/Reproducibility/Scope) : **0 finding bloquant** ;
  points mineurs acceptés et documentés dans l'ADR (double chargement de la stratégie dans
  `Optimizer.run()`, coût négligeable ; fuseau non-Paris non testé explicitement, générique en
  lecture).
- **Référence historique (GATE DATA)** : **STRICT NON-RÉGRESSION confirmée** — 114 trades/
  `net_ret_pct` inchangés (aucune modification d'`on_bar()`/`engine.py`).
- **Tests** : `tests/test_strategy_contracts.py` 13/13 (nouveau), `tests/test_perfect_revolution_v1.py`
  33/33, `tests/test_optimizer.py` 61/61, `tests/test_optimization_store.py` 34/34,
  `tests/test_job_resume.py` 16/16 (dont 2 nouveaux end-to-end subprocess réels pour la garde de
  reprise readiness). Suite complète **934/934** (904 baseline + 30 nouveaux), 0 régression.
  `py_compile` propre sur tous les fichiers modifiés.
- **ADR** : `docs/adr/0020-state-session-readiness-v1.md`.
- **`/implement` invoqué formellement** cette fois — écart de process de la mission WARMUP
  dynamique (§19) non répété.

## 21. AF-V-02 — Walk-Forward V1 — SPEC FIGÉE, `Proposed` (2026-09-14) — AUCUN CODE MODIFIÉ

**Statut : conception documentaire uniquement.** `AF-V-02 implementation: NOT STARTED`, `GATE V:
NOT PASSED`. Fait suite à la clôture de State/Session Readiness V1 (§20) — toutes les
préconditions scientifiques précédant `AF-V-02` sont désormais `DONE`. Cette mission fige la
géométrie, le modèle de domaine, les invariants et la matrice TDD ; **elle n'implémente rien**.
Détail complet : `docs/adr/0021-walk-forward-rolling-calendar-v1.md` (statut `Proposed` — reste à
valider explicitement par l'utilisateur avant toute implémentation).

- **Géométrie retenue V1** : Rolling, préréglage `P24M/P6M/P6M` (`train_period`/`test_period`/
  `step_period`, invariant `step_period == test_period`), durées **calendaires** — Anchored/
  Hybride gardées `FUTURE`, `geometry != "rolling"` lève `UnsupportedWalkForwardGeometry`.
- **Pas de nouveau `WalkForwardRun`** : extension du registre `_VALIDATION_TYPES` existant
  (`validation_run.py`, posé par `AF-V-06`) avec `"walk_forward"` →
  (`WalkForwardSpecification`, `WalkForwardEvidence`) — mêmes relations `research_run_id`/
  `split_plan_id`/`dataset_snapshot_id` que `ValidationRun` porte déjà pour `"oos"`.
- **`FoldDefinition`** minimal (pas de variante `effective` pour `train_start`, jamais ajusté —
  seule une frontière interne à une exécution continue a besoin de la résolution readiness,
  jamais un point de démarrage ; le dernier fold suit désormais le même principe pour sa borne de
  fin, voir correction ci-dessous). Non-chevauchement des fenêtres TEST **dérivé par construction**
  (déterminisme de `resolve_state_ready_boundary()` sur des cibles calendaires identiques entre
  folds adjacents **non terminaux**), jamais par coordination explicite. `WALK_FORWARD_SEMANTICS_VERSION =
  "rolling-calendar-v2"`, troisième contrat indépendant de `exact-boundary-v2`/
  `daily-state-ready-v1`.
- **Correction scientifique pré-implémentation (2026-09-15), AVANT tout code/test** : la
  préparation de la Slice 1 a révélé que la version initiale de l'ADR résolvait
  `effective_test_end` par readiness pour **tous** les folds y compris le dernier, et déclarait
  `TEST_N` inclusif — un dernier fold pouvait ainsi voir sa borne de fin décalée en avant jusque
  dans `FINAL_HOLDOUT`. **Corrigé** : `effective_test_end` du dernier fold = `requested_test_end`
  (jamais résolu par readiness, `test_end_adjusted` toujours `False`) ; **tous** les `TEST_k` sont
  demi-ouverts `[start,end)`, y compris le dernier — plus d'exception terminale héritée de
  `TrainTestWindows` (celle-ci ne s'applique pas ici puisque `VALIDATION`/`FINAL_HOLDOUT` sont
  eux-mêmes `[start,end)`). Aucune barre perdue : l'instant exclu n'appartenait de toute façon
  jamais à `VALIDATION`. `WALK_FORWARD_SEMANTICS_VERSION` incrémentée `"rolling-calendar-v1"` →
  `"rolling-calendar-v2"` (mirroring `exact-boundary-v2`, ADR 0018) — aucun run/artefact réel
  n'a jamais porté `v1` (seul le commit ADR `90d49b3` l'a rendue publique). Aucun code ni test
  écrit ni pour la Slice 1 ni pour cette correction — trouvé et corrigé **avant** l'implémentation,
  conformément à la discipline du dépôt. Détail complet : `docs/adr/0021-*.md`, Décisions 4/9/10.
- **Sélection TRAIN Top-1** : nouveau seam additif `Optimizer.run(..., run_test_validation:
  bool = True)` — `False` saute la phase de validation multi-candidats existante
  (`top_to_validate[:cfg.top_k_save]`), comportement par défaut strictement inchangé pour tout
  appelant existant. Walk-Forward exécute ensuite `optimizer._run_single()` **exactement une
  fois** par fold (réutilisée telle quelle) — jamais le comportement multi-candidats actuel.
- **`VALIDATION`** (zone du `DatasetSplitPlan`, jusqu'ici jamais peuplée — vérifié :
  `results/dataset_splits/split_perfect_revolution_v1_final_holdout/split_plan.json` a
  `validation: null`) devient le conteneur macro des folds. **Prérequis d'implémentation identifié,
  non résolu par cette mission** : construction d'un nouveau `DatasetSplitPlan` avec `VALIDATION`
  peuplée (`FINAL_HOLDOUT` inchangé, `2025-05-19` → `2026-05-20`), avant tout premier fold réel.
- **`FINAL_HOLDOUT`** structurellement inaccessible (aucune référence dans les objets Walk-Forward,
  jamais un fold implicite, `FinalHoldoutOverlapError` en garde défensive).
- **Taxonomie d'erreurs consolidée** : 10 nouvelles (`UnsupportedWalkForwardGeometry`,
  `DatasetTooShortForWalkForward`, `InsufficientWarmupHistory`, `NonDeterministicSearchWithoutSeed`,
  `NoEligibleTrainCandidate`, `FinalHoldoutOverlapError`, `WalkForwardResumeMismatch`,
  `WalkForwardSemanticsMismatch`, `FoldArtifactConflict`, `OosOverlapError`) + 1 réutilisée
  (`NoStateReadyBoundary`) — 3 candidates de la proposition initiale écartées par redondance
  (`NoValidWalkForwardFold`, `EmptyTrainWindow`, `EmptyTestWindow`).
- **Verdict scientifique séparé de la preuve factuelle** : `PASS` structurellement impossible sans
  `verdict_policy_id` pré-enregistré (sinon `INCONCLUSIVE` systématique) — jamais une décision
  Champion (hors scope, `GATE V` reste distincte de toute future notion Champion).
- **Persistance additive** : `results/job_xxx/walk_forward/` (manifest/state/folds/aggregate/
  `validation_run.json`), fingerprint de reprise à 3 versions de sémantique + seed + politique de
  verdict, `atomic_json_store.py` réutilisé sans duplication.
- **Compléments ajoutés lors de la mission de clôture Git (2026-09-14), répartis sur les Décisions
  1, 4, 6, 13, 14, 15** — trouvés manquants par la relecture finale ciblée (checklist explicite de
  la mission), pas des changements scientifiques : des clarifications de décisions déjà arrêtées
  mais jamais transcrites (attribution exacte corrigée ici après une 1ʳᵉ version de cette section
  qui les regroupait tous, à tort, sous « Décisions 14/15 » — trouvaille `/code-review` de cette
  même mission de clôture) :
  - **Décision 1** : `allow_partial_last_fold=False` (dernier segment incomplet enregistré, jamais
    exécuté ni compté).
  - **Décision 4** : notation explicite `TRAIN_k = [train_start_k, effective_boundary_k)`
    (symétrique de `TEST_k`, déjà présente).
  - **Décision 6** : `_run_single()` réelle jette `trades`/`equity` (`optimizer.py:266`) — la phase
    TEST d'un fold doit donc l'appeler différemment (paramètre renvoyant aussi `trades`/`equity`,
    ou appel direct à `run_backtest()`) pour produire `oos_trades.csv`/`oos_equity.csv` (Décision
    12) et `FoldResult.expectancy` (métrique introduite par Walk-Forward lui-même, PnL net moyen
    par trade — `engine.py` n'a pas de champ `expectancy` natif, `CONTEXT.md` le documente comme
    non défini projet-wide).
  - **Décision 13** : séparation explicite `execution_status`/`scientific_verdict` (une erreur
    technique n'est jamais traduite en `FAIL` scientifique).
  - **Décision 14** : `position_transition_policy="flat_each_fold_v1"` (instance `Strategy()`
    fraîche, capital initial identique, aucune position/PnL hérité par fold) ; absence explicite de
    rétroaction TEST inter-fold (search space/scoring/seed/budget gelés pour tout le run, seules
    les DONNÉES avancent dans le temps, jamais les résultats — distinct de la reprise/Décision 12,
    qui ne fait que sauter les folds déjà terminés, jamais lire leur résultat pour en influencer un
    autre).
  - **Décision 15** : agrégation OOS — **trades concaténés littéralement** (PF/win-rate insensibles
    au capital de base) mais **courbe d'équity reconstruite par rendements normalisés chaînés**
    (jamais une concaténation brute des capitaux absolus, qui donnerait un artefact en dents de
    scie puisque chaque fold repart du même capital) ; `oos_profit_factor = gross_win_total /
    gross_loss_total` (mêmes noms que `engine.py`, `float("inf")` si `gross_loss_total==0` avec
    trades — jamais `None` dans ce cas, jamais une moyenne de `profit_factor` par fold) ;
    zéro-trade TEST = observation valide, jamais un `FAIL` automatique.
- **`/domain-modeling`, `/codebase-design`, `/grill-with-docs`, `/to-spec`, `/tdd` (conception de
  matrice uniquement), `ui-ux-pro-max` (revue d'exploitabilité backend, aucune UI codée)**
  réellement invoqués. `/code-review` exécuté sur le diff documentaire de cette mission (2
  sous-agents `general-purpose`, axes scientifique/architecture et reproductibilité/documentation)
  — **0 blocker, 4+2 important, 3+5 minor**, tous corrigés dans l'ADR/cette section avant clôture :
  prémisse explicite d'un `base_params` unique partagé par tous les folds pour la résolution
  readiness (Décision 4) ; réutilisation de `NoStateReadyBoundary` comme TYPE seulement, messages
  reconstruits par fold (Décision 11) ; absence de double résolution de frontière grâce à
  `train_test.enabled=False` sur l'appel `Optimizer.run()` par fold (Décision 6) ; paragraphe
  "Zones consommées" de la roadmap resynchronisé avec la Décision 8. `/implement`, `/to-tickets`,
  `/speckit-*` **non invoqués** (mission de conception, pas d'implémentation ni de spec Kit).
- **Mission de clôture Git distincte (2026-09-14)** — relecture finale ciblée sur checklist
  explicite (24 points), `/grill-with-docs` + `/code-review` (1 sous-agent `general-purpose`)
  réellement invoqués pour CETTE mission (ne pas confondre avec la revue de la mission de
  conception ci-dessus) : **0 blocker, 3 important, 1 minor**, tous corrigés — attribution exacte
  Décisions 1/4/6/13/14/15 (une 1ʳᵉ version de cette section les regroupait à tort sous « 14/15 
  seulement ») ; `expectancy` explicitement défini comme métrique introduite par Walk-Forward
  (jamais un champ `engine.py` natif) et dépendance technique identifiée (`_run_single()` jette
  `trades`/`equity`) ; réconciliation trades-concaténés-littéralement vs équity-normalisée-chaînée
  entre Décisions 14/15. `/simplify` invoqué mais jugé non pertinent mécaniquement pour un diff
  purement documentaire (ses 4 axes — reuse/simplification/efficiency/altitude — sont conçus pour
  du code) ; vérification manuelle de redondance effectuée à la place, aucune trouvée au-delà du
  style déjà établi par ce document. `ui-ux-pro-max` confirmé sans régression sur le contrat
  d'exploitabilité UI déjà validé.
- **Prochaine mission unique recommandée** : `AF-V-02` — implémentation TDD du Walk-Forward V1
  conformément à `docs/adr/0021-*.md` et à la spec figée — **non commencée dans cette mission**.

## 22. Vision produit / UX synchronisée avant Autopilot — documentaire uniquement (2026-09-16)

**Priorité immédiate inchangée : `AF-V-02` (Walk-Forward).** Statut au moment de cette mission :
Slice 1 (DatasetSplitPlan `VALIDATION` + cœur géométrique déterministe) **implémentée en local,
non committée** (`AF-V-02 implementation: IN PROGRESS`, `GATE V: NOT PASSED` — voir le rapport de
la mission Slice 1 pour le détail ; ce §22 ne touche ni ne documente ce travail en détail, mission
strictement documentaire produit/UX, aucun code modifié). Checkpoint Git au début de cette mission :
`4680448cf4324ae3b33480fc8baf1345eedb214c` (= `origin/master`, divergence `0 0`).

## 23. AF-V-02 Slice 1 — géométrie déterministe Walk-Forward committée (2026-09-17)

Sécurisée et committée à l'ouverture de la mission Bootstrap Autopilot (autorisation explicite de
commit/push accordée par cette mission — voir son rapport pour la politique complète). Travail
réalisé lors de la mission Slice 1 précédente (2026-09-15/16), resté non committé jusqu'ici ;
aucune modification de code entre-temps, uniquement re-vérifié vert avant commit
(122/122 ciblés, suite complète re-confirmée dans le rapport de cette mission).

- **Contenu** : `WalkForwardSpecification`/`FoldDefinition`/`FoldSelection`/`FoldResult`/
  `AggregateResult`/`WalkForwardEvidence` (`validation_run.py`, registre `_VALIDATION_TYPES`
  étendu) ; `walk_forward.py` (géométrie Rolling déterministe, guards FINAL_HOLDOUT/overlap,
  `WALK_FORWARD_SEMANTICS_VERSION="rolling-calendar-v2"`) ; nouveau `DatasetSplitPlan`
  (`split_perfect_revolution_v1_walk_forward_v1`, zone `VALIDATION` peuplée, `FINAL_HOLDOUT`
  inchangé, plan historique jamais modifié) via `scripts/create_walk_forward_validation_split_plan.py`.
  Détail complet : rapports des missions Slice 1 et de correction terminale (2026-09-15/16),
  `docs/adr/0021-walk-forward-rolling-calendar-v1.md`.
- **Non inclus dans cette tranche** (Slice 2+, toujours non commencé) : Optimizer TRAIN-only réel,
  sélection Top-1 réelle, exécution TEST OOS réelle, persistence complète, agrégation OOS réelle,
  reprise complète, Monte-Carlo, Parameter Stability.
- **Statut** : `AF-V-02 implementation: IN PROGRESS`. `GATE V` reste **NON PASSÉE**.

**Ce qui a changé** : la vision produit long terme (« AlphaForge = Strategy Factory », pas un
simple backtester) et la direction UX/UI sont désormais documentées séparément, pour qu'un futur
Autopilot puisse distinguer le présent (AF-V-02, validation scientifique) du futur (tout le reste)
sans jamais confondre documentation produit et preuve d'implémentation :

- **`docs/product/PRODUCT_VISION_V2.md`** — Strategy Factory : Feature Registry massif, génération
  automatique de stratégies, contrôle combinatoire, méthodes de Discovery, multi-objectifs/Pareto,
  régimes de marché, Strategy Genealogy, conservation des échecs, détection de similarité,
  diversification, Portfolio Engine, replay de trade, audit automatique, budget de calcul, early
  stopping, construction sans code, export ProRealTime/ProOrder, Paper/Forward testing, Strategy
  Health. Chaque capacité rattachée à un track/gate déjà existant dans `MASTER_ROADMAP.md`
  (§9 y référence ce document) — **aucun nouveau track, aucune nouvelle gate, aucun réordonnancement**.
- **`docs/ux/UX_UI_PRODUCT_DIRECTION.md`** — langue française, mode guidé/expert, interprétation
  des métriques, niveau de preuve (Evidence Ladder), séparation stricte Performance ≠ Robustesse,
  design system (direction visuelle), grammaire de statuts. Complète, sans le dupliquer,
  `docs/architecture/UI_UX_ARCHITECTURE.md` (architecture de code/navigation technique, inchangé).

**Statuts utilisés, strictement** : `ACCEPTED PRODUCT DIRECTION / IMPLEMENTATION DEFERRED` pour
la quasi-totalité (sauf preuve contraire déjà présente dans le dépôt) ; `PLANNED / DEFERRED` pour
Portfolio Engine (track/gate déjà nommés) et ProRealTime/Paper-Forward ; `PROPOSED / DEFERRED`
pour Strategy Health (déjà `FUTURE` dans `DOMAIN_MODEL.md` §15). **Rien n'est déclaré
`IMPLEMENTED`/`TESTED`/`DONE`.**

**Tensions signalées, non résolues par cette mission** (voir les deux documents pour le détail) :
navigation produit à 12 espaces (mission) vs 10 espaces déjà documentés
(`UI_UX_ARCHITECTURE.md` §2) ; thème « clair premium » visé vs thème sombre actuel
(`.streamlit/config.toml`). Deux concepts de domaine nouveaux identifiés sans être définis
(`Strategy Genealogy`, `Rejected Strategy History`) — nécessitent une future session
`/domain-modeling` réelle avant toute conception.

**Aucune fonctionnalité listée dans ces deux documents n'a été implémentée par cette mission.**
Aucun contrat scientifique existant (`exact-boundary-v2`/`daily-state-ready-v1`/
`rolling-calendar-v2`) n'a été modifié.

## 24. AlphaForge Autopilot — Bootstrap V1 (2026-09-17)

Superviseur autonome auditable, construit AU MILIEU d'AF-V-02 sans interrompre ni recommencer le
travail en cours (mission « Bootstrap AlphaForge Autopilot V1 en cours d'AF-V-02 »). AF-V-02
Slice 1 (voir §23) a été sécurisé et committé (`2a9a6da`, `efe49ef`, poussés) **avant** tout
travail de Bootstrap — aucune modification étrangère mélangée dans ces commits, aucun travail
perdu.

- **Package** : `scripts/autopilot/` — `state_machine.py` (18 états, table de transitions
  explicite, persistance atomique via `atomic_json_store.save_atomic_overwrite()`, nouvelle
  fonction additive, comportement de `save_atomic()` inchangé), `git_safety.py` (liste fermée de
  motifs interdits : force push, `--no-verify`, `reset --hard`, `clean` destructeur, suppression
  de branche distante, `add -A/./--all` ; fichiers protégés ; espace disque ; détection de
  secrets/gros fichiers ; anti-boucle), `quota_detector.py` (classification prudente, jamais
  "quota" par défaut), `human_gate.py` (rapport français structuré, 1-3 options, une seule
  recommandée), `mission_queue.py` (file avec dépendances), `claude_invoker.py` (argv réel,
  flags confirmés `claude --help` v2.1.220, jamais `--dangerously-skip-permissions`),
  `supervisor.py` (machine à états pilotée pas à pas, idempotente/reprenable, verrou
  mono-instance, `FakeGitOps`/`RealGitOps` — toute opération Git passe par `git_safety` avant
  exécution), `cli.py` (`status`/`stop` pleinement fonctionnels ; `start`/`resume` construisent
  le superviseur réel mais **jamais exécutés en conditions réelles par cette mission**),
  `hooks/pre_bash_safety_check.py` (hook `PreToolUse`, testé par sous-processus réel).
- **`.claude/settings.json`** (nouveau, versionné) : allowlist précise pour les opérations
  ordinaires (git non destructif, pytest, py_compile), denylist explicite (force push,
  `--no-verify`, `reset --hard`, `clean -f*`, `add -A/./--all`, `branch -D`, écriture sur
  `app_corrupted_backup.py`/`nasdaq_3m.csv`), hook `PreToolUse` sur l'outil Bash.
- **`.autopilot/`** (nouveau) : `policy.json` (résumé lisible, l'application réelle testée reste
  dans `git_safety.py`), `missions.json` (file — **volontairement un seul gabarit `BLOCKED`**,
  AF-V-02 Slice 2 n'y a pas été placée automatiquement, voir `prompts/example.md` pour la
  justification), `README.md` (documentation complète + limites connues, honnêtes).
  `.autopilot/state/` (runtime, verrou/état/historique) ajouté à `.gitignore`, jamais versionné.
- **Tests** : 121 (`tests/test_autopilot_*.py` ×9, `tests/test_atomic_json_store.py`) — TDD
  strict (RED confirmé avant chaque module) puis 9 tests de régression ajoutés après la revue
  indépendante (voir ci-dessous), aucun sous-processus Claude/Git réel dans la suite (doublures
  injectées + un seul test d'intégration réelle du hook via sous-processus Python, sans commande
  Git). Suite complète : **1131/1131** (1010 + 121).
- **Bugs réels trouvés et corrigés pendant l'implémentation** (TDD, pas seulement en revue) :
  `SingleInstanceLock.release()` ne libérait pas un verrou détenu par une AUTRE instance de
  process (`cmd_stop` s'exécute toujours dans une invocation séparée de celle qui a démarré la
  boucle) — corrigé par `force_release()`, dédié à l'arrêt externe, distinct de `release()`
  (libération par le détenteur lui-même) ; retenter une même phase (`DEVELOPING`/`TESTING`) via
  `transition_to()` violait la table de transitions (pas de self-loop autorisé dans
  `ALLOWED_TRANSITIONS`) — corrigé par `AutopilotStateStore.update()`, une mise à jour de champs
  SANS transition, distincte de `transition_to()`.
- **`/code-review` exécuté** (2 sous-agents `general-purpose` indépendants, axes
  sécurité/architecture et reproductibilité/scope). Axe reproductibilité/scope : 0 BLOCKER, 2
  IMPORTANT (nombre de tests obsolète dans `.autopilot/README.md`, référence à cette section avant
  qu'elle n'existe — lecture antérieure à l'édition, résolu), 1 MINOR (fichier étranger
  préexistant `=1.12.0`, non touché, hors scope). Axe sécurité/architecture : **3 BLOCKER
  empiriquement reproduits**, tous corrigés avant commit :
  1. `ALLOWED_TRANSITIONS[PLANNING]` n'incluait pas `COMPLETED` alors que `_handle_planning()` y
     transitionne si la file de missions se vide entre deux relectures (état et file sont deux
     fichiers séparés) — `IllegalTransitionError` en reprise réaliste. Corrigé (arête ajoutée +
     test dédié).
  2. `ALLOWED_TRANSITIONS[DEVELOPING]` n'incluait pas `WAITING_FOR_EXTERNAL_RESOURCE` alors que
     `_handle_failure()` y route toute `FailureCategory.NETWORK` — une erreur réseau ordinaire
     crashait le superviseur. Corrigé (arête ajoutée + test dédié).
  3. `ALLOWED_TRANSITIONS[TESTING]` n'incluait ni `HUMAN_GATE_REQUIRED` ni
     `WAITING_FOR_EXTERNAL_RESOURCE`, ET `_handle_failure()` lisait `raw_output` — absent du
     contrat `tester_fn` (qui ne renvoie que `summary`) — donc classifiait TOUJOURS sur une
     chaîne vide : trois échecs de test consécutifs, un cas parfaitement ordinaire, crashaient tout
     le superviseur au lieu de déclencher l'anti-boucle prévue. Corrigé (arêtes ajoutées, repli
     `raw_output or summary` dans `_handle_failure()`, contrat `tester_fn` précisé, 2 tests dédiés).
  Plus 4 IMPORTANT, tous corrigés : (I1) un échec Git réel non couvert par `git_safety`
  (`RuntimeError` au commit/push) sortait de `run_one_step()` sans être rattrapé — `_handle_committing`
  route désormais vers `BLOCKED_SAFETY`, `_handle_pushing` vers `WAITING_FOR_EXTERNAL_RESOURCE`
  (déjà réservé pour ce cas par `state_machine.py` mais jamais atteint) ; (I2) `check_scope_files()`
  ne validait que les chemins passés à `add()`, jamais l'index Git réel au moment du commit —
  `RealGitOps.commit()` relit désormais `git diff --cached --name-only` et revalide l'index réel
  avant de committer ; (I3) aucun plafond de coût câblé sur le vrai point d'appel `real_developer_fn`
  malgré le support existant dans `claude_invoker` — `DEFAULT_MAX_BUDGET_USD=5.0` ajouté par
  défense en profondeur (le vrai point d'appel n'est de toute façon jamais exercé par cette
  mission) ; (I4) le commentaire d'en-tête de `resume.ps1` affirmait une reprise déjà câblée —
  corrigé pour refléter que `cmd_resume` reste un alias de `cmd_start` en V1. 3 MINOR restants,
  non bloquants et documentés tels quels (paramètre `retry_phase` mort — retiré ; TOCTOU du verrou
  mono-instance déjà partiellement disclosed ; pattern de deny `settings.json` non testable
  depuis cette session, `git_safety.py` restant la source de vérité réellement testée).
- **Limites V1 assumées, documentées dans `.autopilot/README.md`** : review indépendante non
  encore câblée réellement (`real_reviewer_fn` retourne toujours "propre") ; verrou mono-instance
  non robuste multi-OS (pas de détection de PID mort) ; historique anti-boucle non persisté à
  travers un crash réel (repart à zéro) ; tâche planifiée Windows non enregistrée par cette
  mission (scripts d'installation prêts, jamais exécutés) ; file de missions vide de tout vrai
  travail ; boucle réelle (`run_until()`) jamais câblée à `cmd_start`/`cmd_resume`.
- **`start`/`resume` n'ont jamais été exécutés pour de vrai** : aucune boucle autonome réelle
  n'a tourné, aucun `claude -p` récursif n'a été invoqué, aucun commit/push Autopilot réel n'a eu
  lieu — uniquement prouvé par tests avec doublures. Choix explicite, pas une incapacité :
  démarrer une boucle non supervisée avec accès push à `master` méritait d'être vu et approuvé
  par l'utilisateur au moins une fois avant d'être activé.
- **Statut** : `AF-V-02 implementation: IN PROGRESS` (inchangé par cette mission), `GATE V: NOT
  PASSED`. Bootstrap Autopilot committé séparément d'AF-V-02 (aucun mélange de scope).

## 25. AlphaForge Autopilot — V1.1, opérationnel et validé en conditions réelles (2026-09-17)

Mission « Autopilot V1.1 opérationnel », déclenchée par un contrôle externe jugeant le Bootstrap
V1 « validable comme socle technique, non validable comme Autopilot autonome prêt à être lancé ».
Autorisation explicite et en temps réel de l'utilisateur pour aller jusqu'à l'ignition réelle
(canary avec vrais appels `claude -p`, tâche planifiée Windows, démarrage réel de la boucle
autonome) — recueillie via une question directe avant tout travail à risque, distincte de
l'autorisation écrite standing des missions précédentes.

**Travail réalisé sur une branche/worktree isolé** (`autopilot/v1-1-operational`,
`C:\Users\Mira Alexandre\Desktop\backtest-nasdaq-revolution-autopilot-v11`), comme demandé par la
mission elle-même pour cette tranche à risque — jamais partagé avec l'index du dépôt principal.

**Le Bootstrap V1 (§24) est devenu un Autopilot réellement opérationnel** :

- `start`/`resume` exécutent RÉELLEMENT la boucle (`run_until()`) — n'annoncent plus jamais un
  succès sans qu'un superviseur ait réellement tourné.
- Le Developer réel lit le vrai `prompt_file` de la mission, son scope déclaré, les findings de
  review à corriger ; les fichiers modifiés viennent de l'état Git réel, jamais inventés.
- Le Reviewer est réellement indépendant : nouvelle session Claude à chaque appel (jamais
  `--resume` celle du développeur), sortie structurée validée par schéma JSON,
  `permission_mode="plan"` (ne peut jamais éditer de fichier).
- Le Tester exécute les `targeted_tests` de la mission d'abord, impose la suite complète pour un
  risque élevé ou des contrats scientifiques déclarés.
- Verrou mono-instance atomique et conscient du PID (Windows, `ctypes`/`OpenProcess`) ; signal
  d'arrêt coopératif vérifié entre chaque étape ; reprise réelle depuis `WAITING_FOR_CLAUDE`/
  `WAITING_FOR_EXTERNAL_RESOURCE` vers la phase interrompue (`resume_to_phase`) ; commit/push
  idempotents à travers un crash simulé (`last_commit_sha`/`last_push_sha`) ; un diagnostic
  indépendant est tenté une fois avant d'escalader un échec répété vers un Human Gate ; schéma de
  mission enrichi (scope/tests/risque/budget/preuves) et validé strictement — un fichier de
  missions absent/invalide route vers `BLOCKED_SAFETY`, jamais une file vide silencieuse.

**Canary réel de bout en bout, sans aucune doublure** : vraie sélection de mission, vrai
Developer (`claude -p` a écrit `.autopilot/canary/CANARY_MARKER.md` avec l'horodatage réel
demandé, strictement dans le scope autorisé), vrais tests ciblés, vrai Reviewer indépendant,
vrai commit (`f2e2611`), vrai push sur la branche isolée.

**Bugs réels trouvés et corrigés** (pendant le canary lui-même, ou en retraçant précisément ses
conséquences — pas seulement en revue statique) :

1. `sys.executable` vs un chemin `.venv` codé en dur — cassait dans tout déploiement sans `.venv`
   local sous `REPO_ROOT` (le worktree isolé de cette mission même).
2. Décodage Windows non explicite (`cp1252` par défaut) — a fait planter un thread lecteur
   `subprocess` sur le premier caractère accentué (dépôt en français) ; corrigé partout
   (`encoding="utf-8", errors="replace"` explicite).
3. **Trouvaille la plus sérieuse** : la sortie structurée du Reviewer réel s'est révélée
   silencieusement mal interprétée — la review indépendante réelle du canary a retourné
   `"0 finding(s) — verdict=?"`, le `?` trahissant un échec de parsing de `result` (chaîne
   JSON potentiellement entourée de texte) retombant sur `body={}`, indiscernable d'une review
   authentiquement propre. Un second sondage réel (`claude -p --json-schema`) a révélé un champ
   `structured_output` natif jusque-là ignoré. Corrigé : `structured_output` devient la source
   prioritaire ; l'absence de `verdict`/`findings` est désormais un échec TECHNIQUE de la review,
   jamais un "propre" silencieux — **un commit/push avait eu lieu sur la base de cette review
   défaillante avant que le bug ne soit trouvé et corrigé** (le contenu commité restait conforme
   au scope/aux tests, aucune donnée corrompue, mais la garantie d'indépendance de la review
   n'était, de fait, pas au rendez-vous pour ce cycle précis).
4. Le flip `DONE` d'une mission dans `missions.json` avait lieu APRÈS le push
   (`_handle_next_mission()`) — jamais committé ni poussé ; un fresh checkout/pull aurait revu la
   mission comme `PLANNED` et aurait pu la re-sélectionner/la ré-exécuter. Déplacé dans
   `_handle_committing()`, même commit que le travail de la mission, idempotent.
5. `mission.requires_clean_worktree` (schéma, défaut `True`) déclaré mais jamais vérifié —
   exactement le scénario qui avait pollué le scope du canary lui-même (édits d'ingénierie non
   committés mélangés au travail du canary, `changed_files` reflétant tout le working tree dirty).
   Réellement câblé dans `_handle_planning()`.
6. Une mission disparaissant en cours de route (`missions.json` corrompu/modifié pendant
   DEVELOPING/TESTING/REVIEWING/CORRECTING) laissait le Developer/Reviewer réel être invoqué —
   donc facturé — sur un contexte quasi vide avant que la corruption ne soit détectée à
   `COMMITTING`. Bloque désormais immédiatement, avant tout appel réel.

**Coût réel observé** (deux sondages `claude -p --output-format json` indépendants) : ~0,32-0,41 $
pour UN SEUL tour, même trivial — dominé par la création de cache du contexte projet
(CLAUDE.md/mémoire/skills, ~53-57k tokens), pas par le travail demandé. `DEFAULT_MAX_BUDGET_USD`
porté à `3.0` (`5.0` initialement supposé au Bootstrap, jamais vérifié empiriquement à l'époque).

**Revue indépendante** (2 sous-agents `general-purpose`, axes sécurité/architecture et
reproductibilité/scope, sur le diff complet `39e002a...HEAD`) — les points 5 et 6 ci-dessus ont
été trouvés/confirmés par l'axe reproductibilité/scope (le point 3 avait déjà été détecté et
corrigé avant la revue via un second sondage empirique indépendant, la revue l'a confirmé réglé).
L'axe sécurité/architecture a trouvé **3 BLOCKER supplémentaires, tous empiriquement reproduits**,
tous corrigés :

7. `ALLOWED_TRANSITIONS[REVIEWING]` n'incluait pas `HUMAN_GATE_REQUIRED`, alors que
   `_handle_reviewing()` route un échec technique de review (exactement ce que produit un Reviewer
   réel qui échoue à produire une sortie exploitable — voir point 3) à travers le même
   `_handle_failure()` que DEVELOPING/TESTING/CORRECTING. Un échec de review répété, pourtant
   ordinaire, crashait tout le process avec une exception non rattrapée — et comme l'état n'est
   jamais persisté avant l'échec de la transition, une reprise ultérieure retombait indéfiniment
   sur le même crash.
8. Le repli de `_resume_to_recorded_phase()` (`PLANNING`) n'était pas une transition légale depuis
   `WAITING_FOR_CLAUDE` — crashait toute reprise d'un fichier d'état antérieur à `resume_to_phase`
   (champ nouveau en V1.1, absent/`None` par défaut sur tout état pré-existant ou corrompu).
9. Sous Windows, `_pid_is_alive()` traitait TOUT échec `OpenProcess` comme "process mort" —
   y compris `ERROR_ACCESS_DENIED` (process bien vivant mais protégé/contexte de sécurité
   différent/EDR), indiscernable d'un PID réellement inexistant. Permettait de voler un verrou
   activement détenu par un process vivant. Corrigé : seul `ERROR_INVALID_PARAMETER` (via
   `GetLastError()`) est désormais traité comme une preuve de mort.

Plus 2 IMPORTANT : plusieurs commandes Git en lecture seule (`status`/`diff`/`rev-parse`/
`merge-base`) contournaient encore `git_safety.check_git_command()` malgré la promesse
documentée du module (aucune n'était exploitable aujourd'hui — liste noire, aucune de ces
sous-commandes dessus — mais une future règle les aurait silencieusement ratées), routées
désormais via un `_run_readonly_git()` partagé ; aucun sous-processus réel (git/`claude -p`/
pytest) n'avait de `timeout=`, rendant le signal d'arrêt coopératif sans effet pratique pendant
un appel bloqué — bornes ajoutées partout (généreuses, jamais limitantes pour un travail légitime).

**Tests** : 180 tests Autopilot dédiés (123 nouveaux/modifiés depuis le Bootstrap V1), tous verts.
Suite complète du projet : 1190/1190.
Suite complète du projet également verte.

## 26. AlphaForge Autopilot — Finalisation sécurité opérationnelle, worktree permanent (2026-09-17)

Mission « Finaliser la sécurité opérationnelle et débloquer AF-V-02 Slice 2 », déclenchée après
qu'une tentative d'ignition réelle depuis le dossier principal a été refusée par
`requires_clean_worktree` : des modifications préexistantes de l'utilisateur (`AGENTS.md`, ADR
0016, `docs/agents/skills-usage.md`, `=1.12.0`) étaient présentes dans l'index au moment de
`cmd_start`. Décision explicite de l'utilisateur : conserver ces fichiers intégralement dans le
dossier principal (jamais commit/stash/modification) et exécuter l'Autopilot depuis un **worktree
Git permanent dédié**, plutôt que d'exiger une décision humaine sur leur sort. L'état
`BLOCKED_SAFETY` original est archivé tel quel dans
`.autopilot/archive/2026-09-17-blocked-safety-main-repo-dirty-worktree.md` (worktree permanent).

**Worktree permanent** : `C:\Users\Mira Alexandre\Desktop\backtest-nasdaq-revolution-autopilot-permanent`,
branche `autopilot/permanent`, créé depuis `origin/master` au checkpoint vérifié `f979e76`.
`.venv/` : jonction NTFS vers le `.venv/` du dossier principal (aucun téléchargement dupliqué) ;
`nasdaq_3m.csv` copié (gitignoré). Verrou mono-instance et signal d'arrêt rendus VRAIMENT globaux
au dépôt (`git rev-parse --git-common-dir`, jamais `.autopilot/state/` qui est propre à chaque
worktree) — un superviseur démarré depuis le dossier principal OU le worktree permanent ne peut
plus jamais tourner en concurrence avec un autre sur la même file. Worktree conservé durablement
(jamais supprimé), contrairement aux worktrees jetables des missions précédentes.

**Canary réel de bout en bout exécuté dans ce chemin d'exécution permanent** (aucune doublure) :
Developer réel a corrigé un bug intentionnel, disclosed, sur une fixture canary jetable
(`scripts/autopilot/canary_fixture.py`, jamais du code scientifique) ; tests ciblés réels passés ;
Reviewer indépendant réel a couvert exactement les 2 fichiers attendus, 0 finding ; commit+push
réel (`67f7db7`) sur la branche distante dédiée `autopilot/canary-test`, jamais `master`. La boucle
a ensuite automatiquement enchaîné, comme prévu par sa propre autorisation, sur la mission
scientifique réelle `AF-V-02-SLICE-2` (PID réel, verrou détenu, `claude -p` en train de modifier
`optimizer.py`/`walk_forward.py` selon ADR 0021 Décision 6).

**Arrêt coopératif exercé en conditions réelles** : sur instruction explicite de sécuriser le
superviseur avant de laisser Slice 2 se poursuivre, `autopilot stop` a été invoqué pendant que ce
process réel tournait. Confirmé : le signal d'arrêt n'a PAS forcé la libération du verrou (détenu
par un process vivant) ; la frontière d'effet exacte est entre deux `run_one_step()` — la phase
`DEVELOPING` en cours a fini et persisté sa transition vers `TESTING` (le code écrit par le
Developer restant intact, non commité), puis la boucle s'est arrêtée avant d'invoquer
`tester_fn()`. Aucun test, aucune review, aucun commit/push n'a eu lieu pour Slice 2 dans cet
arrêt. Le process a quitté proprement, libérant lui-même son verrou.

**7 corrections apportées, chacune avec un test de régression écrit rouge avant correction** —
6 trouvées par une paire de revues indépendantes (sécurité/architecture, reproductibilité/scope)
sur la mission de finalisation précédente, plus 1 trouvée en auditant l'état réel du process Slice
2 en cours :

1. `_handle_correcting()` ne perd plus les findings de review/test ORIGINAUX lors d'un échec
   technique transitoire et sans rapport du Developer — préservés et combinés à la nouvelle note
   d'échec, jamais remplacés.
2. `_invoke_safely()` (nouveau) enveloppe les 4 points d'appel `developer_fn`/`tester_fn`/
   `reviewer_fn` — une exception non gérée d'un de ces callbacks ne crashe plus jamais le
   superviseur hors `COMMITTING`/`PUSHING`, convertie en échec ordinaire classifié normalement.
3. `_git_common_dir()` rattrape désormais une exception du sous-processus Git (pas seulement un
   code de retour non nul) et se replie sur une résolution PAR LECTURE DIRECTE de `.git`/
   `commondir` — jamais un `repo_dir/".git"` brut qui produirait un verrou différent par worktree.
4. La couverture de review (`reviewed_files`) devient OBLIGATOIRE avant tout commit — une liste
   absente ou vide avec des `artifacts` non vides bloque désormais systématiquement, jamais un
   contrôle opt-in contournable silencieusement.
5. Le diffing de review utilise désormais un INDEX GIT TEMPORAIRE (`GIT_INDEX_FILE`, seedé via
   `git read-tree HEAD`), jamais l'index réel (`.git/index`) — fermant un bug réel de pollution
   permanente (`intent-to-add` jamais nettoyé si une mission n'atteignait jamais `COMMITTING`,
   pouvant rendre `dirty_worktree` non résoluble pour toujours). Deux failles complémentaires,
   trouvées par les revues, ont aussi été fermées : le code de retour de `read-tree` est
   maintenant vérifié (un index sous-seedé montrait silencieusement un fichier modifié comme
   entièrement supprimé au Reviewer) ; l'aide nettoie désormais son propre répertoire temporaire
   en cas d'échec pendant sa propre initialisation.
6. Le cycle diagnostic précédant le Human Gate respecte désormais `retry_target` — une escalade
   originant de TESTING repasse réellement par `CORRECTING` (un vrai appel Developer), jamais un
   simple retour sur TESTING seul.
7. `_handle_planning()` réinitialise désormais `tests_status`/`review_status`/`reviewed_files`/
   `artifacts`/`developer_session_id`/`reviewer_session_id`/`stop_reason` au démarrage d'une
   nouvelle mission — ses preuves ne peuvent plus jamais être lues comme si elles concernaient la
   mission précédente.

Une note MINOR reste documentée sans bloquer l'activation : le préfixe textuel distinguant un
finding original d'une note de constat d'échec pourrait théoriquement entrer en collision avec un
finding réel commençant par cette même phrase exacte — jugé négligeable en pratique.

**Tests** : 201 tests Autopilot dédiés (52 dans `test_autopilot_supervisor.py`, 35 dans
`test_autopilot_cli.py`, plus les tests `claude_invoker`), tous verts. Suite complète du projet :
1243/1243, y compris le travail scientifique de Slice 2 laissé intact et non commité dans ce
worktree pendant toute cette mission.

**Publication** : commit `1ddb832` (les 4 fichiers de correction, isolé du travail scientifique de
Slice 2) poussé vers `origin/autopilot/permanent` (branche neuve, aucune divergence, jamais
`master`) — SHA local et distant vérifiés identiques après push.
