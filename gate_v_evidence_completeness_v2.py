"""
gate_v_evidence_completeness_v2.py — AF-V-07 Slice D1 (ADR 0025 Décision 21.6 / 21.11).

Complétude STRUCTURELLE des preuves WF / MC / Parameter Stability d'une campagne GATE V V2,
jugée sur des objets REÇUS (``GateVCampaignPlanV2`` + ``ValidationRun`` déjà chargés). Module pur :
aucune lecture de fichier, aucune donnée de marché, aucune écriture, aucune horloge, aucun accès
FINAL_HOLDOUT. Complétude ≠ verdict scientifique : aucune fonction ici ne produit PASS/FAIL/
Champion/verdict GATE V.

V1 intentionally remains frozen. This V2 implementation is independently versioned and protected by differential tests.

Ces tests (``tests/test_gate_v_evidence_completeness_v2.py``) jugent les mêmes preuves synthétiques
avec les prédicats privés de ``gate_v_campaign.py`` (couplés à ``GateVCampaignPlan``/OOS, jamais
importés ici ni modifiés) puis avec ceux-ci : issues égales, sauf six divergences V2 décidées, testées
une à une :
(1) un booléen n'est ni un compteur ni une mesure (V1 l'accepte car ``bool`` est un ``int``) ;
(2) un compteur structurel mal typé (``n_input_trades``, ``n_candidates_total``) lève toujours
    ``ValueError`` (V1 : ``TypeError``, ou preuve acceptée, ou statut différent) ;
(3) une entrée invalide (mapping non ``Mapping``, référence non hachable, preuve qui n'est pas une
    ``ValidationRun``) lève ``ValueError`` (V1 : ``AttributeError``/``TypeError`` non typé) ;
(4) les compteurs de voisinage Parameter Stability couvrent exactement les paramètres sélectionnés
    (le producteur les indexe par ``best_params`` ; V1 ne relie pas ces clés à ``best_params``) ;
(5) l'agrégat Walk-Forward doit égaler le recalcul de ``walk_forward.build_aggregate_result`` depuis
    les folds (V1 : trois compteurs seulement, alors que la policy lira ``oos_net_return_pct``) ;
(6) invariants producteur des faits élémentaires de chaque fold, contrôlés avant le recalcul d'agrégat :
    ``net_ret_pct``, ``score_test``, ``gross_win``, ``gross_loss`` finis et non booléens, sommes brutes
    >= 0, ``score_test`` dans [0, 100] (``scoring.compute_score`` le borne) ; ``n_win`` entier non
    booléen avec ``0 <= n_win <= n_trades`` ; sur un fold zéro trade, ``gross_win == gross_loss ==
    n_win == 0`` et ``score_test == 0`` (le producteur les force). Sans cela, un fold falsifié
    produirait un agrégat recalculé « cohérent » (V1 ne contrôle rien de cela). Relations du moteur sur un
    fold avec trades : ``n_win > 0`` <=> ``gross_win > 0`` ; tous gagnants => ``gross_loss == 0`` (la
    réciproque est fausse : un trade à résultat nul est une « perte » sans gross_loss) ; ``win_rate ==
    n_win / n_trades * 100`` ; ``profit_factor == gross_win / gross_loss`` si ``gross_loss > 0``, sinon
    ``+inf`` : valide et canonique, ``isfinite`` ne lui est jamais appliqué.

Hors périmètre V2 (pas une divergence numérotée) : le cas OOS. V1 juge aussi une preuve OOS ; une campagne
V2 ne référence jamais l'OOS avant la clôture (Décision 21.6), donc ``validate_scoped_evidence_run_v2``
refuse ``oos`` et tout ``validation_type`` inconnu.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from atomic_json_store import validate_portable_identifier
from gate_v_campaign_plan_v2 import GateVCampaignPlanV2
from gate_v_preregistration import compute_fold_definitions_hash
from walk_forward import build_aggregate_result
from validation_run import (
    VALIDATION_TYPE_MONTE_CARLO,
    VALIDATION_TYPE_PARAMETER_STABILITY,
    VALIDATION_TYPE_WALK_FORWARD,
    AggregateResult,
    FoldDefinition,
    FoldResult,
    FoldSelection,
    MonteCarloEvidence,
    MonteCarloSpecification,
    ParameterStabilityEvidence,
    ParameterStabilitySpecification,
    ValidationRun,
    WalkForwardEvidence,
    WalkForwardSpecification,
    build_monte_carlo_specification,
    build_parameter_stability_specification,
)

__all__ = [
    "gate_v_v2_validation_run_id",
    "validate_scoped_evidence_run_v2",
    "walk_forward_evidence_complete_v2",
    "monte_carlo_evidence_complete_v2",
    "parameter_stability_evidence_complete_v2",
    "GateVPreHoldoutEvidenceFacts",
    "evaluate_pre_holdout_evidence_v2",
]

_INTERNAL_VALIDATION_TYPES = (
    VALIDATION_TYPE_WALK_FORWARD,
    VALIDATION_TYPE_MONTE_CARLO,
    VALIDATION_TYPE_PARAMETER_STABILITY,
)


def _require_plan_v2(plan) -> None:
    if not isinstance(plan, GateVCampaignPlanV2):
        raise ValueError("plan doit être un GateVCampaignPlanV2 validé.")


def gate_v_v2_validation_run_id(
    plan: GateVCampaignPlanV2, validation_type: str, *, fold_id: Optional[str] = None,
) -> str:
    """Identifiant déterministe, scopé campagne, d'une preuve interne V2 (forme V1, espace
    ``gate_v_v2_<hex>_...`` disjoint de V1 par construction du ``campaign_id`` V2)."""
    _require_plan_v2(plan)
    if not isinstance(validation_type, str) or validation_type not in _INTERNAL_VALIDATION_TYPES:
        raise ValueError("validation_type doit être une preuve interne GATE V reconnue.")
    if validation_type == VALIDATION_TYPE_PARAMETER_STABILITY:
        if not isinstance(fold_id, str) or fold_id not in plan.expected_fold_ids:
            raise ValueError("fold_id doit appartenir aux folds attendus de la campagne.")
        suffix = f"_{fold_id}"
    elif fold_id is not None:
        raise ValueError("fold_id n'est autorisé que pour Parameter Stability.")
    else:
        suffix = ""
    return validate_portable_identifier(
        f"{plan.campaign_id}_{validation_type}{suffix}", "validation_run_id",
    )


def _evidence_field(value, name: str):
    """Les enregistrements imbriqués d'une ValidationRun sont des dataclasses en mémoire mais des
    dict/list une fois rechargés depuis JSON : les deux formes doivent donner le même jugement."""
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def validate_scoped_evidence_run_v2(
    plan: GateVCampaignPlanV2, run_id: str, validation_type: str,
    evidence_by_validation_run_id: Mapping[str, ValidationRun],
) -> Optional[ValidationRun]:
    """Preuve interne « scoped » à la campagne V2 : ``None`` si la référence est absente du mapping
    (preuve manquante, pas une erreur), la ``ValidationRun`` si sa provenance est celle du plan,
    ``ValueError`` si elle est étrangère ou incohérente. Pas de cas OOS : une campagne V2 ne
    référence jamais l'OOS avant la clôture (Décision 21.6)."""
    _require_plan_v2(plan)
    if validation_type not in _INTERNAL_VALIDATION_TYPES:
        raise ValueError("validation_type doit être une preuve interne GATE V reconnue.")
    if not isinstance(evidence_by_validation_run_id, Mapping):
        raise ValueError("evidence_by_validation_run_id doit être un mapping de ValidationRun.")
    if not isinstance(run_id, str):
        raise ValueError("run_id doit être un identifiant de preuve (chaîne).")
    run = evidence_by_validation_run_id.get(run_id)
    if run is None:
        return None
    if not isinstance(run, ValidationRun) or run.validation_run_id != run_id:
        raise ValueError(f"validation_run_id {run_id!r} incohérent ou étranger à la campagne.")
    if (
        run.validation_type != validation_type
        or run.dataset_snapshot_id != plan.dataset_snapshot_id
        or run.split_plan_id != plan.split_plan_id
        or run.strategy_name != plan.strategy_name
        or run.status != "completed"
    ):
        raise ValueError(f"Preuve {run_id!r} de type, statut ou provenance étrangère à la campagne.")
    if run.research_run_id != plan.research_run_id:
        raise ValueError(f"Preuve {run_id!r} issue d'un autre ResearchRun/campagne.")
    if _evidence_field(run.evidence, "scientific_verdict") != "INCONCLUSIVE":
        raise ValueError(f"Preuve {run_id!r} avec verdict scientifique sans policy enregistrée.")
    if validation_type in (VALIDATION_TYPE_WALK_FORWARD, VALIDATION_TYPE_MONTE_CARLO) and (
        run.strategy_params != plan.base_params
    ):
        raise ValueError(f"Paramètres de stratégie {validation_type} étrangers au plan.")
    return run


