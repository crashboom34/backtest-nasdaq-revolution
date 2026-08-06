"""
market_data/ig/client.py — IgClient : point d'entrée public du connecteur IG (démo, lecture seule).

Endpoints, en-têtes VERSION et formats confirmés par recoupement documentation officielle IG
Labs + bibliothèque de référence trading-ig le 2026-08-06 (voir AI_HANDOFF.md) :
  - POST /session (VERSION 2)                          — connexion, renvoie CST/X-SECURITY-TOKEN
  - DELETE /session (VERSION 1)                        — déconnexion
  - GET /accounts (VERSION 1)                           — liste des comptes
  - GET /markets?searchTerm=... (VERSION 1)             — recherche de marchés
  - GET /markets/{epic} (VERSION 3)                     — détails d'un marché
  - GET /prices/{epic}/{resolution}/{start}/{end} (VERSION 2) — historique de prix

AUCUNE fonction de trading n'existe ici, structurellement : /positions, /workingorders et toute
autre route d'écriture IG ne sont tout simplement pas câblées dans ce module (voir
test_igclient_public_surface_is_exactly_the_expected_read_only_methods côté tests).

Les tokens de session (CST, X-SECURITY-TOKEN) restent en mémoire via IgHttpClient — jamais
écrits sur disque par ce module. logout() les efface même si l'appel réseau de déconnexion
échoue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import pandas as pd

from .config import IgConfig
from .errors import IgError
from .http_client import IgHttpClient
from .normalize import normalize_price_records

# Résolutions IG confirmées (bibliothèque de référence trading-ig, voir AI_HANDOFF.md) — toute
# autre valeur est refusée avant le moindre appel réseau (pas de résolution devinée).
VALID_RESOLUTIONS: frozenset = frozenset(
    {
        "SECOND", "MINUTE", "MINUTE_2", "MINUTE_3", "MINUTE_5", "MINUTE_10", "MINUTE_15",
        "MINUTE_30", "HOUR", "HOUR_2", "HOUR_3", "HOUR_4", "DAY", "WEEK", "MONTH",
    }
)


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class IgLoginResult:
    ok: bool
    message: str
    account_id: Optional[str]


@dataclass(frozen=True)
class IgAccount:
    account_id: Optional[str]
    account_name: Optional[str]
    account_type: Optional[str]
    preferred: Optional[bool]


@dataclass(frozen=True)
class IgPricesResult:
    epic: str
    dataframe: Optional[pd.DataFrame]
    raw_records: Optional[list]
    ok: bool
    message: str


def _quote(value: str) -> str:
    """Encodage RFC 3986 d'un segment de chemin. Nécessaire pour les dates IG (contiennent '/'
    et ':') afin de ne pas corrompre le routage du chemin — voir tests/test_ig_client.py."""
    return quote(str(value), safe="")


class IgClient:
    """Connecteur IG démo, lecture seule. Aucun appel réseau avant le premier appel de méthode."""

    def __init__(self, config: IgConfig, http_client: Optional[IgHttpClient] = None):
        self._config = config
        self._http = http_client or IgHttpClient(config)
        self._account_id: Optional[str] = config.account_id

    def login(self) -> IgLoginResult:
        """Ouvre une session IG démo. Découvre l'account_id depuis la réponse si
        BACKTEST_IG_ACCOUNT_ID n'était pas déjà configuré explicitement."""
        body = {"identifier": self._config.identifier, "password": self._config.password}
        try:
            response_json, response_headers = self._http.request(
                "POST", "/session", version="2", json_body=body, include_auth=False
            )
        except IgError as exc:
            return IgLoginResult(ok=False, message=f"Connexion IG démo échouée : {exc}", account_id=None)

        cst = response_headers.get("CST")
        token = response_headers.get("X-SECURITY-TOKEN")
        if not cst or not token:
            return IgLoginResult(
                ok=False,
                message="Réponse de connexion IG incomplète (tokens de session absents).",
                account_id=None,
            )

        self._http.set_session_tokens(cst, token)
        discovered_account_id = self._config.account_id or response_json.get("currentAccountId")
        self._account_id = discovered_account_id
        return IgLoginResult(ok=True, message="Connexion IG démo réussie.", account_id=discovered_account_id)

    def logout(self) -> None:
        """Ferme la session IG. Les tokens sont effacés de la mémoire même si l'appel réseau de
        déconnexion échoue — jamais de token qui traîne après logout()."""
        try:
            if self._http.authenticated:
                self._http.request("DELETE", "/session", version="1")
        except IgError:
            pass
        finally:
            self._http.clear_session_tokens()

    def test_connection(self) -> ConnectionTestResult:
        """login() puis un appel de lecture minimal (GET /accounts), puis logout() systématique."""
        login = self.login()
        if not login.ok:
            return ConnectionTestResult(ok=False, message=login.message)
        try:
            self.get_accounts()
        except IgError as exc:
            self.logout()
            return ConnectionTestResult(ok=False, message=f"Connexion IG démo échouée : {exc}")
        self.logout()
        return ConnectionTestResult(ok=True, message="Connexion IG démo réussie.")

    def get_accounts(self) -> list:
        body, _ = self._http.request("GET", "/accounts", version="1")
        accounts = body.get("accounts") or []
        return [
            IgAccount(
                account_id=a.get("accountId"),
                account_name=a.get("accountName"),
                account_type=a.get("accountType"),
                preferred=a.get("preferred"),
            )
            for a in accounts
        ]

    def discover_account_id(self) -> Optional[str]:
        """BACKTEST_IG_ACCOUNT_ID s'il était configuré, sinon l'account_id découvert par
        login() (currentAccountId de la réponse de session). None si login() n'a pas encore été
        appelé et qu'aucun account_id n'était configuré."""
        return self._account_id

    def search_markets(self, search_term: str) -> list:
        body, _ = self._http.request("GET", "/markets", version="1", params={"searchTerm": search_term})
        return body.get("markets") or []

    def get_market_details(self, epic: str) -> dict:
        body, _ = self._http.request("GET", f"/markets/{_quote(epic)}", version="3")
        return body

    def get_prices(self, epic: str, resolution: str, start: str, end: str) -> IgPricesResult:
        """Historique de prix en lecture seule pour une petite période récente.

        `resolution` doit être l'une des valeurs IG confirmées (voir VALID_RESOLUTIONS) — une
        valeur inconnue est refusée avant tout appel réseau. `start`/`end` au format IG
        "%Y/%m/%d %H:%M:%S" (voir market_data.ig.normalize).
        """
        if resolution not in VALID_RESOLUTIONS:
            raise ValueError(
                f"Résolution IG non reconnue : {resolution!r} (valides : {sorted(VALID_RESOLUTIONS)})."
            )

        path = f"/prices/{_quote(epic)}/{_quote(resolution)}/{_quote(start)}/{_quote(end)}"
        try:
            body, _ = self._http.request("GET", path, version="2")
            records = body.get("prices") or []
            dataframe = normalize_price_records(records)
        except IgError as exc:
            return IgPricesResult(epic=epic, dataframe=None, raw_records=None, ok=False, message=str(exc))

        return IgPricesResult(
            epic=epic,
            dataframe=dataframe,
            raw_records=records,
            ok=True,
            message=f"{len(dataframe)} bougie(s) reçue(s) pour {epic}.",
        )
