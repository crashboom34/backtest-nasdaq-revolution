"""
tests/test_gate_v_exposure_store_pin.py — AF-V-07 K1 Étape 2, D8 / B5 : épinglage des plafonds de fichiers hachés (`HashLimits`) dans le A0.

Contrat (mission 2026-10-25) : le format HISTORIQUE du A0 est conservé À L'IDENTIQUE (24 clés, `version` = version scientifique d'E3-A, pins de scan à 5
clés, mêmes octets, même `inventory_content_hash`). Un NOUVEAU format, explicitement versionné par la clé `persistence_format`
(`gate_v_exposure_a0_format_v2`), distincte de `version`, ajoute à chaque pin dont la table de règles comporte des règles `HASHED_FILE` un bloc
`hash_limits` à trois entiers stricts. Aucune formule d'identité d'E3-A ne change (`inventory_id`, `inventory_content_digest`,
`static_sources_digest`, `overlap_projection_hash`). Aucun A0 historique n'est réécrit.

Fixtures SYNTHÉTIQUES (`tmp_path`) : aucune donnée de marché, aucun `FINAL_HOLDOUT`. Aucune table B3 publiée (v2/v3/v4) ne comporte de règle `HASHED_FILE` ;
les tests qui exigent une table « hachée » déclarent le digest d'une table publiée comme tel PAR `monkeypatch` (simulation de B3 v5, non écrit ici).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path

import pytest

import gate_v_exposure_interpreters as b3
import gate_v_exposure_scan as scan
import gate_v_exposure_store as store
from gate_v_final_holdout_protocol import EXPOSURE_INVENTORY_SEMANTICS_VERSION
from tests.gate_v_exposure_support import CREATED_AT, assemble, interpret

V2_FORMAT = "gate_v_exposure_a0_format_v2"
V1_LABEL = "gate_v_exposure_a0_format_v1"
HL = scan.HashLimits(max_hashed_file_bytes=1024, max_total_hashed_bytes=8192, max_hashed_files=16)
HL_NAMES = ("max_hashed_file_bytes", "max_total_hashed_bytes", "max_hashed_files")
HISTORICAL_LIMIT_NAMES = ("max_roots", "max_entries", "max_depth", "max_json_bytes", "max_total_read_bytes", "max_json_depth",
                          "max_name_length", "max_path_length", "max_attempts")
GOLDEN_PATH = "/golden/results"
GOLDEN_HASH = "5690e62d92b4033b79dc5c604a1d41db7122945d5ba2e4dcf56540874c6817b8"      # A0 historique figé AVANT toute modification de B5
GOLDEN = json.loads(r'''{"campaign_id":"campaign_current","complete":true,"created_at":"2026-10-20T08:00:00.000000Z","derived_root_labels":[],"exposure_evidence":[{"manifest_content_hash":null,"manifest_source_id":null,"source_id":"job.config:res/job_1/config_used.json","status":"ESTABLISHED_BY_EXECUTION_WINDOW"}],"findings":[{"campaign_id":null,"content_hash":"e97d3edad38ee5b5d856959aa25564a4dca14e69101d244551345588dae34659","overlap":"OVERLAPS","snapshot_id":null,"source_id":"job.config:res/job_1/config_used.json","source_kind":"JOB_EXECUTION","status":"RESOLVED","unresolved_cause":null,"window_end_utc":"2026-02-10T00:00:00.000000Z","window_start_utc":"2026-02-01T00:00:00.000000Z"}],"incomplete_reasons":[],"inventory_content_digest":"f03d46febd38f4b97084abec961c04d7bf4cf71f40316c7d9925b377d47d8d1c","inventory_content_hash":"5690e62d92b4033b79dc5c604a1d41db7122945d5ba2e4dcf56540874c6817b8","inventory_id":"25691edd72575f46b5ae0ebc391528b8e2e7885d2ca14495452a35c507137e96","non_oos_validations":[],"overlap_projection_hash":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","own_record_stage":"NO_OWN_RECORDS","plans":[],"registry":{"chain_head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","registry_id":"reg_main"},"rules_versions":{"b3_interpreters":"gate_v_exposure_interpreters_v4","b4_assembly":"gate_v_exposure_inventory_assembly_v1","e3a_classification":"gate_v_exposure_classification_v1","e3a_inventory":"gate_v_exposure_inventory_v1"},"scan_pins":[{"hooks_used":false,"layout":"RESULTS","limits":{"max_attempts":1,"max_depth":8,"max_entries":2000,"max_json_bytes":1000000,"max_json_depth":32,"max_name_length":128,"max_path_length":1024,"max_roots":8,"max_total_read_bytes":8000000},"roots":[{"label":"res","may_be_empty":false,"resolved_path":"/golden/results"}],"rules_digest":"9014a865e7c5c4fea0ec7fc4cbcd3e8d76357a51693c339981e50f523ae51960"}],"scanned_roots":["res"],"static_sources_digest":"244cb36ae8889e6091ab64a81f4617b529cd597c34b0c5238eb8884c4b9fb685","trial_accounting":{"abandoned_reservations":0,"campaigns":0,"failed_ingestion_attempts":0,"research_runs":0,"strategies":0,"void_commitments":0},"trial_accounting_provenance":{"abandoned_reservations":"NOT_OBSERVED","campaigns":"OBSERVED","failed_ingestion_attempts":"NOT_OBSERVED","reasons":["abandoned_reservations:CLOSING_VIEW_NOT_PROVIDED","failed_ingestion_attempts:VIEW_NOT_PROVIDED","trials:VIEW_NOT_PROVIDED","void_commitments:VIEW_NOT_PROVIDED"],"research_runs":"NOT_OBSERVED","strategies":"NOT_OBSERVED","void_commitments":"NOT_OBSERVED"},"version":"gate_v_exposure_inventory_v1","window_end_utc":"2026-04-01T00:00:00.000000Z","window_start_utc":"2026-01-01T00:00:00.000000Z"}''')
RESULTS_V4_DIGEST = "9014a865e7c5c4fea0ec7fc4cbcd3e8d76357a51693c339981e50f523ae51960"


def adr_bytes(record: dict) -> bytes:
    """Représentation persistée normative (ADR 0025 23.29.4), recopiée."""
    return (json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def adr_hash(record: dict) -> str:
    body = {key: value for key, value in record.items() if key != "inventory_content_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def hashed_interpretation(tmp_path, hash_limits=HL):
    """Interprétation B3 RÉELLE (table v4) dont le scan a, de plus, appliqué des `hash_limits` (comptes cohérents : aucun fichier haché observé)."""
    interpretation = interpret(tmp_path)
    scans = tuple(b3.InterpretedScan(item.layout, dataclasses.replace(item.scan, hash_limits=hash_limits)) for item in interpretation.scans)
    return dataclasses.replace(interpretation, scans=scans)


@pytest.fixture
def hashed_table(monkeypatch):
    """Simule « B3 v5 » : la table RESULTS de la version courante de B3 est déclarée comme comportant des règles `HASHED_FILE`."""
    triple = (b3.B3_SEMANTICS_VERSION, b3.RootLayout.RESULTS, RESULTS_V4_DIGEST)
    monkeypatch.setattr(store, "HASHED_RULES_DIGESTS", frozenset({triple}))
    return triple


@pytest.fixture
def declare_hashed_table(monkeypatch):
    """Comme `hashed_table`, mais l'appelant déclare la table hachée À SON HEURE (après avoir lu ou produit des A0 historiques)."""
    def declare():
        monkeypatch.setattr(store, "HASHED_RULES_DIGESTS", frozenset({(b3.B3_SEMANTICS_VERSION, b3.RootLayout.RESULTS, RESULTS_V4_DIGEST)}))
    return declare


