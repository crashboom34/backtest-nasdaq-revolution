"""
optimization_store.py — Persistance des runs d'optimisation.

Supporte deux modes :
  - Mode classique  : optimization_history/{run_id}{suffix}
  - Mode job        : results/job_xxx/{filename}  (job_dir fourni)

Structure classique (backward compat) :
  {run_id}.meta.json      Métadonnées + top 100 + rapport
  {run_id}.results.csv    Tous les résultats
  {run_id}.config.json    Config complète
  {run_id}.tested.json    Set des hashs testés (pour reprise)
  {run_id}_progress.json  État temps réel (temporaire)
  {run_id}_stop.flag      Signal d'arrêt (temporaire)

Structure job (nouvelle) :
  results/job_YYYYMMDD_HHMMSS_xxxx/
    progress.json       ← état temps réel enrichi
    results.csv
    config_used.json
    tested.json
    meta.json
    stop.flag
    metrics.json        ← KPI summary (job_store)
    best_strategies.csv ← top 100 (job_store)
    report.html         ← rapport standalone (job_store)
    logs.txt            ← logs run (job_store)
    archive.zip         ← 7 fichiers bundlés (job_store)
"""

import json
import os
import csv
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Union


ACTIVE_JOB_STATUSES = {"benchmarking", "running"}
CREATED_JOB_ACTIVE_SECONDS = 5 * 60
TERMINAL_JOB_STATUSES = {"completed", "error", "failed", "stopped"}


# ══════════════════════════════════════════════════════════════════════════════
# BASE DIRS
# ══════════════════════════════════════════════════════════════════════════════

def _base_dir() -> str:
    """Répertoire racine du projet (via BACKTEST_BASE_DIR ou répertoire du script)."""
    env = os.environ.get("BACKTEST_BASE_DIR", "")
    if env:
        return str(Path(env).resolve())
    return os.path.dirname(os.path.abspath(__file__))


def _history_dir() -> str:
    """optimization_history/ — mode classique."""
    d = os.path.join(_base_dir(), "optimization_history")
    os.makedirs(d, exist_ok=True)
    return d


def _results_dir() -> str:
    """results/ — racine du mode job."""
    d = os.path.join(_base_dir(), "results")
    os.makedirs(d, exist_ok=True)
    return d


# ══════════════════════════════════════════════════════════════════════════════
# JOB ID & JOB DIR
# ══════════════════════════════════════════════════════════════════════════════

def make_job_id() -> str:
    """Génère un ID de job unique : job_YYYYMMDD_HHMMSS_xxxx."""
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid  = uuid.uuid4().hex[:4]
    return f"job_{ts}_{uid}"


def get_job_dir(job_id: str) -> str:
    """Crée et retourne le répertoire du job results/job_xxx/."""
    d = os.path.join(_results_dir(), job_id)
    os.makedirs(d, exist_ok=True)
    return d


# ══════════════════════════════════════════════════════════════════════════════
# RÉSOLUTION DE CHEMIN (unifié classique / job)
# ══════════════════════════════════════════════════════════════════════════════

# Mapping suffix classique → nom de fichier dans job_dir
_JOB_SUFFIX_MAP = {
    "_progress.json": "progress.json",
    ".results.csv":   "results.csv",
    ".config.json":   "config_used.json",
    ".tested.json":   "tested.json",
    ".meta.json":     "meta.json",
    "_stop.flag":     "stop.flag",
}


def _path(run_id: str, suffix: str, job_dir: Optional[str] = None) -> str:
    """
    Retourne le chemin complet d'un fichier de run.

    - job_dir=None  → mode classique : optimization_history/{run_id}{suffix}
    - job_dir=str   → mode job       : job_dir/{filename}
    """
    if job_dir is not None:
        filename = _JOB_SUFFIX_MAP.get(suffix, f"{run_id}{suffix}")
        return os.path.join(job_dir, filename)
    return os.path.join(_history_dir(), f"{run_id}{suffix}")


# ══════════════════════════════════════════════════════════════════════════════
# ÉCRITURE ATOMIQUE
# ══════════════════════════════════════════════════════════════════════════════

