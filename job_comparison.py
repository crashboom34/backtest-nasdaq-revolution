"""Lecture et normalisation des jobs pour la comparaison Streamlit."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from job_annotations import JobAnnotation, load_annotation


MIN_SELECTED_JOBS = 2
MAX_SELECTED_JOBS = 5
COMPLETED_STATUSES = {"completed"}


@dataclass(frozen=True)
class JobComparisonRecord:
    job_id: str
    job_dir: str
    date: str
    asset: str
    timeframe: str
    preset: str
    status: str
    score: Optional[float]
    trades: Optional[int]
    win_rate: Optional[float]
    drawdown_pct: Optional[float]
    duration_seconds: Optional[float]
    combinations: Optional[int]
    data_file: str
    strategy_name: str
    config: dict[str, Any] = field(default_factory=dict, compare=False)
    missing_metrics: tuple[str, ...] = ()
    annotation: JobAnnotation = field(default_factory=JobAnnotation, compare=False)

    @property
    def comparison_key(self) -> tuple[str, str, str, str]:
        return (
            self.strategy_name.strip().lower(),
            self.asset.strip().lower(),
            self.timeframe.strip().lower(),
            self.data_file.strip().replace("\\", "/").lower(),
        )

    @property
    def has_no_trades(self) -> bool:
        return self.trades == 0


def validate_selection(job_ids: Iterable[str]) -> tuple[bool, str]:
    selected = list(dict.fromkeys(str(job_id) for job_id in job_ids if job_id))
    if len(selected) < MIN_SELECTED_JOBS:
        return False, "Sélectionne au moins 2 jobs."
    if len(selected) > MAX_SELECTED_JOBS:
        return False, "Sélectionne au maximum 5 jobs."
    return True, ""


def completed_jobs(jobs: Iterable[dict]) -> list[dict]:
    return [
        job for job in jobs
        if str(job.get("status", "")).lower() in COMPLETED_STATUSES
        and job.get("job_id")
        and job.get("job_dir")
    ]


def load_comparison_records(jobs: Iterable[dict]) -> list[JobComparisonRecord]:
    records: list[JobComparisonRecord] = []
    for job in completed_jobs(jobs):
        record = load_job_record(job)
        if record is not None:
            records.append(record)
    return sorted(records, key=lambda item: item.date, reverse=True)


def load_job_record(job: dict) -> Optional[JobComparisonRecord]:
    job_id = str(job.get("job_id", "") or "")
    job_dir = Path(str(job.get("job_dir", "") or ""))
    if not job_id or not job_dir.is_dir():
        return None

    config = _read_json(job_dir / "config_used.json")
    metrics = _read_json(job_dir / "metrics.json")
    meta = _read_json(job_dir / "meta.json")
    meta_best = _best_meta(meta)
    meta_stats = _best_meta_stats(meta)

    score = _number_from(
        (metrics, "best_score"),
        (job, "best_score"),
        (meta_best, "score"),
    )
    trades = _int_from(
        (metrics, "best_total_trades"),
        (meta_stats, "total_trades"),
        (meta_stats, "n_trades"),
    )
    win_rate = _number_from(
        (metrics, "best_win_rate"),
        (meta_stats, "win_rate"),
    )
    drawdown = _number_from(
        (metrics, "best_max_dd_pct"),
        (meta_stats, "max_dd_pct"),
    )
    duration = _number_from(
        (metrics, "duration_seconds"),
        (meta, "duration_seconds"),
        (job, "duration_seconds"),
    )
    combinations = _int_from(
        (metrics, "total_combinations"),
        (meta, "total_combinations"),
        (job, "total_combinations"),
        (config, "total_combinations"),
    )

    if any(value is None for value in (score, trades, win_rate, drawdown)):
        best_csv = _best_result_row(job_dir / "results.csv")
        score = score if score is not None else _number_from((best_csv, "score"))
        trades = trades if trades is not None else _int_from((best_csv, "stat_n_trades"))
        win_rate = win_rate if win_rate is not None else _number_from((best_csv, "stat_win_rate"))
        drawdown = (
            drawdown
            if drawdown is not None
            else _number_from((best_csv, "stat_max_dd_pct"))
        )

    asset, timeframe = _asset_timeframe(config)
    preset = (
        config.get("preset_name")
        or metrics.get("preset_name")
        or meta.get("preset_name")
        or ("Test rapide local" if config.get("quick_validation_mode") else "Ancien job")
    )
    data_file = str(config.get("data_file") or config.get("data_path") or "")
    strategy_name = str(
        config.get("strategy_name")
        or metrics.get("strategy_name")
        or meta.get("strategy_name")
        or job.get("strategy_name")
        or "Stratégie inconnue"
    )
    status = str(
        metrics.get("status")
        or meta.get("status")
        or job.get("status")
        or "completed"
    )
    date = str(
        meta.get("date")
        or metrics.get("generated_at")
        or job.get("date")
        or ""
    )

    missing = tuple(
        label for label, value in (
            ("score", score),
            ("trades", trades),
            ("win_rate", win_rate),
            ("drawdown", drawdown),
            ("duration", duration),
            ("combinaisons", combinations),
        )
        if value is None
    )

    return JobComparisonRecord(
        job_id=job_id,
        job_dir=str(job_dir),
        date=date,
        asset=asset,
        timeframe=timeframe,
        preset=str(preset),
        status=status,
        score=score,
        trades=trades,
        win_rate=win_rate,
        drawdown_pct=drawdown,
        duration_seconds=duration,
        combinations=combinations,
        data_file=data_file or "Fichier inconnu",
        strategy_name=strategy_name,
        config=config,
        missing_metrics=missing,
        annotation=load_annotation(job_dir),
    )


def best_job(records: Iterable[JobComparisonRecord]) -> Optional[JobComparisonRecord]:
    scored = [record for record in records if record.score is not None]
    return max(scored, key=lambda item: item.score) if scored else None


def comparison_issues(records: Iterable[JobComparisonRecord]) -> list[str]:
    selected = list(records)
    issues: list[str] = []
    if not selected:
        return issues

    keys = {record.comparison_key for record in selected}
    if len(keys) > 1:
        issues.append(
            "Les jobs sélectionnés n'utilisent pas tous la même stratégie, le même actif, "
            "le même timeframe et le même fichier de données."
        )

    missing_jobs = [record.job_id for record in selected if record.missing_metrics]
    if missing_jobs:
        issues.append(
            "Certaines métriques sont absentes sur des anciens jobs : "
            + ", ".join(missing_jobs)
            + "."
        )

    if all(record.has_no_trades for record in selected if record.trades is not None):
        known_trade_counts = [record for record in selected if record.trades is not None]
        if known_trade_counts:
            issues.append("Aucun des jobs sélectionnés n'a produit de trade exploitable.")

    return issues


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _best_meta(meta: dict) -> dict:
    top = meta.get("top_100")
    if isinstance(top, list) and top and isinstance(top[0], dict):
        return top[0]
    return {}


def _best_meta_stats(meta: dict) -> dict:
    stats = _best_meta(meta).get("stats", {})
    return stats if isinstance(stats, dict) else {}


def _best_result_row(path: Path) -> dict:
    if not path.is_file():
        return {}
    best: dict = {}
    best_score: Optional[float] = None
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                score = _to_float(row.get("score"))
                if score is None:
                    continue
                if best_score is None or score > best_score:
                    best = row
                    best_score = score
    except (OSError, csv.Error, UnicodeError):
        return {}
    return best


def _asset_timeframe(config: dict) -> tuple[str, str]:
    asset = str(config.get("asset") or config.get("symbol") or "")
    timeframe = str(config.get("timeframe") or config.get("time_frame") or "")
    filename = Path(str(config.get("data_file") or config.get("data_path") or "")).name
    compact = filename.lower().replace("_", "").replace("-", "")

    if not asset:
        if "nasdaq" in compact or "us100" in compact:
            asset = "NASDAQ"
        elif filename:
            asset = Path(filename).stem
    if not timeframe and ("m3" in compact or "3m" in compact):
        timeframe = "M3"

    return asset or "Actif inconnu", timeframe or "Timeframe inconnu"


def _number_from(*sources: tuple[dict, str]) -> Optional[float]:
    for mapping, key in sources:
        if isinstance(mapping, dict) and key in mapping:
            value = _to_float(mapping.get(key))
            if value is not None:
                return value
    return None


def _int_from(*sources: tuple[dict, str]) -> Optional[int]:
    value = _number_from(*sources)
    return int(value) if value is not None else None


def _to_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
