"""
tests/test_autopilot_state_machine.py — Bootstrap Autopilot V1 (2026-09-17).

Machine à états explicite (mission Bootstrap Autopilot, §6) : transitions autorisées, enregistrement
atomique de chaque transition, tolérance à un fichier d'état corrompu/absent (reprise après
crash), jamais de secret dans l'état.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.state_machine import (
    ALL_STATES,
    ALLOWED_TRANSITIONS,
    AutopilotState,
    AutopilotStateRecord,
    IllegalTransitionError,
    AutopilotStateStore,
    build_state_record,
)


def test_all_18_states_are_defined():
    expected = {
        "BOOTSTRAPPING", "READY", "PLANNING", "DEVELOPING", "TESTING", "REVIEWING",
        "CORRECTING", "PRE_COMMIT_CHECK", "COMMITTING", "PUSHING", "CHECKPOINTED",
        "NEXT_MISSION", "WAITING_FOR_CLAUDE", "WAITING_FOR_EXTERNAL_RESOURCE",
        "HUMAN_GATE_REQUIRED", "BLOCKED_SAFETY", "COMPLETED", "STOPPED",
    }
    assert {s.value for s in ALL_STATES} == expected


def test_every_state_has_an_entry_in_the_transition_table():
    for state in ALL_STATES:
        assert state in ALLOWED_TRANSITIONS, f"{state} manque dans ALLOWED_TRANSITIONS"


def test_terminal_states_have_no_outgoing_transition():
    assert ALLOWED_TRANSITIONS[AutopilotState.COMPLETED] == ()


def test_normal_happy_path_transitions_are_allowed():
    path = [
        AutopilotState.BOOTSTRAPPING, AutopilotState.READY, AutopilotState.PLANNING,
        AutopilotState.DEVELOPING, AutopilotState.TESTING, AutopilotState.REVIEWING,
        AutopilotState.PRE_COMMIT_CHECK, AutopilotState.COMMITTING, AutopilotState.PUSHING,
        AutopilotState.CHECKPOINTED, AutopilotState.NEXT_MISSION,
    ]
    for a, b in zip(path, path[1:]):
        assert b in ALLOWED_TRANSITIONS[a], f"{a} -> {b} devrait être autorisée"


def test_transition_table_covers_every_target_the_supervisor_actually_uses():
    """Régression — revue safety/architecture du Bootstrap (2026-09-17), 3 BLOCKERs empiriquement
    reproduits : `supervisor._handle_planning`/`_handle_failure` demandaient des transitions que
    cette table refusait, crashant le superviseur avec `IllegalTransitionError` en usage normal
    (ex. file de missions vidée entre deux étapes, échec réseau/répété depuis DEVELOPING/TESTING).
    Chacune de ces arêtes doit être explicitement présente, jamais retrouvée par accident."""
    assert AutopilotState.COMPLETED in ALLOWED_TRANSITIONS[AutopilotState.PLANNING]
    assert AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE in ALLOWED_TRANSITIONS[AutopilotState.DEVELOPING]
    assert AutopilotState.HUMAN_GATE_REQUIRED in ALLOWED_TRANSITIONS[AutopilotState.TESTING]
    assert AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE in ALLOWED_TRANSITIONS[AutopilotState.TESTING]


def test_transition_table_covers_v1_1_escalation_and_resume_targets():
    """Régression — revue safety/architecture V1.1, 2 BLOCKERs empiriquement reproduits :
    (1) `REVIEWING` n'autorisait pas `HUMAN_GATE_REQUIRED`, alors que `_handle_reviewing()` route
    un échec technique de review à travers `_handle_failure()` — qui peut escalader vers ce même
    état — crashant sur un échec de review pourtant ordinaire et répété. (2) le repli de
    `_resume_to_recorded_phase()` (`PLANNING`) n'était pas autorisé depuis `WAITING_FOR_CLAUDE`,
    crashant toute reprise d'un fichier d'état pré-V1.1 (`resume_to_phase` absent/`None` par
    défaut) ou d'un état corrompu/invalide."""
    assert AutopilotState.HUMAN_GATE_REQUIRED in ALLOWED_TRANSITIONS[AutopilotState.REVIEWING]
    assert AutopilotState.PLANNING in ALLOWED_TRANSITIONS[AutopilotState.WAITING_FOR_CLAUDE]


