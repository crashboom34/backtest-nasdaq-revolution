"""AF-V-07 E3-B — attestations avant et après l'`ADMISSION` : caractérisation de F1 (AI_HANDOFF.md §56.5) sur B3 v3, B4, B5 et B6.

Question : « un slot d'attestation postérieur à l'ADMISSION n'a aucun effet sur l'exécution en cours » (ADR 0025 23.29.3, 23.31.4) alors que B3 lit chaque
`attestation_<seq4>.json` d'une campagne scannée et qu'un slot illisible rend la racine incomplète (`complete` faux), donc change `inventory_id`
(23.30.4), que l'étape 13 de 23.17 recompare. Ce module MESURE, scénario par scénario et séparément, les findings, `complete`, `inventory_id`,
`static_sources_digest`, la projection de recouvrement, les anomalies d'audit et les refus de B6.

Il ne simule AUCUNE garantie d'E3-D (registre, `ADMISSION`) ni d'E3-J (orchestrateur) : une `ADMISSION` n'existe pas dans ce lot. `AttestationPin` est
le SEUL témoin d'admission que B6 reçoit ; il vient de l'appelant, B6 ne peut pas l'authentifier (tests `test_s7*`). Le conflit F1 est donc CARACTÉRISÉ
(`test_s4_*`), pas corrigé : sa correction exige une entrée autoritative dans le recalcul de B3 (proposition exacte dans
`docs/adr/0025-proposal-E3B-F1-F5-PROPOSED.md`, F1 = SPEC BLOCKED). Fixtures SYNTHÉTIQUES dans `tmp_path` uniquement ; aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections import namedtuple
from pathlib import Path

import pytest

import gate_v_exposure_declarations as b6
import gate_v_exposure_interpreters as b3
import gate_v_exposure_store as store
from gate_v_exposure_scan import AuditRoot
from gate_v_final_holdout_protocol import (
    OwnCampaignContext,
    OwnRecordStage,
    build_exposure_declaration,
    compute_exposure_inventory_id,
    compute_overlap_projection_hash,
    compute_static_sources_digest,
)
from tests.gate_v_exposure_support import CREATED_AT, CURRENT, LIMITS, STAGE0, W, assemble, interpret, write_json

Measure = namedtuple("Measure", "findings complete inventory_id static projection reasons inventory")
UNREADABLE = b"{ not json"


def normative_bytes(record) -> bytes:
    return (json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def interpret_campaign(directory: Path):
    root = b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, AuditRoot("camp", str(directory)))
    return b3.interpret_audit_roots((root,), LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])


def measure(directory: Path) -> Measure:
    assembly = assemble(interpret_campaign(directory))
    inventory = assembly.inventory
    return Measure(len(inventory.findings), inventory.complete, assembly.inventory_id, compute_static_sources_digest(inventory, STAGE0),
                   compute_overlap_projection_hash(inventory, STAGE0), assembly.incomplete_reasons, inventory)


def first_declaration(directory: Path, inventory_id: str, carried_from=None) -> None:
    declaration = build_exposure_declaration(declaration_seq=1, declarant="Mira", inventory_id=inventory_id, prev_declaration_id=None,
                                             declared_exposures=(), declared_t_sel_utc=None, declared_trial_counts=None)
    envelope = b6.build_declaration_envelope(declaration, campaign_id=CURRENT, prev_declaration_content_hash=None, carried_from=carried_from,
                                             created_at="2026-10-21T09:00:00+00:00")
    path = b6.declaration_path(directory, inventory_id, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b6.serialize_declaration_envelope(envelope))


def build_campaign(tmp_path: Path):
    """Campagne synthétique `campaign_current` : ancre, A0 publié par B5, première déclaration. Retourne (dossier, inventory_id, mesure de base)."""
    directory = tmp_path / CURRENT
    write_json(directory / "plan.json", {"campaign_id": CURRENT})
    base = measure(directory)
    store.publish_exposure_inventory(directory, assemble(interpret_campaign(directory)), created_at=CREATED_AT)
    first_declaration(directory, base.inventory_id)
    return directory, base.inventory_id, base


def write_slot(directory: Path, inventory_id: str, seq: int, content) -> Path:
    path = b6.attestation_path(directory, inventory_id, seq)
    path.write_bytes(content if isinstance(content, bytes) else normative_bytes(content))
    return path


def pin_of(path: Path, inventory_id: str, seq: int) -> "b6.AttestationPin":
    return b6.AttestationPin(inventory_id, seq, hashlib.sha256(path.read_bytes()).hexdigest())


def lineage(directory: Path, inventory_id: str, pin=None):
    return b6.load_declaration_lineage(directory, current_inventory_id=inventory_id, campaign_id=CURRENT, pinned_a0_hashes=frozenset(),
                                       admitted_attestation=pin)


def refusal(directory: Path, inventory_id: str, pin=None) -> "b6.LineageFailure":
    with pytest.raises(b6.LineageError) as caught:
        lineage(directory, inventory_id, pin)
    return caught.value.failure


def same_scientific_identity(measured: Measure, base: Measure) -> bool:
    return (measured.findings, measured.static, measured.projection, measured.inventory_id) == (base.findings, base.static, base.projection,
                                                                                               base.inventory_id)


def attestation_reasons(measured: Measure):
    return [reason for reason in measured.reasons if "/attestation_" in reason]


def kinds(loaded, kind):
    return [(e.kind, e.relative_path) for e in loaded.ignored if e.kind is kind]


# ── Ligne de base et scénarios 1 à 8 ─────────────────────────────────────────────────────────────────────────────────

def test_s0_baseline_the_exposure_tree_without_attestation_has_the_identity_of_the_bare_campaign(tmp_path):
    directory, inventory_id, base = build_campaign(tmp_path)
    assert (base.findings, base.complete, base.reasons) == (0, True, ())
    assert same_scientific_identity(measure(directory), base)                         # A0 et déclaration lisibles : informatifs, sans effet
    assert lineage(directory, inventory_id).phase is b6.LineagePhase.PRE_ADMISSION


def test_s1_a_valid_attestation_before_admission_changes_no_identity_and_is_read_by_b6(tmp_path):
    directory, inventory_id, base = build_campaign(tmp_path)
    write_slot(directory, inventory_id, 1, {"seq": 1})
    measured = measure(directory)
    assert measured.complete is True and same_scientific_identity(measured, base) and measured.reasons == ()
    loaded = lineage(directory, inventory_id)
    assert loaded.state is b6.LineageState.CURRENT_IS_TERMINAL and b6.highest_attestation_slot(loaded).seq == 1


def test_s2_an_unreadable_attestation_before_admission_is_refused_by_both_layers(tmp_path):
    """Fail-closed AVANT l'ADMISSION : B3 rend la racine incomplète ET B6 refuse la lignée. Seul `inventory_id` bouge (via `complete`)."""
    directory, inventory_id, base = build_campaign(tmp_path)
    write_slot(directory, inventory_id, 1, UNREADABLE)
    measured = measure(directory)
    assert measured.complete is False and measured.inventory_id != base.inventory_id
    assert (measured.findings, measured.static, measured.projection) == (base.findings, base.static, base.projection)    # aucune exposition nouvelle
    assert len(attestation_reasons(measured)) == 1 and attestation_reasons(measured)[0].startswith("INFORMATIVE_UNRESOLVED:")
    assert refusal(directory, inventory_id) is b6.LineageFailure.ATTESTATION_INVALID


