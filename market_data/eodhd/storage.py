"""
market_data/eodhd/storage.py — Stockage local reproductible des données EODHD.

Sous BACKTEST_DATA_DIR (voir CLAUDE.md, Phase 5) :

    BACKTEST_DATA_DIR/
      raw/eodhd/{ticker}/{kind}/{content_hash}.json         # brut, immuable, identifié par hash
      raw/eodhd/{ticker}/{kind}/{content_hash}.manifest.json
      normalized/{asset}/{timeframe}/{content_hash}.parquet  # canonique OHLCV uniquement
      manifests/{content_hash}.json

Principes respectés :
  - données brutes immuables : un instantané avec un contenu identique (même hash SHA-256)
    n'est jamais réécrit — idempotence par contenu, pas par timestamp ;
  - écritures atomiques (fichier temporaire + os.replace()) ;
  - aucun secret dans un manifeste (request_params est stocké tel quel, mais l'appelant ne doit
    jamais y inclure api_token — voir les tests) ;
  - contrôle d'espace disque avant toute écriture (ensure_free_disk_space).

Le stockage normalisé (Parquet) ne concerne que les DataFrames au schéma canonique OHLCV
(EOD/intraday) — les dividendes/splits restent hors de ce schéma (voir docs/adr/0002-...) et ne
sont donc, à cette étape, conservés que sous forme brute (save_raw_snapshot).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from market_data.quality import analyze_quality

from .errors import EodhdConfigError, EodhdError

DEFAULT_DATA_DIR_ENV = "BACKTEST_DATA_DIR"
DEFAULT_MIN_FREE_MB = 2048  # 2 Go, même seuil que le contrôle initial obligatoire (CLAUDE.md)
_SYNC_LOG_FILENAME = "sync_log.json"
_SYNC_LOG_MAX_EVENTS = 200

# Redaction centralisée, défensive : même si un appelant transmettait par erreur ces clés dans
# request_params, elles ne doivent jamais atteindre un manifeste écrit sur disque.
_SENSITIVE_PARAM_KEYS = frozenset({"api_token", "api_key", "token", "password"})


def _redact_request_params(params: dict) -> dict:
    return {k: v for k, v in params.items() if k.lower() not in _SENSITIVE_PARAM_KEYS}


class EodhdStorageError(EodhdError):
    """Erreur de stockage local (espace disque insuffisant, écriture impossible...)."""


@dataclass(frozen=True)
class SnapshotManifest:
    """Manifeste d'un instantané normalisé — jamais aucun secret."""

    provider: str
    ticker: str
    kind: str
    asset: str
    timeframe: str
    exchange: Optional[str]
    content_hash: str
    row_count: int
    start: Optional[str]
    end: Optional[str]
    timezone: str
    quality_score_pct: Optional[float]
    quality_flags: tuple
    synced_at: str


def resolve_data_dir(env_var: str = DEFAULT_DATA_DIR_ENV) -> Path:
    """Résout BACKTEST_DATA_DIR. Lève EodhdConfigError si absent/vide — message explicite."""
    value = os.environ.get(env_var)
    if not value or not value.strip():
        raise EodhdConfigError(
            f"La variable d'environnement {env_var} n'est pas configurée. "
            "Définis-la (chemin d'un dossier local avec assez d'espace disque) avant de "
            "télécharger ou stocker des données de marché."
        )
    return Path(value).resolve()


def _nearest_existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists():
        if current.parent == current:
            break
        current = current.parent
    return current


def ensure_free_disk_space(path: Union[str, Path], min_free_mb: int = DEFAULT_MIN_FREE_MB) -> None:
    """Vérifie l'espace disque libre sur le disque contenant `path` (ou son ancêtre existant le
    plus proche, si `path` n'existe pas encore). Lève EodhdStorageError si insuffisant."""
    target = _nearest_existing_ancestor(Path(path))
    usage = shutil.disk_usage(target)
    free_mb = usage.free / (1024 * 1024)
    if free_mb < min_free_mb:
        raise EodhdStorageError(
            f"Espace disque insuffisant sur {target} : {free_mb:.0f} Mo libres "
            f"(minimum requis {min_free_mb} Mo). Libère de l'espace avant de continuer."
        )


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_part(value: str) -> str:
    """Segment de chemin sûr (mêmes règles que path_resolver._safe_filename_part)."""
    normalized = str(value or "").strip().lower()
    safe = "".join(ch if ch.isalnum() else "_" for ch in normalized)
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "unknown"


def _exchange_from_ticker(ticker: str) -> Optional[str]:
    if "." in ticker:
        return ticker.rsplit(".", 1)[1]
    return None


