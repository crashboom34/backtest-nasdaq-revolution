"""N2-b1b, tranche T1 — OPTION B : plafonds imposés à `read_registry` (ADR 0025 ; note N2-b1 section 19.2 et 19.13 groupe ST).

Fichier NEUF : aucun test existant du store n'est modifié. Le chemin par défaut (`max_slots=None, max_total_bytes=None`) est démontré INCHANGÉ par comparaison différentielle avec le module
COMPLET de HEAD `47317a9` (`gate_v_registry_store_head_47317a9.py.txt`, copie verbatim, chargée sous un autre nom : `read_registry` ET ses helpers sont ceux de HEAD).

Les plafonds bornent les octets lus dans les slots et le NOMBRE D'ENTRÉES PRODUITES par `scandir` (compteur incrémenté avant `lstat`) ; ils ne bornent NI le temps de `scandir` côté noyau,
NI la mémoire de la chaîne décodée, NI le temps de `verify_chain`.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_v_registry_fixtures as fx
import gate_v_registry_audit_support as sup
import gate_v_registry_model as model
import gate_v_registry_store as store
from atomic_json_store import serialize_normative_json
from gate_v_registry_chain import RegistryChainError, RegistryRefusalCode
from gate_v_registry_store import ReadFailure, RegistryReadError

HEAD_ORACLE = Path(__file__).with_name("gate_v_registry_store_head_47317a9.py.txt")
BIG = 10 ** 9
ADMISSIONS = "admissions"


def _load_head_oracle():
    name = "_head_registry_store_oracle"
    module = types.ModuleType(name)
    module.__file__ = str(HEAD_ORACLE)
    sys.modules[name] = module
    try:
        exec(compile(HEAD_ORACLE.read_text(encoding="utf-8"), str(HEAD_ORACLE), "exec"), module.__dict__)
    finally:
        sys.modules.pop(name, None)
    return module


HEAD = _load_head_oracle()


def failure(root, **kwargs):
    with pytest.raises(RegistryReadError) as caught:
        store.read_registry(root, barrier=False, **kwargs)
    return caught.value.failure


def limits(slots, total=BIG):
    return {"max_slots": slots, "max_total_bytes": total}


class Counter:
    """Compte les `os.lstat` des chemins sous un répertoire donné (sans rien modifier)."""

    def __init__(self, monkeypatch, under):
        self.under, self.paths = str(under), []
        real = os.lstat

        def spy(path, *args, **kwargs):
            if os.path.dirname(str(path)) == self.under:
                self.paths.append(str(path))
            return real(path, *args, **kwargs)

        monkeypatch.setattr(os, "lstat", spy)


# ── ST1 : chemin par défaut inchangé ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_default_path_calls_directory_entries_with_two_arguments(tmp_path, monkeypatch):
    root = sup.new_registry(tmp_path)
    sup.populate(root, sup.three_records())
    calls, real = [], store._directory_entries

    def spy(directory, what):                                    # exactement deux paramètres, comme les espions des tests existants
        calls.append((str(directory), what))
        return real(directory, what)

    monkeypatch.setattr(store, "_directory_entries", spy)
    snapshot = store.read_registry(root, barrier=False)
    assert snapshot.chain.next_seq == 3
    assert calls == [(str(root), "racine du registre"), (str(root / ADMISSIONS), "admissions/")]


def test_default_path_does_not_count_orphans_and_reads_constants_at_call_time(tmp_path, monkeypatch):
    root = sup.new_registry(tmp_path)
    sup.populate(root, sup.three_records()[:1])
    sup.put_orphans(root / ADMISSIONS, 5)
    sup.put_orphans(root, 5)
    monkeypatch.setattr(store, "MAX_SLOTS", 3)
    assert store.read_registry(root, barrier=False).chain.next_seq == 1          # 6 entrées dans admissions/ > 3 : seuls les slots comptent
    monkeypatch.setattr(store, "MAX_SLOT_BYTES", 10)
    assert failure(root) is ReadFailure.TOO_LARGE


def _corpus():
    """(nom, constructeur(tmp) -> racine, constantes à patcher sur les DEUX modules)."""
    def healthy(tmp):
        root = sup.new_registry(tmp)
        sup.populate(root, sup.three_records())
        return root

    def empty(tmp):
        return sup.new_registry(tmp)

    def gap(tmp):
        root = sup.new_registry(tmp)
        records = sup.three_records()
        sup.put_slot(root, 0, records[0])
        sup.put_slot(root, 2, records[2])
        return root

    def orphans(tmp):
        root = healthy(tmp)
        sup.put_orphans(root / ADMISSIONS, 4)
        sup.put_orphans(root, 3)
        return root

    def unknown_in_admissions(tmp):
        root = healthy(tmp)
        (root / ADMISSIONS / "notes.txt").write_bytes(b"x")
        return root

    def unknown_at_root(tmp):
        root = healthy(tmp)
        (root / "notes.txt").write_bytes(b"x")
        return root

    def identity_missing(tmp):
        root = healthy(tmp)
        (root / "identity.json").unlink()
        return root

    def identity_garbage(tmp):
        root = healthy(tmp)
        (root / "identity.json").write_bytes(b"not json")
        return root

    def slot_invalid(tmp):
        root = sup.new_registry(tmp)
        sup.put_slot(root, 0, None, raw=b"{")
        return root

    def name_mismatch(tmp):
        root = sup.new_registry(tmp)
        r = fx.reservation(5, sup.GENESIS)
        sup.put_slot(root, 0, r)
        return root

    def chain_broken(tmp):
        root = sup.new_registry(tmp)
        r = fx.reservation(0, sup.GENESIS)
        sup.put_slot(root, 0, r)
        sup.put_slot(root, 1, fx.reservation(1, fx.h("wrong"), fx.CAMPAIGN_B, fx.instant(11), fx.instant(20)))
        return root

    def orphan_directory(tmp):
        root = healthy(tmp)
        (root / ADMISSIONS / sup.orphan_name()).mkdir()
        return root

    def admissions_missing(tmp):
        root = sup.new_registry(tmp)
        (root / ADMISSIONS).rmdir()
        return root

    def root_missing(tmp):
        return tmp / "absent"

    return [("healthy", healthy, {}), ("empty", empty, {}), ("gap", gap, {}), ("orphans", orphans, {}), ("unknown_admissions", unknown_in_admissions, {}),
            ("unknown_root", unknown_at_root, {}), ("identity_missing", identity_missing, {}), ("identity_garbage", identity_garbage, {}),
            ("slot_invalid", slot_invalid, {}), ("name_mismatch", name_mismatch, {}), ("chain_broken", chain_broken, {}), ("orphan_directory", orphan_directory, {}),
            ("admissions_missing", admissions_missing, {}), ("root_missing", root_missing, {}),
            ("too_large", healthy, {"MAX_SLOT_BYTES": 100}), ("too_many_slots", healthy, {"MAX_SLOTS": 2})]


def _run(module, root, monkeypatch):
    lstat_log, read_log = [], []
    real_lstat, real_read = os.lstat, module._read_slot_bytes

    def spy_lstat(path, *args, **kwargs):
        lstat_log.append(str(path))
        return real_lstat(path, *args, **kwargs)

    def spy_read(path, limit):
        read_log.append((str(path), limit))
        return real_read(path, limit)

    with monkeypatch.context() as patch:
        patch.setattr(os, "lstat", spy_lstat)
        patch.setattr(module, "_read_slot_bytes", spy_read)
        try:
            snapshot = module.read_registry(root, barrier=False)
            outcome = ("ok", snapshot.chain.next_seq, snapshot.chain.head_content_hash, snapshot.identity.registry_id, snapshot.identity.instance_id)
        except Exception as error:                                       # noqa: BLE001 — comparaison d'exceptions exactes
            outcome = ("error", type(error).__name__, getattr(getattr(error, "failure", None), "value", None), getattr(error, "message", None), str(error))
    return outcome, lstat_log, read_log


@pytest.mark.parametrize("name,build,constants", _corpus(), ids=[item[0] for item in _corpus()])
def test_st1b_default_path_is_observably_identical_to_head(tmp_path, monkeypatch, name, build, constants):
    """ST1b : même corpus, même racine, lu par le module COMPLET de HEAD puis par le module courant SANS plafonds : même résultat, même exception (nom de classe, `failure.value`, message ;
    les classes sont distinctes car le module de HEAD est chargé sous un autre nom) et même journal d'appels `lstat` / `_read_slot_bytes`."""
    root = build(tmp_path)
    with monkeypatch.context() as patch:
        for constant, value in constants.items():
            patch.setattr(store, constant, value)
            patch.setattr(HEAD, constant, value)
        expected = _run(HEAD, root, monkeypatch)
        actual = _run(store, root, monkeypatch)
    assert actual == expected
    assert expected[1], "le journal lstat ne doit pas être vide (anti-vacuité)"


