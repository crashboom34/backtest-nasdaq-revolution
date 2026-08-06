"""
market_data/eodhd/errors.py — Hiérarchie d'erreurs du connecteur EODHD.

Règle absolue : aucun message d'erreur ne doit jamais contenir la clé API. Les fonctions qui
construisent des URLs pour les messages d'erreur doivent utiliser redact_url() ci-dessous.
"""

from __future__ import annotations

import re

_TOKEN_PATTERN = re.compile(r"(api_token=)[^&\s]+", re.IGNORECASE)


def redact_url(url: str) -> str:
    """Remplace la valeur de api_token par *** dans une URL, pour les logs/erreurs/messages."""
    return _TOKEN_PATTERN.sub(r"\1***", url)


class EodhdError(Exception):
    """Base de toutes les erreurs du connecteur EODHD."""


class EodhdConfigError(EodhdError):
    """Configuration invalide ou incomplète (ex. clé API absente)."""


class EodhdNetworkError(EodhdError):
    """Erreur réseau (timeout, connexion impossible) — enveloppe l'exception requests d'origine
    sans jamais inclure l'URL complète non-redigée."""


class EodhdHttpError(EodhdError):
    """Base des erreurs HTTP avec code de statut. `url` est toujours redigée (voir redact_url)."""

    def __init__(self, message: str, status_code: int, url: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.url = redact_url(url)


class EodhdAuthError(EodhdHttpError):
    """HTTP 401 — clé API absente, invalide ou révoquée."""


class EodhdForbiddenError(EodhdHttpError):
    """HTTP 403 — endpoint non inclus dans le plan d'abonnement, ou action refusée."""


class EodhdNotFoundError(EodhdHttpError):
    """HTTP 404 — symbole, exchange ou endpoint introuvable."""


class EodhdRateLimitError(EodhdHttpError):
    """HTTP 429 — quota ou débit dépassé. `retry_after` en secondes si l'en-tête est présent."""

    def __init__(self, message: str, status_code: int, url: str = "", retry_after: float | None = None):
        super().__init__(message, status_code, url)
        self.retry_after = retry_after


class EodhdServerError(EodhdHttpError):
    """HTTP 5xx — erreur côté serveur EODHD, potentiellement transitoire."""


class EodhdResponseError(EodhdError):
    """Réponse reçue mais de forme inattendue (JSON invalide, schéma inattendu, champs manquants)."""


class EodhdWindowLimitError(EodhdError):
    """Le nombre de fenêtres nécessaires pour couvrir la période demandée dépasse la limite de
    sécurité configurée — voir market_data.eodhd.windowing."""
