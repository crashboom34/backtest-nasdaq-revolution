"""
tests/test_gate_v_final_holdout_protocol.py — AF-V-07 Slice E3-A : modèles purs et classification d'exposition.

Contrat normatif : ADR 0025 Décision 23, addendum 23.27 et contrat de référence 23.28. Tests SYNTHÉTIQUES : aucune
donnée de marché, aucun Claim, aucun fichier, aucun registre, aucune horloge. Les vecteurs SHA-256 sont calculés
dans le test par un calcul INDÉPENDANT (hashlib + json) et en littéraux, jamais par les fonctions testées.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gate_v_final_holdout_protocol as proto

_MODULE_PATH = Path(proto.__file__)

# ============================================================================================
# Tranche 1 — énumérations fermées et instants UTC normalisés
# ============================================================================================


def _values(enum_cls):
    return [member.value for member in enum_cls]


def test_enumerations_are_closed_sets_with_the_documented_counts():
    assert _values(proto.ExposureClass) == [
        "FRESH_UNEXPOSED_DECLARED", "RETROSPECTIVE_EXPOSED", "UNDETERMINED",
    ]
    assert _values(proto.ChronologyLevel) == ["PROSPECTIVE_ANCHORED", "UNSEEN_HISTORICAL", "NOT_APPLICABLE"]
    assert _values(proto.OverlapVerdict) == ["OVERLAPS", "NO_OVERLAP", "UNKNOWN"]
    assert _values(proto.SourceStatus) == ["RESOLVED", "UNRESOLVED"]
    assert _values(proto.ConditionStatus) == ["MET", "NOT_MET", "UNVERIFIED"]
    assert _values(proto.TimeProofStatus) == ["VALID", "INVALID", "UNVERIFIABLE", "ABSENT"]
    assert _values(proto.OwnRecordStage) == ["NO_OWN_RECORDS", "RESERVED", "ADMITTED", "CLAIMED", "CONSUMED"]
    assert _values(proto.UnresolvedCause) == [
        "UNREADABLE", "INVALID_SCHEMA", "UNKNOWN_SCHEMA_VERSION", "WINDOW_UNKNOWN", "TIMEZONE_UNKNOWN",
        "PLAN_UNRESOLVED", "UNKNOWN_SOURCE_TYPE",
    ]
    assert _values(proto.AdmissionRefusal) == [
        "CLASS_RETROSPECTIVE_EXPOSED", "CLASS_UNDETERMINED", "LEVEL_NOT_PROSPECTIVE_ANCHORED",
        "OVERLAPPING_REGISTRATION",
    ]


def test_source_kind_has_twelve_values_split_8_2_2():
    exposing = {
        "HOLDOUT_ACCESS_EVENT", "VALIDATION_RUN_OOS", "JOB_EXECUTION", "V1_CAMPAIGN_OOS",
        "FINAL_HOLDOUT_CLAIM", "CONSUMPTION", "READ_INTENT", "DECLARED_UNRECORDED_WORK",
    }
    registry = {"REGISTRY_RESERVATION", "REGISTRY_ADMISSION"}
    unknown = {"UNKNOWN_SOURCE", "REGISTRY_UNREADABLE"}
    assert len(proto.SourceKind) == 12
    assert {k.value for k in proto.SourceKind} == exposing | registry | unknown
    assert {k.value for k in proto.SourceKind if k.exposes_data} == exposing
    assert {k.value for k in proto.SourceKind if k.capability_unknown} == unknown
    assert not any(k.exposes_data and k.capability_unknown for k in proto.SourceKind)


def test_reason_code_has_32_values_7_class_level_and_25_condition_level_in_documented_order():
    values = _values(proto.ReasonCode)
    assert len(values) == 32
    assert values[:7] == [
        "EXPOSURE_ESTABLISHED_INVENTORY", "EXPOSURE_ESTABLISHED_DECLARED", "UNRESOLVED_SOURCE",
        "INVENTORY_INCOMPLETE", "T_SEL_LOWERING_IGNORED", "OVERLAPPING_REGISTRATION", "OWN_REGISTRATION_ANOMALY",
    ]
    by_condition = {
        name: [v for v in values[7:] if v.startswith(name + "_")] for name in ("F1", "F2", "F3", "F4", "F5", "F6")
    }
    assert {name: len(codes) for name, codes in by_condition.items()} == {
        "F1": 4, "F2": 6, "F3": 2, "F4": 9, "F5": 3, "F6": 1,
    }
    assert sum(len(codes) for codes in by_condition.values()) == 25
    assert values[7:] == [c for name in ("F1", "F2", "F3", "F4", "F5", "F6") for c in by_condition[name]]
    assert by_condition["F1"] == ["F1_EXPOSURE_ESTABLISHED", "F1_SOURCES_UNRESOLVED", "F1_INVENTORY_INCOMPLETE", "F1_OWN_ANOMALY"]
    assert by_condition["F4"] == [
        "F4_RESERVATION_UNKNOWN", "F4_RESERVATION_NOT_DURABLE", "F4_PROOF_ABSENT", "F4_PROOF_UNVERIFIABLE",
        "F4_PROOF_INVALID", "F4_PROOF_NOT_OWN_RESERVATION", "F4_MARGIN_MISSING", "F4_MARGIN_NOT_POSITIVE",
        "F4_ANCHORED_TOO_LATE",
    ]


def test_there_are_exactly_eleven_enumerations_in_the_module():
    import enum

    enums = [
        obj for obj in vars(proto).values()
        if isinstance(obj, type) and issubclass(obj, enum.Enum) and obj.__module__ == proto.__name__
    ]
    assert len(enums) == 11


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-11-02T00:00:00Z", "2026-11-02T00:00:00.000000Z"),
        ("2026-11-02T00:00:00.5Z", "2026-11-02T00:00:00.500000Z"),
        ("2026-11-02T00:00:00.123456Z", "2026-11-02T00:00:00.123456Z"),
        ("2026-11-02T02:00:00+02:00", "2026-11-02T00:00:00.000000Z"),
        ("2026-11-01T22:30:00-01:30", "2026-11-02T00:00:00.000000Z"),
        ("2026-11-02T00:00:00+00:00", "2026-11-02T00:00:00.000000Z"),
        ("2026-12-31T23:59:59.999999Z", "2026-12-31T23:59:59.999999Z"),
        ("2026-01-01T01:00:00+05:30", "2025-12-31T19:30:00.000000Z"),
    ],
)
def test_normalize_utc_instant_converts_offsets_to_fixed_six_digit_utc(raw, expected):
    assert proto.normalize_utc_instant(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-11-02T23:59:59.999999-23:59", "2026-11-03T23:58:59.999999Z"),   # offset extrême négatif : jour suivant
        ("2026-11-02T00:00:00+23:59", "2026-11-01T00:01:00.000000Z"),          # offset extrême positif : jour précédent
        ("2028-02-29T12:00:00Z", "2028-02-29T12:00:00.000000Z"),               # année bissextile
        ("2028-02-29T23:30:00-01:00", "2028-03-01T00:30:00.000000Z"),          # passage 29 février -> 1er mars
        ("2026-12-31T23:30:00-00:30", "2027-01-01T00:00:00.000000Z"),          # passage d'année
        ("2026-03-29T02:30:00+02:00", "2026-03-29T00:30:00.000000Z"),          # date de bascule DST : offset FIXE, aucune zone
        ("2026-10-25T02:30:00+01:00", "2026-10-25T01:30:00.000000Z"),
    ],
)
def test_normalize_utc_instant_handles_extreme_offsets_leap_days_and_fixed_offset_dst_dates(raw, expected):
    assert proto.normalize_utc_instant(raw) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "2026-02-29T00:00:00Z",          # 2026 non bissextile
        "2026-11-02T23:59:60Z",          # seconde intercalaire refusée
        "2026-11-02T00:00:00+24:00",     # offset hors plage
        "2026-11-02T00:00:00+00:60",     # minutes d'offset invalides
        "2026-11-02t00:00:00Z",          # 't' minuscule
        "2026-11-02T00:00:00z",          # 'z' minuscule
        "2026-11-02T00:00:00 Z",
        "9999-12-31T23:59:59-01:00",     # débordement au-delà de l'année 9999 après conversion UTC
        "2026-11-02T00:00:00.Z",         # fraction vide
    ],
)
def test_normalize_utc_instant_rejects_calendar_and_offset_edge_cases(bad):
    with pytest.raises(ValueError):
        proto.normalize_utc_instant(bad)


def test_normalize_utc_instant_is_idempotent():
    once = proto.normalize_utc_instant("2026-11-02T02:00:00+02:00")
    assert proto.normalize_utc_instant(once) == once


@pytest.mark.parametrize(
    "bad",
    [
        "2026-11-02T00:00:00",          # naïf
        "2026-11-02",                    # sans heure
        "2026-11-02 00:00:00Z",          # espace au lieu de T
        "2026-11-02T00:00Z",             # sans secondes
        "2026-11-02T00:00:00.1234567Z",  # 7 chiffres de fraction
        "2026-13-02T00:00:00Z",          # mois invalide
        "2026-11-31T00:00:00Z",          # jour invalide
        "2026-11-02T24:00:00Z",          # heure invalide
        "2026-11-02T00:00:00+0200",      # offset sans deux-points
        "٢٠٢٦-١١-٠٢T00:00:00Z",          # chiffres non ASCII
        "",
        " 2026-11-02T00:00:00Z",
        "2026-11-02T00:00:00Z ",
        "0001-01-01T00:00:00+01:00",     # débordement après conversion UTC
    ],
)
def test_normalize_utc_instant_rejects_invalid_or_naive_instants(bad):
    with pytest.raises(ValueError):
        proto.normalize_utc_instant(bad)


@pytest.mark.parametrize("bad", [None, 20261102, b"2026-11-02T00:00:00Z", True, 1.5])
def test_normalize_utc_instant_rejects_non_str_with_type_error(bad):
    with pytest.raises(TypeError):
        proto.normalize_utc_instant(bad)


def test_normalize_utc_instant_rejects_str_subclass():
    class S(str):
        pass

    with pytest.raises(TypeError):
        proto.normalize_utc_instant(S("2026-11-02T00:00:00Z"))


# ============================================================================================
# Fabriques et constantes de test (synthétiques)
# ============================================================================================

WS = "2026-11-02T00:00:00.000000Z"
WE = "2026-12-01T00:00:00.000000Z"
H1 = "1" * 64
H2 = "2" * 64
CURRENT = "campaign_a"
OTHER = "campaign_b"


def finding_kwargs(**overrides):
    base = dict(
        source_id="evt_1",
        source_kind=proto.SourceKind.HOLDOUT_ACCESS_EVENT,
        status=proto.SourceStatus.RESOLVED,
        overlap=proto.OverlapVerdict.NO_OVERLAP,
        content_hash=H1,
        window_start_utc="2026-01-01T00:00:00.000000Z",
        window_end_utc="2026-02-01T00:00:00.000000Z",
        snapshot_id="snap_1",
        campaign_id=None,
        unresolved_cause=None,
    )
    base.update(overrides)
    return base


def make_finding(**overrides):
    return proto.ExposureFinding(**finding_kwargs(**overrides))


def unresolved_kwargs(**overrides):
    base = finding_kwargs(
        status=proto.SourceStatus.UNRESOLVED,
        overlap=proto.OverlapVerdict.UNKNOWN,
        content_hash=None,
        window_start_utc=None,
        window_end_utc=None,
        unresolved_cause=proto.UnresolvedCause.UNREADABLE,
    )
    base.update(overrides)
    return base


def make_unresolved(**overrides):
    return proto.ExposureFinding(**unresolved_kwargs(**overrides))


def reservation(source_id="res_own", campaign=CURRENT, start=WS, end=WE, overlap=proto.OverlapVerdict.OVERLAPS,
                content_hash=H2, status=proto.SourceStatus.RESOLVED):
    return make_finding(
        source_id=source_id, source_kind=proto.SourceKind.REGISTRY_RESERVATION, overlap=overlap,
        content_hash=content_hash, window_start_utc=start, window_end_utc=end, campaign_id=campaign, status=status,
    )


# ============================================================================================
# Tranche 2 — ExposureFinding et TrialAccounting
# ============================================================================================


def test_exposure_finding_has_ten_public_fields_in_the_frozen_order():
    assert tuple(f.name for f in dataclasses.fields(proto.ExposureFinding)) == (
        "source_id", "source_kind", "status", "overlap", "content_hash", "window_start_utc", "window_end_utc",
        "snapshot_id", "campaign_id", "unresolved_cause",
    )


def test_exposure_finding_is_immutable():
    finding = make_finding()
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.source_id = "other"  # type: ignore[misc]


def test_exposure_finding_accepts_a_resolved_non_overlapping_event():
    finding = make_finding()
    assert finding.status is proto.SourceStatus.RESOLVED
    assert finding.unresolved_cause is None


@pytest.mark.parametrize(
    "overrides",
    [
        dict(source_id=""),
        dict(source_id="   "),
        dict(source_id=5),
        dict(source_kind="CONSUMPTION"),
        dict(status="RESOLVED"),
        dict(overlap="OVERLAPS"),
        dict(content_hash="G" * 64),
        dict(content_hash="1" * 63),
        dict(content_hash="A" * 64),           # majuscules refusées
        dict(snapshot_id=""),
        dict(snapshot_id=7),
        dict(campaign_id=""),
        dict(campaign_id=7),
    ],
)
def test_exposure_finding_rejects_malformed_field_values(overrides):
    with pytest.raises(ValueError):
        make_finding(**overrides)


def test_exposure_finding_requires_normalized_instants_in_the_direct_constructor():
    with pytest.raises(ValueError):
        make_finding(window_start_utc="2026-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        make_finding(window_end_utc="2026-02-01T01:00:00.000000+01:00")


def test_exposure_finding_window_bounds_are_both_present_or_both_absent_and_ordered():
    with pytest.raises(ValueError):
        make_unresolved(window_start_utc="2026-01-01T00:00:00.000000Z")
    with pytest.raises(ValueError):
        make_unresolved(window_end_utc="2026-01-01T00:00:00.000000Z")
    with pytest.raises(ValueError):
        make_finding(window_start_utc="2026-02-01T00:00:00.000000Z", window_end_utc="2026-02-01T00:00:00.000000Z")
    with pytest.raises(ValueError):
        make_finding(window_start_utc="2026-03-01T00:00:00.000000Z", window_end_utc="2026-02-01T00:00:00.000000Z")


def test_resolved_finding_requires_known_overlap_complete_window_and_hash():
    with pytest.raises(ValueError):
        make_finding(overlap=proto.OverlapVerdict.UNKNOWN)
    with pytest.raises(ValueError):
        make_finding(window_start_utc=None, window_end_utc=None)
    with pytest.raises(ValueError):
        make_finding(content_hash=None)
    with pytest.raises(ValueError):
        make_finding(unresolved_cause=proto.UnresolvedCause.UNREADABLE)


def test_unresolved_finding_requires_unknown_overlap_and_a_cause():
    assert make_unresolved().overlap is proto.OverlapVerdict.UNKNOWN
    with pytest.raises(ValueError):
        make_unresolved(overlap=proto.OverlapVerdict.NO_OVERLAP)
    with pytest.raises(ValueError):
        make_unresolved(overlap=proto.OverlapVerdict.OVERLAPS)
    with pytest.raises(ValueError):
        make_unresolved(unresolved_cause=None)
    with pytest.raises(ValueError):
        make_unresolved(unresolved_cause="UNREADABLE")


def test_unresolved_finding_may_carry_a_partial_window_hash_or_none():
    assert make_unresolved(content_hash=H1).content_hash == H1
    assert make_unresolved(content_hash=None).content_hash is None


@pytest.mark.parametrize("kind", [proto.SourceKind.UNKNOWN_SOURCE, proto.SourceKind.REGISTRY_UNREADABLE])
def test_unknown_capability_kinds_can_never_be_resolved(kind):
    with pytest.raises(ValueError):
        make_finding(source_kind=kind)
    assert make_unresolved(source_kind=kind).source_kind is kind


def test_declared_unrecorded_work_has_no_content_hash_and_a_declared_prefix_id():
    declared = make_finding(
        source_id="declared:0001:0001", source_kind=proto.SourceKind.DECLARED_UNRECORDED_WORK, content_hash=None,
    )
    assert declared.content_hash is None
    with pytest.raises(ValueError):
        make_finding(
            source_id="declared:0001:0001", source_kind=proto.SourceKind.DECLARED_UNRECORDED_WORK, content_hash=H1,
        )
    with pytest.raises(ValueError):
        make_finding(source_id="evt_1", source_kind=proto.SourceKind.DECLARED_UNRECORDED_WORK, content_hash=None)


def test_reserved_id_prefixes_are_refused():
    with pytest.raises(ValueError):
        make_finding(source_id="declared:0001:0001")  # préfixe réservé aux déclarations
    with pytest.raises(ValueError):
        make_finding(source_id="missing:RESERVATION")
    with pytest.raises(ValueError):
        make_unresolved(source_id="missing:ADMISSION")


@pytest.mark.parametrize(
    "kind",
    [
        proto.SourceKind.REGISTRY_RESERVATION, proto.SourceKind.REGISTRY_ADMISSION,
        proto.SourceKind.FINAL_HOLDOUT_CLAIM, proto.SourceKind.CONSUMPTION, proto.SourceKind.READ_INTENT,
    ],
)
def test_campaign_id_is_required_on_resolved_records_of_the_five_campaign_types(kind):
    with pytest.raises(ValueError):
        make_finding(source_kind=kind, campaign_id=None)
    assert make_finding(source_kind=kind, campaign_id=OTHER).campaign_id == OTHER
    # non résolu : le campaign_id peut être inconnu
    assert make_unresolved(source_kind=kind, campaign_id=None).campaign_id is None


def test_build_exposure_finding_normalizes_instants_and_returns_the_same_object_shape():
    built = proto.build_exposure_finding(
        source_id="evt_1",
        source_kind=proto.SourceKind.HOLDOUT_ACCESS_EVENT,
        status=proto.SourceStatus.RESOLVED,
        overlap=proto.OverlapVerdict.NO_OVERLAP,
        content_hash=H1,
        window_start_utc="2026-01-01T02:00:00+02:00",
        window_end_utc="2026-02-01T00:00:00Z",
        snapshot_id="snap_1",
    )
    assert built == make_finding()
    assert built.window_start_utc == "2026-01-01T00:00:00.000000Z"


def test_build_exposure_finding_rejects_naive_instants():
    with pytest.raises(ValueError):
        proto.build_exposure_finding(
            source_id="evt_1",
            source_kind=proto.SourceKind.HOLDOUT_ACCESS_EVENT,
            status=proto.SourceStatus.RESOLVED,
            overlap=proto.OverlapVerdict.NO_OVERLAP,
            content_hash=H1,
            window_start_utc="2026-01-01T00:00:00",
            window_end_utc="2026-02-01T00:00:00Z",
        )


def test_trial_accounting_has_six_non_negative_integer_counters_in_the_frozen_order():
    assert tuple(f.name for f in dataclasses.fields(proto.TrialAccounting)) == (
        "research_runs", "strategies", "campaigns", "abandoned_reservations", "failed_ingestion_attempts",
        "void_commitments",
    )
    accounting = proto.TrialAccounting(1, 2, 3, 0, 4, 5)
    assert accounting.campaigns == 3
    with pytest.raises(dataclasses.FrozenInstanceError):
        accounting.campaigns = 9  # type: ignore[misc]


@pytest.mark.parametrize("bad", [-1, True, 1.0, "1", None])
def test_trial_accounting_rejects_negative_boolean_or_non_integer_counters(bad):
    for position in range(6):
        values = [0, 0, 0, 0, 0, 0]
        values[position] = bad
        with pytest.raises(ValueError):
            proto.TrialAccounting(*values)


# ============================================================================================
# Tranche 3 — ExposureInventory
# ============================================================================================

ACCOUNTING = proto.TrialAccounting(3, 2, 1, 0, 0, 0)


def inventory_kwargs(**overrides):
    base = dict(
        version=proto.EXPOSURE_INVENTORY_SEMANTICS_VERSION,
        window_start_utc=WS,
        window_end_utc=WE,
        findings=(),
        complete=True,
        scanned_roots=("results",),
        trial_accounting=ACCOUNTING,
    )
    base.update(overrides)
    return base


def make_inventory(*findings, **overrides):
    if findings and "findings" not in overrides:
        overrides["findings"] = tuple(sorted(findings, key=lambda f: f.source_id))
    return proto.ExposureInventory(**inventory_kwargs(**overrides))


def test_exposure_inventory_has_seven_public_fields_in_the_frozen_order():
    assert tuple(f.name for f in dataclasses.fields(proto.ExposureInventory)) == (
        "version", "window_start_utc", "window_end_utc", "findings", "complete", "scanned_roots", "trial_accounting",
    )
    assert proto.EXPOSURE_INVENTORY_SEMANTICS_VERSION == "gate_v_exposure_inventory_v1"


def test_exposure_inventory_is_immutable_and_findings_are_a_tuple():
    inventory = make_inventory(make_finding())
    assert isinstance(inventory.findings, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        inventory.complete = False  # type: ignore[misc]


def test_exposure_inventory_rejects_a_wrong_version_and_non_tuple_collections():
    with pytest.raises(ValueError):
        make_inventory(version="gate_v_exposure_inventory_v0")
    with pytest.raises(ValueError):
        make_inventory(findings=[make_finding()])  # liste refusée : tuple immuable exigé
    with pytest.raises(ValueError):
        make_inventory(scanned_roots=["results"])
    with pytest.raises(ValueError):
        make_inventory(findings=("not a finding",))
    with pytest.raises(ValueError):
        make_inventory(trial_accounting=None)
    with pytest.raises(ValueError):
        make_inventory(complete=1)


def test_exposure_inventory_window_must_be_normalized_and_ordered():
    with pytest.raises(ValueError):
        make_inventory(window_start_utc="2026-11-02T00:00:00Z")
    with pytest.raises(ValueError):
        make_inventory(window_start_utc=WE, window_end_utc=WS)
    with pytest.raises(ValueError):
        make_inventory(window_start_utc=WS, window_end_utc=WS)


def test_complete_inventory_requires_at_least_one_scanned_root():
    with pytest.raises(ValueError):
        make_inventory(complete=True, scanned_roots=())
    assert make_inventory(complete=False, scanned_roots=()).complete is False


def test_scanned_roots_are_sorted_unique_non_empty_strings():
    assert make_inventory(scanned_roots=("a", "b")).scanned_roots == ("a", "b")
    with pytest.raises(ValueError):
        make_inventory(scanned_roots=("b", "a"))
    with pytest.raises(ValueError):
        make_inventory(scanned_roots=("a", "a"))
    with pytest.raises(ValueError):
        make_inventory(scanned_roots=("a", ""))
    with pytest.raises(ValueError):
        make_inventory(scanned_roots=("a", 3))


def test_findings_must_be_sorted_by_source_id_with_unique_ids():
    a, b = make_finding(source_id="a_evt"), make_finding(source_id="b_evt")
    assert make_inventory(findings=(a, b)).findings == (a, b)
    with pytest.raises(ValueError):
        make_inventory(findings=(b, a))
    with pytest.raises(ValueError):
        make_inventory(findings=(a, a))
    # deux findings de même identifiant mais de contenu différent : refusé aussi
    with pytest.raises(ValueError):
        make_inventory(findings=(a, make_finding(source_id="a_evt", content_hash=H2)))


def test_declared_unrecorded_work_is_forbidden_in_the_inventory():
    declared = make_finding(
        source_id="declared:0001:0001", source_kind=proto.SourceKind.DECLARED_UNRECORDED_WORK, content_hash=None,
    )
    with pytest.raises(ValueError):
        make_inventory(findings=(declared,))


@pytest.mark.parametrize(
    "start, end, overlap_ok",
    [
        ("2026-01-01T00:00:00.000000Z", "2026-02-01T00:00:00.000000Z", proto.OverlapVerdict.NO_OVERLAP),
        ("2026-10-01T00:00:00.000000Z", WS, proto.OverlapVerdict.NO_OVERLAP),            # fin == ws : pas de recouvrement
        ("2026-10-01T00:00:00.000000Z", "2026-11-02T00:00:00.000001Z", proto.OverlapVerdict.OVERLAPS),
        (WE, "2027-01-01T00:00:00.000000Z", proto.OverlapVerdict.NO_OVERLAP),            # début == we : pas de recouvrement
        ("2026-11-30T23:59:59.999999Z", "2027-01-01T00:00:00.000000Z", proto.OverlapVerdict.OVERLAPS),
        ("2026-11-10T00:00:00.000000Z", "2026-11-11T00:00:00.000000Z", proto.OverlapVerdict.OVERLAPS),   # inclus dans W
        ("2026-01-01T00:00:00.000000Z", "2027-01-01T00:00:00.000000Z", proto.OverlapVerdict.OVERLAPS),   # englobe W
    ],
)
def test_resolved_overlap_verdict_must_agree_with_the_half_open_window_geometry(start, end, overlap_ok):
    ok = make_finding(window_start_utc=start, window_end_utc=end, overlap=overlap_ok)
    assert make_inventory(findings=(ok,)).findings == (ok,)
    wrong = (
        proto.OverlapVerdict.NO_OVERLAP if overlap_ok is proto.OverlapVerdict.OVERLAPS else proto.OverlapVerdict.OVERLAPS
    )
    with pytest.raises(ValueError):
        make_inventory(findings=(make_finding(window_start_utc=start, window_end_utc=end, overlap=wrong),))


def test_unresolved_findings_are_not_geometry_checked():
    unresolved = make_unresolved(window_start_utc="2026-11-10T00:00:00.000000Z", window_end_utc="2026-11-11T00:00:00.000000Z")
    assert make_inventory(findings=(unresolved,)).findings == (unresolved,)


def test_build_exposure_inventory_sorts_normalizes_and_is_order_independent():
    a, b, c = make_finding(source_id="a"), make_finding(source_id="b"), make_finding(source_id="c")
    one = proto.build_exposure_inventory(
        window_start_utc="2026-11-02T02:00:00+02:00", window_end_utc="2026-12-01T00:00:00Z",
        findings=[c, a, b], complete=True, scanned_roots=["z", "a"], trial_accounting=ACCOUNTING,
    )
    two = proto.build_exposure_inventory(
        window_start_utc=WS, window_end_utc=WE, findings=(b, c, a), complete=True, scanned_roots=("a", "z"),
        trial_accounting=ACCOUNTING,
    )
    assert one == two
    assert [f.source_id for f in one.findings] == ["a", "b", "c"]
    assert one.scanned_roots == ("a", "z")
    assert one.window_start_utc == WS


def test_build_exposure_inventory_rejects_duplicate_ids_and_duplicate_roots():
    a = make_finding(source_id="a")
    with pytest.raises(ValueError):
        proto.build_exposure_inventory(
            window_start_utc=WS, window_end_utc=WE, findings=[a, a], complete=True, scanned_roots=["r"],
            trial_accounting=ACCOUNTING,
        )
    with pytest.raises(ValueError):  # le constructeur direct refuse toujours un doublon de racine
        make_inventory(scanned_roots=("r", "r"))


def test_build_exposure_inventory_deduplicates_scanned_roots_into_the_canonical_sorted_set():
    built = proto.build_exposure_inventory(
        window_start_utc=WS, window_end_utc=WE, findings=[], complete=True, scanned_roots=["z", "r", "r", "a"],
        trial_accounting=ACCOUNTING,
    )
    assert built.scanned_roots == ("a", "r", "z")


# ============================================================================================
# Tranche 4 — déclarations chaînées et t_sel effectif
# ============================================================================================

INV_ID = "a" * 64


def canonical_sha256(obj) -> str:
    """Calcul INDÉPENDANT de la Décision 20.3 : JSON trié, séparateurs compacts, UTF-8."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def finding_record(f):
    return {
        "source_id": f.source_id, "source_kind": f.source_kind.value, "status": f.status.value,
        "overlap": f.overlap.value, "content_hash": f.content_hash, "window_start_utc": f.window_start_utc,
        "window_end_utc": f.window_end_utc, "snapshot_id": f.snapshot_id, "campaign_id": f.campaign_id,
        "unresolved_cause": None if f.unresolved_cause is None else f.unresolved_cause.value,
    }


