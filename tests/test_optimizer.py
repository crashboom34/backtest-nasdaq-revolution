"""
tests/test_optimizer.py — Dette A (Optimizer Integration, 2026-09-12).

Sépare le DataFrame de CONTEXTE (historique conservé pour le warmup des indicateurs, jamais de
donnée postérieure à la fin effective) de la SÉLECTION D'EXÉCUTION effective
(opt_start_date/opt_end_date/max_rows, puis TRAIN/TEST si actif) — sans jamais modifier la
période réellement demandée par l'utilisateur ni la sémantique existante de
`compute_split_dates()`/Dette B.

Gap de couverture comblé : aucun test `optimizer.py`/`optimizer_process.py` n'existait avant
cette mission (confirmé lors de l'audit Dette A/B précédent).

Stratégie et DataFrame 100 % synthétiques, déterministes, sans dépendance à `nasdaq_3m.csv`.
Le moteur réel (`engine.run_backtest`) est monkeypatché par un faux enregistreur dans la plupart
des tests d'intégration — suffisant pour verrouiller QUELLES bornes/QUEL DataFrame sont transmis,
sans lancer de vrai `ProcessPoolExecutor` (voir mission §19, note O9).
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import optimizer
from engine import _add_market_time_columns, run_backtest
from optimizer import (
    ExecutionWindow,
    FilterConfig,
    NoStateReadyBoundary,
    OptimizationConfig,
    Optimizer,
    ParamRange,
    ScoreWeights,
    StateReadinessSemanticsMismatch,
    STATE_READINESS_SEMANTICS_VERSION,
    TrainTestConfig,
    TrainTestSemanticsMismatch,
    TrainTestWindows,
    TRAIN_TEST_SEMANTICS_VERSION,
    _run_single,
    _worker_run_single,
    benchmark_speed,
    compute_split_dates,
    reaches_stratified_sample,
    resolve_execution_window,
    validate_resume_state_readiness_semantics,
    validate_resume_train_test_semantics,
)
from strategy_contracts import DailyStateReadiness


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures / helpers synthétiques
# ═══════════════════════════════════════════════════════════════════════════════


def _build_synthetic_df(n_bars: int, start: str = "2024-01-02T00:00:00", freq_minutes: int = 1440):
    """Une bougie par JOUR par défaut (freq_minutes=1440) — raisonner facilement en dates
    "YYYY-MM-DD" (opt_start_date/opt_end_date), exactement comme optimizer.py/optimizer_process.py
    le font réellement."""
    times = pd.date_range(start, periods=n_bars, freq=f"{freq_minutes}min")
    price = 100.0 + pd.Series(range(n_bars), dtype=float) * 0.01
    raw = pd.DataFrame({
        "time":  times,
        "open":  price.values,
        "high":  (price + 0.5).values,
        "low":   (price - 0.5).values,
        "close": price.values,
    })
    return _add_market_time_columns(raw)


def _bar_date_str(df, idx):
    return df["time_paris"].iloc[idx].strftime("%Y-%m-%d")


def _minimal_config(**overrides):
    defaults = dict(
        run_id="test_run",
        strategy_module="strategies.perfect_revolution_v1",
        strategy_name="test",
        data_file="unused.csv",
        base_params={},
        param_ranges=[],
        mode="grid",
        score_weights=ScoreWeights(),
        filters=FilterConfig(),
        train_test=TrainTestConfig(),
        global_params={},
        n_workers=1,
    )
    defaults.update(overrides)
    return OptimizationConfig(**defaults)


class _RecordingRunBacktest:
    """Faux `engine.run_backtest()` — enregistre exactement ce qu'il reçoit (longueur du
    DataFrame, bornes start_date/end_date) et retourne un résultat vide déterministe, sans jamais
    exécuter de vraie logique de trading. Permet de verrouiller QUEL contexte/QUELLES bornes
    `_run_single()`/`Optimizer` transmettent, sans dépendre d'une stratégie réelle générant des
    trades (mission §19, note O9 : monkeypatch suffit, pas de gros ProcessPool)."""

    def __init__(self):
        self.calls = []

    def __call__(self, df, strategy, params, **kwargs):
        self.calls.append({
            "len_df":       len(df),
            "first_time":   df["time_paris"].iloc[0] if len(df) else None,
            "last_time":    df["time_paris"].iloc[-1] if len(df) else None,
            "start_date":   kwargs.get("start_date"),
            "end_date":     kwargs.get("end_date"),
            "end_boundary": kwargs.get("end_boundary", "inclusive"),
        })
        # n_trades > 0 : évite le court-circuit "Aucun trade" de _run_single() avant même
        # l'appel à compute_score() — la valeur réelle n'a pas d'importance pour ces tests
        # (qui verrouillent les bornes/contexte transmis au moteur, pas la logique de scoring).
        return pd.DataFrame(), pd.DataFrame(), {"n_trades": 1, "net_ret_pct": 1.0}


# ═══════════════════════════════════════════════════════════════════════════════
# resolve_execution_window() — fonction pure (O1, O2, O3, O4, O13, O14)
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveExecutionWindow:

    def test_o13_no_filters_matches_the_whole_dataset(self):
        """O13 — sans opt_start_date/opt_end_date/max_rows, comportement identique à l'existant :
        contexte == exécution == tout le dataset."""
        df = _build_synthetic_df(10)

        window = resolve_execution_window(df)

        assert window.exec_row_count == 10
        assert len(window.context_df) == 10
        assert len(window.execution_df) == 10

    def test_o1_execution_selection_reproduces_start_end_max_rows(self):
        """O1 — la sélection d'EXÉCUTION reproduit exactement opt_start_date -> opt_end_date ->
        max_rows, dans cet ordre, comme l'ancien filtrage physique de optimizer_process.py."""
        df = _build_synthetic_df(20)  # jours 0..19

        window = resolve_execution_window(
            df,
            opt_start_date=_bar_date_str(df, 5),
            opt_end_date=_bar_date_str(df, 14),
            max_rows=3,
        )

        # 5..14 = 10 jours filtrés par date, puis max_rows=3 -> jours 5,6,7
        assert window.exec_row_count == 3
        assert window.execution_df["time_paris"].iloc[0] == df["time_paris"].iloc[5]
        assert window.execution_df["time_paris"].iloc[-1] == df["time_paris"].iloc[7]

    def test_o2_context_preserves_history_before_execution_start(self):
        """O2 — le CONTEXTE contient les barres antérieures à opt_start_date, mais la sélection
        d'exécution démarre bien à la période demandée."""
        df = _build_synthetic_df(20)

        window = resolve_execution_window(df, opt_start_date=_bar_date_str(df, 10))

        assert len(window.context_df) == 20  # tout l'historique conservé (pas d'opt_end_date)
        assert window.execution_df["time_paris"].iloc[0] == df["time_paris"].iloc[10]

    def test_o3_context_never_contains_bars_after_the_effective_end(self):
        """O3 — aucune barre postérieure à la fin EFFECTIVE d'exécution ne reste dans le
        contexte (ici, opt_end_date fixe la fin)."""
        df = _build_synthetic_df(20)

        window = resolve_execution_window(df, opt_end_date=_bar_date_str(df, 14))

        assert len(window.context_df) == 15  # indices 0..14 seulement
        assert window.context_df["time_paris"].iloc[-1] == df["time_paris"].iloc[14]

    def test_o3_context_end_follows_max_rows_when_it_ends_the_period_earlier(self):
        """O3 (suite) — si max_rows termine la période plus tôt que opt_end_date, c'est CETTE
        dernière barre sélectionnée qui devient la fin effective du contexte, pas opt_end_date."""
        df = _build_synthetic_df(20)

        window = resolve_execution_window(
            df, opt_end_date=_bar_date_str(df, 14), max_rows=5)

        # sans opt_start_date : jours 0..4 (max_rows=5) -> fin effective = jour 4
        assert window.exec_row_count == 5
        assert window.execution_df["time_paris"].iloc[-1] == df["time_paris"].iloc[4]
        assert len(window.context_df) == 5  # pas 15 : le contexte suit la fin réelle (jour 4)
        assert window.context_df["time_paris"].iloc[-1] == df["time_paris"].iloc[4]

    def test_o4_max_rows_counts_only_execution_bars_not_context(self):
        """O4 — max_rows=N signifie N barres d'EXÉCUTION, jamais N barres de contexte élargi."""
        df = _build_synthetic_df(30)

        window = resolve_execution_window(
            df, opt_start_date=_bar_date_str(df, 10), max_rows=5)

        assert window.exec_row_count == 5  # jamais 15 (10 barres de contexte + 5 d'exécution)
        assert len(window.context_df) == 15  # 0..14 : historique amont + exécution

    def test_o14_start_after_all_data_yields_an_empty_selection_no_crash(self):
        df = _build_synthetic_df(10)

        window = resolve_execution_window(df, opt_start_date="2099-01-01")

        assert window.exec_row_count == 0
        assert window.exec_start is None
        assert window.exec_end is None
        assert len(window.context_df) == 0

    def test_o14_end_before_all_data_yields_an_empty_selection_no_crash(self):
        df = _build_synthetic_df(10)

        window = resolve_execution_window(df, opt_end_date="2000-01-01")

        assert window.exec_row_count == 0
        assert len(window.context_df) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# _run_single() — le contexte/les bornes transmis à engine.run_backtest() (O5)
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunSingleReceivesResolvedWindow:

    def test_o5_no_train_test_bounds_execution_to_the_effective_window(self, monkeypatch):
        """O5 — même sans train/test, un backtest de l'optimizer ne doit jamais recevoir un
        DataFrame déjà physiquement réduit à l'exécution : il reçoit désormais le CONTEXTE élargi
        + des bornes start_date/end_date explicites correspondant à la période effective."""
        df = _build_synthetic_df(20)
        window = resolve_execution_window(df, opt_start_date=_bar_date_str(df, 10))
        fake = _RecordingRunBacktest()
        monkeypatch.setattr(optimizer, "run_backtest", fake, raising=False)
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)

        config = _minimal_config()
        _run_single({}, config, window.context_df, window.exec_start, window.exec_end)

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["len_df"] == len(window.context_df)  # contexte complet transmis
        assert call["start_date"] == window.exec_start
        assert call["end_date"] == window.exec_end


