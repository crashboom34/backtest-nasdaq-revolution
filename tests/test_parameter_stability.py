"""
tests/test_parameter_stability.py — AF-V-04 Slice 2 : algorithme `parameter_stability.py`
(voisinage, dégradation).

Contrat de référence : `docs/adr/0023-parameter-stability-plateau-v1.md`, Décision 13 (matrice
TDD). `parameter_stability.py` reste un leaf sans dépendance moteur NI `optimizer.py` (Décision
10/11) — vérifié ici par un test d'import statique, jamais par confiance aveugle. Le round-trip
disque complet (`build_validation_run()` -> `save_validation_run()` -> `load_validation_run()`)
sur une fixture à la main est déjà couvert par les tests Slice 1 de `tests/test_validation_run.py`
(contrats génériques déjà enregistrés dans `_VALIDATION_TYPES`) — non dupliqué ici, sauf un test
d'intégration léger qui fait tourner l'algorithme réel avant de le persister, pour prouver que la
sortie RÉELLE (pas seulement une fixture à la main) round-trippe.

**Fingerprint `ParameterStabilitySemanticsMismatch` — NON couvert, ici ni ailleurs, et documenté
honnêtement comme tel plutôt que silencieusement présumé** : cette exception est déclarée
(`validation_run.py`) et sa subclass-`ValueError` est testée (`tests/test_validation_run.py`,
`test_parameter_stability_semantics_mismatch_is_a_value_error_subclass`), mais **aucun code de ce
dépôt ne la lève réellement** — contrairement à `WalkForwardSemanticsMismatch`, réellement levée
par `walk_forward.validate_resume_walk_forward_semantics()`, `load_validation_run()` ne compare
JAMAIS `parameter_stability_semantics_version` (ni `monte_carlo_semantics_version`, même lacune
pré-existante) à la constante courante. Un mécanisme de vérification de version au chargement
appartiendrait à la Décision 8 de l'ADR 0023 (persistance dédiée sous
`results/job_xxx/parameter_stability/`), **explicitement hors scope de cette tranche** (Slice 2) —
voir le prompt de mission. Tant que ce mécanisme n'existe pas, la ligne « Fingerprint » de la
matrice Décision 13 reste non couverte ; ne pas prétendre le contraire ici.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import parameter_stability
import scoring
from parameter_stability import analyze_parameter_stability
from validation_run import (
    PARAMETER_STABILITY_SEMANTICS_VERSION,
    ParameterStabilityEvidence,
    UnknownVerdictPolicy,
    build_parameter_stability_specification,
    build_validation_run,
    load_validation_run,
    save_validation_run,
)


def _spec(search_mode="grid", verdict_policy_id=None, source_candidates_from_optimized_search=True):
    """Construction via le builder sanctionné (Slice 1, déjà validé) — jamais court-circuité ici,
    contrairement aux tests d'algorithme Monte-Carlo qui construisent `MonteCarloSpecification`
    directement pour contrôler `n_simulations`/`master_seed` : `ParameterStabilitySpecification`
    n'a aucun champ équivalent à contrôler librement, le builder suffit toujours."""
    return build_parameter_stability_specification(
        source_validation_run_id="val_test_fixture",
        search_mode=search_mode,
        source_candidates_from_optimized_search=source_candidates_from_optimized_search,
        verdict_policy_id=verdict_policy_id,
    )


def _candidate(params, score):
    return {"params": dict(params), "score": score, "stats": {}, "filtered": score <= 0,
            "filter_reason": "" if score > 0 else "rejected"}


