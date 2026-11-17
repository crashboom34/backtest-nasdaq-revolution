"""Tests de research_admission (T1-a / A0) : diagnostic expérimental, non bloquant.

Deux familles (contrat, F8) :
- tests de logique, en processus unique, avec un lanceur injecté (`execute_request`) ;
- tests à interpréteur enfant, sous un protocole réduit déclaré dans l'enregistrement : ils ne
  valent que pour ce protocole réduit.
Données synthétiques uniquement. Aucun test n'impose PASS sans couverture suffisante."""
import ast
import inspect
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import research_admission as ra
from tests.research_admission_support import (BASE_PARAMS, PARAM_SETS, REDUCED_PROTOCOL, synthetic_frame,
                                              write_approval, write_strategy)

REPO = os.path.dirname(os.path.abspath(ra.__file__))
CHECKS = ("data", "determinism", "prepare_prefix", "decision_replay", "signal_contract")


@pytest.fixture(autouse=True)
def _output_drive(tmp_path, monkeypatch):
    """Le contrat impose D: ; les tests acceptent le lecteur du répertoire temporaire de pytest."""
    monkeypatch.setattr(ra, "ALLOWED_OUTPUT_DRIVES", (os.path.splitdrive(str(tmp_path))[0].upper(),))


def _setup(tmp_path, name, origin="handwritten"):
    for sub in ("strategies", "operator"):
        (tmp_path / sub).mkdir(exist_ok=True)
    path = write_strategy(tmp_path / "strategies", name)
    return path, write_approval(tmp_path / "operator", path, origin=origin)


def _frames(**kwargs):
    return [{"frame": synthetic_frame(**kwargs), "origin": "synthetic"}]


def _run(tmp_path, name, *, in_process=True, protocol=None, frames=None, param_sets=None, origin="handwritten",
         **kwargs):
    path, approval = _setup(tmp_path, name, origin)
    return ra.run_preflight(
        strategy_path=path, approval_path=approval, param_sets=param_sets or PARAM_SETS,
        frames=frames or _frames(), output_dir=str(tmp_path / "out"), protocol=protocol or REDUCED_PROTOCOL,
        runner=ra.execute_request if in_process else None, **kwargs)


def _refused(tmp_path, name="honest", **overrides):
    """Lance le pré-vol avec un lanceur espion ; rend (enregistrement, appels au lanceur)."""
    calls = []
    path, approval = _setup(tmp_path, name, overrides.pop("origin", "handwritten"))
    arguments = dict(strategy_path=path, approval_path=approval, param_sets=PARAM_SETS, frames=_frames(),
                     output_dir=str(tmp_path / "out"), protocol=REDUCED_PROTOCOL, runner=calls.append)
    arguments.update(overrides)
    return ra.run_preflight(**arguments), calls


def _check(record, name):
    (found,) = [c for c in record["checks"] if c["check"] == name]
    return found


def _assert_shape(record):
    assert [c["check"] for c in record["checks"]] == list(CHECKS)
    assert record["decision"] == ra._final_decision(record["checks"], record["protocol"], record["subject"])
    assert record["evidence_level"] == "EXPERIMENTAL"
    assert record["activation"] == "LIBRARY_ONLY"
    assert record["semantics_version"] == "research-admission-v1"
    assert "non bloquant" in record["notice"]
    assert record["not_covered"] and record["not_prevented"]


# ───────────────────────────── logique pure ─────────────────────────────

def _checks(states):
    return [{"check": n, "state": s, "codes": [], "coordinates": {}, "coverage": {}} for n, s in zip(CHECKS, states)]


def test_decision_is_no_violation_only_when_five_checks_pass():
    assert ra.compute_decision(_checks(["PASS"] * 5)) == "NO_VIOLATION_OBSERVED"
    for bad in ("INCONCLUSIVE", "FAIL"):
        for k in range(5):
            states = ["PASS"] * 5
            states[k] = bad
            assert ra.compute_decision(_checks(states)) == "NOT_ADMITTED"


def test_decision_requires_exactly_the_five_checks_once():
    full = _checks(["PASS"] * 5)
    assert ra.compute_decision(full[:4]) == "NOT_ADMITTED"
    assert ra.compute_decision(full + [full[0]]) == "NOT_ADMITTED"
    assert ra.compute_decision(full[:4] + [dict(full[4], check="other")]) == "NOT_ADMITTED"
    assert ra.compute_decision(full[:4] + [dict(full[4], state="pass")]) == "NOT_ADMITTED"
    assert ra.compute_decision(full[:3] + [full[2], full[4]]) == "NOT_ADMITTED"


def test_no_waiver_parameter_exists():
    names = set(inspect.signature(ra.run_preflight).parameters)
    assert not {n for n in names if any(w in n.lower() for w in ("waiv", "override", "force", "derog", "allow"))}


def test_canonical_json_is_sorted_compact_and_rejects_non_finite():
    assert ra.canonical_json({"b": 1, "a": "é"}) == '{"a":"é","b":1}'.encode("utf-8")
    with pytest.raises(ValueError):
        ra.canonical_json({"a": float("nan")})


def test_data_check_passes_on_clean_synthetic_frame():
    result = ra.check_market_frame(synthetic_frame(), "synthetic")
    assert (result["state"], result["codes"]) == ("PASS", [])


def _set(column, row, value):
    def mutate(frame):
        frame.loc[row, column] = value
    return mutate


