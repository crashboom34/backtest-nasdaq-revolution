"""
tests/test_autopilot_cli.py — Autopilot V1.1 (2026-09-17), mission §3.1/§3.5/§3.6/§3.7/§14/§20.

Teste uniquement la logique pure (formatage du statut, dispatch de commande, garde
`RealGitOps`) — n'invoque jamais un vrai sous-processus `claude`/`git` ni ne démarre une vraie
boucle Autopilot contre le dépôt réel (les tests de boucle réelle utilisent des doublures pour
`subprocess.run`, jamais un accès réseau/disque réel)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.cli import RealGitOps, build_status_summary, main
from scripts.autopilot.state_machine import AutopilotState, AutopilotStateStore, build_state_record
from scripts.autopilot.supervisor import ForbiddenGitCommandError


def _fake_result(stdout="", returncode=0, stderr=""):
    class _Result:
        pass

    r = _Result()
    r.stdout = stdout
    r.returncode = returncode
    r.stderr = stderr
    return r


def test_status_summary_with_no_state_says_never_started(tmp_path):
    store = AutopilotStateStore(tmp_path / "state.json")
    summary = build_status_summary(store)
    assert "jamais démarré" in summary.lower() or "aucun état" in summary.lower()


def test_status_summary_reports_current_phase(tmp_path):
    store = AutopilotStateStore(tmp_path / "state.json")
    store.save(build_state_record(
        phase=AutopilotState.TESTING, mission_id="M1", branch="master", head="abc123",
        next_action="exécuter les tests",
    ))
    summary = build_status_summary(store)
    assert "TESTING" in summary
    assert "M1" in summary
    assert "abc123" in summary


def test_status_summary_surfaces_a_human_gate_reason_prominently(tmp_path):
    store = AutopilotStateStore(tmp_path / "state.json")
    store.save(build_state_record(
        phase=AutopilotState.HUMAN_GATE_REQUIRED, mission_id="M1", branch="master",
        stop_reason="# 🚦 HUMAN_GATE_REQUIRED\n\n## Décision\nX",
    ))
    summary = build_status_summary(store)
    assert "HUMAN_GATE_REQUIRED" in summary
    assert "Décision" in summary


def test_real_git_ops_rejects_a_forced_push_before_any_subprocess(tmp_path, monkeypatch):
    """La garde git_safety doit intercepter AVANT tout subprocess.run() réel — vérifié en faisant
    échouer le test si subprocess.run est jamais appelé pour une commande interdite."""
    import scripts.autopilot.cli as cli_module

    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run() ne doit jamais être appelé pour une commande interdite")

    monkeypatch.setattr(cli_module.subprocess, "run", _boom)
    git_ops = RealGitOps(repo_dir=tmp_path)

    with pytest.raises(ForbiddenGitCommandError):
        git_ops.push(force=True)


def test_real_git_ops_rejects_a_protected_path_in_scope(tmp_path, monkeypatch):
    import scripts.autopilot.cli as cli_module

    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run() ne doit jamais être appelé pour un scope protégé")

    monkeypatch.setattr(cli_module.subprocess, "run", _boom)
    git_ops = RealGitOps(repo_dir=tmp_path)

    with pytest.raises(ForbiddenGitCommandError):
        git_ops.add(["app_corrupted_backup.py"])


def test_real_git_ops_commit_rejects_a_protected_path_already_staged_outside_add(tmp_path, monkeypatch):
    """Régression — revue safety/architecture du Bootstrap (IMPORTANT 2) : `check_scope_files()`
    ne validait que les chemins passés à `add()`, jamais l'index Git réel au moment du commit — un
    contenu étranger/protégé déjà indexé (reprise après crash, `git add` humain laissé en cours)
    pouvait entrer dans un commit Autopilot sans jamais être détecté. `commit()` doit désormais
    relire l'index réel (`git diff --cached --name-only`) et le revalider avant de committer."""
    import scripts.autopilot.cli as cli_module

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "diff", "--cached", "--name-only"]:
            return _fake_result(stdout="app_corrupted_backup.py\n")
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path)

    with pytest.raises(ForbiddenGitCommandError):
        git_ops.commit("autopilot: test")


