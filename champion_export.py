"""Exports en mémoire du Rapport Champion, sans dépendance externe."""

from __future__ import annotations

import html
import re

from champion_report import ChampionReport


def champion_export_filename(report: ChampionReport, extension: str) -> str:
    ext = str(extension).lower().lstrip(".")
    if ext not in {"md", "html"}:
        raise ValueError(f"Format d'export non supporté : {extension}")
    safe_job_id = re.sub(r"[^A-Za-z0-9_-]+", "_", report.record.job_id).strip("_")
    return f"rapport_champion_{safe_job_id or 'job'}.{ext}"


def render_champion_markdown(report: ChampionReport) -> str:
    record = report.record
    annotation = record.annotation
    lines = [
        f"# Rapport Champion - {record.job_id}",
        "",
        "## Synthèse",
        "",
    ]
    lines.extend(
        f"- **{label}** : {value}"
        for label, value in _summary_rows(report)
    )
    lines.extend([
        "",
        "## Fichiers disponibles",
        "",
        *_markdown_list(report.available_files, "Aucun fichier disponible."),
        "",
        "## Points forts",
        "",
        *_markdown_list(report.strengths, "Aucun point fort confirmé."),
        "",
        "## Points faibles",
        "",
        *_markdown_list(report.weaknesses, "Aucun point faible majeur détecté."),
        "",
        "## Décision recommandée",
        "",
        f"**{report.decision.title}**",
        "",
        report.decision.explanation,
        "",
        "> Cette recommandation est une aide à la décision. "
        "Elle ne garantit pas les performances futures.",
        "",
    ])
    return "\n".join(lines)


def render_champion_html(report: ChampionReport) -> str:
    record = report.record
    rows = "\n".join(
        "<tr>"
        f"<th>{html.escape(label)}</th>"
        f"<td>{html.escape(value)}</td>"
        "</tr>"
        for label, value in _summary_rows(report)
    )
    files = _html_list(report.available_files, "Aucun fichier disponible.")
    strengths = _html_list(report.strengths, "Aucun point fort confirmé.")
    weaknesses = _html_list(
        report.weaknesses,
        "Aucun point faible majeur détecté.",
    )
    title = f"Rapport Champion - {record.job_id}"
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; color: #202124; margin: 0; background: #f6f7f9; }}
    main {{ max-width: 900px; margin: 0 auto; padding: 32px 20px; }}
    h1, h2 {{ color: #172033; }}
    section {{ background: white; border: 1px solid #dfe3e8; padding: 20px; margin: 16px 0; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #e8eaed; text-align: left; }}
    th {{ width: 34%; color: #5f6368; }}
    li {{ margin: 7px 0; }}
    .decision {{ border-left: 4px solid #2563eb; }}
    .notice {{ color: #5f6368; font-size: 13px; }}
  </style>
</head>
<body>
<main>
  <h1>{html.escape(title)}</h1>
  <section>
    <h2>Synthèse</h2>
    <table>{rows}</table>
  </section>
  <section>
    <h2>Fichiers disponibles</h2>
    {files}
  </section>
  <section>
    <h2>Points forts</h2>
    {strengths}
  </section>
  <section>
    <h2>Points faibles</h2>
    {weaknesses}
  </section>
  <section class="decision">
    <h2>Décision recommandée</h2>
    <p><strong>{html.escape(report.decision.title)}</strong></p>
    <p>{html.escape(report.decision.explanation)}</p>
    <p class="notice">Cette recommandation est une aide à la décision. Elle ne garantit pas les performances futures.</p>
  </section>
</main>
</body>
</html>
"""


def _summary_rows(report: ChampionReport) -> list[tuple[str, str]]:
    record = report.record
    annotation = record.annotation
    return [
        ("Job ID", record.job_id),
        ("Date", record.date or "Indisponible"),
        ("Statut annotation", annotation.status or "Non classé"),
        ("Note utilisateur", annotation.note or "Aucune note"),
        ("Tags", ", ".join(annotation.tags) or "Aucun tag"),
        ("Actif", record.asset),
        ("Timeframe", record.timeframe),
        ("Preset", record.preset),
        ("Fichier de données", record.data_file),
        ("Score", _number(record.score, 2)),
        ("Nombre de trades", _integer(record.trades)),
        ("Win rate", _percentage(record.win_rate)),
        ("Drawdown", _percentage(record.drawdown_pct)),
        ("Durée", _duration(record.duration_seconds)),
        ("Combinaisons testées", _integer(record.combinations)),
    ]


def _number(value, decimals: int) -> str:
    if value is None:
        return "Indisponible"
    return f"{float(value):.{decimals}f}"


def _integer(value) -> str:
    if value is None:
        return "Indisponible"
    return str(int(value))


def _percentage(value) -> str:
    if value is None:
        return "Indisponible"
    return f"{float(value):.2f} %"


def _duration(value) -> str:
    if value is None:
        return "Indisponible"
    total = max(0, int(float(value)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _markdown_list(values, empty_message: str) -> list[str]:
    items = [str(value) for value in values if str(value).strip()]
    return [f"- {value}" for value in items] if items else [f"- {empty_message}"]


def _html_list(values, empty_message: str) -> str:
    items = [str(value) for value in values if str(value).strip()]
    if not items:
        items = [empty_message]
    return "<ul>" + "".join(
        f"<li>{html.escape(value)}</li>"
        for value in items
    ) + "</ul>"
