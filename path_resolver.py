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
    BASE_DIR                : Path — répertoire de base résolu
    to_relative_path        : convertit un chemin absolu → relatif (pour stocker dans JSON)
    resolve_path            : convertit un chemin relatif → absolu (pour utiliser dans le code)
    list_available_assets   : liste les actifs détectés dans data/
    list_available_timeframes : liste les timeframes d'un actif
    resolve_data_csv        : trouve le CSV data/{asset}/{timeframe}/ ou le legacy nasdaq_3m.csv
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

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


DATA_DIR_NAME = "data"
DEFAULT_ASSET = "NASDAQ"
DEFAULT_TIMEFRAME = "M3"
LEGACY_DATASETS = {
    (DEFAULT_ASSET, DEFAULT_TIMEFRAME): "nasdaq_3m.csv",
}


@dataclass(frozen=True)
class DataFileResolution:
    """Résultat de résolution d'un fichier de données CSV."""
    asset: str
    timeframe: str
    path: Path
    relative_path: str
    exists: bool
    source: str
    message: str
    candidates: tuple[str, ...] = ()


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


def _normalize_asset(asset: str) -> str:
    return str(asset or DEFAULT_ASSET).strip().upper().replace(" ", "_")


def _normalize_timeframe(timeframe: str) -> str:
    return str(timeframe or DEFAULT_TIMEFRAME).strip().upper().replace(" ", "")


def _data_root() -> Path:
    return (BASE_DIR / DATA_DIR_NAME).resolve()


def _asset_dir(asset: str) -> Path:
    return _data_root() / _normalize_asset(asset)


def _timeframe_dir(asset: str, timeframe: str) -> Path:
    return _asset_dir(asset) / _normalize_timeframe(timeframe)


def _csv_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".csv")


def list_available_assets(include_legacy: bool = True) -> list[str]:
    """
    Liste les actifs disponibles ou préparés dans data/.

    Le dossier data/NASDAQ/M3 peut être versionné vide via .gitkeep : cela permet
    d'afficher NASDAQ même avant migration physique du gros CSV.
    """
    assets = set()
    root = _data_root()
    if root.is_dir():
        for item in root.iterdir():
            if item.is_dir():
                assets.add(_normalize_asset(item.name))

    if include_legacy:
        for (asset, _timeframe), legacy_rel in LEGACY_DATASETS.items():
            if resolve_path(legacy_rel).exists():
                assets.add(asset)

    if not assets:
        assets.add(DEFAULT_ASSET)

    return sorted(assets)


def list_available_timeframes(asset: str, include_legacy: bool = True) -> list[str]:
    """Liste les timeframes disponibles ou préparés pour un actif."""
    asset_key = _normalize_asset(asset)
    timeframes = set()
    asset_path = _asset_dir(asset_key)
    if asset_path.is_dir():
        for item in asset_path.iterdir():
            if item.is_dir():
                timeframes.add(_normalize_timeframe(item.name))

    if include_legacy:
        for (legacy_asset, timeframe), legacy_rel in LEGACY_DATASETS.items():
            if legacy_asset == asset_key and resolve_path(legacy_rel).exists():
                timeframes.add(timeframe)

    if not timeframes and asset_key == DEFAULT_ASSET:
        timeframes.add(DEFAULT_TIMEFRAME)

    return sorted(timeframes)


def resolve_data_csv(asset: str, timeframe: str, required: bool = False) -> DataFileResolution:
    """
    Résout le CSV correspondant à asset/timeframe.

    Priorité :
    1. data/{ASSET}/{TIMEFRAME}/*.csv
    2. fallback legacy : nasdaq_3m.csv pour NASDAQ/M3
    """
    asset_key = _normalize_asset(asset)
    timeframe_key = _normalize_timeframe(timeframe)
    candidates: list[Path] = []

    directory = _timeframe_dir(asset_key, timeframe_key)
    csvs = _csv_files(directory)
    candidates.extend(csvs)
    if csvs:
        path = csvs[0].resolve()
        return DataFileResolution(
            asset=asset_key,
            timeframe=timeframe_key,
            path=path,
            relative_path=to_relative_path(path),
            exists=True,
            source="data",
            message=f"CSV trouvé dans data/{asset_key}/{timeframe_key}/.",
            candidates=tuple(to_relative_path(p) for p in candidates),
        )

    legacy_rel = LEGACY_DATASETS.get((asset_key, timeframe_key))
    if legacy_rel:
        legacy_path = resolve_path(legacy_rel)
        candidates.append(legacy_path)
        if legacy_path.exists():
            return DataFileResolution(
                asset=asset_key,
                timeframe=timeframe_key,
                path=legacy_path,
                relative_path=to_relative_path(legacy_path),
                exists=True,
                source="legacy",
                message=(
                    f"CSV legacy utilisé : {legacy_rel}. "
                    f"Tu pourras plus tard le placer dans data/{asset_key}/{timeframe_key}/."
                ),
                candidates=tuple(to_relative_path(p) for p in candidates),
            )

    expected = directory / f"{asset_key.lower()}_{timeframe_key.lower()}.csv"
    candidates.append(expected)
    message = (
        f"Aucun CSV trouvé pour {asset_key}/{timeframe_key}. "
        f"Place un fichier .csv dans data/{asset_key}/{timeframe_key}/"
    )
    if legacy_rel:
        message += f" ou ajoute le fichier legacy {legacy_rel} à la racine."
    else:
        message += "."

    resolution = DataFileResolution(
        asset=asset_key,
        timeframe=timeframe_key,
        path=expected.resolve(),
        relative_path=to_relative_path(expected),
        exists=False,
        source="missing",
        message=message,
        candidates=tuple(to_relative_path(p) for p in candidates),
    )
    if required:
        raise FileNotFoundError(message)
    return resolution
