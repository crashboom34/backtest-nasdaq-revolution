"""
tests/test_gate_v_exposure_scan_hashed.py — AF-V-07 K1 Étape 2, décision D8 : amendement ADDITIF du scanner B2 (`gate_v_exposure_scan.py`).

D8 (acceptée pour cette mission seulement) : (1) classe `HASHED_FILE` (fichier reconnu, lu en flux pour son seul SHA-256, jamais interprété) ;
(2) second motif strict d'orphelin de publication `<cible>.<32 hexadécimaux>.tmp` (producteur : `atomic_json_store.save_atomic`) ; (3) plafonds
explicites ; (4) contrats, règles et digests historiques inchangés. Le scanner reste un OBSERVATEUR de faits : aucun finding, aucun verdict.

Fixtures SYNTHÉTIQUES uniquement (`tmp_path`) : aucune donnée de marché, aucun `results/` réel, aucun FINAL_HOLDOUT. Les valeurs attendues sont des
littéraux (digests historiques figés AVANT la modification) ou calculées avec `hashlib` dans ce fichier, jamais avec le code testé.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gate_v_exposure_scan as scan

HEX32 = "0123456789abcdef0123456789abcdef"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
# Digest de `_rules_digest` d'une table HISTORIQUE (INFORMATIVE_JSON + INERT_FILE + STRUCTURAL_DIRECTORY + orphelin `exposure`), calculé avec le
# code B2 publié AVANT D8 (HEAD 6fb8222) : il ne doit jamais changer.
GOLDEN_HISTORICAL_TABLE_DIGEST = "47e4a18760e6a4428cbc2e2cf0dbd78046f1f7d3a8db81f42e4e63d0fd5d30da"
B3_FROZEN_DIGESTS = {
    ("gate_v_exposure_interpreters_v2", "RESULTS"): "9014a865e7c5c4fea0ec7fc4cbcd3e8d76357a51693c339981e50f523ae51960",
    ("gate_v_exposure_interpreters_v2", "CAMPAIGN_DIR"): "cb94f97f1b2c53f8839f90547b3ad619e5a3a64dacfb857071554d329a6a6fa7",
    ("gate_v_exposure_interpreters_v3", "CAMPAIGN_DIR"): "7cc0cb309210f43cc0e6e00a2a220483196fdc3ff1d7e285aff758313de2e04f",
    ("gate_v_exposure_interpreters_v4", "CAMPAIGN_DIR"): "9c05f8b068ac86d321c0d9889df0f3c0f1e015fdd8b17d208479554b1badb43b",
    ("gate_v_exposure_interpreters_v4", "SPLIT_PLAN_DIR"): "e98082afc0482e2afdce61884f0da5f264a943defd666ca4aedd8b75ec217f29",
}
HISTORICAL_LIMIT_NAMES = ("max_roots", "max_entries", "max_depth", "max_json_bytes", "max_total_read_bytes", "max_json_depth",
                          "max_name_length", "max_path_length", "max_attempts")

HASHED = scan.EntryClass.HASHED_FILE if hasattr(scan.EntryClass, "HASHED_FILE") else None


def limits(**overrides):
    values = dict(max_roots=4, max_entries=1000, max_depth=8, max_json_bytes=4096, max_total_read_bytes=65536, max_json_depth=16,
                  max_name_length=100, max_path_length=600, max_attempts=2)
    values.update(overrides)
    return scan.ScanLimits(**values)


def hash_limits(**overrides):
    values = dict(max_hashed_file_bytes=1024, max_total_hashed_bytes=8192, max_hashed_files=16)
    values.update(overrides)
    return scan.HashLimits(**values)


def make_tree(base: Path, files: dict) -> Path:
    root = base / "root"
    root.mkdir(parents=True, exist_ok=True)
    for relative, data in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


def refused(call, failure):
    with pytest.raises(scan.ExposureScanRefusal) as info:
        call()
    assert info.value.failure is failure, info.value
    return info.value


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ══ D8-A : nouvelle classe, invariants des observations, plafonds ═════════════════════════════════════════════════════════════════
def test_hashed_file_is_a_file_class_that_is_neither_read_nor_descended_and_the_other_classes_are_unchanged():
    assert HASHED is not None and HASHED.value == "HASHED_FILE"
    assert (HASHED.is_file, HASHED.is_read, HASHED.is_hashed, HASHED.is_directory, HASHED.is_descended) == (True, False, True, False, False)
    others = [c for c in scan.EntryClass if c is not HASHED]
    assert [c.value for c in others] == ["EXPOSING_JSON", "INFORMATIVE_JSON", "INERT_FILE", "TEMP_ORPHAN_FILE", "INERT_DIRECTORY", "STRUCTURAL_DIRECTORY"]
    assert not any(c.is_hashed for c in others)
    assert {c for c in scan.EntryClass if c.is_read} == {scan.EntryClass.EXPOSING_JSON, scan.EntryClass.INFORMATIVE_JSON}
    assert {c for c in scan.EntryClass if c.is_file} == {scan.EntryClass.EXPOSING_JSON, scan.EntryClass.INFORMATIVE_JSON, scan.EntryClass.INERT_FILE,
                                                         scan.EntryClass.TEMP_ORPHAN_FILE, HASHED}


def test_a_hashed_file_rule_never_carries_a_json_expectation():
    assert scan.SourceRule(("walk_forward", "manifest.json"), HASHED, tag="wf_manifest").entry_class is HASHED
    with pytest.raises(ValueError):
        scan.SourceRule(("walk_forward", "manifest.json"), HASHED, expected_json=scan.JsonKind.OBJECT)


def observation(**overrides):
    values = dict(root_label="main", relative_path="walk_forward/manifest.json", kind=scan.EntryKind.FILE, entry_class=HASHED, anomaly=None, size=3,
                  mtime_ns=1, st_ino=2, st_dev=3, content_hash=sha(b"abc"), value_parsed=False, content_bytes=None, rule_tag="wf_manifest")
    values.update(overrides)
    return scan.ScanObservation(**values)


def test_a_clean_hashed_observation_carries_a_hash_and_size_but_never_content_or_a_parsed_value():
    clean = observation()
    assert clean.content_hash == sha(b"abc") and clean.content_bytes is None and clean.value_parsed is False and clean.value is None


@pytest.mark.parametrize("overrides", [
    dict(content_hash=None),                                    # « propre » sans hash : jamais
    dict(content_hash="AB" * 32),                               # hexadécimal non minuscule
    dict(content_hash="ab" * 31),
    dict(content_hash=12),
    dict(size=None),
    dict(value_parsed=True, content_bytes=b"abc"),              # un fichier haché n'est jamais interprété
    dict(content_bytes=b"abc"),                                 # ni conservé en mémoire
    dict(anomaly=scan.SourceAnomaly.TOO_LARGE),                 # anomalie => aucun hash utilisable
    dict(anomaly=scan.SourceAnomaly.UNREADABLE),
    dict(anomaly=scan.SourceAnomaly.INVALID_JSON, content_hash=None),
    dict(anomaly=scan.SourceAnomaly.UNKNOWN_FILE),              # une entrée reconnue ne porte jamais UNKNOWN_*
])
def test_an_inconsistent_hashed_observation_cannot_be_constructed(overrides):
    with pytest.raises((ValueError, TypeError)):
        observation(**overrides)


@pytest.mark.parametrize("anomaly", [scan.SourceAnomaly.TOO_LARGE, scan.SourceAnomaly.UNREADABLE])
def test_a_hashed_observation_with_a_size_or_read_anomaly_has_no_usable_hash(anomaly):
    assert observation(anomaly=anomaly, content_hash=None).content_hash is None


@pytest.mark.parametrize("forged", [
    dict(content_hash=sha(b"x"), size=None),
    dict(content_hash=None, size=3),
    dict(content_hash=sha(b"x"), size=3),
])
def test_a_hashed_class_on_a_directory_never_carries_a_hash_or_a_size(forged):
    with pytest.raises(ValueError):
        observation(kind=scan.EntryKind.DIRECTORY, anomaly=scan.SourceAnomaly.KIND_MISMATCH, **forged)


def test_a_hashed_class_on_a_directory_is_a_kind_mismatch_only():
    mismatch = observation(kind=scan.EntryKind.DIRECTORY, anomaly=scan.SourceAnomaly.KIND_MISMATCH, size=None, content_hash=None)
    assert mismatch.anomaly is scan.SourceAnomaly.KIND_MISMATCH
    with pytest.raises(ValueError):
        observation(kind=scan.EntryKind.DIRECTORY, anomaly=None, size=None, content_hash=None)


def test_hash_limits_require_every_bound_explicitly_by_keyword_with_strict_positive_integers():
    assert hash_limits().max_hashed_files == 16
    with pytest.raises(TypeError):
        scan.HashLimits(1024, 8192, 16)                                    # positionnels refusés
    with pytest.raises(TypeError):
        scan.HashLimits(max_hashed_file_bytes=1024, max_total_hashed_bytes=8192)    # aucune valeur par défaut cachée
    for name in ("max_hashed_file_bytes", "max_total_hashed_bytes", "max_hashed_files"):
        for bad in (0, -1, True, 1.0, "1", None):
            with pytest.raises((TypeError, ValueError)):
                hash_limits(**{name: bad})
    with pytest.raises(ValueError):
        hash_limits(max_hashed_file_bytes=9000, max_total_hashed_bytes=8192)       # un fichier ne dépasse pas le cumul
    assert hash_limits(max_hashed_file_bytes=8192, max_total_hashed_bytes=8192).max_hashed_file_bytes == 8192


def test_the_nine_historical_scan_limits_are_unchanged_so_persisted_a0_pins_stay_readable():
    assert tuple(f.name for f in dataclasses.fields(scan.ScanLimits)) == HISTORICAL_LIMIT_NAMES
    assert scan._LIMIT_FIELDS == HISTORICAL_LIMIT_NAMES
    import gate_v_exposure_store as store
    assert store._LIMIT_NAMES == HISTORICAL_LIMIT_NAMES
    with pytest.raises(TypeError):
        scan.ScanLimits(4, 1000, 8, 1024, 4096, 16, 80, 200, 1)          # toujours par mot-clé


def test_a_historical_rules_table_keeps_its_exact_digest_and_historical_calls_are_unaffected(tmp_path):
    rules = (
        scan.SourceRule(("plan.json",), scan.EntryClass.INFORMATIVE_JSON, scan.JsonKind.OBJECT, tag="plan"),
        scan.SourceRule(("notes.txt",), scan.EntryClass.INERT_FILE, tag="notes"),
        scan.SourceRule(("exposure",), scan.EntryClass.STRUCTURAL_DIRECTORY),
        scan.SourceRule(("exposure", scan.SegmentPattern(scan.EXPOSURE_TEMP_ORPHAN_PATTERN)), scan.EntryClass.TEMP_ORPHAN_FILE, tag="orphan"),
    )
    assert scan._rules_digest(rules) == GOLDEN_HISTORICAL_TABLE_DIGEST
    root = make_tree(tmp_path, {"plan.json": b"{}", "notes.txt": b"x"})
    result = scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), rules, limits())
    assert (result.hash_limits, result.hashed_bytes_read, result.hashed_files) == (None, 0, 0)
    assert result.rules_digest == GOLDEN_HISTORICAL_TABLE_DIGEST


def test_the_b3_rules_digests_of_v2_v3_v4_are_frozen_at_their_published_values():
    import gate_v_exposure_interpreters as b3
    published = {(version, layout.value): digest for version, layout, digest in b3.B3_RULES_DIGESTS}
    for key, digest in B3_FROZEN_DIGESTS.items():
        assert published[key] == digest, key


# ══ D8-B : lecture SHA-256 en flux, budgets ═══════════════════════════════════════════════════════════════════════════════════════
MAX_CHUNK = 1 << 20          # contrat : morceaux d'au plus 1 MiB (aucune matérialisation complète du fichier)
WF_FOLD = scan.SegmentPattern(r"fold_[0-9]{3}")


def wf_rules(extra=()):
    return (
        scan.SourceRule(("plan.json",), scan.EntryClass.INFORMATIVE_JSON, scan.JsonKind.OBJECT, tag="plan"),
        scan.SourceRule(("notes.txt",), scan.EntryClass.INERT_FILE, tag="notes"),
        scan.SourceRule(("walk_forward",), scan.EntryClass.STRUCTURAL_DIRECTORY, tag="wf"),
        scan.SourceRule(("walk_forward", "manifest.json"), HASHED, tag="wf_manifest"),
        scan.SourceRule(("walk_forward", "aggregate.json"), HASHED, tag="wf_aggregate"),
        scan.SourceRule(("walk_forward", "folds"), scan.EntryClass.STRUCTURAL_DIRECTORY, tag="folds"),
        scan.SourceRule(("walk_forward", "folds", WF_FOLD), scan.EntryClass.STRUCTURAL_DIRECTORY, tag="fold"),
        scan.SourceRule(("walk_forward", "folds", WF_FOLD, "oos_trades.csv"), HASHED, tag="oos"),
        *extra,
    )


def run(tmp_path, files, rules=None, lim=None, hl=None, hooks=None, root_label="main", **kwargs):
    root = make_tree(tmp_path, files)
    return scan.scan_audit_roots((scan.AuditRoot(root_label, str(root)),), wf_rules() if rules is None else rules, lim or limits(),
                                 hooks=hooks, hash_limits=hash_limits() if hl is None else hl, **kwargs)


def by_path(result):
    return {o.relative_path: o for o in result.observations}


BINARY = b"\xff\xfe\x00\x01 not json \x00\x80" * 7
BASE = {"plan.json": b"{}", "walk_forward/manifest.json": BINARY, "walk_forward/folds/fold_000/oos_trades.csv": b"date,net\n2025-09-02,1.5\n"}


def test_a_hashed_file_yields_its_raw_sha256_and_size_and_nothing_else(tmp_path):
    result = run(tmp_path, BASE)
    manifest = by_path(result)["walk_forward/manifest.json"]
    assert (manifest.entry_class, manifest.anomaly, manifest.kind, manifest.rule_tag) == (HASHED, None, scan.EntryKind.FILE, "wf_manifest")
    assert (manifest.content_hash, manifest.size) == (sha(BINARY), len(BINARY))
    assert (manifest.value_parsed, manifest.content_bytes, manifest.value) == (False, None, None)
    trades = by_path(result)["walk_forward/folds/fold_000/oos_trades.csv"]
    assert trades.content_hash == sha(BASE["walk_forward/folds/fold_000/oos_trades.csv"])
    assert result.hashed_files == 2 and result.hashed_bytes_read == len(BINARY) + len(BASE["walk_forward/folds/fold_000/oos_trades.csv"])
    assert result.bytes_read == 2 and result.hash_limits == hash_limits()      # seul plan.json (« {} ») compte dans le budget JSON historique


def test_an_empty_hashed_file_has_the_empty_sha256_and_a_zero_size(tmp_path):
    files = dict(BASE, **{"walk_forward/aggregate.json": b""})
    aggregate = by_path(run(tmp_path, files))["walk_forward/aggregate.json"]
    assert (aggregate.content_hash, aggregate.size, aggregate.anomaly) == (EMPTY_SHA256, 0, None)


@pytest.mark.parametrize("content", [b'{"a": 1, "a": 2}', b"NaN", b"\xef\xbb\xbf{}", b"not json at all", b"[" * 900, b'{"k": "\\ud800"}'],
                         ids=["duplicate-keys", "nan", "bom", "plain-text", "deep-nesting", "lone-surrogate"])
def test_hashed_content_is_never_interpreted_so_no_json_anomaly_can_arise(tmp_path, content):
    observed = by_path(run(tmp_path, dict(BASE, **{"walk_forward/aggregate.json": content})))["walk_forward/aggregate.json"]
    assert (observed.anomaly, observed.content_hash, observed.value_parsed) == (None, sha(content), False)


def test_a_large_file_is_hashed_in_bounded_chunks_never_loaded_whole(tmp_path, monkeypatch):
    payload = bytes(range(256)) * ((2 * MAX_CHUNK + 4097) // 256 + 1)
    payload = payload[:2 * MAX_CHUNK + 4097]
    requested = []
    original = os.read

    def spy(descriptor, size):
        requested.append(size)
        return original(descriptor, size)
    monkeypatch.setattr(os, "read", spy)
    result = run(tmp_path, dict(BASE, **{"walk_forward/aggregate.json": payload}), hl=hash_limits(max_hashed_file_bytes=3 * MAX_CHUNK, max_total_hashed_bytes=4 * MAX_CHUNK))
    assert by_path(result)["walk_forward/aggregate.json"].content_hash == sha(payload)
    assert requested and max(requested) <= MAX_CHUNK
    assert sum(1 for size in requested if size == MAX_CHUNK) >= 4          # 2 passes x 2 morceaux pleins au moins


def test_a_file_of_exactly_the_per_file_limit_is_hashed_and_one_byte_more_is_too_large_and_never_opened(tmp_path, monkeypatch):
    opened = []
    original = os.open

    def spy(path, flags, *args, **kwargs):
        opened.append(os.fspath(path))
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", spy)
    exact = run(tmp_path / "a", dict(BASE, **{"walk_forward/aggregate.json": b"x" * 1024}), hl=hash_limits(max_hashed_file_bytes=1024))
    assert by_path(exact)["walk_forward/aggregate.json"].content_hash == sha(b"x" * 1024)
    opened.clear()
    over = run(tmp_path / "b", dict(BASE, **{"walk_forward/aggregate.json": b"x" * 1025}), hl=hash_limits(max_hashed_file_bytes=1024))
    too_large = by_path(over)["walk_forward/aggregate.json"]
    assert (too_large.anomaly, too_large.content_hash, too_large.entry_class) == (scan.SourceAnomaly.TOO_LARGE, None, HASHED)
    assert too_large.size == 1025                                           # taille mesurée par lstat, contenu jamais lu
    assert not [p for p in opened if p.endswith("aggregate.json")]
    assert over.hashed_bytes_read == len(BINARY) + len(BASE["walk_forward/folds/fold_000/oos_trades.csv"])


def test_the_cumulative_hashed_volume_is_capped_with_exact_boundary_and_the_excess_file_is_never_opened(tmp_path, monkeypatch):
    files = {"walk_forward/manifest.json": b"a" * 100, "walk_forward/aggregate.json": b"b" * 100, "walk_forward/folds/fold_000/oos_trades.csv": b"c" * 100}
    exact = run(tmp_path / "a", files, hl=hash_limits(max_hashed_file_bytes=100, max_total_hashed_bytes=300))
    assert exact.hashed_bytes_read == 300 and exact.hashed_files == 3
    opened = []
    original = os.open

    def spy(path, flags, *args, **kwargs):
        opened.append(os.path.basename(os.fspath(path)))
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", spy)
    error = refused(lambda: run(tmp_path / "b", files, hl=hash_limits(max_hashed_file_bytes=100, max_total_hashed_bytes=299)), scan.StructuralFailure.LIMIT_EXCEEDED)
    assert "max_total_hashed_bytes" in error.detail
    assert opened.count("manifest.json") == 0                               # le fichier qui ferait dépasser le cumul n'est pas lu (ordre du parcours : aggregate, folds/…, manifest)


def test_the_number_of_hashed_files_is_capped_with_exact_boundary(tmp_path):
    files = {f"walk_forward/folds/fold_{i:03d}/oos_trades.csv": b"x" for i in range(5)}
    assert run(tmp_path / "a", files, hl=hash_limits(max_hashed_files=5)).hashed_files == 5
    error = refused(lambda: run(tmp_path / "b", files, hl=hash_limits(max_hashed_files=4)), scan.StructuralFailure.LIMIT_EXCEEDED)
    assert "max_hashed_files" in error.detail


def test_a_table_with_hashed_rules_requires_explicit_hash_limits_and_never_invents_any(tmp_path):
    root = make_tree(tmp_path, BASE)
    roots = (scan.AuditRoot("main", str(root)),)
    with pytest.raises(ValueError):
        scan.scan_audit_roots(roots, wf_rules(), limits())
    with pytest.raises(TypeError):
        scan.scan_audit_roots(roots, wf_rules(), limits(), hash_limits=limits())
    with pytest.raises(TypeError):
        scan.scan_audit_roots(roots, wf_rules(), limits(), hash_limits={"max_hashed_files": 5})
    historical = tuple(r for r in wf_rules() if not r.entry_class.is_hashed)
    kept = scan.scan_audit_roots(roots, historical, limits(), hash_limits=hash_limits())
    assert (kept.hash_limits, kept.hashed_files, kept.hashed_bytes_read) == (hash_limits(), 0, 0)


def test_the_json_budget_and_the_hashed_budget_are_independent(tmp_path):
    plan = b'{"k": "' + b"v" * 20 + b'"}'
    files = dict(BASE, plan_json=b"")
    files = {"plan.json": plan, "walk_forward/manifest.json": b"z" * 900}
    tight_json = run(tmp_path / "a", files, lim=limits(max_json_bytes=len(plan), max_total_read_bytes=len(plan)), hl=hash_limits(max_hashed_file_bytes=1024))
    assert tight_json.bytes_read == len(plan) and tight_json.hashed_bytes_read == 900        # 900 octets hachés > max_total_read_bytes : sans effet
    tight_hash = run(tmp_path / "b", files, lim=limits(), hl=hash_limits(max_hashed_file_bytes=900, max_total_hashed_bytes=900))
    assert tight_hash.bytes_read == len(plan) and tight_hash.hashed_bytes_read == 900


def test_an_unreadable_hashed_file_is_an_explicit_anomaly_with_no_usable_hash(tmp_path, monkeypatch):
    original = os.open

    def deny(path, flags, *args, **kwargs):
        if os.fspath(path).endswith("aggregate.json"):
            raise PermissionError("refusé")
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", deny)
    aggregate = by_path(run(tmp_path, dict(BASE, **{"walk_forward/aggregate.json": b"data"})))["walk_forward/aggregate.json"]
    assert (aggregate.anomaly, aggregate.content_hash, aggregate.entry_class) == (scan.SourceAnomaly.UNREADABLE, None, HASHED)


def test_a_read_error_after_the_first_chunk_never_yields_a_partial_hash(tmp_path, monkeypatch):
    payload = b"q" * (MAX_CHUNK + 10)
    original = os.read
    calls = {"n": 0}

    def flaky(descriptor, size):
        if size > 1000 and calls["n"] >= 1:
            raise OSError("erreur d'E/S simulée")
        calls["n"] += 1
        return original(descriptor, size)
    monkeypatch.setattr(os, "read", flaky)
    result = run(tmp_path, {"walk_forward/aggregate.json": payload}, hl=hash_limits(max_hashed_file_bytes=2 * MAX_CHUNK, max_total_hashed_bytes=4 * MAX_CHUNK))
    aggregate = by_path(result)["walk_forward/aggregate.json"]
    assert (aggregate.anomaly, aggregate.content_hash) == (scan.SourceAnomaly.UNREADABLE, None)
    assert result.hashed_bytes_read >= MAX_CHUNK                               # le premier morceau a été livré, donc facturé, même si la lecture a échoué


def test_a_hashed_rule_on_a_directory_is_a_kind_mismatch_with_no_hash(tmp_path):
    root = make_tree(tmp_path, BASE)
    (root / "walk_forward" / "aggregate.json").mkdir()
    observed = by_path(scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), wf_rules(), limits(), hash_limits=hash_limits()))["walk_forward/aggregate.json"]
    assert (observed.anomaly, observed.content_hash, observed.kind) == (scan.SourceAnomaly.KIND_MISMATCH, None, scan.EntryKind.DIRECTORY)


def test_the_worst_case_read_volume_is_a_documented_bound_and_a_stable_scan_costs_exactly_two_passes(tmp_path, monkeypatch):
    lim, hl = limits(max_attempts=3), hash_limits()
    assert scan.scan_worst_case_read_bytes(lim, hl) > 0
    with pytest.raises(TypeError):
        scan.scan_worst_case_read_bytes(lim, None)
    with pytest.raises(TypeError):
        scan.scan_worst_case_read_bytes(None, hl)
    delivered = []
    original = os.read

    def counting(descriptor, size):
        data = original(descriptor, size)
        delivered.append(len(data))
        return data
    monkeypatch.setattr(os, "read", counting)
    result = run(tmp_path, BASE, lim=lim, hl=hl)
    assert result.attempts_used == 1
    assert sum(delivered) == 2 * (result.bytes_read + result.hashed_bytes_read) <= scan.scan_worst_case_read_bytes(lim, hl)


def test_an_altered_output_changes_its_hash_and_a_deleted_or_added_one_is_never_silent(tmp_path):
    before = by_path(run(tmp_path / "a", BASE))
    altered = by_path(run(tmp_path / "b", dict(BASE, **{"walk_forward/manifest.json": BINARY + b"!"})))
    assert altered["walk_forward/manifest.json"].content_hash != before["walk_forward/manifest.json"].content_hash
    missing = {k: v for k, v in BASE.items() if k != "walk_forward/manifest.json"}
    assert "walk_forward/manifest.json" not in by_path(run(tmp_path / "c", missing))       # absence constatée par la comparaison des listes, jamais un faux hash
    added = by_path(run(tmp_path / "d", dict(BASE, **{"walk_forward/extra.csv": b"1"})))["walk_forward/extra.csv"]
    assert (added.entry_class, added.anomaly, added.content_hash) == (None, scan.SourceAnomaly.UNKNOWN_FILE, None)


# ══ D8-C : double passe, courses, instabilité ═════════════════════════════════════════════════════════════════════════════════════
AGG = "walk_forward/aggregate.json"
SAME_SIZE_A, SAME_SIZE_B = b"A" * 40, b"B" * 40


def rewrite_in_place(path: Path, data: bytes) -> None:
    """Remplace le contenu SANS changer ni la taille, ni l'inode, ni le mtime : invisible aux seules métadonnées."""
    before = os.stat(path)
    with open(path, "r+b") as handle:
        handle.write(data)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


