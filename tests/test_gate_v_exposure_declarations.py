"""AF-V-07 Slice E3-B6 (partie indépendante d'E3-C) — déclarations, chaînes, lignée et chargeur du `DeclarationSet`.

Fixtures SYNTHÉTIQUES dans `tmp_path` uniquement : aucune donnée réelle, aucun `FINAL_HOLDOUT`, aucun accès réseau. Les tests écrivent
les fichiers directement : AUCUNE fonction de ce lot ne publie une déclaration ou une attestation (publication par lien = E3-C).
Contrat : ADR 0025 23.11 étape 2, 23.13, 23.27.6, 23.29.1 à 23.29.4, 23.29.8 ; design E3-B (AI_HANDOFF.md §44.1, §45).
"""

from __future__ import annotations

import hashlib
import json

import pytest

import gate_v_exposure_declarations as b6
import gate_v_exposure_store as store
from gate_v_final_holdout_protocol import (
    EXPOSURE_DECLARATION_SEMANTICS_VERSION,
    OverlapVerdict,
    SourceKind,
    SourceStatus,
    TrialAccounting,
    UnresolvedCause,
    build_exposure_declaration,
    build_exposure_finding,
    compute_declaration_id,
)
from tests.gate_v_exposure_support import CURRENT, h

INVENTORY_ID = "3" * 64
OTHER_INVENTORY_ID = "4" * 64
DECL_CREATED = "2026-10-21T09:00:00+00:00"


def declared_finding(seq: int, position: int, *, established: bool = True):
    """Exposition déclarée (`declared:<seq4>:<pos4>`) : établie (RESOLVED/OVERLAPS dans W) ou non résolue (WINDOW_UNKNOWN)."""
    source_id = f"declared:{seq:04d}:{position:04d}"
    if established:
        return build_exposure_finding(source_id=source_id, source_kind=SourceKind.DECLARED_UNRECORDED_WORK, status=SourceStatus.RESOLVED,
                                      overlap=OverlapVerdict.OVERLAPS, window_start_utc="2026-02-01T00:00:00+00:00",
                                      window_end_utc="2026-02-10T00:00:00+00:00")
    return build_exposure_finding(source_id=source_id, source_kind=SourceKind.DECLARED_UNRECORDED_WORK, status=SourceStatus.UNRESOLVED,
                                  overlap=OverlapVerdict.UNKNOWN, unresolved_cause=UnresolvedCause.WINDOW_UNKNOWN)


def declared_by_template(seq: int, position: int, template: str):
    """Exposition déclarée selon un gabarit de géométrie vis-à-vis de W = [2026-01-01, 2026-04-01) (demi-ouverte) :
    `est` établie dans W ; `unr` non résolue ; les `ok_*` ont un verdict COHÉRENT avec leur fenêtre ; les `bad_*` le contredisent."""
    source_id = f"declared:{seq:04d}:{position:04d}"
    if template == "est":
        return declared_finding(seq, position, established=True)
    if template == "unr":
        return declared_finding(seq, position, established=False)
    start, end, verdict = {
        "ok_before_adjacent": ("2025-12-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", OverlapVerdict.NO_OVERLAP),     # fin == début de W
        "ok_after_adjacent": ("2026-04-01T00:00:00+00:00", "2026-05-01T00:00:00+00:00", OverlapVerdict.NO_OVERLAP),      # début == fin de W
        "ok_disjoint": ("2025-01-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00", OverlapVerdict.NO_OVERLAP),
        "ok_overlap_by_one_second": ("2025-12-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00", OverlapVerdict.OVERLAPS),
        "ok_enclosing": ("2025-01-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00", OverlapVerdict.OVERLAPS),
        "bad_no_overlap_inside": ("2026-02-01T00:00:00+00:00", "2026-02-10T00:00:00+00:00", OverlapVerdict.NO_OVERLAP),
        "bad_overlap_outside": ("2025-01-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00", OverlapVerdict.OVERLAPS),
        "bad_overlap_adjacent": ("2025-12-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", OverlapVerdict.OVERLAPS),
        "bad_no_overlap_by_one_second": ("2025-12-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00", OverlapVerdict.NO_OVERLAP),
    }[template]
    return build_exposure_finding(source_id=source_id, source_kind=SourceKind.DECLARED_UNRECORDED_WORK, status=SourceStatus.RESOLVED,
                                  overlap=verdict, window_start_utc=start, window_end_utc=end)


def make_declaration(seq=1, prev_id=None, *, inventory_id=INVENTORY_ID, exposures=(), t_sel=None, counts=None):
    return build_exposure_declaration(
        declaration_seq=seq, declarant="Mira", inventory_id=inventory_id, prev_declaration_id=prev_id,
        declared_exposures=tuple(exposures), declared_t_sel_utc=t_sel, declared_trial_counts=counts)


