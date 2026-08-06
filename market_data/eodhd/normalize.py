"""
market_data/eodhd/normalize.py — Conversion des réponses brutes EODHD vers un DataFrame.

Deux catégories, volontairement séparées :
  - EOD / intraday -> schéma canonique OHLCV (market_data.schema.CANONICAL_COLUMNS), colonne
    "time" tz-naive représentant un instant UTC (même convention que market_data/adapters/
    local_csv.py et engine._add_market_time_columns(), qui fait un tz_localize("UTC") sur un
    "time" déjà naïf) ;
  - dividendes / splits -> hors du schéma canonique OHLCV (voir docs/adr/0002-...), colonnes
    propres à ces événements, jamais mélangées aux colonnes canoniques.

Les noms de champs bruts utilisés ici (date, adjusted_close, timestamp, gmtoffset, datetime,
declarationDate, recordDate, paymentDate, unadjustedValue, split...) ont été vérifiés via le MCP
EODHD le 2026-08-06 (voir AI_HANDOFF.md) — jamais devinés.

Module pur : ne fait aucun appel réseau, ne lit ni n'écrit aucun fichier.
"""

from __future__ import annotations

import pandas as pd

from market_data.schema import CANONICAL_COLUMNS

from .errors import EodhdResponseError

_EOD_REQUIRED_FIELDS = ("date", "open", "high", "low", "close")
_INTRADAY_REQUIRED_FIELDS = ("timestamp", "open", "high", "low", "close")


def _empty_canonical_df() -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series(dtype="object") for col in CANONICAL_COLUMNS})


def _require_fields(records: list[dict], required: tuple[str, ...], kind: str) -> None:
    missing_in_first = [f for f in required if f not in records[0]]
    if missing_in_first:
        raise EodhdResponseError(
            f"Champs obligatoires manquants dans la réponse EODHD {kind} : "
            + ", ".join(missing_in_first)
            + f" (champs reçus : {sorted(records[0].keys())})."
        )


def normalize_eod_records(records: list[dict]) -> pd.DataFrame:
    """Convertit une liste d'enregistrements /eod/{ticker} vers le schéma canonique.

    Lève EodhdResponseError si un champ obligatoire (date, open, high, low, close) est absent.
    """
    if not records:
        return _empty_canonical_df()

    _require_fields(records, _EOD_REQUIRED_FIELDS, "EOD")

    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None)
    if "volume" not in df.columns:
        df["volume"] = pd.NA

    ordered = df[list(CANONICAL_COLUMNS)].sort_values("time").reset_index(drop=True)
    return ordered


def normalize_intraday_records(records: list[dict]) -> pd.DataFrame:
    """Convertit une liste d'enregistrements /intraday/{ticker} vers le schéma canonique.

    Utilise le champ "timestamp" (secondes Unix UTC, source de vérité documentée par EODHD)
    plutôt que "datetime"/"gmtoffset" pour construire "time", afin de garantir un UTC canonique
    même si gmtoffset diffère de 0 pour un fournisseur ou une configuration future. Déduplique
    les timestamps identiques (peut arriver en bord de fenêtre lors d'un téléchargement découpé,
    voir market_data.eodhd.windowing) et trie chronologiquement.

    Lève EodhdResponseError si un champ obligatoire est absent.
    """
    if not records:
        return _empty_canonical_df()

    _require_fields(records, _INTRADAY_REQUIRED_FIELDS, "intraday")

    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_localize(None)
    if "volume" not in df.columns:
        df["volume"] = pd.NA

    ordered = (
        df[list(CANONICAL_COLUMNS)]
        .drop_duplicates(subset="time", keep="last")
        .sort_values("time")
        .reset_index(drop=True)
    )
    return ordered


def normalize_dividend_records(records: list[dict]) -> pd.DataFrame:
    """Convertit une liste d'enregistrements /div/{ticker}. Hors schéma canonique OHLCV
    (voir docs/adr/0002-...) : colonnes propres aux dividendes."""
    if not records:
        return pd.DataFrame(
            columns=[
                "ex_dividend_date", "declaration_date", "record_date", "payment_date",
                "period", "value", "unadjusted_value", "currency",
            ]
        )

    df = pd.DataFrame(records)
    return pd.DataFrame(
        {
            "ex_dividend_date": pd.to_datetime(df.get("date")),
            "declaration_date": pd.to_datetime(df.get("declarationDate")),
            "record_date": pd.to_datetime(df.get("recordDate")),
            "payment_date": pd.to_datetime(df.get("paymentDate")),
            "period": df.get("period"),
            "value": df.get("value"),
            "unadjusted_value": df.get("unadjustedValue"),
            "currency": df.get("currency"),
        }
    )


def normalize_split_records(records: list[dict]) -> pd.DataFrame:
    """Convertit une liste d'enregistrements /splits/{ticker}. Hors schéma canonique OHLCV.

    Le champ brut "split" est une chaîne "TO/FROM" (ex. "4.000000/1.000000" pour un split
    4-pour-1, vérifié via le MCP EODHD le 2026-08-06) : décomposé en split_to/split_from/
    split_ratio (= split_to / split_from) pour rester exploitable sans reparser la chaîne.
    """
    if not records:
        return pd.DataFrame(columns=["date", "split_to", "split_from", "split_ratio"])

    df = pd.DataFrame(records)
    parts = df["split"].str.split("/", n=1, expand=True)
    split_to = parts[0].astype(float)
    split_from = parts[1].astype(float)

    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"]),
            "split_to": split_to,
            "split_from": split_from,
            "split_ratio": split_to / split_from,
        }
    )
