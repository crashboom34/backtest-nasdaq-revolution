"""
run_job.py — Lancement d'un job d'optimisation en ligne de commande.

Usage
-----
    python run_job.py --config <fichier.config.json> [options]

Options de surcharge (optionnelles)
------------------------------------
    --workers   <int>   Nombre de workers parallèles
    --max-rows  <int>   Limite de lignes DataFrame
    --run-id    <str>   ID de job personnalisé (sinon job_YYYYMMDD_HHMMSS_xxxx)

Exemples
--------
    # Lancer un job avec la config JSON générée par app.py
    python run_job.py --config optimization_history/my_run.config.json

    # Surcharger workers et max_rows
    python run_job.py --config my_run.config.json --workers 4 --max-rows 50000

    # Sur serveur Linux avec BASE_DIR configuré
    BACKTEST_BASE_DIR=/app python run_job.py --config /app/runs/my_run.config.json

Sorties (dans results/job_xxx/)
--------------------------------
    progress.json         progression temps réel
    config_used.json      config relative (portable)
    results.csv           résultats cumulés
    tested.json           hashs testés (reprise)
    meta.json             résultat interne complet
    metrics.json          KPI synthétiques
    best_strategies.csv   top 100 stratégies
    report.html           rapport standalone
    logs.txt              journal d'exécution
    archive.zip           7 fichiers bundlés

Codes de sortie
---------------
    0  — Succès (completed)
    1  — Erreur fatale (exception ou status=error)
    2  — Arrêté manuellement (status=stopped)
"""

import argparse
import json
import sys
import time
import subprocess
from pathlib import Path

# ── Répertoire du script ──────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_resolver import resolve_path
from job_launcher import launch_optimizer_job


# ── Couleurs terminal (optionnel) ─────────────────────────────────────────────
try:
    from colorama import Fore, Style, init as _cinit
    _cinit(autoreset=True)
    GREEN  = Fore.GREEN
    YELLOW = Fore.YELLOW
    RED    = Fore.RED
    CYAN   = Fore.CYAN
    RESET  = Style.RESET_ALL
except ImportError:
    GREEN = YELLOW = RED = CYAN = RESET = ""


