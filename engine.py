"""
Moteur de backtest générique.
Gère l'exécution des trades, les coûts, le P&L et les statistiques.
La logique de signal est déléguée à l'objet strategy.
"""

import pandas as pd
import numpy as np
from zoneinfo import ZoneInfo
from scoring import compute_equity_r_squared

PARIS = ZoneInfo("Europe/Paris")


def _add_market_time_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les colonnes dérivées (fuseau Paris) consommées par run_backtest().

    Factorisé depuis load_data() pour être réutilisé par load_data_from_source() sans dupliquer
    la logique de fuseau horaire. load_data() produit exactement le même résultat qu'avant
    cette extraction (voir tests/test_engine_load_data_from_source.py).
    """
    df = df.copy()
    df["time_paris"] = df["time"].dt.tz_localize("UTC").dt.tz_convert(PARIS)
    df["date_p"] = df["time_paris"].dt.date
    df["h_p"]    = df["time_paris"].dt.hour
    df["m_p"]    = df["time_paris"].dt.minute
    df["dow_p"]  = df["time_paris"].dt.dayofweek
    df["hm_p"]   = list(zip(df["h_p"], df["m_p"]))
    return df


def load_data(csv_file: str) -> pd.DataFrame:
    df = pd.read_csv(csv_file, parse_dates=["time"])
    return _add_market_time_columns(df)


def load_data_from_source(source, asset: str, timeframe: str) -> pd.DataFrame:
    """Charge un actif/timeframe via un market_data.ports.MarketDataSource (ex.
    market_data.adapters.local_csv.LocalCsvMarketDataSource) plutôt que par un chemin CSV
    direct.

    Produit exactement les mêmes colonnes dérivées que load_data() — voir le test
    d'équivalence dans tests/test_engine_load_data_from_source.py. N'est appelé nulle part
    dans app.py ni run_job.py à cette étape : c'est une capacité additive, le chemin CSV
    existant (load_data) reste inchangé et continue d'être celui réellement utilisé.

    Lève ValueError si la source ne peut pas fournir les données (message explicite du port,
    pas d'exception technique opaque).
    """
    result = source.load(asset, timeframe)
    if not result.ok or result.dataframe is None:
        raise ValueError(f"Impossible de charger {asset}/{timeframe} : {result.message}")

    df = result.dataframe.copy()
    df["time"] = pd.to_datetime(df["time"])
    return _add_market_time_columns(df)


def run_backtest(
    df: pd.DataFrame,
    strategy,
    params: dict,
    initial_capital: float = 10_000.0,
    spread: float = 1.0,
    slip_in: float = 0.5,
    slip_out: float = 0.5,
    progress_cb=None,
    start_date=None,
    end_date=None,
) -> tuple:
    """
    Paramètres
    ----------
    df             : DataFrame chargé via load_data()
    strategy       : instance d'une classe Strategy (prepare + on_bar + reset)
    params         : dict des paramètres spécifiques à la stratégie
    initial_capital: capital de départ
    spread         : spread fixe en unités de prix
    slip_in/out    : slippage entrée/sortie
    progress_cb    : callable(pct) pour barre de progression (optionnel)

    Retourne
    --------
    (trades_df, equity_df, stats_dict)
    """
    # Filtrage optionnel par dates (pour le split train/test de l'optimisateur)
    if start_date is not None:
        df = df[df["time_paris"] >= pd.Timestamp(start_date, tz="Europe/Paris")]
    if end_date is not None:
        df = df[df["time_paris"] <= pd.Timestamp(end_date, tz="Europe/Paris")]
    df = df.reset_index(drop=True)

    # reset() avant prepare() : l'état journalier est purgé, puis prepare()
    # peuple les caches numpy. Les caches survivent ensuite à toute la run.
    strategy.reset()
    # deep=False : nouveau DataFrame mais blocs partagés. prepare() ne fait
    # qu'AJOUTER des colonnes (jamais de mutation in-place), donc safe.
    df = strategy.prepare(df.copy(deep=False), params)
    n  = len(df)

    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values
    opn   = df["open"].values
    # Pré-extraction de la colonne time : str() est lent en hot loop
    times_str = df["time_paris"].astype(str).values

    capital      = initial_capital
    peak_capital = initial_capital
    strat_profit = 0.0

    # État position
    in_pos             = False
    pos_dir            = None
    actual_entry       = 0.0
    stop_price         = 0.0
    target_price       = 0.0
    entry_bar_idx      = 0
    entry_time         = None
    nb_contracts       = 1
    trail_active       = False
    trail_peak         = 0.0
    trail_stop_px      = 0.0
    use_trailing_param = False
    trail_start_pct    = 0.0
    trail_pts_val      = 0.0
    max_bars_param     = 9999
    last_exit_bar      = -1

    trades       = []
    equity_curve = []

    warmup = getattr(strategy, "WARMUP", 130)

    report_every = max(1, n // 100)

    for i in range(warmup, n - 1):

        if progress_cb and i % report_every == 0:
            progress_cb((i - warmup) / (n - warmup))

        context = {
            "in_pos":          in_pos,
            "position":        {
                "direction":    pos_dir,
                "actual_entry": actual_entry,
                "stop_price":   stop_price,
                "target_price": target_price,
                "trail_active": trail_active,
                "entry_bar_idx":entry_bar_idx,
                "bars_held":    i - entry_bar_idx if in_pos else 0,
                "nb_contracts": nb_contracts,
            } if in_pos else None,
            "capital":         capital,
            "strat_profit":    strat_profit,
            "initial_capital": initial_capital,
            "last_exit_bar":   last_exit_bar,
        }

        exit_triggered = False
        exit_price_raw = None
        exit_reason    = None

        # ── Gestion de la position ────────────────────────────
        if in_pos:
            bars_held = i - entry_bar_idx
            next_open = opn[i + 1]

            # Mise à jour trailing stop
            if use_trailing_param and trail_active:
                if pos_dir == "long":
                    trail_peak    = max(trail_peak, high[i])
                    trail_stop_px = trail_peak - trail_pts_val
                else:
                    trail_peak    = min(trail_peak, low[i])
                    trail_stop_px = trail_peak + trail_pts_val

            cur_stop = trail_stop_px if trail_active else stop_price

            # Vérification intra-bougie stop / target
            if pos_dir == "long":
                stop_hit   = low[i]  <= cur_stop
                target_hit = high[i] >= target_price
            else:
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

            # Time stop
            if not exit_triggered and bars_held >= max_bars_param:
                exit_price_raw = next_open
                exit_reason    = "time-stop"
                exit_triggered = True

            # Sortie personnalisée de la stratégie (flat-time, etc.)
            if not exit_triggered:
                sig = strategy.on_bar(i, df, context, params)
                if sig and sig.get("action") == "exit":
                    at = sig.get("at", "next_open")
                    exit_price_raw = next_open if at == "next_open" else close[i]
                    exit_reason    = sig.get("reason", "strategy-exit")
                    exit_triggered = True

            # Enregistrement de la sortie
            if exit_triggered:
                if pos_dir == "long":
                    actual_exit = exit_price_raw - slip_out
                    pnl_net     = (actual_exit - actual_entry) * nb_contracts
                else:
                    actual_exit = exit_price_raw + slip_out
                    pnl_net     = (actual_entry - actual_exit) * nb_contracts

                costs     = (spread + slip_in + slip_out) * nb_contracts
                pnl_gross = pnl_net + costs

                capital      += pnl_net
                strat_profit += pnl_net
                peak_capital  = max(peak_capital, capital)
                dd_now        = (peak_capital - capital) / peak_capital * 100

                exit_t = (
                    df["time_paris"].iloc[i + 1]
                    if exit_reason in ("time-stop", "flat-time")
                    else df["time_paris"].iloc[i]
                )

                trades.append({
                    "date_entree":      str(entry_time),
                    "sens":             pos_dir,
                    "prix_entree":      round(actual_entry, 2),
                    "stop":             round(stop_price, 2),
                    "target":           round(target_price, 2),
                    "date_sortie":      str(exit_t),
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

            # Activation trailing (effet bougie suivante)
            if not exit_triggered and use_trailing_param and not trail_active:
                if pos_dir == "long" and close[i] >= actual_entry * (1 + trail_start_pct / 100):
                    trail_active  = True
                    trail_peak    = high[i]
                    trail_stop_px = trail_peak - trail_pts_val
                elif pos_dir == "short" and close[i] <= actual_entry * (1 - trail_start_pct / 100):
                    trail_active  = True
                    trail_peak    = low[i]
                    trail_stop_px = trail_peak + trail_pts_val

        # ── Signaux d'entrée ──────────────────────────────────
        if not in_pos and i > last_exit_bar:
            # Si une sortie intra-barre vient d'avoir lieu, le context construit
            # en début de bougie a encore in_pos=True. La stratégie renverrait
            # alors None (early-return "in_pos"). On rafraîchit avant l'appel.
            if context["in_pos"]:
                context = {**context, "in_pos": False, "position": None}
            sig = strategy.on_bar(i, df, context, params)
            if sig and sig.get("action") == "enter":
                direction  = sig["direction"]
                next_open  = opn[i + 1]
                nb         = sig.get("nb_contracts", 1)

                if direction == "long":
                    ae = next_open + spread + slip_in
                    sp = ae * (1 - sig["stop_pct"]   / 100)
                    tp = ae * (1 + sig["target_pct"] / 100)
                else:
                    ae = next_open - spread - slip_in
                    sp = ae * (1 + sig["stop_pct"]   / 100)
                    tp = ae * (1 - sig["target_pct"] / 100)

                actual_entry       = ae
                stop_price         = sp
                target_price       = tp
                pos_dir            = direction
                entry_bar_idx      = i + 1
                entry_time         = df["time_paris"].iloc[i + 1]
                nb_contracts       = nb
                in_pos             = True
                trail_active       = False
                trail_peak         = ae
                trail_stop_px      = 0.0
                use_trailing_param = sig.get("use_trailing", False)
                trail_start_pct    = sig.get("trail_start_pct", 2.60)
                trail_pts_val      = sig.get("trail_pts", 650.0)
                max_bars_param     = sig.get("max_bars", 9999)

        # ── Equity curve ──────────────────────────────────────
        if in_pos:
            unr = (
                (close[i] - actual_entry) * nb_contracts if pos_dir == "long"
                else (actual_entry - close[i]) * nb_contracts
            )
        else:
            unr = 0.0

        total_eq = capital + unr
        pk_eq    = max(peak_capital, total_eq)
        dd_eq    = (pk_eq - total_eq) / pk_eq * 100 if pk_eq > 0 else 0.0

        equity_curve.append({
            "date":      times_str[i],
            "capital":   round(total_eq, 2),
            "drawdown":  round(dd_eq, 2),
        })

    # ── Fermeture forcée ──────────────────────────────────────
    if in_pos:
        ep   = close[-1]
        ae2  = ep - slip_out if pos_dir == "long" else ep + slip_out
        pnl  = (ae2 - actual_entry) * nb_contracts if pos_dir == "long" else (actual_entry - ae2) * nb_contracts
        costs = (spread + slip_in + slip_out) * nb_contracts
        capital      += pnl
        strat_profit += pnl
        peak_capital  = max(peak_capital, capital)
        trades.append({
            "date_entree":      str(entry_time),
            "sens":             pos_dir,
            "prix_entree":      round(actual_entry, 2),
            "stop":             round(stop_price, 2),
            "target":           round(target_price, 2),
            "date_sortie":      str(df["time_paris"].iloc[-1]),
            "prix_sortie":      round(ep, 2),
            "raison_sortie":    "fin-donnees",
            "resultat_brut":    round(pnl + costs, 2),
            "cout_spread_slip": round(costs, 2),
            "resultat_net":     round(pnl, 2),
            "capital_apres":    round(capital, 2),
            "drawdown_pct":     round((peak_capital - capital) / peak_capital * 100, 2),
        })

    if progress_cb:
        progress_cb(1.0)

    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    equity_df = pd.DataFrame(equity_curve)
    stats     = _compute_stats(trades_df, equity_df, initial_capital, capital)

    return trades_df, equity_df, stats


def _compute_stats(tdf, edf, initial_capital, final_capital):
    if tdf.empty:
        return {"n_trades": 0}

    net_ret_pct = (final_capital - initial_capital) / initial_capital * 100
    net_ret_usd = final_capital - initial_capital

    n_trades = len(tdf)
    wins     = tdf[tdf["resultat_net"] > 0]
    losses   = tdf[tdf["resultat_net"] <= 0]
    n_win    = len(wins)
    n_loss   = len(losses)
    win_rate = n_win / n_trades * 100 if n_trades > 0 else 0

    avg_win   = wins["resultat_net"].mean()   if n_win  > 0 else 0.0
    avg_loss  = losses["resultat_net"].mean() if n_loss > 0 else 0.0
    payoff    = abs(avg_win / avg_loss)       if avg_loss != 0 else float("inf")

    gross_win    = wins["resultat_net"].sum()           if n_win  > 0 else 0.0
    gross_loss   = abs(losses["resultat_net"].sum())    if n_loss > 0 else 0.0
    profit_factor = gross_win / gross_loss              if gross_loss > 0 else float("inf")

    # Drawdown depuis equity curve
    eq_vals  = edf["capital"].values.astype(float)
    eq_peaks = np.maximum.accumulate(eq_vals)
    dd_arr   = np.where(eq_peaks > 0, (eq_peaks - eq_vals) / eq_peaks * 100, 0.0)
    max_dd_pct = float(dd_arr.max())
    max_dd_usd = float((eq_peaks - eq_vals).max())

    # Runup max
    eq_troughs = np.minimum.accumulate(eq_vals)
    max_runup  = float((eq_vals - eq_troughs).max())

    # Max Daily Drawdown
    edf2 = edf.copy()
    edf2["date_only"] = pd.to_datetime(edf2["date"], utc=True).dt.date
    max_daily_dd = 0.0
    for _d, grp in edf2.groupby("date_only")["capital"]:
        vals = grp.values.astype(float)
        pk   = vals[0]
        if pk > 0:
            dd_d = (pk - vals.min()) / pk * 100
            if dd_d > max_daily_dd:
                max_daily_dd = dd_d

    # Pertes consécutives
    max_consec = cur_consec = 0
    for r in tdf["resultat_net"].values:
        if r <= 0:
            cur_consec += 1
            max_consec  = max(max_consec, cur_consec)
        else:
            cur_consec = 0

    # Temps dans le marché
    tdf2 = tdf.copy()
    tdf2["te"] = pd.to_datetime(tdf2["date_entree"], utc=True)
    tdf2["tx"] = pd.to_datetime(tdf2["date_sortie"], utc=True)
    bars_in    = ((tdf2["tx"] - tdf2["te"]).dt.total_seconds() / 180).clip(lower=1).sum()
    time_in_market = bars_in / len(edf) * 100 if len(edf) > 0 else 0.0

    # Stats annuelles
    tdf2["year"] = tdf2["te"].dt.year
    yearly_pnl   = tdf2.groupby("year")["resultat_net"].sum().to_dict()
    yearly_count = tdf2.groupby("year").size().to_dict()

    # Stats par jour de semaine
    dow_map = {0: "Lun", 1: "Mar", 2: "Mer", 3: "Jeu", 4: "Ven", 5: "Sam", 6: "Dim"}
    tdf2["dow_num"] = tdf2["te"].dt.dayofweek
    tdf2["dow"]     = tdf2["dow_num"].map(dow_map)
    dow_order       = ["Lun", "Mar", "Mer", "Jeu", "Ven"]
    dow_pnl         = tdf2.groupby("dow")["resultat_net"].sum().reindex(dow_order, fill_value=0).to_dict()
    dow_count       = tdf2.groupby("dow").size().reindex(dow_order, fill_value=0).to_dict()

    # Moyenne trades/jour
    dates_traded       = tdf2["te"].dt.date.nunique()
    avg_trades_per_day = n_trades / dates_traded if dates_traded > 0 else 0.0

    # Régularité de l'equity curve (R² de la régression linéaire)
    equity_r_squared = compute_equity_r_squared(eq_vals.tolist())

    return {
        "initial_capital":   initial_capital,
        "final_capital":     final_capital,
        "net_ret_pct":       net_ret_pct,
        "net_ret_usd":       net_ret_usd,
        "n_trades":          n_trades,
        "n_win":             n_win,
        "n_loss":            n_loss,
        "win_rate":          win_rate,
        "avg_win":           avg_win,
        "avg_loss":          avg_loss,
        "payoff":            payoff,
        "profit_factor":     profit_factor,
        "gross_win":         gross_win,
        "gross_loss":        gross_loss,
        "max_dd_pct":        max_dd_pct,
        "max_dd_usd":        max_dd_usd,
        "max_runup":         max_runup,
        "max_daily_dd":      max_daily_dd,
        "max_consec_loss":   max_consec,
        "biggest_win":       float(tdf["resultat_net"].max()),
        "biggest_loss":      float(tdf["resultat_net"].min()),
        "time_in_market":    time_in_market,
        "avg_trades_per_day":avg_trades_per_day,
        "yearly_pnl":        yearly_pnl,
        "yearly_count":      yearly_count,
        "dow_pnl":           dow_pnl,
        "dow_count":         dow_count,
        "equity_r_squared":  equity_r_squared,
    }