# ═══════════════════════════════════════════════════════════════════════════════
# Optimizer.run() — train/test sur la sélection d'exécution, pas le contexte (O6, O7, O8)
# ═══════════════════════════════════════════════════════════════════════════════


class TestOptimizerTrainTestUsesExecutionSelectionNotContext:
    """O6/O7/O8 — RÉÉCRITS (2026-09-12, correction scientifique du split TRAIN/TEST) pour
    verrouiller le NOUVEAU contrat (`TrainTestWindows`, `end_boundary` explicite), plus C5/C6.

    **Ancien résultat verrouillé par ces tests avant cette mission = BUG historique**
    (`compute_split_dates()` perdait la précision horaire et créait un trou silencieux
    TRAIN→TEST — voir l'audit read-only précédent). **Nouveau résultat = correction
    scientifique** : TRAIN=[train_start,boundary) exclusive, TEST=[boundary,test_end]
    inclusive, aucune barre perdue ni dupliquée."""

    def _config_with_train_test(self, opt_start_date=None):
        # base_params réels (Dette WARMUP/State Readiness dynamiques appellent désormais
        # Strategy.required_warmup()/state_readiness() sur cfg.base_params) — {} n'est plus
        # suffisant depuis que ces deux contrats existent (adaptation mécanique, aucun
        # changement de comportement pour ce que ces tests vérifient : les bornes transmises).
        from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
        return _minimal_config(
            mode="grid",
            param_ranges=[],
            base_params=dict(DEFAULT_PARAMS),
            train_test=TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.6),
            opt_start_date=opt_start_date,
        )

    def test_o6_compute_split_dates_matches_the_legacy_physically_filtered_dataframe(self):
        """O6 — pour une configuration donnée, compute_split_dates() doit produire les MÊMES
        `TrainTestWindows` que sur l'ancien DataFrame physiquement filtré (comportement de
        sélection legacy inchangé), même si Optimizer reçoit désormais le contexte élargi."""
        df = _build_synthetic_df(30)
        opt_start = _bar_date_str(df, 10)
        tt = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.6)

        legacy_execution_df = df[df["time_paris"] >= pd.Timestamp(opt_start, tz="Europe/Paris")]
        legacy_execution_df = legacy_execution_df.reset_index(drop=True)
        legacy_windows = compute_split_dates(legacy_execution_df, tt)

        window = resolve_execution_window(df, opt_start_date=opt_start)
        new_windows = compute_split_dates(window.execution_df, tt)

        assert new_windows == legacy_windows
        assert isinstance(new_windows, TrainTestWindows)

    def test_o7_train_phase_receives_context_with_train_bounds_and_exclusive_boundary(
        self, monkeypatch,
    ):
        """O7/C5 — la phase TRAIN reçoit le contexte élargi (historique amont dispo pour le
        warmup) borné à `train_start`/`boundary`, avec `end_boundary="exclusive"` explicite —
        la barre à `boundary` ne doit jamais influencer TRAIN."""
        df = _build_synthetic_df(30)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = self._config_with_train_test(opt_start_date=_bar_date_str(df, 5))
        config.param_ranges = []

        opt = Optimizer(config, df)
        opt.run(progress_cb=None, stop_flag_fn=None, already_tested=set())

        assert fake.calls, "au moins un backtest doit avoir été lancé (mode='grid' sans ranges)"
        windows = opt.resolved_train_test_windows
        assert windows is not None
        train_calls = [c for c in fake.calls if c["end_date"] == windows.boundary]
        assert train_calls, "au moins un appel TRAIN attendu (end_date == boundary)"
        for call in train_calls:
            assert call["start_date"] == windows.train_start
            assert call["end_boundary"] == "exclusive"
            assert call["len_df"] == len(opt.df)  # toujours le contexte complet, pas une coupe

    def test_o8_test_phase_receives_inclusive_boundary_start_and_never_sees_data_after_test_end(
        self, monkeypatch,
    ):
        """O8/C6 — la phase TEST démarre exactement à `boundary` (inclusif, explicite) et ne
        voit jamais de barre postérieure à `test_end` (pas de fuite du futur)."""
        df = _build_synthetic_df(30)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        monkeypatch.setattr(optimizer, "compute_score", lambda *a, **k: (1.0, False, None, []))
        config = self._config_with_train_test()
        config.param_ranges = []
        config.top_k_save = 1

        opt = Optimizer(config, df)
        opt.run(progress_cb=None, stop_flag_fn=None, already_tested=set())

        windows = opt.resolved_train_test_windows
        assert windows is not None
        test_calls = [c for c in fake.calls if c["end_date"] == windows.test_end]
        assert test_calls, "au moins un backtest TEST attendu"
        for call in test_calls:
            assert call["start_date"] == windows.boundary
            assert call["end_boundary"] == "inclusive"


# ═══════════════════════════════════════════════════════════════════════════════
# Fallback worker — même resolver que le chemin nominal (O9, O10)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFallbackWorkerUsesTheSameResolver:

    def test_o9_o10_fallback_produces_the_same_context_and_bounds_as_the_nominal_path(
        self, monkeypatch, tmp_path,
    ):
        """O9/O10 — le fallback _worker_run_single() (sans _worker_df_global, ex. worker
        redémarré) doit produire EXACTEMENT le même contexte et les mêmes bornes que le chemin
        nominal, pour une configuration identique — même resolver, jamais une seconde
        implémentation de filtrage."""
        df = _build_synthetic_df(20)
        opt_start = _bar_date_str(df, 10)

        import engine
        monkeypatch.setattr(engine, "load_data_from_source", lambda source, a, t: df.copy())

        config = _minimal_config(opt_start_date=opt_start)

        # Chemin nominal : résolution directe.
        nominal_window = resolve_execution_window(df, opt_start_date=opt_start)

        # Fallback : force _worker_df_global à None (simule un worker sans initializer).
        monkeypatch.setattr(optimizer, "_worker_df_global", None)
        fake = _RecordingRunBacktest()
        monkeypatch.setattr(engine, "run_backtest", fake)

        _worker_run_single({}, config, nominal_window.exec_start, nominal_window.exec_end)

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["len_df"] == len(nominal_window.context_df)
        assert call["start_date"] == nominal_window.exec_start
        assert call["end_date"] == nominal_window.exec_end


