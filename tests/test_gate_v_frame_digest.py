"""K1 Étape 2, lot L1 : tests de `gate_v_frame_digest` (contrat R9 section 3, PROPOSED — non accepté).

Ces tests ne vérifient que des FAITS sur des octets et des colonnes typées : jamais un verdict d'exposition (FRESH, NO_OVERLAP,
admission, Claim). Les valeurs attendues ne sont jamais calculées par le module testé : elles viennent (a) des vecteurs littéraux
de `docs/adr/0025-proposal-E3E-Q2-STAGE2-VECTORS.json` (recalculés par un programme indépendant) recopiés ici, et (b) d'un oracle
écrit dans ce fichier avec d'autres primitives (`int.to_bytes`, `calendar.timegm`, `struct`, `fractions.Fraction`). Certains tests sont
seulement de COHÉRENCE (même résultat par deux chemins du module, parité avec pandas) : ils détectent une dérive, ils ne remplacent
pas un oracle indépendant.
"""
import calendar
import csv
import hashlib
import io
import json
import random
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import gate_v_frame_digest as fd

ROOT = Path(__file__).resolve().parent.parent

# ── Vecteurs R9 (littéraux ; ne dépendent ni du module ni du fichier JSON, non versionné) ─────────────────────────────────────
HDR = "time,open,high,low,close,tick_volume,spread\n"
V1_CSV = (HDR + "2025-12-31 23:51:00,100.10,100.30,100.00,100.20,7,180\n2025-12-31 23:54:00,100.20,100.40,100.10,100.30,9,180\n"
          "2025-12-31 23:57:00,100.30,100.50,100.20,100.40,11,180\n")
V2_CSV = (HDR + "2025-12-31 23:54:00,100.20,100.40,100.10,100.30,9,180\n2025-12-31 23:57:00,100.30,100.50,100.20,100.40,11,180\n"
          "2026-01-01 00:00:00,100.40,100.60,100.30,100.50,13,180\n")
V3_CSV = (HDR + "2025-12-31 23:52:00,100.10,100.30,100.00,100.20,7,180\n2025-12-31 23:55:00,100.20,100.40,100.10,100.30,9,180\n"
          "2025-12-31 23:58:00,100.30,100.50,100.20,100.40,11,180\n")
VECTORS = {
    "V1": {"csv": V1_CSV, "source_sha256": "8d43f5576f03a0f39ab24409ae9d12152a8a49ab9d48e4af3f1e2e83b8d7dea6", "size": 207, "frame_sha256": "cf582fa6884fc5ab0bfae6bd62b126c1ee669ca5ed74d110ce76ca4c475185c7",
           "first": "2025-12-31T23:51:00.000000Z", "last": "2025-12-31T23:57:00.000000Z", "close": "2026-01-01T00:00:00.000000Z"},
    "V2": {"csv": V2_CSV, "source_sha256": "7d4b35790084c947faa0a1fc465dbdffbedab8c281c613951ddeec911b3ffdc9", "frame_sha256": "974c02e2a8c17ff3aaebad024481e7d35bb364bb481a47bad3c936df38381f4a",
           "first": "2025-12-31T23:54:00.000000Z", "last": "2026-01-01T00:00:00.000000Z", "close": "2026-01-01T00:03:00.000000Z"},
    "V3": {"csv": V3_CSV, "source_sha256": "51d0e06acd720cc1c90f938e935fea940271448d1c8ff0df35f818650c588486", "frame_sha256": "3ea4ae8ea57b37dc9f74ce0c8ea3b2c2daa4b092c1effbeabc523a3095a0bb0d",
           "first": "2025-12-31T23:52:00.000000Z", "last": "2025-12-31T23:58:00.000000Z", "close": "2026-01-01T00:01:00.000000Z"},
}
COLUMNS_V = [{"kind": "time_us", "name": "time"}, {"kind": "f64", "name": "open"}, {"kind": "f64", "name": "high"},
             {"kind": "f64", "name": "low"}, {"kind": "f64", "name": "close"}, {"kind": "i64", "name": "tick_volume"},
             {"kind": "i64", "name": "spread"}]


# ── Oracle indépendant (primitives différentes de celles du module) ───────────────────────────────────────────────────────────
def oracle_us(text):
    y, mo, d = int(text[0:4]), int(text[5:7]), int(text[8:10])
    h, mi, s = int(text[11:13]), int(text[14:16]), int(text[17:19])
    return calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0)) * 1_000_000


def oracle_sha256(csv_text):
    """Préimage R9 3.2 recalculée à la main : en-tête JSON compact, puis, par colonne, nom, longueur, valeurs big-endian."""
    rows = list(csv.reader(io.StringIO(csv_text, newline="")))
    head, body = rows[0], rows[1:]
    n = len(body)
    blobs, spec = [], []
    for j, name in enumerate(head):
        cells = [r[j] for r in body]
        if name == "time":
            vals = [oracle_us(c) for c in cells]
            spec.append((name, "time_us"))
            blobs.append(b"".join(v.to_bytes(8, "big", signed=True) for v in vals))
        elif all(c.lstrip("+-").isdigit() for c in cells):
            spec.append((name, "i64"))
            blobs.append(b"".join(int(c).to_bytes(8, "big", signed=True) for c in cells))
        else:
            spec.append((name, "f64"))
            blobs.append(b"".join(bytes.fromhex("%016x" % struct.unpack(">Q", struct.pack(">d", float(c)))[0]) for c in cells))
    header = json.dumps({"columns": [{"kind": k, "name": nm} for nm, k in spec], "row_count": n}, sort_keys=True,
                        separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    h = hashlib.sha256()
    h.update(b"gate_v_frame_digest_v1\n" + header + b"\n")
    for (nm, _k), blob in zip(spec, blobs):
        h.update(b"column:" + nm.encode("utf-8") + b"\n" + (8 * n).to_bytes(8, "big") + blob)
    return h.hexdigest()


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ══ Tranche 1 : empreinte de trame de référence (vecteurs R9) ═════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("key", ["V1", "V2", "V3"])
def test_frame_digest_of_csv_bytes_matches_the_r9_vector_literal(key):
    v = VECTORS[key]
    columns = fd.columns_from_csv_bytes(v["csv"].encode("utf-8"))
    assert fd.compute_frame_digest(columns) == v["frame_sha256"]


@pytest.mark.parametrize("key", ["V1", "V2", "V3"])
def test_oracle_agrees_with_the_r9_vector_literals(key):
    """Le test d'oracle lui-même doit être juste, sinon il ne prouve rien (anti-tautologie)."""
    assert oracle_sha256(VECTORS[key]["csv"]) == VECTORS[key]["frame_sha256"]
    assert sha(VECTORS[key]["csv"].encode("utf-8")) == VECTORS[key]["source_sha256"]


def test_frame_digest_of_explicit_typed_columns_matches_the_vector():
    """Entrées explicites et typées : le calcul ne dépend pas du texte CSV."""
    columns = (
        fd.FrameColumn("time", "time_us", tuple(oracle_us(t) for t in ("2025-12-31 23:51:00", "2025-12-31 23:54:00", "2025-12-31 23:57:00"))),
        fd.FrameColumn("open", "f64", (100.10, 100.20, 100.30)), fd.FrameColumn("high", "f64", (100.30, 100.40, 100.50)),
        fd.FrameColumn("low", "f64", (100.00, 100.10, 100.20)), fd.FrameColumn("close", "f64", (100.20, 100.30, 100.40)),
        fd.FrameColumn("tick_volume", "i64", (7, 9, 11)), fd.FrameColumn("spread", "i64", (180, 180, 180)),
    )
    assert fd.compute_frame_digest(columns) == VECTORS["V1"]["frame_sha256"]


def test_same_input_gives_the_same_digest_and_a_fresh_interpreter_agrees():
    raw = V1_CSV.encode("utf-8")
    first = fd.compute_frame_digest(fd.columns_from_csv_bytes(raw))
    assert first == fd.compute_frame_digest(fd.columns_from_csv_bytes(raw))
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import gate_v_frame_digest as m; "
            "print(m.compute_frame_digest(m.columns_from_csv_bytes(sys.stdin.buffer.read())))")
    out = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT)], input=raw, capture_output=True, check=True).stdout.decode().strip()
    assert out == first


