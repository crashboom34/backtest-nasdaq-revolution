"""
scripts/autopilot/claude_invoker.py — Invocation Claude Code CLI (V1.1, 2026-09-17).

Flags utilisés uniquement parmi ceux réellement confirmés par `claude --help` sur la version
installée (2.1.220) au moment de cette mission — jamais un flag supposé (mission §2). Version à
revérifier si l'installation change (`claude --version`).

**`--dangerously-skip-permissions` n'est jamais construit ici** (mission §9) — l'appelant
(`supervisor.py`/`cli.py`) reste responsable de configurer `.claude/settings.json`/hooks pour que
le mode non interactif fonctionne sans ce contournement.

**V1.1** (mission Autopilot V1.1 §6) : le JSON de sortie (`--output-format json`) est réellement
PARSÉ, `session_id` et `total_cost_usd` sont extraits, et `exit_code == 0` n'est plus considéré
comme une preuve suffisante de réussite fonctionnelle — `functionally_succeeded` s'appuie sur le
champ `is_error` du JSON structuré quand il est présent. Forme du JSON réel confirmée
empiriquement lors de cette mission (un appel `-p --output-format json` réel, cas d'échec par
dépassement de budget) : objet PLAT portant au minimum `type`, `subtype`, `is_error`,
`session_id`, `total_cost_usd`, `duration_ms`, `usage` — `result` (texte de réponse) n'apparaît
que sur un tour réussi, non observé directement lors de ce sondage (budget épuisé avant réponse).
Coût réel observé pour un tour trivial : ~0,32 $ (dominé par la création de cache du contexte
projet/CLAUDE.md, ~53k tokens) — jamais négligeable, à budgéter en conséquence."""

from __future__ import annotations

import json
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
    json_schema: Optional[str] = None,
) -> List[str]:
    """Construit l'argv d'un appel `claude -p ...` non interactif. `permission_mode` : l'un de
    `acceptEdits`/`auto`/`bypassPermissions`/`manual`/`dontAsk`/`plan` (choix réels confirmés,
    `claude --help`) — jamais validé ici (la CLI validera elle-même), pour ne pas dupliquer une
    liste qui pourrait changer de version en version. `json_schema` : schéma JSON (chaîne) pour
    une sortie structurée validée par Claude Code lui-même (`--json-schema`, confirmé disponible
    sur 2.1.220) — utilisé par le Reviewer indépendant (mission §3.3/§6)."""
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
    if json_schema:
        argv += ["--json-schema", json_schema]
    argv.append(prompt)
    return argv


@dataclass(frozen=True)
class ClaudeInvocationResult:
    exit_code: int
    stdout: str
    stderr: str
    category: Optional[FailureCategory]
    session_id: Optional[str] = None
    parsed: Optional[dict] = None
    cost_usd: Optional[float] = None

    @property
    def functionally_succeeded(self) -> bool:
        """`exit_code == 0` seul n'est JAMAIS une preuve suffisante de réussite fonctionnelle
        (mission §6) — s'appuie en priorité sur `is_error` du JSON structuré quand disponible,
        car Claude Code peut sortir en erreur logique (budget épuisé, tour incomplet...) même si
        le process lui-même se termine, et inversement."""
        if self.parsed is not None and "is_error" in self.parsed:
            return self.exit_code == 0 and self.parsed["is_error"] is False
        return self.exit_code == 0

    @property
    def result_text(self) -> Optional[str]:
        """Le champ `result` du JSON structuré (texte de réponse sur un tour réussi), ou `None`
        s'il est absent (échec avant réponse, ou parsing JSON impossible)."""
        if self.parsed is not None:
            value = self.parsed.get("result")
            return value if isinstance(value, str) else None
        return None

    @property
    def result_structured(self) -> Optional[dict]:
        """La réponse structurée d'un appel `--json-schema` — forme exacte non confirmée
        empiriquement par cette mission (le sondage réel a épuisé son budget avant réponse) : gère
        les deux formes plausibles sans supposer laquelle Claude Code produit — `result` déjà un
        objet (retourné tel quel), ou `result` une chaîne JSON-encodée (désérialisée). Retourne
        `None` pour toute autre forme — jamais une exception propagée pour une sortie inattendue
        d'un processus externe."""
        if self.parsed is None:
            return None
        raw = self.parsed.get("result")
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                candidate = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return None
            return candidate if isinstance(candidate, dict) else None
        return None


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
        parsed: Optional[dict] = None
        if stdout:
            try:
                candidate = json.loads(stdout)
            except (json.JSONDecodeError, TypeError):
                candidate = None
            if isinstance(candidate, dict):
                parsed = candidate
        session_id = parsed.get("session_id") if parsed else None
        cost_usd = parsed.get("total_cost_usd") if parsed else None
        return ClaudeInvocationResult(
            exit_code=exit_code, stdout=stdout, stderr=stderr, category=category,
            session_id=session_id, parsed=parsed, cost_usd=cost_usd,
        )
