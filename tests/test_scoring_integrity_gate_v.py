"""Scoring Integrity — garde de provenance Gate V (ADR 0029, S-2 option A, G-8..G-11).

Seam : `gate_v_campaign.execute_gate_v_campaign`. Une preuve Walk-Forward (et les preuves
Monte-Carlo / Parameter Stability qui en dérivent) n'est réutilisée que si le manifeste de capture
du checkpoint est égal, clé par clé, au manifeste attendu sous `finite-metrics-v1`. « Legacy » est
simulé en retirant `scoring_semantics_version` d'une capture réelle : exactement le manifeste qu'une
capture antérieure à la correction aurait écrit.
"""
from __future__ import annotations

import dataclasses
import json
import shutil

import pytest

import gate_v_campaign as gvc
from scoring import ScoreWeights
from tests.test_gate_v_campaign import (
    _execute, _execute_base_config, _execute_data_manifest, _execute_fake_run,
    _execute_ready_campaign, _never_called,
)


def _full_campaign(tmp_path):
    plan, split_plan, root = _execute_ready_campaign(tmp_path)
    dm = _execute_data_manifest(tmp_path)  # manifeste de données immuable : créé UNE fois
    run_fn, _ = _execute_fake_run(plan, split_plan)
    manifest = _execute(plan, root, tmp_path, run_walk_forward_fn=run_fn,
                        resume_walk_forward_fn=_never_called("resume"), data_manifest_path=dm)
    return plan, split_plan, root, manifest, dm


def _campaign_dir(root, plan):
    return root / plan.campaign_id


def _legacyize(root, plan, *names):
    """Retire la clé de sémantique des manifestes Walk-Forward présents (capture et/ou run)."""
    wf_dir = _campaign_dir(root, plan) / "walk_forward"
    for path in (wf_dir / ".gate_v_checkpoints_v1" / "manifest.json", wf_dir / "manifest.json"):
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop("scoring_semantics_version", None)
            path.write_text(json.dumps(data), encoding="utf-8")


def _reset_campaign_manifest(root, plan):
    """Crash avant le rattachement : artefacts présents, manifeste de campagne absent."""
    (_campaign_dir(root, plan) / "manifest.json").unlink()


def _manifest_bytes(root, plan):
    path = _campaign_dir(root, plan) / "manifest.json"
    return path.read_bytes() if path.is_file() else None


def _assert_refused_before_mutation(plan, root, tmp_path, dm, **fns):
    before = _manifest_bytes(root, plan)
    kw = dict(fns.get("kw", {}), data_manifest_path=dm)
    with pytest.raises(gvc.GateVEvidenceProvenanceMismatch):
        _execute(plan, root, tmp_path,
                 run_walk_forward_fn=fns.get("run", _never_called("run")),
                 resume_walk_forward_fn=fns.get("resume", _never_called("resume")), **kw)
    assert _manifest_bytes(root, plan) == before  # aucune mutation du manifeste de campagne
    if before is not None:
        reloaded = gvc.load_gate_v_campaign_manifest(_campaign_dir(root, plan) / "manifest.json", plan)
        assert reloaded.technical_failure_reason is None  # refus de précondition, jamais TECHNICAL_FAILURE


def test_r63_complete_finite_metrics_campaign_is_reused_unchanged(tmp_path):
    plan, _split, root, manifest, dm = _full_campaign(tmp_path)
    before = _manifest_bytes(root, plan)
    again = _execute(plan, root, tmp_path, run_walk_forward_fn=_never_called("run"),
                     resume_walk_forward_fn=_never_called("resume"), data_manifest_path=dm)
    assert again.status == manifest.status and _manifest_bytes(root, plan) == before


def test_r57_r60_r61_legacy_evidence_already_attached_is_refused(tmp_path):
    """Chemins 4 et 5 : ids Walk-Forward / MC / PS déjà rattachés — la phase WF serait sautée."""
    plan, _split, root, _, dm = _full_campaign(tmp_path)
    _legacyize(root, plan)
    _assert_refused_before_mutation(plan, root, tmp_path, dm)


def test_r57_existing_validation_run_with_detached_manifest_is_refused_when_legacy(tmp_path):
    """Chemin 1 : validation_run.json présent, manifeste de campagne remis à zéro (crash)."""
    plan, _split, root, _, dm = _full_campaign(tmp_path)
    _reset_campaign_manifest(root, plan)
    _legacyize(root, plan)
    _assert_refused_before_mutation(plan, root, tmp_path, dm)


