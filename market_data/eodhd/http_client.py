"""
market_data/eodhd/http_client.py — Client HTTP bas niveau pour l'API REST EODHD.

Responsabilités, et uniquement celles-ci :
  - construire la requête (URL, paramètres, en-têtes, timeouts) ;
  - retenter un nombre limité de fois avec backoff exponentiel sur erreurs réseau / 429 / 5xx ;
  - mapper les codes HTTP vers des exceptions explicites (voir errors.py) ;
  - garder une taille de réponse plafonnée ;
  - ne jamais laisser fuiter la clé API dans un message d'erreur (redact_url()).

Aucun appel réseau à l'import. `session` est injectable pour les tests (aucun test unitaire
n'utilise le vrai réseau) ; `sleep_fn` est injectable pour ne jamais ralentir la suite de tests
avec un vrai backoff.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

import requests

from .config import EodhdConfig
from .errors import (
    EodhdAuthError,
    EodhdForbiddenError,
    EodhdNetworkError,
    EodhdNotFoundError,
    EodhdRateLimitError,
    EodhdResponseError,
    EodhdServerError,
    redact_url,
)


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse l'en-tête Retry-After (secondes uniquement — EODHD ne documente pas le format
    HTTP-date pour cet en-tête). Valeur invalide ou absente -> None, jamais d'exception."""
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


class EodhdHttpClient:
    """Client HTTP bas niveau, un seul point d'entrée réseau pour tout le connecteur EODHD."""

    def __init__(
        self,
        config: EodhdConfig,
        session: Optional[requests.Session] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self._config = config
        self._session = session or requests.Session()
        self._sleep = sleep_fn

    def get_json(self, path: str, params: Optional[dict] = None) -> Any:
        """GET vers `{base_url}{path}`, retourne le JSON décodé. Lève une sous-classe de
        EodhdError explicite en cas d'échec (réseau, HTTP, réponse malformée)."""
        request_params = dict(params or {})
        request_params["api_token"] = self._config.api_key
        request_params.setdefault("fmt", "json")
        url = f"{self._config.base_url}{path}"
        headers = {"User-Agent": self._config.user_agent}
        timeout = (self._config.connect_timeout, self._config.read_timeout)

        last_error: Optional[Exception] = None
        for attempt in range(1, self._config.max_retries + 1):
            try:
                response = self._session.get(url, params=request_params, headers=headers, timeout=timeout)
            except requests.Timeout as exc:
                last_error = EodhdNetworkError(f"Timeout lors de l'appel EODHD ({redact_url(url)}).")
                if attempt < self._config.max_retries:
                    self._sleep(self._backoff_delay(attempt))
                    continue
                raise last_error from exc
            except requests.ConnectionError as exc:
                last_error = EodhdNetworkError(f"Connexion impossible à EODHD ({redact_url(url)}).")
                if attempt < self._config.max_retries:
                    self._sleep(self._backoff_delay(attempt))
                    continue
                raise last_error from exc

            outcome = self._handle_response(response, url, attempt)
            if outcome.retry:
                last_error = outcome.error
                self._sleep(outcome.delay or self._backoff_delay(attempt))
                continue
            if outcome.error is not None:
                raise outcome.error
            return outcome.payload

        # Ne devrait être atteint que si max_retries <= 0 (config invalide) — filet de sécurité.
        raise last_error or EodhdNetworkError(f"Échec de l'appel EODHD sans détail ({redact_url(url)}).")

    def _handle_response(self, response: requests.Response, url: str, attempt: int) -> "_Outcome":
        content_length = response.headers.get("Content-Length")
        if content_length and content_length.isdigit():
            if int(content_length) > self._config.max_response_bytes:
                response.close()
                return _Outcome(
                    error=EodhdResponseError(
                        f"Réponse EODHD trop volumineuse ({content_length} octets, "
                        f"limite {self._config.max_response_bytes}) pour {redact_url(url)}."
                    )
                )

        status = response.status_code

        if status == 200:
            content = response.content
            if len(content) > self._config.max_response_bytes:
                return _Outcome(
                    error=EodhdResponseError(
                        f"Réponse EODHD trop volumineuse ({len(content)} octets, "
                        f"limite {self._config.max_response_bytes}) pour {redact_url(url)}."
                    )
                )
            try:
                return _Outcome(payload=json.loads(content))
            except json.JSONDecodeError as exc:
                return _Outcome(
                    error=EodhdResponseError(f"JSON invalide reçu depuis {redact_url(url)} : {exc}")
                )

        if status == 401:
            return _Outcome(
                error=EodhdAuthError(
                    "Authentification refusée (401) — vérifie la clé API EODHD.", status, url
                )
            )
        if status == 403:
            return _Outcome(
                error=EodhdForbiddenError(
                    "Accès refusé (403) — endpoint non inclus dans le plan EODHD ou action non "
                    "autorisée.",
                    status,
                    url,
                )
            )
        if status == 404:
            return _Outcome(
                error=EodhdNotFoundError(
                    "Ressource introuvable (404) — vérifie le symbole, l'exchange ou l'endpoint.",
                    status,
                    url,
                )
            )
        if status == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            error = EodhdRateLimitError(
                "Quota ou débit EODHD dépassé (429).", status, url, retry_after=retry_after
            )
            if attempt < self._config.max_retries:
                return _Outcome(retry=True, error=error, delay=retry_after)
            return _Outcome(error=error)
        if 500 <= status < 600:
            error = EodhdServerError(f"Erreur serveur EODHD ({status}).", status, url)
            if attempt < self._config.max_retries:
                return _Outcome(retry=True, error=error)
            return _Outcome(error=error)

        return _Outcome(
            error=EodhdResponseError(f"Code HTTP inattendu ({status}) pour {redact_url(url)}.")
        )

    def _backoff_delay(self, attempt: int) -> float:
        return self._config.backoff_factor * (2 ** (attempt - 1))


class _Outcome:
    """Résultat interne du traitement d'une réponse HTTP — jamais exposé hors de ce module."""

    def __init__(
        self,
        payload: Any = None,
        error: Optional[Exception] = None,
        retry: bool = False,
        delay: Optional[float] = None,
    ):
        self.payload = payload
        self.error = error
        self.retry = retry
        self.delay = delay
