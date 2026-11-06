"""Support de tests de N2-b2a (diagnostic des déclarations des plans V2) : mondes SYNTHÉTIQUES en mémoire (observations S1 simulées, aucun accès disque) et fabriques d'enregistrements de plan.
Les attendus des tests sont des littéraux ou des recalculs écrits à la main dans le test ; ce module n'est pas collecté (nom sans préfixe `test_`)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gate_v_campaign_plan_v2 import GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION, compute_gate_v_campaign_id_v2
from gate_v_exposure_interpreters import RootLayout
from gate_v_exposure_scan import EntryKind

MAX_JSON = 1_000_000
RUN_HASH_1, RUN_HASH_2 = "1" * 64, "2" * 64
SPACE = "0a1b2c3d4e5f"


def hex64(number: int) -> str:
    return f"{number:064x}"


def campaign_record(index: int, **changes) -> dict:
    """Enregistrement `plan.json` minimal AUTO-COHÉRENT (les seuls champs lus par le diagnostic) : `campaign_id` recalculé depuis l'identifiant de préenregistrement et l'empreinte, sauf si fourni."""
    record = {"campaign_plan_semantics_version": GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION, "preregistration_id": hex64(0xA000 + index),
              "campaign_protocol_fingerprint": hex64(0xB000 + index), "research_run_id": "run_alpha", "research_run_content_hash": RUN_HASH_1, "strategy_name": "sma_cross",
              "base_params": {"fast": 10, "slow": 30}, "search_mode": "grid", "search_space_hash": SPACE}
    record.update({key: value for key, value in changes.items() if key != "campaign_id"})
    if "campaign_id" in changes:
        record["campaign_id"] = changes["campaign_id"]
    else:
        record["campaign_id"] = compute_gate_v_campaign_id_v2(campaign_plan_semantics_version=GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION, preregistration_id=record["preregistration_id"],
                                                              campaign_protocol_fingerprint=record["campaign_protocol_fingerprint"])
    return record


def observation(label: str, record, **changes):
    fields = dict(root_label=label, relative_path="plan.json", kind=EntryKind.FILE, anomaly=None, value_parsed=True, content_hash="ab" * 32, value=record)
    fields.update(changes)
    return SimpleNamespace(**fields)


class CountingList(list):
    """Liste d'observations qui compte ses parcours (un seul parcours de S1 est exigé)."""

    passes = 0

    def __iter__(self):
        type(self).passes += 1
        return super().__iter__()


def interpretation(observations, *, layout=RootLayout.CAMPAIGN_DIR, counting=False):
    items = CountingList(observations) if counting else list(observations)
    return SimpleNamespace(scans=(SimpleNamespace(layout=layout, scan=SimpleNamespace(observations=items)),))


def derived_of(campaigns) -> tuple:
    return tuple(sorted((label, record["campaign_id"]) for label, record in campaigns))


def world(records, *, extra_other=0, counting=False, **observation_changes):
    """`records` : liste d'enregistrements de plan ; étiquettes `c0`, `c1`… Retourne (interprétation, derived, other_campaign_count)."""
    campaigns = [(f"c{index}", record) for index, record in enumerate(records)]
    return interpretation([observation(label, record, **observation_changes) for label, record in campaigns], counting=counting), derived_of(campaigns), len(campaigns) + extra_other
