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
from scripts.autopilot.state_machine import AutopilotState, AutopilotStateRecord, AutopilotStateStore
from scripts.autopilot.supervisor import (
    AutopilotSupervisor, FakeGitOps, HumanGateResolutionRefused, SingleInstanceLock, StopSignal,
)


@pytest.fixture(autouse=True)
def _default_sufficient_disk_space(monkeypatch):
    """Isolation de test — bug réel confirmé en conditions réelles (mission « poursuite
    AlphaForge ») : `git_safety.check_disk_space()` vérifie le VRAI disque hôte
    (`shutil.disk_usage()`), jamais isolé par `tmp_path`/`FakeGitOps`. Une machine réellement sous
    le seuil de sécurité (2 Go) fait échouer TOUTE la suite Autopilot qui traverse
    BOOTSTRAPPING/TESTING/PRE_COMMIT_CHECK — reproduit empiriquement (40 tests en échec sur cette
    machine au moment où son disque est passé sous 2 Go) — jamais un test dont le résultat dépend
    de l'espace disque réel de la machine qui l'exécute. Espace suffisant par défaut pour tous les
    tests de ce fichier ; les tests dédiés au comportement `disk_space` repatchent explicitement
    cette même fonction dans leur propre corps (le patch le plus récent prévaut pour ce test)."""
    monkeypatch.setattr("scripts.autopilot.git_safety.check_disk_space", lambda *a, **k: None)


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
    # Finalisation sécurité (point 4.4) : la couverture de review est désormais OBLIGATOIRE dès
    # qu'il existe des `artifacts` — "dummy.py" reflète ce que `_ok_developer` déclare réellement
    # avoir modifié, jamais une couverture inventée sans rapport avec le changement réel.
    return {"success": True, "blocking_findings": [], "summary": "clean", "reviewed_files": ["dummy.py"]}


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


def test_mission_disappearing_mid_flight_blocks_before_invoking_the_developer(tmp_path):
    """Régression — trouvé par la revue reproductibilité/scope V1.1 : si `missions.json` devient
    corrompu/modifié PENDANT DEVELOPING/TESTING/REVIEWING/CORRECTING (une fois la mission déjà
    sélectionnée), `_mission_by_id()` retournait silencieusement `None` et le Developer réel était
    quand même invoqué (donc FACTURÉ) sur un contexte quasi vide, la corruption n'étant détectée
    qu'à COMMITTING. Doit désormais bloquer immédiatement, AVANT tout appel `developer_fn`."""
    develop_calls = {"count": 0}

    def counting_developer(mission, attempt, findings=None):
        develop_calls["count"] += 1
        return _ok_developer(mission, attempt, findings=findings)

    missions_path = _one_mission_queue(tmp_path)
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=counting_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()
    supervisor.run_one_step()  # BOOTSTRAPPING -> READY
    supervisor.run_one_step()  # READY -> PLANNING
    supervisor.run_one_step()  # PLANNING -> DEVELOPING (mission_id="M1" persisted)
    # La file de missions "disparaît"/devient illisible pendant que DEVELOPING est en cours.
    missions_path.unlink()

    final_state = supervisor.run_one_step()  # DEVELOPING doit bloquer AVANT d'appeler developer_fn

    assert final_state == AutopilotState.BLOCKED_SAFETY
    assert develop_calls["count"] == 0
    assert "introuvable" in state_store.load().stop_reason.lower()


def test_requires_clean_worktree_blocks_planning_on_a_dirty_worktree(tmp_path):
    """Régression — trouvé par la revue indépendante V1.1 : `Mission.requires_clean_worktree`
    (True par défaut) était déclaré dans le schéma mais jamais réellement vérifié nulle part —
    exactement le scénario qui a pollué le scope (`changed_files`) du canary réel de cette
    mission (édits d'ingénierie laissés non committés pendant que le Developer tournait)."""
    class DirtyGitOps(FakeGitOps):
        def is_worktree_clean(self):
            return False

    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(id="M1", title="x", status="PLANNED", prompt_file="m1.md", requires_clean_worktree=True),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = DirtyGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.DEVELOPING, AutopilotState.BLOCKED_SAFETY})

    assert final_state == AutopilotState.BLOCKED_SAFETY
    assert "worktree" in state_store.load().stop_reason.lower()


def test_requires_clean_worktree_false_proceeds_despite_a_dirty_worktree(tmp_path):
    class DirtyGitOps(FakeGitOps):
        def is_worktree_clean(self):
            return False

    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(id="M1", title="x", status="PLANNED", prompt_file="m1.md", requires_clean_worktree=False),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = DirtyGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.DEVELOPING, AutopilotState.BLOCKED_SAFETY})

    assert final_state == AutopilotState.DEVELOPING


def test_blocked_safety_on_dirty_worktree_resolves_once_the_worktree_becomes_clean(tmp_path):
    """Finalisation V1.1 §2.E : une résolution CONTRÔLÉE — jamais un effacement d'état ni une
    désactivation de `requires_clean_worktree` — revérifie la cause précise (ici : le worktree
    est-il RÉELLEMENT redevenu propre ?) et ne reprend que si c'est authentiquement vrai."""
    class ToggleableGitOps(FakeGitOps):
        def __init__(self):
            super().__init__()
            self.clean = False

        def is_worktree_clean(self):
            return self.clean

    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(id="M1", title="x", status="PLANNED", prompt_file="m1.md", requires_clean_worktree=True),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = ToggleableGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()

    blocked = supervisor.run_until({AutopilotState.BLOCKED_SAFETY})
    assert blocked == AutopilotState.BLOCKED_SAFETY
    assert state_store.load().blocked_reason_category == "dirty_worktree"

    # Toujours sale : rappeler run_one_step() ne doit RIEN changer, jamais forcé.
    still_blocked = supervisor.run_one_step()
    assert still_blocked == AutopilotState.BLOCKED_SAFETY

    # Redevenu réellement propre : la reprise doit maintenant progresser.
    git_ops.clean = True
    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION})
    assert final_state == AutopilotState.NEXT_MISSION


