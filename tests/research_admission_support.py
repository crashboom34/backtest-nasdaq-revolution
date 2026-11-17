"""Support des tests de research_admission (T1-a / A0) : barres synthétiques et stratégies de sonde.

Les stratégies de sonde sont écrites dans un répertoire temporaire par les tests ; chacune porte
sa vérité (causale ou non). Données synthétiques uniquement."""
import hashlib
import json
import os

import numpy as np
import pandas as pd

BASE_PARAMS = {"lookback": 10, "thr": 0.05, "every": 3, "stop_pct": 0.30, "target_pct": 0.50, "max_bars": 12}
PARAM_SETS = [dict(BASE_PARAMS), dict(BASE_PARAMS, thr=0.03), dict(BASE_PARAMS, thr=0.07)]
REDUCED_PROTOCOL = {"window_bars": 12, "n_trace_windows": 2, "n_independent_windows": 1, "min_decisions": 3,
                    "future_bars": 5, "sparse_bars": 2, "prefix_cuts": 3, "max_replays": 4000, "timeout_s": 120}

_TEMPLATE = '''"""Stratégie de sonde générée : {name}. Usage synthétique uniquement."""
{header}
STRATEGY_NAME = "{name}"


class Strategy:
    def reset(self):
        self._c = None

    @staticmethod
    def required_warmup(params):
        return int(params["lookback"]) + 12

    def prepare(self, df, params):
        k = int(params["lookback"])
{prepare}
        self._c = df["close"].values
        self._v = df["volume"].values
        return df

    def on_bar(self, i, df, context, params):
        if context["in_pos"]:
            return None
        if i % int(params["every"]) != 0:
            return None
        c = self._c[i]
        thr = params["thr"] / 100.0
{decide}
        if go:
            return {{"action": "enter", "direction": "long", "stop_pct": {stop},
                    "target_pct": params["target_pct"], "max_bars": int(params["max_bars"]), "nb_contracts": 1}}
        return None
'''
_HP = '        self._ref = df["close"].shift(k).values'
_HD = "        go = c > self._ref[i] * (1 + thr)"
_PD = "        r = self._ref[i]\n        go = (r == r) and r > c * (1 + thr)"
_CACHE = ("        if k not in _CACHE:\n            _CACHE[k] = df[\"close\"].shift(-k).values\n"
          "        self._ref = _CACHE[k][: len(df)]\n        if len(self._ref) != len(df):\n"
          "            raise ValueError(\"cached array shorter than data\")")
_STOP = 'params["stop_pct"]'

