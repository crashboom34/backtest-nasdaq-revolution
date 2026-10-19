"""AF-V-07 Slice E3-B5 — persistance et relecture stricte du A0 (`<campaign_dir>/exposure/inventory_<inventory_content_hash>.json`).

Fixtures SYNTHÉTIQUES dans `tmp_path` uniquement : aucune donnée réelle, aucun `FINAL_HOLDOUT`, aucun accès réseau.
Contrat : ADR 0025 23.11 étape 1, 23.13, 23.27.3, 23.29.4, 23.29.5, 23.30.1 ; design E3-B (AI_HANDOFF.md §44.1, §45, §52, §53).
Les identités attendues viennent d'E3-A (publié) ; la recette du hash et de la sérialisation vient de l'ADR (23.29.4), recopiée ici.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

import gate_v_exposure_interpreters as b3
import gate_v_exposure_inventory as b4
import gate_v_exposure_store as store
from gate_v_exposure_scan import AuditRoot, ScanHooks
from gate_v_final_holdout_protocol import (
    EXPOSURE_INVENTORY_SEMANTICS_VERSION,
    compute_overlap_projection_hash,
    compute_static_sources_digest,
)
from tests.gate_v_exposure_support import CREATED_AT, CURRENT, LIMITS, STAGE0, W, assemble, h, interpret, make_job


def adr_hash(record: dict) -> str:
    """Recette de l'ADR (23.29.4) : SHA-256 du JSON canonique compact de TOUTES les clés sauf le hash lui-même."""
    body = {key: value for key, value in record.items() if key != "inventory_content_hash"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def adr_bytes(record: dict) -> bytes:
    """Représentation persistée normative (23.29.4)."""
    return (json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


# ── Tranche 1 : traceur — enveloppe, hash du contenu complet, sérialisation normative, séparation des identités ───────────

def test_the_record_carries_the_inventory_identities_and_a_hash_over_its_whole_content(tmp_path):
    assembly = assemble(interpret(tmp_path))
    record = store.build_exposure_inventory_record(assembly, created_at=CREATED_AT)
    assert record["version"] == EXPOSURE_INVENTORY_SEMANTICS_VERSION == "gate_v_exposure_inventory_v1"
    assert record["created_at"] == "2026-10-20T08:00:00.000000Z"                       # instant injecté, normalisé, jamais une horloge
    assert record["inventory_id"] == assembly.inventory_id
    assert record["inventory_content_digest"] == assembly.inventory_content_digest
    assert record["static_sources_digest"] == compute_static_sources_digest(assembly.inventory, STAGE0)
    assert record["overlap_projection_hash"] == compute_overlap_projection_hash(assembly.inventory, STAGE0)
    assert record["inventory_content_hash"] == adr_hash(record) == store.compute_inventory_content_hash(record)
    assert (record["campaign_id"], record["own_record_stage"]) == (CURRENT, "NO_OWN_RECORDS")


def test_the_record_has_exactly_the_documented_keys(tmp_path):
    record = store.build_exposure_inventory_record(assemble(interpret(tmp_path)), created_at=CREATED_AT)
    assert sorted(record) == sorted(store.A0_RECORD_KEYS)
    assert set(record["trial_accounting"]) == {"research_runs", "strategies", "campaigns", "abandoned_reservations",
                                               "failed_ingestion_attempts", "void_commitments"}
    assert set(record["trial_accounting_provenance"]) == set(record["trial_accounting"]) | {"reasons"}


def test_the_persisted_representation_is_the_normative_one(tmp_path):
    record = store.build_exposure_inventory_record(assemble(interpret(tmp_path)), created_at=CREATED_AT)
    raw = store.serialize_exposure_inventory_record(record)
    assert raw == adr_bytes(record) and raw.endswith(b"\n") and b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw) == record


def test_provenance_is_covered_by_the_content_hash_but_by_no_scientific_identity(tmp_path):
    interpretation = interpret(tmp_path)
    verified = assemble(interpretation, accounting=b4.AccountingViews(failed_ingestion=b4.TrialItemsView(items=()),
                                                                       void_commitments=b4.TrialItemsView(items=())))
    placeholder = assemble(interpretation)
    first = store.build_exposure_inventory_record(verified, created_at=CREATED_AT)
    second = store.build_exposure_inventory_record(placeholder, created_at=CREATED_AT)
    for name in ("inventory_id", "inventory_content_digest", "static_sources_digest", "overlap_projection_hash", "trial_accounting"):
        assert first[name] == second[name], name
    assert first["trial_accounting_provenance"] != second["trial_accounting_provenance"]
    assert first["inventory_content_hash"] != second["inventory_content_hash"]


def test_informative_registers_change_the_content_hash_and_never_an_identity(tmp_path):
    interpretation = interpret(tmp_path)
    notes = (b3.NonOosValidationRun("validation.run:res/x/validation_run.json", "walk_forward", h("w")),)
    evidence = (b3.ExposureEvidence("job.config:res/other/config_used.json", b3.EvidenceStatus.ABSENCE_NOT_ESTABLISHED),)
    plain = store.build_exposure_inventory_record(assemble(interpretation), created_at=CREATED_AT)
    for changes in (dict(non_oos_validations=notes), dict(exposure_evidence=evidence)):
        other = store.build_exposure_inventory_record(assemble(dataclasses.replace(interpretation, **changes)), created_at=CREATED_AT)
        assert other["inventory_id"] == plain["inventory_id"] and other["inventory_content_digest"] == plain["inventory_content_digest"]
        assert other["inventory_content_hash"] != plain["inventory_content_hash"]


def test_created_at_is_part_of_the_content_hash_and_of_nothing_else(tmp_path):
    assembly = assemble(interpret(tmp_path))
    first = store.build_exposure_inventory_record(assembly, created_at=CREATED_AT)
    later = store.build_exposure_inventory_record(assembly, created_at="2026-10-20T08:00:01+00:00")
    assert {k for k in first if first[k] != later[k]} == {"created_at", "inventory_content_hash"}


@pytest.mark.parametrize("created_at, error", [("2026-10-20T08:00:00", ValueError), ("not a date", ValueError), (None, TypeError),
                                               (12, TypeError)])
def test_created_at_must_be_an_injected_aware_instant(tmp_path, created_at, error):
    with pytest.raises(error):
        store.build_exposure_inventory_record(assemble(interpret(tmp_path)), created_at=created_at)


def test_an_assembly_built_from_hooked_scans_is_never_persisted(tmp_path):
    """Un scan avec `ScanHooks` (outil de test) n'a aucune autorité de production : il ne devient jamais un A0 (E3-J le refuse aussi)."""
    results = tmp_path / "results"
    make_job(results, "job_1", "2026-02-01T00:00:00+00:00", "2026-02-10T00:00:00+00:00")
    hooked = b3.interpret_audit_roots((b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("res", str(results))),), LIMITS,
                                      holdout_window_start_utc=W[0], holdout_window_end_utc=W[1],
                                      hooks=ScanHooks(after_first_pass=lambda attempt: None))
    assembly = assemble(hooked)
    assert assembly.hooks_used is True
    with pytest.raises(ValueError):
        store.build_exposure_inventory_record(assembly, created_at=CREATED_AT)


