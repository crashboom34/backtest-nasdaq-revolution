"""
tests/test_eodhd_config.py — Tests de market_data/eodhd/config.py.

Vérifie :
  - la clé absente lève EodhdConfigError avec un message explicite, jamais de secret ;
  - la clé configurée (env ou fichier) produit un EodhdConfig valide ;
  - EodhdConfig ne révèle jamais api_key dans repr()/str() ;
  - config_from_api_key() refuse une clé vide.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.eodhd.config import EodhdConfig, config_from_api_key, load_eodhd_config
from market_data.eodhd.errors import EodhdConfigError


def test_load_eodhd_config_raises_explicit_error_when_key_absent(tmp_path):
    with pytest.raises(EodhdConfigError) as exc_info:
        load_eodhd_config(path=tmp_path / "data_providers.json")

    assert "BACKTEST_EODHD_API_KEY" in str(exc_info.value)


def test_load_eodhd_config_reads_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKTEST_EODHD_API_KEY", "super-secret-key")
    config = load_eodhd_config(path=tmp_path / "data_providers.json")

    assert isinstance(config, EodhdConfig)
    assert config.api_key == "super-secret-key"


def test_eodhd_config_repr_never_exposes_the_key():
    config = EodhdConfig(api_key="super-secret-key")
    text = repr(config)

    assert "super-secret-key" not in text
    assert "super-secret-key" not in str(config)


def test_config_from_api_key_rejects_empty_value():
    with pytest.raises(EodhdConfigError):
        config_from_api_key("   ")


def test_config_from_api_key_builds_valid_config():
    config = config_from_api_key("my-key", max_retries=5)
    assert config.api_key == "my-key"
    assert config.max_retries == 5


def test_default_base_url_is_the_official_eodhd_endpoint():
    config = config_from_api_key("my-key")
    assert config.base_url == "https://eodhd.com/api"


def test_default_user_agent_is_explicit_not_generic():
    config = config_from_api_key("my-key")
    assert "python-requests" not in config.user_agent.lower()
    assert len(config.user_agent) > 10
