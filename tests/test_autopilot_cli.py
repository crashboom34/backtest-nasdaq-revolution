"""
tests/test_autopilot_cli.py — Autopilot V1.1 (2026-09-17), mission §3.1/§3.5/§3.6/§3.7/§14/§20.

Teste uniquement la logique pure (formatage du statut, dispatch de commande, garde
`RealGitOps`) — n'invoque jamais un vrai sous-processus `claude`/`git` ni ne démarre une vraie
boucle Autopilot contre le dépôt réel (les tests de boucle réelle utilisent des doublures pour
`subprocess.run`, jamais un accès réseau/disque réel)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.cli import RealGitOps, build_status_summary, main
from scripts.autopilot.state_machine import AutopilotState, AutopilotStateStore, build_state_record
from scripts.autopilot.supervisor import ForbiddenGitCommandError


def _fake_result(stdout="", returncode=0, stderr=""):
    class _Result:
        pass

    r = _Result()
    r.stdout = stdout
    r.returncode = returncode
    r.stderr = stderr
    return r


def test_status_summary_with_no_state_says_never_started(tmp_path):
    store = AutopilotStateStore(tmp_path / "state.json")
    summary = build_status_summary(store)
    assert "jamais démarré" in summary.lower() or "aucun état" in summary.lower()


def test_status_summary_reports_current_phase(tmp_path):
    store = AutopilotStateStore(tmp_path / "state.json")
    store.save(build_state_record(
        phase=AutopilotState.TESTING, mission_id="M1", branch="master", head="abc123",
        next_action="exécuter les tests",
    ))
    summary = build_status_summary(store)
    assert "TESTING" in summary
    assert "M1" in summary
    assert "abc123" in summary


def test_status_summary_surfaces_a_human_gate_reason_prominently(tmp_path):
    store = AutopilotStateStore(tmp_path / "state.json")
    store.save(build_state_record(
        phase=AutopilotState.HUMAN_GATE_REQUIRED, mission_id="M1", branch="master",
        stop_reason="# 🚦 HUMAN_GATE_REQUIRED\n\n## Décision\nX",
    ))
    summary = build_status_summary(store)
    assert "HUMAN_GATE_REQUIRED" in summary
    assert "Décision" in summary


def test_real_git_ops_rejects_a_forced_push_before_any_subprocess(tmp_path, monkeypatch):
    """La garde git_safety doit intercepter AVANT tout subprocess.run() réel — vérifié en faisant
    échouer le test si subprocess.run est jamais appelé pour une commande interdite."""
    import scripts.autopilot.cli as cli_module

    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run() ne doit jamais être appelé pour une commande interdite")

    monkeypatch.setattr(cli_module.subprocess, "run", _boom)
    git_ops = RealGitOps(repo_dir=tmp_path)

    with pytest.raises(ForbiddenGitCommandError):
        git_ops.push(force=True)


def test_real_git_ops_rejects_a_protected_path_in_scope(tmp_path, monkeypatch):
    import scripts.autopilot.cli as cli_module

    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run() ne doit jamais être appelé pour un scope protégé")

    monkeypatch.setattr(cli_module.subprocess, "run", _boom)
    git_ops = RealGitOps(repo_dir=tmp_path)

    with pytest.raises(ForbiddenGitCommandError):
        git_ops.add(["app_corrupted_backup.py"])


def test_real_git_ops_commit_rejects_a_protected_path_already_staged_outside_add(tmp_path, monkeypatch):
    """Régression — revue safety/architecture du Bootstrap (IMPORTANT 2) : `check_scope_files()`
    ne validait que les chemins passés à `add()`, jamais l'index Git réel au moment du commit — un
    contenu étranger/protégé déjà indexé (reprise après crash, `git add` humain laissé en cours)
    pouvait entrer dans un commit Autopilot sans jamais être détecté. `commit()` doit désormais
    relire l'index réel (`git diff --cached --name-only`) et le revalider avant de committer."""
    import scripts.autopilot.cli as cli_module

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "diff", "--cached", "--name-only"]:
            return _fake_result(stdout="app_corrupted_backup.py\n")
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path)

    with pytest.raises(ForbiddenGitCommandError):
        git_ops.commit("autopilot: test")


def test_real_git_ops_commit_rejects_a_secret_found_in_the_staged_diff(tmp_path, monkeypatch):
    """Mission Autopilot V1.1 §3.7 : secrets/gros fichiers doivent être contrôlés sur le CHEMIN
    D'EXÉCUTION RÉEL du commit, pas seulement via les fonctions pures isolées de `git_safety.py`."""
    import scripts.autopilot.cli as cli_module

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "diff", "--cached", "--name-only"]:
            return _fake_result(stdout="config.py\n")
        if argv == ["git", "diff", "--cached"]:
            return _fake_result(stdout='api_key = "AKIAABCDEFGHIJKLMNOP"\n')
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path)

    with pytest.raises(ForbiddenGitCommandError):
        git_ops.commit("autopilot: test")


