"""PN-1-S1 — frontières : B2 strict, B3 v6, L3-A, validateur V2 de complétude. Fixtures synthétiques ; aucune donnée de marché ; aucun accès
FINAL_HOLDOUT. Le contraste « ancien écrivain » (token `Infinity`) prouve que le défaut était bien le fichier, pas l'audit."""

from __future__ import annotations

import dataclasses
import json
import math
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _gate_v_claim_world as cw
import gate_v_evidence_completeness_v2 as c2
from gate_v_exposure_scan import SourceAnomaly, StrictJsonError, parse_strict_json
from tests.gate_v_registry_audit_support import interpret_campaigns
from tests.test_gate_v_k1s2_verifier import K, RUN, codes, verify, world
from validation_run import WalkForwardEvidence, load_validation_run, save_validation_run
import walk_forward

INF = math.inf


def _legacy_bytes(run) -> bytes:
    text = json.dumps(dataclasses.asdict(run), ensure_ascii=False, indent=2) + "\n"
    return text.replace("\n", os.linesep).encode("utf-8")


def _consistent_fold(fold, *, gross_win, gross_loss, n_trades, n_win):
    profit_factor = gross_win / gross_loss if gross_loss > 0 else INF
    return dataclasses.replace(
        fold, n_trades=n_trades, zero_trade_oos=False, profit_factor=profit_factor, gross_win=gross_win, gross_loss=gross_loss, n_win=n_win,
        win_rate=n_win / n_trades * 100, max_dd_pct=1.0, expectancy=1.0, net_ret_pct=1.0, score_test=50.0)


def _loss_free_variant(run, specs):
    folds = tuple(_consistent_fold(f, **spec) for f, spec in zip(run.evidence.fold_results, specs))
    evidence = WalkForwardEvidence(folds, walk_forward.build_aggregate_result(folds), "completed", "INCONCLUSIVE", ())
    return dataclasses.replace(run, evidence=evidence)


LOSS_FREE = dict(gross_win=10.0, gross_loss=0.0, n_trades=3, n_win=3)
LOSSY = dict(gross_win=10.0, gross_loss=5.0, n_trades=3, n_win=2)


@pytest.fixture(scope="module")
def synthetic_world(tmp_path_factory):
    return cw.build_world(tmp_path_factory.mktemp("pn1_world") / "w")


# ═══ 8. B2 strict ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_b2_reads_the_file_of_a_loss_free_run_written_by_the_new_writer(tmp_path, synthetic_world):
    base = synthetic_world.proofs[cw._ids(synthetic_world.plan)["wf"]]
    run = _loss_free_variant(base, [LOSS_FREE, LOSSY, LOSSY])
    path = save_validation_run(tmp_path / "v.json", run)
    document = parse_strict_json(path.read_bytes(), max_bytes=10**7, max_depth=64)
    assert document["evidence"]["fold_results"][0]["profit_factor"] == {"kind": "float", "value": "+inf"}


def test_b2_refuses_the_same_run_written_by_the_old_writer_with_non_finite(tmp_path, synthetic_world):
    base = synthetic_world.proofs[cw._ids(synthetic_world.plan)["wf"]]
    run = _loss_free_variant(base, [LOSS_FREE, LOSSY, LOSSY])
    with pytest.raises(StrictJsonError) as excinfo:
        parse_strict_json(_legacy_bytes(run), max_bytes=10**7, max_depth=64)
    assert excinfo.value.anomaly is SourceAnomaly.NON_FINITE


# ═══ 9. B3 v6 ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

def _b3_findings_with(world_, tmp_path, writer_bytes):
    """Copie physique du monde synthétique, dont le run Walk-Forward est remplacé ; B3 v6 réel."""
    clone = world_.clone_into(tmp_path / "clone")
    wf_id = cw._ids(clone.plan)["wf"]
    path = clone.campaign_dir / "validations" / wf_id / "validation_run.json"
    path.unlink()
    path.write_bytes(writer_bytes)
    interpretation = interpret_campaigns([("CAMP", clone.campaign_dir)])
    wf_findings = [f for f in interpretation.findings if wf_id in f.source_id and f.source_id.endswith("validation_run.json")]
    return interpretation, wf_findings


def test_b3_v6_reads_a_loss_free_run_without_unreadable_finding_or_source_anomaly(tmp_path, synthetic_world):
    base = synthetic_world.proofs[cw._ids(synthetic_world.plan)["wf"]]
    run = _loss_free_variant(base, [LOSS_FREE, LOSSY, LOSSY])
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    new_bytes = save_validation_run(scratch / "v.json", run).read_bytes()
    interpretation, findings = _b3_findings_with(synthetic_world, tmp_path, new_bytes)
    assert len(findings) == 1
    assert findings[0].unresolved_cause.value == "WINDOW_UNKNOWN"
    assert "SOURCE_ANOMALY" not in {reason.split(":")[0] for reason in interpretation.incomplete_reasons}