def test_scan_pins_keep_the_rules_limits_and_resolved_roots_but_no_volatile_filesystem_field(tmp_path):
    record = store.build_exposure_inventory_record(assemble(interpret(tmp_path)), created_at=CREATED_AT)
    (pin,) = record["scan_pins"]
    assert set(pin) == {"layout", "rules_digest", "limits", "hooks_used", "roots"} and pin["hooks_used"] is False
    assert pin["layout"] == "RESULTS" and len(pin["rules_digest"]) == 64
    assert set(pin["limits"]) == {"max_roots", "max_entries", "max_depth", "max_json_bytes", "max_total_read_bytes",
                                  "max_json_depth", "max_name_length", "max_path_length", "max_attempts"}
    (root,) = pin["roots"]
    assert set(root) == {"label", "resolved_path", "may_be_empty"} and root["label"] == "res"
    assert "st_ino" not in json.dumps(record) and "mtime" not in json.dumps(record)


# ── Tranche 2 : publication exclusive durable, relecture stricte, corruptions ──────────────────────────────────────────

import os  # noqa: E402
from pathlib import Path  # noqa: E402

import atomic_json_store  # noqa: E402
from tests.gate_v_exposure_support import registry  # noqa: E402


def campaign(tmp_path) -> Path:
    path = tmp_path / "campaign_dir"
    path.mkdir(exist_ok=True)
    return path


def publish(tmp_path, assembly=None, created_at=CREATED_AT) -> Path:
    assembly = assemble(interpret(tmp_path)) if assembly is None else assembly
    return store.publish_exposure_inventory(campaign(tmp_path), assembly, created_at=created_at)


def test_publish_writes_the_normative_bytes_under_the_hash_named_path_and_creates_exposure_without_parents(tmp_path):
    assembly = assemble(interpret(tmp_path))
    directory = campaign(tmp_path)
    path = store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    record = store.build_exposure_inventory_record(assembly, created_at=CREATED_AT)
    assert path == directory / "exposure" / f"inventory_{record['inventory_content_hash']}.json"
    assert path == store.exposure_inventory_path(directory, record["inventory_content_hash"])
    assert path.read_bytes() == adr_bytes(record)
    assert sorted(entry.name for entry in (directory / "exposure").iterdir()) == [path.name]