def test_st1b_oracle_is_a_verbatim_copy_of_head_and_distinct_from_the_current_module():
    assert HEAD.read_registry is not store.read_registry
    assert HEAD.RegistryReadError is not store.RegistryReadError
    assert HEAD.MAX_SLOTS == 100000 and HEAD.MAX_SLOT_BYTES == 262144 and HEAD.MAX_IDENTITY_BYTES == 4096 and HEAD.LISTING_ATTEMPTS == 3
    assert not hasattr(HEAD, "MAX_ORPHAN_ENTRIES")


# ── ST2 : validation, ordre et types d'exception littéraux ────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def no_disk(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("accès disque pendant la validation")

    for owner, name in ((os, "lstat"), (os, "scandir"), (os, "open"), (store, "_read_slot_bytes")):
        monkeypatch.setattr(owner, name, boom)


@pytest.mark.parametrize("kwargs,exception", [
    ({"max_slots": 3}, ValueError), ({"max_total_bytes": 3}, ValueError), ({"max_slots": None, "max_total_bytes": 5.0}, ValueError), ({"max_slots": 5.0, "max_total_bytes": None}, ValueError),
    ({"max_slots": True, "max_total_bytes": 5}, TypeError), ({"max_slots": 5, "max_total_bytes": False}, TypeError),
    ({"max_slots": 3.0, "max_total_bytes": 5}, TypeError), ({"max_slots": 3, "max_total_bytes": "5"}, TypeError),
    ({"max_slots": 0, "max_total_bytes": 5}, ValueError), ({"max_slots": 3, "max_total_bytes": 0}, ValueError), ({"max_slots": -1, "max_total_bytes": 5}, ValueError),
    ({"max_slots": 100001, "max_total_bytes": 5}, ValueError), ({"max_slots": 3, "max_total_bytes": 100000 * 262144 + 1}, ValueError),
])
def test_st2_validation_errors_come_before_any_disk_access(tmp_path, no_disk, kwargs, exception):
    target = tmp_path / "x"
    with pytest.raises(exception):
        store.read_registry(target, barrier=False, **kwargs)


