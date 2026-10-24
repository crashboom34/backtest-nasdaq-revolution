"""AF-V-07 Slice E3-B3 — interprètes de sources (rattachement observation ↔ règle, findings, ancres, complétude).

Arborescences SYNTHÉTIQUES dans `tmp_path` uniquement : aucune donnée réelle, aucun `FINAL_HOLDOUT`, aucun accès réseau.
Contrat : ADR 0025 23.3, 23.11 étape 1, 23.13, 23.27.1-23.27.3 ; design E3-B (AI_HANDOFF.md §44.1, §45) ; préconditions B3 (§47).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import gate_v_exposure_interpreters as b3
from gate_v_exposure_scan import AuditRoot, ScanLimits, scan_audit_roots
from gate_v_final_holdout_protocol import OverlapVerdict, SourceKind, SourceStatus, UnresolvedCause

W = ("2026-01-01T00:00:00+00:00", "2026-04-01T00:00:00+00:00")  # fenêtre FINAL_HOLDOUT synthétique

LIMITS = ScanLimits(max_roots=8, max_entries=2_000, max_depth=8, max_json_bytes=1_000_000, max_total_read_bytes=8_000_000,
                    max_json_depth=32, max_name_length=128, max_path_length=1_024, max_attempts=1)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, indent=2).encode("utf-8"))


def job_config(start=None, end=None, **extra) -> dict:
    return {"run_id": "job_x", "strategy_name": "s", "opt_start_date": start, "opt_end_date": end, **extra}


def make_job(results: Path, name: str, config: dict, inert=("archive.zip", "logs.txt")) -> None:
    write_json(results / name / "config_used.json", config)
    for file in inert:
        (results / name / file).write_bytes(b"x")


def results_root(path: Path, label: str = "res") -> b3.LayoutRoot:
    return b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot(label, str(path)))


def interpret(*roots, window=W):
    return b3.interpret_audit_roots(roots, LIMITS, holdout_window_start_utc=window[0], holdout_window_end_utc=window[1])


def finding(result, source_id):
    matches = [f for f in result.findings if f.source_id == source_id]
    assert len(matches) == 1, [f.source_id for f in result.findings]
    return matches[0]


# ── Tranche 1 : traceur — un job sans bornes reste UNRESOLVED, le scan est épinglé ──────────────────────────────

def test_job_without_bounds_is_unresolved_window_unknown_and_scan_is_pinned(tmp_path):
    results = tmp_path / "results"
    make_job(results, "job_20260101_000000_ab12", job_config())
    result = interpret(results_root(results))
    job = finding(result, "job.config:res/job_20260101_000000_ab12/config_used.json")
    assert job.source_kind is SourceKind.JOB_EXECUTION and job.status is SourceStatus.UNRESOLVED
    assert job.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN and job.overlap is OverlapVerdict.UNKNOWN
    assert len(result.findings) == 1                       # les fichiers inertes du job ne sont pas des sources
    (scan,) = result.scans
    assert scan.layout is b3.RootLayout.RESULTS and scan.scan.limits is LIMITS and scan.scan.hooks_used is False
    direct = scan_audit_roots((AuditRoot("res", str(results)),), b3.source_rules(b3.RootLayout.RESULTS), LIMITS)
    assert scan.scan.rules_digest == direct.rules_digest   # la table EXACTE de B3 est épinglée
    assert [r.may_be_empty for r in scan.scan.roots] == [False]


# ── Tranche 2 : jobs — fenêtre accessible au calcul et asymétrie des preuves (ADR 0025 23.30.1, B3 v2) ──────────
# `X` = fenêtre d'exécution configurée : `[opt_start_date, opt_end_date)` exacte pour des bornes ISO-T aware (borne exclusive de
# `optimizer.resolve_execution_window`). Elle ÉTABLIT une exposition si elle recoupe `W` (P1) ; elle ne l'exclut JAMAIS : le job charge
# tout son `data_file` et le moteur laisse tout l'amont visible pour `prepare()`. Aucune preuve d'exclusion n'existe : sans P1 ni P2,
# l'absence d'exposition est NON ÉTABLIE (`UNRESOLVED`), jamais `NO_OVERLAP`.

import hashlib  # noqa: E402

JOB_ID = "job.config:res/job_1/config_used.json"


def one_job(tmp_path, config):
    results = tmp_path / "results"
    make_job(results, "job_1", config)
    return finding(interpret(results_root(results)), JOB_ID), results / "job_1" / "config_used.json"


def evidence_of(result, source_id):
    matches = [e for e in result.exposure_evidence if e.source_id == source_id]
    assert len(matches) == 1, [e.source_id for e in result.exposure_evidence]
    return matches[0]


def test_job_executed_before_w_without_exclusion_proof_is_never_no_overlap(tmp_path):
    """Q-6 : un job exécuté avant `W` a pu lire `W` (données chargées) ; sans preuve d'exclusion, l'absence n'est pas établie."""
    results = tmp_path / "results"
    make_job(results, "job_1", job_config("2025-12-01T00:00:00+00:00", "2025-12-31T23:59:59+00:00"))
    result = interpret(results_root(results))
    job = finding(result, JOB_ID)
    assert job.status is SourceStatus.UNRESOLVED and job.overlap is OverlapVerdict.UNKNOWN
    assert job.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN and job.window_start_utc is None
    evidence = evidence_of(result, JOB_ID)
    assert evidence.status is b3.EvidenceStatus.ABSENCE_NOT_ESTABLISHED and evidence.manifest_source_id is None


@pytest.mark.parametrize("start, end, overlaps", [
    ("2025-12-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", False),          # fin exclusive = ws : P1 absente
    ("2025-12-01T00:00:00+00:00", "2026-01-01T00:00:00.000001+00:00", True),    # fin = ws + 1µs
    ("2025-12-01T00:00:00+00:00", "2026-01-01T02:00:00+02:00", False),          # ws exprimé en +02:00
    ("2026-04-01T00:00:00+00:00", "2026-05-01T00:00:00+00:00", False),          # exécution après W (début inclusif = we)
    ("2026-03-31T23:59:59.999999+00:00", "2026-05-01T00:00:00+00:00", True),    # début = we − 1µs
    ("2025-12-01T00:00:00+00:00", "9999-12-31T23:59:59.999999+00:00", True),    # borne max : exacte
])
def test_execution_window_establishes_but_never_excludes(tmp_path, start, end, overlaps):
    job, _ = one_job(tmp_path, job_config(start, end))
    if overlaps:
        assert job.status is SourceStatus.RESOLVED and job.overlap is OverlapVerdict.OVERLAPS
    else:
        assert job.status is SourceStatus.UNRESOLVED and job.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN


def test_established_job_carries_its_exact_execution_window_and_evidence(tmp_path):
    results = tmp_path / "results"
    make_job(results, "job_1", job_config("2026-03-01T00:00:00+00:00", "2026-04-01T02:00:00+02:00"))
    result = interpret(results_root(results))
    job = finding(result, JOB_ID)
    assert job.status is SourceStatus.RESOLVED and job.overlap is OverlapVerdict.OVERLAPS
    assert (job.window_start_utc, job.window_end_utc) == ("2026-03-01T00:00:00.000000Z", "2026-04-01T00:00:00.000000Z")
    assert job.content_hash == hashlib.sha256((results / "job_1" / "config_used.json").read_bytes()).hexdigest()
    assert evidence_of(result, JOB_ID).status is b3.EvidenceStatus.ESTABLISHED_BY_EXECUTION_WINDOW


# P2 : couverture chargée du `data_manifest.json` du même job (23.30.1). Établit seulement ; n'exclut jamais ; ne neutralise rien.

MANIFEST_ID = "job.manifest:res/job_1/data_manifest.json"
AFTER_W = ("2026-06-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00")       # exécution après W : P1 absente
DATA_FILE = r"C:\Users\x\data\US100_M3.csv"


def manifest(period_start="2020-01-01T00:00:00+00:00", period_end="2026-06-30T23:57:00+00:00", **changes) -> dict:
    record = {"provider": "local_csv", "instrument": "US100_M3", "provider_symbol": "US100_M3", "asset_type": None,
              "snapshot_id": "snap-1", "content_hash": "ab" * 32, "period_start": period_start, "period_end": period_end,
              "source_timeframe": "M3", "derived_timeframe": None, "timezone": "UTC", "session": "regular",
              "partial_bar_handling": "kept_and_flagged", "resample_options": {}, "strategy_version": "s",
              "engine_version": "1", "git_commit": "abc1234", "launched_at": "2026-07-01T00:00:00+00:00"}
    record.update(changes)
    return record


def job_with_manifest(tmp_path, record, config=None, raw=None):
    results = tmp_path / "results"
    make_job(results, "job_1", config if config is not None else job_config(*AFTER_W, data_file=DATA_FILE))
    path = results / "job_1" / "data_manifest.json"
    path.write_bytes(raw if raw is not None else json.dumps(record, indent=2).encode("utf-8"))
    result = interpret(results_root(results))
    return finding(result, JOB_ID), result, path


