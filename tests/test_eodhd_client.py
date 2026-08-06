"""
tests/test_eodhd_client.py — Tests de market_data/eodhd/client.py.

100% hors ligne : EodhdClient reçoit un FakeHttpClient qui rejoue des réponses préparées à
l'avance pour chaque chemin d'URL, sans jamais toucher le réseau. Vérifie l'assemblage complet :
test_connection(), get_account_status() (jamais de PII/secret), search_instruments(),
list_exchanges(), list_exchange_symbols() (dont delisted), download_eod(), download_intraday()
(dont découpage en fenêtres et dédoublonnage), download_dividends(), download_splits().
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.eodhd.client import EodhdClient
from market_data.eodhd.config import config_from_api_key
from market_data.eodhd.errors import EodhdAuthError, EodhdWindowLimitError


class FakeHttpClient:
    """Rejoue une réponse par chemin d'URL (ou une exception), enregistre tous les appels."""

    def __init__(self, responses_by_path):
        self._responses = dict(responses_by_path)
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append({"path": path, "params": dict(params or {})})
        item = self._responses[path]
        if isinstance(item, list) and item and isinstance(item[0], Exception):
            # séquence d'exceptions/réponses pour un même path (téléchargement multi-fenêtres)
            result = item.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        if isinstance(item, Exception):
            raise item
        return item


def _client(responses_by_path):
    config = config_from_api_key("super-secret-key")
    http = FakeHttpClient(responses_by_path)
    return EodhdClient(config=config, http_client=http), http


def test_connection_success():
    client, http = _client({"/user": {"name": "Alex", "email": "a@b.com", "subscriptionType": "monthly"}})
    result = client.test_connection()
    assert result.ok is True
    assert "super-secret-key" not in result.message


def test_connection_failure_reports_without_raising():
    client, http = _client({"/user": EodhdAuthError("Authentification refusée (401).", 401, "")})
    result = client.test_connection()
    assert result.ok is False
    assert "401" in result.message or "refusée" in result.message.lower()


def test_get_account_status_never_exposes_name_or_email():
    client, http = _client(
        {
            "/user": {
                "name": "Alex Mira",
                "email": "piecolorama@gmail.com",
                "subscriptionType": "monthly",
                "apiRequests": 2,
                "apiRequestsDate": "2026-08-06",
                "dailyRateLimit": 100000,
                "extraLimit": 500,
            }
        }
    )
    status = client.get_account_status()

    assert status.subscription_type == "monthly"
    assert status.daily_rate_limit == 100000
    assert status.extra_limit == 500
    assert status.api_requests_today == 2
    text = repr(status) + str(status.__dict__)
    assert "Alex Mira" not in text
    assert "piecolorama@gmail.com" not in text


def test_search_instruments_passes_query_and_filters():
    client, http = _client({"/search/AAPL": [{"Code": "AAPL", "Exchange": "US"}]})
    results = client.search_instruments("AAPL", limit=5, exchange="US", type="stock")

    assert results == [{"Code": "AAPL", "Exchange": "US"}]
    call = http.calls[0]
    assert call["path"] == "/search/AAPL"
    assert call["params"]["limit"] == 5
    assert call["params"]["exchange"] == "US"
    assert call["params"]["type"] == "stock"


def test_list_exchanges_returns_raw_list():
    client, http = _client({"/exchanges-list/": [{"Code": "US", "Name": "USA Stocks"}]})
    result = client.list_exchanges()
    assert result == [{"Code": "US", "Name": "USA Stocks"}]


def test_list_exchange_symbols_maps_delisted_flag():
    client, http = _client({"/exchange-symbol-list/US": [{"Code": "AAPL"}]})
    client.list_exchange_symbols("US", delisted=True, type="etf")

    call = http.calls[0]
    assert call["params"]["delisted"] == 1
    assert call["params"]["type"] == "etf"


def test_download_eod_calls_correct_endpoint_and_normalizes():
    client, http = _client(
        {
            "/eod/AAPL.US": [
                {"date": "2026-07-28", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100},
            ]
        }
    )
    result = client.download_eod("AAPL.US", start_date="2026-07-28", end_date="2026-07-28")

    assert result.ok is True
    assert len(result.dataframe) == 1
    call = http.calls[0]
    assert call["params"]["from"] == "2026-07-28"
    assert call["params"]["to"] == "2026-07-28"
    assert call["params"]["period"] == "d"


def test_download_intraday_single_window():
    client, http = _client(
        {
            "/intraday/AAPL.US": [
                {"timestamp": 1785830400, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 10},
            ]
        }
    )
    start = datetime(2026, 8, 4, tzinfo=timezone.utc)
    end = datetime(2026, 8, 4, 1, tzinfo=timezone.utc)

    result = client.download_intraday("AAPL.US", interval="1m", start=start, end=end)

    assert result.ok is True
    assert result.windows_fetched == 1
    assert len(result.dataframe) == 1


