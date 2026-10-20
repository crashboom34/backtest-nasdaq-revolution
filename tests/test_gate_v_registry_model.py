"""AF-V-07 Slice E3-D, tranche 0 — modèle PUR des enregistrements du registre (ADR 0025 23.10) : aucune E/S.

Chaque test s'ancre soit dans l'ADR (règle ACCEPTED de la matrice `docs/adr/0025-proposal-E3D-REGISTRY-MATRIX-PROPOSED.md`), soit dans un choix PROPOSÉ nommé comme tel.
Les valeurs attendues sont des littéraux de l'ADR ou des calculs indépendants (`hashlib`), jamais une réutilisation de la formule du code testé.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_registry_fixtures as fx
import gate_v_registry_model as model
from gate_v_registry_model import RecordType


def _chain_start():
    prev = model.genesis_prev_content_hash(fx.INSTANCE_ID)
    return fx.reservation(0, prev)


# ── Genèse, noms de slot ────────────────────────────────────────────────────────────────────────────────────────────────

def test_genesis_prev_hash_is_sha256_of_the_adr_literal():
    expected = hashlib.sha256(("gate_v_registry_genesis:" + fx.INSTANCE_ID).encode("utf-8")).hexdigest()
    assert model.genesis_prev_content_hash(fx.INSTANCE_ID) == expected


@pytest.mark.parametrize("bad", ["", "A" * 32, "a" * 31, "a" * 33, "g" * 32, 123, None, b"a" * 32])
def test_genesis_refuses_a_malformed_instance_id(bad):
    with pytest.raises(ValueError):
        model.genesis_prev_content_hash(bad)


def test_slot_file_name_is_six_digit_zero_padded():
    assert model.slot_file_name(0) == "admission_000000.json"
    assert model.slot_file_name(41) == "admission_000041.json"
    assert model.parse_slot_file_name("admission_000041.json") == 41


@pytest.mark.parametrize("name", [
    "admission_41.json", "admission_0000041.json", "admission_00004a.json", "admission_000041.JSON", "Admission_000041.json", "admission_000041.json.bak",
    "admission_000041.json ", " admission_000041.json", "admission_-00041.json", "admission_٠٠٠٠٤١.json", "admission_000041.jsonl", "", "identity.json"])
def test_parse_slot_file_name_refuses_every_other_name(name):
    assert model.parse_slot_file_name(name) is None


@pytest.mark.parametrize("bad", [-1, True, 1.0, "1", None, 1_000_000])
def test_slot_file_name_refuses_a_bad_sequence(bad):
    with pytest.raises(ValueError):
        model.slot_file_name(bad)


# ── Validation stricte d'un enregistrement ──────────────────────────────────────────────────────────────────────────────

def test_each_record_type_validates_and_reports_its_type():
    base = _chain_start()
    reservation_hash = model.compute_record_content_hash(base)
    admission = fx.admission(1, reservation_hash, base, reservation_hash)
    admission_hash = model.compute_record_content_hash(admission)
    consumption = fx.consumption(2, admission_hash, admission, admission_hash)
    rebind = fx.rebind(3, model.compute_record_content_hash(consumption), "b" * 32)
    for record, expected in ((base, RecordType.RESERVATION), (admission, RecordType.ADMISSION), (consumption, RecordType.CONSUMPTION), (rebind, RecordType.REBIND)):
        assert model.validate_registry_record(record) is expected


def test_unknown_record_type_is_refused():
    record = _chain_start()
    record["record_type"] = "RELEASE"
    with pytest.raises(ValueError):
        model.validate_registry_record(record)


@pytest.mark.parametrize("key", sorted(_chain_start()))
def test_a_missing_key_is_refused(key):
    record = _chain_start()
    del record[key]
    with pytest.raises(ValueError):
        model.validate_registry_record(record)


def test_an_unknown_extra_key_is_refused_for_every_type():
    prev = model.genesis_prev_content_hash(fx.INSTANCE_ID)
    base = _chain_start()
    reservation_hash = model.compute_record_content_hash(base)
    admission = fx.admission(1, reservation_hash, base, reservation_hash)
    for record in (base, admission, fx.rebind(1, prev, "b" * 32)):
        record["unexpected"] = "x"
        with pytest.raises(ValueError):
            model.validate_registry_record(record)


def test_a_reservation_refuses_admission_only_fields():
    record = _chain_start()
    record["reservation_content_hash"] = fx.h("x")
    with pytest.raises(ValueError):
        model.validate_registry_record(record)


def test_rebind_has_neither_campaign_id_nor_window():
    record = fx.rebind(1, fx.h("p"), "b" * 32)
    for key in ("campaign_id", "window_start_utc", "window_end_utc"):
        broken = {**record, key: "x"}
        with pytest.raises(ValueError):
            model.validate_registry_record(broken)


@pytest.mark.parametrize("field,value", [
    ("admission_semantics_version", "gate_v_registry_record_v2"), ("admission_semantics_version", 1),
    ("registry_id", ""), ("registry_id", "has space"), ("registry_id", "x" * 129), ("registry_id", 5),
    ("instance_id", "A" * 32), ("instance_id", "a" * 31), ("instance_id", 5),
    ("seq", -1), ("seq", True), ("seq", 1.0), ("seq", "0"),
    ("prev_content_hash", "A" * 64), ("prev_content_hash", "a" * 63), ("prev_content_hash", None),
    ("created_at", "2031-02-01T00:00:00Z"), ("created_at", "2031-02-01T02:00:00.000000+02:00"), ("created_at", "2031-02-01T00:00:00.000000"), ("created_at", 5),
    ("campaign_id", "gate_v_v2_" + "1" * 63), ("campaign_id", "other_" + "1" * 64), ("campaign_id", ""), ("campaign_id", None),
    ("window_start_utc", "2031-01-01T00:00:00Z"), ("window_start_utc", "2031-01-01"), ("window_end_utc", "2031-01-10T00:00:00.000000+00:00"),
    ("commitment_id", ""), ("commitment_id", "x" * 257), ("commitment_id", "bad\nline"), ("commitment_id", 7),
    ("commitment_content_hash", "z" * 64), ("code_identity_hash", "a" * 10), ("static_sources_digest", "A" * 64),
    ("campaign_dir_locator", ""), ("campaign_dir_locator", 3), ("campaign_dir_locator", "x" * 4097),
])
def test_a_malformed_field_is_refused(field, value):
    record = _chain_start()
    record[field] = value
    with pytest.raises(ValueError):
        model.validate_registry_record(record)


@pytest.mark.parametrize("bad", [-1, True, 1.0, "1", None, 10 ** 6])
def test_reservation_seq_must_still_be_a_valid_sequence_number(bad):
    # `reservation_seq` est informatif (23.10) mais reste un entier valide : il est couvert par le hash du contenu.
    with pytest.raises(ValueError):
        model.validate_registry_record(_admission_with(reservation_seq=bad))


@pytest.mark.parametrize("bad", [-1, True, 1.0, "1", None, 10 ** 6])
def test_restored_head_seq_must_be_a_valid_sequence_number(bad):
    with pytest.raises(ValueError):
        model.validate_registry_record(fx.rebind(1, fx.h("p"), "b" * 32, restored_head_seq=bad))


def test_window_must_be_strictly_positive_length():
    equal = _chain_start()
    equal["window_end_utc"] = equal["window_start_utc"]
    with pytest.raises(ValueError):
        model.validate_registry_record(equal)
    reversed_window = _chain_start()
    reversed_window["window_start_utc"], reversed_window["window_end_utc"] = reversed_window["window_end_utc"], reversed_window["window_start_utc"]
    with pytest.raises(ValueError):
        model.validate_registry_record(reversed_window)


def test_a_subclass_of_dict_or_str_is_refused():
    class Dict(dict):
        pass

    class Text(str):
        pass

    with pytest.raises(ValueError):
        model.validate_registry_record(Dict(_chain_start()))
    record = _chain_start()
    record["campaign_id"] = Text(record["campaign_id"])
    with pytest.raises(ValueError):
        model.validate_registry_record(record)


def test_a_float_anywhere_is_refused():
    base = _chain_start()
    reservation_hash = model.compute_record_content_hash(base)
    admission = fx.admission(1, reservation_hash, base, reservation_hash, attestation_observation={"highest_slot_observed": 3.0})
    with pytest.raises(ValueError):
        model.validate_registry_record(admission)


def _admission_with(**overrides):
    base = _chain_start()
    reservation_hash = model.compute_record_content_hash(base)
    return fx.admission(1, reservation_hash, base, reservation_hash, **overrides)


@pytest.mark.parametrize("field", ["attestation_hash", "authorization_hash"])
@pytest.mark.parametrize("bad", ["", "A" * 64, "a" * 63, "a" * 65, "g" * 64, {"kind": "x"}, 5, None, b"a" * 64])
def test_attestation_and_authorization_are_sha256_hashes_as_the_adr_says(field, bad):
    # ACCEPTED (23.10) : l'ADMISSION porte les « hashs d'attestation et d'autorisation » ; leur contenu (forme F5) n'est pas interprété ici.
    with pytest.raises(ValueError):
        model.validate_registry_record(_admission_with(**{field: bad}))


@pytest.mark.parametrize("bad", [{}, [], "text", 5, None, {"nested": float("nan")}, {"k": (1, 2)}])
def test_the_attestation_observation_must_be_a_non_empty_normative_object(bad):
    # PROPOSÉ (P9, orientation F1 §0.3, non normative) : conteneur opaque, jamais interprété.
    with pytest.raises(ValueError):
        model.validate_registry_record(_admission_with(attestation_observation=bad))


def test_the_attestation_observation_depth_is_bounded():
    deep = current = {}
    for _ in range(model.MAX_OPAQUE_DEPTH + 1):
        current["k"] = {}
        current = current["k"]
    current["leaf"] = 1
    with pytest.raises(ValueError):
        model.validate_registry_record(_admission_with(attestation_observation=deep))


def _nested(levels):
    value = {"leaf": 1}
    for _ in range(levels - 1):
        value = {"k": value}
    return value                                   # `levels` conteneurs imbriqués


def test_the_depth_limit_is_exact_at_the_boundary():
    model.validate_registry_record(_admission_with(attestation_observation=_nested(model.MAX_OPAQUE_DEPTH)))
    with pytest.raises(ValueError):
        model.validate_registry_record(_admission_with(attestation_observation=_nested(model.MAX_OPAQUE_DEPTH + 1)))


@pytest.mark.parametrize("levels", [600, 5000])
def test_a_hostile_nesting_is_a_value_error_never_a_recursion_error(levels):
    deep = current = {}
    for _ in range(levels):
        current["k"] = {}
        current = current["k"]
    current["leaf"] = 1
    with pytest.raises(ValueError):
        model.validate_registry_record(_admission_with(attestation_observation=deep))


def test_the_attestation_observation_size_is_bounded():
    # Un conteneur opaque trop gros produirait un slot que le lecteur strict refuserait : il est refusé AVANT toute publication.
    with pytest.raises(ValueError):
        model.validate_registry_record(_admission_with(attestation_observation={"blob": "A" * (model.MAX_OPAQUE_BYTES + 1)}))
    model.validate_registry_record(_admission_with(attestation_observation={"blob": "A" * 1000}))


def test_the_whole_record_size_cap_is_enforced(monkeypatch):
    # Inatteignable avec les bornes actuelles (l'opaque est borné) mais exercé : un plafond abaissé refuse l'enregistrement complet.
    monkeypatch.setattr(model, "MAX_RECORD_BYTES", 300)
    with pytest.raises(ValueError, match="au plus 300"):
        model.validate_registry_record(_chain_start())


def test_a_complete_record_always_fits_the_reader_size_cap_by_construction():
    assert model.MAX_RECORD_BYTES >= 4 * model.MAX_OPAQUE_BYTES > 0
    biggest = _admission_with(attestation_observation={"blob": "A" * (model.MAX_OPAQUE_BYTES - 64)})
    model.validate_registry_record(biggest)
    assert len(model.serialize_for_slot(biggest)) <= model.MAX_RECORD_BYTES


def test_rebind_binding_hashes_must_differ_and_instance_changes():
    # PROPOSÉ (P16) : un REBIND qui ne change aucune liaison n'a pas de sens.
    same = fx.rebind(1, fx.h("p"), "b" * 32, new_binding_hash=fx.h("old-binding"))
    with pytest.raises(ValueError):
        model.validate_registry_record(same)


def test_validation_does_not_mutate_the_record():
    record = _chain_start()
    before = copy.deepcopy(record)
    model.validate_registry_record(record)
    assert record == before


# ── Hash du contenu ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_record_content_hash_is_sha256_of_compact_sorted_json_of_the_whole_record():
    record = _chain_start()
    text = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert model.compute_record_content_hash(record) == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_record_content_hash_matches_a_frozen_golden_vector_including_non_ascii():
    # Chaîne JSON compacte écrite À LA MAIN (clés triées, UTF-8 non échappé) et son SHA-256 calculé séparément avec hashlib : un vecteur figé, pas la recette du code.
    record = {
        "admission_semantics_version": "gate_v_registry_record_v1", "registry_id": "golden-registry", "instance_id": "a" * 32, "seq": 0, "prev_content_hash": "0" * 64,
        "record_type": "RESERVATION", "created_at": "2031-02-01T00:00:00.000000Z", "campaign_id": "gate_v_v2_" + "1" * 64,
        "window_start_utc": "2031-01-01T00:00:00.000000Z", "window_end_utc": "2031-01-10T00:00:00.000000Z", "commitment_id": "commitment-1",
        "commitment_content_hash": "2" * 64, "code_identity_hash": "3" * 64, "campaign_dir_locator": "campagnes/été/日本", "static_sources_digest": "4" * 64}
    assert model.compute_record_content_hash(record) == "7e093eb043524ff045e6e882d5483a13d3e5b49139382948930d7e07a26787f8"
    assert model.compute_reservation_semantic_id(record) != model.compute_record_content_hash(record)


def test_record_content_hash_covers_seq_prev_and_created_at():
    base = _chain_start()
    reference = model.compute_record_content_hash(base)
    for field, value in (("seq", 1), ("prev_content_hash", fx.h("other")), ("created_at", "2031-02-02T00:00:00.000000Z")):
        assert model.compute_record_content_hash({**base, field: value}) != reference


def test_record_content_hash_is_independent_of_key_order():
    record = _chain_start()
    reordered = dict(reversed(list(record.items())))
    assert model.compute_record_content_hash(reordered) == model.compute_record_content_hash(record)


def test_record_content_hash_refuses_an_invalid_record():
    record = _chain_start()
    del record["registry_id"]
    with pytest.raises(ValueError):
        model.compute_record_content_hash(record)


def test_admission_id_excludes_the_non_semantic_fields():
    base = _chain_start()
    reservation_hash = model.compute_record_content_hash(base)
    first = fx.admission(1, reservation_hash, base, reservation_hash)
    other = fx.admission(7, fx.h("another-prev"), base, reservation_hash, campaign_dir_locator="elsewhere", reservation_seq=99,
                         created_at="2032-01-01T00:00:00.000000Z")
    assert model.compute_admission_id(first) == model.compute_admission_id(other)
    assert model.compute_record_content_hash(first) != model.compute_record_content_hash(other)


@pytest.mark.parametrize("field,value", [
    ("attachment_id", "attachment-2"), ("overlap_projection_hash", fx.h("p2")), ("static_sources_digest", fx.h("s2")),
    ("attestation_hash", fx.h("att2")), ("authorization_hash", fx.h("auth2")), ("attestation_observation", {"highest_slot_observed": 4}), ("window_end_utc", fx.instant(11)),
    ("reservation_content_hash", fx.h("r2")), ("commitment_content_hash", fx.h("c2")), ("time_proof_content_hash", fx.h("t2"))])
def test_admission_id_changes_with_every_semantic_field(field, value):
    base = _chain_start()
    reservation_hash = model.compute_record_content_hash(base)
    first = fx.admission(1, reservation_hash, base, reservation_hash)
    changed = {**first, field: value}
    assert model.compute_admission_id(changed) != model.compute_admission_id(first)


def test_admission_id_refuses_a_non_admission():
    with pytest.raises(ValueError):
        model.compute_admission_id(_chain_start())


# PROPOSÉ (P19) : l'ADR parle d'un « contenu sémantique identique » pour la réutilisation d'une RESERVATION sans le définir ; on adopte la même règle que pour `admission_id`
# (sans `seq`, `prev_content_hash`, `created_at` ni `campaign_dir_locator`).

def test_reservation_semantic_id_excludes_the_non_semantic_fields():
    first = _chain_start()
    other = fx.reservation(9, fx.h("another-prev"), fx.CAMPAIGN_A, campaign_dir_locator="elsewhere", created_at="2032-01-01T00:00:00.000000Z")
    assert model.compute_reservation_semantic_id(first) == model.compute_reservation_semantic_id(other)
    assert model.compute_record_content_hash(first) != model.compute_record_content_hash(other)


@pytest.mark.parametrize("field,value", [
    ("window_end_utc", fx.instant(11)), ("window_start_utc", fx.instant(2)), ("static_sources_digest", fx.h("s2")), ("commitment_content_hash", fx.h("c2")),
    ("commitment_id", "commitment-other"), ("code_identity_hash", fx.h("code-2")), ("campaign_id", fx.CAMPAIGN_B)])
def test_reservation_semantic_id_changes_with_every_semantic_field(field, value):
    first = _chain_start()
    assert model.compute_reservation_semantic_id({**first, field: value}) != model.compute_reservation_semantic_id(first)


def test_reservation_semantic_id_refuses_a_non_reservation():
    base = _chain_start()
    reservation_hash = model.compute_record_content_hash(base)
    with pytest.raises(ValueError):
        model.compute_reservation_semantic_id(fx.admission(1, reservation_hash, base, reservation_hash))


# ── Fenêtres ────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b,expected", [
    ((1, 10), (5, 15), True),     # partiel
    ((1, 10), (1, 10), True),     # identique
    ((1, 10), (3, 4), True),      # inclus
    ((3, 4), (1, 10), True),      # inclus (sens inverse)
    ((1, 10), (10, 20), False),   # adjacent : fenêtres semi-ouvertes [début, fin)
    ((10, 20), (1, 10), False),
    ((1, 5), (6, 9), False),      # disjoint
])
def test_windows_overlap_is_half_open(a, b, expected):
    assert model.windows_overlap(fx.instant(a[0]), fx.instant(a[1]), fx.instant(b[0]), fx.instant(b[1])) is expected


def test_windows_overlap_compares_instants_not_text_offsets():
    # Les instants sont déjà normalisés en UTC : la comparaison est chronologique, même au-delà d'un changement de jour.
    assert model.windows_overlap("2031-01-01T23:59:59.999999Z", "2031-01-02T00:00:00.000001Z", "2031-01-02T00:00:00.000000Z", "2031-01-03T00:00:00.000000Z")
    assert not model.windows_overlap("2031-01-01T00:00:00.000000Z", "2031-01-02T00:00:00.000000Z", "2031-01-02T00:00:00.000000Z", "2031-01-03T00:00:00.000000Z")


def test_windows_overlap_refuses_non_normalised_instants():
    with pytest.raises(ValueError):
        model.windows_overlap("2031-01-01T00:00:00Z", fx.instant(2), fx.instant(1), fx.instant(2))
