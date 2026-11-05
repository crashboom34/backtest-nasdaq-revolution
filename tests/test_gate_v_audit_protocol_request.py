"""N-VIDE-2 / N2-a — requête de configuration stricte : refus typés, jamais d'exception, aucun accès disque avant les refus de configuration, aucune valeur implicite."""

from __future__ import annotations

import dataclasses
import inspect
import os
from unittest import mock

import pytest

import gate_v_audit_protocol as ap
import gate_v_exposure_interpreters_v5 as v5
import gate_v_exposure_scan as scan
from gate_v_exposure_scan import HashLimits, ScanHooks, ScanLimits
from tests.gate_v_audit_protocol_support import (CAMPAIGN, ONE_GROUP_BUDGET, PROTOCOL_LIMITS, RESULTS, campaign_spec, request_for, request_of,
                                                 scenario_dir)
from tests.gate_v_exposure_support import LIMITS, W
from tests.gate_v_manifest_scenarios import CID, HL

R = ap.RefusalCode


def refused(report, *codes):
    assert report.receivability is ap.Receivability.REFUSED and {d.code for d in report.refusals} == set(codes), [(d.code, d.detail) for d in report.refusals]
    assert report.roots == () and report.blocks == () and report.b3_completeness is ap.Completeness.NOT_BUILT and report.rescan is ap.RescanStatus.NOT_PERFORMED
    assert report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE and report.grants == () and report.e3j_prerequisites_unmet != ()
    return report


@pytest.fixture()
def directory(tmp_path):
    return scenario_dir(tmp_path, "01-ready-initial")


@pytest.fixture()
def no_disk(monkeypatch):
    """Aucun refus de configuration ne doit toucher le disque : ni scan, ni `lstat`, ni `scandir`, ni `realpath` pendant l'audit (garde appliquée autour de l'appel seulement)."""
    def boom(*args, **kwargs):
        raise AssertionError("accès disque avant un refus de configuration")
    monkeypatch.setattr(v5, "scan_audit_roots", boom)
    return lambda: (mock.patch.multiple(os, lstat=boom, stat=boom, scandir=boom, listdir=boom), mock.patch.object(os.path, "realpath", boom))


# ── Signature : la requête ne porte que de la configuration ──────────────────────────────────────────────────────────────────────────────────────
def test_the_public_entry_point_takes_exactly_one_request_and_the_request_carries_only_configuration():
    assert list(inspect.signature(ap.audit_campaign_exposure).parameters) == ["request"]
    assert {f.name for f in dataclasses.fields(ap.AuditRequest)} == {"own_campaign_id", "roots", "limits", "hash_limits", "protocol_limits", "window_start_utc",
                                                                      "window_end_utc", "window_declared_source", "window_source", "registry"}      # N2-b1a puis N2-b1b : un bloc optionnel ajouté à chaque fois
    assert {f.name for f in dataclasses.fields(ap.AuditRootSpec)} == {"label", "path", "layout", "expected_name", "may_be_empty"}
    names = " ".join(f.name for cls in (ap.AuditRequest, ap.AuditRootSpec, ap.ProtocolLimits) for f in dataclasses.fields(cls)).lower()
    for forbidden in ("scan", "tree", "interpretation", "inventory", "hook", "finding", "fact", "verdict", "observation"):
        assert forbidden not in names


def test_no_limit_has_a_default_value():
    """N2-b1a / N2-b1b : les seules exemptions sont les blocs OPTIONNELS `window_source` et `registry` (défaut `None` = mode N2-a). Les plafonds, la fenêtre de l'opérateur et les plafonds du
    registre (`RegistryConfig`) restent sans valeur par défaut."""
    defaulted = set()
    for cls in (ap.AuditRequest, ap.ProtocolLimits, ap.RegistryConfig):
        for field in dataclasses.fields(cls):
            if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING:
                defaulted.add((cls.__name__, field.name, field.default))
    assert defaulted == {("AuditRequest", "window_source", None), ("AuditRequest", "registry", None)}


@pytest.mark.parametrize("hostile", [None, 0, "request", {}, [], object(), scan.ExposureScanRefusal, ScanHooks()])
def test_a_non_request_argument_is_refused_never_raised(hostile):
    refused(ap.audit_campaign_exposure(hostile), R.REQUEST_INVALID)


def test_a_subclass_of_the_request_is_refused_because_only_the_exact_type_is_configuration(directory):
    class Smuggler(ap.AuditRequest):
        scan = "forged"
    request = request_of(directory)
    forged = Smuggler(**{f.name: getattr(request, f.name) for f in dataclasses.fields(request)})
    refused(ap.audit_campaign_exposure(forged), R.REQUEST_INVALID)


