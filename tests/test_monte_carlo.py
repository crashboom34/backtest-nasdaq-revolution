"""
tests/test_monte_carlo.py — AF-V-03 Slice 2 : algorithme `monte_carlo.py` (permutation, bootstrap).

Contrat de référence : `docs/adr/0022-monte-carlo-trade-resampling-v1.md`, Décision 13 (matrice
TDD). `monte_carlo.py` reste un leaf sans dépendance moteur (Décision 10/11) — vérifié ici par un
test d'import statique, jamais par confiance aveugle.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import monte_carlo
from monte_carlo import run_monte_carlo_simulation
from validation_run import (
    MONTE_CARLO_SEMANTICS_VERSION,
    FoldDefinition,
    FoldResult,
    FoldSelection,
    MonteCarloEvidence,
    MonteCarloSpecification,
    UnknownVerdictPolicy,
    build_monte_carlo_specification,
)
from walk_forward import build_aggregate_result


def _spec(n_simulations=200, master_seed=42, verdict_policy_id=None):
    """Construction directe (jamais via `build_monte_carlo_specification()`) pour contrôler
    `n_simulations`/`master_seed` librement dans les tests d'algorithme — la dette disciplinaire
    de `MonteCarloSpecification` (dataclass frozen ordinaire, ADR 0022 Décision 5) est assumée ici
    volontairement, exactement comme documenté."""
    return MonteCarloSpecification(
        n_simulations=n_simulations,
        master_seed=master_seed,
        source_validation_run_id="vr_test_fixture",
        source_trades_from_optimized_params=False,
        monte_carlo_semantics_version=MONTE_CARLO_SEMANTICS_VERSION,
        verdict_policy_id=verdict_policy_id,
    )


class TestNoEngineDependency:
    """ADR 0022 Décision 10/11 : `monte_carlo.py` ne doit structurellement jamais pouvoir accéder
    à la zone holdout finale réservée — preuve par analyse statique des imports réels (AST),
    jamais par recherche textuelle naïve."""

    def test_static_import_analysis_finds_no_engine_optimizer_dataset_split_or_walk_forward(self):
        source = Path(monte_carlo.__file__).read_text(encoding="utf-8")
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
        # Jetons reconstruits par concaténation : une vérification littérale de LEUR PROPRE
        # absence ne peut pas, par construction, contenir le jeton complet en clair.
        forbidden_holdout_token = "FINAL_" + "HOLDOUT"
        forbidden_access_event_token = "Holdout" + "AccessEvent"
        module_source = Path(monte_carlo.__file__).read_text(encoding="utf-8")
        test_source = Path(__file__).read_text(encoding="utf-8")
        for text, label in ((module_source, "monte_carlo.py"), (test_source, "test_monte_carlo.py")):
            assert forbidden_holdout_token not in text, label
            assert forbidden_access_event_token not in text, label


class TestMethodValidation:
    """ADR 0022 Décision 9 : `method` inconnu -> `ValueError` immédiat, jamais une valeur par
    défaut silencieuse."""

    def test_invalid_method_raises_value_error(self):
        with pytest.raises(ValueError):
            monte_carlo._derive_method_seed(42, "not_a_real_method")

    def test_valid_methods_do_not_raise(self):
        monte_carlo._derive_method_seed(42, "sequence_risk")
        monte_carlo._derive_method_seed(42, "sampling_uncertainty")


class TestNSimulationsValidation:
    """ADR 0022 Décision 9 : `n_simulations <= 0` -> `ValueError` immédiat, avant tout calcul.
    `build_monte_carlo_specification()` (Slice 1) ne peut structurellement pas produire cette
    valeur, mais `MonteCarloSpecification` reste une dataclass frozen ordinaire qu'un appelant
    peut construire directement (dette disciplinaire assumée, Décision 5) — ce garde-fou doit donc
    vivre ici, jamais supposé impossible."""

    def test_zero_n_simulations_raises_value_error(self):
        with pytest.raises(ValueError):
            run_monte_carlo_simulation((1.0, -1.0), _spec(n_simulations=0))

    def test_negative_n_simulations_raises_value_error(self):
        with pytest.raises(ValueError):
            run_monte_carlo_simulation((1.0, -1.0), _spec(n_simulations=-5))

    def test_invalid_n_simulations_raises_before_any_trades_are_consumed(self):
        # Même avec zéro trade (qui ne lèverait normalement jamais d'exception, Décision 7), un
        # n_simulations invalide reste une erreur structurelle de la spec elle-même.
        with pytest.raises(ValueError):
            run_monte_carlo_simulation((), _spec(n_simulations=0))


class TestZeroAndSingleTrade:
    """ADR 0022 Décision 7 : jamais une erreur, une observation factuelle honnête."""

    def test_zero_trades_never_raises_and_marks_zero_trade_input(self):
        evidence = run_monte_carlo_simulation((), _spec())

        assert isinstance(evidence, MonteCarloEvidence)
        assert evidence.zero_trade_input is True
        assert evidence.n_input_trades == 0
        assert evidence.execution_status == "completed"
        assert evidence.observed_net_ret_pct is None
        assert evidence.observed_max_dd_trade_close_basis_pct is None
        assert evidence.observed_lag1_autocorrelation is None
        assert evidence.observed_longest_losing_streak is None
        assert evidence.sequence_risk_max_dd_trade_close_basis_pct is None
        assert evidence.sequence_risk_longest_losing_streak is None
        assert evidence.sampling_uncertainty_net_ret_pct is None
        assert evidence.sampling_uncertainty_max_dd_trade_close_basis_pct is None

    def test_single_trade_never_raises_sequence_risk_has_exactly_one_permutation(self):
        evidence = run_monte_carlo_simulation((5.0,), _spec(n_simulations=1000))

        assert evidence.zero_trade_input is False
        assert evidence.n_input_trades == 1
        assert evidence.observed_net_ret_pct == pytest.approx(5.0)
        # 1! = 1 seule permutation possible -> distribution dégénérée mais valide (p5 == p95).
        summary = evidence.sequence_risk_max_dd_trade_close_basis_pct
        assert summary.p5 == pytest.approx(summary.p95)

    def test_single_trade_bootstrap_is_degenerate_but_well_defined(self):
        evidence = run_monte_carlo_simulation((5.0,), _spec(n_simulations=1000))

        summary = evidence.sampling_uncertainty_net_ret_pct
        assert summary.p5 == pytest.approx(5.0)
        assert summary.p95 == pytest.approx(5.0)


class TestDeterminism:
    """ADR 0022 Décision 5 : deux appels avec le même `source_validation_run_id`/mêmes trades
    produisent une `MonteCarloEvidence` bit-à-bit identique."""

    def test_two_calls_with_the_same_inputs_produce_an_identical_evidence(self):
        trades = (3.0, -2.0, 5.0, -1.0, 4.0, -6.0, 2.0)
        spec = _spec(n_simulations=500, master_seed=777)

        evidence_a = run_monte_carlo_simulation(trades, spec)
        evidence_b = run_monte_carlo_simulation(trades, spec)

        assert evidence_a == evidence_b


class TestDefaultRngInstantiation:
    """ADR 0022 Décision 5/13 : `default_rng` instancié au plus 2 fois — exactement 1 appel par
    méthode utilisant réellement le tirage aléatoire, jamais 1 par simulation."""

    def _spy(self, monkeypatch):
        calls = []
        real_default_rng = np.random.default_rng

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            return real_default_rng(*args, **kwargs)

        monkeypatch.setattr(monte_carlo.np.random, "default_rng", spy)
        return calls

    def test_small_n_trades_triggers_exhaustive_enumeration_rng_never_consumed_by_sequence_risk(
        self, monkeypatch,
    ):
        calls = self._spy(monkeypatch)
        trades_arr = np.array([1.0, -2.0, 3.0, -0.5])  # n_trades=4, 4! = 24

        monte_carlo._sequence_risk(trades_arr, n_simulations=100, master_seed=42)

        assert calls == []

    def test_large_n_trades_triggers_vectorized_draw_exactly_one_rng_call(self, monkeypatch):
        calls = self._spy(monkeypatch)
        trades_arr = np.arange(1, 11, dtype=float)  # n_trades=10, 10! >> 50

        monte_carlo._sequence_risk(trades_arr, n_simulations=50, master_seed=42)

        assert len(calls) == 1

    def test_sampling_uncertainty_always_instantiates_rng_exactly_once(self, monkeypatch):
        calls = self._spy(monkeypatch)
        trades_arr = np.array([1.0, -2.0, 3.0])

        monte_carlo._sampling_uncertainty(trades_arr, n_simulations=50, master_seed=42)

        assert len(calls) == 1

    def test_full_run_never_instantiates_rng_more_than_twice(self, monkeypatch):
        calls = self._spy(monkeypatch)
        trades_arr = tuple(float(x) for x in np.arange(1, 11))  # vectorized branch both methods

        run_monte_carlo_simulation(trades_arr, _spec(n_simulations=50))

        assert len(calls) <= 2


class TestIndependentSeedsBetweenMethods:
    """ADR 0022 Décision 5 : `sequence_risk` et `sampling_uncertainty` ne partagent jamais un flux
    aléatoire identique."""

    def test_method_seeds_differ_between_sequence_risk_and_sampling_uncertainty(self):
        seed_a = monte_carlo._derive_method_seed(123, "sequence_risk")
        seed_b = monte_carlo._derive_method_seed(123, "sampling_uncertainty")

        assert seed_a != seed_b

    def test_rng_instances_are_seeded_differently_end_to_end(self, monkeypatch):
        seeds_used = []
        real_default_rng = np.random.default_rng

        def spy(seed, *args, **kwargs):
            seeds_used.append(seed)
            return real_default_rng(seed, *args, **kwargs)

        monkeypatch.setattr(monte_carlo.np.random, "default_rng", spy)
        trades_arr = np.arange(1, 11, dtype=float)

        monte_carlo._sequence_risk(trades_arr, n_simulations=50, master_seed=999)
        monte_carlo._sampling_uncertainty(trades_arr, n_simulations=50, master_seed=999)

        assert len(seeds_used) == 2
        assert seeds_used[0] != seeds_used[1]


class TestVectorizedDrawRowsAreIndependentValidPermutations:
    """ADR 0022 Décision 13 (finding architecture, seconde revue) : sur `n_simulations` petit et
    `n_trades` non trivial, aucune paire de lignes n'est identique par construction/bug d'axe, et
    chaque ligne contient bien une permutation valide (mêmes éléments, ordre différent)."""

    def test_no_two_rows_are_identical_and_each_row_is_a_valid_permutation(self):
        trades_arr = np.arange(1, 11, dtype=float)  # 10 valeurs distinctes
        permuted = monte_carlo._draw_sequence_risk_permutations(
            trades_arr, n_simulations=20, master_seed=13,
        )

        assert permuted.shape == (20, 10)
        for row in permuted:
            assert sorted(row.tolist()) == sorted(trades_arr.tolist())

        unique_rows = {tuple(row.tolist()) for row in permuted}
        assert len(unique_rows) > 1, "toutes les lignes sont identiques -- bug d'axe probable"

    def test_bootstrap_rows_are_independent_draws_with_replacement(self):
        trades_arr = np.arange(1, 11, dtype=float)
        sampled = monte_carlo._draw_sampling_uncertainty_samples(
            trades_arr, n_simulations=20, master_seed=13,
        )

        assert sampled.shape == (20, 10)
        for row in sampled:
            assert set(row.tolist()).issubset(set(trades_arr.tolist()))

        unique_rows = {tuple(row.tolist()) for row in sampled}
        assert len(unique_rows) > 1, "toutes les lignes sont identiques -- bug d'axe probable"


class TestPermutationPreservesFinalReturn:
    """ADR 0022 Décision 2 : le rendement net final est mathématiquement identique à chaque
    permutation (la multiplication est commutative) -- seule la trajectoire varie."""

    def test_all_permutations_of_the_same_trades_chain_to_the_same_final_value(self):
        trades_arr = np.array([10.0, -5.0, 3.0, -8.0, 2.0])
        permuted = monte_carlo._draw_sequence_risk_permutations(
            trades_arr, n_simulations=500, master_seed=5,
        )

        curves = monte_carlo._chain_returns(permuted)
        final_values = curves[:, -1]

        assert final_values == pytest.approx(final_values[0])


class TestBootstrapVariesFinalReturn:
    """ADR 0022 Décision 2 : contrairement à la permutation, le rendement final VARIE sous
    bootstrap."""

    def test_bootstrap_final_return_distribution_has_spread(self):
        trades = (10.0, -5.0, 3.0, -8.0, 2.0, 6.0, -1.0)
        evidence = run_monte_carlo_simulation(trades, _spec(n_simulations=2000))

        summary = evidence.sampling_uncertainty_net_ret_pct
        assert summary.p5 != summary.p95


class TestDrawdownTradeCloseBasisNeverConfusedWithEngine:
    """ADR 0022 Décision 6 : ce drawdown n'est observable QU'AUX POINTS DE CLÔTURE de chaque
    trade -- il ignore structurellement l'excursion adverse intra-trade (MAE), donc sous-estime
    systématiquement un drawdown barre-par-barre de référence. Fixture construite à la main,
    jamais un chiffre du vrai moteur (`monte_carlo.py` ne le connaît structurellement pas)."""

    def test_trade_close_basis_drawdown_is_strictly_below_a_hand_built_bar_by_bar_reference(self):
        # Deux trades : +20 % puis -10 %, connus. Clôtures : [1.0, 1.2, 1.08].
        trades = (20.0, -10.0)

        # Excursion intra-trade CONNUE et fournie par la fixture (jamais recalculée par un
        # moteur) : durant le premier trade, l'équité barre-par-barre creuse à 0.85 avant de
        # remonter à 1.2 à la clôture -- un mouvement invisible à la seule base "clôture de trade".
        bar_by_bar_equity = [1.0, 0.85, 1.05, 1.2, 1.08]
        peak = bar_by_bar_equity[0]
        bar_by_bar_reference_max_dd = 0.0
        for value in bar_by_bar_equity[1:]:
            peak = max(peak, value)
            bar_by_bar_reference_max_dd = max(
                bar_by_bar_reference_max_dd, (peak - value) / peak * 100.0,
            )

        evidence = run_monte_carlo_simulation(trades, _spec())

        assert evidence.observed_max_dd_trade_close_basis_pct == pytest.approx(10.0)
        assert bar_by_bar_reference_max_dd == pytest.approx(15.0)
        assert (
            evidence.observed_max_dd_trade_close_basis_pct
            < bar_by_bar_reference_max_dd
        )
        assert evidence.observed_max_dd_trade_close_basis_pct != bar_by_bar_reference_max_dd


class TestFactorialBelowNSimulationsForMultipleValues:
    """ADR 0022 Décision 4/9 : `n_trades! < n_simulations` est une relation MATHÉMATIQUE relative,
    jamais un seuil `7` câblé en dur -- testé pour au moins deux couples différents."""

    @pytest.mark.parametrize(
        "n_trades,n_simulations",
        [
            (4, 100),   # 4! = 24 < 100
            (5, 200),   # 5! = 120 < 200
            (6, 5000),  # 6! = 720 < 5000
        ],
    )
    def test_exhaustive_branch_produces_exactly_factorial_many_distinct_rows(
        self, n_trades, n_simulations,
    ):
        import math

        trades_arr = np.arange(1, n_trades + 1, dtype=float)
        permuted = monte_carlo._draw_sequence_risk_permutations(
            trades_arr, n_simulations=n_simulations, master_seed=1,
        )

        assert permuted.shape[0] == math.factorial(n_trades)
        unique_rows = {tuple(row.tolist()) for row in permuted}
        assert len(unique_rows) == math.factorial(n_trades)

    @pytest.mark.parametrize("n_trades,n_simulations", [(8, 100), (9, 500)])
    def test_vectorized_branch_produces_exactly_n_simulations_rows(self, n_trades, n_simulations):
        trades_arr = np.arange(1, n_trades + 1, dtype=float)
        permuted = monte_carlo._draw_sequence_risk_permutations(
            trades_arr, n_simulations=n_simulations, master_seed=1,
        )

        assert permuted.shape[0] == n_simulations


class TestIidBiasReportedAsFactNeverAsThreshold:
    """ADR 0022 Décision 3 : `observed_lag1_autocorrelation`/`observed_longest_losing_streak`
    calculés correctement sur un jeu de trades synthétique à corrélation connue -- aucun champ
    "significatif"/"anormal" n'existe dans `MonteCarloEvidence`."""

    def test_no_significance_or_abnormality_field_exists_on_monte_carlo_evidence(self):
        field_names = {f.name for f in dataclasses.fields(MonteCarloEvidence)}
        assert not any("signif" in name for name in field_names)
        assert not any("abnormal" in name for name in field_names)
        assert not any("anorm" in name for name in field_names)

    def test_lag1_autocorrelation_on_perfectly_alternating_signs_is_minus_one(self):
        # b = -a exactement -> corrélation de Pearson = -1.0, calcul vérifiable à la main.
        trades = (1.0, -1.0, 1.0, -1.0)

        evidence = run_monte_carlo_simulation(trades, _spec())

        assert evidence.observed_lag1_autocorrelation == pytest.approx(-1.0)

    def test_lag1_autocorrelation_is_none_below_two_trades(self):
        evidence = run_monte_carlo_simulation((5.0,), _spec())

        assert evidence.observed_lag1_autocorrelation is None

    def test_lag1_autocorrelation_is_none_for_exactly_two_trades(self):
        # ADR 0022 Décision 3 : avec exactement 2 trades, `trades_arr[:-1]`/`trades_arr[1:]` sont
        # chacun des tableaux à UN SEUL élément -- np.corrcoef calcule alors une covariance sur un
        # échantillon de taille 1 (degrés de liberté = 0), donc 0/0 = nan, jamais une corrélation
        # définie. Il faut au moins 2 PAIRES (x_i, x_i+1), donc au moins 3 trades -- `None` ici,
        # jamais `nan` (jamais une valeur inventée).
        evidence = run_monte_carlo_simulation((5.0, -3.0), _spec())

        assert evidence.observed_lag1_autocorrelation is None

    def test_lag1_autocorrelation_is_none_for_zero_variance_lagged_subarray(self):
        # ADR 0022 Décision 3/finding MAJOR (revue indépendante) : `n_trades >= 3` ne suffit pas
        # à garantir une corrélation de Pearson définie -- si `trades_arr[:-1]` (ou `[1:]`) a une
        # variance nulle (plusieurs `net_ret_pct` consécutifs strictement identiques, plausible
        # avec une taille de position/distance de stop fixe), `np.corrcoef` produit `0/0 = nan`,
        # jamais une valeur inventée -- `None` attendu ici, exactement comme le cas `n_trades < 3`.
        evidence = run_monte_carlo_simulation((0.0, 0.0, 0.0, 5.0), _spec())

        assert evidence.observed_lag1_autocorrelation is None

    def test_lag1_autocorrelation_is_none_when_all_trades_are_identical(self):
        evidence = run_monte_carlo_simulation((1.0, 1.0, 1.0), _spec())

        assert evidence.observed_lag1_autocorrelation is None

    def test_longest_losing_streak_counts_consecutive_non_positive_returns(self):
        trades = (1.0, -1.0, -2.0, -3.0, 1.0, -1.0)

        evidence = run_monte_carlo_simulation(trades, _spec())

        assert evidence.observed_longest_losing_streak == 3

    def test_longest_losing_streak_is_zero_when_no_losses(self):
        trades = (1.0, 2.0, 3.0)

        evidence = run_monte_carlo_simulation(trades, _spec())

        assert evidence.observed_longest_losing_streak == 0

    def test_sequence_risk_longest_losing_streak_percentiles_are_integer_valued(self):
        trades = (1.0, -1.0, -2.0, -3.0, 1.0, -1.0, 2.0)
        evidence = run_monte_carlo_simulation(trades, _spec(n_simulations=500))

        summary = evidence.sequence_risk_longest_losing_streak
        for value in (summary.p5, summary.p25, summary.p50, summary.p75, summary.p95):
            assert value == int(value), f"percentile non entier : {value!r}"