def test_real_git_ops_commit_succeeds_when_staged_index_is_in_scope(tmp_path, monkeypatch):
    import scripts.autopilot.cli as cli_module

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        calls.append(argv)
        if argv == ["git", "diff", "--cached", "--name-only"]:
            return _fake_result(stdout="scripts/autopilot/cli.py\n")
        if argv == ["git", "diff", "--cached"]:
            return _fake_result(stdout="+ trivial change\n")
        if argv == ["git", "diff", "--cached", "--numstat"]:
            return _fake_result(stdout="")
        if argv == ["git", "rev-parse", "HEAD"]:
            return _fake_result(stdout="deadbeefcafe\n")
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path)

    sha = git_ops.commit("autopilot: test")

    assert any(c[:2] == ["git", "commit"] for c in calls)
    assert sha == "deadbeefcafe"


def test_real_git_ops_push_fetches_and_proceeds_when_origin_is_an_ancestor_of_head(tmp_path, monkeypatch):
    """Mission Autopilot V1.1 §3.7/§8 : `git fetch origin` doit avoir lieu avant tout push réel ;
    quand `origin/master` est un ancêtre de HEAD (avance normale, fast-forward), le push procède.
    Finalisation V1.1 §2.D : vérifie aussi que la branche courante est explicitement contrôlée et
    que le SHA distant final est revérifié après le push (pas seulement supposé réussi)."""
    import scripts.autopilot.cli as cli_module

    calls = []
    origin_rev_parse_calls = {"count": 0}

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        calls.append(argv)
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")
        if argv == ["git", "rev-parse", "origin/master"]:
            origin_rev_parse_calls["count"] += 1
            if origin_rev_parse_calls["count"] == 1:
                return _fake_result(stdout="oldsha\n")  # avant push : état distant connu
            return _fake_result(stdout="newsha\n")  # après push : le distant a bien avancé
        if argv == ["git", "rev-parse", "HEAD"]:
            return _fake_result(stdout="newsha\n")
        if argv == ["git", "merge-base", "--is-ancestor", "oldsha", "HEAD"]:
            return _fake_result(returncode=0)  # oldsha EST un ancêtre -> avance normale
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path, branch="master")

    pushed_sha = git_ops.push()

    assert ["git", "fetch", "origin"] in calls
    assert any(c[:2] == ["git", "push"] for c in calls)
    assert pushed_sha == "newsha"


def test_real_git_ops_push_uses_an_explicit_refspec_never_a_hardcoded_master(tmp_path, monkeypatch):
    """Régression — bug réel confirmé (mission finalisation V1.1 §2.D) : le code poussait
    inconditionnellement `git push origin master`, quelle que soit la branche RÉELLEMENT extraite
    dans le worktree — dangereux dès qu'un worktree dédié travaille sur une autre branche.
    `push()` doit désormais vérifier HEAD explicitement et utiliser un refspec `branche:cible`."""
    import scripts.autopilot.cli as cli_module

    calls = []
    origin_calls = {"count": 0}

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        calls.append(argv)
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="autopilot/permanent\n")
        if argv == ["git", "rev-parse", "origin/master"]:
            origin_calls["count"] += 1
            return _fake_result(stdout="oldsha\n" if origin_calls["count"] == 1 else "newsha\n")
        if argv == ["git", "rev-parse", "HEAD"]:
            return _fake_result(stdout="newsha\n")
        if argv == ["git", "merge-base", "--is-ancestor", "oldsha", "HEAD"]:
            return _fake_result(returncode=0)
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path, branch="autopilot/permanent", remote_ref="master")

    git_ops.push()

    push_calls = [c for c in calls if c[:2] == ["git", "push"]]
    assert push_calls == [["git", "push", "origin", "autopilot/permanent:master"]]


def test_real_git_ops_push_refuses_when_head_does_not_match_the_declared_branch(tmp_path, monkeypatch):
    """Régression — mission finalisation V1.1 §2.D : ne jamais pousser sans vérifier explicitement
    que HEAD correspond bien à la branche de travail déclarée."""
    import scripts.autopilot.cli as cli_module

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="some-other-branch\n")
        raise AssertionError("aucune autre commande Git ne doit être tentée après un mismatch de branche")

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path, branch="autopilot/permanent")

    with pytest.raises(RuntimeError, match="branche de travail inattendue"):
        git_ops.push()


def test_real_git_ops_push_refuses_on_real_divergence_never_forcing(tmp_path, monkeypatch):
    """Quand `origin/master` N'EST PAS un ancêtre de HEAD (divergence réelle — quelqu'un/quelque
    chose d'autre a poussé), le push doit être refusé (levée d'exception, jamais silencieux) et
    JAMAIS automatiquement forcé (mission §8 : "ne jamais forcer, diagnostiquer la divergence")."""
    import scripts.autopilot.cli as cli_module

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")
        if argv == ["git", "rev-parse", "origin/master"]:
            return _fake_result(stdout="othersha\n")
        if argv == ["git", "rev-parse", "HEAD"]:
            return _fake_result(stdout="mysha\n")
        if argv == ["git", "merge-base", "--is-ancestor", "othersha", "HEAD"]:
            return _fake_result(returncode=1)  # PAS un ancêtre -> vraie divergence
        if argv[:2] == ["git", "push"]:
            raise AssertionError("git push ne doit jamais être tenté en cas de divergence non comprise")
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    git_ops = RealGitOps(repo_dir=tmp_path)

    with pytest.raises(RuntimeError, match="divergence"):
        git_ops.push()


