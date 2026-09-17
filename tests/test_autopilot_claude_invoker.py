"""
tests/test_autopilot_claude_invoker.py — Bootstrap Autopilot V1 (2026-09-17), mission §2/§13.

`ClaudeInvoker` construit l'argv réel (uniquement des flags confirmés par `claude --help` sur la
version installée, 2.1.220 — jamais un flag supposé) et classe l'échec via `quota_detector` sans
jamais réellement lancer de sous-processus dans ces tests (fonction `run_fn` injectée).

**Finalisation sécurité (2026-09-17)** : le prompt n'est plus JAMAIS un élément de `argv` — bug
réel confirmé en conditions réelles sur AF-V-02 Slice 2, un `claude -p` réel a échoué sur Windows
avec `FileNotFoundError: [WinError 206] Nom de fichier ou extension trop long` dès qu'un lot de
diff de review dépassait la limite de longueur de ligne de commande de `CreateProcess`. Le prompt
est désormais transmis en second argument positionnel à `run_fn` (STDIN pour `_real_run()`,
confirmé empiriquement que `claude -p` lit le prompt depuis STDIN en l'absence d'argument
positionnel)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.claude_invoker import ClaudeInvoker, build_claude_argv
from scripts.autopilot.quota_detector import FailureCategory


def test_real_run_converts_a_subprocess_timeout_into_a_graceful_failure(monkeypatch):
    """Régression — revue safety/architecture V1.1 : aucun sous-processus réel n'avait de
    `timeout=`, rendant le signal d'arrêt coopératif sans effet pratique pendant un `claude -p`
    bloqué. `_real_run()` doit désormais borner l'appel ET ne jamais laisser
    `subprocess.TimeoutExpired` s'échapper (contrat : toujours un tuple, jamais une exception)."""
    import subprocess

    import scripts.autopilot.claude_invoker as invoker_module

    def fake_run(argv, **kwargs):
        assert kwargs.get("timeout") == invoker_module.CLAUDE_SUBPROCESS_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs["timeout"], output="partial", stderr="partial-err")

    monkeypatch.setattr(subprocess, "run", fake_run)

    exit_code, stdout, stderr = invoker_module._real_run(["claude", "-p"], "x")

    assert exit_code == 1
    assert "timeout" in stderr.lower()


def test_claude_invoker_passes_an_explicit_cwd_through_to_real_run(monkeypatch):
    """Finalisation V1.1 §3 : le répertoire de travail d'un appel `claude -p` réel doit être
    EXPLICITE, jamais hérité implicitement du process Autopilot lui-même — un worktree dédié
    invoqué depuis un mauvais répertoire de travail modifierait/lirait le mauvais dépôt."""
    import subprocess

    import scripts.autopilot.claude_invoker as invoker_module

    seen_kwargs = {}

    class _FakeCompleted:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(argv, **kwargs):
        seen_kwargs.update(kwargs)
        return _FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    invoker = invoker_module.ClaudeInvoker(cwd="C:/some/dedicated/worktree")

    invoker.run("x")

    assert seen_kwargs.get("cwd") == "C:/some/dedicated/worktree"


def test_claude_invoker_without_cwd_calls_run_fn_with_argv_and_prompt_as_separate_args():
    """Finalisation sécurité : sans `cwd` (défaut `None`), `run_fn` reçoit `argv` et `prompt`
    comme deux arguments positionnels SÉPARÉS — jamais le prompt concaténé dans `argv` (bug réel
    confirmé sur AF-V-02 Slice 2, voir docstring du module)."""
    seen = {}

    def fake_run(argv, prompt):
        seen["argv"] = argv
        seen["prompt"] = prompt
        return 0, "{}", ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    invoker.run("x")

    assert "x" not in seen["argv"]
    assert seen["prompt"] == "x"


def test_a_very_large_prompt_is_never_embedded_in_argv():
    """Régression — bug réel confirmé en conditions réelles (AF-V-02 Slice 2, review d'un gros
    diff) : le prompt était auparavant ajouté comme DERNIER ARGUMENT de la ligne de commande, ce
    qui a fait échouer un `claude -p` réel sur Windows avec `FileNotFoundError: [WinError 206]
    Nom de fichier ou extension trop long` dès qu'un lot de diff dépassait la limite de longueur
    de ligne de commande de `CreateProcess` (~32k caractères). Le prompt doit désormais être
    transmis séparément (STDIN pour `_real_run()`), sans aucune limite de longueur de ce type."""
    seen = {}

    def fake_run(argv, prompt):
        seen["argv"] = argv
        seen["prompt"] = prompt
        return 0, "{}", ""

    huge_prompt = "x" * 100_000  # dépasserait largement la limite Windows si embarqué dans argv
    invoker = ClaudeInvoker(run_fn=fake_run)

    invoker.run(huge_prompt, permission_mode="plan")

    assert huge_prompt not in seen["argv"]
    assert all(len(tok) < 1000 for tok in seen["argv"])  # aucun token géant dans argv
    assert seen["prompt"] == huge_prompt