@pytest.mark.parametrize("mutate, code", [
    (_set("close", 7, np.nan), "DATA_NON_FINITE"),
    (_set("open", 7, np.inf), "DATA_NON_FINITE"),
    (_set("time", 9, pd.Timestamp("2024-01-02 13:00")), "DATA_TIME_NOT_INCREASING"),
    (_set("high", 5, 1.0), "DATA_OHLC_INCONSISTENT"),
    (lambda f: f.__setitem__("future_ret", f["close"].shift(-1).fillna(0.0)), "DATA_UNDECLARED_COLUMN"),
    (lambda f: f.__setitem__("h_p", 1), "DATA_UNDECLARED_COLUMN"),
])
def test_data_check_fails_with_code(mutate, code):
    frame = synthetic_frame()
    mutate(frame)
    result = ra.check_market_frame(frame, "synthetic")
    assert result["state"] == "FAIL" and code in result["codes"]


def test_data_check_missing_canonical_column_fails():
    result = ra.check_market_frame(synthetic_frame().drop(columns=["volume"]), "synthetic")
    assert result["state"] == "FAIL" and "DATA_UNDECLARED_COLUMN" in result["codes"]


def test_train_excerpt_without_split_plan_is_inconclusive():
    result = ra.check_market_frame(synthetic_frame(), "train_excerpt")
    assert (result["state"], result["codes"]) == ("INCONCLUSIVE", ["DATA_ZONE_UNVERIFIED"])


def _plan(train, holdout, validation=None):
    def boundary(pair):
        return SimpleNamespace(start=pair[0], end=pair[1])
    return SimpleNamespace(train=boundary(train), final_holdout=boundary(holdout),
                           validation=boundary(validation) if validation else None, discovery_oos=None)


def test_train_excerpt_inside_train_zone_passes():
    plan = _plan(("2024-01-01T00:00:00+00:00", "2024-02-01T00:00:00+00:00"),
                 ("2024-03-01T00:00:00+00:00", "2024-04-01T00:00:00+00:00"))
    assert ra.check_market_frame(synthetic_frame(), "train_excerpt", split_plan=plan)["state"] == "PASS"


@pytest.mark.parametrize("train, holdout", [
    (("2023-01-01T00:00:00+00:00", "2024-01-02T14:00:00+00:00"), ("2024-01-02T14:00:00+00:00", "2024-04-01T00:00:00+00:00")),
    (("2023-01-01T00:00:00+00:00", "2023-06-01T00:00:00+00:00"), ("2023-06-01T00:00:00+00:00", "2024-04-01T00:00:00+00:00")),
    (("2024-02-01T00:00:00+00:00", "2024-03-01T00:00:00+00:00"), ("2024-03-01T00:00:00+00:00", "2024-04-01T00:00:00+00:00")),
])
def test_excerpt_outside_train_is_refused_before_any_execution(tmp_path, train, holdout):
    record, calls = _refused(tmp_path, frames=[{"frame": synthetic_frame(), "origin": "train_excerpt"}],
                             split_plan=_plan(train, holdout))
    assert record["decision"] == "NOT_ADMITTED" and record["refusal"] == "DATA_ZONE_FORBIDDEN" and calls == []


def test_unknown_frame_origin_is_refused(tmp_path):
    record, calls = _refused(tmp_path, frames=[{"frame": synthetic_frame(), "origin": "final_holdout"}])
    assert record["decision"] == "NOT_ADMITTED" and record["refusal"] == "DATA_ZONE_FORBIDDEN" and calls == []


def test_future_bars_use_only_the_cut_bar_and_the_amplitude():
    frame = synthetic_frame()
    amplitude = ra.excerpt_amplitude(frame)
    assert amplitude == pytest.approx(3 * float(np.abs(np.diff(frame["close"].to_numpy())).max()))
    cut = 200
    other = frame.copy()
    other.loc[cut + 1:, ["open", "high", "low", "close", "volume"]] = 123.0
    for variant in ("up", "down"):
        short = ra.truncated_frame(frame, cut, 5, amplitude, variant)
        pd.testing.assert_frame_equal(short, ra.truncated_frame(other, cut, 5, amplitude, variant))
        assert len(short) == cut + 6
        pd.testing.assert_frame_equal(short.iloc[: cut + 1], frame.iloc[: cut + 1])
        assert list(short["time"].iloc[cut + 1:]) == list(frame["time"].iloc[cut + 1: cut + 6])
        tail = short.iloc[cut + 1:]
        assert (tail["high"] > tail["low"]).all() and (tail["low"] > 0).all()
        assert (tail["high"] >= tail[["open", "close"]].max(axis=1)).all()
        closes = np.concatenate([[frame["close"].iloc[cut]], tail["close"].to_numpy()])
        if variant == "up":
            assert (np.diff(closes) > 0).all() and (tail["volume"] == 0).all()
        else:
            assert (np.diff(closes) < 0).all()
            assert (tail["volume"] == 10 * frame["volume"].iloc[cut]).all()


