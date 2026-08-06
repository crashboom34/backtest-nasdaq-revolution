"""
market_data/ig/errors.py — Hiérarchie d'erreurs du connecteur IG.

Règle absolue : aucun message d'erreur ne doit jamais contenir api_key, identifier, password,
CST ou X-SECURITY-TOKEN.
"""

from __future__ import annotations


class IgError(Exception):
    """Base de toutes les erreurs du connecteur IG."""


class IgConfigError(IgError):
    """Configuration invalide ou incomplète (identifiants manquants)."""


class IgEnvironmentRefusedError(IgError):
    """BACKTEST_IG_ENVIRONMENT n'est pas exactement 'demo' — levée avant tout appel réseau.

    C'est la garde de sécurité la plus importante de ce package : voir CLAUDE.md, section
    "SÉCURITÉ IG IMPÉRATIVE"."""


class IgNetworkError(IgError):
    """Erreur réseau (timeout, connexion impossible)."""


class IgHttpError(IgError):
    """Base des erreurs HTTP avec code de statut."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class IgAuthError(IgHttpError):
    """HTTP 401 — identifiants refusés ou session expirée."""


class IgForbiddenError(IgHttpError):
    """HTTP 403 — action non autorisée pour ce compte/cette clé API."""


class IgNotFoundError(IgHttpError):
    """HTTP 404 — ressource introuvable (EPIC, endpoint...)."""


class IgRateLimitError(IgHttpError):
    """HTTP 429 — quota ou débit dépassé."""


class IgServerError(IgHttpError):
    """HTTP 5xx — erreur côté serveur IG, potentiellement transitoire."""


class IgResponseError(IgError):
    """Réponse reçue mais de forme inattendue (JSON invalide, champs manquants)."""


class IgSessionError(IgError):
    """Session IG absente ou invalide au moment d'un appel qui en a besoin."""
