"""
parameter_stability.py — Parameter Stability V1 : ré-analyse de voisinage déterministe d'un pool
de candidats déjà évalués (AF-V-04 Slice 2).

Contrat de référence : `docs/adr/0023-parameter-stability-plateau-v1.md` (Décisions 1-13). Module
top-level LEAF (Décision 11) : n'importe ni `engine.py`, ni `optimizer.py`, ni `dataset_split.py`,
ni `walk_forward.py` — preuve structurelle de la Décision 10 (impossibilité structurelle d'accéder
à la zone holdout finale réservée, jamais consultée ni consultable ici). Seuls `validation_run.py`
(contrats typés + `UnknownVerdictPolicy`, réutilisée telle quelle) et `scoring.py`
(`compute_sensitivity_filtered`/`compute_sensitivity_correlation`, réutilisées TELLES QUELLES,
jamais réimplémentées) sont importés.

`analyze_parameter_stability(candidates, best_params, spec) -> ParameterStabilityEvidence` est la
seule fonction publique : fonction PURE, aucun accès disque/réseau, aucun tirage aléatoire
(Décision 4/5 — protocole entièrement déterministe, aucune graine à dériver).
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

import scoring
from validation_run import (
    ParameterStabilityEvidence,
    ParameterStabilitySpecification,
    PercentileDistributionSummary,
    UnknownVerdictPolicy,
)

_DETERMINISTIC_SEARCH_MODES = frozenset({"single_var", "cross_zone", "grid"})
"""Duplication LOCALE et délibérée de `optimizer.DETERMINISTIC_DISPATCH_MODES` (valeurs LITTÉRALES
identiques, jamais un import — ce module reste un leaf, ADR 0023 Décision 3/11). Sert à la fois à
résoudre `neighborhood_applicability` (Décision 3) et de garde-fou défensif de `search_mode`
(mirroring la validation défensive de `n_simulations` par `monte_carlo.run_monte_carlo_simulation()`
— `ParameterStabilitySpecification` reste une dataclass frozen ordinaire, jamais construite en
confiance aveugle même si le seul constructeur sanctionné,
`build_parameter_stability_specification()`, ne peut structurellement pas produire une valeur
invalide)."""

_VALID_SEARCH_MODES = _DETERMINISTIC_SEARCH_MODES | {"general"}


def _neighborhood_applicability(search_mode: str) -> str:
    """ADR 0023 Décision 3 — champ EXPLICITE, jamais inféré après coup d'un voisinage vide."""
    return (
        "local_neighborhood_available"
        if search_mode in _DETERMINISTIC_SEARCH_MODES
        else "global_correlation_only"
    )


def _resolve_verdict(
    spec: ParameterStabilitySpecification,
) -> Tuple[str, Tuple[str, ...]]:
    """Séparation stricte preuve factuelle / verdict scientifique (ADR 0023 Décision 12, mirroring
    exact de Walk-Forward/Monte-Carlo) : `scientific_verdict` reste TOUJOURS `"INCONCLUSIVE"` sans
    `verdict_policy_id` enregistré ; `verdict_policy_id` fourni -> `UnknownVerdictPolicy` levée
    (réutilisée telle quelle depuis `validation_run.py`, jamais une classe dupliquée)."""
    if spec.verdict_policy_id is None:
        return "INCONCLUSIVE", (
            "Aucun verdict_policy_id enregistré pour cette ParameterStabilitySpecification — le "
            "verdict reste structurellement INCONCLUSIVE (ADR 0023 Décision 12).",
        )
    raise UnknownVerdictPolicy(
        f"verdict_policy_id={spec.verdict_policy_id!r} ne correspond à aucune politique "
        "enregistrée — aucune politique concrète de seuils PASS/FAIL n'existe encore dans ce "
        "dépôt (ADR 0023 Décision 12)."
    )


def _sensitivity_sample_size_filtered(candidates: list, param_name: str, best_params: dict) -> int:
    """Compte-seul, MÊMES critères EXACTS que `scoring.compute_sensitivity_filtered()` (ADR 0023
    Décision 6, correction BLOCKER B2) — jamais une réimplémentation du calcul de sensibilité
    lui-même, seulement de sa taille d'échantillon interne réelle."""
    return sum(
        1 for r in candidates
        if r.get("score", 0) > 0 and all(
            r["params"].get(k) == best_params.get(k) for k in best_params if k != param_name
        )
    )


def _sensitivity_sample_size_correlation(candidates: list, param_name: str) -> int:
    """Compte-seul, MÊMES critères EXACTS que `scoring.compute_sensitivity_correlation()`."""
    return sum(
        1 for r in candidates
        if r.get("score", 0) > 0 and r["params"].get(param_name) is not None
    )


