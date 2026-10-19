"""AF-V-07 Slice E3-C — intégration SYNTHÉTIQUE de la primitive de publication par lien avec ses futurs consommateurs.

Aucun consommateur n'est implémenté ici : ni le registre (E3-D), ni la publication des déclarations et attestations (B6 : le chargeur est en lecture
seule), ni l'événement canonique (E3-G). Les tests jouent le rôle de l'appelant futur pour prouver que les octets, les noms et les états produits par
`atomic_json_store.publish_*_by_link` sont ceux que les modules DÉJÀ publiés (B2 scanner, B6 chargeur) lisent, tolèrent ou refusent.

Fixtures synthétiques dans `tmp_path` uniquement : aucune donnée de marché, aucun `FINAL_HOLDOUT`, aucun accès réseau. Contrat : ADR 0025 23.10, 23.13,
23.22, 23.29.1 à 23.29.4, 23.31.
"""

from __future__ import annotations

import errno
import os
import re
import stat
from pathlib import Path

import pytest

import atomic_json_store as store
import gate_v_exposure_declarations as b6
from gate_v_final_holdout_protocol import (
    OverlapVerdict,
    SourceKind,
    SourceStatus,
    build_exposure_declaration,
    build_exposure_finding,
    compute_declaration_id,
)
from tests.gate_v_exposure_support import CREATED_AT, CURRENT, assemble, interpret

SIMULATED = store.DurabilityProfile.SIMULATED_DURABLE
EXPOSURE = store.TempNaming.EXPOSURE
REGISTRY = store.TempNaming.REGISTRY


def names(directory) -> list:
    return sorted(entry.name for entry in directory.iterdir())


def declared(seq: int, position: int):
    return build_exposure_finding(source_id=f"declared:{seq:04d}:{position:04d}", source_kind=SourceKind.DECLARED_UNRECORDED_WORK,
                                  status=SourceStatus.RESOLVED, overlap=OverlapVerdict.OVERLAPS, window_start_utc="2026-02-01T00:00:00+00:00",
                                  window_end_utc="2026-02-10T00:00:00+00:00")


def declaration(seq: int, inventory_id: str, previous=None, declarant: str = "Mira"):
    return build_exposure_declaration(
        declaration_seq=seq, declarant=declarant, inventory_id=inventory_id,
        prev_declaration_id=None if previous is None else compute_declaration_id(previous),
        declared_exposures=(declared(seq, 1),), declared_t_sel_utc=None, declared_trial_counts=None)


def envelope(item, previous_envelope=None) -> dict:
    return b6.build_declaration_envelope(
        item, campaign_id=CURRENT, prev_declaration_content_hash=None if previous_envelope is None else previous_envelope["declaration_content_hash"],
        carried_from=None, created_at=f"2026-10-21T09:{item.declaration_seq:02d}:00+00:00")


@pytest.fixture
def campaign(tmp_path):
    """Répertoire de campagne synthétique avec un A0 réel (publié par B5, code historique) : retourne `(répertoire, inventory_id)`."""
    from gate_v_exposure_store import publish_exposure_inventory
    directory = tmp_path / "campaign_dir"
    directory.mkdir()
    assembly = assemble(interpret(tmp_path / "src"))
    publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    (directory / "exposure" / assembly.inventory_id).mkdir()                       # le parent métier est créé par l'APPELANT, jamais par la primitive
    return directory, assembly.inventory_id


def load(directory, inventory_id):
    return b6.load_declaration_lineage(directory, current_inventory_id=inventory_id, campaign_id=CURRENT, pinned_a0_hashes=frozenset(),
                                       admitted_attestation=None)


def publish_declaration(directory, inventory_id, item, previous_envelope=None):
    record = envelope(item, previous_envelope)
    result = store.publish_json_by_link(b6.declaration_path(directory, inventory_id, item.declaration_seq), record, durability=SIMULATED, naming=EXPOSURE,
                                        kind="déclaration")
    return record, result