def test_job_after_w_whose_warmup_reads_w_is_established_by_loaded_coverage(tmp_path):
    """Cas « exécution après W mais warm-up lisant W » : la couverture chargée établit l'exposition."""
    job, result, path = job_with_manifest(tmp_path, manifest())
    assert job.status is SourceStatus.RESOLVED and job.overlap is OverlapVerdict.OVERLAPS
    assert (job.window_start_utc, job.window_end_utc) == ("2020-01-01T00:00:00.000000Z", "2026-06-30T23:57:00.000001Z")
    evidence = evidence_of(result, JOB_ID)
    assert evidence.status is b3.EvidenceStatus.ESTABLISHED_BY_LOADED_COVERAGE
    assert (evidence.manifest_source_id, evidence.manifest_content_hash) == (MANIFEST_ID,
                                                                             hashlib.sha256(path.read_bytes()).hexdigest())
    assert result.complete is True and not any(f.source_id == MANIFEST_ID for f in result.findings)  # informatif


def test_job_after_w_without_manifest_has_absence_not_established(tmp_path):
    results = tmp_path / "results"
    make_job(results, "job_1", job_config(*AFTER_W, data_file=DATA_FILE))
    result = interpret(results_root(results))
    job = finding(result, JOB_ID)
    assert job.status is SourceStatus.UNRESOLVED and job.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN
    assert evidence_of(result, JOB_ID).status is b3.EvidenceStatus.ABSENCE_NOT_ESTABLISHED


def test_execution_window_takes_priority_over_loaded_coverage(tmp_path):
    """Obligation 4 : P1 avec manifeste présent — la fenêtre portée est `X`, et le relevé dit P1."""
    job, result, _ = job_with_manifest(tmp_path, manifest(), config=job_config("2026-02-01T00:00:00+00:00",
                                                                               "2026-03-01T00:00:00+00:00", data_file=DATA_FILE))
    assert (job.window_start_utc, job.window_end_utc) == ("2026-02-01T00:00:00.000000Z", "2026-03-01T00:00:00.000000Z")
    evidence = evidence_of(result, JOB_ID)
    assert evidence.status is b3.EvidenceStatus.ESTABLISHED_BY_EXECUTION_WINDOW and evidence.manifest_source_id is None


def test_attributable_manifest_disjoint_from_w_never_excludes(tmp_path):
    job, result, _ = job_with_manifest(tmp_path, manifest(period_end="2025-12-31T23:57:00+00:00"),
                                       config=job_config("2025-01-01T00:00:00+00:00", "2025-12-01T00:00:00+00:00",
                                                         data_file=DATA_FILE))
    assert job.status is SourceStatus.UNRESOLVED and job.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN
    assert evidence_of(result, JOB_ID).status is b3.EvidenceStatus.ABSENCE_NOT_ESTABLISHED and result.complete is True


@pytest.mark.parametrize("period_start, period_end, overlaps", [
    ("2020-01-01T00:00:00+00:00", "2025-12-31T23:59:59.999999+00:00", False),   # dernière barre à ws − 1µs
    ("2020-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", True),           # dernière barre à ws
    ("2026-04-01T00:00:00+00:00", "2026-06-30T00:00:00+00:00", False),          # première barre à we
    ("2026-03-31T23:59:59.999999+00:00", "2026-06-30T00:00:00+00:00", True),    # première barre à we − 1µs
])
def test_loaded_coverage_boundaries_are_bar_instants(tmp_path, period_start, period_end, overlaps):
    job, _, _ = job_with_manifest(tmp_path, manifest(period_start, period_end))
    assert (job.overlap is OverlapVerdict.OVERLAPS) is overlaps
    assert job.status is (SourceStatus.RESOLVED if overlaps else SourceStatus.UNRESOLVED)


@pytest.mark.parametrize("data_file", [r"C:\Users\x\data\US100_M3.csv", "/srv/data/US100_M3.csv", "US100_M3.csv",
                                       r"D:\mixed/dir\US100_M3.csv", "C:US100_M3.csv"])
def test_attribution_uses_both_path_separators_whatever_the_auditor_os(tmp_path, data_file):
    job, _, _ = job_with_manifest(tmp_path, manifest(), config=job_config(*AFTER_W, data_file=data_file))
    assert job.overlap is OverlapVerdict.OVERLAPS


@pytest.mark.parametrize("data_file", [r"C:\a\US100_M3.csv", "/x/US100_M3.csv", "US100_M3", ".hidden", "...a.csv", "a.b.csv",
                                       r"C:\dir\.env", r"D:\m/x\n.tar.gz", "x/", "a.", "C:US100_M3.csv", r"\\srv\share\f.csv"])
def test_instrument_derivation_matches_the_windows_writer_whatever_the_auditor_os(data_file):
    """23.30.1 : l'attribution reproduit `splitext(basename(data_file))[0]` de `job_store.write_data_manifest` (exécuté sous Windows,
    donc `ntpath`), pour tout système d'auditeur ; `ntpath` sert d'oracle indépendant."""
    import ntpath
    assert b3._instrument_of(data_file) == (ntpath.splitext(ntpath.basename(data_file))[0] or None)


@pytest.mark.parametrize("record, config, raw", [
    (None, None, b"{broken"),                                                                    # illisible
    (manifest(extra=1), None, None),                                                             # clé en trop
    ({k: v for k, v in manifest().items() if k != "session"}, None, None),                       # clé manquante
    (manifest(resample_options=[]), None, None),                                                 # type inexact
    (manifest(content_hash=3), None, None),
    (manifest(period_start="2020-01-01T00:00:00"), None, None),                                  # borne naïve
    (manifest("2026-06-30T00:00:00+00:00", "2020-01-01T00:00:00+00:00"), None, None),            # bornes inversées
    (manifest(period_end="9999-12-31T23:59:59.999999+00:00"), None, None),                       # fin non représentable
    (manifest(instrument="EURUSD_M3"), None, None),                                              # non attribuable
    (manifest(), job_config(*AFTER_W), None),                                                    # `data_file` absent
    (manifest(), job_config(*AFTER_W, data_file=""), None),
])
def test_invalid_or_unattributable_manifest_gives_no_proof_and_an_incomplete_inventory(tmp_path, record, config, raw):
    job, result, _ = job_with_manifest(tmp_path, record, config=config, raw=raw)
    assert job.status is SourceStatus.UNRESOLVED and job.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN
    assert result.complete is False and "INFORMATIVE_UNRESOLVED:res/job_1/data_manifest.json" in result.incomplete_reasons


def test_legacy_manifest_without_bounds_is_no_proof_and_no_anomaly(tmp_path):
    """`write_data_manifest` met `period_start`, `period_end` et `content_hash` à None ENSEMBLE (chemin legacy)."""
    job, result, _ = job_with_manifest(tmp_path, manifest(period_start=None, period_end=None, content_hash=None))
    assert job.status is SourceStatus.UNRESOLVED and result.complete is True


@pytest.mark.parametrize("changes", [{"period_start": None, "period_end": None}, {"content_hash": None},
                                     {"period_end": None}, {"content_hash": ""}, {"content_hash": "AB" * 32},
                                     {"content_hash": "ab" * 31}])
def test_mixed_nullity_or_malformed_content_hash_is_an_anomaly_of_the_proof(tmp_path, changes):
    job, result, _ = job_with_manifest(tmp_path, manifest(**changes))
    assert job.status is SourceStatus.UNRESOLVED and result.complete is False


@pytest.mark.parametrize("config, raw, cause", [
    (job_config("2026-07-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00", data_file=DATA_FILE), None,
     UnresolvedCause.INVALID_SCHEMA),                                                             # bornes inversées
    (job_config(3, AFTER_W[1], data_file=DATA_FILE), None, UnresolvedCause.INVALID_SCHEMA),     # type invalide
    (job_config("2026-07-01", "2026-06-01", data_file=DATA_FILE), None, UnresolvedCause.INVALID_SCHEMA),  # civiles inversées
    (job_config("2026-07-01T00:00:00", "2026-06-01T00:00:00", data_file=DATA_FILE), None,
     UnresolvedCause.INVALID_SCHEMA),                                                             # naïves inversées
    (None, b"{broken", UnresolvedCause.UNREADABLE),                                             # config illisible
])
def test_a_proof_never_neutralises_an_anomaly_of_the_source(tmp_path, config, raw, cause):
    results = tmp_path / "results"
    make_job(results, "job_1", config if config is not None else job_config(*AFTER_W, data_file=DATA_FILE))
    if raw is not None:
        (results / "job_1" / "config_used.json").write_bytes(raw)
    write_json(results / "job_1" / "data_manifest.json", manifest())
    result = interpret(results_root(results))
    job = finding(result, JOB_ID)
    assert job.status is SourceStatus.UNRESOLVED and job.unresolved_cause is cause
    assert not any(e.source_id == JOB_ID for e in result.exposure_evidence)


def test_evidence_register_has_one_state_per_execution_source_reaching_steps_2_to_4(tmp_path):
    """Obligation 12 : arbre multi-sources ; aucune entrée pour l'étape 1 ; ABSENCE_ESTABLISHED n'est jamais produit à ce jour."""
    results = tmp_path / "results"
    make_job(results, "job_p1", job_config("2026-02-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00", data_file=DATA_FILE))
    make_job(results, "job_p2", job_config(*AFTER_W, data_file=DATA_FILE))
    write_json(results / "job_p2" / "data_manifest.json", manifest())
    make_job(results, "job_none", job_config("2025-01-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00"))
    make_job(results, "job_invalid", job_config("2026-07-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00"))
    write_json(results / "validations" / "val-ok01" / "validation_run.json", validation_record())
    write_json(results / "validations" / "val-bad01" / "validation_run.json", validation_record(extra_field=1))
    result = interpret(results_root(results))
    states = {e.source_id: e.status for e in result.exposure_evidence}
    assert states == {
        "job.config:res/job_p1/config_used.json": b3.EvidenceStatus.ESTABLISHED_BY_EXECUTION_WINDOW,
        "job.config:res/job_p2/config_used.json": b3.EvidenceStatus.ESTABLISHED_BY_LOADED_COVERAGE,
        "job.config:res/job_none/config_used.json": b3.EvidenceStatus.ABSENCE_NOT_ESTABLISHED,
        "validation.run:res/validations/val-ok01/validation_run.json": b3.EvidenceStatus.ESTABLISHED_BY_EXECUTION_WINDOW,
    }
    for source_id, status in states.items():
        established = status.value.startswith("ESTABLISHED")
        assert (finding(result, source_id).overlap is OverlapVerdict.OVERLAPS) is established
    assert all(f.overlap is not OverlapVerdict.NO_OVERLAP for f in result.findings
               if f.source_kind in (SourceKind.JOB_EXECUTION, SourceKind.VALIDATION_RUN_OOS))