def _is_count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _recomputed_fold_definitions_hash(definitions) -> str:
    """Hash des bornes de folds de la preuve, par la formule UNIQUE de la Slice B (jamais une
    troisième réimplémentation). Une définition rechargée de JSON (dict) est reconstruite en
    ``FoldDefinition`` : une forme inattendue (clé en trop ou manquante) est une erreur."""
    folds = []
    for item in definitions:
        if isinstance(item, dict):
            try:
                item = FoldDefinition(**item)
            except TypeError as exc:
                raise ValueError("Définition de fold Walk-Forward de forme inattendue.") from exc
        folds.append(item)
    try:
        return compute_fold_definitions_hash(folds)
    except TypeError as exc:
        raise ValueError("Définition de fold Walk-Forward de type inattendu.") from exc


def _hydrate(cls, value):
    return cls(**value) if isinstance(value, dict) else value


def _recomputed_aggregate(folds) -> AggregateResult:
    """Agrégat que le PRODUCTEUR (``walk_forward.build_aggregate_result``, pur) calcule depuis les folds.
    Les folds rechargés de JSON (dict) sont reconstruits en dataclasses avant le calcul."""
    try:
        results = tuple(
            _hydrate(FoldResult, {
                **fold, "definition": _hydrate(FoldDefinition, fold["definition"]),
                "selection": _hydrate(FoldSelection, fold["selection"]),
            }) if isinstance(fold, dict) else fold
            for fold in folds
        )
        return build_aggregate_result(results)
    except (TypeError, KeyError, AttributeError, ValueError, ArithmeticError) as exc:
        raise ValueError("Agrégat Walk-Forward non recalculable depuis les folds.") from exc