# ── B6 : déclarations et attestations (lecture seule) lues sur les octets publiés par E3-C ──────────────────────────────────

def test_the_normative_json_of_the_primitive_is_the_exact_byte_form_b6_requires(campaign):
    directory, inventory_id = campaign
    record = envelope(declaration(1, inventory_id))
    assert store.serialize_normative_json(record) == b6.serialize_declaration_envelope(record)


def test_b6_loads_a_declaration_published_by_link_and_binds_the_hash_to_the_file_bytes(campaign):
    directory, inventory_id = campaign
    record, result = publish_declaration(directory, inventory_id, declaration(1, inventory_id))
    assert result.state is store.PublicationState.PUBLISHED_DURABLE and result.temp_disposition is store.TempDisposition.REMOVED
    lineage = load(directory, inventory_id)
    assert lineage.state is b6.LineageState.CURRENT_IS_TERMINAL and len(lineage.declaration_set.declarations) == 1
    assert lineage.chains[-1].tip.content_hash == record["declaration_content_hash"]
    assert b6.declaration_path(directory, inventory_id, 1).read_bytes() == b6.serialize_declaration_envelope(record)
    assert names(directory / "exposure" / inventory_id) == ["declaration_0001.json"]


def test_a_chain_of_two_declarations_published_in_order_is_loaded_as_one_chain(campaign):
    directory, inventory_id = campaign
    first = declaration(1, inventory_id)
    first_envelope, _ = publish_declaration(directory, inventory_id, first)
    publish_declaration(directory, inventory_id, declaration(2, inventory_id, first), first_envelope)
    lineage = load(directory, inventory_id)
    assert [item.declaration_seq for item in lineage.declaration_set.declarations] == [1, 2]


def test_a_publication_orphan_left_by_an_unconfirmed_attempt_is_tolerated_and_recorded_by_b6(campaign, monkeypatch):
    directory, inventory_id = campaign
    calls = {"count": 0}

    def failing_second_barrier(path):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError(errno.EIO, "fsync du répertoire en échec")

    monkeypatch.setattr(store, "_simulated_directory_barrier", failing_second_barrier)
    with pytest.raises(store.PublishedUnconfirmedError) as unconfirmed:
        publish_declaration(directory, inventory_id, declaration(1, inventory_id))
    monkeypatch.undo()
    orphan = unconfirmed.value.publication.temp_path
    lineage = load(directory, inventory_id)                                         # B6 lit le slot publié ET consigne l'orphelin de E3-C, sans erreur
    assert lineage.state is b6.LineageState.CURRENT_IS_TERMINAL
    assert [(item.kind, item.relative_path) for item in lineage.ignored] == [(b6.IgnoredKind.PUBLICATION_ORPHAN,
                                                                               f"exposure/{inventory_id}/{orphan.name}")]
    again = store.confirm_published_slot(b6.declaration_path(directory, inventory_id, 1), expected_sha256=unconfirmed.value.publication.identity.sha256,
                                         durability=SIMULATED)
    assert again.state is store.PublicationState.PUBLISHED_DURABLE


def test_a_second_publication_of_the_same_declaration_slot_is_refused_and_the_chain_is_unchanged(campaign):
    directory, inventory_id = campaign
    record, _ = publish_declaration(directory, inventory_id, declaration(1, inventory_id))
    before = load(directory, inventory_id).chains[-1].tip.content_hash
    with pytest.raises(store.SlotOccupiedError):
        publish_declaration(directory, inventory_id, declaration(1, inventory_id, declarant="Autre"))
    assert load(directory, inventory_id).chains[-1].tip.content_hash == before == record["declaration_content_hash"]
    assert names(directory / "exposure" / inventory_id) == ["declaration_0001.json"]


