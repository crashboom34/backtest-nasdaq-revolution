"""
scripts/autopilot/supervisor.py — Superviseur Autopilot V1.1 (2026-09-17).

Pilote la machine à états (`state_machine.py`) à travers la boucle mission §7 :
ANALYSER -> CHOISIR -> PLANIFIER -> DÉVELOPPER -> TESTER -> RÉVISER -> CORRIGER -> PRÉ-COMMIT
-> COMMIT -> PRÉ-PUSH -> PUSH -> CHECKPOINT -> MISSION SUIVANTE.

`run_one_step()` exécute EXACTEMENT une transition selon l'état persisté courant — la boucle est
donc naturellement idempotente/reprenable (mission §13/§18) : l'appeler après un crash produit la
même suite d'actions que si le process n'avait jamais été interrompu, sans jamais refaire une
étape déjà terminée (l'étape déjà terminée a déjà avancé la phase persistée).

**V1.1** : la reprise depuis `WAITING_FOR_CLAUDE`/`WAITING_FOR_EXTERNAL_RESOURCE` est désormais
RÉELLE (`_resume_to_recorded_phase()`, mission §3.5) plutôt qu'un no-op ; `CORRECTING` invoque
réellement le Developer avec les findings de review (`_handle_correcting`, mission §3.4) ; un
diagnostic est tenté une fois avant d'escalader vers un Human Gate sur échecs répétés identiques
(mission §7/§8) ; le commit/push sont idempotents via `last_commit_sha`/`last_push_sha` (mission
§3.8) ; une file de missions invalide/absente produit `BLOCKED_SAFETY`, jamais une file vide
silencieuse (mission §4).

Collaborateurs INJECTÉS, jamais codés en dur ici (mission Phase D : dry-run sûr avec doublures ;
`cli.py` construit les VRAIS collaborateurs pour un usage réel) :
- `developer_fn(mission, attempt, findings=None) -> dict` : réalise le travail (développement
  initial si `findings` est `None`, correction ciblée sinon). Doit retourner au moins
  `success: bool` et, en cas d'échec, `raw_output: str` (classée par
  `quota_detector.classify_failure()`) ; en cas de succès, `changed_files: list[str]` et
  optionnellement `session_id`.
- `tester_fn(mission) -> dict` : exécute les tests ciblés (`mission.targeted_tests`)/la régression
  proportionnée au risque (mission §5), `success: bool` + `summary`. En
  cas d'échec, `summary` sert de repli pour la classification (`_handle_failure()`) puisque ce
  contrat ne porte pas de `raw_output` séparé — inclure la sortie utile (stdout/stderr) dedans.
- `reviewer_fn(mission) -> dict` : review indépendante — mission §11, doit être un contexte
  séparé du `developer_fn` (contrat imposé à l'appelant réel, non vérifiable structurellement
  ici). Retourne `success: bool` (défaut `True` si absent, compat. doublures existantes) — `False`
  signifie un échec TECHNIQUE de la review elle-même (classée comme n'importe quel autre échec,
  jamais interprété comme "propre") — puis `blocking_findings: list` (vide = review propre) +
  `summary` + optionnellement `session_id`.
- `git_ops` : `GitOps` réel ou `FakeGitOps` — applique TOUJOURS `git_safety.check_git_command()`
  avant toute opération, jamais une commande Git construite ailleurs sans passer par ce garde.
- `diagnostic_fn(mission, failure_signature) -> dict` (optionnel) : tenté UNE fois par mission
  avant l'escalade vers `HUMAN_GATE_REQUIRED` sur échecs répétés identiques (mission §8 : "lancer
  un diagnostic indépendant, tenter une autre approche sûre, documenter les tentatives" — jamais
  une boucle infinie, une seule tentative de diagnostic par mission via `diagnostic_attempted`).
"""

from __future__ import annotations

import ctypes
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Set, Union

