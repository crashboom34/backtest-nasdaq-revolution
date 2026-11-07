"""P5-bis, fermeture du MEDIUM : frontières de parsing JSON de B2 (`parse_strict_json`) et de L2 (`parse_normative_json`, `normative_json_bytes`).

Problème : ces trois fonctions convertissaient TOUTE `RecursionError` en refus typé de DONNÉES (`DEPTH_EXCEEDED`, `JSON_INVALID`, `BAD_VALUE`). Or une `RecursionError` ne dit pas, à elle seule,
si la pile a été épuisée par le DOCUMENT ou par l'ENVIRONNEMENT (appelant déjà profond). Un document peu imbriqué mal étiqueté « imbrication excessive » masquait une défaillance critique, et
le protocole rendait un rapport recevable au lieu de `AUDIT_INTERNAL_FAILURE`.

Règle : le discriminateur est une MESURE DU DOCUMENT, jamais le type de l'exception. Un parcours itératif (sans récursion) mesure l'imbrication ; si elle ne dépasse pas le plancher `64` (le
plafond de profondeur de L3-A), aucune donnée ne peut expliquer l'épuisement : la `RecursionError` d'origine se propage. Au-delà du plancher, le refus typé historique est conservé (document
réellement trop profond, ou cas ambigu : le refus de données reste la voie conservatrice, jamais un statut positif).

Fixtures SYNTHÉTIQUES. Épuisement RÉEL de la pile par un appelant profond (`at_depth`), jamais une simulation seule. Aucun A0, aucune admission, aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

import gate_v_audit_protocol as ap
import gate_v_exposure_scan as scan
import gate_v_k1s2_verifier as vf
import gate_v_run_evidence_models as ev
from tests.gate_v_audit_protocol_support import request_of, scenario_dir
from tests.test_gate_v_audit_protocol_scenarios import coherent_campaign
from tests.test_gate_v_k1s2_verifier import RUN, tree_of, world

R = ap.RefusalCode
SHALLOW = b'{"a": [1, 2, {"b": null}]}'                       # profondeur 3
FLOOR = 64
DEEP = 5000


def nested(depth: int) -> bytes:
    return b"[" * depth + b"]" * depth


def nested_object_text(depth: int) -> bytes:
    """Objet normatif racine contenant `depth - 1` niveaux de listes (imbrication totale `depth`)."""
    return b'{"a": ' + nested(depth - 1) + b"}\n"


class RaisingJson:
    """Remplace le module `json` d'un module testé : `loads` / `dumps` lèvent `error`, tout le reste délègue au vrai module."""

    def __init__(self, error, *, loads=True, dumps=False):
        self._error, self._loads, self._dumps = error, loads, dumps

    def __getattr__(self, name):
        if (name == "loads" and self._loads) or (name == "dumps" and self._dumps):
            def boom(*args, **kwargs):
                raise self._error
            return boom
        return getattr(json, name)


def frame_depth() -> int:
    count, frame = 0, sys._getframe()
    while frame is not None:
        count += 1
        frame = frame.f_back
    return count


def at_depth(spare: int, call):
    """Appelle `call()` avec `spare` cadres Python de marge avant la limite de récursion : épuisement RÉEL de la pile par l'appelant, sans donnée hostile."""
    def descend(remaining):
        return call() if remaining <= 0 else descend(remaining - 1)
    return descend(sys.getrecursionlimit() - frame_depth() - spare - 2)


def outcomes(call, spares=range(0, 48)):
    """Pour chaque marge : ('ok', valeur) | ('recursion', exception) | ('other', exception). Une `RecursionError` levée par `descend` seul est aussi 'recursion'."""
    seen = []
    for spare in spares:
        try:
            seen.append(("ok", at_depth(spare, call)))
        except RecursionError as error:
            seen.append(("recursion", error))
        except Exception as error:                                           # noqa: BLE001 — on classe, on n'interprète pas
            seen.append(("other", error))
    return seen


# ── B2 : `parse_strict_json` ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def strict(raw, *, max_depth=FLOOR):
    return scan.parse_strict_json(raw, max_bytes=1_000_000, max_depth=max_depth)


def anomaly_of(raw, **kwargs):
    with pytest.raises(scan.StrictJsonError) as raised:
        strict(raw, **kwargs)
    return raised.value.anomaly