def test_blocked_safety_with_no_known_auto_resolution_never_resumes_by_itself(tmp_path):
    """Une catégorie sans résolution automatique connue (ex. file de missions invalide) doit
    rester bloquée INDÉFINIMENT, quel que soit le nombre de `run_one_step()` — jamais une reprise
    aveugle après un simple redémarrage (mission finalisation V1.1 §2.E)."""
    state_store = AutopilotStateStore(tmp_path / "state.json")
    missions_path = tmp_path / "missions.json"  # jamais créé -> "missions_invalid"
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()

    blocked = supervisor.run_until({AutopilotState.BLOCKED_SAFETY})
    assert blocked == AutopilotState.BLOCKED_SAFETY
    assert state_store.load().blocked_reason_category == "missions_invalid"

    for _ in range(5):
        assert supervisor.run_one_step() == AutopilotState.BLOCKED_SAFETY


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
        return {"success": True, "blocking_findings": [], "summary": "clean", "reviewed_files": ["dummy.py"]}

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
        return {"success": True, "blocking_findings": [], "summary": "clean", "reviewed_files": ["dummy.py"]}

    supervisor, git_ops, state_store = _make_supervisor(
        tmp_path, developer_fn=recording_developer, reviewer_fn=flaky_reviewer,
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.NEXT_MISSION
    # 1er appel (DEVELOPING) : findings=None ; 2e appel (CORRECTING) : findings=["fix X"].
    assert develop_calls == [None, ["fix X"]]


def test_a_test_failure_transmits_to_correcting_never_blindly_reruns_testing(tmp_path):
    """Régression — trouvé RÉELLEMENT cassé (mission finalisation V1.1 §2.C) : un échec de test
    non-escaladant retentait auparavant EN PLACE sur TESTING, ce qui ne fait que rappeler
    `tester_fn()` sans le moindre changement de code — un test déterministe échoue alors
    IDENTIQUEMENT à chaque fois, sans jamais transmettre l'échec au Developer ni tenter de
    corriger quoi que ce soit. Doit désormais transiter vers CORRECTING avec l'échec en
    `pending_findings`, et le Developer doit être réellement rappelé avec ce retour."""
    develop_calls = []

    def recording_developer(mission, attempt, findings=None):
        develop_calls.append(findings)
        return {"success": True, "changed_files": ["dummy.py"], "raw_output": "ok"}

    test_calls = {"count": 0}

    def flaky_tester(mission):
        test_calls["count"] += 1
        if test_calls["count"] == 1:
            return {"success": False, "summary": "AssertionError: test_foo a échoué"}
        return {"success": True, "summary": "3 passed"}

    supervisor, git_ops, state_store = _make_supervisor(
        tmp_path, developer_fn=recording_developer, tester_fn=flaky_tester,
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.NEXT_MISSION
    assert test_calls["count"] == 2  # jamais rappelé sans un passage par CORRECTING entre les deux
    # 1er appel (DEVELOPING) : findings=None ; 2e appel (CORRECTING, après l'échec de test) :
    # findings porte l'échec de test transmis, jamais None ni les anciens findings de review.
    assert develop_calls[0] is None
    assert develop_calls[1] is not None
    assert "test_foo" in develop_calls[1][0]


def test_a_developing_retry_transmits_the_previous_failure_as_feedback(tmp_path):
    """Complète le test précédent pour DEVELOPING lui-même : une retentative en place doit aussi
    transmettre l'échec précédent, jamais rappeler le Developer avec exactement le même prompt
    sans aucune information sur ce qui a échoué la première fois."""
    develop_calls = []

    def flaky_developer(mission, attempt, findings=None):
        develop_calls.append(findings)
        if attempt == 1:
            return {"success": False, "raw_output": "SyntaxError: ligne 42 invalide", "changed_files": []}
        return {"success": True, "changed_files": ["dummy.py"], "raw_output": "ok"}

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, developer_fn=flaky_developer)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.NEXT_MISSION
    assert len(develop_calls) == 2
    assert develop_calls[0] is None  # 1re tentative : aucun retour antérieur
    assert develop_calls[1] is not None
    assert "SyntaxError" in develop_calls[1][0]  # 2e tentative : l'échec précédent est transmis


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


def test_mission_max_attempts_escalates_even_when_failure_signatures_all_differ(tmp_path):
    """Régression — trouvé non câblé en préparant le lancement réel d'AF-V-02 Slice 2 :
    `Mission.max_attempts` existait dans le schéma mais n'était jamais appliqué — seule
    l'escalade par SIGNATURE IDENTIQUE répétée (`should_escalate`) bornait les tentatives. Une
    vraie mission scientifique dont chaque tentative échoue pour une raison DIFFÉRENTE ne
    déclenchait jamais cette escalade et pouvait retenter indéfiniment."""
    calls = {"count": 0}

    def always_different_failure(mission, attempt, findings=None):
        calls["count"] += 1
        return {"success": False, "raw_output": f"AssertionError: échec distinct numéro {calls['count']}"}

    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(id="M1", title="x", status="PLANNED", prompt_file="m1.md", max_attempts=2),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=always_different_failure,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
        failure_limit=10,  # jamais atteint par signature — seul max_attempts doit borner ici
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until(
        {AutopilotState.WAITING_FOR_CLAUDE, AutopilotState.HUMAN_GATE_REQUIRED}, max_steps=200,
    )

    assert final_state == AutopilotState.HUMAN_GATE_REQUIRED
    assert calls["count"] == 2  # jamais retenté au-delà de max_attempts
    assert "max_attempts=2" in state_store.load().stop_reason


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


@pytest.mark.skipif(os.name != "nt", reason="Windows-only : OpenProcess/GetLastError")
def test_pid_is_alive_windows_never_treats_access_denied_as_dead(monkeypatch):
    """Régression — revue safety/architecture V1.1, BLOCKER empiriquement reproduit :
    `OpenProcess` renvoie NULL aussi bien pour un PID qui n'existe pas QUE pour un PID bien
    vivant mais inaccessible (contexte de sécurité différent, process protégé, EDR/AV) — confondre
    les deux permettait de voler un verrou activement détenu par un process vivant. Seul
    `ERROR_INVALID_PARAMETER` (87) doit être traité comme "mort" ; tout le reste (dont
    `ERROR_ACCESS_DENIED`, 5) doit rester "vivant", conformément au contrat documenté de la
    fonction ("en cas de doute... jamais voler un verrou par erreur")."""
    import ctypes

    from scripts.autopilot.supervisor import _pid_is_alive

    class _FakeKernel32:
        def OpenProcess(self, access, inherit, pid):
            return 0  # échec — simule OpenProcess refusant la poignée

        def CloseHandle(self, handle):
            return True

    monkeypatch.setattr(ctypes, "WinDLL", lambda name, use_last_error=False: _FakeKernel32(), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)  # ERROR_ACCESS_DENIED

    assert _pid_is_alive(1234) is True  # accès refusé -> toujours considéré vivant, jamais volé


@pytest.mark.skipif(os.name != "nt", reason="Windows-only : OpenProcess/GetLastError")
def test_pid_is_alive_windows_treats_invalid_parameter_as_dead(monkeypatch):
    import ctypes

    from scripts.autopilot.supervisor import _pid_is_alive

    class _FakeKernel32:
        def OpenProcess(self, access, inherit, pid):
            return 0

        def CloseHandle(self, handle):
            return True

    monkeypatch.setattr(ctypes, "WinDLL", lambda name, use_last_error=False: _FakeKernel32(), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 87, raising=False)  # ERROR_INVALID_PARAMETER

    assert _pid_is_alive(1234) is False  # PID structurellement inexistant -> mort, récupérable


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


def test_is_held_by_a_live_process_is_true_while_a_real_second_process_holds_the_lock(tmp_path):
    """Régression — mission finalisation V1.1 §2.A, reproduite avec DEUX VRAIS PROCESS locaux
    (pas une simulation) : un verrou détenu par un process réellement vivant ne doit jamais
    pouvoir être volé, et une nouvelle instance doit rester bloquée jusqu'à sa libération EFFECTIVE
    par le propriétaire lui-même."""
    import subprocess
    import time
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    lock_path = tmp_path / "autopilot.lock"
    script = (
        "import sys, time\n"
        f"sys.path.insert(0, {str(repo_root)!r})\n"
        "from scripts.autopilot.supervisor import SingleInstanceLock\n"
        f"lock = SingleInstanceLock({str(lock_path)!r})\n"
        "assert lock.acquire()\n"
        "time.sleep(4)\n"
        "lock.release()\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", script])
    try:
        for _ in range(50):
            if lock_path.exists():
                break
            time.sleep(0.1)
        assert lock_path.exists(), "le vrai process n'a jamais acquis le verrou à temps"

        checker = SingleInstanceLock(lock_path)
        assert checker.is_held_by_a_live_process() is True

        stranger = SingleInstanceLock(lock_path)
        assert stranger.acquire() is False  # jamais volé tant que le vrai process tourne
    finally:
        proc.wait(timeout=15)

    # Le vrai process a terminé et a libéré SON PROPRE verrou (via son propre `release()`) —
    # seulement maintenant une nouvelle instance doit pouvoir acquérir.
    assert not lock_path.exists()
    assert SingleInstanceLock(lock_path).acquire() is True