def test_illegal_transition_is_rejected(tmp_path):
    """READY -> PUSHING n'a aucun sens (aucune mission planifiée/développée/testée entre les
    deux) — doit être rejetée, jamais silencieusement acceptée."""
    store = AutopilotStateStore(tmp_path / "state.json")
    record = build_state_record(phase=AutopilotState.READY, mission_id=None, branch="master")
    store.save(record)

    with pytest.raises(IllegalTransitionError):
        store.transition_to(AutopilotState.PUSHING)


def test_state_store_round_trips_a_record(tmp_path):
    store = AutopilotStateStore(tmp_path / "state.json")
    record = build_state_record(
        phase=AutopilotState.READY, mission_id="M-001", branch="master",
        head="abc123", origin_master="abc123", next_action="planifier la mission suivante",
    )
    store.save(record)

    loaded = store.load()
    assert loaded.phase == "READY"
    assert loaded.mission_id == "M-001"
    assert loaded.head == "abc123"


def test_state_store_load_tolerates_missing_file(tmp_path):
    store = AutopilotStateStore(tmp_path / "does_not_exist.json")
    assert store.load() is None


def test_state_store_load_tolerates_corrupted_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = AutopilotStateStore(path)
    assert store.load() is None


def test_state_store_transition_appends_a_new_record_overwriting_the_current_one(tmp_path):
    store = AutopilotStateStore(tmp_path / "state.json")
    store.save(build_state_record(phase=AutopilotState.BOOTSTRAPPING, mission_id=None, branch="master"))
    store.transition_to(AutopilotState.READY)

    assert store.load().phase == "READY"


def test_state_store_keeps_a_bounded_history_for_audit(tmp_path):
    """Chaque transition importante doit être enregistrée (mission §6) — l'historique est conservé
    dans un journal séparé de l'état courant, jamais mélangé avec lui, et borné en taille pour ne
    jamais grossir indéfiniment sur une machine longtemps allumée."""
    store = AutopilotStateStore(tmp_path / "state.json", history_limit=3)
    store.save(build_state_record(phase=AutopilotState.BOOTSTRAPPING, mission_id=None, branch="master"))
    for target in (AutopilotState.READY, AutopilotState.PLANNING, AutopilotState.DEVELOPING, AutopilotState.TESTING):
        store.transition_to(target)

    history = store.load_history()
    assert len(history) == 3
    assert [h["phase"] for h in history] == ["PLANNING", "DEVELOPING", "TESTING"]


def test_state_record_never_carries_a_field_named_secret_or_token():
    """Garde-fou simple, mission §6 : "ne jamais inclure de secret dans l'état ou les logs" —
    vérifié structurellement sur les noms de champs du record lui-même."""
    record = build_state_record(phase=AutopilotState.READY, mission_id=None, branch="master")
    forbidden_substrings = ("secret", "token", "password", "api_key", "apikey")
    for field_name in record.__dataclass_fields__:
        lowered = field_name.lower()
        assert not any(bad in lowered for bad in forbidden_substrings), field_name


def test_build_state_record_captures_git_context_fields():
    record = build_state_record(
        phase=AutopilotState.PLANNING, mission_id="M-001", branch="master",
        head="deadbeef", origin_master="deadbeef", scope_files=("a.py", "b.py"),
    )
    assert record.branch == "master"
    assert record.head == "deadbeef"
    assert record.origin_master == "deadbeef"
    assert record.scope_files == ("a.py", "b.py")
    assert record.timestamp_utc.endswith("+00:00") or record.timestamp_utc.endswith("Z")
