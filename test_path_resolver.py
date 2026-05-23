"""
test_path_resolver.py — Tests unitaires pour path_resolver.py

Vérifie :
  1. resolve_path(chemin relatif)  → absolu depuis BASE_DIR
  2. resolve_path(chemin absolu)   → inchangé
  3. to_relative_path(absolu)      → relatif POSIX
  4. to_relative_path(hors BASE)   → inchangé
  5. Aucun C:\\Users dans les valeurs renvoyées (portabilité)
  6. Aller-retour : to_relative + resolve = original

Usage :
    python test_path_resolver.py
"""

import sys
import os
from pathlib import Path

# -- Ajouter le répertoire courant au path -------------------------------------
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from path_resolver import BASE_DIR, resolve_path, to_relative_path

PASS = "✅"
FAIL = "❌"
results = []

def check(label: str, condition: bool, details: str = ""):
    status = PASS if condition else FAIL
    results.append((status, label, details))
    print(f"  {status}  {label}" + (f"  →  {details}" if details else ""))
    return condition


print(f"\n{'-'*60}")
print(f"  test_path_resolver  —  BASE_DIR = {BASE_DIR}")
print(f"{'-'*60}\n")

# -----------------------------------------------------------------------------
# Test 1 : resolve_path sur chemin relatif
# -----------------------------------------------------------------------------
p1 = resolve_path("nasdaq_3m.csv")
check(
    "resolve_path('nasdaq_3m.csv') → absolu",
    p1.is_absolute(),
    str(p1),
)
check(
    "resolve_path('nasdaq_3m.csv') → sous BASE_DIR",
    str(p1).startswith(str(BASE_DIR)),
    f"BASE_DIR={BASE_DIR}",
)

# -----------------------------------------------------------------------------
# Test 2 : resolve_path sur chemin relatif avec sous-dossier
# -----------------------------------------------------------------------------
p2 = resolve_path("strategies/perfect_revolution_v1.py")
check(
    "resolve_path('strategies/perfect_revolution_v1.py') → absolu",
    p2.is_absolute(),
    str(p2),
)
check(
    "resolve_path contient 'strategies'",
    "strategies" in str(p2),
    str(p2),
)

# -----------------------------------------------------------------------------
# Test 3 : resolve_path sur chemin déjà absolu → inchangé
# -----------------------------------------------------------------------------
abs_path = str(BASE_DIR / "nasdaq_3m.csv")
p3 = resolve_path(abs_path)
check(
    "resolve_path(absolu) → Path absolu",
    p3.is_absolute(),
    str(p3),
)
check(
    "resolve_path(absolu) == original",
    str(p3) == str(Path(abs_path)),
    str(p3),
)

# -----------------------------------------------------------------------------
# Test 4 : to_relative_path — absolu sous BASE_DIR → relatif POSIX
# -----------------------------------------------------------------------------
abs_data = str(BASE_DIR / "nasdaq_3m.csv")
rel4 = to_relative_path(abs_data)
check(
    "to_relative_path(nasdaq_3m.csv absolu) → 'nasdaq_3m.csv'",
    rel4 == "nasdaq_3m.csv",
    repr(rel4),
)
check(
    "to_relative_path → pas de backslash",
    "\\" not in rel4,
    repr(rel4),
)

abs_strat = str(BASE_DIR / "strategies" / "perfect_revolution_v1.py")
rel5 = to_relative_path(abs_strat)
check(
    "to_relative_path(strategies/... absolu) → 'strategies/perfect_revolution_v1.py'",
    rel5 == "strategies/perfect_revolution_v1.py",
    repr(rel5),
)

# -----------------------------------------------------------------------------
# Test 5 : to_relative_path — chemin HORS BASE_DIR → inchangé
# -----------------------------------------------------------------------------
outside = "C:\\Windows\\System32\\cmd.exe" if os.name == "nt" else "/usr/bin/python3"
rel6 = to_relative_path(outside)
check(
    "to_relative_path(hors BASE_DIR) → inchangé",
    rel6 == str(outside),
    repr(rel6),
)

# -----------------------------------------------------------------------------
# Test 6 : Aller-retour to_relative → resolve == original
# -----------------------------------------------------------------------------
original = BASE_DIR / "nasdaq_3m.csv"
rel7 = to_relative_path(original)
restored = resolve_path(rel7)
check(
    "aller-retour to_relative + resolve == original",
    restored.resolve() == original.resolve(),
    f"{rel7} → {restored}",
)

# -----------------------------------------------------------------------------
# Test 7 : Aucun chemin Windows dur dans les valeurs POSIX
# -----------------------------------------------------------------------------
rel_data  = to_relative_path(BASE_DIR / "nasdaq_3m.csv")
rel_strat = to_relative_path(BASE_DIR / "strategies" / "perfect_revolution_v1.py")

check(
    "to_relative_path(data) → pas de 'C:\\\\Users'",
    "C:\\Users" not in rel_data and "C:/Users" not in rel_data,
    repr(rel_data),
)
check(
    "to_relative_path(strat) → pas de 'C:\\\\Users'",
    "C:\\Users" not in rel_strat and "C:/Users" not in rel_strat,
    repr(rel_strat),
)

# -----------------------------------------------------------------------------
# Résumé
# -----------------------------------------------------------------------------
n_pass = sum(1 for r in results if r[0] == PASS)
n_fail = sum(1 for r in results if r[0] == FAIL)

print(f"\n{'-'*60}")
print(f"  Résultat : {n_pass}/{len(results)} tests OK"
      + (f"  —  {n_fail} ÉCHEC(S)" if n_fail else "  —  TOUT VERT ✅"))
print(f"{'-'*60}\n")

sys.exit(0 if n_fail == 0 else 1)
