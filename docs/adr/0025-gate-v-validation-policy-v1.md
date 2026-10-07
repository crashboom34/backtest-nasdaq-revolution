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
**Amendement additif (Décision 21.8, 2026-10-06)** : le répertoire de campagne V2 gagne
`technical_failure.json`, sentinelle exclusive d'échec technique (absente tant qu'aucun échec n'a
eu lieu), et `manifest.update.lock`, verrou **transitoire** de mise à jour du Manifest (présent
uniquement pendant une transaction, ou résiduel après un état d'écriture incertain ; **jamais** un
`FinalHoldoutAccessClaim`) ; aucune autre entrée de cette arborescence n'est modifiée.
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

## Décision 20 — `GateVCampaignPlan V2` : contrat exact (verrouillé avant TDD, 2026-09-29)

**Contexte** : `AF-V-07` Slice A (`GateVValidationPolicyVersion`) et Slice B (`GateVPreRegistration`)
sont `INTEGRATED` dans `master`. Avant tout code Slice C, cette Décision ferme l'ambiguïté
normative restante identifiée en préparation de Slice C : la formule exacte de `campaign_id` V2
n'était pas explicite (Décision 7 disait seulement "étend encore avec `preregistration_id`").

### 20.1 — Formule V1 réelle, confirmée inchangée, jamais retouchée

Le `campaign_id` V1 (`gate_v_campaign.py::build_gate_v_campaign_plan()`) reste
**bit-pour-bit identique**, formule et code non modifiés :
```
campaign_id_v1 = "gate_v_" + SHA256(json.dumps(fingerprint_v1,
    sort_keys=True, separators=(",", ":"), ensure_ascii=False)).hexdigest()
```
où `fingerprint_v1` contient exactement : `research_run_id`, `dataset_snapshot_id`,
`split_plan_id`, `strategy_name`, `base_params`, `search_mode`, `search_space_hash` (minuscule),
`budget_per_fold`, `walk_forward_specification` (sous-dict `geometry`/`train_period`/`test_period`/
`step_period`/`allow_partial_last_fold`/`position_transition_policy`/`master_seed`),
`readiness_spec` (ou `None`), `expected_fold_ids`, `expected_fold_definitions_hash`,
`validation_zone_hash`, `split_plan_fingerprint`, `walk_forward_spec_semantics_version`,
`monte_carlo_semantics_version`, `parameter_stability_semantics_version`,
`monte_carlo_verdict_policy_id`/`parameter_stability_verdict_policy_id`/
`walk_forward_verdict_policy_id` (toujours `None` sur le chemin V2, mais présents comme clés en
V1), `oos_evidence_validation_run_id`, `oos_evidence_hash`. **Note technique** : cette formule V1
n'utilise PAS `allow_nan=False` (contrairement à la discipline canonique Slice A/B) — laissé
tel quel, jamais changé rétroactivement. `split_plan_path`/`oos_evidence_path` ne participent
JAMAIS à ce fingerprint (déjà correct en V1, confirmé par lecture directe).

### 20.2 — `campaign_protocol_fingerprint` : réutilisation obligatoire, jamais réimplémentée

