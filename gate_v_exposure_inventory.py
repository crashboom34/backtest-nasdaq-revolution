"""
gate_v_exposure_inventory.py — AF-V-07 Slice E3-B4 : assemblage de l'`ExposureInventory` et comptabilité des essais.

Contrat normatif : ADR 0025 Décision 23, 23.11 étape 1 et « Comptabilité des essais », 23.27.1 à 23.27.6, 23.29.5 (provenance des
compteurs), 23.30 ; design E3-B (AI_HANDOFF.md §44.1, §45) ; préconditions B3/B4 (§47, §51.4).

Module PUR : aucune entrée/sortie, aucune horloge, aucun état global mutable. Il ASSEMBLE ce que B3 a établi (`SourceInterpretation`)
et ce que des vues injectées déclarent (registre, clôtures, ingestion, engagements nuls, essais) ; il ne scanne pas, ne lit aucun
fichier et ne reclasse rien. Toute classification, identité et règle d'absorption reste à E3-A (`build_exposure_inventory`,
`compute_*`, `partition_own_records`).

Garanties :
- les findings de B3 sont repris TELS QUELS ; l'incomplétude de B3 est conservée mot pour mot et ne peut qu'être élargie ici ;
- la comptabilité (six compteurs) n'entre dans aucune formule d'identité sauf `inventory_content_digest` (E3-A) ; sa provenance
  (`OBSERVED` / `PARTIAL` / `NOT_OBSERVED`, 23.29.5) n'entre dans AUCUNE formule d'E3-A ;
- un zéro de remplacement (`NOT_OBSERVED`) n'est jamais un zéro vérifié ;
- ni `non_oos_validations` ni `exposure_evidence` de B3 ne servent à compter : ils sont transmis tels quels (B5 les persistera).

Contrat de la couche d'adaptation (D1) :
- B4 reçoit des identités OPAQUES (chaînes) par des vues (`CampaignTrials`, `TrialItem`, `ClosingView`, `RegistryView`). Il les compare par
  égalité EXACTE, sans normalisation, et ne lit aucun artefact. Deux chaînes identiques sont la MÊME identité : elles sont fusionnées, y compris
  entre campagnes ; deux chaînes différentes ne le sont jamais. B4 n'a donc aucune défense propre contre un identifiant réutilisé pour deux
  évaluations distinctes : la garantie (d) ci-dessous incombe entièrement à la couche d'adaptation.
- Les vues sont alimentées par une couche d'adaptation (E3-D/E3-J ou tranche dédiée), qui DOIT : (a) ne reprendre un `research_run_id` existant
  (`ResearchRun`, `ValidationRun.research_run_id`) que lorsque son attribution à la campagne est PROUVÉE par un lien d'artefact vérifié ;
  (b) ne jamais déduire une identité d'un nom de fichier ou de dossier ; (c) vérifier la configuration de stratégie effectivement évaluée
  (identité de configuration de stratégie évaluée) ; (d) garantir qu'une même évaluation n'a qu'une identité et que deux évaluations
  distinctes n'en partagent jamais une : un identifiant portable n'est PAS unique d'une campagne à l'autre. Dans le doute sur une campagne ou
  un élément, la couche ne le fournit pas et l'ajoute à `unreadable_count` de la vue (granularité d'une campagne ou d'un élément entier)
  au lieu de le fusionner ou de l'inventer.
- Le modèle public `ResearchRun` n'est pas modifié et aucun modèle de stratégie n'est créé ici.
- Nombres déclarés (question Q-3, ouverte dans l'ADR 0025) : B4 ne fusionne jamais les nombres déclarés avec les compteurs observés, n'invente
  aucune formule d'agrégation et ne revendique aucune couverture complète de cette question. La provenance `OBSERVED` d'un compteur ne
  qualifie que ce que les vues fournies ont permis d'observer ; elle n'établit ni l'exactitude au sens de l'ADR (qui compte aussi les nombres
  déclarés) ni la règle `REAL` de la question Q-5, qui restent ouvertes.

Comptabilité préadmission et `ClosingRecord` (D2) :
- Le A0 préadmission (ce module) EXCLUT la campagne courante de tous les compteurs (23.27.5).
- Le `ClosingRecord` conserve la comptabilité finale, qui INCLUT cette campagne (23.27.5 : `campaigns` augmenté de un, à état par ailleurs
  inchangé), sans compter sa propre clôture en cours comme abandon : `abandoned_reservations` ne compte jamais la campagne en cours de clôture.
  La portée exacte de cette inclusion pour les autres compteurs est fixée par la tranche responsable du `ClosingRecord`. Ce contrat est
  formalisé ici ; son calcul est REPORTÉ à cette tranche : B4 n'en calcule aucun.

Racines dérivées (D3) :
- `derived_root_labels` est un FAIT DE L'APPELANT. B4 ne l'infère jamais de la disposition d'une racine ; il le valide contre les labels
  scannés par B3 (à l'assemblage et à la construction de l'assemblage) et le consigne. E3-J devra vérifier que chaque label dérivé désigne un
  dossier de campagne de la chaîne du registre et que les racines statiques sont celles de la configuration de root (23.27.3, 23.30.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from gate_v_exposure_interpreters import SourceInterpretation
from gate_v_exposure_sources import normalize_window, overlap_verdict
from gate_v_final_holdout_protocol import (
    ExposureFinding,
    ExposureInventory,
    OverlapVerdict,
    OwnCampaignContext,
    SourceKind,
    SourceStatus,
    TrialAccounting,
    UnresolvedCause,
    build_exposure_finding,
    build_exposure_inventory,
    compute_exposure_inventory_id,
    compute_inventory_content_digest,
)

B4_SEMANTICS_VERSION = "gate_v_exposure_inventory_assembly_v1"
REASON_NO_STATIC_ROOT = "NO_STATIC_ROOT"
_COUNTER_NAMES = ("research_runs", "strategies", "campaigns", "abandoned_reservations", "failed_ingestion_attempts", "void_commitments")
_HEX_DIGITS = frozenset("0123456789abcdef")

# Les trois types d'enregistrement du registre que B4 sait lire (23.27.5) et le libellé qui entre dans l'identifiant d'une source.
_REGISTRY_LABELS = {
    SourceKind.REGISTRY_RESERVATION: "reservation",
    SourceKind.REGISTRY_ADMISSION: "admission",
    SourceKind.CONSUMPTION: "consumption",
}
_NON_EXPOSING_REGISTRY_KINDS = frozenset({SourceKind.REGISTRY_RESERVATION, SourceKind.REGISTRY_ADMISSION})


class CounterProvenance(str, Enum):
    """Provenance d'un compteur (23.29.5) : jamais présentée comme exacte si elle n'est pas `OBSERVED`."""

    OBSERVED = "OBSERVED"
    PARTIAL = "PARTIAL"
    NOT_OBSERVED = "NOT_OBSERVED"


# ── Validation commune ───────────────────────────────────────────────────────────────────────────────────────────

# Convention du dépôt (E1, E3-A, B3) : `TypeError` pour un type invalide, `ValueError` pour une valeur invalide.
# Les helpers privés sont dupliqués volontairement (ils ne sont jamais importés entre modules).

def _require_hex64(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} doit être exactement un str.")
    if len(value) != 64 or not set(value) <= _HEX_DIGITS:
        raise ValueError(f"{name} doit être un SHA-256 hexadécimal minuscule de 64 caractères.")
    return value


def _require_text(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} doit être exactement un str.")
    if not value:
        raise ValueError(f"{name} doit être une chaîne non vide.")
    return value


def _require_optional_text(value: object, name: str) -> Optional[str]:
    return None if value is None else _require_text(value, name)


def _require_count(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} doit être exactement un int.")
    if value < 0:
        raise ValueError(f"{name} doit être un entier >= 0.")
    return value


def _require_tuple(value: object, name: str) -> tuple:
    if type(value) is not tuple:
        raise TypeError(f"{name} doit être un tuple.")
    return value


def _unique_texts(value: object, name: str) -> tuple:
    items = _require_tuple(value, name)
    for item in items:
        _require_text(item, f"{name}[]")
    if len(set(items)) != len(items):
        raise ValueError(f"{name} : identifiant dupliqué.")
    return items


# ── Vues injectées (minimales : B4 ne lit aucun fichier et ne construit ni registre ni clôture) ───────────────────

@dataclass(frozen=True)
class RegistryRecordFact:
    """Un enregistrement lisible de la chaîne du registre (RESERVATION, ADMISSION ou CONSUMPTION), tel que le fournit E3-D.
    `campaign_id` et la fenêtre peuvent être absents (enregistrement non attribuable ou à fenêtre illisible, 23.27.4) : le finding
    est alors `UNRESOLVED`, jamais ignoré. L'identité d'une source est `registry.<type>:<registry_id>/<seq>` (jamais le
    `campaign_dir_locator`, 23.27.2)."""

    seq: int
    kind: SourceKind
    campaign_id: Optional[str]
    content_hash: str
    window_start_utc: Optional[str]
    window_end_utc: Optional[str]
    snapshot_id: Optional[str] = None

    def __post_init__(self) -> None:
        if type(self.seq) is not int:
            raise TypeError("seq doit être exactement un int.")
        if self.seq < 0:
            raise ValueError("seq doit être un entier >= 0 (le registre E3-D numérote ses slots depuis 0, C-16).")
        if type(self.kind) is not SourceKind:
            raise TypeError("kind doit être un SourceKind.")
        if self.kind not in _REGISTRY_LABELS:
            raise ValueError("kind doit être REGISTRY_RESERVATION, REGISTRY_ADMISSION ou CONSUMPTION.")
        _require_optional_text(self.campaign_id, "campaign_id")
        _require_hex64(self.content_hash, "content_hash")
        _require_optional_text(self.snapshot_id, "snapshot_id")
        if (self.window_start_utc is None) != (self.window_end_utc is None):
            raise ValueError("Les deux bornes de fenêtre doivent être présentes ensemble ou absentes ensemble.")
        if self.window_start_utc is not None:
            start, end = normalize_window(self.window_start_utc, self.window_end_utc)
            object.__setattr__(self, "window_start_utc", start)
            object.__setattr__(self, "window_end_utc", end)


@dataclass(frozen=True)
class RegistryView:
    """Vue du registre injectée par E3-D : identifiant, tête de chaîne (consignée telle quelle pour B5), enregistrements lisibles
    et identifiants des enregistrements ILLISIBLES. Une vue absente est une erreur d'appel (jamais un registre vide)."""

    registry_id: str
    chain_head: Optional[str]
    records: tuple
    unreadable_record_ids: tuple = ()

    def __post_init__(self) -> None:
        _require_text(self.registry_id, "registry_id")
        if self.chain_head is not None:
            _require_hex64(self.chain_head, "chain_head")
        records = _require_tuple(self.records, "records")
        if any(type(record) is not RegistryRecordFact for record in records):
            raise TypeError("records ne contient que des RegistryRecordFact.")
        if len({record.seq for record in records}) != len(records):
            raise ValueError("records : seq dupliqué.")
        _unique_texts(self.unreadable_record_ids, "unreadable_record_ids")