def _aggregate_matches_folds(aggregate, folds) -> bool:
    """Égalité exacte champ à champ (NaN, booléen, flottant à la place d'un compteur : refusés)."""
    expected = _recomputed_aggregate(folds)
    counters = ("n_folds", "n_folds_zero_trade", "total_oos_trades")
    for field in dataclasses.fields(AggregateResult):
        actual = _evidence_field(aggregate, field.name)
        if isinstance(actual, bool) or actual != getattr(expected, field.name):
            return False
        if field.name in counters and not _is_count(actual):
            return False
    return True


def _check_traded_fold_relations(fold, fold_id, n_trades: int, n_win: int) -> None:
    """Relations imposées par ``engine._compute_stats`` à un fold avec trades : un gagnant a un résultat > 0
    (``n_win > 0`` <=> ``gross_win > 0``) ; tous gagnants => aucune perte brute ; un trade à résultat nul est
    classé « perte » sans changer ``gross_loss`` (``gross_loss == 0`` n'implique donc PAS ``n_win == n_trades``) ;
    ``win_rate = n_win / n_trades * 100`` ; ``profit_factor = gross_win / gross_loss`` si ``gross_loss > 0``
    sinon ``+inf`` (valeur canonique, jamais soumise à ``isfinite``)."""
    gross_win = _evidence_field(fold, "gross_win")
    gross_loss = _evidence_field(fold, "gross_loss")
    if (n_win > 0) != (gross_win > 0) or (n_win == n_trades and gross_loss != 0):
        raise ValueError(f"Fold {fold_id} : gagnants et sommes brutes incompatibles avec le moteur.")
    win_rate = _evidence_field(fold, "win_rate")
    if not _is_finite_number(win_rate) or win_rate != n_win / n_trades * 100:
        raise ValueError(f"Fold {fold_id} : win_rate incohérent avec n_win / n_trades * 100.")
    profit_factor = _evidence_field(fold, "profit_factor")
    expected = gross_win / gross_loss if gross_loss > 0 else math.inf
    if isinstance(profit_factor, bool) or not isinstance(profit_factor, (int, float)) or profit_factor != expected:
        raise ValueError(f"Fold {fold_id} : profit_factor incohérent avec gross_win / gross_loss.")