def _is_structural_neighbor(candidate: dict, best_params: dict, param_name: str) -> bool:
    """Filtre de voisinage de la Décision 2 — DÉLIBÉRÉMENT différent de la clause de score de
    `compute_sensitivity_filtered()` : (i) mêmes CLÉS que `best_params` EXACTEMENT (exclut les
    "faux voisins" portant une clé supplémentaire), (ii) tous les autres paramètres égaux à
    `best_params`, (iii) n'est PAS `best_params` lui-même. AUCUNE exclusion sur le score ici —
    voir l'appelant pour la séparation accepté/rejeté (Décision 2/6, correction BLOCKER B1)."""
    params = candidate["params"]
    if params == best_params:
        return False
    if set(params.keys()) != set(best_params.keys()):
        return False
    return all(params.get(k) == best_params.get(k) for k in best_params if k != param_name)


def _hamming_distance(params: dict, best_params: dict) -> Optional[int]:
    """Distance de Hamming vis-à-vis de `best_params` — définie UNIQUEMENT pour un candidat
    partageant EXACTEMENT le même ensemble de clés (même discipline "faux voisin" que le filtre
    par-paramètre de la Décision 2) ; `None` sinon (candidat ignoré par la statistique jointe).
    Un candidat identique à `best_params` produit une distance `0`, naturellement exclue par le
    filtre `1 <= d <= 2` de l'appelant — aucune exclusion explicite supplémentaire nécessaire."""
    if set(params.keys()) != set(best_params.keys()):
        return None
    return sum(1 for k in best_params if params.get(k) != best_params.get(k))


def _distribution_summary(values: list) -> PercentileDistributionSummary:
    p5, p25, p50, p75, p95 = np.percentile(
        np.asarray(values, dtype=np.float64), [5, 25, 50, 75, 95],
    )
    return PercentileDistributionSummary(
        p5=float(p5), p25=float(p25), p50=float(p50), p75=float(p75), p95=float(p95),
    )


def _degradation_summaries(
    best_score: float, neighbor_scores: list,
) -> Tuple[Optional[PercentileDistributionSummary], Optional[PercentileDistributionSummary]]:
    """Formule de la Décision 2 : pourcentage `(best_score - neighbor_score) / abs(best_score)`
    (absent si `best_score == 0`, jamais une division par zéro masquée) ET delta absolu de points
    `best_score - neighbor_score` (toujours défini, jamais divisé, Décision 6) — les DEUX, jamais
    un seul, sur les voisins non rejetés uniquement (l'appelant filtre déjà `score > 0` avant
    d'appeler cette fonction)."""
    if not neighbor_scores:
        return None, None
    points_summary = _distribution_summary([best_score - s for s in neighbor_scores])
    if best_score == 0:
        return None, points_summary
    pct_summary = _distribution_summary(
        [(best_score - s) / abs(best_score) for s in neighbor_scores]
    )
    return pct_summary, points_summary