def write_a0(tmp_path, record, *, rehash=True, rename=True) -> Path:
    if rehash:
        record = dict(record, inventory_content_hash=store.compute_inventory_content_hash(record))
    directory = tmp_path / "campaign_dir" / "exposure"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (f"inventory_{record['inventory_content_hash']}.json" if rename else "inventory_" + "0" * 64 + ".json")
    target.write_bytes(adr_bytes(record))
    return target


def refused(path, failure):
    with pytest.raises(store.ExposureStoreError) as info:
        store.load_exposure_inventory(path)
    assert info.value.failure is failure, info.value
    return info.value


def v2_record(tmp_path, hash_limits=HL):
    return store.build_exposure_inventory_record(assemble(hashed_interpretation(tmp_path, hash_limits)), created_at=CREATED_AT)


# ══ Format HISTORIQUE : inchangé ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_golden_historical_a0_still_loads_with_the_same_identities_and_the_historical_format_label(tmp_path):
    assert adr_hash(GOLDEN) == GOLDEN["inventory_content_hash"] == GOLDEN_HASH == store.compute_inventory_content_hash(GOLDEN)
    loaded = store.load_exposure_inventory(write_a0(tmp_path, GOLDEN, rehash=False))
    assert loaded.persistence_format == V1_LABEL and loaded.inventory_content_hash == GOLDEN_HASH
    (pin,) = loaded.scan_pins
    assert pin.hash_limits is None and pin.limits.max_attempts == 1 and pin.rules_digest == RESULTS_V4_DIGEST
    assert loaded.inventory_id == GOLDEN["inventory_id"] and loaded.rules_versions.is_current() is True
    assert sorted(GOLDEN) == sorted(store.A0_RECORD_KEYS) and len(GOLDEN) == 24 and GOLDEN["version"] == EXPOSURE_INVENTORY_SEMANTICS_VERSION


