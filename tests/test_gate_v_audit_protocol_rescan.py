"""N-VIDE-2 / N2-a — S1 / S2 : un seul scanner (B3 v6 → B2), un second appel FRAIS, comparaison des projections F (faits) et I (identité et contexte), refus défensifs.
Un faux interpréteur n'est injecté que par `mock.patch` du nom `interpret_audit_roots_v6` du module ; aucune API publique n'accepte d'objet de scan."""

from __future__ import annotations

import dataclasses
import os
from unittest import mock

import pytest

import gate_v_audit_protocol as ap
import gate_v_exposure_interpreters as b3
import gate_v_exposure_interpreters_v5 as v5
import gate_v_exposure_interpreters_v6 as v6
import gate_v_exposure_scan as scan
import gate_v_k1s2_observations as obs
import gate_v_k1s2_verifier as vf
from tests.gate_v_audit_protocol_support import RESULTS, campaign_spec, request_for, request_of, scenario_dir, tree_digest
from tests.gate_v_exposure_support import LIMITS, W
from tests.gate_v_manifest_scenarios import CID, HL

R = ap.RefusalCode


def real(roots, limits, **kwargs):
    return v6.interpret_audit_roots_v6(roots, limits, **kwargs)


class Between:
    """Interpréteur de test : le vrai B3 v6, avec une action exécutée ENTRE le premier et le second appel (le disque change pendant l'audit)."""

    def __init__(self, action=None, *, first=None, second=None):
        self.calls, self.action, self.first, self.second = [], action, first, second

    def __call__(self, roots, limits, **kwargs):
        self.calls.append(roots)
        result = real(roots, limits, **kwargs)
        if len(self.calls) == 1:
            if self.action is not None:
                self.action()
            return self.first(result) if self.first else result
        return self.second(result) if self.second else result


def audit(request, interpreter):
    """Le protocole appelle `interpret_audit_roots_v6` par un nom de module : le test le remplace par un faux qui ENVELOPPE le vrai B3 v6 (aucun paramètre privé)."""
    with mock.patch.object(ap, "interpret_audit_roots_v6", interpreter):
        return ap.audit_campaign_exposure(request)


def refused(report, *codes):
    assert report.receivability is ap.Receivability.REFUSED and {d.code for d in report.refusals} == set(codes), [(d.code, d.detail) for d in report.refusals]
    return report


@pytest.fixture()
def directory(tmp_path):
    return scenario_dir(tmp_path, "07-running-validations-empty")


# ── Un seul scanner, appelé deux fois par disposition, jamais avec des hooks ─────────────────────────────────────────────────────────────────────
def test_the_scanner_is_called_exactly_twice_per_layout_group_and_only_through_b3_v6(directory, tmp_path, monkeypatch):
    calls = []
    real_scan = v5.scan_audit_roots
    monkeypatch.setattr(v5, "scan_audit_roots", lambda *a, **k: (calls.append(k.get("hooks")), real_scan(*a, **k))[1])
    ap.audit_campaign_exposure(request_of(directory))
    assert calls == [None, None]
    results = tmp_path / "results"
    (results / "job").mkdir(parents=True)
    calls.clear()
    spec = ap.AuditRootSpec(label="res", path=str(results), layout=RESULTS, expected_name=None, may_be_empty=True)
    ap.audit_campaign_exposure(request_for(campaign_spec(directory), spec))
    assert len(calls) == 4 and set(calls) == {None}


def test_the_second_scan_is_a_fresh_call_with_fresh_root_objects(directory):
    spy = Between()
    report = audit(request_of(directory), spy)
    assert report.rescan is ap.RescanStatus.PROTOCOL_RESCAN_MATCHED and len(spy.calls) == 2
    first, second = spy.calls
    assert first is not second and all(a is not b and a.root is not b.root for a, b in zip(first, second))
    assert tuple(type(item) for item in first) == (b3.LayoutRoot,)


