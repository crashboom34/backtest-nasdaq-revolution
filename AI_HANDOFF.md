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

**Tests** : 206 tests Autopilot dédiés (52 dans `test_autopilot_supervisor.py`, 39 dans
`test_autopilot_cli.py`, plus les tests `claude_invoker`), tous verts. Suite complète du projet :
1261/1261, y compris le travail scientifique de Slice 2 laissé intact et non commité dans ce
worktree pendant toute cette mission.

**Publication** : commit `1ddb832` (les 4 fichiers de correction, isolé du travail scientifique de
Slice 2) puis `3378d36` (documentation) poussés vers `origin/autopilot/permanent` (branche neuve,
aucune divergence, jamais `master`) — SHA local et distant vérifiés identiques après chaque push.

### Reprise réelle de Slice 2 — 2 bugs opérationnels réels supplémentaires trouvés et corrigés

La reprise effective (`autopilot resume`) depuis l'état `TESTING` sauvegardé a réellement exécuté
la suite de tests ciblée (1257 passed), puis une review indépendante réelle a trouvé 3 findings
bloquants sur le code Walk-Forward, corrigés par un vrai cycle Developer, puis une seconde review
réelle en a trouvé 3 autres — dont un **BLOCKER scientifique réel** : `run_fold_test()` ramène
silencieusement `score_test` à `0.0` dès qu'une exécution TEST authentique (trades réels,
métriques saines) échoue un filtre d'éligibilité pensé pour TRAIN (`FilterConfig.min_trades`
notamment), masquant exactement le signal de sur-apprentissage que le Walk-Forward existe pour
révéler — reproduit empiriquement par le Reviewer indépendant, jamais injecté. Plus 2 MAJOR :
`fold_seed` n'alimente jamais le RNG du mode de recherche `general`/échantillonnage stratifié
(reproductibilité non garantie) ; aucun test ne verrouille `end_boundary="inclusive"` côté TRAIN
(régression silencieuse non détectée par la suite actuelle, vérifié empiriquement par mutation).

Deux tentatives de review suivantes ont ensuite CRASHÉ de façon répétée (`exception non gérée dans
reviewer_fn`), épuisant `max_attempts=3` (5 tentatives avec diagnostic) et escaladant vers
`HUMAN_GATE_REQUIRED` — la cause réelle, retrouvée en lisant `stdout`/`stderr` du process :
`FileNotFoundError: [WinError 206] Nom de fichier ou extension trop long`. Deux bugs opérationnels
réels, corrigés avec un test de régression chacun (commit `47af120`) :

1. **Le prompt `claude -p` était un ÉLÉMENT DE LA LIGNE DE COMMANDE** (`build_claude_argv()`
   l'ajoutait en dernier argument) — un lot de diff de review volumineux (walk_forward.py/ses
   tests, après deux cycles de correction) a dépassé la limite de longueur de ligne de commande de
   `CreateProcess` sous Windows (~32k caractères). Confirmé empiriquement
   (`echo "..." | claude -p --output-format json` répond correctement) : `claude -p` lit le
   prompt depuis STDIN en l'absence d'argument positionnel. `ClaudeInvoker`/`_real_run()`
   transmettent désormais TOUJOURS le prompt via `subprocess.run(..., input=prompt)`, jamais
   `argv` — plus aucune limite de longueur pratique de ce type.
2. **Le dernier `print()` du CLI plantait sur un `stop_reason` contenant un emoji** (le rapport
   Human Gate en inclut un) — la console Windows par défaut encode en `cp1252`, incapable de le
   représenter, masquant le VRAI code de sortie (`HUMAN_GATE_REQUIRED`) derrière un code de sortie
   1 générique de crash Python, alors que tout le travail réel (verrou libéré, état persisté)
   s'était déjà terminé correctement. Nouveau `_ensure_utf8_stdio()` (appelé en tête de `main()`)
   reconfigure `stdout`/`stderr` en UTF-8 avant tout affichage.

**État réel actuel de Slice 2 (non résolu, décision humaine requise)** : `HUMAN_GATE_REQUIRED`.
Le worktree permanent porte toujours le vrai code écrit (`optimizer.py`, `walk_forward.py`,
`tests/test_optimizer.py`, `tests/test_walk_forward.py`, non commité, intact). `pending_findings`
a été vidé par les cycles de correction déjà appliqués (les 3 premiers findings et probablement une
partie des 3 seconds) — le contenu exact des findings ci-dessus a été retrouvé dans
`.autopilot/state/current_state.json.history.json` (historique borné des transitions), jamais
perdu. Aucune transition automatique n'existe depuis `HUMAN_GATE_REQUIRED` (`ALLOWED_TRANSITIONS`
ne permet que `STOPPED`/`PLANNING`, et `PLANNING` rebloquerait immédiatement sur
`requires_clean_worktree` contre le propre travail non commité de Slice 2) — jamais contourné ni
forcé par cette mission, conformément à l'exigence explicite qu'un Human Gate reste une décision
humaine.

## 27. AF-V-02 Slice 3 — Orchestration multi-fold + agrégation OOS en mémoire (2026-09-18)

Mission « Poursuite du développement autorisé d'AlphaForge », donnant suite à la finalisation
opérationnelle (§26). **Autorisation permanente accordée par l'utilisateur** : les tranches AF-V-02
dérivées strictement du périmètre déjà décidé par l'ADR 0021 s'enchaînent désormais sans demande de
confirmation individuelle par tranche — consignée dans `.autopilot/README.md` (bornée : ne
supprime aucune protection scientifique/opérationnelle existante, voir ce document pour le détail
exact).

**Détermination de la tranche suivante, jamais devinée depuis le seul numéro** : dérivée de la
section « Ce qui N'EST PAS dans cette tranche » de Slice 2 (item 2, « Agrégation OOS multi-fold »)
et de l'ADR 0021 Décisions 14/15 — confirmée par lecture du code réel (aucun orchestrateur
multi-fold n'existait encore, `AggregateResult` déjà typé dans `validation_run.py` mais documenté
« forme figée, population différée »). Nouveau `.autopilot/prompts/af-v02-slice-3.md`, nouvelle
entrée `missions.json` (mêmes budget/risque/scope que Slice 2, `depends_on=["AF-V-02-SLICE-2"]`).

**Bug réel trouvé et corrigé avant le lancement** : `COMPLETED` n'avait aucune transition sortante
ni handler — un `autopilot start` relancé après l'ajout d'une nouvelle mission `PLANNED` à la file
restait bloqué indéfiniment sans jamais la remarquer (reproduit empiriquement : Slice 3 mise en
file après que Slice 2 avait déjà atteint `COMPLETED`, `autopilot start` n'a rien fait). Corrigé
par un nouveau `_handle_completed()` (mirroring exact de `_handle_ready()`) + `ALLOWED_TRANSITIONS
[COMPLETED] = (PLANNING,)`, TDD, revue indépendante (aucun BLOCKER/IMPORTANT), commit `5e6e60b`.

**Deux limites d'usage Claude réelles rencontrées et correctement gérées** (jamais un Human Gate
scientifique, conformément à la consigne explicite) :
1. Une réutilisation de la classification déjà corrigée en §26 (`"spend limit"`) a immédiatement
   renvoyé `WAITING_FOR_CLAUDE` sur un message similaire.
2. Une DEUXIÈME limite, de forme différente (coût réel non nul, `$0,56`, 7 tours, avant d'être
   interrompue), a également été classée `QUOTA_LIMIT` par les motifs génériques déjà présents
   (`"usage limit"`/`"limit reached"`) — aucun nouveau correctif nécessaire, la généralisation du
   §26 a tenu. État conservé exactement (`WAITING_FOR_CLAUDE`, `resume_to_phase=REVIEWING`), aucun
   plafond relevé, aucun budget réinitialisé, reprise simple via `autopilot resume` une fois la
   limite levée — le travail du Developer déjà réalisé (`walk_forward.py`/`validation_run.py`/
   `tests/test_walk_forward.py`) est resté intact et non perdu entre les deux pauses.

