"""
tests/_store_fault_injection.py — outils de test (PAS un module pytest) : injection de défaillances SIMULÉES dans
`atomic_json_store.save_exclusive(..., durable=True)`.

Partagé par tests/test_atomic_json_store_durable.py (contrat du store) et par les tests de la Slice E2
(`gate_v_final_holdout_claim_acquisition`). Les défaillances (ENOSPC, permissions, fsync...) sont injectées dans un
PROXY du module `os` propre à `atomic_json_store` : le reste du processus (pytest compris) n'est pas affecté.
Une panne réelle (coupure d'alimentation) n'est pas démontrable par des tests.
"""

from __future__ import annotations

import errno
import os


class OsProxy:
    """Remplace `atomic_json_store.os` : délègue au vrai `os`, sauf les attributs surchargés."""

    def __init__(self, **overrides):
        self.__dict__["_overrides"] = overrides

    def __getattr__(self, name):
        overrides = self.__dict__["_overrides"]
        return overrides[name] if name in overrides else getattr(os, name)


class FaultyHandle:
    """Enveloppe un vrai fichier binaire : enregistre les appels, injecte une erreur à une étape (`write`, `flush`,
    `close`), et ferme TOUJOURS le vrai descripteur (aucune fuite, même sur erreur)."""

    def __init__(self, real, events, fail_at=None, error=None):
        self._real, self._events, self._fail_at, self._error = real, events, fail_at, error
        self._closed = False

    def _maybe_fail(self, stage):
        if self._fail_at == stage:
            raise self._error

    def write(self, payload):
        self._events.append("write")
        self._maybe_fail("write")
        return self._real.write(payload)

    def flush(self):
        self._events.append("flush")
        self._maybe_fail("flush")
        return self._real.flush()

    def fileno(self):
        return self._real.fileno()

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self._real.close()
            finally:
                self._events.append("close")
        self._maybe_fail("close")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False


def install_store_faults(monkeypatch, store, *, fail_at=None, error=None, dir_sync=False,
                         dir_sync_fail_on_call=None, open_error=None, fdopen_error=None,
                         fdopen_closes_descriptor=False):
    """Installe le proxy `os` dans `atomic_json_store` (et la branche POSIX du fsync de répertoire, simulée).

    `fail_at` ∈ {write, flush, fsync, close} injecte `error` à cette étape APRÈS la création exclusive ;
    `open_error` fait échouer l'ouverture exclusive elle-même ; `fdopen_error` fait échouer l'enveloppe du
    descripteur (qui reste alors ouvert : à l'appelant de le fermer, SAUF avec `fdopen_closes_descriptor=True` qui
    reproduit `io.open`, lequel ferme déjà le descripteur avant de relever l'erreur) ; `dir_sync_fail_on_call=N` fait échouer le
    N-ième fsync de répertoire (1 = la sonde AVANT création, 2 = le fsync APRÈS). Retourne (événements, appels)."""
    events = []
    real_open, real_fdopen, real_fsync = os.open, os.fdopen, os.fsync

    def fake_open(path, flags, *args, **kwargs):
        events.append(("open", flags))
        if open_error is not None:
            raise open_error
        return real_open(path, flags, *args, **kwargs)

    def fake_fdopen(fd, mode="r", *args, **kwargs):
        events.append(("fdopen", mode))
        if fdopen_error is not None:
            if fdopen_closes_descriptor:
                os.close(fd)  # comme `io.open` : son propre nettoyage ferme déjà le descripteur avant de relever l'erreur
            raise fdopen_error
        return FaultyHandle(real_fdopen(fd, mode, *args, **kwargs), events, fail_at, error)

    def fake_fsync(fd):
        events.append("fsync")
        if fail_at == "fsync":
            raise error
        return real_fsync(fd)

    monkeypatch.setattr(store, "os", OsProxy(open=fake_open, fdopen=fake_fdopen, fsync=fake_fsync))
    monkeypatch.setattr(store, "_DIRECTORY_FSYNC_SUPPORTED", dir_sync)
    calls = []

    def fake_dir_sync(directory):
        calls.append(directory)
        events.append("dirsync")
        if dir_sync_fail_on_call is not None and len(calls) == dir_sync_fail_on_call:
            raise OSError(errno.EIO, "répertoire : fsync simulé en échec")

    monkeypatch.setattr(store, "_fsync_directory", fake_dir_sync)
    return events, calls