def once(action):
    done = {"n": 0}

    def wrapper(*args):
        if done["n"] == 0:
            done["n"] = 1
            action(*args)
    return wrapper


def once_on(relative_path, action):
    """Déclenche `action` une seule fois, quand le hook concerne EXACTEMENT ce chemin (les hooks sont aussi appelés pour les lectures JSON)."""
    done = {"n": 0}

    def wrapper(_label, path):
        if path == relative_path and done["n"] == 0:
            done["n"] = 1
            action()
    return wrapper


OLD_MTIME_NS = 1_000_000_000_000_000_000          # 2001-09-09 : très antérieur à toute édition de test


def tree_with_aggregate(tmp_path, content=SAME_SIZE_A):
    """Arbre de test dont tous les fichiers sont VIEILLIS : l'horloge des `mtime` a une granularité grossière et variable (mesurée sur une machine Windows : pas médian
    ≈ 1 ms, 15 % des écritures consécutives de même `mtime`), donc une édition faite dans le même pas que la création laissait le `mtime` inchangé (modification
    annulée indétectable par construction : limite documentée du scanner) et rendait intermittents les tests qui supposent qu'une édition change le `mtime`.
    Après vieillissement à 2001, toute édition le change quelle que soit la résolution du système de fichiers."""
    root = make_tree(tmp_path, dict(BASE, **{AGG: content}))
    for path in root.rglob("*"):
        if path.is_file():
            os.utime(path, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
    return root


def scan_tree(root, hooks, attempts, hl=None, rules=None):
    return scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), wf_rules() if rules is None else rules, limits(max_attempts=attempts), hooks=hooks,
                                 hash_limits=hash_limits() if hl is None else hl)


