"""AF-V-07 Slice E3-D, tranche 6 — LECTURES du registre : réutilisation d'une RESERVATION / ADMISSION existante (lecture, JAMAIS publication, 23.10) et interface de lecture
AUTORITATIVE de l'ADMISSION préparée pour F1/F5.

Ce n'est PAS la vue F1 (comparaison d'exposition et de recouvrement : E3-J) ni l'évaluation F5 de l'attestation (E3-E) : les références d'attestation, d'autorisation et d'observation
du plus haut slot d'attestation restent des conteneurs OPAQUES, copiés tels quels, jamais interprétés. L'ADMISSION fabriquée ici par le moteur interne est une fixture sans valeur probante.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_registry_fixtures as fx
import atomic_json_store as e3c
import gate_v_registry_append as engine
import gate_v_registry_model as model
import gate_v_registry_store as store
import gate_v_registry_views as views
from atomic_json_store import DurabilityProfile
from gate_v_registry_chain import CampaignState, RegistryChainError, RegistryRefusal, RegistryRefusalCode
from gate_v_registry_model import RecordType

_ENGINE_OWNED = ("admission_semantics_version", "registry_id", "instance_id", "seq", "prev_content_hash")


def body(record):
    return {key: value for key, value in record.items() if key not in _ENGINE_OWNED}


def new_registry(tmp_path):
    root = tmp_path / "registry"
    store.initialize_synthetic_registry(root, registry_id=fx.REGISTRY_ID, instance_id=fx.INSTANCE_ID, durability=DurabilityProfile.SIMULATED_DURABLE)
    return root


def reservation_body(campaign=fx.CAMPAIGN_A, start=1, end=10, **overrides):
    return body(fx.reservation(0, "0" * 64, campaign, fx.instant(start), fx.instant(end), **overrides))


def admission_body(snapshot, campaign=fx.CAMPAIGN_A, **overrides):
    entry = snapshot.chain.campaign_entry(campaign, RecordType.RESERVATION)
    record = fx.admission(0, "0" * 64, entry.record, entry.content_hash, **overrides)
    record["reservation_seq"] = entry.seq
    return body(record)


def with_admission(tmp_path):
    root = new_registry(tmp_path)
    engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=3, unproven_synthetic=True)
    engine._append_record(root, lambda snapshot: admission_body(snapshot), max_attempts=3, unproven_synthetic=True)
    return root


def listing(root):
    return sorted((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*"))


# ── Réutilisation par lecture ───────────────────────────────────────────────────────────────────────────────────────────

def test_an_identical_reservation_is_reused_by_reading_and_nothing_is_written(tmp_path):
    root = new_registry(tmp_path)
    engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=3, unproven_synthetic=True)
    before = listing(root)
    candidate = reservation_body(campaign_dir_locator="elsewhere", created_at="2032-05-05T00:00:00.000000Z")       # champs non sémantiques différents
    reused = views.find_reusable_record(root, RecordType.RESERVATION, candidate)
    assert reused.entry.seq == 0 and reused.entry.record_type is RecordType.RESERVATION
    assert reused.publication.operation is e3c.PublicationOperation.RECONFIRMED and reused.publication.state is e3c.PublicationState.PUBLISHED_DURABLE
    assert listing(root) == before


def test_an_absent_campaign_has_nothing_to_reuse(tmp_path):
    root = new_registry(tmp_path)
    before = listing(root)
    assert views.find_reusable_record(root, RecordType.RESERVATION, reservation_body()) is None
    assert listing(root) == before


@pytest.mark.parametrize("override", [{"window_end_utc": fx.instant(11)}, {"static_sources_digest": fx.h("changed")}, {"commitment_content_hash": fx.h("other")}])
def test_a_different_reservation_for_the_same_campaign_is_refused_never_reused(tmp_path, override):
    root = new_registry(tmp_path)
    engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=3, unproven_synthetic=True)
    before = listing(root)
    with pytest.raises(RegistryRefusal) as caught:
        views.find_reusable_record(root, RecordType.RESERVATION, reservation_body(**override))
    assert caught.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED
    assert listing(root) == before


def test_an_identical_admission_is_reused_and_a_different_one_is_refused(tmp_path):
    root = with_admission(tmp_path)
    snapshot = store.read_registry(root, barrier=False)
    before = listing(root)
    reused = views.find_reusable_record(root, RecordType.ADMISSION, admission_body(snapshot, campaign_dir_locator="moved", created_at="2033-01-01T00:00:00.000000Z"))
    assert reused.entry.seq == 1 and reused.entry.record_type is RecordType.ADMISSION
    with pytest.raises(RegistryRefusal) as caught:
        views.find_reusable_record(root, RecordType.ADMISSION, admission_body(snapshot, attachment_id="attachment-2"))
    assert caught.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED
    assert listing(root) == before


def test_an_admission_is_not_reusable_once_the_campaign_is_consumed(tmp_path, monkeypatch):
    # ACCEPTED (23.10, « Même campaign_id, deux tentatives ») : réutilisable seulement si « aucune CONSUMPTION n'existe dans le registre pour ce campaign_id ».
    root = with_admission(tmp_path)

    def consumption_body(snapshot):
        entry = snapshot.chain.campaign_entry(fx.CAMPAIGN_A, RecordType.ADMISSION)
        return body(fx.consumption(0, "0" * 64, entry.record, entry.content_hash))

    engine._append_record(root, consumption_body, max_attempts=3, unproven_synthetic=True)
    snapshot = store.read_registry(root, barrier=False)
    reconfirmations = []
    monkeypatch.setattr(views, "confirm_published_slot", lambda *a, **k: reconfirmations.append(a))
    before = listing(root)
    with pytest.raises(RegistryRefusal) as caught:
        views.find_reusable_record(root, RecordType.ADMISSION, admission_body(snapshot))
    assert caught.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_CONSUMED
    assert reconfirmations == [] and listing(root) == before         # refusé AVANT toute re-confirmation


def test_reading_back_the_reservation_of_a_consumed_campaign_stays_allowed_it_is_only_a_read():
    # PROPOSÉ (P26) : l'ADR ne conditionne par l'absence de CONSUMPTION que la réutilisation d'une ADMISSION ; relire une RESERVATION identique n'est pas une publication,
    # l'exclusivité est portée par la CONSUMPTION. Cette permissivité est documentée, pas supposée.
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = with_admission(Path(raw))

        def consumption_body(snapshot):
            entry = snapshot.chain.campaign_entry(fx.CAMPAIGN_A, RecordType.ADMISSION)
            return body(fx.consumption(0, "0" * 64, entry.record, entry.content_hash))

        engine._append_record(root, consumption_body, max_attempts=3, unproven_synthetic=True)
        reused = views.find_reusable_record(root, RecordType.RESERVATION, reservation_body())
        assert reused is not None and reused.entry.record_type is RecordType.RESERVATION


def test_the_local_claim_and_readintent_condition_is_not_checked_here_and_says_so():
    # La condition « aucun Claim ni ReadIntent local » (23.10) relève d'E3-J (artefacts HORS registre) : la docstring le dit, la fonction ne prétend pas la vérifier.
    assert "E3-J" in views.find_reusable_record.__doc__ and "Claim" in views.find_reusable_record.__doc__


@pytest.mark.parametrize("record_type", [RecordType.CONSUMPTION, RecordType.REBIND])
def test_consumption_and_rebind_are_never_reusable(tmp_path, record_type, monkeypatch):
    root = with_admission(tmp_path)
    snapshot = store.read_registry(root, barrier=False)
    entry = snapshot.chain.campaign_entry(fx.CAMPAIGN_A, RecordType.ADMISSION)
    if record_type is RecordType.CONSUMPTION:
        valid_body = body(fx.consumption(0, "0" * 64, entry.record, entry.content_hash))       # corps COMPLET et valide : seul le TYPE doit le faire refuser
    else:
        valid_body = body(fx.rebind(1, entry.content_hash, "b" * 32))
    reads = []
    monkeypatch.setattr(views, "read_registry", lambda *a, **k: reads.append(a))
    with pytest.raises(ValueError, match="CONSUMPTION n'a aucune réutilisation"):
        views.find_reusable_record(root, record_type, valid_body)
    assert reads == []                                                    # refusé avant toute lecture du registre


def test_reuse_requires_a_successful_exact_byte_reconfirmation(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=3, unproven_synthetic=True)

    def mismatch(destination, **kwargs):
        raise e3c.SlotContentMismatchError("octets différents", destination)

    monkeypatch.setattr(views, "confirm_published_slot", mismatch)
    with pytest.raises(e3c.SlotContentMismatchError):
        views.find_reusable_record(root, RecordType.RESERVATION, reservation_body())


def test_reuse_does_not_accept_a_body_of_another_type(tmp_path):
    root = with_admission(tmp_path)
    snapshot = store.read_registry(root, barrier=False)
    complete_admission_body = admission_body(snapshot)                       # corps ADMISSION complet et valide, demandé comme une RESERVATION
    with pytest.raises(ValueError, match="doit être un dict de type RESERVATION"):
        views.find_reusable_record(root, RecordType.RESERVATION, complete_admission_body)
    with pytest.raises(ValueError, match="doit être un dict de type ADMISSION"):
        views.find_reusable_record(root, RecordType.ADMISSION, ["not", "a", "dict"])


# ── Lecture autoritative de l'ADMISSION (préparation F1 / F5) ───────────────────────────────────────────────────────────

def test_no_authoritative_admission_for_an_absent_or_only_reserved_campaign(tmp_path):
    root = new_registry(tmp_path)
    assert views.read_authoritative_admission(root, fx.CAMPAIGN_A) is None
    engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=3, unproven_synthetic=True)
    assert views.read_authoritative_admission(root, fx.CAMPAIGN_A) is None


def test_authoritative_admission_exposes_the_verified_record_and_the_opaque_references(tmp_path):
    root = with_admission(tmp_path)
    view = views.read_authoritative_admission(root, fx.CAMPAIGN_A)
    chain = store.read_registry(root, barrier=False).chain
    entry = chain.campaign_entry(fx.CAMPAIGN_A, RecordType.ADMISSION)
    assert view.campaign_id == fx.CAMPAIGN_A and view.admission_seq == 1
    assert view.admission_content_hash == entry.content_hash
    assert view.reservation_content_hash == chain.campaign_entry(fx.CAMPAIGN_A, RecordType.RESERVATION).content_hash
    assert view.window_start_utc == fx.instant(1) and view.window_end_utc == fx.instant(10)
    assert view.attestation_hash == fx.h("attestation") and view.authorization_hash == fx.h("authorization")       # épingles par hash (23.10), jamais interprétées
    assert view.attestation_observation == {"highest_slot_observed": 3}           # copié, non interprété (F5 / E3-J)
    assert view.is_probative_admission_proof is False                             # un registre SYNTHETIC n'est jamais une preuve d'admission
    assert view.chain_head_seq == chain.next_seq - 1 and view.chain_head_content_hash == chain.head_content_hash
    assert view.campaign_state is CampaignState.ADMITTED
    assert view.registry_mode.value == "SYNTHETIC"
    assert view.confirmation.operation is e3c.PublicationOperation.RECONFIRMED
    assert len(view.admission_id) == 64
    assert view.admission_id == model.compute_admission_id(entry.record) != view.admission_content_hash       # hash SÉMANTIQUE (sans seq, prev, locator, reservation_seq, created_at)


def test_authoritative_admission_returns_copies_not_aliases(tmp_path):
    root = with_admission(tmp_path)
    first = views.read_authoritative_admission(root, fx.CAMPAIGN_A)
    first.attestation_observation["highest_slot_observed"] = 99
    assert views.read_authoritative_admission(root, fx.CAMPAIGN_A).attestation_observation["highest_slot_observed"] == 3
    with pytest.raises(Exception):
        first.campaign_id = "other"                                              # dataclass gelée


def test_authoritative_admission_reflects_a_consumption(tmp_path):
    root = with_admission(tmp_path)

    def consumption_body(snapshot):
        entry = snapshot.chain.campaign_entry(fx.CAMPAIGN_A, RecordType.ADMISSION)
        return body(fx.consumption(0, "0" * 64, entry.record, entry.content_hash))

    engine._append_record(root, consumption_body, max_attempts=3, unproven_synthetic=True)
    view = views.read_authoritative_admission(root, fx.CAMPAIGN_A)
    assert view.campaign_state is CampaignState.CONSUMED and view.admission_seq == 1


def test_reading_is_after_the_chain_and_a_failing_barrier_gives_no_view(tmp_path, monkeypatch):
    root = with_admission(tmp_path)
    monkeypatch.setattr(store, "directory_read_barrier", lambda directory, *, durability: (_ for _ in ()).throw(OSError(5, "barrier down")))
    with pytest.raises(store.RegistryReadError) as caught:
        views.read_authoritative_admission(root, fx.CAMPAIGN_A)
    assert caught.value.failure is store.ReadFailure.BARRIER_FAILED


def test_a_tampered_registry_gives_no_view(tmp_path):
    root = with_admission(tmp_path)
    slot = root / "admissions" / "admission_000000.json"
    slot.write_bytes(slot.read_bytes().replace(b"campaigns/", b"tampered/"))
    with pytest.raises((RegistryChainError, store.RegistryReadError)):
        views.read_authoritative_admission(root, fx.CAMPAIGN_A)


def test_a_slot_that_cannot_be_reconfirmed_gives_no_view(tmp_path, monkeypatch):
    root = with_admission(tmp_path)

    def absent(destination, **kwargs):
        raise e3c.SlotAbsentError("absent", destination)

    monkeypatch.setattr(views, "confirm_published_slot", absent)
    with pytest.raises(e3c.SlotAbsentError):
        views.read_authoritative_admission(root, fx.CAMPAIGN_A)


def test_the_view_takes_no_caller_supplied_admission_or_proof(tmp_path):
    root = with_admission(tmp_path)
    for extra in ({"admission": {}}, {"record": {}}, {"authorized": True}, {"attestation_hash": "0" * 64}):
        with pytest.raises(TypeError):
            views.read_authoritative_admission(root, fx.CAMPAIGN_A, **extra)


@pytest.mark.parametrize("bad", ["", "gate_v_v2_short", None, 5, "x" * 74])
def test_a_malformed_campaign_id_is_refused(tmp_path, bad):
    root = with_admission(tmp_path)
    with pytest.raises(ValueError):
        views.read_authoritative_admission(root, bad)


def test_reading_publishes_nothing(tmp_path):
    root = with_admission(tmp_path)
    before = listing(root)
    views.read_authoritative_admission(root, fx.CAMPAIGN_A)
    views.find_reusable_record(root, RecordType.RESERVATION, reservation_body())
    assert listing(root) == before
