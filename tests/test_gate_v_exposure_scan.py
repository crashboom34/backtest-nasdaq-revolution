"""
tests/test_gate_v_exposure_scan.py — AF-V-07 Slice E3-B2 : scanner strict des racines d'audit.

Contrat : ADR 0025 Décision 23, 23.11 étape 1 (listage strict), 23.27/23.28 (E3-A), 23.29.1 (arborescence `exposure/`) et 23.29.6
(double passe) ; design E3-B (AI_HANDOFF.md §44.1). Fixtures SYNTHÉTIQUES uniquement : octets en mémoire et arborescences
temporaires (`tmp_path`). Aucun vrai `results/`, aucune donnée de marché, aucun registre, aucun Claim réel.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import random
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gate_v_exposure_scan as scan

_MODULE_PATH = Path(scan.__file__)

# ============================================================================================
# Tranche 1 — parse_strict_json : lecture JSON stricte réutilisable (octets bruts, jamais de réparation)
# ============================================================================================

LIMIT = {"max_bytes": 1_000_000, "max_depth": 32}


def _anomaly(raw: bytes, **limits) -> "scan.SourceAnomaly":
    with pytest.raises(scan.StrictJsonError) as info:
        scan.parse_strict_json(raw, **{**LIMIT, **limits})
    return info.value.anomaly


@pytest.mark.parametrize(
    "raw, expected",
    [
        (b'{"a": 1, "b": [true, null, 1.5, "x"]}', {"a": 1, "b": [True, None, 1.5, "x"]}),
        (b"[]", []),
        (b"{}", {}),
        (b'"texte"', "texte"),
        (b"12345678901234567890", 12345678901234567890),   # entier sans perte
        (b"1.0", 1.0),
        (b"null", None),
        (b' \n\t{"k": "\xc3\xa9"}\n', {"k": "é"}),          # espaces JSON légitimes ; UTF-8 valide
        (b'"\\ud83d\\ude00"', "\U0001F600"),                # paire de substituts échappée : valide
    ],
)
def test_parse_strict_json_returns_exact_python_values(raw, expected):
    value = scan.parse_strict_json(raw, **LIMIT)
    assert value == expected and type(value) is type(expected)


def test_parse_strict_json_keeps_bool_distinct_from_numbers():
    assert scan.parse_strict_json(b"[true, 1, false, 0]", **LIMIT) == [True, 1, False, 0]
    assert [type(v) for v in scan.parse_strict_json(b"[true, 1]", **LIMIT)] == [bool, int]


@pytest.mark.parametrize("raw", [b"", b"   ", b"\n", b'{"a": 1', b'{"a": ', b"[1, 2", b'{"a": 1}}', b"{} {}", b"01", b"{'a': 1}", b'{"a": 1,}'])
def test_parse_strict_json_refuses_truncated_empty_or_malformed_documents(raw):
    assert _anomaly(raw) is scan.SourceAnomaly.INVALID_JSON


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a": 1, "a": 2}',
        b'{"o": {"k": 1, "k": 1}}',
        b'[{"x": 0, "x": 1}]',
        b'{"a": 1, "\\u0061": 2}',    # même clé après décodage des échappements
    ],
)
def test_parse_strict_json_refuses_duplicate_keys_at_any_depth(raw):
    assert _anomaly(raw) is scan.SourceAnomaly.DUPLICATE_KEY


@pytest.mark.parametrize("raw", [b"NaN", b"Infinity", b"-Infinity", b'{"x": NaN}', b"[Infinity]", b"1e999", b"-1e999", b'{"x": 1e400}'])
def test_parse_strict_json_refuses_non_finite_values(raw):
    assert _anomaly(raw) is scan.SourceAnomaly.NON_FINITE


def test_parse_strict_json_refuses_a_byte_order_mark():
    assert _anomaly(b'\xef\xbb\xbf{"a": 1}') is scan.SourceAnomaly.BOM


@pytest.mark.parametrize("raw", [b'{"a": "\xff"}', b"\xc0\xaf", b'["\xe9"]', b"\xff\xfe{}", b'{"a": "\xed\xa0\x80"}'])
def test_parse_strict_json_refuses_invalid_utf8(raw):
    assert _anomaly(raw) is scan.SourceAnomaly.NOT_UTF8


@pytest.mark.parametrize("raw", [b'"\\ud800"', b'{"a": "\\udfff"}', b'{"\\ud800": 1}', b'["x", {"y": ["\\udc00z"]}]'])
def test_parse_strict_json_refuses_lone_surrogates_in_keys_and_values(raw):
    assert _anomaly(raw) is scan.SourceAnomaly.LONE_SURROGATE


def test_parse_strict_json_bounds_the_nesting_depth_without_recursion_errors():
    assert scan.parse_strict_json(b'{"a": 1}', max_bytes=100, max_depth=1) == {"a": 1}
    assert scan.parse_strict_json(b"1", max_bytes=100, max_depth=1) == 1                    # un scalaire a la profondeur 0
    assert _anomaly(b'{"a": {}}', max_depth=1) is scan.SourceAnomaly.DEPTH_EXCEEDED
    deep = b"[" * 32 + b"]" * 32
    assert scan.parse_strict_json(deep, max_bytes=1000, max_depth=32) == json.loads(deep)
    assert _anomaly(b"[" * 33 + b"]" * 33, max_depth=32) is scan.SourceAnomaly.DEPTH_EXCEEDED
    hostile = b"[" * 200_000
    assert _anomaly(hostile, max_bytes=300_000, max_depth=32) is scan.SourceAnomaly.DEPTH_EXCEEDED


def test_parse_strict_json_does_not_count_brackets_inside_strings():
    assert scan.parse_strict_json(b'{"a": "[[[[[[[[[["}', max_bytes=100, max_depth=1) == {"a": "[[[[[[[[[["}
    assert scan.parse_strict_json(b'{"a": "\\"[[[[[[["}', max_bytes=100, max_depth=1) == {"a": '"[[[[[[['}
    assert scan.parse_strict_json(b'{"a\\\\": "[[[["}', max_bytes=100, max_depth=1) == {"a\\": "[[[["}


def test_parse_strict_json_bounds_the_size_before_decoding():
    raw = b'{"a": 1}'
    assert scan.parse_strict_json(raw, max_bytes=len(raw), max_depth=4) == {"a": 1}
    assert _anomaly(raw, max_bytes=len(raw) - 1) is scan.SourceAnomaly.TOO_LARGE
    assert _anomaly(b"\xff" * 50, max_bytes=10) is scan.SourceAnomaly.TOO_LARGE   # la taille prime sur le décodage


def test_strict_json_error_is_a_value_error_carrying_the_typed_anomaly():
    with pytest.raises(ValueError) as info:
        scan.parse_strict_json(b"{", **LIMIT)
    assert isinstance(info.value, scan.StrictJsonError) and info.value.anomaly is scan.SourceAnomaly.INVALID_JSON


@pytest.mark.parametrize("raw", ["{}", bytearray(b"{}"), memoryview(b"{}"), None, 1, ["{}"], object()])
def test_parse_strict_json_rejects_non_bytes_input_with_type_error(raw):
    with pytest.raises(TypeError):
        scan.parse_strict_json(raw, **LIMIT)


@pytest.mark.parametrize("bad", [True, 0, -1, 1.5, None, "5"])
def test_parse_strict_json_validates_its_limits(bad):
    with pytest.raises((TypeError, ValueError)):
        scan.parse_strict_json(b"{}", max_bytes=bad, max_depth=4)
    with pytest.raises((TypeError, ValueError)):
        scan.parse_strict_json(b"{}", max_bytes=100, max_depth=bad)


# ============================================================================================
# Tranche 2 — types de configuration : AuditRoot, SegmentPattern, SourceRule, ScanLimits, ScanHooks
# ============================================================================================

def _limits(**overrides):
    base = dict(
        max_roots=4, max_entries=1000, max_depth=8, max_json_bytes=64 * 1024, max_total_read_bytes=1024 * 1024,
        max_json_depth=16, max_name_length=80, max_path_length=400, max_attempts=1,
    )
    base.update(overrides)
    return scan.ScanLimits(**base)


def test_audit_root_accepts_a_portable_label_and_an_absolute_path(tmp_path):
    root = scan.AuditRoot("results-main_1", str(tmp_path))
    assert root.label == "results-main_1"
    assert root.path == os.path.normpath(str(tmp_path))
    assert scan.AuditRoot("r", tmp_path).path == root.path            # os.PathLike accepté, normalisé en str
    assert hash(root) == hash(scan.AuditRoot("results-main_1", str(tmp_path)))


@pytest.mark.parametrize("label", ["", " a", "a ", "a b", "a/b", "a\\b", ".", "..", "-x", "_x", "é", "a" * 65, "a:b", "a.b", "a\n"])
def test_audit_root_refuses_a_non_portable_label(tmp_path, label):
    with pytest.raises(ValueError):
        scan.AuditRoot(label, str(tmp_path))


@pytest.mark.parametrize("label", [None, 1, b"a", ["a"], object()])
def test_audit_root_rejects_a_non_str_label_with_type_error(tmp_path, label):
    with pytest.raises(TypeError):
        scan.AuditRoot(label, str(tmp_path))


def test_audit_root_rejects_a_str_subclass_label(tmp_path):
    class S(str):
        pass

    with pytest.raises(TypeError):
        scan.AuditRoot(S("a"), str(tmp_path))


def test_audit_root_requires_an_absolute_path_without_parent_segments(tmp_path):
    for relative in ("results", "./results", "a/b", os.path.join("..", "x")):
        with pytest.raises(ValueError):
            scan.AuditRoot("r", relative)
    with pytest.raises(ValueError):
        scan.AuditRoot("r", os.path.join(str(tmp_path), "..", "x"))        # remontée `..` refusée même sous un chemin absolu
    with pytest.raises(ValueError):
        scan.AuditRoot("r", "")
    with pytest.raises(ValueError):
        scan.AuditRoot("r", str(tmp_path) + "\x00")
    for bad in (None, 1, b"x", object()):
        with pytest.raises(TypeError):
            scan.AuditRoot("r", bad)


@pytest.mark.parametrize("pattern, matching, not_matching", [
    (r"[0-9a-f]{64}", ["a" * 64, "0" * 64], ["a" * 63, "A" * 64, "a" * 65, "g" * 64]),
    (r"job_[0-9]+", ["job_1", "job_042"], ["job_", "xjob_1", "job_1.json", "JOB_1"]),
    (r"\.exposure\.tmp\.[0-9a-f]{32}", [".exposure.tmp." + "0" * 32], [".exposure.tmp." + "0" * 31, "x.exposure.tmp." + "0" * 32]),
])
def test_segment_pattern_uses_fullmatch_on_a_single_name(pattern, matching, not_matching):
    segment = scan.SegmentPattern(pattern)
    assert all(segment.matches(name) for name in matching)
    assert not any(segment.matches(name) for name in not_matching)


@pytest.mark.parametrize("permissive", [r".*", r".+", r"[^/]+", r"[A-Za-z0-9._-]+", r"\S+", r"(?s).*", r"^.*$", r"\w+", r"[\s\S]*"])
def test_segment_pattern_refuses_patterns_that_match_any_name(permissive):
    with pytest.raises(ValueError):
        scan.SegmentPattern(permissive)


@pytest.mark.parametrize("bad", ["[", "(", "a{2,1}", "", "x*", "a?", "a" * 301])
def test_segment_pattern_refuses_invalid_empty_matching_or_oversized_regex(bad):
    with pytest.raises(ValueError):
        scan.SegmentPattern(bad)


@pytest.mark.parametrize("bad", [None, 1, b"a", ["a"], object()])
def test_segment_pattern_rejects_a_non_str_regex_with_type_error(bad):
    with pytest.raises(TypeError):
        scan.SegmentPattern(bad)


def test_entry_class_exposes_its_file_directory_and_read_semantics():
    reads = {c for c in scan.EntryClass if c.is_read}
    assert reads == {scan.EntryClass.EXPOSING_JSON, scan.EntryClass.INFORMATIVE_JSON}
    files = {c for c in scan.EntryClass if c.is_file}
    directories = {c for c in scan.EntryClass if c.is_directory}
    assert files == {scan.EntryClass.EXPOSING_JSON, scan.EntryClass.INFORMATIVE_JSON, scan.EntryClass.INERT_FILE, scan.EntryClass.TEMP_ORPHAN_FILE}
    assert directories == {scan.EntryClass.INERT_DIRECTORY, scan.EntryClass.STRUCTURAL_DIRECTORY}
    assert files | directories == set(scan.EntryClass) and not files & directories
    assert {c for c in scan.EntryClass if c.is_descended} == {scan.EntryClass.STRUCTURAL_DIRECTORY}


def test_source_rule_accepts_literal_and_pattern_segments():
    rule = scan.SourceRule(("exposure", scan.SegmentPattern(r"[0-9a-f]{64}"), "declaration_0001.json"), scan.EntryClass.INFORMATIVE_JSON)
    assert rule.depth == 3 and rule.expected_json is None
    assert rule.matches(("exposure", "a" * 64, "declaration_0001.json"))
    assert not rule.matches(("exposure", "a" * 64))                                  # profondeur fixe
    assert not rule.matches(("exposure", "a" * 64, "declaration_0001.json", "x"))
    assert not rule.matches(("exposure", "short", "declaration_0001.json"))
    assert not rule.matches(("Exposure", "a" * 64, "declaration_0001.json"))         # littéral sensible à la casse


@pytest.mark.parametrize("segments", [(), [], "a/b", ("a", ""), ("..",), (".",), ("a/b",), ("a\\b",), ("a b",), ("a", None), ("é",), ("a\x00",)])
def test_source_rule_refuses_invalid_segments(segments):
    with pytest.raises((TypeError, ValueError)):
        scan.SourceRule(segments, scan.EntryClass.INERT_FILE)


def test_source_rule_validates_class_and_expected_json_type():
    with pytest.raises(TypeError):
        scan.SourceRule(("a",), "INERT_FILE")
    with pytest.raises(TypeError):
        scan.SourceRule(("a",), scan.EntryClass.INFORMATIVE_JSON, expected_json=dict)
    for non_read in (scan.EntryClass.INERT_FILE, scan.EntryClass.INERT_DIRECTORY, scan.EntryClass.STRUCTURAL_DIRECTORY, scan.EntryClass.TEMP_ORPHAN_FILE):
        with pytest.raises(ValueError):
            scan.SourceRule(("a",), non_read, expected_json=scan.JsonKind.OBJECT)
    assert scan.SourceRule(("a",), scan.EntryClass.EXPOSING_JSON, expected_json=scan.JsonKind.OBJECT).expected_json is scan.JsonKind.OBJECT


def test_scan_limits_requires_every_bound_explicitly_and_by_keyword():
    assert _limits().max_attempts == 1
    with pytest.raises(TypeError):
        scan.ScanLimits(4, 1000, 8, 1024, 4096, 16, 80, 200, 1)          # arguments positionnels refusés
    full = dict(max_roots=4, max_entries=10, max_depth=8, max_json_bytes=64, max_total_read_bytes=128, max_json_depth=16,
                max_name_length=80, max_path_length=200, max_attempts=1)
    for name in full:                                                     # aucune valeur par défaut normative
        partial = {k: v for k, v in full.items() if k != name}
        with pytest.raises(TypeError):
            scan.ScanLimits(**partial)


@pytest.mark.parametrize("field", ["max_roots", "max_entries", "max_depth", "max_json_bytes", "max_total_read_bytes", "max_json_depth",
                                   "max_name_length", "max_path_length", "max_attempts"])
@pytest.mark.parametrize("bad, error", [(0, ValueError), (-1, ValueError), (True, TypeError), (1.5, TypeError), (None, TypeError), ("3", TypeError)])
def test_scan_limits_refuse_non_positive_or_non_integer_bounds(field, bad, error):
    with pytest.raises(error):
        _limits(**{field: bad})


def test_scan_limits_refuse_a_single_file_cap_above_the_total_read_budget():
    assert _limits(max_json_bytes=100, max_total_read_bytes=100).max_json_bytes == 100
    with pytest.raises(ValueError):
        _limits(max_json_bytes=101, max_total_read_bytes=100)


def test_scan_hooks_accept_callables_or_none_only():
    hooks = scan.ScanHooks()
    assert hooks.after_first_pass is None and hooks.after_file_read is None
    assert scan.ScanHooks(after_first_pass=lambda attempt: None).after_first_pass is not None
    for bad in ("x", 1, object()):
        with pytest.raises(TypeError):
            scan.ScanHooks(after_first_pass=bad)
        with pytest.raises(TypeError):
            scan.ScanHooks(after_file_read=bad)


# ============================================================================================
# Tranche 3 — scan_audit_roots : cœur du scan d'une racine (observations, lecture stricte, inconnus, orphelins)
# ============================================================================================

HEX64 = scan.SegmentPattern(r"[0-9a-f]{64}")
INV = "a" * 64
ORPHAN = ".exposure.tmp." + "0" * 32

RULES = (
    scan.SourceRule(("plan.json",), scan.EntryClass.EXPOSING_JSON, scan.JsonKind.OBJECT),
    scan.SourceRule(("experiments",), scan.EntryClass.STRUCTURAL_DIRECTORY),
    scan.SourceRule(("experiments", scan.SegmentPattern(r"[a-z0-9_]+\.json")), scan.EntryClass.INFORMATIVE_JSON),
    scan.SourceRule(("logs.txt",), scan.EntryClass.INERT_FILE),
    scan.SourceRule(("datasets",), scan.EntryClass.INERT_DIRECTORY),
    scan.SourceRule(("exposure",), scan.EntryClass.STRUCTURAL_DIRECTORY),
    scan.SourceRule(("exposure", HEX64), scan.EntryClass.STRUCTURAL_DIRECTORY),
    scan.SourceRule(("exposure", HEX64, scan.SegmentPattern(r"declaration_[0-9]{4}\.json")), scan.EntryClass.INFORMATIVE_JSON, scan.JsonKind.OBJECT),
    scan.SourceRule(("exposure", HEX64, scan.SegmentPattern(scan.EXPOSURE_TEMP_ORPHAN_PATTERN)), scan.EntryClass.TEMP_ORPHAN_FILE),
)


def _tree(base: Path, files: dict) -> Path:
    """Crée un arbre synthétique : `None` = répertoire, `bytes` = fichier."""
    for relative, data in files.items():
        target = base.joinpath(*relative.split("/"))
        if data is None:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    return base


def _run(tmp_path, files, rules=RULES, hooks=None, label="main", **limit_overrides):
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    _tree(root, files)
    return scan.scan_audit_roots((scan.AuditRoot(label, root),), rules, _limits(**limit_overrides), hooks=hooks)


def _by_path(result):
    return {observation.relative_path: observation for observation in result.observations}


MINIMAL = {
    "plan.json": b'{"campaign_id": "c1"}',
    "experiments/e1.json": b'{ "a" : [1, 2] }',
    "logs.txt": b"journal\n",
    "datasets/raw/ig_prices_raw.json": b'{"prices": []}',
}


def test_scan_of_a_minimal_valid_root_observes_every_entry_in_a_deterministic_order(tmp_path):
    result = _run(tmp_path, MINIMAL)
    assert [(o.relative_path, o.kind, o.entry_class, o.anomaly) for o in result.observations] == [
        ("datasets", scan.EntryKind.DIRECTORY, scan.EntryClass.INERT_DIRECTORY, None),
        ("experiments", scan.EntryKind.DIRECTORY, scan.EntryClass.STRUCTURAL_DIRECTORY, None),
        ("experiments/e1.json", scan.EntryKind.FILE, scan.EntryClass.INFORMATIVE_JSON, None),
        ("logs.txt", scan.EntryKind.FILE, scan.EntryClass.INERT_FILE, None),
        ("plan.json", scan.EntryKind.FILE, scan.EntryClass.EXPOSING_JSON, None),
    ]
    assert result.attempts_used == 1
    assert [(r.label, r.path) for r in result.roots] == [("main", os.path.normpath(str(tmp_path / "root")))]
    assert all(o.root_label == "main" for o in result.observations)


def test_scan_records_the_sha256_of_the_exact_raw_bytes_and_the_file_metadata(tmp_path):
    result = _run(tmp_path, MINIMAL)
    for relative in ("plan.json", "experiments/e1.json"):
        observation = _by_path(result)[relative]
        raw = (tmp_path / "root").joinpath(*relative.split("/")).read_bytes()
        info = os.stat(tmp_path / "root" / relative.replace("/", os.sep))
        assert observation.content_hash == hashlib.sha256(raw).hexdigest()       # octets bruts, jamais un JSON reformaté
        assert (observation.size, observation.mtime_ns, observation.st_ino, observation.st_dev) == (info.st_size, info.st_mtime_ns, info.st_ino, info.st_dev)
    e1 = _by_path(result)["experiments/e1.json"]
    assert e1.content_hash != hashlib.sha256(json.dumps(e1.value, separators=(",", ":")).encode()).hexdigest()
    assert e1.value == {"a": [1, 2]} and e1.value_parsed is True
    assert _by_path(result)["plan.json"].value == {"campaign_id": "c1"}


def test_inert_files_and_directories_are_observed_by_metadata_without_hash_or_value(tmp_path):
    result = _run(tmp_path, MINIMAL)
    for relative in ("logs.txt", "datasets", "experiments"):
        observation = _by_path(result)[relative]
        assert observation.content_hash is None and observation.value_parsed is False and observation.value is None
        assert observation.size is not None or observation.kind is scan.EntryKind.DIRECTORY
    assert _by_path(result)["logs.txt"].size == len(b"journal\n")


@pytest.fixture
def opened(monkeypatch):
    """Journalise toute ouverture de fichier (os.open et builtins.open) pendant le test."""
    log = []
    real_os_open, real_open = os.open, open

    def spy_os_open(path, *args, **kwargs):
        log.append(os.fspath(path))
        return real_os_open(path, *args, **kwargs)

    def spy_open(file, *args, **kwargs):
        log.append(os.fspath(file) if isinstance(file, (str, os.PathLike)) else repr(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy_os_open)
    monkeypatch.setattr("builtins.open", spy_open)
    return log


def test_scan_opens_only_the_recognised_readable_files_never_inert_unknown_orphan_or_market_data(tmp_path, opened):
    files = {
        "plan.json": b"{}",
        "logs.txt": b"x",
        "datasets/raw/ig_prices_raw.json": b'{"prices": []}',
        "datasets/prices.csv": b"time,open\n",
        "results.csv": b"a,b\n",
        "archive.zip": b"PK",
        "unknown.json": b"{}",
        f"exposure/{INV}/declaration_0001.json": b"{}",
        f"exposure/{INV}/{ORPHAN}": b"{",
    }
    _run(tmp_path, files)
    root = str(tmp_path / "root")
    under_root = sorted(os.path.relpath(p, root).replace(os.sep, "/") for p in opened if os.path.normcase(p).startswith(os.path.normcase(root)))
    # exactement les deux fichiers reconnus lisibles, chacun ouvert une fois par passe (double passe : deux fois), aucun autre
    assert under_root == sorted(["plan.json", "plan.json", f"exposure/{INV}/declaration_0001.json", f"exposure/{INV}/declaration_0001.json"])
    assert not any(name in p for p in opened for name in ("prices.csv", "ig_prices_raw", "results.csv", "archive.zip", "logs.txt", "unknown.json", ORPHAN))


def test_unknown_entries_in_a_healthy_root_become_typed_observations_never_silent_absence(tmp_path, opened):
    files = {"plan.json": b"{}", "mystery.json": b"{}", "stray.txt": b"x", "cache.tmp": b"", "tmp8h2k.tmp": b"", "sub/inner.json": b"{}", "empty_dir": None}
    result = _run(tmp_path, files)
    by_path = _by_path(result)
    assert set(by_path) == {"plan.json", "mystery.json", "stray.txt", "cache.tmp", "tmp8h2k.tmp", "sub", "empty_dir"}   # `sub/inner.json` jamais descendu
    for name, anomaly, kind in (
        ("mystery.json", scan.SourceAnomaly.UNKNOWN_FILE, scan.EntryKind.FILE),
        ("stray.txt", scan.SourceAnomaly.UNKNOWN_FILE, scan.EntryKind.FILE),
        ("cache.tmp", scan.SourceAnomaly.UNKNOWN_TEMP_FILE, scan.EntryKind.FILE),
        ("tmp8h2k.tmp", scan.SourceAnomaly.UNKNOWN_TEMP_FILE, scan.EntryKind.FILE),
        ("sub", scan.SourceAnomaly.UNKNOWN_DIRECTORY, scan.EntryKind.DIRECTORY),
        ("empty_dir", scan.SourceAnomaly.UNKNOWN_DIRECTORY, scan.EntryKind.DIRECTORY),
    ):
        observation = by_path[name]
        assert (observation.anomaly, observation.kind, observation.entry_class) == (anomaly, kind, None)
        assert observation.content_hash is None and observation.value_parsed is False
    assert by_path["plan.json"].anomaly is None
    assert not any("mystery.json" in p or "stray.txt" in p or "cache.tmp" in p for p in opened)


def test_an_incomplete_source_table_never_hides_entries(tmp_path):
    result = _run(tmp_path, {"plan.json": b"{}", "a.json": b"{}", "b.json": b"{}"}, rules=())
    assert {o.relative_path: o.anomaly for o in result.observations} == {name: scan.SourceAnomaly.UNKNOWN_FILE for name in ("a.json", "b.json", "plan.json")}


def test_temp_orphans_are_allowed_only_at_their_exact_location_and_never_read(tmp_path, opened):
    files = {
        f"exposure/{INV}/{ORPHAN}": b"{",                          # emplacement exact : orphelin autorisé, consigné
        f"exposure/{ORPHAN}": b"{",                                # même nom, mauvais emplacement
        f"exposure/{INV}/.exposure.tmp." + "0" * 31: b"{",         # motif invalide (31 hexadécimaux)
        f"exposure/{INV}/.exposure.tmp." + "G" * 32: b"{",         # hexadécimaux invalides
        f"exposure/{INV}/other.json.tmp": b"{",                    # `.tmp` étranger à la convention
    }
    by_path = _by_path(_run(tmp_path, files))
    exact = by_path[f"exposure/{INV}/{ORPHAN}"]
    assert (exact.entry_class, exact.anomaly) == (scan.EntryClass.TEMP_ORPHAN_FILE, None)
    assert exact.content_hash is None and exact.value_parsed is False
    for relative in (f"exposure/{ORPHAN}", f"exposure/{INV}/.exposure.tmp." + "0" * 31, f"exposure/{INV}/.exposure.tmp." + "G" * 32, f"exposure/{INV}/other.json.tmp"):
        assert by_path[relative].anomaly in (scan.SourceAnomaly.UNKNOWN_TEMP_FILE, scan.SourceAnomaly.UNKNOWN_FILE), relative
        assert by_path[relative].entry_class is None
    assert by_path[f"exposure/{INV}/other.json.tmp"].anomaly is scan.SourceAnomaly.UNKNOWN_TEMP_FILE
    assert not any(".exposure.tmp." in p for p in opened)


def test_a_known_name_with_the_wrong_entry_kind_is_a_kind_mismatch_anomaly_and_is_not_descended(tmp_path, opened):
    files = {"plan.json/inner.json": b"{}", "logs.txt/inner.txt": b"x", "experiments": b"{}", "datasets": b"x"}
    by_path = _by_path(_run(tmp_path, files))
    assert set(by_path) == {"plan.json", "logs.txt", "experiments", "datasets"}
    assert by_path["plan.json"].entry_class is scan.EntryClass.EXPOSING_JSON and by_path["plan.json"].kind is scan.EntryKind.DIRECTORY
    assert by_path["experiments"].kind is scan.EntryKind.FILE and by_path["datasets"].kind is scan.EntryKind.FILE
    assert {o.anomaly for o in by_path.values()} == {scan.SourceAnomaly.KIND_MISMATCH}
    assert not any(p.endswith("experiments") for p in opened)


@pytest.mark.parametrize("expected, matching, others", [
    (scan.JsonKind.OBJECT, b'{"a": 1}', [b"[]", b'"x"', b"1.5", b"true", b"null"]),
    (scan.JsonKind.ARRAY, b"[1]", [b"{}", b'"x"', b"1.5", b"true", b"null"]),
    (scan.JsonKind.STRING, b'"x"', [b"{}", b"[]", b"1.5", b"true", b"null"]),
    (scan.JsonKind.NUMBER, b"1.5", [b"{}", b"[]", b'"x"', b"true", b"false", b"null"]),      # un booléen n'est pas un nombre
    (scan.JsonKind.BOOLEAN, b"true", [b"{}", b"[]", b'"x"', b"1", b"0", b"null"]),            # un nombre n'est pas un booléen
    (scan.JsonKind.NULL, b"null", [b"{}", b"[]", b'"x"', b"1", b"true"]),
])
def test_an_unexpected_top_level_json_type_is_an_anomaly_that_keeps_the_hash(tmp_path, expected, matching, others):
    rules = (scan.SourceRule(("plan.json",), scan.EntryClass.EXPOSING_JSON, expected),)
    good = _run(tmp_path, {"plan.json": matching}, rules=rules).observations[0]
    assert good.anomaly is None and good.value_parsed is True
    for raw in others:
        (tmp_path / "root" / "plan.json").write_bytes(raw)
        bad = scan.scan_audit_roots((scan.AuditRoot("main", tmp_path / "root"),), rules, _limits()).observations[0]
        assert bad.anomaly is scan.SourceAnomaly.UNEXPECTED_JSON_TYPE, raw
        assert bad.content_hash == hashlib.sha256(raw).hexdigest() and bad.value is None and bad.value_parsed is False


@pytest.mark.parametrize("raw, anomaly", [
    (b'{"a": ', scan.SourceAnomaly.INVALID_JSON),
    (b"", scan.SourceAnomaly.INVALID_JSON),
    (b'{"a": 1, "a": 2}', scan.SourceAnomaly.DUPLICATE_KEY),
    (b'{"a": NaN}', scan.SourceAnomaly.NON_FINITE),
    (b'{"a": Infinity}', scan.SourceAnomaly.NON_FINITE),
    (b'\xef\xbb\xbf{"a": 1}', scan.SourceAnomaly.BOM),
    (b'{"a": "\xff"}', scan.SourceAnomaly.NOT_UTF8),
    (b'{"a": "\\ud800"}', scan.SourceAnomaly.LONE_SURROGATE),
    (b"[" * 20 + b"]" * 20, scan.SourceAnomaly.DEPTH_EXCEEDED),
])
def test_invalid_json_content_is_a_source_anomaly_with_the_raw_hash_never_a_refusal(tmp_path, raw, anomaly):
    files = {"plan.json": raw, "logs.txt": b"ok", "experiments/e1.json": b"{}"}
    rules = (scan.SourceRule(("plan.json",), scan.EntryClass.EXPOSING_JSON),) + RULES[1:4]    # `plan.json` sans type attendu
    result = _run(tmp_path, files, rules=rules, max_json_depth=16)
    by_path = _by_path(result)
    assert by_path["plan.json"].anomaly is anomaly and by_path["plan.json"].value_parsed is False
    assert by_path["plan.json"].content_hash == hashlib.sha256(raw).hexdigest()
    assert by_path["experiments/e1.json"].anomaly is None                      # le reste de la racine saine est observé normalement


def test_an_oversized_json_file_is_reported_too_large_without_being_opened_or_hashed(tmp_path, opened):
    big = b'{"a": "' + b"x" * 500 + b'"}'
    result = _run(tmp_path, {"plan.json": big, "experiments/e1.json": b"{}"}, max_json_bytes=100, max_total_read_bytes=1000)
    observation = _by_path(result)["plan.json"]
    assert observation.anomaly is scan.SourceAnomaly.TOO_LARGE and observation.content_hash is None and observation.size == len(big)
    assert not any(p.endswith("plan.json") for p in opened)


def test_an_unreadable_recognised_file_is_an_unreadable_anomaly_not_a_refusal(tmp_path, monkeypatch):
    real_os_open = os.open

    def deny(path, *args, **kwargs):
        if os.fspath(path).endswith("plan.json"):
            raise PermissionError(13, "refusé")
        return real_os_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", deny)
    result = _run(tmp_path, {"plan.json": b"{}", "experiments/e1.json": b"{}"})
    assert _by_path(result)["plan.json"].anomaly is scan.SourceAnomaly.UNREADABLE
    assert _by_path(result)["plan.json"].content_hash is None
    assert _by_path(result)["experiments/e1.json"].anomaly is None


def test_the_observation_order_does_not_depend_on_the_order_returned_by_the_filesystem(tmp_path, monkeypatch):
    files = {"plan.json": b"{}", "experiments/b.json": b"{}", "experiments/a.json": b"{}", "experiments/c_1.json": b"{}", "logs.txt": b"x", "zzz": b"x", "Abc": b"x"}
    baseline = _run(tmp_path, files).observations
    real_scandir = os.scandir

    class Reversed:
        def __init__(self, path):
            self._inner = real_scandir(path)

        def __enter__(self):
            entries = list(self._inner.__enter__())
            entries.reverse()
            return iter(entries)

        def __exit__(self, *args):
            return self._inner.__exit__(*args)

    monkeypatch.setattr(os, "scandir", Reversed)
    assert scan.scan_audit_roots((scan.AuditRoot("main", tmp_path / "root"),), RULES, _limits()).observations == baseline
    assert [o.relative_path for o in baseline] == sorted(
        [o.relative_path for o in baseline], key=lambda p: tuple(p.split("/"))
    )


def test_scan_audit_roots_validates_its_arguments(tmp_path):
    root = scan.AuditRoot("main", tmp_path)
    (tmp_path / "x.json").write_bytes(b"{}")
    with pytest.raises(TypeError):
        scan.scan_audit_roots([root], RULES, _limits())
    with pytest.raises(TypeError):
        scan.scan_audit_roots((root,), list(RULES), _limits())
    with pytest.raises(TypeError):
        scan.scan_audit_roots((root,), RULES, {"max_roots": 1})
    with pytest.raises(TypeError):
        scan.scan_audit_roots((root,), RULES, _limits(), hooks=lambda: None)
    with pytest.raises(TypeError):
        scan.scan_audit_roots((str(tmp_path),), RULES, _limits())
    with pytest.raises(TypeError):
        scan.scan_audit_roots((root,), (RULES[0], "plan.json"), _limits())
    with pytest.raises(ValueError):
        scan.scan_audit_roots((), RULES, _limits())


# ============================================================================================
# Tranche 4 — défaillances de STRUCTURE : refus du scan (ExposureScanRefusal), jamais de résultat partiel
# ============================================================================================

IS_WINDOWS = sys.platform.startswith("win")


def _refusal(call):
    with pytest.raises(scan.ExposureScanRefusal) as info:
        call()
    return info.value


def _refused(tmp_path, files, expected, rules=RULES, **limit_overrides):
    error = _refusal(lambda: _run(tmp_path, files, rules=rules, **limit_overrides))
    assert error.failure is expected, (error.failure, error.detail)
    return error


def _scan_roots(*roots, rules=RULES, **limit_overrides):
    return scan.scan_audit_roots(tuple(roots), rules, _limits(**limit_overrides))


def _make_symlink(target, link, is_dir=False):
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except (OSError, NotImplementedError):
        pytest.skip("liens symboliques indisponibles (privilège Windows requis) : non démontré sur cette machine")


def _make_junction(target, link):
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"jonction indisponible : {result.stderr.strip()}")


def test_refusal_is_a_value_error_with_a_typed_failure_and_its_location(tmp_path):
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("main", tmp_path / "absent")))
    assert isinstance(error, ValueError) and error.failure is scan.StructuralFailure.ROOT_MISSING
    assert error.root_label == "main" and error.relative_path is None and error.detail


def test_a_missing_root_or_a_root_that_is_not_a_directory_refuses(tmp_path):
    _refused(tmp_path, {}, scan.StructuralFailure.ROOT_EMPTY)           # racine créée mais vide : ROOT_EMPTY
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("main", tmp_path / "nowhere")))
    assert error.failure is scan.StructuralFailure.ROOT_MISSING
    a_file = tmp_path / "afile"
    a_file.write_bytes(b"{}")
    assert _refusal(lambda: _scan_roots(scan.AuditRoot("main", a_file))).failure is scan.StructuralFailure.ROOT_NOT_DIRECTORY


def test_an_empty_root_refuses_unless_the_root_is_explicitly_declared_possibly_empty(tmp_path):
    (tmp_path / "root").mkdir()
    assert _refusal(lambda: _scan_roots(scan.AuditRoot("main", tmp_path / "root"))).failure is scan.StructuralFailure.ROOT_EMPTY
    result = _scan_roots(scan.AuditRoot("main", tmp_path / "root", may_be_empty=True))
    assert result.observations == () and [r.label for r in result.roots] == ["main"]


def test_a_root_whose_listing_fails_refuses_and_a_subdirectory_whose_listing_fails_refuses(tmp_path, monkeypatch):
    _tree(tmp_path / "root", {"plan.json": b"{}", "experiments/e1.json": b"{}"})
    real_scandir = os.scandir

    def deny_for(suffix):
        def fake(path):
            if os.fspath(path).endswith(suffix):
                raise PermissionError(13, "refusé")
            return real_scandir(path)
        return fake

    monkeypatch.setattr(os, "scandir", deny_for("root"))
    assert _refusal(lambda: _scan_roots(scan.AuditRoot("main", tmp_path / "root"))).failure is scan.StructuralFailure.ROOT_UNREADABLE
    monkeypatch.setattr(os, "scandir", deny_for("experiments"))
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("main", tmp_path / "root")))
    assert error.failure is scan.StructuralFailure.SUBDIRECTORY_UNREADABLE and error.relative_path == "experiments"


def test_an_error_on_a_listed_name_is_a_refusal_never_an_absent_entry(tmp_path, monkeypatch):
    _tree(tmp_path / "root", {"plan.json": b"{}", "logs.txt": b"x"})
    real_lstat = os.lstat

    def flaky(path, *args, **kwargs):
        if os.fspath(path).endswith("logs.txt"):
            raise PermissionError(13, "refusé")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", flaky)
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("main", tmp_path / "root")))
    assert error.failure is scan.StructuralFailure.ENTRY_UNREADABLE and error.relative_path == "logs.txt"


def test_duplicate_labels_and_overlapping_or_identical_roots_refuse(tmp_path):
    for name in ("one", "two"):
        _tree(tmp_path / name, {"plan.json": b"{}"})
    _tree(tmp_path / "one", {"inner/plan.json": b"{}"})
    assert _refusal(lambda: _scan_roots(scan.AuditRoot("same", tmp_path / "one"), scan.AuditRoot("same", tmp_path / "two"))).failure is scan.StructuralFailure.DUPLICATE_ROOT_LABEL
    for first, second in ((tmp_path / "one", tmp_path / "one"), (tmp_path / "one", tmp_path / "one" / "inner"), (tmp_path / "one" / "inner", tmp_path / "one")):
        error = _refusal(lambda: _scan_roots(scan.AuditRoot("a", first), scan.AuditRoot("b", second)))
        assert error.failure is scan.StructuralFailure.ROOT_OVERLAP
    assert len(_scan_roots(scan.AuditRoot("a", tmp_path / "one" / "inner"), scan.AuditRoot("b", tmp_path / "two")).roots) == 2   # frères : acceptés
    # un préfixe de nom n'est pas une imbrication
    _tree(tmp_path / "one2", {"plan.json": b"{}"})
    assert len(_scan_roots(scan.AuditRoot("a", tmp_path / "one"), scan.AuditRoot("b", tmp_path / "one2")).roots) == 2


@pytest.mark.skipif(not IS_WINDOWS, reason="comparaison insensible à la casse propre à Windows")
def test_roots_that_differ_only_by_case_overlap_on_windows(tmp_path):
    _tree(tmp_path / "Root", {"plan.json": b"{}"})
    assert _refusal(lambda: _scan_roots(scan.AuditRoot("a", tmp_path / "Root"), scan.AuditRoot("b", str(tmp_path / "Root").lower()))).failure is scan.StructuralFailure.ROOT_OVERLAP


def test_two_roots_with_the_same_device_and_inode_overlap_whatever_their_spelling(tmp_path, monkeypatch):
    for name in ("one", "two"):
        _tree(tmp_path / name, {"plan.json": b"{}"})
    real_lstat = os.lstat

    def aliased(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if os.fspath(path).endswith(("one", "two")) and stat.S_ISDIR(info.st_mode):
            return os.stat_result((info.st_mode, 4242, 77, info.st_nlink, 0, 0, 0, 0, 0, 0))
        return info

    monkeypatch.setattr(os, "lstat", aliased)
    assert _refusal(lambda: _scan_roots(scan.AuditRoot("a", tmp_path / "one"), scan.AuditRoot("b", tmp_path / "two"))).failure is scan.StructuralFailure.ROOT_OVERLAP


def test_a_result_is_never_returned_after_a_structural_failure_in_any_root(tmp_path):
    _tree(tmp_path / "good", {"plan.json": b"{}"})
    with pytest.raises(scan.ExposureScanRefusal):
        _scan_roots(scan.AuditRoot("a", tmp_path / "good"), scan.AuditRoot("b", tmp_path / "absent"))
    with pytest.raises(scan.ExposureScanRefusal):
        _scan_roots(scan.AuditRoot("a", tmp_path / "absent"), scan.AuditRoot("b", tmp_path / "good"))


def test_the_number_of_roots_is_bounded(tmp_path):
    for name in ("one", "two"):
        _tree(tmp_path / name, {"plan.json": b"{}"})
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("a", tmp_path / "one"), scan.AuditRoot("b", tmp_path / "two"), max_roots=1))
    assert error.failure is scan.StructuralFailure.LIMIT_EXCEEDED and "max_roots" in error.detail


def test_a_symbolic_link_file_or_directory_is_refused_and_never_followed(tmp_path, opened):
    outside = tmp_path / "outside"
    _tree(outside, {"secret.json": b'{"secret": true}'})
    root = tmp_path / "root"
    _tree(root, {"plan.json": b"{}"})
    _make_symlink(outside / "secret.json", root / "experiments")                 # lien vers un fichier extérieur, sous un nom connu
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("main", root)))
    assert error.failure is scan.StructuralFailure.LINK_OR_REPARSE_POINT and error.relative_path == "experiments"
    assert not any("secret.json" in p for p in opened)
    (root / "experiments").unlink()
    _make_symlink(outside, root / "datasets", is_dir=True)
    assert _refusal(lambda: _scan_roots(scan.AuditRoot("main", root))).failure is scan.StructuralFailure.LINK_OR_REPARSE_POINT


def test_a_symbolic_link_root_is_refused(tmp_path):
    _tree(tmp_path / "real", {"plan.json": b"{}"})
    _make_symlink(tmp_path / "real", tmp_path / "linked", is_dir=True)
    assert _refusal(lambda: _scan_roots(scan.AuditRoot("main", tmp_path / "linked"))).failure is scan.StructuralFailure.LINK_OR_REPARSE_POINT


@pytest.mark.skipif(not IS_WINDOWS, reason="jonctions NTFS : Windows uniquement")
def test_a_windows_junction_inside_or_as_the_root_is_refused(tmp_path, opened):
    outside = tmp_path / "outside"
    _tree(outside, {"secret.json": b'{"secret": true}'})
    root = tmp_path / "root"
    _tree(root, {"plan.json": b"{}"})
    _make_junction(outside, root / "experiments")
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("main", root)))
    assert error.failure is scan.StructuralFailure.LINK_OR_REPARSE_POINT and error.relative_path == "experiments"
    assert not any("secret.json" in p for p in opened)
    clean = tmp_path / "clean"
    _tree(clean, {"plan.json": b"{}"})                                  # cible sans aucune jonction imbriquée
    _make_junction(clean, tmp_path / "rootjunction")
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("main", tmp_path / "rootjunction")))
    assert error.failure is scan.StructuralFailure.LINK_OR_REPARSE_POINT and error.relative_path is None


@pytest.mark.parametrize("mode, attributes, expected", [
    (stat.S_IFLNK | 0o777, 0, scan.StructuralFailure.LINK_OR_REPARSE_POINT),
    (stat.S_IFDIR | 0o755, 0x400, scan.StructuralFailure.LINK_OR_REPARSE_POINT),    # point d'analyse (jonction, placeholder cloud)
    (stat.S_IFREG | 0o644, 0x400, scan.StructuralFailure.LINK_OR_REPARSE_POINT),
    (stat.S_IFIFO | 0o644, 0, scan.StructuralFailure.SPECIAL_FILE),
    (stat.S_IFSOCK | 0o644, 0, scan.StructuralFailure.SPECIAL_FILE),
    (stat.S_IFCHR | 0o644, 0, scan.StructuralFailure.SPECIAL_FILE),
    (stat.S_IFBLK | 0o644, 0, scan.StructuralFailure.SPECIAL_FILE),
    (stat.S_IFREG | 0o644, 0x20, None),                                              # fichier ordinaire (attribut ARCHIVE)
    (stat.S_IFDIR | 0o755, 0x10, None),
])
def test_entry_type_classification_refuses_links_reparse_points_and_special_files(mode, attributes, expected):
    assert scan._structural_failure_for_stat(SimpleNamespace(st_mode=mode, st_file_attributes=attributes)) is expected


@pytest.mark.skipif(IS_WINDOWS or not hasattr(os, "mkfifo"), reason="FIFO : POSIX uniquement, non démontré sous Windows")
def test_a_fifo_is_refused_without_ever_being_opened(tmp_path, opened):
    root = tmp_path / "root"
    _tree(root, {"plan.json": b"{}"})
    os.mkfifo(root / "logs.txt")
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("main", root)))
    assert error.failure is scan.StructuralFailure.SPECIAL_FILE and not any(p.endswith("logs.txt") for p in opened)


@pytest.mark.parametrize("name, expected", [
    ("plan.json", None), (".exposure.tmp." + "0" * 32, None), ("job_1", None), ("a-b_c.d", None), ("Abc", None), ("conx", None), ("console.json", None),
    ("CON", scan.StructuralFailure.RESERVED_NAME), ("con.txt", scan.StructuralFailure.RESERVED_NAME), ("Nul", scan.StructuralFailure.RESERVED_NAME),
    ("AUX.json", scan.StructuralFailure.RESERVED_NAME), ("prn", scan.StructuralFailure.RESERVED_NAME),
    ("COM0", scan.StructuralFailure.RESERVED_NAME), ("com1.json", scan.StructuralFailure.RESERVED_NAME), ("LPT9", scan.StructuralFailure.RESERVED_NAME),
    ("lpt0.x.y", scan.StructuralFailure.RESERVED_NAME),
    ("a.", scan.StructuralFailure.NON_PORTABLE_NAME), ("a ", scan.StructuralFailure.NON_PORTABLE_NAME), ("a b", scan.StructuralFailure.NON_PORTABLE_NAME),
    ("a:b", scan.StructuralFailure.NON_PORTABLE_NAME), ("é.json", scan.StructuralFailure.NON_PORTABLE_NAME), ("a*b", scan.StructuralFailure.NON_PORTABLE_NAME),
    ("a?b", scan.StructuralFailure.NON_PORTABLE_NAME), ("a\\b", scan.StructuralFailure.NON_PORTABLE_NAME), ("a\nb", scan.StructuralFailure.NON_PORTABLE_NAME),
    ("", scan.StructuralFailure.NON_PORTABLE_NAME),
])
def test_portable_name_policy(name, expected):
    assert scan._portable_name_failure(name) is expected


def test_a_non_portable_name_refuses_the_scan_even_for_unknown_or_inert_entries(tmp_path):
    for files in ({"bad name.json": b"{}"}, {"é.json": b"{}"}, {"experiments/bad name.json": b"{}"}):
        files = {"plan.json": b"{}", **files}
        shutil.rmtree(tmp_path / "root", ignore_errors=True)
        assert _refused(tmp_path, files, scan.StructuralFailure.NON_PORTABLE_NAME).relative_path in ("bad name.json", "é.json", "experiments/bad name.json")


def test_a_windows_reserved_name_refuses_before_any_filesystem_access(tmp_path, monkeypatch):
    root = tmp_path / "root"
    _tree(root, {"plan.json": b"{}"})

    class FakeEntry:
        def __init__(self, name):
            self.name = name

    class FakeListing:
        def __init__(self, path):
            self._names = ["plan.json", "NUL"]

        def __enter__(self):
            return iter([FakeEntry(n) for n in self._names])

        def __exit__(self, *args):
            return False

    touched = []
    real_lstat = os.lstat
    monkeypatch.setattr(os, "scandir", FakeListing)
    monkeypatch.setattr(os, "lstat", lambda path, *a, **k: (touched.append(os.fspath(path)), real_lstat(path, *a, **k))[1])
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("main", root)))
    assert error.failure is scan.StructuralFailure.RESERVED_NAME and error.relative_path == "NUL"
    assert not any(p.endswith("NUL") for p in touched)               # le nom est refusé AVANT tout `lstat`/ouverture


@pytest.mark.parametrize("names, collides", [
    (["A.json", "a.json"], True), (["plan.json", "PLAN.JSON", "x"], True), (["a", "b", "c"], False), (["a", "A1"], False),
])
def test_case_collisions_within_a_directory_refuse(names, collides):
    assert (scan._find_case_collision(names) is not None) is collides


def test_a_case_collision_refuses_the_scan_before_any_entry_is_read(tmp_path, monkeypatch, opened):
    root = tmp_path / "root"
    _tree(root, {"plan.json": b"{}"})

    class FakeEntry:
        def __init__(self, name):
            self.name = name

    class FakeListing:
        def __init__(self, path):
            pass

        def __enter__(self):
            return iter([FakeEntry("plan.json"), FakeEntry("PLAN.JSON")])

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(os, "scandir", FakeListing)
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("main", root)))
    assert error.failure is scan.StructuralFailure.CASE_COLLISION
    assert not any(p.endswith("plan.json") for p in opened)


def test_the_number_of_entries_is_bounded_and_exceeding_it_refuses(tmp_path):
    files = {f"f{i}.txt": b"x" for i in range(6)}
    assert len(_run(tmp_path, files, rules=(), max_entries=6).observations) == 6
    error = _refused(tmp_path, {"extra.txt": b"x"}, scan.StructuralFailure.LIMIT_EXCEEDED, rules=(), max_entries=6)
    assert "max_entries" in error.detail


def test_the_traversal_depth_is_bounded(tmp_path):
    rules = (
        scan.SourceRule(("a",), scan.EntryClass.STRUCTURAL_DIRECTORY),
        scan.SourceRule(("a", "b"), scan.EntryClass.STRUCTURAL_DIRECTORY),
        scan.SourceRule(("a", "b", "c.json"), scan.EntryClass.INFORMATIVE_JSON),
    )
    files = {"a/b/c.json": b"{}"}
    assert [o.relative_path for o in _run(tmp_path, files, rules=rules, max_depth=3).observations] == ["a", "a/b", "a/b/c.json"]
    error = _refused(tmp_path, {}, scan.StructuralFailure.LIMIT_EXCEEDED, rules=rules, max_depth=2)
    assert "max_depth" in error.detail and error.relative_path == "a/b/c.json"


def test_the_path_and_name_lengths_are_bounded(tmp_path):
    error = _refused(tmp_path, {"plan.json": b"{}", "x" * 30 + ".txt": b"x"}, scan.StructuralFailure.LIMIT_EXCEEDED, max_name_length=20)
    assert "max_name_length" in error.detail
    shallow = tmp_path / "root"
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("main", shallow), max_path_length=len(str(shallow)) + 3))
    assert error.failure is scan.StructuralFailure.LIMIT_EXCEEDED and "max_path_length" in error.detail


def test_the_total_number_of_bytes_read_is_bounded_and_exceeding_it_refuses(tmp_path):
    rules = (scan.SourceRule(("experiments",), scan.EntryClass.STRUCTURAL_DIRECTORY),
             scan.SourceRule(("experiments", scan.SegmentPattern(r"e[0-9]\.json")), scan.EntryClass.INFORMATIVE_JSON))
    payload = b'{"k": "' + b"v" * 40 + b'"}'
    files = {f"experiments/e{i}.json": payload for i in range(3)}
    ok = _run(tmp_path, files, rules=rules, max_json_bytes=100, max_total_read_bytes=3 * len(payload))
    assert ok.bytes_read == 3 * len(payload)
    error = _refused(tmp_path, {}, scan.StructuralFailure.LIMIT_EXCEEDED, rules=rules, max_json_bytes=100, max_total_read_bytes=3 * len(payload) - 1)
    assert "max_total_read_bytes" in error.detail


def test_an_ambiguous_source_table_refuses_instead_of_choosing_a_rule(tmp_path):
    rules = (scan.SourceRule(("plan.json",), scan.EntryClass.EXPOSING_JSON), scan.SourceRule(("plan.json",), scan.EntryClass.INERT_FILE))
    error = _refused(tmp_path, {"plan.json": b"{}"}, scan.StructuralFailure.AMBIGUOUS_SOURCE_TABLE, rules=rules)
    assert error.relative_path == "plan.json"
    overlapping = (scan.SourceRule((scan.SegmentPattern(r"job_[0-9]+"),), scan.EntryClass.STRUCTURAL_DIRECTORY),
                   scan.SourceRule(("job_1",), scan.EntryClass.INERT_DIRECTORY))
    shutil.rmtree(tmp_path / "root")
    _refused(tmp_path, {"job_1": None}, scan.StructuralFailure.AMBIGUOUS_SOURCE_TABLE, rules=overlapping)


# ============================================================================================
# Tranche 5 — double passe (ADR 23.29.6) : détection des changements observables, essais bornés, injections de test
# ============================================================================================

BASE_FILES = {"plan.json": b'{"a": 1}', "logs.txt": b"journal", "experiments/e1.json": b"{}", "mystery.json": b"{}"}


def _first_pass_hook(action, *, only_first=True):
    calls = []

    def hook(attempt):
        calls.append(attempt)
        if not only_first or attempt == 1:
            action()

    return scan.ScanHooks(after_first_pass=hook), calls


def _unstable(tmp_path, action, attempts=1, files=BASE_FILES):
    hooks, calls = _first_pass_hook(action, only_first=False)
    error = _refusal(lambda: _run(tmp_path, files, hooks=hooks, max_attempts=attempts))
    assert error.failure is scan.StructuralFailure.UNSTABLE_LISTING and len(calls) == attempts
    return error


def _recovers_on_the_second_attempt(tmp_path, action, files=BASE_FILES):
    hooks, calls = _first_pass_hook(action, only_first=True)
    result = _run(tmp_path, files, hooks=hooks, max_attempts=2)
    assert result.attempts_used == 2 and calls == [1, 2]
    return result


def _mutate_plan(tmp_path, kind):
    path = tmp_path / "root" / "plan.json"
    before = os.stat(path)
    if kind == "touch_only":
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 5_000_000_000))
        return
    path.write_bytes({"same_size": b'{"a": 2}', "same_size_restored_mtime": b'{"a": 2}', "other_size": b'{"a": 22}'}[kind])
    if kind == "same_size_restored_mtime":
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


@pytest.mark.parametrize("kind", ["same_size", "same_size_restored_mtime", "other_size", "touch_only"])
def test_a_read_file_changed_between_the_two_passes_makes_the_listing_unstable(tmp_path, kind):
    error = _unstable(tmp_path, lambda: _mutate_plan(tmp_path, kind))
    assert "plan.json" in error.detail and error.detail


@pytest.mark.parametrize("kind", ["same_size", "same_size_restored_mtime", "other_size"])
def test_a_changed_file_is_accepted_after_a_retry_only_with_its_new_hash(tmp_path, kind):
    result = _recovers_on_the_second_attempt(tmp_path, lambda: _mutate_plan(tmp_path, kind))
    new = (tmp_path / "root" / "plan.json").read_bytes()
    assert _by_path(result)["plan.json"].content_hash == hashlib.sha256(new).hexdigest()


@pytest.mark.parametrize("action_name", ["add_root_file", "add_subdirectory_file", "remove_known_file", "remove_unknown_file", "add_directory"])
def test_a_name_added_or_removed_between_the_passes_makes_the_listing_unstable(tmp_path, action_name):
    root = tmp_path / "root"
    actions = {
        "add_root_file": lambda: (root / "new.txt").write_bytes(b"x"),
        "add_subdirectory_file": lambda: (root / "experiments" / "e2.json").write_bytes(b"{}"),
        "remove_known_file": lambda: (root / "logs.txt").unlink(),
        "remove_unknown_file": lambda: (root / "mystery.json").unlink(),
        "add_directory": lambda: (root / "newdir").mkdir(),
    }
    _unstable(tmp_path, actions[action_name])


def test_a_transient_change_is_absorbed_by_a_retry_when_attempts_remain(tmp_path):
    result = _recovers_on_the_second_attempt(tmp_path, lambda: (tmp_path / "root" / "new.txt").write_bytes(b"x"))
    assert "new.txt" in _by_path(result)


def test_inert_and_unknown_files_are_compared_by_name_only(tmp_path):
    root = tmp_path / "root"

    def churn():
        (root / "logs.txt").write_bytes(b"journal grossi " * 20)            # fichier inerte qu'un job peut réécrire
        (root / "mystery.json").write_bytes(b'{"changed": true}')           # fichier inconnu : comparé par son nom seulement

    hooks, calls = _first_pass_hook(churn)
    result = _run(tmp_path, BASE_FILES, hooks=hooks, max_attempts=1)
    assert result.attempts_used == 1 and calls == [1]
    assert _by_path(result)["logs.txt"].content_hash is None


def test_a_known_file_name_that_is_a_directory_is_compared_by_name_only_between_the_passes(tmp_path):
    root = tmp_path / "root"
    files = {**BASE_FILES, "plan.json": None}                       # `plan.json` est un RÉPERTOIRE : KIND_MISMATCH, jamais lu
    files["plan.json/inner.txt"] = b"x"
    hooks, calls = _first_pass_hook(lambda: (root / "plan.json" / "added.txt").write_bytes(b"y"))
    result = _run(tmp_path, files, hooks=hooks, max_attempts=1)
    assert result.attempts_used == 1 and _by_path(result)["plan.json"].anomaly is scan.SourceAnomaly.KIND_MISMATCH


def test_the_second_pass_rereads_and_rehashes_every_recognised_file_but_never_an_inert_one(tmp_path, opened):
    _run(tmp_path, BASE_FILES)
    names = [os.path.basename(p) for p in opened if os.path.normcase(p).startswith(os.path.normcase(str(tmp_path / "root")))]
    assert names.count("plan.json") == 2 and names.count("e1.json") == 2
    assert "logs.txt" not in names and "mystery.json" not in names


def test_the_number_of_attempts_is_bounded_and_the_refusal_reports_it(tmp_path):
    error = _unstable(tmp_path, lambda: (tmp_path / "root" / "plan.json").write_bytes(os.urandom(8).hex().encode()), attempts=3)
    assert "3" in error.detail and error.root_label is None


def test_after_first_pass_receives_the_attempt_number_and_runs_once_per_attempt(tmp_path):
    hooks, calls = _first_pass_hook(lambda: None)
    assert _run(tmp_path, BASE_FILES, hooks=hooks, max_attempts=5).attempts_used == 1
    assert calls == [1]


def test_a_root_that_disappears_or_changes_nature_between_the_passes_refuses_without_retry(tmp_path):
    root = tmp_path / "root"
    hooks, calls = _first_pass_hook(lambda: shutil.rmtree(root), only_first=False)
    error = _refusal(lambda: _run(tmp_path, BASE_FILES, hooks=hooks, max_attempts=3))
    assert error.failure is scan.StructuralFailure.ROOT_MISSING and calls == [1]
    hooks, calls = _first_pass_hook(lambda: (shutil.rmtree(root), root.write_bytes(b"x")), only_first=False)
    error = _refusal(lambda: _run(tmp_path, BASE_FILES, hooks=hooks, max_attempts=3))
    assert error.failure is scan.StructuralFailure.ROOT_NOT_DIRECTORY and calls == [1]


def test_a_subdirectory_that_becomes_unreadable_between_the_passes_refuses(tmp_path, monkeypatch):
    real_scandir = os.scandir

    def deny_experiments(path):
        if os.fspath(path).endswith("experiments"):
            raise PermissionError(13, "refusé")
        return real_scandir(path)

    hooks, calls = _first_pass_hook(lambda: monkeypatch.setattr(os, "scandir", deny_experiments), only_first=False)
    error = _refusal(lambda: _run(tmp_path, BASE_FILES, hooks=hooks, max_attempts=3))
    assert error.failure is scan.StructuralFailure.SUBDIRECTORY_UNREADABLE and error.relative_path == "experiments" and calls == [1]


def _after_read_hook(action, *, only_first=True):
    calls = []

    def hook(label, relative):
        calls.append((label, relative))
        if relative == "plan.json" and (not only_first or len([c for c in calls if c[1] == "plan.json"]) == 1):
            action()

    return scan.ScanHooks(after_file_read=hook), calls


def test_a_file_modified_during_its_own_read_is_detected_and_retried(tmp_path):
    plan = tmp_path / "root" / "plan.json"
    hooks, calls = _after_read_hook(lambda: plan.write_bytes(b'{"a": 22}'))
    result = _run(tmp_path, BASE_FILES, hooks=hooks, max_attempts=2)
    assert result.attempts_used == 2 and _by_path(result)["plan.json"].content_hash == hashlib.sha256(b'{"a": 22}').hexdigest()
    assert ("main", "plan.json") in calls


def test_a_file_replaced_during_its_own_read_by_another_inode_is_detected(tmp_path):
    root = tmp_path / "root"
    swap = tmp_path / "swap.json"

    def replace_by_same_bytes():
        swap.write_bytes((root / "plan.json").read_bytes())
        os.replace(swap, root / "plan.json")

    hooks, _ = _after_read_hook(replace_by_same_bytes)
    assert _run(tmp_path, BASE_FILES, hooks=hooks, max_attempts=2).attempts_used == 2
    shutil.rmtree(root)
    hooks, _ = _after_read_hook(replace_by_same_bytes, only_first=False)
    error = _refusal(lambda: _run(tmp_path, BASE_FILES, hooks=hooks, max_attempts=2))
    assert error.failure is scan.StructuralFailure.UNSTABLE_LISTING


def test_a_persistent_modification_during_the_read_exhausts_the_attempts_and_refuses(tmp_path):
    plan = tmp_path / "root" / "plan.json"
    counter = {"n": 0}

    def alter():
        counter["n"] += 1
        plan.write_bytes(b'{"a": %d}' % (100 + counter["n"]))

    hooks, _ = _after_read_hook(alter, only_first=False)
    assert _refusal(lambda: _run(tmp_path, BASE_FILES, hooks=hooks, max_attempts=3)).failure is scan.StructuralFailure.UNSTABLE_LISTING
    assert counter["n"] >= 3


def test_a_name_that_vanishes_between_listing_and_lstat_is_instability_not_an_unreadable_entry(tmp_path, monkeypatch):
    _tree(tmp_path / "root", BASE_FILES)
    real_lstat = os.lstat
    state = {"raised": 0}

    def vanishing(path, *args, **kwargs):
        if os.fspath(path).endswith("logs.txt") and state["raised"] < 1:
            state["raised"] += 1
            raise FileNotFoundError(2, "disparu")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", vanishing)
    result = scan.scan_audit_roots((scan.AuditRoot("main", tmp_path / "root"),), RULES, _limits(max_attempts=2))
    assert result.attempts_used == 2 and "logs.txt" in _by_path(result)
    state["raised"] = -10**6                                                       # disparition persistante
    with pytest.raises(scan.ExposureScanRefusal) as info:
        scan.scan_audit_roots((scan.AuditRoot("main", tmp_path / "root"),), RULES, _limits(max_attempts=2))
    assert info.value.failure is scan.StructuralFailure.UNSTABLE_LISTING


def test_a_file_that_vanishes_between_lstat_and_open_is_instability_not_an_unreadable_source(tmp_path, monkeypatch):
    _tree(tmp_path / "root", BASE_FILES)
    real_os_open = os.open
    state = {"raised": 0}

    def vanishing(path, *args, **kwargs):
        if os.fspath(path).endswith("plan.json") and state["raised"] < 1:
            state["raised"] += 1
            raise FileNotFoundError(2, "disparu")
        return real_os_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", vanishing)
    result = scan.scan_audit_roots((scan.AuditRoot("main", tmp_path / "root"),), RULES, _limits(max_attempts=2))
    assert result.attempts_used == 2 and _by_path(result)["plan.json"].anomaly is None


def test_a_modification_restored_to_the_identical_bytes_and_mtime_is_not_detected_by_design(tmp_path):
    """Limite DOCUMENTÉE (23.29.6) : la double passe détecte un changement observable, elle ne détecte pas une modification
    restaurée à l'identique entre les deux passes."""
    plan = tmp_path / "root" / "plan.json"

    def modify_then_restore():
        before = os.stat(plan)
        original = plan.read_bytes()
        plan.write_bytes(b'{"a": 9}')
        plan.write_bytes(original)
        os.utime(plan, ns=(before.st_atime_ns, before.st_mtime_ns))

    hooks, _ = _first_pass_hook(modify_then_restore)
    result = _run(tmp_path, BASE_FILES, hooks=hooks, max_attempts=1)
    assert result.attempts_used == 1 and _by_path(result)["plan.json"].content_hash == hashlib.sha256(b'{"a": 1}').hexdigest()