def test_run_readonly_git_routes_through_git_safety_before_any_subprocess(monkeypatch):
    """Régression — revue safety/architecture V1.1 : plusieurs commandes Git en lecture seule
    (`git status`, `git diff HEAD`, `git rev-parse`, `git merge-base --is-ancestor`) contournaient
    encore `git_safety.check_git_command()`, malgré la promesse documentée du module. Aucune
    n'est aujourd'hui sur liste noire, mais toute commande Git doit passer par ce garde sans
    exception — testé ici avec un argv volontairement interdit pour le prouver."""
    import scripts.autopilot.cli as cli_module

    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run() ne doit jamais être appelé pour une commande interdite")

    monkeypatch.setattr(cli_module.subprocess, "run", _boom)

    with pytest.raises(cli_module.ForbiddenGitCommandError):
        cli_module._run_readonly_git(["git", "reset", "--hard"])


def test_run_readonly_git_passes_a_timeout_to_subprocess(monkeypatch):
    import scripts.autopilot.cli as cli_module

    seen_kwargs = {}

    def fake_run(argv, **kwargs):
        seen_kwargs.update(kwargs)
        return _fake_result(stdout="")

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    cli_module._run_readonly_git(["git", "status", "--porcelain"])

    assert seen_kwargs.get("timeout") == cli_module.GIT_TIMEOUT_SECONDS


def test_real_tester_fn_pytest_timeout_never_raises_and_is_classified_as_a_failure(monkeypatch):
    """Régression — revue safety/architecture V1.1 : un `pytest` bloqué devait être borné et ne
    jamais laisser `subprocess.TimeoutExpired` s'échapper hors de `real_tester_fn` (contrat :
    toujours un dict, jamais une exception non rattrapée hors de `run_one_step()`)."""
    import subprocess

    import scripts.autopilot.cli as cli_module

    def fake_run(argv, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        assert kwargs.get("timeout") == cli_module.PYTEST_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs["timeout"])

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()

    result = supervisor._tester_fn(None)

    assert result["success"] is False
    assert "timeout" in result["summary"].lower()


def test_real_tester_fn_runs_the_full_suite_when_mission_is_none(monkeypatch):
    """Régression — trouvé non testé par la revue reproductibilité/scope V1.1 : les 4 branches de
    `real_tester_fn` (mission absente, targeted_tests vide, targeted en échec, targeted en succès
    + risque élevé) n'avaient aucune couverture dédiée alors que cette fonction décide si la
    régression complète tourne avant un commit/push réel."""
    import scripts.autopilot.cli as cli_module

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        calls.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()

    result = supervisor._tester_fn(None)

    assert result["success"] is True
    assert len(calls) == 1  # une seule commande : la suite complète, aucun ciblage possible


def test_real_tester_fn_runs_the_full_suite_when_targeted_tests_is_empty(monkeypatch):
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        calls.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(id="M1", title="x", status="PLANNED", prompt_file="m1.md", targeted_tests=())

    result = supervisor._tester_fn(mission)

    assert result["success"] is True
    assert len(calls) == 1


def test_real_tester_fn_stops_immediately_when_targeted_tests_fail(monkeypatch):
    """Échec rapide (mission §5) : jamais de suite complète lancée après un échec ciblé."""
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        calls.append(argv)
        return _fake_result(stdout="1 failed", returncode=1)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(
        id="M1", title="x", status="PLANNED", prompt_file="m1.md",
        targeted_tests=("tests/test_x.py",), risk_level="low",
    )

    result = supervisor._tester_fn(mission)

    assert result["success"] is False
    assert len(calls) == 1  # jamais la suite complète après un échec ciblé


def test_real_tester_fn_reruns_full_suite_for_high_risk_missions_even_after_targeted_pass(monkeypatch):
    """Mission §5 : régression complète imposée pour une mission à risque élevé, même si les
    tests ciblés passent déjà."""
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        calls.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(
        id="M1", title="x", status="PLANNED", prompt_file="m1.md",
        targeted_tests=("tests/test_x.py",), risk_level="high",
    )

    result = supervisor._tester_fn(mission)

    assert result["success"] is True
    assert len(calls) == 2  # ciblé d'abord, PUIS la suite complète imposée par le risque élevé


def test_real_tester_fn_reruns_full_suite_when_scientific_contracts_declared(monkeypatch):
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        calls.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(
        id="M1", title="x", status="PLANNED", prompt_file="m1.md",
        targeted_tests=("tests/test_x.py",), risk_level="low",
        scientific_contracts=("ADR-0021",),
    )

    result = supervisor._tester_fn(mission)

    assert result["success"] is True
    assert len(calls) == 2


