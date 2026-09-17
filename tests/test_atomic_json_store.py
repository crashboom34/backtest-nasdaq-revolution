"""
tests/test_atomic_json_store.py — `save_atomic_overwrite()` (Bootstrap Autopilot, 2026-09-17).

`atomic_json_store.py` était jusqu'ici testé uniquement indirectement (via research_run.py/
dataset_split.py/validation_run.py, tous des artefacts scientifiques IMMUABLES). L'état runtime
Autopilot (`scripts/autopilot/`) est au contraire MUTABLE — chaque transition de la machine à
états doit pouvoir réécrire le même fichier. `save_atomic()` refuse explicitement l'écrasement
(comportement scientifique correct, ne doit JAMAIS changer) : ce fichier teste uniquement la
nouvelle fonction `save_atomic_overwrite()`, plus une confirmation de non-régression de
`save_atomic()` lui-même.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from atomic_json_store import load_json_tolerant, save_atomic, save_atomic_overwrite


def test_save_atomic_overwrite_writes_a_new_file(tmp_path):
    path = tmp_path / "state.json"
    save_atomic_overwrite(path, {"phase": "READY"}, "autopilot_state")
    assert load_json_tolerant(path) == {"phase": "READY"}


def test_save_atomic_overwrite_replaces_an_existing_file(tmp_path):
    """Différence essentielle avec save_atomic() : jamais de FileExistsError."""
    path = tmp_path / "state.json"
    save_atomic_overwrite(path, {"phase": "READY"}, "autopilot_state")
    save_atomic_overwrite(path, {"phase": "PLANNING"}, "autopilot_state")
    assert load_json_tolerant(path) == {"phase": "PLANNING"}


def test_save_atomic_overwrite_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "state.json"
    save_atomic_overwrite(path, {"phase": "READY"}, "autopilot_state")
    assert load_json_tolerant(path) == {"phase": "READY"}


def test_save_atomic_overwrite_never_leaves_a_temp_file_behind(tmp_path):
    path = tmp_path / "state.json"
    save_atomic_overwrite(path, {"phase": "READY"}, "autopilot_state")
    leftovers = [p for p in tmp_path.iterdir() if p.name != "state.json"]
    assert leftovers == []


def test_save_atomic_overwrite_does_not_corrupt_the_file_if_interrupted_mid_write(tmp_path, monkeypatch):
    """La substitution passe par un fichier temporaire distinct — une écriture qui échouerait ne
    doit jamais laisser `state.json` lui-même partiellement écrit. On simule l'échec en faisant
    lever une exception juste avant os.replace()."""
    import atomic_json_store as store

    path = tmp_path / "state.json"
    save_atomic_overwrite(path, {"phase": "READY"}, "autopilot_state")

    def _boom(*args, **kwargs):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(store.os, "replace", _boom)
    with pytest.raises(OSError):
        save_atomic_overwrite(path, {"phase": "PLANNING"}, "autopilot_state")

    # Le fichier "officiel" reste celui d'avant l'échec — jamais partiellement écrit.
    assert load_json_tolerant(path) == {"phase": "READY"}


def test_save_atomic_still_refuses_to_overwrite_an_existing_file(tmp_path):
    """Non-régression explicite : save_atomic() garde son comportement immuable existant, jamais
    changé par l'ajout de save_atomic_overwrite()."""
    path = tmp_path / "run.json"
    save_atomic(path, {"a": 1}, "some_record")
    with pytest.raises(FileExistsError):
        save_atomic(path, {"a": 2}, "some_record")
    assert load_json_tolerant(path) == {"a": 1}
