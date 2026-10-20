"""Fixtures SYNTHÉTIQUES partagées des tests du registre E3-D (aucune donnée de marché, aucun `FINAL_HOLDOUT`, aucun accès réseau).

Les enregistrements sont de simples `dict` JSON ; les hashs sont des littéraux hexadécimaux fabriqués (`h("x")`), jamais recalculés par la même formule que le code testé.
"""

from __future__ import annotations

import hashlib

REGISTRY_ID = "synthetic-registry-1"
INSTANCE_ID = "a" * 32
CAMPAIGN_A = "gate_v_v2_" + "1" * 64
CAMPAIGN_B = "gate_v_v2_" + "2" * 64
CAMPAIGN_C = "gate_v_v2_" + "3" * 64


def h(label: str) -> str:
    """Hash littéral fabriqué (SHA-256 d'une étiquette de test) : sert uniquement de valeur de remplissage hexadécimale distincte."""
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def instant(day: int, hour: int = 0) -> str:
    return f"2031-01-{day:02d}T{hour:02d}:00:00.000000Z"


def common(record_type: str, seq: int, prev: str, *, instance_id: str = INSTANCE_ID, created_at: str = "2031-02-01T00:00:00.000000Z") -> dict:
    return {
        "admission_semantics_version": "gate_v_registry_record_v1",
        "registry_id": REGISTRY_ID,
        "instance_id": instance_id,
        "seq": seq,
        "prev_content_hash": prev,
        "record_type": record_type,
        "created_at": created_at,
    }


def campaign_fields(campaign_id: str, start: str, end: str) -> dict:
    return {
        "campaign_id": campaign_id,
        "window_start_utc": start,
        "window_end_utc": end,
        "commitment_id": "commitment-" + campaign_id[-4:],
        "commitment_content_hash": h("commitment:" + campaign_id),
        "code_identity_hash": h("code"),
        "campaign_dir_locator": "campaigns/" + campaign_id,
    }


def reservation(seq: int, prev: str, campaign_id: str = CAMPAIGN_A, start: str = None, end: str = None, **overrides) -> dict:
    record = {**common("RESERVATION", seq, prev), **campaign_fields(campaign_id, start or instant(1), end or instant(10)),
              "static_sources_digest": h("static")}
    record.update(overrides)
    return record


def admission(seq: int, prev: str, reservation_record: dict, reservation_hash: str, **overrides) -> dict:
    record = {
        **common("ADMISSION", seq, prev),
        **{key: reservation_record[key] for key in ("campaign_id", "window_start_utc", "window_end_utc", "commitment_id", "commitment_content_hash",
                                                      "code_identity_hash", "campaign_dir_locator", "static_sources_digest")},
        "overlap_projection_hash": h("projection"),
        "reservation_content_hash": reservation_hash,
        "reservation_seq": reservation_record["seq"],
        "attachment_id": "attachment-1",
        "attachment_content_hash": h("attachment"),
        "time_proof_content_hash": h("time-proof"),
        "attestation_hash": h("attestation"),
        "authorization_hash": h("authorization"),
        "attestation_observation": {"highest_slot_observed": 3},
    }
    record.update(overrides)
    return record


def consumption(seq: int, prev: str, admission_record: dict, admission_hash: str, **overrides) -> dict:
    record = {
        **common("CONSUMPTION", seq, prev),
        **{key: admission_record[key] for key in ("campaign_id", "window_start_utc", "window_end_utc", "commitment_id", "commitment_content_hash",
                                                    "code_identity_hash", "campaign_dir_locator")},
        "claim_id": h("claim-id:" + admission_record["campaign_id"]),
        "claim_content_hash": h("claim-content:" + admission_record["campaign_id"]),
        "admission_content_hash": admission_hash,
    }
    record.update(overrides)
    return record


def rebind(seq: int, prev: str, new_instance_id: str, **overrides) -> dict:
    record = {
        **common("REBIND", seq, prev, instance_id=new_instance_id),
        "old_binding_hash": h("old-binding"),
        "new_binding_hash": h("new-binding"),
        "restored_head_seq": seq - 1,
        "restored_head_content_hash": prev,
        "justification": "synthetic ceremony",
    }
    record.update(overrides)
    return record
