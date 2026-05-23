# Backtest NASDAQ — Revolution 3Mn

Environnement de backtesting sur l'indice US100 (NASDAQ) en timeframe M3 (3 minutes), via MetaTrader 5 avec le broker Admirals.

## Structure du projet

```
Backtest Nasdaq revolution 3Mn/
├── .venv/                  # Environnement virtuel Python (ne pas versionner)
├── requirements.txt        # Dépendances exactes du projet
└── README.md               # Ce fichier
```

## Configuration

| Paramètre   | Valeur        |
|-------------|---------------|
| Plateforme  | MetaTrader 5  |
| Broker      | Admirals (démo) |
| Symbole     | US100         |
| Timeframe   | M3 (3 minutes) |

## Installation

```bash
# Créer et activer l'environnement virtuel
python -m venv .venv
.\.venv\Scripts\activate

# Installer les dépendances
pip install -r requirements.txt
```

## Dépendances principales

| Bibliothèque  | Usage                                      |
|---------------|--------------------------------------------|
| MetaTrader5   | Connexion MT5, récupération des données    |
| pandas        | Manipulation des séries temporelles        |
| numpy         | Calculs numériques                         |
| pandas-ta     | Indicateurs techniques (RSI, EMA, MACD…)  |
| matplotlib    | Visualisation des résultats                |
| openpyxl      | Export des résultats en Excel              |

## Utilisation rapide

```python
import MetaTrader5 as mt5
import pandas as pd

# Connexion au terminal MT5 (doit être ouvert)
mt5.initialize()

# Récupération des bougies M3 sur US100
rates = mt5.copy_rates_from_pos("US100", mt5.TIMEFRAME_M3, 0, 1000)
df = pd.DataFrame(rates)
df['time'] = pd.to_datetime(df['time'], unit='s')

mt5.shutdown()
```