@dataclass(frozen=True)
class ClosingView:
    """Vue des `ClosingRecord` (fournie par E3-D/E3-J) : campagnes dont le `ClosingRecord` terminal est LISIBLE, et campagnes dont il
    est ILLISIBLE. Toute autre campagne de la chaîne est « introuvable » : introuvable ⇒ abandonnée (conservateur, 23.27.5)."""

    terminal_campaign_ids: tuple
    unreadable_campaign_ids: tuple = ()

    def __post_init__(self) -> None:
        terminal = _unique_texts(self.terminal_campaign_ids, "terminal_campaign_ids")
        unreadable = _unique_texts(self.unreadable_campaign_ids, "unreadable_campaign_ids")
        if set(terminal) & set(unreadable):
            raise ValueError("Une campagne ne peut pas avoir un ClosingRecord terminal ET illisible.")


@dataclass(frozen=True)
class TrialItem:
    """Une tentative d'ingestion échouée ou un engagement nul. `campaign_id` est `None` si l'élément n'est pas attribuable à une
    campagne : il est alors compté (conservateur). L'identité `item_id` déduplique."""

    item_id: str
    campaign_id: Optional[str] = None

    def __post_init__(self) -> None:
        _require_text(self.item_id, "item_id")
        _require_optional_text(self.campaign_id, "campaign_id")


