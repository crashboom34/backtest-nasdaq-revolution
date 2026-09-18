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


_FAILURE_NOTE_PREFIX = "Échec précédent à corriger : "
"""Préfixe stable identifiant une note de CONSTAT D'ÉCHEC (ajoutée automatiquement par
`_handle_failure()`), distincte d'un finding ORIGINAL de review/test — permet de préserver ce
dernier à travers un échec transitoire ultérieur sans rapport (finalisation sécurité point 4.1),
sans jamais faire grossir indéfiniment `pending_findings` à chaque nouvelle tentative."""

_ERROR_INVALID_PARAMETER = 87  # Windows : code renvoyé par OpenProcess pour un PID qui n'existe
# structurellement pas (jamais existé/déjà réutilisé par le OS pour un tout autre process) —
# DISTINCT de ERROR_ACCESS_DENIED (5, le process existe mais est protégé/contexte de sécurité
# différent). Confondre les deux a permis un vol de verrou actif, reproduit empiriquement par la
# revue safety/architecture V1.1 : `OpenProcess` échoue aussi pour un process bien vivant mais
# inaccessible (élévation différente, EDR/AV, process protégé) — seul `ERROR_INVALID_PARAMETER`
# est une preuve fiable que le PID n'existe pas.


def _pid_is_alive(pid: Optional[int]) -> bool:
    """Vérifie prudemment si `pid` correspond à un processus vivant. En cas de doute (erreur
    d'API, PID absent), retourne `True` — mission §3.6 : ne JAMAIS voler un verrou par erreur ;
    une fausse détection de mort est bien pire qu'un verrou orphelin non récupéré."""
    if not pid:
        return True
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return ctypes.get_last_error() != _ERROR_INVALID_PARAMETER
        kernel32.CloseHandle(handle)
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

    def is_held_by_a_live_process(self) -> bool:
        """Mission finalisation V1.1 (§2.A) : distingue "personne ne détient le verrou"/"détenu
        par un process mort" (récupérable) de "détenu par un process réellement vivant" (jamais à
        libérer de force). Contenu illisible/absent traité prudemment comme potentiellement
        détenu — cohérent avec `_pid_is_alive`/`acquire()` : ne jamais voler un verrou par doute."""
        if not self.path.exists():
            return False
        info = self._read()
        if info is None:
            return True  # illisible -> prudence, jamais supposé mort
        return _pid_is_alive(info.get("pid"))

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


class HumanGateResolutionRefused(ValueError):
    """Levée par `AutopilotSupervisor.resolve_human_gate()` quand la résolution ne peut être
    appliquée en toute sécurité (mission finalisation reprise 2026-09-18) — jamais une transition
    forcée malgré un refus, jamais un contournement de `requires_clean_worktree`."""