def test_a_historical_interpretation_still_produces_exactly_the_historical_record_and_hash(tmp_path):
    record = store.build_exposure_inventory_record(assemble(interpret(tmp_path)), created_at=CREATED_AT)
    assert sorted(record) == sorted(store.A0_RECORD_KEYS) and "persistence_format" not in record
    for pin in record["scan_pins"]:
        assert set(pin) == {"layout", "rules_digest", "limits", "hooks_used", "roots"} and set(pin["limits"]) == set(HISTORICAL_LIMIT_NAMES)
        for root in pin["roots"]:
            root["resolved_path"] = GOLDEN_PATH
    record["inventory_content_hash"] = store.compute_inventory_content_hash(record)
    assert record == GOLDEN and record["inventory_content_hash"] == GOLDEN_HASH           # mêmes clés, mêmes valeurs, même hash : octets identiques
    assert adr_bytes(record) == adr_bytes(GOLDEN)


def test_a_historical_record_with_a_hash_limits_block_in_a_pin_is_refused_even_when_rehashed(tmp_path):
    record = json.loads(json.dumps(GOLDEN))
    record["scan_pins"][0]["hash_limits"] = dict(zip(HL_NAMES, (1024, 8192, 16)))
    refused(write_a0(tmp_path, record), store.StoreFailure.SCHEMA)


def test_the_nine_historical_scan_limits_are_still_the_only_pinned_limits_of_a_historical_pin():
    assert store._LIMIT_NAMES == HISTORICAL_LIMIT_NAMES
    pin = store.ScanPin(b3.RootLayout.RESULTS, RESULTS_V4_DIGEST, scan.ScanLimits(**GOLDEN["scan_pins"][0]["limits"]), False, ())   # construction historique à 5 arguments
    assert pin.hash_limits is None