def test_cmd_stop_never_removes_a_lock_held_by_a_real_live_process(tmp_path, monkeypatch):
    """Régression — trouvé réellement cassé (mission finalisation V1.1 §2.A) : `cmd_stop()`
    appelait `force_release()` inconditionnellement, supprimant le verrou d'un vrai process
    encore actif AVANT qu'il ait pu s'arrêter proprement — une seconde instance pouvait alors
    démarrer en concurrence pendant que la première tournait toujours."""
    import subprocess
    import time
    from pathlib import Path

    import scripts.autopilot.cli as cli_module

    repo_root = Path(__file__).resolve().parents[1]
    lock_path = tmp_path / "autopilot.lock"
    script = (
        "import sys, time\n"
        f"sys.path.insert(0, {str(repo_root)!r})\n"
        "from scripts.autopilot.supervisor import SingleInstanceLock\n"
        f"lock = SingleInstanceLock({str(lock_path)!r})\n"
        "assert lock.acquire()\n"
        "time.sleep(4)\n"
        "lock.release()\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", script])
    try:
        for _ in range(50):
            if lock_path.exists():
                break
            time.sleep(0.1)
        assert lock_path.exists()

        monkeypatch.setattr(cli_module, "STATE_PATH", tmp_path / "state.json")
        monkeypatch.setattr(cli_module, "LOCK_PATH", lock_path)
        monkeypatch.setattr(cli_module, "STOP_SIGNAL_PATH", tmp_path / "stop.signal")

        cli_module.cmd_stop(None)

        # Le verrou du vrai process actif ne doit PAS avoir disparu.
        assert lock_path.exists()
    finally:
        proc.wait(timeout=15)

    assert not lock_path.exists()  # libéré par le propriétaire lui-même, pas par cmd_stop


def test_cmd_stop_still_cleans_up_a_genuinely_orphaned_lock(tmp_path, monkeypatch):
    """Symétrique : un verrou dont le PID enregistré est mort DOIT toujours être nettoyable par
    `cmd_stop` — le correctif ne doit pas rendre le filet de sécurité inopérant pour ce cas."""
    import json as _json

    import scripts.autopilot.cli as cli_module

    lock_path = tmp_path / "autopilot.lock"
    lock_path.write_text(_json.dumps({"pid": 2147483647, "acquired_at_utc": "x", "worktree": "x"}), encoding="utf-8")

    monkeypatch.setattr(cli_module, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(cli_module, "LOCK_PATH", lock_path)
    monkeypatch.setattr(cli_module, "STOP_SIGNAL_PATH", tmp_path / "stop.signal")

    cli_module.cmd_stop(None)

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


def test_repeated_identical_review_failure_escalates_to_human_gate_from_reviewing(tmp_path):
    """Régression — revue safety/architecture V1.1, BLOCKER empiriquement reproduit :
    `ALLOWED_TRANSITIONS[REVIEWING]` n'incluait pas `HUMAN_GATE_REQUIRED`, alors qu'un échec
    TECHNIQUE de review répété (`reviewer_fn` renvoyant `success: False` — exactement ce que
    `real_reviewer_fn` renvoie sur un Reviewer qui échoue à produire une sortie exploitable, voir
    le correctif "sortie structurée mal interprétée") route à travers `_handle_failure()`, qui
    peut cibler `HUMAN_GATE_REQUIRED` — un `IllegalTransitionError` non rattrapé crashait alors
    tout le process `autopilot start`/`resume`, et comme l'exception survient AVANT la
    persistance de l'état, une reprise ultérieure retombait sur le même crash indéfiniment."""
    def always_broken_reviewer(mission):
        return {"success": False, "raw_output": "AssertionError: reviewer crashed"}

    supervisor, git_ops, state_store = _make_supervisor(
        tmp_path, reviewer_fn=always_broken_reviewer, failure_limit=2,
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until(
        {AutopilotState.WAITING_FOR_CLAUDE, AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE,
         AutopilotState.HUMAN_GATE_REQUIRED}, max_steps=200,
    )

    assert final_state == AutopilotState.HUMAN_GATE_REQUIRED
    assert git_ops.committed is False  # jamais commité sur la base d'une review qui a échoué


def test_resume_from_waiting_for_claude_with_no_recorded_resume_phase_falls_back_to_planning(tmp_path):
    """Régression — revue safety/architecture V1.1, BLOCKER empiriquement reproduit : un fichier
    d'état pré-V1.1 (`resume_to_phase` absent du dataclass à l'époque, donc `None` par défaut au
    chargement) ou tout état corrompu/manuel laissé en `WAITING_FOR_CLAUDE` sans `resume_to_phase`
    valide faisait planter `_resume_to_recorded_phase()` avec `IllegalTransitionError` — le repli
    `PLANNING` n'étant pas une transition autorisée depuis `WAITING_FOR_CLAUDE` à l'époque."""
    supervisor, git_ops, state_store = _make_supervisor(tmp_path)
    supervisor.acquire_lock()
    # Simule un fichier d'état où WAITING_FOR_CLAUDE a été atteint SANS resume_to_phase renseigné
    # (comportement du Bootstrap V1, avant l'introduction de ce champ en V1.1).
    state_store.save(AutopilotStateRecord(
        phase=AutopilotState.WAITING_FOR_CLAUDE.value, mission_id="M1", resume_to_phase=None,
    ))

    final_state = supervisor.run_one_step()

    assert final_state == AutopilotState.PLANNING


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


def test_pre_commit_check_blocks_when_a_file_to_commit_was_never_reviewed(tmp_path):
    """Régression — mission finalisation V1.1 §2.B : "lier les preuves de tests et de review au
    contenu exact finalement committé" — un fichier sur le point d'être committé mais absent des
    `reviewed_files` rapportés par le Reviewer doit bloquer, jamais être committé silencieusement."""
    def developer_with_extra_file(mission, attempt, findings=None):
        return {"success": True, "changed_files": ["reviewed.py", "sneaked_in.py"], "raw_output": "ok"}

    def reviewer_covering_only_one_file(mission):
        return {"success": True, "blocking_findings": [], "summary": "clean", "reviewed_files": ["reviewed.py"]}

    supervisor, git_ops, state_store = _make_supervisor(
        tmp_path, developer_fn=developer_with_extra_file, reviewer_fn=reviewer_covering_only_one_file,
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.BLOCKED_SAFETY, AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.BLOCKED_SAFETY
    assert "sneaked_in.py" in state_store.load().stop_reason
    assert git_ops.committed is False


def test_pre_commit_check_blocks_when_reviewed_files_is_empty_but_artifacts_exist(tmp_path):
    """Finalisation sécurité (point 4.4) : remplace l'ancien test qui exigeait le comportement
    INVERSE (opt-in — une couverture absente/vide laissait passer silencieusement). Trouvé réel :
    la couverture de review est désormais une garde OBLIGATOIRE, jamais un contrôle désactivé par
    défaut — une liste `reviewed_files` absente ou vide alors qu'il existe réellement des
    `artifacts` à committer ne doit JAMAIS permettre un commit/push, exactement comme si un
    Reviewer avait été contourné entièrement."""
    def reviewer_reporting_nothing(mission):
        return {"success": True, "blocking_findings": [], "summary": "clean"}  # reviewed_files absent

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, reviewer_fn=reviewer_reporting_nothing)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.BLOCKED_SAFETY, AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.BLOCKED_SAFETY
    assert state_store.load().blocked_reason_category == "unreviewed_files"
    assert git_ops.committed is False


def test_pre_commit_check_proceeds_when_there_are_no_artifacts_to_commit(tmp_path):
    """Cas vacuité légitime : rien à committer (`artifacts=()`) ne doit jamais être bloqué par la
    garde de couverture — il n'y a alors rien qui aurait pu échapper à la review."""
    def developer_with_no_files(mission, attempt, findings=None):
        return {"success": True, "changed_files": [], "raw_output": "rien à changer"}

    def reviewer_reporting_nothing(mission):
        return {"success": True, "blocking_findings": [], "summary": "clean"}

    supervisor, git_ops, state_store = _make_supervisor(
        tmp_path, developer_fn=developer_with_no_files, reviewer_fn=reviewer_reporting_nothing,
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.BLOCKED_SAFETY, AutopilotState.NEXT_MISSION})

    assert final_state == AutopilotState.NEXT_MISSION
    assert git_ops.committed is True


def test_a_transient_correcting_failure_preserves_the_original_findings_to_fix(tmp_path):
    """Finalisation sécurité (point 4.1) : bug réel confirmé — une retentative en place sur un
    échec SANS RAPPORT survenant PENDANT CORRECTING (ex. `developer_fn` en erreur technique
    transitoire) écrasait `pending_findings` avec une description du NOUVEL échec, perdant les
    findings de review ORIGINAUX que CORRECTING existe pour résoudre. Doit désormais conserver ces
    findings d'origine à travers un tel échec transitoire."""
    develop_calls = []

    def flaky_correcting_developer(mission, attempt, findings=None):
        develop_calls.append(list(findings) if findings else None)
        if len(develop_calls) == 2:
            # 2e appel = 1re invocation de CORRECTING (après la review bloquante) : échoue pour
            # une raison purement technique et TRANSITOIRE, sans rapport avec le finding lui-même —
            # volontairement une catégorie ni QUOTA_LIMIT ni NETWORK (ces deux-là empruntent un
            # chemin distinct qui ne touche déjà jamais `pending_findings`) pour cibler précisément
            # la branche générique de retentative non-escaladante.
            return {"success": False, "raw_output": "InternalToolError: échec technique isolé de l'outil"}
        return {"success": True, "changed_files": ["dummy.py"], "raw_output": "ok"}

    review_calls = {"count": 0}

    def flaky_reviewer(mission):
        review_calls["count"] += 1
        if review_calls["count"] == 1:
            return {"success": True, "blocking_findings": ["corriger le calcul de expectancy"], "summary": "1 blocage"}
        return {"success": True, "blocking_findings": [], "summary": "clean", "reviewed_files": ["dummy.py"]}

    supervisor, git_ops, state_store = _make_supervisor(
        tmp_path, developer_fn=flaky_correcting_developer, reviewer_fn=flaky_reviewer,
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION, AutopilotState.HUMAN_GATE_REQUIRED})

    assert final_state == AutopilotState.NEXT_MISSION
    # 1er appel (DEVELOPING) : None. 2e appel (CORRECTING, échoue) : ["corriger le calcul..."].
    # 3e appel (CORRECTING retenté) : DOIT ENCORE porter le finding original, jamais seulement la
    # description de l'échec transitoire du 2e appel.
    assert len(develop_calls) == 3
    assert develop_calls[1] == ["corriger le calcul de expectancy"]
    assert any("corriger le calcul de expectancy" in f for f in develop_calls[2])


