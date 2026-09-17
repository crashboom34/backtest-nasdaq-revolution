"""
scripts/autopilot/mission_queue.py — File de missions Autopilot (V1.1, 2026-09-17).

Persistée dans `.autopilot/missions.json` (mutable — `save_atomic_overwrite()`). Sélection de la
prochaine mission respectant les dépendances déclarées (mission §4 : "déterminer la prochaine
mission autorisée") — jamais une mission dont un prérequis n'est pas `DONE`, mirroring le principe
déjà appliqué aux gates scientifiques du projet (`GATE V` bloque `D`, etc.) au niveau de
l'Autopilot lui-même.

**V1.1** : schéma enrichi (scope autorisé/interdit, tests ciblés/régression, niveau de risque,
budget, contrats scientifiques concernés, conditions de Human Gate, preuves de complétion) et
validation STRICTE au chargement — mission Autopilot V1.1 §4 : "Un fichier absent, un statut
inconnu ou un prompt inaccessible ne doit jamais produire silencieusement une file vide ou un faux
COMPLETED. Une erreur de configuration doit produire un état explicite et sûr." `load_missions()`
lève désormais `MissionQueueError` dans ces cas (changement de comportement délibéré par rapport au
Bootstrap V1, qui retournait `[]` pour un fichier absent) — les appelants (`supervisor.py`) doivent
router cette exception vers `BLOCKED_SAFETY`, jamais la laisser se propager ni l'avaler."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Tuple, Union

from atomic_json_store import load_json_tolerant, save_atomic_overwrite

ALLOWED_STATUSES = frozenset({"PLANNED", "IN_PROGRESS", "DONE", "BLOCKED"})
ALLOWED_RISK_LEVELS = frozenset({"low", "medium", "high"})
_REQUIRED_FIELDS = ("id", "title", "status", "prompt_file")


class MissionQueueError(ValueError):
    """Levée quand `.autopilot/missions.json` est absent, illisible, mal formé, ou contient une
    entrée invalide (champ requis manquant, statut inconnu, `risk_level` inconnu, `prompt_file`
    introuvable sous `prompts_base_dir`). Jamais avalée en un résultat vide — mission §4."""


@dataclass(frozen=True)
class Mission:
    id: str
    title: str
    status: str  # "PLANNED" | "IN_PROGRESS" | "DONE" | "BLOCKED"
    prompt_file: str
    depends_on: Tuple[str, ...] = ()
    # -- V1.1 : scope, tests, risque, preuves (mission Autopilot V1.1 §4) --
    allowed_paths: Tuple[str, ...] = ()
    forbidden_paths: Tuple[str, ...] = ()
    targeted_tests: Tuple[str, ...] = ()
    regression_tests: Tuple[str, ...] = ()
    risk_level: str = "low"
    max_attempts: int = 3
    max_budget_usd: Optional[float] = None
    requires_clean_worktree: bool = True
    scientific_contracts: Tuple[str, ...] = ()
    human_gate_conditions: Tuple[str, ...] = ()
    completion_evidence: Tuple[str, ...] = ()


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


def _mission_from_raw(raw: dict, prompts_base_dir: Optional[Union[str, Path]]) -> Mission:
    missing = [k for k in _REQUIRED_FIELDS if k not in raw]
    if missing:
        raise MissionQueueError(
            f"mission invalide (id={raw.get('id', '?')!r}) : champ(s) requis manquant(s) : {missing}."
        )
    if raw["status"] not in ALLOWED_STATUSES:
        raise MissionQueueError(
            f"mission {raw['id']!r} : statut inconnu {raw['status']!r} "
            f"(attendu parmi {sorted(ALLOWED_STATUSES)})."
        )
    risk_level = raw.get("risk_level", "low")
    if risk_level not in ALLOWED_RISK_LEVELS:
        raise MissionQueueError(
            f"mission {raw['id']!r} : risk_level inconnu {risk_level!r} "
            f"(attendu parmi {sorted(ALLOWED_RISK_LEVELS)})."
        )
    if prompts_base_dir is not None:
        prompt_path = Path(prompts_base_dir) / raw["prompt_file"]
        if not prompt_path.is_file():
            raise MissionQueueError(f"mission {raw['id']!r} : prompt_file introuvable : {prompt_path}.")
    return Mission(
        id=raw["id"], title=raw["title"], status=raw["status"], prompt_file=raw["prompt_file"],
        depends_on=tuple(raw.get("depends_on", ())),
        allowed_paths=tuple(raw.get("allowed_paths", ())),
        forbidden_paths=tuple(raw.get("forbidden_paths", ())),
        targeted_tests=tuple(raw.get("targeted_tests", ())),
        regression_tests=tuple(raw.get("regression_tests", ())),
        risk_level=risk_level,
        max_attempts=raw.get("max_attempts", 3),
        max_budget_usd=raw.get("max_budget_usd"),
        requires_clean_worktree=raw.get("requires_clean_worktree", True),
        scientific_contracts=tuple(raw.get("scientific_contracts", ())),
        human_gate_conditions=tuple(raw.get("human_gate_conditions", ())),
        completion_evidence=tuple(raw.get("completion_evidence", ())),
    )


def load_missions(
    path: Union[str, Path], prompts_base_dir: Optional[Union[str, Path]] = None,
) -> List[Mission]:
    """Charge et VALIDE la file de missions. Lève `MissionQueueError` — jamais un résultat vide
    silencieux — si : le fichier est absent, le JSON est illisible, la clé `missions` est absente/
    invalide, ou une entrée est invalide (champ requis manquant, statut/risk_level inconnu,
    `prompt_file` introuvable quand `prompts_base_dir` est fourni). `prompts_base_dir` est
    optionnel : omis, la vérification d'existence du fichier de prompt est sautée (utile pour des
    tests qui ne portent pas sur cet aspect) ; fourni (déploiement réel), elle est appliquée."""
    if not Path(path).exists():
        raise MissionQueueError(f"fichier de missions introuvable : {path} (mission §4).")
    data = load_json_tolerant(path)
    if data is None:
        raise MissionQueueError(f"fichier de missions illisible ou JSON corrompu : {path}.")
    if "missions" not in data or not isinstance(data["missions"], list):
        raise MissionQueueError(f"fichier de missions mal formé (clé 'missions' manquante/invalide) : {path}.")
    return [_mission_from_raw(raw, prompts_base_dir) for raw in data["missions"]]


def save_missions(path: Union[str, Path], missions: List[Mission]) -> Path:
    payload = {
        "missions": [
            {
                "id": m.id, "title": m.title, "status": m.status, "prompt_file": m.prompt_file,
                "depends_on": list(m.depends_on),
                "allowed_paths": list(m.allowed_paths),
                "forbidden_paths": list(m.forbidden_paths),
                "targeted_tests": list(m.targeted_tests),
                "regression_tests": list(m.regression_tests),
                "risk_level": m.risk_level,
                "max_attempts": m.max_attempts,
                "max_budget_usd": m.max_budget_usd,
                "requires_clean_worktree": m.requires_clean_worktree,
                "scientific_contracts": list(m.scientific_contracts),
                "human_gate_conditions": list(m.human_gate_conditions),
                "completion_evidence": list(m.completion_evidence),
            }
            for m in missions
        ]
    }
    return save_atomic_overwrite(path, payload, "autopilot_missions")
