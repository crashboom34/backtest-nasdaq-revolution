"""
tests/test_job_resume.py — Reprise de job (resume_run_id) dans le pipeline job-directory.

Bug PH0-OCI-01 : optimizer_process.py appelait load_tested_hashes(config.resume_run_id) sans
job_dir, donc en mode job (results/job_xxx/) la reprise cherchait toujours dans l'ancien
emplacement classique optimization_history/{run_id}.tested.json — jamais dans
results/{resume_run_id}/tested.json, même quand ce dernier existe réellement.

Ces tests utilisent des données synthétiques minimales (jamais nasdaq_3m.csv) et un
BACKTEST_BASE_DIR isolé (tmp_path) — aucun vrai results/ n'est touché.
"""

import json
import os
import subprocess
import sys
import importlib

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import optimization_store as store
import job_launcher as jl


def _synth_ohlcv_csv(path, n_days=3):
    """Petit échantillon OHLCV synthétique (M3), suffisant pour dépasser WARMUP=130."""
    rng = np.random.default_rng(123)
    rows = []
    price = 20000.0
    start = pd.Timestamp("2026-01-05 00:00:00")  # lundi
    day = 0
    added = 0
    while added < n_days:
        d = start + pd.Timedelta(days=day)
        day += 1
        if d.weekday() >= 5:
            continue
        added += 1
        for m in range(0, 24 * 60, 3):
            ts = d + pd.Timedelta(minutes=m)
            price = max(100.0, price + rng.normal(0, 3.0))
            o = price
            h = o + abs(rng.normal(0, 4))
            l = o - abs(rng.normal(0, 4))
            c = o + rng.normal(0, 2)
            v = int(abs(rng.normal(500, 100)))
            rows.append((ts, o, h, l, c, v))
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df.to_csv(path, index=False)
    return path


def _minimal_config(data_file, run_id, resume_run_id=None):
    strat_spec = importlib.util.spec_from_file_location(
        "prv1_resume_test", os.path.join(REPO_ROOT, "strategies", "perfect_revolution_v1.py")
    )
    strat_mod = importlib.util.module_from_spec(strat_spec)
    strat_spec.loader.exec_module(strat_mod)

    cfg = {
        "run_id": run_id,
        "strategy_module": os.path.join(REPO_ROOT, "strategies", "perfect_revolution_v1.py"),
        "strategy_name": strat_mod.STRATEGY_NAME,
        "data_file": str(data_file),
        "base_params": strat_mod.DEFAULT_PARAMS,
        "param_ranges": [
            {"name": "stop_pct", "param_type": "number", "label": "Stop %",
             "min_val": 0.8, "max_val": 1.2, "step": 0.4, "options": None, "enabled": True},
        ],
        "mode": "grid",
        "score_weights": {
            "profit_factor": 3.0, "max_drawdown": 3.0, "total_trades": 2.0,
            "max_consecutive_losses": 2.0, "pct_gain": 2.0, "win_rate": 1.0,
            "avg_win_loss_ratio": 1.5, "equity_regularity": 1.5, "recovery_factor": 1.0,
        },
        "filters": {
            "min_trades": 0, "max_drawdown_pct": 100.0, "min_profit_factor": 0.0,
            "max_consecutive_losses": 100, "min_win_rate": 0.0,
        },
        "train_test": {"enabled": False, "split_method": "ratio", "train_ratio": 0.7,
                        "split_date": None, "alert_degradation_pct": 30.0},
        "global_params": {"initial_capital": 10000.0, "spread": 1.0, "slip_in": 0.5, "slip_out": 0.5},
        "n_workers": 1,
        "top_k_save": 5,
        "top_k_display": 5,
        "total_combinations": 2,
        "max_rows": None,
        "benchmark_n_sample": 1,
        "quick_validation_mode": True,
    }
    if resume_run_id:
        cfg["resume_run_id"] = resume_run_id
    return cfg