def test_an_interpreter_that_returns_the_same_object_twice_is_refused_as_not_distinct(directory):
    cache = []

    def memo(roots, limits, **kwargs):
        if not cache:
            cache.append(real(roots, limits, **kwargs))
        return cache[0]
    refused(audit(request_of(directory), memo), R.RESCAN_NOT_DISTINCT)


def test_an_interpreter_that_reuses_the_scan_of_s1_inside_a_new_interpretation_is_refused_as_not_distinct(directory):
    first = []

    def reuse(roots, limits, **kwargs):
        result = real(roots, limits, **kwargs)
        if not first:
            first.append(result)
            return result
        return dataclasses.replace(result, scans=first[0].scans)
    refused(audit(request_of(directory), reuse), R.RESCAN_NOT_DISTINCT)


# ── Dérive entre S1 et S2 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_file_added_between_the_scans_is_a_fact_drift(directory):
    refused(audit(request_of(directory), Between(lambda: (directory / "stray.txt").write_text("x"))), R.RESCAN_FACT_DRIFT)


def test_an_extra_directory_even_empty_is_never_ignored(directory):
    refused(audit(request_of(directory), Between(lambda: (directory / "extra_empty").mkdir())), R.RESCAN_FACT_DRIFT)


def test_a_file_deleted_between_the_scans_is_a_fact_drift(directory):
    refused(audit(request_of(directory), Between(lambda: (directory / "plan.json").unlink())), R.RESCAN_FACT_DRIFT)


def test_a_read_file_modified_with_the_same_size_is_a_fact_drift(directory):
    manifest = directory / "manifest.json"
    original = manifest.read_bytes()
    flipped = original.replace(b"READY", b"RUNNI") if b"READY" in original else original[:-2] + b"  "
    assert len(flipped) == len(original) and flipped != original
    refused(audit(request_of(directory), Between(lambda: manifest.write_bytes(flipped))), R.RESCAN_FACT_DRIFT)


def test_a_content_change_that_alters_no_interpretation_is_still_a_fact_drift_by_hash(directory):
    """Même taille, même interprétation B3 (un caractère hexadécimal d'un champ non interprété change) : seule l'empreinte de contenu distingue S1 de S2."""
    manifest = directory / "manifest.json"
    text = manifest.read_text()
    key = '"preregistration_id": "'
    at = text.index(key) + len(key)
    flipped = text[:at] + ("1" if text[at] != "1" else "2") + text[at + 1:]
    assert len(flipped) == len(text) and flipped != text
    before = ap.audit_campaign_exposure(request_of(directory))
    assert before.receivability is ap.Receivability.RECEIVABLE
    refused(audit(request_of(directory), Between(lambda: manifest.write_text(flipped))), R.RESCAN_FACT_DRIFT)
    assert before.incomplete_reasons == ap.audit_campaign_exposure(request_of(directory)).incomplete_reasons          # l'interprétation n'a pas changé : seul le contenu diffère


def test_a_difference_confined_to_the_interpretation_reasons_or_the_rule_tags_is_a_fact_drift(directory):
    def other_reasons(result):
        return dataclasses.replace(result, incomplete_reasons=result.incomplete_reasons + ("EXTRA:camp",), complete=False)

    def other_tag(result):
        item = result.scans[0]
        first = dataclasses.replace(item.scan.observations[0], rule_tag="other.tag")
        return dataclasses.replace(result, scans=(b3.InterpretedScan(item.layout, dataclasses.replace(item.scan, observations=(first,) + item.scan.observations[1:])),))
    refused(audit(request_of(directory), Between(second=other_reasons)), R.RESCAN_FACT_DRIFT)
    refused(audit(request_of(directory), Between(second=other_tag)), R.RESCAN_FACT_DRIFT)


