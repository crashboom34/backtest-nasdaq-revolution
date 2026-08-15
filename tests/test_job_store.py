import json
import os
from pathlib import Path

import pandas as pd
import pytest

import job_store
from market_data.backtest_manifest import load_backtest_manifest
from market_data.content_hash import content_hash


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


def test_write_data_manifest_uses_provided_source_timeframe(tmp_path):
    job_store.write_data_manifest(str(tmp_path), {"data_file": "nasdaq_3m.csv"}, {}, source_timeframe="M3")
    manifest = load_backtest_manifest(tmp_path / "data_manifest.json")
    assert manifest.source_timeframe == "M3"


def test_write_data_manifest_defaults_to_unknown_without_source_timeframe(tmp_path):
    job_store.write_data_manifest(str(tmp_path), {"data_file": "nasdaq_3m.csv"}, {})
    manifest = load_backtest_manifest(tmp_path / "data_manifest.json")
    assert manifest.source_timeframe == "unknown"


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


# ═══════════════════════════════════════════════════════════════════════════════
# content_hash — propagation dans le pipeline de job (AF-DATA-02, HASH ONCE, PROPAGATE MANY).
# ═══════════════════════════════════════════════════════════════════════════════


def test_write_data_manifest_propagates_a_real_content_hash_when_provided(tmp_path):
    job_store.write_data_manifest(
        str(tmp_path), {"data_file": "nasdaq_3m.csv"}, {}, content_hash="deadbeef" * 8,
    )
    manifest = load_backtest_manifest(tmp_path / "data_manifest.json")
    assert manifest.content_hash == "deadbeef" * 8


def test_write_data_manifest_content_hash_defaults_to_none_without_it(tmp_path):
    """G. Compatibilité legacy : un appel sans content_hash (comportement historique) laisse
    le champ à None, comme avant AF-DATA-02."""
    job_store.write_data_manifest(str(tmp_path), {"data_file": "nasdaq_3m.csv"}, {})
    manifest = load_backtest_manifest(tmp_path / "data_manifest.json")
    assert manifest.content_hash is None


def test_finalize_job_propagates_content_hash_into_data_manifest(tmp_path):
    """A + B. Un nouveau job transmet le hash réel du fichier source jusqu'au manifeste."""
    job_store.finalize_job(
        job_dir=str(tmp_path),
        meta={"strategy_name": "Test", "top_100": []},
        config_dict={"data_file": "nasdaq_3m.csv"},
        all_results=[],
        benchmark_ms=10.0,
        df_rows_used=100,
        log_lines=["test"],
        content_hash="cafef00d" * 8,
    )
    manifest = load_backtest_manifest(tmp_path / "data_manifest.json")
    assert manifest.content_hash == "cafef00d" * 8


def test_finalize_job_without_content_hash_stays_legacy_compatible(tmp_path):
    """G. Un appel sans content_hash (chemin legacy, encore utilisé tant qu'un appelant ne le
    fournit pas) reste entièrement fonctionnel : le manifeste est produit, content_hash=None."""
    job_store.finalize_job(
        job_dir=str(tmp_path),
        meta={"strategy_name": "Test", "top_100": []},
        config_dict={"data_file": "nasdaq_3m.csv"},
        all_results=[],
        benchmark_ms=10.0,
        df_rows_used=100,
        log_lines=["test"],
    )
    manifest = load_backtest_manifest(tmp_path / "data_manifest.json")
    assert manifest is not None
    assert manifest.content_hash is None


def test_compute_source_content_hash_matches_market_data_content_hash(tmp_path):
    """B. Le hash calculé par ce wrapper est exactement celui de market_data.content_hash pour
    les mêmes octets — aucune transformation, aucun recalcul différent."""
    csv_path = tmp_path / "sample.csv"
    csv_path.write_bytes(b"time,close\n2024-01-01,100.0\n")

    assert job_store.compute_source_content_hash(str(csv_path)) == content_hash(csv_path)


