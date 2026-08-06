"""
market_data/eodhd/client.py — EodhdClient : point d'entrée public du connecteur REST EODHD.

Assemble config (config.py), transport (http_client.py), découpage de fenêtres (windowing.py)
et normalisation (normalize.py) derrière une interface simple. N'effectue aucun appel réseau à
l'import ni à la construction — seulement quand une méthode est explicitement appelée.

Les endpoints, paramètres et limites utilisés ici ont été vérifiés via le MCP EODHD et la
documentation officielle le 2026-08-06 (voir AI_HANDOFF.md) :
  - GET /user                                  (compte / quota)
  - GET /search/{query}                        (recherche d'instruments)
  - GET /exchanges-list/                        (liste des places de marché)
  - GET /exchange-symbol-list/{EXCHANGE_CODE}   (symboles d'une place, dont radiés via delisted)
  - GET /eod/{TICKER}                           (historique quotidien/hebdo/mensuel)
  - GET /intraday/{TICKER}                      (historique intraday, fenêtré)
  - GET /div/{TICKER}                           (dividendes)
  - GET /splits/{TICKER}                        (splits)

Aucune fonction de trading, d'écriture ou de modification n'existe dans ce module : EODHD est un
fournisseur de données, uniquement consommé en lecture.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from .config import EodhdConfig
from .errors import EodhdError, EodhdWindowLimitError
from .http_client import EodhdHttpClient
from .normalize import (
    normalize_dividend_records,
    normalize_eod_records,
    normalize_intraday_records,
    normalize_split_records,
)
from .windowing import split_intraday_windows


@dataclass(frozen=True)
class ConnectionTestResult:
    """Résultat de test_connection() — jamais de secret dans `message`."""

    ok: bool
    message: str


@dataclass(frozen=True)
class EodhdAccountStatus:
    """Statut de compte/quota EODHD — ne contient volontairement PAS le nom ni l'email du
    titulaire du compte, même si /user les renvoie (ce ne sont pas des secrets techniques, mais
    des informations personnelles sans utilité pour le Data Center)."""

    subscription_type: Optional[str]
    subscription_mode: Optional[str]
    api_requests_today: Optional[int]
    api_requests_date: Optional[str]
    daily_rate_limit: Optional[int]
    extra_limit: Optional[int]


@dataclass(frozen=True)
class EodhdDownloadResult:
    """Résultat d'un téléchargement (EOD, intraday, dividendes ou splits)."""

    ticker: str
    dataframe: Optional[pd.DataFrame]
    raw_records: Optional[list]
    ok: bool
    message: str
    windows_fetched: int = 1


def _to_utc_unix(value: datetime) -> int:
    """Convertit un datetime en secondes Unix UTC. Un datetime naïf est supposé déjà en UTC
    (convention documentée sur download_intraday)."""
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return int(aware.astimezone(timezone.utc).timestamp())


def _without_none(params: dict) -> dict:
    return {k: v for k, v in params.items() if v is not None}


