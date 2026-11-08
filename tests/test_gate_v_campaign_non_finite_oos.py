"""PN-1-S1 — les trois sites de `gate_v_campaign.py` (V1) qui re-sérialisent un run : empreinte OOS à la création du plan, même empreinte
recalculée à chaque dérivation de statut, record attendu à la sauvegarde du manifeste. Plus l'exécuteur V1 de bout en bout.

Fixtures synthétiques (monde de `tests/test_gate_v_campaign.py`) : aucune donnée de marché, aucun accès FINAL_HOLDOUT.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import math
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_v_campaign
import validation_run as vr
import tests.test_gate_v_campaign as tg
from gate_v_campaign import (
    build_gate_v_campaign_plan,
    derive_gate_v_campaign_status,
    load_gate_v_campaign_manifest,
    load_gate_v_campaign_plan,
    save_gate_v_campaign_manifest,
    save_gate_v_campaign_plan,
)
from gate_v_exposure_scan import parse_strict_json
from validation_run import (
    VALIDATION_TYPE_OOS,
    VALIDATION_TYPE_WALK_FORWARD,
    build_oos_validation_evidence,
    build_oos_validation_specification,
    build_validation_run,
    load_validation_run,
    save_validation_run,
)

INF = math.inf
# Valeurs relevées sur le clone NON modifié (02d40df) pour le monde synthétique à OOS fini.
FINITE_CAMPAIGN_ID = "gate_v_a2f8f8dfc52cead1933632f7314bc696a7ca65ea5b8071f480954d54811e95a6"
FINITE_OOS_EVIDENCE_HASH = "fad45c514e10c1ac53c34f80c05a5db8ce99d3fc7827f315fc715e4128ff014b"


def _oos_run_with(path, *, profit_factor, win_rate, validation_run_id="synthetic_oos_001", snapshot_id=tg._SNAPSHOT_ID,
                  split_plan_id="synthetic_split", strategy_name="Synthetic Strategy"):
    run = build_validation_run(
        validation_run_id=validation_run_id, research_run_id="external_research_synthetic", split_plan_id=split_plan_id,
        dataset_snapshot_id=snapshot_id, strategy_name=strategy_name, strategy_params={"lookback": 12},
        specification=build_oos_validation_specification("2025-01-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00"),
        evidence=build_oos_validation_evidence("2025-01-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00", 3, 1.5,
                                               profit_factor, win_rate, 0.5),
        validation_type=VALIDATION_TYPE_OOS, completed_at="2025-07-01T00:00:00+00:00")
    save_validation_run(path, run)
    return run


def _infinite_oos(path, **kwargs):
    return _oos_run_with(path, profit_factor=INF, win_rate=100.0, **kwargs)


@pytest.fixture()
def infinite_world(tmp_path, monkeypatch):
    """Même monde que `_synthetic_campaign_evidence`, mais l'OOS référencé a `profit_factor = +inf`."""
    monkeypatch.setattr(tg, "_synthetic_oos_run", _infinite_oos)
    return tg._synthetic_campaign_evidence(tmp_path)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _old_oos_payload(run) -> str:
    return json.dumps(dataclasses.asdict(run), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


# ═══ 11. identité V1 : inchangée pour un OOS fini, stable pour un OOS à +inf ═══════════════════════════════════════════════════════

def test_the_campaign_identity_and_oos_hash_of_a_finite_oos_run_are_unchanged(tmp_path):
    plan, runs, *_ = tg._synthetic_campaign_evidence(tmp_path)
    assert plan.campaign_id == FINITE_CAMPAIGN_ID
    assert plan.oos_evidence_hash == FINITE_OOS_EVIDENCE_HASH
    assert plan.oos_evidence_hash == _sha(_old_oos_payload(runs[plan.oos_evidence_validation_run_id]))


def test_a_plan_can_now_be_built_on_an_oos_run_with_infinite_profit_factor(infinite_world):
    plan, runs, *_ = infinite_world
    oos = runs[plan.oos_evidence_validation_run_id]
    assert oos.evidence.profit_factor == INF
    assert plan.oos_evidence_hash == _sha(vr.canonical_oos_evidence_payload(oos))
    assert plan.oos_evidence_hash != FINITE_OOS_EVIDENCE_HASH and plan.campaign_id != FINITE_CAMPAIGN_ID


def test_the_infinite_oos_identity_is_stable_across_independent_builds(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(tg, "_synthetic_oos_run", _infinite_oos)
    first = tg._synthetic_campaign_evidence(tmp_path_factory.mktemp("a"))[0]
    second = tg._synthetic_campaign_evidence(tmp_path_factory.mktemp("b"))[0]
    assert (first.campaign_id, first.oos_evidence_hash) == (second.campaign_id, second.oos_evidence_hash)


# ═══ 12. site 1 — création du plan, recalculée à chaque reconstruction ═════════════════════════════════════════════════════════════

def test_the_plan_is_rebuilt_to_an_equal_plan_with_the_infinite_oos(infinite_world):
    plan = infinite_world[0]
    assert gate_v_campaign._rebuild_plan(plan) == plan


def test_the_plan_saves_and_reloads_with_the_infinite_oos(infinite_world, tmp_path):
    plan = infinite_world[0]
    root = tmp_path / "gate_v_campaign"
    path = save_gate_v_campaign_plan(root, plan)
    loaded = load_gate_v_campaign_plan(path, split_plan_path=plan.split_plan_path, oos_evidence_path=plan.oos_evidence_path)
    assert loaded == plan


# ═══ site 2 — dérivation du statut ═══════════════════════════════════════════════════════════════════════════════════════════════════

def test_the_status_is_derived_with_the_infinite_oos_in_memory_and_reloaded_from_its_file(infinite_world):
    plan, runs, wf_id, mc_id, ps_by_fold = infinite_world
    manifest = tg._complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    assert derive_gate_v_campaign_status(plan, manifest, runs) == "EVIDENCE_COMPLETE_AWAITING_POLICY"
    reloaded = dict(runs)
    reloaded[plan.oos_evidence_validation_run_id] = load_validation_run(plan.oos_evidence_path)
    assert derive_gate_v_campaign_status(plan, manifest, reloaded) == "EVIDENCE_COMPLETE_AWAITING_POLICY"


def test_a_modified_oos_run_no_longer_matches_the_plan_hash(infinite_world):
    plan, runs, wf_id, mc_id, ps_by_fold = infinite_world
    manifest = tg._complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold)
    oos_id = plan.oos_evidence_validation_run_id
    altered = dataclasses.replace(runs[oos_id], evidence=dataclasses.replace(runs[oos_id].evidence, net_ret_pct=9.9))
    with pytest.raises(ValueError, match="empreinte"):
        derive_gate_v_campaign_status(plan, manifest, {**runs, oos_id: altered})


# ═══ site 3 — record attendu à la sauvegarde du manifeste ═══════════════════════════════════════════════════════════════════════════

def _persist_all(plan, runs, tmp_path):
    root = tmp_path / "gate_v_campaign"
    save_gate_v_campaign_plan(root, plan)
    paths = {}
    for run_id, run in runs.items():
        if run_id == plan.oos_evidence_validation_run_id:
            paths[run_id] = plan.oos_evidence_path
            continue
        path = root / plan.campaign_id / "validations" / run_id / "validation_run.json"
        save_validation_run(path, run)
        paths[run_id] = path
    return root, paths


def _complete_manifest(plan, wf_id, mc_id, ps_by_fold):
    return dataclasses.replace(tg._complete_synthetic_manifest(plan, wf_id, mc_id, ps_by_fold), status="EVIDENCE_COMPLETE_AWAITING_POLICY")


def test_a_complete_manifest_with_the_infinite_oos_is_saved_and_reloaded(infinite_world, tmp_path):
    plan, runs, wf_id, mc_id, ps_by_fold = infinite_world
    root, paths = _persist_all(plan, runs, tmp_path)
    manifest = _complete_manifest(plan, wf_id, mc_id, ps_by_fold)
    path = save_gate_v_campaign_manifest(root, plan, manifest, evidence_by_validation_run_id=runs, evidence_paths_by_validation_run_id=paths)
    assert load_gate_v_campaign_manifest(path, plan) == manifest


def _with_infinite_wf_aggregate(runs, wf_id):
    wf = runs[wf_id]
    aggregate = dataclasses.replace(wf.evidence.aggregate, oos_profit_factor=INF)
    return {**runs, wf_id: dataclasses.replace(wf, evidence=dataclasses.replace(wf.evidence, aggregate=aggregate))}


def test_site_3_accepts_a_walk_forward_proof_whose_aggregate_is_the_marker(tmp_path):
    plan, runs, wf_id, mc_id, ps_by_fold = tg._synthetic_campaign_evidence(tmp_path)
    runs = _with_infinite_wf_aggregate(runs, wf_id)
    root, paths = _persist_all(plan, runs, tmp_path)
    assert json.loads(paths[wf_id].read_text(encoding="utf-8"))["evidence"]["aggregate"]["oos_profit_factor"] == {"kind": "float", "value": "+inf"}
    path = save_gate_v_campaign_manifest(root, plan, _complete_manifest(plan, wf_id, mc_id, ps_by_fold),
                                         evidence_by_validation_run_id=runs, evidence_paths_by_validation_run_id=paths)
    assert path.is_file()


def test_site_3_still_accepts_a_historical_walk_forward_file_with_the_infinity_token(tmp_path):
    plan, runs, wf_id, mc_id, ps_by_fold = tg._synthetic_campaign_evidence(tmp_path)
    runs = _with_infinite_wf_aggregate(runs, wf_id)
    root, paths = _persist_all(plan, runs, tmp_path)
    paths[wf_id].unlink()
    text = json.dumps(dataclasses.asdict(runs[wf_id]), ensure_ascii=False, indent=2) + "\n"
    paths[wf_id].write_text(text, encoding="utf-8")
    assert "Infinity" in paths[wf_id].read_text(encoding="utf-8")
    path = save_gate_v_campaign_manifest(root, plan, _complete_manifest(plan, wf_id, mc_id, ps_by_fold),
                                         evidence_by_validation_run_id=runs, evidence_paths_by_validation_run_id=paths)
    assert path.is_file()


def test_site_3_refuses_a_walk_forward_file_that_differs_from_the_independent_expected_run(tmp_path):
    plan, runs, wf_id, mc_id, ps_by_fold = tg._synthetic_campaign_evidence(tmp_path)
    infinite = _with_infinite_wf_aggregate(runs, wf_id)
    root, paths = _persist_all(plan, infinite, tmp_path)
    expected = _with_finite_wf_aggregate(runs, wf_id)
    with pytest.raises(ValueError, match="preuve"):
        save_gate_v_campaign_manifest(root, plan, _complete_manifest(plan, wf_id, mc_id, ps_by_fold),
                                      evidence_by_validation_run_id=expected, evidence_paths_by_validation_run_id=paths)


def _with_finite_wf_aggregate(runs, wf_id):
    wf = runs[wf_id]
    aggregate = dataclasses.replace(wf.evidence.aggregate, oos_profit_factor=2.0)
    return {**runs, wf_id: dataclasses.replace(wf, evidence=dataclasses.replace(wf.evidence, aggregate=aggregate))}


def test_site_3_refuses_a_marker_forged_outside_the_closed_paths_against_an_independent_expected_run(tmp_path):
    plan, runs, wf_id, mc_id, ps_by_fold = tg._synthetic_campaign_evidence(tmp_path)
    root, paths = _persist_all(plan, runs, tmp_path)
    record = json.loads(paths[wf_id].read_text(encoding="utf-8"))
    record["evidence"]["aggregate"]["oos_net_return_pct"] = {"kind": "float", "value": "+inf"}
    paths[wf_id].write_text(json.dumps(record, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="preuve"):
        save_gate_v_campaign_manifest(root, plan, _complete_manifest(plan, wf_id, mc_id, ps_by_fold),
                                      evidence_by_validation_run_id=runs, evidence_paths_by_validation_run_id=paths)


def test_site_3_refuses_an_altered_file(tmp_path):
    plan, runs, wf_id, mc_id, ps_by_fold = tg._synthetic_campaign_evidence(tmp_path)
    root, paths = _persist_all(plan, runs, tmp_path)
    record = json.loads(paths[wf_id].read_text(encoding="utf-8"))
    record["completed_at"] = "2026-01-01T00:00:00+00:00"
    paths[wf_id].write_text(json.dumps(record, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="preuve"):
        save_gate_v_campaign_manifest(root, plan, _complete_manifest(plan, wf_id, mc_id, ps_by_fold),
                                      evidence_by_validation_run_id=runs, evidence_paths_by_validation_run_id=paths)


# ═══ D-S1-1, 13 : fichier OOS historique — refus conservés, aucun refus de plus pour les fichiers qui passent aujourd'hui ═══════════

def _plan_inputs(tmp_path):
    inputs = tg._plan_kwargs(tmp_path)               # le plan de découpage est immuable : une seule fois par dossier
    inputs["oos_evidence_validation_run_id"] = "synthetic_oos_001"
    return inputs


def _oos_file(tmp_path, name, mutate_text=None):
    path = tmp_path / name
    tg._synthetic_oos_run(path)
    if mutate_text is not None:
        path.write_text(mutate_text(path.read_text(encoding="utf-8")), encoding="utf-8")
    return path


def test_site_1_refuses_a_historical_oos_file_with_the_infinity_token(tmp_path):
    inputs = tg._plan_kwargs(tmp_path)
    inputs["oos_evidence_validation_run_id"] = "synthetic_oos_001"
    path = tmp_path / "legacy_oos.json"
    run = _oos_run_with(tmp_path / "scratch.json", profit_factor=INF, win_rate=100.0)
    path.write_text(json.dumps(dataclasses.asdict(run), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert "Infinity" in path.read_text(encoding="utf-8")
    inputs["oos_evidence_path"] = path
    with pytest.raises(ValueError, match="OOS"):
        build_gate_v_campaign_plan(**inputs)


@pytest.mark.parametrize("token", ["NaN", "-Infinity", "1e999"])
def test_site_1_refuses_every_non_finite_spelling_in_the_run_fields(tmp_path, token):
    inputs = _plan_inputs(tmp_path)
    inputs["oos_evidence_path"] = _oos_file(tmp_path, "oos.json", lambda t: t.replace('"net_ret_pct": 0.0', f'"net_ret_pct": {token}'))
    with pytest.raises(ValueError, match="OOS"):
        build_gate_v_campaign_plan(**inputs)


def test_site_1_adds_no_refusal_for_duplicate_keys_nor_for_non_finite_in_an_ignored_extra_key(tmp_path):
    inputs = _plan_inputs(tmp_path)
    hashes = []
    for name, mutate in (
        ("base.json", None),
        ("dup.json", lambda t: t.replace('"status": "completed"', '"status": "completed", "status": "completed"')),
        ("extra.json", lambda t: t.replace('"status": "completed"', '"status": "completed", "extra": Infinity')),
    ):
        plan = build_gate_v_campaign_plan(**{**inputs, "oos_evidence_path": _oos_file(tmp_path, name, mutate)})
        hashes.append(plan.oos_evidence_hash)
    assert len(set(hashes)) == 1


@pytest.mark.parametrize("replacement", ["true", '"inf"', "[1.0]", '{"x": 1}'])
def test_the_deliberate_new_refusal_a_forbidden_type_at_the_oos_closed_path(tmp_path, replacement):
    inputs = tg._plan_kwargs(tmp_path)
    inputs["oos_evidence_validation_run_id"] = "synthetic_oos_001"
    path = tmp_path / "typed_oos.json"
    _oos_run_with(path, profit_factor=2.0, win_rate=50.0)
    path.write_text(path.read_text(encoding="utf-8").replace('"profit_factor": 2.0', f'"profit_factor": {replacement}'), encoding="utf-8")
    inputs["oos_evidence_path"] = path
    with pytest.raises(vr.NonFiniteMetricRefused):
        build_gate_v_campaign_plan(**inputs)


@pytest.mark.parametrize("replacement", ["true", '"inf"', "[1.0]", '{"x": 1}'])
def test_the_same_forbidden_type_is_refused_by_the_plan_rebuild_when_the_oos_file_is_swapped_after_the_plan_was_built(infinite_world, replacement):
    """Contrat ligne 13 : le refus vaut aussi à `_rebuild_plan` (point d'entrée de la dérivation de statut, de l'exécution et de la reprise)."""
    plan = infinite_world[0]
    path = Path(plan.oos_evidence_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["evidence"]["profit_factor"] == {"kind": "float", "value": "+inf"}
    record["evidence"]["profit_factor"] = json.loads(replacement)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(vr.NonFiniteMetricRefused):
        gate_v_campaign._rebuild_plan(plan)


# ═══ 12. inspection de source : une seule représentation canonique ═══════════════════════════════════════════════════════════════════

def test_sites_1_and_2_call_the_same_canonical_function_and_site_3_the_decoder():
    site_1 = inspect.getsource(gate_v_campaign.build_gate_v_campaign_plan)
    site_2 = inspect.getsource(gate_v_campaign.derive_gate_v_campaign_status)
    site_3 = inspect.getsource(gate_v_campaign.save_gate_v_campaign_manifest)
    assert "canonical_oos_evidence_payload" in site_1 and "canonical_oos_evidence_payload" in site_2
    assert "require_no_legacy_non_finite_in_run_file" in site_1
    assert "decode_validation_run_record" in site_3
    assert "allow_nan=False" not in site_1 and "allow_nan=False" not in site_2


def test_gate_v_campaign_source_never_mentions_the_final_holdout_access_words():
    assert "final_holdout" not in inspect.getsource(gate_v_campaign).lower()


# ═══ exécuteur V1 de bout en bout ════════════════════════════════════════════════════════════════════════════════════════════════════

def test_the_v1_executor_writes_a_strictly_readable_walk_forward_proof_when_the_aggregate_is_infinite(tmp_path):
    plan, split_plan, campaign_root = tg._execute_ready_campaign(tmp_path)
    run_fn, _calls = tg._execute_fake_run_with_trades(plan, split_plan, tg._MC_TRADES_BY_FOLD)
    tg._execute(plan, campaign_root, tmp_path, run_walk_forward_fn=run_fn, resume_walk_forward_fn=tg._never_called("resume"))
    wf_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
    path = campaign_root / plan.campaign_id / "validations" / wf_id / "validation_run.json"
    document = parse_strict_json(path.read_bytes(), max_bytes=10**7, max_depth=64)
    aggregate = document["evidence"]["aggregate"]
    assert aggregate["oos_profit_factor"] == {"kind": "float", "value": "+inf"}
    assert load_validation_run(path).evidence.aggregate["oos_profit_factor"] == INF
    assert b"Infinity" not in path.read_bytes() and b"NaN" not in path.read_bytes()


def test_the_v1_executor_refuses_a_nan_run_after_persisting_the_fold_artifacts_and_marks_a_technical_failure(tmp_path):
    plan, split_plan, campaign_root = tg._execute_ready_campaign(tmp_path)
    results, artifacts = tg._execute_fold_results_and_artifacts_with_trades(
        plan, split_plan, {"fold_000": [{"resultat_net": 10.0, "capital_apres": 10_010.0}]})
    results = tuple(dataclasses.replace(r, net_ret_pct=math.nan) if r.fold_id == "fold_000" else r for r in results)
    run_fn = tg._real_capture_delegate(results, artifacts)
    with pytest.raises(vr.NonFiniteMetricRefused):
        tg._execute(plan, campaign_root, tmp_path, run_walk_forward_fn=run_fn, resume_walk_forward_fn=tg._never_called("resume"))
    campaign_dir = campaign_root / plan.campaign_id
    wf_id = gate_v_campaign.gate_v_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD)
    assert not (campaign_dir / "validations" / wf_id / "validation_run.json").exists()
    assert not list(campaign_dir.rglob("*.tmp"))
    assert (campaign_dir / "walk_forward" / "aggregate.json").is_file(), "les artefacts de pli sont déjà écrits avant le refus"
    manifest = load_gate_v_campaign_manifest(campaign_dir / "manifest.json", plan)
    assert manifest.status == "TECHNICAL_FAILURE"