def test_dense_windows_are_disjoint_ordered_by_decisions_and_reach_the_floor():
    decisions = [100, 101, 102, 150, 300, 301, 500]
    plan = ra.plan_tested_bars(decision_bars=decisions, first_bar=30, last_bar=600, fingerprint="ab" * 32,
                               protocol=dict(REDUCED_PROTOCOL, n_trace_windows=1, min_decisions=7, sparse_bars=0))
    windows = plan["trace_windows"]
    assert windows[0][0] <= 100 and windows[0][1] > 102
    assert plan["tested_decisions"] == 7 and len(windows) >= 2  # le plancher fait ajouter des fenêtres
    for (start, stop) in windows + plan["independent_windows"]:
        assert stop - start == REDUCED_PROTOCOL["window_bars"] and 30 <= start and stop - 1 <= 600
    ordered = sorted(windows)
    assert all(ordered[k][1] <= ordered[k + 1][0] for k in range(len(ordered) - 1))
    assert set(plan["bars"]) >= {b for (start, stop) in windows for b in range(start, stop)}


def test_tested_bars_depend_only_on_fingerprint_protocol_and_trace():
    args = dict(decision_bars=[100, 140, 300], first_bar=30, last_bar=600, protocol=REDUCED_PROTOCOL)
    assert ra.plan_tested_bars(fingerprint="ab" * 32, **args) == ra.plan_tested_bars(fingerprint="ab" * 32, **args)
    independents = {tuple(ra.plan_tested_bars(fingerprint=f"{k:02x}" * 32, **args)["independent_windows"][0])
                    for k in range(12)}
    assert len(independents) > 1


def test_independent_window_exists_without_decisions_but_floor_is_not_met():
    plan = ra.plan_tested_bars(decision_bars=[], first_bar=30, last_bar=600, fingerprint="cd" * 32,
                               protocol=REDUCED_PROTOCOL)
    assert plan["trace_windows"] == [] and len(plan["independent_windows"]) == 1
    assert plan["tested_decisions"] == 0


def test_budget_caps_the_plan():
    plan = ra.plan_tested_bars(decision_bars=list(range(40, 600, 30)), first_bar=30, last_bar=600,
                               fingerprint="ab" * 32, protocol=dict(REDUCED_PROTOCOL, min_decisions=50), max_bars=60)
    assert len(plan["bars"]) <= 60 and plan["budget_exhausted"] is True


def test_child_environment_is_an_allow_list(monkeypatch, tmp_path):
    monkeypatch.setenv("IG_API_KEY", "x")
    monkeypatch.setenv("BACKTEST_BASE_DIR", "x")
    env = ra.build_child_environment(str(tmp_path))
    assert "IG_API_KEY" not in env and "BACKTEST_BASE_DIR" not in env and "PATH" not in env
    assert ra.secret_like_variables(env) == []
    assert ra.secret_like_variables({"IG_PASSWORD": "x", "SystemRoot": "c"}) == ["IG_PASSWORD"]


# ───────────────────────────── refus (rien n'est exécuté) ─────────────────────────────

def test_unapproved_bytes_are_refused_without_loading(tmp_path, monkeypatch):
    marker = tmp_path / "marker.txt"
    monkeypatch.setenv("T1A_MARKER", str(marker))
    path, approval = _setup(tmp_path, "marker_on_import")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n# retouche après approbation\n")
    record = ra.run_preflight(strategy_path=path, approval_path=approval, param_sets=PARAM_SETS, frames=_frames(),
                              output_dir=str(tmp_path / "out"), protocol=REDUCED_PROTOCOL)
    assert record["decision"] == "NOT_ADMITTED" and record["refusal"] == "STRATEGY_NOT_APPROVED"
    assert all(c["state"] == "INCONCLUSIVE" and c["codes"] == ["NOT_RUN"] for c in record["checks"])
    assert not marker.exists()
    _assert_shape(record)


def test_missing_or_misplaced_approval_is_refused(tmp_path):
    path, approval = _setup(tmp_path, "honest")
    out = tmp_path / "out"
    record, calls = _refused(tmp_path, approval_path=str(tmp_path / "absent.json"))
    assert record["refusal"] == "APPROVAL_INVALID" and calls == []
    out.mkdir()
    inside = out / "approval.json"
    inside.write_bytes(open(approval, "rb").read())
    record, calls = _refused(tmp_path, approval_path=str(inside))
    assert record["refusal"] == "APPROVAL_INVALID" and calls == []
    bad = tmp_path / "operator" / "bad.json"
    bad.write_text(json.dumps({"strategy_path": path, "sha256": "0" * 64}), encoding="utf-8")
    record, calls = _refused(tmp_path, approval_path=str(bad))
    assert record["refusal"] == "APPROVAL_INVALID" and calls == []


def test_approval_under_the_repository_is_refused(tmp_path):
    record, calls = _refused(tmp_path, approval_path=os.path.join(REPO, "pytest.ini"))
    assert record["refusal"] == "APPROVAL_INVALID" and calls == []


def test_generated_origin_is_never_diagnosed_favourably(tmp_path):
    record, calls = _refused(tmp_path, origin="generated")
    assert record["decision"] == "NOT_ADMITTED" and record["refusal"] == "STRATEGY_ORIGIN_GENERATED" and calls == []


def test_dotted_module_name_is_refused(tmp_path):
    record, calls = _refused(tmp_path, strategy_path="strategies.perfect_revolution_v1")
    assert record["refusal"] == "UNSUPPORTED_STRATEGY_CONTRACT" and calls == []


@pytest.mark.parametrize("component", ["results", "dataset_splits", "validations", "experiments", "datasets",
                                       "Results", "gate_v_campaign_x"])
