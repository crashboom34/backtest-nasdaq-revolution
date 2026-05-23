"""
NASDAQ Perfect Revolution V1.1 — Backtest Python
Traduction fidèle du code ProRealTime/ProOrder fourni.
"""

import pandas as pd
import numpy as np
import os
import sys
from zoneinfo import ZoneInfo

# ═══════════════════════════════════════════════════════════════════
# PARAMETRES
# ═══════════════════════════════════════════════════════════════════

CSV_FILE        = "nasdaq_3m.csv"
SYMBOL          = "US100"
INITIAL_CAPITAL = 10_000.0

SPREAD   = 1.0   # stress-test spread (unités de prix)
SLIP_IN  = 0.5   # slippage à l'entrée
SLIP_OUT = 0.5   # slippage à la sortie

# Money management
USE_COMPOUNDING      = False
BASE_CONTRACTS       = 1
CAPITAL_PER_CONTRACT = 8_000
MAX_CONTRACTS        = 5

# Shorts
ALLOW_SHORT = False

# Jours autorisés (0=Lun, 1=Mar, 2=Mer, 3=Jeu, 4=Ven)
TRADE_DAYS = {0: True, 1: True, 2: True, 3: False, 4: True}

# Horaires Paris (heure, minute)
OR_START  = (15, 30)
OR_END    = (16,  0)
T_START   = (16,  0)
T_END     = (21, 15)
T_FLAT    = (22, 15)

MAX_TRADES_PER_DAY = 2
MAX_DAILY_LOSS     = -(INITIAL_CAPITAL * 2.0 / 100)  # -200

# Indicateurs
EMA_TREND_LEN  = 120
EMA_FILTER_LEN = 20
ATR_LEN        = 14
MIN_ATR        = 20

# Filtre range
MIN_OR_PTS   = 60
MAX_OR_PTS   = 400
BREAK_BUFFER = 5

# Stop / Target
STOP_PCT   = 1.20
TARGET_PCT = 6.75

# Trailing
USE_TRAILING    = True
TRAIL_START_PCT = 2.60
TRAIL_PTS       = 650.0  # unités de prix (≈ 2.25% sur 28900)

# Time stop
MAX_BARS_IN_TRADE = 40

PARIS = ZoneInfo("Europe/Paris")
SEP   = "-" * 58


# ═══════════════════════════════════════════════════════════════════
# UTILITAIRES
# ═══════════════════════════════════════════════════════════════════

def hm_val(hm):
    return hm[0] * 100 + hm[1]

def in_range(hm, start, end):
    t, s, e = hm_val(hm), hm_val(start), hm_val(end)
    return s <= t < e

def at_or_after(hm, thresh):
    return hm_val(hm) >= hm_val(thresh)