def test_r58_existing_aggregate_without_validation_run_is_refused_when_legacy(tmp_path):
    """Chemin 2 : aggregate.json réutilisable, validation_run.json absent."""
    plan, _split, root, _, dm = _full_campaign(tmp_path)
    _reset_campaign_manifest(root, plan)
    shutil.rmtree(_campaign_dir(root, plan) / "validations")
    _legacyize(root, plan)
    _assert_refused_before_mutation(plan, root, tmp_path, dm)


def test_r59_checkpoint_resume_is_refused_before_any_compute_when_legacy(tmp_path):
    """Chemin 3 : seul le checkpoint de capture subsiste -> reprise ; refusée AVANT resume_fn."""
    plan, _split, root, _, dm = _full_campaign(tmp_path)
    cdir = _campaign_dir(root, plan)
    _reset_campaign_manifest(root, plan)
    shutil.rmtree(cdir / "validations")
    wf_dir = cdir / "walk_forward"
    for child in wf_dir.iterdir():
        if child.name != ".gate_v_checkpoints_v1":
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    _legacyize(root, plan)
    _assert_refused_before_mutation(plan, root, tmp_path, dm)


def test_r62_orphan_walk_forward_artifact_without_checkpoint_is_refused(tmp_path):
    """Chemin 6 : artefact orphelin, aucune provenance établissable."""
    plan, _split, root = _execute_ready_campaign(tmp_path)
    orphan = _campaign_dir(root, plan) / "walk_forward" / "folds" / "fold_000"
    orphan.mkdir(parents=True)
    (orphan / "test_result.json").write_text("{}", encoding="utf-8")
    _assert_refused_before_mutation(plan, root, tmp_path, _execute_data_manifest(tmp_path))


def test_g8_crash_window_with_only_empty_dirs_or_tmp_is_not_an_artifact(tmp_path):
    plan, split_plan, root = _execute_ready_campaign(tmp_path)
    ckpt = _campaign_dir(root, plan) / "walk_forward" / ".gate_v_checkpoints_v1"
    ckpt.mkdir(parents=True)
    (ckpt / "manifest.json.123.tmp").write_text("partial", encoding="utf-8")
    shutil.rmtree(ckpt)  # le moteur réel exige un dossier sans manifeste partiel ; ne garder que le vide
    (_campaign_dir(root, plan) / "walk_forward").mkdir(exist_ok=True)
    run_fn, calls = _execute_fake_run(plan, split_plan)
    _execute(plan, root, tmp_path, run_walk_forward_fn=run_fn, resume_walk_forward_fn=_never_called("resume"))
    assert calls  # campagne neuve : la garde ne bloque pas une fenêtre de crash vide


def test_r64_divergent_configuration_is_refused_even_with_current_semantics(tmp_path):
    plan, _split, root, _, dm = _full_campaign(tmp_path)
    cfg = dataclasses.replace(_execute_base_config(plan),
                              score_weights=dataclasses.replace(ScoreWeights(), win_rate=2.0))
    _assert_refused_before_mutation(plan, root, tmp_path, dm, kw={"base_config": cfg})


def test_s2_guard_adds_no_writer_and_no_forbidden_dependency():
    import inspect
    source = inspect.getsource(gvc._require_walk_forward_evidence_provenance)
    assert "save_" not in source and "final_holdout" not in source.lower()


def test_m34_refusal_on_a_running_manifest_is_never_technical_failure(tmp_path):
    """Crash (BaseException) pendant la phase WF : manifeste RUNNING + artefacts présents. Le refus
    de provenance doit rester une précondition — jamais `_mark_technical_failure_if_running`."""
    plan, split_plan, root = _execute_ready_campaign(tmp_path)
    dm = _execute_data_manifest(tmp_path)
    real_fn, _ = _execute_fake_run(plan, split_plan)

    def crashing(*args, **kwargs):
        real_fn(*args, **kwargs)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _execute(plan, root, tmp_path, run_walk_forward_fn=crashing,
                 resume_walk_forward_fn=_never_called("resume"), data_manifest_path=dm)
    running = gvc.load_gate_v_campaign_manifest(_campaign_dir(root, plan) / "manifest.json", plan)
    assert running.running is True
    _legacyize(root, plan)
    _assert_refused_before_mutation(plan, root, tmp_path, dm)


