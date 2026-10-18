"""AF-V-07 Slice E3-B4 — assemblage de l'`ExposureInventory` et comptabilité des essais (six compteurs + provenance).

Fixtures SYNTHÉTIQUES dans `tmp_path` uniquement : aucune donnée réelle, aucun `FINAL_HOLDOUT`, aucun accès réseau.
Contrat : ADR 0025 23.11 étape 1 et « Comptabilité des essais », 23.27.1-23.27.6, 23.29.5, 23.30 ; design E3-B (AI_HANDOFF.md §44.1,
§45) ; préconditions B3/B4 (§47, §51.4). Les identités attendues viennent d'E3-A (publié), jamais d'un recalcul local.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import gate_v_exposure_interpreters as b3
import gate_v_exposure_inventory as b4
from gate_v_exposure_scan import AuditRoot, ScanLimits
from gate_v_final_holdout_protocol import (
    ExposureInventory,
    OverlapVerdict,
    OwnCampaignContext,
    OwnRecordStage,
    SourceKind,
    SourceStatus,
    TrialAccounting,
    compute_exposure_inventory_id,
    compute_inventory_content_digest,
)

W = ("2026-01-01T00:00:00+00:00", "2026-04-01T00:00:00+00:00")  # fenêtre FINAL_HOLDOUT synthétique
W_NORM = ("2026-01-01T00:00:00.000000Z", "2026-04-01T00:00:00.000000Z")
CURRENT = "campaign_current"
STAGE0 = OwnCampaignContext(CURRENT, OwnRecordStage.NO_OWN_RECORDS)

LIMITS = ScanLimits(max_roots=8, max_entries=2_000, max_depth=8, max_json_bytes=1_000_000, max_total_read_bytes=8_000_000,
                    max_json_depth=32, max_name_length=128, max_path_length=1_024, max_attempts=1)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, indent=2).encode("utf-8"))


def make_job(results: Path, name: str, start=None, end=None) -> None:
    write_json(results / name / "config_used.json",
               {"run_id": name, "strategy_name": "s", "opt_start_date": start, "opt_end_date": end})
    for file in ("archive.zip", "logs.txt"):
        (results / name / file).write_bytes(b"x")


def interpret(tmp_path: Path, *, job=("2026-02-01T00:00:00+00:00", "2026-02-10T00:00:00+00:00"), label="res"):
    """Interprétation B3 RÉELLE d'une racine `results` synthétique (un job exécuté dans `W` par défaut → exposition établie)."""
    results = tmp_path / "results"
    make_job(results, "job_1", *job)
    root = b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot(label, str(results)))
    return b3.interpret_audit_roots((root,), LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])


