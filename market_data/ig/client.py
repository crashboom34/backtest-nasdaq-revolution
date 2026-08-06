"""
market_data/ig/client.py — IgClient : point d'entrée public du connecteur IG (démo, lecture seule).

Endpoints, en-têtes VERSION et formats confirmés par recoupement documentation officielle IG
Labs + bibliothèque de référence trading-ig (voir AI_HANDOFF.md) :
  - POST /session (VERSION 2)                          — connexion, renvoie CST/X-SECURITY-TOKEN
  - DELETE /session (VERSION 1)                        — déconnexion
  - GET /accounts (VERSION 1)                           — liste des comptes
  - GET /markets?searchTerm=... (VERSION 1)             — recherche de marchés
  - GET /markets/{epic} (VERSION 3)                     — détails d'un marché
  - GET /prices/{epic} (VERSION 3), params resolution/from/to/max — historique de prix
    (2026-08-06 : corrige l'ancienne forme VERSION 2 /prices/{epic}/{resolution}/{start}/{end},
    qui produisait un HTTP 400 — voir AI_HANDOFF.md pour le diagnostic complet)

AUCUNE fonction de trading n'existe ici, structurellement : /positions, /workingorders et toute
autre route d'écriture IG ne sont tout simplement pas câblées dans ce module (voir
test_igclient_public_surface_is_exactly_the_expected_read_only_methods côté tests).

Les tokens de session (CST, X-SECURITY-TOKEN) restent en mémoire via IgHttpClient — jamais
écrits sur disque par ce module. logout() les efface même si l'appel réseau de déconnexion
échoue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import pandas as pd

from .config import IgConfig
from .errors import IgError, IgHttpError
from .http_client import IgHttpClient
from .normalize import normalize_price_records

# Format de date exigé par IG pour les paramètres de requête from/to de GET /prices/{epic}
# (VERSION 3) : yyyy-MM-dd'T'HH:mm:ss — confirmé par la documentation officielle IG et
# recoupement indépendant (2026-08-06, voir AI_HANDOFF.md). Ne pas confondre avec le format de
# snapshotTime dans la RÉPONSE (voir market_data.ig.normalize, inchangé).
_REQUEST_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

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
    """`status_code`/`error_code` : uniquement le statut HTTP et le champ IG "errorCode" déjà
    extrait (voir market_data.ig.http_client.extract_ig_error_code()) — jamais un secret, jamais
    le corps de réponse complet. Absents (None) si l'échec n'est pas une erreur HTTP IG (ex.
    identifiants manquants, environnement refusé, timeout réseau)."""

    ok: bool
    message: str
    status_code: Optional[int] = None
    error_code: Optional[str] = None


@dataclass(frozen=True)
class IgLoginResult:
    """Voir ConnectionTestResult pour la portée de status_code/error_code."""

    ok: bool
    message: str
    account_id: Optional[str]
    status_code: Optional[int] = None
    error_code: Optional[str] = None


@dataclass(frozen=True)
class IgAccount:
    account_id: Optional[str]
    account_name: Optional[str]
    account_type: Optional[str]
    preferred: Optional[bool]


@dataclass(frozen=True)
class IgPricesResult:
    """Voir ConnectionTestResult pour la portée de status_code/error_code."""

    epic: str
    dataframe: Optional[pd.DataFrame]
    raw_records: Optional[list]
    ok: bool
    message: str
    status_code: Optional[int] = None
    error_code: Optional[str] = None


def _quote(value: str) -> str:
    """Encodage RFC 3986 d'un segment de chemin (ex. l'EPIC dans /prices/{epic})."""
    return quote(str(value), safe="")


def _is_positive_int(value) -> bool:
    """True si `value` est un entier strictement positif (bool exclu : `isinstance(True, int)`
    vaut True en Python, ce qui accepterait silencieusement max_points=True)."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _error_details(exc: IgError) -> tuple:
    """(status_code, error_code) d'une IgError si c'est une IgHttpError, sinon (None, None) —
    factorise la lecture répétée dans login()/test_connection()/get_prices(). Vérifie le type
    explicitement (pas de duck-typing par attribut) : seule IgHttpError et ses sous-classes
    portent status_code/error_code (voir errors.py)."""
    if isinstance(exc, IgHttpError):
        return exc.status_code, exc.error_code
    return None, None


