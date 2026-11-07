"""N2-b2a — INTÉGRATION du diagnostic des déclarations des plans V2 : adaptateur (`assess`), rapport (`AuditReport`), parité avec le chargeur historique et avec la sélection stricte de la fenêtre,
zéro lecture disque ajoutée, conservation exacte de B4 (six compteurs, `inventory_id`, `inventory_content_digest`, classification), invariants du rapport, refus et non-promotion.

Fixtures SYNTHÉTIQUES (`tmp_path`, plans V2 réels par les fabriques historiques). Aucun A0, aucune écriture de registre, aucune donnée de marché, aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import builtins
import dataclasses
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gate_v_audit_plan_declared as pd
import gate_v_audit_protocol as ap
import gate_v_audit_registry as ar
import gate_v_audit_window as aw
import gate_v_plan_declared_support as psup
import gate_v_registry_audit_support as sup
from gate_v_campaign_plan_v2 import load_gate_v_campaign_plan_v2, save_gate_v_campaign_plan_v2
from gate_v_exposure_interpreters import RootLayout
from gate_v_exposure_inventory import AccountingViews
from tests.gate_v_audit_protocol_support import campaign_spec, request_for
from tests.gate_v_audit_window_support import CAMPAIGN_LABEL, HOLDOUT, HOLDOUT_NORMALISED, build_world, forge_plan, lay_out, split_spec, window_source
from tests.test_gate_v_audit_registry_protocol import B1A_NOT_PROVEN, EARLY, FIVE, OWN_RESERVED, WN, B, R, request, setup_world

MAX_JSON = 1_000_000


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("n2b2a_world"))


def other_plans(world):
    """Quatre plans V2 authentiques et distincts (empreintes recalculées honnêtement). b et c : même configuration ; b, d, e : même run ; c : même contenu de run sous un autre identifiant."""
    return {"b": forge_plan(world.plan, budget_per_fold=11), "c": forge_plan(world.plan, budget_per_fold=12, research_run_id="run_y"),
            "d": forge_plan(world.plan, budget_per_fold=13, strategy_name="other_strategy"), "e": forge_plan(world.plan, budget_per_fold=14, search_space_hash="b" * 12, search_mode="grid")}


class Audit:
    pass


@pytest.fixture
def audit(world, tmp_path):
    base = tmp_path / "audit"
    base.mkdir()
    result = Audit()
    result.base, result.plans, result.own = base, other_plans(world), world.plan
    result.paths = {key: save_gate_v_campaign_plan_v2(base, plan).parent for key, plan in result.plans.items()}
    result.paths["own"] = save_gate_v_campaign_plan_v2(base, world.plan).parent
    return result


def window_of(index: int) -> tuple:
    """Fenêtres DISJOINTES (le registre refuse deux campagnes aux fenêtres qui se recouvrent)."""
    return (f"2025-{index + 1:02d}-01T00:00:00.000000Z", f"2025-{index + 1:02d}-02T00:00:00.000000Z")


def run(tmp_path, audit, keys, *, listed=None, chain=None, name="registry"):
    """`assess` sur un S1 RÉEL des dossiers `keys` (et propre). `chain` : clés des autres campagnes inscrites au registre (par défaut `keys`)."""
    chain_keys = keys if chain is None else chain
    root = sup.new_registry(tmp_path, name)
    sup.populate(root, sup.build_chain([("R", audit.own.campaign_id, *WN)] + [("R", audit.plans[k].campaign_id, *window_of(i)) for i, k in enumerate(chain_keys)]))
    cfg = ar.RegistryConfig(root_path=str(root), max_slots=1000, max_total_bytes=10 ** 7)
    handle = ar.read(cfg, own_campaign_id=audit.own.campaign_id, window=WN)
    roots = [("own", audit.paths["own"], audit.own.campaign_id)] + [(k, audit.paths[k], audit.plans[k].campaign_id) for k in (keys if listed is None else listed)]
    s1 = sup.interpret_campaigns([(label, path) for label, path, _expected in roots])
    return ar.assess(handle, s1, own_campaign_id=audit.own.campaign_id, window=WN, campaign_roots=tuple((label, str(path), expected) for label, path, expected in roots), max_json_bytes=MAX_JSON), s1, roots


# ── Faits attendus d'un corpus de plans réels (parité avec le chargeur historique) ───────────────────────────────────────────────────────────────

def test_ie1_real_plans_give_the_hand_counted_declarations(tmp_path, audit):
    for key, plan in audit.plans.items():
        loaded = load_gate_v_campaign_plan_v2(audit.paths[key] / "plan.json")                                         # le chargeur historique relit exactement ce que la fabrique a écrit
        assert (loaded.research_run_id, loaded.strategy_name, loaded.search_mode, loaded.search_space_hash) == (plan.research_run_id, plan.strategy_name, plan.search_mode, plan.search_space_hash)
    result, _s1, _roots = run(tmp_path, audit, ["b", "c", "d", "e"])
    diagnostic = result.plan_declared_diagnostic
    assert diagnostic.basis is pd.PlanDeclaredBasis.EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ and (diagnostic.source_campaign_count, diagnostic.unavailable_campaign_count) == (4, 0)
    assert (diagnostic.declared_run_reference_count, diagnostic.declared_run_id_count) == (2, 2)                       # (run_x, H) pour b, d, e ; (run_y, H) pour c
    assert (diagnostic.declared_search_config_count, diagnostic.declared_strategy_name_count) == (3, 2)               # {b, c}, {d}, {e}
    assert (diagnostic.multi_campaign_run_reference_count, diagnostic.multi_campaign_search_config_count) == (1, 1)
    assert (diagnostic.id_with_several_content_hashes_count, diagnostic.content_hash_with_several_ids_count, diagnostic.conflicting_run_id_sample) == (0, 1, ())


@pytest.mark.parametrize("mode", ["single_var", "cross_zone", "grid", "general"])
def test_ie2_no_authentic_plan_is_ever_invalid_for_any_search_mode_of_the_loader(tmp_path, world, mode):
    base = tmp_path / "audit"
    base.mkdir()
    plans = [forge_plan(world.plan, budget_per_fold=20 + i, search_mode=mode) for i in range(2)]
    paths = [save_gate_v_campaign_plan_v2(base, plan).parent for plan in plans]
    own_path = save_gate_v_campaign_plan_v2(base, world.plan).parent
    roots = [("own", own_path, world.plan.campaign_id)] + [(f"p{i}", paths[i], plans[i].campaign_id) for i in range(2)]
    s1 = sup.interpret_campaigns([(label, path) for label, path, _ in roots])
    derived = tuple(sorted((label, expected) for label, path, expected in roots[1:] if aw.plan_root_attributed(s1, label=label, root_path=str(path), expected_name=expected, max_json_bytes=MAX_JSON)))
    assert len(derived) == 2                                                                                           # les deux plans passent le chargeur
    result = pd.diagnose(s1, derived=derived, other_campaign_count=2, max_json_bytes=MAX_JSON)
    assert result.unavailable_campaign_count == 0 and result.declared_search_config_count == 1 and result.multi_campaign_search_config_count == 1


def test_ie3_the_plan_record_selector_agrees_with_the_window_selector_on_every_unreadable_variant():
    cases = {"valid": {}, "anomaly": dict(anomaly="X"), "unparsed": dict(value_parsed=False), "no hash": dict(content_hash=None), "directory": dict(kind=psup.EntryKind.DIRECTORY),
             "list": dict(value=[1]), "none": dict(value=None)}
    for label, changes in cases.items():
        record = psup.campaign_record(1)
        interp = psup.interpretation([psup.observation("c1", record, **changes)])
        try:
            aw._observed(interp, RootLayout.CAMPAIGN_DIR, "c1", "plan.json")
            window_reads = True
        except aw.WindowSourceRefused:
            window_reads = False
        result = pd.diagnose(interp, derived=(("c1", record["campaign_id"]),), other_campaign_count=1, max_json_bytes=MAX_JSON)
        assert (result.source_campaign_count == 1) is window_reads, label
        if not window_reads:
            assert result.unavailable_breakdown == (("PLAN_RECORD_NOT_READ", 1),), label
    duplicated = psup.interpretation([psup.observation("c1", psup.campaign_record(1)), psup.observation("c1", psup.campaign_record(1))])
    with pytest.raises(aw.WindowSourceRefused):
        aw._observed(duplicated, RootLayout.CAMPAIGN_DIR, "c1", "plan.json")
    assert pd.diagnose(duplicated, derived=(("c1", psup.campaign_record(1)["campaign_id"]),), other_campaign_count=1, max_json_bytes=MAX_JSON).unavailable_breakdown == (("PLAN_RECORD_NOT_READ", 1),)


def plan_record_of(s1, label):
    found = [o for item in s1.scans for o in item.scan.observations if o.root_label == label and o.relative_path == "plan.json"]
    assert len(found) == 1
    return found[0].value


def raw_hash(preimage: dict) -> str:
    return hashlib.sha256(json.dumps(preimage, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def test_ie10_extracted_facts_equal_the_fields_of_the_plan_loaded_by_the_historical_loader(tmp_path, audit):
    _result, s1, _roots = run(tmp_path, audit, ["b", "c", "d", "e"])
    for key, plan in audit.plans.items():
        loaded = load_gate_v_campaign_plan_v2(audit.paths[key] / "plan.json")
        run_id, content, run_identity, strategy, config_identity = pd._extract(plan_record_of(s1, key), loaded.campaign_id, 8 * MAX_JSON)
        assert (run_id, content, strategy) == (loaded.research_run_id, loaded.research_run_content_hash, loaded.strategy_name)
        assert run_identity == "declared_run_reference_v1_" + raw_hash({"declared_kind": "research_run_reference", "identity_version": "declared_run_reference_v1",
                                                                         "research_run_content_hash": loaded.research_run_content_hash, "research_run_id": loaded.research_run_id})
        assert config_identity == "declared_search_configuration_v1_" + raw_hash({"base_params": json.loads(json.dumps(loaded.base_params)), "declared_kind": "search_configuration",
                                                                                  "identity_version": "declared_search_configuration_v1", "search_mode": loaded.search_mode,
                                                                                  "search_space_hash": loaded.search_space_hash, "strategy_name": loaded.strategy_name})


def test_ie11_an_authentic_plan_copied_into_another_directory_gives_the_same_facts(tmp_path, audit):
    original, _s1, _roots = run(tmp_path, audit, ["b", "c"], name="r1")
    twin = audit.base / "copy_of_b"
    shutil.copytree(audit.paths["b"], twin)
    audit.paths["b"] = twin
    copied, _s1, _roots = run(tmp_path, audit, ["b", "c"], name="r2")
    assert original.plan_declared_diagnostic.source_campaign_count == 2 and copied.plan_declared_diagnostic.source_campaign_count == 2                  # les deux lectures ont bien lu des plans
    assert copied.plan_declared_diagnostic == original.plan_declared_diagnostic                                          # copie conforme : aucune différence observable (limite L5 consignée)


# ── Couverture : plans non fournis, copiés, hors registre ────────────────────────────────────────────────────────────────────────────────────────

def test_ie4_registered_campaigns_without_a_provided_root_are_unavailable_never_zero(tmp_path, audit):
    result, _s1, _roots = run(tmp_path, audit, ["b"], chain=["b", "c", "d"])
    diagnostic = result.plan_declared_diagnostic
    assert diagnostic.basis is pd.PlanDeclaredBasis.SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ and (diagnostic.source_campaign_count, diagnostic.unavailable_breakdown) == (1, (("NO_ATTRIBUTED_ROOT", 2),))
    assert diagnostic.unavailable_breakdown == (("NO_ATTRIBUTED_ROOT", result.registry_uncovered_count),) and diagnostic.multi_campaign_run_reference_count is None


def test_ie5_no_provided_root_at_all_gives_none_everywhere(tmp_path, audit):
    result, _s1, _roots = run(tmp_path, audit, [], chain=["b", "c"])
    diagnostic = result.plan_declared_diagnostic
    assert diagnostic.basis is pd.PlanDeclaredBasis.NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ and diagnostic.declared_run_reference_count is None and diagnostic.unavailable_campaign_count == 2


def test_ie6_a_registry_without_other_campaign_gives_a_constatated_zero(tmp_path, audit):
    result, _s1, _roots = run(tmp_path, audit, [], chain=[])
    diagnostic = result.plan_declared_diagnostic
    assert diagnostic.basis is pd.PlanDeclaredBasis.REGISTRY_HAS_NO_OTHER_CAMPAIGN and diagnostic.declared_run_reference_count == 0 and diagnostic.multi_campaign_run_reference_count is None
    assert result.registry_other_campaign_count == 0 and result.trial_counters[2].value == 0                           # cohérent avec `campaigns = 0` observé par B4


def test_ie7_a_root_whose_name_is_not_in_the_chain_is_not_counted(tmp_path, audit):
    result, _s1, _roots = run(tmp_path, audit, ["b", "c"], chain=["b"])
    diagnostic = result.plan_declared_diagnostic
    assert (diagnostic.source_campaign_count, diagnostic.unavailable_campaign_count, diagnostic.declared_run_reference_count) == (1, 0, 1)


def test_ie8_an_authentic_plan_copied_under_another_campaign_name_is_unattributed(tmp_path, audit):
    (audit.paths["c"] / "plan.json").write_bytes((audit.paths["b"] / "plan.json").read_bytes())                    # c héberge le plan authentique de b : refusé par l'appariement
    result, _s1, _roots = run(tmp_path, audit, ["b", "c"])
    diagnostic = result.plan_declared_diagnostic
    assert result.derived_root_labels == ("b",) and diagnostic.unavailable_breakdown == (("NO_ATTRIBUTED_ROOT", 1),) and diagnostic.source_campaign_count == 1


def test_ie9_the_own_campaign_is_excluded_from_the_declarations(tmp_path, audit):
    assert audit.own.research_run_id == "run_x" and audit.plans["c"].research_run_id == "run_y"
    result, _s1, _roots = run(tmp_path, audit, ["c"])
    diagnostic = result.plan_declared_diagnostic
    assert diagnostic.source_campaign_count == 1 and "OWN_CAMPAIGN_OVERLAP" in diagnostic.not_established
    assert (diagnostic.declared_run_reference_count, diagnostic.declared_run_id_count) == (1, 1)                        # run_x, déclaré par la campagne propre seulement, n'est pas compté


# ── Aucune lecture disque ajoutée ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_dk1_diagnose_performs_no_open_scandir_stat_or_lstat(tmp_path, audit, monkeypatch):
    result, s1, roots = run(tmp_path, audit, ["b", "c", "d", "e"])
    derived = tuple(sorted((label, expected) for label, _path, expected in roots[1:]))
    seen = []
    for module, name in ((os, "open"), (os, "scandir"), (os, "stat"), (os, "lstat"), (os, "listdir"), (builtins, "open")):
        real = getattr(module, name)
        monkeypatch.setattr(module, name, lambda *a, _real=real, _name=name, **k: (seen.append(_name), _real(*a, **k))[1])
    again = pd.diagnose(s1, derived=derived, other_campaign_count=4, max_json_bytes=MAX_JSON)
    monkeypatch.undo()
    assert seen == [] and again == result.plan_declared_diagnostic


def test_dk2_the_audit_reads_exactly_what_the_attribution_reads(tmp_path, audit, monkeypatch):
    guarded, loads = [], []
    real_guard, real_load = aw._guarded_sha256, aw.load_gate_v_campaign_plan_v2
    monkeypatch.setattr(aw, "_guarded_sha256", lambda *a, **k: (guarded.append(a[0]), real_guard(*a, **k))[1])
    monkeypatch.setattr(aw, "load_gate_v_campaign_plan_v2", lambda path: (loads.append(str(path)), real_load(path))[1])
    result, _s1, _roots = run(tmp_path, audit, ["b", "c", "d", "e"])
    assert result.plan_declared_diagnostic.source_campaign_count == 4
    assert len(guarded) == 2 * 4 and len(loads) == 4                                                                   # deux lectures gardées et une lecture du chargeur par racine candidate, rien de plus


# ── Conservation de B4 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_cb1_b4_receives_an_empty_accounting_and_its_outputs_are_those_of_a_direct_call(tmp_path, audit, monkeypatch):
    captured = []
    real = ar.assemble_exposure_inventory
    monkeypatch.setattr(ar, "assemble_exposure_inventory", lambda *a, **k: (captured.append((a, k)), real(*a, **k))[1])
    result, s1, _roots = run(tmp_path, audit, ["b", "c"])
    monkeypatch.undo()
    (args, kwargs), = captured
    assert kwargs["accounting"] == AccountingViews() and set(kwargs) == {"registry", "accounting", "own_context", "derived_root_labels"} and args == (s1,)
    direct = real(*args, **kwargs)
    assert direct.inventory.complete is result.b4_complete and tuple(sorted(set(direct.incomplete_reasons) - set(s1.incomplete_reasons))) == result.b4_incomplete_reasons
    again = real(*args, **kwargs)
    assert (direct.inventory_id, direct.inventory_content_digest) == (again.inventory_id, again.inventory_content_digest)
    from gate_v_final_holdout_protocol import compute_exposure_inventory_id, compute_inventory_content_digest
    assert direct.inventory_id == compute_exposure_inventory_id(direct.inventory, direct.own_context)                    # formules E3-A, appelées à part
    assert direct.inventory_content_digest == compute_inventory_content_digest(direct.inventory, direct.own_context)


def test_cb2_the_six_counters_and_their_reasons_ignore_the_diagnostic(tmp_path, audit):
    with_plans, _s1, _roots = run(tmp_path, audit, ["b", "c", "d", "e"], name="r1")
    without_plans, _s1, _roots = run(tmp_path, audit, [], chain=["b", "c", "d", "e"], name="r2")
    for result in (with_plans, without_plans):
        assert [(c.name, c.value, c.provenance.value) for c in result.trial_counters] == [("research_runs", None, "NOT_OBSERVED"), ("strategies", None, "NOT_OBSERVED"), ("campaigns", 4, "OBSERVED"),
                                                                                           ("abandoned_reservations", None, "NOT_OBSERVED"), ("failed_ingestion_attempts", None, "NOT_OBSERVED"),
                                                                                           ("void_commitments", None, "NOT_OBSERVED")]
    assert with_plans.trial_counter_reasons == without_plans.trial_counter_reasons
    assert with_plans.plan_declared_diagnostic != without_plans.plan_declared_diagnostic


def test_cb3_the_assessment_type_does_not_default_the_diagnostic_and_stays_immutable(tmp_path, audit):
    field = {f.name: f for f in dataclasses.fields(ar.RegistryAssessment)}["plan_declared_diagnostic"]
    assert field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING and list(f.name for f in dataclasses.fields(ar.RegistryAssessment))[-1] == "plan_declared_diagnostic"
    result, _s1, _roots = run(tmp_path, audit, ["b"])
    assert type(result.plan_declared_diagnostic) is pd.PlanDeclaredDiagnostic
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.plan_declared_diagnostic = None
    assert {"PlanDeclaredBasis", "PlanDeclaredDiagnostic"} <= set(ar.__all__)


def test_cb4_the_diagnostic_is_computed_after_the_b4_assembly(tmp_path, audit, monkeypatch):
    order = []
    real_assemble, real_diagnose = ar.assemble_exposure_inventory, pd.diagnose
    monkeypatch.setattr(ar, "assemble_exposure_inventory", lambda *a, **k: (order.append("b4"), real_assemble(*a, **k))[1])
    monkeypatch.setattr(ar.plan_declared, "diagnose", lambda *a, **k: (order.append("diagnose"), real_diagnose(*a, **k))[1])
    run(tmp_path, audit, ["b"])
    assert order == ["b4", "diagnose"]


def test_cb8_the_adapter_forwards_the_derived_roots_the_chain_count_and_the_json_cap(tmp_path, audit, monkeypatch):
    seen = []
    real = pd.diagnose
    monkeypatch.setattr(ar.plan_declared, "diagnose", lambda interpretation, **kwargs: (seen.append(kwargs), real(interpretation, **kwargs))[1])
    _result, _s1, roots = run(tmp_path, audit, ["b", "c"], chain=["b", "c", "d"])
    (kwargs,) = seen
    assert kwargs == {"derived": tuple(sorted((label, expected) for label, _path, expected in roots[1:])), "other_campaign_count": 3, "max_json_bytes": MAX_JSON}


def test_cb5_a_ghost_derived_root_on_an_empty_registry_keeps_the_existing_assembly_refusal(tmp_path, audit, monkeypatch):
    root = sup.new_registry(tmp_path, "ghost")
    sup.populate(root, sup.build_chain([("R", audit.own.campaign_id, *WN)]))
    cfg = ar.RegistryConfig(root_path=str(root), max_slots=1000, max_total_bytes=10 ** 7)
    handle = ar.read(cfg, own_campaign_id=audit.own.campaign_id, window=WN)
    s1 = sup.interpret_campaigns([("own", audit.paths["own"])])
    monkeypatch.setattr(ar, "_derived_roots", lambda *a, **k: (("ghost", sup.foreign_id(0xB)),))
    called = []
    monkeypatch.setattr(ar.plan_declared, "diagnose", lambda *a, **k: called.append(1))
    with pytest.raises(ar.RegistryAuditRefused) as raised:
        ar.assess(handle, s1, own_campaign_id=audit.own.campaign_id, window=WN, campaign_roots=(("own", str(audit.paths["own"]), audit.own.campaign_id),), max_json_bytes=MAX_JSON)
    assert (raised.value.code, raised.value.detail) == ("B4_ASSEMBLY_REFUSED", "ASSEMBLY") and called == []


def test_cb6_assess_alone_refuses_two_roots_with_the_same_expected_name(tmp_path, audit):
    root = sup.new_registry(tmp_path, "dup")
    sup.populate(root, sup.build_chain([("R", audit.own.campaign_id, *WN), ("R", audit.plans["b"].campaign_id, *window_of(0))]))
    cfg = ar.RegistryConfig(root_path=str(root), max_slots=1000, max_total_bytes=10 ** 7)
    handle = ar.read(cfg, own_campaign_id=audit.own.campaign_id, window=WN)
    twin = audit.base / "twin_of_b"
    shutil.copytree(audit.paths["b"], twin)                                                                             # un second dossier portant le plan authentique de b : deux racines, un même nom attendu
    roots = [("own", audit.paths["own"], audit.own.campaign_id), ("b1", audit.paths["b"], audit.plans["b"].campaign_id), ("b2", twin, audit.plans["b"].campaign_id)]
    s1 = sup.interpret_campaigns([(label, path) for label, path, _ in roots])
    with pytest.raises(ValueError):                                                                                   # le protocole les refuse en amont ; l'adaptateur appelé seul lève désormais
        ar.assess(handle, s1, own_campaign_id=audit.own.campaign_id, window=WN, campaign_roots=tuple((label, str(path), expected) for label, path, expected in roots), max_json_bytes=MAX_JSON)


@pytest.mark.parametrize("error", [MemoryError("simulated"), RecursionError("simulated")])
def test_cb7_critical_failures_of_the_diagnostic_are_not_converted_by_the_adapter(tmp_path, audit, monkeypatch, error):
    def boom(*a, **k):
        raise error
    monkeypatch.setattr(ar.plan_declared, "diagnose", boom)
    with pytest.raises(type(error)):
        run(tmp_path, audit, ["b"])


# ── Rapport ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def good(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("n2b2a_good")
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED + [("R", B, *EARLY)])
    return ap.audit_campaign_exposure(request(audit, cfg))


def fields_of(report):
    return {f.name: getattr(report, f.name) for f in dataclasses.fields(ap.AuditReport)}


def test_rp1_without_a_registry_the_report_has_no_diagnostic(tmp_path):
    from tests.gate_v_manifest_scenarios import CID, SCENARIOS, realise
    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    report = ap.audit_campaign_exposure(request_for(campaign_spec(audit), own=CID))
    assert report.receivability is ap.Receivability.RECEIVABLE and report.plan_declared_diagnostic is None


def test_rp2_the_diagnostic_is_the_last_defaulted_field_of_the_report():
    names = [f.name for f in dataclasses.fields(ap.AuditReport)]
    field = {f.name: f for f in dataclasses.fields(ap.AuditReport)}["plan_declared_diagnostic"]
    assert names[-1] == "plan_declared_diagnostic" and field.default is None


def test_rp3_a_registry_audit_reports_the_coherent_diagnostic(good):
    diagnostic = good.plan_declared_diagnostic
    assert type(diagnostic) is pd.PlanDeclaredDiagnostic and diagnostic.basis is pd.PlanDeclaredBasis.NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ
    assert (diagnostic.source_campaign_count, diagnostic.unavailable_campaign_count, diagnostic.unavailable_breakdown) == (0, 1, (("NO_ATTRIBUTED_ROOT", 1),))
    assert diagnostic.declared_run_reference_count is None
    assert good.registry_other_campaign_count == 1 and good.registry_uncovered_count == 1


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubDiagnostic(pd.PlanDeclaredDiagnostic):
    """Sous-classe valide du diagnostic : refusée par le contrôle de type EXACT de la clause (10)."""


def clone_of(diagnostic):
    return SubDiagnostic(**{f.name: getattr(diagnostic, f.name) for f in dataclasses.fields(diagnostic)})


REPORT_CLAUSES = {
    "10 None with a registry": lambda sound: None,
    "10 foreign object": lambda sound: type("Foreign", (), {})(),
    "10 dict": lambda sound: {"basis": 1},
    "10 bare object": lambda sound: object(),
    "10 real subclass": clone_of,
    "11 and 12 sum above the chain count": lambda sound: dataclasses.replace(sound, unavailable_campaign_count=2, unavailable_breakdown=(("NO_ATTRIBUTED_ROOT", 2),)),
    "12 unattributed code count differs from uncovered": lambda sound: dataclasses.replace(sound, unavailable_breakdown=(("PLAN_FIELD_INVALID", 1),)),
}


@pytest.mark.parametrize("label", list(REPORT_CLAUSES))
def test_rp4_each_new_clause_raises_the_registry_family_error(good, label):
    base = fields_of(good)
    with pytest.raises(ValueError, match="champs de registre"):
        ap.AuditReport(**{**base, "plan_declared_diagnostic": REPORT_CLAUSES[label](base["plan_declared_diagnostic"])})


# NOTE : « source <= len(derived_root_labels) » (12, première moitié) est IMPLIQUÉE par (9), (11), (12, seconde moitié) et I4 : source = autres - uncovered - autres_codes. Elle est conservée (spec 7.2)
# et ne peut pas échouer seule ; aucun test ne prétend l'isoler.


def test_rp5_a_diagnostic_without_a_registry_is_refused_before_the_early_return(tmp_path):
    from tests.gate_v_manifest_scenarios import CID, SCENARIOS, realise
    audit = realise(tmp_path / "audit", SCENARIOS["01-ready-initial"])
    plain = ap.audit_campaign_exposure(request_for(campaign_spec(audit), own=CID))
    foreign = fields_of(plain)
    for stray in (pd.diagnose(psup.interpretation([]), derived=(), other_campaign_count=0, max_json_bytes=MAX_JSON), object()):
        with pytest.raises(ValueError, match="champs de registre"):
            ap.AuditReport(**{**foreign, "plan_declared_diagnostic": stray})
    assert ap.AuditReport(**foreign) == plain


def test_rp6_a_refused_report_has_no_diagnostic_even_with_consistent_fields(good):
    defect = ap.AuditDefect(R.REQUEST_INVALID, ap.Stage.REQUEST)
    refused = {**fields_of(good), "receivability": ap.Receivability.REFUSED, "refusals": (defect,), "blocks": (), "roots": (), "b3_completeness": ap.Completeness.NOT_BUILT, "incomplete_reasons": (),
               "rescan": ap.RescanStatus.NOT_PERFORMED}
    with pytest.raises(ValueError):
        ap.AuditReport(**refused)
    plain_refusal = ap.AuditReport(ap.Receivability.REFUSED, refusals=(defect,))
    assert plain_refusal.plan_declared_diagnostic is None
    with pytest.raises(ValueError, match="champs de registre"):
        ap.AuditReport(ap.Receivability.REFUSED, refusals=(defect,), plan_declared_diagnostic=good.plan_declared_diagnostic)


def test_rp7_the_diagnostic_never_changes_the_authority_constants(good):
    assert good.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE and good.grants == () and good.grants_nothing and good.persistence is ap.Persistence.NOT_PERSISTED
    assert good.protocol_version == "gate_v_audit_protocol_v2"
    names = {f.name for f in dataclasses.fields(ap.AuditReport)}
    assert not {"absence_evidence", "grants", "not_proven", "inventory_id", "inventory_content_digest"} & names
    assert good.not_proven == B1A_NOT_PROVEN + FIVE and "PLAN_DECLARED" not in "".join(good.not_proven)                                    # D5 : `_NOT_PROVEN` inchangé, comparé à ses littéraux


def test_rp8_two_audits_of_the_same_world_give_equal_diagnostics(tmp_path_factory):
    reports = []
    for index in range(2):
        tmp_path = tmp_path_factory.mktemp(f"n2b2a_twice_{index}")
        audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED + [("R", B, *EARLY)])
        reports.append(ap.audit_campaign_exposure(request(audit, cfg)))
    assert reports[0].plan_declared_diagnostic == reports[1].plan_declared_diagnostic


@pytest.mark.parametrize("error", [MemoryError("simulated"), RecursionError("simulated")])
def test_rp9_critical_failures_of_the_diagnostic_become_a_typed_internal_refusal_never_a_report(tmp_path, monkeypatch, error):
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED + [("R", B, *EARLY)])

    def boom(*a, **k):
        raise error
    monkeypatch.setattr(ar.plan_declared, "diagnose", boom)
    report = ap.audit_campaign_exposure(request(audit, cfg))
    assert report.receivability is ap.Receivability.REFUSED and report.plan_declared_diagnostic is None
    assert [(d.code, d.stage, d.detail) for d in report.refusals] == [(R.AUDIT_INTERNAL_FAILURE, ap.Stage.PROTOCOL, type(error).__name__)]


def test_rp10_a_registry_changed_between_the_scans_yields_a_refusal_without_any_diagnostic(tmp_path, monkeypatch):
    audit, root, cfg = setup_world(tmp_path, OWN_RESERVED + [("R", B, *EARLY)])
    calls = []
    real_scan = ap.interpret_audit_roots_v6

    def scan_then_extend(*a, **k):
        result = real_scan(*a, **k)
        calls.append(1)
        if len(calls) == 2:
            sup.put_slot(root, 2, sup.build_chain(OWN_RESERVED + [("R", B, *EARLY), ("R", sup.foreign_id(0xC), "2025-03-01T00:00:00.000000Z", "2025-03-02T00:00:00.000000Z")])[2])
        return result

    monkeypatch.setattr(ap, "interpret_audit_roots_v6", scan_then_extend)
    report = ap.audit_campaign_exposure(request(audit, cfg))
    assert report.receivability is ap.Receivability.REFUSED and report.plan_declared_diagnostic is None and report.registry_id is None
    assert [(d.code, d.stage, d.detail) for d in report.refusals] == [(R.REGISTRY_CHAIN_HEAD_CHANGED, ap.Stage.REGISTRY, "EXTENDED")]


def end_to_end_report(tmp_path, world):
    base = tmp_path / "aud"
    base.mkdir()
    layout = lay_out(base, world.plan, world.split_plan)
    plans = [forge_plan(world.plan, budget_per_fold=11), forge_plan(world.plan, budget_per_fold=12, strategy_name="other_strategy")]
    paths = [save_gate_v_campaign_plan_v2(base, plan).parent for plan in plans]
    root = sup.new_registry(tmp_path, "reg")
    sup.populate(root, sup.build_chain([("R", layout.campaign_id, *HOLDOUT_NORMALISED)] + [("R", plan.campaign_id, *window_of(i)) for i, plan in enumerate(plans)]))
    cfg = ar.RegistryConfig(root_path=str(root), max_slots=1000, max_total_bytes=100_000)
    req = request_for(campaign_spec(layout.campaign_dir, label=CAMPAIGN_LABEL), split_spec(layout), campaign_spec(paths[0], label="b"), campaign_spec(paths[1], label="c"), own=layout.campaign_id,
                      window_start_utc=HOLDOUT[0], window_end_utc=HOLDOUT[1], window_source=window_source(), registry=cfg, protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=10 ** 12))
    return ap.audit_campaign_exposure(req)


def test_rp11_end_to_end_with_real_foreign_plans_reaches_the_report(tmp_path, world):
    report = end_to_end_report(tmp_path, world)
    assert report.receivability is ap.Receivability.RECEIVABLE, report.refusals
    diagnostic = report.plan_declared_diagnostic
    assert report.derived_root_labels == ("b", "c") and diagnostic.basis is pd.PlanDeclaredBasis.EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ
    assert (diagnostic.source_campaign_count, diagnostic.declared_run_reference_count, diagnostic.declared_search_config_count, diagnostic.multi_campaign_run_reference_count) == (2, 1, 2, 1)
    assert [c.value for c in report.trial_counters] == [None, None, 2, None, None, None] and report.grants == ()


def test_rp12_the_report_clauses_are_satisfiable_by_legitimate_diagnostics_and_clause_11_stands_alone(tmp_path, world):
    report = end_to_end_report(tmp_path, world)
    base = fields_of(report)
    one_invalid = pd.PlanDeclaredDiagnostic(basis=pd.PlanDeclaredBasis.SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ, source_campaign_count=1, unavailable_campaign_count=1,
                                            unavailable_breakdown=(("PLAN_FIELD_INVALID", 1),), declared_run_reference_count=1, declared_run_id_count=1, declared_search_config_count=1,
                                            declared_strategy_name_count=1, multi_campaign_run_reference_count=None, multi_campaign_search_config_count=None,
                                            id_with_several_content_hashes_count=None, content_hash_with_several_ids_count=None, conflicting_run_id_sample=())
    assert ap.AuditReport(**{**base, "plan_declared_diagnostic": one_invalid}).plan_declared_diagnostic == one_invalid           # un plan illisible parmi deux racines dérivées : cohérent
    missing_one = dataclasses.replace(one_invalid, basis=pd.PlanDeclaredBasis.EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ, unavailable_campaign_count=0, unavailable_breakdown=())
    with pytest.raises(ValueError, match="champs de registre"):
        ap.AuditReport(**{**base, "plan_declared_diagnostic": missing_one})                                                      # seule la clause (11) : 1 + 0 != 2
