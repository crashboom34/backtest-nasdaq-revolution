"""
tests/test_autopilot_mission_queue.py — Bootstrap Autopilot V1 (2026-09-17), mission §5/§7.

File de missions persistée (`.autopilot/missions.json`), sélection respectant les dépendances
déclarées — jamais une mission dont un prérequis n'est pas `DONE`.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.mission_queue import (
    Mission,
    load_missions,
    mark_mission_status,
    save_missions,
    select_next_mission,
)


def _missions():
    return [
        Mission(id="M1", title="Première mission", status="PLANNED", prompt_file="m1.md", depends_on=()),
        Mission(id="M2", title="Deuxième mission", status="PLANNED", prompt_file="m2.md", depends_on=("M1",)),
        Mission(id="M3", title="Troisième mission", status="PLANNED", prompt_file="m3.md", depends_on=("M2",)),
    ]


def test_selects_the_first_mission_with_no_dependency():
    missions = _missions()
    selected = select_next_mission(missions)
    assert selected.id == "M1"


def test_does_not_select_a_mission_whose_dependency_is_not_done():
    missions = _missions()
    missions[0] = Mission(**{**missions[0].__dict__, "status": "IN_PROGRESS"})
    selected = select_next_mission(missions)
    assert selected is None


def test_selects_a_mission_once_its_dependency_is_done():
    missions = _missions()
    missions[0] = Mission(**{**missions[0].__dict__, "status": "DONE"})
    selected = select_next_mission(missions)
    assert selected.id == "M2"


def test_no_selectable_mission_returns_none():
    missions = [Mission(id="M1", title="x", status="DONE", prompt_file="m1.md", depends_on=())]
    assert select_next_mission(missions) is None


def test_a_blocked_mission_is_never_selected():
    missions = [Mission(id="M1", title="x", status="BLOCKED", prompt_file="m1.md", depends_on=())]
    assert select_next_mission(missions) is None


def test_mark_mission_status_updates_only_the_target_mission():
    missions = _missions()
    updated = mark_mission_status(missions, "M1", "DONE")
    by_id = {m.id: m.status for m in updated}
    assert by_id == {"M1": "DONE", "M2": "PLANNED", "M3": "PLANNED"}


def test_mark_mission_status_does_not_mutate_the_input_list():
    missions = _missions()
    mark_mission_status(missions, "M1", "DONE")
    assert missions[0].status == "PLANNED"


def test_save_and_load_missions_round_trip(tmp_path):
    path = tmp_path / "missions.json"
    save_missions(path, _missions())
    loaded = load_missions(path)
    assert [m.id for m in loaded] == ["M1", "M2", "M3"]
    assert loaded[1].depends_on == ("M1",)


def test_load_missions_tolerates_a_missing_file(tmp_path):
    assert load_missions(tmp_path / "does_not_exist.json") == []


def test_save_missions_can_be_called_repeatedly_to_persist_status_changes(tmp_path):
    path = tmp_path / "missions.json"
    save_missions(path, _missions())
    missions = load_missions(path)
    updated = mark_mission_status(missions, "M1", "DONE")
    save_missions(path, updated)

    reloaded = load_missions(path)
    assert reloaded[0].status == "DONE"
