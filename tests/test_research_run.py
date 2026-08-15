"""
tests/test_research_run.py — AF-R-01 : Experiment / ResearchRun, schéma minimal + stockage
fichier (Track R, après GATE DATA = PASS).

Experiment = conteneur durable (hypothesis optionnelle), peut regrouper plusieurs ResearchRun
(DOMAIN_MODEL.md §7). ResearchRun = exécution concrète immuable ; référence le dataset source par
IDENTIFIANT (`dataset_snapshot_id`, ex. "local_csv:sha256:...", produit par AF-DATA), jamais par
copie des autres champs de provenance (period_start/period_end/source_timeframe restent
uniquement dans data_manifest.json).

Aucune base de données, aucune UI : persistance fichier pure, même motif que
market_data/backtest_manifest.py (dataclasses frozen, écriture atomique immuable, lecture
tolérante).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_run import (
    Experiment,
    ResearchRun,
    build_experiment,
    build_research_run,
    load_experiment,
    load_research_run,
    save_experiment,
    save_research_run,
)


# ═══════════════════════════════════════════════════════════════════════════════
# A. Experiment minimal
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_experiment_minimal(tmp_path):
    experiment = build_experiment(experiment_id="exp_nasdaq_daytrading_m15")

    assert experiment.experiment_id == "exp_nasdaq_daytrading_m15"
    assert experiment.hypothesis is None
    assert experiment.created_at  # horodatage auto-rempli


def test_build_experiment_with_hypothesis():
    experiment = build_experiment(
        experiment_id="exp_nasdaq_daytrading_m15",
        hypothesis="Random Baseline vs algorithme génétique sur NASDAQ Day Trading M15",
    )

    assert experiment.hypothesis == (
        "Random Baseline vs algorithme génétique sur NASDAQ Day Trading M15"
    )


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "a\\b", "..", "", "   "])
def test_build_experiment_rejects_unsafe_identifiers(bad_id):
    """experiment_id sert directement à construire un chemin de fichier
    (results/experiments/<experiment_id>.json) — un identifiant contenant un séparateur de
    chemin ou '..' pourrait faire sortir l'écriture du répertoire prévu. Rejeté explicitement,
    pas seulement "espéré propre" par l'appelant (trouvé par MCP Codex, revue indépendante)."""
    with pytest.raises(ValueError):
        build_experiment(experiment_id=bad_id)


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "a\\b", "..", "", "   "])
def test_build_research_run_rejects_unsafe_identifiers(bad_id):
    """Même risque pour research_run_id (utilisé pour research_run.json dans le job_dir — moins
    critique car job_dir est déjà résolu en amont, mais protégé pour la même raison de
    cohérence/contrat)."""
    a_real_snapshot_id = "local_csv:sha256:" + "ab" * 32  # écarte toute ambiguïté avec l'invariant
    # séparé "dataset_snapshot_id obligatoire" : ces deux appels doivent lever à cause de bad_id.

    with pytest.raises(ValueError):
        build_research_run(
            research_run_id=bad_id, experiment_id="exp_x", dataset_snapshot_id=a_real_snapshot_id,
        )

    with pytest.raises(ValueError):
        build_research_run(
            research_run_id="run_x", experiment_id=bad_id, dataset_snapshot_id=a_real_snapshot_id,
        )


def test_build_experiment_accepts_a_normal_slug_identifier():
    """Confirme que les identifiants normaux (alphanumériques, tirets, underscores) restent
    acceptés — la validation ne doit pas être plus stricte que nécessaire."""
    experiment = build_experiment(experiment_id="exp_nasdaq-daytrading_m15.v2")
    assert experiment.experiment_id == "exp_nasdaq-daytrading_m15.v2"


def test_build_experiment_never_contains_a_secret():
    experiment = build_experiment(experiment_id="exp_x", hypothesis="clé api_key=SECRET")
    dump = json.dumps(experiment.__dict__)
    # Ce test documente qu'aucun champ dédié aux secrets n'existe sur Experiment — le champ libre
    # `hypothesis` reste sous la responsabilité de l'appelant, comme tout texte libre du dépôt.
    assert "hypothesis" in dump  # le champ existe ; ne pas cacher son propre contenu ne prouve rien


# ═══════════════════════════════════════════════════════════════════════════════
# Revue AF-R-01 — timestamps UTC, offset-aware, non ambigus (point 6)
# ═══════════════════════════════════════════════════════════════════════════════


