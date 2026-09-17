"""
scripts/autopilot/claude_invoker.py — Invocation Claude Code CLI (Bootstrap V1, 2026-09-17).

Flags utilisés uniquement parmi ceux réellement confirmés par `claude --help` sur la version
installée (2.1.220) au moment de cette mission — jamais un flag supposé (mission §2). Version à
revérifier si l'installation change (`claude --version`).

**`--dangerously-skip-permissions` n'est jamais construit ici** (mission §9) — l'appelant
(`supervisor.py`) reste responsable de configurer `.claude/settings.json`/hooks pour que le mode
non interactif fonctionne sans ce contournement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from scripts.autopilot.quota_detector import FailureCategory, classify_failure

RunFn = Callable[[List[str]], Tuple[int, str, str]]


def build_claude_argv(
    prompt: str,
    output_format: str = "json",
    permission_mode: Optional[str] = None,
    max_budget_usd: Optional[float] = None,
    resume_session_id: Optional[str] = None,
    allowed_tools: Optional[List[str]] = None,
    model: Optional[str] = None,
) -> List[str]:
    """Construit l'argv d'un appel `claude -p ...` non interactif. `permission_mode` : l'un de
    `acceptEdits`/`auto`/`bypassPermissions`/`manual`/`dontAsk`/`plan` (choix réels confirmés,
    `claude --help`) — jamais validé ici (la CLI validera elle-même), pour ne pas dupliquer une
    liste qui pourrait changer de version en version."""
    argv: List[str] = ["claude", "-p", "--output-format", output_format]
    if permission_mode:
        argv += ["--permission-mode", permission_mode]
    if max_budget_usd is not None:
        argv += ["--max-budget-usd", str(max_budget_usd)]
    if resume_session_id:
        argv += ["--resume", resume_session_id]
    if allowed_tools:
        argv += ["--allowedTools", *allowed_tools]
    if model:
        argv += ["--model", model]
    argv.append(prompt)
    return argv


@dataclass(frozen=True)
class ClaudeInvocationResult:
    exit_code: int
    stdout: str
    stderr: str
    category: Optional[FailureCategory]


def _real_run(argv: List[str]) -> Tuple[int, str, str]:
    import subprocess

    completed = subprocess.run(argv, capture_output=True, text=True)
    return completed.returncode, completed.stdout, completed.stderr


class ClaudeInvoker:
    """`run_fn` par défaut lance réellement `claude` via `subprocess.run()` — injectable pour les
    tests (jamais de sous-processus réel dans la suite Autopilot elle-même)."""

    def __init__(self, run_fn: RunFn = _real_run):
        self._run_fn = run_fn

    def run(self, prompt: str, **kwargs) -> ClaudeInvocationResult:
        argv = build_claude_argv(prompt, **kwargs)
        exit_code, stdout, stderr = self._run_fn(argv)
        category = classify_failure(stderr or stdout) if exit_code != 0 else None
        return ClaudeInvocationResult(exit_code=exit_code, stdout=stdout, stderr=stderr, category=category)
