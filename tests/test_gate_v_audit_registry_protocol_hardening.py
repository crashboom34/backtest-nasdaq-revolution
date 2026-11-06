"""N2-b1b — DURCISSEMENT de l'intégration (revue des tests, mutants survivants) : clauses du rapport une à une, fenêtre normalisée avant la comparaison, budgets combinés, recouvrement d'une racine de plan de
split, intégrité (tailles, mtime) et absence d'accès aux données de marché y compris sur refus, ordre d'appel complet, racine dérivée de bout en bout.

Fixtures SYNTHÉTIQUES (`tmp_path`). Aucun A0, aucune admission, aucune écriture de registre par l'audit, aucune donnée de marché, aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import builtins
import dataclasses
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gate_v_audit_protocol as ap
import gate_v_audit_registry as ar
import gate_v_registry_audit_support as sup
from gate_v_campaign_plan_v2 import save_gate_v_campaign_plan_v2
from tests.gate_v_audit_protocol_support import campaign_spec, request_for
from tests.gate_v_audit_window_support import (CAMPAIGN_LABEL, HOLDOUT, HOLDOUT_NORMALISED, build_world, derived_request, forge_plan, lay_out, split_spec, window_source)
from tests.gate_v_exposure_support import LIMITS
from tests.gate_v_manifest_scenarios import CID, HL, SCENARIOS, realise
from tests.test_gate_v_audit_registry_protocol import EARLY, OWN_RESERVED, SCAN_BUDGET, WN, B, R, refusal, request, setup_world
from gate_v_exposure_scan import scan_worst_case_read_bytes


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("n2b1b_hard_world"))


@pytest.fixture(scope="module")
def good(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("n2b1b_hard_good")
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED + [("R", B, *EARLY)])
    return ap.audit_campaign_exposure(request(audit, cfg))


@pytest.fixture
def no_registry_read(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("lecture du registre avant un refus de requête")
    monkeypatch.setattr(ar, "read_registry", boom)


def _derived_setup(tmp_path, world):
    base = tmp_path / "aud"
    base.mkdir()
    layout = lay_out(base, world.plan, world.split_plan)
    root = sup.new_registry(tmp_path, "reg")
    sup.populate(root, sup.build_chain([("R", layout.campaign_id, *HOLDOUT_NORMALISED)]))
    cfg = ar.RegistryConfig(root_path=str(root), max_slots=1000, max_total_bytes=100_000)
    return layout, root, cfg, derived_request(layout, registry=cfg)


def fields_of(report):
    return {f.name: getattr(report, f.name) for f in dataclasses.fields(ap.AuditReport)}


# ── RP1 : clauses du rapport ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_rp1_a_valid_report_passes_and_each_clause_raises_a_value_error_of_the_registry_family(good):
    assert dataclasses.replace(good) == good
    base = fields_of(good)
    for changes in (dict(registry_id=None), dict(trial_counters=()), dict(blocks=()), dict(b4_incomplete_reasons=("X",)), dict(derived_root_labels=("x",)),
                    dict(registry_uncovered_count=5)):
        with pytest.raises(ValueError, match="champs de registre"):
            ap.AuditReport(**{**base, **changes})


def test_rp1_clause_7_alone_a_refused_report_with_fully_consistent_registry_fields(good):
    defect = ap.AuditDefect(R.REQUEST_INVALID, ap.Stage.REQUEST)
    refused_fields = {**fields_of(good), "receivability": ap.Receivability.REFUSED, "refusals": (defect,), "blocks": (), "roots": (), "b3_completeness": ap.Completeness.NOT_BUILT,
                      "incomplete_reasons": (), "rescan": ap.RescanStatus.NOT_PERFORMED, "b4_completeness": ap.Completeness.INCOMPLETE, "b4_incomplete_reasons": ("X",),
                      "registry_coverage": ar.RegistryCoverage.ALL_CHAIN_CAMPAIGNS_HAVE_ROOT, "registry_uncovered_count": 0, "registry_uncovered_sample": (),
                      "registry_other_campaign_count": 1, "derived_root_labels": ("b",)}
    # P6 (cinquième amendement, N2-b2a) : diagnostic cohérent avec une autre campagne attribuée dont le plan n'est pas lu (invariants (10) à (12)), sinon la clause (12) échouerait aussi.
    refused_fields["plan_declared_diagnostic"] = ar.PlanDeclaredDiagnostic(
        basis=ar.PlanDeclaredBasis.NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ, source_campaign_count=0, unavailable_campaign_count=1, unavailable_breakdown=(("PLAN_RECORD_NOT_READ", 1),),
        declared_run_reference_count=None, declared_run_id_count=None, declared_search_config_count=None, declared_strategy_name_count=None, multi_campaign_run_reference_count=None,
        multi_campaign_search_config_count=None, id_with_several_content_hashes_count=None, content_hash_with_several_ids_count=None, conflicting_run_id_sample=())
    witness = object.__new__(ap.AuditReport)                                                                    # témoin : les mêmes champs, sauf le refus, satisfont TOUTES les autres clauses de registre
    for name, value in {**refused_fields, "receivability": ap.Receivability.RECEIVABLE, "refusals": ()}.items():
        object.__setattr__(witness, name, value)
    witness._check_registry_fields()
    with pytest.raises(ValueError, match="champs de registre"):
        ap.AuditReport(**refused_fields)


def test_rp1_clause_4_the_sample_is_20_for_21_uncovered(good):
    ids = tuple(sorted(sup.foreign_id(0x100 + i) for i in range(21)))
    twenty_one_unavailable = dataclasses.replace(good.plan_declared_diagnostic, unavailable_campaign_count=21, unavailable_breakdown=(("NO_ATTRIBUTED_ROOT", 21),))          # N2-b2a : invariant (11)
    valid = {**fields_of(good), "registry_other_campaign_count": 21, "registry_uncovered_count": 21, "registry_uncovered_sample": ids[:20], "plan_declared_diagnostic": twenty_one_unavailable}
    assert ap.AuditReport(**valid).registry_uncovered_count == 21
    for sample in (ids[:21], ids[:19]):
        with pytest.raises(ValueError, match="champs de registre"):
            ap.AuditReport(**{**valid, "registry_uncovered_sample": sample})


# ── Fenêtre normalisée, recouvrement, budgets combinés ───────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("window,expected", [
    (("2026-01-01T01:00:00+01:00", "2026-04-01T02:00:00+02:00"), "RECEIVABLE"),                                 # fenêtre équivalente avec fuseaux : normalisée, aucun écart
    (("2026-01-01T00:00:00.000001+00:00", "2026-04-01T00:00:00+00:00"), "WINDOW_MISMATCH")])                  # écart de 1 µs avec l'enregistrement propre
def test_cv6_the_operator_window_is_normalised_before_the_own_record_comparison(tmp_path, window, expected):
    audit, _root, cfg = setup_world(tmp_path, OWN_RESERVED)
    report = ap.audit_campaign_exposure(request(audit, cfg, window_start_utc=window[0], window_end_utc=window[1]))
    assert (report.refusals[0].code.value if report.refusals else report.receivability.value) == expected


def test_rq2_the_registry_may_not_overlap_a_split_plan_root_either(tmp_path, no_registry_read, world):
    base = tmp_path / "aud"
    base.mkdir()
    layout = lay_out(base, world.plan, world.split_plan)
    for path in (layout.split_dir, layout.split_dir / "reg", layout.split_dir.parent):
        cfg = ar.RegistryConfig(root_path=str(path), max_slots=10, max_total_bytes=1000)
        defect = refusal(ap.audit_campaign_exposure(derived_request(layout, registry=cfg)))
        assert (defect.code, defect.detail) == (R.REQUEST_INVALID, "REGISTRY_ROOT_OVERLAP"), path


def test_rq5_registry_and_window_source_budgets_add_up_exactly(tmp_path, world):
    layout, _root, cfg, _req = _derived_setup(tmp_path, world)
    needed = 2 * SCAN_BUDGET + 6 * LIMITS.max_json_bytes + 2 * (cfg.max_total_bytes + 4098)                       # deux dispositions + provenance de W + part registre
    ok = derived_request(layout, registry=cfg, protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=needed))
    assert ap.audit_campaign_exposure(ok).receivability is ap.Receivability.RECEIVABLE
    short = derived_request(layout, registry=cfg, protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=needed - 1))
    assert refusal(ap.audit_campaign_exposure(short)).detail == "REGISTRY_BUDGET"


# ── NW : tailles et mtime inchangés, aucune donnée de marché, y compris sur refus ───────────────────────────────────────────────────────────────

def tree_stats(base):
    stats = []
    for directory, names, files in os.walk(base):
        names.sort()
        for name in sorted(files):
            info = os.lstat(os.path.join(directory, name))
            stats.append((os.path.relpath(os.path.join(directory, name), base), info.st_size, info.st_mtime_ns))
    return stats


@pytest.mark.parametrize("refuse", [False, True])
def test_nw_sizes_and_mtimes_are_unchanged_and_market_data_is_never_touched_even_on_refusal(tmp_path, monkeypatch, refuse):
    entries = [("R", CID, WN[0], "2026-03-01T00:00:00.000000Z")] if refuse else OWN_RESERVED + [("R", B, *EARLY)]
    audit, root, cfg = setup_world(tmp_path, entries)
    sentinel = tmp_path / "nasdaq_3m.csv"
    sentinel.write_bytes(b"time,open\n")
    before = (tree_stats(audit), tree_stats(root), sentinel.stat().st_mtime_ns)
    seen = []
    real_open, real_lstat, real_builtin_open = os.open, os.lstat, builtins.open
    monkeypatch.setattr(os, "open", lambda path, *a, **k: (seen.append(str(path)), real_open(path, *a, **k))[1])
    monkeypatch.setattr(os, "lstat", lambda path, *a, **k: (seen.append(str(path)), real_lstat(path, *a, **k))[1])
    monkeypatch.setattr(builtins, "open", lambda path, *a, **k: (seen.append(str(path)), real_builtin_open(path, *a, **k))[1])
    report = ap.audit_campaign_exposure(request(audit, cfg))
    monkeypatch.undo()
    assert (report.receivability is ap.Receivability.REFUSED) is refuse and seen
    assert not any("nasdaq_3m" in path for path in seen)
    assert (tree_stats(audit), tree_stats(root), sentinel.stat().st_mtime_ns) == before


# ── RD8 complet et racine dérivée de bout en bout ────────────────────────────────────────────────────────────────────────────────────────────────

def test_rd8_the_full_call_order_includes_l3a_and_the_final_window_recheck(tmp_path, world, monkeypatch):
    _layout, _root, _cfg, req = _derived_setup(tmp_path, world)
    log = []

    def wrap(owner, name, label):
        real = getattr(owner, name)
        monkeypatch.setattr(owner, name, lambda *a, **k: (log.append(label), real(*a, **k))[1])

    for name in ("read", "assess", "compare"):
        wrap(ap.registry_audit, name, name)
    wrap(ap, "interpret_audit_roots_v6", "scan")
    wrap(ap, "_campaign_report", "l3a")
    wrap(ap.provenance, "recheck_sources", "recheck")
    assert ap.audit_campaign_exposure(req).receivability is ap.Receivability.RECEIVABLE
    assert log == ["read", "scan", "l3a", "assess", "scan", "recheck", "compare"]


def test_a_derived_root_reaches_the_report_end_to_end(tmp_path, world):
    base = tmp_path / "aud"
    base.mkdir()
    layout = lay_out(base, world.plan, world.split_plan)
    plan_b = forge_plan(world.plan, budget_per_fold=11)
    path_b = save_gate_v_campaign_plan_v2(base, plan_b).parent
    root = sup.new_registry(tmp_path, "reg")
    sup.populate(root, sup.build_chain([("R", layout.campaign_id, *HOLDOUT_NORMALISED), ("R", plan_b.campaign_id, *EARLY)]))
    cfg = ar.RegistryConfig(root_path=str(root), max_slots=1000, max_total_bytes=100_000)
    req = request_for(campaign_spec(layout.campaign_dir, label=CAMPAIGN_LABEL), split_spec(layout), campaign_spec(path_b, label="b"), own=layout.campaign_id,
                      window_start_utc=HOLDOUT[0], window_end_utc=HOLDOUT[1], window_source=window_source(), registry=cfg,
                      protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=10 ** 12))
    report = ap.audit_campaign_exposure(req)
    assert report.receivability is ap.Receivability.RECEIVABLE, report.refusals
    assert report.derived_root_labels == ("b",) and report.registry_coverage is ar.RegistryCoverage.ALL_CHAIN_CAMPAIGNS_HAVE_ROOT
    assert (report.registry_other_campaign_count, report.registry_uncovered_count) == (1, 0)
    assert not [b for b in report.blocks if b.code is ap.BlockCode.DERIVED_COVERAGE_PARTIAL]
