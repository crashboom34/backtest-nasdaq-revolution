"""Aides de test PARTAGÉES pour N-VIDE-2 / N2-b1a (provenance de la fenêtre W). Fixtures SYNTHÉTIQUES uniquement (`tmp_path`) : un plan de campagne V2 RÉEL (pré-enregistrement et
dépôt Git jetable construits par les fabriques historiques, sous `tmp_path`), un `DatasetSplitPlan` réel, aucune donnée de marché, aucun `FINAL_HOLDOUT`, aucun réseau. Les attendus
(identifiants, bornes) sont des littéraux ou des recalculs INDÉPENDANTS du code testé. Ce module n'est pas collecté (nom sans préfixe `test_`)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import gate_v_audit_protocol as ap
from dataset_split import build_dataset_split_plan, build_split_boundary, save_dataset_split_plan
from gate_v_campaign_plan_v2 import build_gate_v_campaign_plan_v2, compute_gate_v_campaign_id_v2, save_gate_v_campaign_plan_v2
from gate_v_preregistration import build_gate_v_preregistration, compute_campaign_protocol_fingerprint
from gate_v_validation_policy import OosPolicyCriterion, WalkForwardPolicyCriterion, build_gate_v_validation_policy, save_gate_v_validation_policy
from research_run import build_research_run
from tests.gate_v_audit_protocol_support import SPLIT, campaign_spec, request_for
from walk_forward import build_walk_forward_specification

SNAPSHOT_ID = "local_csv:sha256:" + "ab" * 32
SPLIT_PLAN_ID = "plan_x"
HOLDOUT = ("2024-06-01T00:00:00+00:00", "2024-09-01T00:00:00+00:00")           # bornes écrites dans le split plan
HOLDOUT_NORMALISED = ("2024-06-01T00:00:00.000000Z", "2024-09-01T00:00:00.000000Z")   # forme normalisée de `normalize_window`, écrite à la main
SPLIT_LABEL, CAMPAIGN_LABEL = "split", "camp"


def _git(args, cwd):
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout


@dataclass
class World:
    plan: object
    split_plan: object


def split_plan(**changes):
    fields = dict(split_plan_id=SPLIT_PLAN_ID, dataset_snapshot_id=SNAPSHOT_ID, train=build_split_boundary("2020-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00"),
                  final_holdout=build_split_boundary(*HOLDOUT), validation=build_split_boundary("2024-01-01T00:00:00+00:00", "2024-06-01T00:00:00+00:00"))
    fields.update(changes)
    return build_dataset_split_plan(**fields)


def build_world(base: Path) -> World:
    """Plan V2 RÉEL, construit comme en production : dépôt Git jetable, politique validée, pré-enregistrement, puis plan (aucun accès à un dépôt du projet)."""
    repo = base / f"repo_{uuid.uuid4().hex[:8]}"
    repo.mkdir(parents=True)
    _git(["init"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    policy = build_gate_v_validation_policy("pol_test", {"oos": (OosPolicyCriterion(metric="net_ret_pct", operator=">", threshold=0.0),),
                                                          "walk_forward": (WalkForwardPolicyCriterion(metric="oos_net_return_pct", operator=">", threshold=0.0),)})
    policy_path = repo / "validation_policies" / "pol_test.json"
    policy_path.parent.mkdir()
    save_gate_v_validation_policy(policy_path, policy)
    _git(["add", "validation_policies"], repo)
    _git(["commit", "-m", "add policy"], repo)
    run = build_research_run(research_run_id="run_x", experiment_id="exp_x", dataset_snapshot_id=SNAPSHOT_ID, git_sha=None)
    split = split_plan()
    protocol = dict(strategy_name="perfect_revolution_v1", base_params={"n_neighbors": 5}, search_mode="single_var", search_space_hash="a" * 12, budget_per_fold=10,
                    walk_forward_specification=build_walk_forward_specification(base_params={"n_neighbors": 5}, geometry="rolling", train_period="P1M", test_period="P1M",
                                                                                step_period="P1M"), readiness_spec=None)
    prereg = build_gate_v_preregistration(research_run=run, split_plan=split, policy=policy, policy_path=policy_path, assessment_semantics_version="gate_v_assessment_v1",
                                          repo_dir=repo, **protocol)
    plan = build_gate_v_campaign_plan_v2(preregistration=prereg, research_run=run, split_plan=split, policy=policy, policy_path=policy_path, repo_dir=repo, **protocol)
    return World(plan, split)


def forge_plan(plan, **changes):
    """Plan AUTO-COHÉRENT (empreinte de protocole et `campaign_id` recalculés honnêtement) mais aux champs modifiés : passe le chargeur, doit être refusé par l'appariement."""
    forged = dataclasses.replace(plan, **changes)
    fingerprint = compute_campaign_protocol_fingerprint(
        research_run_id=forged.research_run_id, research_run_content_hash=forged.research_run_content_hash, dataset_snapshot_id=forged.dataset_snapshot_id,
        split_plan_id=forged.split_plan_id, split_plan_fingerprint=forged.split_plan_fingerprint, strategy_name=forged.strategy_name, base_params=forged.base_params,
        search_mode=forged.search_mode, search_space_hash=forged.search_space_hash, budget_per_fold=forged.budget_per_fold,
        walk_forward_specification=forged.walk_forward_specification, readiness_spec=forged.readiness_spec, expected_fold_ids=forged.expected_fold_ids,
        expected_fold_definitions_hash=forged.expected_fold_definitions_hash, validation_zone_hash=forged.validation_zone_hash,
        walk_forward_spec_semantics_version=forged.walk_forward_spec_semantics_version, monte_carlo_semantics_version=forged.monte_carlo_semantics_version,
        parameter_stability_semantics_version=forged.parameter_stability_semantics_version, gate_v_validation_policy_id=forged.gate_v_validation_policy_id,
        policy_content_hash=forged.policy_content_hash, assessment_semantics_version=forged.assessment_semantics_version)
    forged = dataclasses.replace(forged, campaign_protocol_fingerprint=fingerprint)
    campaign_id = compute_gate_v_campaign_id_v2(campaign_plan_semantics_version=forged.campaign_plan_semantics_version, preregistration_id=forged.preregistration_id,
                                                campaign_protocol_fingerprint=fingerprint)
    return dataclasses.replace(forged, campaign_id=campaign_id)