def _run_job_sync(config, timeout=120):
    job_id, job_dir, config_path, cfg = jl.prepare_job_config(config)
    cmd = jl.build_optimizer_command(job_id, config_path, job_dir)
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    assert proc.returncode == 0, f"optimizer_process a échoué:\n{proc.stdout}\n{proc.stderr}"
    return job_id, job_dir


@pytest.fixture
def isolated_job_base(tmp_path, monkeypatch):
    """Isole BACKTEST_BASE_DIR sur un répertoire temporaire — jamais le vrai results/."""
    monkeypatch.setenv("BACKTEST_BASE_DIR", str(tmp_path))
    monkeypatch.delenv("BACKTEST_EODHD_API_KEY", raising=False)
    monkeypatch.delenv("BACKTEST_IG_API_KEY", raising=False)
    monkeypatch.delenv("BACKTEST_IG_PASSWORD", raising=False)
    importlib.reload(store)
    importlib.reload(jl)
    return tmp_path


class TestJobResumeEndToEnd:
    """Reproduction du bug réel via le vrai optimizer_process.py (subprocess)."""

    def test_resume_finds_combinations_already_tested_by_a_prior_job(self, isolated_job_base, tmp_path):
        data_file = _synth_ohlcv_csv(tmp_path / "synth.csv")

        cfg_a = _minimal_config(data_file, run_id="resume_src")
        job_id_a, job_dir_a = _run_job_sync(cfg_a)

        tested_a_path = store._path(job_id_a, ".tested.json", job_dir_a)
        with open(tested_a_path, encoding="utf-8") as f:
            tested_a = json.load(f)
        assert len(tested_a) == 2, "job source attendu avec 2 combinaisons testées"

        cfg_b = _minimal_config(data_file, run_id="resume_dst", resume_run_id=job_id_a)
        job_id_b, job_dir_b = _run_job_sync(cfg_b)

        meta_b = json.loads(open(store._path(job_id_b, ".meta.json", job_dir_b), encoding="utf-8").read())
        with open(os.path.join(job_dir_b, "logs.txt"), encoding="utf-8", errors="replace") as f:
            logs_b = f.read()

        # Comportement attendu : le job repris reconnaît les 2 combinaisons du job source dès le
        # chargement (log émis avant tout traitement, cf. optimizer_process.py:281) — lecture du
        # log plutôt que de progress.json final, dont already_tested_count est un accumulateur
        # cumulatif (déjà-testé + nouvellement-testé) et ne distingue pas les deux à la fin d'un run.
        assert "Reprise : 2 combinaisons déjà testées" in logs_b, (
            f"la reprise devrait retrouver les 2 combinaisons déjà testées par le job source — logs:\n{logs_b}"
        )
        # ...et ne les recalcule donc pas (aucune nouvelle combinaison exécutée).
        assert meta_b["combinations_tested"] == 0, (
            "les combinaisons déjà testées ne doivent pas être recalculées "
            f"(recalculées : {meta_b['combinations_tested']})"
        )

    def test_normal_run_without_resume_is_unaffected(self, isolated_job_base, tmp_path):
        """Le fonctionnement actuel hors reprise (resume_run_id absent) reste inchangé."""
        data_file = _synth_ohlcv_csv(tmp_path / "synth.csv")
        cfg = _minimal_config(data_file, run_id="no_resume_job")
        job_id, job_dir = _run_job_sync(cfg)

        meta = json.loads(open(store._path(job_id, ".meta.json", job_dir), encoding="utf-8").read())
        with open(os.path.join(job_dir, "logs.txt"), encoding="utf-8", errors="replace") as f:
            logs = f.read()

        assert "Reprise :" not in logs, "aucune reprise ne devrait être tentée sans resume_run_id"
        assert meta["combinations_tested"] == 2