@dataclass(frozen=True)
class TrialItemsView:
    """Vue d'éléments comptés SANS restriction aux campagnes de la chaîne (23.27.5) : `unreadable_count` éléments illisibles rendent le
    compteur minorant (`PARTIAL`)."""

    items: tuple
    unreadable_count: int = 0

    def __post_init__(self) -> None:
        if any(type(item) is not TrialItem for item in _require_tuple(self.items, "items")):
            raise TypeError("items ne contient que des TrialItem.")
        _require_count(self.unreadable_count, "unreadable_count")


@dataclass(frozen=True)
class CampaignTrials:
    """Identités des `ResearchRun` et des stratégies évalués par UNE campagne (chaîne du registre ou campagne V1 avec OOS). Les
    identités sont opaques pour B4 : il les déduplique par égalité exacte, il ne les interprète pas. Ce que la couche d'adaptation qui les
    fournit doit garantir est fixé par le « Contrat de la couche d'adaptation (D1) » du docstring du module."""

    campaign_id: str
    research_run_ids: tuple
    strategy_ids: tuple

    def __post_init__(self) -> None:
        _require_text(self.campaign_id, "campaign_id")
        _unique_texts(self.research_run_ids, "research_run_ids")
        _unique_texts(self.strategy_ids, "strategy_ids")