def test_a_root_identity_or_limits_change_between_the_scans_is_an_identity_drift(directory):
    def other_inode(result):
        item = result.scans[0]
        root = dataclasses.replace(item.scan.roots[0], st_ino=item.scan.roots[0].st_ino + 1)
        return dataclasses.replace(result, scans=(b3.InterpretedScan(item.layout, dataclasses.replace(item.scan, roots=(root,))),))
    refused(audit(request_of(directory), Between(second=other_inode)), R.RESCAN_IDENTITY_DRIFT)


def test_a_touch_alone_is_an_identity_drift_never_silently_accepted(directory):
    manifest = directory / "manifest.json"
    stat = manifest.stat()
    refused(audit(request_of(directory), Between(lambda: os.utime(manifest, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000)))), R.RESCAN_IDENTITY_DRIFT)


def test_a_forged_first_scan_that_differs_from_the_real_second_scan_is_a_drift(directory):
    def drop_an_observation(result):
        item = result.scans[0]
        forged = dataclasses.replace(item.scan, observations=item.scan.observations[:-1])
        return dataclasses.replace(result, scans=(b3.InterpretedScan(item.layout, forged),))
    refused(audit(request_of(directory), Between(first=drop_an_observation)), R.RESCAN_FACT_DRIFT)       # limite T2 : un faux cohérent aux DEUX appels resterait indistinguable (non testé)


def test_s2_failing_structurally_is_a_typed_refusal_and_s1_alone_is_never_used_as_a_fallback(directory):
    def second(result):
        raise scan.ExposureScanRefusal(scan.StructuralFailure.ROOT_MISSING, "gone", root_label="camp")
    report = refused(audit(request_of(directory), Between(second=second)), R.RESCAN_STRUCTURAL_FAILURE)
    assert report.roots == () and report.rescan is ap.RescanStatus.NOT_PERFORMED


def test_s1_instability_is_a_typed_refusal_without_any_retry_loop_of_the_protocol(directory):
    calls = []

    def unstable(roots, limits, **kwargs):
        calls.append(1)
        raise scan.ExposureScanRefusal(scan.StructuralFailure.UNSTABLE_LISTING, "changed")
    refused(audit(request_of(directory), unstable), R.SCAN_UNSTABLE)
    assert len(calls) == 1


def test_the_drift_report_names_the_first_difference_and_exposes_both_digests(directory):
    report = audit(request_of(directory), Between(lambda: (directory / "stray.txt").write_text("x")))
    assert report.rescan is ap.RescanStatus.DRIFT and report.facts_s1 != report.facts_s2 and "stray.txt" in report.refusals[0].detail
    assert len(report.facts_s1) == len(report.facts_s2) == 64


def test_matching_scans_prove_neither_atomicity_nor_chronology_and_say_so(directory):
    report = ap.audit_campaign_exposure(request_of(directory))
    assert report.rescan is ap.RescanStatus.PROTOCOL_RESCAN_MATCHED
    assert {"SNAPSHOT_ATOMICITY", "CHRONOLOGY", "INDEPENDENT_RESCAN"} <= set(report.not_proven) and report.independent_rescan_required is True


# ── Admissibilité défensive de ce que renvoie l'interpréteur ─────────────────────────────────────────────────────────────────────────────────────
def patch_scan(**changes):
    def apply(result):
        item = result.scans[0]
        return dataclasses.replace(result, scans=(b3.InterpretedScan(item.layout, dataclasses.replace(item.scan, **changes)),))
    return apply


