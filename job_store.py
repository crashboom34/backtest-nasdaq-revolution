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
import html as html_lib
import json
import os
from datetime import datetime
from typing import List, Optional

from job_artifacts import ARCHIVE_SOURCE_FILES, build_job_archive
from market_data.backtest_manifest import build_backtest_manifest, save_backtest_manifest
# Alias explicite : évite que le paramètre `content_hash` (str) de write_data_manifest()/
# compute_source_content_hash() ne masque la fonction dans leur propre portée — risque de
# shadowing déjà anticipé lors de la revue Standards d'AF-DATA-01.
from market_data.content_hash import content_hash as compute_content_hash
from research_run import build_experiment, build_research_run, save_experiment, save_research_run


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
        "preset_name":          config_dict.get("preset_name", meta.get("preset_name", "")),
        "preset_description":   config_dict.get("preset_description", meta.get("preset_description", "")),
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
    preset_name = html_lib.escape(str(config_dict.get("preset_name") or meta.get("preset_name") or "Ancien job"))
    preset_desc = html_lib.escape(str(config_dict.get("preset_description") or meta.get("preset_description") or ""))
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

    preset_block = f"""
      <div class="card">
        <h2>Préréglage</h2>
        <table><tr><th>Paramètre</th><th>Valeur</th></tr>
          <tr><td>Nom</td><td>{preset_name}</td></tr>
          <tr><td>Description</td><td>{preset_desc}</td></tr>
          <tr><td>Lignes max</td><td>{config_dict.get('max_rows') or 'Historique complet'}</td></tr>
          <tr><td>Combinaisons max</td><td>{config_dict.get('max_combinations') or 'Illimité'}</td></tr>
          <tr><td>Benchmark</td><td>{config_dict.get('benchmark_n_sample', 5)}</td></tr>
          <tr><td>Workers</td><td>{config_dict.get('n_workers', 1)}</td></tr>
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
      <div class="label">Préréglage</div>
      <div class="value">{preset_name}</div>
    </div>
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
  {preset_block}

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
_ARCHIVE_FILES = ARCHIVE_SOURCE_FILES


def write_archive(job_dir: str) -> Optional[str]:
    """
    Crée archive.zip contenant les 7 fichiers principaux du job.
    Retourne le chemin de l'archive, ou None si aucun fichier trouvé.
    """
    archive_path = build_job_archive(job_dir)
    return str(archive_path) if archive_path else None


# ══════════════════════════════════════════════════════════════════════════════
# MANIFESTE REPRODUCTIBLE (Data Center Phase 11 — additif)
# ══════════════════════════════════════════════════════════════════════════════

def compute_source_content_hash(data_file: str) -> Optional[str]:
    """Identité de contenu (SHA-256, `market_data.content_hash`) du fichier source local utilisé
    par ce run — voir EPICS_AND_TICKETS.md, AF-DATA-02. C'est le hash de l'ARTEFACT SOURCE, pas
    encore un `DatasetVersion` sémantique complet (voir AF-DATA-01/02, "Out of scope").

    HASH ONCE : à appeler une seule fois par run, au moment où le fichier source vient d'être
    chargé avec succès (voir optimizer_process.py) — jamais recalculé ici ni dans
    `write_data_manifest()`/`finalize_job()`, qui se contentent de propager la valeur reçue.

    Best-effort explicite, à la même politique que `write_data_manifest()` et
    `market_data.backtest_manifest._current_git_commit()` : un calcul de provenance impossible
    (fichier illisible/déplacé entre le chargement et cet appel) ne doit jamais faire planter le
    job — retourne `None` plutôt que de lever. C'est un échec de calcul de provenance, distinct
    d'un échec de chargement des données (déjà géré, bien plus tôt, en amont de cet appel).

    GARANTIE EXACTE (AF-DATA-04A, formulée honnêtement — ne pas sur-promettre) : ce hash certifie
    les octets du fichier source **tels qu'observés au moment de cet appel**, via une lecture
    streamée dédiée (`market_data.content_hash`). Ce n'est **pas** une preuve cryptographique
    atomique que ces octets sont exactement ceux déjà parsés dans le DataFrame utilisé par le
    backtest (le chargement et ce hachage sont deux lectures disque indépendantes du même
    fichier). `optimizer_process.py` complète cette garantie par un contrôle de stabilité léger
    et non cryptographique (`capture_source_signature`/`assert_source_signature_unchanged` —
    taille + `mtime_ns`, PAS un second SHA-256), qui détecte une modification ORDINAIRE du
    fichier survenue entre le chargement et ce hachage — c'est le threat model réel de ce
    pipeline CSV local mono-processus (aucun écrivain concurrent connu), pas une protection
    contre un acteur malveillant capable de falsifier taille et horodatage en même temps que le
    contenu.
    """
    try:
        return compute_content_hash(data_file)
    except OSError as exc:
        print(f"[job_store] content_hash non calculé pour {data_file!r} (non bloquant) : {exc}")
        return None


def build_local_csv_snapshot_id(content_hash_value: Optional[str]) -> Optional[str]:
    """Référence de snapshot content-addressed, typée par source, pour le chemin CSV local
    (AF-DATA-04A) : `"local_csv:sha256:" + content_hash`.

    Distincte de `content_hash` brut (le digest cryptographique seul) : `snapshot_id` porte en
    plus le type de source (`local_csv`) et l'algorithme (`sha256`), explicites — un futur
    provider (EODHD/Dukascopy, `DATA-ADVANCED`) pourra utiliser sa propre convention de
    `snapshot_id` sans collision ni migration de schéma (confirmé via `domain-modeling`,
    2026-08-15 : pas une duplication sémantique de `content_hash`, pas un `DatasetVersion`
    catalogué non plus — juste une référence de snapshot content-addressed typée).

    Retourne `None` si `content_hash_value` est `None` (rien à référencer).
    """
    if content_hash_value is None:
        return None
    return f"local_csv:sha256:{content_hash_value}"


def compute_source_period_bounds(time_series) -> "tuple[Optional[str], Optional[str]]":
    """Bornes (`period_start`, `period_end`) du dataset SOURCE COMPLET, en ISO-8601 UTC explicite
    — AVANT tout filtrage `opt_start_date`/`opt_end_date`/`max_rows` (ces filtres appartiennent au
    Track R, jamais à l'identité du dataset source — voir EPICS_AND_TICKETS.md, AF-DATA-04A).

    Fuseau : UTC, explicite (`+00:00`) — même convention déjà établie par
    `engine.py::_add_market_time_columns()` (`df["time"].dt.tz_localize("UTC")`), jamais une
    nouvelle hypothèse de fuseau inventée ici.

    `time_series` : la colonne `time` (naïve, considérée UTC par convention du dépôt) du
    DataFrame source déjà chargé — aucune nouvelle lecture de fichier.

    Retourne `(None, None)` si la série est vide (rien à borner).
    """
    if len(time_series) == 0:
        return None, None
    start = time_series.min().tz_localize("UTC").isoformat()
    end = time_series.max().tz_localize("UTC").isoformat()
    return start, end


class SourceMutatedDuringLoadError(RuntimeError):
    """Le fichier source a changé (taille et/ou mtime) entre le chargement du DataFrame et le
    calcul du `content_hash` — la provenance de ce run ne peut pas être certifiée fiable.

    Volontairement une exception NON capturée par ce module (propagée telle quelle à l'appelant,
    voir `optimizer_process.py`) : contrairement à `compute_source_content_hash()` (best-effort,
    ne lève jamais), une mutation réellement DÉTECTÉE est un signal de provenance faux qui ne doit
    jamais être absorbé silencieusement en `content_hash=None` — voir AF-DATA-04A, "comportement
    si mutation détectée". Ce comportement reste strictement local à ce cas précis, la politique
    d'erreurs générale du reste du module (best-effort) est inchangée.
    """


def capture_source_signature(data_file: str) -> "tuple[int, int]":
    """Signature filesystem légère `(taille, mtime_ns)` du fichier source, via `os.stat()`.

    PAS une signature cryptographique — un contrôle de cohérence minimal pour détecter une
    modification ORDINAIRE du fichier pendant la fenêtre chargement→hachage (AF-DATA-04A), pas
    une preuve d'intégrité opposable à un acteur malveillant capable de falsifier taille et
    horodatage. C'est le threat model réel de ce pipeline CSV local mono-processus.

    Lève `FileNotFoundError`/`OSError` si `data_file` n'est pas accessible — propagée telle
    quelle, cohérent avec `market_data.content_hash.content_hash()`.
    """
    st = os.stat(data_file)
    return (st.st_size, st.st_mtime_ns)


def assert_source_signature_unchanged(data_file: str, signature_before) -> None:
    """Lève `SourceMutatedDuringLoadError` si la signature filesystem actuelle de `data_file`
    diffère de `signature_before` (capturée avant le chargement, voir `capture_source_signature`).

    Ne calcule JAMAIS de second `content_hash` — un seul SHA-256 complet par run reste un
    invariant absolu (HASH ONCE, AF-DATA-02/04A) ; ce contrôle est intentionnellement limité aux
    métadonnées filesystem, jamais un second passage cryptographique sur le contenu.
    """
    signature_after = capture_source_signature(data_file)
    if signature_after != signature_before:
        raise SourceMutatedDuringLoadError(
            f"Le fichier source {data_file!r} a changé pendant le chargement/hachage : "
            f"signature avant={signature_before!r}, après={signature_after!r}. "
            "Provenance non certifiable pour ce run."
        )


def write_data_manifest(
    job_dir: str,
    config_dict: dict,
    meta: dict,
    source_timeframe: Optional[str] = None,
    content_hash: Optional[str] = None,
    snapshot_id: Optional[str] = None,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
) -> None:
    """Écrit data_manifest.json — manifeste reproductible additif (voir
    market_data.backtest_manifest, DOMAIN_MODEL.md §2).

    Best-effort avec les métadonnées aujourd'hui disponibles dans config_dict/meta : ce pipeline
    ne track pas encore explicitement asset/timeframe/snapshot structurés (data_file est un
    chemin CSV brut, pas un couple provider/asset/timeframe). `source_timeframe`, s'il est
    fourni, vient d'une inférence sur les données réellement chargées (voir
    market_data.resample.infer_timeframe_from_series(), appelée par optimizer_process.py) —
    jamais deviné ici. Reste "unknown" si non fourni. `content_hash`, s'il est fourni, vient de
    `compute_source_content_hash()` — calculé une seule fois par optimizer_process.py juste après
    le chargement des données (HASH ONCE, PROPAGATE MANY), jamais recalculé ici. Reste `None` si
    non fourni (chemin legacy, identique au comportement d'avant AF-DATA-02 — voir
    EPICS_AND_TICKETS.md, "compatibilité legacy"). `snapshot_id`, s'il est fourni, vient de
    `build_local_csv_snapshot_id()` (AF-DATA-04A). `period_start`/`period_end`, s'ils sont
    fournis, viennent de `compute_source_period_bounds()` sur le DataFrame source COMPLET, avant
    tout filtrage Track R (AF-DATA-04A). Les trois restent `None` si non fournis (même chemin
    legacy que `content_hash`). Jamais inclus dans archive.zip (voir ARCHIVE_SOURCE_FILES, liste
    explicite non affectée par ce nouveau fichier).

    N'écrase jamais un manifeste existant (immuable — FileExistsError silencieusement ignorée).
    Une erreur d'écriture ne fait jamais échouer la génération des artefacts du job : ce fichier
    est additif, les artefacts déjà écrits plus haut dans finalize_job() (metrics/best_strategies/
    report/logs/archive) restent prioritaires.
    """
    data_file = config_dict.get("data_file", "") or ""
    instrument = os.path.splitext(os.path.basename(data_file))[0] or "unknown"

    try:
        manifest = build_backtest_manifest(
            provider="local_csv",
            instrument=instrument,
            provider_symbol=instrument,
            source_timeframe=source_timeframe or "unknown",
            content_hash=content_hash,
            snapshot_id=snapshot_id,
            period_start=period_start,
            period_end=period_end,
            strategy_version=meta.get("strategy_name", "unknown"),
            repo_dir=os.path.dirname(os.path.abspath(__file__)),
        )
        save_backtest_manifest(os.path.join(job_dir, "data_manifest.json"), manifest)
    except FileExistsError:
        pass  # déjà écrit pour ce job (ex. deuxième appel) — jamais écrasé
    except Exception as exc:  # noqa: BLE001 — additif, ne doit jamais casser le job
        print(f"[job_store] data_manifest.json non généré (non bloquant) : {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# EXPERIMENT / RESEARCHRUN (Track R, AF-R-01 — additif)
# ══════════════════════════════════════════════════════════════════════════════

def write_research_run(
    job_dir: str,
    research_run_id: str,
    experiment_id: Optional[str] = None,
    hypothesis: Optional[str] = None,
    dataset_snapshot_id: Optional[str] = None,
    seed: Optional[int] = None,
) -> None:
    """Écrit `research_run.json` dans `job_dir` + `experiments/<experiment_id>.json` en sibling de
    `job_dir` (voir `research_run.py`) — additif, AF-R-01.

    **Chemin legacy explicite** : si `experiment_id` n'est pas fourni, ne fait RIEN (aucun fichier
    créé) — aucun appelant actuel de `finalize_job()` ne fournit encore `experiment_id`, ce
    comportement laisse donc le pipeline strictement inchangé tant qu'un futur appelant ne décide
    pas explicitement d'utiliser ce schéma (même politique que `content_hash`/`snapshot_id`
    AF-DATA-02/04A).

    `Experiment` est un conteneur durable partagé entre plusieurs `ResearchRun`/job directories —
    il ne peut structurellement pas vivre dans un seul `job_dir` (voir `research_run.py`). Son
    emplacement (`experiments/`, sibling de `job_dir`) est dérivé de `job_dir` lui-même, sans
    lecture de variable d'environnement supplémentaire.

    `dataset_snapshot_id` : réutilise le `snapshot_id` déjà calculé pour ce job (voir
    `write_data_manifest()`) — jamais recalculé ici. **Obligatoire** pour qu'un `ResearchRun` soit
    réellement écrit (voir `research_run.build_research_run()`) : absent/vide, cette fonction ne
    fait rien (best-effort), aucun fichier — ni `research_run.json` ni `experiments/<id>.json` —
    n'apparaît (atomique : voir la construction du `ResearchRun` avant toute écriture ci-dessous).

    Best-effort, comme `write_data_manifest()` : une erreur ne fait jamais échouer la génération
    des artefacts du job.

    **Décision explicite non tranchée ici (lifecycle, revue AF-R-01 2026-08-15)** : ni cette
    fonction ni `finalize_job()` ne consultent `final_status` ("completed"/"stopped"/"error" —
    voir `optimizer_process.py`). Aujourd'hui ce n'est pas un bug actif : aucun appelant réel de
    `finalize_job()` ne fournit encore `experiment_id`, donc `write_research_run()` n'est jamais
    exécutée en pratique. Mais telle quelle, cette implémentation écrirait un `research_run.json`
    même pour un run `error`/`stopped` si `experiment_id` était un jour fourni sans condition sur
    le statut — un `ResearchRun` n'est pas structurellement garanti représenter une exécution
    *réussie*. Aucune state machine n'est ajoutée pour ce ticket (hors scope AF-R-01) ; le futur
    ticket qui câble réellement `experiment_id` dans `optimizer_process.py` doit trancher s'il
    filtre sur `final_status == "completed"` avant d'appeler `finalize_job(experiment_id=...)`.

    **AF-R-02 (2026-08-15)** : `git_sha`/`engine_version` ne sont PAS des paramètres de cette
    fonction — capturés automatiquement à l'intérieur de `build_research_run()` (voir
    `research_run.py`), exactement comme `write_data_manifest()` ci-dessus ne passe pas
    `git_commit` à `build_backtest_manifest()` et laisse sa détection "auto" par défaut. Seul
    `repo_dir` est transmis explicitement (ancrage sur le dépôt réel, même motif que
    `write_data_manifest()`). `seed`, en revanche, ne peut PAS être auto-détecté (donnée propre à
    l'appelant) : transmis tel quel, `None` par défaut — aucun appelant actuel n'en fournit encore,
    chemin legacy inchangé, cohérent avec `experiment_id`/`research_hypothesis` (AF-R-01).
    """
    if not experiment_id:
        return  # chemin legacy : rien à faire tant qu'aucun appelant ne fournit experiment_id

    try:
        # Construit et valide le ResearchRun EN PREMIER (dataset_snapshot_id obligatoire — voir
        # research_run.py) avant d'écrire quoi que ce soit : si l'identité dataset manque, aucun
        # fichier ne doit apparaître, y compris l'Experiment — sinon un Experiment orphelin (zéro
        # ResearchRun valide) resterait sur disque après un appel qui a pourtant échoué.
        research_run = build_research_run(
            research_run_id, experiment_id, dataset_snapshot_id=dataset_snapshot_id,
            seed=seed, repo_dir=os.path.dirname(os.path.abspath(__file__)),
        )

        # os.path.normpath() avant dirname() : un job_dir se terminant par un séparateur (trailing
        # slash/backslash) ferait sinon retourner job_dir lui-même (moins le séparateur) au lieu de
        # son vrai parent — experiments/ se retrouverait NICHÉ dans job_dir au lieu d'en être le
        # sibling attendu. Sécurité de chemin, pas une hypothèse : les job_dir réels proviennent
        # d'un argument externe (sys.argv/BACKTEST_JOB_DIR), pas garantis sans séparateur final.
        experiments_dir = os.path.join(os.path.dirname(os.path.normpath(job_dir)), "experiments")
        # build_experiment() valide experiment_id EN PREMIER (validate_portable_identifier() côté
        # research_run.py — rejette tout caractère hors [A-Za-z0-9_.-], jamais ne le sanitise :
        # une sanitisation permissive aurait pu faire collisionner deux identités distinctes, ex.
        # "exp:a" et "exp*a" vers le même nom de fichier — trouvé en revue globale Track R, MCP
        # Codex). Construire le chemin seulement APRÈS validation, comme pour research_run ci-dessus.
        try:
            experiment = build_experiment(experiment_id, hypothesis=hypothesis)
            experiment_path = os.path.join(experiments_dir, f"{experiment.experiment_id}.json")
            save_experiment(experiment_path, experiment)
        except FileExistsError:
            pass  # déjà créé par un ResearchRun précédent du même Experiment — jamais écrasé

        save_research_run(os.path.join(job_dir, "research_run.json"), research_run)
    except FileExistsError:
        pass  # research_run.json déjà écrit pour ce job — jamais écrasé
    except Exception as exc:  # noqa: BLE001 — additif, ne doit jamais casser le job
        print(f"[job_store] research_run.json non généré (non bloquant) : {exc}")


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
    source_timeframe: Optional[str] = None,
    content_hash: Optional[str] = None,
    snapshot_id: Optional[str] = None,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    experiment_id: Optional[str] = None,
    research_hypothesis: Optional[str] = None,
    research_seed: Optional[int] = None,
) -> None:
    """
    Génère tous les artefacts finaux du job dans job_dir.
    Appelé à la fin d'optimizer_process.py quand job_dir est fourni.

    `source_timeframe` : code inféré depuis les données réelles (voir
    market_data.resample.infer_timeframe_from_series()), transmis à write_data_manifest().

    `content_hash` : identité de contenu (SHA-256) du fichier source, calculée UNE SEULE FOIS par
    optimizer_process.py juste après le chargement des données (voir
    `compute_source_content_hash()`) — simplement propagée ici jusqu'à `write_data_manifest()`,
    jamais recalculée (HASH ONCE, PROPAGATE MANY, AF-DATA-02). Reste `None` si non fourni (chemin
    legacy, identique au comportement d'avant AF-DATA-02).

    `snapshot_id`/`period_start`/`period_end` : AF-DATA-04A, mêmes règles de propagation simple
    (calculés une fois en amont, jamais recalculés ici, `None` par défaut = chemin legacy).

    `experiment_id`/`research_hypothesis`/`research_seed` : Track R, AF-R-01/AF-R-02. Restent
    `None` par défaut — aucun appelant actuel de `finalize_job()` ne les fournit encore, ce chemin
    reste donc strictement inchangé (voir `write_research_run()`). `dataset_snapshot_id` du
    `ResearchRun` réutilise directement `snapshot_id` ci-dessus, jamais recalculé. `git_sha`/
    `engine_version` ne sont PAS des paramètres ici : capturés automatiquement à l'intérieur de
    `write_research_run()`/`build_research_run()` (AF-R-02), pas de donnée à faire remonter depuis
    optimizer_process.py pour ceux-là.
    """
    top_results = [r for r in all_results if r.get("score", 0) > 0]
    top_results.sort(key=lambda r: r["score"], reverse=True)

    write_metrics(job_dir, meta, config_dict, benchmark_ms, df_rows_used)
    write_best_strategies(job_dir, top_results)
    write_report_html(job_dir, meta, config_dict)
    write_logs(job_dir, log_lines)
    write_archive(job_dir)
    write_data_manifest(
        job_dir, config_dict, meta,
        source_timeframe=source_timeframe, content_hash=content_hash,
        snapshot_id=snapshot_id, period_start=period_start, period_end=period_end,
    )
    if experiment_id:
        write_research_run(
            job_dir,
            research_run_id=os.path.basename(os.path.normpath(job_dir)) or "run",
            experiment_id=experiment_id,
            hypothesis=research_hypothesis,
            dataset_snapshot_id=snapshot_id,
            seed=research_seed,
        )


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
