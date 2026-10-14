"""
tests/test_gate_v_exposure_sources.py — AF-V-07 Slice E3-B1 : primitive d'intervalles UTC demi-ouverts.

Contrat normatif : ADR 0025 Décision 23, 23.3 (fenêtres semi-ouvertes `[ws, we)`), 23.27/23.28 (instants UTC à six décimales,
recouvrement `a.start < b.end ET b.start < a.end`) et 23.29 (design E3-B). Tests SYNTHÉTIQUES : chaînes en mémoire, aucun
fichier, aucune horloge, aucune donnée de marché, aucun registre.
"""

from __future__ import annotations

import ast
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gate_v_exposure_sources as b1
import gate_v_final_holdout_protocol as e3a

_MODULE_PATH = Path(b1.__file__)

# ============================================================================================
# Tranche 1 — normalize_window : validation et normalisation UTC des deux bornes
# ============================================================================================

T0 = "2026-11-02T00:00:00.000000Z"
T1 = "2026-12-01T00:00:00.000000Z"


def test_normalize_window_returns_both_bounds_as_fixed_six_digit_utc():
    assert b1.normalize_window("2026-11-02T00:00:00Z", "2026-12-01T00:00:00Z") == (T0, T1)


@pytest.mark.parametrize(
    "start, end, expected",
    [
        ("2026-11-02T02:00:00+02:00", "2026-12-01T01:00:00+01:00", (T0, T1)),
        ("2026-11-01T19:00:00-05:00", "2026-11-30T19:00:00-05:00", (T0, T1)),
        ("2026-11-02T00:00:00+00:00", "2026-12-01T00:00:00.000000Z", (T0, T1)),
        ("2026-11-02T00:00:00.5Z", "2026-11-02T00:00:00.500001Z",
         ("2026-11-02T00:00:00.500000Z", "2026-11-02T00:00:00.500001Z")),
        ("2026-01-01T01:00:00+05:30", "2026-01-01T20:00:00+05:30",
         ("2025-12-31T19:30:00.000000Z", "2026-01-01T14:30:00.000000Z")),
    ],
)
def test_normalize_window_converts_every_explicit_offset_to_utc(start, end, expected):
    assert b1.normalize_window(start, end) == expected


def test_normalize_window_is_idempotent():
    once = b1.normalize_window("2026-11-02T02:00:00+02:00", "2026-12-01T00:00:00Z")
    assert b1.normalize_window(*once) == once


@pytest.mark.parametrize(
    "start, end",
    [
        (T0, T0),                                                     # début == fin
        (T1, T0),                                                     # début après fin
        ("2026-11-02T00:00:00.000001Z", "2026-11-02T00:00:00.000000Z"),
        ("2026-11-02T02:00:00+02:00", T0),                            # mêmes instants sous deux représentations
    ],
)
def test_normalize_window_refuses_an_empty_or_inverted_window(start, end):
    with pytest.raises(ValueError):
        b1.normalize_window(start, end)


@pytest.mark.parametrize(
    "naive",
    ["2026-11-02T00:00:00", "2026-11-02", "2026-11-02 00:00:00Z", "2026-11-02T00:00Z", "", " 2026-11-02T00:00:00Z"],
)
def test_normalize_window_refuses_naive_or_malformed_instants_on_either_bound(naive):
    with pytest.raises(ValueError):
        b1.normalize_window(naive, T1)
    with pytest.raises(ValueError):
        b1.normalize_window(T0, naive)