def test_download_intraday_splits_across_multiple_windows_and_dedupes():
    # FakeHttpClient ne sait rejouer qu'une seule réponse par chemin d'URL : on a ici besoin de
    # deux réponses distinctes pour deux appels au même chemin (deux fenêtres), d'où ce petit
    # double dédié qui consomme une séquence dans l'ordre.
    class SequencedHttpClient:
        def __init__(self):
            self._sequence = [
                [{"timestamp": 1000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
                [
                    {"timestamp": 1000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
                    {"timestamp": 2000, "open": 2, "high": 2, "low": 2, "close": 2, "volume": 2},
                ],
            ]
            self.calls = []

        def get_json(self, path, params=None):
            self.calls.append({"path": path, "params": dict(params or {})})
            return self._sequence.pop(0)

    config = config_from_api_key("super-secret-key")
    seq_http = SequencedHttpClient()
    client = EodhdClient(config=config, http_client=seq_http)

    # Fenêtres de 120 jours (1m) : demander 150 jours force exactement 2 fenêtres.
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start.replace(year=2026) + (datetime(2026, 5, 31, tzinfo=timezone.utc) - start)

    result = client.download_intraday("AAPL.US", interval="1m", start=start, end=end)

    assert seq_http.calls[0]["path"] == "/intraday/AAPL.US"
    assert result.windows_fetched == 2
    assert len(result.dataframe) == 2  # timestamp 1000 dédupliqué, 2000 ajouté
    assert result.dataframe["time"].is_monotonic_increasing


def test_download_intraday_too_many_windows_raises_explicit_error():
    client, http = _client({})
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    end = datetime(2030, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(EodhdWindowLimitError):
        client.download_intraday("AAPL.US", interval="1m", start=start, end=end, max_windows=2)


def test_download_dividends_calls_correct_endpoint():
    client, http = _client(
        {
            "/div/AAPL.US": [
                {"date": "2025-02-10", "declarationDate": "2025-01-30", "recordDate": "2025-02-10",
                 "paymentDate": "2025-02-13", "period": "Quarterly", "value": 0.25,
                 "unadjustedValue": 0.25, "currency": "USD"},
            ]
        }
    )
    result = client.download_dividends("AAPL.US", start_date="2025-01-01", end_date="2025-12-31")
    assert result.ok is True
    assert len(result.dataframe) == 1
    assert http.calls[0]["path"] == "/div/AAPL.US"


def test_download_splits_calls_correct_endpoint():
    client, http = _client({"/splits/AAPL.US": [{"date": "2020-08-31", "split": "4.000000/1.000000"}]})
    result = client.download_splits("AAPL.US", start_date="2018-01-01", end_date="2025-12-31")
    assert result.ok is True
    assert len(result.dataframe) == 1
    assert http.calls[0]["path"] == "/splits/AAPL.US"


def test_download_eod_reports_failure_without_raising():
    client, http = _client({"/eod/BOGUS.US": EodhdAuthError("401", 401, "")})
    result = client.download_eod("BOGUS.US")
    assert result.ok is False
    assert result.dataframe is None


# Échantillon réel capturé via le MCP EODHD le 2026-08-06 (get_exchange_details, exchange "US")
# — voir AI_HANDOFF.md. Tronqué aux champs utiles pour les tests.
_REAL_US_EXCHANGE_DETAILS_SAMPLE = {
    "Name": "USA Stocks", "Code": "US", "Country": "USA", "Currency": "USD",
    "Timezone": "America/New_York",
    "ExchangeHolidays": {
        "0": {"Holiday": "Washington's Birthday", "Date": "2026-02-16", "Type": "official"},
        "1": {"Holiday": "Good Friday", "Date": "2026-04-03", "Type": "official"},
    },
    "ExchangeEarlyCloseDays": {
        "0": {"Holiday": "Post-Thanksgiving Day Friday 2026", "Date": "2026-11-27",
              "Type": "official", "EarlyClose": "13:00"},
    },
    "isOpen": False,
    "TradingHours": {
        "Open": "09:30:00", "Close": "16:00:00", "OpenUTC": "13:30:00", "CloseUTC": "20:00:00",
        "WorkingDays": "Mon,Tue,Wed,Thu,Fri",
    },
    "ActiveTickers": 51550,
}


def test_get_exchange_details_calls_correct_endpoint():
    client, http = _client({"/exchange-details/US": _REAL_US_EXCHANGE_DETAILS_SAMPLE})
    result = client.get_exchange_details("US")

    assert result == _REAL_US_EXCHANGE_DETAILS_SAMPLE
    assert http.calls[0]["path"] == "/exchange-details/US"
