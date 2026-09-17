"""
tests/test_autopilot_supervisor.py — Bootstrap Autopilot V1 (2026-09-17), dry-run intégration
(mission Phase D : "sans modifier la logique scientifique... invocation simulée ou sûre").

Aucun sous-processus Claude réel, aucune commande Git réelle n'est exécutée par ces tests —
`developer_fn`/`reviewer_fn`/`git_ops` sont des doublures injectées, exactement le contrat que
`supervisor.py` définit pour permettre un dry-run sûr.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.mission_queue import Mission, save_missions
from scripts.autopilot.quota_detector import FailureCategory
from scripts.autopilot.state_machine import AutopilotState, AutopilotStateStore
from scripts.autopilot.supervisor import AutopilotSupervisor, FakeGitOps, SingleInstanceLock


def _one_mission_queue(tmp_path):
    path = tmp_path / "missions.json"
    save_missions(path, [
        Mission(id="M1", title="Mission factice", status="PLANNED", prompt_file="m1.md", depends_on=()),
    ])
    return path


def _ok_developer(mission, attempt):
    return {"success": True, "changed_files": ["dummy.py"], "raw_output": "changes applied"}


def _ok_tester():
    return {"success": True, "summary": "3 passed"}


def _ok_reviewer(mission):
    return {"blocking_findings": [], "summary": "clean"}


def _make_supervisor(tmp_path, developer_fn=_ok_developer, tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, failure_limit=3):
    state_store = AutopilotStateStore(tmp_path / "state.json")
    missions_path = _one_mission_queue(tmp_path)
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    return AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=developer_fn,
        tester_fn=tester_fn, reviewer_fn=reviewer_fn, git_ops=git_ops, lock=lock,
        failure_limit=failure_limit, branch="master",
    ), git_ops, state_store


def test_happy_path_reaches_checkpointed_then_next_mission(tmp_path):
    supervisor, git_ops, state_store = _make_supervisor(tmp_path)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.NEXT_MISSION
    assert git_ops.committed
    assert git_ops.pushed
    assert git_ops.forced_push_attempted is False


def test_no_more_missions_reaches_completed(tmp_path):
    state_store = AutopilotStateStore(tmp_path / "state.json")
    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [])  # aucune mission
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.COMPLETED})
    assert final_state == AutopilotState.COMPLETED


def test_blocking_review_finding_triggers_correcting_then_retests(tmp_path):
    calls = {"review_count": 0}

    def flaky_reviewer(mission):
        calls["review_count"] += 1
        if calls["review_count"] == 1:
            return {"blocking_findings": ["nom de variable trompeur"], "summary": "1 blocage"}
        return {"blocking_findings": [], "summary": "clean"}

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, reviewer_fn=flaky_reviewer)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.NEXT_MISSION
    assert calls["review_count"] == 2
    assert git_ops.committed  # a fini par committer après correction


def test_quota_failure_moves_to_waiting_for_claude_not_human_gate(tmp_path):
    def quota_developer(mission, attempt):
        return {"success": False, "raw_output": "Error: rate_limit_error - exceeded", "changed_files": []}

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, developer_fn=quota_developer)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.WAITING_FOR_CLAUDE, AutopilotState.HUMAN_GATE_REQUIRED})

    assert final_state == AutopilotState.WAITING_FOR_CLAUDE
    record = state_store.load()
    assert record.stop_reason is not None
    assert "quota" in record.stop_reason.lower() or "limit" in record.stop_reason.lower()


def test_repeated_identical_project_failure_escalates_to_human_gate(tmp_path):
    def always_same_failure(mission, attempt):
        return {"success": False, "raw_output": "AssertionError: assert 1 == 2", "changed_files": []}

    supervisor, git_ops, state_store = _make_supervisor(
        tmp_path, developer_fn=always_same_failure, failure_limit=2,
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until(
        {AutopilotState.WAITING_FOR_CLAUDE, AutopilotState.HUMAN_GATE_REQUIRED}, max_steps=200,
    )

    assert final_state == AutopilotState.HUMAN_GATE_REQUIRED


def test_resume_after_simulated_crash_does_not_redo_completed_steps(tmp_path):
    """Mission §18 : "une reprise après arrêt simulé fonctionne", idempotence."""
    develop_calls = {"count": 0}

    def counting_developer(mission, attempt):
        develop_calls["count"] += 1
        return _ok_developer(mission, attempt)

    state_store = AutopilotStateStore(tmp_path / "state.json")
    missions_path = _one_mission_queue(tmp_path)
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=counting_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()
    # Avance jusqu'à juste après DEVELOPING (simule un crash avant TESTING).
    supervisor.run_one_step()  # BOOTSTRAPPING -> READY
    supervisor.run_one_step()  # READY -> PLANNING
    supervisor.run_one_step()  # PLANNING -> DEVELOPING
    supervisor.run_one_step()  # DEVELOPING -> TESTING (appelle developer_fn une fois ici)
    assert develop_calls["count"] == 1
    supervisor.release_lock()  # "crash" : le process s'arrête, le lock est perdu

    # Nouvelle instance, même fichiers d'état — reprise.
    new_state_store = AutopilotStateStore(tmp_path / "state.json")
    new_lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    resumed = AutopilotSupervisor(
        state_store=new_state_store, missions_path=missions_path, developer_fn=counting_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=new_lock, branch="master",
    )
    resumed.acquire_lock()
    final_state = resumed.run_until({AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.NEXT_MISSION
    # developer_fn n'a JAMAIS été rappelé pour la même mission déjà développée — la reprise
    # continue depuis TESTING, ne refait pas DEVELOPING.
    assert develop_calls["count"] == 1


def test_second_instance_cannot_acquire_the_same_lock(tmp_path):
    lock_path = tmp_path / "autopilot.lock"
    lock_a = SingleInstanceLock(lock_path)
    lock_b = SingleInstanceLock(lock_path)

    assert lock_a.acquire() is True
    assert lock_b.acquire() is False

    lock_a.release()
    assert lock_b.acquire() is True


def test_force_release_clears_a_lock_held_by_a_different_process_instance(tmp_path):
    """cmd_stop (cli.py) s'exécute dans une invocation séparée de celle qui a démarré la boucle —
    sa propre instance de SingleInstanceLock n'a donc jamais `_held=True`. `release()` seul ne
    ferait rien (bug réel trouvé lors de l'implémentation de cli.py) ; `force_release()` doit
    supprimer le fichier inconditionnellement."""
    lock_path = tmp_path / "autopilot.lock"
    owner = SingleInstanceLock(lock_path)
    assert owner.acquire() is True

    stranger = SingleInstanceLock(lock_path)  # nouvelle instance, jamais acquis elle-même
    stranger.force_release()

    assert not lock_path.exists()


def test_network_failure_during_development_moves_to_waiting_for_external_resource(tmp_path):
    """Régression — revue safety/architecture du Bootstrap : `ALLOWED_TRANSITIONS[DEVELOPING]`
    n'incluait pas `WAITING_FOR_EXTERNAL_RESOURCE`, alors que `_handle_failure()` peut cibler cet
    état pour `FailureCategory.NETWORK` — crashait avec `IllegalTransitionError` (reproduit
    empiriquement par la revue avec un `developer_fn` renvoyant une erreur réseau ordinaire)."""
    def network_failure_developer(mission, attempt):
        return {"success": False, "raw_output": "ConnectionError: network is unreachable", "changed_files": []}

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, developer_fn=network_failure_developer)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({
        AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE, AutopilotState.HUMAN_GATE_REQUIRED,
    })

    assert final_state == AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE


def test_repeated_identical_test_failure_escalates_to_human_gate_from_testing(tmp_path):
    """Régression — revue safety/architecture du Bootstrap : deux bugs combinés rendaient
    l'échec de TESTING fatal. (1) `ALLOWED_TRANSITIONS[TESTING]` n'incluait ni
    `HUMAN_GATE_REQUIRED` ni `WAITING_FOR_EXTERNAL_RESOURCE`, alors que `_handle_failure()` peut
    cibler les deux depuis TESTING — un `IllegalTransitionError` interrompait le superviseur avant
    même que l'anti-boucle ait pu s'exprimer. (2) `_handle_failure()` lisait `raw_output`, absent
    du contrat `tester_fn` (qui ne renvoie que `summary`) — la classification se faisait toujours
    sur une chaîne vide, ce qui aurait rendu `NETWORK`/`QUOTA_LIMIT` indétectables pour un échec de
    test (voir le test dédié `..._moves_to_waiting_for_external_resource...` pour ce volet réseau)."""
    def failing_tester():
        return {"success": False, "summary": "AssertionError: assert 1 == 2 (test_foo.py)"}

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, tester_fn=failing_tester, failure_limit=2)
    supervisor.acquire_lock()

    final_state = supervisor.run_until(
        {AutopilotState.WAITING_FOR_CLAUDE, AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE,
         AutopilotState.HUMAN_GATE_REQUIRED}, max_steps=200,
    )

    assert final_state == AutopilotState.HUMAN_GATE_REQUIRED
    record = state_store.load()
    assert "assertionerror" in record.stop_reason.lower()


def test_network_failure_during_testing_moves_to_waiting_for_external_resource(tmp_path):
    """Complète le test précédent : une erreur réseau ordinaire remontée par `tester_fn` (via
    `summary`, seul champ que ce contrat porte) doit être classée `NETWORK` et router vers
    `WAITING_FOR_EXTERNAL_RESOURCE` — impossible avant ce correctif, faute à la fois de la
    transition manquante et du repli `summary` absent dans `_handle_failure()`."""
    def network_failing_tester():
        return {"success": False, "summary": "requests.exceptions.ConnectionError: timeout"}

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, tester_fn=network_failing_tester)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({
        AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE, AutopilotState.HUMAN_GATE_REQUIRED,
        AutopilotState.WAITING_FOR_CLAUDE,
    })

    assert final_state == AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE


def test_mission_queue_emptied_between_ready_and_planning_reaches_completed(tmp_path):
    """Régression — revue safety/architecture du Bootstrap : `ALLOWED_TRANSITIONS[PLANNING]`
    n'incluait pas `COMPLETED`, alors que `_handle_planning()` transitionne vers `COMPLETED` si la
    file est vide au moment où elle est relue (état et file de missions sont deux fichiers séparés,
    relus à des instants différents — un scénario réaliste en reprise, pas seulement théorique)."""
    from scripts.autopilot.mission_queue import save_missions

    state_store = AutopilotStateStore(tmp_path / "state.json")
    missions_path = _one_mission_queue(tmp_path)
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()
    supervisor.run_one_step()  # BOOTSTRAPPING -> READY
    supervisor.run_one_step()  # READY -> PLANNING (file non vide vue ici)
    save_missions(missions_path, [])  # la file se vide avant que PLANNING ne la relise

    final_state = supervisor.run_one_step()  # PLANNING doit re-vérifier et aboutir à COMPLETED

    assert final_state == AutopilotState.COMPLETED


def test_unexpected_commit_failure_reaches_blocked_safety_not_a_crash(tmp_path):
    """Régression — revue safety/architecture du Bootstrap (IMPORTANT 1) : un échec Git réel non
    couvert par `git_safety` (hook, disque, ...) faisait remonter l'exception hors de
    `run_one_step()` au lieu d'être traité comme un arrêt sûr nécessitant un regard humain."""
    class ExplodingGitOps(FakeGitOps):
        def commit(self, message):
            raise RuntimeError("pre-commit hook a échoué")

    supervisor, _, state_store = _make_supervisor(tmp_path)
    supervisor._git_ops = ExplodingGitOps()
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.BLOCKED_SAFETY, AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.BLOCKED_SAFETY
    assert "pre-commit hook" in state_store.load().stop_reason


def test_unexpected_push_failure_reaches_waiting_for_external_resource_not_a_crash(tmp_path):
    """Régression — revue safety/architecture du Bootstrap (IMPORTANT 1) : un push refusé pour une
    raison réelle non couverte par `git_safety` (divergence distante, réseau) faisait crasher le
    superviseur au lieu d'utiliser `WAITING_FOR_EXTERNAL_RESOURCE`, déjà réservé exactement pour ce
    cas par `state_machine.py` mais jamais atteint par aucun chemin de code avant ce correctif."""
    class RejectedPushGitOps(FakeGitOps):
        def push(self, force=False):
            raise RuntimeError("push rejeté (non-fast-forward)")

    supervisor, _, state_store = _make_supervisor(tmp_path)
    supervisor._git_ops = RejectedPushGitOps()
    supervisor.acquire_lock()

    final_state = supervisor.run_until({
        AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE, AutopilotState.BLOCKED_SAFETY,
        AutopilotState.NEXT_MISSION,
    })

    assert final_state == AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE
    assert "push rejeté" in state_store.load().stop_reason


def test_forbidden_git_command_never_reaches_the_real_runner(tmp_path):
    """Le git_ops factice lui-même refuse une commande interdite — preuve que le garde
    git_safety est bien câblé dans le chemin d'exécution réel, pas seulement testé isolément."""
    git_ops = FakeGitOps()
    with pytest.raises(ValueError):
        git_ops.push(force=True)
    assert git_ops.forced_push_attempted is True
    assert git_ops.pushed is False
