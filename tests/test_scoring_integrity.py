"""Scoring Integrity (finite-metrics-v1) — contrat docs/adr/0029-scoring-numeric-integrity-v1.md.

Seams : `scoring.compute_score` et les fonctions publiques de validation de `scoring.py`.
Les valeurs attendues des scores valides viennent EXCLUSIVEMENT des vecteurs dorés produits par le
code gelé `ffa987c` (`tests/fixtures/scoring_golden_ffa987c.json`), jamais du code corrigé.
"""
import dataclasses
import json
import math
import random
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

import scoring
from scoring import FilterConfig, ScoreWeights, compute_score

INF = float("inf")
NAN = float("nan")
FIXTURE = Path(__file__).parent / "fixtures" / "scoring_golden_ffa987c.json"
UNFILTERED = FilterConfig(min_trades=0, max_drawdown_pct=INF, min_profit_factor=0.0,
                          max_consecutive_losses=2**31 - 1, min_win_rate=0.0)

# Candidat sain complet (14 clés, cohérent). Son score à ffa987c (sonde du 2026-11-17, mêmes 10
# clés lues par le score) vaut 51.14728669787839 ; les quatre clés auxiliaires ne sont pas lues.
SANE = dict(n_trades=60, n_win=30, n_loss=30, win_rate=50.0, gross_win=3000.0, gross_loss=2000.0,
            profit_factor=1.5, payoff=1.5, max_dd_pct=10.0, max_dd_usd=1000.0, max_consec_loss=4,
            net_ret_pct=20.0, net_ret_usd=2000.0, equity_r_squared=0.8)
SANE_SCORE = 51.14728669787839
SCORED_FIELDS = ["n_trades", "max_dd_pct", "profit_factor", "max_consec_loss", "win_rate",
                 "net_ret_pct", "payoff", "equity_r_squared", "net_ret_usd", "max_dd_usd"]


def score(stats, weights=None, filters=None, **kw):
    return compute_score(stats, weights or ScoreWeights(), filters or FilterConfig(), **kw)


def with_(**kw):
    s = dict(SANE)
    s.update(kw)
    return s


def assert_rejected(result, code=None, field=None, kind="INVALID_METRIC"):
    sc, filtered, reason, warnings = result
    assert sc == 0.0 and filtered is True and warnings == [], result
    assert reason.startswith(kind + ":"), reason
    if code is not None:
        assert reason.split(":")[1] == code, reason
    if field is not None:
        assert reason.split(":", 2)[2] == field, reason


# ── Garde : le candidat sain garde son score historique ──────────────────────────────────────────

def test_sane_candidate_keeps_its_historical_score():
    assert score(SANE) == (SANE_SCORE, False, "", [])


# ── Vecteurs dorés (C10) : identité au bit près pour toute entrée valide ─────────────────────────

def _decode(value):
    if value == "+inf":
        return INF
    if isinstance(value, dict) and set(value) == {"t", "v"}:
        t, v = value["t"], value["v"]
        if v == "+inf":
            return {"float64": np.float64, "float32": np.float32}.get(t, float)(INF)
        return {"float": float, "int": int, "float64": lambda x: np.float64(float(x)),
                "int64": lambda x: np.int64(int(x)), "float32": lambda x: np.float32(float(x))}[t](v)
    return value


def _golden_sets():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data, data["sets"]


def test_golden_fixture_provenance_is_frozen_ffa987c():
    data, sets = _golden_sets()
    assert data["generated_at_head"] == "ffa987ca144edcf0264fee1a88525dc6f1ab2e56"
    assert data["scoring_py_sha256"] == "4919dcb8454a2f0995ef268bc84da565bde016e83d8c28185172e093a6f71d22"
    assert [s["cases"] for s in data["sources"]] == [800, 515, 66]
    assert sum(len(s["cases"]) for s in sets) == 1381


def test_golden_reference_environment():
    data, _ = _golden_sets()
    import platform
    assert np.__version__ == data["reference_numpy"], "vecteurs float32 : numpy de référence requis"
    assert platform.python_version() == data["reference_python"]


