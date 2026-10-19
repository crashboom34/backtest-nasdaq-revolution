"""AF-V-07 Slice E3-C — primitive de publication atomique et durable PAR LIEN (`tmp + fsync + os.link + fsync`, ADR 0025 23.10, 23.13, 23.22, 23.29.4).

Fixtures SYNTHÉTIQUES dans `tmp_path` uniquement : aucune donnée de marché, aucun `FINAL_HOLDOUT`, aucun accès réseau. Les fautes (`fsync`, `link`, écriture,
nettoyage) sont INJECTÉES par `monkeypatch`, comme l'exige 23.2 (profil `SIMULATED_DURABLE`) ; aucune coupure d'alimentation n'est simulée ni qualifiée.
Les tests dont l'appel système n'existe que sous POSIX (`fsync` de répertoire réel, `O_DIRECTORY`, `O_NOFOLLOW`, `follow_symlinks=False`) sont marqués `posix_only`
(tranche 11) : IGNORÉS sous Windows, EXÉCUTÉS et passés sur un hôte Linux hébergé (AI_HANDOFF.md §62). Sous Windows, le profil `POSIX_DIR_FSYNC` n'est exercé que par
une LOGIQUE simulée (fixture `posix_profile`, descripteur de substitution) qui ne prouve rien sur POSIX.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
import sys
import uuid
from pathlib import Path

import pytest

import atomic_json_store as store
from atomic_json_store import (
    DurabilityProfile,
    FileIdentity,
    LinkPublication,
    LinkPublicationError,
    PlatformNotQualifiedError,
    PublicationNotStartedError,
    PublicationOperation,
    PublicationStage,
    PublicationState,
    PublishedUnconfirmedError,
    SlotAbsentError,
    SlotContentMismatchError,
    SlotOccupiedError,
    TempDisposition,
    TempNaming,
)

SIMULATED = DurabilityProfile.SIMULATED_DURABLE
POSIX = DurabilityProfile.POSIX_DIR_FSYNC
posix_only = pytest.mark.skipif(os.name != "posix", reason="appel système POSIX uniquement : non exécuté sous Windows")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def names(directory: Path) -> list:
    return sorted(entry.name for entry in directory.iterdir())


# ── Tranche 0 : vocabulaire public (états, profils, nommages) ─────────────────────────────────────────────────────────

def test_the_durability_profiles_have_the_exact_adr_names():
    """23.2 : `REAL` exige `POSIX_DIR_FSYNC` ; `SYNTHETIC` utilise `SIMULATED_DURABLE`. Les valeurs sont celles de l'ADR, jamais inventées."""
    assert {profile.name: profile.value for profile in DurabilityProfile} == {
        "POSIX_DIR_FSYNC": "POSIX_DIR_FSYNC", "SIMULATED_DURABLE": "SIMULATED_DURABLE"}


def test_the_publication_states_are_exactly_the_two_adr_states():
    """23.10 : `PublishedDurable` (fsync du répertoire réussi) et `PublishedUnconfirmed` (lien fait, fsync absent ou en échec)."""
    assert {state.name for state in PublicationState} == {"PUBLISHED_DURABLE", "PUBLISHED_UNCONFIRMED"}


def test_the_stages_cover_every_step_before_the_link():
    assert {stage.name for stage in PublicationStage} == {"PREFLIGHT", "BARRIER", "PRECHECK", "TEMP_CREATE", "TEMP_WRITE", "TEMP_FSYNC", "TEMP_CLOSE", "LINK"}


def test_the_temporary_name_patterns_are_closed_and_match_the_adr_and_the_scanner_table():
    """23.29.1 : `.exposure.tmp.<32 hexadécimaux>` ; 23.10 étape 7 : `.registry.tmp.<uuid>`. L'autre seul consommateur (le scanner B2) définit sa propre constante :
    les deux ne doivent jamais diverger."""
    from gate_v_exposure_scan import EXPOSURE_TEMP_ORPHAN_PATTERN
    assert store.EXPOSURE_TEMP_NAME_PATTERN == EXPOSURE_TEMP_ORPHAN_PATTERN == r"\.exposure\.tmp\.[0-9a-f]{32}"
    assert re.fullmatch(store.EXPOSURE_TEMP_NAME_PATTERN, ".exposure.tmp." + "a" * 32)
    for bad in (".exposure.tmp." + "a" * 31, ".exposure.tmp." + "A" * 32, ".exposure.tmp." + "a" * 33, "exposure.tmp." + "a" * 32,
                ".exposure.tmp." + "g" * 32, ".exposure.tmp." + "a" * 32 + ".json"):
        assert re.fullmatch(store.EXPOSURE_TEMP_NAME_PATTERN, bad) is None, bad
    assert re.fullmatch(store.REGISTRY_TEMP_NAME_PATTERN, ".registry.tmp." + str(uuid.uuid4()))
    for bad in (".registry.tmp." + uuid.uuid4().hex, ".registry.tmp.", ".registry.tmp." + str(uuid.uuid4()).upper(), ".registry.tmp." + str(uuid.uuid4()) + "x"):
        assert re.fullmatch(store.REGISTRY_TEMP_NAME_PATTERN, bad) is None, bad


def test_is_publication_temp_name_classifies_only_the_two_closed_forms():
    assert store.is_publication_temp_name(".exposure.tmp." + "0" * 32) is TempNaming.EXPOSURE
    assert store.is_publication_temp_name(".registry.tmp." + str(uuid.uuid4())) is TempNaming.REGISTRY
    for other in ("declaration_0001.json", "admission_0001.json", "x.tmp", ".exposure.tmp.zz", "a.tmp.b", ""):
        assert store.is_publication_temp_name(other) is None


# ── Sérialisation normative (23.29.4) ───────────────────────────────────────────────────────────────────────────────────

def test_the_normative_json_is_sorted_indented_utf8_lf_with_a_final_newline():
    record = {"z": {"b": 1, "a": [True, None, "é"]}, "a": "x"}
    expected = ('{\n  "a": "x",\n  "z": {\n    "a": [\n      true,\n      null,\n      "é"\n    ],\n    "b": 1\n  }\n}\n').encode("utf-8")
    assert store.serialize_normative_json(record) == expected
    assert b"\r" not in expected and not expected.startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize("record", [
    {"a": 1.5}, {"a": 1.0}, {"a": [float("nan")]}, {"a": {"b": float("inf")}},       # aucun flottant (23.29.4 « sans flottant »)
    {"a": "\ud800"},                                                                  # substitut isolé : non encodable en UTF-8
    {1: "x"}, {"a": (1, 2)}, {"a": {1, 2}}, {"a": b"x"}, {"a": object()},             # clés non texte, tuple, ensemble, octets : hors JSON natif
    [], "texte", None, 7,                                                             # la racine est un objet
], ids=lambda value: repr(value)[:30])
def test_the_normative_json_refuses_anything_outside_the_contract(record):
    with pytest.raises(store.NormativeJsonError):
        store.serialize_normative_json(record)


def test_the_normative_json_error_is_a_value_error():
    assert issubclass(store.NormativeJsonError, ValueError)


def test_booleans_are_not_floats_and_big_integers_are_kept():
    assert store.serialize_normative_json({"a": True, "n": 10 ** 40}).decode("utf-8") == '{\n  "a": true,\n  "n": 10000000000000000000000000000000000000000\n}\n'


def test_the_identity_of_a_file_is_a_frozen_value():
    identity = FileIdentity(device=1, inode=2, size=3, sha256="0" * 64)
    with pytest.raises(Exception):
        identity.size = 9
    assert identity == FileIdentity(1, 2, 3, "0" * 64)


# ── Aides communes : exécution observée, profil POSIX simulé ─────────────────────────────────────────────────────────

def record_events(monkeypatch, directory: Path) -> list:
    """Observe, sans rien modifier, l'ordre des opérations de la publication (les vrais appels sont conservés)."""
    events, temp_fds = [], set()
    real = {name: getattr(os, name) for name in ("open", "write", "fsync", "close", "link", "unlink")}

    def is_temp(path) -> bool:
        return store.is_publication_temp_name(Path(path).name) is not None

    def wrapped_open(path, *args, **kwargs):
        fd = real["open"](path, *args, **kwargs)
        if is_temp(path):
            temp_fds.add(fd)
            events.append("create_temp")
        return fd

    def wrapped_write(fd, data):
        if fd in temp_fds:
            events.append("write")
        return real["write"](fd, data)

    def wrapped_fsync(fd):
        events.append("fsync_file" if fd in temp_fds else "fsync_directory")
        return real["fsync"](fd)

    def wrapped_close(fd):
        if fd in temp_fds:
            events.append("close_temp")
            temp_fds.discard(fd)
        return real["close"](fd)

    def wrapped_link(src, dst, *args, **kwargs):
        events.append("link")
        return real["link"](src, dst, *args, **kwargs)

    def wrapped_unlink(path, *args, **kwargs):
        if is_temp(path):
            events.append("unlink_temp")
        return real["unlink"](path, *args, **kwargs)

    for name, function in (("open", wrapped_open), ("write", wrapped_write), ("fsync", wrapped_fsync), ("close", wrapped_close),
                           ("link", wrapped_link), ("unlink", wrapped_unlink)):
        monkeypatch.setattr(os, name, function)
    simulated = store._simulated_directory_barrier

    def wrapped_barrier(path):
        events.append("barrier")
        return simulated(path)

    monkeypatch.setattr(store, "_simulated_directory_barrier", wrapped_barrier)
    return events


@pytest.fixture
def posix_profile(monkeypatch, tmp_path_factory):
    """Simule un hôte POSIX pour exercer la LOGIQUE du profil `POSIX_DIR_FSYNC` sous Windows : l'ouverture du répertoire est remplacée par un descripteur de
    fichier ordinaire (le `fsync` y est observé et injectable). Les appels système RÉELS (`O_DIRECTORY`, `fsync` de répertoire) ne sont couverts que par les
    tests `posix_only` de la dernière tranche, NON exécutés sous Windows : cette fixture n'en prouve que la logique d'enchaînement."""
    state = {"opened": []}
    scratch = tmp_path_factory.mktemp("fake_directory_descriptor") / "stand_in.bin"
    scratch.write_bytes(b"")

    def fake_open(path):
        fd = os.open(str(scratch), os.O_RDWR | getattr(os, "O_BINARY", 0))     # fsync exige un descripteur inscriptible (Windows)
        info = os.lstat(path)
        state["opened"].append(fd)
        return fd, (info.st_dev, info.st_ino)

    monkeypatch.setattr(store, "_DIRECTORY_FSYNC_SUPPORTED", True)
    monkeypatch.setattr(store, "_open_posix_directory_descriptor", fake_open)
    monkeypatch.setattr(store, "_fsync_slot_file", lambda path: None)           # sous Windows, fsync d'un descripteur en lecture seule échoue (EBADF)
    return state


# ── Tranche 1 : succès nominal, ordre de l'ADR, octets exacts, noms de temporaires ────────────────────────────────────────

@pytest.mark.parametrize("naming", list(TempNaming))
def test_a_nominal_publication_links_the_exact_bytes_and_confirms_durability_at_the_simulated_level(tmp_path, naming):
    content = b'{"seq": 1}\n\xc3\xa9\r\n\x00\xff'                                  # octets quelconques, CRLF et NUL compris : jamais traduits
    destination = tmp_path / "admission_0001.json"
    result = store.publish_bytes_by_link(destination, content, durability=SIMULATED, naming=naming, kind="admission")
    assert destination.read_bytes() == content
    assert isinstance(result, LinkPublication) and result.destination == destination
    assert result.state is PublicationState.PUBLISHED_DURABLE and result.operation is PublicationOperation.PUBLISHED
    assert result.durability_profile is SIMULATED and result.posix_dir_fsync_succeeded is False         # 23.2 : aucune preuve réelle
    assert result.identity == FileIdentity(os.stat(destination).st_dev, os.stat(destination).st_ino, len(content), sha(content))
    assert result.temp_disposition is TempDisposition.REMOVED and names(tmp_path) == ["admission_0001.json"]
    assert result.writer_pid == os.getpid() and re.fullmatch(r"[0-9a-f]{32}", result.publication_id)


def test_the_operations_follow_the_adr_order_exactly(tmp_path, monkeypatch):
    """23.10 : barrière du répertoire, temporaire exclusif, écriture, `fsync` du fichier, fermeture, `os.link`, `fsync` du répertoire, suppression du temporaire."""
    events = record_events(monkeypatch, tmp_path)
    store.publish_bytes_by_link(tmp_path / "declaration_0001.json", b"abc", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="déclaration")
    assert events == ["barrier", "create_temp", "write", "fsync_file", "close_temp", "link", "barrier", "unlink_temp"]


def test_the_precheck_runs_after_the_barrier_and_before_any_temporary_file(tmp_path, monkeypatch):
    events = record_events(monkeypatch, tmp_path)
    store.publish_bytes_by_link(tmp_path / "x.json", b"1", durability=SIMULATED, naming=TempNaming.REGISTRY, kind="k", precheck=lambda: events.append("precheck"))
    assert events[:3] == ["barrier", "precheck", "create_temp"]


@pytest.mark.parametrize("naming, pattern", [(TempNaming.EXPOSURE, store.EXPOSURE_TEMP_NAME_PATTERN), (TempNaming.REGISTRY, store.REGISTRY_TEMP_NAME_PATTERN)])
def test_the_temporary_name_is_in_the_same_directory_matches_the_closed_pattern_and_is_unique_per_attempt(tmp_path, monkeypatch, naming, pattern):
    seen, real_link = [], os.link

    def spy(src, dst, *args, **kwargs):
        seen.append((Path(src), Path(dst)))
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "link", spy)
    for index in range(3):
        store.publish_bytes_by_link(tmp_path / f"slot_{index}.json", b"x", durability=SIMULATED, naming=naming, kind="k")
    assert all(source.parent == destination.parent == tmp_path for source, destination in seen)
    assert all(re.fullmatch(pattern, source.name) for source, _ in seen)
    assert len({source.name for source, _ in seen}) == 3


def test_publish_json_writes_the_normative_bytes(tmp_path):
    record = {"b": 2, "a": {"y": "é", "x": [1, 2]}}
    result = store.publish_json_by_link(tmp_path / "declaration_0001.json", record, durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="déclaration")
    assert (tmp_path / "declaration_0001.json").read_bytes() == store.serialize_normative_json(record) == result_bytes(record)
    assert result.identity.sha256 == sha(store.serialize_normative_json(record))


