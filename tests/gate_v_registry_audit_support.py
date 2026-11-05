"""Support de tests de N2-b1b (copie des helpers de `test_gate_v_registry_store_read.py`, qui n'est NI modifié NI déplacé) : registres SYNTHÉTIQUES dans `tmp_path`, jamais de donnée de marché,
jamais de `FINAL_HOLDOUT`, aucun accès réseau. Les enregistrements sont de simples `dict` ; les hashs de chaîne se calculent avec `compute_record_content_hash` UNIQUEMENT pour enchaîner les
fixtures (les oracles de test restent des littéraux ou des formules indépendantes écrites dans le test)."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_registry_fixtures as fx
import gate_v_registry_model as model
import gate_v_registry_store as store
from atomic_json_store import DurabilityProfile, serialize_normative_json

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


def populate(root, records):
    for seq, record in enumerate(records):
        put_slot(root, seq, record)


def three_records():
    r = fx.reservation(0, GENESIS)
    a = fx.admission(1, H(r), r, H(r))
    c = fx.consumption(2, H(a), a, H(a))
    return [r, a, c]


def orphan_name() -> str:
    return ".registry.tmp." + str(uuid.uuid4())


def put_orphans(directory, count):
    for _ in range(count):
        (directory / orphan_name()).write_bytes(b"")


def slot_sizes(records):
    return [len(serialize_normative_json(record)) for record in records]


def chain_of(*pairs):
    """Chaîne R (+ A, + C) pour une liste de (campagne, début, fin) : renvoie la liste d'enregistrements enchaînés (RESERVATION seulement par campagne)."""
    records, prev = [], GENESIS
    for seq, (campaign, start, end) in enumerate(pairs):
        record = fx.reservation(seq, prev, campaign, start, end)
        records.append(record)
        prev = H(record)
    return records


# ── Montages de N2-b1b (adaptateur, protocole) : chaîne par entrées, S1 réel par B3 v6, fenêtre propre ────────────────────────────────────────────

WN = ("2026-01-01T00:00:00.000000Z", "2026-04-01T00:00:00.000000Z")          # forme normalisée de `tests.gate_v_exposure_support.W`, écrite à la main


def foreign_id(index: int) -> str:
    return "gate_v_v2_" + f"{index:064x}"


def build_chain(entries):
    """Liste d'enregistrements enchaînés. `entries` : (genre, campagne, début, fin) avec genre R / A / C ; (« B », nouvel_instance, None, None) pour un REBIND. Après un REBIND, les enregistrements
    suivants portent la nouvelle instance."""
    records, prev, last, instance = [], GENESIS, {}, fx.INSTANCE_ID
    for seq, (kind, campaign, start, end) in enumerate(entries):
        if kind == "R":
            record = fx.reservation(seq, prev, campaign, start, end, instance_id=instance)
        elif kind == "A":
            reservation = last[(campaign, "R")]
            record = fx.admission(seq, prev, reservation, H(reservation), instance_id=instance)
        elif kind == "C":
            admission = last[(campaign, "A")]
            record = fx.consumption(seq, prev, admission, H(admission), instance_id=instance)
        elif kind == "B":
            record = fx.rebind(seq, prev, campaign)
            instance = campaign
        else:
            raise ValueError(kind)
        records.append(record)
        last[(campaign, kind)] = record
        prev = H(record)
    return records


def interpret_campaigns(pairs, *, window=None):
    """S1 RÉEL : B3 v6 sur des racines CAMPAIGN_DIR (label, dossier). Aucune donnée de marché."""
    from gate_v_exposure_interpreters import LayoutRoot, RootLayout
    from gate_v_exposure_interpreters_v6 import interpret_audit_roots_v6
    from gate_v_exposure_scan import AuditRoot
    from tests.gate_v_exposure_support import LIMITS, W
    from tests.gate_v_manifest_scenarios import HL
    start, end = window or W
    roots = tuple(LayoutRoot(RootLayout.CAMPAIGN_DIR, AuditRoot(label, str(path), False)) for label, path in pairs)
    return interpret_audit_roots_v6(roots, LIMITS, hash_limits=HL, holdout_window_start_utc=start, holdout_window_end_utc=end)