def _checkpoint_only(root, plan):
    cdir = _campaign_dir(root, plan)
    _reset_campaign_manifest(root, plan)
    shutil.rmtree(cdir / "validations")
    for child in (cdir / "walk_forward").iterdir():
        if child.name != ".gate_v_checkpoints_v1":
            shutil.rmtree(child) if child.is_dir() else child.unlink()


def test_r64b_divergent_configuration_on_a_checkpoint_only_campaign_is_refused(tmp_path):
    """Seul le manifeste de capture peut établir la provenance : la comparaison doit porter sur
    toutes ses clés, pas seulement sur la version de sémantique (tue M32)."""
    plan, _split, root, _, dm = _full_campaign(tmp_path)
    _checkpoint_only(root, plan)
    cfg = dataclasses.replace(_execute_base_config(plan),
                              score_weights=dataclasses.replace(ScoreWeights(), win_rate=2.0))
    _assert_refused_before_mutation(plan, root, tmp_path, dm, kw={"base_config": cfg})


def test_r60b_attached_ids_whose_evidence_disappeared_are_refused_before_any_mutation(tmp_path):
    """Chemin 4 : ids rattachés mais preuves effacées — déjà refusé par le chargeur du manifeste
    (précondition `ValueError`), avant la garde de provenance : un id rattaché implique des fichiers
    lisibles — mais pas forcément visibles du balayage, voir le test M33 ci-dessous."""
    plan, _split, root, _, dm = _full_campaign(tmp_path)
    cdir = _campaign_dir(root, plan)
    shutil.rmtree(cdir / "validations")
    shutil.rmtree(cdir / "walk_forward")
    before = _manifest_bytes(root, plan)
    with pytest.raises(ValueError, match="ValidationRun absent"):
        _execute(plan, root, tmp_path, run_walk_forward_fn=_never_called("run"),
                 resume_walk_forward_fn=_never_called("resume"), data_manifest_path=dm)
    assert _manifest_bytes(root, plan) == before


@pytest.mark.parametrize("attached_field", [
    "walk_forward_validation_run_id", "monte_carlo_validation_run_id",
    "parameter_stability_validation_run_ids_by_fold",
])
def test_m33_an_attached_id_is_an_artifact_even_when_the_file_scan_sees_nothing(tmp_path, attached_field):
    """G-8 : un id rattaché au manifeste de campagne vaut artefact INDÉPENDAMMENT du balayage des
    fichiers. Le balayage ne suffit pas : `validations/<id>` en lien symbolique de dossier est lu par
    `load_validation_run` (`is_file()` suit le lien) mais `rglob("*")` (Python 3.13) ne descend pas
    dans un lien sous `**` — sans la branche des ids, une preuve legacy serait réutilisée (tue M33,
    sans exiger le privilège de création de lien absent de certains postes Windows)."""
    plan, *_ = _execute_ready_campaign(tmp_path)
    empty_campaign_dir = tmp_path / "empty_campaign"
    empty_campaign_dir.mkdir()
    value = {"fold-1": "ps-run"} if attached_field.startswith("parameter_stability") else "run-id"
    manifest = dataclasses.replace(gvc.build_gate_v_campaign_manifest(plan), **{attached_field: value})
    assert gvc._campaign_has_reusable_evidence(empty_campaign_dir, manifest) is True
    assert gvc._campaign_has_reusable_evidence(
        empty_campaign_dir, gvc.build_gate_v_campaign_manifest(plan),
    ) is False  # témoin : campagne neuve sans artefact


def test_r58b_persisted_aggregate_without_run_manifest_is_refused(tmp_path):
    """G-8 : persistance Walk-Forward (aggregate.json) sans walk_forward/manifest.json (tue M_S2run)."""
    plan, _split, root, _, dm = _full_campaign(tmp_path)
    cdir = _campaign_dir(root, plan)
    _reset_campaign_manifest(root, plan)
    shutil.rmtree(cdir / "validations")
    (cdir / "walk_forward" / "manifest.json").unlink()
    _assert_refused_before_mutation(plan, root, tmp_path, dm)
