"""AF-V-07 Slice E3-D — AJOUT au registre par la primitive de publication par lien d'E3-C (ADR 0025 Décision 23.10, étapes 1 à 7). Mode `SYNTHETIC` seulement.

Étapes (23.10) implémentées : (1) lire la chaîne entière et vérifier hashs et numérotation, PUIS barrière de lecture (faite par E3-C avant le lien) ; (2) évaluer le candidat
(`RegistryChain.with_record` : unicité par campagne, recouvrement, liens entre types) ; (3 à 7) publier le slot `n+1` par `tmp + fsync + link + fsync` (E3-C). Un slot occupé
(`SlotOccupiedError`) n'est NI un succès NI une idempotence : on REVIENT À L'ÉTAPE 1 — nouvelle lecture, fabrique de corps rappelée, TOUT revérifié — et jamais on ne publie directement dans le
slot suivant. Le nombre de tentatives est borné PAR APPEL et fourni EXPLICITEMENT (aucune valeur par défaut : la valeur normative reste une décision ouverte, 23.24) ; au-delà :
`RegistryContentionError` (`REGISTRY_CONTENTION`), rien de nous n'est publié. Un slot visible mais non confirmé (`PublishedUnconfirmedError`) reste BINDING : aucune nouvelle tentative,
aucune suppression.

PÉRIMÈTRE (matrice E3-D, W14). `_append_record` est un moteur INTERNE : il n'exporte aucune publication de `RESERVATION`, `ADMISSION` ni `REBIND`. Ces enregistrements dépendent de
preuves d'engagement, de temps, d'attestation et d'autorisation (E3-E / E3-J, NON implémentés) ; une fabrique de corps n'est PAS une preuve et le moteur n'en vérifie aucune. Seule
`publish_consumption` est publique : ses préconditions (ADMISSION de la même campagne présente et reconfirmée, Claim RELU et vérifié par E2, unicité) sont toutes démontrables ici. Elle ne
vaut que pour un registre `SYNTHETIC` : un `ADMISSION` d'un tel registre n'a aucune valeur probante (REAL = DISABLED / NOT QUALIFIED ; GATE V = NON PASSÉE ; FINAL_HOLDOUT = NON ACCÉDÉ).
Une `CONSUMPTION` n'est jamais rejouée ni re-confirmée après l'appel qui l'a publiée : aucune fonction de ce module ne reprend un slot `CONSUMPTION` existant.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Callable

import gate_v_registry_store as store
from atomic_json_store import (
    LinkPublication,
    LinkPublicationError,
    PublishedUnconfirmedError,
    SlotOccupiedError,
    TempNaming,
    confirm_published_slot,
    publish_json_by_link,
    serialize_normative_json,
)
from gate_v_final_holdout_claim_acquisition import load_final_holdout_access_claim
from gate_v_registry_chain import RegistryRefusal, RegistryRefusalCode, assemble_record
from gate_v_registry_model import RecordType, serialize_for_slot
from gate_v_registry_store import RegistrySnapshot, read_registry


class RegistryContentionError(Exception):
    """`REGISTRY_CONTENTION` (23.10) : le nombre borné de tentatives est épuisé par des slots occupés. RIEN de nous n'est publié ; les slots des concurrents sont binding."""

    def __init__(self, attempts: int) -> None:
        super().__init__(f"REGISTRY_CONTENTION : {attempts} tentative(s) épuisée(s) par des slots occupés ; aucun enregistrement n'a été publié par cet appel.")
        self.attempts = attempts


class RegistryUnreadableRecordError(Exception):
    """E3-C : un écrivain de slot dense et IRRÉPARABLE doit prouver, AVANT la publication, que son lecteur relira ces octets. Cet enregistrement dépasserait un plafond du lecteur strict
    (taille du slot, nombre de slots) ou ne ferait pas l'aller-retour exact : il n'est PAS publié (le publier rendrait le registre définitivement illisible)."""

    published_anything = False


