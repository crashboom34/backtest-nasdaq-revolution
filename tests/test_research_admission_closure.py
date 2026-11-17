"""Tests de clôture de research_admission (T1-a / A0), ajoutés après la revue indépendante du
2026-11-16 : extraits dupliqués, plancher de décisions, jeux équivalents, libellé du protocole réduit,
modules locaux hors dépôt, interruption du harnais, réponses mal formées, restitution.
Données synthétiques uniquement."""
import hashlib
import json
import os
import subprocess
import sys

import pandas as pd
import pytest

import research_admission as ra
from tests import research_admission_support as support
from tests.research_admission_support import BASE_PARAMS, PARAM_SETS, REDUCED_PROTOCOL, synthetic_frame
from tests.test_research_admission import CHECKS, _check, _output_drive, _refused, _run, _setup  # noqa: F401


def _sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


# ───────────────────────────── extraits dupliqués ou chevauchants ─────────────────────────────

def test_identical_or_overlapping_excerpts_are_refused_before_any_run(tmp_path):
    frame = synthetic_frame()
    cases = {"same": [frame, frame], "overlap": [frame, frame.iloc[200:].reset_index(drop=True)]}
    for label, frames in cases.items():
        (tmp_path / label).mkdir()
        record, calls = _refused(tmp_path / label, frames=[{"frame": f, "origin": "synthetic"} for f in frames])
        assert record["refusal"] == "DATA_FRAMES_OVERLAP", label
        assert record["decision"] == "NOT_ADMITTED" and calls == [], label


def test_distinct_excerpts_are_not_refused_as_overlapping(tmp_path):
    frames = [{"frame": synthetic_frame(seed=seed), "origin": "synthetic"} for seed in (5, 6)]
    record, _calls = _refused(tmp_path, frames=frames)
    assert record["refusal"] is None


# ───────────────────────────── plancher de décisions ─────────────────────────────

def test_exercised_floor_boundary_is_inclusive_and_per_parameter_set():
    assert ra._exercised_param_sets([10, 10, 9], 10) == [0, 1]
    assert ra._exercised_param_sets([10, 10, 10], 10) == [0, 1, 2]
    assert ra._exercised_param_sets([11, 10, 9], 10) == [0, 1]
    assert ra._exercised_param_sets([0, 5, 5], 0) == [1, 2]  # zéro décision ne compte jamais


def test_floor_one_below_is_inconclusive_and_the_floor_itself_passes(tmp_path):
    first = _run(tmp_path, "honest")
    counts = _check(first, "decision_replay")["coverage"]["tested_decisions_by_param_set"]
    assert len(counts) == 3 and min(counts) > 0
    at_floor = _run(tmp_path, "honest", protocol=dict(REDUCED_PROTOCOL, min_decisions=min(counts)))
    assert _check(at_floor, "decision_replay")["state"] == "PASS"
    # Le plan des fenêtres dépend du plancher : les comptes sont relus dans chaque enregistrement.
    for floor in (min(counts) + 1, max(counts) + 1, 10_000):
        above = _run(tmp_path, "honest", protocol=dict(REDUCED_PROTOCOL, min_decisions=floor))
        replay = _check(above, "decision_replay")
        seen = replay["coverage"]["tested_decisions_by_param_set"]
        assert replay["coverage"]["exercised_param_sets"] == [k for k, c in enumerate(seen) if c >= floor]
        if len(replay["coverage"]["exercised_param_sets"]) < ra.MIN_EXERCISED_SETS:
            assert replay["state"] == "INCONCLUSIVE" and "PARAM_SETS_NOT_EXERCISED" in replay["codes"]
            assert above["decision"] == "NOT_ADMITTED"
        else:
            assert replay["state"] == "PASS"
    assert replay["state"] == "INCONCLUSIVE" and above["decision"] == "NOT_ADMITTED"  # plancher hors d'atteinte


def test_value_equivalent_parameter_sets_do_not_count_as_distinct(tmp_path):
    equivalent = [dict(BASE_PARAMS), dict(BASE_PARAMS, lookback=10.0), dict(BASE_PARAMS, zz=1)]
    record = _run(tmp_path, "honest", param_sets=equivalent)
    replay = _check(record, "decision_replay")
    assert replay["state"] == "INCONCLUSIVE" and "PARAM_SETS_NOT_DISTINCT" in replay["codes"]
    assert replay["coverage"]["indistinguishable_param_sets"] == [[0, 1, 2]]
    assert record["decision"] == "NOT_ADMITTED"


# ───────────────────────────── libellé du protocole réduit ─────────────────────────────

def _passing_checks():
    return [{"check": n, "state": "PASS", "codes": [], "coordinates": {}, "coverage": {}} for n in CHECKS]


def test_final_decision_label_depends_on_protocol_and_runner():
    plain, child = {"reduced": False}, {"runner": "child_interpreters"}
    assert ra._final_decision(_passing_checks(), plain, child) == "NO_VIOLATION_OBSERVED"
    assert ra._final_decision(_passing_checks(), {"reduced": True}, child) == "NO_VIOLATION_OBSERVED_TEST_ONLY"
    assert ra._final_decision(_passing_checks(), plain, {"runner": "injected_in_process"}) \
        == "NO_VIOLATION_OBSERVED_TEST_ONLY"
    broken = _passing_checks()
    broken[3]["state"] = "INCONCLUSIVE"
    assert ra._final_decision(broken, {"reduced": True}, child) == "NOT_ADMITTED"
    assert ra._final_decision(_passing_checks(), plain, None) == "NO_VIOLATION_OBSERVED"