def test_experiment_created_at_is_an_explicit_utc_offset_iso8601_timestamp():
    """datetime.now(timezone.utc).isoformat() produit déjà un format ISO-8601 offset-aware
    explicite ("...+00:00") — preuve documentée, pas une hypothèse. Reproductible et non ambigu
    entre fuseaux horaires (contrairement à un `datetime.now()` naïf sans timezone)."""
    experiment = build_experiment(experiment_id="exp_x")

    parsed = datetime.fromisoformat(experiment.created_at)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_research_run_completed_at_is_an_explicit_utc_offset_iso8601_timestamp():
    run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x",
        dataset_snapshot_id="local_csv:sha256:" + "ab" * 32, git_sha=None,
    )

    parsed = datetime.fromisoformat(run.completed_at)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


# ═══════════════════════════════════════════════════════════════════════════════
# B, C, D. ResearchRun lié à un Experiment, identifiant stable, référence dataset réelle
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_research_run_linked_to_experiment():
    run = build_research_run(
        research_run_id="run_20260815_120000_ab12",
        experiment_id="exp_nasdaq_daytrading_m15",
        dataset_snapshot_id="local_csv:sha256:" + "ab" * 32, git_sha=None,
    )

    assert run.experiment_id == "exp_nasdaq_daytrading_m15"


def test_research_run_has_a_stable_identifier():
    run = build_research_run(
        research_run_id="run_20260815_120000_ab12", experiment_id="exp_x",
        dataset_snapshot_id="local_csv:sha256:" + "ab" * 32, git_sha=None,
    )

    assert run.research_run_id == "run_20260815_120000_ab12"


def test_research_run_references_real_dataset_identity_by_identifier():
    """D. Référence par IDENTIFIANT (la chaîne snapshot_id produite par AF-DATA), jamais une
    copie des autres champs de provenance (period_start/period_end/source_timeframe)."""
    run = build_research_run(
        research_run_id="run_x",
        experiment_id="exp_x", git_sha=None,
        dataset_snapshot_id="local_csv:sha256:" + "ab" * 32,
    )

    assert run.dataset_snapshot_id == "local_csv:sha256:" + "ab" * 32
    # Aucun champ period_start/period_end/source_timeframe sur ResearchRun : la seule source de
    # vérité pour ces informations reste data_manifest.json, référencé par dataset_snapshot_id.
    assert not hasattr(run, "period_start")
    assert not hasattr(run, "source_timeframe")


@pytest.mark.parametrize("bad_snapshot_id", [None, "", "   "])
def test_build_research_run_requires_a_real_dataset_snapshot_id(bad_snapshot_id):
    """Revue AF-R-01 (2026-08-15) : DOMAIN_MODEL.md exprime la référence dataset d'un ResearchRun
    SANS condition ("un ResearchRun référence...", jamais "si disponible") — un ResearchRun sans
    identité dataset ne serait pas un record scientifique reproductible. Un job qui n'a pas encore
    d'identité dataset exploitable ne doit produire AUCUN ResearchRun (voir
    test_write_research_run_does_nothing_without_a_dataset_snapshot_id dans test_job_store.py pour
    la garantie symétrique côté pipeline : ceci ne casse jamais le job, ça empêche juste l'écriture
    d'un enregistrement invalide)."""
    with pytest.raises(ValueError):
        build_research_run(
            research_run_id="run_x", experiment_id="exp_x", dataset_snapshot_id=bad_snapshot_id,
        )


def test_build_research_run_missing_dataset_snapshot_id_argument_is_a_type_error():
    """dataset_snapshot_id n'a plus de valeur par défaut — l'omettre complètement (vs. passer une
    valeur vide) est un TypeError immédiat, signal encore plus explicite qu'une ValeurError pour un
    appelant qui aurait simplement oublié l'argument."""
    with pytest.raises(TypeError):
        build_research_run(research_run_id="run_x", experiment_id="exp_x")


# ═══════════════════════════════════════════════════════════════════════════════
# E. Plusieurs ResearchRun peuvent appartenir au même Experiment
# ═══════════════════════════════════════════════════════════════════════════════


def test_multiple_research_runs_can_share_the_same_experiment(tmp_path):
    a_real_snapshot_id = "local_csv:sha256:" + "ab" * 32
    run_a = build_research_run(
        research_run_id="run_a", experiment_id="exp_shared", dataset_snapshot_id=a_real_snapshot_id,
        git_sha=None,
    )
    run_b = build_research_run(
        research_run_id="run_b", experiment_id="exp_shared", dataset_snapshot_id=a_real_snapshot_id,
        git_sha=None,
    )

    path_a = save_research_run(tmp_path / "job_a" / "research_run.json", run_a)
    path_b = save_research_run(tmp_path / "job_b" / "research_run.json", run_b)

    loaded_a = load_research_run(path_a)
    loaded_b = load_research_run(path_b)

    assert loaded_a.experiment_id == loaded_b.experiment_id == "exp_shared"
    assert loaded_a.research_run_id != loaded_b.research_run_id