class RegistryPreconditionError(Exception):
    """Une précondition de publication (re-confirmation de l'ADMISSION) a échoué : RIEN n'a été publié (`published_anything` est faux). L'erreur de la primitive E3-C est en `__cause__` ;
    elle concerne le slot de l'ADMISSION, jamais un slot de CONSUMPTION : ne pas lui appliquer la règle « PublishedUnconfirmed = binding » d'une publication."""

    published_anything = False


class RegistryPublishedUnconfirmedError(Exception):
    """`PublishedUnconfirmed` (23.10) : le slot est VISIBLE mais sa durabilité n'est pas démontrée. Il est BINDING : ni republication, ni suppression, aucune étape suivante.
    L'erreur de la primitive E3-C est en `__cause__`."""

    slot_is_binding = True
    replay_safe = False

    def __init__(self, message: str, *, seq: int, content_hash: str, slot_path) -> None:
        super().__init__(message)
        self.seq = seq
        self.content_hash = content_hash
        self.slot_path = slot_path


@dataclass(frozen=True)
class AppendOutcome:
    seq: int
    record_type: RecordType
    content_hash: str
    publication: LinkPublication
    attempts: int
    collisions: int


def _require_max_attempts(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("max_attempts doit être un entier (non booléen) >= 1, fourni explicitement : aucune valeur par défaut (23.24).")
    return value


def _prove_reader_will_reread(record: dict, seq: int) -> None:
    """E3-C : avant de publier un slot DENSE et IRRÉPARABLE, prouver que le lecteur strict relira EXACTEMENT ces octets — plafond de taille, plafond du nombre de slots et aller-retour
    octets -> JSON strict -> mêmes octets. Un échec ici ne publie rien (`RegistryUnreadableRecordError`)."""
    payload = serialize_for_slot(record)
    if len(payload) > store.MAX_SLOT_BYTES:
        raise RegistryUnreadableRecordError(f"slot {seq} de {len(payload)} octets : le lecteur strict refuse au-delà de {store.MAX_SLOT_BYTES} ; rien n'est publié.")
    if seq + 1 > store.MAX_SLOTS:
        raise RegistryUnreadableRecordError(f"le slot {seq} dépasserait les {store.MAX_SLOTS} slots que le lecteur strict accepte ; rien n'est publié.")
    try:
        reread = store._load_strict_json(payload, f"slot {seq}")
    except ValueError as error:
        raise RegistryUnreadableRecordError(f"le lecteur strict refuserait le slot {seq} ({error}) ; rien n'est publié.") from error
    if reread != record or serialize_normative_json(reread) != payload:
        raise RegistryUnreadableRecordError(f"le slot {seq} ne ferait pas l'aller-retour exact du lecteur strict ; rien n'est publié.")


def _append_record(root, build_body: Callable[[RegistrySnapshot], dict], *, max_attempts: int, unproven_synthetic: bool) -> AppendOutcome:
    """Moteur INTERNE (voir l'en-tête). `build_body(snapshot)` est rappelée à CHAQUE tentative sur une chaîne fraîchement lue et vérifiée : c'est là que l'appelant revérifie ses propres
    préconditions. Elle peut lever `RegistryRefusal` : rien n'est alors publié.
    `unproven_synthetic` DOIT être `True` : l'appelant reconnaît explicitement que ce moteur ne vérifie AUCUNE preuve (engagement, temps, attestation, autorisation : E3-E / E3-J) et
    que ce qu'il publie, dans un registre SYNTHETIC, n'a aucune valeur probante. Ce n'est pas une preuve : c'est une garde de conception (W14) contre un usage involontaire."""
    if unproven_synthetic is not True:
        raise ValueError("unproven_synthetic=True est obligatoire : ce moteur ne vérifie aucune preuve et ne produit aucune admission utilisable (E3-E / E3-J non implémentés).")
    attempts_allowed = _require_max_attempts(max_attempts)
    collisions = 0
    for attempt in range(1, attempts_allowed + 1):
        snapshot = read_registry(root, barrier=False)                       # étape 1 : lire la chaîne ; la barrière suit, dans la publication
        record = assemble_record(snapshot.chain, build_body(snapshot))
        extended = snapshot.chain.with_record(record)                       # étape 2 : unicité, recouvrement, liens ; RegistryRefusal ou ValueError
        seq = record["seq"]
        _prove_reader_will_reread(record, seq)
        content_hash = extended.entries[-1].content_hash
        target = snapshot.slot_path(seq)
        try:
            publication = publish_json_by_link(target, record, durability=snapshot.identity.durability_profile, naming=TempNaming.REGISTRY,
                                               kind="enregistrement du registre")
        except SlotOccupiedError:
            collisions += 1                                                # le slot est binding ; on REVIENT À L'ÉTAPE 1
            continue
        except PublishedUnconfirmedError as error:
            raise RegistryPublishedUnconfirmedError(
                f"slot {seq} publié mais NON confirmé ({error.reason.value}) : binding, aucune nouvelle tentative, jamais supprimé.",
                seq=seq, content_hash=content_hash, slot_path=target) from error
        return AppendOutcome(seq=seq, record_type=RecordType(record["record_type"]), content_hash=content_hash, publication=publication, attempts=attempt,
                             collisions=collisions)
    raise RegistryContentionError(attempts_allowed)


def publish_consumption(registry_root, plan, campaign_dir, *, created_at: str, max_attempts: int) -> AppendOutcome:
    """Publie la `CONSUMPTION` de la campagne du `plan` (registre `SYNTHETIC` seulement). Préconditions, TOUTES revérifiées à chaque tentative :
      * le Claim est RELU sur disque par `load_final_holdout_access_claim` (E2 : forme stricte, hashs recalculés, liaison au plan) — jamais un booléen ni un objet fourni ;
      * le registre contient l'`ADMISSION` de CETTE campagne (sinon `PREDECESSOR_MISSING`) et son slot est RE-CONFIRMÉ (octets exacts + barrière) avant de la consommer ;
      * aucune `CONSUMPTION` de cette campagne n'existe : sinon `CAMPAIGN_ALREADY_CONSUMED`, même si elle est identique (aucune idempotence, aucune réutilisation).
    Elle ne VÉRIFIE PAS la validité de l'admission (engagement, preuve de temps, attestation, autorisation : E3-E / E3-J, non implémentés)."""
    campaign_id = plan.campaign_id
    locator = os.path.abspath(os.fspath(campaign_dir))

    def build(snapshot: RegistrySnapshot) -> dict:
        claim = load_final_holdout_access_claim(plan, campaign_dir)
        if snapshot.chain.campaign_entry(campaign_id, RecordType.CONSUMPTION) is not None:
            raise RegistryRefusal(RegistryRefusalCode.CAMPAIGN_ALREADY_CONSUMED, "une CONSUMPTION de cette campagne existe déjà : aucune réutilisation ni idempotence.")
        admission = snapshot.chain.campaign_entry(campaign_id, RecordType.ADMISSION)
        if admission is None:
            raise RegistryRefusal(RegistryRefusalCode.PREDECESSOR_MISSING, "aucune ADMISSION de cette campagne dans le registre.")
        admission_record = admission.record
        try:
            confirm_published_slot(snapshot.slot_path(admission.seq), expected_sha256=hashlib.sha256(serialize_normative_json(admission_record)).hexdigest(),
                                   durability=snapshot.identity.durability_profile)
        except LinkPublicationError as error:
            raise RegistryPreconditionError(
                f"l'ADMISSION (slot {admission.seq}) n'a pas pu être re-confirmée ({type(error).__name__}) : rien n'a été publié, aucune CONSUMPTION n'existe du fait de cet appel.") from error
        return {
            "record_type": RecordType.CONSUMPTION.value,
            "created_at": created_at,
            **{name: admission_record[name] for name in ("campaign_id", "window_start_utc", "window_end_utc", "commitment_id", "commitment_content_hash", "code_identity_hash")},
            "campaign_dir_locator": locator,
            "claim_id": claim.claim_id,
            "claim_content_hash": claim.claim_content_hash,
            "admission_content_hash": admission.content_hash,
        }

    return _append_record(registry_root, build, max_attempts=max_attempts, unproven_synthetic=True)
