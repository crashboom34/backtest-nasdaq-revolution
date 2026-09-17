"""
scripts/autopilot/cli.py — Points d'entrée CLI Autopilot (V1.1, 2026-09-17).

Appelé par les scripts PowerShell (`start.ps1`/`status.ps1`/`stop.ps1`/`resume.ps1`) via
`python -m scripts.autopilot.cli <commande>`. Construit les collaborateurs RÉELS (`RealGitOps`,
`ClaudeInvoker`) — jamais les doublures utilisées par la suite de tests.

**V1.1** (mission Autopilot V1.1) : `start`/`resume` exécutent désormais RÉELLEMENT la boucle
(`run_until()`, mission §3.1) au lieu de simplement acquérir le verrou et afficher un statut ;
`real_developer_fn` lit le vrai `prompt_file` de la mission et calcule les fichiers modifiés depuis
l'état Git réel (mission §3.2) ; `real_reviewer_fn` invoque une session Claude INDÉPENDANTE (jamais
`--resume` la session du développeur) avec sortie structurée validée par schéma (mission §3.3/§6) ;
`RealGitOps` revalide secrets/gros fichiers/scope sur l'index RÉEL avant chaque commit et vérifie
`git fetch`/divergence avant chaque push (mission §3.7) ; `cmd_stop` envoie un signal d'arrêt
coopératif en plus de libérer le verrou (mission §3.6)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Set

from scripts.autopilot import git_safety
from scripts.autopilot.claude_invoker import ClaudeInvoker
from scripts.autopilot.state_machine import AutopilotState, AutopilotStateStore
from scripts.autopilot.supervisor import (
    AutopilotSupervisor, ForbiddenGitCommandError, SingleInstanceLock, StopSignal,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOPILOT_DIR = REPO_ROOT / ".autopilot"
STATE_PATH = AUTOPILOT_DIR / "state" / "current_state.json"
LOCK_PATH = AUTOPILOT_DIR / "state" / "autopilot.lock"
STOP_SIGNAL_PATH = AUTOPILOT_DIR / "state" / "stop.signal"
MISSIONS_PATH = AUTOPILOT_DIR / "missions.json"

# Plafond de coût par défaut pour un appel `claude -p` réel déclenché par l'Autopilot (mission §9 :
# jamais de contournement de sécurité pour aller plus vite ; mission §6 : budgéter réellement).
# Sondage réel effectué lors de cette mission : un tour TRIVIAL ("reply pong") a déjà coûté ~0,32 $,
# dominé par la création de cache du contexte projet (~53k tokens, CLAUDE.md/mémoire/skills) — un
# plafond de 0,20 $ (essayé lors du sondage) est insuffisant pour un tour réel utile. 3,00 $ vise une
# marge raisonnable au-dessus de ce coût fixe pour un travail réellement utile, sans être illimité.
DEFAULT_MAX_BUDGET_USD = 3.0
# Modèle utilisé pour le diagnostic avant Human Gate (mission §8) — tâche légère (analyse d'un texte
# d'échec, suggestion d'approche), jamais d'édition de fichiers : un modèle moins coûteux suffit.
DIAGNOSTIC_MODEL = "claude-haiku-4-5-20251001"

REVIEW_JSON_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["CLEAN", "FINDINGS"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["BLOCKER", "MAJOR", "MINOR", "SUGGESTION"]},
                    "file": {"type": "string"},
                    "summary": {"type": "string"},
                    "justification": {"type": "string"},
                    "expected_fix": {"type": "string"},
                },
                "required": ["severity", "summary"],
            },
        },
        "scientific_check": {"type": "string"},
        "reproducibility_check": {"type": "string"},
        "security_check": {"type": "string"},
        "architecture_check": {"type": "string"},
    },
    "required": ["verdict", "findings"],
})


class RealGitOps:
    """Implémentation réelle des opérations Git — chaque méthode passe par `git_safety` AVANT
    tout `subprocess.run()` réel, jamais après (voir `tests/test_autopilot_cli.py`, qui vérifie
    qu'aucun `subprocess.run()` n'est même tenté pour une commande interdite).

    **V1.1** : `commit()` revalide secrets/gros fichiers sur le contenu RÉEL de l'index avant de
    committer (mission §3.7) et retourne le SHA produit (idempotence, mission §3.8) ; `push()`
    exécute `git fetch origin` puis vérifie la divergence avant de pousser (mission §3.7/§8) —
    refuse si `origin/master` a avancé d'une façon non triviale à réconcilier (jamais un push
    aveugle, jamais un force push)."""

    def __init__(self, repo_dir: Path = REPO_ROOT):
        self._repo_dir = repo_dir

    def _run(self, argv: List[str]) -> str:
        reason = git_safety.check_git_command(argv)
        if reason:
            raise ForbiddenGitCommandError(reason)
        result = subprocess.run(argv, cwd=self._repo_dir, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Commande Git échouée ({' '.join(argv)}) : {result.stderr}")
        return result.stdout

    def add(self, paths: List[str]) -> None:
        scope_reason = git_safety.check_scope_files(paths)
        if scope_reason:
            raise ForbiddenGitCommandError(scope_reason)
        self._run(["git", "add", "--", *paths])

    def head_commit_message(self) -> Optional[str]:
        try:
            return self._run(["git", "log", "-1", "--pretty=%s"]).strip()
        except RuntimeError:
            return None  # ex. dépôt sans aucun commit — jamais une exception dans un contrôle

    def current_head_sha(self) -> Optional[str]:
        try:
            return self._run(["git", "rev-parse", "HEAD"]).strip()
        except RuntimeError:
            return None

    def commit(self, message: str) -> str:
        # `check_scope_files()` en `add()` ne valide que les chemins PASSÉS à cet appel — pas
        # l'index Git réel au moment du commit, qui peut déjà porter un contenu étranger/protégé
        # (reprise après crash, `git add` humain laissé en cours...). Revalidation juste avant le
        # commit contre l'index RÉEL (trouvé par la revue safety/architecture du Bootstrap).
        staged = [line for line in self._run(["git", "diff", "--cached", "--name-only"]).splitlines() if line]
        scope_reason = git_safety.check_scope_files(staged)
        if scope_reason:
            raise ForbiddenGitCommandError(scope_reason)

        # V1.1 (mission §3.7) : secrets et gros fichiers contrôlés sur l'index RÉEL, pas seulement
        # via les fonctions pures isolées de `git_safety.py` — câblés dans le chemin d'exécution.
        diff_text = self._run(["git", "diff", "--cached"])
        secret_hits = git_safety.check_no_secrets(diff_text)
        if secret_hits:
            raise ForbiddenGitCommandError(
                f"commit refusé : motif(s) de secret détecté(s) dans le diff indexé : {secret_hits} "
                "(mission §3.7 — jamais commité)."
            )
        numstat = self._run(["git", "diff", "--cached", "--numstat"])
        sizes = {}
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                added, _removed, path = parts
                if added.isdigit():
                    full_path = self._repo_dir / path
                    if full_path.is_file():
                        sizes[path] = full_path.stat().st_size
        large_hits = git_safety.check_no_large_files(sizes)
        if large_hits:
            raise ForbiddenGitCommandError(
                f"commit refusé : fichier(s) trop volumineux dans l'index : {large_hits} (mission §3.7)."
            )

        self._run(["git", "commit", "-m", message])
        return (self.current_head_sha() or "").strip()

    def push(self, force: bool = False) -> str:
        argv = ["git", "push", "origin", "master"]
        if force:
            argv.append("--force")
        # La garde doit intercepter une commande interdite (force push, etc.) AVANT tout
        # subprocess.run() réel — y compris avant le `git fetch` préliminaire ci-dessous.
        reason = git_safety.check_git_command(argv)
        if reason:
            raise ForbiddenGitCommandError(reason)

        # V1.1 (mission §3.7/§8) : `git fetch origin` + vérification de divergence AVANT tout push
        # réel — jamais un push aveugle. `origin/master` doit être un ancêtre de HEAD (fast-forward
        # normal) ; toute autre relation (divergence réelle, avance distante non intégrée) est
        # refusée ici (jamais un force push) et laissée à `_handle_pushing()` pour router vers
        # `WAITING_FOR_EXTERNAL_RESOURCE`.
        self._run(["git", "fetch", "origin"])
        try:
            origin_sha = self._run(["git", "rev-parse", "origin/master"]).strip()
        except RuntimeError:
            origin_sha = None
        head_sha = (self.current_head_sha() or "").strip()
        if origin_sha and origin_sha != head_sha:
            is_ancestor = subprocess.run(
                ["git", "merge-base", "--is-ancestor", origin_sha, "HEAD"],
                cwd=self._repo_dir, capture_output=True, text=True,
            )
            if is_ancestor.returncode != 0:
                raise RuntimeError(
                    f"divergence distante détectée (origin/master={origin_sha} n'est pas un "
                    f"ancêtre de HEAD={head_sha}) — jamais forcé, jamais poussé aveuglément."
                )
        argv = ["git", "push", "origin", "master"]
        if force:
            argv.append("--force")
        self._run(argv)
        return head_sha


def _porcelain_paths(repo_dir: Path) -> List[str]:
    """Fichiers actuellement modifiés/non suivis dans l'arbre de travail (`git status --porcelain`)
    — utilisé pour déterminer RÉELLEMENT les `changed_files` d'un Developer réel (mission §3.2),
    jamais inventés par le modèle lui-même."""
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo_dir, capture_output=True, text=True,
    )
    paths: List[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path_part = line[3:]
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        paths.append(path_part.strip().strip('"'))
    return paths


def build_status_summary(store: AutopilotStateStore) -> str:
    """Mission §20 : résumé simple — mission actuelle, état, dernière action, branche, HEAD,
    tests, review, dernier push, prochaine action, décision éventuellement requise."""
    record = store.load()
    if record is None:
        return "Autopilot : aucun état enregistré (jamais démarré, ou état effacé)."
    lines = [
        f"Mission actuelle : {record.mission_id or '(aucune)'}",
        f"État             : {record.phase}",
        f"Branche          : {record.branch or '(inconnue)'}",
        f"HEAD             : {record.head or '(inconnu)'}",
        f"origin/master    : {record.origin_master or '(inconnu)'}",
        f"Tests            : {record.tests_status or '(non exécutés)'}",
        f"Review           : {record.review_status or '(non faite)'}",
        f"Tentatives       : {record.attempt_count}",
        f"Dernier commit   : {record.last_commit_sha or '(aucun)'}",
        f"Dernier push     : {record.last_push_sha or '(aucun)'}",
        f"Prochaine action : {record.next_action or '(aucune)'}",
    ]
    if record.phase == AutopilotState.HUMAN_GATE_REQUIRED.value and record.stop_reason:
        lines.append("")
        lines.append(record.stop_reason)
    elif record.stop_reason:
        lines.append(f"Dernier arrêt/tentative : {record.stop_reason}")
    return "\n".join(lines)


def cmd_status(_args: argparse.Namespace) -> int:
    store = AutopilotStateStore(STATE_PATH)
    print(build_status_summary(store))
    return 0


def cmd_stop(_args: argparse.Namespace) -> int:
    # V1.1 (mission §3.6) : signal d'arrêt COOPÉRATIF (un `run_until()` en cours le voit à la
    # prochaine frontière d'étape) en plus de la libération inconditionnelle du verrou, qui reste
    # le filet de sécurité final si aucun process n'est réellement en train de tourner.
    StopSignal(STOP_SIGNAL_PATH).request()
    lock = SingleInstanceLock(LOCK_PATH)
    lock.force_release()
    store = AutopilotStateStore(STATE_PATH)
    if store.load() is not None:
        store.update(stop_reason="arrêt demandé par l'utilisateur (autopilot stop)")
    print("Autopilot : arrêt demandé (signal coopératif envoyé), verrou libéré.")
    return 0


def _mission_budget(mission) -> float:
    if mission is not None and mission.max_budget_usd:
        return float(mission.max_budget_usd)
    return DEFAULT_MAX_BUDGET_USD


def _build_real_supervisor() -> AutopilotSupervisor:
    """Construit un superviseur avec les VRAIS collaborateurs — la suite de tests utilise
    toujours des doublures injectées (`tests/test_autopilot_supervisor.py`), jamais ce chemin."""
    developer_invoker = ClaudeInvoker()

    def real_developer_fn(mission, attempt, findings=None):
        sections = [
            f"Mission Autopilot : {mission.title if mission else '(inconnue)'} (tentative {attempt})."
        ]
        if mission and mission.prompt_file:
            prompt_path = AUTOPILOT_DIR / mission.prompt_file
            if prompt_path.is_file():
                sections.append(prompt_path.read_text(encoding="utf-8"))
            else:
                sections.append(f"[AVERTISSEMENT : prompt_file introuvable : {prompt_path}]")
        if mission and mission.allowed_paths:
            sections.append("Chemins/fichiers AUTORISÉS pour cette mission : " + ", ".join(mission.allowed_paths))
        if mission and mission.forbidden_paths:
            sections.append("Chemins/fichiers INTERDITS pour cette mission : " + ", ".join(mission.forbidden_paths))
        if mission and mission.scientific_contracts:
            sections.append("Contrats scientifiques concernés : " + ", ".join(mission.scientific_contracts))
        if mission and mission.completion_evidence:
            sections.append("Preuves de complétion attendues : " + ", ".join(mission.completion_evidence))
        if findings:
            sections.append(
                "Findings de la review indépendante précédente, À CORRIGER RÉELLEMENT :\n"
                + "\n".join(f"- {f}" for f in findings)
            )
        full_prompt = "\n\n".join(sections)

        result = developer_invoker.run(
            full_prompt, permission_mode="acceptEdits", max_budget_usd=_mission_budget(mission),
        )
        changed_files = _porcelain_paths(REPO_ROOT)
        return {
            "success": result.functionally_succeeded,
            "changed_files": changed_files,
            "raw_output": result.result_text or result.stdout or result.stderr,
            "session_id": result.session_id,
        }

    def _run_pytest(extra_args: List[str]):
        # `sys.executable` — jamais un chemin relatif codé en dur (".venv/Scripts/python.exe") —
        # trouvé RÉELLEMENT cassé par le canary V1.1 (mission §9) : un déploiement multi-worktree
        # (ex. `autopilot/v1-1-operational`) n'a pas forcément son PROPRE `.venv/` local, même en
        # réutilisant délibérément l'environnement virtuel du dépôt principal comme interpréteur —
        # `sys.executable` est toujours le bon interpréteur, quel que soit le répertoire de travail.
        argv = [sys.executable, "-m", "pytest", "-q", *extra_args]
        return subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True)

    def real_tester_fn(mission):
        # Mission §5 (V1.1) : tests CIBLÉS d'abord quand la mission les déclare (échec rapide,
        # jamais la suite complète en aveugle) ; régression complète imposée pour une mission à
        # risque élevé ou touchant des contrats scientifiques déclarés — sinon la commande ciblée
        # (ou, à défaut de ciblage déclaré, la suite complète par défaut sûr) suffit.
        if mission and mission.targeted_tests:
            targeted = _run_pytest(list(mission.targeted_tests))
            if targeted.returncode != 0:
                combined = (targeted.stdout + targeted.stderr)[-2000:]
                return {"success": False, "summary": combined}
            needs_full_suite = mission.risk_level == "high" or bool(mission.scientific_contracts)
            if not needs_full_suite:
                combined = (targeted.stdout + targeted.stderr)[-2000:]
                return {"success": True, "summary": combined}
        result = _run_pytest([])
        # `summary` sert aussi de repli de classification d'échec (supervisor._handle_failure) —
        # inclure stderr, pas seulement stdout, sinon une erreur réseau/subprocess sur stderr
        # serait invisible à `quota_detector.classify_failure()`.
        combined = (result.stdout + result.stderr)[-2000:]
        return {"success": result.returncode == 0, "summary": combined}

    def real_reviewer_fn(mission):
        # V1.1 (mission §3.3) : instance ClaudeInvoker FRAÎCHE — jamais `--resume` la session du
        # développeur — avec sortie structurée validée par schéma. `permission_mode="plan"` :
        # le reviewer ne doit JAMAIS pouvoir éditer de fichiers lui-même.
        diff_result = subprocess.run(
            ["git", "diff", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True,
        )
        diff_text = diff_result.stdout[:20000]
        contracts = ", ".join(mission.scientific_contracts) if mission and mission.scientific_contracts else "(aucun déclaré)"
        prompt = (
            "Tu es un réviseur de code INDÉPENDANT pour l'Autopilot AlphaForge. Tu n'as PAS accès "
            "à l'historique de justification du développeur qui a produit ce diff — évalue "
            "uniquement ce qui suit, objectivement, sévèrement si nécessaire.\n\n"
            f"Mission : {mission.title if mission else '(inconnue)'}\n"
            f"Contrats scientifiques concernés : {contracts}\n\n"
            f"Diff réel à réviser (git diff HEAD) :\n{diff_text}\n\n"
            "Réponds STRICTEMENT selon le schéma JSON fourni : verdict CLEAN ou FINDINGS, la "
            "liste des findings (sévérité BLOCKER/MAJOR/MINOR/SUGGESTION, fichier, justification, "
            "correction attendue), et un contrôle explicite scientifique/reproductibilité/"
            "sécurité/architecture."
        )
        reviewer_invoker = ClaudeInvoker()  # NOUVELLE instance à chaque appel, jamais partagée
        result = reviewer_invoker.run(
            prompt, permission_mode="plan", max_budget_usd=_mission_budget(mission),
            json_schema=REVIEW_JSON_SCHEMA,
        )
        if not result.functionally_succeeded:
            return {
                "success": False,
                "raw_output": result.stderr or result.stdout,
                "summary": "review indépendante en échec technique",
            }
        body = result.result_structured or {}
        findings = body.get("findings", []) if isinstance(body, dict) else []
        blocking = [f for f in findings if isinstance(f, dict) and f.get("severity") in ("BLOCKER", "MAJOR")]
        return {
            "success": True,
            "blocking_findings": blocking,
            "summary": f"{len(findings)} finding(s) — verdict={body.get('verdict', '?') if isinstance(body, dict) else '?'}",
            "session_id": result.session_id,
        }

    def real_diagnostic_fn(mission, failure_signature):
        # Mission §8 : "lancer un diagnostic indépendant, tenter une autre approche sûre" — UNE
        # fois par mission (garanti par `supervisor._handle_failure`), modèle léger (haiku) car il
        # s'agit d'analyser du texte, jamais d'éditer de fichiers.
        prompt = (
            "Diagnostic d'échec répété pour l'Autopilot AlphaForge. Un même échec s'est reproduit "
            f"plusieurs fois de suite pour la mission '{mission.title if mission else '(inconnue)'}' "
            f"avec la signature suivante :\n{failure_signature}\n\n"
            "Analyse la cause probable et propose UNE approche différente et sûre à tenter, en "
            "2-3 phrases maximum."
        )
        diagnostic_invoker = ClaudeInvoker()
        result = diagnostic_invoker.run(
            prompt, permission_mode="plan", max_budget_usd=min(1.0, _mission_budget(mission)),
            model=DIAGNOSTIC_MODEL,
        )
        notes = result.result_text or result.stdout or "(diagnostic indisponible)"
        return {"approach_notes": notes[:1000]}

    return AutopilotSupervisor(
        state_store=AutopilotStateStore(STATE_PATH),
        missions_path=MISSIONS_PATH,
        developer_fn=real_developer_fn,
        tester_fn=real_tester_fn,
        reviewer_fn=real_reviewer_fn,
        git_ops=RealGitOps(),
        lock=SingleInstanceLock(LOCK_PATH),
        branch="master",
        diagnostic_fn=real_diagnostic_fn,
        prompts_base_dir=AUTOPILOT_DIR,
        stop_signal=StopSignal(STOP_SIGNAL_PATH),
    )


_WAITING_STATES: Set[AutopilotState] = {
    AutopilotState.COMPLETED, AutopilotState.HUMAN_GATE_REQUIRED, AutopilotState.BLOCKED_SAFETY,
    AutopilotState.WAITING_FOR_CLAUDE, AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE,
    AutopilotState.STOPPED,
}


def _run_real_loop(max_steps: int) -> int:
    """Exécute RÉELLEMENT la boucle Autopilot (mission §3.1 : "start doit réellement lancer la
    boucle ; il ne doit jamais annoncer RUNNING si aucun superviseur ne tourne"). S'arrête à un
    état d'attente/terminal, ou après `max_steps` transitions (jamais indéfiniment silencieux —
    voir `AutopilotSupervisor.run_until()`). Libère TOUJOURS le verrou en sortie (`finally`)."""
    StopSignal(STOP_SIGNAL_PATH).clear()
    supervisor = _build_real_supervisor()
    if not supervisor.acquire_lock():
        print("Autopilot : une instance semble déjà en cours (verrou présent) — utiliser 'stop' d'abord.")
        return 1
    print("Autopilot : démarrage réel de la boucle (run_until)...")
    try:
        final_state = supervisor.run_until(_WAITING_STATES, max_steps=max_steps)
    finally:
        supervisor.release_lock()
    print(f"Autopilot : arrêté à l'état {final_state.value}.")
    print(build_status_summary(AutopilotStateStore(STATE_PATH)))
    if final_state == AutopilotState.HUMAN_GATE_REQUIRED:
        return 2
    if final_state == AutopilotState.BLOCKED_SAFETY:
        return 3
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    return _run_real_loop(max_steps=getattr(args, "max_steps", 500))


def cmd_resume(args: argparse.Namespace) -> int:
    # V1.1 (mission §3.5) : reprise RÉELLE — reconcilie l'état persisté avec le dépôt réel AVANT
    # de relancer la boucle (`_run_real_loop()` gère ensuite la reprise fine phase par phase via
    # `resume_to_phase`, mission §3.5/§3.8 pour l'idempotence Git).
    store = AutopilotStateStore(STATE_PATH)
    record = store.load()
    if record is None:
        print("Autopilot : aucun état à reprendre — utiliser 'start'.")
        return 1
    real_head = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True,
        )
        if result.returncode == 0:
            real_head = result.stdout.strip()
    except OSError:
        real_head = None
    if record.head and real_head and record.head != real_head:
        print(
            f"Autopilot : AVERTISSEMENT — HEAD a changé depuis le dernier enregistrement "
            f"({record.head} -> {real_head}). Reprise quand même (idempotence Git, mission §3.8), "
            "mais ceci mérite un examen si inattendu."
        )
    print(f"Autopilot : reprise depuis la phase {record.phase}.")
    return _run_real_loop(max_steps=getattr(args, "max_steps", 500))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="autopilot", description="Superviseur Autopilot AlphaForge V2")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "resume"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--max-steps", type=int, default=500, dest="max_steps")
    subparsers.add_parser("status")
    subparsers.add_parser("stop")

    args = parser.parse_args(argv)
    handlers = {
        "start": cmd_start, "status": cmd_status, "stop": cmd_stop, "resume": cmd_resume,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
