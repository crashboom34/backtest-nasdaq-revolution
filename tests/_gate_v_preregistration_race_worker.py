"""
tests/_gate_v_preregistration_race_worker.py — standalone worker process for the genuine
2-process concurrency test of AF-V-07 Slice B (`test_two_process_race_exactly_one_winner`).

Not a pytest module itself (no `test_*` functions) -- invoked via `subprocess.Popen` from
tests/test_gate_v_preregistration.py, one process per contender. Busy-waits on a barrier file so
both processes attempt `save_gate_v_preregistration()` on the SAME target path as close to
simultaneously as practically achievable, then reports its own outcome to a private result file
(never stdout/stderr, to avoid any buffering/interleaving ambiguity between the two processes).

Usage: python _gate_v_preregistration_race_worker.py <data_json_path> <target_path> <barrier_path> <result_path>
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gate_v_preregistration import GateVPreRegistration, save_gate_v_preregistration


def main() -> None:
    data_path, target_path, barrier_path, result_path = sys.argv[1:5]
    with open(data_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    preregistration = GateVPreRegistration(**data)

    deadline = time.monotonic() + 10.0
    while not os.path.exists(barrier_path):
        if time.monotonic() > deadline:
            with open(result_path, "w", encoding="utf-8") as handle:
                handle.write("FAIL:BarrierTimeout")
            return
        time.sleep(0.001)

    try:
        save_gate_v_preregistration(target_path, preregistration)
    except FileExistsError:
        with open(result_path, "w", encoding="utf-8") as handle:
            handle.write("FAIL:FileExistsError")
        return
    except Exception as exc:  # pragma: no cover - defensive, reported for diagnosis only
        with open(result_path, "w", encoding="utf-8") as handle:
            handle.write(f"FAIL:{type(exc).__name__}:{exc}")
        return

    with open(result_path, "w", encoding="utf-8") as handle:
        handle.write("OK")


if __name__ == "__main__":
    main()