def adr_hash(envelope: dict) -> str:
    """Recette de l'ADR (23.29.1) : SHA-256 du JSON canonique (20.3) de l'enveloppe SANS `declaration_content_hash`."""
    body = {key: value for key, value in envelope.items() if key != "declaration_content_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def adr_bytes(record: dict) -> bytes:
    return (json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def envelope_of(declaration, *, prev_hash=None, carried_from=None, created_at=DECL_CREATED, campaign_id=CURRENT) -> dict:
    return b6.build_declaration_envelope(declaration, campaign_id=campaign_id, prev_declaration_content_hash=prev_hash,
                                         carried_from=carried_from, created_at=created_at)


CARRIED = {"inventory_id": OTHER_INVENTORY_ID, "tip_seq": 2, "tip_declaration_id": h("tip-id"), "tip_declaration_content_hash": h("tip-hash")}


# ── Tranche 1 : enveloppe d'une déclaration (construction pure, hash, sérialisation, relecture stricte d'un fichier) ──────

def test_the_envelope_has_the_exact_documented_keys_and_the_adr_hash_recipe():
    declaration = make_declaration(exposures=[declared_finding(1, 1)], t_sel="2026-10-20T00:00:00+00:00")
    envelope = envelope_of(declaration)
    assert sorted(envelope) == sorted(b6.DECLARATION_ENVELOPE_KEYS) == sorted(
        ["version", "campaign_id", "declaration", "declaration_id", "prev_declaration_content_hash", "carried_from", "created_at",
         "declaration_content_hash"])
    assert envelope["version"] == EXPOSURE_DECLARATION_SEMANTICS_VERSION == "gate_v_exposure_declaration_v1"
    assert envelope["declaration_id"] == compute_declaration_id(declaration)            # identité d'E3-A, inchangée
    assert envelope["declaration_content_hash"] == adr_hash(envelope) == b6.compute_declaration_content_hash(envelope)
    assert envelope["created_at"] == "2026-10-21T09:00:00.000000Z"
    assert set(envelope["declaration"]) == {"version", "declaration_seq", "declarant", "inventory_id", "prev_declaration_id",
                                            "declared_exposures", "declared_t_sel_utc", "declared_trial_counts"}


def test_the_declaration_id_does_not_cover_the_envelope_but_the_content_hash_covers_everything():
    declaration = make_declaration()
    first = envelope_of(declaration, created_at="2026-10-21T09:00:00+00:00")
    later = envelope_of(declaration, created_at="2026-10-21T09:00:01+00:00")
    assert first["declaration_id"] == later["declaration_id"] and first["declaration_content_hash"] != later["declaration_content_hash"]


def test_the_persisted_representation_is_the_normative_one():
    envelope = envelope_of(make_declaration())
    raw = b6.serialize_declaration_envelope(envelope)
    assert raw == adr_bytes(envelope) and raw.endswith(b"\n") and b"\r" not in raw and json.loads(raw) == envelope


@pytest.mark.parametrize("seq, prev_id, prev_hash, carried, error", [
    (1, None, h("p"), None, ValueError),                 # seq 1 n'a pas de prev_declaration_content_hash
    (2, h("prev"), None, None, ValueError),              # seq > 1 l'exige
    (2, h("prev"), h("p"), CARRIED, ValueError),         # carried_from seulement pour seq 1
])
def test_the_envelope_enforces_the_prev_hash_and_carried_from_rules(seq, prev_id, prev_hash, carried, error):
    with pytest.raises(error):
        envelope_of(make_declaration(seq, prev_id), prev_hash=prev_hash, carried_from=carried)


def test_carried_from_has_exactly_four_pinned_fields():
    envelope = envelope_of(make_declaration(), carried_from=CARRIED)
    assert envelope["carried_from"] == CARRIED
    for bad in (dict(CARRIED, extra=1), {k: v for k, v in CARRIED.items() if k != "tip_seq"}, dict(CARRIED, tip_seq=0),
                dict(CARRIED, tip_seq=True), dict(CARRIED, inventory_id="short"), dict(CARRIED, tip_declaration_id="x")):
        with pytest.raises((ValueError, TypeError)):
            envelope_of(make_declaration(), carried_from=bad)


@pytest.mark.parametrize("created_at, error", [("2026-10-21T09:00:00", ValueError), (None, TypeError)])
def test_created_at_is_injected_and_aware(created_at, error):
    with pytest.raises(error):
        envelope_of(make_declaration(), created_at=created_at)


def test_a_declaration_file_roundtrips_to_the_same_e3a_object_and_identities():
    declaration = make_declaration(2, h("prev"), exposures=[declared_finding(2, 1), declared_finding(2, 2, established=False)],
                                   t_sel="2026-10-20T00:00:00+00:00", counts=TrialAccounting(1, 2, 3, 0, 0, 0))
    envelope = envelope_of(declaration, prev_hash=h("prev-file"))
    parsed = b6.parse_declaration_file(b6.serialize_declaration_envelope(envelope), inventory_id=INVENTORY_ID, seq=2, campaign_id=CURRENT)
    assert parsed.declaration == declaration and parsed.declaration_id == compute_declaration_id(declaration)
    assert parsed.content_hash == envelope["declaration_content_hash"] and parsed.prev_declaration_content_hash == h("prev-file")
    assert parsed.carried_from is None and parsed.created_at == "2026-10-21T09:00:00.000000Z"


def test_a_first_declaration_of_a_successor_chain_exposes_its_carried_from_pin():
    envelope = envelope_of(make_declaration(inventory_id=INVENTORY_ID), carried_from=CARRIED)
    parsed = b6.parse_declaration_file(b6.serialize_declaration_envelope(envelope), inventory_id=INVENTORY_ID, seq=1, campaign_id=CURRENT)
    assert parsed.carried_from == b6.CarriedFrom(OTHER_INVENTORY_ID, 2, CARRIED["tip_declaration_id"], CARRIED["tip_declaration_content_hash"])


def parse_refused(raw: bytes, *, inventory_id=INVENTORY_ID, seq=1, campaign_id=CURRENT) -> store.ExposureStoreError:
    with pytest.raises(store.ExposureStoreError) as refusal:
        b6.parse_declaration_file(raw, inventory_id=inventory_id, seq=seq, campaign_id=campaign_id)
    return refusal.value


def good_raw(**kwargs) -> bytes:
    return b6.serialize_declaration_envelope(envelope_of(make_declaration(exposures=[declared_finding(1, 1)]), **kwargs))


@pytest.mark.parametrize("name, transform, failure", [
    ("bom", lambda raw: b"\xef\xbb\xbf" + raw, store.StoreFailure.NOT_JSON),
    ("invalid_utf8", lambda raw: raw.replace(b"Mira", b"Mi\xff\xfe"), store.StoreFailure.NOT_JSON),
    ("truncated", lambda raw: raw[:80], store.StoreFailure.NOT_JSON),
    ("duplicate_key", lambda raw: raw.replace(b'"declarant": "Mira"', b'"declarant": "Mira",\n    "declarant": "Eve"'), store.StoreFailure.NOT_JSON),
    ("nan", lambda raw: raw.replace(b'"declaration_seq": 1', b'"declaration_seq": NaN'), store.StoreFailure.NOT_JSON),
    ("list", lambda raw: b"[]\n", store.StoreFailure.SCHEMA),
    ("compact", lambda raw: json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode() + b"\n",
     store.StoreFailure.NOT_FIXED_POINT),
    ("crlf", lambda raw: raw.replace(b"\n", b"\r\n"), store.StoreFailure.NOT_FIXED_POINT),
    ("indent4", lambda raw: json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=False, indent=4).encode() + b"\n",
     store.StoreFailure.NOT_FIXED_POINT),
])
def test_unreadable_or_non_normative_bytes_are_refused_with_a_typed_cause(name, transform, failure):
    assert parse_refused(transform(good_raw())).failure is failure


def rewrite(raw: bytes, mutate, *, rehash=True) -> bytes:
    envelope = json.loads(raw)
    mutate(envelope)
    if rehash:
        envelope["declaration_content_hash"] = b6.compute_declaration_content_hash(envelope)
    return adr_bytes(envelope)


DECLARATION_SCHEMA_CASES = [
    ("extra_envelope_key", lambda e: e.update(extra=1)),
    ("missing_envelope_key", lambda e: e.pop("carried_from")),
    ("version_wrong_type", lambda e: e.update(version=7)),
    ("declaration_extra_key", lambda e: e["declaration"].update(extra=1)),
    ("declaration_missing_key", lambda e: e["declaration"].pop("declarant")),
    ("seq_is_bool", lambda e: e["declaration"].update(declaration_seq=True)),
    ("declarant_empty", lambda e: e["declaration"].update(declarant="")),
    ("exposure_extra_key", lambda e: e["declaration"]["declared_exposures"][0].update(extra=1)),
    ("exposure_unknown_kind", lambda e: e["declaration"]["declared_exposures"][0].update(source_kind="NOPE")),
    ("exposure_not_declared_kind", lambda e: e["declaration"]["declared_exposures"][0].update(source_kind="JOB_EXECUTION")),
    ("exposure_wrong_id", lambda e: e["declaration"]["declared_exposures"][0].update(source_id="declared:0009:0001")),
    ("counts_extra_key", lambda e: e["declaration"].update(declared_trial_counts={"research_runs": 1})),
    ("t_sel_not_normalized", lambda e: e["declaration"].update(declared_t_sel_utc="2026-10-20T00:00:00+00:00")),
    ("created_at_not_normalized", lambda e: e.update(created_at="2026-10-21T09:00:00+00:00")),
    ("created_at_naive", lambda e: e.update(created_at="2026-10-21T09:00:00")),
    ("prev_hash_on_seq_1", lambda e: e.update(prev_declaration_content_hash=h("x"))),
    ("carried_from_malformed", lambda e: e.update(carried_from={"inventory_id": "x"})),
    ("declaration_id_malformed", lambda e: e.update(declaration_id="x")),
]


@pytest.mark.parametrize("name, mutate", DECLARATION_SCHEMA_CASES, ids=[case[0] for case in DECLARATION_SCHEMA_CASES])
def test_a_schema_violation_is_refused_even_when_the_hash_is_recomputed(name, mutate):
    assert parse_refused(rewrite(good_raw(), mutate)).failure is store.StoreFailure.SCHEMA


def test_an_unknown_version_is_refused_as_such():
    assert parse_refused(rewrite(good_raw(), lambda e: e.update(version="gate_v_exposure_declaration_v2"))).failure \
        is store.StoreFailure.UNKNOWN_VERSION


def test_a_modified_content_without_a_recomputed_hash_is_refused():
    raw = rewrite(good_raw(), lambda e: e["declaration"].update(declarant="Eve"), rehash=False)
    assert parse_refused(raw).failure is store.StoreFailure.HASH_MISMATCH


def test_the_declaration_id_is_recomputed_never_trusted():
    """Contenu modifié ET hash du fichier recalculé, mais `declaration_id` laissé tel quel : l'identité d'E3-A ne correspond plus."""
    raw = rewrite(good_raw(), lambda e: e["declaration"].update(declarant="Eve"))
    assert parse_refused(raw).failure is store.StoreFailure.IDENTITY_MISMATCH


def test_the_directory_and_the_file_name_must_match_the_content():
    raw = good_raw()
    assert parse_refused(raw, inventory_id=OTHER_INVENTORY_ID).failure is store.StoreFailure.NAME_MISMATCH     # répertoire ≠ inventory_id
    assert parse_refused(raw, seq=2).failure is store.StoreFailure.NAME_MISMATCH                               # nom de fichier ≠ seq
    with pytest.raises(ValueError):
        b6.parse_declaration_file(raw, inventory_id="short", seq=1, campaign_id=CURRENT)
    with pytest.raises(ValueError):
        b6.parse_declaration_file(raw, inventory_id=INVENTORY_ID, seq=0, campaign_id=CURRENT)
    with pytest.raises(ValueError):
        b6.parse_declaration_file(raw, inventory_id=INVENTORY_ID, seq=10000, campaign_id=CURRENT)
    with pytest.raises(TypeError):
        b6.parse_declaration_file("not bytes", inventory_id=INVENTORY_ID, seq=1, campaign_id=CURRENT)


def test_the_normative_paths_are_per_inventory_and_dense_four_digit_slots(tmp_path):
    assert b6.declaration_path(tmp_path, INVENTORY_ID, 7) == tmp_path / "exposure" / INVENTORY_ID / "declaration_0007.json"
    assert b6.attestation_path(tmp_path, INVENTORY_ID, 12) == tmp_path / "exposure" / INVENTORY_ID / "attestation_0012.json"
    for bad_seq in (0, 10000, -1, True, "1"):
        with pytest.raises((ValueError, TypeError)):
            b6.declaration_path(tmp_path, INVENTORY_ID, bad_seq)
    with pytest.raises(ValueError):
        b6.attestation_path(tmp_path, "not-an-inventory-id", 1)


# ── Tranche 2 : découverte de `exposure/`, chaînes, chargeur de lignée ───────────────────────────────────────────────

import dataclasses  # noqa: E402
import os  # noqa: E402
from collections import namedtuple  # noqa: E402

from gate_v_final_holdout_protocol import DeclarationSet  # noqa: E402
from gate_v_final_holdout_protocol import OwnCampaignContext, OwnRecordStage  # noqa: E402
from tests.gate_v_exposure_support import CREATED_AT, CURRENT, assemble, interpret  # noqa: E402

OTHER_CAMPAIGN = OwnCampaignContext("campaign_other", OwnRecordStage.NO_OWN_RECORDS)

Entry = namedtuple("Entry", "declaration content_hash path")


def campaign(tmp_path):
    path = tmp_path / "campaign_dir"
    path.mkdir(exist_ok=True)
    return path


def a0_for(tmp_path, directory, n: int, *, created_at=CREATED_AT, context=None) -> str:
    """Publie un A0 (par B5) d'`inventory_id` distinct pour chaque `n` et retourne cet `inventory_id`."""
    assembly = assemble(interpret(tmp_path / f"src{n}", job=("2026-02-01T00:00:00+00:00", f"2026-02-{10 + n:02d}T00:00:00+00:00")),
                        **({} if context is None else {"context": context}))
    store.publish_exposure_inventory(directory, assembly, created_at=created_at)
    return assembly.inventory_id


def carried_pin(predecessor) -> dict:
    tip = predecessor[-1]
    return {"inventory_id": tip.declaration.inventory_id, "tip_seq": tip.declaration.declaration_seq,
            "tip_declaration_id": compute_declaration_id(tip.declaration), "tip_declaration_content_hash": tip.content_hash}


def write_chain(directory, inventory_id, specs, *, predecessor=None, carried_override=None, prev_hash_override=None, raw_for_seq=None,
                drop_carried=0, alter_carried=None, campaign_id=CURRENT):
    """Écrit `declaration_0001..n.json` (octets normatifs, hashs corrects). `specs` : une liste par déclaration de gabarits
    (`"est"` établie, `"unr"` non résolue) ou un `dict` `{"templates": ..., "t_sel": ...}`. `predecessor` : entrées de la chaîne précédente, dont le
    report cumulatif (renumérotation `declared:0001:<pos4>`) et l'épinglage `carried_from` sont écrits par la première déclaration."""
    entries, previous = [], None
    for index, spec in enumerate(specs, start=1):
        templates, t_sel = (spec.get("templates", ()), spec.get("t_sel")) if isinstance(spec, dict) else (spec, None)
        carried_from, carried_findings = None, []
        if index == 1 and predecessor:
            carried_findings = [f for entry in predecessor for f in entry.declaration.declared_exposures]
            carried_findings = carried_findings[:len(carried_findings) - drop_carried]
            if alter_carried is not None:
                carried_findings = [alter_carried(finding) for finding in carried_findings]
            carried_from = carried_pin(predecessor)
        if index == 1 and carried_override is not None:
            carried_from = carried_override
        exposures = [dataclasses.replace(finding, source_id=f"declared:{index:04d}:{position:04d}")
                     for position, finding in enumerate(carried_findings, start=1)]
        exposures += [declared_by_template(index, len(exposures) + offset, template)
                      for offset, template in enumerate(templates, start=1)]
        declaration = make_declaration(index, None if previous is None else compute_declaration_id(previous.declaration),
                                       inventory_id=inventory_id, exposures=exposures, t_sel=t_sel)
        prev_hash = None if previous is None else (prev_hash_override or {}).get(index, previous.content_hash)
        envelope = envelope_of(declaration, prev_hash=prev_hash, carried_from=carried_from, created_at=f"2026-10-21T09:{index:02d}:00+00:00",
                               campaign_id=campaign_id)
        path = b6.declaration_path(directory, inventory_id, index)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (raw_for_seq or {}).get(index, b6.serialize_declaration_envelope(envelope))
        path.write_bytes(raw)
        previous = Entry(declaration, envelope["declaration_content_hash"], path)
        entries.append(previous)
    return entries


def load(directory, current, **kwargs):
    kwargs.setdefault("campaign_id", CURRENT)
    kwargs.setdefault("pinned_a0_hashes", frozenset())
    kwargs.setdefault("admitted_attestation", None)
    return b6.load_declaration_lineage(directory, current_inventory_id=current, **kwargs)


def refused_lineage(directory, current, **kwargs) -> "b6.LineageError":
    with pytest.raises(b6.LineageError) as refusal:
        load(directory, current, **kwargs)
    return refusal.value


def test_without_an_exposure_directory_there_is_no_lineage_and_no_declaration_set(tmp_path):
    directory = campaign(tmp_path)
    lineage = load(directory, INVENTORY_ID)
    assert lineage.state is b6.LineageState.NO_LINEAGE and lineage.chains == () and lineage.declaration_set is None
    assert lineage.declaration_lineage_digest is None and lineage.inventories == () and lineage.ignored == ()


def test_a_first_inventory_with_its_first_declaration_yields_a_declaration_set_and_the_adr_lineage_digest(tmp_path):
    directory = campaign(tmp_path)
    inventory_id = a0_for(tmp_path, directory, 1)
    (entry,) = write_chain(directory, inventory_id, [("est",)])
    lineage = load(directory, inventory_id)
    assert lineage.state is b6.LineageState.CURRENT_IS_TERMINAL and lineage.terminal_inventory_id == inventory_id
    assert type(lineage.declaration_set) is DeclarationSet and lineage.declaration_set.hash_linked is True
    assert lineage.declaration_set.declarations == (entry.declaration,)
    expected_digest = hashlib.sha256(json.dumps(
        [{"inventory_id": inventory_id, "tip_seq": 1, "tip_declaration_content_hash": entry.content_hash}],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert lineage.declaration_lineage_digest == expected_digest
    assert (lineage.tip_seq, lineage.tip_declaration_content_hash) == (1, entry.content_hash)
    (chain,) = lineage.chains
    assert chain.inventory_id == inventory_id and chain.hash_linked is True and chain.tip.content_hash == entry.content_hash


def test_several_declarations_on_one_inventory_form_a_dense_hash_linked_chain(tmp_path):
    directory = campaign(tmp_path)
    inventory_id = a0_for(tmp_path, directory, 1)
    entries = write_chain(directory, inventory_id, [("est",), ("unr", "est"), {"t_sel": "2026-10-20T00:00:00+00:00"}])
    lineage = load(directory, inventory_id)
    assert [d.declaration_seq for d in lineage.declaration_set.declarations] == [1, 2, 3]
    assert lineage.declaration_set.declarations == tuple(e.declaration for e in entries) and lineage.tip_seq == 3


def test_a_new_inventory_without_any_declaration_yields_no_declaration_set_and_keeps_the_prior_lineage(tmp_path):
    directory = campaign(tmp_path)
    first = a0_for(tmp_path, directory, 1)
    write_chain(directory, first, [("est",)])
    second = a0_for(tmp_path, directory, 2)
    lineage = load(directory, second)
    assert lineage.state is b6.LineageState.NO_CHAIN_FOR_CURRENT and lineage.declaration_set is None
    assert lineage.terminal_inventory_id == first and len(lineage.chains) == 1 and len(lineage.inventories) == 2


def test_several_a0_of_the_same_inventory_share_the_same_chain(tmp_path):
    directory = campaign(tmp_path)
    inventory_id = a0_for(tmp_path, directory, 1)
    assembly = assemble(interpret(tmp_path / "src1", job=("2026-02-01T00:00:00+00:00", "2026-02-11T00:00:00+00:00")),
                        accounting=__import__("gate_v_exposure_inventory").AccountingViews(
                            failed_ingestion=__import__("gate_v_exposure_inventory").TrialItemsView(items=())))
    store.publish_exposure_inventory(directory, assembly, created_at="2026-10-20T08:30:00+00:00")      # comptabilité différente
    write_chain(directory, inventory_id, [("est",)])
    lineage = load(directory, inventory_id)
    assert len(lineage.inventories) == 2 and {a.inventory_id for a in lineage.inventories} == {inventory_id}
    assert len(lineage.chains) == 1


# ── Structure de `exposure/` ───────────────────────────────────────────────────────────────────────────────────────────

def chain_ready(tmp_path, n=1):
    directory = campaign(tmp_path)
    inventory_id = a0_for(tmp_path, directory, n)
    entries = write_chain(directory, inventory_id, [("est",)])
    return directory, inventory_id, entries


@pytest.mark.parametrize("relative", [
    "exposure/notes.txt", "exposure/declaration_0001.json", "exposure/attestation.json", "exposure/inventory_" + "A" * 64 + ".json",
    "exposure/" + "B" * 64 + "/declaration_0001.json", "exposure/short/declaration_0001.json", "exposure/INVENTORY/x",
])
def test_any_unknown_entry_of_exposure_is_refused_never_ignored(tmp_path, relative):
    directory, inventory_id, _ = chain_ready(tmp_path)
    (directory / relative).parent.mkdir(parents=True, exist_ok=True)
    (directory / relative).write_bytes(b"{}")
    error = refused_lineage(directory, inventory_id)
    assert error.failure is b6.LineageFailure.UNKNOWN_ENTRY


@pytest.mark.parametrize("name", ["notes.json", "declaration_1.json", "declaration_00001.json", "declaration_0001.json.tmp",
                                  "attestation_x.json", "DECLARATION_0002.json", "declaration_0002.JSON"])
def test_any_unknown_entry_of_an_inventory_directory_is_refused(tmp_path, name):
    directory, inventory_id, _ = chain_ready(tmp_path)
    (directory / "exposure" / inventory_id / name).write_bytes(b"{}")
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.UNKNOWN_ENTRY


def test_a_subdirectory_inside_an_inventory_directory_is_refused(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    (directory / "exposure" / inventory_id / "sub").mkdir()
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.UNKNOWN_ENTRY


def test_a_directory_named_like_a_declaration_file_is_refused_as_not_regular(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    (directory / "exposure" / inventory_id / "declaration_0002.json").mkdir()
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.NOT_REGULAR


def test_publication_orphans_are_ignored_and_recorded_never_read_as_declarations(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    orphan = ".exposure.tmp." + "c" * 32
    (directory / "exposure" / orphan).write_bytes(b"partial")
    (directory / "exposure" / inventory_id / orphan).write_bytes(b"partial")
    lineage = load(directory, inventory_id)
    assert sorted((i.kind, i.relative_path) for i in lineage.ignored) == sorted([
        (b6.IgnoredKind.PUBLICATION_ORPHAN, f"exposure/{orphan}"), (b6.IgnoredKind.PUBLICATION_ORPHAN, f"exposure/{inventory_id}/{orphan}")])
    assert lineage.declaration_set is not None and len(lineage.declaration_set.declarations) == 1


def test_an_empty_inventory_directory_or_one_with_only_orphans_is_not_a_chain_and_is_recorded(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    (directory / "exposure" / ("5" * 64)).mkdir()
    (directory / "exposure" / ("6" * 64)).mkdir()
    (directory / "exposure" / ("6" * 64) / (".exposure.tmp." + "d" * 32)).write_bytes(b"partial")      # arrêt entre mkdir et link
    lineage = load(directory, inventory_id)
    kinds = sorted((i.kind.value, i.relative_path) for i in lineage.ignored)
    assert ("EMPTY_INVENTORY_DIRECTORY", "exposure/" + "5" * 64) in kinds and ("EMPTY_INVENTORY_DIRECTORY", "exposure/" + "6" * 64) in kinds
    assert len(lineage.chains) == 1                                  # ni racine, ni bifurcation : le répertoire vide est réutilisable


def test_a_directory_with_an_attestation_but_no_declaration_is_an_alteration(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    ghost = directory / "exposure" / ("7" * 64)
    ghost.mkdir()
    (ghost / "attestation_0001.json").write_bytes(b"{}\n")
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.ATTESTATION_WITHOUT_DECLARATION


@pytest.mark.parametrize("present", [[2], [1, 3], [1, 2, 4], [3, 4]])
def test_declaration_slots_must_be_dense_from_one(tmp_path, present):
    directory = campaign(tmp_path)
    inventory_id = a0_for(tmp_path, directory, 1)
    entries = write_chain(directory, inventory_id, [("est",), ("est",), ("est",), ("est",)])
    for entry in entries:
        if entry.declaration.declaration_seq not in present:
            entry.path.unlink()
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.SEQ_GAP


def test_a_corrupt_declaration_is_a_refusal_with_its_typed_cause_never_a_silent_skip(tmp_path):
    directory, inventory_id, (entry,) = chain_ready(tmp_path)
    entry.path.write_bytes(entry.path.read_bytes()[:60])
    error = refused_lineage(directory, inventory_id)
    assert error.failure is b6.LineageFailure.DECLARATION_INVALID and error.cause is store.StoreFailure.NOT_JSON


def test_a_declaration_filed_under_the_wrong_directory_is_refused(tmp_path):
    """Copie sous un autre nom (23.29.2) : le répertoire doit égaler l'`inventory_id` de chacune de ses déclarations."""
    directory, inventory_id, (entry,) = chain_ready(tmp_path)
    copy_dir = directory / "exposure" / OTHER_INVENTORY_ID
    copy_dir.mkdir()
    (copy_dir / "declaration_0001.json").write_bytes(entry.path.read_bytes())
    error = refused_lineage(directory, inventory_id)
    assert error.failure is b6.LineageFailure.DECLARATION_INVALID and error.cause is store.StoreFailure.NAME_MISMATCH


def test_a_broken_declaration_id_chain_is_refused(tmp_path):
    directory = campaign(tmp_path)
    inventory_id = a0_for(tmp_path, directory, 1)
    first, second = write_chain(directory, inventory_id, [("est",), ("est",)])
    rogue = make_declaration(2, h("not-the-previous-id"), inventory_id=inventory_id, exposures=[declared_finding(2, 1)])
    second.path.write_bytes(b6.serialize_declaration_envelope(envelope_of(rogue, prev_hash=first.content_hash)))
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.ID_CHAIN_BROKEN


def test_a_broken_prev_hash_link_in_the_terminal_chain_is_not_hash_linked_but_still_loads(tmp_path):
    """23.29.2 : `hash_linked` n'est faux que si chaque fichier est valide et les identifiants s'enchaînent, mais un lien de hash est rompu."""
    directory = campaign(tmp_path)
    inventory_id = a0_for(tmp_path, directory, 1)
    write_chain(directory, inventory_id, [("est",), ("est",)], prev_hash_override={2: h("wrong")})
    lineage = load(directory, inventory_id)
    assert lineage.declaration_set.hash_linked is False and lineage.chains[0].hash_linked is False


def test_a_broken_prev_hash_link_in_a_non_terminal_chain_is_refused(tmp_path):
    directory = campaign(tmp_path)
    first = a0_for(tmp_path, directory, 1)
    older = write_chain(directory, first, [("est",), ("est",)], prev_hash_override={2: h("wrong")})
    second = a0_for(tmp_path, directory, 2)
    write_chain(directory, second, [("est",)], predecessor=older)
    assert refused_lineage(directory, second).failure is b6.LineageFailure.BROKEN_LINK


def test_every_chain_needs_an_a0_of_its_inventory_that_precedes_its_first_declaration(tmp_path):
    directory = campaign(tmp_path)
    write_chain(directory, INVENTORY_ID, [("est",)])
    assert refused_lineage(directory, INVENTORY_ID).failure is b6.LineageFailure.A0_MISSING          # aucun A0
    (tmp_path / "late").mkdir()
    late = campaign(tmp_path / "late")
    inventory_id = a0_for(tmp_path / "late", late, 3, created_at="2026-10-22T00:00:00+00:00")        # A0 POSTÉRIEUR à la déclaration
    write_chain(late, inventory_id, [("est",)], predecessor=None)
    assert refused_lineage(late, inventory_id).failure is b6.LineageFailure.A0_MISSING
    (tmp_path / "equal").mkdir()
    equal = campaign(tmp_path / "equal")
    same_instant = a0_for(tmp_path / "equal", equal, 3, created_at="2026-10-21T09:01:00+00:00")       # A0 au MÊME instant : accepté
    write_chain(equal, same_instant, [("est",)])
    assert load(equal, same_instant).state is b6.LineageState.CURRENT_IS_TERMINAL


def test_an_unreadable_a0_is_a_recorded_orphan_unless_it_is_pinned_or_cited(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    bad_hash = "9" * 64
    (directory / "exposure" / f"inventory_{bad_hash}.json").write_bytes(b"{")
    lineage = load(directory, inventory_id)
    assert [(i.kind, i.relative_path) for i in lineage.ignored] == [(b6.IgnoredKind.UNREADABLE_INVENTORY, f"exposure/inventory_{bad_hash}.json")]
    assert refused_lineage(directory, inventory_id, pinned_a0_hashes=frozenset({bad_hash})).failure \
        is b6.LineageFailure.PINNED_A0_UNREADABLE
    attestation = directory / "exposure" / inventory_id / "attestation_0001.json"
    attestation.write_bytes(adr_bytes({"pins": {"inventory_content_hash": bad_hash}}))
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.A0_PIN_UNRESOLVED        # citation : non résolue (23.31.3)


def test_the_only_a0_of_an_inventory_being_unreadable_leaves_its_chain_without_an_a0(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    (a0,) = [p for p in (directory / "exposure").iterdir() if p.name.startswith("inventory_")]
    a0.write_bytes(a0.read_bytes()[:100])
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.A0_MISSING


def test_too_many_entries_are_refused_before_any_deep_read(tmp_path, monkeypatch):
    directory, inventory_id, _ = chain_ready(tmp_path)
    monkeypatch.setattr(b6, "MAX_DIRECTORY_ENTRIES", 1)
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.TOO_MANY_ENTRIES


def test_invalid_arguments_are_call_errors(tmp_path):
    directory = campaign(tmp_path)
    with pytest.raises(ValueError):
        b6.load_declaration_lineage(directory, current_inventory_id="short", campaign_id=CURRENT, pinned_a0_hashes=frozenset(), admitted_attestation=None)
    with pytest.raises(TypeError):
        b6.load_declaration_lineage(directory, current_inventory_id=None, campaign_id=CURRENT, pinned_a0_hashes=frozenset(), admitted_attestation=None)
    with pytest.raises(TypeError):
        b6.load_declaration_lineage(directory, current_inventory_id=INVENTORY_ID, campaign_id=CURRENT, pinned_a0_hashes=["x"], admitted_attestation=None)
    with pytest.raises(b6.LineageError) as refusal:
        b6.load_declaration_lineage(tmp_path / "missing", current_inventory_id=INVENTORY_ID, campaign_id=CURRENT, pinned_a0_hashes=frozenset(), admitted_attestation=None)
    assert refusal.value.failure is b6.LineageFailure.BAD_DIRECTORY


# ── Tranche 3 : lignée (linéarité, épinglage, report cumulatif, t_sel), brouillon, attestations, exclusivité ─────────────

T_SEL = "2026-10-20T00:00:00+00:00"


def two_chains(tmp_path, first_specs=(("est",),), second_specs=(("est",),), **kwargs):
    directory = campaign(tmp_path)
    first = a0_for(tmp_path, directory, 1)
    older = write_chain(directory, first, list(first_specs))
    second = a0_for(tmp_path, directory, 2)
    newer = write_chain(directory, second, list(second_specs), predecessor=older, **kwargs)
    return directory, first, second, older, newer


def test_two_chains_form_a_linear_lineage_with_a_cumulative_carry_over_and_the_terminal_set(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path, first_specs=(("est",), ("unr", "est")), second_specs=(("est",),))
    lineage = load(directory, second)
    assert [c.inventory_id for c in lineage.chains] == [first, second] and lineage.terminal_inventory_id == second
    (declaration,) = lineage.declaration_set.declarations
    assert len(declaration.declared_exposures) == 3 + 1                               # 1 + 2 repris de la chaîne précédente, plus 1 nouvelle
    assert [e.source_id for e in declaration.declared_exposures] == [f"declared:0001:{i:04d}" for i in range(1, 5)]
    expected = hashlib.sha256(json.dumps(
        [{"inventory_id": first, "tip_seq": 2, "tip_declaration_content_hash": older[-1].content_hash},
         {"inventory_id": second, "tip_seq": 1, "tip_declaration_content_hash": newer[-1].content_hash}],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert lineage.declaration_lineage_digest == expected


def test_the_omission_of_a_carried_exposure_is_refused_although_e3a_alone_would_accept_it(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path, first_specs=(("est",), ("est",)), second_specs=((),), drop_carried=1)
    assert refused_lineage(directory, second).failure is b6.LineageFailure.CARRY_OVER_OMITTED
    assert DeclarationSet((newer[0].declaration,), True).declarations == (newer[0].declaration,)        # E3-A seul l'accepte


def test_the_multiplicity_of_identical_exposures_must_be_carried(tmp_path):
    """Comparaison par contenu, en multiensemble : deux expositions identiques ne se réduisent pas à une."""
    directory, first, second, older, newer = two_chains(tmp_path, first_specs=(("est", "est"),), second_specs=((),), drop_carried=1)
    assert refused_lineage(directory, second).failure is b6.LineageFailure.CARRY_OVER_OMITTED


def test_an_unresolved_exposure_is_carried_and_keeps_its_multiplicity(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path, first_specs=(("unr", "unr"),), second_specs=((),))
    lineage = load(directory, second)
    assert [e.status.value for e in lineage.declaration_set.declarations[0].declared_exposures] == ["UNRESOLVED", "UNRESOLVED"]
    (tmp_path / "other").mkdir()
    directory2, _, second2, _, _ = two_chains(tmp_path / "other", first_specs=(("unr", "unr"),), second_specs=((),), drop_carried=1)
    assert refused_lineage(directory2, second2).failure is b6.LineageFailure.CARRY_OVER_OMITTED


def test_the_carry_over_compares_content_not_source_id_so_renumbering_is_required_and_accepted(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path, first_specs=(("est",), ("est",)), second_specs=(("unr",),))
    declaration = load(directory, second).declaration_set.declarations[0]
    assert [e.source_id for e in declaration.declared_exposures] == ["declared:0001:0001", "declared:0001:0002", "declared:0001:0003"]


@pytest.mark.parametrize("first_t_sel, accepted", [
    (None, False), ("2026-10-19T00:00:00+00:00", False), ("2026-10-19T23:59:59.999999+00:00", False),
    (T_SEL, True), ("2026-10-20T00:00:00.000001+00:00", True), ("2026-11-01T00:00:00+00:00", True),
])
def test_t_sel_never_decreases_from_one_chain_to_the_next(tmp_path, first_t_sel, accepted):
    directory, first, second, older, newer = two_chains(
        tmp_path, first_specs=(("est",), {"t_sel": T_SEL}), second_specs=({"templates": ("est",), "t_sel": first_t_sel},))
    if accepted:
        assert load(directory, second).declaration_set is not None
    else:
        assert refused_lineage(directory, second).failure is b6.LineageFailure.T_SEL_LOWERED


def test_without_any_previous_t_sel_the_next_chain_is_free(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path, second_specs=({"templates": ("est",), "t_sel": T_SEL},))
    assert load(directory, second).declaration_set is not None


@pytest.mark.parametrize("field, value", [("tip_seq", 2), ("tip_declaration_id", "a" * 64), ("tip_declaration_content_hash", "b" * 64)])
def test_the_carried_from_pin_must_match_the_real_tip_of_the_previous_chain(tmp_path, field, value):
    directory = campaign(tmp_path)
    first = a0_for(tmp_path, directory, 1)
    older = write_chain(directory, first, [("est",)])
    second = a0_for(tmp_path, directory, 2)
    write_chain(directory, second, [("est",)], predecessor=older, carried_override=dict(carried_pin(older), **{field: value}))
    assert refused_lineage(directory, second).failure is b6.LineageFailure.PIN_MISMATCH


def test_appending_a_declaration_to_a_chain_that_already_has_a_successor_breaks_the_pin(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path)
    write_chain(directory, first, [("est",), ("est",)])                              # la chaîne suivie reçoit une déclaration de plus
    assert refused_lineage(directory, second).failure is b6.LineageFailure.PIN_MISMATCH


def test_a_missing_previous_chain_is_refused(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path)
    for path in (directory / "exposure" / first).iterdir():
        path.unlink()
    (directory / "exposure" / first).rmdir()
    assert refused_lineage(directory, second).failure is b6.LineageFailure.MISSING_CHAIN


def test_an_unreadable_previous_chain_is_refused_never_skipped(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path)
    older[0].path.write_bytes(older[0].path.read_bytes()[:80])
    assert refused_lineage(directory, second).failure is b6.LineageFailure.DECLARATION_INVALID


def test_two_roots_are_a_fork(tmp_path):
    directory = campaign(tmp_path)
    for n in (1, 2):
        write_chain(directory, a0_for(tmp_path, directory, n), [("est",)])
    assert refused_lineage(directory, INVENTORY_ID).failure is b6.LineageFailure.FORK


def test_two_successors_of_the_same_chain_are_a_fork(tmp_path):
    directory = campaign(tmp_path)
    first = a0_for(tmp_path, directory, 1)
    older = write_chain(directory, first, [("est",)])
    for n in (2, 3):
        write_chain(directory, a0_for(tmp_path, directory, n), [("est",)], predecessor=older)
    assert refused_lineage(directory, INVENTORY_ID).failure is b6.LineageFailure.FORK


def test_a_lineage_without_a_root_is_a_cycle(tmp_path):
    directory = campaign(tmp_path)
    first, second = a0_for(tmp_path, directory, 1), a0_for(tmp_path, directory, 2)
    pin = {"tip_seq": 1, "tip_declaration_id": h("x"), "tip_declaration_content_hash": h("y")}
    write_chain(directory, first, [("est",)], carried_override=dict(pin, inventory_id=second))
    write_chain(directory, second, [("est",)], carried_override=dict(pin, inventory_id=first))
    assert refused_lineage(directory, first).failure is b6.LineageFailure.CYCLE


def test_a_detached_cycle_beside_the_root_leaves_unlinked_chains_and_is_refused(tmp_path):
    directory = campaign(tmp_path)
    root, first, second = (a0_for(tmp_path, directory, n) for n in (1, 2, 3))
    write_chain(directory, root, [("est",)])
    pin = {"tip_seq": 1, "tip_declaration_id": h("x"), "tip_declaration_content_hash": h("y")}
    write_chain(directory, first, [("est",)], carried_override=dict(pin, inventory_id=second))
    write_chain(directory, second, [("est",)], carried_override=dict(pin, inventory_id=first))
    assert refused_lineage(directory, root).failure is b6.LineageFailure.UNLINKED_CHAIN


def test_going_back_to_an_older_inventory_is_refused(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path)
    assert refused_lineage(directory, first).failure is b6.LineageFailure.INVENTORY_REVERSION


def test_a_third_party_chain_is_not_connected_to_the_lineage_unless_it_is_pinned(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path)
    third = a0_for(tmp_path, directory, 3)
    write_chain(directory, third, [("est",)])                                         # deuxième racine : bifurcation
    assert refused_lineage(directory, third).failure is b6.LineageFailure.FORK


def test_a_chain_of_three_is_ordered_root_to_terminal_with_a_carry_over_of_everything(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path, first_specs=(("est",),), second_specs=(("unr",),))
    third = a0_for(tmp_path, directory, 3)
    last = write_chain(directory, third, [("est",)], predecessor=newer)
    lineage = load(directory, third)
    assert [c.inventory_id for c in lineage.chains] == [first, second, third]
    assert len(lineage.declaration_set.declarations[0].declared_exposures) == 1 + 1 + 1   # 1 (chaîne 1) + 1 nouvelle (chaîne 2) + 1 nouvelle
    assert last[0].content_hash == lineage.tip_declaration_content_hash


def test_the_loaded_lineage_digest_does_not_depend_on_attestations_or_a0_accounting(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path)
    before = load(directory, second).declaration_lineage_digest
    (directory / "exposure" / second / "attestation_0001.json").write_bytes(adr_bytes({"anything": 1}))
    assert load(directory, second).declaration_lineage_digest == before


# ── E3-A : la classification reçoit le report ───────────────────────────────────────────────────────────────────────────

from gate_v_final_holdout_protocol import (  # noqa: E402
    ChronologyFacts,
    ClassificationInput,
    ExposureClass,
    TimeProofFact,
    TimeProofStatus,
    classify_exposure,
)


def assemble_for(tmp_path, n: int):
    """Assemblage de l'inventaire n° `n` de `a0_for` (mêmes sources synthétiques, même contexte propre)."""
    return assemble(interpret(tmp_path / f"src{n}", job=("2026-02-01T00:00:00+00:00", f"2026-02-{10 + n:02d}T00:00:00+00:00")))


def classify(assembly, declaration_set):
    chronology = ChronologyFacts(None, None, TimeProofFact(TimeProofStatus.ABSENT, None, None), None, None, None, None)
    return classify_exposure(ClassificationInput(assembly.inventory, declaration_set, chronology, assembly.own_context))


def test_a_carried_established_exposure_makes_the_next_inventory_retrospective_exposed(tmp_path):
    """Scénario 4 de 23.29.8 : report cumulatif, `RETROSPECTIVE_EXPOSED` si l'exposition déclarée est établie."""
    directory = campaign(tmp_path)
    quiet = ("2025-06-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00")                  # job hors de W : absence NON établie seulement
    first_assembly = assemble(interpret(tmp_path / "a", job=quiet))
    store.publish_exposure_inventory(directory, first_assembly, created_at=CREATED_AT)
    older = write_chain(directory, first_assembly.inventory_id, [("est",)])
    second_assembly = assemble(interpret(tmp_path / "b", job=("2025-06-01T00:00:00+00:00", "2025-07-02T00:00:00+00:00")))
    store.publish_exposure_inventory(directory, second_assembly, created_at=CREATED_AT)
    write_chain(directory, second_assembly.inventory_id, [()], predecessor=older)
    declaration_set = load(directory, second_assembly.inventory_id).declaration_set
    assert classify(second_assembly, declaration_set).classification is ExposureClass.RETROSPECTIVE_EXPOSED
    bare = DeclarationSet((make_declaration(1, None, inventory_id=second_assembly.inventory_id),), True)      # sans report : E3-A l'accepte
    assert classify(second_assembly, bare).classification is ExposureClass.UNDETERMINED


def test_a_non_hash_linked_terminal_chain_makes_f6_not_met_through_the_loaded_set(tmp_path):
    directory = campaign(tmp_path)
    assembly = assemble(interpret(tmp_path / "a", job=("2025-06-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00")))
    store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    write_chain(directory, assembly.inventory_id, [(), ()], prev_hash_override={2: h("wrong")})
    result = classify(assembly, load(directory, assembly.inventory_id).declaration_set)
    assert [c.status.value for c in result.conditions if c.condition == "F6"] == ["NOT_MET"]


# ── Brouillon de report (jamais une publication) ──────────────────────────────────────────────────────────────────────

def test_the_draft_proposes_the_pin_the_renumbered_exposures_and_the_t_sel_floor(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path, first_specs=(("est",), ("unr",)),
                                                      second_specs=(("est",),))
    lineage = load(directory, second)
    third_id = "8" * 64
    draft = b6.draft_first_declaration_carry(lineage, third_id)
    assert draft.carried_from == b6.CarriedFrom(second, 1, compute_declaration_id(newer[-1].declaration), newer[-1].content_hash)
    assert [e.source_id for e in draft.declared_exposures] == [f"declared:0001:{i:04d}" for i in range(1, len(draft.declared_exposures) + 1)]
    assert [(e.status, e.overlap) for e in draft.declared_exposures] == [(e.status, e.overlap) for e in newer[-1].declaration.declared_exposures]
    assert draft.minimum_t_sel_utc is None


def test_the_draft_floor_is_the_maximum_declared_t_sel_of_the_terminal_chain(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path, second_specs=(("est",), {"t_sel": T_SEL}, {"t_sel": "2026-10-19T00:00:00+00:00"}))
    draft = b6.draft_first_declaration_carry(load(directory, second), "8" * 64)
    assert draft.minimum_t_sel_utc == "2026-10-20T00:00:00.000000Z"


def test_a_draft_roundtrips_through_the_loader_once_written_by_a_future_publisher(tmp_path):
    """Le brouillon n'écrit rien ; les octets qu'un futur publicateur (E3-C) écrirait sont acceptés par le chargeur."""
    directory, first, second, older, newer = two_chains(tmp_path, first_specs=(("est",), ("unr",)))
    third = a0_for(tmp_path, directory, 3)
    draft = b6.draft_first_declaration_carry(load(directory, second), third)
    declaration = make_declaration(1, None, inventory_id=third, exposures=list(draft.declared_exposures),
                                   t_sel=draft.minimum_t_sel_utc)
    path = b6.declaration_path(directory, third, 1)
    path.parent.mkdir(parents=True)
    path.write_bytes(b6.serialize_declaration_envelope(envelope_of(declaration, carried_from=draft.carried_from.to_record())))
    assert load(directory, third).state is b6.LineageState.CURRENT_IS_TERMINAL


def test_the_draft_without_any_lineage_has_nothing_to_carry(tmp_path):
    draft = b6.draft_first_declaration_carry(load(campaign(tmp_path), INVENTORY_ID), INVENTORY_ID)
    assert draft.carried_from is None and draft.declared_exposures == () and draft.minimum_t_sel_utc is None


def test_the_draft_refuses_an_inventory_that_already_has_a_chain_or_is_malformed(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path)
    lineage = load(directory, second)
    with pytest.raises(b6.LineageError) as refusal:
        b6.draft_first_declaration_carry(lineage, first)
    assert refusal.value.failure is b6.LineageFailure.INVENTORY_REVERSION
    with pytest.raises(ValueError):
        b6.draft_first_declaration_carry(lineage, "short")
    with pytest.raises(TypeError):
        b6.draft_first_declaration_carry("not a lineage", "8" * 64)


def test_a_carry_over_exactly_at_the_format_capacity_is_accepted(tmp_path):
    directory = campaign(tmp_path)
    first = a0_for(tmp_path, directory, 1)
    write_chain(directory, first, [("est",) * 5000, ("est",) * 4999])                  # 9 999 expositions : la capacité exacte
    draft = b6.draft_first_declaration_carry(load(directory, first), "8" * 64)
    assert len(draft.declared_exposures) == 9999 and draft.declared_exposures[-1].source_id == "declared:0001:9999"
    assert make_declaration(1, None, inventory_id="8" * 64, exposures=draft.declared_exposures).declared_exposures == draft.declared_exposures


class _Flagged:
    def __init__(self, info):
        self._info = info
        self.st_file_attributes = 0x400

    def __getattr__(self, name):
        return getattr(self._info, name)


def test_a_reparse_point_flag_on_a_declaration_file_is_refused_like_a_link(tmp_path, monkeypatch):
    directory, inventory_id, (entry,) = chain_ready(tmp_path)
    real = os.lstat
    monkeypatch.setattr(os, "lstat", lambda p, *a, **k: _Flagged(real(p, *a, **k)) if os.fspath(p).endswith("declaration_0001.json")
                        else real(p, *a, **k))
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.LINK_OR_REPARSE_POINT


def test_a_carry_over_beyond_the_format_capacity_is_refused_never_truncated_or_split(tmp_path):
    directory = campaign(tmp_path)
    first = a0_for(tmp_path, directory, 1)
    write_chain(directory, first, [("est",) * 5000, ("est",) * 5000])                  # 10 000 expositions déclarées au total
    with pytest.raises(b6.LineageError) as refusal:
        b6.draft_first_declaration_carry(load(directory, first), "8" * 64)
    assert refusal.value.failure is b6.LineageFailure.CARRY_OVER_TOO_LARGE


# ── Attestations : chemins, slots denses, lecture stricte, jamais d'écrasement ────────────────────────────────────────

def test_successive_attestation_slots_are_listed_densely_and_never_overwritten(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    for seq, payload in ((1, {"a": 1}), (2, {"a": 2}), (3, {"a": 3})):
        b6.attestation_path(directory, inventory_id, seq).write_bytes(adr_bytes(payload))
    (chain,) = load(directory, inventory_id).chains
    assert [(slot.seq, slot.path.name) for slot in chain.attestation_slots] == [(1, "attestation_0001.json"), (2, "attestation_0002.json"),
                                                                                  (3, "attestation_0003.json")]
    read = b6.read_attestation_slot(directory, inventory_id, 2)
    assert read.value == {"a": 2} and read.file_sha256 == chain.attestation_slots[1].file_sha256 == hashlib.sha256(adr_bytes({"a": 2})).hexdigest()


def test_attestation_slots_must_be_dense_and_well_formed(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 2).write_bytes(adr_bytes({"a": 2}))
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.ATTESTATION_GAP
    b6.attestation_path(directory, inventory_id, 2).unlink()
    b6.attestation_path(directory, inventory_id, 1).write_bytes(b"[]\n")
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.ATTESTATION_INVALID
    b6.attestation_path(directory, inventory_id, 1).write_bytes(b"{")
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.ATTESTATION_INVALID


def test_read_attestation_slot_is_strict(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    with pytest.raises(store.ExposureStoreError) as absent:
        b6.read_attestation_slot(directory, inventory_id, 1)
    assert absent.value.failure is store.StoreFailure.ABSENT
    b6.attestation_path(directory, inventory_id, 1).write_bytes(b"[1]\n")
    with pytest.raises(store.ExposureStoreError) as mistyped:
        b6.read_attestation_slot(directory, inventory_id, 1)
    assert mistyped.value.failure is store.StoreFailure.SCHEMA


# ── Le chargeur est l'unique source d'un `DeclarationSet` ; le lot n'écrit jamais ───────────────────────────────────────

import ast  # noqa: E402
import inspect  # noqa: E402
from pathlib import Path  # noqa: E402

_B6_SOURCE = Path(b6.__file__).read_text(encoding="utf-8")
_B6_TREE = ast.parse(_B6_SOURCE)


def enclosing_functions(node_type_name: str):
    found = []
    for function in ast.walk(_B6_TREE):
        if isinstance(function, ast.FunctionDef):
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == node_type_name:
                    found.append(function.name)
    return found


def callers_of(name: str) -> set:
    return {function.name for function in ast.walk(_B6_TREE) if isinstance(function, ast.FunctionDef)
            and any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == name for n in ast.walk(function))}


def test_declaration_set_is_built_in_one_private_function_called_only_by_the_lineage_loader():
    """Deux sites de construction seulement : `_declaration_set` (remis par le chargeur) et `_probe_declaration_set` (sonde de géométrie,
    construite par le brouillon et consommée sur place par `_check_declared_geometry` qui ne retourne rien : elle ne quitte jamais le module)."""
    assert set(enclosing_functions("DeclarationSet")) == {"_declaration_set", "_probe_declaration_set"}
    assert callers_of("_declaration_set") == {"load_declaration_lineage"}
    assert callers_of("_probe_declaration_set") == {"draft_first_declaration_carry"}
    (checker,) = [f for f in ast.walk(_B6_TREE) if isinstance(f, ast.FunctionDef) and f.name == "_check_declared_geometry"]
    assert all(n.value is None for n in ast.walk(checker) if isinstance(n, ast.Return))


def test_no_public_function_returns_a_declaration_set_except_through_the_loaded_lineage():
    for name, function in inspect.getmembers(b6, inspect.isfunction):
        if not name.startswith("_") and function.__module__ == b6.__name__:
            assert "DeclarationSet" not in str(inspect.signature(function).return_annotation), name
    fields = {f.name: str(f.type) for f in dataclasses.fields(b6.LoadedLineage)}
    assert "DeclarationSet" in fields["declaration_set"]


def test_the_b6_module_never_writes_publishes_or_deletes():
    forbidden_methods = {"write_bytes", "write_text", "unlink", "rmdir", "mkdir", "touch", "rename", "symlink_to", "hardlink_to", "truncate"}
    forbidden_os = {"replace", "rename", "remove", "unlink", "rmdir", "mkdir", "makedirs", "link", "symlink", "fsync", "write", "open",
                    "ftruncate", "chmod", "utime"}
    forbidden_names = {"open", "save_exclusive", "save_atomic", "save_atomic_overwrite"}
    calls = [node for node in ast.walk(_B6_TREE) if isinstance(node, ast.Call)]
    methods = {c.func.attr for c in calls if isinstance(c.func, ast.Attribute)}
    os_calls = {c.func.attr for c in calls if isinstance(c.func, ast.Attribute) and getattr(c.func.value, "id", None) == "os"}
    names = {c.func.id for c in calls if isinstance(c.func, ast.Name)}
    assert not methods & forbidden_methods and not os_calls & forbidden_os and not names & forbidden_names, (methods, os_calls, names)
    imported = {alias.name.split(".")[0] for node in ast.walk(_B6_TREE) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(_B6_TREE) if isinstance(node, ast.ImportFrom)}
    assert imported <= {"__future__", "dataclasses", "hashlib", "json", "os", "re", "stat", "collections", "enum", "pathlib", "typing",
                        "gate_v_exposure_scan", "gate_v_exposure_store", "gate_v_final_holdout_protocol"}, imported


def test_loading_the_lineage_changes_nothing_on_disk(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path)
    (directory / "exposure" / second / "attestation_0001.json").write_bytes(adr_bytes({"a": 1}))

    def snapshot():
        return sorted((str(p.relative_to(directory)), p.stat().st_size, p.stat().st_mtime_ns) for p in directory.rglob("*") if p.is_file())

    before = snapshot()
    load(directory, second)
    assert snapshot() == before


def test_the_loaded_lineage_and_its_parts_are_immutable(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    lineage = load(directory, inventory_id)
    for target, field in ((lineage, "state"), (lineage.chains[0], "hash_linked"), (lineage.chains[0].tip, "created_at")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(target, field, None)


def junction_or_skip(link, target):
    import subprocess
    if os.name != "nt":
        pytest.skip("jonction Windows uniquement")
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    if done.returncode != 0:
        pytest.skip("jonction non disponible")


def test_a_junction_replacing_an_inventory_directory_is_refused_and_never_followed(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "declaration_0001.json").write_bytes(b"{}")
    junction = directory / "exposure" / ("5" * 64)
    junction_or_skip(junction, elsewhere)
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.LINK_OR_REPARSE_POINT


def test_a_junction_replacing_exposure_is_refused(tmp_path):
    directory = campaign(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    junction_or_skip(directory / "exposure", elsewhere)
    assert refused_lineage(directory, INVENTORY_ID).failure is b6.LineageFailure.LINK_OR_REPARSE_POINT

from gate_v_final_holdout_protocol import normalize_utc_instant  # noqa: E402


# ── Tests ajoutés par la campagne de mutation (mutants survivants) ───────────────────────────────────────────────────

def test_the_builder_refuses_a_carried_from_that_designates_the_chain_of_the_declaration_itself():
    with pytest.raises(ValueError):
        envelope_of(make_declaration(), carried_from=dict(CARRIED, inventory_id=INVENTORY_ID))


def test_carried_from_is_refused_when_reading_a_declaration_that_is_not_the_first_of_its_chain():
    second = make_declaration(2, h("previous-id"), exposures=[declared_finding(2, 1)])
    raw = b6.serialize_declaration_envelope(envelope_of(second, prev_hash=h("previous-hash")))
    assert b6.parse_declaration_file(raw, inventory_id=INVENTORY_ID, seq=2, campaign_id=CURRENT).declaration.declaration_seq == 2
    assert parse_refused(rewrite(raw, lambda e: e.update(carried_from=CARRIED)), seq=2).failure is store.StoreFailure.SCHEMA


def test_a_chain_that_takes_over_itself_is_a_cycle_even_beside_a_valid_root(tmp_path):
    directory = campaign(tmp_path)
    root, looping = a0_for(tmp_path, directory, 1), a0_for(tmp_path, directory, 2)
    write_chain(directory, root, [("est",)])
    entry = write_chain(directory, looping, [("est",)], carried_override=dict(CARRIED, inventory_id=root))[0]
    entry.path.write_bytes(rewrite(entry.path.read_bytes(), lambda e: e["carried_from"].update(inventory_id=looping)))
    assert refused_lineage(directory, root).failure is b6.LineageFailure.CYCLE


@pytest.mark.parametrize("name, alter", [
    ("overlap", lambda f: dataclasses.replace(f, overlap=OverlapVerdict.NO_OVERLAP)),
    ("window_end", lambda f: dataclasses.replace(f, window_end_utc=normalize_utc_instant("2026-02-11T00:00:00+00:00"))),
    ("window_start", lambda f: dataclasses.replace(f, window_start_utc=normalize_utc_instant("2026-02-02T00:00:00+00:00"))),
])
def test_a_carried_exposure_that_differs_from_the_original_by_any_single_field_is_not_the_same_exposure(tmp_path, name, alter):
    directory, first, second, older, newer = two_chains(tmp_path, first_specs=(("est",),), second_specs=((),), alter_carried=alter)
    assert refused_lineage(directory, second).failure is b6.LineageFailure.CARRY_OVER_OMITTED


def test_an_a0_of_another_inventory_never_stands_in_for_the_a0_of_a_chain(tmp_path):
    directory = campaign(tmp_path)
    a0_for(tmp_path, directory, 1)                                    # A0 valide mais d'un AUTRE inventaire, antérieur à la déclaration
    write_chain(directory, INVENTORY_ID, [("est",)])
    assert refused_lineage(directory, INVENTORY_ID).failure is b6.LineageFailure.A0_MISSING


# ── Corrections issues de la revue A ─────────────────────────────────────────────────────────────────────────────────

def test_read_attestation_slot_refuses_a_slot_reached_through_a_junctioned_exposure_directory(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "other").mkdir()
    directory, inventory_id, _ = chain_ready(tmp_path / "real")
    (directory / "exposure" / inventory_id / "attestation_0001.json").write_bytes(adr_bytes({"note": "x"}))
    other = campaign(tmp_path / "other")
    junction_or_skip(other / "exposure", directory / "exposure")
    with pytest.raises(store.ExposureStoreError) as refusal:
        b6.read_attestation_slot(other, inventory_id, 1)
    assert refusal.value.failure is store.StoreFailure.LINK_OR_REPARSE_POINT


def test_attestations_are_read_once_even_when_unreadable_a0_files_have_to_be_checked_against_them(tmp_path, monkeypatch):
    directory, inventory_id, _ = chain_ready(tmp_path)
    (directory / "exposure" / inventory_id / "attestation_0001.json").write_bytes(adr_bytes({"note": "x"}))
    (directory / "exposure" / f"inventory_{'9' * 64}.json").write_bytes(b"{")
    (directory / "exposure" / f"inventory_{'8' * 64}.json").write_bytes(b"{")
    real, reads = b6.read_strict_file, []
    monkeypatch.setattr(b6, "read_strict_file", lambda path, **k: (reads.append(Path(path).name), real(path, **k))[1])
    load(directory, inventory_id)
    assert reads.count("attestation_0001.json") == 1


def test_the_cumulative_size_of_the_files_to_read_is_capped_before_any_deep_read(tmp_path, monkeypatch):
    directory, inventory_id, _ = chain_ready(tmp_path)
    monkeypatch.setattr(b6, "MAX_TOTAL_READ_BYTES", 10)
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.TOO_MUCH_DATA


def test_a_permission_error_while_observing_exposure_is_a_typed_lineage_refusal(tmp_path, monkeypatch):
    directory, inventory_id, _ = chain_ready(tmp_path)
    real = os.lstat

    def denied(p, *a, **k):
        if os.fspath(p).endswith("exposure"):
            raise PermissionError("denied")
        return real(p, *a, **k)

    monkeypatch.setattr(os, "lstat", denied)
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.BAD_DIRECTORY


# ── Liaison de campagne (contexte validé du A0) : un A0 d'une autre campagne n'est jamais celui de celle-ci ─────────────

def test_the_loader_demands_the_expected_campaign_id_as_a_validated_argument(tmp_path):
    directory = campaign(tmp_path)
    with pytest.raises(TypeError):
        b6.load_declaration_lineage(directory, current_inventory_id=INVENTORY_ID, pinned_a0_hashes=frozenset(), admitted_attestation=None)   # obligatoire, sans valeur par défaut
    with pytest.raises(TypeError):
        b6.load_declaration_lineage(directory, current_inventory_id=INVENTORY_ID, campaign_id=7, pinned_a0_hashes=frozenset(), admitted_attestation=None)
    with pytest.raises(ValueError):
        b6.load_declaration_lineage(directory, current_inventory_id=INVENTORY_ID, campaign_id=" ", pinned_a0_hashes=frozenset(), admitted_attestation=None)


def test_a_chain_whose_only_a0_belongs_to_another_campaign_is_refused_and_the_foreign_a0_is_never_loaded(tmp_path):
    """Copie simultanée de l'A0 et de la chaîne d'une campagne A vers la campagne B : refusée par le contexte validé de l'A0."""
    directory = campaign(tmp_path)
    inventory_id = a0_for(tmp_path, directory, 1, context=OTHER_CAMPAIGN)
    write_chain(directory, inventory_id, [("est",)])
    error = refused_lineage(directory, inventory_id)
    assert error.failure is b6.LineageFailure.CAMPAIGN_MISMATCH


def test_the_expected_campaign_must_equal_the_one_recorded_in_the_a0(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    assert load(directory, inventory_id).state is b6.LineageState.CURRENT_IS_TERMINAL
    assert refused_lineage(directory, inventory_id, campaign_id="campaign_other").failure is b6.LineageFailure.CAMPAIGN_MISMATCH


def test_a_copied_chain_without_an_a0_of_this_campaign_is_refused_as_missing_a0(tmp_path):
    directory = campaign(tmp_path)
    write_chain(directory, INVENTORY_ID, [("est",)])                       # chaîne copiée seule : aucun A0 du tout
    assert refused_lineage(directory, INVENTORY_ID).failure is b6.LineageFailure.A0_MISSING


def test_a_foreign_a0_beside_a_legitimate_one_is_ignored_recorded_and_never_returned(tmp_path):
    directory = campaign(tmp_path)
    own = a0_for(tmp_path, directory, 1)
    (tmp_path / "foreign").mkdir()
    foreign = a0_for(tmp_path / "foreign", directory, 1, created_at="2026-10-19T00:00:00+00:00", context=OTHER_CAMPAIGN)
    assert foreign == own                                                 # même inventory_id scientifique, A0 de contextes distincts
    write_chain(directory, own, [("est",)])
    lineage = load(directory, own)
    assert {i.own_context.current_campaign_id for i in lineage.inventories} == {CURRENT}
    assert [e.kind for e in lineage.ignored] == [b6.IgnoredKind.FOREIGN_CAMPAIGN_INVENTORY]


def test_a_chain_written_for_this_campaign_after_its_own_a0_is_accepted(tmp_path):
    """Contrôle positif. L'ancienne limite du §55.2 (« la chaîne ne porte aucune campagne ») est fermée par D2 (23.31.1) : la copie
    d'une chaîne d'une campagne jumelle (même W, même `inventory_id`) est refusée, voir les tests `test_copy_*`."""
    directory = campaign(tmp_path)
    inventory_id = a0_for(tmp_path, directory, 1)
    entries = write_chain(directory, inventory_id, [("est",)])
    assert load(directory, inventory_id).state is b6.LineageState.CURRENT_IS_TERMINAL and entries


def test_a_historical_non_terminal_chain_copied_from_another_campaign_is_refused(tmp_path):
    directory = campaign(tmp_path)
    old = a0_for(tmp_path, directory, 1, context=OTHER_CAMPAIGN)          # A0 et chaîne historiques venus d'ailleurs
    older = write_chain(directory, old, [("est",)])
    newest = a0_for(tmp_path, directory, 2)
    write_chain(directory, newest, [("est",)], predecessor=older)
    assert refused_lineage(directory, newest).failure is b6.LineageFailure.CAMPAIGN_MISMATCH


def test_a_chain_copied_from_an_earlier_campaign_must_still_follow_an_a0_of_this_one(tmp_path):
    directory = campaign(tmp_path)
    inventory_id = a0_for(tmp_path, directory, 1, created_at="2026-10-22T00:00:00+00:00")        # A0 de CETTE campagne, postérieur
    write_chain(directory, inventory_id, [("est",)])
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.A0_MISSING


# ── Attestations : octets stricts, point fixe normatif, aucun repli (ADR 23.29.3 / 23.29.4) ──────────────────────────────

ATTESTATION_PAYLOAD = {"z": 1, "a": {"y": "é", "b": 2}}                 # clés non triées et caractère non ASCII, schéma libre (E3-E)

NON_NORMATIVE_ATTESTATIONS = [
    ("indent4", lambda p: (json.dumps(p, sort_keys=True, ensure_ascii=False, indent=4) + "\n").encode("utf-8")),
    ("compact", lambda p: (json.dumps(p, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")),
    ("unsorted_keys", lambda p: (json.dumps(p, sort_keys=False, ensure_ascii=False, indent=2) + "\n").encode("utf-8")),
    ("no_final_newline", lambda p: adr_bytes(p)[:-1]),
    ("crlf", lambda p: adr_bytes(p).replace(b"\n", b"\r\n")),
    ("escaped_non_ascii", lambda p: (json.dumps(p, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode("utf-8")),
]


@pytest.mark.parametrize("name, transform", NON_NORMATIVE_ATTESTATIONS, ids=[case[0] for case in NON_NORMATIVE_ATTESTATIONS])
def test_a_non_normative_attestation_is_refused_by_the_loader_and_by_the_reader(tmp_path, name, transform):
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(transform(ATTESTATION_PAYLOAD))
    error = refused_lineage(directory, inventory_id)
    assert error.failure is b6.LineageFailure.ATTESTATION_INVALID and error.cause is store.StoreFailure.NOT_FIXED_POINT
    with pytest.raises(store.ExposureStoreError) as refusal:
        b6.read_attestation_slot(directory, inventory_id, 1)
    assert refusal.value.failure is store.StoreFailure.NOT_FIXED_POINT


def test_the_normative_attestation_is_accepted_and_returned_without_interpreting_its_schema(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes(ATTESTATION_PAYLOAD))
    (chain,) = load(directory, inventory_id).chains
    assert b6.read_attestation_slot(directory, inventory_id, 1).value == ATTESTATION_PAYLOAD and len(chain.attestation_slots) == 1


@pytest.mark.parametrize("name, raw", [
    ("bom", b"\xef\xbb\xbf{}\n"),
    ("not_utf8", b'{"a": "\xff"}\n'),
    ("duplicate_key", b'{"a": 1, "a": 2}\n'),
    ("nan", b'{"a": NaN}\n'),
    ("infinity", b'{"a": Infinity}\n'),
])
def test_strict_json_defects_in_an_attestation_are_refused_by_the_loader_and_by_the_reader(tmp_path, name, raw):
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(raw)
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.ATTESTATION_INVALID
    with pytest.raises(store.ExposureStoreError) as refusal:
        b6.read_attestation_slot(directory, inventory_id, 1)
    assert refusal.value.failure is store.StoreFailure.NOT_JSON


def test_a_corrupt_highest_slot_refuses_the_whole_lineage_instead_of_falling_back_to_an_older_slot(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"a": 1}))
    b6.attestation_path(directory, inventory_id, 2).write_bytes(NON_NORMATIVE_ATTESTATIONS[0][1]({"a": 2}))
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.ATTESTATION_INVALID


def test_the_selectable_attestation_is_the_highest_slot_of_the_terminal_chain_and_pins_are_not_evaluated(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    assert b6.highest_attestation_slot(load(directory, inventory_id)) is None                        # aucun slot : aucune attestation
    for seq in (1, 2, 3):
        b6.attestation_path(directory, inventory_id, seq).write_bytes(adr_bytes({"seq": seq}))
    slot = b6.highest_attestation_slot(load(directory, inventory_id))
    assert slot.seq == 3 and slot.path.name == "attestation_0003.json"
    assert b6.highest_attestation_slot(load(campaign(tmp_path / "empty") if (tmp_path / "empty").mkdir() is None else None, INVENTORY_ID)) is None


# ── Géométrie des expositions déclarées vis-à-vis de W (E3-A fait foi : `ClassificationInput`) ─────────────────────────

OK_GEOMETRIES = ["est", "unr", "ok_before_adjacent", "ok_after_adjacent", "ok_disjoint", "ok_overlap_by_one_second", "ok_enclosing"]
BAD_GEOMETRIES = ["bad_no_overlap_inside", "bad_overlap_outside", "bad_overlap_adjacent", "bad_no_overlap_by_one_second"]


@pytest.mark.parametrize("template", OK_GEOMETRIES)
def test_a_declared_exposure_whose_verdict_agrees_with_its_window_is_usable(tmp_path, template):
    directory = campaign(tmp_path)
    inventory_id = a0_for(tmp_path, directory, 1)
    write_chain(directory, inventory_id, [(template,)])
    lineage = load(directory, inventory_id)
    assert lineage.state is b6.LineageState.CURRENT_IS_TERMINAL and lineage.declaration_set is not None
    assert classify(assemble_for(tmp_path, 1), lineage.declaration_set) is not None


@pytest.mark.parametrize("template", BAD_GEOMETRIES)
def test_a_declared_exposure_whose_verdict_contradicts_its_window_is_refused_at_loading_never_handed_over(tmp_path, template):
    directory = campaign(tmp_path)
    inventory_id = a0_for(tmp_path, directory, 1)
    write_chain(directory, inventory_id, [(template,)])
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.DECLARED_GEOMETRY_CONTRADICTION


def test_a_contradictory_exposure_in_an_older_chain_is_refused_when_it_is_carried_into_the_terminal_chain(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path, first_specs=(("bad_no_overlap_inside",),), second_specs=((),))
    assert refused_lineage(directory, second).failure is b6.LineageFailure.DECLARED_GEOMETRY_CONTRADICTION


def test_the_carry_over_draft_refuses_a_contradictory_exposure_once_the_new_inventory_window_is_known(tmp_path):
    directory = campaign(tmp_path)
    first = a0_for(tmp_path, directory, 1)
    write_chain(directory, first, [("bad_no_overlap_inside",)])
    third = a0_for(tmp_path, directory, 3)
    lineage = load(directory, third)                                      # l'inventaire courant n'a pas encore de chaîne
    assert lineage.state is b6.LineageState.NO_CHAIN_FOR_CURRENT
    with pytest.raises(b6.LineageError) as refusal:
        b6.draft_first_declaration_carry(lineage, third)
    assert refusal.value.failure is b6.LineageFailure.DECLARED_GEOMETRY_CONTRADICTION


def test_the_carry_over_draft_of_a_coherent_lineage_is_unchanged_by_the_geometry_check(tmp_path):
    directory = campaign(tmp_path)
    first = a0_for(tmp_path, directory, 1)
    write_chain(directory, first, [("est",), ("ok_disjoint", "unr")])
    third = a0_for(tmp_path, directory, 3)
    draft = b6.draft_first_declaration_carry(load(directory, third), third)
    assert len(draft.declared_exposures) == 3


@pytest.mark.parametrize("form", [
    lambda bad: {bad: 1},                                  # le hash est une CLÉ
    lambda bad: {"pins": [bad]},                           # dans une liste
    lambda bad: {"a": {"b": [{"c": bad}]}},                # imbriqué à toute profondeur
    lambda bad: {"inventory_content_hash": bad},           # valeur directe
], ids=["as_key", "in_list", "nested", "direct_value"])
def test_an_unreadable_a0_cited_anywhere_in_an_attestation_is_an_unresolved_pin_reference(tmp_path, form):
    """Le schéma d'attestation relève d'E3-E : un hash cité, quelle que soit sa place, est une référence NON RÉSOLUE, jamais une preuve
    d'épinglage ni d'absence d'épinglage ; le chargeur refuse (23.31.3)."""
    directory, inventory_id, _ = chain_ready(tmp_path)
    bad_hash = "9" * 64
    (directory / "exposure" / f"inventory_{bad_hash}.json").write_bytes(b"{")
    assert load(directory, inventory_id).state is b6.LineageState.CURRENT_IS_TERMINAL              # sans attestation : orphelin consigné
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes(form(bad_hash)))
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.A0_PIN_UNRESOLVED


# ── Revue A de clôture : épinglages fournis par l'appelant, sélection, citation, taxonomie ─────────────────────────────

def test_the_caller_must_state_its_pinned_hashes_explicitly(tmp_path):
    directory = campaign(tmp_path)
    with pytest.raises(TypeError):
        b6.load_declaration_lineage(directory, current_inventory_id=INVENTORY_ID, campaign_id=CURRENT, admitted_attestation=None)       # jamais d'oubli silencieux


def test_a_pinned_a0_that_was_deleted_is_refused_as_missing_never_silently_accepted(tmp_path):
    """Supprimer un A0 épinglé ne doit pas être plus avantageux que le tronquer."""
    directory, inventory_id, _ = chain_ready(tmp_path)
    (own,) = load(directory, inventory_id).inventories
    assert load(directory, inventory_id, pinned_a0_hashes=frozenset({own.inventory_content_hash})).state is b6.LineageState.CURRENT_IS_TERMINAL
    assert refused_lineage(directory, inventory_id, pinned_a0_hashes=frozenset({"7" * 64})).failure is b6.LineageFailure.PINNED_A0_MISSING


def test_a_pinned_a0_that_belongs_to_another_campaign_is_a_campaign_mismatch_not_a_valid_pin(tmp_path):
    directory = campaign(tmp_path)
    own = a0_for(tmp_path, directory, 1)
    (tmp_path / "foreign").mkdir()
    a0_for(tmp_path / "foreign", directory, 1, created_at="2026-10-19T00:00:00+00:00", context=OTHER_CAMPAIGN)
    write_chain(directory, own, [("est",)])
    foreign_hash = next(e.relative_path for e in load(directory, own).ignored).split("inventory_")[1][:-len(".json")]
    assert refused_lineage(directory, own, pinned_a0_hashes=frozenset({foreign_hash})).failure is b6.LineageFailure.CAMPAIGN_MISMATCH


def test_the_highest_attestation_slot_is_only_designated_for_a_current_inventory_that_is_the_terminal_chain(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path)
    b6.attestation_path(directory, second, 1).write_bytes(adr_bytes({"seq": 1}))
    assert b6.highest_attestation_slot(load(directory, second)).seq == 1
    third = a0_for(tmp_path, directory, 3)                                 # l'inventaire courant n'a pas encore de chaîne : la terminale est périmée
    stale = load(directory, third)
    assert stale.state is b6.LineageState.NO_CHAIN_FOR_CURRENT and b6.highest_attestation_slot(stale) is None


@pytest.mark.parametrize("form", [
    lambda bad: {"a": "sha256:" + bad},
    lambda bad: {"b": "inventory_" + bad + ".json"},
    lambda bad: {"c": "x" * 5 + bad + "y" * 5},
    lambda bad: {"d": bad + bad},                                          # deux fois, collés : chaque fenêtre de 64 caractères compte
])
def test_a_hash_embedded_in_a_longer_attestation_string_is_still_an_unresolved_reference(tmp_path, form):
    directory, inventory_id, _ = chain_ready(tmp_path)
    bad_hash = "9" * 64
    (directory / "exposure" / f"inventory_{bad_hash}.json").write_bytes(b"{")
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes(form(bad_hash)))
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.A0_PIN_UNRESOLVED


def test_a_near_miss_of_the_hash_is_not_a_reference_to_it(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    bad_hash = "9" * 64
    (directory / "exposure" / f"inventory_{bad_hash}.json").write_bytes(b"{")
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"a": "9" * 63 + "8", "b": "9" * 63}))
    assert load(directory, inventory_id).state is b6.LineageState.CURRENT_IS_TERMINAL


@pytest.mark.parametrize("cause, failure", [
    (store.StoreFailure.UNREADABLE, b6.LineageFailure.BAD_DIRECTORY),
    (store.StoreFailure.UNSTABLE, b6.LineageFailure.BAD_DIRECTORY),
    (store.StoreFailure.ABSENT, b6.LineageFailure.BAD_DIRECTORY),
    (store.StoreFailure.LINK_OR_REPARSE_POINT, b6.LineageFailure.LINK_OR_REPARSE_POINT),
    (store.StoreFailure.NOT_REGULAR_FILE, b6.LineageFailure.NOT_REGULAR),
])
def test_an_io_or_structure_failure_on_an_a0_is_a_refusal_never_an_orphan(tmp_path, monkeypatch, cause, failure):
    """Seules les défaillances de CONTENU font d'un A0 un orphelin consigné ; une erreur d'E/S ou de structure est un refus, comme dans B3."""
    directory, inventory_id, _ = chain_ready(tmp_path)

    def broken(path, **kwargs):
        raise store.ExposureStoreError(cause, "simulé")

    monkeypatch.setattr(b6, "load_exposure_inventory", broken)
    assert refused_lineage(directory, inventory_id).failure is failure


def test_a_lineage_whose_inventories_have_different_windows_is_refused_because_w_is_fixed_for_a_campaign(tmp_path):
    """23.29.2 : « W étant fixe pour une campagne » est la prémisse de la validité des verdicts reportés."""
    directory = campaign(tmp_path)
    first = a0_for(tmp_path, directory, 1)
    older = write_chain(directory, first, [("est",)])
    other_window = ("2026-01-01T00:00:00+00:00", "2026-05-01T00:00:00+00:00")
    assembly = assemble(interpret(tmp_path / "src_w2", window=other_window))
    store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    write_chain(directory, assembly.inventory_id, [("est",)], predecessor=older)
    assert refused_lineage(directory, assembly.inventory_id).failure is b6.LineageFailure.WINDOW_NOT_FIXED


def test_a_late_own_a0_beside_an_earlier_foreign_one_is_a_missing_a0_not_a_campaign_mismatch(tmp_path):
    """L'étiquette CAMPAIGN_MISMATCH est réservée au cas où AUCUN A0 de cette campagne n'existe pour l'inventaire."""
    directory = campaign(tmp_path)
    own = a0_for(tmp_path, directory, 1, created_at="2026-10-22T00:00:00+00:00")                 # postérieur à la première déclaration
    (tmp_path / "foreign").mkdir()
    a0_for(tmp_path / "foreign", directory, 1, created_at="2026-10-19T00:00:00+00:00", context=OTHER_CAMPAIGN)
    write_chain(directory, own, [("est",)])
    assert refused_lineage(directory, own).failure is b6.LineageFailure.A0_MISSING


# ── D2 (ADR 0025 23.31.1) : `campaign_id` dans l'enveloppe, couvert par le hash de contenu, jamais par `declaration_id` ─────────

import shutil  # noqa: E402

CAMPAIGN_A, CAMPAIGN_B = "campaign_a", "campaign_b"


def campaign_envelope(declaration, campaign_id, **kwargs):
    return b6.build_declaration_envelope(declaration, campaign_id=campaign_id, prev_declaration_content_hash=kwargs.get("prev_hash"),
                                         carried_from=kwargs.get("carried_from"), created_at=kwargs.get("created_at", DECL_CREATED))


def test_the_envelope_carries_the_campaign_id_covered_by_the_content_hash_but_not_by_the_declaration_id():
    declaration = make_declaration(exposures=[declared_finding(1, 1)])
    mine, theirs = campaign_envelope(declaration, CAMPAIGN_A), campaign_envelope(declaration, CAMPAIGN_B)
    assert "campaign_id" in b6.DECLARATION_ENVELOPE_KEYS and mine["campaign_id"] == CAMPAIGN_A and "campaign_id" not in mine["declaration"]
    assert mine["declaration_id"] == theirs["declaration_id"] == compute_declaration_id(declaration)       # identité d'E3-A inchangée
    assert mine["declaration_content_hash"] != theirs["declaration_content_hash"]
    assert mine["declaration_content_hash"] == adr_hash(mine)                                              # recette de 23.29.1 inchangée


@pytest.mark.parametrize("bad", [None, 7, b"campaign_a", "", "   "])
def test_the_envelope_requires_a_non_empty_text_campaign_id(bad):
    with pytest.raises((TypeError, ValueError)):
        campaign_envelope(make_declaration(), bad)
    with pytest.raises(TypeError):
        b6.build_declaration_envelope(make_declaration(), prev_declaration_content_hash=None, carried_from=None, created_at=DECL_CREATED)


def test_reading_a_declaration_demands_the_expected_campaign_and_refuses_another():
    raw = b6.serialize_declaration_envelope(campaign_envelope(make_declaration(exposures=[declared_finding(1, 1)]), CAMPAIGN_A))
    assert b6.parse_declaration_file(raw, inventory_id=INVENTORY_ID, seq=1, campaign_id=CAMPAIGN_A).campaign_id == CAMPAIGN_A
    with pytest.raises(store.ExposureStoreError) as refusal:
        b6.parse_declaration_file(raw, inventory_id=INVENTORY_ID, seq=1, campaign_id=CAMPAIGN_B)
    assert refusal.value.failure is store.StoreFailure.CAMPAIGN_MISMATCH
    with pytest.raises(TypeError):
        b6.parse_declaration_file(raw, inventory_id=INVENTORY_ID, seq=1)                                  # jamais facultatif


@pytest.mark.parametrize("name, mutate", [
    ("missing", lambda e: e.pop("campaign_id")),
    ("blank", lambda e: e.update(campaign_id="  ")),
    ("not_text", lambda e: e.update(campaign_id=7)),
    ("null", lambda e: e.update(campaign_id=None)),
])
def test_an_envelope_with_a_missing_or_malformed_campaign_id_is_a_schema_violation_even_rehashed(name, mutate):
    raw = b6.serialize_declaration_envelope(campaign_envelope(make_declaration(exposures=[declared_finding(1, 1)]), CAMPAIGN_A))
    with pytest.raises(store.ExposureStoreError) as refusal:
        b6.parse_declaration_file(rewrite(raw, mutate), inventory_id=INVENTORY_ID, seq=1, campaign_id=CAMPAIGN_A)
    assert refusal.value.failure is store.StoreFailure.SCHEMA


def test_a_substituted_campaign_id_without_a_recomputed_hash_is_a_hash_mismatch():
    raw = b6.serialize_declaration_envelope(campaign_envelope(make_declaration(), CAMPAIGN_A))
    with pytest.raises(store.ExposureStoreError) as refusal:
        b6.parse_declaration_file(rewrite(raw, lambda e: e.update(campaign_id=CAMPAIGN_B), rehash=False), inventory_id=INVENTORY_ID, seq=1,
                                  campaign_id=CAMPAIGN_B)
    assert refusal.value.failure is store.StoreFailure.HASH_MISMATCH


# Copies entre campagnes : deux dossiers de campagne de MÊME `W` et de MÊME `inventory_id` (mêmes sources), contextes distincts.

def twin_campaigns(tmp_path, specs=(("est",),)):
    """Campagne `CURRENT` (dossier `m`) et campagne `campaign_other` (dossier `t`) : chacune son A0 légitime, même `inventory_id`, même W."""
    (tmp_path / "m").mkdir()
    (tmp_path / "t").mkdir()
    mine, theirs = campaign(tmp_path / "m"), campaign(tmp_path / "t")
    own = a0_for(tmp_path / "m", mine, 1)
    foreign = a0_for(tmp_path / "t", theirs, 1, context=OTHER_CAMPAIGN)
    assert own == foreign
    theirs_entries = write_chain(theirs, foreign, list(specs), campaign_id=OTHER_CAMPAIGN.current_campaign_id)
    return mine, theirs, own, theirs_entries


def test_copy_control_each_twin_campaign_loads_its_own_chain(tmp_path):
    mine, theirs, inventory_id, _ = twin_campaigns(tmp_path)
    write_chain(mine, inventory_id, [("est",)])
    assert load(mine, inventory_id).state is b6.LineageState.CURRENT_IS_TERMINAL
    assert load(theirs, inventory_id, campaign_id=OTHER_CAMPAIGN.current_campaign_id).state is b6.LineageState.CURRENT_IS_TERMINAL


def test_copy_1_a_whole_chain_copied_into_a_twin_campaign_with_its_own_legitimate_a0_is_refused(tmp_path):
    """Ancienne LIMITE du §55.2 (acceptée avant D2) : même W, même `inventory_id`, A0 légitime de la campagne réceptrice."""
    mine, theirs, inventory_id, _ = twin_campaigns(tmp_path)
    shutil.copytree(theirs / "exposure" / inventory_id, mine / "exposure" / inventory_id)
    error = refused_lineage(mine, inventory_id)
    assert error.failure is b6.LineageFailure.CAMPAIGN_MISMATCH and error.cause is store.StoreFailure.CAMPAIGN_MISMATCH


def test_copy_2_a_single_declaration_substituted_from_the_twin_campaign_is_refused(tmp_path):
    mine, theirs, inventory_id, _ = twin_campaigns(tmp_path, specs=(("est",), ("est",)))
    write_chain(mine, inventory_id, [("est",), ("est",)])
    shutil.copyfile(b6.declaration_path(theirs, inventory_id, 2), b6.declaration_path(mine, inventory_id, 2))
    assert refused_lineage(mine, inventory_id).failure is b6.LineageFailure.CAMPAIGN_MISMATCH


def test_copy_3_the_a0_and_the_chain_copied_together_are_refused(tmp_path):
    mine, theirs, inventory_id, _ = twin_campaigns(tmp_path)
    (foreign_a0,) = (theirs / "exposure").glob("inventory_*.json")
    for path in (mine / "exposure").glob("inventory_*.json"):
        path.unlink()
    shutil.copyfile(foreign_a0, mine / "exposure" / foreign_a0.name)
    shutil.copytree(theirs / "exposure" / inventory_id, mine / "exposure" / inventory_id)
    assert refused_lineage(mine, inventory_id).failure is b6.LineageFailure.CAMPAIGN_MISMATCH


def test_copy_4_a_historical_chain_copied_from_the_twin_campaign_under_a_successor_is_refused(tmp_path):
    mine, theirs, inventory_id, theirs_entries = twin_campaigns(tmp_path)
    shutil.copytree(theirs / "exposure" / inventory_id, mine / "exposure" / inventory_id)
    newest = a0_for(tmp_path / "m", mine, 2)
    write_chain(mine, newest, [("est",)], predecessor=theirs_entries)
    assert refused_lineage(mine, newest).failure is b6.LineageFailure.CAMPAIGN_MISMATCH


def test_copy_5_a_lineage_read_under_another_expected_campaign_is_refused_by_the_declarations_themselves(tmp_path):
    mine, theirs, inventory_id, _ = twin_campaigns(tmp_path)
    for path in (theirs / "exposure").glob("inventory_*.json"):          # même sans aucun A0, la chaîne révèle sa campagne
        path.unlink()
    error = refused_lineage(theirs, inventory_id)
    assert error.failure is b6.LineageFailure.CAMPAIGN_MISMATCH and error.cause is store.StoreFailure.CAMPAIGN_MISMATCH


def test_copy_6_a_chain_whose_declarations_disagree_on_their_campaign_is_refused_whatever_the_expected_one(tmp_path):
    mine, theirs, inventory_id, _ = twin_campaigns(tmp_path, specs=(("est",), ("est",)))
    write_chain(mine, inventory_id, [("est",), ("est",)])
    shutil.copyfile(b6.declaration_path(mine, inventory_id, 1), b6.declaration_path(theirs, inventory_id, 1))   # 1 : CURRENT, 2 : other
    for expected in (CURRENT, OTHER_CAMPAIGN.current_campaign_id):
        assert refused_lineage(theirs, inventory_id, campaign_id=expected).failure is b6.LineageFailure.CAMPAIGN_MISMATCH


def test_known_limit_a_deliberate_rewrite_with_recomputed_hashes_is_not_detected(tmp_path):
    """LIMITE (23.31.1) : une intégrité SHA-256 recalculable sans secret ne prouve pas l'authenticité. Réécrire `campaign_id` ET recalculer
    `declaration_content_hash` (puis les liens suivants) n'est pas détectable par E3-B, qui ne revendique aucune liaison cryptographique."""
    mine, theirs, inventory_id, _ = twin_campaigns(tmp_path)
    target = b6.declaration_path(mine, inventory_id, 1)
    target.parent.mkdir(parents=True)
    target.write_bytes(rewrite(b6.declaration_path(theirs, inventory_id, 1).read_bytes(), lambda e: e.update(campaign_id=CURRENT)))
    assert load(mine, inventory_id).state is b6.LineageState.CURRENT_IS_TERMINAL


def test_the_carry_over_draft_and_the_parsed_declarations_expose_the_campaign(tmp_path):
    directory, first, second, older, newer = two_chains(tmp_path)
    lineage = load(directory, second)
    assert {parsed.campaign_id for chain in lineage.chains for parsed in chain.declarations} == {CURRENT}
    third = a0_for(tmp_path, directory, 3)
    assert b6.draft_first_declaration_carry(load(directory, third), third).campaign_id == CURRENT


def test_the_carry_over_draft_carries_the_campaign_of_the_lineage_it_was_read_for(tmp_path):
    mine, theirs, inventory_id, _ = twin_campaigns(tmp_path)
    other = OTHER_CAMPAIGN.current_campaign_id
    newer = a0_for(tmp_path / "t", theirs, 2, context=OTHER_CAMPAIGN)
    draft = b6.draft_first_declaration_carry(load(theirs, newer, campaign_id=other), newer)
    assert draft.campaign_id == other and draft.carried_from.inventory_id == inventory_id
    assert b6.draft_first_declaration_carry(load(mine, inventory_id), "6" * 64).campaign_id == CURRENT     # sans lignée : rien à reprendre


# ── D4 (ADR 0025 23.31.4) : aucun flottant ; après l'`ADMISSION`, seule l'attestation épinglée est pertinente ─────────────────

@pytest.mark.parametrize("payload", [{"a": 1.5}, {"a": [0.0]}, {"a": {"b": -2.0}}, {"a": 1e300}], ids=["fraction", "zero", "nested", "exponent"])
def test_a_float_anywhere_in_an_attestation_is_refused_by_the_loader_and_by_the_reader(tmp_path, payload):
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes(payload))           # forme normative, mais flottant (23.29.4)
    error = refused_lineage(directory, inventory_id)
    assert error.failure is b6.LineageFailure.ATTESTATION_INVALID and error.cause is store.StoreFailure.SCHEMA
    with pytest.raises(store.ExposureStoreError) as refusal:
        b6.read_attestation_slot(directory, inventory_id, 1)
    assert refusal.value.failure is store.StoreFailure.SCHEMA


def test_integers_booleans_and_nulls_remain_accepted_in_an_attestation(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"n": 10 ** 30, "b": True, "z": None, "neg": -3}))
    assert load(directory, inventory_id).state is b6.LineageState.CURRENT_IS_TERMINAL


def admission_pin(directory, inventory_id, seq):
    return b6.AttestationPin(inventory_id, seq, hashlib.sha256(b6.attestation_path(directory, inventory_id, seq).read_bytes()).hexdigest())


def test_the_loader_demands_an_explicit_admission_phase(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    with pytest.raises(TypeError):
        b6.load_declaration_lineage(directory, current_inventory_id=inventory_id, campaign_id=CURRENT, pinned_a0_hashes=frozenset())
    lineage = load(directory, inventory_id, admitted_attestation=None)
    assert lineage.phase is b6.LineagePhase.PRE_ADMISSION and lineage.admitted_attestation is None


@pytest.mark.parametrize("bad", [dict(inventory_id="x"), dict(seq=0), dict(seq=True), dict(file_sha256="A" * 64)])
def test_an_attestation_pin_is_validated(bad):
    values = dict(inventory_id=INVENTORY_ID, seq=1, file_sha256=h("a"))
    with pytest.raises((TypeError, ValueError)):
        b6.AttestationPin(**dict(values, **bad))


def test_after_admission_only_the_pinned_attestation_is_read_and_later_slots_have_no_effect(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"seq": 1}))
    pin = admission_pin(directory, inventory_id, 1)
    b6.attestation_path(directory, inventory_id, 2).write_bytes(b"{ not json")                     # postérieur et illisible
    b6.attestation_path(directory, inventory_id, 3).write_bytes(adr_bytes({"seq": 3}))              # postérieur et valide
    assert refused_lineage(directory, inventory_id).failure in (b6.LineageFailure.ATTESTATION_GAP, b6.LineageFailure.ATTESTATION_INVALID)
    lineage = load(directory, inventory_id, admitted_attestation=pin)
    assert lineage.phase is b6.LineagePhase.POST_ADMISSION and lineage.state is b6.LineageState.CURRENT_IS_TERMINAL
    assert (lineage.admitted_attestation.seq, lineage.admitted_attestation.file_sha256) == (1, pin.file_sha256)
    assert [e.relative_path for e in lineage.ignored if e.kind is b6.IgnoredKind.ATTESTATION_WITHOUT_EFFECT] == [
        f"exposure/{inventory_id}/attestation_0002.json", f"exposure/{inventory_id}/attestation_0003.json"]
    assert b6.highest_attestation_slot(lineage) is None                       # notion propre à la phase avant l'ADMISSION


def test_after_admission_a_replaced_pinned_attestation_is_refused(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"seq": 1}))
    pin = admission_pin(directory, inventory_id, 1)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"seq": 1, "x": "changed"}))
    assert refused_lineage(directory, inventory_id, admitted_attestation=pin).failure is b6.LineageFailure.ADMITTED_ATTESTATION_REPLACED
    b6.attestation_path(directory, inventory_id, 1).write_bytes(b"garbage")                            # remplacée par des octets illisibles
    assert refused_lineage(directory, inventory_id, admitted_attestation=pin).failure is b6.LineageFailure.ADMITTED_ATTESTATION_REPLACED


def test_pins_supplied_for_a_campaign_without_exposure_directory_are_refused_never_silently_satisfied(tmp_path):
    directory = campaign(tmp_path)
    assert load(directory, INVENTORY_ID).state is b6.LineageState.NO_LINEAGE
    assert refused_lineage(directory, INVENTORY_ID, pinned_a0_hashes=frozenset({h("a0")})).failure is b6.LineageFailure.PINNED_A0_MISSING
    error = refused_lineage(directory, INVENTORY_ID, admitted_attestation=b6.AttestationPin(INVENTORY_ID, 1, h("att")))
    assert error.failure is b6.LineageFailure.ADMITTED_ATTESTATION_MISSING


@pytest.mark.parametrize("bad", [(INVENTORY_ID, 1, "0" * 64), {"inventory_id": INVENTORY_ID}, "attestation_0001.json"])
def test_the_admitted_attestation_must_be_an_attestation_pin(tmp_path, bad):
    directory, inventory_id, _ = chain_ready(tmp_path)
    with pytest.raises(TypeError):
        load(directory, inventory_id, admitted_attestation=bad)


def test_after_admission_a_missing_pinned_attestation_is_refused(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"seq": 1}))
    absent_seq = b6.AttestationPin(inventory_id, 2, h("a"))
    absent_chain = b6.AttestationPin("6" * 64, 1, h("a"))
    for pin in (absent_seq, absent_chain):
        assert refused_lineage(directory, inventory_id, admitted_attestation=pin).failure is b6.LineageFailure.ADMITTED_ATTESTATION_MISSING


def test_after_admission_the_pinned_attestation_itself_is_still_read_strictly(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(NON_NORMATIVE_ATTESTATIONS[0][1]({"seq": 1}))
    pin = admission_pin(directory, inventory_id, 1)                                                # épingle des octets non normatifs
    assert refused_lineage(directory, inventory_id, admitted_attestation=pin).failure is b6.LineageFailure.ATTESTATION_INVALID


def test_after_admission_the_structure_is_still_read_strictly(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"seq": 1}))
    pin = admission_pin(directory, inventory_id, 1)
    stray = directory / "exposure" / ("6" * 64)
    stray.mkdir()
    (stray / "attestation_0001.json").write_bytes(adr_bytes({"a": 1}))
    assert refused_lineage(directory, inventory_id, admitted_attestation=pin).failure is b6.LineageFailure.ATTESTATION_WITHOUT_DECLARATION


# ── D1/D6 (ADR 0025 23.31.3) : niveau de preuve d'un épinglage d'A0 ; une référence non résolue n'est ni une preuve ni une absence ────

TRUNCATED_HASH = "9a" * 32                                                   # contient des lettres : la casse compte


def with_truncated_a0(tmp_path):
    directory, inventory_id, entries = chain_ready(tmp_path)
    (directory / "exposure" / f"inventory_{TRUNCATED_HASH}.json").write_bytes(b"{")
    return directory, inventory_id, entries


def test_an_uncited_truncated_a0_is_an_orphan_whose_attestation_pinning_is_reported_as_not_evaluated(tmp_path):
    directory, inventory_id, _ = with_truncated_a0(tmp_path)
    lineage = load(directory, inventory_id)
    assert lineage.pinning.orphan_a0_hashes == (TRUNCATED_HASH,) and lineage.pinning.attestation_pins_evaluated is False
    (entry,) = [e for e in lineage.ignored if e.kind is b6.IgnoredKind.UNREADABLE_INVENTORY]
    assert "non évalué" in entry.detail                                       # jamais présenté comme « non épinglé »


def test_a_cited_truncated_a0_is_an_unresolved_pin_reference_and_is_refused(tmp_path):
    directory, inventory_id, _ = with_truncated_a0(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"anything": TRUNCATED_HASH}))
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.A0_PIN_UNRESOLVED


def test_an_uppercase_citation_of_a_truncated_a0_is_still_an_unresolved_reference(tmp_path):
    directory, inventory_id, _ = with_truncated_a0(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"x": "sha256:" + TRUNCATED_HASH.upper()}))
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.A0_PIN_UNRESOLVED


def test_an_admission_pin_of_a_truncated_a0_is_refused_as_pinned_unreadable(tmp_path):
    directory, inventory_id, _ = with_truncated_a0(tmp_path)
    error = refused_lineage(directory, inventory_id, pinned_a0_hashes=frozenset({TRUNCATED_HASH}))
    assert error.failure is b6.LineageFailure.PINNED_A0_UNREADABLE


def test_irrelevant_hashes_in_an_attestation_conclude_nothing(tmp_path):
    """Hash aléatoire, hash d'un A0 VALIDE, hash de déclaration, hash d'un A0 ABSENT : aucun refus, aucune conclusion d'épinglage."""
    directory, inventory_id, entries = chain_ready(tmp_path)
    (own,) = load(directory, inventory_id).inventories
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({
        "random": h("noise"), "valid_a0": own.inventory_content_hash, "declaration": entries[0].content_hash, "absent_a0": "7" * 64}))
    lineage = load(directory, inventory_id)
    assert lineage.state is b6.LineageState.CURRENT_IS_TERMINAL and lineage.pinning.attestation_pins_evaluated is False
    assert lineage.pinning.admission_pinned_a0_hashes == () and lineage.pinning.orphan_a0_hashes == ()