def test_a_valid_request_is_receivable(directory):
    assert ap.audit_campaign_exposure(request_of(directory)).receivability is ap.Receivability.RECEIVABLE


# ── Configuration hostile ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def hostile_cases(directory):
    spec = campaign_spec(directory)
    skew = object.__new__(HashLimits)
    for name, value in (("max_hashed_file_bytes", 10), ("max_total_hashed_bytes", 5), ("max_hashed_files", 1)):
        object.__setattr__(skew, name, value)
    skew_scan = object.__new__(ScanLimits)
    for field in dataclasses.fields(LIMITS):
        object.__setattr__(skew_scan, field.name, getattr(LIMITS, field.name))
    object.__setattr__(skew_scan, "max_json_bytes", LIMITS.max_total_read_bytes + 1)
    return {
        "own-campaign-not-a-root": (dict(own_campaign_id="gate_v_v2_" + "00" * 32), R.REQUEST_INVALID),
        "own-campaign-not-text": (dict(own_campaign_id=None), R.REQUEST_INVALID),
        "roots-not-a-tuple": (dict(roots=[spec]), R.REQUEST_INVALID),
        "roots-empty": (dict(roots=()), R.REQUEST_INVALID),
        "root-not-a-spec": (dict(roots=(spec, "not-a-spec")), R.REQUEST_INVALID),
        "duplicate-labels": (dict(roots=(spec, campaign_spec(directory))), R.REQUEST_INVALID),
        "relative-path": (dict(roots=(campaign_spec(directory, path="relative/dir"),)), R.REQUEST_INVALID),
        "dotdot-path": (dict(roots=(campaign_spec(directory, path=str(directory) + os.sep + ".." + os.sep + directory.name),)), R.REQUEST_INVALID),
        "non-portable-label": (dict(roots=(campaign_spec(directory, label="bad label"),)), R.REQUEST_INVALID),
        "layout-as-text": (dict(roots=(campaign_spec(directory, layout="CAMPAIGN_DIR"),)), R.REQUEST_INVALID),
        "expected-name-missing": (dict(roots=(campaign_spec(directory, expected_name=None),)), R.REQUEST_INVALID),
        "expected-name-on-results": (dict(roots=(campaign_spec(directory, layout=RESULTS),)), R.REQUEST_INVALID),
        "may-be-empty-not-bool": (dict(roots=(campaign_spec(directory, may_be_empty=1),)), R.REQUEST_INVALID),
        "limits-wrong-type": (dict(limits={"max_roots": 1}), R.REQUEST_INVALID),
        "limits-inconsistent": (dict(limits=skew_scan), R.REQUEST_INVALID),
        "hash-limits-absent": (dict(hash_limits=None), R.HASH_LIMITS_MISSING),
        "hash-limits-wrong-type": (dict(hash_limits={"max_hashed_files": 1}), R.REQUEST_INVALID),
        "hash-limits-contradictory": (dict(hash_limits=skew), R.REQUEST_INVALID),
        "protocol-limits-wrong-type": (dict(protocol_limits=None), R.REQUEST_INVALID),
        "protocol-limits-non-positive": (dict(protocol_limits=ap.ProtocolLimits(max_campaign_roots=0, max_total_read_bytes=ONE_GROUP_BUDGET)), R.REQUEST_INVALID),
        "window-reversed": (dict(window_start_utc=W[1], window_end_utc=W[0]), R.REQUEST_INVALID),
        "window-not-text": (dict(window_start_utc=20260101), R.REQUEST_INVALID),
        "window-naive": (dict(window_start_utc="2026-01-01T00:00:00"), R.REQUEST_INVALID),
        "declared-source-unknown": (dict(window_declared_source="PLAN_AND_SPLIT_LOADED"), R.REQUEST_INVALID),
        "budget-exceeded": (dict(protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=ONE_GROUP_BUDGET - 1)), R.RESOURCE_BUDGET_EXCEEDED),
        "too-many-campaign-roots": (dict(roots=(spec, campaign_spec(directory, label="two", expected_name="gate_v_v2_" + "22" * 32)), protocol_limits=ap.ProtocolLimits(max_campaign_roots=1, max_total_read_bytes=10 * ONE_GROUP_BUDGET)),
                                    R.RESOURCE_BUDGET_EXCEEDED),
        "duplicate-expected-name": (dict(roots=(spec, campaign_spec(directory, label="stale")), protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=10 * ONE_GROUP_BUDGET)), R.REQUEST_INVALID),
        "directory-name-differs-from-expected-name": (dict(roots=(campaign_spec(directory, expected_name="gate_v_v2_" + "11" * 32),), own_campaign_id="gate_v_v2_" + "11" * 32), R.ROOT_FOREIGN),
    }