def accounting_record(a):
    return None if a is None else {
        "research_runs": a.research_runs, "strategies": a.strategies, "campaigns": a.campaigns,
        "abandoned_reservations": a.abandoned_reservations, "failed_ingestion_attempts": a.failed_ingestion_attempts,
        "void_commitments": a.void_commitments,
    }


def make_declared(seq, position, start="2026-01-01T00:00:00.000000Z", end="2026-02-01T00:00:00.000000Z",
                  overlap=proto.OverlapVerdict.NO_OVERLAP, status=proto.SourceStatus.RESOLVED):
    if status is proto.SourceStatus.RESOLVED:
        return make_finding(
            source_id=f"declared:{seq:04d}:{position:04d}", source_kind=proto.SourceKind.DECLARED_UNRECORDED_WORK,
            content_hash=None, window_start_utc=start, window_end_utc=end, overlap=overlap,
        )
    return make_unresolved(
        source_id=f"declared:{seq:04d}:{position:04d}", source_kind=proto.SourceKind.DECLARED_UNRECORDED_WORK,
    )


def declaration_kwargs(**overrides):
    base = dict(
        version=proto.EXPOSURE_DECLARATION_SEMANTICS_VERSION,
        declaration_seq=1,
        declarant="Mira",
        inventory_id=INV_ID,
        prev_declaration_id=None,
        declared_exposures=(),
        declared_t_sel_utc=None,
        declared_trial_counts=None,
    )
    base.update(overrides)
    return base


def make_declaration(**overrides):
    return proto.ExposureDeclaration(**declaration_kwargs(**overrides))


def test_exposure_declaration_has_eight_public_fields_in_the_frozen_order():
    assert tuple(f.name for f in dataclasses.fields(proto.ExposureDeclaration)) == (
        "version", "declaration_seq", "declarant", "inventory_id", "prev_declaration_id", "declared_exposures",
        "declared_t_sel_utc", "declared_trial_counts",
    )
    assert proto.EXPOSURE_DECLARATION_SEMANTICS_VERSION == "gate_v_exposure_declaration_v1"


def test_exposure_declaration_accepts_a_first_declaration_without_exposure():
    declaration = make_declaration()
    assert declaration.declared_exposures == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        declaration.declarant = "x"  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        dict(version="gate_v_exposure_declaration_v0"),
        dict(declaration_seq=0),
        dict(declaration_seq=True),
        dict(declaration_seq="1"),
        dict(declarant=""),
        dict(declarant=3),
        dict(inventory_id="x"),
        dict(inventory_id="A" * 64),
        dict(prev_declaration_id=H1),                       # seq 1 : pas de précédent
        dict(declaration_seq=2, prev_declaration_id=None),  # seq > 1 : précédent obligatoire
        dict(declaration_seq=2, prev_declaration_id="zz"),
        dict(declared_exposures=[make_declared(1, 1)]),     # liste refusée
        dict(declared_exposures=(make_finding(),)),         # pas une exposition déclarée
        dict(declared_t_sel_utc="2026-10-20T00:00:00Z"),    # non normalisé
        dict(declared_trial_counts=(1, 2, 3, 4, 5, 6)),
    ],
)
def test_exposure_declaration_rejects_malformed_values(overrides):
    with pytest.raises(ValueError):
        make_declaration(**overrides)


def test_declared_exposure_ids_must_follow_seq_and_one_based_position_order():
    ok = (make_declared(1, 1), make_declared(1, 2))
    assert make_declaration(declared_exposures=ok).declared_exposures == ok
    with pytest.raises(ValueError):
        make_declaration(declared_exposures=(make_declared(2, 1),))         # mauvais seq dans l'identifiant
    with pytest.raises(ValueError):
        make_declaration(declared_exposures=(make_declared(1, 2),))         # position doit commencer à 1
    with pytest.raises(ValueError):
        make_declaration(declared_exposures=(make_declared(1, 2), make_declared(1, 1)))  # ordre
    with pytest.raises(ValueError):
        make_declaration(declared_exposures=(make_declared(1, 1), make_declared(1, 1)))  # doublon


