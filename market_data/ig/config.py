"""
market_data/ig/config.py — Configuration du connecteur IG, strictement démo.

Résout les identifiants via market_data.provider_config.get_ig_credentials() (mot de passe
env-only, jamais depuis settings/data_providers.json). Base URL démo officielle codée en dur,
JAMAIS paramétrable depuis l'extérieur — voir CLAUDE.md : "ne jamais accepter une URL IG
arbitraire fournie par l'utilisateur", "autoriser uniquement la base URL démo officielle".

L'environnement est vérifié ICI, avant toute construction de client HTTP : environment doit
valoir exactement "demo" (insensible à la casse/espaces) ; toute autre valeur (vide, "live",
"prod", "production", ou n'importe quoi d'autre) lève IgEnvironmentRefusedError. Aucun appel
réseau n'est possible avant ce contrôle, car IgConfig ne peut pas être construit sans lui.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from market_data.provider_config import DEFAULT_PROVIDER_SETTINGS_PATH, get_ig_credentials

from .errors import IgConfigError, IgEnvironmentRefusedError

# Base URL démo officielle IG (confirmée via la documentation officielle IG Labs et la
# bibliothèque de référence trading-ig — voir AI_HANDOFF.md). La base URL live existe dans le
# code UNIQUEMENT en tant que constante de comparaison pour la détecter et la refuser -- elle
# n'est jamais assignable à IgConfig.base_url.
DEMO_BASE_URL = "https://demo-api.ig.com/gateway/deal"
_LIVE_BASE_URL = "https://api.ig.com/gateway/deal"  # jamais utilisée, uniquement pour référence

DEFAULT_USER_AGENT = (
    "backtest-nasdaq-revolution-ig-connector/1.0 "
    "(+https://github.com/crashboom34/backtest-nasdaq-revolution) demo-only-read-only"
)

_ALLOWED_ENVIRONMENT = "demo"
_EXPLICITLY_REFUSED_ENVIRONMENTS = ("live", "prod", "production")


@dataclass(frozen=True)
class IgConfig:
    """Configuration résolue du connecteur IG — ne contient jamais de secret dans repr()/str().

    base_url n'est volontairement PAS un paramètre du constructeur exposé par load_ig_config() :
    il vaut toujours DEMO_BASE_URL (voir docstring du module).
    """

    api_key: str
    identifier: str
    password: str
    account_id: Optional[str]
    base_url: str = DEMO_BASE_URL
    connect_timeout: float = 5.0
    read_timeout: float = 20.0
    max_retries: int = 3
    backoff_factor: float = 1.5
    user_agent: str = DEFAULT_USER_AGENT

    def __post_init__(self):
        # Filet de sécurité supplémentaire : même une construction directe et malveillante de
        # IgConfig(base_url=...) avec l'URL live est refusée ici, pas seulement dans
        # load_ig_config(). Défense en profondeur.
        if self.base_url != DEMO_BASE_URL:
            raise IgEnvironmentRefusedError(
                "IgConfig.base_url doit être l'URL démo officielle IG — toute autre valeur "
                "(y compris l'URL live) est refusée avant tout appel réseau."
            )

    def __repr__(self) -> str:  # noqa: D105 — volontairement redigé
        return (
            f"IgConfig(api_key=set, identifier=set, password=set, "
            f"account_id={'set' if self.account_id else 'unset'}, base_url={self.base_url!r})"
        )


def _normalize_environment(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def load_ig_config(
    path: Union[str, Path] = DEFAULT_PROVIDER_SETTINGS_PATH,
    **overrides,
) -> IgConfig:
    """Construit un IgConfig à partir des identifiants IG résolus.

    Lève IgEnvironmentRefusedError si BACKTEST_IG_ENVIRONMENT n'est pas exactement "demo"
    (vide, "live", "prod", "production", ou toute autre valeur) — AVANT tout appel réseau.
    Lève IgConfigError si api_key/identifier/password sont incomplets.
    """
    creds = get_ig_credentials(path=path)
    env = _normalize_environment(creds.environment)

    if env in _EXPLICITLY_REFUSED_ENVIRONMENTS:
        raise IgEnvironmentRefusedError(
            f"BACKTEST_IG_ENVIRONMENT={creds.environment!r} refusé : ce connecteur n'autorise "
            "que l'environnement 'demo'. Aucune connexion à l'environnement live n'est possible."
        )
    if env != _ALLOWED_ENVIRONMENT:
        raise IgEnvironmentRefusedError(
            "BACKTEST_IG_ENVIRONMENT doit valoir exactement 'demo' (absent ou vide refusé pour "
            f"un test réel). Valeur actuelle : {creds.environment!r}."
        )

    missing = [
        name
        for name, value in (("api_key", creds.api_key), ("identifier", creds.identifier), ("password", creds.password))
        if not value
    ]
    if missing:
        raise IgConfigError(
            "Identifiants IG incomplets, champs manquants : " + ", ".join(missing) + ". "
            "Définis BACKTEST_IG_API_KEY, BACKTEST_IG_IDENTIFIER et BACKTEST_IG_PASSWORD "
            "(mot de passe : variable d'environnement uniquement)."
        )

    return IgConfig(
        api_key=creds.api_key,
        identifier=creds.identifier,
        password=creds.password,
        account_id=creds.account_id,
        **overrides,
    )