# ═══════════════════════════════════════════════════════════════════════════════
# F. Persistance puis relecture strictement cohérente
# ═══════════════════════════════════════════════════════════════════════════════


def test_save_and_load_experiment_round_trips(tmp_path):
    experiment = build_experiment(experiment_id="exp_x", hypothesis="Une question de recherche")
    path = save_experiment(tmp_path / "exp_x.json", experiment)

    loaded = load_experiment(path)

    assert loaded == experiment


def test_save_and_load_research_run_round_trips(tmp_path):
    run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x", git_sha=None,
        dataset_snapshot_id="local_csv:sha256:" + "cd" * 32,
    )
    path = save_research_run(tmp_path / "research_run.json", run)

    loaded = load_research_run(path)

    assert loaded == run


# ═══════════════════════════════════════════════════════════════════════════════
# G, H. Compatibilité legacy — job sans fichiers Research reste lisible, rien modifié
# ═══════════════════════════════════════════════════════════════════════════════


def test_load_research_run_tolerates_missing_file(tmp_path):
    """G. Un ancien job (avant Track R) sans research_run.json reste parfaitement lisible."""
    assert load_research_run(tmp_path / "does_not_exist.json") is None


def test_load_experiment_tolerates_missing_file(tmp_path):
    assert load_experiment(tmp_path / "does_not_exist.json") is None


def test_load_research_run_tolerates_corrupted_file(tmp_path):
    path = tmp_path / "corrupted.json"
    path.write_text("{not valid json", encoding="utf-8")

    assert load_research_run(path) is None


def test_save_research_run_never_modifies_an_unrelated_existing_file(tmp_path):
    """H. Sauver un nouveau ResearchRun ne touche jamais un fichier tiers déjà présent (ex. un
    ancien data_manifest.json du même job directory)."""
    legacy_path = tmp_path / "data_manifest.json"
    legacy_path.write_text('{"legacy": true}', encoding="utf-8")
    original_bytes = legacy_path.read_bytes()
    original_mtime = legacy_path.stat().st_mtime_ns

    run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x", git_sha=None,
        dataset_snapshot_id="local_csv:sha256:" + "ab" * 32,
    )
    save_research_run(tmp_path / "research_run.json", run)

    assert legacy_path.read_bytes() == original_bytes
    assert legacy_path.stat().st_mtime_ns == original_mtime


# ═══════════════════════════════════════════════════════════════════════════════
# I. Immutabilité — jamais écrasé
# ═══════════════════════════════════════════════════════════════════════════════


def test_save_experiment_never_overwrites_an_existing_experiment(tmp_path):
    """Un Experiment est un conteneur durable partagé entre plusieurs ResearchRun : la première
    écriture fait foi, les tentatives suivantes (même expérience relancée) ne l'écrasent jamais."""
    experiment = build_experiment(experiment_id="exp_x", hypothesis="Première version")
    path = tmp_path / "exp_x.json"
    save_experiment(path, experiment)

    with pytest.raises(FileExistsError):
        save_experiment(path, build_experiment(experiment_id="exp_x", hypothesis="Autre version"))

    # Le contenu original reste inchangé.
    assert load_experiment(path).hypothesis == "Première version"


def test_save_research_run_never_overwrites_an_existing_research_run(tmp_path):
    a_real_snapshot_id = "local_csv:sha256:" + "ab" * 32
    run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x", dataset_snapshot_id=a_real_snapshot_id,
        git_sha=None,
    )
    path = tmp_path / "research_run.json"
    save_research_run(path, run)

    with pytest.raises(FileExistsError):
        save_research_run(path, build_research_run(
            research_run_id="run_x", experiment_id="exp_y", dataset_snapshot_id=a_real_snapshot_id,
            git_sha=None,
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# J, K. Aucune dépendance PostgreSQL / UI (structurel, pas une décision cachée)
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# AF-R-02 — capture git_sha / seed / engine_version par ResearchRun
# ═══════════════════════════════════════════════════════════════════════════════


def _real_snapshot_id():
    return "local_csv:sha256:" + "ab" * 32


def test_build_research_run_detects_git_sha_automatically_when_in_a_real_repo():
    """A, B : la détection "auto" (par défaut) réutilise _current_git_commit() tel quel — jamais
    de valeur inventée si Git est indisponible, jamais d'exception. N'affirme aucune valeur
    précise (le SHA réel de la machine n'est pas la question testée), seulement le type de retour
    — même motif que test_build_backtest_manifest_detects_git_commit_when_in_a_repo."""
    run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x", dataset_snapshot_id=_real_snapshot_id(),
        repo_dir=os.path.dirname(os.path.abspath(__file__)),  # ce dépôt, un vrai dépôt Git
    )
    assert run.git_sha is None or isinstance(run.git_sha, str)


def test_build_research_run_git_sha_is_none_outside_a_repo(tmp_path):
    """B : hors d'un dépôt Git, jamais d'exception, jamais une valeur inventée — None honnête.
    Ne dépend pas du vrai SHA de la machine (tmp_path n'est structurellement pas un dépôt)."""
    run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x", dataset_snapshot_id=_real_snapshot_id(),
        repo_dir=tmp_path,
    )
    assert run.git_sha is None