def h(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def registry(records=(), unreadable=(), head="a" * 64, registry_id="reg_main") -> b4.RegistryView:
    return b4.RegistryView(registry_id=registry_id, chain_head=head, records=tuple(records), unreadable_record_ids=tuple(unreadable))


def assemble(interpretation, *, reg=None, accounting=None, context=STAGE0, derived=()):
    return b4.assemble_exposure_inventory(
        interpretation, registry=registry() if reg is None else reg,
        accounting=b4.AccountingViews() if accounting is None else accounting,
        own_context=context, derived_root_labels=derived)


# ── Tranche 1 : traceur — les findings de B3 sont repris tels quels, la comptabilité sans source est NOT_OBSERVED ─────────

def test_b3_findings_are_carried_unchanged_and_accounting_without_sources_is_not_observed(tmp_path):
    interpretation = interpret(tmp_path)
    assembly = assemble(interpretation)
    inventory = assembly.inventory
    assert type(inventory) is ExposureInventory
    assert inventory.findings == interpretation.findings and len(inventory.findings) == 1
    assert (inventory.window_start_utc, inventory.window_end_utc) == W_NORM
    assert inventory.scanned_roots == ("res",) and inventory.complete is True and assembly.incomplete_reasons == ()
    assert inventory.trial_accounting == TrialAccounting(0, 0, 0, 0, 0, 0)
    provenance = assembly.accounting_provenance
    assert provenance.campaigns is b4.CounterProvenance.OBSERVED            # registre lu intégralement : zéro vérifié
    for name in ("research_runs", "strategies", "abandoned_reservations", "failed_ingestion_attempts", "void_commitments"):
        assert getattr(provenance, name) is b4.CounterProvenance.NOT_OBSERVED, name   # aucune source : espace réservé, pas un zéro
    assert assembly.inventory_id == compute_exposure_inventory_id(inventory, STAGE0)
    assert assembly.inventory_content_digest == compute_inventory_content_digest(inventory, STAGE0)
    assert (assembly.registry_id, assembly.registry_chain_head) == ("reg_main", "a" * 64)
    assert assembly.interpretation is interpretation


# ── Tranche 2 : registre — findings, règle de listabilité d'E3-A, compteur `campaigns` (23.27.5) ─────────────────────────

RES, ADM, CONS = SourceKind.REGISTRY_RESERVATION, SourceKind.REGISTRY_ADMISSION, SourceKind.CONSUMPTION
INSIDE = ("2026-01-15T00:00:00+00:00", "2026-02-15T00:00:00+00:00")        # recoupe W
AFTER = ("2026-06-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00")         # après W
TOUCHING = ("2025-12-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00")      # fin exclusive = ws : ne recoupe pas


def rec(seq, kind, campaign_id, window=INSIDE, **changes) -> b4.RegistryRecordFact:
    values = dict(seq=seq, kind=kind, campaign_id=campaign_id, content_hash=h(f"record-{seq}"),
                  window_start_utc=window[0] if window else None, window_end_utc=window[1] if window else None)
    values.update(changes)
    return b4.RegistryRecordFact(**values)


def ids(assembly) -> list:
    return [f.source_id for f in assembly.inventory.findings]


def by_id(assembly, source_id):
    (match,) = [f for f in assembly.inventory.findings if f.source_id == source_id]
    return match


def test_foreign_overlapping_reservation_is_listed_as_resolved_overlap(tmp_path):
    assembly = assemble(interpret(tmp_path), reg=registry([rec(1, RES, "camp_a")]))
    finding = by_id(assembly, "registry.reservation:reg_main/000001")
    assert finding.source_kind is RES and finding.status is SourceStatus.RESOLVED and finding.overlap is OverlapVerdict.OVERLAPS
    assert (finding.campaign_id, finding.content_hash) == ("camp_a", h("record-1"))
    assert (finding.window_start_utc, finding.window_end_utc) == ("2026-01-15T00:00:00.000000Z", "2026-02-15T00:00:00.000000Z")


@pytest.mark.parametrize("kind, name", [(RES, "reservation"), (ADM, "admission")])
@pytest.mark.parametrize("window", [AFTER, TOUCHING])
def test_foreign_non_overlapping_reservation_or_admission_is_counted_but_not_listed(tmp_path, kind, name, window):
    """Règle de listabilité (23.28) : une RESERVATION/ADMISSION étrangère RESOLVED qui ne recoupe pas W n'entre que dans la comptabilité."""
    assembly = assemble(interpret(tmp_path), reg=registry([rec(1, kind, "camp_a", window)]))
    assert not any(i.startswith("registry.") for i in ids(assembly))
    assert assembly.inventory.trial_accounting.campaigns == 1


def test_foreign_non_overlapping_consumption_is_listed_and_changes_inventory_id(tmp_path):
    """23.27.4 : une CONSUMPTION étrangère est une exposition même sans recouvrement ; elle modifie `inventory_id`."""
    interpretation = interpret(tmp_path)
    base = assemble(interpretation)
    consumed = assemble(interpretation, reg=registry([rec(1, CONS, "camp_a", AFTER)]))
    finding = by_id(consumed, "registry.consumption:reg_main/000001")
    assert finding.overlap is OverlapVerdict.NO_OVERLAP and finding.status is SourceStatus.RESOLVED
    assert consumed.inventory_id != base.inventory_id


def test_two_copies_of_the_same_record_content_stay_two_distinct_findings(tmp_path):
    twin = dict(content_hash=h("same"))
    assembly = assemble(interpret(tmp_path), reg=registry([rec(1, CONS, "camp_a", **twin), rec(2, CONS, "camp_a", **twin)]))
    assert [i for i in ids(assembly) if i.startswith("registry.")] == [
        "registry.consumption:reg_main/000001", "registry.consumption:reg_main/000002"]
    assert assembly.inventory.trial_accounting.campaigns == 1               # une seule campagne, jamais deux findings fusionnés


def test_campaigns_counts_distinct_campaign_ids_across_reservation_admission_and_consumption(tmp_path):
    records = [rec(1, RES, "camp_a"), rec(2, ADM, "camp_a"), rec(3, CONS, "camp_a"), rec(4, RES, "camp_b", AFTER),
               rec(5, ADM, "camp_c", AFTER), rec(6, RES, CURRENT)]
    assembly = assemble(interpret(tmp_path), reg=registry(records))
    assert assembly.inventory.trial_accounting.campaigns == 3               # camp_a, camp_b, camp_c ; la campagne courante est exclue
    assert assembly.accounting_provenance.campaigns is b4.CounterProvenance.OBSERVED


def test_own_registry_record_is_listed_so_that_e3a_absorbs_it_and_the_identity_is_unchanged(tmp_path):
    interpretation = interpret(tmp_path)
    context = OwnCampaignContext(CURRENT, OwnRecordStage.RESERVED)
    own = rec(1, RES, CURRENT, window=W)
    with_own = assemble(interpretation, reg=registry([own]), context=context)
    absorbed, remaining, anomalies = partition_own_records(with_own.inventory, context)
    assert [f.source_id for f in absorbed] == ["registry.reservation:reg_main/000001"] and anomalies == ()
    assert with_own.inventory_id == assemble(interpretation).inventory_id    # l'absorption rend l'identité scientifique stable


def test_record_without_window_is_unresolved_listed_and_makes_the_inventory_incomplete(tmp_path):
    assembly = assemble(interpret(tmp_path), reg=registry([rec(1, ADM, "camp_a", window=None)]))
    finding = by_id(assembly, "registry.admission:reg_main/000001")
    assert finding.status is SourceStatus.UNRESOLVED and finding.overlap is OverlapVerdict.UNKNOWN
    assert finding.unresolved_cause.value == "WINDOW_UNKNOWN"
    assert assembly.inventory.complete is False
    assert "REGISTRY_RECORD_UNRESOLVED:registry.admission:reg_main/000001" in assembly.incomplete_reasons


def test_record_without_campaign_id_is_unresolved_and_the_campaign_counter_becomes_partial(tmp_path):
    assembly = assemble(interpret(tmp_path), reg=registry([rec(1, RES, None), rec(2, RES, "camp_a")]))
    finding = by_id(assembly, "registry.reservation:reg_main/000001")
    assert finding.status is SourceStatus.UNRESOLVED and finding.unresolved_cause.value == "INVALID_SCHEMA"
    assert assembly.inventory.trial_accounting.campaigns == 1               # minorant : l'enregistrement sans campagne n'est pas attribuable
    assert assembly.accounting_provenance.campaigns is b4.CounterProvenance.PARTIAL
    assert assembly.inventory.complete is False


def test_unreadable_registry_record_is_a_registry_unreadable_finding_and_never_a_complete_inventory(tmp_path):
    assembly = assemble(interpret(tmp_path), reg=registry([rec(1, RES, "camp_a")], unreadable=["seq-0007"]))
    finding = by_id(assembly, "registry.unreadable:reg_main/seq-0007")
    assert finding.source_kind is SourceKind.REGISTRY_UNREADABLE and finding.status is SourceStatus.UNRESOLVED
    assert finding.unresolved_cause.value == "UNREADABLE" and finding.content_hash is None
    assert assembly.inventory.complete is False and "REGISTRY_UNREADABLE:reg_main/seq-0007" in assembly.incomplete_reasons
    assert assembly.accounting_provenance.campaigns is b4.CounterProvenance.PARTIAL


# ── Tranche 3 : clôtures — `abandoned_reservations` (23.27.5 : sans ClosingRecord terminal, introuvable ⇒ abandonnée) ───

def closing(terminal=(), unreadable=()) -> b4.ClosingView:
    return b4.ClosingView(terminal_campaign_ids=tuple(terminal), unreadable_campaign_ids=tuple(unreadable))


CHAIN = [rec(1, RES, "camp_a"), rec(2, ADM, "camp_a"), rec(3, RES, "camp_b", AFTER), rec(4, RES, CURRENT)]


def test_without_a_closing_view_abandoned_reservations_is_a_placeholder_not_a_verified_zero(tmp_path):
    assembly = assemble(interpret(tmp_path), reg=registry(CHAIN))
    assert assembly.inventory.trial_accounting.abandoned_reservations == 0
    assert assembly.accounting_provenance.abandoned_reservations is b4.CounterProvenance.NOT_OBSERVED
    assert "abandoned_reservations:CLOSING_VIEW_NOT_PROVIDED" in assembly.accounting_provenance.reasons


def test_every_counted_campaign_closed_is_a_verified_zero(tmp_path):
    accounting = b4.AccountingViews(closing=closing(terminal=["camp_a", "camp_b"]))
    assembly = assemble(interpret(tmp_path), reg=registry(CHAIN), accounting=accounting)
    assert assembly.inventory.trial_accounting.abandoned_reservations == 0
    assert assembly.accounting_provenance.abandoned_reservations is b4.CounterProvenance.OBSERVED


def test_a_campaign_without_closing_record_is_abandoned_and_the_counter_is_an_upper_bound(tmp_path):
    accounting = b4.AccountingViews(closing=closing(terminal=["camp_a"]))             # camp_b : ClosingRecord introuvable
    assembly = assemble(interpret(tmp_path), reg=registry(CHAIN), accounting=accounting)
    assert assembly.inventory.trial_accounting.abandoned_reservations == 1
    assert assembly.accounting_provenance.abandoned_reservations is b4.CounterProvenance.PARTIAL
    assert "abandoned_reservations:CLOSING_NOT_FOUND:camp_b" in assembly.accounting_provenance.reasons


def test_an_unreadable_closing_record_counts_as_abandoned_and_is_reported_as_such(tmp_path):
    accounting = b4.AccountingViews(closing=closing(terminal=["camp_a"], unreadable=["camp_b"]))
    assembly = assemble(interpret(tmp_path), reg=registry(CHAIN), accounting=accounting)
    assert assembly.inventory.trial_accounting.abandoned_reservations == 1
    assert assembly.accounting_provenance.abandoned_reservations is b4.CounterProvenance.PARTIAL
    assert "abandoned_reservations:CLOSING_UNREADABLE:camp_b" in assembly.accounting_provenance.reasons


def test_the_current_campaign_is_never_abandoned_and_a_campaign_with_three_records_counts_once(tmp_path):
    records = [rec(1, RES, "camp_a"), rec(2, ADM, "camp_a"), rec(3, CONS, "camp_a"), rec(4, RES, CURRENT)]
    accounting = b4.AccountingViews(closing=closing())                                  # aucune clôture lisible
    assembly = assemble(interpret(tmp_path), reg=registry(records), accounting=accounting)
    assert assembly.inventory.trial_accounting.abandoned_reservations == 1             # camp_a une fois ; la campagne courante exclue


def test_a_closing_record_of_a_campaign_outside_the_chain_is_ignored(tmp_path):
    accounting = b4.AccountingViews(closing=closing(terminal=["camp_a", "camp_b", "camp_elsewhere"]))
    assembly = assemble(interpret(tmp_path), reg=registry(CHAIN), accounting=accounting)
    assert assembly.inventory.trial_accounting.abandoned_reservations == 0
    assert assembly.inventory.trial_accounting.campaigns == 2


def test_a_partial_campaign_set_makes_the_abandoned_counter_partial_even_if_every_closing_is_terminal(tmp_path):
    accounting = b4.AccountingViews(closing=closing(terminal=["camp_a"]))
    assembly = assemble(interpret(tmp_path), reg=registry([rec(1, RES, "camp_a")], unreadable=["seq-0009"]), accounting=accounting)
    assert assembly.inventory.trial_accounting.abandoned_reservations == 0
    assert assembly.accounting_provenance.abandoned_reservations is b4.CounterProvenance.PARTIAL
    assert "abandoned_reservations:CAMPAIGN_SET_PARTIAL" in assembly.accounting_provenance.reasons


def test_closing_view_rejects_an_ambiguous_campaign_and_wrong_types():
    with pytest.raises(ValueError):
        closing(terminal=["camp_a"], unreadable=["camp_a"])                              # terminale ET illisible : ambigu
    with pytest.raises(ValueError):
        closing(terminal=["camp_a", "camp_a"])
    with pytest.raises(TypeError):
        b4.ClosingView(terminal_campaign_ids=["camp_a"], unreadable_campaign_ids=())      # liste : collection mutable refusée


# ── Tranche 4 : ingestion échouée, engagements nuls (sans restriction aux campagnes de la chaîne), campagne courante, final ─

def items(*pairs, unreadable=0) -> b4.TrialItemsView:
    return b4.TrialItemsView(items=tuple(b4.TrialItem(item_id, campaign) for item_id, campaign in pairs), unreadable_count=unreadable)


@pytest.mark.parametrize("field, counter", [("failed_ingestion", "failed_ingestion_attempts"), ("void_commitments", "void_commitments")])
def test_items_are_counted_without_restriction_to_chain_campaigns_even_before_any_reservation(tmp_path, field, counter):
    accounting = b4.AccountingViews(**{field: items(("i1", "camp_never_reserved"), ("i2", None), ("i3", "camp_x"))})
    assembly = assemble(interpret(tmp_path), reg=registry([]), accounting=accounting)             # registre vide : aucune RESERVATION
    assert getattr(assembly.inventory.trial_accounting, counter) == 3
    assert getattr(assembly.accounting_provenance, counter) is b4.CounterProvenance.OBSERVED


@pytest.mark.parametrize("field, counter", [("failed_ingestion", "failed_ingestion_attempts"), ("void_commitments", "void_commitments")])
def test_items_are_deduplicated_and_the_current_campaign_is_excluded_from_the_pre_admission_count(tmp_path, field, counter):
    accounting = b4.AccountingViews(**{field: items(("i1", "camp_a"), ("i1", "camp_a"), ("i2", CURRENT), ("i3", None))})
    assembly = assemble(interpret(tmp_path), accounting=accounting)
    assert getattr(assembly.inventory.trial_accounting, counter) == 2                           # i1 (une fois) et i3 ; i2 est courante


@pytest.mark.parametrize("field, counter", [("failed_ingestion", "failed_ingestion_attempts"), ("void_commitments", "void_commitments")])
def test_an_empty_view_is_a_verified_zero_and_a_missing_view_is_only_a_placeholder(tmp_path, field, counter):
    interpretation = interpret(tmp_path)
    verified = assemble(interpretation, accounting=b4.AccountingViews(**{field: items()}))
    missing = assemble(interpretation)
    assert getattr(verified.inventory.trial_accounting, counter) == getattr(missing.inventory.trial_accounting, counter) == 0
    assert getattr(verified.accounting_provenance, counter) is b4.CounterProvenance.OBSERVED
    assert getattr(missing.accounting_provenance, counter) is b4.CounterProvenance.NOT_OBSERVED
    assert f"{counter}:VIEW_NOT_PROVIDED" in missing.accounting_provenance.reasons


@pytest.mark.parametrize("field, counter", [("failed_ingestion", "failed_ingestion_attempts"), ("void_commitments", "void_commitments")])
def test_unreadable_items_make_the_counter_a_lower_bound_never_exact(tmp_path, field, counter):
    assembly = assemble(interpret(tmp_path), accounting=b4.AccountingViews(**{field: items(("i1", "camp_a"), unreadable=2)}))
    assert getattr(assembly.inventory.trial_accounting, counter) == 1
    assert getattr(assembly.accounting_provenance, counter) is b4.CounterProvenance.PARTIAL
    assert f"{counter}:UNREADABLE_ITEMS:2" in assembly.accounting_provenance.reasons


def test_the_accounting_helper_matches_the_assembly_and_never_includes_the_current_campaign(tmp_path):
    """La comptabilité publique est celle du A0 avant admission (23.27.5) ; le calcul final du `ClosingRecord` est une tranche ultérieure."""
    records = [rec(1, RES, "camp_a"), rec(2, RES, CURRENT)]
    views = b4.AccountingViews(closing=closing(terminal=["camp_a"]), failed_ingestion=items(("i1", "camp_a"), ("i2", CURRENT)))
    accounting, provenance = b4.compute_trial_accounting(registry(records), views, current_campaign_id=CURRENT)
    assembly = assemble(interpret(tmp_path), reg=registry(records), accounting=views)
    assert (accounting.campaigns, accounting.failed_ingestion_attempts) == (1, 1)
    assert accounting == assembly.inventory.trial_accounting and provenance == assembly.accounting_provenance


@pytest.mark.parametrize("build, error", [
    (lambda: b4.TrialItemsView(items=[b4.TrialItem("i1", None)], unreadable_count=0), TypeError),
    (lambda: b4.TrialItemsView(items=(), unreadable_count=-1), ValueError),
    (lambda: b4.TrialItemsView(items=(), unreadable_count="1"), TypeError),
    (lambda: b4.TrialItem("", None), ValueError),
    (lambda: b4.TrialItem(3, None), TypeError),
    (lambda: b4.AccountingViews(failed_ingestion="not a view"), TypeError),
])
def test_item_views_reject_invalid_shapes(build, error):
    with pytest.raises(error):
        build()


# ── Tranche 5 : `research_runs` et `strategies` — identités distinctes sur les campagnes de la chaîne et les campagnes V1 OOS ─

def trials(*campaigns, unreadable=0) -> b4.CampaignTrialsView:
    return b4.CampaignTrialsView(
        campaigns=tuple(b4.CampaignTrials(campaign_id, tuple(runs), tuple(strategies)) for campaign_id, runs, strategies in campaigns),
        unreadable_count=unreadable)


TWO_CAMPAIGNS = [rec(1, RES, "camp_a"), rec(2, ADM, "camp_b", AFTER)]
CHAIN_TRIALS = trials(("camp_a", ["r1", "r2"], ["s1"]), ("camp_b", ["r2", "r3"], ["s1", "s2"]))     # r2 et s1 partagés
V1_TRIALS = trials(("v1_x", ["r4"], ["s3"]))


def test_without_any_trials_view_runs_and_strategies_are_placeholders(tmp_path):
    assembly = assemble(interpret(tmp_path), reg=registry(TWO_CAMPAIGNS))
    assert (assembly.inventory.trial_accounting.research_runs, assembly.inventory.trial_accounting.strategies) == (0, 0)
    assert assembly.accounting_provenance.research_runs is b4.CounterProvenance.NOT_OBSERVED
    assert assembly.accounting_provenance.strategies is b4.CounterProvenance.NOT_OBSERVED
    assert "trials:VIEW_NOT_PROVIDED" in assembly.accounting_provenance.reasons


def test_identities_are_deduplicated_across_campaigns_and_v1_oos_campaigns(tmp_path):
    accounting = b4.AccountingViews(chain_trials=CHAIN_TRIALS, v1_oos_trials=V1_TRIALS)
    assembly = assemble(interpret(tmp_path), reg=registry(TWO_CAMPAIGNS), accounting=accounting)
    accounted = assembly.inventory.trial_accounting
    assert (accounted.research_runs, accounted.strategies, accounted.campaigns) == (4, 3, 2)   # r1..r4 ; s1..s3
    assert assembly.accounting_provenance.research_runs is b4.CounterProvenance.OBSERVED
    assert assembly.accounting_provenance.strategies is b4.CounterProvenance.OBSERVED


def test_the_current_campaign_trials_are_excluded_before_admission_and_not_required_for_coverage(tmp_path):
    chain = trials(("camp_a", ["r1"], ["s1"]), (CURRENT, ["r9"], ["s9"]))
    accounting = b4.AccountingViews(chain_trials=chain, v1_oos_trials=trials())
    assembly = assemble(interpret(tmp_path), reg=registry([rec(1, RES, "camp_a"), rec(2, RES, CURRENT)]), accounting=accounting)
    assert (assembly.inventory.trial_accounting.research_runs, assembly.inventory.trial_accounting.strategies) == (1, 1)
    assert assembly.accounting_provenance.research_runs is b4.CounterProvenance.OBSERVED


def test_trials_of_a_campaign_unknown_to_the_chain_are_counted_but_the_counters_become_partial(tmp_path):
    """Une vue qui cite une campagne absente de la chaîne est incohérente avec le registre : on compte (conservateur), mais jamais `OBSERVED`."""
    chain = trials(("camp_a", ["r1"], ["s1"]), ("camp_stranger", ["r2"], ["s2"]))
    accounting = b4.AccountingViews(chain_trials=chain, v1_oos_trials=trials())
    assembly = assemble(interpret(tmp_path), reg=registry([rec(1, RES, "camp_a")]), accounting=accounting)
    assert (assembly.inventory.trial_accounting.research_runs, assembly.inventory.trial_accounting.strategies) == (2, 2)
    assert assembly.accounting_provenance.research_runs is b4.CounterProvenance.PARTIAL
    assert "trials:CHAIN_TRIALS_FOR_UNKNOWN_CAMPAIGN:camp_stranger" in assembly.accounting_provenance.reasons


def test_a_chain_campaign_without_trials_makes_runs_and_strategies_partial(tmp_path):
    accounting = b4.AccountingViews(chain_trials=trials(("camp_a", ["r1"], ["s1"])), v1_oos_trials=trials())
    assembly = assemble(interpret(tmp_path), reg=registry(TWO_CAMPAIGNS), accounting=accounting)       # camp_b sans entrée
    assert (assembly.inventory.trial_accounting.research_runs, assembly.inventory.trial_accounting.strategies) == (1, 1)
    for name in ("research_runs", "strategies"):
        assert getattr(assembly.accounting_provenance, name) is b4.CounterProvenance.PARTIAL
    assert "trials:CHAIN_CAMPAIGN_WITHOUT_TRIALS:camp_b" in assembly.accounting_provenance.reasons


@pytest.mark.parametrize("views, reason", [
    (dict(chain_trials=CHAIN_TRIALS), "trials:V1_OOS_TRIALS_NOT_PROVIDED"),
    (dict(v1_oos_trials=V1_TRIALS), "trials:CHAIN_TRIALS_NOT_PROVIDED"),
])
def test_one_missing_trials_view_makes_the_counters_partial_lower_bounds(tmp_path, views, reason):
    assembly = assemble(interpret(tmp_path), reg=registry(TWO_CAMPAIGNS), accounting=b4.AccountingViews(**views))
    assert assembly.accounting_provenance.research_runs is b4.CounterProvenance.PARTIAL
    assert assembly.inventory.trial_accounting.research_runs > 0
    assert reason in assembly.accounting_provenance.reasons


def test_unreadable_trial_campaigns_make_the_counters_partial(tmp_path):
    accounting = b4.AccountingViews(chain_trials=trials(("camp_a", ["r1"], ["s1"]), ("camp_b", ["r2"], ["s2"]), unreadable=1),
                                    v1_oos_trials=trials())
    assembly = assemble(interpret(tmp_path), reg=registry(TWO_CAMPAIGNS), accounting=accounting)
    assert assembly.accounting_provenance.strategies is b4.CounterProvenance.PARTIAL
    assert "trials:UNREADABLE_CAMPAIGNS:1" in assembly.accounting_provenance.reasons


def test_a_partial_chain_makes_runs_and_strategies_partial_even_with_full_trial_views(tmp_path):
    accounting = b4.AccountingViews(chain_trials=CHAIN_TRIALS, v1_oos_trials=V1_TRIALS)
    assembly = assemble(interpret(tmp_path), reg=registry(TWO_CAMPAIGNS, unreadable=["seq-0003"]), accounting=accounting)
    assert assembly.accounting_provenance.research_runs is b4.CounterProvenance.PARTIAL
    assert "trials:CAMPAIGN_SET_PARTIAL" in assembly.accounting_provenance.reasons


def test_trial_views_reject_ambiguous_or_invalid_shapes():
    with pytest.raises(ValueError):
        trials(("camp_a", ["r1"], ["s1"]), ("camp_a", ["r2"], ["s2"]))                      # même campagne deux fois : ambigu
    with pytest.raises(ValueError):
        b4.CampaignTrials("camp_a", ("r1", "r1"), ())                                        # identité dupliquée dans une campagne
    with pytest.raises(TypeError):
        b4.CampaignTrials("camp_a", ["r1"], ())
    with pytest.raises(ValueError):
        b4.CampaignTrialsView(campaigns=(), unreadable_count=-1)
    with pytest.raises(TypeError):
        b4.AccountingViews(chain_trials=items())                                             # mauvais type de vue


# ── Tranche 6 : propagation des anomalies et de l'incomplétude de B3, racines dérivées, erreurs d'appel ──────────────────

import dataclasses  # noqa: E402

from gate_v_final_holdout_protocol import (  # noqa: E402
    compute_overlap_projection_hash,
    compute_static_sources_digest,
    partition_own_records,
)


def interpret_two(tmp_path: Path, *, second_files=()):
    """Deux racines `results` (labels `res` et `derived`) : la seconde peut recevoir une entrée inconnue (anomalie B3)."""
    first, second = tmp_path / "results", tmp_path / "derived"
    make_job(first, "job_1", "2026-02-01T00:00:00+00:00", "2026-02-10T00:00:00+00:00")
    make_job(second, "job_2", "2026-02-01T00:00:00+00:00", "2026-02-10T00:00:00+00:00")
    for name in second_files:
        (second / name).write_bytes(b"{}")
    roots = (b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("res", str(first))),
             b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("derived", str(second))))
    return b3.interpret_audit_roots(roots, LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])