def test_an_attestation_slot_published_by_link_is_read_back_with_the_file_hash_as_identity(campaign):
    directory, inventory_id = campaign
    publish_declaration(directory, inventory_id, declaration(1, inventory_id))
    attestation = {"version": "synthetic", "inventory_id": inventory_id, "note": "attestation synthétique"}
    result = store.publish_json_by_link(b6.attestation_path(directory, inventory_id, 1), attestation, durability=SIMULATED, naming=EXPOSURE,
                                        kind="attestation")
    read = b6.read_attestation_slot(directory, inventory_id, 1)
    assert read.value == attestation and read.file_sha256 == result.identity.sha256     # la F5 provisoire (hash de FICHIER) = l'identité de la primitive


def test_bytes_that_are_not_the_normative_form_are_refused_by_b6_even_when_published_by_link(campaign):
    directory, inventory_id = campaign
    publish_declaration(directory, inventory_id, declaration(1, inventory_id))
    store.publish_bytes_by_link(b6.attestation_path(directory, inventory_id, 1), b'{"a": 1}', durability=SIMULATED, naming=EXPOSURE, kind="attestation")
    with pytest.raises(Exception) as refusal:
        b6.read_attestation_slot(directory, inventory_id, 1)
    assert "NOT_FIXED_POINT" in repr(refusal.value)


def test_the_primitive_never_creates_the_business_parent_of_a_declaration(tmp_path):
    missing = tmp_path / "exposure" / ("a" * 64) / "declaration_0001.json"
    with pytest.raises(store.PublicationNotStartedError) as refusal:
        store.publish_bytes_by_link(missing, b"{}", durability=SIMULATED, naming=EXPOSURE, kind="déclaration")
    assert refusal.value.stage is store.PublicationStage.PREFLIGHT and not (tmp_path / "exposure").exists()


def test_b6_publication_is_not_activated_by_e3_c():
    """E3-C fournit la primitive ; l'activation de la publication des déclarations et attestations par B6 est une décision et une tranche distinctes."""
    assert [name for name in dir(b6) if re.match(r"(publish|write|save)_", name)] == []


# ── Slots IRRÉPARABLES : publiable par la primitive, refusé à jamais par le lecteur ─────────────────────────────────────────

def deep_record(depth: int) -> dict:
    record: dict = {"leaf": 1}
    for _ in range(depth):
        record = {"n": record}
    return record


def prove_attestation_rereadable(raw: bytes) -> None:
    """PRÉCONDITION d'un futur écrivain d'attestations (B6/E3-E) : ce que `read_attestation_slot` exigerait, vérifié sur les octets AVANT publication."""
    from gate_v_exposure_store import ExposureStoreError, StoreFailure, parse_strict_record
    value = parse_strict_record(raw)
    if type(value) is not dict:
        raise ExposureStoreError(StoreFailure.SCHEMA, "une attestation doit être un objet JSON")
    if store.serialize_normative_json(value) != raw:
        raise ExposureStoreError(StoreFailure.NOT_FIXED_POINT, "les octets ne sont pas la sérialisation normative")


def test_a_too_deep_attestation_is_publishable_by_the_primitive_and_then_refuses_the_whole_lineage_forever(campaign):
    from gate_v_exposure_store import ExposureStoreError, StoreFailure
    directory, inventory_id = campaign
    publish_declaration(directory, inventory_id, declaration(1, inventory_id))
    path = b6.attestation_path(directory, inventory_id, 1)
    result = store.publish_json_by_link(path, deep_record(40), durability=SIMULATED, naming=EXPOSURE, kind="attestation")   # la primitive est GÉNÉRIQUE : aucune borne
    assert result.state is store.PublicationState.PUBLISHED_DURABLE
    with pytest.raises(ExposureStoreError) as refusal:
        b6.read_attestation_slot(directory, inventory_id, 1)
    assert refusal.value.failure is StoreFailure.NOT_JSON
    with pytest.raises(b6.LineageError):
        load(directory, inventory_id)                                                    # toute la lignée est refusée
    with pytest.raises(store.SlotOccupiedError):                                         # et le slot ne se répare pas : binding, jamais remplacé
        store.publish_json_by_link(path, {"ok": 1}, durability=SIMULATED, naming=EXPOSURE, kind="attestation")