# ═══════════════════════════════════════════════════════════════════════════════
# benchmark_speed() — borné à la période effective (O11)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBenchmarkSpeedRespectsEffectiveWindow:

    def test_o11_benchmark_uses_the_resolved_context_and_bounds(self, monkeypatch):
        df = _build_synthetic_df(20)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = _minimal_config(opt_start_date=_bar_date_str(df, 10))

        benchmark_speed(config, df, n_sample=2)

        window = resolve_execution_window(df, opt_start_date=config.opt_start_date)
        assert len(fake.calls) == 2
        for call in fake.calls:
            assert call["len_df"] == len(window.context_df)
            assert call["start_date"] == window.exec_start
            assert call["end_date"] == window.exec_end


# ═══════════════════════════════════════════════════════════════════════════════
# df_rows_used — représente la sélection d'exécution, jamais le contexte élargi (O12)
# ═══════════════════════════════════════════════════════════════════════════════


class TestDfRowsUsedReflectsExecutionNotContext:

    def test_o12_df_rows_used_is_the_execution_row_count(self):
        df = _build_synthetic_df(30)
        config = _minimal_config(opt_start_date=_bar_date_str(df, 10))

        opt = Optimizer(config, df)

        window = resolve_execution_window(df, opt_start_date=config.opt_start_date)
        assert opt.df_rows_used == window.exec_row_count
        assert opt.df_rows_used != len(opt.df)  # le contexte élargi contient plus de lignes


# ═══════════════════════════════════════════════════════════════════════════════
# Revue adversariale (2026-09-12) — traversée RÉELLE Optimizer -> _run_single ->
# engine.run_backtest(), SANS monkeypatch : preuve empirique que les bornes produites par
# resolve_execution_window() (str ISO naïves via .strftime(), jamais un pd.Timestamp tz-aware
# déjà localisé) sont acceptées par le contrat réel de engine.py
# (`pd.Timestamp(start_date, tz="Europe/Paris")`) — vérifié aussi manuellement :
# `pd.Timestamp(pd.Timestamp("2026-01-01", tz="Europe/Paris"), tz="Europe/Paris")` lève
# `ValueError: Cannot pass a datetime or Timestamp with tzinfo with the tz parameter` — ce n'est
# PAS le type produit ici, mais le gap de couverture (aucun test existant ne traversait le vrai
# moteur) était réel et méritait d'être comblé explicitement.
# ═══════════════════════════════════════════════════════════════════════════════


class TestRealEngineAcceptsResolvedBounds:

    def _config_with_real_strategy(self, **overrides):
        from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
        return _minimal_config(
            strategy_module="strategies.perfect_revolution_v1",
            base_params=DEFAULT_PARAMS,
            **overrides,
        )

    def test_exec_start_and_exec_end_are_naive_iso_strings_not_timezone_aware_timestamps(self):
        """Type runtime exact vérifié — jamais un pd.Timestamp, jamais une chaîne avec offset."""
        df = _build_synthetic_df(20)

        window = resolve_execution_window(df, opt_start_date=_bar_date_str(df, 5))

        assert isinstance(window.exec_start, str)
        assert isinstance(window.exec_end, str)
        assert "+" not in window.exec_start  # pas d'offset de fuseau dans la chaîne
        assert "+" not in window.exec_end

    def test_no_train_test_bounds_are_accepted_by_the_real_engine(self):
        """Comble le gap : preuve réelle (pas monkeypatchée) que _run_single() -> vrai
        engine.run_backtest() accepte exec_start/exec_end sans lever d'exception."""
        from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
        df = _build_synthetic_df(20, freq_minutes=180)  # plusieurs bougies/jour, plus réaliste
        window = resolve_execution_window(df, opt_start_date=_bar_date_str(df, 5))
        config = self._config_with_real_strategy()

        result = _run_single(
            DEFAULT_PARAMS, config, window.context_df, window.exec_start, window.exec_end)

        assert isinstance(result, dict)
        assert "stats" in result and isinstance(result["stats"], dict)
        # _run_single() capture toute exception dans filter_reason="Exception: ..." plutôt que
        # de la laisser se propager — sa présence prouverait un rejet par le vrai moteur.
        assert not str(result.get("filter_reason", "")).startswith("Exception:")

    def test_max_rows_intraday_exec_end_keeps_the_exact_timestamp_not_truncated_to_a_date(self):
        """§7 — si max_rows termine la période en cours de journée, exec_end doit conserver
        l'heure exacte de cette dernière barre (jamais réduit à "YYYY-MM-DD", ce qui décalerait
        silencieusement la fin d'exécution)."""
        df = _build_synthetic_df(20, freq_minutes=180)  # 8 bougies/jour (24h/3h)
        window = resolve_execution_window(df, max_rows=5)  # coupe en plein milieu du jour 0

        assert window.exec_end == df["time_paris"].iloc[4].strftime("%Y-%m-%dT%H:%M:%S")
        assert window.exec_end.count(":") == 2  # heure:minute:seconde présentes, pas juste une date

        from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
        config = self._config_with_real_strategy()
        result = _run_single(
            DEFAULT_PARAMS, config, window.context_df, window.exec_start, window.exec_end)
        assert isinstance(result, dict)

    def test_empty_selection_produces_zero_trades_via_the_real_engine_never_the_whole_context(self):
        """§9 — point CRITIQUE : une sélection vide ne doit jamais, via le vrai moteur, exécuter
        tout le contexte. Vérifié ici avec le vrai engine.run_backtest() (pas une simple lecture
        de code) : context_df est lui-même vide (0 ligne) dans ce cas, donc structurellement
        aucune barre ne peut être exécutée quelles que soient les bornes transmises."""
        df = _build_synthetic_df(20, freq_minutes=180)
        window = resolve_execution_window(df, opt_start_date="2099-01-01")
        assert window.exec_start is None and window.exec_end is None
        assert len(window.context_df) == 0  # jamais tout le df source
        from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
        config = self._config_with_real_strategy()

        result = _run_single(
            DEFAULT_PARAMS, config, window.context_df, window.exec_start, window.exec_end)

        assert result["stats"].get("n_trades", 0) == 0
        assert result["filtered"] is True

    def test_benchmark_speed_on_empty_selection_never_benchmarks_the_whole_context(self):
        """§10 — même vérification pour benchmark_speed(), avec le vrai moteur."""
        df = _build_synthetic_df(20, freq_minutes=180)
        config = self._config_with_real_strategy(opt_start_date="2099-01-01")

        ms = benchmark_speed(config, df, n_sample=2)

        # 0 ligne à traiter -> quasi instantané (quelques ms), jamais le temps d'un vrai run sur
        # tout le contexte (20 bougies synthétiques n'est de toute façon pas lourd, mais la
        # garantie structurelle vient de resolve_execution_window(), pas d'une mesure de temps
        # fragile — voir test précédent pour la preuve directe sur context_df).
        window = resolve_execution_window(df, opt_start_date=config.opt_start_date)
        assert len(window.context_df) == 0
        assert isinstance(ms, float)


# ═══════════════════════════════════════════════════════════════════════════════
# Correction scientifique du split TRAIN/TEST (2026-09-12) — TrainTestWindows, C1-C15
# ═══════════════════════════════════════════════════════════════════════════════
#
# compute_split_dates() perdait la précision horaire (troncature "%Y-%m-%d") et créait un trou
# temporel silencieux TRAIN→TEST (audit read-only précédent, quantifié : 28.6% de barres perdues
# sur un exemple synthétique 7 jours). Correction : TrainTestWindows(train_start, boundary,
# test_end) en ISO-8601 complet (fraction/offset préservés), TRAIN=[train_start,boundary)
# exclusive, TEST=[boundary,test_end] inclusive. `compute_split_dates()` reste appelé sur
# `execution_df` (jamais le contexte élargi) — comportement de sélection inchangé (O6).
#
# "Aucune double inclusion à la frontière" est déjà prouvée au niveau moteur par Dette B
# (tests/test_engine.py::TestEndBoundarySemantics::test_b4_...) — les tests C2/C3 ci-dessous
# vérifient la partie NOUVELLE : que compute_split_dates() produit des bornes qui couvrent
# exactement [global_start, global_end] sans reste, pas une re-preuve de la mécanique moteur.