def test_b3_incompleteness_and_anomalies_are_preserved_verbatim_and_never_erased(tmp_path):
    interpretation = interpret_two(tmp_path, second_files=("stray.json",))
    assert interpretation.complete is False and interpretation.incomplete_reasons
    assembly = assemble(interpretation, reg=registry([rec(1, RES, "camp_a")]))
    assert assembly.inventory.complete is False
    assert set(interpretation.incomplete_reasons) <= set(assembly.incomplete_reasons)
    assert all(finding in assembly.inventory.findings for finding in interpretation.findings)      # chaque finding de B3, inchangé
    assert any(f.source_kind is SourceKind.UNKNOWN_SOURCE for f in assembly.inventory.findings)


def test_b4_never_widens_completeness_whatever_the_accounting_and_the_registry(tmp_path):
    incomplete = interpret_two(tmp_path, second_files=("stray.json",))
    full = b4.AccountingViews(closing=closing(), failed_ingestion=items(), void_commitments=items(),
                              chain_trials=trials(), v1_oos_trials=trials())
    assert assemble(incomplete, accounting=full).inventory.complete is False
    complete = interpret(tmp_path / "other")
    assert complete.complete is True
    assert assemble(complete).inventory.complete is True and assemble(complete, accounting=full).inventory.complete is True


