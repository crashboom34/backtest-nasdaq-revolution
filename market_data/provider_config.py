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


@dataclass(frozen=True)
class ProviderCredential:
    """Statut d'identifiant pour un fournisseur — ne contient jamais le secret lui-même."""

    provider: str
    configured: bool
    source: str  # "env" | "settings_file" | "missing"
    message: str


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

    target = Path(path)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    entry = data.get(provider)
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
    target.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if target.is_file():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError, json.JSONDecodeError):
            data = {}

    data[provider] = {"api_key": api_key.strip()}

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
