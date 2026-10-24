"""AF-V-07 Slice E3-E S-0b/S-5a — garde `inventory.complete` pour RESERVATION et ADMISSION (amendement ADR 0025 23.10 / 23.33.5, accepté le 2026-10-24).

Ce que ces tests établissent : un VALIDATEUR PUR de la part « inventaire » des préconditions d'enregistrement. Ils n'établissent PAS que la garde
est opérationnelle de bout en bout : E3-D n'a aucun écrivain public de RESERVATION/ADMISSION (seul `publish_consumption`, SYNTHETIC) et E3-J n'existe
pas. Les obligations d'orchestration futures sont des contrats différés (tests `skip` avec raison). Fixtures SYNTHÉTIQUES ; aucun droit d'accès n'est
créé : le validateur ne retourne que des REFUS.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

import gate_v_exposure_interpreters as b3
import gate_v_exposure_inventory as b4
import gate_v_inventory_preconditions as guard
import gate_v_registry_append
from gate_v_exposure_scan import AuditRoot
from gate_v_final_holdout_protocol import (
    OwnCampaignContext,
    OwnRecordStage,
    SourceKind,
    compute_exposure_inventory_id,
    compute_static_sources_digest,
)
from tests.gate_v_exposure_support import LIMITS, W, h, make_job, write_json

CURRENT = "campaign_current"
STAGE0 = OwnCampaignContext(CURRENT, OwnRecordStage.NO_OWN_RECORDS)
RESERVED = OwnCampaignContext(CURRENT, OwnRecordStage.RESERVED)
Refusal = guard.InventoryPreconditionRefusal
RES, ADM = guard.RegistryRecordType.RESERVATION, guard.RegistryRecordType.ADMISSION


def interpretation(tmp_path, *, job=None, manifest_valid=True, runs=False):
    """Racine `CAMPAIGN_DIR` ancrée (plan seul) ; options : un job `RESULTS` exposé, un manifeste invalide, un run WF pré-holdout."""
    campaign_id = "gate_v_v2_" + "ab" * 32
    directory = tmp_path / campaign_id
    write_json(directory / "plan.json", {"campaign_id": campaign_id})
    if not manifest_valid:
        write_json(directory / "manifest.json", {"campaign_id": campaign_id})              # forme V1 : refusée par B3 v4
    if runs:
        write_json(directory / "validations" / f"{campaign_id}_walk_forward" / "validation_run.json", {
            "validation_run_id": "x", "research_run_id": "r", "split_plan_id": "s", "dataset_snapshot_id": "S0", "validation_type": "walk_forward",
            "strategy_name": "st", "strategy_params": {}, "evidence": {}, "status": "completed", "completed_at": "2025-12-01T00:00:00+00:00"})
    roots = [b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, AuditRoot("camp", str(directory)))]
    if job is not None:
        results = tmp_path / "results"
        make_job(results, "job_1", *job)
        roots.append(b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("res", str(results))))
    return b3.interpret_audit_roots(tuple(roots), LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])


def fact(seq, kind, campaign_id, window=W):
    return b4.RegistryRecordFact(seq=seq, kind=kind, campaign_id=campaign_id, content_hash=h(f"r{seq}"), window_start_utc=window[0], window_end_utc=window[1])


def assembly(tmp_path, context, records=(), **options):
    reg = b4.RegistryView("reg", None, tuple(records))
    return b4.assemble_exposure_inventory(interpretation(tmp_path, **options), registry=reg, accounting=b4.AccountingViews(), own_context=context,
                                          derived_root_labels=())


def pins(assembled):
    return dict(pinned_inventory_id=compute_exposure_inventory_id(assembled.inventory, assembled.own_context),
                pinned_static_sources_digest=compute_static_sources_digest(assembled.inventory, assembled.own_context))


def refusals(record_type, assembled, **kwargs):
    return guard.inventory_precondition_refusals(record_type, assembled.inventory, assembled.own_context, **kwargs).refusals


# ── RESERVATION ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_complete_inventory_with_an_empty_relevant_set_satisfies_the_inventory_part_of_a_reservation(tmp_path):
    assembled = assembly(tmp_path, STAGE0)
    report = guard.inventory_precondition_refusals(RES, assembled.inventory, assembled.own_context)
    assert assembled.inventory.complete is True and report.refusals == () and report.inventory_part_satisfied is True


def test_an_empty_relevant_set_is_never_enough_when_the_inventory_is_incomplete(tmp_path):
    """Cas central de l'amendement : un `manifest.json` non conforme ne donne qu'une RAISON (aucun finding) ; l'ensemble pertinent reste vide."""
    assembled = assembly(tmp_path, STAGE0, manifest_valid=False)
    assert assembled.inventory.complete is False
    assert [f for f in assembled.inventory.findings if f.overlap.value != "NO_OVERLAP"] == []          # ensemble pertinent vide
    assert refusals(RES, assembled) == (Refusal.INVENTORY_INCOMPLETE,)


