"""
market_data/unified_catalog.py — Vue combinée du catalogue local CSV + EODHD (Data Center).

Combine market_data.catalog.build_catalog() (CSV locaux, via un MarketDataSource, ex.
LocalCsvMarketDataSource) et market_data.eodhd.storage.list_normalized_snapshots() (snapshots
EODHD déjà téléchargés localement) en une liste unique de lignes comparables.

Lecture seule : ne modifie rien, ne télécharge rien, ne recalcule rien — assemble uniquement ce
que market_data.catalog et market_data.eodhd.storage savent déjà produire séparément. Chaque
source est optionnelle : omise (None), elle est simplement ignorée, jamais une erreur.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union


@dataclass(frozen=True)
class UnifiedCatalogRow:
    """Une ligne du catalogue unifié, indépendante du fournisseur d'origine."""

    provider: str
    asset: str
    timeframe: str
    exists: bool
    row_count: Optional[int]
    start: Optional[str]
    end: Optional[str]
    quality_score_pct: Optional[float]
    extra: str  # info complémentaire (symbole fournisseur, chemin relatif...)


def build_unified_catalog(
    local_source=None,
    eodhd_data_dir: Optional[Union[str, Path]] = None,
) -> list:
    """Combine catalogue CSV local + snapshots EODHD normalisés.

    `local_source` : une instance MarketDataSource (ex. LocalCsvMarketDataSource()), ou None
    pour ignorer les CSV locaux.
    `eodhd_data_dir` : le dossier BACKTEST_DATA_DIR déjà résolu, ou None pour ignorer EODHD.
    """
    rows: list = []

    if local_source is not None:
        from market_data.catalog import build_catalog

        for entry in build_catalog(local_source, compute_stats=True):
            rows.append(
                UnifiedCatalogRow(
                    provider="local_csv",
                    asset=entry.asset,
                    timeframe=entry.timeframe,
                    exists=entry.exists,
                    row_count=entry.row_count,
                    start=entry.start,
                    end=entry.end,
                    quality_score_pct=None,
                    extra=entry.relative_path or "",
                )
            )

    if eodhd_data_dir is not None:
        from market_data.eodhd.storage import list_normalized_snapshots

        for snapshot in list_normalized_snapshots(eodhd_data_dir):
            rows.append(
                UnifiedCatalogRow(
                    provider="eodhd",
                    asset=snapshot.asset,
                    timeframe=snapshot.timeframe,
                    exists=True,
                    row_count=snapshot.row_count,
                    start=snapshot.start,
                    end=snapshot.end,
                    quality_score_pct=snapshot.quality_score_pct,
                    extra=snapshot.ticker,
                )
            )

    return rows