def _fine_synthetic_df(n_bars: int, start: str = "2024-01-02T00:00:00", freq_minutes: int = 3):
    """Bougies M3 (par défaut) — nécessaire pour les tests de précision infra-journalière
    (contrairement à `_build_synthetic_df`, qui produit une bougie par jour par défaut)."""
    return _build_synthetic_df(n_bars, start=start, freq_minutes=freq_minutes)


def _paris_midnight_df(dates: list):
    """DataFrame minimal avec `time_paris` explicite, à minuit LOCAL Europe/Paris pour chaque
    date fournie (contourne le décalage UTC->Paris de `_build_synthetic_df`, dont les bougies
    "quotidiennes" tombent en réalité à 01h/02h locale puisque `time` y est traité comme UTC —
    nécessaire ici pour des tests qui exigent une bougie exactement à minuit local)."""
    times = pd.DatetimeIndex([pd.Timestamp(d, tz="Europe/Paris") for d in dates])
    return pd.DataFrame({"time_paris": times})


class TestTrainTestWindowsContract:
    """C1, C7, C8, C15 — compute_split_dates() en tant que fonction pure."""

    def test_c1_ratio_method_preserves_sub_second_precision_never_truncated_to_a_date(self):
        """C1 — la fraction de seconde de `boundary` (méthode ratio) doit survivre, pas être
        écrasée par une troncature `%Y-%m-%d` comme dans l'ancien comportement bugué."""
        df = _fine_synthetic_df(100)  # 100 bougies M3 -> duration = 99*180 = 17820s
        tt = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=1 / 7)  # non entier

        windows = compute_split_dates(df, tt)

        boundary_ts = pd.Timestamp(windows.boundary)
        assert boundary_ts.microsecond != 0, (
            f"boundary={windows.boundary!r} a perdu sa fraction de seconde (1/3 de 17820s "
            "produit un instant non entier — la précision doit être préservée)"
        )

    def test_c2_c3_train_and_test_windows_cover_the_full_range_without_gap_or_duplicate(self):
        """C2/C3 — TRAIN ∪ TEST = [global_start, global_end] exactement (aucune barre perdue),
        et la frontière partagée n'apparaît que dans TEST (aucune duplication) — garanti
        structurellement par construction (boundary = fin exclusive TRAIN = début inclusif
        TEST), vérifié ici sur l'identité produite par compute_split_dates()."""
        df = _fine_synthetic_df(50)
        tt = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.4)

        windows = compute_split_dates(df, tt)

        assert windows.train_start == df["time_paris"].iloc[0].isoformat()
        assert windows.test_end == df["time_paris"].iloc[-1].isoformat()
        # boundary est la SEULE frontière partagée — TRAIN s'arrête juste avant (exclusive),
        # TEST commence pile dessus (inclusive) : aucun instant n'appartient aux deux, aucun
        # instant entre train_start et test_end n'est hors des deux fenêtres.
        assert df["time_paris"].iloc[0].isoformat() < windows.boundary < df["time_paris"].iloc[-1].isoformat()

    def test_c7_test_end_is_the_real_last_timestamp_of_execution_df_never_a_truncated_date(self):
        """C7 — test_end ne doit jamais être réduit à "YYYY-MM-DD" (ancien bug)."""
        df = _fine_synthetic_df(20)
        tt = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.5)

        windows = compute_split_dates(df, tt)

        assert windows.test_end == df["time_paris"].iloc[-1].isoformat()
        assert len(windows.test_end) > len("2024-01-02")  # pas juste une date

    def test_c8_date_method_boundary_is_midnight_of_split_date_first_day_of_test_d1(self):
        """C8 — décision D1 : split_date = PREMIER jour de TEST, à 00:00 Europe/Paris. Une
        bougie datée exactement de split_date (00:00:00 local) appartient à TEST, jamais à
        TRAIN."""
        dates = [f"2024-01-{d:02d}" for d in range(2, 32)]  # 30 jours, minuit local exact
        df = _paris_midnight_df(dates)
        split_day = "2024-01-12"
        tt = TrainTestConfig(enabled=True, split_method="date", split_date=split_day)

        windows = compute_split_dates(df, tt)

        expected_boundary = pd.Timestamp(split_day, tz="Europe/Paris").isoformat()
        assert windows.boundary == expected_boundary
        # La bougie du 12 janvier (exactement à boundary) doit appartenir à TEST :
        # TRAIN=[.,boundary) l'exclut structurellement.
        matching_bar = df[df["time_paris"] == pd.Timestamp(split_day, tz="Europe/Paris")]
        assert len(matching_bar) == 1
        assert matching_bar["time_paris"].iloc[0].isoformat() == windows.boundary

    def test_c15_ratio_at_or_below_zero_raises(self):
        df = _fine_synthetic_df(20)
        tt = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.0)
        with pytest.raises(ValueError):
            compute_split_dates(df, tt)

    def test_c15_ratio_at_or_above_one_raises(self):
        df = _fine_synthetic_df(20)
        tt = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=1.0)
        with pytest.raises(ValueError):
            compute_split_dates(df, tt)

    def test_c15_negative_ratio_raises(self):
        df = _fine_synthetic_df(20)
        tt = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=-0.2)
        with pytest.raises(ValueError):
            compute_split_dates(df, tt)

    def test_c15_ratio_above_one_raises(self):
        df = _fine_synthetic_df(20)
        tt = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=1.4)
        with pytest.raises(ValueError):
            compute_split_dates(df, tt)

    def test_c15_date_method_without_split_date_raises_instead_of_silently_falling_back_to_ratio(self):
        """Défaut adjacent découvert pendant l'implémentation (repli silencieux vers 'ratio' si
        split_date est absent malgré split_method="date") — corrigé dans le même mouvement,
        cohérent avec la politique "jamais de repli silencieux" déjà établie par Dette B."""
        df = _fine_synthetic_df(20)
        tt = TrainTestConfig(enabled=True, split_method="date", split_date=None)
        with pytest.raises(ValueError):
            compute_split_dates(df, tt)

    def test_c15_split_date_before_dataset_raises(self):
        df = _build_synthetic_df(20)
        tt = TrainTestConfig(enabled=True, split_method="date", split_date="2000-01-01")
        with pytest.raises(ValueError):
            compute_split_dates(df, tt)

    def test_c15_split_date_after_dataset_raises(self):
        df = _build_synthetic_df(20)
        tt = TrainTestConfig(enabled=True, split_method="date", split_date="2099-01-01")
        with pytest.raises(ValueError):
            compute_split_dates(df, tt)

    def test_c15_split_date_equal_to_last_bar_raises_only_a_single_test_bar_is_not_acceptable(self):
        """Mission §9 — `boundary == global_end` ne laisserait qu'une seule barre TEST :
        rejeté explicitement (global_start < boundary < global_end strict)."""
        dates = [f"2024-01-{d:02d}" for d in range(2, 22)]  # 20 jours, minuit local exact
        df = _paris_midnight_df(dates)
        last_day = "2024-01-21"  # date exacte de la dernière bougie (minuit local)
        tt = TrainTestConfig(enabled=True, split_method="date", split_date=last_day)
        with pytest.raises(ValueError):
            compute_split_dates(df, tt)

    def test_c15_empty_dataset_with_train_test_active_raises(self):
        df = _build_synthetic_df(0) if False else _build_synthetic_df(1).iloc[0:0]
        tt = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.5)
        with pytest.raises(ValueError):
            compute_split_dates(df, tt)

    def test_c15_single_bar_dataset_with_train_test_active_raises(self):
        """Une seule barre -> global_start == global_end -> impossible de produire deux régions
        temporelles distinctes -> ValueError explicite, jamais une fenêtre vide masquée."""
        df = _build_synthetic_df(1)
        tt = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.5)
        with pytest.raises(ValueError):
            compute_split_dates(df, tt)

    def test_c15_error_messages_are_explicit_not_generic(self):
        """Les erreurs doivent nommer le problème (pas une AssertionError/KeyError opaque)."""
        df = _fine_synthetic_df(20)
        tt = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=1.5)
        with pytest.raises(ValueError, match="train_ratio"):
            compute_split_dates(df, tt)


