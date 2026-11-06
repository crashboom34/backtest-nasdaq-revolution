"""
gate_v_audit_registry.py — N-VIDE-2 / N2-b1b : adaptateur de LECTURE d'AUDIT du registre (module interne, lecture seule, diagnostic seul).

Ce module lit le registre SYNTHÉTIQUE (deux fois : R1 avant le premier scan, R2 après la relecture finale), convertit la chaîne vérifiée en vue de B4, dérive l'étage de l'enregistrement propre,
attribue des racines « dérivées » à des campagnes de la chaîne, assemble B4 et rend des SCALAIRES, des tuples et un diagnostic immuable des déclarations des plans V2 (N2-b2a, séparé de la comptabilité de B4). Il n'écrit rien (la lecture s'accompagne d'une barrière de répertoire, appel de type `fsync` sans modification de contenu), ne persiste rien, n'appelle aucune fonction d'écriture, d'ajout,
d'initialisation ou de publication du registre, ne crée aucun enregistrement propre, n'ouvre aucune donnée de marché et n'accorde aucun droit.

Ce que le résultat n'est PAS : ni une preuve d'absence d'exposition, ni une admission, ni une autorisation, ni une complétude globale du registre. Trois dimensions restent DISTINCTES et ne sont
jamais agrégées : la complétude de B3, la complétude de B4 et la couverture du registre par des racines dérivées. Une racine dérivée est attribuée si son plan V2, recalculé depuis son contenu,
porte le nom attendu : un plan authentique recopié dans un dossier de même nom passerait (attribution faible, limite consignée). Les compteurs que B4 n'observe pas valent `None`, jamais zéro.
Aucun instantané atomique : R1 = R2 ne prouve ni chronologie ni lecture réelle par les workers ; un slot supprimé puis restauré à l'identique entre R1 et R2 n'est pas détecté (ABA).
"""

from __future__ import annotations

import dataclasses
import enum
import os
from typing import Optional

import gate_v_audit_plan_declared as plan_declared
import gate_v_audit_window as window_sources
import gate_v_exposure_interpreters as interpreters
from gate_v_audit_plan_declared import PlanDeclaredBasis, PlanDeclaredDiagnostic
from gate_v_exposure_inventory import AccountingViews, CounterProvenance, RegistryRecordFact, RegistryView, assemble_exposure_inventory
from gate_v_final_holdout_protocol import OwnCampaignContext, OwnRecordStage, SourceKind, SourceStatus
from gate_v_registry_chain import CampaignState, RegistryChainError
from gate_v_registry_model import RecordType
from gate_v_registry_store import MAX_IDENTITY_BYTES, MAX_SLOT_BYTES, MAX_SLOTS, ReadFailure, RegistryReadError, read_registry

__all__ = ["REGISTRY_REFUSAL_CODES", "CounterState", "PlanDeclaredBasis", "PlanDeclaredDiagnostic", "RegistryAssessment", "RegistryAuditRefused", "RegistryConfig", "RegistryCoverage", "RegistryHandle", "TrialCounter", "assess", "compare", "read",
           "validate_config"]

MAX_DETAIL = 300
MAX_B4_REASONS = 64
MAX_UNCOVERED_SAMPLE = 20
_CLAIM_FILE = "final_holdout_access_claim.json"          # constante PRIVÉE : le nom de fichier du Claim de la racine propre ; la garde de vocabulaire ne porte que sur les noms publics

# Codes de refus de l'adaptateur (chaînes d'un ensemble FERMÉ ; le protocole les convertit par table, l'adaptateur n'importe pas son énumération).
REGISTRY_REFUSAL_CODES = ("REQUEST_INVALID", "RESOURCE_BUDGET_EXCEEDED", "REGISTRY_UNREADABLE", "REGISTRY_CHAIN_HEAD_CHANGED", "WINDOW_MISMATCH", "STAGE_NOT_DERIVABLE", "B4_ASSEMBLY_REFUSED")
_TOO_LARGE_FAILURES = frozenset({ReadFailure.TOO_MANY_SLOTS, ReadFailure.TOO_LARGE})
_KINDS = {RecordType.RESERVATION: SourceKind.REGISTRY_RESERVATION, RecordType.ADMISSION: SourceKind.REGISTRY_ADMISSION, RecordType.CONSUMPTION: SourceKind.CONSUMPTION}
_BACKSLASHES = {ord("/"): "\\"}
_EXTENDED_PREFIXES = ("\\\\?\\", "\\\\.\\")          # préfixes étendus Windows (testés après normalisation des barres, toutes graphies) : refusés comme par le scanner des racines d'audit
_COUNTER_NAMES = ("research_runs", "strategies", "campaigns", "abandoned_reservations", "failed_ingestion_attempts", "void_commitments")


