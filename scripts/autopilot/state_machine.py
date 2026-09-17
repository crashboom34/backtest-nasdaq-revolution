"""
scripts/autopilot/state_machine.py — Machine à états Autopilot V1 (Bootstrap, 2026-09-17).

18 états explicites (mission Bootstrap Autopilot §6), table de transitions explicite (toute
transition hors de cette table est un bug, jamais silencieusement acceptée), persistance atomique
de l'état courant (`AutopilotStateStore`, réécrit à chaque transition via
`atomic_json_store.save_atomic_overwrite()` — jamais dupliqué) et d'un historique borné des
dernières transitions (audit — fichier séparé, jamais mélangé à l'état courant).

**État runtime, jamais un artefact scientifique** : contrairement à `ValidationRun`/
`DatasetSplitPlan` (immuables, `save_atomic()`), l'état Autopilot est réécrit en continu — d'où
`save_atomic_overwrite()` plutôt que `save_atomic()`. Aucun champ de `AutopilotStateRecord` ne
porte jamais de secret (`test_state_record_never_carries_a_field_named_secret_or_token`, vérifié
structurellement).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple, Union

from atomic_json_store import load_json_tolerant, save_atomic_overwrite


class AutopilotState(str, Enum):
    BOOTSTRAPPING = "BOOTSTRAPPING"
    READY = "READY"
    PLANNING = "PLANNING"
    DEVELOPING = "DEVELOPING"
    TESTING = "TESTING"
    REVIEWING = "REVIEWING"
    CORRECTING = "CORRECTING"
    PRE_COMMIT_CHECK = "PRE_COMMIT_CHECK"
    COMMITTING = "COMMITTING"
    PUSHING = "PUSHING"
    CHECKPOINTED = "CHECKPOINTED"
    NEXT_MISSION = "NEXT_MISSION"
    WAITING_FOR_CLAUDE = "WAITING_FOR_CLAUDE"
    WAITING_FOR_EXTERNAL_RESOURCE = "WAITING_FOR_EXTERNAL_RESOURCE"
    HUMAN_GATE_REQUIRED = "HUMAN_GATE_REQUIRED"
    BLOCKED_SAFETY = "BLOCKED_SAFETY"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"


ALL_STATES: Tuple[AutopilotState, ...] = tuple(AutopilotState)

# Graphe de transitions explicite. Chaque clé DOIT apparaître (test dédié) ; toute transition
# absente de la table est refusée (IllegalTransitionError), jamais acceptée par défaut.
ALLOWED_TRANSITIONS: dict = {
    AutopilotState.BOOTSTRAPPING: (AutopilotState.READY, AutopilotState.BLOCKED_SAFETY),
    AutopilotState.READY: (
        AutopilotState.PLANNING, AutopilotState.STOPPED, AutopilotState.COMPLETED,
        AutopilotState.BLOCKED_SAFETY,
    ),
    AutopilotState.PLANNING: (
        AutopilotState.DEVELOPING, AutopilotState.HUMAN_GATE_REQUIRED,
        AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE, AutopilotState.BLOCKED_SAFETY,
        AutopilotState.STOPPED, AutopilotState.COMPLETED,
    ),
    AutopilotState.DEVELOPING: (
        AutopilotState.TESTING, AutopilotState.WAITING_FOR_CLAUDE,
        AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE, AutopilotState.HUMAN_GATE_REQUIRED,
        AutopilotState.BLOCKED_SAFETY,
    ),
    AutopilotState.TESTING: (
        AutopilotState.REVIEWING, AutopilotState.CORRECTING, AutopilotState.WAITING_FOR_CLAUDE,
        AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE, AutopilotState.HUMAN_GATE_REQUIRED,
        AutopilotState.BLOCKED_SAFETY,
    ),
    AutopilotState.REVIEWING: (
        AutopilotState.PRE_COMMIT_CHECK, AutopilotState.CORRECTING, AutopilotState.WAITING_FOR_CLAUDE,
        AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE, AutopilotState.HUMAN_GATE_REQUIRED,
        AutopilotState.BLOCKED_SAFETY,
    ),
    # V1.1 : CORRECTING invoque désormais réellement le Developer avec les findings (mission
    # Autopilot V1.1 §3.4) — peut donc échouer exactement comme DEVELOPING (WAITING_FOR_CLAUDE/
    # WAITING_FOR_EXTERNAL_RESOURCE/HUMAN_GATE_REQUIRED), jamais seulement retomber sur TESTING.
    AutopilotState.CORRECTING: (
        AutopilotState.TESTING, AutopilotState.WAITING_FOR_CLAUDE,
        AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE, AutopilotState.HUMAN_GATE_REQUIRED,
        AutopilotState.BLOCKED_SAFETY,
    ),
    AutopilotState.PRE_COMMIT_CHECK: (
        AutopilotState.COMMITTING, AutopilotState.CORRECTING, AutopilotState.BLOCKED_SAFETY,
    ),
    AutopilotState.COMMITTING: (AutopilotState.PUSHING, AutopilotState.BLOCKED_SAFETY),
    AutopilotState.PUSHING: (
        AutopilotState.CHECKPOINTED, AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE,
        AutopilotState.BLOCKED_SAFETY,
    ),
    AutopilotState.CHECKPOINTED: (AutopilotState.NEXT_MISSION,),
    AutopilotState.NEXT_MISSION: (
        AutopilotState.PLANNING, AutopilotState.COMPLETED, AutopilotState.STOPPED,
        AutopilotState.BLOCKED_SAFETY,
    ),
    # V1.1 : "resume" doit réellement reprendre la phase interrompue (`resume_to_phase`), pas
    # seulement PLANNING — voir `_resume_to_recorded_phase()` dans supervisor.py (mission §3.5).
    # PLANNING reste un repli LÉGAL ici (symétrique à WAITING_FOR_EXTERNAL_RESOURCE) : un fichier
    # d'état pré-V1.1 (champ `resume_to_phase` absent, `None` par défaut) ou toute valeur
    # invalide/plus autorisée doit pouvoir se rétablir en repartant d'une sélection de mission,
    # jamais planter — trouvé réellement reproductible par la revue safety/architecture V1.1.
    AutopilotState.WAITING_FOR_CLAUDE: (
        AutopilotState.DEVELOPING, AutopilotState.TESTING, AutopilotState.REVIEWING,
        AutopilotState.CORRECTING, AutopilotState.PLANNING, AutopilotState.STOPPED,
    ),
    AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE: (
        AutopilotState.DEVELOPING, AutopilotState.TESTING, AutopilotState.REVIEWING,
        AutopilotState.CORRECTING, AutopilotState.PLANNING, AutopilotState.PUSHING,
        AutopilotState.STOPPED,
    ),
    AutopilotState.HUMAN_GATE_REQUIRED: (AutopilotState.STOPPED, AutopilotState.PLANNING),
    AutopilotState.BLOCKED_SAFETY: (AutopilotState.STOPPED,),
    AutopilotState.COMPLETED: (),
    AutopilotState.STOPPED: (AutopilotState.READY,),
}


class IllegalTransitionError(ValueError):
    """Levée quand une transition demandée n'apparaît pas dans `ALLOWED_TRANSITIONS` pour l'état
    courant — jamais silencieusement acceptée ni ignorée."""


@dataclass(frozen=True)
class AutopilotStateRecord:
    """Un instantané d'état — mission Bootstrap §6, liste de champs minimale. Jamais de secret
    (vérifié structurellement par un test dédié sur les noms de champs)."""

    phase: str
    mission_id: Optional[str] = None
    timestamp_utc: str = ""
    branch: Optional[str] = None
    head: Optional[str] = None
    origin_master: Optional[str] = None
    scope_files: Tuple[str, ...] = ()
    next_action: Optional[str] = None
    attempt_count: int = 0
    tests_status: Optional[str] = None
    review_status: Optional[str] = None
    stop_reason: Optional[str] = None
    claude_session_id: Optional[str] = None
    artifacts: Tuple[str, ...] = ()
    # -- V1.1 : reprise réelle, idempotence Git, correction pilotée par les findings (mission
    # Autopilot V1.1 §3.2/§3.3/§3.4/§3.5/§3.8) --
    developer_session_id: Optional[str] = None
    reviewer_session_id: Optional[str] = None
    resume_to_phase: Optional[str] = None
    pending_findings: Tuple[str, ...] = ()
    last_commit_sha: Optional[str] = None
    last_push_sha: Optional[str] = None
    diagnostic_attempted: bool = False


def build_state_record(
    phase: AutopilotState,
    mission_id: Optional[str],
    branch: Optional[str],
    head: Optional[str] = None,
    origin_master: Optional[str] = None,
    scope_files: Tuple[str, ...] = (),
    next_action: Optional[str] = None,
    attempt_count: int = 0,
    tests_status: Optional[str] = None,
    review_status: Optional[str] = None,
    stop_reason: Optional[str] = None,
    claude_session_id: Optional[str] = None,
    artifacts: Tuple[str, ...] = (),
    timestamp_utc: Optional[str] = None,
    developer_session_id: Optional[str] = None,
    reviewer_session_id: Optional[str] = None,
    resume_to_phase: Optional[str] = None,
    pending_findings: Tuple[str, ...] = (),
    last_commit_sha: Optional[str] = None,
    last_push_sha: Optional[str] = None,
    diagnostic_attempted: bool = False,
) -> AutopilotStateRecord:
    """Construit un `AutopilotStateRecord`. `timestamp_utc` auto-rempli (UTC, offset explicite)
    si non fourni — même discipline que `research_run.py`/`validation_run.py`."""
    return AutopilotStateRecord(
        phase=phase.value if isinstance(phase, AutopilotState) else phase,
        mission_id=mission_id,
        timestamp_utc=timestamp_utc or datetime.now(timezone.utc).isoformat(),
        branch=branch,
        head=head,
        origin_master=origin_master,
        scope_files=tuple(scope_files),
        next_action=next_action,
        attempt_count=attempt_count,
        tests_status=tests_status,
        review_status=review_status,
        stop_reason=stop_reason,
        claude_session_id=claude_session_id,
        developer_session_id=developer_session_id,
        reviewer_session_id=reviewer_session_id,
        resume_to_phase=resume_to_phase,
        pending_findings=tuple(pending_findings),
        last_commit_sha=last_commit_sha,
        last_push_sha=last_push_sha,
        diagnostic_attempted=diagnostic_attempted,
        artifacts=tuple(artifacts),
    )


def _record_to_dict(record: AutopilotStateRecord) -> dict:
    return {f.name: getattr(record, f.name) for f in fields(record)}


class AutopilotStateStore:
    """Persistance atomique de l'état courant + historique borné des dernières transitions.

    `state_path` porte l'état COURANT (réécrit à chaque transition, `save_atomic_overwrite()`).
    L'historique vit dans un fichier séparé (`<state_path>.history.json`, liste bornée à
    `history_limit` entrées, les plus récentes) — jamais mélangé à l'état courant, pour qu'un
    lecteur de l'état courant n'ait jamais à parser une liste croissante."""

    def __init__(self, state_path: Union[str, Path], history_limit: int = 200):
        self.state_path = Path(state_path)
        self.history_path = self.state_path.with_name(self.state_path.name + ".history.json")
        self.history_limit = history_limit

    def load(self) -> Optional[AutopilotStateRecord]:
        data = load_json_tolerant(self.state_path)
        if data is None:
            return None
        try:
            return AutopilotStateRecord(**data)
        except TypeError:
            return None

    def load_history(self) -> list:
        data = load_json_tolerant(self.history_path)
        if data is None or "entries" not in data:
            return []
        return data["entries"]

    def save(self, record: AutopilotStateRecord) -> None:
        save_atomic_overwrite(self.state_path, _record_to_dict(record), "autopilot_state")
        self._append_history(record)

    def _append_history(self, record: AutopilotStateRecord) -> None:
        entries = self.load_history()
        entries.append(_record_to_dict(record))
        if len(entries) > self.history_limit:
            entries = entries[-self.history_limit:]
        save_atomic_overwrite(self.history_path, {"entries": entries}, "autopilot_state_history")

    def update(self, **updates) -> AutopilotStateRecord:
        """Met à jour des champs de l'enregistrement courant SANS changer de phase — jamais une
        transition, donc jamais validée contre `ALLOWED_TRANSITIONS` (ex. incrémenter
        `attempt_count` lors d'une nouvelle tentative restant dans le même état, mission §7 :
        "diagnostic -> correction -> retest -> review" reste dans la MÊME phase tant que le
        superviseur ne décide pas explicitement d'en changer)."""
        current = self.load()
        if current is None:
            raise ValueError("Aucun état courant à mettre à jour — appeler save() d'abord.")
        base = _record_to_dict(current)
        base.update(updates)
        base["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        new_record = AutopilotStateRecord(**base)
        self.save(new_record)
        return new_record

    def transition_to(self, target: AutopilotState, **updates) -> AutopilotStateRecord:
        """Valide la transition `état courant -> target` contre `ALLOWED_TRANSITIONS`, lève
        `IllegalTransitionError` sinon. `updates` : champs additionnels de `AutopilotStateRecord`
        à mettre à jour dans le nouveau record (ex. `next_action=...`, `tests_status=...`)."""
        current = self.load()
        current_phase = AutopilotState(current.phase) if current is not None else AutopilotState.BOOTSTRAPPING
        allowed = ALLOWED_TRANSITIONS.get(current_phase, ())
        if target not in allowed:
            raise IllegalTransitionError(
                f"Transition refusée : {current_phase.value} -> {target.value} n'apparaît pas "
                f"dans ALLOWED_TRANSITIONS (autorisées depuis {current_phase.value} : "
                f"{[s.value for s in allowed]})."
            )
        base = _record_to_dict(current) if current is not None else {}
        base.update(updates)
        base["phase"] = target.value
        base["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        new_record = AutopilotStateRecord(**base)
        self.save(new_record)
        return new_record