def test_compute_source_content_hash_is_independent_of_path(tmp_path):
    """C. Mêmes octets, deux chemins différents -> même identité de contenu."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    content = b"time,close\n2024-01-01,100.0\n"
    (dir_a / "nasdaq_3m.csv").write_bytes(content)
    (dir_b / "other_name.csv").write_bytes(content)

    assert job_store.compute_source_content_hash(str(dir_a / "nasdaq_3m.csv")) == \
        job_store.compute_source_content_hash(str(dir_b / "other_name.csv"))


def test_compute_source_content_hash_changes_when_a_byte_changes(tmp_path):
    """D. Changement d'un seul octet -> hash différent."""
    csv_path = tmp_path / "sample.csv"
    csv_path.write_bytes(b"time,close\n2024-01-01,100.0\n")
    before = job_store.compute_source_content_hash(str(csv_path))

    csv_path.write_bytes(b"time,close\n2024-01-01,100.1\n")
    after = job_store.compute_source_content_hash(str(csv_path))

    assert before != after


def test_compute_source_content_hash_returns_none_for_a_missing_file(tmp_path):
    """Best-effort explicite : un fichier absent au moment du calcul de provenance ne doit
    jamais faire planter le job (distinct d'un échec de chargement des données, géré ailleurs,
    en amont, avant que ce calcul n'ait lieu)."""
    missing = tmp_path / "does_not_exist.csv"

    assert job_store.compute_source_content_hash(str(missing)) is None


def test_compute_source_content_hash_never_modifies_the_source_file(tmp_path):
    """E. Le calcul de provenance ne modifie jamais le fichier source."""
    csv_path = tmp_path / "sample.csv"
    original = b"time,close\n2024-01-01,100.0\n"
    csv_path.write_bytes(original)
    original_mtime = csv_path.stat().st_mtime_ns

    job_store.compute_source_content_hash(str(csv_path))

    assert csv_path.read_bytes() == original
    assert csv_path.stat().st_mtime_ns == original_mtime


# ═══════════════════════════════════════════════════════════════════════════════
# Compatibilité legacy explicite — AF-DATA-03 (jobs sans provenance complète).
# ═══════════════════════════════════════════════════════════════════════════════


def test_legacy_job_directory_without_data_manifest_stays_readable(tmp_path):
    """Acceptance criterion AF-DATA-03 : un job directory réaliste (autres artefacts
    historiques présents, comme un vrai job d'avant AF-DATA-01/02) mais SANS data_manifest.json
    reste lisible, sans exception."""
    job_store.write_metrics(
        str(tmp_path), {"top_100": []}, {"data_file": "nasdaq_3m.csv"}, 10.0, 100
    )
    job_store.write_best_strategies(str(tmp_path), [])

    assert (tmp_path / "metrics.json").is_file()
    assert not (tmp_path / "data_manifest.json").exists()
    assert load_backtest_manifest(tmp_path / "data_manifest.json") is None  # jamais d'exception


def test_write_data_manifest_preserves_first_content_hash_across_repeated_calls(tmp_path):
    """G, ciblé sur le nouveau chemin AF-DATA-02 : deux appels avec des content_hash DIFFÉRENTS
    -> le premier manifeste écrit (et son content_hash) n'est jamais remplacé par le second."""
    job_store.write_data_manifest(
        str(tmp_path), {"data_file": "nasdaq_3m.csv"}, {}, content_hash="1111" * 16,
    )
    job_store.write_data_manifest(  # ne doit rien changer, immuable
        str(tmp_path), {"data_file": "nasdaq_3m.csv"}, {}, content_hash="2222" * 16,
    )

    manifest = load_backtest_manifest(tmp_path / "data_manifest.json")
    assert manifest.content_hash == "1111" * 16


