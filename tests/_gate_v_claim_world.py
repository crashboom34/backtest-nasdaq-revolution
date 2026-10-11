"""
tests/_gate_v_claim_world.py — fabrique de test (PAS un module pytest) d'une campagne Gate V V2 PERSISTÉE.

Sert les tests de la Slice E2 (`gate_v_final_holdout_claim_acquisition`) et ses workers multiprocessus. Construit,
sous un dossier fourni par l'appelant et sans aucune donnée de marché, la disposition canonique de l'ADR 0025
(Décision 16 / 22.5) :

    <root>/gate_v/preregistrations/<scope_key>.json
    <root>/gate_v/campaigns/<campaign_id>/{plan.json, manifest.json, validations/...}
    <root>/research_run.json, <root>/dataset_splits/split_plan.json
    <root>/repo/validation_policies/pol_e2.json   (dépôt Git local hermétique, policy committée)

Les preuves WF/MC/PS synthétiques reprennent volontairement celles des tests du Manifest V2 (copie : ce module
n'importe aucun module de test) ; `assert_gate_v_pre_holdout_evidence_complete` confirme dans les tests qu'elles
sont COMPLÈTES. Aucun accès FINAL_HOLDOUT, aucun Claim créé ici.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_v_campaign_manifest_v2 as m2
from dataset_split import build_dataset_split_plan, build_split_boundary, save_dataset_split_plan
from gate_v_campaign_plan_v2 import build_gate_v_campaign_plan_v2, save_gate_v_campaign_plan_v2
from gate_v_evidence_completeness_v2 import gate_v_v2_validation_run_id
from gate_v_preregistration import build_gate_v_preregistration, save_gate_v_preregistration
from gate_v_validation_policy import (
    OosPolicyCriterion,
    WalkForwardPolicyCriterion,
    build_gate_v_validation_policy,
    save_gate_v_validation_policy,
)
from research_run import build_research_run, save_research_run
from validation_run import (
    VALIDATION_TYPE_MONTE_CARLO,
    VALIDATION_TYPE_PARAMETER_STABILITY,
    VALIDATION_TYPE_WALK_FORWARD,
    FoldResult,
    FoldSelection,
    MonteCarloEvidence,
    ParameterStabilityEvidence,
    PercentileDistributionSummary,
    WalkForwardEvidence,
    build_monte_carlo_specification,
    build_parameter_stability_specification,
    build_validation_run,
    save_validation_run,
)
from walk_forward import build_aggregate_result, build_walk_forward_specification, compute_fold_definitions

SNAPSHOT_ID = "synthetic_csv:sha256:" + "ab" * 32
STRATEGY = "Synthetic Strategy"
RESEARCH_RUN_ID = "research_synthetic_001"
SPLIT_PLAN_ID = "synthetic_split"
PROTOCOL = dict(base_params={"lookback": 12}, search_mode="grid", search_space_hash="a" * 12)
POLICY_ID = "pol_e2"
CLAIM_FILE = "final_holdout_access_claim.json"
LOCK_FILE = "manifest.update.lock"
SENTINEL_FILE = "technical_failure.json"
_COMPLETED_AT = "2025-07-01T00:00:00+00:00"
_SUMMARY = PercentileDistributionSummary(0.1, 0.2, 0.3, 0.4, 0.5)


def run_git(args, cwd):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    result = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull, *args],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout


@dataclass(frozen=True)
class World:
    """Une campagne persistée et ses sources. Les objets (plan, preuves...) sont indépendants du dossier ;
    seuls les chemins dépendent de `root` (voir `at`)."""

    root: Path
    plan: object
    preregistration: object
    research_run: object
    split: object
    policy: object
    proofs: dict

    @property
    def gate_v_dir(self) -> Path:
        return self.root / "gate_v"

    @property
    def campaign_dir(self) -> Path:
        return self.gate_v_dir / "campaigns" / self.plan.campaign_id

    @property
    def preregistration_path(self) -> Path:
        return self.gate_v_dir / "preregistrations" / f"{self.preregistration.scope_key}.json"

    @property
    def research_run_path(self) -> Path:
        return self.root / "research_run.json"

    @property
    def split_plan_path(self) -> Path:
        return self.root / "dataset_splits" / "split_plan.json"

    @property
    def repo_dir(self) -> Path:
        return self.root / "repo"

    @property
    def policy_path(self) -> Path:
        return self.repo_dir / "validation_policies" / f"{POLICY_ID}.json"

    @property
    def claim_path(self) -> Path:
        return self.campaign_dir / CLAIM_FILE

    def sources(self) -> dict:
        """Les arguments par mot-clé d'E2 (hors `campaign_dir`), tous des chemins."""
        return dict(
            preregistration_path=self.preregistration_path, research_run_path=self.research_run_path,
            split_plan_path=self.split_plan_path, policy_path=self.policy_path, repo_dir=self.repo_dir,
        )

    def config(self) -> dict:
        """Version JSON-sérialisable pour un worker multiprocessus."""
        return {"campaign_dir": str(self.campaign_dir), **{k: str(v) for k, v in self.sources().items()}}

    def at(self, new_root: Path) -> "World":
        return dataclasses.replace(self, root=Path(new_root))

    def clone_into(self, new_root: Path) -> "World":
        """Copie physique complète (dépôt Git compris) : chaque test mute SA copie, jamais la source."""
        shutil.copytree(self.root, new_root)
        return self.at(new_root)


