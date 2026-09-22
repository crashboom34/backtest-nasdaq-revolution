# Mission AF-V-04 Slice 2 — Algorithme `parameter_stability.py` (voisinage, dégradation, ADR 0023)

**Lire intégralement `docs/adr/0023-parameter-stability-plateau-v1.md`** (déjà revue trois passes/
corrigée/committée, `ca321f1`) avant de commencer — cette mission implémente STRICTEMENT ses
Décisions 1 à 10/13/14. AF-V-04 Slice 1 (contrats typés) est terminée et poussée — NE PAS la
modifier, réutiliser telle quelle.

## Ce qui est DANS cette tranche

Nouveau module top-level `parameter_stability.py` (Décision 11 de l'ADR : jamais dans
`validation_run.py`, jamais dans `scoring.py` — **aucun import `engine.py`/`optimizer.py`/
`dataset_split.py`/`walk_forward.py`, y compris pour une seule constante** (même invariant "leaf"
que Slice 1, Décision 9/11 de l'ADR — `search_mode` reçu tel quel dans `spec`, déjà validé par
`build_parameter_stability_specification()` en amont, jamais revalidé contre une constante importée
ici) — **seul import externe autorisé : `scoring.compute_sensitivity_filtered`/
`compute_sensitivity_correlation`** (Décision 2/10 de l'ADR, `scoring.py` est déjà un module de
calcul pur sans dépendance moteur, vérifié par la revue architecture indépendante) :

1. **`analyze_parameter_stability(candidates: Tuple[dict, ...], best_params: dict, spec: ParameterStabilitySpecification) -> ParameterStabilityEvidence`**
   — fonction pure, orchestre l'ensemble :
   - `n_candidates_total = len(candidates)`. Si `== 0` : retourne directement une
     `ParameterStabilityEvidence` avec `zero_candidates_input=True`, TOUS les champs `Optional[...]`
     `None`/vides, les compteurs (`n_neighbors_total_by_param`, etc.) à `{}`/`0`,
     `execution_status="completed"` (Décision 7 de l'ADR) — jamais une exception.
   - Si `n_candidates_total > 0` mais `best_params` n'apparaît dans AUCUN candidat du pool
     (égalité stricte de `dict`, Décision 9 de l'ADR) : `ValueError` immédiat.
   - `sensitivity`/`sensitivity_sample_size_by_param` : appelle `scoring.compute_sensitivity_filtered()`
     (modes `"single_var"`/`"cross_zone"`/`"grid"`) ou `compute_sensitivity_correlation()` (mode
     `"general"`) selon `spec.search_mode` — RÉUTILISE TELLES QUELLES, jamais réimplémentées.
     `sensitivity_sample_size_by_param` : COMPTE-SEUL (mêmes critères EXACTS que ces fonctions —
     lire leur code source avant d'implémenter ce comptage, `scoring.py` lignes ~367-415 — jamais
     une réimplémentation du calcul de sensibilité lui-même).
   - `neighborhood_applicability` : `"local_neighborhood_available"` si `spec.search_mode` ∈
     `{"single_var", "cross_zone", "grid"}`, `"global_correlation_only"` si `"general"` — valeurs
     LITTÉRALES dupliquées localement (mirroring Slice 1, jamais un import `optimizer.py`).
   - **Filtre de voisinage par paramètre (Décision 2 de l'ADR — lire attentivement, DIFFÉRENT du
     filtre de `compute_sensitivity_filtered()` sur la clause de score)** : pour chaque paramètre
     actif (déduit des clés de `best_params`), un candidat est un voisin structurel si (i) mêmes
     CLÉS que `best_params` exactement, (ii) tous les autres paramètres égaux à `best_params`, (iii)
     n'est PAS `best_params` lui-même — **AUCUNE exclusion sur le score**. Calcule
     `n_neighbors_total_by_param`/`n_neighbors_rejected_by_param` (`score <= 0`) séparément ;
     `degradation_by_param`/`degradation_points_by_param` UNIQUEMENT sur les voisins non rejetés
     (`(best_score - neighbor_score) / abs(best_score)` si `best_score != 0` sinon `None`, ET le
     delta absolu `best_score - neighbor_score` — les deux, jamais un seul).
   - **Statistique jointe Hamming `1 <= d <= 2`** (Décision 2/6 de l'ADR, JAMAIS `d=0` — `best_params`
     lui-même exclu) : `n_hamming_le_2_total`/`n_hamming_le_2_rejected` séparés,
     `degradation_hamming_le_2` sur les non-rejetés uniquement, tous paramètres confondus.
   - `observed`/`best_score`/`best_params` : rapportés tels quels.
   - `scientific_verdict`/`verdict_reasons`/`execution_status` : `"completed"` toujours (Décision 11
     de l'ADR) ; `spec.verdict_policy_id is None` -> `"INCONCLUSIVE"` avec raison explicite ;
     `spec.verdict_policy_id` fourni -> lève `validation_run.UnknownVerdictPolicy` (réutilisée
     TELLE QUELLE, jamais une classe dupliquée).
2. Tests TDD (RED confirmé avant implémentation) — reprendre PRÉCISÉMENT la matrice de la Décision
   13 de l'ADR (déterminisme bit-à-bit à séquence fixée, `sensitivity` byte-identique à un appel
   direct de `scoring.py`, sentinel `sensitivity`/`sensitivity_sample_size_by_param` correctement
   distingué, filtre de voisinage JAMAIS identique à la clause de score de
   `compute_sensitivity_filtered()` — test explicite avec des voisins À LA FOIS acceptés et rejetés,
   `best_params` exclu de son propre voisinage PAR PARAMÈTRE ET PAR HAMMING, clés de paramètres
   exactes, dégradation correctement signée y compris le cas d'un `best_params` sélectionné selon un
   critère externe différent du score — voir la nuance de la Décision 1 de l'ADR,
   `degradation_hamming_le_2` distinct de l'analyse par paramètre avec ses propres compteurs,
   `search_mode="general"` vs déterministe -> `neighborhood_applicability` correct,
   `n_candidates_total == 0`, `best_params` absent du pool -> `ValueError`, `search_mode` invalide
   -> `ValueError`, `verdict_policy_id` None/fourni, round-trip disque complet, fingerprint,
   aucune dépendance moteur — test d'import statique, aucun accès holdout).
3. **Test de cohérence obligatoire avec un run Walk-Forward réel** (Décision 13 de l'ADR) : sur
   `train_candidates.csv` d'un fold Walk-Forward réel (mirroring les fixtures de
   `tests/test_walk_forward.py`), `analyze_parameter_stability()` produit un `sensitivity`/
   `degradation_by_param` cohérent avec les paramètres réellement variés dans ce fold.
4. Régression complète (`tests/test_validation_run.py`, nouveau `tests/test_parameter_stability.py`)
   reste 100 % verte, aucune modification des Slices AF-V-02/AF-V-03/AF-V-04 Slice 1 déjà en place.

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- Persistance disque (`manifest.json`/`evidence.json` sous `results/job_xxx/parameter_stability/`,
  Décision 8 de l'ADR) — tranche suivante si jugée nécessaire séparément, ou combinée si la mission
  juge le périmètre proportionné une fois l'algorithme terminé (à documenter le choix si combiné,
  même précédent que Slice 2 d'AF-V-03).
- Tout appelant réel produisant un pool de candidats pour Parameter Stability (câblage OOS/
  Walk-Forward/`Optimizer.run()`) — hors scope, `candidates` reste un paramètre fourni par
  l'appelant, jamais recalculé ici.
- Toute politique concrète de seuils PASS/FAIL — jamais inventée.
- `n_simulations`/graine — n'existent PAS dans ce protocole (Décision 4/5 de l'ADR), ne jamais en
  inventer un par mimétisme avec Monte-Carlo.

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict (RED confirmé avant l'implémentation).
- `parameter_stability.py` reste un leaf sans dépendance moteur NI `optimizer.py` — vérifié par un
  test d'import statique explicite couvrant les DEUX (`engine`/`optimizer`/`dataset_split`/
  `walk_forward` tous exclus, `scoring` seul autorisé en plus de `validation_run`).
- `FINAL_HOLDOUT` jamais mentionné/consulté — ce module n'a structurellement aucun moyen d'y accéder.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète).
- Ne rien déclarer `PASS`/robuste — le verdict reste structurellement `INCONCLUSIVE` sans politique.