def test_real_git_ops_commit_rejects_a_secret_found_in_the_staged_diff(tmp_path, monkeypatch):
    """Mission Autopilot V1.1 §3.7 : secrets/gros fichiers doivent être contrôlés sur le CHEMIN
    D'EXÉCUTION RÉEL du commit, pas seulement via les fonctions pures isolées de `git_safety.py`."""
    import scripts.autopilot.cli as cli_module

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "diff", "--cached", "--name-only"]:
            return _fake_result(stdout="config.py\n")
        if argv == ["git", "diff", "--cached"]:
            return _fake_result(stdout='api_key = "AKIAABCDEFGHIJKLMNOP"\n')
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path)

    with pytest.raises(ForbiddenGitCommandError):
        git_ops.commit("autopilot: test")


def test_real_git_ops_commit_succeeds_when_staged_index_is_in_scope(tmp_path, monkeypatch):
    import scripts.autopilot.cli as cli_module

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        calls.append(argv)
        if argv == ["git", "diff", "--cached", "--name-only"]:
            return _fake_result(stdout="scripts/autopilot/cli.py\n")
        if argv == ["git", "diff", "--cached"]:
            return _fake_result(stdout="+ trivial change\n")
        if argv == ["git", "diff", "--cached", "--numstat"]:
            return _fake_result(stdout="")
        if argv == ["git", "rev-parse", "HEAD"]:
            return _fake_result(stdout="deadbeefcafe\n")
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path)

    sha = git_ops.commit("autopilot: test")

    assert any(c[:2] == ["git", "commit"] for c in calls)
    assert sha == "deadbeefcafe"


def test_real_git_ops_push_fetches_and_proceeds_when_origin_is_an_ancestor_of_head(tmp_path, monkeypatch):
    """Mission Autopilot V1.1 §3.7/§8 : `git fetch origin` doit avoir lieu avant tout push réel ;
    quand `origin/master` est un ancêtre de HEAD (avance normale, fast-forward), le push procède.
    Finalisation V1.1 §2.D : vérifie aussi que la branche courante est explicitement contrôlée et
    que le SHA distant final est revérifié après le push (pas seulement supposé réussi)."""
    import scripts.autopilot.cli as cli_module

    calls = []
    origin_rev_parse_calls = {"count": 0}

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        calls.append(argv)
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")
        if argv == ["git", "rev-parse", "origin/master"]:
            origin_rev_parse_calls["count"] += 1
            if origin_rev_parse_calls["count"] == 1:
                return _fake_result(stdout="oldsha\n")  # avant push : état distant connu
            return _fake_result(stdout="newsha\n")  # après push : le distant a bien avancé
        if argv == ["git", "rev-parse", "HEAD"]:
            return _fake_result(stdout="newsha\n")
        if argv == ["git", "merge-base", "--is-ancestor", "oldsha", "HEAD"]:
            return _fake_result(returncode=0)  # oldsha EST un ancêtre -> avance normale
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path, branch="master")

    pushed_sha = git_ops.push()

    assert ["git", "fetch", "origin"] in calls
    assert any(c[:2] == ["git", "push"] for c in calls)
    assert pushed_sha == "newsha"


def test_real_git_ops_push_uses_an_explicit_refspec_never_a_hardcoded_master(tmp_path, monkeypatch):
    """Régression — bug réel confirmé (mission finalisation V1.1 §2.D) : le code poussait
    inconditionnellement `git push origin master`, quelle que soit la branche RÉELLEMENT extraite
    dans le worktree — dangereux dès qu'un worktree dédié travaille sur une autre branche.
    `push()` doit désormais vérifier HEAD explicitement et utiliser un refspec `branche:cible`."""
    import scripts.autopilot.cli as cli_module

    calls = []
    origin_calls = {"count": 0}

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        calls.append(argv)
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="autopilot/permanent\n")
        if argv == ["git", "rev-parse", "origin/master"]:
            origin_calls["count"] += 1
            return _fake_result(stdout="oldsha\n" if origin_calls["count"] == 1 else "newsha\n")
        if argv == ["git", "rev-parse", "HEAD"]:
            return _fake_result(stdout="newsha\n")
        if argv == ["git", "merge-base", "--is-ancestor", "oldsha", "HEAD"]:
            return _fake_result(returncode=0)
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path, branch="autopilot/permanent", remote_ref="master")

    git_ops.push()

    push_calls = [c for c in calls if c[:2] == ["git", "push"]]
    assert push_calls == [["git", "push", "origin", "autopilot/permanent:master"]]


