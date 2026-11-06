"""P5 — défaillances CRITIQUES d'exécution sur les chemins d'audit : `plan_root_attributed`, `derive_window`, `_manifest_state` et leur appelant `audit_campaign_exposure`.

Règle : une `MemoryError`, une `RecursionError` ou toute autre `RuntimeError` n'est JAMAIS dégradée en racine non attribuée, en source de fenêtre invalide ni en manifeste illisible ;
elle se propage jusqu'au point d'entrée, qui la rend en refus typé `AUDIT_INTERNAL_FAILURE` (contrat public : jamais d'exception, jamais de rapport recevable). Les erreurs ordinaires de
DONNÉES (`ValueError`, `TypeError`, `OSError`) gardent leur traitement.

Origines (vérifiées par lecture) : le chargeur V2 et ses dépendances ne lèvent aucune `RuntimeError` explicitement. Une `RecursionError` peut en revanche venir des DONNÉES : `max_json_depth`
de l'opérateur n'est pas plafonné, un plan très imbriqué accepté par le premier scan peut épuiser la pile dans les récursions Python du chargeur (`_freeze_json`, `dataclasses.asdict`). Ce cas est
VOULU fail-closed : tout l'audit est refusé `AUDIT_INTERNAL_FAILURE` (même règle que D-impl-1 de N2-b2a), jamais une racine « non attribuée » ni un rapport recevable. Plafonner
`max_json_depth` dans la requête serait un changement du contrat de requête de N2-a : proposition séparée, non faite ici. Un `OSError` de niveau système (ENOMEM, EMFILE) reste une erreur de
lecture (limite connue).

Fixtures SYNTHÉTIQUES (`tmp_path`). Aucun A0, aucune admission, aucune écriture de registre par l'audit, aucune donnée de marché, aucun FINAL_HOLDOUT.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gate_v_audit_protocol as ap
import gate_v_audit_registry as ar
import gate_v_audit_window as aw
import gate_v_registry_audit_support as sup
from gate_v_campaign_plan_v2 import save_gate_v_campaign_plan_v2
from tests.gate_v_audit_protocol_support import campaign_spec, request_for, request_of, scenario_dir
from tests.gate_v_audit_window_support import CAMPAIGN_LABEL, HOLDOUT, HOLDOUT_NORMALISED, build_world, derived_request, forge_plan, lay_out, split_spec, window_source

R = ap.RefusalCode
EARLY = ("2025-01-01T00:00:00.000000Z", "2025-02-01T00:00:00.000000Z")
MAX_JSON = 1_000_000
CRITICAL = [MemoryError("simulated"), RecursionError("simulated"), RuntimeError("simulated"), NotImplementedError("simulated")]
DATA = [ValueError("simulated"), TypeError("simulated"), OSError("simulated")]


def ids(errors):
    return [type(error).__name__ for error in errors]


def raiser(error):
    def boom(*args, **kwargs):
        raise error
    return boom


def internal_failure(report, error):
    """Refus typé du point d'entrée, sans aucun champ de rapport recevable."""
    assert report.receivability is ap.Receivability.REFUSED, report
    assert [(d.code, d.stage, d.detail) for d in report.refusals] == [(R.AUDIT_INTERNAL_FAILURE, ap.Stage.PROTOCOL, type(error).__name__)]
    assert report.roots == () and report.blocks == () and report.registry_id is None and report.plan_declared_diagnostic is None
    assert report.grants == () and report.absence_evidence is ap.AbsenceEvidence.UNAVAILABLE


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("p5_world"))


# ── P5-A : `plan_root_attributed` ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def foreign(world, tmp_path):
    """Racine d'une autre campagne avec son plan V2 authentique et le premier scan strict de cette racine."""
    base = tmp_path / "foreign"
    base.mkdir()
    plan = forge_plan(world.plan, budget_per_fold=11)
    path = save_gate_v_campaign_plan_v2(base, plan).parent
    return plan.campaign_id, path, sup.interpret_campaigns([("b", path)])


def attributed(foreign):
    expected, path, s1 = foreign
    return aw.plan_root_attributed(s1, label="b", root_path=str(path), expected_name=expected, max_json_bytes=MAX_JSON)


def test_p5a0_characterisation_an_authentic_foreign_plan_is_attributed(foreign):
    assert attributed(foreign) is True