def test_registry_incompleteness_is_added_to_the_b3_reasons_sorted_and_without_duplicates(tmp_path):
    interpretation = interpret_two(tmp_path, second_files=("stray.json",))
    assembly = assemble(interpretation, reg=registry([rec(1, ADM, "camp_a", window=None)], unreadable=["seq-9"]))
    reasons = assembly.incomplete_reasons
    assert list(reasons) == sorted(set(reasons))
    assert "REGISTRY_UNREADABLE:reg_main/seq-9" in reasons and "REGISTRY_RECORD_UNRESOLVED:registry.admission:reg_main/000001" in reasons
    assert set(interpretation.incomplete_reasons) <= set(reasons)


def test_derived_roots_are_read_sources_but_never_scanned_roots(tmp_path):
    interpretation = interpret_two(tmp_path)
    assembly = assemble(interpretation, derived=("derived",))
    assert assembly.inventory.scanned_roots == ("res",)
    assert len(assembly.inventory.findings) == 2                         # le job de la racine dérivée reste une source lue
    assert assemble(interpretation).inventory.scanned_roots == ("derived", "res")


def test_declaring_a_root_as_derived_changes_the_scanned_roots_and_so_the_scientific_identity(tmp_path):
    interpretation = interpret_two(tmp_path)
    assert assemble(interpretation, derived=("derived",)).inventory_id != assemble(interpretation).inventory_id


def test_an_unknown_derived_label_is_refused(tmp_path):
    with pytest.raises(ValueError):
        assemble(interpret_two(tmp_path), derived=("nope",))


def test_an_inventory_without_any_static_root_is_never_complete_and_does_not_raise(tmp_path):
    interpretation = interpret(tmp_path)
    assert interpretation.complete is True
    assembly = assemble(interpretation, derived=("res",))
    assert assembly.inventory.scanned_roots == () and assembly.inventory.complete is False
    assert "NO_STATIC_ROOT" in assembly.incomplete_reasons