def test_a_same_size_edit_with_restored_mtime_between_the_passes_is_caught_by_the_hash_and_never_accepted_as_stable(tmp_path):
    root = tree_with_aggregate(tmp_path)
    target = root / AGG
    hooks = scan.ScanHooks(after_first_pass=once(lambda attempt: rewrite_in_place(target, SAME_SIZE_B)))
    refused(lambda: scan_tree(root, hooks, 1), scan.StructuralFailure.UNSTABLE_LISTING)
    root = tree_with_aggregate(tmp_path / "second")
    recovered = scan_tree(root, scan.ScanHooks(after_first_pass=once(lambda attempt: rewrite_in_place(root / AGG, SAME_SIZE_B))), 2)
    assert recovered.attempts_used == 2 and by_path(recovered)[AGG].content_hash == sha(SAME_SIZE_B)     # état final cohérent entre les deux passes


def test_a_file_that_changes_on_every_attempt_ends_in_a_refusal_never_in_a_partial_result(tmp_path):
    root = tree_with_aggregate(tmp_path)
    flip = {"n": 0}

    def alternate(_attempt):
        flip["n"] += 1
        rewrite_in_place(root / AGG, SAME_SIZE_B if flip["n"] % 2 else SAME_SIZE_A)
    error = refused(lambda: scan_tree(root, scan.ScanHooks(after_first_pass=alternate), 3), scan.StructuralFailure.UNSTABLE_LISTING)
    assert "3 essai" in error.detail


def test_a_hashed_file_deleted_or_an_unknown_file_added_between_the_passes_is_an_instability(tmp_path):
    root = tree_with_aggregate(tmp_path / "a")
    refused(lambda: scan_tree(root, scan.ScanHooks(after_first_pass=once(lambda attempt: (root / AGG).unlink())), 1), scan.StructuralFailure.UNSTABLE_LISTING)
    root = tree_with_aggregate(tmp_path / "b")
    refused(lambda: scan_tree(root, scan.ScanHooks(after_first_pass=once(lambda attempt: (root / "walk_forward" / "extra.bin").write_bytes(b"1"))), 1),
            scan.StructuralFailure.UNSTABLE_LISTING)


