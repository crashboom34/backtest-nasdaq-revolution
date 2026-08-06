"""
market_data/ig/normalize.py — Conversion des prix IG vers un DataFrame proche du schéma canonique.

IG fournit un bid et un ask pour chaque OHLC (pas un close unique) — champs bruts confirmés par
recoupement documentation officielle IG Labs + bibliothèque de référence trading-ig
(2026-08-06, voir AI_HANDOFF.md) sur l'endpoint /prices/{epic}/{resolution}/{startDate}/
{endDate} (version 2) : prices[].{snapshotTime, openPrice:{bid,ask}, highPrice:{bid,ask},
lowPrice:{bid,ask}, closePrice:{bid,ask}, lastTradedVolume}. Format de date confirmé pour cette
version : "%Y/%m/%d %H:%M:%S".

Ce module calcule le prix médian (bid+ask)/2 pour chaque OHLC afin de produire les colonnes
canoniques (market_data.schema.CANONICAL_COLUMNS, "time" tz-naive UTC — même convention que
market_data.eodhd.normalize). Les valeurs bid/ask brutes restent disponibles en plus, dans des
colonnes *_bid/*_ask, pour ne perdre aucune information de la source.

Module pur : ne fait aucun appel réseau, ne lit ni n'écrit aucun fichier.
"""

from __future__ import annotations

import pandas as pd

from market_data.schema import CANONICAL_COLUMNS

from .errors import IgResponseError

_DATE_FORMAT_V2 = "%Y/%m/%d %H:%M:%S"
_REQUIRED_FIELDS = ("snapshotTime", "openPrice", "highPrice", "lowPrice", "closePrice")
_OHLC_FIELDS = (("open", "openPrice"), ("high", "highPrice"), ("low", "lowPrice"), ("close", "closePrice"))


def _empty_price_df() -> pd.DataFrame:
    columns = list(CANONICAL_COLUMNS) + [f"{name}_{side}" for name, _ in _OHLC_FIELDS for side in ("bid", "ask")]
    return pd.DataFrame({col: pd.Series(dtype="object") for col in columns})


def normalize_price_records(records: list) -> pd.DataFrame:
    """Convertit une liste d'enregistrements prices[] (endpoint /prices IG, v2) vers un
    DataFrame proche du schéma canonique (mid bid/ask) + colonnes bid/ask brutes.

    Lève IgResponseError si un champ obligatoire est absent du premier enregistrement.
    """
    if not records:
        return _empty_price_df()

    missing = [f for f in _REQUIRED_FIELDS if f not in records[0]]
    if missing:
        raise IgResponseError(
            "Champs obligatoires manquants dans la réponse IG /prices : "
            + ", ".join(missing)
            + f" (champs reçus : {sorted(records[0].keys())})."
        )

    rows = []
    for record in records:
        row = {"time": pd.to_datetime(record["snapshotTime"], format=_DATE_FORMAT_V2)}
        for canonical_name, raw_key in _OHLC_FIELDS:
            side_prices = record.get(raw_key) or {}
            bid = side_prices.get("bid")
            ask = side_prices.get("ask")
            row[f"{canonical_name}_bid"] = bid
            row[f"{canonical_name}_ask"] = ask
            row[canonical_name] = (bid + ask) / 2 if bid is not None and ask is not None else None
        row["volume"] = record.get("lastTradedVolume")
        rows.append(row)

    df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
    ordered_cols = list(CANONICAL_COLUMNS) + [
        f"{name}_{side}" for name, _ in _OHLC_FIELDS for side in ("bid", "ask")
    ]
    return df[[c for c in ordered_cols if c in df.columns]]