def test_b3_v6_flags_the_old_writer_output_as_unreadable_with_source_anomaly(tmp_path, synthetic_world):
    base = synthetic_world.proofs[cw._ids(synthetic_world.plan)["wf"]]
    run = _loss_free_variant(base, [LOSS_FREE, LOSSY, LOSSY])
    interpretation, findings = _b3_findings_with(synthetic_world, tmp_path, _legacy_bytes(run))
    assert len(findings) == 1 and findings[0].unresolved_cause.value == "UNREADABLE"
    assert "SOURCE_ANOMALY" in {reason.split(":")[0] for reason in interpretation.incomplete_reasons}


def test_b3_requires_the_exact_top_level_key_set_and_the_new_writer_keeps_it(tmp_path, synthetic_world):
    base = synthetic_world.proofs[cw._ids(synthetic_world.plan)["wf"]]
    run = _loss_free_variant(base, [LOSS_FREE, LOSSY, LOSSY])
    record = json.loads(save_validation_run(tmp_path / "v.json", run).read_text(encoding="utf-8"))
    assert set(record) == set(dataclasses.asdict(run))


# ═══ 10. L3-A ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

def _run_with_id(synthetic_world, run_id):
    base = synthetic_world.proofs[cw._ids(synthetic_world.plan)["wf"]]
    return dataclasses.replace(_loss_free_variant(base, [LOSS_FREE, LOSSY, LOSSY]), validation_run_id=run_id)


def test_l3a_establishes_the_chain_of_a_loss_free_run_written_by_the_new_writer(tmp_path, synthetic_world):
    run = _run_with_id(synthetic_world, RUN)
    data = save_validation_run(tmp_path / "v.json", run).read_bytes()
    report = verify(world(run_data=data))
    assert report.defects == () and report.established is True


def test_l3a_refuses_the_old_writer_output_as_not_attributable(tmp_path, synthetic_world):
    run = _run_with_id(synthetic_world, RUN)
    report = verify(world(run_data=_legacy_bytes(run)))
    assert K.RUN_NOT_ATTRIBUTABLE in codes(report)


# ═══ validateur V2 de complétude : même verdict avant sérialisation et après relecture ═══════════════════════════════════════════

def test_the_v2_completeness_verdict_is_identical_before_serialisation_and_after_reload(tmp_path, synthetic_world):
    plan = synthetic_world.plan
    run = _loss_free_variant(synthetic_world.proofs[cw._ids(plan)["wf"]], [LOSS_FREE, LOSSY, LOSSY])
    before = c2.walk_forward_evidence_complete_v2(plan, run)
    reloaded = load_validation_run(save_validation_run(tmp_path / "v.json", run))
    assert before is True and c2.walk_forward_evidence_complete_v2(plan, reloaded) is True


def test_the_v2_validator_refuses_a_forged_marker_on_a_fold_with_a_finite_loss(tmp_path, synthetic_world):
    plan = synthetic_world.plan
    run = _loss_free_variant(synthetic_world.proofs[cw._ids(plan)["wf"]], [LOSS_FREE, LOSSY, LOSSY])
    path = save_validation_run(tmp_path / "v.json", run)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["evidence"]["fold_results"][1]["profit_factor"] = {"kind": "float", "value": "+inf"}
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="profit_factor"):
        c2.walk_forward_evidence_complete_v2(plan, load_validation_run(forged))


def test_the_v2_validator_refuses_a_marker_dictionary_it_cannot_decode(tmp_path, synthetic_world):
    plan = synthetic_world.plan
    run = _loss_free_variant(synthetic_world.proofs[cw._ids(plan)["wf"]], [LOSS_FREE, LOSSY, LOSSY])
    record = json.loads(save_validation_run(tmp_path / "v.json", run).read_text(encoding="utf-8"))
    record["evidence"]["fold_results"][0]["profit_factor"] = {"kind": "float", "value": "-inf"}
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError):
        c2.walk_forward_evidence_complete_v2(plan, load_validation_run(forged))


# ═══ 17. aucune admission ni validation supplémentaire ═══════════════════════════════════════════════════════════════════════════════

def test_the_completeness_verdict_is_the_same_for_the_in_memory_run_and_the_run_reloaded_from_the_new_writer_file(synthetic_world):
    """La preuve du monde synthétique relue par le nouvel écrivain redonne les mêmes verdicts de complétude que l'objet en mémoire."""
    plan = synthetic_world.plan
    wf_id = cw._ids(plan)["wf"]
    run = synthetic_world.proofs[wf_id]
    assert c2.walk_forward_evidence_complete_v2(plan, run) == c2.walk_forward_evidence_complete_v2(
        plan, load_validation_run(Path(synthetic_world.campaign_dir) / "validations" / wf_id / "validation_run.json"))
