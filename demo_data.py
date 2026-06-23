"""Jeu de donnees factices pour tester l'interface Streamlit sans vrais runs."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from job_artifacts import build_job_archive
from job_decisions import CATEGORY_ACTION
from retest_plan import RETEST_PLAN_EVENT_LAUNCHED


DEMO_SESSION_KEY = "demo_ui_mode_enabled"
DEMO_BASE_SESSION_KEY = "demo_ui_base_dir"
DEMO_PREVIOUS_BASE_SESSION_KEY = "demo_ui_previous_backtest_base_dir"


@dataclass(frozen=True)
class DemoDataset:
    base_dir: Path
    results_dir: Path
    job_ids: tuple[str, ...]


@dataclass(frozen=True)
class _DemoJobSpec:
    job_id: str
    status: str
    annotation: str
    note: str
    tags: tuple[str, ...]
    score: float | None
    trades: int | None
    win_rate: float | None
    drawdown_pct: float | None
    preset: str
    combinations: int
    duration_seconds: float
    max_rows: int | None
    max_combinations: int | None
    progress_pct: float = 100.0
    source_job_id: str = ""
    error_message: str = ""


SOURCE_RETEST_JOB_ID = "job_demo_champion_retest_source"
COMPLETED_RETEST_JOB_ID = "job_demo_retest_completed"
STOPPED_RETEST_JOB_ID = "job_demo_retest_stopped"


def default_demo_base_dir() -> Path:
    """Retourne un dossier temporaire stable, hors du depot Git."""
    return Path(tempfile.gettempdir()) / "backtest_nasdaq_demo_ui"


def ensure_demo_dataset(base_dir: str | Path | None = None) -> DemoDataset:
    """
    Cree ou rafraichit un petit results/ factice.

    Important : cette fonction ne change pas BACKTEST_BASE_DIR. L'appelant choisit
    explicitement quand l'interface doit lire ce dossier temporaire.
    """
    base = Path(base_dir) if base_dir is not None else default_demo_base_dir()
    base = base.resolve()
    results_dir = base / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    specs = _demo_specs()
    for index, spec in enumerate(specs):
        _write_demo_job(results_dir / spec.job_id, spec, index=index)

    _write_json(base / "demo_manifest.json", {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "description": "Dossier temporaire pour le mode demo UI. Donnees factices.",
        "jobs": [spec.job_id for spec in specs],
    })
    return DemoDataset(
        base_dir=base,
        results_dir=results_dir,
        job_ids=tuple(spec.job_id for spec in specs),
    )


def is_demo_base_dir(path: str | Path | None) -> bool:
    if not path:
        return False
    try:
        return Path(path).resolve() == default_demo_base_dir().resolve()
    except OSError:
        return False


def _demo_specs() -> tuple[_DemoJobSpec, ...]:
    return (
        _DemoJobSpec(
            job_id="job_demo_completed_good",
            status="completed",
            annotation="",
            note="Job factice termine avec un bon score pour tester les resultats.",
            tags=(),
            score=72.4,
            trades=86,
            win_rate=58.2,
            drawdown_pct=8.6,
            preset="Test moyen",
            combinations=100,
            duration_seconds=154.0,
            max_rows=100_000,
            max_combinations=100,
        ),
        _DemoJobSpec(
            job_id="job_demo_no_trades",
            status="completed",
            annotation="À revoir",
            note="Aucun trade : utile pour verifier les messages pedagogiques.",
            tags=("trop peu de trades",),
            score=0.0,
            trades=0,
            win_rate=0.0,
            drawdown_pct=0.0,
            preset="Test rapide local",
            combinations=12,
            duration_seconds=18.0,
            max_rows=20_000,
            max_combinations=12,
        ),
        _DemoJobSpec(
            job_id="job_demo_error",
            status="error",
            annotation="Rejeté",
            note="Erreur factice pour tester l'historique et les alertes.",
            tags=(),
            score=None,
            trades=None,
            win_rate=None,
            drawdown_pct=None,
            preset="Test moyen",
            combinations=42,
            duration_seconds=11.0,
            max_rows=100_000,
            max_combinations=100,
            progress_pct=42.0,
            error_message="Erreur factice : donnees volontairement simulees.",
        ),
        _DemoJobSpec(
            job_id="job_demo_stopped",
            status="stopped",
            annotation="À revoir",
            note="Job stoppe factice pour tester l'etat arrete.",
            tags=("à tester plus longtemps",),
            score=18.5,
            trades=14,
            win_rate=47.0,
            drawdown_pct=16.0,
            preset="Test moyen",
            combinations=48,
            duration_seconds=76.0,
            max_rows=100_000,
            max_combinations=100,
            progress_pct=48.0,
        ),
        _DemoJobSpec(
            job_id="job_demo_champion",
            status="completed",
            annotation="Champion",
            note="Champion factice robuste : bon score, assez de trades, drawdown contenu.",
            tags=("prometteur",),
            score=91.7,
            trades=142,
            win_rate=61.4,
            drawdown_pct=7.4,
            preset="Optimisation complète",
            combinations=320,
            duration_seconds=612.0,
            max_rows=None,
            max_combinations=320,
        ),
        _DemoJobSpec(
            job_id="job_demo_favorite",
            status="completed",
            annotation="Favori",
            note="Favori prometteur mais encore court.",
            tags=("à tester plus longtemps",),
            score=41.2,
            trades=22,
            win_rate=54.5,
            drawdown_pct=12.8,
            preset="Test rapide local",
            combinations=12,
            duration_seconds=21.0,
            max_rows=20_000,
            max_combinations=12,
        ),
        _DemoJobSpec(
            job_id="job_demo_rejected",
            status="completed",
            annotation="Rejeté",
            note="Score faible et drawdown eleve : exemple a ne pas prioriser.",
            tags=("drawdown élevé",),
            score=-4.2,
            trades=36,
            win_rate=38.0,
            drawdown_pct=31.0,
            preset="Test moyen",
            combinations=100,
            duration_seconds=133.0,
            max_rows=100_000,
            max_combinations=100,
        ),
        _DemoJobSpec(
            job_id=SOURCE_RETEST_JOB_ID,
            status="completed",
            annotation="Champion",
            note="Champion source avec deux retests factices lies.",
            tags=("prometteur", "à tester plus longtemps"),
            score=63.5,
            trades=44,
            win_rate=55.1,
            drawdown_pct=13.2,
            preset="Test moyen",
            combinations=100,
            duration_seconds=187.0,
            max_rows=100_000,
            max_combinations=100,
        ),
        _DemoJobSpec(
            job_id=COMPLETED_RETEST_JOB_ID,
            status="completed",
            annotation="",
            note="Retest termine issu du Champion source.",
            tags=(),
            score=76.9,
            trades=103,
            win_rate=57.3,
            drawdown_pct=10.1,
            preset="Optimisation complète",
            combinations=300,
            duration_seconds=477.0,
            max_rows=None,
            max_combinations=300,
            source_job_id=SOURCE_RETEST_JOB_ID,
        ),
        _DemoJobSpec(
            job_id=STOPPED_RETEST_JOB_ID,
            status="stopped",
            annotation="",
            note="Retest stoppe lie au Champion source.",
            tags=(),
            score=25.0,
            trades=18,
            win_rate=50.0,
            drawdown_pct=18.8,
            preset="Test moyen",
            combinations=66,
            duration_seconds=98.0,
            max_rows=100_000,
            max_combinations=100,
            progress_pct=66.0,
            source_job_id=SOURCE_RETEST_JOB_ID,
        ),
    )


def _write_demo_job(job_dir: Path, spec: _DemoJobSpec, index: int) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now() - timedelta(minutes=15 * index)
    date = now.isoformat(timespec="seconds")
    config = _config_for(spec)
    meta = _meta_for(spec, date)
    progress = _progress_for(spec, date, job_dir)
    metrics = _metrics_for(spec, date)

    _write_json(job_dir / "config_used.json", config)
    _write_json(job_dir / "meta.json", meta)
    _write_json(job_dir / "metrics.json", metrics)
    _write_json(job_dir / "progress.json", progress)
    _write_json(job_dir / "tested.json", [f"demo_combo_{i}" for i in range(min(spec.combinations, 5))])
    _write_results_csv(job_dir / "results.csv", spec)
    _write_best_strategies_csv(job_dir / "best_strategies.csv", spec)
    _write_report(job_dir / "report.html", spec)
    _write_text(job_dir / "logs.txt", _logs_for(spec))
    _write_json(job_dir / "job_notes.json", _notes_for(spec, date))
    _write_json(job_dir / "job_decisions.json", _decisions_for(spec, date))
    build_job_archive(job_dir)


def _config_for(spec: _DemoJobSpec) -> dict:
    config = {
        "run_id": spec.job_id,
        "strategy_name": "Perfect Revolution V1",
        "strategy_module": "strategies/perfect_revolution_v1.py",
        "asset": "NASDAQ",
        "timeframe": "M3",
        "data_file": "demo/nasdaq_3m_demo.csv",
        "data_path": "demo/nasdaq_3m_demo.csv",
        "data_source": "demo_ui",
        "mode": 4,
        "preset_name": spec.preset,
        "preset_description": f"Preset factice {spec.preset}",
        "max_rows": spec.max_rows,
        "max_combinations": spec.max_combinations,
        "benchmark_n_sample": 3 if spec.preset == "Test moyen" else 5,
        "workers": 2,
        "n_workers": 2,
        "total_combinations": spec.combinations,
        "raw_total_combinations": max(spec.combinations, spec.max_combinations or spec.combinations),
        "quick_validation_mode": spec.preset == "Test rapide local",
        "base_params": {},
        "param_ranges": [
            {
                "name": "ema_fast",
                "param_type": "int",
                "label": "EMA rapide",
                "min_val": 8,
                "max_val": 14,
                "step": 2,
                "enabled": True,
            },
            {
                "name": "rsi_threshold",
                "param_type": "float",
                "label": "Seuil RSI",
                "min_val": 45.0,
                "max_val": 55.0,
                "step": 2.5,
                "enabled": True,
            },
        ],
        "score_weights": {},
        "filters": {},
        "train_test": {"enabled": False},
        "global_params": {},
    }
    if spec.source_job_id:
        config["source_job_id"] = spec.source_job_id
        config["relaunched_from_job_id"] = spec.source_job_id
        config["retest_plan_source_job_id"] = spec.source_job_id
        config["retest_plan_justification"] = "Retest factice relie au Champion source."
    return config


def _meta_for(spec: _DemoJobSpec, date: str) -> dict:
    top_100 = [_top_entry(spec)] if spec.score is not None and spec.score > 0 else []
    return {
        "run_id": spec.job_id,
        "date": date,
        "strategy_name": "Perfect Revolution V1",
        "mode": 4,
        "preset_name": spec.preset,
        "preset_description": f"Preset factice {spec.preset}",
        "status": spec.status,
        "variables_tested": ["ema_fast", "rsi_threshold"],
        "total_combinations": spec.combinations,
        "combinations_tested": spec.combinations,
        "combinations_filtered_out": 0,
        "duration_seconds": spec.duration_seconds,
        "workers_used": 2,
        "workers": 2,
        "benchmark_ms_per_backtest": 120.0,
        "top_100": top_100,
        "sensitivity": {"ema_fast": 0.21, "rsi_threshold": 0.13},
        "report": {
            "categorie": "Demo UI",
            "resume": "Rapport factice genere pour tester l'interface.",
        },
    }


def _metrics_for(spec: _DemoJobSpec, date: str) -> dict:
    metrics = {
        "job_id": spec.job_id,
        "generated_at": date,
        "strategy_name": "Perfect Revolution V1",
        "mode": 4,
        "preset_name": spec.preset,
        "preset_description": f"Preset factice {spec.preset}",
        "status": spec.status,
        "total_combinations": spec.combinations,
        "combinations_tested": spec.combinations,
        "combinations_filtered": 0,
        "duration_seconds": spec.duration_seconds,
        "workers_used": 2,
        "benchmark_ms": 120.0,
        "df_rows_used": spec.max_rows or 250_000,
        "n_top_results": 1 if spec.score and spec.score > 0 else 0,
        "top_10_scores": [spec.score] if spec.score is not None else [],
        "variables_tested": ["ema_fast", "rsi_threshold"],
        "sensitivity": {"ema_fast": 0.21, "rsi_threshold": 0.13},
    }
    if spec.score is not None:
        metrics.update({
            "best_score": spec.score,
            "best_total_trades": spec.trades,
            "best_win_rate": spec.win_rate,
            "best_max_dd_pct": spec.drawdown_pct,
            "best_profit_factor": 1.72 if spec.score > 0 else 0.0,
            "best_net_ret_pct": round(spec.score / 5, 2),
            "best_payoff": 1.25 if spec.score > 0 else 0.0,
            "best_params": {"ema_fast": 10, "rsi_threshold": 50.0},
        })
    return metrics


def _progress_for(spec: _DemoJobSpec, date: str, job_dir: Path) -> dict:
    done = int(round(spec.combinations * spec.progress_pct / 100.0))
    payload = {
        "job_id": spec.job_id,
        "job_dir": str(job_dir),
        "status": spec.status,
        "started_at": date,
        "updated_at": date,
        "completed": done,
        "failed": 0,
        "total_combinations": spec.combinations,
        "combinations_done": done,
        "combinations_total": spec.combinations,
        "progress_pct": spec.progress_pct,
        "elapsed_seconds": spec.duration_seconds,
        "duration_seconds": spec.duration_seconds,
        "best_score": spec.score or 0,
        "workers_used": 2,
    }
    if spec.error_message:
        payload["error_message"] = spec.error_message
    return payload


def _top_entry(spec: _DemoJobSpec) -> dict:
    return {
        "rank": 1,
        "score": spec.score,
        "score_train": spec.score,
        "score_test": spec.score,
        "degradation_pct": 0.0,
        "overfitting_alert": False,
        "params": {"ema_fast": 10, "rsi_threshold": 50.0},
        "warnings": [],
        "stats": {
            "profit_factor": 1.72,
            "total_trades": spec.trades or 0,
            "n_trades": spec.trades or 0,
            "win_rate": spec.win_rate or 0,
            "max_dd_pct": spec.drawdown_pct or 0,
            "net_ret_pct": round((spec.score or 0) / 5, 2),
            "max_consec_loss": 3,
            "payoff": 1.25,
            "equity_r_squared": 0.82,
            "net_ret_usd": round((spec.score or 0) * 15, 2),
            "max_dd_usd": round((spec.drawdown_pct or 0) * 25, 2),
        },
    }


def _write_results_csv(path: Path, spec: _DemoJobSpec) -> None:
    rows = []
    if spec.score is not None:
        rows.append({
            "score": spec.score,
            "filtered": False,
            "filter_reason": "",
            "warnings": "",
            "param_ema_fast": 10,
            "param_rsi_threshold": 50.0,
            "stat_n_trades": spec.trades if spec.trades is not None else "",
            "stat_win_rate": spec.win_rate if spec.win_rate is not None else "",
            "stat_max_dd_pct": spec.drawdown_pct if spec.drawdown_pct is not None else "",
        })
    _write_csv(path, rows, [
        "score",
        "filtered",
        "filter_reason",
        "warnings",
        "param_ema_fast",
        "param_rsi_threshold",
        "stat_n_trades",
        "stat_win_rate",
        "stat_max_dd_pct",
    ])


def _write_best_strategies_csv(path: Path, spec: _DemoJobSpec) -> None:
    rows = []
    if spec.score is not None and spec.score > 0:
        rows.append({
            "rank": 1,
            "score": spec.score,
            "param_ema_fast": 10,
            "param_rsi_threshold": 50.0,
            "stat_total_trades": spec.trades or 0,
            "stat_win_rate": spec.win_rate or 0,
            "stat_max_dd_pct": spec.drawdown_pct or 0,
        })
    _write_csv(path, rows, [
        "rank",
        "score",
        "param_ema_fast",
        "param_rsi_threshold",
        "stat_total_trades",
        "stat_win_rate",
        "stat_max_dd_pct",
    ])


def _notes_for(spec: _DemoJobSpec, date: str) -> dict:
    return {
        "status": spec.annotation,
        "note": spec.note,
        "tags": list(spec.tags),
        "updated_at": date,
    }


def _decisions_for(spec: _DemoJobSpec, date: str) -> dict:
    events = []
    if spec.annotation:
        events.append({
            "timestamp": date,
            "event_type": "annotation_status_changed",
            "category": "annotation",
            "message": f"Classement demo : {spec.annotation}.",
            "old_state": {"status": ""},
            "new_state": {"status": spec.annotation},
        })
    if spec.job_id == SOURCE_RETEST_JOB_ID:
        events.append({
            "timestamp": date,
            "event_type": RETEST_PLAN_EVENT_LAUNCHED,
            "category": CATEGORY_ACTION,
            "message": f"Retest demo lance dans {COMPLETED_RETEST_JOB_ID}.",
            "old_state": None,
            "new_state": {
                "source_job_id": SOURCE_RETEST_JOB_ID,
                "new_job_id": COMPLETED_RETEST_JOB_ID,
                "recommended_preset": "Optimisation complète",
            },
        })
        events.append({
            "timestamp": date,
            "event_type": RETEST_PLAN_EVENT_LAUNCHED,
            "category": CATEGORY_ACTION,
            "message": f"Retest demo stoppe dans {STOPPED_RETEST_JOB_ID}.",
            "old_state": None,
            "new_state": {
                "source_job_id": SOURCE_RETEST_JOB_ID,
                "new_job_id": STOPPED_RETEST_JOB_ID,
                "recommended_preset": "Test moyen",
            },
        })
    return {"version": 1, "events": events}


def _write_report(path: Path, spec: _DemoJobSpec) -> None:
    title = f"Rapport demo {spec.job_id}"
    body = (
        "<!doctype html><html lang=\"fr\"><meta charset=\"utf-8\">"
        f"<title>{title}</title><body>"
        f"<h1>{title}</h1>"
        "<p>Données factices pour tester l'interface Streamlit.</p>"
        f"<p>Statut : {spec.status}</p>"
        "</body></html>"
    )
    _write_text(path, body)


def _logs_for(spec: _DemoJobSpec) -> str:
    lines = [
        f"[demo] job_id={spec.job_id}",
        f"[demo] status={spec.status}",
        "[demo] aucun backtest reel n'a ete lance.",
    ]
    if spec.source_job_id:
        lines.append(f"[demo] source champion={spec.source_job_id}")
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
