"""
scripts/autopilot/supervisor.py — Superviseur Autopilot V1 (Bootstrap, 2026-09-17).

Pilote la machine à états (`state_machine.py`) à travers la boucle mission §7 :
ANALYSER -> CHOISIR -> PLANIFIER -> DÉVELOPPER -> TESTER -> RÉVISER -> CORRIGER -> PRÉ-COMMIT
-> COMMIT -> PRÉ-PUSH -> PUSH -> CHECKPOINT -> MISSION SUIVANTE.

`run_one_step()` exécute EXACTEMENT une transition selon l'état persisté courant — la boucle est
donc naturellement idempotente/reprenable (mission §13/§18) : l'appeler après un crash produit la
même suite d'actions que si le process n'avait jamais été interrompu, sans jamais refaire une
étape déjà terminée (l'étape déjà terminée a déjà avancé la phase persistée).

Collaborateurs INJECTÉS, jamais codés en dur ici (mission Phase D : dry-run sûr, aucun
sous-processus Claude ni commande Git réelle dans les tests) :
- `developer_fn(mission, attempt) -> dict` : réalise le travail (en production, invoque Claude via
  `claude_invoker.py` ; en dry-run, une doublure). Doit retourner au moins `success: bool` et,
  en cas d'échec, `raw_output: str` (classée par `quota_detector.classify_failure()`).
- `tester_fn() -> dict` : exécute les tests ciblés/la régression, `success: bool` + `summary`. En
  cas d'échec, `summary` sert de repli pour la classification (`_handle_failure()`) puisque ce
  contrat ne porte pas de `raw_output` séparé — inclure la sortie utile (stdout/stderr) dedans.
- `reviewer_fn(mission) -> dict` : review indépendante — mission §11, doit être un contexte
  séparé du `developer_fn` (contrat imposé à l'appelant réel, non vérifiable structurellement
  ici) ; retourne `blocking_findings: list` (vide = review propre) + `summary`.
- `git_ops` : `GitOps` réel ou `FakeGitOps` — applique TOUJOURS `git_safety.check_git_command()`
  avant toute opération, jamais une commande Git construite ailleurs sans passer par ce garde.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Set, Union

from scripts.autopilot import git_safety
from scripts.autopilot.human_gate import HumanGateOption, HumanGateReport, format_human_gate_markdown
from scripts.autopilot.mission_queue import (
    Mission, load_missions, mark_mission_status, save_missions, select_next_mission,
)
from scripts.autopilot.quota_detector import FailureCategory, classify_failure
from scripts.autopilot.state_machine import AutopilotState, AutopilotStateRecord, AutopilotStateStore


class SingleInstanceLock:
    """Verrou fichier simple — mission §18 "une instance multiple est évitée". Pas un verrou
    inter-processus de niveau production (pas de détection de PID mort — limitation documentée,
    voir `.autopilot/README.md`), suffisant en V1 pour empêcher un second superviseur de démarrer
    tant que le premier tient le fichier et le libère proprement en sortie."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self._held = False

    def acquire(self) -> bool:
        if self.path.exists():
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("locked", encoding="utf-8")
        self._held = True
        return True

    def release(self) -> None:
        """Libère le verrou détenu par CETTE instance (`acquire()` appelé avec succès plus tôt
        dans le MÊME process). N'a aucun effet si cette instance ne le détenait pas."""
        if self._held and self.path.exists():
            self.path.unlink()
        self._held = False

    def force_release(self) -> None:
        """Supprime le fichier de verrou inconditionnellement, même depuis un process qui ne l'a
        jamais acquis lui-même — nécessaire pour `autopilot stop` (mission §14/§20), qui
        s'exécute typiquement dans une invocation CLI séparée de celle qui a démarré la boucle et
        ne peut donc jamais avoir `_held=True` sur sa propre instance."""
        if self.path.exists():
            self.path.unlink()
        self._held = False


class ForbiddenGitCommandError(ValueError):
    """Levée par `GitOps`/`FakeGitOps` si une opération violerait `git_safety.check_git_command()`
    ou `check_scope_files()` — jamais une commande interdite exécutée silencieusement."""