def atomic_write_json(path: str, data: dict) -> None:
    """
    Écriture atomique d'un fichier JSON.
    Streamlit ne lira jamais un fichier à moitié écrit.
    """
    dir_path = os.path.dirname(path)
    os.makedirs(dir_path, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=dir_path, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=_json_default)
        tmp_path = f.name

    delays = (0.05, 0.10, 0.20, 0.40, 0.80)
    last_error = None
    for attempt in range(len(delays) + 1):
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError as exc:
            last_error = exc
        except OSError as exc:
            if getattr(exc, "winerror", None) != 5:
                raise
            last_error = exc

        if attempt < len(delays):
            time.sleep(delays[attempt])

    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except OSError:
        pass

    raise PermissionError(
        f"Impossible de remplacer {path} après {len(delays) + 1} tentatives."
    ) from last_error


def _json_default(obj):
    """Sérialiser les types non standards (numpy, etc.)."""
    import math
    if hasattr(obj, "item"):      # numpy scalars
        return obj.item()
    if isinstance(obj, float) and math.isinf(obj):
        return "Inf"
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ══════════════════════════════════════════════════════════════════════════════
# PROGRESSION (fichier temporaire lu par Streamlit)
# ══════════════════════════════════════════════════════════════════════════════

def _enrich_progress_for_job(state: dict, job_dir: str) -> dict:
    """
    Enrichit un dict de progression avec les champs job + backward compat.

    Règle : tous les anciens champs sont CONSERVÉS, les nouveaux ajoutés.
    Streamlit continue de lire les anciens champs sans modification.
    """
    enriched = dict(state)

    # Backward compat : dupliquer sous les anciens noms si absents
    if "combinations_done" not in enriched:
        enriched["combinations_done"] = (
            (enriched.get("completed", 0) or 0)
            + (enriched.get("failed", 0) or 0)
        )
    if "combinations_total" not in enriched:
        enriched["combinations_total"] = enriched.get("total_combinations", 0)

    # Champs nouveaux spécifiques au mode job
    enriched["job_dir"] = job_dir
    enriched["job_id"]  = os.path.basename(job_dir)

    return enriched


def write_progress(run_id: str, state: dict, job_dir: Optional[str] = None) -> None:
    """Écrit l'état de progression en mode atomique."""
    state_with_update = dict(state)
    state_with_update.setdefault("updated_at", datetime.now().isoformat())
    data = _enrich_progress_for_job(state_with_update, job_dir) if job_dir else state_with_update
    atomic_write_json(_path(run_id, "_progress.json", job_dir), data)