`GateVCampaignPlanV2` DOIT calculer son `campaign_protocol_fingerprint` en appelant directement
`gate_v_preregistration.compute_campaign_protocol_fingerprint()` (Décision 7), avec les MÊMES
inputs primitifs recalculés depuis ses propres sources (jamais des valeurs héritées telles
quelles d'un appelant) :
- `research_run_content_hash` : recalculé via `gate_v_preregistration.research_run_content_hash()`
  depuis le `ResearchRun` fourni — jamais une valeur transmise par l'appelant sans recalcul.
- `split_plan_fingerprint` : recalculé via `dataset_split.dataset_split_plan_fingerprint()` depuis
  le `DatasetSplitPlan` fourni.
- `expected_fold_ids`/`expected_fold_definitions_hash`/`validation_zone_hash` : recalculés depuis
  `walk_forward.compute_fold_definitions()` appliqué à `split_plan.validation`/
  `walk_forward_specification`/`readiness_spec` fournis — jamais des listes/hash transmis
  directement par l'appelant.
- `policy_content_hash` : recalculé via `gate_v_validation_policy.policy_content_hash()` depuis la
  `GateVValidationPolicyVersion` fournie.

Aucune SECONDE implémentation de cette empreinte n'existe ni ne doit exister. Le résultat DOIT
être comparé par égalité stricte à `preregistration.campaign_protocol_fingerprint` — tout écart
lève une exception, construction refusée (fail-closed).

### 20.3 — `campaign_id` V2 : formule exacte, normative, non ambiguë

```
GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION = "gate_v_campaign_plan_v2"

campaign_id_v2 = "gate_v_v2_" + SHA256(canonical_json({
    campaign_plan_semantics_version: "gate_v_campaign_plan_v2",
    preregistration_id: <preregistration.preregistration_id>,
    campaign_protocol_fingerprint: <valeur validée égale en Décision 20.2>
})).hexdigest()

canonical_json = json.dumps(record, sort_keys=True, separators=(",", ":"),
    ensure_ascii=False, allow_nan=False)
```

**Justification exhaustive de cette forme minimale (hash-de-hashes), et pourquoi elle suffit** :
- `preregistration_id` inclut déjà, transitivement (Décision 8 corrigée), TOUT le protocole
  (via `campaign_protocol_fingerprint`), `research_run_id`/`research_run_content_hash`,
  `dataset_snapshot_id`/`split_plan_id`/`strategy_name`, `gate_v_validation_policy_id`/
  `policy_content_hash`, **et** `policy_git_sha` (que `campaign_protocol_fingerprint` seul
  n'inclut PAS — c'est précisément pourquoi `preregistration_id` doit être inclus directement, et
  pas seulement `campaign_protocol_fingerprint`).
- `campaign_protocol_fingerprint` est INCLUS EN PLUS, redondamment — même principe de redondance
  délibérée pour intégrité/auditabilité déjà établi en Décision 8 pour
  `research_run_content_hash`/`policy_git_sha` dans `preregistration_content_hash` : permet de
  vérifier/auditer le protocole directement depuis le plan seul, sans dépendre d'un accès croisé
  systématique à la `GateVPreRegistration` référencée.
- `campaign_plan_semantics_version` dans la préimage ET le préfixe littéral `"gate_v_v2_"` (distinct
  de `"gate_v_"` en V1) rendent V1/V2 structurellement non confondables — pas seulement
  sémantiquement, mais au niveau de la CHAÎNE elle-même (préfixes de longueur différente,
  jamais de collision possible entre les deux espaces d'identifiants).
- Aucun horodatage : `GateVCampaignPlanV2` ne porte AUCUN champ `created_at` ni aucun timestamp
  (Décision 20.4) — le plan reste entièrement déterministe, jamais un audit-timestamp dans son
  contrat normatif ni dans son identité.
- Aucune donnée observée (OOS/WF/MC/PS/FINAL_HOLDOUT) : structurellement absente, `GateVCampaignPlanV2`
  n'a aucun champ de ce type (Décision 20.4).
- Aucune collision logique avec un autre préenregistrement : `preregistration_id` est
  cryptographiquement unique par scope+protocole+policy+provenance Git (Décision 8) ; SHA256 hérite
  cette garantie de collision-résistance.

### 20.4 — Champs normatifs `GateVCampaignPlanV2`, et interdictions strictes

```python
GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION = "gate_v_campaign_plan_v2"

campaign_plan_semantics_version = GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION
campaign_id
preregistration_id
preregistration_content_hash
campaign_protocol_fingerprint
research_run_id
research_run_content_hash
dataset_snapshot_id
split_plan_id
split_plan_fingerprint
strategy_name
base_params
search_mode
search_space_hash
budget_per_fold
walk_forward_specification
readiness_spec
expected_fold_ids
expected_fold_definitions_hash
validation_zone_hash
walk_forward_spec_semantics_version
monte_carlo_semantics_version
parameter_stability_semantics_version
gate_v_validation_policy_id
policy_content_hash
assessment_semantics_version
policy_git_sha                   # 27e champ — provenance Git immuable de la policy (Décision 20.10)
```
**Compte normatif : exactement 27 champs** (numérotés dans l'ordre ci-dessus : 1
`campaign_plan_semantics_version` … 26 `assessment_semantics_version`, 27 `policy_git_sha`).
Aucun champ implicite, aucun champ « etc. ». **Aucun `created_at` ni aucun timestamp** : le plan est
déterministe, sans horodatage d'audit dans son contrat normatif.

`preregistration_content_hash` est inclus comme champ persisté (audit/traçabilité directe vers
l'artefact PreRegistration référencé) mais N'EST PAS dans la préimage de `campaign_id` V2
(Décision 20.3) — seul `preregistration_id` y participe. `policy_git_sha` est porté DIRECTEMENT par
le plan (copié depuis la `GateVPreRegistration` validée, jamais recalculé ni modifié), et participe
à l'identité uniquement de façon transitive via `preregistration_id` (Décision 20.3) ; règles de
cohérence et de vérification : Décision 20.10.

**Interdits à la construction, structurellement absents du type (jamais `Optional`, jamais un
champ existant mis à `None` — le type lui-même ne les porte PAS)** :
```
oos_evidence_validation_run_id
oos_evidence_hash
oos_evidence_path
```
Aucun résultat Walk-Forward/Monte-Carlo/Parameter Stability/OOS/`FINAL_HOLDOUT` ne peut exister
dans `GateVCampaignPlanV2` — ni comme champ, ni comme entrée de son calcul d'identité.

### 20.5 — Modèle de type : `GateVCampaignPlanV2`, dataclass DISTINCTE (Option B retenue)

**Options évaluées** :
- **Option A (étendre `GateVCampaignPlan`)** — REJETÉE. Mélanger des champs V1 (`oos_evidence_*`,
  légitimement peuplés) et des champs V2 (interdits à la construction) sur UNE seule dataclass
  rendrait des états illégaux représentables (une instance avec `oos_evidence_validation_run_id`
  ET `campaign_plan_semantics_version="gate_v_campaign_plan_v2"` simultanément) — nécessiterait une
  validation croisée permanente partout où le type est consommé, fragile, contraire au principe
  "rendre les états illégaux non représentables".
- **Option B (dataclass distincte `GateVCampaignPlanV2`)** — RETENUE. Chaque type ne porte QUE ses
  champs valides — aucune combinaison illégale représentable au niveau du type lui-même. V1
  (`GateVCampaignPlan`, `build_gate_v_campaign_plan()`, son `campaign_id`) reste strictement
  inchangé, zéro risque de régression (aucun fichier V1 modifié). Une future Slice D distingue
  V1/V2 par `isinstance()` ou par présence de `campaign_plan_semantics_version`, sans ambiguïté.
  Aucun refactor big-bang — pur ajout, nouveau module additif (`gate_v_campaign_plan_v2.py`,
  candidat, à confirmer en implémentation), n'important JAMAIS `gate_v_campaign.py` — même
  discipline de frontière que Slice A/B.
- **Option C** : aucune alternative démontrée supérieure identifiée ; non retenue.

### 20.6 — Save/load V2 : stratégie exacte, fail-closed

**Emplacement** : `results/job_xxx/gate_v/campaigns/<campaign_id>/plan.json` (Décision 16,
inchangée — le chemin reste toujours fourni par l'appelant, jamais résolu en interne).

**Persistance** : `save_exclusive()` (Slice B, `atomic_json_store.py`), PAS `save_atomic()`. Le
plan V2 étant déterministe (aucun timestamp, Décision 20.4), deux constructions légitimes du MÊME
`campaign_id` produisent un contenu identique ; mais `save_atomic()` autorise l'écrasement
silencieux d'un fichier existant sur le même chemin (le TOCTOU documenté), y compris par un
contenu DIFFÉRENT (plan altéré ou construit depuis d'autres sources) sans jamais lever
d'exception. `save_exclusive()` impose "jamais d'écrasement silencieux" : un plan déjà présent au
chemin fourni lève une exception, par cohérence avec `GateVPreRegistration`.

**Discrimination V1/V2** : jamais par emplacement/nom de fichier — par le CONTENU. Absence de la
clé `campaign_plan_semantics_version` = fichier V1 (chargé par le loader V1 existant, inchangé,
jamais ce nouveau loader). Présence avec valeur EXACTE `"gate_v_campaign_plan_v2"` = V2. Toute
AUTRE valeur (version future inconnue, ou corruption) = **refus fermé immédiat**, jamais interprété
comme V1 ni comme V2 par repli silencieux.

**Chargeur strict V2** (`load_gate_v_campaign_plan_v2()`, conceptuel — non implémenté ce tour) :
1. Rejette tout JSON invalide/absent (jamais un `None` silencieux — comme Slice A/B).
2. Rejette toute clé de premier niveau inconnue, et tout champ obligatoire manquant.
3. Rejette toute `campaign_plan_semantics_version` absente ou différente de la constante exacte.
4. Reconstruit les types imbriqués (`walk_forward_specification`, `readiness_spec`).
5. **Revalidation en DEUX temps, obligatoire, ferme le gap identifié en revue architecture
   (20.7)** : (a) recalcule `campaign_protocol_fingerprint` depuis les champs primitifs persistés
   et compare à la valeur persistée — détecte toute altération des champs scientifiques ; (b)
   recalcule `campaign_id` depuis `{campaign_plan_semantics_version, preregistration_id,
   campaign_protocol_fingerprint}` (tels que PERSISTÉS, après l'étape (a)) et compare à la valeur
   persistée — détecte spécifiquement toute altération de `preregistration_id` seul, que (a) seul
   ne peut pas détecter (`preregistration_id` ne fait PAS partie de la préimage de
   `campaign_protocol_fingerprint` lui-même, par construction Décision 20.3). Tout écart sur (a)
   OU (b) : exception, jamais un objet partiellement validé retourné.
6. Le chargeur NE recharge PAS lui-même la `GateVPreRegistration` référencée (pas d'E/S croisée
   cachée dans un loader — même discipline que Slice A/B) — cette vérification croisée relève de
   la CONSTRUCTION (`build_gate_v_campaign_plan_v2()`, qui reçoit l'objet `GateVPreRegistration`
   déjà chargé par l'appelant, jamais un chemin).
7. Un fichier corrompu/tronqué (crash après `save_exclusive()` mais avant écriture complète,
   même matrice de crash que Décision 9 réutilisée) échoue à l'étape 1 (JSON invalide) — jamais
   interprété comme valide.

**Limite acceptée, inhérente, déjà présente en Slice A/B, non nouvelle** : une falsification
totalement auto-cohérente (attaquant recalculant honnêtement `campaign_id` à partir de champs
qu'il a lui-même altérés) n'est PAS détectable par revalidation seule — la protection réelle vient
de l'exclusivité de création + la provenance Git de la policy au moment de la CRÉATION initiale
(Décision 6/9), pas du chargement a posteriori.

### 20.7 — Findings de revue adversariale (résolus dans cette spec avant tout code)

**Axe scientifique** — tous fermés par la conception ci-dessus : policy/paramètres/split/
readiness/seed/folds changés après préenregistrement → `campaign_protocol_fingerprint` recalculé
diffère → refus fermé (20.2) ; ancien plan V1 présenté comme V2 → rejeté (`campaign_plan_semantics_version`
absente, 20.6) ; OOS injectée avant le plan → structurellement impossible (20.4, Option B) ;
`FINAL_HOLDOUT` observé avant WF/MC/PS → hors du périmètre de `GateVCampaignPlanV2` par
construction (aucun champ, aucune dépendance), reste de la responsabilité de l'ordonnancement
Décision 2/9/11 (tranche future).

**Axe architecture/reproductibilité** — un gap réel a été trouvé et fermé ICI (avant code) :
revalidation au chargement fondée UNIQUEMENT sur `campaign_protocol_fingerprint` ne détecte PAS
une altération isolée de `preregistration_id` (champ hors de sa préimage) → **corrigé** par la
revalidation en deux temps obligatoire (20.6, étape 5). Formule dupliquée → prévenue (20.2,
réutilisation obligatoire de `compute_campaign_protocol_fingerprint()`). Chemins runtime dans
l'identité → exclus explicitement (confirmé absent en V1, même discipline en V2). Timestamps dans
l'identité → aucun champ timestamp/`created_at` dans le plan V2 (20.3/20.4). Ordre des clés JSON → neutralisé par
`sort_keys=True` partout. Dérive d'identité V1 accidentelle → impossible (préfixe distinct,
préimage non partagée, code V1 jamais touché). Aucun autre BLOCKER/MAJOR trouvé.

### 20.8 — Ordonnancement scientifique, reconfirmé (pas une nouvelle décision, Décision 2 inchangée)

`GateVValidationPolicyVersion` committée → `GateVPreRegistration` → `GateVCampaignPlanV2` →
Walk-Forward → Monte-Carlo → Parameter Stability (tous folds) → `FinalHoldoutAccessClaim` →
`FINAL_HOLDOUT` — Décision 2 s'applique sans changement ; Slice C construit uniquement l'étape
"Plan V2", jamais l'exécution WF/MC/PS ni la Claim.

### 20.9 — Relation avec `GateVCampaignManifest` V2 (hors périmètre Slice C)

`GateVCampaignPlanV2` doit fournir à un futur Manifest V2 (tranche ultérieure, non implémentée
ici) : `campaign_id`, `preregistration_id`, `expected_fold_ids` (même rôle de suivi de complétude
WF/MC/PS que V1). Restent explicitement hors de Slice C : la structure `GateVCampaignManifest` V2
elle-même, l'exécution WF/MC/PS (équivalent Niveau B pour V2), `FinalHoldoutAccessClaim`,
`ValidationAssessment`, `GateVPolicyAssessment`, tout accès `FINAL_HOLDOUT`.

### 20.10 — `policy_git_sha` : frontière création / relecture ; barrières de revalidation explicites

**(a) `policy_git_sha` dans le Plan V2.** Champ n°27 (Décision 20.4), copié depuis la
`GateVPreRegistration` validée. Il doit être strictement égal à `preregistration.policy_git_sha` à
la construction du plan ET à toute revalidation ; tout écart = exception (fail-closed). Immuable :
jamais recalculé, jamais réécrit, jamais remplacé par le HEAD courant.

**(b) Deux phases distinctes — NE PAS les confondre.**
- **Création de la `GateVPreRegistration`** (Slice B, Décision 6, inchangée) :
  `policy_git_sha == HEAD courant` est EXIGÉ à cet instant précis (comparaison canonique
  `git rev-parse HEAD^{commit}` vs `<sha>^{commit}`).
- **Construction du Plan V2, chargement et relecture historique ultérieure** : le système NE DOIT
  PAS exiger `HEAD courant == policy_git_sha` — HEAD a naturellement avancé depuis la création du
  préenregistrement, et exiger cette égalité rendrait tout artefact historique illisible. Il vérifie
  à la place la provenance HISTORIQUE référencée : (1) le commit `policy_git_sha` est résolvable
  dans le dépôt ; (2) le blob committé de la policy à ce commit existe et est du JSON valide ;
  (3) son `validation_policy_id` == `gate_v_validation_policy_id` du plan ; (4) le hash de contenu de ce blob
  (`gate_v_validation_policy.policy_content_hash()`) == `policy_content_hash` du plan ; (5) cohérence
  avec la `GateVPreRegistration` (`policy_git_sha`, `gate_v_validation_policy_id`,
  `policy_content_hash` identiques). Commit non résolvable, blob absent/altéré ou toute
  incohérence = refus fermé.
- **Séparation obligatoire en Slice C.** L'API actuelle `verify_policy_git_provenance()`
  (`gate_v_preregistration.py`) est orientée CRÉATION : elle exige `policy_git_sha == HEAD`. Elle ne
  doit PAS être affaiblie (la garantie de création reste intacte) ni réutilisée telle quelle pour la
  relecture. L'implémentation Slice C devra ajouter une vérification de provenance HISTORIQUE
  distincte (fonction ou mode dédié, sans l'exigence HEAD), appelée comme étape explicite — jamais
  silencieusement omise, jamais fusionnée dans le chargeur pur (20.6 étape 6 : pas d'E/S Git
  cachée dans un loader, même discipline que Slice B). Aucun code Slice B n'est modifié par la
  présente spécification.

**(c) Deux barrières de revalidation, toutes deux OBLIGATOIRES et explicites.**
- **Barrière 1 (protocole)** : recalculer `computed_campaign_protocol_fingerprint` depuis les vraies
  sources via l'unique `compute_campaign_protocol_fingerprint()` (20.2), puis exiger
  `computed_campaign_protocol_fingerprint == preregistration.campaign_protocol_fingerprint ==
  plan.campaign_protocol_fingerprint`.
- **Barrière 2 (identité)** : recalculer `expected_campaign_id_v2` depuis
  `campaign_plan_semantics_version`, le `preregistration_id` validé et le
  `campaign_protocol_fingerprint` validé (formule 20.3), puis exiger
  `expected_campaign_id_v2 == plan.campaign_id`. Cette barrière est indépendante de la première :
  seule elle détecte une falsification isolée de `preregistration_id` (20.6 étape 5b, 20.7). Le
  MAJOR identifié en revue architecture est ainsi explicitement fermé à la construction ET au
  chargement.

## Décision 21 — `GateVCampaignManifestV2` / discrimination V1-V2 (Slice D, verrouillé avant TDD, 2026-10-06)

**Contexte** : Slices A/B/C sont `INTEGRATED` dans `master` (Slice C = commit
`59dd901f74370bac96ba9564a4729347ba994d81`, suite complète 1915/1915). Cette Décision ferme, AVANT
tout code, les questions normatives de la Slice D : (A) le Manifest V2 et (B) la discrimination
V1/V2. Elle précise (sans le contredire) la Décision 13 (champs V2 du Manifest) et la Décision 20.9
(relation Plan V2 → Manifest V2). **Aucun code, aucun test, aucun accès `FINAL_HOLDOUT`** n'est
produit par cette conception.

### 21.1 — Périmètre

**Dans Slice D** : type `GateVCampaignManifestV2` ; identité/liaison au Plan V2 ; statuts factuels V2 ;
règles de complétude WF/MC/PS ; précondition vérifiable du futur Claim ; persistance, transitions,
concurrence, crash/reprise ; algorithme de discrimination V1/V2.
**Hors Slice D** (tranches suivantes, rien de cela n'est implémenté ni préparé par du code mort) :
exécution WF/MC/PS V2 (un futur `execute_gate_v_campaign_v2`), `FinalHoldoutAccessClaim` et son
acquisition, `run_gate_v_final_holdout_validation`, `HoldoutAccessEvent` V2, `ValidationAssessment`,
`GateVPolicyAssessment`, toute policy concrète de seuils, tout accès `FINAL_HOLDOUT`.

### 21.2 — Constats sur le code réel (`gate_v_campaign.py`, V1, gelé)

- `GateVCampaignManifest` V1 : 10 champs (`campaign_id`, `expected_fold_ids`, `status`,
  `oos_evidence_validation_run_id`, `walk_forward_validation_run_id`, `monte_carlo_validation_run_id`,
  `parameter_stability_validation_run_ids_by_fold`, `execution_started`, `running`,
  `technical_failure_reason`) ; **aucun champ de version sémantique** ; persisté par
  `save_atomic_overwrite()` ; chargé par `GateVCampaignManifest(**record)` — toute clé inconnue lève
  `TypeError` puis `ValueError` : **un fichier V2 est donc déjà refusé fermé par le chargeur V1**, et
  un fichier V1 (sans clés V2) sera refusé par le chargeur V2.
- Six statuts V1 (`NOT_READY` jamais persisté). **`EVIDENCE_COMPLETE_AWAITING_POLICY` exige la
  référence OOS** (`_validate_gate_v_manifest_structure`, `derive_gate_v_campaign_status`) : c'est un
  état **OOS-first**, faux par construction en V2 (Décision 2 : l'OOS est la dernière preuve).
- Les prédicats de complétude (`_walk_forward_complete`, `_monte_carlo_complete`,
  `_parameter_stability_quality`, `_validate_scoped_run`) sont **privés** à `gate_v_campaign.py`. Un seul
  verrou technique les lie au type V1 : `gate_v_validation_run_id()` applique
  `isinstance(plan, GateVCampaignPlan)` et est appelée par `_monte_carlo_complete` (les trois autres
  ne lisent que des champs que `GateVCampaignPlanV2` porte aussi). La vraie raison de ne pas les réutiliser
  est la **discipline de frontière** (Décision 20.5) : un module V2 n'importe ni `gate_v_campaign.py`
  ni ses noms privés ; les réutiliser exigerait de toucher V1 (extraction) ou de s'y coupler.
- Le Manifest V1 est un artefact mutable à écriture monotone (règles de non-régression à la sauvegarde)
  et son statut est vérifié égal au statut dérivé des preuves persistées au chargement ET à la
  sauvegarde. Ce principe (preuves = autorité, manifeste = pointeurs + marqueurs d'exécution) est
  conservé en V2.
- Aucun consommateur externe (UI, jobs, autopilot) ne lit `manifest.json` : la surface d'intégration
  est limitée à `gate_v_campaign.py` et ses tests.

### 21.3 — Type : options comparées, Option B retenue

| Option | Description | Verdict |
|---|---|---|
| A — type commun, champs optionnels | `GateVCampaignManifest` gagne `manifest_semantics_version` + champs V2 optionnels | **Rejetée** : modifie la dataclass V1 gelée ; rend représentable un état V1 portant un claim, ou un état V2 portant une référence OOS avant les preuves ; `GateVCampaignManifest(**record)` V1 accepterait ou refuserait selon des clés optionnelles — dérive silencieuse du chargeur historique |
| **B — dataclass V2 distincte** | `GateVCampaignManifestV2`, module additif, n'importe jamais `gate_v_campaign.py` | **Retenue** — même argument que Décision 20.5 : chaque type ne porte que ses champs valides ; V1 inchangé à l'octet ; la discrimination devient un test de type + un champ de version |
| C — wrapper/union versionnée | `VersionedManifest(version, payload)` | **Rejetée comme type de persistance** (ajoute une couche sans supprimer d'état illégal ; Python n'a pas de somme exhaustive vérifiée). **Conservée uniquement comme sortie de classification** (21.9) : une valeur `"v1"`/`"v2"`, jamais un conteneur de données |

### 21.4 — Contrat exact de `GateVCampaignManifestV2`

```
GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION = "gate_v_campaign_manifest_v2"
```
Dataclass `frozen`, **exactement 17 champs**, dans cet ordre, aucun timestamp, aucun chemin, aucun
verdict :
```
# Identité / liaison — IMMUABLES (jamais modifiés après la création)
1  manifest_semantics_version                 # == constante ci-dessus, exact
2  campaign_id                                # "gate_v_v2_" + 64 hex (Décision 20.3)
3  preregistration_id                         # copié du Plan V2
4  campaign_protocol_fingerprint              # copié du Plan V2

# État de progression — MUTABLES, monotones (21.8)
5  manifest_revision                          # int >= 0, +1 par mise à jour effective ; détection d'écriture périmée + audit, JAMAIS une identité ni un primitif d'exclusion (21.8)
6  status                                     # instantané DÉRIVÉ (21.5), jamais fourni par l'appelant
7  execution_started                          # bool, False -> True une fois
8  running                                    # bool
9  technical_failure_reason                   # None -> str non vide, une fois, jamais effacé
10 walk_forward_validation_run_id             # None -> id, une fois
11 monte_carlo_validation_run_id              # None -> id, une fois
12 parameter_stability_validation_run_ids_by_fold   # dict fold_id -> id, ajouts seuls

# RÉSERVÉS (Décision 13) — présents dans le schéma, valeur IMPOSÉE None en Slice D
13 final_holdout_claim_id
14 final_holdout_claim_content_hash
15 holdout_access_event_id
16 holdout_access_event_content_hash
17 oos_evidence_validation_run_id
```
**Invariants structurels imposés par le chargeur pur V2** (reprise des règles V1
`_validate_gate_v_manifest_structure`, plus les règles V2) : ensemble de clés EXACT (inconnue ou
manquante → refus) ; `manifest_semantics_version` exacte ; `campaign_id` de forme `gate_v_v2_<64 hex>`
**et égal au `campaign_id` recalculé** depuis `{GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION,
preregistration_id, campaign_protocol_fingerprint}` (le Manifest ne porte pas
`campaign_plan_semantics_version` : la constante du module Plan V2, impliquée par
`manifest_semantics_version`, entre dans le recalcul) ; `preregistration_id` et fingerprint = 64 hex ;
`manifest_revision` entier non booléen `>= 0` ; `status` ∈ `GATE_V_CAMPAIGN_V2_STATUSES` ; `execution_started`
et `running` booléens ; `running` ⇒ `execution_started` ; `technical_failure_reason` non nul ⇒ chaîne non
vide, `execution_started` et non `running` ; toute référence de preuve ⇒ `execution_started` ;
`monte_carlo_validation_run_id` ou toute entrée Parameter Stability ⇒ `walk_forward_validation_run_id` non nul ;
chaque identifiant de preuve == identifiant déterministe de 21.6 ; champs 13-17 tous `None` ; statut
cohérent avec les marqueurs (`marker_status` calculable sans I/O pour `TECHNICAL_FAILURE`, `RUNNING`,
`READY_FOR_EXECUTION` ; `EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT` exige WF, MC et une entrée PS au
minimum — l'égalité exacte à `expected_fold_ids` relève de la couche de liaison au plan).

**Non persisté car dérivable du Plan V2 ou des preuves** (jamais dupliqué) : `expected_fold_ids`,
`split_plan_*`, `research_run_*`, `policy_*`, `preregistration_content_hash`, `assessment_semantics_version`,
`walk_forward_specification`, tous les hashes de protocole (le Plan V2 est la seule source), et tout
résumé de preuve. **Pas de `manifest_content_hash`** : aucun artefact existant ni prévu (Claim D10,
HoldoutAccessEvent D13, `GateVPolicyAssessment` D14) ne référence le contenu du Manifest ; un hash de
contenu d'un artefact mutable n'est pas une identité. L'identité d'une campagne est `campaign_id`
(immuable). `manifest_revision` sert à la détection d'écriture périmée et à l'audit (21.8) — pas
d'exclusion — et n'entre dans
aucun hash. Si un besoin futur d'instantané apparaît, il sera un hash d'une forme canonique excluant
le hash lui-même, jamais une identité.

**Champs réservés — règle normative (mission §7, options comparées)** :
(i) *champs présents, valeur forcée `None`* ; (ii) *champs absents, ajoutés par une tranche future* ;
(iii) *sous-enregistrements typés dès maintenant*. **Retenu : (i).** (ii) obligerait à changer
l'ensemble de clés — donc une nouvelle version sémantique et une migration in-place d'artefacts
existants — au pire moment (juste avant le claim) ; (iii) crée des types inutilisés
(Speculative Generality). Avec (i) l'ensemble de clés est stable pour toute la vie du schéma.
Garde-fous exacts :
- En Slice D, le **constructeur, toutes les commandes et le chargeur refusent toute valeur non `None`**
  pour les champs 13-17 (« réservé : acquisition du claim non implémentée, aucune vérification possible
  de l'autorité »). Un claim ajouté à la main (finding 15) est donc refusé fermé.
- **Principe d'extension monotone** : une tranche future peut seulement AJOUTER des états valides
  (miroir non nul accepté **uniquement** après vérification explicite contre le fichier de claim
  autoritaire, 21.10) ; tout Manifest valide en Slice D reste valide, avec le même sens, après ces
  tranches. Un binaire Slice D qui rencontre un Manifest futur le refuse fermé — comportement voulu.
- Invariants de groupe à imposer dès qu'un champ réservé devient non nul : (13,14) tous deux nuls ou
  tous deux non nuls ; (15,16,17) tous nuls ou tous non nuls ; le groupe (15,16,17) exige le groupe
  (13,14). Aucun état partiel n'est donc admissible.
- **Un Manifest initial ne peut jamais prétendre que `FINAL_HOLDOUT` a été accédé** : aucun champ
  non nul n'est constructible, aucun statut V2 de Slice D ne nomme `FINAL_HOLDOUT` autrement que
  comme « en attente » (`EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT`), et ce statut n'accorde aucun droit
  (21.7, 21.10).

### 21.5 — Statuts factuels V2

Ensemble exact, jamais un état supplémentaire, **jamais** `PASS`/`FAIL`/`Champion`/verdict :
```
GATE_V_CAMPAIGN_V2_STATUSES = {
  "READY_FOR_EXECUTION", "RUNNING", "EVIDENCE_INCOMPLETE",
  "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT", "TECHNICAL_FAILURE",
}
```
| Statut V2 | Condition (dérivée, priorité décroissante de haut en bas) |
|---|---|
| `TECHNICAL_FAILURE` | `technical_failure_reason` non nul (`marker_status`) **OU**, pour `effective_status` seulement, sentinelle `technical_failure.json` présente (21.8). Terminal pour toutes les API de Slice D |
| `RUNNING` | `running` vrai |
| `READY_FOR_EXECUTION` | `execution_started` faux |
| `EVIDENCE_INCOMPLETE` | démarrée, non `running`, sans échec ; au moins l'une de WF / MC / PS (un fold attendu) manque ou ne satisfait pas sa condition de complétude (21.6) |
| `EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT` | démarrée, non `running`, sans échec ; WF + MC + PS (**TOUS** les `expected_fold_ids`) complets au sens de 21.6 ; champs 13-17 tous `None` |

Réutilisation de V1 : `READY_FOR_EXECUTION`, `RUNNING`, `TECHNICAL_FAILURE` gardent le sens V1 exact.
`EVIDENCE_INCOMPLETE` garde son nom mais **sa condition est restreinte à WF/MC/PS** (la condition V1
« OOS absente » supposait OOS-first et devient fausse). `NOT_READY` n'existe pas en V2 (jamais
persisté, V1 compris). **`EVIDENCE_COMPLETE_AWAITING_POLICY` est interdit en V2** (sens faux : il
inclut l'OOS) : il appartient à l'ensemble V1 mais pas à `GATE_V_CAMPAIGN_V2_STATUSES`, le chargeur V2
le refuse. Inversement, un Manifest V2 ne peut pas être lu par le chargeur V1 (clés inconnues, 21.2).

**Deux valeurs dérivées distinctes (ferme un MAJOR de revue)** — le statut **persisté** et le statut
**effectif** ne sont pas la même chose :
- `marker_status` = dérivation depuis les marqueurs du Manifest, ses références et les preuves, **sans
  tenir compte de la sentinelle** ; le statut persisté doit lui être égal (autocohérence du fichier).
- `effective_status` = `TECHNICAL_FAILURE` si la sentinelle `technical_failure.json` existe (même
  illisible : son existence est le fait), sinon `marker_status`. C'est elle que lit la précondition 21.7.
Un Manifest dont la sentinelle est « en avance » sur son marqueur est donc **légal et chargeable**
(`status == marker_status`), et peut être réconcilié par la seule commande `MarkTechnicalFailure` (21.8).
Statuts de la phase `FINAL_HOLDOUT` (réservés, **hors Slice D**, ajoutés plus tard par extension
monotone) : par exemple `FINAL_HOLDOUT_CLAIMED`, `FINAL_HOLDOUT_EVIDENCE_PERSISTED` — noms indicatifs,
non normatifs, non valides en Slice D. Un test impose que **les segments** (découpage sur `_`) d'aucune
valeur de statut n'appartiennent à `{PASS, FAIL, CHAMPION, OOS, VERDICT}` — par segments et non par
sous-chaîne, car `TECHNICAL_FAILURE` (nom hérité de V1, factuel) contient la sous-chaîne `FAIL`.

`status` est **persisté pour la lisibilité** (parité V1, lecture sans charger les preuves) mais
**toujours recalculé par l'API de mise à jour** : l'appelant ne le fournit jamais, un désaccord est donc
impossible par construction ; au chargement/à la vérification, tout écart entre le statut persisté et
`marker_status` (ci-dessous) est un refus.

### 21.6 — Source d'autorité et règles de complétude

**Autorité** : les `ValidationRun` immuables persistées à leur chemin canonique
`<campaign_dir>/validations/<validation_run_id>/validation_run.json` (Décision 16) + le Plan V2 validé.
Le Manifest ne contient que des **pointeurs** et des **marqueurs d'exécution non dérivables** (démarré,
en cours, échec technique). Il ne peut JAMAIS déclarer une phase complète : « complet » n'est qu'un
**résultat de dérivation** sur preuves rechargées depuis le disque (jamais des objets en mémoire fournis
par l'appelant).

`validation_run_id` déterministe (même forme que V1, espace d'identifiants disjoint grâce au préfixe
`gate_v_v2_`) : `"{campaign_id}_{validation_type}"` (WF, MC) et `"{campaign_id}_parameter_stability_{fold_id}"`.
Une référence dont l'identifiant ne vaut pas cette valeur exacte est étrangère → refus.

**Preuve « scoped »** (reprise des règles V1, sans le cas OOS) : `validation_type` attendu ;
`dataset_snapshot_id`, `split_plan_id`, `strategy_name`, `research_run_id` égaux au Plan V2 ;
`status == "completed"` ; `scientific_verdict == "INCONCLUSIVE"` (aucune policy de verdict, Décision 18) ;
WF et MC : `strategy_params == plan.base_params`.
**Walk-Forward complet** : spécification égale à `plan.walk_forward_specification` ; `execution_status ==
"completed"` et agrégat présent ; `fold_id` des résultats **égaux, dans l'ordre exact**, à
`plan.expected_fold_ids` (fold attendu manquant → incomplet ; fold inattendu ou doublon → incomplet) ;
cohérence trades/zéro-trade par fold ; Top-1 TRAIN, `search_space_hash`, `search_mode`, budget ;
hash des définitions de folds recalculé == `plan.expected_fold_definitions_hash` (écart = erreur) ;
agrégat cohérent avec les folds. **Précision (D1, 2026-10-07)** : « cohérent » signifie, en V2, **égal,
champ à champ, au résultat du producteur canonique `walk_forward.build_aggregate_result(fold_results)`**
recalculé sur les folds validés (aucune réimplémentation de la formule ; NaN, booléen ou flottant à la
place d'un compteur refusés) ; une métrique consommée plus tard par la policy (`oos_net_return_pct`,
drawdown, profit factor, win rate, Sharpe) ne peut donc pas provenir d'un agrégat persisté incohérent
avec ses folds. **Précision (D1, 2026-10-07)** : pour V2, les faits élémentaires d'un `FoldResult` doivent
être compatibles avec les invariants du producteur canonique : `net_ret_pct` et `score_test` sont finis,
`score_test` est compris entre `0` et `100` (`scoring.compute_score` le borne) ; `gross_win` et
`gross_loss` sont finis et `>= 0` ; `n_win` est un entier non booléen compris entre `0` et `n_trades` ;
sur un fold zéro trade, `gross_win == gross_loss == n_win == 0` et `score_test == 0` (le producteur les
force) ; aucun de ces nombres n'est un booléen. **Relations imposées par `engine._compute_stats` sur un
fold avec trades** : `n_win > 0` implique `gross_win > 0` ; `n_win == 0` implique `gross_win == 0` ; tous
les trades gagnants (`n_win == n_trades`) impliquent `gross_loss == 0` ; en revanche des trades non
gagnants peuvent être exactement à zéro (classés « pertes » sans changer `gross_loss`), donc
`gross_loss == 0` n'implique **pas** `n_win == n_trades` ; `win_rate == n_win / n_trades * 100` ;
`profit_factor == gross_win / gross_loss` si `gross_loss > 0`, sinon `+inf` ; `win_rate` et `profit_factor`
sont refusés s'ils sont booléens, NaN, absents ou incohérents (sur un fold zéro trade ils restent `None`).
Ces contrôles sont effectués **AVANT** de considérer l'agrégat recalculé comme une preuve de cohérence :
un agrégat auto-cohérent avec un fold falsifié ne blanchit jamais ce fold. `profit_factor = +inf` reste
**valide et canonique** lorsque des trades existent et qu'aucune perte brute n'est observée
(`gross_loss == 0`, convention du producteur, y compris pour des trades tous à zéro) ; `isfinite` ne lui
est jamais appliqué.
**Monte-Carlo complet** : spécification == celle construite pour la run WF de la campagne avec
`verdict_policy_id = None` et circularité déclarée vraie ; nombre de trades == total WF ; aucune
métrique inventée sur zéro trade ; distributions finies présentes sinon incomplet.
**Parameter Stability complète pour un fold** : spécification == celle construite pour (run WF, fold,
`search_mode`, circularité déclarée vraie) ; correspondance avec le Top-1/pool TRAIN du fold ;
compteurs de voisins cohérents ; voisinage exploitable réel ; distributions finies. **Précision (D1,
2026-10-07)** : les ensembles de clés de `n_neighbors_total_by_param` et `n_neighbors_rejected_by_param`
sont **égaux à celui de `best_params`** (le producteur `parameter_stability.py` remplit ces structures
pour chaque paramètre actif, `best_params.keys()`) ; une preuve persistée ne peut ni perdre ni inventer un
paramètre (écart = erreur ; `best_params` absent = aucune clé attendue). Ce contrôle est indépendant de la
règle de saut ci-dessous. **PS complète = TOUS**
les `expected_fold_ids` présents et chacun de qualité suffisante — jamais un simple décompte de fichiers.
**Règles de saut héritées de V1, explicitées** : sans agrégat WF, la comparaison du nombre de trades MC
est sautée (la WF est alors elle-même incomplète, donc le statut reste `EVIDENCE_INCOMPLETE`) ; sans fold
WF source, la correspondance Top-1 d'un fold PS est sautée de même ; une métrique inventée sur un fold
zéro trade est une **erreur** (pas un simple « incomplet »).

**Cas limites (mission §9)** :
| Cas | Règle |
|---|---|
| Fichier de preuve référencé absent ou illisible | **Erreur** (le Manifest est « en avance sur les preuves ») — jamais traité comme incomplet silencieux |
| Fichier de preuve présent non référencé | Jamais une preuve ; ignoré (aucune autorité) ; seule une adoption explicite (21.8) peut le rattacher |
| Preuve étrangère (autre campagne, snapshot, split, stratégie, ResearchRun, type) | Erreur |
| Fold PS référencé hors `expected_fold_ids` | Erreur |
| Fold attendu sans preuve PS | Incomplet |
| Doublon (deux références pour un même fold) | Impossible (dict) ; deux ids différents pour un fold → erreur d'identifiant déterministe |
| Preuve corrompue / type de spécification ou d'evidence incohérent | Erreur |
| Preuve complète structurellement mais de qualité insuffisante (voisinage inexploitable, MC sans distribution) | Incomplet (jamais un `FAIL` scientifique) |
| `TECHNICAL_FAILURE` (marqueur OU sentinelle) | Interdit la complétude, même si toutes les preuves existent |

**Limite acceptée** : `ValidationRun` ne porte ni `preregistration_id` ni `research_run_content_hash` ;
le lien à la PreRegistration passe par le `campaign_id` déterministe de la run (qui inclut
`preregistration_id`). L'étendre exigerait de modifier `validation_run.py` (gelé) — hors périmètre.

### 21.7 — Précondition du futur Claim (vérifiable sans ambiguïté, mission §9)

Une **unique** fonction de vérification (aucune seconde définition) :
`assert_gate_v_pre_holdout_evidence_complete(plan, campaign_dir)`, qui lève ou retourne le Manifest
vérifié ; elle ne crée **rien**. **Signature et dépendances (exactes)** : `plan` est un
`GateVCampaignPlanV2` ; `campaign_dir` est fourni par l'appelant. Le module Manifest **ne reçoit pas**
PreRegistration, ResearchRun, split, policy ni dépôt Git et n'importe donc que `gate_v_campaign_plan_v2`
(structure, chargeur pur, fonction d'identifiant), `gate_v_evidence_completeness_v2`, `validation_run`,
`atomic_json_store`. **La revalidation du Plan V2 aux sources** (`validate_gate_v_campaign_plan_v2_sources`,
Décision 20.10) est une **obligation de l'appelant**, première étape de la séquence du Claim (Décision 11,
étapes 1-2), testée dans la tranche du Claim ; la fonction ci-dessous revérifie seulement ce qu'elle peut
vérifier sans ces sources. Prédicat exact, tous les termes obligatoires :
1. `validate_gate_v_campaign_plan_v2_structure(plan)` passe (barrières internes 1 et 2) ;
   `load_gate_v_campaign_plan_v2(campaign_dir/"plan.json") == plan` ; `campaign_dir.name == plan.campaign_id`.
2. Manifest V2 chargé (chargeur pur), lié au plan (couche de liaison 21.8), `status == marker_status`.
3. `execution_started` et non `running`.
4. `technical_failure_reason` nul **et** sentinelle `technical_failure.json` **absente** (`effective_status`
   ≠ `TECHNICAL_FAILURE`, même si le fichier de sentinelle est illisible).
5. WF complet, MC complet, PS complet pour **chaque** `expected_fold_ids` (21.6), preuves rechargées du
   disque à leur chemin canonique (jamais des objets en mémoire de l'appelant).
6. Champs 13-17 tous `None` (aucun claim, aucun événement, aucune OOS déjà référencés).
7. `manifest.update.lock` **absent** : un verrou résiduel signifie « état d'écriture incertain » (21.8) ;
   le Manifest peut être en cours de transition (marqueur d'échec ou référence en attente), la
   précondition échoue fermée.
8. `effective_status == "EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT"`.
**Condition nécessaire, jamais suffisante** : elle n'autorise pas l'accès à `FINAL_HOLDOUT` (21.10).

### 21.8 — Persistance, transitions, concurrence, crash/reprise

**Chemin** : `<campaign_root>/<campaign_id>/manifest.json`, `campaign_root` toujours fourni par
l'appelant (jamais résolu en interne, aucun job historique touché). Artefact additif de Slice D :
`<campaign_dir>/technical_failure.json` (sentinelle, ci-dessous).

**Création initiale** : `save_exclusive()` (jamais `save_atomic()`) du Manifest initial déterministe
(`READY_FOR_EXECUTION`, `manifest_revision = 0`, tous marqueurs/références vides, 13-17 `None`), après
chargement du Plan V2 persisté. Deux workers créateurs : exactement un gagnant, l'autre reçoit
`FileExistsError`, recharge, ne réécrit jamais (empêche qu'un second créateur écrase un Manifest déjà
avancé — finding 13).

**Mise à jour : `save_atomic_overwrite()` utilisé à dessein** (l'artefact est fait pour évoluer ; une
écriture exclusive est inapplicable), mais **jamais une écriture libre** et **jamais hors du verrou
transitoire `manifest.update.lock`** (voir « Concurrence » ci-dessous : `save_atomic_overwrite()` seule
n'offre aucune exclusion entre processus). L'API de mise à jour accepte uniquement des **commandes
nommées** (ensemble fermé, pas de « nouveau Manifest » arbitraire) :
| Commande | Précondition | Effet |
|---|---|---|
| `Start` | non démarrée, sans échec | `execution_started = True` |
| `SetRunning(bool)` | démarrée, sans échec ; `False` exige `running` | `running` |
| `AttachWalkForward(run_id)` | démarrée, sans échec, WF vide, `run_id` déterministe | `walk_forward_validation_run_id` **et `running = False` dans la MÊME écriture** |
| `AttachMonteCarlo(run_id)` | WF rattachée, MC vide, id déterministe | `monte_carlo_validation_run_id` **et `running = False`, même écriture** |
| `AttachParameterStability(fold_id, run_id)` | WF rattachée, `fold_id` attendu, id déterministe | entrée du mapping **et `running = False`, même écriture** |
| `MarkTechnicalFailure(reason)` | démarrée ; `reason` non vide ; si la sentinelle existe, `reason` doit lui être égale | sentinelle (création, ou constat si elle existe déjà), puis `technical_failure_reason`, `running = False` |
**Atomicité « rattachement + fin d'exécution » (ferme un MAJOR de revue)** : en V1, le rattachement
d'une preuve et `running = False` sont une seule écriture (`gate_v_campaign.py` phases WF/MC/PS) ; les
commandes `Attach…` de V2 **effacent `running` dans la même écriture**. Aucun état « preuves complètes
rattachées et `running` vrai » n'est donc atteignable par l'API. (`SetRunning(True)` précède chaque phase
coûteuse ; `SetRunning(False)` ne sert qu'à un arrêt coopératif sans nouvelle preuve.)
**Ce que valide un rattachement (ferme un MAJOR de revue — pas d'impasse d'adoption)** : une preuve est
rattachable si elle est **structurellement valide et « scoped »** (type, identifiant déterministe,
provenance campagne, `status == "completed"`, `INCONCLUSIVE`, spécification cohérente — 21.6 « preuve
scoped »). **La qualité/complétude n'est PAS une condition de rattachement** : elle relève de la
dérivation du statut. Un Parameter Stability de qualité insuffisante (V1 le persiste) est donc
rattachable et rend `EVIDENCE_INCOMPLETE`, il ne bloque ni l'adoption ni la reprise. Une preuve
structurellement invalide ou étrangère reste une erreur fermée. Les producteurs de preuves (tranche
d'exécution V2) reprennent la règle V1 : ne persister une run WF/MC que complète.
Chaque commande est **idempotente** : même valeur → aucune écriture, `manifest_revision` inchangé ;
valeur différente sur un champ déjà renseigné → `ManifestTransitionError`, rien d'écrit. Aucune
commande n'efface ni ne modifie une référence ; aucune commande ne sort de `TECHNICAL_FAILURE`
(terminal : un éventuel mécanisme de reprise auditée serait une décision future, hors Slice D).
Après application, le Manifest candidat est validé (structure, liaison au plan), **les preuves
référencées sont rechargées** (21.6), le statut est dérivé, et seulement alors persisté.

**Concurrence — le faux compare-and-swap, identifié et corrigé (MAJOR fermé)**. Une version antérieure
de cette Décision présentait `manifest_revision` + `save_atomic_overwrite()` comme un compare-and-swap
atomique. **C'était faux.** Le code réel de `save_atomic_overwrite()` (`atomic_json_store.py`) garantit
seulement « écriture complète du fichier temporaire + `os.replace()` atomique » : il ne lie PAS
atomiquement `lecture de la révision N` + `condition révision == N` + `écriture de la révision N+1`.
**TOCTOU documenté** : deux processus peuvent lire la même révision N, passer chacun leur contrôle, puis
réussir chacun leur `os.replace()` — le dernier gagne silencieusement et peut effacer une référence de
preuve ou un marqueur d'exécution rattaché par l'autre. Un contrôle de révision effectué avant
l'écriture n'est donc **jamais suffisant** ; `manifest_revision` n'est pas un primitif d'exclusion.

**Mécanisme retenu : verrou transitoire V2** `<campaign_dir>/manifest.update.lock`, acquis par
```
os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
```
(même primitive indivisible que la Décision 9 : `CreateFileW(CREATE_NEW)` sous Windows, `open(2)` avec
`O_EXCL` sous POSIX). Il protège **exclusivement** la transaction de mise à jour du Manifest.
**Séquence normative, dans cet ordre exact** :
1. tenter l'acquisition exclusive de `manifest.update.lock` ;
2. si `FileExistsError` → **échec fermé**, aucune mise à jour, **aucun retry automatique** (l'appelant
   décide) ; **tout autre `OSError` à l'étape 1** (sous Windows, un fichier de verrou en suppression en
   attente tenu par un antivirus/indexeur lève `PermissionError`, pas `FileExistsError`) = **même échec
   fermé** (`ManifestLockAcquisitionError`), aucune écriture ; **dans tous les cas où l'étape 1 n'a pas
   abouti, le verrou existant n'est JAMAIS supprimé** (il appartient à un autre processus) ;
2 bis. (propriétaire seulement) écrire le contenu informatif du verrou ; un échec ici est une sortie
   avant l'étape 9 (le propriétaire libère, voir règles de libération) ;
3. **recharger `manifest.json` SOUS le verrou** (chargeur pur + liaison au plan) ;
4. comparer `expected_revision` à la `manifest_revision` **rechargée sous le verrou** — la valeur qui
   fait foi est celle relue APRÈS l'acquisition, jamais une lecture antérieure ; écart →
   `ManifestTransitionError`, **sans correction ni rebase automatique** ;
5. **revalider la commande demandée contre le Manifest réellement rechargé** (préconditions du tableau
   ci-dessus, « sans échec » incluant l'existence de la sentinelle) ;
6. recharger et revalider les preuves nécessaires (21.6) ;
7. calculer le nouveau Manifest et son statut dérivé (`marker_status`) ;
8. `manifest_revision = revision_rechargée + 1` (une commande idempotente sans changement n'écrit rien :
   étape 9-10 sautées, `manifest_revision` inchangée) ;
9. `save_atomic_overwrite(manifest.json)` ;
10. relire le résultat persisté et vérifier qu'il est valide et égal au Manifest voulu ;
11. fermer le descripteur puis supprimer `manifest.update.lock` (sous Windows un fichier ouvert ne se
    supprime pas : fermeture d'abord).
**Propriété et libération du verrou (ferme un MAJOR de revue)** :
- **Seul le processus qui a acquis le verrou à l'étape 1 le libère.** Un processus qui a reçu
  `FileExistsError` (ou tout autre `OSError`) à l'étape 1 ne touche jamais au verrou existant.
- **Avant tout `unlink`**, le propriétaire vérifie que le fichier au chemin est bien celui qu'il a
  créé — comparaison d'identité du fichier (`os.stat(path)` contre `os.fstat(fd)` : périphérique et
  numéro d'inode/index), **jamais du contenu**. Si l'identité a changé (verrou renommé par une récupération
  manuelle puis ré-acquis par un autre), il ne supprime rien.
- Toute sortie du propriétaire **avant l'étape 9** (refus, erreur gérée, idempotence sans écriture,
  échec de l'étape 2 bis) **libère** son verrou : il sait que le Manifest est inchangé. Un Manifest
  absent ou tronqué au chargement de l'étape 3 est un refus fermé *avant l'étape 9* : le verrou est libéré.
- **Exception à l'étape 9 (ferme un MAJOR de revue — collision Windows)** : `save_atomic_overwrite()` ne
  modifie la cible que par `os.replace()` ; sous Windows, un lecteur (antivirus, indexeur, simple lecture
  d'état) qui tient le Manifest ouvert peut faire échouer ce remplacement par `PermissionError` sans que
  rien ne soit écrit. Règle : **relire le Manifest sous le verrou**. S'il est identique à l'ancien →
  rien n'a été écrit : **libérer** et lever `ManifestWriteError` (« refus, rien d'écrit » ; jamais un
  retry automatique) ; s'il est égal au nouveau → **c'est un succès**, poursuivre aux étapes 10-11 ; **sinon, ou
  si la relecture échoue, conserver le verrou** et lever `ManifestWriteUncertainError` (état incertain,
  échec fermé). Un échec à l'étape 10 après un remplacement abouti suit la même règle (relecture ; sinon
  conservation).
- **Échec du `unlink` à l'étape 11** (ex. `PermissionError` sous Windows) **après** un remplacement
  vérifié : la transaction est **validée** (Manifest à la nouvelle révision) mais le verrou reste
  résiduel ; l'API lève `ManifestLockReleaseError(committed=True)`, **distincte d'un refus**, pour que
  l'appelant ne croie jamais « rien n'a été écrit ». Une **nouvelle tentative bornée de son propre
  `unlink`, par le seul propriétaire, avec la vérification d'identité ci-dessus**, est permise ; ce n'est
  **pas** un nettoyage de verrou périmé (aucun autre processus, aucune attente d'un délai, aucune
  décision fondée sur le contenu) ; si elle échoue, le verrou reste résiduel (récupération manuelle).
- **Exceptions typées, jamais confondues** : « refus, rien d'écrit » (`FileExistsError` verrou occupé,
  `ManifestLockAcquisitionError`, `ManifestTransitionError`, `ManifestWriteError`) ; « validé, verrou résiduel »
  (`ManifestLockReleaseError`, `committed=True`) ; « incertain » (`ManifestWriteUncertainError`). Un
  crash dur ne libère rien. Contenu du verrou : informatif et non autoritatif (nom de la commande,
  `campaign_id`, `expected_revision`, **sans horodatage**), jamais lu pour décider.
**Verrou consultatif** : il n'exclut que les écrivains qui passent par l'API ; un écrivain hors API
(édition manuelle) est hors modèle de menace et n'est détecté qu'au chargement suivant (validation
stricte, statut recalculé). La **création initiale** (`save_exclusive`) se fait hors verrou : une mise à
jour qui trouve le Manifest absent ou tronqué échoue fermée (avant l'étape 9).
**Aucun stale-lock automatique — interdit** : ni expiration par délai, ni suppression par âge du
fichier, ni suppression parce qu'un PID n'existe plus, ni retry automatique. Un verrou résiduel signifie
« **état d'écriture incertain** » et reste fermé tant qu'une personne n'a pas tranché.
**Récupération manuelle gouvernée d'un verrou résiduel** (jamais automatisée ; un protocole de
récupération audité complet est un futur ticket, non conçu ici) : décision humaine explicite ; vérifier
qu'aucun écrivain n'est vivant ; inspecter `manifest.json` (valide ? `manifest_revision` ? cohérent avec
les preuves ?) ; **renommer** le verrou (`manifest.update.lock.recovered.<n>`), jamais le supprimer, et
consigner la décision. Le renommage utilise `os.rename` (jamais `os.replace`, qui écraserait) vers un
nom `<n>` unique, et **refuse** si la cible existe déjà.
**Lecteurs** : les chargeurs et les vérifications de preuves ne prennent jamais le verrou (le
remplacement est atomique : ils voient l'ancien ou le nouveau Manifest complet) ; un verrou résiduel ne
bloque donc pas les lectures — mais la précondition du Claim exige son **absence** (21.7). Les lecteurs
n'excluent pas pour autant l'écrivain à l'échelle du système de fichiers : sous Windows, un lecteur qui
tient le fichier ouvert peut faire échouer l'étape 9, cas traité par la règle ci-dessus (relecture, puis
libération si rien n'a été écrit).

**Rôle exact de `manifest_revision`** : détection optimiste d'écriture périmée, audit des transitions
(chaque mise à jour effective la fait avancer de 1) et monotonie logique. **Ce n'est PAS le primitif
d'exclusion** ; l'exclusion est le verrou `O_EXCL`. Sous verrou, `expected_revision` ≠ révision
persistée → `ManifestTransitionError` ; l'appelant recharge et rejoue (commandes idempotentes).
**`expected_revision` est obligatoire dans la signature de TOUTE commande** (y compris `Start` et
`SetRunning`) ; une commande idempotente portant une révision périmée est refusée à l'étape 4 (cohérent
avec S1) : l'appelant recharge puis rejoue. **Point de linéarisation** d'une commande : l'étape 5
(revalidation sous verrou) ; une sentinelle créée après cette étape mais avant l'étape 9 laisse la
commande aboutir, sans perte du fait (`effective_status` prime) ; la future tranche du Claim **revérifie
la sentinelle après l'acquisition du Claim et avant toute lecture de marché** (Décision 11, étape 8).
**Garanties monotones conservées sous le verrou** : aucune référence déjà renseignée n'est supprimée ni
remplacée par un autre identifiant ; `Attach…` et `running = False` sont une seule nouvelle version du
Manifest ; `TECHNICAL_FAILURE` est terminal ; les champs `FINAL_HOLDOUT` réservés restent `None`.

**`manifest.update.lock` n'est PAS un `FinalHoldoutAccessClaim`** (distinction absolue, voir aussi 21.10) :
le verrou **sérialise temporairement une mise à jour factuelle mutable** ; le Claim **consomme
définitivement le droit scientifique d'accéder au `FINAL_HOLDOUT`**. Le verrou est normalement
**supprimé** après une transaction réussie ; le Claim ne l'est **jamais**. Aucun verrou de Manifest ne
permet, n'autorise ni ne déclenche un accès marché, et sa présence ou son absence n'est jamais une preuve
d'un accès `FINAL_HOLDOUT`.

**Résiduel distinct, hors Manifest (MINOR)** : la **production** concurrente d'une même preuve par deux
orchestrateurs n'est pas protégée par ce verrou (`save_validation_run()` s'appuie sur `save_atomic()`,
TOCTOU documenté) — identique à V1 ; la correction scientifique du Manifest **ne dépend plus** du contrat
« un seul orchestrateur par campagne », qui reste une recommandation opérationnelle ; la future tranche
d'exécution V2 pourra fermer ce résiduel (bail d'exécution exclusif) — non conçu ici.

**Sentinelle d'échec technique (conservée après l'introduction du verrou ; rôle précisé)** : le verrou
ferme la perte de mise à jour du Manifest, mais un verrou **résiduel** bloque toute mutation du Manifest
alors qu'un échec technique doit rester **enregistrable** et qu'il conditionne le Claim (21.7). La
sentinelle est donc un fait exclusif **indépendant du verrou**. Sa persistance passe par `save_exclusive()`
de `<campaign_dir>/technical_failure.json` (contenu : version sémantique, `campaign_id`, `reason` ; pas
de timestamp), **avant** de tenter d'acquérir le verrou et de mettre à jour le Manifest, **et seulement si
une lecture non verrouillée montre `execution_started = True`** (marqueur monotone, donc sûr : sans cette
condition une sentinelle posée sur une campagne non démarrée serait irréconciliable) ; si l'acquisition
du verrou échoue (`FileExistsError`), la sentinelle reste et le Manifest est simplement « en retard ».
Règles exactes :
- **Existence = le fait.** Le contenu n'est pas nécessaire au fait : une sentinelle **illisible ou
  tronquée** (crash entre `O_EXCL` et l'écriture complète) compte quand même comme échec technique
  (`effective_status = TECHNICAL_FAILURE`) ; jamais supprimée ni réparée automatiquement. Sa `reason`
  est alors la chaîne fixe `"technical_failure_sentinel_unreadable"` pour toute réconciliation.
- **Sentinelle présente + marqueur absent du Manifest** = état « en retard » **légal et chargeable**
  (21.5 : `status == marker_status`) ; la seule transition admissible est `MarkTechnicalFailure` avec la
  `reason` de la sentinelle (lisible, ou la chaîne fixe ci-dessus), qui constate la sentinelle sans la
  réécrire puis met à jour le Manifest.
- **Seconde `MarkTechnicalFailure` avec une `reason` différente** : `FileExistsError` à la création
  de la sentinelle → la sentinelle existante gagne (« premier échec conservé ») ; la commande échoue avec
  `ManifestTransitionError` si la `reason` diffère, et est idempotente si elle est identique.
- Manifest et sentinelle ne peuvent pas diverger durablement sur la `reason` : si le Manifest porte un
  `technical_failure_reason` différent de la sentinelle lisible, la vérification des preuves refuse
  (fermé) — **sauf** si le Manifest porte la chaîne fixe `"technical_failure_sentinel_unreadable"` (la
  sentinelle était illisible au moment de la réconciliation, par exemple une lecture transitoire
  bloquée par un antivirus) : cette valeur est tolérée et n'est jamais réécrite.
La sentinelle prime sur le Manifest pour `effective_status` et donc pour la précondition 21.7.

**Matrice de crash / reprise** (mission §11 et §14) :
| Cas | Conséquence |
|---|---|
| Crash avant la persistance d'une preuve | Rien d'écrit ; la reprise recalcule (checkpoints WF, ADR 0024 D8) |
| Preuve persistée (`save_atomic`, atomique), crash avant rattachement | Preuve orpheline, Manifest **en retard** : légal. **Adoption** à la reprise : recharger, valider structure + « scoped » (**pas** la qualité, voir « Ce que valide un rattachement »), puis `Attach…` (qui efface `running`) ; jamais de recalcul ; une preuve orpheline structurellement invalide/étrangère → erreur fermée |
| **Crash avant acquisition du verrou** | Aucun effet ; nouvelle tentative possible |
| **Crash après acquisition du verrou, avant toute modification** | `manifest.update.lock` **reste présent** : échec fermé pour toute nouvelle mutation, **aucune suppression automatique**, récupération manuelle gouvernée |
| **Crash pendant `save_atomic_overwrite`** (fichier temporaire + `os.replace`) | Manifest = ancien complet OU nouveau complet, **jamais partiellement remplacé** ; fichiers `*.tmp` orphelins jamais lus ; le verrou résiduel bloque toute nouvelle mutation automatique |
| **Crash après écriture du Manifest, avant suppression du verrou** | Manifest possiblement correctement avancé, verrou présent : échec fermé ; inspection/récupération manuelle uniquement (21.8 « récupération manuelle gouvernée ») |
| **Deux écrivains simultanés** | Un seul acquiert le verrou ; le second reçoit `FileExistsError` ; **aucun last-write-wins silencieux** |
| Crash après sentinelle, avant marqueur | Voir sentinelle : état en retard légal et chargeable, réconcilié par `MarkTechnicalFailure` (une fois le verrou libre) |
| `running = True` figé après crash dur | Légal : `running` n'est jamais une preuve de vivacité. **Action de reprise définie** : pour chaque phase WF, puis MC, puis PS par fold : si la preuve canonique existe → adoption (`Attach…`, efface `running`) ; sinon recalcul. Quand plus aucune phase n'est manquante, `running` est déjà faux (les `Attach…` l'ont effacé) |
| Création initiale tronquée (crash entre `O_EXCL` et l'écriture) | Illisible → **refus fermé**, jamais traité comme absent. Un Manifest initial tronqué rend le scope inutilisable (plan et PreRegistration sont exclusifs) : **récupération manuelle gouvernée** — décision humaine explicite, uniquement si `validations/` ne contient aucune preuve et qu'aucune sentinelle n'existe ; le fichier est **renommé** (`manifest.json.corrupt.<n>`, jamais supprimé), puis le Manifest initial est recréé par `save_exclusive()` ; jamais automatisé. Durcissement possible non retenu : écriture complète puis `os.link` (nouvelle primitive, support filesystem non vérifié, discipline Décision 9) |
| Manifest **plus avancé** que les preuves réelles | **Erreur fermée** (référence vers preuve absente/étrangère, ou statut ≠ dérivé) — jamais corrigé silencieusement |
| Réexécution de l'orchestrateur sur campagne `EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT` | Dérivation = complète, `running` faux → aucune phase relancée, commandes idempotentes |
| Technical failure | **Terminal, accepté par l'utilisateur (2026-10-06)** ; preuves déjà rattachées conservées ; relance automatique interdite (« reprise manuelle requise », comme V1) ; **aucun mécanisme de retry n'est conçu ni autorisé dans Slice D** ; un scope devenu inutilisable après échec technique est un comportement conservateur accepté tant qu'un protocole de reprise auditée n'est pas formellement spécifié |
**Principe** : les preuves persistées restent la source factuelle ; le Manifest n'est qu'un index
monotone derrière elles. Un Manifest en retard est sûr (la dérivation le répare par adoption) ; un
Manifest en avance est une erreur.

### 21.9 — Discrimination V1 / V2 : algorithme exact

Fonction pure de classification (lecture seule, ne valide pas le contenu scientifique) :
`classify_gate_v_campaign_dir(campaign_dir) -> "v1" | "v2"`, sinon `GateVCampaignDiscriminationError`
(sous-classe de `ValueError`). **Jamais par le nom du dossier comme discriminant** (il n'est qu'un test
de cohérence) ; **jamais de repli** : un V2 malformé n'est jamais lu comme V1.
```
1. plan.json : absent, illisible, JSON invalide ou non-objet            -> erreur
2. "campaign_plan_semantics_version" absente                           -> plan_kind = "v1"
   valeur == "gate_v_campaign_plan_v2"                                  -> plan_kind = "v2"
   toute autre valeur (y compris None, v3, v1 explicite)                -> erreur (fail closed)
3. campaign_id du plan : str ; forme V1 `gate_v_[0-9a-f]{64}` ssi v1,
   forme V2 `gate_v_v2_[0-9a-f]{64}` ssi v2 ; nom du dossier == campaign_id -> sinon erreur
4. manifest.json absent                                                 -> retourner plan_kind
   illisible / non-objet                                                -> erreur
5. "manifest_semantics_version" absente -> manifest_kind = "v1"
   == "gate_v_campaign_manifest_v2"     -> manifest_kind = "v2"
   autre valeur                          -> erreur
6. manifest_kind != plan_kind                                           -> erreur (état hybride)
   manifest.campaign_id != campaign_id du plan                          -> erreur
7. retourner plan_kind
```
Le résultat sélectionne le chargeur strict correspondant (V1 : chargeurs existants, inchangés ; V2 :
chargeurs de Slice C et D). Les formes d'identifiant `gate_v_<64 hex>` et `gate_v_v2_<64 hex>` sont
mutuellement exclusives (le segment `v2_` n'est pas hexadécimal), donc un identifiant ne peut être lu
dans l'autre espace.

### 21.10 — Le Manifest n'est JAMAIS le verrou `FINAL_HOLDOUT`

Règle absolue (Décision 9, répétée ici pour être impossible à mal comprendre) :
- **L'autorité unique d'exclusivité est `FinalHoldoutAccessClaim` créé par `os.open(O_CREAT|O_EXCL)`**
  (Décisions 9-11). Le Manifest, quel que soit son contenu, **n'accorde, ne refuse et ne consomme
  aucun droit d'accès**.
- `EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT` est une **précondition nécessaire** du Claim, jamais un
  droit : deux processus voyant ce statut ne sont départagés que par le `O_EXCL` du Claim.
- Les champs 13-17 sont, quand ils seront autorisés, un **miroir d'audit écrit APRÈS** la réussite du
  Claim (jamais avant, jamais comme condition) ; leur absence ou leur divergence n'ouvre ni ne ferme
  aucun accès ; seule une divergence avec le fichier de claim déclenche une erreur d'audit (tranche
  future).
- **`manifest.update.lock` n'est pas un Claim** (21.8) : il sérialise temporairement une mise à jour
  factuelle mutable et est normalement supprimé ; le Claim consomme définitivement le droit d'accès et
  n'est jamais supprimé ; aucun verrou de Manifest ne permet ni ne déclenche un accès marché ; après
  toute opération de Slice D, aucun fichier de Claim n'existe.
- Le module Manifest V2 n'importe pas le module du Claim, ne définit aucune primitive exclusive de
  claim, ne lit aucune donnée de marché, n'utilise jamais `save_atomic_overwrite()` pour un fait
  irréversible de `FINAL_HOLDOUT`. Tests structurels (imports AST, absence de champ booléen
  « holdout accessible », absence de statut contenant `CLAIM` ou `HOLDOUT` autre que
  `EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT`) en Slice D.

### 21.11 — Intégration avec AF-V-08 (`gate_v_campaign.py` V1) : options comparées

| Option | Verdict |
|---|---|
| a — extension minimale de l'orchestrateur V1 (branches V2 dans `gate_v_campaign.py`) | **Rejetée** : touche un module intégré, gelé ; `isinstance` V1 partout ; risque de dérive de V1 |
| **b — nouveaux modules V2 additifs** | **Retenue** |
| c — façade d'**exécution** unifiée (`execute_gate_v_campaign(plan_any)`) | **Rejetée pour l'instant** : masquerait la différence scientifique (OOS-first vs `FINAL_HOLDOUT` dernier) derrière un seul appel — risque de mélange silencieux. L'exécution V2 sera un module séparé dans une tranche ultérieure |
| **d — façade de classification en lecture seule** | **Retenue** (21.9) : réduit six combinaisons de versions à une fonction ; test de suppression : sans elle chaque appelant dupliquerait l'algorithme |
Modules (sans cycle ; **aucun n'importe `gate_v_campaign.py`**) :
```
gate_v_evidence_completeness_v2.py   # pur : prédicats de 21.6 sur Plan V2 + ValidationRun, retourne des faits
gate_v_campaign_manifest_v2.py       # type, identifiant déterministe des preuves, structure, liaison au plan,
                                     # dérivation du statut, commandes, création, mise à jour sous verrou
                                     # transitoire `manifest.update.lock`, sentinelle d'échec technique,
                                     # vérification des preuves, précondition 21.7
gate_v_campaign_dispatch.py          # classification 21.9, lit uniquement des clés JSON
```
Dépendances : `dispatch` ne dépend d'aucun module scientifique ; `manifest_v2` dépend de
`completeness_v2`, `gate_v_campaign_plan_v2`, `validation_run`, `atomic_json_store` — **et de rien
d'autre** (ni PreRegistration, ni ResearchRun, ni split, ni policy, ni Git : la revalidation du Plan V2
aux sources est une obligation de l'appelant, 21.7) ; V1 ne dépend de rien de V2.
**Précision (D1, 2026-10-07)** : « et de rien d'autre » désigne les **imports DIRECTS** de
`gate_v_campaign_manifest_v2.py` ; il ne réinterprète pas la fermeture transitive du graphe d'import
(`gate_v_campaign_plan_v2` importe déjà PreRegistration, ResearchRun, split, policy…), et il ne prescrit
pas la liste des imports directs de `gate_v_evidence_completeness_v2.py`. Ce dernier peut appeler des
helpers **purs** existants nécessaires à la vérification d'une preuve — notamment
`walk_forward.build_aggregate_result()` — sans exécuter de Walk-Forward ni faire d'I/O ; aucun module V2
n'importe `gate_v_campaign.py`.
**Décision de duplication — VALIDÉE par l'utilisateur (2026-10-06)** : **les prédicats WF/MC/PS V2
sont réimplémentés additivement dans le module V2** (`gate_v_evidence_completeness_v2.py`), **sans
modifier `gate_v_campaign.py`**, avec des **tests différentiels V1/V2** qui verrouillent l'équivalence
là où les contrats sont communs (mêmes `ValidationRun` synthétiques jugées par les prédicats V1 et V2 :
résultats ET exceptions égaux). Raisons : V1 est stable, intégré et son comportement historique doit
rester identique à l'octet ; une extraction toucherait inutilement `gate_v_campaign.py` ; V2 peut
légitimement diverger plus tard ; la duplication contrôlée et testée est acceptée (MINOR assumé).
**L'extraction des helpers privés V1 n'est plus proposée comme choix par défaut** ni comme alternative
active de cette spec.

### 21.12 — Revue adversariale (résolue dans cette spec avant tout code)

| # | Scénario | Classe | Fermeture |
|---|---|---|---|
| 1 | Plan V1 présenté comme V2 | — | `campaign_plan_semantics_version` absente → refusé par le chargeur V2 (Décision 20.6) ; classification : `v1` |
| 2 | Plan V2 présenté comme V1 | — | le chargeur V1 reconstruit via `build_gate_v_campaign_plan` : clé inconnue/comparaison `record != _plan_record` → refus ; classification : `v2` jamais `v1` |
| 3 | Sémantique inconnue (plan ou manifeste) | — | erreur fermée à 21.9 pas 2 et 5 |
| 4 | Manifest d'une autre campagne | — | `campaign_id` recalculé depuis `{constante de version du Plan V2, preregistration_id, fingerprint}` (le Manifest ne porte pas `campaign_plan_semantics_version` ; la constante est impliquée par `manifest_semantics_version`) + égalité avec le plan + nom de dossier |
| 5 | `campaign_id` falsifié | — | barrière 2 interne sur le Manifest (même fonction `compute_gate_v_campaign_id_v2` que le Plan V2) |
| 6 | `preregistration_id` falsifié | MAJOR de Slice C, déjà fermé | idem 5 : le `campaign_id` recalculé diverge |
| 7 | Preuve WF étrangère | — | identifiant déterministe + provenance scoped (21.6) |
| 8 | Preuve MC étrangère | — | idem + provenance = run WF de la campagne |
| 9 | Preuve PS d'un fold étranger | — | fold ∉ `expected_fold_ids` → erreur ; id ≠ déterministe → erreur |
| 10 | Fold attendu absent | — | PS/WF incomplet → `EVIDENCE_INCOMPLETE`, jamais complet |
| 11 | `TECHNICAL_FAILURE` ignoré | **MAJOR** | marqueur **et** sentinelle exclusive ; terminal ; précondition 21.7 pas 4 (`effective_status`) |
| 12 | Manifest complet sans preuve | — | preuves rechargées du disque ; référence absente = erreur ; statut ≠ dérivé = erreur |
| 13 | Deux workers mettent à jour | **MAJOR — FERMÉ** | création exclusive (`save_exclusive`) ; **mises à jour sous `manifest.update.lock` (`O_CREAT|O_EXCL`)** avec rechargement et contrôle de révision SOUS le verrou ; commandes idempotentes ; sentinelle d'échec indépendante du verrou ; replay détaillé ci-dessous (S1-S8). Le faux « compare-and-swap » `manifest_revision` + `save_atomic_overwrite()` est supprimé (finding 31) |
| 14 | Crash entre preuve et mise à jour | — | Manifest « en retard » légal, adoption à la reprise (matrice 21.8) |
| 15 | Claim ajouté à la main | **MAJOR** | champs 13-17 forcés `None` en Slice D ; extension monotone future avec vérification contre le claim |
| 16 | OOS référencée avant WF/MC/PS | — | `oos_evidence_validation_run_id` réservé `None` ; le Plan V2 n'en porte pas ; aucun statut V2 n'a besoin d'OOS |
| 17 | V1 cassé par les nouveaux chargeurs | — | aucun fichier V1 modifié ; les chargeurs V2 sont additifs ; tests V1 inchangés verts ; la classification ne remplace aucun chargeur |
Autres findings : (18) **MAJOR** — les prédicats V1 sont privés et un verrou `isinstance` les lie au
type V1 : pas de réutilisation sans coupler V2 à V1 ou toucher V1 → 21.11 ;
(19) **MAJOR** — `EVIDENCE_COMPLETE_AWAITING_POLICY` serait faux en V2 (OOS-first) → statut dédié 21.5 ;
**Findings de la revue adversariale indépendante de cette Décision (2026-10-06), tous fermés dans le
texte ci-dessus** : (20) **MAJOR** — sentinelle « en avance » à la fois légale et refusée par l'égalité
statut persisté = statut dérivé → séparation `marker_status` / `effective_status` (21.5) + règles de
sentinelle illisible/`reason` divergente/seconde marque (21.8) ; (21) **MAJOR** — V1 rattache la preuve
et efface `running` en une seule écriture, V2 le scindait → `Attach…` efface `running` dans la même
écriture + action de reprise définie (21.8) ; (22) **MAJOR** — adoption impossible d'un Parameter
Stability de qualité insuffisante (V1 le persiste, refus d'écrasement) → un rattachement ne vérifie
que structure + « scoped », la qualité relève de la dérivation (21.8) ; (23) **MAJOR** — la précondition
21.7 n'avait ni signature ni dépendances → `assert_gate_v_pre_holdout_evidence_complete(plan, campaign_dir)`,
revalidation aux sources = obligation de l'appelant (21.7, 21.11).
(31) **MAJOR — FERMÉ (2026-10-06, revue de l'utilisateur)** : `manifest_revision` +
`save_atomic_overwrite()` **n'est pas** un compare-and-swap inter-processus atomique (TOCTOU : lecture N,
contrôle, écriture N+1 non liés atomiquement ; deux `os.replace()` peuvent réussir) → verrou transitoire
`manifest.update.lock` (`O_CREAT|O_EXCL`), séquence en 11 étapes avec rechargement et contrôle de
révision sous verrou, aucun stale-lock automatique, matrice de crash dédiée (21.8) ; **(32) MAJOR —
FERMÉ (revue indépendante du contrat de verrou)** : propriété du verrou (le perdant de l'étape 1 ne le
supprime jamais ; vérification d'identité de fichier avant `unlink`) ; **(33) MAJOR — FERMÉ** : collision
Windows à l'étape 9 (un lecteur peut faire échouer `os.replace`) → relecture sous verrou : rien d'écrit
= libération, remplacement abouti = succès, sinon verrou conservé ; **(34) MAJOR — FERMÉ** : échecs
Windows de l'étape 1 (`PermissionError`) et de l'étape 11 (`unlink`), exceptions typées distinctes
(refus / validé-verrou-résiduel / incertain). MINOR traités : verrou consultatif, création initiale hors
verrou, condition `execution_started` pour la sentinelle, tolérance de la raison « sentinelle illisible »,
point de linéarisation à l'étape 5, `expected_revision` obligatoire partout, récupération par `os.rename`.
Le finding
« fenêtre résiduelle / contrat un seul orchestrateur » n'est plus MINOR : il est **MAJOR fermé** et la
correction ne dépend plus de ce contrat.
MINOR : (24) `TECHNICAL_FAILURE` terminal peut rendre un scope inutilisable tant qu'aucune reprise
auditée n'est définie (**comportement conservateur ACCEPTÉ par l'utilisateur, 2026-10-06** ; aucun retry
conçu dans Slice D ; fail-closed, `FINAL_HOLDOUT` non consommé) ; (25) création initiale tronquée →
récupération manuelle gouvernée (21.8) ; (26) **production** concurrente d'une même preuve par deux
orchestrateurs via `save_atomic()` (TOCTOU documenté, résiduel V1 identique, **hors Manifest**, non
couvert par le verrou ; à fermer par la future tranche d'exécution V2) ; (26 bis) un verrou résiduel exige
une récupération manuelle gouvernée (coût opérationnel assumé, jamais d'auto-nettoyage) ;
(27) preuves orphelines non référencées ignorées (jamais
une autorité) ; (28) `ValidationRun` sans `preregistration_id` (21.6) ; (29) duplication des prédicats
V1/V2, verrouillée par un test différentiel ; (30) **longueur de chemin Windows** : un identifiant V2 fait
74 caractères (V1 : 71) ; le chemin relatif le plus long sous `<campaign_root>` est
`<id>/validations/<id>_parameter_stability_<fold>/validation_run.json`, soit ≈ 210 caractères (V1 ≈ 204) —
avec une racine `results/job_xxx/gate_v/campaigns/` usuelle, le total approche ou dépasse `MAX_PATH`
(260) sans support des chemins longs ; **risque préexistant en V1**, non aggravé de façon significative ;
l'implémentation ajoute un test sur le chemin le plus long avec une racine réaliste et documente la
dépendance aux chemins longs Windows. **BLOCKER : aucun. MAJOR : tous fermés par cette spécification.**

**Replay adversarial final du contrat de concurrence (après introduction du verrou)** :
| # | Scénario | Résultat sous le contrat 21.8 |
|---|---|---|
| S1 | Deux writers, même révision N, même transition | Un seul acquiert le verrou ; l'autre reçoit `FileExistsError` (aucun retry automatique). Si l'autre rejoue plus tard avec `expected_revision = N` : rechargé sous verrou = N+1 → `ManifestTransitionError` ; après rechargement par l'appelant, la commande idempotente est un no-op. Aucune référence perdue |
| S2 | Deux writers, transitions différentes (ex. `AttachMonteCarlo` et `AttachParameterStability`) | Un seul acquiert ; le second échoue fermé ; une fois le verrou libre il recharge et rejoue sa commande, valide sur l'état à jour : **les deux références coexistent**, aucun last-write-wins |
| S3 | Writer périmé (`expected_revision` ancienne) | Sous verrou : révision rechargée ≠ attendue → `ManifestTransitionError`, **pas de rebase**, verrou libéré (sortie avant l'étape 9) |
| S4 | Crash après acquisition du verrou | Verrou résiduel, Manifest inchangé : toute mutation échoue fermée ; lecteurs non bloqués ; la précondition 21.7 échoue (verrou présent) ; récupération manuelle gouvernée |
| S5 | Crash après écriture du Manifest, avant suppression du verrou | Manifest avancé et valide, verrou résiduel : même échec fermé ; l'inspection manuelle constate la révision N+1 cohérente avec les preuves |
| S6 | `MarkTechnicalFailure` concurrent à un `Attach…` | La sentinelle (indépendante du verrou) est créée ; si le verrou est pris par l'autre, la commande échoue (`FileExistsError`) mais **le fait est enregistré** : `effective_status = TECHNICAL_FAILURE`, précondition fermée même si toutes les preuves existent ; la réconciliation `MarkTechnicalFailure(reason sentinelle)` aligne le Manifest dès que le verrou est libre. Aucun chemin ne perd l'échec |
| S7 | Preuve persistée entre deux mises à jour | Elle n'est autorité qu'une fois rattachée : la mise à jour U1 n'en tient pas compte (Manifest « en retard », légal) ; U2 la rattache après validation structure + « scoped » sous verrou ; le statut ne dérive que des références |
| S8 | Claim ajouté manuellement | Champs 13-17 non nuls → refus du chargeur (y compris à l'étape 3 sous verrou) ; aucun fichier de Claim n'est créé par Slice D ; `manifest.update.lock` n'est pas un Claim |
**Aucun BLOCKER ni MAJOR ouvert.**

### 21.13 — Découpage TDD indicatif (tranches d'implémentation, chacune RED→GREEN→revue)

D1 `gate_v_evidence_completeness_v2` + test différentiel V1/V2 ; D2 type, constantes, liaison et
validation structurelle du Manifest V2 ; D3 dérivation de statut et commandes (pures) ; D4 création
exclusive, mise à jour sous verrou `manifest.update.lock`, sentinelle ; D5 vérification des preuves +
précondition 21.7 ; D6 `gate_v_campaign_dispatch`.
**Tests de concurrence et de crash exigés (contrat 21.8, non négociables)** — le test de concurrence
utilise **deux processus réels** (pas des threads, pas des mocks) synchronisés par une barrière, sur le
modèle du test à deux processus de Slice B :
1. deux processus réels tentent la même transition ;
2. exactement un acquiert `manifest.update.lock` ;
3. le second reçoit `FileExistsError` ;
4. aucune référence déjà persistée n'est perdue ;
5. `expected_revision` périmé sous verrou → `ManifestTransitionError` (pas de rebase) ;
6. crash simulé après acquisition → le verrou résiduel bloque toute mutation suivante ;
7. aucun auto-nettoyage du verrou (ni délai, ni âge, ni PID, ni retry) ;
8. verrou supprimé après une transaction normale ; verrou **libéré** sur toute sortie avant l'étape 9 et
   **conservé** sur une erreur pendant/après l'étape 9 ;
9. `manifest.update.lock` ne crée jamais de `FinalHoldoutAccessClaim` ;
10. aucun fichier de Claim n'existe après toutes les opérations de Slice D ;
11. la précondition 21.7 échoue tant que le verrou existe ; les lecteurs ne prennent jamais le verrou ;
12. deux transitions différentes simultanées : les deux références coexistent après rejeu (S2) ;
13. sentinelle créée même quand le verrou est occupé (S6), et seulement si `execution_started` est vrai ;
14. **le perdant ne supprime jamais le verrou du gagnant** (`FileExistsError` et autre `OSError` à
    l'étape 1) ; le propriétaire ne supprime pas un verrou dont l'identité de fichier a changé ;
15. `PermissionError` simulé à l'étape 9 : relecture, rien d'écrit → verrou libéré + `ManifestWriteError` ;
    remplacement abouti malgré l'exception → succès ; relecture impossible → verrou conservé +
    `ManifestWriteUncertainError` ;
16. `unlink` en échec à l'étape 11 après remplacement vérifié → `ManifestLockReleaseError(committed=True)`,
    jamais confondu avec un refus ; nouvelle tentative bornée du seul propriétaire ;
17. `OSError` non `FileExistsError` à l'étape 1 → échec fermé sans écriture ni suppression ;
18. `expected_revision` obligatoire pour toute commande, y compris idempotente (révision périmée refusée) ;
19. une commande `Attach…` qui franchit l'étape 5 avant une sentinelle concurrente aboutit sans perte du
    fait (`effective_status = TECHNICAL_FAILURE`).

Tests minimaux transverses (hors concurrence) : 17 champs exacts dans l'ordre ; champs
réservés refusés non nuls ; V1/V2 mutuellement refusés par les chargeurs ; aucun import de
`gate_v_campaign.py` ni du Claim ; aucun segment de statut dans `{PASS, FAIL, CHAMPION, OOS, VERDICT}`
(21.5) ; test du chemin relatif le plus long avec une racine réaliste (21.12 #30) ;
`gate_v_campaign.py` identique à `HEAD` ; suite V1 inchangée verte.
**Interdits dans Slice D** : `FinalHoldoutAccessClaim`, accès `FINAL_HOLDOUT`, `HoldoutAccessEvent` V2,
`ValidationAssessment`, `GateVPolicyAssessment`, exécution WF/MC/PS V2, policy concrète de seuils,
campagne réelle, Champion, modification de `gate_v_campaign.py`.

## Conséquences

- **État réel initial** : `AF-V-07` = **DESIGN ACCEPTED / READY FOR IMPLEMENTATION** (2026-09-29,
  au moment de l'acceptation V1-V7 de cette ADR). Aucune ligne de code Python, aucun test, aucune
  campagne réelle, aucun accès `FINAL_HOLDOUT` n'avait été produit par ce processus de conception.
  `AF-V-08` (ADR 0024) reste `DONE`, intégrée dans `master`. **`GATE V` reste NON PASSÉE** —
  aucune décision de cette ADR ne produit ni ne peut produire un verdict `PASS`/Champion.
- **Mise à jour (2026-09-29, additive, ne remplace pas ce qui précède)** : Slice A
  (`GateVValidationPolicyVersion`) et Slice B (`GateVPreRegistration`, provenance Git fail-closed,
  exclusivité atomique du scope) sont désormais **`INTEGRATED`** dans `master` (commits `bcee84e`
  puis `0f0df82`/`3bf1872`). Le contrat exact de Slice C (`GateVCampaignPlanV2`) est verrouillé par
  la Décision 20 ci-dessus — **`Slice C` = SPEC LOCKED, READY FOR IMPLEMENTATION uniquement après
  validation explicite de l'utilisateur** ; aucun code Slice C n'a été écrit par ce processus de
  conception. `GATE V` reste NON PASSÉE.
- **Mise à jour (2026-10-06, additive, ne remplace rien de ce qui précède)** : **`Slice C` =
  IMPLEMENTED + TESTED + INTEGRATED** dans `master` (commit
  `59dd901f74370bac96ba9564a4729347ba994d81`, parent `f1e39713d43479a0ed038c5652197a323d087cd2`,
  suite complète 1915/1915) ; la mention « SPEC LOCKED » ci-dessus décrit l'état à la date de la
  mise à jour précédente. Le contrat de la **Slice D** (`GateVCampaignManifestV2` / discrimination V1-V2)
  est verrouillé par la Décision 21 : **`Slice D` = SPEC LOCKED, NOT IMPLEMENTED**, implémentation
  uniquement après validation explicite de l'utilisateur. `AF-V-07` = IN PROGRESS, `AF-V-08` = DONE,
  `GATE V` NON PASSÉE, `FINAL_HOLDOUT` NON ACCÉDÉ.
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