def test_new_mission_never_inherits_the_previous_missions_test_and_review_evidence(tmp_path):
    """Finalisation sécurité (point 5) : bug réel confirmé sur le canary réel de cette mission —
    `current_state.json` affichait encore `tests_status`/`review_status`/`reviewed_files` de la
    mission PRÉCÉDENTE une fois la mission suivante sélectionnée (ces champs ne sont réécrits
    qu'une fois TESTING/REVIEWING réellement exécutés POUR la nouvelle mission). Les preuves de
    tests/review d'une mission ne doivent jamais pouvoir être lues comme valant pour une autre."""
    # `session_id` renseigné explicitement (contrairement à `_ok_developer`/`_ok_reviewer`) —
    # sinon la réinitialisation de `developer_session_id`/`reviewer_session_id` serait indiscernable
    # d'une simple absence de valeur (trouvé par la revue reproductibilité/scope de cette mission :
    # le test précédent ne prouvait rien sur ces deux champs faute de valeur réelle à réinitialiser).
    def developer_with_session(mission, attempt, findings=None):
        return {"success": True, "changed_files": ["dummy.py"], "raw_output": "ok", "session_id": "dev-session-m1"}

    def reviewer_with_session(mission):
        return {
            "success": True, "blocking_findings": [], "summary": "clean",
            "reviewed_files": ["dummy.py"], "session_id": "rev-session-m1",
        }

    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(id="M1", title="Premiere", status="PLANNED", prompt_file="m1.md"),
        Mission(id="M2", title="Seconde", status="PLANNED", prompt_file="m2.md"),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=developer_with_session,
        tester_fn=_ok_tester, reviewer_fn=reviewer_with_session, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()

    # M1 termine intégralement — pose des preuves de tests/review bien réelles dans l'état.
    supervisor.run_until({AutopilotState.NEXT_MISSION})
    record_after_m1 = state_store.load()
    assert record_after_m1.mission_id == "M1"
    assert record_after_m1.tests_status is not None
    assert record_after_m1.review_status is not None
    assert record_after_m1.reviewed_files != ()
    assert record_after_m1.artifacts != ()
    assert record_after_m1.developer_session_id == "dev-session-m1"
    assert record_after_m1.reviewer_session_id == "rev-session-m1"
    # Simule un `stop_reason` résiduel légitimement posé par M1 en cours de route (ex. résolution
    # d'un BLOCKED_SAFETY — le seul cas réel où `stop_reason` se pose sans être ensuite nettoyé par
    # aucune étape de succès ultérieure : PRE_COMMIT_CHECK/COMMITTING/PUSHING/CHECKPOINTED/
    # NEXT_MISSION ne touchent jamais `stop_reason` sur leur chemin de succès, empiriquement
    # confirmé par la revue reproductibilité/scope de cette mission).
    state_store.update(stop_reason="BLOCKED_SAFETY résolu (cause 'disk_space' revérifiée) — reprise contrôlée.")

    # NEXT_MISSION -> PLANNING -> DEVELOPING sélectionne et démarre M2 — ses preuves doivent déjà
    # être réinitialisées à CE point, avant même que M2 ne développe/teste/revoie quoi que ce soit.
    final_state = supervisor.run_until({AutopilotState.DEVELOPING})
    assert final_state == AutopilotState.DEVELOPING
    record_after_m2_selected = state_store.load()
    assert record_after_m2_selected.mission_id == "M2"
    assert record_after_m2_selected.tests_status is None
    assert record_after_m2_selected.review_status is None
    assert not record_after_m2_selected.reviewed_files
    assert not record_after_m2_selected.artifacts
    assert record_after_m2_selected.developer_session_id is None
    assert record_after_m2_selected.reviewer_session_id is None
    assert record_after_m2_selected.stop_reason is None


def test_an_uncaught_developer_exception_never_crashes_the_supervisor(tmp_path):
    """Finalisation sécurité (point 4.2) : une exception NON GÉRÉE levée par `developer_fn` lui-même
    (bug interne, appel Git inattendu...) ne doit jamais se propager hors de `run_one_step()` —
    convertie en échec ordinaire, classifiée et retentée exactement comme un `success: False` réel,
    jamais un crash ni un succès implicite."""
    def exploding_developer(mission, attempt, findings=None):
        raise RuntimeError("bug interne inattendu du developer_fn")

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, developer_fn=exploding_developer)
    supervisor.acquire_lock()

    final_state = supervisor.run_one_step()  # BOOTSTRAPPING -> READY
    final_state = supervisor.run_one_step()  # READY -> PLANNING
    final_state = supervisor.run_one_step()  # PLANNING -> DEVELOPING
    final_state = supervisor.run_one_step()  # DEVELOPING : ne doit JAMAIS lever

    assert final_state in (AutopilotState.DEVELOPING, AutopilotState.WAITING_FOR_CLAUDE)
    record = state_store.load()
    assert record.stop_reason is not None
    assert "bug interne inattendu" in record.stop_reason
    assert git_ops.committed is False


