"""
scripts/autopilot/hooks/pre_bash_safety_check.py — Hook Claude Code `PreToolUse` (Bootstrap V1,
2026-09-17).

Enregistré dans `.claude/settings.json` (matcher `Bash`). Reçoit sur stdin le JSON standard d'un
hook `PreToolUse` (`{"tool_name": "Bash", "tool_input": {"command": "..."}, ...}`), vérifie la
commande via `scripts.autopilot.git_safety.check_git_command_string()` et bloque (code de sortie
2, message sur stderr — contrat `PreToolUse` : un exit code 2 bloque l'appel d'outil) si un motif
interdit est détecté. **Fail-open sur l'inconnu** : toute entrée illisible ou commande non
identifiée comme interdite est laissée passer — ce hook est une DÉFENSE SUPPLÉMENTAIRE, jamais le
seul mécanisme (la politique/tests de `git_safety.py` restent la source de vérité testée)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.autopilot.git_safety import check_git_command_string


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # entrée illisible : ne jamais bloquer sur une erreur de parsing du hook lui-même
    command = (payload.get("tool_input") or {}).get("command", "") if isinstance(payload, dict) else ""
    reason = check_git_command_string(command)
    if reason:
        print(f"BLOQUÉ par le hook de sécurité Autopilot (PreToolUse) : {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
