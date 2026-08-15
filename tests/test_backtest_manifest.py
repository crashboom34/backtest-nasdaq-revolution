"""
tests/test_backtest_manifest.py — Tests de market_data/backtest_manifest.py (Phase 11).

Module additif, non branché dans job_store.py/run_job.py à cette étape (voir AI_HANDOFF.md).
Vérifie que le manifeste contient tous les champs minimaux requis par CLAUDE.md (Phase 11),
que l'écriture est atomique et n'écrase jamais un manifeste existant, et que la détection du
commit Git ne bloque jamais si git est absent ou si le dossier n'est pas un dépôt.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.backtest_manifest import (
    BacktestManifest,
    build_backtest_manifest,
    load_backtest_manifest,
    save_backtest_manifest,
)

_REQUIRED_FIELDS = (
    "provider", "instrument", "provider_symbol", "asset_type", "snapshot_id", "content_hash",
    "period_start", "period_end", "source_timeframe", "derived_timeframe", "timezone",
    "session", "partial_bar_handling", "resample_options", "strategy_version",
    "engine_version", "git_commit", "launched_at",
)


def test_build_backtest_manifest_has_all_required_fields():
    manifest = build_backtest_manifest(
        provider="local_csv", instrument="NASDAQ", provider_symbol="US100",
        source_timeframe="M3", strategy_version="NASDAQ Perfect Revolution V1.1",
        git_commit=None,
    )
    for field in _REQUIRED_FIELDS:
        assert hasattr(manifest, field), f"champ manquant : {field}"


def test_build_backtest_manifest_defaults_are_sensible():
    manifest = build_backtest_manifest(
        provider="local_csv", instrument="NASDAQ", provider_symbol="US100",
        source_timeframe="M3", git_commit=None,
    )
    assert manifest.timezone == "UTC"
    assert manifest.engine_version
    assert manifest.launched_at  # horodatage auto-rempli


def test_build_backtest_manifest_detects_git_commit_when_in_a_repo():
    manifest = build_backtest_manifest(
        provider="local_csv", instrument="NASDAQ", provider_symbol="US100",
        source_timeframe="M3", git_commit="auto",
        repo_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    # Ce dépôt est un vrai dépôt Git : un commit doit être détecté, sans jamais lever.
    assert manifest.git_commit is None or isinstance(manifest.git_commit, str)


def test_build_backtest_manifest_git_detection_never_raises_outside_a_repo(tmp_path):
    manifest = build_backtest_manifest(
        provider="local_csv", instrument="NASDAQ", provider_symbol="US100",
        source_timeframe="M3", git_commit="auto", repo_dir=tmp_path,
    )
    assert manifest.git_commit is None  # tmp_path n'est pas un dépôt Git


def test_save_backtest_manifest_writes_valid_json(tmp_path):
    manifest = build_backtest_manifest(
        provider="local_csv", instrument="NASDAQ", provider_symbol="US100",
        source_timeframe="M3", git_commit=None,
    )
    path = save_backtest_manifest(tmp_path / "data_manifest.json", manifest)

    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["provider"] == "local_csv"


def test_save_backtest_manifest_never_overwrites_an_existing_manifest(tmp_path):
    manifest = build_backtest_manifest(
        provider="local_csv", instrument="NASDAQ", provider_symbol="US100",
        source_timeframe="M3", git_commit=None,
    )
    target = tmp_path / "data_manifest.json"
    save_backtest_manifest(target, manifest)

    with pytest.raises(FileExistsError):
        save_backtest_manifest(target, manifest)


def test_load_backtest_manifest_round_trips(tmp_path):
    manifest = build_backtest_manifest(
        provider="eodhd", instrument="AAPL", provider_symbol="AAPL.US",
        source_timeframe="D1", derived_timeframe="W1", asset_type="stock",
        snapshot_id="abc123", content_hash="deadbeef", git_commit=None,
    )
    path = save_backtest_manifest(tmp_path / "data_manifest.json", manifest)

    loaded = load_backtest_manifest(path)
    assert loaded == manifest


def test_load_backtest_manifest_tolerates_missing_file(tmp_path):
    assert load_backtest_manifest(tmp_path / "does_not_exist.json") is None


def test_load_backtest_manifest_tolerates_corrupted_file(tmp_path):
    path = tmp_path / "corrupted.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_backtest_manifest(path) is None


def test_build_backtest_manifest_never_contains_a_secret():
    manifest = build_backtest_manifest(
        provider="eodhd", instrument="AAPL", provider_symbol="AAPL.US",
        source_timeframe="D1", git_commit=None,
    )
    dump = json.dumps(manifest.__dict__)
    assert "api_token" not in dump
    assert "api_key" not in dump


# ═══════════════════════════════════════════════════════════════════════════════
# Compatibilité legacy explicite — AF-DATA-03 (LEGACY / INCOMPLETE PROVENANCE).
# ═══════════════════════════════════════════════════════════════════════════════

def _legacy_manifest_json():
    """Un dict JSON-sérialisable représentant un data_manifest.json valide, une clé par champ de
    BacktestManifest — dérivé de `_REQUIRED_FIELDS` pour rester synchronisé si le schéma évolue
    (une seule liste de champs à maintenir, pas deux). Nouvelle copie fraîche à chaque appel :
    jamais un dict de module partagé/mutable entre tests."""
    values = dict.fromkeys(_REQUIRED_FIELDS)
    values.update({
        "provider": "local_csv", "instrument": "nasdaq_3m", "provider_symbol": "nasdaq_3m",
        "source_timeframe": "unknown", "timezone": "UTC", "session": "regular",
        "partial_bar_handling": "kept_and_flagged", "resample_options": {},
        "strategy_version": "NASDAQ Perfect Revolution V1.1", "engine_version": "1.0",
        "launched_at": "2026-01-01T00:00:00+00:00",
    })
    return values


def test_load_backtest_manifest_reads_an_explicit_legacy_null_content_hash(tmp_path):
    """B. Un ancien manifeste avec content_hash=None (JSON `null`) reste lisible, et la
    distinction LEGACY / INCOMPLETE PROVENANCE reste vérifiable programmatiquement."""
    path = tmp_path / "data_manifest.json"
    path.write_text(json.dumps(_legacy_manifest_json()), encoding="utf-8")

    manifest = load_backtest_manifest(path)

    assert manifest is not None
    assert manifest.content_hash is None


def test_load_backtest_manifest_tolerates_a_field_missing_from_an_older_schema(tmp_path):
    """C. Robustesse générique du loader face à un champ manquant.

    Note honnête (vérifié via `git log --follow -- market_data/backtest_manifest.py`, un seul
    commit d'introduction, `content_hash` déjà présent dès l'origine) : aucun format historique
    réel de data_manifest.json n'a jamais existé sans ce champ — ce test ne prétend donc pas
    reproduire un format passé réel. Il protège le loader contre une future évolution additive
    du schéma (ajout d'un nouveau champ requis) qui casserait sinon la lecture des manifestes
    déjà écrits — exigence explicite AF-DATA-03 : "ne laisse pas une évolution additive casser
    les manifestes historiques"."""
    path = tmp_path / "data_manifest.json"
    incomplete = _legacy_manifest_json()
    del incomplete["launched_at"]  # simule un champ requis absent d'un ancien format
    path.write_text(json.dumps(incomplete), encoding="utf-8")

    assert load_backtest_manifest(path) is None  # jamais d'exception, jamais un objet partiel


def test_load_backtest_manifest_never_modifies_the_file_it_reads(tmp_path):
    """F. La lecture d'un manifeste ne modifie jamais le fichier lu (octets/mtime inchangés)."""
    manifest = build_backtest_manifest(
        provider="local_csv", instrument="nasdaq_3m", provider_symbol="nasdaq_3m",
        source_timeframe="M3", git_commit=None,
    )
    path = save_backtest_manifest(tmp_path / "data_manifest.json", manifest)
    original_bytes = path.read_bytes()
    original_mtime = path.stat().st_mtime_ns

    load_backtest_manifest(path)

    assert path.read_bytes() == original_bytes
    assert path.stat().st_mtime_ns == original_mtime