class TestNoEngineDependency:
    """ADR 0023 Décision 10/11 : `parameter_stability.py` ne doit structurellement jamais pouvoir
    accéder à la zone holdout finale réservée — preuve par analyse statique des imports réels
    (AST), jamais par recherche textuelle naïve."""

    def test_static_import_analysis_finds_no_engine_optimizer_dataset_split_or_walk_forward(self):
        source = Path(parameter_stability.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        forbidden = {"engine", "optimizer", "dataset_split", "walk_forward"}
        assert imported.isdisjoint(forbidden), imported & forbidden

    def test_module_and_its_tests_never_reference_final_holdout_or_holdout_access_event(self):
        forbidden_holdout_token = "FINAL_" + "HOLDOUT"
        forbidden_access_event_token = "Holdout" + "AccessEvent"
        module_source = Path(parameter_stability.__file__).read_text(encoding="utf-8")
        test_source = Path(__file__).read_text(encoding="utf-8")
        for text, label in (
            (module_source, "parameter_stability.py"),
            (test_source, "test_parameter_stability.py"),
        ):
            assert forbidden_holdout_token not in text, label
            assert forbidden_access_event_token not in text, label


class TestSearchModeValidation:
    """ADR 0023 Décision 9 — `search_mode` invalide -> `ValueError` immédiat. `spec` reste une
    dataclass frozen ordinaire (même dette disciplinaire assumée que `MonteCarloSpecification`) :
    ce garde-fou doit vivre dans l'algorithme, jamais supposé impossible juste parce que
    `build_parameter_stability_specification()` ne peut structurellement pas produire cette
    valeur."""

    def _spec_with_raw_mode(self, mode):
        spec = _spec()
        return dataclasses.replace(spec, search_mode=mode)

    def test_invalid_search_mode_raises_value_error(self):
        with pytest.raises(ValueError):
            analyze_parameter_stability((), {}, self._spec_with_raw_mode("bayesian"))

    def test_invalid_search_mode_raises_even_with_zero_candidates(self):
        with pytest.raises(ValueError):
            analyze_parameter_stability((), {"a": 1}, self._spec_with_raw_mode("not_real"))

    @pytest.mark.parametrize("mode", ["single_var", "cross_zone", "grid", "general"])
    def test_valid_modes_do_not_raise(self, mode):
        evidence = analyze_parameter_stability((), {}, self._spec_with_raw_mode(mode))
        assert isinstance(evidence, ParameterStabilityEvidence)


class TestVerdict:
    """ADR 0023 Décision 12 : séparation stricte preuve factuelle / verdict scientifique --
    `INCONCLUSIVE` sans politique, `UnknownVerdictPolicy` sinon (réutilisée telle quelle)."""

    def test_no_verdict_policy_id_yields_inconclusive_with_explicit_reason(self):
        evidence = analyze_parameter_stability((), {}, _spec(verdict_policy_id=None))

        assert evidence.scientific_verdict == "INCONCLUSIVE"
        assert len(evidence.verdict_reasons) >= 1
        assert all(isinstance(r, str) and r for r in evidence.verdict_reasons)

    def test_verdict_policy_id_provided_raises_unknown_verdict_policy(self):
        with pytest.raises(UnknownVerdictPolicy):
            analyze_parameter_stability((), {}, _spec(verdict_policy_id="some_policy_v1"))

    def test_verdict_policy_id_provided_raises_before_any_zero_candidates_shortcut(self):
        with pytest.raises(UnknownVerdictPolicy):
            analyze_parameter_stability((), {}, _spec(verdict_policy_id="some_policy_v1"))


class TestZeroCandidates:
    """ADR 0023 Décision 7 : jamais une erreur, une observation factuelle honnête."""

    def test_zero_candidates_never_raises_and_marks_zero_candidates_input(self):
        evidence = analyze_parameter_stability((), {"stop_pct": 1.0}, _spec())

        assert isinstance(evidence, ParameterStabilityEvidence)
        assert evidence.zero_candidates_input is True
        assert evidence.n_candidates_total == 0
        assert evidence.execution_status == "completed"
        assert evidence.best_score is None
        assert evidence.best_params is None
        assert evidence.sensitivity == {}
        assert evidence.sensitivity_sample_size_by_param == {}
        assert evidence.n_neighbors_total_by_param == {}
        assert evidence.n_neighbors_rejected_by_param == {}
        assert evidence.degradation_by_param == {}
        assert evidence.degradation_points_by_param == {}
        assert evidence.n_hamming_le_2_total == 0
        assert evidence.n_hamming_le_2_rejected == 0
        assert evidence.degradation_hamming_le_2 is None

    def test_zero_candidates_still_reports_neighborhood_applicability_from_search_mode(self):
        evidence = analyze_parameter_stability((), {}, _spec(search_mode="general"))
        assert evidence.neighborhood_applicability == "global_correlation_only"

        evidence2 = analyze_parameter_stability((), {}, _spec(search_mode="grid"))
        assert evidence2.neighborhood_applicability == "local_neighborhood_available"


class TestBestParamsMustBeInPool:
    """ADR 0023 Décision 9 : un `best_params` qui ne correspond à AUCUN candidat évalué est
    incohérent -- `ValueError` immédiat, égalité stricte de `dict`."""

    def test_best_params_absent_from_pool_raises_value_error(self):
        candidates = (_candidate({"stop_pct": 1.0}, 10.0), _candidate({"stop_pct": 2.0}, 20.0))
        with pytest.raises(ValueError):
            analyze_parameter_stability(candidates, {"stop_pct": 999.0}, _spec())

    def test_best_params_present_does_not_raise(self):
        candidates = (_candidate({"stop_pct": 1.0}, 10.0), _candidate({"stop_pct": 2.0}, 20.0))
        evidence = analyze_parameter_stability(candidates, {"stop_pct": 2.0}, _spec())
        assert evidence.best_score == pytest.approx(20.0)
        assert evidence.best_params == {"stop_pct": 2.0}


class TestSensitivityReusedAsIs:
    """ADR 0023 Décision 2 : `sensitivity` réutilise TEL QUEL `scoring.compute_sensitivity_filtered
    ()`/`compute_sensitivity_correlation()` -- byte-identique à un appel direct."""

    def test_sensitivity_is_byte_identical_to_direct_scoring_call_in_grid_mode(self):
        best = {"stop_pct": 1.0, "target_pct": 5.0}
        candidates = (
            _candidate({"stop_pct": 1.0, "target_pct": 5.0}, 50.0),
            _candidate({"stop_pct": 1.2, "target_pct": 5.0}, 55.0),
            _candidate({"stop_pct": 0.8, "target_pct": 5.0}, 40.0),
            _candidate({"stop_pct": 1.0, "target_pct": 6.0}, 60.0),
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="grid"))

        expected_stop = scoring.compute_sensitivity_filtered(list(candidates), "stop_pct", best)
        expected_target = scoring.compute_sensitivity_filtered(list(candidates), "target_pct", best)
        assert evidence.sensitivity["stop_pct"] == expected_stop
        assert evidence.sensitivity["target_pct"] == expected_target

    def test_sensitivity_is_byte_identical_to_direct_scoring_call_in_general_mode(self):
        best = {"stop_pct": 1.0}
        candidates = tuple(
            _candidate({"stop_pct": float(i)}, float(i) * 3.0) for i in range(1, 15)
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="general"))

        expected = scoring.compute_sensitivity_correlation(list(candidates), "stop_pct")
        assert evidence.sensitivity["stop_pct"] == expected

    def test_sensitivity_sentinel_below_three_filtered_neighbors_is_distinguished_by_sample_size(
        self,
    ):
        best = {"stop_pct": 1.0}
        # Un seul autre candidat partageant les mêmes "autres paramètres" (ici aucun autre
        # paramètre) -> len(filtered) == 2 < 3 -> sentinel 0.0, jamais confondu avec une vraie
        # sensibilité nulle.
        candidates = (
            _candidate({"stop_pct": 1.0}, 50.0),
            _candidate({"stop_pct": 1.2}, 55.0),
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="grid"))

        assert evidence.sensitivity["stop_pct"] == 0.0
        assert evidence.sensitivity_sample_size_by_param["stop_pct"] == 2

    def test_sensitivity_real_zero_at_sufficient_sample_size_is_distinguished_from_sentinel(self):
        best = {"stop_pct": 1.0}
        # >= 3 candidats filtrés, tous strictement le MÊME score -> écart-type réellement nul,
        # jamais un sentinel (sample_size >= 3 le prouve).
        candidates = (
            _candidate({"stop_pct": 1.0}, 50.0),
            _candidate({"stop_pct": 1.1}, 50.0),
            _candidate({"stop_pct": 1.2}, 50.0),
            _candidate({"stop_pct": 1.3}, 50.0),
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="grid"))

        assert evidence.sensitivity["stop_pct"] == 0.0
        assert evidence.sensitivity_sample_size_by_param["stop_pct"] == 4

    def test_general_mode_sentinel_below_ten_pairs_is_distinguished_by_sample_size(self):
        best = {"stop_pct": 1.0}
        candidates = tuple(_candidate({"stop_pct": float(i)}, float(i)) for i in range(1, 5))
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="general"))

        assert evidence.sensitivity["stop_pct"] == 0.0
        assert evidence.sensitivity_sample_size_by_param["stop_pct"] == 4