class _FakeSequentialPool:
    """Remplace `ProcessPoolExecutor` dans les tests C10/C11 : exécute `submit()`
    immédiatement, dans le MÊME process (pas de vrai spawn/pickling — impossible à monkeypatcher
    autrement, voir mission §19 note O9), tout en exerçant réellement le code de
    `_run_batch_parallel()` (futures réels, `as_completed`, `initializer`). Honore
    `max_workers`/`initializer`/`initargs` comme le vrai `ProcessPoolExecutor`."""

    def __init__(self, max_workers=None, initializer=None, initargs=()):
        if initializer:
            initializer(*initargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def submit(self, fn, *args, **kwargs):
        from concurrent.futures import Future
        fut = Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - defensif, comme le vrai pool
            fut.set_exception(exc)
        return fut


class TestEndBoundaryPropagationAcrossExecutionPaths:
    """C5, C6, C10, C11, C12 — `end_boundary` doit être transmis IDENTIQUEMENT quel que soit le
    chemin d'exécution (séquentiel, "parallèle" via pool factice, fallback worker), et rester
    "inclusive" par défaut hors train/test (non-régression)."""

    def test_c5_sequential_batch_forwards_explicit_end_boundary(self, monkeypatch):
        df = _build_synthetic_df(10)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = _minimal_config()
        opt = Optimizer(config, df)

        opt._run_batch_sequential(
            [{}], None, None, set(), start_date="2024-01-01", end_date="2024-01-05",
            end_boundary="exclusive",
        )

        assert fake.calls and fake.calls[0]["end_boundary"] == "exclusive"

    def test_c12_sequential_batch_defaults_to_inclusive_when_end_boundary_omitted(self, monkeypatch):
        """Non-régression : le chemin sans train/test n'appelle jamais explicitement
        `end_boundary`, donc le défaut doit rester `"inclusive"` (comportement historique)."""
        df = _build_synthetic_df(10)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = _minimal_config()
        opt = Optimizer(config, df)

        opt._run_batch_sequential(
            [{}], None, None, set(), start_date="2024-01-01", end_date="2024-01-05")

        assert fake.calls and fake.calls[0]["end_boundary"] == "inclusive"

    def test_c10_parallel_batch_forwards_the_same_end_boundary_as_sequential(self, monkeypatch):
        df = _build_synthetic_df(10)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        # ProcessPoolExecutor est importé localement dans _run_batch_parallel() (pas un
        # attribut de module `optimizer`) — patcher à la source (concurrent.futures), relu à
        # chaque appel grâce à l'import local.
        monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", _FakeSequentialPool)
        config = _minimal_config(n_workers=2)
        opt = Optimizer(config, df)

        opt._run_batch_parallel(
            [{}], None, None, set(), start_date="2024-01-01", end_date="2024-01-05",
            end_boundary="exclusive",
        )

        assert fake.calls and fake.calls[0]["end_boundary"] == "exclusive"

    def test_c11_fallback_worker_forwards_end_boundary(self, monkeypatch):
        """C11 — `_worker_run_single()` sans `_worker_df_global` (fallback) transmet
        `end_boundary` exactement comme le chemin nominal."""
        df = _build_synthetic_df(10)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        monkeypatch.setattr(engine, "load_data_from_source", lambda source, a, t: df.copy())
        monkeypatch.setattr(optimizer, "_worker_df_global", None)
        config = _minimal_config()

        _worker_run_single({}, config, "2024-01-01", "2024-01-05", end_boundary="exclusive")

        assert fake.calls and fake.calls[0]["end_boundary"] == "exclusive"

    def test_c11_nominal_worker_path_forwards_end_boundary_too(self, monkeypatch):
        df = _build_synthetic_df(10)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        monkeypatch.setattr(optimizer, "_worker_df_global", df)

        _worker_run_single({}, _minimal_config(), "2024-01-01", "2024-01-05", end_boundary="exclusive")

        assert fake.calls and fake.calls[0]["end_boundary"] == "exclusive"


class TestTrainTestSemanticsVersioning:
    """C14 — garde de reprise cross-version (fonction pure `validate_resume_train_test_semantics`)."""

    def test_c14_no_train_test_on_the_resumed_run_is_never_blocked(self):
        """Reprise SANS train/test activé sur le run courant : jamais bloquée par cette dette,
        quelle que soit la sémantique (ou son absence) côté source."""
        current = TrainTestConfig(enabled=False)
        validate_resume_train_test_semantics(current, None, "some_source")
        validate_resume_train_test_semantics(
            current, {"train_test_semantics_version": "anything-else"}, "some_source")

    def test_c14_matching_version_is_allowed(self):
        current = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.6)
        validate_resume_train_test_semantics(
            current, {"train_test_semantics_version": TRAIN_TEST_SEMANTICS_VERSION}, "src")

    def test_c14_missing_version_field_treated_as_legacy_and_refused(self):
        """Job source antérieur à cette correction : jamais de champ -> traité comme "legacy",
        distinct de la version courante -> reprise refusée."""
        current = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.6)
        with pytest.raises(TrainTestSemanticsMismatch):
            validate_resume_train_test_semantics(current, {}, "legacy_src")

    def test_c14_source_config_none_treated_as_legacy_and_refused(self):
        """Le job source n'a même pas pu être chargé (config_used.json introuvable) : jamais un
        mélange silencieux, refus explicite."""
        current = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.6)
        with pytest.raises(TrainTestSemanticsMismatch):
            validate_resume_train_test_semantics(current, None, "missing_src")

    def test_c14_different_version_string_is_refused(self):
        current = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.6)
        with pytest.raises(TrainTestSemanticsMismatch):
            validate_resume_train_test_semantics(
                current, {"train_test_semantics_version": "some-other-version"}, "src")

    def test_c14_error_message_names_the_source_run_id_and_both_versions(self):
        current = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.6)
        with pytest.raises(TrainTestSemanticsMismatch, match="legacy_src"):
            validate_resume_train_test_semantics(current, {}, "legacy_src")


class TestRealEngineTrainTestIntegration:
    """§32/C9 — au moins un test traverse réellement Optimizer -> run/batch -> _run_single ->
    vrai engine.run_backtest(), pour TRAIN ET TEST, sans monkeypatcher le moteur."""

    def test_optimizer_run_with_train_test_resolves_valid_windows_and_executes_train_via_the_real_engine(self):
        """La phase TRAIN de `Optimizer.run()` passe TOUJOURS par le vrai moteur (indépendant du
        score obtenu, contrairement à la phase TEST — gating pré-existant, non lié à cette
        correction, voir §785+)."""
        from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
        df = _fine_synthetic_df(400, freq_minutes=180)  # plusieurs jours, réaliste
        config = _minimal_config(
            strategy_module="strategies.perfect_revolution_v1",
            base_params=DEFAULT_PARAMS,
            mode="grid",
            param_ranges=[],
            train_test=TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.5),
        )

        opt = Optimizer(config, df)
        all_results, _ = opt.run(progress_cb=None, stop_flag_fn=None, already_tested=set())

        windows = opt.resolved_train_test_windows
        assert windows is not None
        assert windows.train_start < windows.boundary < windows.test_end
        assert all_results, "au moins un résultat attendu (mode grid, 1 combo) — TRAIN a tourné"
        assert not str(all_results[0].get("filter_reason", "")).startswith("Exception:")

    def test_train_and_test_phases_both_execute_via_the_real_engine_without_exception(self):
        """§32 — preuve directe, sans monkeypatcher `engine.run_backtest`, que TRAIN
        (`end_boundary="exclusive"`) ET TEST (`end_boundary="inclusive"`) s'exécutent tous deux
        via le vrai moteur pour la même fenêtre résolue, indépendamment du filtre de score de
        `Optimizer.run()` (préexistant, hors scope de cette correction)."""
        from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
        df = _fine_synthetic_df(400, freq_minutes=180)
        config = _minimal_config(
            strategy_module="strategies.perfect_revolution_v1",
            base_params=DEFAULT_PARAMS,
            train_test=TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.5),
        )
        opt = Optimizer(config, df)
        windows = compute_split_dates(opt._execution_df, config.train_test)

        train_result = _run_single(
            DEFAULT_PARAMS, config, opt.df, windows.train_start, windows.boundary,
            end_boundary="exclusive",
        )
        test_result = _run_single(
            DEFAULT_PARAMS, config, opt.df, windows.boundary, windows.test_end,
            end_boundary="inclusive",
        )

        for label, result in (("TRAIN", train_result), ("TEST", test_result)):
            assert isinstance(result, dict), label
            assert "stats" in result and isinstance(result["stats"], dict), label
            assert not str(result.get("filter_reason", "")).startswith("Exception:"), (
                f"{label} a été rejeté par le vrai moteur : {result.get('filter_reason')}"
            )

    def test_c9_dst_spring_forward_boundary_is_handled_end_to_end_without_crash(self):
        """C9 — dataset traversant le changement d'heure Europe/Paris (2024-03-31, spring
        forward) : aucune AmbiguousTimeError/NonExistentTimeError, TRAIN et TEST s'exécutent
        réellement via le vrai moteur."""
        from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
        df = _fine_synthetic_df(80, start="2024-03-28T00:00:00", freq_minutes=180)
        config = _minimal_config(
            strategy_module="strategies.perfect_revolution_v1",
            base_params=DEFAULT_PARAMS,
            mode="grid",
            param_ranges=[],
            train_test=TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.5),
        )

        opt = Optimizer(config, df)
        all_results, _ = opt.run(progress_cb=None, stop_flag_fn=None, already_tested=set())

        windows = opt.resolved_train_test_windows
        assert windows is not None
        # Round-trip : le boundary doit rester parseable et cohérent (pas de décalage d'offset).
        boundary_ts = pd.Timestamp(windows.boundary)
        assert boundary_ts.tzinfo is not None
        assert all_results