def test_loading_a_historical_a0_never_rewrites_it_and_publishing_a_new_format_leaves_it_byte_identical(tmp_path, declare_hashed_table):
    path = write_a0(tmp_path, GOLDEN, rehash=False)
    before = (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_size)
    store.load_exposure_inventory(path)
    declare_hashed_table()
    refused(path, store.StoreFailure.SCHEMA)           # un A0 historique ne prouve jamais un scan HASHED_FILE : une table déclarée hachée l'exige au format 2
    published = store.publish_exposure_inventory(tmp_path / "campaign_dir", assemble(hashed_interpretation(tmp_path)), created_at=CREATED_AT)
    assert published != path and (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_size) == before
    assert sorted(p.name for p in path.parent.iterdir()) == sorted([path.name, published.name])


# ══ Nouveau format : producteur ═══════════════════════════════════════════════════════════════════════════════════════════════════
def test_a_scan_that_applied_hash_limits_is_persisted_in_the_new_format_with_the_exact_limits_and_unchanged_scientific_identities(tmp_path, declare_hashed_table):
    historical = store.build_exposure_inventory_record(assemble(interpret(tmp_path / "b")), created_at=CREATED_AT)
    declare_hashed_table()
    record = v2_record(tmp_path / "a")
    assert sorted(record) == sorted(store.A0_RECORD_KEYS_V2) and len(record) == 25
    assert record["persistence_format"] == V2_FORMAT and record["version"] == EXPOSURE_INVENTORY_SEMANTICS_VERSION       # distincte de la version d'E3-A
    (pin,) = record["scan_pins"]
    assert set(pin) == {"layout", "rules_digest", "limits", "hooks_used", "roots", "hash_limits"}
    assert pin["hash_limits"] == dict(zip(HL_NAMES, (1024, 8192, 16))) and set(pin["limits"]) == set(HISTORICAL_LIMIT_NAMES)
    for name in ("inventory_id", "inventory_content_digest", "static_sources_digest", "overlap_projection_hash", "complete", "findings"):
        assert record[name] == historical[name], name                                       # aucune identité scientifique ne change
    assert record["inventory_content_hash"] == adr_hash(record) != historical["inventory_content_hash"]


@pytest.mark.parametrize("limits", [
    scan.HashLimits(max_hashed_file_bytes=1, max_total_hashed_bytes=1, max_hashed_files=1),
    scan.HashLimits(max_hashed_file_bytes=3, max_total_hashed_bytes=7, max_hashed_files=2),
    scan.HashLimits(max_hashed_file_bytes=2**40, max_total_hashed_bytes=2**41, max_hashed_files=10**6),
])
def test_the_pin_carries_exactly_the_limits_applied_by_the_scanner_whatever_their_value(tmp_path, hashed_table, limits):
    (pin,) = v2_record(tmp_path, limits)["scan_pins"]
    assert pin["hash_limits"] == {"max_hashed_file_bytes": limits.max_hashed_file_bytes, "max_total_hashed_bytes": limits.max_total_hashed_bytes,
                                  "max_hashed_files": limits.max_hashed_files}


def test_the_producer_refuses_hash_limits_for_a_table_without_hashed_rules_and_a_hashed_table_without_hash_limits(tmp_path, monkeypatch):
    with pytest.raises(ValueError):                                                          # table publiée sans règle HASHED_FILE + plafonds fournis
        store.build_exposure_inventory_record(assemble(hashed_interpretation(tmp_path / "a")), created_at=CREATED_AT)
    triple = (b3.B3_SEMANTICS_VERSION, b3.RootLayout.RESULTS, RESULTS_V4_DIGEST)
    monkeypatch.setattr(store, "HASHED_RULES_DIGESTS", frozenset({triple}))
    with pytest.raises(ValueError):                                                          # table hachée sans plafonds appliqués
        store.build_exposure_inventory_record(assemble(interpret(tmp_path / "b")), created_at=CREATED_AT)


