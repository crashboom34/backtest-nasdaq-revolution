"""
gate_v_validation_policy.py — GateVValidationPolicyVersion (AF-V-07 Slice A, ADR 0025).

Typed Gate V policy criteria, canonical semantic hash, immutable persistence. Leaf module:
imports nothing from `gate_v_campaign.py`/`validation_oos.py`/`walk_forward.py`/`monte_carlo.py`/
`parameter_stability.py` orchestration — reuses only `atomic_json_store.py` primitives, same as
`validation_run.py`/`dataset_split.py`.

Scope boundary (ADR 0025 Décision 4/5, Slice A only): typed criteria, `GateVValidationPolicyVersion`,
derived `pass_capable`, canonical serialization, `policy_content_hash`, immutable save/load. NO
evaluator (`evaluate_validation_run()`/`evaluate_gate_v_campaign()`), NO `GateVPreRegistration`,
NO `policy_git_sha` verification, NO `campaign_protocol_fingerprint`, NO real scientific threshold
policy — all reserved for later slices.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Dict, Literal, Mapping, Tuple, Union

from atomic_json_store import load_json_tolerant, save_atomic, validate_portable_identifier

REQUIRED_VALIDATION_TYPES: Tuple[str, ...] = ("oos", "walk_forward", "monte_carlo", "parameter_stability")

Operator = Literal[">", ">=", "<", "<=", "=="]
_OPERATORS = (">", ">=", "<", "<=", "==")

_OOS_METRICS = ("n_trades", "net_ret_pct", "profit_factor", "win_rate", "max_dd_pct")
_WF_METRICS = (
    "total_oos_trades",
    "oos_net_return_pct",
    "oos_max_dd_pct",
    "oos_profit_factor",
    "oos_win_rate",
    "oos_sharpe",
)
_MC_DISTRIBUTIONS = (
    "sequence_risk_max_dd_trade_close_basis_pct",
    "sequence_risk_longest_losing_streak",
    "sampling_uncertainty_net_ret_pct",
    "sampling_uncertainty_max_dd_trade_close_basis_pct",
)
_MC_PERCENTILES = ("p5", "p25", "p50", "p75", "p95")
_PS_SCOPES = ("ALL_USABLE_PARAMETERS", "WORST_CASE_PARAMETER")
_PS_METRICS = ("degradation_by_param", "degradation_points_by_param")


def _validate_operator(operator: str) -> str:
    if operator not in _OPERATORS:
        raise ValueError(f"operator invalide : {operator!r} — attendu un de {_OPERATORS}")
    return operator


def _validate_threshold(threshold) -> float:
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError(f"threshold doit être un nombre fini, jamais bool : {threshold!r}")
    value = float(threshold)
    if not math.isfinite(value):
        raise ValueError(f"threshold doit être fini (ni NaN ni Inf) : {threshold!r}")
    return value


def _validate_literal(value: str, allowed: Tuple[str, ...], field_name: str) -> str:
    if value not in allowed:
        raise ValueError(f"{field_name} invalide : {value!r} — attendu un de {allowed}")
    return value


@dataclass(frozen=True)
class OosPolicyCriterion:
    """Critère typé sur `OosValidationEvidence` (ADR 0025 Décision 4)."""

    metric: str
    operator: Operator
    threshold: float

    def __post_init__(self) -> None:
        _validate_literal(self.metric, _OOS_METRICS, "OosPolicyCriterion.metric")
        object.__setattr__(self, "operator", _validate_operator(self.operator))
        object.__setattr__(self, "threshold", _validate_threshold(self.threshold))


@dataclass(frozen=True)
class WalkForwardPolicyCriterion:
    """Critère typé sur `AggregateResult` Walk-Forward (ADR 0025 Décision 4)."""

    metric: str
    operator: Operator
    threshold: float

    def __post_init__(self) -> None:
        _validate_literal(self.metric, _WF_METRICS, "WalkForwardPolicyCriterion.metric")
        object.__setattr__(self, "operator", _validate_operator(self.operator))
        object.__setattr__(self, "threshold", _validate_threshold(self.threshold))


@dataclass(frozen=True)
class MonteCarloPolicyCriterion:
    """Critère typé sur `PercentileDistributionSummary` Monte-Carlo (ADR 0025 Décision 4)."""

    distribution: str
    percentile: str
    operator: Operator
    threshold: float

    def __post_init__(self) -> None:
        _validate_literal(self.distribution, _MC_DISTRIBUTIONS, "MonteCarloPolicyCriterion.distribution")
        _validate_literal(self.percentile, _MC_PERCENTILES, "MonteCarloPolicyCriterion.percentile")
        object.__setattr__(self, "operator", _validate_operator(self.operator))
        object.__setattr__(self, "threshold", _validate_threshold(self.threshold))


@dataclass(frozen=True)
class ParameterStabilityPolicyCriterion:
    """Critère typé, agnostique de stratégie — jamais un nom de paramètre (ADR 0025 Décision 4/15)."""

    scope: str
    metric: str
    operator: Operator
    threshold: float

    def __post_init__(self) -> None:
        _validate_literal(self.scope, _PS_SCOPES, "ParameterStabilityPolicyCriterion.scope")
        _validate_literal(self.metric, _PS_METRICS, "ParameterStabilityPolicyCriterion.metric")
        object.__setattr__(self, "operator", _validate_operator(self.operator))
        object.__setattr__(self, "threshold", _validate_threshold(self.threshold))


_CRITERION_TYPE_BY_FAMILY: Dict[str, type] = {
    "oos": OosPolicyCriterion,
    "walk_forward": WalkForwardPolicyCriterion,
    "monte_carlo": MonteCarloPolicyCriterion,
    "parameter_stability": ParameterStabilityPolicyCriterion,
}

PolicyCriteriaInput = Mapping[str, object]


@dataclass(frozen=True)
class GateVValidationPolicyVersion:
    """Définition de policy Gate V, source-contrôlée, immuable (ADR 0025 Décision 4).

    Forme normative MINIMALE : uniquement `validation_policy_id`/`scientific_criteria`.
    `pass_capable` est dérivé (propriété), jamais un champ persisté indépendant. Construire
    exclusivement via `build_gate_v_validation_policy()` — jamais l'appel direct au constructeur,
    qui ne revalide pas les familles/types de critère."""

    validation_policy_id: str
    scientific_criteria: Mapping[str, Tuple[object, ...]]

    @property
    def pass_capable(self) -> bool:
        return all(len(self.scientific_criteria.get(t, ())) > 0 for t in REQUIRED_VALIDATION_TYPES)


def build_gate_v_validation_policy(
    validation_policy_id: str, scientific_criteria: PolicyCriteriaInput
) -> GateVValidationPolicyVersion:
    """Seul point de construction validé : identifiant, familles connues, type de critère par
    famille. Réutilisé aussi par `load_gate_v_validation_policy()` pour revalider au chargement."""
    validate_portable_identifier(validation_policy_id, "validation_policy_id")
    unknown = set(scientific_criteria.keys()) - set(REQUIRED_VALIDATION_TYPES)
    if unknown:
        raise ValueError(f"scientific_criteria contient des familles inconnues : {sorted(unknown)}")
    normalized: Dict[str, Tuple[object, ...]] = {}
    for family in REQUIRED_VALIDATION_TYPES:
        expected_cls = _CRITERION_TYPE_BY_FAMILY[family]
        criteria_tuple = tuple(scientific_criteria.get(family, ()))
        for criterion in criteria_tuple:
            if type(criterion) is not expected_cls:
                raise ValueError(
                    f"scientific_criteria[{family!r}] attend uniquement {expected_cls.__name__}, "
                    f"reçu {type(criterion).__name__}"
                )
        normalized[family] = criteria_tuple
    return GateVValidationPolicyVersion(
        validation_policy_id=validation_policy_id,
        scientific_criteria=MappingProxyType(normalized),
    )


def _policy_normative_record(policy: GateVValidationPolicyVersion) -> dict:
    """Contenu normatif seul — jamais `pass_capable`/`policy_content_hash` (auto-référence)."""
    return {
        "validation_policy_id": policy.validation_policy_id,
        "scientific_criteria": {
            family: [asdict(criterion) for criterion in policy.scientific_criteria.get(family, ())]
            for family in REQUIRED_VALIDATION_TYPES
        },
    }


def canonical_policy_json(policy: GateVValidationPolicyVersion) -> str:
    """Sérialisation canonique — ADR 0025 Décision 5. L'ordre des critères DANS une famille est
    normatif (préservé tel quel, jamais trié) ; seules les clés des dict sont triées (`sort_keys`)."""
    return json.dumps(
        _policy_normative_record(policy),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def policy_content_hash(policy: GateVValidationPolicyVersion) -> str:
    """Hash sémantique canonique — jamais un hash d'octets bruts de fichier (ADR 0025 Décision 5).
    Toujours dérivé, jamais inclus dans sa propre préimage (jamais stocké dans le fichier persisté)."""
    return hashlib.sha256(canonical_policy_json(policy).encode("utf-8")).hexdigest()


def save_gate_v_validation_policy(path: Union[str, Path], policy: GateVValidationPolicyVersion) -> Path:
    """Persistance immuable — réutilise `save_atomic()` (refuse tout écrasement). L'appelant
    fournit le chemin ; ce module ne résout jamais lui-même un répertoire de projet."""
    return save_atomic(path, _policy_normative_record(policy), kind="GateVValidationPolicyVersion")


def _criterion_from_dict(family: str, data: object) -> object:
    if not isinstance(data, dict):
        raise ValueError(f"critère malformé pour {family!r} : objet JSON attendu, reçu {data!r}")
    cls = _CRITERION_TYPE_BY_FAMILY[family]
    try:
        return cls(**data)
    except TypeError as exc:
        raise ValueError(f"critère malformé pour {family!r} : {data!r}") from exc


def gate_v_validation_policy_from_dict(data: dict) -> GateVValidationPolicyVersion:
    """Reconstruction STRICTE depuis un `dict` JSON déjà parsé — extrait de
    `load_gate_v_validation_policy()` (AF-V-07 Slice B) pour rester l'UNIQUE chemin de
    reconstruction/validation, partagé par le chargement fichier normal ET par la vérification
    fail-closed de provenance Git (`gate_v_preregistration.py`), qui parse des octets récupérés
    via `git show` plutôt que via un chemin de fichier."""
    if not isinstance(data, dict):
        raise ValueError("GateVValidationPolicyVersion malformée : objet JSON attendu")
    allowed_top_level_keys = {"validation_policy_id", "scientific_criteria"}
    unknown_top_level = set(data.keys()) - allowed_top_level_keys
    if unknown_top_level:
        raise ValueError(
            f"GateVValidationPolicyVersion malformée : champ(s) inconnu(s) {sorted(unknown_top_level)}"
        )
    try:
        validation_policy_id = data["validation_policy_id"]
        raw_criteria = data["scientific_criteria"]
    except KeyError as exc:
        raise ValueError(f"GateVValidationPolicyVersion malformée : champ manquant {exc}") from exc
    if not isinstance(raw_criteria, dict):
        raise ValueError("scientific_criteria malformé : objet JSON attendu")
    unknown = set(raw_criteria.keys()) - set(REQUIRED_VALIDATION_TYPES)
    if unknown:
        raise ValueError(f"scientific_criteria contient des familles inconnues : {sorted(unknown)}")
    normalized: Dict[str, Tuple[object, ...]] = {}
    for family in REQUIRED_VALIDATION_TYPES:
        raw_list = raw_criteria.get(family, [])
        if not isinstance(raw_list, list):
            raise ValueError(f"scientific_criteria[{family!r}] malformé : liste attendue")
        normalized[family] = tuple(_criterion_from_dict(family, item) for item in raw_list)
    return build_gate_v_validation_policy(validation_policy_id, normalized)


def load_gate_v_validation_policy(path: Union[str, Path]) -> GateVValidationPolicyVersion:
    """Chargement STRICT — usage scientifique, jamais tolérant : fichier absent/illisible/
    malformé -> exception, jamais un `None` silencieux (contrairement à `load_tolerant()`
    générique du module partagé, réservé aux usages non critiques)."""
    data = load_json_tolerant(path)
    if data is None:
        raise ValueError(f"GateVValidationPolicyVersion illisible ou introuvable : {path}")
    return gate_v_validation_policy_from_dict(data)
