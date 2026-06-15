from datetime import datetime, timezone

import dashboard
import path_resolver


def _disk(free_gb=20):
    return {
        "total": 100 * 1024**3,
        "used": (100 - free_gb) * 1024**3,
        "free": free_gb * 1024**3,
    }


def test_empty_dashboard_summary_has_no_jobs_and_no_crash():
    summary = dashboard.build_dashboard_summary(
        jobs=[],
        data_sources=[],
        disk_usage=_disk(),
    )

    assert summary.total_jobs == 0
    assert summary.completed_jobs == 0
    assert summary.error_jobs == 0
    assert summary.latest_job_id == ""
    assert any(alert.title == "Aucune donnee CSV utilisable" for alert in summary.alerts)


def test_dashboard_summary_counts_completed_and_error_jobs():
    jobs = [
        {
            "job_id": "job_error",
            "status": "error",
            "date": "2026-06-02T12:00:00+00:00",
            "best_score": 0,
        },
        {
            "job_id": "job_done",
            "status": "completed",
            "date": "2026-06-03T12:00:00+00:00",
            "best_score": 42.5,
        },
    ]
    sources = [
        dashboard.DashboardDataSource("NASDAQ", "M3", "legacy", "nasdaq_3m.csv", True, "ok")
    ]

    summary = dashboard.build_dashboard_summary(
        jobs=jobs,
        data_sources=sources,
        disk_usage=_disk(),
    )

    assert summary.total_jobs == 2
    assert summary.completed_jobs == 1
    assert summary.error_jobs == 1
    assert summary.latest_job_id == "job_done"
    assert summary.latest_completed_job_id == "job_done"
    assert summary.best_recent_score == 42.5
    assert any(alert.title == "Jobs en erreur" for alert in summary.alerts)


def test_dashboard_flags_low_disk():
    summary = dashboard.build_dashboard_summary(
        jobs=[],
        data_sources=[
            dashboard.DashboardDataSource("NASDAQ", "M3", "legacy", "nasdaq_3m.csv", True, "ok")
        ],
        disk_usage=_disk(free_gb=1),
    )

    assert any(alert.level == "error" and alert.title == "Disque presque plein" for alert in summary.alerts)


def test_dashboard_detects_stale_active_job():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    jobs = [
        {
            "job_id": "job_running",
            "status": "running",
            "date": "2026-06-15T11:00:00+00:00",
            "_updated_at": "2026-06-15T11:00:00+00:00",
        }
    ]

    summary = dashboard.build_dashboard_summary(
        jobs=jobs,
        data_sources=[
            dashboard.DashboardDataSource("NASDAQ", "M3", "legacy", "nasdaq_3m.csv", True, "ok")
        ],
        disk_usage=_disk(),
        now=now,
    )

    assert summary.active_jobs == 1
    assert summary.stale_active_jobs == 1
    assert any(alert.title == "Job actif potentiellement bloque" for alert in summary.alerts)


def test_list_data_sources_detects_data_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)
    csv_path = tmp_path / "data" / "SP500" / "M15" / "sp500_m15.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("time,open,high,low,close\n", encoding="utf-8")

    sources = dashboard.list_data_sources()

    assert len(sources) == 1
    assert sources[0].asset == "SP500"
    assert sources[0].timeframe == "M15"
    assert sources[0].source == "data"
    assert sources[0].exists is True


def test_list_data_sources_handles_empty_data_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(path_resolver, "BASE_DIR", tmp_path)

    sources = dashboard.list_data_sources()

    assert len(sources) == 1
    assert sources[0].asset == "NASDAQ"
    assert sources[0].timeframe == "M3"
    assert sources[0].exists is False