def walk_forward_evidence_complete_v2(plan: GateVCampaignPlanV2, run: ValidationRun) -> bool:
    """``True`` si la preuve Walk-Forward couvre exactement les folds attendus et est cohérente ;
    ``False`` si elle est structurellement incomplète ; ``ValueError`` si elle est incohérente ou
    contredit le plan. Jamais un verdict scientifique."""
    _require_plan_v2(plan)
    if not isinstance(run, ValidationRun):
        raise ValueError("La preuve Walk-Forward doit être une ValidationRun.")
    if not isinstance(run.specification, WalkForwardSpecification) or run.specification != plan.walk_forward_specification:
        raise ValueError("La spécification Walk-Forward diffère du plan de campagne.")
    if not isinstance(run.evidence, WalkForwardEvidence):
        raise ValueError("Preuve Walk-Forward de type incohérent.")
    evidence = run.evidence
    if evidence.execution_status != "completed" or evidence.aggregate is None:
        return False
    folds = evidence.fold_results
    if tuple(_evidence_field(fold, "fold_id") for fold in folds) != plan.expected_fold_ids:
        return False
    for fold in folds:
        fold_id = _evidence_field(fold, "fold_id")
        definition = _evidence_field(fold, "definition")
        selection = _evidence_field(fold, "selection")
        n_trades = _evidence_field(fold, "n_trades")
        zero_trade = _evidence_field(fold, "zero_trade_oos")
        if (not _is_count(n_trades) or n_trades < 0
                or not isinstance(zero_trade, bool) or zero_trade != (n_trades == 0)):
            raise ValueError(f"Fold {fold_id} : compte ou indicateur zéro trade TEST incohérent.")
        # Faits élémentaires du fold, contrôlés AVANT que l'agrégat recalculé serve de preuve de cohérence :
        # finis, jamais booléens ; sommes brutes >= 0. ``profit_factor`` n'est PAS concerné (+inf légitime).
        if not all(_is_finite_number(_evidence_field(fold, name)) for name in (
            "net_ret_pct", "score_test", "gross_win", "gross_loss",
        )) or _evidence_field(fold, "gross_win") < 0 or _evidence_field(fold, "gross_loss") < 0:
            raise ValueError(f"Fold {fold_id} : rendement, score ou sommes brutes non finis, booléens ou négatifs.")
        # Le producteur borne tout score à [0, 100] et le force à 0.0 sans trade (optimizer.py).
        score_test = _evidence_field(fold, "score_test")
        if not 0 <= score_test <= 100 or (n_trades == 0 and score_test != 0):
            raise ValueError(f"Fold {fold_id} : score_test hors de [0, 100] ou non nul sans trade.")
        if n_trades == 0 and (
            _evidence_field(fold, "net_ret_pct") != 0.0
            or any(_evidence_field(fold, name) is not None for name in (
                "profit_factor", "win_rate", "expectancy",
            ))
        ):
            raise ValueError(f"Fold {fold_id} : métrique inventée sur zéro trade TEST.")
        n_win = _evidence_field(fold, "n_win")
        if not _is_count(n_win) or not 0 <= n_win <= n_trades or (n_trades == 0 and any(
            _evidence_field(fold, name) != 0 for name in ("gross_win", "gross_loss")
        )):
            raise ValueError(f"Fold {fold_id} : gagnants ou sommes brutes incohérents avec le compte de trades.")
        if n_trades > 0:
            _check_traded_fold_relations(fold, fold_id, n_trades, n_win)
        candidates = _evidence_field(selection, "train_candidates_evaluated")
        # Divergence V1 décidée : un booléen n'est pas un nombre de candidats (V1 accepte True comme 1).
        if (
            _evidence_field(definition, "fold_id") != fold_id
            or _evidence_field(selection, "fold_id") != fold_id
            or _evidence_field(selection, "rank_in_train") != 1
            or _evidence_field(selection, "search_space_hash") != plan.search_space_hash
            or _evidence_field(selection, "algorithm") != plan.search_mode
            or not _is_count(candidates)
            or not 0 < candidates <= plan.budget_per_fold
        ):
            raise ValueError(f"Top-1 TRAIN ou search_space_hash incohérent pour {fold_id}.")
    definitions = [_evidence_field(fold, "definition") for fold in folds]
    if any(definition is None for definition in definitions):
        return False
    if _recomputed_fold_definitions_hash(definitions) != plan.expected_fold_definitions_hash:
        raise ValueError("Les bornes Walk-Forward ne correspondent pas aux folds de la campagne.")
    aggregate = evidence.aggregate
    if _evidence_field(aggregate, "n_folds") != len(plan.expected_fold_ids):
        return False
    if not _aggregate_matches_folds(aggregate, folds):
        raise ValueError("L'agrégat Walk-Forward diffère du recalcul depuis les folds (trades, zéro trade, métriques).")
    return True


