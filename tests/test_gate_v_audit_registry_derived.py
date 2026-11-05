"""N2-b1b, tranche T5 — RACINES DÉRIVÉES et couverture du registre par des racines (groupe DR de la note section 19.13).

Plans de campagne V2 RÉELS (fabriques historiques, dépôt Git jetable sous `tmp_path`) et plans AUTO-COHÉRENTS forgés (`forge_plan`). Une racine « dérivée » est attribuée si son plan V2, recalculé depuis son
contenu, porte le nom attendu ; la couverture ne dit RIEN du contenu des dossiers ni de l'exposition (un plan authentique recopié passerait : limite consignée).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gate_v_audit_registry as ar
import gate_v_audit_window as aw
import gate_v_registry_audit_support as sup
from gate_v_campaign_plan_v2 import save_gate_v_campaign_plan_v2
from tests.gate_v_audit_window_support import build_world, forge_plan
from tests.gate_v_manifest_scenarios import SCENARIOS, realise

WN = sup.WN
EARLY = ("2025-01-01T00:00:00.000000Z", "2025-02-01T00:00:00.000000Z")
MAX_JSON = 1_000_000


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("derived_world")
    return build_world(base)


@pytest.fixture
def audit(world, tmp_path):
    """Campagnes propre (A) et étrangère (B) avec leurs plans V2 authentiques sous `tmp_path/audit`."""
    base = tmp_path / "audit"
    base.mkdir()
    plan_a = world.plan
    plan_b = forge_plan(world.plan, budget_per_fold=11)
    assert plan_a.campaign_id != plan_b.campaign_id
    path_a, path_b = save_gate_v_campaign_plan_v2(base, plan_a).parent, save_gate_v_campaign_plan_v2(base, plan_b).parent
    return type("Audit", (), {"base": base, "a": plan_a.campaign_id, "b": plan_b.campaign_id, "path_a": path_a, "path_b": path_b})


def run(tmp_path, audit_world, chain_entries, roots, *, name="registry", mutate_after_s1=None):
    root = sup.new_registry(tmp_path, name)
    sup.populate(root, sup.build_chain(chain_entries))
    cfg = ar.RegistryConfig(root_path=str(root), max_slots=1000, max_total_bytes=10 ** 7)
    handle = ar.read(cfg, own_campaign_id=audit_world.a, window=WN)
    s1 = sup.interpret_campaigns([(label, path) for label, path, _expected in roots])
    if mutate_after_s1 is not None:
        mutate_after_s1()
    return ar.assess(handle, s1, own_campaign_id=audit_world.a, window=WN, campaign_roots=tuple((label, str(path), expected) for label, path, expected in roots), max_json_bytes=MAX_JSON)


def entries(audit_world, *others):
    return [("R", audit_world.a, *WN)] + [("R", other, *EARLY) for other in others]


def test_dr1_authentic_plan_in_a_directory_named_like_a_registered_campaign_is_derived(tmp_path, audit):
    result = run(tmp_path, audit, entries(audit, audit.b), [("own", audit.path_a, audit.a), ("b", audit.path_b, audit.b)])
    assert result.derived_root_labels == ("b",)
    assert result.registry_coverage is ar.RegistryCoverage.ALL_CHAIN_CAMPAIGNS_HAVE_ROOT
    assert (result.registry_other_campaign_count, result.registry_uncovered_count, result.registry_uncovered_sample) == (1, 0, ())
    assert result.b4_complete is True


def test_dr2_a_registered_campaign_without_a_root_is_partial_with_exact_counts(tmp_path, audit):
    result = run(tmp_path, audit, entries(audit, audit.b), [("own", audit.path_a, audit.a)])
    assert result.derived_root_labels == () and result.registry_coverage is ar.RegistryCoverage.PARTIAL
    assert (result.registry_other_campaign_count, result.registry_uncovered_count, result.registry_uncovered_sample) == (1, 1, (audit.b,))
    assert result.b4_complete is True                                                                            # B4 COMPLETE et couverture PARTIAL : exposés tels quels, jamais agrégés


@pytest.mark.parametrize("count,sample_len", [(20, 20), (21, 20)])
def test_dr3_sample_is_the_first_20_sorted_identifiers_and_count_is_exact(tmp_path, audit, count, sample_len):
    foreigners = [sup.foreign_id(0x100 + index) for index in range(count)]
    chain = [("R", audit.a, *WN)] + [("R", cid, f"2024-01-{day + 1:02d}T00:00:00.000000Z", f"2024-01-{day + 2:02d}T00:00:00.000000Z") for day, cid in enumerate(foreigners)]
    result = run(tmp_path, audit, chain, [("own", audit.path_a, audit.a)])
    assert (result.registry_other_campaign_count, result.registry_uncovered_count) == (count, count)
    assert result.registry_uncovered_sample == tuple(sorted(foreigners))[:sample_len] and len(result.registry_uncovered_sample) == sample_len


def test_dr4_a_root_whose_name_is_not_in_the_chain_stays_static(tmp_path, audit):
    result = run(tmp_path, audit, entries(audit), [("own", audit.path_a, audit.a), ("b", audit.path_b, audit.b)])
    assert result.derived_root_labels == () and result.registry_other_campaign_count == 0
    assert result.registry_coverage is ar.RegistryCoverage.ALL_CHAIN_CAMPAIGNS_HAVE_ROOT                          # vrai par vacuité : ne dit rien du contenu


def test_dr5_a_forged_minimal_anchor_is_refuted_by_the_v2_loader(tmp_path, audit):
    forged = tmp_path / "forged" / audit.b
    forged.mkdir(parents=True)
    (forged / "plan.json").write_bytes(b'{"campaign_id": "%s"}' % audit.b.encode())                         # ancre minimale : B3 la juge « complète »
    s1 = sup.interpret_campaigns([("forged", forged)])
    assert s1.complete is True                                                                                   # B3 seul accepte cette ancre forgée
    result = run(tmp_path, audit, entries(audit, audit.b), [("own", audit.path_a, audit.a), ("b", forged, audit.b)])
    assert result.derived_root_labels == () and result.registry_coverage is ar.RegistryCoverage.PARTIAL and result.registry_uncovered_sample == (audit.b,)


@pytest.mark.parametrize("variant", ["missing", "another_campaigns_plan", "garbage"])
def test_dr6_anchor_variants_leave_the_root_static(tmp_path, audit, variant):
    target = audit.path_b
    plan_file = target / "plan.json"
    if variant == "missing":
        plan_file.unlink()
        (target / "notes.txt").write_bytes(b"x")                                                                 # une racine vide est refusée par le scanner : on garde un fichier inerte
    elif variant == "another_campaigns_plan":
        plan_file.write_bytes((audit.path_a / "plan.json").read_bytes())
    else:
        plan_file.write_bytes(b"{")
    result = run(tmp_path, audit, entries(audit, audit.b), [("own", audit.path_a, audit.a), ("b", target, audit.b)])
    assert result.derived_root_labels == () and result.registry_coverage is ar.RegistryCoverage.PARTIAL


def test_dr7_a_plan_changed_between_the_first_scan_and_the_guarded_read_is_static(tmp_path, audit):
    plan_file = audit.path_b / "plan.json"
    result = run(tmp_path, audit, entries(audit, audit.b), [("own", audit.path_a, audit.a), ("b", audit.path_b, audit.b)],
                 mutate_after_s1=lambda: plan_file.write_bytes(plan_file.read_bytes() + b"\n"))
    assert result.derived_root_labels == () and result.registry_coverage is ar.RegistryCoverage.PARTIAL


def test_dr8_a_derived_root_with_an_unresolved_exposing_source_keeps_the_inventory_incomplete(tmp_path, audit):
    (audit.path_b / "final_holdout_access_claim.json").write_bytes(b"{")
    result = run(tmp_path, audit, entries(audit, audit.b), [("own", audit.path_a, audit.a), ("b", audit.path_b, audit.b)])
    assert result.derived_root_labels == ("b",) and result.b4_complete is False


def test_dr9_root_order_does_not_change_the_assessment(tmp_path, audit):
    roots = [("own", audit.path_a, audit.a), ("b", audit.path_b, audit.b)]
    first = run(tmp_path, audit, entries(audit, audit.b), roots, name="r1")
    second = run(tmp_path, audit, entries(audit, audit.b), list(reversed(roots)), name="r2")
    assert first == second


def test_dr12_dr13_own_root_is_never_derived_and_dimensions_stay_separate(tmp_path, audit):
    result = run(tmp_path, audit, entries(audit, audit.b), [("own", audit.path_a, audit.a)])
    assert "own" not in result.derived_root_labels
    fields = {f for f in result.__dataclass_fields__}
    assert not {name for name in fields if {"complete", "overall", "global", "all"} & set(name.split("_"))} - {"b4_complete"}      # `b4_complete` : la complétude de B4 seule
    assert not hasattr(result, "overall") and not hasattr(result, "global_complete")


def test_dr_parity_with_the_window_derivation_on_the_own_plan(tmp_path, audit, world):
    """Parité de comportement : la fonction NOUVELLE accepte le plan propre authentique comme le fait la dérivation de b1a (qui n'est pas modifiée)."""
    s1 = sup.interpret_campaigns([("own", audit.path_a)])
    assert aw.plan_root_attributed(s1, label="own", root_path=str(audit.path_a), expected_name=audit.a, max_json_bytes=MAX_JSON) is True
    assert aw.plan_root_attributed(s1, label="own", root_path=str(audit.path_a), expected_name=audit.b, max_json_bytes=MAX_JSON) is False
    assert aw.plan_root_attributed(s1, label="absent", root_path=str(audit.path_a), expected_name=audit.a, max_json_bytes=MAX_JSON) is False


# ── Durcissement (revue des tests, mutants W02 / W03) ─────────────────────────────────────────────────────────────────────────────────────────

def test_dr7_the_second_guarded_read_catches_a_change_made_during_the_loader(tmp_path, audit, monkeypatch):
    plan_file = audit.path_b / "plan.json"
    real = aw.load_gate_v_campaign_plan_v2

    def load_then_change(path):
        plan = real(path)
        plan_file.write_bytes(plan_file.read_bytes() + b"\n")
        return plan

    monkeypatch.setattr(aw, "load_gate_v_campaign_plan_v2", load_then_change)
    result = run(tmp_path, audit, entries(audit, audit.b), [("own", audit.path_a, audit.a), ("b", audit.path_b, audit.b)])
    assert result.derived_root_labels == () and result.registry_coverage is ar.RegistryCoverage.PARTIAL


def test_dr7_the_first_guarded_read_prevents_the_loader_from_reading_a_changed_file(tmp_path, audit, monkeypatch):
    plan_file = audit.path_b / "plan.json"
    calls, real = [], aw.load_gate_v_campaign_plan_v2
    monkeypatch.setattr(aw, "load_gate_v_campaign_plan_v2", lambda path: (calls.append(path), real(path))[1])
    unchanged = run(tmp_path, audit, entries(audit, audit.b), [("own", audit.path_a, audit.a), ("b", audit.path_b, audit.b)], name="r1")
    assert unchanged.derived_root_labels == ("b",) and calls == [str(audit.path_b / "plan.json")]              # anti-vacuité : le chargeur est appelé pour une racine intacte
    calls.clear()
    changed = run(tmp_path, audit, entries(audit, audit.b), [("own", audit.path_a, audit.a), ("b", audit.path_b, audit.b)], name="r2",
                  mutate_after_s1=lambda: plan_file.write_bytes(plan_file.read_bytes() + b"\n"))
    assert changed.derived_root_labels == () and calls == []                                                   # jamais lu par le chargeur : la première garde refuse d'abord


@pytest.mark.parametrize("variant", ["bom", "directory", "case", "tampered"])
def test_dr6_more_anchor_variants_leave_the_root_static(tmp_path, audit, variant):
    import json
    target = audit.path_b
    plan_file = target / "plan.json"
    if variant == "bom":
        plan_file.write_bytes(b"\xef\xbb\xbf" + plan_file.read_bytes())
    elif variant == "directory":
        plan_file.unlink()
        plan_file.mkdir()
        (plan_file / "x").write_bytes(b"x")
    elif variant == "case":
        plan_file.rename(target / "Plan.json")
    else:
        record = json.loads(plan_file.read_bytes())
        record["budget_per_fold"] = 12                                                                        # plan modifié : l'identifiant recalculé ne correspond plus
        plan_file.write_bytes(json.dumps(record).encode("utf-8"))
    result = run(tmp_path, audit, entries(audit, audit.b), [("own", audit.path_a, audit.a), ("b", target, audit.b)])
    assert result.derived_root_labels == () and result.registry_coverage is ar.RegistryCoverage.PARTIAL


def test_the_static_to_derived_switch_changes_what_b4_receives_and_its_inventory_identity(tmp_path, audit, monkeypatch):
    import json
    seen, real = [], ar.assemble_exposure_inventory

    def spy(interpretation, **kwargs):
        assembly = real(interpretation, **kwargs)
        seen.append((kwargs["derived_root_labels"], assembly.inventory.scanned_roots, assembly.inventory_id))
        return assembly

    monkeypatch.setattr(ar, "assemble_exposure_inventory", spy)
    roots = [("own", audit.path_a, audit.a), ("b", audit.path_b, audit.b)]
    run(tmp_path, audit, entries(audit, audit.b), roots, name="derived")
    plan_file = audit.path_b / "plan.json"
    record = json.loads(plan_file.read_bytes())
    record["budget_per_fold"] = 12                                                                              # le plan ne correspond plus à son identifiant : la racine devient statique
    plan_file.write_bytes(json.dumps(record).encode("utf-8"))                                                   # modifié AVANT le nouveau S1 : l'ancre B3 reste acceptée (nom égal), le chargeur refuse
    run(tmp_path, audit, entries(audit, audit.b), roots, name="static")
    assert seen[0][:2] == (("b",), ("own",)) and seen[1][:2] == ((), ("b", "own"))
    assert seen[0][2] != seen[1][2]                                                                             # l'identité de l'inventaire change quand un label passe de statique à dérivé


def test_dr9_root_order_does_not_change_the_assessment_and_both_runs_are_really_derived(tmp_path, audit):
    roots = [("own", audit.path_a, audit.a), ("b", audit.path_b, audit.b)]
    first = run(tmp_path, audit, entries(audit, audit.b), roots, name="r1")
    second = run(tmp_path, audit, entries(audit, audit.b), list(reversed(roots)), name="r2")
    assert first == second and first.derived_root_labels == ("b",) and second.derived_root_labels == ("b",)
