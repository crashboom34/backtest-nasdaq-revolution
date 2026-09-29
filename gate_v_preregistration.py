"""
gate_v_preregistration.py — GateVPreRegistration (AF-V-07 Slice B, ADR 0025 Décision 6/7/8).

Liaison immuable ResearchRun + protocole complet + policy Gate V, AVANT toute exécution
scientifique et AVANT tout FINAL_HOLDOUT. Fail-closed sur la provenance Git de la policy
(Décision 6) : les octets utilisés viennent toujours du blob Git committé (`git show`), jamais du
working tree. `preregistration_id`/`preregistration_content_hash` incluent directement
`research_run_content_hash` et `policy_git_sha` (correctif ADR 0025, commit `0f0df82`).

Module additif, ne modifie aucun comportement existant. N'importe PAS `gate_v_campaign.py`
(orchestration V1, non touchée) — réutilise uniquement les primitives pures/leaf déjà établies :
`dataset_split.py` (`DatasetSplitPlan`, `dataset_split_plan_fingerprint`),
`walk_forward.py` (`WalkForwardSpecification`, `compute_fold_definitions`, pures — aucune
exécution), `research_run.py` (`ResearchRun`), `validation_run.py` (constantes de version
sémantique Monte-Carlo/Parameter Stability), `gate_v_validation_policy.py` (Slice A),
`atomic_json_store.py`.

Scope Slice B (STRICT) : `GateVPreRegistration` + vérification Git fail-closed + fonction pure
canonique `compute_campaign_protocol_fingerprint()` (destinée à être réutilisée par un futur
`GateVCampaignPlan V2`, non implémenté ici). AUCUN `FinalHoldoutAccessClaim`, AUCUN
`ValidationAssessment`, AUCUN `GateVPolicyAssessment`, AUCUN accès `FINAL_HOLDOUT`, AUCUNE
campagne réelle — réservés aux tranches suivantes.

**Duplication documentée et volontaire** : `_fold_definitions_hash()`/le hash de
`validation_zone` ci-dessous répliquent EXACTEMENT la même formule que les fonctions privées
homonymes de `gate_v_campaign.py` (non importables, privées, et ce module ne doit pas dépendre de
l'orchestration V1). Un futur `GateVCampaignPlan V2` devra recalculer cette MÊME formule et exiger
une égalité stricte (ADR 0025 Décision 7) — voir revue Slice B pour la discussion de cette dette
architecturale connue.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Tuple, Union

from atomic_json_store import load_json_tolerant, save_exclusive, validate_portable_identifier
from dataset_split import DatasetSplitPlan, dataset_split_plan_fingerprint
from gate_v_validation_policy import (
    GateVValidationPolicyVersion,
    gate_v_validation_policy_from_dict,
    policy_content_hash as compute_policy_content_hash,
)
from research_run import ResearchRun
from strategy_contracts import DailyStateReadiness
from validation_run import MONTE_CARLO_SEMANTICS_VERSION, PARAMETER_STABILITY_SEMANTICS_VERSION
from walk_forward import WalkForwardSpecification, compute_fold_definitions

GATE_V_PREREGISTRATION_SEMANTICS_VERSION = "gate_v_preregistration_v1"
CAMPAIGN_PLAN_SEMANTICS_VERSION_V2 = "gate_v_campaign_plan_v2"


class GitProvenanceError(ValueError):
    """Provenance Git de la policy invalide ou non vérifiable — échec fermé (ADR 0025 Décision 6)."""


def _canonical_json(record) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def research_run_content_hash(research_run: ResearchRun) -> str:
    """Hash sémantique canonique du contenu réel du `ResearchRun` (ADR 0025 Décision 7) — même
    `research_run_id` avec un contenu différent produit un hash différent."""
    return _sha256_hex(_canonical_json(asdict(research_run)))


def compute_scope_key(
    research_run_id: str, dataset_snapshot_id: str, split_plan_id: str, strategy_name: str
) -> str:
    """Scope scientifique — ne dépend jamais de la policy (ADR 0025 Décision 8)."""
    return _sha256_hex(_canonical_json({
        "research_run_id": research_run_id,
        "dataset_snapshot_id": dataset_snapshot_id,
        "split_plan_id": split_plan_id,
        "strategy_name": strategy_name,
    }))


def compute_campaign_protocol_fingerprint(
    *,
    research_run_id: str,
    research_run_content_hash: str,
    dataset_snapshot_id: str,
    split_plan_id: str,
    split_plan_fingerprint: str,
    strategy_name: str,
    base_params: Mapping,
    search_mode: str,
    search_space_hash: str,
    budget_per_fold: int,
    walk_forward_specification: WalkForwardSpecification,
    readiness_spec: Optional[DailyStateReadiness],
    expected_fold_ids: Tuple[str, ...],
    expected_fold_definitions_hash: str,
    validation_zone_hash: str,
    walk_forward_spec_semantics_version: str,
    monte_carlo_semantics_version: str,
    parameter_stability_semantics_version: str,
    gate_v_validation_policy_id: str,
    policy_content_hash: str,
    assessment_semantics_version: str,
) -> str:
    """Fonction canonique UNIQUE (ADR 0025 Décision 7) — aucune evidence `FINAL_HOLDOUT` en entrée.
    Destinée à être réutilisée telle quelle par un futur `GateVCampaignPlan V2`, jamais
    réimplémentée séparément."""
    record = {
        "research_run_id": research_run_id,
        "research_run_content_hash": research_run_content_hash,
        "dataset_snapshot_id": dataset_snapshot_id,
        "split_plan_id": split_plan_id,
        "split_plan_fingerprint": split_plan_fingerprint,
        "strategy_name": strategy_name,
        "base_params": base_params,
        "search_mode": search_mode,
        "search_space_hash": search_space_hash,
        "budget_per_fold": budget_per_fold,
        "walk_forward_specification": {
            "geometry": walk_forward_specification.geometry,
            "train_period": walk_forward_specification.train_period,
            "test_period": walk_forward_specification.test_period,
            "step_period": walk_forward_specification.step_period,
            "allow_partial_last_fold": walk_forward_specification.allow_partial_last_fold,
            "position_transition_policy": walk_forward_specification.position_transition_policy,
            "master_seed": walk_forward_specification.master_seed,
        },
        "readiness_spec": asdict(readiness_spec) if readiness_spec is not None else None,
        "expected_fold_ids": list(expected_fold_ids),
        "expected_fold_definitions_hash": expected_fold_definitions_hash,
        "validation_zone_hash": validation_zone_hash,
        "walk_forward_spec_semantics_version": walk_forward_spec_semantics_version,
        "monte_carlo_semantics_version": monte_carlo_semantics_version,
        "parameter_stability_semantics_version": parameter_stability_semantics_version,
        "gate_v_validation_policy_id": gate_v_validation_policy_id,
        "policy_content_hash": policy_content_hash,
        "assessment_semantics_version": assessment_semantics_version,
        "campaign_plan_semantics_version": CAMPAIGN_PLAN_SEMANTICS_VERSION_V2,
    }
    return _sha256_hex(_canonical_json(record))


def _preregistration_id_fields(
    *,
    scope_key, campaign_protocol_fingerprint, research_run_id, research_run_content_hash,
    dataset_snapshot_id, split_plan_id, strategy_name, gate_v_validation_policy_id,
    policy_content_hash, policy_git_sha, assessment_semantics_version,
    preregistration_semantics_version,
) -> dict:
    return {
        "scope_key": scope_key,
        "campaign_protocol_fingerprint": campaign_protocol_fingerprint,
        "research_run_id": research_run_id,
        "research_run_content_hash": research_run_content_hash,
        "dataset_snapshot_id": dataset_snapshot_id,
        "split_plan_id": split_plan_id,
        "strategy_name": strategy_name,
        "gate_v_validation_policy_id": gate_v_validation_policy_id,
        "policy_content_hash": policy_content_hash,
        "policy_git_sha": policy_git_sha,
        "assessment_semantics_version": assessment_semantics_version,
        "preregistration_semantics_version": preregistration_semantics_version,
    }


def compute_preregistration_id(**kwargs) -> str:
    """ADR 0025 Décision 8 (corrigée, commit `0f0df82`) : inclut directement
    `research_run_content_hash` et `policy_git_sha`. `created_at` toujours exclu."""
    return _sha256_hex(_canonical_json(_preregistration_id_fields(**kwargs)))


def compute_preregistration_content_hash(*, preregistration_id: str, **kwargs) -> str:
    """S'exclut lui-même de sa préimage. `created_at` toujours exclu."""
    record = _preregistration_id_fields(**kwargs)
    record["preregistration_id"] = preregistration_id
    return _sha256_hex(_canonical_json(record))


