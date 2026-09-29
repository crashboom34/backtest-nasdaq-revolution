# ADR 0025 — Gate V Validation Policy, Pre-Registration & Final Holdout V2

Status: Accepté — design validé, READY FOR IMPLEMENTATION, aucune implémentation encore
réalisée (2026-09-29)

**Contexte** : `AF-V-08` (ADR 0024) fournit l'orchestration de campagne `GATE V` — Walk-Forward,
Monte-Carlo, Parameter Stability, référence OOS — mais `scientific_verdict`/`verdict_reasons`
embarqués dans `WalkForwardEvidence`/`MonteCarloEvidence`/`ParameterStabilityEvidence` restent
structurellement `"INCONCLUSIVE"` en permanence : `build_gate_v_campaign_plan()` rejette tout
`*_verdict_policy_id` non-`None`, et `build_walk_forward_evidence()`/l'équivalent Monte-Carlo/
`_resolve_verdict()` (Parameter Stability) lèvent toutes `UnknownVerdictPolicy` pour tout id fourni
— aucune `ValidationPolicyVersion` réelle n'existe. `AF-V-07` ferme cet écart : définir COMMENT une
politique scientifique est identifiée, versionnée, figée AVANT observation des résultats, référence
les règles applicables, produit `PASS`/`FAIL`/`INCONCLUSIVE` de façon reproductible, reste
auditable, et ne modifie jamais rétroactivement les preuves historiques.

**Ticket** : `AF-V-07` — identifiant déjà réservé (ADR 0024 §Ticket), jamais réutilisé pour un
autre objet. **ADR** : `0025` — prochain numéro disponible (`0024` = orchestration GATE V, dernier
attribué).

**Processus de conception** : cette ADR formalise sept itérations de conception successives
(V1-V7), chacune close par une revue scientifique et architecture/reproductibilité adversariale
avant la suivante — voir `AI_HANDOFF.md` pour la trace complète de chaque itération. Seule la V7,
finale, sans BLOCKER/MAJOR restant, est normative ici. Un diagramme d'architecture (Figma/FigJam)
a accompagné chaque itération, référencé §Conséquences comme **document non normatif** — le texte
de cette ADR seul fait foi.

**Portée explicitement exclue** (aucune exception, aucune ambiguïté) : aucune campagne scientifique
réelle, aucun accès `FINAL_HOLDOUT` réel, aucune politique de promotion Champion (concept distinct,
`DOMAIN_MODEL.md` §13, `OPEN QUESTION` non tranchée ici), aucune valeur de seuil scientifique
concrète, aucun verdict `AF-V-07 V1` promu automatiquement en `GATE V = PASS`.

## Décision 1 — Six objets normatifs, jamais fusionnés

```
GateVValidationPolicyVersion   # définition de policy, source-contrôlée, immuable
GateVPreRegistration            # liaison protocole+policy, artefact runtime portable, immuable
GateVCampaignPlan V2            # extension versionnée de GateVCampaignPlan (ADR 0024), immuable
FinalHoldoutAccessClaim         # primitif d'exclusivité un-coup, immuable
ValidationAssessment            # interprétation scientifique d'UNE ValidationRun sous UNE policy
GateVPolicyAssessment           # composition AND stricte de tous les ValidationAssessment requis
```
Jamais `GateVVerdict` seul comme nom de l'artefact de composition — un `PASS` de policy n'est pas
la décision humaine/produit "`GATE V` a passé" (Décision 12).

## Décision 2 — Ordre scientifique obligatoire V2 : `FINAL_HOLDOUT` structurellement dernier

```
1. GateVValidationPolicyVersion déjà approuvée, immuable, committée (Décision 5/6)
2. GateVPreRegistration persistée — lie research_run + protocole complet + policy (Décision 8)
3. GateVCampaignPlan V2 construite ET persistée — AUCUNE evidence OOS observée à ce stade (Décision 3)
4. Walk-Forward exécuté
5. Monte-Carlo dérivé
6. Parameter Stability dérivé pour CHAQUE fold attendu
7. Confirmation : WF+MC+PS complets, aucun TECHNICAL_FAILURE
8. FinalHoldoutAccessClaim acquis en exclusivité (Décision 9-11) — un seul gagnant possible
9. FINAL_HOLDOUT consulté UNE SEULE FOIS
10. OOS ValidationRun + HoldoutAccessEvent canonique persistés (Décision 13)
11. ValidationAssessment produit pour OOS/WF/MC/chaque fold PS (Décision 14)
12. GateVPolicyAssessment composé (Décision 4/14)
13. Human Gate — décision distincte, jamais automatique (Décision 12)
```
Aucun `FINAL_HOLDOUT` avant l'étape 8. C'est la correction scientifique centrale de cette ADR par
rapport à l'ordre historique `AF-V-08` V1 (OOS potentiellement référencée dès la construction du
plan) : `DISCOVERY/TRAIN → validation/Walk-Forward → Monte-Carlo/Parameter Stability →
FINAL_HOLDOUT EN DERNIER` est désormais le contrat V2, jamais réinterprété rétroactivement sur V1.

