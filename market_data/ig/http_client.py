"""
market_data/ig/http_client.py — Client HTTP bas niveau pour l'API REST IG (démo uniquement).

Un seul point d'entrée réseau pour tout le connecteur IG. Gère l'en-tête VERSION requis par
chaque endpoint IG, l'authentification par session (CST + X-SECURITY-TOKEN, jamais par clé
API seule), le retry/backoff sur erreurs réseau/429/5xx, et le mapping des codes HTTP.

Sécurité :
  - un appel avec include_auth=True (par défaut) sans session active (`set_session_tokens()`
    jamais appelé) est refusé AVANT tout appel réseau (IgSessionError) ;
  - CST/X-SECURITY-TOKEN restent uniquement en mémoire (attributs d'instance), jamais écrits
    sur disque par ce module ;
  - aucun message d'erreur ne contient api_key/CST/X-SECURITY-TOKEN.

`session` et `sleep_fn` sont injectables : aucun test unitaire ne touche le vrai réseau ni ne
ralentit la suite avec un vrai backoff.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

import requests

from .config import IgConfig
from .errors import (
    IgAuthError,
    IgBadRequestError,
    IgForbiddenError,
    IgNetworkError,
    IgNotFoundError,
    IgRateLimitError,
    IgResponseError,
    IgServerError,
    IgSessionError,
    IgUnexpectedStatusError,
)


def extract_ig_error_code(response: requests.Response) -> Optional[str]:
    """Extrait UNIQUEMENT le champ "errorCode" du corps de réponse IG (ex. {"errorCode":
    "error.security.api-key-invalid"}), sans jamais conserver ni retourner le reste du corps.

    Retourne None si le corps est absent, illisible, n'est pas un objet JSON, ou n'a pas de
    champ "errorCode" de type chaîne — jamais d'exception, jamais de fuite du corps complet.
    """
    try:
        payload = json.loads(response.content)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    error_code = payload.get("errorCode")
    return error_code if isinstance(error_code, str) else None


class IgHttpClient:
    """Client HTTP bas niveau, seul point d'entrée réseau du connecteur IG."""

    def __init__(
        self,
        config: IgConfig,
        session: Optional[requests.Session] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self._config = config
        self._session = session or requests.Session()
        self._sleep = sleep_fn
        self._cst: Optional[str] = None
        self._security_token: Optional[str] = None

    @property
    def authenticated(self) -> bool:
        return bool(self._cst and self._security_token)

    def set_session_tokens(self, cst: str, security_token: str) -> None:
        """Enregistre les tokens de session IG — en mémoire uniquement, jamais sur disque."""
        self._cst = cst
        self._security_token = security_token

    def clear_session_tokens(self) -> None:
        self._cst = None
        self._security_token = None

    def request(
        self,
        method: str,
        path: str,
        *,
        version: str,
        json_body: Optional[dict] = None,
        params: Optional[dict] = None,
        include_auth: bool = True,
    ) -> tuple[Any, dict]:
        """Effectue un appel IG. Retourne (corps JSON décodé, en-têtes de réponse).

        `include_auth=False` uniquement pour POST /session (login), qui n'a pas encore de
        session à envoyer. Tout autre appel authentifié sans session active lève IgSessionError
        avant le moindre appel réseau.
        """
        if include_auth and not self.authenticated:
            raise IgSessionError(
                "Aucune session IG active : appelle login() avant cette opération authentifiée."
            )

        headers = {
            "X-IG-API-KEY": self._config.api_key,
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json; charset=UTF-8",
            "Version": version,
            "User-Agent": self._config.user_agent,
        }
        if include_auth:
            headers["CST"] = self._cst
            headers["X-SECURITY-TOKEN"] = self._security_token

        url = f"{self._config.base_url}{path}"
        timeout = (self._config.connect_timeout, self._config.read_timeout)

        last_error: Optional[Exception] = None
        for attempt in range(1, self._config.max_retries + 1):
            try:
                response = self._session.request(
                    method, url, params=params, json=json_body, headers=headers, timeout=timeout
                )
            except requests.Timeout as exc:
                last_error = IgNetworkError("Timeout lors de l'appel IG (environnement démo).")
                if attempt < self._config.max_retries:
                    self._sleep(self._backoff_delay(attempt))
                    continue
                raise last_error from exc
            except requests.ConnectionError as exc:
                last_error = IgNetworkError("Connexion impossible à IG (environnement démo).")
                if attempt < self._config.max_retries:
                    self._sleep(self._backoff_delay(attempt))
                    continue
                raise last_error from exc

            outcome = self._handle_response(response, attempt)
            if outcome.retry:
                last_error = outcome.error
                self._sleep(self._backoff_delay(attempt))
                continue
            if outcome.error is not None:
                raise outcome.error
            return outcome.payload, dict(response.headers)

        raise last_error or IgNetworkError("Échec de l'appel IG sans détail.")

    def _handle_response(self, response: requests.Response, attempt: int) -> "_Outcome":
        status = response.status_code

        if status in (200, 201, 204):
            content = response.content
            if not content:
                return _Outcome(payload={})
            try:
                return _Outcome(payload=json.loads(content))
            except json.JSONDecodeError as exc:
                return _Outcome(error=IgResponseError(f"JSON invalide reçu depuis l'API IG : {exc}"))

        # Erreurs HTTP : on extrait UNIQUEMENT le champ "errorCode" du corps de réponse, jamais
        # le corps complet (voir extract_ig_error_code()) — satisfait l'interdiction absolue
        # d'afficher/conserver une réponse IG entière. Appliqué à TOUTE réponse non réussie,
        # y compris 400 et tout statut non spécifiquement listé (voir IgUnexpectedStatusError).
        error_code = extract_ig_error_code(response)

        if status == 400:
            return _Outcome(error=IgBadRequestError("Requête IG invalide (400).", status, error_code))
        if status == 401:
            return _Outcome(error=IgAuthError("Authentification IG refusée (401).", status, error_code))
        if status == 403:
            return _Outcome(error=IgForbiddenError("Action IG refusée (403).", status, error_code))
        if status == 404:
            return _Outcome(error=IgNotFoundError("Ressource IG introuvable (404).", status, error_code))
        if status == 429:
            error = IgRateLimitError("Quota ou débit IG dépassé (429).", status, error_code)
            if attempt < self._config.max_retries:
                return _Outcome(retry=True, error=error)
            return _Outcome(error=error)
        if 500 <= status < 600:
            error = IgServerError(f"Erreur serveur IG ({status}).", status, error_code)
            if attempt < self._config.max_retries:
                return _Outcome(retry=True, error=error)
            return _Outcome(error=error)

        return _Outcome(error=IgUnexpectedStatusError(f"Code HTTP IG inattendu ({status}).", status, error_code))

    def _backoff_delay(self, attempt: int) -> float:
        return self._config.backoff_factor * (2 ** (attempt - 1))


class _Outcome:
    """Résultat interne du traitement d'une réponse HTTP — jamais exposé hors de ce module."""

    def __init__(self, payload: Any = None, error: Optional[Exception] = None, retry: bool = False):
        self.payload = payload
        self.error = error
        self.retry = retry