def test_the_scan_documents_that_the_double_pass_is_not_an_atomic_snapshot():
    doc = scan.scan_audit_roots.__doc__
    assert "instantané atomique" in doc and "après la seconde passe" in doc and "restaurée" in doc


def test_the_scan_result_is_a_past_observation_not_a_live_view(tmp_path):
    result = _run(tmp_path, BASE_FILES)
    (tmp_path / "root" / "plan.json").write_bytes(b'{"a": 999}')           # modification APRÈS la seconde passe : jamais détectée
    assert _by_path(result)["plan.json"].content_hash == hashlib.sha256(b'{"a": 1}').hexdigest()


# ============================================================================================
# Tranche 6 — durcissement, lecture seule, propriétés à graines fixes, pureté architecturale
# ============================================================================================

def test_a_gigantic_directory_listing_is_refused_without_being_materialised(tmp_path, monkeypatch):
    _tree(tmp_path / "root", {"plan.json": b"{}"})
    produced = {"n": 0}

    class FakeEntry:
        def __init__(self, name):
            self.name = name

    class Endless:
        def __init__(self, path):
            pass

        def __enter__(self):
            def entries():
                for index in range(50_000):
                    produced["n"] += 1
                    yield FakeEntry(f"f{index}.txt")
            return entries()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(os, "scandir", Endless)
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("main", tmp_path / "root"), max_entries=10))
    assert error.failure is scan.StructuralFailure.LIMIT_EXCEEDED and "max_entries" in error.detail
    assert produced["n"] <= 12                                              # le listage s'arrête au plafond, il n'est pas matérialisé