@pytest.mark.parametrize("set_index", [0, 1, 2])
def test_golden_valid_scores_are_bit_identical(set_index):
    _, sets = _golden_sets()
    gset = sets[set_index]
    weights_table = gset["weights"] if isinstance(gset["weights"], dict) else {"default": None}
    mismatches = []
    for case in gset["cases"]:
        stats = {k: _decode(v) for k, v in case["stats"].items()}
        wname = case.get("weights", "default")
        weights = ScoreWeights(**weights_table[wname]) if weights_table.get(wname) else ScoreWeights()
        filters = FilterConfig() if case["filters"] == "default" else UNFILTERED
        kwargs = {}
        if case.get("params") is not None:
            kwargs["params"] = case["params"]
        if case.get("with_param_ranges"):
            kwargs["param_ranges"] = [dict(r) for r in gset["param_ranges"]]
        got = compute_score(stats, weights, filters, **kwargs)
        expected_warnings = case["warnings"] if "warnings" in case else None
        ok = (float(got[0]).hex() == case["score_hex"] and got[1] == case["filtered"]
              and got[2] == case["reason"]
              and (len(got[3]) == case["n_warnings"] if expected_warnings is None
                   else got[3] == expected_warnings))
        if not ok:
            mismatches.append((case["id"], case.get("group"), got[:3], case["score_hex"], case["reason"]))
    assert mismatches == [], f"{len(mismatches)} divergence(s) : {mismatches[:5]}"


# ── R01-R04 : NaN ne contourne ni filtre ni normalisation ────────────────────────────────────────

def test_r01_nan_drawdown_no_longer_bypasses_the_filter():
    assert_rejected(score(with_(max_dd_pct=NAN)), "NON_FINITE", "max_dd_pct")


@pytest.mark.parametrize("field", ["n_trades", "max_dd_pct", "profit_factor", "max_consec_loss", "win_rate"])
def test_r02_nan_never_passes_an_elimination_filter(field):
    assert_rejected(score(with_(**{field: NAN})), "NON_FINITE", field)


@pytest.mark.parametrize("stats, performance_reason", [
    (dict(SANE, n_trades=5, n_win=3, n_loss=2, max_consec_loss=2, win_rate=NAN), "Trop peu de trades"),
    (dict(SANE, max_dd_pct=80.0, equity_r_squared=NAN), "Drawdown trop"),
])
def test_r02b_numeric_rejection_takes_precedence_over_performance_filters(stats, performance_reason):
    sc, filtered, reason, _ = score(stats)
    assert reason.startswith("INVALID_METRIC:"), reason
    assert performance_reason not in reason


def test_r03_clamp_refuses_nan():
    with pytest.raises(scoring.ScoringInvariantError):
        scoring._clamp(NAN)


def test_r03_invariant_error_is_not_an_arithmetic_error():
    assert issubclass(scoring.ScoringInvariantError, Exception)
    assert not issubclass(scoring.ScoringInvariantError, ArithmeticError)


@pytest.mark.parametrize("field", SCORED_FIELDS)
def test_r04_nan_never_produces_a_positive_score(field):
    assert_rejected(score(with_(**{field: NAN})), "NON_FINITE", field)
    assert_rejected(score(with_(**{field: NAN}), filters=UNFILTERED), "NON_FINITE", field)


# ── R05-R08 : profit factor et payoff infinis ────────────────────────────────────────────────────

def test_r05_negative_infinite_profit_factor_is_rejected():
    assert_rejected(score(with_(profit_factor=-INF)), "NON_FINITE", "profit_factor")


def test_r06_normalizers_treat_negative_infinity_as_worst_not_best():
    assert scoring.normalize_profit_factor(-INF) == 0.0
    assert scoring.normalize_recovery_factor(-INF) == 0.0


def test_r06b_derived_negative_infinite_recovery_factor_scores_like_zero_recovery():
    extreme = score(with_(net_ret_usd=-1e300, max_dd_usd=1e-300))
    zero_rf = score(with_(net_ret_usd=0.0))
    assert extreme[1] is False and extreme[0] == zero_rf[0]


