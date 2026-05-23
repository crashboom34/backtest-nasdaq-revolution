import MetaTrader5 as mt5
import pandas as pd
import os
import sys

SYMBOL     = "US100"
TIMEFRAME  = mt5.TIMEFRAME_M3
N_CANDLES  = 1_000_000
OUTPUT     = "nasdaq_3m.csv"
SEP        = "-" * 50

def section(title):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)

# ── 1. Connexion ──────────────────────────────────
section("1. CONNEXION MT5")

if not mt5.initialize():
    print(f"[ERREUR] Connexion impossible : {mt5.last_error()}")
    sys.exit(1)
print("[OK] Terminal MT5 connecte.")

term = mt5.terminal_info()
if not term.connected:
    print("[ERREUR] Le terminal n'est pas connecte au broker.")
    mt5.shutdown()
    sys.exit(1)
print("[OK] Terminal connecte au broker.")

# ── 2. Verification du symbole ────────────────────
section("2. VERIFICATION DU SYMBOLE")

if mt5.symbol_info(SYMBOL) is None:
    print(f"[ERREUR] Symbole '{SYMBOL}' introuvable.")
    mt5.shutdown()
    sys.exit(1)
print(f"[OK] Symbole '{SYMBOL}' disponible.")

if not mt5.symbol_select(SYMBOL, True):
    print(f"[ERREUR] Impossible de selectionner '{SYMBOL}' : {mt5.last_error()}")
    mt5.shutdown()
    sys.exit(1)
print(f"[OK] '{SYMBOL}' selectionne dans le Market Watch.")

# ── 3. Telechargement des bougies ─────────────────
section("3. TELECHARGEMENT DES DONNEES")

print(f"  Demande : {N_CANDLES:,} bougies M3 sur {SYMBOL}...")
rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, N_CANDLES)

if rates is None or len(rates) == 0:
    print(f"[ERREUR] Aucune donnee recue : {mt5.last_error()}")
    mt5.shutdown()
    sys.exit(1)

n_received = len(rates)
print(f"  Recu    : {n_received:,} bougies.")
mt5.shutdown()

# ── 4. Construction du DataFrame ─────────────────
section("4. TRAITEMENT DES DONNEES")

df = pd.DataFrame(rates)
df["time"] = pd.to_datetime(df["time"], unit="s")
df = df[["time", "open", "high", "low", "close", "tick_volume", "spread"]]
df = df.drop_duplicates(subset="time")
df = df.sort_values("time").reset_index(drop=True)

print(f"  Doublons supprimes. Lignes finales : {len(df):,}")

# ── 5. Sauvegarde CSV ─────────────────────────────
section("5. SAUVEGARDE")

df.to_csv(OUTPUT, index=False)
file_size_kb = os.path.getsize(OUTPUT) / 1024
print(f"  Fichier sauvegarde : {OUTPUT}")
print(f"  Taille             : {file_size_kb:,.1f} Ko")

# ── 6. Rapport final ──────────────────────────────
section("6. RAPPORT")

first_date  = df["time"].iloc[0]
last_date   = df["time"].iloc[-1]
n_days      = (last_date - first_date).days
n_missing   = df[["open", "high", "low", "close"]].isnull().sum().sum()

spread_ok = df["spread"].notna().any() and df["spread"].sum() > 0
spread_str = f"{df['spread'].mean():.1f} points" if spread_ok else "non disponible"

print(f"  Bougies telechargees : {len(df):,}")
print(f"  Premiere date        : {first_date}")
print(f"  Derniere date        : {last_date}")
print(f"  Periode couverte     : {n_days} jours (~{n_days/365:.1f} ans)")
print(f"  Valeurs manquantes   : {n_missing}")
print(f"  Spread moyen         : {spread_str}")
print(f"  Taille CSV           : {file_size_kb:,.1f} Ko")

if len(df) < 500_000:
    print()
    print("  [AVERTISSEMENT] Moins de 500 000 bougies obtenues.")
    print("  Causes possibles :")
    print("    - MT5 n'a pas encore charge suffisamment d'historique.")
    print("    - Le broker Admirals ne fournit pas autant d'historique M3.")
    print("  Solution : dans MT5, allez dans Outils > Options > Graphiques,")
    print("    augmentez 'Barres maximum dans l'historique' a 10 000 000,")
    print("    puis rouvrez le graphique US100 M3 et re-executez ce script.")
else:
    print()
    print("  [OK] Volume d'historique suffisant pour un backtest robuste.")