@pytest.mark.parametrize("kwargs", [{"max_slots": 1, "max_total_bytes": 1}, {"max_slots": 100000, "max_total_bytes": 100000 * 262144}])
def test_st2_validation_boundaries_are_inclusive(tmp_path, kwargs):
    assert failure(tmp_path / "absent", **kwargs) is ReadFailure.ROOT_UNUSABLE            # la validation passe, puis le disque échoue


def test_st2b_constants_are_read_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MAX_SLOTS", 5)
    monkeypatch.setattr(store, "MAX_SLOT_BYTES", 7)
    assert failure(tmp_path / "absent", max_slots=5, max_total_bytes=35) is ReadFailure.ROOT_UNUSABLE
    with pytest.raises(ValueError):
        store.read_registry(tmp_path / "absent", barrier=False, max_slots=6, max_total_bytes=35)
    with pytest.raises(ValueError):
        store.read_registry(tmp_path / "absent", barrier=False, max_slots=5, max_total_bytes=36)


# ── ST3 : frontière des slots ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_st3_max_slots_slots_are_accepted_and_one_more_is_refused(tmp_path):
    root = sup.new_registry(tmp_path)
    sup.populate(root, sup.three_records())
    assert store.read_registry(root, barrier=False, **limits(3)).chain.next_seq == 3
    sup.put_slot(root, 3, None, raw=b"x")
    assert failure(root, **limits(3)) is ReadFailure.TOO_MANY_SLOTS
    assert failure(root, **limits(4)) is ReadFailure.SLOT_INVALID                # 4 slots : le plafond passe, le contenu est refusé ensuite


