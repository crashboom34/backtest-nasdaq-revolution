"""
tests/test_canary_finalization.py — fixture JETABLE pour le canary de validation intégrée de
l'Autopilot (mission finalisation V1.1 §4). JAMAIS un test scientifique — vérifie uniquement
`scripts/autopilot/canary_fixture.py` (lui-même jetable) et un marqueur canary.
"""

from __future__ import annotations

from pathlib import Path

from scripts.autopilot.canary_fixture import format_greeting


def test_format_greeting_repeats_the_expected_number_of_times():
    result = format_greeting("Mira", 3)
    assert result == "Bonjour, Mira ! Bonjour, Mira ! Bonjour, Mira !"


def test_new_canary_marker_file_was_created():
    assert Path(".autopilot/canary/finalization_marker.md").is_file()