def test_an_oversized_attestation_is_publishable_by_the_primitive_and_refused_by_the_reader(campaign):
    from gate_v_exposure_store import MAX_A0_BYTES, ExposureStoreError, StoreFailure
    directory, inventory_id = campaign
    publish_declaration(directory, inventory_id, declaration(1, inventory_id))
    huge = {"payload": "x" * (MAX_A0_BYTES + 1)}
    store.publish_json_by_link(b6.attestation_path(directory, inventory_id, 1), huge, durability=SIMULATED, naming=EXPOSURE, kind="attestation")
    with pytest.raises(ExposureStoreError) as refusal:
        b6.read_attestation_slot(directory, inventory_id, 1)
    assert refusal.value.failure is StoreFailure.TOO_LARGE


def test_a_declaration_with_a_bad_hash_is_publishable_by_the_primitive_and_refused_by_the_lineage_loader(campaign):
    directory, inventory_id = campaign
    record = envelope(declaration(1, inventory_id))
    record["declaration_content_hash"] = "0" * 64                                         # schéma valide, hash faux
    store.publish_json_by_link(b6.declaration_path(directory, inventory_id, 1), record, durability=SIMULATED, naming=EXPOSURE, kind="déclaration")
    with pytest.raises(b6.LineageError):
        load(directory, inventory_id)


@pytest.mark.parametrize("what", ["too_deep", "too_large", "not_an_object", "not_normative"])
def test_the_pre_publication_proof_in_precheck_refuses_an_unreadable_attestation_before_anything_is_created(campaign, what):
    """Protection mise en œuvre PAR L'APPELANT, pas par la primitive : `precheck` (après la barrière, avant tout fichier) rejoue la relecture stricte."""
    from gate_v_exposure_store import MAX_A0_BYTES, ExposureStoreError
    directory, inventory_id = campaign
    publish_declaration(directory, inventory_id, declaration(1, inventory_id))
    path = b6.attestation_path(directory, inventory_id, 1)
    raw = {"too_deep": store.serialize_normative_json(deep_record(40)),
           "too_large": store.serialize_normative_json({"payload": "x" * (MAX_A0_BYTES + 1)}),
           "not_an_object": b"[1, 2]\n",
           "not_normative": b'{"a": 1}'}[what]
    before = names(path.parent)
    with pytest.raises(ExposureStoreError):
        store.publish_bytes_by_link(path, raw, durability=SIMULATED, naming=EXPOSURE, kind="attestation", precheck=lambda: prove_attestation_rereadable(raw))
    assert names(path.parent) == before and not path.exists()                           # rien créé : le slot dense reste LIBRE
    good = store.serialize_normative_json({"version": "synthetic", "inventory_id": inventory_id})
    store.publish_bytes_by_link(path, good, durability=SIMULATED, naming=EXPOSURE, kind="attestation", precheck=lambda: prove_attestation_rereadable(good))
    assert b6.read_attestation_slot(directory, inventory_id, 1).value["version"] == "synthetic"


def test_the_pre_publication_proof_of_a_declaration_is_the_readers_own_parser(campaign):
    """Pour une déclaration, la preuve est `parse_declaration_file` : l'écrivain relit ses propres octets avec le code du lecteur AVANT de consommer le slot."""
    from gate_v_exposure_store import ExposureStoreError
    directory, inventory_id = campaign
    bad = envelope(declaration(1, inventory_id))
    bad["declaration_content_hash"] = "0" * 64
    bad_raw = store.serialize_normative_json(bad)
    path = b6.declaration_path(directory, inventory_id, 1)

    def prove(raw):
        return lambda: b6.parse_declaration_file(raw, inventory_id=inventory_id, seq=1, campaign_id=CURRENT)

    with pytest.raises(ExposureStoreError):
        store.publish_bytes_by_link(path, bad_raw, durability=SIMULATED, naming=EXPOSURE, kind="déclaration", precheck=prove(bad_raw))
    assert not path.exists()
    good_raw = store.serialize_normative_json(envelope(declaration(1, inventory_id)))
    store.publish_bytes_by_link(path, good_raw, durability=SIMULATED, naming=EXPOSURE, kind="déclaration", precheck=prove(good_raw))
    assert load(directory, inventory_id).state is b6.LineageState.CURRENT_IS_TERMINAL


