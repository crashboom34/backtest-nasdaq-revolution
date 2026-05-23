"""
Persistance de l'historique des backtests.

Architecture : chaque backtest est stocké dans 2 fichiers
  - <id>.meta.json   : métadonnées (lecture rapide, parsable, sûr)
  - <id>.data.pkl.gz : DataFrames (pickle gzippé, equity downsamplé)

Avantages vs un seul .pkl :
  - list_runs() ne lit que les .json => instantané même avec 50+ backtests
  - Métadonnées lisibles à l'œil, indépendantes de la version de pandas
  - Surface pickle réduite (data uniquement, jamais chargée pour le listing)

Sécurité : le dossier history/ ne doit jamais recevoir de fichiers tiers
non vérifiés (pickle.load reste exposé sur les .pkl.gz lors d'un load_run).
"""

import os
import json
import gzip
import pickle
import glob
from datetime import datetime
from uuid import uuid4

import pandas as pd

HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history")

EQUITY_MAX_POINTS = 5000   # downsampling de l'equity curve pour stockage


# ── Helpers ───────────────────────────────────────────────────────

def _ensure_dir():
    os.makedirs(HISTORY_DIR, exist_ok=True)


def _safe_filename(filename: str) -> bool:
    """Refuse les composants traversants ou les chemins absolus."""
    if not filename:
        return False
    if "/" in filename or "\\" in filename:
        return False
    if filename.startswith(".") or ".." in filename:
        return False
    return True


def _meta_path(run_id: str) -> str:
    return os.path.join(HISTORY_DIR, f"{run_id}.meta.json")


def _data_path(run_id: str) -> str:
    return os.path.join(HISTORY_DIR, f"{run_id}.data.pkl.gz")


def _downsample(df: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    """Réduit un DataFrame à max_rows lignes par échantillonnage régulier."""
    if len(df) <= max_rows:
        return df
    step = len(df) // max_rows
    sampled = df.iloc[::step].copy()
    # On garde toujours la dernière ligne (utile pour les charts)
    if df.iloc[[-1]].index[0] not in sampled.index:
        sampled = pd.concat([sampled, df.iloc[[-1]]])
    return sampled.reset_index(drop=True)


# ── API publique ──────────────────────────────────────────────────

def save_run(run_data: dict) -> str:
    """Sauvegarde un backtest. Retourne l'ID généré."""
    _ensure_dir()

    now = datetime.now()
    # Microsecondes + uuid pour éviter toute collision même en cas de rerun simultané
    run_id = now.strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:6]

    name = run_data.get("name") or f"{run_data['strat_name']} — {now.strftime('%d/%m/%Y %H:%M')}"

    meta = {
        "id":          run_id,
        "timestamp":   now.isoformat(),
        "name":        name,
        "strat_name":  run_data["strat_name"],
        "initial_cap": run_data["initial_cap"],
        "spread":      run_data.get("spread"),
        "slip_in":     run_data.get("slip_in"),
        "slip_out":    run_data.get("slip_out"),
        "params":      run_data["params"],
        "stats":       run_data["stats"],
    }

    # Downsampling de l'equity curve pour limiter la taille disque
    equity_df = run_data["equity_df"]
    if equity_df is not None and len(equity_df) > EQUITY_MAX_POINTS:
        equity_df = _downsample(equity_df, EQUITY_MAX_POINTS)

    data = {
        "trades_df": run_data["trades_df"],
        "equity_df": equity_df,
    }

    # Écriture atomique : on écrit dans des fichiers temporaires puis on rename
    meta_tmp = _meta_path(run_id) + ".tmp"
    data_tmp = _data_path(run_id) + ".tmp"

    with open(meta_tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
    with gzip.open(data_tmp, "wb", compresslevel=5) as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

    os.replace(meta_tmp, _meta_path(run_id))
    os.replace(data_tmp, _data_path(run_id))

    return run_id


def list_runs() -> list:
    """
    Liste tous les backtests via leurs métadonnées (ne lit JAMAIS les data).
    Trié du plus récent au plus ancien.
    Les fichiers corrompus sont signalés via la clé "_error".
    """
    _ensure_dir()
    files = glob.glob(os.path.join(HISTORY_DIR, "*.meta.json"))
    runs = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                meta = json.load(fp)
            runs.append(meta)
        except Exception as e:
            # On surface l'erreur au lieu de l'avaler en silence
            runs.append({
                "id":         os.path.basename(f).replace(".meta.json", ""),
                "name":       f"⚠ Fichier corrompu ({os.path.basename(f)})",
                "timestamp":  "1970-01-01",
                "strat_name": "—",
                "stats":      {},
                "initial_cap": 0,
                "_error":     str(e),
            })
    runs.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return runs


def load_run(run_id: str) -> dict:
    """
    Charge un backtest complet par ID (métadonnées + DataFrames).
    Lève FileNotFoundError si le run n'existe pas.
    """
    if not _safe_filename(run_id):
        raise ValueError(f"ID de backtest invalide : {run_id!r}")

    meta_p = _meta_path(run_id)
    data_p = _data_path(run_id)

    if not os.path.exists(meta_p):
        raise FileNotFoundError(f"Backtest {run_id} introuvable.")

    with open(meta_p, "r", encoding="utf-8") as f:
        meta = json.load(f)

    if os.path.exists(data_p):
        with gzip.open(data_p, "rb") as f:
            data = pickle.load(f)
        meta["trades_df"] = data.get("trades_df")
        meta["equity_df"] = data.get("equity_df")
    else:
        meta["trades_df"] = pd.DataFrame()
        meta["equity_df"] = pd.DataFrame()

    return meta


def delete_run(run_id: str) -> bool:
    """Supprime les deux fichiers d'un backtest. Retourne True si réussi."""
    if not _safe_filename(run_id):
        return False

    ok = False
    for path in (_meta_path(run_id), _data_path(run_id)):
        if os.path.exists(path):
            os.remove(path)
            ok = True
    return ok


def rename_run(run_id: str, new_name: str) -> bool:
    """Renomme un backtest (modifie le champ 'name' dans le JSON)."""
    if not _safe_filename(run_id):
        return False

    meta_p = _meta_path(run_id)
    if not os.path.exists(meta_p):
        return False

    new_name = (new_name or "").strip()
    if not new_name:
        return False

    with open(meta_p, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["name"] = new_name

    tmp = meta_p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, meta_p)
    return True
