import MetaTrader5 as mt5
import sys

SYMBOL = "US100"
SEP = "-" * 45

def section(title):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)

# ── 1. Connexion ──────────────────────────────────
section("1. CONNEXION AU TERMINAL MT5")

if not mt5.initialize():
    print(f"[ERREUR] Impossible de se connecter au terminal MT5.")
    print(f"         Code erreur : {mt5.last_error()}")
    print("         Assurez-vous que MetaTrader 5 est ouvert et connecté.")
    sys.exit(1)

print("[OK] Connexion établie avec le terminal MetaTrader 5.")

# ── 2. Informations du compte ─────────────────────
section("2. INFORMATIONS DU COMPTE DÉMO")

account = mt5.account_info()
if account is None:
    print(f"[ERREUR] Impossible de récupérer les infos du compte : {mt5.last_error()}")
    mt5.shutdown()
    sys.exit(1)

print(f"  Numéro de compte   : {account.login}")
print(f"  Nom                : {account.name}")
print(f"  Broker             : {account.company}")
print(f"  Serveur            : {account.server}")
print(f"  Type de compte     : {'Démo' if account.trade_mode == 0 else 'Réel'}")
print(f"  Devise             : {account.currency}")
print(f"  Balance            : {account.balance:,.2f} {account.currency}")
print(f"  Equity             : {account.equity:,.2f} {account.currency}")
print(f"  Levier             : 1:{account.leverage}")

# ── 3. Vérification du symbole ────────────────────
section(f"3. VÉRIFICATION DU SYMBOLE {SYMBOL}")

symbol_info = mt5.symbol_info(SYMBOL)
if symbol_info is None:
    print(f"[ERREUR] Symbole '{SYMBOL}' introuvable.")
    print("         Vérifiez l'orthographe ou cherchez-le dans le Market Watch.")
    mt5.shutdown()
    sys.exit(1)

print(f"[OK] Symbole '{SYMBOL}' trouvé.")

# ── 4. Sélection dans le Market Watch ────────────
section(f"4. SÉLECTION DANS LE MARKET WATCH")

if not mt5.symbol_select(SYMBOL, True):
    print(f"[ERREUR] Impossible de sélectionner '{SYMBOL}' : {mt5.last_error()}")
    mt5.shutdown()
    sys.exit(1)

print(f"[OK] '{SYMBOL}' sélectionné et visible dans le Market Watch.")

# ── 5. Informations détaillées sur US100 ─────────
section(f"5. INFORMATIONS DÉTAILLÉES SUR {SYMBOL}")

info = mt5.symbol_info(SYMBOL)
tick = mt5.symbol_info_tick(SYMBOL)

spread = round((info.ask - info.bid) / info.point) if info.point > 0 else "N/A"

print(f"  Nom exact          : {info.name}")
print(f"  Description        : {info.description}")
print(f"  Bid                : {info.bid}")
print(f"  Ask                : {info.ask}")
print(f"  Spread actuel      : {spread} points")
print(f"  Digits             : {info.digits}")
print(f"  Point              : {info.point}")
print(f"  Taille du contrat  : {info.trade_contract_size}")
print(f"  Devise de profit   : {info.currency_profit}")

# ── Fin ───────────────────────────────────────────
section("RÉSULTAT FINAL")
print("[OK] Tous les contrôles sont passés avec succès.")
print(f"     L'environnement est prêt pour le backtest sur {SYMBOL} M3.\n")

mt5.shutdown()
