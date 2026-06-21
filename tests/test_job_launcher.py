import json
from pathlib import Path

import job_launcher
import optimizer as optimizer_module
from optimizer import (
    OptimizationConfig,
    Optimizer,
    ParamRange,
    TrainTestConfig,
    effective_combinations_total,
)
from scoring import FilterConfig, ScoreWeights


def test_prepare_job_config_creates_portable_job(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKTEST_BASE_DIR", str(tmp_path))

    config = {
        "run_id": "manual_test",
        "strategy_name": "Test Strategy",
        "mode": "grid",
        "param_ranges": [],
        "n_workers": 2,
    }

    job_id, job_dir, config_path, normalized = job_launcher.prepare_job_config(config)

    assert job_id == "job_manual_test"
    assert normalized["run_id"] == "job_manual_test"
    assert Path(job_dir).parent == tmp_path / "results"
    assert Path(config_path).name == "config_used.json"

    saved = json.loads(Path(config_path).read_text(encoding="utf-8"))
    assert saved["run_id"] == "job_manual_test"
    assert saved["strategy_name"] == "Test Strategy"


def test_build_optimizer_command_includes_job_dir(tmp_path):
    command = job_launcher.build_optimizer_command(
        "job_abc",
        str(tmp_path / "config_used.json"),
        str(tmp_path / "job_abc"),
        python_exe="python-test",
    )

    assert command[0] == "python-test"
    assert command[1].endswith("optimizer_process.py")
    assert command[2] == "job_abc"
    assert command[3].endswith("config_used.json")
    assert command[4].endswith("job_abc")


def test_launch_optimizer_job_blocks_when_active_job_exists(monkeypatch):
    monkeypatch.setattr(job_launcher, "list_active_jobs", lambda: [{"job_id": "job_active"}])

    try:
        job_launcher.launch_optimizer_job({"strategy_name": "T", "param_ranges": []})
    except job_launcher.ActiveJobExistsError as exc:
        assert exc.active_jobs[0]["job_id"] == "job_active"
    else:
        raise AssertionError("Expected ActiveJobExistsError")


def test_launch_optimizer_job_second_call_sees_recent_created_job(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKTEST_BASE_DIR", str(tmp_path))

    class FakeProcess:
        pass

    monkeypatch.setattr(job_launcher.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    config = {
        "strategy_name": "Test Strategy",
        "mode": "grid",
        "param_ranges": [],
        "n_workers": 1,
    }

    first = job_launcher.launch_optimizer_job(config)
    assert first.job_id.startswith("job_")

    try:
        job_launcher.launch_optimizer_job(config)
    except job_launcher.ActiveJobExistsError as exc:
        assert exc.active_jobs[0]["job_id"] == first.job_id
    else:
        raise AssertionError("Expected second launch to be blocked")


def test_clone_config_for_new_job_removes_old_identity():
    cloned = job_launcher.clone_config_for_new_job(
        {
            "run_id": "job_old",
            "job_id": "job_old",
            "job_dir": "results/job_old",
            "strategy_name": "Test Strategy",
            "param_ranges": [],
            "max_combinations": 12,
        }
    )

    assert "run_id" not in cloned
    assert "job_id" not in cloned
    assert "job_dir" not in cloned
    assert cloned["source_job_id"] == "job_old"
    assert cloned["relaunched_from_job_id"] == "job_old"
    assert cloned["max_combinations"] == 12


def _optimizer_config(max_combinations=None) -> OptimizationConfig:
    return OptimizationConfig(
        run_id="test_quick_limit",
        strategy_module="strategies/perfect_revolution_v1.py",
        strategy_name="Test Strategy",
        data_file="nasdaq_3m.csv",
        base_params={},
        param_ranges=[
            ParamRange(
                name="x",
                param_type="number",
                label="X",
                min_val=1,
                max_val=20,
                step=1,
                enabled=True,
            )
        ],
        mode="grid",
        score_weights=ScoreWeights(),
        filters=FilterConfig(),
        train_test=TrainTestConfig(),
        global_params={},
        n_workers=1,
        max_combinations=max_combinations,
    )


def test_effective_combinations_total_applies_quick_limit():
    assert effective_combinations_total(496, 12) == 12


def test_effective_combinations_total_keeps_full_mode_unlimited():
    assert effective_combinations_total(496, None) == 496


def test_optimizer_limits_actual_scheduled_combinations(monkeypatch):
    def fake_run_single(params, _config, _df, _start_date=None, _end_date=None):
        return {
            "score": 0.0,
            "params": params,
            "stats": {},
            "filtered": True,
            "filter_reason": "test",
            "warnings": [],
        }

    monkeypatch.setattr(optimizer_module, "_run_single", fake_run_single)

    opt = Optimizer(_optimizer_config(max_combinations=12), df=object())
    results = opt.run_mode3()

    assert len(results) == 12
    assert [r["params"]["x"] for r in results] == list(range(1, 13))


def test_optimizer_keeps_full_mode_unlimited(monkeypatch):
    def fake_run_single(params, _config, _df, _start_date=None, _end_date=None):
        return {
            "score": 0.0,
            "params": params,
            "stats": {},
            "filtered": True,
            "filter_reason": "test",
            "warnings": [],
        }

    monkeypatch.setattr(optimizer_module, "_run_single", fake_run_single)

    opt = Optimizer(_optimizer_config(max_combinations=None), df=object())
    results = opt.run_mode3()

    assert len(results) == 20