def test_publish_uses_the_exclusive_durable_primitive_with_a_recursively_sorted_dict(tmp_path, monkeypatch):
    calls = []
    real = atomic_json_store.save_exclusive

    def spy(path, data, kind, *, durable=False):
        calls.append((path, data, durable))
        return real(path, data, kind, durable=durable)

    monkeypatch.setattr(store, "save_exclusive", spy)
    publish(tmp_path)
    ((path, data, durable),) = calls
    assert durable is True and type(data) is dict

    def is_sorted(value):
        if isinstance(value, dict):
            return list(value) == sorted(value) and all(is_sorted(item) for item in value.values())
        return all(is_sorted(item) for item in value) if isinstance(value, list) else True

    assert is_sorted(data)
    assert (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8") == adr_bytes(data)   # octets de save_exclusive = normatif


def test_several_a0_for_the_same_inventory_coexist_and_never_overwrite_each_other(tmp_path):
    assembly = assemble(interpret(tmp_path))
    directory = campaign(tmp_path)
    first = store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    before = first.read_bytes()
    second = store.publish_exposure_inventory(directory, assembly, created_at="2026-10-20T09:00:00+00:00")
    assert first != second and first.read_bytes() == before and second.exists()
    assert len(list((directory / "exposure").iterdir())) == 2


def test_publishing_the_same_content_twice_is_idempotent_after_a_strict_reread(tmp_path):
    assembly = assemble(interpret(tmp_path))
    directory = campaign(tmp_path)
    first = store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    stamp = first.stat().st_mtime_ns
    again = store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    assert again == first and first.stat().st_mtime_ns == stamp and len(list((directory / "exposure").iterdir())) == 1


def test_a_truncated_file_at_the_expected_name_is_never_overwritten_nor_deleted_and_demands_a_new_created_at(tmp_path):
    assembly = assemble(interpret(tmp_path))
    directory = campaign(tmp_path)
    good = store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    good.write_bytes(good.read_bytes()[:50])                                  # crash après création : fichier tronqué au nom attendu
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    assert refusal.value.failure is store.StoreFailure.NAME_CONSUMED and good.exists() and len(good.read_bytes()) == 50
    retry = store.publish_exposure_inventory(directory, assembly, created_at="2026-10-20T08:00:01+00:00")
    assert retry != good and store.load_exposure_inventory(retry).created_at == "2026-10-20T08:00:01.000000Z"


def test_an_incomplete_durable_write_is_reported_and_leaves_the_consumed_path_in_place(tmp_path, monkeypatch):
    directory = campaign(tmp_path)

    def crashing(path, data, kind, *, durable=False):
        Path(path).write_bytes(b"{")                                          # le chemin est créé puis l'écriture échoue
        raise atomic_json_store.ExclusiveCreationIncompleteError("disk full", path)

    monkeypatch.setattr(store, "save_exclusive", crashing)
    with pytest.raises(store.ExposureStoreError) as refusal:
        publish(tmp_path)
    assert refusal.value.failure is store.StoreFailure.INCOMPLETE_WRITE
    (leftover,) = (directory / "exposure").iterdir()
    assert leftover.read_bytes() == b"{"                                      # jamais supprimé


def test_publish_never_creates_missing_parents(tmp_path):
    assembly = assemble(interpret(tmp_path))
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.publish_exposure_inventory(tmp_path / "no" / "such" / "campaign", assembly, created_at=CREATED_AT)
    assert refusal.value.failure is store.StoreFailure.BAD_DIRECTORY and not (tmp_path / "no").exists()


@pytest.mark.parametrize("kind", ["campaign_is_a_file", "exposure_is_a_file"])
def test_publish_refuses_a_campaign_or_exposure_path_that_is_not_a_directory(tmp_path, kind):
    assembly = assemble(interpret(tmp_path))
    directory = tmp_path / "campaign_dir"
    if kind == "campaign_is_a_file":
        directory.write_bytes(b"x")
    else:
        directory.mkdir()
        (directory / "exposure").write_bytes(b"x")
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    assert refusal.value.failure is store.StoreFailure.BAD_DIRECTORY


def symlink_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("liens symboliques non disponibles (privilège Windows requis)")


def test_publish_refuses_a_symlinked_exposure_directory(tmp_path):
    assembly = assemble(interpret(tmp_path))
    directory = campaign(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    symlink_or_skip(directory / "exposure", elsewhere, directory=True)
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    assert refusal.value.failure in (store.StoreFailure.BAD_DIRECTORY, store.StoreFailure.LINK_OR_REPARSE_POINT)
    assert list(elsewhere.iterdir()) == []


def test_the_roundtrip_restores_every_object_and_recomputes_the_identities(tmp_path):
    accounting = b4.AccountingViews(closing=b4.ClosingView(terminal_campaign_ids=()), failed_ingestion=b4.TrialItemsView(items=()))
    assembly = assemble(interpret(tmp_path), accounting=accounting)
    path = publish(tmp_path, assembly)
    loaded = store.load_exposure_inventory(path)
    assert loaded.inventory == assembly.inventory and loaded.own_context == assembly.own_context
    assert (loaded.inventory_id, loaded.inventory_content_digest) == (assembly.inventory_id, assembly.inventory_content_digest)
    assert loaded.accounting_provenance == assembly.accounting_provenance
    assert loaded.incomplete_reasons == assembly.incomplete_reasons
    assert (loaded.registry_id, loaded.registry_chain_head) == (assembly.registry_id, assembly.registry_chain_head)
    assert loaded.derived_root_labels == assembly.derived_root_labels
    assert loaded.plans == assembly.interpretation.plans and loaded.exposure_evidence == assembly.interpretation.exposure_evidence
    assert loaded.non_oos_validations == assembly.interpretation.non_oos_validations
    assert loaded.created_at == "2026-10-20T08:00:00.000000Z" and loaded.path == path
    assert loaded.inventory_content_hash == path.name[len("inventory_"):-len(".json")]
    assert loaded.file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert store.read_exposure_inventory(path.parent.parent, loaded.inventory_content_hash) == loaded
    (pin,) = loaded.scan_pins
    assert pin.layout is b3.RootLayout.RESULTS and pin.hooks_used is False and pin.limits == LIMITS
    assert [(root.label, root.may_be_empty) for root in pin.roots] == [("res", False)]


def test_the_roundtrip_of_an_incomplete_inventory_keeps_its_reasons_and_unresolved_findings(tmp_path):
    interpretation = interpret(tmp_path, job=("2025-06-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00"))      # absence non établie
    assembly = assemble(interpretation, reg=registry(unreadable=("seq-0003",)))
    loaded = store.load_exposure_inventory(publish(tmp_path, assembly))
    assert loaded.inventory.complete is False and loaded.incomplete_reasons == assembly.incomplete_reasons
    assert loaded.inventory.findings == assembly.inventory.findings


def test_non_ascii_text_is_persisted_unescaped_and_roundtrips(tmp_path):
    assembly = assemble(interpret(tmp_path), reg=registry(registry_id="régistre"))
    path = publish(tmp_path, assembly)
    assert "régistre".encode("utf-8") in path.read_bytes()
    assert store.load_exposure_inventory(path).registry_id == "régistre"


def test_an_absent_or_non_regular_target_is_distinguished_from_a_corrupt_file(tmp_path):
    directory = campaign(tmp_path)
    (directory / "exposure").mkdir()
    name = "inventory_" + "a" * 64 + ".json"
    with pytest.raises(store.ExposureStoreError) as absent:
        store.load_exposure_inventory(directory / "exposure" / name)
    assert absent.value.failure is store.StoreFailure.ABSENT
    (directory / "exposure" / name).mkdir()
    with pytest.raises(store.ExposureStoreError) as not_regular:
        store.load_exposure_inventory(directory / "exposure" / name)
    assert not_regular.value.failure is store.StoreFailure.NOT_REGULAR_FILE


def test_a_symlinked_file_is_refused_and_never_followed(tmp_path):
    path = publish(tmp_path)
    link = path.parent / ("inventory_" + "b" * 64 + ".json")
    symlink_or_skip(link, path, directory=False)
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.load_exposure_inventory(link)
    assert refusal.value.failure is store.StoreFailure.LINK_OR_REPARSE_POINT


def test_a_file_above_the_size_cap_is_refused_before_parsing(tmp_path):
    path = publish(tmp_path)
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.load_exposure_inventory(path, max_bytes=100)
    assert refusal.value.failure is store.StoreFailure.TOO_LARGE


def forge(tmp_path, mutate=None, *, rehash=True, rename=True, raw_transform=None, assembly=None) -> Path:
    """Fabrique un A0 altéré : `mutate(record)`, recalcul optionnel du hash (pour atteindre les contrôles suivants), nom = hash."""
    source = publish(tmp_path, assembly)
    record = json.loads(source.read_bytes())
    if mutate is not None:
        mutate(record)
    if rehash:
        record["inventory_content_hash"] = store.compute_inventory_content_hash(record)
    raw = adr_bytes(record)
    if raw_transform is not None:
        raw = raw_transform(raw)
    target = source.parent / (f"inventory_{record['inventory_content_hash']}.json" if rename else source.name)
    if target != source:
        source.rename(target)
    target.write_bytes(raw)
    return target


def refused(path: Path) -> store.ExposureStoreError:
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.load_exposure_inventory(path)
    return refusal.value


@pytest.mark.parametrize("name, transform, failure", [
    ("bom", lambda raw: b"\xef\xbb\xbf" + raw, store.StoreFailure.NOT_JSON),
    ("invalid_utf8", lambda raw: raw.replace(b"campaign_current", b"campaign_\xff\xfe"), store.StoreFailure.NOT_JSON),
    ("truncated", lambda raw: raw[:200], store.StoreFailure.NOT_JSON),
    ("empty", lambda raw: b"", store.StoreFailure.NOT_JSON),
    ("trailing_garbage", lambda raw: raw + b"{}", store.StoreFailure.NOT_JSON),
    ("duplicate_key", lambda raw: raw.replace(b'"complete": true', b'"complete": true,\n  "complete": false'), store.StoreFailure.NOT_JSON),
    ("nan_constant", lambda raw: raw.replace(b'"campaigns": 0', b'"campaigns": NaN'), store.StoreFailure.NOT_JSON),
    ("infinity_constant", lambda raw: raw.replace(b'"campaigns": 0', b'"campaigns": Infinity'), store.StoreFailure.NOT_JSON),
    ("top_level_list", lambda raw: b"[]\n", store.StoreFailure.SCHEMA),
])
def test_unreadable_json_is_refused_with_a_typed_cause(tmp_path, name, transform, failure):
    path = forge(tmp_path, rehash=False, rename=False, raw_transform=transform)
    assert refused(path).failure is failure


def reversed_keys(raw: bytes) -> bytes:
    return json.dumps(dict(reversed(list(json.loads(raw).items()))), ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


@pytest.mark.parametrize("name, transform", [
    ("compact", lambda raw: json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"),
    ("crlf", lambda raw: raw.replace(b"\n", b"\r\n")),
    ("extra_trailing_newline", lambda raw: raw + b"\n"),
    ("no_trailing_newline", lambda raw: raw[:-1]),
    ("four_space_indent", lambda raw: json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=False, indent=4).encode() + b"\n"),
    ("unsorted_keys", reversed_keys),
])
def test_content_that_is_not_the_byte_fixed_point_of_the_normative_serialization_is_refused(tmp_path, name, transform):
    path = forge(tmp_path, rehash=False, rename=False, raw_transform=transform)
    assert refused(path).failure is store.StoreFailure.NOT_FIXED_POINT


def test_escaped_non_ascii_is_not_the_normative_form(tmp_path):
    assembly = assemble(interpret(tmp_path), reg=registry(registry_id="régistre"))
    path = forge(tmp_path, rehash=False, rename=False, assembly=assembly,
                 raw_transform=lambda raw: json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=True, indent=2).encode() + b"\n")
    assert b"\\u00e9" in path.read_bytes() and refused(path).failure is store.StoreFailure.NOT_FIXED_POINT


def test_a_modified_content_without_a_recomputed_hash_is_refused(tmp_path):
    path = forge(tmp_path, lambda record: record.update(created_at="2026-10-21T00:00:00.000000Z"), rehash=False, rename=False)
    assert refused(path).failure is store.StoreFailure.HASH_MISMATCH


def test_a_file_whose_name_is_not_its_hash_is_refused(tmp_path):
    path = forge(tmp_path)
    renamed = path.parent / ("inventory_" + "c" * 64 + ".json")
    path.rename(renamed)
    assert refused(renamed).failure is store.StoreFailure.NAME_MISMATCH
    odd = renamed.parent / "inventory_x.json"
    renamed.rename(odd)
    assert refused(odd).failure is store.StoreFailure.NAME_MISMATCH


def test_the_stored_hash_key_must_equal_the_recomputed_hash(tmp_path):
    path = forge(tmp_path, lambda record: record.update(inventory_content_hash="d" * 64), rehash=False, rename=False)
    assert refused(path).failure is store.StoreFailure.HASH_MISMATCH


def set_in(record, dotted, value):
    node = record
    *parents, last = dotted.split(".")
    for part in parents:
        node = node[int(part)] if part.isdigit() else node[part]
    if last.isdigit():
        node[int(last)] = value
    else:
        node[last] = value


SCHEMA_CASES = [
    ("unknown_extra_key", lambda r: r.update(surprise=1)),
    ("missing_key", lambda r: r.pop("registry")),
    ("version_wrong_type", lambda r: r.update(version=1)),
    ("complete_not_bool", lambda r: r.update(complete=1)),
    ("counter_is_bool", lambda r: set_in(r, "trial_accounting.campaigns", True)),
    ("counter_is_float", lambda r: set_in(r, "trial_accounting.campaigns", 0.0)),
    ("counter_negative", lambda r: set_in(r, "trial_accounting.campaigns", -1)),
    ("counter_missing", lambda r: r["trial_accounting"].pop("strategies")),
    ("counter_extra", lambda r: r["trial_accounting"].update(extra=0)),
    ("provenance_unknown_state", lambda r: set_in(r, "trial_accounting_provenance.campaigns", "EXACT")),
    ("provenance_missing_reasons", lambda r: r["trial_accounting_provenance"].pop("reasons")),
    ("findings_not_list", lambda r: r.update(findings={})),
    ("finding_extra_key", lambda r: r["findings"][0].update(extra=1)),
    ("finding_unknown_kind", lambda r: set_in(r, "findings.0.source_kind", "NOT_A_KIND")),
    ("finding_bad_hash", lambda r: set_in(r, "findings.0.content_hash", "xyz")),
    ("scanned_roots_unsorted", lambda r: r.update(scanned_roots=["z", "a"])),
    ("scan_pins_empty_limits", lambda r: set_in(r, "scan_pins.0.limits", {})),
    ("scan_pin_unknown_layout", lambda r: set_in(r, "scan_pins.0.layout", "SOMEWHERE")),
    ("scan_pin_hooks_used", lambda r: set_in(r, "scan_pins.0.hooks_used", True)),
    ("scan_pin_zero_limit", lambda r: set_in(r, "scan_pins.0.limits.max_entries", 0)),
    ("registry_head_bad", lambda r: set_in(r, "registry.chain_head", "short")),
    ("stage_unknown", lambda r: r.update(own_record_stage="NEVER")),
    ("campaign_empty", lambda r: r.update(campaign_id="")),
    ("window_not_normalized", lambda r: r.update(window_start_utc="2026-01-01T00:00:00+00:00")),
    ("created_at_not_normalized", lambda r: r.update(created_at="2026-10-20T08:00:00+00:00")),
    ("created_at_naive", lambda r: r.update(created_at="2026-10-20T08:00:00")),
    ("complete_with_reasons", lambda r: r.update(incomplete_reasons=["SOMETHING"])),
    ("incomplete_without_reasons", lambda r: r.update(complete=False)),
    ("derived_label_unknown", lambda r: r.update(derived_root_labels=["nope"])),
    ("plans_not_list", lambda r: r.update(plans="x")),
    ("evidence_unknown_status", lambda r: r.update(exposure_evidence=[{"source_id": "x", "status": "MAYBE", "manifest_source_id": None,
                                                                      "manifest_content_hash": None}])),
    ("evidence_manifest_without_coverage_status", lambda r: r.update(exposure_evidence=[{
        "source_id": "x", "status": "ABSENCE_NOT_ESTABLISHED", "manifest_source_id": "m", "manifest_content_hash": h("m")}])),
    ("non_oos_extra_key", lambda r: r.update(non_oos_validations=[{"source_id": "x", "validation_type": "t", "content_hash": h("x"),
                                                                    "extra": 1}])),
]


@pytest.mark.parametrize("name, mutate", SCHEMA_CASES, ids=[case[0] for case in SCHEMA_CASES])
def test_a_schema_violation_is_refused_even_when_the_hash_is_recomputed(tmp_path, name, mutate):
    assert refused(forge(tmp_path, mutate)).failure is store.StoreFailure.SCHEMA


def test_an_unknown_version_is_refused_as_such(tmp_path):
    assert refused(forge(tmp_path, lambda r: r.update(version="gate_v_exposure_inventory_v2"))).failure is store.StoreFailure.UNKNOWN_VERSION
    assert refused(forge(tmp_path, lambda r: set_in(r, "rules_versions.b3_interpreters", "other"))).failure \
        is store.StoreFailure.UNKNOWN_VERSION


IDENTITY_CASES = [
    ("inventory_id", lambda r: r.update(inventory_id="e" * 64)),
    ("content_digest", lambda r: r.update(inventory_content_digest="e" * 64)),
    ("static_digest", lambda r: r.update(static_sources_digest="e" * 64)),
    ("projection", lambda r: r.update(overlap_projection_hash="e" * 64)),
    ("counter_changed_without_digest", lambda r: set_in(r, "trial_accounting.campaigns", 5)),
    ("finding_window_changed", lambda r: set_in(r, "findings.0.window_start_utc", "2026-02-02T00:00:00.000000Z")),
]


@pytest.mark.parametrize("name, mutate", IDENTITY_CASES, ids=[case[0] for case in IDENTITY_CASES])
def test_identities_are_recomputed_with_e3a_and_a_mismatch_is_refused_even_with_a_valid_hash(tmp_path, name, mutate):
    assert refused(forge(tmp_path, mutate)).failure is store.StoreFailure.IDENTITY_MISMATCH


def test_a_finding_whose_overlap_contradicts_its_window_is_refused(tmp_path):
    """E3-A refuse un verdict de recouvrement incompatible avec les fenêtres : la relecture ne l'accepte pas non plus."""
    flipped = forge(tmp_path, lambda r: set_in(r, "findings.0.overlap", "NO_OVERLAP"))
    assert refused(flipped).failure is store.StoreFailure.SCHEMA


def test_the_provenance_is_covered_by_the_content_hash_only(tmp_path):
    """Éditer la provenance sans recalculer le hash est refusé ; la recalculer ne touche AUCUNE identité scientifique."""
    edit = lambda r: set_in(r, "trial_accounting_provenance.campaigns", "PARTIAL")      # noqa: E731
    assert refused(forge(tmp_path / "stale", edit, rehash=False, rename=False)).failure is store.StoreFailure.HASH_MISMATCH
    honest = store.load_exposure_inventory(publish(tmp_path / "honest"))
    rehashed = store.load_exposure_inventory(forge(tmp_path / "rehashed", edit))
    assert rehashed.accounting_provenance.campaigns is b4.CounterProvenance.PARTIAL
    assert (rehashed.inventory_id, rehashed.inventory_content_digest) == (honest.inventory_id, honest.inventory_content_digest)
    assert rehashed.inventory_content_hash != honest.inventory_content_hash


class _Wrapped:
    """`os.stat_result` enrobé : un attribut de fichier surchargé, tout le reste délégué."""

    def __init__(self, info, **overrides):
        self._info, self._overrides = info, overrides

    def __getattr__(self, name):
        return self._overrides[name] if name in self._overrides else getattr(self._info, name)


def test_a_reparse_point_flag_on_the_target_file_is_refused_like_a_link(tmp_path, monkeypatch):
    """Simule un point d'analyse sans privilège : l'attribut `FILE_ATTRIBUTE_REPARSE_POINT` d'un FICHIER est refusé, jamais suivi."""
    path = publish(tmp_path)
    real = os.lstat
    monkeypatch.setattr(os, "lstat", lambda p, *a, **k: _Wrapped(real(p, *a, **k), st_file_attributes=0x400)
                        if os.fspath(p).endswith(path.name) else real(p, *a, **k))
    assert refused(path).failure is store.StoreFailure.LINK_OR_REPARSE_POINT


def test_a_file_that_changes_during_its_read_is_refused_as_unstable(tmp_path, monkeypatch):
    path = publish(tmp_path)
    real, calls = os.lstat, []

    def shifting(p, *a, **k):
        info = real(p, *a, **k)
        if os.fspath(p).endswith(path.name):
            calls.append(1)
            if len(calls) >= 2:                                               # observation APRÈS la lecture : mtime changé
                return _Wrapped(info, st_mtime_ns=info.st_mtime_ns + 1)
        return info

    monkeypatch.setattr(os, "lstat", shifting)
    assert refused(path).failure is store.StoreFailure.UNSTABLE


def test_a_file_whose_size_disagrees_with_the_bytes_read_is_refused_as_unstable(tmp_path, monkeypatch):
    path = publish(tmp_path)
    real = os.lstat
    monkeypatch.setattr(os, "lstat", lambda p, *a, **k: _Wrapped(real(p, *a, **k), st_size=real(p, *a, **k).st_size + 1)
                        if os.fspath(p).endswith(path.name) else real(p, *a, **k))
    assert refused(path).failure is store.StoreFailure.UNSTABLE


def junction_or_skip(link: Path, target: Path) -> None:
    import subprocess
    if os.name != "nt":
        pytest.skip("jonction Windows uniquement")
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    if done.returncode != 0:
        pytest.skip("jonction non disponible")


def test_publish_refuses_an_exposure_directory_that_is_a_junction_and_writes_nothing_through_it(tmp_path):
    assembly = assemble(interpret(tmp_path))
    directory = campaign(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    junction_or_skip(directory / "exposure", elsewhere)
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    assert refusal.value.failure is store.StoreFailure.LINK_OR_REPARSE_POINT and list(elsewhere.iterdir()) == []


def test_load_refuses_an_a0_reached_through_a_junctioned_exposure_directory(tmp_path):
    real = publish(tmp_path / "real")
    (tmp_path / "other").mkdir()
    directory = campaign(tmp_path / "other")
    junction_or_skip(directory / "exposure", real.parent)
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.load_exposure_inventory(directory / "exposure" / real.name)
    assert refusal.value.failure is store.StoreFailure.LINK_OR_REPARSE_POINT


def test_the_campaign_id_and_stage_are_hash_covered_context_not_part_of_the_scientific_identity(tmp_path):
    changed = store.load_exposure_inventory(forge(tmp_path / "other", lambda r: r.update(campaign_id="another_campaign")))
    honest = store.load_exposure_inventory(publish(tmp_path / "honest"))
    assert changed.own_context.current_campaign_id == "another_campaign" and changed.inventory_id == honest.inventory_id
    assert changed.inventory_content_hash != honest.inventory_content_hash


# ── Tests ajoutés par la campagne de mutation (mutants survivants) ───────────────────────────────────────────────────

def test_a_read_that_returns_fewer_bytes_than_the_observed_size_is_refused_as_unstable(tmp_path, monkeypatch):
    path = publish(tmp_path)
    monkeypatch.setattr(os, "read", lambda descriptor, count: b"")
    assert refused(path).failure is store.StoreFailure.UNSTABLE


def test_publish_refuses_a_campaign_directory_that_is_a_junction_and_writes_nothing_through_it(tmp_path):
    assembly = assemble(interpret(tmp_path))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / "campaign_link"
    junction_or_skip(link, elsewhere)
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.publish_exposure_inventory(link, assembly, created_at=CREATED_AT)
    assert refusal.value.failure is store.StoreFailure.LINK_OR_REPARSE_POINT and list(elsewhere.iterdir()) == []


def test_publish_checks_that_the_bytes_handed_to_the_exclusive_primitive_are_the_normative_ones(tmp_path, monkeypatch):
    assembly = assemble(interpret(tmp_path))
    real = store.serialize_exposure_inventory_record
    monkeypatch.setattr(store, "serialize_exposure_inventory_record", lambda record: real(record) + b" ")
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.publish_exposure_inventory(campaign(tmp_path), assembly, created_at=CREATED_AT)
    assert refusal.value.failure is store.StoreFailure.NOT_FIXED_POINT
    assert not (tmp_path / "campaign" / "exposure").exists() or list((tmp_path / "campaign" / "exposure").iterdir()) == []


def test_a_scanned_root_that_no_pin_declares_is_refused_even_when_the_hash_is_recomputed(tmp_path):
    assert refused(forge(tmp_path, lambda r: r.update(scanned_roots=["zzz"]))).failure is store.StoreFailure.SCHEMA


def _duplicate_first(record, dotted):
    node = record
    for part in dotted.split("."):
        node = node[int(part)] if part.isdigit() else node[part]
    node.append(json.loads(json.dumps(node[0])))


@pytest.mark.parametrize("name, mutate", [
    ("duplicate_pin_root", lambda r: _duplicate_first(r, "scan_pins.0.roots")),
    ("duplicate_pin_layout", lambda r: _duplicate_first(r, "scan_pins")),
    ("duplicate_evidence_entry", lambda r: _duplicate_first(r, "exposure_evidence")),
    ("duplicate_non_oos_entry", lambda r: r.update(non_oos_validations=[
        {"source_id": "x", "validation_type": "t", "content_hash": h("x")}, {"source_id": "x", "validation_type": "t", "content_hash": h("x")}])),
    ("unsorted_non_oos_entries", lambda r: r.update(non_oos_validations=[
        {"source_id": "b", "validation_type": "t", "content_hash": h("b")}, {"source_id": "a", "validation_type": "t", "content_hash": h("a")}])),
    ("duplicate_derived_label", lambda r: r.update(derived_root_labels=["res", "res"])),
    ("duplicate_incomplete_reason", lambda r: r.update(complete=False, incomplete_reasons=["R", "R"])),
    ("unsorted_incomplete_reasons", lambda r: r.update(complete=False, incomplete_reasons=["B", "A"])),
    ("empty_incomplete_reason", lambda r: r.update(complete=False, incomplete_reasons=[""])),
    ("provenance_reason_not_text", lambda r: set_in(r, "trial_accounting_provenance.reasons", [1])),
    ("provenance_reason_empty", lambda r: set_in(r, "trial_accounting_provenance.reasons", [""])),
], ids=lambda case: case if isinstance(case, str) else "")
def test_registers_must_be_strictly_sorted_unique_and_non_empty(tmp_path, name, mutate):
    assert refused(forge(tmp_path, mutate)).failure is store.StoreFailure.SCHEMA


# ── Corrections issues de la revue A ─────────────────────────────────────────────────────────────────────────────────

def test_read_refuses_an_a0_reached_through_a_junctioned_campaign_directory(tmp_path):
    real = publish(tmp_path / "real")
    link = tmp_path / "campaign_link"
    junction_or_skip(link, real.parent.parent)
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.read_exposure_inventory(link, real.name[len("inventory_"):-len(".json")])
    assert refusal.value.failure is store.StoreFailure.LINK_OR_REPARSE_POINT


def test_publish_refuses_a_record_that_the_strict_reader_would_refuse_and_writes_nothing(tmp_path):
    base = assemble(interpret(tmp_path, job=("2025-06-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00")), reg=registry(unreadable=("seq-0003",)))
    assembly = dataclasses.replace(base, incomplete_reasons=base.incomplete_reasons * 2)                   # doublon : jamais relu
    directory = campaign(tmp_path)
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    assert refusal.value.failure is store.StoreFailure.SCHEMA and not (directory / "exposure").exists()


def test_a_permission_error_while_observing_exposure_is_a_typed_refusal(tmp_path, monkeypatch):
    assembly = assemble(interpret(tmp_path))
    directory = campaign(tmp_path)
    real = os.lstat

    def denied(p, *a, **k):
        if os.fspath(p).endswith("exposure"):
            raise PermissionError("denied")
        return real(p, *a, **k)

    monkeypatch.setattr(os, "lstat", denied)
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    assert refusal.value.failure is store.StoreFailure.BAD_DIRECTORY


# ── Cohérence des informations d'audit avec les findings auxquels elles se rattachent (dans les limites des preuves) ─────

UNRESOLVED_JOB = ("2025-06-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00")               # hors W : absence NON établie, finding UNRESOLVED
JOB_FINDING_ID = "job.config:res/job_1/config_used.json"
WF_FINDING_ID = "validation.run:res/validations/val-wf-1/validation_run.json"


def walk_forward_interpretation(tmp_path):
    from tests.gate_v_exposure_support import write_json, make_job
    results = tmp_path / "results"
    make_job(results, "job_1", *UNRESOLVED_JOB)
    write_json(results / "validations" / "val-wf-1" / "validation_run.json", {
        "validation_run_id": "val-wf-1", "research_run_id": "rr-1", "split_plan_id": "plan-alpha", "dataset_snapshot_id": "snap-1",
        "validation_type": "walk_forward", "strategy_name": "s", "strategy_params": {}, "evidence": {"n_windows": 3}, "status": "completed",
        "completed_at": "2026-05-01T00:00:00+00:00"})
    (results / "validations" / "val-wf-1" / "research_run.json").write_bytes(b"{}")
    root = b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("res", str(results)))
    return b3.interpret_audit_roots((root,), LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])


def test_a_coherent_audit_register_roundtrips_for_established_unresolved_and_non_oos_sources(tmp_path):
    for name, assembly in (("established", assemble(interpret(tmp_path / "e"))),
                           ("unresolved", assemble(interpret(tmp_path / "u", job=UNRESOLVED_JOB))),
                           ("non_oos", assemble(walk_forward_interpretation(tmp_path / "n")))):
        (tmp_path / name).mkdir()
        loaded = store.load_exposure_inventory(publish(tmp_path / name, assembly))
        assert loaded.exposure_evidence == assembly.interpretation.exposure_evidence, name
    assert loaded.non_oos_validations and loaded.non_oos_validations[0].source_id == WF_FINDING_ID


def evidence_status(status):
    return lambda r: set_in(r, "exposure_evidence.0.status", status)


AUDIT_INCOHERENT_CASES = [
    ("evidence_for_a_missing_finding", "established",
     lambda r: set_in(r, "exposure_evidence.0.source_id", "job.config:res/ghost/config_used.json")),
    ("evidence_for_a_finding_of_another_nature", "non_oos", lambda r: set_in(r, "exposure_evidence.0.source_id", WF_FINDING_ID)),
    ("established_exposure_denied_by_the_evidence", "established", evidence_status("ABSENCE_NOT_ESTABLISHED")),
    ("established_exposure_turned_into_established_absence", "established", evidence_status("ABSENCE_ESTABLISHED")),
    ("unestablished_absence_turned_into_established_exposure", "unresolved", evidence_status("ESTABLISHED_BY_EXECUTION_WINDOW")),
    ("unestablished_absence_turned_into_established_absence", "unresolved", evidence_status("ABSENCE_ESTABLISHED")),
    ("resolved_execution_without_any_evidence", "established", lambda r: r.update(exposure_evidence=[])),
    ("non_oos_note_for_a_missing_finding", "non_oos", lambda r: set_in(r, "non_oos_validations.0.source_id", "validation.run:res/ghost")),
    ("non_oos_note_for_a_job_finding", "non_oos", lambda r: set_in(r, "non_oos_validations.0.source_id", JOB_FINDING_ID)),
    ("non_oos_note_with_another_content_hash", "non_oos", lambda r: set_in(r, "non_oos_validations.0.content_hash", h("other"))),
]


@pytest.mark.parametrize("name, fixture, mutate", AUDIT_INCOHERENT_CASES, ids=[case[0] for case in AUDIT_INCOHERENT_CASES])
def test_an_audit_register_that_contradicts_its_findings_is_refused_even_with_a_valid_hash(tmp_path, name, fixture, mutate):
    assembly = {"established": lambda: assemble(interpret(tmp_path)),
                "unresolved": lambda: assemble(interpret(tmp_path, job=UNRESOLVED_JOB)),
                "non_oos": lambda: assemble(walk_forward_interpretation(tmp_path))}[fixture]()
    assert refused(forge(tmp_path, mutate, assembly=assembly)).failure is store.StoreFailure.SCHEMA


def test_resolved_paths_are_local_audit_data_covered_by_the_content_hash_but_by_no_portable_identity(tmp_path):
    """Les mêmes sources dans deux emplacements donnent les mêmes identités SCIENTIFIQUES et portables ; seul `inventory_content_hash`
    (identité du FICHIER, donc de la machine) change avec le chemin résolu. Aucune formule d'E3-A ne lit un chemin."""
    first = store.build_exposure_inventory_record(assemble(interpret(tmp_path / "machine_a")), created_at=CREATED_AT)
    second = store.build_exposure_inventory_record(assemble(interpret(tmp_path / "machine_b")), created_at=CREATED_AT)
    assert first["scan_pins"][0]["roots"][0]["resolved_path"] != second["scan_pins"][0]["roots"][0]["resolved_path"]
    for name in ("inventory_id", "inventory_content_digest", "static_sources_digest", "overlap_projection_hash", "findings"):
        assert first[name] == second[name], name
    assert first["inventory_content_hash"] != second["inventory_content_hash"]


# ── Revue B de clôture : aucune preuve d'exclusion n'existe (23.30.1), couverture P2 réservée aux jobs, relevé symétrique ──

def forged_established_absence(r):
    """Finding de job RESOLVED/NO_OVERLAP hors de W (cohérent pour E3-A) avec une preuve `ABSENCE_ESTABLISHED` : l'ADR 23.30.1 dit
    « preuves d'exclusion reconnues : aucune à ce jour » (23.30.4 : jamais NO_OVERLAP pour un job)."""
    set_in(r, "findings.0.overlap", "NO_OVERLAP")
    set_in(r, "findings.0.window_start_utc", "2025-01-01T00:00:00.000000Z")
    set_in(r, "findings.0.window_end_utc", "2025-02-01T00:00:00.000000Z")
    set_in(r, "exposure_evidence.0.status", "ABSENCE_ESTABLISHED")


def coverage_evidence(manifest_source_id):
    return lambda r: r.update(exposure_evidence=[{"source_id": JOB_FINDING_ID, "status": "ESTABLISHED_BY_LOADED_COVERAGE",
                                                  "manifest_source_id": manifest_source_id, "manifest_content_hash": h("manifest")}])


def test_no_absence_of_exposure_is_ever_accepted_for_an_execution_source_because_no_exclusion_proof_exists(tmp_path):
    assert refused(forge(tmp_path, forged_established_absence, assembly=assemble(interpret(tmp_path)))).failure is store.StoreFailure.SCHEMA


def test_a_loaded_coverage_evidence_must_cite_the_manifest_of_its_own_job(tmp_path):
    own = "job.manifest:res/job_1/data_manifest.json"
    loaded = store.load_exposure_inventory(forge(tmp_path, coverage_evidence(own), assembly=assemble(interpret(tmp_path))))
    assert loaded.exposure_evidence[0].manifest_source_id == own
    for name, other in (("another_job", "job.manifest:res/job_2/data_manifest.json"), ("another_root", "job.manifest:other/job_1/data_manifest.json"),
                        ("not_a_manifest", "job.config:res/job_1/config_used.json")):
        (tmp_path / name).mkdir()
        assert refused(forge(tmp_path / name, coverage_evidence(other), assembly=assemble(interpret(tmp_path / name)))).failure \
            is store.StoreFailure.SCHEMA, name


def test_an_unresolved_execution_finding_by_unknown_window_or_timezone_must_have_its_register_entry(tmp_path):
    assembly = assemble(interpret(tmp_path, job=UNRESOLVED_JOB))
    assert refused(forge(tmp_path, lambda r: r.update(exposure_evidence=[]), assembly=assembly)).failure is store.StoreFailure.SCHEMA


def test_a_non_oos_note_cannot_target_an_unresolved_finding_of_another_nature(tmp_path):
    """Une note non OOS ne se rattache qu'à un finding UNKNOWN_SOURCE : un job non résolu de même `content_hash` ne convient pas."""
    assembly = assemble(interpret(tmp_path, job=UNRESOLVED_JOB))

    def note_on_the_job(record):
        record["non_oos_validations"] = [{"source_id": JOB_FINDING_ID, "validation_type": "walk_forward",
                                          "content_hash": record["findings"][0]["content_hash"]}]

    assert refused(forge(tmp_path, note_on_the_job, assembly=assembly)).failure is store.StoreFailure.SCHEMA


def test_an_unexpected_os_error_while_writing_is_a_typed_refusal(tmp_path, monkeypatch):
    assembly = assemble(interpret(tmp_path))

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(store, "save_exclusive", denied)
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.publish_exposure_inventory(campaign(tmp_path), assembly, created_at=CREATED_AT)
    assert refusal.value.failure is store.StoreFailure.UNREADABLE


def test_a_loaded_coverage_evidence_is_refused_on_a_validation_run_finding(tmp_path):
    """P2 (couverture chargée d'un manifeste) n'existe que pour un job : un finding OOS ne peut pas la citer."""
    own = "job.manifest:res/job_1/data_manifest.json"

    def as_oos_with_coverage(record):
        set_in(record, "findings.0.source_kind", "VALIDATION_RUN_OOS")
        coverage_evidence(own)(record)

    assert refused(forge(tmp_path, as_oos_with_coverage, assembly=assemble(interpret(tmp_path)))).failure is store.StoreFailure.SCHEMA


def test_an_unresolved_execution_finding_by_unknown_timezone_must_have_its_register_entry(tmp_path):
    assembly = assemble(interpret(tmp_path, job=("2026-02-01", "2026-02-10")))                    # dates civiles : TIMEZONE_UNKNOWN
    (finding,) = [f for f in assembly.inventory.findings]
    assert finding.unresolved_cause.value == "TIMEZONE_UNKNOWN" and assembly.interpretation.exposure_evidence
    assert refused(forge(tmp_path, lambda r: r.update(exposure_evidence=[]), assembly=assembly)).failure is store.StoreFailure.SCHEMA


# ── D3/D7 (ADR 0025 23.31.2, 23.31.6) : versions et digests enregistrés ; lecture historique intègre ≠ requalification ─────────

from tests.gate_v_exposure_support import write_json  # noqa: E402

V2, V3 = "gate_v_exposure_interpreters_v2", "gate_v_exposure_interpreters_v3"
CAMPAIGN_DIGEST_V2 = "cb94f97f1b2c53f8839f90547b3ad619e5a3a64dacfb857071554d329a6a6fa7"    # mesuré sur `git archive 41fe58d` (B3 v2 publié)
CAMPAIGN_DIGEST_V3 = "7cc0cb309210f43cc0e6e00a2a220483196fdc3ff1d7e285aff758313de2e04f"    # table CAMPAIGN_DIR courante (23.31.2)


def area(tmp_path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def campaign_assembly(tmp_path):
    """Assemblage d'une racine `CAMPAIGN_DIR` (ancre seule) : son épinglage de scan porte le digest de la table de campagne."""
    directory = tmp_path / "camp_src"
    write_json(directory / "plan.json", {"campaign_id": "x"})
    root = b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, AuditRoot("camp", str(directory)))
    return assemble(b3.interpret_audit_roots((root,), LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1]))


