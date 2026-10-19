"""AF-V-07 Slice E3-D — vérification PURE de la chaîne du registre et évaluation d'un enregistrement candidat (ADR 0025 Décision 23.10). Aucune E/S.

Une seule logique sert deux usages :
  * `verify_chain` (LECTURE) : toute violation rend la chaîne CASSÉE (`RegistryChainError`) ; aucun repli, aucune réparation, jamais « chaîne vide » pour une chaîne invalide ;
  * `RegistryChain.with_record` (ÉVALUATION d'un candidat) : une violation est un refus TYPÉ (`RegistryRefusal`) ; le candidat n'est ni écrit ni publié ici.

Codes de refus : `CAMPAIGN_ALREADY_REGISTERED`, `CAMPAIGN_ALREADY_CONSUMED` et `OVERLAPPING_REGISTRATION` viennent de l'ADR (23.10 ; ce dernier existe déjà dans E3-A) ;
les autres (`CHAIN_LINK_BROKEN`, `REGISTRY_MISMATCH`, `INSTANCE_MISMATCH`, `PREDECESSOR_*`, `REBIND_INVALID`, `INVALID_RECORD`) sont PROPOSÉS (P21).
Ordre des vérifications (PROPOSÉ, P23 : l'ADR liste les contrôles de l'étape 2 sans fixer d'ordre) : lien de chaîne, instance, unicité par campagne, recouvrement, liens entre types.

Complexité : la vérification d'une chaîne de n slots est en O(n log n) (état incrémental : index par campagne, intervalles triés des fenêtres). Les fenêtres de campagnes différentes
sont deux à deux DISJOINTES dans une chaîne valide, donc seuls les deux voisins d'une fenêtre candidate peuvent la recouper.

Ce module ne dit RIEN de la validité d'une admission : les preuves (engagement, preuve de temps, attestation, autorisation) relèvent d'E3-E / E3-J et ne sont pas vérifiées ici.
"""

from __future__ import annotations

import bisect
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional

from gate_v_registry_model import (
    CAMPAIGN_RECORD_TYPES,
    REGISTRY_RECORD_VERSION,
    RecordType,
    compute_record_content_hash,
    genesis_prev_content_hash,
    validate_registry_record,
)

_ENGINE_FIELDS = frozenset({"admission_semantics_version", "registry_id", "seq", "prev_content_hash"})
_WINDOW_OWNERS = (RecordType.RESERVATION, RecordType.ADMISSION)


class CampaignState(str, Enum):
    """États dérivés du registre SEUL (23.18). `INCONSISTENT`, `*_STALE`, `CONSUMED_UNCONFIRMED` dépendent d'artefacts hors chaîne ou de la durabilité d'un slot : non dérivés ici."""

    ABSENT = "ABSENT"
    RESERVED = "RESERVED"
    ADMITTED = "ADMITTED"
    CONSUMED = "CONSUMED"


class RegistryRefusalCode(str, Enum):
    CAMPAIGN_ALREADY_REGISTERED = "CAMPAIGN_ALREADY_REGISTERED"      # ACCEPTED (23.10)
    CAMPAIGN_ALREADY_CONSUMED = "CAMPAIGN_ALREADY_CONSUMED"          # ACCEPTED (23.10)
    OVERLAPPING_REGISTRATION = "OVERLAPPING_REGISTRATION"            # ACCEPTED (nom E3-A `AdmissionRefusal`)
    CHAIN_LINK_BROKEN = "CHAIN_LINK_BROKEN"                          # PROPOSÉ
    REGISTRY_MISMATCH = "REGISTRY_MISMATCH"                          # PROPOSÉ
    INSTANCE_MISMATCH = "INSTANCE_MISMATCH"                          # PROPOSÉ
    PREDECESSOR_MISSING = "PREDECESSOR_MISSING"                      # PROPOSÉ
    PREDECESSOR_MISMATCH = "PREDECESSOR_MISMATCH"                    # PROPOSÉ
    REBIND_INVALID = "REBIND_INVALID"                                # PROPOSÉ
    INVALID_RECORD = "INVALID_RECORD"                                # PROPOSÉ (lecture seulement)


class RegistryRefusal(Exception):
    """Un candidat est refusé : RIEN n'est publié. `code` est un membre de `RegistryRefusalCode`."""

    def __init__(self, code: RegistryRefusalCode, message: str) -> None:
        super().__init__(f"{code.value} : {message}")
        self.code = code
        self.message = message