## Décision 3 — `V1` historique : jamais réécrite

- Fichiers `GateVCampaignPlan` V1 existants restent chargeables tels quels, mêmes loaders.
- `campaign_id` V1 **bit-pour-bit inchangé** — la formule d'empreinte actuelle (`research_run_id`,
  `dataset_snapshot_id`, `split_plan_id`, `strategy_name`, `base_params`, `search_mode`,
  `search_space_hash`, `budget_per_fold`, spécification Walk-Forward, `readiness_spec`,
  `expected_fold_ids`, `expected_fold_definitions_hash`, `validation_zone_hash`,
  `split_plan_fingerprint`, versions sémantiques WF/MC/PS, `*_verdict_policy_id` (toujours `None`),
  référence/hash OOS) reste la SEULE formule pour tout plan sans `campaign_plan_semantics_version`
  explicite — aucune nouvelle clé n'est ajoutée au dictionnaire d'empreinte pour un appel V1.
- Le comportement OOS-first (OOS potentiellement référencée dès la construction du plan, ADR 0024
  Décision 9) reste un fait historique légitime, jamais interdit rétroactivement.
- **Aucun plan V1 n'est éligible à un `GateVPolicyAssessment PASS` `AF-V-07`** — `evaluate_gate_v_campaign()`
  refuse explicitement tout plan sans `campaign_plan_semantics_version = "gate_v_campaign_plan_v2"`.
- **Aucune promotion rétrospective en V1** — une évidence V1 ne devient jamais éligible V2 après
  coup, quelle que soit sa complétude structurelle.

## Décision 4 — `GateVValidationPolicyVersion` — contrat de policy

Immuable, git-trackée sous `validation_policies/<validation_policy_id>.json`, jamais de base de
données, jamais de moteur de règles, jamais de DSL.

- **Quatre familles obligatoires, fixes, non configurables** :
  ```python
  REQUIRED_VALIDATION_TYPES = ("oos", "walk_forward", "monte_carlo", "parameter_stability")
  ```
  Constante module, jamais un champ auteur — une policy ne peut en retirer aucune. Toute évolution
  future de cet ensemble exige une nouvelle `assessment_semantics_version` + un amendement ADR.
- **AND strict câblé dans l'évaluateur, jamais configurable par la policy** : `treatment_of_inconclusive`
  n'existe PAS comme champ de policy. Règle fixe : une FAIL → `FAIL` ; sinon une INCONCLUSIVE →
  `INCONCLUSIVE` ; sinon toutes PASS → `PASS`. Pour Parameter Stability, appliqué à travers TOUS
  les folds attendus — aucune moyenne, aucun vote, aucune pondération, aucune sélection du
  meilleur fold.
- **`pass_capable` dérivé uniquement**, jamais un champ persisté indépendant :
  ```
  pass_capable(policy) = all(len(policy.scientific_criteria.get(t, [])) > 0 for t in REQUIRED_VALIDATION_TYPES)
  ```
  L'éligibilité structurelle ne compte jamais comme critère scientifique.
- **Critères typés, jamais un mini-DSL** — enum fermé sur les champs réellement présents
  aujourd'hui dans `validation_run.py`, opérateur explicite, seuil fini explicite :
  ```python
  Operator = Literal[">", ">=", "<", "<=", "=="]

  class OosPolicyCriterion:
      metric: Literal["n_trades", "net_ret_pct", "profit_factor", "win_rate", "max_dd_pct"]
      operator: Operator; threshold: float

  class WalkForwardPolicyCriterion:
      metric: Literal["total_oos_trades", "oos_net_return_pct", "oos_max_dd_pct",
                        "oos_profit_factor", "oos_win_rate", "oos_sharpe"]  # AggregateResult réel
      operator: Operator; threshold: float

  class MonteCarloPolicyCriterion:
      distribution: Literal["sequence_risk_max_dd_trade_close_basis_pct",
                              "sequence_risk_longest_losing_streak",
                              "sampling_uncertainty_net_ret_pct",
                              "sampling_uncertainty_max_dd_trade_close_basis_pct"]
      percentile: Literal["p5", "p25", "p50", "p75", "p95"]  # PercentileDistributionSummary réel
      operator: Operator; threshold: float

  class ParameterStabilityPolicyCriterion:
      scope: Literal["ALL_USABLE_PARAMETERS", "WORST_CASE_PARAMETER"]  # jamais un nom de paramètre
      metric: Literal["degradation_by_param", "degradation_points_by_param"]
      operator: Operator; threshold: float
  ```
  Aucune expression exécutable, aucune chaîne interprétée, aucun chemin de champ arbitraire.
