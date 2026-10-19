"""AF-V-07 Slice E3-D, tranche 4 — PUBLICATION D'UNE `CONSUMPTION` (ADR 0025 23.10) avec un VRAI Claim d'E2 relu sur disque.

Contrat testé : le Claim est RELU par `load_final_holdout_access_claim` à chaque tentative (jamais un booléen ni un objet fourni) ; l'ADMISSION de la même campagne doit exister et son slot
est re-confirmé octet par octet ; une seconde CONSUMPTION est refusée même identique (aucune idempotence, aucune re-confirmation après l'appel qui l'a publiée). Registre `SYNTHETIC` seulement :
l'ADMISSION posée ici par le moteur interne est une fixture SANS valeur probante (preuves E3-E / E3-J non implémentées). Campagne synthétique d'E2 : aucun FINAL_HOLDOUT, aucun marché.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_claim_world as cw
import _gate_v_registry_fixtures as fx
import atomic_json_store as e3c
import gate_v_final_holdout_claim_acquisition as acq
import gate_v_registry_append as engine
import gate_v_registry_store as store
from atomic_json_store import DurabilityProfile
from gate_v_registry_chain import CampaignState, RegistryRefusal, RegistryRefusalCode
from gate_v_registry_model import RecordType

_ENGINE_OWNED = ("admission_semantics_version", "registry_id", "instance_id", "seq", "prev_content_hash")
CREATED = "2026-10-11T10:00:00+00:00"
CONSUMED_AT = "2031-03-01T00:00:00.000000Z"


@pytest.fixture(scope="module")
def base_world(tmp_path_factory):
    return cw.build_world(tmp_path_factory.mktemp("e3d") / "base")


@pytest.fixture
def world(base_world, tmp_path):
    return base_world.clone_into(tmp_path / "w")


def acquire(world):
    return acq.acquire_final_holdout_access_claim(world.campaign_dir, created_at=CREATED, **world.sources())


def body(record):
    return {key: value for key, value in record.items() if key not in _ENGINE_OWNED}


def registry_with_admission(tmp_path, campaign_id):
    root = tmp_path / "registry"
    store.initialize_synthetic_registry(root, registry_id=fx.REGISTRY_ID, instance_id=fx.INSTANCE_ID, durability=DurabilityProfile.SIMULATED_DURABLE)
    engine._append_record(root, lambda snapshot: body(fx.reservation(0, "0" * 64, campaign_id)), max_attempts=3, unproven_synthetic=True)

    def admission_body(snapshot):
        entry = snapshot.chain.campaign_entry(campaign_id, RecordType.RESERVATION)
        record = fx.admission(0, "0" * 64, entry.record, entry.content_hash)
        record["reservation_seq"] = entry.seq
        return body(record)

    engine._append_record(root, admission_body, max_attempts=3, unproven_synthetic=True)
    return root


def consume(root, world, **kwargs):
    return engine.publish_consumption(root, world.plan, world.campaign_dir, created_at=CONSUMED_AT, max_attempts=3, **kwargs)


def listing(root):
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in root.rglob("*"))


def test_nominal_consumption_records_the_claim_read_from_disk_and_the_admission_hash(tmp_path, world):
    root = registry_with_admission(tmp_path, world.plan.campaign_id)
    claim = acquire(world)
    outcome = consume(root, world)
    assert outcome.seq == 2 and outcome.record_type is RecordType.CONSUMPTION
    snapshot = store.read_registry(root, barrier=False)
    assert snapshot.chain.campaign_state(world.plan.campaign_id) is CampaignState.CONSUMED
    record = snapshot.chain.campaign_entry(world.plan.campaign_id, RecordType.CONSUMPTION).record
    admission = snapshot.chain.campaign_entry(world.plan.campaign_id, RecordType.ADMISSION)
    assert record["claim_id"] == claim.claim_id and record["claim_content_hash"] == claim.claim_content_hash
    assert record["admission_content_hash"] == admission.content_hash
    assert record["campaign_dir_locator"] == os.path.abspath(str(world.campaign_dir))
    assert record["created_at"] == CONSUMED_AT


def test_a_relative_campaign_directory_is_recorded_as_an_absolute_locator(tmp_path, world, monkeypatch):
    root = registry_with_admission(tmp_path, world.plan.campaign_id)
    acquire(world)
    monkeypatch.chdir(world.root)
    relative = os.path.relpath(world.campaign_dir, world.root)
    assert not os.path.isabs(relative)
    engine.publish_consumption(root, world.plan, relative, created_at=CONSUMED_AT, max_attempts=3)
    record = store.read_registry(root, barrier=False).chain.campaign_entry(world.plan.campaign_id, RecordType.CONSUMPTION).record
    assert os.path.isabs(record["campaign_dir_locator"]) and record["campaign_dir_locator"] == os.path.abspath(relative)


def test_the_admission_slot_is_reconfirmed_by_exact_bytes_before_consuming(tmp_path, world, monkeypatch):
    root = registry_with_admission(tmp_path, world.plan.campaign_id)
    acquire(world)
    calls = []
    real = engine.confirm_published_slot
    monkeypatch.setattr(engine, "confirm_published_slot", lambda destination, **kwargs: (calls.append((Path(destination).name, kwargs["expected_sha256"])), real(destination, **kwargs))[1])
    consume(root, world)
    slot = root / "admissions" / "admission_000001.json"
    assert calls == [("admission_000001.json", hashlib.sha256(slot.read_bytes()).hexdigest())]      # l'ADMISSION seulement, jamais la CONSUMPTION


def test_a_missing_claim_publishes_nothing(tmp_path, world):
    root = registry_with_admission(tmp_path, world.plan.campaign_id)
    before = listing(root)
    with pytest.raises(FileNotFoundError):
        consume(root, world)
    assert listing(root) == before


@pytest.mark.parametrize("garbage", [b"", b"not json", b"[]", b'{"claim_id": "x"}', b"\xef\xbb\xbf{}"])
def test_a_forged_or_unreadable_claim_publishes_nothing(tmp_path, world, garbage):
    root = registry_with_admission(tmp_path, world.plan.campaign_id)
    world.claim_path.write_bytes(garbage)
    before = listing(root)
    with pytest.raises(ValueError):
        consume(root, world)
    assert listing(root) == before


def test_without_an_admission_in_the_registry_nothing_is_consumed(tmp_path, world):
    root = tmp_path / "registry"
    store.initialize_synthetic_registry(root, registry_id=fx.REGISTRY_ID, instance_id=fx.INSTANCE_ID, durability=DurabilityProfile.SIMULATED_DURABLE)
    engine._append_record(root, lambda snapshot: body(fx.reservation(0, "0" * 64, world.plan.campaign_id)), max_attempts=3, unproven_synthetic=True)       # RESERVATION seulement
    acquire(world)
    before = listing(root)
    with pytest.raises(RegistryRefusal) as caught:
        consume(root, world)
    assert caught.value.code is RegistryRefusalCode.PREDECESSOR_MISSING
    assert listing(root) == before


def test_a_second_consumption_is_refused_even_when_identical_and_changes_nothing(tmp_path, world):
    root = registry_with_admission(tmp_path, world.plan.campaign_id)
    acquire(world)
    consume(root, world)
    before = listing(root)
    with pytest.raises(RegistryRefusal) as caught:
        consume(root, world)
    assert caught.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_CONSUMED
    assert listing(root) == before


def test_a_copied_campaign_directory_cannot_consume_or_reserve_a_second_time(tmp_path, world):
    root = registry_with_admission(tmp_path, world.plan.campaign_id)
    acquire(world)
    consume(root, world)
    copy = world.clone_into(tmp_path / "copy")                     # même campaign_id, Claim copié, autre racine
    before = listing(root)
    with pytest.raises(RegistryRefusal) as consumed:
        consume(root, copy)
    assert consumed.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_CONSUMED
    with pytest.raises(RegistryRefusal) as reserved:
        engine._append_record(root, lambda snapshot: body(fx.reservation(0, "0" * 64, copy.plan.campaign_id)), max_attempts=3, unproven_synthetic=True)
    assert reserved.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED
    assert listing(root) == before


def test_a_failing_reconfirmation_of_the_admission_publishes_nothing(tmp_path, world, monkeypatch):
    root = registry_with_admission(tmp_path, world.plan.campaign_id)
    acquire(world)
    before = listing(root)

    def mismatch(destination, **kwargs):
        raise e3c.SlotContentMismatchError("octets différents", destination)

    monkeypatch.setattr(engine, "confirm_published_slot", mismatch)
    with pytest.raises(engine.RegistryPreconditionError) as caught:
        consume(root, world)
    assert isinstance(caught.value.__cause__, e3c.SlotContentMismatchError) and caught.value.published_anything is False
    assert listing(root) == before


@pytest.mark.parametrize("error_factory", [
    lambda destination: e3c.SlotAbsentError("absent", destination),
    lambda destination: e3c.SlotContentMismatchError("octets différents", destination),
])
def test_a_failed_admission_reconfirmation_is_never_mistaken_for_a_published_consumption(tmp_path, world, monkeypatch, error_factory):
    # Les erreurs de re-confirmation de l'ADMISSION ne sont PAS celles d'une publication de CONSUMPTION : un appelant qui applique « PublishedUnconfirmed = binding »
    # aux erreurs de la primitive E3-C ne doit pas conclure qu'une CONSUMPTION existe.
    root = registry_with_admission(tmp_path, world.plan.campaign_id)
    acquire(world)
    monkeypatch.setattr(engine, "confirm_published_slot", lambda destination, **kw: (_ for _ in ()).throw(error_factory(destination)))
    with pytest.raises(engine.RegistryPreconditionError) as caught:
        consume(root, world)
    assert not isinstance(caught.value, engine.RegistryPublishedUnconfirmedError)
    assert store.read_registry(root, barrier=False).chain.campaign_state(world.plan.campaign_id) is CampaignState.ADMITTED


def test_an_unconfirmed_consumption_is_binding_and_is_never_reconfirmed_or_replayed(tmp_path, world, monkeypatch):
    root = registry_with_admission(tmp_path, world.plan.campaign_id)
    acquire(world)
    confirmed = []
    real_confirm = engine.confirm_published_slot
    monkeypatch.setattr(engine, "confirm_published_slot", lambda destination, **kw: (confirmed.append(Path(destination).name), real_confirm(destination, **kw))[1])
    barrier_calls = []

    def failing_third_barrier(directory):
        barrier_calls.append(directory)
        if len(barrier_calls) == 3:                    # reconfirmation de l'ADMISSION, barrière avant le lien, puis fsync après le lien de la CONSUMPTION
            raise OSError(5, "simulated fsync failure")

    monkeypatch.setattr(e3c, "_simulated_directory_barrier", failing_third_barrier)
    with pytest.raises(engine.RegistryPublishedUnconfirmedError) as caught:
        consume(root, world)
    assert caught.value.seq == 2 and caught.value.slot_is_binding is True
    monkeypatch.undo()
    monkeypatch.setattr(engine, "confirm_published_slot", lambda destination, **kw: pytest.fail("re-confirmation interdite après la CONSUMPTION"))
    with pytest.raises(RegistryRefusal) as again:
        consume(root, world)
    assert again.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_CONSUMED
    assert confirmed == ["admission_000001.json"]      # jamais le slot de la CONSUMPTION


def test_no_claim_or_authorisation_can_be_passed_by_the_caller(tmp_path, world):
    root = registry_with_admission(tmp_path, world.plan.campaign_id)
    acquire(world)
    for extra in ({"claim": True}, {"claim_ok": True}, {"authorized": True}, {"claim_content_hash": "0" * 64}):
        with pytest.raises(TypeError):
            consume(root, world, **extra)
    assert store.read_registry(root, barrier=False).chain.campaign_state(world.plan.campaign_id) is CampaignState.ADMITTED


def test_max_attempts_and_created_at_are_mandatory(tmp_path, world):
    root = registry_with_admission(tmp_path, world.plan.campaign_id)
    acquire(world)
    with pytest.raises(TypeError):
        engine.publish_consumption(root, world.plan, world.campaign_dir, created_at=CONSUMED_AT)           # type: ignore[call-arg]
    with pytest.raises(TypeError):
        engine.publish_consumption(root, world.plan, world.campaign_dir, max_attempts=3)                   # type: ignore[call-arg]
    with pytest.raises(ValueError):
        engine.publish_consumption(root, world.plan, world.campaign_dir, created_at="2031-03-01T00:00:00Z", max_attempts=3)     # instant non normalisé
