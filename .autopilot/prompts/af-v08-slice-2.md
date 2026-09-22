# Mission AF-V-08 Slice 2 — Contrat `GateVCampaignManifest` + calcul pur du statut à 6 états (ADR 0024 Décisions 4/6/7)

**Lire intégralement `docs/adr/0024-gate-v-campaign-orchestration-v1.md` avant de commencer,
notamment les Décisions 4, 6 et 7 (état `EVIDENCE_COMPLETE_AWAITING_POLICY`/Parameter Stability,
corrigées en revue — lire le paragraphe "deux conditions CUMULATIVES" de la Décision 6 et le
paragraphe "Portée exacte" ajouté à la Décision 7 avec la plus grande attention : c'est le cœur
scientifique de cette tranche).** AF-V-08 Slice 1 (contrats `GateVCampaignPlan` + Niveau A) est
terminée et poussée — NE PAS la modifier, réutiliser telle quelle.

## Ce qui est DANS cette tranche

Ajouts à `gate_v_campaign.py` (même module, Slice 1 non modifiée) :

1. **`GateVCampaignManifest`** (dataclass mutable de façon contrôlée — Décision 4, jamais un champ
   supplémentaire non prévu par l'ADR) — champs exacts, synthétisés depuis les Décisions 2/4/7 :
   - `campaign_id: str`, `expected_fold_ids: Tuple[str, ...]` (copié du plan à la construction
     initiale du manifeste, jamais recalculé).
   - `status: str` — une des 6 valeurs EXACTES de la Décision 7, jamais une septième inventée :
     `"NOT_READY"`, `"READY_FOR_EXECUTION"`, `"RUNNING"`, `"EVIDENCE_INCOMPLETE"`,
     `"EVIDENCE_COMPLETE_AWAITING_POLICY"`, `"TECHNICAL_FAILURE"`.
   - `oos_evidence_validation_run_id: Optional[str]` — copié du plan (Décision 2, RÉFÉRENCE jamais
     générée par la campagne).
   - `walk_forward_validation_run_id: Optional[str] = None`, `monte_carlo_validation_run_id: Optional[str] = None`
     — assignés à l'exécution (Décision 2, Slices 3/4 — cette tranche ne les peuple jamais elle-même).
   - `parameter_stability_validation_run_ids_by_fold: Dict[str, str] = field(default_factory=dict)`
     — `fold_id -> validation_run_id`, un par fold ATTENDU (Décision 2/6, Slice 5).

2. **`derive_gate_v_campaign_status(manifest_facts, *, walk_forward_complete: bool, monte_carlo_complete: bool, parameter_stability_evidence_by_fold: Dict[str, "ParameterStabilityQualityFacts"], expected_fold_ids: Tuple[str, ...], oos_evidence_present: bool) -> str`**
   — fonction PURE, SANS AUCUN accès disque/réseau (Décision 6/7), séparée du reste de l'orchestration
   pour être testable isolément avec des faits synthétiques (aucune `ValidationRun` réelle nécessaire
   dans cette tranche) :
   - Retourne `"EVIDENCE_INCOMPLETE"` si `oos_evidence_present` est `False`, OU
     `walk_forward_complete` est `False`, OU `monte_carlo_complete` est `False`, OU
     `len(parameter_stability_evidence_by_fold) < len(expected_fold_ids)`.
   - **Retourne `"EVIDENCE_INCOMPLETE"` (jamais `"EVIDENCE_COMPLETE_AWAITING_POLICY"`) si au moins UN
     fold de `parameter_stability_evidence_by_fold` ne satisfait pas la condition de qualité ADR 0023
     Décision 3 — CORRECTIF MAJEUR de la revue scientifique, le cœur de cette tranche** : pour CHAQUE
     fold, exige CUMULATIVEMENT (a) `neighborhood_applicability == "local_neighborhood_available"`
     ET (b) au moins un paramètre avec `n_neighbors_total_by_param[param] - n_neighbors_rejected_by_param[param] > 0`.
     Modélise ces faits par petite structure `ParameterStabilityQualityFacts` (dataclass locale à
     `gate_v_campaign.py`, PAS `ParameterStabilityEvidence` complet — seulement les 3 champs
     nécessaires à ce calcul : `neighborhood_applicability: str`,
     `n_neighbors_total_by_param: Dict[str, int]`, `n_neighbors_rejected_by_param: Dict[str, int]` —
     les tranches suivantes (Slice 5) construiront ces faits à partir d'une vraie
     `ParameterStabilityEvidence`, cette tranche ne le fait pas elle-même).
   - Retourne `"EVIDENCE_COMPLETE_AWAITING_POLICY"` UNIQUEMENT si TOUTES les conditions ci-dessus sont
     satisfaites (les 4 catégories de preuve RÉELLEMENT complètes ET chaque fold Parameter Stability
     satisfait la condition de qualité).
   - **Ne contient AUCUNE logique dérivant un état depuis `scientific_verdict`** — la fonction ne
     reçoit et ne compare JAMAIS un `scientific_verdict`/`PASS`/`FAIL` (Décision 7, "aucun code de ce
     module ne compare `scientific_verdict` à quoi que ce soit pour en dériver un état de campagne").
   - `RUNNING`/`NOT_READY`/`TECHNICAL_FAILURE` restent des états ASSIGNÉS DIRECTEMENT par l'orchestrateur
     (Slices 3-6), jamais dérivés par cette fonction — documenter ce choix explicitement dans le
     docstring de la fonction (elle ne calcule QUE la distinction `EVIDENCE_INCOMPLETE` vs
     `EVIDENCE_COMPLETE_AWAITING_POLICY`, les 4 autres états relèvent du contrôle de flux de Niveau B).

3. Tests TDD (RED confirmé avant implémentation), au minimum : chacun des 6 états testé
   individuellement pour sa condition de déclenchement exacte ; **test explicite avec un fold
   `neighborhood_applicability="global_correlation_only"`** -> `EVIDENCE_INCOMPLETE` malgré
   `len(...) == len(expected_fold_ids)` ; **test explicite avec un fold
   `neighborhood_applicability="local_neighborhood_available"` mais `n_neighbors_total_by_param`
   tous égaux à `n_neighbors_rejected_by_param`** (zéro voisin exploitable net) ->
   `EVIDENCE_INCOMPLETE` ; test avec TOUS les folds qualifiants -> `EVIDENCE_COMPLETE_AWAITING_POLICY` ;
   `status` ne contient JAMAIS la sous-chaîne `"PASS"` — test de présence exhaustive des 6 valeurs
   autorisées uniquement ; test round-trip disque du manifeste (`save_atomic()`/relecture, tous les
   champs préservés, y compris `parameter_stability_validation_run_ids_by_fold` avec plusieurs
   entrées).

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- Toute exécution réelle/factice (`execute_gate_v_campaign()`, collaborateurs injectés) — Slices 3-6.
- La construction d'une vraie `ParameterStabilityQualityFacts` depuis une vraie `ParameterStabilityEvidence`
  produite par `parameter_stability.analyze_parameter_stability()` — Slice 5 (cette tranche ne teste
  que la fonction de dérivation de statut avec des faits synthétiques construits à la main).
- La logique de reprise/persistance atomique du manifeste après chaque étape (Décision 8) — Slice 3
  introduit la première écriture réelle du manifeste pendant une exécution.
- Toute politique concrète de seuils PASS/FAIL — jamais inventée.

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `derive_gate_v_campaign_status()` reste une fonction PURE (aucun accès disque/réseau) — testable
  entièrement avec des données synthétiques en mémoire.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète,
  y compris tous les tests de Slice 1, jamais modifiés).
- Ne rien déclarer `PASS`/robuste.
