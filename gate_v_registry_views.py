"""AF-V-07 Slice E3-D — LECTURES du registre, en lecture seule (ADR 0025 Décision 23.10) : jamais une publication.

1. `find_reusable_record` : « reprise après crash » (23.10). Pour `RESERVATION` et `ADMISSION` SEULEMENT, relit l'enregistrement existant de la campagne et le retourne s'il a un contenu
   SÉMANTIQUE identique à celui du candidat (identité sémantique : `admission_id` pour l'admission, PROPOSÉ P19 pour la réservation) ; son slot est alors re-confirmé octet par octet
   (re-confirmation permise pour ces deux types). Un contenu différent est un refus `CAMPAIGN_ALREADY_REGISTERED`, jamais une réutilisation ni une publication. `CONSUMPTION` (et
   `REBIND`) : AUCUNE réutilisation ni idempotence, `ValueError`.
2. `read_authoritative_admission` : interface de lecture AUTORITATIVE de l'ADMISSION d'une campagne, préparée pour F1/F5 sans les figer. Elle lit et vérifie la chaîne ENTIÈRE (barrière
   APRÈS la lecture), re-confirme le slot de l'ADMISSION, puis copie le contenu vérifié. Elle ne prend AUCUN enregistrement ni preuve de l'appelant : un témoin fourni n'est jamais autoritatif.
   Les références d'attestation, d'autorisation et d'observation du plus haut slot d'attestation sont des conteneurs OPAQUES recopiés tels quels (P9) : leur forme, leur hash et leur
   évaluation relèvent de F5 / E3-E, et la vérification de l'atomicité de l'observation, d'E3-J. Ce n'est PAS la vue F1 (exposition, recouvrement) et rien ici ne vaut preuve d'admission
   (REAL = DISABLED / NOT QUALIFIED ; registre SYNTHETIQUE ; GATE V = NON PASSÉE ; FINAL_HOLDOUT = NON ACCÉDÉ).
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from typing import Optional

from atomic_json_store import LinkPublication, confirm_published_slot, serialize_normative_json
from gate_v_registry_chain import CampaignState, ChainEntry, RegistryRefusal, RegistryRefusalCode, assemble_record
from gate_v_registry_model import (
    RecordType,
    RegistryMode,
    compute_admission_id,
    compute_reservation_semantic_id,
    validate_campaign_id,
    validate_registry_record,
)
from gate_v_registry_store import RegistrySnapshot, read_registry

_REUSABLE = {RecordType.RESERVATION: compute_reservation_semantic_id, RecordType.ADMISSION: compute_admission_id}


@dataclass(frozen=True)
class ReusedRecord:
    """Un enregistrement existant relu, de contenu sémantique identique, dont le slot vient d'être re-confirmé. Rien n'a été publié."""

    entry: ChainEntry
    publication: LinkPublication


@dataclass(frozen=True)
class AuthoritativeAdmission:
    """Copie VÉRIFIÉE de l'ADMISSION d'une campagne telle que lue dans une chaîne entière et valide. Les trois références sont OPAQUES (copies profondes)."""

    registry_id: str
    registry_mode: RegistryMode
    campaign_id: str
    campaign_state: CampaignState
    admission_seq: int
    admission_content_hash: str
    admission_id: str
    reservation_content_hash: str
    reservation_seq: int
    commitment_id: str
    commitment_content_hash: str
    code_identity_hash: str
    window_start_utc: str
    window_end_utc: str
    static_sources_digest: str
    overlap_projection_hash: str
    attachment_id: str
    attachment_content_hash: str
    time_proof_content_hash: str
    attestation_hash: str
    authorization_hash: str
    attestation_observation: dict
    chain_head_seq: int
    chain_head_content_hash: str
    confirmation: LinkPublication

    @property
    def is_probative_admission_proof(self) -> bool:
        """TOUJOURS faux. Aucune vue de ce module n'est une preuve d'admission : un registre SYNTHETIC n'a aucune valeur probante, et les preuves (engagement, preuve de temps,
        attestation, autorisation) relèvent d'E3-E / E3-J, non implémentés ; REAL = DISABLED / NOT QUALIFIED. Un consommateur F1/F5 ne doit jamais accorder de droit sur cette seule vue."""
        return False