def test_a_file_replaced_by_another_inode_between_lstat_and_open_is_never_hashed_as_the_original(tmp_path):
    root = tree_with_aggregate(tmp_path)
    target = root / AGG

    def swap(_label, _path):
        before = os.stat(target)
        replacement = target.with_name("replacement.bin")
        replacement.write_bytes(SAME_SIZE_B)
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        os.replace(replacement, target)
    refused(lambda: scan_tree(root, scan.ScanHooks(before_open=once(swap)), 1), scan.StructuralFailure.UNSTABLE_LISTING)
    root = tree_with_aggregate(tmp_path / "second")
    target = root / AGG
    recovered = scan_tree(root, scan.ScanHooks(before_open=once(swap)), 2)
    assert by_path(recovered)[AGG].content_hash == sha(SAME_SIZE_B) and recovered.attempts_used == 2


def test_a_hashed_file_deleted_between_lstat_and_open_is_an_instability_not_a_missing_hash(tmp_path):
    root = tree_with_aggregate(tmp_path)
    refused(lambda: scan_tree(root, scan.ScanHooks(before_open=once(lambda label, path: (root / AGG).unlink())), 1), scan.StructuralFailure.UNSTABLE_LISTING)


@pytest.mark.parametrize("mutation", ["grow_within_limit", "shrink", "append_over_limit"])
def test_a_size_change_between_lstat_and_read_is_an_instability_and_over_the_limit_it_ends_too_large(tmp_path, mutation):
    root = tree_with_aggregate(tmp_path)
    target = root / AGG
    actions = {
        "grow_within_limit": lambda: target.write_bytes(SAME_SIZE_A + b"+"),
        "shrink": lambda: target.write_bytes(SAME_SIZE_A[:10]),
        "append_over_limit": lambda: target.write_bytes(b"x" * 2000),
    }
    hooks = scan.ScanHooks(before_open=once(lambda label, path: actions[mutation]()))
    refused(lambda: scan_tree(root, hooks, 1), scan.StructuralFailure.UNSTABLE_LISTING)
    root = tree_with_aggregate(tmp_path / "second")
    target = root / AGG
    hooks = scan.ScanHooks(before_open=once(lambda label, path: actions[mutation]()))
    recovered = by_path(scan_tree(root, hooks, 2))[AGG]
    if mutation == "append_over_limit":
        assert (recovered.anomaly, recovered.content_hash) == (scan.SourceAnomaly.TOO_LARGE, None)
    else:
        assert recovered.content_hash == sha(target.read_bytes())


def test_a_modification_right_after_the_read_is_detected_by_the_final_lstat_or_by_the_second_pass(tmp_path):
    root = tree_with_aggregate(tmp_path)
    target = root / AGG
    refused(lambda: scan_tree(root, scan.ScanHooks(after_file_read=once_on(AGG, lambda: target.write_bytes(SAME_SIZE_B + b"!"))), 1),
            scan.StructuralFailure.UNSTABLE_LISTING)
    root = tree_with_aggregate(tmp_path / "second")
    target = root / AGG
    # même taille, mtime restauré, inode conservé : invisible au `lstat` final de la première passe, mais la SECONDE passe voit un autre SHA-256
    refused(lambda: scan_tree(root, scan.ScanHooks(after_file_read=once_on(AGG, lambda: rewrite_in_place(target, SAME_SIZE_B))), 1),
            scan.StructuralFailure.UNSTABLE_LISTING)


def test_unstable_attempts_do_not_accumulate_the_hashed_budget(tmp_path):
    root = make_tree(tmp_path, {AGG: SAME_SIZE_A})
    exact = hash_limits(max_hashed_file_bytes=40, max_total_hashed_bytes=40, max_hashed_files=1)
    rules = tuple(r for r in wf_rules() if r.tag in {"wf", "wf_aggregate"})
    hooks = scan.ScanHooks(after_first_pass=once(lambda attempt: rewrite_in_place(root / AGG, SAME_SIZE_B)))
    result = scan_tree(root, hooks, 3, hl=exact, rules=rules)
    assert result.attempts_used == 2 and result.hashed_bytes_read == 40 and result.hashed_files == 1


def make_symlink(target: Path, link: Path):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("création de lien symbolique non permise sur cette machine")


def test_a_symlink_where_a_hashed_file_is_expected_is_a_structural_refusal_and_is_never_opened(tmp_path, monkeypatch):
    root = make_tree(tmp_path, dict(BASE, **{"outside.bin": b"outside"}))
    make_symlink(root / "outside.bin", root / "walk_forward" / "aggregate.json")
    opened = []
    original = os.open

    def spy(path, flags, *args, **kwargs):
        opened.append(os.path.basename(os.fspath(path)))
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", spy)
    refused(lambda: scan_tree(root, None, 1), scan.StructuralFailure.LINK_OR_REPARSE_POINT)
    assert "aggregate.json" not in opened


def test_a_file_swapped_for_a_symlink_just_before_open_never_yields_the_target_content_as_a_hash(tmp_path):
    root = make_tree(tmp_path, dict(BASE, **{AGG: SAME_SIZE_A, "other.bin": b"T" * 40}))
    target = root / AGG

    def swap(_label, _path):
        target.unlink()
        make_symlink(root / "other.bin", target)
    try:
        result = scan_tree(root, scan.ScanHooks(before_open=once(swap)), 1)
    except scan.ExposureScanRefusal as error:
        assert error.failure in (scan.StructuralFailure.UNSTABLE_LISTING, scan.StructuralFailure.LINK_OR_REPARSE_POINT)
        return
    observed = by_path(result).get(AGG)
    assert observed is None or observed.content_hash not in (sha(b"T" * 40), sha(SAME_SIZE_A))


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO : POSIX uniquement, non démontré sous Windows")
def test_a_fifo_where_a_hashed_file_is_expected_is_refused_without_blocking(tmp_path):
    root = make_tree(tmp_path, BASE)
    os.mkfifo(root / "walk_forward" / "aggregate.json")
    refused(lambda: scan_tree(root, None, 1), scan.StructuralFailure.SPECIAL_FILE)


# ══ D8-D : second motif strict d'orphelins de publication (`<cible>.<32 hex>.tmp`, producteur `save_atomic`) ═══════════════════════
import json
import random
import re

SUFFIX = r"\.[0-9a-f]{32}\.tmp"


def orphan_name(target: str, hex32: str = HEX32) -> str:
    return f"{target}.{hex32}.tmp"


def test_the_publication_orphan_pattern_for_a_literal_target_is_exactly_the_target_plus_the_save_atomic_suffix():
    assert scan.PUBLICATION_ORPHAN_SUFFIX == SUFFIX
    pattern = scan.publication_orphan_pattern("manifest.json")
    assert pattern.regex == r"manifest\.json" + SUFFIX
    assert pattern.matches(orphan_name("manifest.json"))
    for name in (orphan_name("manifest.json", "0" * 31), orphan_name("manifest.json", "0" * 33), orphan_name("manifest.json", "A" * 32),
                 orphan_name("manifest.json") + "2", orphan_name("manifest.json") + "." + HEX32 + ".tmp", "x" + orphan_name("manifest.json"),
                 orphan_name("manifestXjson"), orphan_name("manifest.json").replace(".tmp", ".TMP"), "manifest.json.tmp", orphan_name("manifest.json")[1:],
                 f"manifest.json.{HEX32}.tmp\n", f"manifest.json.{HEX32}.tmp "):
        assert not pattern.matches(name), name


def test_the_publication_orphan_pattern_for_a_patterned_target_wraps_the_whole_target_pattern():
    fold_json = scan.SegmentPattern(r"fold_[0-9]{3}\.json")
    pattern = scan.publication_orphan_pattern(fold_json)
    assert pattern.regex == r"(?:fold_[0-9]{3}\.json)" + SUFFIX
    assert pattern.matches(orphan_name("fold_007.json")) and not pattern.matches(orphan_name("fold_7.json")) and not pattern.matches("fold_007.json")


@pytest.mark.parametrize("target", ["", ".", "..", "a/b", "a\\b", "a b", "é", "x.tmp", "x.tmp.y", "x.TMP", "n" * 92])
def test_the_publication_orphan_pattern_refuses_invalid_or_temporary_looking_targets(target):
    with pytest.raises(ValueError):
        scan.publication_orphan_pattern(target)


@pytest.mark.parametrize("target", [None, 1, b"a", ["a"], object()])
def test_the_publication_orphan_pattern_refuses_non_text_non_pattern_targets(target):
    with pytest.raises(TypeError):
        scan.publication_orphan_pattern(target)


def test_the_longest_admissible_target_fits_the_name_length_ceiling():
    longest = "n" * 91
    assert scan.publication_orphan_pattern(longest).matches(orphan_name(longest)) and len(orphan_name(longest)) == 128


def test_a_temp_orphan_rule_accepts_only_the_historical_pattern_or_a_pattern_built_by_the_factory():
    scan.SourceRule(("exposure", scan.SegmentPattern(scan.EXPOSURE_TEMP_ORPHAN_PATTERN)), scan.EntryClass.TEMP_ORPHAN_FILE)      # historique inchangé
    scan.SourceRule(("walk_forward", scan.publication_orphan_pattern("manifest.json")), scan.EntryClass.TEMP_ORPHAN_FILE)
    scan.SourceRule(("walk_forward", scan.publication_orphan_pattern(scan.SegmentPattern(r"fold_[0-9]{3}\.json"))), scan.EntryClass.TEMP_ORPHAN_FILE)
    forged = [
        r"manifest.json" + SUFFIX,                                  # point non échappé : jamais une forme canonique
        r"manifest\.json\.[0-9a-f]{31}\.tmp",
        r"manifest\.json\.[0-9a-f]{32}\.TMP",
        r"[a-z.]{1,40}" + SUFFIX,                                   # cible non littérale et non enveloppée
        r"(?:[a-z.]{1,40})" + r"\.[0-9a-f]{32}\.tmp2",
        r".+\.tmp", r"[a-z_]+\.json" + SUFFIX, r"x\.tmp" + SUFFIX, r"manifest\.json" + SUFFIX + "x",
    ]
    for regex in forged:
        with pytest.raises(ValueError):
            scan.SourceRule(("walk_forward", scan.SegmentPattern(regex)), scan.EntryClass.TEMP_ORPHAN_FILE)
    with pytest.raises(ValueError):
        scan.SourceRule(("walk_forward", "manifest.json"), scan.EntryClass.TEMP_ORPHAN_FILE)               # un littéral n'est jamais un orphelin


