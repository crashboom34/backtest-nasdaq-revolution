import json
import hashlib

from champion_validation import ChampionValidationSettings
from validation_settings import (
    load_validation_settings,
    reset_validation_settings,
    save_validation_settings,
)


def test_default_values_match_current_thresholds():
    settings = ChampionValidationSettings()

    assert settings.min_trades == 30
    assert settings.min_score == 0.0
    assert settings.watch_drawdown_pct == 20.0
    assert settings.blocking_drawdown_pct == 30.0
    assert settings.min_win_rate_pct == 40.0
    assert settings.min_combinations == 100
    assert settings.min_rows == 100_000
    assert settings.min_period_days == 180
    assert settings.quick_preset_non_validating is True


def test_load_custom_settings(tmp_path):
    path = tmp_path / "champion_validation.json"
    path.write_text(json.dumps({
        "min_trades": 50,
        "min_score": 12.5,
        "watch_drawdown_pct": 15,
        "blocking_drawdown_pct": 25,
        "min_win_rate_pct": 45,
        "min_combinations": 250,
        "min_rows": 200_000,
        "min_period_days": 365,
        "quick_preset_non_validating": False,
    }), encoding="utf-8")

    settings = load_validation_settings(path)

    assert settings.min_trades == 50
    assert settings.min_score == 12.5
    assert settings.min_combinations == 250
    assert settings.quick_preset_non_validating is False


def test_missing_settings_file_uses_defaults(tmp_path):
    assert load_validation_settings(tmp_path / "missing.json") == ChampionValidationSettings()


def test_invalid_settings_file_uses_defaults(tmp_path):
    path = tmp_path / "champion_validation.json"
    path.write_text("{invalid json", encoding="utf-8")

    assert load_validation_settings(path) == ChampionValidationSettings()


def test_reset_writes_default_settings(tmp_path):
    path = tmp_path / "champion_validation.json"
    save_validation_settings(
        ChampionValidationSettings(min_trades=99),
        path,
    )

    reset = reset_validation_settings(path)

    assert reset == ChampionValidationSettings()
    assert load_validation_settings(path) == ChampionValidationSettings()


def test_settings_write_does_not_modify_job_results(tmp_path):
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()
    raw_paths = []
    for filename in ("config_used.json", "metrics.json", "results.csv"):
        path = job_dir / filename
        path.write_text(f"raw {filename}", encoding="utf-8")
        raw_paths.append(path)
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in raw_paths
    }

    save_validation_settings(
        ChampionValidationSettings(min_trades=55),
        tmp_path / "settings" / "champion_validation.json",
    )

    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in raw_paths
    } == before
