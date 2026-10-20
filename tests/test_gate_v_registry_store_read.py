"""AF-V-07 Slice E3-D, tranche 2 — LECTURE STRICTE du registre sur disque (ADR 0025 23.9, 23.10 étape 1) : `identity.json`, table fermée des entrées, numérotation dense,
JSON strict à point fixe d'octets, plafonds, refus des liens, échec fermé. Aucune réparation, jamais « absent » pour un fichier présent invalide, lecture seule.

Fixtures SYNTHÉTIQUES dans `tmp_path` ; les slots sont posés par de simples écritures de test (la publication par E3-C est exercée aux tranches suivantes).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_registry_fixtures as fx
import atomic_json_store as e3c
import gate_v_registry_model as model
import gate_v_registry_store as store
from atomic_json_store import DurabilityProfile, serialize_normative_json
from gate_v_registry_chain import CampaignState, RegistryChainError
from gate_v_registry_store import ReadFailure, RegistryReadError

H = model.compute_record_content_hash
GENESIS = model.genesis_prev_content_hash(fx.INSTANCE_ID)


def new_registry(tmp_path, name="registry"):
    root = tmp_path / name
    store.initialize_synthetic_registry(root, registry_id=fx.REGISTRY_ID, instance_id=fx.INSTANCE_ID, durability=DurabilityProfile.SIMULATED_DURABLE)
    return root


def put_slot(root, seq, record, *, raw=None):
    path = root / "admissions" / model.slot_file_name(seq)
    path.write_bytes(serialize_normative_json(record) if raw is None else raw)
    return path


def three_records():
    r = fx.reservation(0, GENESIS)
    a = fx.admission(1, H(r), r, H(r))
    c = fx.consumption(2, H(a), a, H(a))
    return [r, a, c]


def populate(root, records):
    for seq, record in enumerate(records):
        put_slot(root, seq, record)


def failure(root, **kwargs):
    with pytest.raises(RegistryReadError) as caught:
        store.read_registry(root, barrier=False, **kwargs)
    return caught.value.failure


# ── Initialisation et lecture nominale ──────────────────────────────────────────────────────────────────────────────────

def test_initialised_registry_reads_as_an_empty_verified_chain(tmp_path):
    root = new_registry(tmp_path)
    snapshot = store.read_registry(root, barrier=False)
    assert snapshot.identity.registry_id == fx.REGISTRY_ID
    assert snapshot.identity.instance_id == fx.INSTANCE_ID
    assert snapshot.identity.mode is model.RegistryMode.SYNTHETIC
    assert snapshot.identity.durability_profile is DurabilityProfile.SIMULATED_DURABLE
    assert snapshot.chain.next_seq == 0
    assert sorted(p.name for p in root.iterdir()) == ["admissions", "identity.json"]


def test_initialisation_never_overwrites_an_existing_registry(tmp_path):
    root = new_registry(tmp_path)
    before = (root / "identity.json").read_bytes()
    with pytest.raises(RegistryReadError) as caught:
        store.initialize_synthetic_registry(root, registry_id="other", instance_id="b" * 32, durability=DurabilityProfile.SIMULATED_DURABLE)
    assert caught.value.failure is ReadFailure.ROOT_EXISTS
    assert (root / "identity.json").read_bytes() == before


@pytest.mark.parametrize("registry_id,instance_id", [("", "a" * 32), ("bad id", "a" * 32), ("ok", "A" * 32), ("ok", "a" * 31), (None, "a" * 32)])
def test_initialisation_refuses_malformed_identifiers(tmp_path, registry_id, instance_id):
    with pytest.raises(ValueError):
        store.initialize_synthetic_registry(tmp_path / "r", registry_id=registry_id, instance_id=instance_id, durability=DurabilityProfile.SIMULATED_DURABLE)
    assert not (tmp_path / "r").exists()


def test_a_populated_chain_is_read_verified_and_in_order(tmp_path):
    root = new_registry(tmp_path)
    records = three_records()
    populate(root, records)
    snapshot = store.read_registry(root, barrier=False)
    assert snapshot.chain.next_seq == 3
    assert snapshot.chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.CONSUMED
    assert snapshot.chain.head_content_hash == H(records[2])
    assert snapshot.slot_path(1) == root / "admissions" / "admission_000001.json"


def test_reading_is_read_only(tmp_path):
    root = new_registry(tmp_path)
    populate(root, three_records())

    def fingerprint():
        return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*"))

    before = fingerprint()
    store.read_registry(root, barrier=False)
    assert fingerprint() == before


def test_barrier_follows_the_read_and_is_made_on_the_admissions_directory(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    populate(root, three_records()[:1])
    calls = []
    real_read = store._read_slot_bytes

    def spy_read(path, limit):
        calls.append(("read", path.name))
        return real_read(path, limit)

    monkeypatch.setattr(store, "_read_slot_bytes", spy_read)
    monkeypatch.setattr(store, "directory_read_barrier", lambda directory, *, durability: calls.append(("barrier", Path(directory).name, durability)))
    store.read_registry(root, barrier=True)
    assert [call[0] for call in calls] == ["read", "read", "barrier"]               # identité, slot 0, puis la barrière (lire la chaîne PUIS barrière)
    assert calls[1] == ("read", "admission_000000.json")
    assert calls[-1] == ("barrier", "admissions", DurabilityProfile.SIMULATED_DURABLE)


@pytest.mark.parametrize("flag", [1, 0, None, "yes"])
def test_the_barrier_flag_is_an_explicit_bool(tmp_path, flag):
    root = new_registry(tmp_path)
    with pytest.raises(TypeError):
        store.read_registry(root, barrier=flag)
    with pytest.raises(TypeError):
        store.read_registry(root)                                    # type: ignore[call-arg]


def test_initialisation_makes_each_directory_durable_before_publishing_the_identity(tmp_path, monkeypatch):
    events = []
    real_publish = store.publish_json_by_link
    monkeypatch.setattr(store, "directory_read_barrier", lambda directory, *, durability: events.append(("barrier", Path(directory).name, durability)))

    def spy_publish(destination, record, **kwargs):
        events.append(("publish", Path(destination).name, kwargs["naming"], kwargs["durability"]))
        return real_publish(destination, record, **kwargs)

    monkeypatch.setattr(store, "publish_json_by_link", spy_publish)
    store.initialize_synthetic_registry(tmp_path / "registry", registry_id=fx.REGISTRY_ID, instance_id=fx.INSTANCE_ID, durability=DurabilityProfile.SIMULATED_DURABLE)
    simulated = DurabilityProfile.SIMULATED_DURABLE
    assert events == [("barrier", tmp_path.name, simulated), ("barrier", tmp_path.name, simulated), ("barrier", "registry", simulated),     # préflight, puis durabilité des mkdir
                      ("publish", "identity.json", store.TempNaming.REGISTRY, simulated)]


def test_initialisation_preflights_the_platform_before_creating_anything(tmp_path, monkeypatch):
    # Un échec de plateforme (ex. POSIX_DIR_FSYNC sous Windows) ne doit laisser AUCUN résidu : le préflight précède tout mkdir.
    def not_qualified(directory, *, durability):
        raise e3c.PlatformNotQualifiedError("profil indisponible", directory)

    monkeypatch.setattr(store, "directory_read_barrier", not_qualified)
    with pytest.raises(e3c.PlatformNotQualifiedError):
        store.initialize_synthetic_registry(tmp_path / "r", registry_id=fx.REGISTRY_ID, instance_id=fx.INSTANCE_ID, durability=DurabilityProfile.POSIX_DIR_FSYNC)
    assert not (tmp_path / "r").exists()


def test_the_writer_size_cap_never_exceeds_the_reader_cap():
    assert model.MAX_RECORD_BYTES <= store.MAX_SLOT_BYTES
    assert store.MAX_SLOTS <= model.MAX_SEQ + 1


def test_an_unexpected_os_error_on_identity_is_a_typed_failure(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    real_lstat = os.lstat
    seen = {"identity": 0}

    def denied_on_the_identity_check(path, *args, **kwargs):
        if Path(path).name == "identity.json":
            seen["identity"] += 1
            if seen["identity"] >= 2:                         # le 1er lstat est celui du listage de la racine ; le 2e est celui de _read_identity
                raise PermissionError("denied")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", denied_on_the_identity_check)
    assert failure(root) is ReadFailure.ROOT_UNUSABLE


def test_initialisation_requires_a_durability_profile_member(tmp_path):
    with pytest.raises(ValueError):
        store.initialize_synthetic_registry(tmp_path / "r", registry_id=fx.REGISTRY_ID, instance_id=fx.INSTANCE_ID, durability="SIMULATED_DURABLE")
    assert not (tmp_path / "r").exists()


def test_an_identity_that_is_not_the_normative_byte_fixed_point_is_refused(tmp_path):
    root = new_registry(tmp_path)
    current = store._load_strict_json((root / "identity.json").read_bytes(), "identity")
    (root / "identity.json").write_bytes(json.dumps(current, separators=(",", ":")).encode("utf-8"))
    assert failure(root) is ReadFailure.IDENTITY_INVALID


def test_a_failing_barrier_is_a_read_failure_not_a_silent_success(tmp_path, monkeypatch):
    root = new_registry(tmp_path)

    def broken(directory, *, durability):
        raise OSError("simulated barrier failure")

    monkeypatch.setattr(store, "directory_read_barrier", broken)
    with pytest.raises(RegistryReadError) as caught:
        store.read_registry(root, barrier=True)
    assert caught.value.failure is ReadFailure.BARRIER_FAILED


# ── Racine et table fermée ──────────────────────────────────────────────────────────────────────────────────────────────

def test_missing_root_or_file_root_is_refused(tmp_path):
    assert failure(tmp_path / "absent") is ReadFailure.ROOT_UNUSABLE
    (tmp_path / "file").write_text("x")
    assert failure(tmp_path / "file") is ReadFailure.ROOT_UNUSABLE


def test_a_root_with_parent_traversal_is_refused(tmp_path):
    root = new_registry(tmp_path)
    assert failure(root / ".." / root.name) is ReadFailure.ROOT_UNUSABLE


def test_unknown_root_entry_is_refused(tmp_path):
    root = new_registry(tmp_path)
    (root / "notes.txt").write_text("stray")
    assert failure(root) is ReadFailure.UNKNOWN_ENTRY


def test_unknown_entry_in_admissions_is_refused(tmp_path):
    root = new_registry(tmp_path)
    for name in ("readme.txt", "admission_1.json", "admission_000000.json.bak", "Admission_000000.json"):
        (root / "admissions" / name).write_text("{}")
        assert failure(root) is ReadFailure.UNKNOWN_ENTRY
        (root / "admissions" / name).unlink()


def test_registry_orphan_temporaries_are_tolerated_and_ignored(tmp_path):
    root = new_registry(tmp_path)
    populate(root, three_records()[:1])
    (root / "admissions" / f".registry.tmp.{uuid.uuid4()}").write_bytes(b"half a record")
    (root / f".registry.tmp.{uuid.uuid4()}").write_bytes(b"half an identity")
    assert store.read_registry(root, barrier=False).chain.next_seq == 1


def test_exposure_temporary_names_are_not_registry_orphans(tmp_path):
    root = new_registry(tmp_path)
    (root / "admissions" / (".exposure.tmp." + "a" * 32)).write_bytes(b"x")
    assert failure(root) is ReadFailure.UNKNOWN_ENTRY


def test_a_directory_named_like_a_slot_is_refused(tmp_path):
    root = new_registry(tmp_path)
    (root / "admissions" / "admission_000000.json").mkdir()
    assert failure(root) is ReadFailure.NOT_REGULAR


def test_a_directory_named_like_a_registry_orphan_is_refused_not_tolerated(tmp_path):
    root = new_registry(tmp_path)
    (root / "admissions" / f".registry.tmp.{uuid.uuid4()}").mkdir()
    assert failure(root) is ReadFailure.NOT_REGULAR


def test_identity_json_must_be_an_ordinary_file(tmp_path):
    root = new_registry(tmp_path)
    (root / "identity.json").unlink()
    (root / "identity.json").mkdir()
    assert failure(root) is ReadFailure.NOT_REGULAR


def test_admissions_must_be_a_real_directory(tmp_path):
    root = new_registry(tmp_path)
    (root / "admissions").rmdir()
    (root / "admissions").write_text("not a directory")
    assert failure(root) is ReadFailure.NOT_REGULAR


def test_symlinks_are_refused_never_followed(tmp_path):
    root = new_registry(tmp_path)
    target = tmp_path / "elsewhere.json"
    target.write_bytes(serialize_normative_json(three_records()[0]))
    try:
        os.symlink(target, root / "admissions" / "admission_000000.json")
    except (OSError, NotImplementedError):
        pytest.skip("création de liens symboliques indisponible sur cette plateforme")
    assert failure(root) is ReadFailure.NOT_REGULAR


# ── Lecture pendant une publication concurrente ─────────────────────────────────────────────────────────────────────────

def _vanishing_lstat(monkeypatch, name):
    real_lstat = os.lstat

    def vanishing(path, *args, **kwargs):
        if Path(path).name == name:
            raise FileNotFoundError(path)
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", vanishing)


def test_a_publication_temporary_that_vanishes_during_the_listing_is_ignored(tmp_path, monkeypatch):
    # Un écrivain concurrent crée puis supprime son temporaire (23.10 étape 7) : le lecteur ne doit pas échouer pour un fichier « en vol ».
    root = new_registry(tmp_path)
    populate(root, three_records()[:1])
    temp = root / "admissions" / f".registry.tmp.{uuid.uuid4()}"
    temp.write_bytes(b"in flight")
    _vanishing_lstat(monkeypatch, temp.name)
    assert store.read_registry(root, barrier=False).chain.next_seq == 1


def test_a_slot_that_vanishes_during_the_listing_is_a_failure(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    populate(root, three_records()[:1])
    _vanishing_lstat(monkeypatch, "admission_000000.json")
    assert failure(root) is ReadFailure.SLOT_UNREADABLE


def test_a_torn_listing_is_re_observed_before_concluding_to_a_gap(tmp_path, monkeypatch):
    # Un ajout concurrent peut faire voir le slot 2 sans le slot 1 pendant UN listage (le répertoire n'est pas un instantané) : on relit, on ne répare rien.
    root = new_registry(tmp_path)
    populate(root, three_records())
    real = store._directory_entries
    calls = []

    def torn_first_time(directory, what):
        entries = real(directory, what)
        calls.append(what)
        if what == "admissions/" and calls.count("admissions/") == 1:
            return [entry for entry in entries if entry[0] != "admission_000001.json"]
        return entries

    monkeypatch.setattr(store, "_directory_entries", torn_first_time)
    assert store.read_registry(root, barrier=False).chain.next_seq == 3
    assert calls.count("admissions/") == 2


def test_a_persistent_gap_is_still_a_gap_after_a_bounded_number_of_re_listings(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    populate(root, three_records())
    (root / "admissions" / "admission_000001.json").unlink()
    real = store._directory_entries
    calls = []
    monkeypatch.setattr(store, "_directory_entries", lambda directory, what: (calls.append(what), real(directory, what))[1])
    assert failure(root) is ReadFailure.SLOT_GAP
    assert calls.count("admissions/") == store.LISTING_ATTEMPTS == 3


# ── Identité ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_missing_identity_is_refused_not_treated_as_a_new_registry(tmp_path):
    root = new_registry(tmp_path)
    (root / "identity.json").unlink()
    assert failure(root) is ReadFailure.IDENTITY_MISSING


def _rewrite_identity(root, **changes):
    current = store._load_strict_json((root / "identity.json").read_bytes(), "identity")
    current.update(changes)
    (root / "identity.json").write_bytes(serialize_normative_json(current))


@pytest.mark.parametrize("changes", [
    {"mode": "SYNTHETIC "}, {"mode": "other"}, {"registry_identity_version": "v0"}, {"registry_id": "bad id"}, {"instance_id": "A" * 32},
    {"durability_profile": "NONE"}, {"extra": 1}, {"registry_id": 5}])
def test_an_invalid_identity_is_refused(tmp_path, changes):
    root = new_registry(tmp_path)
    _rewrite_identity(root, **changes)
    assert failure(root) is ReadFailure.IDENTITY_INVALID


def test_real_mode_is_refused_with_its_own_failure(tmp_path):
    root = new_registry(tmp_path)
    _rewrite_identity(root, mode="REAL", durability_profile="POSIX_DIR_FSYNC")
    assert failure(root) is ReadFailure.MODE_REFUSED


def test_identity_missing_a_key_is_refused(tmp_path):
    root = new_registry(tmp_path)
    current = store._load_strict_json((root / "identity.json").read_bytes(), "identity")
    del current["instance_id"]
    (root / "identity.json").write_bytes(serialize_normative_json(current))
    assert failure(root) is ReadFailure.IDENTITY_INVALID


def test_identity_must_match_the_records(tmp_path):
    root = new_registry(tmp_path)
    populate(root, three_records()[:1])
    _rewrite_identity(root, registry_id="another-registry")
    with pytest.raises(RegistryChainError):
        store.read_registry(root, barrier=False)


# ── JSON strict et point fixe d'octets ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    b"\xef\xbb\xbf{}", b"\xff\xfe", b"not json", b"", b"[]", b"{", b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1.5}', b'{"a":1e3}',
    b"[" * 5000 + b"]" * 5000, b'{"a":"\\ud800"}'])
def test_strict_json_rejects_every_non_normative_input(raw):
    with pytest.raises(ValueError):
        store._load_strict_json(raw, "test")


def test_a_slot_that_is_not_the_normative_byte_fixed_point_is_refused(tmp_path):
    root = new_registry(tmp_path)
    record = three_records()[0]
    put_slot(root, 0, record, raw=json.dumps(record, separators=(",", ":")).encode("utf-8"))        # JSON valide, mais pas les octets normatifs
    assert failure(root) is ReadFailure.SLOT_INVALID


@pytest.mark.parametrize("raw", [b"\xef\xbb\xbf{}", b'{"seq":0,"seq":1}', b'{"a":1.5}', b"[]", b"", b"garbage"])
def test_an_undecodable_slot_is_refused(tmp_path, raw):
    root = new_registry(tmp_path)
    put_slot(root, 0, None, raw=raw)
    assert failure(root) is ReadFailure.SLOT_INVALID


def test_an_oversized_slot_is_refused_before_being_read_fully(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    populate(root, three_records()[:1])
    monkeypatch.setattr(store, "MAX_SLOT_BYTES", 100)
    assert failure(root) is ReadFailure.TOO_LARGE


def test_too_many_slots_are_refused(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    populate(root, three_records())
    monkeypatch.setattr(store, "MAX_SLOTS", 2)
    assert failure(root) is ReadFailure.TOO_MANY_SLOTS


def test_an_unreadable_slot_is_a_failure_never_an_absent_slot(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    populate(root, three_records())
    real_read = store._read_slot_bytes

    def deny_one(path, limit):
        if path.name == "admission_000001.json":
            raise PermissionError("denied")
        return real_read(path, limit)

    monkeypatch.setattr(store, "_read_slot_bytes", deny_one)
    assert failure(root) is ReadFailure.SLOT_UNREADABLE


# ── Densité et nommage ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_hole_in_the_sequence_is_refused(tmp_path):
    root = new_registry(tmp_path)
    populate(root, three_records())
    (root / "admissions" / "admission_000001.json").unlink()
    assert failure(root) is ReadFailure.SLOT_GAP


def test_a_chain_not_starting_at_zero_is_refused(tmp_path):
    root = new_registry(tmp_path)
    populate(root, three_records())
    (root / "admissions" / "admission_000000.json").unlink()
    assert failure(root) is ReadFailure.SLOT_GAP


def test_the_file_name_must_equal_the_record_seq(tmp_path):
    root = new_registry(tmp_path)
    records = three_records()
    put_slot(root, 0, records[0])
    put_slot(root, 1, records[2])         # le contenu porte seq 2 : le nom ment
    assert failure(root) is ReadFailure.SLOT_NAME_MISMATCH


def test_a_tampered_record_is_a_broken_chain(tmp_path):
    root = new_registry(tmp_path)
    records = three_records()
    populate(root, records)
    tampered = dict(records[0], campaign_dir_locator="edited-after-the-fact")
    put_slot(root, 0, tampered)
    with pytest.raises(RegistryChainError):
        store.read_registry(root, barrier=False)


def test_two_campaigns_with_overlapping_windows_on_disk_are_a_broken_chain(tmp_path):
    root = new_registry(tmp_path)
    r = fx.reservation(0, GENESIS)
    b = fx.reservation(1, H(r), fx.CAMPAIGN_B, fx.instant(5), fx.instant(15))
    populate(root, [r, b])
    with pytest.raises(RegistryChainError):
        store.read_registry(root, barrier=False)