class TestResumeJobDirResolution:
    """Tests unitaires rapides (sans subprocess) sur la résolution du job_dir de reprise."""

    def test_resolve_sibling_job_dir_none_in_classic_mode(self, isolated_job_base):
        assert store.resolve_sibling_job_dir(None, "some_run_id") is None

    def test_resolve_sibling_job_dir_points_to_sibling_in_job_mode(self, isolated_job_base, tmp_path):
        current_job_dir = store.get_job_dir("job_current")
        resolved = store.resolve_sibling_job_dir(current_job_dir, "job_source")
        expected = os.path.join(os.path.dirname(current_job_dir), "job_source")
        assert resolved == expected

    def test_resolve_sibling_job_dir_does_not_create_directory(self, isolated_job_base, tmp_path):
        current_job_dir = store.get_job_dir("job_current2")
        resolved = store.resolve_sibling_job_dir(current_job_dir, "job_never_created")
        assert not os.path.exists(resolved), "resolve_sibling_job_dir ne doit créer aucun répertoire"

    def test_load_tested_hashes_via_resolved_sibling_dir_finds_real_hashes(self, isolated_job_base):
        source_dir = store.get_job_dir("job_source_real")
        store.save_tested_hashes("job_source_real", {"h1", "h2", "h3"}, job_dir=source_dir)

        current_dir = store.get_job_dir("job_current_real")
        resolved = store.resolve_sibling_job_dir(current_dir, "job_source_real")
        loaded = store.load_tested_hashes("job_source_real", job_dir=resolved)

        assert loaded == {"h1", "h2", "h3"}

    def test_resume_run_id_nonexistent_returns_empty_set(self, isolated_job_base):
        current_dir = store.get_job_dir("job_current3")
        resolved = store.resolve_sibling_job_dir(current_dir, "job_that_never_existed")
        loaded = store.load_tested_hashes("job_that_never_existed", job_dir=resolved)
        assert loaded == set()

    def test_job_without_previous_results_returns_empty_set(self, isolated_job_base):
        """Le job source existe (config_used.json écrit) mais n'a jamais produit tested.json."""
        source_dir = store.get_job_dir("job_source_no_tested")
        store.save_config("job_source_no_tested", {"run_id": "job_source_no_tested"}, job_dir=source_dir)

        current_dir = store.get_job_dir("job_current4")
        resolved = store.resolve_sibling_job_dir(current_dir, "job_source_no_tested")
        loaded = store.load_tested_hashes("job_source_no_tested", job_dir=resolved)
        assert loaded == set()

    def test_partial_results_returns_only_what_was_saved(self, isolated_job_base):
        """Résultats partiels : le job source a été interrompu après 1 combinaison sur N."""
        source_dir = store.get_job_dir("job_source_partial")
        store.save_tested_hashes("job_source_partial", {"only_one_hash"}, job_dir=source_dir)

        current_dir = store.get_job_dir("job_current5")
        resolved = store.resolve_sibling_job_dir(current_dir, "job_source_partial")
        loaded = store.load_tested_hashes("job_source_partial", job_dir=resolved)
        assert loaded == {"only_one_hash"}

    def test_no_collision_between_two_job_directories(self, isolated_job_base):
        """Deux jobs différents gardent des tested.json indépendants — pas de fuite croisée."""
        dir_a = store.get_job_dir("job_alpha")
        dir_b = store.get_job_dir("job_beta")
        store.save_tested_hashes("job_alpha", {"alpha1", "alpha2"}, job_dir=dir_a)
        store.save_tested_hashes("job_beta", {"beta1"}, job_dir=dir_b)

        loaded_a = store.load_tested_hashes("job_alpha", job_dir=dir_a)
        loaded_b = store.load_tested_hashes("job_beta", job_dir=dir_b)

        assert loaded_a == {"alpha1", "alpha2"}
        assert loaded_b == {"beta1"}
        assert loaded_a.isdisjoint(loaded_b)

    def test_classic_mode_resume_still_works_unchanged(self, isolated_job_base):
        """Mode classique (job_dir=None des deux côtés) — comportement historique préservé."""
        store.save_tested_hashes("classic_resume_src", {"c1", "c2"})
        resolved = store.resolve_sibling_job_dir(None, "classic_resume_src")
        assert resolved is None
        loaded = store.load_tested_hashes("classic_resume_src", job_dir=resolved)
        assert loaded == {"c1", "c2"}


