"""
market_data/catalog.py — Catalogue local minimal des jeux de données de marché (Phase 1).

Construit et persiste un inventaire léger des jeux de données déjà présents dans data/ (et du
fallback legacy nasdaq_3m.csv), à partir d'un MarketDataSource (aujourd'hui : uniquement
LocalCsvMarketDataSource). Ne modifie jamais les CSV sources, ne fait aucun appel réseau.

Le catalogue est un fichier JSON généré localement (settings/data_catalog.json, ignoré par
Git — même convention que settings/champion_validation.json), reconstruit à la demande via
refresh_catalog(). Il n'est pas encore branché dans l'interface Streamlit à cette étape.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Union

from market_data.ports import MarketDataSource
from market_data.schema import MarketDatasetInfo

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent.parent / "settings" / "data_catalog.json"


@dataclass(frozen=True)
class CatalogEntry:
    """Une ligne du catalogue : métadonnées d'un jeu de données, avec statistiques optionnelles."""

    provider: str
    asset: str
    timeframe: str
    source: str
    exists: bool
    relative_path: Optional[str]
    message: str
    row_count: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None
    stats_error: Optional[str] = None


def build_catalog(source: MarketDataSource, compute_stats: bool = True) -> list[CatalogEntry]:
    """Construit le catalogue à partir d'un MarketDataSource.

    compute_stats=True charge chaque dataset existant pour calculer row_count/start/end
    (lecture locale uniquement, aucun réseau). Pour un gros CSV (ex. nasdaq_3m.csv), cela peut
    prendre plusieurs secondes : passer compute_stats=False pour un inventaire rapide sans stats.
    """
    return [_build_entry(source, info, compute_stats) for info in source.list_available()]


def _build_entry(source: MarketDataSource, info: MarketDatasetInfo, compute_stats: bool) -> CatalogEntry:
    base = dict(
        provider=info.provider,
        asset=info.asset,
        timeframe=info.timeframe,
        source=info.source,
        exists=info.exists,
        relative_path=info.relative_path,
        message=info.message,
    )

    if not info.exists or not compute_stats:
        return CatalogEntry(**base)

    result = source.load(info.asset, info.timeframe)
    if not result.ok or result.dataframe is None:
        return CatalogEntry(**base, stats_error=result.message)

    df = result.dataframe
    row_count = int(len(df))
    start = str(df["time"].min()) if row_count else None
    end = str(df["time"].max()) if row_count else None
    return CatalogEntry(**base, row_count=row_count, start=start, end=end)


def save_catalog(entries: list[CatalogEntry], path: Union[str, Path] = DEFAULT_CATALOG_PATH) -> None:
    """Sauvegarde atomique du catalogue en JSON (écriture fichier temporaire + os.replace,
    même schéma que validation_settings.save_validation_settings)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".json.tmp")
    payload = [asdict(entry) for entry in entries]
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, target)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


def load_catalog(path: Union[str, Path] = DEFAULT_CATALOG_PATH) -> list[CatalogEntry]:
    """Lecture tolérante : catalogue absent, illisible ou invalide → liste vide, jamais d'exception."""
    target = Path(path)
    if not target.is_file():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            return []
        return [CatalogEntry(**item) for item in payload if isinstance(item, dict)]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []


def refresh_catalog(
    source: MarketDataSource,
    path: Union[str, Path] = DEFAULT_CATALOG_PATH,
    compute_stats: bool = True,
) -> list[CatalogEntry]:
    """Reconstruit le catalogue à partir de la source et le sauvegarde sur disque."""
    entries = build_catalog(source, compute_stats=compute_stats)
    save_catalog(entries, path)
    return entries
