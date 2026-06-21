from job_comparison import JobComparisonRecord
from champion_validation import (
    STATUS_BLOCKING,
    STATUS_UNKNOWN,
    STATUS_VALID,
    STATUS_WATCH,
    VERDICT_INCOMPLETE,
    VERDICT_INSUFFICIENT,
    VERDICT_PROMISING,
    VERDICT_SERIOUS,
    evaluate_champion,
)


def _record(**overrides) -> JobComparisonRecord:
    values = {
        "job_id": "job_validation",
        "job_dir": "job_validation",
        "date": "2026-06-21T12:00:00",
        "asset": "NASDAQ",
        "timeframe": "M3",
        "preset": "Test moyen",
        "status": "completed",
        "score": 48.0,
        "trades": 60,
        "win_rate": 55.0,
        "drawdown_pct": 8.0,
        "duration_seconds": 120.0,
        "combinations": 150,
        "data_file": "nasdaq_3m.csv",
        "strategy_name": "Strategy",
        "config": {"max_rows": None},
    }
    values.update(overrides)
    return JobComparisonRecord(**values)


def _criterion(validation, code: str):
    return next(item for item in validation.criteria if item.code == code)


def test_complete_champion_is_serious_candidate():
    validation = evaluate_champion(_record())

    assert validation.verdict == VERDICT_SERIOUS
    assert all(item.status == STATUS_VALID for item in validation.criteria)
    assert "observation" in validation.recommendation.lower()


def test_zero_trade_is_blocking_and_insufficient():
    validation = evaluate_champion(_record(trades=0))

    assert _criterion(validation, "trades").status == STATUS_BLOCKING
    assert validation.verdict == VERDICT_INSUFFICIENT
    assert "rejeter" in validation.recommendation.lower()


def test_low_trade_count_is_promising_but_needs_retest():
    validation = evaluate_champion(_record(trades=12))

    assert _criterion(validation, "trades").status == STATUS_WATCH
    assert validation.verdict == VERDICT_PROMISING
    assert "historique" in validation.recommendation.lower()


def test_quick_preset_cannot_be_serious():
    validation = evaluate_champion(_record(
        preset="Test rapide local",
        combinations=12,
        config={"max_rows": 20_000},
    ))

    assert _criterion(validation, "preset").status == STATUS_WATCH
    assert _criterion(validation, "combinations").status == STATUS_WATCH
    assert validation.verdict == VERDICT_PROMISING
    assert "historique" in validation.recommendation.lower()


def test_high_drawdown_is_blocking_at_thirty_percent():
    validation = evaluate_champion(_record(drawdown_pct=32.0))

    assert _criterion(validation, "drawdown").status == STATUS_BLOCKING
    assert validation.verdict == VERDICT_INSUFFICIENT
    assert "drawdown" in validation.recommendation.lower()


def test_legacy_job_with_missing_metrics_is_incomplete():
    validation = evaluate_champion(_record(
        score=None,
        trades=None,
        win_rate=None,
        drawdown_pct=None,
        combinations=None,
        preset="Ancien job",
        config={},
        missing_metrics=(
            "score",
            "trades",
            "win_rate",
            "drawdown",
            "combinaisons",
        ),
    ))

    assert _criterion(validation, "metrics").status == STATUS_BLOCKING
    assert _criterion(validation, "win_rate").status == STATUS_UNKNOWN
    assert _criterion(validation, "data_period").status == STATUS_UNKNOWN
    assert validation.verdict == VERDICT_INCOMPLETE
    assert "observation" in validation.recommendation.lower()


def test_drawdown_between_twenty_and_thirty_is_watch():
    validation = evaluate_champion(_record(drawdown_pct=24.0))

    assert _criterion(validation, "drawdown").status == STATUS_WATCH
    assert validation.verdict == VERDICT_PROMISING