def test_real_run_passes_the_prompt_via_stdin_input_not_argv(monkeypatch):
    """Complète le test précédent au niveau de `_real_run()` (le `run_fn` RÉEL) : le prompt doit
    être transmis via `subprocess.run(..., input=prompt)`, jamais concaténé dans `argv`."""
    import subprocess

    import scripts.autopilot.claude_invoker as invoker_module

    seen_kwargs = {}

    class _FakeCompleted:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(argv, **kwargs):
        seen_kwargs["argv"] = argv
        seen_kwargs.update(kwargs)
        return _FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    invoker_module._real_run(["claude", "-p", "--output-format", "json"], "le prompt réel à envoyer")

    assert seen_kwargs.get("input") == "le prompt réel à envoyer"
    assert "le prompt réel à envoyer" not in seen_kwargs["argv"]


def test_real_run_uses_explicit_utf8_encoding_never_the_windows_default(monkeypatch):
    """Régression — trouvé RÉELLEMENT cassé pendant le canary V1.1 (mission §9) : un
    `UnicodeDecodeError` dans un thread lecteur de `subprocess` (`'charmap' codec can't decode
    byte...`) s'est produit en confiant à `subprocess.run(text=True)` le codec de LOCALE Windows
    (cp1252) pour décoder une sortie `claude -p` contenant des caractères accentués (dépôt en
    français). `encoding="utf-8", errors="replace"` doit être explicite, jamais implicite."""
    import subprocess

    import scripts.autopilot.claude_invoker as invoker_module

    seen_kwargs = {}

    class _FakeCompleted:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(argv, **kwargs):
        seen_kwargs.update(kwargs)
        return _FakeCompleted()

    # `_real_run()` fait `import subprocess` localement (dans son corps) — patcher le module
    # global `subprocess.run` directement, seul point que ce import local pourra résoudre.
    monkeypatch.setattr(subprocess, "run", fake_run)

    invoker_module._real_run(["claude", "-p"], "x")

    assert seen_kwargs.get("encoding") == "utf-8"
    assert seen_kwargs.get("errors") == "replace"


def test_build_claude_argv_uses_print_and_json_output():
    argv = build_claude_argv()
    assert argv[0] == "claude"
    assert "-p" in argv or "--print" in argv
    assert "--output-format" in argv
    assert "json" in argv


def test_build_claude_argv_includes_permission_mode_when_given():
    argv = build_claude_argv(permission_mode="acceptEdits")
    assert "--permission-mode" in argv
    assert "acceptEdits" in argv


def test_build_claude_argv_includes_max_budget_when_given():
    argv = build_claude_argv(max_budget_usd=5.0)
    assert "--max-budget-usd" in argv
    assert "5.0" in argv


def test_build_claude_argv_includes_resume_session_id_when_given():
    argv = build_claude_argv(resume_session_id="abc-123")
    assert "--resume" in argv
    assert "abc-123" in argv


def test_build_claude_argv_never_includes_dangerously_skip_permissions_by_default():
    """Mission §9 : "ne pas utiliser --dangerously-skip-permissions comme solution générale"."""
    argv = build_claude_argv()
    assert "--dangerously-skip-permissions" not in argv
    assert "--allow-dangerously-skip-permissions" not in argv


def test_invoker_returns_success_result_on_zero_exit():
    def fake_run(argv, prompt):
        return 0, '{"result": "ok"}', ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("do the thing")
    assert result.exit_code == 0
    assert result.category is None
    assert result.stdout == '{"result": "ok"}'


def test_invoker_classifies_failure_category_on_nonzero_exit():
    def fake_run(argv, prompt):
        return 1, "", "Error: rate_limit_error - exceeded"

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("do the thing")
    assert result.exit_code == 1
    assert result.category is FailureCategory.QUOTA_LIMIT


def test_invoker_passes_the_prompt_to_run_fn_separately_from_argv():
    seen = {}

    def fake_run(argv, prompt):
        seen["argv"] = argv
        seen["prompt"] = prompt
        return 0, "{}", ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    invoker.run("hello world", permission_mode="acceptEdits")
    assert seen["prompt"] == "hello world"
    assert "hello world" not in seen["argv"]
    assert "acceptEdits" in seen["argv"]


def test_build_claude_argv_includes_json_schema_when_given():
    argv = build_claude_argv(json_schema='{"type":"object"}')
    assert "--json-schema" in argv
    assert '{"type":"object"}' in argv