@dataclass(frozen=True)
class CampaignTrialsView:
    """Essais par campagne ; `unreadable_count` campagnes illisibles rendent les compteurs minorants (`PARTIAL`)."""

    campaigns: tuple
    unreadable_count: int = 0

    def __post_init__(self) -> None:
        campaigns = _require_tuple(self.campaigns, "campaigns")
        if any(type(entry) is not CampaignTrials for entry in campaigns):
            raise TypeError("campaigns ne contient que des CampaignTrials.")
        if len({entry.campaign_id for entry in campaigns}) != len(campaigns):
            raise ValueError("campaigns : une campagne ne peut figurer qu'une fois dans une vue.")
        _require_count(self.unreadable_count, "unreadable_count")


@dataclass(frozen=True)
class AccountingViews:
    """Sources de comptabilité injectées. Une vue absente (`None`) donne `NOT_OBSERVED` (23.29.5), jamais un zéro vérifié."""

    closing: Optional[ClosingView] = None
    failed_ingestion: Optional[TrialItemsView] = None
    void_commitments: Optional[TrialItemsView] = None
    chain_trials: Optional[CampaignTrialsView] = None
    v1_oos_trials: Optional[CampaignTrialsView] = None

    def __post_init__(self) -> None:
        for name, expected in (("closing", ClosingView), ("failed_ingestion", TrialItemsView), ("void_commitments", TrialItemsView),
                               ("chain_trials", CampaignTrialsView), ("v1_oos_trials", CampaignTrialsView)):
            value = getattr(self, name)
            if value is not None and type(value) is not expected:
                raise TypeError(f"{name} doit être None ou un {expected.__name__}.")


@dataclass(frozen=True)
class TrialAccountingProvenance:
    """Provenance des six compteurs (23.29.5). Consignée dans l'A0 (B5), couverte par `inventory_content_hash`, mais dans AUCUNE
    formule d'E3-A. `reasons` explique chaque dégradation (texte déterministe, trié) ; il n'a aucune valeur d'identité."""

    research_runs: CounterProvenance
    strategies: CounterProvenance
    campaigns: CounterProvenance
    abandoned_reservations: CounterProvenance
    failed_ingestion_attempts: CounterProvenance
    void_commitments: CounterProvenance
    reasons: tuple = ()

    def __post_init__(self) -> None:
        for name in _COUNTER_NAMES:
            if type(getattr(self, name)) is not CounterProvenance:
                raise TypeError(f"{name} doit être un CounterProvenance.")
        for reason in _require_tuple(self.reasons, "reasons"):
            _require_text(reason, "reasons[]")


