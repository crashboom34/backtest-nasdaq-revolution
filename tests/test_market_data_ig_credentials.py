"""
tests/test_market_data_ig_credentials.py — Tests des identifiants IG dans provider_config.py.

Contraintes vérifiées (voir CLAUDE.md, section IG) :
  - api_key, identifier, environment, account_id : variable d'environnement en priorité, sinon
    settings/data_providers.json (comme EODHD) ;
  - password : UNIQUEMENT variable d'environnement, jamais lu ni écrit dans le fichier local ;
  - IgCredentials.__repr__/__str__ ne révèle jamais api_key/identifier/password ;
  - ig_credential_status() ne renvoie aucune valeur sensible, seulement configuré/absent/origine ;
  - save_ig_credentials() ne peut structurellement pas écrire de mot de passe (pas de paramètre
    password) et n'écrase pas les autres fournisseurs déjà présents dans le fichier.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.provider_config import (
    IgCredentials,
    ProviderCredentialStatus,
    get_ig_credentials,
    ig_credential_status,
    save_api_key,
    save_ig_credentials,
)


def test_ig_credentials_all_absent_by_default(tmp_path):
    creds = get_ig_credentials(path=tmp_path / "data_providers.json")

    assert isinstance(creds, IgCredentials)
    assert creds.api_key is None
    assert creds.identifier is None
    assert creds.password is None
    assert creds.environment is None
    assert creds.account_id is None
    assert creds.configured is False


def test_ig_credentials_env_vars_take_priority(monkeypatch, tmp_path):
    settings_path = tmp_path / "data_providers.json"
    save_ig_credentials(api_key="file-key", identifier="file-id", path=settings_path)

    monkeypatch.setenv("BACKTEST_IG_API_KEY", "env-key")
    monkeypatch.setenv("BACKTEST_IG_IDENTIFIER", "env-id")
    monkeypatch.setenv("BACKTEST_IG_PASSWORD", "env-password")
    monkeypatch.setenv("BACKTEST_IG_ENVIRONMENT", "demo")
    monkeypatch.setenv("BACKTEST_IG_ACCOUNT_ID", "env-account")

    creds = get_ig_credentials(path=settings_path)
    assert creds.api_key == "env-key"
    assert creds.identifier == "env-id"
    assert creds.password == "env-password"
    assert creds.environment == "demo"
    assert creds.account_id == "env-account"
    assert creds.configured is True


def test_ig_credentials_fallback_to_settings_file_except_password(monkeypatch, tmp_path):
    settings_path = tmp_path / "data_providers.json"
    save_ig_credentials(
        api_key="file-key",
        identifier="file-id",
        environment="demo",
        account_id="file-account",
        path=settings_path,
    )
    # Aucune variable d'environnement définie pour ces champs.
    monkeypatch.delenv("BACKTEST_IG_API_KEY", raising=False)
    monkeypatch.delenv("BACKTEST_IG_IDENTIFIER", raising=False)
    monkeypatch.delenv("BACKTEST_IG_ENVIRONMENT", raising=False)
    monkeypatch.delenv("BACKTEST_IG_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("BACKTEST_IG_PASSWORD", raising=False)

    creds = get_ig_credentials(path=settings_path)
    assert creds.api_key == "file-key"
    assert creds.identifier == "file-id"
    assert creds.environment == "demo"
    assert creds.account_id == "file-account"
    # Le mot de passe n'est jamais lu depuis le fichier : il reste absent même si le fichier
    # existe et contient d'autres champs IG.
    assert creds.password is None


def test_save_ig_credentials_never_accepts_a_password_argument():
    """save_ig_credentials() ne doit structurellement pas pouvoir écrire de mot de passe :
    aucun paramètre 'password' n'existe dans sa signature."""
    import inspect

    sig = inspect.signature(save_ig_credentials)
    assert "password" not in sig.parameters


def test_settings_file_never_contains_a_password_field(tmp_path):
    settings_path = tmp_path / "data_providers.json"
    save_ig_credentials(
        api_key="file-key", identifier="file-id", environment="demo", path=settings_path
    )

    raw = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "password" not in raw.get("ig", {})


def test_save_ig_credentials_does_not_overwrite_other_providers(tmp_path):
    settings_path = tmp_path / "data_providers.json"
    save_api_key("eodhd", "eodhd-key", path=settings_path)
    save_ig_credentials(api_key="ig-key", identifier="ig-id", path=settings_path)

    raw = json.loads(settings_path.read_text(encoding="utf-8"))
    assert raw["eodhd"]["api_key"] == "eodhd-key"
    assert raw["ig"]["api_key"] == "ig-key"


def test_ig_credentials_repr_never_exposes_secrets():
    creds = IgCredentials(
        api_key="super-secret-key",
        identifier="my-identifier",
        password="super-secret-password",
        environment="demo",
        account_id="ACC123",
    )
    text = repr(creds)

    assert "super-secret-key" not in text
    assert "my-identifier" not in text
    assert "super-secret-password" not in text
    assert "ACC123" not in text
    # str() doit se comporter comme repr() par défaut (aucune surcharge séparée qui fuiterait).
    assert "super-secret-key" not in str(creds)
    assert "super-secret-password" not in str(creds)


def test_ig_credential_status_never_exposes_secret_values(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKTEST_IG_API_KEY", "super-secret-key")
    monkeypatch.setenv("BACKTEST_IG_IDENTIFIER", "my-identifier")
    monkeypatch.setenv("BACKTEST_IG_PASSWORD", "super-secret-password")
    monkeypatch.setenv("BACKTEST_IG_ENVIRONMENT", "demo")
    monkeypatch.setenv("BACKTEST_IG_ACCOUNT_ID", "ACC123")

    status = ig_credential_status(path=tmp_path / "data_providers.json")

    assert isinstance(status, ProviderCredentialStatus)
    assert status.configured is True
    dump = json.dumps(
        {"message": status.message, "field_status": status.field_status}, ensure_ascii=False
    )
    assert "super-secret-key" not in dump
    assert "my-identifier" not in dump
    assert "super-secret-password" not in dump
    assert "ACC123" not in dump


def test_ig_credential_status_reports_missing_fields_by_name(tmp_path):
    status = ig_credential_status(path=tmp_path / "data_providers.json")

    assert status.configured is False
    assert status.field_status["api_key"] == "missing"
    assert status.field_status["identifier"] == "missing"
    assert status.field_status["password"] == "missing"


def test_ig_credential_status_distinguishes_env_and_settings_file_origin(monkeypatch, tmp_path):
    settings_path = tmp_path / "data_providers.json"
    save_ig_credentials(api_key="file-key", identifier="file-id", path=settings_path)
    monkeypatch.setenv("BACKTEST_IG_PASSWORD", "env-password")

    status = ig_credential_status(path=settings_path)

    assert status.field_status["api_key"] == "settings_file"
    assert status.field_status["identifier"] == "settings_file"
    assert status.field_status["password"] == "env"
    assert status.field_status["environment"] == "missing"