# ── ST4 : arrêt précoce du listage et frontières du compteur ──────────────────────────────────────────────────────────────────────────────────────

def test_st4_enumeration_stops_after_the_entry_cap(tmp_path, monkeypatch):
    root = sup.new_registry(tmp_path)
    admissions = root / ADMISSIONS
    for seq in range(50):
        (admissions / model.slot_file_name(seq)).write_bytes(b"x")
    for index in range(5000):
        (admissions / f"junk_{index}.txt").write_bytes(b"x")
    counter = Counter(monkeypatch, admissions)
    assert failure(root, **limits(3)) is ReadFailure.TOO_MANY_SLOTS
    cap = 3 + store.MAX_ORPHAN_ENTRIES
    assert len(counter.paths) <= cap < 50 + 5000
    assert len(counter.paths) >= cap - 5                                          # anti-vacuité : le plafond est effectivement atteint


def test_st4_entry_cap_beats_unknown_entry_and_unknown_entry_beats_slot_count(tmp_path):
    root = sup.new_registry(tmp_path)
    admissions = root / ADMISSIONS
    for index in range(3 + store.MAX_ORPHAN_ENTRIES + 1):
        (admissions / f"junk_{index}.txt").write_bytes(b"x")
    assert failure(root, **limits(3)) is ReadFailure.TOO_MANY_SLOTS                # plafond d'entrées, quel que soit l'ordre du listage
    other = sup.new_registry(tmp_path, "other")
    for seq in range(4):
        (other / ADMISSIONS / model.slot_file_name(seq)).write_bytes(b"x")
    (other / ADMISSIONS / "notes.txt").write_bytes(b"x")
    assert failure(other, **limits(3)) is ReadFailure.UNKNOWN_ENTRY                # entrée anormale avant le décompte des slots (précédence d'aujourd'hui)


def test_st4_counter_is_per_listing_not_cumulative_across_relistings(tmp_path):
    root = sup.new_registry(tmp_path)
    records = sup.three_records()
    sup.put_slot(root, 0, records[0])
    sup.put_slot(root, 2, records[2])                                            # trou persistant
    sup.put_orphans(root / ADMISSIONS, store.MAX_ORPHAN_ENTRIES)                 # 2 slots + 1 024 orphelins = max_slots + 1 024 = plafond exact, par listage
    assert failure(root, **limits(2)) is ReadFailure.SLOT_GAP                      # 3 listages de 1 026 entrées : jamais TOO_MANY_SLOTS


# ── ST5 : autres entrées (orphelins, inconnues) : admissions/ et racine ───────────────────────────────────────────────────────────────────────────

def test_st5_other_entries_boundary_in_admissions(tmp_path):
    root = sup.new_registry(tmp_path)
    sup.populate(root, sup.three_records())
    sup.put_orphans(root / ADMISSIONS, store.MAX_ORPHAN_ENTRIES)
    assert store.read_registry(root, barrier=False, **limits(3)).chain.next_seq == 3
    sup.put_orphans(root / ADMISSIONS, 1)
    assert failure(root, **limits(3)) is ReadFailure.TOO_MANY_SLOTS              # la 1 025ᵉ autre entrée


def test_st5_root_boundary_is_1026_entries(tmp_path):
    root = sup.new_registry(tmp_path)
    sup.populate(root, sup.three_records())
    sup.put_orphans(root, store.MAX_ORPHAN_ENTRIES)                              # identity.json + admissions + 1 024 = 1 026
    assert store.read_registry(root, barrier=False, **limits(3)).chain.next_seq == 3
    sup.put_orphans(root, 1)
    assert failure(root, **limits(3)) is ReadFailure.TOO_MANY_SLOTS              # la 1 027ᵉ


def test_st5_default_path_has_no_root_cap(tmp_path):
    root = sup.new_registry(tmp_path)
    sup.put_orphans(root, store.MAX_ORPHAN_ENTRIES + 10)
    assert store.read_registry(root, barrier=False).chain.next_seq == 0