HOSTILE = sorted(hostile_cases(__import__("pathlib").Path(os.getcwd())))


@pytest.mark.parametrize("name", HOSTILE)
def test_a_hostile_configuration_is_refused_with_the_exact_code_before_any_disk_access(directory, no_disk, name):
    changes, code = hostile_cases(directory)[name]
    base = request_of(directory)
    fields = {f.name: getattr(base, f.name) for f in dataclasses.fields(base)}
    fields.update(changes)
    request = ap.AuditRequest(**fields)
    guard_os, guard_realpath = no_disk()
    with guard_os, guard_realpath:
        report = ap.audit_campaign_exposure(request)
    refused(report, code)


def test_the_read_budget_is_the_documented_conservative_bound_two_scans_per_layout_group(directory, tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    (results / "x").mkdir()
    needs_two_groups = 2 * ONE_GROUP_BUDGET
    specs = (campaign_spec(directory), ap.AuditRootSpec(label="res", path=str(results), layout=RESULTS, expected_name=None, may_be_empty=True))
    refused(ap.audit_campaign_exposure(request_for(*specs, protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=needs_two_groups - 1))), R.RESOURCE_BUDGET_EXCEEDED)
    assert ap.audit_campaign_exposure(request_for(*specs, protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=needs_two_groups))).refusals == ()


def test_a_derived_campaign_root_beside_the_own_campaign_is_accepted_not_refused(tmp_path):
    own = scenario_dir(tmp_path / "a", "01-ready-initial")
    other_name = "gate_v_v2_" + "ee" * 32
    other = tmp_path / "b" / other_name
    other.mkdir(parents=True)
    (other / "plan.json").write_text('{"campaign_id": "%s"}' % other_name)
    report = ap.audit_campaign_exposure(request_for(campaign_spec(own), campaign_spec(other, label="derived"), own=CID))
    assert report.refusals == () and {r.label for r in report.roots} == {"camp", "derived"}
    assert {r.label: r.chain for r in report.roots} == {"camp": ap.ChainStatus.NOT_EVALUATED, "derived": ap.ChainStatus.NOT_EVALUATED}


# ── Refus structurels de B2, convertis en refus typés ────────────────────────────────────────────────────────────────────────────────────────────
def test_a_missing_root_is_a_typed_structural_refusal_carrying_the_b2_code(tmp_path):
    ghost = tmp_path / CID
    report = ap.audit_campaign_exposure(request_for(campaign_spec(ghost)))
    refused(report, R.SCAN_STRUCTURAL_FAILURE)
    assert "ROOT_MISSING" in report.refusals[0].detail


def test_overlapping_roots_are_refused_structurally(tmp_path):
    outer = scenario_dir(tmp_path, "01-ready-initial")
    inner = outer / "validations"
    inner.mkdir()
    report = ap.audit_campaign_exposure(request_for(campaign_spec(outer), campaign_spec(inner, label="inner", layout=RESULTS, expected_name=None, may_be_empty=True)))
    refused(report, R.SCAN_STRUCTURAL_FAILURE)
    assert "ROOT_OVERLAP" in report.refusals[0].detail


def test_an_unknown_non_portable_name_stops_the_scan_and_is_never_interpreted(tmp_path):
    directory = scenario_dir(tmp_path, "01-ready-initial")
    (directory / "bad name.txt").write_text("x")
    report = ap.audit_campaign_exposure(request_of(directory))
    refused(report, R.SCAN_STRUCTURAL_FAILURE)
    assert "NON_PORTABLE_NAME" in report.refusals[0].detail


def test_a_scan_plafond_exceeded_is_a_refusal_never_a_truncation(directory):
    tiny = dataclasses.replace(LIMITS, max_entries=1)
    report = ap.audit_campaign_exposure(request_of(directory, limits=tiny, protocol_limits=PROTOCOL_LIMITS))
    refused(report, R.SCAN_STRUCTURAL_FAILURE)
    assert "LIMIT_EXCEEDED" in report.refusals[0].detail