def test_b1_a_document_beyond_the_explicit_limit_keeps_its_typed_refusal():
    assert anomaly_of(nested(FLOOR + 1)) is scan.SourceAnomaly.DEPTH_EXCEEDED
    assert anomaly_of(nested(5), max_depth=4) is scan.SourceAnomaly.DEPTH_EXCEEDED


def test_b2_a_really_too_deep_document_under_a_huge_limit_keeps_its_typed_refusal():
    """Aucune limite explicite ne l'arrête : c'est l'interpréteur qui échoue sur le DOCUMENT. Refus de données, comme avant."""
    assert anomaly_of(nested(DEEP), max_depth=10 ** 6) is scan.SourceAnomaly.DEPTH_EXCEEDED


@pytest.mark.parametrize("depth", [0, 1, 3, 32, FLOOR])
def test_b3_a_recursion_error_on_a_document_within_the_floor_is_never_blamed_on_the_data(monkeypatch, depth):
    error = RecursionError("simulated")
    raw = (b"[" * depth + b"1" + b"]" * depth) if depth else b"1"
    monkeypatch.setattr(scan, "json", RaisingJson(error))
    with pytest.raises(RecursionError) as raised:
        strict(raw)
    assert raised.value is error                                              # l'exception d'origine elle-même, jamais un refus typé de données


SHALLOW_BUT_TRICKY = [
    ("wide", b"[" + b",".join([b"[1]"] * 500) + b"]"),                                              # 500 listes sœurs : la profondeur reste 2 (le `]` décrémente)
    ("brackets in a string", b'{"a": "' + b"[" * 500 + b'"}'),                                      # 500 `[` dans une chaîne : jamais de l'imbrication
    ("escaped quote in a string", b'{"a": "\\"' + b"[" * 500 + b'\\""}'),                           # un guillemet échappé ne ferme pas la chaîne
    ("escaped backslash then quote", b'{"a": "\\\\", "b": [1]}'),                                   # `\\` puis `"` : la chaîne se ferme bien
]


@pytest.mark.parametrize("raw", [item[1] for item in SHALLOW_BUT_TRICKY], ids=[item[0] for item in SHALLOW_BUT_TRICKY])
def test_b3b_the_depth_measure_counts_nesting_only_not_width_or_string_content(monkeypatch, raw):
    error = RecursionError("simulated")
    monkeypatch.setattr(scan, "json", RaisingJson(error))
    with pytest.raises(RecursionError) as raised:
        strict(raw)
    assert raised.value is error


DEEP_AFTER_TRICKY = [
    ("deep after an escaped backslash", b'{"a": "\\\\", "b": ' + nested(100) + b"}"),                # `\\` puis `"` ferme la chaîne : l'imbrication qui suit DOIT être comptée
    ("deep after brackets in a string", b'{"a": "[[[", "b": ' + nested(100) + b"}"),
    ("deep after an escaped quote", b'{"a": "\\"x", "b": ' + nested(100) + b"}"),
]


@pytest.mark.parametrize("raw", [item[1] for item in DEEP_AFTER_TRICKY], ids=[item[0] for item in DEEP_AFTER_TRICKY])
def test_b3c_a_deep_document_after_string_tricks_keeps_the_conservative_typed_refusal(monkeypatch, raw):
    monkeypatch.setattr(scan, "json", RaisingJson(RecursionError("simulated")))
    assert anomaly_of(raw, max_depth=10 ** 6) is scan.SourceAnomaly.DEPTH_EXCEEDED


@pytest.mark.parametrize("depth", [FLOOR + 1, 100, 400])
def test_b4_a_recursion_error_above_the_floor_keeps_the_conservative_typed_refusal(monkeypatch, depth):
    """Cas ambigu (document plus profond que le plancher) : le refus de DONNÉES historique est conservé ; jamais un statut positif."""
    monkeypatch.setattr(scan, "json", RaisingJson(RecursionError("simulated")))
    assert anomaly_of(nested(depth), max_depth=10 ** 6) is scan.SourceAnomaly.DEPTH_EXCEEDED


def test_b5_a_really_exhausted_stack_on_a_shallow_document_is_never_a_depth_anomaly():
    seen = outcomes(lambda: strict(SHALLOW))
    kinds = {kind for kind, _ in seen}
    assert "recursion" in kinds, "le test n'atteint jamais l'épuisement de la pile : il serait vide"
    assert not [error for kind, error in seen if kind == "other"], [error for kind, error in seen if kind == "other"]          # ni StrictJsonError, ni autre refus typé
    assert all(value == {"a": [1, 2, {"b": None}]} for kind, value in seen if kind == "ok")