@pytest.mark.parametrize("kwargs, error", [
    ({"source_id": "", "status": b3.EvidenceStatus.ABSENCE_NOT_ESTABLISHED}, TypeError),
    ({"source_id": "x", "status": "ABSENCE_NOT_ESTABLISHED"}, TypeError),
    ({"source_id": "x", "status": b3.EvidenceStatus.ESTABLISHED_BY_LOADED_COVERAGE}, ValueError),
    ({"source_id": "x", "status": b3.EvidenceStatus.ESTABLISHED_BY_EXECUTION_WINDOW, "manifest_source_id": "m",
      "manifest_content_hash": "h"}, ValueError),
])
def test_evidence_entry_refuses_inconsistent_facts(kwargs, error):
    with pytest.raises(error):
        b3.ExposureEvidence(**kwargs)


# ── Q-8 (ADR 0025 23.30.3) : conséquences d'une absence non établie sur E3-A, INCHANGÉ ───────────────────────────
# Caractérisation de contrats publiés : ces tests décrivent l'effet de B3 v2 sur 23.10 / 23.27.1 et ne modifient pas E3-A.

from gate_v_final_holdout_protocol import (  # noqa: E402
    OwnCampaignContext, OwnRecordStage, compute_exposure_inventory_id, compute_static_sources_digest,
)

OWN_CONTEXT = OwnCampaignContext("gate_v_v2_" + "ab" * 32, OwnRecordStage.NO_OWN_RECORDS)


def e3a_identities(findings, roots=("res",)) -> tuple:
    inventory = build_exposure_inventory(window_start_utc=W[0], window_end_utc=W[1], findings=tuple(findings), complete=True,
                                         scanned_roots=roots, trial_accounting=TrialAccounting(0, 0, 0, 0, 0, 0))
    return compute_static_sources_digest(inventory, OWN_CONTEXT), compute_exposure_inventory_id(inventory, OWN_CONTEXT)


def test_unresolved_execution_source_is_in_the_relevant_set(tmp_path):
    """23.30.3 : une source d'exécution à absence non établie n'est jamais hors de l'ensemble pertinent (digest ≠ ensemble vide)."""
    results = tmp_path / "results"
    make_job(results, "job_a", job_config("2025-01-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00"))
    one = interpret(results_root(results))
    assert [f.overlap for f in one.findings] == [OverlapVerdict.UNKNOWN]
    assert e3a_identities(one.findings)[0] != e3a_identities(())[0]


def test_adding_removing_or_modifying_a_relevant_source_changes_the_pinned_digest(tmp_path):
    """23.30.3 : ajouter, retirer ou modifier une source pertinente change `static_sources_digest` (le refus de l'étape 8 de 23.10,
    exécuté plus tard par E3-D/E3-J, repose sur ce changement) ; aucun contournement par suppression n'est silencieux."""
    results = tmp_path / "results"
    make_job(results, "job_a", job_config("2025-01-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00"))
    only_a = e3a_identities(interpret(results_root(results)).findings)[0]
    make_job(results, "job_b", job_config("2023-01-01T00:00:00+00:00", "2023-02-01T00:00:00+00:00"))
    with_b = e3a_identities(interpret(results_root(results)).findings)[0]
    assert with_b != only_a                                              # ajout « sans rapport » : le digest épinglé change
    shutil.rmtree(results / "job_b")
    assert e3a_identities(interpret(results_root(results)).findings)[0] == only_a   # retrait réellement exercé
    (results / "job_a" / "config_used.json").write_bytes(b'{"opt_start_date": null, "opt_end_date": null}')
    assert e3a_identities(interpret(results_root(results)).findings)[0] != only_a   # contenu modifié


def test_changing_the_audited_roots_changes_the_inventory_id():
    """23.30.3 : élargir ou réduire `scanned_roots` change `inventory_id` ; une réduction artificielle des racines est visible."""
    assert e3a_identities((), roots=("res", "autre"))[1] != e3a_identities((), roots=("res",))[1]


def test_established_exposure_and_unestablished_absence_are_distinct_states_never_an_absence(tmp_path):
    """23.30.3 : exposition établie (OVERLAPS) et absence non établie (UNRESOLVED) restent deux états ; aucun n'est NO_OVERLAP."""
    results = tmp_path / "results"
    make_job(results, "job_established", job_config("2026-02-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00"))
    make_job(results, "job_unestablished", job_config("2025-01-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00"))
    result = interpret(results_root(results))
    states = {f.source_id.split("/")[1]: (f.status, f.overlap) for f in result.findings}
    assert states == {"job_established": (SourceStatus.RESOLVED, OverlapVerdict.OVERLAPS),
                      "job_unestablished": (SourceStatus.UNRESOLVED, OverlapVerdict.UNKNOWN)}


def test_civil_bounds_with_covering_manifest_are_established_otherwise_timezone_unknown(tmp_path):
    job, _, _ = job_with_manifest(tmp_path, manifest(), config=job_config("2026-06-01", "2026-06-30", data_file=DATA_FILE))
    assert job.status is SourceStatus.RESOLVED and job.overlap is OverlapVerdict.OVERLAPS
    job, _, _ = job_with_manifest(tmp_path / "b", manifest(period_end="2025-12-31T23:57:00+00:00"),
                                  config=job_config("2025-06-01", "2025-06-30", data_file=DATA_FILE))
    assert job.status is SourceStatus.UNRESOLVED and job.unresolved_cause is UnresolvedCause.TIMEZONE_UNKNOWN


@pytest.mark.parametrize("start, end, cause", [
    ("2025-12-01", "2025-12-31", UnresolvedCause.TIMEZONE_UNKNOWN),                       # date civile : fuseau non supposé
    ("2025-12-01T00:00:00", "2025-12-31T00:00:00", UnresolvedCause.TIMEZONE_UNKNOWN),     # instant naïf
    ("2025-12-01", "2025-12-31T00:00:00+00:00", UnresolvedCause.TIMEZONE_UNKNOWN),        # début civil, fin ISO-T
    ("2025-12-01T00:00:00+00:00", "2025-12-31", UnresolvedCause.TIMEZONE_UNKNOWN),        # fin civile (23:59:59 Paris implicite)
    ("2025-12-01T00:00:00+00:00", None, UnresolvedCause.WINDOW_UNKNOWN),                 # borne manquante
    (None, "2025-12-31T00:00:00+00:00", UnresolvedCause.WINDOW_UNKNOWN),
    ("2026-02-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", UnresolvedCause.INVALID_SCHEMA),  # début après fin
    ("2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+01:00", UnresolvedCause.INVALID_SCHEMA),  # fenêtre vide [t, t)
    (3, "2025-12-31T00:00:00+00:00", UnresolvedCause.INVALID_SCHEMA),                     # type invalide
])
def test_undeterminable_job_windows_stay_unresolved(tmp_path, start, end, cause):
    job, _ = one_job(tmp_path, job_config(start, end))
    assert job.status is SourceStatus.UNRESOLVED and job.unresolved_cause is cause and job.window_start_utc is None


def test_job_config_without_window_keys_is_window_unknown(tmp_path):
    job, _ = one_job(tmp_path, {"run_id": "job_1"})
    assert job.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN


# ── Tranche 3 : anomalies, entrées inconnues, complétude (préconditions B3 n° 2 et 3) ───────────────────────────

def clean_results(tmp_path):
    results = tmp_path / "results"
    make_job(results, "job_1", job_config("2025-12-01T00:00:00+00:00", "2025-12-31T00:00:00+00:00"))
    return results


def test_clean_tree_is_complete(tmp_path):
    result = interpret(results_root(clean_results(tmp_path)))
    assert result.complete is True and result.incomplete_reasons == ()


@pytest.mark.parametrize("build, source_id", [
    (lambda r: (r / "notes.txt").write_bytes(b"?"), "unknown:res/notes.txt"),                       # fichier hors table
    (lambda r: (r / "mystery").mkdir(), "unknown:res/mystery"),                                     # répertoire jamais descendu
    (lambda r: (r / "job_1" / "tmp87fh6z9w.tmp").write_bytes(b""), "unknown:res/job_1/tmp87fh6z9w.tmp"),  # temporaire réel
    (lambda r: (r / "job_1" / "logs.txt").unlink() or (r / "job_1" / "logs.txt").mkdir(), "job.inert:res/job_1/logs.txt"),
])
def test_unknown_or_mismatched_entries_are_unresolved_unknown_sources(tmp_path, build, source_id):
    results = clean_results(tmp_path)
    build(results)
    result = interpret(results_root(results))
    unknown = finding(result, source_id)
    assert unknown.source_kind is SourceKind.UNKNOWN_SOURCE and unknown.status is SourceStatus.UNRESOLVED
    assert unknown.unresolved_cause in (UnresolvedCause.UNKNOWN_SOURCE_TYPE, UnresolvedCause.INVALID_SCHEMA)
    assert result.complete is False and any(source_id.split(":", 1)[1] in r for r in result.incomplete_reasons)


