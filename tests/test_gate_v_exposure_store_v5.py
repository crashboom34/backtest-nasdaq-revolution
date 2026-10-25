"""AF-V-07 B3 v5-A / B5 — persistance et relecture d'un A0 produit avec les tables v5 (format de persistance 2, `HASHED_RULES_DIGESTS`).

Un A0 de v5 est LISIBLE mais n'est jamais « courant » (`rules_versions.is_current()` faux : la version courante de B3 reste v4 tant qu'aucune décision n'a activé v5).
Le registre ne contient QUE le triplet vérifié de la table de campagne de v5 ; les triplets historiques (v2, v3, v4) n'y figurent pas. Aucune formule d'identité
d'E3-A, aucun format historique n'est modifié. Fixtures SYNTHÉTIQUES (`tmp_path`) : aucune donnée de marché, aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

import gate_v_exposure_interpreters as b3
import gate_v_exposure_interpreters_v5 as v5
import gate_v_exposure_scan as scan
import gate_v_exposure_store as store
from gate_v_exposure_scan import AuditRoot, HashLimits
from tests.gate_v_exposure_support import CREATED_AT, LIMITS, W, assemble
from tests.test_gate_v_exposure_interpreters_v5 import HL, build, evidence_files, wf_outputs
from tests.test_gate_v_exposure_store_pin import adr_bytes, adr_hash, refused, write_a0

V4 = "gate_v_exposure_interpreters_v4"
V5 = v5.B3_V5_SEMANTICS_VERSION
CAMPAIGN = b3.RootLayout.CAMPAIGN_DIR
CAMPAIGN_V5_DIGEST = "aa389aca9e29052ce9812c766f99abaf95a2bb656a3e82fcff17ab041d4a10af"      # littéral gelé, indépendant du module testé
V2_FORMAT = "gate_v_exposure_a0_format_v2"
JOB_CONFIG = {"run_id": "job_1", "strategy_name": "s", "opt_start_date": "2026-02-01T00:00:00+00:00", "opt_end_date": "2026-02-10T00:00:00+00:00"}


def results_root(tmp_path):
    results = tmp_path / "results"
    (results / "job_1").mkdir(parents=True)
    (results / "job_1" / "config_used.json").write_text(json.dumps(JOB_CONFIG), encoding="utf-8")
    return b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("res", str(results)))


def v5_interpretation(tmp_path, *, hl=HL, with_results=False):
    campaign = build(tmp_path / "campaign", {**wf_outputs(), **evidence_files()})
    roots = [b3.LayoutRoot(CAMPAIGN, AuditRoot("camp", str(campaign)))]
    if with_results:
        roots.append(results_root(tmp_path))
    return v5.interpret_audit_roots_v5(tuple(roots), LIMITS, hash_limits=hl, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])


def record_of(interpretation):
    return store.build_exposure_inventory_record(assemble(interpretation), created_at=CREATED_AT)


def copy_of(record):
    return json.loads(json.dumps(record))


# ══ B3-v5A-5 : registre et concordance ═══════════════════════════════════════════════════════════════════════════════════════════
def test_the_registry_holds_exactly_the_verified_v5_campaign_triple_and_no_historical_table():
    assert store.HASHED_RULES_DIGESTS == frozenset({(V5, CAMPAIGN, CAMPAIGN_V5_DIGEST)})
    assert not {version for version, _, _ in store.HASHED_RULES_DIGESTS} & set(b3.KNOWN_B3_VERSIONS)             # v2, v3, v4 : jamais inscrites
    assert not store.HASHED_RULES_DIGESTS & {(version, layout, digest) for version, layout, digest in b3.B3_RULES_DIGESTS}


def unregistered_hashed_tables(source_rules, version, registered):
    """Concordance : toute table RÉELLEMENT utilisée par `version` qui comporte une règle `HASHED_FILE` est inscrite avec son digest recalculé."""
    return [(version, layout, scan._rules_digest(source_rules(layout))) for layout in b3.RootLayout
            if any(rule.entry_class.is_hashed for rule in source_rules(layout)) and (version, layout, scan._rules_digest(source_rules(layout))) not in registered]


def test_every_hashed_v5_table_is_registered_and_every_registered_table_really_contains_hashed_rules():
    assert unregistered_hashed_tables(v5.source_rules_v5, V5, store.HASHED_RULES_DIGESTS) == []
    for version, layout, digest in store.HASHED_RULES_DIGESTS:
        assert version == V5 and digest == scan._rules_digest(v5.source_rules_v5(layout)) and any(r.entry_class.is_hashed for r in v5.source_rules_v5(layout))
        assert (version, layout, digest) in v5.B3_V5_RULES_DIGESTS                                                  # le digest enregistré est celui de la table v5 publiée


def test_the_concordance_guard_detects_an_unregistered_hashed_table_and_the_producer_refuses_it(tmp_path, monkeypatch):
    interpretation = v5_interpretation(tmp_path)
    monkeypatch.setattr(store, "HASHED_RULES_DIGESTS", frozenset())
    assert unregistered_hashed_tables(v5.source_rules_v5, V5, store.HASHED_RULES_DIGESTS) == [(V5, CAMPAIGN, CAMPAIGN_V5_DIGEST)]
    with pytest.raises(ValueError):                                                       # aucun inventaire ne peut s'appuyer sur une table hachée non enregistrée
        record_of(interpretation)


# ══ Producteur ════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_a_v5_campaign_inventory_is_produced_in_format_2_with_the_exact_applied_hash_limits_and_the_v5_version(tmp_path):
    record = record_of(v5_interpretation(tmp_path))
    assert record["persistence_format"] == V2_FORMAT and len(record) == 25
    assert record["rules_versions"]["b3_interpreters"] == V5
    (pin,) = record["scan_pins"]
    assert pin["layout"] == "CAMPAIGN_DIR" and pin["rules_digest"] == CAMPAIGN_V5_DIGEST
    assert pin["hash_limits"] == {"max_hashed_file_bytes": HL.max_hashed_file_bytes, "max_total_hashed_bytes": HL.max_total_hashed_bytes,
                                  "max_hashed_files": HL.max_hashed_files}
    assert set(pin["limits"]) == {"max_roots", "max_entries", "max_depth", "max_json_bytes", "max_total_read_bytes", "max_json_depth", "max_name_length",
                                  "max_path_length", "max_attempts"}


def test_only_the_hashed_table_pins_hash_limits_when_a_results_root_is_scanned_with_the_same_call(tmp_path):
    record = record_of(v5_interpretation(tmp_path, with_results=True))
    pins = {pin["layout"]: pin for pin in record["scan_pins"]}
    assert set(pins) == {"CAMPAIGN_DIR", "RESULTS"} and "hash_limits" in pins["CAMPAIGN_DIR"] and "hash_limits" not in pins["RESULTS"]
    assert pins["RESULTS"]["rules_digest"] == "9014a865e7c5c4fea0ec7fc4cbcd3e8d76357a51693c339981e50f523ae51960"      # table RESULTS identique à v4


def test_a_v5_inventory_without_a_hashed_table_is_written_in_the_historical_format_1_and_records_v5(tmp_path):
    interpretation = v5.interpret_audit_roots_v5((results_root(tmp_path),), LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    record = record_of(interpretation)
    assert "persistence_format" not in record and len(record) == 24 and record["rules_versions"]["b3_interpreters"] == V5
    assert all("hash_limits" not in pin for pin in record["scan_pins"])
    loaded = store.load_exposure_inventory(write_a0(tmp_path, record, rehash=False))
    assert loaded.persistence_format == store.A0_PERSISTENCE_FORMAT_V1 and loaded.rules_versions.b3_interpreters == V5


def test_the_producer_refuses_a_hashed_table_scan_that_carries_no_hash_limits_and_never_invents_a_default(tmp_path):
    interpretation = v5_interpretation(tmp_path)
    with pytest.raises(ValueError):                                       # un scan de fichiers hachés sans plafonds est incohérent dès la construction du résultat
        dataclasses.replace(interpretation.scans[0].scan, hash_limits=None)
    empty_scan = dataclasses.replace(interpretation.scans[0].scan, hash_limits=None, observations=(), hashed_bytes_read=0, hashed_files=0)
    hollow = dataclasses.replace(interpretation, scans=(dataclasses.replace(interpretation.scans[0], scan=empty_scan),))
    with pytest.raises(ValueError):                                       # même sans observation hachée : la table hachée exige des plafonds pour être persistée
        record_of(hollow)


# ══ Persistance et relecture du format 2 ═════════════════════════════════════════════════════════════════════════════════════════
def test_publish_and_reload_a_v5_inventory_keeps_every_scientific_identity_and_is_never_current(tmp_path):
    assembly = assemble(v5_interpretation(tmp_path))
    (tmp_path / "campaign_dir").mkdir()
    path = store.publish_exposure_inventory(tmp_path / "campaign_dir", assembly, created_at=CREATED_AT)
    loaded = store.load_exposure_inventory(path)
    assert loaded.persistence_format == V2_FORMAT and loaded.rules_versions.b3_interpreters == V5 and loaded.rules_versions.is_current() is False
    (pin,) = loaded.scan_pins
    assert pin.hash_limits == HL and isinstance(pin.hash_limits, HashLimits) and pin.rules_digest == CAMPAIGN_V5_DIGEST
    assert loaded.inventory_id == assembly.inventory_id and loaded.inventory_content_digest == assembly.inventory_content_digest
    assert path.read_bytes() == adr_bytes(json.loads(path.read_bytes())) and path.name == f"inventory_{adr_hash(json.loads(path.read_bytes()))}.json"


def test_changing_one_byte_of_a_hash_budget_in_a_v5_inventory_is_detected_by_the_content_hash_and_the_name(tmp_path):
    record = record_of(v5_interpretation(tmp_path))
    tampered = copy_of(record)
    tampered["scan_pins"][0]["hash_limits"]["max_hashed_files"] += 1
    refused(write_a0(tmp_path / "a", tampered, rehash=False), store.StoreFailure.HASH_MISMATCH)           # budget changé, hash inchangé : contenu ≠ hash
    coherent = write_a0(tmp_path / "b", tampered)                                                        # hash recalculé : un AUTRE A0 valide (autre hash, autre nom)
    assert store.load_exposure_inventory(coherent).scan_pins[0].hash_limits.max_hashed_files == HL.max_hashed_files + 1
    assert coherent.name != f"inventory_{record['inventory_content_hash']}.json"
    renamed = coherent.with_name("inventory_" + "1" * 64 + ".json")
    coherent.rename(renamed)
    refused(renamed, store.StoreFailure.NAME_MISMATCH)


def test_the_reader_refuses_a_v5_campaign_pin_without_hash_limits_even_when_the_hash_is_recomputed(tmp_path):
    broken = copy_of(record_of(v5_interpretation(tmp_path)))
    del broken["scan_pins"][0]["hash_limits"]
    refused(write_a0(tmp_path, broken), store.StoreFailure.SCHEMA)


def test_the_reader_refuses_hash_limits_on_a_v5_pin_whose_table_has_no_hashed_rule(tmp_path):
    forged = copy_of(record_of(v5_interpretation(tmp_path, with_results=True)))
    campaign_pin = next(pin for pin in forged["scan_pins"] if pin["layout"] == "CAMPAIGN_DIR")
    next(pin for pin in forged["scan_pins"] if pin["layout"] == "RESULTS")["hash_limits"] = dict(campaign_pin["hash_limits"])
    refused(write_a0(tmp_path, forged), store.StoreFailure.SCHEMA)


def test_the_reader_refuses_a_version_and_digest_that_do_not_belong_together(tmp_path):
    record = record_of(v5_interpretation(tmp_path))
    old_digest = copy_of(record)
    old_digest["scan_pins"][0]["rules_digest"] = "9c05f8b068ac86d321c0d9889df0f3c0f1e015fdd8b17d208479554b1badb43b"        # digest de la table v4 sous la version v5
    refused(write_a0(tmp_path / "a", old_digest), store.StoreFailure.RULES_DIGEST_MISMATCH)
    as_v4 = copy_of(record)
    as_v4["rules_versions"]["b3_interpreters"] = V4                                                                      # digest de la table v5 sous la version v4
    refused(write_a0(tmp_path / "b", as_v4), store.StoreFailure.RULES_DIGEST_MISMATCH)
    unknown = copy_of(record)
    unknown["rules_versions"]["b3_interpreters"] = "gate_v_exposure_interpreters_v6"
    refused(write_a0(tmp_path / "c", unknown), store.StoreFailure.UNKNOWN_VERSION)


def test_a_historical_v4_campaign_inventory_is_still_produced_and_read_unchanged_with_no_hash_limits(tmp_path):
    root = b3.LayoutRoot(CAMPAIGN, AuditRoot("camp", str(build(tmp_path / "campaign", {}))))
    interpretation = b3.interpret_audit_roots((root,), LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    record = record_of(interpretation)
    assert "persistence_format" not in record and len(record) == 24 and record["rules_versions"]["b3_interpreters"] == V4
    assert all("hash_limits" not in pin for pin in record["scan_pins"])
    loaded = store.load_exposure_inventory(write_a0(tmp_path, record, rehash=False))
    assert loaded.rules_versions.is_current() is True and loaded.persistence_format == store.A0_PERSISTENCE_FORMAT_V1
    with_limits = dataclasses.replace(interpretation, scans=tuple(dataclasses.replace(item, scan=dataclasses.replace(item.scan, hash_limits=HL)) for item in interpretation.scans))
    with pytest.raises(ValueError):                                                                                         # v4 + hash_limits : refusé (table non hachée)
        record_of(with_limits)


def test_v4_stays_the_only_current_b3_version_and_the_store_opens_no_admission():
    assert b3.B3_SEMANTICS_VERSION == V4 != V5 and V5 not in b3.KNOWN_B3_VERSIONS
    assert not [name for name in dir(store) if name.lower().startswith(("admit", "reserve", "authoris", "authoriz"))]