@pytest.mark.parametrize("kwargs", [
    dict(registry=None), dict(accounting="views"), dict(own_context="ctx"), dict(derived_root_labels=["res"]),
])
def test_call_errors_raise_type_error(tmp_path, kwargs):
    base = dict(registry=registry(), accounting=b4.AccountingViews(), own_context=STAGE0, derived_root_labels=())
    base.update(kwargs)
    with pytest.raises(TypeError):
        b4.assemble_exposure_inventory(interpret(tmp_path), **base)


def test_the_interpretation_must_be_a_b3_source_interpretation(tmp_path):
    with pytest.raises(TypeError):
        b4.assemble_exposure_inventory("not an interpretation", registry=registry(), accounting=b4.AccountingViews(),
                                       own_context=STAGE0)


def test_hooks_used_is_carried_from_the_interpretation_in_both_directions(tmp_path):
    """Un scan produit avec des `ScanHooks` n'a aucune autorité de production : E3-J doit le voir à travers l'assemblage."""
    from gate_v_exposure_scan import ScanHooks
    results = tmp_path / "results"
    make_job(results, "job_1", "2026-02-01T00:00:00+00:00", "2026-02-10T00:00:00+00:00")
    root = (b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("res", str(results))),)
    plain = b3.interpret_audit_roots(root, LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    hooked = b3.interpret_audit_roots(root, LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1],
                                      hooks=ScanHooks(after_first_pass=lambda attempt: None))
    assert assemble(plain).hooks_used is False and assemble(hooked).hooks_used is True


def test_assembly_rejects_an_incoherent_completeness(tmp_path):
    assembly = assemble(interpret(tmp_path))
    with pytest.raises(ValueError):
        dataclasses.replace(assembly, incomplete_reasons=("SOMETHING",))                # complete mais une raison : incohérent


def test_a_duplicate_finding_identifier_is_refused_never_merged(tmp_path):
    interpretation = interpret(tmp_path)
    clash = dataclasses.replace(interpretation.findings[0], source_id="registry.reservation:reg_main/000001",
                                source_kind=SourceKind.JOB_EXECUTION)
    forged = dataclasses.replace(interpretation, findings=(clash,))
    with pytest.raises(ValueError):
        assemble(forged, reg=registry([rec(1, RES, "camp_a")]))


# ── Indépendance de la comptabilité, effet sur `inventory_content_digest`, provenance hors formules E3-A ───────────────

def full_views(**changes) -> b4.AccountingViews:
    values = dict(closing=closing(terminal=["camp_a"]), failed_ingestion=items(("i1", None)), void_commitments=items(("v1", None)),
                  chain_trials=trials(("camp_a", ["r1"], ["s1"])), v1_oos_trials=trials(("v1_x", ["r2"], ["s2"])))
    values.update(changes)
    return b4.AccountingViews(**values)


BASE_RECORDS = [rec(1, RES, "camp_a")]
VARIANTS = {
    "research_runs": dict(accounting=full_views(chain_trials=trials(("camp_a", ["r1", "r1b"], ["s1"])))),
    "strategies": dict(accounting=full_views(chain_trials=trials(("camp_a", ["r1"], ["s1", "s1b"])))),
    "campaigns": dict(records=BASE_RECORDS + [rec(2, RES, "camp_new", AFTER)], accounting=full_views(
        closing=closing(terminal=["camp_a", "camp_new"]), chain_trials=trials(("camp_a", ["r1"], ["s1"]), ("camp_new", [], [])))),
    "abandoned_reservations": dict(accounting=full_views(closing=closing())),
    "failed_ingestion_attempts": dict(accounting=full_views(failed_ingestion=items(("i1", None), ("i2", None)))),
    "void_commitments": dict(accounting=full_views(void_commitments=items(("v1", None), ("v2", None)))),
}


def build_variant(tmp_path, **changes):
    values = dict(records=BASE_RECORDS, accounting=full_views())
    values.update(changes)
    return assemble(interpret(tmp_path), reg=registry(values["records"]), accounting=values["accounting"])


@pytest.mark.parametrize("counter", sorted(VARIANTS))
def test_each_counter_changes_the_content_digest_but_never_the_scientific_identity(tmp_path, counter):
    baseline, changed = build_variant(tmp_path), build_variant(tmp_path, **VARIANTS[counter])
    assert getattr(changed.inventory.trial_accounting, counter) != getattr(baseline.inventory.trial_accounting, counter)
    assert changed.inventory_content_digest != baseline.inventory_content_digest
    assert changed.inventory_id == baseline.inventory_id
    assert changed.inventory.complete is baseline.inventory.complete and changed.inventory.findings == baseline.inventory.findings
    own = baseline.own_context
    assert compute_static_sources_digest(changed.inventory, own) == compute_static_sources_digest(baseline.inventory, own)
    assert compute_overlap_projection_hash(changed.inventory, own) == compute_overlap_projection_hash(baseline.inventory, own)


def test_provenance_alone_never_changes_any_e3a_identity(tmp_path):
    """Même valeur (zéro), provenance différente (zéro vérifié vs espace réservé) : aucune formule d'E3-A ne bouge (23.29.5)."""
    interpretation = interpret(tmp_path)
    verified = assemble(interpretation, accounting=b4.AccountingViews(failed_ingestion=items(), void_commitments=items()))
    placeholder = assemble(interpretation)
    assert verified.inventory.trial_accounting == placeholder.inventory.trial_accounting
    assert verified.accounting_provenance != placeholder.accounting_provenance
    assert (verified.inventory_id, verified.inventory_content_digest) == (placeholder.inventory_id, placeholder.inventory_content_digest)
    context = verified.own_context
    assert compute_static_sources_digest(verified.inventory, context) == compute_static_sources_digest(placeholder.inventory, context)
    assert compute_overlap_projection_hash(verified.inventory, context) == compute_overlap_projection_hash(placeholder.inventory, context)
    assert verified.inventory == placeholder.inventory       # le contenu intégral d'E3-A est identique ; seule la provenance diffère


def test_a_degraded_accounting_source_never_changes_completeness_or_scientific_identity(tmp_path):
    interpretation = interpret(tmp_path)
    degraded = assemble(interpretation, reg=registry(BASE_RECORDS))                                   # aucune source de comptabilité
    full = assemble(interpretation, reg=registry(BASE_RECORDS), accounting=full_views())
    assert degraded.inventory.complete is full.inventory.complete is True
    assert degraded.incomplete_reasons == full.incomplete_reasons == ()
    assert degraded.inventory_id == full.inventory_id and degraded.inventory.findings == full.inventory.findings


def test_non_oos_validations_and_exposure_evidence_are_neither_counted_nor_altered(tmp_path):
    interpretation = interpret(tmp_path)
    notes = (b3.NonOosValidationRun("validation.run:res/x/validation_run.json", "walk_forward", h("w")),
             b3.NonOosValidationRun("validation.run:res/y/validation_run.json", "monte_carlo", h("m")))
    evidence = (b3.ExposureEvidence("job.config:res/x/config_used.json", b3.EvidenceStatus.ABSENCE_NOT_ESTABLISHED),
                b3.ExposureEvidence("job.config:res/y/config_used.json", b3.EvidenceStatus.ESTABLISHED_BY_EXECUTION_WINDOW))
    forged = dataclasses.replace(interpretation, non_oos_validations=notes, exposure_evidence=evidence)
    plain, with_notes = assemble(interpretation), assemble(forged)
    assert with_notes.inventory.trial_accounting == plain.inventory.trial_accounting == TrialAccounting(0, 0, 0, 0, 0, 0)
    assert with_notes.accounting_provenance == plain.accounting_provenance and with_notes.inventory == plain.inventory
    assert with_notes.interpretation.non_oos_validations is notes            # transmis tels quels (B5 les persistera)
    assert with_notes.interpretation.exposure_evidence is evidence


# ── Invariants d'absorption entre étages (23.27.2, 23.27.6) applicables à B4 ──────────────────────────────────────────

OWN = {
    OwnRecordStage.RESERVED: [rec(1, RES, CURRENT, W)],
    OwnRecordStage.ADMITTED: [rec(1, RES, CURRENT, W), rec(2, ADM, CURRENT, W)],
    OwnRecordStage.CONSUMED: [rec(1, RES, CURRENT, W), rec(2, ADM, CURRENT, W), rec(3, CONS, CURRENT, W)],
}
EXPECTED_ANOMALIES = {                       # le Claim vient de B3 (dossier de campagne) : absent de cette fixture au stade CONSUMED
    OwnRecordStage.RESERVED: (), OwnRecordStage.ADMITTED: (), OwnRecordStage.CONSUMED: ("missing:FINAL_HOLDOUT_CLAIM",),
}