def test_output_dir_under_an_observed_component_is_refused(tmp_path, component):
    target = tmp_path / component / "job_1"
    record, calls = _refused(tmp_path, output_dir=str(target))
    assert record["refusal"] == "OUTPUT_DIR_REFUSED" and calls == [] and not target.exists()


def test_output_dir_inside_a_git_tree_or_on_another_drive_is_refused(tmp_path, monkeypatch):
    assert ra.output_dir_refusal(os.path.join(REPO, "admissions")) is not None
    (tmp_path / "tree" / ".git").mkdir(parents=True)
    assert ra.output_dir_refusal(str(tmp_path / "tree" / "sub" / "out")) is not None
    assert ra.output_dir_refusal(str(tmp_path / "out")) is None
    monkeypatch.setattr(ra, "ALLOWED_OUTPUT_DRIVES", ("Q:",))
    assert ra.output_dir_refusal(str(tmp_path / "out")) is not None


def test_default_output_drive_is_d():
    source = open(os.path.join(REPO, "research_admission.py"), encoding="utf-8").read()
    assert 'ALLOWED_OUTPUT_DRIVES = ("D:",)' in source


def test_insufficient_free_space_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ra, "_free_bytes", lambda path: 10)
    record, calls = _refused(tmp_path)
    assert record["refusal"] == "OUTPUT_DIR_REFUSED" and calls == []


def test_inactive_copy_on_write_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ra, "_copy_on_write_active", lambda: False)
    record, calls = _refused(tmp_path)
    assert record["refusal"] == "ISOLATION_UNAVAILABLE" and calls == []


def test_unknown_protocol_key_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        _run(tmp_path, "honest", protocol=dict(REDUCED_PROTOCOL, waiver=True))


# ───────────────────────────── contrôles, lanceur injecté ─────────────────────────────

def test_honest_probe_shows_no_violation_under_reduced_protocol(tmp_path):
    record = _run(tmp_path, "honest")
    _assert_shape(record)
    assert [(c["check"], c["state"]) for c in record["checks"]] == [(n, "PASS") for n in CHECKS]
    assert record["decision"] == "NO_VIOLATION_OBSERVED_TEST_ONLY"
    assert record["protocol"]["reduced"] is True
    replay = _check(record, "decision_replay")["coverage"]
    assert len(replay["groups"]) == 3
    assert all(g["tested_decisions"] >= REDUCED_PROTOCOL["min_decisions"] and g["replays"] > 0 for g in replay["groups"])
    assert replay["exercised_param_sets"] == [0, 1, 2]
    prefix = _check(record, "prepare_prefix")["coverage"]
    assert "attr:_ref" in prefix["compared_non_trivial"] and prefix["cuts"]
    assert record["subject"]["origin_declared"] == "handwritten"
    stored = os.path.join(str(tmp_path / "out"), "admissions", record["admission_id"] + ".json")
    assert json.loads(open(stored, encoding="utf-8").read())["admission_id"] == record["admission_id"]
    assert not os.listdir(os.path.join(str(tmp_path / "out"), "work"))


def test_same_inputs_give_the_same_admission_id_and_no_path_in_content(tmp_path):
    first = _run(tmp_path, "honest")
    second = _run(tmp_path, "honest")
    assert first == second
    text = ra.canonical_json(first).decode("utf-8")
    assert str(tmp_path) not in text and str(tmp_path).replace("\\", "\\\\") not in text
    assert REPO not in text and REPO.replace("\\", "\\\\") not in text
    assert ra.verify_record(first) == (True, [])


def test_reread_record_is_recomputed_not_trusted(tmp_path):
    record = _run(tmp_path, "peek_onbar")
    assert ra.verify_record(record) == (True, [])
    ok, problems = ra.verify_record(dict(record, decision="NO_VIOLATION_OBSERVED"))
    assert not ok and problems
    forged_checks = [dict(c, state="PASS", codes=[]) for c in record["checks"]]
    ok, problems = ra.verify_record(dict(record, checks=forged_checks, decision="NO_VIOLATION_OBSERVED"))
    assert not ok and problems


@pytest.mark.parametrize("name", ["peek_prepare", "centered_ma"])
def test_prepare_reading_the_future_fails_the_prefix_control(tmp_path, name):
    record = _run(tmp_path, name)
    prefix = _check(record, "prepare_prefix")
    assert prefix["state"] == "FAIL" and "PREPARE_USES_FUTURE" in prefix["codes"]
    assert {"frame", "param_set", "cut", "name", "bar"} <= set(prefix["coordinates"])
    assert record["decision"] == "NOT_ADMITTED"


@pytest.mark.parametrize("name", ["peek_onbar", "peek_i2_guarded", "vol_peek", "rare_peek"])
def test_on_bar_reading_the_future_fails_the_replay_control(tmp_path, name):
    record = _run(tmp_path, name)
    assert _check(record, "determinism")["state"] == "PASS"
    assert _check(record, "prepare_prefix")["state"] == "PASS"
    replay = _check(record, "decision_replay")
    assert replay["state"] == "FAIL" and "DECISION_DEPENDS_ON_FUTURE" in replay["codes"]
    assert {"frame", "param_set", "cut", "variant", "bar"} <= set(replay["coordinates"])
    assert record["decision"] == "NOT_ADMITTED"