def test_r07_legitimate_infinite_profit_factor_keeps_penalty_and_warning():
    s = with_(n_win=60, n_loss=0, win_rate=100.0, gross_loss=0.0, profit_factor=INF, payoff=INF,
              max_consec_loss=0)
    sc, filtered, reason, warnings = score(s)
    assert filtered is False and sc > 0
    assert any("Profit Factor infini" in w for w in warnings)


def test_r08_profit_factor_zero_over_zero_is_undefined():
    s = with_(n_win=0, n_loss=60, win_rate=0.0, gross_win=0.0, gross_loss=0.0, profit_factor=INF,
              payoff=INF, max_consec_loss=60)
    assert_rejected(score(s, filters=UNFILTERED), "UNDEFINED", "profit_factor")


def test_f9_winners_plus_zero_pnl_losers_infinite_pf_and_payoff_are_legitimate():
    s = with_(n_win=40, n_loss=20, win_rate=40 / 60 * 100, gross_win=3000.0, gross_loss=0.0,
              profit_factor=INF, payoff=INF)
    sc, filtered, reason, _ = score(s, filters=UNFILTERED)
    assert filtered is False and sc > 0, reason


def test_f9_infinite_payoff_without_any_gain_is_undefined():
    s = with_(n_win=0, n_loss=60, win_rate=0.0, gross_win=0.0, gross_loss=2000.0, profit_factor=0.0,
              payoff=INF, max_consec_loss=10)
    assert_rejected(score(s, filters=UNFILTERED), "UNDEFINED", "payoff")


# ── R10-R12 : cohérence ──────────────────────────────────────────────────────────────────────────

def test_r10_counts_must_add_up():
    assert_rejected(score(with_(n_win=25, n_loss=25)), "INCOHERENT", "n_trades")


def test_r11_profit_factor_must_match_gross_amounts():
    assert_rejected(score(with_(profit_factor=3.0)), "INCOHERENT", "profit_factor")


def test_r11b_finite_profit_factor_requires_losses():
    assert_rejected(score(with_(gross_loss=0.0, profit_factor=1.5)), "INCOHERENT", "profit_factor")


def test_r11c_profit_factor_check_tolerates_exact_zero():
    s = with_(n_win=0, n_loss=60, win_rate=0.0, gross_win=0.0, profit_factor=0.0, payoff=0.0,
              max_consec_loss=10)
    assert score(s, filters=UNFILTERED)[1] is False


def test_r12_consecutive_losses_cannot_exceed_losses():
    assert_rejected(score(with_(max_consec_loss=40)), "INCOHERENT", "max_consec_loss")


def test_r12b_win_rate_must_match_counts():
    assert_rejected(score(with_(win_rate=55.0)), "INCOHERENT", "win_rate")


# ── R13-R16 : types, alias, débordement, domaine, types numpy ────────────────────────────────────

@pytest.mark.parametrize("bad", [None, "1.5", True, np.bool_(True), Decimal("1.5"), Fraction(3, 2)],
                         ids=["None", "str", "bool", "np_bool", "Decimal", "Fraction"])
@pytest.mark.parametrize("field", SCORED_FIELDS)
def test_r13_invalid_types_are_rejected_without_exception(field, bad):
    assert_rejected(score(with_(**{field: bad})), "TYPE", field)


def test_r13_non_mapping_stats_is_rejected():
    assert_rejected(score(None), "TYPE", "stats")


def test_r13_non_integral_count_is_rejected():
    assert_rejected(score(with_(n_trades=60.5)), "TYPE", "n_trades")


@pytest.mark.parametrize("primary, alias", [
    ("n_trades", "total_trades"), ("max_consec_loss", "max_consecutive_losses"),
    ("net_ret_pct", "pct_gain"), ("payoff", "avg_win_loss_ratio"), ("net_ret_usd", "net_profit"),
])
def test_r13b_aliases_follow_the_score_resolution_order(primary, alias):
    only_alias = dict(SANE)
    only_alias[alias] = only_alias.pop(primary)
    assert score(only_alias) == score(SANE)
    primary_none = dict(SANE)
    primary_none[primary] = None
    primary_none[alias] = SANE[primary]
    assert_rejected(score(primary_none), "TYPE", primary)
    conflicting = dict(SANE)
    conflicting[alias] = SANE[primary] + 1
    assert_rejected(score(conflicting), "INCOHERENT", primary)


