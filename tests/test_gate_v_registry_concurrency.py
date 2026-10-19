"""AF-V-07 Slice E3-D, tranche 5 — CONCURRENCE INTER-PROCESSUS RÉELLE et MORT DE PROCESSUS sur le registre (ADR 0025 23.10, 23.13).

Chaque scénario lance de vrais processus (`_gate_v_registry_worker.py`) derrière une barrière de départ commune. Invariants vérifiés sur la chaîne RELUE du disque : numérotation dense,
chaîne de hashs valide, AUCUNE paire de campagnes différentes aux fenêtres recouvrantes, au plus un enregistrement par campagne, tout succès annoncé est présent, tout refus est typé.
La mort brutale (`os._exit`) est démontrée pour la mort du PROCESSUS, pas pour une coupure d'alimentation (aucune coupure n'est simulée, ADR 0025 23.2). Registre SYNTHÉTIQUE, tmp_path.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_registry_fixtures as fx
import atomic_json_store as e3c
import gate_v_registry_store as store
from atomic_json_store import DurabilityProfile
from gate_v_registry_append import _append_record
from gate_v_registry_chain import CampaignState, RegistryRefusal, RegistryRefusalCode
from gate_v_registry_model import RecordType

_WORKER = Path(__file__).with_name("_gate_v_registry_worker.py")
_ENGINE_OWNED = ("admission_semantics_version", "registry_id", "instance_id", "seq", "prev_content_hash")
CAMPAIGN_D = "gate_v_v2_" + "4" * 64


def new_registry(tmp_path):
    root = tmp_path / "registry"
    store.initialize_synthetic_registry(root, registry_id=fx.REGISTRY_ID, instance_id=fx.INSTANCE_ID, durability=DurabilityProfile.SIMULATED_DURABLE)
    return root


def reservation_body(campaign, start, end):
    record = fx.reservation(0, "0" * 64, campaign, fx.instant(start), fx.instant(end))
    return {key: value for key, value in record.items() if key not in _ENGINE_OWNED}


def run_processes(root, tmp_path, specs, attempts=20):
    """Lance un processus par spécification derrière une barrière commune ; retourne [(code de sortie, résultat JSON ou None, stderr)] dans l'ordre des spécifications."""
    go = tmp_path / "go"
    processes = []
    for index, (body, fault) in enumerate(specs):
        ready = tmp_path / f"ready_{index}"
        config = {"root": str(root), "body": body, "attempts": attempts, "ready": str(ready), "go": str(go), "fault": fault}
        processes.append((ready, subprocess.Popen([sys.executable, str(_WORKER), json.dumps(config)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)))
    deadline = time.monotonic() + 120
    while not all(ready.exists() for ready, _ in processes):
        assert time.monotonic() < deadline, "un worker n'a pas démarré"
        for _, process in processes:
            assert process.poll() in (None, 0), process.communicate()[1]
        time.sleep(0.01)
    go.write_text("go")
    results = []
    for _, process in processes:
        stdout, stderr = process.communicate(timeout=180)
        lines = [line for line in stdout.splitlines() if line.strip()]
        results.append((process.returncode, json.loads(lines[-1]) if lines else None, stderr))
    return results


def assert_chain_invariants(root):
    return store.read_registry(root, barrier=False).chain           # relecture stricte : densité, hashs, unicité, recouvrement


def verdict(result):
    return "ok" if "ok" in result else result["refused"]


# ── Deux processus, même campagne ───────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("round_number", range(6))
def test_two_processes_for_the_same_campaign_publish_exactly_one_reservation(tmp_path, round_number):
    root = new_registry(tmp_path)
    body = reservation_body(fx.CAMPAIGN_A, 1, 10)
    results = run_processes(root, tmp_path, [(body, None), (body, None)])
    assert all(code == 0 for code, _, _ in results), results
    assert sorted(verdict(result) for _, result, _ in results) == ["CAMPAIGN_ALREADY_REGISTERED", "ok"]
    chain = assert_chain_invariants(root)
    assert chain.next_seq == 1 and chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.RESERVED


# ── Deux processus, même campagne : ADMISSION puis CONSUMPTION (ADR 23.20 : une seule admission, une seule consommation) ─────

def _stage_body(root, record_type):
    snapshot = store.read_registry(root, barrier=False)
    if record_type is RecordType.ADMISSION:
        entry = snapshot.chain.campaign_entry(fx.CAMPAIGN_A, RecordType.RESERVATION)
        record = fx.admission(0, "0" * 64, entry.record, entry.content_hash)
        record["reservation_seq"] = entry.seq
    else:
        entry = snapshot.chain.campaign_entry(fx.CAMPAIGN_A, RecordType.ADMISSION)
        record = fx.consumption(0, "0" * 64, entry.record, entry.content_hash)
    return {key: value for key, value in record.items() if key not in _ENGINE_OWNED}


@pytest.mark.parametrize("round_number", range(4))
def test_two_processes_for_the_same_admission_publish_exactly_one(tmp_path, round_number):
    root = new_registry(tmp_path)
    _append_record(root, lambda snapshot: reservation_body(fx.CAMPAIGN_A, 1, 10), max_attempts=3, unproven_synthetic=True)
    body = _stage_body(root, RecordType.ADMISSION)
    results = run_processes(root, tmp_path, [(body, None), (body, None)])
    assert all(code == 0 for code, _, _ in results), results
    assert sorted(verdict(result) for _, result, _ in results) == ["CAMPAIGN_ALREADY_REGISTERED", "ok"]
    chain = assert_chain_invariants(root)
    assert chain.next_seq == 2 and chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.ADMITTED


@pytest.mark.parametrize("round_number", range(4))
def test_two_processes_for_the_same_consumption_publish_exactly_one_even_with_identical_content(tmp_path, round_number):
    root = new_registry(tmp_path)
    _append_record(root, lambda snapshot: reservation_body(fx.CAMPAIGN_A, 1, 10), max_attempts=3, unproven_synthetic=True)
    _append_record(root, lambda snapshot: _stage_body(root, RecordType.ADMISSION), max_attempts=3, unproven_synthetic=True)
    body = _stage_body(root, RecordType.CONSUMPTION)
    results = run_processes(root, tmp_path, [(body, None), (body, None)])
    assert all(code == 0 for code, _, _ in results), results
    assert sorted(verdict(result) for _, result, _ in results) == ["CAMPAIGN_ALREADY_CONSUMED", "ok"]
    chain = assert_chain_invariants(root)
    assert chain.next_seq == 3 and chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.CONSUMED


# ── Deux campagnes : fenêtres recouvrantes (exactement une gagne) ───────────────────────────────────────────────────────

@pytest.mark.parametrize("name,window_a,window_b", [
    ("partiel", (1, 10), (5, 15)),
    ("identique", (1, 10), (1, 10)),
    ("inclus", (1, 10), (3, 4)),
    ("inclus inverse", (3, 4), (1, 10)),
])
@pytest.mark.parametrize("round_number", range(3))
def test_two_campaigns_with_overlapping_windows_exactly_one_wins(tmp_path, name, window_a, window_b, round_number):
    root = new_registry(tmp_path)
    results = run_processes(root, tmp_path, [(reservation_body(fx.CAMPAIGN_A, *window_a), None), (reservation_body(fx.CAMPAIGN_B, *window_b), None)])
    assert all(code == 0 for code, _, _ in results), results
    assert sorted(verdict(result) for _, result, _ in results) == [RegistryRefusalCode.OVERLAPPING_REGISTRATION.value, "ok"]
    chain = assert_chain_invariants(root)
    winners = [campaign for campaign in (fx.CAMPAIGN_A, fx.CAMPAIGN_B) if chain.campaign_state(campaign) is CampaignState.RESERVED]
    assert len(winners) == 1 and chain.next_seq == 1


# ── Deux campagnes : fenêtres disjointes ou adjacentes (les deux publient) ──────────────────────────────────────────────

@pytest.mark.parametrize("name,window_a,window_b", [("adjacentes", (1, 10), (10, 20)), ("disjointes", (1, 5), (7, 9))])
@pytest.mark.parametrize("round_number", range(4))
def test_two_campaigns_with_non_overlapping_windows_both_publish_with_dense_slots(tmp_path, name, window_a, window_b, round_number):
    root = new_registry(tmp_path)
    results = run_processes(root, tmp_path, [(reservation_body(fx.CAMPAIGN_A, *window_a), None), (reservation_body(fx.CAMPAIGN_B, *window_b), None)])
    assert all(code == 0 and "ok" in result for code, result, _ in results), results
    assert sorted(result["seq"] for _, result, _ in results) == [0, 1]
    chain = assert_chain_invariants(root)
    assert chain.next_seq == 2
    assert chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.RESERVED and chain.campaign_state(fx.CAMPAIGN_B) is CampaignState.RESERVED


# ── Quatre processus, invariants globaux ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("round_number", range(3))
def test_four_processes_keep_every_chain_invariant(tmp_path, round_number):
    root = new_registry(tmp_path)
    plans = {fx.CAMPAIGN_A: (1, 10), fx.CAMPAIGN_B: (10, 20), fx.CAMPAIGN_C: (5, 12), CAMPAIGN_D: (25, 26)}     # C recoupe A et B ; D est libre
    results = run_processes(root, tmp_path, [(reservation_body(campaign, *window), None) for campaign, window in plans.items()])
    chain = assert_chain_invariants(root)
    assert all(code == 0 for code, _, _ in results), results
    published = 0
    for campaign, (_, result, _) in zip(plans, results):
        present = chain.campaign_state(campaign) is CampaignState.RESERVED
        if "ok" in result:
            assert present
            published += 1
        else:
            assert result == {"refused": RegistryRefusalCode.OVERLAPPING_REGISTRATION.value} and not present
    assert chain.next_seq == published
    assert chain.campaign_state(CAMPAIGN_D) is CampaignState.RESERVED          # la fenêtre libre n'est jamais bloquée par les autres
    c_present = chain.campaign_state(fx.CAMPAIGN_C) is CampaignState.RESERVED
    a_and_b_present = chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.RESERVED and chain.campaign_state(fx.CAMPAIGN_B) is CampaignState.RESERVED
    assert c_present != a_and_b_present                                         # C exclut A et B, et réciproquement


# ── Mort de processus ───────────────────────────────────────────────────────────────────────────────────────────────────

def orphans(root):
    return sorted(path.name for path in (root / "admissions").iterdir() if path.name.startswith(".registry.tmp."))


def test_death_before_the_link_leaves_no_slot_and_a_harmless_orphan(tmp_path):
    root = new_registry(tmp_path)
    (code, result, _), = run_processes(root, tmp_path, [(reservation_body(fx.CAMPAIGN_A, 1, 10), "die_before_link")])
    assert code == 7 and result is None
    assert len(orphans(root)) == 1                                         # temporaire inoffensif (23.10 étape 7)
    chain = assert_chain_invariants(root)                                  # la lecture tolère l'orphelin
    assert chain.next_seq == 0 and chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.ABSENT
    assert _append_record(root, lambda snapshot: reservation_body(fx.CAMPAIGN_A, 1, 10), max_attempts=3, unproven_synthetic=True).seq == 0       # jamais enregistrée : réservation permise
    assert len(orphans(root)) == 1                                         # l'orphelin n'est jamais nettoyé en silence


def test_death_after_the_link_leaves_a_binding_slot_that_blocks_replay_and_overlap(tmp_path):
    root = new_registry(tmp_path)
    (code, result, _), = run_processes(root, tmp_path, [(reservation_body(fx.CAMPAIGN_A, 1, 10), "die_after_link")])
    assert code == 7 and result is None
    chain = assert_chain_invariants(root)
    assert chain.next_seq == 1 and chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.RESERVED       # le slot est visible, valide et binding
    assert len(orphans(root)) == 1
    with pytest.raises(RegistryRefusal) as replay:
        _append_record(root, lambda snapshot: reservation_body(fx.CAMPAIGN_A, 1, 10), max_attempts=3, unproven_synthetic=True)
    assert replay.value.code is RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED
    with pytest.raises(RegistryRefusal) as overlap:
        _append_record(root, lambda snapshot: reservation_body(fx.CAMPAIGN_B, 5, 15), max_attempts=3, unproven_synthetic=True)
    assert overlap.value.code is RegistryRefusalCode.OVERLAPPING_REGISTRATION
    assert _append_record(root, lambda snapshot: reservation_body(fx.CAMPAIGN_B, 20, 21), max_attempts=3, unproven_synthetic=True).seq == 1


def test_a_reservation_left_by_a_dead_writer_can_be_reconfirmed_by_its_exact_bytes(tmp_path):
    root = new_registry(tmp_path)
    run_processes(root, tmp_path, [(reservation_body(fx.CAMPAIGN_A, 1, 10), "die_after_link")])
    snapshot = store.read_registry(root, barrier=False)
    entry = snapshot.chain.campaign_entry(fx.CAMPAIGN_A, RecordType.RESERVATION)
    slot = snapshot.slot_path(entry.seq)
    publication = e3c.confirm_published_slot(slot, expected_sha256=hashlib.sha256(slot.read_bytes()).hexdigest(), durability=DurabilityProfile.SIMULATED_DURABLE)
    assert publication.operation is e3c.PublicationOperation.RECONFIRMED and publication.state is e3c.PublicationState.PUBLISHED_DURABLE


@pytest.mark.parametrize("round_number", range(4))
def test_a_writer_dying_after_the_link_while_another_writer_races_keeps_the_chain_dense(tmp_path, round_number):
    root = new_registry(tmp_path)
    results = run_processes(root, tmp_path, [(reservation_body(fx.CAMPAIGN_A, 1, 10), "die_after_link"), (reservation_body(fx.CAMPAIGN_B, 20, 21), None)])
    (dead_code, dead_result, _), (live_code, live_result, _) = results
    assert dead_code == 7 and dead_result is None
    assert live_code == 0 and "ok" in live_result
    chain = assert_chain_invariants(root)
    assert chain.next_seq == 2
    assert chain.campaign_state(fx.CAMPAIGN_A) is CampaignState.RESERVED and chain.campaign_state(fx.CAMPAIGN_B) is CampaignState.RESERVED