def test_a_citation_in_an_attestation_without_effect_after_admission_does_not_refuse(tmp_path):
    directory, inventory_id, _ = with_truncated_a0(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"seq": 1}))
    pin = admission_pin(directory, inventory_id, 1)
    b6.attestation_path(directory, inventory_id, 2).write_bytes(adr_bytes({"cites": TRUNCATED_HASH}))
    assert load(directory, inventory_id, admitted_attestation=pin).pinning.orphan_a0_hashes == (TRUNCATED_HASH,)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"cites": TRUNCATED_HASH}))
    assert refused_lineage(directory, inventory_id, admitted_attestation=admission_pin(directory, inventory_id, 1)).failure \
        is b6.LineageFailure.A0_PIN_UNRESOLVED


def test_admission_pins_that_were_checked_are_reported_and_invalid_pins_are_call_errors(tmp_path):
    directory, inventory_id, _ = chain_ready(tmp_path)
    (own,) = load(directory, inventory_id).inventories
    lineage = load(directory, inventory_id, pinned_a0_hashes=frozenset({own.inventory_content_hash}))
    assert lineage.pinning.admission_pinned_a0_hashes == (own.inventory_content_hash,)
    for bad in (frozenset({"short"}), frozenset({own.inventory_content_hash.upper()}), frozenset({7})):
        with pytest.raises((TypeError, ValueError)):
            load(directory, inventory_id, pinned_a0_hashes=bad)


