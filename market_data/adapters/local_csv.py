"""
market_data/adapters/local_csv.py — Adaptateur MarketDataSource pour les CSV locaux existants.

Réutilise `path_resolver.py` (résolution de data/{ASSET}/{TIMEFRAME}/, fallback legacy
nasdaq_3m.csv) sans dupliquer sa logique de résolution de chemin. N'importe et ne modifie aucun
fichier existant du dépôt.

Ce module ne fait aucune connexion réseau : il lit uniquement des fichiers déjà présents en
local, exactement comme le fait aujourd'hui l'onglet Streamlit "Données".
"""

from __future__ import annotations

import path_resolver
from market_data.csv_reading import read_canonical_csv
from market_data.schema import MarketDataResult, MarketDatasetInfo


class LocalCsvMarketDataSource:
    """Premier adaptateur concret du port MarketDataSource : les CSV gérés par path_resolver."""

    provider = "local_csv"

    def list_available(self) -> list[MarketDatasetInfo]:
        infos: list[MarketDatasetInfo] = []
        for asset in path_resolver.list_available_assets():
            for timeframe in path_resolver.list_available_timeframes(asset):
                resolution = path_resolver.resolve_data_csv(asset, timeframe)
                infos.append(self._info_from_resolution(resolution))
        return infos

    def load(self, asset: str, timeframe: str) -> MarketDataResult:
        resolution = path_resolver.resolve_data_csv(asset, timeframe)
        info = self._info_from_resolution(resolution)

        if not resolution.exists:
            return MarketDataResult(info=info, dataframe=None, ok=False, message=resolution.message)

        outcome = read_canonical_csv(resolution.path)
        if not outcome.ok:
            # Même message que l'ancienne implémentation inline, juste reformaté via le chemin
            # relatif (plus lisible pour l'utilisateur) plutôt que le chemin absolu du helper.
            message = outcome.message.replace(str(resolution.path), resolution.relative_path)
            return MarketDataResult(info=info, dataframe=None, ok=False, message=message)

        return MarketDataResult(info=info, dataframe=outcome.dataframe, ok=True, message="OK")

    @staticmethod
    def _info_from_resolution(resolution: "path_resolver.DataFileResolution") -> MarketDatasetInfo:
        return MarketDatasetInfo(
            provider="local_csv",
            asset=resolution.asset,
            timeframe=resolution.timeframe,
            source=resolution.source,
            exists=resolution.exists,
            relative_path=resolution.relative_path if resolution.exists else None,
            message=resolution.message,
        )