def test_build_exposure_declaration_normalizes_and_orders_declared_exposures():
    built = proto.build_exposure_declaration(
        declaration_seq=1, declarant="Mira", inventory_id=INV_ID, prev_declaration_id=None,
        declared_exposures=[make_declared(1, 2), make_declared(1, 1)],
        declared_t_sel_utc="2026-10-20T02:00:00+02:00", declared_trial_counts=ACCOUNTING,
    )
    assert [f.source_id for f in built.declared_exposures] == ["declared:0001:0001", "declared:0001:0002"]
    assert built.declared_t_sel_utc == "2026-10-20T00:00:00.000000Z"
    assert built.declared_trial_counts == ACCOUNTING
    assert built.version == proto.EXPOSURE_DECLARATION_SEMANTICS_VERSION


def test_compute_declaration_id_matches_an_independent_canonical_json_hash():
    declaration = make_declaration(
        declared_exposures=(make_declared(1, 1),), declared_t_sel_utc="2026-10-20T00:00:00.000000Z",
        declared_trial_counts=ACCOUNTING,
    )
    expected = canonical_sha256({
        "version": "gate_v_exposure_declaration_v1",
        "declaration_seq": 1,
        "declarant": "Mira",
        "inventory_id": INV_ID,
        "prev_declaration_id": None,
        "declared_t_sel_utc": "2026-10-20T00:00:00.000000Z",
        "declared_exposures": [finding_record(make_declared(1, 1))],
        "declared_trial_counts": accounting_record(ACCOUNTING),
    })
    assert proto.compute_declaration_id(declaration) == expected


def test_compute_declaration_id_changes_with_every_semantic_field_and_is_stable():
    base = make_declaration()
    assert proto.compute_declaration_id(base) == proto.compute_declaration_id(make_declaration())
    variants = [
        make_declaration(declarant="Alex"),
        make_declaration(inventory_id="b" * 64),
        make_declaration(declared_t_sel_utc="2026-10-20T00:00:00.000000Z"),
        make_declaration(declared_exposures=(make_declared(1, 1),)),
        make_declaration(declared_trial_counts=ACCOUNTING),
        make_declaration(declaration_seq=2, prev_declaration_id=proto.compute_declaration_id(base)),
    ]
    ids = {proto.compute_declaration_id(v) for v in variants} | {proto.compute_declaration_id(base)}
    assert len(ids) == len(variants) + 1


def chain(*declaration_specs, hash_linked=True):
    """Construit une chaîne dense valide de déclarations à partir de dicts d'overrides."""
    declarations = []
    prev = None
    for index, spec in enumerate(declaration_specs, start=1):
        declaration = make_declaration(declaration_seq=index, prev_declaration_id=prev, **spec)
        declarations.append(declaration)
        prev = proto.compute_declaration_id(declaration)
    return proto.DeclarationSet(declarations=tuple(declarations), hash_linked=hash_linked)


def test_declaration_set_has_two_fields_and_validates_a_dense_hash_chain():
    assert tuple(f.name for f in dataclasses.fields(proto.DeclarationSet)) == ("declarations", "hash_linked")
    declarations = chain({}, {"declared_t_sel_utc": "2026-10-21T00:00:00.000000Z"}, {})
    assert [d.declaration_seq for d in declarations.declarations] == [1, 2, 3]
    assert declarations.hash_linked is True


def test_declaration_set_rejects_gaps_wrong_links_and_inconsistent_emptiness():
    first = make_declaration()
    second_ok = make_declaration(declaration_seq=2, prev_declaration_id=proto.compute_declaration_id(first))
    assert proto.DeclarationSet(declarations=(first, second_ok), hash_linked=True)
    with pytest.raises(ValueError):  # lien de chaîne faux
        proto.DeclarationSet(
            declarations=(first, make_declaration(declaration_seq=2, prev_declaration_id=H1)), hash_linked=True,
        )
    with pytest.raises(ValueError):  # trou dans les seq
        proto.DeclarationSet(
            declarations=(first, make_declaration(declaration_seq=3, prev_declaration_id=proto.compute_declaration_id(first))),
            hash_linked=True,
        )
    with pytest.raises(ValueError):  # ne commence pas à 1
        proto.DeclarationSet(declarations=(second_ok,), hash_linked=True)
    with pytest.raises(ValueError):  # liste
        proto.DeclarationSet(declarations=[first], hash_linked=True)
    with pytest.raises(ValueError):  # vide mais hash_linked vrai
        proto.DeclarationSet(declarations=(), hash_linked=True)
    with pytest.raises(ValueError):
        proto.DeclarationSet(declarations=(first,), hash_linked=1)
    assert proto.DeclarationSet(declarations=(), hash_linked=False).declarations == ()


def test_declaration_set_hash_linked_false_is_a_legal_fact_kept_as_is():
    assert chain({}, hash_linked=False).hash_linked is False


T10 = "2026-10-10T00:00:00.000000Z"
T20 = "2026-10-20T00:00:00.000000Z"
T25 = "2026-10-25T00:00:00.000000Z"


def test_effective_t_sel_is_the_running_maximum_and_never_goes_back():
    declarations = chain({"declared_t_sel_utc": T25}, {"declared_t_sel_utc": T20}, {"declared_t_sel_utc": None}).declarations
    effective, ignored = proto.compute_effective_t_sel(T10, declarations)
    assert effective == T25
    assert ignored == (2,)


def test_effective_t_sel_can_be_pushed_later_and_equal_values_are_not_lowering():
    declarations = chain({"declared_t_sel_utc": T20}, {"declared_t_sel_utc": T20}).declarations
    assert proto.compute_effective_t_sel(T10, declarations) == (T20, ())


def test_effective_t_sel_is_none_when_the_commitment_has_none():
    declarations = chain({"declared_t_sel_utc": T25}).declarations
    assert proto.compute_effective_t_sel(None, declarations) == (None, ())


def test_effective_t_sel_ignores_a_declaration_lower_than_the_commitment():
    declarations = chain({"declared_t_sel_utc": T10}).declarations
    assert proto.compute_effective_t_sel(T20, declarations) == (T20, (1,))  # T10 < T20 : abaissement, ignoré et listé


def test_effective_t_sel_rejects_bad_arguments():
    with pytest.raises(ValueError):
        proto.compute_effective_t_sel("2026-10-10T00:00:00Z", ())
    with pytest.raises(TypeError):
        proto.compute_effective_t_sel(T10, [make_declaration()])


def test_effective_t_sel_requires_declarations_in_strictly_increasing_seq_order():
    declarations = chain({"declared_t_sel_utc": T25}, {"declared_t_sel_utc": T20}).declarations
    assert proto.compute_effective_t_sel(T10, declarations) == (T25, (2,))
    with pytest.raises(ValueError):
        proto.compute_effective_t_sel(T10, tuple(reversed(declarations)))
    with pytest.raises(ValueError):
        proto.compute_effective_t_sel(T10, (declarations[0], declarations[0]))


def test_declaration_seq_beyond_the_four_digit_identifier_capacity_is_refused():
    with pytest.raises(ValueError):
        make_declaration(declaration_seq=10000, prev_declaration_id=H1)
    assert make_declaration(declaration_seq=9999, prev_declaration_id=H1).declaration_seq == 9999


# ============================================================================================
# Tranche 5 — contexte de campagne, absorption des enregistrements propres, inventory_id inter-étages
# ============================================================================================

K = proto.SourceKind
Stage = proto.OwnRecordStage


def own_record(kind, source_id, campaign=CURRENT, start=WS, end=WE, overlap=proto.OverlapVerdict.OVERLAPS,
               content_hash=H2):
    return make_finding(
        source_id=source_id, source_kind=kind, overlap=overlap, content_hash=content_hash,
        window_start_utc=start, window_end_utc=end, campaign_id=campaign,
    )


def res(source_id="res_own", **kw):
    return own_record(K.REGISTRY_RESERVATION, source_id, **kw)


def adm(source_id="adm_own", **kw):
    return own_record(K.REGISTRY_ADMISSION, source_id, **kw)


def claim(source_id="claim_own", **kw):
    return own_record(K.FINAL_HOLDOUT_CLAIM, source_id, **kw)


def consumption(source_id="cons_own", **kw):
    return own_record(K.CONSUMPTION, source_id, **kw)


def read_intent(source_id="intent_own", **kw):
    return own_record(K.READ_INTENT, source_id, **kw)


def ctx(stage, campaign=CURRENT):
    return proto.OwnCampaignContext(current_campaign_id=campaign, own_record_stage=stage)


def stage_inventory(*findings, **overrides):
    return make_inventory(*findings, **overrides)


def ids(findings):
    return tuple(f.source_id for f in findings)


def test_own_campaign_context_has_two_fields_and_validates_them():
    assert tuple(f.name for f in dataclasses.fields(proto.OwnCampaignContext)) == (
        "current_campaign_id", "own_record_stage",
    )
    assert ctx(Stage.RESERVED).current_campaign_id == CURRENT
    with pytest.raises(ValueError):
        proto.OwnCampaignContext(current_campaign_id="", own_record_stage=Stage.RESERVED)
    with pytest.raises(ValueError):
        proto.OwnCampaignContext(current_campaign_id=CURRENT, own_record_stage="RESERVED")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx(Stage.RESERVED).own_record_stage = Stage.CLAIMED  # type: ignore[misc]


@pytest.mark.parametrize(
    "stage, records",
    [
        (Stage.NO_OWN_RECORDS, ()),
        (Stage.RESERVED, (res(),)),
        (Stage.ADMITTED, (res(), adm())),
        (Stage.CLAIMED, (res(), adm(), claim())),
        (Stage.CONSUMED, (res(), adm(), claim(), consumption())),
    ],
)
def test_expected_own_records_are_absorbed_at_each_verified_stage(stage, records):
    absorbed, remaining, anomalies = proto.partition_own_records(stage_inventory(*records), ctx(stage))
    assert set(ids(absorbed)) == set(ids(records))
    assert remaining == ()
    assert anomalies == ()


def test_foreign_records_are_never_absorbed():
    foreign = res("res_other", campaign=OTHER)
    absorbed, remaining, anomalies = proto.partition_own_records(stage_inventory(res(), foreign), ctx(Stage.RESERVED))
    assert ids(absorbed) == ("res_own",)
    assert ids(remaining) == ("res_other",)
    assert anomalies == ()


def test_duplicate_own_reservation_is_not_absorbed_and_both_ids_are_anomalies_without_missing():
    absorbed, remaining, anomalies = proto.partition_own_records(
        stage_inventory(res("res_1"), res("res_2")), ctx(Stage.RESERVED),
    )
    assert absorbed == ()
    assert ids(remaining) == ("res_1", "res_2")
    assert anomalies == ("res_1", "res_2")


def test_missing_expected_own_record_is_reported_as_missing_type_anomaly():
    assert proto.partition_own_records(stage_inventory(), ctx(Stage.RESERVED))[2] == ("missing:RESERVATION",)
    assert proto.partition_own_records(stage_inventory(res()), ctx(Stage.ADMITTED))[2] == ("missing:ADMISSION",)
    assert proto.partition_own_records(stage_inventory(res(), adm()), ctx(Stage.CLAIMED))[2] == (
        "missing:FINAL_HOLDOUT_CLAIM",
    )
    assert proto.partition_own_records(stage_inventory(res(), adm(), claim()), ctx(Stage.CONSUMED))[2] == (
        "missing:CONSUMPTION",
    )
    everything_missing = proto.partition_own_records(stage_inventory(), ctx(Stage.CONSUMED))[2]
    assert everything_missing == (
        "missing:ADMISSION", "missing:CONSUMPTION", "missing:FINAL_HOLDOUT_CLAIM", "missing:RESERVATION",
    )


def test_unexpected_own_non_exposing_record_is_an_anomaly_and_stays_in_the_remaining_findings():
    absorbed, remaining, anomalies = proto.partition_own_records(
        stage_inventory(res(), adm()), ctx(Stage.RESERVED),
    )
    assert ids(absorbed) == ("res_own",)
    assert ids(remaining) == ("adm_own",)
    assert anomalies == ("adm_own",)


def test_own_reservation_with_a_window_different_from_w_is_not_absorbed():
    shifted = res(start="2026-11-03T00:00:00.000000Z", end=WE)
    absorbed, remaining, anomalies = proto.partition_own_records(stage_inventory(shifted), ctx(Stage.RESERVED))
    assert absorbed == ()
    assert ids(remaining) == ("res_own",)
    assert anomalies == ("res_own",)


def test_own_unresolved_record_with_a_window_equal_to_w_is_still_not_absorbed():
    unresolved = make_unresolved(
        source_id="res_own", source_kind=K.REGISTRY_RESERVATION, campaign_id=CURRENT,
        window_start_utc=WS, window_end_utc=WE, unresolved_cause=proto.UnresolvedCause.INVALID_SCHEMA,
    )
    absorbed, remaining, anomalies = proto.partition_own_records(stage_inventory(unresolved), ctx(Stage.RESERVED))
    assert absorbed == () and ids(remaining) == ("res_own",) and anomalies == ("res_own",)


def test_own_resolved_reservation_with_a_disjoint_window_is_an_anomaly_not_a_construction_error():
    disjoint = res(start="2026-01-01T00:00:00.000000Z", end="2026-02-01T00:00:00.000000Z",
                   overlap=proto.OverlapVerdict.NO_OVERLAP)
    absorbed, remaining, anomalies = proto.partition_own_records(stage_inventory(disjoint), ctx(Stage.RESERVED))
    assert absorbed == () and anomalies == ("res_own",)
    result = classify(disjoint)
    assert result.classification is Cls.UNDETERMINED and result.overlapping_registration_ids == ()


def test_own_unresolved_non_exposing_record_is_not_absorbed_and_is_an_anomaly():
    unresolved = make_unresolved(source_id="res_own", source_kind=K.REGISTRY_RESERVATION, campaign_id=CURRENT)
    absorbed, remaining, anomalies = proto.partition_own_records(stage_inventory(unresolved), ctx(Stage.RESERVED))
    assert absorbed == ()
    assert ids(remaining) == ("res_own",)
    assert anomalies == ("res_own",)


@pytest.mark.parametrize(
    "stage, records, expected_remaining",
    [
        (Stage.RESERVED, (res(), claim()), ("claim_own",)),                       # Claim inattendu
        (Stage.CLAIMED, (res(), adm(), claim("c1"), claim("c2")), ("c1", "c2")),  # Claim dupliqué
        (Stage.CLAIMED, (res(), adm(), claim(start="2026-11-03T00:00:00.000000Z")), ("claim_own",)),  # fenêtre != W
        (Stage.RESERVED, (res(), consumption()), ("cons_own",)),                  # CONSUMPTION inattendue
        (Stage.CONSUMED, (res(), adm(), claim(), consumption("k1"), consumption("k2")), ("k1", "k2")),
        (Stage.CLAIMED, (res(), adm(), claim(), read_intent()), ("intent_own",)),  # ReadIntent jamais attendu
    ],
)
def test_own_exposing_records_that_cannot_be_absorbed_stay_visible_without_being_anomalies(
    stage, records, expected_remaining,
):
    absorbed, remaining, anomalies = proto.partition_own_records(stage_inventory(*records), ctx(stage))
    assert ids(remaining) == expected_remaining
    assert anomalies == ()  # elles sont des expositions, pas des anomalies d'enregistrement non exposant


def test_own_unresolved_claim_is_present_so_it_is_not_missing_and_not_absorbed():
    unresolved = make_unresolved(
        source_id="claim_own", source_kind=K.FINAL_HOLDOUT_CLAIM, campaign_id=CURRENT,
        unresolved_cause=proto.UnresolvedCause.WINDOW_UNKNOWN,
    )
    absorbed, remaining, anomalies = proto.partition_own_records(
        stage_inventory(res(), adm(), unresolved), ctx(Stage.CLAIMED),
    )
    assert ids(absorbed) == ("adm_own", "res_own")
    assert ids(remaining) == ("claim_own",)
    assert anomalies == ()


def test_other_exposing_kinds_carrying_the_current_campaign_id_are_ordinary_exposures():
    event = make_finding(source_id="evt_own", source_kind=K.HOLDOUT_ACCESS_EVENT, campaign_id=CURRENT)
    absorbed, remaining, anomalies = proto.partition_own_records(stage_inventory(res(), event), ctx(Stage.RESERVED))
    assert ids(absorbed) == ("res_own",)
    assert ids(remaining) == ("evt_own",)
    assert anomalies == ()


