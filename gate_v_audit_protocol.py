"""
gate_v_audit_protocol.py — N-VIDE-2 / N2-a : noyau du protocole d'audit (DIAGNOSTIC SEUL, lecture seule).

Une seule couture : `audit_campaign_exposure(AuditRequest) -> AuditReport`. La requête ne porte que de la CONFIGURATION de l'opérateur (racines, plafonds, fenêtre) ; elle n'accepte
jamais un scan, un arbre observé, une interprétation, des hooks, des findings ni un verdict. Le protocole exécute lui-même le scanner (B3 v6 → B2), deux fois :

- S1 alimente B3 (raisons d'incomplétude), L3-A (arbre observé, chaîne des runs Walk-Forward, diagnostic des répertoires vides) et les projections ;
- S2 est un appel NOUVEAU, avec des racines reconstruites ; les projections F (faits observés) et I (identité et contexte) de S1 et S2 sont comparées. Deux projections
  égales ne prouvent NI un instantané atomique, NI une chronologie, NI l'absence de modification après S2 : ce n'est pas le rescan indépendant de E3-J.

Le rapport n'accorde rien : aucun statut n'est FRESH, NO_OVERLAP, une autorisation de réservation ou d'admission, un accès au holdout ou un passage de la Gate V. Il n'est pas un
justificatif transportable (aucune API de sérialisation, ni pickle ni copie ; les empreintes F / I sont des champs de diagnostic, pas des justificatifs) : l'aval relance l'audit. En Python, un
objet du même processus reste forgeable : limite de protocole, pas cryptographique. Aucun A0, aucune déclaration, aucun Claim, aucun écrivain de registre, aucun B5 ;
B4 et le registre n'interviennent que par le bloc OPTIONNEL `registry` (N2-b1b : lecture seule, adaptateur interne, trois dimensions distinctes jamais agrégées, aucune écriture). La fenêtre W est celle de l'opérateur, NON revalidée (`UNVERIFIED`). L3-A prouve une cohérence avec les observations fournies, jamais l'exclusion.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import os
import re
from typing import Optional

import gate_v_audit_registry as registry_audit
import gate_v_audit_window as provenance
from gate_v_audit_registry import PlanDeclaredDiagnostic, RegistryConfig, RegistryCoverage, TrialCounter
from gate_v_exposure_interpreters import InterpretedScan, LayoutRoot, RootLayout, SourceInterpretation
from gate_v_exposure_interpreters_v6 import B3_V6_RULES_DIGESTS, B3_V6_SEMANTICS_VERSION, interpret_audit_roots_v6
from gate_v_exposure_scan import AuditRoot, EntryClass, EntryKind, ExposureScan, ExposureScanRefusal, HashLimits, ScanLimits, StructuralFailure, parse_strict_json, scan_worst_case_read_bytes
from gate_v_exposure_sources import normalize_window
import gate_v_k1s2_emptiness as emptiness
import gate_v_k1s2_observations as observations
import gate_v_k1s2_verifier as verifier

__all__ = [
    "AUDIT_B3_ACCEPTED", "AUDIT_PROTOCOL_VERSION", "E3J_PREREQUISITES_UNMET", "MAX_DETAIL_CHARS", "AbsenceEvidence", "AuditBlock", "AuditDefect", "AuditReport", "AuditRequest",
    "AuditRootSpec", "AuxiliaryRuns", "BlockCode", "ChainDefect", "ChainStatus", "Completeness", "ManifestState", "Persistence", "ProtocolLimits", "Receivability", "RefusalCode",
    "RegistryConfig", "RescanStatus", "RootReport", "S0Facts", "Stage", "WindowDeclaredSource", "WindowProvenance", "WindowSource", "audit_campaign_exposure",
]

AUDIT_PROTOCOL_VERSION = "gate_v_audit_protocol_v1"
AUDIT_B3_ACCEPTED = ("gate_v_exposure_interpreters_v6",)        # liste blanche littérale : jamais une comparaison de versions, jamais un nom de version historique
MAX_DETAIL_CHARS = 300

# Ce que l'audit n'a PAS fait (liste reprise des obligations déjà écrites : préconditions, L3-A). Seule exemption du contrôle de vocabulaire : elle NOMME ce qui manque.
E3J_PREREQUISITES_UNMET = ("INDEPENDENT_RESCAN", "CHRONOLOGY_PROOF", "SEAL_ANTERIORITY", "D5_PREDICATE", "S0_RECOMPUTATION", "INVENTORY_CONTENT_DIGEST_RECHECK", "ATTESTATION",
                           "AUTHORIZATION", "COMMITMENT", "RESERVATION_TIME_PROOF", "REGISTRY_CHAIN_STRICT_READ", "ADMISSION_WRITER")
_NOT_PROVEN = verifier.NOT_PROVEN + ("SNAPSHOT_ATOMICITY", "CHRONOLOGY", "INDEPENDENT_RESCAN", "S0_RECOMPUTATION", "PLAN_SOURCES_AUTHENTICITY",   # b1a : le plan V2 n'est pas revalidé contre ses sources
                                     "CAMPAIGNS_OUTSIDE_REGISTRY", "TRIAL_ACCOUNTING", "DERIVED_ROOT_CONTENT_ATTRIBUTION", "REGISTRY_NOT_REAL_BOUND", "STAGE_CONSUMPTION_LINK_UNVERIFIED")   # N2-b1b, constants dans tous les modes

_CAMPAIGN_NAME = re.compile(r"gate_v_v2_[0-9a-f]{64}")
_STATUS_ALIASES = {"READY_FOR_EXECUTION": "INITIAL", "RUNNING": "RUNNING", "TECHNICAL_FAILURE": "TECHNICAL_FAILURE", "EVIDENCE_INCOMPLETE": "EVIDENCE_INCOMPLETE",
                   "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT": "EVIDENCE_COMPLETE"}
_V6_DIGESTS = {layout: digest for _version, layout, digest in B3_V6_RULES_DIGESTS}
_HASHED_LAYOUTS = frozenset({RootLayout.CAMPAIGN_DIR})            # seule disposition dont la table comporte des règles hachées : B3 n'y applique `hash_limits` qu'à elle
_BLOCK_SENTINEL_LABEL = "(registry)"          # ne peut pas heurter un label d'opérateur : les labels portables n'admettent pas de parenthèse
_COUNTER_ORDER = ("research_runs", "strategies", "campaigns", "abandoned_reservations", "failed_ingestion_attempts", "void_commitments")
_MAX_B4_REASONS = 64
_MAX_UNCOVERED_SAMPLE = 20
_CANDIDATE_READS = 3          # lectures du JSON d'une racine candidate (deux gardées autour du chargeur du plan V2, plus la lecture du chargeur lui-même) : majorant TYPIQUE, non imposé (le chargeur lit sans plafond)
_WINDOW_SOURCE_READS = 6          # majorant exact des lectures JSON de la provenance de W : split plan (1), plan (avant, chargeur, après = 3), relecture finale (plan, split plan = 2)


# ── Vocabulaire fermé ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
class Receivability(str, enum.Enum):
    RECEIVABLE = "RECEIVABLE"            # le scan et la requête sont structurellement recevables ; PAS « sain »
    REFUSED = "REFUSED"


class Stage(str, enum.Enum):
    REQUEST = "REQUEST"
    FIRST_SCAN = "FIRST_SCAN"
    OBSERVATION = "OBSERVATION"
    SECOND_SCAN = "SECOND_SCAN"
    WINDOW_SOURCE = "WINDOW_SOURCE"
    REGISTRY = "REGISTRY"
    PROTOCOL = "PROTOCOL"


class RefusalCode(str, enum.Enum):
    REQUEST_INVALID = "REQUEST_INVALID"
    HASH_LIMITS_MISSING = "HASH_LIMITS_MISSING"
    RESOURCE_BUDGET_EXCEEDED = "RESOURCE_BUDGET_EXCEEDED"
    ROOT_FOREIGN = "ROOT_FOREIGN"
    SCAN_STRUCTURAL_FAILURE = "SCAN_STRUCTURAL_FAILURE"
    SCAN_UNSTABLE = "SCAN_UNSTABLE"
    SCAN_HOOKS_PRESENT = "SCAN_HOOKS_PRESENT"
    SCAN_TABLE_MISMATCH = "SCAN_TABLE_MISMATCH"
    SCAN_LIMITS_MISMATCH = "SCAN_LIMITS_MISMATCH"
    SCAN_CONTEXT_MISMATCH = "SCAN_CONTEXT_MISMATCH"
    VERSION_BELOW_MINIMUM = "VERSION_BELOW_MINIMUM"
    OBSERVATION_REFUSED = "OBSERVATION_REFUSED"
    OBSERVATION_PROJECTION_MISMATCH = "OBSERVATION_PROJECTION_MISMATCH"
    RESCAN_NOT_DISTINCT = "RESCAN_NOT_DISTINCT"
    RESCAN_STRUCTURAL_FAILURE = "RESCAN_STRUCTURAL_FAILURE"
    RESCAN_FACT_DRIFT = "RESCAN_FACT_DRIFT"
    RESCAN_IDENTITY_DRIFT = "RESCAN_IDENTITY_DRIFT"
    WINDOW_SOURCE_INVALID = "WINDOW_SOURCE_INVALID"            # plan V2 ou plan de split absent, non strictement observé, mal formé ou refusé par son chargeur
    PLAN_SPLIT_CONTRADICTION = "PLAN_SPLIT_CONTRADICTION"      # campagne, identifiant, snapshot ou empreinte recalculée : désaccord entre le plan V2 et le plan de split
    WINDOW_MISMATCH = "WINDOW_MISMATCH"                        # la fenêtre de l'opérateur diffère de la fenêtre dérivée, ou d'un enregistrement propre du registre : jamais remplacée en silence
    WINDOW_SOURCE_CHANGED = "WINDOW_SOURCE_CHANGED"            # un fichier source ne porte plus les octets observés par le premier scan
    REGISTRY_UNREADABLE = "REGISTRY_UNREADABLE"                # N2-b1b : le registre n'a pas pu être lu de façon sûre (R1 ou R2)
    REGISTRY_CHAIN_HEAD_CHANGED = "REGISTRY_CHAIN_HEAD_CHANGED"  # R2 diffère de R1 : un ajout légitime pendant l'audit invalide l'audit
    STAGE_NOT_DERIVABLE = "STAGE_NOT_DERIVABLE"                # l'étage de l'enregistrement propre n'est pas dérivable des faits
    B4_ASSEMBLY_REFUSED = "B4_ASSEMBLY_REFUSED"                # la conversion ou l'assemblage de B4 est refusé
    AUDIT_INTERNAL_FAILURE = "AUDIT_INTERNAL_FAILURE"


class BlockCode(str, enum.Enum):
    """Blocage SÉMANTIQUE : le scan est recevable mais dit « chaîne incohérente » ou « vide bloquant ». Il bloque toute preuve d'absence future ; il n'est jamais un refus."""

    CHAIN_INCOHERENT = "CHAIN_INCOHERENT"
    EMPTINESS_BLOCKING = "EMPTINESS_BLOCKING"
    DERIVED_COVERAGE_PARTIAL = "DERIVED_COVERAGE_PARTIAL"      # N2-b1b : une campagne de la chaîne n'a pas de racine dérivée ; jamais un refus


class Completeness(str, enum.Enum):
    COMPLETE = "COMPLETE"                # recopie de `complete` de B3 v6 ; PAS une absence d'exposition
    INCOMPLETE = "INCOMPLETE"
    NOT_BUILT = "NOT_BUILT"


class ChainStatus(str, enum.Enum):
    COHERENT = "COHERENT"                # cohérent avec les observations fournies : ni lecture réelle, ni exclusivité, ni antériorité, ni absence d'exposition
    INCOHERENT = "INCOHERENT"
    NOT_EVALUATED = "NOT_EVALUATED"


class ManifestState(str, enum.Enum):
    """`INITIAL` = statut `READY_FOR_EXECUTION` ; `EVIDENCE_COMPLETE` = `EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT` ; les autres noms sont ceux du schéma D2."""

    ABSENT = "ABSENT"
    INITIAL = "INITIAL"
    RUNNING = "RUNNING"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    EVIDENCE_COMPLETE = "EVIDENCE_COMPLETE"
    UNREADABLE_OR_NONCONFORMING = "UNREADABLE_OR_NONCONFORMING"
    FOREIGN = "FOREIGN"


class RescanStatus(str, enum.Enum):
    PROTOCOL_RESCAN_MATCHED = "PROTOCOL_RESCAN_MATCHED"      # stabilité observée sur deux appels : PAS un instantané, PAS une chronologie, PAS le rescan indépendant d'E3-J
    DRIFT = "DRIFT"
    NOT_PERFORMED = "NOT_PERFORMED"


class WindowDeclaredSource(str, enum.Enum):
    """Entrée : seule `OPERATOR_CONFIGURED` est acceptée. `SPLIT_PLAN_REFERENCED` n'existe que dans un RAPPORT, posée par le protocole après une dérivation réussie."""

    OPERATOR_CONFIGURED = "OPERATOR_CONFIGURED"
    SPLIT_PLAN_REFERENCED = "SPLIT_PLAN_REFERENCED"