def _fmt_duration(seconds: float) -> str:
    """Formate une durée en secondes en 'Xh Ym Zs'."""
    if seconds is None or seconds < 0:
        return "?"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _read_progress(job_dir: str) -> dict:
    """Lit le fichier de progression JSON depuis job_dir."""
    prog_path = Path(job_dir) / "progress.json"
    try:
        with open(prog_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _print_progress(prog: dict, last_pct: float) -> float:
    """Affiche la progression. Retourne le nouveau last_pct."""
    status  = prog.get("status", "?")
    pct     = prog.get("progress_pct", 0.0)
    done    = prog.get("completed", 0)
    total   = prog.get("total_combinations", 0)
    best    = prog.get("best_score", 0.0)
    elapsed = prog.get("elapsed_seconds", 0.0)
    eta     = prog.get("eta_seconds", None)
    bms     = prog.get("benchmark_ms_per_backtest", 0.0)
    workers = prog.get("workers_used", 1)

    # N'afficher que si progression significative (>=0.5%) ou status change
    if pct - last_pct < 0.5 and status not in ("completed", "error", "stopped", "benchmarking"):
        return last_pct

    color = GREEN if status == "completed" else (RED if status == "error" else CYAN)

    bar_len = 30
    filled  = int(bar_len * pct / 100)
    bar     = "#" * filled + "." * (bar_len - filled)

    eta_str = f"ETA {_fmt_duration(eta)}" if eta else "ETA ?"
    print(
        f"\r{color}[{status:12s}]{RESET} [{bar}] {pct:5.1f}% "
        f"({done}/{total}) | score {best:.1f} | {_fmt_duration(elapsed)} | {eta_str} "
        f"| {bms:.0f}ms/bt | {workers}w",
        end="", flush=True
    )

    if status in ("completed", "error", "stopped"):
        print()  # saut de ligne final

    return pct


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Lance un job d'optimisation sans Streamlit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config", "-c", required=True,
        help="Chemin vers le fichier .config.json (relatif ou absolu)"
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=None,
        help="Nombre de workers parallèles (surcharge n_workers du JSON)"
    )
    parser.add_argument(
        "--max-rows", type=int, default=None,
        help="Limite de lignes DataFrame (surcharge max_rows du JSON)"
    )
    parser.add_argument(
        "--run-id", type=str, default=None,
        help="ID de job personnalisé (sinon job_YYYYMMDD_HHMMSS_xxxx)"
    )
    parser.add_argument(
        "--poll", type=float, default=1.0,
        help="Intervalle de polling de la progression en secondes (defaut: 1.0)"
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    # ── Résolution du fichier config ──────────────────────────────────────────
    config_path = resolve_path(args.config)
    if not config_path.exists():
        print(f"{RED}Fichier config introuvable : {config_path}{RESET}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # ── Surcharges CLI ────────────────────────────────────────────────────────
    if args.workers is not None:
        cfg["n_workers"] = args.workers
        print(f"{YELLOW}  workers surcharge -> {args.workers}{RESET}")

    if args.max_rows is not None:
        cfg["max_rows"] = args.max_rows
        print(f"{YELLOW}  max_rows surcharge -> {args.max_rows}{RESET}")

    # ── Création du job et lancement via le helper partagé ───────────────────
    launched = launch_optimizer_job(
        cfg,
        run_id=args.run_id,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    job_id        = launched.job_id
    job_dir       = launched.job_dir
    config_in_job = launched.config_path
    cfg           = launched.config

    # ── Infos de démarrage ────────────────────────────────────────────────────
    strat  = cfg.get("strategy_name", "?")
    combos = cfg.get("total_combinations", "?")
    mode   = cfg.get("mode", "?")
    n_w    = cfg.get("n_workers", 1)
    m_rows = cfg.get("max_rows", "toutes")

    print(f"\n{GREEN}{'='*60}{RESET}")
    print(f"{GREEN}  Backtest Optimizer — run CLI (mode job){RESET}")
    print(f"{GREEN}{'='*60}{RESET}")
    print(f"  Job ID    : {CYAN}{job_id}{RESET}")
    print(f"  Job dir   : {job_dir}")
    print(f"  Strategie : {strat}")
    print(f"  Mode      : {mode}")
    print(f"  Combos    : {combos}")
    print(f"  Workers   : {n_w}")
    print(f"  Max rows  : {m_rows}")
    print(f"{GREEN}{'='*60}{RESET}\n")

    # ── Subprocess optimizer_process.py ──────────────────────────────────────
    proc = launched.process
    print(f"Lancement : {' '.join(launched.command)}\n")

    # ── Polling de la progression ─────────────────────────────────────────────
    last_pct     = -1.0
    final_status = None

    while proc.poll() is None:
        time.sleep(args.poll)
        prog = _read_progress(job_dir)
        if prog:
            last_pct = _print_progress(prog, last_pct)
            s = prog.get("status", "")
            if s in ("completed", "error", "stopped"):
                final_status = s
                break

    # Lire la sortie du process
    try:
        stdout_remainder, _ = proc.communicate(timeout=10)
        if stdout_remainder:
            for line in stdout_remainder.splitlines():
                # Supprimer les caractères de remplacement Unicode (cp1252 incompatible)
                safe_line = line.replace("�", "?").replace("\x00", "")
                print(f"  {safe_line}")
    except subprocess.TimeoutExpired:
        proc.kill()

    # Lecture finale de la progression si pas encore récupérée
    if final_status is None:
        prog = _read_progress(job_dir)
        if prog:
            _print_progress(prog, last_pct)
            final_status = prog.get("status", "unknown")

    # ── Résumé final ──────────────────────────────────────────────────────────
    meta_path = Path(job_dir) / "meta.json"
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        # best_score : dans progress (plus fiable) ou top_100[0]
        _prog_final = _read_progress(job_dir)
        best_score  = (_prog_final.get("best_score")
                       or (meta.get("top_100") or [{}])[0].get("score", 0)
                       or 0)
        best_params = ((_prog_final.get("best_params"))
                       or (meta.get("top_100") or [{}])[0].get("params", {})
                       or {})
        n_tested    = meta.get("combinations_tested", 0)
        duration    = meta.get("duration_seconds", 0)

        print(f"\n{GREEN}{'-'*60}{RESET}")
        print(f"  Status     : {final_status}")
        print(f"  Testes     : {n_tested} / {combos}")
        print(f"  Duree      : {_fmt_duration(duration)}")
        print(f"  Best score : {best_score:.2f}")
        if best_params:
            print(f"  Best params:")
            for k, v in best_params.items():
                print(f"    {k} = {v}")
        print(f"\n  Fichiers job ({job_id}) :")
        for fname in ["config_used.json", "results.csv", "metrics.json",
                      "best_strategies.csv", "report.html", "logs.txt", "archive.zip"]:
            fp = Path(job_dir) / fname
            size = f"{fp.stat().st_size // 1024}KB" if fp.exists() else "absent"
            mark = "OK" if fp.exists() else "--"
            print(f"    [{mark}] {fname:25s} {size}")
        print(f"  Job dir    : {job_dir}")
        print(f"{GREEN}{'-'*60}{RESET}\n")

    # ── Code de sortie ────────────────────────────────────────────────────────
    rc = proc.returncode or 0
    if final_status == "error" or rc != 0:
        sys.exit(1)
    elif final_status == "stopped":
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