def test_partition_uses_the_exact_current_campaign_id_only():
    absorbed, remaining, anomalies = proto.partition_own_records(
        stage_inventory(res(campaign="campaign_a2")), ctx(Stage.RESERVED),
    )
    assert absorbed == ()
    assert ids(remaining) == ("res_own",)
    assert anomalies == ("missing:RESERVATION",)


def test_partition_rejects_bad_arguments():
    with pytest.raises(TypeError):
        proto.partition_own_records("inventory", ctx(Stage.RESERVED))
    with pytest.raises(TypeError):
        proto.partition_own_records(stage_inventory(), "ctx")


def independent_inventory_id(inventory, absorbed_ids=()):
    return canonical_sha256({
        "version": inventory.version,
        "window_start_utc": inventory.window_start_utc,
        "window_end_utc": inventory.window_end_utc,
        "complete": inventory.complete,
        "scanned_roots": list(inventory.scanned_roots),
        "findings": [finding_record(f) for f in inventory.findings if f.source_id not in absorbed_ids],
    })


def test_inventory_id_matches_an_independent_hash_over_the_non_absorbed_findings():
    inventory = stage_inventory(res(), make_finding(source_id="evt_x"))
    expected = independent_inventory_id(inventory, absorbed_ids={"res_own"})
    assert proto.compute_exposure_inventory_id(inventory, ctx(Stage.RESERVED)) == expected


def test_inventory_id_is_identical_across_the_legitimate_stages_and_ignores_absorbed_records():
    foreign = make_finding(source_id="evt_x")
    by_stage = {
        Stage.RESERVED: stage_inventory(res(), foreign),
        Stage.ADMITTED: stage_inventory(res(), adm(), foreign),
        Stage.CLAIMED: stage_inventory(res(), adm(), claim(), foreign),
        Stage.CONSUMED: stage_inventory(res(), adm(), claim(), consumption(), foreign),
    }
    results = {stage: proto.compute_exposure_inventory_id(inv, ctx(stage)) for stage, inv in by_stage.items()}
    assert len(set(results.values())) == 1


def test_inventory_id_ignores_trial_accounting_and_changes_with_scientific_content():
    base = stage_inventory(res())
    base_id = proto.compute_exposure_inventory_id(base, ctx(Stage.RESERVED))
    for field in ("research_runs", "strategies", "campaigns", "abandoned_reservations",
                  "failed_ingestion_attempts", "void_commitments"):
        values = dataclasses.asdict(ACCOUNTING)
        values[field] += 1
        changed = stage_inventory(res(), trial_accounting=proto.TrialAccounting(**values))
        assert proto.compute_exposure_inventory_id(changed, ctx(Stage.RESERVED)) == base_id
    variants = [
        stage_inventory(res(), complete=False),
        stage_inventory(res(), scanned_roots=("other_root",)),
        stage_inventory(res(), make_finding(source_id="evt_x")),
        stage_inventory(res(), window_end_utc="2026-12-02T00:00:00.000000Z"),
    ]
    for variant in variants:
        assert proto.compute_exposure_inventory_id(variant, ctx(Stage.RESERVED)) != base_id


def test_a_foreign_consumption_changes_the_inventory_id_but_a_foreign_registry_record_listed_via_overlap_too():
    base = stage_inventory(res())
    foreign_consumption = make_finding(source_id="cons_foreign", source_kind=K.CONSUMPTION, campaign_id=OTHER)
    with_foreign = stage_inventory(res(), foreign_consumption)
    assert proto.compute_exposure_inventory_id(with_foreign, ctx(Stage.RESERVED)) != proto.compute_exposure_inventory_id(
        base, ctx(Stage.RESERVED),
    )


def test_same_exposure_under_two_snapshot_ids_has_two_inventory_ids():
    one = stage_inventory(res(), make_finding(source_id="evt_x", snapshot_id="snap_1"))
    two = stage_inventory(res(), make_finding(source_id="evt_x", snapshot_id="snap_2"))
    assert proto.compute_exposure_inventory_id(one, ctx(Stage.RESERVED)) != proto.compute_exposure_inventory_id(
        two, ctx(Stage.RESERVED),
    )


def test_a_stage_too_high_or_too_low_does_not_hide_the_unexpected_record_from_the_inventory_id():
    inventory = stage_inventory(res(), adm())
    at_reserved = proto.compute_exposure_inventory_id(inventory, ctx(Stage.RESERVED))   # adm inattendue : visible
    at_admitted = proto.compute_exposure_inventory_id(inventory, ctx(Stage.ADMITTED))   # les deux absorbées
    assert at_reserved != at_admitted


# ============================================================================================
# Tranche 6 — faits de chronologie (preuve de temps, ancrage, S0, ingestion)
# ============================================================================================

T_SEL = "2026-10-20T00:00:00.000000Z"
T_ANCHOR = "2026-10-25T00:00:00.000000Z"
S0_MAX = "2026-05-19T12:48:00.000000Z"
INGESTED = "2026-12-02T00:00:00.000000Z"
DAY = 86400


def valid_proof(bound=T_ANCHOR, own=True):
    return proto.TimeProofFact(status=proto.TimeProofStatus.VALID, bound_utc=bound, targets_own_reservation=own)


def no_proof(status=proto.TimeProofStatus.ABSENT):
    return proto.TimeProofFact(status=status, bound_utc=None, targets_own_reservation=None)


def chronology_kwargs(**overrides):
    base = dict(
        commitment_t_sel_utc=T_SEL,
        reservation_durable=True,
        time_proof=valid_proof(),
        anchor_margin_seconds=DAY,
        s0_max_time_utc=S0_MAX,
        ingested_at_utc=INGESTED,
        ingestion_range_matches=True,
    )
    base.update(overrides)
    return base


def make_chronology(**overrides):
    return proto.ChronologyFacts(**chronology_kwargs(**overrides))


def test_time_proof_fact_has_three_fields_and_enforces_valid_iff_bound_and_target_present():
    assert tuple(f.name for f in dataclasses.fields(proto.TimeProofFact)) == (
        "status", "bound_utc", "targets_own_reservation",
    )
    assert valid_proof().bound_utc == T_ANCHOR
    assert valid_proof(own=False).targets_own_reservation is False
    for status in (proto.TimeProofStatus.ABSENT, proto.TimeProofStatus.INVALID, proto.TimeProofStatus.UNVERIFIABLE):
        assert no_proof(status).bound_utc is None
        with pytest.raises(ValueError):
            proto.TimeProofFact(status=status, bound_utc=T_ANCHOR, targets_own_reservation=True)
        with pytest.raises(ValueError):
            proto.TimeProofFact(status=status, bound_utc=None, targets_own_reservation=True)
    with pytest.raises(ValueError):
        proto.TimeProofFact(status=proto.TimeProofStatus.VALID, bound_utc=None, targets_own_reservation=True)
    with pytest.raises(ValueError):
        proto.TimeProofFact(status=proto.TimeProofStatus.VALID, bound_utc=T_ANCHOR, targets_own_reservation=None)
    with pytest.raises(ValueError):
        proto.TimeProofFact(status=proto.TimeProofStatus.VALID, bound_utc="2026-10-25T00:00:00Z",
                            targets_own_reservation=True)
    with pytest.raises(ValueError):
        proto.TimeProofFact(status="VALID", bound_utc=T_ANCHOR, targets_own_reservation=True)


def test_chronology_facts_has_seven_fields_in_the_frozen_order_and_is_immutable():
    assert tuple(f.name for f in dataclasses.fields(proto.ChronologyFacts)) == (
        "commitment_t_sel_utc", "reservation_durable", "time_proof", "anchor_margin_seconds", "s0_max_time_utc",
        "ingested_at_utc", "ingestion_range_matches",
    )
    chronology = make_chronology()
    with pytest.raises(dataclasses.FrozenInstanceError):
        chronology.reservation_durable = False  # type: ignore[misc]


def test_chronology_facts_accepts_unknown_values_as_none_without_inventing_defaults():
    unknown = make_chronology(
        commitment_t_sel_utc=None, reservation_durable=None, time_proof=no_proof(), anchor_margin_seconds=None,
        s0_max_time_utc=None, ingested_at_utc=None, ingestion_range_matches=None,
    )
    assert unknown.anchor_margin_seconds is None
    assert unknown.reservation_durable is None


@pytest.mark.parametrize(
    "overrides",
    [
        dict(commitment_t_sel_utc="2026-10-20T00:00:00Z"),
        dict(s0_max_time_utc="2026-05-19T12:48:00"),
        dict(ingested_at_utc="2026-12-02"),
        dict(reservation_durable=1),
        dict(reservation_durable="yes"),
        dict(ingestion_range_matches=0),
        dict(time_proof=None),
        dict(time_proof="VALID"),
        dict(anchor_margin_seconds=True),
        dict(anchor_margin_seconds=1.5),
        dict(anchor_margin_seconds="86400"),
    ],
)
def test_chronology_facts_rejects_malformed_values(overrides):
    with pytest.raises(ValueError):
        make_chronology(**overrides)


def test_zero_margin_is_constructible_so_that_the_rules_can_judge_it():
    assert make_chronology(anchor_margin_seconds=0).anchor_margin_seconds == 0


def test_build_chronology_facts_normalizes_instants():
    built = proto.build_chronology_facts(
        commitment_t_sel_utc="2026-10-20T02:00:00+02:00", reservation_durable=True, time_proof=valid_proof(),
        anchor_margin_seconds=DAY, s0_max_time_utc="2026-05-19T14:48:00+02:00",
        ingested_at_utc="2026-12-02T00:00:00Z", ingestion_range_matches=True,
    )
    assert built == make_chronology()
    with pytest.raises(ValueError):
        proto.build_chronology_facts(
            commitment_t_sel_utc="2026-10-20T00:00:00", reservation_durable=True, time_proof=valid_proof(),
            anchor_margin_seconds=DAY, s0_max_time_utc=None, ingested_at_utc=None, ingestion_range_matches=None,
        )


# ============================================================================================
# Tranche 7 — ClassificationInput, résultat et classification R1 / R2 / R3
# ============================================================================================

CLASS_LEVEL_CODES = frozenset(list(proto.ReasonCode)[:7])
RC = proto.ReasonCode
Cls = proto.ExposureClass


def make_input(*findings, stage=Stage.RESERVED, declaration_specs=({},), hash_linked=True, chronology=None,
               campaign=CURRENT, **inventory_overrides):
    """ClassificationInput valide dont les déclarations référencent l'inventory_id calculé pour l'étage."""
    inventory = make_inventory(*findings, **inventory_overrides)
    context = ctx(stage, campaign)
    inventory_id = proto.compute_exposure_inventory_id(inventory, context)
    declarations = []
    prev = None
    for index, spec in enumerate(declaration_specs, start=1):
        declaration = make_declaration(declaration_seq=index, prev_declaration_id=prev, inventory_id=inventory_id, **spec)
        declarations.append(declaration)
        prev = proto.compute_declaration_id(declaration)
    return proto.ClassificationInput(
        inventory=inventory,
        declarations=proto.DeclarationSet(declarations=tuple(declarations), hash_linked=hash_linked),
        chronology=chronology if chronology is not None else make_chronology(),
        own_context=context,
    )


def b0(**overrides):
    return make_input(res(), **overrides)


def class_reasons(result):
    return tuple(r for r in result.reasons if r in CLASS_LEVEL_CODES)


def assert_class_twins(result):
    """UNRESOLVED_SOURCE / INVENTORY_INCOMPLETE / OWN_REGISTRATION_ANOMALY <=> code F1 jumeau."""
    f1 = next(c for c in result.conditions if c.condition == "F1")
    for class_code, f1_code in (
        (RC.UNRESOLVED_SOURCE, RC.F1_SOURCES_UNRESOLVED),
        (RC.INVENTORY_INCOMPLETE, RC.F1_INVENTORY_INCOMPLETE),
        (RC.OWN_REGISTRATION_ANOMALY, RC.F1_OWN_ANOMALY),
    ):
        assert (class_code in result.reasons) == (f1_code in f1.reasons)
    assert ((RC.EXPOSURE_ESTABLISHED_INVENTORY in result.reasons) or (RC.EXPOSURE_ESTABLISHED_DECLARED in result.reasons)) == (
        RC.F1_EXPOSURE_ESTABLISHED in f1.reasons
    )


def classify(*findings, **kw):
    result = proto.classify_exposure(make_input(*findings, **kw))
    assert_class_twins(result)
    return result


def test_classification_input_has_four_fields_in_the_frozen_order():
    assert tuple(f.name for f in dataclasses.fields(proto.ClassificationInput)) == (
        "inventory", "declarations", "chronology", "own_context",
    )


def test_classification_input_requires_at_least_one_declaration():
    inventory = make_inventory(res())
    with pytest.raises(ValueError):
        proto.ClassificationInput(
            inventory=inventory, declarations=proto.DeclarationSet(declarations=(), hash_linked=False),
            chronology=make_chronology(), own_context=ctx(Stage.RESERVED),
        )


def test_classification_input_rejects_a_declaration_that_references_another_inventory_id():
    good = b0()
    other = make_declaration(inventory_id="f" * 64)
    with pytest.raises(ValueError):
        proto.ClassificationInput(
            inventory=good.inventory, declarations=proto.DeclarationSet(declarations=(other,), hash_linked=True),
            chronology=good.chronology, own_context=good.own_context,
        )


def test_classification_input_rejects_wrong_component_types():
    good = b0()
    for name in ("inventory", "declarations", "chronology", "own_context"):
        kwargs = dict(inventory=good.inventory, declarations=good.declarations, chronology=good.chronology,
                      own_context=good.own_context)
        kwargs[name] = object()
        with pytest.raises(ValueError):
            proto.ClassificationInput(**kwargs)


def test_foreign_registry_records_must_overlap_w_to_be_listable():
    foreign_disjoint = res("res_other", campaign=OTHER, start="2026-01-01T00:00:00.000000Z",
                           end="2026-02-01T00:00:00.000000Z", overlap=proto.OverlapVerdict.NO_OVERLAP)
    with pytest.raises(ValueError):
        make_input(res(), foreign_disjoint)
    foreign_admission_disjoint = adm("adm_other", campaign=OTHER, start="2026-01-01T00:00:00.000000Z",
                                     end="2026-02-01T00:00:00.000000Z", overlap=proto.OverlapVerdict.NO_OVERLAP)
    with pytest.raises(ValueError):
        make_input(res(), foreign_admission_disjoint)


def test_declared_exposure_verdict_must_agree_with_w_geometry():
    bad = make_declared(1, 1, start="2026-11-10T00:00:00.000000Z", end="2026-11-11T00:00:00.000000Z",
                        overlap=proto.OverlapVerdict.NO_OVERLAP)
    with pytest.raises(ValueError):
        make_input(res(), declaration_specs=({"declared_exposures": (bad,)},))


def test_exposure_classification_result_has_sixteen_fields_in_the_frozen_order():
    assert tuple(f.name for f in dataclasses.fields(proto.ExposureClassificationResult)) == (
        "rules_version", "classification", "chronology_level", "inventory_id", "inventory_content_digest",
        "input_digest", "classification_id", "t_sel_effective_utc", "t_sel_lowering_ignored_seqs",
        "established_exposure_ids", "unresolved_source_ids", "overlapping_registration_ids",
        "absorbed_own_record_ids", "own_anomaly_ids", "conditions", "reasons",
    )
    assert tuple(f.name for f in dataclasses.fields(proto.FConditionResult)) == ("condition", "status", "reasons")
    assert proto.EXPOSURE_CLASSIFICATION_RULES_VERSION == "gate_v_exposure_classification_v1"


def test_b0_is_fresh_with_no_class_level_reason_and_its_own_reservation_absorbed():
    result = classify(res())
    assert result.classification is Cls.FRESH_UNEXPOSED_DECLARED
    assert class_reasons(result) == ()
    assert result.absorbed_own_record_ids == ("res_own",)
    assert result.established_exposure_ids == () and result.unresolved_source_ids == ()
    assert result.overlapping_registration_ids == () and result.own_anomaly_ids == ()
    assert [c.condition for c in result.conditions] == ["F1", "F2", "F3", "F4", "F5", "F6"]
    assert result.conditions[0].status is proto.ConditionStatus.MET
    assert result.rules_version == proto.EXPOSURE_CLASSIFICATION_RULES_VERSION
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.classification = Cls.UNDETERMINED  # type: ignore[misc]