def test_reduced_record_is_labelled_and_cannot_be_relabelled(tmp_path):
    record = _run(tmp_path, "honest")
    assert record["decision"] == "NO_VIOLATION_OBSERVED_TEST_ONLY"
    assert ra.verify_record(record) == (True, [])
    forged = dict(record, decision="NO_VIOLATION_OBSERVED")
    forged["admission_id"] = ra._record_id(forged)
    ok, problems = ra.verify_record(forged)
    assert not ok and "decision" in problems
    assert "NO_VIOLATION_OBSERVED_TEST_ONLY" in ra.format_record(record)


# ───────────────────────────── restitution ─────────────────────────────

def test_rendering_carries_the_unimplemented_controls_and_the_coverage(tmp_path):
    record = _run(tmp_path, "honest")
    text = ra.format_record(record)
    for item in ra.NOT_IMPLEMENTED_AT_A0:
        assert item in text
    counts = _check(record, "decision_replay")["coverage"]["tested_decisions_by_param_set"]
    assert f"décisions testées par jeu : {counts}" in text and "plancher" in text
    assert "not_covered" in text and "not_prevented" in text


# ───────────────────────────── modules locaux hors dépôt (interpréteurs enfants) ─────────────────────────────

def _helper_strategy(monkeypatch, tmp_path, name):
    helpers = tmp_path / "helpers"
    helpers.mkdir(exist_ok=True)
    helper = helpers / "helperx.py"
    helper.write_text("X = 1\n", encoding="utf-8")
    header = f"import sys\nsys.path.insert(0, {str(helpers)!r})\nimport helperx"
    monkeypatch.setitem(support.SPECS, name, (True, header, support._HP, support._HD, support._STOP))
    return helper