def _reconfirm(snapshot: RegistrySnapshot, entry: ChainEntry) -> LinkPublication:
    expected = hashlib.sha256(serialize_normative_json(entry.record)).hexdigest()
    return confirm_published_slot(snapshot.slot_path(entry.seq), expected_sha256=expected, durability=snapshot.identity.durability_profile)


def find_reusable_record(registry_root, record_type: RecordType, body: dict) -> Optional[ReusedRecord]:
    """Voir l'en-tête. `body` est le corps complet du candidat (hors champs du moteur). Retourne `None` si la campagne n'a aucun enregistrement de ce type.
    ADMISSION : réutilisable seulement si AUCUNE `CONSUMPTION` n'existe dans le registre pour ce `campaign_id` (23.10) — sinon `CAMPAIGN_ALREADY_CONSUMED`, avant toute re-confirmation.
    NON vérifié ici (artefacts HORS registre, E3-J) : la condition de 23.10 « aucun Claim ni ReadIntent n'existe localement » ; l'appelant (E3-J) doit la contrôler lui-même."""
    if type(record_type) is not RecordType or record_type not in _REUSABLE:
        raise ValueError("seules une RESERVATION et une ADMISSION peuvent être relues et réutilisées ; une CONSUMPTION n'a aucune réutilisation ni idempotence.")
    if type(body) is not dict or body.get("record_type") != record_type.value:
        raise ValueError(f"le corps doit être un dict de type {record_type.value}.")
    snapshot = read_registry(registry_root, barrier=False)
    candidate = assemble_record(snapshot.chain, body)
    validate_registry_record(candidate)
    existing = snapshot.chain.campaign_entry(candidate["campaign_id"], record_type)
    if existing is None:
        return None
    if record_type is RecordType.ADMISSION and snapshot.chain.campaign_entry(candidate["campaign_id"], RecordType.CONSUMPTION) is not None:
        raise RegistryRefusal(RegistryRefusalCode.CAMPAIGN_ALREADY_CONSUMED,
                              "une CONSUMPTION de cette campagne existe : son ADMISSION n'est plus réutilisable (23.10), aucune re-confirmation n'est faite.")
    semantic_id = _REUSABLE[record_type]
    if semantic_id(existing.record) != semantic_id(candidate):
        raise RegistryRefusal(RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED,
                              f"la campagne a déjà une {record_type.value} (slot {existing.seq}) de contenu différent : refus, aucune réutilisation.")
    return ReusedRecord(entry=existing, publication=_reconfirm(snapshot, existing))


def read_authoritative_admission(registry_root, campaign_id: str) -> Optional[AuthoritativeAdmission]:
    """Voir l'en-tête. `None` si la campagne n'a pas d'ADMISSION. Toute anomalie de lecture, de chaîne, de barrière ou de re-confirmation lève : AUCUNE vue partielle."""
    campaign_id = validate_campaign_id(campaign_id)
    snapshot = read_registry(registry_root, barrier=True)
    chain = snapshot.chain
    admission = chain.campaign_entry(campaign_id, RecordType.ADMISSION)
    if admission is None:
        return None
    reservation = chain.campaign_entry(campaign_id, RecordType.RESERVATION)
    confirmation = _reconfirm(snapshot, admission)
    record = admission.record
    return AuthoritativeAdmission(
        registry_id=chain.registry_id, registry_mode=snapshot.identity.mode, campaign_id=campaign_id, campaign_state=chain.campaign_state(campaign_id),
        admission_seq=admission.seq, admission_content_hash=admission.content_hash, admission_id=compute_admission_id(record),
        reservation_content_hash=record["reservation_content_hash"], reservation_seq=reservation.seq,
        commitment_id=record["commitment_id"], commitment_content_hash=record["commitment_content_hash"], code_identity_hash=record["code_identity_hash"],
        window_start_utc=record["window_start_utc"], window_end_utc=record["window_end_utc"], static_sources_digest=record["static_sources_digest"],
        overlap_projection_hash=record["overlap_projection_hash"], attachment_id=record["attachment_id"], attachment_content_hash=record["attachment_content_hash"],
        time_proof_content_hash=record["time_proof_content_hash"], attestation_hash=record["attestation_hash"],
        authorization_hash=record["authorization_hash"], attestation_observation=copy.deepcopy(record["attestation_observation"]),
        chain_head_seq=chain.next_seq - 1, chain_head_content_hash=chain.head_content_hash, confirmation=confirmation)
