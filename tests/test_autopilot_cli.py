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
    quand `origin/master` est un ancêtre de HEAD (avance normale, fast-forward), le push procède."""
    import scripts.autopilot.cli as cli_module

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        calls.append(argv)
        if argv == ["git", "rev-parse", "origin/master"]:
            return _fake_result(stdout="oldsha\n")
        if argv == ["git", "rev-parse", "HEAD"]:
            return _fake_result(stdout="newsha\n")
        if argv == ["git", "merge-base", "--is-ancestor", "oldsha", "HEAD"]:
            return _fake_result(returncode=0)  # oldsha EST un ancêtre -> avance normale
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path)

    pushed_sha = git_ops.push()

    assert ["git", "fetch", "origin"] in calls
    assert any(c[:2] == ["git", "push"] for c in calls)
    assert pushed_sha == "newsha"


def test_real_git_ops_push_refuses_on_real_divergence_never_forcing(tmp_path, monkeypatch):
    """Quand `origin/master` N'EST PAS un ancêtre de HEAD (divergence réelle — quelqu'un/quelque
    chose d'autre a poussé), le push doit être refusé (levée d'exception, jamais silencieux) et
    JAMAIS automatiquement forcé (mission §8 : "ne jamais forcer, diagnostiquer la divergence")."""
    import scripts.autopilot.cli as cli_module

    def fake_run(argv, cwd, capture_output, text, **kwargs):
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


def test_real_tester_fn_invokes_sys_executable_not_a_hardcoded_relative_venv_path(monkeypatch):
    """Régression — trouvé RÉELLEMENT cassé par le canary V1.1 (mission §9) : un chemin relatif
    codé en dur (".venv/Scripts/python.exe") échoue (`FileNotFoundError`/`WinError 2`) dans tout
    déploiement qui n'a pas son PROPRE `.venv/` local sous `REPO_ROOT` — ex. le worktree isolé
    `autopilot/v1-1-operational` de cette mission, qui réutilise délibérément l'interpréteur du
    dépôt principal. `sys.executable` doit être utilisé à la place, toujours correct."""
    import scripts.autopilot.cli as cli_module

    seen_argv = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        seen_argv.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()

    supervisor._tester_fn(None)

    assert seen_argv, "aucun subprocess.run() n'a été appelé"
    assert seen_argv[0][0] == cli_module.sys.executable
    assert ".venv/Scripts/python.exe" not in seen_argv[0]


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


def test_main_stop_command_releases_the_lock_and_returns_zero(tmp_path, monkeypatch, capsys):
    import scripts.autopilot.cli as cli_module

    monkeypatch.setattr(cli_module, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(cli_module, "LOCK_PATH", tmp_path / "autopilot.lock")
    monkeypatch.setattr(cli_module, "STOP_SIGNAL_PATH", tmp_path / "stop.signal")
    (tmp_path / "autopilot.lock").write_text("locked", encoding="utf-8")

    exit_code = main(["stop"])
    assert exit_code == 0
    assert not (tmp_path / "autopilot.lock").exists()
    assert (tmp_path / "stop.signal").exists()  # signal coopératif déposé (mission §3.6)


def test_main_rejects_an_unknown_command():
    with pytest.raises(SystemExit):
        main(["this-command-does-not-exist"])
