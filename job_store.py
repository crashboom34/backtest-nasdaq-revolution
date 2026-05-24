"""
job_store.py — Génération des artefacts finaux pour un job.

Appelé par optimizer_process.py à la fin du run (mode job uniquement).

Fichiers générés dans job_dir/ :
  metrics.json        KPI synthétiques du job
  best_strategies.csv Top 100 stratégies triées par score
  report.html         Rapport standalone (zéro dépendance externe)
  logs.txt            Journal d'exécution
  archive.zip         Bundle des 7 fichiers principaux
"""

import csv
import json
import os
import zipfile
from datetime import datetime
from typing import List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# MÉTRIQUES (KPI synthétiques)
# ══════════════════════════════════════════════════════════════════════════════

def write_metrics(
    job_dir: str,
    meta: dict,
    config_dict: dict,
    benchmark_ms: float,
    df_rows_used: int,
) -> None:
    """Écrit metrics.json — résumé KPI du job."""
    top = meta.get("top_100", [{}])
    best = top[0] if top else {}
    best_stats = best.get("stats", {})

    metrics = {
        "job_id":               os.path.basename(job_dir),
        "generated_at":         datetime.now().isoformat(),
        "strategy_name":        meta.get("strategy_name", ""),
        "mode":                 meta.get("mode", ""),
        "status":               meta.get("status", "completed"),

        # Perf optimisation
        "total_combinations":   meta.get("total_combinations", 0),
        "combinations_tested":  meta.get("combinations_tested", 0),
        "combinations_filtered": meta.get("combinations_filtered_out", 0),
        "duration_seconds":     meta.get("duration_seconds", 0),
        "workers_used":         meta.get("workers_used", 1),
        "benchmark_ms":         round(benchmark_ms, 1),
        "df_rows_used":         df_rows_used,

        # Best strategy
        "best_score":           best.get("score", 0),
        "best_params":          best.get("params", {}),
        "best_profit_factor":   best_stats.get("profit_factor", 0),
        "best_win_rate":        best_stats.get("win_rate", 0),
        "best_max_dd_pct":      best_stats.get("max_dd_pct", 0),
        "best_total_trades":    best_stats.get("total_trades", 0),
        "best_net_ret_pct":     best_stats.get("net_ret_pct", 0),
        "best_net_ret_usd":     best_stats.get("net_ret_usd", 0),
        "best_max_dd_usd":      best_stats.get("max_dd_usd", 0),
        "best_payoff":          best_stats.get("payoff", 0),

        # Dégradation train/test
        "best_score_train":     best.get("score_train", best.get("score", 0)),
        "best_score_test":      best.get("score_test",  best.get("score", 0)),
        "best_degradation_pct": best.get("degradation_pct", 0),

        # Top N scores
        "top_10_scores":        [r.get("score", 0) for r in top[:10]],
        "n_top_results":        len(top),

        # Variables optimisées
        "variables_tested":     meta.get("variables_tested", []),
        "sensitivity":          meta.get("sensitivity", {}),
    }

    _write_json(os.path.join(job_dir, "metrics.json"), metrics)


# ══════════════════════════════════════════════════════════════════════════════
# MEILLEURES STRATÉGIES (CSV lisible)
# ══════════════════════════════════════════════════════════════════════════════