def test_real_tester_fn_skips_full_suite_for_low_risk_mission_with_no_scientific_contracts(monkeypatch):
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    calls = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        calls.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(
        id="M1", title="x", status="PLANNED", prompt_file="m1.md",
        targeted_tests=("tests/test_x.py",), risk_level="low",
    )

    result = supervisor._tester_fn(mission)

    assert result["success"] is True
    assert len(calls) == 1  # ciblé suffit, jamais la suite complète pour ce cas


def _fake_claude_json(verdict="CLEAN", findings=None, is_error=False, session_id="sess-1"):
    import json as _json

    return _json.dumps({
        "is_error": is_error, "session_id": session_id,
        "structured_output": {"verdict": verdict, "findings": findings or []},
    })


def test_real_reviewer_fn_covers_a_new_untracked_file_via_intent_to_add(monkeypatch):
    """Régression — bug réel confirmé (mission finalisation V1.1 §2.B) : `git diff HEAD` seul
    n'affiche RIEN pour un fichier jamais suivi — un NOUVEAU fichier créé par le Developer était
    invisible au Reviewer. `git add --intent-to-add` doit le rendre visible sans le committer."""
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")
        if argv == ["git", "status", "--porcelain"]:
            return _fake_result(stdout="?? new_file.py\n")
        if argv[:3] == ["git", "ls-files", "--error-unmatch"]:
            return _fake_result(returncode=1)  # non suivi
        if "--intent-to-add" in argv:
            return _fake_result()
        if argv == ["git", "diff", "HEAD", "--", "new_file.py"]:
            return _fake_result(stdout="+++ b/new_file.py\n+contenu du nouveau fichier\n")
        if argv[0] == "claude":
            return _fake_result(stdout=_fake_claude_json())
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(id="M1", title="x", status="PLANNED", prompt_file="m1.md")

    result = supervisor._reviewer_fn(mission)

    assert result["success"] is True
    assert result["reviewed_files"] == ["new_file.py"]
    assert any("--intent-to-add" in c for c in calls)


def test_real_reviewer_fn_splits_a_large_diff_into_multiple_batches_and_aggregates_findings(monkeypatch):
    """Régression — bug réel confirmé (mission finalisation V1.1 §2.B) : le diff total était
    tronqué silencieusement à 20000 caractères — un gros diff pouvait être partiellement invisible
    au Reviewer. Doit désormais être découpé en lots bornés, chacun revu séparément, avec les
    findings de TOUS les lots agrégés."""
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    claude_calls = {"count": 0}

    def fake_run(argv, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")
        if argv == ["git", "status", "--porcelain"]:
            return _fake_result(stdout=" M big_file_a.py\n M big_file_b.py\n")
        if argv[:3] == ["git", "ls-files", "--error-unmatch"]:
            return _fake_result(returncode=0)  # déjà suivis
        if argv == ["git", "diff", "HEAD", "--", "big_file_a.py"]:
            return _fake_result(stdout="+x\n" * 6000)  # gros diff, dépasse le budget à lui seul
        if argv == ["git", "diff", "HEAD", "--", "big_file_b.py"]:
            return _fake_result(stdout="+y\n" * 6000)
        if argv[0] == "claude":
            claude_calls["count"] += 1
            # Le 1er lot rapporte 1 finding MINOR, le 2e rapporte 1 finding BLOCKER.
            if claude_calls["count"] == 1:
                return _fake_result(stdout=_fake_claude_json(
                    verdict="FINDINGS", findings=[{"severity": "MINOR", "summary": "style"}],
                ))
            return _fake_result(stdout=_fake_claude_json(
                verdict="FINDINGS", findings=[{"severity": "BLOCKER", "summary": "bug réel"}],
            ))
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(id="M1", title="x", status="PLANNED", prompt_file="m1.md")

    result = supervisor._reviewer_fn(mission)

    assert result["success"] is True
    assert claude_calls["count"] == 2  # deux lots, deux appels Reviewer distincts
    assert len(result["blocking_findings"]) == 1
    assert result["blocking_findings"][0]["severity"] == "BLOCKER"
    assert set(result["reviewed_files"]) == {"big_file_a.py", "big_file_b.py"}


def test_real_reviewer_fn_fails_when_a_changed_file_is_never_actually_covered(monkeypatch):
    """Mission finalisation V1.1 §2.B : "vérifier explicitement la couverture complète" — si un
    fichier annoncé comme modifié n'a jamais pu être diffusé (cas limite), la review doit échouer
    plutôt que de se déclarer silencieusement complète."""
    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission

    def fake_run(argv, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")
        if argv == ["git", "status", "--porcelain"]:
            return _fake_result(stdout=" M covered.py\n M never_diffed.py\n")
        if argv[:3] == ["git", "ls-files", "--error-unmatch"]:
            return _fake_result(returncode=0)
        if argv == ["git", "diff", "HEAD", "--", "covered.py"]:
            return _fake_result(stdout="+un vrai diff\n")
        if argv == ["git", "diff", "HEAD", "--", "never_diffed.py"]:
            return _fake_result(stdout="")  # rien produit -> jamais couvert
        if argv[0] == "claude":
            return _fake_result(stdout=_fake_claude_json())
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()
    mission = Mission(id="M1", title="x", status="PLANNED", prompt_file="m1.md")

    result = supervisor._reviewer_fn(mission)

    assert result["success"] is False
    assert "never_diffed.py" in result["raw_output"]


def test_stage_intent_to_add_in_temp_index_never_touches_the_real_index(tmp_path):
    """Finalisation sécurité (point 4.5) : bug réel confirmé — l'ancien `_stage_intent_to_add()`
    posait son `git add --intent-to-add` sur l'INDEX RÉEL (`.git/index`) sans AUCUN mécanisme de
    nettoyage ; une mission qui n'atteint jamais COMMITTING (ex. escalade vers Human Gate) laissait
    ces entrées en place indéfiniment, pouvant rendre `dirty_worktree` non résoluble pour toujours
    (le contraire exact de ce que le correctif finalisation V1.1 §2.E promet). Doit désormais
    utiliser un INDEX TEMPORAIRE (`GIT_INDEX_FILE`), jamais l'index réel — vérifié ici avec un VRAI
    dépôt Git, pas une simulation."""
    import shutil
    import subprocess

    import scripts.autopilot.cli as cli_module

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "tracked.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    (repo / "brand_new.py").write_text("y = 1\n", encoding="utf-8")
    status_before = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True,
    ).stdout
    assert status_before.strip() == "?? brand_new.py"

    tmp_index = cli_module._stage_intent_to_add_in_temp_index(["brand_new.py"], repo_dir=repo)
    try:
        diff_text = cli_module._diff_for_file("brand_new.py", repo_dir=repo, index_file=tmp_index)
        assert "y = 1" in diff_text  # le contenu réel du nouveau fichier est bien visible au diff

        status_during = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True,
        ).stdout
        # L'INDEX RÉEL doit rester STRICTEMENT inchangé PENDANT la review — le fichier reste non
        # suivi ("??"), jamais promu en staged ("A ") comme le ferait un intent-to-add réel.
        assert status_during.strip() == "?? brand_new.py"
    finally:
        if tmp_index is not None:
            shutil.rmtree(tmp_index.parent, ignore_errors=True)

    status_after = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True,
    ).stdout
    assert status_after.strip() == "?? brand_new.py"


