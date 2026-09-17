"""
tests/test_autopilot_supervisor.py — Autopilot V1.1 (2026-09-17), dry-run intégration
(mission Phase D : "sans modifier la logique scientifique... invocation simulée ou sûre").

Aucun sous-processus Claude réel, aucune commande Git réelle n'est exécutée par ces tests —
`developer_fn`/`reviewer_fn`/`git_ops` sont des doublures injectées, exactement le contrat que
`supervisor.py` définit pour permettre un dry-run sûr.

**V1.1** : `developer_fn` prend désormais `findings=None` (correction pilotée par la review, mission
§3.4) ; `_handle_correcting` invoque réellement le Developer ; la reprise depuis WAITING_* est
réelle (`resume_to_phase`, mission §3.5) ; le verrou détecte un PID mort (mission §3.6) ; un fichier
de missions invalide route vers `BLOCKED_SAFETY` (mission §4) ; commit/push sont idempotents
(mission §3.8).
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.mission_queue import Mission, save_missions
from scripts.autopilot.quota_detector import FailureCategory
from scripts.autopilot.state_machine import AutopilotState, AutopilotStateStore
from scripts.autopilot.supervisor import AutopilotSupervisor, FakeGitOps, SingleInstanceLock, StopSignal


def _one_mission_queue(tmp_path):
    path = tmp_path / "missions.json"
    save_missions(path, [
        Mission(id="M1", title="Mission factice", status="PLANNED", prompt_file="m1.md", depends_on=()),
    ])
    return path


def _ok_developer(mission, attempt, findings=None):
    return {"success": True, "changed_files": ["dummy.py"], "raw_output": "changes applied"}


def _ok_tester(mission):
    return {"success": True, "summary": "3 passed"}


def _ok_reviewer(mission):
    return {"success": True, "blocking_findings": [], "summary": "clean"}


def _make_supervisor(
    tmp_path, developer_fn=_ok_developer, tester_fn=_ok_tester, reviewer_fn=_ok_reviewer,
    failure_limit=3, diagnostic_fn=None,
):
    state_store = AutopilotStateStore(tmp_path / "state.json")
    missions_path = _one_mission_queue(tmp_path)
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    return AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=developer_fn,
        tester_fn=tester_fn, reviewer_fn=reviewer_fn, git_ops=git_ops, lock=lock,
        failure_limit=failure_limit, branch="master", diagnostic_fn=diagnostic_fn,
    ), git_ops, state_store


def test_happy_path_reaches_checkpointed_then_next_mission(tmp_path):
    supervisor, git_ops, state_store = _make_supervisor(tmp_path)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.NEXT_MISSION
    assert git_ops.committed
    assert git_ops.pushed
    assert git_ops.forced_push_attempted is False


def test_mission_done_status_is_committed_together_with_its_own_work(tmp_path):
    """Régression — trouvé RÉELLEMENT cassé par le canary V1.1 : l'ancien `_handle_next_mission()`
    marquait la mission `DONE` dans `missions.json` APRÈS le push, donc ce changement n'était
    JAMAIS committé ni poussé — un fresh checkout/pull aurait revu la mission comme "PLANNED" et
    aurait pu la re-sélectionner/la ré-exécuter. Le flip doit désormais faire partie du MÊME
    commit que le travail de la mission elle-même."""
    from scripts.autopilot.mission_queue import load_missions

    missions_path = _one_mission_queue(tmp_path)
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()

    supervisor.run_until({AutopilotState.NEXT_MISSION})

    # Le fichier de missions sur disque (ce que "committer" représente ici, FakeGitOps n'écrivant
    # jamais réellement dans Git) doit déjà porter DONE avant même que NEXT_MISSION ne s'exécute —
    # preuve que le flip a eu lieu pendant COMMITTING, pas après PUSHING/CHECKPOINTED.
    reloaded = load_missions(missions_path)
    assert reloaded[0].status == "DONE"
    # Et ce chemin doit avoir fait partie de ce qui a été "ajouté" au commit.
    assert str(missions_path) in git_ops.added


def test_no_more_missions_reaches_completed(tmp_path):
    state_store = AutopilotStateStore(tmp_path / "state.json")
    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [])  # file bien formée mais vide
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.COMPLETED})
    assert final_state == AutopilotState.COMPLETED


def test_missing_missions_file_reaches_blocked_safety_not_a_false_completed(tmp_path):
    """Régression — mission Autopilot V1.1 §4 : "un fichier absent... ne doit jamais produire
    silencieusement une file vide ou un faux COMPLETED". Avant V1.1, un fichier absent était
    tolérant (`[]`) et cette situation aboutissait silencieusement à `COMPLETED`."""
    state_store = AutopilotStateStore(tmp_path / "state.json")
    missions_path = tmp_path / "missions.json"  # jamais créé
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.COMPLETED, AutopilotState.BLOCKED_SAFETY})

    assert final_state == AutopilotState.BLOCKED_SAFETY
    assert "missions" in state_store.load().stop_reason.lower()


def test_malformed_missions_file_reaches_blocked_safety(tmp_path):
    state_store = AutopilotStateStore(tmp_path / "state.json")
    missions_path = tmp_path / "missions.json"
    missions_path.write_text('{"missions": [{"id": "M1"}]}', encoding="utf-8")  # champs manquants
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.COMPLETED, AutopilotState.BLOCKED_SAFETY})
    assert final_state == AutopilotState.BLOCKED_SAFETY


def test_blocking_review_finding_triggers_correcting_then_retests(tmp_path):
    calls = {"review_count": 0}

    def flaky_reviewer(mission):
        calls["review_count"] += 1
        if calls["review_count"] == 1:
            return {"success": True, "blocking_findings": ["nom de variable trompeur"], "summary": "1 blocage"}
        return {"success": True, "blocking_findings": [], "summary": "clean"}

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, reviewer_fn=flaky_reviewer)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.NEXT_MISSION
    assert calls["review_count"] == 2
    assert git_ops.committed  # a fini par committer après correction


def test_correcting_really_invokes_the_developer_with_the_review_findings(tmp_path):
    """Régression — mission Autopilot V1.1 §3.4 : "la phase CORRECTING ne corrige rien" avant ce
    correctif (transition directe REVIEWING -> CORRECTING -> TESTING sans nouvel appel Developer).
    Le Developer doit désormais recevoir les findings exacts et être réellement rappelé."""
    develop_calls = []

    def recording_developer(mission, attempt, findings=None):
        develop_calls.append(findings)
        return {"success": True, "changed_files": ["dummy.py"], "raw_output": "ok"}

    review_calls = {"count": 0}

    def flaky_reviewer(mission):
        review_calls["count"] += 1
        if review_calls["count"] == 1:
            return {"success": True, "blocking_findings": ["fix X"], "summary": "1 blocage"}
        return {"success": True, "blocking_findings": [], "summary": "clean"}

    supervisor, git_ops, state_store = _make_supervisor(
        tmp_path, developer_fn=recording_developer, reviewer_fn=flaky_reviewer,
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.NEXT_MISSION
    # 1er appel (DEVELOPING) : findings=None ; 2e appel (CORRECTING) : findings=["fix X"].
    assert develop_calls == [None, ["fix X"]]


def test_quota_failure_moves_to_waiting_for_claude_not_human_gate(tmp_path):
    def quota_developer(mission, attempt, findings=None):
        return {"success": False, "raw_output": "Error: rate_limit_error - exceeded", "changed_files": []}

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, developer_fn=quota_developer)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.WAITING_FOR_CLAUDE, AutopilotState.HUMAN_GATE_REQUIRED})

    assert final_state == AutopilotState.WAITING_FOR_CLAUDE
    record = state_store.load()
    assert record.stop_reason is not None
    assert "quota" in record.stop_reason.lower() or "limit" in record.stop_reason.lower()
    assert record.resume_to_phase == "DEVELOPING"


def test_waiting_for_claude_really_resumes_into_the_interrupted_phase(tmp_path):
    """Régression — mission Autopilot V1.1 §3.5 : avant ce correctif, `WAITING_FOR_CLAUDE` était un
    no-op ("rien à faire tant qu'un appelant externe ne change pas explicitement l'état") — une
    reprise (`run_one_step()`/`run_until()` rappelé sur cet état) ne faisait RIEN. Elle doit
    maintenant retourner réellement vers la phase interrompue (ici DEVELOPING), pas vers PLANNING."""
    calls = {"count": 0}

    def fails_once_then_succeeds(mission, attempt, findings=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"success": False, "raw_output": "rate_limit_error", "changed_files": []}
        return {"success": True, "changed_files": ["dummy.py"], "raw_output": "ok"}

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, developer_fn=fails_once_then_succeeds)
    supervisor.acquire_lock()

    waiting = supervisor.run_until({AutopilotState.WAITING_FOR_CLAUDE})
    assert waiting == AutopilotState.WAITING_FOR_CLAUDE
    assert state_store.load().resume_to_phase == "DEVELOPING"

    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION})
    assert final_state == AutopilotState.NEXT_MISSION
    assert calls["count"] == 2  # la reprise a bien rappelé le Developer, pas re-sélectionné une mission


def test_tester_fn_receives_the_current_mission_for_targeted_tests(tmp_path):
    """Mission Autopilot V1.1 §5/§13 : "le Tester exécute les tests définis [par la mission]" — le
    Tester doit recevoir la mission courante (`mission.targeted_tests`/`risk_level`/
    `scientific_contracts`), jamais lancer la suite complète en aveugle sans pouvoir cibler."""
    seen = []

    def recording_tester(mission):
        seen.append(mission)
        return {"success": True, "summary": "ok"}

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, tester_fn=recording_tester)
    supervisor.acquire_lock()
    supervisor.run_until({AutopilotState.NEXT_MISSION})

    assert len(seen) == 1
    assert seen[0].id == "M1"


def test_repeated_identical_project_failure_escalates_to_human_gate(tmp_path):
    def always_same_failure(mission, attempt, findings=None):
        return {"success": False, "raw_output": "AssertionError: assert 1 == 2", "changed_files": []}

    supervisor, git_ops, state_store = _make_supervisor(
        tmp_path, developer_fn=always_same_failure, failure_limit=2,
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until(
        {AutopilotState.WAITING_FOR_CLAUDE, AutopilotState.HUMAN_GATE_REQUIRED}, max_steps=200,
    )

    assert final_state == AutopilotState.HUMAN_GATE_REQUIRED


def test_a_diagnostic_is_attempted_once_before_escalating_to_human_gate(tmp_path):
    """Mission Autopilot V1.1 §8 : "avant le Human Gate, lancer un diagnostic indépendant, tenter
    une autre approche sûre" — UNE fois par mission (`diagnostic_attempted`), jamais une boucle
    supplémentaire non bornée."""
    diagnostic_calls = []

    def diagnostic_fn(mission, signature):
        diagnostic_calls.append(signature)
        return {"approach_notes": "essayer une autre stratégie de correction"}

    def always_same_failure(mission, attempt, findings=None):
        return {"success": False, "raw_output": "AssertionError: assert 1 == 2", "changed_files": []}

    supervisor, git_ops, state_store = _make_supervisor(
        tmp_path, developer_fn=always_same_failure, failure_limit=2, diagnostic_fn=diagnostic_fn,
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until(
        {AutopilotState.WAITING_FOR_CLAUDE, AutopilotState.HUMAN_GATE_REQUIRED}, max_steps=200,
    )

    assert final_state == AutopilotState.HUMAN_GATE_REQUIRED
    assert len(diagnostic_calls) == 1  # jamais répété indéfiniment
    assert state_store.load().diagnostic_attempted is True


def test_resume_after_simulated_crash_does_not_redo_completed_steps(tmp_path):
    """Mission §18 : "une reprise après arrêt simulé fonctionne", idempotence."""
    develop_calls = {"count": 0}

    def counting_developer(mission, attempt, findings=None):
        develop_calls["count"] += 1
        return _ok_developer(mission, attempt, findings=findings)

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


def test_lock_file_stores_pid_and_metadata(tmp_path):
    lock_path = tmp_path / "autopilot.lock"
    lock = SingleInstanceLock(lock_path)
    assert lock.acquire() is True

    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    assert "acquired_at_utc" in payload
    assert "worktree" in payload


def test_a_lock_held_by_a_dead_pid_is_reclaimed(tmp_path):
    """Régression — mission Autopilot V1.1 §3.6 : le verrou Bootstrap V1 "peut devenir orphelin"
    sans détection de PID mort. Un PID manifestement inexistant (hors plage réelle) doit être
    détecté comme mort et le verrou automatiquement récupéré par une nouvelle instance."""
    lock_path = tmp_path / "autopilot.lock"
    lock_path.write_text(
        json.dumps({"pid": 2147483647, "acquired_at_utc": "2020-01-01T00:00:00+00:00", "worktree": "x"}),
        encoding="utf-8",
    )

    new_lock = SingleInstanceLock(lock_path)
    assert new_lock.acquire() is True

    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()


def test_a_lock_held_by_the_current_live_process_is_never_reclaimed(tmp_path):
    lock_path = tmp_path / "autopilot.lock"
    owner = SingleInstanceLock(lock_path)
    assert owner.acquire() is True  # écrit le PID du process de test courant, réellement vivant

    stranger = SingleInstanceLock(lock_path)
    assert stranger.acquire() is False  # jamais volé tant que le détenteur est vivant


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


def test_stop_signal_interrupts_run_until_at_the_next_step_boundary(tmp_path):
    """Mission Autopilot V1.1 §3.6 : "stop doit demander l'arrêt du superviseur, pas seulement
    supprimer son verrou" — arrêt COOPÉRATIF vérifié entre deux étapes, jamais en plein milieu."""
    develop_calls = {"count": 0}

    def counting_developer(mission, attempt, findings=None):
        develop_calls["count"] += 1
        return _ok_developer(mission, attempt, findings=findings)

    state_store = AutopilotStateStore(tmp_path / "state.json")
    missions_path = _one_mission_queue(tmp_path)
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    stop_signal = StopSignal(tmp_path / "stop.signal")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=counting_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
        stop_signal=stop_signal,
    )
    supervisor.acquire_lock()
    stop_signal.request()

    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.BOOTSTRAPPING  # jamais avancé, arrêté avant la 1ère étape
    assert develop_calls["count"] == 0