class TestNeighborFilterDiffersFromSensitivityFilterOnRejectedCandidates:
    """ADR 0023 Décision 2 : la clause `score > 0` de `compute_sensitivity_filtered()` NE DOIT PAS
    être héritée par la statistique de dégradation de voisinage -- preuve avec des voisins À LA
    FOIS acceptés et rejetés."""

    def test_neighbors_count_both_accepted_and_rejected_but_degradation_only_uses_accepted(self):
        best = {"stop_pct": 1.0}
        candidates = (
            _candidate({"stop_pct": 1.0}, 100.0),   # best_params lui-même
            _candidate({"stop_pct": 1.1}, 90.0),    # voisin accepté
            _candidate({"stop_pct": 1.2}, 80.0),    # voisin accepté
            _candidate({"stop_pct": 1.3}, 0.0),     # voisin REJETÉ (score <= 0)
            _candidate({"stop_pct": 1.4}, -5.0),    # voisin REJETÉ (score <= 0)
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="grid"))

        assert evidence.n_neighbors_total_by_param["stop_pct"] == 4
        assert evidence.n_neighbors_rejected_by_param["stop_pct"] == 2

        summary = evidence.degradation_by_param["stop_pct"]
        # Distribution calculée UNIQUEMENT sur les 2 voisins acceptés (90.0, 80.0).
        expected_values = sorted([(100.0 - 90.0) / 100.0, (100.0 - 80.0) / 100.0])
        assert summary.p5 == pytest.approx(min(expected_values), abs=0.05)
        assert summary.p95 == pytest.approx(max(expected_values), abs=0.05)