def prove_lineage_with_candidate(directory, inventory_id: str, seq: int, raw: bytes):
    """Preuve de NIVEAU LIGNÉE (motif, non implémenté par E3-C ni B6) : charger la lignée sur une COPIE de la campagne contenant le candidat. Coûteux (copie
    du dossier, budget de B6 inclus), valable seulement avec UN SEUL écrivain par campagne ; une API de validation de candidat dans B6 serait une NOUVELLE
    décision (PROPOSÉE)."""
    import shutil
    import tempfile
    from gate_v_exposure_store import ExposureStoreError, StoreFailure
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "campaign_dir"
        shutil.copytree(directory, copy, symlinks=True)                                   # ne déréférence JAMAIS un lien (le lecteur les refuse)
        for entry in [copy, *copy.rglob("*")]:
            info = os.lstat(entry)
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ExposureStoreError(StoreFailure.LINK_OR_REPARSE_POINT, f"{entry.name} est un lien : la copie le masquerait")
        candidate = b6.declaration_path(copy, inventory_id, seq)
        candidate.write_bytes(raw)
        load(copy, inventory_id)                                                         # lève `LineageError` si la lignée serait refusée


def test_a_per_file_proof_does_not_cover_chain_errors_but_a_lineage_level_proof_does(campaign):
    """Constat de la revue D-H1 : `parse_declaration_file` prouve UN fichier ; le chargeur refuse aussi la lignée entière (chaîne, état). Une déclaration 2 dont
    `prev_declaration_id` désigne une autre déclaration passe la preuve par fichier, est publiée, puis refuse la lignée À JAMAIS (slot occupé, donc irréparable)."""
    directory, inventory_id = campaign
    first = declaration(1, inventory_id)
    first_envelope, _ = publish_declaration(directory, inventory_id, first)
    impostor = declaration(1, inventory_id, declarant="Autre")                          # un AUTRE prédécesseur que le sommet réel
    bad = declaration(2, inventory_id, impostor)
    bad_raw = store.serialize_normative_json(envelope(bad, first_envelope))
    b6.parse_declaration_file(bad_raw, inventory_id=inventory_id, seq=2, campaign_id=CURRENT)       # la preuve PAR FICHIER passe
    path = b6.declaration_path(directory, inventory_id, 2)
    # La preuve de niveau lignée, elle, refuse AVANT toute création :
    with pytest.raises(b6.LineageError) as proof_refusal:
        store.publish_bytes_by_link(path, bad_raw, durability=SIMULATED, naming=EXPOSURE, kind="déclaration",
                                    precheck=lambda: prove_lineage_with_candidate(directory, inventory_id, 2, bad_raw))
    assert proof_refusal.value.failure is b6.LineageFailure.ID_CHAIN_BROKEN and not path.exists()
    # Sans elle, le slot serait consommé et la lignée refusée pour toujours :
    store.publish_bytes_by_link(path, bad_raw, durability=SIMULATED, naming=EXPOSURE, kind="déclaration")
    with pytest.raises(b6.LineageError) as late_refusal:
        load(directory, inventory_id)
    assert late_refusal.value.failure is b6.LineageFailure.ID_CHAIN_BROKEN
    with pytest.raises(store.SlotOccupiedError):
        store.publish_bytes_by_link(path, b"{}", durability=SIMULATED, naming=EXPOSURE, kind="déclaration")