def test_a_reservation_is_refused_while_any_relevant_source_exists_including_a_rival_registration(tmp_path):
    exposed = assembly(tmp_path / "a", STAGE0, job=("2026-02-01T00:00:00+00:00", "2026-02-10T00:00:00+00:00"))
    unknown = assembly(tmp_path / "b", STAGE0, runs=True)
    rival = assembly(tmp_path / "c", STAGE0, records=[fact(0, SourceKind.REGISTRY_RESERVATION, "other_campaign")])
    for assembled in (exposed, unknown, rival):
        assert Refusal.RELEVANT_SET_NOT_EMPTY in refusals(RES, assembled)


def test_a_reservation_is_refused_when_the_stage_is_not_the_initial_one(tmp_path):
    assembled = assembly(tmp_path, RESERVED, records=[fact(0, SourceKind.REGISTRY_RESERVATION, CURRENT)])
    assert Refusal.STAGE_MISMATCH in refusals(RES, assembled)


# ── ADMISSION ──────────────────────────────────────────────────────────────────────────────────────────────────────

def admitted_candidate(tmp_path, **options):
    return assembly(tmp_path, RESERVED, records=[fact(0, SourceKind.REGISTRY_RESERVATION, CURRENT)], **options)


def test_an_admission_with_a_complete_inventory_and_matching_pins_satisfies_the_inventory_part(tmp_path):
    assembled = admitted_candidate(tmp_path)
    assert refusals(ADM, assembled, **pins(assembled)) == ()


def test_an_admission_is_refused_without_pins_or_with_diverging_pins(tmp_path):
    assembled = admitted_candidate(tmp_path)
    assert refusals(ADM, assembled) == (Refusal.PINS_MISSING,)
    good = pins(assembled)
    assert refusals(ADM, assembled, **{**good, "pinned_inventory_id": "0" * 64}) == (Refusal.PINNED_INVENTORY_ID_MISMATCH,)
    assert refusals(ADM, assembled, **{**good, "pinned_static_sources_digest": "0" * 64}) == (Refusal.PINNED_STATIC_SOURCES_DIGEST_MISMATCH,)


def test_an_admission_is_refused_on_an_incomplete_inventory_even_with_correct_pins(tmp_path):
    assembled = admitted_candidate(tmp_path, manifest_valid=False)
    assert Refusal.INVENTORY_INCOMPLETE in refusals(ADM, assembled, **pins(assembled))


def test_an_admission_is_refused_for_an_exposing_or_unresolved_source_and_for_a_rival_registration(tmp_path):
    exposed = admitted_candidate(tmp_path / "a", job=("2026-02-01T00:00:00+00:00", "2026-02-10T00:00:00+00:00"))
    unknown = admitted_candidate(tmp_path / "b", runs=True)
    rival = assembly(tmp_path / "c", RESERVED, records=[fact(0, SourceKind.REGISTRY_RESERVATION, CURRENT), fact(1, SourceKind.REGISTRY_ADMISSION, "other")])
    for assembled in (exposed, unknown):
        assert Refusal.UNRESOLVED_OR_EXPOSING_SOURCE in refusals(ADM, assembled, **pins(assembled))
    assert Refusal.OVERLAPPING_REGISTRATION in refusals(ADM, rival, **pins(rival))


def test_an_admission_is_refused_when_the_own_reservation_is_missing_or_the_stage_is_wrong(tmp_path):
    no_reservation = assembly(tmp_path / "a", RESERVED)
    assert Refusal.OWN_RECORD_ANOMALY in refusals(ADM, no_reservation, **pins(no_reservation))
    wrong_stage = assembly(tmp_path / "b", STAGE0)
    assert Refusal.STAGE_MISMATCH in refusals(ADM, wrong_stage, **pins(wrong_stage))


def test_an_unabsorbed_own_claim_like_record_is_relevant_even_when_its_window_is_disjoint_from_w(tmp_path):
    """Revue indépendante (2026-10-24) : E3-A traite un enregistrement propre exposant résolu non absorbé comme une exposition (23.27.2, échec fermé) ;
    le validateur ne doit pas être plus permissif que la classification."""
    after_w = ("2026-06-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00")
    own_consumption = fact(1, SourceKind.CONSUMPTION, CURRENT, window=after_w)
    reservation_stage = assembly(tmp_path / "a", STAGE0, records=[own_consumption])
    assert Refusal.RELEVANT_SET_NOT_EMPTY in refusals(RES, reservation_stage)
    admission_stage = assembly(tmp_path / "b", RESERVED, records=[fact(0, SourceKind.REGISTRY_RESERVATION, CURRENT), own_consumption])
    assert Refusal.UNRESOLVED_OR_EXPOSING_SOURCE in refusals(ADM, admission_stage, **pins(admission_stage))
    foreign = assembly(tmp_path / "c", STAGE0, records=[fact(1, SourceKind.CONSUMPTION, "other_campaign", window=after_w)])
    assert refusals(RES, foreign) == ()                                # un enregistrement étranger disjoint de W n'est pas pertinent


