# Backtest NASDAQ — Revolution 3Mn

Plateforme de backtesting et d'optimisation de stratégies de trading sur l'indice US100 (NASDAQ), timeframe M3 (3 minutes).

Interface web Streamlit + optimiseur parallèle en ligne de commande.

---

## Ce que fait le projet

- Charge un historique de prix NASDAQ en CSV (`nasdaq_3m.csv`)
- Exécute une stratégie de trading paramétrable (`strategies/perfect_revolution_v1.py`)
- Optimise les paramètres par force brute sur toutes les combinaisons possibles
- Affiche les résultats dans une interface Streamlit (graphiques, tableau des meilleures stratégies, rapport HTML)
- Génère un dossier de résultats par job : `results/job_YYYYMMDD_HHMMSS_xxxx/`

---

## Prérequis

- Python 3.10+ (testé avec 3.13)
- Windows (interface graphique) ou Linux/Mac (ligne de commande)
- Fichier `nasdaq_3m.csv` à placer à la racine du projet (non versionné)

---

## Installation

```bash
# 1. Cloner le projet
git clone https://github.com/crashboom34/backtest-nasdaq-revolution.git
cd backtest-nasdaq-revolution

# 2. Créer l'environnement virtuel
python -m venv .venv

# 3. Activer l'environnement
# Windows :
.\.venv\Scripts\activate
# Linux/Mac :
source .venv/bin/activate

# 4. Installer les dépendances
# Windows :
pip install -r requirements.txt
# Serveur Linux :
pip install -r requirements-server.txt
```

---

## Données requises

Le fichier `nasdaq_3m.csv` est nécessaire pour faire tourner le backtest. Il n'est **pas inclus** dans le dépôt Git (fichier volumineux).

Il doit contenir au minimum les colonnes : `time`, `open`, `high`, `low`, `close`, `volume` au format CSV.

Placez-le à la racine du projet avant de lancer l'application.

---

## Lancement

### Interface Streamlit (recommandé)

Double-cliquez sur `lancer_app.bat` ou lancez :

```bash
.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501
```

Ouvre automatiquement [http://localhost:8501](http://localhost:8501)

### Ligne de commande (sans interface)

```bash
# Lancer un job avec un fichier de configuration JSON
.venv\Scripts\python.exe run_job.py --config optimization_history/mon_run.config.json

# Options disponibles
.venv\Scripts\python.exe run_job.py --config mon_run.config.json --workers 4 --max-rows 50000
```

---

## Structure du projet

```
Backtest Nasdaq revolution 3Mn/
├── app.py                      # Interface Streamlit principale
├── run_job.py                  # Lanceur CLI (sans interface)
├── optimizer_process.py        # Moteur d'optimisation (subprocess)
├── optimizer.py                # Logique d'optimisation
├── engine.py                   # Moteur de backtest
├── scoring.py                  # Calcul du score / KPI
├── optimization_store.py       # Lecture/écriture des runs
├── job_store.py                # Génération des artefacts de job
├── path_resolver.py            # Résolution des chemins
├── strategies/
│   └── perfect_revolution_v1.py   # Stratégie principale
├── market_data/                 # Socle du futur Data Center (schéma, catalogue, resampling — voir AI_HANDOFF.md)
├── lancer_app.bat              # Démarrage Windows (double-clic)
├── requirements.txt            # Dépendances Windows
├── requirements-server.txt     # Dépendances Linux/serveur
├── nasdaq_3m.csv               # [NON VERSIONNÉ] Données de prix
├── optimization_history/       # [NON VERSIONNÉ] Runs Streamlit
├── results/                    # [NON VERSIONNÉ] Jobs CLI (dossier par job)
└── history/                    # [NON VERSIONNÉ] Cache DataFrame
```

---

## Dossiers générés localement (non versionnés)

| Dossier / Fichier         | Contenu                                      |
|---------------------------|----------------------------------------------|
| `optimization_history/`   | Configs et résultats des runs Streamlit      |
| `results/job_xxx/`        | Artefacts complets par job CLI               |
| `history/`                | Cache DataFrame compressé (.pkl.gz)          |
| `nasdaq_3m.csv`           | Données de prix (à fournir manuellement)     |

---

## Dépendances principales

| Bibliothèque  | Usage                                      |
|---------------|--------------------------------------------|
| streamlit     | Interface web                              |
| pandas        | Manipulation des données                   |
| numpy         | Calculs numériques                         |
| pandas-ta     | Indicateurs techniques (RSI, EMA, etc.)    |
| plotly        | Graphiques interactifs                     |
| colorama      | Couleurs terminal                          |

---

## Reprendre le projet proprement

1. Cloner le dépôt Git
2. Créer et activer le `.venv`
3. `pip install -r requirements.txt`
4. Placer `nasdaq_3m.csv` à la racine
5. Double-cliquer sur `lancer_app.bat`
6. Lire `AI_HANDOFF.md` pour le contexte technique complet

---

## Liens

- Dépôt GitHub : [crashboom34/backtest-nasdaq-revolution](https://github.com/crashboom34/backtest-nasdaq-revolution)