def test_s3_a_valid_later_slot_after_admission_has_no_effect_anywhere(tmp_path):
    directory, inventory_id, base = build_campaign(tmp_path)
    pin = pin_of(write_slot(directory, inventory_id, 1, {"seq": 1}), inventory_id, 1)
    write_slot(directory, inventory_id, 2, {"seq": 2})
    measured = measure(directory)
    assert measured.complete is True and same_scientific_identity(measured, base)
    loaded = lineage(directory, inventory_id, pin)
    assert loaded.state is b6.LineageState.CURRENT_IS_TERMINAL and loaded.admitted_attestation.seq == 1
    assert kinds(loaded, b6.IgnoredKind.ATTESTATION_WITHOUT_EFFECT) == [
        (b6.IgnoredKind.ATTESTATION_WITHOUT_EFFECT, f"exposure/{inventory_id}/attestation_0002.json")]


def test_s4_known_conflict_f1_an_unreadable_later_slot_after_admission_is_inert_for_b6_but_changes_the_b3_inventory_id(tmp_path):
    """CONFLIT F1 CARACTÉRISÉ, NON CORRIGÉ (SPEC BLOCKED) : 23.29.3 dit « aucun effet » et B6 s'y conforme ; B3 ne dispose d'aucune information
    d'`ADMISSION` (voir `test_b3_has_no_admission_input`) : `complete` passe à faux, donc `inventory_id` change, alors que findings,
    `static_sources_digest` et projection (les autres comparaisons de l'étape 13) restent égaux. Ce test devra changer, volontairement, quand la
    décision normative de F1 sera prise."""
    directory, inventory_id, base = build_campaign(tmp_path)
    pin = pin_of(write_slot(directory, inventory_id, 1, {"seq": 1}), inventory_id, 1)
    write_slot(directory, inventory_id, 2, UNREADABLE)
    measured = measure(directory)
    assert measured.complete is False and measured.inventory_id != base.inventory_id          # le conflit
    assert (measured.findings, measured.static, measured.projection) == (base.findings, base.static, base.projection)
    assert attestation_reasons(measured) == [f"INFORMATIVE_UNRESOLVED:camp/exposure/{inventory_id}/attestation_0002.json"]
    assert lineage(directory, inventory_id, pin).state is b6.LineageState.CURRENT_IS_TERMINAL     # B6 : sans effet, conformément à l'ADR


