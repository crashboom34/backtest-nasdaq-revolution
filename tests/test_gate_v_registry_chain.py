"""AF-V-07 Slice E3-D, tranche 1 — vérification PURE de la chaîne du registre (ADR 0025 23.10) : numérotation dense, chaînage de hashs, `instance_id`/`REBIND`,
unicité par campagne, recouvrement des fenêtres, liens entre types, états dérivés. Aucune E/S.

Les mêmes règles servent à la lecture (`verify_chain` : une chaîne qui les viole est CASSÉE, `RegistryChainError`) et à l'évaluation d'un candidat
(`RegistryChain.with_record` : refus TYPÉ, `RegistryRefusal`). Le candidat n'est jamais publié ici.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_registry_fixtures as fx
import gate_v_registry_model as model
from gate_v_registry_chain import CampaignState, RegistryChainError, RegistryRefusal, RegistryRefusalCode, assemble_record, verify_chain
from gate_v_registry_model import RecordType

H = model.compute_record_content_hash
GENESIS = model.genesis_prev_content_hash(fx.INSTANCE_ID)


def verify(records):
    return verify_chain(records, registry_id=fx.REGISTRY_ID, genesis_instance_id=fx.INSTANCE_ID)


def reserved(campaign=fx.CAMPAIGN_A, start=None, end=None, seq=0, prev=GENESIS):
    return fx.reservation(seq, prev, campaign, start, end)


def admitted(reservation_record, seq, prev, **overrides):
    return fx.admission(seq, prev, reservation_record, H(reservation_record), **overrides)


def consumed(admission_record, seq, prev, **overrides):
    return fx.consumption(seq, prev, admission_record, H(admission_record), **overrides)


def full_campaign():
    r = reserved()
    a = admitted(r, 1, H(r))
    c = consumed(a, 2, H(a))
    return [r, a, c]


# ── Chaîne vide, états ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_empty_chain_head_is_the_genesis_hash():
    chain = verify([])
    assert chain.next_seq == 0
    assert chain.head_content_hash == GENESIS
    assert chain.current_instance_id == fx.INSTANCE_ID
    assert chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.ABSENT


def test_states_follow_reservation_admission_consumption():
    r, a, c = full_campaign()
    assert verify([r]).campaign_state(fx.CAMPAIGN_A) is CampaignState.RESERVED
    assert verify([r, a]).campaign_state(fx.CAMPAIGN_A) is CampaignState.ADMITTED
    chain = verify([r, a, c])
    assert chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.CONSUMED
    assert chain.next_seq == 3
    assert chain.head_content_hash == H(c)
    assert chain.campaign_state(fx.CAMPAIGN_B) is CampaignState.ABSENT


def test_campaign_entry_exposes_a_verified_copy_per_type():
    r, a, c = full_campaign()
    chain = verify([r, a, c])
    entry = chain.campaign_entry(fx.CAMPAIGN_A, RecordType.ADMISSION)
    assert entry.seq == 1 and entry.content_hash == H(a) and entry.record_type is RecordType.ADMISSION
    assert entry.record == a
    entry.record["attachment_id"] = "tampered"           # une copie : la chaîne reste intacte
    assert chain.campaign_entry(fx.CAMPAIGN_A, RecordType.ADMISSION).record == a
    assert chain.campaign_entry(fx.CAMPAIGN_B, RecordType.ADMISSION) is None


def test_chain_does_not_alias_the_input_records():
    r = reserved()
    chain = verify([r])
    r["campaign_dir_locator"] = "changed-after-verification"
    assert chain.campaign_entry(fx.CAMPAIGN_A, RecordType.RESERVATION).record["campaign_dir_locator"] != "changed-after-verification"


# ── Densité et chaînage ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_slot_zero_must_start_from_the_genesis_hash():
    with pytest.raises(RegistryChainError):
        verify([reserved(prev=fx.h("not-genesis"))])


def test_sequence_must_be_dense_from_zero():
    r = reserved()
    for bad in (reserved(seq=1), reserved(seq=2)):
        with pytest.raises(RegistryChainError):
            verify([bad])
    b = reserved(fx.CAMPAIGN_B, fx.instant(20), fx.instant(21), seq=2, prev=H(r))
    with pytest.raises(RegistryChainError):
        verify([r, b])                                     # trou : le slot 1 manque


def test_a_repeated_sequence_number_is_refused():
    r = reserved()
    again = reserved(fx.CAMPAIGN_B, fx.instant(20), fx.instant(21), seq=0, prev=H(r))
    with pytest.raises(RegistryChainError):
        verify([r, again])


def test_prev_content_hash_must_equal_the_hash_of_the_previous_record():
    r = reserved()
    b = reserved(fx.CAMPAIGN_B, fx.instant(20), fx.instant(21), seq=1, prev=fx.h("wrong"))
    with pytest.raises(RegistryChainError):
        verify([r, b])


def test_a_tampered_earlier_record_breaks_the_chain():
    r = reserved()
    b = reserved(fx.CAMPAIGN_B, fx.instant(20), fx.instant(21), seq=1, prev=H(r))
    r["campaign_dir_locator"] = "silently-edited"           # même une indication hors identité change le hash du contenu (23.10)
    with pytest.raises(RegistryChainError):
        verify([r, b])


def test_registry_id_must_be_constant_and_match_the_identity():
    r = reserved()
    other = {**reserved(fx.CAMPAIGN_B, fx.instant(20), fx.instant(21), seq=1, prev=H(r)), "registry_id": "another-registry"}
    with pytest.raises(RegistryChainError):
        verify([r, other])
    with pytest.raises(RegistryChainError):
        verify_chain([r], registry_id="another-registry", genesis_instance_id=fx.INSTANCE_ID)


def test_instance_id_of_slot_zero_must_equal_the_genesis_instance():
    other_instance = "b" * 32
    r = fx.reservation(0, model.genesis_prev_content_hash(other_instance))
    r["instance_id"] = other_instance
    with pytest.raises(RegistryChainError):
        verify([r])


def test_instance_id_cannot_change_without_a_rebind():
    r = reserved()
    b = reserved(fx.CAMPAIGN_B, fx.instant(20), fx.instant(21), seq=1, prev=H(r))
    b["instance_id"] = "b" * 32
    with pytest.raises(RegistryChainError):
        verify([r, b])


@pytest.mark.parametrize("position", [1, 2])
def test_the_error_reports_the_position_of_the_first_faulty_record(position):
    r = reserved()
    good_second = reserved(fx.CAMPAIGN_B, fx.instant(20), fx.instant(21), seq=1, prev=H(r))
    records = [r, good_second]
    if position == 1:
        records[1] = {**good_second, "prev_content_hash": fx.h("wrong")}            # lien rompu : refus typé
    else:
        records.append({**reserved(fx.CAMPAIGN_C, fx.instant(30), fx.instant(31), seq=2, prev=H(good_second)), "window_end_utc": "2031-01-30T00:00:00.000000Z"})    # invalide
    with pytest.raises(RegistryChainError) as caught:
        verify(records)
    assert caught.value.index == position


def test_an_invalid_record_makes_the_chain_unreadable():
    r = reserved()
    r["window_end_utc"] = r["window_start_utc"]
    with pytest.raises(RegistryChainError):
        verify([r])
    with pytest.raises(RegistryChainError):
        verify(["not a record"])


# ── REBIND ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_rebind_changes_the_instance_for_all_following_records():
    r = reserved()
    new_instance = "b" * 32
    rb = fx.rebind(1, H(r), new_instance)
    b = fx.reservation(2, H(rb), fx.CAMPAIGN_B, fx.instant(20), fx.instant(21))
    b["instance_id"] = new_instance
    chain = verify([r, rb, b])
    assert chain.current_instance_id == new_instance
    assert chain.next_seq == 3


def test_a_record_after_a_rebind_must_carry_the_new_instance():
    r = reserved()
    rb = fx.rebind(1, H(r), "b" * 32)
    b = fx.reservation(2, H(rb), fx.CAMPAIGN_B, fx.instant(20), fx.instant(21))      # ancien instance_id
    with pytest.raises(RegistryChainError):
        verify([r, rb, b])


def test_rebind_must_change_the_instance_and_cannot_open_the_chain():
    r = reserved()
    with pytest.raises(RegistryChainError):
        verify([r, fx.rebind(1, H(r), fx.INSTANCE_ID)])                   # même instance
    with pytest.raises(RegistryChainError):
        verify([fx.rebind(0, GENESIS, "b" * 32, restored_head_seq=0)])     # aucun enregistrement à restaurer


@pytest.mark.parametrize("override", [{"restored_head_seq": 5}, {"restored_head_content_hash": fx.h("other-head")}])
def test_rebind_restored_head_must_be_the_previous_record(override):
    # PROPOSÉ (P17) : la tête restaurée désigne le slot qui précède le REBIND.
    r = reserved()
    with pytest.raises(RegistryChainError):
        verify([r, fx.rebind(1, H(r), "b" * 32, **override)])


def test_a_rebind_may_never_return_to_an_intermediate_instance_either():
    r = reserved()
    rb1 = fx.rebind(1, H(r), "b" * 32)
    rb2 = fx.rebind(2, H(rb1), "c" * 32, new_binding_hash=fx.h("new-binding-2"))
    back_to_b = fx.rebind(3, H(rb2), "b" * 32, new_binding_hash=fx.h("new-binding-3"))
    with pytest.raises(RegistryChainError):
        verify([r, rb1, rb2, back_to_b])


def test_a_recursion_error_while_validating_is_a_typed_chain_error(monkeypatch):
    import gate_v_registry_chain as chain_module

    def exhausted(record):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(chain_module, "validate_registry_record", exhausted)
    with pytest.raises(RegistryChainError) as caught:
        verify([reserved()])
    assert caught.value.code is RegistryRefusalCode.INVALID_RECORD


def test_evaluating_a_candidate_never_alters_the_original_chain():
    chain = verify([reserved()])
    candidate = fx.reservation(1, chain.head_content_hash, fx.CAMPAIGN_B, fx.instant(20), fx.instant(21))
    extended = chain.with_record(candidate)
    assert extended.campaign_state(fx.CAMPAIGN_B) is CampaignState.RESERVED
    # l'ORIGINAL est intact, y compris ses index internes : la même évaluation réussit encore et ne devient pas « déjà enregistrée »
    assert chain.campaign_state(fx.CAMPAIGN_B) is CampaignState.ABSENT and chain.head_content_hash == H(reserved())
    assert chain.with_record(candidate).next_seq == 2
    overlapping = fx.reservation(1, chain.head_content_hash, fx.CAMPAIGN_C, fx.instant(20), fx.instant(21))
    assert chain.with_record(overlapping).next_seq == 2                      # la fenêtre de B n'a pas fui dans l'original


def test_a_rebind_may_never_return_to_an_instance_used_before():
    # PROPOSÉ (P22) : l'ADR dit « nouvel instance_id » ; on refuse aussi un instance_id déjà porté par la chaîne (genèse comprise).
    r = reserved()
    rb1 = fx.rebind(1, H(r), "b" * 32)
    back_to_genesis = fx.rebind(2, H(rb1), fx.INSTANCE_ID, new_binding_hash=fx.h("new-binding-2"))
    back_to_genesis["restored_head_seq"], back_to_genesis["restored_head_content_hash"] = 1, H(rb1)
    with pytest.raises(RegistryChainError):
        verify([r, rb1, back_to_genesis])
    rb2 = fx.rebind(2, H(rb1), "c" * 32, new_binding_hash=fx.h("new-binding-2"))
    assert verify([r, rb1, rb2]).current_instance_id == "c" * 32


# ── Unicité par campagne ────────────────────────────────────────────────────────────────────────────────────────────────

def test_two_reservations_of_the_same_campaign_are_a_broken_chain():
    r = reserved()
    again = reserved(seq=1, prev=H(r))                                    # contenu identique, seq différent
    with pytest.raises(RegistryChainError):
        verify([r, again])


def test_two_admissions_of_the_same_campaign_are_a_broken_chain():
    r = reserved()
    a = admitted(r, 1, H(r))
    a2 = admitted(r, 2, H(a))
    with pytest.raises(RegistryChainError):
        verify([r, a, a2])


def test_two_consumptions_of_the_same_campaign_are_a_broken_chain():
    r, a, c = full_campaign()
    c2 = consumed(a, 3, H(c))
    with pytest.raises(RegistryChainError):
        verify([r, a, c, c2])


# ── Liens entre types ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_admission_requires_a_reservation_of_the_same_campaign():
    r = reserved(fx.CAMPAIGN_B, fx.instant(20), fx.instant(21))
    stranger = reserved(fx.CAMPAIGN_A)
    a = fx.admission(1, H(r), stranger, H(stranger))                       # désigne une réservation absente de la chaîne
    with pytest.raises(RegistryChainError):
        verify([r, a])


def test_admission_must_pin_the_exact_reservation_hash():
    r = reserved()
    wrong_hash = fx.admission(1, H(r), r, fx.h("not-the-reservation"))
    with pytest.raises(RegistryChainError):
        verify([r, wrong_hash])


def test_reservation_seq_is_informative_only_as_the_adr_says():
    # ACCEPTED (23.10) : « `reservation_seq` est informatif » ; seul `reservation_content_hash` lie l'ADMISSION à sa RESERVATION.
    r = reserved()
    chain = verify([r, admitted(r, 1, H(r), reservation_seq=7)])
    assert chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.ADMITTED


@pytest.mark.parametrize("override", [{"window_end_utc": fx.instant(11)}, {"window_start_utc": fx.instant(2)}, {"commitment_content_hash": fx.h("another-commitment")}])
def test_admission_must_repeat_the_commitment_and_window_of_its_reservation(override):
    r = reserved()
    with pytest.raises(RegistryChainError):
        verify([r, admitted(r, 1, H(r), **override)])


def test_consumption_requires_the_admission_of_the_same_campaign_by_hash():
    r, a, _ = full_campaign()
    wrong = fx.consumption(2, H(a), a, fx.h("not-the-admission"))
    with pytest.raises(RegistryChainError):
        verify([r, a, wrong])
    orphan = fx.consumption(1, H(r), a, H(a))                              # aucune ADMISSION dans la chaîne
    with pytest.raises(RegistryChainError):
        verify([r, orphan])


def test_consumption_must_repeat_the_window_of_its_admission():
    # PROPOSÉ (P18) : les champs de campagne d'une CONSUMPTION égalent ceux de l'ADMISSION qu'elle consomme.
    r, a, _ = full_campaign()
    bad = consumed(a, 2, H(a), window_end_utc=fx.instant(11))
    with pytest.raises(RegistryChainError):
        verify([r, a, bad])


# ── Recouvrement ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("window,overlaps", [
    ((5, 15), True), ((1, 10), True), ((3, 4), True), ((0 + 1, 2), True), ((10, 20), False), ((20, 25), False)])
def test_overlapping_windows_of_different_campaigns_are_a_broken_chain(window, overlaps):
    r = reserved(start=fx.instant(1), end=fx.instant(10))
    b = reserved(fx.CAMPAIGN_B, fx.instant(window[0]), fx.instant(window[1]), seq=1, prev=H(r))
    if overlaps:
        with pytest.raises(RegistryChainError):
            verify([r, b])
    else:
        assert verify([r, b]).next_seq == 2


def test_an_admission_window_blocks_other_campaigns_even_without_a_claim():
    r = reserved()
    a = admitted(r, 1, H(r))
    b = reserved(fx.CAMPAIGN_B, fx.instant(5), fx.instant(6), seq=2, prev=H(a))
    with pytest.raises(RegistryChainError):
        verify([r, a, b])


def test_a_consumed_campaign_keeps_blocking_its_window_forever():
    r, a, c = full_campaign()
    b = reserved(fx.CAMPAIGN_B, fx.instant(9), fx.instant(12), seq=3, prev=H(c))
    with pytest.raises(RegistryChainError):
        verify([r, a, c, b])


def test_concurrent_campaigns_with_disjoint_windows_coexist():
    r = reserved()
    b = reserved(fx.CAMPAIGN_B, fx.instant(20), fx.instant(21), seq=1, prev=H(r))
    chain = verify([r, b])
    assert chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.RESERVED
    assert chain.campaign_state(fx.CAMPAIGN_B) is CampaignState.RESERVED


# ── Évaluation d'un candidat (refus TYPÉS, rien n'est publié) ───────────────────────────────────────────────────────────

def test_candidate_with_a_fresh_campaign_and_free_window_extends_the_chain():
    chain = verify([reserved()])
    candidate = fx.reservation(1, chain.head_content_hash, fx.CAMPAIGN_B, fx.instant(20), fx.instant(21))
    extended = chain.with_record(candidate)
    assert extended.next_seq == 2 and extended.head_content_hash == H(candidate)
    assert chain.next_seq == 1                                              # l'original est inchangé


def test_candidate_of_an_already_registered_campaign_is_refused_even_when_identical():
    chain = verify([reserved()])
    identical = reserved(seq=1, prev=chain.head_content_hash)
    with pytest.raises(RegistryRefusal) as caught:
        chain.with_record(identical)
    assert caught.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED


def test_second_admission_candidate_is_refused_as_already_registered():
    r = reserved()
    a = admitted(r, 1, H(r))
    chain = verify([r, a])
    with pytest.raises(RegistryRefusal) as caught:
        chain.with_record(admitted(r, 2, H(a)))
    assert caught.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED


def test_second_consumption_candidate_is_refused_as_already_consumed_even_when_identical():
    r, a, c = full_campaign()
    chain = verify([r, a, c])
    with pytest.raises(RegistryRefusal) as caught:
        chain.with_record(consumed(a, 3, H(c)))
    assert caught.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_CONSUMED


def test_overlapping_candidate_is_refused_with_the_overlap_code():
    chain = verify([reserved()])
    candidate = fx.reservation(1, chain.head_content_hash, fx.CAMPAIGN_B, fx.instant(5), fx.instant(15))
    with pytest.raises(RegistryRefusal) as caught:
        chain.with_record(candidate)
    assert caught.value.code is RegistryRefusalCode.OVERLAPPING_REGISTRATION


@pytest.mark.parametrize("shifted", [("2031-01-07T00:00:00.000000Z", "2031-01-20T00:00:00.000000Z"), ("2031-01-02T00:00:00.000000Z", "2031-01-12T00:00:00.000000Z")])
def test_an_admission_window_overlapping_only_its_own_reservation_is_a_predecessor_mismatch_not_an_overlap(shifted):
    # La fenêtre d'une campagne ne la « recoupe » jamais elle-même : seule une fenêtre d'une AUTRE campagne produit OVERLAPPING_REGISTRATION.
    r = reserved(start=fx.instant(5), end=fx.instant(15))
    chain = verify([r])
    candidate = fx.admission(1, chain.head_content_hash, r, H(r), window_start_utc=shifted[0], window_end_utc=shifted[1])
    with pytest.raises(RegistryRefusal) as caught:
        chain.with_record(candidate)
    assert caught.value.code is RegistryRefusalCode.PREDECESSOR_MISMATCH


def test_uniqueness_is_checked_before_overlap():
    chain = verify([reserved()])
    same_campaign_other_window = fx.reservation(1, chain.head_content_hash, fx.CAMPAIGN_A, fx.instant(5), fx.instant(15))
    with pytest.raises(RegistryRefusal) as caught:
        chain.with_record(same_campaign_other_window)
    assert caught.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED


def test_candidate_must_extend_the_head_exactly():
    chain = verify([reserved()])
    for seq, prev in ((2, chain.head_content_hash), (1, fx.h("stale-head")), (0, chain.head_content_hash)):
        candidate = fx.reservation(seq, prev, fx.CAMPAIGN_B, fx.instant(20), fx.instant(21))
        with pytest.raises(RegistryRefusal) as caught:
            chain.with_record(candidate)
        assert caught.value.code is RegistryRefusalCode.CHAIN_LINK_BROKEN


def test_candidate_admission_without_its_reservation_is_refused():
    chain = verify([reserved(fx.CAMPAIGN_B, fx.instant(20), fx.instant(21))])
    stranger = reserved(fx.CAMPAIGN_A)
    with pytest.raises(RegistryRefusal) as caught:
        chain.with_record(fx.admission(1, chain.head_content_hash, stranger, H(stranger)))
    assert caught.value.code is RegistryRefusalCode.PREDECESSOR_MISSING


def test_candidate_consumption_without_its_admission_is_refused():
    r = reserved()
    chain = verify([r])
    a = admitted(r, 1, H(r))
    with pytest.raises(RegistryRefusal) as caught:
        chain.with_record(consumed(a, 1, chain.head_content_hash))
    assert caught.value.code is RegistryRefusalCode.PREDECESSOR_MISSING


def test_candidate_with_a_mismatching_predecessor_pin_is_refused():
    r = reserved()
    chain = verify([r])
    with pytest.raises(RegistryRefusal) as caught:
        chain.with_record(fx.admission(1, chain.head_content_hash, r, fx.h("not-the-reservation")))
    assert caught.value.code is RegistryRefusalCode.PREDECESSOR_MISMATCH


# ── Équivalence avec une vérification naïve, et passage à l'échelle ─────────────────────────────────────────────────────────

def _naive_overlap_free(windows):
    """Vérité de référence par force brute : la liste de (campagne, début, fin) contient-elle une paire recouvrante de campagnes différentes ?"""
    for i, (campaign_a, start_a, end_a) in enumerate(windows):
        for campaign_b, start_b, end_b in windows[:i]:
            if campaign_a != campaign_b and start_a < end_b and start_b < end_a:
                return False
    return True


def _campaign(number):
    return "gate_v_v2_" + f"{number:064x}"


def test_the_interval_index_agrees_with_a_brute_force_check_on_random_windows():
    import random

    rng = random.Random(20261019)
    for _ in range(150):
        records, windows, prev = [], [], GENESIS
        for number in range(rng.randint(2, 9)):
            start = rng.randint(1, 25)
            end = start + rng.randint(1, 6)
            candidate = fx.reservation(len(records), prev, _campaign(number + 1), fx.instant(start), fx.instant(end))
            expected_ok = _naive_overlap_free(windows + [(_campaign(number + 1), fx.instant(start), fx.instant(end))])
            chain = verify(records)
            if expected_ok:
                extended = chain.with_record(candidate)
                records.append(candidate)
                windows.append((_campaign(number + 1), fx.instant(start), fx.instant(end)))
                prev = extended.head_content_hash
            else:
                with pytest.raises(RegistryRefusal) as caught:
                    chain.with_record(candidate)
                assert caught.value.code is RegistryRefusalCode.OVERLAPPING_REGISTRATION


def test_verifying_a_long_chain_is_not_quadratic():
    import time
    from datetime import datetime, timedelta, timezone

    base = datetime(2031, 1, 1, tzinfo=timezone.utc)
    records, prev = [], GENESIS
    for number in range(2000):
        start = base + timedelta(days=number)
        end = start + timedelta(days=1)
        record = fx.reservation(number, prev, _campaign(number + 1), start.strftime("%Y-%m-%dT%H:%M:%S.000000Z"), end.strftime("%Y-%m-%dT%H:%M:%S.000000Z"))
        records.append(record)
        prev = H(record)
    started = time.monotonic()
    chain = verify(records)
    elapsed = time.monotonic() - started
    assert chain.next_seq == 2000
    assert elapsed < 12, f"vérification de 2000 slots en {elapsed:.1f} s : la complexité n'est plus quasi linéaire"


def test_hostile_nesting_in_a_record_makes_the_chain_unreadable_with_a_typed_error():
    deep = current = {}
    for _ in range(5000):
        current["k"] = {}
        current = current["k"]
    r = reserved()
    a = admitted(r, 1, H(r), attestation_observation=deep)
    with pytest.raises(RegistryChainError) as caught:
        verify([r, a])
    assert caught.value.code is RegistryRefusalCode.INVALID_RECORD


def test_assemble_record_is_a_public_chain_function_owning_the_chain_fields():
    chain = verify([reserved()])
    body = {key: value for key, value in fx.reservation(0, GENESIS, fx.CAMPAIGN_B, fx.instant(20), fx.instant(21)).items()
            if key not in ("admission_semantics_version", "registry_id", "instance_id", "seq", "prev_content_hash")}
    record = assemble_record(chain, body)
    assert record["seq"] == 1 and record["prev_content_hash"] == chain.head_content_hash and record["instance_id"] == fx.INSTANCE_ID
    assert chain.with_record(record).next_seq == 2
    for forbidden in ({"seq": 5}, {"registry_id": "x"}, {"prev_content_hash": "0" * 64}, {"admission_semantics_version": "x"}, {"instance_id": "b" * 32}):
        with pytest.raises(ValueError):
            assemble_record(chain, {**body, **forbidden})
    for not_a_dict in (["not", "a", "dict"], None, 5, "text"):
        with pytest.raises(ValueError, match="dict"):
            assemble_record(chain, not_a_dict)


def test_an_invalid_candidate_is_a_value_error_not_a_refusal():
    chain = verify([reserved()])
    candidate = fx.reservation(1, chain.head_content_hash, fx.CAMPAIGN_B, fx.instant(20), fx.instant(21))
    candidate["registry_id"] = "bad id"
    with pytest.raises(ValueError):
        chain.with_record(candidate)