def _unattributable_paths(dirty_paths: List[str], allowed_paths) -> List[str]:
    """Chemins "sales" qui ne relèvent PAS du scope déclaré d'une mission (`mission.allowed_paths`)
    — utilisé par `resolve_human_gate()` pour distinguer le travail légitimement en cours de la
    mission interrompue (attribuable) d'une contamination étrangère (jamais résolue à l'aveugle).
    Une correspondance EXACTE ou un chemin sous un préfixe de répertoire déclaré (ex.
    `.autopilot/canary/`) compte comme attribuable."""
    allowed = [p.replace("\\", "/") for p in allowed_paths]

    def _covered(path: str) -> bool:
        normalized = path.replace("\\", "/")
        return any(
            normalized == a or normalized.startswith(a.rstrip("/") + "/") for a in allowed
        )

    return sorted(p for p in dirty_paths if not _covered(p))


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
        # Finalisation reprise (2026-09-18) : chemins "sales" simulés, pour tester la
        # reconnaissance du travail attribuable à une mission (`resolve_human_gate()`) — vide par
        # défaut, cohérent avec `is_worktree_clean()` retournant `True` par défaut.
        self.simulated_dirty_paths: List[str] = []

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
        # lui-même simule via `add()`/`commit()` — "propre" ssi aucun chemin sale simulé.
        return not self.simulated_dirty_paths

    def dirty_paths(self) -> List[str]:
        """Chemins actuellement "sales" — simulés pour les tests (`resolve_human_gate()`,
        finalisation reprise 2026-09-18) ; jamais un accès disque réel dans cette doublure."""
        return list(self.simulated_dirty_paths)


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
            # Finalisation V1.1 (§2.E) : résolution CONTRÔLÉE, plus un no-op — revérifie la cause
            # précise avant toute reprise, ne force jamais.
            AutopilotState.BLOCKED_SAFETY: self._handle_blocked_safety,
        }.get(phase)
        if handler is None:
            # États terminaux/d'attente restants (COMPLETED, STOPPED, HUMAN_GATE_REQUIRED) : rien
            # à faire tant qu'un appelant externe ne change pas explicitement l'état (résolution
            # Human Gate, `autopilot stop`/reprise manuelle...).
            return phase
        return handler()

    # ── Handlers ──────────────────────────────────────────────────────────────────────────

    def _transition(self, target: AutopilotState, **updates) -> AutopilotState:
        record = self._state_store.transition_to(target, **updates)
        return AutopilotState(record.phase)

    def _retry_in_place(self, **updates) -> AutopilotState:
        record = self._state_store.update(**updates)
        return AutopilotState(record.phase)

    @staticmethod
    def _invoke_safely(fn, *args, label: str, **kwargs) -> dict:
        """Finalisation sécurité (point 4.2) : enveloppe un callback INJECTÉ (Developer/Tester/
        Reviewer). Avant ce correctif, seuls `_handle_committing`/`_handle_pushing` protégeaient
        leur appel Git contre une exception — une exception levée PAR `developer_fn`/`tester_fn`/
        `reviewer_fn` eux-mêmes (bug interne, ex. `real_reviewer_fn` levant
        `ForbiddenGitCommandError` via `git_safety`) se propageait hors de `run_one_step()` et
        crashait tout le process, sans le moindre état persisté ni classification — jamais un
        succès implicite, jamais un crash silencieux : convertie en échec `success: False` ORDINAIRE,
        retraité exactement comme n'importe quel autre échec fonctionnel (classification, retry,
        escalade)."""
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # jamais un crash du superviseur pour un bug du callback injecté
            return {
                "success": False,
                "raw_output": f"exception non gérée dans {label} (jamais un succès implicite) : {exc!r}",
            }

    def _load_missions_or_block(self) -> Optional[List[Mission]]:
        """Mission §4 : un fichier de missions absent/mal formé/invalide ne doit JAMAIS produire
        silencieusement une file vide ni un faux `COMPLETED` — route explicitement vers
        `BLOCKED_SAFETY` avec la raison exacte. Retourne `None` quand ce routage a eu lieu (au
        lieu d'une liste), l'appelant doit alors retourner directement la valeur reçue en amont."""
        try:
            return load_missions(self._missions_path, prompts_base_dir=self._prompts_base_dir)
        except MissionQueueError as exc:
            self._transition(
                AutopilotState.BLOCKED_SAFETY, stop_reason=f"file de missions invalide : {exc}",
                blocked_reason_category="missions_invalid",
            )
            return None

    def _handle_bootstrapping(self) -> AutopilotState:
        # transition_to() gère déjà nativement l'absence de record initial (current=None ->
        # current_phase=BOOTSTRAPPING par défaut, base={}) — aucune initialisation manuelle
        # nécessaire ici.
        disk_reason = git_safety.check_disk_space()
        if disk_reason:
            return self._transition(
                AutopilotState.BLOCKED_SAFETY, stop_reason=disk_reason,
                blocked_reason_category="disk_space", resume_to_phase=AutopilotState.READY.value,
            )
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
                blocked_reason_category="dirty_worktree", resume_to_phase=AutopilotState.PLANNING.value,
            )
        self._failure_signatures = []
        return self._transition(
            AutopilotState.DEVELOPING, mission_id=mission.id,
            next_action=f"développer {mission.title}", attempt_count=0,
            diagnostic_attempted=False, pending_findings=(), last_commit_sha=None, last_push_sha=None,
            # Finalisation sécurité (point 5) : bug réel confirmé sur le canary de cette mission —
            # `tests_status`/`review_status`/`reviewed_files`/`artifacts`/les session ids restaient
            # ceux de la mission PRÉCÉDENTE jusqu'à ce que TESTING/REVIEWING tournent réellement
            # pour la NOUVELLE mission. `transition_to()` ne fait qu'un merge partiel (tout champ
            # omis ici est conservé tel quel) — jamais un simple oubli, ces preuves d'une mission ne
            # doivent jamais pouvoir être lues comme valant pour une autre.
            tests_status=None, review_status=None, reviewed_files=(), artifacts=(),
            developer_session_id=None, reviewer_session_id=None,
            # Complète le fix ci-dessus (trouvé incomplet par la revue reproductibilité/scope de
            # cette mission, empiriquement reproduit) : un `stop_reason` posé par un événement
            # RÉSOLU de la mission précédente (ex. la résolution d'un BLOCKED_SAFETY, seul cas où
            # `stop_reason` se pose sans être ensuite nettoyé par une étape de succès) ne doit
            # jamais rester lisible comme s'il concernait la nouvelle mission.
            stop_reason=None,
        )

    def _resolve_mission_or_block(self, record: AutopilotStateRecord):
        """Résout la mission courante depuis son id persisté. `record.mission_id` renseigné mais
        introuvable (file corrompue/modifiée pendant l'exécution) est une ANOMALIE distincte d'une
        mission jamais choisie — routée immédiatement vers `BLOCKED_SAFETY`, jamais dégradée
        silencieusement en invoquant un `developer_fn`/`reviewer_fn` réel (donc facturé) avec un
        contexte quasi vide (trouvé par la revue reproductibilité/scope de cette mission : sans ce
        garde, un appel Claude réel aurait été payé sur un prompt sans contenu avant que la
        corruption ne soit enfin détectée à `COMMITTING`). Retourne `(mission, None)` normalement,
        ou `(None, blocked_state)` si le routage vers `BLOCKED_SAFETY` a déjà eu lieu."""
        if record.mission_id is None:
            return None, None
        mission = self._mission_by_id(record.mission_id)
        if mission is None:
            blocked = self._transition(
                AutopilotState.BLOCKED_SAFETY,
                stop_reason=(
                    f"mission {record.mission_id!r} introuvable dans la file (fichier corrompu/"
                    "modifié pendant l'exécution) — jamais dégradé silencieusement vers un appel "
                    "réel sans contexte (mission Autopilot V1.1 §4)."
                ),
                blocked_reason_category="mission_not_found",
            )
            return None, blocked
        return mission, None

    def _handle_developing(self) -> AutopilotState:
        record = self._current_record()
        mission, blocked = self._resolve_mission_or_block(record)
        if blocked is not None:
            return blocked
        attempt = record.attempt_count + 1
        # Finalisation V1.1 (§2.C) : une retentative en place (échec non-escaladant) doit
        # transmettre l'échec précédent au Developer, jamais répéter le MÊME prompt sans le
        # moindre retour sur ce qui a échoué — `pending_findings` porte ce retour s'il existe déjà.
        findings = list(record.pending_findings) if record.pending_findings else None
        result = self._invoke_safely(self._developer_fn, mission, attempt, label="developer_fn", findings=findings)
        if not result.get("success", False):
            return self._handle_failure(result, attempt, mission)
        return self._transition(
            AutopilotState.TESTING, attempt_count=attempt,
            artifacts=tuple(result.get("changed_files", ())),
            next_action="exécuter les tests ciblés", stop_reason=None, pending_findings=(),
            developer_session_id=result.get("session_id"),
        )

    def _handle_testing(self) -> AutopilotState:
        record = self._current_record()
        mission, blocked = self._resolve_mission_or_block(record)
        if blocked is not None:
            return blocked
        result = self._invoke_safely(self._tester_fn, mission, label="tester_fn")
        if not result.get("success", False):
            attempt = record.attempt_count + 1
            # Finalisation V1.1 (§2.C) — bug réel trouvé : un échec de test retentait en place SUR
            # TESTING, ce qui ne fait que rappeler `tester_fn()` sans le moindre changement de code
            # entre-temps — un test déterministe échoue alors IDENTIQUEMENT à chaque fois, sans
            # jamais progresser vers une correction (juste vers une escalade accélérée par
            # signature répétée). Toute retentative non-escaladante doit transmettre l'échec au
            # Developer via CORRECTING, jamais rester en boucle sur TESTING seul.
            return self._handle_failure(result, attempt, mission, retry_target=AutopilotState.CORRECTING)
        return self._transition(
            AutopilotState.REVIEWING, tests_status=result.get("summary", "passed"),
            next_action="lancer la review indépendante", stop_reason=None,
        )

    def _handle_reviewing(self) -> AutopilotState:
        record = self._current_record()
        mission, blocked = self._resolve_mission_or_block(record)
        if blocked is not None:
            return blocked
        result = self._invoke_safely(self._reviewer_fn, mission, label="reviewer_fn")
        if not result.get("success", True):
            attempt = record.attempt_count + 1
            return self._handle_failure(result, attempt, mission)
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
            # Finalisation V1.1 (§2.B) : lie la preuve de review au contenu exact — vérifié à
            # `_handle_pre_commit_check()` avant de committer quoi que ce soit.
            reviewed_files=tuple(result.get("reviewed_files", ())),
        )

    def _handle_correcting(self) -> AutopilotState:
        # V1.1 (mission §3.4) : le Developer reçoit RÉELLEMENT les findings de review et modifie
        # le code — jamais un simple passage direct vers TESTING sans nouvelle tentative réelle.
        record = self._current_record()
        mission, blocked = self._resolve_mission_or_block(record)
        if blocked is not None:
            return blocked
        attempt = record.attempt_count + 1
        result = self._invoke_safely(
            self._developer_fn, mission, attempt, label="developer_fn (correcting)",
            findings=list(record.pending_findings),
        )
        if not result.get("success", False):
            return self._handle_failure(result, attempt, mission)
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
            return self._transition(
                AutopilotState.BLOCKED_SAFETY, stop_reason=scope_reason,
                blocked_reason_category="scope_violation",
            )
        disk_reason = git_safety.check_disk_space()
        if disk_reason:
            return self._transition(
                AutopilotState.BLOCKED_SAFETY, stop_reason=disk_reason,
                blocked_reason_category="disk_space", resume_to_phase=AutopilotState.PRE_COMMIT_CHECK.value,
            )
        # Finalisation V1.1 (§2.B), rendu OBLIGATOIRE par la finalisation sécurité (point 4.4) :
        # "lier les preuves de tests et de review au contenu EXACT finalement committé" — une
        # couverture de review ABSENTE OU VIDE ne doit plus jamais laisser passer un commit dès
        # lors qu'il existe réellement des `artifacts` à committer (bug réel confirmé : l'ancienne
        # garde était opt-in — un `reviewer_fn` ne renseignant pas `reviewed_files`, par bug ou par
        # contournement, désactivait purement et simplement ce contrôle). Rien à committer
        # (`artifacts=()`) reste le seul cas trivialement non bloqué : il n'y a alors rien qui
        # aurait pu échapper à la review.
        if record.artifacts:
            if not record.reviewed_files:
                return self._transition(
                    AutopilotState.BLOCKED_SAFETY,
                    stop_reason=(
                        "aucune preuve de couverture de review pour les fichiers sur le point "
                        f"d'être committés ({sorted(record.artifacts)}) — une liste de fichiers "
                        "revus absente ou vide ne doit jamais permettre un commit/push "
                        "(finalisation sécurité point 4.4)."
                    ),
                    blocked_reason_category="unreviewed_files",
                )
            unreviewed = sorted(set(record.artifacts) - set(record.reviewed_files))
            if unreviewed:
                return self._transition(
                    AutopilotState.BLOCKED_SAFETY,
                    stop_reason=(
                        f"fichier(s) sur le point d'être committé(s) jamais couvert(s) par la review "
                        f"indépendante : {unreviewed} (mission finalisation V1.1 §2.B)."
                    ),
                    blocked_reason_category="unreviewed_files",
                )
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
            return self._transition(
                AutopilotState.BLOCKED_SAFETY, stop_reason=str(exc), blocked_reason_category="git_forbidden",
            )
        except Exception as exc:  # échec Git réel non couvert par git_safety (hook, disque, ...)
            # Jamais retenté silencieusement à l'identique (mission §7) : un commit qui échoue
            # pour une raison autre qu'une commande interdite est un cas qui n'a jamais été prévu
            # par cette V1 — traité conservativement comme nécessitant un regard humain, jamais
            # laissé crasher le superviseur (trouvé par la revue safety/architecture du Bootstrap).
            return self._transition(
                AutopilotState.BLOCKED_SAFETY,
                stop_reason=f"échec Git inattendu au commit (jamais retenté automatiquement) : {exc}",
                blocked_reason_category="commit_error",
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
            return self._transition(
                AutopilotState.BLOCKED_SAFETY, stop_reason=str(exc), blocked_reason_category="git_forbidden",
            )
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

    # ── Résolution contrôlée de BLOCKED_SAFETY (finalisation V1.1 §2.E) ─────────────────────

    def _handle_blocked_safety(self) -> AutopilotState:
        """Ne JAMAIS reprendre aveuglément (ni effacer l'état, ni désactiver une garde comme
        `requires_clean_worktree`) : revérifie explicitement la cause précise catégorisée
        (`blocked_reason_category`) et ne quitte `BLOCKED_SAFETY` QUE si elle est réellement
        résolue maintenant. Seules certaines catégories ont une résolution automatique connue
        (`dirty_worktree`, `disk_space`) — toute autre catégorie (fichier de missions invalide,
        mission introuvable, violation de scope, review incomplète, commande Git interdite,
        échec de commit inattendu) nécessite une intervention externe réelle (édition d'un
        fichier, changement de configuration) et reste bloquée indéfiniment sans une telle
        intervention — jamais une résolution automatique inventée pour une cause qui n'en a pas."""
        record = self._current_record()
        if record is None:
            return AutopilotState.BLOCKED_SAFETY
        category = record.blocked_reason_category
        resolved = False
        if category == "dirty_worktree":
            resolved = self._git_ops.is_worktree_clean()
        elif category == "disk_space":
            resolved = git_safety.check_disk_space() is None
        if not resolved:
            return AutopilotState.BLOCKED_SAFETY  # cause toujours présente -> reste bloqué
        target: Optional[AutopilotState] = None
        if record.resume_to_phase:
            try:
                candidate = AutopilotState(record.resume_to_phase)
                if candidate in ALLOWED_TRANSITIONS.get(AutopilotState.BLOCKED_SAFETY, ()):
                    target = candidate
            except ValueError:
                target = None
        if target is None:
            target = AutopilotState.PLANNING
        return self._transition(
            target,
            stop_reason=f"BLOCKED_SAFETY résolu (cause {category!r} revérifiée) — reprise contrôlée.",
            blocked_reason_category=None, resume_to_phase=None,
        )

    # ── Résolution contrôlée de HUMAN_GATE_REQUIRED (finalisation reprise 2026-09-18) ────────

    def resolve_human_gate(
        self, resume_to: AutopilotState, operational_cause_resolved: str,
    ) -> AutopilotState:
        """Résolution EXPLICITE, tracée et testée d'un `HUMAN_GATE_REQUIRED` dont la cause
        OPÉRATIONNELLE (jamais scientifique) est corrigée — jamais une simple réédition du
        fichier d'état pour forcer une transition. Reprend DIRECTEMENT vers `resume_to` (validé
        contre `ALLOWED_TRANSITIONS`) — jamais un redémarrage `PLANNING` qui perdrait la
        progression réelle déjà accomplie. `pending_findings` scientifique n'est JAMAIS touché
        ici : tout finding non résolu reste tel quel, transmis à la prochaine invocation réelle
        du Developer/Reviewer selon la phase de reprise.

        Refuse (lève `HumanGateResolutionRefused`, JAMAIS une transition partielle) si : la phase
        courante n'est pas `HUMAN_GATE_REQUIRED` ; `resume_to` n'est pas une cible autorisée
        depuis cet état ; la mission persistée est introuvable dans la file (jamais résolu à
        l'aveugle sans pouvoir vérifier son scope déclaré) ; le worktree porte des modifications
        NON ATTRIBUABLES au scope déclaré de cette mission (`mission.allowed_paths`) — dans ce
        dernier cas, une contamination étrangère reste bloquée jusqu'à investigation humaine,
        `requires_clean_worktree` n'est ni contourné ni désactivé globalement par cette méthode."""
        current = self._current_phase()
        if current != AutopilotState.HUMAN_GATE_REQUIRED:
            raise HumanGateResolutionRefused(
                f"résolution refusée : phase courante {current.value!r}, pas HUMAN_GATE_REQUIRED "
                "— jamais appliquée hors de cet état."
            )
        if resume_to not in ALLOWED_TRANSITIONS.get(AutopilotState.HUMAN_GATE_REQUIRED, ()):
            raise HumanGateResolutionRefused(
                f"résolution refusée : cible {resume_to.value!r} non autorisée depuis "
                "HUMAN_GATE_REQUIRED."
            )
        record = self._current_record()
        mission = self._mission_by_id(record.mission_id) if record is not None else None
        if mission is None:
            raise HumanGateResolutionRefused(
                f"résolution refusée : mission {(record.mission_id if record else None)!r} "
                "introuvable dans la file — jamais résolu à l'aveugle sans pouvoir vérifier son "
                "scope déclaré."
            )
        dirty = self._git_ops.dirty_paths()
        unattributable = _unattributable_paths(dirty, mission.allowed_paths)
        if unattributable:
            raise HumanGateResolutionRefused(
                f"résolution refusée : modification(s) non attribuables au scope déclaré de "
                f"{mission.id} ({sorted(mission.allowed_paths)}) détectée(s) dans le worktree : "
                f"{unattributable} — jamais résolu tant qu'elles ne sont pas identifiées "
                "(étrangères ou hors scope) ; requires_clean_worktree n'est jamais désactivé."
            )
        return self._transition(
            resume_to,
            stop_reason=(
                f"HUMAN_GATE_REQUIRED résolu — cause opérationnelle corrigée : "
                f"{operational_cause_resolved}. Reprise vers {resume_to.value}, tout finding "
                "scientifique non résolu préservé tel quel."
            ),
            blocked_reason_category=None,
            # Finalisation reprise — bug réel confirmé par la revue indépendante de cette
            # mission : sans ceci, `attempt_count`/`diagnostic_attempted` restaient à leur valeur
            # DÉJÀ ÉPUISÉE d'avant la correction (ex. 5 tentatives, diagnostic déjà tenté) — un
            # SEUL échec suivant sur la phase reprise, même transitoire et sans le moindre rapport
            # avec la cause opérationnelle désormais corrigée, réescaladait IMMÉDIATEMENT vers
            # HUMAN_GATE_REQUIRED sans la moindre retentative réelle. La phase reprise mérite un
            # budget de tentatives authentiquement frais — jamais hérité de la séquence épuisée
            # qui a précédé la correction (les findings scientifiques, eux, restent intouchés :
            # `pending_findings` n'apparaît jamais dans ces `updates`).
            attempt_count=0, diagnostic_attempted=False,
        )

    # ── Échecs / diagnostic / escalade (mission §7/§8/§13) ───────────────────────────────────

    def _handle_failure(
        self, result: dict, attempt: int, mission: Optional[Mission] = None,
        retry_target: Optional[AutopilotState] = None,
    ) -> AutopilotState:
        # `developer_fn` renvoie `raw_output` ; `tester_fn`/`reviewer_fn` ne renvoient que
        # `summary` (contrat documenté en tête de module) — sans repli, une classification sur ""
        # masquait TOUJOURS NETWORK/QUOTA_LIMIT pour ces échecs (trouvé par la revue safety/
        # architecture du Bootstrap, empiriquement reproduit). Repli sur `summary`.
        raw_output = result.get("raw_output") or result.get("summary") or ""
        category = classify_failure(raw_output)
        signature = raw_output.strip()[:200]
        current_phase_value = self._current_phase().value
        record_before = self._current_record()
        # Finalisation sécurité (point 4.1) : les findings ORIGINAUX que CORRECTING existe pour
        # résoudre ne doivent jamais être perdus par un échec ultérieur SANS RAPPORT (ex.
        # `developer_fn` en erreur technique transitoire PENDANT CORRECTING lui-même) — distingués
        # ici des notes de constat d'échec déjà ajoutées à une tentative précédente (préfixées),
        # jamais réinjectées telles quelles ni dupliquées indéfiniment à chaque nouvel échec.
        prior_original_findings = tuple(
            f for f in (record_before.pending_findings if record_before is not None else ())
            if not f.startswith(_FAILURE_NOTE_PREFIX)
        )

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
        # V1.1 : `mission.max_attempts` est désormais RÉELLEMENT appliqué, pas seulement déclaré
        # dans le schéma (trouvé non câblé en préparant le lancement réel d'AF-V-02 Slice 2 — une
        # vraie mission scientifique, aux causes d'échec potentiellement toutes DIFFÉRENTES d'une
        # tentative à l'autre, jamais bornée par le seul mécanisme de signature identique répétée).
        max_attempts = mission.max_attempts if mission is not None else self._failure_limit
        attempts_exhausted = attempt >= max_attempts
        signature_repeated = git_safety.should_escalate(already_seen, signature, limit=self._failure_limit)
        if not signature_repeated and not attempts_exhausted:
            # Finalisation V1.1 (§2.C) : transmettre TOUJOURS l'échec comme retour exploitable pour
            # la prochaine invocation du Developer — jamais une retentative "à l'identique" sans
            # le moindre contexte sur ce qui a échoué (bug réel trouvé : un échec de TESTING
            # retentait auparavant TESTING seul, rappelant `tester_fn()` sans aucun changement de
            # code entre-temps, ce qui ne peut jamais corriger quoi que ce soit).
            new_note = f"{_FAILURE_NOTE_PREFIX}{raw_output.strip()[:2000]}"
            if retry_target is None and prior_original_findings:
                # Retentative EN PLACE (CORRECTING échoue sur lui-même, sans changer de phase) :
                # préserver le(s) finding(s) original(aux), jamais les remplacer par le seul
                # constat de CE nouvel échec (bug réel confirmé, finalisation sécurité point 4.1).
                feedback = prior_original_findings + (new_note,)
            else:
                feedback = (new_note,)
            if retry_target is not None:
                return self._transition(
                    retry_target, attempt_count=attempt, pending_findings=feedback,
                    stop_reason=f"tentative {attempt} échouée, transmise pour correction : {signature}",
                )
            return self._retry_in_place(
                attempt_count=attempt, pending_findings=feedback,
                stop_reason=f"tentative {attempt} échouée : {signature}",
            )

        # Mission §8 : "avant le Human Gate, lancer un diagnostic indépendant, tenter une autre
        # approche sûre, documenter les tentatives" — UNE seule fois par mission
        # (`diagnostic_attempted`), jamais une boucle supplémentaire non bornée. Universel, jamais
        # conditionné à `attempts_exhausted` : qu'on escalade par signature répétée ou par
        # `max_attempts` atteint, le diagnostic reste la même unique tentative "changer d'approche"
        # avant Human Gate — au prix d'UNE tentative de développeur de plus que `max_attempts` au
        # pire cas, un dépassement borné et assumé, jamais une boucle non bornée.
        record = self._current_record()
        if self._diagnostic_fn is not None and not record.diagnostic_attempted:
            diagnosis = self._diagnostic_fn(self._mission_by_id(record.mission_id), signature)
            notes = diagnosis.get("approach_notes", "(aucune note)") if isinstance(diagnosis, dict) else "(aucune note)"
            diagnostic_stop_reason = (
                f"échec répété ({self._failure_limit}x, signature identique) — diagnostic "
                f"indépendant tenté avant escalade : {notes}"
            )
            if retry_target is not None:
                # Finalisation sécurité (point 4.6) : bug réel confirmé — `retry_target` était
                # ignoré ici, retombant toujours sur une retentative EN PLACE. Pour une escalade
                # originant de TESTING (`retry_target=CORRECTING`), ceci laissait la phase à
                # TESTING : le prochain `run_one_step()` rappelait `tester_fn()` directement, SANS
                # repasser par le Developer — réintroduisant l'anti-pattern éliminé par le
                # correctif §2.C, pour ce seul cycle diagnostic. Transmet aussi le constat d'échec
                # ET la note de diagnostic comme retour exploitable pour cette invocation.
                new_note = f"{_FAILURE_NOTE_PREFIX}{raw_output.strip()[:2000]}"
                diag_note = f"Note de diagnostic (approche différente suggérée) : {notes}"
                feedback = prior_original_findings + (new_note, diag_note)
                return self._transition(
                    retry_target, attempt_count=attempt, diagnostic_attempted=True,
                    pending_findings=feedback, stop_reason=diagnostic_stop_reason,
                )
            return self._retry_in_place(
                attempt_count=attempt, diagnostic_attempted=True, stop_reason=diagnostic_stop_reason,
            )

        reason = (
            f"{attempt} tentative(s) — plafond `max_attempts={max_attempts}` de la mission atteint : {signature}"
            if attempts_exhausted else
            f"Échec identique {self._failure_limit} fois de suite : {signature}"
        )
        report = HumanGateReport(
            decision="Un même échec se répète — poursuivre nécessite un changement d'approche.",
            reason=reason,
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
