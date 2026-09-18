"""
tests/test_autopilot_quota_detector.py — Bootstrap Autopilot V1 (2026-09-17), mission §13.

Classification PRUDENTE (mission : "Ne pas classer toute erreur réseau ou toute sortie inhabituelle
comme limite de quota") — heuristique documentée comme imparfaite, jamais présentée comme un
détecteur infaillible.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.quota_detector import FailureCategory, classify_failure


def test_classifies_a_quota_message():
    text = "Claude AI usage limit reached. Your limit will reset at 3pm."
    assert classify_failure(text) is FailureCategory.QUOTA_LIMIT


def test_classifies_a_rate_limit_message_as_quota():
    text = "Error: rate_limit_error - Number of request tokens has exceeded your per-minute rate limit"
    assert classify_failure(text) is FailureCategory.QUOTA_LIMIT


def test_classifies_a_monthly_spend_limit_message_as_quota():
    """Régression — bug réel confirmé en conditions réelles (reprise d'AF-V-02 Slice 2, tentative
    4 sur REVIEWING) : `real_reviewer_fn` a réellement reçu
    `{"is_error":true,...,"stop_reason":"stop_sequence",...}` avec, dans le texte complet (tronqué
    à 200 caractères dans `stop_reason` persisté), le message "You've hit your monthly spend
    limit" — jamais reconnu par `_QUOTA_KEYWORDS`, donc classé `UNKNOWN` et traité comme un échec
    ORDINAIRE plutôt que `QUOTA_LIMIT` (mission §13 : "une limite Claude n'est jamais un Human
    Gate"). Conséquence réelle : la mission a escaladé vers HUMAN_GATE_REQUIRED (une décision
    humaine SCIENTIFIQUE apparente) alors que la vraie cause était une limite de dépenses externe,
    nécessitant simplement d'attendre/d'ajuster le plafond — jamais un Human Gate pour ce cas."""
    text = "You've hit your monthly spend limit. Your limit will reset next month."
    assert classify_failure(text) is FailureCategory.QUOTA_LIMIT


def test_classifies_a_network_timeout():
    text = "requests.exceptions.ConnectionError: Failed to establish a new connection: [Errno 11001] getaddrinfo failed"
    assert classify_failure(text) is FailureCategory.NETWORK


def test_classifies_an_auth_error():
    text = "Error: authentication_error - Invalid API key provided"
    assert classify_failure(text) is FailureCategory.AUTH


def test_classifies_a_cli_error():
    text = "claude: command not found"
    assert classify_failure(text) is FailureCategory.CLI_ERROR


def test_classifies_a_project_test_failure_as_project_error():
    text = "AssertionError: assert 3 == 4\nFAILED tests/test_walk_forward.py::test_x"
    assert classify_failure(text) is FailureCategory.PROJECT_ERROR


def test_classifies_a_python_traceback_crash():
    text = "Traceback (most recent call last):\n  File \"supervisor.py\", line 10\nZeroDivisionError: division by zero"
    assert classify_failure(text) is FailureCategory.CRASH


def test_classifies_an_explicit_stop_request():
    text = "STOP_REQUESTED by user"
    assert classify_failure(text) is FailureCategory.STOP_REQUESTED


def test_unrecognized_output_is_unknown_not_quota():
    """Prudence obligatoire (mission §13) : une sortie inhabituelle ne doit jamais être classée
    par défaut comme limite de quota."""
    text = "Some completely unexpected output nobody has ever seen before xyz123"
    assert classify_failure(text) is FailureCategory.UNKNOWN


def test_empty_output_is_unknown():
    assert classify_failure("") is FailureCategory.UNKNOWN


def test_classify_failure_is_case_insensitive_for_quota():
    text = "USAGE LIMIT REACHED"
    assert classify_failure(text) is FailureCategory.QUOTA_LIMIT
