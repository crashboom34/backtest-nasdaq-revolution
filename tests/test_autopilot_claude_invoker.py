"""
tests/test_autopilot_claude_invoker.py — Bootstrap Autopilot V1 (2026-09-17), mission §2/§13.

`ClaudeInvoker` construit l'argv réel (uniquement des flags confirmés par `claude --help` sur la
version installée, 2.1.220 — jamais un flag supposé) et classe l'échec via `quota_detector` sans
jamais réellement lancer de sous-processus dans ces tests (fonction `run_fn` injectée)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.claude_invoker import ClaudeInvoker, build_claude_argv
from scripts.autopilot.quota_detector import FailureCategory


def test_build_claude_argv_uses_print_and_json_output():
    argv = build_claude_argv("do the thing")
    assert argv[0] == "claude"
    assert "-p" in argv or "--print" in argv
    assert "--output-format" in argv
    assert "json" in argv
    assert "do the thing" in argv


def test_build_claude_argv_includes_permission_mode_when_given():
    argv = build_claude_argv("x", permission_mode="acceptEdits")
    assert "--permission-mode" in argv
    assert "acceptEdits" in argv


def test_build_claude_argv_includes_max_budget_when_given():
    argv = build_claude_argv("x", max_budget_usd=5.0)
    assert "--max-budget-usd" in argv
    assert "5.0" in argv


def test_build_claude_argv_includes_resume_session_id_when_given():
    argv = build_claude_argv("x", resume_session_id="abc-123")
    assert "--resume" in argv
    assert "abc-123" in argv


def test_build_claude_argv_never_includes_dangerously_skip_permissions_by_default():
    """Mission §9 : "ne pas utiliser --dangerously-skip-permissions comme solution générale"."""
    argv = build_claude_argv("x")
    assert "--dangerously-skip-permissions" not in argv
    assert "--allow-dangerously-skip-permissions" not in argv


def test_invoker_returns_success_result_on_zero_exit():
    def fake_run(argv):
        return 0, '{"result": "ok"}', ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("do the thing")
    assert result.exit_code == 0
    assert result.category is None
    assert result.stdout == '{"result": "ok"}'


def test_invoker_classifies_failure_category_on_nonzero_exit():
    def fake_run(argv):
        return 1, "", "Error: rate_limit_error - exceeded"

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("do the thing")
    assert result.exit_code == 1
    assert result.category is FailureCategory.QUOTA_LIMIT


def test_invoker_passes_the_built_argv_to_run_fn():
    seen = {}

    def fake_run(argv):
        seen["argv"] = argv
        return 0, "{}", ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    invoker.run("hello world", permission_mode="acceptEdits")
    assert "hello world" in seen["argv"]
    assert "acceptEdits" in seen["argv"]
