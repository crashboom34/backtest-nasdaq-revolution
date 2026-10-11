"""
tests/test_atomic_json_store_durable.py — AF-V-07 Slice E2 : contrat `save_exclusive(..., durable=...)`.

Contrat normatif : ADR 0025 Décision 9 (primitif `O_CREAT|O_EXCL`) et Décision 22.8 (durabilité). Complète
`tests/test_atomic_json_store.py`, laissé intact. Propriétés établies ici :

- `durable=False` (défaut) : comportement HISTORIQUE strictement identique (octets, exceptions, aucun fsync) ;
- `durable=True` : payload encodé AVANT la création ; sonde `fsync` du répertoire (POSIX) AVANT la création ;
  création exclusive ; écriture, flush, fsync du fichier, fsync du répertoire (POSIX) ; toute erreur APRÈS la
  création = `ExclusiveCreationIncompleteError`, jamais confondue avec le refus initial `FileExistsError` ;
  le fichier créé n'est jamais supprimé.

Les défaillances (ENOSPC, permissions, fsync...) sont SIMULÉES par injection dans un proxy du module `os` propre
à `atomic_json_store` ; la durabilité réelle (coupure d'alimentation) n'est pas démontrable par des tests.
Tout se passe dans `tmp_path` ; aucune donnée de marché, aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import errno
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # outils de test partagés (`_store_fault_injection`)

import _store_fault_injection as faults
import atomic_json_store as store
from atomic_json_store import ExclusiveCreationIncompleteError, save_exclusive

_DATA = {"a": 1, "é": "ü", "nested": {"k": [1, 2.5, None]}}
_KIND = "some_exclusive_record"


def _expected_text(data=_DATA) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _install(monkeypatch, **options):
    """Raccourci : injecte les défaillances dans `atomic_json_store` via l'outil partagé."""
    return faults.install_store_faults(monkeypatch, store, **options)


# -- Compatibilité : durable=False reste STRICTEMENT le comportement historique ----------------------