def test_real_git_ops_push_refuses_when_head_does_not_match_the_declared_branch(tmp_path, monkeypatch):
    """Régression — mission finalisation V1.1 §2.D : ne jamais pousser sans vérifier explicitement
    que HEAD correspond bien à la branche de travail déclarée."""
    import scripts.autopilot.cli as cli_module

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="some-other-branch\n")
        raise AssertionError("aucune autre commande Git ne doit être tentée après un mismatch de branche")

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path, branch="autopilot/permanent")

    with pytest.raises(RuntimeError, match="branche de travail inattendue"):
        git_ops.push()


def test_real_git_ops_push_refuses_on_real_divergence_never_forcing(tmp_path, monkeypatch):
    """Quand `origin/master` N'EST PAS un ancêtre de HEAD (divergence réelle — quelqu'un/quelque
    chose d'autre a poussé), le push doit être refusé (levée d'exception, jamais silencieux) et
    JAMAIS automatiquement forcé (mission §8 : "ne jamais forcer, diagnostiquer la divergence")."""
    import scripts.autopilot.cli as cli_module

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")
        if argv == ["git", "rev-parse", "origin/master"]:
            return _fake_result(stdout="othersha\n")
        if argv == ["git", "rev-parse", "HEAD"]:
            return _fake_result(stdout="mysha\n")
        if argv == ["git", "merge-base", "--is-ancestor", "othersha", "HEAD"]:
            return _fake_result(returncode=1)  # PAS un ancêtre -> vraie divergence
        if argv[:2] == ["git", "push"]:
            raise AssertionError("git push ne doit jamais être tenté en cas de divergence non comprise")
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path)

    with pytest.raises(RuntimeError, match="divergence"):
        git_ops.push()


def test_run_readonly_git_routes_through_git_safety_before_any_subprocess(monkeypatch):
    """Régression — revue safety/architecture V1.1 : plusieurs commandes Git en lecture seule
    (`git status`, `git diff HEAD`, `git rev-parse`, `git merge-base --is-ancestor`) contournaient
    encore `git_safety.check_git_command()`, malgré la promesse documentée du module. Aucune
    n'est aujourd'hui sur liste noire, mais toute commande Git doit passer par ce garde sans
    exception — testé ici avec un argv volontairement interdit pour le prouver."""
    import scripts.autopilot.cli as cli_module

    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run() ne doit jamais être appelé pour une commande interdite")

    monkeypatch.setattr(cli_module.subprocess, "run", _boom)

    with pytest.raises(cli_module.ForbiddenGitCommandError):
        cli_module._run_readonly_git(["git", "reset", "--hard"])


def test_run_readonly_git_passes_a_timeout_to_subprocess(monkeypatch):
    import scripts.autopilot.cli as cli_module

    seen_kwargs = {}

    def fake_run(argv, **kwargs):
        seen_kwargs.update(kwargs)
        return _fake_result(stdout="")

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    cli_module._run_readonly_git(["git", "status", "--porcelain"])

    assert seen_kwargs.get("timeout") == cli_module.GIT_TIMEOUT_SECONDS


def test_real_tester_fn_pytest_timeout_never_raises_and_is_classified_as_a_failure(monkeypatch):
    """Régression — revue safety/architecture V1.1 : un `pytest` bloqué devait être borné et ne
    jamais laisser `subprocess.TimeoutExpired` s'échapper hors de `real_tester_fn` (contrat :
    toujours un dict, jamais une exception non rattrapée hors de `run_one_step()`)."""
    import subprocess

    import scripts.autopilot.cli as cli_module

    def fake_run(argv, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        assert kwargs.get("timeout") == cli_module.PYTEST_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs["timeout"])

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()

    result = supervisor._tester_fn(None)

    assert result["success"] is False
    assert "timeout" in result["summary"].lower()


def test_real_tester_fn_runs_the_full_suite_when_mission_is_none(monkeypatch):
    """Régression — trouvé non testé par la revue reproductibilité/scope V1.1 : les 4 branches de
    `real_tester_fn` (mission absente, targeted_tests vide, targeted en échec, targeted en succès
    + risque élevé) n'avaient aucune couverture dédiée alors que cette fonction décide si la
    régression complète tourne avant un commit/push réel."""
    import scripts.autopilot.cli as cli_module

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        calls.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()

    result = supervisor._tester_fn(None)

    assert result["success"] is True
    assert len(calls) == 1  # une seule commande : la suite complète, aucun ciblage possible


