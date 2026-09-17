"""
tests/test_autopilot_cli.py — Bootstrap Autopilot V1 (2026-09-17), mission §14/§20.

Teste uniquement la logique pure (formatage du statut, dispatch de commande, garde
`RealGitOps`) — n'invoque jamais un vrai sous-processus `claude`/`git` ni ne démarre une vraie
boucle Autopilot (mission Phase D : dry-run sûr uniquement)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.cli import RealGitOps, build_status_summary, main
from scripts.autopilot.state_machine import AutopilotState, AutopilotStateStore, build_state_record
from scripts.autopilot.supervisor import ForbiddenGitCommandError


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

    def fake_run(argv, cwd, capture_output, text):
        class _Result:
            returncode = 0
            stderr = ""
            stdout = "app_corrupted_backup.py\n" if argv[:3] == ["git", "diff", "--cached"] else ""
        return _Result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path)

    with pytest.raises(ForbiddenGitCommandError):
        git_ops.commit("autopilot: test")


def test_real_git_ops_commit_succeeds_when_staged_index_is_in_scope(tmp_path, monkeypatch):
    import scripts.autopilot.cli as cli_module

    calls = []

    def fake_run(argv, cwd, capture_output, text):
        calls.append(argv)

        class _Result:
            returncode = 0
            stderr = ""
            stdout = "scripts/autopilot/cli.py\n" if argv[:3] == ["git", "diff", "--cached"] else ""
        return _Result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path)

    git_ops.commit("autopilot: test")

    assert calls[-1][:2] == ["git", "commit"]


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
    (tmp_path / "autopilot.lock").write_text("locked", encoding="utf-8")

    exit_code = main(["stop"])
    assert exit_code == 0
    assert not (tmp_path / "autopilot.lock").exists()


def test_main_rejects_an_unknown_command():
    with pytest.raises(SystemExit):
        main(["this-command-does-not-exist"])