def test_invoker_extracts_session_id_and_cost_from_real_json_shape(tmp_path):
    """Forme réellement observée lors de la mission Autopilot V1.1 (§2/§6) : objet PLAT avec
    `session_id`/`total_cost_usd`/`is_error` au premier niveau, jamais imbriqués."""
    real_shape = (
        '{"is_error":true,"session_id":"19cb61e4-5da0-47be-be4d-77c9978dd589",'
        '"total_cost_usd":0.321516,"type":"result","subtype":"error_max_budget_usd"}'
    )

    def fake_run(argv, prompt):
        return 1, real_shape, ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("x")

    assert result.session_id == "19cb61e4-5da0-47be-be4d-77c9978dd589"
    assert result.cost_usd == 0.321516
    assert result.parsed["subtype"] == "error_max_budget_usd"


def test_functionally_succeeded_is_false_when_is_error_true_even_with_zero_exit_code():
    """Mission §6 : "ne pas considérer exit_code==0 comme preuve suffisante" — `is_error` du JSON
    structuré doit primer quand il est présent."""
    def fake_run(argv, prompt):
        return 0, '{"is_error": true, "result": "partial"}', ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("x")

    assert result.exit_code == 0
    assert result.functionally_succeeded is False


def test_functionally_succeeded_is_true_when_is_error_false_and_exit_code_zero():
    def fake_run(argv, prompt):
        return 0, '{"is_error": false, "result": "done"}', ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("x")

    assert result.functionally_succeeded is True
    assert result.result_text == "done"


def test_functionally_succeeded_falls_back_to_exit_code_when_json_has_no_is_error_field():
    def fake_run(argv, prompt):
        return 0, "not json at all", ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("x")

    assert result.parsed is None
    assert result.functionally_succeeded is True


def test_result_structured_parses_a_json_encoded_result_string():
    def fake_run(argv, prompt):
        return 0, '{"is_error": false, "result": "{\\"verdict\\": \\"CLEAN\\"}"}', ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("x")

    assert result.result_structured == {"verdict": "CLEAN"}


def test_result_structured_prefers_the_real_structured_output_field(tmp_path):
    """Forme RÉELLEMENT confirmée par un second sondage empirique de cette mission (un appel
    `--json-schema` réussi) : `structured_output` est un dict natif déjà validé, prioritaire sur
    `result` (qui peut porter du texte parasite autour du JSON, ce qui a fait réellement échouer
    le parsing de `result` lors du canary — un Reviewer dont l'échec de parsing ressemblait
    silencieusement à "review propre, 0 finding"). `result`/`structured_output` DIFFÈRENT
    délibérément ici (pas seulement la même valeur dupliquée) — preuve que c'est bien
    `structured_output` qui est lu, pas `result` de manière incidemment correcte (finding trouvé
    par la revue reproductibilité/scope V1.1 : le test précédent ne pouvait pas distinguer les
    deux, `result` étant réparable par coïncidence dans cette forme-là)."""
    real_shape = (
        '{"is_error":false,"session_id":"23c726cd-d4a8-425f-bd6b-c9256dfafcee",'
        # `result` volontairement NON parseable tel quel (texte parasite autour du JSON, la forme
        # réelle qui a fait échouer le parsing lors du canary) — si `result_structured` lisait
        # encore `result` en priorité, ce test échouerait.
        '"result":"Voici la réponse : {\\"verdict\\":\\"FINDINGS\\",\\"findings\\":[{}]}",'
        '"structured_output":{"verdict":"CLEAN","findings":[]}}'
    )

    def fake_run(argv, prompt):
        return 0, real_shape, ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("x")

    assert result.result_structured == {"verdict": "CLEAN", "findings": []}


def test_result_structured_falls_back_to_result_when_structured_output_absent():
    def fake_run(argv, prompt):
        return 0, '{"is_error": false, "result": "{\\"verdict\\": \\"CLEAN\\"}"}', ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("x")

    assert result.result_structured == {"verdict": "CLEAN"}


def test_result_structured_handles_result_already_being_a_nested_object():
    """Deuxième forme plausible de sortie `--json-schema`, non confirmée empiriquement (le sondage
    réel a épuisé son budget avant réponse) — `result_structured` doit gérer les deux sans
    supposer laquelle Claude Code produit réellement."""
    def fake_run(argv, prompt):
        return 0, '{"is_error": false, "result": {"verdict": "FINDINGS", "findings": []}}', ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("x")

    assert result.result_structured == {"verdict": "FINDINGS", "findings": []}


def test_result_structured_is_none_when_result_is_not_json():
    def fake_run(argv, prompt):
        return 0, '{"is_error": false, "result": "plain text answer"}', ""

    invoker = ClaudeInvoker(run_fn=fake_run)
    result = invoker.run("x")

    assert result.result_structured is None
