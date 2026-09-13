"""
tests/test_strategy_contracts.py — State/Session Readiness V1 (2026-09-14).

Règle simple et déterministe (aucun calendrier, aucun replay) : `requested_boundary` convertie
en heure locale (fuseau déclaré par la stratégie, Europe/Paris pour Perfect Revolution) ; si
l'heure locale est `<= latest_safe_start_hour:minute`, la frontière est déjà admissible
(`effective_boundary == requested_boundary`) ; sinon elle est décalée au **minuit local du jour
calendaire suivant** — construction DST-safe (date locale + 1 jour, puis relocalisation),
JAMAIS `+ Timedelta(hours=24)` (vérifié empiriquement bugué d'1h les jours de changement
d'heure).

Portée strictement la fonction PURE `resolve_state_ready_boundary()` — aucune dépendance à
`engine.py`/`optimizer.py`/un DataFrame réel. Intégration Optimizer testée séparément dans
`tests/test_optimizer.py`.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_contracts import (
    DailyStateReadiness,
    StateReadinessResolution,
    resolve_state_ready_boundary,
)


def _spec(h=15, m=30, tz="Europe/Paris"):
    return DailyStateReadiness(latest_safe_start_hour=h, latest_safe_start_minute=m, timezone=tz)


class TestNoReadinessSpec:

    def test_sr_t1_none_spec_returns_requested_unchanged(self):
        """SR-T1 — stratégie stateless (aucune déclaration) : jamais d'ajustement."""
        requested = pd.Timestamp("2024-01-10 17:00:00", tz="Europe/Paris").isoformat()

        res = resolve_state_ready_boundary(requested, None)

        assert isinstance(res, StateReadinessResolution)
        assert res.requested_boundary == requested
        assert res.effective_boundary == requested
        assert res.adjusted is False


class TestAdmissibleBoundaries:

    def test_sr_t2_before_or_start_unchanged(self):
        requested = pd.Timestamp("2024-01-10 14:00:00", tz="Europe/Paris").isoformat()
        res = resolve_state_ready_boundary(requested, _spec())
        assert res.effective_boundary == requested
        assert res.adjusted is False

    def test_sr_t3_exactly_or_start_unchanged(self):
        """Frontière == or_start exactement : admissible (comparaison inclusive)."""
        requested = pd.Timestamp("2024-01-10 15:30:00", tz="Europe/Paris").isoformat()
        res = resolve_state_ready_boundary(requested, _spec(15, 30))
        assert res.effective_boundary == requested
        assert res.adjusted is False

    def test_sr_t11_method_date_d1_midnight_is_always_admissible(self):
        """Méthode date (D1) : split_date à minuit local — toujours <= or_start, jamais
        d'ajustement attendu (comportement scientifique inchangé pour ce cas courant)."""
        requested = pd.Timestamp("2024-01-10 00:00:00", tz="Europe/Paris").isoformat()
        res = resolve_state_ready_boundary(requested, _spec())
        assert res.effective_boundary == requested
        assert res.adjusted is False