@pytest.mark.parametrize("raw, cause", [
    (b"{not json", UnresolvedCause.UNREADABLE),
    (b'{"a": 1, "a": 2}', UnresolvedCause.UNREADABLE),           # clé dupliquée : jamais « la dernière gagne »
    (b"[1, 2]", UnresolvedCause.INVALID_SCHEMA),                   # type JSON inattendu
])
def test_anomalous_exposing_content_keeps_its_kind_and_stays_unresolved(tmp_path, raw, cause):
    results = clean_results(tmp_path)
    (results / "job_1" / "config_used.json").write_bytes(raw)
    result = interpret(results_root(results))
    job = finding(result, "job.config:res/job_1/config_used.json")
    assert job.source_kind is SourceKind.JOB_EXECUTION and job.status is SourceStatus.UNRESOLVED
    assert job.unresolved_cause is cause and job.content_hash == hashlib.sha256(raw).hexdigest()
    assert result.complete is False


def test_empty_root_allowed_by_policy_is_never_complete(tmp_path):
    empty = tmp_path / "results"
    empty.mkdir()
    result = b3.interpret_audit_roots((b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("res", str(empty), may_be_empty=True)),),
                                      LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    assert result.findings == () and result.complete is False
    assert result.incomplete_reasons == ("ROOT_WITHOUT_SOURCE:res",)


# ── Tranche 4 : entrées requises absentes (précondition B3 n° 4 : B2 n'observe pas ce qui manque) ──────────────

def test_job_directory_without_its_anchor_is_an_unresolved_job(tmp_path):
    results = clean_results(tmp_path)
    (results / "job_2").mkdir()
    (results / "job_2" / "logs.txt").write_bytes(b"x")
    result = interpret(results_root(results))
    missing = finding(result, "job.config:res/job_2/config_used.json")
    assert missing.source_kind is SourceKind.JOB_EXECUTION and missing.status is SourceStatus.UNRESOLVED
    assert missing.unresolved_cause is UnresolvedCause.INVALID_SCHEMA and missing.content_hash is None
    assert result.complete is False and "MISSING_REQUIRED:res/job_2/config_used.json" in result.incomplete_reasons


def test_anchor_present_but_anomalous_is_reported_once(tmp_path):
    results = clean_results(tmp_path)
    (results / "job_1" / "config_used.json").write_bytes(b"{broken")
    result = interpret(results_root(results))
    assert [f.source_id for f in result.findings] == ["job.config:res/job_1/config_used.json"]
    assert not any(r.startswith("MISSING_REQUIRED") for r in result.incomplete_reasons)


# ── Tranche 5 : plans de split (informatifs, indexés) et événements d'accès legacy ─────────────────────────────

import copy  # noqa: E402

from dataset_split import build_dataset_split_plan, build_split_boundary, dataset_split_plan_fingerprint  # noqa: E402

PLAN = {"split_plan_id": "plan-alpha", "dataset_snapshot_id": "snap-1",
        "train": {"start": "2020-01-01T00:00:00+00:00", "end": "2026-01-01T00:00:00+00:00"},
        "final_holdout": {"start": "2026-01-01T00:00:00+00:00", "end": "2026-04-01T00:00:00+00:00"},
        "validation": None, "discovery_oos": None, "created_at": "2025-06-01T00:00:00+00:00"}
EVENT = {"split_plan_id": "plan-alpha", "dataset_snapshot_id": "snap-1", "research_run_id": "rr-1", "reason": "oos",
         "locked_state": "locked", "accessed_at": "2026-05-01T00:00:00+00:00", "event_id": "e1", "validation_run_id": "val-1"}
EVENT_ID = "split.event:res/dataset_splits/plan-alpha/holdout_access/2026-05-01_e1.json"


def make_split(results, plan=PLAN, events=(EVENT,), directory="plan-alpha"):
    if plan is not None:
        write_json(results / "dataset_splits" / directory / "split_plan.json", plan)
    for i, event in enumerate(events):
        name = "2026-05-01_e1.json" if i == 0 else f"2026-05-0{i + 1}_e{i + 1}.json"
        write_json(results / "dataset_splits" / directory / "holdout_access" / name, event)
    (results / "dataset_splits" / directory).mkdir(parents=True, exist_ok=True)


def test_event_takes_the_final_holdout_window_of_its_plan(tmp_path):
    results = clean_results(tmp_path)
    make_split(results)
    result = interpret(results_root(results))
    event = finding(result, EVENT_ID)
    assert event.source_kind is SourceKind.HOLDOUT_ACCESS_EVENT and event.status is SourceStatus.RESOLVED
    assert (event.window_start_utc, event.window_end_utc) == ("2026-01-01T00:00:00.000000Z", "2026-04-01T00:00:00.000000Z")
    assert event.overlap is OverlapVerdict.OVERLAPS and event.campaign_id is None
    (plan,) = result.plans                                   # informatif : jamais un finding (23.27.1)
    assert plan.split_plan_id == "plan-alpha" and plan.source_id == "split.plan:res/dataset_splits/plan-alpha/split_plan.json"
    expected = dataset_split_plan_fingerprint(build_dataset_split_plan(
        split_plan_id="plan-alpha", dataset_snapshot_id="snap-1",
        train=build_split_boundary(PLAN["train"]["start"], PLAN["train"]["end"]),
        final_holdout=build_split_boundary(PLAN["final_holdout"]["start"], PLAN["final_holdout"]["end"]),
        created_at=PLAN["created_at"]))
    assert plan.fingerprint == expected
    assert not any(f.source_id.startswith("split.plan") for f in result.findings) and result.complete is True


def _other_plan(**changes):
    plan = copy.deepcopy(PLAN)
    plan.update(changes)
    return plan


@pytest.mark.parametrize("arrange", [
    lambda r: make_split(r, plan=None) or None,                                            # aucun plan
    lambda r: (make_split(r), make_split(r, plan=_other_plan(final_holdout={              # deux plans, fenêtres divergentes
        "start": "2026-02-01T00:00:00+00:00", "end": "2026-05-01T00:00:00+00:00"}), events=(), directory="plan-alpha-copy")),
    lambda r: make_split(r, plan=_other_plan(dataset_snapshot_id="snap-2")),               # snapshot incohérent avec l'événement
    lambda r: make_split(r, plan=_other_plan(final_holdout={"start": "2026-01-01T00:00:00", "end": "2026-04-01T00:00:00"})),
])
def test_event_whose_plan_is_missing_ambiguous_or_inconsistent_is_plan_unresolved(tmp_path, arrange):
    results = clean_results(tmp_path)
    arrange(results)
    event = finding(interpret(results_root(results)), EVENT_ID)
    assert event.status is SourceStatus.UNRESOLVED and event.unresolved_cause is UnresolvedCause.PLAN_UNRESOLVED


def test_event_designates_by_identifier_and_its_own_snapshot_without_requiring_other_plans_to_concord(tmp_path):
    """23.30.2 : un plan de même identifiant mais d'un AUTRE snapshot est un plan distinct ; aucune concordance n'est exigée."""
    results = clean_results(tmp_path)
    make_split(results)
    make_split(results, plan=_other_plan(dataset_snapshot_id="snap-2", final_holdout={
        "start": "2026-02-01T00:00:00+00:00", "end": "2026-05-01T00:00:00+00:00"}), events=(), directory="plan-alpha-snap2")
    event = finding(interpret(results_root(results)), EVENT_ID)
    assert event.status is SourceStatus.RESOLVED
    assert (event.window_start_utc, event.window_end_utc) == ("2026-01-01T00:00:00.000000Z", "2026-04-01T00:00:00.000000Z")


def test_extended_or_malformed_event_is_invalid_schema_until_e3g(tmp_path):
    results = clean_results(tmp_path)
    make_split(results, events=({**EVENT, "campaign_id": "gate_v_v2_" + "0" * 64},))
    assert finding(interpret(results_root(results)), EVENT_ID).unresolved_cause is UnresolvedCause.INVALID_SCHEMA
    results2 = clean_results(tmp_path / "b")
    make_split(results2, events=({k: v for k, v in EVENT.items() if k != "event_id"},))
    assert finding(interpret(results_root(results2)), EVENT_ID).unresolved_cause is UnresolvedCause.INVALID_SCHEMA


def test_legacy_event_without_validation_run_id_is_accepted(tmp_path):
    results = clean_results(tmp_path)
    make_split(results, events=({k: v for k, v in EVENT.items() if k != "validation_run_id"},))
    assert finding(interpret(results_root(results)), EVENT_ID).status is SourceStatus.RESOLVED


def test_invalid_plan_is_reported_and_never_indexed(tmp_path):
    results = clean_results(tmp_path)
    make_split(results, plan=_other_plan(final_holdout={"start": "2026-04-01T00:00:00+00:00", "end": "2026-01-01T00:00:00+00:00"}))
    result = interpret(results_root(results))
    assert result.plans == () and result.complete is False
    assert "INFORMATIVE_UNRESOLVED:res/dataset_splits/plan-alpha/split_plan.json" in result.incomplete_reasons
    assert finding(result, EVENT_ID).unresolved_cause is UnresolvedCause.PLAN_UNRESOLVED