def read_progress(run_id: str, job_dir: Optional[str] = None) -> Optional[dict]:
    """Lit l'état de progression. Retourne None si le fichier n'existe pas."""
    path = _path(run_id, "_progress.json", job_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def delete_progress(run_id: str, job_dir: Optional[str] = None) -> None:
    path = _path(run_id, "_progress.json", job_dir)
    if os.path.exists(path):
        os.remove(path)


# ══════════════════════════════════════════════════════════════════════════════
# FLAG D'ARRÊT
# ══════════════════════════════════════════════════════════════════════════════

def write_stop_flag(run_id: str, job_dir: Optional[str] = None) -> None:
    """Demande l'arrêt propre d'un run en cours."""
    path = _path(run_id, "_stop.flag", job_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("stop")


def check_and_clear_stop_flag(run_id: str, job_dir: Optional[str] = None) -> bool:
    """Retourne True si le flag existe, puis le supprime."""
    path = _path(run_id, "_stop.flag", job_dir)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# RÉSULTATS CSV (append progressif)
# ══════════════════════════════════════════════════════════════════════════════

def append_results_csv(
    run_id: str,
    results: list,
    fieldnames: list = None,
    job_dir: Optional[str] = None,
) -> None:
    """
    Ajoute des résultats au fichier CSV de manière progressive.
    Crée le fichier avec les en-têtes si nécessaire.
    """
    if not results:
        return

    path        = _path(run_id, ".results.csv", job_dir)
    file_exists = os.path.exists(path)

    # Construire les noms de colonnes
    sample = results[0]
    if fieldnames is None:
        param_keys = sorted(sample.get("params", {}).keys())
        stat_keys  = sorted(sample.get("stats",  {}).keys())
        meta_keys  = ["score", "filtered", "filter_reason", "warnings",
                      "score_train", "score_test", "degradation_pct"]
        fieldnames = meta_keys + ["param_" + k for k in param_keys] + ["stat_" + k for k in stat_keys]

    with open(path, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()

        for r in results:
            row = {}
            for k in ["score", "filtered", "filter_reason", "score_train",
                       "score_test", "degradation_pct"]:
                row[k] = r.get(k, "")
            row["warnings"] = "; ".join(r.get("warnings", []))
            for k, v in r.get("params", {}).items():
                row["param_" + k] = v
            for k, v in r.get("stats", {}).items():
                if not isinstance(v, (dict, list)):
                    row["stat_" + k] = v
            writer.writerow(row)


def load_results_csv(run_id: str, job_dir: Optional[str] = None):
    """Charge tous les résultats depuis le CSV. Retourne un DataFrame."""
    import pandas as pd
    path = _path(run_id, ".results.csv", job_dir)
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)


# ══════════════════════════════════════════════════════════════════════════════
# HASHS TESTÉS (pour reprise de run interrompu)
# ══════════════════════════════════════════════════════════════════════════════

def load_tested_hashes(run_id: str, job_dir: Optional[str] = None) -> set:
    path = _path(run_id, ".tested.json", job_dir)
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_tested_hashes(
    run_id: str,
    hashes: set,
    job_dir: Optional[str] = None,
) -> None:
    atomic_write_json(_path(run_id, ".tested.json", job_dir), list(hashes))


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION (pour relance identique)
# ══════════════════════════════════════════════════════════════════════════════

def save_config(
    run_id: str,
    config_dict: dict,
    job_dir: Optional[str] = None,
) -> None:
    atomic_write_json(_path(run_id, ".config.json", job_dir), config_dict)


def load_config(run_id: str, job_dir: Optional[str] = None) -> Optional[dict]:
    path = _path(run_id, ".config.json", job_dir)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════════════════
# META (résultat final du run)
# ══════════════════════════════════════════════════════════════════════════════

def save_meta(
    run_id: str,
    meta: dict,
    job_dir: Optional[str] = None,
) -> None:
    atomic_write_json(_path(run_id, ".meta.json", job_dir), meta)


def load_meta(run_id: str, job_dir: Optional[str] = None) -> Optional[dict]:
    path = _path(run_id, ".meta.json", job_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — MODE CLASSIQUE
# ══════════════════════════════════════════════════════════════════════════════

def list_runs() -> list:
    """
    Liste tous les runs terminés (ou en cours) dans optimization_history/.
    Retourne une liste de dicts triée par date décroissante.
    """
    d    = _history_dir()
    runs = []

    for filename in os.listdir(d):
        if not filename.endswith(".meta.json"):
            continue
        run_id = filename[:-len(".meta.json")]
        meta   = load_meta(run_id)
        if meta is None:
            continue

        # Enrichir avec l'état temps réel si en cours
        progress = read_progress(run_id)
        if progress and progress.get("status") == "running":
            meta["status"]       = "running"
            meta["progress_pct"] = progress.get("progress_pct", 0)

        runs.append({
            "run_id":              run_id,
            "date":                meta.get("date", ""),
            "strategy_name":       meta.get("strategy_name", ""),
            "mode":                meta.get("mode", ""),
            "status":              meta.get("status", "completed"),
            "total_combinations":  meta.get("total_combinations", 0),
            "combinations_tested": meta.get("combinations_tested", 0),
            "duration_seconds":    meta.get("duration_seconds", 0),
            "best_score":          meta["top_100"][0]["score"] if meta.get("top_100") else 0,
            "workers_used":        meta.get("workers_used", 1),
            "variables_tested":    meta.get("variables_tested", []),
            "progress_pct":        meta.get("progress_pct", 100),
        })

    runs.sort(key=lambda r: r["date"], reverse=True)
    return runs


def load_run(run_id: str) -> Optional[dict]:
    """Charge le run complet (meta + CSV disponible séparément)."""
    return load_meta(run_id)


def delete_run(run_id: str, job_dir: Optional[str] = None) -> None:
    """Supprime tous les fichiers d'un run."""
    suffixes = [
        ".meta.json", ".results.csv", ".config.json",
        ".tested.json", "_progress.json", "_stop.flag",
    ]
    for suffix in suffixes:
        path = _path(run_id, suffix, job_dir)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


def get_run_status(run_id: str, job_dir: Optional[str] = None) -> str:
    """Retourne le statut d'un run depuis progress.json ou meta.json."""
    progress = read_progress(run_id, job_dir)
    if progress:
        return progress.get("status", "unknown")
    meta = load_meta(run_id, job_dir)
    if meta:
        return meta.get("status", "completed")
    return "not_found"


def cleanup_old_progress_files(max_age_hours: int = 24) -> int:
    """
    Supprime les fichiers _progress.json plus vieux que max_age_hours.
    Retourne le nombre de fichiers supprimés.
    """
    d      = _history_dir()
    cutoff = time.time() - max_age_hours * 3600
    count  = 0

    for filename in os.listdir(d):
        if not filename.endswith("_progress.json"):
            continue
        path = os.path.join(d, filename)
        if os.path.getmtime(path) < cutoff:
            try:
                os.remove(path)
                count += 1
            except Exception:
                pass

    return count


# ══════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — MODE JOB
# ══════════════════════════════════════════════════════════════════════════════

def list_jobs() -> list:
    """
    Liste tous les jobs dans results/.
    Retourne une liste de dicts triée par date décroissante.
    """
    results_root = _results_dir()
    jobs = []

    for dirname in os.listdir(results_root):
        if not dirname.startswith("job_"):
            continue
        job_dir  = os.path.join(results_root, dirname)
        job_id   = dirname
        run_id   = job_id  # V1: run_id == job_id

        meta = load_meta(run_id, job_dir)
        if meta is None:
            # Job en cours, juste créé, ou vide — essayer progress/config.
            prog = read_progress(run_id, job_dir)
            if prog:
                processed = prog.get("combinations_done")
                if processed is None:
                    processed = (prog.get("completed", 0) or 0) + (prog.get("failed", 0) or 0)
                jobs.append({
                    "job_id":              job_id,
                    "job_dir":             job_dir,
                    "date":                prog.get("started_at", ""),
                    "strategy_name":       prog.get("strategy_name", ""),
                    "mode":                prog.get("mode", ""),
                    "status":              prog.get("status", "running"),
                    "total_combinations":  prog.get("total_combinations", 0),
                    "combinations_tested": processed,
                    "duration_seconds":    prog.get("elapsed_seconds", 0),
                    "best_score":          prog.get("best_score", 0),
                    "workers_used":        prog.get("workers_used", 1),
                    "progress_pct":        prog.get("progress_pct", 0),
                })
                continue

            cfg = load_config(run_id, job_dir)
            if cfg:
                cfg_path = _path(run_id, ".config.json", job_dir)
                try:
                    date = datetime.fromtimestamp(os.path.getmtime(cfg_path)).isoformat()
                except Exception:
                    date = ""
                jobs.append({
                    "job_id":              job_id,
                    "job_dir":             job_dir,
                    "date":                date,
                    "strategy_name":       cfg.get("strategy_name", ""),
                    "mode":                cfg.get("mode", ""),
                    "status":              "created",
                    "total_combinations":  cfg.get("total_combinations", 0),
                    "combinations_tested": 0,
                    "duration_seconds":    0,
                    "best_score":          0,
                    "workers_used":        cfg.get("n_workers", 1),
                    "variables_tested": [
                        pr.get("name", "")
                        for pr in cfg.get("param_ranges", [])
                        if pr.get("enabled")
                    ],
                    "progress_pct":        0,
                })
            continue

        # Enrichir avec progression temps réel si en cours
        progress = read_progress(run_id, job_dir)
        if progress and progress.get("status") in ("running", "benchmarking"):
            meta["status"]       = progress["status"]
            meta["progress_pct"] = progress.get("progress_pct", 0)

        jobs.append({
            "job_id":              job_id,
            "job_dir":             job_dir,
            "date":                meta.get("date", ""),
            "strategy_name":       meta.get("strategy_name", ""),
            "mode":                meta.get("mode", ""),
            "status":              meta.get("status", "completed"),
            "total_combinations":  meta.get("total_combinations", 0),
            "combinations_tested": meta.get("combinations_tested", 0),
            "duration_seconds":    meta.get("duration_seconds", 0),
            "best_score":          meta["top_100"][0]["score"] if meta.get("top_100") else 0,
            "workers_used":        meta.get("workers_used", 1),
            "variables_tested":    meta.get("variables_tested", []),
            "progress_pct":        meta.get("progress_pct", 100),
        })

    jobs.sort(key=lambda j: j["date"], reverse=True)
    return jobs


def _job_timestamp_for_activity(job: dict) -> Optional[float]:
    """Retourne le timestamp disque le plus fiable pour juger un job récent."""
    job_id = job.get("job_id", "")
    job_dir = job.get("job_dir", "")
    if not job_id or not job_dir:
        return None

    for suffix in ("_progress.json", ".config.json"):
        path = _path(job_id, suffix, job_dir)
        if os.path.exists(path):
            try:
                return os.path.getmtime(path)
            except OSError:
                return None
    return None


def is_active_job(job: dict, now_ts: Optional[float] = None) -> bool:
    """Détermine si un job doit être proposé comme réellement actif."""
    job_id = job.get("job_id", "")
    job_dir = job.get("job_dir", "")
    status = job.get("status", "")

    if status in TERMINAL_JOB_STATUSES:
        return False

    if job_id and job_dir and os.path.exists(_path(job_id, "_stop.flag", job_dir)):
        return False

    if status in ACTIVE_JOB_STATUSES:
        return True

    if status == "created":
        ts = _job_timestamp_for_activity(job)
        if ts is None:
            return False
        now = time.time() if now_ts is None else now_ts
        return 0 <= (now - ts) <= CREATED_JOB_ACTIVE_SECONDS

    return False


def list_active_jobs(now_ts: Optional[float] = None) -> list:
    """Liste les jobs encore actifs depuis results/job_xxx/."""
    return [
        job for job in list_jobs()
        if is_active_job(job, now_ts=now_ts)
    ]


def load_job(job_id: str) -> Optional[dict]:
    """Charge les données complètes d'un job."""
    job_dir = os.path.join(_results_dir(), job_id)
    if not os.path.isdir(job_dir):
        return None
    meta = load_meta(job_id, job_dir)
    if meta:
        meta["job_dir"] = job_dir
    return meta


# ══════════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DU META DICT (appelé par optimizer_process à la fin du run)
# ══════════════════════════════════════════════════════════════════════════════

def build_meta(
    run_id: str,
    config_dict: dict,
    all_results: list,
    sensitivity: dict,
    status: str,
    duration_seconds: float,
    combinations_tested: int,
    benchmark_ms: float,
    report: dict = None,
) -> dict:
    """
    Construit le dictionnaire méta complet pour {run_id}.meta.json.
    """
    # Top 100
    valid = [r for r in all_results if r["score"] > 0]
    valid.sort(key=lambda r: r["score"], reverse=True)
    top_100 = []

    for rank, r in enumerate(valid[:100], start=1):
        stats = r.get("stats", {})
        entry = {
            "rank":              rank,
            "score":             round(r["score"], 2),
            "score_train":       round(r.get("score_train", r["score"]), 2),
            "score_test":        round(r.get("score_test",  r["score"]), 2),
            "degradation_pct":   round(r.get("degradation_pct", 0.0), 1),
            "overfitting_alert": r.get("overfitting_alert", False),
            "params":            r.get("params", {}),
            "warnings":          r.get("warnings", []),
            "stats": {
                "profit_factor":    _safe_float(stats.get("profit_factor", 0)),
                "total_trades":     stats.get("n_trades", 0),
                "win_rate":         round(stats.get("win_rate", 0), 2),
                "max_dd_pct":       round(stats.get("max_dd_pct", 0), 2),
                "net_ret_pct":      round(stats.get("net_ret_pct", 0), 2),
                "max_consec_loss":  stats.get("max_consec_loss", 0),
                "payoff":           _safe_float(stats.get("payoff", 0)),
                "equity_r_squared": round(stats.get("equity_r_squared", 0.5), 3),
                "net_ret_usd":      round(stats.get("net_ret_usd", 0), 2),
                "max_dd_usd":       round(stats.get("max_dd_usd", 0), 2),
            },
        }
        top_100.append(entry)

    combinations_filtered = len([r for r in all_results if r.get("filtered")])

    return {
        "run_id":                    run_id,
        "date":                      datetime.now().isoformat(),
        "strategy_name":             config_dict.get("strategy_name", ""),
        "mode":                      config_dict.get("mode", ""),
        "status":                    status,
        "variables_tested":          [pr["name"] for pr in config_dict.get("param_ranges", [])
                                      if pr.get("enabled", True)],
        "total_combinations":        config_dict.get("total_combinations", combinations_tested),
        "combinations_tested":       combinations_tested,
        "combinations_filtered_out": combinations_filtered,
        "duration_seconds":          round(duration_seconds, 1),
        "workers_used":              config_dict.get("n_workers", 1),
        "benchmark_ms_per_backtest": round(benchmark_ms, 1),
        "score_weights":             config_dict.get("score_weights", {}),
        "filters":                   config_dict.get("filters", {}),
        "train_test":                config_dict.get("train_test", {}),
        "top_100":                   top_100,
        "sensitivity":               {k: round(v, 3) for k, v in sensitivity.items()},
        "report":                    report or {},
    }


def _safe_float(v) -> float:
    import math
    if v is None:
        return 0.0
    if isinstance(v, float) and math.isinf(v):
        return 999.0
    try:
        return round(float(v), 3)
    except Exception:
        return 0.0