class TestMaxRowsAndTrainTestCombination:
    """C13 — max_rows/opt_start_date/opt_end_date combinés à train/test : compute_split_dates()
    continue d'opérer sur `execution_df` (la sélection réduite), jamais le contexte élargi."""

    def test_c13_train_test_windows_stay_within_the_max_rows_reduced_selection(self):
        from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
        df = _build_synthetic_df(30)
        config = _minimal_config(
            opt_start_date=_bar_date_str(df, 5),
            max_rows=10,
            base_params=dict(DEFAULT_PARAMS),
            train_test=TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.5),
        )

        opt = Optimizer(config, df)
        opt.run(progress_cb=None, stop_flag_fn=None, already_tested=set())

        windows = opt.resolved_train_test_windows
        exec_window = resolve_execution_window(
            df, opt_start_date=config.opt_start_date, max_rows=config.max_rows)
        assert windows.train_start == exec_window.execution_df["time_paris"].iloc[0].isoformat()
        assert windows.test_end == exec_window.execution_df["time_paris"].iloc[-1].isoformat()


# ═══════════════════════════════════════════════════════════════════════════════
# State/Session Readiness V1 (2026-09-14) — intégration Optimizer, SR-T1/T2/T3/T4/T14-16/T21
# ═══════════════════════════════════════════════════════════════════════════════
#
# Architecture READY-3 : la stratégie déclare (state_readiness(params)), le protocole
# (Optimizer.run(), APRÈS compute_split_dates(), jamais dedans) résout requested->effective.
# engine.py et compute_split_dates() restent strictement inchangés.


def _paris_range_df(start: str, end: str, freq_minutes: int = 60):
    """DataFrame minimal (`time_paris` uniquement) sur une plage Europe/Paris exacte et
    contrôlée — nécessaire pour placer `boundary` à un instant local précis et prévisible
    (contourne le décalage UTC->Paris de `_build_synthetic_df`)."""
    times = pd.date_range(start, end, freq=f"{freq_minutes}min", tz="Europe/Paris")
    return pd.DataFrame({"time_paris": pd.DatetimeIndex(times)})


class _StatelessFakeStrategy:
    """Stratégie factice SANS `state_readiness` — legacy pur, ne doit jamais déclencher
    d'ajustement (SR-T1)."""
    WARMUP = 2
    def reset(self): pass
    def prepare(self, df, params): return df
    def on_bar(self, i, df, context, params): return None


def _ratio_boundary_iso(start: str, end: str, ratio: float, tz: str = "Europe/Paris") -> str:
    """Recalcule le `boundary` EXACT que produirait `compute_split_dates()` pour ces bornes/ce
    ratio — même formule (`global_start + Timedelta(seconds=duration*ratio)`), pour éviter toute
    hypothèse sur une valeur "ronde" que l'arithmétique flottante ne produit pas forcément à la
    nanoseconde près."""
    global_start = pd.Timestamp(start, tz=tz)
    global_end = pd.Timestamp(end, tz=tz)
    duration = (global_end - global_start).total_seconds()
    return (global_start + pd.Timedelta(seconds=duration * ratio)).isoformat()


class TestStateReadinessAdjustsRatioBoundary:

    def _config_with_ratio(self, train_ratio):
        from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
        return _minimal_config(
            mode="grid",
            param_ranges=[],
            base_params=dict(DEFAULT_PARAMS),
            train_test=TrainTestConfig(enabled=True, split_method="ratio", train_ratio=train_ratio),
        )

    def test_sr_admissible_boundary_before_or_start_is_never_adjusted(self, monkeypatch):
        """ratio=0.3 sur 48h depuis 2024-01-10T00:00 -> boundary brute ≈ 14:24, avant
        or_start=15:30 (DEFAULT_PARAMS) -> aucun ajustement attendu."""
        df = _paris_range_df("2024-01-10T00:00:00", "2024-01-12T00:00:00", freq_minutes=60)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = self._config_with_ratio(0.3)

        opt = Optimizer(config, df)
        opt.run(progress_cb=None, stop_flag_fn=None, already_tested=set())

        requested = _ratio_boundary_iso("2024-01-10T00:00:00", "2024-01-12T00:00:00", 0.3)
        windows = opt.resolved_train_test_windows
        resolution = opt.state_readiness_resolution
        assert windows.boundary == requested
        assert resolution is not None
        assert resolution.adjusted is False
        assert resolution.requested_boundary == requested
        assert resolution.effective_boundary == requested

    def test_sr_t4_boundary_after_or_start_is_shifted_to_next_local_midnight(self, monkeypatch):
        """ratio=0.35 sur 48h -> boundary brute ≈ 16:48, après or_start=15:30 -> décalée au
        minuit local Europe/Paris du jour suivant."""
        df = _paris_range_df("2024-01-10T00:00:00", "2024-01-12T00:00:00", freq_minutes=60)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        # Score forcé positif : ce test vérifie les bornes transmises au moteur pour la phase
        # TEST (gating pré-existant sur score>0, non lié à cette mission — voir O8), pas la
        # logique de scoring/filtres réelle.
        monkeypatch.setattr(optimizer, "compute_score", lambda *a, **k: (1.0, False, None, []))
        config = self._config_with_ratio(0.35)
        config.top_k_save = 1

        opt = Optimizer(config, df)
        opt.run(progress_cb=None, stop_flag_fn=None, already_tested=set())

        requested = _ratio_boundary_iso("2024-01-10T00:00:00", "2024-01-12T00:00:00", 0.35)
        expected_effective = pd.Timestamp("2024-01-11 00:00:00", tz="Europe/Paris").isoformat()
        windows = opt.resolved_train_test_windows
        resolution = opt.state_readiness_resolution
        assert windows.boundary == expected_effective
        assert resolution.adjusted is True
        assert resolution.requested_boundary == requested
        assert resolution.effective_boundary == expected_effective

        # SR-T14 (contiguïté) / SR-T15 (aucune duplication) : TRAIN et TEST utilisent la MÊME
        # frontière effective, TRAIN exclusive / TEST inclusive.
        train_calls = [c for c in fake.calls if c["end_date"] == expected_effective]
        test_calls = [c for c in fake.calls if c["start_date"] == expected_effective]
        assert train_calls and train_calls[0]["end_boundary"] == "exclusive"
        assert test_calls and test_calls[0]["end_boundary"] == "inclusive"

    def test_sr_t1_stateless_strategy_never_adjusted(self, monkeypatch):
        """Même configuration que le test précédent (qui provoquerait un ajustement pour une
        stratégie readiness-aware) mais avec une stratégie SANS state_readiness -> aucun
        ajustement, comportement legacy strictement inchangé."""
        df = _paris_range_df("2024-01-10T00:00:00", "2024-01-12T00:00:00", freq_minutes=60)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        monkeypatch.setattr(
            optimizer, "_load_strategy",
            lambda module_path: (None, _StatelessFakeStrategy()),
        )
        config = self._config_with_ratio(0.35)

        opt = Optimizer(config, df)
        opt.run(progress_cb=None, stop_flag_fn=None, already_tested=set())

        requested = _ratio_boundary_iso("2024-01-10T00:00:00", "2024-01-12T00:00:00", 0.35)
        windows = opt.resolved_train_test_windows
        assert windows.boundary == requested  # jamais décalée
        assert opt.state_readiness_resolution is None

    def test_sr_t16_no_room_after_adjustment_raises_explicitly(self, monkeypatch):
        """ratio=0.7 sur 24h (2024-01-10T00:00 -> 2024-01-11T00:00) -> boundary brute ≈ 16:48,
        décalée au 2024-01-11T00:00 == test_end EXACTEMENT -> aucune barre TEST possible ->
        NoStateReadyBoundary explicite, jamais une fenêtre TEST vide silencieuse."""
        df = _paris_range_df("2024-01-10T00:00:00", "2024-01-11T00:00:00", freq_minutes=60)
        import engine
        monkeypatch.setattr(engine, "run_backtest", _RecordingRunBacktest())
        config = self._config_with_ratio(0.7)

        opt = Optimizer(config, df)
        with pytest.raises(NoStateReadyBoundary):
            opt.run(progress_cb=None, stop_flag_fn=None, already_tested=set())

    def test_sr_t21_train_test_semantics_version_unaffected_by_readiness(self):
        """La correction readiness n'altère jamais la géométrie exact-boundary-v2 elle-même."""
        assert TRAIN_TEST_SEMANTICS_VERSION == "exact-boundary-v2"