def analyze_parameter_stability(
    candidates: Tuple[dict, ...],
    best_params: dict,
    spec: ParameterStabilitySpecification,
) -> ParameterStabilityEvidence:
    """Orchestre le protocole Parameter Stability V1 (ADR 0023) — fonction PURE. `candidates` :
    pool de candidats DÉJÀ évalués (Décision 1, `Tuple[dict, ...]`, chaque élément portant au
    minimum `params: dict`/`score: float`), fourni par l'appelant, jamais recalculé ici.

    `search_mode` invalide -> `ValueError` immédiat, AVANT tout calcul (Décision 9). Résolution du
    verdict scientifique ensuite (peut lever `UnknownVerdictPolicy`, AVANT le raccourci
    zéro-candidat — mirroring exact de l'ordre retenu par `monte_carlo.run_monte_carlo_simulation()`
    pour `n_simulations`). `n_candidates_total == 0` -> `zero_candidates_input=True`, jamais une
    exception (Décision 7). `best_params` absent du pool -> `ValueError` (Décision 9, égalité
    stricte de `dict`). `execution_status` reste TOUJOURS `"completed"` en V1 (Décision 11)."""
    if spec.search_mode not in _VALID_SEARCH_MODES:
        raise ValueError(
            f"search_mode={spec.search_mode!r} invalide — attendu un de "
            f"{sorted(_VALID_SEARCH_MODES)!r} (ADR 0023 Décision 9). `spec` reste une dataclass "
            "frozen ordinaire : ce garde-fou vit ici même si "
            "build_parameter_stability_specification() ne peut structurellement pas produire "
            "cette valeur."
        )
    scientific_verdict, verdict_reasons = _resolve_verdict(spec)
    neighborhood_applicability = _neighborhood_applicability(spec.search_mode)

    n_candidates_total = len(candidates)
    if n_candidates_total == 0:
        return ParameterStabilityEvidence(
            n_candidates_total=0,
            zero_candidates_input=True,
            search_mode=spec.search_mode,
            neighborhood_applicability=neighborhood_applicability,
            best_score=None,
            best_params=None,
            sensitivity={},
            sensitivity_sample_size_by_param={},
            n_neighbors_total_by_param={},
            n_neighbors_rejected_by_param={},
            degradation_by_param={},
            degradation_points_by_param={},
            n_hamming_le_2_total=0,
            n_hamming_le_2_rejected=0,
            degradation_hamming_le_2=None,
            execution_status="completed",
            scientific_verdict=scientific_verdict,
            verdict_reasons=verdict_reasons,
        )

    candidates_list = list(candidates)
    matching = [c for c in candidates_list if c["params"] == best_params]
    if not matching:
        raise ValueError(
            "best_params ne correspond à AUCUN candidat du pool fourni (égalité stricte de dict, "
            "ADR 0023 Décision 9) — un vainqueur incohérent avec son propre pool ne peut jamais "
            "être résolu à l'aveugle."
        )
    best_score = matching[0]["score"]

    active_params = tuple(best_params.keys())
    deterministic = spec.search_mode in _DETERMINISTIC_SEARCH_MODES

    sensitivity: Dict[str, float] = {}
    sensitivity_sample_size_by_param: Dict[str, int] = {}
    n_neighbors_total_by_param: Dict[str, int] = {}
    n_neighbors_rejected_by_param: Dict[str, int] = {}
    degradation_by_param: Dict[str, Optional[PercentileDistributionSummary]] = {}
    degradation_points_by_param: Dict[str, Optional[PercentileDistributionSummary]] = {}

    for param_name in active_params:
        if deterministic:
            sensitivity[param_name] = scoring.compute_sensitivity_filtered(
                candidates_list, param_name, best_params,
            )
            sensitivity_sample_size_by_param[param_name] = _sensitivity_sample_size_filtered(
                candidates_list, param_name, best_params,
            )
        else:
            sensitivity[param_name] = scoring.compute_sensitivity_correlation(
                candidates_list, param_name,
            )
            sensitivity_sample_size_by_param[param_name] = _sensitivity_sample_size_correlation(
                candidates_list, param_name,
            )

        neighbors = [
            c for c in candidates_list if _is_structural_neighbor(c, best_params, param_name)
        ]
        accepted = [c for c in neighbors if c.get("score", 0) > 0]
        rejected = [c for c in neighbors if c.get("score", 0) <= 0]
        n_neighbors_total_by_param[param_name] = len(neighbors)
        n_neighbors_rejected_by_param[param_name] = len(rejected)

        pct_summary, points_summary = _degradation_summaries(
            best_score, [c["score"] for c in accepted],
        )
        degradation_by_param[param_name] = pct_summary
        degradation_points_by_param[param_name] = points_summary

    hamming_neighbors = []
    for c in candidates_list:
        distance = _hamming_distance(c["params"], best_params)
        if distance is not None and 1 <= distance <= 2:
            hamming_neighbors.append(c)
    hamming_accepted = [c for c in hamming_neighbors if c.get("score", 0) > 0]
    hamming_rejected = [c for c in hamming_neighbors if c.get("score", 0) <= 0]
    n_hamming_le_2_total = len(hamming_neighbors)
    n_hamming_le_2_rejected = len(hamming_rejected)
    degradation_hamming_le_2, _hamming_points_unused = _degradation_summaries(
        best_score, [c["score"] for c in hamming_accepted],
    )

    return ParameterStabilityEvidence(
        n_candidates_total=n_candidates_total,
        zero_candidates_input=False,
        search_mode=spec.search_mode,
        neighborhood_applicability=neighborhood_applicability,
        best_score=best_score,
        best_params=best_params,
        sensitivity=sensitivity,
        sensitivity_sample_size_by_param=sensitivity_sample_size_by_param,
        n_neighbors_total_by_param=n_neighbors_total_by_param,
        n_neighbors_rejected_by_param=n_neighbors_rejected_by_param,
        degradation_by_param=degradation_by_param,
        degradation_points_by_param=degradation_points_by_param,
        n_hamming_le_2_total=n_hamming_le_2_total,
        n_hamming_le_2_rejected=n_hamming_le_2_rejected,
        degradation_hamming_le_2=degradation_hamming_le_2,
        execution_status="completed",
        scientific_verdict=scientific_verdict,
        verdict_reasons=verdict_reasons,
    )