def test_non_deterministic_strategy_fails_and_downstream_controls_are_not_run(tmp_path):
    record = _run(tmp_path, "random_entry")
    determinism = _check(record, "determinism")
    assert determinism["state"] == "FAIL" and "STRATEGY_NOT_DETERMINISTIC" in determinism["codes"]
    for name in ("prepare_prefix", "decision_replay", "signal_contract"):
        assert (_check(record, name)["state"], _check(record, name)["codes"]) == ("INCONCLUSIVE", ["NOT_RUN"])
    assert record["decision"] == "NOT_ADMITTED"


def test_invalid_signal_fails_the_signal_contract(tmp_path):
    record = _run(tmp_path, "bad_signal")
    signal = _check(record, "signal_contract")
    assert signal["state"] == "FAIL" and signal["codes"] == ["SIGNAL_INVALID"]
    assert record["decision"] == "NOT_ADMITTED"


def test_strategy_without_array_passes_prefix_by_declared_vacuity(tmp_path):
    record = _run(tmp_path, "no_array")
    prefix = _check(record, "prepare_prefix")
    assert prefix["state"] == "PASS" and prefix["codes"] == ["NO_NON_TRIVIAL_ARRAY_EXPOSED"]
    assert prefix["coverage"]["vacuous"] is True
    assert _check(record, "decision_replay")["state"] == "PASS"


def test_strategy_raising_on_full_data_is_inconclusive_not_fail(tmp_path):
    record = _run(tmp_path, "raises_always")
    determinism = _check(record, "determinism")
    assert (determinism["state"], determinism["codes"]) == ("INCONCLUSIVE", ["STRATEGY_RAISES"])
    assert record["decision"] == "NOT_ADMITTED"
    assert "missing column" not in ra.canonical_json(record).decode("utf-8")


def test_fewer_than_three_exercised_sets_is_inconclusive(tmp_path):
    record = _run(tmp_path, "honest", param_sets=PARAM_SETS[:2])
    replay = _check(record, "decision_replay")
    assert replay["state"] == "INCONCLUSIVE" and "PARAM_SETS_NOT_EXERCISED" in replay["codes"]
    assert record["decision"] == "NOT_ADMITTED"


def test_param_set_without_decisions_is_listed_and_does_not_count(tmp_path):
    silent = dict(BASE_PARAMS, thr=50.0)
    record = _run(tmp_path, "honest", param_sets=PARAM_SETS[:2] + [silent])
    replay = _check(record, "decision_replay")
    assert replay["state"] == "INCONCLUSIVE" and "PARAM_SETS_NOT_EXERCISED" in replay["codes"]
    assert replay["coverage"]["exercised_param_sets"] == [0, 1]
    assert replay["coverage"]["not_exercised_param_sets"] == [2]


def test_floor_not_reached_is_inconclusive_never_pass(tmp_path):
    record = _run(tmp_path, "honest", frames=_frames(n_bars=150), protocol=dict(REDUCED_PROTOCOL, min_decisions=500))
    replay = _check(record, "decision_replay")
    assert replay["state"] == "INCONCLUSIVE" and record["decision"] == "NOT_ADMITTED"
    assert set(replay["codes"]) & {"NO_DECISION_EXERCISED", "PARAM_SETS_NOT_EXERCISED"}


def test_budget_exhausted_before_the_floor_is_inconclusive(tmp_path):
    record = _run(tmp_path, "honest", protocol=dict(REDUCED_PROTOCOL, max_replays=40))
    replay = _check(record, "decision_replay")
    assert replay["state"] == "INCONCLUSIVE" and "BUDGET_EXCEEDED" in replay["codes"]


def test_excerpt_shorter_than_warmup_is_inconclusive(tmp_path):
    record = _run(tmp_path, "honest", frames=_frames(n_bars=18))
    assert record["decision"] == "NOT_ADMITTED"
    assert all(c["state"] != "FAIL" for c in record["checks"])
    assert "EXCERPT_TOO_SHORT_FOR_WARMUP" in _check(record, "decision_replay")["codes"]


def test_runner_failure_never_gives_pass(tmp_path):
    def broken(request):
        raise OSError("launcher unavailable")
    record, _calls = _refused(tmp_path, runner=broken)
    assert record["decision"] == "NOT_ADMITTED"
    assert _check(record, "determinism")["state"] == "INCONCLUSIVE"
    assert all(c["state"] != "PASS" for c in record["checks"] if c["check"] != "data")


def test_data_failure_stops_before_any_strategy_execution(tmp_path):
    frame = synthetic_frame()
    frame.loc[5, "close"] = np.nan
    record, calls = _refused(tmp_path, frames=[{"frame": frame, "origin": "synthetic"}])
    assert _check(record, "data")["state"] == "FAIL" and calls == []
    assert all(_check(record, n)["codes"] == ["NOT_RUN"] for n in CHECKS[1:])


def test_existing_record_is_never_overwritten(tmp_path):
    record = _run(tmp_path, "honest")
    stored = os.path.join(str(tmp_path / "out"), "admissions", record["admission_id"] + ".json")
    with open(stored, "ab") as handle:
        handle.write(b" ")
    with pytest.raises(FileExistsError):
        _run(tmp_path, "honest")
    assert open(stored, "rb").read().endswith(b" ")


# ───────────────────────────── cas adverses issus de la revue du code ─────────────────────────────

def test_duplicate_param_sets_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        _run(tmp_path, "honest", param_sets=[BASE_PARAMS, dict(BASE_PARAMS), dict(BASE_PARAMS)])