def test_split_directory_without_plan_is_reported_missing(tmp_path):
    results = clean_results(tmp_path)
    make_split(results, plan=None, events=())
    result = interpret(results_root(results))
    assert "MISSING_REQUIRED:res/dataset_splits/plan-alpha/split_plan.json" in result.incomplete_reasons
    assert [f.source_id for f in result.findings] == ["job.config:res/job_1/config_used.json"]   # un plan n'est pas un finding


# ── Tranche 6 : ValidationRun (OOS legacy inclusive ; WF/MC/PS non tranchés : Q-2 ouverte) ─────────────────────

from validation_run import (  # noqa: E402
    VALIDATION_TYPE_MONTE_CARLO, VALIDATION_TYPE_OOS, VALIDATION_TYPE_PARAMETER_STABILITY, VALIDATION_TYPE_WALK_FORWARD,
)

VAL_ID = "validation.run:res/validations/val-oos-1/validation_run.json"


def validation_record(validation_type=VALIDATION_TYPE_OOS, start="2026-01-01T00:00:00+00:00", end="2026-04-01T00:00:00+00:00",
                      **extra):
    return {"validation_run_id": "val-oos-1", "research_run_id": "rr-1", "split_plan_id": "plan-alpha",
            "dataset_snapshot_id": "snap-1", "validation_type": validation_type, "strategy_name": "s", "strategy_params": {},
            "evidence": {"period_start": start, "period_end": end, "n_trades": 0}, "status": "completed",
            "completed_at": "2026-05-01T00:00:00+00:00", **extra}


def one_validation(tmp_path, record, inert=True):
    results = clean_results(tmp_path)
    write_json(results / "validations" / "val-oos-1" / "validation_run.json", record)
    if inert:
        (results / "validations" / "val-oos-1" / "research_run.json").write_bytes(b"{}")
    result = interpret(results_root(results))
    return finding(result, VAL_ID), result


def test_legacy_oos_validation_window_is_inclusive_and_resolved(tmp_path):
    validation, result = one_validation(tmp_path, validation_record())
    assert validation.source_kind is SourceKind.VALIDATION_RUN_OOS and validation.status is SourceStatus.RESOLVED
    assert (validation.window_start_utc, validation.window_end_utc) == ("2026-01-01T00:00:00.000000Z", "2026-04-01T00:00:00.000001Z")
    assert validation.overlap is OverlapVerdict.OVERLAPS and result.complete is True


def test_legacy_oos_validation_outside_w_has_absence_not_established(tmp_path):
    """23.30.1 : une `ValidationRun` OOS legacy n'a aucune preuve d'exclusion (aucun manifeste) ; hors de `W` elle reste
    UNRESOLVED ; égale à `W` son exposition est établie par sa fenêtre d'exécution (P1)."""
    validation, result = one_validation(tmp_path, validation_record(start="2025-10-01T00:00:00+00:00",
                                                                    end="2025-12-01T00:00:00+00:00"))
    assert validation.status is SourceStatus.UNRESOLVED and validation.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN
    assert evidence_of(result, VAL_ID).status is b3.EvidenceStatus.ABSENCE_NOT_ESTABLISHED
    _, established = one_validation(tmp_path / "b", validation_record())
    assert evidence_of(established, VAL_ID).status is b3.EvidenceStatus.ESTABLISHED_BY_EXECUTION_WINDOW


def test_current_record_with_specification_key_is_accepted(tmp_path):
    validation, _ = one_validation(tmp_path, validation_record(specification={"holdout_start": "x"}))
    assert validation.status is SourceStatus.RESOLVED


# Un `ValidationRun` n'est typé `VALIDATION_RUN_OOS` que si son contenu établit `validation_type == "oos"`. E3-A (publié) n'a aucun
# type pour un walk-forward, un Monte-Carlo ou une stabilité : B3 les rend `UNKNOWN_SOURCE` (capacité d'exposition inconnue,
# jamais RESOLVED, compté non résolu par F1 et F2) et consigne leur nature réelle dans `non_oos_validations` (informatif).

@pytest.mark.parametrize("validation_type", [VALIDATION_TYPE_WALK_FORWARD, VALIDATION_TYPE_MONTE_CARLO,
                                             VALIDATION_TYPE_PARAMETER_STABILITY])
def test_non_oos_validation_is_never_typed_oos_and_keeps_its_nature(tmp_path, validation_type):
    validation, result = one_validation(tmp_path, validation_record(validation_type))
    assert validation.source_kind is SourceKind.UNKNOWN_SOURCE and validation.status is SourceStatus.UNRESOLVED
    assert validation.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN          # Q-2 : fenêtre exposée non tranchée
    (note,) = result.non_oos_validations
    assert (note.source_id, note.validation_type, note.content_hash) == (VAL_ID, validation_type, validation.content_hash)


def test_oos_validation_is_not_listed_as_non_oos(tmp_path):
    _, result = one_validation(tmp_path, validation_record())
    assert result.non_oos_validations == ()


@pytest.mark.parametrize("record, kind, cause", [
    (validation_record("stress_v9"), SourceKind.UNKNOWN_SOURCE, UnresolvedCause.UNKNOWN_SCHEMA_VERSION),   # type inconnu
    ({k: v for k, v in validation_record().items() if k != "validation_type"}, SourceKind.UNKNOWN_SOURCE,
     UnresolvedCause.INVALID_SCHEMA),                                                                        # type absent
    (validation_record(VALIDATION_TYPE_WALK_FORWARD, extra_field=1), SourceKind.UNKNOWN_SOURCE, UnresolvedCause.INVALID_SCHEMA),
    (validation_record(extra_field=1), SourceKind.VALIDATION_RUN_OOS, UnresolvedCause.INVALID_SCHEMA),     # OOS, schéma faux
    ({k: v for k, v in validation_record().items() if k != "evidence"}, SourceKind.VALIDATION_RUN_OOS,
     UnresolvedCause.INVALID_SCHEMA),
    (validation_record(start="2026-01-01"), SourceKind.VALIDATION_RUN_OOS, UnresolvedCause.TIMEZONE_UNKNOWN),
    (validation_record(end="9999-12-31T23:59:59.999999+00:00"), SourceKind.VALIDATION_RUN_OOS,
     UnresolvedCause.WINDOW_UNKNOWN),                                                     # fin inclusive max : jamais tronquée
])
def test_invalid_validation_records_stay_unresolved(tmp_path, record, kind, cause):
    validation, _ = one_validation(tmp_path, record)
    assert validation.status is SourceStatus.UNRESOLVED and validation.unresolved_cause is cause
    assert validation.source_kind is kind


def test_unreadable_validation_run_has_an_unknown_nature(tmp_path):
    results = clean_results(tmp_path)
    (results / "validations" / "val-oos-1").mkdir(parents=True)
    (results / "validations" / "val-oos-1" / "validation_run.json").write_bytes(b"{broken")
    validation = finding(interpret(results_root(results)), VAL_ID)
    assert validation.source_kind is SourceKind.UNKNOWN_SOURCE and validation.unresolved_cause is UnresolvedCause.UNREADABLE


def test_validation_directory_without_run_is_unresolved(tmp_path):
    results = clean_results(tmp_path)
    (results / "validations" / "val-oos-1").mkdir(parents=True)
    (results / "validations" / "val-oos-1" / "research_run.json").write_bytes(b"{}")
    missing = finding(interpret(results_root(results)), VAL_ID)
    assert missing.source_kind is SourceKind.UNKNOWN_SOURCE and missing.unresolved_cause is UnresolvedCause.INVALID_SCHEMA


# ── Tranche 7 : table RESULTS fermée sur la disposition réelle (noms constatés le 2026-10-16) ───────────────────

REAL_JOB_FILES = ("archive.zip", "logs.txt", "meta.json", "metrics.json", "progress.json", "report.html", "tested.json",
                  "results.csv", "best_strategies.csv", "job_decisions.json", "job_notes.json",
                  "stop.flag", "research_run.json")


def real_layout_replica(tmp_path):
    """Réplique SYNTHÉTIQUE de la disposition de `results/` (noms réels, contenus factices, aucune donnée de marché)."""
    results = tmp_path / "results"
    make_job(results, "job_20260815_120000_ab12", job_config(), inert=REAL_JOB_FILES)
    write_json(results / "job_20260815_120000_ab12" / "data_manifest.json",               # manifeste legacy : bornes nulles
               manifest(period_start=None, period_end=None, content_hash=None))
    make_job(results, "job_gate_data_validation", job_config("2025-01-01", None), inert=("archive.zip",))
    make_split(results)
    write_json(results / "validations" / "val-oos-1" / "validation_run.json", validation_record())
    (results / "validations" / "val-oos-1" / "research_run.json").write_bytes(b"{}")
    write_json(results / "experiments" / "exp_alpha.json", {"created_at": "x", "experiment_id": "exp_alpha", "hypothesis": "h"})
    dataset = results / "datasets" / "ig_ix_d_nasdaq_ifd_ip_minute_3"
    for relative in ("raw/ig_prices_raw.json", "raw/manifest.json", "normalized/ig_prices_normalized.csv",
                     "normalized/manifest.json", "research_run.json"):
        (dataset / relative).parent.mkdir(parents=True, exist_ok=True)
        (dataset / relative).write_bytes(b"NOT-JSON market bytes must never be opened")
    return results