class WindowProvenance(str, enum.Enum):
    UNVERIFIED = "UNVERIFIED"             # W est configurée par l'opérateur et non revalidée contre le plan V2 et le plan de split
    SPLIT_PLAN_FINGERPRINT_MATCHED = "SPLIT_PLAN_FINGERPRINT_MATCHED"   # métadonnées du plan V2 et du plan de split COHÉRENTES : ni authenticité, ni chronologie, ni absence d'exposition


class AbsenceEvidence(str, enum.Enum):
    UNAVAILABLE = "UNAVAILABLE"


class AuxiliaryRuns(str, enum.Enum):
    UNQUALIFIED = "UNQUALIFIED"


class S0Facts(str, enum.Enum):
    NOT_VERIFIED = "NOT_VERIFIED"


class Persistence(str, enum.Enum):
    NOT_PERSISTED = "NOT_PERSISTED"


# ── Requête : CONFIGURATION seulement (dataclasses ordinaires : un contenu hostile est refusé par l'audit, jamais une exception) ───────────────────
@dataclasses.dataclass(frozen=True, kw_only=True)
class ProtocolLimits:
    """Bornes propres au protocole, EXPLICITES (aucune valeur par défaut) : racines de campagne et budget de lecture total (S1 + S2, toutes dispositions)."""

    max_campaign_roots: int
    max_total_read_bytes: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class AuditRootSpec:
    """Racine d'audit configurée. `expected_name` : nom de dossier attendu d'une racine CAMPAIGN_DIR (la campagne propre ET les campagnes dérivées) ; None pour les autres dispositions."""

    label: str
    path: str
    layout: RootLayout
    expected_name: Optional[str] = None
    may_be_empty: bool = False