def test_publish_roundtrips_the_new_format_and_the_pin_equals_the_hash_limits_the_scan_applied(tmp_path, hashed_table):
    (tmp_path / "campaign_dir").mkdir()
    path = store.publish_exposure_inventory(tmp_path / "campaign_dir", assemble(hashed_interpretation(tmp_path)), created_at=CREATED_AT)
    loaded = store.load_exposure_inventory(path)
    assert loaded.persistence_format == V2_FORMAT and loaded.rules_versions.is_current() is True
    (pin,) = loaded.scan_pins
    assert pin.hash_limits == HL and isinstance(pin.hash_limits, scan.HashLimits) and pin.limits.max_attempts == 1
    assert path.read_bytes() == adr_bytes(json.loads(path.read_bytes()))                    # point fixe d'octets de la sérialisation normative


# ══ Nouveau format : relecteur strict ═════════════════════════════════════════════════════════════════════════════════════════════
def edited(tmp_path, mutate, *, rehash=True):
    record = v2_record(tmp_path)
    mutate(record)
    return write_a0(tmp_path, record, rehash=rehash)


def test_a_budget_changed_by_one_byte_is_detected_by_the_content_hash_and_by_the_file_name(tmp_path, hashed_table):
    path = edited(tmp_path, lambda r: r["scan_pins"][0]["hash_limits"].update(max_total_hashed_bytes=8193), rehash=False)
    refused(path, store.StoreFailure.HASH_MISMATCH)
    path = edited(tmp_path / "second", lambda r: r["scan_pins"][0]["hash_limits"].update(max_total_hashed_bytes=8193), rehash=True)
    assert store.load_exposure_inventory(path).scan_pins[0].hash_limits.max_total_hashed_bytes == 8193      # cohérent, mais AUTRE A0 (autre hash, autre nom)
    renamed = path.with_name("inventory_" + "1" * 64 + ".json")
    path.rename(renamed)
    refused(renamed, store.StoreFailure.NAME_MISMATCH)


@pytest.mark.parametrize("name, mutate", [
    ("pin_without_hash_limits_for_a_hashed_table", lambda r: r["scan_pins"][0].pop("hash_limits")),
    ("hash_limits_null", lambda r: r["scan_pins"][0].update(hash_limits=None)),
    ("hash_limits_empty", lambda r: r["scan_pins"][0].update(hash_limits={})),
    ("hash_limits_missing_key", lambda r: r["scan_pins"][0]["hash_limits"].pop("max_hashed_files")),
    ("hash_limits_extra_key", lambda r: r["scan_pins"][0]["hash_limits"].update(max_hashed_extra=1)),
    ("hash_limits_not_an_object", lambda r: r["scan_pins"][0].update(hash_limits=[1024, 8192, 16])),
    ("file_limit_zero", lambda r: r["scan_pins"][0]["hash_limits"].update(max_hashed_file_bytes=0)),
    ("total_limit_negative", lambda r: r["scan_pins"][0]["hash_limits"].update(max_total_hashed_bytes=-1)),
    ("count_limit_zero", lambda r: r["scan_pins"][0]["hash_limits"].update(max_hashed_files=0)),
    ("file_limit_bool", lambda r: r["scan_pins"][0]["hash_limits"].update(max_hashed_file_bytes=True)),
    ("count_limit_bool", lambda r: r["scan_pins"][0]["hash_limits"].update(max_hashed_files=True)),
    ("file_limit_float", lambda r: r["scan_pins"][0]["hash_limits"].update(max_hashed_file_bytes=1024.0)),
    ("file_limit_text", lambda r: r["scan_pins"][0]["hash_limits"].update(max_hashed_file_bytes="1024")),
    ("file_limit_null", lambda r: r["scan_pins"][0]["hash_limits"].update(max_hashed_file_bytes=None)),
    ("file_above_total", lambda r: r["scan_pins"][0]["hash_limits"].update(max_hashed_file_bytes=9000)),
    ("unknown_pin_key", lambda r: r["scan_pins"][0].update(surprise=1)),
    ("historical_limits_extended", lambda r: r["scan_pins"][0]["limits"].update(max_hashed_files=16)),
    ("historical_limit_removed", lambda r: r["scan_pins"][0]["limits"].pop("max_attempts")),
])
def test_a_violation_of_the_new_pin_schema_is_refused_even_when_the_hash_is_recomputed(tmp_path, hashed_table, name, mutate):
    refused(edited(tmp_path, mutate), store.StoreFailure.SCHEMA)