def test_stage_intent_to_add_in_temp_index_raises_and_cleans_up_when_read_tree_fails(tmp_path, monkeypatch):
    """Régression — bug réel confirmé par la revue indépendante (finalisation sécurité, fix 5) :
    le code de retour de `git read-tree HEAD` n'était jamais vérifié. Sur un HEAD invalide (dépôt
    sans aucun commit, cas réel reproduit), l'index temporaire restait silencieusement SOUS-SEEDÉ
    plutôt que peuplé depuis HEAD — un fichier déjà suivi et modifié apparaissait alors au diff
    comme une SUPPRESSION COMPLÈTE plutôt que sa vraie modification, une review fondée sur un diff
    fabriqué. Doit désormais lever bruyamment (jamais un index partiellement initialisé retourné
    comme si de rien n'était) ET nettoyer son propre répertoire temporaire avant de lever — jamais
    un répertoire créé puis abandonné sur disque si l'initialisation échoue en cours de route."""
    import subprocess as real_subprocess
    import tempfile as real_tempfile

    import scripts.autopilot.cli as cli_module

    repo = tmp_path / "repo"
    repo.mkdir()
    real_subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "brand_new.py").write_text("y = 1\n", encoding="utf-8")
    # Aucun commit -> HEAD n'existe pas -> `git read-tree HEAD` échoue nécessairement.

    created_dirs = []
    real_mkdtemp = real_tempfile.mkdtemp

    def recording_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        created_dirs.append(path)
        return path

    monkeypatch.setattr(cli_module.tempfile, "mkdtemp", recording_mkdtemp)

    with pytest.raises(RuntimeError):
        cli_module._stage_intent_to_add_in_temp_index(["brand_new.py"], repo_dir=repo)

    assert len(created_dirs) == 1
    assert not os.path.exists(created_dirs[0])  # jamais laissé en place après un échec interne