def test_network_failure_during_development_moves_to_waiting_for_external_resource(tmp_path):
    """Régression — revue safety/architecture du Bootstrap : `ALLOWED_TRANSITIONS[DEVELOPING]`
    n'incluait pas `WAITING_FOR_EXTERNAL_RESOURCE`, alors que `_handle_failure()` peut cibler cet
    état pour `FailureCategory.NETWORK` — crashait avec `IllegalTransitionError` (reproduit
    empiriquement par la revue avec un `developer_fn` renvoyant une erreur réseau ordinaire)."""
    def network_failure_developer(mission, attempt, findings=None):
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
    def failing_tester(mission):
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
    def network_failing_tester(mission):
        return {"success": False, "summary": "requests.exceptions.ConnectionError: timeout"}

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, tester_fn=network_failing_tester)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({
        AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE, AutopilotState.HUMAN_GATE_REQUIRED,
        AutopilotState.WAITING_FOR_CLAUDE,
    })

    assert final_state == AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE


def test_reviewer_technical_failure_is_classified_not_treated_as_clean(tmp_path):
    """Mission Autopilot V1.1 §3.3 : un échec TECHNIQUE de la review elle-même (ex. le Claude
    reviewer indépendant a lui-même échoué) ne doit jamais être interprété silencieusement comme
    "review propre" — il doit être classé/routé comme n'importe quel autre échec."""
    def failing_reviewer(mission):
        return {"success": False, "raw_output": "rate_limit_error during review", "summary": "review indisponible"}

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, reviewer_fn=failing_reviewer)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.WAITING_FOR_CLAUDE, AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.WAITING_FOR_CLAUDE
    assert git_ops.committed is False  # jamais commité sur la base d'une review qui n'a pas eu lieu