@dataclass(frozen=True)
class ExposureInventoryAssembly:
    """A0 assemblé (23.11 étape 1) : l'inventaire d'E3-A, la provenance des compteurs, les raisons d'incomplétude (celles de B3 conservées
    telles quelles, plus celles de B4), les épinglages utiles à B5/E3-J (registre, racines dérivées, interprétation de B3 transmise
    intacte, y compris `exposure_evidence`, `non_oos_validations` et `plans`) et les identités scientifiques calculées par E3-A.
    Les identités sont recontrôlées à la construction : un assemblage incohérent est refusé."""

    semantics_version: str
    inventory: ExposureInventory
    own_context: OwnCampaignContext
    accounting_provenance: TrialAccountingProvenance
    incomplete_reasons: tuple
    registry_id: str
    registry_chain_head: Optional[str]
    derived_root_labels: tuple
    interpretation: SourceInterpretation
    inventory_id: str
    inventory_content_digest: str

    def __post_init__(self) -> None:
        if self.semantics_version != B4_SEMANTICS_VERSION:
            raise ValueError(f"semantics_version inconnue : attendu {B4_SEMANTICS_VERSION!r}.")
        if type(self.inventory) is not ExposureInventory or type(self.interpretation) is not SourceInterpretation:
            raise TypeError("inventory et interpretation doivent être un ExposureInventory et un SourceInterpretation.")
        if type(self.own_context) is not OwnCampaignContext or type(self.accounting_provenance) is not TrialAccountingProvenance:
            raise TypeError("own_context et accounting_provenance ont un type invalide.")
        _require_text(self.registry_id, "registry_id")
        if self.registry_chain_head is not None:
            _require_hex64(self.registry_chain_head, "registry_chain_head")
        derived = _unique_texts(self.derived_root_labels, "derived_root_labels")
        if self.inventory.scanned_roots != _static_roots(self.interpretation, derived):
            raise ValueError("scanned_roots doit être égal aux racines scannées par B3 moins derived_root_labels.")
        for reason in _require_tuple(self.incomplete_reasons, "incomplete_reasons"):
            _require_text(reason, "incomplete_reasons[]")
        if self.inventory.complete == bool(self.incomplete_reasons):
            raise ValueError("complete est vrai si et seulement si aucune raison d'incomplétude n'existe.")
        if self.inventory.complete and not self.interpretation.complete:
            raise ValueError("B4 n'élargit jamais la complétude de B3.")
        if (self.inventory_id != compute_exposure_inventory_id(self.inventory, self.own_context)
                or self.inventory_content_digest != compute_inventory_content_digest(self.inventory, self.own_context)):
            raise ValueError("Les identités ne correspondent pas à l'inventaire (formules d'E3-A).")

    @property
    def hooks_used(self) -> bool:
        """Vrai si l'interprétation de B3 a été produite avec des `ScanHooks` (outil de test) : aucune autorité de production."""
        return self.interpretation.hooks_used


# ── Registre : findings ──────────────────────────────────────────────────────────────────────────────────────────

def _registry_source_id(view: RegistryView, fact: RegistryRecordFact) -> str:
    return f"registry.{_REGISTRY_LABELS[fact.kind]}:{view.registry_id}/{fact.seq:06d}"


def _registry_finding(view: RegistryView, fact: RegistryRecordFact, window: tuple) -> ExposureFinding:
    source_id = _registry_source_id(view, fact)
    unresolved = None
    if fact.campaign_id is None:
        unresolved = UnresolvedCause.INVALID_SCHEMA
    elif fact.window_start_utc is None:
        unresolved = UnresolvedCause.WINDOW_UNKNOWN
    if unresolved is not None:
        return build_exposure_finding(
            source_id=source_id, source_kind=fact.kind, status=SourceStatus.UNRESOLVED, overlap=OverlapVerdict.UNKNOWN,
            content_hash=fact.content_hash, snapshot_id=fact.snapshot_id, campaign_id=fact.campaign_id, unresolved_cause=unresolved)
    return build_exposure_finding(
        source_id=source_id, source_kind=fact.kind, status=SourceStatus.RESOLVED,
        overlap=overlap_verdict(fact.window_start_utc, fact.window_end_utc, window[0], window[1]),
        content_hash=fact.content_hash, window_start_utc=fact.window_start_utc, window_end_utc=fact.window_end_utc,
        snapshot_id=fact.snapshot_id, campaign_id=fact.campaign_id)


