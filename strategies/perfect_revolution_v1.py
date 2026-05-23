"""
NASDAQ Perfect Revolution V1.1
Traduction fidèle du code ProRealTime fourni.
"""

import pandas as pd
import numpy as np

STRATEGY_NAME = "NASDAQ Perfect Revolution V1.1"
WARMUP        = 130

DEFAULT_PARAMS = {
    "use_compounding":       False,
    "base_contracts":        1,
    "capital_per_contract":  8000,
    "max_contracts":         5,
    "allow_short":           False,
    "trade_monday":          True,
    "trade_tuesday":         True,
    "trade_wednesday":       True,
    "trade_thursday":        False,
    "trade_friday":          True,
    "or_start_h":            15,
    "or_start_m":            30,
    "or_end_h":              16,
    "or_end_m":              0,
    "t_start_h":             16,
    "t_start_m":             0,
    "t_end_h":               21,
    "t_end_m":               15,
    "t_flat_h":              22,
    "t_flat_m":              15,
    "max_trades_per_day":    2,
    "max_daily_loss_pct":    2.0,
    "ema_trend_len":         120,
    "ema_filter_len":        20,
    "atr_len":               14,
    "min_atr":               20.0,
    "min_or_pts":            60.0,
    "max_or_pts":            400.0,
    "break_buffer":          5.0,
    "stop_pct":              1.20,
    "target_pct":            6.75,
    "use_trailing":          True,
    "trail_start_pct":       2.60,
    "trail_pts":             650.0,
    "max_bars_in_trade":     40,
}

# Schéma pour la génération automatique de l'UI
PARAM_SCHEMA = {
    "Stratégie": {
        "allow_short":       {"type": "bool",  "label": "Autoriser les Shorts"},
        "use_compounding":   {"type": "bool",  "label": "Compounding (réinvestissement)"},
    },
    "Jours tradés": {
        "trade_monday":      {"type": "bool",  "label": "Lundi"},
        "trade_tuesday":     {"type": "bool",  "label": "Mardi"},
        "trade_wednesday":   {"type": "bool",  "label": "Mercredi"},
        "trade_thursday":    {"type": "bool",  "label": "Jeudi"},
        "trade_friday":      {"type": "bool",  "label": "Vendredi"},
    },
    "Indicateurs": {
        "ema_trend_len":     {"type": "int",   "label": "EMA Tendance (barres)", "min": 5,   "max": 500},
        "ema_filter_len":    {"type": "int",   "label": "EMA Filtre (barres)",   "min": 5,   "max": 200},
        "atr_len":           {"type": "int",   "label": "ATR Période",           "min": 5,   "max": 50},
        "min_atr":           {"type": "float", "label": "ATR Minimum",           "min": 0.0, "max": 200.0, "step": 1.0},
    },
    "Range d'ouverture": {
        "min_or_pts":        {"type": "float", "label": "Range min (pts)",       "min": 0.0, "max": 500.0, "step": 5.0},
        "max_or_pts":        {"type": "float", "label": "Range max (pts)",       "min": 0.0, "max": 2000.0,"step": 10.0},
        "break_buffer":      {"type": "float", "label": "Buffer cassure (pts)",  "min": 0.0, "max": 50.0,  "step": 1.0},
    },
    "Stop / Target": {
        "stop_pct":          {"type": "float", "label": "Stop Loss (%)",         "min": 0.1, "max": 10.0,  "step": 0.1},
        "target_pct":        {"type": "float", "label": "Take Profit (%)",       "min": 0.1, "max": 30.0,  "step": 0.25},
    },
    "Trailing Stop": {
        "use_trailing":      {"type": "bool",  "label": "Trailing actif"},
        "trail_start_pct":   {"type": "float", "label": "Déclenchement (%)",     "min": 0.1, "max": 10.0,  "step": 0.1},
        "trail_pts":         {"type": "float", "label": "Distance trailing (pts)","min": 10.0,"max": 2000.0,"step": 10.0},
    },
    "Gestion des risques": {
        "max_bars_in_trade": {"type": "int",   "label": "Time stop (barres)",    "min": 1,   "max": 200},
        "max_trades_per_day":{"type": "int",   "label": "Max trades / jour",     "min": 1,   "max": 10},
        "max_daily_loss_pct":{"type": "float", "label": "Perte max journalière (%)","min":0.1,"max":20.0,"step":0.1},
    },
}


