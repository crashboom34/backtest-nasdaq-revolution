import json
from pathlib import Path

import job_launcher


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