def test_an_uncaught_reviewer_exception_never_crashes_the_supervisor_nor_reads_as_clean(tmp_path):
    """Symétrique pour `reviewer_fn` — bug réel confirmé (mission finalisation sécurité point
    4.2) : `real_reviewer_fn` peut lever `ForbiddenGitCommandError` (ou toute autre exception) hors
    de `_handle_committing`/`_handle_pushing`, les seuls handlers jusqu'ici protégés — jamais lue
    comme une review propre, jamais un commit sur cette base."""
    def exploding_reviewer(mission):
        raise ValueError("git_safety a refusé une commande inattendue pendant la review")

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, reviewer_fn=exploding_reviewer)
    supervisor.acquire_lock()

    final_state = supervisor.run_until({
        AutopilotState.WAITING_FOR_CLAUDE, AutopilotState.HUMAN_GATE_REQUIRED, AutopilotState.NEXT_MISSION,
    })

    assert final_state != AutopilotState.NEXT_MISSION
    assert git_ops.committed is False
    record = state_store.load()
    assert "git_safety a refusé" in (record.stop_reason or "")


def test_diagnostic_after_a_testing_failure_still_routes_through_correcting(tmp_path):
    """Finalisation sécurité (point 4.6) : bug réel confirmé — le cycle diagnostic (juste avant le
    Human Gate) ignorait `retry_target`, retombant toujours sur une retentative EN PLACE. Pour une
    escalade originant de TESTING (`retry_target=CORRECTING`), ceci laissait la phase à TESTING et
    le prochain `run_one_step()` rappelait `tester_fn()` directement, SANS repasser par le
    Developer — réintroduisant exactement l'anti-pattern éliminé par le correctif §2.C, pour ce
    seul cycle. Le diagnostic doit désormais transiter vers CORRECTING (Developer réellement
    rappelé) avant d'atteindre le Human Gate."""
    # Événements horodatés dans l'ORDRE réel d'exécution — seule une assertion sur l'ORDRE relatif
    # ("developer" après "diagnostic") distingue vraiment le correctif : compter les appels seuls
    # ne suffit pas, un premier passage CORRECTING légitime (avant même le diagnostic, déjà
    # fonctionnel) produit déjà >=2 appels indépendamment de ce bug précis.
    events = []

    def counting_developer(mission, attempt, findings=None):
        events.append("developer")
        return {"success": True, "changed_files": ["dummy.py"], "raw_output": "ok"}

    def always_same_test_failure(mission):
        return {"success": False, "summary": "AssertionError: test_foo a échoué identiquement"}

    def diagnostic_fn(mission, signature):
        events.append("diagnostic")
        return {"approach_notes": "essayer une autre stratégie"}

    supervisor, git_ops, state_store = _make_supervisor(
        tmp_path, developer_fn=counting_developer, tester_fn=always_same_test_failure,
        failure_limit=2, diagnostic_fn=diagnostic_fn,
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until(
        {AutopilotState.WAITING_FOR_CLAUDE, AutopilotState.HUMAN_GATE_REQUIRED}, max_steps=200,
    )

    assert final_state == AutopilotState.HUMAN_GATE_REQUIRED
    assert events.count("diagnostic") == 1
    diagnostic_index = events.index("diagnostic")
    # Le Developer doit être RÉELLEMENT rappelé APRÈS le diagnostic — jamais un retour direct sur
    # TESTING seul (bug réel confirmé : l'ancien code ignorait `retry_target` ici).
    assert "developer" in events[diagnostic_index + 1:]


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


def _human_gate_setup(tmp_path, allowed_paths=("optimizer.py", "walk_forward.py"), pending_findings=()):
    """Construit un superviseur déjà à HUMAN_GATE_REQUIRED pour une mission M1 dont le scope
    déclaré est `allowed_paths` — mirroring le scénario réel (AF-V-02 Slice 2 escaladé par des
    échecs RÉPÉTÉS de reviewer_fn, purement opérationnels, jamais scientifiques)."""
    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(
            id="M1", title="Mission scientifique", status="PLANNED", prompt_file="m1.md",
            allowed_paths=allowed_paths,
        ),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    state_store.save(AutopilotStateRecord(
        phase=AutopilotState.HUMAN_GATE_REQUIRED.value, mission_id="M1",
        pending_findings=tuple(pending_findings),
        stop_reason="échec répété (opérationnel) — plafond max_attempts atteint",
    ))
    return supervisor, git_ops, state_store


def test_resolve_human_gate_resumes_to_the_specified_phase_when_worktree_matches_mission_scope(tmp_path):
    """Finalisation reprise (2026-09-18) : une résolution EXPLICITE d'un Human Gate dont la cause
    est purement OPÉRATIONNELLE (jamais scientifique) doit reprendre DIRECTEMENT vers la phase où
    l'escalade a eu lieu (ex. REVIEWING) — jamais un redémarrage PLANNING qui perdrait la
    progression déjà accomplie — et jamais bloquée par un worktree "sale" qui correspond
    exactement au scope déclaré de LA MÊME mission (travail attribuable, pas une contamination)."""
    supervisor, git_ops, state_store = _human_gate_setup(tmp_path)
    git_ops.simulated_dirty_paths = ["optimizer.py", "walk_forward.py"]  # == scope déclaré de M1

    final_state = supervisor.resolve_human_gate(
        AutopilotState.REVIEWING, "prompt claude -p transmis par stdin, plus de crash argv Windows",
    )

    assert final_state == AutopilotState.REVIEWING
    record = state_store.load()
    assert record.phase == AutopilotState.REVIEWING.value
    assert "cause opérationnelle corrigée" in record.stop_reason
    assert record.blocked_reason_category is None


def test_resolve_human_gate_preserves_pending_scientific_findings_untouched(tmp_path):
    """Les findings scientifiques NON RÉSOLUS ne doivent jamais être perdus par la résolution
    d'une cause purement opérationnelle — transmis tels quels à la prochaine invocation réelle."""
    supervisor, git_ops, state_store = _human_gate_setup(
        tmp_path, pending_findings=("corriger le calcul de expectancy",),
    )
    git_ops.simulated_dirty_paths = ["optimizer.py"]

    supervisor.resolve_human_gate(AutopilotState.CORRECTING, "bug opérationnel corrigé")

    record = state_store.load()
    assert list(record.pending_findings) == ["corriger le calcul de expectancy"]


def test_resolve_human_gate_refuses_when_not_currently_at_human_gate(tmp_path):
    supervisor, git_ops, state_store = _human_gate_setup(tmp_path)
    state_store.save(AutopilotStateRecord(phase=AutopilotState.DEVELOPING.value, mission_id="M1"))

    with pytest.raises(HumanGateResolutionRefused):
        supervisor.resolve_human_gate(AutopilotState.REVIEWING, "peu importe")

    assert state_store.load().phase == AutopilotState.DEVELOPING.value  # jamais modifié


def test_resolve_human_gate_refuses_an_illegal_resume_target(tmp_path):
    """`COMPLETED` n'est jamais une cible légale depuis HUMAN_GATE_REQUIRED — jamais une
    résolution qui ferait croire qu'une mission a terminé sans être réellement passée par
    COMMITTING/PUSHING."""
    supervisor, git_ops, state_store = _human_gate_setup(tmp_path)
    git_ops.simulated_dirty_paths = ["optimizer.py"]

    with pytest.raises(HumanGateResolutionRefused):
        supervisor.resolve_human_gate(AutopilotState.COMPLETED, "peu importe")

    assert state_store.load().phase == AutopilotState.HUMAN_GATE_REQUIRED.value


def test_resolve_human_gate_refuses_when_mission_no_longer_in_the_queue(tmp_path):
    """La mission a disparu/été renommée dans missions.json entre l'escalade et la tentative de
    résolution — jamais résolu à l'aveugle sans pouvoir revérifier son scope déclaré."""
    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [])  # M1 n'existe plus
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    git_ops.simulated_dirty_paths = ["optimizer.py"]
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    state_store.save(AutopilotStateRecord(phase=AutopilotState.HUMAN_GATE_REQUIRED.value, mission_id="M1"))

    with pytest.raises(HumanGateResolutionRefused):
        supervisor.resolve_human_gate(AutopilotState.REVIEWING, "peu importe")

    assert state_store.load().phase == AutopilotState.HUMAN_GATE_REQUIRED.value


