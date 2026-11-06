"""
gate_v_audit_plan_declared.py — N-VIDE-2 / N2-b2a : diagnostic DESCRIPTIF des déclarations des plans de campagne V2 (module interne, pur, diagnostic seul).

Ce module décrit ce que les plans V2 des AUTRES campagnes de la chaîne du registre lue PROMETTENT : références de run et configurations de recherche déclarées, leur réemploi entre campagnes, leurs
conflits d'identifiant. Il ne dit RIEN de ce qui a été exécuté. Ce n'est PAS de la comptabilité : aucun de ces nombres n'est un nombre d'essais exécutés, ni le N d'un test multiple, ni une entrée
d'un calcul de PBO ou de DSR, et aucun n'entre dans la comptabilité de B4 (qui reste observée séparément). Les comptes de campagnes et de déclarations lues sont des MINORANTS de la recherche
réelle, quelle que soit la base : campagnes V1, hors registre, hors campagne ou sans dossier fourni sont invisibles. Les comptes de déclarations DISTINCTES (références, configurations, noms) sont
TEXTUELS : deux écritures sémantiquement équivalentes (`10` et `10.0`, deux graphies Unicode d'un même nom) comptent pour deux ; ils ne sont donc ni des minorants ni des majorants stricts.

Pur : aucune lecture disque, aucune écriture, aucune horloge, aucun hasard, aucun sous-processus. Les faits viennent des observations strictes du PREMIER scan déjà en mémoire, pour les seules racines
déjà attribuées par l'adaptateur. Les faits lus sont DÉTERMINÉS par l'identifiant de campagne (à collision de SHA-256 près) mais NON AUTHENTIFIÉS : rien ne lie une référence de run à un run réel.
Limite connue (ABA) : un adversaire ayant un accès en écriture concurrent au dossier de campagne pendant l'audit pourrait faire entrer des faits forgés ; le contrôle d'identifiant ci-dessous ne vérifie
que la cohérence interne des trois champs d'identité, pas l'empreinte de protocole.

Défaillances CRITIQUES d'exécution (mémoire, récursion) : jamais dégradées en « campagne indisponible » ; elles se propagent, le protocole les rend en refus typé. Seules les erreurs ordinaires de
DONNÉES d'un plan donnent une campagne indisponible avec un code fermé.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import re
from typing import Optional

from gate_v_campaign_plan_v2 import GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION, compute_gate_v_campaign_id_v2
from gate_v_exposure_interpreters import RootLayout
from gate_v_exposure_scan import EntryKind

__all__ = ["MAX_CONFLICT_SAMPLE", "PLAN_DECLARED_SEMANTICS_VERSION", "UNAVAILABLE_CODES", "PlanDeclaredBasis", "PlanDeclaredDiagnostic", "diagnose"]

PLAN_DECLARED_SEMANTICS_VERSION = "gate_v_plan_declared_v1"
MAX_CONFLICT_SAMPLE = 20
UNAVAILABLE_CODES = ("NO_ATTRIBUTED_ROOT", "PLAN_CAMPAIGN_ID_MISMATCH", "PLAN_FIELD_INVALID", "PLAN_RECORD_NOT_READ", "PREIMAGE_TOO_LARGE")          # ensemble FERMÉ, trié
_SCOPE = "REGISTRY_CHAIN_PLAN_V2_ONLY"
_NOT_ESTABLISHED = ("EXECUTION_OF_DECLARED_RESEARCH", "EVALUATED_PARAMETER_POINTS", "V1_CAMPAIGNS", "CAMPAIGNS_OUTSIDE_REGISTRY", "RESEARCH_OUTSIDE_CAMPAIGNS", "RUN_ARTIFACT_VERIFICATION",
                    "RUN_REFERENCE_AUTHENTICITY", "PLAN_SOURCES_CROSS_VALIDATION", "PLAN_ROOT_CONTENT_ATTRIBUTION", "STRATEGY_CODE_IDENTITY", "CONFIGURATION_DATA_BINDING", "OWN_CAMPAIGN_OVERLAP",
                    "ABANDONED_FAILED_OR_VOID_ATTEMPTS", "MULTIPLE_TESTING_N")
_PLAN_FILE = "plan.json"
_PREIMAGE_FACTOR = 8
_MAX_RUN_ID_LENGTH = 255          # DIVERGENCE VOULUE avec le chargeur (qui n'impose aucune longueur) : limite d'un nom de fichier, borne la taille du rapport ; un identifiant plus long rend la campagne indisponible (minorant)
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX12 = re.compile(r"[0-9a-f]{12}")
_CAMPAIGN_ID = re.compile(r"gate_v_v2_[0-9a-f]{64}")
_RUN_ID = re.compile(r"[A-Za-z0-9_.-]+")
_RUN_PREFIX = "declared_run_reference_v1_"
_CONFIG_PREFIX = "declared_search_configuration_v1_"
_DECLARED_FIELDS = ("declared_run_reference_count", "declared_run_id_count", "declared_search_config_count", "declared_strategy_name_count")
_REUSE_FIELDS = ("multi_campaign_run_reference_count", "multi_campaign_search_config_count", "id_with_several_content_hashes_count", "content_hash_with_several_ids_count")
_COUNT_FIELDS = _DECLARED_FIELDS + _REUSE_FIELDS


class PlanDeclaredBasis(str, enum.Enum):
    """Base du diagnostic. Les noms disent ce qui a été LU (un enregistrement de plan dans le premier scan), jamais une exhaustivité : les comptes de campagnes et de déclarations lues sont des minorants ; les
    comptes de déclarations distinctes sont textuels (voir le docstring du module)."""

    REGISTRY_HAS_NO_OTHER_CAMPAIGN = "REGISTRY_HAS_NO_OTHER_CAMPAIGN"                  # la chaîne lue n'a aucune autre campagne ; ne dit rien des campagnes V1, hors registre ou hors campagne
    EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ = "EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ"
    SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ = "SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ"
    NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ = "NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ"


def _is_count(value) -> bool:
    return type(value) is int and value >= 0


def _is_optional_count(value) -> bool:
    return value is None or _is_count(value)


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlanDeclaredDiagnostic:
    """Déclarations des plans V2 des AUTRES campagnes de la chaîne. Aucun champ n'est un nombre d'essais exécutés. Les comptes valent `None` quand ils ne sont pas calculables (aucun fait lu, ou moins de
    deux campagnes sources pour un réemploi) ; le zéro n'est constaté que pour une chaîne sans autre campagne (portée `scope`). Les `multi_campaign_*` comptent un RÉEMPLOI entre au moins deux autres
    campagnes, jamais avec la campagne auditée : un zéro ne signifie ni « aucun réemploi » ni indépendance de la campagne auditée."""

    basis: PlanDeclaredBasis
    source_campaign_count: int
    unavailable_campaign_count: int
    unavailable_breakdown: tuple
    declared_run_reference_count: Optional[int]
    declared_run_id_count: Optional[int]
    declared_search_config_count: Optional[int]
    declared_strategy_name_count: Optional[int]
    multi_campaign_run_reference_count: Optional[int]
    multi_campaign_search_config_count: Optional[int]
    id_with_several_content_hashes_count: Optional[int]
    content_hash_with_several_ids_count: Optional[int]
    conflicting_run_id_sample: tuple

    def __post_init__(self) -> None:
        bad = ValueError("PlanDeclaredDiagnostic incohérent")
        if type(self.basis) is not PlanDeclaredBasis or not _is_count(self.source_campaign_count) or not _is_count(self.unavailable_campaign_count):                    # I1
            raise bad
        if type(self.unavailable_breakdown) is not tuple or type(self.conflicting_run_id_sample) is not tuple or any(not _is_optional_count(getattr(self, n)) for n in _COUNT_FIELDS):
            raise bad
        self._check_breakdown(bad)
        k, u = self.source_campaign_count, self.unavailable_campaign_count
        expected = PlanDeclaredBasis.REGISTRY_HAS_NO_OTHER_CAMPAIGN if k == 0 and u == 0 else (
            PlanDeclaredBasis.NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ if k == 0 else (
                PlanDeclaredBasis.EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ if u == 0 else PlanDeclaredBasis.SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ))
        if self.basis is not expected:                                                                                                                                     # I2
            raise bad
        if k == 0:
            self._check_without_source(bad)
        else:
            self._check_with_source(bad)

    def _check_breakdown(self, bad: ValueError) -> None:                                                                                                                  # I4
        rows = self.unavailable_breakdown
        if any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str or row[0] not in UNAVAILABLE_CODES or type(row[1]) is not int or row[1] <= 0 for row in rows):
            raise bad
        codes = [row[0] for row in rows]
        if codes != sorted(set(codes)) or sum(row[1] for row in rows) != self.unavailable_campaign_count:
            raise bad

    def _check_without_source(self, bad: ValueError) -> None:
        if self.conflicting_run_id_sample != ():
            raise bad
        zero = 0 if self.unavailable_campaign_count == 0 else None                                                                                                         # chaîne sans autre campagne : zéro constaté ; sinon aucun fait : None
        if any(getattr(self, n) != zero for n in _DECLARED_FIELDS) or any(getattr(self, n) is not None for n in _REUSE_FIELDS):
            raise bad

    def _check_with_source(self, bad: ValueError) -> None:                                                                                                                # I3
        k = self.source_campaign_count
        refs, ids, configs, names = (getattr(self, n) for n in _DECLARED_FIELDS)
        if any(v is None for v in (refs, ids, configs, names)) or not (1 <= refs <= k and 1 <= ids <= refs and 1 <= configs <= k and 1 <= names <= configs):
            raise bad
        reuse = tuple(getattr(self, n) for n in _REUSE_FIELDS)
        if k == 1:
            if any(v is not None for v in reuse) or self.conflicting_run_id_sample != ():
                raise bad
            return
        if any(v is None for v in reuse):
            raise bad
        multi_runs, multi_configs, id_conflicts, hash_conflicts = reuse
        if not (multi_runs <= refs and refs + multi_runs <= k and multi_configs <= configs and configs + multi_configs <= k):                                      # une identité réemployée couvre >= 2 campagnes
            raise bad
        if not (id_conflicts <= ids and ids + id_conflicts <= refs and (refs == ids) == (id_conflicts == 0) and 2 * hash_conflicts <= refs and (hash_conflicts == 0 or ids >= 2)):          # conflits : paires (identifiant, contenu) distinctes
            raise bad
        sample = self.conflicting_run_id_sample
        if any(type(s) is not str or len(s) > _MAX_RUN_ID_LENGTH for s in sample) or list(sample) != sorted(set(sample)) or len(sample) != min(MAX_CONFLICT_SAMPLE, id_conflicts):
            raise bad

    @property
    def semantics_version(self) -> str:
        return PLAN_DECLARED_SEMANTICS_VERSION

    @property
    def scope(self) -> str:
        return _SCOPE

    @property
    def not_established(self) -> tuple:
        return _NOT_ESTABLISHED


# ── Identités versionnées (SHA-256 sur JSON canonique) ───────────────────────────────────────────────────────────────────────────────────────────

class _Unavailable(Exception):
    """Interne : une campagne dont les faits ne sont pas extraits, avec un code de `UNAVAILABLE_CODES`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _canonical(preimage: dict) -> bytes:
    """Même canonicalisation que l'empreinte de protocole des plans V2, codée en UTF-8 (un surrogate isolé lève `UnicodeEncodeError`, un `ValueError`)."""
    return json.dumps(preimage, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _identity(prefix: str, preimage: dict, cap: Optional[int]) -> str:
    encoded = _canonical(preimage)
    if cap is not None and len(encoded) > cap:
        raise _Unavailable("PREIMAGE_TOO_LARGE")
    return prefix + hashlib.sha256(encoded).hexdigest()


def _run_reference_identity(run_id: str, content_hash: str, cap: Optional[int] = None) -> str:
    return _identity(_RUN_PREFIX, {"declared_kind": "research_run_reference", "identity_version": "declared_run_reference_v1", "research_run_content_hash": content_hash, "research_run_id": run_id}, cap)


def _configuration_identity(strategy_name: str, base_params: dict, search_mode: str, search_space_hash: str, cap: Optional[int] = None) -> str:
    return _identity(_CONFIG_PREFIX, {"base_params": base_params, "declared_kind": "search_configuration", "identity_version": "declared_search_configuration_v1", "search_mode": search_mode,
                                      "search_space_hash": search_space_hash, "strategy_name": strategy_name}, cap)


# ── Extraction par campagne ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _hex(record: dict, key: str, pattern) -> str:
    value = record.get(key)
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise _Unavailable("PLAN_FIELD_INVALID")
    return value


def _text(record: dict, key: str) -> str:
    value = record.get(key)
    if type(value) is not str or not value.strip():
        raise _Unavailable("PLAN_FIELD_INVALID")
    return value


def _strict_record(observations) -> dict:
    """Reproduit la sémantique de l'observation stricte de la fenêtre : exactement une observation, fichier, sans anomalie, lue, empreinte non nulle, objet JSON."""
    if len(observations) != 1:
        raise _Unavailable("PLAN_RECORD_NOT_READ")
    found = observations[0]
    if found.kind is not EntryKind.FILE or found.anomaly is not None or not found.value_parsed or found.content_hash is None or type(found.value) is not dict:
        raise _Unavailable("PLAN_RECORD_NOT_READ")
    return found.value


def _hex_id(record: dict) -> str:
    value = record.get("campaign_id")
    if type(value) is not str or _CAMPAIGN_ID.fullmatch(value) is None:
        raise _Unavailable("PLAN_FIELD_INVALID")
    return value


def _extract(record: dict, expected_id: str, cap: int) -> tuple:
    """Faits d'un plan : (identifiant de run, contenu, identité de référence, nom de stratégie, identité de configuration). Version contrôlée en premier."""
    if record.get("campaign_plan_semantics_version") != GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION:
        raise _Unavailable("PLAN_FIELD_INVALID")
    declared_id = _hex_id(record)
    preregistration = _hex(record, "preregistration_id", _HEX64)
    fingerprint = _hex(record, "campaign_protocol_fingerprint", _HEX64)
    content = _hex(record, "research_run_content_hash", _HEX64)
    space = _hex(record, "search_space_hash", _HEX12)
    run_id = record.get("research_run_id")
    if type(run_id) is not str or len(run_id) > _MAX_RUN_ID_LENGTH or _RUN_ID.fullmatch(run_id) is None or ".." in run_id:
        raise _Unavailable("PLAN_FIELD_INVALID")
    strategy, mode = _text(record, "strategy_name"), _text(record, "search_mode")
    params = record.get("base_params")
    if type(params) is not dict or not params:
        raise _Unavailable("PLAN_FIELD_INVALID")
    recomputed = compute_gate_v_campaign_id_v2(campaign_plan_semantics_version=GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION, preregistration_id=preregistration, campaign_protocol_fingerprint=fingerprint)
    if recomputed != expected_id or recomputed != declared_id:
        raise _Unavailable("PLAN_CAMPAIGN_ID_MISMATCH")
    return run_id, content, _run_reference_identity(run_id, content, cap), strategy, _configuration_identity(strategy, params, mode, space, cap)


def _facts_of(observations, expected_id: str, cap: int) -> tuple:
    try:
        return _extract(_strict_record(observations), expected_id, cap)
    except OverflowError:
        raise _Unavailable("PREIMAGE_TOO_LARGE") from None
    except (ValueError, TypeError):                              # erreurs ordinaires de DONNÉES (dont `UnicodeEncodeError`, clés mixtes sous `sort_keys`) ; MemoryError et RecursionError se propagent volontairement
        raise _Unavailable("PLAN_FIELD_INVALID") from None


# ── Préconditions ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _check_arguments(derived, other_campaign_count, max_json_bytes) -> None:
    for value in (other_campaign_count, max_json_bytes):
        if type(value) is not int:
            raise TypeError("other_campaign_count et max_json_bytes doivent être des entiers (bool exclu)")
    if max_json_bytes < 1 or other_campaign_count < 0:
        raise ValueError("max_json_bytes >= 1 et other_campaign_count >= 0 attendus")
    if type(derived) is not tuple or any(type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str or type(pair[1]) is not str for pair in derived):
        raise TypeError("derived doit être un tuple de couples (étiquette, identifiant)")
    labels, ids = [pair[0] for pair in derived], [pair[1] for pair in derived]
    if len(set(labels)) != len(labels) or len(set(ids)) != len(ids) or any(_CAMPAIGN_ID.fullmatch(identifier) is None for identifier in ids):
        raise ValueError("derived : étiquettes et identifiants distincts, identifiants de la forme gate_v_v2_<64 hexadécimaux>")
    if other_campaign_count < len(derived):
        raise ValueError("other_campaign_count doit couvrir les racines dérivées")


# ── Agrégation ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _index(interpretation, wanted: frozenset) -> dict:
    """Un SEUL parcours des observations de S1 : disposition `CAMPAIGN_DIR`, nom `plan.json`, étiquettes demandées seulement."""
    found = {}
    for item in interpretation.scans:
        if item.layout is not RootLayout.CAMPAIGN_DIR:
            continue
        for observation in item.scan.observations:
            if observation.relative_path == _PLAN_FILE and observation.root_label in wanted:
                found.setdefault(observation.root_label, []).append(observation)
    return found


def _reuse(counts: dict) -> int:
    return sum(1 for n in counts.values() if n >= 2)


def diagnose(interpretation, *, derived: tuple, other_campaign_count: int, max_json_bytes: int) -> PlanDeclaredDiagnostic:
    """Diagnostic des déclarations des plans V2 des autres campagnes de la chaîne. `interpretation` : B3 sur le PREMIER scan. `derived` : couples (étiquette, identifiant) des racines déjà attribuées,
    campagne propre exclue. Préconditions (erreur de programmation : `TypeError`/`ValueError`, jamais « campagne indisponible ») avant tout index. Une défaillance de DONNÉES d'un plan rend la campagne
    indisponible avec un code fermé ; `MemoryError` et `RecursionError` se propagent."""
    _check_arguments(derived, other_campaign_count, max_json_bytes)
    cap = _PREIMAGE_FACTOR * max_json_bytes
    pairs = sorted(derived)
    index = _index(interpretation, frozenset(label for label, _identifier in pairs)) if pairs else {}
    unavailable = {}
    if other_campaign_count > len(pairs):
        unavailable["NO_ATTRIBUTED_ROOT"] = other_campaign_count - len(pairs)
    run_refs, configs, strategies, hashes_of_id, ids_of_hash, run_ids = {}, {}, set(), {}, {}, set()
    source = 0
    for label, identifier in pairs:
        try:
            run_id, content, run_identity, strategy, config_identity = _facts_of(index.get(label, []), identifier, cap)
        except _Unavailable as failure:
            unavailable[failure.code] = unavailable.get(failure.code, 0) + 1
            continue
        source += 1
        run_refs[run_identity] = run_refs.get(run_identity, 0) + 1
        configs[config_identity] = configs.get(config_identity, 0) + 1
        strategies.add(strategy)
        run_ids.add(run_id)
        hashes_of_id.setdefault(run_id, set()).add(content)
        ids_of_hash.setdefault(content, set()).add(run_id)
    breakdown = tuple(sorted(unavailable.items()))
    missing = sum(unavailable.values())
    if source == 0:
        basis = PlanDeclaredBasis.REGISTRY_HAS_NO_OTHER_CAMPAIGN if missing == 0 else PlanDeclaredBasis.NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ
        zero = 0 if missing == 0 else None
        return PlanDeclaredDiagnostic(basis=basis, source_campaign_count=0, unavailable_campaign_count=missing, unavailable_breakdown=breakdown, declared_run_reference_count=zero,
                                      declared_run_id_count=zero, declared_search_config_count=zero, declared_strategy_name_count=zero, multi_campaign_run_reference_count=None,
                                      multi_campaign_search_config_count=None, id_with_several_content_hashes_count=None, content_hash_with_several_ids_count=None, conflicting_run_id_sample=())
    comparable = source >= 2
    conflicting = sorted(run_id for run_id, hashes in hashes_of_id.items() if len(hashes) > 1)
    return PlanDeclaredDiagnostic(
        basis=PlanDeclaredBasis.EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ if missing == 0 else PlanDeclaredBasis.SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ,
        source_campaign_count=source, unavailable_campaign_count=missing, unavailable_breakdown=breakdown, declared_run_reference_count=len(run_refs), declared_run_id_count=len(run_ids),
        declared_search_config_count=len(configs), declared_strategy_name_count=len(strategies),
        multi_campaign_run_reference_count=_reuse(run_refs) if comparable else None, multi_campaign_search_config_count=_reuse(configs) if comparable else None,
        id_with_several_content_hashes_count=len(conflicting) if comparable else None,
        content_hash_with_several_ids_count=sum(1 for ids in ids_of_hash.values() if len(ids) > 1) if comparable else None,
        conflicting_run_id_sample=tuple(conflicting[:MAX_CONFLICT_SAMPLE]) if comparable else ())