def ensure_long_paths(root: Path) -> None:
    """Prérequis de déploiement (ADR 0025 §21.12 n° 30) : les chemins canoniques des preuves dépassent MAX_PATH."""
    if sys.platform != "win32":
        return
    probe = root / ("long_path_probe_" + "x" * 120) / ("y" * 120) / "probe.txt"
    try:
        probe.parent.mkdir(parents=True)
        probe.write_text("ok", encoding="utf-8")
    except OSError as error:
        raise RuntimeError(f"Chemins longs Windows requis (LongPathsEnabled=1) : {error}") from error
    probe.unlink()
    probe.parent.rmdir()
    probe.parent.parent.rmdir()


def _split_plan():
    return build_dataset_split_plan(
        split_plan_id=SPLIT_PLAN_ID,
        dataset_snapshot_id=SNAPSHOT_ID,
        train=build_split_boundary("2020-01-01T00:00:00+00:00", "2021-07-01T00:00:00+00:00"),
        validation=build_split_boundary("2021-07-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
        final_holdout=build_split_boundary("2025-01-01T00:00:00+00:00", "2025-07-01T00:00:00+00:00"),
        created_at="2025-01-01T00:00:00+00:00",
    )


def _ids(plan):
    return dict(
        wf=gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_WALK_FORWARD),
        mc=gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_MONTE_CARLO),
        ps={
            fold: gate_v_v2_validation_run_id(plan, VALIDATION_TYPE_PARAMETER_STABILITY, fold_id=fold)
            for fold in plan.expected_fold_ids
        },
    )


def synthetic_proofs(plan, split):
    """WF + MC + une PS par fold attendu, COMPLÈTES, sans aucun moteur (copie des tests du Manifest V2)."""
    definitions = compute_fold_definitions(split.validation, plan.walk_forward_specification, plan.readiness_spec)
    results = tuple(
        FoldResult(
            fold_id=definition.fold_id, definition=definition,
            selection=FoldSelection(
                fold_id=definition.fold_id, selected_params={"lookback": 12 + index},
                selected_params_hash="synthetic_hash", score_train=1.0 + index, rank_in_train=1,
                train_candidates_evaluated=2 + index, train_candidates_unique=2 + index,
                train_candidates_eligible=2 + index, search_space_hash=plan.search_space_hash,
                algorithm=plan.search_mode, fold_seed=None,
            ),
            n_trades=0, net_ret_pct=0.0, max_dd_pct=None, profit_factor=None, win_rate=None, expectancy=None,
            score_test=0.0, zero_trade_oos=True, forced_closes=0, coverage_bars=1,
        ) for index, definition in enumerate(definitions)
    )
    ids = _ids(plan)
    common = dict(
        research_run_id=plan.research_run_id, split_plan_id=plan.split_plan_id,
        dataset_snapshot_id=plan.dataset_snapshot_id, strategy_name=plan.strategy_name,
        strategy_params=dict(plan.base_params), completed_at=_COMPLETED_AT,
    )
    proofs = {
        ids["wf"]: build_validation_run(
            validation_run_id=ids["wf"], validation_type=VALIDATION_TYPE_WALK_FORWARD,
            specification=plan.walk_forward_specification,
            evidence=WalkForwardEvidence(results, build_aggregate_result(results), "completed", "INCONCLUSIVE", ()),
            **common),
        ids["mc"]: build_validation_run(
            validation_run_id=ids["mc"], validation_type=VALIDATION_TYPE_MONTE_CARLO,
            specification=build_monte_carlo_specification(ids["wf"], True),
            evidence=MonteCarloEvidence(
                n_input_trades=0, zero_trade_input=True, observed_net_ret_pct=None,
                observed_max_dd_trade_close_basis_pct=None, observed_lag1_autocorrelation=None,
                observed_longest_losing_streak=None, sequence_risk_max_dd_trade_close_basis_pct=None,
                sequence_risk_longest_losing_streak=None, sampling_uncertainty_net_ret_pct=None,
                sampling_uncertainty_max_dd_trade_close_basis_pct=None, execution_status="completed",
                scientific_verdict="INCONCLUSIVE", verdict_reasons=()),
            **common),
    }
    for index, fold_id in enumerate(plan.expected_fold_ids):
        proofs[ids["ps"][fold_id]] = build_validation_run(
            validation_run_id=ids["ps"][fold_id], validation_type=VALIDATION_TYPE_PARAMETER_STABILITY,
            specification=build_parameter_stability_specification(
                ids["wf"], plan.search_mode, True, source_fold_id=fold_id),
            evidence=ParameterStabilityEvidence(
                n_candidates_total=2 + index, zero_candidates_input=False, search_mode=plan.search_mode,
                neighborhood_applicability="local_neighborhood_available", best_score=1.0 + index,
                best_params={"lookback": 12 + index}, sensitivity={"lookback": 0.0},
                sensitivity_sample_size_by_param={"lookback": 2}, n_neighbors_total_by_param={"lookback": 1},
                n_neighbors_rejected_by_param={"lookback": 0}, degradation_by_param={"lookback": _SUMMARY},
                degradation_points_by_param={"lookback": _SUMMARY}, n_hamming_le_2_total=1,
                n_hamming_le_2_rejected=0, degradation_hamming_le_2=_SUMMARY, execution_status="completed",
                scientific_verdict="INCONCLUSIVE", verdict_reasons=()),
            **common)
    return proofs