def test_a_historical_a0_recorded_under_b3_v2_still_anchors_its_chain_and_is_reported_as_not_current(tmp_path):
    """D7 (23.31.6) : lecture historique intègre, jamais requalifiée ; elle suffit à l'existence de l'A0 antérieur à la déclaration."""
    directory, inventory_id, _ = chain_ready(tmp_path)
    (path,) = (directory / "exposure").glob("inventory_*.json")
    record = json.loads(path.read_bytes())
    record["rules_versions"]["b3_interpreters"] = "gate_v_exposure_interpreters_v2"
    record["inventory_content_hash"] = store.compute_inventory_content_hash(record)
    path.unlink()
    (directory / "exposure" / f"inventory_{record['inventory_content_hash']}.json").write_bytes(adr_bytes(record))
    lineage = load(directory, inventory_id)
    assert lineage.state is b6.LineageState.CURRENT_IS_TERMINAL
    assert [a0.rules_versions.is_current() for a0 in lineage.inventories] == [False]


# ── D5 (ADR 0025 23.31.5) : plafonds = gardes SYNTHETIC provisoires, jamais un défaut REAL ─────────────────────────────────────

def test_the_lineage_caps_are_synthetic_guards_never_qualified_for_real():
    assert b6.OPERATIONAL_LIMITS_QUALIFIED_FOR_REAL is False is store.OPERATIONAL_LIMITS_QUALIFIED_FOR_REAL
    assert (b6.MAX_DIRECTORY_ENTRIES, b6.MAX_TOTAL_READ_BYTES) == (100_000, 128 * 1024 * 1024)


