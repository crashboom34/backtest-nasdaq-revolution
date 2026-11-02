"""K1 Étape 2, lot L3-A : conversion PURE `ExposureScan` (B2, table fermée B3 v5-A) → `ObservedRunTree`, puis vérification de bout en bout.

Les arbres sont écrits SUR DISQUE (`tmp_path`, contenus synthétiques, aucune donnée de marché, aucun FINAL_HOLDOUT) et lus par le VRAI scan B2 sous la table
fermée de B3 v5-A : le hash et la taille de chaque sortie viennent donc du scan, jamais d'un objet construit à la main. Les valeurs attendues sont recalculées
ici avec `hashlib` (oracle indépendant). Un résultat positif reste « cohérent avec les observations fournies » : le scan de ces tests n'est pas un rescan
indépendant (E3-J).
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import os
from pathlib import Path

import pytest

import gate_v_exposure_interpreters as b3
import gate_v_exposure_interpreters_v5 as v5
import gate_v_exposure_scan as scan
import gate_v_k1s2_observations as obs
import gate_v_k1s2_verifier as vf
from gate_v_exposure_scan import AuditRoot, HashLimits
from tests.gate_v_exposure_support import LIMITS, write_json
from tests.test_gate_v_k1s2_verifier import CID, K, OTHER_CID, RUN, RUN_FILE, SEAL, SESSION1, V5_DIGEST, V5_VERSION, models, sha, tree_of, world

HL = HashLimits(max_hashed_file_bytes=65_536, max_total_hashed_bytes=2_000_000, max_hashed_files=200)
CAMPAIGN = b3.RootLayout.CAMPAIGN_DIR
OUTPUT = "walk_forward/manifest.json"
ORPHAN_SUFFIX = "." + "ab" * 16 + ".tmp"


def write_tree(directory: Path, files: dict) -> Path:
    write_json(directory / "plan.json", {"campaign_id": directory.name})
    for relative, data in files.items():
        target = directory / relative
        if data is None:                                              # répertoire vide
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return directory


def scan_of(directory: Path, *, label: str = "camp", rules=None):
    rules = v5.source_rules_v5(CAMPAIGN) if rules is None else rules
    return scan.scan_audit_roots((AuditRoot(label, str(directory)),), rules, LIMITS, hash_limits=HL)


def verified(tmp_path, files: dict, *, name: str = CID):
    directory = write_tree(tmp_path / name, files)
    tree = obs.observed_tree_from_scan(scan_of(directory), root_label="camp", campaign_dir_name=name)
    return vf.verify_run_chain(tree, RUN)


# ══ Bout en bout : le vrai scan B2 sur disque ═══════════════════════════════════════════════════════════════════════════════════════
def test_a_consistent_chain_read_by_the_real_scan_is_established_with_independently_recomputed_facts(tmp_path):
    files = world()
    report = verified(tmp_path, files)
    assert report.established, [(d.code.value, d.path, d.detail) for d in report.defects]
    coverage, sessions, seal, outputs, run_data = models()
    facts = report.facts
    assert (facts.coverage_sha256, facts.run_record_sha256, facts.seal_sha256) == (hashlib.sha256(coverage.to_bytes()).hexdigest(), hashlib.sha256(run_data).hexdigest(),
                                                                                    hashlib.sha256(seal.to_bytes()).hexdigest())
    assert (facts.output_count, facts.output_bytes) == (len(outputs), sum(len(d) for d in outputs.values()))
    assert report.requires_independent_rescan is True


def test_the_scan_derived_tree_has_the_same_hashed_files_as_the_independent_in_memory_oracle(tmp_path):
    files = world()
    directory = write_tree(tmp_path / CID, files)
    from_scan = obs.observed_tree_from_scan(scan_of(directory), root_label="camp", campaign_dir_name=CID)
    oracle = tree_of(files)
    pick = lambda tree: {(i.path, i.size, i.sha256) for i in tree.items if i.kind is vf.ObservedKind.FILE and (i.path.startswith(("walk_forward/", "validations/")))}  # noqa: E731
    assert pick(from_scan) == pick(oracle) and len(pick(oracle)) == len(files)          # plan.json (hors périmètre) est le seul fichier propre ignoré par `pick`
    retained = {i.path for i in from_scan.items if i.content is not None}
    assert retained == {path for path in files if path.startswith("validations/")}       # octets conservés sous le run seulement ; jamais ceux des sorties


def test_the_item_order_of_the_scan_does_not_change_the_tree_or_the_report(tmp_path):
    directory = write_tree(tmp_path / CID, world())
    result = scan_of(directory)
    reordered = dataclasses.replace(result, observations=tuple(reversed(result.observations)))
    first = obs.observed_tree_from_scan(result, root_label="camp", campaign_dir_name=CID)
    second = obs.observed_tree_from_scan(reordered, root_label="camp", campaign_dir_name=CID)
    assert first == second and vf.verify_run_chain(first, RUN) == vf.verify_run_chain(second, RUN)


def without(files: dict, *paths) -> dict:
    return {path: data for path, data in files.items() if path not in paths}


DISK_CASES = {
    "modified_output": (lambda f: {**f, OUTPUT: b"altered bytes\n"}, {K.OUTPUT_ALTERED}),
    "output_with_same_size_other_bytes": (lambda f: {**f, OUTPUT: bytes(reversed(f[OUTPUT]))}, {K.OUTPUT_ALTERED}),
    "missing_output": (lambda f: without(f, OUTPUT), {K.OUTPUT_MISSING}),
    "extra_recognised_output": (lambda f: {**f, "walk_forward/folds/fold_002/definition.json": b"{}"}, {K.OUTPUT_UNSEALED}),
    "unknown_file_in_outputs": (lambda f: {**f, "walk_forward/notes.txt": b"x"}, {K.UNKNOWN_RUN_FILE}),
    "publication_orphan_in_outputs": (lambda f: {**f, OUTPUT + ORPHAN_SUFFIX: b"half"}, {K.OUTPUT_ORPHAN}),
    "publication_orphan_in_run_dir": (lambda f: {**f, RUN_FILE + ORPHAN_SUFFIX: b"half"}, {K.RUN_FILE_ORPHAN}),
    "empty_fold_directory": (lambda f: {**f, "walk_forward/folds/fold_002": None}, {K.EMPTY_OUTPUT_DIRECTORY}),
    "unknown_entry_in_campaign": (lambda f: {**f, "stray.txt": b"x"}, {K.UNKNOWN_ENTRY_IN_TREE}),
    "missing_seal": (lambda f: without(f, SEAL), {K.NO_SEAL}),
    "missing_session": (lambda f: without(f, SESSION1), {K.SESSION_MISSING}),
    "missing_validation_run": (lambda f: without(f, RUN_FILE), {K.NO_VALIDATION_RUN}),
    "truncated_seal_json": (lambda f: {**f, SEAL: b"{"}, {K.RUN_FILE_ANOMALY, K.NO_SEAL}),
    "oversized_output": (lambda f: {**f, OUTPUT: b"x" * 70_000}, {K.OUTPUT_ANOMALY, K.OUTPUT_MISSING}),
    "second_walk_forward_run": (lambda f: {**f, f"validations/{OTHER_CID}_walk_forward/run_seal.json": b"{}"}, {K.MIXED_RUNS}),
    "wrong_run_record": (lambda f: {**f, RUN_FILE: b'{"validation_run_id": "x", "validation_type": "walk_forward"}'}, {K.RUN_NOT_ATTRIBUTABLE, K.RUN_ALTERED}),
}


@pytest.mark.parametrize("name", sorted(DISK_CASES))
def test_a_real_disk_tree_that_departs_from_the_seal_is_refused_with_the_expected_code(tmp_path, name):
    mutate, expected = DISK_CASES[name]
    report = verified(tmp_path, mutate(world()))
    assert report.established is False and report.facts is None
    assert expected <= {d.code for d in report.defects}, [(d.code.value, d.path) for d in report.defects]


def test_a_symbolic_link_in_the_outputs_stops_the_scan_so_no_tree_and_no_verification_can_exist(tmp_path):
    directory = write_tree(tmp_path / CID, without(world(), OUTPUT))
    try:
        os.symlink(directory / "plan.json", directory / OUTPUT)
    except (OSError, NotImplementedError):
        pytest.skip("création de lien symbolique non permise sur ce poste")
    with pytest.raises(scan.ExposureScanRefusal) as caught:                  # B2 refuse AVANT toute observation : il n'y a rien à convertir ni à vérifier
        scan_of(directory)
    assert caught.value.failure is scan.StructuralFailure.LINK_OR_REPARSE_POINT


# ══ Refus à la frontière de conversion ══════════════════════════════════════════════════════════════════════════════════════════════
def refused(**kwargs):
    with pytest.raises(vf.ObservationRefused) as caught:
        obs.observed_tree_from_scan(**kwargs)
    return caught.value.code


def test_the_conversion_refuses_a_scan_of_another_table_a_hooked_scan_a_wrong_root_and_wrong_types(tmp_path):
    directory = write_tree(tmp_path / CID, world())
    good = scan_of(directory)
    v4_scan = scan_of(directory, rules=b3.source_rules(CAMPAIGN))
    assert refused(scan=v4_scan, root_label="camp", campaign_dir_name=CID) is vf.ObservationRefusal.BAD_TREE            # table v4 : digest différent
    assert refused(scan=dataclasses.replace(good, hooks_used=True), root_label="camp", campaign_dir_name=CID) is vf.ObservationRefusal.BAD_TREE
    assert refused(scan=good, root_label="other", campaign_dir_name=CID) is vf.ObservationRefusal.BAD_TREE
    assert refused(scan=good, root_label="camp", campaign_dir_name=OTHER_CID) is vf.ObservationRefusal.BAD_TREE         # dossier racine ≠ dossier annoncé
    for bad in (None, object(), good.observations, "scan"):
        assert refused(scan=bad, root_label="camp", campaign_dir_name=CID) is vf.ObservationRefusal.BAD_TREE
    assert refused(scan=good, root_label=3, campaign_dir_name=CID) is vf.ObservationRefusal.BAD_TREE


def observation(**changes) -> scan.ScanObservation:
    fields = dict(root_label="camp", relative_path="walk_forward/x.txt", kind=scan.EntryKind.FILE, entry_class=scan.EntryClass.INERT_FILE, anomaly=None, size=3,
                  mtime_ns=1, st_ino=1, st_dev=1, content_hash=None, value_parsed=False, content_bytes=None, rule_tag="t")
    fields.update(changes)
    return scan.ScanObservation(**fields)


def test_a_clean_unhashed_file_is_kept_as_inert_and_refused_by_the_verifier_only_inside_the_chain_scope():
    run_dir = f"validations/{RUN}"
    outside = obs.observed_item_from_scan(observation(relative_path="notes/readme.txt"), run_dir)
    inside = obs.observed_item_from_scan(observation(relative_path="walk_forward/readme.txt"), run_dir)
    in_run = obs.observed_item_from_scan(observation(relative_path=f"{run_dir}/readme.txt"), run_dir)
    assert outside.kind is inside.kind is in_run.kind is vf.ObservedKind.INERT and (outside.size, outside.sha256, outside.content) == (None, None, None)
    base = tree_of(world())
    for item, expected in ((inside, K.OUTPUT_ANOMALY), (in_run, K.RUN_FILE_ANOMALY)):
        report = vf.verify_run_chain(vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, (*base.items, item)), RUN)
        assert report.established is False and {d.code for d in report.defects} == {expected}
    assert vf.verify_run_chain(vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, (*base.items, outside)), RUN).established is True


def test_the_conversion_never_drops_an_observation_and_keeps_the_root_manifest_bytes(tmp_path):
    from tests.test_gate_v_exposure_interpreters_v4 import manifest_record
    import json
    directory = write_tree(tmp_path / CID, world())
    (directory / "manifest.json").write_bytes(json.dumps(manifest_record(), indent=2).encode())
    (directory / "datasets" / "d1").mkdir(parents=True)
    result = scan_of(directory)
    tree = obs.observed_tree_from_scan(result, root_label="camp", campaign_dir_name=CID)
    assert {item.path for item in tree.items} == {o.relative_path for o in result.observations if o.root_label == "camp"}     # aucune observation perdue
    manifest = next(item for item in tree.items if item.path == "manifest.json")
    assert manifest.content == (directory / "manifest.json").read_bytes() and manifest.sha256 == hashlib.sha256(manifest.content).hexdigest()
    assert all(item.content is None for item in tree.items if not item.path.startswith("validations/") and item.path != "manifest.json")


def test_unknown_anomalous_orphan_and_directory_entries_keep_their_nature():
    unknown = obs.observed_item_from_scan(observation(entry_class=None, anomaly=scan.SourceAnomaly.UNKNOWN_FILE), None)
    broken = obs.observed_item_from_scan(observation(entry_class=scan.EntryClass.HASHED_FILE, anomaly=scan.SourceAnomaly.UNREADABLE, size=4), None)
    orphan = obs.observed_item_from_scan(observation(entry_class=scan.EntryClass.TEMP_ORPHAN_FILE), None)
    directory = obs.observed_item_from_scan(observation(kind=scan.EntryKind.DIRECTORY, entry_class=scan.EntryClass.STRUCTURAL_DIRECTORY, size=None, mtime_ns=None), None)
    assert (unknown.kind, unknown.anomaly) == (vf.ObservedKind.UNKNOWN, "UNKNOWN_FILE")
    assert (broken.kind, broken.anomaly) == (vf.ObservedKind.ANOMALY, "UNREADABLE")
    assert orphan.kind is vf.ObservedKind.ORPHAN and directory.kind is vf.ObservedKind.DIRECTORY
    with pytest.raises(vf.ObservationRefused):
        obs.observed_item_from_scan("not an observation")


def test_the_conversion_module_is_pure_no_io_no_hashing_and_only_the_documented_imports():
    tree = ast.parse(Path(obs.__file__).read_text(encoding="utf-8"))
    imported = {(node.module or "").split(".")[0] if isinstance(node, ast.ImportFrom) else alias.name.split(".")[0]
                for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in (getattr(node, "names", None) or [None])}
    assert imported <= {"__future__", "re", "typing", "gate_v_k1s2_verifier", "gate_v_exposure_scan"}, imported
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "eval", "exec", "__import__", "compile", "print"}
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attributes & {"read_bytes", "read_text", "scandir", "listdir", "walk", "stat", "lstat", "sha256", "hexdigest", "now", "getenv", "environ", "urlopen"}
    assert (v5.B3_V5_SEMANTICS_VERSION, V5_DIGEST) == (V5_VERSION, vf.TABLE_DIGEST) == (vf.TABLE_VERSION, vf.TABLE_DIGEST)
    campaign_digest = next(d for version, layout, d in v5.B3_V5_RULES_DIGESTS if version == v5.B3_V5_SEMANTICS_VERSION and layout is CAMPAIGN)
    assert campaign_digest == vf.TABLE_DIGEST                                  # constantes figées = celles publiées par B3 v5-A


def test_a_scan_with_the_same_root_label_twice_is_refused_as_ambiguous(tmp_path):
    result = scan_of(write_tree(tmp_path / CID, world()))
    duplicated = dataclasses.replace(result, roots=(result.roots[0], result.roots[0]))
    assert refused(scan=duplicated, root_label="camp", campaign_dir_name=CID) is vf.ObservationRefusal.BAD_TREE
