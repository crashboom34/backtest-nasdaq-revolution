"""
scripts/autopilot/git_safety.py — Politique de sécurité Git Autopilot (Bootstrap V1, 2026-09-17).

Fonctions PURES (aucune commande Git n'est exécutée ici) — vérifiées AVANT toute commande Git
réellement lancée par `supervisor.py`. Mission §9 (interdictions absolues) : liste fermée de
motifs interdits (force push, reset --hard, clean destructeur, --no-verify, suppression de
branche distante, ajout global aveugle) — tout le reste est implicitement autorisé (liste noire,
cohérent avec l'autonomie large de la mission, à condition que ces interdictions restent
absolues). Complété par des gardes indépendants : fichiers protégés (§9), espace disque (§9/§18),
détection de secrets/gros fichiers (§8/§10), et une politique d'escalade anti-boucle (§7)."""

from __future__ import annotations

import re
import shlex
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

PROTECTED_PATHS = frozenset({
    "app_corrupted_backup.py",
    "nasdaq_3m.csv",
})
"""Fichiers ne devant JAMAIS apparaître dans le scope d'un commit Autopilot (mission §9/§16)."""


def check_git_command(argv: Sequence[str]) -> Optional[str]:
    """Inspecte les tokens d'une commande Git PROPOSÉE et retourne une raison de refus, ou `None`
    si autorisée. N'exécute jamais rien elle-même."""
    if not argv or argv[0] != "git":
        return None
    tokens = list(argv[1:])
    subcommand = tokens[0] if tokens else ""

    if "--no-verify" in tokens:
        return "commande refusée : --no-verify contourne les hooks (interdiction absolue, mission §9)."

    if subcommand == "push":
        if "--force" in tokens or "-f" in tokens or "--force-with-lease" in tokens:
            return "commande refusée : force push interdit (mission §9)."
        if "--delete" in tokens or "-d" in tokens:
            return (
                "commande refusée : suppression d'une branche distante interdite sans validation "
                "explicite (mission §9)."
            )

    if subcommand == "reset" and "--hard" in tokens:
        return "commande refusée : reset --hard peut détruire du travail non sauvegardé (mission §9)."

    if subcommand == "clean":
        combined_short = "".join(
            t[1:] for t in tokens if t.startswith("-") and not t.startswith("--")
        )
        if "--force" in tokens or "f" in combined_short:
            return (
                "commande refusée : git clean avec -f/--force supprime des fichiers non suivis, "
                "toute combinaison (-fd, -xdf...) reste interdite (mission §9)."
            )

    if subcommand == "branch" and ("-D" in tokens or ("--delete" in tokens and "--force" in tokens)):
        return "commande refusée : suppression forcée de branche interdite (mission §9)."

    if subcommand == "add" and any(t in ("-A", "--all", ".") for t in tokens):
        return (
            "commande refusée : ajout global aveugle interdit — construire la liste explicite "
            "des pathspecs (mission §3/§8)."
        )

    return None


def check_git_command_string(command: str) -> Optional[str]:
    """Variante de `check_git_command()` acceptant une commande shell BRUTE (ex. celle qu'un hook
    Claude Code `PreToolUse` reçoit pour l'outil Bash) plutôt qu'un argv déjà découpé. Découpe
    grossièrement sur les séparateurs de commandes shell les plus courants (`&&`, `;`, `|`) — une
    commande composée (ex. `cd repo && git push --force origin master`) ne doit jamais laisser
    passer une sous-commande interdite cachée après un premier segment inoffensif. Retourne `None`
    dès qu'aucun segment ne contient `git` (évite un `shlex.split` inutile sur une commande sans
    rapport)."""
    if not command or "git" not in command:
        return None
    for segment in re.split(r"&&|;|\|", command):
        try:
            tokens = shlex.split(segment, posix=False)
        except ValueError:
            continue
        if "git" not in tokens:
            continue
        idx = tokens.index("git")
        if reason := check_git_command(tokens[idx:]):
            return reason
    return None


def check_scope_files(files: Iterable[str]) -> Optional[str]:
    """Vérifie qu'aucun fichier protégé (`PROTECTED_PATHS`) n'apparaît dans un scope de commit
    proposé."""
    normalized = [f.replace("\\", "/") for f in files]
    hits = [f for f in normalized if Path(f).name in PROTECTED_PATHS or f in PROTECTED_PATHS]
    if hits:
        return f"fichiers protégés présents dans le scope : {', '.join(hits)} (mission §9)."
    return None


def check_disk_space(min_gb: float = 2.0, path: str = ".") -> Optional[str]:
    """Mission §9 : si l'espace libre est inférieur à 2 Go, l'appelant doit passer en
    `BLOCKED_SAFETY` avant toute écriture importante."""
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024 ** 3)
    if free_gb < min_gb:
        return (
            f"espace disque insuffisant : {free_gb:.2f} Go libres < seuil {min_gb} Go "
            "(mission §9 — BLOCKED_SAFETY)."
        )
    return None


_SECRET_PATTERNS = (
    ("AWS Access Key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "Affectation de type clé API/secret/token/mot de passe",
        re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{20,}[\"']?"),
    ),
    ("En-tête de clé privée PEM", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)
"""Heuristiques volontairement simples (mission §8/§10) — un vrai secret scanner dédié resterait
hors scope V1 ; ce garde attrape les formes les plus communes avant tout commit Autopilot."""


def check_no_secrets(diff_text: str) -> List[str]:
    """Retourne la liste des motifs de secret détectés (vide si aucun) dans un texte de diff."""
    return [label for label, pattern in _SECRET_PATTERNS if pattern.search(diff_text)]


def check_no_large_files(file_sizes: Dict[str, int], max_mb: float = 50) -> List[str]:
    """`file_sizes` : nom de fichier -> taille en octets. Retourne la liste des fichiers dépassant
    `max_mb` (mission §9 : jamais de gros dataset/résultat ajouté)."""
    limit_bytes = max_mb * 1024 * 1024
    return [
        f"{name} ({size / (1024 * 1024):.1f} Mo > {max_mb} Mo)"
        for name, size in file_sizes.items()
        if size > limit_bytes
    ]


def should_escalate(failure_signatures: Sequence[str], current_signature: str, limit: int = 3) -> bool:
    """Mission §7 : "Si plusieurs tentatives échouent pour exactement la même cause, effectuer un
    diagnostic de niveau supérieur et changer d'approche" — jamais une boucle infinie identique.
    `failure_signatures` : historique des signatures d'échec déjà observées pour la mission
    courante (avant la tentative actuelle) ; `current_signature` : signature de l'échec le plus
    récent. Compare une chaîne EXACTE, jamais une similarité floue — une escalade sur un
    diagnostic incorrect serait pire qu'une tentative de plus."""
    return sum(s == current_signature for s in failure_signatures) >= limit