@pytest.mark.parametrize("first,code", [
    (patch_scan(hooks_used=True), R.SCAN_HOOKS_PRESENT),
    (patch_scan(rules_digest="0" * 64), R.SCAN_TABLE_MISMATCH),
    (patch_scan(limits=dataclasses.replace(LIMITS, max_entries=LIMITS.max_entries + 1)), R.SCAN_LIMITS_MISMATCH),
    (patch_scan(hash_limits=None), R.SCAN_LIMITS_MISMATCH),
    (patch_scan(hash_limits=dataclasses.replace(HL, max_hashed_files=HL.max_hashed_files + 1)), R.SCAN_LIMITS_MISMATCH),
    (lambda result: dataclasses.replace(result, semantics_version="gate_v_exposure_interpreters_v7"), R.VERSION_BELOW_MINIMUM),
    (lambda result: dataclasses.replace(result, holdout_window_start_utc="2025-01-01T00:00:00+00:00"), R.SCAN_CONTEXT_MISMATCH),
    (lambda result: dataclasses.replace(result, scans=()), R.ROOT_FOREIGN),
    (lambda result: "not an interpretation", R.SCAN_CONTEXT_MISMATCH),
])
def test_an_inadmissible_first_interpretation_is_refused_with_the_exact_defensive_code(directory, first, code):
    refused(audit(request_of(directory), Between(first=first)), code)


def test_a_scan_of_a_root_that_was_not_configured_is_refused_as_foreign(directory, tmp_path):
    other = tmp_path / "elsewhere" / directory.name
    other.mkdir(parents=True)
    (other / "plan.json").write_text("{}")

    def swapped(roots, limits, **kwargs):
        return real((b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, scan.AuditRoot("camp", str(other))),), limits, **kwargs)
    refused(audit(request_of(directory), swapped), R.ROOT_FOREIGN)


@pytest.mark.parametrize("name", ["gate_v_exposure_interpreters_v4", "gate_v_exposure_interpreters_v5"])
def test_v4_and_v5_are_refused_for_the_new_protocol_but_stay_readable_historically(directory, name):
    def old(roots, limits, *, hash_limits, holdout_window_start_utc, holdout_window_end_utc, **kw):
        if name.endswith("v4"):
            return b3.interpret_audit_roots(roots, limits, holdout_window_start_utc=holdout_window_start_utc, holdout_window_end_utc=holdout_window_end_utc)
        return v5.interpret_audit_roots_v5(roots, limits, hash_limits=hash_limits, holdout_window_start_utc=holdout_window_start_utc, holdout_window_end_utc=holdout_window_end_utc)
    refused(audit(request_of(directory), old), R.VERSION_BELOW_MINIMUM)
    roots = (b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, scan.AuditRoot("camp", str(directory))),)
    assert old(roots, LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1]).semantics_version == name


def test_the_accepted_version_list_is_exactly_v6_and_the_default_interpreter_is_v6(directory):
    assert ap.AUDIT_B3_ACCEPTED == ("gate_v_exposure_interpreters_v6",) and ap.AUDIT_PROTOCOL_VERSION == "gate_v_audit_protocol_v2"
    assert ap.audit_campaign_exposure(request_of(directory)).b3_semantics_version == v6.B3_V6_SEMANTICS_VERSION


# ── L3-A : conversion, projection, refus ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_l3a_receives_only_scans_taken_from_s1_and_a_refusal_of_the_adapter_is_typed(directory, monkeypatch):
    seen = []
    real_convert = obs.observed_tree_from_scan

    def spy(scan_, **kwargs):
        seen.append(scan_)
        return real_convert(scan_, **kwargs)
    monkeypatch.setattr(obs, "observed_tree_from_scan", spy)
    spy_interpreter = Between()
    audit(request_of(directory), spy_interpreter)
    assert len(seen) == 1 and seen[0] is not None
    monkeypatch.setattr(obs, "observed_tree_from_scan", lambda *a, **k: (_ for _ in ()).throw(vf.ObservationRefused(vf.ObservationRefusal.BAD_TREE, "x")))
    report = audit(request_of(directory), Between())
    refused(report, R.OBSERVATION_REFUSED)
    assert report.refusals[0].root_label == "camp"