def test_st5_unknown_entry_under_the_cap_and_orphan_directory(tmp_path):
    root = sup.new_registry(tmp_path)
    (root / ADMISSIONS / "notes.txt").write_bytes(b"x")
    assert failure(root, **limits(3)) is ReadFailure.UNKNOWN_ENTRY
    other = sup.new_registry(tmp_path, "other")
    (other / ADMISSIONS / sup.orphan_name()).mkdir()
    assert failure(other, **limits(3)) is ReadFailure.NOT_REGULAR


# ── ST6 / ST7 / ST8 : octets ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_st6_cumulative_byte_budget_boundary_and_bytes_actually_read(tmp_path, monkeypatch):
    root = sup.new_registry(tmp_path)
    records = sup.three_records()
    sup.populate(root, records)
    sizes = sup.slot_sizes(records)
    total = sum(sizes)
    returned, real = [], store._read_slot_bytes

    def spy(path, limit):
        raw = real(path, limit)
        if Path(path).name != "identity.json":                              # seuls les slots comptent dans le budget (l'identité a son propre plafond)
            returned.append((len(raw), limit))
        return raw

    monkeypatch.setattr(store, "_read_slot_bytes", spy)
    assert store.read_registry(root, barrier=False, max_slots=3, max_total_bytes=total).chain.next_seq == 3
    assert returned == [(sizes[0], min(262144, total)), (sizes[1], min(262144, total - sizes[0])), (sizes[2], total - sizes[0] - sizes[1])]
    returned.clear()
    assert failure(root, max_slots=3, max_total_bytes=total - 1) is ReadFailure.TOO_LARGE
    assert sum(read for read, _limit in returned) <= (total - 1) + 1


def test_st7_per_slot_limit_boundary(tmp_path, monkeypatch):
    root = sup.new_registry(tmp_path)
    records = sup.three_records()
    sup.populate(root, records)
    biggest = max(sup.slot_sizes(records))
    monkeypatch.setattr(store, "MAX_SLOT_BYTES", biggest)
    assert store.read_registry(root, barrier=False, max_slots=3, max_total_bytes=3 * biggest).chain.next_seq == 3
    monkeypatch.setattr(store, "MAX_SLOT_BYTES", biggest - 1)
    assert failure(root, max_slots=3, max_total_bytes=3 * (biggest - 1)) is ReadFailure.TOO_LARGE


def test_st8_identity_is_bounded_to_4097_bytes(tmp_path, monkeypatch):
    root = sup.new_registry(tmp_path)
    (root / "identity.json").write_bytes(b" " * 4097)
    returned, real = [], store._read_slot_bytes

    def spy(path, limit):
        raw = real(path, limit)
        returned.append(len(raw))
        return raw

    monkeypatch.setattr(store, "_read_slot_bytes", spy)
    assert failure(root, **limits(3)) is ReadFailure.TOO_LARGE
    assert returned == [4097]
    (root / "identity.json").write_bytes(b" " * 4096)
    assert failure(root, **limits(3)) is ReadFailure.IDENTITY_INVALID                # 4 096 octets : lisible, puis refusé pour son contenu


# ── ST9 : liens et points d'analyse (simulés par le prédicat du store, comme les tests existants) ────────────────────────────────────────────────

@pytest.mark.parametrize("target,expected", [("", ReadFailure.ROOT_UNUSABLE), (ADMISSIONS, ReadFailure.NOT_REGULAR), ("identity.json", ReadFailure.NOT_REGULAR),
                                             (f"{ADMISSIONS}/admission_000000.json", ReadFailure.NOT_REGULAR)])
def test_st9_reparse_points_are_refused_under_limits(tmp_path, monkeypatch, target, expected):
    root = sup.new_registry(tmp_path)
    sup.populate(root, sup.three_records()[:1])
    inode = os.lstat(root / target if target else root).st_ino
    assert inode, "st_ino requis pour désigner la cible"
    monkeypatch.setattr(store, "_is_link", lambda info: info.st_ino == inode)
    assert failure(root, **limits(3)) is expected


# ── ST10 / ST11 : chaîne sur disque, un cas par code de refus, indice littéral ───────────────────────────────────────────────────────────────────