def test_finalize_job_never_touches_a_preexisting_config_used_json(tmp_path):
    """In scope AF-DATA-03 : config_used.json (écrit en amont par optimizer_process.py, pas par
    job_store) n'est ni réécrit ni modifié par le nouveau chemin enrichi de content_hash —
    y compris lorsque write_archive() le lit pour le bundler dans archive.zip."""
    legacy_config_path = tmp_path / "config_used.json"
    legacy_config_path.write_text('{"data_file": "nasdaq_3m.csv", "legacy": true}', encoding="utf-8")
    original_bytes = legacy_config_path.read_bytes()
    original_mtime = legacy_config_path.stat().st_mtime_ns

    job_store.finalize_job(
        job_dir=str(tmp_path),
        meta={"strategy_name": "Test", "top_100": []},
        config_dict={"data_file": "nasdaq_3m.csv"},
        all_results=[],
        benchmark_ms=10.0,
        df_rows_used=100,
        log_lines=["test"],
        content_hash="deadbeef" * 8,
    )

    assert legacy_config_path.read_bytes() == original_bytes
    assert legacy_config_path.stat().st_mtime_ns == original_mtime


# ═══════════════════════════════════════════════════════════════════════════════
# AF-DATA-04A — snapshot_id, period_start/period_end, contrôle de stabilité source.
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_local_csv_snapshot_id_has_the_expected_format(tmp_path):
    """B. Format exact : local_csv:sha256:<content_hash>."""
    csv_path = tmp_path / "sample.csv"
    csv_path.write_bytes(b"abc")
    expected_hash = content_hash(csv_path)

    snapshot_id = job_store.build_local_csv_snapshot_id(expected_hash)

    assert snapshot_id == f"local_csv:sha256:{expected_hash}"


def test_build_local_csv_snapshot_id_is_none_when_content_hash_is_none():
    assert job_store.build_local_csv_snapshot_id(None) is None


def test_build_local_csv_snapshot_id_same_content_different_paths_same_snapshot_id(tmp_path):
    """C. Mêmes octets, chemins différents -> même content_hash -> même snapshot_id."""
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    data = b"time,close\n2024-01-01,100.0\n"
    (dir_a / "nasdaq_3m.csv").write_bytes(data)
    (dir_b / "other_name.csv").write_bytes(data)

    hash_a = job_store.compute_source_content_hash(str(dir_a / "nasdaq_3m.csv"))
    hash_b = job_store.compute_source_content_hash(str(dir_b / "other_name.csv"))

    assert job_store.build_local_csv_snapshot_id(hash_a) == job_store.build_local_csv_snapshot_id(hash_b)


def test_build_local_csv_snapshot_id_different_content_different_snapshot_id(tmp_path):
    """D. Un octet modifié -> content_hash différent -> snapshot_id différent."""
    csv_path = tmp_path / "sample.csv"
    csv_path.write_bytes(b"time,close\n2024-01-01,100.0\n")
    before = job_store.build_local_csv_snapshot_id(job_store.compute_source_content_hash(str(csv_path)))

    csv_path.write_bytes(b"time,close\n2024-01-01,100.1\n")
    after = job_store.build_local_csv_snapshot_id(job_store.compute_source_content_hash(str(csv_path)))

    assert before != after


def test_write_data_manifest_propagates_snapshot_id_when_provided(tmp_path):
    """A. snapshot_id réel écrit dans le manifeste."""
    job_store.write_data_manifest(
        str(tmp_path), {"data_file": "nasdaq_3m.csv"}, {},
        snapshot_id="local_csv:sha256:" + "ab" * 32,
    )
    manifest = load_backtest_manifest(tmp_path / "data_manifest.json")
    assert manifest.snapshot_id == "local_csv:sha256:" + "ab" * 32


def test_write_data_manifest_snapshot_id_defaults_to_none_without_it(tmp_path):
    """E. Un appel sans snapshot_id (legacy) reste compatible : reste None."""
    job_store.write_data_manifest(str(tmp_path), {"data_file": "nasdaq_3m.csv"}, {})
    manifest = load_backtest_manifest(tmp_path / "data_manifest.json")
    assert manifest.snapshot_id is None


def test_write_data_manifest_propagates_period_bounds_when_provided(tmp_path):
    job_store.write_data_manifest(
        str(tmp_path), {"data_file": "nasdaq_3m.csv"}, {},
        period_start="2024-01-01T00:00:00+00:00", period_end="2024-01-02T00:00:00+00:00",
    )
    manifest = load_backtest_manifest(tmp_path / "data_manifest.json")
    assert manifest.period_start == "2024-01-01T00:00:00+00:00"
    assert manifest.period_end == "2024-01-02T00:00:00+00:00"


