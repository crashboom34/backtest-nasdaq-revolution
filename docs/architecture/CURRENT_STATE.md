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
| Reprise après interruption/crash | Mécanisme moteur : **implémenté et testé réellement (2026-08-07, reconfirmé sous Linux OCI le 2026-08-14)** — exposition utilisateur : **toujours absente** | `resume_run_id` + `tested.json` existent au niveau moteur (`optimizer.py`/`optimizer_process.py`). > **Note historique (2026-08-06)** : à l'audit initial, le mécanisme était présent mais jamais testé en conditions réelles du pipeline job-directory. > **État factuel actuel (2026-08-14)** : le bug de résolution du dossier source (`optimization_store.resolve_sibling_job_dir()`) a été corrigé et testé le 2026-08-07 (`tests/test_job_resume.py`, 11 tests), puis **reconfirmé en conditions réelles sous Linux OCI** le 2026-08-14 (subprocess réel, dans la suite 546/546 — voir `LINUX_PORTABILITY_REPORT.md` §15). Ce qui reste vrai sans changement : **aucune UI ni CLI n'expose `resume_run_id`** à l'utilisateur aujourd'hui — le mécanisme fonctionne, mais reste inaccessible en pratique. Aucun suivi de PID, aucun watchdog. |
| Concurrence | Implémenté et validé (contrainte forte) | **Un seul job actif à la fois**, verrouillé explicitement par `job_launcher.assert_no_active_jobs()` — décision d'architecture actuelle à confronter à la cible multi-workers. |
| Queue externe | Absent | Aucune trace de Redis/Celery/RQ dans le dépôt. |

## 2. Interface (`app.py`)

**Fait vérifié** : `app.py` fait **6 416 lignes**, **126 fonctions top-level**, 7 onglets
principaux (Accueil, Backtest manuel, Historique manuel, Nouvelle stratégie, Données, Maintenance,
Optimisation), l'onglet Optimisation contenant lui-même **10 sous-onglets**. Mélange rendu
Streamlit, appel direct du moteur, orchestration de subprocess, lecture/écriture disque, logique
de décision Champion. Dette technique majeure confirmée et chiffrée (voir ADR 0010).

> **Note historique (2026-08-06)** : `.streamlit/config.toml` avait `headless = false` — signalé
> comme à corriger pour un déploiement serveur sans affichage.
>
> **État factuel actuel (2026-08-14)** : corrigé le 2026-08-07 (`headless = true` par défaut ;
> `lancer_app.bat` passe désormais `--server.headless false` explicitement pour préserver
> l'ouverture automatique du navigateur en usage local Windows). **Validé réellement sous Linux
> OCI** le 2026-08-14 : `lancer_app.sh` exécuté via `./lancer_app.sh` (mode Git `100755`),
> Streamlit démarré réellement en mode headless, HTTP 200 confirmé sur `/_stcore/health` et sur
> `/`, arrêt propre — voir `LINUX_PORTABILITY_REPORT.md` §15.

## 3. Portabilité Linux

> **Note historique (2026-08-06)** : ce qui suit est un **audit statique** — aucune exécution
> Linux réelle n'avait encore eu lieu à cette date (Docker/WSL2/CI indisponibles sur le poste de
> développement).
>
> **État factuel actuel (2026-08-14)** : la validation Linux réelle a depuis eu lieu sur une
> instance OCI (`backtester-ph0-oci-01`, Ubuntu 24.04.4 LTS x86_64, glibc 2.39) — dépendances de
> `requirements-server.txt` installées réellement (51 paquets, aucune compilation), suite pytest
> **546/546 passed** avec les vraies données, `lancer_app.sh`/Streamlit headless validés
> réellement, backtest complet (`NASDAQ Perfect Revolution V1.1`) **IDENTIQUE** entre Windows et
> OCI. Détail complet : `LINUX_PORTABILITY_REPORT.md` §15. Ticket `PH0-OCI-01` :
> **clôturé** (`docs/roadmap/EPICS_AND_TICKETS.md`).

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
| Provenance (snapshot_id/content_hash/période) — chemin CSV local | **Implémenté et validé (`GATE DATA = PASS`, 2026-08-15)** | `job_store.write_data_manifest()` relie désormais `content_hash` (SHA-256 réel, `market_data/content_hash.py`), `snapshot_id` (`"local_csv:sha256:<hash>"`) et `period_start`/`period_end` réels pour chaque nouveau job CSV local — voir `EPICS_AND_TICKETS.md` §10, `AF-DATA-01`→`AF-DATA-04A`. **Note historique — état au 2026-08-06/07** : ce champ était vide dans 100 % des manifestes à l'époque de cet audit ; cette limitation est levée pour les nouveaux jobs (les anciens manifestes restent lisibles avec `content_hash=None`, jamais réécrits). Chemin EODHD (`storage.SnapshotManifest`) reste séparé, non unifié — ADR 0008. |
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
- **52 fichiers `test_*.py`** dans `tests/` (54 fichiers `.py` au total avec `__init__.py` et
  `conftest.py` — recompté le 2026-08-14 ; +1 test par rapport à l'audit du 2026-08-06,
  `tests/test_job_resume.py`, ajouté lors de la correction du bug de reprise, voir §1),
  majoritairement `market_data`/EODHD/IG (~25), jobs/Champion/retest (~13),
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
