"""
market_data/ports.py — Port (interface) MarketDataSource.

Un "port", au sens architecture hexagonale : une interface stable que le moteur de backtest
(et plus tard le catalogue, l'UI Data Center...) pourra utiliser sans connaître le fournisseur
concret derrière. Aujourd'hui, un seul adaptateur existe :
`market_data.adapters.local_csv.LocalCsvMarketDataSource`.

Rien n'est branché sur app.py ni engine.py à cette étape — voir docs/adr/0002-... pour le
raisonnement complet et les étapes suivantes prévues.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from market_data.schema import MarketDataResult, MarketDatasetInfo


@runtime_checkable
class MarketDataSource(Protocol):
    """Interface commune que doit respecter tout adaptateur de source de données de marché."""

    def list_available(self) -> list[MarketDatasetInfo]:
        """Liste les jeux de données disponibles ou préparés pour ce fournisseur."""
        ...

    def load(self, asset: str, timeframe: str) -> MarketDataResult:
        """Charge un jeu de données normalisé (schéma canonique) pour un actif/timeframe donné."""
        ...