class FakeGitOps:
    """Doublure pour les tests/dry-run — n'exécute JAMAIS de commande Git réelle. Applique
    exactement les mêmes gardes `git_safety` qu'une implémentation réelle (`GitOps`) le ferait —
    preuve que le câblage de sécurité fonctionne dans le chemin d'exécution réel, pas seulement
    dans des tests isolés de `git_safety.py`."""

    def __init__(self):
        self.added: List[str] = []
        self.committed: bool = False
        self.commit_message: Optional[str] = None
        self.pushed: bool = False
        self.forced_push_attempted: bool = False

    def add(self, paths: List[str]) -> None:
        reason = git_safety.check_git_command(["git", "add", "--", *paths])
        if reason:
            raise ForbiddenGitCommandError(reason)
        scope_reason = git_safety.check_scope_files(paths)
        if scope_reason:
            raise ForbiddenGitCommandError(scope_reason)
        self.added.extend(paths)

    def commit(self, message: str) -> None:
        reason = git_safety.check_git_command(["git", "commit", "-m", message])
        if reason:
            raise ForbiddenGitCommandError(reason)
        self.committed = True
        self.commit_message = message

    def push(self, force: bool = False) -> None:
        argv = ["git", "push", "origin", "master"] + (["--force"] if force else [])
        reason = git_safety.check_git_command(argv)
        if reason:
            self.forced_push_attempted = force
            raise ForbiddenGitCommandError(reason)
        self.pushed = True


DeveloperFn = Callable[[Optional[Mission], int], dict]
TesterFn = Callable[[], dict]
ReviewerFn = Callable[[Optional[Mission]], dict]


