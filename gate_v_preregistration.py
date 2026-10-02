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
canonique `compute_campaign_protocol_fingerprint()` (réutilisée depuis Slice C par
`GateVCampaignPlanV2`, `gate_v_campaign_plan_v2.py`). AUCUN `FinalHoldoutAccessClaim`, AUCUN
`ValidationAssessment`, AUCUN `GateVPolicyAssessment`, AUCUN accès `FINAL_HOLDOUT`, AUCUNE
campagne réelle — réservés aux tranches suivantes.

**Duplication documentée et volontaire** : `compute_fold_definitions_hash()`/
`compute_validation_zone_hash()` ci-dessous répliquent EXACTEMENT la même formule que les
fonctions/calculs de `gate_v_campaign.py` (V1, non importable, et ce module ne doit pas dépendre de
l'orchestration V1) ; l'égalité avec la formule V1 est verrouillée par test. Depuis Slice C, ces
helpers (et `compute_fold_geometry()`) sont PUBLICS et constituent le point de calcul UNIQUE côté
Slice B/C : `GateVCampaignPlanV2` les réutilise, aucune troisième formule (dette MINOR de Slice B
soldée côté V2 ; il ne reste que la copie V1, volontairement non touchée).

Slice C ajoute aussi `verify_policy_git_provenance_historical()` : la vérification de CRÉATION
(`verify_policy_git_provenance()`, `policy_git_sha == HEAD`) est inchangée ; la version historique
(ADR 0025 Décision 20.10) sert la construction du Plan V2 et toute relecture, sans exiger HEAD.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
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
from walk_forward import WalkForwardSpecification, build_walk_forward_specification, compute_fold_definitions

GATE_V_PREREGISTRATION_SEMANTICS_VERSION = "gate_v_preregistration_v1"
CAMPAIGN_PLAN_SEMANTICS_VERSION_V2 = "gate_v_campaign_plan_v2"


class GitProvenanceError(ValueError):
    """Provenance Git de la policy invalide ou non vérifiable — échec fermé (ADR 0025 Décision 6)."""


# Protocole de recherche : mêmes règles que le plan V1 (`gate_v_campaign.py`, non importé ici ; égalité
# verrouillée par test) — UNE seule validation canonique, partagée par la PreRegistration et par
# `GateVCampaignPlanV2`, pour qu'un scope exclusif ne puisse jamais être consommé par un protocole que
# le Plan V2 refuserait ensuite.
GATE_V_SEARCH_MODES = frozenset({"single_var", "cross_zone", "grid", "general"})
_SEARCH_SPACE_HASH_RE = re.compile(r"[0-9a-fA-F]{12}")

# Identifiant d'objet Git COMPLET canonique (SHA-1 40 ou SHA-256 64 hex minuscules) : seule forme
# admise pour `policy_git_sha` persisté (ADR 0025 Décision 20.10). Publique : réutilisée par le Plan V2.
FULL_GIT_OBJECT_ID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _assert_json_finite(value, field_name: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{field_name} doit avoir des clés non vides de type chaîne.")
            _assert_json_finite(item, field_name)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_json_finite(item, field_name)
    elif value is None or isinstance(value, (str, bool, int)):
        return
    elif isinstance(value, float) and math.isfinite(value):
        return
    else:
        raise ValueError(f"{field_name} contient une valeur non JSON ou non finie : {type(value).__name__}.")


def validate_campaign_protocol_inputs(
    *,
    base_params,
    search_mode,
    search_space_hash,
    budget_per_fold,
    walk_forward_specification,
    readiness_spec,
) -> str:
    """Validation CANONIQUE (pure, fail-closed) des entrées de protocole d'une campagne Gate V —
    appelée AVANT toute construction de `GateVPreRegistration` et de `GateVCampaignPlanV2`.

    Règles (celles du plan V1) : `search_mode` ∈ `GATE_V_SEARCH_MODES` ; `search_space_hash` = 12
    chiffres hexadécimaux ; `budget_per_fold` = entier strictement positif (bool interdit) ;
    `base_params` = dict JSON fini non vide, identique à `walk_forward_specification.base_params` ;
    `WalkForwardSpecification` canonique (reconstruite à l'identique, sans policy de verdict WF) ;
    `readiness_spec` = `DailyStateReadiness` valide ou `None`.

    Retourne le `search_space_hash` NORMALISÉ en minuscule (comme le V1 avant fingerprint) : c'est
    cette valeur que l'appelant doit utiliser pour le fingerprint et pour la persistance."""
    if not isinstance(base_params, dict) or not base_params:
        raise ValueError("base_params est obligatoire et doit être un dictionnaire non vide.")
    _assert_json_finite(base_params, "base_params")
    if not isinstance(search_mode, str) or search_mode not in GATE_V_SEARCH_MODES:
        raise ValueError(f"search_mode est obligatoire et doit être dans {sorted(GATE_V_SEARCH_MODES)}.")
    if not isinstance(search_space_hash, str) or _SEARCH_SPACE_HASH_RE.fullmatch(search_space_hash) is None:
        raise ValueError("search_space_hash est obligatoire et doit être l'empreinte de 12 chiffres hexadécimaux.")
    if not _is_int(budget_per_fold) or budget_per_fold <= 0:
        raise ValueError("budget_per_fold est obligatoire et doit être un entier strictement positif.")

    spec = walk_forward_specification
    if not isinstance(spec, WalkForwardSpecification):
        raise ValueError("walk_forward_specification doit être une WalkForwardSpecification.")
    if spec.verdict_policy_id is not None:
        raise ValueError("walk_forward_specification.verdict_policy_id doit être None : aucune policy de verdict WF.")
    if not isinstance(spec.base_params, dict) or spec.base_params != base_params:
        raise ValueError("walk_forward_specification.base_params doit être identique à base_params.")
    if spec.master_seed is not None and not _is_int(spec.master_seed):
        raise ValueError("walk_forward_specification.master_seed doit être un entier ou None.")
    try:
        rebuilt = build_walk_forward_specification(
            base_params=dict(spec.base_params), geometry=spec.geometry, train_period=spec.train_period,
            test_period=spec.test_period, step_period=spec.step_period,
            allow_partial_last_fold=spec.allow_partial_last_fold,
            position_transition_policy=spec.position_transition_policy,
            verdict_policy_id=spec.verdict_policy_id, master_seed=spec.master_seed,
        )
    except (ValueError, TypeError) as exc:
        raise ValueError(f"walk_forward_specification invalide : {exc}") from exc
    if rebuilt != spec:
        raise ValueError("walk_forward_specification incohérente avec sa reconstruction canonique.")

    if readiness_spec is not None:
        if not isinstance(readiness_spec, DailyStateReadiness):
            raise ValueError("readiness_spec doit être un DailyStateReadiness ou None.")
        if not _is_int(readiness_spec.latest_safe_start_hour) or not 0 <= readiness_spec.latest_safe_start_hour <= 23:
            raise ValueError("readiness_spec.latest_safe_start_hour invalide.")
        if not _is_int(readiness_spec.latest_safe_start_minute) or not 0 <= readiness_spec.latest_safe_start_minute <= 59:
            raise ValueError("readiness_spec.latest_safe_start_minute invalide.")
        if not isinstance(readiness_spec.timezone, str) or not readiness_spec.timezone.strip():
            raise ValueError("readiness_spec.timezone est obligatoire et doit être une chaîne non vide.")
    return search_space_hash.lower()


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
    Réutilisée telle quelle par `GateVCampaignPlanV2` (`gate_v_campaign_plan_v2.py`, Slice C), jamais
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
    except (OSError, ValueError) as exc:  # ValueError : argument invalide (ex. octet NUL) -> échec fermé typé
        raise GitProvenanceError(f"git introuvable ou inexécutable : {exc}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip() if result.stderr else ""
        raise GitProvenanceError(f"git {' '.join(args)} a échoué : {stderr}")
    return result.stdout


def _resolve_policy_git_sha(policy_git_sha: str, repo_dir: Union[str, Path]) -> str:
    """Identité CANONIQUE COMPLÈTE du commit désigné (ADR 0025 Décision 6 + 20.10) : `"auto"` vaut
    `HEAD` ; toute autre valeur (`HEAD`, branche, tag, SHA court ou complet) est résolue via
    `rev-parse <valeur>^{commit}`. Seul le SHA complet résolu est retourné — donc persisté dans
    l'artefact et dans `preregistration_id`/`preregistration_content_hash` — jamais la référence
    symbolique ou abrégée d'origine (qui bougerait ou deviendrait ambiguë). Que ce commit soit
    exactement le HEAD courant reste vérifié séparément par `verify_policy_git_provenance()`."""
    if not isinstance(policy_git_sha, str) or not policy_git_sha.strip():
        raise GitProvenanceError("policy_git_sha explicite doit être une chaîne non vide.")
    revision = "HEAD" if policy_git_sha == "auto" else policy_git_sha
    if revision != revision.strip() or revision.startswith("-"):
        raise GitProvenanceError(f"policy_git_sha invalide (espaces ou option Git) : {policy_git_sha!r}")
    try:
        canonical = _run_git(["rev-parse", f"{revision}^{{commit}}"], cwd=repo_dir).decode("utf-8").strip()
    except GitProvenanceError as exc:
        raise GitProvenanceError(
            f"policy_git_sha ne résout à aucun commit du dépôt : {policy_git_sha!r} ({exc})"
        ) from exc
    if FULL_GIT_OBJECT_ID_RE.fullmatch(canonical) is None:
        raise GitProvenanceError(f"Identifiant de commit canonique inattendu : {canonical!r}")
    return canonical


def _resolve_repo_relative_path(policy_path: Path, resolved_repo_dir: Path):
    """Racine du dépôt Git + chemin POSIX de la policy relatif à cette racine — partagé par la
    vérification de CRÉATION et la vérification HISTORIQUE (aucune dépendance au CWD du processus)."""
    toplevel_raw = _run_git(["rev-parse", "--show-toplevel"], cwd=resolved_repo_dir)
    toplevel = Path(toplevel_raw.decode("utf-8").strip()).resolve()
    try:
        rel_path = policy_path.resolve().relative_to(toplevel)
    except ValueError as exc:
        raise GitProvenanceError(
            f"{policy_path} n'est pas dans le dépôt Git résolu ({toplevel})."
        ) from exc
    return toplevel, rel_path.as_posix()


def _verify_committed_policy_blob(
    *, toplevel: Path, rel_path_str: str, policy_git_sha: str,
    validation_policy_id: str, expected_policy_content_hash: str,
) -> None:
    """Lit le blob committé (`git show <sha>:<path>`, jamais le working tree), le reconstruit via
    l'UNIQUE chemin de validation de Slice A, puis vérifie identifiant et hash de contenu. Partagé
    par la vérification de CRÉATION et la vérification HISTORIQUE."""
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

    toplevel, rel_path_str = _resolve_repo_relative_path(policy_path, resolved_repo_dir)

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

    _verify_committed_policy_blob(
        toplevel=toplevel, rel_path_str=rel_path_str, policy_git_sha=policy_git_sha,
        validation_policy_id=validation_policy_id,
        expected_policy_content_hash=expected_policy_content_hash,
    )


def verify_policy_git_provenance_historical(
    *,
    policy_path: Union[str, Path],
    validation_policy_id: str,
    expected_policy_content_hash: str,
    policy_git_sha: str,
    repo_dir: Optional[Union[str, Path]] = None,
) -> None:
    """Provenance Git HISTORIQUE de la policy, fail-closed (ADR 0025 Décision 20.10) — distincte de
    `verify_policy_git_provenance()`, qui reste la règle de CRÉATION (`policy_git_sha == HEAD`).

    Sert la construction de `GateVCampaignPlanV2` (postérieure à la PreRegistration) et toute
    relecture : HEAD a naturellement avancé, l'égalité au HEAD courant n'est donc JAMAIS exigée.
    Vérifie à la place, depuis l'objet Git référencé : (1) `policy_git_sha` est un identifiant
    d'objet COMPLET immuable (40 ou 64 hex minuscules — jamais `HEAD`/branche/tag/SHA court, qui
    bougent ou deviennent ambigus) ; (2) il désigne un commit résolvable ; (3) le blob de la policy
    à ce commit existe, est du JSON valide et une policy bien formée ; (4) `validation_policy_id` et
    `policy_content_hash` correspondent. Le working tree n'est JAMAIS lu (le fichier local peut avoir
    été modifié ou supprimé depuis) ; le fichier de policy n'a pas besoin d'exister localement."""
    policy_path = Path(policy_path)
    resolved_repo_dir = Path(repo_dir) if repo_dir is not None else policy_path.parent
    if not isinstance(policy_git_sha, str) or FULL_GIT_OBJECT_ID_RE.fullmatch(policy_git_sha) is None:
        raise GitProvenanceError(
            "policy_git_sha historique doit être un identifiant d'objet Git complet "
            f"(40 ou 64 hex minuscules), pas une référence symbolique/courte : {policy_git_sha!r}"
        )

    toplevel, rel_path_str = _resolve_repo_relative_path(policy_path, resolved_repo_dir)

    try:
        resolved_sha = _run_git(["rev-parse", f"{policy_git_sha}^{{commit}}"], cwd=toplevel).decode("utf-8").strip()
    except GitProvenanceError as exc:
        raise GitProvenanceError(
            f"policy_git_sha ne résout à aucun commit du dépôt : {policy_git_sha!r} ({exc})"
        ) from exc
    if resolved_sha != policy_git_sha:
        raise GitProvenanceError(
            f"policy_git_sha n'est pas l'identifiant canonique du commit : "
            f"fourni={policy_git_sha!r}, résolu={resolved_sha!r}"
        )

    _verify_committed_policy_blob(
        toplevel=toplevel, rel_path_str=rel_path_str, policy_git_sha=policy_git_sha,
        validation_policy_id=validation_policy_id,
        expected_policy_content_hash=expected_policy_content_hash,
    )


def compute_fold_definitions_hash(fold_definitions) -> str:
    """Hash canonique des `FoldDefinition` — MÊME formule que `gate_v_campaign._fold_definitions_hash`
    (V1, non importable ici) ; verrouillée contre elle par test. Point de calcul UNIQUE côté Slice
    B/C : `GateVCampaignPlanV2` l'appelle, jamais une troisième réimplémentation."""
    payload = [dataclasses.asdict(fold) for fold in fold_definitions]
    return _sha256_hex(_canonical_json(payload))


def compute_validation_zone_hash(validation_zone) -> str:
    """Hash canonique de la zone de validation (`SplitBoundary`) — même formule que le calcul inline
    de `gate_v_campaign.build_gate_v_campaign_plan()`."""
    return _sha256_hex(_canonical_json(asdict(validation_zone)))


def compute_fold_geometry(
    split_plan: DatasetSplitPlan,
    walk_forward_specification: WalkForwardSpecification,
    readiness_spec: Optional[DailyStateReadiness],
) -> Tuple[Tuple[str, ...], str, str]:
    """`(expected_fold_ids, expected_fold_definitions_hash, validation_zone_hash)` recalculés depuis
    les VRAIES structures — jamais des valeurs transmises par l'appelant (pure, aucune exécution)."""
    if split_plan.validation is None:
        raise ValueError("Le DatasetSplitPlan doit contenir une zone validation pour Walk-Forward.")
    fold_definitions = compute_fold_definitions(split_plan.validation, walk_forward_specification, readiness_spec)
    return (
        tuple(fold.fold_id for fold in fold_definitions),
        compute_fold_definitions_hash(fold_definitions),
        compute_validation_zone_hash(split_plan.validation),
    )


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
    # Même exigence que `GateVCampaignPlanV2` (chaîne non vide) : refusée ICI, jamais après sauvegarde.
    if not isinstance(assessment_semantics_version, str) or not assessment_semantics_version.strip():
        raise ValueError("assessment_semantics_version est obligatoire et doit être une chaîne non vide.")
    # Protocole validé AVANT toute construction (donc avant tout scope exclusif consommable) : même
    # validation canonique que `GateVCampaignPlanV2`. `search_space_hash` normalisé en minuscule.
    search_space_hash = validate_campaign_protocol_inputs(
        base_params=base_params, search_mode=search_mode, search_space_hash=search_space_hash,
        budget_per_fold=budget_per_fold, walk_forward_specification=walk_forward_specification,
        readiness_spec=readiness_spec,
    )
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

    expected_fold_ids, expected_fold_definitions_hash, validation_zone_hash = compute_fold_geometry(
        split_plan, walk_forward_specification, readiness_spec
    )
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
