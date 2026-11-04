"""N-VIDE-2 / N2-b1a — provenance DÉCLARATIVE de la fenêtre W, par l'INTERFACE PUBLIQUE (requête → rapport). Fixtures SYNTHÉTIQUES sur disque (`tmp_path`) : un plan de campagne V2 réel,
un `DatasetSplitPlan` réel, des racines CAMPAIGN_DIR et SPLIT_PLAN_DIR. Les attendus sont des littéraux ou des recalculs indépendants du code testé. Le niveau
`SPLIT_PLAN_FINGERPRINT_MATCHED` signifie seulement : les métadonnées du plan V2 et du split plan sont COHÉRENTES et ce sont les octets observés par S1 ; jamais authentiques,
jamais une chronologie, jamais une absence d'exposition, jamais un droit d'accès au holdout."""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import re
from pathlib import Path
from unittest import mock

import pytest

import gate_v_audit_protocol as ap
import gate_v_audit_window as aw
from dataset_split import build_split_boundary
from gate_v_exposure_scan import scan_worst_case_read_bytes
from tests.gate_v_audit_protocol_support import PROTOCOL_LIMITS, campaign_spec, request_for, request_of, scenario_dir, tree_digest
from tests.gate_v_audit_window_support import (CAMPAIGN_LABEL, HOLDOUT, HOLDOUT_NORMALISED, SNAPSHOT_ID, SPLIT_LABEL, SPLIT_PLAN_ID, build_world, derived_request,
                                               forge_plan, independent_fingerprint, lay_out, split_plan, split_spec, window_source)
from tests.gate_v_exposure_support import LIMITS
from tests.gate_v_manifest_scenarios import HL

R = ap.RefusalCode
MATCHED, UNVERIFIED = ap.WindowProvenance.SPLIT_PLAN_FINGERPRINT_MATCHED, ap.WindowProvenance.UNVERIFIED


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("b1a_world"))


@pytest.fixture()
def layout(world, tmp_path):
    return lay_out(tmp_path, world.plan, world.split_plan)


def audit(layout, **changes):
    return ap.audit_campaign_exposure(derived_request(layout, **changes))


def refused(report, *codes):
    assert report.receivability is ap.Receivability.REFUSED and {d.code for d in report.refusals} == set(codes), [(d.code, d.detail) for d in report.refusals]
    assert report.window_provenance is UNVERIFIED and report.window_declared_source in (None, ap.WindowDeclaredSource.OPERATOR_CONFIGURED)
    assert report.grants == () and report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE
    return report


def rewrite(path: Path, edit) -> None:
    before = path.read_bytes()
    after = edit(before)
    assert after != before, "la dégradation n'a rien changé : le test serait vide"
    path.write_bytes(after)


# ── T0 : caractérisation de N2-a (verts AVANT tout code N2-b1a) ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name, facts", [("01-ready-initial", "5167d98fc4aeb9eba3773d2be1a3c288ebbb09661cd9150d7fd09223d3af3f75"),
                                         ("02-wf-declared-directory-absent", "92d4ac2deb6b3a44b18ffdf97d7af9bdcefb36b1f82d98c5aaf519d9569612e5"),
                                         ("25-all-declared-runs-present", "23916504dbfb3690ffffbe8ff1dc3918569ba450404f6cbd1e981ef3429b3d62")])
def test_the_default_mode_facts_digest_is_pinned_to_the_literal_measured_before_n2b1a(tmp_path, name, facts):
    """Épingle le digest F de N2-a (indépendant du chemin) mesuré AVANT toute modification : le mode par défaut ne change pas d'un octet."""
    report = ap.audit_campaign_exposure(request_of(scenario_dir(tmp_path, name)))
    assert report.receivability is ap.Receivability.RECEIVABLE and report.facts_s1 == facts == report.facts_s2
    assert report.window_provenance is UNVERIFIED and report.window_declared_source is ap.WindowDeclaredSource.OPERATOR_CONFIGURED


