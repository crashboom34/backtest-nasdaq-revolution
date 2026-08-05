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
| `market_data/provider_config.py` | Emplacement générique des futures clés API fournisseurs (jamais versionné) |
| `market_data/summary.py` | Assemble catalogue + statut timeframes + qualité (fondation future page Data Center) |

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

Prochaine étape restante : Phase 2 — un vrai connecteur EODHD (ou autre fournisseur), qui
nécessite une clé API réelle et une vérification de la documentation officielle du fournisseur
avant d'écrire le moindre appel réseau (voir la contrainte disque ci-dessous).

**Point d'attention disque** : ≈3,0 Go libres sur C: au début de la session du 2026-08-05,
≈6,3 Go plus tard dans la même session (espace libéré entre-temps, en dehors de ce projet).
Avant toute Phase 2/3 (téléchargement réel de données), vérifier l'espace disponible au moment
voulu et prévoir, si besoin, de stocker les données de marché sur un autre disque.

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

### Reste à faire (prochaines étapes suggérées)

- [ ] Tester manuellement le lancement complet depuis Streamlit avec le nouveau système de jobs
- [ ] Documenter la source / format exact de `nasdaq_3m.csv`
- [ ] Brancher plus tard MT5 ou une autre source d'import vers `data/{ASSET}/{TIMEFRAME}/`
- [ ] Ajouter plus tard une gestion avancée des formats CSV exotiques si nécessaire (fuseaux horaires spécifiques, colonnes renommées non standards)
- [ ] Éventuellement : déploiement serveur Linux avec `BACKTEST_BASE_DIR`
- [ ] Data Center : faire réellement passer `run_job.py`/le lancement d'optimisation par `engine.load_data_from_source()` (actuellement disponible mais pas utilisé par le chemin réel de backtest — décision à prendre explicitement, pas automatique)
- [ ] Data Center Phase 2 : premier vrai connecteur fournisseur (EODHD ou autre) — **bloqué en attente d'une clé API réelle et de la documentation officielle du fournisseur**, fournies par l'utilisateur ; aucun connecteur ne doit être écrit sur la base d'endpoints devinés
- [ ] Data Center Phase 2 : valider le budget de téléchargement face à l'espace disque disponible avant tout premier téléchargement réel
- [ ] Décider si Playwright (installé localement dans `.venv` pour la validation du 2026-08-05) doit devenir une dépendance permanente (`requirements.txt`) avec une suite de tests UI récurrente

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
