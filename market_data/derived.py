"""
market_data/derived.py — Cache disque des timeframes dérivés (Phase 1).

Combine market_data.resample (calcul) et un cache CSV local pour éviter de recalculer un
timeframe dérivé à chaque backtest ("générer une fois lors du premier usage, réutiliser
ensuite" — voir la demande initiale du Data Center, section 3).

Le cache vit dans derived_data/ (racine du dépôt, ignoré par Git — ce sont des fichiers
générés, jamais des données sources). Il est invalidé automatiquement si les données source ont
changé depuis la dernière génération (comparaison d'une signature légère : nombre de lignes +
dernier timestamp, plus robuste qu'une date de modification de fichier après un git checkout).

Rien n'est encore branché dans app.py/engine.py à cette étape.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from market_data.ports import MarketDataSource
from market_data.resample import ResampleError, resample_ohlcv
from market_data.schema import CANONICAL_COLUMNS

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "derived_data"


@dataclass(frozen=True)
class DerivedResult:
    """Résultat d'une demande de timeframe dérivé, servi depuis le cache ou fraîchement calculé."""

    dataframe: Optional[pd.DataFrame]
    asset: str
    source_timeframe: str
    target_timeframe: str
    ok: bool
    from_cache: bool
    incomplete_last_bar: bool = False
    message: str = ""


def get_or_generate(
    source: MarketDataSource,
    asset: str,
    source_timeframe: str,
    target_timeframe: str,
    cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
) -> DerivedResult:
    """Sert le timeframe dérivé depuis le cache s'il est à jour, sinon le (re)calcule et le
    sauvegarde. Ne modifie jamais les données source."""
    cache_dir = Path(cache_dir)
    csv_path, meta_path = _cache_paths(cache_dir, asset, source_timeframe, target_timeframe)

    source_result = source.load(asset, source_timeframe)
    if not source_result.ok or source_result.dataframe is None:
        return DerivedResult(
            dataframe=None,
            asset=asset,
            source_timeframe=source_timeframe,
            target_timeframe=target_timeframe,
            ok=False,
            from_cache=False,
            message=f"Source {source_timeframe} indisponible : {source_result.message}",
        )

    source_signature = _source_signature(source_result.dataframe)

    cached = _read_cache(csv_path, meta_path, source_signature)
    if cached is not None:
        return DerivedResult(
            dataframe=cached,
            asset=asset,
            source_timeframe=source_timeframe,
            target_timeframe=target_timeframe,
            ok=True,
            from_cache=True,
            message=f"Servi depuis le cache ({csv_path.name}).",
        )

    try:
        result = resample_ohlcv(source_result.dataframe, source_timeframe, target_timeframe)
    except ResampleError as exc:
        return DerivedResult(
            dataframe=None,
            asset=asset,
            source_timeframe=source_timeframe,
            target_timeframe=target_timeframe,
            ok=False,
            from_cache=False,
            message=str(exc),
        )

    _write_cache(csv_path, meta_path, result.dataframe, source_signature)

    return DerivedResult(
        dataframe=result.dataframe,
        asset=asset,
        source_timeframe=source_timeframe,
        target_timeframe=target_timeframe,
        ok=True,
        from_cache=False,
        incomplete_last_bar=result.incomplete_last_bar,
        message=result.message,
    )


def is_cached(
    cache_dir: Union[str, Path], asset: str, source_timeframe: str, target_timeframe: str
) -> bool:
    """True si un timeframe dérivé a déjà un fichier en cache pour cet actif.

    Vérifie uniquement la présence des fichiers, pas leur fraîcheur : la fraîcheur (signature
    de la source) n'est contrôlée qu'au moment de get_or_generate(). Utilisé par
    market_data.catalog pour distinguer "calculable" de "déjà en cache" (voir la demande
    initiale, section 3 : unité source / calculable / en cache)."""
    csv_path, meta_path = _cache_paths(Path(cache_dir), asset, source_timeframe, target_timeframe)
    return csv_path.is_file() and meta_path.is_file()


def _cache_paths(cache_dir: Path, asset: str, source_timeframe: str, target_timeframe: str) -> tuple[Path, Path]:
    folder = cache_dir / asset
    stem = f"{target_timeframe}__from_{source_timeframe}"
    return folder / f"{stem}.csv", folder / f"{stem}.meta.json"


def _source_signature(df: pd.DataFrame) -> dict:
    """Signature légère du DataFrame source, utilisée pour invalider le cache s'il change."""
    if df.empty:
        return {"row_count": 0, "last_time": None}
    return {"row_count": int(len(df)), "last_time": str(df["time"].iloc[-1])}


def _read_cache(csv_path: Path, meta_path: Path, source_signature: dict) -> Optional[pd.DataFrame]:
    if not csv_path.is_file() or not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict) or meta.get("source_signature") != source_signature:
        return None
    try:
        df = pd.read_csv(csv_path, parse_dates=["time"])
    except Exception:
        return None
    ordered_cols = [c for c in CANONICAL_COLUMNS if c in df.columns]
    return df[ordered_cols]


def _write_cache(csv_path: Path, meta_path: Path, df: pd.DataFrame, source_signature: dict) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_csv = csv_path.with_suffix(".csv.tmp")
    df.to_csv(tmp_csv, index=False)
    os.replace(tmp_csv, csv_path)

    tmp_meta = meta_path.with_suffix(".json.tmp")
    tmp_meta.write_text(
        json.dumps({"source_signature": source_signature}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_meta, meta_path)