def test_the_lineage_level_proof_accepts_a_correct_candidate(campaign):
    directory, inventory_id = campaign
    first = declaration(1, inventory_id)
    first_envelope, _ = publish_declaration(directory, inventory_id, first)
    good_raw = store.serialize_normative_json(envelope(declaration(2, inventory_id, first), first_envelope))
    path = b6.declaration_path(directory, inventory_id, 2)
    store.publish_bytes_by_link(path, good_raw, durability=SIMULATED, naming=EXPOSURE, kind="déclaration",
                                precheck=lambda: prove_lineage_with_candidate(directory, inventory_id, 2, good_raw))
    assert [item.declaration_seq for item in load(directory, inventory_id).declaration_set.declarations] == [1, 2]


# ── E3-D (registre) : créneaux d'admission synthétiques, noms de temporaires du registre ─────────────────────────────────────

def admissions(directory) -> list:
    """Listeur synthétique d'un futur registre : seuls `admission_<4 chiffres>.json` comptent ; tout temporaire est ignoré."""
    return sorted(name for name in names(directory) if re.fullmatch(r"admission_[0-9]{4}\.json", name))


def test_registry_slots_use_the_registry_temporary_names_and_leave_only_complete_admissions(tmp_path):
    result = store.publish_json_by_link(tmp_path / "admission_0001.json", {"campaign_id": CURRENT, "seq": 1}, durability=SIMULATED, naming=REGISTRY,
                                        kind="admission")
    assert store.is_publication_temp_name(result.temp_path.name) is REGISTRY and names(tmp_path) == ["admission_0001.json"]
    assert admissions(tmp_path) == ["admission_0001.json"]


def test_a_registry_orphan_is_never_listed_as_an_admission_and_never_blocks_the_slot(tmp_path):
    orphan = tmp_path / ".registry.tmp.12345678-1234-4234-8234-123456789abc"
    orphan.write_bytes(b"{")                                                                        # crash antérieur : temporaire partiel
    assert admissions(tmp_path) == []
    store.publish_json_by_link(tmp_path / "admission_0001.json", {"seq": 1}, durability=SIMULATED, naming=REGISTRY, kind="admission")
    assert admissions(tmp_path) == ["admission_0001.json"] and orphan.read_bytes() == b"{"


def test_the_primitive_never_picks_another_slot_by_itself_after_an_occupied_refusal(tmp_path):
    """La primitive ne choisit JAMAIS un autre slot ni ne rejoue. ATTENTION : ce test est SYNTHÉTIQUE et n'est PAS un modèle pour E3-D : après `FileExistsError`,
    23.10 (étape 5) impose de REVENIR À L'ÉTAPE 1 et de rejouer TOUTES les vérifications (23.27.4), pas de publier directement dans le slot suivant."""
    store.publish_json_by_link(tmp_path / "admission_0001.json", {"who": "first"}, durability=SIMULATED, naming=REGISTRY, kind="admission")
    with pytest.raises(store.SlotOccupiedError):
        store.publish_json_by_link(tmp_path / "admission_0001.json", {"who": "second"}, durability=SIMULATED, naming=REGISTRY, kind="admission")
    assert admissions(tmp_path) == ["admission_0001.json"]
    store.publish_json_by_link(tmp_path / "admission_0002.json", {"who": "second"}, durability=SIMULATED, naming=REGISTRY, kind="admission")
    assert admissions(tmp_path) == ["admission_0001.json", "admission_0002.json"]


def test_the_precheck_hook_lets_a_registry_replay_its_scientific_preconditions_before_any_file_exists(tmp_path):
    class PreconditionFailed(Exception):
        pass

    def precheck():
        raise PreconditionFailed("réservation périmée")

    with pytest.raises(PreconditionFailed):
        store.publish_json_by_link(tmp_path / "admission_0001.json", {"seq": 1}, durability=SIMULATED, naming=REGISTRY, kind="admission", precheck=precheck)
    assert names(tmp_path) == []