def _snapshot(base: Path) -> dict:
    state = {}
    for current, directories, files in os.walk(base):
        for name in directories + files:
            path = Path(current) / name
            info = os.lstat(path)
            state[str(path)] = (stat.S_ISDIR(info.st_mode), info.st_size, info.st_mtime_ns, None if stat.S_ISDIR(info.st_mode) else path.read_bytes())
    return state


def test_the_scan_is_strictly_read_only_even_with_anomalies_orphans_and_unknown_entries(tmp_path):
    files = {**BASE_FILES, "datasets/raw/a.csv": b"t,o\n", "bad.json": b"{", f"exposure/{INV}/{ORPHAN}": b"{", "tmp1.tmp": b"", "plan2/x.json": b"{}"}
    root = tmp_path / "root"
    _tree(root, files)
    before = _snapshot(root)
    _run(tmp_path, {}, max_attempts=2)
    assert _snapshot(root) == before                                          # aucun octet, taille, mtime ni nom modifié ou créé
    assert scan._READ_FLAGS & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) == 0


_PAYLOADS = {   # contenu synthétique → (anomalie attendue pour plan.json [OBJECT attendu], anomalie pour une entrée sans type attendu)
    b'{"v": 1}': (None, None),
    b'{"v": ': (scan.SourceAnomaly.INVALID_JSON, scan.SourceAnomaly.INVALID_JSON),
    b"[]": (scan.SourceAnomaly.UNEXPECTED_JSON_TYPE, None),
    b'{"a": 1, "a": 2}': (scan.SourceAnomaly.DUPLICATE_KEY, scan.SourceAnomaly.DUPLICATE_KEY),
    b'{"n": NaN}': (scan.SourceAnomaly.NON_FINITE, scan.SourceAnomaly.NON_FINITE),
}