def test_real_tester_fn_invokes_sys_executable_not_a_hardcoded_relative_venv_path(monkeypatch):
    """Régression — trouvé RÉELLEMENT cassé par le canary V1.1 (mission §9) : un chemin relatif
    codé en dur (".venv/Scripts/python.exe") échoue (`FileNotFoundError`/`WinError 2`) dans tout
    déploiement qui n'a pas son PROPRE `.venv/` local sous `REPO_ROOT` — ex. le worktree isolé
    `autopilot/v1-1-operational` de cette mission, qui réutilise délibérément l'interpréteur du
    dépôt principal. `sys.executable` doit être utilisé à la place, toujours correct."""
    import scripts.autopilot.cli as cli_module

    seen_argv = []

    def fake_run(argv, cwd, capture_output, text, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")  # détection de branche à la construction
        seen_argv.append(argv)
        return _fake_result(stdout="1 passed", returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    supervisor = cli_module._build_real_supervisor()

    supervisor._tester_fn(None)

    assert seen_argv, "aucun subprocess.run() n'a été appelé"
    assert seen_argv[0][0] == cli_module.sys.executable
    assert ".venv/Scripts/python.exe" not in seen_argv[0]


def test_git_common_dir_resolves_to_the_same_absolute_path_from_a_linked_worktree(tmp_path):
    """Régression — bug réel confirmé (mission finalisation V1.1 §3) : `LOCK_PATH`/
    `STOP_SIGNAL_PATH` dérivaient de `.autopilot/state/`, propre à CHAQUE worktree (gitignoré) —
    deux superviseurs lancés depuis deux worktrees différents avaient chacun leur propre fichier
    de verrou, invisibles l'un à l'autre. `_git_common_dir()` doit résoudre vers le MÊME chemin
    absolu qu'on l'appelle depuis le dépôt principal ou depuis un worktree lié — testé avec un
    VRAI dépôt Git et un VRAI worktree, pas une simulation."""
    import subprocess

    import scripts.autopilot.cli as cli_module

    main_repo = tmp_path / "main"
    main_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=main_repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=main_repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=main_repo, check=True)
    (main_repo / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=main_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=main_repo, check=True)

    linked_worktree = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "-b", "other-branch", str(linked_worktree)],
        cwd=main_repo, check=True, capture_output=True, text=True,
    )

    from_main = cli_module._git_common_dir(main_repo)
    from_linked = cli_module._git_common_dir(linked_worktree)

    assert from_main == from_linked
    assert from_main == (main_repo / ".git").resolve()


def test_git_common_dir_never_crashes_when_the_git_binary_is_unavailable_and_still_matches_across_worktrees(
    tmp_path, monkeypatch,
):
    """Finalisation sécurité (point 4.3) : bug réel confirmé — `_git_common_dir()` ne rattrapait
    qu'un `returncode != 0`, jamais une exception (`git` absent du PATH, `FileNotFoundError`...).
    Comme `LOCK_PATH`/`STOP_SIGNAL_PATH` sont calculés à l'IMPORT du module, une telle exception
    rendait `import scripts.autopilot.cli` impossible — même `autopilot stop` devenait inutilisable
    exactement quand il serait le plus utile. Le repli doit aussi rester SÛR (jamais un verrou
    ALTERNATIF différent selon le worktree) : recalculé par lecture directe de la structure `.git`,
    jamais un `repo_dir / ".git"` brut (qui serait un FICHIER de redirection dans un worktree lié,
    pas le répertoire commun réel)."""
    import subprocess

    import scripts.autopilot.cli as cli_module

    main_repo = tmp_path / "main"
    main_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=main_repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=main_repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=main_repo, check=True)
    (main_repo / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=main_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=main_repo, check=True)

    linked_worktree = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "-b", "other-branch2", str(linked_worktree)],
        cwd=main_repo, check=True, capture_output=True, text=True,
    )

    def raise_git_missing(*args, **kwargs):
        raise FileNotFoundError("[WinError 2] git introuvable sur le PATH")

    monkeypatch.setattr(cli_module.subprocess, "run", raise_git_missing)

    from_main = cli_module._git_common_dir(main_repo)  # ne doit JAMAIS lever
    from_linked = cli_module._git_common_dir(linked_worktree)

    assert from_main == from_linked  # jamais un verrou différent d'un worktree à l'autre
    assert from_main == (main_repo / ".git").resolve()


def test_real_git_ops_is_worktree_clean_reflects_git_status_porcelain(tmp_path, monkeypatch):
    """Régression — mission Autopilot V1.1 §4 : `mission.requires_clean_worktree` était déclaré
    dans le schéma mais jamais réellement câblé à une vérification Git réelle avant cette mission."""
    import scripts.autopilot.cli as cli_module

    def fake_run_clean(argv, cwd, capture_output, text, **kwargs):
        return _fake_result(stdout="")

    def fake_run_dirty(argv, cwd, capture_output, text, **kwargs):
        return _fake_result(stdout=" M some_file.py\n")

    git_ops = RealGitOps(repo_dir=tmp_path)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run_clean)
    assert git_ops.is_worktree_clean() is True

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run_dirty)
    assert git_ops.is_worktree_clean() is False