class CounterState(str, enum.Enum):
    """Provenance d'un compteur d'essais (correspondance exhaustive avec `CounterProvenance` de B4, que le protocole ne peut pas importer)."""

    OBSERVED = "OBSERVED"
    PARTIAL = "PARTIAL"
    NOT_OBSERVED = "NOT_OBSERVED"


class RegistryCoverage(str, enum.Enum):
    """Couverture du registre par des racines dérivées : ne dit RIEN du contenu des dossiers ni de l'exposition ; vraie par vacuité sur une chaîne sans autre campagne."""

    NOT_ASSESSED = "NOT_ASSESSED"
    ALL_CHAIN_CAMPAIGNS_HAVE_ROOT = "ALL_CHAIN_CAMPAIGNS_HAVE_ROOT"
    PARTIAL = "PARTIAL"


_STATE_OF = {CounterProvenance.OBSERVED: CounterState.OBSERVED, CounterProvenance.PARTIAL: CounterState.PARTIAL, CounterProvenance.NOT_OBSERVED: CounterState.NOT_OBSERVED}


@dataclasses.dataclass(frozen=True, kw_only=True)
class RegistryConfig:
    """Configuration de l'opérateur : racine du registre et plafonds EXPLICITES (aucune valeur par défaut). Les deux plafonds bornent les octets lus dans les slots et le nombre d'entrées énumérées."""

    root_path: str
    max_slots: int
    max_total_bytes: int


@dataclasses.dataclass(frozen=True)
class TrialCounter:
    """`value` vaut `None` si et seulement si la provenance est `NOT_OBSERVED` : jamais le zéro de remplacement de B4 pour un compteur non observé."""

    name: str
    value: Optional[int]
    provenance: CounterState

    def __post_init__(self) -> None:
        if type(self.name) is not str or type(self.provenance) is not CounterState or (self.value is not None and (type(self.value) is not int or self.value < 0)):
            raise ValueError("TrialCounter mal formé")
        if (self.value is None) != (self.provenance is CounterState.NOT_OBSERVED):
            raise ValueError("value vaut None si et seulement si la provenance est NOT_OBSERVED")


class RegistryAuditRefused(Exception):
    """Refus typé de la lecture d'audit : `code` ∈ `REGISTRY_REFUSAL_CODES`, `detail` ∈ ensemble fermé documenté (ou préfixé `R2:`)."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in REGISTRY_REFUSAL_CODES or type(detail) is not str or len(detail) > MAX_DETAIL:
            raise ValueError("RegistryAuditRefused mal formé")
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclasses.dataclass(frozen=True)
class RegistryAssessment:
    """Résultat de `assess` : scalaires, tuples et un diagnostic immuable des déclarations des plans V2 (jamais l'assemblage de B4, la vue, la chaîne, l'instantané ni `inventory_id`). Le diagnostic est
    OBLIGATOIRE (aucune valeur par défaut) et n'entre jamais dans la comptabilité de B4."""

    b4_complete: bool
    b4_incomplete_reasons: tuple
    b4_semantics_version: str
    registry_id: str
    registry_chain_head: str
    registry_slot_count: int
    registry_rebind_count: int
    registry_durability_profile: str
    derived_root_labels: tuple
    registry_coverage: RegistryCoverage
    registry_other_campaign_count: int
    registry_uncovered_count: int
    registry_uncovered_sample: tuple
    trial_counters: tuple
    trial_counter_reasons: tuple
    plan_declared_diagnostic: PlanDeclaredDiagnostic


_TOKEN = object()