# ══ Tranche 2 : sensibilité de l'empreinte et refus des entrées explicites ═════════════════════════════════════════════════════
def _v1_columns():
    return list(fd.columns_from_csv_bytes(V1_CSV.encode("utf-8")))


def _replace(columns, target, **changes):
    out = []
    for c in columns:
        if c.name == target:
            c = fd.FrameColumn(changes.get("name", c.name), changes.get("kind", c.kind), changes.get("values", c.values))
        out.append(c)
    return tuple(out)


BASE_DIGEST = VECTORS["V1"]["frame_sha256"]


def test_one_changed_value_changes_the_digest():
    changed = _replace(_v1_columns(), "close", values=(100.20, 100.30, 100.41))
    assert fd.compute_frame_digest(changed) != BASE_DIGEST


def test_changing_the_last_bit_of_a_float_changes_the_digest():
    value = 100.20
    neighbour = struct.unpack(">d", (struct.unpack(">Q", struct.pack(">d", value))[0] + 1).to_bytes(8, "big"))[0]
    assert neighbour != value
    changed = _replace(_v1_columns(), "close", values=(value, 100.30, 100.40))
    nudged = _replace(_v1_columns(), "close", values=(neighbour, 100.30, 100.40))
    assert fd.compute_frame_digest(changed) != fd.compute_frame_digest(nudged)


def test_a_changed_timestamp_changes_the_digest():
    times = list(next(c for c in _v1_columns() if c.name == "time").values)
    times[1] += 1  # une microseconde
    assert fd.compute_frame_digest(_replace(_v1_columns(), "time", values=tuple(times))) != BASE_DIGEST


def test_adding_or_removing_a_row_changes_the_digest():
    cols = _v1_columns()
    shorter = tuple(fd.FrameColumn(c.name, c.kind, c.values[:-1]) for c in cols)
    longer = tuple(fd.FrameColumn(c.name, c.kind, c.values + (c.values[-1],)) for c in cols)
    digests = {BASE_DIGEST, fd.compute_frame_digest(shorter), fd.compute_frame_digest(longer)}
    assert len(digests) == 3


def test_permuted_columns_change_the_digest():
    cols = _v1_columns()
    swapped = (cols[0], cols[2], cols[1]) + tuple(cols[3:])
    assert fd.compute_frame_digest(swapped) != BASE_DIGEST


def test_reordered_rows_change_the_digest():
    order = (2, 0, 1)
    shuffled = tuple(fd.FrameColumn(c.name, c.kind, tuple(c.values[i] for i in order)) for c in _v1_columns())
    assert fd.compute_frame_digest(shuffled) != BASE_DIGEST


def test_a_diverging_column_kind_changes_the_digest():
    as_float = _replace(_v1_columns(), "spread", kind="f64", values=(180.0, 180.0, 180.0))
    assert fd.compute_frame_digest(as_float) != BASE_DIGEST


def test_a_renamed_column_changes_the_digest():
    assert fd.compute_frame_digest(_replace(_v1_columns(), "spread", name="spread2")) != BASE_DIGEST


def test_negative_zero_is_a_distinct_value_from_positive_zero():
    """Décision L1 (R9 muette) : les 64 bits IEEE sont l'identité ; -0.0 et 0.0 ne sont pas confondus."""
    zero = _replace(_v1_columns(), "low", values=(0.0, 100.10, 100.20))
    minus = _replace(_v1_columns(), "low", values=(-0.0, 100.10, 100.20))
    assert fd.compute_frame_digest(zero) != fd.compute_frame_digest(minus)


def test_float_columns_are_hashed_as_their_exact_ieee_bits():
    cols = (fd.FrameColumn("time", "time_us", (0, 180_000_000)), fd.FrameColumn("x", "f64", (5e-324, 1.7976931348623157e308)))
    expected = oracle_frame_sha256_columns([("time", "time_us", (0, 180_000_000)), ("x", "f64", (5e-324, 1.7976931348623157e308))])
    assert fd.compute_frame_digest(cols) == expected