- **Policy strategy-agnostic en V1** — identité normative jamais liée à `strategy_name`/Perfect
  Revolution. Une policy strategy-spécifique future serait un contrat DISTINCT.
- **Aucune policy PASS-capable livrée par défaut** — le dépôt peut livrer schéma+évaluateur+tests
  sans commiter une seule valeur de seuil arbitraire. Une future policy concrète exige un Human
  Gate séparé, explicite, AVANT toute observation de l'évidence qu'elle jugera.
- **Champs legacy `walk_forward_verdict_policy_id`/`monte_carlo_verdict_policy_id`/
  `parameter_stability_verdict_policy_id`** (`WalkForwardSpecification`/`MonteCarloSpecification`/
  `ParameterStabilitySpecification`, ADR 0021/0022/0023) **restent historiques et DOIVENT rester
  `None`** sur le chemin `AF-V-07` V2 — `gate_v_campaign.py` ne leur transmet jamais de valeur
  réelle. La policy canonique vit exclusivement dans `ValidationAssessment`, jamais dans ces
  champs embarqués (voir Décision 18, supersession).

## Décision 5 — `policy_content_hash` : hash sémantique canonique, jamais un hash d'octets bruts

```
policy_content_hash = SHA256(canonical_json(contenu normatif de GateVValidationPolicyVersion))
canonical_json = json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
```
**Jamais** le hash des octets bruts du fichier (qui varierait avec l'indentation/l'ordre
d'écriture sans changement sémantique). À la `GateVPreRegistration` (Décision 8) : (1) récupérer
les octets COMMITTÉS via `git show <policy_git_sha>:validation_policies/<id>.json` ; (2) parser le
JSON ; (3) valider le schéma ; (4) reconstruire sa représentation canonique ; (5) recalculer
`policy_content_hash` ; (6) comparer strictement au hash attendu — échec fermé sinon. Le snapshot
portable (Décision 17) peut conserver les octets exacts du fichier committé pour l'audit, mais
cela reste distinct du hash sémantique canonique qui gouverne l'identité.

## Décision 6 — Provenance Git de la policy : fermée à l'échec, obligatoire

`policy_git_sha: str` — **non optionnel** sur `GateVPreRegistration` V2. Contrôles requis, TOUS
doivent réussir ou la construction refuse (aucun repli, aucun défaut inventé) :
1. Dépôt Git résolvable (réutilise le mécanisme déjà existant de `research_run.py`/
   `market_data.backtest_manifest._current_git_commit()`, jamais réimplémenté).
2. `validation_policies/<policy_id>.json` existe localement.
3. Le chemin est tracké par Git (`git ls-files --error-unmatch`, plomberie Git standard).
4. `policy_git_sha` = `HEAD` au moment de la préenregistrement.
5. Octets EXACTS committés récupérés via `git show <sha>:<path>` — **jamais** l'arbre de travail
   (immunise contre une édition locale non committée).
6. `policy_content_hash` (Décision 5) recalculé depuis ces octets committés et comparé strictement
   à la valeur attendue.

**Une policy modifiée uniquement dans le working tree ne peut jamais être utilisée
silencieusement.** Seuls les octets du fichier policy comptent — le reste du dépôt peut rester
sale sans conséquence (limite `ResearchRun.git_sha` préexistante et déjà documentée, explicitement
hors périmètre de cette ADR — `git show` contourne le problème pour le seul fichier qui compte
ici).

## Décision 7 — `campaign_protocol_fingerprint` : empreinte de protocole complète

```
campaign_protocol_fingerprint = SHA256(canonical_json({
    research_run_id, research_run_content_hash,
    dataset_snapshot_id, split_plan_id, split_plan_fingerprint,
    strategy_name, base_params, search_mode, search_space_hash, budget_per_fold,
    walk_forward_specification: {geometry, train_period, test_period, step_period,
                                   allow_partial_last_fold, position_transition_policy, master_seed},
    readiness_spec,
    expected_fold_ids, expected_fold_definitions_hash, validation_zone_hash,
    walk_forward_spec_semantics_version, monte_carlo_semantics_version, parameter_stability_semantics_version,
    gate_v_validation_policy_id, policy_content_hash, assessment_semantics_version,
    campaign_plan_semantics_version = "gate_v_campaign_plan_v2"
}))
```
```
research_run_content_hash = SHA256(canonical_json(dataclasses.asdict(research_run)))
```
`split_plan_fingerprint` = `dataset_split_plan_fingerprint()` (existante, réutilisée).
`expected_fold_ids`/`expected_fold_definitions_hash`/`validation_zone_hash` se dérivent de
`split_plan.validation`+`WalkForwardSpecification`+`readiness_spec` via `compute_fold_definitions()`
(fonction pure existante, réutilisée, ne nécessite pas l'objet plan). **Aucune evidence
`FINAL_HOLDOUT` observée dans cette empreinte** — elle est calculée AVANT que l'OOS n'existe.

**Une seule fonction canonique future** calcule cette empreinte — jamais deux implémentations
indépendantes dans `GateVPreRegistration` et `GateVCampaignPlan`. `GateVCampaignPlan` V2
recalcule cette MÊME formule depuis ses propres champs et exige l'égalité EXACTE avec ce que la
`GateVPreRegistration` référencée a déjà pinné — refus fail-closed sinon. **Graphe de dépendance
sans cycle** : `ResearchRun`/`DatasetSplitPlan`/`GateVValidationPolicyVersion` existent tous
indépendamment et avant toute préenregistrement ; direction unique (ResearchRun, DatasetSplitPlan,
Policy, paramètres bruts) → `campaign_protocol_fingerprint` → (PreRegistration le pinne) → (Plan V2
le reproduit + vérifie) → `campaign_id` V2 (étend encore avec `preregistration_id`).

## Décision 8 — `GateVPreRegistration` : liaison protocole+policy avant exécution

Immuable, artefact RUNTIME portable (pas source-contrôlé, voir Décision 17-19) :
```
GATE_V_PREREGISTRATION_SEMANTICS_VERSION = "gate_v_preregistration_v1"

scope_key                        # SHA256(canonical_json({research_run_id, dataset_snapshot_id, split_plan_id, strategy_name}))
preregistration_id               # SHA256(canonical_json({scope_key, campaign_protocol_fingerprint,
                                  #   research_run_id, research_run_content_hash, dataset_snapshot_id, split_plan_id, strategy_name,
                                  #   gate_v_validation_policy_id, policy_content_hash, policy_git_sha,
                                  #   assessment_semantics_version, preregistration_semantics_version}))
preregistration_content_hash     # SHA256(canonical_json({scope_key, preregistration_id, campaign_protocol_fingerprint,
                                  #   research_run_id, research_run_content_hash, dataset_snapshot_id, split_plan_id, strategy_name,
                                  #   gate_v_validation_policy_id, policy_content_hash, policy_git_sha,
                                  #   assessment_semantics_version, preregistration_semantics_version}))
                                  # preregistration_content_hash s'exclut lui-même de sa préimage ; created_at exclu des DEUX (audit seul).
campaign_protocol_fingerprint    # Décision 7
research_run_id
research_run_content_hash        # Décision 7
dataset_snapshot_id
split_plan_id
strategy_name
gate_v_validation_policy_id
policy_content_hash
policy_git_sha                   # Décision 6, non optionnel
assessment_semantics_version
preregistration_semantics_version = GATE_V_PREREGISTRATION_SEMANTICS_VERSION
created_at                       # audit seul, JAMAIS l'identité
```
**Pourquoi `research_run_content_hash` et `policy_git_sha` sont directement hashés** (et pas
seulement transitifs) : `research_run_content_hash` participe déjà transitivement via
`campaign_protocol_fingerprint`, mais reste aussi un champ normatif persisté de `GateVPreRegistration`
— `preregistration_content_hash` doit représenter l'artefact persisté réel, pas seulement un
sous-ensemble transitif. `policy_git_sha` est une provenance obligatoire qui ne fait PAS partie de
`campaign_protocol_fingerprint` (Décision 7) — il doit donc être directement lié à
`preregistration_id`/`preregistration_content_hash`, sinon une `GateVPreRegistration` persistée
pourrait changer sa provenance Git tout en conservant le même hash de contenu.

**Unicité par scope scientifique** : stockage keyé par `scope_key` (jamais par `preregistration_id`,
qui inclut la policy et permettrait sinon à deux policies différentes de coexister pour le même
scope). Écriture protégée par refus d'écrasement — une SECONDE préenregistrement pour le MÊME
scope (quelle que soit sa policy) entre en collision sur le MÊME chemin et est refusée. **Un
`ResearchRun` scientifique = une seule policy/protocole actifs.** Changer de policy OU de protocole
après coup exige un NOUVEAU `ResearchRun` avant tout `FINAL_HOLDOUT` — jamais une sélection après
observation de l'évidence.

**Intégrité `ResearchRun`** : `research_run_content_hash` calculé depuis le `research_run.json`
réel chargé (`load_research_run()`, réutilisée) — même `research_run_id` mais contenu différent →
hash différent → échec fermé, jamais une confiance sur le seul id.

## Décision 9 — `FinalHoldoutAccessClaim` : primitif exclusif un-coup

**Correctif BLOCKER, revue architecture** : `save_atomic()`/`save_atomic_overwrite()`
(`atomic_json_store.py`) garantissent une écriture complète de fichier (fichier temporaire +
`os.replace()`) mais **PAS l'exclusivité entre processus** — `save_atomic()` documente lui-même ne
"pas résoudre entièrement le TOCTOU inhérent au contrôle `target.is_file()`". Un simple booléen
mutable sur `GateVCampaignManifest` (écrasable par `save_atomic_overwrite()`, sans contrôle
d'existence) ne peut structurellement pas garantir qu'un seul processus accède à `FINAL_HOLDOUT`.

**Primitif retenu** : création exclusive atomique au niveau système de fichiers.
```
os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
```
Un seul appel système indivisible — jamais `if not path.exists(): write()` (même TOCTOU que
`save_atomic()`), jamais `save_atomic_overwrite()`, jamais `GateVCampaignManifest` comme verrou.
Portable Windows (`CreateFileW(..., CREATE_NEW, ...)`, garanti au niveau du pilote NTFS) et POSIX
(`open(2)` natif `O_EXCL`, garanti par le noyau).

**Support filesystem ciblé V1** : filesystem local Windows compatible, filesystem local Linux
compatible, filesystem bloc/persistant OCI **seulement si cette propriété est garantie/testée**.
Un futur stockage distribué/NFS/object-store dont la sémantique d'exclusivité n'est pas vérifiée
**ne doit jamais être supposé compatible**. Un futur backend distribué pourrait remplacer ce
primitif par une transaction DB/un verrou distribué/une création conditionnelle d'objet — hors
périmètre V1.

## Décision 10 — Identité et hash du claim, sans cycle

```
FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION = "final_holdout_access_claim_v1"

claim_id = SHA256(canonical_json({
    campaign_id, preregistration_id, preregistration_content_hash,
    campaign_protocol_fingerprint, research_run_id, research_run_content_hash,
    dataset_snapshot_id, split_plan_id, split_plan_fingerprint,
    assessment_semantics_version, claim_semantics_version
}))

claim_content_hash = SHA256(canonical_json({
    claim_id,
    campaign_id, preregistration_id, preregistration_content_hash,
    campaign_protocol_fingerprint, research_run_id, research_run_content_hash,
    dataset_snapshot_id, split_plan_id, split_plan_fingerprint,
    assessment_semantics_version, claim_semantics_version
}))   # claim_content_hash EXCLU de sa propre préimage — aucune définition récursive/circulaire
```
`created_at` explicitement exclu des deux. Stockage : `<campaign_dir>/final_holdout_access_claim.json`
— chemin déjà scopé par `campaign_id`, un seul claim valide possible par campagne.

## Décision 11 — Acquisition, course entre processus, matrice de crash

**Séquence obligatoire, avant tout appel à `run_backtest_fn`** :
1. Plan V2 persisté chargé et vérifié (empreinte, Décision 7).
2. Préenregistrement chargée et validée.
3. Walk-Forward, Monte-Carlo, Parameter Stability (tous folds) confirmés complets.
4. Aucun `TECHNICAL_FAILURE`.
5. `FinalHoldoutAccessClaim` déterministe construit (pure fonction des données déjà validées).
6. Tentative de création exclusive (Décision 9) au chemin du claim.
7. Échec (`FileExistsError`) → **échec fermé immédiat** — jamais d'inspection du détenteur
   existant, jamais de décision de retry automatique, quelle que soit la raison suspectée.
8. Succès → rechargement immédiat depuis le disque, contenu vérifié identique à l'écriture voulue.
9. Seulement alors : délégation à `run_oos_validation()` (existante, inchangée).

**Deux processus simultanés — argument d'atomicité concret** : `O_CREAT|O_EXCL` est une opération
indivisible unique au niveau noyau/pilote sur l'entrée de répertoire, garantie par POSIX pour
`O_EXCL` et par `CreateFileW(CREATE_NEW)` sous Windows — aucune fenêtre "vérifier-puis-créer"
exposée à l'espace utilisateur. Exactement un appel réussit ; l'autre reçoit `FileExistsError`
avant tout accès marché, de façon synchrone et déterministe.

**Matrice de crash** :

| Cas | Conséquence |
|---|---|
| Crash avant création du claim | Sûr — nouvelle tentative complète d'acquisition |
| Claim créé, crash avant lecture marché | Consommé pour toujours, aucun retry (règle scientifique conservatrice : incertitude sur la consommation réelle des données marché → traité comme consommé) |
| Crash pendant `FINAL_HOLDOUT` | Consommé, `TECHNICAL_FAILURE`, aucun retry |
| Crash après résultat, avant persistance complète | Consommé, récupération manuelle uniquement depuis des octets déjà durables, jamais une relecture du holdout |
| Claim corrompu/malformé | Fail closed — **jamais** traité comme absent |
| Claim supprimé manuellement | Risque de gouvernance/destruction externe explicite, non fermable par le code seul |

## Décision 12 — `GateVPolicyAssessment` ≠ Human Gate

`GateVPolicyAssessment.verdict == "PASS"` signifie **uniquement** : "les preuves immuables
satisfont la policy scientifique pré-enregistrée." Cela ne signifie **pas** automatiquement
`GATE V = PASS`, et ne peut jamais : promouvoir un Champion, modifier automatiquement la roadmap,
déclencher un accès réel/live, accéder de nouveau au holdout. `GateVCampaignManifest` n'est jamais
muté vers PASS/FAIL — ses statuts structurels (ADR 0024 Décision 7) restent exactement ce qu'ils
sont aujourd'hui. La décision Human Gate reste distincte, séparée, jamais automatique (ADR 0024
Décision 15, inchangée).

## Décision 13 — `HoldoutAccessEvent` V2 : extension additive, un seul événement canonique

Extension rétrocompatible (champs optionnels, événements légataires restent lisibles) :
```
gate_v_preregistration_id: Optional[str] = None
gate_v_preregistration_content_hash: Optional[str] = None
campaign_id: Optional[str] = None
final_holdout_claim_id: Optional[str] = None

holdout_access_event_content_hash = SHA256(canonical_json({
    event_id, campaign_id, final_holdout_claim_id,
    split_plan_id, dataset_snapshot_id, research_run_id, reason, locked_state,
    accessed_at, validation_run_id, gate_v_preregistration_id, gate_v_preregistration_content_hash
}))
```
`run_oos_validation()` reste **inchangée**. Un nouveau wrapper additif `run_gate_v_final_holdout_validation(...)`
exécute la séquence de la Décision 11, puis, sur retour réussi, construit l'UNIQUE `HoldoutAccessEvent`
canonique et persiste la `ValidationRun` OOS immuablement — **jamais** un événement générique PUIS
un second enrichi pour un seul accès physique. `GateVCampaignManifest` gagne `final_holdout_claim_id`/
`final_holdout_claim_content_hash`/`holdout_access_event_id`/`holdout_access_event_content_hash`/
`oos_evidence_validation_run_id` (V2, transition `None→id` une seule fois, symétrique à WF/MC/PS) —
un **miroir de référence pour l'audit uniquement**, jamais l'autorité d'exclusivité elle-même
(Décision 9).

## Décision 14 — `ValidationAssessment`/`GateVPolicyAssessment` : contrats exacts

```
ValidationAssessmentResult   # PUR, déterministe, AUCUN horodatage
    assessment_id = SHA256(canonical_json({validation_run_id, validation_run_content_hash,
                             validation_policy_id, policy_content_hash, assessment_semantics_version}))
    assessment_content_hash = SHA256(canonical_json(dataclasses.asdict(ValidationAssessmentResult)))
    validation_run_id, validation_run_content_hash, validation_type,
    validation_policy_id, policy_content_hash, assessment_semantics_version,
    evaluated_evidence_semantics_version, verdict, reasons

ValidationAssessment         # enveloppe de PERSISTANCE
    result: ValidationAssessmentResult
    created_at: str           # exclu de assessment_content_hash

GateVPolicyAssessment
    gate_v_policy_assessment_id = SHA256(canonical_json({campaign_id, preregistration_id,
        gate_v_validation_policy_id, policy_content_hash, assessment_semantics_version,
        ordered_child_assessment_ids}))
    gate_v_policy_assessment_content_hash = SHA256(canonical_json({...tout ce qui précède...,
        holdout_access_event_id, holdout_access_event_content_hash,
        preregistration_content_hash, verdict, reasons, ordered_child_assessment_content_hashes}))
```
**Ordre canonique des enfants** : OOS, puis Walk-Forward, puis Monte-Carlo, puis Parameter
Stability dans l'ordre EXACT de `plan.expected_fold_ids` — jamais l'ordre du système de fichiers,
jamais l'ordre d'insertion d'un dict. Participe à l'identité/hash de `GateVPolicyAssessment`.

`evaluate_validation_run()`/`evaluate_gate_v_campaign()` restent **vraiment déterministes** —
aucun `datetime.now()`/uuid à l'intérieur. La couche GATE V (impure) vérifie l'éligibilité de
l'evidence OOS (liaison valide à un `HoldoutAccessEvent` canonique) AVANT de transmettre la source
déjà vérifiée à l'évaluateur pur — jamais d'E/S cachée dans l'évaluateur, jamais un signature
spéciale pour un seul type de validation.

**Sémantique métrique indisponible/nulle, taxonomie à 5 niveaux** :
```
STRUCTURAL INVALID      -> évaluation refusée (raise), jamais un verdict
STRUCTURAL INCOMPLETE   -> aucun assessment produit
SCIENTIFIC INCONCLUSIVE -> métrique requise None/absente/non-finie -> INCONCLUSIVE + raison structurée
SCIENTIFIC FAIL         -> métrique disponible, finie, comparaison fausse
SCIENTIFIC PASS         -> métrique disponible, finie, comparaison vraie, pour TOUS les critères requis
```
**Aucun `ValidationRun` historique jamais réécrit.** Aucune réévaluation rétrospective générale en
V1 (capacité explicitement FUTURE, hors périmètre).

## Décision 15 — Parameter Stability : critère générique, agnostique de stratégie

`scope: Literal["ALL_USABLE_PARAMETERS", "WORST_CASE_PARAMETER"]` (Décision 4) — aucun nom de
paramètre Perfect Revolution ou autre dans la policy V1. `ALL_USABLE_PARAMETERS` : le critère doit
tenir pour CHAQUE paramètre usable (`n_neighbors_total_by_param[p] - n_neighbors_rejected_by_param[p] > 0`).
`WORST_CASE_PARAMETER` : évalué contre le paramètre usable le plus défavorable — conservateur par
construction. AND appliqué à travers tous les folds attendus (Décision 4) — aucune moyenne, aucun
vote, aucun best-fold.

## Décision 16 — Emplacement portable canonique

```
results/job_xxx/
    research_run.json                       # convention existante, job_store.write_research_run()
    gate_v/
        preregistrations/<scope_key>.json
        policies/<validation_policy_id>.json   # snapshot portable, Décision 17
        campaigns/<campaign_id>/
            plan.json
            manifest.json
            final_holdout_access_claim.json
            validations/
            assessments/
            gate_v_policy_assessment.json
```
`validation_policies/<validation_policy_id>.json` reste séparée, source-contrôlée (Décision 4-6).
Aucun répertoire de job historique déplacé ni réécrit. `save_research_run()`/`save_dataset_split_plan()`/
`save_validation_run()` ne résolvent jamais leur propre répertoire (principe déjà établi) — le
nouveau code suit la même discipline, chemin toujours fourni par l'appelant réel.

## Décision 17 — Snapshot de policy portable

`results/job_xxx/gate_v/policies/<validation_policy_id>.json` (chemin multi-policy-safe, préféré à
un unique `policy_snapshot.json`, pour la compatibilité future multi-stratégies/multi-campagnes) :
copie exacte des octets du blob Git committé, `policy_git_sha` enregistré, hash canonique
(Décision 5) vérifié à la copie — **audit/portabilité uniquement, jamais une source mutable de
vérité**. `validation_policies/<id>.json` git-trackée reste seule canonique.

## Décision 18 — Supersession explicite, jamais une contradiction silencieuse

> **L'ADR AF-V-07 (0025) remplace (supersession) la portion de l'ADR 0021 Décision 13 / ADR 0022 /
> ADR 0023 Décision 12 qui désignait `scientific_verdict` embarqué comme futur point d'extension
> pour une politique réelle — sans changer aucun comportement runtime existant, sans réécrire
> aucun artefact déjà persisté.** `scientific_verdict` embarqué reste structurellement
> `"INCONCLUSIVE"` en permanence dans ce dépôt (`build_gate_v_campaign_plan()` continue de rejeter
> tout `*_verdict_policy_id` réel, Décision 4) ; `ValidationAssessment` (ADR 0025) est désormais
> l'artefact canonique de verdict scientifique GATE V.

## Décision 19 — Amendement ADR 0024

`ADR 0024` reste la source normative de l'orchestration structurelle GATE V (Niveau A/B,
`GateVCampaignManifest`, 6 états factuels, jamais `PASS`). Amendement : l'architecture V1
OOS-first (Décision 9 de l'ADR 0024) reste vraie historiquement et inchangée ; **`AF-V-07`/ADR 0025
la remplace pour toute NOUVELLE campagne scientifique V2, avec `FINAL_HOLDOUT` structurellement
dernier** (Décision 2 ci-dessus) ; V1 et V2 coexistent pour la rétrocompatibilité, jamais l'un ne
réinterprète l'autre ; `GateVCampaignPlan` gagne la sémantique V2 (`campaign_plan_semantics_version`) ;
`GateVCampaignManifest` gagne les champs V2 additifs (Décision 13) mais n'est jamais lui-même le
verrou d'exclusivité (Décision 9) ; aucun retry automatique après un `FinalHoldoutAccessClaim`
réussi (Décision 11) ; `GateVPolicyAssessment` ≠ Human Gate (Décision 12, cohérent avec ADR 0024
Décision 15, inchangée).

## Conséquences

- **État réel** : `AF-V-07` = **DESIGN ACCEPTED / READY FOR IMPLEMENTATION** (2026-09-29). Aucune
  ligne de code Python, aucun test, aucune campagne réelle, aucun accès `FINAL_HOLDOUT` n'a été
  produit par ce processus de conception. `AF-V-08` (ADR 0024) reste `DONE`, intégrée dans
  `master`. **`GATE V` reste NON PASSÉE** — aucune décision de cette ADR ne produit ni ne peut
  produire un verdict `PASS`/Champion.
- **Documents de conception non normatifs, référencés pour traçabilité uniquement** : diagrammes
  Figma/FigJam produits au fil des itérations V1-V7 (dernier, V7 : `https://www.figma.com/board/tbncsrWhuFng8HF0QDKKD1`)
  — visualisent la frontière source-contrôlée/portable, la chaîne d'immutabilité pré-holdout, le
  marqueur d'exclusivité et la course entre deux workers, et la séparation `GateVPolicyAssessment`/
  Human Gate. **Le texte de cette ADR seul fait foi en cas de divergence.**
- **Dépendance explicite sur une future policy concrète** (valeurs de seuils réelles, hors
  périmètre de cette ADR, Human Gate séparé) et sur `AF-V-07` implémentée + testée avant qu'un
  premier `GateVPolicyAssessment` réel puisse exister.
- **Aucun risque de régression sur `AF-V-08`** : cette ADR n'exige la modification d'aucun module
  gelé (`walk_forward.py`, `monte_carlo.py`, `parameter_stability.py`, `validation_run.py`,
  `validation_oos.py` restent inchangés dans leur comportement runtime existant) — toute
  l'extension est additive (nouveaux fichiers, nouveaux champs optionnels, un nouveau wrapper).
- **Points restant à valider explicitement par l'utilisateur avant implémentation** : aucun
  désaccord matériel identifié à ce stade — sept itérations de revue adversariale (scientifique et
  architecture/reproductibilité) n'ont laissé aucun BLOCKER/MAJOR ouvert. Trois questions
  mineures, non bloquantes pour le début de l'implémentation, restent à reconfirmer en cours de
  route : convention exacte de nommage sous `results/job_xxx/gate_v/` contre un orchestrateur réel
  non encore inspecté ; contenu réel d'une future policy concrète (hors périmètre par
  construction) ; politique opérationnelle exacte de reprise manuelle après un crash mi-vol
  pendant l'unique accès holdout (décision humaine, pas technique).