def test_record_real_git_context_fills_head_and_origin_master(tmp_path, monkeypatch):
    """Régression — mission §6 : `head`/`origin_master` sont des champs d'audit requis, mais
    restaient toujours `(inconnu)` (`None`) tout au long du canary V1.1 réel — jamais renseignés
    nulle part sur le chemin réel avant ce correctif."""
    import scripts.autopilot.cli as cli_module

    def fake_run(argv, cwd=None, capture_output=None, text=None, **kwargs):
        if argv == ["git", "rev-parse", "HEAD"]:
            return _fake_result(stdout="realhead123\n")
        if argv == ["git", "rev-parse", "origin/master"]:
            return _fake_result(stdout="realorigin456\n")
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    store = AutopilotStateStore(tmp_path / "state.json")
    store.save(build_state_record(phase=AutopilotState.READY, mission_id=None, branch="master"))

    cli_module._record_real_git_context(store)

    record = store.load()
    assert record.head == "realhead123"
    assert record.origin_master == "realorigin456"


def test_record_real_git_context_never_raises_when_no_state_exists(tmp_path):
    import scripts.autopilot.cli as cli_module

    store = AutopilotStateStore(tmp_path / "state.json")
    cli_module._record_real_git_context(store)  # ne doit jamais lever, même sans état existant

    assert store.load() is None