def test_signature_adds_a_keyword_only_durable_defaulting_to_false():
    parameters = inspect.signature(save_exclusive).parameters
    assert list(parameters) == ["path", "data", "kind", "durable"]
    assert parameters["durable"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["durable"].default is False


def test_default_and_explicit_false_write_identical_legacy_bytes(tmp_path):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    save_exclusive(first, _DATA, _KIND)
    save_exclusive(second, _DATA, _KIND, durable=False)
    legacy = _expected_text().replace("\n", os.linesep).encode("utf-8")  # mode texte historique
    assert first.read_bytes() == second.read_bytes() == legacy


def test_non_durable_never_fsyncs_nor_probes_the_directory(tmp_path, monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("durable=False ne doit jamais appeler fsync")

    monkeypatch.setattr(store, "os", faults.OsProxy(fsync=forbidden))
    monkeypatch.setattr(store, "_DIRECTORY_FSYNC_SUPPORTED", True)
    monkeypatch.setattr(store, "_fsync_directory", forbidden)
    save_exclusive(tmp_path / "x.json", _DATA, _KIND)
    save_exclusive(tmp_path / "y.json", _DATA, _KIND, durable=False)
    assert json.loads((tmp_path / "x.json").read_text(encoding="utf-8")) == _DATA


def test_non_durable_exceptions_are_unchanged(tmp_path):
    path = tmp_path / "x.json"
    save_exclusive(path, {"first": True}, _KIND)
    before = path.read_bytes()
    with pytest.raises(FileExistsError, match=_KIND):
        save_exclusive(path, {"second": True}, _KIND)
    assert path.read_bytes() == before
    with pytest.raises(TypeError):
        save_exclusive(tmp_path / "z.json", {"x": object()}, _KIND)


def test_existing_consumers_still_pass_positional_arguments(tmp_path):
    assert save_exclusive(str(tmp_path / "p.json"), {"a": 1}, "k") == tmp_path / "p.json"


# -- durable=True : contenu, création, ordre des opérations ------------------------------------------


def test_durable_writes_exact_utf8_lf_bytes_and_returns_the_target(tmp_path):
    path = tmp_path / "claim.json"
    assert save_exclusive(path, _DATA, _KIND, durable=True) == path
    assert path.read_bytes() == _expected_text().encode("utf-8")  # LF seul, jamais de traduction de fin de ligne
    assert json.loads(path.read_text(encoding="utf-8")) == _DATA


def test_durable_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "a" / "b" / "claim.json"
    save_exclusive(path, _DATA, _KIND, durable=True)
    assert json.loads(path.read_text(encoding="utf-8")) == _DATA


def test_durable_operation_order_posix_branch(tmp_path, monkeypatch):
    events, calls = _install(monkeypatch, dir_sync=True)
    path = tmp_path / "claim.json"
    save_exclusive(path, _DATA, _KIND, durable=True)
    names = [event if isinstance(event, str) else event[0] for event in events]
    # sonde du répertoire AVANT la création ; puis écriture, flush, fsync du fichier, fermeture ; fsync du répertoire
    assert names == ["dirsync", "open", "fdopen", "write", "flush", "fsync", "close", "dirsync"]
    flags = next(event[1] for event in events if isinstance(event, tuple) and event[0] == "open")
    assert flags & os.O_CREAT and flags & os.O_EXCL and flags & os.O_WRONLY
    assert next(event[1] for event in events if isinstance(event, tuple) and event[0] == "fdopen") == "wb"
    assert calls == [tmp_path, tmp_path]


def test_durable_windows_branch_skips_directory_fsync(tmp_path, monkeypatch):
    events, calls = _install(monkeypatch, dir_sync=False)
    save_exclusive(tmp_path / "claim.json", _DATA, _KIND, durable=True)
    names = [event if isinstance(event, str) else event[0] for event in events]
    assert names == ["open", "fdopen", "write", "flush", "fsync", "close"] and calls == []


def test_directory_fsync_support_is_posix_only_by_default():
    assert store._DIRECTORY_FSYNC_SUPPORTED is (os.name == "posix")


# -- durable=True : échecs AVANT toute création ------------------------------------------------------


def test_directory_probe_failure_raises_before_any_creation(tmp_path, monkeypatch):
    events, _ = _install(monkeypatch, dir_sync=True, dir_sync_fail_on_call=1)
    path = tmp_path / "claim.json"
    with pytest.raises(OSError, match="simulé") as raised:
        save_exclusive(path, _DATA, _KIND, durable=True)
    assert not isinstance(raised.value, ExclusiveCreationIncompleteError)
    assert not path.exists() and not any(isinstance(e, tuple) and e[0] == "open" for e in events)


@pytest.mark.parametrize("data, error", (({"x": "\ud800"}, UnicodeEncodeError), ({"x": object()}, TypeError)))
def test_unencodable_or_unserializable_payload_raises_before_any_creation(tmp_path, monkeypatch, data, error):
    events, _ = _install(monkeypatch, dir_sync=True)
    path = tmp_path / "claim.json"
    with pytest.raises(error):
        save_exclusive(path, data, _KIND, durable=True)
    assert not path.exists() and events == []  # ni sonde, ni ouverture


def test_open_errors_other_than_file_exists_propagate_raw_and_create_nothing(tmp_path, monkeypatch):
    _install(monkeypatch, open_error=PermissionError(errno.EACCES, "refusé"))
    path = tmp_path / "claim.json"
    with pytest.raises(PermissionError) as raised:
        save_exclusive(path, _DATA, _KIND, durable=True)
    assert not isinstance(raised.value, ExclusiveCreationIncompleteError) and not path.exists()


@pytest.mark.parametrize("existing", (b"", b"{", b"not json at all", json.dumps({"a": 1}).encode()))
def test_existing_path_of_any_content_is_refused_untouched_and_never_incomplete(tmp_path, existing):
    path = tmp_path / "claim.json"
    path.write_bytes(existing)
    with pytest.raises(FileExistsError, match=_KIND) as raised:
        save_exclusive(path, {"new": True}, _KIND, durable=True)
    assert type(raised.value) is FileExistsError and not isinstance(raised.value, ExclusiveCreationIncompleteError)
    assert path.read_bytes() == existing


def test_a_file_exists_error_from_the_parent_directory_is_never_the_exclusive_refusal(tmp_path):
    """`mkdir` du parent lève `FileExistsError` quand le parent est un FICHIER : ce n'est PAS le refus d'`O_EXCL`
    du chemin du Claim (rien n'a été tenté sur lui) et ne doit jamais être lu comme « déjà consommé »."""
    (tmp_path / "blocker").write_bytes(b"x")
    target = tmp_path / "blocker" / "claim.json"
    with pytest.raises(OSError) as raised:
        save_exclusive(target, _DATA, _KIND, durable=True)
    assert not isinstance(raised.value, FileExistsError)
    assert isinstance(raised.value, NotADirectoryError) and isinstance(raised.value.__cause__, FileExistsError)
    assert (tmp_path / "blocker").read_bytes() == b"x"  # le fichier qui bloque n'est pas touché


def test_the_historical_mode_keeps_its_own_parent_directory_error(tmp_path):
    (tmp_path / "blocker").write_bytes(b"x")
    with pytest.raises(FileExistsError):  # comportement historique INCHANGÉ en durable=False
        save_exclusive(tmp_path / "blocker" / "claim.json", _DATA, _KIND)


# -- durable=True : échecs APRÈS la création = ExclusiveCreationIncompleteError ----------------------

_ERRORS = (
    OSError(errno.ENOSPC, "disque plein simulé"),
    PermissionError(errno.EACCES, "permission refusée simulée"),
    OSError(errno.EIO, "erreur d'E/S simulée"),
    FileExistsError(errno.EEXIST, "FileExistsError tardive simulée"),
)
# (étape, erreur) : 4 étapes x 4 erreurs, plus le fsync de répertoire POSIX (EIO simulée par l'outil, une seule fois)
_FAILURES = [(stage, error) for stage in ("write", "flush", "fsync", "close") for error in _ERRORS]
_FAILURES.append(("dirsync_after", None))


@pytest.mark.parametrize(
    "stage, error", _FAILURES,
    ids=lambda v: v if isinstance(v, str) else (type(v).__name__ + str(v.errno) if v is not None else "EIO"),
)
def test_any_error_after_creation_is_classified_incomplete_and_the_file_is_kept(tmp_path, monkeypatch, stage, error):
    if stage == "dirsync_after":
        _install(monkeypatch, dir_sync=True, dir_sync_fail_on_call=2)
    else:
        _install(monkeypatch, fail_at=stage, error=error)
    path = tmp_path / "claim.json"
    with pytest.raises(ExclusiveCreationIncompleteError) as raised:
        save_exclusive(path, _DATA, _KIND, durable=True)
    failure = raised.value
    assert isinstance(failure, OSError)
    assert not isinstance(failure, FileExistsError)  # JAMAIS confondue avec le refus initial d'O_EXCL
    assert isinstance(failure.__cause__, OSError)
    if error is not None:
        assert failure.__cause__ is error
    assert failure.path == path and str(path) in str(failure)
    assert path.exists()  # le chemin créé est consommé : aucun nettoyage automatique
    path.unlink()  # sous Windows échouerait si un descripteur était resté ouvert


def test_fdopen_failure_after_the_exclusive_open_is_incomplete_and_closes_the_descriptor(tmp_path, monkeypatch):
    error = OSError(errno.EMFILE, "trop de fichiers ouverts simulé")
    _install(monkeypatch, fdopen_error=error)
    path = tmp_path / "claim.json"
    with pytest.raises(ExclusiveCreationIncompleteError) as raised:
        save_exclusive(path, _DATA, _KIND, durable=True)
    assert raised.value.__cause__ is error and path.exists()
    path.unlink()


def test_an_interruption_during_descriptor_wrapping_closes_the_descriptor_and_propagates_untouched(tmp_path, monkeypatch):
    """Une interruption (BaseException) n'est jamais rangée en ExclusiveCreationIncompleteError ; le descripteur ne fuit pas."""
    _install(monkeypatch, fdopen_error=KeyboardInterrupt())
    path = tmp_path / "claim.json"
    with pytest.raises(KeyboardInterrupt):
        save_exclusive(path, _DATA, _KIND, durable=True)
    assert path.exists()  # créé donc consommé, jamais supprimé
    path.unlink()  # sous Windows échouerait si le descripteur avait fuité


@pytest.mark.parametrize("raised", (KeyboardInterrupt(), OSError(errno.EMFILE, "trop de fichiers ouverts simulé")))
def test_a_descriptor_already_closed_by_fdopen_does_not_mask_the_original_error(tmp_path, monkeypatch, raised):
    """`io.open` ferme lui-même le descripteur avant de relever son erreur : notre fermeture de secours ne doit alors
    ni lever `EBADF` (qui masquerait l'erreur d'origine, et transformerait une interruption en `Incomplete`), ni
    s'en prendre à un numéro de descripteur réutilisé sans nécessité."""
    _install(monkeypatch, fdopen_error=raised, fdopen_closes_descriptor=True)
    path = tmp_path / "claim.json"
    expected = ExclusiveCreationIncompleteError if isinstance(raised, OSError) else KeyboardInterrupt
    with pytest.raises(expected) as caught:
        save_exclusive(path, _DATA, _KIND, durable=True)
    assert (caught.value.__cause__ is raised) if isinstance(raised, OSError) else (caught.value is raised)
    assert path.exists()
    path.unlink()


def test_incomplete_error_is_an_oserror_carrying_the_created_path():
    assert issubclass(ExclusiveCreationIncompleteError, OSError)
    failure = ExclusiveCreationIncompleteError("m", Path("p"))
    assert failure.path == Path("p") and "m" in str(failure)
    with pytest.raises(TypeError):  # le chemin créé est obligatoire : aucun défaut spéculatif
        ExclusiveCreationIncompleteError("m")


@pytest.mark.skipif(os.name != "posix", reason="le fsync d'un répertoire n'existe que sous POSIX")
def test_the_real_directory_fsync_works_on_a_real_directory(tmp_path):
    store._fsync_directory(tmp_path)  # corps réel, non simulé : ne doit lever ni sur un répertoire existant ...
    with pytest.raises(OSError):
        store._fsync_directory(tmp_path / "absent")  # ... ni se taire sur un répertoire absent


def test_a_stored_file_is_never_deleted_by_the_store_itself():
    source = Path(store.__file__).read_text(encoding="utf-8")
    start, end = source.index("def _save_exclusive_durable"), source.index("def save_exclusive(")
    assert 0 < start < end  # sinon la tranche serait vide et le test passerait à vide
    durable_part = source[start:end]
    assert "os.fsync" in durable_part and "O_EXCL" in durable_part  # on inspecte bien la bonne fonction
    assert not [token for token in ("unlink", "os.remove", "os.replace", "os.rename", "shutil") if token in durable_part]