def test_resolve_human_gate_refuses_when_the_worktree_has_foreign_unattributable_changes(tmp_path):
    """Régression — exigence explicite de la mission finalisation reprise : "bloque uniquement
    les modifications étrangères ou non attribuables". Un fichier hors du scope déclaré de la
    mission (ex. un autre fichier scientifique, ou pire un fichier protégé) ne doit JAMAIS être
    silencieusement toléré au prétexte qu'une résolution de Human Gate est en cours —
    `requires_clean_worktree` n'est jamais contourné."""
    supervisor, git_ops, state_store = _human_gate_setup(
        tmp_path, allowed_paths=("optimizer.py", "walk_forward.py"),
    )
    git_ops.simulated_dirty_paths = ["optimizer.py", "un_fichier_etranger_non_lie.py"]

    with pytest.raises(HumanGateResolutionRefused) as exc_info:
        supervisor.resolve_human_gate(AutopilotState.REVIEWING, "peu importe")

    assert "un_fichier_etranger_non_lie.py" in str(exc_info.value)
    assert state_store.load().phase == AutopilotState.HUMAN_GATE_REQUIRED.value  # jamais résolu


def test_resolve_human_gate_never_touches_requires_clean_worktree_globally(tmp_path):
    """La résolution ne doit jamais désactiver `requires_clean_worktree` pour la mission
    elle-même ni pour aucune autre — vérifié en confirmant que le champ déclaré sur la Mission
    reste `True` après une résolution réussie (aucun mécanisme de cette méthode ne le modifie,
    jamais un flag global muté)."""
    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(
            id="M1", title="x", status="PLANNED", prompt_file="m1.md",
            allowed_paths=("optimizer.py",), requires_clean_worktree=True,
        ),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    git_ops.simulated_dirty_paths = ["optimizer.py"]
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    state_store.save(AutopilotStateRecord(phase=AutopilotState.HUMAN_GATE_REQUIRED.value, mission_id="M1"))

    supervisor.resolve_human_gate(AutopilotState.REVIEWING, "peu importe")

    from scripts.autopilot.mission_queue import load_missions
    reloaded = load_missions(missions_path)
    assert reloaded[0].requires_clean_worktree is True


def test_resolve_human_gate_resets_the_retry_budget_for_the_resumed_phase(tmp_path):
    """Régression — bug réel confirmé par la revue indépendante de cette mission : sans
    réinitialiser `attempt_count`/`diagnostic_attempted`, un Human Gate atteint après épuisement
    de `max_attempts` (ex. 5 tentatives, diagnostic déjà tenté) laissait le compteur DÉJÀ épuisé
    après résolution — un SEUL échec suivant, même transitoire et sans rapport avec la cause
    opérationnelle corrigée, réescaladait IMMÉDIATEMENT vers HUMAN_GATE_REQUIRED sans la moindre
    retentative réelle. La résolution doit donner à la phase reprise un budget de tentatives
    RÉELLEMENT frais, jamais hérité de la séquence épuisée qui a précédé la correction."""
    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(
            id="M1", title="x", status="PLANNED", prompt_file="m1.md",
            allowed_paths=("optimizer.py",), max_attempts=3,
        ),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    git_ops.simulated_dirty_paths = ["optimizer.py"]
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")

    review_calls = {"count": 0}

    def flaky_once_reviewer(mission):
        review_calls["count"] += 1
        if review_calls["count"] == 1:
            # Échec transitoire, SANS RAPPORT avec la cause opérationnelle déjà corrigée.
            return {"success": False, "raw_output": "InternalToolError: échec isolé sans rapport"}
        return {"success": True, "blocking_findings": [], "summary": "clean", "reviewed_files": ["optimizer.py"]}

    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=flaky_once_reviewer, git_ops=git_ops, lock=lock,
        branch="master",
    )
    # Simule l'état réel observé : 5 tentatives déjà épuisées, diagnostic déjà tenté, avant que la
    # cause opérationnelle (désormais corrigée) n'ait fait escalader vers HUMAN_GATE_REQUIRED.
    state_store.save(AutopilotStateRecord(
        phase=AutopilotState.HUMAN_GATE_REQUIRED.value, mission_id="M1",
        attempt_count=5, diagnostic_attempted=True,
        stop_reason="échec répété (opérationnel) — plafond max_attempts atteint",
    ))

    resumed = supervisor.resolve_human_gate(AutopilotState.REVIEWING, "bug opérationnel corrigé")
    assert resumed == AutopilotState.REVIEWING
    record = state_store.load()
    assert record.attempt_count == 0
    assert record.diagnostic_attempted is False

    # Un run_one_step() sur REVIEWING invoque flaky_once_reviewer() : échec transitoire sur cette
    # PREMIÈRE tentative post-résolution — ne doit JAMAIS réescalader immédiatement.
    final_state = supervisor.run_one_step()
    assert final_state != AutopilotState.HUMAN_GATE_REQUIRED
    assert review_calls["count"] == 1


def test_resolve_human_gate_also_resolves_a_blocked_safety_dirty_worktree_against_the_same_missions_own_scope(tmp_path):
    """Régression réelle (poursuite AlphaForge, 2026-09-20) — scénario reproduit en production :
    une résolution `unreviewed_files` d'un `BLOCKED_SAFETY` persisté par du code ANTÉRIEUR (sans
    `resume_to_phase` fiable) retombe sur le repli `PLANNING`, qui ré-sélectionne la mission
    DÉJÀ en cours et se re-bloque en `BLOCKED_SAFETY`/`dirty_worktree` contre son PROPRE travail
    légitime (déjà testé, déjà revu) — `_handle_planning()` n'a qu'un contrôle global
    `is_worktree_clean()`, jamais attribué à une mission. `resolve_human_gate()`, déjà prouvé sûr
    pour HUMAN_GATE_REQUIRED, doit pouvoir résoudre ce cas EXACTEMENT de la même façon (même
    garde d'attribution), sans redémarrer la mission depuis DEVELOPING et sans jamais contourner
    `requires_clean_worktree` pour une contamination réellement étrangère."""
    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(
            id="AF-V-02-SLICE-4", title="x", status="PLANNED", prompt_file="m1.md",
            allowed_paths=("walk_forward.py", "tests/test_walk_forward.py"),
            requires_clean_worktree=True,
        ),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    git_ops.simulated_dirty_paths = ["walk_forward.py", "tests/test_walk_forward.py"]
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    # État réel observé : BLOCKED_SAFETY/dirty_worktree/resume_to_phase=PLANNING, preuves de
    # TESTING/REVIEWING déjà réelles et non perdues (jamais réinitialisées par cette résolution).
    state_store.save(AutopilotStateRecord(
        phase=AutopilotState.BLOCKED_SAFETY.value, mission_id="AF-V-02-SLICE-4",
        blocked_reason_category="dirty_worktree", resume_to_phase=AutopilotState.PLANNING.value,
        review_status="5 finding(s) sur 2 lot(s), 2 fichier(s) couverts",
        tests_status="1325 passed",
        reviewed_files=("tests/test_walk_forward.py", "walk_forward.py"),
        artifacts=("tests/test_walk_forward.py", "walk_forward.py"),
    ))

    final_state = supervisor.resolve_human_gate(
        AutopilotState.PRE_COMMIT_CHECK,
        "dirty_worktree ré-attribué au travail déjà testé/revu de AF-V-02-SLICE-4 lui-même, "
        "jamais une contamination étrangère",
    )

    assert final_state == AutopilotState.PRE_COMMIT_CHECK
    record = state_store.load()
    assert record.phase == AutopilotState.PRE_COMMIT_CHECK.value
    assert record.blocked_reason_category is None
    # Preuves déjà réelles jamais perdues — pas un redémarrage DEVELOPING à vide.
    assert record.tests_status == "1325 passed"
    assert list(record.reviewed_files) == ["tests/test_walk_forward.py", "walk_forward.py"]