def test_compute_source_period_bounds_returns_full_range_as_iso8601_utc():
    """F, G. period_start/period_end = min/max de la colonne time, en UTC explicite (même
    convention que engine.py::_add_market_time_columns, pas une nouvelle hypothèse de fuseau)."""
    times = pd.to_datetime(pd.Series(["2024-03-01 09:00:00", "2024-03-01 09:03:00", "2024-03-01 09:06:00"]))

    period_start, period_end = job_store.compute_source_period_bounds(times)

    assert period_start == "2024-03-01T09:00:00+00:00"
    assert period_end == "2024-03-01T09:06:00+00:00"


def test_compute_source_period_bounds_is_order_independent():
    """La borne ne dépend pas de l'ordre des lignes dans le DataFrame source."""
    times = pd.to_datetime(pd.Series(["2024-03-01 09:06:00", "2024-03-01 09:00:00", "2024-03-01 09:03:00"]))

    period_start, period_end = job_store.compute_source_period_bounds(times)

    assert period_start == "2024-03-01T09:00:00+00:00"
    assert period_end == "2024-03-01T09:06:00+00:00"


def test_compute_source_period_bounds_returns_none_for_empty_series():
    period_start, period_end = job_store.compute_source_period_bounds(pd.Series([], dtype="datetime64[ns]"))

    assert period_start is None
    assert period_end is None


# ── Contrôle de stabilité source (taille + mtime_ns, pas un second SHA-256) ─────────────────