class RegistryHandle:
    """Poignée OPAQUE d'une lecture : aucun attribut public, ni copie, ni sérialisation. Elle porte l'instantané jusqu'à `assess`, puis seulement l'empreinte et les `content_hash`."""

    __slots__ = ("_state",)

    def __init__(self, token, snapshot, stamp: tuple, hashes: tuple) -> None:
        if token is not _TOKEN:
            raise TypeError("RegistryHandle ne se construit que par `read`")
        object.__setattr__(self, "_state", [snapshot, stamp, hashes])

    def __setattr__(self, name, value):
        raise AttributeError("RegistryHandle est figée")

    def __reduce__(self):
        raise TypeError("RegistryHandle n'est pas transportable")

    def __reduce_ex__(self, protocol):
        raise TypeError("RegistryHandle n'est pas transportable")

    def __copy__(self):
        raise TypeError("RegistryHandle n'est pas copiable")

    def __deepcopy__(self, memo):
        raise TypeError("RegistryHandle n'est pas copiable")

    def __delattr__(self, name):
        raise AttributeError("RegistryHandle est figée")

    def __repr__(self) -> str:
        return "RegistryHandle()"


def _refuse(code: str, detail: str):
    raise RegistryAuditRefused(code, detail)


def _clip(text: str) -> str:
    return text if len(text) <= MAX_DETAIL else text[:MAX_DETAIL - 1] + "…"


# ── Configuration (mémoire seule : aucun accès disque) ───────────────────────────────────────────────────────────────────────────────────────────
def _is_strict_int(value) -> bool:
    return type(value) is int


def _components(path: str) -> tuple:
    absolute = os.path.normcase(os.path.abspath(path))
    drive, rest = os.path.splitdrive(absolute)
    return drive, tuple(part for part in rest.split(os.sep) if part)


def _has_parent_component(path: str) -> bool:
    return any(part == ".." for chunk in path.split("/") for part in chunk.split("\\"))


def _overlaps(first: tuple, second: tuple) -> bool:
    if first[0] != second[0]:
        return False
    shorter, longer = (first[1], second[1]) if len(first[1]) <= len(second[1]) else (second[1], first[1])
    return longer[:len(shorter)] == shorter


def validate_config(config, *, audit_root_paths) -> int:
    """Valide `config` SANS accès disque et retourne la PART REGISTRE du budget de lecture : `2 × (max_total_bytes + MAX_IDENTITY_BYTES + 2)` (R1 et R2 ; `+ 2` = le `+ 1` d'un échec par
    lecture, deux lectures d'identité de `MAX_IDENTITY_BYTES + 1` octets au plus). Lève `RegistryAuditRefused`. Pas de `realpath` : une jonction, un nom 8.3 ou un lien dans un parent
    échappent au garde de recouvrement, de même qu'un lecteur mappé ou `subst` (B2 verrait alors des entrées inconnues : audit incomplet, jamais silencieux). Les préfixes étendus Windows (`\\\\?\\`, `\\\\.\\`) sont refusés. Les constantes du store (`MAX_SLOTS`, `MAX_SLOT_BYTES`,
    `MAX_IDENTITY_BYTES`) sont liées à l'import de ce module (valeurs fixes en production) ; le store relit les siennes à chaque appel."""
    if type(config) is not RegistryConfig:
        _refuse("REQUEST_INVALID", "REGISTRY_CONFIG")
    path = config.root_path
    if type(path) is not str or not path.strip() or "\x00" in path or not os.path.isabs(path) or _has_parent_component(path) or path.translate(_BACKSLASHES).startswith(_EXTENDED_PREFIXES):
        _refuse("REQUEST_INVALID", "REGISTRY_CONFIG")
    if not _is_strict_int(config.max_slots) or not _is_strict_int(config.max_total_bytes) or config.max_slots < 1 or config.max_total_bytes < 1:
        _refuse("REQUEST_INVALID", "REGISTRY_CONFIG")
    if config.max_slots > MAX_SLOTS or config.max_total_bytes > MAX_SLOTS * MAX_SLOT_BYTES:
        _refuse("REQUEST_INVALID", "REGISTRY_CONFIG")
    if type(audit_root_paths) is not tuple or any(type(p) is not str for p in audit_root_paths):
        _refuse("REQUEST_INVALID", "REGISTRY_CONFIG")
    registry = _components(path)
    for other in audit_root_paths:
        if _overlaps(registry, _components(other)):
            _refuse("REQUEST_INVALID", "REGISTRY_ROOT_OVERLAP")
    return 2 * (config.max_total_bytes + MAX_IDENTITY_BYTES + 2)