class RegistryChainError(Exception):
    """La chaîne lue est CASSÉE : rien n'est réparé, aucun repli. `index` : position du premier enregistrement fautif ; `code` : cause."""

    def __init__(self, code: RegistryRefusalCode, message: str, *, index: int) -> None:
        super().__init__(f"chaîne cassée au slot {index} ({code.value}) : {message}")
        self.code = code
        self.message = message
        self.index = index


@dataclass(frozen=True)
class ChainEntry:
    """Un enregistrement VÉRIFIÉ. `record` est une COPIE (le JSON canonique est conservé) : la modifier ne change pas la chaîne."""

    seq: int
    record_type: RecordType
    content_hash: str
    prev_content_hash: str
    instance_id: str
    campaign_id: Optional[str]
    window: Optional[tuple]
    record_json: str

    @property
    def record(self) -> dict:
        return json.loads(self.record_json)


def _refuse(code: RegistryRefusalCode, message: str):
    raise RegistryRefusal(code, message)


class _State:
    """État incrémental d'une chaîne vérifiée. `check` n'a AUCUN effet de bord ; `add` ajoute une entrée déjà vérifiée par `check`."""

    def __init__(self, registry_id: str, genesis_instance_id: str) -> None:
        self.registry_id = registry_id
        self.genesis_instance_id = genesis_instance_id
        self.entries: list = []
        self.index: dict = {}                      # campaign_id -> {RecordType: ChainEntry}
        self.intervals: list = []                  # [(début, fin, campaign_id)] triée ; UNE fenêtre par campagne (celle de sa première RESERVATION/ADMISSION)
        self.windowed: set = set()                 # campagnes déjà présentes dans `intervals`
        self.instances: set = {genesis_instance_id}

    @property
    def next_seq(self) -> int:
        return len(self.entries)

    @property
    def head_hash(self) -> str:
        return self.entries[-1].content_hash if self.entries else genesis_prev_content_hash(self.genesis_instance_id)

    @property
    def current_instance(self) -> str:
        return self.entries[-1].instance_id if self.entries else self.genesis_instance_id

    def clone(self) -> "_State":
        copy = _State(self.registry_id, self.genesis_instance_id)
        copy.entries = list(self.entries)
        copy.index = dict(self.index)
        copy.intervals = list(self.intervals)
        copy.windowed = set(self.windowed)
        copy.instances = set(self.instances)
        return copy

    def add(self, entry: ChainEntry) -> None:
        self.entries.append(entry)
        self.instances.add(entry.instance_id)
        if entry.campaign_id is None:
            return
        self.index[entry.campaign_id] = {**self.index.get(entry.campaign_id, {}), entry.record_type: entry}
        if entry.record_type in _WINDOW_OWNERS and entry.campaign_id not in self.windowed:
            bisect.insort(self.intervals, (entry.window[0], entry.window[1], entry.campaign_id))
            self.windowed.add(entry.campaign_id)

    @classmethod
    def from_entries(cls, registry_id: str, genesis_instance_id: str, entries: Iterable) -> "_State":
        state = cls(registry_id, genesis_instance_id)
        for entry in entries:
            state.add(entry)
        return state

    # ── contrôles ───────────────────────────────────────────────────────────────────────────────────────────────────────

    def check(self, record: dict) -> ChainEntry:
        record_type = validate_registry_record(record)
        expected_seq, expected_prev = self.next_seq, self.head_hash
        if record["seq"] != expected_seq:
            _refuse(RegistryRefusalCode.CHAIN_LINK_BROKEN, f"seq {record['seq']} au lieu de {expected_seq} (numérotation dense).")
        if record["prev_content_hash"] != expected_prev:
            _refuse(RegistryRefusalCode.CHAIN_LINK_BROKEN, "prev_content_hash ne désigne pas la tête de la chaîne.")
        if record["registry_id"] != self.registry_id:
            _refuse(RegistryRefusalCode.REGISTRY_MISMATCH, "registry_id différent de celui du registre.")
        if record_type is RecordType.REBIND:
            self._check_rebind(record, expected_seq, expected_prev)
        elif record["instance_id"] != self.current_instance:
            _refuse(RegistryRefusalCode.INSTANCE_MISMATCH, "instance_id différent de l'instance en vigueur (seul un REBIND la change).")
        campaign_id = window = None
        if record_type in CAMPAIGN_RECORD_TYPES:
            campaign_id = record["campaign_id"]
            window = (record["window_start_utc"], record["window_end_utc"])
            self._check_campaign_rules(record, record_type, campaign_id, window)
        return ChainEntry(seq=expected_seq, record_type=record_type, content_hash=compute_record_content_hash(record), prev_content_hash=record["prev_content_hash"],
                          instance_id=record["instance_id"], campaign_id=campaign_id, window=window,
                          record_json=json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))

    def _check_rebind(self, record: dict, expected_seq: int, expected_prev: str) -> None:
        if expected_seq == 0:
            _refuse(RegistryRefusalCode.REBIND_INVALID, "un REBIND ne peut pas ouvrir la chaîne.")
        if record["instance_id"] == self.current_instance:
            _refuse(RegistryRefusalCode.REBIND_INVALID, "un REBIND doit introduire un NOUVEL instance_id.")
        if record["instance_id"] in self.instances:                                         # PROPOSÉ (P22)
            _refuse(RegistryRefusalCode.REBIND_INVALID, "cet instance_id a déjà été porté par la chaîne : un REBIND n'y revient jamais.")
        if record["restored_head_seq"] != expected_seq - 1 or record["restored_head_content_hash"] != expected_prev:    # PROPOSÉ (P17)
            _refuse(RegistryRefusalCode.REBIND_INVALID, "la tête restaurée doit être l'enregistrement qui précède le REBIND.")

    def _check_campaign_rules(self, record: dict, record_type: RecordType, campaign_id: str, window: tuple) -> None:
        known = self.index.get(campaign_id, {})
        if record_type in known:                    # unicité : AUCUN second enregistrement du même type, même à contenu identique
            code = RegistryRefusalCode.CAMPAIGN_ALREADY_CONSUMED if record_type is RecordType.CONSUMPTION else RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED
            _refuse(code, f"la campagne a déjà un enregistrement {record_type.value} (slot {known[record_type].seq}).")
        rival = self._overlapping_rival(campaign_id, window)
        if rival is not None:
            _refuse(RegistryRefusalCode.OVERLAPPING_REGISTRATION, f"la fenêtre recoupe celle de la campagne {rival[2]} (réservation ou admission, conservée pour toujours).")
        if record_type is RecordType.ADMISSION:
            self._check_predecessor(known.get(RecordType.RESERVATION), record, window, "RESERVATION", "reservation_content_hash")
        elif record_type is RecordType.CONSUMPTION:
            self._check_predecessor(known.get(RecordType.ADMISSION), record, window, "ADMISSION", "admission_content_hash")

    def _overlapping_rival(self, campaign_id: str, window: tuple) -> Optional[tuple]:
        """Première fenêtre d'une AUTRE campagne qui recoupe `window` (semi-ouverte : `a.start < b.end ∧ b.start < a.end`), sinon `None`. Les fenêtres stockées sont deux à deux
        disjointes, donc triées par début ET par fin : seuls les plus proches voisins non-propres, à gauche et à droite, peuvent recouper."""
        start, end = window
        position = bisect.bisect_left(self.intervals, (start, ""))
        left = position - 1
        while left >= 0 and self.intervals[left][2] == campaign_id:
            left -= 1
        if left >= 0 and self.intervals[left][1] > start:
            return self.intervals[left]
        right = position
        while right < len(self.intervals) and self.intervals[right][2] == campaign_id:
            right += 1
        if right < len(self.intervals) and self.intervals[right][0] < end:
            return self.intervals[right]
        return None

    @staticmethod
    def _check_predecessor(predecessor: Optional[ChainEntry], record: dict, window: tuple, label: str, pin_field: str) -> None:
        if predecessor is None:
            _refuse(RegistryRefusalCode.PREDECESSOR_MISSING, f"aucune {label} de cette campagne dans la chaîne.")
        if record[pin_field] != predecessor.content_hash:
            _refuse(RegistryRefusalCode.PREDECESSOR_MISMATCH, f"{pin_field} ne désigne pas la {label} de la campagne.")
        # `reservation_seq` est INFORMATIF (23.10) : seul le hash du contenu lie l'ADMISSION à sa RESERVATION.
        earlier = predecessor.record
        if predecessor.window != window or earlier["commitment_content_hash"] != record["commitment_content_hash"]:    # fenêtre et engagement : 23.10 ; PROPOSÉ (P18) pour la CONSUMPTION
            _refuse(RegistryRefusalCode.PREDECESSOR_MISMATCH, f"fenêtre ou engagement différents de ceux de la {label}.")