def test_real_layout_replica_is_fully_known_and_market_data_is_never_opened(tmp_path):
    result = interpret(results_root(real_layout_replica(tmp_path)))
    assert not [f for f in result.findings if f.source_kind is SourceKind.UNKNOWN_SOURCE]
    assert sorted(f.source_kind.value for f in result.findings) == [
        "HOLDOUT_ACCESS_EVENT", "JOB_EXECUTION", "JOB_EXECUTION", "VALIDATION_RUN_OOS"]
    assert result.complete is True
    (scan,) = result.scans
    opened = {o.relative_path for o in scan.scan.observations if o.content_hash is not None}
    assert not any(path.startswith("datasets/") for path in opened)       # données de marché jamais lues
    assert opened == {"job_20260815_120000_ab12/config_used.json", "job_gate_data_validation/config_used.json",
                      "job_20260815_120000_ab12/data_manifest.json",                 # preuve P2 (23.30.1)
                      "dataset_splits/plan-alpha/split_plan.json",
                      "dataset_splits/plan-alpha/holdout_access/2026-05-01_e1.json",
                      "validations/val-oos-1/validation_run.json", "experiments/exp_alpha.json"}


def test_real_temporary_file_in_a_job_makes_the_inventory_incomplete(tmp_path):
    results = real_layout_replica(tmp_path)
    (results / "job_20260815_120000_ab12" / "tmp87fh6z9w.tmp").write_bytes(b"")
    result = interpret(results_root(results))
    assert finding(result, "unknown:res/job_20260815_120000_ab12/tmp87fh6z9w.tmp").source_kind is SourceKind.UNKNOWN_SOURCE
    assert result.complete is False


def test_file_in_experiments_that_is_not_an_experiment_is_never_trusted(tmp_path):
    results = real_layout_replica(tmp_path)
    write_json(results / "experiments" / "exp_beta.json", {"claim_id": "x", "experiment_id": "exp_beta"})
    result = interpret(results_root(results))
    assert "INFORMATIVE_UNRESOLVED:res/experiments/exp_beta.json" in result.incomplete_reasons and result.complete is False


# ── Tranche 8 : dossier de campagne V2 et Claims (fenêtre = FINAL_HOLDOUT du plan désigné, 23.27.2) ───────────

from gate_v_exposure_scan import ExposureScanRefusal, StructuralFailure  # noqa: E402
from gate_v_final_holdout_claim import (  # noqa: E402
    FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION, compute_final_holdout_access_claim_content_hash,
    compute_final_holdout_access_claim_id,
)

CAMPAIGN_ID = "gate_v_v2_" + "ab" * 32


def plan_fingerprint(plan=PLAN) -> str:
    return dataset_split_plan_fingerprint(build_dataset_split_plan(
        split_plan_id=plan["split_plan_id"], dataset_snapshot_id=plan["dataset_snapshot_id"],
        train=build_split_boundary(plan["train"]["start"], plan["train"]["end"]),
        final_holdout=build_split_boundary(plan["final_holdout"]["start"], plan["final_holdout"]["end"]),
        created_at=plan["created_at"]))


def claim_record(campaign_id=CAMPAIGN_ID, split_plan_fingerprint=None) -> dict:
    preimage = {"campaign_id": campaign_id, "preregistration_id": "1" * 64, "preregistration_content_hash": "2" * 64,
                "campaign_protocol_fingerprint": "3" * 64, "research_run_id": "rr-1", "research_run_content_hash": "4" * 64,
                "dataset_snapshot_id": "snap-1", "split_plan_id": "plan-alpha",
                "split_plan_fingerprint": split_plan_fingerprint or plan_fingerprint(),
                "assessment_semantics_version": "assessment_v1", "claim_semantics_version": FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION}
    claim_id = compute_final_holdout_access_claim_id(**preimage)
    content_hash = compute_final_holdout_access_claim_content_hash(claim_id=claim_id, **preimage)
    return {"claim_semantics_version": preimage["claim_semantics_version"], "claim_id": claim_id,
            "claim_content_hash": content_hash, **{k: v for k, v in preimage.items() if k != "claim_semantics_version"},
            "created_at": "2026-04-02T00:00:00+00:00"}


def make_campaign(base: Path, claim=None, plan_campaign_id=CAMPAIGN_ID, name=CAMPAIGN_ID) -> Path:
    directory = base / name
    if plan_campaign_id is not None:
        write_json(directory / "plan.json", {"campaign_id": plan_campaign_id})
    write_json(directory / "final_holdout_access_claim.json", claim if claim is not None else claim_record())
    return directory


def campaign_root(path: Path, label: str) -> b3.LayoutRoot:
    return b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, AuditRoot(label, str(path)))


def with_plan(tmp_path):
    results = clean_results(tmp_path / "w")
    make_split(results, events=())
    return results


def test_claim_takes_the_final_holdout_window_of_the_plan_it_designates(tmp_path):
    results = with_plan(tmp_path)
    campaign = make_campaign(tmp_path / "campaigns")
    result = interpret(results_root(results), campaign_root(campaign, "camp1"))
    claim = finding(result, "campaign.claim:camp1/final_holdout_access_claim.json")
    assert claim.source_kind is SourceKind.FINAL_HOLDOUT_CLAIM and claim.status is SourceStatus.RESOLVED
    assert claim.campaign_id == CAMPAIGN_ID and claim.overlap is OverlapVerdict.OVERLAPS
    assert (claim.window_start_utc, claim.window_end_utc) == ("2026-01-01T00:00:00.000000Z", "2026-04-01T00:00:00.000000Z")
    assert result.complete is True


def test_two_copies_of_one_claim_are_two_distinct_findings(tmp_path):
    """Test obligatoire (23.27.2) : deux copies d'un même Claim ne sont jamais fusionnées ni dédupliquées."""
    results = with_plan(tmp_path)
    first = make_campaign(tmp_path / "a")
    second = make_campaign(tmp_path / "b")
    result = interpret(results_root(results), campaign_root(first, "camp1"), campaign_root(second, "camp2"))
    claims = [f for f in result.findings if f.source_kind is SourceKind.FINAL_HOLDOUT_CLAIM]
    assert [c.source_id for c in claims] == ["campaign.claim:camp1/final_holdout_access_claim.json",
                                             "campaign.claim:camp2/final_holdout_access_claim.json"]
    assert claims[0].content_hash == claims[1].content_hash and all(c.status is SourceStatus.RESOLVED for c in claims)


def test_claim_is_bound_to_its_fingerprinted_plan_not_to_a_same_id_copy(tmp_path):
    """Règle retenue (§51.1) : `split_plan_id` est choisi par l'appelant, donc non unique ; le plan désigné par un Claim est celui
    dont l'identifiant ET l'empreinte égalent ceux du Claim (le Claim épingle `split_plan_fingerprint`, couvert par `claim_id`)."""
    results = with_plan(tmp_path)
    make_split(results, plan=_other_plan(final_holdout={"start": "2026-02-01T00:00:00+00:00", "end": "2026-05-01T00:00:00+00:00"}),
               events=(), directory="plan-alpha-copy")
    campaign = make_campaign(tmp_path / "campaigns")
    claim = finding(interpret(results_root(results), campaign_root(campaign, "camp1")),
                    "campaign.claim:camp1/final_holdout_access_claim.json")
    assert claim.status is SourceStatus.RESOLVED
    assert (claim.window_start_utc, claim.window_end_utc) == ("2026-01-01T00:00:00.000000Z", "2026-04-01T00:00:00.000000Z")
    result = interpret(results_root(results), campaign_root(campaign, "camp1"))
    assert result.complete is True and not any(r.startswith("PLAN_FINGERPRINT_MISMATCH") for r in result.incomplete_reasons)


def test_two_copies_of_one_plan_identity_with_different_bytes_give_one_window(tmp_path):
    """Obligation 14 : même identité (identifiant + empreinte recalculée), octets différents (mise en forme, ordre des clés)."""
    results = with_plan(tmp_path)
    copy_path = results / "dataset_splits" / "plan-alpha-copy" / "split_plan.json"
    copy_path.parent.mkdir(parents=True)
    copy_path.write_bytes(json.dumps(dict(reversed(list(PLAN.items())))).encode("utf-8"))   # sans indentation, clés inversées
    campaign = make_campaign(tmp_path / "campaigns")
    result = interpret(results_root(results), campaign_root(campaign, "camp1"))
    plans = [p for p in result.plans if p.split_plan_id == "plan-alpha"]
    assert len(plans) == 2 and plans[0].content_hash != plans[1].content_hash and plans[0].fingerprint == plans[1].fingerprint
    assert finding(result, "campaign.claim:camp1/final_holdout_access_claim.json").status is SourceStatus.RESOLVED


def test_incompatible_fingerprint_claim_is_an_explicit_incoherence(tmp_path):
    """23.30.2 : un plan valide du même identifiant est lu, mais aucun n'a l'empreinte revendiquée → incohérence explicite."""
    results = with_plan(tmp_path)
    campaign = make_campaign(tmp_path / "c", claim=claim_record(split_plan_fingerprint="9" * 64))
    result = interpret(results_root(results), campaign_root(campaign, "camp1"))
    claim = finding(result, "campaign.claim:camp1/final_holdout_access_claim.json")
    assert claim.status is SourceStatus.UNRESOLVED and claim.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN
    assert result.complete is False
    assert "PLAN_FINGERPRINT_MISMATCH:camp1/final_holdout_access_claim.json" in result.incomplete_reasons


def test_claim_without_any_plan_of_its_identifier_is_only_unresolved(tmp_path):
    results = clean_results(tmp_path / "w")
    campaign = make_campaign(tmp_path / "c")
    result = interpret(results_root(results), campaign_root(campaign, "camp1"))
    claim = finding(result, "campaign.claim:camp1/final_holdout_access_claim.json")
    assert claim.unresolved_cause is UnresolvedCause.WINDOW_UNKNOWN and result.complete is True


