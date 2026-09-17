"""
tests/test_autopilot_mission_queue.py — Autopilot V1.1 (2026-09-17), mission §4/§5/§7.

File de missions persistée (`.autopilot/missions.json`), sélection respectant les dépendances
déclarées — jamais une mission dont un prérequis n'est pas `DONE`. V1.1 : schéma enrichi
(scope/tests/risque/preuves) + validation stricte au chargement — un fichier absent, un statut
inconnu ou un prompt_file introuvable doit produire une erreur explicite, jamais une file vide
silencieuse ni un faux `COMPLETED` (mission Autopilot V1.1 §4).
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.mission_queue import (
    Mission,
    MissionQueueError,
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


def test_load_missions_raises_on_a_missing_file(tmp_path):
    """Régression — mission Autopilot V1.1 §4 : un fichier absent ne doit JAMAIS produire
    silencieusement une file vide (qui atteindrait `COMPLETED` à tort). Avant V1.1, ce cas
    retournait `[]` — comportement délibérément changé, voir aussi `_handle_ready`/`_handle_planning`
    dans `supervisor.py`, qui routent désormais cette erreur vers `BLOCKED_SAFETY`."""
    with pytest.raises(MissionQueueError):
        load_missions(tmp_path / "does_not_exist.json")


def test_save_missions_can_be_called_repeatedly_to_persist_status_changes(tmp_path):
    path = tmp_path / "missions.json"
    save_missions(path, _missions())
    missions = load_missions(path)
    updated = mark_mission_status(missions, "M1", "DONE")
    save_missions(path, updated)

    reloaded = load_missions(path)
    assert reloaded[0].status == "DONE"


def test_load_missions_raises_on_malformed_json(tmp_path):
    path = tmp_path / "missions.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(MissionQueueError):
        load_missions(path)


def test_load_missions_raises_when_missions_key_is_missing(tmp_path):
    path = tmp_path / "missions.json"
    path.write_text('{"not_missions": []}', encoding="utf-8")
    with pytest.raises(MissionQueueError):
        load_missions(path)


def test_load_missions_raises_on_missing_required_field(tmp_path):
    path = tmp_path / "missions.json"
    path.write_text('{"missions": [{"id": "M1", "title": "x", "status": "PLANNED"}]}', encoding="utf-8")
    with pytest.raises(MissionQueueError):
        load_missions(path)


def test_load_missions_raises_on_unknown_status(tmp_path):
    path = tmp_path / "missions.json"
    path.write_text(
        '{"missions": [{"id": "M1", "title": "x", "status": "SORT_OF_DONE", "prompt_file": "m1.md"}]}',
        encoding="utf-8",
    )
    with pytest.raises(MissionQueueError):
        load_missions(path)


def test_load_missions_raises_when_prompt_file_is_unreachable_under_prompts_base_dir(tmp_path):
    path = tmp_path / "missions.json"
    save_missions(path, [Mission(id="M1", title="x", status="PLANNED", prompt_file="does-not-exist.md")])
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    with pytest.raises(MissionQueueError):
        load_missions(path, prompts_base_dir=prompts_dir)


def test_load_missions_succeeds_when_prompt_file_exists_under_prompts_base_dir(tmp_path):
    path = tmp_path / "missions.json"
    save_missions(path, [Mission(id="M1", title="x", status="PLANNED", prompt_file="m1.md")])
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "m1.md").write_text("Contenu du prompt.", encoding="utf-8")

    loaded = load_missions(path, prompts_base_dir=prompts_dir)
    assert loaded[0].id == "M1"


def test_mission_carries_the_enriched_v1_1_scope_and_evidence_fields():
    mission = Mission(
        id="M1", title="x", status="PLANNED", prompt_file="m1.md",
        allowed_paths=("scripts/autopilot/",), forbidden_paths=("app_corrupted_backup.py",),
        targeted_tests=("tests/test_autopilot_state_machine.py",), regression_tests=("autopilot",),
        risk_level="medium", max_attempts=5, max_budget_usd=3.0, requires_clean_worktree=True,
        scientific_contracts=("ADR-0021",), human_gate_conditions=("modification FINAL_HOLDOUT",),
        completion_evidence=("tests verts", "review sans BLOQUANT"),
    )
    assert mission.risk_level == "medium"
    assert mission.max_attempts == 5
    assert mission.scientific_contracts == ("ADR-0021",)


def test_enriched_fields_round_trip_through_save_and_load(tmp_path):
    path = tmp_path / "missions.json"
    mission = Mission(
        id="M1", title="x", status="PLANNED", prompt_file="m1.md",
        allowed_paths=("scripts/autopilot/",), targeted_tests=("tests/test_x.py",),
        risk_level="high", max_attempts=2, max_budget_usd=1.5, requires_clean_worktree=False,
        scientific_contracts=("ADR-0021",), human_gate_conditions=(), completion_evidence=("x",),
    )
    save_missions(path, [mission])
    loaded = load_missions(path)[0]
    assert loaded.allowed_paths == ("scripts/autopilot/",)
    assert loaded.targeted_tests == ("tests/test_x.py",)
    assert loaded.risk_level == "high"
    assert loaded.max_attempts == 2
    assert loaded.max_budget_usd == 1.5
    assert loaded.requires_clean_worktree is False
    assert loaded.scientific_contracts == ("ADR-0021",)
    assert loaded.completion_evidence == ("x",)


def test_mission_defaults_are_safe_when_fields_are_absent_from_json(tmp_path):
    path = tmp_path / "missions.json"
    path.write_text(
        '{"missions": [{"id": "M1", "title": "x", "status": "PLANNED", "prompt_file": "m1.md"}]}',
        encoding="utf-8",
    )
    loaded = load_missions(path)[0]
    assert loaded.risk_level == "low"
    assert loaded.max_attempts == 3
    assert loaded.max_budget_usd is None
    assert loaded.requires_clean_worktree is True
    assert loaded.allowed_paths == ()