def test_s5_the_pinned_attestation_becoming_unreadable_is_refused_by_both_layers(tmp_path):
    directory, inventory_id, base = build_campaign(tmp_path)
    first = write_slot(directory, inventory_id, 1, {"seq": 1})
    pin = pin_of(first, inventory_id, 1)
    first.write_bytes(UNREADABLE)
    assert measure(directory).complete is False
    assert refusal(directory, inventory_id, pin) is b6.LineageFailure.ADMITTED_ATTESTATION_REPLACED


def test_s5b_the_pinned_attestation_replaced_by_another_valid_one_is_refused_by_b6_and_invisible_to_b3(tmp_path):
    """« Remplacée » = fichier épinglé par hash différent (23.29.3). B3 ne voit rien (JSON valide, informatif) : seul le hash épinglé protège."""
    directory, inventory_id, base = build_campaign(tmp_path)
    first = write_slot(directory, inventory_id, 1, {"seq": 1})
    pin = pin_of(first, inventory_id, 1)
    first.write_bytes(normative_bytes({"seq": 1, "forged": True}))
    assert same_scientific_identity(measure(directory), base)
    assert refusal(directory, inventory_id, pin) is b6.LineageFailure.ADMITTED_ATTESTATION_REPLACED


def test_s6_an_earlier_slot_altered_after_admission_is_not_reread_by_b6_but_stays_visible_and_typed(tmp_path):
    """Chronologie NON prouvée : B6 ne sait pas quand un slot a été altéré. Après l'ADMISSION seule l'attestation épinglée est pertinente
    (23.29.3) : B6 ne relit pas un slot antérieur, mais le consigne distinctement d'un slot postérieur (`ATTESTATION_NOT_REREAD`). B3 le
    signale par l'incomplétude : c'est la seule détection d'une altération d'historique, qu'une option (b) générale supprimerait."""
    directory, inventory_id, base = build_campaign(tmp_path)
    first = write_slot(directory, inventory_id, 1, {"seq": 1})
    pin = pin_of(write_slot(directory, inventory_id, 2, {"seq": 2}), inventory_id, 2)
    first.write_bytes(UNREADABLE)
    measured = measure(directory)
    assert measured.complete is False and attestation_reasons(measured) == [
        f"INFORMATIVE_UNRESOLVED:camp/exposure/{inventory_id}/attestation_0001.json"]
    loaded = lineage(directory, inventory_id, pin)
    assert loaded.admitted_attestation.seq == 2
    assert kinds(loaded, b6.IgnoredKind.ATTESTATION_NOT_REREAD) == [
        (b6.IgnoredKind.ATTESTATION_NOT_REREAD, f"exposure/{inventory_id}/attestation_0001.json")]
    assert not kinds(loaded, b6.IgnoredKind.ATTESTATION_WITHOUT_EFFECT)


