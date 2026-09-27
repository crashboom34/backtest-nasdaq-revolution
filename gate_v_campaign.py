"""
gate_v_campaign.py — GATE V Campaign Orchestration V1, Niveau A (AF-V-08 Slice 1).

Contrat de référence : `docs/adr/0024-gate-v-campaign-orchestration-v1.md` (Décisions 1-5, partie
Niveau A uniquement — Niveau B/`execute_gate_v_campaign()` reste hors scope de cette tranche,
Slices 3-6). Nouveau module top-level LEAF côté écriture (ADR Décision 1 : jamais dans
`validation_run.py`, qui reste sans connaissance d'aucun concept de "campagne").

**`GateVCampaignPlan`** (frozen, immuable) synthétise les entrées obligatoires d'une campagne
`GATE V` (ADR Décisions 1-4) : identifiants (`campaign_id` DISTINCT de `research_run_id`, jamais
fusionnés — Décision 2), entrées scientifiques sans aucun défaut (Décision 3), versions de
sémantique capturées TELLES QUELLES depuis les constantes module réelles au moment de la
construction, et `expected_fold_ids` calculé UNE SEULE FOIS par `build_gate_v_campaign_plan()`
elle-même (Décision 5/6) pour qu'un futur Niveau B (Slices 3-6) puisse vérifier l'exhaustivité
sans recalculer.

**`build_gate_v_campaign_plan()`** est la SEULE construction sanctionnée (Décision 5, Niveau A) :
validation fail-closed de toutes les entrées obligatoires, chargement du `DatasetSplitPlan` réel
(zone VALIDATION uniquement — jamais la zone terminale réservée, voir plus bas), vérification
optionnelle d'une preuve OOS déjà existante (Décision 9), calcul déterministe de
`expected_fold_ids` via `walk_forward.compute_fold_definitions()` (fonction PURE déjà existante,
ADR 0021), et persistance UNE SEULE FOIS du plan immuable. **Aucune donnée de marché, aucun
`Optimizer`, aucun backtest** — entièrement local, déterministe, rejouable à l'identique.

**Résolution de chemin, tension non tranchée littéralement par la mission (décision prise ici,
documentée plutôt que devinée silencieusement)** : la mission décrit une signature de
`build_gate_v_campaign_plan()` à 13 paramètres scientifiques, mais la Décision 5 lui demande aussi
de (a) charger un `DatasetSplitPlan` déjà écrit sur disque depuis un `split_plan_id`, (b) charger
une `ValidationRun` OOS déjà écrite depuis un `oos_evidence_validation_run_id` (Décision 9), et (c)
persister le plan produit sous `.../gate_v_campaign/<campaign_id>/plan.json` (Décision 4). Aucune
de ces trois opérations disque n'est réalisable sans une information de CHEMIN — et le précédent
RÉEL déjà établi dans ce dépôt (`scripts/create_walk_forward_validation_split_plan.py`,
`dataset_split.load_dataset_split_plan(path)`, `validation_run.load_validation_run(path)`,
`dataset_split.save_dataset_split_plan(path, plan)`) est que la résolution `identifiant -> chemin`
est TOUJOURS une responsabilité de l'appelant (script/orchestration), JAMAIS devinée par le module
de contrat lui-même via une convention `résultats/<type>/<id>/...` codée en dur — précisément pour
éviter qu'une suite de tests isolée (`tmp_path`) ne soit forcée d'écrire sous le `results/` RÉEL du
dépôt (qui contient déjà des `DatasetSplitPlan` réels, `results/dataset_splits/`). Ce module ajoute
donc trois paramètres keyword-only de PLOMBERIE PURE, absents du domaine (jamais stockés sur
`GateVCampaignPlan`, qui ne garde que les IDENTIFIANTS — `split_plan_id`/
`oos_evidence_validation_run_id` — exactement comme l'ADR le spécifie) : `split_plan_path`
(obligatoire), `job_dir` (obligatoire — répertoire équivalent à ce que
`optimization_store.get_job_dir()` produirait ailleurs, jamais importé ici puisque
`optimization_store.py` est hors périmètre de cette mission), `oos_evidence_validation_run_path`
(optionnel, fourni conjointement avec `oos_evidence_validation_run_id` — les deux ou aucun).

**Géométrie Walk-Forward exposée explicitement (corrigé — finding MAJEUR, revue architecture)** :
`build_gate_v_campaign_plan()` accepte `walk_forward_geometry`/`walk_forward_train_period`/
`walk_forward_test_period`/`walk_forward_step_period`/`walk_forward_master_seed` en paramètres
keyword-only optionnels, avec pour défauts EXACTEMENT ceux de `walk_forward.
build_walk_forward_specification()` ("rolling"/P24M/P6M/P6M/`None`) — aucune régression pour un
appelant qui ne les fournit pas. Ce choix N'EST PAS neutre (il détermine le nombre et les dates de
chaque fold, donc toute la preuve produite en aval) : le figer silencieusement aurait forcé toute
campagne à une seule géométrie sans possibilité de le changer sans casser le contrat déjà persisté.
Les cinq valeurs sont donc transmises telles quelles à `walk_forward.
build_walk_forward_specification()` et stockées sur `GateVCampaignPlan` (mêmes noms de champs),
pour qu'un futur Niveau B/lecteur du plan sache exactement quelle géométrie a produit
`expected_fold_ids`, sans avoir à la redeviner.

**Pas d'accès à la zone terminale réservée** : ce module lit UNIQUEMENT `split_plan.validation` —
il ne lit, ne transmet, ne référence JAMAIS l'autre zone de `DatasetSplitPlan` (ADR Décision 10),
et n'importe jamais `validation_oos.py` (le seul module autorisé à la consulter) — vérifié par un
test d'import statique dédié (`tests/test_gate_v_campaign.py`).

**Découplage (`/codebase-design`)** : imports autorisés uniquement vers des modules déjà réels et
déjà revus — `dataset_split.py`, `walk_forward.py`, `validation_run.py`, `atomic_json_store.py`.
Jamais `engine.py`/`optimizer.py`/`validation_oos.py` (vérifié par test d'import statique AST,
mirroring `tests/test_monte_carlo.py`). `walk_forward.py` importe lui-même `optimizer.py` en
transitif — sans rapport avec la garantie structurelle de CE module, qui ne porte que sur SES
propres imports directs (ADR Décision 10, portée explicite).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Tuple, Union

from atomic_json_store import load_json_tolerant, save_atomic, validate_portable_identifier
from dataset_split import load_dataset_split_plan
from validation_run import (
    VALIDATION_TYPE_OOS,
    MONTE_CARLO_SEMANTICS_VERSION,
    PARAMETER_STABILITY_SEMANTICS_VERSION,
    load_validation_run,
)
from walk_forward import (
    WALK_FORWARD_SEMANTICS_VERSION,
    build_walk_forward_specification,
    compute_fold_definitions,
)

_VALID_SEARCH_MODES = frozenset({"single_var", "cross_zone", "grid", "general"})
"""Duplication LOCALE et délibérée (mirroring `validation_run._PARAMETER_STABILITY_VALID_SEARCH_MODES`,
lui-même dupliqué depuis `optimizer.DETERMINISTIC_DISPATCH_MODES ∪ {"general"}`) — ce module reste
un leaf côté imports scientifiques, jamais un import direct de `optimizer.py` (ADR 0024 Décision 5,
mirroring AF-V-04 Slice 1)."""


@dataclass(frozen=True)
class GateVCampaignPlan:
    """Préparation immuable d'une campagne `GATE V` — ADR 0024 Décisions 1-4. Distincte de toute
    `ValidationRun` (une campagne en agrège PLUSIEURS, de `validation_type` différents) et de tout
    `GateVCampaignManifest` (mutable, Niveau B, hors scope de cette tranche).

    `campaign_id` reste un identifiant DISTINCT de `research_run_id` (Décision 2) — jamais
    fusionnés, même si cette tranche ne construit qu'un seul `ResearchRun` par campagne en
    pratique. `expected_fold_ids` est calculé UNE SEULE FOIS par `build_gate_v_campaign_plan()`
    (Décision 5/6) et stocké ici pour qu'un futur Niveau B puisse vérifier l'exhaustivité sans
    recalculer. Aucune méthode de mutation — un nouveau `GateVCampaignPlan` distinct est le seul
    moyen de changer une entrée (Décision 1)."""

    campaign_id: str
    research_run_id: str
    dataset_snapshot_id: str
    split_plan_id: str
    strategy_name: str
    base_params: dict
    search_mode: str
    search_space_hash: str
    budget_per_fold: int
    walk_forward_spec_semantics_version: str
    monte_carlo_semantics_version: str
    parameter_stability_semantics_version: str
    expected_fold_ids: Tuple[str, ...]
    walk_forward_geometry: str = "rolling"
    walk_forward_train_period: str = "P24M"
    walk_forward_test_period: str = "P6M"
    walk_forward_step_period: str = "P6M"
    walk_forward_master_seed: Optional[int] = None
    monte_carlo_verdict_policy_id: Optional[str] = None
    parameter_stability_verdict_policy_id: Optional[str] = None
    walk_forward_verdict_policy_id: Optional[str] = None
    oos_evidence_validation_run_id: Optional[str] = None


def _require_non_empty_str(value, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field_name} est obligatoire pour construire un GateVCampaignPlan — aucun défaut "
            f"silencieux (ADR 0024 Décision 3) : {value!r}"
        )
    return value


def build_gate_v_campaign_plan(
    campaign_id: str,
    research_run_id: str,
    dataset_snapshot_id: str,
    split_plan_id: str,
    strategy_name: str,
    base_params: dict,
    search_mode: str,
    search_space_hash: str,
    budget_per_fold: int,
    *,
    split_plan_path: Union[str, Path],
    job_dir: Union[str, Path],
    walk_forward_geometry: str = "rolling",
    walk_forward_train_period: str = "P24M",
    walk_forward_test_period: str = "P6M",
    walk_forward_step_period: str = "P6M",
    walk_forward_master_seed: Optional[int] = None,
    monte_carlo_verdict_policy_id: Optional[str] = None,
    parameter_stability_verdict_policy_id: Optional[str] = None,
    walk_forward_verdict_policy_id: Optional[str] = None,
    oos_evidence_validation_run_id: Optional[str] = None,
    oos_evidence_validation_run_path: Optional[Union[str, Path]] = None,
) -> GateVCampaignPlan:
    """SEULE construction sanctionnée d'un `GateVCampaignPlan` (ADR 0024 Décision 5, Niveau A —
    préparation déterministe, jamais d'exécution).

    Lève `ValueError` immédiatement, AVANT tout accès disque, pour chaque champ obligatoire
    manquant/vide : `campaign_id`/`research_run_id`/`dataset_snapshot_id`/`split_plan_id`/
    `strategy_name` (chaîne non vide), `base_params` (dict non vide), `search_mode` (une des 4
    valeurs réelles de ce dépôt), `search_space_hash` (chaîne non vide), `budget_per_fold`
    (entier strictement positif) — Décision 3, taxonomie fail-closed.

    Charge ensuite le `DatasetSplitPlan` réel depuis `split_plan_path` (`dataset_split.
    load_dataset_split_plan()`, EXISTANT, jamais réimplémenté) : `ValueError` si absent/invalide,
    si son `dataset_snapshot_id` diverge de celui fourni, ou si sa zone VALIDATION est `None`
    (Décision 5). Lit UNIQUEMENT cette zone — jamais l'autre zone réservée du plan (Décision 10).

    Si `oos_evidence_validation_run_id` est fourni (avec `oos_evidence_validation_run_path`,
    obligatoire dans ce cas), charge la `ValidationRun` correspondante (`validation_run.
    load_validation_run()`, EXISTANT) : `ValueError` si absente/invalide ou si son
    `validation_type` n'est pas `"oos"` (Décision 9). Les deux paramètres `oos_evidence_*` doivent
    être fournis ensemble ou omis ensemble — jamais l'un sans l'autre.

    Calcule `expected_fold_ids` via `walk_forward.compute_fold_definitions()` (fonction PURE,
    déterministe, ADR 0021) sur la zone VALIDATION du plan et une `WalkForwardSpecification`
    construite depuis `base_params`/`walk_forward_verdict_policy_id` et la géométrie explicite
    `walk_forward_geometry`/`walk_forward_train_period`/`walk_forward_test_period`/
    `walk_forward_step_period`/`walk_forward_master_seed` (défauts EXACTEMENT ceux de
    `walk_forward.build_walk_forward_specification()` — "rolling"/P24M/P6M/P6M/`None` — jamais un
    choix implicite différent, corrigé suite à un finding MAJEUR de revue). `readiness_spec=None` —
    ce plan ne porte aucun contrat de readiness, mirroring le comportement stateless documenté par
    `strategy_contracts.resolve_state_ready_boundary()`. N'exécute JAMAIS de backtest, ne charge
    JAMAIS de donnée de marché, ne consomme aucun budget de calcul scientifique réel.

    Persiste le plan UNE SEULE FOIS sous `<job_dir>/gate_v_campaign/<campaign_id>/plan.json`
    (`atomic_json_store.save_atomic()`, refuse un `campaign_id` déjà écrit — `FileExistsError`,
    Décision 4) et retourne le `GateVCampaignPlan` FROZEN construit."""
    campaign_id = validate_portable_identifier(
        _require_non_empty_str(campaign_id, "campaign_id"), "campaign_id"
    )
    research_run_id = validate_portable_identifier(
        _require_non_empty_str(research_run_id, "research_run_id"), "research_run_id"
    )
    dataset_snapshot_id = _require_non_empty_str(dataset_snapshot_id, "dataset_snapshot_id")
    split_plan_id = validate_portable_identifier(
        _require_non_empty_str(split_plan_id, "split_plan_id"), "split_plan_id"
    )
    strategy_name = _require_non_empty_str(strategy_name, "strategy_name")
    if not isinstance(base_params, dict) or not base_params:
        raise ValueError(
            "base_params est obligatoire et non vide — jamais un DEFAULT_PARAMS implicite (ADR "
            "0024 Décision 3)."
        )
    if search_mode not in _VALID_SEARCH_MODES:
        raise ValueError(
            f"search_mode={search_mode!r} invalide — valeurs acceptées : "
            f"{sorted(_VALID_SEARCH_MODES)} (ADR 0024 Décision 3, taxonomie fail-closed)."
        )
    search_space_hash = _require_non_empty_str(search_space_hash, "search_space_hash")
    if not isinstance(budget_per_fold, int) or budget_per_fold <= 0:
        raise ValueError(
            f"budget_per_fold doit être un entier strictement positif : {budget_per_fold!r} "
            "(ADR 0024 Décision 3, plafond explicite, jamais un budget illimité implicite)."
        )
    if (oos_evidence_validation_run_id is None) != (oos_evidence_validation_run_path is None):
        raise ValueError(
            "oos_evidence_validation_run_id et oos_evidence_validation_run_path doivent être "
            "fournis ensemble ou omis ensemble — jamais l'un sans l'autre (ambiguïté sinon)."
        )

    split_plan = load_dataset_split_plan(split_plan_path)
    if split_plan is None:
        raise ValueError(
            f"split_plan_id={split_plan_id!r} introuvable/invalide à split_plan_path="
            f"{str(split_plan_path)!r} — un DatasetSplitPlan réel doit déjà être écrit sur disque "
            "(ADR 0024 Décision 3/5)."
        )
    if split_plan.split_plan_id != split_plan_id:
        raise ValueError(
            f"split_plan_id={split_plan_id!r} incohérent avec celui du plan réellement chargé à "
            f"split_plan_path={str(split_plan_path)!r} ({split_plan.split_plan_id!r}) — un "
            "split_plan_id doit référencer un DatasetSplitPlan réel (ADR 0024 Décision 3)."
        )
    if split_plan.dataset_snapshot_id != dataset_snapshot_id:
        raise ValueError(
            f"dataset_snapshot_id={dataset_snapshot_id!r} incohérent avec celui du split_plan "
            f"chargé ({split_plan.dataset_snapshot_id!r}) — ADR 0024 Décision 3."
        )
    if split_plan.validation is None:
        raise ValueError(
            f"split_plan_id={split_plan_id!r} n'a pas de zone VALIDATION — obligatoire pour une "
            "campagne GATE V (ADR 0024 Décision 5)."
        )

    if oos_evidence_validation_run_id is not None:
        oos_evidence_validation_run_id = _require_non_empty_str(
            oos_evidence_validation_run_id, "oos_evidence_validation_run_id"
        )
        oos_run = load_validation_run(oos_evidence_validation_run_path)
        if oos_run is None:
            raise ValueError(
                f"oos_evidence_validation_run_id={oos_evidence_validation_run_id!r} "
                f"introuvable/invalide à oos_evidence_validation_run_path="
                f"{str(oos_evidence_validation_run_path)!r} (ADR 0024 Décision 9)."
            )
        if oos_run.validation_run_id != oos_evidence_validation_run_id:
            raise ValueError(
                f"oos_evidence_validation_run_id={oos_evidence_validation_run_id!r} incohérent "
                f"avec celui de la ValidationRun réellement chargée à "
                f"oos_evidence_validation_run_path={str(oos_evidence_validation_run_path)!r} "
                f"({oos_run.validation_run_id!r}) — un oos_evidence_validation_run_id doit "
                "référencer la ValidationRun OOS réellement chargée, jamais une autre "
                "silencieusement (ADR 0024 Décision 9, mirroring la vérification split_plan_id)."
            )
        if oos_run.validation_type != VALIDATION_TYPE_OOS:
            raise ValueError(
                f"oos_evidence_validation_run_id={oos_evidence_validation_run_id!r} référence une "
                f"ValidationRun de validation_type={oos_run.validation_type!r}, attendu "
                f"{VALIDATION_TYPE_OOS!r} (ADR 0024 Décision 9)."
            )

    wf_spec = build_walk_forward_specification(
        base_params=base_params,
        geometry=walk_forward_geometry,
        train_period=walk_forward_train_period,
        test_period=walk_forward_test_period,
        step_period=walk_forward_step_period,
        verdict_policy_id=walk_forward_verdict_policy_id,
        master_seed=walk_forward_master_seed,
    )
    fold_definitions = compute_fold_definitions(split_plan.validation, wf_spec, readiness_spec=None)
    expected_fold_ids = tuple(fold.fold_id for fold in fold_definitions)

    plan = GateVCampaignPlan(
        campaign_id=campaign_id,
        research_run_id=research_run_id,
        dataset_snapshot_id=dataset_snapshot_id,
        split_plan_id=split_plan_id,
        strategy_name=strategy_name,
        base_params=dict(base_params),
        search_mode=search_mode,
        search_space_hash=search_space_hash,
        budget_per_fold=budget_per_fold,
        walk_forward_spec_semantics_version=WALK_FORWARD_SEMANTICS_VERSION,
        monte_carlo_semantics_version=MONTE_CARLO_SEMANTICS_VERSION,
        parameter_stability_semantics_version=PARAMETER_STABILITY_SEMANTICS_VERSION,
        expected_fold_ids=expected_fold_ids,
        walk_forward_geometry=walk_forward_geometry,
        walk_forward_train_period=walk_forward_train_period,
        walk_forward_test_period=walk_forward_test_period,
        walk_forward_step_period=walk_forward_step_period,
        walk_forward_master_seed=walk_forward_master_seed,
        monte_carlo_verdict_policy_id=monte_carlo_verdict_policy_id,
        parameter_stability_verdict_policy_id=parameter_stability_verdict_policy_id,
        walk_forward_verdict_policy_id=walk_forward_verdict_policy_id,
        oos_evidence_validation_run_id=oos_evidence_validation_run_id,
    )

    plan_path = Path(job_dir) / "gate_v_campaign" / campaign_id / "plan.json"
    save_atomic(plan_path, asdict(plan), "gate_v_campaign_plan")
    return plan


def load_gate_v_campaign_plan(path: Union[str, Path]) -> Optional[GateVCampaignPlan]:
    """Lecture tolérante avec rehydratation de `expected_fold_ids` (liste JSON -> tuple) — voir
    `atomic_json_store.load_tolerant()` docstring : un `cls(**data)` générique ne suffit pas pour
    ce champ, même s'il ne s'agit pas d'une dataclass imbriquée (mirroring l'esprit de
    `dataset_split.load_dataset_split_plan()`/`validation_run.load_validation_run()`)."""
    data = load_json_tolerant(path)
    if data is None:
        return None
    try:
        return GateVCampaignPlan(
            campaign_id=data["campaign_id"],
            research_run_id=data["research_run_id"],
            dataset_snapshot_id=data["dataset_snapshot_id"],
            split_plan_id=data["split_plan_id"],
            strategy_name=data["strategy_name"],
            base_params=data["base_params"],
            search_mode=data["search_mode"],
            search_space_hash=data["search_space_hash"],
            budget_per_fold=data["budget_per_fold"],
            walk_forward_spec_semantics_version=data["walk_forward_spec_semantics_version"],
            monte_carlo_semantics_version=data["monte_carlo_semantics_version"],
            parameter_stability_semantics_version=data["parameter_stability_semantics_version"],
            expected_fold_ids=tuple(data["expected_fold_ids"]),
            walk_forward_geometry=data.get("walk_forward_geometry", "rolling"),
            walk_forward_train_period=data.get("walk_forward_train_period", "P24M"),
            walk_forward_test_period=data.get("walk_forward_test_period", "P6M"),
            walk_forward_step_period=data.get("walk_forward_step_period", "P6M"),
            walk_forward_master_seed=data.get("walk_forward_master_seed"),
            monte_carlo_verdict_policy_id=data.get("monte_carlo_verdict_policy_id"),
            parameter_stability_verdict_policy_id=data.get(
                "parameter_stability_verdict_policy_id"
            ),
            walk_forward_verdict_policy_id=data.get("walk_forward_verdict_policy_id"),
            oos_evidence_validation_run_id=data.get("oos_evidence_validation_run_id"),
        )
    except (TypeError, KeyError):
        return None
