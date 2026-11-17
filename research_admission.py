"""research_admission — pré-vol expérimental d'une stratégie (T1-a, étape A0).

DIAGNOSTIC EXPÉRIMENTAL, NON BLOQUANT. Bibliothèque autonome et commande manuelle : aucun point
d'entrée du dépôt n'appelle ce module, il ne protège donc rien (`LIBRARY_ONLY`).

`PASS` d'un contrôle = aucune violation observée dans la couverture effectivement exécutée.
Jamais : causalité établie, absence de sur-ajustement, robustesse, qualité, autorisation de
trading, qualification Champion. `NO_VIOLATION_OBSERVED` si et seulement si les cinq contrôles
sont `PASS` ; sinon `NOT_ADMITTED`. Aucune dérogation : ni `INCONCLUSIVE` ni `FAIL` ne se convertissent.
Le plancher `min_decisions` est cependant un réglage de protocole : l'abaisser marque le protocole
`reduced` et le libellé favorable devient `NO_VIOLATION_OBSERVED_TEST_ONLY` (la commande manuelle
refuse tout protocole réduit). Seul `MIN_EXERCISED_SETS` est une constante.

Sécurité : le code de la stratégie est EXÉCUTÉ, pas confiné. Deux interpréteurs séparés ne sont
pas un bac à sable. Seules des stratégies locales explicitement approuvées par l'opérateur
(chemin réel et SHA-256 des octets) sont exécutées par le harnais ; l'option interne `--worker`
du même fichier (réservée aux interpréteurs enfants, hors approbation) est une exception déclarée.

Contrat : docs/adr/0028-research-admission-v1.md.
"""
import argparse
import bisect
import hashlib
import importlib.machinery
import itertools
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import types
from datetime import datetime, timezone

import numpy as np
import pandas as pd

SEMANTICS_VERSION = "research-admission-v1"
NOTICE = "diagnostic expérimental, non bloquant"
ACTIVATION = "LIBRARY_ONLY"
CHECK_NAMES = ("data", "determinism", "prepare_prefix", "decision_replay", "signal_contract")
STATES = ("PASS", "INCONCLUSIVE", "FAIL")
CANONICAL_COLUMNS = ("time", "open", "high", "low", "close", "volume")
VALUE_COLUMNS = CANONICAL_COLUMNS[1:]
FRAME_ORIGINS = ("synthetic", "train_excerpt")
VARIANTS = ("up", "down")
ALLOWED_OUTPUT_DRIVES = ("D:",)
FORBIDDEN_OUTPUT_COMPONENTS = ("results", "dataset_splits", "validations", "experiments", "datasets")
FORBIDDEN_OUTPUT_PREFIXES = ("gate_v", "campaign")
PINNED_REPO_MODULES = ("engine", "scoring", "strategy_contracts")
MAX_FRAME_BARS = 20_000
# Suite de barres consécutives aux valeurs identiques (horodatages ignorés) à partir de laquelle deux
# positions sont tenues pour la même preuve : copie décalée dans le temps. Constante, jamais un réglage.
OVERLAP_RUN_BARS = 5
MIN_FREE_BYTES = 1 << 30
MAX_RESPONSE_BYTES = 32 << 20
MAX_APPROVAL_BYTES = 1 << 20
DEFAULT_PROTOCOL = {
    "window_bars": 300, "n_trace_windows": 2, "n_independent_windows": 1, "min_decisions": 10,
    "future_bars": 5, "sparse_bars": 16, "prefix_cuts": 5, "max_replays": 20_000, "timeout_s": 3600,
}
MIN_EXERCISED_SETS = 3  # jeu de base et deux autres jeux distincts : constante, jamais un réglage
_STRENGTH_KEYS = ("window_bars", "n_trace_windows", "n_independent_windows", "min_decisions", "future_bars",
                  "sparse_bars", "prefix_cuts")
NOT_COVERED = (
    "évasion délibérée (stratégie qui détecte le harnais)",
    "information passée par le code : constantes, dates ou seuils choisis après avoir vu l'historique",
    "colonne déjà dérivée du futur dans le fichier de données",
    "chemin de code que les barres testées n'exercent pas, dont une violation tardive",
    "calendrier de la barre suivante : les horodatages réels des barres futures sont conservés",
    "lectures du système de fichiers par la stratégie et tous ses effets de bord",
    "décalage de début de fenêtre appliqué en production : seul le démarrage au warmup est exercé",
    "optimisme d'exécution du moteur ; nombre d'essais ; réutilisation de la zone de validation",
    "fuseau horaire des données",
    "scalaires non numériques et objets propres à la stratégie laissés par prepare()",
    "prédicats sur le futur que deux variantes monotones ne séparent pas",
    "fuites douces ne changeant aucune décision testée",
    "resoumission et choix des extraits par l'opérateur",
    "origine de la stratégie et des extraits : déclarées, non vérifiées",
    "volume entier des données réelles : le harnais convertit les colonnes de valeurs en flottants",
    "ordre dépendant du hachage : la graine est fixée à 0 dans les interpréteurs enfants, la production la randomise",
    "jeux de paramètres au comportement identique sur les extraits : comptés une fois ; leur effet sur d'autres données reste inconnu",
)
NOT_PREVENTED = (
    "accès réseau par la stratégie",
    "lecture de tout fichier lisible par l'opérateur, donc du fichier de données complet, zone finale comprise",
    "modules natifs",
    "fils et processus lancés par la stratégie",
    "épuisement de la mémoire",
    "remplissage du disque au-delà du contrôle préalable d'espace",
    "falsification du fichier de résultat d'un interpréteur enfant",
    "toute attaque menée par le même utilisateur",
    "contournement de la garde d'import par chargement direct d'un fichier ou accès au module principal du harnais",
    "modification d'un module local approuvé entre sa vérification et son import",
    "processus lancés par la stratégie et survivant à une fin normale de l'interpréteur enfant : non détectés",
    "crochet d'audit : fil d'alerte au mieux, contournable par du code natif",
    "enregistrement tronqué par une panne pendant l'écriture : il bloque les écritures suivantes du même identifiant",
    "arrêt brutal du harnais (processus tué) : ses interpréteurs enfants ne sont pas arrêtés ; une interruption au clavier les arrête",
    "petits-enfants détachés avant un arrêt sur délai : l'arrêt suit les liens de parenté encore vivants",
    "repli Popen.kill() si taskkill échoue : il n'atteint que le lanceur du venv Windows, pas l'interpréteur réel (signalé par `survivors`)",
    "dossier nommé site-packages ajouté au chemin de recherche par la stratégie : exempté de la garde et du hachage",
    "plafond de rejeux : seuls les rejeux comptés le consomment ; une requête en échec ou hors délai n'est pas "
    "débitée (son groupe est INCONCLUSIVE)",
    "option interne `--worker` du même fichier : exécute la stratégie d'un fichier de requête, sans approbation",
    "nouvelle tentative après délai ou réponse illisible : l'attente maximale par requête double",
    "modules locaux approuvés lus depuis le disque : fenêtre entre vérification, import et hachage final",
)
NOT_IMPLEMENTED_AT_A0 = (
    "lignes du source jamais exécutées à une barre testée",
    "répartition des barres testées par heure et jour de semaine",
    "début d'extrait à une frontière de jour : non vérifié",
    "contrôle C-SUFFIXE-RÉEL (rejeu sur suffixe réel après une exception au rejeu) : différé à A1 ; toute exception "
    "reproduite donne INCONCLUSIVE / STRATEGY_RAISES, FAIL STRATEGY_FAILS_WITHOUT_FUTURE n'est jamais émis",
    "exécution des modules locaux approuvés depuis leurs octets : comparaison a posteriori des hash seulement",
    "paquets locaux approuvés (répertoire) : non chargeables ; modules épinglés scoring et strategy_contracts : "
    "enregistrés, non comparés",
    "équivalence avec le chargeur de production : visée, non testée (__file__ et __spec__ diffèrent)",
)
_STRATEGY_FILENAME = "<approved-strategy>"
_SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "IG_", "BROKER", "BACKTEST_BASE_DIR")
_SIDE_EFFECT_EVENTS = frozenset({
    "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.system", "os.startfile", "os.exec", "os.spawn",
    "os.posix_spawn", "os.fork", "subprocess.Popen", "socket.connect", "socket.bind", "socket.sendto",
    "socket.getaddrinfo", "socket.__new__", "ctypes.dlopen", "shutil.rmtree", "shutil.move", "shutil.copyfile",
    "os.truncate", "os.chmod", "os.symlink", "os.link", "urllib.Request",
})
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


# ───────────────────────────── utilitaires purs ─────────────────────────────

def canonical_json(value):
    """JSON canonique : clés triées, séparateurs compacts, non-ASCII conservé, non-finis interdits."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalised_sha256(path):
    """SHA-256 après normalisation des fins de ligne, comme les épingles du dépôt."""
    with open(path, "rb") as handle:
        return _sha256(handle.read().replace(b"\r\n", b"\n"))


def _same_path(left, right):
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _is_under(path, root):
    path = os.path.normcase(os.path.realpath(path))
    root = os.path.normcase(os.path.realpath(root))
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def _hash_int(*parts):
    return int(_sha256("|".join(str(p) for p in parts).encode("utf-8")), 16)


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):  # entier hors de portée des flottants : non fini
        return None
    return value if math.isfinite(value) else None


def _check(name, state, codes=(), coordinates=None, coverage=None):
    return {"check": name, "state": state, "codes": list(codes), "coordinates": dict(coordinates or {}),
            "coverage": dict(coverage or {})}


def _not_run(name):
    return _check(name, "INCONCLUSIVE", ["NOT_RUN"])


def compute_decision(checks):
    """Le diagnostic est calculé à partir d'exactement cinq contrôles, chacun une fois."""
    try:
        names = [c["check"] for c in checks]
        states = [c["state"] for c in checks]
    except (TypeError, KeyError):
        return "NOT_ADMITTED"
    if tuple(names) != CHECK_NAMES or any(s not in STATES for s in states):
        return "NOT_ADMITTED"
    return "NO_VIOLATION_OBSERVED" if all(s == "PASS" for s in states) else "NOT_ADMITTED"


