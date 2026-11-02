"""N-VIDE-1 / B3 v6 / B5 — persistance et relecture d'un A0 produit avec la version v6 (format de persistance 2, `HASHED_RULES_DIGESTS`).

Un A0 de v6 est LISIBLE mais n'est jamais « courant » (`rules_versions.is_current()` reste faux : la version courante de B3 reste v4 sans décision d'activation). La table v6 est strictement la
table v5, donc son digest est celui de v5 : le registre ajoute le triplet (v6, CAMPAIGN_DIR, digest) sans retirer celui de v5 ni inscrire aucune table historique. Les formats 1 et 2 existants,
les formules d'identité d'E3-A et `is_current()` ne changent pas. Fixtures SYNTHÉTIQUES (`tmp_path`) : aucune donnée de marché, aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import json

import pytest

import gate_v_exposure_interpreters as b3
import gate_v_exposure_interpreters_v5 as v5
import gate_v_exposure_interpreters_v6 as v6
import gate_v_exposure_scan as scan
import gate_v_exposure_store as store
from gate_v_exposure_scan import AuditRoot, ScanHooks
from tests.gate_v_exposure_support import CREATED_AT, LIMITS, W, assemble
from tests.gate_v_manifest_scenarios import HL, SCENARIOS, realise, roots_of
from tests.test_gate_v_exposure_store_pin import refused, write_a0

V4 = "gate_v_exposure_interpreters_v4"
V5 = v5.B3_V5_SEMANTICS_VERSION
V6 = "gate_v_exposure_interpreters_v6"
CAMPAIGN = b3.RootLayout.CAMPAIGN_DIR
DIGEST = "aa389aca9e29052ce9812c766f99abaf95a2bb656a3e82fcff17ab041d4a10af"       # littéral gelé, indépendant des modules testés
V2_FORMAT = "gate_v_exposure_a0_format_v2"


def v6_interpretation(tmp_path, scenario="07-running-validations-empty", **kwargs):
    directory = realise(tmp_path / "campaign", SCENARIOS[scenario])
    return v6.interpret_audit_roots_v6(roots_of(directory), LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1], **kwargs)


def record_of(interpretation):
    return store.build_exposure_inventory_record(assemble(interpretation), created_at=CREATED_AT)


def copy_of(record):
    return json.loads(json.dumps(record))


# ══ Registre et concordance ═══════════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_registry_holds_exactly_the_v5_and_v6_campaign_triples_and_no_historical_table():
    assert store.HASHED_RULES_DIGESTS == frozenset({(V5, CAMPAIGN, DIGEST), (V6, CAMPAIGN, DIGEST)})
    assert not {version for version, _, _ in store.HASHED_RULES_DIGESTS} & set(b3.KNOWN_B3_VERSIONS)             # v2, v3, v4 : jamais inscrites
    assert not store.HASHED_RULES_DIGESTS & {(version, layout, digest) for version, layout, digest in b3.B3_RULES_DIGESTS}
    assert v6.B3_V6_SEMANTICS_VERSION == V6


def test_every_hashed_v6_table_is_registered_and_every_registered_v6_table_really_contains_hashed_rules():
    for layout in b3.RootLayout:
        rules = v6.source_rules_v6(layout)
        hashed = any(rule.entry_class.is_hashed for rule in rules)
        assert hashed == ((V6, layout, scan._rules_digest(rules)) in store.HASHED_RULES_DIGESTS)
    for version, layout, digest in store.HASHED_RULES_DIGESTS:
        assert digest == scan._rules_digest(v6.source_rules_v6(layout)) and (version, layout, digest) in (v5.B3_V5_RULES_DIGESTS + v6.B3_V6_RULES_DIGESTS)


def test_the_concordance_guard_detects_an_unregistered_v6_table_and_the_producer_refuses_it(tmp_path, monkeypatch):
    interpretation = v6_interpretation(tmp_path)
    monkeypatch.setattr(store, "HASHED_RULES_DIGESTS", frozenset({(V5, CAMPAIGN, DIGEST)}))
    with pytest.raises(ValueError):
        record_of(interpretation)


# ══ Producteur ════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_a_v6_campaign_inventory_is_produced_in_format_2_with_the_exact_applied_hash_limits_and_the_v6_version(tmp_path):
    record = record_of(v6_interpretation(tmp_path))
    assert record["persistence_format"] == V2_FORMAT and len(record) == 25 and record["rules_versions"]["b3_interpreters"] == V6
    (pin,) = record["scan_pins"]
    assert pin["layout"] == "CAMPAIGN_DIR" and pin["rules_digest"] == DIGEST
    assert pin["hash_limits"] == {"max_hashed_file_bytes": HL.max_hashed_file_bytes, "max_total_hashed_bytes": HL.max_total_hashed_bytes, "max_hashed_files": HL.max_hashed_files}


def test_a_v6_inventory_without_a_hashed_table_is_written_in_the_historical_format_1_and_records_v6(tmp_path):
    results = tmp_path / "results"
    (results / "job_1").mkdir(parents=True)
    (results / "job_1" / "config_used.json").write_text(json.dumps({"run_id": "job_1", "strategy_name": "s", "opt_start_date": "2026-02-01T00:00:00+00:00",
                                                                     "opt_end_date": "2026-02-10T00:00:00+00:00"}), encoding="utf-8")
    interpretation = v6.interpret_audit_roots_v6((b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("res", str(results))),), LIMITS, hash_limits=HL,
                                                 holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    record = record_of(interpretation)
    assert "persistence_format" not in record and len(record) == 24 and record["rules_versions"]["b3_interpreters"] == V6
    loaded = store.load_exposure_inventory(write_a0(tmp_path, record, rehash=False))
    assert loaded.persistence_format == store.A0_PERSISTENCE_FORMAT_V1 and loaded.rules_versions.b3_interpreters == V6


def test_the_new_manifest_reasons_are_persisted_as_incomplete_reasons_and_the_inventory_is_incomplete(tmp_path):
    record = record_of(v6_interpretation(tmp_path))
    assert record["complete"] is False
    assert record["incomplete_reasons"] == ["MANIFEST_RUN_IN_PROGRESS:camp/manifest.json#status"]
    assert record["findings"] == []                                                       # aucun finding fabriqué : une exécution en cours n'est pas une exposition prouvée


def test_an_assembly_from_a_scan_with_hooks_is_never_persisted_under_v6(tmp_path):
    hooked = v6_interpretation(tmp_path, hooks=ScanHooks(after_first_pass=lambda attempt: None))
    assert hooked.hooks_used is True
    with pytest.raises(ValueError):
        record_of(hooked)


# ══ Persistance et relecture du format 2 ═════════════════════════════════════════════════════════════════════════════════════════
def test_publish_and_reload_a_v6_inventory_keeps_every_identity_and_is_never_current(tmp_path):
    assembly = assemble(v6_interpretation(tmp_path))
    (tmp_path / "campaign_dir").mkdir()
    path = store.publish_exposure_inventory(tmp_path / "campaign_dir", assembly, created_at=CREATED_AT)
    loaded = store.load_exposure_inventory(path)
    assert loaded.persistence_format == V2_FORMAT and loaded.rules_versions.b3_interpreters == V6 and loaded.rules_versions.is_current() is False
    assert loaded.inventory_id == assembly.inventory_id and loaded.inventory_content_digest == assembly.inventory_content_digest
    assert loaded.incomplete_reasons == assembly.incomplete_reasons and loaded.inventory.complete is False
    (pin,) = loaded.scan_pins
    assert pin.hash_limits == HL and pin.rules_digest == DIGEST


def test_the_reader_refuses_to_flip_a_v6_inventory_to_complete_by_dropping_its_manifest_reasons(tmp_path):
    record = record_of(v6_interpretation(tmp_path))
    forged = copy_of(record)
    forged["incomplete_reasons"] = []
    refused(write_a0(tmp_path / "a", forged), store.StoreFailure.SCHEMA)                  # complete=False sans raison : incohérent
    forged["complete"] = True
    with pytest.raises(store.ExposureStoreError):
        store.load_exposure_inventory(write_a0(tmp_path / "b", forged))                  # complete=True : les identités E3-A recalculées ne concordent plus


def test_the_reader_refuses_a_v6_pin_without_hash_limits(tmp_path):
    broken = copy_of(record_of(v6_interpretation(tmp_path)))
    del broken["scan_pins"][0]["hash_limits"]
    refused(write_a0(tmp_path / "a", broken), store.StoreFailure.SCHEMA)


def test_the_reader_refuses_a_version_and_digest_that_do_not_belong_together_for_v6(tmp_path):
    record = record_of(v6_interpretation(tmp_path))
    old_digest = copy_of(record)
    old_digest["scan_pins"][0]["rules_digest"] = "9c05f8b068ac86d321c0d9889df0f3c0f1e015fdd8b17d208479554b1badb43b"        # digest de la table v4 sous la version v6
    refused(write_a0(tmp_path / "a", old_digest), store.StoreFailure.RULES_DIGEST_MISMATCH)
    as_v4 = copy_of(record)
    as_v4["rules_versions"]["b3_interpreters"] = V4                                                                      # digest de la table v5/v6 sous la version v4
    refused(write_a0(tmp_path / "b", as_v4), store.StoreFailure.RULES_DIGEST_MISMATCH)
    unknown = copy_of(record)
    unknown["rules_versions"]["b3_interpreters"] = "gate_v_exposure_interpreters_v7"
    refused(write_a0(tmp_path / "c", unknown), store.StoreFailure.UNKNOWN_VERSION)


def test_a_v5_record_and_a_v6_record_of_the_same_tree_differ_only_by_version_and_the_new_reasons(tmp_path):
    directory = realise(tmp_path / "campaign", SCENARIOS["01-ready-initial"])
    roots = roots_of(directory)
    r5 = record_of(v5.interpret_audit_roots_v5(roots, LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1]))
    r6 = record_of(v6.interpret_audit_roots_v6(roots, LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1]))
    assert r5["rules_versions"]["b3_interpreters"] == V5 and r6["rules_versions"]["b3_interpreters"] == V6
    differing = {key for key in r5 if r5[key] != r6[key]}
    assert differing <= {"rules_versions", "inventory_content_hash"}                      # aucune réécriture rétroactive d'identité : mêmes identités E3-A, même contenu scientifique


def test_a_historical_v4_and_v5_inventory_is_still_produced_and_read_unchanged(tmp_path):
    directory = realise(tmp_path / "campaign", SCENARIOS["01-ready-initial"])
    roots = roots_of(directory)
    r4 = record_of(b3.interpret_audit_roots(roots, LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1]))
    assert "persistence_format" not in r4 and r4["rules_versions"]["b3_interpreters"] == V4
    assert store.load_exposure_inventory(write_a0(tmp_path / "a", r4, rehash=False)).rules_versions.is_current() is True
    r5 = record_of(v5.interpret_audit_roots_v5(roots, LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1]))
    loaded = store.load_exposure_inventory(write_a0(tmp_path / "b", r5))
    assert loaded.rules_versions.b3_interpreters == V5 and loaded.rules_versions.is_current() is False


def test_v4_stays_the_only_current_b3_version_and_the_store_opens_no_admission():
    assert b3.B3_SEMANTICS_VERSION == V4 != V6 and V6 not in b3.KNOWN_B3_VERSIONS
    assert store.RulesVersions("a", "b", V6, "c").is_current() is False
    assert not [name for name in dir(store) if name.lower().startswith(("admit", "reserve", "authoris", "authoriz"))]


# ══ Relabelling v5 <-> v6 (même table, même digest) : altération DÉTECTABLE vs falsification AVEC recalcul d'authenticité ═══════════════════════════════════════════
def _v5_and_v6_records(tmp_path):
    roots = roots_of(realise(tmp_path / "campaign", SCENARIOS["01-ready-initial"]))
    kwargs = dict(hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    return (record_of(v5.interpret_audit_roots_v5(roots, LIMITS, **kwargs)), record_of(v6.interpret_audit_roots_v6(roots, LIMITS, **kwargs)))


def test_a_v5_v6_relabelling_without_recomputing_the_content_hash_is_detected_in_both_directions(tmp_path):
    r5, r6 = _v5_and_v6_records(tmp_path)
    as_v6, as_v5 = copy_of(r5), copy_of(r6)
    as_v6["rules_versions"]["b3_interpreters"], as_v5["rules_versions"]["b3_interpreters"] = V6, V5
    refused(write_a0(tmp_path / "a", as_v6, rehash=False, rename=True), store.StoreFailure.HASH_MISMATCH)          # le hash stocké est celui du contenu v5
    refused(write_a0(tmp_path / "b", as_v5, rehash=False, rename=True), store.StoreFailure.HASH_MISMATCH)


def test_a_v5_v6_relabelling_WITH_a_recomputed_content_hash_is_not_detected_by_the_rules_digest_and_stays_never_current(tmp_path):
    """LIMITE DOCUMENTÉE (non corrigée) : la table v6 EST la table v5 ; un `rules_digest` identique n'est PAS une équivalence sémantique (v6 ajoute des raisons que le digest ne couvre pas). Un auteur capable
    de recalculer l'authenticité (hash de contenu + nom de fichier) fait lire un A0 sous l'autre version ; ce n'est pas une attestation : la version relue n'est jamais courante et aucun droit n'en découle."""
    r5, r6 = _v5_and_v6_records(tmp_path)
    as_v6, as_v5 = copy_of(r5), copy_of(r6)
    as_v6["rules_versions"]["b3_interpreters"], as_v5["rules_versions"]["b3_interpreters"] = V6, V5
    loaded_v6 = store.load_exposure_inventory(write_a0(tmp_path / "a", as_v6))
    loaded_v5 = store.load_exposure_inventory(write_a0(tmp_path / "b", as_v5))
    assert loaded_v6.rules_versions.b3_interpreters == V6 and loaded_v5.rules_versions.b3_interpreters == V5
    assert loaded_v6.rules_versions.is_current() is False and loaded_v5.rules_versions.is_current() is False
    assert loaded_v6.inventory_id == r5["inventory_id"] and loaded_v5.inventory_id == r6["inventory_id"]            # aucune formule d'identité ne dépend de la version de B3
