"""P5-bis (option A1) — défaillances de RESSOURCES dans les fonctions totales de L3-A : `gate_v_k1s2_emptiness.diagnose_emptiness` et `gate_v_k1s2_verifier.verify_run_chain`.

Règle (décision utilisateur, A1) : `MemoryError` et `RecursionError` ne sont JAMAIS converties en `BAD_INPUT` : elles se propagent hors de la fonction, jusqu'au point d'entrée
`audit_campaign_exposure`, qui rend un refus typé `AUDIT_INTERNAL_FAILURE` (jamais de rapport recevable). Toute autre exception — erreurs de données ordinaires ET autres
`RuntimeError` — garde le traitement historique : `BAD_INPUT`, jamais « établi », jamais d'exception. `RecursionError` hérite de `RuntimeError` : la clause de propagation doit
donc précéder `except Exception`.

Versionnement : un changement observable de la sémantique publique d'audit (ici : un épuisement de ressources passe de « rapport recevable bloquant » à « refus typé ») exige une
nouvelle version de protocole : `AUDIT_PROTOCOL_VERSION == "gate_v_audit_protocol_v2"`. Règle prospective ; les rapports ne sont pas persistables (`__reduce__` lève), donc aucun
artefact antérieur n'est réinterprété.

Fixtures SYNTHÉTIQUES (`tmp_path`, arbres en mémoire). Aucun A0, aucune admission, aucune écriture de registre, aucune donnée de marché, aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import ast
import inspect

import pytest

import gate_v_audit_protocol as ap
import gate_v_k1s2_emptiness as em
import gate_v_k1s2_verifier as vf
from tests.gate_v_audit_protocol_support import request_of, scenario_dir
from tests.test_gate_v_audit_protocol_scenarios import coherent_campaign
from tests.test_gate_v_k1s2_verifier import K, RUN, tree_of, world

R = ap.RefusalCode
C = ap.BlockCode


class _DeepRecursion(RecursionError):
    pass


class _Exhausted(MemoryError):
    pass


CRITICAL = [MemoryError("simulated"), RecursionError("simulated"), _Exhausted("simulated"), _DeepRecursion("simulated")]
ORDINARY = [RuntimeError("simulated"), NotImplementedError("simulated"), ValueError("simulated"), TypeError("simulated"), AttributeError("simulated"),
            KeyError("simulated"), IndexError("simulated"), OSError("simulated"), ZeroDivisionError("simulated"), AssertionError("simulated")]


def ids(errors):
    return [type(error).__name__ for error in errors]


def raiser(error):
    def boom(*args, **kwargs):
        raise error
    return boom


def seam_from_bytes(monkeypatch, error):
    monkeypatch.setattr(vf.ev.RunSeal, "from_bytes", classmethod(lambda cls, data: (_ for _ in ()).throw(error)))


def seam_chain(monkeypatch, error):
    monkeypatch.setattr(vf, "_verify_run_chain", raiser(error))


def seam_diagnose(monkeypatch, error):
    monkeypatch.setattr(em, "_diagnose_emptiness", raiser(error))


def seam_ancestors(monkeypatch, error):
    monkeypatch.setattr(vf, "ancestor_directories", raiser(error))


CHAIN_SEAMS = [seam_from_bytes, seam_chain]
EMPTINESS_SEAMS = [seam_diagnose, seam_ancestors]
# Par le protocole, `RunSeal.from_bytes` est aussi appelée EN AMONT de `verify_run_chain` (interprète B3) : elle n'isole pas L3-A. Seule la couture `_verify_run_chain` le fait.
PROTOCOL_CHAIN_SEAMS = [seam_chain]


def internal_failure(report, error):
    """Refus typé du point d'entrée, sans aucun champ de rapport recevable."""
    assert report.receivability is ap.Receivability.REFUSED, report
    assert [(d.code, d.stage, d.detail) for d in report.refusals] == [(R.AUDIT_INTERNAL_FAILURE, ap.Stage.PROTOCOL, type(error).__name__)]
    assert report.roots == () and report.blocks == () and report.registry_id is None
    assert report.grants == () and report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE


# ── R1-R2 : `diagnose_emptiness` ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seam", EMPTINESS_SEAMS, ids=lambda s: s.__name__)
@pytest.mark.parametrize("error", CRITICAL, ids=ids(CRITICAL))
def test_r1_r2_diagnose_emptiness_propagates_a_resource_exhaustion(monkeypatch, seam, error):
    tree = tree_of(world())
    seam(monkeypatch, error)
    with pytest.raises(type(error)) as raised:
        em.diagnose_emptiness(tree)
    assert raised.value is error                                                  # l'exception injectée elle-même, jamais une autre levée en route


# ── R3-R4 : `verify_run_chain` ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seam", CHAIN_SEAMS, ids=lambda s: s.__name__)
@pytest.mark.parametrize("error", CRITICAL, ids=ids(CRITICAL))
def test_r3_r4_verify_run_chain_propagates_a_resource_exhaustion(monkeypatch, seam, error):
    tree = tree_of(world())
    seam(monkeypatch, error)
    with pytest.raises(type(error)) as raised:
        vf.verify_run_chain(tree, RUN)
    assert raised.value is error


# ── R5 : par le point d'entrée public, côté vide ──────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seam", EMPTINESS_SEAMS, ids=lambda s: s.__name__)
@pytest.mark.parametrize("error", CRITICAL, ids=ids(CRITICAL))
def test_r5_through_the_protocol_an_emptiness_exhaustion_is_a_typed_internal_refusal_never_a_receivable_report(tmp_path, monkeypatch, seam, error):
    directory = scenario_dir(tmp_path, "01-ready-initial")
    seam(monkeypatch, error)
    report = ap.audit_campaign_exposure(request_of(directory))
    internal_failure(report, error)


