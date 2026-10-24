"""K1 Étape 2, lot L2 : tests des modèles purs `RunDataCoverage`, `RunSession`, `RunSeal` (contrat R9 section 5, PROPOSED).

Ces modèles ne portent QUE des faits et des références de hash fournis par l'appelant. Ils n'observent aucune lecture réelle, ne
prouvent aucune chronologie, n'émettent aucun verdict (FRESH, NO_OVERLAP, admission, Claim) et ne produisent aucun objet d'autorisation.

Valeurs attendues jamais calculées par le module testé : (a) littéraux de la chaîne de vecteurs R9 (`docs/adr/0025-proposal-E3E-Q2-
STAGE2-VECTORS.json`, recalculée par un programme indépendant) recopiés ci-dessous ; (b) un oracle écrit dans ce fichier (sérialisation
normative et SHA-256 recalculés avec json/hashlib, sans importer le module testé).
"""
import copy
import hashlib
import json
import pickle
from pathlib import Path

import pytest

import gate_v_frame_digest as fd
import gate_v_run_evidence_models as ev

ROOT = Path(__file__).resolve().parent.parent

# Littéraux R9 (chaîne WF) : CSV synthétique V1, identité de run, enregistrements et hashs attendus.
VECTOR = json.loads(r'''{
  "csv_v1": "time,open,high,low,close,tick_volume,spread\n2025-12-31 23:51:00,100.10,100.30,100.00,100.20,7,180\n2025-12-31 23:54:00,100.20,100.40,100.10,100.30,9,180\n2025-12-31 23:57:00,100.30,100.50,100.20,100.40,11,180\n",
  "wf_id": "gate_v_v2_abababababababababababababababababababababababababababababababab_walk_forward",
  "mc_id": "gate_v_v2_abababababababababababababababababababababababababababababababab_monte_carlo",
  "frame_sha256_v1": "cf582fa6884fc5ab0bfae6bd62b126c1ee669ca5ed74d110ce76ca4c475185c7",
  "frame_sha256_v2": "974c02e2a8c17ff3aaebad024481e7d35bb364bb481a47bad3c936df38381f4a",
  "frame_sha256_v3": "3ea4ae8ea57b37dc9f74ce0c8ea3b2c2daa4b092c1effbeabc523a3095a0bb0d",
  "s0_frame_facts_sha256": "cdcdcde70f0316be82734b9d35027ddbb87f21e05ce9c53f58ae7c22de7cb6c3",
  "run_record_sha256": "9a257ab355585ff89e2a847c01f8fbb78beba4594846f9bccf5863d720bfcac4",
  "coverage_sha256": "5e8a1baad41741aec523377a4a366e3849f494a0e7a640f074b12e20c9bae10e",
  "session_sha256": "dc011a2adb4caab376fa3212d7a487e78be42b2775f92e6364bf647f33f88cad",
  "seal_sha256": "570a679591c5578cdaef24cba3ecff36aa111c97e4931ca77909b405361beea5",
  "coverage_record": {
    "binding_kind": "MARKET_DATA_FRAME",
    "coverage_semantics_version": "gate_v_run_data_coverage_v1",
    "dataset_snapshot_id": "local_csv:sha256:8d43f5576f03a0f39ab24409ae9d12152a8a49ab9d48e4af3f1e2e83b8d7dea6",
    "frame": {
      "bar_duration_seconds": 180,
      "columns": [
        {"kind": "time_us", "name": "time"}, {"kind": "f64", "name": "open"}, {"kind": "f64", "name": "high"}, {"kind": "f64", "name": "low"},
        {"kind": "f64", "name": "close"}, {"kind": "i64", "name": "tick_volume"}, {"kind": "i64", "name": "spread"}
      ],
      "first_open_utc": "2025-12-31T23:51:00.000000Z",
      "frame_digest_version": "gate_v_frame_digest_v1",
      "frame_sha256": "cf582fa6884fc5ab0bfae6bd62b126c1ee669ca5ed74d110ce76ca4c475185c7",
      "last_close_utc_exclusive": "2026-01-01T00:00:00.000000Z",
      "last_open_utc": "2025-12-31T23:57:00.000000Z",
      "row_count": 3,
      "time_semantics": "naive_utc_declared"
    },
    "loader_id": "gate_v_s0_frame_loader_v1",
    "runtime": {"numpy": "2.2.6", "pandas": "3.0.3", "python": "3.13.7"},
    "source_sha256": "8d43f5576f03a0f39ab24409ae9d12152a8a49ab9d48e4af3f1e2e83b8d7dea6",
    "source_size_bytes": 207,
    "validation_run_id": "gate_v_v2_abababababababababababababababababababababababababababababababab_walk_forward"
  },
  "session_record": {
    "coverage_sha256": "5e8a1baad41741aec523377a4a366e3849f494a0e7a640f074b12e20c9bae10e",
    "frame_row_count": 3,
    "frame_sha256_before": "cf582fa6884fc5ab0bfae6bd62b126c1ee669ca5ed74d110ce76ca4c475185c7",
    "resumed": false,
    "session_index": 1,
    "session_semantics_version": "gate_v_run_session_v1",
    "validation_run_id": "gate_v_v2_abababababababababababababababababababababababababababababababab_walk_forward"
  },
  "seal_record": {
    "coverage_sha256": "5e8a1baad41741aec523377a4a366e3849f494a0e7a640f074b12e20c9bae10e",
    "finalized_by_recovery": false,
    "frame_sha256_after": "cf582fa6884fc5ab0bfae6bd62b126c1ee669ca5ed74d110ce76ca4c475185c7",
    "output_artifacts": [
      {"path": "walk_forward/folds/fold_000/oos_trades.csv", "sha256": "07c1e3c274ab091f88632afa41648704843b8d67265bebe78e8d5f5bc12e5fe4", "size": 55},
      {"path": "walk_forward/manifest.json", "sha256": "41cba73e77218b0a6ec1a55fa7a2c8823cfdde92ca33dfd3af54f49517a7352d", "size": 8}
    ],
    "run_record_sha256": "9a257ab355585ff89e2a847c01f8fbb78beba4594846f9bccf5863d720bfcac4",
    "seal_semantics_version": "gate_v_run_seal_v1",
    "sessions": [{"session_index": 1, "session_sha256": "dc011a2adb4caab376fa3212d7a487e78be42b2775f92e6364bf647f33f88cad"}],
    "validation_run_id": "gate_v_v2_abababababababababababababababababababababababababababababababab_walk_forward",
    "validation_type": "walk_forward"
  },
  "mc_seal_record": {
    "coverage_sha256": "23392b149496eccf6e2013d1eed4cdb4db6d9c79f4636f3921913ddeede680dd",
    "finalized_by_recovery": false,
    "frame_sha256_after": null,
    "output_artifacts": [],
    "run_record_sha256": "5ece0da0b2081c7ca521108601e7329b18bb3baf61000500a196d551c47d1669",
    "seal_semantics_version": "gate_v_run_seal_v1",
    "sessions": [],
    "validation_run_id": "gate_v_v2_abababababababababababababababababababababababababababababababab_monte_carlo",
    "validation_type": "monte_carlo"
  },
  "mc_seal_sha256": "397d0349dbb2c304ba190e2723bb77f6001c2ae6928ee0fb57274e343aee5514"
}''')
WF = VECTOR["wf_id"]
CSV_V1 = VECTOR["csv_v1"]
RUNTIME = VECTOR["coverage_record"]["runtime"]
H = "ab" * 32