# nom -> (causale ?, en-tête, prepare, decide, stop)
SPECS = {
    "honest": (True, "", _HP, _HD, _STOP),
    "peek_prepare": (False, "", '        self._ref = df["close"].shift(-k).values', _PD, _STOP),
    "centered_ma": (False, "", '        self._ref = df["close"].rolling(2 * k + 1, center=True).mean().values', _PD, _STOP),
    "peek_onbar": (False, "", _HP, "        go = self._c[i + 1] > c * (1 + thr)", _STOP),
    "peek_i2_guarded": (False, "", _HP,
                        "        try:\n            go = self._c[i + 2] > c * (1 + thr)\n        except IndexError:\n            go = False", _STOP),
    "vol_peek": (False, "", _HP, "        go = c > self._ref[i] * (1 + thr) and self._v[i + 1] > 0.5", _STOP),
    "rare_peek": (False, "", _HP, "        go = (self._c[i + 1] > c) if i % 9 == 0 else c > self._ref[i] * (1 + thr)", _STOP),
    "modcache_peek": (False, "_CACHE = {}", _CACHE, _PD, _STOP),
    "diskcache_peek": (False, "import os\nimport numpy as np",
                       "        path = os.path.join(os.getcwd(), 'cache_%d.npy' % k)\n"
                       "        if not os.path.exists(path):\n            np.save(path, df[\"close\"].shift(-k).values)\n"
                       "        self._ref = np.load(path)[: len(df)]", _PD, _STOP),
    "random_entry": (True, "import random", _HP, "        go = random.random() < 0.3", _STOP),
    "bad_signal": (True, "", _HP, _HD, "-1.0"),
    "env_probe": (True, "import os\nif os.environ.get('T1A_LEAK') or os.listdir(os.getcwd()):\n"
                        "    raise RuntimeError('inherited environment or non-empty working directory')", _HP, _HD, _STOP),
    "sleeper": (True, "import time", "        time.sleep(600)\n" + _HP, _HD, _STOP),
    "imports_unapproved": (True, "import walk_forward", _HP, _HD, _STOP),
    "no_array": (True, "", "        self._k = k", "        go = c > df['close'].values[i - int(params['lookback'])] * (1 + thr)", _STOP),
    "raises_always": (True, "", "        raise KeyError('missing column')", _HD, _STOP),
    "state_counter": (True, "_CALLS = [0]", _HP, "        _CALLS[0] += 1\n        go = _CALLS[0] < 40", _STOP),
    "modstate_onbar": (True, "_SEEN = {}", _HP, "        go = _SEEN.setdefault(i, c) > self._ref[i] * (1 + thr)", _STOP),
    "unstable_unused": (False, "", _HP + '\n        self._x = df["close"].shift(-k).values', _HD, _STOP),
    "length_scalar": (True, "", _HP + "\n        self._n = len(df)", _HD, _STOP),
    "opaque_diff": (False, "import numpy as np", _HP + '\n        self._r = np.diff(df["close"].values)', _HD, _STOP),
    "empty_dict": (True, "", _HP, "        go = False\n        if i % 2 == 0:\n            return {}", _STOP),
    "raises_in_replay": (False, "", _HP,
                         "        if self._v[i + 1] == 0.0 or self._v[i + 1] > 5.0:\n"
                         "            raise RuntimeError('unusual volume')\n" + _HD, _STOP),
    "lazy_import": (True, "", "        try:\n            import walk_forward  # noqa: F401\n"
                              "        except ImportError:\n            pass\n" + _HP, _HD, _STOP),
    "forged_response": (True, "import os\nimport sys\n"
                              "open(os.path.join(os.path.dirname(sys.argv[-1]), 'response.json'), 'w').write("
                              "'{\"status\":\"ok\",\"trace\":[],\"same_fresh\":true,\"same_module\":true,"
                              "\"prefix\":null,\"audit\":[]}')", _HP, _HD, _STOP),
    "marker_on_import": (True, "import os\nopen(os.environ.get('T1A_MARKER', 'marker.txt'), 'w').write('x')", _HP, _HD, _STOP),
}


def write_strategy(directory, name):
    causal, header, prepare, decide, stop = SPECS[name]
    path = os.path.join(str(directory), f"{name}.py")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(_TEMPLATE.format(name=name, header=header, prepare=prepare, decide=decide, stop=stop))
    return path


def write_approval(directory, strategy_path, origin="handwritten"):
    with open(strategy_path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    path = os.path.join(str(directory), "approval.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"strategy_path": os.path.realpath(strategy_path), "sha256": digest, "origin": origin,
                   "local_modules": {}}, handle)
    return path


def synthetic_frame(n_bars=420, seed=5, vol=4.0, base=15000.0):
    """Marche aléatoire sans dérive, barres de 3 minutes, colonnes canoniques."""
    rng = np.random.default_rng(seed)
    times = pd.date_range("2024-01-02 13:00", periods=n_bars, freq="3min")
    close = base + np.cumsum(rng.normal(0.0, vol, size=n_bars))
    open_ = np.concatenate([[base], close[:-1]])
    wick = np.abs(rng.normal(0.0, vol * 0.6, size=n_bars))
    return pd.DataFrame({"time": times, "open": open_, "high": np.maximum(open_, close) + wick,
                         "low": np.minimum(open_, close) - wick, "close": close,
                         "volume": rng.uniform(1.0, 2.0, size=n_bars)})
