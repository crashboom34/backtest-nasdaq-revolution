"""Worker de test (PAS un module pytest) : un PROCESSUS qui tente d'ajouter UN enregistrement à un registre SYNTHÉTIQUE, derrière une barrière de départ, avec une faute optionnelle.

Usage : python _gate_v_registry_worker.py '<json>' avec {"root", "body", "attempts", "ready", "go", "fault"}. `fault` : null | "die_before_link" | "die_after_link" (mort brutale `os._exit`,
sans nettoyage ni `finally`). Le résultat est écrit en une ligne JSON sur la sortie standard. Aucune donnée de marché, aucun accès réseau.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gate_v_registry_append as engine
from gate_v_registry_chain import RegistryRefusal


def _wait_for(path: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not os.path.exists(path):
        if time.monotonic() > deadline:
            print(json.dumps({"error": "go timeout"}))
            sys.exit(3)
        time.sleep(0.002)


def main() -> None:
    config = json.loads(sys.argv[1])
    fault = config.get("fault")
    if fault is not None:
        real_link = os.link

        def faulty_link(*args, **kwargs):
            if fault == "die_before_link":
                os._exit(7)
            result = real_link(*args, **kwargs)
            os._exit(7)                                       # le lien existe, ni fsync ni suppression du temporaire n'ont eu lieu
            return result

        os.link = faulty_link
    Path(config["ready"]).write_text("ready")
    _wait_for(config["go"])
    try:
        outcome = engine._append_record(config["root"], lambda snapshot: dict(config["body"]), max_attempts=config["attempts"],
                                        unproven_synthetic=True)
        result = {"ok": True, "seq": outcome.seq, "attempts": outcome.attempts, "collisions": outcome.collisions}
    except RegistryRefusal as refusal:
        result = {"refused": refusal.code.value}
    except engine.RegistryContentionError as error:
        result = {"contention": error.attempts}
    except Exception as error:                                # noqa: BLE001 - le test veut le nom exact de toute autre erreur
        result = {"error": f"{type(error).__name__}: {error}"}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
