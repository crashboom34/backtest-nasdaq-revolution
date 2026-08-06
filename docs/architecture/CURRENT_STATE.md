# État actuel constaté — audit du 2026-08-06

> Document factuel, issu d'un audit direct du code (pas d'hypothèse). Complète, sans les
> dupliquer, `README.md` et `AI_HANDOFF.md`. Voir `docs/INDEX.md` pour la navigation.

Libellés utilisés : **Fait vérifié** (constaté dans le code) / **Implémenté et validé** /
**Implémenté mais partiel** / **Prévu mais non branché** / **Absent** / **Code mort**.

## 1. Orchestration et jobs

| Élément | Statut | Détail |
|---|---|---|
| Backtest simple | Implémenté et validé | S'exécute **en process, de façon synchrone**, dans le thread Streamlit (`app.py` → `engine.run_backtest()` directement). Bloque le rendu pendant le calcul. |
| Optimisation | Implémenté et validé | 1 process OS par job (`subprocess.Popen` → `optimizer_process.py`), parallélisé en interne par `ProcessPoolExecutor` (`optimizer.py`). Chemin unique, réutilisé identiquement par l'UI (`job_launcher.py`) et la CLI (`run_job.py`). |
| Contrat du job directory | Implémenté et validé | `results/job_xxx/` : `progress.json`, `config_used.json`, `results.csv`, `tested.json`, `meta.json`, `stop.flag`, `metrics.json`, `best_strategies.csv`, `report.html`, `logs.txt`, `archive.zip` (7 fichiers précis), `data_manifest.json` (additif). Écrivains précis identifiés dans `optimization_store.py`/`job_store.py`/`job_artifacts.py`. **À préserver intégralement.** |
| Survie à la fermeture du navigateur | Implémenté et validé | L'état des jobs actifs est reconstruit **depuis le disque** (mtime des fichiers), pas depuis `st.session_state` — une page rechargée retrouve le job en cours. |
| Survie à la fermeture du process serveur | Non prouvé | Aucun hook de cycle de vie n'attache le subprocess à la session Streamlit ; comportement dépendant du défaut OS, non testé explicitement dans le dépôt. |
| Reprise après interruption/crash | Prévu mais non branché | `resume_run_id` + `tested.json` existent au niveau moteur (`optimizer.py`/`optimizer_process.py`) mais **ne sont jamais assignés ni exposés** par l'UI/CLI. Aucun suivi de PID, aucun watchdog. |
| Concurrence | Implémenté et validé (contrainte forte) | **Un seul job actif à la fois**, verrouillé explicitement par `job_launcher.assert_no_active_jobs()` — décision d'architecture actuelle à confronter à la cible multi-workers. |
| Queue externe | Absent | Aucune trace de Redis/Celery/RQ dans le dépôt. |

## 2. Interface (`app.py`)

**Fait vérifié** : `app.py` fait **6 416 lignes**, **126 fonctions top-level**, 7 onglets
principaux (Accueil, Backtest manuel, Historique manuel, Nouvelle stratégie, Données, Maintenance,
Optimisation), l'onglet Optimisation contenant lui-même **10 sous-onglets**. Mélange rendu
Streamlit, appel direct du moteur, orchestration de subprocess, lecture/écriture disque, logique
de décision Champion. Dette technique majeure confirmée et chiffrée (voir ADR 0010).

`.streamlit/config.toml` a `headless = false` — à corriger pour un déploiement serveur sans
affichage.

## 3. Portabilité Linux

**Meilleure que redouté.** Aucune dépendance Windows dure dans `app.py`, `engine.py`,
`job_launcher.py`, `optimizer_process.py`, `path_resolver.py`. Seules dépendances Windows
identifiées :
- `get_data.py` / `check_mt5.py` : `import MetaTrader5` — scripts **autonomes, jamais importés**
  par `app.py` au runtime (confirmé par recherche exhaustive).
- `metatrader5==5.0.5735` dans `requirements.txt` (absent de `requirements-server.txt`, déjà
  préparé pour Linux).
- `.streamlit/config.toml` : `headless = false` à corriger.

`path_resolver.py` gère déjà `BACKTEST_BASE_DIR` et convertit systématiquement en chemins POSIX
relatifs dans les artefacts JSON — bonne base de portabilité déjà en place.

## 4. `market_data/` — Data Center, EODHD, IG