class TestVerdict:
    """ADR 0022 Décision 12 : séparation stricte preuve factuelle / verdict scientifique --
    `INCONCLUSIVE` sans politique, `UnknownVerdictPolicy` sinon (réutilisée telle quelle)."""

    def test_no_verdict_policy_id_yields_inconclusive_with_explicit_reason(self):
        evidence = run_monte_carlo_simulation((1.0, -1.0), _spec(verdict_policy_id=None))

        assert evidence.scientific_verdict == "INCONCLUSIVE"
        assert len(evidence.verdict_reasons) >= 1
        assert all(isinstance(r, str) and r for r in evidence.verdict_reasons)

    def test_zero_trade_input_still_resolves_verdict_to_inconclusive(self):
        evidence = run_monte_carlo_simulation((), _spec(verdict_policy_id=None))

        assert evidence.scientific_verdict == "INCONCLUSIVE"

    def test_verdict_policy_id_provided_raises_unknown_verdict_policy(self):
        with pytest.raises(UnknownVerdictPolicy):
            run_monte_carlo_simulation((1.0, -1.0), _spec(verdict_policy_id="some_policy_v1"))

    def test_verdict_policy_id_provided_raises_before_any_zero_trade_shortcut(self):
        with pytest.raises(UnknownVerdictPolicy):
            run_monte_carlo_simulation((), _spec(verdict_policy_id="some_policy_v1"))