@dataclasses.dataclass(frozen=True, kw_only=True)
class WindowSource:
    """Demande de dérivation de W : désigne la racine SPLIT_PLAN_DIR configurée qui porte `split_plan.json`. La racine propre (plan V2) est celle de la campagne propre. Ne REMPLACE
    jamais la fenêtre de l'opérateur : la confronte."""

    split_plan_root_label: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class AuditRequest:
    own_campaign_id: str
    roots: tuple
    limits: ScanLimits
    hash_limits: Optional[HashLimits]
    protocol_limits: ProtocolLimits
    window_start_utc: str
    window_end_utc: str
    window_declared_source: WindowDeclaredSource
    window_source: Optional[WindowSource] = None
    registry: Optional[RegistryConfig] = None          # N2-b1b : lecture d'audit du registre SYNTHÉTIQUE ; None = mode N2-a / N2-b1a inchangé


# ── Rapport ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _clip(text: str) -> str:
    return text if len(text) <= MAX_DETAIL_CHARS else text[:MAX_DETAIL_CHARS - 1] + "…"


@dataclasses.dataclass(frozen=True)
class AuditDefect:
    """Refus structurel : l'audit n'est pas recevable ; aucun statut de couche n'est exposé."""

    code: RefusalCode
    stage: Stage
    root_label: Optional[str] = None
    detail: str = ""

    def __post_init__(self) -> None:
        if type(self.code) is not RefusalCode or type(self.stage) is not Stage or type(self.detail) is not str or len(self.detail) > MAX_DETAIL_CHARS:
            raise ValueError("AuditDefect mal formé")


@dataclasses.dataclass(frozen=True)
class AuditBlock:
    code: BlockCode
    root_label: str
    detail: str = ""

    def __post_init__(self) -> None:
        if type(self.code) is not BlockCode or type(self.root_label) is not str or type(self.detail) is not str or len(self.detail) > MAX_DETAIL_CHARS:
            raise ValueError("AuditBlock mal formé")


@dataclasses.dataclass(frozen=True)
class ChainDefect:
    code: str                  # code L3-A conservé tel quel
    path: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class RootReport:
    """Par racine. Pour une racine non CAMPAIGN_DIR : `manifest_state` et `emptiness_category` valent None, la chaîne est `NOT_EVALUATED`."""

    label: str
    layout: RootLayout
    manifest_state: Optional[ManifestState]
    observed_execution_artefacts: Optional[int]
    chain: ChainStatus
    chain_defects: tuple
    emptiness_category: Optional[str]
    emptiness_reasons: tuple
    empty_directories: tuple