# ── Revue A de verrouillage (2026-10-18) : mémoire des citations, densité après l'ADMISSION, octets lus ≠ tailles listées ─────────

def test_the_citation_scan_does_not_hold_every_hex_window_in_memory(tmp_path):
    """M1 : une attestation faite d'une longue chaîne hexadécimale ne doit pas produire un ensemble de fenêtres de 64 caractères
    (≈ 137 octets retenus par octet lu) ; seules les références aux A0 illisibles comptent."""
    import tracemalloc
    directory, inventory_id, _ = with_truncated_a0(tmp_path)
    noise = os.urandom(500_000).hex()                                           # 1 Mo d'hexadécimal aléatoire : ≈ 1 million de fenêtres distinctes
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"blob": noise}))
    tracemalloc.start()
    try:
        lineage = load(directory, inventory_id)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert lineage.pinning.orphan_a0_hashes == (TRUNCATED_HASH,)
    assert peak < 48 * 1024 * 1024, peak


def test_a_citation_hidden_in_a_long_hex_string_is_still_found(tmp_path):
    directory, inventory_id, _ = with_truncated_a0(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"blob": "f" * 1001 + TRUNCATED_HASH.upper() + "0" * 999}))
    assert refused_lineage(directory, inventory_id).failure is b6.LineageFailure.A0_PIN_UNRESOLVED


