"""
tests/conftest.py — Configuration pytest partagée.

Isole systématiquement la suite de tests des vraies variables d'environnement sensibles
(clés API fournisseurs, identifiants IG, drapeau de tests réels) présentes sur la machine de
développement. Sans cela, un test qui ne fait pas explicitement `monkeypatch.delenv(...)` peut
lire une vraie clé (ex. BACKTEST_EODHD_API_KEY) et donner un résultat différent selon la machine
— voir l'incident constaté sur tests/test_market_data_provider_config.py (2026-08-06).

Chaque test reste libre de redéfinir une valeur via son propre `monkeypatch.setenv(...)` : cette
fixture autouse s'exécute avant le corps du test, donc un `setenv` dans le test prend le dessus.
"""

from __future__ import annotations

import pytest

# Variables sensibles ou influençant le comportement réseau, à neutraliser par défaut dans toute
# la suite de tests hors ligne. Un script de test réel dédié (scripts/test_*_connection.py) n'est
# pas concerné : il n'est pas exécuté par pytest.
_SENSITIVE_ENV_VARS: tuple[str, ...] = (
    "BACKTEST_EODHD_API_KEY",
    "BACKTEST_IG_API_KEY",
    "BACKTEST_IG_IDENTIFIER",
    "BACKTEST_IG_PASSWORD",
    "BACKTEST_IG_ENVIRONMENT",
    "BACKTEST_IG_ACCOUNT_ID",
    "BACKTEST_RUN_LIVE_PROVIDER_TESTS",
)


@pytest.fixture(autouse=True)
def _isolate_provider_env_vars(monkeypatch):
    """Neutralise les variables d'environnement sensibles avant chaque test, par défaut."""
    for var in _SENSITIVE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