class Strategy:
    """Implémentation de NASDAQ Perfect Revolution V1.1"""

    def __init__(self):
        self.reset()

    def reset(self):
        """Réinitialise l'état journalier. Ne touche pas aux caches numpy
        (peuplés par prepare() qui est appelé une seule fois)."""
        self._cur_date         = None
        self._trades_today     = 0
        self._day_start_profit = 0.0
        self._or_high          = None
        self._or_low           = None
        self._or_ready         = False
        self._system_on        = True

    # ── Indicateurs ───────────────────────────────────────────
    def prepare(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        df["ema_trend"]  = df["close"].ewm(span=params["ema_trend_len"],  adjust=False).mean()
        df["ema_filter"] = df["close"].ewm(span=params["ema_filter_len"], adjust=False).mean()

        prev_c = df["close"].shift(1).fillna(df["close"])
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - prev_c).abs(),
            (df["low"]  - prev_c).abs(),
        ], axis=1).max(axis=1)
        # Wilder's ATR (RMA)
        df["atr"] = tr.ewm(alpha=1.0 / params["atr_len"], adjust=False).mean()

        # Pré-extraction des arrays — évite df["col"].values[i] dans la hot loop
        self._high  = df["high"].values
        self._low   = df["low"].values
        self._close = df["close"].values
        self._open  = df["open"].values
        self._ema_t = df["ema_trend"].values
        self._ema_f = df["ema_filter"].values
        self._atr   = df["atr"].values
        self._hm    = df["hm_p"].values
        self._dow   = df["dow_p"].values
        self._date  = df["date_p"].values

        return df

    # ── Utilitaires horaires ───────────────────────────────────
    @staticmethod
    def _hv(hm):
        return hm[0] * 100 + hm[1]

    def _in_range(self, hm, start, end):
        t, s, e = self._hv(hm), self._hv(start), self._hv(end)
        return s <= t < e

    def _after(self, hm, thresh):
        return self._hv(hm) >= self._hv(thresh)

    # ── Logique principale ────────────────────────────────────
    def on_bar(self, i: int, df: pd.DataFrame, context: dict, params: dict):
        in_pos       = context["in_pos"]
        strat_profit = context["strat_profit"]
        initial_cap  = context.get("initial_capital", 10_000)
        last_exit    = context["last_exit_bar"]

        # Lecture rapide via caches numpy peuplés par prepare()
        hm   = self._hm[i]
        dow  = self._dow[i]
        date = self._date[i]
        h    = self._high[i]
        l    = self._low[i]
        c    = self._close[i]
        o    = self._open[i]

        # ── Reset journalier ──────────────────────────────────
        if date != self._cur_date:
            self._cur_date         = date
            self._trades_today     = 0
            self._day_start_profit = strat_profit
            self._or_high          = None
            self._or_low           = None
            self._or_ready         = False
            self._system_on        = True

        # ── Sécurité perte journalière ────────────────────────
        daily_pnl = strat_profit - self._day_start_profit
        if daily_pnl <= -(initial_cap * params["max_daily_loss_pct"] / 100):
            self._system_on = False

        # ── Horaires depuis les params ────────────────────────
        or_start = (params["or_start_h"], params["or_start_m"])
        or_end   = (params["or_end_h"],   params["or_end_m"])
        t_start  = (params["t_start_h"],  params["t_start_m"])
        t_flat   = (params["t_flat_h"],   params["t_flat_m"])

        # ── Construction range d'ouverture ────────────────────
        if self._in_range(hm, or_start, or_end):
            if self._or_high is None or h > self._or_high:
                self._or_high = h
            if self._or_low is None or l < self._or_low:
                self._or_low = l

        if self._after(hm, or_end) and self._or_high is not None:
            self._or_ready = True

        or_pts   = (self._or_high - self._or_low) if (self._or_high and self._or_low) else 0
        range_ok = (
            self._or_ready
            and params["min_or_pts"] <= or_pts <= params["max_or_pts"]
        )

        # ── Sortie flat-time (si en position) ─────────────────
        if in_pos and self._after(hm, t_flat):
            return {"action": "exit", "at": "next_open", "reason": "flat-time"}

        if in_pos:
            return None  # exits standards gérés par l'engine

        # ── Filtres d'entrée ──────────────────────────────────
        if i <= last_exit:
            return None

        trade_days = {
            0: params["trade_monday"],
            1: params["trade_tuesday"],
            2: params["trade_wednesday"],
            3: params["trade_thursday"],
            4: params["trade_friday"],
        }

        t_end    = (params["t_end_h"], params["t_end_m"])
        day_ok   = trade_days.get(dow, False)
        time_ok  = self._in_range(hm, t_start, t_end)
        count_ok = self._trades_today < params["max_trades_per_day"]
        flat_ok  = not self._after(hm, t_flat)
        vol_ok   = self._atr[i] >= params["min_atr"]

        if not (self._system_on and day_ok and time_ok and count_ok and vol_ok and range_ok and flat_ok):
            return None

        # ── Calcul des indicateurs sur la bougie courante ─────
        ema_t = self._ema_t
        ema_f = self._ema_f

        bar_range  = h - l
        body_size  = abs(c - o)
        body_ratio = body_size / bar_range if bar_range > 0 else 0

        # ── Signal LONG ───────────────────────────────────────
        trend_long = (
            c > ema_t[i]
            and ema_f[i] > ema_t[i]
            and ema_t[i] > ema_t[i - 5]
        )
        confirm_long  = c > o and body_ratio >= 0.50
        breakout_long = (
            self._or_high is not None
            and c > self._or_high + params["break_buffer"]
        )

        if trend_long and confirm_long and breakout_long:
            self._trades_today += 1
            return {
                "action":          "enter",
                "direction":       "long",
                "stop_pct":        params["stop_pct"],
                "target_pct":      params["target_pct"],
                "use_trailing":    params["use_trailing"],
                "trail_start_pct": params["trail_start_pct"],
                "trail_pts":       params["trail_pts"],
                "max_bars":        params["max_bars_in_trade"],
                "nb_contracts":    1,
            }

        # ── Signal SHORT ──────────────────────────────────────
        if params["allow_short"]:
            trend_short = (
                c < ema_t[i]
                and ema_f[i] < ema_t[i]
                and ema_t[i] < ema_t[i - 5]
            )
            confirm_short  = c < o and body_ratio >= 0.50
            breakout_short = (
                self._or_low is not None
                and c < self._or_low - params["break_buffer"]
            )

            if trend_short and confirm_short and breakout_short:
                self._trades_today += 1
                return {
                    "action":          "enter",
                    "direction":       "short",
                    "stop_pct":        params["stop_pct"],
                    "target_pct":      params["target_pct"],
                    "use_trailing":    params["use_trailing"],
                    "trail_start_pct": params["trail_start_pct"],
                    "trail_pts":       params["trail_pts"],
                    "max_bars":        params["max_bars_in_trade"],
                    "nb_contracts":    1,
                }

        return None