class TestBestParamsExcludedFromOwnNeighborhood:
    """ADR 0023 Décision 2, correction MAJEUR M4 : `best_params` n'apparaît JAMAIS dans les
    candidats comptés par `n_neighbors_total_by_param`, PAR PARAMÈTRE ET PAR HAMMING."""

    def test_best_params_never_counted_as_its_own_neighbor_per_param(self):
        best = {"stop_pct": 1.0, "target_pct": 5.0}
        candidates = (
            _candidate(best, 100.0),
            _candidate({"stop_pct": 1.1, "target_pct": 5.0}, 90.0),
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="grid"))

        assert evidence.n_neighbors_total_by_param["stop_pct"] == 1
        assert evidence.n_neighbors_total_by_param["target_pct"] == 0

    def test_best_params_never_counted_in_hamming_joint_statistic(self):
        best = {"stop_pct": 1.0, "target_pct": 5.0}
        candidates = (
            _candidate(best, 100.0),
            _candidate({"stop_pct": 1.1, "target_pct": 5.5}, 90.0),  # Hamming = 2
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="grid"))

        assert evidence.n_hamming_le_2_total == 1  # jamais 2 (best_params exclu, Hamming=0)


class TestExactParameterKeysRequired:
    """ADR 0023 Décision 2 : un candidat portant une clé SUPPLÉMENTAIRE absente de `best_params`
    n'est JAMAIS compté comme voisin structurel (exclusion des "faux voisins")."""

    def test_candidate_with_extra_key_is_never_counted_as_a_structural_neighbor(self):
        best = {"stop_pct": 1.0}
        candidates = (
            _candidate(best, 100.0),
            _candidate({"stop_pct": 1.1, "extra_param": 42}, 90.0),
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="grid"))

        assert evidence.n_neighbors_total_by_param["stop_pct"] == 0


