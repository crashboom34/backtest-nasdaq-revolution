"""Aides de test PARTAGÉES pour E3-B5 (A0) et E3-B6 (déclarations, lignée). Fixtures SYNTHÉTIQUES uniquement (`tmp_path`) : aucune
donnée réelle, aucun `FINAL_HOLDOUT`, aucun accès réseau. Ce module n'est pas collecté (nom sans préfixe `test_`)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import gate_v_exposure_interpreters as b3
import gate_v_exposure_inventory as b4
from gate_v_exposure_scan import AuditRoot, ScanLimits
from gate_v_final_holdout_protocol import OwnCampaignContext, OwnRecordStage

W = ("2026-01-01T00:00:00+00:00", "2026-04-01T00:00:00+00:00")        # fenêtre FINAL_HOLDOUT synthétique
CURRENT = "campaign_current"
CREATED_AT = "2026-10-20T08:00:00+00:00"
STAGE0 = OwnCampaignContext(CURRENT, OwnRecordStage.NO_OWN_RECORDS)

LIMITS = ScanLimits(max_roots=8, max_entries=2_000, max_depth=8, max_json_bytes=1_000_000, max_total_read_bytes=8_000_000,
                    max_json_depth=32, max_name_length=128, max_path_length=1_024, max_attempts=1)


def h(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, indent=2).encode("utf-8"))


def make_job(results: Path, name: str, start=None, end=None) -> None:
    write_json(results / name / "config_used.json",
               {"run_id": name, "strategy_name": "s", "opt_start_date": start, "opt_end_date": end})
    for file in ("archive.zip", "logs.txt"):
        (results / name / file).write_bytes(b"x")


def interpret(tmp_path: Path, *, job=("2026-02-01T00:00:00+00:00", "2026-02-10T00:00:00+00:00"), label="res", window=W):
    """Interprétation B3 RÉELLE d'une racine `results` synthétique (par défaut un job exécuté dans `W` : exposition établie)."""
    results = tmp_path / "results"
    make_job(results, "job_1", *job)
    root = b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot(label, str(results)))
    return b3.interpret_audit_roots((root,), LIMITS, holdout_window_start_utc=window[0], holdout_window_end_utc=window[1])


def registry(records=(), unreadable=(), head="a" * 64, registry_id="reg_main") -> b4.RegistryView:
    return b4.RegistryView(registry_id=registry_id, chain_head=head, records=tuple(records), unreadable_record_ids=tuple(unreadable))


def assemble(interpretation, *, reg=None, accounting=None, context=STAGE0, derived=()):
    return b4.assemble_exposure_inventory(
        interpretation, registry=registry() if reg is None else reg,
        accounting=b4.AccountingViews() if accounting is None else accounting,
        own_context=context, derived_root_labels=derived)