def test_state_kept_between_instances_of_one_module_fails_determinism(tmp_path):
    determinism = _check(_run(tmp_path, "state_counter"), "determinism")
    assert (determinism["state"], determinism["codes"]) == ("FAIL", ["STATE_LEAKS_BETWEEN_RUNS"])


def test_state_kept_between_replays_fails_the_replay_control(tmp_path):
    record = _run(tmp_path, "modstate_onbar")
    assert _check(record, "determinism")["state"] == "PASS"
    replay = _check(record, "decision_replay")
    assert (replay["state"], replay["codes"]) == ("FAIL", ["STATE_LEAKS_BETWEEN_RUNS"])


def test_prefix_gap_that_changes_no_decision_is_inconclusive(tmp_path):
    record = _run(tmp_path, "unstable_unused")
    prefix = _check(record, "prepare_prefix")
    assert (prefix["state"], prefix["codes"]) == ("INCONCLUSIVE", ["PREPARE_NOT_BITWISE_STABLE"])
    assert prefix["coordinates"]["name"] == "attr:_x" and record["decision"] == "NOT_ADMITTED"


def test_scalar_depending_on_length_is_inconclusive(tmp_path):
    prefix = _check(_run(tmp_path, "length_scalar"), "prepare_prefix")
    assert (prefix["state"], prefix["codes"]) == ("INCONCLUSIVE", ["PREPARE_SCALAR_DEPENDS_ON_LENGTH"])


def test_data_left_by_prepare_that_cannot_be_compared_is_never_pass(tmp_path):
    record = _run(tmp_path, "opaque_diff")
    prefix = _check(record, "prepare_prefix")
    assert (prefix["state"], prefix["codes"]) == ("INCONCLUSIVE", ["PREPARE_STATE_NOT_COMPARABLE"])
    assert prefix["coverage"]["not_compared_data"] == ["attr:_r"] and record["decision"] == "NOT_ADMITTED"


def test_empty_mapping_is_not_a_decision(tmp_path):
    record = _run(tmp_path, "empty_dict")
    assert _check(record, "signal_contract")["codes"] == ["NO_DECISION_EXERCISED"]
    assert _check(record, "decision_replay")["state"] == "INCONCLUSIVE" and record["decision"] == "NOT_ADMITTED"


def test_strategy_raising_during_replay_is_inconclusive_with_coordinates(tmp_path):
    replay = _check(_run(tmp_path, "raises_in_replay"), "decision_replay")
    assert replay["state"] == "INCONCLUSIVE" and "STRATEGY_RAISES" in replay["codes"]
    assert {"frame", "param_set", "cut", "variant"} <= set(replay["coordinates"])


def test_ok_response_without_the_requested_replays_is_not_trusted(tmp_path):
    def lazy(request):
        if request["role"] == "replay":
            return {"status": "ok", "replays": 0, "violation": None, "audit": []}
        return ra.execute_request(request)
    record, _ = _refused(tmp_path, runner=lazy)
    replay = _check(record, "decision_replay")
    assert replay["state"] == "INCONCLUSIVE" and "ISOLATION_UNAVAILABLE" in replay["codes"]
    assert record["decision"] == "NOT_ADMITTED"


def test_malformed_full_response_is_not_trusted(tmp_path):
    record, _ = _refused(tmp_path, runner=lambda request: {"status": "ok", "trace": [], "same_fresh": 1})
    assert _check(record, "determinism")["codes"] == ["ISOLATION_UNAVAILABLE"]


def test_approved_local_module_with_wrong_hash_is_refused(tmp_path):
    path, _approval = _setup(tmp_path, "honest")
    helper = tmp_path / "strategies" / "helper.py"
    helper.write_text("X = 1\n", encoding="utf-8")
    approval = tmp_path / "operator" / "with_module.json"
    digest = __import__("hashlib").sha256(open(path, "rb").read()).hexdigest()
    approval.write_text(json.dumps({"strategy_path": path, "sha256": digest, "origin": "handwritten",
                                    "local_modules": {str(helper): "0" * 64}}), encoding="utf-8")
    record, calls = _refused(tmp_path, approval_path=str(approval))
    assert record["refusal"] == "STRATEGY_NOT_APPROVED" and calls == []


def test_engine_changing_during_the_run_is_inconclusive(tmp_path, monkeypatch):
    seen = []

    def drifting(path):
        seen.append(path)
        return f"{len(seen):064d}"
    monkeypatch.setattr(ra, "normalised_sha256", drifting)
    record = _run(tmp_path, "honest")
    determinism = _check(record, "determinism")
    assert determinism["state"] == "INCONCLUSIVE" and "ENGINE_ERROR" in determinism["codes"]
    assert record["decision"] == "NOT_ADMITTED"


def test_import_gate_refuses_an_unapproved_repo_module_before_it_runs(monkeypatch):
    engine_file = os.path.normcase(os.path.realpath(os.path.join(REPO, "engine.py")))
    monkeypatch.setitem(ra._GUARD, "repo", REPO)
    monkeypatch.setitem(ra._GUARD, "allowed", {engine_file})
    monkeypatch.setitem(ra._GUARD, "blocked", [])
    assert ra._ImportGate.find_spec("walk_forward") is None  # garde désarmée : aucun effet
    monkeypatch.setitem(ra._GUARD, "armed", True)
    with pytest.raises(ImportError):
        ra._ImportGate.find_spec("walk_forward")
    assert ra._GUARD["blocked"] == ["walk_forward"]
    assert ra._ImportGate.find_spec("engine") is None and ra._ImportGate.find_spec("json") is None
    assert ra._GUARD["blocked"] == ["walk_forward"]