def _random_tree(rng: random.Random):
    """Génère un arbre synthétique ET son résultat attendu, calculés indépendamment du scanner."""
    payloads = list(_PAYLOADS)
    files, expected = {}, {}

    def add(path, data, anomaly, hashed, entry_class):
        files[path] = data
        expected[path] = (entry_class, anomaly, hashlib.sha256(data).hexdigest() if hashed else None)

    expected["top0.json"] = (None, scan.SourceAnomaly.UNKNOWN_FILE, None)
    files["top0.json"] = b"{}"                                               # racine toujours non vide
    if rng.random() < 0.8:
        data = rng.choice(payloads)
        add("plan.json", data, _PAYLOADS[data][0], True, scan.EntryClass.EXPOSING_JSON)
    if rng.random() < 0.7:
        add("logs.txt", bytes(rng.randrange(256) for _ in range(rng.randrange(0, 20))), None, False, scan.EntryClass.INERT_FILE)
    for index in range(rng.randrange(0, 4)):
        data = rng.choice(payloads)
        add(f"experiments/e{index}.json", data, _PAYLOADS[data][1], True, scan.EntryClass.INFORMATIVE_JSON)
        expected["experiments"] = (scan.EntryClass.STRUCTURAL_DIRECTORY, None, None)
    for index in range(rng.randrange(0, 3)):
        path = f"experiments/Z{index}.JSON"
        files[path] = b"{}"
        expected[path] = (None, scan.SourceAnomaly.UNKNOWN_FILE, None)
        expected["experiments"] = (scan.EntryClass.STRUCTURAL_DIRECTORY, None, None)
    if rng.random() < 0.5:
        files["experiments/sub/x.json"] = b"{}"
        expected["experiments/sub"] = (None, scan.SourceAnomaly.UNKNOWN_DIRECTORY, None)
        expected["experiments"] = (scan.EntryClass.STRUCTURAL_DIRECTORY, None, None)
    if rng.random() < 0.5:
        files["datasets/raw/prices.csv"] = b"t,o\n1,2\n"
        expected["datasets"] = (scan.EntryClass.INERT_DIRECTORY, None, None)
    if rng.random() < 0.5:
        files["misc/z.json"] = b"{}"
        expected["misc"] = (None, scan.SourceAnomaly.UNKNOWN_DIRECTORY, None)
    for index in range(rng.randrange(0, 3)):
        files[f"cache{index}.tmp"] = b""
        expected[f"cache{index}.tmp"] = (None, scan.SourceAnomaly.UNKNOWN_TEMP_FILE, None)
    return files, expected


