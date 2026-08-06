"""
market_data/eodhd/windowing.py — Découpage des téléchargements intraday en fenêtres autorisées.

Limites documentées officiellement par EODHD (vérifiées via la documentation officielle et le
MCP EODHD le 2026-08-06, voir AI_HANDOFF.md) pour l'endpoint /intraday/{ticker} :
  - interval "1m" : 120 jours maximum par requête ;
  - interval "5m" : 600 jours maximum par requête ;
  - interval "1h" : 7200 jours maximum par requête.

Module pur : ne fait aucun appel réseau, ne lit ni n'écrit aucun fichier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .errors import EodhdWindowLimitError

MAX_DAYS_BY_INTERVAL: dict[str, int] = {"1m": 120, "5m": 600, "1h": 7200}


def max_days_for_interval(interval: str) -> int:
    """Nombre maximal de jours couvrables en une seule requête pour cet intervalle intraday."""
    try:
        return MAX_DAYS_BY_INTERVAL[interval]
    except KeyError as exc:
        valid = ", ".join(sorted(MAX_DAYS_BY_INTERVAL))
        raise ValueError(f"Intervalle intraday non supporté : {interval!r} (valides : {valid}).") from exc


@dataclass(frozen=True)
class IntradayWindow:
    """Une fenêtre de téléchargement intraday, bornes incluse/exclue laissées à l'appelant."""

    start: datetime
    end: datetime


def split_intraday_windows(
    start: datetime,
    end: datetime,
    interval: str,
    max_windows: int = 50,
) -> list[IntradayWindow]:
    """Découpe [start, end] en fenêtres contiguës respectant la limite de `interval`.

    Lève ValueError si start >= end. Lève EodhdWindowLimitError si la période demandée
    nécessiterait plus de `max_windows` fenêtres (garde-fou explicite plutôt qu'un
    téléchargement silencieusement énorme — voir CLAUDE.md, contrainte "limite du nombre de
    fenêtres").
    """
    if start >= end:
        raise ValueError("start doit être strictement antérieur à end.")

    window_length = timedelta(days=max_days_for_interval(interval))

    windows: list[IntradayWindow] = []
    cursor = start
    while cursor < end:
        window_end = min(cursor + window_length, end)
        windows.append(IntradayWindow(start=cursor, end=window_end))
        if len(windows) > max_windows:
            raise EodhdWindowLimitError(
                f"La période demandée ({start} -> {end}, intervalle {interval!r}) nécessiterait "
                f"plus de {max_windows} fenêtres de {max_days_for_interval(interval)} jours. "
                "Réduis la période ou augmente explicitement max_windows si c'est voulu."
            )
        cursor = window_end
    return windows
