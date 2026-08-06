"""
market_data/csv_reading.py — Lecture et validation CSV canonique, partagée entre adaptateurs.

Factorise la logique commune entre LocalCsvMarketDataSource (adapters/local_csv.py) et
SingleFileCsvMarketDataSource (adapters/single_file_csv.py) : lire un CSV, vérifier les colonnes
canoniques obligatoires, remplir "volume" à NA si absent, ordonner les colonnes selon le schéma
canonique. Module pur : ne fait aucune résolution de chemin (c'est la responsabilité de chaque
adaptateur) ni aucun appel réseau.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from market_data.schema import CANONICAL_COLUMNS, validate_canonical_columns


@dataclass(frozen=True)
class CsvReadOutcome:
    """Résultat de la lecture/validation d'un CSV canonique."""

    dataframe: Optional[pd.DataFrame]
    ok: bool
    message: str


def _read_and_check_required_columns(path: Union[str, Path]) -> tuple:
    """Partagé par les deux fonctions publiques ci-dessous : lit le CSV et vérifie les colonnes
    obligatoires. Retourne (df_ou_None, message_erreur_ou_vide)."""
    try:
        df = pd.read_csv(path, parse_dates=["time"])
    except Exception as exc:
        return None, f"CSV illisible ({path}) : {exc}"

    missing = validate_canonical_columns(df)
    if missing:
        return None, f"Colonnes canoniques manquantes dans {path} : {', '.join(missing)}."
    return df, ""


def read_canonical_csv(path: Union[str, Path]) -> CsvReadOutcome:
    """Lit un CSV et le NORMALISE au schéma canonique : colonnes canoniques en premier (ordre
    stable), "volume" synthétisé à NA si absent, toute colonne supplémentaire du fichier source
    conservée après (ex. tick_volume, spread...) — jamais de perte silencieuse de données. Ne
    modifie jamais le fichier source. Ne lève jamais d'exception : toute erreur (fichier
    illisible, colonnes obligatoires manquantes) est renvoyée dans CsvReadOutcome.ok/message.

    Utilisé par LocalCsvMarketDataSource, dont le contrat garantit que "volume" existe toujours
    dans le résultat. Pour un passage strictement transparent (aucune colonne ajoutée ni
    réordonnée), voir read_raw_validated_csv() ci-dessous.
    """
    df, error = _read_and_check_required_columns(path)
    if df is None:
        return CsvReadOutcome(dataframe=None, ok=False, message=error)

    df = df.copy()
    if "volume" not in df.columns:
        df["volume"] = pd.NA

    canonical_present = [c for c in CANONICAL_COLUMNS if c in df.columns]
    extra_cols = [c for c in df.columns if c not in CANONICAL_COLUMNS]
    return CsvReadOutcome(dataframe=df[canonical_present + extra_cols], ok=True, message="OK")


def read_raw_validated_csv(path: Union[str, Path]) -> CsvReadOutcome:
    """Lit un CSV SANS le normaliser : aucune colonne ajoutée, retirée ou réordonnée — un
    passage strictement transparent, identique à un `pd.read_csv(path, parse_dates=["time"])`
    direct (le comportement historique d'engine.load_data()). Vérifie seulement que les
    colonnes canoniques obligatoires (time, open, high, low, close) sont présentes.

    Utilisé par SingleFileCsvMarketDataSource, dont le rôle est d'être un remplacement
    strictement transparent d'un appel direct à engine.load_data(csv_file) — voir
    tests/test_engine_load_data_from_source.py, équivalence vérifiée contre le vrai
    nasdaq_3m.csv (qui a des colonnes tick_volume/spread en plus des colonnes canoniques,
    silencieusement perdues par read_canonical_csv() ci-dessus — comportement voulu pour
    LocalCsvMarketDataSource, pas pour ce cas d'usage).
    """
    df, error = _read_and_check_required_columns(path)
    if df is None:
        return CsvReadOutcome(dataframe=None, ok=False, message=error)
    return CsvReadOutcome(dataframe=df, ok=True, message="OK")