@pytest.mark.parametrize("boundary", ["load_gate_v_campaign_plan_v2", "_guarded_sha256", "_observed"])
@pytest.mark.parametrize("error", CRITICAL, ids=ids(CRITICAL))
def test_p5a1_a_critical_failure_is_never_read_as_a_non_attributed_root(foreign, monkeypatch, boundary, error):
    monkeypatch.setattr(aw, boundary, raiser(error))
    with pytest.raises(type(error)) as raised:
        attributed(foreign)
    assert raised.value is error                                                  # l'exception injectée elle-même, jamais une sous-classe ou une autre levée en route


@pytest.mark.parametrize("error", DATA, ids=ids(DATA))
def test_p5a2_an_ordinary_data_failure_of_the_loader_still_means_non_attributed(foreign, monkeypatch, error):
    monkeypatch.setattr(aw, "load_gate_v_campaign_plan_v2", raiser(error))
    assert attributed(foreign) is False


def derived_world(tmp_path, world):
    base = tmp_path / "aud"
    base.mkdir()
    layout = lay_out(base, world.plan, world.split_plan)
    plan_b = forge_plan(world.plan, budget_per_fold=11)
    path_b = save_gate_v_campaign_plan_v2(base, plan_b).parent
    root = sup.new_registry(tmp_path, "reg")
    sup.populate(root, sup.build_chain([("R", layout.campaign_id, *HOLDOUT_NORMALISED), ("R", plan_b.campaign_id, *EARLY)]))
    cfg = ar.RegistryConfig(root_path=str(root), max_slots=1000, max_total_bytes=100_000)
    req = request_for(campaign_spec(layout.campaign_dir, label=CAMPAIGN_LABEL), split_spec(layout), campaign_spec(path_b, label="b"), own=layout.campaign_id,
                      window_start_utc=HOLDOUT[0], window_end_utc=HOLDOUT[1], window_source=window_source(), registry=cfg,
                      protocol_limits=ap.ProtocolLimits(max_campaign_roots=8, max_total_read_bytes=10 ** 12))
    return req, path_b


def test_p5a3_characterisation_the_derived_root_reaches_a_receivable_report(tmp_path, world):
    req, _path_b = derived_world(tmp_path, world)
    report = ap.audit_campaign_exposure(req)
    assert report.receivability is ap.Receivability.RECEIVABLE and report.derived_root_labels == ("b",), report.refusals


@pytest.mark.parametrize("error", CRITICAL, ids=ids(CRITICAL))
def test_p5a4_through_the_protocol_a_critical_failure_on_a_foreign_root_is_a_typed_internal_refusal_never_partial_coverage(tmp_path, world, monkeypatch, error):
    req, path_b = derived_world(tmp_path, world)
    real = aw.load_gate_v_campaign_plan_v2
    seen = []

    def load(path):
        if Path(path).resolve().parent == path_b.resolve():                     # seule la racine étrangère : la dérivation de la fenêtre propre reste réelle
            seen.append(path)
            raise error
        return real(path)
    monkeypatch.setattr(aw, "load_gate_v_campaign_plan_v2", load)
    internal_failure(ap.audit_campaign_exposure(req), error)
    assert len(seen) == 1


def test_p5a5_through_the_protocol_a_data_failure_on_a_foreign_root_still_gives_partial_coverage(tmp_path, world, monkeypatch):
    req, path_b = derived_world(tmp_path, world)
    real = aw.load_gate_v_campaign_plan_v2
    monkeypatch.setattr(aw, "load_gate_v_campaign_plan_v2", lambda path: (_ for _ in ()).throw(ValueError("x")) if Path(path).resolve().parent == path_b.resolve() else real(path))
    report = ap.audit_campaign_exposure(req)
    assert report.receivability is ap.Receivability.RECEIVABLE and report.derived_root_labels == () and report.registry_coverage is ar.RegistryCoverage.PARTIAL, report.refusals


# ── P5-B : `derive_window` ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def layout(world, tmp_path):
    return lay_out(tmp_path, world.plan, world.split_plan)


