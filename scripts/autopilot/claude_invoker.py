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
empiriquement lors de cette mission par DEUX sondages réels distincts : (1) un tour échoué par
dépassement de budget — objet PLAT `type`/`subtype`/`is_error`/`session_id`/`total_cost_usd`/
`duration_ms`/`usage`, jamais de `result` (aucune réponse produite) ; (2) un tour réussi avec
`--json-schema` — porte EN PLUS un champ `structured_output` (l'objet validé par le schéma,
DÉJÀ un dict natif, jamais une chaîne à re-parser) ET, séparément, un `result` qui est la MÊME
donnée réencodée en chaîne JSON. `structured_output` est la source AUTORITATIVE de
`result_structured` — trouvé nécessaire après que le canary réel de cette mission a silencieusement
traité un Reviewer dont le parsing de `result` avait échoué comme "review propre, 0 finding" (le
verdict affiché restait `?`, jamais authentiquement `CLEAN`) : `result` peut porter du texte
supplémentaire autour du JSON (markdown, préambule) que `structured_output` n'a jamais. Coût réel
observé pour un tour trivial : ~0,32-0,41 $ (dominé par la création de cache du contexte
projet/CLAUDE.md, ~53-57k tokens) — jamais négligeable, à budgéter en conséquence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from scripts.autopilot.quota_detector import FailureCategory, classify_failure

RunFn = Callable[..., Tuple[int, str, str]]  # (argv, prompt, cwd=...) -> (exit_code, stdout, stderr)


def build_claude_argv(
    output_format: str = "json",
    permission_mode: Optional[str] = None,
    max_budget_usd: Optional[float] = None,
    resume_session_id: Optional[str] = None,
    allowed_tools: Optional[List[str]] = None,
    model: Optional[str] = None,
    json_schema: Optional[str] = None,
) -> List[str]:
    """Construit l'argv d'un appel `claude -p ...` non interactif — JAMAIS le prompt lui-même
    (mission finalisation sécurité, bug réel confirmé en conditions réelles sur AF-V-02 Slice 2) :
    un prompt ajouté comme dernier argument de la ligne de commande a fait échouer un `claude -p`
    réel sur Windows avec `FileNotFoundError: [WinError 206] Nom de fichier ou extension trop
    long` dès qu'un lot de diff de review dépassait la limite de longueur de ligne de commande de
    `CreateProcess` (~32k caractères). Confirmé empiriquement (`echo "..." | claude -p
    --output-format json` répond correctement) : `claude -p` lit le prompt depuis STDIN en
    l'absence d'argument positionnel — voir `ClaudeInvoker.run()`/`_real_run()`, qui transmettent
    désormais le prompt via `subprocess.run(..., input=prompt)`, sans limite de longueur
    pratique de ce type. `permission_mode` : l'un de `acceptEdits`/`auto`/`bypassPermissions`/
    `manual`/`dontAsk`/`plan` (choix réels confirmés, `claude --help`) — jamais validé ici (la CLI
    validera elle-même), pour ne pas dupliquer une liste qui pourrait changer de version en
    version. `json_schema` : schéma JSON (chaîne) pour une sortie structurée validée par Claude
    Code lui-même (`--json-schema`, confirmé disponible sur 2.1.220) — utilisé par le Reviewer
    indépendant (mission §3.3/§6)."""
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
        """La réponse structurée d'un appel `--json-schema` — confirmé empiriquement (sondage réel
        de cette mission) : `structured_output` est un dict NATIF déjà validé par le schéma, la
        source AUTORITATIVE, préférée en premier. Repli sur `result` (dict déjà, ou chaîne
        JSON-encodée à désérialiser) seulement si `structured_output` est absent — ex. version de
        Claude Code différente, ou aucun `--json-schema` fourni. Retourne `None` si rien n'est
        exploitable — jamais une exception propagée pour une sortie inattendue d'un processus
        externe, et jamais un dict vide qui se ferait passer pour "aucun finding" (voir
        `cli.py:real_reviewer_fn`, qui doit traiter ce `None` comme un échec technique, pas comme
        une review propre — trouvé réellement silencieux lors du canary de cette mission)."""
        if self.parsed is None:
            return None
        structured = self.parsed.get("structured_output")
        if isinstance(structured, dict):
            return structured
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


