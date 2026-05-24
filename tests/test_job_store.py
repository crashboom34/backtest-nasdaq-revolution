from pathlib import Path

import job_store


def test_write_best_strategies_creates_empty_csv(tmp_path):
    job_store.write_best_strategies(str(tmp_path), [])

    csv_path = tmp_path / "best_strategies.csv"
    assert csv_path.exists()
    header = csv_path.read_text(encoding="utf-8").splitlines()[0]
    assert "rank" in header
    assert "score" in header
