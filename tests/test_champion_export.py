import hashlib
import json
from pathlib import Path

from champion_export import (
    champion_export_filename,
    render_champion_html,
    render_champion_markdown,
)
from champion_report import load_champion_report
from champion_validation import ChampionValidationSettings
from job_annotations import save_annotation


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report(tmp_path: Path, *, complete: bool = True, settings=None):
    job_dir = tmp_path / "job_export"
    job_dir.mkdir()
    _write_json(job_dir / "config_used.json", {
        "asset": "NASDAQ",
        "timeframe": "M3",
        "preset_name": "Test moyen",
        "data_file": "nasdaq_3m.csv",
        "strategy_name": "Perfect Revolution",
    })
    if complete:
        _write_json(job_dir / "metrics.json", {
            "status": "completed",
            "best_score": 42.5,
            "best_total_trades": 48,
            "best_win_rate": 56.4,
            "best_max_dd_pct": 9.2,
            "duration_seconds": 125,
            "combinations_tested": 86,
        })
        (job_dir / "results.csv").write_text("score\n42.5\n", encoding="utf-8")
    save_annotation(
        job_dir,
        status="Champion",
        note="Solide <à confirmer> & surveiller.",
        tags=["prometteur", "à tester plus longtemps"],
    )
    job = {
        "job_id": "job_export",
        "job_dir": str(job_dir),
        "status": "completed",
        "date": "2026-06-21T14:30:00",
    }
    return load_champion_report(job, settings=settings), job_dir


def test_markdown_export_is_non_empty_and_complete(tmp_path):
    report, _ = _report(tmp_path)

    content = render_champion_markdown(report)

    assert len(content.encode("utf-8")) > 100
    for expected in (
        "job_export",
        "Champion",
        "Solide <à confirmer> & surveiller.",
        "prometteur",
        "NASDAQ",
        "M3",
        "Test moyen",
        "nasdaq_3m.csv",
        "42.50",
        "48",
        "56.40 %",
        "9.20 %",
        "2m 05s",
        "86",
        "results.csv",
        "Points forts",
        "Points faibles",
        "Checklist de validation",
        "Nombre de trades suffisant",
        "Prometteur mais à retester",
        "Décision recommandée",
    ):
        assert expected in content


def test_html_export_is_non_empty_complete_and_escaped(tmp_path):
    report, _ = _report(tmp_path)

    content = render_champion_html(report)

    assert len(content.encode("utf-8")) > 200
    assert content.startswith("<!doctype html>")
    assert "<title>Rapport Champion - job_export</title>" in content
    assert "Solide &lt;à confirmer&gt; &amp; surveiller." in content
    assert "Solide <à confirmer> & surveiller." not in content
    assert "results.csv" in content
    assert "Checklist de validation" in content
    assert "Nombre de trades suffisant" in content
    assert "Prometteur mais à retester" in content
    assert "Décision recommandée" in content


def test_exports_support_legacy_job_without_metrics(tmp_path):
    report, _ = _report(tmp_path, complete=False)

    markdown = render_champion_markdown(report)
    html = render_champion_html(report)

    assert "Ancien job" not in markdown
    assert "Indisponible" in markdown
    assert "Indisponible" in html
    assert "Garder en observation" in markdown


def test_export_filenames_are_stable_and_safe(tmp_path):
    report, _ = _report(tmp_path)

    assert champion_export_filename(report, "md") == "rapport_champion_job_export.md"
    assert champion_export_filename(report, "html") == "rapport_champion_job_export.html"


def test_exports_do_not_modify_raw_result_files(tmp_path):
    report, job_dir = _report(tmp_path)
    raw_names = ("config_used.json", "metrics.json", "results.csv")
    before = {name: _hash(job_dir / name) for name in raw_names}

    render_champion_markdown(report)
    render_champion_html(report)

    assert {name: _hash(job_dir / name) for name in raw_names} == before


def test_exports_use_configured_thresholds(tmp_path):
    report, _ = _report(
        tmp_path,
        settings=ChampionValidationSettings(
            min_trades=75,
            min_score=10.0,
            min_combinations=300,
        ),
    )

    markdown = render_champion_markdown(report)
    html = render_champion_html(report)

    assert "seuil conseillé : 75" in markdown
    assert "seuil minimum : 10.00" in markdown
    assert "seuil conseillé : 300" in html
