"""
Shared launcher for optimizer jobs.

Both Streamlit and the CLI should create jobs the same way:
  1. normalize/create a job_id
  2. create results/job_xxx/
  3. write config_used.json
  4. launch optimizer_process.py with job_dir
"""

import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from optimization_store import get_job_dir, list_active_jobs, make_job_id, save_config


SCRIPT_DIR = Path(__file__).resolve().parent


@dataclass
class LaunchedJob:
    job_id: str
    job_dir: str
    config_path: str
    command: list
    process: subprocess.Popen
    config: dict


class ActiveJobExistsError(RuntimeError):
    """Raised when a new optimization job would conflict with an active job."""

    def __init__(self, active_jobs: list):
        self.active_jobs = active_jobs
        count = len(active_jobs)
        super().__init__(
            "Un job d'optimisation est deja actif."
            if count == 1
            else f"{count} jobs d'optimisation sont deja actifs."
        )


def assert_no_active_jobs(active_jobs: Optional[list] = None) -> None:
    """Fail early if a job is already active on disk."""
    jobs = list_active_jobs() if active_jobs is None else active_jobs
    if jobs:
        raise ActiveJobExistsError(jobs)


def clone_config_for_new_job(config_dict: dict, source_job_id: Optional[str] = None) -> dict:
    """Return a config copy safe to launch as a brand-new job."""
    cfg = deepcopy(config_dict or {})
    old_run_id = source_job_id or cfg.get("run_id") or cfg.get("job_id")

    for key in (
        "run_id",
        "job_id",
        "job_dir",
        "status",
        "progress_pct",
        "started_at",
        "updated_at",
        "duration_seconds",
        "elapsed_seconds",
        "error_message",
    ):
        cfg.pop(key, None)

    if old_run_id:
        cfg["source_job_id"] = str(old_run_id)
        cfg["relaunched_from_job_id"] = str(old_run_id)

    return cfg


def normalize_job_id(config_dict: dict, requested_run_id: Optional[str] = None) -> str:
    """Return a job_xxx id, preserving explicit ids when possible."""
    job_id = requested_run_id or config_dict.get("run_id") or make_job_id()
    job_id = str(job_id)
    if not job_id.startswith("job_"):
        job_id = f"job_{job_id}"
    return job_id


def prepare_job_config(config_dict: dict, run_id: Optional[str] = None) -> tuple:
    """
    Create the job directory and write config_used.json.

    Returns (job_id, job_dir, config_path, normalized_config).
    """
    cfg = dict(config_dict)
    job_id = normalize_job_id(cfg, run_id)
    cfg["run_id"] = job_id

    job_dir = get_job_dir(job_id)
    save_config(job_id, cfg, job_dir=job_dir)
    config_path = str(Path(job_dir) / "config_used.json")

    return job_id, job_dir, config_path, cfg


def build_optimizer_command(
    job_id: str,
    config_path: str,
    job_dir: str,
    python_exe: Optional[str] = None,
) -> list:
    """Build the optimizer_process.py command for a job directory run."""
    optimizer_script = SCRIPT_DIR / "optimizer_process.py"
    return [
        python_exe or sys.executable,
        str(optimizer_script),
        job_id,
        config_path,
        job_dir,
    ]


def launch_optimizer_job(
    config_dict: dict,
    run_id: Optional[str] = None,
    python_exe: Optional[str] = None,
    cwd: Optional[str] = None,
    prevent_concurrent: bool = True,
    **popen_kwargs,
) -> LaunchedJob:
    """Prepare and launch optimizer_process.py in job mode."""
    if prevent_concurrent:
        assert_no_active_jobs()

    job_id, job_dir, config_path, cfg = prepare_job_config(config_dict, run_id)
    cmd = build_optimizer_command(job_id, config_path, job_dir, python_exe)
    proc = subprocess.Popen(cmd, cwd=cwd or str(SCRIPT_DIR), **popen_kwargs)

    return LaunchedJob(
        job_id=job_id,
        job_dir=job_dir,
        config_path=config_path,
        command=cmd,
        process=proc,
        config=cfg,
    )