def _is_finite_number(value) -> bool:
    """Un booléen n'est pas une mesure (même divergence V1 décidée que ``_is_count``)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


_PERCENTILES = ("p5", "p25", "p50", "p75", "p95")


def _distribution_complete(summary) -> bool:
    return summary is not None and all(
        _is_finite_number(_evidence_field(summary, percentile)) for percentile in _PERCENTILES
    )


_MC_ZERO_TRADE_NONE_FIELDS = (
    "observed_net_ret_pct", "observed_max_dd_trade_close_basis_pct",
    "observed_lag1_autocorrelation", "observed_longest_losing_streak",
    "sequence_risk_max_dd_trade_close_basis_pct", "sequence_risk_longest_losing_streak",
    "sampling_uncertainty_net_ret_pct", "sampling_uncertainty_max_dd_trade_close_basis_pct",
)


def monte_carlo_evidence_complete_v2(
    plan: GateVCampaignPlanV2, wf: Optional[ValidationRun], mc: ValidationRun,
) -> bool:
    """``True`` si la preuve Monte-Carlo est complète et issue de la Walk-Forward de la campagne ;
    ``False`` si incomplète ; ``ValueError`` si étrangère ou incohérente. ``wf`` absent (ou sans
    agrégat) : le compte de trades n'est pas comparé — la WF est alors elle-même incomplète (21.6)."""
    _require_plan_v2(plan)
    if not isinstance(mc, ValidationRun):
        raise ValueError("La preuve Monte-Carlo doit être une ValidationRun.")
    if wf is not None and (not isinstance(wf, ValidationRun) or not isinstance(wf.evidence, WalkForwardEvidence)):
        raise ValueError("La preuve source Walk-Forward doit être une ValidationRun Walk-Forward ou None.")
    if not isinstance(mc.specification, MonteCarloSpecification) or not isinstance(mc.evidence, MonteCarloEvidence):
        raise ValueError("Preuve Monte-Carlo de type incohérent.")
    if mc.specification != build_monte_carlo_specification(
        gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD), True,
    ):
        raise ValueError("Provenance Monte-Carlo étrangère à la campagne Walk-Forward.")
    evidence = mc.evidence
    if not _is_count(evidence.n_input_trades):
        raise ValueError("n_input_trades Monte-Carlo doit être un entier (jamais un booléen ni un flottant).")
    if wf is not None and wf.evidence.aggregate is not None:
        expected_trades = _evidence_field(wf.evidence.aggregate, "total_oos_trades")
        if evidence.n_input_trades != expected_trades or evidence.zero_trade_input != (expected_trades == 0):
            raise ValueError("Le compte des trades Monte-Carlo diffère du Walk-Forward.")
    if evidence.zero_trade_input and any(
        getattr(evidence, field_name) is not None for field_name in _MC_ZERO_TRADE_NONE_FIELDS
    ):
        raise ValueError("Monte-Carlo à zéro trade ne peut contenir de métrique inventée.")
    complete = evidence.execution_status == "completed"
    if not evidence.zero_trade_input:
        complete = complete and (
            _is_count(evidence.n_input_trades) and evidence.n_input_trades > 0
            and _is_finite_number(evidence.observed_net_ret_pct)
            and _is_finite_number(evidence.observed_max_dd_trade_close_basis_pct)
            and _is_count(evidence.observed_longest_losing_streak)
            and evidence.observed_longest_losing_streak >= 0
            and all(_distribution_complete(summary) for summary in (
                evidence.sequence_risk_max_dd_trade_close_basis_pct,
                evidence.sequence_risk_longest_losing_streak,
                evidence.sampling_uncertainty_net_ret_pct,
                evidence.sampling_uncertainty_max_dd_trade_close_basis_pct,
            ))
        )
    return complete


