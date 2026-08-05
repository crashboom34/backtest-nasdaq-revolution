"""
market_data/schema.py — Schéma canonique interne des données de marché (Phase 1 — socle local).

Ce module ne contient aucune logique d'accès aux fichiers ni de connexion à un fournisseur.
Il définit uniquement la forme commune que doit respecter une donnée de marché une fois
normalisée, quel que soit le fournisseur d'origine (CSV local aujourd'hui ; EODHD, Dukascopy,
FirstRate, IG plus tard).

Portée volontairement réduite pour cette première étape (voir docs/adr/0002-...) :
- pas de bid/ask, pas de dividendes/splits, pas d'options ;
- ces champs seront ajoutés par des évolutions ultérieures du schéma, documentées dans de
  nouveaux ADR, sans jamais retirer ni renommer les colonnes de cette version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

# Colonnes attendues dans un DataFrame canonique. "volume" est optionnel côté fournisseur mais
# toujours présent dans le DataFrame normalisé (rempli à NA si inconnu), pour que tout code
# consommateur puisse compter dessus sans vérification préalable.
CANONICAL_COLUMNS: tuple[str, ...] = ("time", "open", "high", "low", "close", "volume")

REQUIRED_CANONICAL_COLUMNS: tuple[str, ...] = ("time", "open", "high", "low", "close")


@dataclass(frozen=True)
class MarketDatasetInfo:
    """Métadonnées légères décrivant un jeu de données de marché disponible ou préparé.

    Volontairement minimal pour cette étape : pas encore de catalogue persistant (période
    couverte, qualité, dernière synchro...) — ce sera l'objet d'une étape ultérieure du plan.
    """

    provider: str
    asset: str
    timeframe: str
    source: str  # "data" (data/{asset}/{timeframe}/), "legacy" (nasdaq_3m.csv) ou "missing"
    exists: bool
    relative_path: Optional[str] = None
    message: str = ""


@dataclass(frozen=True)
class MarketDataResult:
    """Résultat normalisé du chargement d'un jeu de données de marché."""

    info: MarketDatasetInfo
    dataframe: Optional[pd.DataFrame]  # colonnes CANONICAL_COLUMNS si ok=True, sinon None
    ok: bool
    message: str = ""


def validate_canonical_columns(df: pd.DataFrame) -> list[str]:
    """Retourne les colonnes obligatoires manquantes (volume exclu, il est optionnel)."""
    return [col for col in REQUIRED_CANONICAL_COLUMNS if col not in df.columns]