def test_s6b_later_and_earlier_slots_are_typed_apart_around_the_pinned_one(tmp_path):
    directory, inventory_id, _ = build_campaign(tmp_path)
    write_slot(directory, inventory_id, 1, {"seq": 1})
    pin = pin_of(write_slot(directory, inventory_id, 2, {"seq": 2}), inventory_id, 2)
    write_slot(directory, inventory_id, 3, {"seq": 3})
    loaded = lineage(directory, inventory_id, pin)
    assert kinds(loaded, b6.IgnoredKind.ATTESTATION_NOT_REREAD) == [
        (b6.IgnoredKind.ATTESTATION_NOT_REREAD, f"exposure/{inventory_id}/attestation_0001.json")]
    assert kinds(loaded, b6.IgnoredKind.ATTESTATION_WITHOUT_EFFECT) == [
        (b6.IgnoredKind.ATTESTATION_WITHOUT_EFFECT, f"exposure/{inventory_id}/attestation_0003.json")]


def test_s7a_a_forged_pin_whose_hash_matches_no_file_is_refused(tmp_path):
    directory, inventory_id, _ = build_campaign(tmp_path)
    write_slot(directory, inventory_id, 1, {"seq": 1})
    assert refusal(directory, inventory_id, b6.AttestationPin(inventory_id, 1, "0" * 64)) is b6.LineageFailure.ADMITTED_ATTESTATION_REPLACED
    assert refusal(directory, inventory_id, b6.AttestationPin(inventory_id, 2, "0" * 64)) is b6.LineageFailure.ADMITTED_ATTESTATION_MISSING
    assert refusal(directory, inventory_id, b6.AttestationPin("7" * 64, 1, "0" * 64)) is b6.LineageFailure.ADMITTED_ATTESTATION_MISSING


def test_s7b_b6_cannot_authenticate_which_slot_the_admission_really_pinned(tmp_path):
    """DÉPENDANCE E3-D / E3-J : deux épinglages différents, chacun cohérent avec un fichier réel, sont acceptés ; un appelant qui désigne un slot
    ANTÉRIEUR fait passer un slot illisible plus haut pour « sans effet ». Seule la référence portée par l'enregistrement `ADMISSION` du registre
    (hors B6) fait foi ; B6 ne peut que vérifier que le fichier désigné existe, est identique et valide."""
    directory, inventory_id, _ = build_campaign(tmp_path)
    first = write_slot(directory, inventory_id, 1, {"seq": 1})
    second = write_slot(directory, inventory_id, 2, {"seq": 2})
    assert lineage(directory, inventory_id, pin_of(first, inventory_id, 1)).admitted_attestation.seq == 1
    assert lineage(directory, inventory_id, pin_of(second, inventory_id, 2)).admitted_attestation.seq == 2
    second.write_bytes(UNREADABLE)                                               # le slot le plus haut devient illisible
    assert lineage(directory, inventory_id, pin_of(first, inventory_id, 1)).admitted_attestation.seq == 1      # « sans effet » si l'on affirme seq 1
    assert refusal(directory, inventory_id) is b6.LineageFailure.ATTESTATION_INVALID                          # sans affirmation : refus


def test_s7c_the_pin_is_the_only_admission_witness_b6_receives():
    assert list(b6.AttestationPin.__dataclass_fields__) == ["inventory_id", "seq", "file_sha256"]
    assert set(inspect.signature(b6.load_declaration_lineage).parameters) == {
        "campaign_dir", "current_inventory_id", "campaign_id", "pinned_a0_hashes", "admitted_attestation"}


