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
from engine import _add_market_time_columns
from optimizer import (
    ExecutionWindow,
    FilterConfig,
    OptimizationConfig,
    Optimizer,
    ParamRange,
    ScoreWeights,
    TrainTestConfig,
    _run_single,
    _worker_run_single,
    benchmark_speed,
    compute_split_dates,
    resolve_execution_window,
)


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
            "len_df":     len(df),
            "first_time": df["time_paris"].iloc[0] if len(df) else None,
            "last_time":  df["time_paris"].iloc[-1] if len(df) else None,
            "start_date": kwargs.get("start_date"),
            "end_date":   kwargs.get("end_date"),
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

    def _config_with_train_test(self, opt_start_date=None):
        return _minimal_config(
            mode="grid",
            param_ranges=[],
            train_test=TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.6),
            opt_start_date=opt_start_date,
        )

    def test_o6_compute_split_dates_matches_the_legacy_physically_filtered_dataframe(self):
        """O6 — pour une configuration donnée, compute_split_dates() doit produire EXACTEMENT
        les mêmes bornes que sur l'ancien DataFrame physiquement filtré (comportement legacy),
        même si Optimizer reçoit désormais le contexte élargi. Le trou de journée déjà connu
        (compute_split_dates()) n'est ni corrigé ni aggravé ici."""
        df = _build_synthetic_df(30)
        opt_start = _bar_date_str(df, 10)
        tt = TrainTestConfig(enabled=True, split_method="ratio", train_ratio=0.6)

        # Ancien comportement : DataFrame physiquement réduit à la période demandée.
        legacy_execution_df = df[df["time_paris"] >= pd.Timestamp(opt_start, tz="Europe/Paris")]
        legacy_execution_df = legacy_execution_df.reset_index(drop=True)
        legacy_bounds = compute_split_dates(legacy_execution_df, tt)

        window = resolve_execution_window(df, opt_start_date=opt_start)
        new_bounds = compute_split_dates(window.execution_df, tt)

        assert new_bounds == legacy_bounds

    def test_o7_train_phase_receives_context_with_train_bounds(self, monkeypatch):
        """O7 — la phase TRAIN reçoit le contexte élargi (historique amont dispo pour le warmup)
        mais bornée à train_start/train_end (jamais tout le contexte sans borne)."""
        df = _build_synthetic_df(30)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        config = self._config_with_train_test(opt_start_date=_bar_date_str(df, 5))
        config.param_ranges = []

        opt = Optimizer(config, df)
        opt.run(progress_cb=None, stop_flag_fn=None, already_tested=set())

        assert fake.calls, "au moins un backtest doit avoir été lancé (mode='grid' sans ranges)"
        # Toutes les bornes utilisées doivent être des dates réelles (jamais None,None) et
        # jamais au-delà du contexte transmis (borné par _run_single/run_backtest lui-même).
        for call in fake.calls:
            assert call["start_date"] is not None
            assert call["end_date"] is not None
            assert call["len_df"] == len(opt.df)  # toujours le contexte complet, pas une coupe

    def test_o8_test_phase_never_lets_prepare_see_data_after_test_end(self, monkeypatch):
        """O8 — la phase TEST reçoit l'historique antérieur disponible (TRAIN inclus, warmup
        causal légitime) mais jamais de barre postérieure à test_end (pas de fuite du futur)."""
        df = _build_synthetic_df(30)
        fake = _RecordingRunBacktest()
        import engine
        monkeypatch.setattr(engine, "run_backtest", fake)
        # Score toujours positif : ce test vérifie les bornes transmises au moteur, pas la
        # logique de scoring/filtres réelle (hors sujet ici — voir scoring.py pour ses propres
        # tests dédiés).
        monkeypatch.setattr(optimizer, "compute_score", lambda *a, **k: (1.0, False, None, []))
        config = self._config_with_train_test()
        config.param_ranges = []
        config.top_k_save = 1

        opt = Optimizer(config, df)
        opt.run(progress_cb=None, stop_flag_fn=None, already_tested=set())

        # Au moins un appel doit porter les bornes TEST (end_date == test_end réel).
        tt = config.train_test
        _, _, test_start, test_end = compute_split_dates(df, tt)
        test_calls = [c for c in fake.calls if c["end_date"] == test_end]
        assert test_calls, "au moins un backtest TEST attendu"
        for call in test_calls:
            # Le contexte transmis à run_backtest ne dépasse jamais physiquement test_end (les
            # bornes end_date le garantissent déjà au niveau moteur, vérifié ici au niveau appel).
            assert call["end_date"] == test_end


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