def test_a_symbolic_link_is_refused_where_the_platform_allows_creating_one(tmp_path):
    directory = scenario_dir(tmp_path, "01-ready-initial")
    try:
        os.symlink(str(directory / "plan.json"), str(directory / "alias.json"))
    except (OSError, NotImplementedError):
        pytest.skip("création de lien symbolique non permise sur ce poste (WinError 1314) : comportement POSIX / liens non démontré ici")
    report = ap.audit_campaign_exposure(request_of(directory))
    refused(report, R.SCAN_STRUCTURAL_FAILURE)
    assert "LINK_OR_REPARSE_POINT" in report.refusals[0].detail


def test_the_refusal_detail_is_bounded_and_the_code_set_is_closed():
    assert ap.MAX_DETAIL_CHARS == 300
    assert {c.value for c in ap.RefusalCode} == {
        "REQUEST_INVALID", "HASH_LIMITS_MISSING", "RESOURCE_BUDGET_EXCEEDED", "ROOT_FOREIGN", "SCAN_STRUCTURAL_FAILURE", "SCAN_UNSTABLE", "SCAN_HOOKS_PRESENT",
        "SCAN_TABLE_MISMATCH", "SCAN_LIMITS_MISMATCH", "SCAN_CONTEXT_MISMATCH", "VERSION_BELOW_MINIMUM", "OBSERVATION_REFUSED", "OBSERVATION_PROJECTION_MISMATCH", "RESCAN_NOT_DISTINCT",
        "RESCAN_STRUCTURAL_FAILURE", "RESCAN_FACT_DRIFT", "RESCAN_IDENTITY_DRIFT", "AUDIT_INTERNAL_FAILURE",
        "WINDOW_SOURCE_INVALID", "PLAN_SPLIT_CONTRADICTION", "WINDOW_MISMATCH", "WINDOW_SOURCE_CHANGED",      # N2-b1a : quatre codes de provenance de W
        "REGISTRY_UNREADABLE", "REGISTRY_CHAIN_HEAD_CHANGED", "STAGE_NOT_DERIVABLE", "B4_ASSEMBLY_REFUSED"}      # N2-b1b : quatre codes du registre
    assert {c.value for c in ap.BlockCode} == {"CHAIN_INCOHERENT", "EMPTINESS_BLOCKING", "DERIVED_COVERAGE_PARTIAL"}


def test_the_spy_proves_no_hook_is_ever_given_to_the_scanner(directory, monkeypatch):
    seen = []
    real = v5.scan_audit_roots
    monkeypatch.setattr(v5, "scan_audit_roots", lambda *a, **k: (seen.append(k.get("hooks")), real(*a, **k))[1])
    ap.audit_campaign_exposure(request_of(directory))
    assert seen == [None, None]


# ── Racines vides et nom réel du dossier ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_an_empty_campaign_root_declared_may_be_empty_is_diagnosed_not_refused(tmp_path):
    empty = tmp_path / CID
    empty.mkdir()
    report = ap.audit_campaign_exposure(request_for(campaign_spec(empty, may_be_empty=True)))
    assert report.refusals == () and report.receivability is ap.Receivability.RECEIVABLE
    (root,) = report.roots
    assert root.manifest_state is ap.ManifestState.ABSENT and root.chain is ap.ChainStatus.NOT_EVALUATED and root.observed_execution_artefacts == 0
    refused(ap.audit_campaign_exposure(request_for(campaign_spec(empty, may_be_empty=False))), R.SCAN_STRUCTURAL_FAILURE)       # sans déclaration : ROOT_EMPTY, comme B2


def test_an_empty_results_root_beside_a_campaign_is_diagnosed_not_refused(directory, tmp_path):
    results = tmp_path / "results_empty"
    results.mkdir()
    spec = ap.AuditRootSpec(label="res", path=str(results), layout=RESULTS, expected_name=None, may_be_empty=True)
    report = ap.audit_campaign_exposure(request_for(campaign_spec(directory), spec))
    assert report.refusals == () and {r.label for r in report.roots} == {"camp", "res"}


def test_the_real_name_on_disk_decides_attribution_not_the_spelling_given_by_the_operator(tmp_path):
    real = tmp_path / ("GATE_V_V2_" + CID[len("gate_v_v2_"):].upper())
    real.mkdir()
    (real / "plan.json").write_text("{}")
    spelled = real.parent / CID
    if not spelled.exists():
        pytest.skip("système de fichiers sensible à la casse : le chemin en minuscules désigne un autre dossier (comportement non démontré ici)")
    refused(ap.audit_campaign_exposure(request_for(campaign_spec(spelled))), R.ROOT_FOREIGN)
