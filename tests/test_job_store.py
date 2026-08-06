import json
from pathlib import Path

import job_store
from market_data.backtest_manifest import load_backtest_manifest


def test_write_best_strategies_creates_empty_csv(tmp_path):
    job_store.write_best_strategies(str(tmp_path), [])

    csv_path = tmp_path / "best_strategies.csv"
    assert csv_path.exists()
    header = csv_path.read_text(encoding="utf-8").splitlines()[0]
    assert "rank" in header
    assert "score" in header


# ═══════════════════════════════════════════════════════════════════════════════
# data_manifest.json — additif, Data Center Phase 11.
# ═══════════════════════════════════════════════════════════════════════════════


def test_write_data_manifest_creates_a_valid_manifest(tmp_path):
    config_dict = {"data_file": "C:/some/path/nasdaq_3m.csv"}
    meta = {"strategy_name": "NASDAQ Perfect Revolution V1.1"}

    job_store.write_data_manifest(str(tmp_path), config_dict, meta)

    manifest_path = tmp_path / "data_manifest.json"
    assert manifest_path.is_file()
    manifest = load_backtest_manifest(manifest_path)
    assert manifest is not None
    assert manifest.instrument == "nasdaq_3m"
    assert manifest.strategy_version == "NASDAQ Perfect Revolution V1.1"


def test_write_data_manifest_never_raises_even_with_empty_inputs(tmp_path):
    job_store.write_data_manifest(str(tmp_path), {}, {})  # ne doit jamais lever
    assert (tmp_path / "data_manifest.json").is_file()


def test_write_data_manifest_does_not_overwrite_an_existing_manifest(tmp_path):
    job_store.write_data_manifest(str(tmp_path), {"data_file": "a.csv"}, {})
    first = (tmp_path / "data_manifest.json").read_text(encoding="utf-8")

    job_store.write_data_manifest(str(tmp_path), {"data_file": "b.csv"}, {})  # ne doit pas lever
    second = (tmp_path / "data_manifest.json").read_text(encoding="utf-8")

    assert first == second  # immuable : le second appel n'a rien changé


def test_write_data_manifest_never_contains_a_secret(tmp_path):
    job_store.write_data_manifest(str(tmp_path), {"data_file": "nasdaq_3m.csv"}, {})
    dump = (tmp_path / "data_manifest.json").read_text(encoding="utf-8")
    assert "api_token" not in dump
    assert "api_key" not in dump


def test_finalize_job_writes_data_manifest_without_breaking_archive_file_list(tmp_path):
    job_store.finalize_job(
        job_dir=str(tmp_path),
        meta={"strategy_name": "Test", "top_100": []},
        config_dict={"data_file": "nasdaq_3m.csv"},
        all_results=[],
        benchmark_ms=10.0,
        df_rows_used=100,
        log_lines=["test"],
    )

    assert (tmp_path / "data_manifest.json").is_file()

    # data_manifest.json ne doit jamais apparaître dans archive.zip — seuls les fichiers de
    # ARCHIVE_SOURCE_FILES (progress.json/config_used.json/results.csv/metrics.json/
    # best_strategies.csv/report.html/logs.txt) y sont inclus, jamais un scan de dossier.
    import zipfile

    with zipfile.ZipFile(tmp_path / "archive.zip") as zf:
        names = set(zf.namelist())
    assert "data_manifest.json" not in names
    assert names.issubset(
        {"progress.json", "config_used.json", "results.csv", "metrics.json",
         "best_strategies.csv", "report.html", "logs.txt"}
    )
    assert "metrics.json" in names  # au moins un fichier réellement généré par finalize_job
