"""
tests/test_market_data_provider_config.py — Tests de market_data/provider_config.py.

Vérifie :
  - priorité à la variable d'environnement sur le fichier local ;
  - repli sur settings/data_providers.json si l'environnement est vide ;
  - statut explicite "non configuré" sans exception si aucune source n'est renseignée ;
  - credential_status() ne renvoie jamais la valeur du secret, seulement son origine ;
  - save_api_key()/get_api_key() font un aller-retour fidèle, sans écraser les autres
    fournisseurs déjà enregistrés dans le même fichier ;
  - un fichier de settings absent, vide ou corrompu ne casse rien.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.provider_config import (
    credential_status,
    env_var_name,
    get_api_key,
    save_api_key,
)


def test_env_var_name_is_upper_snake_case():
    assert env_var_name("eodhd") == "BACKTEST_EODHD_API_KEY"
    assert env_var_name("Dukascopy") == "BACKTEST_DUKASCOPY_API_KEY"


def test_missing_credential_is_reported_without_exception(tmp_path):
    status = credential_status("eodhd", path=tmp_path / "data_providers.json")

    assert status.configured is False
    assert status.source == "missing"
    assert "eodhd" in status.message


def test_env_var_takes_priority_over_settings_file(monkeypatch, tmp_path):
    settings_path = tmp_path / "data_providers.json"
    save_api_key("eodhd", "file-key-should-be-ignored", path=settings_path)
    monkeypatch.setenv("BACKTEST_EODHD_API_KEY", "env-key")

    assert get_api_key("eodhd", path=settings_path) == "env-key"
    status = credential_status("eodhd", path=settings_path)
    assert status.configured is True
    assert status.source == "env"
    assert "env-key" not in status.message  # jamais le secret dans le message


def test_settings_file_is_used_when_env_var_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("BACKTEST_EODHD_API_KEY", raising=False)
    settings_path = tmp_path / "data_providers.json"
    save_api_key("eodhd", "my-secret-key", path=settings_path)

    assert get_api_key("eodhd", path=settings_path) == "my-secret-key"
    status = credential_status("eodhd", path=settings_path)
    assert status.configured is True
    assert status.source == "settings_file"
    assert "my-secret-key" not in status.message


def test_save_api_key_does_not_overwrite_other_providers(tmp_path):
    settings_path = tmp_path / "data_providers.json"
    save_api_key("eodhd", "eodhd-key", path=settings_path)
    save_api_key("ig", "ig-key", path=settings_path)

    assert get_api_key("eodhd", path=settings_path) == "eodhd-key"
    assert get_api_key("ig", path=settings_path) == "ig-key"


def test_save_api_key_rejects_empty_value(tmp_path):
    with pytest.raises(ValueError):
        save_api_key("eodhd", "   ", path=tmp_path / "data_providers.json")


def test_get_api_key_tolerates_missing_file(tmp_path):
    assert get_api_key("eodhd", path=tmp_path / "does_not_exist.json") is None


def test_get_api_key_tolerates_corrupted_file(tmp_path):
    corrupted = tmp_path / "data_providers.json"
    corrupted.write_text("{not valid json", encoding="utf-8")

    assert get_api_key("eodhd", path=corrupted) is None