def test_plan_stored_under_another_directory_name_is_still_designable(tmp_path):
    """23.30.2 : `split_plan_slug` est une convention de rangement, l'identité ne dépend pas du nom de répertoire."""
    results = clean_results(tmp_path / "w")
    make_split(results, events=(), directory="plan-stored-elsewhere")
    campaign = make_campaign(tmp_path / "c")
    claim = finding(interpret(results_root(results), campaign_root(campaign, "camp1")),
                    "campaign.claim:camp1/final_holdout_access_claim.json")
    assert claim.status is SourceStatus.RESOLVED


@pytest.mark.parametrize("mutate, cause", [
    (lambda c: c.update(claim_semantics_version="final_holdout_access_claim_v9"), UnresolvedCause.UNKNOWN_SCHEMA_VERSION),
    (lambda c: c.update(claim_id="0" * 64), UnresolvedCause.INVALID_SCHEMA),             # hash recalculé par E1 : refus
    (lambda c: c.update(extra="x"), UnresolvedCause.INVALID_SCHEMA),
])
def test_invalid_claims_stay_unresolved(tmp_path, mutate, cause):
    record = claim_record()
    mutate(record)
    campaign = make_campaign(tmp_path / "c", claim=record)
    claim = finding(interpret(results_root(with_plan(tmp_path)), campaign_root(campaign, "camp1")),
                    "campaign.claim:camp1/final_holdout_access_claim.json")
    assert claim.status is SourceStatus.UNRESOLVED and claim.unresolved_cause is cause


@pytest.mark.parametrize("plan_campaign_id, reason", [
    (None, "MISSING_REQUIRED:camp1/plan.json"),
    ("gate_v_v2_" + "cd" * 32, "INFORMATIVE_UNRESOLVED:camp1/plan.json"),               # ancre d'un autre dossier
])
def test_campaign_directory_must_be_anchored_by_its_plan(tmp_path, plan_campaign_id, reason):
    campaign = make_campaign(tmp_path / "c", plan_campaign_id=plan_campaign_id)
    result = interpret(results_root(with_plan(tmp_path)), campaign_root(campaign, "camp1"))
    assert reason in result.incomplete_reasons and result.complete is False
    claim = finding(result, "campaign.claim:camp1/final_holdout_access_claim.json")
    assert claim.status is SourceStatus.RESOLVED      # une ancre défaillante ne masque jamais l'exposition elle-même


def test_unlisted_campaign_files_are_unknown_until_their_interpreters_exist(tmp_path):
    # Amendé avec B3 v4 (Q-2, K1 Étage 1, accepté le 2026-10-24) : `manifest.json` est désormais une source INFORMATIVE à schéma strict ; ce nom
    # ne sert donc plus d'exemple de fichier inconnu (voir `test_gate_v_exposure_interpreters_v4.py` pour son contrat). Un nom sans interprète
    # reste inconnu, bloquant et fait d'un finding `UNKNOWN_SOURCE`, comme avant.
    campaign = make_campaign(tmp_path / "c")
    write_json(campaign / "anything.json", {"x": 1})
    result = interpret(results_root(with_plan(tmp_path)), campaign_root(campaign, "camp1"))
    assert finding(result, "unknown:camp1/anything.json").source_kind is SourceKind.UNKNOWN_SOURCE and result.complete is False


def test_campaign_root_nested_under_results_root_is_refused(tmp_path):
    results = with_plan(tmp_path)
    nested = make_campaign(results / "job_9")
    with pytest.raises(ExposureScanRefusal) as refusal:
        interpret(results_root(results), campaign_root(nested, "camp1"))
    assert refusal.value.failure is StructuralFailure.ROOT_OVERLAP


def test_root_labels_are_unique_across_layouts(tmp_path):
    campaign = make_campaign(tmp_path / "c")
    with pytest.raises(ExposureScanRefusal) as refusal:
        interpret(results_root(with_plan(tmp_path), label="same"), campaign_root(campaign, "same"))
    assert refusal.value.failure is StructuralFailure.DUPLICATE_ROOT_LABEL


# ── Tranche 9 : préconditions B3 vérifiées comme propriétés (§47 n° 1, 3, 5, 6) et contrat E3-A réutilisé ─────

import ast  # noqa: E402
import inspect  # noqa: E402

from gate_v_exposure_scan import EntryClass, ScanHooks, SegmentPattern, SourceAnomaly  # noqa: E402
from gate_v_final_holdout_protocol import TrialAccounting, build_exposure_inventory  # noqa: E402

EXPECTED_INERT_PATHS = {
    *(("job_1", name) for name in REAL_JOB_FILES),
    ("validations", "val-oos-1", "research_run.json"),
    ("datasets", "ig_ds_1", "research_run.json"),
    ("datasets", "ig_ds_1", "raw", "ig_prices_raw.json"), ("datasets", "ig_ds_1", "raw", "manifest.json"),
    ("datasets", "ig_ds_1", "normalized", "ig_prices_normalized.csv"), ("datasets", "ig_ds_1", "normalized", "manifest.json"),
}
HOSTILE_PATHS = [
    ("job_1", "final_holdout_access_claim.json"), ("job_1", "Archive.zip"), ("job_1", "archive.zip.bak"), ("job_1", "x.json"),
    ("job_1", "config_used.json"), ("job_1", "data_manifest.json"), ("job_1", "read_intent.json"), ("job_1", "holdout_access"),
    ("validations", "val-oos-1", "validation_run.json"), ("validations", "val-oos-1", "read_intent.json"),
    ("datasets", "ig_ds_1", "raw", "final_holdout_access_claim.json"), ("datasets", "ig_ds_1", "raw", "prices.csv"),
    ("datasets", "ig_ds_1", "plan.json"), ("experiments", "exp.json"), ("plan.json",), ("final_holdout_access_claim.json",),
]


def _inert_rules():
    return [rule for layout in b3.RootLayout for rule in b3.source_rules(layout)
            if rule.entry_class in (EntryClass.INERT_FILE, EntryClass.INERT_DIRECTORY)]


def test_table_is_closed_inert_rules_are_literal_and_enumerated():
    """Précondition n° 1 : chaque nom inerte attendu est apparié, aucun nom inconnu ou hostile ne l'est ; aucun INERT_DIRECTORY."""
    rules = _inert_rules()
    assert rules and all(rule.entry_class is EntryClass.INERT_FILE for rule in rules)
    assert all(type(rule.segments[-1]) is str for rule in rules)           # le NOM inerte est toujours un littéral
    for path in EXPECTED_INERT_PATHS:
        assert sum(rule.matches(path) for rule in rules) == 1, path
    for path in HOSTILE_PATHS:
        assert not any(rule.matches(path) for rule in rules), path


def test_every_read_rule_is_bound_to_an_interpreter_or_an_informative_check():
    for layout in b3.RootLayout:
        for rule in b3.source_rules(layout):
            assert rule.tag is not None
            if rule.entry_class is EntryClass.EXPOSING_JSON:
                assert rule.tag in b3._INTERPRETERS and rule.tag in b3._FALLBACK_KINDS
            elif rule.entry_class is EntryClass.INFORMATIVE_JSON:
                assert rule.tag in b3._INFORMATIVE_TAGS


def test_every_scanner_anomaly_has_an_unresolved_cause():
    """Précondition n° 3 : aucune anomalie de B2 ne peut traverser B3 sans cause typée (exhaustif)."""
    assert set(b3._ANOMALY_CAUSES) == set(SourceAnomaly)


def test_validation_types_known_to_b3_match_the_registered_types():
    assert b3._VALIDATION_TYPES_WINDOW_OPEN | {b3._VALIDATION_OOS} == {
        VALIDATION_TYPE_OOS, VALIDATION_TYPE_WALK_FORWARD, VALIDATION_TYPE_MONTE_CARLO, VALIDATION_TYPE_PARAMETER_STABILITY}


def test_scan_pins_are_carried_and_test_hooks_are_visible(tmp_path):
    """Précondition n° 5 : rules_digest, limits, may_be_empty et hooks_used restent attachés au résultat."""
    results = real_layout_replica(tmp_path)
    plain = interpret(results_root(results))
    hooked = b3.interpret_audit_roots((results_root(results),), LIMITS, holdout_window_start_utc=W[0],
                                      holdout_window_end_utc=W[1], hooks=ScanHooks(after_first_pass=lambda attempt: None))
    assert plain.hooks_used is False and hooked.hooks_used is True
    assert hooked.scans[0].scan.rules_digest == plain.scans[0].scan.rules_digest and hooked.scans[0].scan.limits is LIMITS


_MODULE_TREE = ast.parse(Path(b3.__file__).read_text(encoding="utf-8"))