def add_successor_chain(tmp_path: Path, directory: Path, first_id: str, *, with_declaration: bool = True):
    """Deuxième inventaire de la même campagne (autre racine `results` : un job dans W, autre `inventory_id`, même W) et, si demandé, sa chaîne,
    qui reprend la première par `carried_from`. Retourne l'assemblage du successeur."""
    second = assemble(interpret(tmp_path / "second"))
    assert second.inventory_id != first_id
    store.publish_exposure_inventory(directory, second, created_at="2026-10-20T09:00:00+00:00")
    if with_declaration:
        older = b6.parse_declaration_file(b6.declaration_path(directory, first_id, 1).read_bytes(), inventory_id=first_id, seq=1, campaign_id=CURRENT)
        carried = b6.CarriedFrom(first_id, 1, older.declaration_id, older.content_hash)
        first_declaration(directory, second.inventory_id, carried_from=carried.to_record())
    return second


def test_s7d_a_pin_on_a_non_terminal_chain_is_refused_because_the_terminal_chain_changed(tmp_path):
    """23.29.3 : après l'ADMISSION, un changement de chaîne terminale est un changement d'exposition (étape 13 de 23.17)."""
    directory, first_id, _ = build_campaign(tmp_path)
    old_pin = pin_of(write_slot(directory, first_id, 1, {"seq": 1}), first_id, 1)
    second = add_successor_chain(tmp_path, directory, first_id)
    assert refusal(directory, first_id, old_pin) is b6.LineageFailure.INVENTORY_REVERSION                     # déjà refusé : courant non terminal
    assert refusal(directory, second.inventory_id, old_pin) is b6.LineageFailure.ADMITTED_CHAIN_NOT_TERMINAL     # nouveau


def test_s7e_a_pin_on_the_terminal_chain_is_refused_when_the_current_inventory_has_no_chain_yet(tmp_path):
    """Revue A : l'inventaire courant recalculé n'est plus celui de l'attestation épinglée (nouvel `inventory_id`, pas encore de chaîne) ; avant
    l'ADMISSION l'attestation serait périmée (`highest_attestation_slot` = None), après elle le recalcul est un changement d'exposition."""
    directory, first_id, _ = build_campaign(tmp_path)
    pin = pin_of(write_slot(directory, first_id, 1, {"seq": 1}), first_id, 1)
    second = add_successor_chain(tmp_path, directory, first_id, with_declaration=False)
    assert lineage(directory, second.inventory_id).state is b6.LineageState.NO_CHAIN_FOR_CURRENT               # sans épinglage : état seul
    assert refusal(directory, second.inventory_id, pin) is b6.LineageFailure.ADMITTED_INVENTORY_CHANGED
    assert lineage(directory, first_id, pin).state is b6.LineageState.CURRENT_IS_TERMINAL                    # contrôle positif


def test_s6c_slots_of_another_chain_are_never_later_slots_whatever_their_seq(tmp_path):
    """Mutation : « postérieur » exige la MÊME chaîne que le slot épinglé ; un slot de plus haut `seq` dans une chaîne historique est « non relu »."""
    directory, first_id, _ = build_campaign(tmp_path)
    write_slot(directory, first_id, 1, {"seq": 1})
    write_slot(directory, first_id, 2, {"seq": 2})
    write_slot(directory, first_id, 3, {"seq": 3})
    second = add_successor_chain(tmp_path, directory, first_id)
    pin = pin_of(write_slot(directory, second.inventory_id, 1, {"seq": 1}), second.inventory_id, 1)
    write_slot(directory, second.inventory_id, 2, {"seq": 2})
    loaded = lineage(directory, second.inventory_id, pin)
    assert kinds(loaded, b6.IgnoredKind.ATTESTATION_WITHOUT_EFFECT) == [
        (b6.IgnoredKind.ATTESTATION_WITHOUT_EFFECT, f"exposure/{second.inventory_id}/attestation_0002.json")]
    assert [path for _, path in kinds(loaded, b6.IgnoredKind.ATTESTATION_NOT_REREAD)] == [
        f"exposure/{first_id}/attestation_000{n}.json" for n in (1, 2, 3)]