@pytest.mark.parametrize("field", ["net_ret_pct", "net_ret_usd", "n_trades"])
def test_r14_huge_integers_are_rejected_without_overflow_error(field):
    assert_rejected(score(with_(**{field: 10**400})), "OVERFLOW", field)


@pytest.mark.parametrize("field, value, code", [
    ("max_dd_pct", -5.0, "OUT_OF_DOMAIN"), ("max_dd_pct", -INF, "NON_FINITE"),
    ("max_consec_loss", -3, "OUT_OF_DOMAIN"), ("win_rate", 150.0, "OUT_OF_DOMAIN"),
    ("win_rate", -1.0, "OUT_OF_DOMAIN"), ("equity_r_squared", 1.2, "OUT_OF_DOMAIN"),
    ("equity_r_squared", -0.1, "OUT_OF_DOMAIN"), ("max_dd_usd", -1.0, "OUT_OF_DOMAIN"),
    ("n_trades", -5, "OUT_OF_DOMAIN"), ("profit_factor", -0.5, "OUT_OF_DOMAIN"),
])
def test_r15_out_of_domain_values_are_rejected(field, value, code):
    assert_rejected(score(with_(**{field: value})), code, field)


@pytest.mark.parametrize("field, aux", [("gross_win", NAN), ("gross_loss", -1.0), ("n_win", NAN)])
def test_r15b_auxiliary_coherence_keys_are_validated(field, aux):
    assert score(with_(**{field: aux}))[2].startswith("INVALID_METRIC:")


def test_r16_validation_never_mutates_or_converts_stats():
    s = with_(profit_factor=np.float64(1.5), n_trades=np.int64(60), equity_r_squared=np.float32(0.8))
    before = {k: (type(v), v) for k, v in s.items()}
    score(s)
    assert {k: (type(v), v) for k, v in s.items()} == before


# ── R17-R21 : configuration et invariants internes ──────────────────────────────────────────────

@pytest.mark.parametrize("weights, field", [
    (dataclasses.replace(ScoreWeights(), win_rate=INF), "weights.win_rate"),
    (dataclasses.replace(ScoreWeights(), win_rate=NAN), "weights.win_rate"),
    (dataclasses.replace(ScoreWeights(), win_rate=-3.0), "weights.win_rate"),
    (dataclasses.replace(ScoreWeights(), win_rate=True), "weights.win_rate"),
    (ScoreWeights(**{f.name: 0.0 for f in dataclasses.fields(ScoreWeights)}), "weights.total"),
    (ScoreWeights(**{f.name: 1e308 for f in dataclasses.fields(ScoreWeights)}), "weights.total"),
], ids=["inf", "nan", "negative", "bool", "all_zero", "sum_overflow"])
def test_r17_r18_r21b_invalid_weights(weights, field):
    assert_rejected(score(SANE, weights=weights), kind="INVALID_CONFIG", field=field)
    with pytest.raises(scoring.InvalidScoringConfiguration, match=field.replace(".", r"\.")):
        scoring.validate_scoring_configuration(weights, FilterConfig())


@pytest.mark.parametrize("filters, field", [
    (FilterConfig(min_trades=NAN), "filters.min_trades"),
    (FilterConfig(max_drawdown_pct=NAN), "filters.max_drawdown_pct"),
    (FilterConfig(min_win_rate=True), "filters.min_win_rate"),
])
def test_r19_invalid_filter_thresholds(filters, field):
    assert_rejected(score(with_(n_trades=1, n_win=1, n_loss=0, win_rate=100.0, gross_loss=0.0,
                                profit_factor=INF, payoff=INF, max_consec_loss=0), filters=filters),
                    kind="INVALID_CONFIG", field=field)
    with pytest.raises(scoring.InvalidScoringConfiguration):
        scoring.validate_scoring_configuration(ScoreWeights(), filters)