ORPHAN_PROBE_NAMES = ("manifest.json", "aggregate.json", "fold_000.json", "oos_trades.csv")


def orphan_rules():
    return wf_rules(extra=(
        scan.SourceRule(("walk_forward", scan.publication_orphan_pattern("manifest.json")), scan.EntryClass.TEMP_ORPHAN_FILE, tag="wf_manifest_orphan"),
        scan.SourceRule(("walk_forward", scan.publication_orphan_pattern("aggregate.json")), scan.EntryClass.TEMP_ORPHAN_FILE, tag="wf_aggregate_orphan"),
        scan.SourceRule(("walk_forward", "folds", WF_FOLD, scan.publication_orphan_pattern("oos_trades.csv")), scan.EntryClass.TEMP_ORPHAN_FILE, tag="oos_orphan"),
    ))


def test_an_orphan_rule_needs_a_known_file_target_in_the_same_directory_checked_when_the_scan_starts(tmp_path):
    root = make_tree(tmp_path, BASE)
    roots = (scan.AuditRoot("main", str(root)),)

    def attempt(rule):
        return scan.scan_audit_roots(roots, wf_rules(extra=(rule,)), limits(), hash_limits=hash_limits())
    ok = scan.SourceRule(("walk_forward", scan.publication_orphan_pattern("manifest.json")), scan.EntryClass.TEMP_ORPHAN_FILE)
    assert attempt(ok).hashed_files == 2
    for bad in (
        scan.SourceRule(("walk_forward", scan.publication_orphan_pattern("unknown.json")), scan.EntryClass.TEMP_ORPHAN_FILE),               # cible inconnue
        scan.SourceRule(("walk_forward", "folds", scan.publication_orphan_pattern("manifest.json")), scan.EntryClass.TEMP_ORPHAN_FILE),    # autre répertoire
        scan.SourceRule((scan.publication_orphan_pattern("manifest.json"),), scan.EntryClass.TEMP_ORPHAN_FILE),                           # racine : cible absente
        scan.SourceRule(("walk_forward", scan.publication_orphan_pattern("notes.txt")), scan.EntryClass.TEMP_ORPHAN_FILE),                # cible INERT ailleurs
        scan.SourceRule(("walk_forward", scan.publication_orphan_pattern(scan.SegmentPattern(r"manifest\.json"))), scan.EntryClass.TEMP_ORPHAN_FILE),   # cible motif ≠ cible littérale
        scan.SourceRule(("walk_forward", "folds", WF_FOLD, scan.publication_orphan_pattern(scan.SegmentPattern(r"fold_[0-9]{3}"))), scan.EntryClass.TEMP_ORPHAN_FILE),
    ):
        with pytest.raises(ValueError):
            attempt(bad)
    inert = scan.SourceRule(("walk_forward", "inert.bin"), scan.EntryClass.INERT_FILE)
    orphan_of_inert = scan.SourceRule(("walk_forward", scan.publication_orphan_pattern("inert.bin")), scan.EntryClass.TEMP_ORPHAN_FILE)
    with pytest.raises(ValueError):
        scan.scan_audit_roots(roots, wf_rules(extra=(inert, orphan_of_inert)), limits(), hash_limits=hash_limits())      # un INERT_FILE n'acquiert pas d'orphelin


@pytest.mark.parametrize("target_class", [scan.EntryClass.EXPOSING_JSON, scan.EntryClass.INFORMATIVE_JSON, HASHED])
def test_an_orphan_rule_is_allowed_for_json_and_hashed_targets(tmp_path, target_class):
    expected = scan.JsonKind.OBJECT if target_class.is_read else None
    rules = (scan.SourceRule(("run",), scan.EntryClass.STRUCTURAL_DIRECTORY),
             scan.SourceRule(("run", "out.json"), target_class, expected),
             scan.SourceRule(("run", scan.publication_orphan_pattern("out.json")), scan.EntryClass.TEMP_ORPHAN_FILE, tag="o"))
    root = make_tree(tmp_path, {"run/out.json": b"{}", f"run/{orphan_name('out.json')}": b"half-written"})
    result = scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), rules, limits(), hash_limits=hash_limits())
    assert by_path(result)[f"run/{orphan_name('out.json')}"].entry_class is scan.EntryClass.TEMP_ORPHAN_FILE


def test_a_recognised_orphan_is_a_fact_never_opened_never_hashed_never_counted_and_name_only_in_the_double_pass(tmp_path, monkeypatch):
    files = dict(BASE, **{f"walk_forward/{orphan_name('manifest.json')}": b"half-written", f"walk_forward/folds/fold_000/{orphan_name('oos_trades.csv')}": b"x"})
    opened = []
    original = os.open

    def spy(path, flags, *args, **kwargs):
        opened.append(os.path.basename(os.fspath(path)))
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", spy)
    root = make_tree(tmp_path, files)
    orphan_path = root / "walk_forward" / orphan_name("manifest.json")
    hooks = scan.ScanHooks(after_first_pass=lambda attempt: orphan_path.write_bytes(b"changed after the first pass, larger"))
    result = scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), orphan_rules(), limits(max_attempts=1), hooks=hooks, hash_limits=hash_limits())
    found = by_path(result)[f"walk_forward/{orphan_name('manifest.json')}"]
    assert (found.entry_class, found.anomaly, found.content_hash, found.value_parsed, found.content_bytes, found.rule_tag) == (
        scan.EntryClass.TEMP_ORPHAN_FILE, None, None, False, None, "wf_manifest_orphan")
    assert result.attempts_used == 1                                          # le contenu d'un orphelin n'est pas comparé (constat par le nom)
    assert not [name for name in opened if name.endswith(".tmp")]
    assert result.hashed_files == 2 and result.bytes_read == 2                # ni compté dans les fichiers hachés, ni dans le budget JSON


UNKNOWN = scan.SourceAnomaly.UNKNOWN_TEMP_FILE


@pytest.mark.parametrize("relative", [
    f"{orphan_name('manifest.json')}",                                          # racine : emplacement non autorisé
    f"walk_forward/folds/{orphan_name('manifest.json')}",                       # autre répertoire que la cible
    f"walk_forward/{orphan_name('other.json')}",                                # cible non déclarée
    f"walk_forward/{orphan_name('manifest.json', '0' * 31)}",
    f"walk_forward/{orphan_name('manifest.json', 'A' * 32)}",
    f"walk_forward/{orphan_name('manifest.json')}.bak.tmp",
    "walk_forward/manifest.json.tmp",
    "walk_forward/manifest.tmp",
    "walk_forward/.tmp",
    f"walk_forward/.exposure.tmp.{HEX32}",                                      # motif d'exposition : jamais valide ici
    f"walk_forward/final_holdout_access_claim.json.{HEX32}.tmp",               # un Claim ne se cache pas derrière un temporaire
    f"walk_forward/{orphan_name('MANIFEST.json')}",
])
def test_a_temporary_outside_the_exact_rule_stays_an_unknown_blocking_fact(tmp_path, relative):
    result = run(tmp_path, dict(BASE, **{relative: b"x"}), rules=orphan_rules())
    found = by_path(result)[relative]
    assert (found.entry_class, found.anomaly, found.content_hash, found.rule_tag) == (None, UNKNOWN, None, None)


def test_the_exposure_orphan_pattern_and_the_publication_pattern_never_recognise_each_others_names(tmp_path):
    rules = (scan.SourceRule(("exposure",), scan.EntryClass.STRUCTURAL_DIRECTORY),
             scan.SourceRule(("exposure", "a.json"), scan.EntryClass.INFORMATIVE_JSON, scan.JsonKind.OBJECT),
             scan.SourceRule(("exposure", scan.SegmentPattern(scan.EXPOSURE_TEMP_ORPHAN_PATTERN)), scan.EntryClass.TEMP_ORPHAN_FILE, tag="exposure_orphan"),
             scan.SourceRule(("exposure", scan.publication_orphan_pattern("a.json")), scan.EntryClass.TEMP_ORPHAN_FILE, tag="publication_orphan"))
    files = {"exposure/a.json": b"{}", f"exposure/.exposure.tmp.{HEX32}": b"1", f"exposure/{orphan_name('a.json')}": b"2"}
    seen = by_path(run(tmp_path, files, rules=rules))
    assert seen[f"exposure/.exposure.tmp.{HEX32}"].rule_tag == "exposure_orphan" and seen[f"exposure/{orphan_name('a.json')}"].rule_tag == "publication_orphan"
    generator = random.Random(8)
    exposure_re, publication_re = re.compile(scan.EXPOSURE_TEMP_ORPHAN_PATTERN), re.compile(r"a\.json" + SUFFIX)
    for _ in range(2000):
        digits = "".join(generator.choice("0123456789abcdef") for _ in range(32))
        for name in (f".exposure.tmp.{digits}", f"a.json.{digits}.tmp", f"a.json.{digits}.tmp.{digits}", f".exposure.tmp.{digits}.tmp"):
            assert not (exposure_re.fullmatch(name) and publication_re.fullmatch(name)), name


def test_a_target_pattern_that_also_matches_temporary_names_makes_the_table_ambiguous_and_the_scan_refuses(tmp_path):
    greedy_target = scan.SegmentPattern(r"[a-z0-9.]{1,80}")
    rules = (scan.SourceRule(("run",), scan.EntryClass.STRUCTURAL_DIRECTORY),
             scan.SourceRule(("run", greedy_target), HASHED, tag="greedy"),
             scan.SourceRule(("run", scan.publication_orphan_pattern(greedy_target)), scan.EntryClass.TEMP_ORPHAN_FILE, tag="o"))
    root = make_tree(tmp_path, {"run/out.json": b"1", f"run/{orphan_name('out.json')}": b"2"})
    refused(lambda: scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), rules, limits(), hash_limits=hash_limits()), scan.StructuralFailure.AMBIGUOUS_SOURCE_TABLE)