def build_world(root: Path, *, attach_all_parameter_stability: bool = True) -> World:
    """Crée la campagne persistée sous `root`. Avec `attach_all_parameter_stability=False`, le dernier fold n'a ni
    preuve rattachée : la campagne est alors honnêtement `EVIDENCE_INCOMPLETE`."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    ensure_long_paths(root)

    repo_dir = root / "repo"
    (repo_dir / "validation_policies").mkdir(parents=True)
    run_git(["init"], repo_dir)
    run_git(["config", "user.email", "test@example.com"], repo_dir)
    run_git(["config", "user.name", "Test"], repo_dir)
    policy = build_gate_v_validation_policy(
        POLICY_ID,
        {
            "oos": (OosPolicyCriterion(metric="net_ret_pct", operator=">", threshold=0.0),),
            "walk_forward": (WalkForwardPolicyCriterion(metric="oos_net_return_pct", operator=">", threshold=0.0),),
        },
    )
    policy_path = repo_dir / "validation_policies" / f"{POLICY_ID}.json"
    save_gate_v_validation_policy(policy_path, policy)
    run_git(["add", "validation_policies"], repo_dir)
    run_git(["commit", "-m", f"add policy {uuid.uuid4().hex}"], repo_dir)

    research_run = build_research_run(
        research_run_id=RESEARCH_RUN_ID, experiment_id="exp_e2", dataset_snapshot_id=SNAPSHOT_ID, git_sha=None,
    )
    split = _split_plan()
    spec = build_walk_forward_specification(
        base_params=dict(PROTOCOL["base_params"]), geometry="rolling", train_period="P24M",
        test_period="P6M", step_period="P6M",
    )
    protocol = dict(
        strategy_name=STRATEGY, walk_forward_specification=spec, readiness_spec=None, budget_per_fold=20, **PROTOCOL,
    )
    preregistration = build_gate_v_preregistration(
        research_run=research_run, split_plan=split, policy=policy, policy_path=policy_path,
        assessment_semantics_version="gate_v_assessment_v1", repo_dir=repo_dir, **protocol,
    )
    plan = build_gate_v_campaign_plan_v2(
        preregistration=preregistration, research_run=research_run, split_plan=split, policy=policy,
        policy_path=policy_path, repo_dir=repo_dir, **protocol,
    )
    proofs = synthetic_proofs(plan, split)
    world = World(root, plan, preregistration, research_run, split, policy, proofs)

    save_research_run(world.research_run_path, research_run)
    save_dataset_split_plan(world.split_plan_path, split)
    save_gate_v_preregistration(world.preregistration_path, preregistration)
    save_gate_v_campaign_plan_v2(world.gate_v_dir / "campaigns", plan)
    campaign_dir = world.campaign_dir
    m2.create_gate_v_campaign_manifest_v2(plan, campaign_dir)

    def update(command):
        revision = m2.load_gate_v_campaign_manifest_v2(plan, campaign_dir).manifest_revision
        return m2.update_gate_v_campaign_manifest_v2(plan, campaign_dir, command, expected_revision=revision)

    update(m2.Start())
    ids = _ids(plan)
    folds = plan.expected_fold_ids if attach_all_parameter_stability else plan.expected_fold_ids[:-1]
    wanted = [ids["wf"], ids["mc"], *(ids["ps"][fold] for fold in folds)]
    for run_id in wanted:
        save_validation_run(campaign_dir / "validations" / run_id / "validation_run.json", proofs[run_id])
    update(m2.AttachWalkForward(ids["wf"]))
    update(m2.AttachMonteCarlo(ids["mc"]))
    for fold in folds:
        update(m2.AttachParameterStability(fold, ids["ps"][fold]))
    return world


def snapshot(directory: Path, *, skip_git: bool = True) -> dict:
    """Instantané octet par octet des fichiers sous `directory` (le contenu de `.git` est exclu par défaut : les
    commandes Git en lecture y touchent des métadonnées) : preuve qu'une opération n'a rien écrit."""
    result = {}
    for path in sorted(Path(directory).rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        if skip_git and (".git/" in "/" + relative):
            continue
        result[relative] = path.read_bytes()
    return result