def _mc_fold_definition(index, is_last):
    return FoldDefinition(
        fold_index=index,
        fold_id=f"fold_{index:03d}",
        train_start="2023-01-01T00:00:00+00:00",
        requested_boundary="2023-02-01T00:00:00+00:00",
        effective_boundary="2023-02-01T00:00:00+00:00",
        boundary_adjusted=False,
        requested_test_end="2023-03-01T00:00:00+00:00",
        effective_test_end="2023-03-01T00:00:00+00:00",
        test_end_adjusted=False,
        is_last_fold=is_last,
    )


def _mc_fold_selection(fold):
    return FoldSelection(
        fold_id=fold.fold_id,
        selected_params={"ema_trend_len": 140},
        selected_params_hash="deadbeef",
        score_train=1.0,
        rank_in_train=1,
        train_candidates_evaluated=1,
        train_candidates_unique=1,
        train_candidates_eligible=1,
        search_space_hash="deadbeef",
        algorithm="grid",
        fold_seed=None,
    )


def _mc_fold_result(fold, trades):
    """`FoldResult` construit à la main, mirroring `_fold_result_stub()` de
    `tests/test_walk_forward.py` -- `net_ret_pct` est ICI le chaînage produit réel des `trades` de
    ce fold (même formule que `walk_forward.build_aggregate_result()`, ADR 0021 Décision 15/ADR
    0022 Décision 1/2), pour que le run Walk-Forward construit ci-dessous soit mathématiquement
    cohérent avec la séquence de trades concaténée fournie au Monte-Carlo (ADR 0022 Décision 13)."""
    chained = 1.0
    for r in trades:
        chained *= 1.0 + r / 100.0
    net_ret_pct = (chained - 1.0) * 100.0
    return FoldResult(
        fold_id=fold.fold_id,
        definition=fold,
        selection=_mc_fold_selection(fold),
        n_trades=len(trades),
        net_ret_pct=net_ret_pct,
        max_dd_pct=None,
        profit_factor=None,
        win_rate=None,
        expectancy=None,
        score_test=1.0,
        zero_trade_oos=False,
        forced_closes=0,
        coverage_bars=10,
        gross_win=0.0,
        gross_loss=0.0,
        n_win=0,
    )