def test_an_orphan_name_that_is_a_directory_is_a_kind_mismatch_and_is_never_descended(tmp_path):
    root = make_tree(tmp_path, BASE)
    (root / "walk_forward" / orphan_name("manifest.json")).mkdir()
    (root / "walk_forward" / orphan_name("manifest.json") / "hidden.bin").write_bytes(b"x")
    result = scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), orphan_rules(), limits(), hash_limits=hash_limits())
    names = set(by_path(result))
    assert by_path(result)[f"walk_forward/{orphan_name('manifest.json')}"].anomaly is scan.SourceAnomaly.KIND_MISMATCH
    assert not any(name.endswith("hidden.bin") for name in names)


def test_a_forged_temporary_neutralises_no_other_observation_and_never_makes_a_run_look_complete(tmp_path):
    clean = by_path(run(tmp_path / "a", dict(BASE, **{"walk_forward/folds/fold_000/other.bin": b"unknown"}), rules=orphan_rules()))
    forged_files = dict(BASE, **{"walk_forward/folds/fold_000/other.bin": b"unknown", f"walk_forward/{orphan_name('manifest.json')}": b"forged",
                                 f"walk_forward/folds/fold_000/{orphan_name('oos_trades.csv')}": b"forged"})
    forged = by_path(run(tmp_path / "b", forged_files, rules=orphan_rules()))
    facts = lambda o: (o.relative_path, o.kind, o.entry_class, o.anomaly, o.size, o.content_hash, o.value_parsed, o.rule_tag)
    for path, observed in clean.items():
        assert facts(forged[path]) == facts(observed)                       # les autres constats sont strictement identiques
    assert clean["walk_forward/folds/fold_000/other.bin"].anomaly is scan.SourceAnomaly.UNKNOWN_FILE == forged["walk_forward/folds/fold_000/other.bin"].anomaly
    added = set(forged) - set(clean)
    assert added == {f"walk_forward/{orphan_name('manifest.json')}", f"walk_forward/folds/fold_000/{orphan_name('oos_trades.csv')}"}


def test_an_orphan_does_not_replace_a_missing_output_the_scanner_reports_only_what_exists(tmp_path):
    files = {k: v for k, v in BASE.items() if k != "walk_forward/manifest.json"}
    files[f"walk_forward/{orphan_name('manifest.json')}"] = b"half-written"
    seen = by_path(run(tmp_path, files, rules=orphan_rules()))
    assert "walk_forward/manifest.json" not in seen and f"walk_forward/{orphan_name('manifest.json')}" in seen


def test_the_rules_digest_covers_hashed_and_orphan_rules_deterministically_and_historical_tables_are_untouched():
    def oracle(rules):
        lines = sorted(json.dumps({"segments": [s if type(s) is str else {"regex": s.regex} for s in r.segments], "entry_class": r.entry_class.value,
                                   "expected_json": r.expected_json.value if r.expected_json else None, "tag": r.tag},
                                  sort_keys=True, separators=(",", ":"), ensure_ascii=True) for r in rules)
        return hashlib.sha256("\n".join(lines).encode("ascii")).hexdigest()
    full, historical = orphan_rules(), tuple(r for r in orphan_rules() if r.entry_class not in (HASHED, scan.EntryClass.TEMP_ORPHAN_FILE))
    assert scan._rules_digest(full) == oracle(full) == scan._rules_digest(tuple(reversed(full)))
    assert scan._rules_digest(full) != scan._rules_digest(historical) and scan._rules_digest(historical) == oracle(historical)
    inert_instead = tuple(scan.SourceRule(r.segments, scan.EntryClass.INERT_FILE, tag=r.tag) if r.entry_class is HASHED else r for r in wf_rules())
    assert scan._rules_digest(inert_instead) != scan._rules_digest(wf_rules())


def test_a_historical_inert_file_never_becomes_hashed_by_itself(tmp_path):
    inert_rules = tuple(scan.SourceRule(r.segments, scan.EntryClass.INERT_FILE, tag=r.tag) if r.entry_class is HASHED else r for r in wf_rules())
    root = make_tree(tmp_path, dict(BASE, **{AGG: SAME_SIZE_A}))
    hooks = scan.ScanHooks(after_first_pass=lambda attempt: rewrite_in_place(root / AGG, SAME_SIZE_B))
    result = scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), inert_rules, limits(), hooks=hooks)        # aucune hash_limits requise
    inert = by_path(result)[AGG]
    assert (inert.entry_class, inert.content_hash, inert.anomaly, result.attempts_used, result.hash_limits) == (scan.EntryClass.INERT_FILE, None, None, 1, None)


# ══ Durcissements issus de la mutation ciblée ═════════════════════════════════════════════════════════════════════════════════════
def arm_on(target_path, armed):
    """Hook `before_open` : arme le drapeau uniquement pour le fichier haché visé (les lectures JSON ne le déclenchent pas)."""
    return scan.ScanHooks(before_open=lambda label, path: armed.__setitem__("on", path == target_path))


def test_a_file_swapped_for_an_identical_copy_during_the_second_pass_is_still_an_instability(tmp_path):
    root = tree_with_aggregate(tmp_path)
    target = root / AGG
    calls = {"n": 0}

    def swap_identical(_label, path):
        if path != AGG:
            return
        calls["n"] += 1
        if calls["n"] == 2:                               # seconde passe : le `lstat` est déjà pris, le fichier change d'inode avant l'ouverture
            before = os.stat(target)
            replacement = target.with_name("replacement.bin")
            replacement.write_bytes(SAME_SIZE_A)
            os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
            os.replace(replacement, target)
    refused(lambda: scan_tree(root, scan.ScanHooks(before_open=swap_identical), 1), scan.StructuralFailure.UNSTABLE_LISTING)


def test_a_file_swapped_for_an_identical_copy_right_after_the_read_of_the_second_pass_is_still_an_instability(tmp_path):
    root = tree_with_aggregate(tmp_path)
    target = root / AGG
    calls = {"n": 0}

    def swap_identical(_label, path):
        if path != AGG:
            return
        calls["n"] += 1
        if calls["n"] == 2:
            before = os.stat(target)
            replacement = target.with_name("replacement.bin")
            replacement.write_bytes(SAME_SIZE_A)
            os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
            os.replace(replacement, target)
    refused(lambda: scan_tree(root, scan.ScanHooks(after_file_read=swap_identical), 1), scan.StructuralFailure.UNSTABLE_LISTING)


def test_a_short_read_with_unchanged_metadata_never_yields_a_hash_of_fewer_bytes_than_the_file_size(tmp_path, monkeypatch):
    root = tree_with_aggregate(tmp_path)
    armed = {"on": False, "served": False}
    original = os.read

    def short(descriptor, size):
        if armed["on"]:
            if armed["served"]:
                return b""
            armed["served"] = True
            return original(descriptor, size)[:-1]             # un octet de moins que la taille annoncée, puis fin de fichier
        return original(descriptor, size)

    def rearm(_label, path):
        armed["on"], armed["served"] = path == AGG, False      # chaque OUVERTURE du fichier est « courte » de la même façon, dans les deux passes
    monkeypatch.setattr(os, "read", short)
    refused(lambda: scan_tree(root, scan.ScanHooks(before_open=rearm), 1), scan.StructuralFailure.UNSTABLE_LISTING)


def test_a_content_edit_between_the_end_of_the_read_and_the_final_lstat_with_a_restored_mtime_is_still_an_instability(tmp_path, monkeypatch):
    root = tree_with_aggregate(tmp_path)
    target = root / AGG
    original_stat = os.stat(target)
    armed = {"on": False, "restore": False}
    original = os.read

    def edit_at_eof(descriptor, size):
        data = original(descriptor, size)
        if armed["on"] and data == b"":                         # fin de lecture : le descripteur voit ensuite le fichier modifié (mtime nouveau)
            armed["on"], armed["restore"] = False, True
            with open(target, "r+b") as handle:
                handle.write(SAME_SIZE_B)
        return data

    def restore_mtime(_label, path):
        if path == AGG and armed["restore"]:
            armed["restore"] = False
            with open(target, "r+b") as handle:                 # contenu ET mtime remis à l'identique : l'état final est celui d'origine
                handle.write(SAME_SIZE_A)
            os.utime(target, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    monkeypatch.setattr(os, "read", edit_at_eof)
    hooks = scan.ScanHooks(before_open=lambda label, path: armed.__setitem__("on", path == AGG), after_file_read=restore_mtime)
    refused(lambda: scan_tree(root, hooks, 1), scan.StructuralFailure.UNSTABLE_LISTING)


def test_a_content_edit_between_lstat_and_open_with_the_mtime_restored_before_the_end_of_the_read_is_still_an_instability(tmp_path, monkeypatch):
    root = tree_with_aggregate(tmp_path)
    target = root / AGG
    original_stat = os.stat(target)
    armed = {"on": False}
    original = os.read

    def restore_on_first_read(descriptor, size):
        if armed["on"]:
            armed["on"] = False
            os.utime(target, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        return original(descriptor, size)

    def edit_before_open(_label, path):
        if path == AGG:
            with open(target, "r+b") as handle:                  # `fstat` juste après l'ouverture voit le mtime modifié
                handle.write(SAME_SIZE_B)
            armed["on"] = True
    monkeypatch.setattr(os, "read", restore_on_first_read)
    refused(lambda: scan_tree(root, scan.ScanHooks(before_open=edit_before_open), 1), scan.StructuralFailure.UNSTABLE_LISTING)


def test_a_scan_result_cannot_carry_a_cumulative_hashed_volume_above_its_total_cap_even_if_each_file_fits(tmp_path):
    files = {"walk_forward/aggregate.json": b"a" * 600, "walk_forward/manifest.json": b"b" * 600}
    result = run(tmp_path, files, hl=hash_limits(max_hashed_file_bytes=1024, max_total_hashed_bytes=4096))
    cap = hash_limits(max_hashed_file_bytes=1024, max_total_hashed_bytes=1024)
    base = dict(roots=result.roots, observations=result.observations, attempts_used=1, bytes_read=result.bytes_read, rules_digest=result.rules_digest,
                hooks_used=False, limits=result.limits)
    assert result.hashed_bytes_read == 1200
    with pytest.raises(ValueError):
        scan.ExposureScan(**base, hash_limits=cap, hashed_bytes_read=1200, hashed_files=2)


def test_a_descriptor_that_is_not_a_regular_file_when_opened_is_never_read(tmp_path, monkeypatch):
    root = tree_with_aggregate(tmp_path)
    armed = {"on": False, "reading": False}
    reads_after = []
    original_fstat, original_read = os.fstat, os.read

    def fake_fstat(descriptor):
        real = original_fstat(descriptor)
        if armed["on"]:
            armed["on"], armed["reading"] = False, True
            values = list(tuple(real)[:10])
            values[0] = stat.S_IFIFO | 0o600
            return os.stat_result(values)
        return real

    def spy(descriptor, size):
        if armed["reading"]:
            reads_after.append(size)
        return original_read(descriptor, size)
    monkeypatch.setattr(os, "fstat", fake_fstat)
    monkeypatch.setattr(os, "read", spy)
    refused(lambda: scan_tree(root, arm_on(AGG, armed), 1), scan.StructuralFailure.UNSTABLE_LISTING)
    assert reads_after == []


def test_even_a_file_that_grows_without_bound_is_read_at_most_the_per_file_limit_plus_one_byte(tmp_path, monkeypatch):
    root = tree_with_aggregate(tmp_path)
    target = root / AGG
    armed = {"on": False}
    delivered = []
    original = os.read

    def counting(descriptor, size):
        data = original(descriptor, size)
        if armed["on"]:
            delivered.append(len(data))
        return data
    monkeypatch.setattr(os, "read", counting)

    def grow_then_arm(_label, path):
        if path == AGG:
            target.write_bytes(b"g" * (3 * MAX_CHUNK))        # croissance APRÈS le `lstat`, AVANT l'ouverture
            armed["on"] = True
    refused(lambda: scan_tree(root, scan.ScanHooks(before_open=grow_then_arm), 1), scan.StructuralFailure.UNSTABLE_LISTING)
    assert 0 < sum(delivered) <= hash_limits().max_hashed_file_bytes + 1


def test_hash_limits_of_a_wrong_type_are_a_type_error_even_when_no_hashed_file_was_observed(tmp_path):
    root = make_tree(tmp_path, {"plan.json": b"{}"})
    rules = (scan.SourceRule(("plan.json",), scan.EntryClass.INFORMATIVE_JSON, scan.JsonKind.OBJECT, tag="plan"),)
    ok = scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), rules, limits())
    base = dict(roots=ok.roots, observations=ok.observations, attempts_used=1, bytes_read=ok.bytes_read, rules_digest=ok.rules_digest, hooks_used=False, limits=ok.limits)
    for bad in ("x", {"max_hashed_files": 1}, limits(), 5):
        with pytest.raises(TypeError):
            scan.ExposureScan(**base, hash_limits=bad, hashed_bytes_read=0, hashed_files=0)