class TestStateReadinessSemanticsVersioning:
    """C14-style — garde de reprise cross-version dédiée à la readiness, INDÉPENDANTE de
    TrainTestSemanticsMismatch (deux contrats distincts, voir docs/adr à venir)."""

    def test_not_readiness_aware_never_blocked(self):
        validate_resume_state_readiness_semantics(False, None, "src")
        validate_resume_state_readiness_semantics(
            False, {"state_readiness_semantics_version": "anything-else"}, "src")

    def test_matching_version_is_allowed(self):
        validate_resume_state_readiness_semantics(
            True, {"state_readiness_semantics_version": STATE_READINESS_SEMANTICS_VERSION}, "src")

    def test_missing_version_field_treated_as_legacy_and_refused(self):
        with pytest.raises(StateReadinessSemanticsMismatch):
            validate_resume_state_readiness_semantics(True, {}, "legacy_src")

    def test_source_config_none_treated_as_legacy_and_refused(self):
        with pytest.raises(StateReadinessSemanticsMismatch):
            validate_resume_state_readiness_semantics(True, None, "missing_src")

    def test_different_version_string_is_refused(self):
        with pytest.raises(StateReadinessSemanticsMismatch):
            validate_resume_state_readiness_semantics(
                True, {"state_readiness_semantics_version": "some-other-version"}, "src")

    def test_error_message_names_the_source_run_id(self):
        with pytest.raises(StateReadinessSemanticsMismatch, match="legacy_src"):
            validate_resume_state_readiness_semantics(True, {}, "legacy_src")


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 2 — resolve_execution_window() : opt_end_date accepte désormais un timestamp
# ISO-8601 complet en borne EXCLUSIVE exacte (nécessaire pour borner une fenêtre TRAIN de fold
# Walk-Forward à [train_start_k, effective_boundary_k), ADR 0021 Décision 6) — distinct du mode
# historique "YYYY-MM-DD" (inclusif jusqu'à 23:59:59), inchangé pour tout appelant existant.
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveExecutionWindowIsoTimestampOptEndDate:

    def test_full_iso_timestamp_opt_end_date_excludes_the_boundary_bar(self):
        """Une barre exactement à opt_end_date (ISO-8601 complet) est EXCLUE — jamais incluse
        comme avec le mode 'YYYY-MM-DD' historique (23:59:59 inclusif)."""
        df = _build_synthetic_df(5, start="2024-01-01T00:00:00", freq_minutes=60)
        boundary = df["time_paris"].iloc[2].isoformat()

        window = resolve_execution_window(df, opt_end_date=boundary)

        assert window.exec_row_count == 2
        assert window.execution_df["time_paris"].iloc[-1] == df["time_paris"].iloc[1]

    def test_plain_date_opt_end_date_behavior_is_unchanged(self):
        """Non-régression explicite : le mode historique 'YYYY-MM-DD' (jamais de 'T') reste
        inchangé — inclusif jusqu'à 23:59:59."""
        df = _build_synthetic_df(20)
        window = resolve_execution_window(df, opt_end_date=_bar_date_str(df, 14))
        assert window.exec_row_count == 15

    def test_iso_timestamp_opt_start_date_already_worked_before_this_mission(self):
        """opt_start_date acceptait déjà un timestamp ISO-8601 complet (comparaison `>=` directe,
        aucune concaténation de chaîne) — documenté ici explicitement comme le pendant symétrique
        du nouveau mode de opt_end_date, pas une régression trouvée."""
        df = _build_synthetic_df(5, start="2024-01-01T00:00:00", freq_minutes=60)
        start = df["time_paris"].iloc[2].isoformat()

        window = resolve_execution_window(df, opt_start_date=start)

        assert window.execution_df["time_paris"].iloc[0] == df["time_paris"].iloc[2]

    def test_full_iso_timestamp_start_and_end_together_bound_a_half_open_window(self):
        df = _build_synthetic_df(10, start="2024-01-01T00:00:00", freq_minutes=60)
        start = df["time_paris"].iloc[2].isoformat()
        end = df["time_paris"].iloc[6].isoformat()

        window = resolve_execution_window(df, opt_start_date=start, opt_end_date=end)

        assert window.exec_row_count == 4  # indices 2,3,4,5 — 6 exclu
        assert window.execution_df["time_paris"].iloc[0] == df["time_paris"].iloc[2]
        assert window.execution_df["time_paris"].iloc[-1] == df["time_paris"].iloc[5]


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 2 — _run_single() : paramètre optionnel include_artifacts renvoyant aussi
# trades/equity (ADR 0021 Décision 6, relecture de clôture) — rétrocompatible, absent par défaut.
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunSingleIncludeArtifacts:

    def test_default_omits_trades_and_equity_from_the_returned_dict(self, monkeypatch):
        df = _build_synthetic_df(5)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = _minimal_config()

        result = _run_single({}, config, df)

        assert "trades" not in result
        assert "equity" not in result

    def test_include_artifacts_true_returns_the_real_trades_and_equity_dataframes(self, monkeypatch):
        df = _build_synthetic_df(5)
        trades_df = pd.DataFrame([{"resultat_net": 10.0, "raison_sortie": "fin-donnees"}])
        equity_df = pd.DataFrame([{"date": "x", "capital": 10_010.0}])

        def fake_run_backtest(df_, strategy, params, **kwargs):
            return trades_df, equity_df, {"n_trades": 1, "net_ret_pct": 0.1}

        import engine
        monkeypatch.setattr(engine, "run_backtest", fake_run_backtest)
        config = _minimal_config()

        result = _run_single({}, config, df, include_artifacts=True)

        assert result["trades"] is trades_df
        assert result["equity"] is equity_df

    def test_include_artifacts_true_on_exception_returns_none_not_a_crash(self, monkeypatch):
        import engine

        def boom(*a, **k):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(engine, "run_backtest", boom)
        config = _minimal_config()
        df = _build_synthetic_df(5)

        result = _run_single({}, config, df, include_artifacts=True)

        assert result["filtered"] is True
        assert result["trades"] is None
        assert result["equity"] is None

    def test_include_artifacts_true_on_zero_trades_returns_the_real_empty_dataframes(self, monkeypatch):
        import engine
        empty_trades = pd.DataFrame()
        empty_equity = pd.DataFrame()
        monkeypatch.setattr(
            engine, "run_backtest",
            lambda *a, **k: (empty_trades, empty_equity, {"n_trades": 0}),
        )
        config = _minimal_config()
        df = _build_synthetic_df(5)

        result = _run_single({}, config, df, include_artifacts=True)

        assert result["filter_reason"] == "Aucun trade"
        assert result["trades"] is empty_trades
        assert result["equity"] is empty_equity


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 2 — Optimizer.run(run_test_validation=...) : nouveau seam additif (ADR 0021
# Décision 6). False saute la phase de validation TEST existante (~lignes 1044-1065) sans y
# toucher autrement ; True (défaut) laisse tout appelant existant strictement inchangé.
# ═══════════════════════════════════════════════════════════════════════════════


class TestOptimizerRunTestValidationSeam:

    def _config_with_train_test(self):
        from strategies.perfect_revolution_v1 import DEFAULT_PARAMS
        return _minimal_config(
            mode="grid", param_ranges=[],
            base_params=dict(DEFAULT_PARAMS),
            train_test=TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.6),
        )

    def test_run_test_validation_false_skips_the_test_phase_entirely(self, monkeypatch):
        df = _build_synthetic_df(30)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = self._config_with_train_test()
        config.top_k_save = 1

        opt = Optimizer(config, df)
        all_results, _sensitivity = opt.run(run_test_validation=False)

        assert all_results
        assert "score_test" not in all_results[0]
        windows = opt.resolved_train_test_windows
        assert not [c for c in fake.calls if c["end_date"] == windows.test_end]

    def test_run_test_validation_true_default_matches_omitting_the_argument(self, monkeypatch):
        df = _build_synthetic_df(30)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        monkeypatch.setattr(optimizer, "compute_score", lambda *a, **k: (1.0, False, None, []))
        config = self._config_with_train_test()
        config.top_k_save = 1

        opt_default = Optimizer(config, df)
        results_default, _ = opt_default.run()

        opt_explicit = Optimizer(config, df)
        results_explicit, _ = opt_explicit.run(run_test_validation=True)

        assert "score_test" in results_default[0]
        assert "score_test" in results_explicit[0]


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 2 — Optimizer.run(seed=...) / _run_stratified_sample() (ADR 0021 Décisions 9/11).
# Régression review indépendante (tentative 2, finding MAJEUR) : _run_stratified_sample() tirait
# ses combinaisons via random.choice() GLOBAL, sans aucun random.seed() nulle part dans
# optimizer.py — non-déterministe pour tout appelant (mode="general", 50 000 < N <= 500 000)
# n'ayant pas explicitement seedé le module random process-wide. seed=None (défaut, tout appelant
# existant) doit laisser ce comportement historique strictement inchangé.
# ═══════════════════════════════════════════════════════════════════════════════


