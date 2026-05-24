"""
tests/test_optimization_store.py — Tests de persistance (Step 6).
Vérifie la création/lecture de tous les fichiers de run.
"""

import sys
import os
import json
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import optimization_store as store


# Utiliser un run_id temporaire pour ne pas polluer optimization_history/
TEST_RUN_ID = "test_audit_run_000"


@pytest.fixture(autouse=True)
def cleanup():
    """Supprime les fichiers du run de test avant ET après chaque test."""
    store.delete_run(TEST_RUN_ID)
    yield
    store.delete_run(TEST_RUN_ID)


class TestAtomicWrite:

    def test_write_and_read_json(self):
        """Écriture atomique puis relecture correcte."""
        data = {"key": "value", "num": 42, "nested": {"a": 1}}
        path = os.path.join(store._history_dir(), f"{TEST_RUN_ID}_test.json")
        store.atomic_write_json(path, data)
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data
        os.remove(path)

    def test_write_inf_float(self):
        """Les float Inf doivent être sérialisés sans erreur."""
        data = {"pf": float("inf"), "val": 42.0}
        path = os.path.join(store._history_dir(), f"{TEST_RUN_ID}_inf.json")
        store.atomic_write_json(path, data)
        assert os.path.exists(path)
        os.remove(path)


class TestProgressFile:

    def test_write_and_read_progress(self):
        state = {"run_id": TEST_RUN_ID, "status": "running", "progress_pct": 42.0}
        store.write_progress(TEST_RUN_ID, state)
        loaded = store.read_progress(TEST_RUN_ID)
        assert loaded is not None
        assert loaded["status"] == "running"
        assert loaded["progress_pct"] == 42.0

    def test_job_progress_counts_failed_as_done(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            job_dir = os.path.join(tmp_dir, TEST_RUN_ID)
            state = {
                "run_id": TEST_RUN_ID,
                "status": "running",
                "completed": 0,
                "failed": 100,
                "total_combinations": 200,
                "progress_pct": 50.0,
            }

            store.write_progress(TEST_RUN_ID, state, job_dir=job_dir)
            loaded = store.read_progress(TEST_RUN_ID, job_dir=job_dir)

            assert loaded is not None
            assert loaded["combinations_done"] == 100
            assert loaded["combinations_total"] == 200
            assert loaded["progress_pct"] == 50.0

    def test_read_nonexistent_returns_none(self):
        result = store.read_progress("nonexistent_run_xyz")
        assert result is None

    def test_delete_progress(self):
        store.write_progress(TEST_RUN_ID, {"status": "running"})
        store.delete_progress(TEST_RUN_ID)
        assert store.read_progress(TEST_RUN_ID) is None


class TestStopFlag:

    def test_write_and_check_stop_flag(self):
        store.write_stop_flag(TEST_RUN_ID)
        assert store.check_and_clear_stop_flag(TEST_RUN_ID) is True

    def test_stop_flag_is_cleared_after_check(self):
        store.write_stop_flag(TEST_RUN_ID)
        store.check_and_clear_stop_flag(TEST_RUN_ID)  # consomme le flag
        assert store.check_and_clear_stop_flag(TEST_RUN_ID) is False

    def test_no_stop_flag_returns_false(self):
        assert store.check_and_clear_stop_flag(TEST_RUN_ID) is False


class TestTestedHashes:

    def test_save_and_load_hashes(self):
        hashes = {"abc123", "def456", "ghi789"}
        store.save_tested_hashes(TEST_RUN_ID, hashes)
        loaded = store.load_tested_hashes(TEST_RUN_ID)
        assert loaded == hashes

    def test_load_nonexistent_returns_empty_set(self):
        result = store.load_tested_hashes("nonexistent_run_xyz")
        assert result == set()


class TestResultsCSV:

    def test_append_and_check_csv_exists(self):
        results = [
            {
                "score":          75.0,
                "filtered":       False,
                "filter_reason":  "",
                "warnings":       ["test warning"],
                "score_train":    75.0,
                "score_test":     70.0,
                "degradation_pct": 6.7,
                "params":  {"stop_loss": 30, "take_profit": 60},
                "stats":   {"n_trades": 80, "profit_factor": 2.0, "max_dd_pct": 10.0},
            }
        ]
        store.append_results_csv(TEST_RUN_ID, results)
        path = store._path(TEST_RUN_ID, ".results.csv")
        assert os.path.exists(path), "CSV non créé"

    def test_load_results_csv_returns_dataframe(self):
        import pandas as pd
        results = [
            {
                "score": 75.0, "filtered": False, "filter_reason": "",
                "warnings": [], "score_train": 75.0, "score_test": 70.0,
                "degradation_pct": 6.7,
                "params": {"stop_loss": 30}, "stats": {"n_trades": 80},
            }
        ]
        store.append_results_csv(TEST_RUN_ID, results)
        df = store.load_results_csv(TEST_RUN_ID)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0


class TestMetaFile:

    def _make_results(self, n=5):
        return [
            {
                "score": 70.0 + i,
                "filtered": False,
                "params": {"stop_loss": 20 + i * 5, "take_profit": 60},
                "stats": {
                    "n_trades": 60 + i,
                    "profit_factor": 1.8,
                    "max_dd_pct": 10.0,
                    "win_rate": 55.0,
                    "net_ret_pct": 50.0,
                    "max_consec_loss": 4,
                    "payoff": 1.5,
                    "equity_r_squared": 0.85,
                    "net_ret_usd": 5000.0,
                    "max_dd_usd": 1000.0,
                },
                "score_train": 70.0 + i,
                "score_test": 68.0 + i,
                "degradation_pct": 2.0,
                "overfitting_alert": False,
                "warnings": [],
            }
            for i in range(n)
        ]

    def test_save_and_load_meta(self):
        results = self._make_results()
        config_dict = {
            "strategy_name": "Test Strategy",
            "mode": "grid",
            "param_ranges": [
                {"name": "stop_loss", "enabled": True}
            ],
            "n_workers": 1,
            "total_combinations": 5,
        }
        meta = store.build_meta(
            run_id=TEST_RUN_ID,
            config_dict=config_dict,
            all_results=results,
            sensitivity={"stop_loss": 0.45},
            status="completed",
            duration_seconds=12.5,
            combinations_tested=5,
            benchmark_ms=50.0,
            report={"categorie": "Réglage recommandé"},
        )
        store.save_meta(TEST_RUN_ID, meta)
        loaded = store.load_meta(TEST_RUN_ID)
        assert loaded is not None
        assert loaded["run_id"] == TEST_RUN_ID
        assert loaded["status"] == "completed"
        assert "top_100" in loaded
        assert len(loaded["top_100"]) == 5
        assert loaded["top_100"][0]["score"] >= loaded["top_100"][-1]["score"]

    def test_meta_top100_sorted_by_score(self):
        results = self._make_results(10)
        config_dict = {"strategy_name": "T", "mode": "grid", "param_ranges": [], "n_workers": 1}
        meta = store.build_meta(
            run_id=TEST_RUN_ID,
            config_dict=config_dict,
            all_results=results,
            sensitivity={},
            status="completed",
            duration_seconds=5.0,
            combinations_tested=10,
            benchmark_ms=50.0,
        )
        scores = [e["score"] for e in meta["top_100"]]
        assert scores == sorted(scores, reverse=True), "Top100 non trié par score décroissant"


class TestConfigFile:

    def test_save_and_load_config(self):
        config = {
            "strategy_module": "strategies.perfect_revolution_v1",
            "strategy_name": "Test",
            "data_file": "nasdaq_3m.csv",
            "mode": "grid",
            "param_ranges": [],
            "base_params": {},
            "n_workers": 1,
        }
        store.save_config(TEST_RUN_ID, config)
        loaded = store.load_config(TEST_RUN_ID)
        assert loaded is not None
        assert loaded["strategy_name"] == "Test"
        assert loaded["mode"] == "grid"
