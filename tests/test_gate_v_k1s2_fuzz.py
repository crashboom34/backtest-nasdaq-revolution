"""K1 Étape 2, lot L3-A : totalité, hostilité, complexité et vecteurs INDÉPENDANTS du vérificateur (`gate_v_k1s2_verifier`) et du diagnostic des vides.

Propriétés cherchées (section 9 de la mission) : fausse cohérence, sortie omise, run usurpé, hash mal attribué, liste déclarée prise pour une observation, arbre
incomplet accepté, chemin hostile, cycle, complexité anormale, exceptions non typées. Graine FIXE (reproductible) ; fixtures EN MÉMOIRE ; aucune donnée de marché.
Les valeurs attendues des vecteurs sont des LITTÉRAUX recalculables avec `hashlib` : le code testé ne les produit pas.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import random
import time

import pytest

import gate_v_k1s2_emptiness as em
import gate_v_k1s2_verifier as vf
from tests.test_gate_v_k1s2_verifier import BASE, CID, COVERAGE, K, RUN, RUN_FILE, SEAL, SESSION1, V5_DIGEST, V5_VERSION, items_of, sha, tree_of, verify, world

SEED = 20261025
NASTY_TEXT = ["", ".", "..", "../x", "a/../b", "/abs", "a//b", "a/", "a\\b", "C:/x", "a:b", "a b ", "a.", "é/x", "x\x00y", "x\ny", "\u202e", "a" * 300, "a/" * 3000,
              "validations/../walk_forward/x", "walk_forward/./x", "WALK_FORWARD/x", "walk_forward\\x", "walk_forward/x ", "\ud800", "\U0001f600"]
GOLDEN = {"run_data_coverage.json": ("69988120c20048ec413827c7ad3145709a241d6e442c3dd5def2d8f0c92f96ff", 1477),
          "run_seal.json": ("11a6d43d9bda015523269cc473dff697f1cf0d6e4177d8db9b7e1c710150a278", 2413),
          "run_session_0001.json": ("d4c2fa14b1d8ec65812ed348e58d137d7d89210a182892ad89829ee2d1519dd8", 421),
          "validation_run.json": ("0c7a2003f2d69bbd09dc923076f486e4068beaba37e228402313870b1049d07f", 394)}


def random_value(rng: random.Random):
    return rng.choice([None, True, False, 0, 1, -1, 2 ** 70, 1.5, float("nan"), "x", "a" * 64, "A" * 64, b"", b"abc", [], (), {}, object(), vf.ObservedKind.FILE, vf.ObservedKind,
                       NASTY_TEXT[rng.randrange(len(NASTY_TEXT))], bytearray(b"x"), memoryview(b"x")])


# ══ Totalité de la frontière d'observation ═══════════════════════════════════════════════════════════════════════════════════════════
def test_hostile_item_construction_only_ever_raises_the_typed_refusal():
    rng, built, refused = random.Random(SEED), 0, 0
    for _ in range(6000):
        arguments = {name: (random_value(rng) if rng.random() < 0.7 else None) for name in ("size", "sha256", "content", "anomaly")}
        path = NASTY_TEXT[rng.randrange(len(NASTY_TEXT))] if rng.random() < 0.6 else rng.choice(["walk_forward/a.json", f"{BASE}/run_seal.json", 5, None, b"x"])
        kind = rng.choice([*vf.ObservedKind, "FILE", None, 3])
        try:
            item = vf.ObservedItem(path, kind, **arguments)
        except vf.ObservationRefused as refusal:
            assert type(refusal.code) is vf.ObservationRefusal
            refused += 1
        else:
            built += 1
            assert item.path == path and "\\" not in item.path and ".." not in item.path.split("/") and not item.path.startswith("/")
            if item.kind is vf.ObservedKind.FILE:
                assert type(item.size) is int and len(item.sha256) == 64
                assert item.content is None or hashlib.sha256(item.content).hexdigest() == item.sha256
    assert refused > 5000                                                      # l'immense majorité des entrées hostiles est refusée


def test_near_valid_items_exercise_the_acceptance_paths_and_every_accepted_item_is_internally_consistent():
    rng, built, refused = random.Random(SEED + 4), 0, 0
    paths = ["walk_forward/manifest.json", f"{BASE}/run_seal.json", "validations/x/y.json", "a"]
    for _ in range(5000):
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(40)))
        fields = {"size": len(data), "sha256": sha(data), "content": data, "anomaly": "UNREADABLE"}
        args = {name: value for name, value in fields.items() if rng.random() < 0.6}
        if args and rng.random() < 0.4:
            args[rng.choice(list(args))] = random_value(rng)
        kind = rng.choice(list(vf.ObservedKind))
        try:
            item = vf.ObservedItem(rng.choice(paths), kind, **args)
        except vf.ObservationRefused:
            refused += 1
            continue
        built += 1
        if item.kind is vf.ObservedKind.FILE:
            assert type(item.size) is int and item.size >= 0 and len(item.sha256) == 64
            assert item.content is None or (len(item.content) == item.size and hashlib.sha256(item.content).hexdigest() == item.sha256)
        else:
            assert (item.size, item.sha256, item.content) == (None, None, None)
        assert (item.anomaly is not None) <= (item.kind in (vf.ObservedKind.ANOMALY, vf.ObservedKind.UNKNOWN))
        assert (item.kind is vf.ObservedKind.ANOMALY) <= (item.anomaly is not None)
    assert built > 150 and refused > 1000


def test_hostile_tree_construction_only_ever_raises_the_typed_refusal():
    rng = random.Random(SEED + 1)
    good = tree_of(world()).items
    for _ in range(400):
        items = rng.choice([good, list(good), (good[0], good[0]), (None,), "items", good + (object(),), (*good, *good)])
        name = rng.choice([CID, "", "gate_v_v2_x", None, 5, CID.upper(), CID + "x"])
        try:
            vf.ObservedRunTree(name, rng.choice([V5_VERSION, 3, None]), rng.choice([V5_DIGEST, "x", None]), items)
        except vf.ObservationRefused as refusal:
            assert refusal.code is vf.ObservationRefusal.BAD_TREE
    with pytest.raises(vf.ObservationRefused):
        vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(vf.ObservedItem(f"d/{i}", vf.ObservedKind.DIRECTORY) for i in range(vf.MAX_ITEMS + 1)))


def test_forged_objects_that_bypass_the_constructors_never_raise_and_are_never_established():
    base = tree_of(world())
    forged_item = dataclasses.replace(base.items[0])
    object.__setattr__(forged_item, "kind", "NOT_A_KIND")
    object.__setattr__(forged_item, "path", 7)
    forged_tree = vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, base.items)
    object.__setattr__(forged_tree, "items", (*base.items[1:], forged_item))
    for subject in (forged_tree, object(), None, "tree"):
        report = vf.verify_run_chain(subject, RUN)
        assert report.established is False and report.facts is None
        assert em.diagnose_emptiness(subject).absence_consideration_blocked is True
    for run_id in (None, 3, b"x", [], "", "x", RUN + "x", RUN.upper()):
        assert vf.verify_run_chain(base, run_id).established is False


def test_an_internal_failure_is_reported_as_bad_input_never_as_an_established_chain(monkeypatch):
    files = world()
    monkeypatch.setattr(vf.ev.RunSeal, "from_bytes", classmethod(lambda cls, data: (_ for _ in ()).throw(RuntimeError("boom"))))
    report = verify(files)
    assert report.established is False and {d.code for d in report.defects} == {K.BAD_INPUT}


# ══ Fausse cohérence : toute altération d'un octet, d'un hash, d'une entrée est détectée ═══════════════════════════════════════
def altered(files: dict, path: str, data: bytes) -> vf.ObservedRunTree:
    items = [item for item in items_of(files) if item.path != path]
    items.append(vf.ObservedItem(path, vf.ObservedKind.FILE, size=len(data), sha256=sha(data), content=data if path.startswith("validations/") else None))
    return vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(sorted(items, key=lambda item: item.path)))


@pytest.mark.parametrize("sessions,recovery", [(1, False), (3, True)])
def test_no_single_byte_alteration_of_any_proof_file_keeps_the_chain_established(sessions, recovery):
    files = world(sessions=sessions, recovery=recovery)
    assert verify(files).established
    mutations = 0
    for path in sorted(files):
        if not path.startswith("validations/"):
            continue
        data = files[path]
        for index in range(len(data)):
            for xor in (0x01, 0x20):
                changed = bytes(data[:index]) + bytes([data[index] ^ xor]) + bytes(data[index + 1:])
                report = vf.verify_run_chain(altered(files, path, changed), RUN)
                assert report.established is False, (path, index, xor)
                mutations += 1
    assert mutations > 8000


def test_no_alteration_of_an_output_hash_size_or_presence_keeps_the_chain_established():
    files = world()
    for path in sorted(p for p in files if p.startswith("walk_forward/")):
        data = files[path]
        for changed in (data + b"x", data[:-1], b"", bytes(reversed(data)) if len(set(data)) > 1 else data + b"y"):
            assert vf.verify_run_chain(altered(files, path, changed), RUN).established is False
        without = vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(i for i in tree_of(files).items if i.path != path))
        assert K.OUTPUT_MISSING in {d.code for d in vf.verify_run_chain(without, RUN).defects}


def test_removing_any_file_or_adding_any_in_scope_entry_is_never_established():
    files = world()
    base = tree_of(files)
    for item in base.items:
        if item.kind is vf.ObservedKind.FILE:
            reduced = vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(i for i in base.items if i.path != item.path))
            assert vf.verify_run_chain(reduced, RUN).established is False, item.path
    rng = random.Random(SEED + 2)
    scopes = ["walk_forward", "walk_forward/folds", "walk_forward/folds/fold_000", "walk_forward/.gate_v_checkpoints_v1", BASE]
    existing = {item.path for item in base.items}
    for _ in range(300):
        path = f"{rng.choice(scopes)}/{rng.choice(['extra.json', 'run_session_0002.json', 'x.tmp', 'state.json.tmp', 'notes.txt'])}"
        if path in existing:
            continue
        kind = rng.choice([vf.ObservedKind.INERT, vf.ObservedKind.ORPHAN, vf.ObservedKind.DIRECTORY, vf.ObservedKind.UNKNOWN, vf.ObservedKind.ANOMALY, vf.ObservedKind.FILE])
        extra = {vf.ObservedKind.ANOMALY: dict(anomaly="UNREADABLE"), vf.ObservedKind.FILE: dict(size=3, sha256="c" * 64)}.get(kind, {})
        report = vf.verify_run_chain(vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, (*base.items, vf.ObservedItem(path, kind, **extra))), RUN)
        if kind is vf.ObservedKind.DIRECTORY and path.startswith(BASE):
            continue                                                               # un sous-répertoire du dossier du run : couvert par la matrice (UNKNOWN_RUN_FILE)
        assert report.established is False, (kind, path)


def test_random_structurally_valid_trees_never_raise_and_are_deterministic_and_never_report_bad_input():
    rng = random.Random(SEED + 3)
    pool = list(items_of(world(sessions=2)))
    seen = set()
    for _ in range(400):
        chosen = [item for item in pool if rng.random() < 0.85]
        for _ in range(rng.randrange(3)):
            path = rng.choice(["walk_forward/a.json", f"{BASE}/x.json", "validations/other/y", f"{BASE}/run_session_0009.json", "stray"])
            kind = rng.choice([vf.ObservedKind.INERT, vf.ObservedKind.ORPHAN, vf.ObservedKind.UNKNOWN])
            if path not in {i.path for i in chosen}:
                chosen.append(vf.ObservedItem(path, kind))
        tree = vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(chosen))
        report = vf.verify_run_chain(tree, RUN)
        assert vf.verify_run_chain(vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(reversed(chosen))), RUN) == report
        assert K.BAD_INPUT not in {d.code for d in report.defects}
        assert report.established == (report.facts is not None) == (not report.defects)
        seen.add(report.established)
        assert em.diagnose_emptiness(tree).category is not em.EmptinessCategory.BAD_INPUT
    assert seen == {True, False}                                                  # les deux issues sont exercées


# ══ Complexité anormale ═════════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_a_hundred_thousand_entries_are_verified_in_bounded_time():
    files = world()
    base = list(tree_of(files).items)
    flood = [vf.ObservedItem(f"walk_forward/folds/fold_{i // 1000:03d}/junk_{i:06d}.json", vf.ObservedKind.INERT) for i in range(vf.MAX_ITEMS - len(base) - 1000)]
    tree = vf.ObservedRunTree(CID, V5_VERSION, V5_DIGEST, tuple(base + flood))
    started = time.perf_counter()
    report = vf.verify_run_chain(tree, RUN)
    assert time.perf_counter() - started < 20.0 and report.established is False and len(report.defects) == len(flood)
    started = time.perf_counter()
    em.diagnose_emptiness(tree)
    assert time.perf_counter() - started < 20.0


def test_deep_and_long_paths_and_huge_defect_lists_do_not_blow_up():
    with pytest.raises(vf.ObservationRefused) as caught:
        vf.ObservedItem("walk_forward/" + "/".join(["d"] * 500) + "/f.json", vf.ObservedKind.UNKNOWN)
    assert caught.value.code is vf.ObservationRefusal.BAD_PATH                   # profondeur bornée à 32 segments (complexité des ancêtres)
    deep = "walk_forward/" + "/".join(["d"] * 30) + "/f.json"
    report = verify(world(), [vf.ObservedItem(deep, vf.ObservedKind.UNKNOWN)])
    assert report.established is False and len(report.defects) == 1
    assert all(len(defect.detail) <= 400 for defect in report.defects)


# ══ Vecteurs INDÉPENDANTS (littéraux recalculables avec hashlib) ══════════════════════════════════════════════════════════════════
def test_the_golden_chain_has_the_frozen_digests_and_the_verifier_reports_exactly_them():
    files = world()
    for name, (digest, size) in GOLDEN.items():
        path = f"{BASE}/{name}"
        assert (hashlib.sha256(files[path]).hexdigest(), len(files[path])) == (digest, size)          # oracle hashlib ; dérive de sérialisation L2 ⇒ rouge ici
    facts = verify(files).facts
    assert (facts.coverage_sha256, facts.session_sha256s, facts.run_record_sha256, facts.seal_sha256) == (
        GOLDEN["run_data_coverage.json"][0], (GOLDEN["run_session_0001.json"][0],), GOLDEN["validation_run.json"][0], GOLDEN["run_seal.json"][0])
    outputs = sorted((p, hashlib.sha256(d).hexdigest(), len(d)) for p, d in files.items() if p.startswith("walk_forward/"))
    assert (facts.output_count, facts.output_bytes) == (10, 525) == (len(outputs), sum(size for _, _, size in outputs))
    assert hashlib.sha256(json.dumps([[p, [h, s]] for p, h, s in outputs]).encode()).hexdigest() == "b9ae2b19386cd50fdb39f345317c384db5f57d2d28ea9a11328f5093bb218e22"


def test_the_golden_chain_with_bytes_swapped_between_roles_is_refused():
    files = world()
    swapped = dict(files)
    swapped[COVERAGE], swapped[SEAL] = files[SEAL], files[COVERAGE]               # mêmes octets, mauvais rôles : hash correct, mauvais chemin
    assert verify(swapped).established is False
    swapped = dict(files)
    swapped[SESSION1], swapped[RUN_FILE] = files[RUN_FILE], files[SESSION1]
    assert verify(swapped).established is False
