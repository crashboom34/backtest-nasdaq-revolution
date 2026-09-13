"""
tests/test_perfect_revolution_v1.py — Warmup dynamique des indicateurs (2026-09-13).

Contexte : `WARMUP=130` statique est mathématiquement insuffisant (audit read-only préalable) —
résiduel de l'influence de la condition initiale de l'EWM `(1-alpha)^k` à k=130 barres = 11.46 %
pour `ema_trend_len=120` (DEFAULT_PARAMS), jusqu'à 59.45 % pour `ema_trend_len=500` (max schéma).
`Strategy.required_warmup(params)` encapsule ce calcul de convergence — le moteur (`engine.py`)
reste ignorant d'EMA/ATR/epsilon (deep module, voir `/codebase-design`).

Portée strictement INDICATEUR. La readiness d'état path-dependent (opening range, compteurs
journaliers) reste une dette séparée, hors scope de cette mission (voir audit précédent).

Tous les tests recalculent la valeur attendue de façon INDÉPENDANTE (formule réécrite ici, pas
importée depuis la production) — évite un test tautologique qui ne ferait que réimporter la
même logique que celle testée.
"""

from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.perfect_revolution_v1 import DEFAULT_PARAMS, PARAM_SCHEMA, Strategy


def _independent_k(alpha: float, epsilon: float = 0.01) -> int:
    """Recalcul indépendant de `k = ceil(log(epsilon) / log(1-alpha))` — même formule que la
    production, mais réécrite ici pour ne jamais masquer un bug de la vraie implémentation."""
    return math.ceil(math.log(epsilon) / math.log(1 - alpha))


def _independent_ema_k(span: int, epsilon: float = 0.01) -> int:
    return _independent_k(2 / (span + 1), epsilon)


def _independent_atr_k(n: int, epsilon: float = 0.01) -> int:
    return _independent_k(1 / n, epsilon)


# ═══════════════════════════════════════════════════════════════════════════════
# W-T1, W-T2, W-T3 — monotonie : required_warmup augmente avec chaque longueur
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequiredWarmupMonotonicity:

    def test_w_t1_increases_with_ema_trend_len(self):
        p1 = dict(DEFAULT_PARAMS, ema_trend_len=50)
        p2 = dict(DEFAULT_PARAMS, ema_trend_len=200)
        assert Strategy.required_warmup(p2) > Strategy.required_warmup(p1)

    def test_w_t2_increases_with_ema_filter_len(self):
        # ema_filter_len doit dominer pour observer l'effet isolément (sinon masqué par trend).
        p1 = dict(DEFAULT_PARAMS, ema_trend_len=5, ema_filter_len=10, atr_len=5)
        p2 = dict(DEFAULT_PARAMS, ema_trend_len=5, ema_filter_len=400, atr_len=5)
        assert Strategy.required_warmup(p2) > Strategy.required_warmup(p1)

    def test_w_t3_increases_with_atr_len(self):
        p1 = dict(DEFAULT_PARAMS, ema_trend_len=5, ema_filter_len=5, atr_len=10)
        p2 = dict(DEFAULT_PARAMS, ema_trend_len=5, ema_filter_len=5, atr_len=50)
        assert Strategy.required_warmup(p2) > Strategy.required_warmup(p1)