def staged(tmp_path, stage, own_records, foreign=()):
    context = OwnCampaignContext(CURRENT, stage)
    return assemble(interpret(tmp_path), reg=registry(list(own_records) + list(foreign)), context=context)


def test_scientific_identities_and_accounting_are_identical_across_stages_without_a_foreign_change(tmp_path):
    foreign = [rec(10, CONS, "camp_a", AFTER), rec(11, ADM, "camp_b", INSIDE)]
    reference = staged(tmp_path, OwnRecordStage.RESERVED, OWN[OwnRecordStage.RESERVED], foreign)
    for stage in (OwnRecordStage.ADMITTED, OwnRecordStage.CONSUMED):
        other = staged(tmp_path, stage, OWN[stage], foreign)
        assert other.inventory_id == reference.inventory_id
        assert other.inventory_content_digest == reference.inventory_content_digest         # la campagne courante est exclue du A0
        assert other.inventory.trial_accounting == reference.inventory.trial_accounting
        assert (compute_static_sources_digest(other.inventory, other.own_context)
                == compute_static_sources_digest(reference.inventory, reference.own_context))
        assert (compute_overlap_projection_hash(other.inventory, other.own_context)
                == compute_overlap_projection_hash(reference.inventory, reference.own_context))


@pytest.mark.parametrize("stage", sorted(OWN, key=lambda s: s.value))
def test_own_records_equal_to_w_are_absorbed_at_their_stage(tmp_path, stage):
    assembly = staged(tmp_path, stage, OWN[stage])
    absorbed, _, anomalies = partition_own_records(assembly.inventory, assembly.own_context)
    assert len(absorbed) == len(OWN[stage]) and anomalies == EXPECTED_ANOMALIES[stage]


def test_an_own_record_that_is_not_absorbable_is_never_hidden_and_changes_the_scientific_identity(tmp_path):
    reference = staged(tmp_path, OwnRecordStage.RESERVED, OWN[OwnRecordStage.RESERVED])
    shifted = staged(tmp_path, OwnRecordStage.RESERVED, [rec(1, RES, CURRENT, INSIDE)])              # fenêtre ≠ W : non absorbée
    absorbed, _, anomalies = partition_own_records(shifted.inventory, shifted.own_context)
    assert absorbed == () and anomalies == ("registry.reservation:reg_main/000001",)
    assert shifted.inventory_id != reference.inventory_id


def test_an_own_record_that_does_not_overlap_w_is_still_listed_and_is_an_anomaly_never_dropped(tmp_path):
    """La règle de listabilité ne vaut que pour les enregistrements ÉTRANGERS : un enregistrement propre hors de `W` reste listé (échec fermé)."""
    assembly = staged(tmp_path, OwnRecordStage.RESERVED, [rec(1, RES, CURRENT, AFTER)])
    finding = by_id(assembly, "registry.reservation:reg_main/000001")
    assert finding.overlap is OverlapVerdict.NO_OVERLAP and finding.campaign_id == CURRENT
    absorbed, _, anomalies = partition_own_records(assembly.inventory, assembly.own_context)
    assert absorbed == () and anomalies == ("registry.reservation:reg_main/000001",)


def test_the_assembly_refuses_to_widen_the_completeness_of_b3(tmp_path):
    interpretation = interpret(tmp_path)
    complete = assemble(interpretation)
    incomplete = dataclasses.replace(interpretation, complete=False, incomplete_reasons=("SOURCE_ANOMALY:res/x",))   # mêmes racines et findings
    assert complete.inventory.complete is True and incomplete.complete is False
    with pytest.raises(ValueError, match="n'élargit jamais"):
        dataclasses.replace(complete, interpretation=incomplete)


def test_a_second_own_reservation_is_listed_never_collapsed_by_the_assembly(tmp_path):
    assembly = staged(tmp_path, OwnRecordStage.RESERVED, [rec(1, RES, CURRENT, W), rec(2, RES, CURRENT, W)])
    absorbed, _, anomalies = partition_own_records(assembly.inventory, assembly.own_context)
    assert absorbed == () and len(anomalies) == 2                          # E3-A refuse l'absorption : deux enregistrements du même type
    assert assembly.inventory.trial_accounting.campaigns == 0              # mais la campagne courante reste exclue du compteur


# ── Tranche 7 : bout en bout avec la classification d'E3-A, validations, déterminisme, provenance exacte, pureté ──────────

import ast  # noqa: E402

from gate_v_final_holdout_protocol import (  # noqa: E402
    ChronologyFacts,
    ClassificationInput,
    DeclarationSet,
    ExposureClass,
    TimeProofFact,
    TimeProofStatus,
    build_exposure_declaration,
    classify_exposure,
)


def classify(assembly):
    declaration = build_exposure_declaration(declaration_seq=1, declarant="Mira", inventory_id=assembly.inventory_id,
                                             prev_declaration_id=None, declared_exposures=(), declared_t_sel_utc=None,
                                             declared_trial_counts=None)
    chronology = ChronologyFacts(None, None, TimeProofFact(TimeProofStatus.ABSENT, None, None), None, None, None, None)
    return classify_exposure(ClassificationInput(assembly.inventory, DeclarationSet((declaration,), True), chronology,
                                                 assembly.own_context))


def test_an_established_b3_exposure_reaches_the_classification_as_retrospective_exposed(tmp_path):
    assembly = assemble(interpret(tmp_path))                              # job exécuté dans W : exposition établie par B3 (P1)
    result = classify(assembly)
    assert result.classification is ExposureClass.RETROSPECTIVE_EXPOSED
    assert result.inventory_id == assembly.inventory_id and result.inventory_content_digest == assembly.inventory_content_digest


def test_an_unestablished_absence_never_becomes_fresh_through_the_assembly(tmp_path):
    interpretation = interpret(tmp_path, job=("2025-06-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00"))   # avant W : absence non établie
    assert interpretation.findings[0].status is SourceStatus.UNRESOLVED
    result = classify(assemble(interpretation, accounting=full_views(), reg=registry(BASE_RECORDS)))
    assert result.classification is ExposureClass.UNDETERMINED            # comptabilité complète ou non : jamais FRESH


def test_an_incomplete_b3_interpretation_makes_the_classification_undetermined_never_fresh(tmp_path):
    results = tmp_path / "results"
    make_job(results, "job_1", "2026-06-01T00:00:00+00:00", "2026-06-10T00:00:00+00:00")
    (results / "job_1" / "config_used.json").unlink()
    interpretation = b3.interpret_audit_roots((b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("res", str(results))),), LIMITS,
                                              holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    assert interpretation.complete is False                               # B3 : ancre manquante → raison MISSING_REQUIRED
    assert classify(assemble(interpretation)).classification is ExposureClass.UNDETERMINED


@pytest.mark.parametrize("changes, error", [
    (dict(seq=0), ValueError), (dict(seq=True), TypeError), (dict(seq="1"), TypeError),
    (dict(kind=SourceKind.JOB_EXECUTION), ValueError), (dict(kind="CONSUMPTION"), TypeError),
    (dict(campaign_id=""), ValueError), (dict(campaign_id=3), TypeError),
    (dict(content_hash="abc"), ValueError), (dict(content_hash="A" * 64), ValueError), (dict(content_hash=5), TypeError),
    (dict(snapshot_id=""), ValueError), (dict(snapshot_id=7), TypeError),
    (dict(window_start_utc=INSIDE[0], window_end_utc=None), ValueError),
    (dict(window_start_utc=INSIDE[1], window_end_utc=INSIDE[0]), ValueError),
    (dict(window_start_utc="2026-01-01T00:00:00", window_end_utc="2026-02-01T00:00:00"), ValueError),     # instant naïf refusé
])
def test_registry_record_fact_rejects_invalid_values_with_the_repo_error_convention(changes, error):
    """Convention du dépôt (E1, E3-A, B3) : `TypeError` pour un type invalide, `ValueError` pour une valeur invalide."""
    values = dict(seq=1, kind=RES, campaign_id="camp_a", content_hash=h("r"), window_start_utc=INSIDE[0], window_end_utc=INSIDE[1])
    values.update(changes)
    with pytest.raises(error):
        b4.RegistryRecordFact(**values)


