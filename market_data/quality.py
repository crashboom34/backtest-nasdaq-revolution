"""
market_data/quality.py — Contrôle qualité basique d'un jeu de données de marché canonique.

Calcule des indicateurs simples sur un DataFrame déjà normalisé au schéma canonique
(market_data.schema.CANONICAL_COLUMNS). Ne modifie et ne "répare" jamais les données —
uniquement des constats chiffrés et des quality_flags explicites (voir la demande initiale,
section 11 : "ne jamais interpoler silencieusement les prix sans indiquer que la donnée a été
reconstruite" — ce module n'interpole rien du tout).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

_REQUIRED_COLUMNS = ("time", "open", "high", "low", "close")


@dataclass(frozen=True)
class QualityReport:
    """Rapport de qualité en lecture seule pour un DataFrame canonique."""

    row_count: int
    duplicate_timestamps: int
    invalid_ohlc: int  # lignes où high < low
    non_positive_prices: int
    missing_values: int
    out_of_order: bool
    quality_flags: tuple[str, ...]
    quality_score_pct: float


def analyze_quality(df: pd.DataFrame) -> QualityReport:
    """Analyse un DataFrame canonique et retourne un rapport de qualité.

    Lève ValueError si les colonnes obligatoires du schéma canonique sont absentes — ce n'est
    pas un problème de qualité de données, c'est un appel invalide de la fonction.
    """
    missing_columns = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        raise ValueError(
            "Colonnes canoniques manquantes pour l'analyse qualité : " + ", ".join(missing_columns) + "."
        )

    row_count = int(len(df))
    if row_count == 0:
        return QualityReport(
            row_count=0,
            duplicate_timestamps=0,
            invalid_ohlc=0,
            non_positive_prices=0,
            missing_values=0,
            out_of_order=False,
            quality_flags=("empty_dataset",),
            quality_score_pct=0.0,
        )

    working = df.copy()
    working["time"] = pd.to_datetime(working["time"])

    duplicate_timestamps = int(working["time"].duplicated().sum())
    invalid_ohlc = int((working["high"] < working["low"]).sum())
    price_cols = [c for c in ("open", "high", "low", "close") if c in working.columns]
    non_positive_prices = int((working[price_cols] <= 0).sum().sum())
    missing_values = int(working[list(_REQUIRED_COLUMNS)].isna().sum().sum())
    out_of_order = not bool(working["time"].is_monotonic_increasing)

    flags: list[str] = []
    if duplicate_timestamps:
        flags.append("duplicate_bar")
    if invalid_ohlc:
        flags.append("invalid_ohlc")
    if non_positive_prices:
        flags.append("non_positive_price")
    if missing_values:
        flags.append("missing_value")
    if out_of_order:
        flags.append("out_of_order")

    # Score simple : proportion de lignes touchées par une anomalie de structure (doublons ou
    # high < low). Volontairement grossier pour cette étape — un scoring plus fin (trous
    # pendant les heures de séance, outliers statistiques...) nécessite un calendrier de marché
    # qui n'existe pas encore (voir docs/adr/0003-timeframe-resampling-rules.md).
    anomalous_rows = duplicate_timestamps + invalid_ohlc
    quality_score_pct = round(max(0.0, 100.0 * (1 - anomalous_rows / row_count)), 1)

    return QualityReport(
        row_count=row_count,
        duplicate_timestamps=duplicate_timestamps,
        invalid_ohlc=invalid_ohlc,
        non_positive_prices=non_positive_prices,
        missing_values=missing_values,
        out_of_order=out_of_order,
        quality_flags=tuple(flags),
        quality_score_pct=quality_score_pct,
    )
