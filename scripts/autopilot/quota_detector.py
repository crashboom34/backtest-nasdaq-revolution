"""
scripts/autopilot/quota_detector.py — Classification prudente des échecs (Bootstrap V1, 2026-09-17).

Mission §13 : "Une limite Claude n'est jamais un Human Gate" mais "la détection doit être
prudente" — "Ne pas classer toute erreur réseau ou toute sortie inhabituelle comme limite de
quota". Heuristique par mots-clés, volontairement simple et documentée comme imparfaite — jamais
présentée comme un détecteur infaillible. Toute sortie non reconnue reste `UNKNOWN`, jamais
`QUOTA_LIMIT` par défaut."""

from __future__ import annotations

from enum import Enum


class FailureCategory(str, Enum):
    QUOTA_LIMIT = "QUOTA_LIMIT"
    NETWORK = "NETWORK"
    AUTH = "AUTH"
    CLI_ERROR = "CLI_ERROR"
    PROJECT_ERROR = "PROJECT_ERROR"
    CRASH = "CRASH"
    STOP_REQUESTED = "STOP_REQUESTED"
    UNKNOWN = "UNKNOWN"


_STOP_KEYWORDS = ("stop_requested",)
_QUOTA_KEYWORDS = (
    "usage limit", "rate_limit_error", "rate limit exceeded", "quota exceeded",
    "limite d'usage", "limit reached", "usage limit reached",
)
_AUTH_KEYWORDS = ("authentication_error", "invalid api key", "unauthorized", " 401 ", "401 unauthorized")
_NETWORK_KEYWORDS = (
    "connectionerror", "timeout", "getaddrinfo failed", "network is unreachable",
    "connection refused", "temporary failure in name resolution",
)
_CLI_KEYWORDS = (
    "command not found", "is not recognized as an internal or external command",
    "no such file or directory: 'claude'",
)
_CRASH_KEYWORDS = ("traceback (most recent call last)",)
_PROJECT_ERROR_KEYWORDS = ("assertionerror", "failed tests/", "pytest", " failed ")

# Ordre de vérification volontaire : STOP > QUOTA > AUTH > NETWORK > CLI > CRASH > PROJECT_ERROR
# > UNKNOWN — un arrêt explicite prime sur tout, un quota est vérifié avant un réseau générique
# (un message de quota peut mentionner "connection" en aparté sans être une vraie panne réseau).
_ORDERED_CATEGORIES = (
    (FailureCategory.STOP_REQUESTED, _STOP_KEYWORDS),
    (FailureCategory.QUOTA_LIMIT, _QUOTA_KEYWORDS),
    (FailureCategory.AUTH, _AUTH_KEYWORDS),
    (FailureCategory.NETWORK, _NETWORK_KEYWORDS),
    (FailureCategory.CLI_ERROR, _CLI_KEYWORDS),
    (FailureCategory.CRASH, _CRASH_KEYWORDS),
    (FailureCategory.PROJECT_ERROR, _PROJECT_ERROR_KEYWORDS),
)


def classify_failure(output_text: str) -> FailureCategory:
    """Classe un texte de sortie/erreur en catégorie. Retourne `UNKNOWN` pour tout texte vide ou
    non reconnu — jamais `QUOTA_LIMIT` par défaut (mission §13, prudence obligatoire)."""
    text = (output_text or "").lower()
    if not text:
        return FailureCategory.UNKNOWN
    for category, keywords in _ORDERED_CATEGORIES:
        if any(keyword in text for keyword in keywords):
            return category
    return FailureCategory.UNKNOWN