def test_a_split_plan_directory_root_is_audited_through_the_protocol_without_window_source(layout):
    report = audit(layout, source=None)
    assert report.receivability is ap.Receivability.RECEIVABLE and [r.label for r in report.roots] == [CAMPAIGN_LABEL, SPLIT_LABEL]
    assert report.window_provenance is UNVERIFIED and report.window_declared_source is ap.WindowDeclaredSource.OPERATOR_CONFIGURED


# ── Requête : le bloc est de la configuration, validé en mémoire (aucun accès disque avant un refus de configuration) ─────────────────────────────
def test_the_window_source_block_defaults_to_none_and_carries_only_the_split_plan_root_label():
    assert {f.name for f in dataclasses.fields(ap.WindowSource)} == {"split_plan_root_label"}
    field = next(f for f in dataclasses.fields(ap.AuditRequest) if f.name == "window_source")
    assert field.default is None


@pytest.fixture()
def no_disk(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("accès disque avant un refus de configuration")
    monkeypatch.setattr(ap, "interpret_audit_roots_v6", boom)
    monkeypatch.setattr(aw, "derive_window", boom)
    return lambda: (mock.patch.multiple(os, lstat=boom, stat=boom, scandir=boom, listdir=boom, open=boom), mock.patch.object(os.path, "realpath", boom))


class Smuggler(ap.WindowSource):
    pass


@pytest.mark.parametrize("hostile", ["split", None.__class__, 3, object(), {"split_plan_root_label": SPLIT_LABEL}, ap.WindowSource(split_plan_root_label=None),
                                     ap.WindowSource(split_plan_root_label=3), ap.WindowSource(split_plan_root_label="not-configured"),
                                     ap.WindowSource(split_plan_root_label=CAMPAIGN_LABEL), Smuggler(split_plan_root_label=SPLIT_LABEL)])
def test_a_hostile_window_source_is_refused_in_memory_before_any_disk_access(layout, no_disk, hostile):
    first, second = no_disk()
    with first, second:
        report = audit(layout, source=hostile)
    refused(report, R.REQUEST_INVALID)


def test_the_operator_cannot_declare_the_derived_source_the_protocol_sets_it_itself(layout, no_disk):
    first, second = no_disk()
    with first, second:
        report = audit(layout, source=None, window_declared_source=ap.WindowDeclaredSource.SPLIT_PLAN_REFERENCED)
    refused(report, R.REQUEST_INVALID)


def test_a_report_can_only_claim_the_derived_source_when_receivable_and_with_a_known_value():
    refusal = ap.AuditDefect(R.REQUEST_INVALID, ap.Stage.REQUEST)
    with pytest.raises(ValueError):
        ap.AuditReport(ap.Receivability.REFUSED, refusals=(refusal,), window_declared_source=ap.WindowDeclaredSource.SPLIT_PLAN_REFERENCED)
    with pytest.raises(ValueError):
        ap.AuditReport(ap.Receivability.REFUSED, refusals=(refusal,), window_declared_source="SPLIT_PLAN_REFERENCED")
    assert ap.AuditReport(ap.Receivability.REFUSED, refusals=(refusal,)).window_provenance is UNVERIFIED


# ── Nominal ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_independent_oracle_matches_the_plan_fingerprint(world):
    assert independent_fingerprint(world.split_plan) == world.plan.split_plan_fingerprint


def test_a_coherent_plan_and_split_plan_give_the_matched_level_and_the_normalised_final_holdout_window(layout):
    report = audit(layout)
    assert report.receivability is ap.Receivability.RECEIVABLE and report.window == HOLDOUT_NORMALISED
    assert report.window_declared_source is ap.WindowDeclaredSource.SPLIT_PLAN_REFERENCED and report.window_provenance is MATCHED
    assert MATCHED.value == "SPLIT_PLAN_FINGERPRINT_MATCHED" and ap.WindowDeclaredSource.SPLIT_PLAN_REFERENCED.value == "SPLIT_PLAN_REFERENCED"


def test_a_matched_report_still_grants_nothing_and_proves_neither_authenticity_nor_absence(layout):
    report = audit(layout)
    assert report.grants == () and report.grants_nothing and report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE and report.persistence is ap.Persistence.NOT_PERSISTED
    assert report.e3j_prerequisites_unmet == ap.E3J_PREREQUISITES_UNMET != () and report.independent_rescan_required is True
    assert report.s0_facts is ap.S0Facts.NOT_VERIFIED and report.auxiliary_runs is ap.AuxiliaryRuns.UNQUALIFIED and report.rescan is ap.RescanStatus.PROTOCOL_RESCAN_MATCHED
    assert {"CHRONOLOGY", "SNAPSHOT_ATOMICITY", "INDEPENDENT_RESCAN"} <= set(report.not_proven)


def test_without_window_source_the_report_stays_unverified_even_when_the_files_are_coherent(layout):
    report = audit(layout, source=None)
    assert report.receivability is ap.Receivability.RECEIVABLE and report.window_provenance is UNVERIFIED
    assert report.window_declared_source is ap.WindowDeclaredSource.OPERATOR_CONFIGURED


def test_equivalent_instants_in_another_offset_are_the_same_window(world, tmp_path):
    """Les instants sont comparés après normalisation, jamais lexicalement : même fenêtre exprimée en +02:00 chez l'opérateur ET dans le split plan."""
    shifted = ("2024-06-01T02:00:00+02:00", "2024-09-01T02:00:00+02:00")
    split = split_plan(final_holdout=build_split_boundary(*shifted))
    plan = forge_plan(world.plan, split_plan_fingerprint=independent_fingerprint(split))
    layout = lay_out(tmp_path, plan, split)
    report = audit(layout, window=HOLDOUT)
    assert report.receivability is ap.Receivability.RECEIVABLE and report.window == HOLDOUT_NORMALISED and report.window_provenance is MATCHED
    assert audit(layout, window=shifted).window_provenance is MATCHED


# ── Contradictions : chacune des cinq égalités est refusée SEULE ─────────────────────────────────────────────────────────────────────────────────
def test_a_window_that_differs_from_the_split_plan_final_holdout_is_a_mismatch_never_replaced(layout):
    for window in (("2024-06-02T00:00:00+00:00", HOLDOUT[1]), (HOLDOUT[0], "2024-08-31T23:59:59.999999+00:00"), (HOLDOUT[0], "2024-09-01T00:00:00.000001+00:00")):
        report = refused(audit(layout, window=window), R.WINDOW_MISMATCH)
        assert report.window_provenance is UNVERIFIED


def test_the_plan_split_plan_id_must_equal_the_split_plan_id(world, tmp_path):
    layout = lay_out(tmp_path, forge_plan(world.plan, split_plan_id="plan_y"), world.split_plan)
    refused(audit(layout), R.PLAN_SPLIT_CONTRADICTION)


def test_the_plan_dataset_snapshot_id_must_equal_the_split_plan_snapshot_id(world, tmp_path):
    layout = lay_out(tmp_path, forge_plan(world.plan, dataset_snapshot_id="local_csv:sha256:" + "cd" * 32), world.split_plan)
    refused(audit(layout), R.PLAN_SPLIT_CONTRADICTION)


def test_the_plan_split_fingerprint_must_equal_the_recomputed_fingerprint(world, tmp_path):
    layout = lay_out(tmp_path, forge_plan(world.plan, split_plan_fingerprint="0" * 64), world.split_plan)
    refused(audit(layout), R.PLAN_SPLIT_CONTRADICTION)


def test_a_plan_of_another_campaign_placed_under_the_own_campaign_directory_is_refused(world, tmp_path):
    foreign = lay_out(tmp_path / "foreign", world.plan, world.split_plan)
    own = lay_out(tmp_path / "own", forge_plan(world.plan, split_plan_id="plan_z"), world.split_plan)
    own.plan_file.write_bytes(foreign.plan_file.read_bytes())            # plan V2 valide et cohérent, mais d'une AUTRE campagne que le dossier audité
    refused(audit(own), R.PLAN_SPLIT_CONTRADICTION)


def test_a_changed_split_plan_breaks_the_fingerprint_recorded_in_the_unchanged_plan(world, tmp_path):
    changed = split_plan(final_holdout=build_split_boundary("2024-06-01T00:00:00+00:00", "2024-09-02T00:00:00+00:00"))
    assert independent_fingerprint(changed) != world.plan.split_plan_fingerprint == independent_fingerprint(world.split_plan)
    layout = lay_out(tmp_path, world.plan, changed)                      # plan inchangé (empreinte de l'ancien split plan), split plan modifié
    refused(audit(layout, window=("2024-06-01T00:00:00+00:00", "2024-09-02T00:00:00+00:00")), R.PLAN_SPLIT_CONTRADICTION)


# ── Lecture hostile : aucun repli sur la fenêtre de l'opérateur, jamais le niveau MATCHED ───────────────────────────────────────────────────────
def _drop(path: Path) -> None:
    path.unlink()


def _invalid_json(data: bytes) -> bytes:
    return b"{"


def _bom(data: bytes) -> bytes:
    return b"\xef\xbb\xbf" + data


def _duplicate_key(data: bytes) -> bytes:
    return data.replace(b"{", b'{"split_plan_id": "shadowed", ', 1)


def _not_an_object(data: bytes) -> bytes:
    return b"[1, 2, 3]"


def _oversize(data: bytes) -> bytes:
    return data + b" " * (LIMITS.max_json_bytes + 1)


def _non_finite(data: bytes) -> bytes:
    return re.sub(rb'"created_at":\s*"[^"]*"', b'"created_at": NaN', data)


def _non_finite_plan(data: bytes) -> bytes:
    return re.sub(rb'"search_space_hash":\s*"[^"]*"', b'"search_space_hash": NaN', data)


def _extra_key(data: bytes) -> bytes:
    return data.replace(b"{", b'{"zz": 1, ', 1)


def _empty_created_at(data: bytes) -> bytes:
    return re.sub(rb'"created_at":\s*"[^"]*"', b'"created_at": ""', data)


def _integer_created_at(data: bytes) -> bytes:
    return re.sub(rb'"created_at":\s*"[^"]*"', b'"created_at": 5', data)


def _empty_optional_boundary(data: bytes) -> bytes:
    return re.sub(rb'"validation":\s*\{[^}]*\}', b'"validation": {}', data)


def _missing_key(data: bytes) -> bytes:
    return re.sub(rb',?\s*"discovery_oos":\s*null', b"", data)


SPLIT_DAMAGE = {"missing-key": _missing_key, "invalid-json": _invalid_json, "bom": _bom, "duplicate-key": _duplicate_key, "not-an-object": _not_an_object, "oversize": _oversize,
                "non-finite": _non_finite, "extra-key": _extra_key, "empty-created-at-no-clock": _empty_created_at, "integer-created-at": _integer_created_at,
                "empty-optional-boundary": _empty_optional_boundary}


@pytest.mark.parametrize("damage", sorted(SPLIT_DAMAGE))
def test_a_damaged_split_plan_is_a_typed_refusal_and_never_the_matched_level(layout, damage):
    rewrite(layout.split_file, SPLIT_DAMAGE[damage])
    refused(audit(layout), R.WINDOW_SOURCE_INVALID)


PLAN_DAMAGE = {k: v for k, v in SPLIT_DAMAGE.items() if k not in {"empty-created-at-no-clock", "integer-created-at", "empty-optional-boundary", "non-finite", "missing-key"}}
PLAN_DAMAGE["missing-key"] = lambda data: re.sub(rb',\s*"policy_git_sha":\s*"[^"]*"', b"", data)
PLAN_DAMAGE["non-finite"] = _non_finite_plan


@pytest.mark.parametrize("damage", sorted(PLAN_DAMAGE))
def test_a_damaged_plan_is_a_typed_refusal_and_never_the_matched_level(layout, damage):
    rewrite(layout.plan_file, PLAN_DAMAGE[damage])
    refused(audit(layout), R.WINDOW_SOURCE_INVALID)


def test_a_plan_that_is_a_valid_object_but_not_a_plan_v2_is_refused(layout):
    layout.plan_file.write_bytes(json.dumps({"campaign_id": layout.campaign_id}).encode())
    refused(audit(layout), R.WINDOW_SOURCE_INVALID)


@pytest.mark.parametrize("which, sibling", [("plan_file", "campaign_dir"), ("split_file", "split_dir")])
def test_a_missing_source_file_is_refused_not_replaced_by_the_operator_window(layout, which, sibling):
    (getattr(layout, sibling) / ("exposure" if which == "plan_file" else "holdout_access")).mkdir()       # racine NON vide : le refus vient de la provenance, pas du scanner
    _drop(getattr(layout, which))
    refused(audit(layout), R.WINDOW_SOURCE_INVALID)


@pytest.mark.parametrize("which", ["plan_file", "split_file"])
def test_a_source_file_missing_from_an_otherwise_empty_root_keeps_the_scanner_structural_refusal_of_n2a(layout, which):
    _drop(getattr(layout, which))
    refused(audit(layout), R.SCAN_STRUCTURAL_FAILURE)


@pytest.mark.parametrize("which", ["plan_file", "split_file"])
def test_a_directory_in_place_of_the_source_file_is_refused(layout, which):
    path = getattr(layout, which)
    path.unlink()
    path.mkdir()
    refused(audit(layout), R.WINDOW_SOURCE_INVALID)


def test_a_file_whose_name_differs_only_by_case_is_not_the_source_file(layout):
    layout.split_file.rename(layout.split_dir / "SPLIT_PLAN.JSON")
    refused(audit(layout), R.WINDOW_SOURCE_INVALID)


def test_a_symbolic_link_in_place_of_the_split_plan_is_refused(layout, tmp_path):
    target = tmp_path / "outside.json"
    target.write_bytes(layout.split_file.read_bytes())
    layout.split_file.unlink()
    try:
        os.symlink(target, layout.split_file)
    except (OSError, NotImplementedError):
        pytest.skip("liens symboliques indisponibles sur ce poste (WinError 1314)")
    refused(audit(layout), R.WINDOW_SOURCE_INVALID)


@pytest.mark.parametrize("which", ["plan_file", "split_file"])
def test_a_hard_linked_source_is_refused_because_its_content_lives_outside_the_audited_root(layout, tmp_path, which):
    try:
        os.link(getattr(layout, which), tmp_path / "outside.json")
    except (OSError, NotImplementedError):
        pytest.skip("liens physiques indisponibles")
    refused(audit(layout), R.WINDOW_SOURCE_INVALID)


# ── Concurrence : les sources sont liées aux octets de S1, puis relues après S2 ───────────────────────────────────────────────────────────────────
class Race:
    """Enveloppe l'appel RÉEL à B3 v6 (module patché par son nom, technique de N2-a) et modifie VRAIMENT le disque avant ou après le Ne appel."""

    def __init__(self, calls, action):
        self.calls, self.action, self.count, self.real = calls, action, 0, ap.interpret_audit_roots_v6

    def __call__(self, *args, **kwargs):
        self.count += 1
        if (self.count, "before") in self.calls:
            self.action(self.count)
        result = self.real(*args, **kwargs)
        if (self.count, "after") in self.calls:
            self.action(self.count)
        return result


def touch_with_whitespace(path: Path):
    return lambda _count: path.write_bytes(path.read_bytes() + b"\n")


def test_a_plan_changed_after_s1_is_a_changed_source(layout):
    with mock.patch.object(ap, "interpret_audit_roots_v6", Race({(1, "after")}, touch_with_whitespace(layout.plan_file))):
        report = refused(audit(layout), R.WINDOW_SOURCE_CHANGED)
    assert report.rescan is ap.RescanStatus.NOT_PERFORMED


def test_a_split_plan_changed_between_s1_and_s2_is_a_fact_drift_of_the_existing_protocol(layout):
    with mock.patch.object(ap, "interpret_audit_roots_v6", Race({(2, "before")}, touch_with_whitespace(layout.split_file))):
        refused(audit(layout), R.RESCAN_FACT_DRIFT)


@pytest.mark.parametrize("which", ["plan_file", "split_file"])
def test_a_source_changed_after_s2_is_detected_by_the_final_reread(layout, which):
    with mock.patch.object(ap, "interpret_audit_roots_v6", Race({(2, "after")}, touch_with_whitespace(getattr(layout, which)))):
        report = refused(audit(layout), R.WINDOW_SOURCE_CHANGED)
    assert report.rescan is ap.RescanStatus.PROTOCOL_RESCAN_MATCHED and report.facts_s1 == report.facts_s2 is not None


def test_a_plan_replaced_while_the_historical_loader_reads_it_is_a_changed_source(layout):
    real = aw.load_gate_v_campaign_plan_v2

    def racing(path):
        loaded = real(path)
        Path(path).write_bytes(Path(path).read_bytes() + b"\n")
        return loaded
    with mock.patch.object(aw, "load_gate_v_campaign_plan_v2", racing):
        refused(audit(layout), R.WINDOW_SOURCE_CHANGED)


def test_a_read_error_after_s1_is_a_typed_refusal_never_an_exception(layout):
    state = {"armed": False}
    real = os.lstat

    def lstat(path, *args, **kwargs):
        if state["armed"] and str(path).endswith("plan.json") and not str(path).endswith("split_plan.json"):
            raise PermissionError("simulated")
        return real(path, *args, **kwargs)
    race = Race({(1, "after")}, lambda _count: state.update(armed=True))
    with mock.patch.object(ap, "interpret_audit_roots_v6", race), mock.patch.object(os, "lstat", lstat):
        refused(audit(layout), R.WINDOW_SOURCE_INVALID)


def test_a_change_after_the_final_reread_is_not_detectable_and_the_report_says_it_does_not_prove_atomicity(layout):
    report = audit(layout)
    layout.plan_file.write_bytes(layout.plan_file.read_bytes() + b"\n")
    assert report.window_provenance is MATCHED and "SNAPSHOT_ATOMICITY" in report.not_proven


def test_a_reparse_point_appearing_after_s2_is_a_changed_source(layout):
    """Le test structurel est le même que celui du scanner (lien, jonction, point d'analyse) ; simulé par un `lstat` truqué car les liens sont indisponibles sur ce poste."""
    state, real = {"armed": False}, os.lstat

    def lstat(path, *args, **kwargs):
        info = real(path, *args, **kwargs)
        if state["armed"] and str(path).endswith("split_plan.json"):
            return type("Reparse", (), {"st_mode": info.st_mode, "st_file_attributes": 0x400, "st_nlink": 1, "st_size": info.st_size, "st_ino": info.st_ino, "st_dev": info.st_dev})()
        return info
    with mock.patch.object(ap, "interpret_audit_roots_v6", Race({(2, "after")}, lambda _count: state.update(armed=True))), mock.patch.object(os, "lstat", lstat):
        refused(audit(layout), R.WINDOW_SOURCE_CHANGED)


def test_a_source_renamed_by_case_after_s2_is_a_changed_source_even_though_the_bytes_are_identical(layout):
    def rename(_count):
        layout.split_file.rename(layout.split_dir / "SPLIT_PLAN.JSON")
    with mock.patch.object(ap, "interpret_audit_roots_v6", Race({(2, "after")}, rename)):
        refused(audit(layout), R.WINDOW_SOURCE_CHANGED)


@pytest.mark.parametrize("field, value", [("content_hash", "0" * 64), ("split_plan_id", "plan_other"), ("fingerprint", "0" * 64), ("dataset_snapshot_id", "local_csv:sha256:" + "cd" * 32),
                                          ("final_holdout_end_utc", "2024-09-02T00:00:00.000000Z"), ("source_id", "split.plan:decoy/split_plan.json")])
def test_a_plan_index_that_disagrees_with_the_strict_reconstruction_is_refused(layout, field, value):
    """Lecture indépendante de B3 : si l'index des plans de l'interpréteur ne porte pas les mêmes octets, identités et bornes, la provenance est refusée."""
    real = ap.interpret_audit_roots_v6

    def tampered(*args, **kwargs):
        result = real(*args, **kwargs)
        return dataclasses.replace(result, plans=tuple(dataclasses.replace(entry, **{field: value}) for entry in result.plans)) if result.plans else result
    with mock.patch.object(ap, "interpret_audit_roots_v6", tampered):
        report = audit(layout)
    refused(report, R.WINDOW_SOURCE_INVALID)


def test_an_empty_plan_index_is_refused_never_read_as_nothing_to_compare(layout):
    real = ap.interpret_audit_roots_v6
    with mock.patch.object(ap, "interpret_audit_roots_v6", lambda *a, **k: dataclasses.replace(real(*a, **k), plans=())):
        refused(audit(layout), R.WINDOW_SOURCE_INVALID)


@pytest.mark.parametrize("field, value", [("campaign_id", "gate_v_v2_" + "00" * 32), ("split_plan_id", "plan_other"), ("dataset_snapshot_id", "local_csv:sha256:" + "cd" * 32),
                                          ("split_plan_fingerprint", "0" * 64)])
def test_a_loaded_plan_that_disagrees_with_the_expected_identity_is_a_contradiction_even_if_the_bytes_of_s1_are_coherent(layout, world, field, value):
    """Chaque égalité est vérifiée sur le plan CHARGÉ : un chargeur qui rendrait une autre identité que celle attendue est refusé, les octets de S1 fussent-ils cohérents."""
    tampered = dataclasses.replace(world.plan, **{field: value})
    with mock.patch.object(aw, "load_gate_v_campaign_plan_v2", lambda path: tampered):
        refused(audit(layout), R.PLAN_SPLIT_CONTRADICTION)


def test_a_loader_result_that_disagrees_with_the_strict_record_of_s1_is_a_contradiction(world, tmp_path):
    """Le plan chargé doit être celui de l'enregistrement strict de S1 : sur disque, un plan cohérent mais de split_plan_id différent ; le chargeur « rend » l'identité attendue."""
    forged = forge_plan(world.plan, split_plan_id="plan_y")
    layout = lay_out(tmp_path, forged, world.split_plan)
    consistent_for_the_loader = dataclasses.replace(world.plan, campaign_id=forged.campaign_id)          # passe les quatre égalités du plan chargé
    with mock.patch.object(aw, "load_gate_v_campaign_plan_v2", lambda path: consistent_for_the_loader):
        report = refused(audit(layout), R.PLAN_SPLIT_CONTRADICTION)
    assert "enregistrement strict" in report.refusals[0].detail


def test_a_plan_the_historical_loader_refuses_is_a_refusal_even_if_its_json_is_strict(layout):
    with mock.patch.object(aw, "load_gate_v_campaign_plan_v2", mock.Mock(side_effect=RecursionError("deep"))):
        refused(audit(layout), R.WINDOW_SOURCE_INVALID)


def test_two_split_plan_roots_only_the_designated_one_is_used(layout, tmp_path):
    from dataset_split import save_dataset_split_plan
    decoy_dir = tmp_path / "decoy"
    decoy_dir.mkdir()
    save_dataset_split_plan(decoy_dir / "split_plan.json", split_plan(split_plan_id="plan_decoy", final_holdout=build_split_boundary("2024-06-01T00:00:00+00:00", "2024-09-02T00:00:00+00:00")))

    def request(label):
        return request_for(campaign_spec(layout.campaign_dir, label=CAMPAIGN_LABEL), split_spec(layout), split_spec(layout, label="decoy", path=str(decoy_dir)), own=layout.campaign_id,
                           window_start_utc=HOLDOUT[0], window_end_utc=HOLDOUT[1], window_source=window_source(split_plan_root_label=label))
    assert ap.audit_campaign_exposure(request(SPLIT_LABEL)).window_provenance is MATCHED
    refused(ap.audit_campaign_exposure(request("decoy")), R.PLAN_SPLIT_CONTRADICTION)


def test_a_matched_report_cannot_be_rebuilt_without_its_evidence_and_is_not_a_credential(layout):
    report = audit(layout)
    assert report.window_provenance is MATCHED and "PLAN_SOURCES_AUTHENTICITY" in report.not_proven
    for changes in (dict(window=None), dict(facts_s2="0" * 64), dict(facts_s1=None, facts_s2=None), dict(identity_s2="0" * 64), dict(roots=()), dict(roots=report.roots[:1])):
        with pytest.raises(ValueError):
            dataclasses.replace(report, **changes)


# ── Budget : les lectures supplémentaires n'existent que si window_source est configuré ──────────────────────────────────────────────────────────
def test_the_extra_json_reads_are_counted_only_when_window_source_is_configured(layout):
    base = 2 * 2 * scan_worst_case_read_bytes(LIMITS, HL)                 # deux dispositions : campagne et split plan
    exact = dataclasses.replace(PROTOCOL_LIMITS, max_total_read_bytes=base)
    assert audit(layout, source=None, protocol_limits=exact).receivability is ap.Receivability.RECEIVABLE
    refused(audit(layout, protocol_limits=exact), R.RESOURCE_BUDGET_EXCEEDED)
    enough = dataclasses.replace(PROTOCOL_LIMITS, max_total_read_bytes=base + 6 * LIMITS.max_json_bytes)
    assert audit(layout, protocol_limits=enough).receivability is ap.Receivability.RECEIVABLE
    below = dataclasses.replace(PROTOCOL_LIMITS, max_total_read_bytes=base + 6 * LIMITS.max_json_bytes - 1)
    refused(audit(layout, protocol_limits=below), R.RESOURCE_BUDGET_EXCEEDED)


# ── Science : lecture seule, aucun accès au holdout, aucune écriture, aucun A0 ───────────────────────────────────────────────────────────────────
def test_the_audit_writes_nothing_even_on_a_refusal_and_creates_no_registry_a0_or_reservation_file(layout, tmp_path):
    before = tree_digest(tmp_path)
    names = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")}
    audit(layout)
    rewrite(layout.split_file, _duplicate_key)
    refused(audit(layout), R.WINDOW_SOURCE_INVALID)
    rewrite(layout.split_file, lambda data: data.replace(b'{"split_plan_id": "shadowed", ', b"{", 1))
    assert tree_digest(tmp_path) == before
    assert {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")} == names


def test_an_empty_holdout_directory_next_to_the_split_plan_does_not_disturb_the_derivation(layout):
    (layout.split_dir / "holdout_access").mkdir()
    report = audit(layout)
    assert report.receivability is ap.Receivability.RECEIVABLE and report.window_provenance is MATCHED


# ── Le module de provenance : pur, borné, sans autorité (garde AST) ─────────────────────────────────────────────────────────────────────────────
SOURCE = Path(aw.__file__).read_text(encoding="utf-8")


def test_the_window_module_imports_only_the_documented_modules_and_writes_nothing():
    tree = ast.parse(SOURCE)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "dataclasses", "enum", "hashlib", "os", "stat", "typing", "dataset_split", "gate_v_campaign_plan_v2", "gate_v_exposure_interpreters",
                        "gate_v_exposure_scan", "gate_v_exposure_sources"}, imported
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "open" not in calls and not {"write", "write_bytes", "write_text", "mkdir", "unlink", "rename", "replace", "remove", "rmdir", "makedirs", "utime", "now", "time",
                                         "popen", "system", "run"} & attributes
    for forbidden in ("save_exclusive", "save_atomic", "save_dataset_split_plan", "load_dataset_split_plan", "load_json_tolerant", "validate_gate_v_campaign_plan_v2_sources",
                      "subprocess", "datetime", "pandas", "read_csv", "holdout_access", "nasdaq_3m", "mt5"):
        assert forbidden not in SOURCE, forbidden


def test_the_window_module_never_names_the_protocol_or_the_historical_interpreters_d11():
    for forbidden in ("gate_v_audit_protocol", "gate_v_exposure_interpreters_v", "interpret_audit_roots"):
        assert forbidden not in SOURCE, forbidden
    assert re.search(r"gate_v_k1s2_(verifier|observations|emptiness)", SOURCE) is None
