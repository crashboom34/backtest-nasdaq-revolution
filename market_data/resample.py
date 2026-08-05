"""
market_data/resample.py — Génération de timeframes dérivés (resampling).

Règles complètes documentées dans docs/adr/0003-timeframe-resampling-rules.md :
- un timeframe cible n'est calculable que s'il est un multiple entier du timeframe source ;
- ancrage UTC uniquement pour cette étape (pas de calendrier de marché) ;
- la dernière bougie dérivée est signalée si elle est incomplète, jamais supprimée en silence.

Module pur : ne lit ni n'écrit aucun fichier. Le cache disque des résultats dérivés est géré
par market_data.derived (étape suivante du plan).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from market_data.schema import CANONICAL_COLUMNS

_TIMEFRAME_PATTERN = re.compile(r"^([MHD])(\d+)$")
_UNIT_MINUTES = {"M": 1, "H": 60, "D": 1440}


class ResampleError(ValueError):
    """Levée quand un timeframe cible n'est pas calculable depuis le timeframe source."""


def timeframe_to_minutes(timeframe: str) -> int:
    """Convertit un code timeframe (ex. 'M3', 'H1', 'D1') en nombre de minutes.

    Formats acceptés : M<n> (minutes), H<n> (heures), D<n> (jours).
    Lève ResampleError si le format n'est pas reconnu ou si <n> n'est pas positif.
    """
    code = str(timeframe or "").strip().upper()
    match = _TIMEFRAME_PATTERN.match(code)
    if not match:
        raise ResampleError(
            f"Timeframe non reconnu : {timeframe!r} (formats acceptés : M<n>, H<n>, D<n>)."
        )
    unit, amount = match.group(1), int(match.group(2))
    if amount <= 0:
        raise ResampleError(f"Timeframe invalide : {timeframe!r} (le multiplicateur doit être positif).")
    return _UNIT_MINUTES[unit] * amount


def is_derivable(source_timeframe: str, target_timeframe: str) -> bool:
    """True si target_timeframe peut être dérivé de source_timeframe (multiple entier, >= source)."""
    try:
        source_minutes = timeframe_to_minutes(source_timeframe)
        target_minutes = timeframe_to_minutes(target_timeframe)
    except ResampleError:
        return False
    if target_minutes < source_minutes:
        return False
    return target_minutes % source_minutes == 0


@dataclass(frozen=True)
class ResampleResult:
    """Résultat d'une dérivation de timeframe."""

    dataframe: pd.DataFrame
    source_timeframe: str
    target_timeframe: str
    incomplete_last_bar: bool
    message: str


def resample_ohlcv(df: pd.DataFrame, source_timeframe: str, target_timeframe: str) -> ResampleResult:
    """Dérive target_timeframe à partir d'un DataFrame canonique déjà chargé en source_timeframe.

    df doit contenir au moins les colonnes obligatoires du schéma canonique (time, open, high,
    low, close) ; volume est sommé s'il est présent. Lève ResampleError si le timeframe cible
    n'est pas calculable depuis le timeframe source (voir is_derivable()).
    """
    if not is_derivable(source_timeframe, target_timeframe):
        raise ResampleError(
            f"Impossible de dériver {target_timeframe!r} depuis {source_timeframe!r} : "
            "le timeframe cible doit être un multiple entier du timeframe source."
        )

    source_minutes = timeframe_to_minutes(source_timeframe)
    target_minutes = timeframe_to_minutes(target_timeframe)

    missing = [c for c in ("time", "open", "high", "low", "close") if c not in df.columns]
    if missing:
        raise ResampleError(f"Colonnes canoniques manquantes pour le resampling : {', '.join(missing)}.")

    if target_minutes == source_minutes:
        # Timeframe cible identique à la source : rien à dériver.
        ordered_cols = [c for c in CANONICAL_COLUMNS if c in df.columns]
        return ResampleResult(
            dataframe=df[ordered_cols].copy(),
            source_timeframe=source_timeframe,
            target_timeframe=target_timeframe,
            incomplete_last_bar=False,
            message="Timeframe cible identique au timeframe source, aucune dérivation nécessaire.",
        )

    if df.empty:
        ordered_cols = [c for c in CANONICAL_COLUMNS if c in df.columns]
        return ResampleResult(
            dataframe=df[ordered_cols].copy(),
            source_timeframe=source_timeframe,
            target_timeframe=target_timeframe,
            incomplete_last_bar=False,
            message="Aucune donnée source à dériver.",
        )

    working = df.copy()
    working["time"] = pd.to_datetime(working["time"])
    working = working.sort_values("time").set_index("time")

    rule = f"{target_minutes}min"
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in working.columns:
        agg["volume"] = "sum"

    resampled = working.resample(rule, label="left", closed="left").agg(agg)
    bar_counts = working["close"].resample(rule, label="left", closed="left").count()

    resampled = resampled.dropna(subset=["open", "high", "low", "close"], how="all")
    bar_counts = bar_counts.reindex(resampled.index)

    expected_bars_per_bucket = target_minutes // source_minutes
    incomplete_last_bar = False
    if len(bar_counts):
        incomplete_last_bar = bool(bar_counts.iloc[-1] < expected_bars_per_bucket)

    resampled = resampled.reset_index()
    ordered_cols = [c for c in CANONICAL_COLUMNS if c in resampled.columns]
    resampled = resampled[ordered_cols]

    message = (
        f"{len(resampled)} bougie(s) {target_timeframe} dérivée(s) de {source_timeframe} "
        "(ancrage UTC, sans calendrier de marché — voir docs/adr/0003-timeframe-resampling-rules.md)."
    )
    if incomplete_last_bar:
        message += " Dernière bougie incomplète (série source arrêtée avant la fin de l'intervalle)."

    return ResampleResult(
        dataframe=resampled,
        source_timeframe=source_timeframe,
        target_timeframe=target_timeframe,
        incomplete_last_bar=incomplete_last_bar,
        message=message,
    )
