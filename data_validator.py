"""
data_validator.py - Validation legere des CSV de marche avant import.

Ce module ne lance aucun backtest. Il verifie seulement qu'un fichier CSV peut
servir de source de donnees pour le moteur existant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import pandas as pd


DATE_ALIASES = {
    "time",
    "datetime",
    "date",
    "timestamp",
    "date_time",
    "time_utc",
}

OHLC_ALIASES = {
    "open": {"open", "o", "opening"},
    "high": {"high", "h", "max"},
    "low": {"low", "l", "min"},
    "close": {"close", "c", "closing", "last"},
}

VOLUME_ALIASES = {"volume", "vol", "tick_volume", "real_volume"}


@dataclass
class CsvValidationResult:
    """Resultat lisible par Streamlit et par les tests unitaires."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    dataframe: pd.DataFrame | None = None
    column_map: dict[str, str] = field(default_factory=dict)

    @property
    def can_save(self) -> bool:
        return self.ok and not self.errors and self.dataframe is not None

    @property
    def quality_label(self) -> str:
        if self.errors:
            return "Erreurs bloquantes"
        if self.warnings:
            return "OK avec avertissements"
        return "OK"


def _column_key(name: object) -> str:
    key = str(name).strip().lower()
    key = key.replace("\ufeff", "")
    for old, new in ((" ", "_"), ("-", "_"), (".", "_"), ("/", "_")):
        key = key.replace(old, new)
    while "__" in key:
        key = key.replace("__", "_")
    return key.strip("_")


def _detect_columns(columns: list[object]) -> dict[str, str]:
    normalized = {_column_key(col): str(col) for col in columns}
    detected: dict[str, str] = {}

    for alias in DATE_ALIASES:
        if alias in normalized:
            detected["time"] = normalized[alias]
            break

    for target, aliases in OHLC_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                detected[target] = normalized[alias]
                break

    for alias in VOLUME_ALIASES:
        if alias in normalized:
            detected["volume"] = normalized[alias]
            break

    return detected


def _empty_result(error: str) -> CsvValidationResult:
    return CsvValidationResult(
        ok=False,
        errors=[error],
        summary={
            "row_count": 0,
            "start": None,
            "end": None,
            "duplicate_dates": 0,
            "missing_values": 0,
        },
    )


def validate_market_csv_bytes(raw: bytes) -> CsvValidationResult:
    """
    Valide un CSV de donnees marche.

    Colonnes attendues apres detection :
    - time/date/datetime/timestamp
    - open, high, low, close
    - volume optionnel

    Le dataframe retourne est normalise avec les noms attendus par engine.load_data().
    """
    if not raw:
        return _empty_result("Le fichier CSV est vide.")

    try:
        df = pd.read_csv(BytesIO(raw), sep=None, engine="python")
    except Exception as exc:
        return _empty_result(f"CSV illisible : {exc}")

    if df.empty:
        return _empty_result("Le fichier CSV ne contient aucune ligne.")

    errors: list[str] = []
    warnings: list[str] = []
    detected = _detect_columns(list(df.columns))

    if "time" not in detected:
        errors.append("Aucune colonne date/temps detectee. Utilise par exemple une colonne 'time'.")

    missing_ohlc = [name for name in ("open", "high", "low", "close") if name not in detected]
    if missing_ohlc:
        errors.append("Colonnes OHLC manquantes : " + ", ".join(missing_ohlc) + ".")

    summary: dict[str, Any] = {
        "row_count": int(len(df)),
        "start": None,
        "end": None,
        "duplicate_dates": 0,
        "missing_values": 0,
        "non_positive_prices": 0,
        "high_below_low": 0,
        "chronological": None,
        "has_volume": "volume" in detected,
    }

    if errors:
        return CsvValidationResult(
            ok=False,
            errors=errors,
            warnings=warnings,
            summary=summary,
            dataframe=None,
            column_map=detected,
        )

    normalized = pd.DataFrame()
    parsed_time = pd.to_datetime(df[detected["time"]], errors="coerce", utc=True)
    invalid_dates = int(parsed_time.isna().sum())
    if invalid_dates:
        errors.append(f"{invalid_dates} date(s) impossible(s) a convertir.")
    else:
        normalized["time"] = parsed_time.dt.tz_convert("UTC").dt.tz_localize(None)

    for col in ("open", "high", "low", "close"):
        normalized[col] = pd.to_numeric(df[detected[col]], errors="coerce")

    if "volume" in detected:
        normalized["volume"] = pd.to_numeric(df[detected["volume"]], errors="coerce")

    required_cols = ["time", "open", "high", "low", "close"]
    if "time" in normalized:
        missing_values = int(normalized[required_cols].isna().sum().sum())
    else:
        missing_values = int(normalized[["open", "high", "low", "close"]].isna().sum().sum())
    summary["missing_values"] = missing_values
    if missing_values:
        errors.append(f"{missing_values} valeur(s) manquante(s) dans les colonnes obligatoires.")

    price_cols = ["open", "high", "low", "close"]
    non_positive = int((normalized[price_cols] <= 0).sum().sum())
    summary["non_positive_prices"] = non_positive
    if non_positive:
        errors.append(f"{non_positive} prix negatif(s) ou nul(s) detecte(s).")

    high_below_low = int((normalized["high"] < normalized["low"]).sum())
    summary["high_below_low"] = high_below_low
    if high_below_low:
        errors.append(f"{high_below_low} ligne(s) avec high < low.")

    if "time" in normalized:
        duplicate_dates = int(normalized["time"].duplicated().sum())
        summary["duplicate_dates"] = duplicate_dates
        if duplicate_dates:
            warnings.append(f"{duplicate_dates} date(s) dupliquee(s) detectee(s).")

        chronological = bool(normalized["time"].is_monotonic_increasing)
        summary["chronological"] = chronological
        if not chronological:
            warnings.append("Les lignes ne sont pas dans l'ordre chronologique ; elles seront sauvegardees triees.")
            normalized = normalized.sort_values("time").reset_index(drop=True)

        summary["start"] = normalized["time"].min().strftime("%Y-%m-%d %H:%M:%S")
        summary["end"] = normalized["time"].max().strftime("%Y-%m-%d %H:%M:%S")
        normalized["time"] = normalized["time"].dt.strftime("%Y-%m-%d %H:%M:%S")

    if "volume" in normalized:
        volume_missing = int(normalized["volume"].isna().sum())
        if volume_missing:
            warnings.append(f"{volume_missing} valeur(s) de volume manquante(s). Le volume reste optionnel.")
            normalized["volume"] = normalized["volume"].fillna(0)

    return CsvValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        summary=summary,
        dataframe=normalized if not errors else None,
        column_map=detected,
    )