def result_bytes(record) -> bytes:
    """Recette de l'ADR recopiée (23.29.4), indépendante du sérialiseur du module."""
    import json
    return (json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


@pytest.mark.parametrize("record", [{"a": 1.5}, {"a": float("nan")}, {"a": "\ud800"}, [], {"a": (1,)}])
def test_a_non_normative_record_is_refused_before_anything_is_created(tmp_path, record):
    with pytest.raises(store.NormativeJsonError):
        store.publish_json_by_link(tmp_path / "x.json", record, durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert names(tmp_path) == []


@pytest.mark.parametrize("content", ["texte", bytearray(b"x"), memoryview(b"x"), None, 7])
def test_the_content_must_be_exactly_bytes(tmp_path, content):
    with pytest.raises(TypeError):
        store.publish_bytes_by_link(tmp_path / "x.json", content, durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert names(tmp_path) == []


def test_durability_and_naming_are_required_enums_with_no_default(tmp_path):
    with pytest.raises(TypeError):
        store.publish_bytes_by_link(tmp_path / "x.json", b"x", naming=TempNaming.EXPOSURE, kind="k")                  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        store.publish_bytes_by_link(tmp_path / "x.json", b"x", durability=SIMULATED, kind="k")                        # type: ignore[call-arg]
    for bad in ("SIMULATED_DURABLE", None, 1):
        with pytest.raises(TypeError):
            store.publish_bytes_by_link(tmp_path / "x.json", b"x", durability=bad, naming=TempNaming.EXPOSURE, kind="k")
    for bad in ("EXPOSURE", None, ".exposure.tmp.abc"):
        with pytest.raises(TypeError):
            store.publish_bytes_by_link(tmp_path / "x.json", b"x", durability=SIMULATED, naming=bad, kind="k")
    assert names(tmp_path) == []


@pytest.mark.parametrize("relative", ["../escape.json", "sub/../escape.json", "a/../../escape.json"])
def test_a_destination_with_a_parent_traversal_is_refused_before_any_effect(tmp_path, relative):
    (tmp_path / "a").mkdir()
    (tmp_path / "sub").mkdir()
    with pytest.raises(ValueError):
        store.publish_bytes_by_link(tmp_path / relative, b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert names(tmp_path) == ["a", "sub"] and names(tmp_path / "a") == [] and names(tmp_path / "sub") == []


@pytest.mark.parametrize("name", ["x.tmp", "x.tmp.json", ".exposure.tmp." + "0" * 32, ".registry.tmp." + str(uuid.uuid4()), "a.TMP", ".hidden.Tmp.zz"])
def test_a_destination_named_like_a_temporary_file_is_refused(tmp_path, name):
    """B2 tient tout nom en `.tmp` ou contenant `.tmp.` pour un temporaire : un slot ainsi nommé serait pris pour un orphelin."""
    with pytest.raises(ValueError):
        store.publish_bytes_by_link(tmp_path / name, b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert names(tmp_path) == []


def test_a_missing_parent_directory_is_never_created(tmp_path):
    with pytest.raises(PublicationNotStartedError) as refusal:
        store.publish_bytes_by_link(tmp_path / "missing" / "x.json", b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert refusal.value.stage is PublicationStage.PREFLIGHT and refusal.value.temp_disposition is TempDisposition.NOT_CREATED
    assert names(tmp_path) == []


def test_a_parent_that_is_a_file_is_refused(tmp_path):
    (tmp_path / "plain").write_bytes(b"x")
    with pytest.raises(PublicationNotStartedError) as refusal:
        store.publish_bytes_by_link(tmp_path / "plain" / "x.json", b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert refusal.value.stage is PublicationStage.PREFLIGHT


@pytest.mark.skipif(os.name == "posix", reason="sous POSIX le profil est disponible")
def test_the_posix_profile_is_refused_before_anything_is_created_on_a_platform_without_directory_fsync(tmp_path):
    """23.2 / 23.10 : sous Windows la durabilité du lien n'est pas démontrable et `REAL` est refusé ; aucun repli silencieux sur le profil simulé."""
    with pytest.raises(PlatformNotQualifiedError):
        store.publish_bytes_by_link(tmp_path / "x.json", b"x", durability=POSIX, naming=TempNaming.EXPOSURE, kind="k")
    assert names(tmp_path) == []


def test_the_posix_profile_logic_syncs_the_held_directory_descriptor_in_the_adr_order_with_a_stand_in(tmp_path, posix_profile, monkeypatch):
    events = record_events(monkeypatch, tmp_path)
    result = store.publish_bytes_by_link(tmp_path / "admission_0001.json", b"abc", durability=POSIX, naming=TempNaming.REGISTRY, kind="admission")
    assert result.state is PublicationState.PUBLISHED_DURABLE and result.durability_profile is POSIX and result.posix_dir_fsync_succeeded is True
    assert events == ["fsync_directory", "create_temp", "write", "fsync_file", "close_temp", "link", "fsync_directory", "unlink_temp"]
    assert len(posix_profile["opened"]) == 1                                # le descripteur de répertoire est ouvert UNE fois pour toute la publication


# ── Tranche 2 : collision au `link` (23.10 étape 5) ────────────────────────────────────────────────────────────────────

EXISTING_CONTENTS = [b"", b"x", b'{"seq": 1}\n', b'{"se', b"\x00\xff" * 100]


@pytest.mark.parametrize("existing", EXISTING_CONTENTS, ids=["empty", "one_byte", "complete_json", "truncated_json", "binary"])
def test_an_occupied_slot_is_refused_untouched_whatever_its_content(tmp_path, existing):
    slot = tmp_path / "admission_0001.json"
    slot.write_bytes(existing)
    before = os.stat(slot)
    with pytest.raises(SlotOccupiedError) as refusal:
        store.publish_bytes_by_link(slot, b'{"seq": 2}\n', durability=SIMULATED, naming=TempNaming.REGISTRY, kind="admission")
    assert slot.read_bytes() == existing and (os.stat(slot).st_ino, os.stat(slot).st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert isinstance(refusal.value, FileExistsError) and refusal.value.stage is PublicationStage.LINK and refusal.value.destination == slot
    assert isinstance(refusal.value.__cause__, FileExistsError)
    assert refusal.value.temp_disposition is TempDisposition.REMOVED and names(tmp_path) == ["admission_0001.json"]


def test_republishing_identical_bytes_is_refused_too_there_is_no_idempotence_at_this_level(tmp_path):
    first = store.publish_bytes_by_link(tmp_path / "slot.json", b"same", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    with pytest.raises(SlotOccupiedError):
        store.publish_bytes_by_link(tmp_path / "slot.json", b"same", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert os.stat(tmp_path / "slot.json").st_ino == first.identity.inode and names(tmp_path) == ["slot.json"]


def test_a_collision_never_claims_durability_nor_runs_the_final_barrier(tmp_path, monkeypatch):
    (tmp_path / "slot.json").write_bytes(b"first")
    events = record_events(monkeypatch, tmp_path)
    with pytest.raises(SlotOccupiedError):
        store.publish_bytes_by_link(tmp_path / "slot.json", b"second", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert events == ["barrier", "create_temp", "write", "fsync_file", "close_temp", "link", "unlink_temp"]


def test_a_directory_at_the_slot_is_an_occupied_slot_and_is_left_alone(tmp_path):
    (tmp_path / "slot.json").mkdir()
    (tmp_path / "slot.json" / "inner.txt").write_bytes(b"keep")
    with pytest.raises(SlotOccupiedError):
        store.publish_bytes_by_link(tmp_path / "slot.json", b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert (tmp_path / "slot.json" / "inner.txt").read_bytes() == b"keep" and names(tmp_path) == ["slot.json"]


def test_a_dangling_symbolic_link_at_the_slot_is_an_occupied_slot_and_its_target_is_never_created(tmp_path):
    victim = tmp_path / "outside" / "created_through_the_link.json"
    (tmp_path / "outside").mkdir()
    try:
        os.symlink(victim, tmp_path / "slot.json")
    except (OSError, NotImplementedError):
        pytest.skip("création de lien symbolique non permise sur cette machine")
    with pytest.raises(SlotOccupiedError):
        store.publish_bytes_by_link(tmp_path / "slot.json", b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert not victim.exists() and os.path.islink(tmp_path / "slot.json")


def test_the_two_occupied_outcomes_are_distinguishable_from_every_other_error(tmp_path):
    (tmp_path / "slot.json").write_bytes(b"x")
    try:
        store.publish_bytes_by_link(tmp_path / "slot.json", b"y", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    except LinkPublicationError as error:
        assert type(error) is SlotOccupiedError and not isinstance(error, (PublicationNotStartedError, PublishedUnconfirmedError))
    else:
        pytest.fail("aucun refus")


# ── Tranche 3 : échecs AVANT la création du lien (23.10, matrice de crash) ──────────────────────────────────────────────

@pytest.fixture
def descriptors(monkeypatch):
    """Descripteurs ouverts par la publication et pas encore fermés : doit être vide à la fin de CHAQUE test d'échec (aucune fuite)."""
    live = set()
    real_open, real_close = os.open, os.close

    def tracked_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        live.add(fd)
        return fd

    def tracked_close(fd):
        live.discard(fd)
        return real_close(fd)

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", tracked_close)
    return live


def only_for_temporaries(monkeypatch, name: str, replacement) -> list:
    """Remplace `os.<name>` pour les seuls appels visant un temporaire de publication (fichier ou descripteur de ce fichier) ; les autres appels passent."""
    calls, real, temp_fds = [], getattr(os, name), set()
    real_open = os.open

    def opened(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if store.is_publication_temp_name(Path(path).name) is not None:
            temp_fds.add(fd)
        return fd

    def wrapper(target, *args, **kwargs):
        concerned = (target in temp_fds) if isinstance(target, int) else (store.is_publication_temp_name(Path(target).name) is not None)
        if not concerned:
            return real(target, *args, **kwargs)
        calls.append(target)
        return replacement(real, target, *args, **kwargs)

    if name != "open":
        monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, name, wrapper)
    return calls


def raising(error):
    def replacement(real, *args, **kwargs):
        raise error
    return replacement


def publish(tmp_path, **kwargs):
    kwargs.setdefault("durability", SIMULATED)
    kwargs.setdefault("naming", TempNaming.EXPOSURE)
    kwargs.setdefault("kind", "k")
    return store.publish_bytes_by_link(tmp_path / "slot.json", kwargs.pop("content", b"abcdef"), **kwargs)


def test_a_failing_initial_barrier_publishes_nothing_and_skips_the_precheck(tmp_path, monkeypatch, descriptors):
    boom = OSError(errno.EIO, "barrière en échec")
    monkeypatch.setattr(store, "_simulated_directory_barrier", lambda directory: (_ for _ in ()).throw(boom))
    called = []
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path, precheck=lambda: called.append(1))
    assert refusal.value.stage is PublicationStage.BARRIER and refusal.value.__cause__ is boom and not called
    assert refusal.value.temp_disposition is TempDisposition.NOT_CREATED and names(tmp_path) == [] and not descriptors


def test_the_prepublication_check_refuses_with_its_own_exception_and_nothing_is_created(tmp_path, descriptors):
    class BusinessRefusal(Exception):
        pass

    refusal = BusinessRefusal("recouvrement")
    def precheck():
        raise refusal

    with pytest.raises(BusinessRefusal) as caught:
        publish(tmp_path, precheck=precheck)
    assert caught.value is refusal and names(tmp_path) == [] and not descriptors


def test_a_temporary_file_that_cannot_be_created_leaves_nothing(tmp_path, monkeypatch, descriptors):
    only_for_temporaries(monkeypatch, "open", raising(PermissionError(errno.EACCES, "refusé")))
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.TEMP_CREATE and refusal.value.temp_disposition is TempDisposition.NOT_CREATED
    assert isinstance(refusal.value.__cause__, PermissionError) and names(tmp_path) == [] and not descriptors


def test_a_temporary_name_collision_is_retried_with_a_new_name(tmp_path, monkeypatch, descriptors):
    state = {"count": 0, "first": None}
    real_open = os.open

    def colliding(path, *args, **kwargs):
        if store.is_publication_temp_name(Path(path).name) is not None:
            state["count"] += 1
            if state["count"] == 1:
                state["first"] = Path(path).name
                raise FileExistsError(errno.EEXIST, "nom déjà pris")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", colliding)
    result = publish(tmp_path)
    assert state["count"] == 2 and result.temp_path.name != state["first"] and names(tmp_path) == ["slot.json"]


def test_endless_temporary_name_collisions_are_bounded_and_publish_nothing(tmp_path, monkeypatch, descriptors):
    calls = only_for_temporaries(monkeypatch, "open", raising(FileExistsError(errno.EEXIST, "nom déjà pris")))
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.TEMP_CREATE and len(calls) == 3 and names(tmp_path) == []


def test_a_write_that_fails_midway_removes_its_own_temporary_and_leaves_no_slot(tmp_path, monkeypatch, descriptors):
    def half_then_fail(real, fd, data):
        real(fd, bytes(data[:3]))
        raise OSError(errno.ENOSPC, "disque plein")

    only_for_temporaries(monkeypatch, "write", half_then_fail)
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.TEMP_WRITE and refusal.value.temp_disposition is TempDisposition.REMOVED
    assert names(tmp_path) == [] and not descriptors                                   # ni slot tronqué, ni orphelin, ni descripteur ouvert


def test_a_write_that_makes_no_progress_is_an_error_not_an_endless_loop(tmp_path, monkeypatch, descriptors):
    only_for_temporaries(monkeypatch, "write", lambda real, fd, data: 0)
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.TEMP_WRITE and names(tmp_path) == [] and not descriptors


def test_short_writes_are_completed_and_the_bytes_stay_exact(tmp_path, monkeypatch, descriptors):
    content = bytes(range(256)) * 4
    only_for_temporaries(monkeypatch, "write", lambda real, fd, data: real(fd, bytes(data[:1])))
    publish(tmp_path, content=content)
    assert (tmp_path / "slot.json").read_bytes() == content and names(tmp_path) == ["slot.json"] and not descriptors


@pytest.mark.parametrize("name, stage", [("fsync", PublicationStage.TEMP_FSYNC), ("close", PublicationStage.TEMP_CLOSE)])
def test_a_failing_fsync_or_close_of_the_temporary_publishes_nothing(tmp_path, monkeypatch, descriptors, name, stage):
    def fail(real, fd, *args):
        if name == "close":
            real(fd)                                                                    # le vrai descripteur est fermé : l'échec simulé ne fuit pas
        raise OSError(errno.EIO, f"{name} en échec")

    only_for_temporaries(monkeypatch, name, fail)
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is stage and refusal.value.temp_disposition is TempDisposition.REMOVED
    assert names(tmp_path) == [] and not descriptors


def test_a_link_refused_for_a_reason_other_than_an_occupied_slot_publishes_nothing(tmp_path, monkeypatch, descriptors):
    only_for_temporaries(monkeypatch, "link", raising(PermissionError(errno.EACCES, "accès refusé")))
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.LINK and refusal.value.filesystem_not_qualified is False
    assert refusal.value.temp_disposition is TempDisposition.REMOVED and names(tmp_path) == [] and not descriptors


@pytest.mark.parametrize("error", [OSError(errno.EPERM, "x"), OSError(errno.EXDEV, "x"), OSError(getattr(errno, "ENOTSUP", 95), "x"),
                                   OSError(getattr(errno, "ENOSYS", 38), "x"), OSError(1, "x", None, 1), OSError(1, "x", None, 50)],
                         ids=["EPERM", "EXDEV", "ENOTSUP", "ENOSYS", "winerror_1", "winerror_50"])
def test_a_filesystem_without_hard_links_is_reported_as_not_qualified(tmp_path, monkeypatch, descriptors, error):
    only_for_temporaries(monkeypatch, "link", raising(error))
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.LINK and refusal.value.filesystem_not_qualified is True and names(tmp_path) == []


def test_an_interruption_during_the_write_closes_the_descriptor_removes_the_temporary_and_propagates(tmp_path, monkeypatch, descriptors):
    only_for_temporaries(monkeypatch, "write", raising(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        publish(tmp_path)
    assert names(tmp_path) == [] and not descriptors


def test_an_interruption_around_the_link_never_touches_what_may_exist(tmp_path, monkeypatch, descriptors):
    """Au `link`, une interruption laisse un état INCONNU : le temporaire est conservé (aucune suppression devinée) et l'appelant doit traiter le slot comme
    possiblement occupé."""
    only_for_temporaries(monkeypatch, "link", raising(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        publish(tmp_path)
    left = names(tmp_path)
    assert len(left) == 1 and store.is_publication_temp_name(left[0]) is TempNaming.EXPOSURE and not descriptors


def test_a_parent_replaced_after_the_anchor_is_taken_is_refused_before_the_link(tmp_path, descriptors):
    directory = tmp_path / "dir"
    directory.mkdir()

    def replace_the_directory():
        directory.rename(tmp_path / "old")
        directory.mkdir()

    with pytest.raises(PublicationNotStartedError) as refusal:
        store.publish_bytes_by_link(directory / "slot.json", b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k", precheck=replace_the_directory)
    assert refusal.value.stage is PublicationStage.LINK and refusal.value.temp_disposition is TempDisposition.REMOVED
    assert names(directory) == [] and names(tmp_path / "old") == [] and not descriptors


def junction_or_symlink(link: Path, target: Path):
    if os.name == "nt":
        import subprocess
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)       # octets : la sortie OEM n'est pas de l'UTF-8
        if done.returncode != 0:
            pytest.skip("jonction non disponible")
    else:
        os.symlink(target, link, target_is_directory=True)


def test_a_parent_turned_into_a_junction_or_symlink_is_refused_before_the_link_and_leaves_nothing_in_the_target(tmp_path, descriptors):
    """ATTENTION (revue C-M1) : le temporaire EST créé, écrit et synchronisé À TRAVERS le lien (opérations par chemin), puis détecté avant le `link` et supprimé ;
    ce test ne vérifie que l'état FINAL. Le durcissement `dir_fd` qui supprimerait cette fenêtre est PROPOSÉ et non implémenté (validation Linux requise)."""
    directory, elsewhere = tmp_path / "dir", tmp_path / "elsewhere"
    directory.mkdir()
    elsewhere.mkdir()

    def swap_for_a_link():
        directory.rmdir()
        junction_or_symlink(directory, elsewhere)

    with pytest.raises(PublicationNotStartedError) as refusal:
        store.publish_bytes_by_link(directory / "slot.json", b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k", precheck=swap_for_a_link)
    assert refusal.value.stage is PublicationStage.LINK and names(elsewhere) == [] and not descriptors


def test_a_parent_that_is_already_a_junction_or_symlink_is_refused_up_front(tmp_path):
    real, link = tmp_path / "real", tmp_path / "link"
    real.mkdir()
    junction_or_symlink(link, real)
    with pytest.raises(PublicationNotStartedError) as refusal:
        store.publish_bytes_by_link(link / "slot.json", b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert refusal.value.stage is PublicationStage.PREFLIGHT and names(real) == []


# ── `directory_read_barrier` (23.10 étape 1) ─────────────────────────────────────────────────────────────────────────

def test_the_read_barrier_runs_the_simulated_barrier_once(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(store, "_simulated_directory_barrier", lambda directory: calls.append(Path(directory)))
    assert store.directory_read_barrier(tmp_path, durability=SIMULATED) is None
    assert calls == [tmp_path]


def test_a_failing_read_barrier_is_a_not_started_refusal(tmp_path, monkeypatch):
    boom = OSError(errno.EIO, "x")
    monkeypatch.setattr(store, "_simulated_directory_barrier", lambda directory: (_ for _ in ()).throw(boom))
    with pytest.raises(PublicationNotStartedError) as refusal:
        store.directory_read_barrier(tmp_path, durability=SIMULATED)
    assert refusal.value.stage is PublicationStage.BARRIER and refusal.value.__cause__ is boom


def test_the_read_barrier_refuses_a_missing_directory_and_never_creates_it(tmp_path):
    with pytest.raises(PublicationNotStartedError) as refusal:
        store.directory_read_barrier(tmp_path / "absent", durability=SIMULATED)
    assert refusal.value.stage is PublicationStage.PREFLIGHT and names(tmp_path) == []


def test_the_posix_read_barrier_syncs_the_directory_descriptor_once_and_closes_it(tmp_path, posix_profile, monkeypatch, descriptors):
    events = record_events(monkeypatch, tmp_path)
    store.directory_read_barrier(tmp_path, durability=POSIX)
    assert events == ["fsync_directory"] and len(posix_profile["opened"]) == 1


@pytest.mark.skipif(os.name == "posix", reason="sous POSIX le profil est disponible")
def test_the_posix_read_barrier_is_refused_on_a_platform_without_directory_fsync(tmp_path):
    with pytest.raises(PlatformNotQualifiedError):
        store.directory_read_barrier(tmp_path, durability=POSIX)


def test_a_failing_posix_directory_fsync_before_the_link_publishes_nothing(tmp_path, posix_profile, monkeypatch, descriptors):
    real_fsync = os.fsync

    def fail_for_the_directory(fd):
        if fd in posix_profile["opened"]:
            raise OSError(errno.EIO, "fsync du répertoire en échec")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_for_the_directory)
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path, durability=POSIX)
    assert refusal.value.stage is PublicationStage.BARRIER and names(tmp_path) == [] and not descriptors


# ── Tranche 4 : échecs APRÈS la création du lien — `PublishedUnconfirmed` (23.10) ────────────────────────────────────────

def barrier_script(monkeypatch, *actions) -> list:
    """Remplace la barrière simulée : l'action n°i est exécutée au i-ème appel (`None` = rien). Retourne la liste des appels."""
    calls = []

    def barrier(directory):
        index = len(calls)
        calls.append(Path(directory))
        if index < len(actions) and actions[index] is not None:
            actions[index]()

    monkeypatch.setattr(store, "_simulated_directory_barrier", barrier)
    return calls


def failing(error):
    def action():
        raise error
    return action


def after_link(monkeypatch, action) -> None:
    """Exécute `action(destination, temporaire)` juste APRÈS le vrai `os.link` (simule un tiers qui agit entre le lien et la vérification)."""
    real = os.link

    def link(source, destination, *args, **kwargs):
        real(source, destination, *args, **kwargs)
        action(Path(destination), Path(source))

    monkeypatch.setattr(os, "link", link)


def test_a_failing_final_barrier_leaves_a_binding_unconfirmed_slot_and_keeps_the_temporary(tmp_path, monkeypatch, descriptors):
    boom = OSError(errno.EIO, "fsync du répertoire en échec")
    barrier_script(monkeypatch, None, failing(boom))
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path, content=b"abcdef")
    error = unconfirmed.value
    assert error.reason is store.UnconfirmedReason.DIRECTORY_FSYNC_FAILED and error.__cause__ is boom and error.slot_is_binding is True
    result = error.publication
    assert result.state is PublicationState.PUBLISHED_UNCONFIRMED and result.operation is PublicationOperation.PUBLISHED
    assert result.temp_disposition is TempDisposition.KEPT_UNCONFIRMED and result.posix_dir_fsync_succeeded is False
    assert (tmp_path / "slot.json").read_bytes() == b"abcdef"                           # le slot est COMPLET et reste en place (jamais supprimé)
    assert result.identity == FileIdentity(os.stat(tmp_path / "slot.json").st_dev, os.stat(tmp_path / "slot.json").st_ino, 6, sha(b"abcdef"))
    assert sorted(names(tmp_path)) == sorted(["slot.json", result.temp_path.name]) and result.temp_path.exists() and not descriptors


def test_an_unconfirmed_slot_stays_binding_for_the_next_writer_and_its_temporary_is_never_touched(tmp_path, monkeypatch, descriptors):
    barrier_script(monkeypatch, None, failing(OSError(errno.EIO, "x")))
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path, content=b"first")
    orphan = unconfirmed.value.publication.temp_path
    monkeypatch.undo()
    with pytest.raises(SlotOccupiedError):
        publish(tmp_path, content=b"second")
    assert (tmp_path / "slot.json").read_bytes() == b"first" and orphan.exists()       # ni republié, ni supprimé, ni orphelin d'un autre appel nettoyé


def test_a_failing_posix_directory_fsync_after_the_link_is_unconfirmed(tmp_path, posix_profile, monkeypatch, descriptors):
    real_fsync, state = os.fsync, {"directory_calls": 0}

    def fsync(fd):
        if fd in posix_profile["opened"]:
            state["directory_calls"] += 1
            if state["directory_calls"] == 2:
                raise OSError(errno.EIO, "fsync du répertoire en échec")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path, durability=POSIX)
    assert unconfirmed.value.reason is store.UnconfirmedReason.DIRECTORY_FSYNC_FAILED
    assert unconfirmed.value.publication.durability_profile is POSIX and unconfirmed.value.publication.posix_dir_fsync_succeeded is False
    assert (tmp_path / "slot.json").exists() and not descriptors


def test_an_interruption_during_the_final_barrier_propagates_and_keeps_both_names(tmp_path, monkeypatch, descriptors):
    barrier_script(monkeypatch, None, failing(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        publish(tmp_path)
    left = names(tmp_path)
    assert len(left) == 2 and "slot.json" in left and not descriptors                  # lien fait, rien deviné ni supprimé


def test_a_slot_replaced_by_another_file_right_after_the_link_is_unconfirmed_and_left_untouched(tmp_path, monkeypatch, descriptors):
    def replace_the_slot(destination, temp):
        destination.unlink()
        destination.write_bytes(b"intrus")

    after_link(monkeypatch, replace_the_slot)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path, content=b"abcdef")
    assert unconfirmed.value.reason is store.UnconfirmedReason.SLOT_IDENTITY_CHANGED
    assert (tmp_path / "slot.json").read_bytes() == b"intrus"                           # le fichier du tiers n'est jamais supprimé ni écrasé
    assert unconfirmed.value.publication.temp_disposition is TempDisposition.KEPT_UNCONFIRMED and unconfirmed.value.publication.temp_path.exists()


def test_a_slot_that_vanished_after_the_link_is_unconfirmed_never_republished(tmp_path, monkeypatch, descriptors):
    after_link(monkeypatch, lambda destination, temp: destination.unlink())
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert unconfirmed.value.reason is store.UnconfirmedReason.SLOT_MISSING and not (tmp_path / "slot.json").exists()


def test_a_slot_that_became_a_directory_after_the_link_is_unconfirmed(tmp_path, monkeypatch, descriptors):
    def replace_by_a_directory(destination, temp):
        destination.unlink()
        destination.mkdir()

    after_link(monkeypatch, replace_by_a_directory)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert unconfirmed.value.reason is store.UnconfirmedReason.SLOT_NOT_REGULAR and (tmp_path / "slot.json").is_dir()


def test_an_extra_hard_link_to_the_published_file_is_an_anomaly_and_is_unconfirmed(tmp_path, monkeypatch, descriptors):
    real_link = os.link                                                                  # capturé AVANT la substitution (sinon récursion)
    after_link(monkeypatch, lambda destination, temp: real_link(temp, tmp_path / "intrus-link"))
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert unconfirmed.value.reason is store.UnconfirmedReason.LINK_COUNT_ANOMALY
    assert (tmp_path / "slot.json").read_bytes() == b"abcdef" and (tmp_path / "intrus-link").exists()      # rien de supprimé par l'appel


def test_the_slot_content_changed_in_place_after_the_link_is_unconfirmed(tmp_path, monkeypatch, descriptors):
    def rewrite_in_place(destination, temp):
        with open(destination, "r+b") as handle:
            handle.write(b"ZZZ")

    after_link(monkeypatch, rewrite_in_place)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path, content=b"abcdef")
    assert unconfirmed.value.reason is store.UnconfirmedReason.CONTENT_CHANGED


def test_a_parent_replaced_after_the_final_barrier_is_unconfirmed(tmp_path, monkeypatch, descriptors):
    directory = tmp_path / "dir"
    directory.mkdir()

    def swap_the_directory():
        directory.rename(tmp_path / "old")
        directory.mkdir()

    barrier_script(monkeypatch, None, swap_the_directory)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        store.publish_bytes_by_link(directory / "slot.json", b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert unconfirmed.value.reason is store.UnconfirmedReason.PARENT_CHANGED
    assert (tmp_path / "old" / "slot.json").exists() and not descriptors


def test_the_unconfirmed_reasons_are_a_closed_vocabulary():
    assert {reason.name for reason in store.UnconfirmedReason} == {
        "DIRECTORY_FSYNC_FAILED", "FILE_FSYNC_FAILED", "SLOT_MISSING", "SLOT_NOT_REGULAR", "SLOT_IDENTITY_CHANGED", "LINK_COUNT_ANOMALY", "CONTENT_CHANGED",
        "SLOT_UNREADABLE", "LINK_OUTCOME_UNKNOWN", "PARENT_CHANGED"}


# ── Tranche 5 : nettoyage du temporaire APRÈS un succès durable ──────────────────────────────────────────────────────────

def test_a_temporary_that_cannot_be_removed_after_a_durable_publication_is_a_harmless_orphan(tmp_path, monkeypatch, descriptors):
    only_for_temporaries(monkeypatch, "unlink", raising(PermissionError(errno.EACCES, "suppression refusée")))
    result = publish(tmp_path)
    assert result.state is PublicationState.PUBLISHED_DURABLE and result.temp_disposition is TempDisposition.REMOVAL_FAILED
    assert result.temp_cleanup_error and (tmp_path / "slot.json").read_bytes() == b"abcdef"
    assert names(tmp_path) == sorted(["slot.json", result.temp_path.name]) and store.is_publication_temp_name(result.temp_path.name) is TempNaming.EXPOSURE


def test_a_temporary_name_taken_over_by_another_file_is_never_deleted(tmp_path, monkeypatch, descriptors):
    import builtins
    real_open, reads = builtins.open, {"count": 0}

    def swapping_open(file, *args, **kwargs):
        handle = real_open(file, *args, **kwargs)
        if Path(file) == tmp_path / "slot.json":
            reads["count"] += 1
            if reads["count"] == 2:                      # relecture APRÈS la barrière : les contrôles ont déjà passé, le nettoyage va suivre
                temp = next(tmp_path.glob(".exposure.tmp.*"))
                other = tmp_path / "autre-fichier"
                other.write_bytes(b"autre")
                os.replace(other, temp)                  # le nom du temporaire désigne désormais un AUTRE fichier (nouvel inode)
        return handle

    monkeypatch.setattr(builtins, "open", swapping_open)
    result = publish(tmp_path)
    assert result.state is PublicationState.PUBLISHED_DURABLE and result.temp_disposition is TempDisposition.IDENTITY_MISMATCH_KEPT
    assert result.temp_path.read_bytes() == b"autre" and (tmp_path / "slot.json").read_bytes() == b"abcdef"


def test_a_durable_publication_leaves_exactly_one_name_and_one_link(tmp_path, descriptors):
    result = publish(tmp_path)
    assert names(tmp_path) == ["slot.json"] and result.temp_disposition is TempDisposition.REMOVED and os.stat(tmp_path / "slot.json").st_nlink == 1


def test_orphan_temporaries_of_earlier_attempts_are_never_deleted_by_a_later_publication(tmp_path, descriptors):
    orphan = tmp_path / (".exposure.tmp." + "a" * 32)
    orphan.write_bytes(b"orphelin-crash-anterieur")
    publish(tmp_path)
    assert orphan.read_bytes() == b"orphelin-crash-anterieur" and names(tmp_path) == sorted([orphan.name, "slot.json"])


# ── Tranche 6 : re-confirmation d'un slot publié (`confirm_published_slot`) ──────────────────────────────────────────────

def published_slot(tmp_path, content: bytes = b"abcdef"):
    result = publish(tmp_path, content=content)
    return tmp_path / "slot.json", result


def confirm(tmp_path, content: bytes = b"abcdef", **kwargs):
    kwargs.setdefault("durability", SIMULATED)
    kwargs.setdefault("expected_sha256", sha(content))
    return store.confirm_published_slot(tmp_path / "slot.json", **kwargs)


def test_reconfirmation_only_runs_a_barrier_and_never_writes_links_or_removes(tmp_path, monkeypatch, descriptors):
    slot, first = published_slot(tmp_path)
    before = (names(tmp_path), slot.read_bytes(), os.stat(slot).st_mtime_ns, os.stat(slot).st_ino)
    events = record_events(monkeypatch, tmp_path)
    result = confirm(tmp_path)
    assert events == ["barrier"]                                                         # AUCUNE création, écriture, lien ni suppression
    assert (names(tmp_path), slot.read_bytes(), os.stat(slot).st_mtime_ns, os.stat(slot).st_ino) == before
    assert result.operation is PublicationOperation.RECONFIRMED and result.state is PublicationState.PUBLISHED_DURABLE
    assert result.temp_path is None and result.temp_disposition is TempDisposition.NOT_CREATED and result.destination == slot
    assert result.identity == first.identity and result.publication_id != first.publication_id and result.writer_pid == os.getpid()
    assert result.posix_dir_fsync_succeeded is False and not descriptors            # profil simulé : aucune valeur de preuve


def test_reconfirmation_turns_an_unconfirmed_slot_into_a_durable_one_without_touching_the_orphan(tmp_path, monkeypatch, descriptors):
    barrier_script(monkeypatch, None, failing(OSError(errno.EIO, "x")))
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path, content=b"abcdef")
    orphan = unconfirmed.value.publication.temp_path
    monkeypatch.undo()
    result = confirm(tmp_path, expected_identity=unconfirmed.value.publication.identity)
    assert result.state is PublicationState.PUBLISHED_DURABLE and result.operation is PublicationOperation.RECONFIRMED
    assert orphan.exists() and (tmp_path / "slot.json").read_bytes() == b"abcdef"      # un nlink de 2 est normal tant que l'orphelin existe


def test_reconfirmation_of_an_absent_slot_is_a_refusal_and_creates_nothing(tmp_path, descriptors):
    with pytest.raises(store.SlotAbsentError):
        confirm(tmp_path)
    assert names(tmp_path) == []


@pytest.mark.parametrize("current", [b"abcdeZ", b"abc", b"abcdefg", b""], ids=["same_size", "shorter", "longer", "empty"])
def test_reconfirmation_of_a_slot_with_other_bytes_is_never_a_confirmation(tmp_path, descriptors, current):
    (tmp_path / "slot.json").write_bytes(current)
    with pytest.raises(store.SlotContentMismatchError):
        confirm(tmp_path, content=b"abcdef")
    assert (tmp_path / "slot.json").read_bytes() == current


def test_reconfirmation_checks_the_expected_identity_when_given(tmp_path, descriptors):
    slot, first = published_slot(tmp_path)
    assert confirm(tmp_path, expected_identity=first.identity).identity == first.identity
    for wrong in (FileIdentity(first.identity.device, first.identity.inode + 1, first.identity.size, first.identity.sha256),
                  FileIdentity(first.identity.device + 1, first.identity.inode, first.identity.size, first.identity.sha256),
                  FileIdentity(first.identity.device, first.identity.inode, first.identity.size + 1, first.identity.sha256),
                  FileIdentity(first.identity.device, first.identity.inode, first.identity.size, "0" * 64)):
        with pytest.raises(store.SlotContentMismatchError):
            confirm(tmp_path, expected_identity=wrong)


def test_reconfirmation_refuses_a_slot_that_is_not_a_regular_file(tmp_path, descriptors):
    (tmp_path / "slot.json").mkdir()
    with pytest.raises(store.SlotContentMismatchError) as refusal:
        confirm(tmp_path)
    assert "fichier régulier" in str(refusal.value)                                    # refusé par le contrôle de type, pas par une erreur de lecture


def test_a_failing_barrier_during_reconfirmation_stays_unconfirmed_and_touches_nothing(tmp_path, monkeypatch, descriptors):
    slot, first = published_slot(tmp_path)
    boom = OSError(errno.EIO, "fsync en échec")
    barrier_script(monkeypatch, failing(boom))
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        confirm(tmp_path)
    publication = unconfirmed.value.publication
    assert unconfirmed.value.reason is store.UnconfirmedReason.DIRECTORY_FSYNC_FAILED and unconfirmed.value.__cause__ is boom
    assert publication.operation is PublicationOperation.RECONFIRMED and publication.state is PublicationState.PUBLISHED_UNCONFIRMED
    assert publication.temp_path is None and publication.identity == first.identity and names(tmp_path) == ["slot.json"]


def test_reconfirmation_flags_a_foreign_hard_link(tmp_path, descriptors):
    slot, first = published_slot(tmp_path)
    os.link(slot, tmp_path / "intrus-link")
    os.link(slot, tmp_path / "intrus-link-2")
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        confirm(tmp_path)
    assert unconfirmed.value.reason is store.UnconfirmedReason.LINK_COUNT_ANOMALY and slot.read_bytes() == b"abcdef"


def test_reconfirmation_detects_a_parent_replaced_during_its_barrier(tmp_path, monkeypatch, descriptors):
    directory = tmp_path / "dir"
    directory.mkdir()
    (directory / "slot.json").write_bytes(b"abcdef")

    def swap():
        directory.rename(tmp_path / "old")
        directory.mkdir()

    barrier_script(monkeypatch, swap)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        store.confirm_published_slot(directory / "slot.json", expected_sha256=sha(b"abcdef"), durability=SIMULATED)
    assert unconfirmed.value.reason is store.UnconfirmedReason.PARENT_CHANGED


def test_reconfirmation_arguments_are_strict(tmp_path):
    published_slot(tmp_path)
    for bad_hash in ("", "ABC", "0" * 63, "0" * 65, "G" * 64, "A" * 64, None, b"0" * 64):
        with pytest.raises((ValueError, TypeError)):
            confirm(tmp_path, expected_sha256=bad_hash)
    with pytest.raises(TypeError):
        confirm(tmp_path, durability="SIMULATED_DURABLE")
    with pytest.raises(TypeError):
        confirm(tmp_path, expected_identity=(1, 2, 3, "x"))
    with pytest.raises(ValueError):
        store.confirm_published_slot(tmp_path / (".exposure.tmp." + "a" * 32), expected_sha256="0" * 64, durability=SIMULATED)
    with pytest.raises(store.SlotAbsentError):                                          # parent absent : le slot ne peut pas exister (jamais créé)
        store.confirm_published_slot(tmp_path / "absent" / "slot.json", expected_sha256="0" * 64, durability=SIMULATED)
    assert not (tmp_path / "absent").exists()


def test_the_posix_reconfirmation_syncs_the_directory_descriptor_once(tmp_path, posix_profile, monkeypatch, descriptors):
    published_slot(tmp_path)
    events = record_events(monkeypatch, tmp_path)
    result = confirm(tmp_path, durability=POSIX)
    assert events == ["fsync_directory"] and result.durability_profile is POSIX and result.posix_dir_fsync_succeeded is True and not descriptors


def test_reconfirmation_twice_is_a_pure_read_with_distinct_confirmation_ids(tmp_path, descriptors):
    published_slot(tmp_path)
    first, second = confirm(tmp_path), confirm(tmp_path)
    assert first.identity == second.identity and first.publication_id != second.publication_id and names(tmp_path) == ["slot.json"]


# ── Tranche 12 : garanties transversales et mutants survivants rendus observables SANS Linux ───────────────────────────────

def destructive_calls_on(monkeypatch, slot: Path) -> list:
    """Enregistre (sans les empêcher) tout appel de CE processus qui détruirait, remplacerait ou réécrirait le slot : `unlink`, `remove`, `rename`, `replace`,
    `truncate`, ouverture en écriture/troncature/ajout. Les actions des TIERS simulés des scénarios n'utilisent pas ces appels sur le slot."""
    calls = []

    def guard(name):
        real = getattr(os, name)

        def wrapper(path, *args, **kwargs):
            if Path(path) == slot or (name in ("rename", "replace") and args and Path(args[0]) == slot):      # le slot comme SOURCE ou comme DESTINATION
                calls.append(name)
            return real(path, *args, **kwargs)
        monkeypatch.setattr(os, name, wrapper)

    for name in ("unlink", "remove", "rename", "replace", "truncate"):
        guard(name)
    real_open = os.open
    writing = os.O_WRONLY | os.O_RDWR | os.O_APPEND | getattr(os, "O_TRUNC", 0)

    def wrapped_open(path, flags, *args, **kwargs):
        if isinstance(path, (str, Path)) and Path(path) == slot and flags & writing:
            calls.append("open_for_write")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", wrapped_open)
    import builtins
    real_builtin_open = builtins.open

    def wrapped_builtin_open(file, mode="r", *args, **kwargs):
        if isinstance(file, (str, Path)) and Path(file) == slot and any(flag in str(mode) for flag in "wax+"):
            calls.append("builtin_open_for_write")
        return real_builtin_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", wrapped_builtin_open)
    return calls


@pytest.mark.parametrize("scenario", ["final_barrier_fails", "foreign_hard_link", "ambiguous_link_error", "reconfirm_then_republish_refused"])
def test_an_error_after_the_link_never_overwrites_republishes_or_destroys_the_slot(tmp_path, monkeypatch, scenario):
    """Garantie transversale (23.10) : après `os.link`, AUCUN chemin de la primitive ne détruit, remplace ni réécrit le slot, quelle que soit la panne."""
    slot = tmp_path / "slot.json"
    calls = destructive_calls_on(monkeypatch, slot)
    real_link = os.link
    if scenario == "final_barrier_fails":
        barrier_script(monkeypatch, None, failing(OSError(errno.EIO, "x")))
        with pytest.raises(PublishedUnconfirmedError):
            publish(tmp_path, content=b"abcdef")
    elif scenario == "foreign_hard_link":
        after_link(monkeypatch, lambda destination, temp: real_link(temp, tmp_path / "intrus"))
        with pytest.raises(PublishedUnconfirmedError):
            publish(tmp_path, content=b"abcdef")
    elif scenario == "ambiguous_link_error":
        def link_then_fail(source, destination, *args, **kwargs):
            real_link(source, destination, *args, **kwargs)
            raise OSError(errno.EIO, "x")
        monkeypatch.setattr(os, "link", link_then_fail)
        assert publish(tmp_path, content=b"abcdef").state is PublicationState.PUBLISHED_DURABLE
    else:
        barrier_script(monkeypatch, None, failing(OSError(errno.EIO, "x")))
        with pytest.raises(PublishedUnconfirmedError):
            publish(tmp_path, content=b"abcdef")
        with pytest.raises(SlotOccupiedError):
            publish(tmp_path, content=b"autre")
        monkeypatch.setattr(store, "_simulated_directory_barrier", lambda directory: None)
        confirm(tmp_path, content=b"abcdef")
    assert slot.read_bytes() == b"abcdef" and calls == []


def test_a_published_unconfirmed_error_cannot_be_mistaken_for_an_ordinary_collision_or_a_retryable_failure():
    unconfirmed = sample_unconfirmed()
    assert not isinstance(unconfirmed, (SlotOccupiedError, FileExistsError, OSError, PublicationNotStartedError))
    assert unconfirmed.replay_safe is False and unconfirmed.slot_is_binding is True
    assert unconfirmed.publication.state is PublicationState.PUBLISHED_UNCONFIRMED and unconfirmed.publication.posix_dir_fsync_succeeded is False


def sample_unconfirmed():
    slot = Path("slot.json").resolve()
    publication = LinkPublication(slot, PublicationState.PUBLISHED_UNCONFIRMED, POSIX, PublicationOperation.PUBLISHED, FileIdentity(1, 2, 3, "0" * 64),
                                  "p" * 32, 1, None, TempDisposition.KEPT_UNCONFIRMED)
    return PublishedUnconfirmedError("non confirmé", slot, publication=publication, reason=store.UnconfirmedReason.DIRECTORY_FSYNC_FAILED)


def test_no_visible_unconfirmed_slot_is_ever_returned_as_a_success(tmp_path, monkeypatch):
    """Un slot visible mais non confirmé n'est JAMAIS rendu comme un résultat : seule l'exception le porte, et `PUBLISHED_UNCONFIRMED` n'est jamais durable."""
    barrier_script(monkeypatch, None, failing(OSError(errno.EIO, "x")))
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert (tmp_path / "slot.json").exists() and unconfirmed.value.publication.state is not PublicationState.PUBLISHED_DURABLE


def test_the_generic_primitive_imposes_no_business_limit_of_its_own():
    """Aucune borne de profondeur, de taille ou de schéma dans la primitive : ces plafonds sont ceux du LECTEUR (B5/B6), provisoires (23.31.5)."""
    assert [name for name in dir(store) if name.startswith(("MAX_", "DEFAULT_MAX"))] == []


def as_symlink(info):
    """Même `st_dev`/`st_ino`/taille, mais mode de lien symbolique : rend observable la LOGIQUE de refus des liens sans créer de lien (non permis ici)."""
    return os.stat_result((stat.S_IFLNK | 0o777, info.st_ino, info.st_dev, info.st_nlink, info.st_uid, info.st_gid, info.st_size,
                           int(info.st_atime), int(info.st_mtime), int(info.st_ctime)))


def lstat_faked_as_symlink(monkeypatch, wanted):
    """`os.lstat(path)` renvoie un lien symbolique pour les chemins où `wanted(path)` est vrai ; le reste passe."""
    real = os.lstat

    def lstat(path, *args, **kwargs):
        info = real(path, *args, **kwargs)
        return as_symlink(info) if wanted(Path(path)) else info

    monkeypatch.setattr(os, "lstat", lstat)


def test_a_symbolic_link_mode_is_recognised_as_a_link_even_without_a_reparse_attribute():
    from types import SimpleNamespace
    assert store._is_symlink_or_reparse_point(SimpleNamespace(st_mode=stat.S_IFLNK | 0o777)) is True
    assert store._is_symlink_or_reparse_point(SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_file_attributes=0x400)) is True
    assert store._is_symlink_or_reparse_point(SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_file_attributes=0)) is False
    assert store._is_symlink_or_reparse_point(SimpleNamespace(st_mode=stat.S_IFDIR | 0o755)) is False


def flag_when_temp_is_closed(monkeypatch) -> dict:
    """Pose `flag["on"]` dès que le temporaire de la publication est fermé (donc juste avant le contrôle d'avant-lien)."""
    flag, real_close, real_open, temp_fds = {"on": False}, os.close, os.open, set()

    def tracking_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if store.is_publication_temp_name(Path(path).name) is not None:
            temp_fds.add(fd)
        return fd

    def closing(fd):
        real_close(fd)
        if fd in temp_fds:
            flag["on"] = True

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "close", closing)
    return flag


def test_a_temporary_that_looks_like_a_symlink_with_the_same_identity_is_refused_before_the_link(tmp_path, monkeypatch, descriptors):
    flag = flag_when_temp_is_closed(monkeypatch)
    lstat_faked_as_symlink(monkeypatch, lambda path: flag["on"] and store.is_publication_temp_name(path.name) is not None)
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.LINK and not (tmp_path / "slot.json").exists()


def test_a_parent_that_looks_like_a_symlink_with_the_same_identity_is_refused_before_the_link(tmp_path, monkeypatch, descriptors):
    flag = flag_when_temp_is_closed(monkeypatch)
    lstat_faked_as_symlink(monkeypatch, lambda path: flag["on"] and path == tmp_path)
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.LINK and not (tmp_path / "slot.json").exists()


def test_a_parent_that_turns_into_a_symlink_after_the_link_is_a_parent_change(tmp_path, monkeypatch, descriptors):
    flag = {"on": False}
    after_link(monkeypatch, lambda destination, temp: flag.update(on=True))
    lstat_faked_as_symlink(monkeypatch, lambda path: flag["on"] and path == tmp_path)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert unconfirmed.value.reason is store.UnconfirmedReason.PARENT_CHANGED


def test_a_link_error_is_not_resolved_as_our_link_when_the_slot_looks_like_a_symlink(tmp_path, monkeypatch, descriptors):
    real = os.link

    def link_then_fail(source, destination, *args, **kwargs):
        real(source, destination, *args, **kwargs)
        raise OSError(errno.EIO, "x")

    monkeypatch.setattr(os, "link", link_then_fail)
    lstat_faked_as_symlink(monkeypatch, lambda path: path == tmp_path / "slot.json")
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.LINK


def test_a_str_subclass_is_not_accepted_as_an_expected_hash(tmp_path):
    class Text(str):
        pass

    published_slot(tmp_path)
    with pytest.raises(ValueError):
        confirm(tmp_path, expected_sha256=Text(sha(b"abcdef")))


def test_the_slot_file_is_opened_without_following_a_final_link_when_it_is_synced(tmp_path, monkeypatch):
    """Logique seule (le drapeau `O_NOFOLLOW` n'existe pas sous Windows : posé artificiellement) ; l'effet réel est couvert par un test `posix_only`."""
    fake_flag = 0x40000
    monkeypatch.setattr(os, "O_NOFOLLOW", fake_flag, raising=False)
    seen, real_open = [], os.open

    def recording_open(path, flags, *args, **kwargs):
        seen.append(flags)
        return real_open(path, flags & ~fake_flag, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    monkeypatch.setattr(os, "fsync", lambda fd: None)
    (tmp_path / "slot.json").write_bytes(b"x")
    store._fsync_slot_file(tmp_path / "slot.json")
    assert len(seen) == 1 and seen[0] & fake_flag and not seen[0] & (os.O_WRONLY | os.O_RDWR)


@pytest.mark.parametrize("name", ["a\0b.json", "\0.json"])
def test_a_destination_name_with_a_nul_character_is_refused_before_anything_is_created(tmp_path, name):
    """Revue C-L1 : avant, l'échec survenait au `link` (après création et écriture du temporaire) en `ValueError` brut, orphelin laissé."""
    with pytest.raises(ValueError):
        store.publish_bytes_by_link(tmp_path / name, b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert names(tmp_path) == []


def test_closing_the_directory_descriptor_never_masks_the_outcome_of_a_publication(tmp_path, posix_profile, monkeypatch, descriptors):
    """Revue C-L2 : le `fsync` est déjà fait ; une erreur de `close` du descripteur de répertoire ne doit ni remplacer le résultat ni une exception en cours."""
    real_close = os.close

    def failing_close(fd):
        real_close(fd)
        if fd in posix_profile["opened"]:
            raise OSError(errno.EIO, "close du répertoire en échec")

    monkeypatch.setattr(os, "close", failing_close)
    assert publish(tmp_path, durability=POSIX).state is PublicationState.PUBLISHED_DURABLE
    barrier_failure = OSError(errno.EIO, "x")
    real_fsync = os.fsync
    calls = {"n": 0}

    def failing_second_directory_fsync(fd):
        if fd in posix_profile["opened"]:
            calls["n"] += 1
            if calls["n"] == 2:
                raise barrier_failure
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", failing_second_directory_fsync)
    second = tmp_path / "second"
    second.mkdir()
    with pytest.raises(PublishedUnconfirmedError):                                  # l'exception d'origine, pas l'erreur de fermeture
        store.publish_bytes_by_link(second / "slot.json", b"abcdef", durability=POSIX, naming=TempNaming.EXPOSURE, kind="k")


AMBIGUOUS_LINK_ERRNOS = ["EIO", "ESTALE", "ETIMEDOUT", "EINTR", "ECONNRESET"]


def unobservable_slot(monkeypatch, slot: Path) -> None:
    real_lstat = os.lstat

    def lstat(path, *args, **kwargs):
        if Path(path) == slot:
            raise PermissionError(errno.EACCES, "observation impossible")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", lstat)


@pytest.mark.parametrize("name", [n for n in AMBIGUOUS_LINK_ERRNOS if hasattr(errno, n)])
def test_an_ambiguous_link_error_followed_by_an_unobservable_slot_is_unconfirmed_never_replay_safe(tmp_path, monkeypatch, descriptors, name):
    """Revue D-M1 : si `link` échoue d'une façon qui peut SUIVRE un lien abouti (réponse perdue) et que le slot ne peut PAS être observé (≠ absent), le lien a
    peut-être abouti : jamais « rien n'est publié »."""
    only_for_temporaries(monkeypatch, "link", raising(OSError(getattr(errno, name), "réponse perdue")))
    unobservable_slot(monkeypatch, tmp_path / "slot.json")
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert unconfirmed.value.reason is store.UnconfirmedReason.LINK_OUTCOME_UNKNOWN and unconfirmed.value.replay_safe is False
    assert "PEUT-ÊTRE" in str(unconfirmed.value)                                       # le message ne prétend pas que le lien existe


@pytest.mark.parametrize("code", [errno.EINVAL, errno.ENOENT, errno.EACCES, errno.EPERM], ids=["EINVAL", "ENOENT", "EACCES", "EPERM"])
def test_a_deterministic_link_error_with_an_unobservable_slot_is_a_replay_safe_refusal_not_a_phantom_binding_slot(tmp_path, monkeypatch, descriptors, code):
    """Revue E-M1 : un nom invalide fait échouer `link` ET `lstat` de la même façon ; ce n'est PAS une issue inconnue : temporaire supprimé, rien de binding."""
    only_for_temporaries(monkeypatch, "link", raising(OSError(code, "refus déterministe")))
    unobservable_slot(monkeypatch, tmp_path / "slot.json")
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.LINK and refusal.value.temp_disposition is TempDisposition.REMOVED and names(tmp_path) == []


@pytest.mark.parametrize("name", ["x" * 256, pytest.param("é" * 200 + ".json", marks=pytest.mark.skipif(os.name == "nt", reason="la limite Windows se compte en unités UTF-16"))],
                         ids=["256_chars", "400_bytes"])
def test_a_destination_name_longer_than_the_filesystem_limit_is_refused_before_anything_is_created(tmp_path, name):
    with pytest.raises(ValueError):
        store.publish_bytes_by_link(tmp_path / name, b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert names(tmp_path) == []


@pytest.mark.skipif(os.name != "nt", reason="caractères réservés propres à Windows")
@pytest.mark.parametrize("name", ["a*.json", "a?.json", "a<b>.json", "a|b.json", 'a"b.json', "a\x01b.json"])
def test_windows_reserved_characters_in_a_name_are_refused_before_anything_is_created(tmp_path, name):
    with pytest.raises(ValueError):
        store.publish_bytes_by_link(tmp_path / name, b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert names(tmp_path) == []


def test_a_link_outcome_unknown_slot_is_reported_without_claiming_the_link_exists(tmp_path, monkeypatch, descriptors):
    only_for_temporaries(monkeypatch, "link", raising(OSError(errno.EIO, "réponse perdue")))
    unobservable_slot(monkeypatch, tmp_path / "slot.json")
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert isinstance(unconfirmed.value.__cause__, OSError) and unconfirmed.value.__cause__.errno == errno.EIO      # la cause (erreur du `link`) est conservée
    assert unconfirmed.value.publication.temp_disposition is TempDisposition.KEPT_UNCONFIRMED and unconfirmed.value.publication.temp_path.exists()


def test_an_occupied_slot_that_cannot_be_observed_is_still_an_occupied_slot_error(tmp_path, monkeypatch, descriptors):
    """`EEXIST` prouve que le slot existe : même inobservable ensuite, c'est un slot OCCUPÉ (binding), pas un `PublishedUnconfirmed` (le lien n'est pas le nôtre)."""
    (tmp_path / "slot.json").write_bytes(b"autre")
    real_lstat = os.lstat

    def lstat(path, *args, **kwargs):
        if Path(path) == tmp_path / "slot.json":
            raise PermissionError(errno.EACCES, "observation impossible")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", lstat)
    with pytest.raises(SlotOccupiedError) as occupied:
        publish(tmp_path)
    assert occupied.value.temp_disposition is TempDisposition.REMOVED and names(tmp_path) == ["slot.json"]


def test_a_destination_name_the_filesystem_cannot_encode_is_refused_before_anything_is_created(tmp_path, monkeypatch):
    real = os.fsencode

    def refusing(value):
        if "unencodable" in str(value):
            raise UnicodeEncodeError("utf-8", str(value), 0, 1, "surrogate")
        return real(value)

    monkeypatch.setattr(os, "fsencode", refusing)
    with pytest.raises(ValueError):
        store.publish_bytes_by_link(tmp_path / "unencodable.json", b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert names(tmp_path) == []


def test_reconfirming_a_slot_that_exists_but_cannot_be_read_is_never_a_replay_safe_refusal(tmp_path, monkeypatch):
    """Revue F-M3 : `PublicationNotStartedError` (`replay_safe` vrai, « rien n'est publié ») serait faux : le slot EXISTE. Échec non rejouable et binding."""
    import builtins
    published_slot(tmp_path)
    real_open = builtins.open

    def refusing(file, *args, **kwargs):
        if Path(file) == tmp_path / "slot.json":
            raise PermissionError(errno.EACCES, "lecture refusée")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", refusing)
    with pytest.raises(store.SlotContentMismatchError) as refusal:
        confirm(tmp_path)
    assert refusal.value.replay_safe is False and refusal.value.slot_is_binding is True and "illisible" in str(refusal.value)


def test_reconfirming_a_slot_that_cannot_be_observed_is_never_a_replay_safe_refusal(tmp_path, monkeypatch):
    published_slot(tmp_path)
    unobservable_slot(monkeypatch, tmp_path / "slot.json")
    with pytest.raises(store.SlotContentMismatchError) as refusal:
        confirm(tmp_path)
    assert refusal.value.replay_safe is False and refusal.value.slot_is_binding is True and "inobservable" in str(refusal.value)


UNRELIABLE_RECONFIRMATION = {store.UnconfirmedReason.DIRECTORY_FSYNC_FAILED, store.UnconfirmedReason.FILE_FSYNC_FAILED}


@pytest.mark.parametrize("reason", list(store.UnconfirmedReason), ids=lambda reason: reason.name)
def test_a_reconfirmation_after_an_fsync_failure_is_flagged_as_unreliable(tmp_path, reason):
    """Revue F-M2 : après un échec de `fsync`, une re-confirmation (nouveau descripteur, cache de pages) peut réussir sans rien prouver (erreur déjà rapportée) :
    décision humaine, pas boucle de re-confirmation."""
    slot = tmp_path / "slot.json"
    publication = LinkPublication(slot, PublicationState.PUBLISHED_UNCONFIRMED, SIMULATED, PublicationOperation.PUBLISHED, FileIdentity(1, 2, 3, "0" * 64),
                                  "p" * 32, 1, None, TempDisposition.KEPT_UNCONFIRMED)
    assert PublishedUnconfirmedError("x", slot, publication=publication, reason=reason).reconfirmation_reliable is (reason not in UNRELIABLE_RECONFIRMATION)


def test_reconfirming_below_a_parent_that_is_not_a_directory_never_claims_the_slot_is_free(tmp_path):
    """Revue H-M1 : un parent inutilisable (pas un répertoire, lien, droits, erreur d'E/S) ne dit RIEN de l'état du slot : jamais « rejeu permis »."""
    (tmp_path / "file_not_dir").write_bytes(b"x")
    with pytest.raises(store.SlotContentMismatchError) as refusal:
        store.confirm_published_slot(tmp_path / "file_not_dir" / "slot.json", expected_sha256="0" * 64, durability=SIMULATED)
    assert refusal.value.replay_safe is False and refusal.value.slot_is_binding is True and "parent" in str(refusal.value)


def test_reconfirming_when_the_directory_descriptor_cannot_be_opened_never_claims_the_slot_is_free(tmp_path, posix_profile, monkeypatch):
    published_slot(tmp_path)

    def refusing(path):
        raise PermissionError(errno.EACCES, "ouverture refusée")

    monkeypatch.setattr(store, "_open_posix_directory_descriptor", refusing)
    with pytest.raises(store.SlotContentMismatchError) as refusal:
        confirm(tmp_path, durability=POSIX)
    assert refusal.value.replay_safe is False and (tmp_path / "slot.json").exists()


def test_a_slot_that_vanishes_between_the_observation_and_the_read_is_absent_not_unreadable(tmp_path, monkeypatch):
    import builtins
    published_slot(tmp_path)
    real_open = builtins.open

    def vanishing(file, *args, **kwargs):
        if Path(file) == tmp_path / "slot.json":
            raise FileNotFoundError(errno.ENOENT, "disparu")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", vanishing)
    with pytest.raises(store.SlotAbsentError):
        confirm(tmp_path)


def test_a_missing_slot_after_a_link_error_is_still_a_replay_safe_refusal(tmp_path, monkeypatch, descriptors):
    only_for_temporaries(monkeypatch, "link", raising(OSError(errno.EIO, "x")))
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.LINK and refusal.value.temp_disposition is TempDisposition.REMOVED and names(tmp_path) == []


# ── Tranche 11 : appels système POSIX RÉELS (`posix_only` : IGNORÉS sous Windows ; exécutés sous Linux, AI_HANDOFF.md §62) ────────────────────

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="profil REAL : Linux uniquement (23.2) ; non exécuté ici")


def fsync_kind(fd) -> str:
    return "directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"


@posix_only
def test_posix_the_real_directory_descriptor_is_opened_without_following_links_and_matches_the_lstat_identity(tmp_path, descriptors):
    fd, identity = store._open_posix_directory_descriptor(tmp_path)
    try:
        assert stat.S_ISDIR(os.fstat(fd).st_mode) and identity == (os.lstat(tmp_path).st_dev, os.lstat(tmp_path).st_ino)
    finally:
        os.close(fd)
    link = tmp_path.parent / (tmp_path.name + "-link")
    os.symlink(tmp_path, link, target_is_directory=True)
    with pytest.raises(OSError):
        store._open_posix_directory_descriptor(link)                                # O_NOFOLLOW | O_DIRECTORY : jamais à travers un lien
    with pytest.raises(OSError):
        store._open_posix_directory_descriptor(tmp_path / "absent")


@posix_only
def test_posix_a_regular_file_is_not_a_directory_descriptor(tmp_path):
    (tmp_path / "f").write_bytes(b"x")
    with pytest.raises(OSError):
        store._open_posix_directory_descriptor(tmp_path / "f")


@posix_only
@linux_only
def test_posix_a_real_publication_syncs_the_held_directory_descriptor_twice_and_reports_a_successful_directory_fsync(tmp_path, monkeypatch, descriptors):
    real_fsync, kinds = os.fsync, []

    def recording(fd):
        kinds.append(fsync_kind(fd))
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording)
    result = publish(tmp_path, durability=POSIX)
    assert kinds == ["directory", "file", "directory"]                              # barrière de lecture, fsync du temporaire, barrière après le lien
    assert result.posix_dir_fsync_succeeded is True and names(tmp_path) == ["slot.json"] and not descriptors


@posix_only
@linux_only
def test_posix_a_failing_real_directory_fsync_after_the_link_is_unconfirmed(tmp_path, monkeypatch, descriptors):
    real_fsync, count = os.fsync, {"directories": 0}

    def failing(fd):
        if fsync_kind(fd) == "directory":
            count["directories"] += 1
            if count["directories"] == 2:
                raise OSError(errno.EIO, "fsync du répertoire en échec")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", failing)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path, durability=POSIX)
    assert unconfirmed.value.reason is store.UnconfirmedReason.DIRECTORY_FSYNC_FAILED and unconfirmed.value.publication.posix_dir_fsync_succeeded is False
    assert (tmp_path / "slot.json").read_bytes() == b"abcdef" and not descriptors


@posix_only
@linux_only
def test_posix_a_symlinked_parent_is_refused_before_any_file_is_created(tmp_path):
    real, link = tmp_path / "real", tmp_path / "link"
    real.mkdir()
    os.symlink(real, link, target_is_directory=True)
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish_into(link, durability=POSIX)
    assert refusal.value.stage is PublicationStage.PREFLIGHT and names(real) == []


def publish_into(directory, **kwargs):
    kwargs.setdefault("durability", SIMULATED)
    return store.publish_bytes_by_link(directory / "slot.json", b"abcdef", naming=TempNaming.EXPOSURE, kind="k", **kwargs)


@posix_only
def test_posix_link_with_follow_symlinks_false_links_the_symlink_itself_not_its_target(tmp_path):
    if os.link not in os.supports_follow_symlinks:
        pytest.skip("follow_symlinks indisponible sur cette plateforme")
    (tmp_path / "target").write_bytes(b"cible")
    os.symlink(tmp_path / "target", tmp_path / "symlink")
    os.link(tmp_path / "symlink", tmp_path / "linked", follow_symlinks=False)
    assert stat.S_ISLNK(os.lstat(tmp_path / "linked").st_mode)


@posix_only
def test_posix_a_temporary_replaced_by_a_symlink_is_refused_by_the_pre_link_check_whatever_inode_reuse_does(tmp_path, monkeypatch, descriptors):
    real_close, real_open, temp_fds = os.close, os.open, set()

    def tracking_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if store.is_publication_temp_name(Path(path).name) is not None:
            temp_fds.add((fd, Path(path)))
        return fd

    def swapping_close(fd):
        real_close(fd)
        for tracked_fd, temp in list(temp_fds):
            if tracked_fd == fd:
                temp_fds.discard((tracked_fd, temp))
                (tmp_path / "victim").write_bytes(b"victime")
                temp.unlink()
                os.symlink(tmp_path / "victim", temp)

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "close", swapping_close)
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.LINK and not (tmp_path / "slot.json").exists()
    assert (tmp_path / "victim").read_bytes() == b"victime"


@posix_only
def test_posix_a_temporary_swapped_for_a_symlink_AFTER_the_pre_link_check_is_refused_by_the_post_link_check(tmp_path, monkeypatch, descriptors):
    """Atteint réellement `os.link` (contrôle d'avant-lien neutralisé) : avec `follow_symlinks=False`, c'est le LIEN SYMBOLIQUE qui est lié, jamais sa cible ;
    la vérification après le lien refuse un slot qui n'est pas un fichier régulier et ne supprime rien."""
    real_close, real_open, temp_fds = os.close, os.open, set()

    def tracking_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if store.is_publication_temp_name(Path(path).name) is not None:
            temp_fds.add((fd, Path(path)))
        return fd

    def swapping_close(fd):
        real_close(fd)
        for tracked_fd, temp in list(temp_fds):
            if tracked_fd == fd:
                temp_fds.discard((tracked_fd, temp))
                (tmp_path / "victim").write_bytes(b"victime")
                temp.unlink()
                os.symlink(tmp_path / "victim", temp)

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "close", swapping_close)
    monkeypatch.setattr(store, "_link_precondition_problem", lambda anchor, temp_path, temp_identity: None)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert unconfirmed.value.reason in (store.UnconfirmedReason.SLOT_NOT_REGULAR, store.UnconfirmedReason.SLOT_IDENTITY_CHANGED)
    assert (tmp_path / "victim").read_bytes() == b"victime"


@posix_only
@linux_only
def test_posix_reconfirmation_syncs_the_slot_file_then_the_directory(tmp_path, monkeypatch, descriptors):
    published_slot(tmp_path)
    real_fsync, kinds = os.fsync, []
    monkeypatch.setattr(os, "fsync", lambda fd: (kinds.append(fsync_kind(fd)), real_fsync(fd))[1])
    result = confirm(tmp_path, durability=POSIX)
    assert kinds == ["file", "directory"] and result.posix_dir_fsync_succeeded is True and not descriptors


@posix_only
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignore les permissions")
def test_posix_an_unwritable_directory_refuses_before_creating_anything(tmp_path):
    directory = tmp_path / "ro"
    directory.mkdir()
    directory.chmod(0o500)
    try:
        with pytest.raises(PublicationNotStartedError) as refusal:
            publish_into(directory)
        assert refusal.value.stage is PublicationStage.TEMP_CREATE and names(directory) == []
    finally:
        directory.chmod(0o700)


@posix_only
@linux_only
@pytest.mark.parametrize("naming", ["EXPOSURE", "REGISTRY"])
@pytest.mark.parametrize("point", ["initial_barrier", "after_temp_create", "partial_write", "before_file_fsync", "after_file_fsync", "before_link", "after_link",
                                  "after_final_barrier", "after_temp_removal"])      # les 9 lignes de CRASH_MATRIX (défini plus bas)
def test_posix_a_real_process_death_under_the_real_profile_keeps_the_slot_complete_or_absent(tmp_path, point, naming):
    done = run_child(CRASH_CHILD, point, tmp_path, naming, "POSIX_DIR_FSYNC")
    assert done.returncode == CRASH_EXIT_CODE, (done.returncode, done.stderr[-400:])
    slot_expected, orphans_expected, orphan_size = CRASH_MATRIX[point]
    slot = tmp_path / "slot.json"
    orphans = [entry for entry in tmp_path.iterdir() if entry.name != "slot.json"]
    assert slot.exists() is slot_expected and len(orphans) == orphans_expected
    if slot_expected:
        assert slot.read_bytes() == b"abcdef"
    for orphan in orphans:
        assert store.is_publication_temp_name(orphan.name) is TempNaming[naming] and orphan.stat().st_size == orphan_size
    # Moitié REPRISE sous le profil réel : un slot publié reste binding et se re-confirme ; un slot absent se republie sans toucher aux orphelins.
    snapshot = {orphan.name: orphan.read_bytes() for orphan in orphans}
    if slot_expected:
        with pytest.raises(SlotOccupiedError):
            publish(tmp_path, content=b"autre", naming=TempNaming[naming], durability=POSIX)
        again = confirm(tmp_path, durability=POSIX)
        assert again.state is PublicationState.PUBLISHED_DURABLE and again.posix_dir_fsync_succeeded is True and slot.read_bytes() == b"abcdef"
    else:
        republished = publish(tmp_path, content=b"abcdef", naming=TempNaming[naming], durability=POSIX)
        assert republished.posix_dir_fsync_succeeded is True and slot.read_bytes() == b"abcdef"
    assert {entry.name: entry.read_bytes() for entry in tmp_path.iterdir() if entry.name in snapshot} == snapshot


@posix_only
@linux_only
def test_posix_the_no_follow_option_is_really_in_force_on_linux():
    assert store._LINK_OPTIONS == {"follow_symlinks": False}


# ── Tranche 9 : non-régression — l'extension est ADDITIVE, le code historique est figé ─────────────────────────────────────────

# SHA-256 du texte source de chaque définition historique, relevés sur le commit publié 71095d0 (avant E3-C). Toute modification d'une de ces définitions
# casse ce test : elle exige une décision explicite, pas une retouche discrète.
LEGACY_SOURCE_HASHES = {
    "save_atomic": "c31022c7e0cfa01d78a2fe9d12b442be051dee35aee78af15836644894c61b40",
    "save_atomic_overwrite": "24d26b19beb1337d43cc52f5c2ea63c00002c573c1634dcd775046e1be59e42e",
    "ExclusiveCreationIncompleteError": "2ba1cfa5326a99e8667fed32f9887e813bd25670914a7b7423fa457e49511c79",
    "_DIRECTORY_FSYNC_SUPPORTED": "2624a79218dd40ce0568786c02dd4de06a532d02a8bca287546e906194bbf164",
    "_fsync_directory": "aad49322d4edd932c62efbe77867b97e7321da30ef588ce3629c68e86b5d9538",
    "_save_exclusive_durable": "1668081f930e6c2977c4075498123407208f1f3b644922d11f0f7b6ec9d58698",
    "save_exclusive": "acd6ab1c8055d49929662c232e4fc9feae2ff0f9ec5c4cd4c876a4986ed908f5",
    "load_json_tolerant": "a8e6400990f8497f37ede08c22e0255a3e85b4418ab97c4f498067266dbb86aa",
    "load_tolerant": "97e02dde398537b6c1d01a12432125ed12475114e8447e4ab952ab66181d1719",
    "filesystem_safe": "fc7fa97705ec62ed6b038b095657c9a97ef3dbc68d34c93570d9cb5810b635f4",
    "validate_identifier": "311aac035b53ec75e236a4dd6f0b2f7306a27e4ce2b5d2ac63715a9ae389d608",
    "validate_portable_identifier": "eb69a4922c6cc155b9b4337953997d0abc45ed58e3a5e1f4983ef98465dea0b7",
}


def test_the_historical_definitions_of_the_store_are_byte_for_byte_unchanged():
    import ast
    source = Path(store.__file__).read_text(encoding="utf-8")
    found = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in LEGACY_SOURCE_HASHES:
            found[node.name] = hashlib.sha256(ast.get_source_segment(source, node).encode("utf-8")).hexdigest()
        elif isinstance(node, ast.Assign) and any(getattr(target, "id", "") == "_DIRECTORY_FSYNC_SUPPORTED" for target in node.targets):
            found["_DIRECTORY_FSYNC_SUPPORTED"] = hashlib.sha256(ast.get_source_segment(source, node).encode("utf-8")).hexdigest()
    assert found == LEGACY_SOURCE_HASHES


def test_the_legacy_exclusive_creation_keeps_its_behaviour(tmp_path):
    first = store.save_exclusive(tmp_path / "a.json", {"x": 1}, "legacy")
    assert first == tmp_path / "a.json"
    with pytest.raises(FileExistsError):
        store.save_exclusive(tmp_path / "a.json", {"x": 2}, "legacy")
    assert store.load_json_tolerant(tmp_path / "a.json") == {"x": 1}
    durable = store.save_exclusive(tmp_path / "b.json", {"y": 1}, "legacy", durable=True)
    assert durable == tmp_path / "b.json" and store.load_json_tolerant(durable) == {"y": 1}
    assert [name for name in names(tmp_path) if ".tmp" in name] == []


def test_the_new_section_does_not_change_the_public_names_the_legacy_modules_import():
    for name in ("save_atomic", "save_atomic_overwrite", "save_exclusive", "ExclusiveCreationIncompleteError", "load_json_tolerant", "load_tolerant",
                 "filesystem_safe", "validate_identifier", "validate_portable_identifier"):
        assert callable(getattr(store, name)), name


# ── Tranche 7 : durcissement du lien contre un temporaire remplacé par un lien symbolique ──────────────────────────────────

def test_the_link_never_follows_a_symlink_source_on_platforms_that_can_refuse_it(tmp_path, monkeypatch):
    seen, real = {}, os.link

    def link(source, destination, **kwargs):
        seen.update(kwargs)
        real(source, destination)

    monkeypatch.setattr(os, "link", link)
    monkeypatch.setattr(store, "_LINK_OPTIONS", {"follow_symlinks": False})
    publish(tmp_path)
    assert seen == {"follow_symlinks": False}


def test_the_link_is_called_without_extra_arguments_where_follow_symlinks_is_unsupported(tmp_path, monkeypatch):
    seen, real = {}, os.link

    def link(source, destination, **kwargs):
        seen.update(kwargs)
        real(source, destination)

    monkeypatch.setattr(os, "link", link)
    monkeypatch.setattr(store, "_LINK_OPTIONS", {})
    publish(tmp_path)
    assert seen == {}


def test_the_no_follow_capability_is_decided_once_from_the_real_os_link_not_from_a_wrapper():
    """Revue F-L1 : avant, le test d'identité `os.link in os.supports_follow_symlinks` était refait à chaque appel : tout espion ou mock désactivait la protection."""
    assert store._LINK_OPTIONS == ({"follow_symlinks": False} if os.link in os.supports_follow_symlinks else {})


# ── Tranche 8 : mort RÉELLE du processus (`os._exit`) à chaque point de la matrice de crash 23.10, et course entre processus ─────────────────────

REPO_ROOT = str(Path(store.__file__).resolve().parent)
CRASH_EXIT_CODE = 42
CRASH_CHILD = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
import atomic_json_store as store
point, directory, naming = sys.argv[2], sys.argv[3], sys.argv[4]
def die():
    os._exit(42)
def is_temp(path):
    return store.is_publication_temp_name(os.path.basename(str(path))) is not None
real_open, real_write, real_fsync, real_link, real_unlink = os.open, os.write, os.fsync, os.link, os.unlink
temp_fds = set()
def open_(path, *args, **kwargs):
    fd = real_open(path, *args, **kwargs)
    if is_temp(path):
        temp_fds.add(fd)
        if point == "after_temp_create":
            die()
    return fd
def write_(fd, data):
    if fd in temp_fds and point == "partial_write":
        real_write(fd, bytes(data[:3]))
        die()
    return real_write(fd, data)
directory_syncs = {"count": 0}
def fsync_(fd):
    if fd in temp_fds and point == "before_file_fsync":
        die()
    if fd not in temp_fds:
        directory_syncs["count"] += 1       # profil POSIX : barrière initiale = 1er fsync de répertoire, barrière finale = 2e
        if point == "initial_barrier" and posix_profile and directory_syncs["count"] == 1:
            die()
    result = real_fsync(fd)
    if fd in temp_fds and point == "after_file_fsync":
        die()
    if fd not in temp_fds and point == "after_final_barrier" and posix_profile and directory_syncs["count"] == 2:
        die()
    return result
def link_(source, destination, *args, **kwargs):
    if point == "before_link":
        die()
    real_link(source, destination, *args, **kwargs)
    if point == "after_link":
        die()
def unlink_(path, *args, **kwargs):
    result = real_unlink(path, *args, **kwargs)
    if is_temp(path) and point == "after_temp_removal":
        die()
    return result
barrier_calls = {"count": 0}
def barrier(path):
    barrier_calls["count"] += 1
    if point == "initial_barrier" and barrier_calls["count"] == 1:
        die()
    if point == "after_final_barrier" and barrier_calls["count"] == 2:
        die()
posix_profile = len(sys.argv) > 5 and sys.argv[5] == "POSIX_DIR_FSYNC"
os.open, os.write, os.fsync, os.link, os.unlink = open_, write_, fsync_, link_, unlink_
store._simulated_directory_barrier = barrier
profile = store.DurabilityProfile[sys.argv[5]] if len(sys.argv) > 5 else store.DurabilityProfile.SIMULATED_DURABLE
store.publish_bytes_by_link(os.path.join(directory, "slot.json"), b"abcdef", durability=profile, naming=store.TempNaming[naming], kind="k")
os._exit(0)
'''
# point de crash -> (slot présent, nombre d'orphelins, taille du temporaire s'il existe) ; chaque ligne est une ligne de la matrice de 23.10
CRASH_MATRIX = {
    "initial_barrier": (False, 0, None),           # échec de la barrière initiale : rien
    "after_temp_create": (False, 1, 0),            # avant tout octet : temporaire vide
    "partial_write": (False, 1, 3),                # temporaire PARTIEL : jamais lié
    "before_file_fsync": (False, 1, 6),
    "after_file_fsync": (False, 1, 6),
    "before_link": (False, 1, 6),                  # crash avant `os.link` : slot absent
    "after_link": (True, 1, 6),                    # lien fait, aucun fsync de répertoire : PublishedUnconfirmed
    "after_final_barrier": (True, 1, 6),           # fsync fait, temporaire pas encore supprimé
    "after_temp_removal": (True, 0, None),         # tout est fait
}


def run_child(source: str, *arguments, timeout: int = 60):
    import subprocess
    return subprocess.run([sys.executable, "-c", source, REPO_ROOT, *map(str, arguments)], capture_output=True, text=True, timeout=timeout)


@pytest.mark.parametrize("naming", ["EXPOSURE", "REGISTRY"])
@pytest.mark.parametrize("point", list(CRASH_MATRIX))
def test_a_real_process_death_at_each_matrix_point_leaves_the_slot_complete_or_absent_and_recoverable(tmp_path, point, naming):
    done = run_child(CRASH_CHILD, point, tmp_path, naming)
    assert done.returncode == CRASH_EXIT_CODE, (done.returncode, done.stderr[-400:])         # le crash a bien eu lieu au point visé
    slot_expected, orphans_expected, orphan_size = CRASH_MATRIX[point]
    slot = tmp_path / "slot.json"
    orphans = [entry for entry in tmp_path.iterdir() if entry.name != "slot.json"]
    assert slot.exists() is slot_expected and len(orphans) == orphans_expected
    if slot_expected:
        assert slot.read_bytes() == b"abcdef"                                                 # jamais tronqué
    for orphan in orphans:
        assert store.is_publication_temp_name(orphan.name) is TempNaming[naming]              # seuls des orphelins aux noms FERMÉS (tolérés par le scanner)
        assert orphan.stat().st_size == orphan_size
    # Reprise : le slot publié est binding ; un slot absent se republie sans jamais toucher aux orphelins d'un crash antérieur.
    snapshot = {orphan.name: orphan.read_bytes() for orphan in orphans}
    if slot_expected:
        with pytest.raises(SlotOccupiedError):
            publish(tmp_path, content=b"autre", naming=TempNaming[naming])
        assert slot.read_bytes() == b"abcdef"
        assert confirm(tmp_path).state is PublicationState.PUBLISHED_DURABLE and slot.read_bytes() == b"abcdef"
    else:
        publish(tmp_path, content=b"abcdef", naming=TempNaming[naming])
        assert slot.read_bytes() == b"abcdef"
    assert {orphan.name: orphan.read_bytes() for orphan in tmp_path.iterdir() if orphan.name in snapshot} == snapshot


RACE_CHILD = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
import atomic_json_store as store
directory, go, index = sys.argv[2], sys.argv[3], sys.argv[4]
while not os.path.exists(go):
    time.sleep(0.001)
try:
    store.publish_bytes_by_link(os.path.join(directory, "slot.json"), ("writer-" + index).encode(), durability=store.DurabilityProfile.SIMULATED_DURABLE,
                                naming=store.TempNaming.EXPOSURE, kind="k")
    print("WON")
except store.SlotOccupiedError:
    print("OCCUPIED")
except BaseException as error:
    print("OTHER", type(error).__name__, error)
'''


def test_concurrent_processes_racing_for_one_slot_have_exactly_one_winner_and_a_complete_slot(tmp_path):
    import subprocess
    writers = 6
    for round_number in range(3):
        directory = tmp_path / f"round{round_number}"
        directory.mkdir()
        go = tmp_path / f"go{round_number}"
        children = [subprocess.Popen([sys.executable, "-c", RACE_CHILD, REPO_ROOT, str(directory), str(go), str(index)], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True) for index in range(writers)]
        go.write_bytes(b"")
        outputs = [child.communicate(timeout=60)[0].strip() for child in children]
        assert all(child.returncode == 0 for child in children), outputs
        assert sorted(outputs).count("WON") == 1 and sorted(outputs).count("OCCUPIED") == writers - 1, outputs
        winner = (directory / "slot.json").read_bytes()
        assert winner.startswith(b"writer-") and names(directory) == ["slot.json"]            # un seul gagnant, slot complet, aucun orphelin laissé par les perdants


def test_the_exception_hierarchy_distinguishes_every_outcome():
    for cls in (PlatformNotQualifiedError, PublicationNotStartedError, SlotOccupiedError, PublishedUnconfirmedError, SlotAbsentError, SlotContentMismatchError):
        assert issubclass(cls, LinkPublicationError)
    assert issubclass(SlotOccupiedError, FileExistsError)           # compatible avec les appelants qui attendent le refus d'exclusivité historique (23.13)
    assert not issubclass(PublishedUnconfirmedError, FileExistsError)
    assert not issubclass(PublicationNotStartedError, SlotOccupiedError)
    assert not issubclass(PublishedUnconfirmedError, PublicationNotStartedError)


# ── Tranche 10 : corrections après revues indépendantes et campagne de mutation ──────────────────────────────────────────

def test_only_the_occupied_slot_is_an_oserror_so_a_retry_loop_on_oserror_cannot_swallow_an_unconfirmed_publication():
    """Revue A3 / B-M7 : « étape suivante interdite » après `PublishedUnconfirmed` (23.10). Un `except OSError: republier` ne doit pas l'attraper."""
    assert not issubclass(LinkPublicationError, OSError)
    for cls in (PlatformNotQualifiedError, PublicationNotStartedError, PublishedUnconfirmedError, SlotAbsentError, SlotContentMismatchError):
        assert not issubclass(cls, OSError), cls
    assert issubclass(SlotOccupiedError, OSError)                    # via FileExistsError (23.13)


def test_an_occupied_slot_error_is_a_genuine_file_exists_error_with_its_errno(tmp_path):
    error = SlotOccupiedError("occupé", tmp_path / "slot.json")
    assert isinstance(error, FileExistsError) and error.errno == errno.EEXIST and error.destination == tmp_path / "slot.json"


def test_every_failure_declares_whether_a_replay_is_safe_and_whether_the_slot_is_binding():
    expected = {PlatformNotQualifiedError: (False, False), PublicationNotStartedError: (True, False), SlotOccupiedError: (False, True),
                PublishedUnconfirmedError: (False, True), SlotAbsentError: (False, False), SlotContentMismatchError: (False, True)}
    assert {cls: (cls.replay_safe, cls.slot_is_binding) for cls in expected} == expected


def sample_errors(tmp_path):
    slot = tmp_path / "slot.json"
    publication = LinkPublication(slot, PublicationState.PUBLISHED_UNCONFIRMED, SIMULATED, PublicationOperation.PUBLISHED,
                                  FileIdentity(1, 2, 3, "0" * 64), "p" * 32, 7, tmp_path / ".exposure.tmp.x", TempDisposition.KEPT_UNCONFIRMED)
    return [PlatformNotQualifiedError("plateforme", slot),
            PublicationNotStartedError("pas démarré", slot, stage=PublicationStage.LINK, temp_disposition=TempDisposition.REMOVED, temp_path=tmp_path / "t",
                                       filesystem_not_qualified=True),
            SlotOccupiedError("occupé", slot, temp_disposition=TempDisposition.REMOVED, temp_path=tmp_path / "t"),
            PublishedUnconfirmedError("non confirmé", slot, publication=publication, reason=store.UnconfirmedReason.SLOT_MISSING),
            SlotAbsentError("absent", slot), SlotContentMismatchError("différent", slot)]


def test_every_failure_survives_pickling_and_copying_with_all_its_facts(tmp_path):
    """Revue A2 : un échec levé dans un processus enfant (`ProcessPoolExecutor`) ne doit pas se perdre à la frontière."""
    import copy
    import pickle
    for error in sample_errors(tmp_path):
        for clone in (pickle.loads(pickle.dumps(error)), copy.copy(error), copy.deepcopy(error)):
            assert type(clone) is type(error) and str(clone) == str(error) and clone.destination == error.destination and clone.stage == error.stage
            assert clone.__dict__ == error.__dict__


def test_a_slot_deleted_during_the_final_barrier_is_unconfirmed_not_a_raw_error(tmp_path, monkeypatch, descriptors):
    barrier_script(monkeypatch, None, lambda: (tmp_path / "slot.json").unlink())
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert unconfirmed.value.reason is store.UnconfirmedReason.SLOT_MISSING and unconfirmed.value.publication.temp_path.exists()
    assert unconfirmed.value.publication.temp_disposition is TempDisposition.KEPT_UNCONFIRMED


def test_a_slot_replaced_during_the_final_barrier_is_never_reported_durable(tmp_path, monkeypatch, descriptors):
    def replace():
        slot = tmp_path / "slot.json"
        slot.unlink()
        slot.write_bytes(b"INTRUS")

    barrier_script(monkeypatch, None, replace)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert unconfirmed.value.reason is store.UnconfirmedReason.SLOT_IDENTITY_CHANGED and (tmp_path / "slot.json").read_bytes() == b"INTRUS"


def test_no_final_barrier_is_run_for_a_slot_that_is_already_wrong_right_after_the_link(tmp_path, monkeypatch, descriptors):
    calls = barrier_script(monkeypatch)
    after_link(monkeypatch, lambda destination, temp: (destination.unlink(), destination.write_bytes(b"intrus")))
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert unconfirmed.value.reason is store.UnconfirmedReason.SLOT_IDENTITY_CHANGED and len(calls) == 1      # la barrière de lecture seule


def test_a_parent_removed_during_the_final_barrier_is_unconfirmed(tmp_path, monkeypatch, descriptors):
    directory = tmp_path / "dir"
    directory.mkdir()
    barrier_script(monkeypatch, None, lambda: directory.rename(tmp_path / "moved"))
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        store.publish_bytes_by_link(directory / "slot.json", b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert unconfirmed.value.reason is store.UnconfirmedReason.PARENT_CHANGED


def test_a_parent_replaced_right_after_the_link_is_reported_as_a_parent_change(tmp_path, monkeypatch, descriptors):
    directory = tmp_path / "dir"
    directory.mkdir()

    def swap(destination, temp):
        directory.rename(tmp_path / "old")
        directory.mkdir()

    after_link(monkeypatch, swap)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        store.publish_bytes_by_link(directory / "slot.json", b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert unconfirmed.value.reason is store.UnconfirmedReason.PARENT_CHANGED


def test_a_temporary_name_removed_by_a_third_party_after_the_link_is_a_link_count_anomaly(tmp_path, monkeypatch, descriptors):
    after_link(monkeypatch, lambda destination, temp: temp.unlink())
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert unconfirmed.value.reason is store.UnconfirmedReason.LINK_COUNT_ANOMALY


def test_bytes_appended_to_the_slot_after_the_link_are_a_content_change(tmp_path, monkeypatch, descriptors):
    def append(destination, temp):
        with open(destination, "ab") as handle:
            handle.write(b"X")

    after_link(monkeypatch, append)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path, content=b"abcdef")
    assert unconfirmed.value.reason is store.UnconfirmedReason.CONTENT_CHANGED


def test_a_slot_that_cannot_be_read_back_is_unconfirmed_with_its_own_reason(tmp_path, monkeypatch, descriptors):
    import builtins
    real_open = builtins.open

    def refusing(file, *args, **kwargs):
        if Path(file) == tmp_path / "slot.json":
            raise PermissionError(errno.EACCES, "lecture refusée")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", refusing)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        publish(tmp_path)
    assert unconfirmed.value.reason is store.UnconfirmedReason.SLOT_UNREADABLE


@pytest.mark.parametrize("error", [OSError(errno.EIO, "x"), FileExistsError(errno.EEXIST, "x")], ids=["EIO", "spurious_EEXIST"])
def test_a_link_error_raised_after_the_link_really_happened_is_resolved_by_observing_the_slot(tmp_path, monkeypatch, descriptors, error):
    """Revue A6 / B-M2 : `EIO` ou `EEXIST` parasite après un lien abouti (retransmission) : le slot porte l'inode du temporaire → c'est NOTRE lien."""
    real = os.link

    def link_then_fail(source, destination, *args, **kwargs):
        real(source, destination, *args, **kwargs)
        raise error

    monkeypatch.setattr(os, "link", link_then_fail)
    result = publish(tmp_path)
    assert result.state is PublicationState.PUBLISHED_DURABLE and (tmp_path / "slot.json").read_bytes() == b"abcdef" and names(tmp_path) == ["slot.json"]


def test_a_link_error_with_a_foreign_file_at_the_slot_is_still_an_occupied_slot_and_nothing_foreign_is_touched(tmp_path, monkeypatch, descriptors):
    (tmp_path / "slot.json").write_bytes(b"autre")
    with pytest.raises(SlotOccupiedError) as occupied:
        publish(tmp_path)
    assert (tmp_path / "slot.json").read_bytes() == b"autre" and occupied.value.temp_disposition is TempDisposition.REMOVED


def test_a_temporary_replaced_by_another_file_before_the_link_is_refused_and_the_foreign_file_is_kept(tmp_path, monkeypatch, descriptors):
    real_close, real_open, temp_fds = os.close, os.open, set()

    def tracking_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if store.is_publication_temp_name(Path(path).name) is not None:
            temp_fds.add((fd, Path(path)))
        return fd

    def swapping_close(fd):
        real_close(fd)
        for tracked_fd, temp in list(temp_fds):
            if tracked_fd == fd:
                temp_fds.discard((tracked_fd, temp))
                other = tmp_path / "autre-fichier"
                other.write_bytes(b"autre")
                os.replace(other, temp)                                               # nouvel inode, même nom

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "close", swapping_close)
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path)
    assert refusal.value.stage is PublicationStage.LINK and refusal.value.temp_disposition is TempDisposition.IDENTITY_MISMATCH_KEPT
    assert refusal.value.temp_path.read_bytes() == b"autre" and not (tmp_path / "slot.json").exists()


def test_a_failed_close_of_the_temporary_closes_the_descriptor_exactly_once(tmp_path, monkeypatch):
    real_close, real_open, temp_fds, closes = os.close, os.open, set(), []

    def tracking_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if store.is_publication_temp_name(Path(path).name) is not None:
            temp_fds.add(fd)
        return fd

    def failing_close(fd):
        if fd in temp_fds:
            closes.append(fd)
            real_close(fd)
            raise OSError(errno.EIO, "close en échec")
        return real_close(fd)

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "close", failing_close)
    with pytest.raises(PublicationNotStartedError):
        publish(tmp_path)
    assert len(closes) == 1


def test_a_temporary_name_that_already_exists_is_never_opened_for_writing(tmp_path, monkeypatch, descriptors):
    """`O_EXCL` : un fichier déjà présent sous le nom tiré n'est jamais tronqué ni réutilisé ; la publication retire un NOUVEAU nom."""
    existing = tmp_path / (".exposure.tmp." + "a" * 32)
    existing.write_bytes(b"orphelin")
    names_to_use = iter([existing.name, ".exposure.tmp." + "b" * 32])
    monkeypatch.setattr(store, "_new_temp_name", lambda naming: next(names_to_use))
    result = publish(tmp_path)
    assert existing.read_bytes() == b"orphelin" and result.temp_path.name == ".exposure.tmp." + "b" * 32 and (tmp_path / "slot.json").read_bytes() == b"abcdef"


def test_a_registry_temporary_name_must_be_a_canonical_uuid4_to_be_recognised():
    ok = ".registry.tmp.12345678-1234-4234-8234-123456789abc"
    assert store.is_publication_temp_name(ok) is TempNaming.REGISTRY
    for bad in (".registry.tmp.12345678-1234-1234-8234-123456789abc", ".registry.tmp.12345678-1234-4234-c234-123456789abc",
                ".registry.tmp.12345678123442348234123456789abc", ".registry.tmp.12345678-1234-4234-8234-123456789ABC", ok + ".json"):
        assert store.is_publication_temp_name(bad) is None, bad


def test_the_read_barrier_refuses_a_parent_traversal(tmp_path):
    with pytest.raises(ValueError):
        store.directory_read_barrier(tmp_path / ".." / tmp_path.name, durability=SIMULATED)


@pytest.mark.parametrize("destination", ["", ".", "SEPARATOR"], ids=["empty", "dot", "root"])
def test_a_destination_without_a_file_name_is_refused(tmp_path, destination):
    target = tmp_path.anchor if destination == "SEPARATOR" else destination
    with pytest.raises(ValueError):
        store.publish_bytes_by_link(target, b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")


def test_a_directory_whose_identity_changes_while_it_is_opened_is_refused(tmp_path, posix_profile, monkeypatch, descriptors):
    scratch = tmp_path.parent / "identity_scratch.bin"
    scratch.write_bytes(b"")

    def shifting_open(path):
        return os.open(str(scratch), os.O_RDWR | getattr(os, "O_BINARY", 0)), (-1, -1)

    monkeypatch.setattr(store, "_open_posix_directory_descriptor", shifting_open)
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path, durability=POSIX)
    assert refusal.value.stage is PublicationStage.PREFLIGHT and names(tmp_path) == []


def test_a_failing_close_while_refusing_a_shifting_directory_still_reports_the_refusal(tmp_path, posix_profile, monkeypatch, descriptors):
    """Revue E-LOW-3 : la fermeture du descripteur ouvert pour une identité qui a changé passe aussi par la fermeture silencieuse."""
    scratch = tmp_path.parent / "identity_scratch_2.bin"
    scratch.write_bytes(b"")
    real_close, opened = os.close, []

    def shifting_open(path):
        fd = os.open(str(scratch), os.O_RDWR | getattr(os, "O_BINARY", 0))
        opened.append(fd)
        return fd, (-1, -1)

    def failing_close(fd):
        real_close(fd)
        if fd in opened:
            raise OSError(errno.EIO, "close en échec")

    monkeypatch.setattr(store, "_open_posix_directory_descriptor", shifting_open)
    monkeypatch.setattr(os, "close", failing_close)
    with pytest.raises(PublicationNotStartedError) as refusal:
        publish(tmp_path, durability=POSIX)
    assert refusal.value.stage is PublicationStage.PREFLIGHT and names(tmp_path) == []


def test_closing_a_directory_anchor_twice_is_harmless(tmp_path, monkeypatch, descriptors):
    fd = os.open(str(tmp_path / "scratch"), os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0))
    anchor = store._DirectoryAnchor(tmp_path, (1, 1), fd)
    closes, real_close = [], os.close
    monkeypatch.setattr(os, "close", lambda descriptor: (closes.append(descriptor), real_close(descriptor))[1])
    anchor.close()
    anchor.close()
    assert closes == [fd] and not descriptors                                         # UNE seule fermeture : un numéro de descripteur recyclé n'est jamais refermé


@pytest.mark.skipif(os.name == "posix", reason="sous POSIX le profil est disponible")
def test_the_posix_reconfirmation_is_refused_on_a_platform_without_directory_fsync(tmp_path):
    (tmp_path / "slot.json").write_bytes(b"abcdef")
    with pytest.raises(PlatformNotQualifiedError):
        confirm(tmp_path, durability=POSIX)


@pytest.mark.parametrize("operation", ["publish", "confirm", "barrier"])
def test_the_posix_profile_is_refused_on_macos_where_fsync_is_not_a_full_flush(tmp_path, posix_profile, monkeypatch, operation):
    monkeypatch.setattr(sys, "platform", "darwin")
    (tmp_path / "slot.json").write_bytes(b"abcdef")
    with pytest.raises(PlatformNotQualifiedError):
        if operation == "publish":
            publish(tmp_path / "sub", durability=POSIX)
        elif operation == "confirm":
            confirm(tmp_path, durability=POSIX)
        else:
            store.directory_read_barrier(tmp_path, durability=POSIX)


def test_the_slot_is_synced_before_the_directory_when_it_is_reconfirmed_under_the_posix_profile(tmp_path, posix_profile, monkeypatch):
    """Revue A5 : un `fsync` de répertoire ne persiste pas les données du fichier ; un slot qui n'a pas été écrit par cette primitive doit être synchronisé."""
    published_slot(tmp_path)
    events = record_events(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "_fsync_slot_file", lambda path: events.append(("fsync_slot", Path(path))))
    confirm(tmp_path, durability=POSIX)
    assert events == [("fsync_slot", tmp_path / "slot.json"), "fsync_directory"]


def test_a_failing_slot_sync_during_reconfirmation_is_unconfirmed_and_skips_the_directory_barrier(tmp_path, posix_profile, monkeypatch):
    published_slot(tmp_path)
    events = record_events(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "_fsync_slot_file", lambda path: (_ for _ in ()).throw(OSError(errno.EIO, "fsync du slot en échec")))
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        confirm(tmp_path, durability=POSIX)
    assert unconfirmed.value.reason is store.UnconfirmedReason.FILE_FSYNC_FAILED and events == []


def test_the_simulated_reconfirmation_does_not_sync_the_slot_file(tmp_path, monkeypatch):
    published_slot(tmp_path)
    monkeypatch.setattr(store, "_fsync_slot_file", lambda path: pytest.fail("aucun fsync de fichier sous le profil simulé"))
    confirm(tmp_path)


def test_a_slot_replaced_during_the_reconfirmation_barrier_is_unconfirmed(tmp_path, monkeypatch):
    slot, first = published_slot(tmp_path)

    def replace():
        other = tmp_path / "autre"
        other.write_bytes(b"abcdef")                                                  # mêmes octets, autre fichier
        os.replace(other, slot)

    barrier_script(monkeypatch, replace)
    with pytest.raises(PublishedUnconfirmedError) as unconfirmed:
        confirm(tmp_path)
    assert unconfirmed.value.reason is store.UnconfirmedReason.SLOT_IDENTITY_CHANGED


def test_a_slot_that_differs_after_the_first_kilobyte_is_not_confirmed(tmp_path):
    original = b"a" * 3000
    (tmp_path / "slot.json").write_bytes(b"a" * 2500 + b"b" * 500)
    with pytest.raises(store.SlotContentMismatchError):
        confirm(tmp_path, content=original)


def test_a_multi_megabyte_slot_is_published_and_reconfirmed_with_exact_size_and_hash(tmp_path):
    content = (b"0123456789abcdef" * 1024) * 160 + b"fin"                           # ≈ 2,6 Mio : plusieurs blocs de lecture
    result = publish(tmp_path, content=content)
    again = confirm(tmp_path, content=content)
    assert result.identity.size == len(content) == again.identity.size and again.identity.sha256 == sha(content)


@pytest.mark.skipif(os.name != "nt", reason="alias de noms propres à Windows")
@pytest.mark.parametrize("name", ["x.json.", "x.json ", "y.tmp ", "z.json:ads", "CON", "nul.json", "COM1.txt", "AUX.", "lpt9"])
def test_windows_alias_and_device_names_are_refused_up_front(tmp_path, name):
    with pytest.raises(ValueError):
        store.publish_bytes_by_link(tmp_path / name, b"x", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert names(tmp_path) == []


def test_a_relative_destination_is_reported_as_an_absolute_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = store.publish_bytes_by_link("slot.json", b"abc", durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert result.destination.is_absolute() and result.destination.samefile(tmp_path / "slot.json")
    monkeypatch.chdir(tmp_path.parent)
    assert confirm_at(result.destination, b"abc").state is PublicationState.PUBLISHED_DURABLE


def confirm_at(path, content: bytes):
    return store.confirm_published_slot(path, expected_sha256=sha(content), durability=SIMULATED)


def test_a_record_too_deep_or_cyclic_is_a_normative_json_refusal_and_creates_nothing(tmp_path):
    deep: dict = {}
    cursor = deep
    for _ in range(5000):
        cursor["a"] = {}
        cursor = cursor["a"]
    cyclic: dict = {}
    cyclic["self"] = cyclic
    for record in (deep, cyclic):
        with pytest.raises(store.NormativeJsonError):
            store.publish_json_by_link(tmp_path / "slot.json", record, durability=SIMULATED, naming=TempNaming.EXPOSURE, kind="k")
    assert names(tmp_path) == []
