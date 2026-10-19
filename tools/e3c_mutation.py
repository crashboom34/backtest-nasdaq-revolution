"""Mutation ciblée E3-C sur une COPIE hors dépôt de `atomic_json_store.py` (aucune écriture dans le dépôt). Usage : python e3c_mutation.py [passe].

Base verte exigée ; « tué » = pytest signale des échecs de test (code 1) ou dépasse le délai (boucle infinie) ; tout autre code non nul (collecte,
environnement) est une ERREUR de mutation, jamais une détection. Les ancres doivent apparaître EXACTEMENT une fois."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(os.environ.get("E3C_REPO", os.getcwd()))
PY = sys.executable
TESTS = ["tests/test_atomic_link_publication.py"]
EXTRA_FILES = ["tests/test_atomic_link_publication.py", "tests/test_atomic_link_publication_consumers.py"]
TARGET = "atomic_json_store.py"
TIMEOUT = 90

M = []


def mut(name, old, new):
    M.append((name, old, new))


# ── Nommage, JSON normatif ──────────────────────────────────────────────────────────────────────────────────────────────
mut("exposure pattern 31 hex", r'EXPOSURE_TEMP_NAME_PATTERN = r"\.exposure\.tmp\.[0-9a-f]{32}"', r'EXPOSURE_TEMP_NAME_PATTERN = r"\.exposure\.tmp\.[0-9a-f]{31}"')
mut("exposure pattern uppercase", r'EXPOSURE_TEMP_NAME_PATTERN = r"\.exposure\.tmp\.[0-9a-f]{32}"', r'EXPOSURE_TEMP_NAME_PATTERN = r"\.exposure\.tmp\.[0-9a-fA-F]{32}"')
mut("registry pattern any version", "-4[0-9a-f]{3}-[89ab]", "-[0-9a-f][0-9a-f]{3}-[89ab]")
mut("registry temp name hex not hyphenated", 'return f".registry.tmp.{uuid.uuid4()}"', 'return f".registry.tmp.{uuid.uuid4().hex}"')
mut("exposure temp name constant", 'return f".exposure.tmp.{uuid.uuid4().hex}"', 'return f".exposure.tmp.{\'0\' * 32}"')
mut("registry temp name constant", 'return f".registry.tmp.{uuid.uuid4()}"', 'return ".registry.tmp.12345678-1234-4234-8234-123456789abc"')
mut("temp recognizer registry dropped", "    if _REGISTRY_TEMP_RE.fullmatch(name):\n        return TempNaming.REGISTRY\n", "")
mut("normative sort_keys off", "text = json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)", "text = json.dumps(record, sort_keys=False, ensure_ascii=False, indent=2, allow_nan=False)")
mut("normative ensure_ascii on", "text = json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)", "text = json.dumps(record, sort_keys=True, ensure_ascii=True, indent=2, allow_nan=False)")
mut("normative indent 4", "text = json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)", "text = json.dumps(record, sort_keys=True, ensure_ascii=False, indent=4, allow_nan=False)")
mut("normative no final newline", 'indent=2, allow_nan=False) + "\\n"\n        return text', 'indent=2, allow_nan=False)\n        return text')
mut("normative root not dict accepted", "    if type(record) is not dict:\n        raise NormativeJsonError", "    if False:\n        raise NormativeJsonError")
mut("normative float accepted", "    if value is None or kind is bool or kind is int or kind is str:", "    if value is None or kind is bool or kind is int or kind is str or kind is float:")
mut("normative tuple accepted", "    if kind is list:", "    if kind is list or kind is tuple:")
mut("normative surrogate accepted", '                value.encode("utf-8")\n', "                pass\n")
mut("normative key type unchecked", "            if type(key) is not str:\n                raise NormativeJsonError", "            if False:\n                raise NormativeJsonError")

# ── Destination, ancre ─────────────────────────────────────────────────────────────────────────────────────────────────
mut("dotdot allowed in destination", "    if \"..\" in path.parts:\n        raise ValueError(f\"composante '..' interdite dans la destination", "    if False:\n        raise ValueError(f\"composante '..' interdite dans la destination")
mut("dotdot allowed in read barrier", "    if \"..\" in path.parts:\n        raise ValueError(f\"composante '..' interdite dans le répertoire", "    if False:\n        raise ValueError(f\"composante '..' interdite dans le répertoire")
mut("empty name allowed", '    if not name or name in (".", ".."):', "    if False:")
mut("exact temp name allowed as destination", "if is_publication_temp_name(name) is not None or folded.endswith", "if folded.endswith")
mut(".tmp suffix allowed as destination", 'or folded.endswith(".tmp") or ".tmp." in folded:', 'or ".tmp." in folded:')
mut(".tmp. infix allowed as destination", 'or folded.endswith(".tmp") or ".tmp." in folded:', 'or folded.endswith(".tmp"):')
mut("casefold dropped", "    folded = name.casefold()", "    folded = name")
mut("parent symlink allowed", "    if _is_symlink_or_reparse_point(info):\n        raise PublicationNotStartedError(f\"{directory} est un lien", "    if False:\n        raise PublicationNotStartedError(f\"{directory} est un lien")
mut("parent not-a-directory allowed", "    if not stat.S_ISDIR(info.st_mode):\n        raise PublicationNotStartedError(f\"{directory} n'est pas un répertoire.\", destination", "    if False:\n        raise PublicationNotStartedError(f\"{directory} n'est pas un répertoire.\", destination")
mut("posix opened identity unchecked", "    if opened_identity != identity:", "    if False:")
mut("reparse attribute ignored", "    return stat.S_ISLNK(info.st_mode) or bool((getattr(info, \"st_file_attributes\", 0) or 0) & _REPARSE_POINT_ATTRIBUTE)", "    return stat.S_ISLNK(info.st_mode)")
mut("symlink mode ignored", "    return stat.S_ISLNK(info.st_mode) or bool(", "    return bool(")
mut("anchor barrier inverted", "        if self.descriptor is None:\n            _simulated_directory_barrier(self.directory)", "        if self.descriptor is not None:\n            _simulated_directory_barrier(self.directory)")
mut('anchor close keeps descriptor', '            descriptor, self.descriptor = self.descriptor, None\n            try:\n                os.close(descriptor)', '            descriptor = self.descriptor\n            try:\n                os.close(descriptor)')

# ── Arguments, plateforme ──────────────────────────────────────────────────────────────────────────────────────────────
mut("content str accepted", "    if type(content) is not bytes:\n        raise TypeError", "    if False:\n        raise TypeError")
mut("content bytes subclass-tolerant", "    if type(content) is not bytes:\n        raise TypeError", "    if not isinstance(content, (bytes, bytearray)):\n        raise TypeError")
mut("naming unchecked", '    _require_member(naming, TempNaming, "naming")\n    directory, name = _split_destination(destination)', "    directory, name = _split_destination(destination)")
mut("enum member check loose", "    if type(value) is not enum_class:", "    if not isinstance(value, (enum_class, str)):")
mut('posix profile allowed off posix (publish)', 'and not _posix_profile_available():\n        raise PlatformNotQualifiedError(\n', 'and False:\n        raise PlatformNotQualifiedError(\n')
mut('posix profile allowed off posix (barrier)', 'and not _posix_profile_available():\n        raise PlatformNotQualifiedError(f"Le profil {durability.value} exige un fsync de répertoire, indisponible sur cette plateforme.", path)', 'and False:\n        raise PlatformNotQualifiedError(f"Le profil {durability.value} exige un fsync de répertoire, indisponible sur cette plateforme.", path)')
mut('posix profile allowed off posix (confirm)', 'and not _posix_profile_available():\n        raise PlatformNotQualifiedError(f"Le profil {durability.value} exige un fsync de répertoire, indisponible sur cette plateforme.", target)', 'and False:\n        raise PlatformNotQualifiedError(f"Le profil {durability.value} exige un fsync de répertoire, indisponible sur cette plateforme.", target)')
mut("precheck skipped", "        if precheck is not None:\n            precheck()", "        if False:\n            precheck()")
mut("initial barrier skipped", "        _run_barrier(anchor, target)\n        if precheck", "        if precheck")
mut("barrier failure swallowed", "    except OSError as error:\n        raise PublicationNotStartedError(f\"barrière de répertoire en échec : {error}\", destination, stage=PublicationStage.BARRIER) from error", "    except OSError:\n        pass")
mut("barrier failure wrong stage", "f\"barrière de répertoire en échec : {error}\", destination, stage=PublicationStage.BARRIER", "f\"barrière de répertoire en échec : {error}\", destination, stage=PublicationStage.PREFLIGHT")
mut("read barrier skipped", "    anchor = _open_anchor(path, durability, path)\n    try:\n        _run_barrier(anchor, path)", "    anchor = _open_anchor(path, durability, path)\n    try:\n        pass")

# ── Temporaire ─────────────────────────────────────────────────────────────────────────────────────────────────────────
mut("O_EXCL dropped", "flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY", "flags = os.O_CREAT | os.O_WRONLY")
mut("temp attempts 1", "_TEMP_CREATE_ATTEMPTS = 3", "_TEMP_CREATE_ATTEMPTS = 1")
mut("temp attempts 5", "_TEMP_CREATE_ATTEMPTS = 3", "_TEMP_CREATE_ATTEMPTS = 5")
mut("temp collision not retried", "        except FileExistsError as error:\n            last_collision = error\n", "        except FileExistsError as error:\n            raise PublicationNotStartedError('x', target, stage=PublicationStage.TEMP_CREATE) from error\n")
mut("temp create error wrong stage", 'f"création du temporaire impossible : {error}", target, stage=PublicationStage.TEMP_CREATE', 'f"création du temporaire impossible : {error}", target, stage=PublicationStage.PREFLIGHT')
mut("write progress unchecked", "            if count <= 0:", "            if count < 0:")
mut("write offset ignored", "            count = os.write(descriptor, view[written:])", "            count = os.write(descriptor, view)")
mut("file fsync skipped", "        stage = PublicationStage.TEMP_FSYNC\n        os.fsync(descriptor)", "        stage = PublicationStage.TEMP_FSYNC\n        pass")
mut("write stage mislabelled", "        stage = PublicationStage.TEMP_WRITE\n        view,", "        stage = PublicationStage.TEMP_FSYNC\n        view,")
mut("close stage mislabelled", "        stage = PublicationStage.TEMP_CLOSE\n        descriptor_open = False", "        stage = PublicationStage.TEMP_FSYNC\n        descriptor_open = False")
mut("failed close double closed", "        descriptor_open = False  # un `close` en échec", "        descriptor_open = True  # un `close` en échec")
mut("descriptor not closed on failure", "        if descriptor_open:\n            try:\n                os.close(descriptor)", "        if False:\n            try:\n                os.close(descriptor)")
mut("own temp not removed on failure", "else _remove_own_temp(temp_path, identity)[0]\n", "else TempDisposition.REMOVED\n")
mut("interrupt wrapped", "        if isinstance(error, OSError):\n            raise PublicationNotStartedError(f\"échec à l'étape", "        if True:\n            raise PublicationNotStartedError(f\"échec à l'étape")
mut("temp identity not taken", "        identity = (info.st_dev, info.st_ino)\n        stage = PublicationStage.TEMP_WRITE", "        identity = None\n        stage = PublicationStage.TEMP_WRITE")

# ── Contrôle avant le lien ─────────────────────────────────────────────────────────────────────────────────────────────
mut("pre-link parent identity ignored", "    if _is_symlink_or_reparse_point(parent) or (parent.st_dev, parent.st_ino) != anchor.identity:\n        return f\"le répertoire", "    if _is_symlink_or_reparse_point(parent):\n        return f\"le répertoire")
mut("pre-link parent link ignored", "    if _is_symlink_or_reparse_point(parent) or (parent.st_dev, parent.st_ino) != anchor.identity:\n        return f\"le répertoire", "    if (parent.st_dev, parent.st_ino) != anchor.identity:\n        return f\"le répertoire")
mut("pre-link temp identity ignored", "    if _is_symlink_or_reparse_point(temp) or (temp.st_dev, temp.st_ino) != temp_identity:", "    if _is_symlink_or_reparse_point(temp):")
mut("pre-link temp link ignored", "    if _is_symlink_or_reparse_point(temp) or (temp.st_dev, temp.st_ino) != temp_identity:", "    if (temp.st_dev, temp.st_ino) != temp_identity:")
mut("pre-link problem ignored", "    if problem is not None:\n        disposition, _ = _remove_own_temp(temp_path, temp_identity)\n        raise PublicationNotStartedError(problem", "    if False:\n        disposition, _ = _remove_own_temp(temp_path, temp_identity)\n        raise PublicationNotStartedError(problem")
mut("pre-link problem keeps temp", "    if problem is not None:\n        disposition, _ = _remove_own_temp(temp_path, temp_identity)", "    if problem is not None:\n        disposition = TempDisposition.REMOVED")

# ── Lien ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
mut("link follows symlinks", 'link_options = {"follow_symlinks": False} if os.link in os.supports_follow_symlinks else {}', "link_options = {}")
mut("link always no-follow", 'link_options = {"follow_symlinks": False} if os.link in os.supports_follow_symlinks else {}', 'link_options = {"follow_symlinks": False}')
mut("errno EPERM dropped", '("EPERM", "EXDEV", "ENOTSUP", "EOPNOTSUPP", "ENOSYS")', '("EXDEV", "ENOTSUP", "EOPNOTSUPP", "ENOSYS")')
mut("errno EXDEV dropped", '("EPERM", "EXDEV", "ENOTSUP", "EOPNOTSUPP", "ENOSYS")', '("EPERM", "ENOTSUP", "EOPNOTSUPP", "ENOSYS")')
mut("errno ENOTSUP dropped", '("EPERM", "EXDEV", "ENOTSUP", "EOPNOTSUPP", "ENOSYS")', '("EPERM", "EXDEV", "EOPNOTSUPP", "ENOSYS")')
mut("errno ENOSYS dropped", '("EPERM", "EXDEV", "ENOTSUP", "EOPNOTSUPP", "ENOSYS")', '("EPERM", "EXDEV", "ENOTSUP", "EOPNOTSUPP")')
mut("winerror 1 dropped", "frozenset({1, 50})", "frozenset({50})")
mut("winerror 50 dropped", "frozenset({1, 50})", "frozenset({1})")
mut("winerror ignored", 'or getattr(error, "winerror", None) in _UNSUPPORTED_LINK_WINERRORS', "")
mut("errno ignored", "return error.errno in _UNSUPPORTED_LINK_ERRNOS or getattr", "return getattr")

# ── Après le lien ──────────────────────────────────────────────────────────────────────────────────────────────────────
mut("post-link parent unchecked", "    if not _parent_unchanged(anchor):\n        return UnconfirmedReason.PARENT_CHANGED", "    if False:\n        return UnconfirmedReason.PARENT_CHANGED")
mut("parent check ignores link", "    return not _is_symlink_or_reparse_point(parent) and (parent.st_dev, parent.st_ino) == anchor.identity", "    return (parent.st_dev, parent.st_ino) == anchor.identity")
mut("parent check ignores identity", "    return not _is_symlink_or_reparse_point(parent) and (parent.st_dev, parent.st_ino) == anchor.identity", "    return not _is_symlink_or_reparse_point(parent)")
mut('parent check oserror true', '    try:\n        parent = os.lstat(anchor.directory)\n    except OSError:\n        return False\n    return not _is_symlink', '    try:\n        parent = os.lstat(anchor.directory)\n    except OSError:\n        return True\n    return not _is_symlink')
mut("slot missing ignored", "    except OSError:\n        return UnconfirmedReason.SLOT_MISSING\n", "    except OSError:\n        return None\n")
mut("slot regular unchecked", "    if _is_symlink_or_reparse_point(slot) or not stat.S_ISREG(slot.st_mode):\n        return UnconfirmedReason.SLOT_NOT_REGULAR", "    if False:\n        return UnconfirmedReason.SLOT_NOT_REGULAR")
mut("slot identity unchecked", "    if (slot.st_dev, slot.st_ino) != temp_identity:\n        return UnconfirmedReason.SLOT_IDENTITY_CHANGED", "    if False:\n        return UnconfirmedReason.SLOT_IDENTITY_CHANGED")
mut("nlink unchecked", "    if slot.st_nlink != 2:\n        return UnconfirmedReason.LINK_COUNT_ANOMALY", "    if False:\n        return UnconfirmedReason.LINK_COUNT_ANOMALY")
mut("nlink only upper bound", "    if slot.st_nlink != 2:\n        return UnconfirmedReason.LINK_COUNT_ANOMALY", "    if slot.st_nlink > 2:\n        return UnconfirmedReason.LINK_COUNT_ANOMALY")
mut("content tail unread", "            observed = handle.read(len(content) + 1)", "            observed = handle.read(len(content))")
mut("content unchecked", "    return None if observed == content else UnconfirmedReason.CONTENT_CHANGED", "    return None")
mut('content read error ignored', '    except OSError:\n        return UnconfirmedReason.SLOT_UNREADABLE\n    return None if observed', '    except OSError:\n        return None\n    return None if observed')
mut('post-link problem ignored', '    if anomaly is not None:\n        raise _unconfirmed_error(anomaly, f"Vérification après le lien', '    if False:\n        raise _unconfirmed_error(anomaly, f"Vérification après le lien')
mut("final barrier skipped", "    try:\n        anchor.barrier()\n    except OSError as error:\n        raise _unconfirmed_error(UnconfirmedReason.DIRECTORY_FSYNC_FAILED, f\"fsync du répertoire en échec ({error}).\", target, temp_path, temp_identity,", "    try:\n        pass\n    except OSError as error:\n        raise _unconfirmed_error(UnconfirmedReason.DIRECTORY_FSYNC_FAILED, f\"fsync du répertoire en échec ({error}).\", target, temp_path, temp_identity,")
mut("final barrier failure swallowed", "    except OSError as error:\n        raise _unconfirmed_error(UnconfirmedReason.DIRECTORY_FSYNC_FAILED, f\"fsync du répertoire en échec ({error}).\", target, temp_path, temp_identity,\n                                 content, durability) from error", "    except OSError:\n        pass")
mut("unconfirmed temp removed state", "publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=temp_path, temp_disposition=TempDisposition.KEPT_UNCONFIRMED)", "publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=temp_path, temp_disposition=TempDisposition.REMOVED)")
mut("unconfirmed claims durable", "destination=target, state=PublicationState.PUBLISHED_UNCONFIRMED, durability_profile=durability, operation=PublicationOperation.PUBLISHED,", "destination=target, state=PublicationState.PUBLISHED_DURABLE, durability_profile=durability, operation=PublicationOperation.PUBLISHED,")
mut('unconfirmed not binding', '    slot_is_binding = True\n\n    def __init__(self, message: str, destination: Union[str, Path], *, publication', '    slot_is_binding = False\n\n    def __init__(self, message: str, destination: Union[str, Path], *, publication')
mut("real durability claimed for simulated", "return self.state is PublicationState.PUBLISHED_DURABLE and self.durability_profile is DurabilityProfile.POSIX_DIR_FSYNC", "return self.state is PublicationState.PUBLISHED_DURABLE")
mut("real durability claimed when unconfirmed", "return self.state is PublicationState.PUBLISHED_DURABLE and self.durability_profile is DurabilityProfile.POSIX_DIR_FSYNC", "return self.durability_profile is DurabilityProfile.POSIX_DIR_FSYNC")

# ── Nettoyage du temporaire ─────────────────────────────────────────────────────────────────────────────────────────────
mut("foreign temp deleted", "    if (info.st_dev, info.st_ino) != identity:\n        return TempDisposition.IDENTITY_MISMATCH_KEPT, None", "    if False:\n        return TempDisposition.IDENTITY_MISMATCH_KEPT, None")
mut("removal failure reported as removed", "    except OSError as error:\n        return TempDisposition.REMOVAL_FAILED, str(error)\n    return TempDisposition.REMOVED, None", "    except OSError as error:\n        return TempDisposition.REMOVED, None\n    return TempDisposition.REMOVED, None")
mut("removal failure no message", "    except OSError as error:\n        return TempDisposition.REMOVAL_FAILED, str(error)\n    return TempDisposition.REMOVED, None", "    except OSError as error:\n        return TempDisposition.REMOVAL_FAILED, None\n    return TempDisposition.REMOVED, None")

# ── Re-confirmation ─────────────────────────────────────────────────────────────────────────────────────────────────────
mut("sha regex uppercase", '_SHA256_HEX = re.compile(r"[0-9a-f]{64}")', '_SHA256_HEX = re.compile(r"[0-9a-fA-F]{64}")')
mut("sha regex length", '_SHA256_HEX = re.compile(r"[0-9a-f]{64}")', '_SHA256_HEX = re.compile(r"[0-9a-f]{32,64}")')
mut("sha type unchecked", "    if type(expected_sha256) is not str or not _SHA256_HEX.fullmatch(expected_sha256):", "    if not _SHA256_HEX.fullmatch(str(expected_sha256)):")
mut("identity type unchecked", "    if expected_identity is not None and type(expected_identity) is not FileIdentity:", "    if False:")
mut("confirm absent slot not refused", "        except FileNotFoundError as error:\n            raise SlotAbsentError", "        except FileNotFoundError as error:\n            raise SlotContentMismatchError")
mut("confirm regular unchecked", "        if _is_symlink_or_reparse_point(slot) or not stat.S_ISREG(slot.st_mode):\n            raise SlotContentMismatchError", "        if False:\n            raise SlotContentMismatchError")
mut("confirm hash unchecked", "        if observed_sha256 != expected_sha256:", "        if False:")
mut("confirm identity unchecked", "        if expected_identity is not None and expected_identity != identity:", "        if False:")
mut("confirm nlink unchecked", "        if slot.st_nlink > 2:", "        if False:")
mut("confirm nlink too strict", "        if slot.st_nlink > 2:", "        if slot.st_nlink > 1:")
mut("confirm nlink too lax", "        if slot.st_nlink > 2:", "        if slot.st_nlink > 3:")
mut("confirm barrier skipped", "        try:\n            anchor.barrier()\n        except OSError as error:\n            raise unconfirmed(", "        try:\n            pass\n        except OSError as error:\n            raise unconfirmed(")
mut("confirm barrier failure swallowed", "        except OSError as error:\n            raise unconfirmed(UnconfirmedReason.DIRECTORY_FSYNC_FAILED, f\"fsync du répertoire en échec ({error}).\") from error", "        except OSError:\n            pass")
mut("confirm parent unchecked", "        if not _parent_unchanged(anchor):\n            raise unconfirmed(", "        if False:\n            raise unconfirmed(")
mut("confirm slot reidentity unchecked", "        if (again.st_dev, again.st_ino) != (slot.st_dev, slot.st_ino):", "        if False:")
mut("confirm operation published", "destination=target, state=PublicationState.PUBLISHED_DURABLE, durability_profile=durability, operation=PublicationOperation.RECONFIRMED,\n            identity=identity, publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=None, temp_disposition=TempDisposition.NOT_CREATED)\n    finally:", "destination=target, state=PublicationState.PUBLISHED_DURABLE, durability_profile=durability, operation=PublicationOperation.PUBLISHED,\n            identity=identity, publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=None, temp_disposition=TempDisposition.NOT_CREATED)\n    finally:")
mut("confirm publication id constant", "identity=identity, publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=None, temp_disposition=TempDisposition.NOT_CREATED)\n    finally:", "identity=identity, publication_id='0' * 32, writer_pid=os.getpid(), temp_path=None, temp_disposition=TempDisposition.NOT_CREATED)\n    finally:")
mut("confirm hashes only a prefix", "            digest.update(chunk)\n            size += len(chunk)", "            digest.update(chunk[:1024])\n            size += len(chunk)")
mut("confirm size miscounted", "            digest.update(chunk)\n            size += len(chunk)", "            digest.update(chunk)\n            size += 1")


# ── Ajouts après revues et première campagne ────────────────────────────────────────────────────────────────────────────
mut("occupied slot keeps temp / link error keeps temp", "        disposition, _ = _remove_own_temp(temp_path, temp_identity)\n        if isinstance(link_error, FileExistsError):", "        disposition = TempDisposition.REMOVED\n        if isinstance(link_error, FileExistsError):")
mut("link error not qualified flag", "filesystem_not_qualified=_link_is_unsupported(link_error)) from link_error", "filesystem_not_qualified=False) from link_error")
mut("link error always not qualified", "filesystem_not_qualified=_link_is_unsupported(link_error)) from link_error", "filesystem_not_qualified=True) from link_error")
mut("post-barrier check skipped", "    if anomaly is not None:\n        raise _unconfirmed_error(anomaly, f\"Vérification après la barrière", "    if False:\n        raise _unconfirmed_error(anomaly, f\"Vérification après la barrière")
mut("durable identity wrong size", "identity=FileIdentity(temp_identity[0], temp_identity[1], len(content), hashlib.sha256(content).hexdigest()),\n        publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=temp_path, temp_disposition=disposition,", "identity=FileIdentity(temp_identity[0], temp_identity[1], 0, hashlib.sha256(content).hexdigest()),\n        publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=temp_path, temp_disposition=disposition,")
mut("durable identity wrong hash", "identity=FileIdentity(temp_identity[0], temp_identity[1], len(content), hashlib.sha256(content).hexdigest()),\n        publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=temp_path, temp_disposition=disposition,", "identity=FileIdentity(temp_identity[0], temp_identity[1], len(content), hashlib.sha256(b'').hexdigest()),\n        publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=temp_path, temp_disposition=disposition,")
mut("unconfirmed identity wrong size", "identity=FileIdentity(temp_identity[0], temp_identity[1], len(content), hashlib.sha256(content).hexdigest()),\n        publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=temp_path, temp_disposition=TempDisposition.KEPT_UNCONFIRMED)", "identity=FileIdentity(temp_identity[0], temp_identity[1], 0, hashlib.sha256(content).hexdigest()),\n        publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=temp_path, temp_disposition=TempDisposition.KEPT_UNCONFIRMED)")
mut("temp cleanup skipped on success", "    disposition, cleanup_error = _remove_own_temp(temp_path, temp_identity)\n    return LinkPublication(", "    disposition, cleanup_error = TempDisposition.REMOVED, None\n    return LinkPublication(")
mut("slot unreadable mislabelled", "        return UnconfirmedReason.SLOT_UNREADABLE", "        return UnconfirmedReason.CONTENT_CHANGED")
mut("confirm slot fsync skipped", "        if durability is DurabilityProfile.POSIX_DIR_FSYNC:\n            try:\n                _fsync_slot_file(target)", "        if False:\n            try:\n                _fsync_slot_file(target)")
mut("confirm slot fsync failure swallowed", "            except OSError as error:\n                raise unconfirmed(UnconfirmedReason.FILE_FSYNC_FAILED, f\"fsync du fichier du slot en échec ({error}).\") from error", "            except OSError:\n                pass")
mut("confirm slot fsync always", "        if durability is DurabilityProfile.POSIX_DIR_FSYNC:\n            try:\n                _fsync_slot_file(target)", "        if True:\n            try:\n                _fsync_slot_file(target)")
mut("macos allowed", '    return _DIRECTORY_FSYNC_SUPPORTED and sys.platform != "darwin"', "    return _DIRECTORY_FSYNC_SUPPORTED")
mut("windows trailing dot or space allowed", '        if name != name.rstrip(" .") or ":" in name:', '        if ":" in name:')
mut("windows colon allowed", '        if name != name.rstrip(" .") or ":" in name:', '        if name != name.rstrip(" ."):')
mut("windows device stems allowed", '        if name.split(".")[0].rstrip(" ").upper() in _WINDOWS_DEVICE_STEMS:', "        if False:")
mut("windows device stem case", '        if name.split(".")[0].rstrip(" ").upper() in _WINDOWS_DEVICE_STEMS:', '        if name.split(".")[0].rstrip(" ") in _WINDOWS_DEVICE_STEMS:')
mut("destination not made absolute", "    return Path(os.path.abspath(path.parent)), name", "    return path.parent, name")
mut("recursion not wrapped", '    except RecursionError as error:\n        raise NormativeJsonError("imbrication', '    except ZeroDivisionError as error:\n        raise NormativeJsonError("imbrication')
mut("base error is oserror", "class LinkPublicationError(Exception):", "class LinkPublicationError(OSError):")
mut("not-started not replay safe", "    replay_safe = True\n\n    def __init__(", "    replay_safe = False\n\n    def __init__(")
mut("occupied not binding", "    slot_is_binding = True\n\n    def __init__(self, message: str, destination: Union[str, Path], *, temp_disposition", "    slot_is_binding = False\n\n    def __init__(self, message: str, destination: Union[str, Path], *, temp_disposition")
mut("reduce loses facts", "        return _restore_publication_error, (type(self), self.args, dict(self.__dict__))", "        return type(self), self.args")
mut("restore skips oserror init", "    if isinstance(obj, OSError):\n        OSError.__init__(obj, *args)", "    if False:\n        OSError.__init__(obj, *args)")
mut("restore skips state", "    obj.__dict__.update(state)\n    return obj", "    return obj")
mut("occupied errno dropped", "        FileExistsError.__init__(self, errno.EEXIST, message)", "        FileExistsError.__init__(self, message)")
mut("tmp attempts counted in confirm", "    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, \"O_BINARY\", 0) | getattr(os, \"O_NOFOLLOW\", 0) | getattr(os, \"O_CLOEXEC\", 0))", "    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, \"O_BINARY\", 0) | getattr(os, \"O_CLOEXEC\", 0))")
mut('observation identity ignored', '    ours = not _is_symlink_or_reparse_point(info) and (info.st_dev, info.st_ino) == temp_identity\n', '    ours = not _is_symlink_or_reparse_point(info)\n')
mut('observation symlink ignored', '    ours = not _is_symlink_or_reparse_point(info) and (info.st_dev, info.st_ino) == temp_identity\n', '    ours = (info.st_dev, info.st_ino) == temp_identity\n')
mut('observation error means absent', '    except OSError:\n        return _SLOT_UNOBSERVABLE\n', '    except OSError:\n        return _SLOT_OTHER_OR_ABSENT\n')
mut('observation absence means unobservable', '    except FileNotFoundError:\n        return _SLOT_OTHER_OR_ABSENT\n    except OSError:', '    except FileNotFoundError:\n        return _SLOT_UNOBSERVABLE\n    except OSError:')
mut('link error always treated as our link', '    observed = _observe_slot_after_link_error(target, temp_identity) if link_error is not None else _SLOT_OURS\n', '    observed = _SLOT_OURS\n')
mut('link error never treated as our link', '    observed = _observe_slot_after_link_error(target, temp_identity) if link_error is not None else _SLOT_OURS\n', '    observed = _SLOT_OTHER_OR_ABSENT if link_error is not None else _SLOT_OURS\n')
mut('anchor close error masks', '            except OSError:\n                pass    # le `fsync`', '            except OSError:\n                raise    # le `fsync`')
mut('nul allowed in destination', '        if "\\0" in part:', '        if False:')
mut('fsencode unchecked', '            os.fsencode(part)\n', '            pass\n')
mut('quiet close raises', '    try:\n        os.close(descriptor)\n    except OSError:\n        pass\n\n\ndef _open_posix_directory_descriptor', '    try:\n        os.close(descriptor)\n    except OSError:\n        raise\n\n\ndef _open_posix_directory_descriptor')
mut('windows control chars allowed', '        if any(char in name for char in \'<>"|?*\') or any(ord(char) < 32 for char in name):', '        if any(char in name for char in \'<>"|?*\'):')
mut('windows reserved chars allowed', '        if any(char in name for char in \'<>"|?*\') or any(ord(char) < 32 for char in name):', '        if any(ord(char) < 32 for char in name):')
mut('name length limit raised', '    if (len(name) if os.name == "nt" else len(os.fsencode(name))) > 255:', '    if (len(name) if os.name == "nt" else len(os.fsencode(name))) > 100000:')
mut('name length unchecked', '    if (len(name) if os.name == "nt" else len(os.fsencode(name))) > 255:', '    if False:')
mut('unknown outcome loses cause', '        raise _unconfirmed_error(UnconfirmedReason.LINK_OUTCOME_UNKNOWN, f"erreur du lien ({link_error}) et slot inobservable.", target, temp_path,\n                                 temp_identity, content, durability) from link_error', '        raise _unconfirmed_error(UnconfirmedReason.LINK_OUTCOME_UNKNOWN, f"erreur du lien ({link_error}) et slot inobservable.", target, temp_path,\n                                 temp_identity, content, durability) from None')
mut('unknown outcome claims existence', '    if reason is UnconfirmedReason.LINK_OUTCOME_UNKNOWN:\n        suffix', '    if False:\n        suffix')
mut('unknown outcome mislabelled', 'raise _unconfirmed_error(UnconfirmedReason.LINK_OUTCOME_UNKNOWN, f"erreur du lien', 'raise _unconfirmed_error(UnconfirmedReason.SLOT_MISSING, f"erreur du lien')
mut('ambiguous errno ESTALE dropped', '("EIO", "ESTALE", "ETIMEDOUT", "EINTR", "ECONNRESET")', '("EIO", "ETIMEDOUT", "EINTR", "ECONNRESET")')
mut('ambiguous errno EIO dropped', '("EIO", "ESTALE", "ETIMEDOUT", "EINTR", "ECONNRESET")', '("ESTALE", "ETIMEDOUT", "EINTR", "ECONNRESET")')
mut('ambiguous errno ignored', '    if observed == _SLOT_UNOBSERVABLE and link_error.errno in _AMBIGUOUS_LINK_ERRNOS and not isinstance(link_error, FileExistsError):', '    if observed == _SLOT_UNOBSERVABLE and not isinstance(link_error, FileExistsError):')
mut('unobservable never unconfirmed', '    if observed == _SLOT_UNOBSERVABLE and link_error.errno in _AMBIGUOUS_LINK_ERRNOS and not isinstance(link_error, FileExistsError):', '    if False:')
mut('eexist unobservable becomes unconfirmed', '    if observed == _SLOT_UNOBSERVABLE and link_error.errno in _AMBIGUOUS_LINK_ERRNOS and not isinstance(link_error, FileExistsError):', '    if observed == _SLOT_UNOBSERVABLE and link_error.errno in _AMBIGUOUS_LINK_ERRNOS:')


def main() -> int:
    only = os.environ.get("MUT_ONLY")
    mutants = M
    if only:
        wanted = set(only.split("|"))
        mutants = [item for item in M if item[0] in wanted]
    shards, shard = int(os.environ.get("MUT_SHARDS", "1")), int(os.environ.get("MUT_SHARD", "0"))
    mutants = mutants[shard::shards]
    print(f"shard {shard}/{shards} : {len(mutants)} mutants", flush=True)
    tests = TESTS if not os.environ.get("MUT_ALL_TESTS") else EXTRA_FILES
    work = Path(tempfile.mkdtemp(prefix="e3cm_", dir=tempfile.gettempdir()))
    (work / "tests").mkdir()
    tracked = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines()
    for rel in tracked + EXTRA_FILES + [TARGET]:
        if rel.startswith("frontend/") or (rel.startswith("tests/") and rel not in ("tests/__init__.py", "tests/conftest.py", "tests/gate_v_exposure_support.py")
                                           and rel not in EXTRA_FILES):
            continue
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, work / rel)
    for name in ("pytest.ini",):
        if (REPO / name).exists():
            shutil.copy(REPO / name, work / name)
    original = (REPO / TARGET).read_text(encoding="utf-8")
    target = work / TARGET
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

    def run() -> int:
        try:
            return subprocess.run([PY, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests], cwd=work, env=env, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            return 1

    baseline = run()
    if baseline != 0:
        sys.exit(f"base non verte (code {baseline}) : mutation invalide ({work})")
    print("baseline green", work, flush=True)
    results = []
    try:
        for name, old, new in mutants:
            count = original.count(old)
            if count != 1:
                results.append((name, "ANCHOR-ERROR", count))
                continue
            target.write_text(original.replace(old, new, 1), encoding="utf-8", newline="\n")
            code = run()
            results.append((name, "KILLED" if code == 1 else ("SURVIVED" if code == 0 else f"ERROR-{code}"), ""))
    finally:
        target.write_text(original, encoding="utf-8", newline="\n")
    digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    print("restored identical to repo:", digest(target) == digest(REPO / TARGET))
    for name, status, extra in results:
        if status != "KILLED":
            print(f"{status:12} {name} {extra}")
    print("killed", sum(1 for item in results if item[1] == "KILLED"), "of", len(results))
    shutil.rmtree(work, ignore_errors=True)
    return 0


sys.exit(main())
