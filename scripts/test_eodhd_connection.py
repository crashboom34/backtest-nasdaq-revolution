"""
scripts/test_eodhd_connection.py — Petit test de connexion EODHD, pour un débutant.

Usage :
    .\\.venv\\Scripts\\python.exe scripts\\test_eodhd_connection.py

Ce script n'affiche JAMAIS une clé, un mot de passe, un token ou une URL contenant un secret.
Il affiche uniquement : configuré / non configuré / connexion réussie / connexion échouée /
une erreur non sensible.

Par défaut, AUCUN appel réseau n'est effectué : il faut explicitement mettre la variable
d'environnement BACKTEST_RUN_LIVE_PROVIDER_TESTS=1 pour autoriser un test réel. Le test réel se
limite à : un seul symbole (AAPL.US), une période de quelques jours, quelques kilooctets de
données — jamais un téléchargement volumineux.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

# Évite les accents mal affichés sur la console Windows par défaut (cp1252/cp850). Sans effet
# sur les plateformes où stdout est déjà en UTF-8 ; ne casse jamais le script si indisponible.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.eodhd.client import EodhdClient
from market_data.eodhd.config import load_eodhd_config
from market_data.eodhd.errors import EodhdConfigError, EodhdError
from market_data.provider_config import credential_status

LIVE_TEST_ENV_VAR = "BACKTEST_RUN_LIVE_PROVIDER_TESTS"
SAMPLE_TICKER = "AAPL.US"  # symbole public bien connu, pour une vérification minimale et rapide


def main() -> int:
    print("=== Test de connexion EODHD ===")

    status = credential_status("eodhd")
    if not status.configured:
        print("Clé API EODHD : non configuré.")
        print(
            "-> Définis la variable d'environnement BACKTEST_EODHD_API_KEY, ou utilise "
            "market_data.provider_config.save_api_key('eodhd', ...)."
        )
        return 0

    print(f"Clé API EODHD : configuré (origine : {status.source}).")

    if os.environ.get(LIVE_TEST_ENV_VAR) != "1":
        print(
            f"Test réel désactivé ({LIVE_TEST_ENV_VAR} != '1') : aucun appel réseau effectué.\n"
            f"-> Pour tester réellement la connexion, définis {LIVE_TEST_ENV_VAR}=1 puis relance "
            "ce script."
        )
        return 0

    try:
        config = load_eodhd_config()
        client = EodhdClient(config=config)
    except EodhdConfigError as exc:
        print(f"Erreur de configuration : {exc}")
        return 1

    print("Test réel activé : vérification de la connexion (1 appel API, /user)...")
    result = client.test_connection()
    if not result.ok:
        print("Connexion échouée.")
        print(f"Détail (non sensible) : {result.message}")
        return 1
    print("Connexion réussie.")

    print(f"Petit téléchargement de test ({SAMPLE_TICKER}, 5 derniers jours, EOD)...")
    end = date.today()
    start = end - timedelta(days=5)
    try:
        download = client.download_eod(SAMPLE_TICKER, start_date=start.isoformat(), end_date=end.isoformat())
    except EodhdError as exc:
        print("Téléchargement de test échoué.")
        print(f"Détail (non sensible) : {exc}")
        return 1

    if not download.ok:
        print("Téléchargement de test échoué.")
        print(f"Détail (non sensible) : {download.message}")
        return 1

    row_count = len(download.dataframe) if download.dataframe is not None else 0
    print(f"Téléchargement de test réussi : {row_count} ligne(s) reçue(s) pour {SAMPLE_TICKER}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
