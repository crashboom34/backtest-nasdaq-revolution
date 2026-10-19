"""AF-V-07 Slice E3-D, tranche 3 — MOTEUR D'AJOUT du registre par la primitive E3-C (ADR 0025 23.10 étapes 1 à 7) : lecture de la chaîne, évaluation du candidat, publication
par lien, collision de slot (`SlotOccupiedError`) => REVENIR À L'ÉTAPE 1 et revérifier tout, nombre de tentatives borné (`REGISTRY_CONTENTION`), `PublishedUnconfirmed` binding.

`_append_record` est un moteur INTERNE (W14) : il n'est pas une API de publication métier. Il ne vérifie AUCUNE preuve d'engagement, de temps, d'attestation ni d'autorisation (E3-E / E3-J,
BLOQUÉS) : les tests l'exercent avec une fabrique de corps SYNTHÉTIQUE pour démontrer la concurrence, le recouvrement et la durabilité, jamais pour produire une admission utilisable.
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
from atomic_json_store import DurabilityProfile, PublishedUnconfirmedError, serialize_normative_json
from gate_v_registry_chain import CampaignState, RegistryRefusal, RegistryRefusalCode, assemble_record
from gate_v_registry_model import RecordType

H = model.compute_record_content_hash
_ENGINE_OWNED = ("admission_semantics_version", "registry_id", "instance_id", "seq", "prev_content_hash")


def new_registry(tmp_path):
    root = tmp_path / "registry"
    store.initialize_synthetic_registry(root, registry_id=fx.REGISTRY_ID, instance_id=fx.INSTANCE_ID, durability=DurabilityProfile.SIMULATED_DURABLE)
    return root


def reservation_body(campaign=fx.CAMPAIGN_A, start=None, end=None):
    record = fx.reservation(0, "0" * 64, campaign, start, end)
    return {key: value for key, value in record.items() if key not in _ENGINE_OWNED}


def admission_body(snapshot, campaign=fx.CAMPAIGN_A):
    entry = snapshot.chain.campaign_entry(campaign, RecordType.RESERVATION)
    record = fx.admission(0, "0" * 64, entry.record, entry.content_hash)
    record["reservation_seq"] = entry.seq
    return {key: value for key, value in record.items() if key not in _ENGINE_OWNED}


def consumption_body(snapshot, campaign=fx.CAMPAIGN_A):
    entry = snapshot.chain.campaign_entry(campaign, RecordType.ADMISSION)
    record = fx.consumption(0, "0" * 64, entry.record, entry.content_hash)
    return {key: value for key, value in record.items() if key not in _ENGINE_OWNED}


def append(root, body, attempts=3):
    return engine._append_record(root, (lambda snapshot: body) if isinstance(body, dict) else body, max_attempts=attempts, unproven_synthetic=True)


def listing(root):
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in root.rglob("*"))


# ── Publication nominale ────────────────────────────────────────────────────────────────────────────────────────────────

def test_first_append_publishes_slot_zero_with_the_normative_bytes_and_chain_fields(tmp_path):
    root = new_registry(tmp_path)
    outcome = append(root, reservation_body())
    assert outcome.seq == 0 and outcome.record_type is RecordType.RESERVATION and outcome.attempts == 1 and outcome.collisions == 0
    assert outcome.publication.state is e3c.PublicationState.PUBLISHED_DURABLE
    slot = root / "admissions" / "admission_000000.json"
    record = store._load_strict_json(slot.read_bytes(), "slot")
    assert record["seq"] == 0 and record["prev_content_hash"] == model.genesis_prev_content_hash(fx.INSTANCE_ID)
    assert record["registry_id"] == fx.REGISTRY_ID and record["instance_id"] == fx.INSTANCE_ID
    assert slot.read_bytes() == serialize_normative_json(record)
    assert outcome.content_hash == H(record)
    assert not [p for p in (root / "admissions").iterdir() if p.name.startswith(".registry.tmp.")]      # le temporaire est supprimé
    assert store.read_registry(root, barrier=False).chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.RESERVED


def test_full_lifecycle_is_chained_slot_by_slot(tmp_path):
    root = new_registry(tmp_path)
    r = append(root, reservation_body())
    a = append(root, lambda snapshot: admission_body(snapshot))
    c = append(root, lambda snapshot: consumption_body(snapshot))
    assert (r.seq, a.seq, c.seq) == (0, 1, 2)
    chain = store.read_registry(root, barrier=False).chain
    assert chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.CONSUMED
    assert chain.head_content_hash == c.content_hash
    assert chain.campaign_entry(fx.CAMPAIGN_A, RecordType.ADMISSION).record["prev_content_hash"] == r.content_hash


def test_the_chain_is_read_before_the_publication_barrier(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    events = []
    real_read, real_publish = engine.read_registry, engine.publish_json_by_link
    monkeypatch.setattr(engine, "read_registry", lambda *a, **k: (events.append("read"), real_read(*a, **k))[1])
    monkeypatch.setattr(engine, "publish_json_by_link", lambda *a, **k: (events.append("publish"), real_publish(*a, **k))[1])
    append(root, reservation_body())
    assert events == ["read", "publish"]                 # 23.10 étape 1 : lire la chaîne, PUIS la barrière (faite dans la publication E3-C)


# ── Refus : rien n'est publié ───────────────────────────────────────────────────────────────────────────────────────────

def test_a_second_reservation_of_the_same_campaign_is_refused_even_when_identical(tmp_path):
    root = new_registry(tmp_path)
    append(root, reservation_body())
    before = listing(root)
    with pytest.raises(RegistryRefusal) as caught:
        append(root, reservation_body())
    assert caught.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED
    assert listing(root) == before


def test_an_overlapping_campaign_is_refused_and_nothing_is_written(tmp_path):
    root = new_registry(tmp_path)
    append(root, reservation_body())
    before = listing(root)
    with pytest.raises(RegistryRefusal) as caught:
        append(root, reservation_body(fx.CAMPAIGN_B, fx.instant(5), fx.instant(15)))
    assert caught.value.code is RegistryRefusalCode.OVERLAPPING_REGISTRATION
    assert listing(root) == before


def test_adjacent_campaigns_both_publish(tmp_path):
    root = new_registry(tmp_path)
    append(root, reservation_body(fx.CAMPAIGN_A, fx.instant(1), fx.instant(10)))
    append(root, reservation_body(fx.CAMPAIGN_B, fx.instant(10), fx.instant(20)))
    assert store.read_registry(root, barrier=False).chain.next_seq == 2


def test_a_second_consumption_is_refused_with_no_idempotence(tmp_path):
    root = new_registry(tmp_path)
    append(root, reservation_body())
    append(root, lambda snapshot: admission_body(snapshot))
    append(root, lambda snapshot: consumption_body(snapshot))
    before = listing(root)
    with pytest.raises(RegistryRefusal) as caught:
        append(root, lambda snapshot: consumption_body(snapshot))
    assert caught.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_CONSUMED
    assert listing(root) == before


def test_a_refusal_raised_by_the_body_factory_publishes_nothing(tmp_path):
    root = new_registry(tmp_path)
    before = listing(root)

    def refusing(snapshot):
        raise RegistryRefusal(RegistryRefusalCode.PREDECESSOR_MISSING, "preuve manquante")

    with pytest.raises(RegistryRefusal):
        append(root, refusing)
    assert listing(root) == before


def test_an_invalid_body_is_a_value_error_and_publishes_nothing(tmp_path):
    root = new_registry(tmp_path)
    before = listing(root)
    for body in ({**reservation_body(), "seq": 5}, {**reservation_body(), "registry_id": "other"}, {**reservation_body(), "prev_content_hash": "0" * 64},
                 {**reservation_body(), "admission_semantics_version": "x"}, {**reservation_body(), "instance_id": "b" * 32}, {"record_type": "RESERVATION"}):
        with pytest.raises(ValueError):
            append(root, body)
    assert listing(root) == before


def test_a_factory_must_return_a_dict(tmp_path):
    root = new_registry(tmp_path)
    with pytest.raises(ValueError):
        append(root, lambda snapshot: ["not", "a", "dict"])


@pytest.mark.parametrize("attempts", [0, -1, True, 1.0, "3", None])
def test_max_attempts_must_be_an_explicit_positive_int(tmp_path, attempts):
    root = new_registry(tmp_path)
    with pytest.raises(ValueError):
        engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=attempts, unproven_synthetic=True)


def test_max_attempts_has_no_default(tmp_path):
    root = new_registry(tmp_path)
    with pytest.raises(TypeError):
        engine._append_record(root, lambda snapshot: reservation_body())          # type: ignore[call-arg]


def test_an_unreadable_registry_publishes_nothing(tmp_path):
    root = new_registry(tmp_path)
    (root / "identity.json").unlink()
    with pytest.raises(store.RegistryReadError):
        append(root, reservation_body())
    assert not list((root / "admissions").iterdir())


# ── Collision de slot : revenir à l'étape 1 ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def competitor(monkeypatch):
    """Insère UN concurrent dans le slot visé juste avant le lien de la première tentative : la vraie primitive E3-C échoue alors en `SlotOccupiedError`."""
    real_publish = engine.publish_json_by_link
    state = {"queue": [], "calls": 0}

    def wrapped(destination, record, **kwargs):
        state["calls"] += 1
        if state["queue"]:
            body = state["queue"].pop(0)
            snapshot = store.read_registry(Path(destination).parent.parent, barrier=False)
            rival = assemble_record(snapshot.chain, body)
            real_publish(snapshot.slot_path(rival["seq"]), rival, **kwargs)
        return real_publish(destination, record, **kwargs)

    monkeypatch.setattr(engine, "publish_json_by_link", wrapped)
    return state


def test_after_a_collision_the_chain_is_reloaded_and_every_precondition_is_rechecked(tmp_path, competitor):
    root = new_registry(tmp_path)
    competitor["queue"].append(reservation_body(fx.CAMPAIGN_B, fx.instant(20), fx.instant(21)))
    seen_heads = []

    def factory(snapshot):
        seen_heads.append(snapshot.chain.next_seq)
        return reservation_body()

    outcome = append(root, factory)
    assert seen_heads == [0, 1]                         # la fabrique est rappelée sur une chaîne RECHARGÉE qui contient le concurrent
    assert outcome.seq == 1 and outcome.attempts == 2 and outcome.collisions == 1
    chain = store.read_registry(root, barrier=False).chain
    assert chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.RESERVED and chain.campaign_state(fx.CAMPAIGN_B) is CampaignState.RESERVED


def test_a_collision_with_an_overlapping_rival_turns_into_a_typed_refusal_on_retry(tmp_path, competitor):
    root = new_registry(tmp_path)
    competitor["queue"].append(reservation_body(fx.CAMPAIGN_B, fx.instant(5), fx.instant(15)))
    with pytest.raises(RegistryRefusal) as caught:
        append(root, reservation_body())
    assert caught.value.code is RegistryRefusalCode.OVERLAPPING_REGISTRATION
    chain = store.read_registry(root, barrier=False).chain
    assert chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.ABSENT and chain.next_seq == 1       # le slot du rival reste binding, le nôtre n'est pas publié


def test_a_collision_with_the_same_campaign_is_never_treated_as_success(tmp_path, competitor):
    root = new_registry(tmp_path)
    competitor["queue"].append(reservation_body())        # deux appelants pour la MÊME campagne, contenu identique
    with pytest.raises(RegistryRefusal) as caught:
        append(root, reservation_body())
    assert caught.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED
    assert store.read_registry(root, barrier=False).chain.next_seq == 1


def test_contention_is_bounded_and_publishes_nothing_of_ours(tmp_path, competitor):
    root = new_registry(tmp_path)
    # Un rival différent et disjoint à CHAQUE tentative : la contention ne s'épuise jamais.
    for day in range(1, 4):
        competitor["queue"].append(reservation_body("gate_v_v2_" + str(day + 3) * 64, fx.instant(10 + 2 * day), fx.instant(11 + 2 * day)))
    with pytest.raises(engine.RegistryContentionError) as caught:
        append(root, reservation_body(), attempts=3)
    assert caught.value.attempts == 3
    assert competitor["calls"] == 3
    chain = store.read_registry(root, barrier=False).chain
    assert chain.next_seq == 3 and chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.ABSENT


# ── PublishedUnconfirmed : binding, jamais rejoué ───────────────────────────────────────────────────────────────────────

def test_an_unconfirmed_publication_is_binding_and_never_retried(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    barrier_calls = []

    def failing_second_barrier(directory):
        barrier_calls.append(directory)
        if len(barrier_calls) == 2:                     # 1re : barrière de lecture ; 2e : fsync après le lien
            raise OSError(5, "simulated fsync failure")

    monkeypatch.setattr(e3c, "_simulated_directory_barrier", failing_second_barrier)
    with pytest.raises(engine.RegistryPublishedUnconfirmedError) as caught:
        append(root, reservation_body(), attempts=5)
    assert caught.value.seq == 0 and caught.value.slot_is_binding is True and caught.value.replay_safe is False
    assert isinstance(caught.value.__cause__, PublishedUnconfirmedError)
    assert len(barrier_calls) == 2                      # aucune nouvelle tentative
    monkeypatch.undo()
    chain = store.read_registry(root, barrier=False).chain
    assert chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.RESERVED          # le slot est visible et lié
    with pytest.raises(RegistryRefusal) as refused:
        append(root, reservation_body())
    assert refused.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED


def test_a_failure_before_the_link_publishes_nothing_and_is_not_swallowed(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    monkeypatch.setattr(e3c, "_simulated_directory_barrier", lambda directory: (_ for _ in ()).throw(OSError(5, "barrier down")))
    with pytest.raises(e3c.PublicationNotStartedError):
        append(root, reservation_body())
    monkeypatch.undo()
    assert store.read_registry(root, barrier=False).chain.next_seq == 0
    assert append(root, reservation_body()).seq == 0         # le rejeu est permis ensuite, avec une nouvelle lecture


def test_the_registry_durability_profile_and_registry_naming_reach_the_primitive(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    identity = store._load_strict_json((root / "identity.json").read_bytes(), "identity")
    identity["durability_profile"] = "POSIX_DIR_FSYNC"                    # lisible partout ; la primitive POSIX n'est PAS appelée (arrêt avant)
    (root / "identity.json").write_bytes(serialize_normative_json(identity))
    captured = {}

    def stop(destination, record, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop avant toute écriture")

    monkeypatch.setattr(engine, "publish_json_by_link", stop)
    with pytest.raises(RuntimeError):
        append(root, reservation_body())
    assert captured["durability"] is DurabilityProfile.POSIX_DIR_FSYNC and captured["naming"] is e3c.TempNaming.REGISTRY


@pytest.mark.parametrize("flag", [False, 1, None, "yes"])
def test_the_engine_requires_the_explicit_acknowledgement_that_no_proof_is_verified(tmp_path, flag):
    # Garde de conception (W14, PROPOSÉ) : le moteur ne vérifie AUCUNE preuve (E3-E / E3-J) ; l'appelant le reconnaît explicitement, sans valeur par défaut.
    root = new_registry(tmp_path)
    before = listing(root)
    with pytest.raises(ValueError):
        engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=3, unproven_synthetic=flag)
    with pytest.raises(TypeError):
        engine._append_record(root, lambda snapshot: reservation_body(), max_attempts=3)               # type: ignore[call-arg]
    assert listing(root) == before


def test_the_writer_proves_the_reader_will_reread_the_exact_bytes_before_linking(tmp_path, monkeypatch):
    # E3-C : un écrivain de slot dense et irréparable doit prouver, AVANT la publication, que son lecteur relira ces octets.
    root = new_registry(tmp_path)
    monkeypatch.setattr(store, "MAX_SLOT_BYTES", 300)                       # le lecteur refuserait ce slot
    before = listing(root)
    with pytest.raises(engine.RegistryUnreadableRecordError):
        append(root, reservation_body())
    assert listing(root) == before


def test_the_writer_refuses_a_slot_beyond_the_reader_slot_count(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    append(root, reservation_body(fx.CAMPAIGN_A, fx.instant(1), fx.instant(2)))
    monkeypatch.setattr(store, "MAX_SLOTS", 1)                              # le lecteur refuserait une chaîne de 2 slots
    before = listing(root)
    with pytest.raises(engine.RegistryUnreadableRecordError):
        append(root, reservation_body(fx.CAMPAIGN_B, fx.instant(20), fx.instant(21)))
    assert listing(root) == before


def test_the_writer_refuses_a_slot_whose_strict_reread_would_differ(tmp_path, monkeypatch):
    root = new_registry(tmp_path)
    real = store._load_strict_json
    monkeypatch.setattr(store, "_load_strict_json", lambda raw, what: {**real(raw, what), "seq": 99} if what.startswith("slot ") else real(raw, what))
    before = listing(root)
    with pytest.raises(engine.RegistryUnreadableRecordError):
        append(root, reservation_body())
    assert listing(root) == before


def test_the_published_bytes_are_exactly_what_the_reader_reads_back(tmp_path):
    root = new_registry(tmp_path)
    outcome = append(root, reservation_body())
    snapshot = store.read_registry(root, barrier=False)
    assert snapshot.chain.head_content_hash == outcome.content_hash and snapshot.chain.next_seq == 1


def test_the_engine_is_not_part_of_the_public_surface():
    assert not hasattr(engine, "append_record")
    assert "_append_record" in dir(engine)