def test_main_status_command_returns_zero(tmp_path, monkeypatch, capsys):
    import scripts.autopilot.cli as cli_module

    monkeypatch.setattr(cli_module, "STATE_PATH", tmp_path / "state.json")
    exit_code = main(["status"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "état" in captured.out.lower() or "démarré" in captured.out.lower()


def test_main_stop_command_cleans_an_orphaned_lock_and_returns_zero(tmp_path, monkeypatch, capsys):
    """Régression — finalisation V1.1 §2.A : ce test écrivait auparavant un verrou au contenu
    illisible ("locked", pas du JSON) et attendait qu'il soit TOUJOURS supprimé — c'était
    exactement le comportement buggé (`force_release()` inconditionnel). Un contenu illisible est
    désormais traité prudemment comme "peut-être détenu" (jamais volé) — ce test écrit donc un
    verrou explicitement ORPHELIN (PID mort) pour vérifier que ce cas reste bien nettoyé."""
    import json as _json

    import scripts.autopilot.cli as cli_module

    monkeypatch.setattr(cli_module, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(cli_module, "LOCK_PATH", tmp_path / "autopilot.lock")
    monkeypatch.setattr(cli_module, "STOP_SIGNAL_PATH", tmp_path / "stop.signal")
    (tmp_path / "autopilot.lock").write_text(
        _json.dumps({"pid": 2147483647, "acquired_at_utc": "x", "worktree": "x"}), encoding="utf-8",
    )

    exit_code = main(["stop"])
    assert exit_code == 0
    assert not (tmp_path / "autopilot.lock").exists()
    assert (tmp_path / "stop.signal").exists()  # signal coopératif déposé (mission §3.6)


def test_main_stop_command_never_removes_a_lock_with_unreadable_content(tmp_path, monkeypatch):
    """Complète le test précédent : un contenu de verrou illisible (jamais du JSON valide) doit
    être traité prudemment comme "peut-être détenu par un process vivant" — jamais supprimé par
    doute, cohérent avec `_pid_is_alive`/`is_held_by_a_live_process()`."""
    import scripts.autopilot.cli as cli_module

    monkeypatch.setattr(cli_module, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(cli_module, "LOCK_PATH", tmp_path / "autopilot.lock")
    monkeypatch.setattr(cli_module, "STOP_SIGNAL_PATH", tmp_path / "stop.signal")
    (tmp_path / "autopilot.lock").write_text("locked", encoding="utf-8")

    exit_code = main(["stop"])
    assert exit_code == 0
    assert (tmp_path / "autopilot.lock").exists()  # jamais supprimé par doute


def test_ensure_utf8_stdio_never_crashes_when_printing_non_cp1252_characters():
    """Régression — bug réel confirmé en conditions réelles (reprise d'AF-V-02 Slice 2 après
    l'arrêt coopératif) : le vrai travail (verrou libéré, état HUMAN_GATE_REQUIRED persisté)
    s'était terminé correctement, mais le DERNIER `print(build_status_summary(store))` a ensuite
    levé `UnicodeEncodeError: 'charmap' codec can't encode character '\\U0001f6a6'` — le
    `stop_reason` d'un Human Gate contient un emoji (`format_human_gate_markdown()`), et la
    console Windows par défaut encode en `cp1252`, incapable de le représenter. Ceci a fait
    ressortir le process avec le code de sortie GÉNÉRIQUE 1 (crash Python) au lieu du VRAI code 2
    (HUMAN_GATE_REQUIRED), masquant l'information réelle. `_ensure_utf8_stdio()` doit rendre
    `sys.stdout`/`sys.stderr` capables d'imprimer n'importe quel caractère sans jamais lever."""
    import io

    import scripts.autopilot.cli as cli_module

    fake_stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", write_through=True)
    original_stdout = sys.stdout
    sys.stdout = fake_stdout
    try:
        cli_module._ensure_utf8_stdio()
        print("# 🚦 HUMAN_GATE_REQUIRED\n\nTexte accentué : éàî, ✅ option recommandée")
    finally:
        sys.stdout = original_stdout


def test_ensure_utf8_stdio_tolerates_a_stream_without_reconfigure():
    """Un flux redirigé/capturé (ex. par un test, ou une redirection shell inhabituelle) peut ne
    pas exposer `.reconfigure()` — ne doit jamais faire planter l'appelant pour cette raison."""
    import scripts.autopilot.cli as cli_module

    class _StreamWithoutReconfigure:
        def write(self, s):
            pass

        def flush(self):
            pass

    original_stdout = sys.stdout
    sys.stdout = _StreamWithoutReconfigure()
    try:
        cli_module._ensure_utf8_stdio()  # ne doit JAMAIS lever AttributeError
    finally:
        sys.stdout = original_stdout


def test_main_rejects_an_unknown_command():
    with pytest.raises(SystemExit):
        main(["this-command-does-not-exist"])


def test_cmd_resolve_human_gate_resumes_a_real_supervisor_past_an_operational_human_gate(tmp_path, monkeypatch):
    """Finalisation reprise (2026-09-18) : `autopilot resolve-human-gate --resume-to REVIEWING
    --note "..."` doit reprendre RÉELLEMENT (via `_build_real_supervisor()`, jamais une doublure)
    un `HUMAN_GATE_REQUIRED` dont la cause opérationnelle est corrigée, en reconnaissant le
    travail non commité (`git status --porcelain`) comme attribuable au scope déclaré de la
    mission persistée — jamais en rééditant `current_state.json` à la main."""
    import argparse

    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission, save_missions
    from scripts.autopilot.state_machine import AutopilotState, AutopilotStateRecord, AutopilotStateStore

    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(id="M1", title="x", status="PLANNED", prompt_file="m1.md", allowed_paths=("optimizer.py",)),
    ])
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(cli_module, "STATE_PATH", state_path)
    monkeypatch.setattr(cli_module, "MISSIONS_PATH", missions_path)
    monkeypatch.setattr(cli_module, "LOCK_PATH", tmp_path / "autopilot.lock")
    monkeypatch.setattr(cli_module, "STOP_SIGNAL_PATH", tmp_path / "stop.signal")
    monkeypatch.setattr(cli_module, "AUTOPILOT_DIR", tmp_path)
    (tmp_path / "m1.md").write_text("prompt factice", encoding="utf-8")

    store = AutopilotStateStore(state_path)
    store.save(AutopilotStateRecord(phase=AutopilotState.HUMAN_GATE_REQUIRED.value, mission_id="M1"))

    def fake_run(argv, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")
        if argv == ["git", "status", "--porcelain"]:
            return _fake_result(stdout=" M optimizer.py\n")  # attribuable au scope déclaré de M1
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    exit_code = cli_module.cmd_resolve_human_gate(
        argparse.Namespace(resume_to="REVIEWING", note="prompt claude -p transmis par stdin")
    )

    assert exit_code == 0
    reloaded = store.load()
    assert reloaded.phase == AutopilotState.REVIEWING.value
    assert not tmp_path.joinpath("autopilot.lock").exists()  # libéré après la résolution


def test_cmd_resolve_human_gate_returns_nonzero_and_never_transitions_on_foreign_changes(tmp_path, monkeypatch):
    """Symétrique : une modification hors scope ne doit jamais être résolue, même via la vraie
    commande CLI — code de sortie non nul, état laissé strictement inchangé."""
    import argparse

    import scripts.autopilot.cli as cli_module
    from scripts.autopilot.mission_queue import Mission, save_missions
    from scripts.autopilot.state_machine import AutopilotState, AutopilotStateRecord, AutopilotStateStore

    missions_path = tmp_path / "missions.json"
    save_missions(missions_path, [
        Mission(id="M1", title="x", status="PLANNED", prompt_file="m1.md", allowed_paths=("optimizer.py",)),
    ])
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(cli_module, "STATE_PATH", state_path)
    monkeypatch.setattr(cli_module, "MISSIONS_PATH", missions_path)
    monkeypatch.setattr(cli_module, "LOCK_PATH", tmp_path / "autopilot.lock")
    monkeypatch.setattr(cli_module, "STOP_SIGNAL_PATH", tmp_path / "stop.signal")
    monkeypatch.setattr(cli_module, "AUTOPILOT_DIR", tmp_path)
    (tmp_path / "m1.md").write_text("prompt factice", encoding="utf-8")

    store = AutopilotStateStore(state_path)
    store.save(AutopilotStateRecord(phase=AutopilotState.HUMAN_GATE_REQUIRED.value, mission_id="M1"))

    def fake_run(argv, **kwargs):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return _fake_result(stdout="master\n")
        if argv == ["git", "status", "--porcelain"]:
            return _fake_result(stdout=" M optimizer.py\n M AGENTS.md\n")  # AGENTS.md hors scope
        return _fake_result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    exit_code = cli_module.cmd_resolve_human_gate(
        argparse.Namespace(resume_to="REVIEWING", note="peu importe")
    )

    assert exit_code == 1
    assert store.load().phase == AutopilotState.HUMAN_GATE_REQUIRED.value