def test_r20_infinite_thresholds_used_by_walk_forward_test_scoring_are_valid():
    scoring.validate_scoring_configuration(ScoreWeights(), UNFILTERED)
    assert score(SANE, filters=UNFILTERED)[1] is False


def test_r21_non_finite_computed_score_becomes_a_typed_rejection(monkeypatch):
    monkeypatch.setattr(scoring, "normalize_win_rate", lambda wr: NAN)
    assert_rejected(score(SANE), "NON_FINITE", "computed")


class _PR:
    def __init__(self, name="x", lo=1, hi=10, step=1):
        self.param_type, self.name, self.min_val, self.max_val, self.step = "number", name, lo, hi, step


@pytest.mark.parametrize("params, ranges, kind, field", [
    ({"x": NAN}, [_PR()], "INVALID_METRIC", "param.x"),
    ({"x": "3"}, [_PR()], "INVALID_METRIC", "param.x"),
    ({"x": True}, [_PR()], "INVALID_METRIC", "param.x"),
    ({"x": 3}, [_PR(step=0)], "INVALID_CONFIG", "param_ranges.x"),
    ({"x": 3}, [_PR(step=NAN)], "INVALID_CONFIG", "param_ranges.x"),
    ({"x": 3}, [_PR(lo="1")], "INVALID_CONFIG", "param_ranges.x"),
    ({"x": 3}, [{"param_type": "number", "name": "x", "min_val": 1, "max_val": Decimal(10), "step": 1}],
     "INVALID_CONFIG", "param_ranges.x"),
])
def test_r21c_candidate_parameters_and_ranges_are_validated(params, ranges, kind, field):
    assert_rejected(score(SANE, params=params, param_ranges=ranges), kind=kind, field=field)


def test_r21c_none_parameter_value_keeps_legacy_behaviour():
    assert score(SANE, params={"x": None}, param_ranges=[_PR()]) == score(SANE)


def test_r22_nan_r_squared_no_longer_escapes_its_penalty():
    assert_rejected(score(with_(equity_r_squared=NAN)), "NON_FINITE", "equity_r_squared")


# ── R24 : propriété — aucun invalide n'est éligible, aucune exception ────────────────────────────

_BAD_VALUES = [NAN, INF, -INF, None, "x", True, np.bool_(False), Decimal("1"), Fraction(1, 2), 10**400,
               -1, np.float64("nan"), np.float32("inf")]


def test_r24_no_invalid_candidate_is_ever_eligible_and_compute_score_never_raises():
    rng = random.Random(20261117)
    fields = list(SANE)
    for _ in range(2000):
        field = rng.choice(fields)
        bad = rng.choice(_BAD_VALUES)
        if bad == -1 and field in ("net_ret_pct", "net_ret_usd"):
            continue  # valeur légitime pour ces champs
        result = score(with_(**{field: bad}), filters=rng.choice([FilterConfig(), UNFILTERED]))
        assert result[0] == 0.0 and result[1] is True, (field, bad, result)
        assert result[2].startswith("INVALID_"), (field, bad, result)


# ── Version de sémantique ───────────────────────────────────────────────────────────────────────

def test_scoring_semantics_version_constant():
    assert scoring.SCORING_SEMANTICS_VERSION == "finite-metrics-v1"


# ── R52 : aucun appelant de production ne contourne compute_score ────────────────────────────────

def test_r52_only_known_production_callers_use_scoring_entry_points():
    import ast
    root = Path(__file__).resolve().parents[1]
    callers = {}
    for path in root.glob("*.py"):
        if path.name == "scoring.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
                if name in ("compute_score", "is_filtered_out", "compute_penalties"):
                    callers.setdefault(name, set()).add(path.name)
    assert callers.get("compute_score", set()) <= {"optimizer.py", "walk_forward.py"}
    assert "is_filtered_out" not in callers and "compute_penalties" not in callers


def test_configuration_class_instead_of_instance_is_a_typed_rejection():
    assert_rejected(score(SANE, weights=ScoreWeights), kind="INVALID_CONFIG", field="weights")
    assert_rejected(score(SANE, filters=FilterConfig), kind="INVALID_CONFIG", field="filters")
