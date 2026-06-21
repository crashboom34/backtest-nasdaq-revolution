"""Persistance globale des seuils de validation Champion."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from champion_validation import ChampionValidationSettings


DEFAULT_SETTINGS_PATH = (
    Path(__file__).resolve().parent / "settings" / "champion_validation.json"
)


def load_validation_settings(
    path: str | Path = DEFAULT_SETTINGS_PATH,
) -> ChampionValidationSettings:
    target = Path(path)
    if not target.is_file():
        return ChampionValidationSettings()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return _settings_from_dict(data)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return ChampionValidationSettings()


def save_validation_settings(
    settings: ChampionValidationSettings,
    path: str | Path = DEFAULT_SETTINGS_PATH,
) -> ChampionValidationSettings:
    validated = _settings_from_dict(asdict(settings))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".json.tmp")
    try:
        temp.write_text(
            json.dumps(asdict(validated), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, target)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass
    return validated


def reset_validation_settings(
    path: str | Path = DEFAULT_SETTINGS_PATH,
) -> ChampionValidationSettings:
    return save_validation_settings(ChampionValidationSettings(), path)


def _settings_from_dict(data) -> ChampionValidationSettings:
    if not isinstance(data, dict):
        raise ValueError("Configuration invalide")
    settings = ChampionValidationSettings(
        min_trades=_positive_int(data.get("min_trades", 30)),
        min_score=_number(data.get("min_score", 0.0)),
        watch_drawdown_pct=_non_negative(data.get("watch_drawdown_pct", 20.0)),
        blocking_drawdown_pct=_non_negative(data.get("blocking_drawdown_pct", 30.0)),
        min_win_rate_pct=_percentage(data.get("min_win_rate_pct", 40.0)),
        min_combinations=_positive_int(data.get("min_combinations", 100)),
        min_rows=_positive_int(data.get("min_rows", 100_000)),
        min_period_days=_positive_int(data.get("min_period_days", 180)),
        quick_preset_non_validating=_boolean(
            data.get("quick_preset_non_validating", True)
        ),
    )
    if settings.blocking_drawdown_pct <= settings.watch_drawdown_pct:
        raise ValueError("Le seuil bloquant doit dépasser le seuil de surveillance")
    return settings


def _number(value) -> float:
    if isinstance(value, bool):
        raise TypeError("Nombre attendu")
    return float(value)


def _non_negative(value) -> float:
    number = _number(value)
    if number < 0:
        raise ValueError("Valeur positive attendue")
    return number


def _positive_int(value) -> int:
    number = _number(value)
    if number <= 0 or not number.is_integer():
        raise ValueError("Entier positif attendu")
    return int(number)


def _percentage(value) -> float:
    number = _non_negative(value)
    if number > 100:
        raise ValueError("Pourcentage hors limites")
    return number


def _boolean(value) -> bool:
    if not isinstance(value, bool):
        raise TypeError("Booléen attendu")
    return value
