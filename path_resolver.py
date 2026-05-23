"""
path_resolver.py — Gestion des chemins portables entre Windows et Linux.

Objectif
--------
Permettre de stocker des chemins *relatifs* dans les fichiers JSON de config
(ex: "strategies/perfect_revolution_v1.py", "nasdaq_3m.csv") et de les
résoudre en chemins *absolus* au moment où le subprocess en a besoin.

Cela garantit que les JSON générés sur Windows peuvent être relus sur un
serveur Linux sans modification.

Variable d'environnement
------------------------
    BACKTEST_BASE_DIR : chemin absolu du dossier racine du projet.
    Si non défini : dossier contenant ce fichier (comportement actuel).

Exemple serveur Linux
---------------------
    export BACKTEST_BASE_DIR=/app
    python optimizer_process.py my_run my_run.config.json

Fonctions publiques
-------------------
    BASE_DIR          : Path — répertoire de base résolu
    to_relative_path  : convertit un chemin absolu → relatif (pour stocker dans JSON)
    resolve_path      : convertit un chemin relatif → absolu (pour utiliser dans le code)
"""

import os
from pathlib import Path
from typing import Union

# ══════════════════════════════════════════════════════════════════════════════
# RÉPERTOIRE DE BASE DU PROJET
# ══════════════════════════════════════════════════════════════════════════════

_env_base = os.environ.get("BACKTEST_BASE_DIR", "")

if _env_base:
    # Serveur Linux : chemin configuré explicitement via variable d'environnement
    BASE_DIR: Path = Path(_env_base).resolve()
else:
    # Local Windows : dossier contenant ce fichier (détection automatique)
    BASE_DIR: Path = Path(__file__).resolve().parent


# ══════════════════════════════════════════════════════════════════════════════
# FONCTIONS DE CONVERSION
# ══════════════════════════════════════════════════════════════════════════════

def to_relative_path(path: Union[str, Path]) -> str:
    """
    Convertit un chemin absolu en chemin relatif par rapport à BASE_DIR.

    Utilise des '/' comme séparateur (format POSIX) pour être
    identique sur Windows et Linux.

    Comportement :
    - Chemin sous BASE_DIR  → chemin relatif avec '/'
                              Ex: "strategies/perfect_revolution_v1.py"
    - Chemin hors BASE_DIR  → chemin original sous forme str (non modifié)

    Utilisation typique : stocker des chemins dans les JSON de config.

    Exemple
    -------
    >>> to_relative_path("C:/Users/Mira/Desktop/Backtest/nasdaq_3m.csv")
    'nasdaq_3m.csv'
    >>> to_relative_path("C:/Users/Mira/Desktop/Backtest/strategies/perfect_revolution_v1.py")
    'strategies/perfect_revolution_v1.py'
    """
    try:
        rel = Path(path).resolve().relative_to(BASE_DIR)
        return rel.as_posix()   # forward slashes : portable Windows + Linux
    except ValueError:
        # Le chemin n'est pas sous BASE_DIR — impossible de rendre relatif
        return str(path)


def resolve_path(path: Union[str, Path]) -> Path:
    """
    Résout un chemin en chemin absolu utilisable par le code.

    Règles (dans l'ordre) :
    1. Chemin déjà absolu                → retourné tel quel (Path)
    2. Chemin relatif (ex: "data/x.csv") → résolu depuis BASE_DIR

    Utilisation typique : lire les chemins depuis un JSON de config
    avant de les passer à load_data() ou importlib.

    Exemple
    -------
    >>> resolve_path("nasdaq_3m.csv")
    PosixPath('/app/nasdaq_3m.csv')           # Linux
    WindowsPath('C:/Users/.../nasdaq_3m.csv') # Windows

    >>> resolve_path("strategies/perfect_revolution_v1.py")
    PosixPath('/app/strategies/perfect_revolution_v1.py')
    """
    p = Path(path)
    if p.is_absolute():
        return p
    return (BASE_DIR / p).resolve()
