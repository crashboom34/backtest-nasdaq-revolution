"""
tests/test_autopilot_git_safety.py — Bootstrap Autopilot V1 (2026-09-17), mission §9/§18.

Fonctions pures — aucune commande Git n'est réellement exécutée par ces tests, seuls les argv/
chemins/tailles proposés sont vérifiés avant qu'une commande réelle ne soit jamais lancée par le
superviseur (voir supervisor.py).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.git_safety import (
    PROTECTED_PATHS,
    check_disk_space,
    check_git_command,
    check_git_command_string,
    check_no_large_files,
    check_no_secrets,
    check_scope_files,
    should_escalate,
)


def test_git_push_force_is_forbidden():
    assert check_git_command(["git", "push", "--force", "origin", "master"]) is not None


def test_git_push_force_with_lease_is_forbidden():
    assert check_git_command(["git", "push", "--force-with-lease", "origin", "master"]) is not None


def test_git_push_dash_f_shorthand_is_forbidden():
    assert check_git_command(["git", "push", "-f", "origin", "master"]) is not None


def test_normal_push_is_allowed():
    assert check_git_command(["git", "push", "origin", "master"]) is None


def test_reset_hard_is_forbidden():
    assert check_git_command(["git", "reset", "--hard", "HEAD~1"]) is not None


def test_reset_soft_is_allowed():
    assert check_git_command(["git", "reset", "--soft", "HEAD~1"]) is None


def test_clean_fd_is_forbidden():
    assert check_git_command(["git", "clean", "-fd"]) is not None


def test_clean_xdf_is_forbidden():
    assert check_git_command(["git", "clean", "-xdf"]) is not None


def test_commit_no_verify_is_forbidden():
    assert check_git_command(["git", "commit", "--no-verify", "-m", "x"]) is not None


def test_push_no_verify_is_forbidden():
    assert check_git_command(["git", "push", "--no-verify", "origin", "master"]) is not None


def test_normal_commit_is_allowed():
    assert check_git_command(["git", "commit", "-m", "docs: update"]) is None


def test_add_dash_a_dash_all_is_forbidden():
    """Mission §3/§8 : jamais un ajout global aveugle si le worktree contient plusieurs scopes."""
    assert check_git_command(["git", "add", "-A"]) is not None
    assert check_git_command(["git", "add", "."]) is not None
    assert check_git_command(["git", "add", "--all"]) is not None


def test_add_explicit_pathspecs_is_allowed():
    assert check_git_command(["git", "add", "--", "walk_forward.py", "tests/test_walk_forward.py"]) is None


def test_deleting_a_remote_branch_is_forbidden():
    assert check_git_command(["git", "push", "origin", "--delete", "some-branch"]) is not None


def test_branch_delete_force_is_forbidden():
    assert check_git_command(["git", "branch", "-D", "some-branch"]) is not None


def test_protected_paths_include_the_repo_rules():
    assert "app_corrupted_backup.py" in PROTECTED_PATHS
    assert "nasdaq_3m.csv" in PROTECTED_PATHS


def test_scope_including_a_protected_path_is_rejected():
    reason = check_scope_files(["walk_forward.py", "app_corrupted_backup.py"])
    assert reason is not None
    assert "app_corrupted_backup.py" in reason


def test_scope_without_protected_paths_is_accepted():
    assert check_scope_files(["walk_forward.py", "tests/test_walk_forward.py"]) is None


def test_disk_space_below_threshold_is_rejected(tmp_path, monkeypatch):
    import shutil

    fake_usage = shutil.disk_usage(tmp_path)._replace(free=1 * 1024 ** 3)  # 1 Go
    monkeypatch.setattr("shutil.disk_usage", lambda _: fake_usage)
    assert check_disk_space(min_gb=2.0, path=str(tmp_path)) is not None


def test_disk_space_above_threshold_is_accepted(tmp_path, monkeypatch):
    import shutil

    fake_usage = shutil.disk_usage(tmp_path)._replace(free=20 * 1024 ** 3)  # 20 Go
    monkeypatch.setattr("shutil.disk_usage", lambda _: fake_usage)
    assert check_disk_space(min_gb=2.0, path=str(tmp_path)) is None


def test_no_secrets_in_a_clean_diff():
    diff = "+def foo():\n+    return 42\n"
    assert check_no_secrets(diff) == []


def test_detects_an_aws_style_access_key():
    diff = "+AWS_ACCESS_KEY_ID = \"AKIAABCDEFGHIJKLMNOP\"\n"
    findings = check_no_secrets(diff)
    assert findings != []


def test_detects_a_generic_api_key_assignment():
    diff = "+api_key = \"sk-abcdefghijklmnopqrstuvwx1234567890ABCD\"\n"
    assert check_no_secrets(diff) != []


def test_detects_a_pem_private_key_header():
    diff = "+-----BEGIN RSA PRIVATE KEY-----\n"
    assert check_no_secrets(diff) != []


def test_does_not_flag_a_normal_looking_variable():
    diff = "+ema_trend_len = 120\n+or_start_h = 15\n"
    assert check_no_secrets(diff) == []


def test_no_large_files_under_the_limit():
    assert check_no_large_files({"walk_forward.py": 20_000}, max_mb=50) == []


def test_large_file_over_the_limit_is_flagged():
    findings = check_no_large_files({"nasdaq_3m.csv": 200 * 1024 * 1024}, max_mb=50)
    assert findings != []
    assert "nasdaq_3m.csv" in findings[0]


def test_should_not_escalate_below_the_limit():
    signatures = ["ImportError: foo", "ImportError: foo"]
    assert should_escalate(signatures, "ImportError: foo", limit=3) is False


def test_should_escalate_after_repeated_identical_failures():
    """Mission §7 : "Si plusieurs tentatives échouent pour exactement la même cause, effectuer un
    diagnostic de niveau supérieur et changer d'approche" — jamais une boucle infinie."""
    signatures = ["ImportError: foo", "ImportError: foo", "ImportError: foo"]
    assert should_escalate(signatures, "ImportError: foo", limit=3) is True


def test_should_not_escalate_when_failures_differ():
    signatures = ["ImportError: foo", "AssertionError: bar", "TypeError: baz"]
    assert should_escalate(signatures, "TypeError: baz", limit=3) is False


# ── check_git_command_string — pour le hook Claude Code PreToolUse (commande shell brute) ──


def test_string_variant_allows_a_normal_push():
    assert check_git_command_string("git push origin master") is None


def test_string_variant_blocks_a_force_push():
    assert check_git_command_string("git push --force origin master") is not None


def test_string_variant_blocks_a_force_push_hidden_after_a_cd():
    """Une commande composée (cd puis git) ne doit jamais laisser passer un force push caché."""
    assert check_git_command_string("cd repo && git push --force origin master") is not None


def test_string_variant_blocks_reset_hard_after_a_semicolon():
    assert check_git_command_string("echo hello; git reset --hard HEAD~1") is not None


def test_string_variant_allows_a_non_git_command():
    assert check_git_command_string("pytest -q") is None


def test_string_variant_allows_an_empty_command():
    assert check_git_command_string("") is None