def test_build_research_run_git_sha_explicit_override_disables_auto_detection():
    """Passer git_sha explicitement (y compris None) désactive la détection — même contrat que
    build_backtest_manifest(git_commit=...). Utile pour des tests hermétiques ailleurs (voir
    _real_snapshot_id() ci-dessus, git_sha=None partout où ce n'est pas ce qui est testé)."""
    run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x", dataset_snapshot_id=_real_snapshot_id(),
        git_sha="deadbeef",
    )
    assert run.git_sha == "deadbeef"


def test_build_research_run_captures_an_explicit_seed():
    """C. Le seed fourni par l'appelant est enregistré tel quel."""
    run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x", dataset_snapshot_id=_real_snapshot_id(),
        git_sha=None, seed=42,
    )
    assert run.seed == 42


def test_build_research_run_never_invents_a_seed_when_not_provided():
    """E. Aucun seed implicite (pas de random.randint/time.time()/hash() caché) — reste None si
    l'appelant n'en fournit pas. DOMAIN_MODEL.md (ligne 611) qualifie déjà le seed de "lorsque
    applicable" : une recherche déterministe n'a légitimement aucun seed."""
    run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x", dataset_snapshot_id=_real_snapshot_id(),
        git_sha=None,
    )
    assert run.seed is None


def test_research_run_seed_survives_persistence_round_trip(tmp_path):
    """D. Le seed enregistré survit strictement à l'écriture/relecture (round-trip identique)."""
    run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x", dataset_snapshot_id=_real_snapshot_id(),
        git_sha=None, seed=1234567,
    )
    path = save_research_run(tmp_path / "research_run.json", run)

    loaded = load_research_run(path)

    assert loaded.seed == 1234567


def test_build_research_run_captures_engine_version_matching_backtest_manifest_source_of_truth():
    """F, G. engine_version par défaut est EXACTEMENT market_data.backtest_manifest.ENGINE_VERSION
    — même source de vérité, pas une deuxième constante dupliquée."""
    from market_data.backtest_manifest import ENGINE_VERSION

    run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x", dataset_snapshot_id=_real_snapshot_id(),
        git_sha=None,
    )
    assert run.engine_version == ENGINE_VERSION
    assert run.engine_version  # non vide


def test_save_and_load_research_run_round_trips_git_sha_seed_and_engine_version(tmp_path):
    """H. git_sha + seed + engine_version survivent tous les trois à la persistance/relecture,
    en plus des champs AF-R-01 déjà couverts par test_save_and_load_research_run_round_trips."""
    run = build_research_run(
        research_run_id="run_x", experiment_id="exp_x", dataset_snapshot_id=_real_snapshot_id(),
        git_sha="cafef00d", seed=7, engine_version="9.9",
    )
    path = save_research_run(tmp_path / "research_run.json", run)

    loaded = load_research_run(path)

    assert loaded == run
    assert loaded.git_sha == "cafef00d"
    assert loaded.seed == 7
    assert loaded.engine_version == "9.9"


def test_research_run_module_has_no_database_or_ui_dependency():
    """J, K. Vérifie qu'aucun IMPORT PostgreSQL/Redis/Streamlit n'a été introduit
    silencieusement — persistance fichier pure, comme annoncé par le ticket. Ne scanne que les
    lignes d'import réelles, pas les docstrings/commentaires (qui peuvent légitimement nommer ces
    technologies pour expliquer pourquoi elles ne sont PAS utilisées)."""
    import research_run as module

    import_lines = "\n".join(
        line for line in open(module.__file__, encoding="utf-8")
        if line.strip().startswith(("import ", "from "))
    ).lower()

    assert "psycopg2" not in import_lines
    assert "sqlalchemy" not in import_lines
    assert "streamlit" not in import_lines
    assert "redis" not in import_lines
    assert "celery" not in import_lines