def _run_child_with_modules(tmp_path, name, modules):
    path, approval = _setup(tmp_path, name)
    data = json.loads(open(approval, encoding="utf-8").read())
    data["local_modules"] = {os.path.realpath(m): _sha(m) for m in modules}
    with open(approval, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return ra.run_preflight(strategy_path=path, approval_path=approval, param_sets=PARAM_SETS,
                            frames=[{"frame": synthetic_frame(), "origin": "synthetic"}],
                            output_dir=str(tmp_path / "out"), protocol=REDUCED_PROTOCOL)


def test_unapproved_module_outside_the_repository_is_refused(tmp_path, monkeypatch):
    _helper_strategy(monkeypatch, tmp_path, "use_helper")
    record = _run_child_with_modules(tmp_path, "use_helper", [])
    determinism = _check(record, "determinism")
    assert determinism["state"] == "INCONCLUSIVE" and "STRATEGY_IMPORT_NOT_APPROVED" in determinism["codes"]
    assert record["decision"] == "NOT_ADMITTED"


def test_approved_module_outside_the_repository_is_accepted_and_hashed(tmp_path, monkeypatch):
    helper = _helper_strategy(monkeypatch, tmp_path, "use_helper")
    record = _run_child_with_modules(tmp_path, "use_helper", [helper])
    assert [c["state"] for c in record["checks"]] == ["PASS"] * 5
    loaded = record["subject"]["loaded_local_modules"]
    assert loaded.get(f"external/{_sha(helper)[:12]}/helperx.py") == _sha(helper)
    assert str(tmp_path) not in ra.canonical_json(record).decode("utf-8").replace("\\\\", "\\")


def test_approved_module_changed_after_the_parent_check_is_refused(tmp_path, monkeypatch):
    helper = _helper_strategy(monkeypatch, tmp_path, "use_helper")
    original, done = ra._ChildRunner._attempt, []

    def tamper_once(self, request):
        if not done:
            done.append(True)
            with open(helper, "a", encoding="utf-8") as handle:
                handle.write("# modifié après la vérification du parent\n")
        return original(self, request)
    monkeypatch.setattr(ra._ChildRunner, "_attempt", tamper_once)
    record = _run_child_with_modules(tmp_path, "use_helper", [helper])
    determinism = _check(record, "determinism")
    assert determinism["state"] == "INCONCLUSIVE" and "STRATEGY_IMPORT_NOT_APPROVED" in determinism["codes"]


# ───────────────────────────── lancement des enfants ─────────────────────────────

class _FakeProcess:
    pid = 4242
    returncode = None

    def __init__(self, wait_behaviour):
        self._behaviour, self.killed, self.waits = wait_behaviour, False, []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self._behaviour(self, timeout)

    def kill(self):
        self.killed = True
        self.returncode = -9


def _fake_popen(monkeypatch, process):
    captured = {}

    def factory(args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        return process
    monkeypatch.setattr(ra.subprocess, "Popen", factory)
    return captured


def test_interrupted_harness_kills_the_child_tree_and_reraises(tmp_path, monkeypatch):
    def interrupted(process, timeout):
        if len(process.waits) == 1:
            raise KeyboardInterrupt
        return 0
    process, killed = _FakeProcess(interrupted), []
    _fake_popen(monkeypatch, process)
    monkeypatch.setattr(ra, "_kill_tree", killed.append)
    with pytest.raises(KeyboardInterrupt):
        ra._ChildRunner(str(tmp_path), sys.executable, 5)._attempt({"role": "full"})
    assert killed == [4242]


def test_waits_after_a_timeout_are_bounded_and_fall_back_to_kill(tmp_path, monkeypatch):
    def never_ends(process, timeout):
        if process.killed:
            return 0
        raise subprocess.TimeoutExpired("x", timeout)
    process, killed = _FakeProcess(never_ends), []
    _fake_popen(monkeypatch, process)
    monkeypatch.setattr(ra, "_kill_tree", killed.append)
    response = ra._ChildRunner(str(tmp_path), sys.executable, 5)._attempt({"role": "full"})
    assert killed == [4242] and process.killed is True
    assert response["status"] == "error" and response["error"]["origin"] == "timeout"
    assert len(process.waits) >= 2 and all(timeout is not None for timeout in process.waits)


def test_child_launch_uses_the_pinned_flags_and_the_whitelisted_environment(tmp_path, monkeypatch):
    process = _FakeProcess(lambda p, t: 0)
    process.returncode = 0
    captured = _fake_popen(monkeypatch, process)
    ra._ChildRunner(str(tmp_path), sys.executable, 5)._attempt({"role": "full"})
    assert captured["args"][1:4] == ["-s", "-P", "-B"] and captured["args"][5] == "--worker"
    env = captured["kwargs"]["env"]
    expected = {"TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "PYTHONHASHSEED",
                "PYTHONPYCACHEPREFIX"}
    assert set(env) - {"SystemRoot"} == expected and env["PYTHONHASHSEED"] == "0"
    assert os.path.realpath(env["PYTHONPYCACHEPREFIX"]).startswith(os.path.realpath(str(tmp_path)))
    assert captured["kwargs"]["stdout"] is subprocess.DEVNULL and captured["kwargs"]["stdin"] is subprocess.DEVNULL


def test_worker_option_cannot_be_reached_by_abbreviation():
    with pytest.raises(SystemExit) as raised:
        ra.main(["--work", "request.json"])
    assert raised.value.code == 2


# ───────────────────────────── réponses mal formées ─────────────────────────────

@pytest.mark.parametrize("response", [
    {"status": "error", "error": {"origin": []}},
    {"status": "error", "error": "texte"},
    {"status": "error"},
    {"status": "ok", "same_fresh": True, "same_module": True, "trace": []},
    {"status": "ok", "same_fresh": True, "same_module": True, "trace": [], "prefix": 3},
])
def test_malformed_child_response_is_inconclusive_not_a_crash(response):
    request = {"role": "full", "approved_digests": []}
    assert ra._call(lambda _request: dict(response), request) == (None, ["ISOLATION_UNAVAILABLE"])


def test_deeply_nested_response_file_is_unreadable_not_a_crash(tmp_path):
    path = tmp_path / "response.json"
    path.write_text("[" * 200000 + "]" * 200000, encoding="utf-8")
    assert ra._read_response_file(str(path)) is None
    path.write_text('{"status": "error"}', encoding="utf-8")
    assert ra._read_response_file(str(path)) == {"status": "error"}


def test_ragged_list_left_by_prepare_is_not_a_harness_error(tmp_path, monkeypatch):
    monkeypatch.setitem(support.SPECS, "ragged", (True, "", support._HP + "\n        self._g = [[1], [1, 2]]",
                                                  support._HD, support._STOP))
    prefix = _check(_run(tmp_path, "ragged"), "prepare_prefix")
    assert (prefix["state"], prefix["codes"]) == ("INCONCLUSIVE", ["PREPARE_STATE_NOT_COMPARABLE"])


# ───────────────────────────── seconde revue des correctifs ─────────────────────────────

def test_parameter_sets_differing_only_by_int_or_float_do_not_count_as_distinct(tmp_path):
    """La stratégie de sonde recopie `stop_pct` et `target_pct` dans ses signaux : `2` et `2.0` y diffèrent."""
    sets = [dict(BASE_PARAMS, stop_pct=2, target_pct=3), dict(BASE_PARAMS, stop_pct=2.0, target_pct=3.0),
            dict(BASE_PARAMS, stop_pct=2, target_pct=3.0)]
    record = _run(tmp_path, "honest", param_sets=sets)
    replay = _check(record, "decision_replay")
    assert replay["state"] == "INCONCLUSIVE" and "PARAM_SETS_NOT_DISTINCT" in replay["codes"]
    assert replay["coverage"]["indistinguishable_param_sets"] == [[0, 1, 2]]


def test_malformed_excerpt_is_a_data_failure_not_a_crash(tmp_path):
    broken = synthetic_frame().drop(columns=["volume"])
    record, calls = _refused(tmp_path, frames=[{"frame": broken, "origin": "synthetic"},
                                               {"frame": synthetic_frame(seed=6), "origin": "synthetic"}])
    assert _check(record, "data")["state"] == "FAIL" and record["decision"] == "NOT_ADMITTED" and calls == []


def test_timezone_aware_copy_of_an_excerpt_is_still_an_overlap(tmp_path):
    naive = synthetic_frame()
    aware = naive.copy()
    aware["time"] = aware["time"].dt.tz_localize("UTC")
    record, calls = _refused(tmp_path, frames=[{"frame": naive, "origin": "synthetic"},
                                               {"frame": aware, "origin": "synthetic"}])
    assert record["refusal"] == "DATA_FRAMES_OVERLAP" and calls == []


def test_same_basename_in_two_directories_gives_two_distinct_records(tmp_path, monkeypatch):
    import types
    files = []
    for name, text in (("a", "X = 1\n"), ("b", "X = 2\n")):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "helper.py").write_text(text, encoding="utf-8")
        module = types.ModuleType(f"helper_{name}")
        module.__file__ = str(folder / "helper.py")
        monkeypatch.setitem(sys.modules, module.__name__, module)
        files.append(str(folder / "helper.py"))
    report = ra._environment_report(os.path.dirname(os.path.abspath(ra.__file__)))["local_modules"]
    external = {key: digest for key, digest in report.items() if key.startswith("external/") and key.endswith("/helper.py")}
    assert sorted(external.values()) == sorted(_sha(path) for path in files)
    assert str(tmp_path) not in json.dumps(report)


def test_forged_reduced_flag_is_detected(tmp_path):
    record = _run(tmp_path, "honest")
    forged = dict(record, protocol=dict(record["protocol"], reduced=False), decision="NO_VIOLATION_OBSERVED")
    forged["admission_id"] = ra._record_id(forged)
    ok, problems = ra.verify_record(forged)
    assert not ok and "protocol" in problems


def test_empty_set_left_by_prepare_is_not_non_comparable_data(tmp_path, monkeypatch):
    monkeypatch.setitem(support.SPECS, "empty_set", (True, "", support._HP + "\n        self._s = set()",
                                                     support._HD, support._STOP))
    prefix = _check(_run(tmp_path, "empty_set"), "prepare_prefix")
    assert prefix["state"] == "PASS"


@pytest.mark.skipif(os.name != "nt", reason="chemin taskkill propre à Windows")
def test_missing_taskkill_does_not_raise_from_the_tree_kill(monkeypatch):
    monkeypatch.setattr(ra, "_taskkill_path", lambda: None)
    ra._kill_tree(1)  # aucun processus n'est visé : le chemin est absent


def test_interruption_during_the_timeout_kill_still_reaps_the_child(tmp_path, monkeypatch):
    def timeout_first(process, timeout):
        if len(process.waits) == 1:
            raise subprocess.TimeoutExpired("x", timeout)
        return 0
    process, calls = _FakeProcess(timeout_first), []

    def kill(pid):
        calls.append(pid)
        if len(calls) == 1:
            raise KeyboardInterrupt
    _fake_popen(monkeypatch, process)
    monkeypatch.setattr(ra, "_kill_tree", kill)
    with pytest.raises(KeyboardInterrupt):
        ra._ChildRunner(str(tmp_path), sys.executable, 5)._attempt({"role": "full"})
    assert calls == [4242, 4242]


# ───────────────────────────── mutants survivants de la passe finale ─────────────────────────────

def test_swallowed_unapproved_import_is_flagged_even_when_the_role_succeeds(tmp_path, monkeypatch):
    """M30 : l'import refusé puis avalé n'est visible, dans l'interpréteur des rejeux, que par ce contrôle final."""
    frame_csv = tmp_path / "frame.csv"
    frame_csv.write_bytes(ra.frame_csv_bytes(synthetic_frame()))
    request = {"repo_root": os.path.dirname(os.path.abspath(ra.__file__)), "role": "replay",
               "frame_csv": str(frame_csv), "guards": False}
    monkeypatch.setattr(ra, "_strategy_loader", lambda _request: None)
    monkeypatch.setitem(ra._GUARD, "blocked", [])

    def role_that_swallows(_request, _load, _frame, _run_backtest):
        ra._GUARD["blocked"].append("walk_forward")
        return {"replays": 0, "violation": None}
    monkeypatch.setattr(ra, "_replay_role", role_that_swallows)
    response = ra.execute_request(request)
    assert response["status"] == "error" and response["error"]["origin"] == "import_not_approved"
    monkeypatch.setitem(ra._GUARD, "blocked", [])
    monkeypatch.setattr(ra, "_replay_role", lambda *_args: {"replays": 0, "violation": None})
    assert ra.execute_request(request)["status"] == "ok"


def test_admission_id_must_match_the_content(tmp_path):
    """M22 : un enregistrement dont le contenu change mais dont l'identité reste est incohérent."""
    record = _run(tmp_path, "honest")
    altered = dict(record, param_sets=[dict(p, thr=0.5) for p in record["param_sets"]])
    ok, problems = ra.verify_record(altered)
    assert not ok and problems == ["admission_id"]
    ok, problems = ra.verify_record(dict(record, admission_id="0" * 64))
    assert not ok and problems == ["admission_id"]


def test_child_wait_uses_the_configured_timeout(tmp_path, monkeypatch):
    """M23 : le délai de l'attente est celui du protocole, pas une valeur fixe."""
    process = _FakeProcess(lambda p, t: 0)
    process.returncode = 0
    _fake_popen(monkeypatch, process)
    ra._ChildRunner(str(tmp_path), sys.executable, 7)._attempt({"role": "full"})
    assert process.waits[0] == 7


def test_huge_integer_in_a_trace_does_not_crash_the_signature():
    assert ra._numbers_as_floats([[1, True, {"a": 2, "b": 10 ** 400}]]) == [[1.0, True, {"a": 2.0, "b": 10 ** 400}]]
    assert ra.canonical_json(ra._numbers_as_floats({"x": 10 ** 400}))  # sérialisable


# ───────────────────────────── gate final : quatre MEDIUM (M1 à M4) et LOW associés ─────────────────────────────

_IN_POSITION_SOURCE = '''"""Stratégie de sonde : signal d'entrée émis en position (ignoré par le moteur). Synthétique."""


class Strategy:
    def reset(self):
        self._c = None

    @staticmethod
    def required_warmup(params):
        return 22

    def prepare(self, df, params):
        self._c = df["close"].values
        self._ref = df["close"].shift(10).values
        return df

    def on_bar(self, i, df, context, params):
        if context["in_pos"]:
            if i % 5 == 0:
                return {{"action": "enter", "direction": "long", "stop_pct": {stop}, "target_pct": 0.5}}
            return None
        if i % 3 != 0:
            return None
        if self._c[i] > self._ref[i] * (1 + params["thr"] / 100.0):
            return {{"action": "enter", "direction": "long", "stop_pct": params["stop_pct"],
                    "target_pct": params["target_pct"], "max_bars": int(params["max_bars"]), "nb_contracts": 1,
                    "note": {note}}}
        return None
'''


def _custom_strategy(tmp_path, name, source):
    for sub in ("strategies", "operator"):
        (tmp_path / sub).mkdir(exist_ok=True)
    path = tmp_path / "strategies" / f"{name}.py"
    path.write_text(source, encoding="utf-8", newline="\n")
    return str(path), support.write_approval(tmp_path / "operator", str(path))


def _run_custom(tmp_path, name, source, in_process=True):
    path, approval = _custom_strategy(tmp_path, name, source)
    return ra.run_preflight(strategy_path=path, approval_path=approval, param_sets=PARAM_SETS,
                            frames=[{"frame": synthetic_frame(), "origin": "synthetic"}],
                            output_dir=str(tmp_path / "out"), protocol=REDUCED_PROTOCOL,
                            runner=ra.execute_request if in_process else None)


# M1 — entier non représentable en flottant dans un signal

@pytest.mark.parametrize("value, expected", [
    (10 ** 400, False), (2 ** 1024, False), (-(10 ** 400), False), (float("inf"), False), (float("nan"), False),
    (True, False), (False, False), ("1", False), (None, False), ([1], False), (0, False), (-1, False), (0.0, False),
    (10 ** 308, True), (1.7976931348623157e308, True), (5e-324, True), (1, True), (0.3, True),
])
def test_positive_number_boundaries(value, expected):
    assert ra._positive_number(value) is expected


def test_finite_conversion_of_an_unrepresentable_integer_is_none():
    assert ra._finite(10 ** 400) is None
    assert ra._finite(10 ** 308) == 1e308 and ra._finite("x") is None and ra._finite(float("inf")) is None


def test_unrepresentable_stop_in_a_signal_ignored_by_the_engine_is_a_signal_failure(tmp_path):
    record = _run_custom(tmp_path, "huge_stop", _IN_POSITION_SOURCE.format(stop="10 ** 400", note="None"))
    signal = _check(record, "signal_contract")
    assert (signal["state"], signal["codes"]) == ("FAIL", ["SIGNAL_INVALID"])
    assert signal["coordinates"]["reason"] == "stop_or_target"
    assert record["decision"] == "NOT_ADMITTED" and ra.verify_record(record) == (True, [])


def test_representable_values_are_not_refused(tmp_path):
    record = _run_custom(tmp_path, "large_stop", _IN_POSITION_SOURCE.format(stop="1e308", note="10 ** 400"))
    assert [c["state"] for c in record["checks"]] == ["PASS"] * 5  # entier géant dans un champ hors contrat : accepté


def test_unrepresentable_stop_through_child_interpreters_is_a_signal_failure(tmp_path):
    record = _run_custom(tmp_path, "huge_stop", _IN_POSITION_SOURCE.format(stop="10 ** 400", note="None"),
                         in_process=False)
    assert _check(record, "signal_contract")["codes"] == ["SIGNAL_INVALID"]
    assert record["decision"] == "NOT_ADMITTED"


# M2 — budget de rejeux épuisé sur les derniers extraits

def _three_excerpts():
    return [{"frame": synthetic_frame(seed=seed), "origin": "synthetic"} for seed in (5, 6, 7)]


def test_exhausted_budget_on_late_excerpts_is_inconclusive_not_pass(tmp_path):
    record = _run(tmp_path, "honest", frames=_three_excerpts(), protocol=dict(REDUCED_PROTOCOL, max_replays=240))
    replay = _check(record, "decision_replay")
    assert replay["state"] == "INCONCLUSIVE" and "BUDGET_EXCEEDED" in replay["codes"]
    assert record["decision"] == "NOT_ADMITTED"
    coverage = replay["coverage"]
    assert coverage["max_replays"] == 240 and coverage["replays"] <= 240
    groups = coverage["groups"]
    assert len(groups) == 9 and all(g["budget_exhausted"] for g in groups if g["tested_bars"] == 0)
    assert any(g["tested_bars"] == 0 for g in groups)
    for group in groups:  # répartition effective : chaque groupe non épuisé a rejoué toutes ses barres
        if not group["budget_exhausted"]:
            assert group["replays"] == len(ra.VARIANTS) * group["tested_bars"] + 1


def test_exactly_sufficient_budget_passes_and_one_less_is_inconclusive(tmp_path):
    ample = _run(tmp_path, "honest", frames=_three_excerpts())
    ample_replay = _check(ample, "decision_replay")
    assert ample_replay["state"] == "PASS"
    needed = ample_replay["coverage"]["replays"]
    assert needed == sum(len(ra.VARIANTS) * g["tested_bars"] + 1 for g in ample_replay["coverage"]["groups"])
    exact = _check(_run(tmp_path, "honest", frames=_three_excerpts(),
                        protocol=dict(REDUCED_PROTOCOL, max_replays=needed)), "decision_replay")
    assert exact["state"] == "PASS" and exact["coverage"]["groups"] == ample_replay["coverage"]["groups"]
    short = _check(_run(tmp_path, "honest", frames=_three_excerpts(),
                        protocol=dict(REDUCED_PROTOCOL, max_replays=needed - 1)), "decision_replay")
    assert short["state"] == "INCONCLUSIVE" and "BUDGET_EXCEEDED" in short["codes"]
    assert short["coverage"]["replays"] <= needed - 1
    assert [g["budget_exhausted"] for g in short["coverage"]["groups"]] == [False] * 8 + [True]


def test_budget_truncating_only_the_sparse_bars_is_flagged():
    decisions = list(range(40, 600, 30))
    protocol = dict(REDUCED_PROTOCOL, sparse_bars=4)
    full = ra.plan_tested_bars(decision_bars=decisions, first_bar=30, last_bar=600, fingerprint="ab" * 32,
                               protocol=protocol)
    assert len(full["sparse"]) == 4 and full["budget_exhausted"] is False
    exact = ra.plan_tested_bars(decision_bars=decisions, first_bar=30, last_bar=600, fingerprint="ab" * 32,
                                protocol=protocol, max_bars=len(full["bars"]))
    assert exact == full
    cut = ra.plan_tested_bars(decision_bars=decisions, first_bar=30, last_bar=600, fingerprint="ab" * 32,
                              protocol=protocol, max_bars=len(full["bars"]) - 1)
    assert cut["trace_windows"] == full["trace_windows"] and len(cut["sparse"]) == 3
    assert cut["budget_exhausted"] is True


# M3 — même extrait décalé dans le temps

def _shifted(frame, days=30):
    copy = frame.copy()
    copy["time"] = copy["time"] + pd.Timedelta(days=days)
    return copy


def test_time_shifted_copy_of_an_excerpt_is_refused_before_any_run(tmp_path, monkeypatch):
    frame = synthetic_frame()
    single = [{"frame": frame, "origin": "synthetic"}]
    # Toutes les décisions de l'extrait seul (plancher hors d'atteinte : le plan couvre toute la trace).
    totals = _check(_run(tmp_path, "honest", frames=single, protocol=dict(REDUCED_PROTOCOL, min_decisions=10_000)),
                    "decision_replay")["coverage"]["tested_decisions_by_param_set"]
    floor = dict(REDUCED_PROTOCOL, min_decisions=max(totals) + 1)
    assert 2 * min(totals) >= floor["min_decisions"]  # la copie doublerait les comptes au-delà du plancher
    alone = _run(tmp_path, "honest", frames=single, protocol=floor)
    assert _check(alone, "decision_replay")["state"] == "INCONCLUSIVE" and alone["decision"] == "NOT_ADMITTED"
    cases = {"full": [frame, _shifted(frame)], "partial": [frame, _shifted(frame.iloc[100:220])],
             "inside_one": [pd.concat([frame, _shifted(frame, 3)], ignore_index=True)]}
    for label, frames in cases.items():
        (tmp_path / label).mkdir()
        record, calls = _refused(tmp_path / label, frames=[{"frame": f, "origin": "synthetic"} for f in frames],
                                 protocol=floor)
        assert record["refusal"] == "DATA_FRAMES_OVERLAP", label
        assert record["decision"] == "NOT_ADMITTED" and calls == [], label
    # Faux PASS historique, reproduit en neutralisant le refus : c'est le refus qui l'empêche.
    monkeypatch.setattr(ra, "_frames_share_rows", lambda frames: False)
    (tmp_path / "neutralised").mkdir()
    doubled = _run(tmp_path / "neutralised", "honest", frames=[{"frame": f, "origin": "synthetic"}
                                                               for f in cases["full"]], protocol=floor)
    assert _check(doubled, "decision_replay")["state"] == "PASS"


def test_excerpts_overlapping_by_fewer_bars_than_a_run_are_still_refused(tmp_path):
    """Mutant N01 : deux exportations adjacentes qui partagent trois barres (horodatage et valeurs) ; la
    suite partagée est plus courte que `OVERLAP_RUN_BARS`, seule la comparaison des lignes la voit."""
    frame = synthetic_frame()
    record, calls = _refused(tmp_path, frames=[{"frame": frame.iloc[:200].reset_index(drop=True), "origin": "synthetic"},
                                               {"frame": frame.iloc[197:].reset_index(drop=True), "origin": "synthetic"}])
    assert record["refusal"] == "DATA_FRAMES_OVERLAP" and calls == []


def test_copy_differing_only_by_value_dtype_is_still_an_overlap(tmp_path):
    """Revue scientifique F1 : le harnais relit toutes les valeurs en float64 ; une copie dont le volume
    passe d'entier à flottant porte la même preuve."""
    frame = synthetic_frame()
    frame["volume"] = (frame["volume"] * 100).round().astype("int64")
    as_float = frame.copy()
    as_float["volume"] = as_float["volume"].astype("float64")
    cases = {"shifted": [frame, _shifted(as_float)], "same_time": [frame, as_float],
             "inside_one": [pd.concat([frame, _shifted(as_float, 3)], ignore_index=True)]}
    for label, frames in cases.items():
        (tmp_path / label).mkdir()
        record, calls = _refused(tmp_path / label, frames=[{"frame": f, "origin": "synthetic"} for f in frames])
        assert record["refusal"] == "DATA_FRAMES_OVERLAP" and calls == [], label


def _with_rows_of(target, source, start_source, start_target, count):
    out = target.copy()
    columns = list(ra.VALUE_COLUMNS)
    out.loc[start_target:start_target + count - 1, columns] = \
        source.loc[start_source:start_source + count - 1, columns].to_numpy()
    return out


def test_shared_value_run_threshold_separates_coincidence_from_copy(tmp_path):
    a, b = synthetic_frame(seed=5), synthetic_frame(seed=6)
    run = 5  # valeur du contrat (ADR 0028, « Barres testées ») : 4 barres partagées acceptées, 5 refusées
    assert ra.OVERLAP_RUN_BARS == run
    below = _with_rows_of(b, a, 50, 300, run - 1)
    record, _calls = _refused(tmp_path, frames=[{"frame": a, "origin": "synthetic"},
                                                {"frame": below, "origin": "synthetic"}])
    assert record["refusal"] is None  # quelques barres égales par coïncidence : extraits distincts acceptés
    (tmp_path / "at").mkdir()
    at = _with_rows_of(b, a, 50, 300, run)
    record, calls = _refused(tmp_path / "at", frames=[{"frame": a, "origin": "synthetic"},
                                                      {"frame": at, "origin": "synthetic"}])
    assert record["refusal"] == "DATA_FRAMES_OVERLAP" and calls == []


def test_constant_runs_and_distinct_excerpts_with_equal_timestamps_are_not_overlaps(tmp_path):
    a, b = synthetic_frame(seed=5), synthetic_frame(seed=6)
    flat = {"open": 15000.0, "high": 15000.0, "low": 15000.0, "close": 15000.0, "volume": 0.0}
    for frame in (a, b):  # barres de remplissage identiques, à des positions différentes
        start = 100 if frame is a else 250
        for column, value in flat.items():
            frame.loc[start:start + 2 * ra.OVERLAP_RUN_BARS, column] = value
    assert (a["time"] == b["time"]).all()
    record, _calls = _refused(tmp_path, frames=[{"frame": a, "origin": "synthetic"},
                                                {"frame": b, "origin": "synthetic"}])
    assert record["refusal"] is None


# M4 — réponses mal formées de l'interpréteur enfant

def _forging(full=None, replay=None):
    def runner(request):
        response = ra.execute_request(request)
        change = full if request["role"] == "full" else replay
        if change is not None and response.get("status") == "ok":
            change(response)
        return response
    return runner


def _set_signal(value):
    def change(response):
        response["trace"][0][2] = {"note": value}
    return change


def _set(key, value):
    def change(response):
        response[key] = value
    return change


def _set_prefix(**fields):
    def change(response):
        response["prefix"] = dict(response["prefix"], **fields)
    return change


_ENV = {"third_party": {}, "local_modules": {}, "python": "3"}


@pytest.mark.parametrize("change", [
    _set_signal(float("nan")), _set_signal(float("inf")), _set_signal(float("-inf")), _set_signal(10 ** 5000),
    _set_signal("\ud800"), _set_signal({1: 2, "a": 3}), _set_signal(object()),
    _set("environment", ["x"]), _set("environment", dict(_ENV, local_modules=["a.py"])),
    _set("environment", {"local_modules": {}}), _set("environment", dict(_ENV, local_modules={"a.py": ["h"]})),
    _set("environment", dict(_ENV, third_party=[])), _set("prefix", {"error": "x"}), _set("prefix", {"error": {}}),
    _set("prefix", {"cuts": []}), _set_prefix(scalars=[["a"]]), _set_prefix(scalars=["\ud800"]),
    _set_prefix(cuts=[float("nan")]), _set_prefix(cuts=[True]), _set_prefix(mismatch={"cut": 1}),
    _set_prefix(mismatch=[]), _set_prefix(scalar_mismatch="x"), _set("trace", [[True, False, None]]),
    _set("trace", [[-1, False, None]]), _set("trace", [[30, False, None], [29, False, None]]),
    _set("trace", [[30, "no", None]]),
    # revue Python L1, L2 : écarts vides ou aux clés inattendues, coupes différentes de celles demandées
    _set_prefix(scalar_mismatch={}), _set_prefix(mismatch={}),
    _set_prefix(mismatch={"frame": "x", "cut": 1, "name": "a", "bar": None, "max_abs_diff": None}),
    _set_prefix(scalar_mismatch={"cut": 1, "name": "a", "param_set": 9}), _set_prefix(cuts=[10 ** 500]),
    _set_prefix(cuts=[]),
])
def test_malformed_full_response_is_inconclusive_never_an_exception(tmp_path, change):
    record, _calls = _refused(tmp_path, runner=_forging(full=change))
    determinism = _check(record, "determinism")
    assert (determinism["state"], determinism["codes"]) == ("INCONCLUSIVE", ["ISOLATION_UNAVAILABLE"])
    assert record["decision"] == "NOT_ADMITTED" and record["admission_id"]


@pytest.mark.parametrize("change", [
    _set("environment", ["x"]), _set("environment", dict(_ENV, local_modules=["a.py"])), _set("replays", True),
    _set("violation", {"kind": "future", "variant": "up", "cut": 1}), _set("violation", "x"),
    _set("audit", float("nan")),
    lambda r: r.update(violation={"kind": "future", "variant": "up", "cut": 30, "bar": 30}, replays=True),
    lambda r: r.update(violation={"kind": "future", "variant": "up", "cut": True, "bar": 30}, replays=3),
    lambda r: r.update(violation={"kind": "future", "variant": "up", "cut": 30, "bar": -1}, replays=3),
    # revue Python S1 : plus de rejeux que demandés
    lambda r: r.update(violation={"kind": "future", "variant": "up", "cut": 30, "bar": 30}, replays=10 ** 6),
])
def test_malformed_replay_response_is_inconclusive_never_an_exception(tmp_path, change):
    record, _calls = _refused(tmp_path, runner=_forging(replay=change))
    replay = _check(record, "decision_replay")
    assert replay["state"] == "INCONCLUSIVE" and "ISOLATION_UNAVAILABLE" in replay["codes"]
    assert record["decision"] == "NOT_ADMITTED"


def test_well_formed_responses_with_an_environment_are_still_accepted(tmp_path):
    def with_environment(response):
        response["environment"] = dict(_ENV, local_modules={"engine.py": "0" * 64})
    record, _calls = _refused(tmp_path, runner=_forging(full=with_environment, replay=with_environment))
    assert [c["state"] for c in record["checks"]] == ["PASS"] * 5
    assert record["subject"]["loaded_local_modules"] == {"engine.py": "0" * 64}


@pytest.mark.parametrize("text", ['{"status": "error", "x": NaN}', '{"status": "error", "x": Infinity}',
                                  '{"status": "error", "x": -Infinity}', '{"status": "error", "x": 1' + "0" * 5000 + "}"])
def test_non_standard_json_constants_in_a_response_file_are_unreadable(tmp_path, text):
    path = tmp_path / "response.json"
    path.write_text(text, encoding="utf-8")
    assert ra._read_response_file(str(path)) is None


def test_child_response_file_with_nan_is_unreadable_not_trusted(tmp_path, monkeypatch):
    process = _FakeProcess(lambda p, t: 0)
    process.returncode = 0

    def factory(args, **kwargs):
        response = os.path.join(os.path.dirname(args[-1]), "response.json")
        with open(response, "w", encoding="utf-8") as handle:
            handle.write('{"status":"ok","trace":[[0,false,{"x":NaN}]],"same_fresh":true,"same_module":true,'
                         '"prefix":null,"audit":[]}')
        return process
    monkeypatch.setattr(ra.subprocess, "Popen", factory)
    response = ra._ChildRunner(str(tmp_path), sys.executable, 5)._attempt({"role": "full"})
    assert response["status"] == "error" and response["error"]["origin"] == "unreadable"


@pytest.mark.parametrize("text", ['{"status":"error","error":"x"}', '{"status":"error"}',
                                  '{"status":"error","error":{}}', '{"status":"error","error":{"origin":3}}'])
def test_malformed_child_error_response_is_retried_as_unreadable(tmp_path, monkeypatch, text):
    """Revue Python L3 : une réponse d'erreur mal formée est illisible (nouvelle tentative), jamais une exception."""
    attempts = []

    def factory(args, **kwargs):
        attempts.append(args[-1])
        with open(os.path.join(os.path.dirname(args[-1]), "response.json"), "w", encoding="utf-8") as handle:
            handle.write(text)
        process = _FakeProcess(lambda p, t: 0)
        process.returncode = 0
        return process
    monkeypatch.setattr(ra.subprocess, "Popen", factory)
    response = ra._ChildRunner(str(tmp_path), sys.executable, 5)({"role": "full"})
    assert response["status"] == "error" and response["error"]["origin"] == "unreadable" and len(attempts) == 2


# LOW associés — mêmes frontières de validation

@pytest.mark.parametrize("column", [
    lambda f: pd.Series([10 ** 400] * len(f), dtype=object),
    lambda f: f["time"],
    lambda f: f["time"] - f["time"].iloc[0],
])
def test_unrepresentable_or_temporal_values_are_a_data_failure_not_a_crash(tmp_path, column):
    """Revue Python L4 : entiers hors de portée des flottants, dates ou durées dans une colonne de valeurs."""
    frame = synthetic_frame()
    frame["volume"] = column(frame)
    check = ra.check_market_frame(frame, "synthetic")
    assert (check["state"], check["codes"]) == ("FAIL", ["DATA_NON_FINITE"])
    record, calls = _refused(tmp_path, frames=[{"frame": frame, "origin": "synthetic"}])
    assert _check(record, "data")["state"] == "FAIL" and calls == []


@pytest.mark.parametrize("params", ['{"a": 1}', "[]", "5", '[{"a": NaN}]', '[{"a": 1}, {"a": 1}]'])
def test_manual_command_reports_invalid_parameter_sets_as_usage_errors(tmp_path, params):
    """Revue Python L5 : jeux de paramètres lisibles mais invalides."""
    path, approval = _setup(tmp_path, "honest")
    params_path = tmp_path / "params.json"
    params_path.write_text(params, encoding="utf-8")
    frame_csv = tmp_path / "frame.csv"
    frame_csv.write_bytes(ra.frame_csv_bytes(synthetic_frame()))
    with pytest.raises(SystemExit) as raised:
        ra.main(["--strategy", path, "--approval", approval, "--output-dir", str(tmp_path / "out"),
                 "--params-json", str(params_path), "--frame-csv", str(frame_csv), "--frame-origin", "synthetic"])
    assert raised.value.code == 2


def test_manual_command_usage_error_keeps_the_reason(tmp_path, capsys):
    path, approval = _setup(tmp_path, "honest")
    protocol = tmp_path / "protocol.json"
    protocol.write_text('{"bogus": 1}', encoding="utf-8")
    with pytest.raises(SystemExit):
        ra.main(["--strategy", path, "--approval", approval, "--output-dir", str(tmp_path / "out"),
                 "--params-json", str(protocol), "--frame-csv", "x.csv", "--frame-origin", "synthetic",
                 "--protocol-json", str(protocol)])
    assert "bogus" in capsys.readouterr().err

def test_complex_values_are_a_data_failure_not_a_crash(tmp_path):
    frame = synthetic_frame()
    frame["close"] = frame["close"].astype(complex)
    check = ra.check_market_frame(frame, "synthetic")
    assert (check["state"], check["codes"]) == ("FAIL", ["DATA_NON_FINITE"])
    record, calls = _refused(tmp_path, frames=[{"frame": frame, "origin": "synthetic"}])
    assert _check(record, "data")["state"] == "FAIL" and record["decision"] == "NOT_ADMITTED" and calls == []


def test_excerpt_without_a_frame_is_a_data_failure_not_a_crash(tmp_path):
    record, calls = _refused(tmp_path, frames=[{"origin": "synthetic"}])
    data = _check(record, "data")
    assert (data["state"], data["codes"]) == ("FAIL", ["DATA_UNDECLARED_COLUMN"])
    assert record["decision"] == "NOT_ADMITTED" and calls == []


@pytest.mark.parametrize("broken", ["protocol", "params", "csv"])
def test_manual_command_reports_unreadable_inputs_as_usage_errors(tmp_path, broken):
    path, approval = _setup(tmp_path, "honest")
    good_params = tmp_path / "params.json"
    good_params.write_text(json.dumps(PARAM_SETS), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    frame_csv = tmp_path / "frame.csv"
    frame_csv.write_bytes(ra.frame_csv_bytes(synthetic_frame()))
    argv = ["--strategy", path, "--approval", approval, "--output-dir", str(tmp_path / "out"),
            "--params-json", str(bad if broken == "params" else good_params),
            "--frame-csv", str(tmp_path / "missing.csv" if broken == "csv" else frame_csv),
            "--frame-origin", "synthetic"]
    if broken == "protocol":
        argv += ["--protocol-json", str(bad)]
    with pytest.raises(SystemExit) as raised:
        ra.main(argv)
    assert raised.value.code == 2