# ── R6 : par le point d'entrée public, côté chaîne ────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seam", PROTOCOL_CHAIN_SEAMS, ids=lambda s: s.__name__)
@pytest.mark.parametrize("error", CRITICAL, ids=ids(CRITICAL))
def test_r6_through_the_protocol_a_chain_exhaustion_is_a_typed_internal_refusal_never_a_receivable_report(tmp_path, monkeypatch, seam, error):
    directory, _cid = coherent_campaign(tmp_path)
    seam(monkeypatch, error)
    report = ap.audit_campaign_exposure(request_of(directory))
    internal_failure(report, error)


def test_r6_characterisation_the_chain_seam_is_really_reached_on_the_coherent_world(tmp_path, monkeypatch):
    """Garde-fou de l'injection R6 : sans panne, le monde cohérent atteint `verify_run_chain` et rend un rapport recevable."""
    directory, _cid = coherent_campaign(tmp_path)
    calls = []
    real = vf.verify_run_chain
    monkeypatch.setattr(vf, "verify_run_chain", lambda *a, **k: calls.append(1) or real(*a, **k))
    report = ap.audit_campaign_exposure(request_of(directory))
    assert report.receivability is ap.Receivability.RECEIVABLE and calls == [1]


# ── G1 : comportement historique conservé pour toute autre exception ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seam", EMPTINESS_SEAMS, ids=lambda s: s.__name__)
@pytest.mark.parametrize("error", ORDINARY, ids=ids(ORDINARY))
def test_g1_diagnose_emptiness_keeps_bad_input_for_every_ordinary_exception(monkeypatch, seam, error):
    tree = tree_of(world())
    seam(monkeypatch, error)
    diagnostic = em.diagnose_emptiness(tree)
    assert diagnostic.category is em.EmptinessCategory.BAD_INPUT and diagnostic.reasons == (em.EmptinessReason.BAD_INPUT,)
    assert diagnostic.absence_consideration_blocked is True


@pytest.mark.parametrize("seam", CHAIN_SEAMS, ids=lambda s: s.__name__)
@pytest.mark.parametrize("error", ORDINARY, ids=ids(ORDINARY))
def test_g1_verify_run_chain_keeps_bad_input_for_every_ordinary_exception(monkeypatch, seam, error):
    tree = tree_of(world())
    seam(monkeypatch, error)
    report = vf.verify_run_chain(tree, RUN)
    assert report.established is False and {d.code for d in report.defects} == {K.BAD_INPUT} and report.facts is None


@pytest.mark.parametrize("error", [RuntimeError("simulated"), NotImplementedError("simulated")], ids=["RuntimeError", "NotImplementedError"])
def test_g1_through_the_protocol_a_non_resource_runtime_error_keeps_the_conservative_receivable_blocking_path(tmp_path, monkeypatch, error):
    """Limite connue et voulue (A1) : une `RuntimeError` HORS ressources dans L3-A reste un défaut de données bloquant (`RECEIVABLE` + blocs), contrairement à P5 sur les chargeurs."""
    directory = scenario_dir(tmp_path, "01-ready-initial")
    seam_diagnose(monkeypatch, error)
    report = ap.audit_campaign_exposure(request_of(directory))
    assert report.receivability is ap.Receivability.RECEIVABLE and C.EMPTINESS_BLOCKING in {b.code for b in report.blocks}


def test_g1_through_the_protocol_a_chain_runtime_error_stays_a_chain_blocking_defect(tmp_path, monkeypatch):
    directory, _cid = coherent_campaign(tmp_path)
    seam_chain(monkeypatch, RuntimeError("simulated"))
    report = ap.audit_campaign_exposure(request_of(directory))
    assert report.receivability is ap.Receivability.RECEIVABLE and C.CHAIN_INCOHERENT in {b.code for b in report.blocks}
    assert report.roots[0].chain is ap.ChainStatus.INCOHERENT


# ── S1 : garde de structure — la propagation précède `except Exception` (RecursionError ⊂ RuntimeError ⊂ Exception) ───────────────────────────

def handlers_of(module, function: str) -> list:
    tree = ast.parse(inspect.getsource(module))
    (definition,) = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function]
    (statement,) = [n for n in definition.body if isinstance(n, ast.Try)]
    return statement.handlers


@pytest.mark.parametrize("module,function", [(em, "diagnose_emptiness"), (vf, "verify_run_chain")], ids=["diagnose_emptiness", "verify_run_chain"])
def test_s1_the_resource_clause_comes_first_and_is_a_bare_reraise(module, function):
    handlers = handlers_of(module, function)
    assert len(handlers) == 2
    first, second = handlers
    assert isinstance(first.type, ast.Tuple) and [e.id for e in first.type.elts] == ["MemoryError", "RecursionError"]
    assert len(first.body) == 1 and isinstance(first.body[0], ast.Raise) and first.body[0].exc is None and first.body[0].cause is None
    assert isinstance(second.type, ast.Name) and second.type.id == "Exception"


# ── V1 : versionnement ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_v1_the_public_audit_semantics_change_carries_a_new_protocol_version(tmp_path):
    assert ap.AUDIT_PROTOCOL_VERSION == "gate_v_audit_protocol_v2"
    report = ap.audit_campaign_exposure(request_of(scenario_dir(tmp_path, "01-ready-initial")))
    assert report.protocol_version == "gate_v_audit_protocol_v2"
