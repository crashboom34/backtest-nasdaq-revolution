"""
tests/_gate_v_final_holdout_claim_worker.py — processus autonome (PAS un module pytest) de la Slice E2.

Lancé par `subprocess.Popen` depuis tests/test_gate_v_final_holdout_claim_acquisition.py, un processus par
concurrent. Appelle `acquire_final_holdout_access_claim` sur une campagne de TEST (dossier temporaire) et publie
son issue dans un fichier résultat privé (jamais stdout/stderr : pas d'entrelacement ambigu).

Pour que la course se joue VRAIMENT au niveau de `O_CREAT|O_EXCL` (et non pendant les validations de sources,
de durées inégales), `save_exclusive` est enveloppée : chaque worker signale « prêt » puis attend un fichier
« go » créé par le test quand TOUS sont prêts. Les modes `crash_*` simulent un crash dur (`os._exit`, aucun
nettoyage, aucun `finally`) à un point précis de la création durable :

    race               aucune défaillance (course à N processus)
    crash_before_open  mort juste avant `os.open`
    crash_after_open   mort juste après l'ouverture exclusive, avant toute écriture  -> fichier VIDE
    crash_mid_write    mort après une écriture PARTIELLE                              -> fichier TRONQUÉ
    crash_before_fsync mort après flush, avant fsync                                   -> contenu complet
    crash_after_fsync  mort juste après le fsync du fichier                            -> contenu complet

Usage : python _gate_v_final_holdout_claim_worker.py <config.json> <mode> <result_path> <sync_dir> <go_path>
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CRASH_EXIT_CODE = 9
_WAIT_SECONDS = 90.0


def _publish(result_path: str, text: str) -> None:
    Path(result_path).write_text(text, encoding="utf-8")


def main() -> None:
    config_path, mode, result_path, sync_dir, go_path = sys.argv[1:6]
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))

    import gate_v_final_holdout_claim_acquisition as acq

    real_save = acq.save_exclusive

    def gated_save(path, data, kind, *, durable=False):
        Path(sync_dir, f"{os.getpid()}.ready").write_text("1", encoding="utf-8")
        deadline = time.monotonic() + _WAIT_SECONDS
        while not os.path.exists(go_path):
            if time.monotonic() > deadline:
                _publish(result_path, "FAIL:GoTimeout")
                os._exit(3)
            time.sleep(0.001)
        if mode == "crash_before_open":
            os._exit(_CRASH_EXIT_CODE)
        if mode == "crash_after_open":
            os.fdopen = lambda *_a, **_k: os._exit(_CRASH_EXIT_CODE)
        elif mode == "crash_mid_write":
            def partial(fd, *_a, **_k):
                os.write(fd, b'{\n  "claim_semantics_version": "final_hold')  # écriture PARTIELLE puis mort dure
                os._exit(_CRASH_EXIT_CODE)
            os.fdopen = partial
        elif mode in ("crash_before_fsync", "crash_after_fsync"):
            # Seul le fsync d'un FICHIER ordinaire déclenche la mort : sous POSIX la sonde du fsync de RÉPERTOIRE
            # (avant création) passe elle aussi par `os.fsync` et doit rester inoffensive.
            real_fsync = os.fsync

            def fsync_then_maybe_die(fd):
                is_file = stat.S_ISREG(os.fstat(fd).st_mode)
                if is_file and mode == "crash_before_fsync":
                    os._exit(_CRASH_EXIT_CODE)
                real_fsync(fd)
                if is_file:
                    os._exit(_CRASH_EXIT_CODE)
            os.fsync = fsync_then_maybe_die
        return real_save(path, data, kind, durable=durable)

    acq.save_exclusive = gated_save
    try:
        claim = acq.acquire_final_holdout_access_claim(
            config["campaign_dir"],
            preregistration_path=config["preregistration_path"],
            research_run_path=config["research_run_path"],
            split_plan_path=config["split_plan_path"],
            policy_path=config["policy_path"],
            repo_dir=config["repo_dir"],
            created_at=config.get("created_at"),
        )
    except acq.FinalHoldoutClaimAlreadyConsumedError:
        _publish(result_path, "CONSUMED")
    except acq.FinalHoldoutClaimPostAcquisitionError as error:
        _publish(result_path, f"POST:{type(error.__cause__).__name__}")
    except BaseException as error:  # rapporté pour diagnostic uniquement
        _publish(result_path, f"ERR:{type(error).__name__}:{error}")
    else:
        _publish(result_path, f"OK:{claim.claim_id}")


if __name__ == "__main__":
    main()