# ══ Défauts démontrés par la revue indépendante : budget des lectures avortées, états forgés ═══════════════════════════════════════
def test_bytes_delivered_by_aborted_hashed_reads_are_charged_so_many_failing_files_cannot_exhaust_the_io_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(scan, "_HASH_CHUNK", 1024)
    files = {f"walk_forward/folds/fold_{i:03d}/oos_trades.csv": b"d" * 3000 for i in range(16)}
    delivered = []
    original = os.read

    def fail_after_the_first_chunk(descriptor, size):
        data = original(descriptor, size)
        delivered.append(len(data))
        if len(delivered) % 3 == 0:
            raise OSError("verrou simulé sur la fin du fichier")
        return data
    monkeypatch.setattr(os, "read", fail_after_the_first_chunk)
    tight = hash_limits(max_hashed_file_bytes=3000, max_total_hashed_bytes=3000, max_hashed_files=16)
    error = refused(lambda: run(tmp_path, files, hl=tight, lim=limits(max_attempts=1)), scan.StructuralFailure.LIMIT_EXCEEDED)
    assert "max_total_hashed_bytes" in error.detail
    assert sum(delivered) <= 2 * (tight.max_total_hashed_bytes + 1)            # au plus une passe partielle, jamais 16 fichiers x 3000 octets


def test_a_file_that_grows_during_the_second_pass_cannot_push_the_delivered_bytes_past_the_hashed_budget_plus_one_byte(tmp_path, monkeypatch):
    big, small = b"a" * 999, b"b"
    root = make_tree(tmp_path, {"walk_forward/aggregate.json": big, "walk_forward/manifest.json": small})
    tight = hash_limits(max_hashed_file_bytes=1000, max_total_hashed_bytes=1000, max_hashed_files=2)
    calls = {"n": 0}
    delivered = []
    original = os.read

    def counting(descriptor, size):
        data = original(descriptor, size)
        delivered.append(len(data))
        return data
    monkeypatch.setattr(os, "read", counting)

    def grow_in_second_pass(_label, path):
        if path == "walk_forward/manifest.json":
            calls["n"] += 1
            if calls["n"] == 2:
                (root / "walk_forward" / "manifest.json").write_bytes(b"g" * 1000)
    refused(lambda: scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), wf_rules(), limits(max_attempts=1), hash_limits=tight,
                                          hooks=scan.ScanHooks(before_open=grow_in_second_pass)), scan.StructuralFailure.LIMIT_EXCEEDED)
    assert sum(delivered) <= 2 * (tight.max_total_hashed_bytes + 1) + 2 * 2


def test_the_worst_case_bound_covers_every_delivered_byte_not_only_the_charged_ones():
    lim, hl = limits(max_attempts=3), hash_limits()
    assert scan.scan_worst_case_read_bytes(lim, hl) == 3 * 2 * (lim.max_entries * (lim.max_json_bytes + 1) + hl.max_total_hashed_bytes + 1)


@pytest.mark.parametrize("overrides", [
    dict(anomaly=scan.SourceAnomaly.UNREADABLE, content_hash=None, size=None),      # une taille est toujours mesurée par `lstat` pour un fichier
    dict(anomaly=scan.SourceAnomaly.TOO_LARGE, content_hash=None, size=-1),
    dict(size=-1),
    dict(size=True),
])
def test_a_hashed_file_observation_always_carries_its_measured_size(overrides):
    with pytest.raises((ValueError, TypeError)):
        observation(**overrides)


def test_a_scan_result_cannot_carry_hashed_observations_inconsistent_with_its_hash_limits(tmp_path):
    result = run(tmp_path, BASE)
    base = dict(roots=result.roots, attempts_used=1, bytes_read=result.bytes_read, rules_digest=result.rules_digest, hooks_used=False, limits=result.limits)
    manifest_path = "walk_forward/manifest.json"
    others = tuple(o for o in result.observations if o.relative_path != manifest_path)
    real = by_path(result)[manifest_path]
    oversized = dataclasses.replace(real, size=5000)
    cap = hash_limits(max_hashed_file_bytes=1024)
    with pytest.raises(ValueError):                                         # un fichier « propre » ne peut pas dépasser le plafond par fichier
        scan.ExposureScan(**base, observations=others + (oversized,), hash_limits=cap, hashed_bytes_read=result.hashed_bytes_read - real.size + 5000,
                          hashed_files=result.hashed_files)
    too_large_but_small = dataclasses.replace(real, anomaly=scan.SourceAnomaly.TOO_LARGE, content_hash=None)
    with pytest.raises(ValueError):                                         # TOO_LARGE exige une taille réellement supérieure au plafond
        scan.ExposureScan(**base, observations=others + (too_large_but_small,), hash_limits=cap, hashed_bytes_read=result.hashed_bytes_read - real.size,
                          hashed_files=result.hashed_files)


# ══ Audit final B2 (mission pin) : budget des lectures avortées, répétitions, anciens mutants survivants ═══════════════════════════
def delivered_counter(monkeypatch):
    delivered = []
    original = os.read

    def counting(descriptor, size):
        data = original(descriptor, size)
        delivered.append(len(data))
        return data
    monkeypatch.setattr(os, "read", counting)
    return delivered


def scan_tree_with(root, hooks, lim, hl):
    return scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), wf_rules(), lim, hooks=hooks, hash_limits=hl)


def test_a_one_byte_growth_past_the_exact_hashed_budget_is_a_refusal_naming_the_limit_with_at_most_budget_plus_one_delivered(tmp_path, monkeypatch):
    big, small = b"a" * 700, b"b" * 300
    root = make_tree(tmp_path, {AGG: big, "walk_forward/manifest.json": small})
    exact = hash_limits(max_hashed_file_bytes=1000, max_total_hashed_bytes=1000, max_hashed_files=2)
    assert scan_tree_with(root, None, limits(max_attempts=1), exact).hashed_bytes_read == 1000          # le budget exact suffit
    delivered = delivered_counter(monkeypatch)
    grow = once_on("walk_forward/manifest.json", lambda: (root / "walk_forward" / "manifest.json").write_bytes(small + b"!"))
    error = refused(lambda: scan_tree_with(root, scan.ScanHooks(before_open=grow), limits(max_attempts=1), exact), scan.StructuralFailure.LIMIT_EXCEEDED)
    assert "max_total_hashed_bytes" in error.detail
    assert sum(delivered) <= 1000 + 1


def test_repeated_unstable_attempts_deliver_in_total_more_than_one_attempt_and_never_more_than_the_documented_worst_case(tmp_path, monkeypatch):
    delivered = delivered_counter(monkeypatch)
    root = tree_with_aggregate(tmp_path)
    toggle = {"n": 0}

    def alternate(_attempt):
        toggle["n"] += 1
        rewrite_in_place(root / AGG, SAME_SIZE_B if toggle["n"] % 2 else SAME_SIZE_A)
    lim, hl = limits(max_attempts=4), hash_limits()
    refused(lambda: scan_tree_with(root, scan.ScanHooks(after_first_pass=alternate), lim, hl), scan.StructuralFailure.UNSTABLE_LISTING)
    assert 4 * 2 * len(SAME_SIZE_A) <= sum(delivered) <= scan.scan_worst_case_read_bytes(lim, hl)       # quatre essais x deux passes ont relu le fichier