# ═══════════════════════════════════════════════════════════════════════════════
# W-T4, W-T5 — valeurs exactes (epsilon=1%, lookback ema_trend[i-5] inclus)
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequiredWarmupExactValues:

    def test_w_t4_default_params_matches_independent_formula_including_lookback(self):
        expected_trend  = _independent_ema_k(DEFAULT_PARAMS["ema_trend_len"]) + 5
        expected_filter = _independent_ema_k(DEFAULT_PARAMS["ema_filter_len"])
        expected_atr    = _independent_atr_k(DEFAULT_PARAMS["atr_len"])
        expected = max(expected_trend, expected_filter, expected_atr)

        result = Strategy.required_warmup(DEFAULT_PARAMS)

        assert result == expected
        # Valeur de référence documentée (mission), obtenue par calcul indépendant — jamais
        # hardcodée côté production.
        assert result == 282

    def test_w_t5_max_schema_params_matches_independent_formula(self):
        max_params = dict(DEFAULT_PARAMS, ema_trend_len=500, ema_filter_len=200, atr_len=50)
        expected_trend  = _independent_ema_k(500) + 5
        expected_filter = _independent_ema_k(200)
        expected_atr    = _independent_atr_k(50)
        expected = max(expected_trend, expected_filter, expected_atr)

        result = Strategy.required_warmup(max_params)

        assert result == expected
        assert result == 1157


# ═══════════════════════════════════════════════════════════════════════════════
# W-T6 — paramètres non positifs : erreur explicite (jamais dépendant de PARAM_SCHEMA)
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequiredWarmupInvalidParams:

    @pytest.mark.parametrize("key", ["ema_trend_len", "ema_filter_len", "atr_len"])
    @pytest.mark.parametrize("bad_value", [0, -1, -50])
    def test_w_t6_non_positive_param_raises(self, key, bad_value):
        bad_params = dict(DEFAULT_PARAMS, **{key: bad_value})
        with pytest.raises(ValueError):
            Strategy.required_warmup(bad_params)

    @pytest.mark.parametrize("key", ["ema_trend_len", "ema_filter_len", "atr_len"])
    @pytest.mark.parametrize("bad_value", [None, "20", [], True, False])
    def test_non_numeric_or_boolean_param_raises_a_clear_value_error(self, key, bad_value):
        """Trouvaille de revue (mineure) corrigée : `None`/chaîne produisaient un `TypeError`
        non nommé, et `True`/`False` (sous-classe d'`int` en Python) passaient la validation de
        positivité puis faisaient planter le calcul avec un `math domain error` opaque. Doit
        désormais lever un `ValueError` explicite, cohérent avec les autres valeurs invalides."""
        bad_params = dict(DEFAULT_PARAMS, **{key: bad_value})
        with pytest.raises(ValueError, match=key):
            Strategy.required_warmup(bad_params)


# ═══════════════════════════════════════════════════════════════════════════════
# W-T7 — config externe dépassant les maxima UI (PARAM_SCHEMA) : reste valide
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequiredWarmupBeyondUiSchema:

    def test_w_t7_params_exceeding_ui_schema_maxima_are_accepted(self):
        """La validité scientifique ne dépend jamais des maxima UI — une config externe
        (job JSON direct) peut légitimement dépasser PARAM_SCHEMA tant qu'elle reste
        mathématiquement positive."""
        schema_max_trend = PARAM_SCHEMA["Indicateurs"]["ema_trend_len"]["max"]
        beyond_ui = schema_max_trend + 500
        params = dict(DEFAULT_PARAMS, ema_trend_len=beyond_ui)

        result = Strategy.required_warmup(params)

        expected = _independent_ema_k(beyond_ui) + 5
        assert result == expected


# ═══════════════════════════════════════════════════════════════════════════════
# W-T13 — le lookback ema_trend[i-5] est réellement verrouillé
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequiredWarmupLookbackLock:

    def test_w_t13_trend_dominant_case_includes_the_minus_5_lookback_offset(self):
        """ema_trend seul domine largement (filter/atr courts) — l'écart mesuré doit être
        EXACTEMENT +5, jamais 0 ni un autre décalage arbitraire. Un mutant qui supprimerait le
        +5 dans la production ferait échouer ce test."""
        params = dict(DEFAULT_PARAMS, ema_trend_len=300, ema_filter_len=5, atr_len=5)
        k_trend_alone = _independent_ema_k(300)

        result = Strategy.required_warmup(params)

        assert result == k_trend_alone + 5
        assert result != k_trend_alone