def write_best_strategies(
    job_dir: str,
    top_results: list,
    n: int = 100,
) -> None:
    """Écrit best_strategies.csv — top N stratégies triées par score."""
    path = os.path.join(job_dir, "best_strategies.csv")

    if not top_results:
        fieldnames = [
            "rank", "score", "score_train", "score_test",
            "degradation_pct", "overfitting_alert", "warnings",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
        return

    rows = top_results[:n]

    # Collecter toutes les clés de params et stats
    all_param_keys = set()
    all_stat_keys  = set()
    for r in rows:
        all_param_keys.update(r.get("params", {}).keys())
        all_stat_keys.update(
            k for k, v in r.get("stats", {}).items()
            if not isinstance(v, (dict, list))
        )

    param_keys = sorted(all_param_keys)
    stat_keys  = sorted(all_stat_keys)

    fieldnames = (
        ["rank", "score", "score_train", "score_test", "degradation_pct", "overfitting_alert"]
        + [f"param_{k}" for k in param_keys]
        + [f"stat_{k}"  for k in stat_keys]
        + ["warnings"]
    )

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rank, r in enumerate(rows, start=1):
            row = {
                "rank":              rank,
                "score":             round(r.get("score", 0), 2),
                "score_train":       round(r.get("score_train", r.get("score", 0)), 2),
                "score_test":        round(r.get("score_test",  r.get("score", 0)), 2),
                "degradation_pct":   round(r.get("degradation_pct", 0), 1),
                "overfitting_alert": r.get("overfitting_alert", False),
                "warnings":          "; ".join(r.get("warnings", [])),
            }
            for k, v in r.get("params", {}).items():
                row[f"param_{k}"] = v
            for k, v in r.get("stats", {}).items():
                if not isinstance(v, (dict, list)):
                    row[f"stat_{k}"] = v
            writer.writerow(row)


# ══════════════════════════════════════════════════════════════════════════════
# RAPPORT HTML (standalone, zéro dépendance externe)
# ══════════════════════════════════════════════════════════════════════════════

def write_report_html(
    job_dir: str,
    meta: dict,
    config_dict: dict,
) -> None:
    """Génère report.html — rapport standalone sans librairies externes."""

    job_id     = os.path.basename(job_dir)
    top        = meta.get("top_100", [])
    best       = top[0] if top else {}
    best_stats = best.get("stats", {})
    best_par   = best.get("params", {})
    sens       = meta.get("sensitivity", {})
    report_d   = meta.get("report", {})
    filters    = config_dict.get("filters", {})
    sw         = config_dict.get("score_weights", {})
    tt         = config_dict.get("train_test", {})
    now        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Top 10 rows ───────────────────────────────────────────────────────────
    top10_rows = ""
    for i, r in enumerate(top[:10], start=1):
        s  = r.get("stats", {})
        bg = "#f0fff4" if i == 1 else ("#fff" if i % 2 == 0 else "#fafafa")
        top10_rows += f"""
        <tr style="background:{bg}">
          <td><b>{i}</b></td>
          <td><b>{r.get('score', 0):.2f}</b></td>
          <td>{s.get('profit_factor', 0):.2f}</td>
          <td>{s.get('win_rate', 0):.1f}%</td>
          <td>{s.get('max_dd_pct', 0):.1f}%</td>
          <td>{int(s.get('total_trades', 0))}</td>
          <td>{s.get('net_ret_pct', 0):.1f}%</td>
          <td>{_fmt_params(r.get('params', {}))}</td>
        </tr>"""

    # ── Sensitivity rows ──────────────────────────────────────────────────────
    sens_rows = ""
    if sens:
        for var, score in sorted(sens.items(), key=lambda x: -x[1]):
            bar_w = min(100, int(score * 10))
            sens_rows += f"""
        <tr>
          <td>{var}</td>
          <td>
            <div style="background:#e2e8f0;border-radius:4px;height:16px;width:200px;">
              <div style="background:#3b82f6;width:{bar_w}%;height:100%;border-radius:4px;"></div>
            </div>
          </td>
          <td>{score:.3f}</td>
        </tr>"""

    # ── Best params rows ──────────────────────────────────────────────────────
    params_rows = ""
    for k, v in best_par.items():
        params_rows += f"<tr><td><code>{k}</code></td><td><b>{v}</b></td></tr>"

    # ── Score weights rows ────────────────────────────────────────────────────
    sw_rows = ""
    for k, v in sw.items():
        sw_rows += f"<tr><td>{k}</td><td>{v}</td></tr>"

    # ── Filters rows ──────────────────────────────────────────────────────────
    filt_rows = ""
    for k, v in filters.items():
        filt_rows += f"<tr><td>{k}</td><td>{v}</td></tr>"

    # ── Status badge ──────────────────────────────────────────────────────────
    status     = meta.get("status", "completed")
    status_col = {"completed": "#22c55e", "error": "#ef4444", "stopped": "#f59e0b"}.get(status, "#6b7280")

    # ── Train/Test block ──────────────────────────────────────────────────────
    tt_block = ""
    if tt.get("enabled"):
        tt_block = f"""
      <div class="card">
        <h2>Train / Test</h2>
        <table><tr><th>Paramètre</th><th>Valeur</th></tr>
          <tr><td>Méthode split</td><td>{tt.get('split_method','ratio')}</td></tr>
          <tr><td>Ratio train</td><td>{tt.get('train_ratio', 0.7):.0%}</td></tr>
          <tr><td>Alert dégradation</td><td>{tt.get('alert_degradation_pct', 30)}%</td></tr>
          <tr><td>Score train (best)</td><td>{best.get('score_train', best.get('score', 0)):.2f}</td></tr>
          <tr><td>Score test (best)</td><td>{best.get('score_test', best.get('score', 0)):.2f}</td></tr>
          <tr><td>Dégradation (best)</td><td>{best.get('degradation_pct', 0):.1f}%</td></tr>
        </table>
      </div>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rapport — {job_id}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          background: #f8fafc; color: #1e293b; font-size: 14px; line-height: 1.6; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px; }}
  header {{ background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
             color: white; padding: 28px 32px; border-radius: 12px; margin-bottom: 24px; }}
  header h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 6px; }}
  header .meta {{ opacity: 0.85; font-size: 13px; }}
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px;
            font-size: 12px; font-weight: 600; color: white;
            background: {status_col}; margin-left: 8px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
           gap: 16px; margin-bottom: 24px; }}
  .kpi {{ background: white; border-radius: 10px; padding: 20px;
          box-shadow: 0 1px 4px rgba(0,0,0,.08); border-left: 4px solid #3b82f6; }}
  .kpi .label {{ color: #64748b; font-size: 12px; font-weight: 500; text-transform: uppercase;
                 letter-spacing: .05em; margin-bottom: 6px; }}
  .kpi .value {{ font-size: 26px; font-weight: 700; color: #0f172a; }}
  .kpi .unit  {{ font-size: 13px; color: #94a3b8; margin-left: 3px; }}
  .card {{ background: white; border-radius: 10px; padding: 20px;
           box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 20px; }}
  .card h2 {{ font-size: 16px; font-weight: 600; color: #1e40af; margin-bottom: 14px;
              padding-bottom: 8px; border-bottom: 2px solid #e2e8f0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #f1f5f9; color: #475569; font-weight: 600; padding: 8px 12px;
        text-align: left; border-bottom: 2px solid #e2e8f0; }}
  td {{ padding: 7px 12px; border-bottom: 1px solid #f1f5f9; }}
  code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
  footer {{ text-align: center; color: #94a3b8; font-size: 12px; margin-top: 32px;
            padding-top: 16px; border-top: 1px solid #e2e8f0; }}
</style>
</head>
<body>
<div class="container">

  <header>
    <h1>Rapport d'optimisation
      <span class="badge">{status}</span>
    </h1>
    <div class="meta">
      Job : {job_id} &nbsp;|&nbsp;
      Stratégie : {meta.get('strategy_name', '?')} &nbsp;|&nbsp;
      Mode : {meta.get('mode', '?')} &nbsp;|&nbsp;
      Généré le {now}
    </div>
  </header>

  <!-- KPIs -->
  <div class="grid">
    <div class="kpi">
      <div class="label">Meilleur Score</div>
      <div class="value">{best.get('score', 0):.2f}</div>
    </div>
    <div class="kpi">
      <div class="label">Profit Factor</div>
      <div class="value">{best_stats.get('profit_factor', 0):.2f}</div>
    </div>
    <div class="kpi">
      <div class="label">Win Rate</div>
      <div class="value">{best_stats.get('win_rate', 0):.1f}<span class="unit">%</span></div>
    </div>
    <div class="kpi">
      <div class="label">Max Drawdown</div>
      <div class="value">{best_stats.get('max_dd_pct', 0):.1f}<span class="unit">%</span></div>
    </div>
    <div class="kpi">
      <div class="label">Trades</div>
      <div class="value">{int(best_stats.get('total_trades', 0))}</div>
    </div>
    <div class="kpi">
      <div class="label">Retour Net</div>
      <div class="value">{best_stats.get('net_ret_pct', 0):.1f}<span class="unit">%</span></div>
    </div>
    <div class="kpi">
      <div class="label">Combos testées</div>
      <div class="value">{meta.get('combinations_tested', 0)}</div>
    </div>
    <div class="kpi">
      <div class="label">Durée</div>
      <div class="value">{_fmt_duration(meta.get('duration_seconds', 0))}</div>
    </div>
  </div>

  <!-- Top 10 -->
  <div class="card">
    <h2>Top 10 Stratégies</h2>
    <table>
      <tr>
        <th>#</th><th>Score</th><th>PF</th><th>Win%</th>
        <th>DD%</th><th>Trades</th><th>Net%</th><th>Paramètres</th>
      </tr>
      {top10_rows}
    </table>
  </div>

  <!-- Best params -->
  <div class="card">
    <h2>Meilleurs Paramètres</h2>
    <table>
      <tr><th>Paramètre</th><th>Valeur</th></tr>
      {params_rows if params_rows else '<tr><td colspan="2">Aucun paramètre</td></tr>'}
    </table>
  </div>

  <!-- Sensibilité -->
  {'<div class="card"><h2>Sensibilité des Variables</h2><table><tr><th>Variable</th><th>Impact</th><th>Score</th></tr>' + sens_rows + '</table></div>' if sens_rows else ''}

  {tt_block}

  <!-- Config -->
  <div class="grid" style="grid-template-columns:1fr 1fr;margin-bottom:0">
    <div class="card">
      <h2>Poids des Scores</h2>
      <table>
        <tr><th>Critère</th><th>Poids</th></tr>
        {sw_rows if sw_rows else '<tr><td colspan="2">Défaut</td></tr>'}
      </table>
    </div>
    <div class="card">
      <h2>Filtres</h2>
      <table>
        <tr><th>Filtre</th><th>Valeur</th></tr>
        {filt_rows if filt_rows else '<tr><td colspan="2">Défaut</td></tr>'}
      </table>
    </div>
  </div>

  <footer>
    Backtest Optimizer &mdash; {now} &mdash; Job {job_id}
  </footer>

</div>
</body>
</html>"""

    with open(os.path.join(job_dir, "report.html"), "w", encoding="utf-8") as f:
        f.write(html)


# ══════════════════════════════════════════════════════════════════════════════
# LOGS
# ══════════════════════════════════════════════════════════════════════════════

def write_logs(job_dir: str, log_lines: List[str]) -> None:
    """Écrit logs.txt — journal complet du run."""
    path = os.path.join(job_dir, "logs.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
        if log_lines and not log_lines[-1].endswith("\n"):
            f.write("\n")


# ══════════════════════════════════════════════════════════════════════════════
# ARCHIVE ZIP
# ══════════════════════════════════════════════════════════════════════════════

# Fichiers inclus dans l'archive (les 7 principaux, hors tested.json/meta.json/stop.flag)
_ARCHIVE_FILES = [
    "progress.json",
    "config_used.json",
    "results.csv",
    "metrics.json",
    "best_strategies.csv",
    "report.html",
    "logs.txt",
]


def write_archive(job_dir: str) -> Optional[str]:
    """
    Crée archive.zip contenant les 7 fichiers principaux du job.
    Retourne le chemin de l'archive, ou None si aucun fichier trouvé.
    """
    archive_path = os.path.join(job_dir, "archive.zip")
    found = []

    for filename in _ARCHIVE_FILES:
        fp = os.path.join(job_dir, filename)
        if os.path.exists(fp):
            found.append((filename, fp))

    if not found:
        return None

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, fp in found:
            zf.write(fp, arcname=filename)

    return archive_path


# ══════════════════════════════════════════════════════════════════════════════
# FINALIZATION (point d'entrée unique pour optimizer_process)
# ══════════════════════════════════════════════════════════════════════════════

def finalize_job(
    job_dir: str,
    meta: dict,
    config_dict: dict,
    all_results: list,
    benchmark_ms: float,
    df_rows_used: int,
    log_lines: List[str],
) -> None:
    """
    Génère tous les artefacts finaux du job dans job_dir.
    Appelé à la fin d'optimizer_process.py quand job_dir est fourni.
    """
    top_results = [r for r in all_results if r.get("score", 0) > 0]
    top_results.sort(key=lambda r: r["score"], reverse=True)

    write_metrics(job_dir, meta, config_dict, benchmark_ms, df_rows_used)
    write_best_strategies(job_dir, top_results)
    write_report_html(job_dir, meta, config_dict)
    write_logs(job_dir, log_lines)
    write_archive(job_dir)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS INTERNES
# ══════════════════════════════════════════════════════════════════════════════

def _write_json(path: str, data: dict) -> None:
    """Écriture JSON simple (non atomique, pour artefacts finaux)."""
    import math

    def _default(obj):
        if hasattr(obj, "item"):
            return obj.item()
        if isinstance(obj, float) and math.isinf(obj):
            return "Inf"
        if isinstance(obj, set):
            return list(obj)
        raise TypeError(f"Not JSON serializable: {type(obj)}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=_default)


def _fmt_params(params: dict) -> str:
    """Formate les paramètres en une courte string pour tableau HTML."""
    if not params:
        return "—"
    return ", ".join(f"{k}={v}" for k, v in list(params.items())[:4])


def _fmt_duration(seconds: float) -> str:
    """Formate une durée en 'Xh Ym Zs'."""
    if not seconds:
        return "0s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"