@pytest.mark.parametrize("error", CRITICAL, ids=ids(CRITICAL))
def test_p5b1_a_critical_failure_of_the_loader_is_a_typed_internal_refusal_never_an_invalid_window_source(layout, monkeypatch, error):
    monkeypatch.setattr(aw, "load_gate_v_campaign_plan_v2", raiser(error))
    internal_failure(ap.audit_campaign_exposure(derived_request(layout)), error)


@pytest.mark.parametrize("error", CRITICAL, ids=ids(CRITICAL))
def test_p5b2_characterisation_a_critical_failure_of_the_guarded_read_already_propagates(layout, monkeypatch, error):
    monkeypatch.setattr(aw, "_guarded_sha256", raiser(error))
    internal_failure(ap.audit_campaign_exposure(derived_request(layout)), error)


@pytest.mark.parametrize("error", DATA, ids=ids(DATA))
def test_p5b3_an_ordinary_data_failure_of_the_loader_is_still_an_invalid_window_source(layout, monkeypatch, error):
    monkeypatch.setattr(aw, "load_gate_v_campaign_plan_v2", raiser(error))
    report = ap.audit_campaign_exposure(derived_request(layout))
    assert report.receivability is ap.Receivability.REFUSED and [d.code for d in report.refusals] == [R.WINDOW_SOURCE_INVALID]


# ── P5-C : `_manifest_state` ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_p5c0_characterisation_the_initial_manifest_is_read(tmp_path):
    report = ap.audit_campaign_exposure(request_of(scenario_dir(tmp_path, "01-ready-initial")))
    assert report.receivability is ap.Receivability.RECEIVABLE and report.roots[0].manifest_state is ap.ManifestState.INITIAL


@pytest.mark.parametrize("error", CRITICAL, ids=ids(CRITICAL))
def test_p5c1_a_critical_failure_while_reading_the_manifest_is_a_typed_internal_refusal_never_an_unreadable_manifest(tmp_path, monkeypatch, error):
    monkeypatch.setattr(ap, "parse_strict_json", raiser(error))
    internal_failure(ap.audit_campaign_exposure(request_of(scenario_dir(tmp_path, "01-ready-initial"))), error)


@pytest.mark.parametrize("error", [ValueError("simulated"), TypeError("simulated")], ids=["ValueError", "TypeError"])
def test_p5c2_an_ordinary_data_failure_while_reading_the_manifest_is_still_an_unreadable_manifest(tmp_path, monkeypatch, error):
    monkeypatch.setattr(ap, "parse_strict_json", raiser(error))
    report = ap.audit_campaign_exposure(request_of(scenario_dir(tmp_path, "01-ready-initial")))
    assert report.receivability is ap.Receivability.RECEIVABLE and report.roots[0].manifest_state is ap.ManifestState.UNREADABLE_OR_NONCONFORMING


@pytest.mark.parametrize("status", [["READY_FOR_EXECUTION"], {"k": "v"}], ids=["list", "object"])
def test_p5c3_an_unhashable_status_is_a_data_failure_never_an_exception(tmp_path, monkeypatch, status):
    """Données réelles du chemin : un `status` non hachable lève `TypeError` dans la table des alias ; il reste « illisible ou non conforme »."""
    monkeypatch.setattr(ap, "parse_strict_json", lambda raw, **k: {"status": status})
    report = ap.audit_campaign_exposure(request_of(scenario_dir(tmp_path, "01-ready-initial")))
    assert report.receivability is ap.Receivability.RECEIVABLE and report.roots[0].manifest_state is ap.ManifestState.UNREADABLE_OR_NONCONFORMING


# ── Garde statique : les trois gestionnaires ne nomment plus de défaillance critique ─────────────────────────────────────────────────────────

def test_p5s_the_handlers_name_only_ordinary_data_errors():
    import ast
    import inspect
    for function in (aw.plan_root_attributed, aw.derive_window, ap._manifest_state):
        tree = ast.parse(inspect.getsource(function).replace("\r\n", "\n").lstrip())
        handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
        assert handlers, function.__name__
        for handler in handlers:
            assert handler.type is not None, function.__name__
            names = {n.id if isinstance(n, ast.Name) else n.attr for n in ast.walk(handler.type) if isinstance(n, (ast.Name, ast.Attribute))}
            assert not names & {"Exception", "BaseException", "MemoryError", "RecursionError", "RuntimeError", "NotImplementedError"}, (function.__name__, names)
