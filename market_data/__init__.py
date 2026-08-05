"""
market_data — Socle du futur "Data Center" (Phase 1, voir docs/adr/0002-...).

Ce package ne modifie ni n'appelle aucun des modules existants du moteur de backtest
(`engine.py`, `app.py`). Il définit uniquement :

- `market_data.schema`   : le schéma canonique interne minimal (colonnes OHLCV).
- `market_data.ports`    : l'interface `MarketDataSource` (port, au sens hexagonal).
- `market_data.adapters` : les implémentations concrètes du port (aujourd'hui : CSV local).

Rien ici n'est encore branché dans le reste de l'application.
"""