# ── Scénario 8 : reprise après ADMISSION puis Claim / CONSUMPTION ──────────────────────────────────────────────────────

def own_registry_view(stage_records):
    """Vue du registre avec les enregistrements PROPRES de la campagne (RESERVATION, ADMISSION) : fenêtre égale à W, donc absorbés par E3-A à l'étage
    qui les attend (23.27.2). Le Claim et la CONSUMPTION exigent le fichier Claim d'E2 et un registre complet (E3-D) : non simulés ici."""
    from gate_v_exposure_inventory import RegistryRecordFact
    from gate_v_final_holdout_protocol import SourceKind, normalize_utc_instant
    from tests.gate_v_exposure_support import h, registry
    kinds_by_name = {"RES": SourceKind.REGISTRY_RESERVATION, "ADM": SourceKind.REGISTRY_ADMISSION}
    window = (normalize_utc_instant(W[0]), normalize_utc_instant(W[1]))
    return registry(RegistryRecordFact(seq=seq, kind=kinds_by_name[name], campaign_id=CURRENT, content_hash=h(name), window_start_utc=window[0],
                                       window_end_utc=window[1]) for seq, name in enumerate(stage_records, start=1))


def stage_measure(directory: Path, stage: "OwnRecordStage", records) -> str:
    return assemble(interpret_campaign(directory), reg=own_registry_view(records), context=OwnCampaignContext(CURRENT, stage)).inventory_id


@pytest.mark.parametrize("stage, records", [(OwnRecordStage.RESERVED, ("RES",)), (OwnRecordStage.ADMITTED, ("RES", "ADM"))],
                         ids=["reserved", "admitted"])
def test_s8_with_the_own_registry_records_absorbed_the_inventory_identity_is_stable_and_the_f1_conflict_remains(tmp_path, stage, records):
    """Étage RÉEL : les enregistrements propres du registre sont absorbés à l'étage qui les attend, l'`inventory_id` est celui de la campagne nue
    (comparé à l'étape 13) ; un slot valide postérieur ne le change pas, un slot illisible postérieur le change (F1) comme à l'ADMISSION."""
    directory, inventory_id, base = build_campaign(tmp_path)
    assert stage_measure(directory, stage, records) == base.inventory_id                             # enregistrements propres absorbés
    write_slot(directory, inventory_id, 1, {"seq": 1})
    write_slot(directory, inventory_id, 2, {"seq": 2})
    assert stage_measure(directory, stage, records) == base.inventory_id
    write_slot(directory, inventory_id, 2, UNREADABLE)
    assert stage_measure(directory, stage, records) != base.inventory_id


def test_s8_the_stage_given_to_the_recalculation_matters_so_the_caller_must_supply_the_right_one(tmp_path):
    """Limite constatée par la revue B : l'étage n'est pas dans la formule, mais il décide quels enregistrements propres sont absorbés. Un mauvais
    étage (ici NO_OWN_RECORDS alors qu'une RESERVATION et une ADMISSION existent) change `inventory_id` : E3-J doit fournir l'étage exact (23.27.2)."""
    directory, _, base = build_campaign(tmp_path)
    admitted = ("RES", "ADM")
    assert stage_measure(directory, OwnRecordStage.ADMITTED, admitted) == base.inventory_id
    assert stage_measure(directory, OwnRecordStage.NO_OWN_RECORDS, admitted) != base.inventory_id
    assert stage_measure(directory, OwnRecordStage.RESERVED, admitted) != base.inventory_id


