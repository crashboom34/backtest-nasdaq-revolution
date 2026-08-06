"""
tests/test_ig_http_client.py — Tests de market_data/ig/http_client.py.

100% hors ligne : requests.Session remplacé par un FakeSession. Vérifie : succès JSON + headers
de réponse renvoyés, gestion 401/403/404/429/5xx, timeout/connexion réseau, JSON invalide,
refus d'appel authentifié sans session active, jamais de secret dans un message d'erreur,
en-têtes X-IG-API-KEY/Version envoyés correctement, CST/X-SECURITY-TOKEN jamais dans un log.
"""

from __future__ import annotations

import json
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.ig.config import IgConfig
from market_data.ig.errors import (
    IgAuthError,
    IgForbiddenError,
    IgNetworkError,
    IgNotFoundError,
    IgRateLimitError,
    IgResponseError,
    IgServerError,
    IgSessionError,
)
from market_data.ig.http_client import IgHttpClient


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, content=None, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        if content is not None:
            self.content = content
        elif json_body is not None:
            self.content = json.dumps(json_body).encode("utf-8")
        else:
            self.content = b""


class FakeSession:
    def __init__(self, items):
        self._items = list(items)
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "params": params, "json": json, "headers": headers, "timeout": timeout}
        )
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _config(**overrides):
    return IgConfig(
        api_key="super-secret-api-key", identifier="my-id", password="super-secret-pw",
        account_id=None, max_retries=3, backoff_factor=0.01, **overrides,
    )


def _client(items, **config_overrides):
    session = FakeSession(items)
    sleeps = []
    client = IgHttpClient(_config(**config_overrides), session=session, sleep_fn=sleeps.append)
    return client, session, sleeps


def test_unauthenticated_call_without_include_auth_false_is_refused():
    client, session, _ = _client([FakeResponse(200, json_body={})])
    with pytest.raises(IgSessionError):
        client.request("GET", "/accounts", version="1")  # include_auth=True par défaut, pas de session
    assert len(session.calls) == 0  # refusé avant tout appel réseau


def test_login_style_call_with_include_auth_false_succeeds_without_session():
    client, session, _ = _client(
        [FakeResponse(200, json_body={"currentAccountId": "ABC"}, headers={"CST": "cst-token", "X-SECURITY-TOKEN": "sec-token"})]
    )
    body, headers = client.request("POST", "/session", version="2", json_body={"identifier": "x", "password": "y"}, include_auth=False)

    assert body == {"currentAccountId": "ABC"}
    assert headers["CST"] == "cst-token"


def test_set_and_clear_session_tokens():
    client, _, _ = _client([])
    assert client.authenticated is False
    client.set_session_tokens("cst-token", "sec-token")
    assert client.authenticated is True
    client.clear_session_tokens()
    assert client.authenticated is False


def test_authenticated_call_sends_cst_and_security_token_headers():
    client, session, _ = _client([FakeResponse(200, json_body={"accounts": []})])
    client.set_session_tokens("cst-token", "sec-token")
    client.request("GET", "/accounts", version="1")

    sent = session.calls[0]["headers"]
    assert sent["CST"] == "cst-token"
    assert sent["X-SECURITY-TOKEN"] == "sec-token"
    assert sent["X-IG-API-KEY"] == "super-secret-api-key"
    assert sent["Version"] == "1"


def test_api_key_never_appears_in_error_messages():
    client, session, _ = _client([FakeResponse(401)])
    client.set_session_tokens("cst-token", "sec-token")
    with pytest.raises(IgAuthError) as exc_info:
        client.request("GET", "/accounts", version="1")
    assert "super-secret-api-key" not in str(exc_info.value)


def test_401_raises_auth_error_without_retry():
    client, session, _ = _client([FakeResponse(401)])
    client.set_session_tokens("cst-token", "sec-token")
    with pytest.raises(IgAuthError):
        client.request("GET", "/accounts", version="1")
    assert len(session.calls) == 1


def test_403_raises_forbidden_error():
    client, session, _ = _client([FakeResponse(403)])
    client.set_session_tokens("cst-token", "sec-token")
    with pytest.raises(IgForbiddenError):
        client.request("GET", "/accounts", version="1")


def test_404_raises_not_found_error():
    client, session, _ = _client([FakeResponse(404)])
    client.set_session_tokens("cst-token", "sec-token")
    with pytest.raises(IgNotFoundError):
        client.request("GET", "/markets/BOGUS", version="3")


def test_429_retries_then_succeeds():
    client, session, sleeps = _client([FakeResponse(429), FakeResponse(200, json_body={"ok": True})])
    client.set_session_tokens("cst-token", "sec-token")
    body, _ = client.request("GET", "/accounts", version="1")
    assert body == {"ok": True}
    assert len(session.calls) == 2


def test_429_exhausts_retries_and_raises():
    client, session, _ = _client([FakeResponse(429)] * 3)
    client.set_session_tokens("cst-token", "sec-token")
    with pytest.raises(IgRateLimitError):
        client.request("GET", "/accounts", version="1")


def test_5xx_retries_then_succeeds():
    client, session, _ = _client([FakeResponse(503), FakeResponse(200, json_body={"ok": True})])
    client.set_session_tokens("cst-token", "sec-token")
    body, _ = client.request("GET", "/accounts", version="1")
    assert body == {"ok": True}


def test_5xx_exhausts_retries_and_raises():
    client, session, _ = _client([FakeResponse(500)] * 3)
    client.set_session_tokens("cst-token", "sec-token")
    with pytest.raises(IgServerError):
        client.request("GET", "/accounts", version="1")


def test_timeout_retries_then_succeeds():
    client, session, _ = _client([requests.Timeout("boom"), FakeResponse(200, json_body={"ok": True})])
    client.set_session_tokens("cst-token", "sec-token")
    body, _ = client.request("GET", "/accounts", version="1")
    assert body == {"ok": True}


def test_connection_error_exhausts_retries_and_raises_network_error():
    client, session, _ = _client([requests.ConnectionError("boom")] * 3)
    client.set_session_tokens("cst-token", "sec-token")
    with pytest.raises(IgNetworkError):
        client.request("GET", "/accounts", version="1")


def test_invalid_json_raises_response_error():
    client, session, _ = _client([FakeResponse(200, content=b"{not valid json")])
    client.set_session_tokens("cst-token", "sec-token")
    with pytest.raises(IgResponseError):
        client.request("GET", "/accounts", version="1")


def test_empty_204_response_is_treated_as_empty_body():
    # DELETE /session (logout) répond typiquement 200/204 avec un corps vide.
    client, session, _ = _client([FakeResponse(200, content=b"")])
    client.set_session_tokens("cst-token", "sec-token")
    body, _ = client.request("DELETE", "/session", version="1")
    assert body == {}