| Élément | Statut | Détail |
|---|---|---|
| Schéma canonique OHLCV | Implémenté et validé | ADR 0002. |
| Resampling M/H/D | Implémenté et validé | ADR 0003, ancrage UTC. |
| Resampling calendaire W1/MO1 | Implémenté et validé | ADR 0004, dérivé de D1 uniquement. |
| Calendrier de marché dans le resampling | **Absent, non branché** | `eodhd/calendar.py` existe ; `resample.py` ne l'importe jamais. Seul point de branchement (`quality.detect_missing_trading_days`) sans appelant en production. Voir ADR 0013. |
| Provenance (snapshot_id/content_hash/période) | Implémenté mais partiel — **vide dans 100 % des manifestes produits aujourd'hui** | Les champs existent dans `BacktestManifest` mais `job_store.write_data_manifest()` ne les relie jamais au vrai hash EODHD (`storage.SnapshotManifest`, lui, complet). Voir ADR 0008. |
| Téléchargement EODHD — fenêtrage | Implémenté et validé | `eodhd/windowing.py`, utilisé par `EodhdClient.download_intraday()`. |
| Téléchargement EODHD — reprise après interruption | Absent | Pas de checkpoint, échec global si une fenêtre échoue. |
| Téléchargement EODHD — quota | Implémenté mais partiel | Statut interrogé à la demande (`get_account_status`), pas de suivi cumulatif local. |
| Téléchargement EODHD — sync incrémentale | Absent | Chaque appel redemande la période complète fournie. |
| **Aucun chemin de production n'appelle réellement un téléchargement persistant EODHD** | Fait vérifié | Seuls appelants hors `market_data/`/`tests/` : `scripts/test_eodhd_connection.py` (script manuel, n'enregistre rien). |
| Dividendes / splits / titres radiés | Implémenté au niveau connecteur, non branché | `download_dividends`/`download_splits`/`list_exchange_symbols(delisted=True)` existent et fonctionnent, mais **zéro appelant de production** ; aucun ajustement de prix dans le moteur. |
| Contrôle qualité | Implémenté mais partiel | Doublons, OHLC invalide, valeurs manquantes, ordre chronologique : oui. Trous/jours fériés (calendrier) : code existant mais non branché. DST : absent. |
| Stockage | Hétérogène | Parquet **uniquement** pour le normalisé EODHD ; JSON pour le brut/manifestes EODHD ; CSV pour les sources locales et le cache de timeframes dérivés. Voir ADR 0008. |
| `catalog.py` (persistance JSON) | **Code mort en production** | `settings/data_catalog.json` n'a aucun appelant réel ; seule la construction en mémoire (`build_catalog()`) est utilisée. |
| `unified_catalog.py` | Implémenté et validé | Combine CSV local + snapshots EODHD, lecture pure, alimente l'UI. |
| IG — méthodes publiques | Implémenté et validé, lecture seule structurelle | `login/logout/test_connection/get_accounts/discover_account_id/search_markets/get_market_details/get_prices`. Aucune fonction d'écriture n'existe dans le module. |
| IG — registre de produits, historisation spreads/horaires | Absent | Aucune persistance des résultats de recherche/détails de marché IG. |
| `ui_data_center.py` | Implémenté et validé pour le branchement ; strictement lecture seule + tests de connexion pour les actions | Sous-onglet actif de l'onglet Données. Aucun bouton ne déclenche un téléchargement persistant — seules les deux fonctions `run_*_connection_test()` font un appel réseau. |

## 5. Stratégies et tests

- **Une seule stratégie** (`strategies/perfect_revolution_v1.py`), mais le système est **conçu
  pour en accueillir plusieurs** : découverte dynamique par fichiers (`glob.glob("strategies/*.py")`),
  contrat duck-typing (`reset/prepare/on_bar`), aucune liste blanche codée en dur.
- **51 fichiers `test_*.py`** dans `tests/` (53 fichiers `.py` au total avec `__init__.py` et
  `conftest.py`), majoritairement `market_data`/EODHD/IG (~25), jobs/Champion/retest (~13),
  moteur/scoring (~6), UI (~2), divers (~5).
- Deux scripts de bout en bout non collectés par pytest : `test_e2e_subprocess.py`,
  `test_e2e_parallel.py` — valident le pipeline subprocess/multiprocessing réel, exécution
  manuelle uniquement.
- `scripts/test_eodhd_connection.py`/`test_ig_connection.py` : scripts manuels de diagnostic,
  jamais exécutés par pytest.

## 6. Infrastructure

**Absent, confirmé par recherche exhaustive** : `.github/workflows/`, `Dockerfile`,
`docker-compose.yml`, config Redis, config PostgreSQL, `pytest.ini`/`pyproject.toml` racine,
fichier `backtest-secrets.ps1`. `.gitignore` protège déjà correctement `.env`/`.env.*`/
`.streamlit/credentials.toml`/les clés fournisseurs.

## 7. Documentation existante à respecter

- 4 ADR existants (`0001` à `0004`), **tous au statut Proposé** — jamais renumérotés ; prochain
  numéro utilisé dans cette mission : `0005`.
- Une spec d'architecture antérieure existe déjà :
  `docs/superpowers/specs/2026-05-19-backtest-optimizer-design.md` — décrit déjà le pattern
  `subprocess.Popen`/`ProcessPoolExecutor`, note explicitement que **walk-forward et Monte-Carlo
  sont reportés en V2** (jamais implémentés). Référencée, pas dupliquée, par
  `TEST_AND_VALIDATION_ARCHITECTURE.md`.
- `CONTEXT.md` (dernière mise à jour 2026-08-05) est légèrement en retard sur le code pour le
  terme "Calendrier de marché" (code du 2026-08-06 plus récent) — à corriger lors du branchement
  réel (ADR 0013).

## 8. Ce qui est prêt pour la suite (points positifs à ne pas re-découvrir)

- `path_resolver.py` déjà portable et paramétrable par `BACKTEST_BASE_DIR`.
- `requirements-server.txt` déjà préparé sans MetaTrader5.
- Contrat de job directory déjà stable, documenté, avec compatibilité descendante explicite.
- Port `MarketDataSource` déjà en place, adopté par `optimizer_process.py`/`optimizer.py`.
- Mécanisme de reprise (`resume_run_id`/`tested.json`) déjà écrit au niveau moteur — à brancher,
  pas à réinventer.
