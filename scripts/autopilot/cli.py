"""
scripts/autopilot/cli.py — Points d'entrée CLI Autopilot (Bootstrap V1, 2026-09-17).

Appelé par les scripts PowerShell (`start.ps1`/`status.ps1`/`stop.ps1`/`resume.ps1`) via
`python -m scripts.autopilot.cli <commande>`. Construit les collaborateurs RÉELS (`RealGitOps`,
`ClaudeInvoker`) — jamais les doublures utilisées par la suite de tests.

**`start`/`resume` ne sont volontairement PAS exercés en conditions réelles par cette mission de
Bootstrap** (aucune boucle autonome réellement lancée, aucun `claude -p` récursif réellement
invoqué) — seule la logique (machine à états, garde Git, verrou, formatage de statut) est
testée via des doublures (`tests/test_autopilot_*.py`). Démarrer réellement l'Autopilot pour de
vrai reste un choix explicite de l'utilisateur, documenté dans `.autopilot/README.md`."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from scripts.autopilot import git_safety
from scripts.autopilot.claude_invoker import ClaudeInvoker
from scripts.autopilot.mission_queue import load_missions
from scripts.autopilot.state_machine import AutopilotState, AutopilotStateStore
from scripts.autopilot.supervisor import (
    AutopilotSupervisor, ForbiddenGitCommandError, SingleInstanceLock,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOPILOT_DIR = REPO_ROOT / ".autopilot"
STATE_PATH = AUTOPILOT_DIR / "state" / "current_state.json"
LOCK_PATH = AUTOPILOT_DIR / "state" / "autopilot.lock"
MISSIONS_PATH = AUTOPILOT_DIR / "missions.json"


class RealGitOps:
    """Implémentation réelle des opérations Git — chaque méthode passe par `git_safety` AVANT
    tout `subprocess.run()` réel, jamais après (voir `tests/test_autopilot_cli.py`, qui vérifie
    qu'aucun `subprocess.run()` n'est même tenté pour une commande interdite)."""

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

    def commit(self, message: str) -> None:
        # `check_scope_files()` en `add()` ne valide que les chemins PASSÉS à cet appel — pas
        # l'index Git réel au moment du commit, qui peut déjà porter un contenu étranger/protégé
        # (reprise après crash, `git add` humain laissé en cours...). Revalidation juste avant le
        # commit contre l'index RÉEL (trouvé par la revue safety/architecture du Bootstrap).
        staged = [line for line in self._run(["git", "diff", "--cached", "--name-only"]).splitlines() if line]
        scope_reason = git_safety.check_scope_files(staged)
        if scope_reason:
            raise ForbiddenGitCommandError(scope_reason)
        self._run(["git", "commit", "-m", message])

    def push(self, force: bool = False) -> None:
        argv = ["git", "push", "origin", "master"]
        if force:
            argv.append("--force")
        self._run(argv)


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
    lock = SingleInstanceLock(LOCK_PATH)
    lock.force_release()
    store = AutopilotStateStore(STATE_PATH)
    if store.load() is not None:
        store.update(stop_reason="arrêt demandé par l'utilisateur (autopilot stop)")
    print("Autopilot : arrêt demandé, verrou libéré.")
    return 0


# Plafond de coût par défaut pour un appel `claude -p` réel déclenché par l'Autopilot — défense
# en profondeur contre une spirale récursive (mission §9 "jamais de contournement pour aller plus
# vite") tant que `real_developer_fn` n'est câblé nulle part au vrai `run_until()` (Bootstrap V1) ;
# trouvé absent par la revue safety/architecture du Bootstrap malgré le support déjà présent dans
# `claude_invoker.build_claude_argv()`.
DEFAULT_MAX_BUDGET_USD = 5.0


def _build_real_supervisor() -> AutopilotSupervisor:
    """Construit un superviseur avec les VRAIS collaborateurs — non exercé par la suite de tests
    (qui utilise toujours des doublures injectées), non invoqué par cette mission de Bootstrap."""
    invoker = ClaudeInvoker()

    def real_developer_fn(mission, attempt):
        result = invoker.run(
            f"Mission Autopilot : {mission.title if mission else '(inconnue)'}, tentative {attempt}.",
            permission_mode="acceptEdits",
            max_budget_usd=DEFAULT_MAX_BUDGET_USD,
        )
        return {
            "success": result.exit_code == 0,
            "changed_files": [],  # à déterminer par git status réel dans une future itération
            "raw_output": result.stdout if result.exit_code == 0 else result.stderr,
        }

    def real_tester_fn():
        result = subprocess.run(
            [".venv/Scripts/python.exe", "-m", "pytest", "-q"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        # `summary` sert aussi de repli de classification d'échec (supervisor._handle_failure) —
        # inclure stderr, pas seulement stdout, sinon une erreur réseau/subprocess sur stderr
        # serait invisible à `quota_detector.classify_failure()`.
        combined = (result.stdout + result.stderr)[-500:]
        return {"success": result.returncode == 0, "summary": combined}

    def real_reviewer_fn(mission):
        # Bootstrap V1 : pas encore de review Claude indépendante réellement câblée ici (mission
        # §11 exige un CONTEXTE séparé du developer_fn — hors scope de ce commit, voir
        # `.autopilot/README.md` "Limites connues"). Retourne toujours "propre" pour ne jamais
        # bloquer silencieusement une future intégration réelle sans le documenter explicitement.
        return {"blocking_findings": [], "summary": "review réelle non encore câblée (Bootstrap V1)"}

    return AutopilotSupervisor(
        state_store=AutopilotStateStore(STATE_PATH),
        missions_path=MISSIONS_PATH,
        developer_fn=real_developer_fn,
        tester_fn=real_tester_fn,
        reviewer_fn=real_reviewer_fn,
        git_ops=RealGitOps(),
        lock=SingleInstanceLock(LOCK_PATH),
        branch="master",
    )


def cmd_start(_args: argparse.Namespace) -> int:
    supervisor = _build_real_supervisor()
    if not supervisor.acquire_lock():
        print("Autopilot : une instance semble déjà en cours (verrou présent) — utiliser 'stop' d'abord.")
        return 1
    print("Autopilot : démarré. Utiliser 'status' pour suivre la progression.")
    print("(Bootstrap V1 : boucle non exécutée ici — voir .autopilot/README.md.)")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    return cmd_start(args)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="autopilot", description="Superviseur Autopilot AlphaForge V2")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start")
    subparsers.add_parser("status")
    subparsers.add_parser("stop")
    subparsers.add_parser("resume")

    args = parser.parse_args(argv)
    handlers = {
        "start": cmd_start, "status": cmd_status, "stop": cmd_stop, "resume": cmd_resume,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