def relabel(version, digest=None):
    def mutate(record):
        set_in(record, "rules_versions.b3_interpreters", version)
        if digest is not None:
            record["scan_pins"][0]["rules_digest"] = digest
    return mutate


def test_a_new_a0_records_b3_v3_and_is_read_as_current(tmp_path):
    a0 = store.load_exposure_inventory(publish(tmp_path))
    assert a0.rules_versions.b3_interpreters == V3 == b3.B3_SEMANTICS_VERSION
    assert a0.rules_versions.is_current() is True


def test_an_a0_recorded_under_the_published_b3_v2_is_an_intact_historical_read_never_a_current_one(tmp_path):
    current = store.load_exposure_inventory(publish(area(tmp_path, "cur")))
    historical = store.load_exposure_inventory(forge(area(tmp_path, "hist"), relabel(V2)))
    assert historical.rules_versions.b3_interpreters == V2 and historical.rules_versions.is_current() is False
    assert [pin.layout for pin in historical.scan_pins] == [b3.RootLayout.RESULTS]          # table RESULTS identique en v2 et en v3
    assert (historical.inventory_id, historical.inventory_content_digest) == (current.inventory_id, current.inventory_content_digest)
    assert historical.inventory_content_hash != current.inventory_content_hash                # l'étiquette est couverte par le hash seul