class TestDegradationCorrectlySigned:
    """ADR 0023 Décision 1/2 : un voisin STRICTEMENT MEILLEUR que `best_params` (cas synthétique,
    `best_params` sélectionné selon un critère externe différent du score) produit une dégradation
    NÉGATIVE, jamais tronquée à zéro."""

    def test_a_strictly_better_neighbor_produces_negative_degradation(self):
        best = {"stop_pct": 1.0}
        candidates = (
            _candidate(best, 50.0),          # "best_params" choisi hors score (critère externe)
            _candidate({"stop_pct": 1.1}, 70.0),  # objectivement meilleur score
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="grid"))

        pct = evidence.degradation_by_param["stop_pct"]
        points = evidence.degradation_points_by_param["stop_pct"]
        assert pct.p50 < 0
        assert points.p50 < 0
        assert pct.p50 == pytest.approx((50.0 - 70.0) / 50.0)
        assert points.p50 == pytest.approx(50.0 - 70.0)


class TestDegradationAbsentWithoutNonRejectedNeighbors:
    """ADR 0023 Décision 7 : aucun voisin non rejeté pour un paramètre -- jamais bloquant, jamais
    une valeur inventée."""

    def test_all_neighbors_rejected_leaves_degradation_none_but_counters_honest(self):
        best = {"stop_pct": 1.0}
        candidates = (
            _candidate(best, 50.0),
            _candidate({"stop_pct": 1.1}, 0.0),
            _candidate({"stop_pct": 1.2}, -1.0),
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="grid"))

        assert evidence.n_neighbors_total_by_param["stop_pct"] == 2
        assert evidence.n_neighbors_rejected_by_param["stop_pct"] == 2
        assert evidence.degradation_by_param["stop_pct"] is None
        assert evidence.degradation_points_by_param["stop_pct"] is None

    def test_no_structural_neighbor_at_all_leaves_degradation_none(self):
        best = {"stop_pct": 1.0}
        candidates = (_candidate(best, 50.0),)
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="grid"))

        assert evidence.n_neighbors_total_by_param["stop_pct"] == 0
        assert evidence.degradation_by_param["stop_pct"] is None


class TestHammingJointSignalDistinctFromPerParameterAnalysis:
    """ADR 0023 Décision 2 (finding MAJEUR M2) : un candidat variant 2 paramètres SIMULTANÉMENT
    dégrade fortement le score, mais chaque paramètre pris séparément (Hamming=1, comparé à
    `best_params` sur cet axe seul) ne montre AUCUNE dégradation dans le pool -- `
    degradation_hamming_le_2` capture cette dégradation alors que `degradation_by_param` ne la voit
    pas."""

    def test_joint_degradation_invisible_per_param_is_captured_by_hamming_signal(self):
        best = {"stop_pct": 1.0, "target_pct": 5.0}
        candidates = (
            _candidate(best, 100.0),
            # Hamming=1 sur stop_pct seul : AUCUNE dégradation (score identique au best).
            _candidate({"stop_pct": 1.1, "target_pct": 5.0}, 100.0),
            # Hamming=1 sur target_pct seul : AUCUNE dégradation non plus.
            _candidate({"stop_pct": 1.0, "target_pct": 5.5}, 100.0),
            # Hamming=2 (les deux ensemble) : forte dégradation, invisible par paramètre.
            _candidate({"stop_pct": 1.1, "target_pct": 5.5}, 20.0),
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="grid"))

        # Chaque paramètre pris séparément ne voit AUCUNE dégradation (voisins à score identique).
        assert evidence.degradation_by_param["stop_pct"].p50 == pytest.approx(0.0)
        assert evidence.degradation_by_param["target_pct"].p50 == pytest.approx(0.0)

        # Le signal joint Hamming 1-2 AGRÈGE les 3 voisins (Hamming 1, 1, 2) -- il voit la
        # dégradation moyenne tirée vers le bas par le candidat joint, contrairement à une analyse
        # par paramètre qui ignorerait ce candidat sur chaque axe pris isolément à degradation == 0
        # pour les deux voisins Hamming=1.
        assert evidence.n_hamming_le_2_total == 3
        assert evidence.degradation_hamming_le_2 is not None
        # La dégradation du candidat joint (0.8) tire nettement le haut de la distribution vers
        # le haut, contrairement aux deux dégradations par-paramètre qui restent exactement à 0 —
        # valeur exacte non vérifiée ici (percentile interpolé sur 3 points), seule la présence du
        # signal l'est.
        assert evidence.degradation_hamming_le_2.p95 > 0.5

    def test_hamming_counters_separate_accepted_and_rejected_like_the_per_param_case(self):
        best = {"stop_pct": 1.0, "target_pct": 5.0}
        candidates = (
            _candidate(best, 100.0),
            _candidate({"stop_pct": 1.1, "target_pct": 5.5}, 20.0),   # Hamming=2, accepté
            _candidate({"stop_pct": 1.2, "target_pct": 5.6}, 0.0),    # Hamming=2, rejeté
            _candidate({"stop_pct": 1.3, "target_pct": 5.7}, -3.0),   # Hamming=2, rejeté
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="grid"))

        assert evidence.n_hamming_le_2_total == 3
        assert evidence.n_hamming_le_2_rejected == 2
        assert evidence.degradation_hamming_le_2 is not None  # calculé sur l'unique accepté


