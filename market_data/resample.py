"""
market_data/resample.py — Génération de timeframes dérivés (resampling).

Règles complètes documentées dans docs/adr/0003-timeframe-resampling-rules.md (M/H/D par
multiple entier de minutes) et docs/adr/0004-calendar-timeframe-resampling.md (W1/MO1,
calendaires, dérivables uniquement depuis une source D1) :
- un timeframe cible M/H/D n'est calculable que s'il est un multiple entier du timeframe
  source ; ancrage UTC uniquement (pas de calendrier de marché) ;
- W1 (semaine, ancrage lundi-dimanche) et MO1 (mois civil) ne sont dérivables que depuis D1 ;
- la dernière bougie dérivée est signalée si elle est incomplète, jamais supprimée en silence.

Module pur : ne lit ni n'écrit aucun fichier. Le cache disque des résultats dérivés est géré
par market_data.derived (étape suivante du plan).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from market_data.schema import CANONICAL_COLUMNS

# "MO" (mois) doit être tenté avant "M" (minutes) dans l'alternation pour que "MO1" ne soit pas
# d'abord lu comme l'unité minute "M" suivie d'un résidu "O1" invalide.
_TIMEFRAME_PATTERN = re.compile(r"^(MO|[MHDW])(\d+)$")
_UNIT_MINUTES = {"M": 1, "H": 60, "D": 1440}
# Unités calendaires : pas de durée fixe en minutes, dérivation dédiée (voir ADR 0004).
_CALENDAR_UNITS = ("W", "MO")


class ResampleError(ValueError):
    """Levée quand un timeframe cible n'est pas calculable depuis le timeframe source."""


def _parse_timeframe(timeframe: str) -> tuple[str, int]:
    code = str(timeframe or "").strip().upper()
    match = _TIMEFRAME_PATTERN.match(code)
    if not match:
        raise ResampleError(
            f"Timeframe non reconnu : {timeframe!r} (formats acceptés : M<n>, H<n>, D<n>, W1, MO1)."
        )
    unit, amount = match.group(1), int(match.group(2))
    if amount <= 0:
        raise ResampleError(f"Timeframe invalide : {timeframe!r} (le multiplicateur doit être positif).")
    return unit, amount


def timeframe_to_minutes(timeframe: str) -> int:
    """Convertit un code timeframe (ex. 'M3', 'H1', 'D1') en nombre de minutes.

    Formats acceptés : M<n> (minutes), H<n> (heures), D<n> (jours). Lève ResampleError si le
    format n'est pas reconnu, si <n> n'est pas positif, ou si le timeframe est une unité
    calendaire (W1, MO1 — pas de durée fixe en minutes, voir ADR 0004).
    """
    unit, amount = _parse_timeframe(timeframe)
    if unit in _CALENDAR_UNITS:
        raise ResampleError(
            f"{timeframe!r} est une unité calendaire sans durée fixe en minutes ; utilise "
            "is_derivable()/resample_ohlcv() qui la gèrent directement (voir ADR 0004)."
        )
    return _UNIT_MINUTES[unit] * amount


def _is_derivable_calendar(source_timeframe: str, target_timeframe: str) -> bool:
    """W1/MO1 uniquement, uniquement depuis une source D1 (voir ADR 0004)."""
    try:
        target_unit, target_amount = _parse_timeframe(target_timeframe)
    except ResampleError:
        return False
    if target_unit not in _CALENDAR_UNITS or target_amount != 1:
        return False
    return str(source_timeframe or "").strip().upper() == "D1"


def is_derivable(source_timeframe: str, target_timeframe: str) -> bool:
    """True si target_timeframe peut être dérivé de source_timeframe.

    M/H/D : multiple entier de minutes, cible >= source (voir ADR 0003).
    W1/MO1 : uniquement depuis une source D1 (voir ADR 0004) — jamais de dérivation inverse
    (une source calendaire ne dérive rien dans cette version).
    """
    src = str(source_timeframe or "").strip().upper()
    tgt = str(target_timeframe or "").strip().upper()

    src_match = _TIMEFRAME_PATTERN.match(src)
    tgt_match = _TIMEFRAME_PATTERN.match(tgt)
    src_is_calendar = bool(src_match and src_match.group(1) in _CALENDAR_UNITS)
    tgt_is_calendar = bool(tgt_match and tgt_match.group(1) in _CALENDAR_UNITS)

    if src_is_calendar or tgt_is_calendar:
        return _is_derivable_calendar(src, tgt)

    try:
        source_minutes = timeframe_to_minutes(src)
        target_minutes = timeframe_to_minutes(tgt)
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
            "le timeframe cible doit être un multiple entier du timeframe source (ou W1/MO1 "
            "depuis une source D1 — voir ADR 0004)."
        )

    missing = [c for c in ("time", "open", "high", "low", "close") if c not in df.columns]
    if missing:
        raise ResampleError(f"Colonnes canoniques manquantes pour le resampling : {', '.join(missing)}.")

    tgt_match = _TIMEFRAME_PATTERN.match(str(target_timeframe).strip().upper())
    if tgt_match and tgt_match.group(1) in _CALENDAR_UNITS:
        return _resample_calendar(df, source_timeframe, target_timeframe, tgt_match.group(1))

    source_minutes = timeframe_to_minutes(source_timeframe)
    target_minutes = timeframe_to_minutes(target_timeframe)

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