def test_local_module_rule_exempts_an_installed_environment_inside_the_repository():
    assert ra._is_local(os.path.join(REPO, "engine.py"), REPO) is True
    assert ra._is_local(os.path.join(REPO, ".venv", "Lib", "site-packages", "pandas", "__init__.py"), REPO) is False
    # hors du dépôt mais ni bibliothèque standard ni paquet installé : code local, haché et soumis à approbation
    assert ra._is_local(os.path.join(os.path.dirname(REPO), "elsewhere.py"), REPO) is True
    assert ra._is_local(os.__file__, REPO) is False and ra._is_local(np.__file__, REPO) is False
    assert ra._is_local(os.path.join(sys.prefix, "Lib", "x.py"), REPO) is False


def test_zero_dimensional_array_left_by_prepare_is_not_a_harness_error(tmp_path):
    from tests.research_admission_support import SPECS, _HD, _HP, _STOP
    SPECS["zero_dim"] = (True, "import numpy as np", _HP + "\n        self._z = np.array(3.0)", _HD, _STOP)
    try:
        prefix = _check(_run(tmp_path, "zero_dim"), "prepare_prefix")
    finally:
        del SPECS["zero_dim"]
    assert (prefix["state"], prefix["codes"]) == ("INCONCLUSIVE", ["PREPARE_STATE_NOT_COMPARABLE"])


def test_real_drive_rule_refuses_the_system_drive(monkeypatch):
    monkeypatch.setattr(ra, "ALLOWED_OUTPUT_DRIVES", ("D:",))
    assert ra.output_dir_refusal("C:\\AlphaForge\\out") is not None
    assert ra.output_dir_refusal("\\\\server\\share\\out") is not None


def test_injected_runner_and_reduced_protocol_are_declared(tmp_path):
    record = _run(tmp_path, "peek_onbar")
    assert record["subject"]["runner"] == "injected_in_process" and record["protocol"]["reduced"] is True
    text = ra.format_record(record)
    assert "PROTOCOLE RÉDUIT" in text and "LANCEUR INJECTÉ" in text
    assert ra._resolve_protocol(None)["reduced"] is False
    assert ra._resolve_protocol({"max_replays": 10, "timeout_s": 5})["reduced"] is False
    assert ra._resolve_protocol({"min_decisions": 9})["reduced"] is True
    assert "min_exercised_sets" not in ra.DEFAULT_PROTOCOL and ra.MIN_EXERCISED_SETS == 3


def test_stripped_record_does_not_verify(tmp_path):
    record = _run(tmp_path, "peek_onbar")
    for key in ("not_covered", "not_prevented", "notice", "protocol"):
        stripped = {k: v for k, v in record.items() if k != key}
        stripped["admission_id"] = ra._record_id(stripped)  # identité recalculée : cohérent avec lui-même
        ok, problems = ra.verify_record(stripped)
        assert ok is False and key in problems


def test_manual_command_refuses_a_reduced_protocol(tmp_path):
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"min_decisions": 1}), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, os.path.join(REPO, "research_admission.py"), "--strategy", "s.py", "--approval", "a.json",
         "--params-json", "p.json", "--frame-csv", "f.csv", "--frame-origin", "synthetic",
         "--protocol-json", str(protocol), "--output-dir", str(tmp_path / "out")],
        capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, PYTHONUTF8="1"), timeout=120,
        check=False)
    assert done.returncode == 2 and "protocole réduit refusé" in done.stderr
    assert not (tmp_path / "out").exists()


def test_child_processes_refuse_a_swallowed_unapproved_import(tmp_path):
    determinism = _check(_run(tmp_path, "lazy_import", in_process=False), "determinism")
    assert determinism["state"] == "INCONCLUSIVE" and "STRATEGY_IMPORT_NOT_APPROVED" in determinism["codes"]


def test_child_process_response_written_by_the_strategy_is_not_trusted(tmp_path):
    record = _run(tmp_path, "forged_response", in_process=False)
    determinism = _check(record, "determinism")
    assert determinism["state"] == "INCONCLUSIVE" and "ISOLATION_UNAVAILABLE" in determinism["codes"]
    assert record["decision"] == "NOT_ADMITTED"


# ───────────────────────────── module : contraintes du dépôt ─────────────────────────────

def test_module_calls_no_pinned_writer_and_contains_no_forbidden_substring():
    source = open(os.path.join(REPO, "research_admission.py"), encoding="utf-8").read()
    names = {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
             for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)}
    assert not names & {"save_atomic", "save_atomic_overwrite", "save_exclusive"}
    for forbidden in ("gate_v_audit_protocol", "gate_v_k1s2_", "gate_v_exposure_interpreters_v5",
                      "gate_v_exposure_interpreters_v6", "interpret_audit_roots_v5", "interpret_audit_roots_v6",
                      "atomic_json_store", "optimizer", "walk_forward", "ADMITTED_EXPERIMENTAL"):
        assert forbidden not in source