def _is_listable(finding: ExposureFinding, current_campaign_id: str) -> bool:
    """Règle de listabilité d'E3-A (23.28) : une RESERVATION ou ADMISSION étrangère RESOLVED qui ne recoupe pas `W` n'entre que dans
    la comptabilité. Tout le reste est listé : CONSUMPTION (même sans recouvrement), enregistrements propres, non résolus."""
    return not (
        finding.source_kind in _NON_EXPOSING_REGISTRY_KINDS
        and finding.status is SourceStatus.RESOLVED
        and finding.campaign_id != current_campaign_id
        and finding.overlap is not OverlapVerdict.OVERLAPS
    )


def _unreadable_finding(view: RegistryView, record_id: str) -> ExposureFinding:
    return build_exposure_finding(
        source_id=f"registry.unreadable:{view.registry_id}/{record_id}", source_kind=SourceKind.REGISTRY_UNREADABLE,
        status=SourceStatus.UNRESOLVED, overlap=OverlapVerdict.UNKNOWN, unresolved_cause=UnresolvedCause.UNREADABLE)


def _registry_findings(view: RegistryView, window: tuple, current_campaign_id: str) -> tuple:
    """`(findings, raisons d'incomplétude)` : tout enregistrement non attribuable, à fenêtre illisible ou illisible rend l'inventaire
    incomplet (jamais une absence silencieuse, §44.1)."""
    findings, reasons = [], []
    for fact in view.records:
        finding = _registry_finding(view, fact, window)
        if finding.status is SourceStatus.UNRESOLVED:
            reasons.append(f"REGISTRY_RECORD_UNRESOLVED:{finding.source_id}")
        if _is_listable(finding, current_campaign_id):
            findings.append(finding)
    for record_id in view.unreadable_record_ids:
        findings.append(_unreadable_finding(view, record_id))
        reasons.append(f"REGISTRY_UNREADABLE:{view.registry_id}/{record_id}")
    return tuple(findings), tuple(reasons)


# ── Comptabilité ─────────────────────────────────────────────────────────────────────────────────────────────────

def _registry_campaigns(view: RegistryView, excluded_campaign_id: Optional[str]) -> tuple:
    """`(campagnes distinctes, provenance, raisons)` (23.27.5) : R/A/C d'une même campagne comptent une fois ; `excluded_campaign_id`
    (la campagne courante avant admission) n'est pas comptée."""
    campaigns = {fact.campaign_id for fact in view.records if fact.campaign_id is not None and fact.campaign_id != excluded_campaign_id}
    reasons = [f"campaigns:RECORD_WITHOUT_CAMPAIGN:{_registry_source_id(view, fact)}" for fact in view.records if fact.campaign_id is None]
    reasons += [f"campaigns:REGISTRY_UNREADABLE:{record_id}" for record_id in view.unreadable_record_ids]
    provenance = CounterProvenance.PARTIAL if reasons else CounterProvenance.OBSERVED
    return campaigns, provenance, tuple(reasons)


def _abandoned(closing: Optional[ClosingView], campaigns: set, campaigns_provenance: CounterProvenance) -> tuple:
    """`abandoned_reservations` = parmi les campagnes comptées, celles sans `ClosingRecord` terminal lisible (introuvable ⇒ abandonnée).
    Un `ClosingRecord` introuvable ou illisible rend le compteur MAJORANT (`PARTIAL`, 23.29.5) ; une vue absente donne `NOT_OBSERVED`."""
    if closing is None:
        return 0, CounterProvenance.NOT_OBSERVED, ("abandoned_reservations:CLOSING_VIEW_NOT_PROVIDED",)
    unreadable = set(closing.unreadable_campaign_ids)
    missing = sorted(campaigns - set(closing.terminal_campaign_ids))
    reasons = [f"abandoned_reservations:{'CLOSING_UNREADABLE' if c in unreadable else 'CLOSING_NOT_FOUND'}:{c}" for c in missing]
    if campaigns_provenance is not CounterProvenance.OBSERVED:
        reasons.append("abandoned_reservations:CAMPAIGN_SET_PARTIAL")
    return len(missing), (CounterProvenance.PARTIAL if reasons else CounterProvenance.OBSERVED), tuple(reasons)