from scripts.autopilot import git_safety
from scripts.autopilot.human_gate import HumanGateOption, HumanGateReport, format_human_gate_markdown
from scripts.autopilot.mission_queue import (
    Mission, MissionQueueError, load_missions, mark_mission_status, save_missions, select_next_mission,
)
from scripts.autopilot.quota_detector import FailureCategory, classify_failure
from scripts.autopilot.state_machine import (
    ALLOWED_TRANSITIONS, AutopilotState, AutopilotStateRecord, AutopilotStateStore,
)


def _pid_is_alive(pid: Optional[int]) -> bool:
    """Vérifie prudemment si `pid` correspond à un processus vivant. En cas de doute (erreur
    d'API, PID absent), retourne `True` — mission §3.6 : ne JAMAIS voler un verrou par erreur ;
    une fausse détection de mort est bien pire qu'un verrou orphelin non récupéré."""
    if not pid:
        return True
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


class SingleInstanceLock:
    """Verrou fichier ATOMIQUE (`os.O_CREAT|os.O_EXCL`, mission §3.6) portant PID, horodatage UTC
    et répertoire de travail. Un verrou dont le PID enregistré ne correspond plus à un processus
    vivant est considéré ORPHELIN et automatiquement récupéré (une seule tentative de reprise, pas
    de boucle) — jamais si le contenu du verrou est illisible (JSON absent/corrompu : traité comme
    potentiellement détenu, prudence, cohérent avec `_pid_is_alive`). Pas encore un verrou
    inter-processus de niveau production multi-machine (limitation documentée,
    `.autopilot/README.md`) — suffisant en V1.1 pour une seule machine avec détection de PID mort."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self._held = False

    def _payload(self) -> dict:
        return {
            "pid": os.getpid(),
            "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
            "worktree": str(Path.cwd()),
        }

    def _read(self) -> Optional[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def acquire(self, _retried: bool = False) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not _retried:
                info = self._read()
                if info is not None and not _pid_is_alive(info.get("pid")):
                    # Verrou orphelin (processus mort) — le remplacer prudemment, UNE seule reprise.
                    self.force_release()
                    return self.acquire(_retried=True)
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._payload()))
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
        ne peut donc jamais avoir `_held=True` sur sa propre instance. `autopilot stop` doit
        idéalement signaler un arrêt coopératif avant de forcer (voir `StopSignal`) — ceci reste
        le filet de sécurité final."""
        if self.path.exists():
            self.path.unlink()
        self._held = False