def _parse_request_date(value: str) -> Optional[datetime]:
    """Parse une date de requête IG (format _REQUEST_DATE_FORMAT). Retourne None si `value` ne
    respecte pas exactement ce format — la validation de format elle-même reste la
    responsabilité d'IG (HTTP 400 explicite) ; ce parseur ne sert qu'aux contrôles applicatifs
    (plage inversée, date future) quand le format est bien celui attendu."""
    try:
        return datetime.strptime(value, _REQUEST_DATE_FORMAT)
    except (ValueError, TypeError):
        return None


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
            status_code, error_code = _error_details(exc)
            return IgLoginResult(
                ok=False,
                message=f"Connexion IG démo échouée : {exc}",
                account_id=None,
                status_code=status_code,
                error_code=error_code,
            )

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
            return ConnectionTestResult(
                ok=False, message=login.message,
                status_code=login.status_code, error_code=login.error_code,
            )
        try:
            self.get_accounts()
        except IgError as exc:
            self.logout()
            status_code, error_code = _error_details(exc)
            return ConnectionTestResult(
                ok=False,
                message=f"Connexion IG démo échouée : {exc}",
                status_code=status_code,
                error_code=error_code,
            )
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

    def get_prices(
        self,
        epic: str,
        resolution: str,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
        max_points: Optional[int] = None,
    ) -> IgPricesResult:
        """Historique de prix en lecture seule pour une petite période récente.

        Utilise `GET /prices/{epic}` (VERSION 3), confirmé par la documentation officielle IG
        (voir AI_HANDOFF.md, 2026-08-06) — remplace l'ancienne forme VERSION 2
        `/prices/{epic}/{resolution}/{start}/{end}`, qui produisait un HTTP 400.

        `resolution` doit être l'une des valeurs IG confirmées (voir VALID_RESOLUTIONS) — une
        valeur inconnue est refusée avant tout appel réseau.

        `start`/`end` sont optionnels, au format IG "%Y-%m-%dT%H:%M:%S" (yyyy-MM-dd'T'HH:mm:ss —
        différent du format de snapshotTime dans la réponse, voir market_data.ig.normalize).
        `max_points` (optionnel) limite le nombre de bougies retournées — utile pour une requête
        minimale sans plage de dates. Toutes les validations ci-dessous s'exécutent avant le
        moindre appel réseau :
          - résolution reconnue ;
          - max_points entier strictement positif si fourni ;
          - start < end si les deux sont fournis et au format attendu ;
          - end n'est pas dans le futur, si fourni et au format attendu.
        """
        if resolution not in VALID_RESOLUTIONS:
            raise ValueError(
                f"Résolution IG non reconnue : {resolution!r} (valides : {sorted(VALID_RESOLUTIONS)})."
            )
        if max_points is not None and not _is_positive_int(max_points):
            raise ValueError(f"max_points doit être un entier strictement positif, reçu : {max_points!r}.")

        parsed_start = _parse_request_date(start) if start else None
        parsed_end = _parse_request_date(end) if end else None
        if parsed_start and parsed_end and parsed_start >= parsed_end:
            raise ValueError(f"Plage de dates invalide : start ({start!r}) doit être strictement antérieur à end ({end!r}).")
        if parsed_end and parsed_end > datetime.now(timezone.utc).replace(tzinfo=None):
            raise ValueError(f"end ({end!r}) ne peut pas être dans le futur.")

        params = {"resolution": resolution}
        if start is not None:
            params["from"] = start
        if end is not None:
            params["to"] = end
        if max_points is not None:
            params["max"] = max_points

        try:
            body, _ = self._http.request("GET", f"/prices/{_quote(epic)}", version="3", params=params)
            records = body.get("prices") or []
            dataframe = normalize_price_records(records)
        except IgError as exc:
            status_code, error_code = _error_details(exc)
            return IgPricesResult(
                epic=epic, dataframe=None, raw_records=None, ok=False, message=str(exc),
                status_code=status_code, error_code=error_code,
            )

        return IgPricesResult(
            epic=epic,
            dataframe=dataframe,
            raw_records=records,
            ok=True,
            message=f"{len(dataframe)} bougie(s) reçue(s) pour {epic}.",
        )