class TestSearchModeApplicability:
    """ADR 0023 Décision 3 : `"general"` reste honnêtement sans preuve de voisinage LOCAL."""

    def test_general_mode_yields_global_correlation_only_and_zero_structural_neighbors(self):
        # Deux paramètres qui varient CONJOINTEMENT sans jamais reproduire exactement la valeur
        # de l'AUTRE paramètre du vainqueur -- avec un seul paramètre actif, "tous les autres
        # paramètres égaux" serait vacuously vrai pour tout candidat (aucun "autre" axe à
        # distinguer), ce qui ne représente pas un espace de recherche "general" réaliste
        # (Décision 3 : la coïncidence EXACTE ne devient rare qu'avec plusieurs dimensions).
        best = {"stop_pct": 1.0, "target_pct": 5.0}
        candidates = (_candidate(best, 100.0),) + tuple(
            _candidate({"stop_pct": float(i) / 10.0, "target_pct": 5.0 + i}, float(i))
            for i in range(1, 20)
        )
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="general"))

        assert evidence.neighborhood_applicability == "global_correlation_only"
        assert evidence.n_neighbors_total_by_param["stop_pct"] == 0
        assert evidence.n_neighbors_rejected_by_param["stop_pct"] == 0
        # sensitivity reste peuplée (Spearman), jamais vide sous "general".
        assert "stop_pct" in evidence.sensitivity

    @pytest.mark.parametrize("mode", ["single_var", "cross_zone", "grid"])
    def test_deterministic_modes_yield_local_neighborhood_available(self, mode):
        best = {"stop_pct": 1.0}
        candidates = (_candidate(best, 50.0),)
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode=mode))
        assert evidence.neighborhood_applicability == "local_neighborhood_available"


class TestDeterminismBitForBit:
    """ADR 0023 Décision 5 : deux appels avec le MÊME pool DANS LE MÊME ORDRE produisent une
    `ParameterStabilityEvidence` bit-à-bit identique -- propriété garantie PAR CONSTRUCTION
    (aucun hasard), pas seulement testée empiriquement."""

    def test_two_calls_with_the_same_ordered_pool_produce_an_identical_evidence(self):
        best = {"stop_pct": 1.0, "target_pct": 5.0}
        candidates = (
            _candidate(best, 100.0),
            _candidate({"stop_pct": 1.1, "target_pct": 5.0}, 90.0),
            _candidate({"stop_pct": 0.9, "target_pct": 5.0}, 85.0),
            _candidate({"stop_pct": 1.0, "target_pct": 6.0}, 95.0),
            _candidate({"stop_pct": 1.1, "target_pct": 6.0}, 20.0),
        )
        spec = _spec(search_mode="grid")

        evidence_a = analyze_parameter_stability(candidates, best, spec)
        evidence_b = analyze_parameter_stability(candidates, best, spec)

        assert evidence_a == evidence_b


class TestNoInventedJudgmentField:
    """ADR 0023 Décision 6 : aucun jugement "plateau large"/"pic isolé"/"stable"/"instable" -- ce
    jugement reste de la responsabilité exclusive d'une politique de verdict pré-enregistrée."""

    def test_no_stability_judgment_field_exists_on_parameter_stability_evidence(self):
        field_names = {f.name for f in dataclasses.fields(ParameterStabilityEvidence)}
        for forbidden_substring in ("stable", "instab", "plateau", "isole", "isolé"):
            assert not any(forbidden_substring in name.lower() for name in field_names), (
                forbidden_substring, field_names,
            )