# ── Lecture ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _read_error(error: Exception, prefix: str) -> RegistryAuditRefused:
    """Table fermée : `TOO_MANY_SLOTS` et `TOO_LARGE` ⇒ `RESOURCE_BUDGET_EXCEEDED` (`REGISTRY_TOO_LARGE`) ; les autres échecs de lecture et les erreurs de chaîne ⇒ `REGISTRY_UNREADABLE`. Aucun autre
    type d'erreur n'est converti : il n'existe pas de détail « erreur de lecture générique »."""
    if isinstance(error, RegistryReadError):
        if error.failure in _TOO_LARGE_FAILURES:
            return RegistryAuditRefused("RESOURCE_BUDGET_EXCEEDED", prefix + "REGISTRY_TOO_LARGE")
        return RegistryAuditRefused("REGISTRY_UNREADABLE", _clip(prefix + error.failure.value))
    if isinstance(error, RegistryChainError):
        return RegistryAuditRefused("REGISTRY_UNREADABLE", _clip(f"{prefix}CHAIN:{error.code.value}@{error.index}"))
    raise error


def _read_snapshot(config: RegistryConfig, prefix: str):
    try:
        return read_registry(config.root_path, barrier=True, max_slots=config.max_slots, max_total_bytes=config.max_total_bytes)
    except (RegistryReadError, RegistryChainError) as error:          # toute autre exception (dont un `ValueError` de validation du store) n'est PAS masquée : le protocole la rend `AUDIT_INTERNAL_FAILURE`
        raise _read_error(error, prefix) from None


def _stamp(snapshot) -> tuple:
    identity, chain = snapshot.identity, snapshot.chain
    return (identity.registry_id, identity.instance_id, identity.mode.value, identity.durability_profile.value, chain.current_instance_id, chain.head_content_hash, chain.next_seq)


def read(config, *, own_campaign_id: str, window: tuple) -> RegistryHandle:
    """R1 : lecture stricte avec barrière et plafonds, puis contrôle IMMÉDIAT des fenêtres des enregistrements de la campagne propre (elles doivent égaler la fenêtre de l'opérateur, `window`
    normalisée) : sinon refus `WINDOW_MISMATCH` avant tout scan. Retourne une poignée opaque."""
    snapshot = _read_snapshot(config, "")
    for entry in snapshot.chain.entries:
        if entry.campaign_id == own_campaign_id and entry.window != window:
            _refuse("WINDOW_MISMATCH", "OWN_RECORD_WINDOW")
    return RegistryHandle(_TOKEN, snapshot, _stamp(snapshot), tuple(entry.content_hash for entry in snapshot.chain.entries))


def compare(handle, config) -> None:
    """R2 : relit (mêmes plafonds, barrière) et compare à R1, règles ordonnées, la première qui s'applique décide : IDENTITY_CHANGED, DIVERGED, INSTANCE_CHANGED, EXTENDED. Aucun ajout légitime
    pendant l'audit n'est un succès. Un échec de lecture de R2 suit la table de R1 avec le préfixe `R2:`. Ne prouve ni instantané atomique ni absence de modification après R2."""
    if type(handle) is not RegistryHandle:
        raise TypeError("handle doit être un RegistryHandle")
    _snapshot, stamp1, hashes1 = handle._state
    second = _read_snapshot(config, "R2:")
    stamp2 = _stamp(second)
    hashes2 = tuple(entry.content_hash for entry in second.chain.entries)
    n1, n2 = stamp1[6], stamp2[6]
    if stamp1[:4] != stamp2[:4]:
        _refuse("REGISTRY_CHAIN_HEAD_CHANGED", "IDENTITY_CHANGED")
    if n2 < n1 or hashes2[:n1] != hashes1:
        _refuse("REGISTRY_CHAIN_HEAD_CHANGED", "DIVERGED")
    if stamp1[4] != stamp2[4]:
        _refuse("REGISTRY_CHAIN_HEAD_CHANGED", "INSTANCE_CHANGED")
    if n2 > n1:
        _refuse("REGISTRY_CHAIN_HEAD_CHANGED", "EXTENDED")