def test_capture_source_signature_returns_size_and_mtime(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_bytes(b"abc")

    size, mtime_ns = job_store.capture_source_signature(str(csv_path))

    st = os.stat(csv_path)
    assert size == st.st_size == 3
    assert mtime_ns == st.st_mtime_ns


def test_assert_source_signature_unchanged_passes_when_source_is_stable(tmp_path):
    """K. Source stable -> pipeline normal, aucune exception."""
    csv_path = tmp_path / "sample.csv"
    csv_path.write_bytes(b"time,close\n2024-01-01,100.0\n")
    before = job_store.capture_source_signature(str(csv_path))

    job_store.assert_source_signature_unchanged(str(csv_path), before)  # ne doit pas lever


def test_assert_source_signature_unchanged_raises_when_source_mutated(tmp_path):
    """L. Mutation détectée entre les étapes -> le pipeline refuse de certifier la provenance.
    Mutation simulée de façon déterministe (écriture directe du fichier), pas une course
    réelle entre threads/process."""
    csv_path = tmp_path / "sample.csv"
    csv_path.write_bytes(b"time,close\n2024-01-01,100.0\n")
    before = job_store.capture_source_signature(str(csv_path))

    csv_path.write_bytes(b"time,close\n2024-01-01,100.0\nEXTRA,LINE\n")  # mutation déterministe

    with pytest.raises(job_store.SourceMutatedDuringLoadError):
        job_store.assert_source_signature_unchanged(str(csv_path), before)


def test_stability_check_never_computes_a_second_sha256(tmp_path, monkeypatch):
    """M. HASH ONCE : capture_source_signature()/assert_source_signature_unchanged() ne
    déclenchent jamais de second calcul de content_hash."""
    csv_path = tmp_path / "sample.csv"
    csv_path.write_bytes(b"time,close\n2024-01-01,100.0\n")

    calls = []
    original = job_store.compute_content_hash

    def _counting_hash(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(job_store, "compute_content_hash", _counting_hash)

    signature_before = job_store.capture_source_signature(str(csv_path))
    result_hash = job_store.compute_source_content_hash(str(csv_path))
    job_store.assert_source_signature_unchanged(str(csv_path), signature_before)

    assert len(calls) == 1
    assert result_hash == content_hash(csv_path)


def test_capture_source_signature_never_modifies_the_source_file(tmp_path):
    """N. Le contrôle de stabilité ne modifie jamais le fichier source."""
    csv_path = tmp_path / "sample.csv"
    original = b"time,close\n2024-01-01,100.0\n"
    csv_path.write_bytes(original)
    original_mtime = csv_path.stat().st_mtime_ns

    job_store.capture_source_signature(str(csv_path))

    assert csv_path.read_bytes() == original
    assert csv_path.stat().st_mtime_ns == original_mtime


def test_finalize_job_with_content_hash_keeps_all_historical_artifacts_intact(tmp_path):
    """F, combiné avec un content_hash réel (trouvé manquant par la revue Spec AF-DATA-02) :
    fournir un content_hash ne dégrade en rien la génération des 5 artefacts historiques + leur
    archive — même vérification que test_finalize_job_writes_data_manifest_without_breaking_
    archive_file_list, mais avec content_hash effectivement renseigné cette fois."""
    job_store.finalize_job(
        job_dir=str(tmp_path),
        meta={"strategy_name": "Test", "top_100": []},
        config_dict={"data_file": "nasdaq_3m.csv"},
        all_results=[],
        benchmark_ms=10.0,
        df_rows_used=100,
        log_lines=["test"],
        content_hash="feedface" * 8,
    )

    assert (tmp_path / "metrics.json").is_file()
    assert (tmp_path / "best_strategies.csv").is_file()
    assert (tmp_path / "report.html").is_file()
    assert (tmp_path / "logs.txt").is_file()
    assert (tmp_path / "data_manifest.json").is_file()

    manifest = load_backtest_manifest(tmp_path / "data_manifest.json")
    assert manifest.content_hash == "feedface" * 8

    import zipfile
    with zipfile.ZipFile(tmp_path / "archive.zip") as zf:
        names = set(zf.namelist())
    assert "data_manifest.json" not in names  # toujours exclu de l'archive
    assert "metrics.json" in names


# ═══════════════════════════════════════════════════════════════════════════════
# AF-R-01 — Experiment / ResearchRun, câblage optionnel dans le pipeline de job.
# ═══════════════════════════════════════════════════════════════════════════════


def test_write_research_run_does_nothing_without_experiment_id(tmp_path):
    """Legacy compatible : sans experiment_id, aucun fichier Research n'est créé — chemin
    inchangé pour les jobs qui n'utilisent pas encore ce schéma."""
    job_store.write_research_run(str(tmp_path), research_run_id="run_x")

    assert not (tmp_path / "research_run.json").exists()
    assert not (tmp_path.parent / "experiments").exists()


def test_write_research_run_creates_research_run_and_experiment_files(tmp_path):
    job_dir = tmp_path / "results" / "job_x"
    job_dir.mkdir(parents=True)

    job_store.write_research_run(
        str(job_dir), research_run_id="run_x", experiment_id="exp_x",
        dataset_snapshot_id="local_csv:sha256:" + "ab" * 32,
    )

    research_run_path = job_dir / "research_run.json"
    experiment_path = tmp_path / "results" / "experiments" / "exp_x.json"
    assert research_run_path.is_file()
    assert experiment_path.is_file()

    from research_run import load_experiment, load_research_run
    run = load_research_run(research_run_path)
    experiment = load_experiment(experiment_path)
    assert run.experiment_id == "exp_x"
    assert run.dataset_snapshot_id == "local_csv:sha256:" + "ab" * 32
    assert experiment.experiment_id == "exp_x"


def test_write_research_run_shares_one_experiment_file_across_two_jobs(tmp_path):
    """E, au niveau pipeline : deux jobs différents partageant le même experiment_id -> un seul
    fichier experiments/exp_x.json, jamais réécrit par le second job."""
    job_dir_a = tmp_path / "results" / "job_a"
    job_dir_b = tmp_path / "results" / "job_b"
    job_dir_a.mkdir(parents=True)
    job_dir_b.mkdir(parents=True)

    a_real_snapshot_id = "local_csv:sha256:" + "ab" * 32
    job_store.write_research_run(
        str(job_dir_a), research_run_id="run_a", experiment_id="exp_shared",
        hypothesis="Première formulation", dataset_snapshot_id=a_real_snapshot_id,
    )
    job_store.write_research_run(  # ne doit pas lever, ne doit pas écraser
        str(job_dir_b), research_run_id="run_b", experiment_id="exp_shared",
        hypothesis="Reformulation ignorée", dataset_snapshot_id=a_real_snapshot_id,
    )

    from research_run import load_experiment
    experiment = load_experiment(tmp_path / "results" / "experiments" / "exp_shared.json")
    assert experiment.hypothesis == "Première formulation"
    assert (job_dir_a / "research_run.json").is_file()
    assert (job_dir_b / "research_run.json").is_file()


def test_reusing_an_experiment_id_with_a_contradictory_hypothesis_never_corrupts_the_first(
    tmp_path,
):
    """Revue AF-R-01 (2026-08-15), scénario explicite demandé : 1) créer Experiment exp-A avec
    hypothesis="H1" (via un premier ResearchRun) ; 2) tenter de réutiliser experiment_id="exp-A"
    avec hypothesis="H2" incompatible (via un second ResearchRun).

    Garantie : ni écrasement silencieux, ni fusion trompeuse de deux hypothèses incompatibles sous
    un même Experiment — la première écriture fait foi, immuable (`FileExistsError` interne
    absorbé en best-effort, jamais un `hypothesis` mélangé ou corrompu). C'est la conséquence
    directe et déjà voulue de "Experiment = conteneur durable, jamais modifié après création" : le
    choix du même `experiment_id` par l'appelant EST l'affirmation qu'il s'agit de la même ligne de
    recherche — un `experiment_id` différent est le mécanisme prévu pour deux hypothèses
    distinctes, pas une divergence de `hypothesis` texte libre sous le même id."""
    job_dir_a = tmp_path / "results" / "job_a"
    job_dir_b = tmp_path / "results" / "job_b"
    job_dir_a.mkdir(parents=True)
    job_dir_b.mkdir(parents=True)
    a_real_snapshot_id = "local_csv:sha256:" + "ab" * 32

    job_store.write_research_run(  # 1) Experiment exp-A créé avec H1
        str(job_dir_a), research_run_id="run_a", experiment_id="exp-A",
        hypothesis="H1", dataset_snapshot_id=a_real_snapshot_id,
    )
    job_store.write_research_run(  # 2) tentative avec H2 incompatible — ne doit jamais lever
        str(job_dir_b), research_run_id="run_b", experiment_id="exp-A",
        hypothesis="H2", dataset_snapshot_id=a_real_snapshot_id,
    )

    from research_run import load_experiment
    experiment = load_experiment(tmp_path / "results" / "experiments" / "exp-A.json")
    assert experiment.hypothesis == "H1"  # jamais écrasé par H2, jamais fusionné
    assert experiment.hypothesis != "H2"


@pytest.mark.parametrize("bad_snapshot_id", [None, "", "   "])
def test_write_research_run_does_nothing_without_a_real_dataset_snapshot_id(
    tmp_path, bad_snapshot_id,
):
    """Symétrique de test_build_research_run_requires_a_real_dataset_snapshot_id
    (tests/test_research_run.py) au niveau pipeline : un job sans identité dataset exploitable ne
    doit produire AUCUN ResearchRun — mais ne doit jamais casser le job (best-effort, comme le
    reste de write_research_run())."""
    job_dir = tmp_path / "results" / "job_x"
    job_dir.mkdir(parents=True)

    job_store.write_research_run(  # ne doit jamais lever
        str(job_dir), research_run_id="run_x", experiment_id="exp_x",
        dataset_snapshot_id=bad_snapshot_id,
    )

    assert not (job_dir / "research_run.json").exists()
    assert not (tmp_path / "results" / "experiments" / "exp_x.json").exists()


def test_write_research_run_places_experiments_dir_as_a_true_sibling_even_with_trailing_separator(
    tmp_path,
):
    """Revue AF-R-01, point 5 : os.path.dirname(job_dir) seul se laisserait piéger par un job_dir
    se terminant par un séparateur (renverrait job_dir lui-même, pas son parent) — experiments/
    finirait niché DANS le job directory au lieu d'en être le sibling attendu
    (results/experiments/, pas results/job_x/experiments/). job_dir provient d'un argument externe
    (sys.argv/BACKTEST_JOB_DIR côté optimizer_process.py) — pas garanti sans séparateur final."""
    job_dir = tmp_path / "results" / "job_x"
    job_dir.mkdir(parents=True)
    job_dir_with_trailing_sep = str(job_dir) + os.sep

    job_store.write_research_run(
        job_dir_with_trailing_sep, research_run_id="run_x", experiment_id="exp_x",
        dataset_snapshot_id="local_csv:sha256:" + "ab" * 32,
    )

    sibling_experiments_dir = tmp_path / "results" / "experiments"
    nested_experiments_dir = job_dir / "experiments"
    assert (sibling_experiments_dir / "exp_x.json").is_file()
    assert not nested_experiments_dir.exists()


def test_write_research_run_rejects_an_experiment_id_unsafe_for_windows_filenames(tmp_path):
    """Trouvé en revue globale Track R : experiment_id passe validate_identifier() (rejette
    seulement '/', '\\', '..', vide) mais PAS ':'/'*'/'?'/'<'/'>'/'|', invalides comme nom de
    fichier Windows. **Correction (MCP Codex)** : sanitiser silencieusement (remplacer par '_')
    serait une transformation à PERTE — "exp:a" et "exp*a" produiraient le même nom de fichier, un
    vrai risque de collision d'identité. Un experiment_id du type "exp:v2*bad?" doit donc être
    REJETÉ (ValueError côté build_experiment(), absorbé en best-effort ici — ne casse jamais le
    job), jamais silencieusement transformé."""
    job_dir = tmp_path / "results" / "job_x"
    job_dir.mkdir(parents=True)

    job_store.write_research_run(  # ne doit jamais lever au niveau pipeline (best-effort)
        str(job_dir), research_run_id="run_x", experiment_id="exp:v2*bad?",
        dataset_snapshot_id="local_csv:sha256:" + "ab" * 32,
    )

    experiments_dir = tmp_path / "results" / "experiments"
    assert not experiments_dir.exists() or list(experiments_dir.glob("*.json")) == []
    # Atomique : experiment_id invalide -> ni l'Experiment ni research_run.json ne sont écrits.
    assert not (job_dir / "research_run.json").exists()


def test_write_research_run_never_modifies_a_preexisting_data_manifest(tmp_path):
    job_dir = tmp_path / "results" / "job_x"
    job_dir.mkdir(parents=True)
    legacy_manifest = job_dir / "data_manifest.json"
    legacy_manifest.write_text('{"legacy": true}', encoding="utf-8")
    original_bytes = legacy_manifest.read_bytes()
    original_mtime = legacy_manifest.stat().st_mtime_ns

    job_store.write_research_run(str(job_dir), research_run_id="run_x", experiment_id="exp_x")

    assert legacy_manifest.read_bytes() == original_bytes
    assert legacy_manifest.stat().st_mtime_ns == original_mtime


@pytest.mark.parametrize("bad_experiment_id", ["../escape", "a/b", "a\\b", ".."])
def test_write_research_run_rejects_unsafe_experiment_id_without_escaping_experiments_dir(
    tmp_path, bad_experiment_id,
):
    """Trouvé par revue indépendante (MCP Codex) : `experiment_id` sert à construire
    `experiments/<experiment_id>.json` — un identifiant contenant un séparateur de chemin ou
    '..' pourrait faire écrire en dehors de `results/experiments/`. `research_run.py` rejette
    maintenant ces identifiants (`_validate_identifier`) ; ici on vérifie qu'au niveau pipeline
    ce rejet reste best-effort (ne casse jamais le job — même contrat que le reste de
    write_research_run()) et qu'aucun fichier n'apparaît hors de results/experiments/."""
    job_dir = tmp_path / "results" / "job_x"
    job_dir.mkdir(parents=True)

    job_store.write_research_run(  # ne doit jamais lever
        str(job_dir), research_run_id="run_x", experiment_id=bad_experiment_id,
    )

    assert not (job_dir / "research_run.json").exists()
    assert not (tmp_path / "escape.json").exists()
    experiments_dir = tmp_path / "results" / "experiments"
    if experiments_dir.exists():
        assert list(experiments_dir.iterdir()) == []


def test_finalize_job_without_experiment_id_stays_legacy_compatible(tmp_path):
    """Chemin par défaut (aucun appelant actuel ne fournit encore experiment_id) : finalize_job()
    reste identique à avant AF-R-01, aucun fichier Research créé."""
    job_store.finalize_job(
        job_dir=str(tmp_path),
        meta={"strategy_name": "Test", "top_100": []},
        config_dict={"data_file": "nasdaq_3m.csv"},
        all_results=[],
        benchmark_ms=10.0,
        df_rows_used=100,
        log_lines=["test"],
    )

    assert not (tmp_path / "research_run.json").exists()


def test_finalize_job_with_experiment_id_writes_research_run(tmp_path):
    job_dir = tmp_path / "results" / "job_x"
    job_dir.mkdir(parents=True)

    job_store.finalize_job(
        job_dir=str(job_dir),
        meta={"strategy_name": "Test", "top_100": []},
        config_dict={"data_file": "nasdaq_3m.csv"},
        all_results=[],
        benchmark_ms=10.0,
        df_rows_used=100,
        log_lines=["test"],
        content_hash="deadbeef" * 8,
        snapshot_id="local_csv:sha256:" + "deadbeef" * 8,
        experiment_id="exp_x",
    )

    assert (job_dir / "research_run.json").is_file()
    from research_run import load_research_run
    run = load_research_run(job_dir / "research_run.json")
    # dataset_snapshot_id du ResearchRun réutilise le snapshot_id déjà calculé pour ce job — jamais
    # recalculé, jamais dupliqué manuellement par l'appelant.
    assert run.dataset_snapshot_id == "local_csv:sha256:" + "deadbeef" * 8
    # AF-R-02 : git_sha/engine_version capturés automatiquement (job_store.py vit dans ce vrai
    # dépôt Git) sans qu'aucun appelant n'ait rien fourni — jamais d'exception, jamais None inventé
    # comme une fausse preuve si Git était indisponible (voir test dédié ci-dessous pour ce cas).
    assert run.git_sha is None or isinstance(run.git_sha, str)
    assert run.engine_version
    # research_seed non fourni ici -> reste None, jamais inventé (E).
    assert run.seed is None


def test_finalize_job_with_research_seed_writes_it_into_research_run(tmp_path):
    """C, D au niveau pipeline : research_seed transmis à finalize_job() se retrouve tel quel dans
    le ResearchRun persisté."""
    job_dir = tmp_path / "results" / "job_x"
    job_dir.mkdir(parents=True)

    job_store.finalize_job(
        job_dir=str(job_dir),
        meta={"strategy_name": "Test", "top_100": []},
        config_dict={"data_file": "nasdaq_3m.csv"},
        all_results=[],
        benchmark_ms=10.0,
        df_rows_used=100,
        log_lines=["test"],
        snapshot_id="local_csv:sha256:" + "deadbeef" * 8,
        experiment_id="exp_x",
        research_seed=20260815,
    )

    from research_run import load_research_run
    run = load_research_run(job_dir / "research_run.json")
    assert run.seed == 20260815


def test_finalize_job_without_research_seed_stays_legacy_compatible(tmp_path):
    """L : un appelant qui ne fournit pas research_seed (chemin actuel, aucun appelant réel ne le
    fait encore) obtient un ResearchRun avec seed=None — comportement inchangé par rapport à
    avant AF-R-02, pas une régression du chemin déjà testé par test_finalize_job_without_
    experiment_id_stays_legacy_compatible (aucun fichier Research du tout, cas plus strict)."""
    job_dir = tmp_path / "results" / "job_y"
    job_dir.mkdir(parents=True)

    job_store.finalize_job(
        job_dir=str(job_dir),
        meta={"strategy_name": "Test", "top_100": []},
        config_dict={"data_file": "nasdaq_3m.csv"},
        all_results=[],
        benchmark_ms=10.0,
        df_rows_used=100,
        log_lines=["test"],
        snapshot_id="local_csv:sha256:" + "deadbeef" * 8,
        experiment_id="exp_y",
    )

    from research_run import load_research_run
    run = load_research_run(job_dir / "research_run.json")
    assert run.seed is None