def _final_decision(checks, protocol, subject):
    """Libellé enregistré. Un protocole réduit ou un lanceur injecté n'obtiennent jamais le libellé
    favorable simple : leur résultat ne vaut que pour les tests."""
    decision = compute_decision(checks)
    if decision != "NO_VIOLATION_OBSERVED":
        return decision
    if (protocol or {}).get("reduced") or (subject or {}).get("runner") == "injected_in_process":
        return "NO_VIOLATION_OBSERVED_TEST_ONLY"
    return decision


def _resolve_protocol(protocol):
    merged = dict(DEFAULT_PROTOCOL)
    for key, value in dict(protocol or {}).items():
        if key not in DEFAULT_PROTOCOL:
            raise ValueError(f"paramètre de protocole inconnu : {key!r}")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"paramètre de protocole invalide : {key!r}")
        merged[key] = value
    if min(merged["window_bars"], merged["future_bars"], merged["timeout_s"], merged["n_independent_windows"]) < 1:
        raise ValueError("window_bars, future_bars, timeout_s et n_independent_windows doivent être >= 1")
    # Protocole réduit : au moins un réglage plus faible que le défaut. Déclaré dans l'enregistrement ;
    # la commande manuelle le refuse. Un diagnostic sous protocole réduit ne vaut que pour lui.
    merged["reduced"] = any(merged[k] < DEFAULT_PROTOCOL[k] for k in _STRENGTH_KEYS)
    merged["variants"] = list(VARIANTS)
    return merged


# ───────────────────────────── données ─────────────────────────────

def frame_csv_bytes(frame):
    """Octets canoniques d'un extrait (colonnes canoniques seulement) : base de son empreinte."""
    text = frame.loc[:, list(CANONICAL_COLUMNS)].to_csv(index=False, lineterminator="\n",
                                                        date_format="%Y-%m-%dT%H:%M:%S.%f")
    return text.encode("utf-8")


def _read_frame_csv(path):
    frame = pd.read_csv(path, parse_dates=["time"], float_precision="round_trip")
    for column in VALUE_COLUMNS:
        frame[column] = frame[column].astype("float64")
    return frame


def _as_utc(value):
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _zone_codes(frame, origin, split_plan):
    if origin == "synthetic":
        return []
    if origin != "train_excerpt":
        return ["DATA_ZONE_FORBIDDEN"]
    if split_plan is None:
        return ["DATA_ZONE_UNVERIFIED"]
    first, last = _as_utc(frame["time"].iloc[0]), _as_utc(frame["time"].iloc[-1])
    try:
        train = split_plan.train
        inside = _as_utc(train.start) <= first and last < _as_utc(train.end)
        for name in ("final_holdout", "validation", "discovery_oos"):
            zone = getattr(split_plan, name, None)
            if zone is not None and first < _as_utc(zone.end) and _as_utc(zone.start) <= last:
                inside = False
    except (AttributeError, TypeError, ValueError):
        return ["DATA_ZONE_UNVERIFIED"]
    return [] if inside else ["DATA_ZONE_FORBIDDEN"]


def check_market_frame(frame, origin, split_plan=None, declared_sha256=None):
    """Contrôle « données » d'un extrait. Ne lit que l'extrait fourni."""
    fail, soft = [], []
    coverage = {"origin": origin, "n_bars": int(len(frame)) if hasattr(frame, "__len__") else 0}
    if not isinstance(frame, pd.DataFrame) or set(frame.columns) != set(CANONICAL_COLUMNS) \
            or len(frame.columns) != len(CANONICAL_COLUMNS):
        return _check("data", "FAIL", ["DATA_UNDECLARED_COLUMN"], coverage=coverage)
    if len(frame) < 2 or not pd.api.types.is_datetime64_any_dtype(frame["time"]) or frame["time"].isna().any():
        return _check("data", "FAIL", ["DATA_TIME_NOT_INCREASING"], coverage=coverage)
    # Complexes (partie imaginaire), dates et durées : pas des réels, même si numpy sait les convertir.
    if any(frame[column].dtype.kind in "cMm" for column in VALUE_COLUMNS):
        return _check("data", "FAIL", ["DATA_NON_FINITE"], coverage=coverage)
    try:
        values = frame.loc[:, list(VALUE_COLUMNS)].to_numpy(dtype="float64")
    except (TypeError, ValueError, OverflowError):  # entier hors de portée des flottants : non fini
        return _check("data", "FAIL", ["DATA_NON_FINITE"], coverage=coverage)
    if not np.isfinite(values).all():
        fail.append("DATA_NON_FINITE")
    if not (np.diff(frame["time"].to_numpy().astype("datetime64[ns]").astype("int64")) > 0).all():
        fail.append("DATA_TIME_NOT_INCREASING")
    opened, high, low, close = values[:, 0], values[:, 1], values[:, 2], values[:, 3]
    if "DATA_NON_FINITE" not in fail and not (
            (high >= np.maximum(opened, close)) & (low <= np.minimum(opened, close)) & (high >= low)).all():
        fail.append("DATA_OHLC_INCONSISTENT")
    if not fail:
        fingerprint = _sha256(frame_csv_bytes(frame))
        coverage["sha256"] = fingerprint
        if declared_sha256 is not None and declared_sha256 != fingerprint:
            fail.append("DATA_HASH_MISMATCH")
    for code in _zone_codes(frame, origin, split_plan):
        (fail if code == "DATA_ZONE_FORBIDDEN" else soft).append(code)
    if len(frame) > MAX_FRAME_BARS:
        soft.append("FRAME_TOO_LARGE")
    if fail:
        return _check("data", "FAIL", fail, coverage=coverage)
    return _check("data", "INCONCLUSIVE" if soft else "PASS", soft, coverage=coverage)


# ───────────────────────────── barres testées et barres futures ─────────────────────────────

def excerpt_amplitude(frame):
    """Trois fois le plus grand mouvement absolu de clôture à clôture de l'extrait."""
    closes = frame["close"].to_numpy(dtype="float64")
    largest = float(np.abs(np.diff(closes)).max()) if len(closes) > 1 else 0.0
    if not math.isfinite(largest) or largest <= 0.0:
        largest = max(abs(float(closes[-1])) * 0.001, 1e-9) if len(closes) else 1.0
    return 3.0 * largest


def truncated_frame(frame, cut, future_bars, amplitude, variant):
    """Historique coupé après `cut`, plus `future_bars` barres synthétiques.

    Les barres futures gardent leurs horodatages (et colonnes horaires dérivées) ; toutes leurs
    colonnes de valeurs sont reconstruites à partir de la seule clôture de la barre de coupe et de
    l'amplitude : jamais d'une valeur future réelle."""
    if variant not in VARIANTS:
        raise ValueError(f"variante inconnue : {variant!r}")
    stop = cut + 1 + future_bars
    if cut < 0 or stop > len(frame):
        raise ValueError("coupe hors de l'extrait")
    out = frame.iloc[:stop].copy()
    anchor = float(frame["close"].iloc[cut])
    step = min(float(amplitude), abs(anchor) / (2.0 * (future_bars + 1))) if anchor > 0 else float(amplitude)
    sign = 1.0 if variant == "up" else -1.0
    ranks = np.arange(1, future_bars + 1, dtype="float64")
    opened = anchor + sign * (ranks - 1.0) * step
    close = anchor + sign * ranks * step
    volume = 0.0 if variant == "up" else 10.0 * float(frame["volume"].iloc[cut])
    columns = {"open": opened, "close": close, "high": np.maximum(opened, close) + 0.1 * step,
               "low": np.minimum(opened, close) - 0.1 * step, "volume": np.full(future_bars, volume)}
    for name, values in columns.items():
        out.iloc[cut + 1:, out.columns.get_loc(name)] = values
    return out


