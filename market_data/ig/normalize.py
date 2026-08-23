"""
market_data/ig/normalize.py — Conversion des prix IG vers un DataFrame proche du schéma canonique.

IG fournit un bid et un ask pour chaque OHLC (pas un close unique) — champs bruts confirmés par
recoupement documentation officielle IG Labs + bibliothèque de référence trading-ig (2026-08-06,
voir AI_HANDOFF.md). Forme des enregistrements confirmée sur l'endpoint réellement utilisé par ce
dépôt, `GET /prices/{epic}` VERSION 3 (voir market_data/ig/client.py) : prices[].{snapshotTime,
snapshotTimeUTC, openPrice:{bid,ask}, highPrice:{bid,ask}, lowPrice:{bid,ask},
closePrice:{bid,ask}, lastTradedVolume} — la forme VERSION 2 historique
(/prices/{epic}/{resolution}/{startDate}/{endDate}) n'est plus utilisée depuis la correction du
2026-08-06 documentée dans AI_HANDOFF.md, mentionnée ici uniquement pour mémoire.

**Champ temporel source : `snapshotTimeUTC`, jamais `snapshotTime` (AF-V-01, 2026-08-23, voir
docs/adr/0017-ig-demo-dataset-snapshot-identity-and-timezone-assumption.md pour l'investigation
complète).** `snapshotTime` (format `%Y/%m/%d %H:%M:%S`) est une heure locale/serveur non
documentée par IG (confusion connue, fil IG Labs "prices API timezone is messy") — la bibliothèque
de référence `trading-ig` l'abandonne d'ailleurs délibérément au profit de `snapshotTimeUTC`
(format `%Y-%m-%dT%H:%M:%S`) pour les réponses VERSION 3, précisément pour cette raison. Confirmé
sur les 4800 enregistrements réels acquis lors d'AF-V-01 Phase A : `snapshotTimeUTC` présent à
100%, jamais un offset fixe supposé (aucun `+2h`/`+1h` codé en dur nulle part dans ce module —
seule la valeur du champ compte). `snapshotTime` n'est ni requis, ni conservé dans le DataFrame
produit (décision explicite, pas un oubli — voir l'ADR : il ne porterait aucune information que
`snapshotTimeUTC` n'a pas déjà, seulement une ambiguïté supplémentaire).

Ce module calcule le prix médian (bid+ask)/2 pour chaque OHLC afin de produire les colonnes
canoniques (market_data.schema.CANONICAL_COLUMNS, "time" tz-naive UTC — même convention que
market_data.eodhd.normalize ; le calcul du mid bid/ask est inchangé par la correction du champ
temporel décrite ci-dessus, seule la construction de "time" en dépendait). Les valeurs bid/ask
brutes restent disponibles en plus, dans des colonnes *_bid/*_ask, pour ne perdre aucune
information de la source.

Module pur : ne fait aucun appel réseau, ne lit ni n'écrit aucun fichier.
"""

from __future__ import annotations

import pandas as pd

from market_data.schema import CANONICAL_COLUMNS

from .errors import IgResponseError

# Format IG confirmé pour snapshotTimeUTC (VERSION 3) — distinct du format historique de
# snapshotTime (%Y/%m/%d %H:%M:%S, plus utilisé ici, voir docstring du module).
_DATE_FORMAT_UTC = "%Y-%m-%dT%H:%M:%S"
_REQUIRED_FIELDS = ("snapshotTimeUTC", "openPrice", "highPrice", "lowPrice", "closePrice")
_OHLC_FIELDS = (("open", "openPrice"), ("high", "highPrice"), ("low", "lowPrice"), ("close", "closePrice"))


def _empty_price_df() -> pd.DataFrame:
    columns = list(CANONICAL_COLUMNS) + [f"{name}_{side}" for name, _ in _OHLC_FIELDS for side in ("bid", "ask")]
    return pd.DataFrame({col: pd.Series(dtype="object") for col in columns})


def normalize_price_records(records: list) -> pd.DataFrame:
    """Convertit une liste d'enregistrements prices[] (endpoint /prices IG, v3) vers un
    DataFrame proche du schéma canonique (mid bid/ask) + colonnes bid/ask brutes.

    "time" est construit depuis `snapshotTimeUTC` (jamais `snapshotTime`, ambigu — voir docstring
    du module et docs/adr/0017-...) via le même idiome de fond que market_data.eodhd.normalize
    (`pd.to_datetime(..., utc=True).dt.tz_localize(None)`), avec un `format=` explicite en plus
    (le format IG est fixe et connu, contrairement aux dates EODHD) : numériquement un no-op ici
    (la chaîne ne porte aucun offset à convertir), mais cohérent avec la convention déjà établie
    et sûr si une future version de l'API IG ajoutait un indicateur d'offset explicite à ce champ.

    Lève IgResponseError si un champ obligatoire (dont `snapshotTimeUTC`, vérifié sur CHAQUE
    enregistrement, pas seulement le premier) est absent.
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

    # snapshotTimeUTC est vérifié sur CHAQUE enregistrement, pas seulement le premier (trouvé en
    # revue Spec, 2026-08-23) — un enregistrement ultérieur incomplet doit lever IgResponseError
    # comme n'importe quel champ obligatoire manquant, jamais un KeyError brut non maîtrisé.
    # Volontairement pas étendu aux autres _REQUIRED_FIELDS (openPrice/etc.) : hors du périmètre
    # de ce correctif, qui ne porte que sur la source temporelle (voir docs/adr/0017-...).
    for index, record in enumerate(records):
        if "snapshotTimeUTC" not in record:
            raise IgResponseError(
                f"Champ obligatoire manquant dans l'enregistrement IG /prices à l'index {index} : "
                f"snapshotTimeUTC (champs reçus : {sorted(record.keys())})."
            )

    rows = []
    for record in records:
        snapshot_utc = pd.to_datetime(record["snapshotTimeUTC"], format=_DATE_FORMAT_UTC, utc=True)
        row = {"time": snapshot_utc.tz_localize(None)}
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
