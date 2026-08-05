"""
market_data/summary.py — Assemble un instantané en lecture seule du Data Center local.

Combine le catalogue (market_data.catalog), le statut des timeframes candidats et un contrôle
qualité basique (market_data.quality) en une structure unique. Pensé comme fondation d'une
future page Streamlit "Data Center" (non créée à cette étape — aucune dépendance Streamlit
ajoutée ici, aucun fichier existant modifié).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from market_data.catalog import (
    DEFAULT_CANDIDATE_TIMEFRAMES,
    CatalogEntry,
    TimeframeStatus,
    build_catalog,
    list_timeframe_status,
)
from market_data.ports import MarketDataSource
from market_data.quality import QualityReport, analyze_quality


@dataclass(frozen=True)
class DatasetSummary:
    """Instantané complet d'un jeu de données : catalogue + timeframes dérivables + qualité."""

    catalog_entry: CatalogEntry
    timeframe_statuses: tuple[TimeframeStatus, ...]
    quality: Optional[QualityReport]
    quality_error: Optional[str] = None


def build_dataset_summary(
    source: MarketDataSource,
    asset: str,
    timeframe: str,
    candidate_timeframes: tuple[str, ...] = DEFAULT_CANDIDATE_TIMEFRAMES,
) -> Optional[DatasetSummary]:
    """Construit l'instantané d'un actif/timeframe précis, ou None si absent du catalogue.

    Ne modifie rien : lecture seule sur la source, le catalogue et l'analyse qualité.
    """
    entries = build_catalog(source, compute_stats=True)
    matching = next((e for e in entries if e.asset == asset and e.timeframe == timeframe), None)
    if matching is None:
        return None
    return _summarize_entry(source, matching, candidate_timeframes)


def build_data_center_summary(
    source: MarketDataSource,
    candidate_timeframes: tuple[str, ...] = DEFAULT_CANDIDATE_TIMEFRAMES,
) -> tuple[DatasetSummary, ...]:
    """Instantané de tous les jeux de données listés par la source (actifs/timeframes connus,
    existants ou non). Ne reconstruit le catalogue qu'une seule fois, contrairement à des
    appels répétés de build_dataset_summary()."""
    entries = build_catalog(source, compute_stats=True)
    return tuple(_summarize_entry(source, entry, candidate_timeframes) for entry in entries)


def _summarize_entry(
    source: MarketDataSource,
    entry: CatalogEntry,
    candidate_timeframes: tuple[str, ...],
) -> DatasetSummary:
    statuses = tuple(
        list_timeframe_status(entry.asset, entry.timeframe, candidate_timeframes=candidate_timeframes)
    )

    quality: Optional[QualityReport] = None
    quality_error: Optional[str] = None
    if entry.exists:
        result = source.load(entry.asset, entry.timeframe)
        if result.ok and result.dataframe is not None:
            quality = analyze_quality(result.dataframe)
        else:
            quality_error = result.message

    return DatasetSummary(
        catalog_entry=entry,
        timeframe_statuses=statuses,
        quality=quality,
        quality_error=quality_error,
    )