class TestNCandidatesTotalAndSearchModeReportedAsIs:
    def test_n_candidates_total_and_search_mode_are_reported_as_is(self):
        best = {"stop_pct": 1.0}
        candidates = (_candidate(best, 50.0), _candidate({"stop_pct": 1.1}, 40.0))
        evidence = analyze_parameter_stability(candidates, best, _spec(search_mode="cross_zone"))

        assert evidence.n_candidates_total == 2
        assert evidence.search_mode == "cross_zone"


class TestIntegrationWithRealAlgorithmOutputRoundTrips:
    """Preuve additionnelle (au-delà du round-trip générique déjà testé sur une fixture à la main
    dans `tests/test_validation_run.py` Slice 1) : la sortie RÉELLE d'`analyze_parameter_stability
    ()` (pas seulement une `ParameterStabilityEvidence` construite à la main) survit intacte à
    `build_validation_run()` -> `save_validation_run()` -> `load_validation_run()`."""

    def test_real_algorithm_output_round_trips_through_disk(self, tmp_path):
        best = {"stop_pct": 1.0, "target_pct": 5.0}
        candidates = (
            _candidate(best, 100.0),
            _candidate({"stop_pct": 1.1, "target_pct": 5.0}, 90.0),
            _candidate({"stop_pct": 0.9, "target_pct": 5.0}, 0.0),
            _candidate({"stop_pct": 1.0, "target_pct": 6.0}, 85.0),
            _candidate({"stop_pct": 1.1, "target_pct": 5.5}, 20.0),
        )
        spec = _spec(search_mode="grid")
        evidence = analyze_parameter_stability(candidates, best, spec)

        run = build_validation_run(
            validation_run_id="val_ps_integration",
            research_run_id="rr_x",
            split_plan_id="sp_x",
            dataset_snapshot_id="ds_x",
            validation_type="parameter_stability",
            strategy_name="NASDAQ Perfect Revolution V1.1",
            strategy_params={"stop_pct": 1.0},
            specification=spec,
            evidence=evidence,
        )
        path = tmp_path / "ps_integration.json"
        save_validation_run(path, run)

        loaded = load_validation_run(path)

        assert loaded.evidence.n_candidates_total == evidence.n_candidates_total
        assert loaded.evidence.best_score == evidence.best_score
        assert loaded.evidence.best_params == evidence.best_params
        assert loaded.evidence.sensitivity == evidence.sensitivity
        assert (
            loaded.evidence.n_neighbors_total_by_param == evidence.n_neighbors_total_by_param
        )
        assert (
            loaded.evidence.n_neighbors_rejected_by_param
            == evidence.n_neighbors_rejected_by_param
        )
        assert loaded.specification.parameter_stability_semantics_version == (
            PARAMETER_STABILITY_SEMANTICS_VERSION
        )