def test_a_recorded_rules_digest_that_is_not_the_one_of_the_recorded_b3_version_is_refused(tmp_path):
    error = refused(forge(tmp_path, lambda r: r["scan_pins"][0].update(rules_digest="0" * 64)))
    assert error.failure is store.StoreFailure.RULES_DIGEST_MISMATCH


def test_the_campaign_rules_digest_tells_v2_from_v3_and_must_match_the_recorded_version(tmp_path):
    current = store.load_exposure_inventory(publish(area(tmp_path, "cur"), campaign_assembly(tmp_path)))
    assert [(p.layout, p.rules_digest) for p in current.scan_pins] == [(b3.RootLayout.CAMPAIGN_DIR, CAMPAIGN_DIGEST_V3)]
    v2_label_v3_table = forge(area(tmp_path, "a"), relabel(V2), assembly=campaign_assembly(tmp_path))
    v3_label_v2_table = forge(area(tmp_path, "b"), relabel(V3, CAMPAIGN_DIGEST_V2), assembly=campaign_assembly(tmp_path))
    for path in (v2_label_v3_table, v3_label_v2_table):
        assert refused(path).failure is store.StoreFailure.RULES_DIGEST_MISMATCH
    historical = store.load_exposure_inventory(forge(area(tmp_path, "c"), relabel(V2, CAMPAIGN_DIGEST_V2), assembly=campaign_assembly(tmp_path)))
    assert historical.rules_versions.is_current() is False and historical.inventory_id == current.inventory_id


