"""
market_data/provider_config.py — Emplacement générique pour les identifiants des futurs
fournisseurs de données (EODHD, Dukascopy, FirstRate, IG, Binance, Alpaca...).

Ce module ne se connecte à AUCUNE API : il définit seulement où et comment un identifiant
sera lu plus tard, avec un statut "configuré / non configuré" clair. Deux emplacements
possibles, dans cet ordre de priorité :

1. Variable d'environnement `BACKTEST_<PROVIDER>_API_KEY` (ex. `BACKTEST_EODHD_API_KEY`).
2. Fichier local `settings/data_providers.json` (jamais suivi par Git — voir .gitignore).

Aucun secret n'est jamais écrit dans un fichier suivi par Git, ni inclus dans un message
d'erreur ou de log : credential_status() ne retourne jamais la valeur de la clé, seulement
son origine (env / fichier / absente).

IG est un cas particulier à plusieurs champs (api_key, identifier, password, environment,
account_id), avec une contrainte de sécurité supplémentaire : le mot de passe IG n'est JAMAIS
lu depuis, ni écrit dans, settings/data_providers.json — uniquement la variable d'environnement
BACKTEST_IG_PASSWORD (voir IgCredentials / save_ig_credentials / ig_credential_status).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

DEFAULT_PROVIDER_SETTINGS_PATH = (
    Path(__file__).resolve().parent.parent / "settings" / "data_providers.json"
)

# Champs IG qui peuvent être secondés par settings/data_providers.json si la variable
# d'environnement correspondante est absente. "password" est volontairement exclu de cette
# liste : il n'a pas d'équivalent fichier (voir docstring du module).
_IG_FILE_BACKED_FIELDS: tuple[str, ...] = ("api_key", "identifier", "environment", "account_id")


def _redacted_flag(value: Optional[str]) -> str:
    """Redaction centralisée : ne renvoie jamais la valeur, seulement sa présence."""
    return "set" if value else "unset"


@dataclass(frozen=True)
class ProviderCredential:
    """Statut d'identifiant simple (un seul champ) pour un fournisseur — ne contient jamais le
    secret lui-même. Utilisé pour les fournisseurs à une seule clé API (EODHD, Dukascopy...)."""

    provider: str
    configured: bool
    source: str  # "env" | "settings_file" | "missing"
    message: str


@dataclass(frozen=True)
class ProviderCredentialStatus:
    """Statut d'identifiants multi-champs pour un fournisseur (ex. IG) — ne contient jamais la
    valeur d'un secret, seulement l'origine de chaque champ."""

    provider: str
    configured: bool
    field_status: dict  # nom de champ -> "env" | "settings_file" | "missing"
    message: str


@dataclass(frozen=True)
class EodhdCredentials:
    """Identifiant EODHD résolu — ne révèle jamais api_key dans repr()/str()."""

    api_key: Optional[str] = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def __repr__(self) -> str:  # noqa: D105 — volontairement redigé, voir docstring module
        return f"EodhdCredentials(api_key={_redacted_flag(self.api_key)}, configured={self.configured})"


@dataclass(frozen=True)
class IgCredentials:
    """Identifiants IG résolus — ne révèle jamais api_key/identifier/password/account_id dans
    repr()/str(). `environment` n'est pas un secret (attendu : "demo") et reste visible."""

    api_key: Optional[str] = None
    identifier: Optional[str] = None
    password: Optional[str] = None
    environment: Optional[str] = None
    account_id: Optional[str] = None

    @property
    def configured(self) -> bool:
        """True si les identifiants minimaux pour ouvrir une session sont présents."""
        return bool(self.api_key and self.identifier and self.password)

    def __repr__(self) -> str:  # noqa: D105 — volontairement redigé, voir docstring module
        return (
            "IgCredentials("
            f"api_key={_redacted_flag(self.api_key)}, "
            f"identifier={_redacted_flag(self.identifier)}, "
            f"password={_redacted_flag(self.password)}, "
            f"environment={self.environment!r}, "
            f"account_id={_redacted_flag(self.account_id)}, "
            f"configured={self.configured})"
        )


def _read_settings_data(path: Union[str, Path]) -> dict:
    """Lecture tolérante de settings/data_providers.json : fichier absent, illisible ou invalide
    renvoie un dict vide, jamais d'exception."""
    target = Path(path)
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write_json(target: Path, data: dict) -> None:
    """Écriture atomique commune (fichier temporaire + os.replace, cleanup en cas d'erreur)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".json.tmp")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, target)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


def env_var_name(provider: str) -> str:
    """Nom de la variable d'environnement attendue pour ce fournisseur."""
    return f"BACKTEST_{provider.strip().upper()}_API_KEY"


def get_api_key(
    provider: str, path: Union[str, Path] = DEFAULT_PROVIDER_SETTINGS_PATH
) -> Optional[str]:
    """Résout la clé API d'un fournisseur : variable d'environnement en priorité, sinon
    settings/data_providers.json. Retourne None si aucune des deux n'est renseignée."""
    env_value = os.environ.get(env_var_name(provider))
    if env_value:
        return env_value

    entry = _read_settings_data(path).get(provider)
    if not isinstance(entry, dict):
        return None
    value = entry.get("api_key")
    return value or None


