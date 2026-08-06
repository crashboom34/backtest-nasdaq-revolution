"""
market_data/eodhd/config.py — Configuration du connecteur REST EODHD.

Résout la clé API via market_data.provider_config (variable d'environnement en priorité, sinon
settings/data_providers.json — mécanisme EODHD existant conservé tel quel). Ne fait aucun appel
réseau. EodhdConfig ne révèle jamais api_key dans repr()/str().
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from market_data.provider_config import DEFAULT_PROVIDER_SETTINGS_PATH, get_api_key

from .errors import EodhdConfigError

DEFAULT_BASE_URL = "https://eodhd.com/api"

# Identification explicite de l'appelant auprès d'EODHD (contrainte "User-Agent explicite").
DEFAULT_USER_AGENT = (
    "backtest-nasdaq-revolution-eodhd-connector/1.0 "
    "(+https://github.com/crashboom34/backtest-nasdaq-revolution)"
)


@dataclass(frozen=True)
class EodhdConfig:
    """Configuration résolue du connecteur EODHD — ne contient jamais la clé en clair dans
    repr()/str() (voir __repr__)."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    connect_timeout: float = 5.0
    read_timeout: float = 20.0
    max_retries: int = 3
    backoff_factor: float = 1.5
    user_agent: str = DEFAULT_USER_AGENT
    # Garde-fou générique : aucune réponse ne doit dépasser cette taille (contrainte "limite de
    # taille des réponses"). 25 Mo est largement suffisant pour un CSV/JSON EODHD raisonnable.
    max_response_bytes: int = 25_000_000
    # Garde-fou générique : nombre maximal de fenêtres pour un téléchargement découpé (intraday).
    max_windows_per_download: int = 50

    def __repr__(self) -> str:  # noqa: D105 — volontairement redigé
        return (
            f"EodhdConfig(api_key=set, base_url={self.base_url!r}, "
            f"connect_timeout={self.connect_timeout}, read_timeout={self.read_timeout}, "
            f"max_retries={self.max_retries})"
        )


def load_eodhd_config(
    path: Union[str, Path] = DEFAULT_PROVIDER_SETTINGS_PATH,
    **overrides,
) -> EodhdConfig:
    """Construit un EodhdConfig à partir de la clé API résolue (env puis fichier local).

    Lève EodhdConfigError si aucune clé n'est configurée — message explicite, jamais la valeur
    d'un secret puisqu'il n'y en a justement pas encore.
    """
    api_key = get_api_key("eodhd", path=path)
    if not api_key:
        raise EodhdConfigError(
            "Aucune clé API EODHD configurée. Définis la variable d'environnement "
            "BACKTEST_EODHD_API_KEY, ou utilise market_data.provider_config.save_api_key('eodhd', ...)."
        )
    return EodhdConfig(api_key=api_key, **overrides)


def config_from_api_key(api_key: str, **overrides) -> EodhdConfig:
    """Construit un EodhdConfig directement depuis une clé déjà en main (ex. tests, script
    utilisant --api-token explicite). Lève EodhdConfigError si la clé est vide."""
    if not api_key or not api_key.strip():
        raise EodhdConfigError("La clé API EODHD ne peut pas être vide.")
    return EodhdConfig(api_key=api_key.strip(), **overrides)