@pytest.mark.parametrize("admitted", [False, True], ids=["pre_admission", "post_admission"])
def test_a_deleted_attestation_slot_is_a_structural_gap_in_both_phases(tmp_path, admitted):
    """m1 : les slots ne sont jamais supprimés (23.29.3) ; la densité des NOMS est une règle de structure, lue dans les deux phases."""
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 2).write_bytes(adr_bytes({"seq": 2}))
    pin = admission_pin(directory, inventory_id, 2) if admitted else None
    assert refused_lineage(directory, inventory_id, admitted_attestation=pin).failure is b6.LineageFailure.ATTESTATION_GAP


def shrink_listed_sizes(monkeypatch, predicate):
    """Simule un fichier qui GRANDIT entre le listage et la lecture : le listage annonce une taille plus petite que le fichier lu."""
    real = b6._list_directory

    def listed(path, budget):
        entries = []
        for name, info in real(path, budget):
            if predicate(name):
                values = list(info)
                values[6] = max(0, info.st_size - 1)                                 # st_size
                info = os.stat_result(values)
            entries.append((name, info))
        return entries

    monkeypatch.setattr(b6, "_list_directory", listed)


@pytest.mark.parametrize("prefix", ["declaration_", "attestation_", "inventory_"])
def test_a_file_larger_at_read_time_than_when_listed_is_refused_as_unstable_never_read_beyond_its_listed_size(tmp_path, monkeypatch, prefix):
    """m3 : le plafond cumulé est calculé sur les tailles listées ; aucun fichier n'est lu au-delà de sa taille listée."""
    directory, inventory_id, _ = chain_ready(tmp_path)
    b6.attestation_path(directory, inventory_id, 1).write_bytes(adr_bytes({"seq": 1}))
    shrink_listed_sizes(monkeypatch, lambda name: name.startswith(prefix))
    error = refused_lineage(directory, inventory_id)
    assert error.cause is store.StoreFailure.UNSTABLE, error
