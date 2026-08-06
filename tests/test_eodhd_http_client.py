"""
tests/test_eodhd_http_client.py — Tests de market_data/eodhd/http_client.py.

100% hors ligne : `requests.Session` est remplacé par un FakeSession qui rejoue des réponses ou
des exceptions préparées à l'avance, sans jamais toucher le réseau. `sleep_fn` est remplacé par
une fonction qui ne dort pas réellement, pour que la suite de tests reste rapide.

Vérifie : succès JSON, 401, 403, 404, 429 (avec et sans épuisement des retries), 5xx (avec et
sans épuisement des retries), timeout réseau, connexion refusée, JSON invalide, réponse trop
volumineuse, User-Agent explicite envoyé, clé API jamais présente dans un message d'erreur.
"""

from __future__ import annotations

import json
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.eodhd.config import config_from_api_key
from market_data.eodhd.errors import (
    EodhdAuthError,
    EodhdForbiddenError,
    EodhdNetworkError,
    EodhdNotFoundError,
    EodhdRateLimitError,
    EodhdResponseError,
    EodhdServerError,
)
from market_data.eodhd.http_client import EodhdHttpClient


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

    def close(self):
        pass


class FakeSession:
    """Rejoue une séquence de réponses ou d'exceptions, dans l'ordre, un item par appel .get()."""

    def __init__(self, items):
        self._items = list(items)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(items, **config_overrides):
    config = config_from_api_key("super-secret-key", max_retries=3, backoff_factor=0.01, **config_overrides)
    session = FakeSession(items)
    sleeps = []
    client = EodhdHttpClient(config, session=session, sleep_fn=sleeps.append)
    return client, session, sleeps


def test_successful_json_response_is_returned():
    client, session, _ = _client([FakeResponse(200, json_body=[{"date": "2026-01-02"}])])

    result = client.get_json("/eod/AAPL.US", params={"period": "d"})

    assert result == [{"date": "2026-01-02"}]
    assert len(session.calls) == 1


def test_api_key_is_sent_as_query_param_and_never_in_error_messages():
    client, session, _ = _client([FakeResponse(401)])

    with pytest.raises(EodhdAuthError) as exc_info:
        client.get_json("/user")

    assert session.calls[0]["params"]["api_token"] == "super-secret-key"
    assert "super-secret-key" not in str(exc_info.value)


def test_user_agent_header_is_explicit():
    client, session, _ = _client([FakeResponse(200, json_body={})])
    client.get_json("/user")

    sent_headers = session.calls[0]["headers"]
    assert "User-Agent" in sent_headers
    assert "python-requests" not in sent_headers["User-Agent"].lower()


def test_timeout_tuple_is_passed_to_session():
    client, session, _ = _client([FakeResponse(200, json_body={})], connect_timeout=3.0, read_timeout=15.0)
    client.get_json("/user")

    assert session.calls[0]["timeout"] == (3.0, 15.0)


def test_401_raises_auth_error_without_retry():
    client, session, _ = _client([FakeResponse(401)])
    with pytest.raises(EodhdAuthError):
        client.get_json("/user")
    assert len(session.calls) == 1  # pas de retry sur 401


def test_403_raises_forbidden_error_without_retry():
    client, session, _ = _client([FakeResponse(403)])
    with pytest.raises(EodhdForbiddenError):
        client.get_json("/search/AAPL")
    assert len(session.calls) == 1


def test_404_raises_not_found_error_without_retry():
    client, session, _ = _client([FakeResponse(404)])
    with pytest.raises(EodhdNotFoundError):
        client.get_json("/eod/DOESNOTEXIST.US")
    assert len(session.calls) == 1


def test_429_retries_then_succeeds():
    client, session, sleeps = _client(
        [FakeResponse(429, headers={"Retry-After": "0.5"}), FakeResponse(200, json_body={"ok": True})]
    )
    result = client.get_json("/eod/AAPL.US")

    assert result == {"ok": True}
    assert len(session.calls) == 2
    assert sleeps == [0.5]  # respecte Retry-After plutôt que le backoff générique


def test_429_exhausts_retries_and_raises_rate_limit_error():
    client, session, _ = _client([FakeResponse(429), FakeResponse(429), FakeResponse(429)])
    with pytest.raises(EodhdRateLimitError):
        client.get_json("/eod/AAPL.US")
    assert len(session.calls) == 3


def test_5xx_retries_then_succeeds():
    client, session, _ = _client([FakeResponse(503), FakeResponse(200, json_body={"ok": True})])
    result = client.get_json("/eod/AAPL.US")
    assert result == {"ok": True}
    assert len(session.calls) == 2


def test_5xx_exhausts_retries_and_raises_server_error():
    client, session, _ = _client([FakeResponse(500), FakeResponse(500), FakeResponse(500)])
    with pytest.raises(EodhdServerError):
        client.get_json("/eod/AAPL.US")
    assert len(session.calls) == 3


def test_timeout_retries_then_succeeds():
    client, session, _ = _client([requests.Timeout("boom"), FakeResponse(200, json_body={"ok": True})])
    result = client.get_json("/eod/AAPL.US")
    assert result == {"ok": True}


def test_connection_error_exhausts_retries_and_raises_network_error():
    client, session, _ = _client(
        [requests.ConnectionError("boom"), requests.ConnectionError("boom"), requests.ConnectionError("boom")]
    )
    with pytest.raises(EodhdNetworkError):
        client.get_json("/eod/AAPL.US")


def test_invalid_json_raises_response_error():
    client, session, _ = _client([FakeResponse(200, content=b"{not valid json")])
    with pytest.raises(EodhdResponseError):
        client.get_json("/eod/AAPL.US")


def test_response_too_large_by_content_length_header_raises_response_error():
    client, session, _ = _client(
        [FakeResponse(200, json_body={"a": 1}, headers={"Content-Length": "999999999"})],
        max_response_bytes=1000,
    )
    with pytest.raises(EodhdResponseError):
        client.get_json("/eod/AAPL.US")


def test_response_too_large_by_actual_size_raises_response_error():
    big_content = b"[" + b"1," * 2000 + b"1]"
    client, session, _ = _client([FakeResponse(200, content=big_content)], max_response_bytes=100)
    with pytest.raises(EodhdResponseError):
        client.get_json("/eod/AAPL.US")


def test_unexpected_status_code_raises_response_error():
    client, session, _ = _client([FakeResponse(418)])
    with pytest.raises(EodhdResponseError):
        client.get_json("/eod/AAPL.US")