def parameter_stability_evidence_complete_v2(
    plan: GateVCampaignPlanV2, run: ValidationRun, fold_id: str, source_fold_result=None,
) -> bool:
    """``True`` si la Parameter Stability du fold ``fold_id`` est complète (voisinage exploitable,
    distributions finies) ; ``False`` si structurellement incomplète ; ``ValueError`` si sa provenance
    ou ses compteurs sont incohérents. ``source_fold_result`` (résultat du fold WF source) absent :
    la correspondance Top-1/pool TRAIN est sautée — la WF est alors elle-même incomplète (21.6)."""
    _require_plan_v2(plan)
    if not isinstance(fold_id, str) or fold_id not in plan.expected_fold_ids:
        raise ValueError("fold_id doit appartenir aux folds attendus de la campagne.")
    if not isinstance(run, ValidationRun):
        raise ValueError("La preuve Parameter Stability doit être une ValidationRun.")
    specification, evidence = run.specification, run.evidence
    if not isinstance(specification, ParameterStabilitySpecification) or not isinstance(
        evidence, ParameterStabilityEvidence,
    ):
        raise ValueError("Preuve Parameter Stability de type incohérent.")
    wf_id = gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
    if (
        specification != build_parameter_stability_specification(
            wf_id, plan.search_mode, True, source_fold_id=fold_id,
        )
        or evidence.search_mode != plan.search_mode
    ):
        raise ValueError(f"Provenance Parameter Stability incorrecte pour le fold {fold_id}.")
    if evidence.execution_status != "completed":
        return False
    if source_fold_result is not None:
        selection = _evidence_field(source_fold_result, "selection")
        if (
            selection is None
            or evidence.best_params != _evidence_field(selection, "selected_params")
            or evidence.best_score != _evidence_field(selection, "score_train")
            or evidence.n_candidates_total != _evidence_field(selection, "train_candidates_evaluated")
        ):
            raise ValueError(f"Parameter Stability {fold_id} ne correspond pas au Top-1/pool TRAIN du fold.")
    totals = evidence.n_neighbors_total_by_param
    rejected = evidence.n_neighbors_rejected_by_param
    if not isinstance(totals, dict) or not isinstance(rejected, dict):
        raise ValueError(f"Compteurs de voisins invalides pour le fold {fold_id}.")
    # Divergence V1 décidée : un compteur de pool absent/non entier est une ValueError (V1 : TypeError).
    if not _is_count(evidence.n_candidates_total):
        raise ValueError(f"n_candidates_total invalide pour le fold {fold_id}.")
    selected = set(evidence.best_params) if isinstance(evidence.best_params, dict) else set()
    if set(totals) != selected:
        raise ValueError(f"Compteurs de voisins du fold {fold_id} différents des paramètres sélectionnés.")
    for param, total in totals.items():
        rejection = rejected.get(param)
        if (
            not _is_count(total) or total < 0
            or not _is_count(rejection) or rejection < 0 or rejection > total
            or total > evidence.n_candidates_total - 1
        ):
            raise ValueError(f"Compteurs de voisins incohérents pour le fold {fold_id}.")
    if set(rejected) != set(totals):
        raise ValueError(f"Compteurs de voisins incomplets pour le fold {fold_id}.")
    usable = [param for param, total in totals.items() if total - rejected[param] > 0]
    if evidence.neighborhood_applicability != "local_neighborhood_available" or not usable:
        return False
    for param in usable:
        for summaries in (evidence.degradation_by_param, evidence.degradation_points_by_param):
            summary = summaries.get(param) if isinstance(summaries, dict) else None
            if not _distribution_complete(summary):
                return False
    return True


