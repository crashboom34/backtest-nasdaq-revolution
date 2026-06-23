import hashlib
import json
from pathlib import Path

from champion_roadmap import (
    MATURITY_INCOMPLETE,
    MATURITY_REJECTED,
    MATURITY_RETEST,
    MATURITY_SERIOUS,
    MATURITY_VALIDATE_HISTORY,
    build_roadmap,
    filter_roadmap_items,
    roadmap_summary,
)
from job_annotations import save_annotation
from job_decisions import CATEGORY_ACTION, append_decision_event


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job(
    tmp_path: Path,
    job_id: str,
    annotation: str,
    note: str = "",
    tags: list[str] | None = None,
    metrics: dict | None = None,
    config: dict | None = None,
):
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    job = {
        "job_id": job_id,
        "job_dir": str(job_dir),
        "status": "completed",
        "date": "2026-06-21T12:00:00",
    }
    _write_json(job_dir / "config_used.json", {
        "asset": "NASDAQ",
        "timeframe": "M3",
        "preset_name": "Test moyen",
        "data_file": "nasdaq_3m.csv",
        "strategy_name": "Strategy",
        "max_rows": None,
        **(config or {}),
    })
    _write_json(job_dir / "metrics.json", metrics or {
        "status": "completed",
        "best_score": 45.0,
        "best_total_trades": 60,
        "best_win_rate": 55.0,
        "best_max_dd_pct": 8.0,
        "duration_seconds": 120,
        "total_combinations": 150,
    })
    save_annotation(job_dir, status=annotation, note=note, tags=tags or [])
    return job, job_dir


def test_empty_roadmap():
    assert build_roadmap([]).items == ()


def test_champion_serious_candidate(tmp_path):
    job, _ = _job(tmp_path, "job_serious", "Champion", note="Solide")

    roadmap = build_roadmap([job])

    assert roadmap.items[0].maturity_status == MATURITY_SERIOUS
    assert roadmap.items[0].annotation == "Champion"
    assert "Garder" in roadmap.items[0].recommended_action


def test_favorite_to_retest(tmp_path):
    job, _ = _job(
        tmp_path,
        "job_retest",
        "Favori",
        metrics={"best_score": 25, "best_total_trades": 12, "best_win_rate": 50, "best_max_dd_pct": 8, "total_combinations": 150},
    )

    roadmap = build_roadmap([job])

    assert roadmap.items[0].maturity_status == MATURITY_RETEST
    assert "historique" in roadmap.items[0].recommended_action.lower()


def test_rejected_job(tmp_path):
    job, _ = _job(tmp_path, "job_rejected", "Rejeté")

    roadmap = build_roadmap([job])

    assert roadmap.items[0].maturity_status == MATURITY_REJECTED
    assert "rejet" in roadmap.items[0].recommended_action.lower()


def test_filter_annotation_status_tag_and_asset_timeframe(tmp_path):
    champion, _ = _job(tmp_path, "job_champion", "Champion", tags=["prometteur"])
    favorite, _ = _job(
        tmp_path,
        "job_favorite",
        "Favori",
        config={"asset": "DAX", "timeframe": "H1", "data_file": "dax_h1.csv"},
        metrics={"best_score": 25, "best_total_trades": 12, "best_win_rate": 50, "best_max_dd_pct": 8, "total_combinations": 150},
    )
    items = build_roadmap([champion, favorite]).items

    assert [item.job_id for item in filter_roadmap_items(items, annotation="Champion")] == ["job_champion"]
    assert [item.job_id for item in filter_roadmap_items(items, maturity_status=MATURITY_RETEST)] == ["job_favorite"]
    assert [item.job_id for item in filter_roadmap_items(items, tag="prometteur")] == ["job_champion"]
    assert [item.job_id for item in filter_roadmap_items(items, asset_timeframe="DAX/H1")] == ["job_favorite"]


def test_priority_action_prefers_history_validation(tmp_path):
    serious, _ = _job(tmp_path, "job_serious", "Champion")
    quick, _ = _job(
        tmp_path,
        "job_quick",
        "Favori",
        config={"preset_name": "Test rapide local", "max_rows": 20_000},
        metrics={"best_score": 30, "best_total_trades": 40, "best_win_rate": 50, "best_max_dd_pct": 8, "total_combinations": 12},
    )

    summary = roadmap_summary(build_roadmap([serious, quick]).items)

    assert summary.serious_count == 1
    assert summary.retest_count == 1
    assert summary.priority_job_id == "job_quick"
    assert "historique" in summary.priority_action.lower()


def test_legacy_job_with_missing_metrics_is_incomplete(tmp_path):
    job, job_dir = _job(tmp_path, "job_legacy", "À revoir", metrics={}, config={})
    (job_dir / "metrics.json").write_text("{}", encoding="utf-8")

    roadmap = build_roadmap([job])

    assert roadmap.items[0].maturity_status == MATURITY_INCOMPLETE


def test_last_decision_is_loaded(tmp_path):
    job, job_dir = _job(tmp_path, "job_decision", "Champion")
    append_decision_event(
        job_dir,
        "config_duplicated",
        CATEGORY_ACTION,
        "Configuration dupliquée.",
    )

    item = build_roadmap([job]).items[0]

    assert item.last_decision == "Configuration dupliquée."


def test_roadmap_does_not_modify_raw_results(tmp_path):
    job, job_dir = _job(tmp_path, "job_raw", "Champion")
    raw_names = ("config_used.json", "metrics.json")
    before = {name: _hash(job_dir / name) for name in raw_names}

    build_roadmap([job])

    assert {name: _hash(job_dir / name) for name in raw_names} == before