def _count_items(name: str, view: Optional[TrialItemsView], excluded_campaign_id: Optional[str]) -> tuple:
    """Éléments distincts (par `item_id`), SANS restriction aux campagnes de la chaîne (23.27.5) ; `NOT_OBSERVED` si la vue est absente,
    `PARTIAL` (minorant) si des éléments sont illisibles."""
    if view is None:
        return 0, CounterProvenance.NOT_OBSERVED, (f"{name}:VIEW_NOT_PROVIDED",)
    count = len({item.item_id for item in view.items if item.campaign_id is None or item.campaign_id != excluded_campaign_id})
    if view.unreadable_count:
        return count, CounterProvenance.PARTIAL, (f"{name}:UNREADABLE_ITEMS:{view.unreadable_count}",)
    return count, CounterProvenance.OBSERVED, ()


def _count_trials(accounting: AccountingViews, campaigns: set, campaigns_provenance: CounterProvenance,
                  excluded_campaign_id: Optional[str]) -> tuple:
    """`(research_runs, strategies, provenance, raisons)` : identités DISTINCTES sur les campagnes de la chaîne et les campagnes V1 avec
    OOS (23.27.5). Les nombres déclarés ne sont jamais fusionnés. `OBSERVED` seulement si les deux vues sont fournies et lues
    intégralement et si chaque campagne comptée de la chaîne y figure ; une seule vue lue donne un minorant `PARTIAL`."""
    chain, v1 = accounting.chain_trials, accounting.v1_oos_trials
    if chain is None and v1 is None:
        return 0, 0, CounterProvenance.NOT_OBSERVED, ("trials:VIEW_NOT_PROVIDED",)
    runs, strategies, unreadable, reasons = set(), set(), 0, []
    for view in (chain, v1):
        if view is None:
            continue
        unreadable += view.unreadable_count
        for entry in view.campaigns:
            if entry.campaign_id != excluded_campaign_id:
                runs.update(entry.research_run_ids)
                strategies.update(entry.strategy_ids)
    if unreadable:
        reasons.append(f"trials:UNREADABLE_CAMPAIGNS:{unreadable}")
    if chain is None:
        reasons.append("trials:CHAIN_TRIALS_NOT_PROVIDED")
    else:
        covered = {entry.campaign_id for entry in chain.campaigns} - {excluded_campaign_id}
        reasons.extend(f"trials:CHAIN_CAMPAIGN_WITHOUT_TRIALS:{campaign}" for campaign in sorted(campaigns - covered))
        # Une vue qui cite une campagne absente de la chaîne est incohérente avec le registre : comptée (conservateur), jamais `OBSERVED`.
        reasons.extend(f"trials:CHAIN_TRIALS_FOR_UNKNOWN_CAMPAIGN:{campaign}" for campaign in sorted(covered - campaigns))
    if v1 is None:
        reasons.append("trials:V1_OOS_TRIALS_NOT_PROVIDED")
    if campaigns_provenance is not CounterProvenance.OBSERVED:
        reasons.append("trials:CAMPAIGN_SET_PARTIAL")
    return len(runs), len(strategies), (CounterProvenance.PARTIAL if reasons else CounterProvenance.OBSERVED), tuple(reasons)


def compute_trial_accounting(registry: RegistryView, accounting: AccountingViews, *, current_campaign_id: str) -> tuple:
    """Les six compteurs et leur provenance (23.27.5, 23.29.5) pour le A0 AVANT admission : la campagne courante est exclue de tous les
    compteurs. Retourne `(TrialAccounting, TrialAccountingProvenance)`. Aucun nombre déclaré n'est fusionné ici. La comptabilité finale
    du `ClosingRecord` (campagne courante incluse) n'est pas calculée par cette tranche."""
    if type(registry) is not RegistryView or type(accounting) is not AccountingViews:
        raise TypeError("registry et accounting doivent être un RegistryView et un AccountingViews.")
    _require_text(current_campaign_id, "current_campaign_id")
    excluded = current_campaign_id
    campaigns, campaigns_provenance, campaigns_reasons = _registry_campaigns(registry, excluded)
    abandoned, abandoned_provenance, abandoned_reasons = _abandoned(accounting.closing, campaigns, campaigns_provenance)
    ingestion, ingestion_provenance, ingestion_reasons = _count_items("failed_ingestion_attempts", accounting.failed_ingestion, excluded)
    voids, voids_provenance, voids_reasons = _count_items("void_commitments", accounting.void_commitments, excluded)
    runs, strategies, trials_provenance, trials_reasons = _count_trials(accounting, campaigns, campaigns_provenance, excluded)
    value = TrialAccounting(research_runs=runs, strategies=strategies, campaigns=len(campaigns), abandoned_reservations=abandoned,
                            failed_ingestion_attempts=ingestion, void_commitments=voids)
    provenance = TrialAccountingProvenance(
        research_runs=trials_provenance, strategies=trials_provenance, campaigns=campaigns_provenance,
        abandoned_reservations=abandoned_provenance, failed_ingestion_attempts=ingestion_provenance, void_commitments=voids_provenance,
        reasons=tuple(sorted(campaigns_reasons + abandoned_reasons + ingestion_reasons + voids_reasons + trials_reasons)))
    return value, provenance