class TestConsistencyWithAggregateResult:
    """ADR 0022 Décision 13 : sur la MÊME séquence ordonnée de `net_ret_pct` qu'un `AggregateResult`
    Walk-Forward réel (ADR 0021 Décision 15, chaînage multiplicatif par composition chronologique),
    `observed_net_ret_pct` recalculé par Monte-Carlo est STRICTEMENT ÉGAL (tolérance flottante) à
    `AggregateResult.oos_net_return_pct` -- assertion ferme, jamais une simple absence d'erreur."""

    def test_observed_net_ret_pct_matches_aggregate_result_oos_net_return_pct_exactly(self):
        fold0 = _mc_fold_definition(0, is_last=False)
        fold1 = _mc_fold_definition(1, is_last=True)
        fold0_trades = (10.0, -5.0, 2.0)
        fold1_trades = (-3.0, 8.0)

        r0 = _mc_fold_result(fold0, fold0_trades)
        r1 = _mc_fold_result(fold1, fold1_trades)
        aggregate = build_aggregate_result((r0, r1))

        concatenated_trades = fold0_trades + fold1_trades
        spec = build_monte_carlo_specification(
            source_validation_run_id="vr_consistency_test",
            source_trades_from_optimized_params=False,
        )
        evidence = run_monte_carlo_simulation(concatenated_trades, spec)

        assert evidence.observed_net_ret_pct == pytest.approx(
            aggregate.oos_net_return_pct, rel=1e-9, abs=1e-9,
        )

    def test_holds_for_a_single_fold_too(self):
        fold0 = _mc_fold_definition(0, is_last=True)
        fold0_trades = (4.0, -2.0, 6.0, -1.5, 3.0)
        r0 = _mc_fold_result(fold0, fold0_trades)
        aggregate = build_aggregate_result((r0,))

        spec = build_monte_carlo_specification(
            source_validation_run_id="vr_consistency_test_single_fold",
            source_trades_from_optimized_params=False,
        )
        evidence = run_monte_carlo_simulation(fold0_trades, spec)

        assert evidence.observed_net_ret_pct == pytest.approx(
            aggregate.oos_net_return_pct, rel=1e-9, abs=1e-9,
        )