@dataclass(frozen=True)
class RegistryChain:
    """Chaîne vérifiée, immuable. Se construit par `verify_chain` ou `with_record` : le constructeur direct ne revérifie RIEN (il reconstruit seulement les index)."""

    registry_id: str
    genesis_instance_id: str
    entries: tuple
    _state: Optional[_State] = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._state is None:
            object.__setattr__(self, "_state", _State.from_entries(self.registry_id, self.genesis_instance_id, self.entries))

    @property
    def next_seq(self) -> int:
        return len(self.entries)

    @property
    def head_content_hash(self) -> str:
        return self._state.head_hash

    @property
    def current_instance_id(self) -> str:
        return self._state.current_instance

    def campaign_entry(self, campaign_id: str, record_type: RecordType) -> Optional[ChainEntry]:
        return self._state.index.get(campaign_id, {}).get(record_type)

    def campaign_state(self, campaign_id: str) -> CampaignState:
        known = self._state.index.get(campaign_id, {})
        if RecordType.CONSUMPTION in known:
            return CampaignState.CONSUMED
        if RecordType.ADMISSION in known:
            return CampaignState.ADMITTED
        if RecordType.RESERVATION in known:
            return CampaignState.RESERVED
        return CampaignState.ABSENT

    def with_record(self, record: dict) -> "RegistryChain":
        """Chaîne prolongée par `record` s'il est valide ET admissible ; sinon `RegistryRefusal` (un enregistrement mal formé reste un `ValueError`). Ne publie rien."""
        entry = self._state.check(record)
        state = self._state.clone()
        state.add(entry)
        return RegistryChain(self.registry_id, self.genesis_instance_id, tuple(state.entries), state)


