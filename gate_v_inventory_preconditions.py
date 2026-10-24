"""
gate_v_inventory_preconditions.py — AF-V-07 E3-E S-0b/S-5a : part « inventaire » des préconditions d'une RESERVATION et d'une ADMISSION.

Amendement de l'ADR 0025 23.10 / 23.33.5 (accepté par l'utilisateur le 2026-10-24) : une `RESERVATION` ou une `ADMISSION` n'est recevable que si
l'inventaire COMPLET a été démontré (`inventory.complete == True`). Un ensemble pertinent vide ne suffit jamais si `complete` est faux : un
`manifest.json` non conforme, par exemple, ne produit qu'une RAISON d'incomplétude (aucun finding, B3 v4), donc un ensemble pertinent vide.

Ce module est PUR : aucune E/S, aucune horloge, aucune écriture, aucun import de registre ou d'écrivain. Il ne retourne que des REFUS ; une liste de
refus vide signifie seulement « la part inventaire est satisfaite », JAMAIS « autorisé » : les autres préconditions (chaîne du registre lue
strictement, concurrence de slots, engagement, preuve de temps, attestation, autorisation, déclarations, D5) relèvent de E3-D/E3-J. E3-D n'a pas
d'écrivain public de RESERVATION/ADMISSION et E3-J n'existe pas : la garde n'est donc PAS opérationnelle de bout en bout (contrats différés testés).

LIMITE EXPLICITE : ce validateur ne remplace PAS les sept vérifications préalables d'une `ADMISSION` (ADR 0025 23.27.4), répétées après tout conflit de
slot. Il n'en couvre qu'une part (complétude, ensemble pertinent, `inventory_id`, `static_sources_digest`). Restent des obligations d'E3-J, testées en
contrats différés : `inventory_content_digest` (non vérifié ici), attestation valide (classification recalculée égale), autorisation valide, déclarations
inchangées, `ReservationTimeProof`, projection de recouvrement, chaîne du registre lue strictement. Aucun appelant ne doit lire une liste de refus vide
comme une admission.

Règles (ADR 0025 23.10, 23.27.1) :
- RESERVATION (étage `NO_OWN_RECORDS`) : inventaire complet ET ensemble pertinent VIDE (toute source non `NO_OVERLAP`, rivale comprise, bloque) ;
- ADMISSION (étage `RESERVED`) : inventaire complet ; aucune source exposante, inconnue ou non résolue dans l'ensemble pertinent ; aucune
  réservation ou admission rivale recoupante (`OVERLAPPING_REGISTRATION`) ; `inventory_id` et `static_sources_digest` recalculés égaux à ceux épinglés.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from gate_v_final_holdout_protocol import (
    ExposureInventory,
    OverlapVerdict,
    OwnCampaignContext,
    OwnRecordStage,
    SourceKind,
    SourceStatus,
    compute_exposure_inventory_id,
    compute_static_sources_digest,
    partition_own_records,
)


class RegistryRecordType(str, Enum):
    RESERVATION = "RESERVATION"
    ADMISSION = "ADMISSION"


class InventoryPreconditionRefusal(str, Enum):
    INVENTORY_INCOMPLETE = "INVENTORY_INCOMPLETE"
    STAGE_MISMATCH = "STAGE_MISMATCH"
    OWN_RECORD_ANOMALY = "OWN_RECORD_ANOMALY"
    RELEVANT_SET_NOT_EMPTY = "RELEVANT_SET_NOT_EMPTY"
    UNRESOLVED_OR_EXPOSING_SOURCE = "UNRESOLVED_OR_EXPOSING_SOURCE"
    OVERLAPPING_REGISTRATION = "OVERLAPPING_REGISTRATION"
    PINS_MISSING = "PINS_MISSING"
    PINNED_INVENTORY_ID_MISMATCH = "PINNED_INVENTORY_ID_MISMATCH"
    PINNED_STATIC_SOURCES_DIGEST_MISMATCH = "PINNED_STATIC_SOURCES_DIGEST_MISMATCH"


_EXPECTED_STAGE = {RegistryRecordType.RESERVATION: OwnRecordStage.NO_OWN_RECORDS, RegistryRecordType.ADMISSION: OwnRecordStage.RESERVED}
_REGISTRATION_KINDS = frozenset({SourceKind.REGISTRY_RESERVATION, SourceKind.REGISTRY_ADMISSION})
_OWN_EXPOSING_KINDS = frozenset({SourceKind.FINAL_HOLDOUT_CLAIM, SourceKind.CONSUMPTION, SourceKind.READ_INTENT})


@dataclass(frozen=True)
class InventoryPreconditionReport:
    """Refus de la part inventaire, dans l'ordre fixe de l'énumération. Vide = part inventaire satisfaite, jamais une autorisation."""

    record_type: RegistryRecordType
    refusals: tuple

    @property
    def inventory_part_satisfied(self) -> bool:
        return not self.refusals


def inventory_precondition_refusals(
    record_type: RegistryRecordType,
    inventory: ExposureInventory,
    own_context: OwnCampaignContext,
    *,
    pinned_inventory_id: Optional[str] = None,
    pinned_static_sources_digest: Optional[str] = None,
) -> InventoryPreconditionReport:
    if type(record_type) is not RegistryRecordType:
        raise TypeError("record_type doit être un RegistryRecordType.")
    if type(inventory) is not ExposureInventory:
        raise TypeError("inventory doit être un ExposureInventory.")
    if type(own_context) is not OwnCampaignContext:
        raise TypeError("own_context doit être un OwnCampaignContext.")
    for name, value in (("pinned_inventory_id", pinned_inventory_id), ("pinned_static_sources_digest", pinned_static_sources_digest)):
        if value is not None and type(value) is not str:
            raise TypeError(f"{name} doit être un str ou None.")
    found = set()
    if not inventory.complete:
        found.add(InventoryPreconditionRefusal.INVENTORY_INCOMPLETE)
    if own_context.own_record_stage is not _EXPECTED_STAGE[record_type]:
        found.add(InventoryPreconditionRefusal.STAGE_MISMATCH)
    _, remaining, anomalies = partition_own_records(inventory, own_context)
    if anomalies:
        found.add(InventoryPreconditionRefusal.OWN_RECORD_ANOMALY)
    # Ensemble pertinent (23.27.1) PLUS tout Claim, `CONSUMPTION` ou `ReadIntent` PROPRE résolu mais non absorbé : même disjoint de `W`, E3-A le traite
    # comme une exposition établie (23.27.2, échec fermé) ; ce validateur ne doit jamais être plus permissif que la classification.
    relevant = [finding for finding in remaining
                if finding.overlap is not OverlapVerdict.NO_OVERLAP
                or (finding.campaign_id == own_context.current_campaign_id and finding.source_kind in _OWN_EXPOSING_KINDS
                    and finding.status is SourceStatus.RESOLVED)]
    if record_type is RegistryRecordType.RESERVATION:
        if relevant:
            found.add(InventoryPreconditionRefusal.RELEVANT_SET_NOT_EMPTY)
    else:
        if any(finding.source_kind not in _REGISTRATION_KINDS for finding in relevant):
            found.add(InventoryPreconditionRefusal.UNRESOLVED_OR_EXPOSING_SOURCE)
        if any(finding.source_kind in _REGISTRATION_KINDS for finding in relevant):
            found.add(InventoryPreconditionRefusal.OVERLAPPING_REGISTRATION)
        if pinned_inventory_id is None or pinned_static_sources_digest is None:
            found.add(InventoryPreconditionRefusal.PINS_MISSING)
        else:
            if pinned_inventory_id != compute_exposure_inventory_id(inventory, own_context):
                found.add(InventoryPreconditionRefusal.PINNED_INVENTORY_ID_MISMATCH)
            if pinned_static_sources_digest != compute_static_sources_digest(inventory, own_context):
                found.add(InventoryPreconditionRefusal.PINNED_STATIC_SOURCES_DIGEST_MISMATCH)
    return InventoryPreconditionReport(record_type, tuple(refusal for refusal in InventoryPreconditionRefusal if refusal in found))
