"""
scripts/test_ig_connection.py — Petit test de connexion IG (démo uniquement), pour un débutant.

Usage :
    .\\.venv\\Scripts\\python.exe scripts\\test_ig_connection.py

Ce script n'affiche JAMAIS une clé, un identifiant, un mot de passe, un CST, un
X-SECURITY-TOKEN ou une URL contenant un secret. Il affiche uniquement : configuré / non
configuré / connexion réussie / connexion échouée / une erreur non sensible.

Par défaut, AUCUN appel réseau n'est effectué : il faut explicitement mettre la variable
d'environnement BACKTEST_RUN_LIVE_PROVIDER_TESTS=1 pour autoriser un test réel. Le test réel se
limite à : connexion à l'environnement DÉMO uniquement, une lecture des comptes, puis
déconnexion immédiate. Aucun ordre, aucune position, aucune opération d'écriture n'est jamais
effectuée — ce connecteur ne sait tout simplement pas le faire.

BACKTEST_IG_ENVIRONMENT doit valoir exactement "demo". Toute autre valeur (vide, "live",
"prod"...) est refusée avant le moindre appel réseau.
"""

from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.ig.client import IgClient
from market_data.ig.config import load_ig_config
from market_data.ig.error_codes import explain_ig_error_code
from market_data.ig.errors import IgConfigError, IgEnvironmentRefusedError, IgError
from market_data.provider_config import get_ig_credentials


def _print_failure_details(status_code, error_code, message) -> None:
    """Affiche uniquement : statut HTTP, errorCode IG s'il existe, explication lisible, et le
    message déjà sûr du connecteur. Ne montre jamais une clé, un identifiant, un mot de passe,
    un header, CST/X-SECURITY-TOKEN/OAuth, ni le corps complet d'une requête ou réponse."""
    if status_code is not None:
        print(f"Statut HTTP : {status_code}")
    if error_code:
        print(f"Code IG (errorCode) : {error_code}")
        print(f"Explication : {explain_ig_error_code(error_code)}")
    print(f"Détail (non sensible) : {message}")

LIVE_TEST_ENV_VAR = "BACKTEST_RUN_LIVE_PROVIDER_TESTS"


def main() -> int:
    print("=== Test de connexion IG (démo uniquement) ===")

    creds = get_ig_credentials()
    if not creds.configured:
        print("Identifiants IG : non configuré.")
        print(
            "-> Définis BACKTEST_IG_API_KEY, BACKTEST_IG_IDENTIFIER et BACKTEST_IG_PASSWORD "
            "(variables d'environnement) ainsi que BACKTEST_IG_ENVIRONMENT=demo."
        )
        return 0

    print("Identifiants IG : configuré.")

    if os.environ.get(LIVE_TEST_ENV_VAR) != "1":
        print(
            f"Test réel désactivé ({LIVE_TEST_ENV_VAR} != '1') : aucun appel réseau effectué.\n"
            f"-> Pour tester réellement la connexion, définis {LIVE_TEST_ENV_VAR}=1 puis relance "
            "ce script."
        )
        return 0

    try:
        config = load_ig_config()
    except IgEnvironmentRefusedError as exc:
        print("Environnement refusé.")
        print(f"Détail (non sensible) : {exc}")
        return 1
    except IgConfigError as exc:
        print("Erreur de configuration.")
        print(f"Détail (non sensible) : {exc}")
        return 1

    print("Test réel activé : connexion à l'environnement DÉMO IG (lecture seule)...")
    client = IgClient(config)
    try:
        result = client.test_connection()
    except IgError as exc:
        print("Connexion échouée.")
        _print_failure_details(getattr(exc, "status_code", None), getattr(exc, "error_code", None), exc)
        return 1

    if not result.ok:
        print("Connexion échouée.")
        _print_failure_details(result.status_code, result.error_code, result.message)
        return 1

    print("Connexion réussie.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