@pytest.mark.parametrize("key", ["e3a_inventory", "e3a_classification", "b4_assembly"])
def test_e3a_and_b4_rules_have_a_single_known_version(tmp_path, key):
    assert refused(forge(tmp_path, lambda r: set_in(r, f"rules_versions.{key}", "unknown_v0"))).failure is store.StoreFailure.UNKNOWN_VERSION


def test_an_unknown_b3_version_is_refused_even_with_a_digest_known_for_another_version(tmp_path):
    error = refused(forge(tmp_path, relabel("gate_v_exposure_interpreters_v1")))
    assert error.failure is store.StoreFailure.UNKNOWN_VERSION


# ── D5 (ADR 0025 23.31.5) : plafonds = gardes SYNTHETIC provisoires, jamais un défaut REAL ─────────────────────────────────────

def test_the_store_caps_are_synthetic_guards_never_qualified_for_real():
    assert store.OPERATIONAL_LIMITS_QUALIFIED_FOR_REAL is False
    assert (store.MAX_A0_BYTES, store.MAX_JSON_DEPTH) == (16 * 1024 * 1024, 32)


def test_publish_refuses_before_any_write_an_a0_larger_than_the_strict_reader_accepts(tmp_path, monkeypatch):
    """M2 : jamais un A0 publié que la relecture stricte refuserait (taille), ni de nom consommé par lui."""
    monkeypatch.setattr(store, "MAX_A0_BYTES", 512)
    with pytest.raises(store.ExposureStoreError) as refusal:
        publish(tmp_path)
    assert refusal.value.failure is store.StoreFailure.TOO_LARGE
    assert not (tmp_path / "campaign_dir" / "exposure").exists()


