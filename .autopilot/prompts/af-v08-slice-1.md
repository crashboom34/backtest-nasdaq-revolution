# Mission AF-V-08 Slice 1 — Contrats `GateVCampaignPlan` + Niveau A (`build_gate_v_campaign_plan()`, ADR 0024)

**Lire intégralement `docs/adr/0024-gate-v-campaign-orchestration-v1.md` avant de commencer** —
cette ADR a été rédigée, revue par deux revues indépendantes (architecture/reproductibilité +
validité scientifique) SUR DEUX PASSES (2 BLOCKER + 3 MAJEUR + 3 MINEUR en première passe, toutes
confirmées corrigées en seconde passe), et committée (`cc00f65`). Cette mission implémente
STRICTEMENT ses Décisions 1, 2, 3, 4 et la partie **Niveau A** de la Décision 5 — jamais le
Niveau B (Slices 3-6). Ne réinterprète rien, ne réintroduit AUCUNE des formulations déjà corrigées
par la revue.

## Ce qui est DANS cette tranche

Nouveau module top-level `gate_v_campaign.py` (jamais dans `validation_run.py`, Décision 1) :

1. **`GateVCampaignPlan`** (frozen dataclass, immuable — Décision 1/3) — champs exacts, synthétisés
   depuis les Décisions 1 à 4 de l'ADR (aucune n'énumère une liste unique consolidée — cette
   synthèse fait foi pour cette tranche) :
   - `campaign_id: str` — identifiant DISTINCT de `research_run_id` (Décision 2, jamais fusionnés).
   - `research_run_id: str` — le `ResearchRun` parent, partagé par TOUTES les `ValidationRun`
     produites (Décision 2) ; fourni explicitement à la construction du plan, jamais généré/deviné
     ici (référence un `ResearchRun` déjà construit ailleurs via `research_run.build_research_run()`
     — cette tranche ne l'appelle PAS elle-même, elle reçoit `research_run_id` comme un `str` déjà
     obtenu par l'appelant).
   - `dataset_snapshot_id: str`, `split_plan_id: str`, `strategy_name: str`, `base_params: dict`
     (NON vide), `search_mode: str`, `search_space_hash: str`, `budget_per_fold: int` (`> 0`) —
     Décision 3, AUCUN défaut.
   - `walk_forward_spec_semantics_version: str`, `monte_carlo_semantics_version: str`,
     `parameter_stability_semantics_version: str` — Décision 3, capturées TELLES QUELLES depuis les
     constantes module RÉELLES (`walk_forward.WALK_FORWARD_SEMANTICS_VERSION`,
     `monte_carlo.MONTE_CARLO_SEMANTICS_VERSION`, `validation_run.PARAMETER_STABILITY_SEMANTICS_VERSION`
     — vérifier les noms exacts dans le code source avant d'écrire l'import), jamais choisies par
     l'appelant.
   - `monte_carlo_verdict_policy_id: Optional[str] = None`,
     `parameter_stability_verdict_policy_id: Optional[str] = None`,
     `walk_forward_verdict_policy_id: Optional[str] = None` — Décision 3, `None` par défaut EXPLICITE.
   - `oos_evidence_validation_run_id: Optional[str] = None` — Décision 3/9.
   - `expected_fold_ids: Tuple[str, ...]` — calculé PAR `build_gate_v_campaign_plan()` elle-même
     (Décision 5 Niveau A, voir point 2 ci-dessous), stocké sur le plan pour que le Niveau B (tranches
     suivantes) puisse vérifier l'exhaustivité SANS recalculer (Décision 6).

2. **`build_gate_v_campaign_plan(campaign_id: str, research_run_id: str, dataset_snapshot_id: str, split_plan_id: str, strategy_name: str, base_params: dict, search_mode: str, search_space_hash: str, budget_per_fold: int, *, monte_carlo_verdict_policy_id: Optional[str] = None, parameter_stability_verdict_policy_id: Optional[str] = None, walk_forward_verdict_policy_id: Optional[str] = None, oos_evidence_validation_run_id: Optional[str] = None) -> GateVCampaignPlan`**
   (Décision 5 Niveau A — SEULE construction sanctionnée) :
   - `ValueError` immédiat (AVANT tout accès disque) pour CHAQUE champ obligatoire manquant/vide —
     `campaign_id`/`research_run_id`/`dataset_snapshot_id`/`split_plan_id`/`strategy_name` (str non
     vide), `base_params` (dict non vide), `search_mode` (une des 4 valeurs réelles — dupliquer
     LOCALEMENT l'ensemble `{"single_var", "cross_zone", "grid", "general"}` comme fait
     `validation_run.py`, JAMAIS un import `optimizer.py` — mirroring AF-V-04 Slice 1), `budget_per_fold`
     (`int > 0`) — mirroring la taxonomie fail-closed déjà établie (Décision 3).
   - Charge le `DatasetSplitPlan` réel (`dataset_split.load_dataset_split_plan(split_plan_id)`, DÉJÀ
     existant, jamais réimplémenté) — `ValueError` si `split_plan.dataset_snapshot_id != dataset_snapshot_id`
     fourni, `ValueError` si `split_plan.validation is None`. **Lit UNIQUEMENT `split_plan.validation`,
     ne référence JAMAIS `split_plan.final_holdout`** (Décision 10 — vérifié par un test d'absence de
     référence textuelle à `final_holdout`/`FINAL_HOLDOUT` dans `gate_v_campaign.py`).
   - Si `oos_evidence_validation_run_id` fourni : `validation_run.load_validation_run(oos_evidence_validation_run_id)`
     (EXISTANT) DOIT réussir et retourner une `ValidationRun` de `validation_type == "oos"` — sinon
     `ValueError` explicite (Décision 9). Si `None`, aucune vérification (contribution OOS restera
     `EVIDENCE_INCOMPLETE`, tranche ultérieure).
   - Capture les 3 `*_semantics_version` depuis les constantes module réelles (voir point 1).
   - Calcule `expected_fold_ids` en appelant `walk_forward.compute_fold_definitions()` (fonction PURE
     déjà existante, ADR 0021) sur `split_plan.validation` + une `WalkForwardSpecification` construite
     depuis `budget_per_fold`/`search_mode`/`search_space_hash` (vérifier la signature réelle de
     `WalkForwardSpecification`/`compute_fold_definitions()` avant d'écrire cet appel — ne jamais
     deviner ses paramètres).
   - **Ne charge AUCUNE donnée de marché** (`nasdaq_3m.csv` jamais ouvert), **n'importe ni n'appelle
     `engine.py`/`optimizer.py::Optimizer.run()`/`validation_oos.py`**, **ne consomme aucun budget de
     calcul scientifique réel** — entièrement local, déterministe, rejouable à l'identique (Décision 5).
   - Persiste le plan UNE SEULE FOIS via `atomic_json_store.save_atomic()` (refuse un `campaign_id`
     déjà écrit, mirroring `save_dataset_split_plan()`/`save_validation_run()`), sous
     `results/job_xxx/gate_v_campaign/<campaign_id>/plan.json` (Décision 4 — chemin PARAMÉTRABLE,
     jamais codé en dur sous `results/` sans passer par une convention cohérente avec
     `optimization_store.get_job_dir()` — vérifier cette convention avant d'écrire le chemin).
   - Retourne le `GateVCampaignPlan` FROZEN — aucune méthode de mutation.

3. Tests TDD (RED confirmé avant implémentation), au minimum : chaque champ obligatoire manquant/vide
   testé INDIVIDUELLEMENT ; `search_mode` invalide -> `ValueError` ; `split_plan_id` inexistant/
   `dataset_snapshot_id` incohérent -> `ValueError` ; `split_plan.validation is None` -> `ValueError` ;
   `oos_evidence_validation_run_id` fourni mais introuvable/de mauvais `validation_type` -> `ValueError` ;
   AUCUN appel à un quelconque collaborateur d'exécution (aucun paramètre de ce type n'existe même dans
   la signature) ; **reproductibilité exacte** — deux appels avec les MÊMES entrées produisent des
   `expected_fold_ids` identiques (déterminisme de `compute_fold_definitions()`, déjà garanti par ADR
   0021) ; round-trip disque réel (`plan.json` écrit puis relu, tous les champs préservés) ; second
   appel avec le MÊME `campaign_id` refuse d'écraser (`FileExistsError` ou équivalent explicite) ;
   test d'import statique — `gate_v_campaign.py` n'importe JAMAIS `validation_oos`, aucune référence
   textuelle à `final_holdout`/`FINAL_HOLDOUT` dans son code source (Décision 10, TDD ligne dédiée
   Décision 13).

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- `GateVCampaignManifest`, le calcul du statut à 6 états (Décision 7) — tranche suivante (Slice 2).
- Tout Niveau B (`execute_gate_v_campaign()`, collaborateurs injectés, exécution réelle/factice) —
  Slices 3 à 6.
- Toute politique concrète de seuils PASS/FAIL — jamais inventée.
- Câblage Autopilot/script d'appel réel — hors scope de toute cette ADR (Décision 11).

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `gate_v_campaign.py` n'importe JAMAIS `engine.py`/`optimizer.py`/`validation_oos.py` — vérifié par
  un test d'import statique explicite. Import de `dataset_split.py`/`walk_forward.py`/
  `validation_run.py`/`research_run.py`/`atomic_json_store.py` autorisé (lecture de contrats/fonctions
  déjà existantes), jamais leur modification (voir `forbidden_paths` de la mission).
- `FINAL_HOLDOUT` jamais mentionné/consulté — ce module n'a structurellement aucun moyen d'y accéder.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète).
- Ne rien déclarer `PASS`/robuste — cette tranche ne produit aucune évidence, seulement la préparation.
- Aucune exécution réelle sur `nasdaq_3m.csv`, aucun backtest, aucune recherche `Optimizer`, aucun
  téléchargement, aucun accès `FINAL_HOLDOUT` — mission de câblage uniquement.
