"""
tests/test_ig_config.py — Tests de market_data/ig/config.py.

Le cœur de la sécurité IG se joue ici : environnement live/prod/vide refusé AVANT toute
construction de client, base URL démo non paramétrable, aucun secret dans repr()/str().
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.ig.config import DEMO_BASE_URL, IgConfig, load_ig_config
from market_data.ig.errors import IgConfigError, IgEnvironmentRefusedError


def _set_full_demo_env(monkeypatch):
    monkeypatch.setenv("BACKTEST_IG_API_KEY", "super-secret-api-key")
    monkeypatch.setenv("BACKTEST_IG_IDENTIFIER", "my-identifier")
    monkeypatch.setenv("BACKTEST_IG_PASSWORD", "super-secret-password")
    monkeypatch.setenv("BACKTEST_IG_ENVIRONMENT", "demo")


def test_load_ig_config_succeeds_with_full_demo_env(monkeypatch, tmp_path):
    _set_full_demo_env(monkeypatch)
    config = load_ig_config(path=tmp_path / "data_providers.json")

    assert config.base_url == DEMO_BASE_URL
    assert config.api_key == "super-secret-api-key"


@pytest.mark.parametrize("bad_env", ["live", "LIVE", "prod", "PROD", "production", "Production"])
def test_load_ig_config_refuses_live_and_prod_environments(monkeypatch, tmp_path, bad_env):
    _set_full_demo_env(monkeypatch)
    monkeypatch.setenv("BACKTEST_IG_ENVIRONMENT", bad_env)

    with pytest.raises(IgEnvironmentRefusedError):
        load_ig_config(path=tmp_path / "data_providers.json")


def test_load_ig_config_refuses_empty_environment(monkeypatch, tmp_path):
    _set_full_demo_env(monkeypatch)
    monkeypatch.delenv("BACKTEST_IG_ENVIRONMENT", raising=False)

    with pytest.raises(IgEnvironmentRefusedError):
        load_ig_config(path=tmp_path / "data_providers.json")


def test_load_ig_config_refuses_unknown_environment_value(monkeypatch, tmp_path):
    _set_full_demo_env(monkeypatch)
    monkeypatch.setenv("BACKTEST_IG_ENVIRONMENT", "staging")

    with pytest.raises(IgEnvironmentRefusedError):
        load_ig_config(path=tmp_path / "data_providers.json")


def test_load_ig_config_refuses_missing_credentials_even_with_demo_env(monkeypatch, tmp_path):
    monkeypatch.delenv("BACKTEST_IG_API_KEY", raising=False)
    monkeypatch.delenv("BACKTEST_IG_IDENTIFIER", raising=False)
    monkeypatch.delenv("BACKTEST_IG_PASSWORD", raising=False)
    monkeypatch.setenv("BACKTEST_IG_ENVIRONMENT", "demo")

    with pytest.raises(IgConfigError):
        load_ig_config(path=tmp_path / "data_providers.json")


def test_environment_is_checked_before_credentials_are_required(monkeypatch, tmp_path):
    # Même sans AUCUN identifiant, un environnement live doit être refusé en premier (et pas
    # masqué par une IgConfigError sur les identifiants manquants) — l'environnement est la
    # garde de sécurité prioritaire.
    monkeypatch.delenv("BACKTEST_IG_API_KEY", raising=False)
    monkeypatch.delenv("BACKTEST_IG_IDENTIFIER", raising=False)
    monkeypatch.delenv("BACKTEST_IG_PASSWORD", raising=False)
    monkeypatch.setenv("BACKTEST_IG_ENVIRONMENT", "live")

    with pytest.raises(IgEnvironmentRefusedError):
        load_ig_config(path=tmp_path / "data_providers.json")


def test_igconfig_base_url_cannot_be_overridden_to_the_live_url():
    with pytest.raises(IgEnvironmentRefusedError):
        IgConfig(
            api_key="k", identifier="i", password="p", account_id=None,
            base_url="https://api.ig.com/gateway/deal",
        )


def test_igconfig_base_url_cannot_be_overridden_to_an_arbitrary_url():
    with pytest.raises(IgEnvironmentRefusedError):
        IgConfig(
            api_key="k", identifier="i", password="p", account_id=None,
            base_url="https://evil.example.com",
        )


def test_igconfig_repr_never_exposes_secrets():
    config = IgConfig(api_key="super-secret-key", identifier="my-id", password="super-secret-pw", account_id="ACC1")
    text = repr(config)

    assert "super-secret-key" not in text
    assert "my-id" not in text
    assert "super-secret-pw" not in text
    assert "super-secret-key" not in str(config)


def test_load_ig_config_does_not_expose_base_url_as_a_public_override_parameter(monkeypatch, tmp_path):
    _set_full_demo_env(monkeypatch)
    with pytest.raises(IgEnvironmentRefusedError):
        load_ig_config(path=tmp_path / "data_providers.json", base_url="https://api.ig.com/gateway/deal")