def calc_contracts(capital, strat_profit):
    if not USE_COMPOUNDING:
        return BASE_CONTRACTS
    cur = max(INITIAL_CAPITAL + strat_profit, INITIAL_CAPITAL)
    nb  = max(BASE_CONTRACTS, int(cur / CAPITAL_PER_CONTRACT))
    return min(nb, MAX_CONTRACTS)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    print(f"\n{'=' * 58}")
    print("  NASDAQ Perfect Revolution V1.1 — Backtest Python")
    print(f"{'=' * 58}")

    # ── Chargement ───────────────────────────────────────────
    if not os.path.exists(CSV_FILE):
        print(f"[ERREUR] {CSV_FILE} introuvable.")
        sys.exit(1)

    df = pd.read_csv(CSV_FILE, parse_dates=["time"])
    df["time_paris"] = (
        df["time"].dt.tz_localize("UTC").dt.tz_convert(PARIS)
    )
    df["date_p"] = df["time_paris"].dt.date
    df["h_p"]    = df["time_paris"].dt.hour
    df["m_p"]    = df["time_paris"].dt.minute
    df["dow_p"]  = df["time_paris"].dt.dayofweek
    df["hm_p"]   = list(zip(df["h_p"], df["m_p"]))

    n     = len(df)
    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values
    opn   = df["open"].values

    # ── Indicateurs ──────────────────────────────────────────
    print("  Calcul des indicateurs...")

    ema_trend  = df["close"].ewm(span=EMA_TREND_LEN,  adjust=False).mean().values
    ema_filter = df["close"].ewm(span=EMA_FILTER_LEN, adjust=False).mean().values

    prev_c = np.empty(n)
    prev_c[0] = close[0]
    prev_c[1:] = close[:-1]
    tr = np.maximum(high - low,
         np.maximum(np.abs(high - prev_c), np.abs(low - prev_c)))

    atr = np.zeros(n)
    atr[ATR_LEN - 1] = tr[:ATR_LEN].mean()
    for k in range(ATR_LEN, n):
        atr[k] = (atr[k - 1] * (ATR_LEN - 1) + tr[k]) / ATR_LEN

    WARMUP = EMA_TREND_LEN + 10  # bougies minimum avant de trader

    print(f"  {n:,} barres | warmup : {WARMUP} barres")
    print(f"  Simulation en cours...\n")

    # ── État global ───────────────────────────────────────────
    capital         = INITIAL_CAPITAL
    peak_capital    = INITIAL_CAPITAL
    strat_profit    = 0.0

    # Position
    in_pos        = False
    pos_dir       = None
    actual_entry  = 0.0
    stop_price    = 0.0
    target_price  = 0.0
    entry_bar_idx = 0
    entry_time    = None
    nb_contracts  = 1
    trail_active  = False
    trail_peak    = 0.0
    trail_stop_px = 0.0
    last_exit_bar = -1   # évite ré-entrée même bougie qu'une sortie décalée

    # État journalier
    cur_date          = None
    trades_today      = 0
    day_start_profit  = 0.0
    day_start_capital = INITIAL_CAPITAL
    or_high           = None
    or_low            = None
    or_ready          = False
    system_on         = True

    trades       = []
    equity_curve = []

    # ── Boucle principale ─────────────────────────────────────
    for i in range(WARMUP, n - 1):

        bar_date = df["date_p"].iloc[i]
        hm       = df["hm_p"].iloc[i]
        dow      = df["dow_p"].iloc[i]

        # ── Reset journalier ──────────────────────────────────
        if bar_date != cur_date:
            cur_date          = bar_date
            trades_today      = 0
            day_start_profit  = strat_profit
            day_start_capital = capital
            or_high           = None
            or_low            = None
            or_ready          = False
            system_on         = True

        # ── Sécurité perte journalière ───────────────────────
        daily_pnl = strat_profit - day_start_profit
        if daily_pnl <= MAX_DAILY_LOSS:
            system_on = False

        # ── Construction du range d'ouverture ────────────────
        if in_range(hm, OR_START, OR_END):
            if or_high is None or high[i] > or_high:
                or_high = high[i]
            if or_low is None or low[i] < or_low:
                or_low = low[i]

        if at_or_after(hm, OR_END) and or_high is not None:
            or_ready = True

        or_pts   = (or_high - or_low) if (or_high is not None and or_low is not None) else 0
        range_ok = or_ready and (MIN_OR_PTS <= or_pts <= MAX_OR_PTS)

        # ── Gestion de la position ────────────────────────────
        exit_triggered = False
        exit_price_raw = None
        exit_reason    = None

        if in_pos:
            bars_held = i - entry_bar_idx
            next_open = df["open"].iloc[i + 1]

            # 1. Mise à jour trailing stop (déjà actif)
            if trail_active:
                if pos_dir == "long":
                    trail_peak    = max(trail_peak, high[i])
                    trail_stop_px = trail_peak - TRAIL_PTS
                else:
                    trail_peak    = min(trail_peak, low[i])
                    trail_stop_px = trail_peak + TRAIL_PTS

            # 2. Stop courant
            if pos_dir == "long":
                cur_stop = trail_stop_px if trail_active else stop_price
            else:
                cur_stop = trail_stop_px if trail_active else stop_price

            # 3. Vérification intra-bougie stop / target
            if pos_dir == "long":
                stop_hit   = low[i]  <= cur_stop
                target_hit = high[i] >= target_price

                if stop_hit and target_hit:        # pessimiste : stop l'emporte
                    exit_price_raw = cur_stop
                    exit_reason    = "stop-trailing" if trail_active else "stop-loss"
                    exit_triggered = True
                elif stop_hit:
                    exit_price_raw = cur_stop
                    exit_reason    = "stop-trailing" if trail_active else "stop-loss"
                    exit_triggered = True
                elif target_hit:
                    exit_price_raw = target_price
                    exit_reason    = "target"
                    exit_triggered = True

            else:  # short
                stop_hit   = high[i] >= cur_stop
                target_hit = low[i]  <= target_price

                if stop_hit and target_hit:
                    exit_price_raw = cur_stop
                    exit_reason    = "stop-trailing" if trail_active else "stop-loss"
                    exit_triggered = True
                elif stop_hit:
                    exit_price_raw = cur_stop
                    exit_reason    = "stop-trailing" if trail_active else "stop-loss"
                    exit_triggered = True
                elif target_hit:
                    exit_price_raw = target_price
                    exit_reason    = "target"
                    exit_triggered = True

            # 4. Time stop (sortie à l'open suivant)
            if not exit_triggered and bars_held >= MAX_BARS_IN_TRADE:
                exit_price_raw = next_open
                exit_reason    = "time-stop"
                exit_triggered = True

            # 5. Flat-time (sortie à l'open suivant)
            if not exit_triggered and at_or_after(hm, T_FLAT):
                exit_price_raw = next_open
                exit_reason    = "flat-time"
                exit_triggered = True

            # 6. Enregistrement de la sortie
            if exit_triggered:
                if pos_dir == "long":
                    actual_exit = exit_price_raw - SLIP_OUT
                    pnl_net     = (actual_exit - actual_entry) * nb_contracts
                else:
                    actual_exit = exit_price_raw + SLIP_OUT
                    pnl_net     = (actual_entry - actual_exit) * nb_contracts

                costs     = (SPREAD + SLIP_IN + SLIP_OUT) * nb_contracts
                pnl_gross = pnl_net + costs  # avant déduction des coûts

                capital      += pnl_net
                strat_profit += pnl_net
                peak_capital  = max(peak_capital, capital)
                dd_now        = (peak_capital - capital) / peak_capital * 100

                exit_time = df["time_paris"].iloc[i + 1] \
                    if exit_reason in ("time-stop", "flat-time") \
                    else df["time_paris"].iloc[i]

                trades.append({
                    "date_entree":      str(entry_time),
                    "sens":             pos_dir,
                    "prix_entree":      round(actual_entry, 2),
                    "stop":             round(stop_price, 2),
                    "target":           round(target_price, 2),
                    "date_sortie":      str(exit_time),
                    "prix_sortie":      round(exit_price_raw, 2),
                    "raison_sortie":    exit_reason,
                    "resultat_brut":    round(pnl_gross, 2),
                    "cout_spread_slip": round(costs, 2),
                    "resultat_net":     round(pnl_net, 2),
                    "capital_apres":    round(capital, 2),
                    "drawdown_pct":     round(dd_now, 2),
                })

                in_pos       = False
                trail_active = False
                if exit_reason in ("time-stop", "flat-time"):
                    last_exit_bar = i + 1

            # 7. Activation trailing stop (effet sur bougie i+1)
            if not exit_triggered and USE_TRAILING and not trail_active:
                if pos_dir == "long" and close[i] >= actual_entry * (1 + TRAIL_START_PCT / 100):
                    trail_active  = True
                    trail_peak    = high[i]
                    trail_stop_px = trail_peak - TRAIL_PTS
                elif pos_dir == "short" and close[i] <= actual_entry * (1 - TRAIL_START_PCT / 100):
                    trail_active  = True
                    trail_peak    = low[i]
                    trail_stop_px = trail_peak + TRAIL_PTS

        # ── Signaux d'entrée ──────────────────────────────────
        if not in_pos and i > last_exit_bar:

            day_ok   = TRADE_DAYS.get(dow, False)
            time_ok  = in_range(hm, T_START, T_END)
            count_ok = trades_today < MAX_TRADES_PER_DAY
            flat_ok  = not at_or_after(hm, T_FLAT)
            vol_ok   = atr[i] >= MIN_ATR

            entry_ok = system_on and day_ok and time_ok and count_ok and vol_ok and range_ok and flat_ok

            if entry_ok:
                bar_range  = high[i] - low[i]
                body_size  = abs(close[i] - opn[i])
                body_ratio = body_size / bar_range if bar_range > 0 else 0

                # LONG
                trend_long = (
                    close[i] > ema_trend[i]
                    and ema_filter[i] > ema_trend[i]
                    and ema_trend[i] > ema_trend[i - 5]
                )
                confirm_long  = close[i] > opn[i] and body_ratio >= 0.50
                breakout_long = or_high is not None and close[i] > or_high + BREAK_BUFFER

                if trend_long and confirm_long and breakout_long:
                    next_open    = df["open"].iloc[i + 1]
                    nb_contracts = calc_contracts(capital, strat_profit)
                    actual_entry = next_open + SPREAD + SLIP_IN
                    stop_price   = actual_entry * (1 - STOP_PCT   / 100)
                    target_price = actual_entry * (1 + TARGET_PCT / 100)

                    in_pos        = True
                    pos_dir       = "long"
                    entry_bar_idx = i + 1
                    entry_time    = df["time_paris"].iloc[i + 1]
                    trail_active  = False
                    trail_peak    = actual_entry
                    trail_stop_px = 0.0
                    trades_today += 1

                # SHORT (AllowShort=False → ne se déclenchera jamais)
                elif ALLOW_SHORT:
                    trend_short    = (
                        close[i] < ema_trend[i]
                        and ema_filter[i] < ema_trend[i]
                        and ema_trend[i] < ema_trend[i - 5]
                    )
                    confirm_short  = close[i] < opn[i] and body_ratio >= 0.50
                    breakout_short = or_low is not None and close[i] < or_low - BREAK_BUFFER

                    if trend_short and confirm_short and breakout_short:
                        next_open    = df["open"].iloc[i + 1]
                        nb_contracts = calc_contracts(capital, strat_profit)
                        actual_entry = next_open - SPREAD - SLIP_IN
                        stop_price   = actual_entry * (1 + STOP_PCT   / 100)
                        target_price = actual_entry * (1 - TARGET_PCT / 100)

                        in_pos        = True
                        pos_dir       = "short"
                        entry_bar_idx = i + 1
                        entry_time    = df["time_paris"].iloc[i + 1]
                        trail_active  = False
                        trail_peak    = actual_entry
                        trail_stop_px = 0.0
                        trades_today += 1

        # ── Equity curve (capital réalisé + PnL latent) ───────
        if in_pos:
            if pos_dir == "long":
                unrealized = (close[i] - actual_entry) * nb_contracts
            else:
                unrealized = (actual_entry - close[i]) * nb_contracts
        else:
            unrealized = 0.0

        total_equity = capital + unrealized
        peak_eq      = max(peak_capital, total_equity)
        dd_eq        = (peak_eq - total_equity) / peak_eq * 100 if peak_eq > 0 else 0.0

        equity_curve.append({
            "date":      str(df["time_paris"].iloc[i]),
            "capital":   round(total_equity, 2),
            "drawdown":  round(dd_eq, 2),
        })

    # ── Fermeture forcée fin de données ──────────────────────
    if in_pos:
        exit_price_raw = close[-1]
        if pos_dir == "long":
            actual_exit = exit_price_raw - SLIP_OUT
            pnl_net     = (actual_exit - actual_entry) * nb_contracts
        else:
            actual_exit = exit_price_raw + SLIP_OUT
            pnl_net     = (actual_entry - actual_exit) * nb_contracts

        costs     = (SPREAD + SLIP_IN + SLIP_OUT) * nb_contracts
        pnl_gross = pnl_net + costs

        capital      += pnl_net
        strat_profit += pnl_net
        peak_capital  = max(peak_capital, capital)
        dd_now        = (peak_capital - capital) / peak_capital * 100

        trades.append({
            "date_entree":      str(entry_time),
            "sens":             pos_dir,
            "prix_entree":      round(actual_entry, 2),
            "stop":             round(stop_price, 2),
            "target":           round(target_price, 2),
            "date_sortie":      str(df["time_paris"].iloc[-1]),
            "prix_sortie":      round(exit_price_raw, 2),
            "raison_sortie":    "fin-donnees",
            "resultat_brut":    round(pnl_gross, 2),
            "cout_spread_slip": round(costs, 2),
            "resultat_net":     round(pnl_net, 2),
            "capital_apres":    round(capital, 2),
            "drawdown_pct":     round(dd_now, 2),
        })

    # ═══════════════════════════════════════════════════════════
    # STATISTIQUES
    # ═══════════════════════════════════════════════════════════

    if not trades:
        print("[AVERTISSEMENT] Aucun trade genere. Verifiez les donnees et les parametres.")
        return

    tdf = pd.DataFrame(trades)
    edf = pd.DataFrame(equity_curve)

    final_capital  = capital
    net_ret_pct    = (final_capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    net_ret_usd    = final_capital - INITIAL_CAPITAL

    n_trades = len(tdf)
    wins     = tdf[tdf["resultat_net"] > 0]
    losses   = tdf[tdf["resultat_net"] <= 0]
    n_win    = len(wins)
    n_loss   = len(losses)
    win_rate = n_win / n_trades * 100 if n_trades > 0 else 0

    avg_win  = wins["resultat_net"].mean()   if n_win   > 0 else 0.0
    avg_loss = losses["resultat_net"].mean() if n_loss  > 0 else 0.0
    payoff   = abs(avg_win / avg_loss)       if avg_loss != 0 else float("inf")

    gross_win    = wins["resultat_net"].sum()           if n_win  > 0 else 0.0
    gross_loss   = abs(losses["resultat_net"].sum())    if n_loss > 0 else 0.0
    profit_factor = gross_win / gross_loss              if gross_loss > 0 else float("inf")

    biggest_win  = tdf["resultat_net"].max()
    biggest_loss = tdf["resultat_net"].min()

    # Drawdown historique depuis equity curve
    eq_vals  = edf["capital"].values.astype(float)
    eq_peaks = np.maximum.accumulate(eq_vals)
    dd_arr   = np.where(eq_peaks > 0, (eq_peaks - eq_vals) / eq_peaks * 100, 0.0)
    max_dd_pct = dd_arr.max()
    max_dd_usd = (eq_peaks - eq_vals).max()

    # Max Daily Drawdown
    edf["date_only"] = pd.to_datetime(edf["date"], utc=True).dt.date
    max_daily_dd_pct = 0.0
    for _d, grp in edf.groupby("date_only")["capital"]:
        vals = grp.values.astype(float)
        pk   = vals[0]
        if pk > 0:
            dd_d = (pk - vals.min()) / pk * 100
            if dd_d > max_daily_dd_pct:
                max_daily_dd_pct = dd_d

    # Séquence maximale de pertes consécutives
    max_consec = cur_consec = 0
    for r in tdf["resultat_net"].values:
        if r <= 0:
            cur_consec += 1
            max_consec  = max(max_consec, cur_consec)
        else:
            cur_consec = 0

    # Stats annuelles
    tdf["year"] = pd.to_datetime(tdf["date_entree"], utc=True).dt.year
    yearly_pnl   = tdf.groupby("year")["resultat_net"].sum()
    yearly_count = tdf.groupby("year").size()

    # ═══════════════════════════════════════════════════════════
    # RAPPORT TERMINAL
    # ═══════════════════════════════════════════════════════════

    W = 30  # largeur colonne valeur

    def row(label, value):
        print(f"  {label:<28} {value}")

    print(f"\n{'=' * 58}")
    print("  RAPPORT FINAL — NASDAQ Perfect Revolution V1.1")
    print(f"{'=' * 58}")

    print(f"\n--- Capital ---")
    row("Capital initial",       f"${INITIAL_CAPITAL:>12,.2f}")
    row("Capital final",         f"${final_capital:>12,.2f}")
    row("Rendement net (%)",      f"{net_ret_pct:>+11.2f} %")
    row("Rendement net ($)",      f"${net_ret_usd:>+12,.2f}")

    print(f"\n--- Trades ---")
    row("Nombre total",          f"{n_trades:>13,}")
    row("Trades gagnants",       f"{n_win:>13,}")
    row("Trades perdants",       f"{n_loss:>13,}")
    row("Taux de reussite",      f"{win_rate:>11.1f} %")

    print(f"\n--- Qualite ---")
    row("Gain moyen",            f"${avg_win:>+12,.2f}")
    row("Perte moyenne",         f"${avg_loss:>+12,.2f}")
    row("Payoff ratio",          f"{payoff:>13.2f}")
    row("Profit Factor",         f"{profit_factor:>13.2f}")

    print(f"\n--- Risque ---")
    row("Max Drawdown (%)",      f"{max_dd_pct:>11.2f} %")
    row("Max Drawdown ($)",      f"${max_dd_usd:>12,.2f}")
    row("Max Daily Drawdown (%)",f"{max_daily_dd_pct:>11.2f} %")
    row("Plus gros gain",        f"${biggest_win:>+12,.2f}")
    row("Plus grosse perte",     f"${biggest_loss:>+12,.2f}")
    row("Pertes consecutives max",f"{max_consec:>13}")

    print(f"\n--- Par annee ---")
    print(f"  {'Annee':<8} {'Rendement ($)':>14} {'Nb trades':>10}")
    print(f"  {'-' * 34}")
    for yr in sorted(yearly_pnl.index):
        print(f"  {yr:<8} ${yearly_pnl[yr]:>+12,.2f} {yearly_count[yr]:>10,}")

    # ═══════════════════════════════════════════════════════════
    # EXPORT FICHIERS
    # ═══════════════════════════════════════════════════════════

    tdf.to_csv("trades.csv", index=False, encoding="utf-8")
    edf.to_csv("equity_curve.csv", index=False, encoding="utf-8")

    # Rapport Markdown
    md_lines = [
        "# Backtest — NASDAQ Perfect Revolution V1.1",
        "",
        "## Parametres",
        f"- Symbole : {SYMBOL}",
        f"- Timeframe : M3",
        f"- Capital initial : ${INITIAL_CAPITAL:,.2f}",
        f"- Spread stress-test : {SPREAD} pt",
        f"- Slippage entree / sortie : {SLIP_IN} / {SLIP_OUT} pt",
        f"- Shorts autorises : {ALLOW_SHORT}",
        f"- Compounding : {USE_COMPOUNDING}",
        "",
        "## Resultats globaux",
        "| Metrique | Valeur |",
        "|---|---|",
        f"| Capital initial | ${INITIAL_CAPITAL:,.2f} |",
        f"| Capital final | ${final_capital:,.2f} |",
        f"| Rendement net | {net_ret_pct:+.2f}% / ${net_ret_usd:+,.2f} |",
        f"| Nombre de trades | {n_trades} |",
        f"| Trades gagnants | {n_win} ({win_rate:.1f}%) |",
        f"| Trades perdants | {n_loss} |",
        f"| Gain moyen | ${avg_win:+,.2f} |",
        f"| Perte moyenne | ${avg_loss:+,.2f} |",
        f"| Payoff ratio | {payoff:.2f} |",
        f"| Profit Factor | {profit_factor:.2f} |",
        f"| Max Drawdown | {max_dd_pct:.2f}% / ${max_dd_usd:,.2f} |",
        f"| Max Daily Drawdown | {max_daily_dd_pct:.2f}% |",
        f"| Plus gros gain | ${biggest_win:+,.2f} |",
        f"| Plus grosse perte | ${biggest_loss:+,.2f} |",
        f"| Pertes consecutives max | {max_consec} |",
        "",
        "## Rendement par annee",
        "| Annee | Rendement ($) | Nb trades |",
        "|---|---|---|",
    ]
    for yr in sorted(yearly_pnl.index):
        md_lines.append(f"| {yr} | ${yearly_pnl[yr]:+,.2f} | {yearly_count[yr]} |")

    md_lines += [
        "",
        "## Hypotheses de traduction",
        "- Timestamps CSV : UTC -> converti en Europe/Paris pour les comparaisons horaires",
        "- Signaux evalues sur bougie fermee i, execution a l'open de la bougie i+1",
        "- Entree LONG : open[i+1] + spread(1pt) + slippage_entree(0.5pt)",
        "- Sortie : prix_sortie - slippage_sortie(0.5pt) pour les longs",
        "- Stop et target calcules depuis le prix d'entree reel (apres couts)",
        "- TrailPts = 650 = 650 unites de prix (confirme par commentaire '2.25% ~ 650 pts')",
        "- Trailing activee sur close[i], appliquee a partir de [i+1]",
        "- Time stop et flat-time : sortie au open[i+1] (comportement ProOrder standard)",
        "- AllowShort = False : longs uniquement",
        "- UseCompounding = False : 1 contrat fixe",
        "- Stop vs target meme bougie : pessimiste, stop l'emporte",
        "- StrategyProfit = P&L realise uniquement (pas de P&L latent dans le seuil journalier)",
    ]

    with open("rapport_backtest.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print(f"\n{SEP}")
    print(f"  Fichiers generes :")
    print(f"  - trades.csv          ({n_trades} trades)")
    print(f"  - equity_curve.csv    ({len(edf):,} points)")
    print(f"  - rapport_backtest.md")
    print(f"{SEP}\n")


if __name__ == "__main__":
    main()
