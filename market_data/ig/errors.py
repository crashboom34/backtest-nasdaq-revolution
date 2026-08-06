"""
market_data/ig/errors.py — Hiérarchie d'erreurs du connecteur IG.

Règle absolue : aucun message d'erreur ne doit jamais contenir api_key, identifier, password,
CST, X-SECURITY-TOKEN ou un token OAuth — ni le corps complet d'une requête ou d'une réponse.

IgHttpError porte un `error_code` optionnel : uniquement le champ "errorCode" du corps de
réponse IG, déjà isolé par market_data.ig.http_client.extract_ig_error_code() — jamais le reste
du corps. Voir market_data.ig.error_codes.explain_ig_error_code() pour son explication lisible.
"""

from __future__ import annotations

from typing import Optional


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
    """Base des erreurs HTTP avec code de statut.

    `error_code` : uniquement le champ "errorCode" isolé du corps de réponse IG (jamais le
    reste du corps) — voir market_data.ig.http_client.extract_ig_error_code(). Absent (None) si
    la réponse n'a pas de corps JSON exploitable ou pas de champ "errorCode".
    """

    def __init__(self, message: str, status_code: int, error_code: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class IgBadRequestError(IgHttpError):
    """HTTP 400 — requête malformée (paramètre invalide, format de date incorrect, plage de
    dates ou combinaison de paramètres non acceptée par IG...)."""


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


class IgUnexpectedStatusError(IgHttpError):
    """Tout code HTTP d'erreur non spécifiquement géré par les classes ci-dessus — toujours
    accompagné du statut et, si disponible, de errorCode (voir extract_ig_error_code())."""


class IgResponseError(IgError):
    """Réponse reçue mais de forme inattendue (JSON invalide, champs manquants)."""


class IgSessionError(IgError):
    """Session IG absente ou invalide au moment d'un appel qui en a besoin."""