@pytest.mark.parametrize("seed", [101, 102, 103, 104, 105, 106, 107, 108])
def test_the_scanner_matches_an_independent_oracle_on_seeded_random_trees(tmp_path, seed):
    files, expected = _random_tree(random.Random(seed))
    result = _run(tmp_path, files, max_attempts=2)
    observed = {o.relative_path: (o.entry_class, o.anomaly, o.content_hash) for o in result.observations}
    assert observed == expected
    assert [o.relative_path for o in result.observations] == sorted((o.relative_path for o in result.observations), key=lambda p: tuple(p.split("/")))
    assert result.bytes_read == sum(len(files[p]) for p, (cls, _anomaly, digest) in expected.items() if digest is not None)


@pytest.mark.parametrize("seed", [201, 202, 203])
def test_two_scans_of_the_same_tree_are_identical_and_independent_of_the_creation_order(tmp_path, seed):
    rng = random.Random(seed)
    files, _ = _random_tree(rng)
    items = list(files.items())
    rng.shuffle(items)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = _run(tmp_path / "a", dict(items), max_attempts=2)
    second = _run(tmp_path / "b", dict(reversed(items)), max_attempts=2)
    comparable = lambda scan_result: [(o.root_label, o.relative_path, o.kind, o.entry_class, o.anomaly, o.size, o.content_hash) for o in scan_result.observations]
    assert comparable(first) == comparable(second)


def _module_tree():
    return ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))


def test_the_module_imports_only_the_standard_library_modules_it_needs():
    allowed = {"__future__", "dataclasses", "enum", "hashlib", "json", "os", "re", "stat", "typing", "warnings"}
    imported = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            imported.add(node.module.split(".")[0])
    assert imported <= allowed, imported - allowed


def test_the_module_has_no_dependency_on_e3a_b1_e2_engine_registry_or_market_data():
    source = _MODULE_PATH.read_text(encoding="utf-8")
    imports = {n.module or "" for n in ast.walk(_module_tree()) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(_module_tree()) if isinstance(n, ast.Import) for a in n.names}
    assert not [name for name in imports if "gate_v" in name or "engine" in name or "dataset_split" in name or "registry" in name]
    for fragment in ("ig_prices", ".csv", ".parquet", "FINAL_HOLDOUT", "S_H", "Europe/Paris", "zoneinfo", "datetime", "time.", "random", "uuid"):
        assert fragment not in source.replace("_json_kind", ""), fragment


def test_the_module_performs_only_authorised_read_only_filesystem_calls():
    forbidden_attributes = {"remove", "unlink", "rename", "mkdir", "makedirs", "rmdir", "removedirs", "write", "chmod", "chown",
                            "utime", "symlink", "link", "truncate", "ftruncate", "fsync", "walk", "listdir", "stat_float_times", "popen",
                            "system", "startfile", "readlink", "resolve", "glob", "rglob", "iterdir", "read_bytes", "read_text"}
    forbidden_names = {"open", "print", "input", "exec", "eval", "compile", "__import__", "glob", "shutil", "subprocess", "pathlib"}
    allowed_os_calls = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_attributes, node.attr
            if isinstance(node.value, ast.Name) and node.value.id == "os":
                allowed_os_calls.add(node.attr)
        elif isinstance(node, ast.Name):
            assert node.id not in forbidden_names, node.id
    assert allowed_os_calls <= {"open", "read", "close", "fstat", "lstat", "scandir", "fspath", "path", "PathLike", "sep", "O_RDONLY",
                                "O_BINARY", "O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK"}, allowed_os_calls