def test_b6_a_memory_error_while_parsing_propagates(monkeypatch):
    error = MemoryError("simulated")
    monkeypatch.setattr(scan, "json", RaisingJson(error))
    with pytest.raises(MemoryError) as raised:
        strict(SHALLOW)
    assert raised.value is error


@pytest.mark.parametrize("raw,anomaly", [
    (b"", scan.SourceAnomaly.INVALID_JSON), (b"[1,", scan.SourceAnomaly.INVALID_JSON), (b'{"a":1,"a":2}', scan.SourceAnomaly.DUPLICATE_KEY), (b"[NaN]", scan.SourceAnomaly.NON_FINITE),
    (b"\xef\xbb\xbf{}", scan.SourceAnomaly.BOM), (b"\xff", scan.SourceAnomaly.NOT_UTF8), (b'["\\ud800"]', scan.SourceAnomaly.LONE_SURROGATE), (b"9" * 5000, scan.SourceAnomaly.INVALID_JSON),
])
def test_b7_the_historical_refusals_of_invalid_documents_are_unchanged(raw, anomaly):
    assert anomaly_of(raw) is anomaly


# ── L2 : `parse_normative_json` et `normative_json_bytes` ─────────────────────────────────────────────────────────────────────────────────────

def refusal_of(call):
    with pytest.raises(ev.EvidenceRefused) as raised:
        call()
    return raised.value.code


def test_l1_a_really_too_deep_normative_document_keeps_its_typed_refusal():
    assert refusal_of(lambda: ev.parse_normative_json(nested_object_text(DEEP))) is ev.EvidenceRefusal.JSON_INVALID


@pytest.mark.parametrize("depth", [1, 2, 8, 32, FLOOR])
def test_l2_a_recursion_error_on_a_document_within_the_floor_is_never_blamed_on_the_data(monkeypatch, depth):
    error = RecursionError("simulated")
    raw = nested_object_text(depth) if depth > 1 else b'{"a": 1}\n'
    monkeypatch.setattr(ev, "json", RaisingJson(error))
    with pytest.raises(RecursionError) as raised:
        ev.parse_normative_json(raw)
    assert raised.value is error


@pytest.mark.parametrize("raw", [item[1] for item in SHALLOW_BUT_TRICKY], ids=[item[0] for item in SHALLOW_BUT_TRICKY])
def test_l2b_the_depth_measure_counts_nesting_only_not_width_or_string_content(monkeypatch, raw):
    error = RecursionError("simulated")
    monkeypatch.setattr(ev, "json", RaisingJson(error))
    with pytest.raises(RecursionError) as raised:
        ev.parse_normative_json(raw)
    assert raised.value is error


def test_l2c_the_record_measure_counts_nesting_only_not_width_or_sharing(monkeypatch):
    error = RecursionError("simulated")
    shared = [1]
    wide = {"a": [[i] for i in range(500)], "b": [shared] * 500, "c": {str(i): shared for i in range(200)}}                  # large, objets PARTAGÉS, imbrication 3
    diamond: object = 1
    for _ in range(14):
        diamond = [diamond, diamond]                                                                                          # DAG partagé : imbrication 15, 2^14 chemins
    monkeypatch.setattr(ev, "json", RaisingJson(error, loads=False, dumps=True))
    for record in (wide, {"a": diamond}):
        with pytest.raises(RecursionError) as raised:
            ev.normative_json_bytes(record)
        assert raised.value is error


@pytest.mark.parametrize("raw", [item[1] + b"\n" for item in DEEP_AFTER_TRICKY], ids=[item[0] for item in DEEP_AFTER_TRICKY])
def test_l2c_a_deep_document_after_string_tricks_keeps_the_conservative_typed_refusal(monkeypatch, raw):
    monkeypatch.setattr(ev, "json", RaisingJson(RecursionError("simulated")))
    assert refusal_of(lambda: ev.parse_normative_json(raw)) is ev.EvidenceRefusal.JSON_INVALID