class AutopilotSupervisor:
    def __init__(
        self,
        state_store: AutopilotStateStore,
        missions_path: Union[str, Path],
        developer_fn: DeveloperFn,
        tester_fn: TesterFn,
        reviewer_fn: ReviewerFn,
        git_ops,
        lock: SingleInstanceLock,
        branch: str = "master",
        failure_limit: int = 3,
    ):
        self._state_store = state_store
        self._missions_path = missions_path
        self._developer_fn = developer_fn
        self._tester_fn = tester_fn
        self._reviewer_fn = reviewer_fn
        self._git_ops = git_ops
        self._lock = lock
        self._branch = branch
        self._failure_limit = failure_limit
        # Historique EN MÉMOIRE des signatures d'échec pour la mission courante (mission §7,
        # anti-boucle) — suffisant en V1 pour une exécution continue d'un même process ; une
        # reprise après crash réel repart avec un historique vide (limitation documentée,
        # `.autopilot/README.md`) plutôt que de faire dépendre l'escalade d'un état persisté
        # supplémentaire non demandé par le Bootstrap V1.
        self._failure_signatures: List[str] = []

    def acquire_lock(self) -> bool:
        return self._lock.acquire()

    def release_lock(self) -> None:
        self._lock.release()

    def _current_record(self) -> Optional[AutopilotStateRecord]:
        return self._state_store.load()

    def _current_phase(self) -> AutopilotState:
        record = self._current_record()
        return AutopilotState(record.phase) if record is not None else AutopilotState.BOOTSTRAPPING

    def run_until(self, terminal_states: Set[AutopilotState], max_steps: int = 500) -> AutopilotState:
        for _ in range(max_steps):
            state = self.run_one_step()
            if state in terminal_states:
                return state
        raise RuntimeError(
            f"Autopilot : {max_steps} étapes exécutées sans atteindre un état terminal parmi "
            f"{[s.value for s in terminal_states]} — probable bug de boucle, jamais laissé tourner "
            "indéfiniment silencieusement (mission §7)."
        )

    def run_one_step(self) -> AutopilotState:
        phase = self._current_phase()
        handler = {
            AutopilotState.BOOTSTRAPPING: self._handle_bootstrapping,
            AutopilotState.READY: self._handle_ready,
            AutopilotState.PLANNING: self._handle_planning,
            AutopilotState.DEVELOPING: self._handle_developing,
            AutopilotState.TESTING: self._handle_testing,
            AutopilotState.REVIEWING: self._handle_reviewing,
            AutopilotState.CORRECTING: self._handle_correcting,
            AutopilotState.PRE_COMMIT_CHECK: self._handle_pre_commit_check,
            AutopilotState.COMMITTING: self._handle_committing,
            AutopilotState.PUSHING: self._handle_pushing,
            AutopilotState.CHECKPOINTED: self._handle_checkpointed,
            AutopilotState.NEXT_MISSION: self._handle_next_mission,
        }.get(phase)
        if handler is None:
            # États terminaux/d'attente (COMPLETED, STOPPED, WAITING_*, HUMAN_GATE_REQUIRED,
            # BLOCKED_SAFETY) : rien à faire tant qu'un appelant externe ne change pas
            # explicitement l'état (résolution Human Gate, reprise manuelle...).
            return phase
        return handler()

    # ── Handlers ──────────────────────────────────────────────────────────────────────────

    def _transition(self, target: AutopilotState, **updates) -> AutopilotState:
        record = self._state_store.transition_to(target, **updates)
        return AutopilotState(record.phase)

    def _retry_in_place(self, **updates) -> AutopilotState:
        record = self._state_store.update(**updates)
        return AutopilotState(record.phase)

    def _handle_bootstrapping(self) -> AutopilotState:
        # transition_to() gère déjà nativement l'absence de record initial (current=None ->
        # current_phase=BOOTSTRAPPING par défaut, base={}) — aucune initialisation manuelle
        # nécessaire ici.
        disk_reason = git_safety.check_disk_space()
        if disk_reason:
            return self._transition(AutopilotState.BLOCKED_SAFETY, stop_reason=disk_reason)
        return self._transition(AutopilotState.READY, branch=self._branch)

    def _handle_ready(self) -> AutopilotState:
        missions = load_missions(self._missions_path)
        if select_next_mission(missions) is None:
            return self._transition(AutopilotState.COMPLETED)
        return self._transition(AutopilotState.PLANNING)

    def _handle_planning(self) -> AutopilotState:
        missions = load_missions(self._missions_path)
        mission = select_next_mission(missions)
        if mission is None:
            return self._transition(AutopilotState.COMPLETED)
        self._failure_signatures = []
        return self._transition(
            AutopilotState.DEVELOPING, mission_id=mission.id,
            next_action=f"développer {mission.title}", attempt_count=0,
        )

    def _handle_developing(self) -> AutopilotState:
        record = self._current_record()
        mission = self._mission_by_id(record.mission_id)
        attempt = record.attempt_count + 1
        result = self._developer_fn(mission, attempt)
        if not result.get("success", False):
            return self._handle_failure(result, attempt)
        return self._transition(
            AutopilotState.TESTING, attempt_count=attempt,
            artifacts=tuple(result.get("changed_files", ())),
            next_action="exécuter les tests ciblés", stop_reason=None,
        )

    def _handle_testing(self) -> AutopilotState:
        record = self._current_record()
        result = self._tester_fn()
        if not result.get("success", False):
            attempt = record.attempt_count + 1
            return self._handle_failure(result, attempt)
        return self._transition(
            AutopilotState.REVIEWING, tests_status=result.get("summary", "passed"),
            next_action="lancer la review indépendante", stop_reason=None,
        )

    def _handle_reviewing(self) -> AutopilotState:
        record = self._current_record()
        mission = self._mission_by_id(record.mission_id)
        result = self._reviewer_fn(mission)
        blocking = result.get("blocking_findings", [])
        if blocking:
            return self._transition(
                AutopilotState.CORRECTING, review_status=f"{len(blocking)} finding(s) bloquant(s)",
                next_action="corriger les findings bloquants",
            )
        return self._transition(
            AutopilotState.PRE_COMMIT_CHECK, review_status=result.get("summary", "clean"),
            next_action="contrôles pré-commit",
        )

    def _handle_correcting(self) -> AutopilotState:
        # Mission §7 : diagnostic -> correction -> retest -> review, jamais un Human Gate pour un
        # simple finding de review (mission §12).
        return self._transition(AutopilotState.TESTING, next_action="retester après correction")

    def _handle_pre_commit_check(self) -> AutopilotState:
        record = self._current_record()
        scope_reason = git_safety.check_scope_files(record.artifacts)
        if scope_reason:
            return self._transition(AutopilotState.BLOCKED_SAFETY, stop_reason=scope_reason)
        disk_reason = git_safety.check_disk_space()
        if disk_reason:
            return self._transition(AutopilotState.BLOCKED_SAFETY, stop_reason=disk_reason)
        return self._transition(AutopilotState.COMMITTING, next_action="commit atomique")

    def _handle_committing(self) -> AutopilotState:
        record = self._current_record()
        mission = self._mission_by_id(record.mission_id)
        try:
            self._git_ops.add(list(record.artifacts))
            self._git_ops.commit(f"autopilot: {mission.title if mission else record.mission_id}")
        except ForbiddenGitCommandError as exc:
            return self._transition(AutopilotState.BLOCKED_SAFETY, stop_reason=str(exc))
        except Exception as exc:  # échec Git réel non couvert par git_safety (hook, disque, ...)
            # Jamais retenté silencieusement à l'identique (mission §7) : un commit qui échoue
            # pour une raison autre qu'une commande interdite est un cas qui n'a jamais été prévu
            # par cette V1 — traité conservativement comme nécessitant un regard humain, jamais
            # laissé crasher le superviseur (trouvé par la revue safety/architecture du Bootstrap).
            return self._transition(
                AutopilotState.BLOCKED_SAFETY,
                stop_reason=f"échec Git inattendu au commit (jamais retenté automatiquement) : {exc}",
            )
        return self._transition(AutopilotState.PUSHING, next_action="push origin master")

    def _handle_pushing(self) -> AutopilotState:
        try:
            self._git_ops.push()
        except ForbiddenGitCommandError as exc:
            return self._transition(AutopilotState.BLOCKED_SAFETY, stop_reason=str(exc))
        except Exception as exc:  # push refusé/échoué pour une raison non couverte par git_safety
            # Mission §8 : "jamais force, récupérer l'état distant, diagnostiquer la divergence" —
            # WAITING_FOR_EXTERNAL_RESOURCE est réservé exactement pour ce cas dans la machine à
            # états, mais aucun chemin ne l'atteignait avant ce correctif (revue safety/architecture
            # du Bootstrap, reproduit empiriquement : un push qui échoue crashait le superviseur).
            return self._transition(
                AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE,
                stop_reason=f"push refusé/échoué, divergence distante possible (jamais forcé) : {exc}",
            )
        return self._transition(AutopilotState.CHECKPOINTED, next_action="checkpoint")

    def _handle_checkpointed(self) -> AutopilotState:
        return self._transition(AutopilotState.NEXT_MISSION)

    def _handle_next_mission(self) -> AutopilotState:
        record = self._current_record()
        missions = load_missions(self._missions_path)
        if record.mission_id:
            missions = mark_mission_status(missions, record.mission_id, "DONE")
            save_missions(self._missions_path, missions)
        if select_next_mission(missions) is None:
            return self._transition(AutopilotState.COMPLETED)
        return self._transition(AutopilotState.PLANNING)

    # ── Échecs / escalade (mission §7/§13) ───────────────────────────────────────────────────

    def _handle_failure(self, result: dict, attempt: int) -> AutopilotState:
        # `developer_fn` renvoie `raw_output` ; `tester_fn` ne renvoie que `summary` (contrat
        # documenté en tête de module) — sans repli, une classification sur "" masquait TOUJOURS
        # NETWORK/QUOTA_LIMIT pour un échec de test (trouvé par la revue safety/architecture du
        # Bootstrap, empiriquement reproduit). Repli sur `summary` pour couvrir les deux appelants.
        raw_output = result.get("raw_output") or result.get("summary") or ""
        category = classify_failure(raw_output)
        signature = raw_output.strip()[:200]

        if category == FailureCategory.QUOTA_LIMIT:
            return self._transition(
                AutopilotState.WAITING_FOR_CLAUDE,
                stop_reason=f"limite d'usage Claude détectée : {signature}", attempt_count=attempt,
            )
        if category == FailureCategory.NETWORK:
            return self._transition(
                AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE,
                stop_reason=f"ressource externe indisponible : {signature}", attempt_count=attempt,
            )

        already_seen = list(self._failure_signatures)
        self._failure_signatures.append(signature)
        if git_safety.should_escalate(already_seen, signature, limit=self._failure_limit):
            report = HumanGateReport(
                decision="Un même échec se répète — poursuivre nécessite un changement d'approche.",
                reason=f"Échec identique {self._failure_limit} fois de suite : {signature}",
                recommendation="Escalader vers une revue humaine plutôt que de retenter la même approche.",
                options=[
                    HumanGateOption(
                        label="Escalader (recommandé)",
                        pros=["Évite une boucle infinie sur une cause déjà connue"],
                        cons=["Nécessite une intervention humaine"], recommended=True,
                    ),
                    HumanGateOption(
                        label="Continuer à retenter",
                        pros=["Aucune intervention requise"],
                        cons=["Risque de boucle improductive"], recommended=False,
                    ),
                ],
                risks=["Consommation de ressources sans progrès si on continue à retenter."],
                consequences="La mission reste bloquée jusqu'à résolution.",
            )
            return self._transition(
                AutopilotState.HUMAN_GATE_REQUIRED,
                stop_reason=format_human_gate_markdown(report), attempt_count=attempt,
            )

        return self._retry_in_place(attempt_count=attempt, stop_reason=f"tentative {attempt} échouée : {signature}")

    def _mission_by_id(self, mission_id: Optional[str]) -> Optional[Mission]:
        if mission_id is None:
            return None
        for m in load_missions(self._missions_path):
            if m.id == mission_id:
                return m
        return None
