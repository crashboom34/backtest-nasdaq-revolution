"""
optimizer_process.py — Point d'entrée subprocess pour l'optimisation.

Lancé par app.py ou run_job.py via subprocess.Popen() :
    python optimizer_process.py <run_id> <config_file> [job_dir]

- run_id      : identifiant unique du run (= job_id en mode job)
- config_file : chemin vers le fichier .config.json
- job_dir     : (optionnel) répertoire job results/job_xxx/
                Aussi lisible via env BACKTEST_JOB_DIR

Totalement indépendant de Streamlit. Utilise ProcessPoolExecutor
en interne pour paralléliser les backtests.

Écrit dans optimization_history/ (mode classique) ou job_dir/ (mode job) :
  - {run_id}_progress.json / progress.json
  - {run_id}.results.csv   / results.csv
  - {run_id}.tested.json   / tested.json
  - {run_id}.meta.json     / meta.json

En mode job, génère également (via job_store) :
  - metrics.json
  - best_strategies.csv
  - report.html
  - logs.txt
  - archive.zip
"""

import sys
import os
import json
import time
import math
import multiprocessing
from datetime import datetime
from dataclasses import asdict

# Compatibilité Windows : doit être dans le bloc __main__
if __name__ == "__main__":
    multiprocessing.freeze_support()

    # ── Ajout du répertoire courant au path ────────────────────
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    from optimization_store import (
        write_progress, load_tested_hashes, save_tested_hashes,
        append_results_csv, save_meta, save_config, load_config, build_meta,
        check_and_clear_stop_flag, delete_progress, resolve_sibling_job_dir,
    )
    from optimizer import (
        OptimizationConfig, ParamRange, TrainTestConfig,
        ScoreWeights, FilterConfig,
        Optimizer, benchmark_speed, count_combinations,
        effective_combinations_total, estimate_duration, format_duration,
        normalize_max_combinations, resolve_execution_window,
        TRAIN_TEST_SEMANTICS_VERSION, validate_resume_train_test_semantics,
    )
    from report_generator import generate_report
    from engine import load_data_from_source
    from market_data.adapters.single_file_csv import SingleFileCsvMarketDataSource, PLACEHOLDER_ASSET, PLACEHOLDER_TIMEFRAME

    # ════════════════════════════════════════════════════════════
    # COLLECTE DE LOGS
    # ════════════════════════════════════════════════════════════

    log_lines     = []
    _run_started  = datetime.now().isoformat()

    def _log(msg: str) -> None:
        """Affiche sur stdout ET conserve dans log_lines."""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        log_lines.append(line)

    # ════════════════════════════════════════════════════════════
    # LECTURE DES ARGUMENTS
    # ════════════════════════════════════════════════════════════

    if len(sys.argv) < 3:
        print("Usage: python optimizer_process.py <run_id> <config_file> [job_dir]")
        sys.exit(1)

    run_id      = sys.argv[1]
    config_file = sys.argv[2]

    # job_dir : 3ème arg CLI ou variable d'env
    job_dir = None
    if len(sys.argv) >= 4:
        job_dir = sys.argv[3]
    elif os.environ.get("BACKTEST_JOB_DIR"):
        job_dir = os.environ["BACKTEST_JOB_DIR"]

    if job_dir:
        os.makedirs(job_dir, exist_ok=True)

    _log(f"optimizer_process starting — run_id={run_id}, job_dir={job_dir or 'classique'}")

    with open(config_file, "r", encoding="utf-8") as f:
        cfg_dict = json.load(f)

    # ════════════════════════════════════════════════════════════
    # RÉSOLUTION DES CHEMINS RELATIFS → ABSOLUS
    # Les JSON stockent des chemins POSIX relatifs (portables W/Linux).
    # On résout ici pour l'utilisation interne, mais on conserve les
    # chemins relatifs dans cfg_dict pour que save_config() reste portable.
    # ════════════════════════════════════════════════════════════
    from path_resolver import resolve_path, to_relative_path
    _abs_strategy = str(resolve_path(cfg_dict["strategy_module"]))
    _abs_data     = str(resolve_path(cfg_dict["data_file"]))
    # cfg_dict garde les chemins relatifs (pour save_config + re-run portable)
    cfg_dict["strategy_module"] = to_relative_path(_abs_strategy)
    cfg_dict["data_file"]       = to_relative_path(_abs_data)

    # ════════════════════════════════════════════════════════════
    # RECONSTRUCTION DE L'OptimizationConfig
    # ════════════════════════════════════════════════════════════

    param_ranges = [
        ParamRange(**pr) for pr in cfg_dict["param_ranges"]
    ]
    raw_total_combinations = count_combinations([pr for pr in param_ranges if pr.enabled])
    max_combinations = normalize_max_combinations(cfg_dict.get("max_combinations"))
    if cfg_dict.get("quick_validation_mode") and max_combinations is None:
        max_combinations = normalize_max_combinations(cfg_dict.get("total_combinations"))
    effective_total_combinations = effective_combinations_total(
        raw_total_combinations,
        max_combinations,
    )
    cfg_dict["raw_total_combinations"] = raw_total_combinations
    cfg_dict["total_combinations"] = effective_total_combinations
    if max_combinations is not None:
        cfg_dict["max_combinations"] = max_combinations
        cfg_dict["max_combinations_applied"] = effective_total_combinations

    sw_dict = cfg_dict.get("score_weights", {})
    score_weights = ScoreWeights(
        profit_factor=sw_dict.get("profit_factor", 3.0),
        max_drawdown=sw_dict.get("max_drawdown", 3.0),
        total_trades=sw_dict.get("total_trades", 2.0),
        max_consecutive_losses=sw_dict.get("max_consecutive_losses", 2.0),
        pct_gain=sw_dict.get("pct_gain", 2.0),
        win_rate=sw_dict.get("win_rate", 1.0),
        avg_win_loss_ratio=sw_dict.get("avg_win_loss_ratio", 1.5),
        equity_regularity=sw_dict.get("equity_regularity", 1.5),
        recovery_factor=sw_dict.get("recovery_factor", 1.0),
    )

    fi_dict = cfg_dict.get("filters", {})
    filters = FilterConfig(
        min_trades=fi_dict.get("min_trades", 30),
        max_drawdown_pct=fi_dict.get("max_drawdown_pct", 25.0),
        min_profit_factor=fi_dict.get("min_profit_factor", 1.1),
        max_consecutive_losses=fi_dict.get("max_consecutive_losses", 12),
        min_win_rate=fi_dict.get("min_win_rate", 35.0),
    )

    tt_dict = cfg_dict.get("train_test", {})
    train_test = TrainTestConfig(
        enabled=tt_dict.get("enabled", False),
        split_method=tt_dict.get("split_method", "ratio"),
        train_ratio=tt_dict.get("train_ratio", 0.70),
        split_date=tt_dict.get("split_date", None),
        alert_degradation_pct=tt_dict.get("alert_degradation_pct", 30.0),
    )

    config = OptimizationConfig(
        run_id=run_id,
        strategy_module=_abs_strategy,   # chemin absolu pour importlib
        strategy_name=cfg_dict["strategy_name"],
        data_file=_abs_data,             # chemin absolu pour load_data
        base_params=cfg_dict["base_params"],
        param_ranges=param_ranges,
        mode=cfg_dict["mode"],
        score_weights=score_weights,
        filters=filters,
        train_test=train_test,
        global_params=cfg_dict.get("global_params", {}),
        n_workers=cfg_dict.get("n_workers", cfg_dict.get("workers", 1)),
        max_combinations_warning=cfg_dict.get("max_combinations_warning", 100_000),
        max_combinations=max_combinations,
        top_k_save=cfg_dict.get("top_k_save", 100),
        top_k_display=cfg_dict.get("top_k_display", 10),
        resume_run_id=cfg_dict.get("resume_run_id", None),
        opt_start_date=cfg_dict.get("opt_start_date", None),
        opt_end_date=cfg_dict.get("opt_end_date", None),
        max_rows=cfg_dict.get("max_rows", None),
        benchmark_n_sample=cfg_dict.get("benchmark_n_sample", 5),
        quick_validation_mode=cfg_dict.get("quick_validation_mode", False),
    )

    # Correction scientifique du split TRAIN/TEST (2026-09-12) : la sémantique train/test est
    # une propriété LOGICIELLE/reproductible, jamais une option UI — injectée automatiquement,
    # jamais demandée à l'utilisateur (mission §22). `None` quand train/test n'est pas activé
    # (rien à versionner). Persistée AVANT save_config() pour que config_used.json en soit la
    # trace canonique, consommée par validate_resume_train_test_semantics() ci-dessous pour
    # toute FUTURE reprise de CE job.
    cfg_dict["train_test_semantics_version"] = (
        TRAIN_TEST_SEMANTICS_VERSION if train_test.enabled else None
    )

    # Sauvegarder la config (permet relance identique)
    save_config(run_id, cfg_dict, job_dir=job_dir)

    # ════════════════════════════════════════════════════════════
    # CHARGEMENT DES DONNÉES
    # ════════════════════════════════════════════════════════════

    # AF-DATA-04A : signature filesystem (taille+mtime_ns) capturée AVANT le chargement — bracket
    # de contrôle de stabilité, comparée après le hachage ci-dessous. Best-effort (si la capture
    # elle-même échoue, on dégrade silencieusement vers le comportement AF-DATA-02 : pas de
    # vérification de stabilité pour ce run, jamais un nouveau mode de blocage).
    from job_store import capture_source_signature
    try:
        _source_signature_before_load = capture_source_signature(config.data_file)
    except OSError:
        _source_signature_before_load = None

    _log(f"Chargement des données : {_abs_data}")
    # Façade de compatibilité (Data Center Phase 11) : passe par le port MarketDataSource au
    # lieu d'un appel direct à engine.load_data(chemin_brut). SingleFileCsvMarketDataSource
    # enveloppe le même chemin déjà résolu (config.data_file) et produit un résultat strictement
    # identique — vérifié par test contre le vrai nasdaq_3m.csv, voir
    # tests/test_engine_load_data_from_source.py::test_single_file_csv_source_matches_load_data_on_the_real_nasdaq_csv.
    df = load_data_from_source(
        SingleFileCsvMarketDataSource(config.data_file), PLACEHOLDER_ASSET, PLACEHOLDER_TIMEFRAME
    )
    _log(f"DataFrame chargé : {len(df)} lignes")

    # Inférence honnête du timeframe source depuis les données réellement chargées (jamais
    # deviné) — utilisée uniquement pour enrichir data_manifest.json, voir job_store.finalize_job.
    from market_data.resample import infer_timeframe_from_series
    _inferred_source_timeframe = infer_timeframe_from_series(df["time"])

    # HASH ONCE, PROPAGATE MANY (AF-DATA-02) : identité de contenu du fichier source calculée une
    # seule fois ici, juste après un chargement réussi (le fichier est garanti exister à cet
    # instant) — jamais recalculée plus loin. Propagée à finalize_job() -> write_data_manifest()
    # -> build_backtest_manifest(), exactement comme _inferred_source_timeframe ci-dessus.
    # Best-effort (voir job_store.compute_source_content_hash) : ne bloque jamais le job.
    # ATTENTION (AF-DATA-04A) : ce hash certifie les octets du fichier "à cet instant du
    # pipeline" — pas une preuve cryptographique atomique que ces octets sont EXACTEMENT ceux
    # parsés dans `df` ci-dessus (deux lectures disque indépendantes). Le contrôle de stabilité
    # ci-dessous détecte les modifications ordinaires survenues entre les deux, sans verrou ni
    # second hash — voir docstring de compute_source_content_hash() pour la limite exacte.
    from job_store import (
        compute_source_content_hash, assert_source_signature_unchanged,
        build_local_csv_snapshot_id, compute_source_period_bounds,
    )
    _source_content_hash = compute_source_content_hash(config.data_file)

    # AF-DATA-04A : contrôle de stabilité — UN SEUL SHA-256 calculé ci-dessus, jamais un second ;
    # seule une comparaison de métadonnées filesystem (taille+mtime_ns). Si une mutation
    # ORDINAIRE du fichier est détectée pendant la fenêtre chargement->hachage, ce nouveau job ne
    # doit pas écrire un manifeste affirmant une provenance fiable qu'il ne peut pas certifier —
    # erreur explicite et non capturée ici (propagée, comme un échec de chargement des données),
    # plutôt qu'un content_hash=None silencieux qui masquerait le problème. Se produit AVANT la
    # phase de calcul lourd (benchmark/optimisation ci-dessous n'a pas encore commencé).
    if _source_signature_before_load is not None:
        assert_source_signature_unchanged(config.data_file, _source_signature_before_load)

    _source_snapshot_id = build_local_csv_snapshot_id(_source_content_hash)
    # Bornes du dataset SOURCE COMPLET (avant tout filtrage ci-dessous) — Track DATA seulement,
    # jamais la sélection effectivement consommée par un ResearchRun (Track R, hors scope ici).
    _source_period_start, _source_period_end = compute_source_period_bounds(df["time"])

    # ════════════════════════════════════════════════════════════
    # SÉPARATION CONTEXTE / EXÉCUTION (Dette A — Optimizer Integration, 2026-09-12)
    # ════════════════════════════════════════════════════════════
    # `df` (chargé ci-dessus) reste désormais le DataFrame SOURCE complet, jamais réduit
    # physiquement à opt_start_date/opt_end_date/max_rows ici — resolve_execution_window()
    # (optimizer.py) sépare le CONTEXTE (historique amont conservé pour le warmup des
    # indicateurs par engine.py, jamais de barre postérieure à la fin effective) de la sélection
    # d'EXÉCUTION elle-même (bornes identiques, ligne à ligne, au comportement historique de ce
    # bloc). Résolu UNE seule fois ici, réutilisé par benchmark_speed()/Optimizer() ci-dessous
    # (même contrat que le fallback _worker_run_single(), jamais une seconde implémentation).

    execution_window = resolve_execution_window(
        df, config.opt_start_date, config.opt_end_date, config.max_rows,
    )
    _log(
        f"[fenêtre] contexte={len(execution_window.context_df)} lignes, "
        f"exécution={execution_window.exec_row_count} lignes "
        f"(opt_start_date={config.opt_start_date}, opt_end_date={config.opt_end_date}, "
        f"max_rows={config.max_rows})"
    )

    # Nombre de lignes utilisées pour les métriques finales — la sélection d'EXÉCUTION effective,
    # jamais le contexte élargi (voir optimizer.py::ExecutionWindow, Optimizer.df_rows_used).
    df_rows_used = execution_window.exec_row_count

    # ════════════════════════════════════════════════════════════
    # REPRISE DE RUN INTERROMPU (garde de version AVANT tout traitement coûteux)
    # ════════════════════════════════════════════════════════════
    #
    # Placé AVANT le benchmark (correction scientifique du split TRAIN/TEST, 2026-09-12, revue
    # /code-review) : une reprise cross-version vouée au refus ne doit payer aucun coût de calcul
    # (benchmark_speed() lance config.benchmark_n_sample backtests réels) avant d'être rejetée.

    already_tested = set()
    if config.resume_run_id:
        # V1 : run_id == job_id — le job source d'une reprise vit dans un dossier FRÈRE de
        # job_dir (results/{resume_run_id}/), jamais dans job_dir lui-même (celui du run
        # courant). resolve_sibling_job_dir() retourne None en mode classique (job_dir=None),
        # préservant la résolution optimization_history/ existante.
        resume_job_dir = resolve_sibling_job_dir(job_dir, config.resume_run_id)

        # Garde de reprise cross-version (correction scientifique du split TRAIN/TEST,
        # 2026-09-12, mission §19-20) : AVANT toute lecture des hashs déjà testés, refuser
        # explicitement une reprise si le run COURANT active train/test et que le job source n'a
        # pas la MÊME sémantique train/test versionnée (absente = "legacy"). Non capturée par le
        # try/except plus bas (comme assert_source_signature_unchanged ci-dessus) : une
        # incohérence scientifique de cette nature doit interrompre le job immédiatement, jamais
        # être traitée comme une erreur d'exécution ordinaire.
        source_config = load_config(config.resume_run_id, job_dir=resume_job_dir)
        validate_resume_train_test_semantics(
            config.train_test, source_config, config.resume_run_id)

        already_tested = load_tested_hashes(config.resume_run_id, job_dir=resume_job_dir)
        _log(f"Reprise : {len(already_tested)} combinaisons déjà testées")

    # ════════════════════════════════════════════════════════════
    # BENCHMARK DE VITESSE (sauf si reprise)
    # ════════════════════════════════════════════════════════════

    benchmark_ms = cfg_dict.get("benchmark_ms", None)
    if benchmark_ms is None:
        write_progress(run_id, {
            "run_id": run_id,
            "status": "benchmarking",
            "total_combinations": 0,
            "completed": 0,
            "failed": 0,
            "progress_pct": 0.0,
            "best_score": 0.0,
            "best_params": {},
            "best_stats": {},
            "elapsed_seconds": 0.0,
            "eta_seconds": None,
            "workers_used": config.n_workers,
            "benchmark_ms_per_backtest": 0.0,
            "already_tested_count": 0,
            "error_message": None,
            "started_at": _run_started,
            "strategy_name": cfg_dict.get("strategy_name", ""),
            "mode": cfg_dict.get("mode", ""),
        }, job_dir=job_dir)
        _log(f"Benchmark de vitesse (n={config.benchmark_n_sample})...")
        benchmark_ms = benchmark_speed(
            config, df, n_sample=config.benchmark_n_sample, execution_window=execution_window,
        )
        _log(f"Benchmark : {benchmark_ms:.1f} ms/backtest")

    n_total = effective_total_combinations
    if max_combinations is not None and raw_total_combinations != n_total:
        _log(f"Limite max_combinations appliquée : {n_total}/{raw_total_combinations}")
    eta_init = estimate_duration(
        max(0, n_total - len(already_tested)),
        benchmark_ms,
        config.n_workers,
    )
    _log(f"Combinaisons totales : {n_total} | ETA estimé : {format_duration(eta_init)} "
         f"| Workers : {config.n_workers}")

    # ════════════════════════════════════════════════════════════
    # ÉTAT INITIAL
    # ════════════════════════════════════════════════════════════

    t_start = time.perf_counter()
    state = {
        "completed":      0,
        "failed":         0,
        "best_score":     0.0,
        "best_params":    {},
        "best_stats":     {},
        "all_results":    [],
        "csv_fieldnames": None,
    }

    def write_state(status="running"):
        elapsed   = time.perf_counter() - t_start
        completed = state["completed"]
        failed    = state["failed"]
        processed = completed + failed
        remaining = max(0, n_total - processed)
        speed     = processed / elapsed if elapsed > 0 else 0
        eta       = remaining / speed if speed > 0 else None

        write_progress(run_id, {
            "run_id":                    run_id,
            "status":                    status,
            "total_combinations":        n_total,
            "completed":                 completed,
            "failed":                    failed,
            "combinations_done":         processed,
            "combinations_total":        n_total,
            "progress_pct":              round(processed / max(1, n_total) * 100, 1),
            "best_score":                round(state["best_score"], 2),
            "best_params":               state["best_params"],
            "best_stats":                state["best_stats"],
            "elapsed_seconds":           round(elapsed, 1),
            "eta_seconds":               round(eta, 0) if eta else None,
            "workers_used":              config.n_workers,
            "benchmark_ms_per_backtest": round(benchmark_ms, 1),
            "already_tested_count":      len(already_tested),
            "error_message":             None,
            "started_at":                _run_started,
            "strategy_name":             cfg_dict.get("strategy_name", ""),
            "mode":                      cfg_dict.get("mode", ""),
        }, job_dir=job_dir)

    write_state("running")

    # ════════════════════════════════════════════════════════════
    # CALLBACK DE PROGRESSION
    # ════════════════════════════════════════════════════════════

    _last_progress_write = [0.0]
    _last_csv_flush      = [0.0]
    _pending_results     = []

    def progress_cb(done_in_batch, total_in_batch, result):
        if result.get("filtered"):
            state["failed"] += 1
        else:
            state["completed"] += 1

        if result["score"] > state["best_score"]:
            state["best_score"]  = result["score"]
            state["best_params"] = result.get("params", {})
            state["best_stats"]  = {
                k: v for k, v in result.get("stats", {}).items()
                if not isinstance(v, (dict, list))
            }

        state["all_results"].append(result)
        _pending_results.append(result)

        # Écriture progress toutes les 500ms
        now = time.perf_counter()
        if now - _last_progress_write[0] > 0.5:
            write_state("running")
            _last_progress_write[0] = now

        # Flush CSV toutes les 2 secondes (ou tous les 50 résultats)
        if len(_pending_results) >= 50 or now - _last_csv_flush[0] > 2.0:
            append_results_csv(run_id, _pending_results, state["csv_fieldnames"],
                               job_dir=job_dir)
            _pending_results.clear()
            _last_csv_flush[0] = now

        # Sauvegarde hashs testés
        h = None
        try:
            from optimizer import params_hash
            h = params_hash(result.get("params", {}))
        except Exception:
            pass
        if h:
            already_tested.add(h)

    # ════════════════════════════════════════════════════════════
    # EXÉCUTION
    # ════════════════════════════════════════════════════════════

    stop_requested = {"value": False}

    def stop_flag_fn():
        if check_and_clear_stop_flag(run_id, job_dir=job_dir):
            stop_requested["value"] = True
            return True
        return False

    final_status = "completed"
    sensitivity  = {}
    opt          = None  # référencé après le try/except pour la fenêtre TRAIN/TEST résolue

    try:
        _log("Lancement de l'optimisation...")
        opt = Optimizer(config, df, execution_window=execution_window)

        run_results, sensitivity = opt.run(
            progress_cb=progress_cb,
            stop_flag_fn=stop_flag_fn,
            already_tested=already_tested,
        )

        # Flush final des résultats en attente
        if _pending_results:
            append_results_csv(run_id, _pending_results, state["csv_fieldnames"],
                               job_dir=job_dir)
            _pending_results.clear()

        # Sauvegarde des hashs
        save_tested_hashes(run_id, already_tested, job_dir=job_dir)

        # Vérifier si arrêt propre demandé
        if stop_requested["value"] or check_and_clear_stop_flag(run_id, job_dir=job_dir):
            final_status = "stopped"

        _log(f"Optimisation terminée — {state['completed']} testées, "
             f"{state['failed']} filtrées, best_score={state['best_score']:.2f}")

    except Exception as e:
        import traceback
        final_status = "error"
        tb = traceback.format_exc()
        _log(f"ERREUR : {e}\n{tb}")
        write_progress(run_id, {
            "run_id":             run_id,
            "status":             "error",
            "error_message":      str(e),
            "total_combinations": n_total,
            "completed":          state["completed"],
            "failed":             state["failed"],
            "combinations_done":  state["completed"] + state["failed"],
            "combinations_total": n_total,
            "progress_pct":       round(
                (state["completed"] + state["failed"]) / max(1, n_total) * 100, 1
            ),
            "started_at":         _run_started,
        }, job_dir=job_dir)
        # On continue quand même pour sauvegarder les résultats partiels

    # ════════════════════════════════════════════════════════════
    # GÉNÉRATION DU RAPPORT & SAUVEGARDE
    # ════════════════════════════════════════════════════════════

    elapsed     = time.perf_counter() - t_start
    all_results = state["all_results"]

    # Générer le rapport automatique
    try:
        from report_generator import generate_report
        report = generate_report(
            all_results=all_results,
            sensitivity=sensitivity,
            config_dict=cfg_dict,
        )
    except Exception as e:
        _log(f"[report_generator] Erreur : {e}")
        report = {"error": str(e)}

    # Fenêtre TRAIN/TEST réellement résolue (correction scientifique du split, 2026-09-12) —
    # None si train/test désactivé, ou si l'optimisation a échoué avant sa résolution (opt=None
    # ou run() jamais atteint). Convertie en dict simple pour build_meta()/JSON.
    resolved_windows_dict = None
    if opt is not None and opt.resolved_train_test_windows is not None:
        resolved_windows_dict = asdict(opt.resolved_train_test_windows)

    # Construire et sauvegarder le meta
    meta = build_meta(
        run_id=run_id,
        config_dict=cfg_dict,
        all_results=all_results,
        sensitivity=sensitivity,
        status=final_status,
        duration_seconds=elapsed,
        combinations_tested=state["completed"] + state["failed"],
        benchmark_ms=benchmark_ms,
        report=report,
        resolved_train_test_windows=resolved_windows_dict,
    )
    save_meta(run_id, meta, job_dir=job_dir)

    # État final
    write_state(final_status)

    # ════════════════════════════════════════════════════════════
    # FINALISATION JOB (artefacts supplémentaires)
    # ════════════════════════════════════════════════════════════

    if job_dir:
        _log("Génération des artefacts job (metrics, best_strategies, report.html, logs, archive)...")
        try:
            from job_store import finalize_job
            # Ajouter les logs finaux avant d'écrire logs.txt
            _log(f"Run {run_id} — status={final_status}, "
                 f"tested={state['completed']+state['failed']}, "
                 f"best_score={state['best_score']:.1f}, "
                 f"durée={elapsed:.1f}s")
            finalize_job(
                job_dir=job_dir,
                meta=meta,
                config_dict=cfg_dict,
                all_results=all_results,
                benchmark_ms=benchmark_ms,
                df_rows_used=df_rows_used,
                log_lines=log_lines,
                source_timeframe=_inferred_source_timeframe,
                content_hash=_source_content_hash,
                snapshot_id=_source_snapshot_id,
                period_start=_source_period_start,
                period_end=_source_period_end,
            )
            _log("Artefacts job générés avec succès.")
        except Exception as e:
            import traceback
            _log(f"[job_store] Erreur finalisation : {e}\n{traceback.format_exc()}")

    _log(f"[optimizer_process] Run {run_id} terminé — status={final_status}, "
         f"tested={state['completed']+state['failed']}, best_score={state['best_score']:.1f}")