@pytest.mark.parametrize("stage", list(OwnRecordStage), ids=lambda stage: stage.value)
def test_s8_without_own_records_the_f1_conflict_is_the_same_whatever_the_stage_argument(tmp_path, stage):
    """Niveau formule d'E3-A seulement (aucun enregistrement propre dans cette campagne synthétique) : l'étage reçu ne change rien. Le Claim et la
    CONSUMPTION ne sont pas simulés ; ce test ne prétend pas couvrir un registre réel."""
    directory, inventory_id, base = build_campaign(tmp_path)
    context = OwnCampaignContext(CURRENT, stage)
    persisted_id = compute_exposure_inventory_id(base.inventory, context)
    write_slot(directory, inventory_id, 1, {"seq": 1})
    write_slot(directory, inventory_id, 2, {"seq": 2})
    assert compute_exposure_inventory_id(measure(directory).inventory, context) == persisted_id
    write_slot(directory, inventory_id, 2, UNREADABLE)
    assert compute_exposure_inventory_id(measure(directory).inventory, context) != persisted_id


def test_s8b_a_restart_after_claim_rereads_the_same_lineage_and_the_same_pinned_attestation(tmp_path):
    """Reprise : deux chargements successifs (avant et après un arrêt) donnent la même lignée, le même sommet, le même slot épinglé ; B6 n'a ni
    entrée ni état d'étage, de Claim ou de CONSUMPTION."""
    directory, inventory_id, _ = build_campaign(tmp_path)
    pin = pin_of(write_slot(directory, inventory_id, 1, {"seq": 1}), inventory_id, 1)
    write_slot(directory, inventory_id, 2, {"seq": 2})
    first, second = lineage(directory, inventory_id, pin), lineage(directory, inventory_id, pin)
    keys = lambda loaded: (loaded.state, loaded.phase, loaded.declaration_lineage_digest, loaded.tip_declaration_content_hash,
                           loaded.admitted_attestation, loaded.pinning, tuple(loaded.ignored))
    assert keys(first) == keys(second) and first.declaration_set == second.declaration_set


def test_the_scanner_and_the_lineage_loader_agree_on_an_orphan_a0_and_on_a_pinned_one(tmp_path):
    """Cohérence B3 / B6 sur un A0 illisible (déplacé depuis `test_gate_v_exposure_integration.py` pour garder le commit B5 autonome, assertions
    inchangées) : B3 ne rend jamais la racine incomplète, B6 le consigne et ne le refuse que si l'ADMISSION l'épingle."""
    directory = tmp_path / "campaign_current"
    write_json(directory / "plan.json", {"campaign_id": "campaign_current"})
    assembly = assemble(interpret(tmp_path / "src"))
    store.publish_exposure_inventory(directory, assembly, created_at=CREATED_AT)
    orphan_hash = "9" * 64
    (directory / "exposure" / f"inventory_{orphan_hash}.json").write_bytes(b"{")
    assert interpret_campaign(directory).complete is True                               # B3 : jamais une incomplétude, l'épinglage lui est inconnu
    loaded = b6.load_declaration_lineage(directory, current_inventory_id=assembly.inventory_id, campaign_id="campaign_current",
                                         pinned_a0_hashes=frozenset(), admitted_attestation=None)
    assert [(e.kind, e.relative_path) for e in loaded.ignored] == [
        (b6.IgnoredKind.UNREADABLE_INVENTORY, f"exposure/inventory_{orphan_hash}.json")] and len(loaded.inventories) == 1
    with pytest.raises(b6.LineageError) as pinned:                                      # B6 : refus dès que l'appelant (ADMISSION) l'épingle
        b6.load_declaration_lineage(directory, current_inventory_id=assembly.inventory_id, campaign_id="campaign_current",
                                    pinned_a0_hashes=frozenset({orphan_hash}), admitted_attestation=None)
    assert pinned.value.failure is b6.LineageFailure.PINNED_A0_UNREADABLE


def test_b3_has_no_admission_input():
    """Information disponible pour décider F1 : B3 ne reçoit que des racines, des plafonds et la fenêtre. Aucune entrée d'ADMISSION, de slot épinglé
    ou de phase : il ne peut pas distinguer un slot postérieur d'un défaut antérieur. Son contrat public est verrouillé par un test publié."""
    assert set(inspect.signature(b3.interpret_audit_roots).parameters) == {
        "roots", "limits", "holdout_window_start_utc", "holdout_window_end_utc", "hooks"}