def test_the_module_has_no_mutable_module_level_state():
    for node in _module_tree().body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            assert not isinstance(node.value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)), ast.dump(node)[:80]
    assert not any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(_module_tree()))


def test_the_public_api_is_exactly_the_documented_surface():
    public = sorted(name for name, obj in vars(scan).items() if not name.startswith("_") and getattr(obj, "__module__", None) == scan.__name__)
    public += ["EXPOSURE_TEMP_ORPHAN_PATTERN"]
    assert sorted(public) == sorted([
        "AuditRoot", "EntryClass", "EntryKind", "ExposureScan", "ExposureScanRefusal", "JsonKind", "ScanHooks", "ScanLimits", "ScanObservation",
        "ScannedRoot", "SegmentPattern", "SourceAnomaly", "SourceRule", "StrictJsonError", "StructuralFailure", "EXPOSURE_TEMP_ORPHAN_PATTERN",
        "parse_strict_json", "scan_audit_roots",
    ])


def test_the_scanner_produces_no_finding_no_classification_and_no_admission_decision():
    assert [f.name for f in dataclasses.fields(scan.ExposureScan)] == ["roots", "observations", "attempts_used", "bytes_read", "rules_digest", "hooks_used", "limits"]
    assert {f.name for f in dataclasses.fields(scan.ScanObservation)} == {
        "root_label", "relative_path", "kind", "entry_class", "anomaly", "size", "mtime_ns", "st_ino", "st_dev", "content_hash", "value_parsed",
        "content_bytes", "rule_tag",
    }
    vocabulary = {member.value for enum in (scan.SourceAnomaly, scan.StructuralFailure, scan.EntryClass, scan.EntryKind, scan.JsonKind) for member in enum}
    assert not {value for value in vocabulary if any(word in value for word in ("FRESH", "EXPOSED", "RETROSPECTIVE", "UNDETERMINED", "ADMISSION", "AUTHORI"))}
    identifiers = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            identifiers.add(node.name)
    for word in ("ExposureFinding", "ExposureInventory", "TrialAccounting", "DeclarationSet", "ExposureClass", "OverlapVerdict", "SourceStatus"):
        assert word not in identifiers, word
    assert not [name for name in identifiers if name.lower().startswith(("classify", "admit", "authorise", "authorize"))]


# ============================================================================================
# Durcissement issu du contrôle de mutation : frontières exactes, contrôles en lecture, racines multiples
# ============================================================================================

def test_every_limit_accepts_its_exact_value_and_refuses_one_more(tmp_path):
    long_name = "n" * 20 + ".txt"
    assert long_name in _by_path(_run(tmp_path, {"plan.json": b"{}", long_name: b"x"}, max_name_length=len(long_name)))
    shutil.rmtree(tmp_path / "root")
    exact_path = os.path.join(str(tmp_path / "root"), "plan.json")
    assert "plan.json" in _by_path(_run(tmp_path, {"plan.json": b"{}"}, max_path_length=len(exact_path)))
    error = _refusal(lambda: _run(tmp_path, {}, max_path_length=len(exact_path) - 1))
    assert error.failure is scan.StructuralFailure.LIMIT_EXCEEDED and "max_path_length" in error.detail
    shutil.rmtree(tmp_path / "root")
    payload = b'{"k": "' + b"v" * 20 + b'"}'
    exact = _run(tmp_path, {"plan.json": payload}, max_json_bytes=len(payload), max_total_read_bytes=len(payload))
    assert _by_path(exact)["plan.json"].anomaly is None and _by_path(exact)["plan.json"].content_hash == hashlib.sha256(payload).hexdigest()
    shutil.rmtree(tmp_path / "root")
    over = _run(tmp_path, {"plan.json": payload + b" "}, max_json_bytes=len(payload), max_total_read_bytes=len(payload))
    assert _by_path(over)["plan.json"].anomaly is scan.SourceAnomaly.TOO_LARGE


@pytest.mark.parametrize("kind", ["touch_only", "other_size_restored_mtime", "replaced_inode_same_bytes", "replaced_inode_same_mtime"])
def test_a_change_right_after_the_last_read_of_the_second_pass_is_still_detected_in_that_pass(tmp_path, kind):
    root = tmp_path / "root"
    plan = root / "plan.json"
    swap = tmp_path / "swap.json"
    state = {"reads": 0}

    def change():
        before = os.stat(plan)
        if kind == "touch_only":
            os.utime(plan, ns=(before.st_atime_ns, before.st_mtime_ns + 5_000_000_000))
        elif kind == "other_size_restored_mtime":
            plan.write_bytes(b'{"a": 22}')
            os.utime(plan, ns=(before.st_atime_ns, before.st_mtime_ns))
        else:
            swap.write_bytes(plan.read_bytes())
            if kind == "replaced_inode_same_mtime":     # même taille, même mtime, mêmes octets : seul l'inode change
                os.utime(swap, ns=(before.st_atime_ns, before.st_mtime_ns))
            os.replace(swap, plan)

    def hook(label, relative):
        if relative == "plan.json":
            state["reads"] += 1
            if state["reads"] == 2:                      # seconde passe du premier essai : plus aucune comparaison ne suit
                change()

    result = _run(tmp_path, BASE_FILES, hooks=scan.ScanHooks(after_file_read=hook), max_attempts=2)
    assert result.attempts_used == 2 and state["reads"] == 4


def test_a_root_replaced_by_another_directory_with_the_same_names_between_the_passes_is_unstable(tmp_path):
    files = {"logs.txt": b"x", "other.txt": b"y"}               # aucun fichier lu : seule l'identité de la racine change
    root = tmp_path / "root"

    def swap_root():
        os.rename(root, tmp_path / "root_old")
        root.mkdir()
        (root / "logs.txt").write_bytes(b"x")
        (root / "other.txt").write_bytes(b"y")

    _unstable(tmp_path, swap_root, files=files)


def test_a_file_that_can_never_be_opened_because_it_is_gone_is_instability_not_an_unreadable_source(tmp_path, monkeypatch):
    _tree(tmp_path / "root", BASE_FILES)
    real_os_open = os.open

    def gone(path, *args, **kwargs):
        if os.fspath(path).endswith("plan.json"):
            raise FileNotFoundError(2, "disparu")
        return real_os_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", gone)
    with pytest.raises(scan.ExposureScanRefusal) as info:
        scan.scan_audit_roots((scan.AuditRoot("main", tmp_path / "root"),), RULES, _limits(max_attempts=2))
    assert info.value.failure is scan.StructuralFailure.UNSTABLE_LISTING


def test_several_roots_are_scanned_and_reported_in_label_order_whatever_the_input_order(tmp_path):
    for name in ("zeta", "alpha"):
        _tree(tmp_path / name, {"plan.json": b"{}", "logs.txt": b"x"})
    first = _scan_roots(scan.AuditRoot("zeta", tmp_path / "zeta"), scan.AuditRoot("alpha", tmp_path / "alpha"))
    second = _scan_roots(scan.AuditRoot("alpha", tmp_path / "alpha"), scan.AuditRoot("zeta", tmp_path / "zeta"))
    assert [r.label for r in first.roots] == ["alpha", "zeta"]
    assert [(o.root_label, o.relative_path) for o in first.observations] == [
        ("alpha", "logs.txt"), ("alpha", "plan.json"), ("zeta", "logs.txt"), ("zeta", "plan.json"),
    ]
    assert [(o.root_label, o.relative_path, o.content_hash) for o in first.observations] == [(o.root_label, o.relative_path, o.content_hash) for o in second.observations]
    assert first.bytes_read == 4


@pytest.mark.parametrize("risky", [r"(a+)+b", r"(a*)*c", r"(\d+)*x", r"(?:a+)+b", r"([a-z]+)+\.json", r"(a|b+)+z", r"(a{2,3})+b", r"((a+))+", r"(a|a)+b", r"(a|aa)+", r"((ab)+)+", r"(?:_[0-9]+)*\.json"])
def test_segment_pattern_refuses_nested_quantifiers_that_allow_catastrophic_backtracking(risky):
    with pytest.raises(ValueError):
        scan.SegmentPattern(risky)


@pytest.mark.parametrize("sequence", [
    "a*" * 20 + "b", "a?" * 40 + "a" * 40, r"\w*" * 30 + "b", "(?:a|a)" * 30 + "b", "a{0,2}" * 30 + "b", "(?:a+)" * 25 + "b", "a+" * 4 + "b",
    "(?:aa|a)" * 25, "a*a*a*a*b",
])
def test_segment_pattern_refuses_long_sequences_of_variable_elements_without_any_nested_group(sequence):
    with pytest.raises(ValueError):
        scan.SegmentPattern(sequence)


@pytest.mark.parametrize("safe", [r"(?:x|y)_[0-9]+\.json", r"[a-z0-9_]+\.json", r"(?:a|b)_[0-9]+", r"[0-9]+_[0-9]+", r"e[0-9]+_[0-9]+\.json"])
def test_segment_pattern_accepts_up_to_two_variable_elements(safe):
    assert scan.SegmentPattern(safe).matches("zzz") in (True, False)


@pytest.mark.parametrize("three", [r"[a-z]*[a-z]*[a-z]*(?:a{1}){40}-", r".*.*.*(?:a{1}){100}-", r"[0-9]+_[0-9]+_[0-9]+", r"(?:x|y|z)_[0-9]+\.json", r"a*a*a*b"])
def test_three_variable_elements_are_refused_because_their_worst_case_cost_is_cubic_in_the_name_length(three):
    with pytest.raises(ValueError):
        scan.SegmentPattern(three)


# ============================================================================================
# Audit final : intégrité de la preuve, table appliquée, autorité des hooks, bornes de coût
# ============================================================================================

def test_the_name_length_limit_is_capped_because_pattern_matching_cost_grows_with_the_name_length():
    assert _limits(max_name_length=128).max_name_length == 128
    with pytest.raises(ValueError):
        _limits(max_name_length=129)
    with pytest.raises(ValueError):
        _limits(max_name_length=10_000)


def test_the_worst_admitted_pattern_stays_cheap_at_the_maximum_name_length():
    import time
    # au plus 2 éléments variables : au plus (n+1)^2 chemins de retour arrière × O(n) = O(n^3) ; mesuré : quelques dizaines de ms à n = 128
    for pattern in (r"[a-z]*[a-z]*(?:a{1}){40}-", r".*.*(?:a{1}){100}-", r"[a-z]*[a-z]*[0-9]"):
        segment = scan.SegmentPattern(pattern)
        started = time.perf_counter()
        assert segment.matches("a" * 128 + "!") is False
        assert time.perf_counter() - started < 2.0                 # la marge absorbe une machine lente (mesure usuelle : < 0,05 s)


@pytest.mark.parametrize("segments", [
    ("final_holdout_access_claim.json",),                                                         # nom littéral : un Claim ne peut pas devenir « orphelin »
    (scan.SegmentPattern(r"[a-z_]+\.json"),),
    ("exposure", scan.SegmentPattern(r"\.exposure\.tmp\.[0-9a-f]{31}")),
    ("exposure", "x.exposure.tmp." + "0" * 32),
])
def test_a_temp_orphan_rule_must_use_exactly_the_publication_orphan_pattern_as_its_last_segment(segments):
    with pytest.raises(ValueError):
        scan.SourceRule(segments, scan.EntryClass.TEMP_ORPHAN_FILE)


def test_a_temp_orphan_rule_with_the_exact_pattern_is_accepted_at_any_location():
    rule = scan.SourceRule(("exposure", HEX64, scan.SegmentPattern(scan.EXPOSURE_TEMP_ORPHAN_PATTERN)), scan.EntryClass.TEMP_ORPHAN_FILE, tag="orphan")
    assert rule.matches(("exposure", INV, ORPHAN))
    other_classes = scan.SourceRule(("a",), scan.EntryClass.INERT_FILE)                         # les autres classes ne sont pas concernées
    assert other_classes.entry_class is scan.EntryClass.INERT_FILE


def test_the_parsed_value_is_a_fresh_copy_so_mutating_it_never_alters_the_proof(tmp_path):
    raw = b'{"campaign_id": "c1", "windows": [1, 2]}'
    observation = _by_path(_run(tmp_path, {"plan.json": raw}))["plan.json"]
    first = observation.value
    first["campaign_id"] = "FORGED"
    first["windows"].append(999)
    assert observation.value == {"campaign_id": "c1", "windows": [1, 2]}              # l'objet interne n'a pas bougé
    assert observation.value is not observation.value and observation.value == observation.value
    assert observation.content_bytes == raw and hashlib.sha256(observation.content_bytes).hexdigest() == observation.content_hash
    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.content_bytes = b"{}"
    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.content_hash = "0" * 64


def test_every_parsed_observation_carries_the_exact_bytes_that_match_its_hash_and_others_carry_none(tmp_path):
    files = {"plan.json": b'{"a": 1}', "experiments/e1.json": b"[1, 2]", "experiments/e2.json": b"{", "logs.txt": b"x", "stray.txt": b"y", "datasets": None}
    result = _run(tmp_path, files)
    for observation in result.observations:
        if observation.value_parsed:
            assert observation.content_bytes == files[observation.relative_path]
            assert hashlib.sha256(observation.content_bytes).hexdigest() == observation.content_hash
            assert observation.value == json.loads(files[observation.relative_path])
        else:
            assert observation.content_bytes is None and observation.value is None
    assert _by_path(result)["experiments/e2.json"].value_parsed is False and _by_path(result)["experiments/e2.json"].content_hash is not None


def _observation_kwargs(**overrides):
    base = dict(root_label="main", relative_path="plan.json", kind=scan.EntryKind.FILE, entry_class=scan.EntryClass.EXPOSING_JSON, anomaly=None,
                size=2, mtime_ns=1, st_ino=1, st_dev=1, content_hash=hashlib.sha256(b"{}").hexdigest(), value_parsed=True, content_bytes=b"{}")
    base.update(overrides)
    return base


def test_an_observation_cannot_be_built_with_bytes_that_contradict_its_hash():
    assert scan.ScanObservation(**_observation_kwargs()).value == {}
    for bad in (
        _observation_kwargs(content_bytes=b"[]"),                                        # octets ≠ hash
        _observation_kwargs(content_bytes=None),                                         # analysé sans octets
        _observation_kwargs(value_parsed=False),                                         # octets sans analyse
        _observation_kwargs(content_hash=None),
        _observation_kwargs(content_bytes="{}"),
    ):
        with pytest.raises((ValueError, TypeError)):
            scan.ScanObservation(**bad)