def test_resolve_human_gate_still_refuses_a_blocked_safety_with_foreign_unattributable_changes(tmp_path):
    """Même en élargissant `resolve_human_gate()` à `BLOCKED_SAFETY`, une contamination
    réellement étrangère au scope déclaré de la mission reste bloquée — jamais un contournement
    global de `requires_clean_worktree`."""
    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(
            id="M1", title="x", status="PLANNED", prompt_file="m1.md",
            allowed_paths=("walk_forward.py",), requires_clean_worktree=True,
        ),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    git_ops.simulated_dirty_paths = ["walk_forward.py", "un_fichier_etranger_non_lie.py"]
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    state_store.save(AutopilotStateRecord(
        phase=AutopilotState.BLOCKED_SAFETY.value, mission_id="M1",
        blocked_reason_category="dirty_worktree", resume_to_phase=AutopilotState.PLANNING.value,
    ))

    with pytest.raises(HumanGateResolutionRefused) as exc_info:
        supervisor.resolve_human_gate(AutopilotState.PRE_COMMIT_CHECK, "peu importe")

    assert "un_fichier_etranger_non_lie.py" in str(exc_info.value)
    assert state_store.load().phase == AutopilotState.BLOCKED_SAFETY.value  # jamais résolu


@pytest.mark.parametrize("dangerous_target", [AutopilotState.COMMITTING, AutopilotState.PUSHING, AutopilotState.READY])
def test_resolve_human_gate_refuses_to_jump_a_blocked_safety_straight_to_committing_pushing_or_ready(tmp_path, dangerous_target):
    """BLOCKER trouvé par la revue indépendante (poursuite AlphaForge, 2026-09-20) —
    `ALLOWED_TRANSITIONS[BLOCKED_SAFETY]` inclut `COMMITTING`/`PUSHING`/`READY`, mais ces cibles
    ne sont sûres, dans la boucle normale, qu'APRÈS que `_handle_blocked_safety()` a revérifié la
    cause précise catégorisée (ex. `unreviewed_files` exige `dirty ⊆ record.reviewed_files`,
    jamais recontrôlé par `_handle_committing()` lui-même). `resolve_human_gate()` ne fait
    qu'une vérification d'ATTRIBUTION (scope de la mission), jamais la vérification catégorielle
    complète — l'accepter à l'identique aurait permis de committer/pousser du code jamais
    confirmé revu. Doit toujours refuser, quel que soit le scope attribuable."""
    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(
            id="M1", title="x", status="PLANNED", prompt_file="m1.md",
            allowed_paths=("walk_forward.py",), requires_clean_worktree=True,
        ),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    git_ops.simulated_dirty_paths = ["walk_forward.py"]  # entièrement attribuable
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    state_store.save(AutopilotStateRecord(
        phase=AutopilotState.BLOCKED_SAFETY.value, mission_id="M1",
        blocked_reason_category="unreviewed_files", resume_to_phase=AutopilotState.PLANNING.value,
    ))

    with pytest.raises(HumanGateResolutionRefused):
        supervisor.resolve_human_gate(dangerous_target, "peu importe")

    assert state_store.load().phase == AutopilotState.BLOCKED_SAFETY.value  # jamais résolu


def test_a_ready_authorized_next_mission_chains_automatically_without_stopping(tmp_path):
    """Vérification (mission « poursuite AlphaForge », point 5) — pas une correction : le
    superviseur ne doit JAMAIS s'arrêter entre deux missions quand la suivante est `PLANNED` et sa
    seule dépendance déjà `DONE` — un UNIQUE `run_until()` doit traverser M1 (jusqu'à
    NEXT_MISSION) PUIS enchaîner automatiquement M2 en entier (PLANNING -> ... -> NEXT_MISSION ->
    PLANNING -> ... -> COMPLETED), sans qu'aucun appelant externe n'ait besoin de relancer la
    boucle entre les deux. Si ce test échoue, c'est la preuve empirique qu'un correctif minimal
    est nécessaire (point 5) ; s'il passe, aucune intervention supplémentaire n'est justifiée."""
    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(id="M1", title="Premiere", status="PLANNED", prompt_file="m1.md"),
        Mission(
            id="M2", title="Seconde", status="PLANNED", prompt_file="m2.md", depends_on=("M1",),
        ),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()

    final_state = supervisor.run_until({AutopilotState.COMPLETED}, max_steps=100)

    assert final_state == AutopilotState.COMPLETED
    record = state_store.load()
    assert record.mission_id == "M2"  # la dernière mission traitée, jamais restée sur M1
    from scripts.autopilot.mission_queue import load_missions
    reloaded = load_missions(missions_path)
    assert {m.id: m.status for m in reloaded} == {"M1": "DONE", "M2": "DONE"}


def test_a_fresh_start_from_a_previously_completed_state_notices_a_newly_queued_mission(tmp_path):
    """Régression — bug réel confirmé en conditions réelles (mission « poursuite AlphaForge »,
    point 5) : `COMPLETED` n'avait AUCUN handler (`run_one_step()` le retournait tel quel, seul un
    état vraiment terminal) — l'enchaînement AUTOMATIQUE au sein d'UNE MÊME boucle continue
    (`_handle_next_mission()`, voir le test précédent) fonctionnait déjà, mais un `autopilot
    start`/`resume` RELANCÉ APRÈS coup, une fois l'état déjà persisté à `COMPLETED` d'un run
    antérieur, restait bloqué indéfiniment même après l'ajout d'une toute nouvelle mission
    `PLANNED` prête (dépendances satisfaites) à la file — jamais remarquée. Reproduit ici
    exactement ce scénario réel : M1 termine d'abord dans un run complet, PUIS M2 est ajoutée
    seulement APRÈS que l'état a déjà été persisté à COMPLETED (simulant l'ajout d'une nouvelle
    tranche AF-V-02 après une session Autopilot précédente), PUIS une NOUVELLE invocation
    (`run_one_step()`, mirroring un nouveau `cmd_start`/`cmd_resume`) doit reprendre le travail."""
    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(id="M1", title="Premiere", status="PLANNED", prompt_file="m1.md"),
    ])
    state_store = AutopilotStateStore(tmp_path / "state.json")
    git_ops = FakeGitOps()
    lock = SingleInstanceLock(tmp_path / "autopilot.lock")
    supervisor = AutopilotSupervisor(
        state_store=state_store, missions_path=missions_path, developer_fn=_ok_developer,
        tester_fn=_ok_tester, reviewer_fn=_ok_reviewer, git_ops=git_ops, lock=lock, branch="master",
    )
    supervisor.acquire_lock()
    completed = supervisor.run_until({AutopilotState.COMPLETED}, max_steps=100)
    assert completed == AutopilotState.COMPLETED

    # Une nouvelle tranche est mise en file APRÈS coup — exactement le scénario réel : la boucle
    # précédente est déjà retombée sur COMPLETED avant que la nouvelle mission n'existe.
    from scripts.autopilot.mission_queue import load_missions
    existing = load_missions(missions_path)
    save_missions(missions_path, list(existing) + [
        Mission(id="M2", title="Seconde", status="PLANNED", prompt_file="m2.md", depends_on=("M1",)),
    ])

    # Nouvelle invocation (mirroring un nouveau `cmd_start`/`cmd_resume`) — ne doit PLUS rester
    # bloquée sur COMPLETED sans jamais revérifier la file.
    final_state = supervisor.run_until({AutopilotState.COMPLETED}, max_steps=100)

    assert final_state == AutopilotState.COMPLETED
    record = state_store.load()
    assert record.mission_id == "M2"
    reloaded = load_missions(missions_path)
    assert {m.id: m.status for m in reloaded} == {"M1": "DONE", "M2": "DONE"}