@dataclass(frozen=True)
class GateVPreHoldoutEvidenceFacts:
    """Faits de complétude interne d'une campagne V2 avant FINAL_HOLDOUT. Uniquement des booléens et
    des identifiants de folds : jamais un verdict, un score ni un statut de campagne."""

    walk_forward_complete: bool
    monte_carlo_complete: bool
    parameter_stability_complete_fold_ids: Tuple[str, ...]
    parameter_stability_incomplete_fold_ids: Tuple[str, ...]
    pre_holdout_evidence_complete: bool


def evaluate_pre_holdout_evidence_v2(
    plan: GateVCampaignPlanV2, evidence_by_validation_run_id: Mapping[str, ValidationRun],
) -> GateVPreHoldoutEvidenceFacts:
    """Juge WF, MC et Parameter Stability de TOUS les folds attendus sur des ``ValidationRun`` déjà
    chargées. Seuls les identifiants déterministes du plan font autorité : toute autre entrée du
    mapping est ignorée. Preuve absente = incomplète ; preuve étrangère ou incohérente = ``ValueError``."""
    _require_plan_v2(plan)
    wf = validate_scoped_evidence_run_v2(
        plan, gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD),
        VALIDATION_TYPE_WALK_FORWARD, evidence_by_validation_run_id,
    )
    mc = validate_scoped_evidence_run_v2(
        plan, gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO),
        VALIDATION_TYPE_MONTE_CARLO, evidence_by_validation_run_id,
    )
    wf_complete = walk_forward_evidence_complete_v2(plan, wf) if wf is not None else False
    mc_complete = monte_carlo_evidence_complete_v2(plan, wf, mc) if mc is not None else False
    source_folds = {
        fold_id: fold for fold in wf.evidence.fold_results
        if isinstance(fold_id := _evidence_field(fold, "fold_id"), str)
    } if wf is not None and isinstance(wf.evidence, WalkForwardEvidence) else {}
    complete_folds, incomplete_folds = [], []
    for fold_id in plan.expected_fold_ids:
        ps = validate_scoped_evidence_run_v2(
            plan, gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_PARAMETER_STABILITY, fold_id=fold_id),
            VALIDATION_TYPE_PARAMETER_STABILITY, evidence_by_validation_run_id,
        )
        # Sans fold WF source, seule la correspondance Top-1 est sautée (§21.6) ; la complétude globale
        # reste fail-closed car une WF dont un fold manque est elle-même incomplète.
        quality = ps is not None and parameter_stability_evidence_complete_v2(
            plan, ps, fold_id, source_folds.get(fold_id),
        )
        (complete_folds if quality else incomplete_folds).append(fold_id)
    return GateVPreHoldoutEvidenceFacts(
        walk_forward_complete=wf_complete,
        monte_carlo_complete=mc_complete,
        parameter_stability_complete_fold_ids=tuple(complete_folds),
        parameter_stability_incomplete_fold_ids=tuple(incomplete_folds),
        pre_holdout_evidence_complete=wf_complete and mc_complete and not incomplete_folds,
    )