def test_mission_queue_emptied_between_ready_and_planning_reaches_completed(tmp_path):
    """Régression — revue safety/architecture du Bootstrap : `ALLOWED_TRANSITIONS[PLANNING]`
    n'incluait pas `COMPLETED`, alors que `_handle_planning()` transitionne vers `COMPLETED` si la
    file est vide au moment où elle est relue (état et file de missions sont deux fichiers séparés,
    relus à des instants différents — un scénario réaliste en reprise, pas seulement théorique)."""
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


def test_committing_is_idempotent_after_a_commit_already_landed_before_a_crash(tmp_path):
    """Mission Autopilot V1.1 §3.8 : un crash après un `git commit` réel réussi mais avant que la
    transition COMMITTING -> PUSHING ne soit enregistrée ne doit JAMAIS produire un second commit
    au prochain passage dans `_handle_committing()`."""
    from dataclasses import replace as _replace

    supervisor, git_ops, state_store = _make_supervisor(tmp_path)
    supervisor.acquire_lock()
    for _ in range(8):  # BOOTSTRAPPING -> ... -> PUSHING (le vrai commit a lieu en route)
        state = supervisor.run_one_step()
        if state == AutopilotState.PUSHING:
            break
    assert git_ops._commit_count == 1

    # Simule : la transition COMMITTING -> PUSHING n'a jamais été persistée (crash juste après le
    # `git commit` réel), mais le commit lui-même a bien eu lieu -> l'état est forcé en arrière.
    record = state_store.load()
    corrupted = _replace(record, phase=AutopilotState.COMMITTING.value)
    state_store.save(corrupted)

    final_state = supervisor.run_one_step()  # COMMITTING relu -> ne doit PAS committer une 2e fois

    assert final_state == AutopilotState.PUSHING
    assert git_ops._commit_count == 1  # toujours un seul commit