def test_l2d_the_record_measure_handles_cyclic_dicts_and_refuses_foreign_container_types_before_any_recursion():
    cyclic: dict = {}
    cyclic["a"] = cyclic
    assert refusal_of(lambda: ev.normative_json_bytes(cyclic)) is ev.EvidenceRefusal.BAD_VALUE          # cycle de dict : mesure > plancher, refus de données

    class Mapping(dict):
        pass

    for foreign in ({"a": (1, [[[]]])}, {"a": Mapping(b=1)}, {"a": {1, 2}}):
        assert refusal_of(lambda: ev.normative_json_bytes(foreign)) is ev.EvidenceRefusal.BAD_TYPE       # refusé par `_check_value` avant toute récursion : la mesure n'a pas à les parcourir


@pytest.mark.parametrize("depth", [FLOOR + 1, 100, 400])
def test_l3_a_recursion_error_above_the_floor_keeps_the_conservative_typed_refusal(monkeypatch, depth):
    monkeypatch.setattr(ev, "json", RaisingJson(RecursionError("simulated")))
    assert refusal_of(lambda: ev.parse_normative_json(nested_object_text(depth))) is ev.EvidenceRefusal.JSON_INVALID


def test_l4_a_really_exhausted_stack_on_a_shallow_normative_document_is_never_a_data_refusal():
    raw = ev.normative_json_bytes({"a": [1, {"b": "x"}]})
    seen = outcomes(lambda: ev.parse_normative_json(raw))
    assert "recursion" in {kind for kind, _ in seen}, "le test n'atteint jamais l'épuisement de la pile : il serait vide"
    assert not [error for kind, error in seen if kind == "other"], [error for kind, error in seen if kind == "other"]
    assert all(value == {"a": [1, {"b": "x"}]} for kind, value in seen if kind == "ok")


def deep_record(depth: int) -> dict:
    """Objet racine dont l'imbrication TOTALE de conteneurs vaut exactement `depth` (le dict racine compte pour 1)."""
    inner: object = 1
    for _ in range(depth - 1):
        inner = [inner]
    return {"a": inner}


def cyclic_record() -> dict:
    loop: list = []
    loop.append(loop)
    return {"a": loop}


def test_l5_a_really_too_deep_or_cyclic_record_keeps_its_typed_refusal_on_serialisation():
    assert refusal_of(lambda: ev.normative_json_bytes(deep_record(DEEP))) is ev.EvidenceRefusal.BAD_VALUE
    assert refusal_of(lambda: ev.normative_json_bytes(cyclic_record())) is ev.EvidenceRefusal.BAD_VALUE


@pytest.mark.parametrize("levels", [1, 2, 8, FLOOR])
def test_l6_a_recursion_error_while_serialising_a_shallow_record_is_never_blamed_on_the_data(monkeypatch, levels):
    error = RecursionError("simulated")
    monkeypatch.setattr(ev, "json", RaisingJson(error, loads=False, dumps=True))
    with pytest.raises(RecursionError) as raised:
        ev.normative_json_bytes(deep_record(levels))
    assert raised.value is error


@pytest.mark.parametrize("levels", [FLOOR + 1, 100, 400])
def test_l7_a_recursion_error_while_serialising_above_the_floor_keeps_the_conservative_typed_refusal(monkeypatch, levels):
    monkeypatch.setattr(ev, "json", RaisingJson(RecursionError("simulated"), loads=False, dumps=True))
    assert refusal_of(lambda: ev.normative_json_bytes(deep_record(levels))) is ev.EvidenceRefusal.BAD_VALUE


def test_l8_a_really_exhausted_stack_while_serialising_is_never_a_data_refusal():
    record = {"a": [1, {"b": "x"}]}
    seen = outcomes(lambda: ev.normative_json_bytes(record))
    assert "recursion" in {kind for kind, _ in seen}, "le test n'atteint jamais l'épuisement de la pile : il serait vide"
    assert not [error for kind, error in seen if kind == "other"], [error for kind, error in seen if kind == "other"]


def test_l9_a_memory_error_while_parsing_or_serialising_propagates(monkeypatch):
    error = MemoryError("simulated")
    monkeypatch.setattr(ev, "json", RaisingJson(error, loads=True, dumps=True))
    for call in (lambda: ev.parse_normative_json(b'{"a": 1}\n'), lambda: ev.normative_json_bytes({"a": 1})):
        with pytest.raises(MemoryError) as raised:
            call()
        assert raised.value is error


