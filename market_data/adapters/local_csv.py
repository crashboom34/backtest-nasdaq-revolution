"""
market_data/adapters/local_csv.py — Adaptateur MarketDataSource pour les CSV locaux existants.

Réutilise `path_resolver.py` (résolution de data/{ASSET}/{TIMEFRAME}/, fallback legacy
nasdaq_3m.csv) sans dupliquer sa logique de résolution de chemin. N'importe et ne modifie aucun
fichier existant du dépôt.

Ce module ne fait aucune connexion réseau : il lit uniquement des fichiers déjà présents en
local, exactement comme le fait aujourd'hui l'onglet Streamlit "Données".
"""

from __future__ import annotations

import pandas as pd

import path_resolver
from market_data.schema import (
    CANONICAL_COLUMNS,
    MarketDataResult,
    MarketDatasetInfo,
    validate_canonical_columns,
)


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

        try:
            df = pd.read_csv(resolution.path, parse_dates=["time"])
        except Exception as exc:
            message = f"CSV illisible ({resolution.relative_path}) : {exc}"
            return MarketDataResult(info=info, dataframe=None, ok=False, message=message)

        missing = validate_canonical_columns(df)
        if missing:
            message = (
                f"Colonnes canoniques manquantes dans {resolution.relative_path} : "
                + ", ".join(missing)
                + "."
            )
            return MarketDataResult(info=info, dataframe=None, ok=False, message=message)

        df = df.copy()
        if "volume" not in df.columns:
            df["volume"] = pd.NA

        ordered_cols = [c for c in CANONICAL_COLUMNS if c in df.columns]
        df = df[ordered_cols]

        return MarketDataResult(info=info, dataframe=df, ok=True, message="OK")

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