def test_registry_record_fact_normalizes_its_window():
    fact = rec(1, RES, "camp_a", window=("2026-01-15T02:00:00+02:00", "2026-02-15T00:00:00+00:00"))
    assert fact.window_start_utc == "2026-01-15T00:00:00.000000Z"


@pytest.mark.parametrize("changes, error", [
    (dict(registry_id=""), ValueError), (dict(registry_id=None), TypeError), (dict(head="short"), ValueError),
    (dict(head="G" * 64), ValueError), (dict(head=5), TypeError), (dict(unreadable=["x", "x"]), TypeError),
    (dict(unreadable=[""]), TypeError),
])
def test_registry_view_rejects_invalid_values_with_the_repo_error_convention(changes, error):
    with pytest.raises(error):
        registry(**changes) if "unreadable" not in changes else b4.RegistryView("reg", None, (), changes["unreadable"])


@pytest.mark.parametrize("unreadable, error", [(("x", "x"), ValueError), (("",), ValueError), ((3,), TypeError)])
def test_registry_view_rejects_invalid_unreadable_identifiers(unreadable, error):
    with pytest.raises(error):
        b4.RegistryView("reg", None, (), unreadable)


def test_registry_view_rejects_mutable_collections():
    with pytest.raises(TypeError):
        b4.RegistryView("reg", None, [rec(1, RES, "camp_a")])
    with pytest.raises(TypeError):
        b4.RegistryView("reg", None, (), ["seq-1"])


def test_registry_view_rejects_duplicate_seq_and_foreign_record_types():
    with pytest.raises(ValueError):
        registry([rec(1, RES, "camp_a"), rec(1, ADM, "camp_b")])
    with pytest.raises(TypeError):
        b4.RegistryView("reg", None, ("not a fact",))


def test_an_empty_chain_has_no_chain_head_and_is_a_verified_zero_campaign_count(tmp_path):
    assembly = assemble(interpret(tmp_path), reg=registry(head=None))
    assert assembly.registry_chain_head is None and assembly.inventory.trial_accounting.campaigns == 0
    assert assembly.accounting_provenance.campaigns is b4.CounterProvenance.OBSERVED


def test_the_assembly_is_deterministic_and_independent_of_the_record_order(tmp_path):
    interpretation = interpret(tmp_path)
    records = [rec(1, RES, "camp_a"), rec(2, CONS, "camp_b", AFTER), rec(3, ADM, "camp_c", INSIDE)]
    first = assemble(interpretation, reg=registry(records), accounting=full_views())
    second = assemble(interpretation, reg=registry(list(reversed(records))), accounting=full_views())
    assert first.inventory == second.inventory and first.inventory_id == second.inventory_id
    assert first.accounting_provenance == second.accounting_provenance


def test_all_six_counters_are_observed_only_when_every_source_is_provided_and_read_completely(tmp_path):
    records = [rec(1, RES, "camp_a"), rec(2, ADM, "camp_a"), rec(3, RES, "camp_b", AFTER)]
    accounting = full_views(closing=closing(terminal=["camp_a", "camp_b"]),
                            chain_trials=trials(("camp_a", ["r1"], ["s1"]), ("camp_b", ["r2"], ["s2"])),
                            v1_oos_trials=trials(("v1_x", ["r3"], ["s3"])))
    exact = assemble(interpret(tmp_path), reg=registry(records), accounting=accounting)
    provenance = exact.accounting_provenance
    assert all(getattr(provenance, name) is b4.CounterProvenance.OBSERVED for name in (
        "research_runs", "strategies", "campaigns", "abandoned_reservations", "failed_ingestion_attempts", "void_commitments"))
    assert provenance.reasons == ()
    assert exact.inventory.trial_accounting == TrialAccounting(research_runs=3, strategies=3, campaigns=2, abandoned_reservations=0,
                                                              failed_ingestion_attempts=1, void_commitments=1)


def test_provenance_reasons_are_sorted_and_deterministic(tmp_path):
    interpretation = interpret(tmp_path)
    first = assemble(interpretation, reg=registry([rec(1, RES, None)], unreadable=["b", "a"]))
    second = assemble(interpretation, reg=registry([rec(1, RES, None)], unreadable=["a", "b"]))
    assert first.accounting_provenance.reasons == tuple(sorted(first.accounting_provenance.reasons))
    assert first.accounting_provenance == second.accounting_provenance and first.inventory == second.inventory


def test_the_assembly_and_its_views_are_immutable(tmp_path):
    assembly = assemble(interpret(tmp_path))
    for target, field in ((assembly, "inventory_id"), (assembly.accounting_provenance, "campaigns"),
                          (registry(), "registry_id"), (items(), "unreadable_count"), (trials(), "campaigns")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(target, field, None)


_B4_TREE = ast.parse(Path(b4.__file__).read_text(encoding="utf-8"))


def test_b4_is_pure_and_imports_only_stdlib_b1_b3_and_e3a():
    imported = set()
    for node in ast.walk(_B4_TREE):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "dataclasses", "enum", "typing", "gate_v_exposure_interpreters", "gate_v_exposure_sources",
                        "gate_v_final_holdout_protocol"}, imported


def test_b4_performs_no_io_reads_no_clock_and_keeps_no_global_state():
    called = {node.func.id for node in ast.walk(_B4_TREE) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & {"open", "print", "input", "eval", "exec", "__import__", "ScanObservation", "ExposureScan", "ScannedRoot"}
    attributes = {node.attr for node in ast.walk(_B4_TREE) if isinstance(node, ast.Attribute)}
    assert not attributes & {"read_bytes", "read_text", "scandir", "listdir", "walk", "now", "utcnow", "time", "environ"}
    assert not any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(_B4_TREE))


def test_b4_does_not_read_the_informative_b3_registers_for_counting():
    """`non_oos_validations` et `exposure_evidence` sont transmis, jamais lus par la comptabilité (23.30.4, §51.4)."""
    attributes = {node.attr for node in ast.walk(_B4_TREE) if isinstance(node, ast.Attribute)}
    assert not attributes & {"non_oos_validations", "exposure_evidence", "plans"}


def test_b4_does_not_classify_or_decide_anything():
    names = {node.id for node in ast.walk(_B4_TREE) if isinstance(node, ast.Name)}
    assert not names & {"classify_exposure", "ExposureClass", "admission_refusals", "partition_own_records"}


@pytest.mark.parametrize("field", ["inventory_id", "inventory_content_digest"])
def test_the_assembly_rejects_identities_that_do_not_match_its_inventory(tmp_path, field):
    assembly = assemble(interpret(tmp_path))
    with pytest.raises(ValueError):
        dataclasses.replace(assembly, **{field: "0" * 64})


def test_the_assembly_rejects_a_malformed_identity(tmp_path):
    with pytest.raises(ValueError):
        dataclasses.replace(assemble(interpret(tmp_path)), inventory_id="not hex")


def test_the_assembly_rejects_an_inventory_changed_after_the_fact(tmp_path):
    assembly = assemble(interpret(tmp_path))
    other = assemble(interpret(tmp_path), reg=registry([rec(1, CONS, "camp_a", AFTER)]))
    with pytest.raises(ValueError):
        dataclasses.replace(assembly, inventory=other.inventory)           # identités de l'ancien inventaire : incohérentes


@pytest.mark.parametrize("kwargs, error", [
    (dict(registry=None), TypeError), (dict(accounting="views"), TypeError), (dict(current_campaign_id=None), TypeError),
    (dict(current_campaign_id=""), ValueError),
])
def test_compute_trial_accounting_checks_its_arguments(kwargs, error):
    base = dict(registry=registry(), accounting=b4.AccountingViews(), current_campaign_id=CURRENT)
    base.update(kwargs)
    with pytest.raises(error):
        b4.compute_trial_accounting(base.pop("registry"), base.pop("accounting"), **base)


def test_derived_root_labels_are_recorded_in_the_assembly_so_that_later_slices_can_audit_them(tmp_path):
    """Le caractère « dérivé » d'une racine est une entrée de l'appelant : B4 ne peut pas le prouver, il le consigne (23.30.3)."""
    interpretation = interpret_two(tmp_path)
    assert assemble(interpretation, derived=("derived",)).derived_root_labels == ("derived",)
    assert assemble(interpretation).derived_root_labels == ()


