"""
market_data/eodhd/adapter.py — Adaptateur MarketDataSource pour les snapshots EODHD normalisés.

Implémente le port market_data.ports.MarketDataSource (voir ADR 0002) en relisant les snapshots
déjà téléchargés et normalisés localement sous BACKTEST_DATA_DIR (voir storage.py). Comme
market_data.adapters.local_csv.LocalCsvMarketDataSource, list_available()/load() sont purement
en lecture : AUCUN téléchargement ni appel réseau n'est déclenché ici. Pour obtenir de nouvelles
données EODHD, il faut appeler EodhdClient explicitement (voir client.py) puis
storage.save_normalized() — cet adaptateur sert uniquement à relire ce qui existe déjà,
exactement comme engine.load_data_from_source() sait déjà lire un CSV local.

C'est la pièce manquante de la "façade de compatibilité" (Phase 11, CLAUDE.md) : engine.py ne
dépend que du port MarketDataSource, jamais d'EODHD directement — cet adaptateur permet de
brancher des données EODHD derrière la même façade que les CSV locaux, sans qu'engine.py en ait
la moindre connaissance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd

from market_data.schema import (
    CANONICAL_COLUMNS,
    MarketDataResult,
    MarketDatasetInfo,
    validate_canonical_columns,
)

from .errors import EodhdConfigError
from .storage import list_normalized_snapshots, normalized_snapshot_path, resolve_data_dir


class EodhdMarketDataSource:
    """Adaptateur MarketDataSource pour les snapshots EODHD normalisés déjà stockés localement.

    `data_dir` est optionnel : si absent, résolu depuis BACKTEST_DATA_DIR à chaque appel (comme
    le reste du connecteur EODHD). Le passer explicitement est surtout utile pour les tests.
    """

    provider = "eodhd"

    def __init__(self, data_dir: Optional[Union[str, Path]] = None):
        self._data_dir_override = Path(data_dir) if data_dir is not None else None

    def _resolve_data_dir(self) -> Path:
        if self._data_dir_override is not None:
            return self._data_dir_override
        return resolve_data_dir()

    def list_available(self) -> list:
        try:
            data_dir = self._resolve_data_dir()
        except EodhdConfigError:
            return []

        return [
            MarketDatasetInfo(
                provider="eodhd",
                asset=snapshot.asset,
                timeframe=snapshot.timeframe,
                source="eodhd_normalized",
                exists=True,
                relative_path=None,
                message=f"Snapshot EODHD {snapshot.ticker} synchronisé le {snapshot.synced_at}.",
            )
            for snapshot in list_normalized_snapshots(data_dir)
        ]

    def load(self, asset: str, timeframe: str) -> MarketDataResult:
        try:
            data_dir = self._resolve_data_dir()
        except EodhdConfigError as exc:
            info = MarketDatasetInfo(
                provider="eodhd", asset=asset, timeframe=timeframe, source="missing",
                exists=False, message=str(exc),
            )
            return MarketDataResult(info=info, dataframe=None, ok=False, message=str(exc))

        matches = [
            s for s in list_normalized_snapshots(data_dir) if s.asset == asset and s.timeframe == timeframe
        ]
        if not matches:
            message = f"Aucun snapshot EODHD normalisé trouvé localement pour {asset}/{timeframe}."
            info = MarketDatasetInfo(
                provider="eodhd", asset=asset, timeframe=timeframe, source="missing",
                exists=False, message=message,
            )
            return MarketDataResult(info=info, dataframe=None, ok=False, message=message)

        # Le plus récent en cas de plusieurs snapshots (ex. deux téléchargements successifs).
        latest = max(matches, key=lambda s: s.synced_at)
        path = normalized_snapshot_path(data_dir, latest)

        try:
            df = pd.read_parquet(path)
        except Exception as exc:
            message = f"Snapshot EODHD illisible ({path}) : {exc}"
            info = MarketDatasetInfo(
                provider="eodhd", asset=asset, timeframe=timeframe, source="eodhd_normalized",
                exists=True, message=message,
            )
            return MarketDataResult(info=info, dataframe=None, ok=False, message=message)

        missing = validate_canonical_columns(df)
        if missing:
            message = f"Colonnes canoniques manquantes dans le snapshot EODHD : {', '.join(missing)}."
            info = MarketDatasetInfo(
                provider="eodhd", asset=asset, timeframe=timeframe, source="eodhd_normalized",
                exists=True, message=message,
            )
            return MarketDataResult(info=info, dataframe=None, ok=False, message=message)

        ordered_cols = [c for c in CANONICAL_COLUMNS if c in df.columns]
        df = df[ordered_cols]
        info = MarketDatasetInfo(
            provider="eodhd", asset=asset, timeframe=timeframe, source="eodhd_normalized",
            exists=True, relative_path=str(path), message="OK",
        )
        return MarketDataResult(info=info, dataframe=df, ok=True, message="OK")