def v2_forged_record():
    """Un enregistrement V2 FORGÉ : pin avec `hash_limits` sur une table publiée (aucune règle HASHED_FILE) — le producteur ne le produirait pas."""
    record = json.loads(json.dumps(GOLDEN))
    record["persistence_format"] = V2_FORMAT
    record["scan_pins"][0]["hash_limits"] = dict(zip(HL_NAMES, (1024, 8192, 16)))
    return record


def test_hash_limits_on_a_pin_whose_table_has_no_hashed_rule_are_refused_by_the_reader(tmp_path):
    refused(write_a0(tmp_path, v2_forged_record()), store.StoreFailure.SCHEMA)


def test_the_hashed_table_requirement_depends_on_the_recorded_b3_version_not_only_on_the_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "HASHED_RULES_DIGESTS", frozenset({(b3.B3_SEMANTICS_VERSION, b3.RootLayout.RESULTS, RESULTS_V4_DIGEST)}))
    record = v2_forged_record()
    record["rules_versions"]["b3_interpreters"] = "gate_v_exposure_interpreters_v3"        # même digest RESULTS en v3, mais v3 ne connaît pas HASHED_FILE
    refused(write_a0(tmp_path, record), store.StoreFailure.SCHEMA)
    assert store.load_exposure_inventory(write_a0(tmp_path / "ok", v2_forged_record())).scan_pins[0].hash_limits == HL      # version courante : accepté


def test_a_hashed_digest_unknown_to_the_recorded_b3_version_is_a_rules_digest_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "HASHED_RULES_DIGESTS", frozenset({(b3.B3_SEMANTICS_VERSION, b3.RootLayout.RESULTS, "ab" * 32)}))
    record = v2_forged_record()
    record["scan_pins"][0]["rules_digest"] = "ab" * 32
    refused(write_a0(tmp_path, record), store.StoreFailure.RULES_DIGEST_MISMATCH)


def test_the_format_selector_and_the_scientific_version_are_distinct_and_unknown_values_are_refused(tmp_path, hashed_table):
    refused(edited(tmp_path / "a", lambda r: r.update(persistence_format="gate_v_exposure_a0_format_v3")), store.StoreFailure.UNKNOWN_VERSION)
    refused(edited(tmp_path / "b", lambda r: r.update(persistence_format=V1_LABEL)), store.StoreFailure.UNKNOWN_VERSION)     # le format 1 est implicite, jamais écrit
    refused(edited(tmp_path / "c", lambda r: r.update(persistence_format=2)), store.StoreFailure.SCHEMA)
    refused(edited(tmp_path / "d", lambda r: r.update(persistence_format=None)), store.StoreFailure.SCHEMA)
    refused(edited(tmp_path / "e", lambda r: r.update(version="gate_v_exposure_inventory_v2")), store.StoreFailure.UNKNOWN_VERSION)
    refused(edited(tmp_path / "f", lambda r: r.update(version=V2_FORMAT)), store.StoreFailure.UNKNOWN_VERSION)               # le format ne se substitue pas à la version d'E3-A


