"""
scripts/autopilot/canary_fixture.py — fixture JETABLE pour le canary de validation intégrée de
l'Autopilot (mission finalisation V1.1 §4) — JAMAIS du code scientifique, jamais utilisée par
Slice 2 ni par aucune logique de backtest. Contient un bug INTENTIONNEL, disclosed, sur ce module
canary lui-même — jamais sur `strategies/`/`engine.py`/`optimizer.py`/`walk_forward.py`.
"""

from __future__ import annotations


def format_greeting(name: str, times: int) -> str:
    # BUG intentionnel de FIXTURE (jamais du code scientifique) : ne répète pas le salut `times`
    # fois comme l'exige `tests/test_canary_finalization.py` — le Developer réel doit le corriger.
    return f"Bonjour, {name} !"
