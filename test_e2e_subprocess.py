"""
test_e2e_subprocess.py — Test E2E contrôlé du pipeline subprocess.

Paramètres du test :
  - run_id        : e2e_quick_001
  - max_rows      : 50 000 lignes (~5% des données)
  - benchmark_n   : 1 échantillon
  - combos        : stop_pct [0.8,1.2,1.6] × target_pct [5.0,7.0,9.0,11.0] = 12 combos
  - n_workers     : 1
  - train/test    : désactivé
  - quick_mode    : True

Usage : python test_e2e_subprocess.py
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
STRAT_FILE  = os.path.join(BASE_DIR, "strategies", "perfect_revolution_v1.py")
DATA_FILE   = os.path.join(BASE_DIR, "nasdaq_3m.csv")

RUN_ID      = "e2e_quick_001"
MAX_TIMEOUT = 600  # 10 minutes max

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
            "min_val": 0.8, "max_val": 1.6, "step": 0.4,
            "options": None, "enabled": True,
        },
        {
            "name": "target_pct", "param_type": "number", "label": "Target %",
            "min_val": 5.0, "max_val": 11.0, "step": 2.0,
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
    "n_workers":            1,
    "top_k_save":           20,
    "top_k_display":        10,
    "total_combinations":   12,
    # Nouveaux champs F1-F3
    "max_rows":             50_000,
    "opt_start_date":       None,
    "opt_end_date":         None,
    "benchmark_n_sample":   1,
    "quick_validation_mode": True,
}

# ── Nettoyage des fichiers du run précédent ────────────────────────────────────

def cleanup_run(run_id):
    for f in os.listdir(OPT_DIR):
        if f.startswith(run_id):
            os.remove(os.path.join(OPT_DIR, f))

os.makedirs(OPT_DIR, exist_ok=True)
cleanup_run(RUN_ID)
print(f"[setup] Run {RUN_ID} nettoyé")

# ── Sauvegarde config ──────────────────────────────────────────────────────────

config_file = os.path.join(OPT_DIR, f"{RUN_ID}.config.json")
with open(config_file, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
print(f"[setup] Config sauvegardée : {config_file}")
print(f"[setup] Combos attendus   : stop_pct [0.8,1.2,1.6] x target_pct [5.0,7.0,9.0,11.0] = 12")
print(f"[setup] max_rows          : {config['max_rows']:,}")
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
        return f"EXISTE ({size} octets)"
    return "absent"

last_status  = ""
last_combos  = 0
output_lines = []

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
            total   = prog.get("total_combinations", 0)
            score   = prog.get("best_score", 0)
            bms     = prog.get("benchmark_ms_per_backtest", 0)

            if status != last_status or done != last_combos:
                print(f"  [{elapsed:5.1f}s] status={status} | "
                      f"{done}/{total} combos | score={score:.1f} | "
                      f"bench={bms:.0f}ms")
                last_status = status
                last_combos = done
        except Exception as e:
            print(f"  [progress] Lecture erreur: {e}")

    # Vérifier si le process est terminé
    ret = proc.poll()
    if ret is not None:
        print(f"\n[subprocess] Terminé en {elapsed:.1f}s — code retour={ret}")
        # Lire le reste du stdout
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

    time.sleep(2.0)

# ── Rapport final ──────────────────────────────────────────────────────────────

elapsed_total = time.perf_counter() - t_start
print("\n" + "="*65)
print("RAPPORT FINAL — TEST E2E SUBPROCESS")
print("="*65)
print(f"\nDurée totale du test : {elapsed_total:.1f}s")

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
print("\n— PROGRESSION —")
if os.path.exists(progress_file):
    with open(progress_file, "r", encoding="utf-8") as f:
        prog = json.load(f)
    for k in ["status", "completed", "failed", "total_combinations",
              "best_score", "progress_pct", "elapsed_seconds",
              "benchmark_ms_per_backtest", "workers_used"]:
        print(f"  {k:30s} : {prog.get(k, '—')}")
else:
    print("  progress_file absent")

# Contenu meta
print("\n— META —")
if os.path.exists(meta_file):
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    print(f"  status             : {meta.get('status', '—')}")
    print(f"  combinations_tested: {meta.get('combinations_tested', '—')}")
    print(f"  best_score         : {meta.get('best_score', '—')}")
    print(f"  duration_seconds   : {meta.get('duration_seconds', '—'):.1f}s")
    # Top résultats
    top = meta.get("report", {}).get("top_results", [])
    if top:
        print(f"\n  — TOP {len(top)} RÉSULTATS —")
        for i, r in enumerate(top[:10], 1):
            score = r.get("score", 0)
            params = r.get("params", {})
            stop   = params.get("stop_pct", "?")
            tgt    = params.get("target_pct", "?")
            print(f"  #{i:2d}  score={score:.1f}  stop={stop}  target={tgt}")
    else:
        print("  Aucun résultat dans le rapport")
else:
    print("  meta_file absent")

# CSV
print("\n— CSV RÉSULTATS —")
if os.path.exists(csv_file):
    with open(csv_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    print(f"  {len(lines)-1} ligne(s) de résultats (+ header)")
    if len(lines) > 1:
        print(f"  Colonnes : {lines[0].strip()[:120]}")
else:
    print("  CSV absent")

# Verdict
print("\n— VERDICT —")
checks = {
    "Subprocess terminé proprement"    : proc.returncode == 0,
    "_progress.json créé"              : os.path.exists(progress_file),
    ".results.csv créé"                : os.path.exists(csv_file),
    ".meta.json créé"                  : os.path.exists(meta_file),
    ".tested.json créé"                : os.path.exists(tested_file),
    "Durée raisonnable (< 5min)"       : elapsed_total < 300,
}
if os.path.exists(progress_file):
    with open(progress_file, "r", encoding="utf-8") as f:
        prog = json.load(f)
    checks["Status=completed"] = prog.get("status") == "completed"
    checks["Combos testés > 0"]   = prog.get("completed", 0) > 0

all_ok = all(checks.values())
for label, ok in checks.items():
    print(f"  {'OK' if ok else 'ECHEC':6s}  {label}")

print(f"\n{'SUCCES - Pipeline validé' if all_ok else 'ECHECS DETECTES - voir ci-dessus'}")
print("="*65)
