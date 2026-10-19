"""Mutation ciblée E3-D sur une COPIE hors dépôt (aucune écriture dans le dépôt). Usage : python e3d_mutation.py   (MUT_ONLY="a|b" pour filtrer, MUT_TARGET=model|chain|store|append|views).

Base verte exigée ; « tué » = pytest signale des échecs (code 1) ou dépasse le délai ; tout autre code non nul est une ERREUR. Les ancres doivent apparaître EXACTEMENT une fois.
Une mutation qui survit aux tests rapides est rejouée avec les tests de concurrence multi-processus avant d'être déclarée survivante."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(os.environ.get("E3D_REPO", os.getcwd()))
PY = sys.executable
E3D_MODULES = ["gate_v_registry_model.py", "gate_v_registry_chain.py", "gate_v_registry_store.py", "gate_v_registry_append.py", "gate_v_registry_views.py"]
FAST_TESTS = ["tests/test_gate_v_registry_model.py", "tests/test_gate_v_registry_chain.py", "tests/test_gate_v_registry_store_read.py", "tests/test_gate_v_registry_append.py",
              "tests/test_gate_v_registry_views.py", "tests/test_gate_v_registry_consumption.py", "tests/test_gate_v_registry_posix.py"]
SLOW_TESTS = ["tests/test_gate_v_registry_concurrency.py"]
HELPERS = ["tests/_gate_v_registry_fixtures.py", "tests/_gate_v_registry_worker.py"]
TIMEOUT = 600

M = []


def mut(target, name, old, new):
    M.append((target, name, old, new))


MODEL, CHAIN, STORE, APPEND, VIEWS = ("gate_v_registry_model.py", "gate_v_registry_chain.py", "gate_v_registry_store.py", "gate_v_registry_append.py", "gate_v_registry_views.py")

# ── MODEL ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
mut(MODEL, "genesis prefix colon dropped", 'GENESIS_PREFIX = "gate_v_registry_genesis:"', 'GENESIS_PREFIX = "gate_v_registry_genesis"')
mut(MODEL, "slot digits 7", "SLOT_DIGITS = 6", "SLOT_DIGITS = 7")
mut(MODEL, "slot name prefix match", "match = _SLOT_NAME_RE.fullmatch(name)", "match = _SLOT_NAME_RE.match(name)")
mut(MODEL, "slot name unicode digits", 'r"admission_([0-9]{%d})\\.json"', 'r"admission_(\\d{%d})\\.json"')
mut(MODEL, "seq bool accepted", "if type(value) is not int or not 0 <= value <= MAX_SEQ:", "if not isinstance(value, int) or not 0 <= value <= MAX_SEQ:")
mut(MODEL, "seq upper bound off by one", "or not 0 <= value <= MAX_SEQ:", "or not 0 <= value <= MAX_SEQ + 1:")
mut(MODEL, "seq negative accepted", "or not 0 <= value <= MAX_SEQ:", "or not -1 <= value <= MAX_SEQ:")
mut(MODEL, "instant normalisation unchecked", "    if normalized != value:\n        raise ValueError(f\"{name} doit être sous forme normalisée", "    if False:\n        raise ValueError(f\"{name} doit être sous forme normalisée")
mut(MODEL, "overlap non strict", "return start_a < end_b and start_b < end_a", "return start_a <= end_b and start_b <= end_a")
mut(MODEL, "overlap one sided", "return start_a < end_b and start_b < end_a", "return start_a < end_b")
mut(MODEL, "overlap or", "return start_a < end_b and start_b < end_a", "return start_a < end_b or start_b < end_a")
mut(MODEL, "unknown keys tolerated", "    if unknown or missing:", "    if missing:")
mut(MODEL, "missing keys tolerated", "    if unknown or missing:", "    if unknown:")
mut(MODEL, "version unchecked", "    if record[\"admission_semantics_version\"] != REGISTRY_RECORD_VERSION or type(record[\"admission_semantics_version\"]) is not str:", "    if False:")
mut(MODEL, "registry id unchecked", "or _REGISTRY_ID_RE.fullmatch(record[\"registry_id\"]) is None:", "or False:")
mut(MODEL, "instance id unchecked", "or _INSTANCE_ID_RE.fullmatch(record[\"instance_id\"]) is None:", "or False:")
mut(MODEL, "hex uppercase accepted", '_HEX64_RE = re.compile(r"[0-9a-f]{64}")', '_HEX64_RE = re.compile(r"[0-9a-fA-F]{64}")')
mut(MODEL, "campaign id suffix dropped", 'GATE_V_CAMPAIGN_ID_V2_PREFIX) + r"[0-9a-f]{64}")\n_CONTROL', 'GATE_V_CAMPAIGN_ID_V2_PREFIX) + r".*")\n_CONTROL')
mut(MODEL, "window zero length allowed", "        if not start < end:", "        if not start <= end:")
mut(MODEL, "window order unchecked", "        if not start < end:", "        if False:")
mut(MODEL, "rebind bindings may be equal", '        if record["old_binding_hash"] == record["new_binding_hash"]:', "        if False:")
mut(MODEL, "opaque may be empty", "    if type(value) is not dict or not value:\n        raise ValueError(f\"{name} doit être un objet JSON non vide", "    if type(value) is not dict:\n        raise ValueError(f\"{name} doit être un objet JSON non vide")
mut(MODEL, "opaque depth unbounded", "    if _depth(value) > MAX_OPAQUE_DEPTH:", "    if False:")
mut(MODEL, "record normative check dropped", "        serialize_normative_json(record)       # aucun flottant", "        pass       # aucun flottant")
mut(MODEL, "hash keys unsorted", "return json.dumps(value, sort_keys=True, separators", "return json.dumps(value, sort_keys=False, separators")
mut(MODEL, "hash separators spaced", 'separators=(",", ":"), ensure_ascii=False, allow_nan=False)\n\n\ndef compute_record_content_hash', 'separators=(", ", ": "), ensure_ascii=False, allow_nan=False)\n\n\ndef compute_record_content_hash')
mut(MODEL, "admission id keeps created_at", '_ADMISSION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "campaign_dir_locator", "reservation_seq", "created_at"})', '_ADMISSION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "campaign_dir_locator", "reservation_seq"})')
mut(MODEL, "admission id keeps reservation_seq", '_ADMISSION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "campaign_dir_locator", "reservation_seq", "created_at"})', '_ADMISSION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "campaign_dir_locator", "created_at"})')
mut(MODEL, "admission id keeps locator", '_ADMISSION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "campaign_dir_locator", "reservation_seq", "created_at"})', '_ADMISSION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "reservation_seq", "created_at"})')
mut(MODEL, "admission id keeps prev", '_ADMISSION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "campaign_dir_locator", "reservation_seq", "created_at"})', '_ADMISSION_ID_EXCLUDED = frozenset({"seq", "campaign_dir_locator", "reservation_seq", "created_at"})')
mut(MODEL, "reservation id keeps created_at", '_RESERVATION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "campaign_dir_locator", "created_at"})', '_RESERVATION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "campaign_dir_locator"})')
mut(MODEL, "reservation id keeps locator", '_RESERVATION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "campaign_dir_locator", "created_at"})', '_RESERVATION_ID_EXCLUDED = frozenset({"seq", "prev_content_hash", "created_at"})')
mut(MODEL, "admission id type unchecked", "    if validate_registry_record(record) is not RecordType.ADMISSION:", "    if False:")
mut(MODEL, "reservation id type unchecked", "    if validate_registry_record(record) is not RecordType.RESERVATION:", "    if False:")
mut(MODEL, "record dict subclass accepted", '    if type(record) is not dict:\n        raise ValueError("enregistrement', '    if not isinstance(record, dict):\n        raise ValueError("enregistrement')
mut(MODEL, "text control chars accepted", "or _CONTROL_CHAR_RE.search(value):", ":")
mut(MODEL, "text length unbounded", "or len(value) > maximum", "")
mut(MODEL, "restored head seq unchecked", '        _require_seq(record["restored_head_seq"], "restored_head_seq")', "        pass")
mut(MODEL, "reservation seq unchecked", '        _require_seq(record["reservation_seq"], "reservation_seq")', "        pass")
mut(MODEL, "commitment id unchecked", '_SHORT_TEXT_FIELDS = frozenset({"commitment_id", "attachment_id"})', '_SHORT_TEXT_FIELDS = frozenset({"attachment_id"})')
mut(MODEL, "locator unchecked", '_LONG_TEXT_FIELDS = frozenset({"campaign_dir_locator", "justification"})', '_LONG_TEXT_FIELDS = frozenset({"justification"})')
mut(MODEL, "hex field dropped", '    "restored_head_content_hash"})', '    })')
mut(MODEL, "created_at unchecked", '    _require_instant(record["created_at"], "created_at")', "    pass")

# ── CHAIN ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
mut(CHAIN, "seq unchecked", '    if record["seq"] != expected_seq:', "    if False:")
mut(CHAIN, "prev unchecked", '    if record["prev_content_hash"] != expected_prev:', "    if False:")
mut(CHAIN, "registry id unchecked", '    if record["registry_id"] != chain.registry_id:', "    if False:")
mut(CHAIN, "instance unchecked", '    elif record["instance_id"] != current_instance:', "    elif False:")
mut(CHAIN, "rebind may open chain", "        if expected_seq == 0:", "        if False:")
mut(CHAIN, "rebind may keep instance", '        if record["instance_id"] == current_instance:', "        if False:")
mut(CHAIN, "rebind restored seq unchecked", 'if record["restored_head_seq"] != expected_seq - 1 or record["restored_head_content_hash"] != expected_prev:', 'if record["restored_head_content_hash"] != expected_prev:')
mut(CHAIN, "rebind restored hash unchecked", 'if record["restored_head_seq"] != expected_seq - 1 or record["restored_head_content_hash"] != expected_prev:', 'if record["restored_head_seq"] != expected_seq - 1:')
mut(CHAIN, "uniqueness unchecked", "    if record_type in known:", "    if False:")
mut(CHAIN, "consumed code lost", "RegistryRefusalCode.CAMPAIGN_ALREADY_CONSUMED if record_type is RecordType.CONSUMPTION else", "RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED if False else")
mut(CHAIN, "registered code lost", "else RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED\n", "else RegistryRefusalCode.CAMPAIGN_ALREADY_CONSUMED\n")
mut(CHAIN, "overlap unchecked", "        if other.record_type in (RecordType.RESERVATION, RecordType.ADMISSION) and other.campaign_id != campaign_id:", "        if False:")
mut(CHAIN, "overlap includes same campaign", " and other.campaign_id != campaign_id:", ":")
mut(CHAIN, "overlap ignores reservations", "if other.record_type in (RecordType.RESERVATION, RecordType.ADMISSION)", "if other.record_type in (RecordType.ADMISSION,)")
mut(CHAIN, "overlap ignores admissions", "if other.record_type in (RecordType.RESERVATION, RecordType.ADMISSION)", "if other.record_type in (RecordType.RESERVATION,)")
mut(CHAIN, "overlap code wrong", "_refuse(RegistryRefusalCode.OVERLAPPING_REGISTRATION,", "_refuse(RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED,")
mut(CHAIN, "admission predecessor unchecked", "    if record_type is RecordType.ADMISSION:\n        _check_predecessor(", "    if False:\n        _check_predecessor(")
mut(CHAIN, "consumption predecessor unchecked", "    elif record_type is RecordType.CONSUMPTION:\n        _check_predecessor(", "    elif False:\n        _check_predecessor(")
mut(CHAIN, "predecessor missing unchecked", "    if predecessor is None:", "    if False:")
mut(CHAIN, "predecessor pin unchecked", "    if record[pin_field] != predecessor.content_hash:", "    if False:")
mut(CHAIN, "predecessor seq unchecked", "    if extra is not None and record[extra[0]] != getattr(predecessor, extra[1]):", "    if False:")
mut(CHAIN, "predecessor window unchecked", 'if predecessor.window != window or earlier["commitment_content_hash"] != record["commitment_content_hash"]:', 'if earlier["commitment_content_hash"] != record["commitment_content_hash"]:')
mut(CHAIN, "predecessor commitment unchecked", 'if predecessor.window != window or earlier["commitment_content_hash"] != record["commitment_content_hash"]:', "if predecessor.window != window:")
mut(CHAIN, "current instance ignores rebind", "        return self.entries[-1].instance_id if self.entries else self.genesis_instance_id", "        return self.genesis_instance_id")
mut(CHAIN, "consumed state wrong", "            return CampaignState.CONSUMED", "            return CampaignState.ADMITTED")
mut(CHAIN, "admitted state wrong", "            return CampaignState.ADMITTED\n        if RecordType.RESERVATION in known:", "            return CampaignState.RESERVED\n        if RecordType.RESERVATION in known:")
mut(CHAIN, "invalid record not mapped", "        except ValueError as error:\n            raise RegistryChainError(RegistryRefusalCode.INVALID_RECORD, str(error), index=index) from error", "        except KeyError as error:\n            raise RegistryChainError(RegistryRefusalCode.INVALID_RECORD, str(error), index=index) from error")
mut(CHAIN, "chain error index wrong", "raise RegistryChainError(refusal.code, refusal.message, index=index) from refusal", "raise RegistryChainError(refusal.code, refusal.message, index=0) from refusal")
mut(CHAIN, "entry hash from prev", "content_hash=compute_record_content_hash(record), prev_content_hash", "content_hash=record[\"prev_content_hash\"], prev_content_hash")

# ── STORE ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
mut(STORE, "bom accepted", '    if raw.startswith(b"\\xef\\xbb\\xbf"):', "    if False:")
mut(STORE, "duplicate keys accepted", "    if len(set(keys)) != len(keys):", "    if False:")
mut(STORE, "constants accepted", '        raise ValueError(f"constante JSON non finie {name!r} refusée.")', "        return None")
mut(STORE, "floats accepted", '    raise ValueError(f"nombre non entier {text!r}', "    return 0\n    raise ValueError(f\"nombre non entier {text!r}")
mut(STORE, "non object root accepted", '    if type(value) is not dict:\n        raise ValueError(f"{what} : un objet', '    if False:\n        raise ValueError(f"{what} : un objet')
mut(STORE, "loader normative check dropped", "        serialize_normative_json(value)\n    except NormativeJsonError as error:\n        raise ValueError(f\"{what} : {error}\") from error\n    return value", "        pass\n    except NormativeJsonError as error:\n        raise ValueError(f\"{what} : {error}\") from error\n    return value")
mut(STORE, "reparse points not links", "    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, \"st_file_attributes\", 0) & _REPARSE_POINT)", "    return stat.S_ISLNK(info.st_mode)")
mut(STORE, "symlinks not links", "    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, \"st_file_attributes\", 0) & _REPARSE_POINT)", "    return bool(getattr(info, \"st_file_attributes\", 0) & _REPARSE_POINT)")
mut(STORE, "non regular accepted", "    if _is_link(info) or not stat.S_ISREG(info.st_mode):\n        _fail(ReadFailure.NOT_REGULAR, f\"{what} n'est pas", "    if _is_link(info):\n        _fail(ReadFailure.NOT_REGULAR, f\"{what} n'est pas")
mut(STORE, "size cap unchecked", "    if len(raw) > limit:", "    if False:")
mut(STORE, "size cap off by one read", "        return handle.read(limit + 1)", "        return handle.read(limit)")
mut(STORE, "dotdot root allowed", '    if ".." in path.parts:\n        _fail(ReadFailure.ROOT_UNUSABLE', '    if False:\n        _fail(ReadFailure.ROOT_UNUSABLE')
mut(STORE, "unknown root entry ignored", '            _fail(ReadFailure.UNKNOWN_ENTRY, f"entrée inconnue à la racine du registre : {name!r}.")', "            pass")
mut(STORE, "unknown admissions entry ignored", '                _fail(ReadFailure.UNKNOWN_ENTRY, f"entrée inconnue dans admissions/ : {name!r}.")', "                continue")
mut(STORE, "exposure orphans tolerated", "    if is_publication_temp_name(name) is not TempNaming.REGISTRY:\n        return False", "    if is_publication_temp_name(name) is None:\n        return False")
mut(STORE, "orphan not regular tolerated", '    if _is_link(info) or not stat.S_ISREG(info.st_mode):\n        _fail(ReadFailure.NOT_REGULAR, f"{name} n\'est pas un fichier ordinaire.")\n    return True', "    return True")
mut(STORE, "vanished non temp ignored", "                    if is_publication_temp_name(entry.name) is TempNaming.REGISTRY:\n                        continue", "                    if True:\n                        continue")
mut(STORE, "vanished temp not ignored", "                    if is_publication_temp_name(entry.name) is TempNaming.REGISTRY:\n                        continue", "                    if False:\n                        continue")
mut(STORE, "listing attempts 1", "LISTING_ATTEMPTS = 3", "LISTING_ATTEMPTS = 1")
mut(STORE, "listing attempts 5", "LISTING_ATTEMPTS = 3", "LISTING_ATTEMPTS = 5")
mut(STORE, "gap unchecked", "        if ordered == list(range(len(ordered))):\n            return ordered", "        if True:\n            return ordered")
mut(STORE, "too many slots unchecked", "        if len(slots) > MAX_SLOTS:", "        if False:")
mut(STORE, "identity fixed point unchecked", '        if serialize_normative_json(record) != raw:\n            raise ValueError("identity.json n\'est pas', '        if False:\n            raise ValueError("identity.json n\'est pas')
mut(STORE, "identity keys unchecked", "        if set(record) != _IDENTITY_KEYS:", "        if False:")
mut(STORE, "identity version unchecked", '        if record["registry_identity_version"] != IDENTITY_VERSION:', "        if False:")
mut(STORE, "real mode accepted", "    if mode is not RegistryMode.SYNTHETIC:", "    if False:")
mut(STORE, "slot seq unchecked", '    if record.get("seq") != seq or type(record.get("seq")) is not int:', "    if False:")
mut(STORE, "slot fixed point unchecked", '        if serialize_normative_json(record) != raw:\n            raise ValueError(f"{name} n\'est pas', '        if False:\n            raise ValueError(f"{name} n\'est pas')
mut(STORE, "barrier never made", "    if barrier:\n        try:", "    if False:\n        try:")
mut(STORE, "barrier always made", "    if barrier:\n        try:", "    if True:\n        try:")
mut(STORE, "barrier oserror swallowed", "        except (OSError, LinkPublicationError) as error:\n            raise RegistryReadError(ReadFailure.BARRIER_FAILED", "        except LinkPublicationError as error:\n            raise RegistryReadError(ReadFailure.BARRIER_FAILED")
mut(STORE, "barrier flag unchecked", "    if type(barrier) is not bool:\n        raise TypeError", "    if False:\n        raise TypeError")
mut(STORE, "init overwrites", "    except FileExistsError:\n        _fail(ReadFailure.ROOT_EXISTS", "    except KeyError:\n        _fail(ReadFailure.ROOT_EXISTS")
mut(STORE, "init parent barrier skipped", "    directory_read_barrier(parent, durability=durability)        # l'entrée", "    pass        # l'entrée")
mut(STORE, "init root barrier skipped", "    directory_read_barrier(path, durability=durability)          # l'entrée", "    pass          # l'entrée")
mut(STORE, "init identity naming exposure", 'publish_json_by_link(path / IDENTITY_FILE, identity, durability=durability, naming=TempNaming.REGISTRY,', 'publish_json_by_link(path / IDENTITY_FILE, identity, durability=durability, naming=TempNaming.EXPOSURE,')
mut(STORE, "init durability unchecked", "    if type(durability) is not DurabilityProfile:\n        raise ValueError", "    if False:\n        raise ValueError")
mut(STORE, "init mode real", '"mode": RegistryMode.SYNTHETIC.value,', '"mode": RegistryMode.REAL.value,')

# ── APPEND ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
mut(APPEND, "max attempts zero allowed", "    if type(value) is not int or value < 1:", "    if type(value) is not int or value < 0:")
mut(APPEND, "max attempts bool allowed", "    if type(value) is not int or value < 1:", "    if value < 1:")
mut(APPEND, "instance in body allowed", '    if "instance_id" in body and body.get("record_type") != RecordType.REBIND.value:', "    if False:")
mut(APPEND, "engine fields claimable", "    if claimed:", "    if False:")
mut(APPEND, "body type unchecked", "    if type(body) is not dict:\n        raise ValueError(\"la fabrique", "    if False:\n        raise ValueError(\"la fabrique")
mut(APPEND, "collision counter lost", "            collisions += 1", "            pass")
mut(APPEND, "collision aborts", "            continue\n        except PublishedUnconfirmedError", "            raise\n        except PublishedUnconfirmedError")
mut(APPEND, "unconfirmed not wrapped", "        except PublishedUnconfirmedError as error:\n            raise RegistryPublishedUnconfirmedError(", "        except KeyError as error:\n            raise RegistryPublishedUnconfirmedError(")
mut(APPEND, "chain read once", "    for attempt in range(1, attempts_allowed + 1):\n        snapshot = read_registry(root, barrier=False)", "    snapshot = read_registry(root, barrier=False)\n    for attempt in range(1, attempts_allowed + 1):\n        pass")
mut(APPEND, "attempts off by one", "for attempt in range(1, attempts_allowed + 1):", "for attempt in range(1, attempts_allowed + 2):")
mut(APPEND, "attempts one fewer", "for attempt in range(1, attempts_allowed + 1):", "for attempt in range(1, attempts_allowed):")
mut(APPEND, "contention attempts wrong", "    raise RegistryContentionError(attempts_allowed)", "    raise RegistryContentionError(0)")
mut(APPEND, "durability from constant", "durability=snapshot.identity.durability_profile, naming=TempNaming.REGISTRY,\n                                               kind=", "durability=DurabilityProfile.SIMULATED_DURABLE, naming=TempNaming.REGISTRY,\n                                               kind=")
mut(APPEND, "naming exposure", "naming=TempNaming.REGISTRY,\n                                               kind=", "naming=TempNaming.EXPOSURE,\n                                               kind=")
mut(APPEND, "consumption existence unchecked", "        if snapshot.chain.campaign_entry(campaign_id, RecordType.CONSUMPTION) is not None:", "        if False:")
mut(APPEND, "admission existence unchecked", "        if admission is None:\n            raise RegistryRefusal(RegistryRefusalCode.PREDECESSOR_MISSING", "        if False:\n            raise RegistryRefusal(RegistryRefusalCode.PREDECESSOR_MISSING")
mut(APPEND, "admission not reconfirmed", "        confirm_published_slot(snapshot.slot_path(admission.seq),", "        (lambda *a, **k: None)(snapshot.slot_path(admission.seq),")
mut(APPEND, "claim hash wrong field", '"claim_content_hash": claim.claim_content_hash,', '"claim_content_hash": claim.claim_id,')
mut(APPEND, "claim id wrong field", '"claim_id": claim.claim_id,', '"claim_id": claim.claim_content_hash,')
mut(APPEND, "admission pin wrong", '"admission_content_hash": admission.content_hash,', '"admission_content_hash": admission_record["commitment_content_hash"],')
mut(APPEND, "locator not absolute", "locator = os.path.abspath(os.fspath(campaign_dir))", "locator = os.fspath(campaign_dir)")
mut(APPEND, "reconfirm hash wrong", "expected_sha256=hashlib.sha256(serialize_normative_json(admission_record)).hexdigest(),", 'expected_sha256="0" * 64,')

# ── VIEWS ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
mut(VIEWS, "consumption reusable", "    if type(record_type) is not RecordType or record_type not in _REUSABLE:", "    if type(record_type) is not RecordType:")
mut(VIEWS, "reuse type unchecked", "    if type(record_type) is not RecordType or record_type not in _REUSABLE:\n        raise ValueError", "    if False:\n        raise ValueError")
mut(VIEWS, "reuse body type unchecked", '    if type(body) is not dict or body.get("record_type") != record_type.value:', "    if False:")
mut(VIEWS, "different content reused", "    if semantic_id(existing.record) != semantic_id(candidate):", "    if False:")
mut(VIEWS, "reuse not reconfirmed", "    return ReusedRecord(entry=existing, publication=_reconfirm(snapshot, existing))", "    return ReusedRecord(entry=existing, publication=None)")
mut(VIEWS, "reuse absent returns entry", "    if existing is None:\n        return None", "    if False:\n        return None")
mut(VIEWS, "view without barrier", "    snapshot = read_registry(registry_root, barrier=True)", "    snapshot = read_registry(registry_root, barrier=False)")
mut(VIEWS, "view campaign unchecked", "    campaign_id = validate_campaign_id(campaign_id)", "    pass")
mut(VIEWS, "view absent admission returns", "    if admission is None:\n        return None\n    reservation", "    if False:\n        return None\n    reservation")
mut(VIEWS, "view not reconfirmed", "    confirmation = _reconfirm(snapshot, admission)", "    confirmation = None")
mut(VIEWS, "view head seq wrong", "chain_head_seq=chain.next_seq - 1,", "chain_head_seq=chain.next_seq,")
mut(VIEWS, "view state constant", "campaign_state=chain.campaign_state(campaign_id),", "campaign_state=CampaignState.ADMITTED,")
mut(VIEWS, "view reservation hash wrong", 'reservation_content_hash=record["reservation_content_hash"],', 'reservation_content_hash=record["static_sources_digest"],')
mut(VIEWS, "view observation wrong field", 'attestation_observation=copy.deepcopy(record["attestation_observation"]),', 'attestation_observation=copy.deepcopy(record["authorization_reference"]),')
mut(VIEWS, "view admission id from content", "admission_id=compute_admission_id(record),", "admission_id=admission.content_hash,")


# ── Révision après revues A et B : ancres modifiées (anciennes retirées) et mutants des nouvelles règles ─────────────────────
OBSOLETE = {
    "hex field dropped", "record normative check dropped", "opaque depth unbounded", "overlap unchecked", "overlap includes same campaign", "overlap ignores reservations",
    "overlap ignores admissions", "admission predecessor unchecked", "consumption predecessor unchecked", "predecessor seq unchecked", "invalid record not mapped",
    "current instance ignores rebind", "size cap off by one read", "instance in body allowed", "engine fields claimable", "body type unchecked", "view absent admission returns",
}
M[:] = [item for item in M if item[1] not in OBSOLETE]
# modèle
mut(MODEL, "hashes dropped from hex set", '"restored_head_content_hash", "attestation_hash", "authorization_hash"})', '"restored_head_content_hash"})')
mut(MODEL, "record normative check dropped", "size = len(serialize_normative_json(record))", "size = 0")
mut(MODEL, "opaque depth unbounded", "    if _exceeds_depth(value, MAX_OPAQUE_DEPTH):", "    if False:")
mut(MODEL, "opaque depth off by one", "def _exceeds_depth(value: object, limit: int) -> bool:", "def _exceeds_depth(value: object, limit: int) -> bool:\n    limit += 1")
mut(MODEL, "opaque size unbounded", "    if size > MAX_OPAQUE_BYTES:", "    if False:")
mut(MODEL, "record size unbounded", "    if size > MAX_RECORD_BYTES:", "    if False:")
mut(MODEL, "hash field not hex", '_HEX64_FIELDS = frozenset({\n    "prev_content_hash",', '_HEX64_FIELDS = frozenset({\n    "x_dummy",')
# chaîne
mut(CHAIN, "overlap unchecked", "        rival = self._overlapping_rival(campaign_id, window)", "        rival = None")
mut(CHAIN, "overlap own left not skipped", "        while left >= 0 and self.intervals[left][2] == campaign_id:", "        while False:")
mut(CHAIN, "overlap own right not skipped", "        while right < len(self.intervals) and self.intervals[right][2] == campaign_id:", "        while False:")
mut(CHAIN, "overlap left closed", "if left >= 0 and self.intervals[left][1] > start:", "if left >= 0 and self.intervals[left][1] >= start:")
mut(CHAIN, "overlap right closed", "self.intervals[right][0] < end:", "self.intervals[right][0] <= end:")
mut(CHAIN, "overlap left ignored", "        if left >= 0 and self.intervals[left][1] > start:\n            return self.intervals[left]\n", "")
mut(CHAIN, "overlap right ignored", "        if right < len(self.intervals) and self.intervals[right][0] < end:\n            return self.intervals[right]\n", "")
mut(CHAIN, "overlap windows from reservations only", "_WINDOW_OWNERS = (RecordType.RESERVATION, RecordType.ADMISSION)", "_WINDOW_OWNERS = (RecordType.ADMISSION,)")
mut(CHAIN, "overlap windows from admissions only", "_WINDOW_OWNERS = (RecordType.RESERVATION, RecordType.ADMISSION)", "_WINDOW_OWNERS = (RecordType.RESERVATION,)")
mut(CHAIN, "overlap window registered twice", "entry.campaign_id not in self.windowed:", "True:")
mut(CHAIN, "admission predecessor unchecked", "        if record_type is RecordType.ADMISSION:\n            self._check_predecessor(", "        if False:\n            self._check_predecessor(")
mut(CHAIN, "consumption predecessor unchecked", "        elif record_type is RecordType.CONSUMPTION:\n            self._check_predecessor(", "        elif False:\n            self._check_predecessor(")
mut(CHAIN, "invalid record not mapped", "        except (ValueError, RecursionError) as error:", "        except RecursionError as error:")
mut(CHAIN, "recursion not mapped", "        except (ValueError, RecursionError) as error:", "        except ValueError as error:")
mut(CHAIN, "current instance ignores rebind", "return self.entries[-1].instance_id if self.entries else self.genesis_instance_id", "return self.genesis_instance_id")
mut(CHAIN, "rebind may reuse an instance", '        if record["instance_id"] in self.instances:', "        if False:")
mut(CHAIN, "instances not tracked", "        self.instances.add(entry.instance_id)\n", "")
mut(CHAIN, "assemble engine fields claimable", "    if claimed:", "    if False:")
mut(CHAIN, "assemble instance in body allowed", '    if "instance_id" in body and body.get("record_type") != RecordType.REBIND.value:', "    if False:")
mut(CHAIN, "assemble body type unchecked", '    if type(body) is not dict:\n        raise ValueError("la fabrique', '    if False:\n        raise ValueError("la fabrique')
mut(CHAIN, "assemble seq wrong", '"registry_id": chain.registry_id, "seq": chain.next_seq,', '"registry_id": chain.registry_id, "seq": chain.next_seq + 1,')
mut(CHAIN, "clone shares entries", "        copy.entries = list(self.entries)", "        copy.entries = self.entries")
mut(CHAIN, "clone shares intervals", "        copy.intervals = list(self.intervals)", "        copy.intervals = self.intervals")
mut(CHAIN, "bisect key past equal starts", 'position = bisect.bisect_left(self.intervals, (start, ""))', 'position = bisect.bisect_left(self.intervals, (start, "~"))')
# store
mut(STORE, "size cap off by one read", "chunks, remaining = [], limit + 1", "chunks, remaining = [], limit")
mut(STORE, "open fstat unchecked", "        if not stat.S_ISREG(os.fstat(descriptor).st_mode):", "        if False:")
mut(STORE, "open follows links", 'getattr(os, "O_NOFOLLOW", 0) | ', "")
mut(STORE, "open may block", 'getattr(os, "O_NONBLOCK", 0) | ', "")
mut(STORE, "identity oserror raw", '    except OSError as error:\n        _fail(ReadFailure.ROOT_UNUSABLE, f"identity.json inobservable', '    except KeyError as error:\n        _fail(ReadFailure.ROOT_UNUSABLE, f"identity.json inobservable')
mut(STORE, "init preflight skipped", "    directory_read_barrier(parent, durability=durability)        # PRÉFLIGHT", "    pass        # PRÉFLIGHT")
# moteur d'ajout
mut(APPEND, "ack unchecked", "    if unproven_synthetic is not True:", "    if False:")
mut(APPEND, "reader proof skipped", "        _prove_reader_will_reread(record, seq)", "        pass")
mut(APPEND, "reader size cap unchecked", "    if len(payload) > store.MAX_SLOT_BYTES:", "    if False:")
mut(APPEND, "reader slot count unchecked", "    if seq + 1 > store.MAX_SLOTS:", "    if False:")
mut(APPEND, "reader slot count off by one", "    if seq + 1 > store.MAX_SLOTS:", "    if seq > store.MAX_SLOTS:")
mut(APPEND, "reader roundtrip unchecked", "    if reread != record or serialize_normative_json(reread) != payload:", "    if False:")
mut(APPEND, "precondition error not wrapped", "        except LinkPublicationError as error:\n            raise RegistryPreconditionError(", "        except KeyError as error:\n            raise RegistryPreconditionError(")
mut(APPEND, "published_anything true", "class RegistryPreconditionError(Exception):", "class RegistryPreconditionError(Exception):\n    published_anything = True\n\n\nclass _Unused(Exception):")
# vues
mut(VIEWS, "reuse after consumption allowed", 'if record_type is RecordType.ADMISSION and snapshot.chain.campaign_entry(candidate["campaign_id"], RecordType.CONSUMPTION) is not None:', "if False:")
mut(VIEWS, "reuse after consumption for reservations too", 'if record_type is RecordType.ADMISSION and snapshot.chain.campaign_entry(candidate["campaign_id"], RecordType.CONSUMPTION) is not None:',
    'if snapshot.chain.campaign_entry(candidate["campaign_id"], RecordType.CONSUMPTION) is not None:')
mut(VIEWS, "view probative", "        return False\n", "        return True\n")
mut(VIEWS, "view absent admission returns", "    if admission is None:\n        return None\n    reservation", "    if False:\n        return None\n    reservation")
mut(VIEWS, "view attestation hash wrong", "attestation_hash=record[\"attestation_hash\"],", "attestation_hash=record[\"authorization_hash\"],")
mut(VIEWS, "view authorization hash wrong", "authorization_hash=record[\"authorization_hash\"],", "authorization_hash=record[\"attestation_hash\"],")


# ── Ancres corrigées (rejeu) ─────────────────────────────────────────────────────────────────────────────────────────────
mut(CHAIN, "registry id unchecked v2", '        if record["registry_id"] != self.registry_id:', "        if False:")
mut(CHAIN, "instance unchecked v2", '        elif record["instance_id"] != self.current_instance:', "        elif False:")
mut(CHAIN, "rebind may keep instance v2", '        if record["instance_id"] == self.current_instance:', "        if False:")
mut(STORE, "constants accepted v2", '    raise ValueError(f"constante JSON non finie {name!r} refusée.")', "    return None")


def main() -> int:
    only = os.environ.get("MUT_ONLY")
    target_filter = os.environ.get("MUT_TARGET")
    mutants = M
    if only:
        wanted = set(only.split("|"))
        mutants = [item for item in mutants if item[1] in wanted]
    if target_filter:
        wanted_targets = {"gate_v_registry_" + part + ".py" for part in target_filter.split(",")}
        mutants = [item for item in mutants if item[0] in wanted_targets]
    work = Path(tempfile.mkdtemp(prefix="e3dm_", dir=tempfile.gettempdir()))
    (work / "tests").mkdir()
    tracked = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines()
    wanted_tests = set(FAST_TESTS + SLOW_TESTS + HELPERS)
    for rel in tracked + E3D_MODULES + sorted(wanted_tests):
        if rel.startswith("frontend/") or (rel.startswith("tests/") and rel not in wanted_tests and not Path(rel).name.startswith("_")
                                           and rel not in ("tests/__init__.py", "tests/conftest.py", "tests/gate_v_exposure_support.py")):
            continue
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, work / rel)
    shutil.copy(REPO / "pytest.ini", work / "pytest.ini")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

    def run(tests) -> int:
        try:
            return subprocess.run([PY, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests], cwd=work, env=env, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            return 1

    baseline = run(FAST_TESTS + SLOW_TESTS)
    if baseline != 0:
        sys.exit(f"base non verte (code {baseline}) : mutation invalide ({work})")
    print("baseline green", work, flush=True)
    originals = {name: (REPO / name).read_text(encoding="utf-8") for name in E3D_MODULES}
    results = []
    try:
        for target, name, old, new in mutants:
            original = originals[target]
            count = original.count(old)
            if count != 1:
                results.append((name, "ANCHOR-ERROR", count))
                print("ANCHOR-ERROR", name, count, flush=True)
                continue
            path = work / target
            path.write_text(original.replace(old, new, 1), encoding="utf-8", newline="\n")
            code = run(FAST_TESTS)
            if code == 0:
                code = run(SLOW_TESTS)
            status = "KILLED" if code == 1 else ("SURVIVED" if code == 0 else f"ERROR-{code}")
            results.append((name, status, ""))
            print(f"{status:10} {name}", flush=True)
            path.write_text(original, encoding="utf-8", newline="\n")
    finally:
        for name, text in originals.items():
            (work / name).write_text(text, encoding="utf-8", newline="\n")
    print("SUMMARY")
    for name, status, extra in results:
        if status != "KILLED":
            print(f"{status:12} {name} {extra}")
    print("killed", sum(1 for item in results if item[1] == "KILLED"), "of", len(results))
    shutil.rmtree(work, ignore_errors=True)
    return 0


sys.exit(main())