# ── E3-G (événement canonique) : nommage du temporaire NON fixé par l'ADR ──────────────────────────────────────────────────

def test_the_canonical_event_cannot_use_an_unregistered_temporary_naming(tmp_path):
    """23.13 fixe le slot de l'événement mais pas la forme de son temporaire. Les tables fermées des scanners (B2/B3) n'en tolèrent que deux : un troisième
    nom exige une décision (E3-G) ET une extension coordonnée des tables fermées ; la primitive refuse donc tout autre nommage."""
    with pytest.raises(TypeError):
        store.publish_json_by_link(tmp_path / "event_0001.json", {"kind": "synthetic"}, durability=SIMULATED, naming="EVENT", kind="événement")
    assert names(tmp_path) == []


def test_the_b3_tables_tolerate_a_publication_orphan_only_under_exposure_and_never_for_the_registry_naming():
    """DÉPENDANCE BLOQUANTE pour E3-G (revue B-M4) : la table fermée de B3 ne tolère un orphelin de publication (`.exposure.tmp.<32 hex>`) que sous
    `exposure/` ; AUCUNE règle ne tolère `.registry.tmp.<uuid>` et le répertoire d'événements (`holdout_access/`) n'a aucune règle d'orphelin : un
    temporaire laissé par un crash y serait classé `UNKNOWN_TEMP_FILE` (source inconnue, inventaire incomplet). Publier l'événement exige donc une
    décision E3-G (nommage) ET une extension coordonnée des tables fermées (nouvelle version de B3, nouveau `rules_digest`) : PROPOSÉ, non décidé."""
    from gate_v_exposure_interpreters import _TABLES
    from gate_v_exposure_scan import EntryClass
    orphan_rules = [(layout, rule.segments[0]) for layout, rules in _TABLES.items() for rule in rules if rule.entry_class is EntryClass.TEMP_ORPHAN_FILE]
    assert orphan_rules and {first for _, first in orphan_rules} == {"exposure"}
    assert all(layout.name == "CAMPAIGN_DIR" for layout, _ in orphan_rules)
    for layout, rules in _TABLES.items():
        for rule in rules:
            for segment in rule.segments:
                regex = getattr(segment, "regex", None)
                if regex is not None:
                    assert store.REGISTRY_TEMP_NAME_PATTERN not in regex and "registry" not in regex


def test_an_event_slot_can_be_published_with_a_closed_naming_and_is_binding_once_taken(tmp_path):
    """La nomination REGISTRY n'est utilisée ICI que pour exercer la sémantique du slot (occupé = binding) ; elle ne dit PAS que le scanner la tolérerait
    dans le répertoire d'événements (voir le test précédent) : le nommage du temporaire de l'événement canonique reste NON décidé (23.13 est muet)."""
    event = {"event": "synthetic", "seq": 1}
    result = store.publish_json_by_link(tmp_path / "event_0001.json", event, durability=SIMULATED, naming=REGISTRY, kind="événement")
    assert result.state is store.PublicationState.PUBLISHED_DURABLE
    with pytest.raises(store.SlotOccupiedError):
        store.publish_json_by_link(tmp_path / "event_0001.json", {"event": "other", "seq": 1}, durability=SIMULATED, naming=REGISTRY, kind="événement")
    assert (tmp_path / "event_0001.json").read_bytes() == store.serialize_normative_json(event)


def test_the_re_confirmation_gives_the_orchestrator_verifiable_facts_and_no_policy(tmp_path):
    first = store.publish_json_by_link(tmp_path / "event_0001.json", {"seq": 1}, durability=SIMULATED, naming=REGISTRY, kind="événement")
    again = store.confirm_published_slot(tmp_path / "event_0001.json", expected_sha256=first.identity.sha256, durability=SIMULATED,
                                         expected_identity=first.identity)
    assert again.operation is store.PublicationOperation.RECONFIRMED and again.identity == first.identity
    assert again.writer_pid == os.getpid() == first.writer_pid and again.publication_id != first.publication_id