def plan_tested_bars(*, decision_bars, first_bar, last_bar, fingerprint, protocol, max_bars=None):
    """Barres testées d'un groupe (extrait, jeu de paramètres).

    Fenêtres indépendantes de la trace : tirées de l'empreinte de l'extrait et de la version.
    Fenêtres denses sur la trace : non chevauchantes, par nombre décroissant de décisions,
    départage par position croissante, ajoutées jusqu'au nombre demandé PUIS jusqu'au plancher de
    décisions ; le budget (`max_bars`) est un plafond."""
    width = min(int(protocol["window_bars"]), last_bar - first_bar + 1)
    plan = {"trace_windows": [], "independent_windows": [], "sparse": [], "bars": [], "tested_decisions": 0,
            "budget_exhausted": False}
    if width < 1:
        return plan
    budget = math.inf if max_bars is None else int(max_bars)
    low, high = first_bar, last_bar - width + 1
    decisions = sorted({int(b) for b in decision_bars if first_bar <= b <= last_bar})
    bars = set()

    def affordable(window):
        return len(bars | set(range(window[0], window[1]))) <= budget

    for rank in range(int(protocol["n_independent_windows"])):
        start = low + _hash_int(fingerprint, SEMANTICS_VERSION, "independent", rank) % (high - low + 1)
        window = [start, start + width]
        if not affordable(window):
            plan["budget_exhausted"] = True
            break
        if window not in plan["independent_windows"]:
            plan["independent_windows"].append(window)
            bars.update(range(*window))

    def tested():
        return sum(1 for d in decisions if d in bars)

    while not plan["budget_exhausted"]:
        left = [d for d in decisions if d not in bars]
        if not left or (len(plan["trace_windows"]) >= protocol["n_trace_windows"]
                        and tested() >= protocol["min_decisions"]):
            break
        starts = {min(max(s, low), high) for d in left for s in (d - width // 2, d, d - width + 1)}
        free = [s for s in starts if all(s + width <= w[0] or w[1] <= s for w in plan["trace_windows"])]
        scored = sorted((-sum(1 for d in left if s <= d < s + width), s) for s in free)
        if not scored or scored[0][0] == 0:
            break
        window = [scored[0][1], scored[0][1] + width]
        if not affordable(window):
            plan["budget_exhausted"] = True
            break
        plan["trace_windows"].append(window)
        bars.update(range(*window))

    plan["tested_decisions"] = tested()
    outside = [d for d in decisions if d not in bars]
    owed = min(int(protocol["sparse_bars"]), len(outside))
    wanted = min(owed, max(0, int(min(budget, 10 ** 9)) - len(bars)))
    if wanted < owed:  # barres éparses tronquées par le budget : obligation non remplie
        plan["budget_exhausted"] = True
    if wanted == 1:
        plan["sparse"] = [outside[0]]
    elif wanted > 1:
        plan["sparse"] = sorted({outside[k * (len(outside) - 1) // (wanted - 1)] for k in range(wanted)})
    bars.update(plan["sparse"])
    plan["bars"] = sorted(bars)
    return plan


def _prefix_cuts(frame, fingerprint, count):
    """Longueurs de préfixe tirées de l'empreinte, décalées hors des débuts d'heure."""
    size = len(frame)
    low, high = size // 3, size - 1
    if high <= low or count < 1:
        return []
    minutes = frame["time"].dt.minute.to_numpy()
    cuts = set()
    for rank in range(count):
        cut = low + _hash_int(fingerprint, SEMANTICS_VERSION, "prefix", rank) % (high - low)
        while cut < high and minutes[cut] == 0:
            cut += 1
        cuts.add(int(cut))
    return sorted(cuts)


# ───────────────────────────── refus : sortie, approbation, environnement ─────────────────────────────

def _free_bytes(path):
    probe = os.path.abspath(path)
    while not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return shutil.disk_usage(probe).free


def output_dir_refusal(output_dir):
    """Motif de refus du répertoire de sortie, ou None. N'écrit rien."""
    if not isinstance(output_dir, str) or not output_dir or output_dir.startswith(("\\\\", "//")):
        return "chemin de sortie invalide ou réseau"
    path = os.path.abspath(output_dir)
    for candidate in (path, os.path.realpath(path)):  # le chemin donné et sa cible réelle (jonctions)
        drive = os.path.splitdrive(candidate)[0].upper()
        if drive not in ALLOWED_OUTPUT_DRIVES:
            return f"lecteur {drive or '(aucun)'} non autorisé"
        for part in [p.lower() for p in candidate.replace("\\", "/").split("/") if p]:
            if part in FORBIDDEN_OUTPUT_COMPONENTS or part.startswith(FORBIDDEN_OUTPUT_PREFIXES):
                return f"composant observé : {part}"
    if _is_under(path, _REPO_ROOT):
        return "sous le dépôt"
    probe = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(probe, ".git")):
            return "sous un arbre Git"
        parent = os.path.dirname(probe)
        if parent == probe:
            return None
        probe = parent


def _copy_on_write_active():
    frame = pd.DataFrame({"a": [1.0, 2.0]})
    shallow = frame.copy(deep=False)
    try:
        shallow.iloc[0, 0] = 9.0
    except Exception:  # noqa: BLE001 - toute anomalie vaut « non actif »
        return False
    return float(frame.iloc[0, 0]) == 1.0


def build_child_environment(base_dir):
    """Environnement d'un interpréteur enfant : liste blanche, jamais l'environnement du parent."""
    home, temp = os.path.join(base_dir, "home"), os.path.join(base_dir, "tmp")
    env = {"TEMP": temp, "TMP": temp, "TMPDIR": temp, "HOME": home, "USERPROFILE": home, "APPDATA": home,
           "LOCALAPPDATA": home, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
           "NUMEXPR_NUM_THREADS": "1", "PYTHONHASHSEED": "0",
           # répertoire de cache de bytecode vide : aucun `__pycache__` préexistant n'est lu à la place des sources
           "PYTHONPYCACHEPREFIX": os.path.join(base_dir, "pyc")}
    if os.environ.get("SystemRoot"):
        env["SystemRoot"] = os.environ["SystemRoot"]
    return env


def secret_like_variables(env):
    return sorted(name for name in env if any(marker in name.upper() for marker in _SECRET_MARKERS))


def _taskkill_path():
    root = os.environ.get("SystemRoot")
    path = os.path.join(root, "System32", "taskkill.exe") if root else None
    return path if path and os.path.isfile(path) else None


def _tree_kill_available():
    return _taskkill_path() is not None if os.name == "nt" else hasattr(os, "killpg")


def process_alive(pid):
    """Vrai si le processus existe encore. N'envoie aucun signal sous Windows."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return ctypes.get_last_error() == 5
    try:
        code = wintypes.DWORD()
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle(handle)


def _kill_tree(pid):
    if os.name == "nt":
        try:
            subprocess.run([_taskkill_path(), "/PID", str(int(pid)), "/T", "/F"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=60)
        except (OSError, TypeError, subprocess.TimeoutExpired):
            pass  # l'appelant retombe sur Popen.kill() puis vérifie la disparition du processus
    else:
        try:
            os.killpg(pid, 9)
        except OSError:
            pass


def _wait_dead(pid, seconds=10.0):
    deadline = time.monotonic() + seconds
    while process_alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


class _Refusal(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _read_approved_strategy(strategy_path, approval_path, output_dir):
    """Ordre imposé avant tout import : approbation, chemin réel, octets lus une fois, hash."""
    if not isinstance(strategy_path, str) or not strategy_path.endswith(".py") \
            or not (os.path.isabs(strategy_path) or os.sep in strategy_path or "/" in strategy_path):
        raise _Refusal("UNSUPPORTED_STRATEGY_CONTRACT")
    try:
        if not os.path.isfile(approval_path) or os.path.getsize(approval_path) > MAX_APPROVAL_BYTES \
                or _is_under(approval_path, _REPO_ROOT) or _is_under(approval_path, output_dir):
            raise _Refusal("APPROVAL_INVALID")
        with open(approval_path, "rb") as handle:
            approval = json.loads(handle.read().decode("utf-8"))
    except (OSError, TypeError, ValueError):
        raise _Refusal("APPROVAL_INVALID") from None
    if not isinstance(approval, dict) or set(approval) != {"strategy_path", "sha256", "origin", "local_modules"} \
            or approval["origin"] not in ("handwritten", "generated") or not isinstance(approval["local_modules"], dict) \
            or not isinstance(approval["strategy_path"], str) or not isinstance(approval["sha256"], str):
        raise _Refusal("APPROVAL_INVALID")
    absolute = os.path.abspath(strategy_path)
    if strategy_path.startswith(("\\\\", "//")) or not os.path.isfile(absolute) \
            or os.path.normcase(os.path.realpath(absolute)) != os.path.normcase(absolute):
        raise _Refusal("STRATEGY_PATH_REFUSED")
    with open(absolute, "rb") as handle:
        data = handle.read()
    if _sha256(data) != approval["sha256"] or not _same_path(approval["strategy_path"], absolute):
        raise _Refusal("STRATEGY_NOT_APPROVED")
    modules = {}
    for path, digest in sorted(approval["local_modules"].items()):
        real = os.path.realpath(path)
        try:
            with open(real, "rb") as handle:
                matches = _sha256(handle.read()) == digest
        except OSError:
            matches = False
        if not matches:
            raise _Refusal("STRATEGY_NOT_APPROVED")
        modules[os.path.normcase(real)] = digest
    if approval["origin"] == "generated":
        raise _Refusal("STRATEGY_ORIGIN_GENERATED")
    return data, approval["origin"], modules


# ───────────────────────────── interpréteur enfant : exécution ─────────────────────────────

class _WorkerError(Exception):
    def __init__(self, origin, exc_type="", stage=""):
        super().__init__(origin)
        self.payload = {"origin": origin, "type": exc_type, "stage": stage}


_GUARD = {"armed": False, "events": set(), "blocked": [], "allowed": set(), "repo": None}


def _audit_hook(event, args):
    if not _GUARD["armed"]:
        return
    if event == "open":
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        if (isinstance(mode, str) and any(ch in mode for ch in "wax+")) or \
                (mode is None and isinstance(flags, int) and flags & _WRITE_FLAGS):
            _GUARD["events"].add("file_write")
    elif event in _SIDE_EFFECT_EVENTS:
        _GUARD["events"].add(event)


def _is_local(path, repo):
    """Vrai pour tout fichier de code qui n'est ni de la bibliothèque standard ni un paquet installé :
    fichiers du dépôt comme fichiers ajoutés au chemin de recherche par la stratégie. Un tel module
    doit être épinglé ou approuvé, et son hash est enregistré."""
    normal = os.path.normcase(os.path.realpath(path)).replace("\\", "/") + "/"
    if "/site-packages/" in normal:
        return False
    prefixes = {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix}
    return not any(_is_under(path, prefix) for prefix in prefixes if not _is_under(repo, prefix))


class _ImportGate:
    """Refuse l'import par nom de tout module du dépôt ni épinglé ni approuvé. Garde au mieux : un
    chargement direct de fichier la contourne (écrit dans chaque enregistrement)."""

    @staticmethod
    def find_spec(name, path=None, target=None):
        if not _GUARD["armed"]:
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None:
            return None
        places = [spec.origin] if spec.origin and spec.origin not in ("built-in", "frozen") else []
        places += list(spec.submodule_search_locations or [])
        for place in places:
            if _is_local(place, _GUARD["repo"]) and os.path.normcase(os.path.realpath(place)) not in _GUARD["allowed"]:
                _GUARD["blocked"].append(name)
                raise ImportError(f"module local non approuvé : {name}")
        return None


def _install_guards(request):
    repo = request["repo_root"]
    allowed = {os.path.normcase(os.path.realpath(os.path.join(repo, name + ".py"))) for name in PINNED_REPO_MODULES}
    _GUARD.update(repo=repo, allowed=allowed | set(request["approved_modules"]))
    sys.meta_path.insert(0, _ImportGate)
    sys.addaudithook(_audit_hook)


class _WarmUp:
    WARMUP = 1

    def reset(self):
        return None

    def prepare(self, df, params):
        return df

    def on_bar(self, i, df, context, params):
        return None


def _error_origin(exc):
    files = [entry.filename for entry in traceback.extract_tb(exc.__traceback__)]
    if _STRATEGY_FILENAME in files:
        return "strategy"
    return "engine" if any(os.path.basename(name) == "engine.py" for name in files) else "harness"


def _guarded(stage, function, *args):
    """Appelle du code de stratégie ou du moteur ; classe l'erreur par origine, sans message."""
    try:
        return function(*args)
    except _WorkerError:
        raise
    except Exception as exc:  # noqa: BLE001 - classification par origine, jamais d'état PASS
        if _GUARD["blocked"]:
            raise _WorkerError("import_not_approved", stage=stage) from None
        raise _WorkerError(_error_origin(exc), type(exc).__name__, stage) from None


def _strategy_loader(request):
    with open(request["strategy_copy"], "rb") as handle:
        data = handle.read()
    if _sha256(data) != request["strategy_sha256"]:
        raise _WorkerError("harness", "StrategyCopyAltered", "load")
    code = compile(data, _STRATEGY_FILENAME, "exec", dont_inherit=True)

    def load():
        # Comportement visé : celui du chargement de production par chemin de fichier (module nommé
        # `_opt_strategy`, non inscrit dans sys.modules), mais exécuté depuis les octets approuvés.
        # Écarts connus : `__file__` et `__spec__`. Équivalence non testée à A0.
        module = types.ModuleType("_opt_strategy")
        module.__file__ = _STRATEGY_FILENAME
        exec(code, module.__dict__)  # noqa: S102 - octets approuvés par l'opérateur, hash revérifié
        if _GUARD["blocked"]:
            raise _WorkerError("import_not_approved", stage="load")
        return module
    return load


def _plain(value):
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"__float__": repr(value)}
    return {"__type__": type(value).__name__}


def _freeze(signal):
    if signal is None:
        return None
    if not isinstance(signal, dict):
        return {"__invalid__": type(signal).__name__, "__truthy__": bool(signal)}
    return {str(key): _plain(value) for key, value in signal.items()}


def _is_decision(frozen):
    """Décision au sens du moteur : retour évalué vrai."""
    if frozen is None:
        return False
    return bool(frozen.get("__truthy__", True)) if "__invalid__" in frozen else bool(frozen)


def _trace_run(module, frame, params, run_backtest):
    strategy = module.Strategy()
    original = strategy.on_bar
    trace = []

    def recording(i, df, context, call_params):
        in_position = bool(context["in_pos"])
        signal = original(i, df, context, call_params)
        trace.append([int(i), in_position, _freeze(signal)])
        return signal
    try:
        strategy.on_bar = recording
    except AttributeError:
        raise _WorkerError("unsupported", "AttributeError", "instrument") from None
    run_backtest(frame, strategy, json.loads(json.dumps(params)))
    return trace


def _first_difference(expected, got):
    for left, right in zip(expected, got):
        if left != right:
            return min(left[0], right[0])
    longer = expected if len(expected) > len(got) else got
    return longer[min(len(expected), len(got))][0] if len(expected) != len(got) else None


def _is_numeric(array):
    return array.dtype.kind in "fiub"


def _same_values(left, right):
    if left.shape != right.shape:
        return False
    if _is_numeric(left) and _is_numeric(right):
        return bool(np.array_equal(left, right, equal_nan=left.dtype.kind == "f" or right.dtype.kind == "f"))
    return bool(pd.Series(list(left), dtype=object).equals(pd.Series(list(right), dtype=object)))


def _difference(left, right):
    """(première barre différente, écart absolu maximal ou None)."""
    if left.shape != right.shape:
        return None, None
    if _is_numeric(left) and _is_numeric(right):
        a, b = left.astype("float64"), right.astype("float64")
        bad = ~((a == b) | (np.isnan(a) & np.isnan(b)))
        if bad.ndim > 1:
            bad = bad.reshape(len(bad), -1).any(axis=1)
        with np.errstate(invalid="ignore"):
            gap = np.nanmax(np.abs(a - b)) if np.isfinite(a - b).any() else None
        return int(np.flatnonzero(bad)[0]), _finite(gap)
    for row, (x, y) in enumerate(zip(list(left), list(right))):
        if not (x is y or x == y or (x != x and y != y)):
            return row, None
    return None, None


def _nonempty_container(value):
    """Vrai pour un conteneur non vide ou un tableau sans dimension. Une liste irrégulière compte comme
    non vide : `np.ndim` lèverait une exception qui serait prise pour une panne du harnais."""
    if isinstance(value, np.ndarray):
        return value.ndim == 0 or len(value) > 0
    try:
        return len(value) > 0
    except TypeError:
        return True


def _snapshot(module, frame, params):
    """Tout ce que prepare() laisse de comparable : colonnes rendues et attributs par barre."""
    strategy = module.Strategy()
    strategy.reset()
    prepared = strategy.prepare(frame.copy(deep=False), json.loads(json.dumps(params)))
    size = len(frame)
    arrays, scalars, skipped, opaque = {}, {}, [], []
    if isinstance(prepared, pd.DataFrame) and len(prepared) == size:
        for column in prepared.columns:
            arrays[f"col:{column}"] = prepared[column].to_numpy()

    def walk(prefix, mapping, depth):
        for key in sorted(mapping, key=str):
            name, value = f"{prefix}{key}", mapping[key]
            if isinstance(value, (bool, int, float, np.number)):
                scalars[name] = value
            elif isinstance(value, np.ndarray) and value.ndim >= 1 and value.shape[0] == size:
                arrays[name] = value
            elif isinstance(value, (pd.Series, pd.Index)) and len(value) == size:
                arrays[name] = value.to_numpy()
            elif isinstance(value, pd.DataFrame) and len(value) == size:
                for column in value.columns:
                    arrays[f"{name}.{column}"] = value[column].to_numpy()
            elif isinstance(value, (list, tuple)) and len(value) == size and size > 0:
                arrays[name] = np.asarray(list(value), dtype=object)
            elif isinstance(value, dict) and depth < 2:
                walk(f"{name}.", value, depth + 1)
            elif isinstance(value, (np.ndarray, pd.Series, pd.Index, pd.DataFrame, list, tuple, dict, set,
                                    frozenset)) and _nonempty_container(value):
                opaque.append(name)  # conteneur de données que le contrôle ne sait pas comparer
            elif value is not None:
                skipped.append(name)
    walk("attr:", getattr(strategy, "__dict__", {}), 0)
    return arrays, scalars, skipped, opaque


def _prefix_control(load, frame, params, cuts):
    arrays, scalars, skipped, opaque = _guarded("prepare_full", lambda: _snapshot(load(), frame, params))
    inputs = [frame[column].to_numpy() for column in frame.columns]
    trivial = sorted(name for name, values in arrays.items()
                     if any(_same_values(values, source) for source in inputs))
    result = {"cuts": list(cuts), "compared_non_trivial": sorted(set(arrays) - set(trivial)), "trivial": trivial,
              "not_compared": sorted(skipped), "not_compared_data": sorted(opaque), "scalars": sorted(scalars),
              "mismatch": None, "scalar_mismatch": None}
    for cut in cuts:
        part, part_scalars, _, _ = _guarded("prepare_prefix", lambda: _snapshot(load(), frame.iloc[:cut], params))
        for name in sorted(arrays):
            reference = arrays[name][:cut]
            if name not in part:
                result["mismatch"] = {"cut": cut, "name": name, "bar": None, "max_abs_diff": None}
            elif not _same_values(part[name], reference):
                bar, gap = _difference(part[name], reference)
                result["mismatch"] = {"cut": cut, "name": name, "bar": bar, "max_abs_diff": gap}
            if result["mismatch"]:
                return result
        for name in sorted(set(scalars) & set(part_scalars)):
            left, right = part_scalars[name], scalars[name]
            if result["scalar_mismatch"] is None and not (left == right or (left != left and right != right)):
                result["scalar_mismatch"] = {"cut": cut, "name": name}
    return result


def _full_role(request, load, frame, run_backtest):
    params = request["params"]
    first_module = _guarded("load", load)
    first = _guarded("run", _trace_run, first_module, frame, params, run_backtest)
    second_module = _guarded("load", load)
    second = _guarded("run", _trace_run, second_module, frame, params, run_backtest)
    third = _guarded("run", _trace_run, second_module, frame, params, run_backtest)
    response = {"trace": first, "same_fresh": first == second, "same_module": second == third, "prefix": None}
    if response["same_fresh"] and response["same_module"]:
        try:
            response["prefix"] = _prefix_control(load, frame, params, request["prefix_cuts"])
        except _WorkerError as error:
            response["prefix"] = {"error": error.payload}
    return response


def _replay_role(request, load, frame, run_backtest):
    params, expected = request["params"], request["expected"]
    expected_bars = [entry[0] for entry in expected]
    horizon, amplitude = request["future_bars"], request["amplitude"]
    shared = _guarded("load", load)
    replays, first_seen = 0, None

    def replay(module, cut, variant):
        got = _trace_run(module, truncated_frame(frame, cut, horizon, amplitude, variant), params, run_backtest)
        return [entry for entry in got if entry[0] <= cut]

    def strategy_failure(exc, stage):
        """Nom du type si l'erreur naît dans la stratégie ; sinon lève l'erreur classée."""
        if _GUARD["blocked"]:
            raise _WorkerError("import_not_approved", stage=stage) from None
        if isinstance(exc, _WorkerError):
            raise exc
        if _error_origin(exc) != "strategy":
            raise _WorkerError(_error_origin(exc), type(exc).__name__, stage) from None
        return type(exc).__name__

    def verdict(cut, variant):
        """(violation ou None, trace du rejeu). Un écart est qualifié par un rejeu de contrôle sur
        un module neuf : état conservé entre exécutions, ou dépendance au futur."""
        wanted = expected[:bisect.bisect_right(expected_bars, cut)]
        got, raised = None, None
        try:
            got = replay(shared, cut, variant)
        except Exception as exc:  # noqa: BLE001
            raised = strategy_failure(exc, "replay")
        if raised is None and got == wanted:
            return None, got
        where = {"cut": cut, "variant": variant}
        try:
            fresh = replay(_guarded("load", load), cut, variant)
        except Exception as exc:  # noqa: BLE001
            strategy_failure(exc, "replay_control")
            return dict(where, bar=cut, kind="raises"), got
        if fresh == wanted:
            return dict(where, bar=cut if raised else _first_difference(wanted, got), kind="state_leak"), got
        return dict(where, bar=_first_difference(wanted, fresh), kind="future"), got

    for cut in sorted(request["bars"]):
        for variant in VARIANTS:
            violation, got = verdict(cut, variant)
            replays += 1
            if violation:
                return {"replays": replays, "violation": violation}
            if first_seen is None:
                first_seen = (cut, variant, got)
    if first_seen is not None:
        # Le premier rejeu est rejoué en dernier sur le même module : un écart signale un état conservé.
        cut, variant, got = first_seen
        again = _guarded("replay_again", replay, shared, cut, variant)
        replays += 1
        if again != got:
            return {"replays": replays, "violation": {"cut": cut, "variant": variant,
                                                       "bar": _first_difference(got, again), "kind": "state_leak"}}
    return {"replays": replays, "violation": None}


def execute_request(request):
    """Exécute une requête de contrôle dans le processus courant et rend une réponse sérialisable.

    C'est la fonction que lance chaque interpréteur enfant ; injectée comme lanceur, elle sert aux
    tests de logique (sans séparation de processus ni garde d'import)."""
    repo = request["repo_root"]
    if repo not in sys.path:
        sys.path.insert(0, repo)
    try:
        from engine import _add_market_time_columns, run_backtest
        frame = _add_market_time_columns(_read_frame_csv(request["frame_csv"]))
        load = _strategy_loader(request)
        if request.get("guards"):
            try:
                run_backtest(frame.iloc[:60], _WarmUp(), {})
            except Exception:  # noqa: BLE001 - simple amorçage des imports paresseux
                pass
            _GUARD["armed"] = True
        role = _full_role if request["role"] == "full" else _replay_role
        response = dict(role(request, load, frame, run_backtest), status="ok")
        if _GUARD["blocked"]:  # import refusé puis avalé par la stratégie : chemin différent de la production
            raise _WorkerError("import_not_approved", stage="lazy")
    except _WorkerError as error:
        response = {"status": "error", "error": error.payload}
    except Exception as exc:  # noqa: BLE001 - une erreur du harnais ne donne jamais PASS
        response = {"status": "error", "error": {"origin": "harness", "type": type(exc).__name__, "stage": "setup"}}
    finally:
        _GUARD["armed"] = False
    response["audit"] = sorted(_GUARD["events"])
    if request.get("guards"):
        response["environment"] = _environment_report(repo)
    return response


def _environment_report(repo):
    versions, local = {}, {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if not path or name == "__main__":
            continue
        if _is_local(path, repo):
            with open(path, "rb") as handle:
                digest = _sha256(handle.read())
            real = os.path.realpath(path)
            if _is_under(real, repo):
                key = os.path.relpath(real, os.path.realpath(repo)).replace("\\", "/")
            else:  # hors dépôt : jamais de chemin dans l'enregistrement
                key = f"external/{digest[:12]}/{os.path.basename(real)}"  # contenu dans la clé : pas de collision
            local[key] = digest
        elif "." not in name and isinstance(getattr(module, "__version__", None), str) \
                and "site-packages" in path.replace("\\", "/"):
            versions[name] = module.__version__
    return {"third_party": versions, "local_modules": local, "python": sys.version.split()[0]}


def _worker_main(request_path):
    io_dir = os.path.dirname(os.path.abspath(request_path))
    with open(os.path.join(io_dir, "child.pid"), "w", encoding="ascii") as handle:
        handle.write(str(os.getpid()))
    with open(request_path, "rb") as handle:
        request = json.loads(handle.read().decode("utf-8"))
    request["guards"] = True
    _install_guards(request)
    response = execute_request(request)
    _write_exclusive(os.path.join(io_dir, "response.json"), canonical_json(response))
    return 0


# ───────────────────────────── harnais : lancement des enfants ─────────────────────────────

def _write_exclusive(path, data):
    """Création exclusive durable. Jamais d'écrasement."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _tree_files(*roots):
    return sorted(os.path.join(base, name) for root in roots for base, _dirs, files in os.walk(root) for name in files)


def _refuse_json_constant(name):
    raise ValueError(f"constante JSON non standard : {name}")


def _read_response_file(path):
    """Lit la réponse d'un enfant : taille plafonnée, JSON standard seulement (`NaN`, `Infinity` et
    `-Infinity` refusés), jamais d'exception (illisible = None)."""
    try:
        if os.path.getsize(path) > MAX_RESPONSE_BYTES:
            return None
        with open(path, "rb") as handle:
            return json.loads(handle.read().decode("utf-8"), parse_constant=_refuse_json_constant)
    except (OSError, ValueError, RecursionError):
        return None


class _ChildRunner:
    """Un interpréteur neuf par requête : environnement en liste blanche, répertoires vides,
    délai, arrêt de l'arbre de processus. Séparation de processus, pas confinement."""

    def __init__(self, run_dir, python_exe, timeout_s):
        self._run_dir, self._python, self._timeout = run_dir, python_exe, timeout_s
        self._counter = itertools.count()

    @staticmethod
    def _reap(process):
        """Attente bornée après un arrêt ; repli sur Popen.kill() si l'arrêt de l'arbre a échoué."""
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pass  # processus inarrêtable : `survivors` le signalera, jamais d'attente sans fin

    def _attempt(self, request):
        base = os.path.join(self._run_dir, f"child-{next(self._counter):03d}")
        io_dir, sandbox = os.path.join(base, "io"), [os.path.join(base, n) for n in ("cwd", "tmp", "home")]
        for path in [io_dir] + sandbox:
            os.makedirs(path)
        request_path = os.path.join(io_dir, "request.json")
        _write_exclusive(request_path, canonical_json(request))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # `-s -P -B` et non `-I` : l'environnement est déjà une liste blanche, et `-I` ignorerait la
        # graine de hachage fixée. Sorties standard fermées : plafonnées par construction.
        process = subprocess.Popen(  # noqa: S603 - arguments en liste, sans interpréteur de commandes
            [self._python, "-s", "-P", "-B", os.path.join(_REPO_ROOT, "research_admission.py"), "--worker",
             request_path],
            cwd=sandbox[0], env=build_child_environment(base), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
            start_new_session=os.name != "nt")
        timed_out = False
        try:
            try:
                process.wait(timeout=self._timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(process.pid)  # l'identifiant vient du harnais, jamais d'un fichier du bac de travail
                self._reap(process)
        except BaseException:  # interruption au clavier, arrêt demandé : jamais d'enfant laissé vivant
            _kill_tree(process.pid)
            self._reap(process)
            raise
        survivors = False
        try:  # contrôle seulement : aucun arrêt n'est lancé sur un identifiant lu dans un fichier
            with open(os.path.join(io_dir, "child.pid"), encoding="ascii") as handle:
                survivors = not _wait_dead(int(handle.read()))
        except (OSError, ValueError):
            pass
        response = None
        if not timed_out and process.returncode == 0:
            response = _read_response_file(os.path.join(io_dir, "response.json"))
        malformed_error = isinstance(response, dict) and response.get("status") == "error" and not (
            isinstance(response.get("error"), dict) and isinstance(response["error"].get("origin"), str))
        if not isinstance(response, dict) or response.get("status") not in ("ok", "error") or malformed_error:
            response = {"status": "error", "error": {"origin": "timeout" if timed_out else "unreadable",
                                                     "type": "", "stage": "child"}, "audit": []}
        response["side_effects"] = bool(_tree_files(*sandbox))
        response["survivors"] = survivors
        return response

    def __call__(self, request):
        first = self._attempt(request)
        if not (first["status"] == "error" and first["error"]["origin"] in ("timeout", "unreadable")):
            return first
        response = self._attempt(request)  # une seule nouvelle tentative ; les indices de la première restent
        response["side_effects"] = response["side_effects"] or first["side_effects"]
        response["survivors"] = response["survivors"] or first["survivors"]
        return response


_ERROR_CODES = {"strategy": "STRATEGY_RAISES", "engine": "ENGINE_ERROR", "timeout": "HARNESS_TIMEOUT",
                "import_not_approved": "STRATEGY_IMPORT_NOT_APPROVED", "unsupported": "UNSUPPORTED_STRATEGY_CONTRACT"}


_PREFIX_NAME_LISTS = ("compared_non_trivial", "trivial", "not_compared", "not_compared_data", "scalars")


def _index(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _string_map(value):
    return isinstance(value, dict) and all(isinstance(item, str) for item in value.values())


def _environment_well_formed(environment):
    return isinstance(environment, dict) and set(environment) == {"third_party", "local_modules", "python"} \
        and _string_map(environment["third_party"]) and _string_map(environment["local_modules"]) \
        and isinstance(environment["python"], str)


def _prefix_well_formed(prefix):
    if prefix is None:
        return True
    if not isinstance(prefix, dict):
        return False
    if "error" in prefix:
        return set(prefix) == {"error"} and isinstance(prefix["error"], dict) \
            and isinstance(prefix["error"].get("origin"), str)
    mismatch, scalar = prefix.get("mismatch"), prefix.get("scalar_mismatch")
    gap = mismatch.get("max_abs_diff") if isinstance(mismatch, dict) else None
    # Écarts : clés exactes de `_prefix_control` ; un écart vide ne vaut jamais « aucun écart ».
    return set(prefix) == set(_PREFIX_NAME_LISTS) | {"cuts", "mismatch", "scalar_mismatch"} \
        and isinstance(prefix["cuts"], list) and all(_index(cut) for cut in prefix["cuts"]) \
        and all(_strings(prefix[key]) for key in _PREFIX_NAME_LISTS) \
        and (mismatch is None or (isinstance(mismatch, dict) and set(mismatch) == {"cut", "name", "bar", "max_abs_diff"}
                                  and _index(mismatch["cut"]) and isinstance(mismatch["name"], str)
                                  and (mismatch["bar"] is None or _index(mismatch["bar"]))
                                  and (gap is None or (isinstance(gap, (int, float)) and not isinstance(gap, bool))))) \
        and (scalar is None or (isinstance(scalar, dict) and set(scalar) == {"cut", "name"}
                                and _index(scalar["cut"]) and isinstance(scalar["name"], str)))


def _trace_well_formed(trace):
    """Entrées [barre, en position, signal figé] ; barres entières positives, jamais décroissantes (le
    moteur peut appeler la stratégie deux fois à la même barre, après une sortie)."""
    if not isinstance(trace, list):
        return False
    previous = 0
    for entry in trace:
        if not (isinstance(entry, list) and len(entry) == 3 and _index(entry[0]) and entry[0] >= previous
                and isinstance(entry[1], bool) and (entry[2] is None or isinstance(entry[2], dict))):
            return False
        previous = entry[0]
    return True


def _well_formed(request, response):
    """Une réponse « ok » doit porter la couverture demandée, selon un schéma strict : sinon elle ne
    vaut rien. La réponse a déjà été normalisée en JSON standard par `_call`."""
    try:
        if "environment" in response and not _environment_well_formed(response["environment"]):
            return False
        if response["status"] == "error":
            return isinstance(response["error"], dict) and isinstance(response["error"].get("origin"), str)
        if request["role"] == "full":
            prefix = response["prefix"]
            return isinstance(response["same_fresh"], bool) and isinstance(response["same_module"], bool) \
                and _trace_well_formed(response["trace"]) and _prefix_well_formed(prefix) \
                and (prefix is None or "error" in prefix or prefix["cuts"] == request["prefix_cuts"])  # coupes demandées
        violation, replays = response["violation"], response["replays"]
        requested = len(VARIANTS) * len(request["bars"]) + 1  # tous les rejeux, plus le premier rejoué en dernier
        if not _index(replays):
            return False
        if violation is None:
            return replays == requested
        return 1 <= replays <= requested and isinstance(violation, dict) \
            and violation["kind"] in ("future", "state_leak", "raises") \
            and violation["variant"] in VARIANTS and all(_index(violation[k]) for k in ("cut", "bar"))
    except (KeyError, TypeError):
        return False


def _as_standard_json(response):
    """Copie de la réponse relue depuis son JSON canonique, ou None si elle n'en a pas : flottant non fini,
    entier trop long, caractère non encodable, clé ou objet non sérialisable, imbrication excessive. Le
    parent ne travaille ensuite que sur cette copie : rien en aval ne peut lever en la sérialisant."""
    try:
        return json.loads(canonical_json(response).decode("utf-8"), parse_constant=_refuse_json_constant)
    except (TypeError, ValueError, RecursionError):
        return None


def _call(runner, request):
    """Appelle le lanceur ; rend (réponse ou None, codes INCONCLUSIVE)."""
    try:
        response = runner(request)
    except Exception:  # noqa: BLE001 - lanceur indisponible : jamais PASS
        return None, ["ISOLATION_UNAVAILABLE"]
    if isinstance(response, dict):
        response = _as_standard_json(response)
    if not isinstance(response, dict) or response.get("status") not in ("ok", "error"):
        return None, ["ISOLATION_UNAVAILABLE"]
    if not _well_formed(request, response):
        return None, ["ISOLATION_UNAVAILABLE"]
    codes = []
    pinned = {name + ".py" for name in PINNED_REPO_MODULES}
    loaded = (response.get("environment") or {}).get("local_modules") or {}
    if any(name not in pinned and digest not in request["approved_digests"] for name, digest in loaded.items()):
        codes.append("STRATEGY_IMPORT_NOT_APPROVED")  # module local chargé dont les octets ne sont pas approuvés
    if response.get("side_effects") or response.get("audit"):
        codes.append("SIDE_EFFECT_DETECTED")
    if response.get("survivors"):
        codes.append("ISOLATION_UNAVAILABLE")
    if response["status"] == "error":
        codes.append(_ERROR_CODES.get(response.get("error", {}).get("origin"), "ISOLATION_UNAVAILABLE"))
    return response, codes


# ───────────────────────────── contrat de signal ─────────────────────────────

def _positive_number(value):
    """Nombre strictement positif et fini une fois lu comme flottant, comme le lit le moteur : un
    entier hors de portée des flottants (`10**400`) n'est pas un nombre fini du contrat."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value > 0
    except OverflowError:
        return False


def _signal_problem(frozen):
    if "__invalid__" in frozen:
        return "signal_not_a_mapping"
    if any(isinstance(value, dict) for value in frozen.values()):
        return "value_not_a_finite_scalar"
    action = frozen.get("action")
    if action not in ("enter", "exit"):
        return "unknown_action"
    if action == "enter":
        if frozen.get("direction") not in ("long", "short"):
            return "direction"
        if not _positive_number(frozen.get("stop_pct")) or not _positive_number(frozen.get("target_pct")):
            return "stop_or_target"
        if "nb_contracts" in frozen and not _positive_number(frozen["nb_contracts"]):
            return "size"
    return None


def _signal_check(groups):
    counts, problem = {}, None
    for group in groups:
        for bar, _in_position, frozen in group["trace"]:
            if not _is_decision(frozen):
                continue
            issue = _signal_problem(frozen)
            kind = "invalid" if issue else (f"enter_{frozen['direction']}" if frozen["action"] == "enter" else "exit")
            counts[kind] = counts.get(kind, 0) + 1
            if issue and problem is None:
                problem = {"frame": group["frame"], "param_set": group["param_set"], "bar": bar, "reason": issue}
    coverage = {"decisions_by_type": counts}
    if problem:
        return _check("signal_contract", "FAIL", ["SIGNAL_INVALID"], problem, coverage)
    if not counts:
        return _check("signal_contract", "INCONCLUSIVE", ["NO_DECISION_EXERCISED"], coverage=coverage)
    return _check("signal_contract", "PASS", coverage=coverage)


# ───────────────────────────── pré-vol ─────────────────────────────

def _base_record(protocol, checks, refusal=None):
    return {"semantics_version": SEMANTICS_VERSION, "record_type": "ExperimentalAdmissionRecord",
            "evidence_level": "EXPERIMENTAL", "activation": ACTIVATION, "notice": NOTICE, "protocol": protocol,
            "checks": checks, "decision": compute_decision(checks), "refusal": refusal, "subject": None, "frames": [],
            "param_sets": [], "not_covered": list(NOT_COVERED), "not_prevented": list(NOT_PREVENTED),
            "not_implemented_at_a0": list(NOT_IMPLEMENTED_AT_A0), "admission_id": None}


def _record_id(record):
    return _sha256(canonical_json({key: value for key, value in record.items() if key != "admission_id"}))


def verify_record(record):
    """Recalcule un enregistrement relu. Rend (cohérent, problèmes). N'authentifie rien : un
    enregistrement écrit à la main et cohérent avec lui-même est indétectable."""
    problems = []
    try:
        if record.get("semantics_version") != SEMANTICS_VERSION:
            problems.append("semantics_version")
        if record.get("decision") != _final_decision(record.get("checks"), record.get("protocol"),
                                                      record.get("subject")):
            problems.append("decision")
        if record.get("refusal") is not None and record.get("decision") != "NOT_ADMITTED":
            problems.append("refusal")
        if record.get("admission_id") is not None and record["admission_id"] != _record_id(record):
            problems.append("admission_id")
        if record.get("admission_id") is None and record.get("refusal") is None:
            problems.append("admission_id")
        expected = {"notice": NOTICE, "activation": ACTIVATION, "evidence_level": "EXPERIMENTAL",
                    "not_covered": list(NOT_COVERED), "not_prevented": list(NOT_PREVENTED),
                    "not_implemented_at_a0": list(NOT_IMPLEMENTED_AT_A0)}
        problems += [key for key, value in expected.items() if record.get(key) != value]
        if not isinstance(record.get("protocol"), dict) or "reduced" not in record["protocol"]:
            problems.append("protocol")
        else:  # `reduced` se recalcule à partir des valeurs du protocole
            numbers = {key: value for key, value in record["protocol"].items() if key not in ("reduced", "variants")}
            if _resolve_protocol(numbers)["reduced"] != record["protocol"]["reduced"]:
                problems.append("protocol")
        if record.get("refusal") is None and not isinstance(record.get("subject"), dict):
            problems.append("subject")
    except (AttributeError, TypeError, ValueError):
        problems.append("unreadable")
    return (not problems, problems)


def _determinism_phase(runner, common, frames, param_sets, protocol):
    groups, codes, fail, coordinates = [], [], [], {}
    for frame_index, item in enumerate(frames):
        for set_index, params in enumerate(param_sets):
            request = dict(common, role="full", params=params, frame_csv=item["csv"],
                           prefix_cuts=_prefix_cuts(item["frame"], item["sha256"], protocol["prefix_cuts"]))
            response, group_codes = _call(runner, request)
            where = {"frame": frame_index, "param_set": set_index}
            if response is not None and response["status"] == "ok" and not group_codes:
                if not response["same_fresh"]:
                    fail.append("STRATEGY_NOT_DETERMINISTIC")
                elif not response["same_module"]:
                    fail.append("STATE_LEAKS_BETWEEN_RUNS")
            elif not group_codes:
                group_codes = ["ISOLATION_UNAVAILABLE"]
            codes += group_codes
            if fail or group_codes:
                coordinates = where
                break
            groups.append(dict(where, trace=response["trace"], prefix=response["prefix"],
                               environment=response.get("environment")))
        if fail or codes:
            break
    coverage = {"groups_run": len(groups) + (1 if fail or codes else 0), "runs_per_group": 3,
                "groups_planned": len(frames) * len(param_sets)}
    if fail:
        return _check("determinism", "FAIL", sorted(set(fail)), coordinates, coverage), groups
    if codes:
        return _check("determinism", "INCONCLUSIVE", sorted(set(codes)), coordinates, coverage), groups
    return _check("determinism", "PASS", coverage=coverage), groups


def _replay_phase(runner, common, frames, param_sets, protocol, groups, run_dir):
    horizon = protocol["future_bars"]
    remaining = protocol["max_replays"]
    summaries, soft, violation, raised_at = [], [], None, None
    tested = [0] * len(param_sets)
    budget_hit = [False] * len(param_sets)
    for group in groups:
        item = frames[group["frame"]]
        frame, trace = item["frame"], group["trace"]
        summary = {"frame": group["frame"], "param_set": group["param_set"], "tested_bars": 0, "tested_decisions": 0,
                   "bars_without_decision": 0, "replays": 0, "trace_windows": [], "independent_windows": [],
                   "sparse_bars": 0, "budget_exhausted": False}
        summaries.append(summary)
        last_bar = min(trace[-1][0], len(frame) - 1 - horizon) if trace else -1
        if not trace or last_bar < trace[0][0]:
            soft.append("EXCERPT_TOO_SHORT_FOR_WARMUP")
            continue
        decisions = sorted({entry[0] for entry in trace if _is_decision(entry[2])})
        # Un rejeu par barre et par variante, plus le premier rejoué en dernier : ce rejeu final est
        # réservé, le plafond `max_replays` n'est jamais dépassé.
        plan = plan_tested_bars(decision_bars=decisions, first_bar=trace[0][0], last_bar=last_bar,
                                fingerprint=item["sha256"], protocol=protocol,
                                max_bars=max(0, remaining - 1) // len(VARIANTS))
        summary.update(trace_windows=plan["trace_windows"], independent_windows=plan["independent_windows"],
                       sparse_bars=len(plan["sparse"]), tested_bars=len(plan["bars"]))
        if plan["budget_exhausted"] or not plan["bars"]:
            # Obligation du groupe (fenêtres et barres éparses du protocole) non remplie : jamais PASS,
            # quel que soit le total des autres groupes.
            budget_hit[group["param_set"]] = True
            summary["budget_exhausted"] = True
            soft.append("BUDGET_EXCEEDED")
        if not plan["bars"]:
            continue
        # L'interpréteur des rejeux ne reçoit qu'un extrait déjà tronqué : au-delà de la dernière
        # barre testée, seuls les horodatages subsistent.
        visible = frame.iloc[:plan["bars"][-1] + 1 + horizon].copy()
        visible.iloc[plan["bars"][-1] + 1:, [visible.columns.get_loc(c) for c in VALUE_COLUMNS]] = 0.0
        csv_path = os.path.join(run_dir, "frames", f"replay-{group['frame']}-{group['param_set']}.csv")
        _write_exclusive(csv_path, frame_csv_bytes(visible))
        request = dict(common, role="replay", params=param_sets[group["param_set"]], frame_csv=csv_path,
                       bars=plan["bars"], expected=trace, future_bars=horizon, amplitude=item["amplitude"])
        response, codes = _call(runner, request)
        if response is None or response["status"] != "ok":
            soft += codes or ["ISOLATION_UNAVAILABLE"]
            continue
        soft += codes
        remaining -= response["replays"]
        summary["replays"] = response["replays"]
        if response["violation"]:
            violation = dict(response["violation"], frame=group["frame"], param_set=group["param_set"])
            if violation["kind"] != "raises":
                break
            # Exception de la stratégie au rejeu, reproduite sur un module neuf. Sans rejeu de contrôle
            # sur suffixe réel (non implémenté à A0), on ne sait pas l'attribuer à l'absence du futur.
            soft.append("STRATEGY_RAISES")
            raised_at = {key: violation[key] for key in ("frame", "param_set", "cut", "variant", "bar")}
            violation = None
            continue
        if not codes:
            in_windows = {b for w in plan["trace_windows"] + plan["independent_windows"] for b in range(*w)}
            summary["tested_decisions"] = plan["tested_decisions"]
            summary["bars_without_decision"] = len(in_windows) - plan["tested_decisions"]
            tested[group["param_set"]] += plan["tested_decisions"]
    exercised = _exercised_param_sets(tested, protocol["min_decisions"])
    # Deux jeux dont les traces sont égales sur tous les extraits n'ont pas exercé deux comportements :
    # ils ne comptent qu'une fois (jeux égaux en valeur, clé inutilisée, 10 contre 10.0).
    signatures = {}
    for k in exercised:
        key = canonical_json(_numbers_as_floats([g["trace"] for g in sorted(groups, key=lambda g: g["frame"])
                                                 if g["param_set"] == k]))
        signatures.setdefault(key, []).append(k)
    indistinguishable = [members for members in signatures.values() if len(members) > 1]
    distinct = sorted(members[0] for members in signatures.values())
    coverage = {"groups": summaries, "exercised_param_sets": exercised,
                "not_exercised_param_sets": [k for k in range(len(param_sets)) if k not in exercised],
                "indistinguishable_param_sets": indistinguishable, "distinct_exercised_param_sets": distinct,
                "tested_decisions_by_param_set": list(tested),
                "replays": sum(s["replays"] for s in summaries), "max_replays": protocol["max_replays"],
                "variants": list(VARIANTS), "min_decisions_floor": protocol["min_decisions"]}
    if violation:
        kinds = {"future": "DECISION_DEPENDS_ON_FUTURE", "state_leak": "STATE_LEAKS_BETWEEN_RUNS"}
        coordinates = {key: violation[key] for key in ("frame", "param_set", "cut", "variant", "bar")}
        return _check("decision_replay", "FAIL", [kinds[violation["kind"]]], coordinates, coverage)
    if 0 not in exercised:
        soft.append("BUDGET_EXCEEDED" if budget_hit[0] else "NO_DECISION_EXERCISED")
    if len(exercised) < MIN_EXERCISED_SETS:
        soft.append("PARAM_SETS_NOT_EXERCISED")
        if any(budget_hit):
            soft.append("BUDGET_EXCEEDED")
    elif len(distinct) < MIN_EXERCISED_SETS:
        soft.append("PARAM_SETS_NOT_DISTINCT")
    if soft:
        return _check("decision_replay", "INCONCLUSIVE", sorted(set(soft)), raised_at, coverage)
    return _check("decision_replay", "PASS", coverage=coverage)


def _numbers_as_floats(value):
    """Copie où tout entier (hors booléen) devient flottant : `2` et `2.0` ne se distinguent pas."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        try:
            return float(value)
        except OverflowError:
            return value  # entier hors de portée des flottants : laissé tel quel, jamais une exception
    if isinstance(value, list):
        return [_numbers_as_floats(item) for item in value]
    if isinstance(value, dict):
        return {key: _numbers_as_floats(item) for key, item in value.items()}
    return value


def _exercised_param_sets(tested, floor):
    """Jeux dont le nombre de décisions testées atteint le plancher (inclus) ; zéro ne compte jamais."""
    return [k for k, count in enumerate(tested) if count >= floor and count > 0]


def _prefix_check(groups, replay_failed):
    names = {"compared_non_trivial": set(), "trivial": set(), "not_compared": set(), "not_compared_data": set(),
             "scalars": set()}
    cuts, soft, mismatch, scalar = {}, [], None, None
    for group in groups:
        where = {"frame": group["frame"], "param_set": group["param_set"]}
        result = group["prefix"] or {"error": {"origin": "harness"}}
        if "error" in result:
            soft.append(_ERROR_CODES.get(result["error"].get("origin"), "ISOLATION_UNAVAILABLE"))
            continue
        for key, bucket in names.items():
            bucket.update(result[key])
        cuts[str(group["frame"])] = result["cuts"]
        if not result["cuts"]:
            soft.append("EXCERPT_TOO_SHORT_FOR_WARMUP")
        if result["mismatch"] and mismatch is None:
            mismatch = dict(where, **result["mismatch"])
        if result["scalar_mismatch"] and scalar is None:
            scalar = dict(where, **result["scalar_mismatch"])
    vacuous = not names["compared_non_trivial"]
    coverage = dict({key: sorted(bucket) for key, bucket in names.items()}, cuts=cuts, vacuous=vacuous,
                    comparison="bit à bit, NaN égal à NaN ; ne voit que ce que prepare() laisse")
    if mismatch:
        coverage["max_abs_diff"] = mismatch.pop("max_abs_diff")
        if replay_failed:
            return _check("prepare_prefix", "FAIL", ["PREPARE_USES_FUTURE"], mismatch, coverage)
        return _check("prepare_prefix", "INCONCLUSIVE", ["PREPARE_NOT_BITWISE_STABLE"], mismatch, coverage)
    if scalar:
        soft.append("PREPARE_SCALAR_DEPENDS_ON_LENGTH")
    if names["not_compared_data"]:
        # prepare() laisse des données que le contrôle ne sait pas comparer : jamais PASS, même par vacuité
        soft.append("PREPARE_STATE_NOT_COMPARABLE")
    if soft:
        return _check("prepare_prefix", "INCONCLUSIVE", sorted(set(soft)), scalar, coverage)
    return _check("prepare_prefix", "PASS", ["NO_NON_TRIVIAL_ARRAY_EXPOSED"] if vacuous else [], coverage=coverage)


def _frames_share_rows(frames):
    """Vrai si deux extraits portent au moins une barre identique (horodatage et valeurs), ou si la même
    suite d'au moins `OVERLAP_RUN_BARS` barres consécutives de mêmes valeurs apparaît à deux positions,
    quels que soient les horodatages : copie décalée dans le temps, entre deux extraits ou à l'intérieur
    d'un même extrait. Une suite constante (barres toutes identiques, comme des barres de remplissage)
    ne compte jamais : elle ne distingue aucune position."""
    seen, runs = set(), {}
    for index, frame in enumerate(frames):
        try:  # lignes du CSV canonique : le fuseau horaire est écarté, une copie avec fuseau est reconnue
            # Valeurs lues en float64, comme le harnais les relit : une copie qui ne diffère que par le
            # type (volume entier contre flottant) porte la même preuve.
            normal = frame.loc[:, list(CANONICAL_COLUMNS)].astype({column: "float64" for column in VALUE_COLUMNS})
            rows = set(frame_csv_bytes(normal).splitlines()[1:])
            values = normal.loc[:, list(VALUE_COLUMNS)].to_csv(index=False, header=False,
                                                                lineterminator="\n").splitlines()
        except (KeyError, AttributeError, TypeError, ValueError):
            continue  # extrait mal formé : le contrôle de données le signale, il n'est pas comparé ici
        if seen & rows:
            return True
        seen |= rows
        for start in range(len(values) - OVERLAP_RUN_BARS + 1):
            run = tuple(values[start:start + OVERLAP_RUN_BARS])
            if len(set(run)) == 1:
                continue
            first = runs.setdefault(run, (index, start))
            if first[0] != index or start - first[1] >= OVERLAP_RUN_BARS:  # deux positions disjointes
                return True
    return False


def _persist(output_dir, record):
    folder = os.path.join(output_dir, "admissions")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, record["admission_id"] + ".json")
    data = canonical_json(record)
    try:
        _write_exclusive(path, data)
    except FileExistsError:
        with open(path, "rb") as handle:
            if handle.read() != data:
                raise FileExistsError(f"enregistrement présent et différent, jamais écrasé : {path}") from None
        return
    try:  # horodatage de création : fichier voisin, hors identité
        _write_exclusive(path[:-5] + ".created.txt", datetime.now(timezone.utc).isoformat().encode("ascii"))
    except FileExistsError:
        pass


def _normalised_param_sets(param_sets):
    """Copie JSON canonique des jeux de paramètres ; lève ValueError (ou TypeError si ce n'est pas une
    liste) pour une liste vide, un jeu qui n'est pas un dict, une valeur non finie ou un doublon."""
    param_sets = json.loads(canonical_json(list(param_sets)).decode("utf-8"))
    if not param_sets or not all(isinstance(p, dict) for p in param_sets):
        raise ValueError("au moins un jeu de paramètres (dict) et un extrait sont requis")
    if len({canonical_json(p) for p in param_sets}) != len(param_sets):
        raise ValueError("jeux de paramètres dupliqués : un même jeu ne compte pas deux fois")
    return param_sets


def run_preflight(*, strategy_path, approval_path, param_sets, frames, output_dir, protocol=None, split_plan=None,
                  python_exe=None, runner=None, keep_work=False):
    """Pré-vol expérimental. Rend l'enregistrement (dict) ; l'écrit sous `<output_dir>/admissions/`
    sauf en cas de refus. Diagnostic seulement : rien n'est bloqué, rien n'est branché.

    `runner` : lanceur injecté pour les tests de logique ; par défaut, un interpréteur enfant neuf
    par requête. `frames` : liste de {"frame": DataFrame aux colonnes canoniques,
    "origin": "synthetic" | "train_excerpt"}."""
    protocol = _resolve_protocol(protocol)
    param_sets = _normalised_param_sets(param_sets)
    if not frames:
        raise ValueError("au moins un jeu de paramètres (dict) et un extrait sont requis")

    def refuse(code):
        return _base_record(protocol, [_not_run(name) for name in CHECK_NAMES], refusal=code)

    if output_dir_refusal(output_dir) or _free_bytes(output_dir) < MIN_FREE_BYTES:
        return refuse("OUTPUT_DIR_REFUSED")
    if not _copy_on_write_active() or (runner is None and not _tree_kill_available()):
        return refuse("ISOLATION_UNAVAILABLE")
    try:
        source, origin, approved_modules = _read_approved_strategy(strategy_path, approval_path, output_dir)
    except _Refusal as refusal:
        return refuse(refusal.code)
    if any(not isinstance(item, dict) or item.get("origin") not in FRAME_ORIGINS for item in frames):
        return refuse("DATA_ZONE_FORBIDDEN")
    data_checks = [check_market_frame(item.get("frame"), item["origin"], split_plan, item.get("declared_sha256"))
                   for item in frames]  # extrait absent : contrôle de données en échec, jamais une exception
    if any("DATA_ZONE_FORBIDDEN" in check["codes"] for check in data_checks):
        return refuse("DATA_ZONE_FORBIDDEN")
    if _frames_share_rows([item["frame"] for item, check in zip(frames, data_checks) if check["state"] != "FAIL"]):
        return refuse("DATA_FRAMES_OVERLAP")  # le plancher compterait deux fois les mêmes décisions
    engine_path = os.path.join(_REPO_ROOT, "engine.py")
    interpreter = os.path.abspath(python_exe or sys.executable)
    try:
        engine_hash = normalised_sha256(engine_path)
        with open(interpreter, "rb") as handle:
            interpreter_hash = _sha256(handle.read())
    except OSError:
        return refuse("ISOLATION_UNAVAILABLE")

    states = [check["state"] for check in data_checks]
    data_state = "FAIL" if "FAIL" in states else ("INCONCLUSIVE" if "INCONCLUSIVE" in states else "PASS")
    checks = {name: _not_run(name) for name in CHECK_NAMES}
    checks["data"] = _check("data", data_state, sorted({code for check in data_checks for code in check["codes"]}),
                            coverage={"frames": [check["coverage"] for check in data_checks]})
    record = _base_record(protocol, [])
    record["param_sets"] = param_sets
    record["frames"] = [{"origin": c["coverage"]["origin"], "n_bars": c["coverage"]["n_bars"],
                         "sha256": c["coverage"].get("sha256")} for c in data_checks]
    record["subject"] = {
        "strategy_sha256": _sha256(source), "origin_declared": origin, "engine_sha256": engine_hash,
        "approved_local_modules": sorted(approved_modules.values()), "loaded_local_modules": {},
        "param_sets_sha256": _sha256(canonical_json(param_sets)), "python": sys.version.split()[0],
        "third_party": {"numpy": np.__version__, "pandas": pd.__version__}, "threads": 1,
        "interpreter_sha256": interpreter_hash,
        "runner": "child_interpreters" if runner is None else "injected_in_process",
        "synthetic_only": all(item["origin"] == "synthetic" for item in frames)}

    work_root = os.path.join(output_dir, "work")
    os.makedirs(work_root, exist_ok=True)
    run_dir = tempfile.mkdtemp(prefix="run-", dir=work_root)
    try:
        if data_state == "PASS":
            os.makedirs(os.path.join(run_dir, "frames"))
            strategy_copy = os.path.join(run_dir, "strategy_copy.py")
            _write_exclusive(strategy_copy, source)
            prepared = []
            for index, item in enumerate(frames):
                frame = item["frame"].loc[:, list(CANONICAL_COLUMNS)].reset_index(drop=True)
                csv_path = os.path.join(run_dir, "frames", f"frame-{index}.csv")
                _write_exclusive(csv_path, frame_csv_bytes(frame))
                prepared.append({"frame": _read_frame_csv(csv_path), "csv": csv_path,
                                 "sha256": data_checks[index]["coverage"]["sha256"],
                                 "amplitude": excerpt_amplitude(frame)})
            common = {"repo_root": _REPO_ROOT, "strategy_copy": strategy_copy,
                      "strategy_sha256": _sha256(source), "approved_modules": sorted(approved_modules),
                      "approved_digests": sorted(approved_modules.values())}
            if runner is None:
                runner = _ChildRunner(run_dir, interpreter, protocol["timeout_s"])
            checks["determinism"], groups = _determinism_phase(runner, common, prepared, param_sets, protocol)
            if checks["determinism"]["state"] == "PASS":
                checks["decision_replay"] = _replay_phase(runner, common, prepared, param_sets, protocol, groups,
                                                          run_dir)
                checks["prepare_prefix"] = _prefix_check(groups, checks["decision_replay"]["state"] == "FAIL")
                checks["signal_contract"] = _signal_check(groups)
            reports = [g["environment"] for g in groups if g.get("environment")]
            if reports:
                record["subject"]["third_party"] = reports[0]["third_party"]
                record["subject"]["loaded_local_modules"] = reports[0]["local_modules"]
                record["subject"]["python"] = reports[0]["python"]
            if normalised_sha256(engine_path) != engine_hash and checks["determinism"]["state"] != "FAIL":
                codes = (set(checks["determinism"]["codes"]) - {"NOT_RUN"}) | {"ENGINE_ERROR"}
                checks["determinism"] = _check("determinism", "INCONCLUSIVE", sorted(codes),
                                               coverage=checks["determinism"]["coverage"])
        record["checks"] = [checks[name] for name in CHECK_NAMES]
        record["decision"] = _final_decision(record["checks"], record["protocol"], record["subject"])
        record["admission_id"] = _record_id(record)
        _persist(output_dir, record)
    finally:
        if not keep_work:
            shutil.rmtree(run_dir, ignore_errors=True)
    return record


# ───────────────────────────── commande manuelle ─────────────────────────────

def format_record(record):
    lines = [f"{NOTICE} — {ACTIVATION} : aucun point d'entrée n'appelle ce module, il ne protège rien.",
             f"Diagnostic : {record['decision']}" + (f" (refus : {record['refusal']})" if record.get("refusal") else "")]
    if record["protocol"].get("reduced"):
        lines.append("PROTOCOLE RÉDUIT : ce diagnostic ne vaut que pour ce protocole réduit (usage de test).")
    if (record.get("subject") or {}).get("runner") == "injected_in_process":
        lines.append("LANCEUR INJECTÉ : aucune séparation de processus, aucune garde (usage de test).")
    for check in record["checks"]:
        lines.append(f"  {check['check']:<16} {check['state']:<13} {' '.join(check['codes'])}"
                     + (f"  {json.dumps(check['coordinates'], sort_keys=True)}" if check["coordinates"] else ""))
    replay = next((c for c in record["checks"] if c["check"] == "decision_replay"), {}).get("coverage") or {}
    if "tested_decisions_by_param_set" in replay:
        lines.append(f"Couverture du rejeu : décisions testées par jeu : {replay['tested_decisions_by_param_set']} ; "
                     f"plancher : {replay['min_decisions_floor']} ; rejeux : {replay['replays']} ; "
                     f"jeux distincts exercés : {replay['distinct_exercised_param_sets']}")
    for item in record.get("not_implemented_at_a0") or ():
        lines.append(f"Non implémenté à A0 : {item}")
    lines.append(f"Non couvert ({len(record.get('not_covered') or ())}) et non empêché "
                 f"({len(record.get('not_prevented') or ())}) : listes complètes, champs not_covered et "
                 f"not_prevented de l'enregistrement.")
    lines.append("PASS = aucune violation observée dans la couverture exécutée. Ce n'est ni une preuve de causalité,")
    lines.append("ni une mesure de robustesse ou de qualité, ni une autorisation de trading, ni une qualification.")
    if record.get("admission_id"):
        lines.append(f"Enregistrement : admissions/{record['admission_id']}.json")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pré-vol expérimental d'une stratégie (diagnostic non bloquant).",
                                     allow_abbrev=False)
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--strategy")
    parser.add_argument("--approval")
    parser.add_argument("--params-json", help="fichier JSON : liste de jeux de paramètres, le jeu de base en premier")
    parser.add_argument("--frame-csv", action="append", default=[])
    parser.add_argument("--frame-origin", action="append", default=[], choices=list(FRAME_ORIGINS))
    parser.add_argument("--protocol-json")
    parser.add_argument("--output-dir")
    parser.add_argument("--keep-work", action="store_true")
    args = parser.parse_args(argv)
    if args.worker:
        return _worker_main(args.worker)
    if not (args.strategy and args.approval and args.params_json and args.frame_csv and args.output_dir) \
            or len(args.frame_csv) != len(args.frame_origin):
        parser.error("--strategy, --approval, --params-json, --output-dir et un --frame-origin par --frame-csv sont requis")

    def load_json(path):
        with open(path, "rb") as handle:
            return json.loads(handle.read().decode("utf-8"))
    try:  # entrées illisibles : erreur d'usage, jamais une trace brute
        protocol = load_json(args.protocol_json) if args.protocol_json else None
        if _resolve_protocol(protocol)["reduced"]:  # SystemExit : jamais capturé ci-dessous
            parser.error("protocole réduit refusé par la commande manuelle : seuls des réglages au moins égaux au défaut")
        param_sets = _normalised_param_sets(load_json(args.params_json))
        frames = [{"frame": pd.read_csv(path, parse_dates=["time"], float_precision="round_trip"), "origin": origin}
                  for path, origin in zip(args.frame_csv, args.frame_origin)]
    except (OSError, ValueError, TypeError) as error:
        parser.error(f"entrée illisible ou invalide : {type(error).__name__} : {error}")
    record = run_preflight(strategy_path=args.strategy, approval_path=args.approval,
                           param_sets=param_sets, frames=frames, output_dir=args.output_dir,
                           protocol=protocol, keep_work=args.keep_work)
    print(format_record(record))
    return 0 if record["decision"] == "NO_VIOLATION_OBSERVED" else 1


if __name__ == "__main__":
    if "--worker" in sys.argv and _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    sys.exit(main())