# ── Oracle indépendant ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def oracle_bytes(record):
    """Octets normatifs (ADR 0025 23.29.4) : clés triées, indent=2, LF final, UTF-8, sans NaN."""
    return (json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def oracle_sha(record):
    return hashlib.sha256(oracle_bytes(record)).hexdigest()


def coverage_record():
    return copy.deepcopy(VECTOR["coverage_record"])


def refused(code, fn, *args, **kwargs):
    with pytest.raises(ev.EvidenceRefused) as info:
        fn(*args, **kwargs)
    assert info.value.code is code, (info.value.code, str(info.value))


R = ev.EvidenceRefusal


# ══ Tranche 1 : RunDataCoverage ═══════════════════════════════════════════════════════════════════════════════════════════════
def test_the_oracle_agrees_with_the_independent_r9_chain_literals():
    assert oracle_sha(VECTOR["coverage_record"]) == VECTOR["coverage_sha256"]
    assert oracle_sha(VECTOR["session_record"]) == VECTOR["session_sha256"]
    assert oracle_sha(VECTOR["seal_record"]) == VECTOR["seal_sha256"]
    assert oracle_sha(VECTOR["mc_seal_record"]) == VECTOR["mc_seal_sha256"]


def test_coverage_from_the_r9_record_reproduces_the_independent_hash_and_bytes():
    cov = ev.RunDataCoverage.from_record(VECTOR["coverage_record"])
    assert cov.to_record() == VECTOR["coverage_record"]
    assert cov.to_bytes() == oracle_bytes(VECTOR["coverage_record"])
    assert cov.sha256 == VECTOR["coverage_sha256"]
    assert ev.RunDataCoverage.from_bytes(cov.to_bytes()) == cov


def test_coverage_built_from_the_l1_s0_facts_equals_the_r9_vector():
    s0 = fd.compute_s0_frame_facts(CSV_V1.encode(), 180)
    cov = ev.RunDataCoverage.from_s0_facts(WF, s0, RUNTIME)
    assert cov.to_record() == VECTOR["coverage_record"] and cov.sha256 == VECTOR["coverage_sha256"]


def test_the_frame_digest_comes_from_l1_and_is_not_recomputed_here():
    s0 = fd.compute_s0_frame_facts(CSV_V1.encode(), 180)
    cov = ev.RunDataCoverage.from_s0_facts(WF, s0, RUNTIME)
    assert cov.frame_sha256 == s0.frame.frame_sha256 == VECTOR["frame_sha256_v1"]
    assert (cov.first_open_utc, cov.last_open_utc, cov.last_close_utc_exclusive) == (s0.frame.first_open_utc, s0.frame.last_open_utc, s0.frame.last_close_utc_exclusive)
    assert (cov.bar_duration_seconds, cov.row_count, cov.source_size_bytes) == (180, 3, 207)


def test_the_normative_bytes_equal_the_e3c_serializer():
    import atomic_json_store as store
    for record in (VECTOR["coverage_record"], VECTOR["session_record"], VECTOR["seal_record"], {"é": ["a", None, True, 0, -3]}):
        assert ev.normative_json_bytes(record) == store.serialize_normative_json(record)


def test_coverage_has_exactly_nine_keys_and_its_frame_exactly_nine():
    record = VECTOR["coverage_record"]
    assert set(record) == {"coverage_semantics_version", "binding_kind", "validation_run_id", "dataset_snapshot_id", "source_sha256", "source_size_bytes",
                           "loader_id", "frame", "runtime"} and len(record["frame"]) == 9


def _mutated(path, value):
    record = coverage_record()
    target = record
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return record


@pytest.mark.parametrize("path,value,code", [
    (("coverage_semantics_version",), "gate_v_run_data_coverage_v2", R.BAD_VERSION),
    (("binding_kind",), "SOMETHING", R.BAD_VALUE),
    (("binding_kind",), "DERIVED", R.UNSUPPORTED_BINDING_KIND),
    (("loader_id",), "custom_loader", R.BAD_VALUE),
    (("validation_run_id",), "gate_v_v2_" + "ab" * 32 + "_monte_carlo", R.BAD_RUN_ID),
    (("validation_run_id",), "run_1", R.BAD_RUN_ID),
    (("validation_run_id",), "gate_v_v2_" + "AB" * 32 + "_walk_forward", R.BAD_RUN_ID),
    (("validation_run_id",), 7, R.BAD_TYPE),
    (("source_sha256",), "AB" * 32, R.BAD_HEX),
    (("source_sha256",), "ab" * 31, R.BAD_HEX),
    (("dataset_snapshot_id",), "local_csv:sha256:" + "00" * 32, R.SNAPSHOT_MISMATCH),
    (("source_size_bytes",), True, R.BAD_TYPE),
    (("source_size_bytes",), 207.0, R.FLOAT_FORBIDDEN),
    (("source_size_bytes",), "207", R.BAD_TYPE),
    (("source_size_bytes",), -1, R.BAD_VALUE),
    (("source_size_bytes",), 0, R.BAD_VALUE),
    (("source_size_bytes",), 2**63, R.BAD_VALUE),
    (("frame", "frame_digest_version"), "gate_v_frame_digest_v2", R.BAD_VERSION),
    (("frame", "frame_sha256"), "xyz", R.BAD_HEX),
    (("frame", "row_count"), True, R.BAD_TYPE),
    (("frame", "row_count"), 0, R.BAD_VALUE),
    (("frame", "row_count"), 1, R.BAD_FRAME),
    (("frame", "row_count"), 3000000000000, R.BAD_FRAME),
    (("frame", "bar_duration_seconds"), True, R.BAD_TYPE),
    (("frame", "bar_duration_seconds"), 0, R.BAD_VALUE),
    (("frame", "bar_duration_seconds"), 60, R.BAD_FRAME),
    (("frame", "time_semantics"), "utc", R.BAD_VALUE),
    (("frame", "first_open_utc"), "2025-12-31T23:51:00Z", R.BAD_INSTANT),
    (("frame", "first_open_utc"), "2025-12-31T23:51:00.000000+00:00", R.BAD_INSTANT),
    (("frame", "first_open_utc"), "2025-12-31 23:51:00.000000Z", R.BAD_INSTANT),
    (("frame", "first_open_utc"), "2025-13-31T23:51:00.000000Z", R.BAD_INSTANT),
    (("frame", "first_open_utc"), "2025-12-31T24:00:00.000000Z", R.BAD_INSTANT),
    (("frame", "first_open_utc"), "0000-12-31T23:51:00.000000Z", R.BAD_INSTANT),
    (("frame", "first_open_utc"), "２０２５-12-31T23:51:00.000000Z", R.BAD_INSTANT),
    (("frame", "first_open_utc"), 20251231, R.BAD_TYPE),
    (("frame", "first_open_utc"), "2026-01-01T00:00:00.000000Z", R.BAD_FRAME),            # première ouverture >= dernière
    (("frame", "last_close_utc_exclusive"), "2026-01-01T00:03:00.000000Z", R.BAD_FRAME),   # clôture ≠ dernière ouverture + durée
    (("frame", "last_open_utc"), "2025-12-31T23:57:30.000000Z", R.BAD_FRAME),              # écart non multiple de la durée
    (("frame", "columns"), [], R.BAD_FRAME),
    (("frame", "columns"), "time", R.BAD_TYPE),
    (("frame", "columns"), [["time", "time_us"]], R.BAD_TYPE),
    (("frame", "last_open_utc"), KeyError, R.MISSING_FIELD),
    (("loader_id",), KeyError, R.MISSING_FIELD),
    (("runtime",), KeyError, R.MISSING_FIELD),
    (("runtime", "numpy"), KeyError, R.MISSING_FIELD),
    (("runtime", "pandas"), "", R.BAD_VALUE),
    (("runtime", "pandas"), 3, R.BAD_TYPE),
    (("runtime", "gpu"), "x", R.UNKNOWN_FIELD),
    (("seal_sha256",), "ab" * 32, R.UNKNOWN_FIELD),        # une couverture ne référence JAMAIS le sceau (graphe acyclique)
    (("sessions",), [], R.UNKNOWN_FIELD),                  # ni ses sessions : elles la référencent
    (("run_record_sha256",), "ab" * 32, R.UNKNOWN_FIELD),  # ni le run
    (("effective_test_end",), "2025-10-01T00:00:00+02:00", R.UNKNOWN_FIELD),   # aucune couverture n'est inventée depuis TRAIN/TEST
    (("execution_window",), {"start": "x"}, R.UNKNOWN_FIELD),
    (("frame", "extra"), 1, R.UNKNOWN_FIELD),
])
def test_an_invalid_or_altered_coverage_record_is_refused_with_an_exact_code(path, value, code):
    refused(code, ev.RunDataCoverage.from_record, _mutated(path, value))


def test_a_record_that_is_not_a_plain_dict_is_refused():
    class Sub(dict):
        pass
    for bad in (None, [], "x", 3, Sub(coverage_record()), tuple(coverage_record().items())):
        refused(R.BAD_TYPE, ev.RunDataCoverage.from_record, bad)


@pytest.mark.parametrize("path,value", [
    (("source_size_bytes",), 208), (("frame", "frame_sha256"), "11" * 32), (("frame", "row_count"), 2),
    (("runtime", "python"), "3.13.8"), (("validation_run_id",), "gate_v_v2_" + "cd" * 32 + "_walk_forward"), (("source_sha256",), "11" * 32),
])
def test_every_meaningful_field_change_changes_the_coverage_hash_when_the_record_stays_valid(path, value):
    record = _mutated(path, value)
    if path == ("source_sha256",):
        record["dataset_snapshot_id"] = "local_csv:sha256:" + value
    assert ev.RunDataCoverage.from_record(record).sha256 != VECTOR["coverage_sha256"]


def test_the_runtime_is_informative_for_semantic_equality_but_not_for_the_hash():
    a = ev.RunDataCoverage.from_record(VECTOR["coverage_record"])
    b = ev.RunDataCoverage.from_record(_mutated(("runtime", "python"), "3.13.8"))
    assert a.sha256 != b.sha256 and a.semantically_equals(b) and b.semantically_equals(a)
    c = ev.RunDataCoverage.from_record(_mutated(("frame", "frame_sha256"), "11" * 32))
    assert not a.semantically_equals(c)
    refused(R.BAD_TYPE, a.semantically_equals, VECTOR["coverage_record"])


def test_the_columns_are_validated_like_l1_does():
    for columns in ([{"name": "time", "kind": "f64"}], [{"name": "a", "kind": "i64"}], [{"name": "time", "kind": "time_us"}, {"name": "time", "kind": "i64"}],
                    [{"name": "time", "kind": "time_us"}, {"name": "a\nb", "kind": "i64"}], [{"name": "time", "kind": "time_us"}, {"name": "a", "kind": "f32"}],
                    [{"name": "time", "kind": "time_us"}, {"name": "", "kind": "i64"}], [{"name": "time", "kind": "time_us"}, {"name": "a" + chr(0xD800), "kind": "i64"}],
                    [{"name": "time", "kind": "time_us"}, {"name": "a", "kind": "i64", "x": 1}], [{"name": "time", "kind": "time_us"}, {"name": "a"}]):
        record = coverage_record()
        record["frame"]["columns"] = columns
        with pytest.raises(ev.EvidenceRefused):
            ev.RunDataCoverage.from_record(record)


def test_a_forged_s0_facts_object_is_re_validated_not_trusted():
    s0 = fd.compute_s0_frame_facts(CSV_V1.encode(), 180)
    forged = fd.S0FrameFacts(s0.source_sha256, s0.source_size_bytes, "local_csv:sha256:" + "00" * 32, s0.frame)
    refused(R.SNAPSHOT_MISMATCH, ev.RunDataCoverage.from_s0_facts, WF, forged, RUNTIME)
    bad_frame = fd.FrameFacts(s0.frame.frame_sha256, 3, s0.frame.columns, 180, s0.frame.first_open_utc, s0.frame.last_open_utc, "2026-01-01T00:03:00.000000Z")
    refused(R.BAD_FRAME, ev.RunDataCoverage.from_s0_facts, WF, fd.S0FrameFacts(s0.source_sha256, s0.source_size_bytes, s0.dataset_snapshot_id, bad_frame), RUNTIME)
    refused(R.BAD_TYPE, ev.RunDataCoverage.from_s0_facts, WF, s0.to_record(), RUNTIME)


def test_the_coverage_factory_accepts_no_fold_or_execution_parameter():
    import inspect
    assert list(inspect.signature(ev.RunDataCoverage.from_s0_facts).parameters) == ["validation_run_id", "s0", "runtime"]


def test_a_coverage_is_immutable_and_cannot_be_built_directly_with_invalid_fields():
    import dataclasses
    cov = ev.RunDataCoverage.from_record(VECTOR["coverage_record"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        cov.frame_sha256 = "11" * 32
    with pytest.raises(dataclasses.FrozenInstanceError):
        cov.validation_run_id = "x"
    fields = {f.name: getattr(cov, f.name) for f in dataclasses.fields(cov)}
    assert dataclasses.replace(cov) == cov
    with pytest.raises(ev.EvidenceRefused):
        dataclasses.replace(cov, frame_sha256="not-hex")
    with pytest.raises(ev.EvidenceRefused):
        dataclasses.replace(cov, row_count=True)
    with pytest.raises(ev.EvidenceRefused):
        dataclasses.replace(cov, columns=[("time", "time_us")])
    assert fields["columns"][0] == ("time", "time_us")


# ── Octets : JSON strict, canonique, sans flottant ──────────────────────────────────────────────────────────────────────────────
CANON = oracle_bytes(VECTOR["coverage_record"])


@pytest.mark.parametrize("raw,code", [
    (None, R.BAD_TYPE), ("{}", R.BAD_TYPE), (bytearray(CANON), R.BAD_TYPE), (b"", R.JSON_INVALID),
    (b"\xef\xbb\xbf" + CANON, R.BOM), (b"\xff\xfe", R.NOT_UTF8), (CANON[:-1], R.NON_CANONICAL),                      # LF final absent
    (CANON.replace(b"\n", b"\r\n"), R.NON_CANONICAL), (CANON + b"\n", R.NON_CANONICAL), (CANON.replace(b"  ", b"    ", 1), R.NON_CANONICAL),
    (json.dumps(VECTOR["coverage_record"], sort_keys=False).encode() + b"\n", R.NON_CANONICAL),
    (b"[]\n", R.NOT_OBJECT), (b'"x"\n', R.NOT_OBJECT), (b"{", R.JSON_INVALID), (b"{} {}", R.JSON_INVALID),
    (b'{"a": 1, "a": 2}\n', R.DUPLICATE_KEY), (b'{"a": NaN}\n', R.FLOAT_FORBIDDEN), (b'{"a": Infinity}\n', R.FLOAT_FORBIDDEN),
    (b'{"a": 1.5}\n', R.FLOAT_FORBIDDEN), (b'{"a": 1e3}\n', R.FLOAT_FORBIDDEN), (b'{"a": ' + b"9" * 5000 + b"}\n", R.JSON_INVALID),
    (b"[" * 5000 + b"]" * 5000, R.JSON_INVALID), (b'{"a": "\\ud800"}\n', R.BAD_VALUE),
])
def test_bytes_that_are_not_strict_canonical_normative_json_are_refused(raw, code):
    refused(code, ev.RunDataCoverage.from_bytes, raw)


def test_a_float_equal_to_an_integer_is_still_a_float_and_a_bool_is_not_an_integer():
    record = coverage_record()
    text = json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2).replace('"source_size_bytes": 207', '"source_size_bytes": 207.0') + "\n"
    refused(R.FLOAT_FORBIDDEN, ev.RunDataCoverage.from_bytes, text.encode())
    text = json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2).replace('"source_size_bytes": 207', '"source_size_bytes": true') + "\n"
    refused(R.BAD_TYPE, ev.RunDataCoverage.from_bytes, text.encode())


def test_the_normative_serializer_refuses_floats_nan_tuples_and_non_text_keys():
    for bad in ({"a": 1.5}, {"a": float("nan")}, {"a": (1, 2)}, {1: "a"}, {"a": {1, 2}}, {"a": b"x"}, [1], "x", {"a": "\ud800"}):
        with pytest.raises(ev.EvidenceRefused):
            ev.normative_json_bytes(bad)
    cyclic = {}
    cyclic["a"] = cyclic
    with pytest.raises(ev.EvidenceRefused):
        ev.normative_json_bytes(cyclic)


def test_evidence_refused_is_picklable_and_carries_a_closed_code():
    error = ev.EvidenceRefused(R.BAD_HEX, "détail")
    clone = pickle.loads(pickle.dumps(error))
    assert (clone.code, clone.detail, str(clone)) == (R.BAD_HEX, "détail", "BAD_HEX: détail")
    assert all(isinstance(member.value, str) and member.value == member.name for member in R)


# ══ Tranche 2 : RunSession ════════════════════════════════════════════════════════════════════════════════════════════════════════
def session_record():
    return copy.deepcopy(VECTOR["session_record"])


def coverage():
    return ev.RunDataCoverage.from_record(VECTOR["coverage_record"])


def _session_mutated(key, value):
    record = session_record()
    if value is KeyError:
        del record[key]
    else:
        record[key] = value
    return record


def test_session_from_the_r9_record_reproduces_the_independent_hash_and_bytes():
    session = ev.RunSession.from_record(VECTOR["session_record"])
    assert session.to_record() == VECTOR["session_record"]
    assert session.to_bytes() == oracle_bytes(VECTOR["session_record"])
    assert session.sha256 == VECTOR["session_sha256"]
    assert ev.RunSession.from_bytes(session.to_bytes()) == session


def test_session_has_exactly_seven_keys_and_no_after_digest_no_role_no_clock():
    keys = set(VECTOR["session_record"])
    assert keys == {"session_semantics_version", "validation_run_id", "coverage_sha256", "session_index", "frame_sha256_before", "frame_row_count", "resumed"}
    # la session est créée AVANT le calcul : elle ne peut contenir ni digest « après », ni horodatage, ni sceau
    for forbidden in ("frame_sha256_after", "role", "started_at", "finished_at", "seal_sha256", "run_record_sha256", "worker_pid"):
        refused(R.UNKNOWN_FIELD, ev.RunSession.from_record, _session_mutated(forbidden, "x"))


def test_a_session_opened_for_a_coverage_equals_the_r9_vector():
    session = ev.RunSession.open_for(coverage(), 1, VECTOR["frame_sha256_v1"], 3, False)
    assert session.to_record() == VECTOR["session_record"] and session.sha256 == VECTOR["session_sha256"]


def test_opening_a_session_whose_frame_digest_differs_from_the_coverage_produces_no_session():
    refused(R.FRAME_BEFORE_MISMATCH, ev.RunSession.open_for, coverage(), 1, VECTOR["frame_sha256_v2"], 3, False)
    refused(R.FRAME_BEFORE_MISMATCH, ev.RunSession.open_for, coverage(), 1, "00" * 32, 3, False)
    refused(R.ROW_COUNT_MISMATCH, ev.RunSession.open_for, coverage(), 1, VECTOR["frame_sha256_v1"], 2, False)
    refused(R.BAD_TYPE, ev.RunSession.open_for, VECTOR["coverage_record"], 1, VECTOR["frame_sha256_v1"], 3, False)
    refused(R.BAD_VALUE, ev.RunSession.open_for, coverage(), 0, VECTOR["frame_sha256_v1"], 3, False)
    refused(R.BAD_TYPE, ev.RunSession.open_for, coverage(), 1, VECTOR["frame_sha256_v1"], 3, 0)


@pytest.mark.parametrize("key,value,code", [
    ("session_semantics_version", "gate_v_run_session_v2", R.BAD_VERSION),
    ("validation_run_id", VECTOR["mc_id"], R.BAD_RUN_ID),                       # une session de calcul n'existe que pour un walk-forward
    ("validation_run_id", "run_1", R.BAD_RUN_ID),
    ("validation_run_id", None, R.BAD_TYPE),
    ("coverage_sha256", "AB" * 32, R.BAD_HEX),
    ("coverage_sha256", "ab" * 33, R.BAD_HEX),
    ("session_index", True, R.BAD_TYPE),
    ("session_index", 1.0, R.FLOAT_FORBIDDEN),
    ("session_index", "1", R.BAD_TYPE),
    ("session_index", 0, R.BAD_VALUE),
    ("session_index", -1, R.BAD_VALUE),
    ("session_index", 10000, R.BAD_VALUE),                                      # NNNN : quatre chiffres
    ("frame_sha256_before", "zz" * 32, R.BAD_HEX),
    ("frame_row_count", True, R.BAD_TYPE),
    ("frame_row_count", 3.0, R.FLOAT_FORBIDDEN),
    ("frame_row_count", 0, R.BAD_VALUE),
    ("resumed", 0, R.BAD_TYPE),
    ("resumed", "false", R.BAD_TYPE),
    ("resumed", None, R.BAD_TYPE),
    ("resumed", KeyError, R.MISSING_FIELD),
    ("coverage_sha256", KeyError, R.MISSING_FIELD),
])
def test_an_invalid_session_record_is_refused_with_an_exact_code(key, value, code):
    refused(code, ev.RunSession.from_record, _session_mutated(key, value))


def test_a_session_record_that_is_not_a_plain_dict_is_refused():
    class Sub(dict):
        pass
    for bad in (None, [], "x", Sub(session_record())):
        refused(R.BAD_TYPE, ev.RunSession.from_record, bad)


def test_session_bytes_are_strictly_canonical():
    canon = oracle_bytes(VECTOR["session_record"])
    refused(R.NON_CANONICAL, ev.RunSession.from_bytes, canon.replace(b"\n", b"\r\n"))
    refused(R.NON_CANONICAL, ev.RunSession.from_bytes, canon[:-1])
    refused(R.FLOAT_FORBIDDEN, ev.RunSession.from_bytes, canon.replace(b'"session_index": 1', b'"session_index": 1.0'))
    refused(R.BAD_TYPE, ev.RunSession.from_bytes, canon.replace(b'"resumed": false', b'"resumed": 0'))
    refused(R.DUPLICATE_KEY, ev.RunSession.from_bytes, b'{"resumed": true, "resumed": false}\n')


def test_every_session_field_change_changes_the_session_hash():
    base = ev.RunSession.from_record(VECTOR["session_record"]).sha256
    for key, value in (("session_index", 2), ("resumed", True), ("frame_row_count", 4), ("frame_sha256_before", "11" * 32), ("coverage_sha256", "11" * 32),
                       ("validation_run_id", "gate_v_v2_" + "cd" * 32 + "_walk_forward")):
        assert ev.RunSession.from_record(_session_mutated(key, value)).sha256 != base, key
    assert ev.RunSession.from_record(_session_mutated("session_index", 9999)).session_index == 9999


def test_a_session_is_immutable_and_revalidated_when_copied_with_changes():
    import dataclasses
    session = ev.RunSession.from_record(VECTOR["session_record"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        session.session_index = 2
    refused(R.BAD_TYPE, dataclasses.replace, session, session_index=True)
    refused(R.BAD_VALUE, dataclasses.replace, session, session_index=0)
    refused(R.BAD_HEX, dataclasses.replace, session, frame_sha256_before="nope")
    assert dataclasses.replace(session, session_index=2).session_index == 2


# ══ Tranche 3 : RunSeal ═══════════════════════════════════════════════════════════════════════════════════════════════════════════
def seal_record():
    return copy.deepcopy(VECTOR["seal_record"])


def _seal_mutated(mutation):
    record = seal_record()
    mutation(record)
    return record


def test_seal_from_the_r9_walk_forward_record_reproduces_the_independent_hash_and_bytes():
    seal = ev.RunSeal.from_record(VECTOR["seal_record"])
    assert seal.to_record() == VECTOR["seal_record"]
    assert seal.to_bytes() == oracle_bytes(VECTOR["seal_record"])
    assert seal.sha256 == VECTOR["seal_sha256"]
    assert ev.RunSeal.from_bytes(seal.to_bytes()) == seal


def test_seal_for_a_derived_run_has_empty_lists_and_a_null_after_digest():
    seal = ev.RunSeal.from_record(VECTOR["mc_seal_record"])
    assert seal.sha256 == VECTOR["mc_seal_sha256"] and seal.sessions == () and seal.output_artifacts == () and seal.frame_sha256_after is None


def test_seal_has_exactly_nine_keys_and_no_clock():
    assert set(VECTOR["seal_record"]) == {"seal_semantics_version", "validation_run_id", "validation_type", "run_record_sha256", "coverage_sha256", "sessions",
                                          "output_artifacts", "frame_sha256_after", "finalized_by_recovery"}
    for forbidden in ("sealed_at", "completed_at", "seal_sha256", "verdict", "status"):
        refused(R.UNKNOWN_FIELD, ev.RunSeal.from_record, _seal_mutated(lambda r, k=forbidden: r.__setitem__(k, "x")))


def _set(key, value):
    return lambda record: record.__setitem__(key, value)


def _delete(key):
    return lambda record: record.pop(key)


S1 = {"session_index": 1, "session_sha256": VECTOR["session_sha256"]}
S2 = {"session_index": 2, "session_sha256": "22" * 32}
S3 = {"session_index": 3, "session_sha256": "33" * 32}
OUT_A = {"path": "walk_forward/a.csv", "sha256": "44" * 32, "size": 1}
OUT_B = {"path": "walk_forward/b.csv", "sha256": "55" * 32, "size": 2}


@pytest.mark.parametrize("mutation,code", [
    (_set("seal_semantics_version", "gate_v_run_seal_v2"), R.BAD_VERSION),
    (_set("validation_run_id", "run_1"), R.BAD_RUN_ID),
    (_set("validation_type", "optimizer"), R.BAD_VALUE),
    (_set("validation_type", "monte_carlo"), R.VALIDATION_TYPE_MISMATCH),          # type déclaré ≠ type de l'identité du run
    (_set("run_record_sha256", "AB" * 32), R.BAD_HEX),
    (_set("coverage_sha256", "ab" * 31), R.BAD_HEX),
    (_set("sessions", "x"), R.BAD_TYPE),
    (_set("sessions", []), R.SESSION_MISSING),                                      # un walk-forward scellé a au moins une session
    (_set("sessions", [S1, S1]), R.SESSION_DUPLICATE),
    (_set("sessions", [S1, {"session_index": 2, "session_sha256": VECTOR["session_sha256"]}]), R.SESSION_DUPLICATE),   # même hash, deux indices
    (_set("sessions", [S2]), R.SESSION_GAP),                                        # ne commence pas à 1
    (_set("sessions", [S1, S3]), R.SESSION_GAP),                                    # trou
    (_set("sessions", [S2, S1]), R.SEAL_ORDER),                                     # non triées
    (_set("sessions", [{"session_index": 1}]), R.MISSING_FIELD),
    (_set("sessions", [dict(S1, extra=1)]), R.UNKNOWN_FIELD),
    (_set("sessions", [dict(S1, session_index=True)]), R.BAD_TYPE),
    (_set("sessions", [dict(S1, session_index=0)]), R.BAD_VALUE),
    (_set("sessions", [dict(S1, session_sha256="zz" * 32)]), R.BAD_HEX),
    (_set("sessions", [[1, "x"]]), R.BAD_TYPE),
    (_set("output_artifacts", [OUT_B, OUT_A]), R.OUTPUT_ORDER),
    (_set("output_artifacts", [OUT_A, OUT_A]), R.OUTPUT_DUPLICATE),
    (_set("output_artifacts", [dict(OUT_A, path="../x")]), R.OUTPUT_PATH),
    (_set("output_artifacts", [dict(OUT_A, path="/walk_forward/x")]), R.OUTPUT_PATH),
    (_set("output_artifacts", [dict(OUT_A, path="walk_forward\\x")]), R.OUTPUT_PATH),
    (_set("output_artifacts", [dict(OUT_A, path="walk_forward//x")]), R.OUTPUT_PATH),
    (_set("output_artifacts", [dict(OUT_A, path="walk_forward/./x")]), R.OUTPUT_PATH),
    (_set("output_artifacts", [dict(OUT_A, path="walk_forward/../x")]), R.OUTPUT_PATH),
    (_set("output_artifacts", [dict(OUT_A, path="walk_forward/x\n")]), R.OUTPUT_PATH),
    (_set("output_artifacts", [dict(OUT_A, path="walk_forward/C:x")]), R.OUTPUT_PATH),
    (_set("output_artifacts", [dict(OUT_A, path="walk_forward/")]), R.OUTPUT_PATH),
    (_set("output_artifacts", [dict(OUT_A, path="other/x")]), R.OUTPUT_PATH),       # tout ce qui est scellé d'un WF est sous walk_forward/
    (_set("output_artifacts", [dict(OUT_A, path="")]), R.OUTPUT_PATH),
    (_set("output_artifacts", [dict(OUT_A, size=-1)]), R.BAD_VALUE),
    (_set("output_artifacts", [dict(OUT_A, size=True)]), R.BAD_TYPE),
    (_set("output_artifacts", [dict(OUT_A, size=1.0)]), R.FLOAT_FORBIDDEN),
    (_set("output_artifacts", [dict(OUT_A, sha256="x")]), R.BAD_HEX),
    (_set("output_artifacts", [{"path": "walk_forward/a"}]), R.MISSING_FIELD),
    (_set("output_artifacts", "x"), R.BAD_TYPE),
    (_set("frame_sha256_after", None), R.FRAME_AFTER_MISSING),                      # calcul sans digest « après »
    (_set("frame_sha256_after", "xyz"), R.BAD_HEX),
    (_set("finalized_by_recovery", True), R.FRAME_AFTER_UNEXPECTED),                # récupération avec digest « après »
    (_set("finalized_by_recovery", 1), R.BAD_TYPE),
    (_set("finalized_by_recovery", "false"), R.BAD_TYPE),
    (_set("coverage_sha256", VECTOR["run_record_sha256"]), R.HASH_ROLE_COLLISION),  # un même hash ne peut pas être couverture ET run
    (_set("sessions", [dict(S1, session_sha256=VECTOR["coverage_sha256"])]), R.HASH_ROLE_COLLISION),
    (_set("sessions", [dict(S1, session_sha256=VECTOR["run_record_sha256"])]), R.HASH_ROLE_COLLISION),
    (_delete("frame_sha256_after"), R.MISSING_FIELD),
    (_delete("output_artifacts"), R.MISSING_FIELD),
])
def test_an_invalid_walk_forward_seal_record_is_refused_with_an_exact_code(mutation, code):
    refused(code, ev.RunSeal.from_record, _seal_mutated(mutation))


def test_a_recovery_seal_has_no_after_digest_and_is_a_distinct_valid_seal():
    record = seal_record()
    record["frame_sha256_after"], record["finalized_by_recovery"] = None, True
    recovery = ev.RunSeal.from_record(record)
    assert recovery.finalized_by_recovery is True and recovery.frame_sha256_after is None
    assert recovery.sha256 != VECTOR["seal_sha256"]


def _derived(mutation):
    record = copy.deepcopy(VECTOR["mc_seal_record"])
    mutation(record)
    return record


@pytest.mark.parametrize("mutation,code", [
    (_set("sessions", [S1]), R.DERIVED_CONTENT),
    (_set("output_artifacts", [OUT_A]), R.DERIVED_CONTENT),
    (_set("frame_sha256_after", "11" * 32), R.DERIVED_CONTENT),
    (_set("validation_type", "walk_forward"), R.VALIDATION_TYPE_MISMATCH),
    (_set("validation_type", "parameter_stability"), R.VALIDATION_TYPE_MISMATCH),
])
def test_an_invalid_derived_seal_record_is_refused(mutation, code):
    refused(code, ev.RunSeal.from_record, _derived(mutation))


def test_a_derived_seal_may_be_a_recovery_seal_and_a_parameter_stability_run_id_carries_its_fold():
    assert ev.RunSeal.from_record(_derived(_set("finalized_by_recovery", True))).finalized_by_recovery is True
    ps = _derived(lambda r: r.update(validation_run_id="gate_v_v2_" + "ab" * 32 + "_parameter_stability_fold_000", validation_type="parameter_stability"))
    assert ev.RunSeal.from_record(ps).validation_type == "parameter_stability"
    ps_without_fold = _derived(lambda r: r.update(validation_run_id="gate_v_v2_" + "ab" * 32 + "_parameter_stability", validation_type="parameter_stability"))
    refused(R.BAD_RUN_ID, ev.RunSeal.from_record, ps_without_fold)


def test_a_seal_record_that_is_not_a_plain_dict_is_refused_and_bytes_are_canonical():
    class Sub(dict):
        pass
    for bad in (None, [], Sub(seal_record())):
        refused(R.BAD_TYPE, ev.RunSeal.from_record, bad)
    canon = oracle_bytes(VECTOR["seal_record"])
    refused(R.NON_CANONICAL, ev.RunSeal.from_bytes, canon.replace(b"\n", b"\r\n"))
    refused(R.FLOAT_FORBIDDEN, ev.RunSeal.from_bytes, canon.replace(b'"size": 8', b'"size": 8.0'))
    refused(R.BAD_TYPE, ev.RunSeal.from_bytes, canon.replace(b'"finalized_by_recovery": false', b'"finalized_by_recovery": 0'))


def test_every_seal_field_change_changes_the_seal_hash_when_the_record_stays_valid():
    base = VECTOR["seal_sha256"]
    for mutation in (_set("run_record_sha256", "66" * 32), _set("coverage_sha256", "66" * 32), _set("frame_sha256_after", "66" * 32),
                     lambda r: r["output_artifacts"][0].__setitem__("size", 56), lambda r: r["output_artifacts"][0].__setitem__("sha256", "66" * 32),
                     lambda r: r["output_artifacts"].pop(), lambda r: r["sessions"][0].__setitem__("session_sha256", "66" * 32),
                     _set("validation_run_id", "gate_v_v2_" + "cd" * 32 + "_walk_forward")):
        assert ev.RunSeal.from_record(_seal_mutated(mutation)).sha256 != base


def test_a_seal_is_immutable_and_revalidated_when_copied_with_changes():
    import dataclasses
    seal = ev.RunSeal.from_record(VECTOR["seal_record"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        seal.frame_sha256_after = None
    refused(R.FRAME_AFTER_MISSING, dataclasses.replace, seal, frame_sha256_after=None)
    refused(R.BAD_TYPE, dataclasses.replace, seal, sessions=[(1, VECTOR["session_sha256"])])
    refused(R.BAD_TYPE, dataclasses.replace, seal, output_artifacts=[("walk_forward/a", "44" * 32, 1)])
    refused(R.SESSION_GAP, dataclasses.replace, seal, sessions=((2, VECTOR["session_sha256"]),))


# ══ Tranche 4 : chaîne couverture → sessions → run → sceau ═══════════════════════════════════════════════════════════════════════
RUN_HASH = VECTOR["run_record_sha256"]
OTHER_RUN = "gate_v_v2_" + "cd" * 32 + "_walk_forward"


def session(index=1, **changes):
    record = session_record()
    record["session_index"] = index
    record.update(changes)
    return ev.RunSession.from_record(record)


def sealing(sessions, **changes):
    """Sceau cohérent listant exactement `sessions` (indices triés), pour construire des scénarios sans passer par le constructeur testé."""
    record = seal_record()
    record["sessions"] = [{"session_index": s.session_index, "session_sha256": s.sha256} for s in sorted(sessions, key=lambda s: s.session_index)]
    record.update(changes)
    return ev.RunSeal.from_record(record)


def verify(sessions=None, seal=None, run_hash=RUN_HASH, cov=None, **kwargs):
    sessions = [session(1)] if sessions is None else sessions
    return ev.verify_run_evidence(cov or coverage(), sessions, seal or sealing(sessions), run_hash, **kwargs)


def test_the_r9_chain_verifies_and_returns_only_hash_facts():
    facts = verify([ev.RunSession.from_record(VECTOR["session_record"])], ev.RunSeal.from_record(VECTOR["seal_record"]))
    assert (facts.validation_run_id, facts.coverage_sha256, facts.session_sha256s, facts.run_record_sha256, facts.seal_sha256) == (
        WF, VECTOR["coverage_sha256"], (VECTOR["session_sha256"],), RUN_HASH, VECTOR["seal_sha256"])
    assert facts.finalized_by_recovery is False


def test_the_seal_builder_reproduces_the_r9_seal_from_the_models():
    outputs = [(o["path"], o["sha256"], o["size"]) for o in reversed(VECTOR["seal_record"]["output_artifacts"])]   # ordre d'appel quelconque
    seal = ev.RunSeal.for_walk_forward(coverage(), [session(1)], RUN_HASH, outputs, VECTOR["frame_sha256_v1"], False)
    assert seal.to_record() == VECTOR["seal_record"] and seal.sha256 == VECTOR["seal_sha256"]


def test_the_seal_builder_builds_a_recovery_seal_with_no_after_digest():
    seal = ev.RunSeal.for_walk_forward(coverage(), [session(1)], RUN_HASH, [], None, True)
    assert seal.finalized_by_recovery is True and seal.frame_sha256_after is None and seal.output_artifacts == ()


def test_sessions_may_be_supplied_in_any_order_and_the_verdict_facts_are_ordered():
    s1, s2, s3 = session(1), session(2, resumed=True), session(3, resumed=True)
    seal = sealing([s3, s1, s2])
    forward, backward = verify([s1, s2, s3], seal), verify([s3, s2, s1], seal)
    assert forward == backward and forward.session_sha256s == (s1.sha256, s2.sha256, s3.sha256)


def test_a_session_of_another_run_is_refused_run_usurpation():
    foreign = session(1, validation_run_id=OTHER_RUN)
    refused(R.WRONG_RUN, verify, [foreign], sealing([foreign]))
    refused(R.WRONG_RUN, verify, None, sealing([session(1)], validation_run_id=OTHER_RUN))
    other_cov = ev.RunDataCoverage.from_record(_mutated(("validation_run_id",), OTHER_RUN))
    refused(R.WRONG_RUN, verify, None, None, RUN_HASH, other_cov)


def test_a_session_or_seal_bound_to_another_coverage_is_refused():
    wrong = session(1, coverage_sha256="11" * 32)
    refused(R.COVERAGE_MISMATCH, verify, [wrong], sealing([wrong]))
    refused(R.COVERAGE_MISMATCH, verify, None, sealing([session(1)], coverage_sha256="11" * 32))
    other_cov = ev.RunDataCoverage.from_record(_mutated(("runtime", "python"), "3.13.8"))    # même trame, octets différents ⇒ autre hash
    refused(R.COVERAGE_MISMATCH, verify, None, None, RUN_HASH, other_cov)


def test_a_session_whose_before_digest_diverges_from_the_coverage_is_refused():
    divergent = session(1, frame_sha256_before=VECTOR["frame_sha256_v2"])
    refused(R.FRAME_BEFORE_MISMATCH, verify, [divergent], sealing([divergent]))
    rows = session(1, frame_row_count=2)
    refused(R.ROW_COUNT_MISMATCH, verify, [rows], sealing([rows]))


def test_a_seal_whose_after_digest_diverges_from_the_coverage_is_refused():
    refused(R.FRAME_AFTER_MISMATCH, verify, None, sealing([session(1)], frame_sha256_after=VECTOR["frame_sha256_v2"]))


def test_a_duplicated_missing_unlisted_or_altered_session_is_refused():
    s1, s2 = session(1), session(2, resumed=True)
    refused(R.SESSION_DUPLICATE, verify, [s1, s1], sealing([s1]))
    refused(R.SESSION_DUPLICATE, verify, [s1, session(1, resumed=True)], sealing([s1]))
    refused(R.SESSION_MISSING, verify, [s1], sealing([s1, s2]))                      # le sceau liste une session que personne ne fournit
    refused(R.SESSION_MISSING, verify, [], sealing([s1]))
    refused(R.SESSION_NOT_LISTED, verify, [s1, s2], sealing([s1]))                    # session fournie mais absente du sceau
    refused(R.SESSION_HASH_MISMATCH, verify, [session(1, resumed=True)], sealing([s1]))   # même indice, contenu différent
    refused(R.SESSION_GAP, verify, [s1, session(3, resumed=True)], sealing([s1, s2]))


def test_a_seal_fabricated_over_missing_sessions_cannot_be_built():
    s2 = session(2, resumed=True)
    refused(R.SESSION_GAP, ev.RunSeal.for_walk_forward, coverage(), [s2], RUN_HASH, [], VECTOR["frame_sha256_v1"], False)
    refused(R.SESSION_MISSING, ev.RunSeal.for_walk_forward, coverage(), [], RUN_HASH, [], VECTOR["frame_sha256_v1"], False)
    refused(R.WRONG_RUN, ev.RunSeal.for_walk_forward, coverage(), [session(1, validation_run_id=OTHER_RUN)], RUN_HASH, [], VECTOR["frame_sha256_v1"], False)
    refused(R.FRAME_AFTER_MISMATCH, ev.RunSeal.for_walk_forward, coverage(), [session(1)], RUN_HASH, [], VECTOR["frame_sha256_v2"], False)
    refused(R.FRAME_AFTER_MISSING, ev.RunSeal.for_walk_forward, coverage(), [session(1)], RUN_HASH, [], None, False)
    refused(R.OUTPUT_DUPLICATE, ev.RunSeal.for_walk_forward, coverage(), [session(1)], RUN_HASH, [("walk_forward/a", "44" * 32, 1)] * 2, VECTOR["frame_sha256_v1"], False)


def test_a_seal_that_references_other_run_bytes_is_refused():
    refused(R.RUN_RECORD_MISMATCH, verify, None, None, "11" * 32)
    refused(R.BAD_HEX, verify, None, None, "XYZ")


def test_a_circular_hash_chain_is_refused():
    seal = sealing([session(1)])
    refused(R.CIRCULAR_REFERENCE, verify, None, seal, RUN_HASH, None, run_references=(seal.sha256,))     # run → sceau → run
    refused(R.CIRCULAR_REFERENCE, verify, None, seal, RUN_HASH, None, run_references=frozenset({"11" * 32, seal.sha256}))
    # un run qui cite une session ou la couverture reste acyclique (le run suit toujours ses ancêtres) : accepté, sans conclusion
    assert verify(None, seal, RUN_HASH, None, run_references=(session(1).sha256,)).seal_sha256 == seal.sha256
    refused(R.BAD_TYPE, verify, None, seal, RUN_HASH, None, run_references="abc")
    refused(R.BAD_HEX, verify, None, seal, RUN_HASH, None, run_references=("abc",))


def test_distinct_roles_must_have_distinct_hashes_in_a_chain():
    seal = sealing([session(1)])
    refused(R.HASH_ROLE_COLLISION, verify, None, seal, seal.sha256, None)                      # le « run » ne peut pas être le sceau lui-même
    refused(R.HASH_ROLE_COLLISION, verify, None, seal, VECTOR["coverage_sha256"], None)        # ni la couverture
    refused(R.HASH_ROLE_COLLISION, verify, None, seal, session(1).sha256, None)                # ni une session
    refused(R.CIRCULAR_REFERENCE, verify, None, seal, RUN_HASH, None, run_references=(RUN_HASH,))   # ni se citer lui-même


def test_derived_runs_and_ill_typed_arguments_are_refused_by_the_chain_verifier():
    mc = ev.RunSeal.from_record(VECTOR["mc_seal_record"])
    refused(R.UNSUPPORTED_BINDING_KIND, ev.verify_run_evidence, coverage(), [], mc, "5e" * 32)
    cov, s1, seal = coverage(), session(1), sealing([session(1)])
    refused(R.BAD_TYPE, ev.verify_run_evidence, VECTOR["coverage_record"], [s1], seal, RUN_HASH)
    refused(R.BAD_TYPE, ev.verify_run_evidence, cov, [s1.to_record()], seal, RUN_HASH)
    refused(R.BAD_TYPE, ev.verify_run_evidence, cov, {1: s1}, seal, RUN_HASH)
    refused(R.BAD_TYPE, ev.verify_run_evidence, cov, [s1], seal.to_record(), RUN_HASH)
    refused(R.BAD_TYPE, ev.verify_run_evidence, cov, [s1], seal, None)


def test_verification_never_mutates_its_inputs_and_its_result_carries_no_verdict():
    import dataclasses
    cov, s1 = coverage(), session(1)
    seal = sealing([s1])
    before = (cov.to_bytes(), s1.to_bytes(), seal.to_bytes())
    facts = ev.verify_run_evidence(cov, [s1], seal, RUN_HASH)
    assert (cov.to_bytes(), s1.to_bytes(), seal.to_bytes()) == before
    assert {f.name for f in dataclasses.fields(facts)} == {"validation_run_id", "coverage_sha256", "session_sha256s", "run_record_sha256", "seal_sha256",
                                                          "finalized_by_recovery"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        facts.seal_sha256 = "x"


# ══ Tranche 5 : machine d'états pure (sceau terminal, publication partielle, crash simulé) ════════════════════════════════════════
import dataclasses
import itertools


def events_wf(n_sessions=1, recovery=False):
    """Séquence d'événements valide : couverture, n sessions, run, sceau."""
    cov = coverage()
    sessions = [session(i, resumed=i > 1) for i in range(1, n_sessions + 1)]
    seal = ev.RunSeal.for_walk_forward(cov, sessions, RUN_HASH, [("walk_forward/manifest.json", "41" * 32, 8)], None if recovery else VECTOR["frame_sha256_v1"],
                                       recovery)
    return [("coverage", cov), *[("session", s) for s in sessions], ("run_record", RUN_HASH), ("seal", seal)]


PHASES = [ev.PHASE_COVERED, ev.PHASE_IN_SESSIONS, ev.PHASE_RUN_RECORDED, ev.PHASE_SEALED]


def test_the_machine_walks_empty_covered_in_sessions_run_recorded_sealed():
    state = ev.initial_state()
    assert state.phase == ev.PHASE_EMPTY and state.coverage is None and state.sessions == () and state.seal is None
    phases = []
    for kind, payload in events_wf(2):
        state = ev.replay([(kind, payload)], state)
        phases.append(state.phase)
    assert phases == [ev.PHASE_COVERED, ev.PHASE_IN_SESSIONS, ev.PHASE_IN_SESSIONS, ev.PHASE_RUN_RECORDED, ev.PHASE_SEALED]
    assert state.seal.sha256 and [s.session_index for s in state.sessions] == [1, 2]


def test_transitions_are_pure_and_never_mutate_the_previous_state():
    before = ev.initial_state()
    after = ev.apply_coverage(before, coverage())
    assert before.coverage is None and before.phase == ev.PHASE_EMPTY and after.phase == ev.PHASE_COVERED and after is not before
    with pytest.raises(dataclasses.FrozenInstanceError):
        after.seal = None
    refused(R.BAD_TYPE, ev.apply_coverage, None, coverage())
    refused(R.BAD_TYPE, ev.apply_coverage, before, VECTOR["coverage_record"])
    refused(R.BAD_TYPE, ev.apply_session, after, session(1).to_record())
    refused(R.BAD_TYPE, ev.apply_seal, after, None)


def test_events_out_of_order_are_refused():
    cov, s1 = ev.apply_coverage(ev.initial_state(), coverage()), session(1)
    refused(R.MACHINE_ORDER, ev.apply_session, ev.initial_state(), s1)                      # session sans couverture
    refused(R.MACHINE_ORDER, ev.apply_run_record, cov, RUN_HASH)                            # run sans session
    seal = events_wf(1)[-1][1]
    refused(R.MACHINE_ORDER, ev.apply_seal, cov, seal)                                      # sceau sans session ni run
    in_sessions = ev.apply_session(cov, s1)
    refused(R.MACHINE_ORDER, ev.apply_seal, in_sessions, seal)                              # sceau sans run
    recorded = ev.apply_run_record(in_sessions, RUN_HASH)
    refused(R.MACHINE_ORDER, ev.apply_session, recorded, session(2, resumed=True))          # aucune session après le run
    refused(R.BAD_VALUE, ev.replay, [("unknown", 1)])
    refused(R.BAD_TYPE, ev.replay, [("coverage",)])


def test_the_same_coverage_is_idempotent_and_a_different_frame_is_a_binding_conflict_that_leaves_the_state_unchanged():
    state = ev.apply_coverage(ev.initial_state(), coverage())
    assert ev.apply_coverage(state, coverage()) == state
    newer_runtime = ev.RunDataCoverage.from_record(_mutated(("runtime", "python"), "3.13.8"))
    kept = ev.apply_coverage(state, newer_runtime)
    assert kept == state and kept.coverage.sha256 == VECTOR["coverage_sha256"]           # l'existant fait foi : runtime informatif ignoré
    different = ev.RunDataCoverage.from_record(_mutated(("frame", "frame_sha256"), "11" * 32))
    refused(R.BINDING_CONFLICT, ev.apply_coverage, state, different)
    assert state.coverage.frame_sha256 == VECTOR["frame_sha256_v1"]


def test_sessions_are_consecutive_never_replayed_and_checked_against_the_coverage():
    state = ev.apply_session(ev.apply_coverage(ev.initial_state(), coverage()), session(1))
    refused(R.SESSION_DUPLICATE, ev.apply_session, state, session(1))
    refused(R.SESSION_DUPLICATE, ev.apply_session, state, session(1, resumed=True))
    refused(R.SESSION_GAP, ev.apply_session, state, session(3, resumed=True))
    refused(R.WRONG_RUN, ev.apply_session, state, session(2, validation_run_id=OTHER_RUN))
    refused(R.COVERAGE_MISMATCH, ev.apply_session, state, session(2, coverage_sha256="11" * 32))
    refused(R.FRAME_BEFORE_MISMATCH, ev.apply_session, state, session(2, frame_sha256_before=VECTOR["frame_sha256_v2"]))
    refused(R.ROW_COUNT_MISMATCH, ev.apply_session, state, session(2, frame_row_count=2))
    assert len(state.sessions) == 1


def test_run_record_is_set_once_and_cannot_collide_with_other_roles():
    state = ev.apply_session(ev.apply_coverage(ev.initial_state(), coverage()), session(1))
    refused(R.BAD_HEX, ev.apply_run_record, state, "xyz")
    refused(R.HASH_ROLE_COLLISION, ev.apply_run_record, state, VECTOR["coverage_sha256"])
    refused(R.HASH_ROLE_COLLISION, ev.apply_run_record, state, session(1).sha256)
    recorded = ev.apply_run_record(state, RUN_HASH)
    assert ev.apply_run_record(recorded, RUN_HASH) == recorded
    refused(R.RUN_RECORD_MISMATCH, ev.apply_run_record, recorded, "11" * 32)


def test_the_seal_is_validated_against_the_accumulated_state():
    s1, s2 = session(1), session(2, resumed=True)
    recorded = ev.replay(events_wf(2)[:-1])
    refused(R.SESSION_NOT_LISTED, ev.apply_seal, recorded, sealing([s1]))                  # sceau incomplet : session 2 non listée
    one_session = ev.replay(events_wf(1)[:-1])
    refused(R.SESSION_MISSING, ev.apply_seal, one_session, sealing([s1, s2]))              # sceau fabriqué sur une session absente
    refused(R.RUN_RECORD_MISMATCH, ev.apply_seal, one_session, sealing([s1], run_record_sha256="11" * 32))
    refused(R.FRAME_AFTER_MISMATCH, ev.apply_seal, one_session, sealing([s1], frame_sha256_after=VECTOR["frame_sha256_v2"]))
    refused(R.COVERAGE_MISMATCH, ev.apply_seal, one_session, sealing([s1], coverage_sha256="11" * 32))
    refused(R.UNSUPPORTED_BINDING_KIND, ev.apply_seal, one_session, ev.RunSeal.from_record(VECTOR["mc_seal_record"]))
    assert one_session.phase == ev.PHASE_RUN_RECORDED and one_session.seal is None         # un sceau refusé ne change pas l'état


def test_the_expected_session_count_must_be_exhaustive():
    recorded = ev.replay(events_wf(2)[:-1])
    seal = events_wf(2)[-1][1]
    refused(R.SESSION_MISSING, ev.apply_seal, recorded, seal, expected_session_count=3)
    refused(R.SESSION_NOT_LISTED, ev.apply_seal, recorded, seal, expected_session_count=1)
    refused(R.BAD_TYPE, ev.apply_seal, recorded, seal, expected_session_count=True)
    refused(R.BAD_VALUE, ev.apply_seal, recorded, seal, expected_session_count=0)
    assert ev.apply_seal(recorded, seal, expected_session_count=2).phase == ev.PHASE_SEALED


def test_a_sealed_run_is_terminal_in_the_pure_machine():
    sealed = ev.replay(events_wf(1))
    assert sealed.phase == ev.PHASE_SEALED
    refused(R.SEALED_RUN_TERMINAL, ev.apply_session, sealed, session(2, resumed=True))
    refused(R.SEALED_RUN_TERMINAL, ev.apply_run_record, sealed, "11" * 32)
    refused(R.SEALED_RUN_TERMINAL, ev.apply_coverage, sealed, coverage())
    refused(R.SEALED_RUN_TERMINAL, ev.apply_coverage, sealed, ev.RunDataCoverage.from_record(_mutated(("frame", "frame_sha256"), "11" * 32)))
    with pytest.raises(dataclasses.FrozenInstanceError):
        sealed.sessions = ()
    assert isinstance(sealed.sessions, tuple) and len(sealed.sessions) == 1


def test_a_second_different_seal_is_a_duplicate_and_the_same_seal_is_idempotent():
    sealed = ev.replay(events_wf(1))
    same = sealed.seal
    assert ev.apply_seal(sealed, same) == sealed
    other = ev.RunSeal.for_walk_forward(coverage(), [session(1)], RUN_HASH, [("walk_forward/other.json", "42" * 32, 3)], VECTOR["frame_sha256_v1"], False)
    refused(R.SEAL_DUPLICATE, ev.apply_seal, sealed, other)
    recovery = ev.RunSeal.for_walk_forward(coverage(), [session(1)], RUN_HASH, [], None, True)
    refused(R.SEAL_DUPLICATE, ev.apply_seal, sealed, recovery)
    assert sealed.seal == same


def test_a_sealed_state_cannot_be_built_from_inconsistent_parts():
    seal = events_wf(1)[-1][1]
    refused(R.MACHINE_ORDER, ev.RunEvidenceState, seal=seal)
    refused(R.MACHINE_ORDER, ev.RunEvidenceState, coverage=coverage(), seal=seal)
    refused(R.MACHINE_ORDER, ev.RunEvidenceState, sessions=(session(1),))
    refused(R.MACHINE_ORDER, ev.RunEvidenceState, coverage=coverage(), run_record_sha256=RUN_HASH)
    refused(R.SESSION_GAP, ev.RunEvidenceState, coverage=coverage(), sessions=(session(2, resumed=True),))
    refused(R.SESSION_MISSING, ev.RunEvidenceState, coverage=coverage(), sessions=(session(1),), run_record_sha256=RUN_HASH, seal=sealing([session(1), session(2, resumed=True)]))
    refused(R.BAD_TYPE, ev.RunEvidenceState, sessions=[session(1)])
    refused(R.BAD_TYPE, ev.RunEvidenceState, coverage=VECTOR["coverage_record"])


def test_simulated_partial_publication_never_reads_as_sealed_before_the_seal_event():
    events = events_wf(2)
    expected = [ev.PHASE_COVERED, ev.PHASE_IN_SESSIONS, ev.PHASE_IN_SESSIONS, ev.PHASE_RUN_RECORDED, ev.PHASE_SEALED]
    for cut in range(1, len(events) + 1):
        state = ev.replay(events[:cut])
        assert state.phase == expected[cut - 1] and (state.seal is not None) == (cut == len(events))


def test_a_crash_between_any_two_simulated_states_resumes_to_the_same_final_state_from_the_persisted_state():
    for events in (events_wf(1), events_wf(3), events_wf(2, recovery=True)):
        reference = ev.replay(events)
        for first, second in itertools.combinations(range(0, len(events) + 1), 2):
            persisted = ev.replay(events[:first])                    # état durable après le premier crash
            persisted = ev.replay(events[first:second], persisted)   # reprise partielle puis second crash
            assert ev.replay(events[second:], persisted) == reference
        for cut in range(0, len(events) + 1):
            # un crash n'invente rien : l'état d'un préfixe est un état valide et rejouer son dernier événement est refusé ou idempotent
            state = ev.replay(events[:cut])
            if cut and events[cut - 1][0] == "session":
                refused(R.SESSION_DUPLICATE, ev.replay, [events[cut - 1]], state)
            elif cut:
                assert ev.replay([events[cut - 1]], state) == state


def test_a_crash_after_the_run_before_the_seal_is_completed_by_a_recovery_seal_never_by_a_fabricated_one():
    recorded = ev.replay(events_wf(1)[:-1])
    assert recorded.phase == ev.PHASE_RUN_RECORDED
    fabricated = sealing([session(1)], frame_sha256_after=VECTOR["frame_sha256_v2"])
    refused(R.FRAME_AFTER_MISMATCH, ev.apply_seal, recorded, fabricated)
    recovery = ev.RunSeal.for_walk_forward(coverage(), [session(1)], RUN_HASH, [], None, True)
    sealed = ev.apply_seal(recorded, recovery)
    assert sealed.phase == ev.PHASE_SEALED and sealed.seal.finalized_by_recovery is True and sealed.seal.frame_sha256_after is None


# ══ Tranche 6 : vecteurs supplémentaires, identités L1, déterminisme, pureté, absence d'autorisation ══════════════════════════════
# Littéraux recalculés par un programme indépendant (json + hashlib, sans importer le module) : voir la note L2, annexe A.
L2_VECTORS = {
    "session_2_sha256": "62c28b3b3ec7f207116d8a302e332247cceb1d7b982a24a0ca00834fe88c1a52",
    "two_sessions_seal_sha256": "a93aefaa3310474db8026ad96a77e47fef917ebaaef5681db4a175549282c826",
    "recovery_seal_sha256": "6b114fc9bc77579ac3d40150bfc3446bf4a98c17e66d4c88d240efcb59cbeb79",
    "parameter_stability_seal_sha256": "ce20290cc6e0a672afdc02ac8581ee10086bf6a42cd3805e5ebae76e4d3f5383",
    "runtime_variant_coverage_sha256": "36d6a4db2c1d5487b15b4aa62d68191dd2e3703924c8a557d7893a51206427dd",
}
MC_COVERAGE_SHA = "23392b149496eccf6e2013d1eed4cdb4db6d9c79f4636f3921913ddeede680dd"
MC_RUN_SHA = "5ece0da0b2081c7ca521108601e7329b18bb3baf61000500a196d551c47d1669"
CSV_V2 = "time,open,high,low,close,tick_volume,spread\n2025-12-31 23:54:00,100.20,100.40,100.10,100.30,9,180\n2025-12-31 23:57:00,100.30,100.50,100.20,100.40,11,180\n2026-01-01 00:00:00,100.40,100.60,100.30,100.50,13,180\n"
CSV_V3 = "time,open,high,low,close,tick_volume,spread\n2025-12-31 23:52:00,100.10,100.30,100.00,100.20,7,180\n2025-12-31 23:55:00,100.20,100.40,100.10,100.30,9,180\n2025-12-31 23:58:00,100.30,100.50,100.20,100.40,11,180\n"
BASE_OUTPUTS = [(o["path"], o["sha256"], o["size"]) for o in VECTOR["seal_record"]["output_artifacts"]]


def test_the_two_session_chain_the_recovery_seal_and_the_derived_seal_reproduce_the_independent_vectors():
    s1, s2 = session(1), session(2, resumed=True)
    assert s2.sha256 == L2_VECTORS["session_2_sha256"]
    two = ev.RunSeal.for_walk_forward(coverage(), [s2, s1], RUN_HASH, BASE_OUTPUTS, VECTOR["frame_sha256_v1"], False)
    assert two.sha256 == L2_VECTORS["two_sessions_seal_sha256"]
    recovery = ev.RunSeal.for_walk_forward(coverage(), [s1], RUN_HASH, [], None, True)
    assert recovery.sha256 == L2_VECTORS["recovery_seal_sha256"]
    ps = ev.RunSeal.from_record({
        "coverage_sha256": MC_COVERAGE_SHA, "finalized_by_recovery": False, "frame_sha256_after": None, "output_artifacts": [], "run_record_sha256": MC_RUN_SHA,
        "seal_semantics_version": "gate_v_run_seal_v1", "sessions": [], "validation_type": "parameter_stability",
        "validation_run_id": WF.replace("_walk_forward", "_parameter_stability_fold_000")})
    assert ps.sha256 == L2_VECTORS["parameter_stability_seal_sha256"]
    variant = ev.RunDataCoverage.from_record(_mutated(("runtime", "python"), "3.13.8"))
    assert variant.sha256 == L2_VECTORS["runtime_variant_coverage_sha256"] and variant.semantically_equals(coverage())


def test_the_l1_identities_are_unchanged_when_seen_through_the_l2_models():
    for csv_text, digest, rows in ((CSV_V1, VECTOR["frame_sha256_v1"], 3), (CSV_V2, VECTOR["frame_sha256_v2"], 3), (CSV_V3, VECTOR["frame_sha256_v3"], 3)):
        s0 = fd.compute_s0_frame_facts(csv_text.encode(), 180)
        assert s0.frame.frame_sha256 == digest
        cov = ev.RunDataCoverage.from_s0_facts(WF, s0, RUNTIME)
        assert (cov.frame_sha256, cov.row_count, cov.dataset_snapshot_id) == (digest, rows, s0.dataset_snapshot_id)
    s0 = fd.compute_s0_frame_facts(CSV_V1.encode(), 180)
    assert hashlib.sha256(ev.normative_json_bytes(s0.to_record())).hexdigest() == VECTOR["s0_frame_facts_sha256"]
    assert s0.dataset_snapshot_id == "local_csv:sha256:8d43f5576f03a0f39ab24409ae9d12152a8a49ab9d48e4af3f1e2e83b8d7dea6" and fd.FRAME_DIGEST_VERSION == "gate_v_frame_digest_v1"


def test_the_derived_coverage_is_not_implemented_and_never_guessed_from_a_walk_forward_record():
    derived = {"binding_kind": "DERIVED", "coverage_semantics_version": "gate_v_run_data_coverage_v1", "inputs": [], "parent_run_record_sha256": H,
               "parent_seal_sha256": H, "parent_validation_run_id": WF, "validation_run_id": VECTOR["mc_id"], "validation_type": "monte_carlo"}
    refused(R.UNSUPPORTED_BINDING_KIND, ev.RunDataCoverage.from_record, derived)


@pytest.mark.parametrize("field", ["first_open_utc", "last_open_utc", "last_close_utc_exclusive"])
@pytest.mark.parametrize("bad", ["", "2025-12-31", "2025-12-31T23:51:00", "2025-12-31T23:51:00.0Z", "2025-12-31T23:51:00.000000", "2025-12-31t23:51:00.000000Z",
                                 "2025-12-31T23:51:00.000000z", "2025-02-30T23:51:00.000000Z", "2025-12-31T23:60:00.000000Z", "2025-12-31T23:51:60.000000Z",
                                 " 2025-12-31T23:51:00.000000Z", "2025-12-31T23:51:00.000000Z\n", "2025-12-31T23:51:00,000000Z", "2025-12-31T23:51:00.000000+01:00"])
def test_every_instant_field_refuses_a_malformed_or_impossible_timestamp(field, bad):
    refused(R.BAD_INSTANT, ev.RunDataCoverage.from_record, _mutated(("frame", field), bad))


@pytest.mark.parametrize("path", [("source_size_bytes",), ("frame", "row_count"), ("frame", "bar_duration_seconds")])
@pytest.mark.parametrize("bad,code", [(True, R.BAD_TYPE), (False, R.BAD_TYPE), (1.0, R.FLOAT_FORBIDDEN), ("1", R.BAD_TYPE), (None, R.BAD_TYPE), ([1], R.BAD_TYPE)])
def test_no_integer_field_accepts_a_boolean_float_text_or_container(path, bad, code):
    refused(code, ev.RunDataCoverage.from_record, _mutated(path, bad))


def test_models_survive_pickle_and_copy_and_a_tampered_reduction_is_revalidated():
    state = ev.replay(events_wf(2))
    for obj in (coverage(), session(1), events_wf(1)[-1][1], state, ev.verify_run_evidence(coverage(), [session(1)], sealing([session(1)]), RUN_HASH)):
        assert pickle.loads(pickle.dumps(obj)) == obj and copy.deepcopy(obj) == obj and copy.copy(obj) == obj
    function, (record,) = coverage().__reduce__()
    refused(R.BAD_TYPE, function, dict(record, source_size_bytes=True))
    function, (record,) = session(1).__reduce__()
    refused(R.BAD_HEX, function, dict(record, coverage_sha256="x"))
    function, (record,) = events_wf(1)[-1][1].__reduce__()
    refused(R.FRAME_AFTER_MISSING, function, dict(record, frame_sha256_after=None))
    refused(R.BAD_TYPE, dataclasses.replace, coverage(), runtime=(("numpy", "x", "y"), ("pandas", "a"), ("python", "b")))
    refused(R.BAD_TYPE, dataclasses.replace, coverage(), runtime=(("numpy", "1"), ("pandas", "2")))


DETERMINISM_SCRIPT = (
    "import sys, json\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import gate_v_frame_digest as fd\n"
    "import gate_v_run_evidence_models as ev\n"
    "s0 = fd.compute_s0_frame_facts(sys.argv[2].encode(), 180)\n"
    "cov = ev.RunDataCoverage.from_s0_facts(sys.argv[3], s0, json.loads(sys.argv[4]))\n"
    "s1 = ev.RunSession.open_for(cov, 1, s0.frame.frame_sha256, 3, False)\n"
    "outputs = [tuple(o) for o in json.loads(sys.argv[6])]\n"
    "seal = ev.RunSeal.for_walk_forward(cov, [s1], sys.argv[5], outputs, s0.frame.frame_sha256, False)\n"
    "state = ev.replay([('coverage', cov), ('session', s1), ('run_record', sys.argv[5]), ('seal', seal)])\n"
    "print(json.dumps([cov.sha256, s1.sha256, seal.sha256, state.phase, ev.verify_run_evidence(cov, [s1], seal, sys.argv[5]).seal_sha256]))\n"
)


def test_hashes_are_identical_across_processes_and_hash_seeds():
    import os
    import subprocess
    import sys
    results = set()
    for seed in ("0", "1", "4242", "random"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
        completed = subprocess.run([sys.executable, "-c", DETERMINISM_SCRIPT, str(ROOT), CSV_V1, WF, json.dumps(RUNTIME), RUN_HASH, json.dumps(BASE_OUTPUTS)],
                                   capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=120)
        assert completed.returncode == 0, completed.stderr
        results.add(completed.stdout.strip())
    assert results == {json.dumps([VECTOR["coverage_sha256"], VECTOR["session_sha256"], VECTOR["seal_sha256"], "SEALED", VECTOR["seal_sha256"]])}


def test_the_models_are_pure_no_file_no_network_no_clock_no_environment(monkeypatch):
    import builtins
    import os
    import socket
    import time

    def boom(*args, **kwargs):
        raise AssertionError("accès interdit à un module pur")
    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(time, "time", boom)
    monkeypatch.setattr(os, "environ", {})
    state = ev.replay(events_wf(2))
    assert state.phase == ev.PHASE_SEALED and ev.RunSeal.from_bytes(state.seal.to_bytes()) == state.seal


def test_the_module_source_imports_only_the_standard_library_and_l1_and_calls_nothing_dangerous():
    import ast
    tree = ast.parse((ROOT / "gate_v_run_evidence_models.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported == {"__future__", "hashlib", "json", "re", "unicodedata", "dataclasses", "functools", "datetime", "enum", "gate_v_frame_digest"}
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "eval", "exec", "compile", "__import__", "input", "print", "getattr", "setattr", "globals", "vars"}
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attributes & {"now", "utcnow", "today", "time", "environ", "getenv", "random", "uuid4"}
    assigned_to_l1 = [n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AugAssign)) and any(
        isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "fd" for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))]
    assert assigned_to_l1 == []


def test_no_authorisation_verdict_or_scientific_claim_object_exists_in_the_module():
    import ast
    forbidden = ("fresh", "no_overlap", "admission", "admit", "claim", "authoriz", "authoris", "permission", "grant", "token", "verdict", "holdout", "real_enabled",
                 "source_kind", "exposure", "overlap")
    names = set(ev.__all__)
    tree = ast.parse((ROOT / "gate_v_run_evidence_models.py").read_text(encoding="utf-8"))
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    names |= {m.name for m in R} | {f.name for f in dataclasses.fields(ev.EvidenceChainFacts)} | {f.name for f in dataclasses.fields(ev.RunEvidenceState)}
    offenders = sorted(name for name in names if any(word in name.lower() for word in forbidden))
    assert offenders == []
    state = ev.replay(events_wf(1))
    assert {name for name in dir(state) if not name.startswith("_")} == {"coverage", "sessions", "run_record_sha256", "seal", "phase"}
    chain = ev.verify_run_evidence(coverage(), [session(1)], sealing([session(1)]), RUN_HASH)
    assert {name for name in dir(chain) if not name.startswith("_")} == {"validation_run_id", "coverage_sha256", "session_sha256s", "run_record_sha256",
                                                                          "seal_sha256", "finalized_by_recovery"}


def test_the_public_surface_is_frozen():
    assert sorted(ev.__all__) == sorted([
        "BINDING_DERIVED", "BINDING_MARKET_DATA_FRAME", "COVERAGE_SEMANTICS_VERSION", "EvidenceChainFacts", "EvidenceRefusal", "EvidenceRefused", "LOADER_ID",
        "PHASE_COVERED", "PHASE_EMPTY", "PHASE_IN_SESSIONS", "PHASE_RUN_RECORDED", "PHASE_SEALED", "RunDataCoverage", "RunEvidenceState", "RunSeal", "RunSession",
        "SEAL_SEMANTICS_VERSION", "SESSION_SEMANTICS_VERSION", "WALK_FORWARD_OUTPUT_ROOT", "apply_coverage", "apply_run_record", "apply_seal", "apply_session",
        "initial_state", "normative_json_bytes", "parse_normative_json", "replay", "verify_run_evidence"])
    assert sorted(m.value for m in R) == sorted([
        "BAD_TYPE", "BAD_VALUE", "BAD_VERSION", "BAD_RUN_ID", "BAD_HEX", "BAD_INSTANT", "BAD_FRAME", "SNAPSHOT_MISMATCH", "MISSING_FIELD", "UNKNOWN_FIELD",
        "FLOAT_FORBIDDEN", "BOM", "NOT_UTF8", "JSON_INVALID", "NOT_OBJECT", "DUPLICATE_KEY", "NON_CANONICAL", "OUTPUT_CONFLICT", "UNSUPPORTED_BINDING_KIND",
        "FRAME_BEFORE_MISMATCH", "ROW_COUNT_MISMATCH", "VALIDATION_TYPE_MISMATCH", "SESSION_MISSING", "SESSION_DUPLICATE", "SESSION_GAP", "SEAL_ORDER",
        "OUTPUT_ORDER", "OUTPUT_DUPLICATE", "OUTPUT_PATH", "FRAME_AFTER_MISSING", "FRAME_AFTER_UNEXPECTED", "DERIVED_CONTENT", "HASH_ROLE_COLLISION",
        "WRONG_RUN", "COVERAGE_MISMATCH", "SESSION_NOT_LISTED", "SESSION_HASH_MISMATCH", "RUN_RECORD_MISMATCH", "FRAME_AFTER_MISMATCH", "CIRCULAR_REFERENCE",
        "MACHINE_ORDER", "BINDING_CONFLICT", "SEALED_RUN_TERMINAL", "SEAL_DUPLICATE"])


# ══ Tranche 7 : durcissements issus de la mutation ciblée ══════════════════════════════════════════════════════════════════════
def test_microseconds_take_part_in_the_frame_bounds():
    refused(R.BAD_FRAME, ev.RunDataCoverage.from_record, _mutated(("frame", "last_close_utc_exclusive"), "2026-01-01T00:00:00.000001Z"))
    shifted = coverage_record()
    for field in ("first_open_utc", "last_open_utc", "last_close_utc_exclusive"):
        shifted["frame"][field] = shifted["frame"][field].replace(".000000Z", ".000001Z")
    assert ev.RunDataCoverage.from_record(shifted).sha256 != VECTOR["coverage_sha256"]


def test_a_first_open_off_the_bar_grid_is_refused_even_when_the_row_count_would_fit():
    record = _mutated(("frame", "first_open_utc"), "2025-12-31T23:51:30.000000Z")
    record["frame"]["row_count"] = 2
    refused(R.BAD_FRAME, ev.RunDataCoverage.from_record, record)


def test_a_repeated_session_index_with_distinct_hashes_is_a_duplicate_not_a_gap():
    refused(R.SESSION_DUPLICATE, ev.RunSeal.from_record, _seal_mutated(_set("sessions", [S1, dict(S1, session_sha256="22" * 32)])))


def test_the_float_refusal_code_is_exact_and_str_or_key_subclasses_are_refused():
    refused(R.FLOAT_FORBIDDEN, ev.normative_json_bytes, {"a": {"b": [1, 1.5]}})

    class S(str):
        pass
    refused(R.BAD_TYPE, ev.RunDataCoverage.from_record, _mutated(("validation_run_id",), S(WF)))
    refused(R.BAD_TYPE, ev.RunSession.from_record, _session_mutated("coverage_sha256", S(VECTOR["coverage_sha256"])))
    with_key = coverage_record()
    with_key[1] = "x"
    refused(R.BAD_TYPE, ev.RunDataCoverage.from_record, with_key)


# ══ Tranche 8 : défauts démontrés par la relecture indépendante ═════════════════════════════════════════════════════════════════
def test_replay_refuses_ill_typed_events_with_a_closed_code_never_a_raw_exception():
    for bad in ([(["x"], 1)], [({}, 1)], [(None, 1)], 5, None, "abc", [5], [("coverage", coverage(), 1)]):
        with pytest.raises(ev.EvidenceRefused):
            ev.replay(bad)
    refused(R.BAD_TYPE, ev.replay, [(["x"], 1)])
    refused(R.BAD_TYPE, ev.replay, 5)


def test_the_chain_facts_cannot_be_forged_with_junk_values():
    good = ev.verify_run_evidence(coverage(), [session(1)], sealing([session(1)]), RUN_HASH)
    assert dataclasses.replace(good) == good
    refused(R.BAD_RUN_ID, ev.EvidenceChainFacts, "junk", 1, 2, 3, 4, "yes")
    refused(R.BAD_TYPE, ev.EvidenceChainFacts, WF, 1, 2, 3, 4, "yes")
    refused(R.BAD_HEX, ev.EvidenceChainFacts, WF, "x", (VECTOR["session_sha256"],), RUN_HASH, VECTOR["seal_sha256"], False)
    refused(R.BAD_TYPE, ev.EvidenceChainFacts, WF, VECTOR["coverage_sha256"], [VECTOR["session_sha256"]], RUN_HASH, VECTOR["seal_sha256"], False)
    refused(R.BAD_TYPE, ev.EvidenceChainFacts, WF, VECTOR["coverage_sha256"], (VECTOR["session_sha256"],), RUN_HASH, VECTOR["seal_sha256"], "yes")
    refused(R.SESSION_MISSING, ev.EvidenceChainFacts, WF, VECTOR["coverage_sha256"], (), RUN_HASH, VECTOR["seal_sha256"], False)
    recovery = ev.RunSeal.for_walk_forward(coverage(), [session(1)], RUN_HASH, [], None, True)
    assert ev.verify_run_evidence(coverage(), [session(1)], recovery, RUN_HASH).finalized_by_recovery is True


def test_the_run_hash_cannot_be_the_frame_digest_or_the_source_digest_of_the_coverage():
    for confusing in (VECTOR["frame_sha256_v1"], coverage().source_sha256):
        refused(R.HASH_ROLE_COLLISION, ev.RunSeal.for_walk_forward, coverage(), [session(1)], confusing, [], VECTOR["frame_sha256_v1"], False)
        refused(R.HASH_ROLE_COLLISION, verify, None, None, confusing)
        state = ev.apply_session(ev.apply_coverage(ev.initial_state(), coverage()), session(1))
        refused(R.HASH_ROLE_COLLISION, ev.apply_run_record, state, confusing)


@pytest.mark.parametrize("paths,code", [
    (["walk_forward/a", "walk_forward/a/b"], R.OUTPUT_CONFLICT),                 # un fichier et un dossier de même nom
    (["walk_forward/a", "walk_forward/A"], R.OUTPUT_CONFLICT),                   # systèmes de fichiers insensibles à la casse
    (["walk_forward/a/b", "walk_forward/a/c", "walk_forward/a"], R.OUTPUT_CONFLICT),
    (["walk_forward/é"], None),                                             # NFC : accepté
    (["walk_forward/é"], R.OUTPUT_PATH),                                   # NFD : refusé (forme non normalisée)
    (["walk_forward/a."], R.OUTPUT_PATH),                                        # Windows retire le point final
    (["walk_forward/a "], R.OUTPUT_PATH),
    (["walk_forward/a\\b"], R.OUTPUT_PATH),
    (["walk_forward/a\x1fb"], R.OUTPUT_PATH),
    (["walk_forward/a\x7fb"], R.OUTPUT_PATH),
    (["walk_forward/a\ud800"], R.BAD_VALUE),
])
def test_output_listings_that_no_filesystem_could_hold_are_refused(paths, code):
    outputs = [{"path": p, "sha256": "44" * 32, "size": 1} for p in sorted(paths)]
    record = _seal_mutated(_set("output_artifacts", outputs))
    if code is None:
        assert ev.RunSeal.from_record(record).output_artifacts[0][0] == paths[0]
    else:
        refused(code, ev.RunSeal.from_record, record)


@pytest.mark.parametrize("run_id,code", [
    (WF + "_x", R.BAD_RUN_ID), (WF[:-1], R.BAD_RUN_ID), ("gate_v_v2_" + "ab" * 31 + "a_walk_forward", R.BAD_RUN_ID),
    ("gate_v_v2_" + "ab" * 32 + "_parameter_stability_", R.BAD_RUN_ID), ("gate_v_v2_" + "ab" * 32 + "_parameter_stability", R.BAD_RUN_ID),
    ("gate_v_v2_" + "ab" * 32 + "_parameter_stabilityfold", R.BAD_RUN_ID), ("x" + WF, R.BAD_RUN_ID), (WF + "\n", R.BAD_RUN_ID),
])
def test_run_identities_must_match_the_whole_string(run_id, code):
    refused(code, ev.RunSeal.from_record, _seal_mutated(_set("validation_run_id", run_id)))
    refused(code, ev.RunSession.from_record, _session_mutated("validation_run_id", run_id))


def test_text_fields_refuse_lone_surrogates_and_blank_or_control_runtime_strings():
    refused(R.BAD_VALUE, ev.RunDataCoverage.from_record, _mutated(("loader_id",), "gate_v_s0_frame_loader_v1\ud800"))
    for bad in (" ", "\t", "3.13\n", "3.1\x003", "a\x7f"):
        refused(R.BAD_VALUE, ev.RunDataCoverage.from_record, _mutated(("runtime", "pandas"), bad))


def test_derived_seal_records_with_non_list_collections_are_refused():
    refused(R.BAD_TYPE, ev.RunSeal.from_record, _derived(_set("sessions", "x")))
    refused(R.BAD_TYPE, ev.RunSeal.from_record, _derived(_set("output_artifacts", None)))
    refused(R.BAD_TYPE, ev.RunSeal.from_record, _derived(_set("sessions", ())))


def test_a_state_built_from_ill_typed_parts_is_refused():
    refused(R.BAD_HEX, ev.RunEvidenceState, coverage=coverage(), sessions=(session(1),), run_record_sha256="xyz")
    refused(R.BAD_TYPE, ev.RunEvidenceState, coverage=coverage(), sessions=(session(1),), run_record_sha256=RUN_HASH, seal="x")
    refused(R.BAD_TYPE, ev.RunEvidenceState, coverage=coverage(), sessions=(session(1),), run_record_sha256=7)


def test_a_sealed_state_still_checks_the_expected_session_count_and_documents_that_it_is_a_value_not_a_journal():
    sealed = ev.replay(events_wf(2))
    refused(R.SESSION_MISSING, ev.apply_seal, sealed, sealed.seal, expected_session_count=3)
    refused(R.SESSION_NOT_LISTED, ev.apply_seal, sealed, sealed.seal, expected_session_count=1)
    assert ev.apply_seal(sealed, sealed.seal, expected_session_count=2) == sealed
    for documented in (ev.RunEvidenceState, ev.replay, ev.RunSession, ev.EvidenceChainFacts):
        assert documented.__doc__ and ("pas une preuve" in documented.__doc__ or "ne prouve" in documented.__doc__ or "pas un journal" in documented.__doc__)


def test_chain_facts_validate_every_hash_field_and_the_hashes_are_cached_on_the_immutable_models():
    args = [WF, VECTOR["coverage_sha256"], (VECTOR["session_sha256"],), RUN_HASH, VECTOR["seal_sha256"], False]
    for position in (1, 3, 4):
        bad = list(args)
        bad[position] = "x"
        refused(R.BAD_HEX, ev.EvidenceChainFacts, *bad)
    refused(R.BAD_HEX, ev.EvidenceChainFacts, *args[:2], ("x",), *args[3:])
    for model in (coverage(), session(1), events_wf(1)[-1][1]):
        assert model.sha256 is model.sha256


def test_a_long_run_of_sessions_stays_fast_enough_for_the_pure_machine():
    import time
    state = ev.apply_coverage(ev.initial_state(), coverage())
    started = time.perf_counter()
    for index in range(1, 601):
        state = ev.apply_session(state, session(index, resumed=index > 1))
    assert len(state.sessions) == 600 and time.perf_counter() - started < 3.0     # sans cache de sha256 : plus de 10 s


# ══ Tranche 9 : défauts démontrés par la revue finale du delta ═════════════════════════════════════════════════════════════════
def _time_it(fn):
    import time
    started = time.perf_counter()
    try:
        fn()
    except ev.EvidenceRefused:
        pass
    return time.perf_counter() - started


def test_hostile_output_paths_are_bounded_and_the_conflict_check_is_near_linear():
    deep = "walk_forward/" + "/".join(["a"] * 20000) + "/f.csv"
    refused(R.OUTPUT_PATH, ev.RunSeal.from_record, _seal_mutated(_set("output_artifacts", [dict(OUT_A, path=deep)])))
    refused(R.OUTPUT_PATH, ev.RunSeal.from_record, _seal_mutated(_set("output_artifacts", [dict(OUT_A, path="walk_forward/" + "x" * 256)])))
    refused(R.OUTPUT_PATH, ev.RunSeal.from_record, _seal_mutated(_set("output_artifacts", [dict(OUT_A, path="walk_forward/" + "/".join(["d" * 200] * 25))])))
    assert ev.RunSeal.from_record(_seal_mutated(_set("output_artifacts", [dict(OUT_A, path="walk_forward/" + "x" * 255)]))).output_artifacts
    assert _time_it(lambda: ev.RunSeal.from_record(_seal_mutated(_set("output_artifacts", [dict(OUT_A, path=deep)])))) < 1.0
    wide = [dict(OUT_A, path="walk_forward/d%05d/f.csv" % i) for i in range(20000)]
    assert _time_it(lambda: ev.RunSeal.from_record(_seal_mutated(_set("output_artifacts", sorted(wide, key=lambda o: o["path"]))))) < 5.0


def test_sibling_names_sharing_a_prefix_are_not_confused_with_a_file_directory_conflict():
    ok = [dict(OUT_A, path=p) for p in sorted(["walk_forward/a", "walk_forward/a-b", "walk_forward/a.b", "walk_forward/ab/c", "walk_forward/b"])]
    assert len(ev.RunSeal.from_record(_seal_mutated(_set("output_artifacts", ok))).output_artifacts) == 5
    clash = [dict(OUT_A, path=p) for p in sorted(["walk_forward/a", "walk_forward/a-b", "walk_forward/a/c"])]
    refused(R.OUTPUT_CONFLICT, ev.RunSeal.from_record, _seal_mutated(_set("output_artifacts", clash)))
    clash = [dict(OUT_A, path=p) for p in sorted(["walk_forward/A/x", "walk_forward/a", "walk_forward/b"])]
    refused(R.OUTPUT_CONFLICT, ev.RunSeal.from_record, _seal_mutated(_set("output_artifacts", clash)))


class _Boom:
    def __eq__(self, other):
        raise ValueError("hostile __eq__")

    def __hash__(self):
        return 1

    def __str__(self):
        raise RuntimeError("hostile __str__")


def test_hostile_values_never_raise_a_raw_exception():
    deep = []
    for _ in range(100000):
        deep = [deep]
    for path in (10**5000, _Boom(), deep, b"walk_forward/x", None):
        refused(R.BAD_TYPE, ev.RunSeal.for_walk_forward, coverage(), [session(1)], RUN_HASH, [(path, "07" * 32, 5)], VECTOR["frame_sha256_v1"], False)
    mixed = [("walk_forward/a", "44" * 32, 1), (5, "44" * 32, 1)]      # deux éléments : le tri comparerait un texte et un entier
    refused(R.BAD_TYPE, ev.RunSeal.for_walk_forward, coverage(), [session(1)], RUN_HASH, mixed, VECTOR["frame_sha256_v1"], False)
    refused(R.BAD_TYPE, ev.RunSeal.for_walk_forward, coverage(), [session(1)], RUN_HASH, mixed[::-1], VECTOR["frame_sha256_v1"], False)
    refused(R.BAD_TYPE, ev.RunDataCoverage.from_record, _mutated(("binding_kind",), _Boom()))
    refused(R.BAD_TYPE, ev.RunDataCoverage.from_record, _mutated(("loader_id",), _Boom()))
    refused(R.BAD_TYPE, dataclasses.replace, coverage(), runtime=((_Boom(), "a"), ("pandas", "b"), ("python", "c")))
    refused(R.BAD_TYPE, dataclasses.replace, coverage(), runtime=(("numpy", "a"), (_Boom(), "b"), ("python", "c")))
    refused(R.BAD_TYPE, dataclasses.replace, coverage(), columns=((_Boom(), "time_us"),))


def test_chain_facts_built_directly_enforce_the_same_role_and_uniqueness_rules_and_say_they_are_not_proof():
    s, c, r, k = "22" * 32, "11" * 32, "33" * 32, "44" * 32
    assert ev.EvidenceChainFacts(WF, c, (s,), r, k, False).seal_sha256 == k
    refused(R.SESSION_DUPLICATE, ev.EvidenceChainFacts, WF, c, (s, s), r, k, False)
    refused(R.HASH_ROLE_COLLISION, ev.EvidenceChainFacts, WF, c, (s,), c, k, False)      # run = couverture
    refused(R.HASH_ROLE_COLLISION, ev.EvidenceChainFacts, WF, c, (s,), r, c, False)      # sceau = couverture
    refused(R.HASH_ROLE_COLLISION, ev.EvidenceChainFacts, WF, c, (s,), r, r, False)      # sceau = run
    refused(R.HASH_ROLE_COLLISION, ev.EvidenceChainFacts, WF, c, (r,), r, k, False)      # session = run
    refused(R.HASH_ROLE_COLLISION, ev.EvidenceChainFacts, WF, c, (c,), r, k, False)      # session = couverture
    refused(R.HASH_ROLE_COLLISION, ev.EvidenceChainFacts, WF, c, (k,), r, k, False)      # session = sceau
    doc = ev.EvidenceChainFacts.__doc__
    assert "pas une preuve" in doc and "verify_run_evidence" in doc and "construction directe" in doc


def test_a_coverage_cannot_use_one_digest_for_both_the_source_and_the_frame():
    record = coverage_record()
    record["frame"]["frame_sha256"] = record["source_sha256"]
    refused(R.HASH_ROLE_COLLISION, ev.RunDataCoverage.from_record, record)


def test_messages_do_not_assert_causes_or_authorisations_the_model_cannot_know():
    import inspect
    source = inspect.getsource(ev)
    for phrase in ("trame modifiée pendant le calcul", "aucun calcul n'est autorisé"):
        assert phrase not in source


def test_a_seal_applied_before_the_run_is_an_order_error_even_with_a_wrong_expected_count():
    in_sessions = ev.replay(events_wf(1)[:-2])
    assert in_sessions.phase == ev.PHASE_IN_SESSIONS
    refused(R.MACHINE_ORDER, ev.apply_seal, in_sessions, events_wf(1)[-1][1], expected_session_count=5)


def test_a_frame_with_a_single_row_is_refused_even_if_the_span_would_allow_it():
    record = _mutated(("frame", "row_count"), 1)
    refused(R.BAD_FRAME, ev.RunDataCoverage.from_record, record)


def test_the_seal_builder_refuses_ill_shaped_outputs_with_a_closed_code():
    for bad in ("x", None, [["walk_forward/a", "44" * 32, 1]], [("walk_forward/a",)], [("walk_forward/a", "44" * 32, 1, 0)], {"walk_forward/a": 1}):
        refused(R.BAD_TYPE, ev.RunSeal.for_walk_forward, coverage(), [session(1)], RUN_HASH, bad, VECTOR["frame_sha256_v1"], False)