def test_established_inventory_exposure_gives_retrospective_exposed():
    overlapping = make_finding(
        source_id="evt_overlap", overlap=proto.OverlapVerdict.OVERLAPS,
        window_start_utc="2026-11-10T00:00:00.000000Z", window_end_utc="2026-11-11T00:00:00.000000Z",
    )
    result = classify(res(), overlapping)
    assert result.classification is Cls.RETROSPECTIVE_EXPOSED
    assert result.established_exposure_ids == ("evt_overlap",)
    assert RC.EXPOSURE_ESTABLISHED_INVENTORY in result.reasons
    assert result.chronology_level is proto.ChronologyLevel.NOT_APPLICABLE
    f1 = result.conditions[0]
    assert f1.status is proto.ConditionStatus.NOT_MET and RC.F1_EXPOSURE_ESTABLISHED in f1.reasons


def test_established_declared_exposure_gives_retrospective_exposed():
    declared = make_declared(1, 1, start="2026-11-10T00:00:00.000000Z", end="2026-11-11T00:00:00.000000Z",
                             overlap=proto.OverlapVerdict.OVERLAPS)
    result = classify(res(), declaration_specs=({"declared_exposures": (declared,)},))
    assert result.classification is Cls.RETROSPECTIVE_EXPOSED
    assert result.established_exposure_ids == ("declared:0001:0001",)
    assert RC.EXPOSURE_ESTABLISHED_DECLARED in result.reasons
    assert RC.EXPOSURE_ESTABLISHED_INVENTORY not in result.reasons


def test_non_overlapping_resolved_exposure_is_listed_but_does_not_expose_the_window():
    result = classify(res(), make_finding(source_id="evt_old"))
    assert result.classification is Cls.FRESH_UNEXPOSED_DECLARED
    assert result.established_exposure_ids == ()


def test_unresolved_source_alone_gives_undetermined():
    result = classify(res(), make_unresolved(source_id="evt_unreadable"))
    assert result.classification is Cls.UNDETERMINED
    assert result.unresolved_source_ids == ("evt_unreadable",)
    assert RC.UNRESOLVED_SOURCE in result.reasons
    f1 = result.conditions[0]
    assert f1.status is proto.ConditionStatus.UNVERIFIED and RC.F1_SOURCES_UNRESOLVED in f1.reasons
    assert result.chronology_level is proto.ChronologyLevel.UNSEEN_HISTORICAL


def test_unreadable_registry_is_unresolved_and_therefore_undetermined():
    unreadable = make_unresolved(source_id="registry_x", source_kind=K.REGISTRY_UNREADABLE)
    assert classify(res(), unreadable).classification is Cls.UNDETERMINED


def test_incomplete_inventory_gives_undetermined():
    result = classify(res(), complete=False, scanned_roots=())
    assert result.classification is Cls.UNDETERMINED
    assert RC.INVENTORY_INCOMPLETE in result.reasons
    assert RC.F1_INVENTORY_INCOMPLETE in result.conditions[0].reasons


def test_established_exposure_beats_unresolved_source_and_all_applicable_reasons_are_cumulated():
    overlapping = make_finding(
        source_id="evt_overlap", overlap=proto.OverlapVerdict.OVERLAPS,
        window_start_utc="2026-11-10T00:00:00.000000Z", window_end_utc="2026-11-11T00:00:00.000000Z",
    )
    result = classify(res(), overlapping, make_unresolved(source_id="evt_unreadable"))
    assert result.classification is Cls.RETROSPECTIVE_EXPOSED
    assert result.unresolved_source_ids == ("evt_unreadable",)
    assert RC.UNRESOLVED_SOURCE in result.reasons and RC.EXPOSURE_ESTABLISHED_INVENTORY in result.reasons
    assert result.conditions[0].status is proto.ConditionStatus.NOT_MET  # violation connue > donnée manquante


@pytest.mark.parametrize("builder", [res, adm])
def test_foreign_overlapping_registration_is_listed_but_changes_neither_class_nor_exposure(builder):
    rival = builder("rival", campaign=OTHER)
    result = classify(res(), rival)
    assert result.classification is Cls.FRESH_UNEXPOSED_DECLARED
    assert result.overlapping_registration_ids == ("rival",)
    assert RC.OVERLAPPING_REGISTRATION in result.reasons
    assert result.established_exposure_ids == () and result.unresolved_source_ids == ()
    assert result.own_anomaly_ids == ()


def test_duplicate_own_reservation_is_an_anomaly_that_gives_undetermined_without_being_a_rival():
    result = classify(res("res_1"), res("res_2"))
    assert result.classification is Cls.UNDETERMINED
    assert result.own_anomaly_ids == ("res_1", "res_2")
    assert result.overlapping_registration_ids == ()
    assert RC.OWN_REGISTRATION_ANOMALY in result.reasons and RC.F1_OWN_ANOMALY in result.conditions[0].reasons


def test_missing_own_reservation_is_an_anomaly():
    result = classify(stage=Stage.RESERVED)
    assert result.classification is Cls.UNDETERMINED
    assert result.own_anomaly_ids == ("missing:RESERVATION",)


def test_own_reservation_with_a_different_window_or_an_unexpected_admission_is_an_anomaly():
    shifted = classify(res(start="2026-11-03T00:00:00.000000Z"))
    assert shifted.classification is Cls.UNDETERMINED and shifted.own_anomaly_ids == ("res_own", )
    unexpected = classify(res(), adm())
    assert unexpected.classification is Cls.UNDETERMINED and unexpected.own_anomaly_ids == ("adm_own",)


def test_n7_a_known_own_claim_with_window_w_is_absorbed_at_the_claimed_stage():
    result = classify(res(), adm(), claim(), stage=Stage.CLAIMED)
    assert result.classification is Cls.FRESH_UNEXPOSED_DECLARED
    assert result.absorbed_own_record_ids == ("adm_own", "claim_own", "res_own")


def test_n7_b_own_claim_with_unknown_window_is_undetermined_never_fresh():
    unresolved = make_unresolved(
        source_id="claim_own", source_kind=K.FINAL_HOLDOUT_CLAIM, campaign_id=CURRENT,
        unresolved_cause=proto.UnresolvedCause.WINDOW_UNKNOWN,
    )
    result = classify(res(), adm(), unresolved, stage=Stage.CLAIMED)
    assert result.classification is Cls.UNDETERMINED
    assert result.unresolved_source_ids == ("claim_own",)
    assert RC.UNRESOLVED_SOURCE in result.reasons and RC.OWN_REGISTRATION_ANOMALY not in result.reasons
    assert result.own_anomaly_ids == ()


def test_n7_c_own_claim_with_a_known_but_different_window_is_conservatively_exposed():
    other_window = claim(start="2026-11-05T00:00:00.000000Z", end="2026-11-06T00:00:00.000000Z")
    result = classify(res(), adm(), other_window, stage=Stage.CLAIMED)
    assert result.classification is Cls.RETROSPECTIVE_EXPOSED
    assert result.established_exposure_ids == ("claim_own",)


def test_n7_c_own_claim_with_a_disjoint_window_and_no_overlap_verdict_is_still_exposed():
    disjoint = claim(start="2026-01-01T00:00:00.000000Z", end="2026-02-01T00:00:00.000000Z",
                     overlap=proto.OverlapVerdict.NO_OVERLAP)
    result = classify(res(), adm(), disjoint, stage=Stage.CLAIMED)
    assert result.classification is Cls.RETROSPECTIVE_EXPOSED


def test_n7_d_a_duplicated_own_claim_is_never_silently_absorbed():
    result = classify(res(), adm(), claim("claim_1"), claim("claim_2"), stage=Stage.CLAIMED)
    assert result.classification is Cls.RETROSPECTIVE_EXPOSED
    assert result.established_exposure_ids == ("claim_1", "claim_2")
    assert result.absorbed_own_record_ids == ("adm_own", "res_own")


def test_n7_e_an_unexpected_own_claim_at_the_reserved_stage_fails_closed():
    result = classify(res(), claim(), stage=Stage.RESERVED)
    assert result.classification is Cls.RETROSPECTIVE_EXPOSED


def test_n7_f_foreign_established_exposure_wins_over_an_unknown_own_claim():
    unresolved = make_unresolved(
        source_id="claim_own", source_kind=K.FINAL_HOLDOUT_CLAIM, campaign_id=CURRENT,
        unresolved_cause=proto.UnresolvedCause.WINDOW_UNKNOWN,
    )
    foreign = make_finding(source_id="evt_overlap", overlap=proto.OverlapVerdict.OVERLAPS,
                           window_start_utc="2026-11-10T00:00:00.000000Z", window_end_utc="2026-11-11T00:00:00.000000Z")
    result = classify(res(), adm(), unresolved, foreign, stage=Stage.CLAIMED)
    assert result.classification is Cls.RETROSPECTIVE_EXPOSED
    assert result.established_exposure_ids == ("evt_overlap",)
    assert result.unresolved_source_ids == ("claim_own",)


def test_own_consumption_unexpected_or_repeated_is_exposed_and_a_legitimate_one_is_absorbed():
    assert classify(res(), consumption(), stage=Stage.RESERVED).classification is Cls.RETROSPECTIVE_EXPOSED
    both = classify(res(), adm(), claim(), consumption("k1"), consumption("k2"), stage=Stage.CONSUMED)
    assert both.classification is Cls.RETROSPECTIVE_EXPOSED and both.established_exposure_ids == ("k1", "k2")
    legit = classify(res(), adm(), claim(), consumption(), stage=Stage.CONSUMED)
    assert legit.classification is Cls.FRESH_UNEXPOSED_DECLARED and legit.own_anomaly_ids == ()


@pytest.mark.parametrize("builder", [consumption, read_intent])
def test_an_unabsorbed_own_exposing_record_exposes_whatever_its_overlap_verdict_is(builder):
    disjoint = builder(start="2026-01-01T00:00:00.000000Z", end="2026-02-01T00:00:00.000000Z",
                       overlap=proto.OverlapVerdict.NO_OVERLAP)
    result = classify(res(), disjoint, stage=Stage.RESERVED)
    assert result.classification is Cls.RETROSPECTIVE_EXPOSED
    assert result.established_exposure_ids == (disjoint.source_id,)


def test_an_unresolved_declared_exposure_gives_undetermined():
    unresolved_declared = make_declared(1, 1, status=proto.SourceStatus.UNRESOLVED)
    result = classify(res(), declaration_specs=({"declared_exposures": (unresolved_declared,)},))
    assert result.classification is Cls.UNDETERMINED
    assert result.unresolved_source_ids == ("declared:0001:0001",)
    assert RC.UNRESOLVED_SOURCE in result.reasons


def test_a_read_intent_of_the_current_campaign_is_never_absorbed():
    result = classify(res(), read_intent(), stage=Stage.RESERVED)
    assert result.classification is Cls.RETROSPECTIVE_EXPOSED
    assert result.established_exposure_ids == ("intent_own",)


def test_an_other_campaign_consumption_is_listed_non_overlapping_without_exposing_the_window():
    foreign = make_finding(source_id="cons_foreign", source_kind=K.CONSUMPTION, campaign_id=OTHER)
    result = classify(res(), foreign)
    assert result.classification is Cls.FRESH_UNEXPOSED_DECLARED


def test_result_inventory_ids_and_digests_match_independent_computation():
    classified = b0()
    result = proto.classify_exposure(classified)
    inventory_id = independent_inventory_id(classified.inventory, absorbed_ids={"res_own"})
    assert result.inventory_id == inventory_id
    assert result.inventory_content_digest == canonical_sha256(
        {"inventory_id": inventory_id, "trial_accounting": accounting_record(ACCOUNTING)}
    )
    assert result.input_digest == independent_input_digest(classified, inventory_id)
    assert result.classification_id == independent_classification_id(result)


def independent_chronology_record(c):
    proof = c.time_proof
    return {
        "commitment_t_sel_utc": c.commitment_t_sel_utc,
        "reservation_durable": c.reservation_durable,
        "time_proof": {
            "status": proof.status.value, "bound_utc": proof.bound_utc,
            "targets_own_reservation": proof.targets_own_reservation,
        },
        "anchor_margin_seconds": c.anchor_margin_seconds,
        "s0_max_time_utc": c.s0_max_time_utc,
        "ingested_at_utc": c.ingested_at_utc,
        "ingestion_range_matches": c.ingestion_range_matches,
    }


def independent_declaration_record(d):
    return {
        "version": d.version, "declaration_seq": d.declaration_seq, "declarant": d.declarant,
        "inventory_id": d.inventory_id, "prev_declaration_id": d.prev_declaration_id,
        "declared_t_sel_utc": d.declared_t_sel_utc,
        "declared_exposures": [finding_record(f) for f in d.declared_exposures],
        "declared_trial_counts": accounting_record(d.declared_trial_counts),
    }


def independent_input_digest(ci, inventory_id):
    return canonical_sha256({
        "rules_version": "gate_v_exposure_classification_v1",
        "inventory_id": inventory_id,
        "current_campaign_id": ci.own_context.current_campaign_id,
        "declarations": [independent_declaration_record(d) for d in ci.declarations.declarations],
        "hash_linked": ci.declarations.hash_linked,
        "chronology": independent_chronology_record(ci.chronology),
    })


def independent_classification_id(result):
    return canonical_sha256({
        "rules_version": result.rules_version,
        "input_digest": result.input_digest,
        "classification": result.classification.value,
        "chronology_level": result.chronology_level.value,
        "t_sel_effective_utc": result.t_sel_effective_utc,
        "t_sel_lowering_ignored_seqs": list(result.t_sel_lowering_ignored_seqs),
        "established_exposure_ids": list(result.established_exposure_ids),
        "unresolved_source_ids": list(result.unresolved_source_ids),
        "overlapping_registration_ids": list(result.overlapping_registration_ids),
        "own_anomaly_ids": list(result.own_anomaly_ids),
        "conditions": [
            {"condition": c.condition, "status": c.status.value, "reasons": [r.value for r in c.reasons]}
            for c in result.conditions
        ],
        "reasons": [r.value for r in result.reasons],
    })


def test_classify_exposure_rejects_a_non_input_with_type_error():
    with pytest.raises(TypeError):
        proto.classify_exposure("input")


# ============================================================================================
# Tranche 8 — conditions F2 à F6 (tri-états) et niveau chronologique
# ============================================================================================

CS = proto.ConditionStatus
MET, NOT_MET, UNVERIFIED = CS.MET, CS.NOT_MET, CS.UNVERIFIED


def cond(result, code):
    return next(c for c in result.conditions if c.condition == code)


def run(chronology):
    """Classification de B0 avec une chronologie donnée."""
    return classify(res(), chronology=chronology)


def chron(**overrides):
    return make_chronology(**overrides)