def test_an_unparsed_observation_cannot_carry_bytes_and_a_parsed_one_has_precise_construction_errors():
    with pytest.raises(ValueError):
        scan.ScanObservation(**_observation_kwargs(value_parsed=False, anomaly=scan.SourceAnomaly.INVALID_JSON))     # octets sans analyse
    for bad in (_observation_kwargs(content_hash=None), _observation_kwargs(content_bytes=None), _observation_kwargs(content_bytes="{}")):
        with pytest.raises(TypeError):
            scan.ScanObservation(**bad)
    with pytest.raises(ValueError):
        scan.ScanObservation(**_observation_kwargs(size=999))                  # taille observée ≠ octets conservés


def _plain(**overrides):
    base = dict(root_label="main", relative_path="x", kind=scan.EntryKind.FILE, entry_class=None, anomaly=None, size=None, mtime_ns=1, st_ino=1,
                st_dev=1, content_hash=None, value_parsed=False, content_bytes=None, rule_tag=None)
    base.update(overrides)
    return base


@pytest.mark.parametrize("valid", [
    _plain(anomaly=scan.SourceAnomaly.UNKNOWN_FILE),
    _plain(anomaly=scan.SourceAnomaly.UNKNOWN_TEMP_FILE),
    _plain(kind=scan.EntryKind.DIRECTORY, anomaly=scan.SourceAnomaly.UNKNOWN_DIRECTORY),
    _plain(entry_class=scan.EntryClass.INERT_FILE),
    _plain(entry_class=scan.EntryClass.TEMP_ORPHAN_FILE),
    _plain(kind=scan.EntryKind.DIRECTORY, entry_class=scan.EntryClass.INERT_DIRECTORY),
    _plain(kind=scan.EntryKind.DIRECTORY, entry_class=scan.EntryClass.STRUCTURAL_DIRECTORY),
    _plain(entry_class=scan.EntryClass.INERT_DIRECTORY, anomaly=scan.SourceAnomaly.KIND_MISMATCH),                  # fichier à la place d'un répertoire
    _plain(kind=scan.EntryKind.DIRECTORY, entry_class=scan.EntryClass.EXPOSING_JSON, anomaly=scan.SourceAnomaly.KIND_MISMATCH),
    _plain(entry_class=scan.EntryClass.INFORMATIVE_JSON, anomaly=scan.SourceAnomaly.INVALID_JSON, content_hash="0" * 64),
    _plain(entry_class=scan.EntryClass.EXPOSING_JSON, anomaly=scan.SourceAnomaly.TOO_LARGE),
    _plain(entry_class=scan.EntryClass.EXPOSING_JSON, anomaly=scan.SourceAnomaly.UNREADABLE),
])
def test_every_legitimate_scan_outcome_is_a_constructible_observation(valid):
    assert scan.ScanObservation(**valid).value is None


@pytest.mark.parametrize("invalid", [
    _plain(),                                                                                                       # hors table sans anomalie
    _plain(anomaly=scan.SourceAnomaly.INVALID_JSON),                                                                # hors table avec une anomalie de contenu
    _plain(kind=scan.EntryKind.FILE, anomaly=scan.SourceAnomaly.UNKNOWN_DIRECTORY),
    _plain(kind=scan.EntryKind.DIRECTORY, anomaly=scan.SourceAnomaly.UNKNOWN_FILE),
    _plain(entry_class=scan.EntryClass.EXPOSING_JSON, anomaly=scan.SourceAnomaly.UNKNOWN_FILE),                      # classe connue avec une anomalie d'inconnu
    _plain(kind=scan.EntryKind.DIRECTORY, entry_class=scan.EntryClass.EXPOSING_JSON),                               # répertoire sous une règle de fichier lu, sans anomalie
    _plain(entry_class=scan.EntryClass.INERT_DIRECTORY),                                                           # fichier sous une règle de répertoire, sans anomalie
    _plain(entry_class=scan.EntryClass.EXPOSING_JSON, anomaly=scan.SourceAnomaly.KIND_MISMATCH),                    # KIND_MISMATCH sans écart de nature
    _plain(entry_class=scan.EntryClass.INERT_FILE, anomaly=scan.SourceAnomaly.INVALID_JSON),                        # anomalie de contenu sur une entrée non lue
    _plain(kind=scan.EntryKind.DIRECTORY, entry_class=scan.EntryClass.STRUCTURAL_DIRECTORY, anomaly=scan.SourceAnomaly.TOO_LARGE),
    _plain(entry_class=scan.EntryClass.EXPOSING_JSON),                                                              # fichier lu « propre » sans analyse
])
def test_inconsistent_observation_states_are_refused_at_construction(invalid):
    with pytest.raises(ValueError):
        scan.ScanObservation(**invalid)


@pytest.mark.parametrize("bad", [dict(attempts_used=2), dict(bytes_read=2_000_000)])
def test_an_exposure_scan_cannot_claim_more_attempts_or_bytes_than_its_limits_allow(bad):
    with pytest.raises(ValueError):
        scan.ExposureScan(**_scan_kwargs(**bad))


@pytest.mark.parametrize("bad", [
    dict(label=1), dict(path=b"x"), dict(st_dev="1"), dict(st_ino=1.5), dict(may_be_empty=1), dict(st_dev=True),
])
def test_a_scanned_root_validates_its_field_types(bad):
    base = dict(label="main", path="C:/x", st_dev=1, st_ino=2, may_be_empty=False)
    assert scan.ScannedRoot(**base).may_be_empty is False
    with pytest.raises(TypeError):
        scan.ScannedRoot(**{**base, **bad})


def test_the_scan_pins_the_exact_rule_table_it_applied_through_a_digest(tmp_path):
    rules = (
        scan.SourceRule(("plan.json",), scan.EntryClass.EXPOSING_JSON, scan.JsonKind.OBJECT, tag="plan"),
        scan.SourceRule(("datasets",), scan.EntryClass.INERT_DIRECTORY),
        scan.SourceRule(("experiments", scan.SegmentPattern(r"e[0-9]\.json")), scan.EntryClass.INFORMATIVE_JSON),
    )
    expected_lines = sorted([
        json.dumps({"segments": ["plan.json"], "entry_class": "EXPOSING_JSON", "expected_json": "OBJECT", "tag": "plan"}, sort_keys=True, separators=(",", ":")),
        json.dumps({"segments": ["datasets"], "entry_class": "INERT_DIRECTORY", "expected_json": None, "tag": None}, sort_keys=True, separators=(",", ":")),
        json.dumps({"segments": ["experiments", {"regex": r"e[0-9]\.json"}], "entry_class": "INFORMATIVE_JSON", "expected_json": None, "tag": None},
                   sort_keys=True, separators=(",", ":")),
    ])
    expected = hashlib.sha256("\n".join(expected_lines).encode("ascii")).hexdigest()
    result = _run(tmp_path, {"plan.json": b"{}", "datasets": None}, rules=rules)
    assert result.rules_digest == expected
    shutil.rmtree(tmp_path / "root")
    assert _run(tmp_path, {"plan.json": b"{}", "datasets": None}, rules=tuple(reversed(rules))).rules_digest == expected      # indépendant de l'ordre
    changed = (rules[0], scan.SourceRule(("datasets",), scan.EntryClass.INERT_FILE), rules[2])
    shutil.rmtree(tmp_path / "root")
    assert _run(tmp_path, {"plan.json": b"{}", "datasets": b"x"}, rules=changed).rules_digest != expected                      # toute règle modifiée change le digest
    shutil.rmtree(tmp_path / "root")
    assert _run(tmp_path, {"plan.json": b"{}"}, rules=()).rules_digest == hashlib.sha256(b"").hexdigest()


def test_a_scan_run_with_test_hooks_is_marked_so_that_no_downstream_layer_can_mistake_it_for_a_production_scan(tmp_path):
    plain = _run(tmp_path, BASE_FILES)
    assert plain.hooks_used is False
    for hooks in (scan.ScanHooks(), scan.ScanHooks(after_first_pass=lambda attempt: "FAKE FACT"), scan.ScanHooks(after_file_read=lambda label, relative: None)):
        shutil.rmtree(tmp_path / "root")
        hooked = _run(tmp_path, BASE_FILES, hooks=hooks)
        assert hooked.hooks_used is True
        assert [o.relative_path for o in hooked.observations] == [o.relative_path for o in plain.observations]       # un hook n'injecte aucun fait


@pytest.mark.parametrize("kind", ["grown", "shrunk"])
def test_the_number_of_bytes_read_must_equal_the_observed_size_otherwise_the_listing_is_unstable(tmp_path, monkeypatch, kind):
    _tree(tmp_path / "root", BASE_FILES)
    real_read = os.read

    def distorted(descriptor, count):
        data = real_read(descriptor, count)
        if not data:
            return data
        return data + b" " if kind == "grown" else data[:-1]

    monkeypatch.setattr(os, "read", distorted)
    with pytest.raises(scan.ExposureScanRefusal) as info:
        scan.scan_audit_roots((scan.AuditRoot("main", tmp_path / "root"),), RULES, _limits(max_attempts=2))
    assert info.value.failure is scan.StructuralFailure.UNSTABLE_LISTING


@pytest.mark.parametrize("zero_width", [
    r"(?:\b){10000000}x", r"^abc$", r"abc$", r"^abc", r"a\Bb", r"\Aabc", r"abc\Z", r"\bword", r"(?:){5}x", r"(){5}x", r"(?:(?:(?:\b){1000}){1000}){1000}x",
    r"a{0}b", r"a{129}", r"(?:a{1}){500}", r"[0-9]{1000}",
])
def test_segment_pattern_refuses_zero_width_constructs_and_oversized_fixed_repeats_whose_cost_does_not_depend_on_the_name(zero_width):
    with pytest.raises(ValueError):
        scan.SegmentPattern(zero_width)


@pytest.mark.parametrize("safe", [r"a{128}", r"[0-9a-f]{64}", r"\.exposure\.tmp\.[0-9a-f]{32}", r"declaration_[0-9]{4}\.json", r"[\b]x"])
def test_segment_pattern_still_accepts_bounded_fixed_repeats_and_a_backspace_inside_a_class(safe):
    assert scan.SegmentPattern(safe).matches("zzz") in (True, False)


@pytest.mark.parametrize("rule", [
    scan.SourceRule(("declaration_0002.json.tmp",), scan.EntryClass.INERT_FILE),
    scan.SourceRule((scan.SegmentPattern(r"\.exposure\.tmp\.[0-9a-f]{31}"),), scan.EntryClass.INERT_FILE),
    scan.SourceRule(("draft.tmp",), scan.EntryClass.INFORMATIVE_JSON),
    scan.SourceRule(("draft.tmp",), scan.EntryClass.EXPOSING_JSON),
    scan.SourceRule(("scratch.tmp",), scan.EntryClass.INERT_DIRECTORY),
])
def test_only_a_temp_orphan_rule_can_classify_a_temporary_name_so_no_other_rule_can_mask_it(tmp_path, opened, rule):
    name = rule.segments[0] if isinstance(rule.segments[0], str) else ".exposure.tmp." + "0" * 31
    files = {"plan.json": b"{}", name: b"{}" if "scratch" not in name else None}
    result = _run(tmp_path, files, rules=(rule,))
    observation = _by_path(result)[name]
    assert observation.entry_class is None and observation.rule_tag is None and not observation.value_parsed and observation.content_hash is None
    assert observation.anomaly in (scan.SourceAnomaly.UNKNOWN_TEMP_FILE, scan.SourceAnomaly.UNKNOWN_DIRECTORY)
    assert not any(p.endswith(name) for p in opened)                      # jamais ouvert, même sous une règle de classe lue


def test_a_temporary_name_matching_no_rule_or_the_orphan_rule_keeps_its_previous_behaviour(tmp_path):
    rules = (scan.SourceRule(("exposure", HEX64, scan.SegmentPattern(scan.EXPOSURE_TEMP_ORPHAN_PATTERN)), scan.EntryClass.TEMP_ORPHAN_FILE, tag="o"),
             scan.SourceRule(("exposure",), scan.EntryClass.STRUCTURAL_DIRECTORY), scan.SourceRule(("exposure", HEX64), scan.EntryClass.STRUCTURAL_DIRECTORY))
    by_path = _by_path(_run(tmp_path, {f"exposure/{INV}/{ORPHAN}": b"{", "stray.tmp": b""}, rules=rules))
    assert by_path[f"exposure/{INV}/{ORPHAN}"].entry_class is scan.EntryClass.TEMP_ORPHAN_FILE and by_path[f"exposure/{INV}/{ORPHAN}"].rule_tag == "o"
    assert by_path["stray.tmp"].anomaly is scan.SourceAnomaly.UNKNOWN_TEMP_FILE


def test_a_file_whose_stream_is_longer_than_its_declared_size_is_never_hashed_truncated(tmp_path, monkeypatch):
    payload = b'{"a": 1}'
    _tree(tmp_path / "root", {"plan.json": payload})
    real_read = os.read
    state = {}

    def lying(descriptor, count):
        data = real_read(descriptor, count)
        state[descriptor] = state.get(descriptor, 0) + 1
        return b"xyz" if not data and state[descriptor] >= 2 else data       # le flux continue après les `st_size` octets annoncés

    monkeypatch.setattr(os, "read", lying)
    limits = _limits(max_json_bytes=len(payload), max_total_read_bytes=len(payload), max_attempts=2)
    with pytest.raises(scan.ExposureScanRefusal) as info:
        scan.scan_audit_roots((scan.AuditRoot("main", tmp_path / "root"),), RULES, limits)
    assert info.value.failure is scan.StructuralFailure.UNSTABLE_LISTING


def test_a_replaced_inode_with_identical_bytes_size_and_mtime_between_the_passes_is_unstable(tmp_path):
    root = tmp_path / "root"
    swap = tmp_path / "swap.json"

    def replace_by_identical_copy():
        before = os.stat(root / "plan.json")
        swap.write_bytes((root / "plan.json").read_bytes())
        os.utime(swap, ns=(before.st_atime_ns, before.st_mtime_ns))
        os.replace(swap, root / "plan.json")

    _unstable(tmp_path, replace_by_identical_copy, files={"plan.json": b'{"a": 1}', "logs.txt": b"x"})


def test_files_are_opened_non_blocking_where_the_platform_allows_it():
    if not hasattr(os, "O_NONBLOCK"):
        pytest.skip("O_NONBLOCK absent sous Windows : le risque de blocage sur un FIFO substitué est POSIX uniquement")
    assert scan._READ_FLAGS & os.O_NONBLOCK


def test_scan_observation_invariants_forbid_a_read_file_that_looks_clean_without_being_parsed(tmp_path):
    broken = _by_path(_run(tmp_path, {"plan.json": b"{"}, rules=(scan.SourceRule(("plan.json",), scan.EntryClass.EXPOSING_JSON),)))["plan.json"]
    assert broken.anomaly is scan.SourceAnomaly.INVALID_JSON
    with pytest.raises(ValueError):
        dataclasses.replace(broken, anomaly=None)                      # « propre » en apparence mais non analysé
    with pytest.raises(ValueError):
        scan.ScanObservation(**_observation_kwargs(anomaly=scan.SourceAnomaly.INVALID_JSON))        # analysé ET en anomalie
    with pytest.raises(ValueError):
        scan.ScanObservation(**_observation_kwargs(entry_class=scan.EntryClass.INERT_FILE))         # analysé alors que la classe n'est pas lue
    with pytest.raises(ValueError):
        scan.ScanObservation(**_observation_kwargs(kind=scan.EntryKind.DIRECTORY, entry_class=scan.EntryClass.STRUCTURAL_DIRECTORY))
    assert scan.ScanObservation(**_observation_kwargs(value_parsed=False, content_bytes=None, content_hash=None, anomaly=scan.SourceAnomaly.UNREADABLE)).value is None


