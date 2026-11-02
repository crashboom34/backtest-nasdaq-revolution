"""K1 Étape 2, lot L3-A : vérificateur PUR de la chaîne de preuves Walk-Forward (`gate_v_k1s2_verifier`).

Un résultat positif signifie UNIQUEMENT : « la chaîne examinée est structurellement et cryptographiquement cohérente avec les observations FOURNIES. »
Il ne prouve ni la lecture réelle d'un worker, ni l'exclusivité des sources, ni l'antériorité du Seal, ni l'absence d'exposition ; aucun verdict FRESH /
NO_OVERLAP / admission / Claim n'existe dans ce module. Fixtures EN MÉMOIRE (aucun disque, aucune donnée de marché, aucun FINAL_HOLDOUT). Les hashs attendus
sont recalculés ICI avec `hashlib`, jamais par le module testé.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

import gate_v_frame_digest as fd
import gate_v_k1s2_verifier as vf
import gate_v_run_evidence_models as ev

CID = "gate_v_v2_" + "cd" * 32
RUN = f"{CID}_walk_forward"
OTHER_CID = "gate_v_v2_" + "ee" * 32
OTHER_RUN = f"{OTHER_CID}_walk_forward"
V5_VERSION = "gate_v_exposure_interpreters_v5"
V5_DIGEST = "aa389aca9e29052ce9812c766f99abaf95a2bb656a3e82fcff17ab041d4a10af"
CSV = ("time,open,high,low,close,tick_volume,spread\n2025-12-31 23:51:00,100.10,100.30,100.00,100.20,7,180\n"
       "2025-12-31 23:54:00,100.20,100.40,100.10,100.30,9,180\n2025-12-31 23:57:00,100.30,100.50,100.20,100.40,11,180\n")
RUNTIME = {"numpy": "2.2.6", "pandas": "3.0.3", "python": "3.13.7"}
K = vf.ChainRefusal
OUTPUT_PATHS = ("walk_forward/manifest.json", "walk_forward/state.json", "walk_forward/aggregate.json", "walk_forward/.gate_v_checkpoints_v1/manifest.json",
                "walk_forward/folds/fold_000/definition.json", "walk_forward/folds/fold_000/oos_trades.csv",
                "walk_forward/folds/fold_001/definition.json", "walk_forward/folds/fold_001/oos_trades.csv",
                "walk_forward/.gate_v_checkpoints_v1/folds/fold_000.json", "walk_forward/.gate_v_checkpoints_v1/folds/fold_001.json")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normative(record) -> bytes:
    return (json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def run_bytes(run_id: str = RUN, validation_type: str = "walk_forward", extra=None) -> bytes:
    record = {"validation_run_id": run_id, "research_run_id": "r", "split_plan_id": "s", "dataset_snapshot_id": "S0", "validation_type": validation_type,
              "strategy_name": "st", "strategy_params": {}, "evidence": {"ratio": 1.5}, "status": "completed", "completed_at": "2025-12-01T00:00:00+00:00"}
    record.update(extra or {})
    return json.dumps(record, indent=2).encode("utf-8")                    # NON normatif et avec un flottant : un vrai `validation_run.json`


def models(run_id: str = RUN, sessions: int = 1, recovery: bool = False, outputs=None, run_data: bytes = None):
    coverage = ev.RunDataCoverage.from_s0_facts(run_id, fd.compute_s0_frame_facts(CSV.encode(), 180), RUNTIME)
    sess = [ev.RunSession.open_for(coverage, i, coverage.frame_sha256, coverage.row_count, i > 1) for i in range(1, sessions + 1)]
    outputs = {p: f"content of {p}\n".encode() for p in OUTPUT_PATHS} if outputs is None else outputs
    run_data = run_bytes(run_id) if run_data is None else run_data
    seal = ev.RunSeal.for_walk_forward(coverage, sess, sha(run_data), [(p, sha(d), len(d)) for p, d in outputs.items()],
                                       None if recovery else coverage.frame_sha256, recovery)
    return coverage, sess, seal, outputs, run_data


def world(run_id: str = RUN, sessions: int = 1, recovery: bool = False, outputs=None, run_data: bytes = None) -> dict:
    """Arbre COHÉRENT : chemin → octets exacts (sorties, preuves L2, ValidationRun)."""
    coverage, sess, seal, outs, run_data = models(run_id, sessions, recovery, outputs, run_data)
    base = f"validations/{run_id}"
    files = {**outs, f"{base}/validation_run.json": run_data, f"{base}/run_data_coverage.json": coverage.to_bytes(), f"{base}/run_seal.json": seal.to_bytes()}
    files.update({f"{base}/run_session_{s.session_index:04d}.json": s.to_bytes() for s in sess})
    return files


def items_of(files: dict) -> list:
    items, directories = [], set()
    for path, data in files.items():
        parts = path.split("/")
        directories.update("/".join(parts[:i]) for i in range(1, len(parts)))
        retained = path.startswith("validations/")            # les preuves JSON et le run sont conservés (EXPOSING_JSON) ; les sorties ne sont que hachées
        items.append(vf.ObservedItem(path, vf.ObservedKind.FILE, size=len(data), sha256=sha(data), content=data if retained else None))
    items += [vf.ObservedItem(d, vf.ObservedKind.DIRECTORY) for d in sorted(directories)]
    return items


def tree_of(files: dict, extra=(), *, name: str = CID, version: str = V5_VERSION, digest: str = V5_DIGEST) -> vf.ObservedRunTree:
    return vf.ObservedRunTree(name, version, digest, tuple(sorted([*items_of(files), *extra], key=lambda item: item.path)))


def verify(files: dict, extra=(), run_id: str = RUN, **tree_kwargs):
    return vf.verify_run_chain(tree_of(files, extra, **tree_kwargs), run_id)


def codes(report) -> set:
    return {defect.code for defect in report.defects}


def replaced(files: dict, **changes) -> dict:
    out = dict(files)
    for relative, data in changes.items():
        out[relative.replace("__", "/")] = data
    return out


BASE = f"validations/{RUN}"
COVERAGE, SESSION1, SEAL, RUN_FILE = (f"{BASE}/run_data_coverage.json", f"{BASE}/run_session_0001.json", f"{BASE}/run_seal.json", f"{BASE}/validation_run.json")


# ══ Tranche 1 : types d'observation, vocabulaire fermé, frontière scientifique ═══════════════════════════════════════════════════════
def test_a_consistent_chain_is_established_and_only_relative_to_the_provided_observations():
    report = verify(world())
    assert report.defects == () and report.established is True and report.run_id == RUN
    facts = report.facts
    coverage, sessions, seal, outputs, run_data = models()
    assert (facts.validation_run_id, facts.coverage_sha256, facts.session_sha256s, facts.run_record_sha256, facts.seal_sha256) == (
        RUN, sha(coverage.to_bytes()), (sha(sessions[0].to_bytes()),), sha(run_data), sha(seal.to_bytes()))
    assert (facts.output_count, facts.output_bytes, facts.session_count) == (len(outputs), sum(len(d) for d in outputs.values()), 1)
    assert report.requires_independent_rescan is True                   # les observations sont fournies par l'appelant : une relecture indépendante reste due (E3-J)
    assert set(report.not_proven) == {"WORKER_READ", "SOURCE_EXCLUSIVITY", "SEAL_ANTERIORITY", "ABSENCE_OF_EXPOSURE", "DURABILITY"}


def test_the_refusal_vocabulary_is_closed_and_carries_no_verdict_word():
    assert all(member.value == member.name for member in K)
    forbidden = ("FRESH", "NO_OVERLAP", "ADMISSION", "ADMIT", "CLAIM", "AUTHORI", "ABSENCE_ESTABLISHED", "EXCLUSION")
    assert not [m.value for m in K if any(word in m.value for word in forbidden)]
    public = {name for name in dir(vf) if not name.startswith("_")}
    assert not [name for name in public if any(word in name.upper() for word in ("FRESH", "NO_OVERLAP", "ADMISSION", "CLAIM", "AUTHORI"))]
    assert {"NO_COVERAGE", "NO_SEAL", "SESSION_MISSING", "SESSION_GAP", "OUTPUT_MISSING", "OUTPUT_UNSEALED", "OUTPUT_ALTERED", "UNKNOWN_RUN_FILE", "RUN_ALTERED",
            "COVERAGE_ALTERED"} <= {m.value for m in K}                  # vocabulaire de R9 section 7.5


def test_the_core_is_pure_no_io_no_clock_no_hashing_of_its_own_and_only_the_documented_imports():
    tree = ast.parse(Path(vf.__file__).read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported <= {"__future__", "dataclasses", "enum", "hashlib", "re", "typing", "gate_v_run_evidence_models", "gate_v_exposure_scan"}, imported
    for module in ("gate_v_k1s2_verifier.py", "gate_v_k1s2_observations.py", "gate_v_k1s2_emptiness.py"):
        text = (Path(vf.__file__).parent / module).read_text(encoding="utf-8")
        assert "gate_v_exposure_interpreters_v5" not in text and "interpret_audit_roots_v5" not in text, module   # garde de B3 : seul B5 référence v5
    called ={node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & {"open", "eval", "exec", "__import__", "compile", "input", "print"}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attributes & {"read_bytes", "read_text", "write_bytes", "write_text", "scandir", "listdir", "walk", "stat", "lstat", "unlink", "remove", "now", "utcnow",
                             "time", "getenv", "environ", "urlopen", "connect", "md5", "sha1", "sha512", "blake2b", "new", "pbkdf2_hmac"}
    hash_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "sha256"
                  and isinstance(node.func.value, ast.Name) and node.func.value.id == "hashlib"]
    assert len(hash_calls) == 1                                          # un seul site : SHA-256 d'OCTETS BRUTS observés ; aucune préimage de L1/L2 recalculée ici


def test_the_frozen_table_identity_equals_the_one_published_by_b3_v5a():
    import gate_v_exposure_interpreters as b3
    import gate_v_exposure_interpreters_v5 as v5
    published = next(d for version, layout, d in v5.B3_V5_RULES_DIGESTS if version == v5.B3_V5_SEMANTICS_VERSION and layout is b3.RootLayout.CAMPAIGN_DIR)
    assert (vf.TABLE_VERSION, vf.TABLE_DIGEST) == (v5.B3_V5_SEMANTICS_VERSION, published) == (V5_VERSION, V5_DIGEST)


@pytest.mark.parametrize("kwargs, code", [
    (dict(path=""), vf.ObservationRefusal.BAD_PATH), (dict(path="/abs"), vf.ObservationRefusal.BAD_PATH), (dict(path="a/../b"), vf.ObservationRefusal.BAD_PATH),
    (dict(path="a\\b"), vf.ObservationRefusal.BAD_PATH), (dict(path="a//b"), vf.ObservationRefusal.BAD_PATH), (dict(path="a/."), vf.ObservationRefusal.BAD_PATH),
    (dict(path="C:/x"), vf.ObservationRefusal.BAD_PATH), (dict(path="a/b "), vf.ObservationRefusal.BAD_PATH), (dict(path="a/b."), vf.ObservationRefusal.BAD_PATH), (dict(path="a./b"), vf.ObservationRefusal.BAD_PATH), (dict(path="a\x00b"), vf.ObservationRefusal.BAD_PATH),
    (dict(path="é".encode("utf-8")), vf.ObservationRefusal.BAD_PATH), (dict(path=None), vf.ObservationRefusal.BAD_PATH),
    (dict(path="x" * 5000), vf.ObservationRefusal.BAD_PATH), (dict(path="a/" + "y" * 300), vf.ObservationRefusal.BAD_PATH),
    (dict(kind="FILE"), vf.ObservationRefusal.BAD_KIND), (dict(kind=None), vf.ObservationRefusal.BAD_KIND),
    (dict(size=None), vf.ObservationRefusal.BAD_SIZE), (dict(size=-1), vf.ObservationRefusal.BAD_SIZE), (dict(size=True), vf.ObservationRefusal.BAD_SIZE),
    (dict(size=1.5), vf.ObservationRefusal.BAD_SIZE),
    (dict(sha256=None), vf.ObservationRefusal.BAD_HASH), (dict(sha256="AB" * 32), vf.ObservationRefusal.BAD_HASH), (dict(sha256="ab" * 31), vf.ObservationRefusal.BAD_HASH),
    (dict(sha256=12), vf.ObservationRefusal.BAD_HASH),
    (dict(content="text"), vf.ObservationRefusal.BAD_CONTENT), (dict(content=b"zz"), vf.ObservationRefusal.INCONSISTENT),
    (dict(anomaly="TOO_LARGE"), vf.ObservationRefusal.INCONSISTENT),
], ids=lambda value: None if isinstance(value, dict) else str(value))
def test_a_hostile_or_inconsistent_observation_cannot_be_built(kwargs, code):
    good = dict(path="walk_forward/a.json", kind=vf.ObservedKind.FILE, size=3, sha256=sha(b"abc"), content=b"abc", anomaly=None)
    with pytest.raises(vf.ObservationRefused) as info:
        vf.ObservedItem(**{**good, **kwargs})
    assert info.value.code is code and isinstance(info.value, ValueError)


@pytest.mark.parametrize("kwargs", [
    dict(kind=vf.ObservedKind.DIRECTORY, size=1, sha256=None), dict(kind=vf.ObservedKind.DIRECTORY, size=None, sha256=sha(b"x")),
    dict(kind=vf.ObservedKind.DIRECTORY, size=None, sha256=None, content=b"x"), dict(kind=vf.ObservedKind.ORPHAN, size=None, sha256=sha(b"x")),
    dict(kind=vf.ObservedKind.UNKNOWN, size=None, sha256=None, anomaly="UNKNOWN_FILE", content=b"x"),
    dict(kind=vf.ObservedKind.ANOMALY, size=None, sha256=None, anomaly=None), dict(kind=vf.ObservedKind.ANOMALY, size=None, sha256=None, anomaly=""),
    dict(kind=vf.ObservedKind.ANOMALY, size=None, sha256=sha(b"x"), anomaly="UNREADABLE"),
])
def test_only_a_clean_file_carries_a_size_a_hash_or_bytes_and_an_anomaly_exists_only_for_the_anomaly_kind(kwargs):
    base = dict(path="walk_forward/x", kind=vf.ObservedKind.DIRECTORY, size=None, sha256=None, content=None, anomaly=None)
    with pytest.raises(vf.ObservationRefused):
        vf.ObservedItem(**{**base, **kwargs})


def test_a_tree_refuses_duplicate_paths_wrong_types_a_malformed_campaign_name_and_an_excess_of_items():
    item = vf.ObservedItem("walk_forward", vf.ObservedKind.DIRECTORY)
    for bad in ((item, item), [item], (item, "x"), None):
        with pytest.raises(vf.ObservationRefused):
            vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, bad)
    for name in ("", "campaign", "gate_v_v2_" + "AB" * 32, None, 5):
        with pytest.raises(vf.ObservationRefused):
            vf.ObservedRunTree(name, V5_VERSION, V5_DIGEST, (item,))
    with pytest.raises(vf.ObservationRefused):
        vf.ObservedRunTree(CID, V5_VERSION, "xyz", (item,))
    with pytest.raises(vf.ObservationRefused):
        vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(vf.ObservedItem(f"walk_forward/d{i}", vf.ObservedKind.DIRECTORY) for i in range(vf.MAX_ITEMS + 1)))


@pytest.mark.parametrize("hostile_tree, hostile_run", [(None, RUN), ("tree", RUN), (object(), RUN), (b"x", None), (None, None), (5, 5)])
def test_the_verifier_is_total_a_hostile_argument_gives_a_bad_input_report_never_an_exception(hostile_tree, hostile_run):
    report = vf.verify_run_chain(hostile_tree, hostile_run)
    assert codes(report) == {K.BAD_INPUT} and report.established is False and report.facts is None


def test_a_report_is_internally_consistent_facts_exist_only_when_there_is_no_defect():
    good, bad = verify(world()), verify(replaced(world(), **{COVERAGE.replace("/", "__"): b"x"}))
    assert good.facts is not None and bad.facts is None and bad.defects
    with pytest.raises(ValueError):
        vf.ChainVerification(RUN, (), None)
    with pytest.raises(ValueError):
        vf.ChainVerification(RUN, (vf.Defect(K.NO_SEAL, "x"),), good.facts)


# ══ Tranche 2 : la chaîne couverture → sessions → run → sceau ═════════════════════════════════════════════════════════════════════
def test_matrix_01_a_chain_with_several_sessions_and_a_recovery_seal_is_established():
    for sessions, recovery in ((3, False), (1, True), (2, True)):
        report = verify(world(sessions=sessions, recovery=recovery))
        assert report.established and report.facts.session_count == sessions and report.facts.finalized_by_recovery is recovery, (sessions, recovery)


def test_matrix_02_a_missing_coverage_is_no_coverage_and_nothing_else():
    files = world()
    del files[COVERAGE]
    assert codes(verify(files)) == {K.NO_COVERAGE}


def test_matrix_03_a_missing_session_file_is_session_missing_for_every_listed_session():
    files = world(sessions=2)
    del files[f"{BASE}/run_session_0002.json"]
    report = verify(files)
    assert codes(report) == {K.SESSION_MISSING} and [d.path for d in report.defects] == [f"{BASE}/run_session_0002.json"]
    nothing = world()
    del nothing[SESSION1]
    assert codes(verify(nothing)) == {K.SESSION_MISSING}


def test_matrix_04_a_duplicated_session_is_refused_by_file_number_and_by_the_seal():
    files = world()
    files[f"{BASE}/run_session_0002.json"] = files[SESSION1]                    # même enregistrement (indice 1) sous un autre numéro de fichier
    report = verify(files)
    assert K.SESSION_FILE_MISMATCH in codes(report) and K.SESSION_UNLISTED in codes(report)
    seal = json.loads(files[SEAL])
    seal["sessions"].append(dict(seal["sessions"][0]))
    sealed = replaced(world(), **{SEAL.replace("/", "__"): normative(seal)})
    assert codes(verify(sealed)) == {K.SEAL_INVALID} and verify(sealed).defects[0].l2_code == "SESSION_DUPLICATE"


def test_matrix_05_discontinuous_session_indices_are_a_gap_and_a_missing_listed_session():
    files = world(sessions=3)
    del files[f"{BASE}/run_session_0002.json"]
    report = verify(files)
    assert codes(report) == {K.SESSION_GAP, K.SESSION_MISSING}


def test_matrix_06_evidence_of_another_run_in_this_run_directory_is_not_attributable():
    other = world(OTHER_RUN)
    swapped = {path.replace(OTHER_RUN, RUN): data for path, data in other.items() if path.startswith("validations/")}
    files = {**{p: d for p, d in world().items() if not p.startswith("validations/")}, **swapped}
    files[RUN_FILE] = run_bytes(RUN)
    assert {K.COVERAGE_NOT_ATTRIBUTABLE, K.SEAL_NOT_ATTRIBUTABLE, K.SESSION_NOT_ATTRIBUTABLE} <= codes(verify(files))


def test_matrix_07_an_altered_coverage_is_invalid_when_malformed_and_altered_when_valid_but_different():
    files = world()
    assert codes(verify(replaced(files, **{COVERAGE.replace("/", "__"): b"{}"}))) == {K.COVERAGE_INVALID}
    record = json.loads(files[COVERAGE])
    record["runtime"]["python"] = "3.14.0"                                       # enregistrement VALIDE mais différent : le hash change
    altered = verify(replaced(files, **{COVERAGE.replace("/", "__"): normative(record)}))
    assert K.COVERAGE_ALTERED in codes(altered) and K.SESSION_NOT_ATTRIBUTABLE not in codes(altered)


def test_matrix_08_an_altered_session_is_session_altered():
    files = world(sessions=2)
    record = json.loads(files[f"{BASE}/run_session_0002.json"])
    record["resumed"] = not record["resumed"]
    assert codes(verify(replaced(files, **{f"{BASE}/run_session_0002.json".replace("/", "__"): normative(record)}))) == {K.SESSION_ALTERED}


def test_matrix_09_an_altered_seal_is_detected_through_each_field_it_pins():
    files = world()
    seal = json.loads(files[SEAL])
    by_run = dict(seal, run_record_sha256="ab" * 32)
    by_coverage = dict(seal, coverage_sha256="cd" * 32)
    assert K.RUN_ALTERED in codes(verify(replaced(files, **{SEAL.replace("/", "__"): normative(by_run)})))
    assert K.COVERAGE_ALTERED in codes(verify(replaced(files, **{SEAL.replace("/", "__"): normative(by_coverage)})))
    by_after = dict(seal, frame_sha256_after="ef" * 32)
    assert K.FRAME_AFTER_MISMATCH in codes(verify(replaced(files, **{SEAL.replace("/", "__"): normative(by_after)})))


def test_matrix_10_an_altered_validation_run_is_run_altered_and_a_run_of_another_identity_is_not_attributable():
    files = world()
    assert codes(verify(replaced(files, **{RUN_FILE.replace("/", "__"): run_bytes(extra={"strategy_name": "altered"})}))) == {K.RUN_ALTERED}
    assert K.RUN_NOT_ATTRIBUTABLE in codes(verify(replaced(files, **{RUN_FILE.replace("/", "__"): run_bytes(OTHER_RUN)})))
    assert K.RUN_NOT_ATTRIBUTABLE in codes(verify(replaced(files, **{RUN_FILE.replace("/", "__"): run_bytes(RUN, "monte_carlo")})))
    assert K.RUN_NOT_ATTRIBUTABLE in codes(verify(replaced(files, **{RUN_FILE.replace("/", "__"): b"[1, 2]"})))
    assert K.RUN_NOT_ATTRIBUTABLE in codes(verify(replaced(files, **{RUN_FILE.replace("/", "__"): b'{"validation_run_id": "x", "validation_run_id": "y"}'})))
    del files[RUN_FILE]
    assert codes(verify(files)) == {K.NO_VALIDATION_RUN}


def test_matrix_11_a_seal_of_another_run_is_not_attributable():
    files = world()
    files[SEAL] = world(OTHER_RUN)[f"validations/{OTHER_RUN}/run_seal.json"]
    assert K.SEAL_NOT_ATTRIBUTABLE in codes(verify(files))


def test_matrix_12_a_wrong_version_is_refused_for_each_of_the_three_evidence_files():
    files = world()
    for relative, key, wrong, expected in ((COVERAGE, "coverage_semantics_version", "gate_v_run_data_coverage_v2", K.COVERAGE_INVALID),
                                           (SESSION1, "session_semantics_version", "gate_v_run_session_v2", K.SESSION_INVALID),
                                           (SEAL, "seal_semantics_version", "gate_v_run_seal_v2", K.SEAL_INVALID)):
        record = json.loads(files[relative])
        record[key] = wrong
        report = verify(replaced(files, **{relative.replace("/", "__"): normative(record)}))
        assert expected in codes(report) and any(d.l2_code == "BAD_VERSION" for d in report.defects), relative


def test_matrix_25_a_run_that_cites_the_seal_hash_is_a_reference_cycle_even_when_it_is_also_altered():
    files = world()
    seal_hash = sha(files[SEAL])
    cited = run_bytes(extra={"note": seal_hash})
    report = verify(replaced(files, **{RUN_FILE.replace("/", "__"): cited}))
    assert {K.REFERENCE_CYCLE, K.RUN_ALTERED} <= codes(report)


def test_the_l2_cross_check_is_the_final_safety_net_and_its_refusals_are_mapped_not_swallowed(monkeypatch):
    files = world()                                                     # construit AVANT le remplacement : le constructeur de L2 appelle lui-même verify_run_evidence
    def refuse(*args, **kwargs):
        raise ev.EvidenceRefused(ev.EvidenceRefusal.HASH_ROLE_COLLISION, "forcé")
    monkeypatch.setattr(vf.ev, "verify_run_evidence", refuse)
    report = verify(files)
    assert codes(report) == {K.HASH_ROLE_COLLISION} and report.established is False
    monkeypatch.setattr(vf.ev, "verify_run_evidence", lambda *a, **k: (_ for _ in ()).throw(ev.EvidenceRefused(ev.EvidenceRefusal.MACHINE_ORDER, "x")))
    mapped = verify(files)
    assert codes(mapped) == {K.CHAIN_REFUSED} and mapped.defects[0].l2_code == "MACHINE_ORDER"
    monkeypatch.setattr(vf.ev, "verify_run_evidence", lambda *a, **k: (_ for _ in ()).throw(ev.EvidenceRefused(ev.EvidenceRefusal.CIRCULAR_REFERENCE, "x")))
    assert codes(verify(files)) == {K.REFERENCE_CYCLE}


# ══ Tranche 3 : exhaustivité des sorties Walk-Forward face au sceau ═════════════════════════════════════════════════════════════
def test_matrix_13_a_modified_output_is_output_altered_and_names_the_path():
    files = world()
    changed = "walk_forward/folds/fold_000/oos_trades.csv"
    report = verify(replaced(files, **{changed.replace("/", "__"): files[changed] + b"x"}))
    assert codes(report) == {K.OUTPUT_ALTERED} and [d.path for d in report.defects] == [changed]


def test_matrix_14_a_sealed_output_that_was_not_observed_is_output_missing():
    files = world()
    gone = "walk_forward/aggregate.json"
    del files[gone]
    report = verify(files)
    assert codes(report) == {K.OUTPUT_MISSING} and [d.path for d in report.defects] == [gone]


def test_matrix_15_an_observed_output_absent_from_the_seal_is_output_unsealed():
    files = world()
    files["walk_forward/folds/fold_002/definition.json"] = b"surprise"
    report = verify(files)
    assert codes(report) == {K.OUTPUT_UNSEALED} and [d.path for d in report.defects] == ["walk_forward/folds/fold_002/definition.json"]


def test_matrix_16_a_modified_checkpoint_is_detected_like_any_output():
    files = world()
    checkpoint = "walk_forward/.gate_v_checkpoints_v1/folds/fold_001.json"
    report = verify(replaced(files, **{checkpoint.replace("/", "__"): b"tampered"}))
    assert codes(report) == {K.OUTPUT_ALTERED} and [d.path for d in report.defects] == [checkpoint]


def test_matrix_17_a_contradictory_size_is_output_altered_even_when_the_hash_matches():
    files = world()
    target = "walk_forward/state.json"
    items = [i for i in items_of(files) if i.path != target]
    items.append(vf.ObservedItem(target, vf.ObservedKind.FILE, size=len(files[target]) + 1, sha256=sha(files[target]), content=None))
    report = vf.verify_run_chain(vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(sorted(items, key=lambda i: i.path))), RUN)
    assert codes(report) == {K.OUTPUT_ALTERED} and "taille" in report.defects[0].detail


def test_matrix_18_the_right_hash_at_the_wrong_path_is_both_missing_and_unsealed():
    files = world()
    moved = "walk_forward/folds/fold_000/oos_trades.csv"
    files["walk_forward/folds/fold_009/oos_trades.csv"] = files.pop(moved)
    report = verify(files)
    assert codes(report) == {K.OUTPUT_MISSING, K.OUTPUT_UNSEALED}


def test_matrix_19_a_publication_orphan_is_never_an_output_and_blocks_the_proof():
    orphan = vf.ObservedItem("walk_forward/aggregate.json." + "a" * 32 + ".tmp", vf.ObservedKind.ORPHAN)
    report = verify(world(), [orphan])
    assert codes(report) == {K.OUTPUT_ORPHAN}
    in_run = vf.ObservedItem(f"{BASE}/validation_run.json." + "b" * 32 + ".tmp", vf.ObservedKind.ORPHAN)
    assert codes(verify(world(), [in_run])) == {K.RUN_FILE_ORPHAN}
    outside = vf.ObservedItem("exposure/.exposure.tmp." + "c" * 32, vf.ObservedKind.ORPHAN)
    assert verify(world(), [outside]).established                               # un orphelin de A0 hors périmètre reste non bloquant (comportement de B3 v3)


def test_matrix_20_a_scan_anomaly_is_never_an_accepted_output():
    for anomaly in ("KIND_MISMATCH", "TOO_LARGE", "UNREADABLE", "LINK_OR_REPARSE_POINT"):
        item = vf.ObservedItem("walk_forward/folds/fold_000/oos_trades.csv", vf.ObservedKind.ANOMALY, anomaly=anomaly)
        files = world()
        files.pop("walk_forward/folds/fold_000/oos_trades.csv")
        report = verify(files, [item])
        assert K.OUTPUT_ANOMALY in codes(report) and K.OUTPUT_MISSING in codes(report), anomaly


def test_matrix_21_an_empty_output_directory_is_refused_because_nothing_can_seal_it():
    report = verify(world(), [vf.ObservedItem("walk_forward/folds/fold_005", vf.ObservedKind.DIRECTORY)])
    assert codes(report) == {K.EMPTY_OUTPUT_DIRECTORY} and report.defects[0].path == "walk_forward/folds/fold_005"
    only_dirs = verify({p: d for p, d in world().items() if p.startswith("validations/")}, [vf.ObservedItem("walk_forward", vf.ObservedKind.DIRECTORY)])
    assert K.EMPTY_OUTPUT_DIRECTORY in codes(only_dirs)


def test_matrix_22_a_tree_that_looks_complete_but_cannot_be_verified_is_not_established():
    files = world()
    stripped = [vf.ObservedItem(i.path, i.kind, size=i.size, sha256=i.sha256, content=None) if i.path == COVERAGE else i for i in items_of(files)]
    tree = vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(sorted(stripped, key=lambda i: i.path)))
    assert codes(vf.verify_run_chain(tree, RUN)) == {K.COVERAGE_INVALID}          # octets non fournis : le hash seul ne suffit pas à attribuer la preuve
    assert codes(verify(files, version="gate_v_exposure_interpreters_v4")) == {K.WRONG_TABLE}
    assert codes(verify(files, digest="9c05f8b068ac86d321c0d9889df0f3c0f1e015fdd8b17d208479554b1badb43b")) == {K.WRONG_TABLE}


def test_a_recovery_seal_with_no_outputs_and_no_observed_outputs_is_consistent_and_says_so():
    report = verify(world(outputs={}, recovery=True))
    assert report.established and report.facts.output_count == 0 and report.facts.finalized_by_recovery is True


# ══ Tranche 4 : arbre entier, runs mélangés, autre campagne, entrées inconnues, crashs ═══════════════════════════════════════════════
def test_matrix_23_two_walk_forward_runs_in_one_campaign_are_mixed_runs():
    assert verify(world()).established
    other_run = "gate_v_v2_" + "ab" * 32 + "_walk_forward"
    mixed = {**world(), **{p: d for p, d in world(other_run).items() if p.startswith("validations/")}}
    report = verify(mixed)
    assert K.MIXED_RUNS in codes(report) and report.facts is None


def test_matrix_24_a_run_of_another_campaign_is_refused_before_anything_else():
    report = verify(world(OTHER_RUN), run_id=OTHER_RUN)                          # dossier de campagne CID, run d'une AUTRE campagne
    assert codes(report) == {K.FOREIGN_CAMPAIGN}
    assert codes(verify(world(), run_id="not-a-run-id")) == {K.BAD_INPUT}
    assert codes(verify(world(), run_id=f"{CID}_monte_carlo")) == {K.BAD_INPUT}


def test_matrix_26_a_forged_observation_cannot_be_built_and_a_consistent_forgery_is_flagged_as_needing_a_rescan():
    with pytest.raises(vf.ObservationRefused):
        vf.ObservedItem(COVERAGE, vf.ObservedKind.FILE, size=3, sha256=sha(b"xyz"), content=b"abc")              # octets ≠ hash annoncé
    files = world()
    forged = [vf.ObservedItem("walk_forward/state.json", vf.ObservedKind.FILE, size=len(files["walk_forward/state.json"]), sha256=sha(files["walk_forward/state.json"]))
              if i.path == "walk_forward/state.json" else i for i in items_of(files)]
    report = vf.verify_run_chain(vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(sorted(forged, key=lambda i: i.path))), RUN)
    assert report.established and report.requires_independent_rescan is True and "ABSENCE_OF_EXPOSURE" in report.not_proven       # limite documentée


def test_matrix_27_a_seal_with_unsorted_sessions_or_outputs_is_invalid():
    files = world(sessions=2)
    seal = json.loads(files[SEAL])
    seal["sessions"].reverse()
    unsorted_sessions = verify(replaced(files, **{SEAL.replace("/", "__"): normative(seal)}))
    assert codes(unsorted_sessions) == {K.SEAL_INVALID} and unsorted_sessions.defects[0].l2_code in {"SESSION_GAP", "SEAL_ORDER"}
    seal = json.loads(world()[SEAL])
    seal["output_artifacts"].reverse()
    unsorted_outputs = verify(replaced(world(), **{SEAL.replace("/", "__"): normative(seal)}))
    assert codes(unsorted_outputs) == {K.SEAL_INVALID} and unsorted_outputs.defects[0].l2_code == "OUTPUT_ORDER"


CRASH_POINTS = {
    "after-T1-coverage-only": lambda f: {COVERAGE: f[COVERAGE]},
    "after-T2-coverage-and-session": lambda f: {COVERAGE: f[COVERAGE], SESSION1: f[SESSION1]},
    "mid-outputs": lambda f: {COVERAGE: f[COVERAGE], SESSION1: f[SESSION1], **{p: d for p, d in f.items() if p.startswith("walk_forward/") and "fold_001" not in p}},
    "after-T3-run-without-seal": lambda f: {p: d for p, d in f.items() if p != SEAL},
    "seal-without-run": lambda f: {p: d for p, d in f.items() if p != RUN_FILE},
}


@pytest.mark.parametrize("point", sorted(CRASH_POINTS))
def test_matrix_28_every_simulated_crash_point_leaves_a_chain_that_is_not_established(point):
    partial = CRASH_POINTS[point](world())
    report = vf.verify_run_chain(tree_of(partial), RUN)
    assert report.established is False and report.facts is None and report.defects
    expected = {"after-T1-coverage-only": {K.NO_VALIDATION_RUN, K.NO_SEAL, K.SESSION_MISSING}, "after-T2-coverage-and-session": {K.NO_VALIDATION_RUN, K.NO_SEAL},
                "mid-outputs": {K.NO_VALIDATION_RUN, K.NO_SEAL}, "after-T3-run-without-seal": {K.NO_SEAL}, "seal-without-run": {K.NO_VALIDATION_RUN}}[point]
    assert expected <= codes(report), (point, codes(report))


def test_matrix_29_an_unknown_entry_a_hostile_type_or_a_stranger_file_is_never_innocent():
    unknown_in_run = vf.ObservedItem(f"{BASE}/notes.txt", vf.ObservedKind.UNKNOWN, anomaly="UNKNOWN_FILE")
    assert codes(verify(world(), [unknown_in_run])) == {K.UNKNOWN_RUN_FILE}
    unknown_in_outputs = vf.ObservedItem("walk_forward/folds/fold_000/train_progress.csv", vf.ObservedKind.UNKNOWN, anomaly="UNKNOWN_FILE")
    assert codes(verify(world(), [unknown_in_outputs])) == {K.UNKNOWN_RUN_FILE}
    unknown_elsewhere = vf.ObservedItem("random.bin", vf.ObservedKind.UNKNOWN, anomaly="UNKNOWN_FILE")
    assert codes(verify(world(), [unknown_elsewhere])) == {K.UNKNOWN_ENTRY_IN_TREE}
    anomaly_elsewhere = vf.ObservedItem("plan.json", vf.ObservedKind.ANOMALY, anomaly="INVALID_JSON")
    assert codes(verify(world(), [anomaly_elsewhere])) == {K.ENTRY_ANOMALY}
    anomaly_in_run = vf.ObservedItem(f"{BASE}/run_seal.json", vf.ObservedKind.ANOMALY, anomaly="INVALID_JSON")
    seal_removed = {p: d for p, d in world().items() if p != SEAL}
    assert {K.RUN_FILE_ANOMALY, K.NO_SEAL} <= codes(verify(seal_removed, [anomaly_in_run]))


def test_matrix_30_data_not_covered_by_the_proof_is_refused_wherever_it_hides():
    files = world()
    files[f"{BASE}/notes.txt"] = b"extra"                                        # fichier FILE de nom inconnu dans le dossier du run
    assert codes(verify(files)) == {K.UNKNOWN_RUN_FILE}
    seal = json.loads(world()[SEAL])
    seal["extra"] = 1
    assert codes(verify(replaced(world(), **{SEAL.replace("/", "__"): normative(seal)}))) == {K.SEAL_INVALID}
    files = world()
    files[f"{BASE}/run_session_0001.json.bak"] = b"x"
    assert K.UNKNOWN_RUN_FILE in codes(verify(files))
    sub = vf.ObservedItem(f"{BASE}/sub", vf.ObservedKind.DIRECTORY)
    assert K.UNKNOWN_RUN_FILE in codes(verify(world(), [sub]))


def test_defects_are_deterministically_ordered_and_the_verdict_does_not_depend_on_item_order():
    files = world()
    files["walk_forward/extra.json"] = b"e"
    del files["walk_forward/state.json"]
    first = vf.verify_run_chain(tree_of(files), RUN)
    items = list(tree_of(files).items)
    reversed_tree = vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(reversed(items)))
    assert vf.verify_run_chain(reversed_tree, RUN) == first
    assert [d.code.value for d in first.defects] == sorted(d.code.value for d in first.defects)


def test_an_inert_item_carries_no_fingerprint_and_is_refused_inside_the_chain_scope_only():
    inert = lambda path, **kw: vf.ObservedItem(path, vf.ObservedKind.INERT, **kw)  # noqa: E731
    for bad in ({"size": 1}, {"sha256": "a" * 64}, {"content": b"x"}, {"anomaly": "UNREADABLE"}):
        with pytest.raises(vf.ObservationRefused) as caught:
            inert("walk_forward/x.txt", **bad)
        assert caught.value.code is vf.ObservationRefusal.INCONSISTENT
    assert codes(verify(world(), [inert("walk_forward/x.txt")])) == {K.OUTPUT_ANOMALY}
    assert codes(verify(world(), [inert(f"{BASE}/x.txt")])) == {K.RUN_FILE_ANOMALY}
    assert verify(world(), [inert("datasets/d1/research_run.json")]).established is True      # hors périmètre : présent, sans effet sur la chaîne


# ── Survivants de la campagne de mutation (invariants ajoutés) ────────────────────────────────────────────────────────────────────
def _session_with(**changes):
    coverage, sessions, seal, outputs, run_data = models()
    return dataclass_replace_session(sessions[0], **changes), coverage


def dataclass_replace_session(session, **changes):
    import dataclasses
    return dataclasses.replace(session, **changes)


def test_a_session_that_differs_from_the_coverage_by_the_frame_alone_or_the_row_count_alone_is_refused_with_the_precise_code():
    for change in ({"frame_sha256_before": "ab" * 32}, {"frame_row_count": 99}):
        session, coverage = _session_with(**change)
        files = world()
        files[SESSION1] = session.to_bytes()
        codes_found = codes(verify(files))
        assert K.SESSION_FRAME_MISMATCH in codes_found and K.SESSION_ALTERED in codes_found, change


def test_a_run_record_citing_the_coverage_or_a_session_hash_is_a_dag_edge_of_l2_not_a_cycle_while_citing_the_seal_is_one():
    coverage, sessions, seal, outputs, _ = models()
    for cited in (sha(coverage.to_bytes()), sha(sessions[0].to_bytes())):
        assert verify(world(run_data=run_bytes(extra={"note": cited}))).established is True, cited       # run → couverture / session : arête sans cycle (graphe de L2)
    cyclic = verify(replaced(world(), **{RUN_FILE.replace("/", "__"): run_bytes(extra={"note": sha(seal.to_bytes())})}))
    assert K.REFERENCE_CYCLE in codes(cyclic) and cyclic.established is False                   # run → sceau → run : cycle


def test_exactly_max_items_entries_are_accepted_and_one_more_is_refused():
    filler = [vf.ObservedItem(f"d/{i}", vf.ObservedKind.DIRECTORY) for i in range(vf.MAX_ITEMS)]
    assert len(vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(filler)).items) == vf.MAX_ITEMS
    with pytest.raises(vf.ObservationRefused):
        vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple([*filler, vf.ObservedItem("d/extra", vf.ObservedKind.DIRECTORY)]))


# ── Défauts démontrés par la relecture indépendante ────────────────────────────────────────────────────────────────────────────────
def test_a_session_of_another_coverage_gets_the_precise_session_coverage_mismatch_code():
    other_coverage = ev.RunDataCoverage.from_s0_facts(RUN, fd.compute_s0_frame_facts(CSV.encode(), 180), {**RUNTIME, "python": "3.13.8"})
    foreign = ev.RunSession.open_for(other_coverage, 1, other_coverage.frame_sha256, other_coverage.row_count, False)
    files = world()
    files[SESSION1] = foreign.to_bytes()
    assert K.SESSION_COVERAGE_MISMATCH in codes(verify(files))


def test_path_length_depth_and_total_retained_bytes_are_bounded():
    for bad in ("a/" * 600 + "f", "a/" * 40 + "f"):                          # > 1024 caractères / > 32 segments, segments courts
        with pytest.raises(vf.ObservationRefused) as caught:
            vf.ObservedItem(bad, vf.ObservedKind.DIRECTORY)
        assert caught.value.code is vf.ObservationRefusal.BAD_PATH
    with pytest.raises(vf.ObservationRefused) as caught:                          # 11 segments de 100 caractères : 1 100 caractères, profondeur correcte
        vf.ObservedItem("/".join(["s" * 100] * 11), vf.ObservedKind.DIRECTORY)
    assert caught.value.code is vf.ObservationRefusal.BAD_PATH
    vf.ObservedItem("/".join(["s" * 100] * 10), vf.ObservedKind.DIRECTORY)    # 1 009 caractères : accepté
    vf.ObservedItem("a/" * 31 + "f", vf.ObservedKind.DIRECTORY)               # 32 segments : accepté
    big = b"\0" * vf.MAX_CONTENT_BYTES
    items = tuple(vf.ObservedItem(f"validations/x{i}/f", vf.ObservedKind.FILE, size=len(big), sha256=sha(big), content=big) for i in range(17))
    with pytest.raises(vf.ObservationRefused) as caught:
        vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, items)               # 68 Mio retenus > 64 Mio
    assert caught.value.code is vf.ObservationRefusal.BAD_TREE


def test_verification_time_does_not_grow_with_sessions_times_run_size():
    import time
    files = world(sessions=300, run_data=run_bytes(extra={"pad": "x" * 2_000_000}))
    started = time.perf_counter()
    assert verify(files).established is True
    assert time.perf_counter() - started < 5.0


def test_a_hash_cited_in_uppercase_or_inside_a_longer_hex_run_still_counts_as_a_citation():
    seal_hash = sha(models()[2].to_bytes())
    for cited in (seal_hash.upper(), "0" + seal_hash, seal_hash + "f"):
        cyclic = verify(replaced(world(), **{RUN_FILE.replace("/", "__"): run_bytes(extra={"note": cited})}))
        assert K.REFERENCE_CYCLE in codes(cyclic), cited[:12]
    long_run = verify(replaced(world(), **{RUN_FILE.replace("/", "__"): run_bytes(extra={"note": "a" * 400})}))
    assert long_run.established is False and K.RUN_NOT_ATTRIBUTABLE in codes(long_run)