# ── Pureté : le validateur n'ouvre aucun droit et n'écrit rien ───────────────────────────────────────────────────────

def test_the_report_carries_refusals_only_and_no_authorization_vocabulary(tmp_path):
    report = guard.inventory_precondition_refusals(RES, assembly(tmp_path, STAGE0).inventory, STAGE0)
    names = {field.name for field in dataclasses.fields(report)}
    assert names == {"record_type", "refusals"}
    assert not {name for name in dir(report) if any(word in name.lower() for word in ("authoriz", "grant", "allow", "admit", "right"))}


def test_the_module_is_pure_and_imports_nothing_that_can_write_or_publish():
    tree = ast.parse(Path(guard.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "dataclasses", "enum", "typing", "gate_v_final_holdout_protocol"}, imported
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "eval", "exec", "__import__"}


@pytest.mark.parametrize("bad", [dict(record_type="RESERVATION"), dict(inventory=None), dict(own_context=None)])
def test_the_validator_rejects_wrongly_typed_inputs(tmp_path, bad):
    assembled = assembly(tmp_path, STAGE0)
    values = dict(record_type=RES, inventory=assembled.inventory, own_context=STAGE0)
    values.update(bad)
    with pytest.raises(TypeError):
        guard.inventory_precondition_refusals(values["record_type"], values["inventory"], values["own_context"])


# ── Statut réel de la garde : NON opérationnelle de bout en bout (contrats différés) ─────────────────────────────────

def test_e3d_has_no_public_reservation_or_admission_writer_so_the_guard_is_not_wired_end_to_end():
    """Si ce test échoue un jour, un écrivain public existe : il DOIT alors appeler ce validateur (voir les contrats différés ci-dessous)."""
    public = {name for name in dir(gate_v_registry_append) if not name.startswith("_")}
    assert "publish_consumption" in public
    assert not [name for name in public if name.startswith("publish_") and ("reservation" in name or "admission" in name)]


@pytest.mark.skip(reason="E3-J absent : l'écrivain public de RESERVATION doit appeler `inventory_precondition_refusals` et refuser tout enregistrement si "
                         "`refusals` n'est pas vide, après lecture stricte du registre et revérification après tout conflit de slot (23.10, 23.27.4)")
def test_deferred_contract_a_reservation_writer_refuses_an_incomplete_inventory():
    raise AssertionError("contrat différé E3-J")


@pytest.mark.skip(reason="E3-J absent : l'écrivain public d'ADMISSION doit appeler le validateur, comparer `inventory_id` et `static_sources_digest` à "
                         "l'attestation, et refuser sur `complete=False` même avec un ensemble pertinent vide")
def test_deferred_contract_an_admission_writer_refuses_an_incomplete_inventory_and_diverging_pins():
    raise AssertionError("contrat différé E3-J")


def test_the_validator_states_that_it_does_not_replace_the_seven_admission_checks_of_23_27_4():
    """Limite documentée ET testable : `inventory_content_digest` n'est pas vérifié ici ; le validateur n'a aucun paramètre qui le laisserait croire."""
    import inspect
    doc = inspect.getdoc(guard) or ""
    for expected in ("ne remplace PAS les sept vérifications", "23.27.4", "inventory_content_digest", "E3-J"):
        assert expected in doc, expected
    assert set(inspect.signature(guard.inventory_precondition_refusals).parameters) == {
        "record_type", "inventory", "own_context", "pinned_inventory_id", "pinned_static_sources_digest"}


@pytest.mark.skip(reason="E3-J absent : l'écrivain public d'ADMISSION doit vérifier `inventory_content_digest` (ADR 0025 23.27.4) avec les six autres "
                         "contrôles préalables (attestation, autorisation, déclarations, preuve de temps, projection de recouvrement, chaîne), répétés "
                         "après tout conflit de slot ; ce validateur n'en couvre pas la totalité")
def test_deferred_contract_an_admission_writer_verifies_inventory_content_digest_and_the_seven_checks():
    raise AssertionError("contrat différé E3-J")


@pytest.mark.skip(reason="E3-J absent (R-Q2-15) : D5 en P4 et à l'étape 7, rechecks sentinelle/verrou aux étapes 13 et 14 bis, aucun FRESH si sentinelle "
                         "ou verrou existe, aucune poursuite sans le Manifest vérifié rendu par D5")
def test_deferred_contract_the_orchestration_calls_d5_and_rechecks_the_technical_markers():
    raise AssertionError("contrat différé E3-J")