def test_real_tester_fn_runs_the_full_suite_when_targeted_tests_is_empty(monkeypatch):
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        calls.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(id="M1", title="x", status="PLANNED", prompt_file="m1.md", targeted_tests=())

    result = supervisor._tester_fn(mission)

    assert result["success"] is True
    assert len(calls) == 1


def test_real_tester_fn_stops_immediately_when_targeted_tests_fail(monkeypatch):
    """Échec rapide (mission §5) : jamais de suite complète lancée après un échec ciblé."""
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        calls.append(argv)
        return _fake_result(stdout="1 failed", returncode=1)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(
        id="M1", title="x", status="PLANNED", prompt_file="m1.md",
        targeted_tests=("tests/test_x.py",), risk_level="low",
    )

    result = supervisor._tester_fn(mission)

    assert result["success"] is False
    assert len(calls) == 1  # jamais la suite complète après un échec ciblé


def test_real_tester_fn_reruns_full_suite_for_high_risk_missions_even_after_targeted_pass(monkeypatch):
    """Mission §5 : régression complète imposée pour une mission à risque élevé, même si les
    tests ciblés passent déjà."""
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        calls.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(
        id="M1", title="x", status="PLANNED", prompt_file="m1.md",
        targeted_tests=("tests/test_x.py",), risk_level="high",
    )

    result = supervisor._tester_fn(mission)

    assert result["success"] is True
    assert len(calls) == 2  # ciblé d'abord, PUIS la suite complète imposée par le risque élevé


def test_real_tester_fn_reruns_full_suite_when_scientific_contracts_declared(monkeypatch):
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        calls.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(
        id="M1", title="x", status="PLANNED", prompt_file="m1.md",
        targeted_tests=("tests/test_x.py",), risk_level="low",
        scientific_contracts=("ADR-0021",),
    )

    result = supervisor._tester_fn(mission)

    assert result["success"] is True
    assert len(calls) == 2


def test_real_tester_fn_skips_full_suite_for_low_risk_mission_with_no_scientific_contracts(monkeypatch):
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        calls.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(
        id="M1", title="x", status="PLANNED", prompt_file="m1.md",
        targeted_tests=("tests/test_x.py",), risk_level="low",
    )

    result = supervisor._tester_fn(mission)

    assert result["success"] is True
    assert len(calls) == 1  # ciblé suffit, jamais la suite complète pour ce cas


def test_real_tester_fn_invokes_sys_executable_not_a_hardcoded_relative_venv_path(monkeypatch):
    """Régression — trouvé RÉELLEMENT cassé par le canary V1.1 (mission §9) : un chemin relatif
    codé en dur (".venv/Scripts/python.exe") échoue (`FileNotFoundError`/`WinError 2`) dans tout
    déploiement qui n'a pas son PROPRE `.venv/` local sous `REPO_ROOT` — ex. le worktree isolé
    `autopilot/v1-1-operational` de cette mission, qui réutilise délibérément l'interpréteur du
    dépôt principal. `sys.executable` doit être utilisé à la place, toujours correct."""
    import scripts.autopilot.cli as cli_module

    seen_argv = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        seen_argv.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()

    supervisor._tester_fn(None)

    assert seen_argv, "aucun subprocess.run() n'a été appelé"
    assert seen_argv[0][0] == cli_module.sys.executable
    assert ".venv/Scripts/python.exe" not in seen_argv[0]


def test_real_git_ops_is_worktree_clean_reflects_git_status_porcelain(tmp_path, monkeypatch):
    """Régression — mission Autopilot V1.1 §4 : `mission.requires_clean_worktree` était déclaré
    dans le schéma mais jamais réellement câblé à une vérification Git réelle avant cette mission."""
    import scripts.autopilot.cli as cli_module

    def fake_run_clean(argv, cwd, capture_output, text, **kwargs):
        return _fake_result(stdout="")

    def fake_run_dirty(argv, cwd, capture_output, text, **kwargs):
        return _fake_result(stdout=" M some_file.py\n")

    git_ops = RealGitOps(repo_dir=tmp_path)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run_clean)
    assert git_ops.is_worktree_clean() is True

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run_dirty)
    assert git_ops.is_worktree_clean() is False