def test_publish_refuses_before_any_write_an_a0_that_the_strict_json_reader_would_refuse(tmp_path, monkeypatch):
    """M2 : le JSON strict (profondeur, flottants) est prouvé sur les octets à écrire, avant toute création."""
    monkeypatch.setattr(store, "MAX_JSON_DEPTH", 2)
    with pytest.raises(store.ExposureStoreError) as refusal:
        publish(tmp_path)
    assert refusal.value.failure is store.StoreFailure.NOT_JSON
    assert not (tmp_path / "campaign_dir" / "exposure").exists()


@pytest.mark.parametrize("raw", [b'{"a": 1.5}', b'{"a": {"b": -2.0}}', b'{"a": [0, [1e300]]}', b'[{"x": 0.0}]'],
                         ids=["top", "nested_object", "nested_list", "list_of_objects"])
def test_the_normative_format_has_no_float_anywhere(raw):
    """23.29.4 « sans flottant » : défaut de schéma pour tout artefact (A0, déclaration, attestation), à toute profondeur."""
    with pytest.raises(store.ExposureStoreError) as refusal:
        store.parse_strict_record(raw)
    assert refusal.value.failure is store.StoreFailure.SCHEMA


def test_integers_booleans_nulls_and_texts_are_not_floats():
    assert store.parse_strict_record(b'{"a": [1, -2, 10000000000000000000000, true, null, "1.5"], "b": {"c": 0}}') == {
        "a": [1, -2, 10 ** 22, True, None, "1.5"], "b": {"c": 0}}
