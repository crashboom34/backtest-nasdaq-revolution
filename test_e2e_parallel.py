"""
test_e2e_parallel.py — Test intermédiaire : 42 combos, 2 workers, période réduite.

Paramètres du test :
  - run_id          : e2e_parallel_001
  - opt_start_date  : 2022-01-01
  - max_rows        : 100 000 lignes
  - benchmark_n     : 1 échantillon
  - combos          : stop_pct [0.8..1.8 step 0.2] × target_pct [4.0..10.0 step 1.0]
                      = 6 × 7 = 42 combos
  - n_workers       : 2
  - train/test      : désactivé

Objectifs :
  1. ProcessPoolExecutor fonctionne avec 2 workers sous Windows
  2. Pas de conflits d'écriture (CSV, progress JSON)
  3. progress JSON cohérent (completed monte jusqu'à 42)
  4. CSV créé avec le bon nombre de lignes
  5. Top100 cohérent (tri par score)
  6. Rapport automatique correct
  7. Durée réaliste (~2-3 min avec la réduction de période)

Usage : python test_e2e_parallel.py
"""

import json
import os
import sys
import subprocess
import time

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
OPT_DIR     = os.path.join(BASE_DIR, "optimization_history")
PYTHON      = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
SCRIPT      = os.path.join(BASE_DIR, "optimizer_process.py")

# ── Chemins relatifs (validé portabilité Windows → Linux) ─────────────────────
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from path_resolver import to_relative_path
STRAT_FILE  = to_relative_path(os.path.join(BASE_DIR, "strategies", "perfect_revolution_v1.py"))
DATA_FILE   = to_relative_path(os.path.join(BASE_DIR, "nasdaq_3m.csv"))
print(f"[setup] strategy_module  : {STRAT_FILE!r}  (doit être relatif POSIX)")
print(f"[setup] data_file        : {DATA_FILE!r}  (doit être relatif POSIX)")

RUN_ID      = "e2e_parallel_001"
MAX_TIMEOUT = 900  # 15 minutes max

# ── Config du test ─────────────────────────────────────────────────────────────

config = {
    "run_id":          RUN_ID,
    "strategy_module": STRAT_FILE,
    "strategy_name":   "NASDAQ Perfect Revolution V1.1",
    "data_file":       DATA_FILE,
    "base_params": {
        "use_compounding": False, "base_contracts": 1,
        "capital_per_contract": 8000, "max_contracts": 5,
        "allow_short": False,
        "trade_monday": True, "trade_tuesday": True, "trade_wednesday": True,
        "trade_thursday": False, "trade_friday": True,
        "or_start_h": 15, "or_start_m": 30, "or_end_h": 16, "or_end_m": 0,
        "t_start_h": 16, "t_start_m": 0, "t_end_h": 21, "t_end_m": 15,
        "t_flat_h": 22, "t_flat_m": 15,
        "max_trades_per_day": 2, "max_daily_loss_pct": 2.0,
        "ema_trend_len": 120, "ema_filter_len": 20, "atr_len": 14,
        "min_atr": 20.0, "min_or_pts": 60.0, "max_or_pts": 400.0,
        "break_buffer": 5.0,
        "stop_pct": 1.2, "target_pct": 6.75,
        "use_trailing": True, "trail_start_pct": 2.6, "trail_pts": 650.0,
        "max_bars_in_trade": 40,
    },
    "param_ranges": [
        {
            "name": "stop_pct", "param_type": "number", "label": "Stop %",
            "min_val": 0.8, "max_val": 1.8, "step": 0.2,
            "options": None, "enabled": True,
        },
        {
            "name": "target_pct", "param_type": "number", "label": "Target %",
            "min_val": 4.0, "max_val": 10.0, "step": 1.0,
            "options": None, "enabled": True,
        },
    ],
    "mode": "grid",
    "score_weights": {
        "profit_factor": 3.0, "max_drawdown": 3.0, "total_trades": 2.0,
        "max_consecutive_losses": 2.0, "pct_gain": 2.0, "win_rate": 1.0,
        "avg_win_loss_ratio": 1.5, "equity_regularity": 1.5, "recovery_factor": 1.0,
    },
    "filters": {
        "min_trades": 5, "max_drawdown_pct": 60.0, "min_profit_factor": 0.5,
        "max_consecutive_losses": 20, "min_win_rate": 10.0,
    },
    "train_test": {
        "enabled": False, "split_method": "ratio", "train_ratio": 0.7,
        "split_date": None, "alert_degradation_pct": 30.0,
    },
    "global_params": {
        "initial_capital": 10000.0, "spread": 1.0, "slip_in": 0.5, "slip_out": 0.5,
    },
    "n_workers":            2,
    "top_k_save":           100,
    "top_k_display":        10,
    "total_combinations":   42,
    # F1-F3 fields
    "max_rows":              100_000,
    "opt_start_date":        "2022-01-01",
    "opt_end_date":          None,
    "benchmark_n_sample":    1,
    "quick_validation_mode": False,
}