**Résultat réel, review indépendante comprise** : `AggregateResult` réellement peuplé selon la
Décision 15 (concaténation littérale des trades, courbe d'equity chaînée — jamais une concaténation
brute de capital, jamais une moyenne de ratios), aucune rétroaction inter-fold (Décision 14) prouvée
par test. Suite complète verte (1304/1304). Review indépendante réelle : 2 lots, 3 fichiers
couverts, aucun finding bloquant retenu au commit final. Commit réel `febe701e400ef37859444de767953fded412e8a2`,
poussé sur `origin/autopilot/permanent` puis intégré (fast-forward, aucun force-push, suite
complète revérifiée dans un worktree d'intégration dédié) sur `origin/master`.

**Dossier principal et `business-b2b/`** : intégralement préservés tout du long (jamais touchés).

**Prochaine tranche (non encore cadrée)** : Slice 4, dérivée de l'item 1 restant de la même liste
« hors scope » (persistance disque, ADR 0021 Décision 12 — `results/job_xxx/walk_forward/`,
manifest/state/fold/aggregate, `oos_trades.csv`/`oos_equity.csv`) — à spécifier avec la même
rigueur (prompt dédié citant les décisions ADR réelles, jamais un contenu supposé) avant mise en
file, une fois la forme exacte de l'orchestrateur de Slice 3 examinée.

## 28. AF-V-02 Slice 4 — Persistance disque Walk-Forward, crise d'espace disque réelle, et un catch-22 de reprise trouvé et corrigé (2026-09-19/20)

Suite directe de §27, même autorisation permanente. **Tranche déterminée sans deviner depuis le
numéro** : dérivée de la docstring réelle de `run_walk_forward()` (Slice 3) elle-même — « aucune
persistance disque, aucune reprise : ADR 0021 Décision 12 hors scope » — et de l'ADR 0021 Décision
12. Nouveau `.autopilot/prompts/af-v02-slice-4.md`, nouvelle entrée `missions.json`
(`depends_on=["AF-V-02-SLICE-3"]`).

**Crise réelle d'espace disque pendant l'exécution** (`C:` descendu à 1,34–1,4 Go libres) —
périmètre explicitement exclu par l'utilisateur (« ne prends pas en compte l'espace ») mais dont
l'EFFET sur l'Autopilot devait être corrigé : des échecs `pytest` réels causés par le manque
d'espace ont été mal classifiés comme des échecs de code répétés, escaladant à tort vers
`HUMAN_GATE_REQUIRED` (confondant une cause opérationnelle avec un problème scientifique). Corrigé
par un contrôle `git_safety.check_disk_space()` ajouté en tête de `_handle_testing()` (bloque
proprement en `BLOCKED_SAFETY`/`disk_space` AVANT d'invoquer `tester_fn`, jamais après coup) — ce
qui a révélé un second bug préexistant : 40 tests du superviseur lisaient le VRAI disque hôte,
jamais isolés (fixture `autouse` ajoutée dans `tests/test_autopilot_supervisor.py`). Espace
recouvré naturellement à 2,6 Go+ avant la fin de la mission (1308/1308 tests verts). 19 échecs
`EodhdStorageError` réels, non liés, dans un module de stockage de marché totalement indépendant
ont été identifiés comme 100 % attribuables à la même pénurie externe et documentés sans être
« corrigés » artificiellement — conformément à la consigne explicite de ne pas ouvrir de chantier
de stockage.

**Bug réel confirmé et corrigé — reprise automatique absente après une pause externe** :
l'utilisateur a signalé qu'une fois la limite de dépenses Claude réinitialisée, l'Autopilot ne se
relançait jamais seul. Root-cause à deux volets : (1) la tâche planifiée Windows
`AlphaForgeAutopilot` n'avait qu'un déclencheur `AtLogOn`, jamais de reprise périodique — corrigé
par un second déclencheur répétant `resume.ps1` toutes les 30 minutes (~10 ans, limite pratique du
schéma XML de Task Scheduler — `[TimeSpan]::MaxValue` produit une durée hors limites), sûr par
construction (verrou fichier réacquis à chaque tentative, aucun Human Gate jamais auto-résolu,
aucun plafond jamais relevé) ; `scripts/autopilot/install_task.ps1` mis à jour pour toute
installation future. (2) la classification disque ci-dessus, qui transformait une pause purement
opérationnelle en un blocage d'apparence scientifique.

**Catch-22 de reprise trouvé et corrigé en conditions réelles, commit `8375dc9`** — chaîne
d'événements réelle, jamais reproduite en synthèse a priori :
1. `_handle_pre_commit_check()`/`_handle_blocked_safety()` ont d'abord gagné une résolution
   automatique de la catégorie `unreviewed_files` (revérifie les chemins réellement sales contre
   `record.reviewed_files`, rafraîchit `record.artifacts` si résolu) — corrigeant un blocage
   permanent causé par des `record.artifacts` périmés référençant deux fichiers déjà committés
   séparément (`.autopilot/README.md`/`install_task.ps1`, édités directement pendant que Slice 4
   était en pause). Commit `2fcfccd`, revue indépendante propre.
2. La reprise périodique (30 min) suivante a exécuté ce nouveau code sur un enregistrement
   `BLOCKED_SAFETY`/`unreviewed_files` PERSISTÉ AVANT ce correctif — donc sans `resume_to_phase`
   fiable (le code antérieur ne le renseignait pas pour cette catégorie). La résolution a donc
   correctement reconnu la catégorie comme résolue, mais est retombée sur le repli `PLANNING` par
   défaut faute de cible fiable.
3. `_handle_planning()` a alors re-sélectionné la mission `AF-V-02-SLICE-4`, déjà en cours, et
   s'est re-bloqué en `BLOCKED_SAFETY`/`dirty_worktree` — son contrôle `is_worktree_clean()` étant
   global, jamais attribué à une mission, il a lu le travail LÉGITIME déjà testé (1325 tests) et
   déjà revu de Slice 4 comme une contamination. Un état qui ne pouvait plus jamais se résoudre
   seul (le worktree restant, par construction, « sale » tant que Slice 4 n'était pas committée).

**Corrigé en élargissant, plutôt qu'en reconstruisant, le mécanisme `resolve_human_gate()`** déjà
existant (finalisation §26) pour accepter `BLOCKED_SAFETY` comme phase courante résolvable, en plus
de `HUMAN_GATE_REQUIRED`, avec la même garde d'attribution (`_unattributable_paths()` contre
`mission.allowed_paths`). **Revue indépendante d'une première version a trouvé un vrai BLOCKER** :
hériter tel quel d'`ALLOWED_TRANSITIONS[BLOCKED_SAFETY]` aurait permis d'atteindre directement
`COMMITTING`/`PUSHING`/`READY` — des cibles sûres dans la boucle normale UNIQUEMENT après que
`_handle_blocked_safety()` revérifie la cause catégorielle précise (ex. `unreviewed_files` exige
`dirty ⊆ reviewed_files`, jamais recontrôlé par `_handle_committing()` lui-même), ce qui aurait pu
committer/pousser du code jamais confirmé revu. Corrigé en restreignant les cibles atteignables
depuis `BLOCKED_SAFETY` via cette méthode à un sous-ensemble prouvé sûr (identique à
`HUMAN_GATE_REQUIRED`, plus `PRE_COMMIT_CHECK` qui revérifie intégralement la couverture de revue).
Seconde revue indépendante : SAFE TO COMMIT. Commit réel `8375dc9`, poussé et intégré
(fast-forward, régression complète revérifiée) sur `origin/master`.

**Résolution réelle du blocage et achèvement de Slice 4** : `resolve_human_gate(resume_to=
PRE_COMMIT_CHECK, ...)` appliqué via la CLI pour la mission réellement bloquée, reprise réussie
jusqu'à `COMPLETED`. Suite complète verte (1325/1325). Review indépendante réelle : 2 lots, 2
fichiers couverts, 5 findings non bloquants. Commit réel
`3e4e1ad0f3a22ebefc69d06abd78cd1f6d1ed32b`, poussé sur `origin/autopilot/permanent` puis intégré
(fast-forward, régression complète 1332/1332 revérifiée dans le worktree d'intégration dédié) sur
`origin/master`.

**Dossier principal et `business-b2b/`** : intégralement préservés tout du long (jamais touchés).

**Prochaine tranche déjà cadrée et mise en file** : Slice 5, dérivée du dernier paragraphe de
Décision 12 lui-même et de la docstring réelle de `persist_walk_forward_run()`/
`build_walk_forward_manifest()` (Slice 4) — « aucune logique de reprise ne le relit encore (tranche
suivante) » / « reste entièrement à la charge de la tranche de reprise future (hors scope Slice 4)
». Portée : décision SKIP/REPLAY_TEST/REDO par fold à la reprise, réutilisation des candidats TRAIN
déjà exécutés d'un fold interrompu (investiguer d'abord la réutilisation du mécanisme déjà existant
d'`optimizer.py`/`optimization_store.py` avant d'en inventer un nouveau), agrégat recalculé
intégralement. Explicitement hors scope : `WalkForwardEvidence`/verdict scientifique (Décision 13,
tranche séparée ultérieure), Monte-Carlo/Parameter Stability, intégration `app.py`. Voir
`.autopilot/prompts/af-v02-slice-5.md` pour le détail complet.

## 29. AF-V-02 Slice 5 — Reprise Walk-Forward achevée ; Autopilot désactivé sur demande explicite (2026-09-20/21)

**L'Autopilot autonome est désactivé** : l'utilisateur a explicitement demandé son arrêt (« je ne
veux plus l'autopilot, desactive le, j'ai l'impression qu'il utilise trop de credits »). Le
processus alors actif (Slice 5, phase `CORRECTING`) a été arrêté immédiatement, et la tâche
planifiée Windows `AlphaForgeAutopilot` a été **désactivée** (`Disable-ScheduledTask`, jamais
supprimée — réversible via `Enable-ScheduledTask` + `autopilot resume`) : ses deux déclencheurs
(logon + reprise périodique 30 min, §28) ne se déclenchent plus. Rien n'a été perdu : l'état
persisté (`.autopilot/state/current_state.json`) et le travail réel non commité de Slice 5
(`walk_forward.py`/`tests/test_walk_forward.py`) sont restés intacts — l'arrêt d'un process en
cours d'exécution est un scénario déjà toléré par construction (idempotence Git, mission §3.8).
**Toute poursuite du développement AlphaForge se fait désormais manuellement** (par un humain ou
un agent Claude/Codex opérant directement dans ce worktree), jamais en relançant l'Autopilot sans
nouvelle demande explicite de l'utilisateur.

**Achèvement manuel de Slice 5** (travail déjà réalisé par le pipeline Developer/Reviewer de
l'Autopilot avant son arrêt — 1363/1364 tests, 1 seul finding MAJOR de revue restait à corriger) :
correctif appliqué manuellement, strictement dans le périmètre déjà cadré par
`.autopilot/prompts/af-v02-slice-5.md` (`walk_forward.py`/`tests/test_walk_forward.py`
uniquement), suivant la même discipline TDD/revue indépendante que tout le reste de cette mission.

**Finding MAJOR corrigé** : aucun test n'exerçait `resume_walk_forward_run()` avec
`spec.master_seed` réellement défini pour vérifier que `fold_seed` (ADR 0021 Décision 9) est bien
propagé au chemin `RESUME_ACTION_REDO` (`_redo_fold_reusing_train_candidates()`) — une régression
sur ce calcul (mauvais paramètre, ordre inversé, `fold.fold_id` au lieu de `fold.fold_index`)
n'aurait fait échouer aucun test existant. Nouveau test
`test_redo_propagates_the_same_fold_seed_run_walk_forward_would_have_produced` : compare le
`fold_seed` effectivement transmis lors d'un REDO après interruption à celui qu'un
`run_walk_forward()` non interrompu, sur le même `validation_run_id`/`fold_index`, aurait produit
— **passe du premier coup** contre le code déjà écrit (aucun bug réel, seulement un trou de
couverture, désormais comblé). Design du test confirmé non tautologique par une seconde revue
indépendante : la formule SHA-256 de `run_walk_forward()` (référence de comparaison) est déjà
ancrée indépendamment par un test sibling préexistant
(`test_no_cross_fold_feedback_base_config_and_seed_independent_of_prior_result`).

**Résultat réel, seconde revue indépendante comprise** : aucun autre BLOCKER/MAJOR trouvé sur
l'ensemble du diff (fingerprint-mismatch jamais traité comme SKIP silencieux ; aucun agrégat
partiel silencieux, `WalkForwardOrphanedFoldArtifacts` couvre une zone/readiness rétrécie entre
deux tentatives ; réutilisation `train_progress.csv` restreinte aux modes de recherche prouvés
sûrs, sélection Top-1 reconstruite identique à un REDO complet ; aucune rétroaction inter-fold).
Suite complète verte (1364/1364). Commit réel
`525f28fc2fc847d372c40352c9c15e8910b5b827`, poussé sur `origin/autopilot/permanent` puis intégré
(fast-forward, aucun force-push, régression complète 1364/1364 revérifiée dans le worktree
d'intégration dédié) sur `origin/master`.

**Dossier principal et `business-b2b/`** : intégralement préservés tout du long (jamais touchés).

**Prochaine tranche** : NON encore mise en file — contrairement aux slices précédentes, la
poursuite automatique enchaînée est suspendue tant que l'Autopilot reste désactivé. La prochaine
unité de travail resterait, par dérivation stricte de la même liste « hors scope » que Slice 4/5,
`WalkForwardEvidence`/`execution_status`/`scientific_verdict`/`verdict_reasons`/
`validation_run.json` (ADR 0021 Décision 13) — mais ne pas la cadrer/lancer sans confirmation
explicite de l'utilisateur sur la reprise du développement autonome.

## 30. AF-V-02 Slice 6 — WalkForwardEvidence achevée ; ADR 0021 (les 15 Décisions) désormais entièrement implémenté ; pause avant une décision d'allocation VALIDATION (2026-09-21)

**Reprise autorisée explicitement** par l'utilisateur : « Je confirme que tu peux reprendre
l'enchaînement automatique des unités déjà cadrées par les ADR, la roadmap et AI_HANDOFF.md. Il
n'est plus nécessaire de me demander une autorisation entre chaque slice. » — consommation normale
des crédits Claude autorisée, `HUMAN_GATE_REQUIRED` réservé aux seules décisions scientifiques/
produit réellement absentes des sources.

**Correction hors-bande nécessaire avant relance** : Slice 5 avait été terminée et fusionnée
manuellement (§29, commit `525f28f`) pendant que l'Autopilot était désactivé — le flip `DONE` de
`missions.json` et le repositionnement `COMPLETED` de l'état persisté, normalement effectués dans
le MÊME commit que le travail par `_handle_committing()`, n'avaient jamais eu lieu via la boucle
elle-même. Un premier `autopilot resume` aurait donc tenté de re-corriger un finding déjà résolu
sur un worktree déjà propre (processus arrêté immédiatement dès ce constat, avant toute
consommation réelle). Corrigé via les mêmes mécanismes que le superviseur utilise lui-même —
jamais une transition fabriquée pour contourner une garde : `mark_mission_status()` (flip DONE de
`AF-V-02-SLICE-5`) et `AutopilotStateStore.save()` (repositionnement à `COMPLETED`, `mission_id`
vidé, tous les champs de progression réinitialisés) — `_handle_completed()` (déjà testé, §27) a
ensuite revérifié la file normalement à la reprise suivante.

**Réactivation de l'Autopilot** : tâche planifiée Windows `AlphaForgeAutopilot` réactivée
(`Enable-ScheduledTask`, précédemment désactivée sur demande explicite §29) — vérifiée pointant
vers le worktree permanent, mêmes deux déclencheurs (logon + reprise 30 min, §28), une seule
instance (verrou fichier, vérifié absent avant chaque lancement).

**AF-V-02 Slice 6 — WalkForwardEvidence** (`.autopilot/prompts/af-v02-slice-6.md`, dérivée
strictement de la docstring déjà existante de `WalkForwardEvidence`/de l'absence totale de tout
mécanisme de politique de verdict dans ce dépôt — `OosValidationEvidence` ne porte aucun champ de
verdict) : `build_walk_forward_evidence(outcome, aggregate, verdict_policy_id) ->
WalkForwardEvidence` (nouveau, `validation_run.py`, mirroring `build_oos_validation_evidence()`) —
`execution_status` ∈ {`"completed"`, `"stopped_early"`} reflète `outcome.stopped_early` ;
`scientific_verdict` reste TOUJOURS `"INCONCLUSIVE"` sans `verdict_policy_id` (cas normal, aucune
politique concrète de seuils PASS/FAIL n'existe dans ce dépôt) ; reste `"INCONCLUSIVE"` même avec
un `verdict_policy_id` fourni si `stopped_early=True` (agrégat partiel, jamais un jugement
trompeur) ; lève `UnknownVerdictPolicy` (nouvelle exception, taxonomie Décision 11) pour tout
`verdict_policy_id` fourni sur un run complet — **aucun seuil scientifique inventé, refus explicite
plutôt qu'un verdict deviné**, exactement la contrainte rappelée par l'utilisateur. `walk_forward.py`
n'appelle PAS encore ce nouveau chemin (`build_walk_forward_evidence()` -> `build_validation_run()`
-> `save_validation_run()`) : choix documenté explicitement dans le code — `build_validation_run()`
exige `research_run_id`/`split_plan_id`/`dataset_snapshot_id`/`strategy_name`/`strategy_params`,
qu'aucun appelant réel ne transporte encore, câbler cela sans appelant réel serait spéculatif.
Suite complète verte (1370/1370). Review indépendante réelle : 1 lot, 2 fichiers couverts, 1
finding non bloquant. Commit réel `2a49b111778e0afb63b2c721118bbdd2898d3aad`, poussé sur
`origin/autopilot/permanent` puis intégré (fast-forward, régression complète 1370/1370 revérifiée)
sur `origin/master`.

**ADR 0021 (les 15 Décisions) est désormais entièrement implémenté** (Slices 1 à 6). Avant de
mettre en file une septième tranche, vérification explicite de ce qui reste réellement « cadré » :
la Décision 8 de l'ADR dit elle-même, verbatim, qu'« aucune borne précise pour `VALIDATION` n'est
fixée par cette ADR » et que « le choix exact de la durée/des bornes de `VALIDATION` (combien
d'années réserver à Walk-Forward vs. laisser à Discovery) reste un **prérequis d'implémentation à
trancher séparément**, pas une décision scientifique de cette ADR ». Le `DatasetSplitPlan` réel
(`split_perfect_revolution_v1_final_holdout`) a toujours `validation: null` — aucun plan réel avec
une zone `VALIDATION` peuplée n'existe. **Les trois candidats naturels de « tranche suivante »
convergent tous sur cette même décision non prise** : (a) construire un nouveau
`DatasetSplitPlan` avec `VALIDATION` peuplée (étape 0 explicitement identifiée par les
« Conséquences » de l'ADR, bloquée sur l'allocation exacte) ; (b) une politique concrète de
seuils PASS/FAIL (Décision 13, délibérément jamais inventée) ; (c) le câblage
`walk_forward.py` -> `build_validation_run()` (Slice 6, bloqué sur `split_plan_id`, donc sur (a)).
**Aucune de ces trois unités n'est « clairement définie par les documents du projet »** au même
titre que les Slices 1 à 6 (chacune dérivable sans ambiguïté d'une décision ADR à paramètres
concrets) — mise en file volontairement SUSPENDUE ici, conformément à l'instruction explicite de
l'utilisateur réservant `HUMAN_GATE_REQUIRED`/l'arrêt aux décisions scientifiques/produit
réellement absentes des sources, jamais à une invention silencieuse. L'Autopilot reste actif et
réactivable dès qu'une décision d'allocation `VALIDATION` (ou une politique de verdict, ou un
besoin app.py concret) est fournie par l'utilisateur.

## 31. AF-V-02 Slice 7 — Décision d'allocation VALIDATION fournie par l'utilisateur, nouveau DatasetSplitPlan v2 (2026-09-21)

**Décision explicite de l'utilisateur** (réponse directe à §30) : TRAIN macro (Discovery)
`[2017-10-31T00:00:00+00:00, 2020-11-19T00:00:00+00:00)`, `VALIDATION` (Walk-Forward)
`[2020-11-19T00:00:00+00:00, 2025-05-19T00:00:00+00:00)` (54 mois calendaires), `FINAL_HOLDOUT`
inchangé. Autorisation explicite de reprendre l'enchaînement automatique sans reconfirmation entre
slices, consommation normale des crédits Claude autorisée, `HUMAN_GATE_REQUIRED` réservé aux
décisions scientifiques/produit réellement absentes.

**Vérifié avec les fonctions calendaires réelles du dépôt AVANT mise en file** (jamais supposé) :
`compute_fold_definitions()` avec le préréglage Rolling par défaut (`P24M`/`P6M`/`P6M`) sur cette
zone produit EXACTEMENT 5 folds TEST non chevauchants, le dernier `test_end` tombant exactement sur
`VALIDATION.end`/`FINAL_HOLDOUT.start` (contigu, zéro écart), `detect_partial_tail()` retourne
`None`.

**Découverte importante faite avant la mise en file** : un premier `DatasetSplitPlan`
(`split_perfect_revolution_v1_walk_forward_v1`, `VALIDATION_MONTHS=42`, 3 folds) existait déjà —
décidé et committé lors de Slice 1 (2026-09-15/16, §23), **jamais explicitement confirmé par
l'utilisateur à l'époque**, jamais consommé par aucun code depuis. Artefact réel déjà présent sur
disque dans le checkout principal (`results/dataset_splits/.../split_plan.json`, `.gitignore`,
`created_at: 2026-09-15T05:35:40`). `DatasetSplitPlan` étant immuable, ce plan v1 et son script
(`scripts/create_walk_forward_validation_split_plan.py`) restent **intégralement intacts, jamais
modifiés ni supprimés** — la nouvelle décision de l'utilisateur construit un **second** plan sous
un `split_plan_id` distinct (`split_perfect_revolution_v1_walk_forward_v2`), jamais un écrasement.

**AF-V-02 Slice 7** (`.autopilot/prompts/af-v02-slice-7.md`) : nouveau
`scripts/create_walk_forward_validation_split_plan_v2.py` +
`tests/test_create_walk_forward_validation_split_plan_v2.py`, mirroring exact du script/tests v1
(Slice 1), `VALIDATION_MONTHS=54`. Suite complète verte (1379/1379), y compris les tests v1
inchangés (preuve que le plan/script v1 restent intacts). Review indépendante réelle : 1 lot, 2
fichiers couverts, 3 findings non bloquants. Commit réel
`88c9cf10b532a7e1b955c9161abf21d8ae2f9429`, poussé sur `origin/autopilot/permanent` puis intégré
(fast-forward, régression complète 1379/1379 revérifiée) sur `origin/master`.

**Exécution réelle du script, complétée après coup** : le worktree permanent Autopilot n'a pas
localement le plan historique (`results/` est `.gitignore`, chaque worktree Git a son propre
répertoire de travail non versionné, distinct du checkout principal) — la mission elle-même n'a
donc pas pu exécuter `main()` pour de vrai dans ce worktree. Complété manuellement après la
review : copie en LECTURE SEULE du fichier de données local `split_plan.json` historique depuis le
checkout principal (jamais une modification du checkout principal lui-même — un simple fichier de
données généré, `.gitignore`, au même titre que `nasdaq_3m.csv` déjà copié dans chaque worktree)
vers le worktree permanent, puis exécution réelle de
`python scripts/create_walk_forward_validation_split_plan_v2.py` — sortie vérifiée :
`TRAIN=[2017-10-31,2020-11-19)`, `VALIDATION=[2020-11-19,2025-05-19)`,
`FINAL_HOLDOUT=[2025-05-19,2026-05-20)` inchangé, plan historique non modifié. Artefact réel
produit à `results/dataset_splits/split_perfect_revolution_v1_walk_forward_v2/split_plan.json`
dans le worktree permanent (`.gitignore`, jamais commité — cohérent avec la convention déjà
établie pour `results/`).

**Dossier principal et `business-b2b/`** : intégralement préservés (le checkout principal n'a été
que LU, jamais modifié).

**Prochaine tranche candidate** : le câblage `walk_forward.py` -> `build_walk_forward_evidence()`
-> `build_validation_run()` -> `save_validation_run()`, explicitement laissé hors scope par Slice 6
faute d'un `split_plan_id` réel — désormais disponible
(`split_perfect_revolution_v1_walk_forward_v2`). Reste à concevoir précisément (quel appelant
fournit `research_run_id`/`strategy_name`/`strategy_params` — probablement une nouvelle fonction
additive dans `walk_forward.py`, jamais un appel automatique depuis `run_walk_forward()`/
`resume_walk_forward_run()` elles-mêmes).

## 32. AF-V-02 Slice 8 — Assemblage ValidationRun Walk-Forward achevé ; moteur ADR 0021 désormais complet de bout en bout ; pause avant exécution réelle/GATE V (2026-09-21)

**AF-V-02 Slice 8** (`.autopilot/prompts/af-v02-slice-8.md`), enchaînée automatiquement sans
reconfirmation (autorisation §31) : `build_walk_forward_validation_run(outcome, aggregate, spec,
split_plan, research_run_id, validation_run_id, strategy_name, strategy_params) -> ValidationRun`,
nouvelle fonction additive dans `walk_forward.py` (à côté de `persist_walk_forward_run()`) —
mirroring exact du précédent déjà établi par `validation_oos.py::run_oos_validation()` côté
`"oos"` : identifiants fournis TELS QUELS par l'appelant (jamais générés/devinés ici), assemble
`build_walk_forward_evidence()` (Slice 6, inchangée) puis `build_validation_run()` (inchangée),
**ne persiste rien elle-même** — un futur appelant explicite reste responsable de
`save_validation_run()`. `spec` sert directement de `specification` (contrairement à `"oos"`,
`WalkForwardSpecification` porte déjà l'intention figée avant exécution). Emplacement choisi et
justifié explicitement (pas un nouveau module séparé, contrairement à `validation_oos.py`, dont la
séparation se justifie par la connaissance simultanée d'`engine.py` ET de la persistance — cette
fonction ne connaît ni l'un ni l'autre). Suite complète verte (1383/1383). Review indépendante
réelle : 1 lot, 2 fichiers couverts, 1 finding non bloquant. Commit réel
`dd7136ce7f5d292306b3aee5bde15686c2ca18ca`, poussé sur `origin/autopilot/permanent` puis intégré
(fast-forward, régression complète 1383/1383 revérifiée) sur `origin/master`.

**Le moteur Walk-Forward (ADR 0021, les 15 Décisions) est désormais construit et testé de bout en
bout au niveau bibliothèque** : géométrie de folds (Slice 1), exécution TRAIN-only + Top-1 + TEST
par fold (Slice 2), orchestration multi-fold + agrégation OOS (Slice 3), persistance disque
écriture seule (Slice 4), reprise SKIP/REPLAY_TEST/REDO (Slice 5), `WalkForwardEvidence` + verdict
structurellement `INCONCLUSIVE` sans politique (Slice 6), `DatasetSplitPlan` réel avec `VALIDATION`
peuplée selon la décision explicite de l'utilisateur (Slice 7), assemblage `ValidationRun` complet
(Slice 8). Aucune fonction n'a encore été appelée pour de vrai sur les données réelles
(`nasdaq_3m.csv`) avec Perfect Revolution — tout ce travail reste au niveau bibliothèque/tests.

**Pause volontaire de l'enchaînement automatique ici — nouvelle vérification avant d'inventer une
neuvième tranche.** `GATE V` (voir `docs/roadmap/MASTER_ROADMAP.md` §4, table des gates) exige que
`OOS`+`WalkForward`+`MonteCarlo`+`ParameterStability` produisent **chacun** une `ValidationEvidence`
réelle sur `CURRENT REFERENCE ENGINE` + Perfect Revolution. Trois constats distincts, aucun
« clairement cadré par les documents du projet » au sens où les Slices 1 à 8 l'étaient :
1. **Exécuter réellement** le Walk-Forward construit (lancer un vrai run multi-fold — recherche
   TRAIN réelle par fold, backtests TEST réels, sur les données réelles) est qualitativement
   différent des huit tranches précédentes : une action scientifique réelle, coûteuse en temps de
   calcul et en appels Claude/outils, produisant un artefact qui entre dans l'historique
   scientifique du dépôt — jamais quelque chose à déclencher silencieusement sans que l'utilisateur
   en soit conscient, par analogie directe avec la prudence déjà exercée pour `FINAL_HOLDOUT`
   (accès explicite et délibéré, jamais automatique). Aucun `research_run_id`/`base_params`/budget
   de calcul concret n'a été fourni pour un tel run.
2. **Monte-Carlo et Parameter Stability restent à 0 % d'implémentation**, sans le moindre ADR ni
   ticket de conception équivalent à `docs/adr/0021-*.md` pour Walk-Forward — les concevoir
   maintenant équivaudrait à inventer un protocole scientifique entier, jamais quelque chose à
   dériver silencieusement d'une liste « hors scope ».
3. **`AF-V-01` (OOS)** est déjà `DONE` mais `performance-inconclusive` (`n_trades=0`) — sa
   contribution réelle à `GATE V` reste donc elle-même incomplète, indépendamment de tout travail
   Walk-Forward.

Mise en file d'une neuvième tranche volontairement SUSPENDUE — conformément à l'instruction
explicite de l'utilisateur réservant l'arrêt aux décisions scientifiques/produit réellement
absentes des sources, jamais à une invention silencieuse, et par analogie avec la prudence
existante autour de toute action scientifique réelle et coûteuse. L'Autopilot reste actif et
réactivable dès qu'une décision (lancer un run réel avec quels paramètres/budget, concevoir
Monte-Carlo/Parameter Stability, ou une autre priorité) est fournie par l'utilisateur.

## 33. AF-V-03 (Monte-Carlo) — ADR 0022 rédigée, revue deux fois, corrigée, implémentée en 2 tranches (2026-09-21/22)

**Décision explicite de l'utilisateur** : reprendre `GATE V` par `AF-V-03` (Monte-Carlo) puis
`AF-V-04` (Parameter Stability), chacune précédée d'une ADR scientifique complète, revue par deux
lectures indépendantes, avant toute implémentation ; enchaînement automatique réautorisé sans
reconfirmation entre étapes ; aucune campagne scientifique réelle coûteuse avant que Walk-Forward/
Monte-Carlo/Parameter Stability soient tous prêts et qu'un plan de budget/preuves comparables
existe. Voir aussi la note GATE V ajoutée à `docs/roadmap/MASTER_ROADMAP.md` (§4) : une preuve OOS
externe fraîche reste une action séparée, non déclenchée par cette mission.

**ADR 0022 (`docs/adr/0022-monte-carlo-trade-resampling-v1.md`, `bfbc671`)** : remplace l'ancienne
esquisse non contraignante (perturbations d'exécution — spread/slippage/ordre, jamais implémentable
avec un moteur d'exécution déterministe) par un protocole de rééchantillonnage de trades :
permutation (`sequence_risk`) et bootstrap avec remise (`sampling_uncertainty`), gardés séparés.
**Deux revues indépendantes réelles** (validité scientifique/overfitting ; architecture/
reproductibilité/intégration) ont trouvé 2 BLOCKER + 6 MAJOR réels avant toute implémentation :
- `probability_of_ruin` mathématiquement dégénérée sous chaînage multiplicatif (déjà la seule
  convention retenue par ce dépôt, ADR 0021 Décision 15) — `{0,1}` exact sous permutation, fonction
  triviale de comptage sous bootstrap, lisible à tort comme "risque de ruine nul" en pratique —
  **supprimée** de l'ADR, jamais réintroduite.
- Le drawdown reconstruit depuis les seuls PnL de clôture de trade n'est PAS le `max_dd_pct` réel
  du moteur (barre par barre, capture l'excursion intra-trade) — champs renommés explicitement
  `*_trade_close_basis_pct`, jamais confondus.
- Biais de sélection (trades issus de paramètres optimisés), absence de cadre de test d'hypothèse/
  risque de comparaisons multiples, sens du biais i.i.d. non énoncé, canal de "seed shopping"
  (`master_seed`/`n_simulations` librement choisis), discipline de pré-enregistrement d'une future
  politique de verdict, justification statistique imprécise (`1/sqrt(n)` d'une proportion, pas
  d'un quantile ; `n_trades`, pas `n_simulations`, est la vraie contrainte liante) — tous corrigés,
  reconfirmés propres par une seconde lecture des deux mêmes revues.
- **Aucun `HUMAN_GATE_REQUIRED` consolidé n'a été nécessaire** : chaque choix restait dérivable des
  conventions/contraintes déjà réelles de ce dépôt, jamais un choix scientifique matériellement
  ambigu entre plusieurs protocoles également valides.

**AF-V-03 Slice 1** (`.autopilot/prompts/af-v03-slice-1.md`) : `MonteCarloSpecification`/
`MonteCarloEvidence`/`MonteCarloDistributionSummary`/`MonteCarloSemanticsMismatch` dans
`validation_run.py` (mirroring exact de `WalkForwardSpecification`/`WalkForwardEvidence`),
`build_monte_carlo_specification()` (dérive `master_seed` par SHA-256 depuis
`source_validation_run_id`, jamais un entier libre — ferme le canal "seed shopping"),
`UnknownVerdictPolicy` réutilisée telle quelle (jamais dupliquée), `_VALIDATION_TYPES` étendu par
une troisième entrée littérale. Suite complète verte (1402/1402). Commit réel
`7e673866b8a3cf84b4083f0c75e1883fad9609b4`, intégré (fast-forward, régression complète revérifiée)
sur `origin/master`.

**AF-V-03 Slice 2** (`.autopilot/prompts/af-v03-slice-2.md`) : nouveau module leaf `monte_carlo.py`
— `run_monte_carlo_simulation()`, UN seul `numpy.random.default_rng()` par méthode (jamais un par
simulation, tirage vectorisé — vérifié : exactement 2 appels dans le code réel), énumération
exhaustive des permutations si `n_trades! < n_simulations`, percentiles de la plus longue série de
pertes en valeurs entières réellement observées (interpolation `"lower"`, jamais `"linear"`), test
de cohérence stricte `observed_net_ret_pct` vs `AggregateResult.oos_net_return_pct` sur un run
Walk-Forward réel. Aucun import `engine`/`optimizer`/`dataset_split`/`walk_forward` (vérifié dans
le code réel poussé). Deux pauses réelles sur limite d'usage Claude pendant cette tranche
(correctement `WAITING_FOR_CLAUDE`, jamais un Human Gate), plus une collision de verrou avec le
déclenchement périodique de la tâche Windows (`AlphaForgeAutopilot`, single-instance déjà vérifié
fonctionnel — la reprise manuelle a correctement refusé de démarrer une deuxième instance ;
attendu la fin de l'instance déjà active plutôt que de forcer). Suite complète verte (1444/1444).
Review indépendante réelle : 2 lots, 2 fichiers couverts, 2 findings bloquants réellement corrigés
avant clôture. Commit réel `0758cc52d33bde1387ca6ff431b12d0511b9a1da`, intégré (fast-forward,
régression complète 1444/1444 revérifiée) sur `origin/master`.

**Prochaine tranche** : `AF-V-04` (Parameter Stability) — même discipline (ADR scientifique d'abord,
deux revues indépendantes, correction des BLOCKER/MAJEUR, implémentation TDD ensuite), à préparer
sans redemander d'autorisation.

## 34. AF-V-04 (Parameter Stability) — ADR 0023 rédigée, revue sur TROIS passes, corrigée ; correctifs cross-ADR appliqués au code déjà mergé ; Slices 1/2 mises en file (2026-09-22)

**ADR 0023** (`docs/adr/0023-parameter-stability-plateau-v1.md`, `ca321f1`) : contrairement à
Monte-Carlo, ce protocole **réutilise un mécanisme déjà réellement implémenté** dans ce dépôt —
`scoring.py::compute_sensitivity_filtered()`/`compute_sensitivity_correlation()`, déjà câblées dans
`Optimizer.run()` — plutôt que d'en inventer un nouveau. Conçu comme une ré-analyse purement
déterministe (aucune graine, aucun tirage aléatoire) d'un pool de candidats DÉJÀ évalués par une
recherche `Optimizer` terminée — jamais un nouveau backtest.

**Revue en TROIS passes, chaque nouvelle correction re-vérifiée par les deux mêmes revues** :
1. Première passe : 2 BLOCKER + 6 MAJEUR réels — le filtre réutilisé de `compute_sensitivity_filtered()`
   exclut silencieusement les candidats rejetés (`score <= 0`), or ce sont précisément ceux qui
   démontreraient le plus fortement un pic isolé ; le sentinel `0.0` de `sensitivity` est
   indiscernable d'une vraie valeur nulle sans connaître la taille d'échantillon sous-jacente ;
   absence d'avertissement de circularité (le vainqueur EST l'argmax in-sample sur ce même pool,
   plus circulaire qu'en Monte-Carlo) ; la méthode "un paramètre à la fois" ne peut jamais confirmer
   une robustesse jointe, seulement l'infirmer ; le mode `"general"` produisait des champs vides
   silencieusement confondables avec "analysé et stable" ; `best_params` s'incluait lui-même dans
   son propre voisinage, injectant un point de dégradation `0` garanti ; aucun avertissement de
   comparaisons multiples.
2. Deuxième passe (après corrections) : 2 NOUVEAUX MAJEUR introduits PAR les corrections elles-mêmes
   — la statistique jointe `degradation_hamming_le_2` réincluait la distance `0` (c'est-à-dire
   `best_params` lui-même) et manquait ses compteurs compagnons ; `neighborhood_applicability`
   dérivait uniquement de `search_mode`, jamais du voisinage RÉELLEMENT mesuré (une grille
   clairsemée avec zéro voisin réel se lisait quand même "disponible localement") — corrigées,
   reconfirmées propres.
3. Troisième passe : 3 findings mineurs (troisième sentinel non désambiguïsé pour la corrélation de
   Spearman, incohérence de nommage de champ, impact cross-ADR non documenté) — corrigés.

**Correctifs cross-ADR appliqués au code déjà mergé (AF-V-03), trouvés par la revue architecture
d'ADR 0023 avant même le début de l'implémentation d'AF-V-04** (commit `85dbba0`) :
- `MonteCarloDistributionSummary` renommée `PercentileDistributionSummary` — ce nom suggérait à
  tort une origine unique alors qu'ADR 0023 en devient un second consommateur non lié ; ce dépôt
  applique déjà cette discipline ailleurs (`*_trade_close_basis_pct`, ADR 0022 Décision 6).
  Renommage mécanique (forme/champs inchangés) dans `validation_run.py`/`monte_carlo.py`/leurs
  tests, amendement post-merge documenté dans les Conséquences d'ADR 0022.
- `ValidationSpecification`/`ValidationEvidence` (alias `Union` typés) n'avaient jamais été étendus
  pour inclure `MonteCarloSpecification`/`MonteCarloEvidence` depuis leur ajout (Slice 1 AF-V-03) —
  lacune réelle (leur propre docstring dit pourtant « étendre en ajoutant un membre par futur
  `validation_type` ») — corrigée dans le même commit. Suite complète verte (1444/1444) avant et
  après, intégré sur `origin/master`.

**AF-V-04 Slice 1/Slice 2** (`.autopilot/prompts/af-v04-slice-1.md`/`af-v04-slice-2.md`) mises en
file (`08d3bf9`) — mirroring exact du découpage AF-V-03 (typé d'abord, algorithme ensuite), avec un
rappel explicite dans les deux prompts que `validation_run.py`/`parameter_stability.py` ne doivent
JAMAIS importer `optimizer.py` (pas même pour une constante) — les valeurs de `search_mode` sont
dupliquées littéralement plutôt qu'importées, invariant "leaf" déjà vérifié deux fois par les
revues indépendantes, jamais à régresser.

**AF-V-04 Slice 1/2 — réellement achevées (2026-09-22)** : les deux tranches ont complété dans le
même run Autopilot (plusieurs pauses réelles sur limite d'usage Claude entre les deux, correctement
`WAITING_FOR_CLAUDE`, jamais un Human Gate). Vérifié dans le code réel avant intégration :
`validation_run.py` n'importe toujours ni `optimizer.py` ni `engine.py` ; `parameter_stability.py`
n'importe que `scoring`/`validation_run`/`numpy`/stdlib (jamais `optimizer`/`engine`/
`dataset_split`/`walk_forward`) ; `_is_structural_neighbor()` implémente EXACTEMENT la Décision 2
corrigée (clés exactes, exclusion de `best_params` lui-même, AUCUNE exclusion sur le score) ;
la statistique jointe utilise bien `1 <= distance de Hamming <= 2` (jamais `0`). Suite complète
verte (1509/1509). Commits réels `e2333c11eda1de7e9ec6bf16ded58a523c9c015f` (Slice 1) et
`d8ab4eaa3626ec23b61e242f74b894d83fc5328d` (Slice 2), intégrés (fast-forward, régression complète
1509/1509 revérifiée) sur `origin/master`.

**AF-V-02/AF-V-03/AF-V-04 sont désormais TOUS construits et testés au niveau bibliothèque** —
Walk-Forward, Monte-Carlo, Parameter Stability. Aucun des trois n'a encore été exécuté pour de vrai
sur `nasdaq_3m.csv`/Perfect Revolution. Voir §35 pour la préparation (jamais l'exécution) d'une
campagne `GATE V` intégrée.

## 35. Préparation d'une campagne `GATE V` intégrée (jamais son exécution) — état réel, écart d'orchestration identifié, budget estimé (2026-09-22)

**Décision explicite de l'utilisateur** : préparer une campagne réelle intégrée `GATE V` — définir
ses paramètres/budget/preuves attendues — **sans la lancer** tant que ces trois conditions ne sont
pas explicitement réunies. Ce paragraphe est cette préparation, pas un déclenchement.

### État réel vérifié (jamais supposé) des quatre preuves exigées par `GATE V`

`docs/roadmap/MASTER_ROADMAP.md` §4 : « `OOS`/`WalkForward`/`MonteCarlo`/`ParameterStability`
produisent tous une `ValidationEvidence` réelle sur `CURRENT REFERENCE ENGINE` + Perfect Revolution ».

| Preuve | Mécanisme construit | Exécuté pour de vrai ? |
|---|---|---|
| `OOS` (`AF-V-01`) | `validation_oos.py::run_oos_validation()` | **Oui**, mais `performance-inconclusive` (`n_trades=0`) — évidence conservée telle quelle, jamais relancée sur le même holdout (§29/32). Une preuve fraîche exige un NOUVEAU `DatasetSnapshot` + accès `FINAL_HOLDOUT` explicitement autorisé (note `GATE V` séparée, `MASTER_ROADMAP.md` §4) — action distincte, non déclenchée ici. |
| `WalkForward` (`AF-V-02`) | `walk_forward.py` (Slices 1-8), `build_walk_forward_validation_run()` | **Non** — jamais appelé sur les données réelles, seulement testé avec des fixtures synthétiques/le vrai moteur en isolation (ex. tests de cohérence `AggregateResult`). |
| `MonteCarlo` (`AF-V-03`) | `monte_carlo.py::run_monte_carlo_simulation()` | **Non** — consomme une séquence de trades déjà observés (ADR 0022 Décision 1), jamais encore fournie par un run réel. |
| `ParameterStability` (`AF-V-04`) | `parameter_stability.py::analyze_parameter_stability()` | **Non** — consomme un pool de candidats déjà évalués (ADR 0023 Décision 1), jamais encore fourni par un run réel. |

### Écart d'orchestration réel identifié (jamais construit à ce jour, dans aucune des slices précédentes)

Chaque module (Slice 8 d'AF-V-02, Slices d'AF-V-03/AF-V-04) a été délibérément conçu pour consommer
des FAITS déjà calculés par un appelant — **aucun code existant ne relie aujourd'hui un run
Walk-Forward réel à Monte-Carlo/Parameter Stability**. Concrètement, il manque une fonction (ou un
script, mirroring `scripts/create_walk_forward_validation_split_plan_v2.py`) qui :
1. Charge le `DatasetSplitPlan` réel déjà construit (`split_perfect_revolution_v1_walk_forward_v2`,
   Slice 7 AF-V-02, `VALIDATION` = 54 mois / 5 folds, décision utilisateur du 2026-09-21).
2. Appelle `walk_forward.run_walk_forward()` (ou `resume_walk_forward_run()`) pour de vrai —
   **c'est ICI, et seulement ici, que la campagne devient réellement coûteuse** (recherche
   `Optimizer.run()` réelle par fold, 5 folds, chacun une vraie recherche TRAIN + un vrai backtest
   TEST).
3. Extrait, du `WalkForwardRunOutcome` obtenu, la séquence de trades par fold (déjà persistée en
   CSV, `oos_trades.csv`, Slice 4) pour alimenter `monte_carlo.py`, et le pool de candidats TRAIN
   par fold (`train_candidates.csv`, même Slice) pour alimenter `parameter_stability.py`.
4. Assemble les quatre `ValidationRun` (`OOS` déjà existante, `WalkForward` via
   `build_walk_forward_validation_run()`, `MonteCarlo`/`ParameterStability` via leurs builders
   respectifs) sous un `research_run_id` commun.

**Cette fonction d'orchestration n'existe pas encore** — construire ce CODE (jamais l'exécuter sur
les données réelles) resterait une "préparation" légitime, à coût nul (aucun backtest réel), si une
future tranche est autorisée pour cela. Ce paragraphe se limite à documenter l'écart, ne le comble
pas.

### Identifiants déjà conventionnés dans ce dépôt, à réutiliser pour toute future campagne réelle

- `research_run_id`/`experiment_id` : `research_run.py::build_research_run()`, déjà exige
  `dataset_snapshot_id` réel, capture `git_sha`/`engine_version`/`seed` automatiquement.
- `validation_run_id` (un par preuve — OOS/WalkForward/MonteCarlo/ParameterStability) :
  `validate_portable_identifier()`, même convention que partout ailleurs dans ce dépôt.
- `split_plan_id` : `split_perfect_revolution_v1_walk_forward_v2` (Slice 7 AF-V-02, réel, déjà sur
  disque dans le checkout principal).
- `source_validation_run_id` (Monte-Carlo/Parameter Stability) : le `validation_run_id` du run
  `WalkForward` dont les trades/candidats sont réutilisés — jamais un identifiant inventé
  séparément.

### Budget estimé pour une exécution réelle complète (jamais engagé par cette préparation)

- **`WalkForward`** : SEUL poste réellement coûteux — 5 folds, chacun une vraie recherche
  `Optimizer.run()` (ordre de grandeur dépendant du `search_space`/mode réellement choisi, non
  encore fixé) + un vrai backtest TEST par fold. Aucun budget Claude/API consommé (calcul local pur
  côté moteur) — coût en TEMPS DE CALCUL local, pas en crédits.
  `AF-V-02 Slice 8`'s propre disqualification de l'exécution réelle (§32) reste valable : paramètres
  réels (`base_params`, budget de recherche par fold) non encore fixés, jamais inventés ici.
- **`MonteCarlo`/`ParameterStability`** : négligeables (ADR 0022/0023 Décision 14 — millisecondes à
  secondes, purement locaux, une fois les trades/candidats réels du `WalkForward` disponibles).
- **`OOS` fraîche** : hors scope de cette préparation (action séparée déjà actée, `MASTER_ROADMAP.md`
  §4) — nécessiterait un nouveau `DatasetSnapshot`/accès holdout explicitement autorisés, jamais
  engagés ici.

### Conditions explicites avant toute exécution réelle (rappel, rien de déclenché ici)

Les trois conditions posées par l'utilisateur restent NON réunies à ce stade : (1) Walk-Forward/
Monte-Carlo/Parameter Stability sont prêts (VRAI, ce paragraphe le confirme) ; (2) le plan OOS n'est
PAS encore clarifié au-delà de la note `GATE V` déjà actée (FAUX — reste à préciser : quand, quel
`DatasetSnapshot`) ; (3) aucun identifiant/paramètre/budget réel n'est encore ENREGISTRÉ pour un
run `WalkForward` réel (FAUX — `base_params`/recherche/budget de calcul restent à fixer
explicitement). **Aucune campagne réelle n'est donc lancée par cette section — préparation
documentaire uniquement, conformément à l'instruction explicite de l'utilisateur.**

## 36. `AF-V-08` — ADR 0024 (câblage d'orchestration `GATE V`) rédigée, revue sur DEUX passes, corrigée, intégrée ; implémentation TDD mise en file (2026-09-22)

**Décision explicite de l'utilisateur** : combler l'écart d'orchestration documenté au §35 — un
câblage APPELABLE ET TESTÉ reliant Walk-Forward/Monte-Carlo/Parameter Stability, avec les mêmes
garde-fous scientifiques (mapping TEST-only, exhaustivité par fold, jamais de fusion en score
unique) et une conception/revue rigoureuse AVANT toute implémentation. Ticket `AF-V-08`, ADR `0024`
— identifiants vérifiés disponibles (`grep -rn "AF-V-08" docs/` : aucune occurrence avant l'ADR),
`AF-V-05` (Stress/Noise) explicitement préservé, jamais réutilisé.

### ADR 0024 — conception et double revue indépendante

`docs/adr/0024-gate-v-campaign-orchestration-v1.md` (commit `cc00f65`) définit : le modèle de
campagne (Walk-Forward + Monte-Carlo dérivé + N Parameter Stability par fold, jamais fusionnés),
les identifiants/filiation `ResearchRun`/`ValidationRun`, les entrées obligatoires fail-closed, les
artefacts produits, la séparation stricte Niveau A (préparation déterministe,
`build_gate_v_campaign_plan()`) / Niveau B (exécution explicite future,
`execute_gate_v_campaign()`), le mapping scientifique précis WF→MC/PS, les 6 états factuels
(`NOT_READY`/`READY_FOR_EXECUTION`/`RUNNING`/`EVIDENCE_INCOMPLETE`/
`EVIDENCE_COMPLETE_AWAITING_POLICY`/`TECHNICAL_FAILURE` — **jamais `GATE V PASS`**), la reprise sans
doublon, et la différence entre techniquement prête / exécutée / `GATE V` réellement passée.

**Deux revues indépendantes** ont tourné en parallèle sur l'ADR (axe architecture/reproductibilité,
axe validité scientifique) — 2 BLOCKER + 3 MAJEUR + 3 MINEUR au total, tous corrigés puis
reconfirmés propres par une DEUXIÈME passe de revue (les deux agents originaux n'étant plus
joignables après une compaction de contexte, la confirmation a été refaite via deux nouveaux agents
indépendants relisant l'ADR corrigé dans son intégralité) :

| # | Sévérité | Axe | Résumé |
|---|---|---|---|
| 1 | BLOCKER | Architecture | `persist_walk_forward_run()` (Slice 4 AF-V-02, gelée, `save_atomic()` refuse tout écrasement) aurait été rappelée sans condition après une reprise déjà persistée -> `FileExistsError` dès sa toute première écriture. **Corrigé** : appelée AU PLUS UNE FOIS par campagne, gardée par l'existence de `.../walk_forward/aggregate.json` (dernier fichier écrit, marqueur de complétion fiable). Limite résiduelle honnêtement documentée (crash PENDANT cet appel unique = résolution manuelle, hors scope de modifier Slice 4). |
| 2 | BLOCKER | Scientifique | `source_trades_from_optimized_params`/`source_candidates_from_optimized_search` (drapeaux de circularité obligatoires sur `MonteCarloSpecification`/`ParameterStabilitySpecification`, ADR 0022/0023) n'étaient JAMAIS mentionnés. **Corrigé** : les deux hardcodés `True`, justifié (Walk-Forward TEST/TRAIN sont structurellement toujours issus d'une recherche optimisée dans ce câblage). |
| 3 | MAJEUR | Architecture | Fausse affirmation "signature identique" entre `run_walk_forward()`/`resume_walk_forward_run()` (signatures et types de retour RÉELLEMENT différents). **Corrigé** : deux collaborateurs injectés séparés. |
| 4 | MAJEUR | Architecture | Portée de la garantie FINAL_HOLDOUT (imports propres du module) jamais distinguée de la frontière de confiance d'un futur collaborateur injecté réel. **Corrigé** : précisée explicitement (Décision 10). |
| 5 | MAJEUR | Scientifique | `EVIDENCE_COMPLETE_AWAITING_POLICY`/contribution Parameter Stability "prête" reposaient sur un simple décompte de fichiers, ignorant la condition de qualité qu'ADR 0023 Décision 3 exige déjà d'un futur agrégateur `GATE V` (`neighborhood_applicability`/voisins non rejetés). **Corrigé** : les deux conditions désormais cumulatives. |
| 6-8 | MINEUR ×3 | Les deux | Surface d'injection MC/PS mal cadrée ; branche run frais omettant `build_aggregate_result()` (romprait silencieusement le marqueur de complétion) ; risque de cherry-picking ENTRE campagnes jamais restaté. Les trois corrigés. |

### Intégration

`cc00f65` (ADR 0024 + ticket `AF-V-08`) et `d944c4e` (mission queue) intégrés à `origin/master` via
le worktree d'intégration dédié (fast-forward only, 1517 tests verts avant/après chaque push).
`AF-V-08` : `Status: READY` -> conception achevée, `implementation: NOT STARTED`.

### Implémentation mise en file (jamais lancée par cette mission)

Six tranches TDD séquentielles, `nouveau module gate_v_campaign.py`, mises en file dans
`.autopilot/missions.json` (`AF-V-08-SLICE-1` à `6`, `status: READY`, chaînées par `depends_on`) :

1. Contrats `GateVCampaignPlan` + Niveau A (`build_gate_v_campaign_plan()`).
2. Contrat `GateVCampaignManifest` + calcul PUR du statut à 6 états (dont le correctif MAJEUR #5).
3. Niveau B squelette — phase Walk-Forward, double injection, garde persist-once (correctif BLOCKER #1).
4. Phase Monte-Carlo (mapping TEST-only, drapeau de circularité, correctif BLOCKER #2).
5. Phase Parameter Stability (exhaustive par fold, statut final).
6. Intégration bout-en-bout, garde-fous anti-déclenchement, clôture de la matrice TDD Décision 13.

Chaque `forbidden_paths` protège l'intégralité des modules déjà revus/gelés (`engine.py`,
`optimizer.py`, `walk_forward.py`, `monte_carlo.py`, `parameter_stability.py`, `validation_run.py`,
`validation_oos.py`, `scripts/autopilot/`, `docs/adr/`) — seuls `gate_v_campaign.py`/
`tests/test_gate_v_campaign.py` sont modifiables (`docs/roadmap/EPICS_AND_TICKETS.md` en plus pour
la Slice 6, clôture du ticket).

### Ce qui N'A PAS été fait dans cette mission (conforme à l'instruction explicite)

Aucun backtest réel, aucune recherche `Optimizer`, aucun téléchargement, aucun accès `FINAL_HOLDOUT`.
`base_params`/`search_mode`/`search_space`/`budget_per_fold` réels restent des entrées à fournir —
voir §37 pour la proposition consolidée soumise à décision.

## 37. `AF-V-08` — Slices 1-6 + correctif `TECHNICAL_FAILURE` : IMPLEMENTED + TESTED sur `codex/af-v-08`, prêt pour intégration finale (2026-09-28)

**Branche** : `codex/af-v-08`, worktree isolé `D:\alphaforge-af-v-08-codex` (jamais le checkout
principal). 8 commits devant `origin/master` (`c8cb6a9`), 0 derrière.

**Commits de la branche, dans l'ordre chronologique réel** :
1. `ee3f7b8` — Slice 1 (`build_gate_v_campaign_plan()`, Niveau A).
2. `6d8cd29` — Slice 2 (`GateVCampaignManifest`/`derive_gate_v_campaign_status()`).
3. `7958e29` — API additive Walk-Forward captured artifacts V1
   (`run_walk_forward_with_artifacts_v1()`/`resume_walk_forward_with_artifacts_v1()`, amendement
   ADR 0021) — entre Slice 2 et Slice 3, requise par Slice 3 pour câbler une campagne fraîche sans
   seconde recherche TRAIN/TEST.
4. `a5f16d5` — Slice 3 (phase Walk-Forward de `execute_gate_v_campaign()`).
5. `8fda211` — Slice 4 (phase Monte-Carlo — convention `trade_return_pct` par trajectoire de
   capital, ADR 0022 amendement).
6. `ed21298` — Slice 5 (phase Parameter Stability + relecture publique read-only
   `load_walk_forward_captured_run_v1()`).
7. `3b6c63a` — correctif de stabilisation `TECHNICAL_FAILURE` (le marqueur n'était jamais
   persisté sur exception technique, contredisant ADR 0024 Décision 7 ; corrigé par un helper
   commun aux trois phases, rechargeant toujours le manifeste le plus récent depuis le disque).
8. `6ba966f` — Slice 6 (intégration bout-en-bout SYNTHÉTIQUE, test-only).

**Slices 1-6, toutes IMPLEMENTED + TESTED + PUSHED** :
1. `build_gate_v_campaign_plan()` — préparation déterministe, aucune donnée marché.
2. `GateVCampaignManifest` + `derive_gate_v_campaign_status()` — calcul pur de statut à 6 états.
3. `execute_gate_v_campaign()` phase Walk-Forward — double injection (frais/reprise), garde
   persist-once.
4. Phase Monte-Carlo — mapping TEST-only exact, drapeau de circularité en dur.
5. Phase Parameter Stability — un pool par fold jamais fusionné, relecture read-only de la
   capture V1 (jamais `train_candidates.csv`), crash-reconciliation par fold.
6. Fermeture de l'intégration bout-en-bout SYNTHÉTIQUE (cette mission) : un test d'intégration
   principal construit une campagne complète depuis zéro sur fixtures synthétiques cohérentes —
   plan → Walk-Forward (vraie orchestration `run_walk_forward_with_artifacts_v1()`, seul le
   calcul bas-niveau d'un fold est remplacé par un résultat synthétique cohérent) → Monte-Carlo
   (fonction réelle `run_monte_carlo_simulation()`) → Parameter Stability (fonction réelle
   `analyze_parameter_stability()`, un voisin utilisable réel par fold) → statut
   `EVIDENCE_COMPLETE_AWAITING_POLICY`, dérivé UNIQUEMENT par `derive_gate_v_campaign_status()`
   (jamais forcé manuellement, prouvé par recalcul direct depuis les preuves persistées). Une
   `ValidationRun` OOS SYNTHÉTIQUE déjà `completed` est construite et persistée AVANT le plan
   (jamais via `validation_oos.run_oos_validation()`, jamais importé dans `gate_v_campaign.py`).
   Relecture disque complète (plan/manifeste/OOS/WF/MC/PS/capture V1, tous rechargés
   indépendamment puis restatut recalculé) et idempotence d'un second appel (zéro recalcul,
   horodatages de fichiers inchangés) sont prouvées séparément. IDs déterministes vérifiés
   (aucun `uuid`/`random`/horodatage courant dans `gate_v_validation_run_id()`). Production
   `gate_v_campaign.py` inchangée par cette tranche — fermeture au niveau test uniquement, aucun
   nouveau contrat scientifique nécessaire.

**Tests** : suite complète (`--ignore=tests/test_engine.py`) verte, 1652 passed + 2 skipped après
cette mission (baseline avant Slice 6 : 1647 passed + 2 skipped, +5 tests neufs de Slice 6, aucune
régression). `tests/test_gate_v_campaign.py` seul : 170 passed.

**Architecture** : deux niveaux stricts (A préparation déterministe / B exécution explicite),
jamais de déclenchement automatique — `gate_v_campaign.py` n'a aucun `if __name__ == "__main__"`,
n'est référencé ni par `app.py`, ni `optimizer_process.py`, ni `scripts/autopilot/` (vérifié). Les
trois phases (Walk-Forward/Monte-Carlo/Parameter Stability) partagent désormais un helper commun
de marquage `TECHNICAL_FAILURE` (jamais trois mécanismes séparés). Aucune deuxième source de
vérité pour le statut de campagne : toujours `derive_gate_v_campaign_status()`.

**Limitations connues, non corrigées par cette mission (dettes documentées, pas des bugs
cachés)** : (1) un crash PENDANT l'appel unique `persist_walk_forward_run()` lui-même reste une
limite résiduelle acceptée, résolution manuelle depuis les checkpoints V1 (ADR 0024 Décision 8) ;
(2) aucune sérialisation inter-processus si deux exécuteurs tournent en concurrence sur la même
campagne ; (3) l'échec d'encodage Windows console de
`tests/test_autopilot_hooks.py::test_hook_blocks_a_force_push` est externe à AF-V-08 (prouvé
différentiellement identique sur le parent Slice 4 `8fda211` et sur `ed21298` via un worktree
détaché temporaire ; déterministiquement vert sous `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`) —
Autopilot n'a jamais été modifié pour le contourner.

**Aucune campagne scientifique réelle exécutée. Aucun accès `FINAL_HOLDOUT` réel. Aucun `AF-V-07`
implémenté. `GATE V` reste NON PASSÉE, aucun `PASS`/Champion produit ou possible sur cette
branche (Décision 15, ADR 0024).**

**Prochaine action unique** : revue finale + intégration fast-forward vers `master`, uniquement
après validation explicite de l'utilisateur. Aucun merge n'a été effectué par cette mission ni
par aucune des missions précédentes de cette branche.

## 38. `AF-V-08` intégré dans `master` — ticket DONE, `GATE V` toujours NON PASSÉE (2026-09-28)

**Décision explicite de l'utilisateur** : autorisation donnée pour exécuter le fast-forward
préparé au §37, depuis le worktree d'intégration dédié
(`C:\Users\Mira Alexandre\Desktop\backtest-nasdaq-revolution-master-integration`, branche locale
`integration/master` suivant `origin/master`).

**Intégration** : `origin/master` = `daefc891f853bb0f3d06650b28033aa4218c52eb`. Fast-forward
strict depuis `c8cb6a93c1e475ac07076fcdede99b95c7fde577` (`git merge --ff-only
origin/codex/af-v-08`, message `Fast-forward`) — **aucun commit de merge**. Les 9 commits listés
au §37 sont désormais présents tels quels dans `master` : `ee3f7b8`, `6d8cd29`, `7958e29`,
`a5f16d5`, `8fda211`, `ed21298`, `3b6c63a`, `6ba966f`, `daefc89`.

**Tests** :
- Pré-intégration (worktree `D:\alphaforge-af-v-08-codex`, HEAD `daefc891...`, environnement
  `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`) : **1652 passed, 2 skipped, 0 failed**.
- Post-fast-forward local (worktree d'intégration, même environnement) : **1654 passed, 0
  skipped, 0 failed**. Écart expliqué : les 2 tests auparavant skippés
  (`tests/test_engine_load_data_from_source.py`, `tests/test_market_data_resample.py`, tous deux
  conditionnés à la présence de `nasdaq_3m.csv`) passent réellement dans ce worktree
  d'intégration UNIQUEMENT parce qu'il contient localement ce fichier volumineux non versionné —
  un état préexistant de ce worktree, sans rapport avec le diff AF-V-08 (aucun des deux fichiers
  de test concernés n'apparaît dans `git diff origin/master..origin/codex/af-v-08`). Même total
  de tests (1654) des deux côtés, zéro échec des deux côtés — écart purement environnemental,
  jamais une régression du code intégré.

**Ticket `AF-V-08`** : **DONE**. `ADR 0024` : **Accepté** (implémentation intégrée dans `master`,
statut inchangé — voir mise à jour ADR 0024 du même jour). `MASTER_ROADMAP.md` Track V mis à jour
en conséquence (orchestration `IMPLEMENTED + TESTED + INTEGRATED IN MASTER`, mécanismes
bibliothèque restant séparément `IMPLEMENTED + TESTED`).

**Dettes connues, conservées telles quelles (non traitées par cette clôture)** :
1. Un crash PENDANT l'appel unique `persist_walk_forward_run()` lui-même reste une limite
   résiduelle acceptée — résolution manuelle depuis les checkpoints V1 (ADR 0024 Décision 8).
2. Aucune sérialisation inter-processus si deux exécuteurs tournent en concurrence sur la même
   campagne.
3. L'échec d'encodage Windows console de
   `tests/test_autopilot_hooks.py::test_hook_blocks_a_force_push` reste externe à AF-V-08
   (prouvé différentiellement identique sur le parent et sur la branche ; Autopilot n'a jamais
   été modifié pour le contourner).

**Aucune campagne scientifique réelle exécutée. Aucun accès `FINAL_HOLDOUT` réel. Aucun `AF-V-07`
implémenté. Aucun `PASS`. Aucun Champion. `GATE V` reste NON PASSÉE** — l'intégration dans
`master` porte sur l'orchestration technique, jamais sur un verdict scientifique (Décision 15,
ADR 0024).

**Prochaine étape** : décision utilisateur sur la suite du Track V. Aucun lancement de campagne
réelle, aucun `AF-V-07` et aucun accès `FINAL_HOLDOUT` sans nouvelle décision explicite.

## 39. `AF-V-07` — design `ValidationPolicyVersion` accepté (ADR 0025), READY FOR IMPLEMENTATION, aucun code écrit (2026-09-29)

**Décision explicite de l'utilisateur** : concevoir `AF-V-07` (`ValidationPolicyVersion`) —
DESIGN ONLY, aucun code — à travers sept itérations successives (V1-V7), chacune close par une
revue scientifique et architecture/reproductibilité adversariale avant la suivante, puis formaliser
le résultat accepté dans `docs/adr/0025-gate-v-validation-policy-v1.md`.

**Contenu accepté** (détail complet : ADR 0025) : six objets normatifs
(`GateVValidationPolicyVersion`, `GateVPreRegistration`, `GateVCampaignPlan` V2,
`FinalHoldoutAccessClaim`, `ValidationAssessment`, `GateVPolicyAssessment`) ; ordre scientifique
obligatoire V2 avec `FINAL_HOLDOUT` structurellement DERNIER (après Walk-Forward/Monte-Carlo/
Parameter Stability tous folds complets) ; `V1` historique jamais réécrite, `campaign_id` V1
bit-pour-bit inchangé ; empreinte de protocole complète (`campaign_protocol_fingerprint`, corrige
un oubli des champs dérivés de folds trouvé en V6) ; provenance Git de policy fermée à l'échec
(`policy_git_sha` non optionnel, octets committés vérifiés via `git show`, jamais l'arbre de
travail) ; primitif d'exclusivité un-coup `FinalHoldoutAccessClaim` (`os.O_CREAT|O_EXCL`, ferme un
BLOCKER de course entre processus trouvé en V7 — un simple booléen de manifeste ne pouvait pas
garantir l'exclusivité) ; matrice de crash conservatrice (toute incertitude sur la consommation du
holdout est traitée comme consommée, aucun retry automatique) ; `GateVPolicyAssessment.verdict ==
PASS` explicitement distinct de `GATE V = PASS`.

**Processus de revue** : chaque itération a rejoué un scénario adversarial complet (policy
choisie après observation de l'OOS, protocole modifié après coup, préenregistrements multiples
pour le même scope, crash à chaque étape possible, OOS forgée, provenance Git falsifiée, etc.) —
classé BLOCKER/MAJOR/MINEUR, tout BLOCKER/MAJOR corrigé avant la revue suivante. Aucun BLOCKER/
MAJOR ne subsiste dans la V7 finale.

**Design Pilot** : invoqué à chaque itération — a confirmé systématiquement l'absence de toute
surface UI/UX (aucun écran, aucun utilisateur final) ; n'a jamais décidé une règle scientifique.
**Figma MCP** : utilisé à chaque itération pour produire/mettre à jour un diagramme d'architecture
(FigJam/Mermaid) — dernier diagramme (V7, référence non normative) :
`https://www.figma.com/board/tbncsrWhuFng8HF0QDKKD1`. Un échec transitoire du classificateur
serveur Figma a affecté une itération (V4) — retenté avec succès, signalé honnêtement dans son
compte rendu plutôt que masqué. **Le texte de l'ADR 0025 reste seul normatif** en cas de
divergence avec un diagramme.

**ADR 0025 créée** : `docs/adr/0025-gate-v-validation-policy-v1.md`, Status `Accepté — design
validé, READY FOR IMPLEMENTATION`. **Amendements** : ADR 0021 Décision 13, ADR 0022 Décision 12,
ADR 0023 Décision 12 (supersession explicite, jamais une contradiction silencieuse — le
`scientific_verdict` embarqué reste `INCONCLUSIVE` en permanence, `ValidationAssessment` devient
le canal canonique) ; ADR 0024 (note d'amendement `AF-V-07`, V1 historique préservée, V2
référencée) ; `DOMAIN_MODEL.md` §13 (distinction `GateVValidationPolicyVersion` GATE V vs future
policy Champion, même primitif de versioning, jamais le même contrat sémantique) ;
`EPICS_AND_TICKETS.md`/`MASTER_ROADMAP.md` (statut `AF-V-07` : `DESIGN ACCEPTED / READY FOR
IMPLEMENTATION`, jamais `IMPLEMENTED`/`TESTED`/`DONE`).

**Aucun code Python, aucun test, aucune campagne réelle, aucun accès `FINAL_HOLDOUT` produit par ce
processus de conception. `AF-V-08` reste `DONE`, intégrée dans `master`, inchangée. `GATE V` reste
NON PASSÉE.**

**Prochaine étape** : découpage TDD (ADR 0025, slices A-I) après autorisation explicite de
l'utilisateur pour commencer l'implémentation — aucun code AF-V-07 n'a été écrit par cette mission
de conception.

## 40. `AF-V-07` — Slice A/B intégrées, Slice C (`GateVCampaignPlan V2`) spécifiée et verrouillée (2026-09-29)

Depuis §39 : **Slice A** (`GateVValidationPolicyVersion`, critères typés, hash canonique,
persistance immuable, `gate_v_validation_policy.py`) implémentée en TDD strict, revue
BLOCKER/MAJOR (champs top-level non validés au chargement — corrigé), commitée (`bcee84e`),
poussée sur `origin/master`. **Slice B** (`GateVPreRegistration`, `compute_scope_key()`,
`compute_campaign_protocol_fingerprint()`, `compute_preregistration_id()`/
`compute_preregistration_content_hash()`, `verify_policy_git_provenance()` fail-closed) implémentée
en TDD strict, deux findings adversariaux réels corrigés avant intégration : (1) BLOCKER — TOCTOU
sur l'unicité inter-processus du préenregistrement (`save_atomic()` insuffisant, documenté par sa
propre docstring) — corrigé par une nouvelle primitive additive `save_exclusive()`
(`os.O_CREAT|O_EXCL`, `atomic_json_store.py`), validée par un test à 2 processus réels avec
barrière de synchronisation (5/5 exécutions, exactement 1 gagnant) ; (2) MAJOR — `policy_git_sha`
n'était pas vérifié égal au `HEAD` courant (seulement que le blob existait à ce SHA) — corrigé par
comparaison canonique `git rev-parse HEAD^{commit}` vs `git rev-parse <sha>^{commit}`, testée
(ancien commit avec contenu identique → refusé ; SHA court résolu → accepté ; CWD externe/working
tree dirty → robuste). Commitée (`0f0df82`), corrections commitées (`3bf1872`), poussées sur
`origin/master`. Suite complète : 1789/1789 PASS avant push Slice B corrigée.

**Mission de verrouillage Slice C (2026-09-29, DESIGN ONLY, aucun code)** : ADR 0025 ne donnait pas
de formule explicite pour `campaign_id` V2 — ambiguïté fermée par la Décision 20 (nouvelle) :
formule exacte hash-de-hashes (`preregistration_id` + `campaign_protocol_fingerprint` +
`campaign_plan_semantics_version`, préfixe `"gate_v_v2_"` distinct de V1), réutilisation
obligatoire de `compute_campaign_protocol_fingerprint()` (jamais réimplémentée), dataclass
`GateVCampaignPlanV2` DISTINCTE de `GateVCampaignPlan` V1 (Option B, argumentée contre l'extension
du type existant — états illégaux représentables sinon), stratégie save/load fail-closed avec
revalidation en DEUX temps (protocol_fingerprint ET campaign_id, ce second temps fermant un gap
réel trouvé en revue architecture : une altération isolée de `preregistration_id` seul n'aurait
pas été détectée par la seule revalidation du fingerprint). V1 (`gate_v_campaign.py`) confirmé
bit-pour-bit inchangé, formule documentée en détail (Décision 20.1).

Contrat du plan V2 : exactement 27 champs normatifs, déterministes, SANS `created_at` ni aucun
timestamp ; `policy_git_sha` est le 27e champ, porté directement par le plan et cohérent avec la
`GateVPreRegistration`. Frontière `policy_git_sha` (Décision 20.10) : à la CRÉATION de la
PreRegistration, `policy_git_sha == HEAD` reste exigé (Slice B, inchangé) ; à la relecture
historique du plan, on vérifie le commit/blob historique référencé (commit résolvable, blob,
`validation_policy_id`, `policy_content_hash`, cohérence PreRegistration) SANS exiger
`HEAD courant == policy_git_sha`. `verify_policy_git_provenance()` actuelle est orientée création :
une vérification historique distincte sera à ajouter en implémentation Slice C (Slice B non modifié).

**Aucun code Python Slice C, aucun test, aucune campagne réelle, aucun accès `FINAL_HOLDOUT`
produit par cette mission de conception.**

**Statut** : `Slice A` = INTEGRATED. `Slice B` = INTEGRATED. `Slice C` = SPEC LOCKED, READY FOR
IMPLEMENTATION uniquement après validation explicite de l'utilisateur de la Décision 20. `AF-V-07`
overall = IN PROGRESS. `AF-V-08` = DONE, inchangée. `GATE V` reste NON PASSÉE.

## 41. `AF-V-07` — Slice C intégrée ; Slice D (`GateVCampaignManifestV2` / discrimination V1-V2) spécifiée et verrouillée (2026-10-06)

**Checkpoint (source de vérité, remplace la mention « SPEC LOCKED » de §40 pour Slice C — §40 reste
l'historique)** : `Slice A` = INTEGRATED. `Slice B` = INTEGRATED (+ correctifs de compatibilité B↔C :
`policy_git_sha` toujours SHA complet canonique, validation canonique partagée du protocole,
`assessment_semantics_version` validé avant le scope exclusif). `Slice C` = **IMPLEMENTED + TESTED +
INTEGRATED** (`gate_v_campaign_plan_v2.py`, commit `59dd901f74370bac96ba9564a4729347ba994d81`, parent
`f1e39713d43479a0ed038c5652197a323d087cd2`, suite complète **1915/1915**, `origin/master` = ce commit).
`AF-V-07` = IN PROGRESS. `AF-V-08` = DONE. `GATE V` = NON PASSÉE. `FINAL_HOLDOUT` = NON ACCÉDÉ.

**Mission Slice D (DESIGN ONLY, aucun code, aucun test, aucun commit)** — ADR 0025 **Décision 21**
(additive, ADR 0025 §Conséquences mis à jour). Décisions clés :
- **Type** : `GateVCampaignManifestV2`, dataclass **distincte** (Option B ; ni type commun à champs
  optionnels, ni wrapper de persistance), version sémantique `gate_v_campaign_manifest_v2`,
  **17 champs** (4 d'identité/liaison immuables, 8 de progression monotones, 5 champs `FINAL_HOLDOUT`
  **réservés forcés `None`** en Slice D — Décision 13 respectée sans état hybride, extension monotone
  future vérifiée contre le Claim). Pas de `manifest_content_hash` (identité = `campaign_id`).
- **Statuts V2** : `READY_FOR_EXECUTION`, `RUNNING`, `EVIDENCE_INCOMPLETE`,
  `EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT`, `TECHNICAL_FAILURE`. `EVIDENCE_COMPLETE_AWAITING_POLICY`
  (V1, suppose l'OOS) est **interdit** en V2. Jamais `PASS`/`FAIL`/Champion.
- **Autorité** = `ValidationRun` persistées rechargées du disque + Plan V2 ; le Manifest n'est que
  pointeurs + marqueurs non dérivables. Précondition du futur Claim = un seul prédicat (WF + MC + PS
  de TOUS les `expected_fold_ids`, aucun `TECHNICAL_FAILURE` marqueur **ni** sentinelle, champs
  réservés nuls) — **nécessaire, jamais suffisante** : le Manifest n'est JAMAIS le verrou
  (`FinalHoldoutAccessClaim` + `O_CREAT|O_EXCL` seuls font autorité).
- **Persistance** : création `save_exclusive()` ; mises à jour par **commandes nommées idempotentes**
  via `save_atomic_overwrite()` **SOUS le verrou transitoire `manifest.update.lock`
  (`O_CREAT|O_EXCL`)** (les `Attach…` effacent `running` dans la même écriture, parité V1). **Correction
  (2026-10-06) d'un MAJOR de conception** : `manifest_revision` + `save_atomic_overwrite()` n'est PAS un
  compare-and-swap inter-processus atomique (TOCTOU : deux `os.replace()` peuvent réussir après avoir lu
  la même révision) ; séquence normative en 11 étapes (acquisition, échec fermé si `FileExistsError`,
  rechargement et contrôle de révision SOUS le verrou, revalidation de la commande, écriture, relecture,
  libération) ; verrou résiduel après crash = état d'écriture incertain, **échec fermé, aucun stale-lock
  automatique** (ni délai, ni âge, ni PID, ni retry), récupération manuelle gouvernée ; `manifest_revision`
  = détection d'écriture périmée + audit, jamais l'exclusion ; propriété stricte du verrou (le perdant
  ne le supprime jamais, vérification d'identité de fichier avant `unlink`), collision Windows à
  l'étape d'écriture traitée par relecture sous verrou, exceptions typées distinctes (refus / validé
  avec verrou résiduel / incertain) ; **le verrou n'est PAS un
  `FinalHoldoutAccessClaim`** (sérialise temporairement une mise à jour mutable, supprimé après
  transaction ; le Claim consomme définitivement le droit et n'est jamais supprimé). Sentinelle exclusive
  `technical_failure.json` conservée, indépendante du verrou (existence = le fait) ; statut **persisté**
  (`marker_status`) distinct du statut **effectif** (sentinelle incluse) ; Manifest « en retard » sur les
  preuves = légal (adoption à la reprise, structure + « scoped » seulement), « en avance » = erreur.
  Tests futurs exigés : deux processus réels, un seul acquiert le verrou, second = `FileExistsError`,
  aucune référence perdue, révision périmée refusée, crash après acquisition, aucun auto-nettoyage,
  aucun Claim créé.
- **Précondition du Claim** : `assert_gate_v_pre_holdout_evidence_complete(plan, campaign_dir)` ;
  la revalidation du Plan V2 aux sources reste l'obligation de l'appelant (séquence Décision 11).
- **Discrimination V1/V2** : par le CONTENU (`campaign_plan_semantics_version` du plan,
  `manifest_semantics_version` du manifeste, forme du `campaign_id`), nom du dossier = simple test de
  cohérence, aucun repli V2→V1, hybride refusé fermé. Modules additifs `gate_v_evidence_completeness_v2.py`,
  `gate_v_campaign_manifest_v2.py`, `gate_v_campaign_dispatch.py` ; **`gate_v_campaign.py` non modifié**.
- **Décisions utilisateur VALIDÉES (2026-10-06)** : (1) les prédicats WF/MC/PS V2 sont **réimplémentés
  additivement** dans le module V2, `gate_v_campaign.py` **non modifié**, équivalence verrouillée par
  des **tests différentiels V1/V2** là où les contrats sont communs (l'extraction des helpers privés V1
  n'est plus proposée) ; (2) `TECHNICAL_FAILURE` reste **TERMINAL** dans Slice D, aucun mécanisme de
  reprise/retry conçu, un scope devenu inutilisable est un comportement conservateur accepté jusqu'à un
  futur protocole de reprise auditée.
- Revue adversariale : 17 scénarios + 17 findings supplémentaires (dont 4 MAJOR trouvés par une revue
  indépendante contre le code réel : sentinelle vs statut persisté, atomicité `Attach`+`running`,
  adoption d'une preuve de qualité insuffisante, signature de la précondition ; le MAJOR du faux
  compare-and-swap ; puis 3 MAJOR d'une seconde revue indépendante du contrat de verrou : propriété du
  verrou, collision Windows à l'écriture, échecs Windows d'acquisition/libération) ; **aucun BLOCKER** ; tous les MAJOR **fermés dans la spec** (replay S1-S8 du contrat
  de concurrence : deux writers, transitions différentes, writer périmé, crash après verrou, crash après
  écriture, échec technique concurrent, preuve entre deux mises à jour, claim manuel) ; MINOR acceptés
  listés en Décision 21.12 (dont la production concurrente d'une même preuve, hors Manifest, et la
  longueur de chemin Windows, risque préexistant en V1).

**Aucun code Python, aucun test, aucun `FinalHoldoutAccessClaim`, aucun accès `FINAL_HOLDOUT`, aucune
campagne réelle produits par cette mission.**

**Statut** : `Slice A` = INTEGRATED. `Slice B` = INTEGRATED. `Slice C` = IMPLEMENTED + TESTED +
INTEGRATED. `Slice D` = SPEC LOCKED, NOT IMPLEMENTED (implémentation uniquement après validation
explicite de l'utilisateur de la Décision 21). `AF-V-07` overall = IN PROGRESS. `AF-V-08` = DONE.
`GATE V` NON PASSÉE. `FINAL_HOLDOUT` NON ACCÉDÉ.

## 42. `AF-V-07` — D1–D6, E1 et E2 intégrées ; Décisions 22 et 23 publiées ; addendum E3-A dans un lot documentaire local, non publié (2026-10-13)

**Dernier checkpoint publié vérifié (source de vérité pour ce qui est dans `origin/master`)** : `origin/master` =
`25f395f5bb3ed0d9dd3266de617a12e2598ce301` (commit documentaire de la Décision 23, 956 insertions dans l'ADR 0025),
parent `9c2bf7ef5ccf692e9d89db7b0ca61038bbd962e4` (E2). Le lot documentaire local décrit plus bas se place **au-dessus**
de ce commit et n'est pas poussé : vérifier l'état réel par `git log origin/master..HEAD` et `git status`, le SHA de ce
lot n'étant volontairement pas inscrit ici. Les §39 à §41 restent l'historique ; cette section couvre la période
2026-10-06 → 2026-10-13, que le handoff n'avait pas encore consignée.

**Intégré dans `master`** :
- **Slices D1–D6** (`GateVCampaignManifestV2`, discrimination V1/V2, précondition D5, etc.) : `49ce253` (D1),
  `bbb8aea` (D2), `57878c8` (D3), `2eeade4` (D4), `79941df` (D5), `86b6473` (D6).
- **E1** (`gate_v_final_holdout_claim.py`, cœur pur du `FinalHoldoutAccessClaim`, 14 champs) : commit
  `707ec51b7edc52e5b5d8c4b040d9454f83b27e45`.
- **E2** (`gate_v_final_holdout_claim_acquisition.py` et `atomic_json_store.save_exclusive(durable=True)`, acquisition
  exclusive durable du Claim) : commit `9c2bf7ef5ccf692e9d89db7b0ca61038bbd962e4`. Tests rapportés lors de la revue
  finale d'E2 : 3772 réussis, 2 ignorés (non rejoués depuis).
- **Décision 22** (ADR 0025) : cœur pur du Claim et acquisition ; l'exclusivité est **par campagne** et ne prouve pas la
  fraîcheur du `FINAL_HOLDOUT`.
- **Décision 23** (ADR 0025, commit `25f395f`) : contrat normatif d'E3 — modes `SYNTHETIC`/`REAL`, engagement
  prospectif ancré avant la fenêtre, deux snapshots (S0 de recherche, S_H scellé), preuves de temps, registre mono-hôte
  Linux (`RESERVATION`, `ADMISSION`, `CONSUMPTION`, `REBIND`), `ReadIntent`, lecture unique, `ClosingRecord`.

**Constats structurants à garder en tête** : la fenêtre `FINAL_HOLDOUT` du plan V2 courant est `RETROSPECTIVE_EXPOSED`
(même snapshot et même fenêtre que l'accès documenté d'AF-V-01) ; aucune fenêtre n'est éligible tant qu'un engagement
n'est pas ancré avant `ws` ; le Manifest V2 ne porte que des identifiants ; les coûts d'exécution ne figurent pas dans
le chaînage V2 ; `results/` est gitignoré ; la provenance de S0 se limite à des noms de fichier.

**Lot documentaire LOCAL, NON PUBLIÉ** (un seul commit local au-dessus de `25f395f`, message « docs(gate-v): align E3-A
classification contract and handoff », limité à `docs/adr/0025-gate-v-validation-policy-v1.md` et `AI_HANDOFF.md` ; si
`git log origin/master..HEAD` est vide, ce lot n'a pas été commité ou a été publié, à vérifier) :
- **Addendum E3-A** (ADR 0025, 23.27 et 23.28, avec notes de renvoi dans 23.3, 23.6, 23.10, 23.11, 23.17 et 23.26, et une
  entrée additive dans `Conséquences`). Il aligne la Décision 23 sur le design E3-A : campagne courante par `campaign_id`
  et étage vérifié (suppression de l'exclusion par dossier), comptabilité des essais hors de `inventory_id` mais dans
  `inventory_content_digest`, attestation épinglant `inventory_content_hash`, péremption précisée, contrat de référence de
  la classification (11 énumérations, 11 dataclasses, 16 fonctions, 32 codes de raison) et obligations de test.
- Cette section du handoff.
- **Ce lot n'est pas publié (aucun push) et n'est pas testé** : il est documentaire, aucun code E3-A n'existe. Il a été
  relu par des relecteurs indépendants avant le commit local ; une revue de publication reste à faire avant tout push.
  **Ce lot n'autorise pas le TDD d'E3-A.**

**Statut** : **E3-A = DESIGN LOCKED** (addendum 23.27/23.28 relu, en attente de revue de publication) ; **E3-A = NOT IMPLEMENTED**. `E3` =
documenté, non implémenté. `REAL` = DISABLED, NOT QUALIFIED (aucune qualification d'infrastructure, d'autorité de temps
ni de fournisseur n'est affirmée ; douze portes de qualification non remplies). `AF-V-07` = IN PROGRESS. `AF-V-08` =
DONE. `GATE V` = NON PASSÉE. Aucun Champion qualifié. `FINAL_HOLDOUT` = NON ACCÉDÉ par `AF-V-07`, aucun Claim réel.

**Risques résiduels** : amendements normatifs de l'addendum à approuver (A1 ensemble pertinent et fraîcheur ;
A2 péremption et nouvelles campagnes ; A2 bis contrôles préalables à l'`ADMISSION` ; A3 campagne courante par
`campaign_id` et étage vérifié ; A4 identités d'inventaire et attestation ; A5 règles des enregistrements propres ;
A6 comptabilité des essais ; ces étiquettes désignent les amendements de la mission E3-A, décrits en 23.27.1 à 23.27.5) ;
noms et ordre des champs des dataclasses d'E3-A à faire approuver avant le premier test TDD (23.28) ;
tranche non attribuée en 23.26 pour la persistance des déclarations, de l'attestation et de l'autorisation (proposition :
déclarations en E3-B, modèles d'attestation et d'autorisation en E3-E) ; coût de disponibilité (une nouvelle campagne
tierce ou une clôture périme une attestation avant l'admission) ; REAL non qualifié ; connaissance de marché humaine,
travaux non enregistrés et accès hors E3 restent hors du modèle.

**Prochaine étape** : revue de publication de ce lot documentaire (push uniquement sur autorisation explicite de
l'utilisateur), puis, après autorisation séparée, mission **TDD d'E3-A** (module pur `gate_v_final_holdout_protocol.py`, ordre : instants et énumérations, finding, inventaire,
déclarations, classification, F1–F6, niveau, refus d'admission, identités, pureté).

**Précautions d'environnement** : trois modifications **indexées préexistantes** ne sont pas de cette série et ne
doivent pas être mélangées à un commit documentaire (`AGENTS.md`, `docs/adr/0016-spec-kit-and-skill-orchestration-policy.md`,
`docs/agents/skills-usage.md`) ; le fichier non suivi `=1.12.0` est également préexistant. Utiliser
`git commit --only -- <chemin>` pour isoler un commit. Un hook « Fact-Forcing Gate » exige de présenter des faits avant la
première commande Bash ou la première écriture sur un fichier de la session.

## 43. `AF-V-07` — addenda 23.27/23.28 PUBLIÉS ; mission TDD d'E3-A autorisée (2026-10-14) — fait foi sur le §42

Cette section **prévaut sur le §42** là où celui-ci est devenu périmé (le §42 reste l'historique).

**Checkpoint Git publié au démarrage de la mission TDD** : `master` = `origin/master` =
`72febdecdc7a73fa6c5194b8c1c05d77ec077391` (commit « docs(gate-v): align E3-A classification contract and handoff »),
parent `25f395f5bb3ed0d9dd3266de617a12e2598ce301`. Les addenda **23.27 et 23.28 de l'ADR 0025 sont PUBLIÉS** (poussés,
fast-forward). La mention du §42 « lot documentaire local, non publié » est **périmée**.

**Statut au démarrage** : E3-A = **DESIGN LOCKED** ; l'implémentation TDD est **autorisée par la mission du 2026-10-14**
(fichiers : `gate_v_final_holdout_protocol.py`, `tests/test_gate_v_final_holdout_protocol.py`, `AI_HANDOFF.md`), mais
**n'était pas réalisée au démarrage**. `REAL` = DISABLED, NOT QUALIFIED. `GATE V` = NON PASSÉE. Aucun Champion. Aucun
accès `FINAL_HOLDOUT`, aucun Claim réel. `AF-V-07` = IN PROGRESS.

**Précautions inchangées** : trois modifications indexées préexistantes (`AGENTS.md`, ADR 0016,
`docs/agents/skills-usage.md`, empreinte du diff indexé `8b78a333b37710b5987d1e535c8487e797984df193dc80362efd946ed9670e6f`)
et le fichier non suivi `=1.12.0` ne font pas partie de cette série. `DOMAIN_MODEL.md` est absent à la racine
mais **existe sous `docs/architecture/DOMAIN_MODEL.md`** (correction : une version antérieure de cette section le disait
inexistant, ce qui était inexact) ; le glossaire reste `CONTEXT.md`.

### 43.1 E3-A — implémentation locale, revue finale et régression (2026-10-14) — NON PUBLIÉ

**Checkpoint initial et état Git** : `master` = `origin/master` = `72febdecdc7a73fa6c5194b8c1c05d77ec077391` au démarrage et à
la fin des vérifications. Le lot E3-A est **local** : `gate_v_final_holdout_protocol.py` et
`tests/test_gate_v_final_holdout_protocol.py` (nouveaux), `AI_HANDOFF.md` (modifié). **Il n'est pas publié** ; aucun push
n'a eu lieu. Si `git log origin/master..HEAD` montre un commit « feat(gate-v): implement pure E3-A exposure
classification », il s'agit de ce lot, commité localement et toujours non poussé (son SHA n'est volontairement pas
inscrit ici). Les trois modifications indexées préexistantes (empreinte du diff indexé
`8b78a333b37710b5987d1e535c8487e797984df193dc80362efd946ed9670e6f`) et le fichier non suivi `=1.12.0` ne font pas
partie de la série.

**Statut réel** : E3-A = **IMPLÉMENTÉ ET TESTÉ LOCALEMENT, NON PUBLIÉ**. `AF-V-07` = IN PROGRESS. `REAL` = DISABLED,
NOT QUALIFIED. `GATE V` = NON PASSÉE. Aucun Champion. `FINAL_HOLDOUT` non accédé, aucun Claim réel, aucun backtest, aucune
donnée de marché lue.

**API implémentée (module pur, stdlib seule : `__future__`, `dataclasses`, `datetime`, `enum`, `hashlib`, `json`, `re`,
`typing`)**
- 11 énumérations : `ExposureClass`, `ChronologyLevel`, `OverlapVerdict`, `SourceStatus`, `SourceKind` (12 valeurs, propriétés
  `exposes_data` et `capability_unknown`), `UnresolvedCause` (7), `ConditionStatus`, `TimeProofStatus`, `ReasonCode` (32 = 7 + 25),
  `AdmissionRefusal` (4), `OwnRecordStage` (5).
- 11 dataclasses immuables, champs dans l'ordre approuvé : `ExposureFinding` (10), `TrialAccounting` (6), `ExposureInventory` (7),
  `ExposureDeclaration` (8), `DeclarationSet` (2), `TimeProofFact` (3), `ChronologyFacts` (7), `OwnCampaignContext` (2),
  `ClassificationInput` (4), `FConditionResult` (3), `ExposureClassificationResult` (16).
- 16 fonctions publiques : `normalize_utc_instant`, `build_exposure_finding`, `build_exposure_inventory`,
  `build_exposure_declaration`, `build_chronology_facts`, `partition_own_records`, `compute_exposure_inventory_id`,
  `compute_inventory_content_digest`, `compute_declaration_id`, `compute_classification_input_digest`,
  `compute_static_sources_digest`, `compute_overlap_projection_hash`, `compute_effective_t_sel`, `classify_exposure`,
  `admission_refusals`, `classification_result_to_record`. Les fonctions d'identité qui dépendent de l'absorption prennent
  `(inventory, own_context)`.

**Résultats complets des tests** (environnement : Windows-10-10.0.19045, Python 3.13.7, `.venv` du dépôt)
- Tests dédiés : **345 réussis, 0 ignoré, 0 échoué** (`.venv/Scripts/python.exe -B -m pytest tests/test_gate_v_final_holdout_protocol.py -q -p no:cacheprovider`).
- **Suite complète sur la version finale, tests E3-A inclus** : `.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider -rs`
  → **4114 réussis, 5 ignorés, 0 échoué** en 582 s. Les fichiers E3-A n'ont pas changé pendant cette campagne
  (SHA-256 du module `81fbb24b…1b82`, du test `717d07e2…0ba2`, identiques avant et après).
- 5 ignorés, **non démontrés sous Windows** (aucune qualification de `REAL` n'en découle) :
  `tests/test_atomic_json_store_durable.py:270` (`fsync` de répertoire POSIX) ; `tests/test_gate_v_final_holdout_claim_acquisition.py:837`,
  `:873`, `:945` (liens symboliques, privilège Windows requis) ; `:878` (FIFO, POSIX uniquement).
- Contrôle de pureté par AST (imports restreints à la liste blanche, aucun appel `open`, aucune lecture d'horloge, aucune
  référence à E1/E2, au moteur ou à Streamlit) : inclus dans les 345 tests, avec contre-épreuves sur sources interdites.
- Compatibilité E1/E2 : tests E1/E2 et `atomic_json_store` verts dans la suite complète ; `_canonical_json` égal à celui d'E1 (test).
- Campagnes de mutation sur copies hors dépôt : **32 mutations distinctes, 0 survivante**.

**Revues indépendantes et corrections**
- Revue de la première implémentation : 0 BLOCKER, 0 MAJOR, 8 MINOR, dont 7 corrigés en TDD (débordement de la marge F4, marge
  négative jugée `UNVERIFIED`, ordre des déclarations, invariants du résultat, projection `REGISTRY_UNREADABLE`, racines
  dédupliquées, trous de tests).
- Revue finale à deux axes (skill `code-review`) : axe Standards 0 BLOCKER, 0 MAJOR, 14 MINOR ; axe Spec 0 BLOCKER, 0 MAJOR,
  7 MINOR/INFO ; aucune contradiction normative avec l'ADR.
- Contournement traité en TDD : les fonctions d'identité acceptaient une réservation ou admission étrangère `RESOLVED` non
  recoupante que `ClassificationInput` refusait ; la règle de listabilité est maintenant appliquée par **toutes** les fonctions
  qui prennent le contexte (RED : 11 échecs, puis GREEN).
- Défauts trouvés par les nouveaux tests : offset ISO `+00:60` accepté (regex resserré) ; `TypeError` fuyant des builders sur
  élément invalide (désormais `ValueError`) ; raisons de condition incohérentes avec leur statut et codes F orphelins dans
  `reasons` (nouveaux invariants du résultat) ; trous de couverture comblés.
- Relecture indépendante ciblée des corrections tardives : 0 BLOCKER, 0 MAJOR, 2 MINOR (constante morte supprimée ;
  `ValueError` sur un engagement de mauvais type conservé, D9).
- MINOR acceptés sans changement (aucun défaut fonctionnel démontré) : recalculs redondants de `partition_own_records`,
  `**_unused` des évaluateurs F3 à F5, table de jumelage classe/F1 répétée, longueur de `classify_exposure`, `pytest.raises`
  sans `match=`. Aucun refactor n'a été fait pour réduire les lignes.

**Décisions d'interprétation D1 à D10** (aucune ne nécessite de modifier l'ADR ; aucune contradiction normative majeure)
- Application directe de l'ADR : D6 (cumul littéral de R2 et de 23.27.2 : un enregistrement propre non exposant non résolu est
  non résolu ET anomalie), D9 (convention E1 : `TypeError` pour une erreur d'appel, `ValueError` pour une valeur invalide),
  D10 (`admission_refusals` : refus de classe, SINON refus de niveau, puis chevauchement ; 23.28).
- Choix d'implémentation compatible avec l'ADR : D1 (position des identifiants déclarés à partir de 1), D2 (pas de `t_sel` à
  l'engagement donne un `t_sel` effectif absent, ligne « absent » de la matrice 23.28 ; une déclaration ne le fournit pas),
  D3 (ingestion ou plage inconnue donne `F5_INGESTION_MISSING`, faute de code dédié), D4 (marge jugée seulement pour une
  preuve `VALID` de sa propre réservation), D5 (source de capacité inconnue non résolue comptée en `F2_EXPOSURE_WINDOW_UNKNOWN`,
  conservateur).
- Choix compatible **à ratifier explicitement** : D7 (`declared_trial_counts` est `Optional[TrialAccounting]` ; leur présence
  entre dans `declaration_id` et `input_digest`), D8 (libellés `missing:RESERVATION` et `missing:ADMISSION` issus de l'ADR,
  `missing:FINAL_HOLDOUT_CLAIM` et `missing:CONSUMPTION` extrapolés ; ils entrent dans la préimage de `classification_id`).

**Risques résiduels** : (1) rien n'est persisté ni branché : E3-B à E3-J restent à faire ; (2) les vecteurs SHA-256 figés
ne couvrent que le scénario B0 (les autres préimages sont vérifiées par un calcul indépendant dans le test) ; (3) aucun
recoupement des faits chronologiques avec l'étage (non exigé par l'ADR) ; (4) les 5 tests POSIX ignorés sous Windows ;
(5) `fromisoformat` accepte les fractions de 1 à 5 chiffres sous Python >= 3.11 seulement (le projet est en 3.13) ; (6) un
tuple de refus vide n'est jamais une autorisation : E3-J devra refuser de traiter une classification d'étage `ADMITTED` ou
supérieur comme une autorisation (test E3-J obligatoire, 23.27.7).

**Compatibilité avec les futures slices** : E3-B construira l'inventaire avec les builders (racines `scanned_roots`
statiques, verdicts de recouvrement calculés hors E3-A, règle de listabilité déjà appliquée ici) et la primitive publique de
recouvrement (`_windows_overlap` est privée ici) ; E3-D dérivera l'étage des artefacts persistés ; E3-E fournira les faits
de `ChronologyFacts` ; E3-J reclassifiera, comparera les identités et ne tirera jamais une admission d'un tuple vide.

**Prochaine étape** : revue de publication de ce lot (push uniquement sur autorisation explicite). La mission E3-B
(construction et lecture stricte de l'inventaire, persistance du A0 et des déclarations) ne démarre qu'**après publication
d'E3-A**.

## 44. `AF-V-07` — E3-A PUBLIÉ ; conception E3-B en revue (2026-10-13) — fait foi sur les §42, §43 et §43.1

Cette section **prévaut** sur les états périmés des §42, §43 et §43.1, qui sont conservés comme historique.

**Checkpoint publié vérifié** : `origin/master` = `7f30d0752465b755e8c08460e8ffb4ac13ff1d47` (`master` local identique à la date de
la vérification ; « feat(gate-v):
implement pure E3-A exposure classification »), parent unique `72febdecdc7a73fa6c5194b8c1c05d77ec077391` (« docs(gate-v):
align E3-A classification contract and handoff »). Trois fichiers, +4 170 lignes, aucune suppression ; vérifié aussi par
l'API GitHub.

**Statut E3-A : IMPLEMENTED + TESTED + PUBLISHED.** Mesure rapportée : **4 114 PASS, 5 SKIP, 0 FAIL**, dont **345 tests dédiés
E3-A** (`.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider -rs`, Windows 10, Python 3.13.7, 582 s).

**Dates réellement démontrées (correction des §43 et §43.1)** : les mentions « 2026-10-14 » des §43 et §43.1 (titre, « mesure »)
n'étaient **pas démontrées** et sont **erronées**. Preuves : empreintes des fichiers figées le 2026-10-13 à 20:01:19 +0200 ;
sortie de la campagne complète datée du 2026-10-13 à 20:12:28 +0200 ; commit E3-A daté du 2026-10-13 à 20:15:59 +0200 ; commit
précédent `72febde` le 2026-10-13 à 16:49:11 +0200 ; commit `25f395f` le 2026-10-12 à 18:34:09 +0200. La mesure 4 114/5/0
date donc du **2026-10-13** (fin de campagne 20:12:28 +0200) ; l'heure de début (environ 20:02:46) est déduite de la durée de
582 s, non mesurée.

**Limites POSIX non démontrées sous Windows (5 tests ignorés, aucune qualification de `REAL`)** :
`tests/test_atomic_json_store_durable.py:270` (`fsync` de répertoire) ; `tests/test_gate_v_final_holdout_claim_acquisition.py:837`,
`:873`, `:945` (liens symboliques, privilège Windows requis) ; `:878` (FIFO).

**Décisions D7 et D8 d'E3-A** : choix d'implémentation **compatibles** avec l'ADR, retenus pour E3-A (`declared_trial_counts`
optionnel ; libellés `missing:RESERVATION`, `missing:ADMISSION`, `missing:FINAL_HOLDOUT_CLAIM`, `missing:CONSUMPTION`).
Ce ne sont **pas** des règles normatives supplémentaires de l'ADR 0025 et l'ADR n'a pas été modifiée par ces choix (elle l'est ensuite
par l'addendum 23.29, voir le §45).

**Statut courant (état à la date du §44, PÉRIMÉ : voir le §45)** : **E3-B DESIGN REVIEW DONE — DESIGN NOT LOCKED (ADR CLARIFICATION REQUIRED, voir §44.1) ; E3-B NOT
IMPLEMENTED** (aucun code, aucun test, aucune écriture hors ce fichier). `AF-V-07` = IN PROGRESS. `REAL` = DISABLED, NOT QUALIFIED. `GATE V` = NON PASSÉE. Aucun Champion qualifié.
`FINAL_HOLDOUT` non accédé, aucun Claim réel.

**Précautions inchangées** : trois modifications indexées préexistantes (`AGENTS.md`, ADR 0016, `docs/agents/skills-usage.md`,
empreinte du diff indexé `8b78a333b37710b5987d1e535c8487e797984df193dc80362efd946ed9670e6f`) et le fichier non suivi
`=1.12.0` ne font pas partie de cette série ; `app_corrupted_backup.py` n'est jamais modifié.

### 44.1 E3-B — conception terminée : DESIGN NOT LOCKED (une clarification ADR requise) ; NON IMPLÉMENTÉ — Q-1 résolue ensuite, voir le §45

**État exact à la date du §44.1 (2026-10-13, périmé sur l'ADR : voir le §45)** : conception et revues uniquement ; aucun code ni test
E3-B, ADR alors inchangée, aucun commit. Le brouillon de
conception détaillé n'existait que dans le scratchpad de session ; **ce paragraphe en est la trace durable**. Trois revues
indépendantes (extraction normative de l'ADR, sécurité des fichiers/Windows, contrats scientifiques), puis une revue de
fermeture du design v2 : aucun BLOCKER restant hors Q-1 ; les corrections ci-dessous sont **intégrées au design** mais ne
sont pas du code testé.

**Périmètre E3-B (23.27.7)** : primitive publique de recouvrement, listers/scanners stricts, construction des `ExposureFinding` et de
`ExposureInventory` (réutilise E3-A, aucune classification dupliquée), compteurs `TrialAccounting`, persistance et lecture stricte
du A0, persistance et lecture stricte des déclarations. Hors périmètre : admissions et registre (E3-C/D), engagement et preuves de
temps (E3-E), ingestion de `S_H` (E3-F), événement canonique et lister strict d'événements additif de `dataset_split.py` (E3-G),
orchestration et décisions humaines (E3-J). E3-B n'ouvre aucune donnée `S_H`, n'appelle ni E2 ni le moteur, ne produit aucune permission.

**Architecture proposée (monolithe modulaire, noms plats)** : `gate_v_exposure_scan.py` (E/S strictes : racines, noms, lecteur JSON),
`gate_v_exposure_sources.py` (primitive d'intervalles + interprètes de sources + index des plans de split),
`gate_v_exposure_inventory.py` (assemblage + comptabilité), `gate_v_exposure_store.py` (persistance/relecture A0 puis déclarations).
Graphe : store → inventory → sources → scan ; tous vers E3-A ; sources vers le parseur strict de Claim d'E1 ; jamais E2, moteur,
`dataset_split` ni lecteur tolérant. Sous-lots TDD : **B1** intervalles ; **B2** scan strict ; **B3** interprètes de sources ;
**B4** assemblage et comptabilité ; **B5** persistance/relecture A0 ; **B6** déclarations (bloqué par Q-1 et par la publication
par lien d'E3-C). B1 à B5 deviennent TDD-prêts après approbation explicite du design (errata v2.1 inclus).

**Contrats retenus (choix de conception compatibles, à approuver ; aucun ne modifie l'ADR)**
- *Refus vs finding* : un échec de STRUCTURE (racine absente ou vide, évasion de racine, lien ou jonction, nom non portable, nom
  réservé Windows, sous-répertoire illisible, plafond atteint, listage instable, racines imbriquées) REFUSE sans produire d'A0 ;
  un échec de SOURCE dans une racine saine (JSON illisible, schéma inconnu, fenêtre ou fuseau indéterminable, plan introuvable,
  `*.tmp` hors `exposure/`, répertoire ou fichier inconnu) devient un finding `UNRESOLVED` (donc `UNDETERMINED`). Jamais d'inventaire
  « complet et frais » silencieux ; absence de trace n'est pas preuve d'absence.
- *Sources* : table ancrée sur un `<campaign_dir>` identifié (son `plan.json` porte `campaign_id` égal au nom du dossier) ou sur une
  structure connue ; trois classes (exposant, informatif, inerte) ; **aucun joker** : `datasets/**` et `exposure/**` n'énumèrent que
  des noms connus ; tout fichier hors table est seulement `lstat`é puis finding `UNKNOWN_SOURCE_TYPE` ; tout répertoire inconnu est un
  finding non descendu ; un dossier d'ancrage sans fichier-ancre lisible (`job_*` sans `config_used.json`) est `UNRESOLVED`. Les
  données de marché (`raw/ig_prices_raw.json`, `*.csv`) ne sont jamais ouvertes.
- *Identité* : `source_id = <slug>:<label de racine>/<chemin POSIX relatif>` (copies = ids distincts) ; `content_hash` = SHA-256 des
  octets bruts dès que le fichier est lu ; `scanned_roots` = labels portables (chemins résolus consignés dans l'A0 mais hors
  `inventory_id` et hors digests).
- *Fenêtres* : demi-ouvertes UTC ; sources d'exécution legacy (inclusives par défaut dans le moteur, vérifié dans `optimizer.py` et
  `engine.py`) converties en `[start, end+1µs)`, d'où des fenêtres jointives qui se recoupent pour ces sources (conservateur) ; Claim,
  plan, registre et job ISO-« T » restent exacts ; date civile ou chaîne naïve = `TIMEZONE_UNKNOWN` (Paris implicite non supposé) ;
  sur le corpus actuel presque tous les jobs seront `UNRESOLVED` (33 des 43 sans bornes). Plans indexés par
  `(split_plan_id, fingerprint)`, fenêtres de toutes les sources disponibles tenues de concorder, `ValidationRun` non OOS inventoriés
  si leur fenêtre recoupe `W` ou finit après `ws`.
- *A0* : `<campaign_dir>/exposure/inventory_<inventory_content_hash>.json` (chemin normatif 23.13), hash sur JSON compact canonique
  de toutes les autres clés (`created_at` inclus), fichier en `indent=2`, relecture stricte avec recalcul des identités E3-A et
  point fixe d'octets ; publication par `save_exclusive(durable=True)` (profil simulé sous Windows) via une fonction privée, sans
  répertoire créé récursivement ; `created_at` injecté ; plusieurs A0 coexistent ; un fichier tronqué au nom attendu impose un nouveau
  `created_at`, jamais de suppression.
- *Registre* : vue injectée par E3-D (porte `registry_id` et la tête de chaîne) ; absente = erreur d'appel ; illisible = finding
  `REGISTRY_UNREADABLE` et `complete=False`.
- *Comptabilité* : six compteurs ; `campaigns` = campagnes distinctes de la chaîne (campagne courante exclue de l'A0) ;
  `abandoned_reservations` = sans `ClosingRecord` terminal (introuvable = abandonnée) ; ingestion échouée et engagements nuls fournis
  par des vues, provenance `OBSERVED` / `PARTIAL` / `NOT_OBSERVED` hors digest ; nombres déclarés jamais fusionnés par E3-B.

**Questions normatives**
- **Q-1 [N] BLOQUANTE (B6 uniquement)** : E3-A refuse toute déclaration référençant un autre `inventory_id` et exige une chaîne
  `seq` 1..n, alors que le chemin normatif `exposure/declaration_<seq>.json` est unique par campagne ; quand l'`inventory_id` change
  la nouvelle chaîne n'a aucun emplacement valide. Recommandation : amender ADR 23.13 en
  `exposure/<inventory_id>/declaration_<seq4>.json` (E3-A inchangé ; assouplir `DeclarationSet` rejeté car il modifie l'API publiée
  et contredit 23.27.6 ; une chaîne par campagne rejetée car une `RESERVATION` n'est jamais libérée). Même défaut pour
  `exposure/attestation.json` face aux « attestations successives » (à traiter avec E3-E).
- Q-0 [R] : note de renvoi sur 23.11 étape 1 (« refuse » signifie aucune classe `FRESH`). Q-2 : fenêtres des `ValidationRun`
  walk-forward, Monte-Carlo et stabilité. Q-3 : agrégation observé + déclaré dans le `ClosingRecord`. Q-4 : critère « source
  prouvée exclusive » des exécutions (E3-G). Ces quatre ne bloquent pas B1 à B5.

**Risques résiduels** : les racines d'audit sont choisies par l'appelant (rien ne les lie à une configuration de root absente à
HEAD) : E3-J et l'attestation devront les épingler ; le listage Windows n'est ni trié ni atomique (détection par double passe, pas
de snapshot) ; durabilité de répertoire non démontrable sous Windows ; symlinks non testés sans privilège (jonctions détectées) ;
un `*.tmp` orphelin du corpus réel rendra l'inventaire courant `UNDETERMINED` tant qu'il n'est pas traité ; événements étendus
23.13 classés `INVALID_SCHEMA` tant qu'E3-G n'a pas défini leur schéma.

**Prochaine étape** : décision de l'utilisateur sur Q-1 (et sur les choix compatibles ci-dessus). Si elle est positive : approuver le
design et ouvrir la TDD de B1 à B5 (B6 après l'amendement ADR et la publication par lien d'E3-C). Aucune TDD avant validation.

## 45. `AF-V-07` — Q-1 résolue par l'addendum ADR 23.29 ; E3-B DESIGN LOCKED sous réserve de publication documentaire (2026-10-13) — prévaut sur le §44.1 pour Q-1 (état avant publication, périmé sur la publication : voir le §46)

**Checkpoint publié** : `origin/master` = `7f30d0752465b755e8c08460e8ffb4ac13ff1d47` (E3-A, parent
`72febdecdc7a73fa6c5194b8c1c05d77ec077391`). Les corrections de dates du §44 restent valables (tout est du 2026-10-13). **L'addendum
23.29 et les §44 à §45 ne sont PAS publiés.** Ils sont, selon l'état du dépôt, soit encore des modifications locales non commitées de
`docs/adr/0025-gate-v-validation-policy-v1.md` (addendum 23.29, six notes de renvoi dans 23.10, 23.11 (trois), 23.13 et 23.24, une entrée dans `Conséquences` ; les lignes
« supprimées » du diff sont des lignes d'origine allongées d'une note) et de ce fichier, soit un commit LOCAL « docs(gate-v): lock E3-B
exposure inventory and declaration lineage design » : vérifier par `git log origin/master..HEAD` (aucun SHA n'est inscrit ici). Dans
les deux cas : aucun push, aucun code, aucun test E3-B. **Approbation de l'utilisateur (2026-10-13)** : le principe architectural de
Q-1 et les choix présentés dans le rapport de conception sont approuvés, sous réserve de la revue finale de 23.29.

**Statuts (à ne pas confondre)**
| Objet | DOCUMENTED | DESIGN LOCKED | IMPLEMENTED | TESTED | PUBLISHED |
|---|---|---|---|---|---|
| E3-A | oui | oui | **oui** | **oui** (345 dédiés ; 4 114 PASS, 5 SKIP, 0 FAIL, 2026-10-13) | **oui** (`7f30d07`) |
| Addendum ADR 23.29 | **oui (local)** | — | — | — | **non** |
| E3-B (B1 à B5) | oui (§44.1, §45) | **sous réserve de publication documentaire** | **non** | non | non |
| E3-B B6 (déclarations) | oui | **sous réserve** ; la publication dépend d'E3-C | **non** | non | non |
B1 à B5 sont **candidats à une prochaine mission TDD, après publication de l'addendum et autorisation explicite** ; la lecture et la
vérification de B6 ne dépendent pas d'E3-C, sa publication en dépend.
`REAL` = DISABLED, NOT QUALIFIED. `GATE V` = NON PASSÉE. Aucun Champion qualifié. `FINAL_HOLDOUT` non accédé, aucun Claim réel.

**Q-1 résolue (documentairement)** : déclarations et attestations par répertoire d'inventaire
`exposure/<inventory_id>/declaration_<seq4>.json` et `exposure/<inventory_id>/attestation_<seq4>.json` ; E3-A inchangé
(`DeclarationSet` reçoit la seule chaîne terminale). **Continuité** : lignée linéaire de chaînes reliées par `carried_from` dans la
première déclaration, avec report cumulatif explicite des expositions *déclarées* (renumérotées `declared:0001:<pos4>`), `t_sel` jamais
diminué (E3-A seul ne l'impose pas : la sûreté repose sur le chargeur de lignée d'E3-B), bifurcation, retour à un ancien inventaire,
chaîne absente ou illisible = refus ; `declaration_lineage_digest` épinglé par l'attestation. Aucune rétractation dans cette version.
Plusieurs A0 de même `inventory_id` partagent la chaîne. Attestations en slots denses jamais écrasés ; après l'`ADMISSION` seule
l'attestation épinglée par hash compte.

**Trois clarifications fermées** : (A) provenance des compteurs `OBSERVED` / `PARTIAL` / `NOT_OBSERVED` (jamais un zéro vérifié ;
règle `REAL` « tous `OBSERVED` » renvoyée à E3-J, Q-5) ; (B) la double passe de listage détecte un changement observable entre deux
passes, sans snapshot atomique ni garantie après la seconde passe ; (C) l'A0 peut être publié par `save_exclusive(durable=True)` sans
E3-C, la **publication** des déclarations et attestations dépend de la primitive par lien d'E3-C (motif d'orphelin
`.exposure.tmp.<32hex>`), la lecture et la vérification n'en dépendent pas.

**Réserves du « DESIGN LOCKED »** : l'amendement a été relu par un relecteur indépendant (premier passage : 0 BLOCKER, 3 MAJOR, 9 MINOR,
corrigés ; fermeture : 0 BLOCKER, 0 MAJOR, 7 retouches rédactionnelles), puis par un second relecteur indépendant sans contexte
antérieur, sur le texte final : 0 BLOCKER, 2 MAJOR (conflit avec la clause « attestation remplacée » de 23.10 ; portée de `complete` face
à la provenance) et 10 MINOR, tous corrigés dans les deux fichiers ; relecture limitée des passages modifiés : 0 BLOCKER, 0 MAJOR, puis
6 retouches de comptage et de formulation appliquées sans nouvelle relecture. L'errata v2.1 de la conception (§44.1) n'a pas eu de relecture indépendante distincte de
ces passes. Le verrouillage reste soumis à la **publication documentaire** (push sur autorisation explicite).

**Classification des choix du §44.1 et du §45** (aucune formule, aucun hash ni aucune autorité existants n'est modifié)
- *Conforme directement à une règle existante* : chemin du A0 `exposure/inventory_<hash>.json` et son hash couvrant le contenu intégral
  avec `created_at` (23.13, 23.27.3) ; fenêtres demi-ouvertes UTC ; `scanned_roots` statiques ; comptabilité hors `inventory_id`.
- *Choix d'implémentation compatible, approuvé* : refus de structure contre finding de source (concilie 23.11 étape 1 et 23.3) ; table de
  sources ancrée sans joker ; `source_id` = slug + label + chemin POSIX relatif ; `content_hash` = SHA-256 des octets bruts ; `[start,
  end+1µs)` pour les exécutions legacy inclusives ; date naïve = `TIMEZONE_UNKNOWN` ; plans indexés par `(id, fingerprint)` ; registre
  injecté ; labels de racines portables.
- *Nouvelle règle normative explicitement exposée dans 23.29 et approuvée (nouvelles identités ou contraintes, aucune formule existante
  modifiée)* : chemins par `inventory_id` et numérotation `seq4` dense plafonnée à 9 999 ; plusieurs A0 de même `inventory_id`
  partageant une chaîne ; `declaration_content_hash` (SHA-256 du JSON canonique de l'enveloppe sans ce champ, `created_at` inclus),
  `declaration_lineage_digest`, `carried_from` ; lignée et report cumulatif récurrent (refus au-delà de 9 999 reports) ; interdiction de
  toute rétractation ; chargeur de lignée seule source de `DeclarationSet` ; sérialiseur unique (`sort_keys`, `indent=2`, LF, UTF-8,
  sans flottant) et orphelin `.exposure.tmp.<32hex>` imposés à la primitive d'E3-C ; publication des déclarations et attestations sans
  repli `O_EXCL` et indisponible avant E3-C ; attestation « remplacée » = fichier épinglé absent ou différent ; provenance des
  compteurs ; double passe de listage et son nombre d'essais (23.24).
- *Questions NON tranchées (aucune approbation implicite)* : Q-0, Q-2, Q-3, Q-4, Q-5 (règle `REAL` « tous les compteurs `OBSERVED` »).

**Dépendances** : E3-C (publication par lien, sérialisation éventuelle de la lignée) ; E3-D (vue du registre, `closing_lookup`) ;
E3-E (schéma d'attestation, engagement, preuves de temps) ; E3-G (lister strict d'événements étendus, critère de source prouvée
exclusive) ; E3-J (chargeur de lignée seule source de `DeclarationSet`, règle `REAL` des compteurs, reprise après `ADMISSION`).

**Contrôles scientifiques restants** : matrice TDD de 23.29.8 et du §44.1 (RED/GREEN) ; relecture indépendante du code ; test
d'équivalence de la primitive d'intervalles avec la formule privée d'E3-A ; test d'équivalence de la discrimination V1/V2 sur octets
déjà lus ; réplique synthétique de la disposition réelle de `results/`. Questions ouvertes non bloquantes : Q-0 (note de renvoi sur
« refuse » de 23.11 étape 1), Q-2, Q-3, Q-4, Q-5.

**Prochaine étape unique** : revue de publication du commit documentaire local (push uniquement sur autorisation explicite). Rien
d'autre n'est autorisé avant : ni TDD E3-B (B1 à B5 ne démarrent qu'après publication et autorisation), ni push implicite.

## 46. `AF-V-07` — E3-A publié ; addendum ADR 23.29 PUBLIÉ ; E3-B1 IMPLÉMENTÉ + TESTÉ LOCALEMENT, NON PUBLIÉ (2026-10-14) — fait foi sur le §45

Cette section **prévaut sur le §45**, dont les mentions « NON publié », « commit LOCAL » et « prochaine étape unique : revue de
publication » décrivent l'état **antérieur au push** et sont **périmées** (le §45 reste l'historique).

**Publication démontrée** : commit `3b7dd07b255514bd61245160fa27ac0eb4b877ff` (« docs(gate-v): lock E3-B exposure inventory and
declaration lineage design », daté du 2026-10-13 23:59:40 +0200), parent unique `7f30d0752465b755e8c08460e8ffb4ac13ff1d47`, poussé
sur `master` (événement GitHub `PushEvent` du **2026-10-14 à 06:00:06 UTC**) ; l'API GitHub donne deux fichiers, 429 ajouts et
6 suppressions. Le commit précédent `7f30d07` (E3-A) a été poussé le 2026-10-13 à 18:54:56 UTC.

**Statuts au début de la mission B1** : E3-A = IMPLEMENTED + TESTED + PUBLISHED (4 114 PASS, 5 SKIP, 0 FAIL mesurés le 2026-10-13).
Addendum 23.29 = DOCUMENTED + PUBLISHED. E3-B = DESIGN LOCKED + DOCUMENTED + PUBLISHED, **NOT IMPLEMENTED** au début de la mission.
`REAL` = DISABLED, NOT QUALIFIED. `GATE V` = NON PASSÉE. Aucun Champion qualifié. `FINAL_HOLDOUT` non accédé, aucun Claim réel.
`AF-V-07` = IN PROGRESS.

**Mission B1 (autorisation de l'utilisateur, 2026-10-14)** : implémentation LOCALE en TDD de **B1 seulement** (primitive
d'intervalles UTC demi-ouverts : module `gate_v_exposure_sources.py` et `tests/test_gate_v_exposure_sources.py`), sans commit ni push ;
une mission ultérieure a autorisé une revue finale et au plus un commit LOCAL (jamais de push).
B2 à B6 : NOT IMPLEMENTED.

**Résultat de la mission B1 (mesuré le 2026-10-14, sur la version définitive des octets)** — `gate_v_exposure_sources.py` (nouveau) et
`tests/test_gate_v_exposure_sources.py` (nouveau) : **E3-B1 = IMPLEMENTED + TESTED LOCALLY**. Statut de publication : voir la dernière
phrase de ce paragraphe (le commit local éventuel est **non publié** ; son SHA n'est volontairement pas consigné ici).
- **API publique (5 fonctions pures, aucune classe, aucun état global, pas de `__all__`)** : `normalize_window(start_utc, end_utc) ->
  tuple[str, str]` ; `windows_overlap(a_start, a_end, b_start, b_end) -> bool` ; `overlap_verdict(a_start, a_end, b_start, b_end) ->
  OverlapVerdict` (`OVERLAPS` ou `NO_OVERLAP`, jamais `UNKNOWN` : toute entrée invalide lève) ; `inclusive_end_to_exclusive(end_inclusive)
  -> str` (`+1µs`, `ValueError` à `9999-12-31T23:59:59.999999Z`) ; `inclusive_window_to_half_open(start_utc, end_inclusive_utc) ->
  tuple[str, str]` (exige `start <= end_inclusive`). Les noms viennent du design E3-B (§44), l'ADR ne les nomme pas.
- **Contrat** : fenêtres `[start, end)`, formule `a.start < b.end ET b.start < a.end` sur datetimes parsés ; instants normalisés par le
  `normalize_utc_instant` PUBLIC d'E3-A ; le module n'importe que `datetime`, `__future__`, `normalize_utc_instant` et `OverlapVerdict`
  (aucun symbole privé d'E3-A, test AST) ; `TypeError` pour tout non-`str` (bool, sous-classe de `str` comprises) avec priorité sur
  toute `ValueError`, quel que soit l'ordre des arguments ; la conversion inclusive n'est jamais automatique (jointives = pas de
  recouvrement) ; les sorties de plage via offset (`0001-01-01T00:00:00+00:01`, `9999-12-31T23:59:59-00:01`) lèvent `ValueError`, jamais
  `OverflowError` ; B1 ne détecte aucune source legacy (B3) et n'émet jamais FRESH ni « exposé ».
- **Campagne finale (2026-10-14, octets ci-dessous)** : tests B1 **142 PASS** ; E3-A + B1 : 487 PASS ; **suite complète : 4 256 PASS, 5 SKIP,
  0 FAIL** (4 114 + 142), 733 s. Les 5 SKIP sont les limitations Windows déjà connues (fsync de répertoire POSIX, liens symboliques
  sans privilège, FIFO POSIX) ; aucun SKIP n'a été converti en PASS. SHA-256 des fichiers testés : `gate_v_exposure_sources.py`
  `2c39af57cbddc5d45f873347ace781fd470a84413afb760fb7d8a7c8c7928197` ; `tests/test_gate_v_exposure_sources.py`
  `c709ee7722253234dcf69bd747627120615eed7f32a6098ef728efc53d22c821`.
- **Différentiel E3-A/B1** : 30 000 fenêtres valides à graine fixe (verdicts équilibrés : 19 514 recoupements, 10 486 non-recoupements) sans
  aucun écart avec `_windows_overlap` d'E3-A ; le sous-agent indépendant a obtenu 0 écart sur 35 000 fenêtres avec décalages
  jusqu'à ±23:59. Le différentiel du fichier de tests (4 × 400 fenêtres au format `Z`) est plus petit ; les décalages sont couverts par
  des tests d'invariance séparés. Il n'utilise que des fenêtres valides.
- **Contrôle de mutation** (copies hors dépôt) : 18 mutants du jeu de la mission, 18 tués ; le sous-agent final a appliqué 26 mutants
  distincts : 25 tués, 1 survivant (`isinstance` à la place de `type(...) is`), tué ensuite par un test ajouté.
- **Revues indépendantes** : deux revues en lecture seule, **zéro BLOCKER, zéro MAJOR** dans les deux cas. Revue finale : trois MINOR de
  qualité de tests (priorité de type non testée avec une sous-classe de `str` ; paramètre mort dans un test ; commentaire
  contradictoire), tous corrigés (RED prouvé par le mutant, puis test ajouté). INFO non traités : pas de `__all__` (non exigé),
  double validation de type dans `windows_overlap` (redondante, inoffensive), `=1.12.0` à ne pas commiter.
- **Risques résiduels** : B1 ne détecte aucune source legacy inclusive (B3) ; le comportement fail-closed aux bornes `0001`/`9999` est
  volontaire et testé, mais B3 devra décider quoi faire d'une source dont la fin inclusive est à `9999-12-31T23:59:59.999999Z` (la
  traiter comme `UNRESOLVED`, jamais tronquer) ; le module expose les noms importés (`OverlapVerdict`, etc.) faute de `__all__` ; les
  noms B1 ne figurent que dans le design (§44), pas dans l'ADR (précision ADR [R] possible avec B3).
- **Statut de publication** : E3-B1 est implémenté et testé localement ; il n'est **pas publié**. B2 à B6 : NOT IMPLEMENTED.
  `REAL` = DISABLED, NOT QUALIFIED. `GATE V` = NON PASSÉE. Aucun champion qualifié.

**Dépendances inchangées** : B6 (publication des déclarations et attestations) dépend de la primitive par lien d'E3-C ; la lecture et la
vérification de B6 n'en dépendent pas. Questions ouvertes non tranchées : Q-0, Q-2, Q-3, Q-4, Q-5.

**Sept observations MINOR de la revue de publication (non corrigées : la mission de publication interdisait toute modification)**
1. 23.29.5 dit « en `REAL` elle conditionne l'admission », plus affirmatif que la « cible provisoire (Q-5) » → précision ADR [R] avec
   Q-5 (E3-J).
2. Le §45 cite « les choix présentés dans le rapport de conception » → le §44.1 en est la trace durable ; aucune action.
3. Le report cumulatif ne dit pas si la première déclaration d'une chaîne peut contenir des expositions **en plus** (⊇ ou égalité), ni
   l'ordre canonique des reports et l'affectation de `<pos4>` ; les anciens identifiants ne sont pas conservés (traçabilité d'audit) →
   précision ADR [R] avant **B6**.
4. L'enveloppe persistée n'est pas entièrement énumérée (nom de la clé de version, projection des expositions imbriquées) ;
   `_declaration_record` est privé à E3-A, donc E3-B devra en dupliquer la projection avec un test d'égalité avec
   `compute_declaration_id` → **B6**.
5. Rien n'impose que la publication d'une déclaration vise l'`inventory_id` courant, et « un A0 existe avant la première déclaration »
   n'est vérifiable que par existence → **B5/B6**.
6. Après l'`ADMISSION`, seul « le changement de chaîne terminale » est cité alors qu'ajouter une déclaration à la même chaîne
   terminale change le sommet et annule l'exécution à l'étape 13 de 23.17 (implicite) → test **E3-J** et précision ADR [R].
7. Le retour à un ancien `inventory_id` rend la campagne définitivement inutilisable (échec fermé, explicite) sans être qualifié
   « coût de disponibilité accepté » → précision ADR [R], comme en 23.27.5.

**Précautions inchangées** : trois modifications indexées préexistantes (`AGENTS.md`, ADR 0016, `docs/agents/skills-usage.md`, empreinte
du diff indexé `8b78a333b37710b5987d1e535c8487e797984df193dc80362efd946ed9670e6f`) et le fichier non suivi `=1.12.0` ne font pas partie
de cette série ; `app_corrupted_backup.py` n'est jamais modifié.
