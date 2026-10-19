"""AF-V-07 Slice E3-D — comportements du registre qui DÉPENDENT de POSIX : profil réel `POSIX_DIR_FSYNC` (fsync de fichier et de RÉPERTOIRE réels), liens symboliques, mort de
processus avec fsync réel. IGNORÉS sous Windows (`posix_only`), EXÉCUTÉS sous un hôte Linux hébergé (GitHub Actions). Registre SYNTHÉTIQUE dans `tmp_path`.

Rappel (E3-C) : `posix_dir_fsync_succeeded` dit seulement que l'appel `fsync` du répertoire a rendu 0 ; ce n'est NI une preuve de durabilité NI une qualification du système de
fichiers (tmpfs, ext4 `nobarrier` : aucune garantie). Aucune coupure d'alimentation n'est simulée. REAL = DISABLED / NOT QUALIFIED.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_registry_fixtures as fx
import atomic_json_store as e3c
import gate_v_registry_append as engine
import gate_v_registry_store as store
import gate_v_registry_views as views
from atomic_json_store import DurabilityProfile
from gate_v_registry_chain import CampaignState
from gate_v_registry_model import RecordType

pytestmark = pytest.mark.skipif(os.name != "posix", reason="comportement POSIX : exécuté sous Linux (GitHub Actions), jamais sous Windows")

_ENGINE_OWNED = ("admission_semantics_version", "registry_id", "instance_id", "seq", "prev_content_hash")


def body(record):
    return {key: value for key, value in record.items() if key not in _ENGINE_OWNED}


def posix_registry(tmp_path):
    root = tmp_path / "registry"
    store.initialize_synthetic_registry(root, registry_id=fx.REGISTRY_ID, instance_id=fx.INSTANCE_ID, durability=DurabilityProfile.POSIX_DIR_FSYNC)
    return root


def reservation_body(campaign=fx.CAMPAIGN_A, start=1, end=10):
    return body(fx.reservation(0, "0" * 64, campaign, fx.instant(start), fx.instant(end)))


def test_the_posix_profile_registry_publishes_with_real_directory_and_file_fsync(tmp_path):
    root = posix_registry(tmp_path)
    outcome = engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=3, unproven_synthetic=True)
    assert outcome.publication.durability_profile is DurabilityProfile.POSIX_DIR_FSYNC
    assert outcome.publication.state is e3c.PublicationState.PUBLISHED_DURABLE and outcome.publication.posix_dir_fsync_succeeded
    snapshot = store.read_registry(root, barrier=True)                       # barrière réelle sur admissions/
    assert snapshot.identity.durability_profile is DurabilityProfile.POSIX_DIR_FSYNC
    assert snapshot.chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.RESERVED


def test_reconfirmation_and_reuse_use_the_real_file_and_directory_fsync(tmp_path, monkeypatch):
    root = posix_registry(tmp_path)
    engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=3, unproven_synthetic=True)
    file_syncs = []
    real = e3c._fsync_slot_file
    monkeypatch.setattr(e3c, "_fsync_slot_file", lambda path: (file_syncs.append(Path(path).name), real(path))[1])
    reused = views.find_reusable_record(root, RecordType.RESERVATION, reservation_body())
    assert reused.publication.state is e3c.PublicationState.PUBLISHED_DURABLE and reused.publication.posix_dir_fsync_succeeded
    assert file_syncs == ["admission_000000.json"]


def test_the_authoritative_admission_view_reads_with_the_real_barrier(tmp_path):
    root = posix_registry(tmp_path)
    engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=3, unproven_synthetic=True)

    def admission_body(snapshot):
        entry = snapshot.chain.campaign_entry(fx.CAMPAIGN_A, RecordType.RESERVATION)
        record = fx.admission(0, "0" * 64, entry.record, entry.content_hash)
        record["reservation_seq"] = entry.seq
        return body(record)

    engine._append_record(root, admission_body, max_attempts=3, unproven_synthetic=True)
    view = views.read_authoritative_admission(root, fx.CAMPAIGN_A)
    assert view.confirmation.posix_dir_fsync_succeeded and view.campaign_state is CampaignState.ADMITTED


def test_a_symlink_slot_is_refused_and_never_followed(tmp_path):
    root = posix_registry(tmp_path)
    engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=3, unproven_synthetic=True)
    slot = root / "admissions" / "admission_000000.json"
    target = tmp_path / "outside.json"
    target.write_bytes(slot.read_bytes())
    slot.unlink()
    os.symlink(target, slot)
    with pytest.raises(store.RegistryReadError) as caught:
        store.read_registry(root, barrier=False)
    assert caught.value.failure is store.ReadFailure.NOT_REGULAR


def test_a_slot_swapped_for_a_symlink_between_the_check_and_the_open_is_not_followed(tmp_path, monkeypatch):
    # TOCTOU : même si le contrôle `lstat` est contourné, l'ouverture elle-même refuse de suivre un lien (O_NOFOLLOW) et compare la nature du fichier ouvert.
    root = posix_registry(tmp_path)
    engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=3, unproven_synthetic=True)
    slot = root / "admissions" / "admission_000000.json"
    target = tmp_path / "outside.json"
    target.write_bytes(slot.read_bytes())
    slot.unlink()
    os.symlink(target, slot)
    monkeypatch.setattr(store, "_lstat_regular", lambda path, what: None)
    with pytest.raises(store.RegistryReadError) as caught:
        store.read_registry(root, barrier=False)
    assert caught.value.failure is store.ReadFailure.SLOT_UNREADABLE


def test_a_fifo_in_place_of_a_slot_never_blocks_the_reader(tmp_path, monkeypatch):
    root = posix_registry(tmp_path)
    slot = root / "admissions" / "admission_000000.json"
    os.mkfifo(slot)
    monkeypatch.setattr(store, "_lstat_regular", lambda path, what: None)
    with pytest.raises(store.RegistryReadError):
        store.read_registry(root, barrier=False)                                  # O_NONBLOCK + vérification S_ISREG : aucun blocage


def test_a_symlinked_registry_root_is_refused(tmp_path):
    root = posix_registry(tmp_path)
    alias = tmp_path / "alias"
    os.symlink(root, alias)
    with pytest.raises(store.RegistryReadError) as caught:
        store.read_registry(alias, barrier=False)
    assert caught.value.failure is store.ReadFailure.ROOT_UNUSABLE


def test_a_symlinked_admissions_directory_is_refused(tmp_path):
    root = posix_registry(tmp_path)
    real_directory = tmp_path / "elsewhere"
    (root / "admissions").rename(real_directory)
    os.symlink(real_directory, root / "admissions")
    with pytest.raises(store.RegistryReadError) as caught:
        store.read_registry(root, barrier=False)
    assert caught.value.failure is store.ReadFailure.NOT_REGULAR