def test_low_disk_space_during_testing_blocks_safely_instead_of_being_misread_as_a_test_failure(
    tmp_path, monkeypatch,
):
    """Régression — bug réel confirmé en conditions réelles (mission « poursuite AlphaForge ») :
    `check_disk_space()` n'était vérifié qu'à `BOOTSTRAPPING`/`PRE_COMMIT_CHECK`, jamais à
    `TESTING` — un espace disque réellement insuffisant a fait échouer deux tests Autopilot SANS
    RAPPORT avec la mission en cours (Slice 4), signature répétée identique, escaladant à tort
    vers `HUMAN_GATE_REQUIRED` (« changement d'approche nécessaire ») alors que la VRAIE cause est
    purement environnementale et DÉJÀ correctement gérée ailleurs par
    `BLOCKED_SAFETY`/catégorie `disk_space` — qui se résout tout seul dès que l'espace disque
    redevient suffisant (`_handle_blocked_safety()`, déjà existant et re-vérifié automatiquement
    par la tâche planifiée Windows toutes les 30 minutes). `tester_fn` ne doit JAMAIS être appelé
    tant que le disque est insuffisant — jamais un test réel gaspillé/mal classé pour cette cause."""
    import scripts.autopilot.git_safety as git_safety_module

    tester_calls = {"count": 0}

    def counting_tester(mission):
        tester_calls["count"] += 1
        return {"success": True, "summary": "3 passed"}

    monkeypatch.setattr(
        git_safety_module, "check_disk_space",
        lambda *a, **k: "espace disque insuffisant : 1.36 Go libres < seuil 2.0 Go (mission §9 — BLOCKED_SAFETY).",
    )

    supervisor, git_ops, state_store = _make_supervisor(tmp_path, tester_fn=counting_tester)
    supervisor.acquire_lock()
    # État avancé directement à TESTING (jamais via BOOTSTRAPPING, qui a son PROPRE garde disque
    # déjà testé séparément) — isole précisément le garde ajouté à TESTING par ce correctif.
    state_store.save(AutopilotStateRecord(
        phase=AutopilotState.TESTING.value, mission_id="M1", branch="master",
    ))

    final_state = supervisor.run_one_step()

    assert final_state == AutopilotState.BLOCKED_SAFETY
    record = state_store.load()
    assert record.blocked_reason_category == "disk_space"
    assert record.resume_to_phase == AutopilotState.TESTING.value
    assert tester_calls["count"] == 0  # jamais appelé, jamais gaspillé/mal classé


def test_blocked_safety_on_low_disk_space_during_testing_resolves_once_space_is_freed(tmp_path, monkeypatch):
    """Complète le test précédent : une fois l'espace disque redevenu suffisant, la reprise doit
    réellement continuer vers TESTING (jamais un effacement d'état, jamais un Human Gate) — la
    même mécanique déjà testée pour `dirty_worktree`, ici appliquée à `disk_space` déclenché
    depuis TESTING plutôt que BOOTSTRAPPING."""
    import scripts.autopilot.git_safety as git_safety_module

    disk_state = {"low": True}

    def toggleable_disk_check(*a, **k):
        if disk_state["low"]:
            return "espace disque insuffisant : 1.36 Go libres < seuil 2.0 Go (mission §9 — BLOCKED_SAFETY)."
        return None

    monkeypatch.setattr(git_safety_module, "check_disk_space", toggleable_disk_check)

    supervisor, git_ops, state_store = _make_supervisor(tmp_path)
    supervisor.acquire_lock()
    state_store.save(AutopilotStateRecord(
        phase=AutopilotState.TESTING.value, mission_id="M1", branch="master",
    ))

    blocked = supervisor.run_one_step()
    assert blocked == AutopilotState.BLOCKED_SAFETY
    assert state_store.load().blocked_reason_category == "disk_space"

    still_blocked = supervisor.run_one_step()
    assert still_blocked == AutopilotState.BLOCKED_SAFETY  # toujours sale, jamais forcé

    disk_state["low"] = False
    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION})
    assert final_state == AutopilotState.NEXT_MISSION


def test_stale_unreviewed_artifacts_resolve_once_the_extra_file_is_no_longer_really_dirty(tmp_path):
    """Régression — bug réel confirmé en conditions réelles (mission « poursuite AlphaForge ») :
    `record.artifacts` peut référencer un fichier capturé par un `git status` PASSÉ (ex. un fichier
    édité manuellement en parallèle pendant que la mission était bloquée, puis committé séparément
    entre-temps) sans qu'aucun nouveau DEVELOPING/CORRECTING n'ait tourné pour rafraîchir cette
    liste. `_handle_pre_commit_check()` bloquait alors indéfiniment sur un fichier qui n'est PLUS
    réellement modifié — jamais résolu automatiquement avant ce correctif (`unreviewed_files`
    n'avait même pas de `resume_to_phase`, retombant dangereusement sur un redémarrage PLANNING).
    Doit désormais se résoudre dès que le diff RÉEL actuel est entièrement couvert par la review,
    en rafraîchissant `artifacts` vers cette liste réelle — jamais en tolérant un fichier
    authentiquement non revu."""
    supervisor, git_ops, state_store = _make_supervisor(tmp_path)
    supervisor.acquire_lock()
    state_store.save(AutopilotStateRecord(
        phase=AutopilotState.BLOCKED_SAFETY.value, mission_id="M1", branch="master",
        # "external_file.md" a été committé séparément entre-temps — plus réellement dirty.
        artifacts=("dummy.py", "external_file.md"), reviewed_files=("dummy.py",),
        blocked_reason_category="unreviewed_files", resume_to_phase=AutopilotState.PRE_COMMIT_CHECK.value,
    ))
    git_ops.simulated_dirty_paths = ["dummy.py"]  # external_file.md n'est plus dans le diff réel

    final_state = supervisor.run_until({AutopilotState.NEXT_MISSION, AutopilotState.BLOCKED_SAFETY}, max_steps=20)

    assert final_state == AutopilotState.NEXT_MISSION
    assert git_ops.committed is True


def test_unreviewed_artifacts_stay_blocked_while_a_genuinely_unreviewed_file_is_still_dirty(tmp_path):
    """Symétrique : si le fichier non revu est ENCORE réellement modifié, jamais résolu
    automatiquement — une vraie violation de scope reste bloquée indéfiniment sans intervention."""
    supervisor, git_ops, state_store = _make_supervisor(tmp_path)
    supervisor.acquire_lock()
    state_store.save(AutopilotStateRecord(
        phase=AutopilotState.BLOCKED_SAFETY.value, mission_id="M1", branch="master",
        artifacts=("dummy.py", "sneaked_in.py"), reviewed_files=("dummy.py",),
        blocked_reason_category="unreviewed_files", resume_to_phase=AutopilotState.PRE_COMMIT_CHECK.value,
    ))
    git_ops.simulated_dirty_paths = ["dummy.py", "sneaked_in.py"]  # toujours réellement dirty

    for _ in range(5):
        assert supervisor.run_one_step() == AutopilotState.BLOCKED_SAFETY
    assert git_ops.committed is False