@dataclass(frozen=True)
class GateVPreRegistration:
    """Artefact runtime portable, immuable — voir ADR 0025 Décision 8. PAS source-contrôlé
    (contrairement à `GateVValidationPolicyVersion`, Slice A)."""

    scope_key: str
    preregistration_id: str
    preregistration_content_hash: str
    campaign_protocol_fingerprint: str
    research_run_id: str
    research_run_content_hash: str
    dataset_snapshot_id: str
    split_plan_id: str
    strategy_name: str
    gate_v_validation_policy_id: str
    policy_content_hash: str
    policy_git_sha: str
    assessment_semantics_version: str
    preregistration_semantics_version: str
    created_at: str


def _run_git(args, cwd) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, check=False,
        )
    except OSError as exc:
        raise GitProvenanceError(f"git introuvable ou inexécutable : {exc}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip() if result.stderr else ""
        raise GitProvenanceError(f"git {' '.join(args)} a échoué : {stderr}")
    return result.stdout


def _resolve_policy_git_sha(policy_git_sha: str, repo_dir: Union[str, Path]) -> str:
    if policy_git_sha != "auto":
        if not isinstance(policy_git_sha, str) or not policy_git_sha.strip():
            raise GitProvenanceError("policy_git_sha explicite doit être une chaîne non vide.")
        return policy_git_sha
    return _run_git(["rev-parse", "HEAD"], cwd=repo_dir).decode("utf-8").strip()


def verify_policy_git_provenance(
    *,
    policy_path: Union[str, Path],
    validation_policy_id: str,
    expected_policy_content_hash: str,
    policy_git_sha: str,
    repo_dir: Optional[Union[str, Path]] = None,
) -> None:
    """ADR 0025 Décision 6, fail-closed. Les octets de vérification proviennent EXCLUSIVEMENT du
    blob Git committé (`git show <sha>:<path>`) — le contenu du working tree n'est jamais lu comme
    source de vérité (`policy_path.is_file()` sert uniquement à vérifier l'existence locale)."""
    policy_path = Path(policy_path)
    resolved_repo_dir = Path(repo_dir) if repo_dir is not None else policy_path.parent
    if not policy_path.is_file():
        raise GitProvenanceError(f"Fichier de policy introuvable localement : {policy_path}")
    if not isinstance(policy_git_sha, str) or not policy_git_sha.strip():
        raise GitProvenanceError("policy_git_sha est obligatoire (non optionnel, ADR 0025 Décision 6).")

    toplevel_raw = _run_git(["rev-parse", "--show-toplevel"], cwd=resolved_repo_dir)
    toplevel = Path(toplevel_raw.decode("utf-8").strip()).resolve()
    try:
        rel_path = policy_path.resolve().relative_to(toplevel)
    except ValueError as exc:
        raise GitProvenanceError(
            f"{policy_path} n'est pas dans le dépôt Git résolu ({toplevel})."
        ) from exc
    rel_path_str = rel_path.as_posix()

    _run_git(["ls-files", "--error-unmatch", rel_path_str], cwd=toplevel)  # raises if untracked

    # ADR 0025 Décision 6 : policy_git_sha DOIT être le HEAD courant au moment du
    # préenregistrement -- pas seulement un commit quelconque dont le blob correspond encore.
    # `rev-parse X^{commit}` résout X (court ou long) vers son identité de commit canonique et
    # échoue si X ne désigne aucun commit -- jamais de comparaison ambiguë SHA court/long.
    head_sha = _run_git(["rev-parse", "HEAD^{commit}"], cwd=toplevel).decode("utf-8").strip()
    try:
        resolved_sha = _run_git(["rev-parse", f"{policy_git_sha}^{{commit}}"], cwd=toplevel).decode("utf-8").strip()
    except GitProvenanceError as exc:
        raise GitProvenanceError(
            f"policy_git_sha ne résout à aucun commit du dépôt : {policy_git_sha!r} ({exc})"
        ) from exc
    if resolved_sha != head_sha:
        raise GitProvenanceError(
            f"policy_git_sha doit être le HEAD courant du dépôt (ADR 0025 Décision 6) : "
            f"HEAD={head_sha}, fourni={policy_git_sha!r} (résolu={resolved_sha})"
        )

    committed_bytes = _run_git(["show", f"{policy_git_sha}:{rel_path_str}"], cwd=toplevel)
    try:
        committed_data = json.loads(committed_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GitProvenanceError(
            f"Contenu Git committé invalide (JSON) pour {rel_path_str}@{policy_git_sha} : {exc}"
        ) from exc
    try:
        committed_policy = gate_v_validation_policy_from_dict(committed_data)
    except ValueError as exc:
        raise GitProvenanceError(f"Policy committée malformée : {exc}") from exc

    if committed_policy.validation_policy_id != validation_policy_id:
        raise GitProvenanceError(
            f"policy_id incohérent : attendu {validation_policy_id!r}, "
            f"committé {committed_policy.validation_policy_id!r}"
        )
    actual_hash = compute_policy_content_hash(committed_policy)
    if actual_hash != expected_policy_content_hash:
        raise GitProvenanceError(
            f"policy_content_hash incohérent avec le blob Git committé : "
            f"attendu {expected_policy_content_hash}, calculé {actual_hash}"
        )


def _fold_definitions_hash(fold_definitions) -> str:
    payload = [dataclasses.asdict(fold) for fold in fold_definitions]
    return _sha256_hex(_canonical_json(payload))


def build_gate_v_preregistration(
    *,
    research_run: ResearchRun,
    split_plan: DatasetSplitPlan,
    strategy_name: str,
    base_params: Mapping,
    search_mode: str,
    search_space_hash: str,
    budget_per_fold: int,
    walk_forward_specification: WalkForwardSpecification,
    readiness_spec: Optional[DailyStateReadiness],
    policy: GateVValidationPolicyVersion,
    policy_path: Union[str, Path],
    assessment_semantics_version: str,
    policy_git_sha: str = "auto",
    repo_dir: Optional[Union[str, Path]] = None,
    created_at: Optional[str] = None,
) -> GateVPreRegistration:
    """Construit un `GateVPreRegistration` — AVANT toute exécution WF/MC/PS et AVANT tout
    `FINAL_HOLDOUT`. Refuse fail-closed si la provenance Git de la policy ne vérifie pas."""
    if not isinstance(strategy_name, str) or not strategy_name.strip():
        raise ValueError("strategy_name est obligatoire.")
    if research_run.dataset_snapshot_id != split_plan.dataset_snapshot_id:
        raise ValueError("research_run.dataset_snapshot_id ne correspond pas au split_plan référencé.")
    if split_plan.validation is None:
        raise ValueError("Le DatasetSplitPlan doit contenir une zone validation pour Walk-Forward.")

    resolved_repo_dir = Path(repo_dir) if repo_dir is not None else Path(policy_path).parent
    resolved_git_sha = _resolve_policy_git_sha(policy_git_sha, resolved_repo_dir)
    policy_hash = compute_policy_content_hash(policy)
    verify_policy_git_provenance(
        policy_path=policy_path,
        validation_policy_id=policy.validation_policy_id,
        expected_policy_content_hash=policy_hash,
        policy_git_sha=resolved_git_sha,
        repo_dir=resolved_repo_dir,
    )

    fold_definitions = compute_fold_definitions(split_plan.validation, walk_forward_specification, readiness_spec)
    expected_fold_ids = tuple(fold.fold_id for fold in fold_definitions)
    expected_fold_definitions_hash = _fold_definitions_hash(fold_definitions)
    validation_zone_hash = _sha256_hex(_canonical_json(asdict(split_plan.validation)))
    rr_hash = research_run_content_hash(research_run)

    protocol_fp = compute_campaign_protocol_fingerprint(
        research_run_id=research_run.research_run_id,
        research_run_content_hash=rr_hash,
        dataset_snapshot_id=research_run.dataset_snapshot_id,
        split_plan_id=split_plan.split_plan_id,
        split_plan_fingerprint=dataset_split_plan_fingerprint(split_plan),
        strategy_name=strategy_name,
        base_params=base_params,
        search_mode=search_mode,
        search_space_hash=search_space_hash,
        budget_per_fold=budget_per_fold,
        walk_forward_specification=walk_forward_specification,
        readiness_spec=readiness_spec,
        expected_fold_ids=expected_fold_ids,
        expected_fold_definitions_hash=expected_fold_definitions_hash,
        validation_zone_hash=validation_zone_hash,
        walk_forward_spec_semantics_version=walk_forward_specification.walk_forward_semantics_version,
        monte_carlo_semantics_version=MONTE_CARLO_SEMANTICS_VERSION,
        parameter_stability_semantics_version=PARAMETER_STABILITY_SEMANTICS_VERSION,
        gate_v_validation_policy_id=policy.validation_policy_id,
        policy_content_hash=policy_hash,
        assessment_semantics_version=assessment_semantics_version,
    )

    scope_key = compute_scope_key(
        research_run.research_run_id, research_run.dataset_snapshot_id,
        split_plan.split_plan_id, strategy_name,
    )
    id_kwargs = dict(
        scope_key=scope_key,
        campaign_protocol_fingerprint=protocol_fp,
        research_run_id=research_run.research_run_id,
        research_run_content_hash=rr_hash,
        dataset_snapshot_id=research_run.dataset_snapshot_id,
        split_plan_id=split_plan.split_plan_id,
        strategy_name=strategy_name,
        gate_v_validation_policy_id=policy.validation_policy_id,
        policy_content_hash=policy_hash,
        policy_git_sha=resolved_git_sha,
        assessment_semantics_version=assessment_semantics_version,
        preregistration_semantics_version=GATE_V_PREREGISTRATION_SEMANTICS_VERSION,
    )
    preregistration_id = compute_preregistration_id(**id_kwargs)
    content_hash = compute_preregistration_content_hash(preregistration_id=preregistration_id, **id_kwargs)

    return GateVPreRegistration(
        scope_key=scope_key,
        preregistration_id=preregistration_id,
        preregistration_content_hash=content_hash,
        campaign_protocol_fingerprint=protocol_fp,
        research_run_id=research_run.research_run_id,
        research_run_content_hash=rr_hash,
        dataset_snapshot_id=research_run.dataset_snapshot_id,
        split_plan_id=split_plan.split_plan_id,
        strategy_name=strategy_name,
        gate_v_validation_policy_id=policy.validation_policy_id,
        policy_content_hash=policy_hash,
        policy_git_sha=resolved_git_sha,
        assessment_semantics_version=assessment_semantics_version,
        preregistration_semantics_version=GATE_V_PREREGISTRATION_SEMANTICS_VERSION,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
    )


def save_gate_v_preregistration(path: Union[str, Path], preregistration: GateVPreRegistration) -> Path:
    """Immuable — `save_atomic()` refuse tout écrasement. Convention : chemin keyé par
    `scope_key` (ex. `results/job_xxx/gate_v/preregistrations/<scope_key>.json`), fourni par
    l'appelant — ce module ne résout jamais lui-même un répertoire de projet. Un second
    préenregistrement pour le MÊME `scope_key` (quelle que soit sa policy) entre en collision sur
    le même chemin et est donc refusé (ADR 0025 Décision 8). Réutilise `save_exclusive()`
    (`os.O_CREAT|O_EXCL`) plutôt que `save_atomic()` : celle-ci ne garantit PAS l'exclusivité
    ENTRE PROCESSUS (TOCTOU documenté sur `target.is_file()`) — deux processus concurrents
    préenregistrant le même `scope_key` doivent produire exactement un gagnant, jamais deux
    succès ni un écrasement silencieux (revue Slice B, corrigé)."""
    return save_exclusive(path, asdict(preregistration), kind="GateVPreRegistration")


_PREREGISTRATION_FIELD_NAMES = frozenset(f.name for f in fields(GateVPreRegistration))


def load_gate_v_preregistration(path: Union[str, Path]) -> GateVPreRegistration:
    """Chargement STRICT, fail-closed : absent/illisible/malformé/incohérent -> exception,
    jamais un `None` silencieux. Revalide l'identité/le hash au chargement (ADR 0025) — un
    `preregistration_id`/`preregistration_content_hash`/`preregistration_semantics_version`
    falsifié est détecté par recalcul et rejeté."""
    data = load_json_tolerant(path)
    if data is None:
        raise ValueError(f"GateVPreRegistration illisible ou introuvable : {path}")
    if not isinstance(data, dict):
        raise ValueError("GateVPreRegistration malformée : objet JSON attendu.")
    unknown = set(data.keys()) - _PREREGISTRATION_FIELD_NAMES
    if unknown:
        raise ValueError(f"GateVPreRegistration malformée : champ(s) inconnu(s) {sorted(unknown)}")
    missing = _PREREGISTRATION_FIELD_NAMES - set(data.keys())
    if missing:
        raise ValueError(f"GateVPreRegistration malformée : champ(s) manquant(s) {sorted(missing)}")
    try:
        preregistration = GateVPreRegistration(**data)
    except TypeError as exc:
        raise ValueError(f"GateVPreRegistration malformée : {exc}") from exc

    recomputed_scope_key = compute_scope_key(
        preregistration.research_run_id, preregistration.dataset_snapshot_id,
        preregistration.split_plan_id, preregistration.strategy_name,
    )
    if recomputed_scope_key != preregistration.scope_key:
        raise ValueError("GateVPreRegistration incohérente : scope_key ne correspond pas aux champs référencés.")

    id_kwargs = dict(
        scope_key=preregistration.scope_key,
        campaign_protocol_fingerprint=preregistration.campaign_protocol_fingerprint,
        research_run_id=preregistration.research_run_id,
        research_run_content_hash=preregistration.research_run_content_hash,
        dataset_snapshot_id=preregistration.dataset_snapshot_id,
        split_plan_id=preregistration.split_plan_id,
        strategy_name=preregistration.strategy_name,
        gate_v_validation_policy_id=preregistration.gate_v_validation_policy_id,
        policy_content_hash=preregistration.policy_content_hash,
        policy_git_sha=preregistration.policy_git_sha,
        assessment_semantics_version=preregistration.assessment_semantics_version,
        preregistration_semantics_version=preregistration.preregistration_semantics_version,
    )
    recomputed_id = compute_preregistration_id(**id_kwargs)
    if recomputed_id != preregistration.preregistration_id:
        raise ValueError("GateVPreRegistration incohérente : preregistration_id ne correspond pas au contenu.")
    recomputed_hash = compute_preregistration_content_hash(preregistration_id=recomputed_id, **id_kwargs)
    if recomputed_hash != preregistration.preregistration_content_hash:
        raise ValueError("GateVPreRegistration incohérente : preregistration_content_hash ne correspond pas au contenu.")

    return preregistration