class StopSignal:
    """Signal d'arrêt COOPÉRATIF fichier (mission §3.6 : "stop doit demander l'arrêt du
    superviseur, pas seulement supprimer son verrou"). `request()` (typiquement appelé par
    `autopilot stop` depuis une autre invocation CLI) dépose un fichier ; `is_requested()` est
    vérifié par `run_until()` entre deux étapes ; `clear()` le retire (nouveau démarrage)."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)

    def request(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")

    def is_requested(self) -> bool:
        return self.path.exists()

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


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
        self._commit_count = 0
        self._last_commit_message: Optional[str] = None
        self._last_commit_sha: Optional[str] = None

    def add(self, paths: List[str]) -> None:
        reason = git_safety.check_git_command(["git", "add", "--", *paths])
        if reason:
            raise ForbiddenGitCommandError(reason)
        scope_reason = git_safety.check_scope_files(paths)
        if scope_reason:
            raise ForbiddenGitCommandError(scope_reason)
        self.added.extend(paths)

    def commit(self, message: str) -> str:
        reason = git_safety.check_git_command(["git", "commit", "-m", message])
        if reason:
            raise ForbiddenGitCommandError(reason)
        self.committed = True
        self.commit_message = message
        self._commit_count += 1
        self._last_commit_message = message
        self._last_commit_sha = f"fake-sha-{self._commit_count}"
        return self._last_commit_sha

    def push(self, force: bool = False) -> str:
        argv = ["git", "push", "origin", "master"] + (["--force"] if force else [])
        reason = git_safety.check_git_command(argv)
        if reason:
            self.forced_push_attempted = force
            raise ForbiddenGitCommandError(reason)
        self.pushed = True
        return self._last_commit_sha or "fake-sha-0"

    def head_commit_message(self) -> Optional[str]:
        return self._last_commit_message

    def current_head_sha(self) -> Optional[str]:
        return self._last_commit_sha

    def is_worktree_clean(self) -> bool:
        # Doublure : aucune opération de fichier réelle n'a lieu en dehors de ce que l'Autopilot
        # lui-même simule via `add()`/`commit()` — toujours "propre" du point de vue de ce factice.
        return True


DeveloperFn = Callable[..., dict]
TesterFn = Callable[[Optional[Mission]], dict]
ReviewerFn = Callable[[Optional[Mission]], dict]
DiagnosticFn = Callable[[Optional[Mission], str], dict]


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
        diagnostic_fn: Optional[DiagnosticFn] = None,
        prompts_base_dir: Optional[Union[str, Path]] = None,
        stop_signal: Optional[StopSignal] = None,
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
        self._diagnostic_fn = diagnostic_fn
        self._prompts_base_dir = prompts_base_dir
        self._stop_signal = stop_signal
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
            if self._stop_signal is not None and self._stop_signal.is_requested():
                # Arrêt coopératif (mission §3.6) : ne complète pas l'étape suivante, s'arrête
                # proprement à la frontière d'une transition déjà persistée (jamais en plein
                # milieu d'une opération) — l'état courant reste valide pour une reprise ultérieure.
                return self._current_phase()
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
            # V1.1 : reprise réelle (mission §3.5), plus un no-op.
            AutopilotState.WAITING_FOR_CLAUDE: self._handle_waiting_for_claude,
            AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE: self._handle_waiting_for_external_resource,
        }.get(phase)
        if handler is None:
            # États terminaux/d'attente restants (COMPLETED, STOPPED, HUMAN_GATE_REQUIRED,
            # BLOCKED_SAFETY) : rien à faire tant qu'un appelant externe ne change pas
            # explicitement l'état (résolution Human Gate, `autopilot stop`/reprise manuelle...).
            return phase
        return handler()

    # ── Handlers ──────────────────────────────────────────────────────────────────────────

    def _transition(self, target: AutopilotState, **updates) -> AutopilotState:
        record = self._state_store.transition_to(target, **updates)
        return AutopilotState(record.phase)

    def _retry_in_place(self, **updates) -> AutopilotState:
        record = self._state_store.update(**updates)
        return AutopilotState(record.phase)

    def _load_missions_or_block(self) -> Optional[List[Mission]]:
        """Mission §4 : un fichier de missions absent/mal formé/invalide ne doit JAMAIS produire
        silencieusement une file vide ni un faux `COMPLETED` — route explicitement vers
        `BLOCKED_SAFETY` avec la raison exacte. Retourne `None` quand ce routage a eu lieu (au
        lieu d'une liste), l'appelant doit alors retourner directement la valeur reçue en amont."""
        try:
            return load_missions(self._missions_path, prompts_base_dir=self._prompts_base_dir)
        except MissionQueueError as exc:
            self._transition(AutopilotState.BLOCKED_SAFETY, stop_reason=f"file de missions invalide : {exc}")
            return None

    def _handle_bootstrapping(self) -> AutopilotState:
        # transition_to() gère déjà nativement l'absence de record initial (current=None ->
        # current_phase=BOOTSTRAPPING par défaut, base={}) — aucune initialisation manuelle
        # nécessaire ici.
        disk_reason = git_safety.check_disk_space()
        if disk_reason:
            return self._transition(AutopilotState.BLOCKED_SAFETY, stop_reason=disk_reason)
        return self._transition(AutopilotState.READY, branch=self._branch)

    def _handle_ready(self) -> AutopilotState:
        missions = self._load_missions_or_block()
        if missions is None:
            return self._current_phase()
        if select_next_mission(missions) is None:
            return self._transition(AutopilotState.COMPLETED)
        return self._transition(AutopilotState.PLANNING)

    def _handle_planning(self) -> AutopilotState:
        missions = self._load_missions_or_block()
        if missions is None:
            return self._current_phase()
        mission = select_next_mission(missions)
        if mission is None:
            return self._transition(AutopilotState.COMPLETED)
        # V1.1 : `requires_clean_worktree` était déclaré dans le schéma de mission mais jamais
        # réellement vérifié nulle part — trouvé lors de la revue indépendante de cette mission.
        # Une mission qui l'exige (True par défaut) ne doit JAMAIS démarrer sur un worktree portant
        # déjà des modifications étrangères non liées : c'est exactement le scénario qui a pollué
        # le scope (`changed_files`) du canary réel de cette mission (édits d'ingénierie laissés
        # non committés au moment où le Developer a tourné).
        if mission.requires_clean_worktree and not self._git_ops.is_worktree_clean():
            return self._transition(
                AutopilotState.BLOCKED_SAFETY,
                stop_reason=(
                    f"mission {mission.id} exige un worktree propre (requires_clean_worktree=True) "
                    "mais des modifications non liées sont présentes — jamais démarrée sur un état "
                    "ambigu (mission Autopilot V1.1 §4/§13)."
                ),
            )
        self._failure_signatures = []
        return self._transition(
            AutopilotState.DEVELOPING, mission_id=mission.id,
            next_action=f"développer {mission.title}", attempt_count=0,
            diagnostic_attempted=False, pending_findings=(), last_commit_sha=None, last_push_sha=None,
        )

    def _handle_developing(self) -> AutopilotState:
        record = self._current_record()
        mission = self._mission_by_id(record.mission_id)
        attempt = record.attempt_count + 1
        result = self._developer_fn(mission, attempt, findings=None)
        if not result.get("success", False):
            return self._handle_failure(result, attempt)
        return self._transition(
            AutopilotState.TESTING, attempt_count=attempt,
            artifacts=tuple(result.get("changed_files", ())),
            next_action="exécuter les tests ciblés", stop_reason=None,
            developer_session_id=result.get("session_id"),
        )

    def _handle_testing(self) -> AutopilotState:
        record = self._current_record()
        mission = self._mission_by_id(record.mission_id)
        result = self._tester_fn(mission)
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
        if not result.get("success", True):
            attempt = record.attempt_count + 1
            return self._handle_failure(result, attempt)
        blocking = result.get("blocking_findings", [])
        if blocking:
            return self._transition(
                AutopilotState.CORRECTING, review_status=f"{len(blocking)} finding(s) bloquant(s)",
                pending_findings=tuple(str(f) for f in blocking),
                next_action="corriger les findings bloquants",
                reviewer_session_id=result.get("session_id"),
            )
        return self._transition(
            AutopilotState.PRE_COMMIT_CHECK, review_status=result.get("summary", "clean"),
            next_action="contrôles pré-commit", reviewer_session_id=result.get("session_id"),
        )

    def _handle_correcting(self) -> AutopilotState:
        # V1.1 (mission §3.4) : le Developer reçoit RÉELLEMENT les findings de review et modifie
        # le code — jamais un simple passage direct vers TESTING sans nouvelle tentative réelle.
        record = self._current_record()
        mission = self._mission_by_id(record.mission_id)
        attempt = record.attempt_count + 1
        result = self._developer_fn(mission, attempt, findings=list(record.pending_findings))
        if not result.get("success", False):
            return self._handle_failure(result, attempt)
        return self._transition(
            AutopilotState.TESTING, attempt_count=attempt,
            artifacts=tuple(result.get("changed_files", record.artifacts)),
            next_action="retester après correction", pending_findings=(), stop_reason=None,
            developer_session_id=result.get("session_id"),
        )

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
        intended_message = f"autopilot: {mission.title if mission else record.mission_id}"
        # V1.1 : marquer la mission DONE fait partie du MÊME commit que son propre travail — jamais
        # un flip d'état laissé non committé. Trouvé RÉELLEMENT cassé par le canary : l'ancien
        # `_handle_next_mission()` mettait `missions.json` à jour APRÈS le push (donc jamais
        # inclus dans le commit ni poussé) — un fresh checkout/pull aurait revu la mission comme
        # "PLANNED" et aurait pu la re-sélectionner/la ré-exécuter. Idempotent : réexécuter ce
        # flip lors d'une reprise après crash est un no-op (`mark_mission_status` sur un statut
        # déjà `DONE`, `save_missions()` réécrit un contenu identique).
        scope = list(record.artifacts)
        if record.mission_id:
            missions = self._load_missions_or_block()
            if missions is None:
                return self._current_phase()
            missions = mark_mission_status(missions, record.mission_id, "DONE")
            missions_path_str = str(self._missions_path)
            if missions_path_str not in scope:
                scope.append(missions_path_str)
            save_missions(self._missions_path, missions)
        try:
            # Idempotence (mission §3.8) : si un commit avec ce message exact est déjà HEAD (crash
            # entre un `git commit` réel réussi et l'enregistrement de la transition), ne JAMAIS
            # committer une seconde fois — passer directement au push avec le SHA déjà produit.
            existing_message = self._git_ops.head_commit_message()
            if existing_message == intended_message:
                sha = self._git_ops.current_head_sha()
                return self._transition(
                    AutopilotState.PUSHING, next_action="push origin master (commit déjà effectué)",
                    last_commit_sha=sha,
                )
            self._git_ops.add(scope)
            sha = self._git_ops.commit(intended_message)
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
        return self._transition(AutopilotState.PUSHING, next_action="push origin master", last_commit_sha=sha)

    def _handle_pushing(self) -> AutopilotState:
        record = self._current_record()
        try:
            # Idempotence symétrique (mission §3.8) : si le SHA local a déjà été poussé lors d'un
            # cycle précédent (crash entre un push réel réussi et l'enregistrement du CHECKPOINT),
            # ne JAMAIS repousser — passer directement au checkpoint.
            if record.last_push_sha and record.last_push_sha == record.last_commit_sha:
                return self._transition(AutopilotState.CHECKPOINTED, next_action="checkpoint (déjà poussé)")
            pushed_sha = self._git_ops.push()
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
                resume_to_phase=AutopilotState.PUSHING.value,
            )
        return self._transition(
            AutopilotState.CHECKPOINTED, next_action="checkpoint", last_push_sha=pushed_sha,
        )

    def _handle_checkpointed(self) -> AutopilotState:
        return self._transition(AutopilotState.NEXT_MISSION)

    def _handle_next_mission(self) -> AutopilotState:
        # Le flip DONE de la mission qui vient de se terminer a déjà eu lieu dans
        # `_handle_committing()` (V1.1 — même commit que son propre travail, jamais un flip d'état
        # séparé et non committé) — cette relecture ne fait plus que choisir la mission suivante.
        missions = self._load_missions_or_block()
        if missions is None:
            return self._current_phase()
        if select_next_mission(missions) is None:
            return self._transition(AutopilotState.COMPLETED)
        return self._transition(AutopilotState.PLANNING)

    # ── Reprise réelle depuis WAITING_* (mission §3.5) ───────────────────────────────────────

    def _resume_to_recorded_phase(self) -> AutopilotState:
        record = self._current_record()
        target_value = record.resume_to_phase if record is not None else None
        current_phase = self._current_phase()
        allowed = ALLOWED_TRANSITIONS.get(current_phase, ())
        target: Optional[AutopilotState] = None
        if target_value:
            try:
                candidate = AutopilotState(target_value)
                if candidate in allowed:
                    target = candidate
            except ValueError:
                target = None
        if target is None:
            target = AutopilotState.PLANNING
        return self._transition(target, next_action=f"reprise vers {target.value}", resume_to_phase=None)

    def _handle_waiting_for_claude(self) -> AutopilotState:
        return self._resume_to_recorded_phase()

    def _handle_waiting_for_external_resource(self) -> AutopilotState:
        return self._resume_to_recorded_phase()

    # ── Échecs / diagnostic / escalade (mission §7/§8/§13) ───────────────────────────────────

    def _handle_failure(self, result: dict, attempt: int) -> AutopilotState:
        # `developer_fn` renvoie `raw_output` ; `tester_fn`/`reviewer_fn` ne renvoient que
        # `summary` (contrat documenté en tête de module) — sans repli, une classification sur ""
        # masquait TOUJOURS NETWORK/QUOTA_LIMIT pour ces échecs (trouvé par la revue safety/
        # architecture du Bootstrap, empiriquement reproduit). Repli sur `summary`.
        raw_output = result.get("raw_output") or result.get("summary") or ""
        category = classify_failure(raw_output)
        signature = raw_output.strip()[:200]
        current_phase_value = self._current_phase().value

        if category == FailureCategory.QUOTA_LIMIT:
            return self._transition(
                AutopilotState.WAITING_FOR_CLAUDE,
                stop_reason=f"limite d'usage Claude détectée : {signature}", attempt_count=attempt,
                resume_to_phase=current_phase_value,
            )
        if category == FailureCategory.NETWORK:
            return self._transition(
                AutopilotState.WAITING_FOR_EXTERNAL_RESOURCE,
                stop_reason=f"ressource externe indisponible : {signature}", attempt_count=attempt,
                resume_to_phase=current_phase_value,
            )

        already_seen = list(self._failure_signatures)
        self._failure_signatures.append(signature)
        if not git_safety.should_escalate(already_seen, signature, limit=self._failure_limit):
            return self._retry_in_place(
                attempt_count=attempt, stop_reason=f"tentative {attempt} échouée : {signature}",
            )

        # Mission §8 : "avant le Human Gate, lancer un diagnostic indépendant, tenter une autre
        # approche sûre, documenter les tentatives" — UNE seule fois par mission
        # (`diagnostic_attempted`), jamais une boucle supplémentaire non bornée.
        record = self._current_record()
        if self._diagnostic_fn is not None and not record.diagnostic_attempted:
            diagnosis = self._diagnostic_fn(self._mission_by_id(record.mission_id), signature)
            notes = diagnosis.get("approach_notes", "(aucune note)") if isinstance(diagnosis, dict) else "(aucune note)"
            return self._retry_in_place(
                attempt_count=attempt, diagnostic_attempted=True,
                stop_reason=(
                    f"échec répété ({self._failure_limit}x, signature identique) — diagnostic "
                    f"indépendant tenté avant escalade : {notes}"
                ),
            )

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

    def _mission_by_id(self, mission_id: Optional[str]) -> Optional[Mission]:
        """Relecture tolérante — jamais de transition d'état ici (contrairement à
        `_load_missions_or_block()`, réservée aux points de décision READY/PLANNING/NEXT_MISSION
        où une file invalide EST la cause racine de l'arrêt). Une mission déjà sélectionnée par
        `_handle_planning()` a été validée à ce moment-là ; si le fichier devient illisible plus
        tard dans le même cycle (cas limite), retourner `None` ici ne doit jamais déclencher une
        seconde transition concurrente à celle que gère déjà le handler appelant."""
        if mission_id is None:
            return None
        try:
            missions = load_missions(self._missions_path, prompts_base_dir=self._prompts_base_dir)
        except MissionQueueError:
            return None
        for m in missions:
            if m.id == mission_id:
                return m
        return None