def test_record_real_git_context_fills_head_and_origin_master(tmp_path, monkeypatch):
    """Régression — mission §6 : `head`/`origin_master` sont des champs d'audit requis, mais
    restaient toujours `(inconnu)` (`None`) tout au long du canary V1.1 réel — jamais renseignés
    nulle part sur le chemin réel avant ce correctif."""
    import scripts.autopilot.cli as cli_module

    def fake_run(argv, cwd=None, capture_output=None, text=None, **kwargs):
        if argv == ["git", "rev-parse", "HEAD"]:
            return _fake_result(stdout="realhead123\n")
        if argv == ["git", "rev-parse", "origin/master"]:
            return _fake_result(stdout="realorigin456\n")
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    store = AutopilotStateStore(tmp_path / "state.json")
    store.save(build_state_record(phase=AutopilotState.READY, mission_id=None, branch="master"))

    cli_module._record_real_git_context(store)

    record = store.load()
    assert record.head == "realhead123"
    assert record.origin_master == "realorigin456"


def test_record_real_git_context_never_raises_when_no_state_exists(tmp_path):
    import scripts.autopilot.cli as cli_module

    store = AutopilotStateStore(tmp_path / "state.json")
    cli_module._record_real_git_context(store)  # ne doit jamais lever, même sans état existant

    assert store.load() is None


def test_main_status_command_returns_zero(tmp_path, monkeypatch, capsys):
    import scripts.autopilot.cli as cli_module

    monkeypatch.setattr(cli_module, "STATE_PATH", tmp_path / "state.json")
    exit_code = main(["status"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "état" in captured.out.lower() or "démarré" in captured.out.lower()


def test_main_stop_command_cleans_an_orphaned_lock_and_returns_zero(tmp_path, monkeypatch, capsys):
    """Régression — finalisation V1.1 §2.A : ce test écrivait auparavant un verrou au contenu
    illisible ("locked", pas du JSON) et attendait qu'il soit TOUJOURS supprimé — c'était
    exactement le comportement buggé (`force_release()` inconditionnel). Un contenu illisible est
    désormais traité prudemment comme "peut-être détenu" (jamais volé) — ce test écrit donc un
    verrou explicitement ORPHELIN (PID mort) pour vérifier que ce cas reste bien nettoyé."""
    import json as _json

    import scripts.autopilot.cli as cli_module

    monkeypatch.setattr(cli_module, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(cli_module, "LOCK_PATH", tmp_path / "autopilot.lock")
    monkeypatch.setattr(cli_module, "STOP_SIGNAL_PATH", tmp_path / "stop.signal")
    (tmp_path / "autopilot.lock").write_text(
        _json.dumps({"pid": 2147483647, "acquired_at_utc": "x", "worktree": "x"}), encoding="utf-8",
    )

    exit_code = main(["stop"])
    assert exit_code == 0
    assert not (tmp_path / "autopilot.lock").exists()
    assert (tmp_path / "stop.signal").exists()  # signal coopératif déposé (mission §3.6)


def test_main_stop_command_never_removes_a_lock_with_unreadable_content(tmp_path, monkeypatch):
    """Complète le test précédent : un contenu de verrou illisible (jamais du JSON valide) doit
    être traité prudemment comme "peut-être détenu par un process vivant" — jamais supprimé par
    doute, cohérent avec `_pid_is_alive`/`is_held_by_a_live_process()`."""
    import scripts.autopilot.cli as cli_module

    monkeypatch.setattr(cli_module, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(cli_module, "LOCK_PATH", tmp_path / "autopilot.lock")
    monkeypatch.setattr(cli_module, "STOP_SIGNAL_PATH", tmp_path / "stop.signal")
    (tmp_path / "autopilot.lock").write_text("locked", encoding="utf-8")

    exit_code = main(["stop"])
    assert exit_code == 0
    assert (tmp_path / "autopilot.lock").exists()  # jamais supprimé par doute


def test_main_rejects_an_unknown_command():
    with pytest.raises(SystemExit):
        main(["this-command-does-not-exist"])