def test_no_existing_entry_point_calls_the_module():
    for name in ("engine.py", "optimizer.py", "optimizer_process.py", "app.py", "walk_forward.py", "validation_oos.py"):
        assert "research_admission" not in open(os.path.join(REPO, name), encoding="utf-8").read()


# ───────────────────────────── interpréteurs enfants (protocole réduit) ─────────────────────────────

def test_child_processes_honest_probe_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("T1A_LEAK", "1")
    record = _run(tmp_path, "env_probe", in_process=False)
    assert [(c["check"], c["state"], c["codes"]) for c in record["checks"]] == [(n, "PASS", []) for n in CHECKS]
    assert record["decision"] == "NO_VIOLATION_OBSERVED_TEST_ONLY"  # protocole réduit : jamais le libellé favorable simple
    assert record["subject"]["engine_sha256"] == ra.normalised_sha256(os.path.join(REPO, "engine.py"))
    assert not os.listdir(os.path.join(str(tmp_path / "out"), "work"))
    again = _run(tmp_path, "env_probe", in_process=False)
    assert again["admission_id"] == record["admission_id"]


def test_child_processes_detect_on_bar_peek(tmp_path):
    record = _run(tmp_path, "peek_onbar", in_process=False)
    assert "DECISION_DEPENDS_ON_FUTURE" in _check(record, "decision_replay")["codes"]
    assert record["decision"] == "NOT_ADMITTED"


def test_child_processes_detect_module_cache(tmp_path):
    record = _run(tmp_path, "modcache_peek", in_process=False)
    assert record["decision"] == "NOT_ADMITTED" and record["subject"]["runner"] == "child_interpreters"
    assert _check(record, "decision_replay")["state"] == "FAIL"


def test_child_processes_flag_disk_cache_as_side_effect(tmp_path):
    record = _run(tmp_path, "diskcache_peek", in_process=False)
    assert record["decision"] == "NOT_ADMITTED"
    assert any("SIDE_EFFECT_DETECTED" in c["codes"] for c in record["checks"])


def test_child_processes_refuse_unapproved_local_import(tmp_path):
    record = _run(tmp_path, "imports_unapproved", in_process=False)
    determinism = _check(record, "determinism")
    assert determinism["state"] == "INCONCLUSIVE" and "STRATEGY_IMPORT_NOT_APPROVED" in determinism["codes"]
    assert record["decision"] == "NOT_ADMITTED"


def test_child_process_timeout_kills_the_tree_and_is_inconclusive(tmp_path):
    record = _run(tmp_path, "sleeper", in_process=False, protocol=dict(REDUCED_PROTOCOL, timeout_s=4), keep_work=True)
    determinism = _check(record, "determinism")
    assert determinism["state"] == "INCONCLUSIVE" and "HARNESS_TIMEOUT" in determinism["codes"]
    pids = []
    for root, _dirs, files in os.walk(str(tmp_path / "out" / "work")):
        pids += [int(open(os.path.join(root, f)).read()) for f in files if f == "child.pid"]
    assert pids and not any(ra.process_alive(pid) for pid in pids)


def test_manual_command_prints_the_diagnostic_and_its_limits(tmp_path):
    path, approval = _setup(tmp_path, "peek_onbar")
    frame_csv = tmp_path / "operator" / "frame.csv"
    synthetic_frame().to_csv(frame_csv, index=False)
    params = tmp_path / "operator" / "params.json"
    params.write_text(json.dumps(PARAM_SETS), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, os.path.join(REPO, "research_admission.py"), "--strategy", path, "--approval", approval,
         "--params-json", str(params), "--frame-csv", str(frame_csv), "--frame-origin", "synthetic",
         "--output-dir", str(tmp_path / "out")],
        capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, PYTHONUTF8="1"), timeout=600,
        check=False)
    assert done.returncode == 1, done.stderr
    assert "NOT_ADMITTED" in done.stdout and "non bloquant" in done.stdout and "LIBRARY_ONLY" in done.stdout
    if os.path.splitdrive(str(tmp_path))[0].upper() == "D:":
        assert "DECISION_DEPENDS_ON_FUTURE" in done.stdout
    else:
        assert "OUTPUT_DIR_REFUSED" in done.stdout


@pytest.mark.skipif(os.environ.get("T1A_RUN_REFERENCE_CALIBRATION") != "1",
                    reason="calibrage de la stratégie de référence au protocole par défaut : optionnel, plusieurs minutes")
def test_reference_strategy_at_default_protocol_optional(tmp_path):
    from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
    source = os.path.join(REPO, "strategies", "perfect_revolution_v1.py")
    (tmp_path / "operator").mkdir()
    approval = write_approval(tmp_path / "operator", source)
    sets = [dict(DEFAULT_PARAMS), dict(DEFAULT_PARAMS, stop_pct=1.0, target_pct=5.0, ema_trend_len=100),
            dict(DEFAULT_PARAMS, stop_pct=1.5, target_pct=8.0, ema_filter_len=30, break_buffer=10.0)]
    frames = [{"frame": synthetic_frame(n_bars=3040, seed=s, vol=15.0), "origin": "synthetic"} for s in (7, 11, 13)]
    record = ra.run_preflight(strategy_path=source, approval_path=approval, param_sets=sets, frames=frames,
                              output_dir=str(tmp_path / "out"))
    print(json.dumps([(c["check"], c["state"], c["codes"]) for c in record["checks"]]))
    assert all(c["state"] != "FAIL" for c in record["checks"]), record["checks"]