class TestTrainTestResumeCrossVersionGuard:
    """C14 end-to-end (correction scientifique du split TRAIN/TEST, 2026-09-12) — reprise réelle
    (subprocess optimizer_process.py) : refus explicite si le job source n'a pas la MÊME
    sémantique train/test versionnée que le run courant (absente = "legacy"), jamais un mélange
    silencieux de scores calculés sous deux contrats TRAIN/TEST différents."""

    def _run_job_allow_failure(self, config, timeout=120):
        job_id, job_dir, config_path, cfg = jl.prepare_job_config(config)
        cmd = jl.build_optimizer_command(job_id, config_path, job_dir)
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return job_id, job_dir, proc

    def test_resume_with_train_test_and_legacy_source_config_is_refused(
        self, isolated_job_base, tmp_path,
    ):
        data_file = _synth_ohlcv_csv(tmp_path / "synth.csv", n_days=5)

        # Job source SANS train/test : jamais de train_test_semantics_version persistée
        # ("legacy" au sens de cette dette).
        cfg_a = _minimal_config(data_file, run_id="resume_src_legacy")
        job_id_a, job_dir_a = _run_job_sync(cfg_a)

        # Reprise AVEC train/test activé sur le run courant -> doit être refusée (mission §20 :
        # "cas source historique : champ absent -> LEGACY -> refus si train/test actif côté
        # reprise").
        cfg_b = _minimal_config(data_file, run_id="resume_dst_tt", resume_run_id=job_id_a)
        cfg_b["train_test"] = {
            "enabled": True, "split_method": "ratio", "train_ratio": 0.6,
            "split_date": None, "alert_degradation_pct": 30.0,
        }
        job_id_b, job_dir_b, proc = self._run_job_allow_failure(cfg_b)

        assert proc.returncode != 0, (
            f"la reprise train/test cross-version aurait dû échouer explicitement:\n{proc.stdout}\n{proc.stderr}"
        )
        combined = (proc.stdout + proc.stderr).lower()
        assert "train_test" in combined or "semantics" in combined, (
            f"le message d'erreur devrait nommer le problème de sémantique train/test:\n{combined}"
        )

    def test_resume_with_train_test_and_matching_version_source_is_allowed(
        self, isolated_job_base, tmp_path,
    ):
        data_file = _synth_ohlcv_csv(tmp_path / "synth.csv", n_days=5)

        cfg_a = _minimal_config(data_file, run_id="resume_src_tt")
        cfg_a["train_test"] = {
            "enabled": True, "split_method": "ratio", "train_ratio": 0.6,
            "split_date": None, "alert_degradation_pct": 30.0,
        }
        job_id_a, job_dir_a = _run_job_sync(cfg_a)

        config_used_a = json.loads(
            open(store._path(job_id_a, ".config.json", job_dir_a), encoding="utf-8").read())
        assert config_used_a.get("train_test_semantics_version"), (
            "config_used.json du job source doit persister train_test_semantics_version quand "
            "train/test est activé"
        )

        cfg_b = _minimal_config(data_file, run_id="resume_dst_tt2", resume_run_id=job_id_a)
        cfg_b["train_test"] = dict(cfg_a["train_test"])
        job_id_b, job_dir_b, proc = self._run_job_allow_failure(cfg_b)

        assert proc.returncode == 0, f"reprise même-version attendue OK:\n{proc.stdout}\n{proc.stderr}"

    def test_resume_without_train_test_on_the_resumed_run_is_never_blocked_by_this_guard(
        self, isolated_job_base, tmp_path,
    ):
        """Reprise SANS train/test sur le run courant : jamais bloquée par cette garde, même si
        la source n'a jamais eu de sémantique train/test versionnée."""
        data_file = _synth_ohlcv_csv(tmp_path / "synth.csv", n_days=3)
        cfg_a = _minimal_config(data_file, run_id="resume_src_plain")
        job_id_a, job_dir_a = _run_job_sync(cfg_a)

        cfg_b = _minimal_config(data_file, run_id="resume_dst_plain", resume_run_id=job_id_a)
        job_id_b, job_dir_b, proc = self._run_job_allow_failure(cfg_b)

        assert proc.returncode == 0, (
            f"reprise sans train/test ne doit jamais être bloquée:\n{proc.stdout}\n{proc.stderr}"
        )