@dataclasses.dataclass(frozen=True)
class AuditReport:
    """Rapport diagnostique. Il n'accorde RIEN. Les champs d'autorité sont des propriétés CONSTANTES (jamais fournies par un constructeur)."""

    receivability: Receivability
    refusals: tuple = ()
    blocks: tuple = ()
    window: Optional[tuple] = None
    window_declared_source: Optional[WindowDeclaredSource] = None
    b3_semantics_version: Optional[str] = None
    b3_completeness: Completeness = Completeness.NOT_BUILT
    incomplete_reasons: tuple = ()
    roots: tuple = ()
    rescan: RescanStatus = RescanStatus.NOT_PERFORMED
    facts_s1: Optional[str] = None
    facts_s2: Optional[str] = None
    identity_s1: Optional[str] = None
    identity_s2: Optional[str] = None
    # N2-b1b : trois dimensions DISTINCTES (b3_completeness, b4_completeness, registry_coverage), jamais agrégées ; vides, None, NOT_BUILT ou NOT_ASSESSED sans registre et pour tout rapport REFUSED.
    b4_completeness: Completeness = Completeness.NOT_BUILT
    b4_incomplete_reasons: tuple = ()
    b4_semantics_version: Optional[str] = None
    registry_id: Optional[str] = None
    registry_chain_head: Optional[str] = None
    registry_slot_count: Optional[int] = None
    registry_rebind_count: Optional[int] = None
    registry_durability_profile: Optional[str] = None
    derived_root_labels: tuple = ()
    registry_coverage: RegistryCoverage = RegistryCoverage.NOT_ASSESSED
    registry_other_campaign_count: Optional[int] = None
    registry_uncovered_count: Optional[int] = None
    registry_uncovered_sample: tuple = ()
    trial_counters: tuple = ()
    trial_counter_reasons: tuple = ()
    # N2-b2a : déclarations des plans V2 des autres campagnes de la chaîne (DIAGNOSTIC descriptif, jamais de la comptabilité) ; `None` sans registre et pour tout rapport REFUSED.
    plan_declared_diagnostic: Optional[PlanDeclaredDiagnostic] = None

    def __post_init__(self) -> None:
        self._check_registry_fields()
        if type(self.receivability) is not Receivability or type(self.refusals) is not tuple or type(self.blocks) is not tuple or type(self.roots) is not tuple:
            raise ValueError("AuditReport mal formé")
        if any(type(d) is not AuditDefect for d in self.refusals) or any(type(b) is not AuditBlock for b in self.blocks) or any(type(r) is not RootReport for r in self.roots):
            raise ValueError("AuditReport mal formé")
        if (self.receivability is Receivability.REFUSED) != bool(self.refusals):
            raise ValueError("REFUSED si et seulement si au moins un refus")
        if self.receivability is Receivability.REFUSED and (self.blocks or self.roots or self.b3_completeness is not Completeness.NOT_BUILT or self.incomplete_reasons):
            raise ValueError("un refus structurel n'expose aucun statut de couche")
        if self.receivability is Receivability.RECEIVABLE and (self.rescan is not RescanStatus.PROTOCOL_RESCAN_MATCHED or self.b3_completeness is Completeness.NOT_BUILT):
            raise ValueError("un audit recevable a terminé B3 et le rescan")
        if (self.b3_completeness is Completeness.COMPLETE) and self.incomplete_reasons:
            raise ValueError("COMPLETE exclut toute raison d'incomplétude")
        if self.window_declared_source is not None and type(self.window_declared_source) is not WindowDeclaredSource:
            raise ValueError("window_declared_source inconnu")
        if self.window_declared_source is WindowDeclaredSource.SPLIT_PLAN_REFERENCED:
            layouts = {r.layout for r in self.roots}
            if self.receivability is not Receivability.RECEIVABLE or self.window is None or self.facts_s1 is None or self.facts_s1 != self.facts_s2                     or self.identity_s1 is None or self.identity_s1 != self.identity_s2 or not {RootLayout.CAMPAIGN_DIR, RootLayout.SPLIT_PLAN_DIR} <= layouts:
                raise ValueError("la source dérivée n'est affirmée que par un audit recevable complet (fenêtre, empreintes S1 = S2, racines de campagne et de plan de split) ; ce n'est pas un justificatif")

    def _check_registry_fields(self) -> None:
        """Invariants (1) à (9) des champs de registre (note N2-b1b, 19.11). Constructeur seulement : un rapport forgé par `object.__new__` reste possible (limite T16)."""
        bad = ValueError("AuditReport : champs de registre incohérents")
        blocks = tuple(b for b in self.blocks if type(b) is AuditBlock) if type(self.blocks) is tuple else ()
        if type(self.b4_completeness) is not Completeness or type(self.registry_coverage) is not RegistryCoverage:
            raise bad
        if any(type(value) is not tuple for value in (self.b4_incomplete_reasons, self.derived_root_labels, self.registry_uncovered_sample, self.trial_counters, self.trial_counter_reasons)):
            raise bad
        empty = (self.registry_id is None and self.registry_chain_head is None and self.registry_slot_count is None and self.registry_rebind_count is None
                 and self.registry_durability_profile is None and self.b4_semantics_version is None and self.registry_other_campaign_count is None
                 and self.registry_uncovered_count is None and not self.b4_incomplete_reasons and not self.derived_root_labels and not self.registry_uncovered_sample
                 and not self.trial_counters and not self.trial_counter_reasons)
        absent = self.registry_id is None
        if not (absent == (self.b4_completeness is Completeness.NOT_BUILT) == (self.registry_coverage is RegistryCoverage.NOT_ASSESSED) == empty):          # (1)
            raise bad
        diagnostic = self.plan_declared_diagnostic
        if (diagnostic is None) != absent or (diagnostic is not None and type(diagnostic) is not PlanDeclaredDiagnostic):                                  # (10) : type exact, avant le retour anticipé
            raise bad
        if absent:
            if any(b.code is BlockCode.DERIVED_COVERAGE_PARTIAL for b in blocks):
                raise bad
            return
        if self.receivability is Receivability.REFUSED:                                                                                                  # (7)
            raise bad
        if any(type(v) is not int or v < 0 for v in (self.registry_slot_count, self.registry_rebind_count, self.registry_other_campaign_count, self.registry_uncovered_count)):
            raise bad
        if any(type(v) is not str or not v for v in (self.registry_id, self.registry_chain_head, self.registry_durability_profile, self.b4_semantics_version)):
            raise bad
        reasons = self.b4_incomplete_reasons
        if any(type(r) is not str for r in reasons) or list(reasons) != sorted(reasons) or len(reasons) > _MAX_B4_REASONS:                                  # (6)
            raise bad
        if self.b4_completeness is Completeness.COMPLETE and (self.b3_completeness is not Completeness.COMPLETE or reasons):                               # (2)
            raise bad
        if self.b4_completeness is Completeness.INCOMPLETE and self.b3_completeness is Completeness.COMPLETE and not reasons:                              # (8)
            raise bad
        partial_block = any(b.code is BlockCode.DERIVED_COVERAGE_PARTIAL for b in blocks)
        partial = self.registry_coverage is RegistryCoverage.PARTIAL
        if not (partial == (self.registry_uncovered_count > 0) == partial_block) or self.registry_uncovered_count > self.registry_other_campaign_count:           # (3)
            raise bad
        sample = self.registry_uncovered_sample
        if any(type(s) is not str for s in sample) or list(sample) != sorted(set(sample)) or len(sample) != min(_MAX_UNCOVERED_SAMPLE, self.registry_uncovered_count):   # (4)
            raise bad
        if len(self.trial_counters) != 6 or any(type(c) is not TrialCounter for c in self.trial_counters) or [c.name for c in self.trial_counters] != list(_COUNTER_ORDER):  # (5)
            raise bad
        if any(type(r) is not str for r in self.trial_counter_reasons) or any(type(label) is not str for label in self.derived_root_labels):
            raise bad
        if len(self.derived_root_labels) + self.registry_uncovered_count != self.registry_other_campaign_count:                                              # (9)
            raise bad
        if diagnostic.source_campaign_count + diagnostic.unavailable_campaign_count != self.registry_other_campaign_count:                                  # (11)
            raise bad
        if diagnostic.source_campaign_count > len(self.derived_root_labels) or dict(diagnostic.unavailable_breakdown).get("NO_ATTRIBUTED_ROOT", 0) != self.registry_uncovered_count:   # (12)
            raise bad

    def __reduce__(self):
        raise TypeError("AuditReport n'est pas un justificatif transportable : ni sérialisation, ni copie")

    @property
    def protocol_version(self) -> str:
        return AUDIT_PROTOCOL_VERSION

    @property
    def window_provenance(self) -> WindowProvenance:
        """Propriété DÉRIVÉE de `window_declared_source` (jamais un champ, jamais une entrée) : cohérence de métadonnées, pas une authenticité."""
        if self.window_declared_source is WindowDeclaredSource.SPLIT_PLAN_REFERENCED:
            return WindowProvenance.SPLIT_PLAN_FINGERPRINT_MATCHED
        return WindowProvenance.UNVERIFIED

    @property
    def b4_inventory(self) -> Completeness:
        """Alias en lecture seule de `b4_completeness` (NOT_BUILT sans registre)."""
        return self.b4_completeness

    @property
    def absence_evidence(self) -> AbsenceEvidence:
        return AbsenceEvidence.UNAVAILABLE

    @property
    def auxiliary_runs(self) -> AuxiliaryRuns:
        return AuxiliaryRuns.UNQUALIFIED

    @property
    def s0_facts(self) -> S0Facts:
        return S0Facts.NOT_VERIFIED

    @property
    def persistence(self) -> Persistence:
        return Persistence.NOT_PERSISTED

    @property
    def independent_rescan_required(self) -> bool:
        return True

    @property
    def e3j_prerequisites_unmet(self) -> tuple:
        return E3J_PREREQUISITES_UNMET

    @property
    def not_proven(self) -> tuple:
        return _NOT_PROVEN

    @property
    def grants(self) -> tuple:
        return ()

    @property
    def grants_nothing(self) -> bool:
        return not self.grants


def _refused(defects, *, window=None, facts=(None, None, None, None), rescan=RescanStatus.NOT_PERFORMED, source=None) -> AuditReport:
    return AuditReport(Receivability.REFUSED, refusals=tuple(defects), window=window, window_declared_source=source, rescan=rescan,
                       facts_s1=facts[0], facts_s2=facts[1], identity_s1=facts[2], identity_s2=facts[3])


def _defect(code: RefusalCode, stage: Stage, detail: str = "", label: Optional[str] = None) -> AuditDefect:
    return AuditDefect(code, stage, label, _clip(detail))


# ── Validation de la requête (mémoire seule : aucun accès disque) ────────────────────────────────────────────────────────────────────────────────
def _is_positive_int(value) -> bool:
    return type(value) is int and value > 0