# ── Conversion chaîne → vue de B4 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _convert(chain) -> tuple:
    facts, rebinds = [], 0
    for entry in chain.entries:
        if entry.record_type is RecordType.REBIND:
            rebinds += 1
            continue
        if entry.campaign_id is None or entry.window is None or entry.record_type not in _KINDS:
            _refuse("B4_ASSEMBLY_REFUSED", "FACT_CONSTRUCTION")
        try:
            facts.append(RegistryRecordFact(seq=entry.seq, kind=_KINDS[entry.record_type], campaign_id=entry.campaign_id, content_hash=entry.content_hash,
                                            window_start_utc=entry.window[0], window_end_utc=entry.window[1]))
        except (TypeError, ValueError):
            _refuse("B4_ASSEMBLY_REFUSED", "FACT_CONSTRUCTION")
    if len(facts) + rebinds != chain.next_seq or {f.seq for f in facts} != {e.seq for e in chain.entries if e.record_type is not RecordType.REBIND}:
        _refuse("B4_ASSEMBLY_REFUSED", "FACT_CONSTRUCTION")
    try:
        return RegistryView(registry_id=chain.registry_id, chain_head=chain.head_content_hash, records=tuple(facts)), rebinds
    except (TypeError, ValueError):
        _refuse("B4_ASSEMBLY_REFUSED", "FACT_CONSTRUCTION")


# ── Étage de l'enregistrement propre ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def derive_stage(reg_state: CampaignState, own_claims: tuple, foreign_for_own: tuple, window: tuple, own_campaign_id: str) -> OwnRecordStage:
    """Règles évaluées dans cet ordre, la première qui s'applique décide ; un refus est `STAGE_NOT_DERIVABLE` avec un détail fermé. La table est totale sur (état du registre × {0, 1} enregistrement)."""
    def refuse(detail: str):
        _refuse("STAGE_NOT_DERIVABLE", detail)

    if len(own_claims) > 1:
        refuse("STAGE_RECORD_MULTIPLE")
    own = own_claims[0] if own_claims else None
    if own is not None:
        if own.status is not SourceStatus.RESOLVED or own.campaign_id is None:
            refuse("STAGE_RECORD_UNRESOLVED")
        if own.campaign_id != own_campaign_id:
            refuse("STAGE_RECORD_OTHER_CAMPAIGN")
        if (own.window_start_utc, own.window_end_utc) != window:
            refuse("STAGE_RECORD_WINDOW")
    if foreign_for_own:
        refuse("STAGE_RECORD_OUTSIDE_OWN_ROOT")
    if own is not None and reg_state in (CampaignState.ABSENT, CampaignState.RESERVED):
        refuse("STAGE_RECORD_WITHOUT_PRIOR")
    if own is None and reg_state is CampaignState.CONSUMED:
        refuse("STAGE_CONSUMED_WITHOUT_RECORD")
    table = {(CampaignState.ABSENT, 0): OwnRecordStage.NO_OWN_RECORDS, (CampaignState.RESERVED, 0): OwnRecordStage.RESERVED, (CampaignState.ADMITTED, 0): OwnRecordStage.ADMITTED,
             (CampaignState.ADMITTED, 1): OwnRecordStage.CLAIMED, (CampaignState.CONSUMED, 1): OwnRecordStage.CONSUMED}
    return table[(reg_state, 1 if own is not None else 0)]


def _stage(chain, interpretation, *, own_campaign_id: str, own_label: str, window: tuple) -> OwnRecordStage:
    own_source = f"{interpreters.TAG_CAMPAIGN_CLAIM}:{own_label}/{_CLAIM_FILE}"
    claims = [f for f in interpretation.findings if f.source_kind is SourceKind.FINAL_HOLDOUT_CLAIM]
    own_claims = tuple(f for f in claims if f.source_id == own_source)
    foreign_for_own = tuple(f for f in claims if f.source_id != own_source and f.campaign_id is not None and f.campaign_id == own_campaign_id)
    return derive_stage(chain.campaign_state(own_campaign_id), own_claims, foreign_for_own, window, own_campaign_id)