def _chain_cases():
    g, h = sup.GENESIS, sup.H
    r = fx.reservation(0, g)
    a = fx.admission(1, h(r), r, h(r))
    c = fx.consumption(2, h(a), a, h(a))
    r_other = fx.reservation(1, h(r), fx.CAMPAIGN_B, fx.instant(11), fx.instant(20))
    return {
        RegistryRefusalCode.CAMPAIGN_ALREADY_REGISTERED: ([r, fx.reservation(1, h(r))], 1),
        RegistryRefusalCode.CAMPAIGN_ALREADY_CONSUMED: ([r, a, c, fx.consumption(3, h(c), a, h(a))], 3),
        RegistryRefusalCode.OVERLAPPING_REGISTRATION: ([r, fx.reservation(1, h(r), fx.CAMPAIGN_B)], 1),
        RegistryRefusalCode.CHAIN_LINK_BROKEN: ([r, fx.reservation(1, fx.h("wrong"), fx.CAMPAIGN_B, fx.instant(11), fx.instant(20))], 1),
        RegistryRefusalCode.REGISTRY_MISMATCH: ([r, {**r_other, "registry_id": "another-registry"}], 1),
        RegistryRefusalCode.INSTANCE_MISMATCH: ([r, {**r_other, "instance_id": "b" * 32}], 1),
        RegistryRefusalCode.PREDECESSOR_MISSING: ([fx.admission(0, g, r, h(r))], 0),
        RegistryRefusalCode.PREDECESSOR_MISMATCH: ([r, fx.admission(1, h(r), r, fx.h("wrong"))], 1),
        RegistryRefusalCode.REBIND_INVALID: ([fx.rebind(0, g, "c" * 32, restored_head_seq=0, restored_head_content_hash=g)], 0),
        RegistryRefusalCode.INVALID_RECORD: ([fx.reservation(0, g, "not-a-campaign")], 0),
    }


@pytest.mark.parametrize("code", list(RegistryRefusalCode), ids=[c.value for c in RegistryRefusalCode])
def test_st10_each_chain_refusal_code_with_its_literal_index(tmp_path, code):
    records, index = _chain_cases()[code]
    root = sup.new_registry(tmp_path)
    sup.populate(root, records)
    with pytest.raises(RegistryChainError) as caught:
        store.read_registry(root, barrier=False, **limits(10))
    assert (caught.value.code, caught.value.index) == (code, index)


def test_st10_covers_all_ten_codes():
    assert len(RegistryRefusalCode) == 10 and set(_chain_cases()) == set(RegistryRefusalCode)


def test_st11_identity_of_another_registry_fails_at_slot_zero(tmp_path):
    root = sup.new_registry(tmp_path)
    sup.populate(root, sup.three_records()[:1])
    identity = {"registry_identity_version": store.IDENTITY_VERSION, "registry_id": "another-registry", "instance_id": fx.INSTANCE_ID, "mode": "SYNTHETIC",
                "durability_profile": "SIMULATED_DURABLE"}
    (root / "identity.json").write_bytes(serialize_normative_json(identity))
    with pytest.raises(RegistryChainError) as caught:
        store.read_registry(root, barrier=False, **limits(3))
    assert (caught.value.code, caught.value.index) == (RegistryRefusalCode.REGISTRY_MISMATCH, 0)


def test_option_b_read_path_reaches_no_write_primitive():
    """NW5 (partie store) : la fonction de lecture et ses helpers n'appellent aucune primitive d'écriture, d'ajout ou d'initialisation."""
    import ast
    source = Path(store.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    reading = {"read_registry", "_directory_entries", "_slot_sequence", "_read_record", "_read_bounded", "_read_identity", "_read_slot_bytes", "_require_real_directory", "_tolerated_orphan",
               "_lstat_regular", "_load_strict_json"}
    forbidden = {"publish_json_by_link", "publish_bytes_by_link", "initialize_synthetic_registry", "save_exclusive", "save_atomic", "mkdir", "write_bytes", "write_text", "replace", "unlink",
                 "rename", "remove", "rmdir"}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in reading:
            called = {getattr(n.func, "attr", getattr(n.func, "id", None)) for n in ast.walk(node) if isinstance(n, ast.Call)}
            assert not called & forbidden, (node.name, called & forbidden)
