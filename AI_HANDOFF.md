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
| `path_resolver.py`       | Résout `BASE_DIR` (local vs serveur via `BACKTEST_BASE_DIR`)         |
| `strategies/perfect_revolution_v1.py` | Stratégie principale avec ses paramètres                |

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
- Aucun gros CSV n'a été déplacé automatiquement.
- `.gitignore` ignore `data/**/*.csv`; seul le squelette vide avec `.gitkeep` peut être versionné.
- MT5 n'est pas encore branché.

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
- **`BACKTEST_BASE_DIR`** : variable d'environnement pour déploiement serveur (Linux). La fonction `_base_dir()` dans `optimization_store.py` la gère.
- **Données multi-actifs** : préférer `data/{ASSET}/{TIMEFRAME}/*.csv`; garder `nasdaq_3m.csv` comme fallback legacy pour `NASDAQ/M3`.

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
- [x] Reconnexion Streamlit durcie : les vieux jobs `created` ou avec `stop.flag` ne sont plus considérés comme actifs
- [x] UX benchmark : l'onglet Progression affiche un état dédié pendant `benchmarking` au lieu d'un trompeur `0/0`
- [x] UX débutant : Progression/Résultats/Historique utilisent des statuts lisibles, verdicts simples et messages explicatifs
- [x] UX progression : auto-actualisation sûre toutes les ~2,5 s pendant `created`, `benchmarking` et `running`
- [x] UX Historique/Résultats : cartes jobs rendues avec composants Streamlit natifs, mode rapide affiché comme test technique, top résultats simplifié sans table filtrée répétitive
- [x] Mode validation rapide : la limite 12 combinaisons est maintenant appliquée à l'exécution via `max_combinations`, pas seulement à l'affichage
- [x] Windows : `progress.json` garde l'écriture atomique avec retry court sur `PermissionError` / `WinError 5`
- [x] Historique Runs : le bouton `Voir` charge le job, force l'onglet `Résultats` et ne nécessite plus de second clic
- [x] Validation Playwright Edge : job rapide `job_20260614_190837_032a` terminé, 12/12 combinaisons, pas de `WinError`, téléchargements visibles
- [x] Données multi-actifs/timeframes : squelette `data/NASDAQ/M3/`, résolution CSV via `path_resolver.py`, fallback legacy `nasdaq_3m.csv`
- [x] Tests validés : 12 combos / 1 worker et 42 combos / 2 workers → 7/7 fichiers présents
- [x] Dépôt GitHub créé (privé) : https://github.com/crashboom34/backtest-nasdaq-revolution

### Reste à faire (prochaines étapes suggérées)

- [ ] Tester manuellement le lancement complet depuis Streamlit avec le nouveau système de jobs
- [ ] Documenter la source / format exact de `nasdaq_3m.csv`
- [ ] Brancher plus tard MT5 ou une autre source d'import vers `data/{ASSET}/{TIMEFRAME}/`
- [ ] Éventuellement : déploiement serveur Linux avec `BACKTEST_BASE_DIR`

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

---

## 11. Mode validation rapide (PC lent)

Le toggle **"⚡ Mode validation rapide (PC lent)"** dans Streamlit applique automatiquement :

| Paramètre           | Valeur mode rapide | Valeur mode complet |
|---------------------|--------------------|---------------------|
| `max_rows`          | 20 000 lignes      | None (tout l'historique) |
| `benchmark_n_sample`| 1                  | 5 (défaut selectbox) |
| `n_workers`         | 1                  | auto (cpu_count)     |
| `max_combinations`  | 12 combinaisons réellement exécutées | None / illimité |

**Important** : les résultats obtenus en mode rapide ne sont **pas représentatifs** d'une vraie optimisation. Ce mode sert uniquement à vérifier que le pipeline fonctionne (benchmark → running → fichiers générés).

Quand `max_rows = None` et `quick_mode = False`, un `st.warning()` orange s'affiche dans l'expander "Période d'optimisation" pour alerter l'utilisateur.

Dernière validation automatisée :

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