# ── Racines dérivées et couverture ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _derived_roots(chain_campaigns: frozenset, interpretation, campaign_roots: tuple, own_campaign_id: str, max_json_bytes: int) -> tuple:
    derived = []
    for label, path, expected in campaign_roots:
        if expected == own_campaign_id or expected not in chain_campaigns:
            continue
        if window_sources.plan_root_attributed(interpretation, label=label, root_path=path, expected_name=expected, max_json_bytes=max_json_bytes):
            derived.append((label, expected))
    return tuple(sorted(derived))


def assess(handle, interpretation_s1, *, own_campaign_id: str, window: tuple, campaign_roots: tuple, max_json_bytes: int) -> RegistryAssessment:
    """Conversion, étage, racines dérivées, couverture, comptabilité et assemblage de B4 sur R1 et S1. Retourne des scalaires, des tuples et un diagnostic immuable ; ce dernier est calculé APRÈS B4 et la couverture, hors de tout `except` (une défaillance critique se propage). Après le retour (ou le refus), la poignée libère l'instantané."""
    if type(handle) is not RegistryHandle or handle._state[0] is None:
        raise TypeError("handle doit être une RegistryHandle non consommée")
    snapshot = handle._state[0]
    try:
        chain = snapshot.chain
        view, rebinds = _convert(chain)
        own_label = next((label for label, _path, expected in campaign_roots if expected == own_campaign_id), None)
        if own_label is None:
            _refuse("STAGE_NOT_DERIVABLE", "STAGE_RECORD_OUTSIDE_OWN_ROOT")
        stage = _stage(chain, interpretation_s1, own_campaign_id=own_campaign_id, own_label=own_label, window=window)
        chain_campaigns = frozenset(entry.campaign_id for entry in chain.entries if entry.campaign_id is not None) - {own_campaign_id}
        derived = _derived_roots(chain_campaigns, interpretation_s1, campaign_roots, own_campaign_id, max_json_bytes)
        try:
            assembly = assemble_exposure_inventory(interpretation_s1, registry=view, accounting=AccountingViews(),
                                                   own_context=OwnCampaignContext(current_campaign_id=own_campaign_id, own_record_stage=stage),
                                                   derived_root_labels=tuple(sorted(label for label, _expected in derived)))
        except (TypeError, ValueError):
            _refuse("B4_ASSEMBLY_REFUSED", "ASSEMBLY")
        own_reasons = tuple(sorted(set(assembly.incomplete_reasons) - set(interpretation_s1.incomplete_reasons)))
        if len(own_reasons) > MAX_B4_REASONS:
            _refuse("B4_ASSEMBLY_REFUSED", "ASSEMBLY")
        accounting = assembly.inventory.trial_accounting
        provenance = assembly.accounting_provenance
        counters = tuple(TrialCounter(name, None if getattr(provenance, name) is CounterProvenance.NOT_OBSERVED else getattr(accounting, name), _STATE_OF[getattr(provenance, name)])
                         for name in _COUNTER_NAMES)
        covered = {expected for _label, expected in derived}
        uncovered = sorted(chain_campaigns - covered)
        coverage = RegistryCoverage.PARTIAL if uncovered else RegistryCoverage.ALL_CHAIN_CAMPAIGNS_HAVE_ROOT
        diagnostic = plan_declared.diagnose(interpretation_s1, derived=derived, other_campaign_count=len(chain_campaigns), max_json_bytes=max_json_bytes)          # N2-b2a : après B4 et la couverture, hors de tout `except`
        return RegistryAssessment(
            b4_complete=bool(assembly.inventory.complete), b4_incomplete_reasons=own_reasons, b4_semantics_version=assembly.semantics_version, registry_id=chain.registry_id,
            registry_chain_head=chain.head_content_hash, registry_slot_count=chain.next_seq, registry_rebind_count=rebinds,
            registry_durability_profile=snapshot.identity.durability_profile.value, derived_root_labels=tuple(sorted(label for label, _expected in derived)), registry_coverage=coverage,
            registry_other_campaign_count=len(chain_campaigns), registry_uncovered_count=len(uncovered), registry_uncovered_sample=tuple(uncovered[:MAX_UNCOVERED_SAMPLE]),
            trial_counters=counters, trial_counter_reasons=tuple(provenance.reasons), plan_declared_diagnostic=diagnostic)
    finally:
        handle._state[0] = None