def test_a_tree_that_lost_an_entry_in_the_conversion_is_detected_by_the_independent_projection(directory, monkeypatch):
    real_convert = obs.observed_tree_from_scan

    def lossy(scan_, **kwargs):
        tree = real_convert(scan_, **kwargs)
        return dataclasses.replace(tree, items=tree.items[:-1])
    monkeypatch.setattr(obs, "observed_tree_from_scan", lossy)
    refused(audit(request_of(directory), Between()), R.OBSERVATION_PROJECTION_MISMATCH)


def test_a_tree_whose_hash_differs_from_the_scan_is_detected_by_the_independent_projection(tmp_path, monkeypatch):
    directory = scenario_dir(tmp_path, "25-all-declared-runs-present")
    real_convert = obs.observed_tree_from_scan

    def altered(scan_, **kwargs):
        tree = real_convert(scan_, **kwargs)
        items = tuple(dataclasses.replace(item, sha256="0" * 64) if item.sha256 is not None and item.content is None else item for item in tree.items)
        assert items != tree.items                                    # le mutant modifie bien au moins un fichier haché sans octets conservés
        return dataclasses.replace(tree, items=items)
    monkeypatch.setattr(obs, "observed_tree_from_scan", altered)
    refused(audit(request_of(directory), Between()), R.OBSERVATION_PROJECTION_MISMATCH)


def test_a_failure_inside_the_protocol_is_a_typed_internal_refusal_but_an_interrupt_propagates(directory, monkeypatch):
    def broken(roots, limits, **kwargs):
        raise RuntimeError("unexpected")
    refused(audit(request_of(directory), broken), R.AUDIT_INTERNAL_FAILURE)

    def interrupted(roots, limits, **kwargs):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        audit(request_of(directory), interrupted)


def test_the_diagnostic_never_mutates_the_tree_and_two_runs_give_the_same_report(directory):
    before = tree_digest(directory.parent)
    first, second = ap.audit_campaign_exposure(request_of(directory)), ap.audit_campaign_exposure(request_of(directory))
    assert tree_digest(directory.parent) == before and first == second


# ── Colonnes de F épinglées une à une, table par disposition, conversion L3-A ─────────────────────────────────────────────────────────────────────
def replace_observation(result, predicate, scan_changes=None, **changes):
    scans = []
    for item in result.scans:
        observations = tuple(dataclasses.replace(o, **changes) if predicate(o) else o for o in item.scan.observations)
        scans.append(b3.InterpretedScan(item.layout, dataclasses.replace(item.scan, observations=observations, **(scan_changes or {}))))
    return dataclasses.replace(result, scans=tuple(scans))


def test_a_change_confined_to_the_anomaly_of_one_observation_is_a_fact_drift(tmp_path):
    directory = scenario_dir(tmp_path, "16a-manifest-corrupt-bytes")           # manifest.json : anomalie INVALID_JSON, jamais analysé
    is_manifest = lambda o: o.relative_path == "manifest.json"                 # noqa: E731
    both = Between(first=lambda r: replace_observation(r, is_manifest, anomaly=scan.SourceAnomaly.INVALID_JSON),
                   second=lambda r: replace_observation(r, is_manifest, anomaly=scan.SourceAnomaly.TOO_LARGE))
    refused(audit(request_of(directory), both), R.RESCAN_FACT_DRIFT)


def test_a_size_change_of_an_anomalous_hashed_file_without_hash_is_a_fact_drift(tmp_path):
    directory = scenario_dir(tmp_path, "24-walk-forward-outputs-with-ready-manifest")
    is_output = lambda o: o.relative_path == "walk_forward/manifest.json"      # noqa: E731
    big = dict(anomaly=scan.SourceAnomaly.TOO_LARGE, content_hash=None)
    unread = dict(hashed_bytes_read=0)                                         # un fichier trop grand n'est jamais lu en entier : aucun octet haché facturé
    both = Between(first=lambda r: replace_observation(r, is_output, unread, size=70_000, **big), second=lambda r: replace_observation(r, is_output, unread, size=70_001, **big))
    refused(audit(request_of(directory), both), R.RESCAN_FACT_DRIFT)