class TestStateReadinessResumeCrossVersionGuard:
    """SR-T18/T19/T20 (State/Session Readiness V1, 2026-09-14) — garde de reprise DÉDIÉE à la
    readiness, INDÉPENDANTE de `TrainTestSemanticsMismatch`. Perfect Revolution est
    readiness-aware par construction (state_readiness() réel) : tout job train/test récent
    persiste automatiquement `state_readiness_semantics_version` — simulée absente ici pour
    représenter un job "legacy" antérieur à cette mission."""

    def _run_job_allow_failure(self, config, timeout=120):
        job_id, job_dir, config_path, cfg = jl.prepare_job_config(config)
        cmd = jl.build_optimizer_command(job_id, config_path, job_dir)
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return job_id, job_dir, proc

    def test_sr_t19_resume_refused_when_source_lacks_readiness_version(
        self, isolated_job_base, tmp_path,
    ):
        data_file = _synth_ohlcv_csv(tmp_path / "synth.csv", n_days=5)
        cfg_a = _minimal_config(data_file, run_id="resume_src_readiness_legacy")
        cfg_a["train_test"] = {
            "enabled": True, "split_method": "ratio", "train_ratio": 0.6,
            "split_date": None, "alert_degradation_pct": 30.0,
        }
        job_id_a, job_dir_a = _run_job_sync(cfg_a)

        # Simule un job "legacy" (antérieur à cette mission) : train_test_semantics_version
        # déjà présente (Dette TRAIN/TEST exact déjà DONE à l'époque), mais jamais de
        # state_readiness_semantics_version (mission pas encore implémentée).
        config_path = store._path(job_id_a, ".config.json", job_dir_a)
        source_cfg = json.loads(open(config_path, encoding="utf-8").read())
        assert source_cfg.get("train_test_semantics_version"), "précondition : train_test versionné"
        source_cfg.pop("state_readiness_semantics_version", None)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(source_cfg, f)

        cfg_b = _minimal_config(data_file, run_id="resume_dst_readiness", resume_run_id=job_id_a)
        cfg_b["train_test"] = dict(cfg_a["train_test"])
        job_id_b, job_dir_b, proc = self._run_job_allow_failure(cfg_b)

        assert proc.returncode != 0, (
            f"la reprise readiness cross-version aurait dû échouer explicitement:\n{proc.stdout}\n{proc.stderr}"
        )
        combined = (proc.stdout + proc.stderr).lower()
        assert "readiness" in combined or "semantics" in combined, (
            f"le message d'erreur devrait nommer le problème de sémantique readiness:\n{combined}"
        )

    def test_sr_t18_resume_with_matching_readiness_version_is_allowed(
        self, isolated_job_base, tmp_path,
    ):
        data_file = _synth_ohlcv_csv(tmp_path / "synth.csv", n_days=5)
        cfg_a = _minimal_config(data_file, run_id="resume_src_readiness_ok")
        cfg_a["train_test"] = {
            "enabled": True, "split_method": "ratio", "train_ratio": 0.6,
            "split_date": None, "alert_degradation_pct": 30.0,
        }
        job_id_a, job_dir_a = _run_job_sync(cfg_a)

        config_used_a = json.loads(
            open(store._path(job_id_a, ".config.json", job_dir_a), encoding="utf-8").read())
        assert config_used_a.get("state_readiness_semantics_version"), (
            "config_used.json du job source doit persister state_readiness_semantics_version "
            "pour une stratégie readiness-aware avec train/test activé"
        )

        cfg_b = _minimal_config(data_file, run_id="resume_dst_readiness_ok", resume_run_id=job_id_a)
        cfg_b["train_test"] = dict(cfg_a["train_test"])
        job_id_b, job_dir_b, proc = self._run_job_allow_failure(cfg_b)

        assert proc.returncode == 0, f"reprise même-version readiness attendue OK:\n{proc.stdout}\n{proc.stderr}"