class TestConsistencyWithARealWalkForwardFold:
    """ADR 0023 Décision 13 : sur un pool de candidats TRAIN d'un fold Walk-Forward RÉEL (mirroring
    la fixture `_ScoreByParamRunBacktest`/`_minimal_optimizer_config`/`_param_ranges_3_values` de
    `tests/test_walk_forward.py`, matérialisée ici via `train_candidates.csv` réellement écrit puis
    relu, jamais un pool synthétique arbitraire), `analyze_parameter_stability()` produit un
    `sensitivity`/`degradation_by_param` cohérent avec le SEUL paramètre réellement varié dans ce
    fold (`ema_trend_len`, grille à 3 valeurs 100/120/140 -- tous les autres paramètres du run
    restent constants, donc structurellement sans aucun voisin)."""

    def _real_train_candidates_csv(self, tmp_path, monkeypatch):
        import engine
        from optimizer import (
            FilterConfig,
            OptimizationConfig,
            ParamRange,
            ScoreWeights,
            TrainTestConfig,
        )
        from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
        from validation_run import FoldDefinition
        from walk_forward import _train_candidates_to_dataframe, run_fold_train

        class _ScoreByParamRunBacktest:
            def __call__(self, df, strategy, params, **kwargs):
                net_ret = params.get("ema_trend_len", 0) / 100.0
                trades = pd_module.DataFrame(
                    [{"resultat_net": 10.0, "raison_sortie": "fin-donnees"}]
                )
                equity = pd_module.DataFrame(
                    [{"date": "2020-01-01", "capital": 10_000.0 + net_ret}]
                )
                return trades, equity, {"n_trades": 1, "net_ret_pct": net_ret}

        import pandas as pd_module

        monkeypatch.setattr(engine, "run_backtest", _ScoreByParamRunBacktest())
        monkeypatch.setattr(
            "optimizer.compute_score",
            lambda stats, *a, **k: (stats.get("net_ret_pct", 0.0), False, None, []),
        )

        times = pd_module.date_range("2020-01-01", periods=200, freq="1440min")
        price = 100.0 + pd_module.Series(range(200), dtype=float) * 0.01
        raw = pd_module.DataFrame({
            "time": times, "open": price.values, "high": (price + 0.5).values,
            "low": (price - 0.5).values, "close": price.values,
        })
        df = engine._add_market_time_columns(raw)

        fold = FoldDefinition(
            fold_index=0, fold_id="fold_000",
            train_start=df["time_paris"].iloc[0].isoformat(),
            requested_boundary=df["time_paris"].iloc[100].isoformat(),
            effective_boundary=df["time_paris"].iloc[100].isoformat(),
            boundary_adjusted=False,
            requested_test_end=df["time_paris"].iloc[150].isoformat(),
            effective_test_end=df["time_paris"].iloc[150].isoformat(),
            test_end_adjusted=False,
            is_last_fold=True,
        )
        config = OptimizationConfig(
            run_id="wf_fold_test", strategy_module="strategies.perfect_revolution_v1",
            strategy_name="test", data_file="unused.csv",
            base_params=dict(DEFAULT_PARAMS),
            param_ranges=[ParamRange(
                name="ema_trend_len", param_type="number", label="x",
                min_val=100, max_val=140, step=20,
            )],
            mode="grid", score_weights=ScoreWeights(), filters=FilterConfig(),
            train_test=TrainTestConfig(), global_params={}, n_workers=1,
        )

        all_results, _sensitivity = run_fold_train(fold, config, df)

        csv_path = tmp_path / "train_candidates.csv"
        _train_candidates_to_dataframe(all_results).to_csv(csv_path, index=False)
        return csv_path, dict(DEFAULT_PARAMS)

    def test_only_the_actually_varied_parameter_shows_real_neighbors_and_degradation(
        self, tmp_path, monkeypatch,
    ):
        import pandas as pd

        csv_path, base_params = self._real_train_candidates_csv(tmp_path, monkeypatch)
        rows = pd.read_csv(csv_path)
        reserved_columns = {"score", "filtered", "filter_reason", "n_trades"}
        param_columns = [c for c in rows.columns if c not in reserved_columns]

        candidates = tuple(
            {
                "params": {c: row[c] for c in param_columns},
                "score": float(row["score"]),
            }
            for _, row in rows.iterrows()
        )
        assert len(candidates) == 3  # grille 100/120/140

        best_row = rows.loc[rows["score"].idxmax()]
        best_params = {c: best_row[c] for c in param_columns}
        assert best_params["ema_trend_len"] == 140

        evidence = analyze_parameter_stability(
            candidates, best_params, _spec(search_mode="grid"),
        )

        # Le SEUL paramètre réellement varié dans ce fold a de vrais voisins structurels.
        assert evidence.n_neighbors_total_by_param["ema_trend_len"] == 2
        assert evidence.n_neighbors_rejected_by_param["ema_trend_len"] == 0
        summary = evidence.degradation_by_param["ema_trend_len"]
        assert summary is not None
        import numpy as np

        expected_p5, expected_p95 = np.percentile(
            [(1.4 - 1.0) / 1.4, (1.4 - 1.2) / 1.4], [5, 95],
        )
        assert summary.p5 == pytest.approx(float(expected_p5), abs=1e-6)
        assert summary.p95 == pytest.approx(float(expected_p95), abs=1e-6)

        # Tous les AUTRES paramètres (constants dans ce fold) n'ont structurellement aucun
        # voisin : ils n'ont jamais varié dans la grille de ce run.
        for other_param in base_params:
            if other_param == "ema_trend_len":
                continue
            assert evidence.n_neighbors_total_by_param[other_param] == 0