class TestNonAdmissibleBoundariesShiftToNextLocalMidnight:

    def test_sr_t4_during_or_window_shifted(self):
        requested = pd.Timestamp("2024-01-10 15:45:00", tz="Europe/Paris").isoformat()
        res = resolve_state_ready_boundary(requested, _spec())
        expected = pd.Timestamp("2024-01-11 00:00:00", tz="Europe/Paris").isoformat()
        assert res.effective_boundary == expected
        assert res.adjusted is True

    def test_sr_t5_exactly_or_end_shifted(self):
        requested = pd.Timestamp("2024-01-10 16:00:00", tz="Europe/Paris").isoformat()
        res = resolve_state_ready_boundary(requested, _spec())
        expected = pd.Timestamp("2024-01-11 00:00:00", tz="Europe/Paris").isoformat()
        assert res.effective_boundary == expected
        assert res.adjusted is True

    def test_sr_t6_after_trading_window_shifted(self):
        requested = pd.Timestamp("2024-01-10 23:59:00", tz="Europe/Paris").isoformat()
        res = resolve_state_ready_boundary(requested, _spec())
        expected = pd.Timestamp("2024-01-11 00:00:00", tz="Europe/Paris").isoformat()
        assert res.effective_boundary == expected

    def test_sr_t7_custom_or_start_params_respected(self):
        """Utilise les paramètres RÉELS de la stratégie, jamais une constante 15:30 en dur."""
        requested = pd.Timestamp("2024-01-10 10:30:00", tz="Europe/Paris").isoformat()
        res = resolve_state_ready_boundary(requested, _spec(h=10, m=0))
        expected = pd.Timestamp("2024-01-11 00:00:00", tz="Europe/Paris").isoformat()
        assert res.effective_boundary == expected

    def test_sr_t8_friday_evening_shifts_to_saturday_not_monday(self):
        """Aucune notion de calendrier de marché — le prochain minuit local est samedi,
        parfaitement acceptable ; le moteur démarrera à la première barre réellement
        disponible >= cette frontière, aucune donnée n'est perdue."""
        requested = pd.Timestamp("2024-01-12 17:00:00", tz="Europe/Paris").isoformat()  # vendredi
        res = resolve_state_ready_boundary(requested, _spec())
        expected = pd.Timestamp("2024-01-13 00:00:00", tz="Europe/Paris").isoformat()  # samedi
        assert res.effective_boundary == expected

    def test_sr_t11_iso_string_with_different_utc_offset_converted_correctly(self):
        """Une frontière fournie dans un autre offset (ex. produite ailleurs en UTC) doit être
        convertie vers le fuseau déclaré avant comparaison — jamais une comparaison d'heure
        brute sur un offset différent."""
        requested_utc = "2024-01-10T16:45:00+00:00"  # = 17:45 Paris (hiver, +01:00)
        res = resolve_state_ready_boundary(requested_utc, _spec())
        expected = pd.Timestamp("2024-01-11 00:00:00", tz="Europe/Paris").isoformat()
        assert res.effective_boundary == expected


class TestDstSafety:

    def test_sr_t9_dst_spring_forward_uses_correct_local_midnight(self):
        """Le 31 mars 2024 est le jour du passage à l'heure d'été (bascule à 02:00 local, pas à
        minuit) — minuit local ce jour-là est donc encore en +01:00, ce qui EST le comportement
        correct de `pd.Timestamp(date, tz=)` (vérifié empiriquement avant implémentation)."""
        requested = pd.Timestamp("2024-03-30 17:00:00", tz="Europe/Paris").isoformat()
        res = resolve_state_ready_boundary(requested, _spec())
        expected = pd.Timestamp("2024-03-31 00:00:00", tz="Europe/Paris").isoformat()
        assert res.effective_boundary == expected
        assert res.effective_boundary == "2024-03-31T00:00:00+01:00"

    def test_sr_t10_dst_fall_back_uses_correct_local_midnight(self):
        """Le 27 octobre 2024 est le jour du passage à l'heure d'hiver (bascule à 03:00->02:00
        local) — minuit local ce jour-là est donc encore en +02:00."""
        requested = pd.Timestamp("2024-10-26 17:00:00", tz="Europe/Paris").isoformat()
        res = resolve_state_ready_boundary(requested, _spec())
        expected = pd.Timestamp("2024-10-27 00:00:00", tz="Europe/Paris").isoformat()
        assert res.effective_boundary == expected
        assert res.effective_boundary == "2024-10-27T00:00:00+02:00"

    def test_naive_24h_timedelta_bug_is_never_produced(self):
        """Garde de non-régression explicite contre le piège documenté par la mission :
        + Timedelta(hours=24) le jour du changement d'heure produirait 18:00, jamais 00:00.

        Point de rigueur (trouvaille de revue) : `pd.Timestamp(requested)` reconstruit depuis
        une chaîne ISO+offset perd le nom de zone (`Europe/Paris` -> simple offset fixe
        `UTC+01:00`) — additionner 24h à CE Timestamp ne traverse alors plus jamais la vraie
        bascule DST, et ne prouverait donc rien. Le "faux résultat" de comparaison doit être
        construit depuis un `pd.Timestamp` RÉELLEMENT zoné `Europe/Paris` (comme le ferait tout
        code de production qui commettrait cette erreur), pas depuis une chaîne réanalysée."""
        requested_ts = pd.Timestamp("2024-03-30 17:00:00", tz="Europe/Paris")
        requested = requested_ts.isoformat()

        res = resolve_state_ready_boundary(requested, _spec())

        wrong_value = (requested_ts + pd.Timedelta(hours=24)).isoformat()
        assert wrong_value == "2024-03-31T18:00:00+02:00"  # le vrai bug documenté : 18:00, pas 00:00
        assert res.effective_boundary != wrong_value
        assert pd.Timestamp(res.effective_boundary).time() == pd.Timestamp("00:00:00").time()