def at(instant, delta_seconds):
    from datetime import datetime, timedelta, timezone

    base = datetime.strptime(instant, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return (base + timedelta(seconds=delta_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def test_b0_has_all_six_conditions_met_no_reason_and_is_prospective_anchored():
    result = classify(res())
    assert [c.status for c in result.conditions] == [MET] * 6
    assert result.reasons == ()
    assert result.classification is Cls.FRESH_UNEXPOSED_DECLARED
    assert result.chronology_level is proto.ChronologyLevel.PROSPECTIVE_ANCHORED
    assert result.t_sel_effective_utc == T_SEL
    assert result.t_sel_lowering_ignored_seqs == ()


# ---- F3 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "s0_max, status, reasons",
    [
        (None, UNVERIFIED, (RC.F3_S0_MAX_TIME_MISSING,)),
        (at(WS, -1e-6), MET, ()),                       # juste avant ws
        (WS, NOT_MET, (RC.F3_S0_NOT_BEFORE_WINDOW,)),   # == ws : refusé (strictement inférieur exigé)
        (at(WS, 1), NOT_MET, (RC.F3_S0_NOT_BEFORE_WINDOW,)),
        ("2025-01-01T00:00:00.000000Z", MET, ()),
    ],
)
def test_f3_requires_s0_max_time_strictly_before_ws(s0_max, status, reasons):
    result = run(chron(s0_max_time_utc=s0_max))
    assert cond(result, "F3").status is status
    assert cond(result, "F3").reasons == reasons


# ---- F4 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, status, reasons",
    [
        (dict(reservation_durable=None), UNVERIFIED, (RC.F4_RESERVATION_UNKNOWN,)),
        (dict(reservation_durable=False), NOT_MET, (RC.F4_RESERVATION_NOT_DURABLE,)),
        (dict(time_proof=no_proof(proto.TimeProofStatus.ABSENT)), UNVERIFIED, (RC.F4_PROOF_ABSENT,)),
        (dict(time_proof=no_proof(proto.TimeProofStatus.UNVERIFIABLE)), UNVERIFIED, (RC.F4_PROOF_UNVERIFIABLE,)),
        (dict(time_proof=no_proof(proto.TimeProofStatus.INVALID)), NOT_MET, (RC.F4_PROOF_INVALID,)),
        (dict(time_proof=valid_proof(own=False)), NOT_MET, (RC.F4_PROOF_NOT_OWN_RESERVATION,)),
        (dict(anchor_margin_seconds=None), UNVERIFIED, (RC.F4_MARGIN_MISSING,)),
        (dict(anchor_margin_seconds=0), UNVERIFIED, (RC.F4_MARGIN_NOT_POSITIVE,)),
        (dict(anchor_margin_seconds=8 * DAY), MET, ()),                                   # borne + marge == ws
        (dict(anchor_margin_seconds=8 * DAY + 1), NOT_MET, (RC.F4_ANCHORED_TOO_LATE,)),   # borne + marge > ws
        (dict(time_proof=valid_proof(bound=at(WS, 1)), anchor_margin_seconds=None), NOT_MET,
         (RC.F4_MARGIN_MISSING, RC.F4_ANCHORED_TOO_LATE)),                                # borne > ws sans marge
        (dict(time_proof=valid_proof(bound=WS), anchor_margin_seconds=1), NOT_MET, (RC.F4_ANCHORED_TOO_LATE,)),
    ],
)
def test_f4_reservation_proof_and_margin_rules(overrides, status, reasons):
    result = run(chron(**overrides))
    assert cond(result, "F4").status is status
    assert cond(result, "F4").reasons == reasons


@pytest.mark.parametrize("margin", [10**13, 3 * 10**11, 9 * 10**13, 10**18])
def test_f4_a_huge_margin_is_a_late_anchor_and_never_an_overflow(margin):
    result = run(chron(anchor_margin_seconds=margin))
    assert cond(result, "F4").status is NOT_MET
    assert cond(result, "F4").reasons == (RC.F4_ANCHORED_TOO_LATE,)


@pytest.mark.parametrize("margin", [-1, -86400, -(10**18)])
def test_f4_a_negative_margin_is_not_positive_hence_unverified(margin):
    result = run(chron(anchor_margin_seconds=margin))
    assert cond(result, "F4").status is UNVERIFIED
    assert cond(result, "F4").reasons == (RC.F4_MARGIN_NOT_POSITIVE,)


def test_f4_cumulates_reasons_and_known_violation_beats_missing_data():
    result = run(chron(reservation_durable=False, time_proof=no_proof(proto.TimeProofStatus.INVALID),
                       anchor_margin_seconds=None))
    f4 = cond(result, "F4")
    assert f4.status is NOT_MET
    assert f4.reasons == (RC.F4_RESERVATION_NOT_DURABLE, RC.F4_PROOF_INVALID)  # pas de marge jugée sans preuve valide
    mixed = run(chron(reservation_durable=None, time_proof=no_proof(proto.TimeProofStatus.INVALID)))
    assert cond(mixed, "F4").status is NOT_MET
    assert cond(mixed, "F4").reasons == (RC.F4_RESERVATION_UNKNOWN, RC.F4_PROOF_INVALID)


# ---- F5 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, status, reasons",
    [
        (dict(ingested_at_utc=None), UNVERIFIED, (RC.F5_INGESTION_MISSING,)),
        (dict(ingestion_range_matches=None), UNVERIFIED, (RC.F5_INGESTION_MISSING,)),
        (dict(ingested_at_utc=WE), NOT_MET, (RC.F5_INGESTED_BEFORE_WINDOW_END,)),            # == we : refusé
        (dict(ingested_at_utc=at(WE, 1)), MET, ()),
        (dict(ingested_at_utc=at(WE, -1)), NOT_MET, (RC.F5_INGESTED_BEFORE_WINDOW_END,)),
        (dict(ingestion_range_matches=False), NOT_MET, (RC.F5_RANGE_MISMATCH,)),
        (dict(ingested_at_utc=WE, ingestion_range_matches=False), NOT_MET,
         (RC.F5_INGESTED_BEFORE_WINDOW_END, RC.F5_RANGE_MISMATCH)),
        (dict(ingested_at_utc=None, ingestion_range_matches=False), NOT_MET, (RC.F5_INGESTION_MISSING, RC.F5_RANGE_MISMATCH)),
    ],
)
def test_f5_ingestion_after_we_and_committed_range(overrides, status, reasons):
    result = run(chron(**overrides))
    assert cond(result, "F5").status is status
    assert cond(result, "F5").reasons == reasons


# ---- F6 ---------------------------------------------------------------------------------------


def test_f6_requires_the_declarations_to_be_hash_linked():
    result = classify(res(), hash_linked=False)
    assert cond(result, "F6").status is NOT_MET
    assert cond(result, "F6").reasons == (RC.F6_HASH_LINK_BROKEN,)
    assert result.classification is Cls.FRESH_UNEXPOSED_DECLARED
    assert result.chronology_level is proto.ChronologyLevel.UNSEEN_HISTORICAL


# ---- F2 ---------------------------------------------------------------------------------------


def exposure(source_id, start, end, overlap=proto.OverlapVerdict.NO_OVERLAP):
    return make_finding(source_id=source_id, window_start_utc=start, window_end_utc=end, overlap=overlap)


def test_f2_exposure_ending_exactly_at_ws_is_accepted_and_later_is_not():
    ends_at_ws = exposure("evt_a", "2026-10-01T00:00:00.000000Z", WS)
    assert cond(classify(res(), ends_at_ws), "F2").status is MET
    after = exposure("evt_b", "2026-12-15T00:00:00.000000Z", "2027-01-01T00:00:00.000000Z")   # futur, sans recouvrement
    result = classify(res(), after)
    assert cond(result, "F2").status is NOT_MET and cond(result, "F2").reasons == (RC.F2_EXPOSURE_AFTER_WS,)
    assert result.classification is Cls.FRESH_UNEXPOSED_DECLARED
    assert result.chronology_level is proto.ChronologyLevel.UNSEEN_HISTORICAL


def test_f2_declared_exposure_after_ws_is_taken_into_account():
    declared = make_declared(1, 1, start="2026-12-15T00:00:00.000000Z", end="2027-01-01T00:00:00.000000Z")
    result = classify(res(), declaration_specs=({"declared_exposures": (declared,)},))
    assert cond(result, "F2").reasons == (RC.F2_EXPOSURE_AFTER_WS,)


def test_f2_unresolved_exposing_or_unknown_capability_source_is_a_missing_window():
    for source in (make_unresolved(source_id="evt_u"), make_unresolved(source_id="u2", source_kind=K.UNKNOWN_SOURCE)):
        result = classify(res(), source)
        assert cond(result, "F2").status is UNVERIFIED
        assert cond(result, "F2").reasons == (RC.F2_EXPOSURE_WINDOW_UNKNOWN,)


def test_f2_unresolved_non_exposing_registry_record_does_not_affect_f2():
    unresolved_registry = make_unresolved(source_id="r_u", source_kind=K.REGISTRY_RESERVATION, campaign_id=OTHER)
    result = classify(res(), unresolved_registry)
    assert cond(result, "F2").status is MET
    assert result.classification is Cls.UNDETERMINED


def test_f2_known_violation_beats_missing_window():
    result = classify(res(), exposure("evt_b", "2026-12-15T00:00:00.000000Z", "2027-01-01T00:00:00.000000Z"),
                      make_unresolved(source_id="evt_u"))
    assert cond(result, "F2").status is NOT_MET
    assert cond(result, "F2").reasons == (RC.F2_EXPOSURE_WINDOW_UNKNOWN, RC.F2_EXPOSURE_AFTER_WS)


@pytest.mark.parametrize(
    "t_sel, status, reasons",
    [
        (T_ANCHOR, MET, ()),                                                # t_sel == t_anchor
        (at(T_ANCHOR, 1), NOT_MET, (RC.F2_T_SEL_AFTER_ANCHOR,)),            # entre t_anchor et ws
        (WS, NOT_MET, (RC.F2_T_SEL_AFTER_ANCHOR,)),                         # == ws : accepté pour ws mais > t_anchor
        (at(WS, 1), NOT_MET, (RC.F2_T_SEL_AFTER_WS, RC.F2_T_SEL_AFTER_ANCHOR)),
        (None, UNVERIFIED, (RC.F2_T_SEL_MISSING,)),
    ],
)
def test_f2_t_sel_must_not_exceed_ws_nor_the_anchor(t_sel, status, reasons):
    result = run(chron(commitment_t_sel_utc=t_sel))
    assert cond(result, "F2").status is status
    assert cond(result, "F2").reasons == reasons


def test_f2_without_a_usable_anchor_is_unverified_but_a_t_sel_after_ws_is_still_a_violation():
    for proof in (no_proof(), no_proof(proto.TimeProofStatus.INVALID), valid_proof(own=False)):
        result = run(chron(time_proof=proof))
        assert cond(result, "F2").status is UNVERIFIED
        assert cond(result, "F2").reasons == (RC.F2_ANCHOR_UNKNOWN,)
    late = run(chron(time_proof=no_proof(), commitment_t_sel_utc=at(WS, 1)))
    assert cond(late, "F2").status is NOT_MET
    assert cond(late, "F2").reasons == (RC.F2_ANCHOR_UNKNOWN, RC.F2_T_SEL_AFTER_WS)


def test_declarations_can_push_t_sel_later_and_a_pushed_value_beyond_the_anchor_breaks_f2():
    ok = classify(res(), declaration_specs=({"declared_t_sel_utc": T_ANCHOR},))
    assert ok.t_sel_effective_utc == T_ANCHOR and cond(ok, "F2").status is MET
    late = classify(res(), declaration_specs=({"declared_t_sel_utc": at(T_ANCHOR, 3600)},))
    assert late.t_sel_effective_utc == at(T_ANCHOR, 3600)
    assert cond(late, "F2").reasons == (RC.F2_T_SEL_AFTER_ANCHOR,)


def test_a_declaration_that_lowers_t_sel_is_ignored_listed_and_reported():
    result = classify(res(), declaration_specs=({}, {"declared_t_sel_utc": "2026-10-01T00:00:00.000000Z"}))
    assert result.t_sel_effective_utc == T_SEL
    assert result.t_sel_lowering_ignored_seqs == (2,)
    assert RC.T_SEL_LOWERING_IGNORED in result.reasons
    assert cond(result, "F2").status is MET
    assert result.classification is Cls.FRESH_UNEXPOSED_DECLARED
    # non bloquant pour le niveau, qui reste fonction des seules conditions F1..F6
    assert result.chronology_level is proto.ChronologyLevel.PROSPECTIVE_ANCHORED


def test_the_t_sel_effective_is_never_lowered_by_adding_declarations():
    one = classify(res(), declaration_specs=({"declared_t_sel_utc": T_ANCHOR},))
    two = classify(res(), declaration_specs=({"declared_t_sel_utc": T_ANCHOR}, {"declared_t_sel_utc": T_SEL}))
    assert two.t_sel_effective_utc == one.t_sel_effective_utc == T_ANCHOR


# ---- niveau chronologique ---------------------------------------------------------------------


def test_chronology_level_follows_the_six_conditions_and_the_class():
    anchored = classify(res())
    assert anchored.chronology_level is proto.ChronologyLevel.PROSPECTIVE_ANCHORED
    for overrides in (dict(s0_max_time_utc=WS), dict(ingestion_range_matches=None), dict(reservation_durable=False)):
        result = run(chron(**overrides))
        assert result.classification is Cls.FRESH_UNEXPOSED_DECLARED
        assert result.chronology_level is proto.ChronologyLevel.UNSEEN_HISTORICAL
    exposed = classify(res(), exposure("evt_o", "2026-11-10T00:00:00.000000Z", "2026-11-11T00:00:00.000000Z",
                                       overlap=proto.OverlapVerdict.OVERLAPS))
    assert exposed.chronology_level is proto.ChronologyLevel.NOT_APPLICABLE


# ============================================================================================
# Tranche 9 — refus d'admission et enregistrement JSON du résultat
# ============================================================================================

AR = proto.AdmissionRefusal


def overlapping_exposure():
    return exposure("evt_o", "2026-11-10T00:00:00.000000Z", "2026-11-11T00:00:00.000000Z",
                    overlap=proto.OverlapVerdict.OVERLAPS)


def test_admission_refusals_is_empty_only_for_fresh_and_prospective_anchored_without_rival():
    refusals = proto.admission_refusals(classify(res()))
    assert refusals == () and type(refusals) is tuple


def test_admission_refusals_gives_a_class_refusal_first_and_then_the_level_refusal_only_otherwise():
    assert proto.admission_refusals(classify(res(), overlapping_exposure())) == (AR.CLASS_RETROSPECTIVE_EXPOSED,)
    assert proto.admission_refusals(classify(res(), make_unresolved(source_id="evt_u"))) == (AR.CLASS_UNDETERMINED,)
    unseen = classify(res(), hash_linked=False)
    assert proto.admission_refusals(unseen) == (AR.LEVEL_NOT_PROSPECTIVE_ANCHORED,)


def test_a_rival_registration_adds_the_overlapping_refusal_without_changing_the_class():
    anchored_with_rival = classify(res(), res("rival", campaign=OTHER))
    assert anchored_with_rival.classification is Cls.FRESH_UNEXPOSED_DECLARED
    assert anchored_with_rival.chronology_level is proto.ChronologyLevel.PROSPECTIVE_ANCHORED
    assert proto.admission_refusals(anchored_with_rival) == (AR.OVERLAPPING_REGISTRATION,)
    retro = classify(res(), res("rival", campaign=OTHER), overlapping_exposure())
    assert proto.admission_refusals(retro) == (AR.CLASS_RETROSPECTIVE_EXPOSED, AR.OVERLAPPING_REGISTRATION)
    unseen = classify(res(), res("rival", campaign=OTHER), hash_linked=False)
    assert proto.admission_refusals(unseen) == (AR.LEVEL_NOT_PROSPECTIVE_ANCHORED, AR.OVERLAPPING_REGISTRATION)


def test_an_empty_refusal_tuple_is_documented_as_never_an_authorization_even_at_late_stages():
    doc = proto.admission_refusals.__doc__ or ""
    assert "jamais" in doc and "autorisation" in doc
    consumed = classify(res(), adm(), claim(), consumption(), stage=Stage.CONSUMED)
    assert proto.admission_refusals(consumed) == ()   # audit seulement : l'unicité du registre et E2 restent l'autorité
    assert not any("authoriz" in name.lower() or "allowed" in name.lower() for name in dir(proto)
                   if not name.startswith("_"))


def test_admission_refusals_rejects_a_non_result():
    with pytest.raises(TypeError):
        proto.admission_refusals("result")


def test_classification_result_to_record_is_a_json_serializable_dict_of_the_sixteen_fields():
    result = classify(res(), declaration_specs=({}, {"declared_t_sel_utc": "2026-10-01T00:00:00.000000Z"}))
    record = proto.classification_result_to_record(result)
    assert list(record) == [f.name for f in dataclasses.fields(proto.ExposureClassificationResult)]
    assert record["classification"] == "FRESH_UNEXPOSED_DECLARED"
    assert record["chronology_level"] == "PROSPECTIVE_ANCHORED"
    assert record["t_sel_lowering_ignored_seqs"] == [2]
    assert record["absorbed_own_record_ids"] == ["res_own"]
    assert record["conditions"][0] == {"condition": "F1", "status": "MET", "reasons": []}
    assert record["reasons"] == ["T_SEL_LOWERING_IGNORED"]
    assert json.loads(json.dumps(record)) == record
    assert proto.classification_result_to_record(result) == record