class TestStratifiedSampleSeed:

    def _config_general(self, **overrides):
        defaults = dict(
            mode="general",
            param_ranges=[
                ParamRange(name="a", param_type="number", label="a", min_val=0, max_val=9, step=1),
                ParamRange(name="b", param_type="number", label="b", min_val=0, max_val=9, step=1),
            ],
        )
        defaults.update(overrides)
        return _minimal_config(**defaults)

    def test_run_without_seed_kwarg_defaults_the_instance_attribute_to_none(self, monkeypatch):
        df = _build_synthetic_df(5)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = _minimal_config(mode="grid", param_ranges=[])

        opt = Optimizer(config, df)
        opt.run()

        assert opt._search_seed is None

    def test_run_seed_kwarg_sets_the_instance_attribute_before_dispatch(self, monkeypatch):
        df = _build_synthetic_df(5)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = _minimal_config(mode="grid", param_ranges=[])

        opt = Optimizer(config, df)
        opt.run(seed=777)

        assert opt._search_seed == 777

    def test_same_seed_produces_identical_sampled_combos_across_two_instances(self, monkeypatch):
        df = _build_synthetic_df(5)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = self._config_general()

        opt1 = Optimizer(config, df)
        opt1._search_seed = 42
        results1 = opt1._run_stratified_sample(5)

        opt2 = Optimizer(config, df)
        opt2._search_seed = 42
        results2 = opt2._run_stratified_sample(5)

        assert [r["params"] for r in results1] == [r["params"] for r in results2]
        assert len(results1) == 5

    def test_different_seeds_can_produce_different_sampled_combos(self, monkeypatch):
        """Preuve que le seed influence réellement le tirage (pas ignoré silencieusement) : sur
        100 combinaisons possibles (10x10) et un échantillon de 5, deux seeds distincts
        produisent, empiriquement, des ensembles de candidats différents."""
        df = _build_synthetic_df(5)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = self._config_general()

        opt1 = Optimizer(config, df)
        opt1._search_seed = 1
        results1 = opt1._run_stratified_sample(5)

        opt2 = Optimizer(config, df)
        opt2._search_seed = 2
        results2 = opt2._run_stratified_sample(5)

        assert [r["params"] for r in results1] != [r["params"] for r in results2]

    def test_no_seed_preserves_the_historical_global_random_module_behavior(self, monkeypatch):
        """Rétrocompatibilité stricte (comportement historique, tout appelant existant) : sans
        seed, `_run_stratified_sample()` doit continuer à consommer le module `random` global —
        vérifié en contrôlant son état via `random.seed()` avant l'appel, seule façon de rendre ce
        tirage reproductible avant cette mission."""
        import random as random_module
        df = _build_synthetic_df(5)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = self._config_general()

        random_module.seed(123)
        opt1 = Optimizer(config, df)
        results1 = opt1._run_stratified_sample(5)

        random_module.seed(123)
        opt2 = Optimizer(config, df)
        results2 = opt2._run_stratified_sample(5)

        assert [r["params"] for r in results1] == [r["params"] for r in results2]


class TestReachesStratifiedSampleSingleSourceOfTruth:
    """ADR 0021 Décision 9, review indépendante (tentative 3, finding MAJEUR) :
    `optimizer.reaches_stratified_sample()` doit être le SEUL point de vérité consulté par
    `run_mode4()` (ci-dessous) ET par `walk_forward.run_fold_train()` (tests/test_walk_forward.py,
    `TestRunFoldTrainRefusesNonDeterministicSearchWithoutSeed`) — jamais deux répliques
    indépendantes de la même condition de branchement."""

    def _config(self, n_values_per_param: int, n_params: int = 4, **overrides):
        ranges = [
            ParamRange(
                name=f"p{i}", param_type="number", label=f"p{i}",
                min_val=0, max_val=n_values_per_param - 1, step=1,
            )
            for i in range(n_params)
        ]
        defaults = dict(mode="general", param_ranges=ranges)
        defaults.update(overrides)
        return _minimal_config(**defaults)

    def test_false_for_deterministic_dispatch_modes_regardless_of_combination_count(self):
        for mode in ("single_var", "cross_zone", "grid"):
            config = self._config(n_values_per_param=20, mode=mode)  # 20**4 = 160 000 combos
            assert reaches_stratified_sample(config) is False

    def test_false_when_declared_combinations_are_at_or_below_the_min_threshold(self):
        config = self._config(n_values_per_param=1, n_params=1)  # 1 combo
        assert reaches_stratified_sample(config) is False

    def test_true_when_declared_combinations_fall_strictly_inside_the_stratified_range(self):
        config = self._config(n_values_per_param=20)  # 20**4 = 160 000, dans ]50k, 500k]
        assert reaches_stratified_sample(config) is True

    def test_false_above_the_max_threshold_progressive_grid_takes_over_instead(self):
        config = self._config(n_values_per_param=30)  # 30**4 = 810 000 > 500 000
        assert reaches_stratified_sample(config) is False

    def test_false_when_max_combinations_is_explicitly_capped(self):
        """`max_combinations` fait toujours dispatcher vers `run_mode3()`, jamais vers
        `_run_stratified_sample()`, quel que soit le nombre de combinaisons déclarées."""
        config = self._config(n_values_per_param=20, max_combinations=1000)
        assert reaches_stratified_sample(config) is False

    def test_optimizer_run_dispatch_stays_consistent_with_deterministic_dispatch_modes_constant(
        self, monkeypatch,
    ):
        """Garde de non-régression structurel : si le dispatch dict interne de `Optimizer.run()`
        divergeait un jour du module-level `DETERMINISTIC_DISPATCH_MODES` (renommage de mode,
        ajout d'une entrée), l'assertion runtime de `run()` doit échouer immédiatement plutôt que
        de laisser `reaches_stratified_sample()`/le garde de walk_forward.py se désynchroniser
        silencieusement."""
        import optimizer as optimizer_module
        df = _build_synthetic_df(5)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        monkeypatch.setattr(
            optimizer_module, "DETERMINISTIC_DISPATCH_MODES", frozenset({"not_a_real_mode"}),
        )
        config = _minimal_config(mode="grid", param_ranges=[])

        with pytest.raises(AssertionError):
            Optimizer(config, df).run()
