"""
tests/test_ig_client.py — Tests de market_data/ig/client.py.

100% hors ligne : IgClient reçoit un FakeIgHttpClient qui rejoue des réponses préparées à
l'avance, sans jamais toucher le réseau. Vérifie : login/logout (tokens en mémoire uniquement,
jamais écrits), test_connection(), get_accounts(), discover_account_id() (env explicite ou
découvert au login), search_markets(), get_market_details(), get_prices() (résolutions
valides/invalides, normalisation), et surtout : AUCUNE méthode de trading n'existe sur IgClient.
"""

from __future__ import annotations

import inspect
import os
import sys
from urllib.parse import quote

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.ig.client import IgClient
from market_data.ig.config import IgConfig
from market_data.ig.errors import IgAuthError, IgError


class FakeIgHttpClient:
    """Rejoue une réponse (body, headers) par (method, path), enregistre les appels."""

    def __init__(self, responses):
        self._responses = dict(responses)
        self.calls = []
        self.authenticated = False
        self._cst = None
        self._security_token = None

    def set_session_tokens(self, cst, security_token):
        self._cst = cst
        self._security_token = security_token
        self.authenticated = True

    def clear_session_tokens(self):
        self._cst = None
        self._security_token = None
        self.authenticated = False

    def request(self, method, path, *, version, json_body=None, params=None, include_auth=True):
        key = (method, path)
        self.calls.append({"method": method, "path": path, "version": version, "json_body": json_body, "params": params, "include_auth": include_auth})
        item = self._responses[key]
        if isinstance(item, Exception):
            raise item
        return item


def _config():
    return IgConfig(api_key="k", identifier="my-id", password="super-secret-pw", account_id=None)


def test_login_stores_tokens_and_discovers_account_id():
    http = FakeIgHttpClient(
        {("POST", "/session"): ({"currentAccountId": "ABC123"}, {"CST": "cst-token", "X-SECURITY-TOKEN": "sec-token"})}
    )
    client = IgClient(_config(), http_client=http)

    result = client.login()

    assert result.ok is True
    assert result.account_id == "ABC123"
    assert http.authenticated is True
    assert client.discover_account_id() == "ABC123"


def test_login_prefers_explicit_account_id_over_discovered_one():
    http = FakeIgHttpClient(
        {("POST", "/session"): ({"currentAccountId": "DISCOVERED"}, {"CST": "cst-token", "X-SECURITY-TOKEN": "sec-token"})}
    )
    config = IgConfig(api_key="k", identifier="my-id", password="pw", account_id="EXPLICIT")
    client = IgClient(config, http_client=http)

    result = client.login()
    assert result.account_id == "EXPLICIT"


def test_login_failure_never_exposes_password():
    http = FakeIgHttpClient({("POST", "/session"): IgAuthError("401", 401)})
    client = IgClient(_config(), http_client=http)

    result = client.login()
    assert result.ok is False
    assert "super-secret-pw" not in result.message


def test_login_incomplete_tokens_reports_failure():
    http = FakeIgHttpClient({("POST", "/session"): ({"currentAccountId": "ABC"}, {})})  # pas de CST/token
    client = IgClient(_config(), http_client=http)

    result = client.login()
    assert result.ok is False
    assert http.authenticated is False


def test_logout_clears_tokens_even_on_network_error():
    http = FakeIgHttpClient(
        {
            ("POST", "/session"): ({"currentAccountId": "ABC"}, {"CST": "c", "X-SECURITY-TOKEN": "s"}),
            ("DELETE", "/session"): IgAuthError("boom", 401),
        }
    )
    client = IgClient(_config(), http_client=http)
    client.login()
    assert http.authenticated is True

    client.logout()  # ne doit jamais lever, même si l'appel réseau échoue
    assert http.authenticated is False


def test_logout_without_prior_login_does_not_call_network():
    http = FakeIgHttpClient({})
    client = IgClient(_config(), http_client=http)
    client.logout()  # ne doit rien appeler, ne doit pas lever
    assert http.calls == []


def test_connection_success_logs_in_checks_accounts_then_logs_out():
    http = FakeIgHttpClient(
        {
            ("POST", "/session"): ({"currentAccountId": "ABC"}, {"CST": "c", "X-SECURITY-TOKEN": "s"}),
            ("GET", "/accounts"): ({"accounts": [{"accountId": "ABC", "accountName": "Demo", "accountType": "CFD", "preferred": True}]}, {}),
            ("DELETE", "/session"): ({}, {}),
        }
    )
    client = IgClient(_config(), http_client=http)

    result = client.test_connection()

    assert result.ok is True
    assert http.authenticated is False  # déconnecté proprement à la fin
    methods_called = [(c["method"], c["path"]) for c in http.calls]
    assert ("DELETE", "/session") in methods_called