def test_b3_never_accepts_or_fabricates_observations():
    """Précondition n° 6 : seules les observations retournées par `scan_audit_roots` font foi."""
    public = {name for name, obj in vars(b3).items()
              if callable(obj) and not name.startswith("_") and getattr(obj, "__module__", None) == b3.__name__}
    assert {"interpret_audit_roots", "source_rules"} <= public
    for name in public:
        if inspect.isfunction(getattr(b3, name)):
            assert set(inspect.signature(getattr(b3, name)).parameters) <= {
                "roots", "limits", "holdout_window_start_utc", "holdout_window_end_utc", "hooks", "layout"}, name
    called = {node.func.id for node in ast.walk(_MODULE_TREE) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & {"ScanObservation", "ExposureScan", "ScannedRoot", "open", "eval", "exec", "__import__"}
    attributes = {node.attr for node in ast.walk(_MODULE_TREE) if isinstance(node, ast.Attribute)}
    assert not attributes & {"read_bytes", "read_text", "scandir", "listdir", "walk", "replace_observations"}


def test_b3_imports_neither_engine_nor_e2_nor_dataset_split():
    imported = set()
    for node in ast.walk(_MODULE_TREE):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "hashlib", "json", "os", "dataclasses", "datetime", "enum", "typing",
                        "gate_v_exposure_scan", "gate_v_exposure_sources", "gate_v_final_holdout_protocol",
                        "gate_v_final_holdout_claim"}, imported


def test_findings_satisfy_the_e3a_inventory_contract_and_are_deterministic(tmp_path):
    results = real_layout_replica(tmp_path)
    make_job(results, "job_resolved", job_config("2025-12-01T00:00:00+00:00", "2026-01-15T00:00:00+00:00"))
    first, second = interpret(results_root(results)), interpret(results_root(results))
    assert first.findings == second.findings and first.plans == second.plans
    inventory = build_exposure_inventory(window_start_utc=W[0], window_end_utc=W[1], findings=first.findings,
                                         complete=first.complete, scanned_roots=("res",),
                                         trial_accounting=TrialAccounting(0, 0, 0, 0, 0, 0))
    assert len(inventory.findings) == len(first.findings) == 5


# ── Compléments issus de la passe de mutation (deux survivants : trous de tests) ─────────────────────────────────

from dataset_split import DatasetSplitPlan, SplitBoundary, load_dataset_split_plan  # noqa: E402


_OVERLAPPING_HOLDOUT = (("2026-01-01T00:00:00+00:00", "2026-04-01T00:00:00+00:00"),
                        ("2026-01-01T00:00:00.000000Z", "2026-04-01T00:00:00.000000Z"), OverlapVerdict.OVERLAPS)
_DISJOINT_HOLDOUT = (("2025-06-01T00:00:00+00:00", "2025-09-01T00:00:00+00:00"),
                     ("2025-06-01T00:00:00.000000Z", "2025-09-01T00:00:00.000000Z"), OverlapVerdict.NO_OVERLAP)


@pytest.mark.parametrize("plan_id, train_end, holdout", [
    ("bad id", "2026-01-01T00:00:00+00:00", _OVERLAPPING_HOLDOUT),         # identifiant non portable (espace)
    ("plan-overlap", "2026-02-01T00:00:00+00:00", _OVERLAPPING_HOLDOUT),   # TRAIN chevauche FINAL_HOLDOUT : chronologie invalide
    ("bad id", "2025-06-01T00:00:00+00:00", _DISJOINT_HOLDOUT),
    ("plan-overlap", "2025-07-01T00:00:00+00:00", _DISJOINT_HOLDOUT),
])
def test_plan_validity_beyond_shape_is_dataset_split_responsibility_and_the_verdict_rests_on_the_declared_holdout(
        tmp_path, plan_id, train_end, holdout):
    """23.30.5 : B3 contrôle la forme et les zones `{start, end}` ; l'identifiant portable et la chronologie des zones relèvent de
    `dataset_split` (écriture : `build_dataset_split_plan` ; lecture stricte : `load_dataset_split_plan(strict=True)`, utilisée par
    E2 avant tout Claim). Si un tel plan est lu, B3 l'indexe, mais ni son identifiant ni l'ordre de ses zones n'entrent dans le verdict :
    il ne dépend que de la fenêtre FINAL_HOLDOUT DÉCLARÉE (recoupe `W` ou non), et l'empreinte recalculée suit la formule canonique."""
    declared, expected_window, expected_overlap = holdout
    plan = _other_plan(split_plan_id=plan_id, train={"start": "2020-01-01T00:00:00+00:00", "end": train_end},
                       final_holdout={"start": declared[0], "end": declared[1]})
    with pytest.raises(ValueError):                                   # le composant responsable le refuse à la construction…
        build_dataset_split_plan(split_plan_id=plan_id, dataset_snapshot_id="snap-1",
                                 train=build_split_boundary(plan["train"]["start"], plan["train"]["end"]),
                                 final_holdout=build_split_boundary(plan["final_holdout"]["start"], plan["final_holdout"]["end"]),
                                 created_at=plan["created_at"])
    results = clean_results(tmp_path)
    make_split(results, plan=plan, events=({**EVENT, "split_plan_id": plan_id},), directory="plan-stored")
    with pytest.raises(ValueError):                                   # … et E2 le refuse à la lecture stricte
        load_dataset_split_plan(results / "dataset_splits" / "plan-stored" / "split_plan.json", strict=True)
    result = interpret(results_root(results))
    (entry,) = result.plans                                           # limite connue : B3 l'indexe
    declared_plan = DatasetSplitPlan(split_plan_id=plan_id, dataset_snapshot_id="snap-1", train=SplitBoundary(**plan["train"]),
                                     final_holdout=SplitBoundary(**plan["final_holdout"]), validation=None, discovery_oos=None,
                                     created_at=plan["created_at"])
    assert entry.fingerprint == dataset_split_plan_fingerprint(declared_plan)
    event = finding(result, "split.event:res/dataset_splits/plan-stored/holdout_access/2026-05-01_e1.json")
    assert (event.window_start_utc, event.window_end_utc) == expected_window
    assert event.status is SourceStatus.RESOLVED and event.overlap is expected_overlap


def test_plan_with_an_invalid_train_zone_is_never_indexed(tmp_path):
    results = clean_results(tmp_path)
    make_split(results, plan=_other_plan(train={"start": "2020-01-01T00:00:00", "end": "2026-01-01T00:00:00"}))
    result = interpret(results_root(results))
    assert result.plans == () and "INFORMATIVE_UNRESOLVED:res/dataset_splits/plan-alpha/split_plan.json" in result.incomplete_reasons


def test_unreadable_plan_is_an_incompleteness_never_a_finding(tmp_path):
    """Un plan reste informatif (23.27.1) même illisible : raison d'incomplétude, jamais un finding (hors `inventory_id`)."""
    results = clean_results(tmp_path)
    make_split(results)
    (results / "dataset_splits" / "plan-alpha" / "split_plan.json").write_bytes(b"{broken")
    result = interpret(results_root(results))
    assert not any(f.source_id.startswith(("split.plan", "unknown:")) for f in result.findings)
    assert "INFORMATIVE_UNRESOLVED:res/dataset_splits/plan-alpha/split_plan.json" in result.incomplete_reasons
    assert finding(result, EVENT_ID).unresolved_cause is UnresolvedCause.PLAN_UNRESOLVED


# ── Corrections issues de /code-review (Standards S1, S2 ; Spec a5) ───────────────────────────────────────────────

def test_roots_on_different_drives_are_disjoint_not_a_crash(tmp_path):
    """S1 : `commonpath` lève une ValueError brute entre deux lecteurs Windows ; deux racines disjointes ne sont jamais
    refusées comme imbriquées — ici la seconde, absente, est refusée par B2 avec une défaillance TYPÉE."""
    other_drive = "Z:\\b3-nowhere" if Path(tmp_path).drive.upper() != "Z:" else "Y:\\b3-nowhere"
    with pytest.raises(ExposureScanRefusal) as refusal:
        interpret(results_root(clean_results(tmp_path)), results_root(Path(other_drive), label="res2"))
    assert refusal.value.failure is StructuralFailure.ROOT_MISSING


def test_interpretation_refuses_an_inconsistent_completeness_fact():
    """S2 : `complete` et `incomplete_reasons` ne peuvent jamais se contredire, même construits à la main."""
    with pytest.raises(ValueError):
        b3.SourceInterpretation(b3.B3_SEMANTICS_VERSION, "2026-01-01T00:00:00.000000Z", "2026-04-01T00:00:00.000000Z",
                                (), (), (), complete=True, incomplete_reasons=("UNKNOWN_ENTRY:res/x",), non_oos_validations=(), exposure_evidence=())
    with pytest.raises(ValueError):
        b3.SourceInterpretation(b3.B3_SEMANTICS_VERSION, "2026-01-01T00:00:00.000000Z", "2026-04-01T00:00:00.000000Z",
                                (), (), (), complete=False, incomplete_reasons=(), non_oos_validations=(), exposure_evidence=())


def test_plan_directory_configured_as_its_own_audit_root(tmp_path):
    """Spec a5 : 23.11 étape 1 compte « les répertoires d'événements des plans » parmi les racines d'audit configurées."""
    make_split(tmp_path / "results", directory="plan-alpha")
    plan_dir = tmp_path / "results" / "dataset_splits" / "plan-alpha"
    root = b3.LayoutRoot(b3.RootLayout.SPLIT_PLAN_DIR, AuditRoot("plan1", str(plan_dir)))
    result = interpret(root)
    event = finding(result, "split.event:plan1/holdout_access/2026-05-01_e1.json")
    assert event.status is SourceStatus.RESOLVED and result.plans[0].source_id == "split.plan:plan1/split_plan.json"
    assert result.complete is True
    (plan_dir / "split_plan.json").unlink()
    result = interpret(root)
    assert "MISSING_REQUIRED:plan1/split_plan.json" in result.incomplete_reasons
    assert finding(result, "split.event:plan1/holdout_access/2026-05-01_e1.json").unresolved_cause is UnresolvedCause.PLAN_UNRESOLVED
