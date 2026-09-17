"""
tests/test_autopilot_hooks.py — Bootstrap Autopilot V1 (2026-09-17), mission §10.

Test d'intégration RÉEL du hook `PreToolUse` (sous-processus Python réel, aucune commande Git
réellement exécutée par le hook lui-même — il ne fait qu'inspecter le JSON reçu et retourner un
code de sortie). Mission §10 : "Tester les hooks avec des commandes factices ou des entrées
simulées sans exécuter réellement d'opération destructive" — exactement ce que ce test fait."""

from __future__ import annotations

import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK_SCRIPT = os.path.join(REPO_ROOT, "scripts", "autopilot", "hooks", "pre_bash_safety_check.py")
PYTHON = sys.executable


def _run_hook(command: str) -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(
        [PYTHON, HOOK_SCRIPT], input=payload, capture_output=True, text=True, cwd=REPO_ROOT,
    )


def test_hook_allows_a_normal_git_push():
    result = _run_hook("git push origin master")
    assert result.returncode == 0


def test_hook_blocks_a_force_push():
    result = _run_hook("git push --force origin master")
    assert result.returncode == 2
    assert "BLOQUÉ" in result.stderr


def test_hook_blocks_a_reset_hard_hidden_after_cd():
    result = _run_hook("cd repo && git reset --hard HEAD~1")
    assert result.returncode == 2


def test_hook_allows_a_non_git_command():
    result = _run_hook("pytest -q")
    assert result.returncode == 0


def test_hook_never_crashes_on_malformed_json():
    result = subprocess.run(
        [PYTHON, HOOK_SCRIPT], input="not valid json{{{", capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert result.returncode == 0


def test_hook_never_crashes_on_empty_stdin():
    result = subprocess.run([PYTHON, HOOK_SCRIPT], input="", capture_output=True, text=True, cwd=REPO_ROOT)
    assert result.returncode == 0