def test_a_wholly_unavailable_registry_is_declared_as_one_unreadable_record_and_is_never_a_complete_inventory(tmp_path):
    assembly = assemble(interpret(tmp_path), reg=registry([], unreadable=["chain"]))
    assert assembly.inventory.complete is False and "REGISTRY_UNREADABLE:reg_main/chain" in assembly.incomplete_reasons
    assert assembly.accounting_provenance.campaigns is b4.CounterProvenance.PARTIAL        # jamais un zéro vérifié
    assert by_id(assembly, "registry.unreadable:reg_main/chain").source_kind is SourceKind.REGISTRY_UNREADABLE


@pytest.mark.parametrize("build, error", [
    (lambda: b4.TrialAccountingProvenance("OBSERVED", *([b4.CounterProvenance.OBSERVED] * 5)), TypeError),
    (lambda: b4.TrialAccountingProvenance(*([b4.CounterProvenance.OBSERVED] * 6), reasons=["x"]), TypeError),
    (lambda: b4.TrialAccountingProvenance(*([b4.CounterProvenance.OBSERVED] * 6), reasons=(3,)), TypeError),
])
def test_trial_accounting_provenance_validates_its_fields(build, error):
    with pytest.raises(error):
        build()


@pytest.mark.parametrize("changes, error", [
    (dict(semantics_version="other"), ValueError), (dict(registry_id=""), ValueError), (dict(registry_id=None), TypeError),
    (dict(registry_chain_head="short"), ValueError), (dict(derived_root_labels=["x"]), TypeError),
    (dict(incomplete_reasons=[]), TypeError),
])
def test_the_assembly_validates_its_own_fields(tmp_path, changes, error):
    with pytest.raises(error):
        dataclasses.replace(assemble(interpret(tmp_path)), **changes)


# ── Clôture contractuelle (D1, D2, D3) ────────────────────────────────────────────────────────────────────────────────

def test_d1_identities_are_opaque_exact_strings_never_normalized_and_distinct_ones_are_never_merged(tmp_path):
    """D1 : B4 déduplique par égalité EXACTE de chaîne. Deux identités qui ne diffèrent que par la casse ou une espace sont deux évaluations
    distinctes ; fusionner silencieusement des évaluations distinctes (ou en déduire une identité d'un nom) est interdit."""
    chain = trials(("camp_a", ["R1", "r1", "R1 "], ["S1", "s1"]), ("camp_b", ["R1"], ["S1", " S1"]))
    accounting = b4.AccountingViews(chain_trials=chain, v1_oos_trials=trials())
    accounted = assemble(interpret(tmp_path), reg=registry(TWO_CAMPAIGNS), accounting=accounting).inventory.trial_accounting
    assert (accounted.research_runs, accounted.strategies) == (3, 3)      # {"R1", "r1", "R1 "} ; {"S1", "s1", " S1"}


def test_d2_the_pre_admission_accounting_excludes_the_current_campaign_whatever_its_stage(tmp_path):
    """Même avec des enregistrements propres, une clôture introuvable et des essais, la campagne courante n'entre dans aucun compteur."""
    accounting = full_views(closing=closing(), chain_trials=trials((CURRENT, ["rc"], ["sc"]), ("camp_a", ["r1"], ["s1"])),
                            failed_ingestion=items(("i1", CURRENT)), void_commitments=items(("v1", CURRENT)))
    for stage, own in OWN.items():
        assembly = assemble(interpret(tmp_path), reg=registry(list(own) + [rec(9, RES, "camp_a")]), accounting=accounting,
                            context=OwnCampaignContext(CURRENT, stage))
        assert assembly.inventory.trial_accounting == TrialAccounting(research_runs=2, strategies=2, campaigns=1,
                                                                     abandoned_reservations=1, failed_ingestion_attempts=0,
                                                                     void_commitments=0), stage


def test_d3_derived_root_labels_are_a_caller_fact_never_inferred_from_the_root_layout(tmp_path):
    """D3 : B4 ne devine pas qu'une racine est dérivée (même si sa disposition est `CAMPAIGN_DIR`) ; E3-J devra vérifier le libellé."""
    campaign = tmp_path / "campaign_x"
    write_json(campaign / "plan.json", {"campaign_id": "campaign_x"})
    results = tmp_path / "results"
    make_job(results, "job_1", "2026-02-01T00:00:00+00:00", "2026-02-10T00:00:00+00:00")
    roots = (b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("res", str(results))),
             b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, AuditRoot("camp", str(campaign))))
    interpretation = b3.interpret_audit_roots(roots, LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    undeclared, declared = assemble(interpretation), assemble(interpretation, derived=("camp",))
    assert undeclared.inventory.scanned_roots == ("camp", "res") and undeclared.derived_root_labels == ()
    assert declared.inventory.scanned_roots == ("res",) and declared.derived_root_labels == ("camp",)


@pytest.mark.parametrize("counter, degraded, verified", [
    ("failed_ingestion_attempts", dict(failed_ingestion=items(unreadable=1)), dict(failed_ingestion=items())),
    ("void_commitments", dict(void_commitments=items(unreadable=1)), dict(void_commitments=items())),
    ("abandoned_reservations", dict(closing=None), dict(closing=closing(terminal=["camp_a"]))),
    ("research_runs", dict(chain_trials=trials()), dict(chain_trials=trials(), v1_oos_trials=trials())),
])
def test_no_provenance_state_ever_changes_a_scientific_identity_complete_or_the_findings(tmp_path, counter, degraded, verified):
    """23.29.5 : à valeur égale, la provenance ne change ni `inventory_id`, ni `complete`, ni les findings, ni les digests."""
    interpretation = interpret(tmp_path)
    baseline = assemble(interpretation, reg=registry(BASE_RECORDS))
    variants = [assemble(interpretation, reg=registry(BASE_RECORDS), accounting=b4.AccountingViews(**views))
                for views in (degraded, verified)]
    states = {getattr(a.accounting_provenance, counter) for a in [baseline] + variants}
    assert len(states) >= 2                                              # la fixture couvre bien plusieurs états de provenance
    for other in variants:
        assert getattr(other.inventory.trial_accounting, counter) == getattr(baseline.inventory.trial_accounting, counter) == 0
        assert other.inventory == baseline.inventory                       # même contenu E3-A : findings, complete, comptabilité
        assert (other.inventory_id, other.inventory_content_digest, other.incomplete_reasons) == (
            baseline.inventory_id, baseline.inventory_content_digest, baseline.incomplete_reasons)


def test_the_module_documents_each_closed_contract_in_its_own_section():
    """D1, D2 et D3 sont lisibles par leurs futurs consommateurs, chacun dans sa section (les marqueurs sont ancrés par section)."""
    titles = ("Contrat de la couche d'adaptation (D1)", "Comptabilité préadmission et `ClosingRecord` (D2)", "Racines dérivées (D3)")
    positions = [b4.__doc__.index(title) for title in titles]
    assert positions == sorted(positions)
    d1, d2, d3 = (b4.__doc__[start:end] for start, end in zip(positions, positions[1:] + [len(b4.__doc__)]))
    for marker in ("research_run_id", "MÊME identité", "aucune défense", "Q-3", "unreadable_count"):
        assert marker in d1, marker
    for marker in ("EXCLUT", "INCLUT", "sans compter sa propre clôture", "REPORTÉ"):
        assert marker in d2, marker
    for marker in ("FAIT DE L'APPELANT", "derived_root_labels", "E3-J"):
        assert marker in d3, marker


def test_d3_the_assembly_rejects_derived_labels_inconsistent_with_the_scanned_roots(tmp_path):
    """Un assemblage construit à la main reste cohérent avec les racines de B3 : labels dérivés connus et `scanned_roots` = racines - dérivées."""
    assembly = assemble(interpret_two(tmp_path), derived=("derived",))
    with pytest.raises(ValueError):
        dataclasses.replace(assembly, derived_root_labels=("nope",))
    with pytest.raises(ValueError):
        dataclasses.replace(assembly, derived_root_labels=())                  # scanned_roots ne contient pas la racine « derived »


def test_the_public_surface_is_the_documented_one():
    public = {name for name, obj in vars(b4).items()
              if not name.startswith("_") and getattr(obj, "__module__", None) == b4.__name__ and (callable(obj) or isinstance(obj, type))}
    assert public == {"CounterProvenance", "RegistryRecordFact", "RegistryView", "ClosingView", "TrialItem", "TrialItemsView",
                      "CampaignTrials", "CampaignTrialsView", "AccountingViews", "TrialAccountingProvenance",
                      "ExposureInventoryAssembly", "compute_trial_accounting", "assemble_exposure_inventory"}
