"""
scripts/autopilot/mission_queue.py — File de missions Autopilot (Bootstrap V1, 2026-09-17).

Persistée dans `.autopilot/missions.json` (mutable — `save_atomic_overwrite()`). Sélection de la
prochaine mission respectant les dépendances déclarées (mission §4 : "déterminer la prochaine
mission autorisée") — jamais une mission dont un prérequis n'est pas `DONE`, mirroring le principe
déjà appliqué aux gates scientifiques du projet (`GATE V` bloque `D`, etc.) au niveau de
l'Autopilot lui-même."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Tuple, Union

from atomic_json_store import load_json_tolerant, save_atomic_overwrite


@dataclass(frozen=True)
class Mission:
    id: str
    title: str
    status: str  # "PLANNED" | "IN_PROGRESS" | "DONE" | "BLOCKED"
    prompt_file: str
    depends_on: Tuple[str, ...] = ()


def select_next_mission(missions: List[Mission]) -> Optional[Mission]:
    """Retourne la première mission `PLANNED` dont toutes les dépendances sont `DONE`, ou `None`.
    Ordre de la liste = ordre de priorité (première correspondance retenue)."""
    done_ids = {m.id for m in missions if m.status == "DONE"}
    for mission in missions:
        if mission.status != "PLANNED":
            continue
        if all(dep in done_ids for dep in mission.depends_on):
            return mission
    return None


def mark_mission_status(missions: List[Mission], mission_id: str, status: str) -> List[Mission]:
    """Retourne une NOUVELLE liste avec la mission `mission_id` mise à jour — jamais de mutation
    de la liste/des objets reçus (immuabilité, cohérent avec le reste du dépôt)."""
    return [
        replace(m, status=status) if m.id == mission_id else m
        for m in missions
    ]


def load_missions(path: Union[str, Path]) -> List[Mission]:
    """Tolérant : fichier absent/illisible -> liste vide, jamais une exception."""
    data = load_json_tolerant(path)
    if data is None or "missions" not in data:
        return []
    try:
        return [
            Mission(
                id=m["id"], title=m["title"], status=m["status"],
                prompt_file=m["prompt_file"], depends_on=tuple(m.get("depends_on", ())),
            )
            for m in data["missions"]
        ]
    except (KeyError, TypeError):
        return []


def save_missions(path: Union[str, Path], missions: List[Mission]) -> Path:
    payload = {
        "missions": [
            {
                "id": m.id, "title": m.title, "status": m.status,
                "prompt_file": m.prompt_file, "depends_on": list(m.depends_on),
            }
            for m in missions
        ]
    }
    return save_atomic_overwrite(path, payload, "autopilot_missions")