def independent_fingerprint(split) -> str:
    """Recalcul INDÉPENDANT de l'empreinte du split plan, à partir de ses champs écrits à la main (jamais la fonction testée)."""
    def boundary(b):
        return None if b is None else {"start": b.start, "end": b.end}
    record = {"split_plan_id": split.split_plan_id, "dataset_snapshot_id": split.dataset_snapshot_id, "train": boundary(split.train), "final_holdout": boundary(split.final_holdout),
              "validation": boundary(split.validation), "discovery_oos": boundary(split.discovery_oos), "created_at": split.created_at}
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass
class Layout:
    campaign_dir: Path
    split_dir: Path
    campaign_id: str

    @property
    def plan_file(self) -> Path:
        return self.campaign_dir / "plan.json"

    @property
    def split_file(self) -> Path:
        return self.split_dir / "split_plan.json"


def lay_out(base: Path, plan, split) -> Layout:
    """Écrit `<base>/<campaign_id>/plan.json` et `<base>/splits/<split_plan_id>/split_plan.json` avec les écrivains historiques."""
    plan_path = save_gate_v_campaign_plan_v2(base, plan)
    split_dir = base / "splits" / split.split_plan_id
    split_dir.mkdir(parents=True)
    save_dataset_split_plan(split_dir / "split_plan.json", split)
    return Layout(plan_path.parent, split_dir, plan.campaign_id)


def window_source(**changes) -> ap.WindowSource:
    fields = dict(split_plan_root_label=SPLIT_LABEL)
    fields.update(changes)
    return ap.WindowSource(**fields)


def split_spec(layout: Layout, **changes) -> ap.AuditRootSpec:
    fields = dict(label=SPLIT_LABEL, path=str(layout.split_dir), layout=SPLIT, expected_name=None, may_be_empty=False)
    fields.update(changes)
    return ap.AuditRootSpec(**fields)


def derived_request(layout: Layout, *, source="default", window=HOLDOUT, **changes) -> ap.AuditRequest:
    """Requête N2-b1a nominale : fenêtre de l'opérateur = bornes du split plan, `window_source` configuré."""
    fields = dict(own=layout.campaign_id, window_start_utc=window[0], window_end_utc=window[1])
    chosen = window_source() if isinstance(source, str) and source == "default" else source
    if chosen is not None:                         # `None` : champ OMIS, comme une requête du mode N2-a historique
        fields["window_source"] = chosen
    fields.update(changes)
    return request_for(campaign_spec(layout.campaign_dir, label=CAMPAIGN_LABEL), split_spec(layout), **fields)
