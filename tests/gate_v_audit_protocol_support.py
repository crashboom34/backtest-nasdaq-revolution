"""Aides de test PARTAGÉES pour le protocole d'audit N-VIDE-2 / N2-a. Fixtures SYNTHÉTIQUES uniquement (`tmp_path`) : aucune donnée réelle, aucun
`FINAL_HOLDOUT`, aucun réseau. Ce module n'est pas collecté (nom sans préfixe `test_`)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import gate_v_audit_protocol as ap
import gate_v_exposure_interpreters as b3
from gate_v_exposure_scan import scan_worst_case_read_bytes
from tests.gate_v_exposure_support import LIMITS, W
from tests.gate_v_manifest_scenarios import CID, HL, SCENARIOS, realise

CAMPAIGN = b3.RootLayout.CAMPAIGN_DIR
RESULTS = b3.RootLayout.RESULTS
SPLIT = b3.RootLayout.SPLIT_PLAN_DIR

# Majorant de lecture exact d'UNE disposition (S1 + S2) : oracle recalculé à part de la formule du protocole.
ONE_GROUP_BUDGET = 2 * scan_worst_case_read_bytes(LIMITS, HL)
PROTOCOL_LIMITS = ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=3 * ONE_GROUP_BUDGET)


def campaign_spec(directory: Path, *, label: str = "camp", **changes) -> ap.AuditRootSpec:
    fields = dict(label=label, path=str(directory), layout=CAMPAIGN, expected_name=directory.name, may_be_empty=False)
    fields.update(changes)
    return ap.AuditRootSpec(**fields)


def request_for(*specs: ap.AuditRootSpec, own: str = CID, **changes) -> ap.AuditRequest:
    fields = dict(own_campaign_id=own, roots=tuple(specs), limits=LIMITS, hash_limits=HL, protocol_limits=PROTOCOL_LIMITS,
                  window_start_utc=W[0], window_end_utc=W[1], window_declared_source=ap.WindowDeclaredSource.OPERATOR_CONFIGURED)
    fields.update(changes)
    return ap.AuditRequest(**fields)


def request_of(directory: Path, **changes) -> ap.AuditRequest:
    return request_for(campaign_spec(directory), own=directory.name, **changes)


def scenario_dir(tmp_path: Path, name: str) -> Path:
    return realise(tmp_path / name, SCENARIOS[name])


def tree_digest(base: Path) -> str:
    """Empreinte d'un arbre : chemins, natures, octets (jamais d'horodatage) : preuve de lecture seule."""
    digest = hashlib.sha256()
    for directory, names, files in os.walk(base):
        names.sort()
        for name in sorted(files):
            path = Path(directory, name)
            digest.update(os.path.relpath(path, base).encode() + b"\0" + path.read_bytes() + b"\1")
        for name in names:
            digest.update(os.path.relpath(Path(directory, name), base).encode() + b"\2")
    return digest.hexdigest()