def test_classification_result_to_record_rejects_a_non_result():
    with pytest.raises(TypeError):
        proto.classification_result_to_record({"classification": "FRESH_UNEXPOSED_DECLARED"})


# ============================================================================================
# Tranche 10 — identités, digests, stabilité entre étages, vecteurs SHA-256 indépendants
# ============================================================================================

EMPTY_LIST_SHA256 = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"


def test_the_empty_canonical_list_vector_is_the_sha256_of_two_brackets_independently():
    assert hashlib.sha256(b"[]").hexdigest() == EMPTY_LIST_SHA256


def test_static_sources_digest_and_overlap_projection_are_the_empty_list_hash_for_b0():
    inventory, context = b0().inventory, b0().own_context
    assert proto.compute_static_sources_digest(inventory, context) == EMPTY_LIST_SHA256
    assert proto.compute_overlap_projection_hash(inventory, context) == EMPTY_LIST_SHA256


def relevant_fixture():
    rival = res("rival", campaign=OTHER, content_hash=H1)
    unreadable = make_unresolved(source_id="registry_x", source_kind=K.REGISTRY_UNREADABLE)
    unrelated = make_finding(source_id="evt_x", content_hash=H2)       # NO_OVERLAP : hors ensemble pertinent
    unresolved_event = make_unresolved(source_id="evt_u", content_hash=H1)
    return make_inventory(res(), rival, unreadable, unrelated, unresolved_event), ctx(Stage.RESERVED)


def test_static_sources_digest_covers_the_relevant_set_with_id_and_content_hash_only():
    inventory, context = relevant_fixture()
    expected = canonical_sha256([
        {"source_id": "evt_u", "content_hash": H1},
        {"source_id": "registry_x", "content_hash": None},
        {"source_id": "rival", "content_hash": H1},
    ])
    assert proto.compute_static_sources_digest(inventory, context) == expected
    # un ajout sans rapport avec W ne la modifie pas
    with_unrelated = make_inventory(*inventory.findings, make_finding(source_id="evt_z"))
    assert proto.compute_static_sources_digest(with_unrelated, context) == expected


def test_overlap_projection_covers_foreign_registry_records_overlapping_or_unreadable():
    inventory, context = relevant_fixture()
    expected = canonical_sha256([
        {"source_id": "registry_x", "content_hash": None, "source_kind": "REGISTRY_UNREADABLE"},
        {"source_id": "rival", "content_hash": H1, "source_kind": "REGISTRY_RESERVATION"},
    ])
    assert proto.compute_overlap_projection_hash(inventory, context) == expected


def test_an_unreadable_registry_record_is_always_part_of_the_projection_whatever_campaign_it_claims():
    unreadable_current = make_unresolved(source_id="registry_x", source_kind=K.REGISTRY_UNREADABLE, campaign_id=CURRENT)
    inventory = make_inventory(unreadable_current)
    expected = canonical_sha256([{"source_id": "registry_x", "content_hash": None, "source_kind": "REGISTRY_UNREADABLE"}])
    assert proto.compute_overlap_projection_hash(inventory, ctx(Stage.NO_OWN_RECORDS)) == expected


def test_own_unabsorbed_registry_records_are_never_part_of_the_projection():
    inventory = make_inventory(res("res_1"), res("res_2"))
    assert proto.compute_overlap_projection_hash(inventory, ctx(Stage.RESERVED)) == EMPTY_LIST_SHA256


def test_static_digest_and_projection_ignore_absorbed_own_records_at_every_stage():
    foreign = res("rival", campaign=OTHER)
    reference = None
    for stage, records in (
        (Stage.RESERVED, (res(),)), (Stage.ADMITTED, (res(), adm())),
        (Stage.CLAIMED, (res(), adm(), claim())), (Stage.CONSUMED, (res(), adm(), claim(), consumption())),
    ):
        inventory = make_inventory(*records, foreign)
        pair = (
            proto.compute_static_sources_digest(inventory, ctx(stage)),
            proto.compute_overlap_projection_hash(inventory, ctx(stage)),
        )
        reference = reference or pair
        assert pair == reference


CONTEXT_AWARE_FUNCTIONS = [
    lambda inventory, context: proto.partition_own_records(inventory, context),
    proto.compute_exposure_inventory_id,
    proto.compute_inventory_content_digest,
    proto.compute_static_sources_digest,
    proto.compute_overlap_projection_hash,
]


@pytest.mark.parametrize("function", CONTEXT_AWARE_FUNCTIONS)
@pytest.mark.parametrize("builder", [res, adm])
def test_every_context_aware_function_refuses_a_foreign_non_overlapping_registry_record(function, builder):
    disjoint = builder("rival", campaign=OTHER, start="2026-01-01T00:00:00.000000Z",
                       end="2026-02-01T00:00:00.000000Z", overlap=proto.OverlapVerdict.NO_OVERLAP)
    inventory = make_inventory(res(), disjoint)
    with pytest.raises(ValueError):
        function(inventory, ctx(Stage.RESERVED))


@pytest.mark.parametrize("function", CONTEXT_AWARE_FUNCTIONS)
def test_every_context_aware_function_accepts_listable_inventories(function):
    overlapping_rival = res("rival", campaign=OTHER)
    unresolved_rival = make_unresolved(source_id="rival_u", source_kind=K.REGISTRY_RESERVATION, campaign_id=OTHER)
    own_disjoint = res(start="2026-01-01T00:00:00.000000Z", end="2026-02-01T00:00:00.000000Z",
                       overlap=proto.OverlapVerdict.NO_OVERLAP)
    for findings in ((res(), overlapping_rival), (res(), unresolved_rival), (own_disjoint,)):
        function(make_inventory(*findings), ctx(Stage.RESERVED))


def test_a_listability_failure_can_never_yield_an_inventory_id_that_classification_would_refuse():
    disjoint = res("rival", campaign=OTHER, start="2026-01-01T00:00:00.000000Z", end="2026-02-01T00:00:00.000000Z",
                   overlap=proto.OverlapVerdict.NO_OVERLAP)
    inventory = make_inventory(res(), disjoint)
    with pytest.raises(ValueError):
        proto.compute_exposure_inventory_id(inventory, ctx(Stage.RESERVED))   # pas d'identité attestable
    with pytest.raises(ValueError):
        make_input(res(), disjoint)                                            # et la classification le refuse aussi


def test_digest_functions_reject_bad_arguments_with_type_error():
    inventory, context = relevant_fixture()
    for function in (proto.compute_static_sources_digest, proto.compute_overlap_projection_hash,
                     proto.compute_inventory_content_digest, proto.compute_exposure_inventory_id):
        with pytest.raises(TypeError):
            function("inventory", context)
        with pytest.raises(TypeError):
            function(inventory, "context")
    with pytest.raises(TypeError):
        proto.compute_classification_input_digest("input")
    with pytest.raises(TypeError):
        proto.compute_declaration_id("declaration")


def test_each_trial_accounting_counter_changes_only_the_content_digest():
    base = classify(res())
    for name in ("research_runs", "strategies", "campaigns", "abandoned_reservations",
                 "failed_ingestion_attempts", "void_commitments"):
        values = dataclasses.asdict(ACCOUNTING)
        values[name] += 1
        changed = classify(res(), trial_accounting=proto.TrialAccounting(**values))
        assert changed.inventory_content_digest != base.inventory_content_digest
        assert changed.inventory_id == base.inventory_id
        assert changed.input_digest == base.input_digest
        assert changed.classification == base.classification
        assert changed.classification_id == base.classification_id


def test_a_foreign_non_overlapping_consumption_changes_inventory_id_but_not_the_class():
    base = classify(res())
    foreign = make_finding(source_id="cons_foreign", source_kind=K.CONSUMPTION, campaign_id=OTHER)
    changed = classify(res(), foreign)
    assert changed.inventory_id != base.inventory_id
    assert changed.classification is base.classification is Cls.FRESH_UNEXPOSED_DECLARED


def test_the_same_exposure_under_two_snapshot_ids_has_the_same_class_and_two_inventory_ids():
    one = classify(res(), exposure("evt_o", "2026-11-10T00:00:00.000000Z", "2026-11-11T00:00:00.000000Z",
                                   overlap=proto.OverlapVerdict.OVERLAPS))
    other_snapshot = make_finding(source_id="evt_o", snapshot_id="snap_2", overlap=proto.OverlapVerdict.OVERLAPS,
                                  window_start_utc="2026-11-10T00:00:00.000000Z",
                                  window_end_utc="2026-11-11T00:00:00.000000Z")
    two = classify(res(), other_snapshot)
    assert one.classification is two.classification is Cls.RETROSPECTIVE_EXPOSED
    assert one.inventory_id != two.inventory_id


def test_legitimate_stages_share_every_scientific_identity_and_only_absorbed_ids_differ():
    foreign = make_finding(source_id="evt_x")
    by_stage = {
        Stage.RESERVED: classify(res(), foreign, stage=Stage.RESERVED),
        Stage.ADMITTED: classify(res(), adm(), foreign, stage=Stage.ADMITTED),
        Stage.CLAIMED: classify(res(), adm(), claim(), foreign, stage=Stage.CLAIMED),
        Stage.CONSUMED: classify(res(), adm(), claim(), consumption(), foreign, stage=Stage.CONSUMED),
    }
    reference = by_stage[Stage.RESERVED]
    for stage, result in by_stage.items():
        assert result.classification is Cls.FRESH_UNEXPOSED_DECLARED
        assert [c.status for c in result.conditions] == [MET] * 6
        assert result.inventory_id == reference.inventory_id
        assert result.inventory_content_digest == reference.inventory_content_digest
        assert result.input_digest == reference.input_digest
        assert result.classification_id == reference.classification_id
        assert result.reasons == reference.reasons
    assert [len(by_stage[s].absorbed_own_record_ids) for s in (Stage.RESERVED, Stage.ADMITTED, Stage.CLAIMED,
                                                                 Stage.CONSUMED)] == [1, 2, 3, 4]
    assert by_stage[Stage.CONSUMED].absorbed_own_record_ids == ("adm_own", "claim_own", "cons_own", "res_own")


def test_an_unabsorbable_own_record_makes_the_inventory_id_differ_between_stages_fail_closed():
    unresolved_claim = make_unresolved(
        source_id="claim_own", source_kind=K.FINAL_HOLDOUT_CLAIM, campaign_id=CURRENT,
        unresolved_cause=proto.UnresolvedCause.WINDOW_UNKNOWN,
    )
    admitted = classify(res(), adm(), stage=Stage.ADMITTED)
    claimed = classify(res(), adm(), unresolved_claim, stage=Stage.CLAIMED)
    assert admitted.inventory_id != claimed.inventory_id   # 23.27.6 : exception documentée, échec fermé


def test_classification_is_independent_of_the_input_order_of_findings():
    import itertools

    findings = [
        exposure("evt_a", "2026-01-01T00:00:00.000000Z", "2026-02-01T00:00:00.000000Z"),
        make_unresolved(source_id="evt_b"),
        res("rival", campaign=OTHER),
        res(),
    ]
    results = []
    for permutation in itertools.permutations(findings):
        inventory = proto.build_exposure_inventory(
            window_start_utc=WS, window_end_utc=WE, findings=list(permutation), complete=True,
            scanned_roots=["results"], trial_accounting=ACCOUNTING,
        )
        context = ctx(Stage.RESERVED)
        inventory_id = proto.compute_exposure_inventory_id(inventory, context)
        declaration = make_declaration(inventory_id=inventory_id)
        classification_input = proto.ClassificationInput(
            inventory=inventory, declarations=proto.DeclarationSet(declarations=(declaration,), hash_linked=True),
            chronology=make_chronology(), own_context=context,
        )
        results.append(proto.classification_result_to_record(proto.classify_exposure(classification_input)))
    assert all(record == results[0] for record in results)


def test_adding_declarations_never_lowers_the_class_severity_nor_the_effective_t_sel():
    severity = {Cls.FRESH_UNEXPOSED_DECLARED: 0, Cls.UNDETERMINED: 1, Cls.RETROSPECTIVE_EXPOSED: 2}
    unresolved_declared = make_declared(2, 1, start="2026-01-01T00:00:00.000000Z", end="2026-02-01T00:00:00.000000Z",
                                        status=proto.SourceStatus.UNRESOLVED)
    established_declared = make_declared(3, 1, start="2026-11-10T00:00:00.000000Z", end="2026-11-11T00:00:00.000000Z",
                                         overlap=proto.OverlapVerdict.OVERLAPS)
    specs = (
        {"declared_t_sel_utc": T_SEL},
        {"declared_exposures": (unresolved_declared,), "declared_t_sel_utc": T_ANCHOR},
        {"declared_exposures": (established_declared,), "declared_t_sel_utc": T10},   # tente d'abaisser : ignoré
    )
    previous_severity, previous_t_sel = -1, None
    for count in range(1, len(specs) + 1):
        result = classify(res(), declaration_specs=specs[:count])
        assert severity[result.classification] >= previous_severity
        if previous_t_sel is not None:
            assert result.t_sel_effective_utc >= previous_t_sel
        previous_severity, previous_t_sel = severity[result.classification], result.t_sel_effective_utc
    assert previous_severity == 2 and previous_t_sel == T_ANCHOR


def test_identities_are_deterministic_and_match_frozen_independent_vectors():
    first, second = proto.classify_exposure(b0()), proto.classify_exposure(b0())
    assert first == second and proto.classification_result_to_record(first) == proto.classification_result_to_record(second)
    assert first.inventory_id == FROZEN["inventory_id"]
    assert first.inventory_content_digest == FROZEN["inventory_content_digest"]
    assert first.input_digest == FROZEN["input_digest"]
    assert first.classification_id == FROZEN["classification_id"]
    declaration = b0().declarations.declarations[0]
    assert proto.compute_declaration_id(declaration) == FROZEN["declaration_id"]


# Vecteurs littéraux du scénario B0, calculés HORS du module testé (hashlib + json, fonctions `independent_*` ci-dessus).
FROZEN = {
    "inventory_id": "5fa767f391c159a20b5b034e6128e0e55c98731ddaf0efbb6455762f09d0e01f",
    "inventory_content_digest": "f814e0d09432950e3cbbfcb9a6f493653929fcc7b31a743cacd36207868b54c9",
    "input_digest": "ebf30751c2590ab9d73b5db5099f71b165e3370cc0d92f67c942309d11bdf9af",
    "classification_id": "410e26b819d8997e73043cdeef3367bc2de0fb213a44e01197b693d34806d075",
    "declaration_id": "9aa8fcada2710183ebea4dda44f64680b19867fd9fe37db100fc6ad0177cb23a",
}


# ============================================================================================
# Tranche 11 — pureté (AST), immutabilité, comptes publics et canonicalisation
# ============================================================================================

ALLOWED_IMPORTS = {"__future__", "dataclasses", "datetime", "enum", "hashlib", "json", "re", "typing"}
FORBIDDEN_CALL_NAMES = {"open", "print", "input", "exec", "eval", "__import__", "compile"}
FORBIDDEN_ATTRIBUTES = {"now", "utcnow", "today", "time", "monotonic", "perf_counter", "environ", "getenv", "urlopen"}


def purity_violations(source: str) -> list[str]:
    """Violations de pureté d'un module : imports hors liste blanche stdlib, appels d'E/S, lecture d'horloge."""
    violations = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                violations.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALL_NAMES:
                violations.append(f"call {func.id}()")
            if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_ATTRIBUTES:
                violations.append(f"call .{func.attr}()")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTES - {"time"}:
            violations.append(f"attribute .{node.attr}")
    return violations


@pytest.mark.parametrize(
    "bad_source",
    [
        "import os",
        "import time",
        "import subprocess",
        "import socket",
        "import pathlib",
        "from pathlib import Path",
        "import gate_v_final_holdout_claim_acquisition",
        "from gate_v_final_holdout_claim import FinalHoldoutAccessClaim",
        "import engine",
        "import validation_oos",
        "import streamlit",
        "import pandas",
        "from . import x",
        "x = open('file')",
        "from datetime import datetime\nx = datetime.now()",
        "import datetime\nx = datetime.datetime.utcnow()",
        "import json\nx = json.load(open('f'))",
    ],
)
def test_the_purity_checker_detects_forbidden_dependencies_and_io(bad_source):
    assert purity_violations(bad_source) != []