def test_a_proof_tampered_with_after_construction_is_detected_when_the_value_is_read():
    observation = scan.ScanObservation(**_observation_kwargs())
    object.__setattr__(observation, "content_bytes", b'{"k": "EVIL"}')    # contournement délibéré de l'immutabilité
    with pytest.raises(ValueError):
        observation.value


def test_the_scan_pins_the_limits_and_the_emptiness_policy_it_ran_under(tmp_path):
    limits = _limits(max_json_bytes=4096, max_total_read_bytes=8192, max_attempts=2)
    _tree(tmp_path / "root", BASE_FILES)
    result = scan.scan_audit_roots((scan.AuditRoot("main", tmp_path / "root", may_be_empty=True),), RULES, limits)
    assert result.limits == limits and result.limits is limits
    assert [(r.label, r.may_be_empty) for r in result.roots] == [("main", True)]
    other = scan.scan_audit_roots((scan.AuditRoot("main", tmp_path / "root"),), RULES, limits)
    assert [r.may_be_empty for r in other.roots] == [False] and other.roots != result.roots


def _scan_kwargs(**overrides):
    base = dict(roots=(), observations=(), attempts_used=1, bytes_read=0, rules_digest="0" * 64, hooks_used=False, limits=_limits())
    base.update(overrides)
    return base


@pytest.mark.parametrize("bad", [
    dict(roots=[]), dict(observations=[]), dict(roots=(1,)), dict(observations=("x",)), dict(attempts_used=0), dict(attempts_used=True),
    dict(bytes_read=-1), dict(bytes_read=1.5), dict(rules_digest="x"), dict(rules_digest="A" * 64), dict(rules_digest="0" * 63), dict(hooks_used=0),
    dict(limits=None),
])
def test_an_exposure_scan_cannot_be_built_with_inconsistent_metadata(bad):
    assert scan.ExposureScan(**_scan_kwargs()).hooks_used is False
    with pytest.raises((ValueError, TypeError)):
        scan.ExposureScan(**_scan_kwargs(**bad))


def test_segment_pattern_accepts_the_octal_null_escape_which_is_not_a_backreference():
    assert scan.SegmentPattern(r"a\0b").matches("a\x00b") is True


@pytest.mark.parametrize("backreference", [r"(a*)\1b", r"(a)\1", r"(a*)(a*)(a*)\1\2\3b", r"(?:a)\9"])
def test_segment_pattern_refuses_backreferences(backreference):
    with pytest.raises(ValueError):
        scan.SegmentPattern(backreference)


def test_the_variable_element_cap_also_counts_an_element_at_the_very_end_of_the_pattern():
    with pytest.raises(ValueError):
        scan.SegmentPattern("b[ab]*[ab]*[ab]*")
    assert scan.SegmentPattern("b[ab]*[ab]*").matches("bab") is True


def test_building_a_segment_pattern_never_alters_the_global_warning_filters():
    import warnings
    before = list(warnings.filters)
    scan.SegmentPattern(r"job_[0-9]+")
    for ambiguous in ("[[a]x", "[a&&b]x"):
        with pytest.raises(ValueError):
            scan.SegmentPattern(ambiguous)
    assert list(warnings.filters) == before


@pytest.mark.parametrize("risky", [r"(a|b){2,}z", r"(a+){2,}b", r"(?:a|b)*c"])
def test_segment_pattern_refuses_unbounded_repetitions_of_variable_groups(risky):
    with pytest.raises(ValueError):
        scan.SegmentPattern(risky)


@pytest.mark.parametrize("safe", [r"(?:[]+])+b", r"(?:[^]+])+b", r"(?:a\+)+b", r"(?:\()+b", r"(?:[(])+b"])
def test_the_group_analyser_ignores_escaped_and_bracketed_metacharacters(safe):
    assert scan.SegmentPattern(safe).matches("zzz") in (True, False)


@pytest.mark.parametrize("pattern", ["[[:alpha:]]x", "[a&&b]x", "[[a]x", "[a--b]x"])
def test_regex_future_warnings_about_set_syntax_become_value_errors(pattern):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(ValueError):
            scan.SegmentPattern(pattern)


@pytest.mark.parametrize("prefixed", ["//?/C:/x/a", "//./C:/x/a", "//?/UNC/server/share", r"\/?/C:/x", r"/\?\C:/x", r"/\.\C:/x"])
def test_audit_root_refuses_extended_path_prefixes_written_with_forward_slashes_too(prefixed):
    with pytest.raises(ValueError):
        scan.AuditRoot("r", prefixed)


def test_the_root_path_length_cap_is_exact(tmp_path):
    base = str(tmp_path) + os.sep
    assert len(scan.AuditRoot("r", base + "x" * (4096 - len(base))).path) == 4096
    with pytest.raises(ValueError):
        scan.AuditRoot("r", base + "x" * (4097 - len(base)))


@pytest.mark.parametrize("huge", ["a{99999999999}", "a{4294967296}", "a{0,4294967295}"])
def test_segment_pattern_turns_oversized_repetition_counts_into_value_errors(huge):
    with pytest.raises(ValueError):
        scan.SegmentPattern(huge)


@pytest.mark.parametrize("safe", [r"[0-9a-f]{64}", r"job_[0-9]+", r"(ab)+", r"(?:x|y)\.json", r"declaration_[0-9]{4}\.json",
                                  r"[0-9]{4}(?:-[0-9]{2}){2}\.json", r"(?:[0-9]{4})+\.json", r"(ab){2,3}z"])
def test_segment_pattern_still_accepts_simple_closed_patterns(safe):
    assert scan.SegmentPattern(safe).matches("zzz") in (True, False)


def _make_alias(target, link):
    """Alias de répertoire : jonction sous Windows (sans privilège), lien symbolique ailleurs."""
    if IS_WINDOWS:
        _make_junction(target, link)
    else:
        _make_symlink(target, link, is_dir=True)


def test_roots_nested_through_a_link_in_a_parent_component_overlap(tmp_path):
    real = tmp_path / "real"
    _tree(real, {"plan.json": b"{}", "sub/plan.json": b"{}"})
    _make_alias(real, tmp_path / "alias")
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("a", real), scan.AuditRoot("b", tmp_path / "alias" / "sub")))
    assert error.failure is scan.StructuralFailure.ROOT_OVERLAP
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("a", real / "sub"), scan.AuditRoot("b", tmp_path / "alias")))
    assert error.failure is scan.StructuralFailure.ROOT_OVERLAP


def test_an_alias_in_the_first_position_is_detected_as_well(tmp_path):
    real = tmp_path / "real"
    _tree(real, {"plan.json": b"{}", "sub/plan.json": b"{}"})
    _make_alias(real, tmp_path / "alias")
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("a", tmp_path / "alias" / "sub"), scan.AuditRoot("b", real)))
    assert error.failure is scan.StructuralFailure.ROOT_OVERLAP
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("a", tmp_path / "alias"), scan.AuditRoot("b", real / "sub")))
    assert error.failure is scan.StructuralFailure.ROOT_OVERLAP


@pytest.mark.parametrize("unsupported", [r"(?i)abc", r"(?P<n>a)b", r"(?=a)b", r"(?<=a)b", r"(?!a)b"])
def test_segment_pattern_refuses_group_constructions_it_does_not_analyse(unsupported):
    with pytest.raises(ValueError):
        scan.SegmentPattern(unsupported)


@pytest.mark.parametrize("prefixed", [r"\\?\C:\x\a", r"\\.\C:\x\a", r"\\?\UNC\server\share"])
def test_audit_root_refuses_windows_extended_path_prefixes(prefixed):
    with pytest.raises(ValueError):
        scan.AuditRoot("r", prefixed)


def test_audit_root_refuses_absurdly_long_paths(tmp_path):
    with pytest.raises(ValueError):
        scan.AuditRoot("r", str(tmp_path) + os.sep + "x" * 5000)


def test_a_single_root_below_a_linked_ancestor_is_accepted_because_ancestors_are_trusted_configuration(tmp_path):
    real = tmp_path / "real"
    _tree(real, {"sub/plan.json": b"{}"})
    _make_alias(real, tmp_path / "alias")
    assert len(_scan_roots(scan.AuditRoot("only", tmp_path / "alias" / "sub")).observations) == 1


@pytest.mark.skipif(not IS_WINDOWS, reason="comparaison insensible à la casse propre à Windows")
def test_nested_roots_that_differ_only_by_case_overlap_on_windows(tmp_path):
    _tree(tmp_path / "Real", {"plan.json": b"{}", "sub/plan.json": b"{}"})
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("a", tmp_path / "Real"), scan.AuditRoot("b", str(tmp_path / "Real" / "sub").lower())))
    assert error.failure is scan.StructuralFailure.ROOT_OVERLAP


@pytest.mark.skipif(not IS_WINDOWS, reason="comparaison insensible à la casse propre à Windows")
def test_the_textual_overlap_ignores_case_even_for_paths_that_do_not_exist(tmp_path):
    # racines inexistantes : `realpath` ne peut pas corriger la casse, seule la comparaison textuelle (normcase) les rapproche
    outer = tmp_path / "Absent"
    inner = str(tmp_path / "ABSENT" / "sub")
    error = _refusal(lambda: _scan_roots(scan.AuditRoot("a", outer), scan.AuditRoot("b", inner)))
    assert error.failure is scan.StructuralFailure.ROOT_OVERLAP


def test_rule_tags_are_carried_to_observations_so_that_b3_can_link_them_to_its_own_table(tmp_path):
    rules = (
        scan.SourceRule(("plan.json",), scan.EntryClass.EXPOSING_JSON, scan.JsonKind.OBJECT, tag="campaign_plan"),
        scan.SourceRule(("logs.txt",), scan.EntryClass.INERT_FILE, tag="log"),
        scan.SourceRule(("experiments",), scan.EntryClass.STRUCTURAL_DIRECTORY, tag="experiments_dir"),
        scan.SourceRule(("experiments", scan.SegmentPattern(r"e[0-9]\.json")), scan.EntryClass.INFORMATIVE_JSON, tag="experiment"),
        scan.SourceRule(("datasets",), scan.EntryClass.INERT_DIRECTORY, tag="data"),
    )
    files = {"plan.json": b"{}", "logs.txt": b"x", "experiments/e1.json": b"{", "experiments/other.json": b"{}", "datasets": b"file", "stray.txt": b"x"}
    by_path = _by_path(_run(tmp_path, files, rules=rules))
    assert {p: o.rule_tag for p, o in by_path.items()} == {
        "plan.json": "campaign_plan", "logs.txt": "log", "experiments": "experiments_dir", "experiments/e1.json": "experiment",
        "experiments/other.json": None, "datasets": "data", "stray.txt": None,
    }
    assert by_path["experiments/e1.json"].anomaly is scan.SourceAnomaly.INVALID_JSON          # l'étiquette accompagne aussi une anomalie
    assert by_path["datasets"].anomaly is scan.SourceAnomaly.KIND_MISMATCH and by_path["datasets"].entry_class is scan.EntryClass.INERT_DIRECTORY


@pytest.mark.parametrize("bad", ["", " a", "a b", "é", "a/b", "a" * 65])
def test_a_rule_tag_must_be_a_short_portable_identifier(bad):
    with pytest.raises(ValueError):
        scan.SourceRule(("a",), scan.EntryClass.INERT_FILE, tag=bad)
    for wrong_type in (1, b"x", ["x"]):
        with pytest.raises(TypeError):
            scan.SourceRule(("a",), scan.EntryClass.INERT_FILE, tag=wrong_type)


def test_raw_bytes_are_hashed_exactly_even_with_crlf_and_a_control_z_byte(tmp_path):
    crlf_json = b'{"a":\r\n 1,\r\n "b": "x"}\r\n'
    with_ctrl_z = b'{"a": 1}\r\n\x1a'
    result = _run(tmp_path, {"plan.json": crlf_json, "experiments/e1.json": with_ctrl_z})
    for relative, raw in (("plan.json", crlf_json), ("experiments/e1.json", with_ctrl_z)):
        observation = _by_path(result)[relative]
        assert observation.content_hash == hashlib.sha256(raw).hexdigest() and observation.size == len(raw)
    assert _by_path(result)["plan.json"].anomaly is None
    assert _by_path(result)["experiments/e1.json"].anomaly is scan.SourceAnomaly.INVALID_JSON   # le 0x1A final n'est pas silencieusement tronqué


def test_the_entry_cap_is_cumulative_across_directories(tmp_path):
    files = {"plan.json": b"{}", "logs.txt": b"x", "experiments/e1.json": b"{}", "experiments/e2.json": b"{}", "experiments/e3.json": b"{}"}
    assert len(_run(tmp_path, files, max_entries=6).observations) == 6          # 3 entrées à la racine + 3 dans `experiments`
    error = _refusal(lambda: _run(tmp_path, {}, max_entries=5))
    assert error.failure is scan.StructuralFailure.LIMIT_EXCEEDED and "max_entries" in error.detail


def test_a_subdirectory_that_vanishes_between_discovery_and_listing_is_instability(tmp_path, monkeypatch):
    _tree(tmp_path / "root", BASE_FILES)
    real_scandir = os.scandir
    state = {"raised": 0}

    def vanishing(path):
        if os.fspath(path).endswith("experiments") and state["raised"] < 1:
            state["raised"] += 1
            raise FileNotFoundError(2, "disparu")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", vanishing)
    result = scan.scan_audit_roots((scan.AuditRoot("main", tmp_path / "root"),), RULES, _limits(max_attempts=2))
    assert result.attempts_used == 2 and "experiments/e1.json" in _by_path(result)


def test_an_uppercase_tmp_extension_is_still_an_unknown_temp_file(tmp_path):
    by_path = _by_path(_run(tmp_path, {"plan.json": b"{}", "CACHE.TMP": b"", "Data.Tmp.bak": b""}))
    assert by_path["CACHE.TMP"].anomaly is scan.SourceAnomaly.UNKNOWN_TEMP_FILE and by_path["Data.Tmp.bak"].anomaly is scan.SourceAnomaly.UNKNOWN_TEMP_FILE


def test_a_misplaced_or_malformed_orphan_is_always_reported_as_an_unknown_temp_file(tmp_path):
    names = [f"exposure/{ORPHAN}", f"exposure/{INV}/.exposure.tmp." + "0" * 31, f"exposure/{INV}/.exposure.tmp." + "G" * 32, f"exposure/{INV}/x.tmp.y"]
    by_path = _by_path(_run(tmp_path, {name: b"{" for name in names}))
    assert {by_path[name].anomaly for name in names} == {scan.SourceAnomaly.UNKNOWN_TEMP_FILE}
