"""
market_data/backtest_manifest.py — Manifeste reproductible d'un backtest (Data Center Phase 11).

Capacité additive : produit et sauvegarde un manifeste décrivant précisément quelles données et
quelle configuration ont servi à un backtest, pour pouvoir le reproduire plus tard. N'est PAS
branché automatiquement dans job_store.py/run_job.py à cette étape — même principe que
engine.load_data_from_source() (Phase 1) : capacité disponible et testée, adoption comme chemin
par défaut du pipeline de jobs laissée à une décision explicite séparée, pour ne pas risquer de
régression sur les jobs réellement utilisés (voir AI_HANDOFF.md).

Champs minimaux requis (CLAUDE.md, Phase 11) : fournisseur, instrument, symbole fournisseur,
type d'actif, snapshot, hash, période, unité source, unité dérivée, timezone, séance, gestion
des barres partielles, options de rééchantillonnage, version de la stratégie, version du moteur,
commit Git si disponible, date du lancement.

Un manifeste, une fois écrit, n'est jamais modifié ni écrasé (immuable, comme les données
brutes — voir CLAUDE.md : "Ne modifie jamais les anciens manifestes ou résultats").
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

# Incrémenter manuellement à chaque changement de comportement observable du moteur
# (engine.run_backtest / engine.load_data / engine.load_data_from_source).
ENGINE_VERSION = "1.0"


@dataclass(frozen=True)
class BacktestManifest:
    """Manifeste reproductible d'un backtest — voir docstring du module pour la liste des
    champs minimaux requis (CLAUDE.md, Phase 11)."""

    provider: str
    instrument: str
    provider_symbol: str
    asset_type: Optional[str]
    snapshot_id: Optional[str]
    content_hash: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    source_timeframe: str
    derived_timeframe: Optional[str]
    timezone: str
    session: str
    partial_bar_handling: str
    resample_options: dict
    strategy_version: str
    engine_version: str
    git_commit: Optional[str]
    launched_at: str


def _current_git_commit(repo_dir: Optional[Union[str, Path]] = None) -> Optional[str]:
    """Commit Git court si disponible, sinon None — jamais d'exception, jamais bloquant (git
    absent, dossier hors dépôt, timeout...)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_dir) if repo_dir else None,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def build_backtest_manifest(
    *,
    provider: str,
    instrument: str,
    provider_symbol: str,
    source_timeframe: str,
    asset_type: Optional[str] = None,
    snapshot_id: Optional[str] = None,
    content_hash: Optional[str] = None,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    derived_timeframe: Optional[str] = None,
    timezone_name: str = "UTC",
    session: str = "regular",
    partial_bar_handling: str = "kept_and_flagged",
    resample_options: Optional[dict] = None,
    strategy_version: str = "unknown",
    engine_version: str = ENGINE_VERSION,
    git_commit: Optional[str] = "auto",
    launched_at: Optional[str] = None,
    repo_dir: Optional[Union[str, Path]] = None,
) -> BacktestManifest:
    """Construit un manifeste reproductible.

    `git_commit="auto"` (défaut) détecte le commit Git courant du dépôt ; passer explicitement
    `None` le désactive (utile pour les tests hors dépôt, ou un environnement sans Git).
    """
    resolved_commit = _current_git_commit(repo_dir) if git_commit == "auto" else git_commit
    resolved_launched_at = launched_at or datetime.now(timezone.utc).isoformat()

    return BacktestManifest(
        provider=provider,
        instrument=instrument,
        provider_symbol=provider_symbol,
        asset_type=asset_type,
        snapshot_id=snapshot_id,
        content_hash=content_hash,
        period_start=period_start,
        period_end=period_end,
        source_timeframe=source_timeframe,
        derived_timeframe=derived_timeframe,
        timezone=timezone_name,
        session=session,
        partial_bar_handling=partial_bar_handling,
        resample_options=dict(resample_options or {}),
        strategy_version=strategy_version,
        engine_version=engine_version,
        git_commit=resolved_commit,
        launched_at=resolved_launched_at,
    )


def save_backtest_manifest(path: Union[str, Path], manifest: BacktestManifest) -> Path:
    """Écriture atomique du manifeste en JSON (fichier temporaire + os.replace()).

    Lève FileExistsError si `path` existe déjà : un manifeste est immuable une fois écrit,
    jamais écrasé (voir docstring du module).
    """
    target = Path(path)
    if target.is_file():
        raise FileExistsError(
            f"Un manifeste existe déjà à {target} — les manifestes sont immuables, utilise un "
            "nouveau chemin plutôt que d'écraser celui-ci."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(
            json.dumps(asdict(manifest), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return target


def load_backtest_manifest(path: Union[str, Path]) -> Optional[BacktestManifest]:
    """Lecture tolérante : fichier absent, illisible ou invalide -> None, jamais d'exception."""
    target = Path(path)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return BacktestManifest(**data)
    except TypeError:
        return None