def assemble_record(chain: RegistryChain, body: object) -> dict:
    """Complète un corps par les champs que SEUL le moteur fixe : version, `registry_id`, `seq` (tête + 1), `prev_content_hash` (tête) et `instance_id` en vigueur. Un corps qui
    prétend les fixer est refusé ; `instance_id` n'est admis dans un corps que pour un `REBIND` (le NOUVEL instance_id)."""
    if type(body) is not dict:
        raise ValueError("la fabrique de corps doit retourner un dict.")
    claimed = sorted(_ENGINE_FIELDS & set(body))
    if claimed:
        raise ValueError(f"le corps ne doit pas fixer les champs du moteur : {claimed}.")
    if "instance_id" in body and body.get("record_type") != RecordType.REBIND.value:
        raise ValueError("instance_id n'est fixé par le corps que pour un REBIND.")
    record = {"admission_semantics_version": REGISTRY_RECORD_VERSION, "registry_id": chain.registry_id, "seq": chain.next_seq,
              "prev_content_hash": chain.head_content_hash}
    if "instance_id" not in body:
        record["instance_id"] = chain.current_instance_id
    record.update(body)
    return record


def verify_chain(records: Iterable, *, registry_id: str, genesis_instance_id: str) -> RegistryChain:
    """Vérifie une suite d'enregistrements déjà décodés, DANS L'ORDRE DES SLOTS (le lecteur disque garantit en plus que le nom de chaque fichier égale `seq`).
    Retourne la chaîne vérifiée ou lève `RegistryChainError` ; `ValueError` si `registry_id` ou `genesis_instance_id` sont eux-mêmes mal formés."""
    genesis_prev_content_hash(genesis_instance_id)           # valide le format de l'instance de genèse
    if type(registry_id) is not str or not registry_id:
        raise ValueError("registry_id doit être un texte non vide.")
    state = _State(registry_id, genesis_instance_id)
    for index, record in enumerate(records):
        try:
            state.add(state.check(record))
        except RegistryRefusal as refusal:
            raise RegistryChainError(refusal.code, refusal.message, index=index) from refusal
        except (ValueError, RecursionError) as error:
            raise RegistryChainError(RegistryRefusalCode.INVALID_RECORD, str(error), index=index) from error
    return RegistryChain(registry_id, genesis_instance_id, tuple(state.entries), state)