class EodhdClient:
    """Connecteur REST EODHD — lecture seule, aucun appel réseau avant le premier appel de
    méthode."""

    def __init__(self, config: EodhdConfig, http_client: Optional[EodhdHttpClient] = None):
        self._config = config
        self._http = http_client or EodhdHttpClient(config)

    # ------------------------------------------------------------------ compte / connexion --

    def test_connection(self) -> ConnectionTestResult:
        """Vérifie que la clé API fonctionne avec un appel minimal (GET /user, 1 appel API)."""
        try:
            self._http.get_json("/user")
        except EodhdError as exc:
            return ConnectionTestResult(ok=False, message=f"Connexion EODHD échouée : {exc}")
        return ConnectionTestResult(ok=True, message="Connexion EODHD réussie.")

    def get_account_status(self) -> EodhdAccountStatus:
        """Statut de quota/abonnement (GET /user, 1 appel API) — jamais de PII ni de secret."""
        payload = self._http.get_json("/user")
        return EodhdAccountStatus(
            subscription_type=payload.get("subscriptionType"),
            subscription_mode=payload.get("subscriptionMode"),
            api_requests_today=payload.get("apiRequests"),
            api_requests_date=payload.get("apiRequestsDate"),
            daily_rate_limit=payload.get("dailyRateLimit"),
            extra_limit=payload.get("extraLimit"),
        )

    # ------------------------------------------------------------------------- découverte --

    def search_instruments(
        self,
        query: str,
        *,
        limit: int = 15,
        exchange: Optional[str] = None,
        type: Optional[str] = None,  # noqa: A002 — nom aligné sur le paramètre EODHD documenté
        bonds_only: Optional[bool] = None,
    ) -> list:
        params = _without_none(
            {
                "limit": limit,
                "exchange": exchange,
                "type": type,
                "bonds_only": (1 if bonds_only else None) if bonds_only is not None else None,
            }
        )
        return self._http.get_json(f"/search/{query}", params=params)

    def list_exchanges(self) -> list:
        return self._http.get_json("/exchanges-list/")

    def get_exchange_details(
        self,
        exchange_code: str,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """Métadonnées d'une place de marché : fuseau horaire, heures de séance, jours fériés,
        fermetures anticipées, isOpen (voir market_data.eodhd.calendar pour une version
        structurée). `start_date`/`end_date` (YYYY-MM-DD) filtrent la fenêtre des jours fériés
        retournés."""
        params = _without_none({"from": start_date, "to": end_date})
        return self._http.get_json(f"/exchange-details/{exchange_code}", params=params)

    def list_exchange_symbols(
        self,
        exchange_code: str,
        *,
        delisted: bool = False,
        type: Optional[str] = None,  # noqa: A002
    ) -> list:
        """Symboles d'une place de marché. `delisted=True` renvoie uniquement les titres radiés
        (comportement documenté par EODHD : "Set to 1 to return inactive tickers only")."""
        params = _without_none({"delisted": 1 if delisted else None, "type": type})
        return self._http.get_json(f"/exchange-symbol-list/{exchange_code}", params=params)

    # ------------------------------------------------------------------------ téléchargements --

    def download_eod(
        self,
        ticker: str,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: str = "d",
    ) -> EodhdDownloadResult:
        """Historique quotidien/hebdomadaire/mensuel. start_date/end_date au format YYYY-MM-DD."""
        params = _without_none({"period": period, "from": start_date, "to": end_date})
        return self._fetch_and_normalize(f"/eod/{ticker}", params, normalize_eod_records, ticker, "bougie(s) EOD")

    def download_intraday(
        self,
        ticker: str,
        *,
        interval: str = "1m",
        start: datetime,
        end: datetime,
        max_windows: Optional[int] = None,
    ) -> EodhdDownloadResult:
        """Historique intraday, découpé automatiquement selon les fenêtres autorisées par EODHD
        pour cet intervalle (voir market_data.eodhd.windowing). `start`/`end` naïfs sont
        supposés déjà en UTC.

        Lève EodhdWindowLimitError ou ValueError avant tout appel réseau si la période demandée
        est invalide ou nécessiterait un nombre de fenêtres excessif (garde-fou explicite).
        """
        limit = max_windows if max_windows is not None else self._config.max_windows_per_download
        windows = split_intraday_windows(start, end, interval, max_windows=limit)

        all_records: list = []
        fetched = 0
        try:
            for window in windows:
                params = {
                    "interval": interval,
                    "from": _to_utc_unix(window.start),
                    "to": _to_utc_unix(window.end),
                }
                records = self._http.get_json(f"/intraday/{ticker}", params=params)
                all_records.extend(records)
                fetched += 1
            dataframe = normalize_intraday_records(all_records)
        except EodhdError as exc:
            return EodhdDownloadResult(
                ticker=ticker, dataframe=None, raw_records=None, ok=False,
                message=str(exc), windows_fetched=fetched,
            )

        return EodhdDownloadResult(
            ticker=ticker,
            dataframe=dataframe,
            raw_records=all_records,
            ok=True,
            message=f"{len(dataframe)} bougie(s) intraday téléchargée(s) en {fetched} fenêtre(s).",
            windows_fetched=fetched,
        )

    def download_dividends(
        self, ticker: str, *, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> EodhdDownloadResult:
        params = _without_none({"from": start_date, "to": end_date})
        return self._fetch_and_normalize(
            f"/div/{ticker}", params, normalize_dividend_records, ticker, "dividende(s)"
        )

    def download_splits(
        self, ticker: str, *, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> EodhdDownloadResult:
        params = _without_none({"from": start_date, "to": end_date})
        return self._fetch_and_normalize(
            f"/splits/{ticker}", params, normalize_split_records, ticker, "split(s)"
        )

    # ------------------------------------------------------------------------------- interne --

    def _fetch_and_normalize(self, path, params, normalize_fn, ticker, success_label) -> EodhdDownloadResult:
        try:
            records = self._http.get_json(path, params=params)
            dataframe = normalize_fn(records)
        except EodhdError as exc:
            return EodhdDownloadResult(ticker=ticker, dataframe=None, raw_records=None, ok=False, message=str(exc))
        return EodhdDownloadResult(
            ticker=ticker,
            dataframe=dataframe,
            raw_records=records,
            ok=True,
            message=f"{len(dataframe)} {success_label} téléchargé(s).",
        )