def test_the_key_sets_of_the_two_formats_are_closed_and_cannot_be_mixed(tmp_path, hashed_table):
    refused(edited(tmp_path / "a", lambda r: r.pop("persistence_format")), store.StoreFailure.SCHEMA)           # pins avec hash_limits mais 24 clés : format 1 refusé
    refused(write_a0(tmp_path / "b", dict(GOLDEN, persistence_format=V2_FORMAT)), store.StoreFailure.SCHEMA)    # format 2 sans aucun plafond haché : deux sérialisations d'un même contenu
    refused(edited(tmp_path / "c", lambda r: r.update(surprise=1)), store.StoreFailure.SCHEMA)
    refused(edited(tmp_path / "d", lambda r: r.pop("registry")), store.StoreFailure.SCHEMA)


def test_a_format_2_record_without_any_hash_limits_pin_is_refused_for_that_reason_alone(tmp_path):
    # registre vide (aujourd'hui) : aucun contrôle par pin ne peut refuser ; seul le contrôle « format 2 => au moins un pin haché » le fait
    error = refused(write_a0(tmp_path, dict(GOLDEN, persistence_format=V2_FORMAT)), store.StoreFailure.SCHEMA)
    assert "format 2 sans aucun plafond" in str(error)


def test_a_directly_built_persisted_inventory_defaults_to_the_historical_format_label():
    default = {field.name: field.default for field in dataclasses.fields(store.PersistedExposureInventory)}["persistence_format"]
    assert default == store.A0_PERSISTENCE_FORMAT_V1 == V1_LABEL != V2_FORMAT


def test_the_producer_decides_whether_a_table_is_hashed_from_the_b3_version_of_the_interpretation(tmp_path, hashed_table):
    current = hashed_interpretation(tmp_path)
    (pin,) = store._scan_pins(current)
    assert pin["hash_limits"] == dict(zip(HL_NAMES, (1024, 8192, 16)))
    older = dataclasses.replace(current, semantics_version="gate_v_exposure_interpreters_v3")       # même disposition, même digest, autre version de B3
    with pytest.raises(ValueError):
        store._scan_pins(older)


def unregistered_hashed_tables(source_rules, registry):
    """Garde de concordance (B3 v5) : toute table de règles RÉELLEMENT utilisée qui comporte une règle `HASHED_FILE` doit figurer, avec sa version de B3 et
    son `rules_digest` recalculé, dans le registre ; sinon l'absence de pin `hash_limits` serait acceptée pour une table hachée."""
    missing = []
    for layout in b3.RootLayout:
        rules = source_rules(layout)
        if any(rule.entry_class.is_hashed for rule in rules):
            triple = (b3.B3_SEMANTICS_VERSION, layout, scan._rules_digest(rules))
            if triple not in registry:
                missing.append(triple)
    return missing


def test_no_historical_b3_table_is_registered_none_of_them_has_a_hashed_rule_and_the_guard_finds_nothing_missing():
    # B3 v5-A a inscrit SA table de campagne (voir tests/test_gate_v_exposure_store_v5.py) ; les tables v2, v3 et v4 ne comportent aucune règle HASHED_FILE.
    assert not {version for version, _, _ in store.HASHED_RULES_DIGESTS} & set(b3.KNOWN_B3_VERSIONS)
    assert not store.HASHED_RULES_DIGESTS & {(version, layout, digest) for version, layout, digest in b3.B3_RULES_DIGESTS}
    assert unregistered_hashed_tables(b3.source_rules, store.HASHED_RULES_DIGESTS) == []


def test_the_concordance_guard_detects_a_hashed_table_missing_from_the_registry_and_accepts_it_once_registered():
    hashed_rule = scan.SourceRule(("walk_forward", "manifest.json"), scan.EntryClass.HASHED_FILE, tag="wf_manifest")

    def with_hashed_results(layout):
        rules = tuple(b3.source_rules(layout))
        return rules + (hashed_rule,) if layout is b3.RootLayout.RESULTS else rules
    (triple,) = unregistered_hashed_tables(with_hashed_results, frozenset())
    assert triple[:2] == (b3.B3_SEMANTICS_VERSION, b3.RootLayout.RESULTS) and triple[2] != RESULTS_V4_DIGEST          # le digest recalculé est celui de la table RÉELLE
    assert unregistered_hashed_tables(with_hashed_results, frozenset({triple})) == []
    assert unregistered_hashed_tables(with_hashed_results, frozenset({(b3.B3_SEMANTICS_VERSION, b3.RootLayout.RESULTS, RESULTS_V4_DIGEST)})) == [triple]