def test_pushing_is_idempotent_after_a_push_already_landed_before_a_crash(tmp_path):
    """Mission Autopilot V1.1 §3.8 : symétrique au test précédent pour le push."""
    from dataclasses import replace as _replace

    supervisor, git_ops, state_store = _make_supervisor(tmp_path)
    supervisor.acquire_lock()
    for _ in range(9):  # BOOTSTRAPPING -> ... -> CHECKPOINTED
        state = supervisor.run_one_step()
        if state == AutopilotState.CHECKPOINTED:
            break
    assert git_ops.pushed is True

    record = state_store.load()
    corrupted = _replace(record, phase=AutopilotState.PUSHING.value)  # simule un retour post-crash
    state_store.save(corrupted)
    original_push = git_ops.push
    calls = {"count": 0}

    def counting_push(force=False):
        calls["count"] += 1
        return original_push(force=force)

    git_ops.push = counting_push
    final_state = supervisor.run_one_step()

    assert final_state == AutopilotState.CHECKPOINTED
    assert calls["count"] == 0  # jamais rappelé — reconnu comme déjà poussé via last_push_sha


def test_forbidden_git_command_never_reaches_the_real_runner(tmp_path):
    """Le git_ops factice lui-même refuse une commande interdite — preuve que le garde
    git_safety est bien câblé dans le chemin d'exécution réel, pas seulement testé isolément."""
    git_ops = FakeGitOps()
    with pytest.raises(ValueError):
        git_ops.push(force=True)
    assert git_ops.forced_push_attempted is True
    assert git_ops.pushed is False