def credential_status(
    provider: str, path: Union[str, Path] = DEFAULT_PROVIDER_SETTINGS_PATH
) -> ProviderCredential:
    """Statut lisible pour l'UI/les logs — sans jamais exposer la valeur du secret."""
    env_var = env_var_name(provider)
    if os.environ.get(env_var):
        return ProviderCredential(
            provider=provider,
            configured=True,
            source="env",
            message=f"Clé API trouvée dans la variable d'environnement {env_var}.",
        )

    key = get_api_key(provider, path=path)
    if key:
        return ProviderCredential(
            provider=provider,
            configured=True,
            source="settings_file",
            message=f"Clé API trouvée dans {Path(path).name}.",
        )

    return ProviderCredential(
        provider=provider,
        configured=False,
        source="missing",
        message=(
            f"Aucune clé API pour {provider!r}. Définis la variable d'environnement {env_var} "
            f"ou ajoute-la dans {Path(path).name} (fichier local, jamais versionné)."
        ),
    )


def save_api_key(
    provider: str, api_key: str, path: Union[str, Path] = DEFAULT_PROVIDER_SETTINGS_PATH
) -> None:
    """Sauvegarde locale de la clé (écriture atomique). N'est jamais appelée automatiquement —
    c'est une action explicite (future UI ou script). Le fichier cible reste hors Git."""
    if not api_key or not api_key.strip():
        raise ValueError("La clé API ne peut pas être vide.")

    target = Path(path)
    data = _read_settings_data(path)
    data[provider] = {"api_key": api_key.strip()}
    _atomic_write_json(target, data)


def get_ig_credentials(
    path: Union[str, Path] = DEFAULT_PROVIDER_SETTINGS_PATH,
) -> IgCredentials:
    """Résout les identifiants IG. Chaque champ (sauf password) suit la même priorité que
    get_api_key() : variable d'environnement, sinon settings/data_providers.json["ig"].
    `password` est résolu UNIQUEMENT depuis BACKTEST_IG_PASSWORD, jamais depuis le fichier —
    voir docstring du module."""
    entry = _read_settings_data(path).get("ig")
    file_values = entry if isinstance(entry, dict) else {}

    def _resolve(field: str) -> Optional[str]:
        env_value = os.environ.get(f"BACKTEST_IG_{field.upper()}")
        if env_value:
            return env_value
        if field not in _IG_FILE_BACKED_FIELDS:
            return None
        value = file_values.get(field)
        return value or None

    return IgCredentials(
        api_key=_resolve("api_key"),
        identifier=_resolve("identifier"),
        password=_resolve("password"),
        environment=_resolve("environment"),
        account_id=_resolve("account_id"),
    )


def save_ig_credentials(
    *,
    api_key: Optional[str] = None,
    identifier: Optional[str] = None,
    environment: Optional[str] = None,
    account_id: Optional[str] = None,
    path: Union[str, Path] = DEFAULT_PROVIDER_SETTINGS_PATH,
) -> None:
    """Sauvegarde locale des champs IG non sensibles (écriture atomique).

    Ne prend volontairement AUCUN paramètre `password` : il est donc structurellement
    impossible d'écrire un mot de passe IG dans settings/data_providers.json avec cette
    fonction. Seuls les champs fournis (non None) sont mis à jour ; les autres champs déjà
    enregistrés pour "ig", ainsi que les autres fournisseurs, restent inchangés."""
    target = Path(path)
    data = _read_settings_data(path)
    existing = data.get("ig")
    entry = dict(existing) if isinstance(existing, dict) else {}

    updates = {
        "api_key": api_key,
        "identifier": identifier,
        "environment": environment,
        "account_id": account_id,
    }
    for field, value in updates.items():
        if value is not None and value.strip():
            entry[field] = value.strip()

    data["ig"] = entry
    _atomic_write_json(target, data)


def ig_credential_status(
    path: Union[str, Path] = DEFAULT_PROVIDER_SETTINGS_PATH,
) -> ProviderCredentialStatus:
    """Statut IG lisible pour l'UI/les logs — ne renvoie jamais la valeur d'un secret.

    `configured` est True seulement si api_key, identifier et password sont tous les trois
    présents (le minimum pour ouvrir une session IG)."""
    creds = get_ig_credentials(path=path)

    def _origin(field: str, value: Optional[str]) -> str:
        if not value:
            return "missing"
        if os.environ.get(f"BACKTEST_IG_{field.upper()}"):
            return "env"
        return "settings_file"

    field_status = {
        "api_key": _origin("api_key", creds.api_key),
        "identifier": _origin("identifier", creds.identifier),
        "password": _origin("password", creds.password),
        "environment": _origin("environment", creds.environment),
        "account_id": _origin("account_id", creds.account_id),
    }

    missing = [f for f in ("api_key", "identifier", "password") if field_status[f] == "missing"]
    if not missing:
        message = "Identifiants IG configurés (api_key, identifier, password présents)."
    else:
        message = (
            "Identifiants IG incomplets, champs manquants : "
            + ", ".join(missing)
            + ". Définis les variables d'environnement BACKTEST_IG_<CHAMP> correspondantes "
            "(le mot de passe ne peut être défini que par variable d'environnement)."
        )

    return ProviderCredentialStatus(
        provider="ig",
        configured=creds.configured,
        field_status=field_status,
        message=message,
    )