def test_two_pins_are_checked_independently_hashed_layouts_need_limits_and_the_others_forbid_them(tmp_path, monkeypatch):
    campaign_digest = "9c05f8b068ac86d321c0d9889df0f3c0f1e015fdd8b17d208479554b1badb43b"
    monkeypatch.setattr(store, "HASHED_RULES_DIGESTS", frozenset({(b3.B3_SEMANTICS_VERSION, b3.RootLayout.RESULTS, RESULTS_V4_DIGEST)}))
    record = v2_forged_record()
    second = json.loads(json.dumps(record["scan_pins"][0]))
    second.update(layout="CAMPAIGN_DIR", rules_digest=campaign_digest)
    second.pop("hash_limits")
    second["roots"] = [{"label": "camp", "resolved_path": "/golden/campaign", "may_be_empty": False}]
    record["scan_pins"] = [second, record["scan_pins"][0]]                                 # triés par disposition : CAMPAIGN_DIR avant RESULTS
    record["derived_root_labels"] = ["camp"]                                               # racine dérivée : `scanned_roots` (et l'identité E3-A) restent ceux de l'A0 de référence
    loaded = store.load_exposure_inventory(write_a0(tmp_path, record))
    assert [(p.layout, p.hash_limits is not None) for p in loaded.scan_pins] == [(b3.RootLayout.CAMPAIGN_DIR, False), (b3.RootLayout.RESULTS, True)]
    record["scan_pins"][0]["hash_limits"] = dict(zip(HL_NAMES, (1, 2, 3)))                  # plafonds sur la disposition NON hachée : refusé
    refused(write_a0(tmp_path / "bad", record), store.StoreFailure.SCHEMA)


def test_the_scientific_identities_are_recomputed_by_e3a_in_the_new_format_too(tmp_path, hashed_table):
    refused(edited(tmp_path / "a", lambda r: r.update(inventory_id="0" * 64)), store.StoreFailure.IDENTITY_MISMATCH)
    refused(edited(tmp_path / "b", lambda r: r.update(inventory_content_digest="0" * 64)), store.StoreFailure.IDENTITY_MISMATCH)
    refused(edited(tmp_path / "c", lambda r: r["scan_pins"][0].update(rules_digest="0" * 64)), store.StoreFailure.RULES_DIGEST_MISMATCH)


def test_publish_refuses_before_writing_a_record_the_strict_reader_would_refuse(tmp_path):
    (tmp_path / "campaign_dir").mkdir()
    with pytest.raises(ValueError):
        store.publish_exposure_inventory(tmp_path / "campaign_dir", assemble(hashed_interpretation(tmp_path)), created_at=CREATED_AT)
    assert not (tmp_path / "campaign_dir" / "exposure").exists()


def test_the_module_opens_no_admission_and_keeps_its_non_real_qualification_flag():
    names = {name for name in vars(store) if not name.startswith("_")}
    assert not {name for name in names if any(word in name.lower() for word in ("admission", "admit", "reserve", "reservation", "claim", "authoris", "authoriz"))}
    assert store.OPERATIONAL_LIMITS_QUALIFIED_FOR_REAL is False
    assert store.A0_PERSISTENCE_FORMAT_V2 == V2_FORMAT and store.A0_RECORD_KEYS_V2 == store.A0_RECORD_KEYS + ("persistence_format",)
    assert store.HASH_LIMIT_NAMES == HL_NAMES and len(store.HASHED_RULES_DIGESTS) == 1               # B3 v5-A : uniquement le triplet vérifié de sa table de campagne