@pytest.mark.parametrize("raw,code", [
    (b'{"a": 1.5}\n', ev.EvidenceRefusal.FLOAT_FORBIDDEN), (b'{"a": ' + b"9" * 5000 + b"}\n", ev.EvidenceRefusal.JSON_INVALID), (b"[1]\n", ev.EvidenceRefusal.NOT_OBJECT),
    (b'{"a": 1, "a": 2}\n', ev.EvidenceRefusal.DUPLICATE_KEY), (b'{"a":1}', ev.EvidenceRefusal.NON_CANONICAL), (b"\xef\xbb\xbf{}\n", ev.EvidenceRefusal.BOM),
])
def test_l10_the_historical_refusals_of_invalid_normative_documents_are_unchanged(raw, code):
    assert refusal_of(lambda: ev.parse_normative_json(raw)) is code


# ── L3-A : la chaîne vue de `verify_run_chain` ────────────────────────────────────────────────────────────────────────────────────────────────

def test_c1_a_really_exhausted_stack_never_turns_a_coherent_chain_into_a_typed_defect():
    tree = tree_of(world())
    assert vf.verify_run_chain(tree, RUN).established is True
    seen = outcomes(lambda: vf.verify_run_chain(tree, RUN))
    assert "recursion" in {kind for kind, _ in seen}, "le test n'atteint jamais l'épuisement de la pile : il serait vide"
    assert all(report.established is True for kind, report in seen if kind == "ok"), [(spare, report.defects) for spare, (kind, report) in enumerate(seen) if kind == "ok" and not report.established]
    assert not [error for kind, error in seen if kind == "other"]


# ── Protocole : résultat observable ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def internal_failure(report, error):
    assert report.receivability is ap.Receivability.REFUSED, report
    assert [(d.code, d.stage, d.detail) for d in report.refusals] == [(R.AUDIT_INTERNAL_FAILURE, ap.Stage.PROTOCOL, type(error).__name__)]
    assert report.roots == () and report.blocks == () and report.grants == () and report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE


def test_p1_through_the_protocol_a_stack_exhaustion_in_the_b2_json_read_is_a_typed_internal_refusal(tmp_path, monkeypatch):
    directory = scenario_dir(tmp_path, "01-ready-initial")
    assert ap.audit_campaign_exposure(request_of(directory)).receivability is ap.Receivability.RECEIVABLE
    error = RecursionError("simulated")
    monkeypatch.setattr(scan, "json", RaisingJson(error))
    internal_failure(ap.audit_campaign_exposure(request_of(directory)), error)


def test_p2_through_the_protocol_a_stack_exhaustion_in_the_l2_evidence_read_is_a_typed_internal_refusal(tmp_path, monkeypatch):
    directory, _cid = coherent_campaign(tmp_path)
    assert ap.audit_campaign_exposure(request_of(directory)).receivability is ap.Receivability.RECEIVABLE
    error = RecursionError("simulated")
    monkeypatch.setattr(ev, "json", RaisingJson(error))
    internal_failure(ap.audit_campaign_exposure(request_of(directory)), error)


def test_p3_through_the_protocol_a_memory_error_in_the_json_boundaries_is_a_typed_internal_refusal(tmp_path, monkeypatch):
    directory, _cid = coherent_campaign(tmp_path)
    error = MemoryError("simulated")
    monkeypatch.setattr(scan, "json", RaisingJson(error))
    internal_failure(ap.audit_campaign_exposure(request_of(directory)), error)


# ── Versions et empreintes : inchangées ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_v1_this_change_touches_no_semantic_version_and_no_digest():
    assert (ev.COVERAGE_SEMANTICS_VERSION, ev.SESSION_SEMANTICS_VERSION, ev.SEAL_SEMANTICS_VERSION) == ("gate_v_run_data_coverage_v1", "gate_v_run_session_v1", "gate_v_run_seal_v1")
    assert scan.HASHED_FILE_SEMANTICS_VERSION == "gate_v_scan_hashed_file_v1"
    assert vf.TABLE_VERSION == "gate_v_exposure_interpreters_v5"
    assert vf.TABLE_DIGEST == "aa389aca9e29052ce9812c766f99abaf95a2bb656a3e82fcff17ab041d4a10af"
    assert ap.AUDIT_PROTOCOL_VERSION == "gate_v_audit_protocol_v2"                      # P5-bis : une seule montée de version, partagée par A1 et cette fermeture (non publiée)


# ── Garde de structure ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_s1_the_floor_is_the_documented_l3a_depth_cap():
    assert scan._ENVIRONMENT_DEPTH_FLOOR == ev._ENVIRONMENT_DEPTH_FLOOR == FLOOR == vf._RUN_JSON_MAX_DEPTH