def _resample_calendar(
    df: pd.DataFrame, source_timeframe: str, target_timeframe: str, unit: str
) -> ResampleResult:
    """W1 (ancrage lundi-dimanche) / MO1 (mois civil) depuis une source D1 — voir ADR 0004.

    N'est appelée que par resample_ohlcv() une fois is_derivable() et les colonnes canoniques
    déjà vérifiées."""
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

    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in working.columns:
        agg["volume"] = "sum"

    if unit == "W":
        # "W-SUN" ancre nativement sur le dimanche (fin de semaine) : avec closed="right",
        # label="right" (comportement pandas par défaut pour W), un bucket (dimanche_précédent,
        # dimanche] couvre exactement lundi->dimanche mais est étiqueté par le dimanche. On
        # décale ensuite l'étiquette de 6 jours pour l'exprimer par le lundi de la semaine
        # (convention retenue dans l'ADR 0004).
        resampled = working.resample("W-SUN", label="right", closed="right").agg(agg)
        resampled = resampled.dropna(subset=["open", "high", "low", "close"], how="all")
        resampled.index = resampled.index - pd.Timedelta(days=6)
    else:  # "MO"
        resampled = working.resample("MS", label="left", closed="left").agg(agg)
        resampled = resampled.dropna(subset=["open", "high", "low", "close"], how="all")

    source_max = pd.Timestamp(df["time"].max())
    incomplete_last_bar = False
    if len(resampled):
        last_bucket_start = resampled.index[-1]
        bucket_end = (
            last_bucket_start + pd.Timedelta(days=6)
            if unit == "W"
            else last_bucket_start + pd.offsets.MonthEnd(0)
        )
        incomplete_last_bar = bool(source_max < bucket_end)

    resampled = resampled.reset_index()
    ordered_cols = [c for c in CANONICAL_COLUMNS if c in resampled.columns]
    resampled = resampled[ordered_cols]

    anchor_label = "lundi-dimanche" if unit == "W" else "mois civil"
    message = (
        f"{len(resampled)} bougie(s) {target_timeframe} dérivée(s) de {source_timeframe} "
        f"(ancrage calendaire {anchor_label} UTC, sans calendrier de marché — voir "
        "docs/adr/0004-calendar-timeframe-resampling.md)."
    )
    if incomplete_last_bar:
        message += " Dernière bougie incomplète (période calendaire pas encore terminée dans la source)."

    return ResampleResult(
        dataframe=resampled,
        source_timeframe=source_timeframe,
        target_timeframe=target_timeframe,
        incomplete_last_bar=incomplete_last_bar,
        message=message,
    )


def infer_timeframe_from_series(time_series) -> str | None:
    """Infère un code timeframe (ex. 'M3', 'H1', 'D1') à partir de l'écart médian entre bougies
    consécutives d'une série de temps. Utilisée pour enrichir un manifeste de backtest avec des
    données réellement observées plutôt qu'une valeur devinée (voir market_data.backtest_manifest).

    Retourne None si la série a moins de 2 points, ou si l'écart médian ne correspond pas
    exactement à un multiple entier de minutes — jamais une approximation. La médiane (plutôt
    que la moyenne) résiste aux quelques trous ou barres dupliquées d'une série réelle.
    """
    times = pd.to_datetime(pd.Series(list(time_series))).sort_values().reset_index(drop=True)
    if len(times) < 2:
        return None

    diffs = times.diff().dropna()
    if diffs.empty:
        return None

    median_minutes = diffs.median().total_seconds() / 60
    if median_minutes <= 0 or median_minutes != int(median_minutes):
        return None
    median_minutes = int(median_minutes)

    if median_minutes % 1440 == 0:
        return f"D{median_minutes // 1440}"
    if median_minutes % 60 == 0:
        return f"H{median_minutes // 60}"
    return f"M{median_minutes}"