def oracle_frame_sha256_columns(spec):
    n = len(spec[0][2])
    h = hashlib.sha256()
    header = json.dumps({"columns": [{"kind": k, "name": nm} for nm, k, _ in spec], "row_count": n}, sort_keys=True,
                        separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    h.update(b"gate_v_frame_digest_v1\n" + header + b"\n")
    for nm, k, vals in spec:
        blob = b"".join((struct.pack(">d", v) if k == "f64" else int(v).to_bytes(8, "big", signed=True)) for v in vals)
        h.update(b"column:" + nm.encode("utf-8") + b"\n" + (8 * n).to_bytes(8, "big") + blob)
    return h.hexdigest()


def test_random_frames_agree_with_the_independent_oracle():
    rng = random.Random(20261024)
    for _ in range(25):
        n = rng.randint(1, 40)
        t = tuple(sorted(rng.sample(range(0, 10**12, 180_000_000), n)))
        spec = [("time", "time_us", t), ("a", "f64", tuple(rng.uniform(-1e6, 1e6) for _ in range(n))),
                ("b", "i64", tuple(rng.randint(-2**63, 2**63 - 1) for _ in range(n)))]
        cols = tuple(fd.FrameColumn(nm, k, v) for nm, k, v in spec)
        assert fd.compute_frame_digest(cols) == oracle_frame_sha256_columns(spec)


def _refused(columns, code):
    with pytest.raises(fd.FrameRefused) as info:
        fd.compute_frame_digest(columns)
    assert info.value.code is code


def test_every_refusal_carries_a_code_from_the_closed_vocabulary():
    assert {c.value for c in fd.FrameRefusal} >= {"EMPTY", "NO_TIME_COLUMN", "COLUMN_LENGTH", "DUPLICATE_COLUMN", "BAD_COLUMN", "BAD_VALUE",
                                                  "NON_FINITE", "INT_RANGE"}


def test_refuses_no_columns_and_zero_rows():
    _refused((), fd.FrameRefusal.EMPTY)
    _refused((fd.FrameColumn("time", "time_us", ()),), fd.FrameRefusal.EMPTY)


def test_refuses_a_frame_without_exactly_one_time_us_column():
    _refused((fd.FrameColumn("a", "f64", (1.0,)),), fd.FrameRefusal.NO_TIME_COLUMN)
    _refused((fd.FrameColumn("time", "f64", (1.0,)),), fd.FrameRefusal.NO_TIME_COLUMN)
    _refused((fd.FrameColumn("when", "time_us", (1,)),), fd.FrameRefusal.NO_TIME_COLUMN)


def test_refuses_columns_of_different_lengths_and_duplicate_names():
    _refused((fd.FrameColumn("time", "time_us", (1, 2)), fd.FrameColumn("a", "i64", (1,))), fd.FrameRefusal.COLUMN_LENGTH)
    _refused((fd.FrameColumn("time", "time_us", (1,)), fd.FrameColumn("a", "i64", (1,)), fd.FrameColumn("a", "i64", (2,))),
             fd.FrameRefusal.DUPLICATE_COLUMN)


@pytest.mark.parametrize("name", ["", " ", "a\nb", "a\x00b", "tab\tname", 3, None])
def test_refuses_unusable_column_names(name):
    _refused((fd.FrameColumn("time", "time_us", (1,)), fd.FrameColumn(name, "i64", (1,))), fd.FrameRefusal.BAD_COLUMN)


def test_a_column_name_that_is_not_encodable_in_utf8_is_a_typed_refusal_not_a_raw_exception():
    """Défaut trouvé par sondage : un substitut Unicode isolé levait UnicodeEncodeError (exception non typée) au lieu de FrameRefused."""
    _refused((fd.FrameColumn("time", "time_us", (1,)), fd.FrameColumn("a" + chr(0xD800), "i64", (1,))), fd.FrameRefusal.BAD_COLUMN)


def test_refuses_an_unknown_kind_and_non_tuple_values():
    _refused((fd.FrameColumn("time", "time_us", (1,)), fd.FrameColumn("a", "f32", (1.0,))), fd.FrameRefusal.BAD_COLUMN)
    _refused((fd.FrameColumn("time", "time_us", [1]),), fd.FrameRefusal.BAD_COLUMN)
    _refused(("not a column",), fd.FrameRefusal.BAD_COLUMN)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_refuses_non_finite_floats(value):
    _refused((fd.FrameColumn("time", "time_us", (1,)), fd.FrameColumn("a", "f64", (value,))), fd.FrameRefusal.NON_FINITE)


@pytest.mark.parametrize("kind,value", [("f64", 1), ("f64", True), ("f64", "1.0"), ("i64", 1.0), ("i64", True), ("i64", "1"), ("i64", None)])
def test_refuses_values_whose_python_type_is_not_exactly_the_column_kind(kind, value):
    _refused((fd.FrameColumn("time", "time_us", (1,)), fd.FrameColumn("a", kind, (value,))), fd.FrameRefusal.BAD_VALUE)


@pytest.mark.parametrize("value", [2**63, -2**63 - 1, 10**30])
def test_refuses_integers_outside_int64_for_i64_and_time_us(value):
    _refused((fd.FrameColumn("time", "time_us", (1,)), fd.FrameColumn("a", "i64", (value,))), fd.FrameRefusal.INT_RANGE)
    _refused((fd.FrameColumn("time", "time_us", (value,)),), fd.FrameRefusal.INT_RANGE)


def test_non_ascii_column_names_are_hashed_as_utf8_and_json_is_not_ascii_escaped():
    spec = [("time", "time_us", (0, 180_000_000)), ("prix_é€", "f64", (1.5, 2.5))]
    cols = tuple(fd.FrameColumn(*s) for s in spec)
    assert fd.compute_frame_digest(cols) == oracle_frame_sha256_columns(spec)
    ascii_escaped = hashlib.sha256(b"x").hexdigest()  # garde-fou : l'oracle ne doit pas être trivial
    assert fd.compute_frame_digest(cols) != ascii_escaped


def test_a_second_time_us_column_is_refused_even_under_another_name():
    cols = (fd.FrameColumn("time", "time_us", (0, 180_000_000)), fd.FrameColumn("when", "time_us", (0, 180_000_000)))
    _refused(cols, fd.FrameRefusal.NO_TIME_COLUMN)


def test_accepts_the_int64_bounds():
    cols = (fd.FrameColumn("time", "time_us", (-2**63, 2**63 - 1)), fd.FrameColumn("a", "i64", (-2**63, 2**63 - 1)))
    assert fd.compute_frame_digest(cols) == oracle_frame_sha256_columns([("time", "time_us", (-2**63, 2**63 - 1)), ("a", "i64", (-2**63, 2**63 - 1))])


# ══ Tranche 3 : grammaire CSV, dialecte, texte des temps et des nombres ═════════════════════════════════════════════════════════
def _csv(*rows, header="time,x", eol="\n", final=True):
    text = eol.join([header, *rows]) + (eol if final else "")
    return text.encode("utf-8")


def _csv_refused(raw, code):
    with pytest.raises(fd.FrameRefused) as info:
        fd.columns_from_csv_bytes(raw)
    assert info.value.code is code


R = fd.FrameRefusal


def test_crlf_and_lf_files_give_the_same_digest_and_mixed_endings_are_accepted():
    lf = fd.compute_frame_digest(fd.columns_from_csv_bytes(V1_CSV.encode()))
    crlf = fd.compute_frame_digest(fd.columns_from_csv_bytes(V1_CSV.replace("\n", "\r\n").encode()))
    lines = V1_CSV.split("\n")
    mixed = (lines[0] + "\r\n" + lines[1] + "\n" + lines[2] + "\r\n" + lines[3] + "\n").encode()
    assert lf == crlf == fd.compute_frame_digest(fd.columns_from_csv_bytes(mixed)) == VECTORS["V1"]["frame_sha256"]


@pytest.mark.parametrize("raw,code", [
    (b"", R.EMPTY),
    (b"time,x\n", R.EMPTY),
    (b"\xef\xbb\xbftime,x\n2025-01-01 00:00:00,1\n", R.BOM),
    (b"time,x\n2025-01-01 00:00:00,\xff\n", R.NOT_UTF8),
    (b"time,x\n2025-01-01 00:00:00,1", R.CSV_DIALECT),                      # pas de fin de ligne finale
    (b"time,x\n2025-01-01 00:00:00,1\n\n", R.CSV_DIALECT),                   # ligne vide finale
    (b"time,x\n\n2025-01-01 00:00:00,1\n", R.CSV_DIALECT),                   # ligne vide au milieu
    (b"time,x\r2025-01-01 00:00:00,1\r", R.CSV_DIALECT),                     # CR isolé
    (b"time,x\n2025-01-01 00:00:00,1,9\n", R.CSV_RAGGED),
    (b"time,x\n2025-01-01 00:00:00\n", R.CSV_RAGGED),
    (b'time,x\n2025-01-01 00:00:00,"1\n', R.CSV_DIALECT),                    # guillemet non fermé
    (b"x,y\n1,2\n", R.NO_TIME_COLUMN),
    (b"time,time\n2025-01-01 00:00:00,2025-01-01 00:03:00\n", R.DUPLICATE_COLUMN),
    (b"time,x,x\n2025-01-01 00:00:00,1,2\n", R.DUPLICATE_COLUMN),
    (b"time,\n2025-01-01 00:00:00,1\n", R.BAD_COLUMN),
])
def test_csv_dialect_and_structure_are_refused_with_an_exact_code(raw, code):
    _csv_refused(raw, code)


@pytest.mark.parametrize("cell", [
    "2025-01-01T00:00:00", "2025-01-01 00:00:00Z", "2025-01-01 00:00:00+01:00", "2025-01-01 00:00:00.5", "2025-01-01",
    "2025-02-30 00:00:00", "2025-13-01 00:00:00", "2025-01-01 24:00:00", "2025-01-01 23:59:60", "2025-1-1 00:00:00",
    " 2025-01-01 00:00:00", "2025-01-01 00:00:00 ", "0000-01-01 00:00:00", "２０２５-01-01 00:00:00", "", "1735689600",
])
def test_only_the_naive_second_precision_time_format_is_accepted(cell):
    _csv_refused(_csv(cell + ",1"), R.TIME_FORMAT if cell else R.MISSING_VALUE)


def test_time_values_are_microseconds_since_the_epoch_for_naive_utc_text():
    cols = fd.columns_from_csv_bytes(_csv("1969-12-31 23:59:59,1", "1970-01-01 00:00:00,2", "2000-02-29 12:00:01,3"))
    assert cols[0].values == (-1_000_000, 0, oracle_us("2000-02-29 12:00:01"))


@pytest.mark.parametrize("cell,value", [
    ("1", 1.0), ("1.5", 1.5), ("-0.0", -0.0), ("+1.5", 1.5), (".5", 0.5), ("5.", 5.0), ("1e3", 1000.0), ("1E-3", 0.001),
    ("-1.5e+10", -1.5e10), ("5e-324", 5e-324), ("1.7976931348623157e308", 1.7976931348623157e308), ("0.1", 0.1),
])
def test_float_text_grammar_accepted_values_are_exactly_python_float(cell, value):
    column = fd.columns_from_csv_bytes(_csv("2025-01-01 00:00:00," + cell, "2025-01-01 00:03:00,2.5"))[1]
    assert column.kind == "f64"
    assert struct.pack(">d", column.values[0]) == struct.pack(">d", value)  # y compris le signe du zéro


@pytest.mark.parametrize("cell,code", [
    ("nan", R.NON_FINITE), ("NaN", R.NON_FINITE), ("inf", R.NON_FINITE), ("-inf", R.NON_FINITE), ("infinity", R.NON_FINITE),
    ("1e999", R.NON_FINITE), ("-1e999", R.NON_FINITE),
    ("1_0.5", R.FLOAT_TEXT), (" 1.5", R.FLOAT_TEXT), ("1.5 ", R.FLOAT_TEXT), ("0x10", R.FLOAT_TEXT), ("--1", R.FLOAT_TEXT),
    ("1.5.2", R.FLOAT_TEXT), ("１.５", R.FLOAT_TEXT), ("abc", R.FLOAT_TEXT), ("1e", R.FLOAT_TEXT), ("e5", R.FLOAT_TEXT), (".", R.FLOAT_TEXT),
    ("", R.MISSING_VALUE),
])
def test_float_text_outside_the_strict_grammar_or_non_finite_is_refused(cell, code):
    _csv_refused(_csv("2025-01-01 00:00:00,2.5", "2025-01-01 00:03:00," + cell), code)


@pytest.mark.parametrize("cell,value", [("+5", 5), ("007", 7), ("-0", 0), ("9223372036854775807", 2**63 - 1), ("-9223372036854775808", -2**63)])
def test_integer_text_inside_int64_is_an_i64_column(cell, value):
    column = fd.columns_from_csv_bytes(_csv("2025-01-01 00:00:00," + cell, "2025-01-01 00:03:00,1"))[1]
    assert (column.kind, column.values[0]) == ("i64", value) and type(column.values[0]) is int


@pytest.mark.parametrize("cell", ["9223372036854775808", "-9223372036854775809", "99999999999999999999"])
def test_integer_text_outside_int64_is_refused_not_silently_widened_to_float(cell):
    """Choix L1 plus strict que la lettre de R9 3.2 (« sinon f64 ») : jamais de perte de précision silencieuse."""
    _csv_refused(_csv("2025-01-01 00:00:00,1", "2025-01-01 00:03:00," + cell), R.INT_RANGE)


def test_a_column_mixing_integer_and_decimal_text_is_f64():
    column = fd.columns_from_csv_bytes(_csv("2025-01-01 00:00:00,100", "2025-01-01 00:03:00,100.5"))[1]
    assert column.kind == "f64" and column.values == (100.0, 100.5)


def test_quoted_cells_follow_rfc4180_and_do_not_change_the_digest():
    quoted = V1_CSV.replace("100.10", '"100.10"').replace("time,open", '"time",open')
    assert fd.compute_frame_digest(fd.columns_from_csv_bytes(quoted.encode())) == VECTORS["V1"]["frame_sha256"]


def test_the_time_column_may_sit_anywhere_in_the_header():
    raw = b"x,time\n1,2025-01-01 00:00:00\n2,2025-01-01 00:03:00\n"
    cols = fd.columns_from_csv_bytes(raw)
    assert [c.name for c in cols] == ["x", "time"] and cols[1].kind == "time_us"


# ══ Tranche 4 : faits de trame — bornes, durée de barre DÉCLARÉE, frontières ════════════════════════════════════════════════════
FRAME_RECORD_KEYS = {"frame_digest_version", "frame_sha256", "row_count", "columns", "bar_duration_seconds", "first_open_utc", "last_open_utc",
                     "last_close_utc_exclusive", "time_semantics"}


def _facts(csv_text, bar=180):
    return fd.compute_frame_facts(fd.columns_from_csv_bytes(csv_text.encode()), bar)


@pytest.mark.parametrize("key", ["V1", "V2", "V3"])
def test_frame_facts_match_the_r9_vector_literals(key):
    v = VECTORS[key]
    record = _facts(v["csv"]).to_record()
    assert set(record) == FRAME_RECORD_KEYS
    assert record["frame_sha256"] == v["frame_sha256"]
    assert (record["first_open_utc"], record["last_open_utc"], record["last_close_utc_exclusive"]) == (v["first"], v["last"], v["close"])
    assert (record["row_count"], record["bar_duration_seconds"]) == (3, 180)
    assert record["columns"] == COLUMNS_V
    assert (record["frame_digest_version"], record["time_semantics"]) == ("gate_v_frame_digest_v1", "naive_utc_declared")


def test_the_last_bar_closing_exactly_on_a_boundary_has_that_boundary_as_exclusive_close():
    assert _facts(V1_CSV).last_close_utc_exclusive == "2026-01-01T00:00:00.000000Z"
    assert _facts(V2_CSV).last_close_utc_exclusive == "2026-01-01T00:03:00.000000Z"  # une barre ouverte à la frontière la dépasse
    assert _facts(V3_CSV).last_close_utc_exclusive == "2026-01-01T00:01:00.000000Z"  # la dernière barre chevauche la frontière


def test_facts_expose_no_verdict_field():
    names = {f for f in fd.FrameFacts.__dataclass_fields__} | set(_facts(V1_CSV).to_record())
    assert not [n for n in names if any(w in n.lower() for w in ("verdict", "fresh", "overlap", "exposed", "admiss", "claim"))]


def _times(*seconds, base="2025-01-01 00:00:00"):
    b = oracle_us(base)
    return (fd.FrameColumn("time", "time_us", tuple(b + s * 1_000_000 for s in seconds)),)


def _fact_refused(columns, bar, code):
    with pytest.raises(fd.FrameRefused) as info:
        fd.compute_frame_facts(columns, bar)
    assert info.value.code is code


def test_missing_bars_are_accepted_as_multiples_of_the_declared_duration():
    facts = fd.compute_frame_facts(_times(0, 180, 360, 360 + 180 * 960), 180)  # trou de fin de semaine
    assert facts.bar_duration_seconds == 180 and facts.row_count == 4


@pytest.mark.parametrize("bar", [0, -180, 180.0, "180", True, None])
def test_the_declared_bar_duration_must_be_a_positive_python_int(bar):
    _fact_refused(_times(0, 180), bar, fd.FrameRefusal.BAD_BAR)


def test_a_measured_minimum_gap_different_from_the_declared_duration_is_refused():
    """Défaut D2 de la revue R9 : des écarts de 60 s mêlés à des barres de 180 s ne doivent pas redéfinir la barre."""
    mixed = _times(0, 60, 240, 420, 540)  # 60, 180, 180, 120
    _fact_refused(mixed, 180, fd.FrameRefusal.BAR_DURATION_MISMATCH)
    _fact_refused(_times(0, 180, 360), 60, fd.FrameRefusal.BAR_DURATION_MISMATCH)  # barre déclarée plus courte que la grille mesurée


def test_a_gap_that_is_not_a_multiple_of_the_declared_duration_is_refused():
    _fact_refused(_times(0, 180, 450), 180, fd.FrameRefusal.BAR_GRID)


def test_duplicate_or_unordered_timestamps_are_refused():
    _fact_refused(_times(0, 180, 180), 180, fd.FrameRefusal.NOT_STRICTLY_INCREASING)
    _fact_refused(_times(0, 360, 180), 180, fd.FrameRefusal.NOT_STRICTLY_INCREASING)


def test_a_single_row_has_no_measurable_bar_and_is_refused():
    _fact_refused(_times(0), 180, fd.FrameRefusal.TOO_FEW_ROWS)


def test_sub_second_gaps_are_refused_but_a_constant_sub_second_offset_is_kept_in_the_instants():
    cols = (fd.FrameColumn("time", "time_us", (0, 1_500_000)),)
    _fact_refused(cols, 1, fd.FrameRefusal.SUB_SECOND)
    shifted = (fd.FrameColumn("time", "time_us", (500_000, 180_500_000)),)
    facts = fd.compute_frame_facts(shifted, 180)
    assert (facts.first_open_utc, facts.last_close_utc_exclusive) == ("1970-01-01T00:00:00.500000Z", "1970-01-01T00:06:00.500000Z")


def test_instants_before_the_epoch_and_on_leap_days_are_exact():
    before = fd.compute_frame_facts((fd.FrameColumn("time", "time_us", (-180_000_000, 0)),), 180)
    assert (before.first_open_utc, before.last_close_utc_exclusive) == ("1969-12-31T23:57:00.000000Z", "1970-01-01T00:03:00.000000Z")
    leap = fd.compute_frame_facts(_times(0, 180, base="2024-02-29 23:57:00"), 180)
    assert (leap.first_open_utc, leap.last_close_utc_exclusive) == ("2024-02-29T23:57:00.000000Z", "2024-03-01T00:03:00.000000Z")


def test_instants_outside_the_representable_calendar_are_refused():
    edge = oracle_us("9999-12-31 23:59:00")
    _fact_refused((fd.FrameColumn("time", "time_us", (edge - 180_000_000, edge)),), 180, fd.FrameRefusal.TIME_RANGE)
    _fact_refused((fd.FrameColumn("time", "time_us", (-2**63, -2**63 + 180_000_000)),), 180, fd.FrameRefusal.TIME_RANGE)


def test_facts_refuse_an_invalid_frame_before_computing_anything():
    _fact_refused((), 180, fd.FrameRefusal.EMPTY)
    _fact_refused((fd.FrameColumn("time", "time_us", (0, 180_000_000)), fd.FrameColumn("a", "f64", (float("nan"), 1.0))), 180, fd.FrameRefusal.NON_FINITE)


def test_facts_digest_equals_the_standalone_digest():
    cols = fd.columns_from_csv_bytes(V1_CSV.encode())
    assert fd.compute_frame_facts(cols, 180).frame_sha256 == fd.compute_frame_digest(cols)


# ══ Tranche 5 : faits S0 — octets bruts du snapshot ≠ trame décodée ═══════════════════════════════════════════════════════════
S0_FACTS_SHA256_V1 = "cdcdcde70f0316be82734b9d35027ddbb87f21e05ce9c53f58ae7c22de7cb6c3"


def normative_bytes(obj):
    """Octets normatifs (ADR 0025 23.29.4), recalculés ici : clés triées, indent=2, LF final."""
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


@pytest.mark.parametrize("key", ["V1", "V2", "V3"])
def test_s0_facts_distinguish_the_raw_bytes_hash_from_the_frame_digest(key):
    v = VECTORS[key]
    facts = fd.compute_s0_frame_facts(v["csv"].encode(), 180)
    assert facts.source_sha256 == v["source_sha256"] == sha(v["csv"].encode())
    assert facts.dataset_snapshot_id == "local_csv:sha256:" + v["source_sha256"]
    assert facts.source_size_bytes == len(v["csv"].encode())
    assert facts.frame.frame_sha256 == v["frame_sha256"] != facts.source_sha256


def test_s0_facts_record_matches_the_r9_vector_hash():
    record = fd.compute_s0_frame_facts(V1_CSV.encode(), 180).to_record()
    assert set(record) == {"source_sha256", "source_size_bytes", "dataset_snapshot_id", "frame"}
    assert record["source_size_bytes"] == VECTORS["V1"]["size"] == 207
    assert sha(normative_bytes(record)) == S0_FACTS_SHA256_V1


def _no_float(value):
    if isinstance(value, dict):
        return all(_no_float(v) for v in value.values())
    if isinstance(value, list):
        return all(_no_float(v) for v in value)
    return type(value) is not float


def test_records_contain_no_float_and_survive_a_json_round_trip():
    record = fd.compute_s0_frame_facts(V1_CSV.encode(), 180).to_record()
    assert _no_float(record) and json.loads(json.dumps(record, allow_nan=False)) == record


def test_different_bytes_with_the_same_decoded_frame_share_the_digest_but_not_the_source_hash():
    """Même trame décodée, octets différents (fins de ligne, zéros finaux, guillemets, signe +) : deux identités distinctes."""
    variants = [V1_CSV.replace("\n", "\r\n"), V1_CSV.replace("100.10", "100.1000"), V1_CSV.replace("100.10", '"100.10"'), V1_CSV.replace(",180\n", ",+180\n")]
    base = fd.compute_s0_frame_facts(V1_CSV.encode(), 180)
    for text in variants:
        facts = fd.compute_s0_frame_facts(text.encode(), 180)
        assert facts.frame.frame_sha256 == base.frame.frame_sha256
        assert facts.source_sha256 != base.source_sha256 and facts.dataset_snapshot_id != base.dataset_snapshot_id


@pytest.mark.parametrize("a,b", [("100.0", "100.00"), ("100.0", "1e2"), ("1.5", "+1.5"), ("0.1", "1e-1"), ("-0.0", "-0.00")])
def test_textual_forms_of_the_same_float_hash_identically(a, b):
    def digest(cell):
        return fd.compute_frame_digest(fd.columns_from_csv_bytes(_csv("2025-01-01 00:00:00," + cell, "2025-01-01 00:03:00,2.5")))
    assert digest(a) == digest(b)


def test_integer_text_and_decimal_text_of_equal_value_have_different_kinds_hence_different_digests():
    """Le kind est inféré du TEXTE du fichier (R9 3.2) : `100` (i64) et `100.0` (f64) sont deux colonnes de types différents."""
    as_int = fd.compute_frame_digest(fd.columns_from_csv_bytes(_csv("2025-01-01 00:00:00,100", "2025-01-01 00:03:00,101")))
    as_float = fd.compute_frame_digest(fd.columns_from_csv_bytes(_csv("2025-01-01 00:00:00,100.0", "2025-01-01 00:03:00,101")))
    assert as_int != as_float


# ══ Tranche 6 : parité avec pandas (adaptateur de TEST), défaut du parseur par défaut, flottants difficiles ═══════════════════════
from fractions import Fraction  # noqa: E402

import pandas as pd  # noqa: E402  (pandas n'est importé que par les tests : le module de production n'en dépend pas)


def columns_from_dataframe(df):
    """Adaptateur de TEST (R9 3.2, correspondance trame → kind) : datetime64 naïf → time_us (refus si un ns n'est pas multiple de 1 µs),
    int64 → i64, float64 → f64 ; tout autre dtype est refusé."""
    out = []
    for name in df.columns:
        s = df[name]
        if name == "time":
            if getattr(s.dt, "tz", None) is not None:
                raise TypeError("datetime avec fuseau refusé")
            ns = s.astype("datetime64[ns]").astype("int64")
            if (ns % 1000 != 0).any():
                raise TypeError("précision sub-microseconde refusée")
            out.append(fd.FrameColumn("time", "time_us", tuple(int(v) for v in (ns // 1000).tolist())))
        elif str(s.dtype) == "int64":
            out.append(fd.FrameColumn(name, "i64", tuple(int(v) for v in s.tolist())))
        elif str(s.dtype) == "float64":
            out.append(fd.FrameColumn(name, "f64", tuple(float(v) for v in s.tolist())))
        else:
            raise TypeError(f"dtype refusé : {s.dtype}")
    return tuple(out)


def pandas_digest(raw, **kwargs):
    return fd.compute_frame_digest(columns_from_dataframe(pd.read_csv(io.BytesIO(raw), parse_dates=["time"], **kwargs)))


@pytest.mark.parametrize("key", ["V1", "V2", "V3"])
def test_pandas_round_trip_frame_has_the_same_digest_as_the_pure_decoder(key):
    raw = VECTORS[key]["csv"].encode()
    assert pandas_digest(raw, float_precision="round_trip") == VECTORS[key]["frame_sha256"] == fd.compute_frame_digest(fd.columns_from_csv_bytes(raw))


HARD_FLOATS = [
    "0.1", "0.2", "0.30000000000000004", "1.0000000000000002", "1.00000000000000011102230246251565404236316680908203125",  # égalité exacte → pair
    "0.99999999999999988897769753748434595763683319091796875", "9007199254740993.0", "9007199254740992.5", "123456789.123456789",
    "25972.402815212394", "13555.517785666361", "28942.768675985877", "9789.474283095395",                                   # reproducteurs du défaut
    "5e-324", "2.2250738585072014e-308", "2.225073858507201e-308", "1.7976931348623157e308", "4.9e-324", "1e-400",
    "1e22", "1e23", "8.41e21", "-0.0", "0.0", "-1.5e-7", "123456789012345678901234567890.0", "0.000000000000000000000000000001",
]


def _fraction_oracle(text):
    """Arrondi correct au plus proche (pair en cas d'égalité) par une voie indépendante de float(str) : float(Fraction)."""
    magnitude = float(Fraction(text.lstrip("+-")))
    return -magnitude if text.startswith("-") else magnitude  # le signe vient du texte : Fraction ignore -0


@pytest.mark.parametrize("text", HARD_FLOATS)
def test_hard_decimals_decode_to_the_correctly_rounded_double(text):
    column = fd.columns_from_csv_bytes(_csv("2025-01-01 00:00:00," + text, "2025-01-01 00:03:00,2.5"))[1]
    assert struct.pack(">d", column.values[0]) == struct.pack(">d", _fraction_oracle(text))


def test_pandas_round_trip_agrees_with_the_pure_decoder_on_hard_decimals():
    body = "\n".join(f"2025-01-01 00:{i:02d}:00,{t}" for i, t in enumerate(HARD_FLOATS))
    raw = (f"time,x\n{body}\n").encode()
    assert pandas_digest(raw, float_precision="round_trip") == fd.compute_frame_digest(fd.columns_from_csv_bytes(raw))


@pytest.mark.skipif(pd.__version__ != "3.0.3", reason="caractérisation figée sur pandas 3.0.3 (version du dépôt au 2026-10-24)")
@pytest.mark.parametrize("text,pandas_default", [("25972.402815212394", 25972.402815212397), ("13555.517785666361", 13555.51778566636),
                                                 ("9789.474283095395", 9789.474283095396)])
def test_characterisation_pandas_default_float_parser_is_not_correctly_rounded(text, pandas_default):
    """Défaut R9 démontré : le parseur par défaut de pandas diffère de float() ; seul `round_trip` suit l'arrondi correct. Cette
    divergence ne dit rien d'un fichier réel (prix à 2 décimales) : elle impose que le chargeur V2 fixe `float_precision`."""
    raw = f"time,x\n2025-01-01 00:00:00,{text}\n2025-01-01 00:03:00,2.5\n".encode()
    default_value = pd.read_csv(io.BytesIO(raw))["x"].tolist()[0]
    exact_value = pd.read_csv(io.BytesIO(raw), float_precision="round_trip")["x"].tolist()[0]
    assert default_value == pandas_default != float(text)
    assert exact_value == float(text) == _fraction_oracle(text)
    assert pandas_digest(raw) != fd.compute_frame_digest(fd.columns_from_csv_bytes(raw))  # le digest du défaut ne serait pas celui des octets
    assert pandas_digest(raw, float_precision="round_trip") == fd.compute_frame_digest(fd.columns_from_csv_bytes(raw))


def test_random_synthetic_frames_agree_between_the_pure_decoder_pandas_round_trip_and_the_oracle():
    rng = random.Random(7)
    for trial in range(12):
        n = rng.randint(2, 60)
        lines = ["time,open,volume,flag"]
        t = oracle_us("2024-03-01 00:00:00") // 1_000_000
        for _ in range(n):
            t += 180 * rng.choice([1, 1, 1, 2, 5, 480])
            stamp = "%04d-%02d-%02d %02d:%02d:%02d" % tuple(__import__("time").gmtime(t)[:6])
            price = repr(round(rng.uniform(1, 30000), rng.choice([2, 5, 9, 12, 15])))
            lines.append(f"{stamp},{price},{rng.randint(-5, 10**9)},{rng.randint(0, 1)}")
        raw = ("\n".join(lines) + "\n").encode()
        pure = fd.compute_frame_digest(fd.columns_from_csv_bytes(raw))
        assert pure == pandas_digest(raw, float_precision="round_trip") == oracle_sha256(raw.decode())


# Temps, fuseaux et précision : le module ne connaît QUE du naïf interprété UTC ───────────────────────────────────────────────
def test_timestamp_text_is_read_as_naive_utc_and_a_paris_reading_would_hash_differently():
    """Limite assumée : le module ne peut pas savoir si le texte était de l'heure de Paris ; `time_semantics` le dit (hypothèse
    déclarée, non prouvée, §23.3 F3)."""
    utc = fd.compute_frame_digest(fd.columns_from_csv_bytes(_csv("2025-06-01 12:00:00,1", "2025-06-01 12:03:00,2")))
    paris_as_utc = fd.compute_frame_digest(fd.columns_from_csv_bytes(_csv("2025-06-01 10:00:00,1", "2025-06-01 10:03:00,2")))
    assert utc != paris_as_utc
    assert _facts_of_two().to_record()["time_semantics"] == "naive_utc_declared"


def _facts_of_two():
    return fd.compute_frame_facts(fd.columns_from_csv_bytes(_csv("2025-06-01 12:00:00,1", "2025-06-01 12:03:00,2")), 180)


def test_the_test_adapter_converts_timezone_aware_frames_to_utc_before_hashing_and_refuses_them_otherwise():
    aware = pd.DataFrame({"time": pd.to_datetime(["2025-06-01 14:00:00", "2025-06-01 14:03:00"]).tz_localize("Europe/Paris"), "x": [1, 2]})
    with pytest.raises(TypeError):
        columns_from_dataframe(aware)
    converted = aware.assign(time=aware["time"].dt.tz_convert("UTC").dt.tz_localize(None))
    expected = fd.compute_frame_digest(fd.columns_from_csv_bytes(_csv("2025-06-01 12:00:00,1", "2025-06-01 12:03:00,2")))
    assert fd.compute_frame_digest(columns_from_dataframe(converted)) == expected  # 14:00 Paris (été) = 12:00 UTC


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_pandas_datetime_units_give_the_same_microsecond_values(unit):
    frame = pd.DataFrame({"time": pd.to_datetime(["2025-01-01 00:00:00", "2025-01-01 00:03:00"]).astype(f"datetime64[{unit}]"), "x": [1, 2]})
    assert columns_from_dataframe(frame)[0].values == (oracle_us("2025-01-01 00:00:00"), oracle_us("2025-01-01 00:03:00"))


def test_the_test_adapter_refuses_sub_microsecond_timestamps():
    frame = pd.DataFrame({"time": pd.to_datetime([1735689600000000001, 1735689780000000000], unit="ns"), "x": [1, 2]})
    with pytest.raises(TypeError):
        columns_from_dataframe(frame)


# ══ Tranche 7 : pureté, API publique figée, déterminisme, entrées de mauvais type ═════════════════════════════════════════════════
import ast  # noqa: E402
import builtins  # noqa: E402

MODULE_PATH = ROOT / "gate_v_frame_digest.py"
ALLOWED_IMPORTS = {"__future__", "csv", "dataclasses", "datetime", "enum", "hashlib", "io", "json", "math", "re", "struct"}
FORBIDDEN_NAMES = {"open", "print", "input", "exec", "eval", "compile", "__import__", "globals", "locals", "setattr", "delattr"}


def _module_tree():
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"))


def test_public_api_is_exactly_the_documented_surface():
    assert sorted(fd.__all__) == sorted([
        "FRAME_DIGEST_VERSION", "KIND_F64", "KIND_I64", "KIND_TIME_US", "TIME_COLUMN", "TIME_SEMANTICS", "FrameColumn", "FrameFacts",
        "FrameRefusal", "FrameRefused", "S0FrameFacts", "columns_from_csv_bytes", "compute_frame_digest", "compute_frame_facts",
        "compute_s0_frame_facts"])
    assert all(hasattr(fd, name) for name in fd.__all__)


def test_the_module_imports_only_the_standard_library_subset_and_no_historical_module():
    imported = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= ALLOWED_IMPORTS, imported - ALLOWED_IMPORTS
    assert not imported & {"pandas", "numpy", "os", "sys", "socket", "subprocess", "pathlib", "engine", "walk_forward", "optimizer", "validation_run"}


def test_the_module_calls_no_io_or_dynamic_code_builtin_and_keeps_no_mutable_global_state():
    tree = _module_tree()
    called_names = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not called_names & FORBIDDEN_NAMES, called_names & FORBIDDEN_NAMES
    assert not attributes & {"open", "read_csv", "read_text", "read_bytes", "write_text", "write_bytes", "system", "popen", "urlopen", "connect"}
    for node in tree.body:
        if isinstance(node, ast.Assign) and not any(getattr(t, "id", None) == "__all__" for t in node.targets):  # __all__ : convention
            assert not isinstance(node.value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)), ast.dump(node)[:80]


def test_the_pipeline_works_with_open_and_sockets_disabled(monkeypatch):
    import socket

    def boom(*_a, **_k):
        raise AssertionError("I/O interdit dans la primitive pure")

    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(io, "open", boom)
    monkeypatch.setattr(socket, "socket", boom)
    facts = fd.compute_s0_frame_facts(V1_CSV.encode(), 180)
    assert facts.frame.frame_sha256 == VECTORS["V1"]["frame_sha256"]


def test_digests_do_not_depend_on_the_interpreter_hash_seed():
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import gate_v_frame_digest as m; "
            "print(m.compute_s0_frame_facts(sys.stdin.buffer.read(), 180).frame.frame_sha256)")
    outs = {subprocess.run([sys.executable, "-I", "-c", code, str(ROOT)], input=V3_CSV.encode(), capture_output=True, check=True,
                           env={"PYTHONHASHSEED": seed, "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}).stdout.decode().strip()
            for seed in ("1", "2", "random")}
    assert outs == {VECTORS["V3"]["frame_sha256"]}


def test_columns_are_immutable_and_lists_and_tuples_of_columns_hash_alike():
    cols = fd.columns_from_csv_bytes(V1_CSV.encode())
    with pytest.raises(Exception):
        cols[0].values = ()  # dataclass gelée
    assert fd.compute_frame_digest(list(cols)) == fd.compute_frame_digest(cols) == VECTORS["V1"]["frame_sha256"]


@pytest.mark.parametrize("raw", ["time,x\n2025-01-01 00:00:00,1\n", bytearray(b"time,x\n"), memoryview(b"time,x\n"), None, 12])
def test_csv_input_must_be_exact_bytes(raw):
    with pytest.raises(fd.FrameRefused) as info:
        fd.columns_from_csv_bytes(raw)
    assert info.value.code is fd.FrameRefusal.BAD_COLUMN


def test_a_larger_frame_agrees_between_the_pure_decoder_the_explicit_columns_and_pandas():
    rng = random.Random(99)
    t = oracle_us("2024-01-01 00:00:00") // 1_000_000
    lines = ["time,open,high,tick_volume"]
    for _ in range(20_000):
        t += 180
        lines.append("%04d-%02d-%02d %02d:%02d:%02d,%s,%s,%d" % (*__import__("time").gmtime(t)[:6], repr(round(rng.uniform(1000, 30000), 2)),
                                                                repr(round(rng.uniform(1000, 30000), 6)), rng.randint(0, 10**6)))
    raw = ("\n".join(lines) + "\n").encode()
    pure = fd.compute_frame_digest(fd.columns_from_csv_bytes(raw))
    assert pure == pandas_digest(raw, float_precision="round_trip")
    assert fd.compute_frame_facts(fd.columns_from_csv_bytes(raw), 180).row_count == 20_000


# ══ Tranche 8 : défauts trouvés par la revue indépendante (ReDoS, entier géant, type de kind, pickle, sous-types) ═════════════════
import copy  # noqa: E402
import pickle  # noqa: E402
import time as _time  # noqa: E402


def test_a_hostile_float_cell_is_refused_in_linear_time():
    """ReDoS : `[0-9]+\\.?[0-9]*` était quadratique sur « 1111…1x ». 40 000 chiffres doivent être refusés presque instantanément."""
    raw = b"time,x\n2025-01-01 00:00:00,1.5\n2025-01-01 00:03:00," + b"1" * 40_000 + b"x\n"
    started = _time.perf_counter()
    with pytest.raises(fd.FrameRefused) as info:
        fd.columns_from_csv_bytes(raw)
    assert info.value.code is fd.FrameRefusal.FLOAT_TEXT
    assert _time.perf_counter() - started < 1.0  # quadratique : plusieurs dizaines de secondes ; linéaire : quelques millisecondes


@pytest.mark.parametrize("digits", [4300, 4301, 20_000])
def test_a_giant_integer_in_an_all_integer_column_is_a_typed_int_range_refusal(digits):
    """Python refuse int() au-delà de 4300 chiffres avec une ValueError brute : elle doit devenir un refus typé."""
    raw = b"time,x\n2025-01-01 00:00:00,1\n2025-01-01 00:03:00," + b"1" * digits + b"\n"
    _csv_refused(raw, R.INT_RANGE)


def test_leading_zeros_do_not_make_an_in_range_integer_a_refusal():
    column = fd.columns_from_csv_bytes(_csv("2025-01-01 00:00:00," + "0" * 40 + "7", "2025-01-01 00:03:00,1"))[1]
    assert (column.kind, column.values) == ("i64", (7, 1))


def test_a_kind_object_with_a_hostile_eq_is_a_typed_refusal():
    class Hostile:
        def __eq__(self, other):
            raise RuntimeError("piège")

        __hash__ = None

    _refused((fd.FrameColumn("time", "time_us", (1,)), fd.FrameColumn("a", Hostile(), (1,))), fd.FrameRefusal.BAD_COLUMN)


def test_float_and_int_subclasses_are_refused_exactly():
    class F(float):
        pass

    class I(int):  # noqa: E742
        pass

    _refused((fd.FrameColumn("time", "time_us", (1,)), fd.FrameColumn("a", "f64", (F(1.5),))), fd.FrameRefusal.BAD_VALUE)
    _refused((fd.FrameColumn("time", "time_us", (1,)), fd.FrameColumn("a", "i64", (I(1),))), fd.FrameRefusal.BAD_VALUE)
    _refused((fd.FrameColumn("time", "time_us", (I(1),)),), fd.FrameRefusal.BAD_VALUE)


@pytest.mark.parametrize("big", ["9223372036854775808", "-9223372036854775809", "99999999999999999999", "1" * 5000])
def test_an_out_of_int64_integer_is_refused_even_inside_a_column_that_also_holds_decimals(big):
    """Défaut de la vérification finale : une colonne mixte arrondissait en silence l'entier géant en f64 (1e20), contrairement à la note."""
    _csv_refused(_csv("2025-01-01 00:00:00,1.5", "2025-01-01 00:03:00," + big), R.INT_RANGE)
    _csv_refused(_csv("2025-01-01 00:00:00," + big, "2025-01-01 00:03:00,1.5"), R.INT_RANGE)


def test_in_range_integers_stay_floats_inside_a_decimal_column_as_pandas_does():
    column = fd.columns_from_csv_bytes(_csv("2025-01-01 00:00:00,9007199254740993", "2025-01-01 00:03:00,1.5"))[1]
    assert column.kind == "f64" and column.values[0] == float("9007199254740993")  # arrondi voulu par R9 (float(texte)), comme pandas


@pytest.mark.parametrize("zeros", [40, 4300, 5000, 100_000])
def test_leading_zeros_of_any_length_do_not_change_an_in_range_integer(zeros):
    column = fd.columns_from_csv_bytes(_csv("2025-01-01 00:00:00," + "0" * zeros + "7", "2025-01-01 00:03:00,-" + "0" * zeros + "9"))[1]
    assert (column.kind, column.values) == ("i64", (7, -9))


def test_explicit_columns_report_the_first_defect_in_column_order_too():
    time = fd.FrameColumn("time", "time_us", (0,))
    bad_float = fd.FrameColumn("a", "f64", (float("inf"),))
    bad_int = fd.FrameColumn("b", "i64", (2**63,))
    _refused((time, bad_float, bad_int), fd.FrameRefusal.NON_FINITE)
    _refused((time, bad_int, bad_float), fd.FrameRefusal.INT_RANGE)


@pytest.mark.parametrize("shape", ["1x", "1e", "1.1e+", "1e1e1e1e1e1e1e1e1e1e1e1e", "+-"])
def test_hostile_cells_of_several_shapes_are_refused_in_linear_time(shape):
    cell = (shape * 60_000)[:100_000] if len(shape) < 4 else shape * 6000
    raw = b"time,x\n2025-01-01 00:00:00,1.5\n2025-01-01 00:03:00," + cell.encode() + b"\n"
    started = _time.perf_counter()
    with pytest.raises(fd.FrameRefused):
        fd.columns_from_csv_bytes(raw)
    assert _time.perf_counter() - started < 1.0


def test_with_several_defective_columns_the_first_defect_in_column_order_is_reported():
    """Déterminisme du code de refus : le premier défaut dans l'ordre des colonnes gagne (les contrôles locaux à la lecture d'une
    colonne ne sont pas différés au contrôle final)."""
    row = "2025-01-01 00:00:00,{},{}\n2025-01-01 00:03:00,1,1\n"
    head = "time,a,b\n"
    _csv_refused((head + row.format("1e999", "9223372036854775808")).encode(), R.NON_FINITE)   # a : non fini, b : hors int64
    _csv_refused((head + row.format("9223372036854775808", "1e999")).encode(), R.INT_RANGE)    # a : hors int64, b : non fini
    _csv_refused((head + row.format("1e999", "abc")).encode(), R.NON_FINITE)


def test_a_frame_column_subclass_is_refused_because_its_attributes_could_change_between_reads():
    class Shifting(fd.FrameColumn):
        pass

    _refused((Shifting("time", "time_us", (1,)),), fd.FrameRefusal.BAD_COLUMN)


def test_the_delete_control_character_is_refused_in_names():
    _refused((fd.FrameColumn("time", "time_us", (1,)), fd.FrameColumn("a\x7fb", "i64", (1,))), fd.FrameRefusal.BAD_COLUMN)


def test_a_refusal_survives_pickle_and_copy_with_its_code_and_message():
    """Les workers de l'optimiseur passent des exceptions entre processus : le code de refus ne doit pas se perdre."""
    original = fd.FrameRefused(fd.FrameRefusal.INT_RANGE, "détail")
    for clone in (pickle.loads(pickle.dumps(original)), copy.copy(original), copy.deepcopy(original)):
        assert type(clone) is fd.FrameRefused and clone.code is fd.FrameRefusal.INT_RANGE and str(clone) == str(original)


def test_the_refusal_vocabulary_is_exactly_the_documented_closed_set():
    assert sorted(c.value for c in fd.FrameRefusal) == sorted([
        "EMPTY", "NO_TIME_COLUMN", "COLUMN_LENGTH", "DUPLICATE_COLUMN", "BAD_COLUMN", "BAD_VALUE", "NON_FINITE", "INT_RANGE", "BOM", "NOT_UTF8",
        "CSV_DIALECT", "CSV_RAGGED", "TIME_FORMAT", "MISSING_VALUE", "FLOAT_TEXT", "BAD_BAR", "BAR_DURATION_MISMATCH", "BAR_GRID",
        "NOT_STRICTLY_INCREASING", "SUB_SECOND", "TOO_FEW_ROWS", "TIME_RANGE"])


def test_s0_facts_refuse_what_the_frame_layer_refuses():
    with pytest.raises(fd.FrameRefused) as info:
        fd.compute_s0_frame_facts(V1_CSV.encode(), 60)
    assert info.value.code is fd.FrameRefusal.BAR_DURATION_MISMATCH
    with pytest.raises(fd.FrameRefused) as info:
        fd.compute_s0_frame_facts(b"", 180)
    assert info.value.code is fd.FrameRefusal.EMPTY