# ── Assemblage ───────────────────────────────────────────────────────────────────────────────────────────────────

def _static_roots(interpretation: SourceInterpretation, derived_root_labels: tuple) -> tuple:
    """Racines d'audit STATIQUES scannées (23.27.3) : les racines de B3 moins les racines dérivées (dossiers de campagnes de la chaîne
    du registre), qui sont des sources lues mais jamais des `scanned_roots`."""
    labels = {root.label for item in interpretation.scans for root in item.scan.roots}
    derived = _unique_texts(derived_root_labels, "derived_root_labels")
    if not set(derived) <= labels:
        raise ValueError("derived_root_labels : un label ne correspond à aucune racine scannée par B3.")
    return tuple(sorted(labels - set(derived)))


def assemble_exposure_inventory(interpretation: SourceInterpretation, *, registry: RegistryView, accounting: AccountingViews,
                                own_context: OwnCampaignContext, derived_root_labels: tuple = ()) -> ExposureInventoryAssembly:
    """Assemble l'`ExposureInventory` (A0) depuis l'interprétation de B3, la vue du registre et les sources de comptabilité.

    - Les findings de B3 sont repris tels quels ; ceux du registre sont ajoutés selon la règle de listabilité d'E3-A.
    - `complete` n'est vrai que si B3 est complet ET si le registre est lu sans anomalie ET si une racine statique existe.
    - La comptabilité n'influe ni sur `complete`, ni sur `inventory_id`, ni sur la classe ; sa provenance est consignée à part.
    - `derived_root_labels` : labels de racines scannées par B3 qui sont des campagnes dérivées de la chaîne (jamais `scanned_roots`)."""
    for value, expected, name in ((interpretation, SourceInterpretation, "interpretation"), (registry, RegistryView, "registry"),
                                  (accounting, AccountingViews, "accounting"), (own_context, OwnCampaignContext, "own_context")):
        if type(value) is not expected:
            raise TypeError(f"{name} doit être un {expected.__name__}.")
    window = (interpretation.holdout_window_start_utc, interpretation.holdout_window_end_utc)
    roots = _static_roots(interpretation, derived_root_labels)
    registry_findings, registry_reasons = _registry_findings(registry, window, own_context.current_campaign_id)
    accounting_value, provenance = compute_trial_accounting(
        registry, accounting, current_campaign_id=own_context.current_campaign_id)
    own_reasons = registry_reasons + (() if roots else (REASON_NO_STATIC_ROOT,))
    reasons_all = tuple(sorted(set(interpretation.incomplete_reasons) | set(own_reasons)))
    inventory = build_exposure_inventory(
        window_start_utc=window[0], window_end_utc=window[1],
        findings=interpretation.findings + registry_findings, complete=not reasons_all, scanned_roots=roots,
        trial_accounting=accounting_value)
    return ExposureInventoryAssembly(
        semantics_version=B4_SEMANTICS_VERSION, inventory=inventory, own_context=own_context, accounting_provenance=provenance,
        incomplete_reasons=reasons_all, registry_id=registry.registry_id, registry_chain_head=registry.chain_head,
        derived_root_labels=tuple(sorted(derived_root_labels)), interpretation=interpretation,
        inventory_id=compute_exposure_inventory_id(inventory, own_context),
        inventory_content_digest=compute_inventory_content_digest(inventory, own_context))