# ── Nettoyage des fichiers du run précédent ────────────────────────────────────

os.makedirs(OPT_DIR, exist_ok=True)
for f in os.listdir(OPT_DIR):
    if f.startswith(RUN_ID):
        os.remove(os.path.join(OPT_DIR, f))
print(f"[setup] Run {RUN_ID} nettoyé")

# ── Sauvegarde config ──────────────────────────────────────────────────────────

config_file = os.path.join(OPT_DIR, f"{RUN_ID}.config.json")
with open(config_file, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print(f"[setup] Config sauvegardée : {config_file}")
print(f"[setup] Combos attendus   : stop_pct [0.8..1.8 step 0.2] x target_pct [4..10 step 1] = 42")
print(f"[setup] opt_start_date    : {config['opt_start_date']}")
print(f"[setup] max_rows          : {config['max_rows']:,}")
print(f"[setup] n_workers         : {config['n_workers']}")
print(f"[setup] benchmark_n       : {config['benchmark_n_sample']}")
print()

# ── Lancement subprocess ───────────────────────────────────────────────────────

print(f"[subprocess] Lancement : python optimizer_process.py {RUN_ID} ...")
t_start = time.perf_counter()

proc = subprocess.Popen(
    [PYTHON, SCRIPT, RUN_ID, config_file],
    cwd=BASE_DIR,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    errors="replace",
)
print(f"[subprocess] PID={proc.pid}")
print()

# ── Monitoring ─────────────────────────────────────────────────────────────────

progress_file = os.path.join(OPT_DIR, f"{RUN_ID}_progress.json")
csv_file      = os.path.join(OPT_DIR, f"{RUN_ID}.results.csv")
meta_file     = os.path.join(OPT_DIR, f"{RUN_ID}.meta.json")
tested_file   = os.path.join(OPT_DIR, f"{RUN_ID}.tested.json")

def file_status(path):
    if os.path.exists(path):
        size = os.path.getsize(path)
        return f"EXISTE ({size:,} octets)"
    return "absent"

last_status  = ""
last_combos  = -1
output_lines = []

# Pour suivre la régularité du compteur de combos (détecte conflits d'écriture)
combo_history = []

while True:
    elapsed = time.perf_counter() - t_start

    # Lire les lignes stdout disponibles
    while True:
        try:
            line = proc.stdout.readline()
            if not line:
                break
            line = line.rstrip()
            if line:
                output_lines.append(line)
                print(f"  [stdout] {line}")
        except Exception:
            break

    # Lire le progress JSON
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                prog = json.load(f)
            status  = prog.get("status", "?")
            done    = prog.get("completed", 0)
            failed  = prog.get("failed", 0)
            total   = prog.get("total_combinations", 0)
            score   = prog.get("best_score", 0)
            bms     = prog.get("benchmark_ms_per_backtest", 0)
            workers = prog.get("workers_used", 1)

            if status != last_status or done != last_combos:
                print(f"  [{elapsed:5.1f}s] status={status} | "
                      f"done={done} filtered={failed} total={total} | "
                      f"score={score:.1f} | bench={bms:.0f}ms | workers={workers}")
                last_status = status
                last_combos = done
                combo_history.append((elapsed, done, failed))
        except json.JSONDecodeError:
            pass  # Écriture atomique en cours, skip
        except Exception as e:
            print(f"  [progress] Erreur: {e}")

    # Vérifier si le process est terminé
    ret = proc.poll()
    if ret is not None:
        print(f"\n[subprocess] Terminé en {elapsed:.1f}s — code retour={ret}")
        rest = proc.stdout.read()
        if rest:
            for line in rest.strip().split("\n"):
                if line.strip():
                    output_lines.append(line.strip())
                    print(f"  [stdout] {line.strip()}")
        break

    if elapsed > MAX_TIMEOUT:
        print(f"\n[TIMEOUT] {MAX_TIMEOUT}s dépassé — arrêt forcé")
        proc.terminate()
        proc.wait()
        break

    time.sleep(1.5)

# ── Rapport final ──────────────────────────────────────────────────────────────

elapsed_total = time.perf_counter() - t_start
print("\n" + "="*70)
print("RAPPORT FINAL — TEST INTERMÉDIAIRE 42 COMBOS / 2 WORKERS")
print("="*70)
print(f"\nDurée totale : {elapsed_total:.1f}s ({elapsed_total/60:.1f} min)")

# Fichiers créés
print("\n— FICHIERS CRÉÉS —")
for label, path in [
    ("_progress.json", progress_file),
    (".results.csv",   csv_file),
    (".meta.json",     meta_file),
    (".tested.json",   tested_file),
    (".config.json",   config_file),
]:
    print(f"  {label:25s} : {file_status(path)}")

# Contenu progress
print("\n— PROGRESSION FINALE —")
if os.path.exists(progress_file):
    with open(progress_file, "r", encoding="utf-8") as f:
        prog = json.load(f)
    for k in ["status", "completed", "failed", "total_combinations",
              "best_score", "progress_pct", "elapsed_seconds",
              "benchmark_ms_per_backtest", "workers_used"]:
        print(f"  {k:30s} : {prog.get(k, '—')}")
else:
    print("  progress_file absent")

# Historique des combos — vérifie la régularité (pas de sauts bizarres)
print("\n— HISTORIQUE PROGRESSION (combos) —")
if combo_history:
    for i, (t, done, filt) in enumerate(combo_history):
        delta = done - combo_history[i-1][1] if i > 0 else done
        print(f"  t={t:5.1f}s  done={done:3d}  filtered={filt:3d}  delta=+{delta}")
else:
    print("  (aucun snapshot capturé)")

# Contenu meta
print("\n— META —")
if os.path.exists(meta_file):
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    print(f"  status               : {meta.get('status', '—')}")
    print(f"  combinations_tested  : {meta.get('combinations_tested', '—')}")
    print(f"  duration_seconds     : {meta.get('duration_seconds', 0):.1f}s")
    print(f"  benchmark_ms         : {meta.get('benchmark_ms', '—')}")

    # Top résultats
    top = meta.get("top_100", [])
    if top:
        print(f"\n  — TOP {min(len(top), 10)} RÉSULTATS (sur {len(top)} valides) —")
        prev_score = None
        order_ok   = True
        for i, r in enumerate(top[:10], 1):
            score  = r.get("score", 0)
            params = r.get("params", {})
            stats  = r.get("stats", {})
            stop   = params.get("stop_pct", "?")
            tgt    = params.get("target_pct", "?")
            n      = stats.get("n_trades", stats.get("total_trades", "?"))
            dd     = stats.get("max_dd_pct", "?")
            pf     = stats.get("profit_factor", "?")
            gain   = stats.get("net_ret_pct", "?")
            print(f"  #{i:2d}  score={score:5.1f}  stop={stop}  tgt={tgt}  "
                  f"trades={n}  dd={dd:.1f}%  pf={pf:.2f}  gain={gain:.1f}%")
            if prev_score is not None and score > prev_score:
                order_ok = False
            prev_score = score
        print(f"\n  Tri par score décroissant : {'OK' if order_ok else 'ERREUR — tri incorrect!'}")
    else:
        print("  Aucun résultat dans top_100")

    # Rapport automatique
    report = meta.get("report", {})
    if report and "categorie" in report:
        print(f"\n  — RAPPORT AUTOMATIQUE —")
        print(f"  categorie              : {report.get('categorie', '—')}")
        print(f"  resume                 : {report.get('resume', '—')[:120]}")
        print(f"  risque_overfitting     : {report.get('risque_overfitting', '—')}")
        print(f"  convient_paper_trading : {report.get('convient_paper_trading', '—')}")
        print(f"  recommandation_finale  : {report.get('recommandation_finale', '—')[:120]}")
    elif "error" in report:
        print(f"  ERREUR rapport : {report['error']}")
else:
    print("  meta_file absent")

# CSV
print("\n— CSV RÉSULTATS —")
if os.path.exists(csv_file):
    with open(csv_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    n_data = len(lines) - 1
    print(f"  {n_data} ligne(s) de résultats (+ header)")
    if len(lines) > 1:
        print(f"  Header : {lines[0].strip()[:100]}")
    # Vérification cohérence avec progress
    if os.path.exists(progress_file):
        with open(progress_file, "r", encoding="utf-8") as f:
            prog = json.load(f)
        total_prog = prog.get("completed", 0) + prog.get("failed", 0)
        csv_match = (n_data == total_prog)
        print(f"  CSV lignes ({n_data}) == progress tested ({total_prog}) : "
              f"{'OK' if csv_match else 'DIVERGENCE!'}")
else:
    print("  CSV absent")

# Analyse temps par backtest
print("\n— PERFORMANCE —")
if os.path.exists(meta_file):
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    dur      = meta.get("duration_seconds", elapsed_total)
    tested   = meta.get("combinations_tested", 0)
    bm_ms    = meta.get("benchmark_ms", 0)
    n_valid  = len(meta.get("top_100", []))
    n_filter = tested - n_valid if tested > n_valid else 0

    if tested > 0:
        avg_s  = dur / tested
        speed  = tested / dur if dur > 0 else 0
        print(f"  Temps total           : {dur:.1f}s")
        print(f"  Combos testés         : {tested}")
        print(f"  Moyenne par backtest  : {avg_s:.1f}s ({avg_s*1000:.0f}ms)")
        print(f"  Débit effectif        : {speed:.2f} bt/s")
        print(f"  Benchmark mesuré      : {bm_ms:.0f}ms")
        print(f"  Résultats filtrés     : {n_filter}/{tested}")
        print(f"  Résultats valides     : {n_valid}/{tested}")
        print()
        # Estimation pleine échelle
        full_rows = 900_000  # ~9x100k
        est_full  = avg_s * 9 * 42 / 60
        print(f"  Estimation 42 combos sur full dataset : ~{est_full:.0f} min")
        est_500   = avg_s * 500 / 2 / 60  # 2 workers
        print(f"  Estimation 500 combos (2 workers, 100k rows) : ~{est_500:.0f} min")

# VERDICT FINAL
print("\n— VERDICT —")
checks = {}
checks["Subprocess terminé proprement"]    = proc.returncode == 0
checks["_progress.json créé"]              = os.path.exists(progress_file)
checks[".results.csv créé"]               = os.path.exists(csv_file)
checks[".meta.json créé"]                 = os.path.exists(meta_file)
checks[".tested.json créé"]               = os.path.exists(tested_file)
checks["Durée < 10 min"]                  = elapsed_total < 600

if os.path.exists(progress_file):
    with open(progress_file, "r", encoding="utf-8") as f:
        prog = json.load(f)
    checks["Status=completed"]            = prog.get("status") == "completed"
    checks["workers_used=2"]              = prog.get("workers_used", 0) == 2
    total_tested = prog.get("completed", 0) + prog.get("failed", 0)
    checks["Tous les combos testés (42)"] = total_tested == 42

if os.path.exists(meta_file):
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    top = meta.get("top_100", [])
    checks["Top100 non vide"]             = len(top) > 0
    report = meta.get("report", {})
    checks["Rapport sans erreur"]         = "error" not in report and "categorie" in report

if os.path.exists(csv_file) and os.path.exists(progress_file):
    with open(csv_file, "r", encoding="utf-8") as f:
        n_csv = len(f.readlines()) - 1
    with open(progress_file, "r", encoding="utf-8") as f:
        prog = json.load(f)
    n_prog = prog.get("completed", 0) + prog.get("failed", 0)
    checks["CSV cohérent avec progress"]  = n_csv == n_prog

all_ok = all(checks.values())
for label, ok in checks.items():
    print(f"  {'OK  ' if ok else 'FAIL':6s}  {label}")

print()
if all_ok:
    print("SUCCES - Test intermédiaire 2 workers validé")
else:
    n_fail = sum(1 for v in checks.values() if not v)
    print(f"ECHECS ({n_fail} point(s)) — voir ci-dessus")
print("="*70)