def _rebuild_limits(limits, hash_limits) -> Optional[str]:
    """Reconstruit les objets de plafonds par leurs constructeurs : un objet forgé (contourne `__post_init__`) est rejeté ici."""
    try:
        ScanLimits(**{f.name: getattr(limits, f.name) for f in dataclasses.fields(ScanLimits)})
        if hash_limits is not None:
            HashLimits(**{f.name: getattr(hash_limits, f.name) for f in dataclasses.fields(HashLimits)})
    except (TypeError, ValueError, AttributeError) as error:
        return f"plafonds incohérents : {type(error).__name__}"
    return None


def _validate(request) -> tuple:
    """(défauts, racines B2 construites, fenêtre normalisée). Aucune lecture du disque."""
    if type(request) is not AuditRequest:
        return [_defect(RefusalCode.REQUEST_INVALID, Stage.REQUEST, "la requête doit être exactement un AuditRequest")], (), None
    problems = []

    def bad(detail: str, label: Optional[str] = None) -> None:
        problems.append(_defect(RefusalCode.REQUEST_INVALID, Stage.REQUEST, detail, label))

    if type(request.own_campaign_id) is not str:
        bad("own_campaign_id doit être un texte")
    if type(request.limits) is not ScanLimits:
        bad("limits doit être un ScanLimits")
    if request.hash_limits is None:
        problems.append(_defect(RefusalCode.HASH_LIMITS_MISSING, Stage.REQUEST, "hash_limits est obligatoire : aucun plafond haché par défaut"))
    elif type(request.hash_limits) is not HashLimits:
        bad("hash_limits doit être un HashLimits")
    if type(request.limits) is ScanLimits and (request.hash_limits is None or type(request.hash_limits) is HashLimits):
        detail = _rebuild_limits(request.limits, request.hash_limits)
        if detail is not None:
            bad(detail)
    limits_ok = type(request.protocol_limits) is ProtocolLimits and _is_positive_int(request.protocol_limits.max_campaign_roots) \
        and _is_positive_int(request.protocol_limits.max_total_read_bytes)
    if not limits_ok:
        bad("protocol_limits doit être un ProtocolLimits d'entiers strictement positifs")
    if request.window_declared_source is not WindowDeclaredSource.OPERATOR_CONFIGURED:
        bad("window_declared_source : seule OPERATOR_CONFIGURED est acceptée en entrée (la source dérivée est posée par le protocole)")
    window = None
    try:
        window = normalize_window(request.window_start_utc, request.window_end_utc)
    except (TypeError, ValueError) as error:
        bad(f"fenêtre invalide : {type(error).__name__}")
    roots, specs = [], []
    if type(request.roots) is not tuple or not request.roots:
        bad("roots doit être un tuple non vide")
    else:
        for spec in request.roots:
            if type(spec) is not AuditRootSpec:
                bad("chaque racine doit être exactement un AuditRootSpec")
                continue
            built = _build_root(spec, bad)
            if built is not None:
                roots.append(built)
                specs.append(spec)
        labels = [spec.label for spec in specs]
        if len(set(labels)) != len(labels):
            bad("deux racines portent le même label")
    source = request.window_source
    if source is not None and (type(source) is not WindowSource or type(source.split_plan_root_label) is not str
                               or not any(spec.label == source.split_plan_root_label and spec.layout is RootLayout.SPLIT_PLAN_DIR for spec in specs)):
        bad("window_source : un WindowSource exact désignant le label d'une racine SPLIT_PLAN_DIR configurée est attendu")
    registry_part = 0
    if request.registry is not None:
        try:
            registry_part = registry_audit.validate_config(request.registry, audit_root_paths=tuple(root.path for root in roots))
        except registry_audit.RegistryAuditRefused as error:
            problems.append(_registry_defect(error))
    if problems:
        return problems, (), window
    campaign = [(spec, root) for spec, root in zip(specs, roots) if spec.layout is RootLayout.CAMPAIGN_DIR]
    names = [spec.expected_name for spec, _ in campaign]
    if len(set(names)) != len(names):
        return [_defect(RefusalCode.REQUEST_INVALID, Stage.REQUEST, "deux racines CAMPAIGN_DIR portent le même expected_name")], (), window
    if not any(spec.expected_name == request.own_campaign_id for spec, _ in campaign):
        return [_defect(RefusalCode.REQUEST_INVALID, Stage.REQUEST, "aucune racine CAMPAIGN_DIR ne porte la campagne propre (expected_name == own_campaign_id)")], (), window
    if limits_ok and len(campaign) > request.protocol_limits.max_campaign_roots:
        return [_defect(RefusalCode.RESOURCE_BUDGET_EXCEEDED, Stage.REQUEST, "trop de racines de campagne")], (), window
    foreign = [spec.label for spec, root in campaign if os.path.basename(root.path) != spec.expected_name]
    if foreign:
        return [_defect(RefusalCode.ROOT_FOREIGN, Stage.REQUEST, "le dossier de la racine n'a pas le nom attendu", label) for label in foreign], (), window
    groups = {spec.layout for spec in specs}
    extra = _WINDOW_SOURCE_READS * request.limits.max_json_bytes if request.window_source is not None else 0
    if request.registry is not None:
        # part registre (R1 + R2) puis lectures des plans des racines candidates (toutes les racines CAMPAIGN_DIR NON propres, comptées avant tout accès disque)
        extra += registry_part + _CANDIDATE_READS * request.limits.max_json_bytes * (len(campaign) - 1)
    if limits_ok and request.hash_limits is not None and 2 * len(groups) * scan_worst_case_read_bytes(request.limits, request.hash_limits) + extra > request.protocol_limits.max_total_read_bytes:
        if request.registry is not None:
            return [_defect(RefusalCode.RESOURCE_BUDGET_EXCEEDED, Stage.REQUEST, "REGISTRY_BUDGET")], (), window
        return [_defect(RefusalCode.RESOURCE_BUDGET_EXCEEDED, Stage.REQUEST, "le majorant de lecture (S1 + S2, par disposition) dépasse le budget")], (), window
    return [], tuple(zip(specs, roots)), window


def _build_root(spec: AuditRootSpec, bad) -> Optional[AuditRoot]:
    if type(spec.layout) is not RootLayout:
        bad("layout doit être un RootLayout", spec.label if type(spec.label) is str else None)
        return None
    if spec.layout is RootLayout.CAMPAIGN_DIR:
        if type(spec.expected_name) is not str or _CAMPAIGN_NAME.fullmatch(spec.expected_name) is None:
            bad("expected_name d'une racine CAMPAIGN_DIR : gate_v_v2_<64 hexadécimaux> attendu", spec.label if type(spec.label) is str else None)
            return None
    elif spec.expected_name is not None:
        bad("expected_name n'a de sens que pour une racine CAMPAIGN_DIR", spec.label if type(spec.label) is str else None)
        return None
    try:
        return AuditRoot(spec.label, spec.path, spec.may_be_empty)
    except (TypeError, ValueError) as error:
        bad(f"racine invalide : {type(error).__name__}", spec.label if type(spec.label) is str else None)
        return None


def _layout_roots(pairs) -> tuple:
    """Objets de racines NEUFS à chaque passe : aucun objet de S1 n'est réutilisé par S2."""
    return tuple(LayoutRoot(spec.layout, AuditRoot(root.label, root.path, root.may_be_empty)) for spec, root in pairs)