# Filet de sécurité final (mission §9/§3.6) — trouvé absent par la revue safety/architecture V1.1 :
# sans cela, un `claude -p` bloqué (réseau, CLI qui hang malgré `--output-format json`) rendait le
# signal d'arrêt coopératif (`StopSignal`, vérifié seulement ENTRE deux étapes de la boucle) sans
# effet pratique — un hang à l'intérieur d'UNE étape restait bloqué indéfiniment. Généreux (30 min)
# — un vrai travail de développement légitime peut prendre du temps ; ce n'est pas un plafond de
# coût (`--max-budget-usd` s'en charge), seulement une garantie de terminaison éventuelle.
CLAUDE_SUBPROCESS_TIMEOUT_SECONDS = 1800


def _real_run(argv: List[str], prompt: str, cwd: Optional[str] = None) -> Tuple[int, str, str]:
    import subprocess

    # `encoding="utf-8", errors="replace"` explicite — jamais le défaut de locale Windows
    # (cp1252), qui a réellement fait planter un thread lecteur de `subprocess` (crash silencieux,
    # non fatal pour le process appelant mais une sortie potentiellement tronquée) lors du canary
    # V1.1 : les réponses JSON de `claude -p` peuvent porter des caractères accentués (dépôt en
    # français), tout comme le diff/les messages Git. `cwd` explicite (finalisation V1.1 §3) —
    # jamais hérité implicitement du répertoire de travail du process appelant : un `claude -p`
    # lancé depuis un mauvais répertoire modifierait/lirait le mauvais dépôt. `input=prompt`
    # (finalisation sécurité, bug réel confirmé sur AF-V-02 Slice 2) — le prompt n'est JAMAIS un
    # élément d'`argv` (limite de longueur de ligne de commande Windows, ~32k caractères, dépassée
    # en conditions réelles par un lot de diff de review), transmis par STDIN à la place.
    try:
        completed = subprocess.run(
            argv, input=prompt, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=CLAUDE_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        # Jamais une exception non rattrapée hors de `ClaudeInvoker.run()` (contrat : toujours un
        # `ClaudeInvocationResult`, jamais levée) — convertie en échec classifiable normalement.
        stderr = (exc.stderr or "") + f"\n[timeout après {CLAUDE_SUBPROCESS_TIMEOUT_SECONDS}s]"
        return 1, exc.stdout or "", stderr
    return completed.returncode, completed.stdout, completed.stderr


class ClaudeInvoker:
    """`run_fn` par défaut lance réellement `claude` via `subprocess.run()` — injectable pour les
    tests (jamais de sous-processus réel dans la suite Autopilot elle-même).

    `cwd` (finalisation V1.1 §3) : répertoire de travail EXPLICITE pour chaque invocation —
    jamais hérité implicitement du répertoire de travail du process Autopilot lui-même (qui
    pourrait différer selon comment/depuis où `autopilot start` a été invoqué). `None` (défaut)
    préserve le comportement historique (hérite du process appelant) pour ne jamais casser un
    `run_fn` de test existant qui n'accepte pas ce paramètre."""

    def __init__(self, run_fn: RunFn = _real_run, cwd: Optional[str] = None):
        self._run_fn = run_fn
        self._cwd = cwd

    def run(self, prompt: str, **kwargs) -> ClaudeInvocationResult:
        # Le prompt n'est JAMAIS passé à `build_claude_argv()` (finalisation sécurité, bug réel
        # confirmé) — transmis séparément à `run_fn` pour un envoi par STDIN, jamais concaténé
        # dans la ligne de commande (limite de longueur Windows dépassée en conditions réelles).
        argv = build_claude_argv(**kwargs)
        if self._cwd is not None:
            exit_code, stdout, stderr = self._run_fn(argv, prompt, cwd=self._cwd)
        else:
            exit_code, stdout, stderr = self._run_fn(argv, prompt)
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