def test_get_accounts_parses_account_list():
    http = FakeIgHttpClient(
        {("GET", "/accounts"): ({"accounts": [{"accountId": "A1", "accountName": "N1", "accountType": "CFD", "preferred": True}]}, {})}
    )
    http.set_session_tokens("c", "s")
    client = IgClient(_config(), http_client=http)

    accounts = client.get_accounts()
    assert len(accounts) == 1
    assert accounts[0].account_id == "A1"
    assert accounts[0].preferred is True


def test_search_markets_passes_search_term():
    http = FakeIgHttpClient({("GET", "/markets"): ({"markets": [{"epic": "IX.D.NASDAQ.IFE.IP"}]}, {})})
    http.set_session_tokens("c", "s")
    client = IgClient(_config(), http_client=http)

    results = client.search_markets("nasdaq")
    assert results == [{"epic": "IX.D.NASDAQ.IFE.IP"}]
    assert http.calls[0]["params"] == {"searchTerm": "nasdaq"}
    assert http.calls[0]["version"] == "1"


def test_get_market_details_calls_correct_endpoint():
    http = FakeIgHttpClient({("GET", "/markets/IX.D.NASDAQ.IFE.IP"): ({"instrument": {}}, {})})
    http.set_session_tokens("c", "s")
    client = IgClient(_config(), http_client=http)

    details = client.get_market_details("IX.D.NASDAQ.IFE.IP")
    assert details == {"instrument": {}}
    assert http.calls[0]["version"] == "3"


def test_get_prices_calls_correct_endpoint_and_normalizes():
    start, end = "2026/08/01 00:00:00", "2026/08/02 00:00:00"
    # Les dates IG contiennent "/" et ":" : elles doivent être encodées en segments d'URL
    # (RFC 3986), sinon elles casseraient le routage du chemin — voir client.py.
    encoded_path = f"/prices/{quote('IX.D.NASDAQ.IFE.IP', safe='')}/{quote('DAY', safe='')}/{quote(start, safe='')}/{quote(end, safe='')}"
    http = FakeIgHttpClient(
        {
            ("GET", encoded_path): (
                {"prices": [
                    {"snapshotTime": "2026/08/01 00:00:00", "openPrice": {"bid": 1, "ask": 1.1},
                     "highPrice": {"bid": 2, "ask": 2.1}, "lowPrice": {"bid": 0.5, "ask": 0.6},
                     "closePrice": {"bid": 1.5, "ask": 1.6}, "lastTradedVolume": 10}
                ]}, {}
            )
        }
    )
    http.set_session_tokens("c", "s")
    client = IgClient(_config(), http_client=http)

    result = client.get_prices("IX.D.NASDAQ.IFE.IP", "DAY", start, end)
    assert result.ok is True
    assert len(result.dataframe) == 1


def test_get_prices_rejects_invalid_resolution_before_any_network_call():
    http = FakeIgHttpClient({})
    http.set_session_tokens("c", "s")
    client = IgClient(_config(), http_client=http)

    with pytest.raises(ValueError):
        client.get_prices("IX.D.NASDAQ.IFE.IP", "FORTNIGHT", "2026/08/01 00:00:00", "2026/08/02 00:00:00")
    assert http.calls == []


def test_get_prices_reports_http_failure_without_raising():
    start, end = "2026/08/01 00:00:00", "2026/08/02 00:00:00"
    encoded_path = f"/prices/{quote('BOGUS', safe='')}/{quote('DAY', safe='')}/{quote(start, safe='')}/{quote(end, safe='')}"
    http = FakeIgHttpClient({("GET", encoded_path): IgAuthError("401", 401)})
    http.set_session_tokens("c", "s")
    client = IgClient(_config(), http_client=http)

    result = client.get_prices("BOGUS", "DAY", start, end)
    assert result.ok is False
    assert result.dataframe is None


def test_igclient_has_no_trading_endpoints_whatsoever():
    """Aucune méthode de passage/modification/suppression d'ordre ne doit exister sur IgClient —
    vérifié en énumérant ses méthodes publiques plutôt qu'en testant un comportement d'une
    méthode qui ne devrait pas exister."""
    forbidden_substrings = (
        "position", "order", "deal", "trade", "close", "otc", "confirm",
    )
    public_methods = [name for name, _ in inspect.getmembers(IgClient, predicate=inspect.isfunction) if not name.startswith("_")]

    for name in public_methods:
        lowered = name.lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in lowered, f"Méthode suspecte trouvée sur IgClient : {name!r}"


def test_igclient_public_surface_is_exactly_the_expected_read_only_methods():
    expected = {"login", "logout", "test_connection", "get_accounts", "discover_account_id", "search_markets", "get_market_details", "get_prices"}
    public_methods = {name for name, _ in inspect.getmembers(IgClient, predicate=inspect.isfunction) if not name.startswith("_")}
    assert public_methods == expected