# ── Admissibilité de ce que l'interpréteur renvoie (défensive) ───────────────────────────────────────────────────────────────────────────────────
def _normal(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _check_interpretation(interpretation, request, pairs, window, stage: Stage) -> list:
    def fail(code: RefusalCode, detail: str, label: Optional[str] = None) -> list:
        return [_defect(code, stage, detail, label)]

    if type(interpretation) is not SourceInterpretation or type(interpretation.scans) is not tuple:
        return fail(RefusalCode.SCAN_CONTEXT_MISMATCH, "l'interprétation n'est pas un SourceInterpretation")
    if interpretation.semantics_version not in AUDIT_B3_ACCEPTED:
        return fail(RefusalCode.VERSION_BELOW_MINIMUM, f"version B3 non admise : {interpretation.semantics_version!r}")
    if (interpretation.holdout_window_start_utc, interpretation.holdout_window_end_utc) != window:
        return fail(RefusalCode.SCAN_CONTEXT_MISMATCH, "la fenêtre de l'interprétation diffère de la requête")
    if any(type(item) is not InterpretedScan or type(item.scan) is not ExposureScan for item in interpretation.scans):
        return fail(RefusalCode.SCAN_CONTEXT_MISMATCH, "scan mal typé")
    expected = {}
    for spec, root in pairs:
        expected.setdefault(spec.layout, {})[root.label] = (_normal(root.path), root.may_be_empty)
    if [item.layout for item in interpretation.scans] != [layout for layout in RootLayout if layout in expected]:
        return fail(RefusalCode.ROOT_FOREIGN, "dispositions scannées différentes des dispositions configurées")
    for spec, root in pairs:
        if spec.layout is RootLayout.CAMPAIGN_DIR and os.path.basename(os.path.realpath(root.path)) != spec.expected_name:
            return fail(RefusalCode.ROOT_FOREIGN, "le nom réel du dossier sur disque diffère de expected_name", root.label)
    for item in interpretation.scans:
        scanned = item.scan
        if scanned.hooks_used:
            return fail(RefusalCode.SCAN_HOOKS_PRESENT, "un scan avec hooks n'a aucune autorité")
        digest = _V6_DIGESTS.get(item.layout)
        if scanned.rules_digest != digest or (item.layout is RootLayout.CAMPAIGN_DIR and scanned.rules_digest != verifier.TABLE_DIGEST):
            return fail(RefusalCode.SCAN_TABLE_MISMATCH, f"rules_digest inattendu pour {item.layout.value}")
        hashed = request.hash_limits if item.layout in _HASHED_LAYOUTS else None
        if scanned.limits != request.limits or scanned.hash_limits != hashed:
            return fail(RefusalCode.SCAN_LIMITS_MISMATCH, f"plafonds appliqués différents de la requête pour {item.layout.value}")
        got = {root.label: (_normal(root.path), root.may_be_empty) for root in scanned.roots}
        if got != expected[item.layout] or len(scanned.roots) != len(expected[item.layout]):
            return fail(RefusalCode.ROOT_FOREIGN, f"racines scannées différentes des racines configurées ({item.layout.value})")
    return []


# ── Projections F (faits observés) et I (identité et contexte) ───────────────────────────────────────────────────────────────────────────────────
def _is_content_entry(observation) -> bool:
    cls = observation.entry_class
    return observation.kind is EntryKind.FILE and cls is not None and (cls.is_read or cls.is_hashed)


def _fact_rows(interpretation) -> list:
    rows = []
    for item in interpretation.scans:
        for o in item.scan.observations:
            row = [item.layout.value, o.root_label, o.relative_path, o.kind.value, o.entry_class.value if o.entry_class is not None else None,
                   o.anomaly.value if o.anomaly is not None else None, o.rule_tag, o.value_parsed]
            if _is_content_entry(o):          # même périmètre que la double passe de B2 : seuls les fichiers lus ou hachés portent taille et hash
                row += [o.size, o.content_hash]
            rows.append(row)
    return sorted(rows, key=lambda row: (row[0], row[1], row[2]))


def _identity_rows(interpretation) -> list:
    rows = []
    for item in interpretation.scans:
        for o in item.scan.observations:
            if _is_content_entry(o):
                rows.append([item.layout.value, o.root_label, o.relative_path, o.mtime_ns, o.st_ino, o.st_dev])
    return sorted(rows, key=lambda row: (row[0], row[1], row[2]))


def _facts(interpretation) -> dict:
    return {"complete": interpretation.complete, "reasons": list(interpretation.incomplete_reasons),
            "findings": sorted(f.source_id for f in interpretation.findings), "observations": _fact_rows(interpretation)}


def _identity(interpretation) -> dict:
    scans = []
    for item in interpretation.scans:
        s = item.scan
        scans.append({"layout": item.layout.value, "rules_digest": s.rules_digest, "hooks_used": s.hooks_used,
                      "limits": dataclasses.asdict(s.limits), "hash_limits": dataclasses.asdict(s.hash_limits) if s.hash_limits is not None else None,
                      "roots": sorted([r.label, r.path, r.st_dev, r.st_ino, r.may_be_empty] for r in s.roots)})
    return {"semantics_version": interpretation.semantics_version, "window": [interpretation.holdout_window_start_utc, interpretation.holdout_window_end_utc],
            "window_provenance": WindowProvenance.UNVERIFIED.value, "window_declared_source": WindowDeclaredSource.OPERATOR_CONFIGURED.value,   # décrit le SCAN (fenêtre fournie à B3), pas la provenance
            "protocol_version": AUDIT_PROTOCOL_VERSION, "scans": scans, "files": _identity_rows(interpretation)}


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def _first_difference(first: dict, second: dict) -> str:
    left = {(row[1], row[2]): row for row in first["observations"]}
    right = {(row[1], row[2]): row for row in second["observations"]}
    for key in sorted(set(left) | set(right)):
        if left.get(key) != right.get(key):
            return f"{key[0]}:{key[1]}"
    return "(contexte)"


# ── L3-A par racine de campagne ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
_EXECUTION_PREFIXES = ("validations/", "walk_forward/")


def _expected_kind(o) -> "verifier.ObservedKind":
    """Nature attendue d'une observation, recalculée à part de l'adaptateur de L3-A : une entrée inconnue ou en anomalie n'est jamais rétrogradée en `INERT`."""
    kinds = verifier.ObservedKind
    if o.entry_class is None:
        return kinds.UNKNOWN
    if o.anomaly is not None:
        return kinds.ANOMALY
    if o.entry_class is EntryClass.TEMP_ORPHAN_FILE:
        return kinds.ORPHAN
    if o.kind is EntryKind.DIRECTORY:
        return kinds.DIRECTORY
    return kinds.INERT if o.content_hash is None or o.size is None else kinds.FILE


def _tree_matches_scan(tree, scan: ExposureScan, label: str) -> bool:
    """Projection recalculée à part depuis le scan : mêmes chemins, mêmes natures attendues, mêmes tailles et SHA-256 de fichiers propres."""
    source = {o.relative_path: o for o in scan.observations if o.root_label == label}
    if len(source) != len(tree.items) or {item.path for item in tree.items} != set(source):
        return False
    for item in tree.items:
        o = source[item.path]
        if item.kind is not _expected_kind(o):
            return False
        if item.kind is verifier.ObservedKind.FILE and (item.sha256 != o.content_hash or item.size != o.size):
            return False
    return True


def _manifest_state(tree, diagnostic) -> ManifestState:
    item = next((i for i in tree.items if i.path == "manifest.json"), None)
    if item is None:
        return ManifestState.ABSENT
    reasons = set(diagnostic.reasons)
    if diagnostic.category is emptiness.EmptinessCategory.BAD_INPUT:
        return ManifestState.UNREADABLE_OR_NONCONFORMING
    if emptiness.EmptinessReason.FOREIGN_MANIFEST in reasons:
        return ManifestState.FOREIGN
    if emptiness.EmptinessReason.MANIFEST_UNREADABLE in reasons or emptiness.EmptinessReason.MANIFEST_NOT_CONFORMING in reasons or item.content is None:
        return ManifestState.UNREADABLE_OR_NONCONFORMING
    try:
        record = parse_strict_json(item.content, max_bytes=verifier.MAX_CONTENT_BYTES, max_depth=64)
        alias = _STATUS_ALIASES.get(record.get("status")) if type(record) is dict else None
    except Exception:                                          # noqa: BLE001 — voie conservatrice : jamais un statut inventé
        alias = None
    return ManifestState(alias) if alias is not None else ManifestState.UNREADABLE_OR_NONCONFORMING


def _campaign_report(spec: AuditRootSpec, root: AuditRoot, interpretation) -> tuple:
    """(RootReport, blocs) ou lève `observations.ObservationRefused` / `_ProjectionMismatch`."""
    item = next(i for i in interpretation.scans if i.layout is RootLayout.CAMPAIGN_DIR)
    tree = observations.observed_tree_from_scan(item.scan, root_label=root.label, campaign_dir_name=spec.expected_name)
    if not _tree_matches_scan(tree, item.scan, root.label):
        raise _ProjectionMismatch(root.label)
    diagnostic = emptiness.diagnose_emptiness(tree)
    execution = [i for i in tree.items if i.path.startswith(_EXECUTION_PREFIXES)]
    blocks = []
    if execution or diagnostic.declared_run_id is not None:
        verification = verifier.verify_run_chain(tree, f"{spec.expected_name}_walk_forward")
        defects = tuple(ChainDefect(d.code.value, d.path) for d in verification.defects)
        chain = ChainStatus.INCOHERENT if verification.defects else ChainStatus.COHERENT
    else:
        defects, chain = (), ChainStatus.NOT_EVALUATED
    if chain is ChainStatus.INCOHERENT:
        blocks.append(AuditBlock(BlockCode.CHAIN_INCOHERENT, root.label, _clip(",".join(sorted({d.code for d in defects})))))
    if diagnostic.absence_consideration_blocked:
        blocks.append(AuditBlock(BlockCode.EMPTINESS_BLOCKING, root.label, diagnostic.category.value))
    report = RootReport(root.label, RootLayout.CAMPAIGN_DIR, _manifest_state(tree, diagnostic), len(execution), chain, defects, diagnostic.category.value,
                        tuple(sorted(r.value for r in diagnostic.reasons)), tuple(diagnostic.empty_directories))
    return report, blocks


class _ProjectionMismatch(Exception):
    def __init__(self, label: str) -> None:
        super().__init__(label)
        self.label = label


# ── Orchestration ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _scan_refusal(error: ExposureScanRefusal, stage: Stage, unstable_code: Optional[RefusalCode], structural_code: RefusalCode) -> AuditDefect:
    code = unstable_code if error.failure is StructuralFailure.UNSTABLE_LISTING and unstable_code is not None else structural_code
    return _defect(code, stage, f"{error.failure.value}: {error.detail}", error.root_label)


def _distinct(first, second) -> bool:
    if first is second or first.scans is second.scans:
        return False
    return all(a is not b and a.scan is not b.scan and (not a.scan.observations or a.scan.observations is not b.scan.observations) for a in first.scans for b in second.scans)


_PROVENANCE_CODES = {provenance.WindowFailure.INVALID: RefusalCode.WINDOW_SOURCE_INVALID, provenance.WindowFailure.CONTRADICTION: RefusalCode.PLAN_SPLIT_CONTRADICTION,
                     provenance.WindowFailure.CHANGED: RefusalCode.WINDOW_SOURCE_CHANGED}


def _provenance_defect(error) -> AuditDefect:
    return _defect(_PROVENANCE_CODES[error.failure], Stage.WINDOW_SOURCE, error.detail)


def _registry_defect(error) -> AuditDefect:
    """Conversion par table d'un refus de l'adaptateur (chaîne d'un ensemble fermé) en refus typé du protocole : `REQUEST_INVALID` reste une erreur de requête, les autres portent `Stage.REGISTRY`."""
    code = RefusalCode(error.code)
    return _defect(code, Stage.REQUEST if code is RefusalCode.REQUEST_INVALID else Stage.REGISTRY, error.detail)


def _campaign_roots(pairs) -> tuple:
    return tuple((root.label, root.path, spec.expected_name) for spec, root in pairs if spec.layout is RootLayout.CAMPAIGN_DIR)


def _window_paths(request, pairs) -> tuple:
    """(racine propre, racine du plan de split) : chemins et labels des racines CONFIGURÉES, jamais déduits du disque."""
    own = next(root for spec, root in pairs if spec.layout is RootLayout.CAMPAIGN_DIR and spec.expected_name == request.own_campaign_id)
    split = next(root for spec, root in pairs if spec.layout is RootLayout.SPLIT_PLAN_DIR and spec.label == request.window_source.split_plan_root_label)
    return own, split


def _derive(request, pairs, first, window) -> tuple:
    """(fenêtre dérivée, None) ou (None, refus). La fenêtre de l'opérateur n'est jamais remplacée : un désaccord est un refus."""
    own, split = _window_paths(request, pairs)
    try:
        derived = provenance.derive_window(first, own_label=own.label, split_label=split.label, own_root_path=own.path, split_root_path=split.path,
                                           own_campaign_id=request.own_campaign_id, max_json_bytes=request.limits.max_json_bytes)
    except provenance.WindowSourceRefused as error:
        return None, _provenance_defect(error)
    if derived.window != window:
        return None, _defect(RefusalCode.WINDOW_MISMATCH, Stage.WINDOW_SOURCE, "la fenêtre de l'opérateur diffère de la frontière final_holdout du plan de split")
    return derived, None


def _audit(request) -> AuditReport:
    problems, pairs, window = _validate(request)
    if problems:
        return _refused(problems, window=window)
    source = request.window_declared_source
    handle = None
    if request.registry is not None:                                 # R1 : avant tout scan ; échec ou fenêtre propre incohérente ⇒ refus typé immédiat
        try:
            handle = registry_audit.read(request.registry, own_campaign_id=request.own_campaign_id, window=window)
        except registry_audit.RegistryAuditRefused as error:
            return _refused([_registry_defect(error)], window=window, source=source)
    roots = _layout_roots(pairs)
    try:
        first = interpret_audit_roots_v6(roots, request.limits, hash_limits=request.hash_limits, holdout_window_start_utc=window[0], holdout_window_end_utc=window[1])
    except ExposureScanRefusal as error:
        return _refused([_scan_refusal(error, Stage.FIRST_SCAN, RefusalCode.SCAN_UNSTABLE, RefusalCode.SCAN_STRUCTURAL_FAILURE)], window=window, source=source)
    problems = _check_interpretation(first, request, pairs, window, Stage.FIRST_SCAN)
    if problems:
        return _refused(problems, window=window, source=source)
    derived = None
    if request.window_source is not None:
        derived, refusal = _derive(request, pairs, first, window)
        if refusal is not None:
            return _refused([refusal], window=window, source=source)
    reports, blocks = {}, []
    for spec, root in pairs:
        if spec.layout is RootLayout.CAMPAIGN_DIR:
            try:
                reports[root.label], more = _campaign_report(spec, root, first)
            except verifier.ObservationRefused as error:
                return _refused([_defect(RefusalCode.OBSERVATION_REFUSED, Stage.OBSERVATION, f"{error.code.value}: {error.detail}", root.label)], window=window, source=source)
            except _ProjectionMismatch as error:
                return _refused([_defect(RefusalCode.OBSERVATION_PROJECTION_MISMATCH, Stage.OBSERVATION, "l'arbre observé diffère de la projection du scan", error.label)],
                                window=window, source=source)
            blocks.extend(more)
        else:
            reports[root.label] = RootReport(root.label, spec.layout, None, None, ChainStatus.NOT_EVALUATED, (), None, (), ())
    assessment = None
    if handle is not None:                                           # conversion, étage, racines dérivées, couverture, comptabilité, B4 : sur R1 et S1, avant S2
        try:
            assessment = registry_audit.assess(handle, first, own_campaign_id=request.own_campaign_id, window=window, campaign_roots=_campaign_roots(pairs),
                                               max_json_bytes=request.limits.max_json_bytes)
        except registry_audit.RegistryAuditRefused as error:
            return _refused([_registry_defect(error)], window=window, source=source)
    facts_1, identity_1 = _facts(first), _identity(first)
    try:
        second = interpret_audit_roots_v6(_layout_roots(pairs), request.limits, hash_limits=request.hash_limits, holdout_window_start_utc=window[0],
                                          holdout_window_end_utc=window[1])
    except ExposureScanRefusal as error:
        return _refused([_scan_refusal(error, Stage.SECOND_SCAN, None, RefusalCode.RESCAN_STRUCTURAL_FAILURE)], window=window, source=source)
    problems = _check_interpretation(second, request, pairs, window, Stage.SECOND_SCAN)
    if problems:
        return _refused(problems, window=window, source=source)
    if not _distinct(first, second):
        return _refused([_defect(RefusalCode.RESCAN_NOT_DISTINCT, Stage.SECOND_SCAN, "S2 réutilise un objet de S1 : un second appel frais est exigé")], window=window, source=source)
    facts_2, identity_2 = _facts(second), _identity(second)
    digests = (_digest(facts_1), _digest(facts_2), _digest(identity_1), _digest(identity_2))
    if digests[0] != digests[1]:
        return _refused([_defect(RefusalCode.RESCAN_FACT_DRIFT, Stage.SECOND_SCAN, f"premier écart : {_first_difference(facts_1, facts_2)}")], window=window, source=source,
                        facts=digests, rescan=RescanStatus.DRIFT)
    if digests[2] != digests[3]:
        return _refused([_defect(RefusalCode.RESCAN_IDENTITY_DRIFT, Stage.SECOND_SCAN, "identité ou contexte différents entre S1 et S2 (fichier retouché, racine remplacée)")],
                        window=window, source=source, facts=digests, rescan=RescanStatus.DRIFT)
    if derived is not None:
        own, split = _window_paths(request, pairs)
        try:
            provenance.recheck_sources(derived, own_root_path=own.path, split_root_path=split.path, max_json_bytes=request.limits.max_json_bytes)
        except provenance.WindowSourceRefused as error:
            return _refused([_provenance_defect(error)], window=window, source=source, facts=digests, rescan=RescanStatus.PROTOCOL_RESCAN_MATCHED)
    if handle is not None:                                           # R2 : après la relecture finale de la fenêtre ; la source de la fenêtre de l'opérateur est conservée en cas de refus
        try:
            registry_audit.compare(handle, request.registry)
        except registry_audit.RegistryAuditRefused as error:
            return _refused([_registry_defect(error)], window=window, source=source, facts=digests, rescan=RescanStatus.PROTOCOL_RESCAN_MATCHED)
    if derived is not None:
        source = WindowDeclaredSource.SPLIT_PLAN_REFERENCED
    ordered = tuple(reports[root.label] for _spec, root in pairs)
    registry_fields = {}
    if assessment is not None:
        registry_fields = dict(
            b4_completeness=Completeness.COMPLETE if assessment.b4_complete else Completeness.INCOMPLETE, b4_incomplete_reasons=assessment.b4_incomplete_reasons,
            b4_semantics_version=assessment.b4_semantics_version, registry_id=assessment.registry_id, registry_chain_head=assessment.registry_chain_head,
            registry_slot_count=assessment.registry_slot_count, registry_rebind_count=assessment.registry_rebind_count,
            registry_durability_profile=assessment.registry_durability_profile, derived_root_labels=assessment.derived_root_labels, registry_coverage=assessment.registry_coverage,
            registry_other_campaign_count=assessment.registry_other_campaign_count, registry_uncovered_count=assessment.registry_uncovered_count,
            registry_uncovered_sample=assessment.registry_uncovered_sample, trial_counters=assessment.trial_counters, trial_counter_reasons=assessment.trial_counter_reasons,
            plan_declared_diagnostic=assessment.plan_declared_diagnostic)
        if assessment.registry_coverage is RegistryCoverage.PARTIAL:
            blocks.append(AuditBlock(BlockCode.DERIVED_COVERAGE_PARTIAL, _BLOCK_SENTINEL_LABEL, _clip(f"UNCOVERED:{assessment.registry_uncovered_count}/{assessment.registry_other_campaign_count}")))
    return AuditReport(Receivability.RECEIVABLE, blocks=tuple(blocks), window=window, window_declared_source=source, b3_semantics_version=first.semantics_version,
                       b3_completeness=Completeness.COMPLETE if first.complete else Completeness.INCOMPLETE, incomplete_reasons=tuple(first.incomplete_reasons), roots=ordered,
                       rescan=RescanStatus.PROTOCOL_RESCAN_MATCHED, facts_s1=digests[0], facts_s2=digests[1], identity_s1=digests[2], identity_s2=digests[3], **registry_fields)


def audit_campaign_exposure(request) -> AuditReport:
    """Point d'entrée UNIQUE, total et sans écriture : une requête hostile ou une défaillance inattendue donne un rapport REFUSED typé, jamais une exception ni un résultat partiel.
    Les `BaseException` (interruption, arrêt) se propagent telles quelles : aucune écriture n'est à défaire. Aucune nouvelle tentative, aucun repli sur S1 seul."""
    try:
        return _audit(request)
    except Exception as error:                                   # noqa: BLE001 — fermé : tout chemin imprévu est un refus typé
        return _refused([_defect(RefusalCode.AUDIT_INTERNAL_FAILURE, Stage.PROTOCOL, type(error).__name__)])