def _atomic_write_bytes(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _atomic_write_json(target: Path, data: dict) -> None:
    _atomic_write_bytes(target, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def save_raw_snapshot(
    data_dir: Union[str, Path],
    *,
    ticker: str,
    kind: str,
    raw_records,
    request_params: Optional[dict] = None,
    min_free_mb: int = DEFAULT_MIN_FREE_MB,
) -> Path:
    """Écrit un instantané brut immuable (JSON) + son manifeste. Idempotent par contenu : si un
    instantané identique existe déjà (même hash), aucune écriture n'a lieu et son chemin est
    retourné tel quel.

    `request_params` est informatif uniquement (paramètres de requête utilisés, ex. from/to/
    period). Toute clé sensible (api_token, api_key, token, password) y est filtrée
    automatiquement avant écriture, même si l'appelant l'y incluait par erreur — voir
    _redact_request_params(), redaction défensive plutôt que basée uniquement sur la discipline
    de l'appelant.
    """
    data_dir = Path(data_dir)
    ensure_free_disk_space(data_dir, min_free_mb=min_free_mb)

    payload = json.dumps(raw_records, ensure_ascii=False, sort_keys=True).encode("utf-8")
    content_hash = _content_hash(payload)

    target_dir = data_dir / "raw" / "eodhd" / _safe_part(ticker) / _safe_part(kind)
    target_path = target_dir / f"{content_hash}.json"
    manifest_path = target_dir / f"{content_hash}.manifest.json"

    if target_path.is_file():
        return target_path

    _atomic_write_bytes(target_path, payload)
    _atomic_write_json(
        manifest_path,
        {
            "provider": "eodhd",
            "ticker": ticker,
            "kind": kind,
            "content_hash": content_hash,
            "request_params": _redact_request_params(dict(request_params or {})),
            "row_count": len(raw_records) if isinstance(raw_records, list) else None,
            "synced_at": _utcnow_iso(),
        },
    )
    return target_path


def save_normalized(
    data_dir: Union[str, Path],
    *,
    asset: str,
    timeframe: str,
    dataframe: pd.DataFrame,
    source_ticker: str,
    source: str,
    min_free_mb: int = DEFAULT_MIN_FREE_MB,
) -> tuple[Path, SnapshotManifest]:
    """Écrit un DataFrame canonique OHLCV en Parquet + son manifeste (catalogue minimal).

    Idempotent par contenu (même convention que save_raw_snapshot). `source` identifie l'origine
    EODHD précise (ex. "eod", "intraday_1m") pour traçabilité dans le manifeste.
    """
    data_dir = Path(data_dir)
    ensure_free_disk_space(data_dir, min_free_mb=min_free_mb)

    # Sérialisation stable (CSV) uniquement pour calculer un hash de contenu reproductible —
    # le stockage réel reste le Parquet écrit plus bas. L'identité (asset/timeframe/ticker/
    # source) est incluse dans le hash : le manifeste vit dans un dossier plat (manifests/), le
    # hash doit donc rester unique même si deux instruments différents partagent, par
    # coïncidence, exactement les mêmes valeurs OHLCV.
    identity = f"{asset}|{timeframe}|{source_ticker}|{source}\n".encode("utf-8")
    content_hash = _content_hash(identity + dataframe.to_csv(index=False).encode("utf-8"))

    target_dir = data_dir / "normalized" / _safe_part(asset) / _safe_part(timeframe)
    target_path = target_dir / f"{content_hash}.parquet"

    if not target_path.is_file():
        target_dir.mkdir(parents=True, exist_ok=True)
        tmp = target_path.with_name(target_path.name + ".tmp")
        try:
            dataframe.to_parquet(tmp, index=False)
            os.replace(tmp, target_path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    quality = analyze_quality(dataframe) if len(dataframe) else None
    row_count = int(len(dataframe))
    manifest = SnapshotManifest(
        provider="eodhd",
        ticker=source_ticker,
        kind=f"normalized_{source}",
        asset=asset,
        timeframe=timeframe,
        exchange=_exchange_from_ticker(source_ticker),
        content_hash=content_hash,
        row_count=row_count,
        start=str(dataframe["time"].min()) if row_count else None,
        end=str(dataframe["time"].max()) if row_count else None,
        timezone="UTC",
        quality_score_pct=quality.quality_score_pct if quality else None,
        quality_flags=tuple(quality.quality_flags) if quality else (),
        synced_at=_utcnow_iso(),
    )

    manifests_dir = data_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(manifests_dir / f"{content_hash}.json", asdict(manifest))

    return target_path, manifest


# ═══════════════════════════════════════════════════════════════════════════════
# Catalogue minimal (Phase 5) : lister ce qui est déjà stocké, sans reconstruire un catalogue
# multi-fournisseurs complet (market_data.catalog reste scopé aux CSV locaux à cette étape).
# ═══════════════════════════════════════════════════════════════════════════════


def list_normalized_snapshots(data_dir: Union[str, Path]) -> list:
    """Liste tous les manifestes normalisés déjà enregistrés (manifests/*.json, hors journal de
    synchro). Tolérant : un fichier corrompu ou incomplet est ignoré, jamais d'exception."""
    manifests_dir = Path(data_dir) / "manifests"
    if not manifests_dir.is_dir():
        return []

    results = []
    for path in sorted(manifests_dir.glob("*.json")):
        if path.name == _SYNC_LOG_FILENAME:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            payload = dict(data)
            payload["quality_flags"] = tuple(payload.get("quality_flags") or ())
            results.append(SnapshotManifest(**payload))
        except TypeError:
            continue
    return results


def list_raw_snapshots(data_dir: Union[str, Path], *, ticker: Optional[str] = None) -> list:
    """Liste tous les manifestes d'instantanés bruts EODHD (raw/eodhd/**/*.manifest.json).

    Filtre optionnellement par `ticker`. Tolérant : fichier corrompu ignoré, jamais d'exception.
    """
    raw_dir = Path(data_dir) / "raw" / "eodhd"
    if not raw_dir.is_dir():
        return []

    results = []
    for path in sorted(raw_dir.glob("**/*.manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if ticker is not None and data.get("ticker") != ticker:
            continue
        results.append(data)
    return results


@dataclass(frozen=True)
class DiskUsageSummary:
    """Instantané en lecture seule de l'espace disque — pour affichage UI (Phase 10)."""

    total_gb: float
    used_gb: float
    free_gb: float
    min_free_mb: int
    sufficient: bool


def disk_usage_summary(
    path: Union[str, Path], min_free_mb: int = DEFAULT_MIN_FREE_MB
) -> DiskUsageSummary:
    """Résumé lecture seule de l'espace disque sur le disque contenant `path`."""
    target = _nearest_existing_ancestor(Path(path))
    usage = shutil.disk_usage(target)
    gb = 1024 ** 3
    return DiskUsageSummary(
        total_gb=usage.total / gb,
        used_gb=usage.used / gb,
        free_gb=usage.free / gb,
        min_free_mb=min_free_mb,
        sufficient=(usage.free / (1024 * 1024)) >= min_free_mb,
    )


@dataclass(frozen=True)
class SyncEvent:
    """Un événement du journal de synchronisation — `message` doit déjà être sûr avant appel
    (voir market_data.eodhd.errors.redact_url(), utilisée par toute la chaîne d'erreurs EODHD)."""

    timestamp: str
    ticker: str
    kind: str
    ok: bool
    message: str


def _read_sync_log_raw(log_path: Path) -> list:
    if not log_path.is_file():
        return []
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    events = data.get("events") if isinstance(data, dict) else None
    return list(events) if isinstance(events, list) else []


def record_sync_event(
    data_dir: Union[str, Path], *, ticker: str, kind: str, ok: bool, message: str
) -> None:
    """Ajoute un événement au journal de synchro (manifests/sync_log.json), plafonné aux
    _SYNC_LOG_MAX_EVENTS plus récents (pas de croissance illimitée)."""
    log_path = Path(data_dir) / "manifests" / _SYNC_LOG_FILENAME
    events = _read_sync_log_raw(log_path)
    events.append(
        {
            "timestamp": _utcnow_iso(),
            "ticker": ticker,
            "kind": kind,
            "ok": bool(ok),
            "message": message,
        }
    )
    events = events[-_SYNC_LOG_MAX_EVENTS:]
    _atomic_write_json(log_path, {"events": events})


def load_sync_log(data_dir: Union[str, Path], limit: int = 50) -> list:
    """Les `limit` événements les plus récents, du plus ancien au plus récent. Tolérant."""
    log_path = Path(data_dir) / "manifests" / _SYNC_LOG_FILENAME
    raw_events = _read_sync_log_raw(log_path)[-limit:]
    events = []
    for item in raw_events:
        try:
            events.append(SyncEvent(**item))
        except TypeError:
            continue
    return events


def last_successful_sync(data_dir: Union[str, Path]) -> Optional[SyncEvent]:
    for event in reversed(load_sync_log(data_dir, limit=_SYNC_LOG_MAX_EVENTS)):
        if event.ok:
            return event
    return None


def last_failed_sync(data_dir: Union[str, Path]) -> Optional[SyncEvent]:
    for event in reversed(load_sync_log(data_dir, limit=_SYNC_LOG_MAX_EVENTS)):
        if not event.ok:
            return event
    return None


def normalized_snapshot_path(data_dir: Union[str, Path], manifest: SnapshotManifest) -> Path:
    """Reconstruit le chemin du fichier Parquet correspondant à un manifeste normalisé déjà
    enregistré par save_normalized() — utilisé par market_data.eodhd.adapter pour relire un
    snapshot sans dupliquer la logique de construction de chemin."""
    return (
        Path(data_dir)
        / "normalized"
        / _safe_part(manifest.asset)
        / _safe_part(manifest.timeframe)
        / f"{manifest.content_hash}.parquet"
    )