def test_the_purity_checker_accepts_a_pure_standard_library_module():
    assert purity_violations("import hashlib\nimport json\nfrom dataclasses import dataclass\nx = 1") == []


def test_the_protocol_module_is_pure_standard_library_only_without_io_or_clock():
    source = _MODULE_PATH.read_text(encoding="utf-8")
    assert purity_violations(source) == []
    imported = {
        alias.name.split(".")[0] for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0] for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
    }
    assert imported <= ALLOWED_IMPORTS


def test_the_protocol_module_does_not_reference_e1_e2_the_engine_or_the_registry_apis():
    source = _MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "gate_v_final_holdout_claim", "acquire_final_holdout_access_claim", "save_exclusive", "run_oos_validation",
        "run_backtest", "streamlit", "O_EXCL", "os.link", "fsync",
    ):
        assert forbidden not in source, forbidden


def test_there_are_exactly_eleven_frozen_dataclasses_and_sixteen_public_functions():
    import inspect

    classes = [
        obj for obj in vars(proto).values()
        if dataclasses.is_dataclass(obj) and isinstance(obj, type) and obj.__module__ == proto.__name__
    ]
    assert len(classes) == 11
    assert all(cls.__dataclass_params__.frozen for cls in classes)
    public_functions = sorted(
        name for name, obj in vars(proto).items()
        if inspect.isfunction(obj) and obj.__module__ == proto.__name__ and not name.startswith("_")
    )
    assert public_functions == sorted([
        "normalize_utc_instant", "build_exposure_finding", "build_exposure_inventory", "build_exposure_declaration",
        "build_chronology_facts", "partition_own_records", "compute_exposure_inventory_id",
        "compute_inventory_content_digest", "compute_declaration_id", "compute_classification_input_digest",
        "compute_static_sources_digest", "compute_overlap_projection_hash", "compute_effective_t_sel",
        "classify_exposure", "admission_refusals", "classification_result_to_record",
    ])


def test_every_collection_field_of_every_result_is_an_immutable_tuple():
    result = classify(res(), res("rival", campaign=OTHER), make_unresolved(source_id="evt_u"))
    for name in ("t_sel_lowering_ignored_seqs", "established_exposure_ids", "unresolved_source_ids",
                 "overlapping_registration_ids", "absorbed_own_record_ids", "own_anomaly_ids", "conditions", "reasons"):
        assert type(getattr(result, name)) is tuple, name
    for condition in result.conditions:
        assert type(condition.reasons) is tuple
        with pytest.raises(dataclasses.FrozenInstanceError):
            condition.status = MET  # type: ignore[misc]
    inputs = b0()
    assert type(inputs.inventory.findings) is tuple and type(inputs.declarations.declarations) is tuple


def test_every_frozen_dataclass_refuses_attribute_assignment():
    samples = [
        make_finding(), ACCOUNTING, make_inventory(), make_declaration(), chain({}), valid_proof(),
        make_chronology(), ctx(Stage.RESERVED), b0(), proto.classify_exposure(b0()).conditions[0],
        proto.classify_exposure(b0()),
    ]
    assert len(samples) == 11
    for sample in samples:
        first_field = dataclasses.fields(sample)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(sample, first_field, getattr(sample, first_field))


def test_canonical_json_matches_the_decision_20_3_helper_used_by_e1():
    from gate_v_final_holdout_claim import _canonical_json as e1_canonical_json  # comparaison de TEST seulement

    record = {"b": [1, {"z": None, "a": "é"}], "a": True}
    assert proto._canonical_json(record) == e1_canonical_json(record) == '{"a":true,"b":[1,{"a":"é","z":null}]}'
    with pytest.raises(ValueError):
        proto._canonical_json({"x": float("nan")})


def test_module_functions_do_not_mutate_their_inputs_or_global_state():
    inputs = b0()
    before = (inputs.inventory, inputs.declarations, inputs.chronology, inputs.own_context)
    first = proto.classification_result_to_record(proto.classify_exposure(inputs))
    second = proto.classification_result_to_record(proto.classify_exposure(inputs))
    assert first == second
    assert (inputs.inventory, inputs.declarations, inputs.chronology, inputs.own_context) == before


def test_result_rejects_a_forged_classification_id_or_inconsistent_invariants():
    result = proto.classify_exposure(b0())
    fields = {f.name: getattr(result, f.name) for f in dataclasses.fields(result)}
    for tampered in (
        dict(classification_id="0" * 64),
        dict(chronology_level=proto.ChronologyLevel.UNSEEN_HISTORICAL),               # six MET => ANCHORED
        dict(classification=Cls.RETROSPECTIVE_EXPOSED),                               # sans exposition établie
        dict(established_exposure_ids=("x",)),                                        # classe FRESH incohérente
        dict(reasons=(RC.UNRESOLVED_SOURCE,)),                                        # sans identifiants
        dict(conditions=result.conditions[:5]),
        dict(rules_version="gate_v_exposure_classification_v0"),
        dict(unresolved_source_ids=("b", "a")),
    ):
        with pytest.raises(ValueError):
            proto.ExposureClassificationResult(**{**fields, **tampered})


def forged_result(result, **changes):
    """Résultat falsifié MAIS auto-cohérent pour le hash : `classification_id` recalculé par le calcul indépendant."""
    from types import SimpleNamespace

    fields = {f.name: getattr(result, f.name) for f in dataclasses.fields(result)}
    fields.update(changes)
    fields["classification_id"] = independent_classification_id(SimpleNamespace(**fields)) \
        if "classification_id" not in changes else changes["classification_id"]
    return proto.ExposureClassificationResult(**fields)


def met(code):
    return proto.FConditionResult(condition=code, status=MET, reasons=())


def test_result_invariants_reject_forged_but_hash_consistent_results():
    base = proto.classify_exposure(b0())
    f_all_met = base.conditions
    forgeries = [
        # FRESH + ANCHORED mais des sources non résolues (jumeau F1 absent)
        dict(unresolved_source_ids=("zz",), reasons=(RC.UNRESOLVED_SOURCE,)),
        # FRESH + ANCHORED mais une anomalie propre
        dict(own_anomaly_ids=("missing:ADMISSION",), reasons=(RC.OWN_REGISTRATION_ANOMALY,)),
        # FRESH avec raison d'inventaire incomplet
        dict(reasons=(RC.INVENTORY_INCOMPLETE,)),
        # UNDETERMINED sans aucune explication
        dict(classification=Cls.UNDETERMINED, chronology_level=proto.ChronologyLevel.UNSEEN_HISTORICAL,
             conditions=(f_all_met[0], proto.FConditionResult("F2", UNVERIFIED, (RC.F2_T_SEL_MISSING,)),
                         f_all_met[2], f_all_met[3], f_all_met[4], f_all_met[5]),
             reasons=(RC.F2_T_SEL_MISSING,)),
        # exposition établie sans le jumeau F1 NOT_MET
        dict(classification=Cls.RETROSPECTIVE_EXPOSED, chronology_level=proto.ChronologyLevel.NOT_APPLICABLE,
             established_exposure_ids=("x",), reasons=(RC.EXPOSURE_ESTABLISHED_INVENTORY,)),
        # F1 NOT_MET (exposition établie) mais classe FRESH sans identifiants
        dict(conditions=(proto.FConditionResult("F1", NOT_MET, (RC.F1_EXPOSURE_ESTABLISHED,)), *f_all_met[1:]),
             chronology_level=proto.ChronologyLevel.UNSEEN_HISTORICAL, reasons=(RC.F1_EXPOSURE_ESTABLISHED,)),
    ]
    for changes in forgeries:
        with pytest.raises(ValueError):
            forged_result(base, **changes)


NOT_MET_REASONS = frozenset({
    RC.F1_EXPOSURE_ESTABLISHED, RC.F2_EXPOSURE_AFTER_WS, RC.F2_T_SEL_AFTER_WS, RC.F2_T_SEL_AFTER_ANCHOR,
    RC.F3_S0_NOT_BEFORE_WINDOW, RC.F4_RESERVATION_NOT_DURABLE, RC.F4_PROOF_INVALID, RC.F4_PROOF_NOT_OWN_RESERVATION,
    RC.F4_ANCHORED_TOO_LATE, RC.F5_INGESTED_BEFORE_WINDOW_END, RC.F5_RANGE_MISMATCH, RC.F6_HASH_LINK_BROKEN,
})
UNVERIFIED_REASONS = frozenset({
    RC.F1_SOURCES_UNRESOLVED, RC.F1_INVENTORY_INCOMPLETE, RC.F1_OWN_ANOMALY, RC.F2_EXPOSURE_WINDOW_UNKNOWN,
    RC.F2_T_SEL_MISSING, RC.F2_ANCHOR_UNKNOWN, RC.F3_S0_MAX_TIME_MISSING, RC.F4_RESERVATION_UNKNOWN,
    RC.F4_PROOF_ABSENT, RC.F4_PROOF_UNVERIFIABLE, RC.F4_MARGIN_MISSING, RC.F4_MARGIN_NOT_POSITIVE,
    RC.F5_INGESTION_MISSING,
})


def test_the_twenty_five_condition_reasons_are_partitioned_into_not_met_and_unverified_codes():
    condition_codes = frozenset(list(proto.ReasonCode)[7:])
    assert NOT_MET_REASONS | UNVERIFIED_REASONS == condition_codes
    assert not NOT_MET_REASONS & UNVERIFIED_REASONS
    assert len(NOT_MET_REASONS) == 12 and len(UNVERIFIED_REASONS) == 13


def test_f_condition_result_ties_the_status_to_the_severity_of_its_reasons():
    with pytest.raises(ValueError):   # UNVERIFIED portant une raison de violation connue
        proto.FConditionResult("F3", UNVERIFIED, (RC.F3_S0_NOT_BEFORE_WINDOW,))
    with pytest.raises(ValueError):   # NOT_MET sans aucune violation connue
        proto.FConditionResult("F3", NOT_MET, (RC.F3_S0_MAX_TIME_MISSING,))
    with pytest.raises(ValueError):   # UNVERIFIED mêlant donnée manquante et violation
        proto.FConditionResult("F4", UNVERIFIED, (RC.F4_RESERVATION_UNKNOWN, RC.F4_PROOF_INVALID))
    assert proto.FConditionResult("F4", NOT_MET, (RC.F4_RESERVATION_UNKNOWN, RC.F4_PROOF_INVALID)).status is NOT_MET
    assert proto.FConditionResult("F3", UNVERIFIED, (RC.F3_S0_MAX_TIME_MISSING,)).status is UNVERIFIED


def test_every_reason_of_every_classified_condition_matches_its_severity_class():
    for scenario in (
        classify(res(), chronology=chron(s0_max_time_utc=WS, reservation_durable=None, ingested_at_utc=None)),
        classify(res(), make_unresolved(source_id="u"), res("r", campaign=OTHER)),
    ):
        for condition in scenario.conditions:
            has_violation = any(reason in NOT_MET_REASONS for reason in condition.reasons)
            assert (condition.status is NOT_MET) == has_violation
            if condition.status is UNVERIFIED:
                assert set(condition.reasons) <= UNVERIFIED_REASONS
            if condition.status is MET:
                assert condition.reasons == ()


def test_result_refuses_a_condition_code_that_no_condition_explains():
    base = proto.classify_exposure(b0())
    with pytest.raises(ValueError):
        forged_result(base, reasons=(RC.F3_S0_MAX_TIME_MISSING,))   # F3 est MET : aucune condition ne l'explique


def test_builders_turn_malformed_elements_into_value_errors_not_type_errors():
    from types import SimpleNamespace

    with pytest.raises(ValueError):
        proto.build_exposure_inventory(
            window_start_utc=WS, window_end_utc=WE, findings=[make_finding(), SimpleNamespace(source_id=5)],
            complete=True, scanned_roots=["r"], trial_accounting=ACCOUNTING,
        )
    with pytest.raises(ValueError):
        proto.build_exposure_inventory(
            window_start_utc=WS, window_end_utc=WE, findings=[], complete=True, scanned_roots=[["x"]],
            trial_accounting=ACCOUNTING,
        )
    with pytest.raises(ValueError):
        proto.build_exposure_declaration(
            declaration_seq=1, declarant="Mira", inventory_id=INV_ID, prev_declaration_id=None,
            declared_exposures=[SimpleNamespace(source_id=5)], declared_t_sel_utc=None, declared_trial_counts=None,
        )
    with pytest.raises(TypeError):   # une chaîne n'est pas une collection : erreur d'appel
        proto.build_exposure_inventory(
            window_start_utc=WS, window_end_utc=WE, findings="abc", complete=True, scanned_roots=["r"],
            trial_accounting=ACCOUNTING,
        )


def test_projection_includes_foreign_unresolved_registry_records_and_excludes_own_ones():
    unresolved_foreign = make_unresolved(source_id="r_u", source_kind=K.REGISTRY_RESERVATION, campaign_id=OTHER)
    unresolved_no_campaign = make_unresolved(source_id="r_v", source_kind=K.REGISTRY_ADMISSION)
    unresolved_own = make_unresolved(source_id="r_w", source_kind=K.REGISTRY_RESERVATION, campaign_id=CURRENT)
    inventory = make_inventory(unresolved_foreign, unresolved_no_campaign, unresolved_own)
    expected = canonical_sha256([
        {"source_id": "r_u", "content_hash": None, "source_kind": "REGISTRY_RESERVATION"},
        {"source_id": "r_v", "content_hash": None, "source_kind": "REGISTRY_ADMISSION"},
    ])
    assert proto.compute_overlap_projection_hash(inventory, ctx(Stage.NO_OWN_RECORDS)) == expected


def test_a_declared_exposure_never_carries_a_content_hash_even_when_unresolved():
    with pytest.raises(ValueError):
        make_unresolved(source_id="declared:0001:0001", source_kind=K.DECLARED_UNRECORDED_WORK, content_hash=H1)


def test_an_unresolved_declared_exposure_is_an_unknown_window_for_f2():
    unresolved_declared = make_declared(1, 1, status=proto.SourceStatus.UNRESOLVED)
    result = classify(res(), declaration_specs=({"declared_exposures": (unresolved_declared,)},))
    assert cond(result, "F2").status is UNVERIFIED
    assert cond(result, "F2").reasons == (RC.F2_EXPOSURE_WINDOW_UNKNOWN,)


def test_the_declared_exposure_count_is_capped_by_the_four_digit_position_format():
    class Stub:
        pass

    with pytest.raises(ValueError):
        proto.ExposureDeclaration(**declaration_kwargs(declared_exposures=tuple(Stub() for _ in range(10000))))


def test_f_condition_result_enforces_met_iff_no_reason_and_closed_condition_ids():
    with pytest.raises(ValueError):
        proto.FConditionResult(condition="F7", status=MET, reasons=())
    with pytest.raises(ValueError):
        proto.FConditionResult(condition="F1", status=MET, reasons=(RC.F1_EXPOSURE_ESTABLISHED,))
    with pytest.raises(ValueError):
        proto.FConditionResult(condition="F1", status=NOT_MET, reasons=())
    with pytest.raises(ValueError):
        proto.FConditionResult(condition="F1", status=NOT_MET, reasons=(RC.F2_T_SEL_MISSING,))
    with pytest.raises(ValueError):
        proto.FConditionResult(condition="F1", status=UNVERIFIED, reasons=(RC.F1_OWN_ANOMALY, RC.F1_EXPOSURE_ESTABLISHED))


def test_result_reasons_are_the_sorted_union_of_class_and_condition_reasons():
    result = classify(res(), make_unresolved(source_id="evt_u"), chronology=chron(s0_max_time_utc=WS, ingestion_range_matches=False))
    order = list(proto.ReasonCode)
    assert list(result.reasons) == sorted(result.reasons, key=order.index)
    assert set(result.reasons) >= {RC.UNRESOLVED_SOURCE, RC.F1_SOURCES_UNRESOLVED, RC.F2_EXPOSURE_WINDOW_UNKNOWN,
                                   RC.F3_S0_NOT_BEFORE_WINDOW, RC.F5_RANGE_MISMATCH}