def test_randomised_hostile_reads_never_deliver_more_bytes_than_the_documented_bound(tmp_path, monkeypatch):
    generator = random.Random(2026)
    monkeypatch.setattr(scan, "_HASH_CHUNK", 64)
    original = os.read
    delivered = []

    def hostile_read(descriptor, size):
        if generator.random() < 0.15:
            raise OSError("erreur d'E/S simulée")
        data = original(descriptor, size)
        delivered.append(len(data))
        return data
    monkeypatch.setattr(os, "read", hostile_read)
    for round_number in range(40):
        files = {f"walk_forward/folds/fold_{i:03d}/oos_trades.csv": os.urandom(generator.randint(0, 300)) for i in range(generator.randint(1, 6))}
        hl = hash_limits(max_hashed_file_bytes=generator.randint(50, 300), max_total_hashed_bytes=generator.randint(300, 900), max_hashed_files=generator.randint(1, 6))
        lim = limits(max_attempts=generator.randint(1, 3))
        delivered.clear()
        try:
            run(tmp_path / f"round{round_number}", files, lim=lim, hl=hl)
        except scan.ExposureScanRefusal:
            pass
        assert sum(delivered) <= lim.max_attempts * 2 * (hl.max_total_hashed_bytes + 1), round_number      # arbre sans JSON : borne PAR PASSE du seul budget haché


def test_the_read_loop_never_issues_a_zero_length_read_and_observes_end_of_file_for_a_file_of_exactly_the_limit(tmp_path, monkeypatch):
    calls = []
    original = os.read

    def spy(descriptor, size):
        data = original(descriptor, size)
        calls.append((size, len(data)))
        return data
    monkeypatch.setattr(os, "read", spy)
    exact = run(tmp_path / "exact", {AGG: b"x" * 1024}, hl=hash_limits(max_hashed_file_bytes=1024))        # arbre à UN seul fichier : toutes les lectures sont les siennes
    assert by_path(exact)[AGG].content_hash == sha(b"x" * 1024)
    assert calls == [(1025, 1024), (1, 0)] * 2                                  # par passe : octet sentinelle demandé en plus, puis fin de fichier OBSERVÉE (lecture vide)
    calls.clear()
    empty = run(tmp_path / "empty", {AGG: b""})
    assert by_path(empty)[AGG].content_hash == sha(b"") and calls and all(asked >= 1 and got == 0 for asked, got in calls)
    calls.clear()
    root = make_tree(tmp_path / "grow", {AGG: SAME_SIZE_A})
    grow = once_on(AGG, lambda: (root / AGG).write_bytes(b"g" * 5000))        # croissance APRÈS le lstat : l'octet sentinelle est livré, la lecture s'arrête là
    refused(lambda: scan_tree_with(root, scan.ScanHooks(before_open=grow), limits(max_attempts=1), hash_limits()), scan.StructuralFailure.UNSTABLE_LISTING)
    assert calls == [(1025, 1025)]                                              # une seule lecture, jamais de lecture de longueur nulle après la sentinelle


def test_a_file_that_vanishes_between_lstat_and_open_is_reported_as_such_in_the_instability_refusal(tmp_path):
    root = tree_with_aggregate(tmp_path)
    vanish = once_on(AGG, lambda: (root / AGG).unlink())
    error = refused(lambda: scan_tree_with(root, scan.ScanHooks(before_open=vanish), limits(max_attempts=1), hash_limits()), scan.StructuralFailure.UNSTABLE_LISTING)
    assert "a disparu entre le lstat et l'ouverture" in error.detail


# ══ D8-E : compatibilité B3 / B5, versions, absence de verdict ════════════════════════════════════════════════════════════════════
from types import SimpleNamespace


def test_an_exposure_scan_built_the_historical_way_with_seven_arguments_still_validates(tmp_path):
    root = make_tree(tmp_path, {"plan.json": b"{}"})
    rules = (scan.SourceRule(("plan.json",), scan.EntryClass.INFORMATIVE_JSON, scan.JsonKind.OBJECT, tag="plan"),)
    modern = scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), rules, limits())
    old_style = scan.ExposureScan(modern.roots, modern.observations, modern.attempts_used, modern.bytes_read, modern.rules_digest, False, modern.limits)
    assert old_style == modern and (old_style.hash_limits, old_style.hashed_files, old_style.hashed_bytes_read) == (None, 0, 0)


def test_a_scan_result_cannot_be_forged_with_inconsistent_hashed_accounting(tmp_path):
    result = run(tmp_path, BASE)
    base = dict(roots=result.roots, observations=result.observations, attempts_used=1, bytes_read=result.bytes_read, rules_digest=result.rules_digest,
                hooks_used=False, limits=result.limits)
    assert scan.ExposureScan(**base, hash_limits=result.hash_limits, hashed_bytes_read=result.hashed_bytes_read, hashed_files=result.hashed_files) == result
    for forged in (dict(hash_limits=None, hashed_bytes_read=result.hashed_bytes_read, hashed_files=result.hashed_files),      # fichiers hachés sans plafonds
                   dict(hash_limits=result.hash_limits, hashed_bytes_read=result.hashed_bytes_read + 1, hashed_files=result.hashed_files),
                   dict(hash_limits=result.hash_limits, hashed_bytes_read=result.hashed_bytes_read, hashed_files=result.hashed_files + 1),
                   dict(hash_limits=hash_limits(max_hashed_files=1), hashed_bytes_read=result.hashed_bytes_read, hashed_files=result.hashed_files),
                   dict(hash_limits=hash_limits(max_hashed_file_bytes=1, max_total_hashed_bytes=1), hashed_bytes_read=result.hashed_bytes_read, hashed_files=result.hashed_files),
                   dict(hash_limits={"max_hashed_files": 1}, hashed_bytes_read=0, hashed_files=0),
                   dict(hash_limits=result.hash_limits, hashed_bytes_read=True, hashed_files=result.hashed_files),
                   dict(hash_limits=result.hash_limits, hashed_bytes_read=-1, hashed_files=result.hashed_files)):
        with pytest.raises((ValueError, TypeError)):
            scan.ExposureScan(**base, **forged)


def test_an_unreadable_hashed_file_larger_than_the_per_file_limit_is_a_contradiction_the_scanner_would_have_reported_as_too_large(tmp_path):
    result = run(tmp_path, BASE)
    small = hash_limits(max_hashed_file_bytes=100, max_total_hashed_bytes=1000, max_hashed_files=5)

    def forged(size):
        unreadable = observation(anomaly=scan.SourceAnomaly.UNREADABLE, content_hash=None, size=size)
        return scan.ExposureScan(roots=result.roots, observations=(unreadable,), attempts_used=1, bytes_read=0, rules_digest=result.rules_digest,
                                 hooks_used=False, limits=result.limits, hash_limits=small, hashed_bytes_read=0, hashed_files=1)
    assert forged(50).hashed_files == 1                                          # témoin : la même construction avec une taille admissible est valide
    with pytest.raises(ValueError):
        forged(500)


def test_a0_scan_pins_still_carry_exactly_the_nine_historical_limits_and_never_the_hash_limits(tmp_path):
    import gate_v_exposure_store as store
    root = make_tree(tmp_path, {"plan.json": b"{}"})
    historical_rules = (scan.SourceRule(("plan.json",), scan.EntryClass.INFORMATIVE_JSON, scan.JsonKind.OBJECT, tag="plan"),)
    result = scan.scan_audit_roots((scan.AuditRoot("main", str(root)),), historical_rules, limits())       # scan historique : aucun plafond haché appliqué
    assert result.hash_limits is None
    import gate_v_exposure_interpreters as b3
    pins = store._scan_pins(SimpleNamespace(semantics_version="gate_v_exposure_interpreters_v4",
                                            scans=[SimpleNamespace(layout=b3.RootLayout.RESULTS, scan=result)]))
    assert set(pins[0]["limits"]) == set(HISTORICAL_LIMIT_NAMES) and "hash" not in json.dumps(pins).lower()
    valid = {"layout": "RESULTS", "rules_digest": result.rules_digest, "limits": dict(pins[0]["limits"]), "hooks_used": False, "roots": []}
    assert store._scan_pin(valid, "pin").limits == result.limits                    # un A0 déjà persisté se relit à l'identique
    extended = dict(valid, limits=dict(valid["limits"], max_hashed_files=16))
    with pytest.raises(store._Schema):                                              # B5 refuse (strict) un bloc étendu : le pin des plafonds hachés exige une décision B5 / B3 v5
        store._scan_pin(extended, "pin")


def test_the_scanner_stays_an_observer_hashed_files_create_no_finding_no_verdict_no_authorisation():
    members = {m.value for e in (scan.SourceAnomaly, scan.StructuralFailure, scan.EntryClass, scan.EntryKind, scan.JsonKind) for m in e}
    assert not {v for v in members if any(w in v for w in ("FRESH", "EXPOSED", "RETROSPECTIVE", "UNDETERMINED", "ADMISSION", "AUTHORI", "NO_OVERLAP"))}
    public = {name for name in vars(scan) if not name.startswith("_")}
    assert not {name for name in public if name.lower().startswith(("classify", "admit", "authoris", "authoriz", "verdict", "finding"))}
    assert scan.HASHED_FILE_SEMANTICS_VERSION == "gate_v_scan_hashed_file_v1"


def test_the_published_b3_tables_recomputed_with_the_amended_scanner_keep_their_frozen_v4_digests_and_contain_no_hashed_or_publication_rule():
    import gate_v_exposure_interpreters as b3
    latest = {layout: digest for version, layout, digest in b3.B3_RULES_DIGESTS if version == "gate_v_exposure_interpreters_v4"}
    assert set(latest) == set(b3.RootLayout)
    for layout in b3.RootLayout:
        rules = b3.source_rules(layout)
        assert rules and scan._rules_digest(rules) == latest[layout]                     # formule de B2 amendée, tables B3 inchangées : digest identique
        assert not any(rule.entry_class.is_hashed for rule in rules)
        assert all(_orphan_regex_is_historical(rule) for rule in rules if rule.entry_class is scan.EntryClass.TEMP_ORPHAN_FILE)
    for key, digest in B3_FROZEN_DIGESTS.items():
        assert {(v, lay.value): d for v, lay, d in b3.B3_RULES_DIGESTS}[key] == digest


def _orphan_regex_is_historical(rule) -> bool:
    return rule.segments[-1].regex == scan.EXPOSURE_TEMP_ORPHAN_PATTERN