def test_a_table_digest_is_checked_per_layout_not_only_for_the_campaign_layout(directory, tmp_path):
    results = tmp_path / "results"
    (results / "job").mkdir(parents=True)

    def wrong_results_digest(result):
        scans = tuple(b3.InterpretedScan(i.layout, dataclasses.replace(i.scan, rules_digest="0" * 64)) if i.layout is RESULTS else i for i in result.scans)
        return dataclasses.replace(result, scans=scans)
    spec = ap.AuditRootSpec(label="res", path=str(results), layout=RESULTS, expected_name=None, may_be_empty=True)
    refused(audit(request_for(campaign_spec(directory), spec), Between(first=wrong_results_digest)), R.SCAN_TABLE_MISMATCH)


def test_a_conversion_that_demotes_an_unknown_entry_is_detected(directory, monkeypatch):
    (directory / "stray_unknown.txt").write_text("x")                         # entrée hors table : UNKNOWN_FILE, jamais `INERT`
    real_convert = obs.observed_tree_from_scan

    def demote(scan_, **kwargs):
        tree = real_convert(scan_, **kwargs)
        items = tuple(dataclasses.replace(i, kind=vf.ObservedKind.INERT, anomaly=None) if i.kind is vf.ObservedKind.UNKNOWN else i for i in tree.items)
        assert items != tree.items
        return dataclasses.replace(tree, items=items)
    monkeypatch.setattr(obs, "observed_tree_from_scan", demote)
    refused(audit(request_of(directory), Between()), R.OBSERVATION_PROJECTION_MISMATCH)


def test_a_content_hash_difference_alone_is_a_fact_drift_even_when_the_interpretation_is_unchanged(directory):
    """Isolé par un faux : mêmes natures, mêmes tailles, mêmes raisons et mêmes findings ; seuls les octets conservés (donc le SHA-256) d'un fichier lu diffèrent."""
    import hashlib

    def other_bytes(result):
        manifest = next(o for i in result.scans for o in i.scan.observations if o.relative_path == "manifest.json")
        data = bytearray(manifest.content_bytes)
        at = data.index(b"campaign_protocol_fingerprint") + len(b"campaign_protocol_fingerprint") + 5
        data[at] = ord("a") if data[at] != ord("a") else ord("b")
        changed = bytes(data)
        assert len(changed) == len(manifest.content_bytes) and changed != manifest.content_bytes
        return replace_observation(result, lambda o: o.relative_path == "manifest.json", content_bytes=changed, content_hash=hashlib.sha256(changed).hexdigest())
    refused(audit(request_of(directory), Between(second=other_bytes)), R.RESCAN_FACT_DRIFT)


def test_a_difference_confined_to_the_findings_is_a_fact_drift(directory):
    (directory / "stray_unknown.txt").write_text("x")                         # entrée hors table : B3 produit au moins un finding UNKNOWN_SOURCE
    probe = real((b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, scan.AuditRoot("camp", str(directory))),), LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    assert probe.findings != ()
    refused(audit(request_of(directory), Between(second=lambda r: dataclasses.replace(r, findings=r.findings[:-1]))), R.RESCAN_FACT_DRIFT)


def test_a_conversion_that_changes_only_the_size_of_a_file_is_detected(tmp_path, monkeypatch):
    directory = scenario_dir(tmp_path, "25-all-declared-runs-present")
    real_convert = obs.observed_tree_from_scan

    def resize(scan_, **kwargs):
        tree = real_convert(scan_, **kwargs)
        items = tuple(dataclasses.replace(i, size=i.size + 1, content=None) if i.kind is vf.ObservedKind.FILE and i.content is None else i for i in tree.items)
        assert items != tree.items
        return dataclasses.replace(tree, items=items)
    monkeypatch.setattr(obs, "observed_tree_from_scan", resize)
    refused(audit(request_of(directory), Between()), R.OBSERVATION_PROJECTION_MISMATCH)
