"""
market_data/ig/error_codes.py — Explications lisibles des errorCode IG confirmés.

IG renvoie parfois un corps JSON `{"errorCode": "..."}` sur les réponses d'erreur (401/403/...).
Seuls les codes ci-dessous ont été confirmés par recoupement de la documentation IG Labs et de
la communauté ig-python/trading-ig (voir AI_HANDOFF.md) — jamais un code ni une explication
inventés. Un code absent de cette table renvoie un message générique invitant à consulter la
documentation officielle plutôt qu'une explication devinée.

Ce module ne contient aucune logique réseau et ne manipule jamais un corps de réponse complet :
il se contente d'expliquer un code déjà extrait ailleurs (voir
market_data.ig.http_client.extract_ig_error_code()).
"""

from __future__ import annotations

from typing import Optional

# Codes confirmés (2026-08-06) — voir AI_HANDOFF.md pour les sources.
_KNOWN_IG_ERROR_CODES = {
    "error.security.api-key-invalid": (
        "Clé API invalide : l'identifiant et le mot de passe peuvent être corrects, mais la "
        "clé API (BACKTEST_IG_API_KEY) est incorrecte, ou ne correspond pas à ce compte/cet "
        "environnement démo."
    ),
    "error.security.invalid-details": "Identifiant ou mot de passe IG incorrect.",
    "error.public-api.exceeded-api-key-allowance": (
        "Quota d'appels API dépassé pour cette clé (limite atteinte) — réessaie plus tard."
    ),
}

_DEFAULT_EXPLANATION_NO_CODE = "Aucun code d'erreur IG (errorCode) présent dans la réponse."
_DEFAULT_EXPLANATION_UNKNOWN = (
    "Code IG non reconnu ({code!r}) — consulte la documentation officielle IG (labs.ig.com) "
    "pour ce code précis."
)


def explain_ig_error_code(error_code: Optional[str]) -> str:
    """Explication lisible d'un errorCode IG déjà extrait. Ne prend jamais un corps de réponse
    complet en paramètre — uniquement la chaîne de code déjà isolée en amont."""
    if not error_code:
        return _DEFAULT_EXPLANATION_NO_CODE
    known = _KNOWN_IG_ERROR_CODES.get(error_code)
    if known:
        return known
    return _DEFAULT_EXPLANATION_UNKNOWN.format(code=error_code)