@pytest.mark.parametrize(
    "bad",
    [
        "2026-11-02T00:00:00+00:60",     # minutes d'offset invalides
        "2026-11-02T00:00:00+24:00",     # offset hors plage
        "2026-11-02T00:00:00+0200",      # offset sans deux-points
        "2026-11-02T23:59:60Z",          # seconde intercalaire
        "2026-11-02t00:00:00Z",          # minuscule
        "2026-11-02T00:00:00.1234567Z",  # sept décimales
        "2026-02-29T00:00:00Z",          # 2026 non bissextile
        "2026-13-02T00:00:00Z",
    ],
)
def test_normalize_window_refuses_invalid_offsets_and_calendar_values(bad):
    with pytest.raises(ValueError):
        b1.normalize_window(bad, "2030-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        b1.normalize_window("2020-01-01T00:00:00Z", bad)


def test_normalize_window_accepts_a_leap_day():
    assert b1.normalize_window("2028-02-29T00:00:00Z", "2028-03-01T00:00:00Z") == (
        "2028-02-29T00:00:00.000000Z", "2028-03-01T00:00:00.000000Z",
    )


def test_normalize_window_handles_a_year_rollover_through_offsets():
    # 2026-12-31T23:30-00:30 = 2027-01-01T00:00Z ; 2027-01-01T00:30+00:30 = 2027-01-01T00:00Z : même instant, fenêtre vide
    with pytest.raises(ValueError):
        b1.normalize_window("2026-12-31T23:30:00-00:30", "2027-01-01T00:30:00+00:30")
    start, end = b1.normalize_window("2026-12-31T23:30:00-00:30", "2027-01-01T00:30:00-00:30")
    assert (start, end) == ("2027-01-01T00:00:00.000000Z", "2027-01-01T01:00:00.000000Z")


@pytest.mark.parametrize("bad", [None, True, False, 20261102, 1.5, b"2026-11-02T00:00:00Z", object(), ["2026-11-02T00:00:00Z"]])
def test_normalize_window_rejects_non_str_bounds_with_type_error(bad):
    with pytest.raises(TypeError):
        b1.normalize_window(bad, T1)
    with pytest.raises(TypeError):
        b1.normalize_window(T0, bad)


def test_normalize_window_rejects_str_subclasses():
    class S(str):
        pass

    with pytest.raises(TypeError):
        b1.normalize_window(S(T0), T1)


# ============================================================================================
# Tranche 2 — windows_overlap / overlap_verdict : géométrie de recouvrement de fenêtres [start, end)
# ============================================================================================

def _w(a: int, b: int) -> tuple[str, str]:
    """Fenêtre synthétique en secondes depuis 2026-01-01T00:00:00Z (instants indépendants du code testé)."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    return (base + timedelta(seconds=a)).strftime(fmt), (base + timedelta(seconds=b)).strftime(fmt)


def _overlap(w1, w2):
    return b1.windows_overlap(w1[0], w1[1], w2[0], w2[1])


@pytest.mark.parametrize(
    "w1, w2, expected",
    [
        (_w(0, 10), _w(0, 10), True),      # identiques
        (_w(0, 10), _w(5, 15), True),      # recouvrement partiel
        (_w(0, 10), _w(2, 8), True),       # inclusion totale
        (_w(2, 8), _w(0, 10), True),
        (_w(0, 10), _w(10, 20), False),    # adjacentes : [0,10) et [10,20) ne se recoupent pas
        (_w(10, 20), _w(0, 10), False),
        (_w(0, 10), _w(11, 20), False),    # séparées
    ],
)
def test_windows_overlap_basic_geometry(w1, w2, expected):
    assert _overlap(w1, w2) is expected


def test_windows_overlap_one_microsecond_intersection_overlaps():
    a = ("2026-01-01T00:00:00.000000Z", "2026-01-01T00:00:10.000001Z")
    b = ("2026-01-01T00:00:10.000000Z", "2026-01-01T00:00:20.000000Z")
    assert _overlap(a, b) is True
    assert _overlap(b, a) is True


def test_windows_overlap_gap_of_one_microsecond_does_not_overlap():
    a = ("2026-01-01T00:00:00.000000Z", "2026-01-01T00:00:09.999999Z")
    b = ("2026-01-01T00:00:10.000000Z", "2026-01-01T00:00:20.000000Z")
    assert _overlap(a, b) is False
    assert _overlap(b, a) is False


def test_windows_overlap_is_independent_of_the_offset_representation():
    # mêmes instants sous trois représentations de décalage
    a_utc = ("2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z")
    a_plus2 = ("2026-06-01T12:00:00+02:00", "2026-06-01T14:00:00+02:00")
    b = ("2026-06-01T11:00:00-05:00", "2026-06-01T12:00:00-05:00")          # = 16:00Z..17:00Z : séparée
    b_touch = ("2026-06-01T05:00:00-05:00", "2026-06-01T06:00:00-05:00")    # = 10:00Z..11:00Z : recoupe
    assert _overlap(a_utc, a_plus2) is True
    assert _overlap(a_plus2, a_utc) is True
    assert _overlap(a_plus2, b) is False
    assert _overlap(a_plus2, b_touch) is True


def test_windows_overlap_does_not_compare_lexically_non_normalized_instants():
    # Lexicalement les deux fenêtres semblent se recouper (« 20 » < « 23 » et « 22 » < « 23 ») alors qu'en UTC `late` tombe
    # le 2 juin 01:00Z..04:30Z, APRÈS `early` (1er juin 22:00Z..23:00Z) : une comparaison lexicale donnerait le mauvais verdict.
    late = ("2026-06-01T20:00:00-05:00", "2026-06-01T23:30:00-05:00")
    early = ("2026-06-01T22:00:00Z", "2026-06-01T23:00:00Z")
    assert late[0] < early[1] and early[0] < late[1]    # garde-fou : la comparaison lexicale brute dirait « recoupe »
    assert _overlap(late, early) is False
    assert _overlap(early, late) is False


def test_windows_overlap_leap_day_and_year_rollover():
    assert b1.windows_overlap("2028-02-28T12:00:00Z", "2028-03-01T00:00:00Z", "2028-02-29T00:00:00Z", "2028-02-29T01:00:00Z") is True
    assert b1.windows_overlap("2026-12-31T23:00:00Z", "2027-01-01T00:00:00Z", "2027-01-01T00:00:00Z", "2027-01-01T01:00:00Z") is False
    assert b1.windows_overlap("2026-12-31T23:00:00Z", "2027-01-01T00:00:00.000001Z", "2027-01-01T00:00:00Z", "2027-01-01T01:00:00Z") is True


def test_windows_overlap_dst_adjacent_dates_with_explicit_offsets():
    # Europe/Paris 2026-03-29 : +01:00 avant 02:00 local, +02:00 après ; offsets EXPLICITES, aucune heure locale supposée
    a = ("2026-03-29T01:30:00+01:00", "2026-03-29T03:00:00+02:00")   # 00:30Z..01:00Z
    b = ("2026-03-29T03:00:00+02:00", "2026-03-29T04:00:00+02:00")   # 01:00Z..02:00Z : adjacente
    c = ("2026-03-29T02:59:59.999999+02:00", "2026-03-29T04:00:00+02:00")  # 00:59:59.999999Z..02:00Z : recoupe a
    assert _overlap(a, b) is False
    assert _overlap(a, c) is True


def test_windows_overlap_extreme_representable_bounds():
    lo = ("0001-01-01T00:00:00.000000Z", "0001-01-01T00:00:00.000001Z")
    hi = ("9999-12-31T23:59:59.999998Z", "9999-12-31T23:59:59.999999Z")
    full = ("0001-01-01T00:00:00.000000Z", "9999-12-31T23:59:59.999999Z")
    assert _overlap(lo, full) is True
    assert _overlap(hi, full) is True
    assert _overlap(lo, hi) is False


@pytest.mark.parametrize(
    "w",
    [(T0, T0), (T1, T0), ("2026-11-02T00:00:00", T1), ("2026-02-29T00:00:00Z", T1), ("2026-11-02T00:00:00+00:60", T1)],
)
def test_windows_overlap_refuses_invalid_windows_on_either_side(w):
    valid = (T0, T1)
    with pytest.raises(ValueError):
        _overlap(w, valid)
    with pytest.raises(ValueError):
        _overlap(valid, w)


@pytest.mark.parametrize("bad", [None, True, 5, 1.5, b"x", object()])
def test_windows_overlap_rejects_non_str_arguments_with_type_error(bad):
    for position in range(4):
        args = [T0, T1, T0, T1]
        args[position] = bad
        with pytest.raises(TypeError):
            b1.windows_overlap(*args)


def test_overlap_verdict_maps_the_boolean_to_the_e3a_enum_and_is_never_unknown():
    assert b1.overlap_verdict(*_w(0, 10), *_w(5, 15)) is e3a.OverlapVerdict.OVERLAPS
    assert b1.overlap_verdict(*_w(0, 10), *_w(10, 20)) is e3a.OverlapVerdict.NO_OVERLAP
    assert b1.overlap_verdict(*_w(0, 10), *_w(0, 10)) is e3a.OverlapVerdict.OVERLAPS


def test_overlap_verdict_propagates_errors_instead_of_returning_unknown():
    with pytest.raises(ValueError):
        b1.overlap_verdict(T0, T0, T0, T1)
    with pytest.raises(TypeError):
        b1.overlap_verdict(None, T1, T0, T1)


# ---- Différentiel et propriétés (graines fixes, sans dépendance supplémentaire) ----------------------------

_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"
_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _random_window(rng: random.Random, span_us: int) -> tuple[str, str]:
    start = rng.randrange(0, span_us)
    length = rng.randrange(1, span_us)
    return (
        (_EPOCH + timedelta(microseconds=start)).strftime(_FMT),
        (_EPOCH + timedelta(microseconds=start + length)).strftime(_FMT),
    )


@pytest.mark.parametrize("seed, span_us", [(1, 20), (2, 1_000), (3, 10**9), (4, 10**13)])
def test_windows_overlap_matches_the_e3a_private_formula_on_seeded_random_windows(seed, span_us):
    rng = random.Random(seed)
    seen = {True: 0, False: 0}
    for _ in range(400):
        a = _random_window(rng, span_us)
        b = _random_window(rng, span_us)
        expected = e3a._windows_overlap(a[0], a[1], b[0], b[1])   # oracle différentiel : formule privée d'E3-A
        assert b1.windows_overlap(*a, *b) is expected
        seen[expected] += 1
    assert seen[True] > 0 and seen[False] > 0   # la graine fixe exerce les deux verdicts


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_windows_overlap_is_symmetric_and_deterministic_on_seeded_random_windows(seed):
    rng = random.Random(seed)
    for _ in range(300):
        a = _random_window(rng, 50)
        b = _random_window(rng, 50)
        first = b1.windows_overlap(*a, *b)
        assert b1.windows_overlap(*b, *a) is first
        assert b1.windows_overlap(*a, *b) is first
        assert b1.overlap_verdict(*a, *b) is b1.overlap_verdict(*b, *a)
        assert b1.windows_overlap(*a, *a) is True   # toute fenêtre valide se recoupe elle-même


@pytest.mark.parametrize("seed", [21, 22])
def test_windows_overlap_is_invariant_under_random_offset_representation(seed):
    rng = random.Random(seed)
    for _ in range(200):
        a = _random_window(rng, 10**8)
        b = _random_window(rng, 10**8)

        def reoffset(instant: str) -> str:
            minutes = rng.randrange(-23 * 60, 23 * 60 + 1)
            local = datetime.strptime(instant, _FMT).replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(minutes=minutes)))
            sign = "+" if minutes >= 0 else "-"
            hh, mm = divmod(abs(minutes), 60)
            return local.strftime("%Y-%m-%dT%H:%M:%S.%f") + f"{sign}{hh:02d}:{mm:02d}"

        a2 = (reoffset(a[0]), reoffset(a[1]))
        b2 = (reoffset(b[0]), reoffset(b[1]))
        assert b1.windows_overlap(*a2, *b2) is b1.windows_overlap(*a, *b)


# ============================================================================================
# Tranche 3 — conversion legacy `[start, end_inclusive]` → `[start, end_inclusive + 1µs)`
# ============================================================================================

@pytest.mark.parametrize(
    "end_inclusive, expected",
    [
        ("2026-11-02T10:00:00.000000Z", "2026-11-02T10:00:00.000001Z"),
        ("2026-11-02T10:00:00Z", "2026-11-02T10:00:00.000001Z"),
        ("2026-11-02T23:59:59.999999Z", "2026-11-03T00:00:00.000000Z"),    # minuit
        ("2026-11-02T00:00:00.123456Z", "2026-11-02T00:00:00.123457Z"),    # microsecondes fractionnaires
        ("2026-11-02T00:00:00.999999Z", "2026-11-02T00:00:01.000000Z"),
        ("2026-02-28T23:59:59.999999Z", "2026-03-01T00:00:00.000000Z"),    # fin de février non bissextile
        ("2028-02-28T23:59:59.999999Z", "2028-02-29T00:00:00.000000Z"),    # veille d'un 29 février
        ("2028-02-29T23:59:59.999999Z", "2028-03-01T00:00:00.000000Z"),
        ("2026-04-30T23:59:59.999999Z", "2026-05-01T00:00:00.000000Z"),    # fin de mois
        ("2026-12-31T23:59:59.999999Z", "2027-01-01T00:00:00.000000Z"),    # fin d'année
        ("2026-11-02T23:59:59+01:00", "2026-11-02T22:59:59.000001Z"),      # décalage explicite
        ("0001-01-01T00:00:00.000000Z", "0001-01-01T00:00:00.000001Z"),    # année minimale
        ("9999-12-31T23:59:59.999998Z", "9999-12-31T23:59:59.999999Z"),    # dernière borne exclusive représentable
    ],
)
def test_inclusive_end_to_exclusive_adds_exactly_one_microsecond(end_inclusive, expected):
    assert b1.inclusive_end_to_exclusive(end_inclusive) == expected


def test_inclusive_end_to_exclusive_fails_closed_on_overflow_at_the_maximum_instant():
    with pytest.raises(ValueError):
        b1.inclusive_end_to_exclusive("9999-12-31T23:59:59.999999Z")
    with pytest.raises(ValueError):
        b1.inclusive_end_to_exclusive("9999-12-31T23:59:59.999999+00:00")


@pytest.mark.parametrize("bad", ["2026-11-02T10:00:00", "2026-11-02", "2026-02-29T00:00:00Z", "2026-11-02T10:00:00+00:60", ""])
def test_inclusive_end_to_exclusive_refuses_invalid_instants(bad):
    with pytest.raises(ValueError):
        b1.inclusive_end_to_exclusive(bad)


@pytest.mark.parametrize("bad", [None, True, 5, 1.5, b"x", object()])
def test_inclusive_end_to_exclusive_rejects_non_str_with_type_error(bad):
    with pytest.raises(TypeError):
        b1.inclusive_end_to_exclusive(bad)


def test_inclusive_window_to_half_open_converts_only_the_end():
    assert b1.inclusive_window_to_half_open("2026-11-02T00:00:00Z", "2026-11-02T23:59:59.999999Z") == (
        "2026-11-02T00:00:00.000000Z", "2026-11-03T00:00:00.000000Z",
    )


def test_inclusive_window_to_half_open_accepts_end_equal_to_start_as_one_microsecond_window():
    assert b1.inclusive_window_to_half_open("2026-11-02T10:00:00Z", "2026-11-02T10:00:00Z") == (
        "2026-11-02T10:00:00.000000Z", "2026-11-02T10:00:00.000001Z",
    )


def test_inclusive_window_to_half_open_refuses_end_before_start():
    with pytest.raises(ValueError):
        b1.inclusive_window_to_half_open("2026-11-02T10:00:00.000001Z", "2026-11-02T10:00:00.000000Z")
    with pytest.raises(ValueError):
        b1.inclusive_window_to_half_open("2026-11-03T00:00:00Z", "2026-11-02T00:00:00Z")


def test_inclusive_window_to_half_open_refuses_end_before_start_across_offsets():
    # 10:00+02:00 = 08:00Z est avant 09:00Z
    with pytest.raises(ValueError):
        b1.inclusive_window_to_half_open("2026-11-02T09:00:00Z", "2026-11-02T10:00:00+02:00")


def test_inclusive_window_to_half_open_overflows_fail_closed_never_truncated():
    with pytest.raises(ValueError):
        b1.inclusive_window_to_half_open("9999-12-31T00:00:00Z", "9999-12-31T23:59:59.999999Z")


@pytest.mark.parametrize("bad", [None, True, 5, 1.5, b"x", object()])
def test_inclusive_window_to_half_open_rejects_non_str_with_type_error(bad):
    with pytest.raises(TypeError):
        b1.inclusive_window_to_half_open(bad, T1)
    with pytest.raises(TypeError):
        b1.inclusive_window_to_half_open(T0, bad)


def test_converted_inclusive_window_makes_the_legacy_last_instant_overlap_a_claim_starting_there():
    # fin inclusive = 10:00:00 : lue à tort comme demi-ouverte, la fenêtre est ADJACENTE au Claim qui démarre à 10:00:00 (pas de
    # recouvrement) ; correctement convertie en [start, 10:00:00.000001), elle recoupe ce Claim.
    legacy_start, legacy_end_inclusive = "2026-11-02T09:00:00Z", "2026-11-02T10:00:00Z"
    claim = ("2026-11-02T10:00:00Z", "2026-11-02T11:00:00Z")
    naive_half_open = (legacy_start, legacy_end_inclusive)
    assert b1.windows_overlap(*naive_half_open, *claim) is False
    converted = b1.inclusive_window_to_half_open(legacy_start, legacy_end_inclusive)
    assert b1.windows_overlap(*converted, *claim) is True


# ============================================================================================
# Tranche 4 — pureté du module : imports, appels interdits, état global, API publique
# ============================================================================================

_MODULE_TREE = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))


def test_module_imports_only_datetime_and_public_e3a_symbols():
    allowed_modules = {"__future__", "datetime", "gate_v_final_holdout_protocol"}
    imported_from_e3a: set[str] = set()
    for node in ast.walk(_MODULE_TREE):
        if isinstance(node, ast.Import):
            assert {alias.name.split(".")[0] for alias in node.names} <= allowed_modules
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in allowed_modules, node.module
            if node.module == "gate_v_final_holdout_protocol":
                imported_from_e3a |= {alias.name for alias in node.names}
    assert imported_from_e3a == {"OverlapVerdict", "normalize_utc_instant"}
    assert not any(name.startswith("_") for name in imported_from_e3a)   # E3-A n'a pas de __all__ : public = sans préfixe `_`
    assert all(hasattr(e3a, name) for name in imported_from_e3a)


def test_module_does_not_reference_private_e3a_symbols_or_io_and_clock_primitives():
    forbidden_names = {"open", "print", "input", "exec", "eval", "compile", "__import__", "now", "utcnow", "today", "time", "sleep",
                       "getenv", "environ", "random", "urandom", "uuid4"}
    e3a_private = {name for name in vars(e3a) if name.startswith("_") and not name.startswith("__")}
    for node in ast.walk(_MODULE_TREE):
        if isinstance(node, ast.Name):
            assert node.id not in forbidden_names, node.id
            assert node.id not in e3a_private, node.id   # aucun symbole privé d'E3-A (ex. _instant, _windows_overlap, _parse_aware)
        elif isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_names, node.attr
            assert not (isinstance(node.value, ast.Name) and node.value.id == "gate_v_final_holdout_protocol")
    source = _MODULE_PATH.read_text(encoding="utf-8")
    for fragment in ("gate_v_final_holdout_protocol._", "Europe/Paris", "zoneinfo", "tzlocal"):
        assert fragment not in source, fragment


def test_module_has_no_mutable_module_level_state():
    for node in _MODULE_TREE.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            assert not isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp, ast.Call)), ast.dump(node)
        assert not isinstance(node, (ast.Global, ast.Nonlocal))
    assert not any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(_MODULE_TREE))


def test_public_api_is_exactly_the_five_documented_functions():
    public = sorted(name for name, obj in vars(b1).items() if not name.startswith("_") and getattr(obj, "__module__", None) == b1.__name__)
    assert public == [
        "inclusive_end_to_exclusive",
        "inclusive_window_to_half_open",
        "normalize_window",
        "overlap_verdict",
        "windows_overlap",
    ]


def test_primitives_are_deterministic_and_leave_no_observable_state():
    snapshot = {name: repr(value) for name, value in vars(b1).items() if not callable(value) and not name.startswith("__")}
    first = (
        b1.normalize_window("2026-11-02T02:00:00+02:00", T1),
        b1.windows_overlap(T0, T1, T0, T1),
        b1.inclusive_end_to_exclusive("2026-11-02T23:59:59.999999Z"),
    )
    for _ in range(3):
        assert (
            b1.normalize_window("2026-11-02T02:00:00+02:00", T1),
            b1.windows_overlap(T0, T1, T0, T1),
            b1.inclusive_end_to_exclusive("2026-11-02T23:59:59.999999Z"),
        ) == first
    assert {name: repr(value) for name, value in vars(b1).items() if not callable(value) and not name.startswith("__")} == snapshot


def test_primitives_never_return_findings_or_freshness_verdicts():
    result = b1.overlap_verdict(T0, T1, T0, T1)
    assert isinstance(result, e3a.OverlapVerdict)
    assert result in (e3a.OverlapVerdict.OVERLAPS, e3a.OverlapVerdict.NO_OVERLAP)
    assert b1.overlap_verdict(T0, T1, T1, "2027-01-01T00:00:00Z") is e3a.OverlapVerdict.NO_OVERLAP


# ============================================================================================
# Revue indépendante — durcissements (MINOR) : priorité TypeError > ValueError, décalages extrêmes, entrées hostiles
# ============================================================================================

def test_type_error_takes_precedence_over_value_error_whatever_the_argument_order():
    with pytest.raises(TypeError):
        b1.normalize_window("bad", None)
    with pytest.raises(TypeError):
        b1.normalize_window(None, "bad")
    with pytest.raises(TypeError):
        b1.windows_overlap("bad", "bad", None, None)
    with pytest.raises(TypeError):
        b1.windows_overlap(None, None, "bad", "bad")
    with pytest.raises(TypeError):
        b1.overlap_verdict("bad", T1, T0, 5)
    with pytest.raises(TypeError):
        b1.inclusive_window_to_half_open("bad", None)
    with pytest.raises(TypeError):
        b1.inclusive_window_to_half_open(None, "bad")


class _StrSubclass(str):
    pass


@pytest.mark.parametrize(
    "call",
    [
        lambda s: b1.normalize_window(s(T0), T1),
        lambda s: b1.normalize_window(T0, s(T1)),
        lambda s: b1.windows_overlap(s(T0), T1, T0, T1),
        lambda s: b1.windows_overlap(T0, s(T1), T0, T1),
        lambda s: b1.windows_overlap(T0, T1, s(T0), T1),
        lambda s: b1.windows_overlap(T0, T1, T0, s(T1)),
        lambda s: b1.overlap_verdict(s(T0), T1, T0, T1),
        lambda s: b1.overlap_verdict(T0, T1, T0, s(T1)),
        lambda s: b1.inclusive_end_to_exclusive(s(T0)),
        lambda s: b1.inclusive_window_to_half_open(s(T0), T1),
        lambda s: b1.inclusive_window_to_half_open(T0, s(T1)),
    ],
)
def test_every_public_function_rejects_str_subclasses_on_every_bound(call):
    with pytest.raises(TypeError):
        call(_StrSubclass)


def test_str_subclass_takes_precedence_over_an_earlier_invalid_value():
    # le contrôle de type PRÉALABLE de B1 (et non celui d'E3-A, appliqué borne par borne) doit gagner sur une ValueError antérieure
    with pytest.raises(TypeError):
        b1.normalize_window("bad", _StrSubclass(T0))
    with pytest.raises(TypeError):
        b1.windows_overlap("bad", "bad", _StrSubclass(T0), "x")
    with pytest.raises(TypeError):
        b1.overlap_verdict("bad", T1, T0, _StrSubclass(T1))
    with pytest.raises(TypeError):
        b1.inclusive_window_to_half_open("bad", _StrSubclass(T0))


@pytest.mark.parametrize(
    "instant, expected",
    [
        ("2026-11-02T00:00:00-23:59", "2026-11-02T23:59:00.000000Z"),
        ("2026-11-02T00:00:00+23:59", "2026-11-01T00:01:00.000000Z"),
        ("2026-11-02T00:00:00-00:00", "2026-11-02T00:00:00.000000Z"),
        ("2026-11-02T00:00:00+00:00", "2026-11-02T00:00:00.000000Z"),
    ],
)
def test_extreme_and_signed_zero_offsets_are_accepted_and_normalized(instant, expected):
    assert b1.normalize_window(instant, "2026-11-04T00:00:00Z") == (expected, "2026-11-04T00:00:00.000000Z")


@pytest.mark.parametrize("bad", ["0001-01-01T00:00:00+00:01", "9999-12-31T23:59:59-00:01"])
def test_offsets_that_leave_the_representable_range_are_refused_not_leaked(bad):
    with pytest.raises(ValueError):
        b1.normalize_window(bad, "9999-12-31T23:59:59.999999Z")
    with pytest.raises(ValueError):
        b1.normalize_window("0001-01-01T00:00:00Z", bad)
    with pytest.raises(ValueError):
        b1.inclusive_end_to_exclusive(bad)


@pytest.mark.parametrize(
    "hostile",
    [
        "\uff12\uff10\uff12\uff16-11-02T00:00:00Z",        # chiffres pleine largeur
        "2026-11-02T00:00:00Z\n",          # saut de ligne final
        "2026-11-02T00:00:00\u221205:00",  # signe moins Unicode
        "2026-11-02T00:00:00,5Z",          # virgule décimale
        "2026-11-02T00:00:00.Z",           # point sans décimale
        "2026-11-02T00:00:00\u200bZ",      # espace de largeur nulle
    ],
)
def test_hostile_non_ascii_or_malformed_instants_are_refused(hostile):
    with pytest.raises(ValueError):
        b1.normalize_window(hostile, T1)
    with pytest.raises(ValueError):
        b1.windows_overlap(T0, T1, T0, hostile)
    with pytest.raises(ValueError):
        b1.inclusive_end_to_exclusive(hostile)


@pytest.mark.parametrize("seed", [31, 32])
def test_offsets_up_to_plus_minus_23_59_preserve_overlap_verdicts(seed):
    rng = random.Random(seed)
    for _ in range(200):
        a = _random_window(rng, 10**8)
        b = _random_window(rng, 10**8)

        def reoffset(instant: str) -> str:
            minutes = rng.choice([-23 * 60 - 59, 23 * 60 + 59, rng.randrange(-1439, 1440)])
            local = datetime.strptime(instant, _FMT).replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(minutes=minutes)))
            sign = "+" if minutes >= 0 else "-"
            hh, mm = divmod(abs(minutes), 60)
            return local.strftime("%Y-%m-%dT%H:%M:%S.%f") + f"{sign}{hh:02d}:{mm:02d}"

        assert b1.windows_overlap(reoffset(a[0]), reoffset(a[1]), reoffset(b[0]), reoffset(b[1])) is b1.windows_overlap(*a, *b)
